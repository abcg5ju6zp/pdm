from __future__ import annotations

import os
import shutil
from collections.abc import Iterable
from contextlib import AbstractContextManager
from functools import cached_property
from pathlib import Path
from typing import Any, ClassVar

from pdm.termui import logger


class CachedPackage:
    """A package cached in the central package store.
    The directory name is similar to wheel's filename:

        $PACKAGE_ROOT/<checksum[:2]>/<dist_name>-<version>-<impl>-<abi>-<plat>/

    The checksum is stored in a file named `.checksum` under the directory.

    Under the directory there could be a text file named `.referrers`.
    Each line of the file is a distribution path that refers to this package.
    *Only wheel installations will be cached*
    """

    cache_files: ClassVar[tuple[str, ...]] = (".lock", ".checksum", ".referrers")
    """List of files storing cache metadata and not being part of the package"""

    def __init__(
        self,
        path: str | Path,
        original_wheel: Path | None = None,
        target_path: str | Path | None = None,
    ) -> None:
        self.path = Path(os.path.normcase(os.path.expanduser(path))).resolve()
        self.original_wheel = original_wheel
        # When the package is still a staging candidate, ``path`` points at the
        # candidate directory while ``final_path`` is where it will be published
        # after validation. Both are identical for confirmed packages.
        self.final_path = (
            Path(os.path.normcase(os.path.expanduser(target_path))).resolve() if target_path else self.path
        )
        self._referrers: set[str] | None = None

    def lock(self) -> AbstractContextManager[Any]:
        import filelock

        return filelock.FileLock(self.path / ".lock")

    @cached_property
    def checksum(self) -> str:
        """The checksum of the path"""
        return self.path.joinpath(".checksum").read_text().strip()

    @cached_property
    def dist_info(self) -> Path:
        """The dist-info directory of the wheel"""
        from installer.exceptions import InvalidWheelSource

        try:
            return next(self.path.glob("*.dist-info"))
        except StopIteration:
            raise InvalidWheelSource(f"The wheel doesn't contain metadata {self.path!r}") from None

    def iter_record_entries(self) -> Iterable[tuple[Path, str, str]]:
        """Yield ``(absolute_path, hash_spec, size)`` triples parsed from RECORD.

        ``hash_spec`` and ``size`` are empty strings when not recorded.
        Raises :class:`FileNotFoundError` if the RECORD file is missing.
        """
        from installer.records import parse_record_file

        record_file = self.dist_info / "RECORD"
        rows = parse_record_file(record_file.read_text("utf-8").splitlines())
        for rel, hash_spec, size in rows:
            yield self.path / rel, hash_spec, size

    def is_complete(self) -> bool:
        """Structural validation: every path listed in RECORD exists on disk."""
        from installer.exceptions import InvalidWheelSource

        try:
            entries = list(self.iter_record_entries())
        except (OSError, ValueError, InvalidWheelSource):
            return False
        if not entries:
            return False
        return all(path.exists() for path, _hash, _size in entries if path.name != "RECORD")

    def verify_record_hashes(self) -> None:
        """Verify every hashed file against the RECORD digest.

        This is the strict validation run on a freshly extracted *candidate*
        so that a truncated extraction (disk full, killed process) is never
        promoted to the confirmed cache.
        """
        import base64
        import hashlib

        from installer.exceptions import InvalidWheelSource

        for path, hash_spec, _size in self.iter_record_entries():
            if not hash_spec or path.name == "RECORD":
                if not path.exists():
                    raise InvalidWheelSource(f"Missing file recorded in RECORD: {path}")
                continue
            algorithm, _, expected = hash_spec.partition("=")
            if not path.is_file():
                raise InvalidWheelSource(f"Missing file recorded in RECORD: {path}")
            digest = hashlib.new(algorithm)
            with path.open("rb") as fp:
                for chunk in iter(lambda: fp.read(65536), b""):
                    digest.update(chunk)
            # RECORD digests are urlsafe-base64 encoded without padding.
            encoded = base64.urlsafe_b64encode(digest.digest()).rstrip(b"=").decode("ascii")
            if encoded != expected:
                raise InvalidWheelSource(f"Hash mismatch for cached file {path}")

    @property
    def referrers(self) -> set[str]:
        """A set of entries in referrers file"""
        if self._referrers is None:
            filepath = self.path / ".referrers"
            if not filepath.is_file():
                return set()
            self._referrers = {
                line.strip()
                for line in filepath.read_text("utf8").splitlines()
                if line.strip() and os.path.exists(line.strip())
            }
        return self._referrers

    def add_referrer(self, path: str) -> None:
        """Add a new referrer"""
        path = os.path.normcase(os.path.expanduser(os.path.abspath(path)))
        referrers = self.referrers | {path}
        (self.path / ".referrers").write_text("\n".join(sorted(referrers)) + "\n", "utf8")
        self._referrers = None

    def remove_referrer(self, path: str) -> None:
        """Remove a referrer"""
        path = os.path.normcase(os.path.expanduser(os.path.abspath(path)))
        referrers = self.referrers - {path}
        (self.path / ".referrers").write_text("\n".join(referrers) + "\n", "utf8")
        self._referrers = None

    def cleanup(self) -> None:
        logger.info("Clean up cached package %s", self.path)
        shutil.rmtree(self.path)
