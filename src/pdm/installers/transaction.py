"""Atomic, journaled installation transactions.

A transaction stages every package -- files, generated console scripts and
distribution metadata -- into a shadow tree instead of touching the active
environment. The whole staged batch is validated (RECORD hashes, script
entry points, metadata readability and dependency closure) before anything
is published. Publication only performs per-file atomic renames on the same
filesystem, driven by a durable journal.

Failure, cancellation, a full disk or an aborted process never leave the
active environment half installed: the previous working set is restored and
every staging candidate is discarded. Confirmed package-cache entries are
only created from validated candidates and are never overwritten, so a
failed batch can not poison the cache. Retries deterministically continue
from, or re-execute, the steps that were never confirmed.
"""

from __future__ import annotations

import atexit
import contextlib
import errno
import hashlib
import json
import os
import shutil
import signal
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any

from pdm import termui
from pdm.environments import BaseEnvironment
from pdm.exceptions import InstallationError
from pdm.installers.uninstallers import NormalizedPath, StashedRemovePaths, renames
from pdm.utils import atomic_open_for_write, normalize_name

if TYPE_CHECKING:
    from importlib.metadata import Distribution

    from pdm.models.cached_package import CachedPackage
    from pdm.models.candidates import Candidate

STATE_STAGING = "staging"
STATE_COMMITTING = "committing"
STATE_COMMITTED = "committed"
STATE_ROLLED_BACK = "rolled_back"

STAGE_PREFIX = ".pdm-tx-"

# Schemes that wheel artifacts are actually published under.
_SCHEME_KEYS = ("purelib", "platlib", "scripts", "headers", "include", "data")


class InstallationAborted(InstallationError):
    """Raised when the process receives a termination signal during a sync."""


class StagedEnvironment(BaseEnvironment):
    """Proxy an environment while redirecting install schemes to a stage tree.

    Every real install directory is mapped to a stable per-directory slot
    below the transaction's staging root (identical directories, such as
    ``purelib`` and ``platlib``, share a slot). The interpreter, script kind
    and project are delegated untouched, so generated shebang lines already
    target the real environment.
    """

    def __init__(self, environment: BaseEnvironment, transaction: InstallTransaction) -> None:
        self._environment = environment
        self._transaction = transaction

    def get_paths(self, dist_name: str | None = None) -> dict[str, str]:
        real_paths = self._environment.get_paths(dist_name)
        return {key: self._transaction.map_dir(value) for key, value in real_paths.items()}

    def __getattr__(self, item: str) -> Any:
        return getattr(self._environment, item)


class InstallTransaction:
    """Stage, validate, commit and -- if needed -- roll back an install batch."""

    def __init__(self, environment: BaseEnvironment, ui: Any | None = None) -> None:
        self.environment = environment
        self.ui = ui or environment.project.core.ui
        paths = environment.get_paths()
        self.env_paths = {key: os.path.abspath(paths[key]) for key in _SCHEME_KEYS if key in paths}
        identity_src = json.dumps(self.env_paths, sort_keys=True)
        self.env_id = hashlib.sha1(identity_src.encode("utf-8")).hexdigest()[:16]
        self.tx_id = uuid.uuid4().hex[:12]
        prefix = Path(paths.get("prefix") or paths["data"])
        self.stage_root = prefix / f"{STAGE_PREFIX}{self.tx_id}"
        self.tree_root = self.stage_root / "tree"
        self.stash_root = self.stage_root / "stash"
        self.backup_root = self.stage_root / "backup"
        self.journal_path = environment.project.cache("install-tx") / f"{self.env_id}.json"
        self.state: str | None = None
        self.dir_map: dict[str, str] = {}  # stage slot id -> live directory
        self.operations: list[dict[str, Any]] = []
        self.events: list[dict[str, str]] = []
        self._jlock = threading.Lock()
        self._staged_env: StagedEnvironment | None = None
        self._finished = False
        self._atexit_registered = False
        self._saved_signals: dict[int, Any] = {}

    # ------------------------------------------------------------------ paths

    def map_dir(self, live_dir: str) -> str:
        """Return the staging slot for *live_dir*, creating the mapping once."""
        normalized = os.path.normcase(os.path.abspath(live_dir))
        with self._jlock:
            for slot_id, mapped in self.dir_map.items():
                if mapped == normalized:
                    return os.path.join(self.tree_root, slot_id)
            slot_id = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
            self.dir_map[slot_id] = normalized
            return os.path.join(self.tree_root, slot_id)

    @property
    def staged_environment(self) -> StagedEnvironment:
        if self._staged_env is None:
            self._staged_env = StagedEnvironment(self.environment, self)
        return self._staged_env

    def _staged_to_live(self, staged_path: str) -> str:
        normalized = os.path.normcase(os.path.abspath(staged_path))
        tree = os.path.normcase(os.path.abspath(self.tree_root))
        if normalized == tree or not normalized.startswith(tree + os.sep):
            return normalized
        parts = os.path.relpath(normalized, tree).split(os.sep)
        slot_id, rest = parts[0], parts[1:]
        try:
            live_dir = self.dir_map[slot_id]
        except KeyError:
            return normalized
        return os.path.normcase(os.path.join(live_dir, *rest))

    # ---------------------------------------------------------------- journal

    def _journal_payload(self) -> dict[str, Any]:
        return {
            "version": 1,
            "id": self.tx_id,
            "env_id": self.env_id,
            "created": datetime.now(timezone.utc).isoformat(),
            "state": self.state,
            "prefix": str(self.stage_root.parent),
            "stage_root": str(self.stage_root),
            "env_paths": self.env_paths,
            "dir_map": self.dir_map,
            "operations": self.operations,
            "events": self.events,
        }

    def _persist(self, copy_in_stage: bool = True) -> None:
        payload = self._journal_payload()
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with atomic_open_for_write(self.journal_path) as fp:
            json.dump(payload, fp, indent=2)
        if copy_in_stage:
            with contextlib.suppress(OSError):
                self.stage_root.mkdir(parents=True, exist_ok=True)
                with atomic_open_for_write(self.stage_root / "tx.json") as fp:
                    json.dump(payload, fp, indent=2)

    def begin(self) -> None:
        try:
            self.stage_root.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            shutil.rmtree(self.stage_root, ignore_errors=True)
            self.stage_root.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise InstallationError(
                f"Can't create staging directory {self.stage_root} for the atomic install: {e}. "
                "The target environment is not writable."
            ) from e
        for path in (self.tree_root, self.stash_root, self.backup_root):
            path.mkdir(exist_ok=True)
        self.state = STATE_STAGING
        self._persist()
        self._install_signal_handlers()
        if not self._atexit_registered:
            atexit.register(self._at_exit)
            self._atexit_registered = True

    def activate(self) -> contextlib.AbstractContextManager[Any]:
        return _TransactionContext(self)

    # ------------------------------------------------------------- signals

    def _install_signal_handlers(self) -> None:
        if not hasattr(signal, "SIGTERM"):
            return

        def handler(signum: int, frame: Any) -> None:  # pragma: no cover - signal path
            self.ui.echo(
                "\n[warning]Received termination signal, rolling back the unfinished installation...[/]",
                err=True,
            )
            self.request_abort(f"terminated by signal {signum}")

        with contextlib.suppress(ValueError):
            # Only works from the main thread; parallel workers stay untouched.
            previous = signal.signal(signal.SIGTERM, handler)
            self._saved_signals[signal.SIGTERM] = previous

    def _restore_signal_handlers(self) -> None:
        for sig, previous in self._saved_signals.items():
            with contextlib.suppress(ValueError):
                signal.signal(sig, previous)
        self._saved_signals.clear()

    def request_abort(self, reason: str = "aborted") -> None:
        """Roll back immediately (signal/atexit use) and raise to unwind."""
        if self._finished:
            return
        with contextlib.suppress(Exception):
            self.rollback(reason=reason)
        self._restore_signal_handlers()
        raise InstallationAborted(f"Installation {reason}, environment restored.")

    def _at_exit(self) -> None:  # pragma: no cover - interpreter shutdown
        if not self._finished and self.state in (STATE_STAGING, STATE_COMMITTING):
            with contextlib.suppress(Exception):
                self.rollback(reason="process exit")

    # ------------------------------------------------------------- staging

    def acquire_candidate(self, wheel: Path) -> CachedPackage:
        return self.environment.project.package_cache.acquire_candidate(wheel)

    def discard_attempt(
        self,
        sink: list[tuple[str, str, str]] | None,
        cached_package: CachedPackage | None,
    ) -> None:
        """Clean files of a staging attempt that never completed."""
        for _scheme, _rel, staged in sink or ():
            with contextlib.suppress(OSError):
                path = Path(staged)
                if path.is_symlink() or path.is_file():
                    path.unlink()
        if cached_package is not None and cached_package.path != cached_package.final_path:
            cached_package.cleanup()
            with contextlib.suppress(OSError):
                cached_package.path.with_suffix(".lock").unlink()

    def discard_op(self, op: dict[str, Any]) -> None:
        """Drop a registered operation and remove everything it staged."""
        sink = [
            ("", rel, os.path.join(self.tree_root, slot_id, *rel.split("/"))) for slot_id, rel in op.get("files", ())
        ]
        candidate = None
        if op.get("candidate"):
            from pdm.models.cached_package import CachedPackage

            with contextlib.suppress(Exception):
                candidate = CachedPackage(op["candidate"], target_path=op.get("cache_dest"))
        self.discard_attempt(sink, candidate)
        with self._jlock:
            with contextlib.suppress(ValueError):
                self.operations.remove(op)
            self._persist()

    def register_install(
        self,
        candidate: Candidate,
        staged_dist_info: str,
        sink: list[tuple[str, str, str]],
        cached_package: CachedPackage | None,
        extras: set[str] | None = None,
    ) -> dict[str, Any]:
        """Validate one staged package and journal it as a confirmed step."""
        op = self._build_op(candidate, staged_dist_info, sink, cached_package, extras or set())
        self._verify_package(op, sink)
        with self._jlock:
            self.operations.append(op)
            self._persist()
        return op

    def queue_update(self, op: dict[str, Any], live_dist: Distribution) -> None:
        """Mark a staged operation as an in-place update.

        The old distribution's files are only moved aside at commit time.
        """
        with self._jlock:
            op["kind"] = "update"
            op["old_dist_info"] = os.path.normcase(
                os.path.abspath(str(live_dist._path))  # type: ignore[attr-defined]
            )
            self._persist()

    def queue_remove(self, live_dist: Distribution) -> None:
        with self._jlock:
            self.operations.append(
                {
                    "kind": "remove",
                    "key": normalize_name(live_dist.metadata.get("Name")),
                    "old_dist_info": os.path.normcase(
                        os.path.abspath(str(live_dist._path))  # type: ignore[attr-defined]
                    ),
                }
            )
            self._persist()

    def _build_op(
        self,
        candidate: Candidate,
        staged_dist_info: str,
        sink: list[tuple[str, str, str]],
        cached_package: CachedPackage | None,
        extras: set[str],
    ) -> dict[str, Any]:
        tree_norm = os.path.normcase(os.path.abspath(self.tree_root))
        files: list[list[str]] = []
        for _scheme, rel, staged in sink:
            staged_norm = os.path.normcase(os.path.abspath(staged))
            slot = Path(staged_norm).relative_to(tree_norm).parts[0]
            files.append([slot, rel.replace(os.sep, "/")])
        live_dist_info = self._staged_to_live(staged_dist_info)
        return {
            "kind": "add",
            "key": candidate.identify(),
            "staged_dist_info": os.path.normcase(os.path.abspath(staged_dist_info)),
            "live_dist_info": live_dist_info,
            "files": files,
            "extras": sorted(extras),
            "candidate": (
                str(cached_package.path)
                if cached_package is not None and cached_package.path != cached_package.final_path
                else None
            ),
            "cache_dest": str(cached_package.final_path) if cached_package is not None else None,
        }

    # ------------------------------------------------------------ validation

    @staticmethod
    def _script_basenames(name: str) -> tuple[str, ...]:
        from pdm.installers.uninstallers import _script_names

        if os.name == "nt":
            return tuple({*_script_names(name, False), *_script_names(name, True)})
        return (name,)

    def _verify_package(self, op: dict[str, Any], sink: list[tuple[str, str, str]]) -> None:
        from importlib.metadata import Distribution

        staged_dist_info = op["staged_dist_info"]
        try:
            dist = Distribution.at(staged_dist_info)
            name = dist.metadata["Name"]
            version = dist.version
        except Exception as e:
            raise InstallationError(f"Invalid metadata staged for {op['key']}: {e}") from e
        if not name or not version:
            raise InstallationError(f"Staged metadata for {op['key']} is missing name or version")
        record_file = Path(staged_dist_info) / "RECORD"
        if not record_file.is_file():
            raise InstallationError(f"Staged package {name} {version} has no RECORD metadata")
        staged_scripts = {os.path.basename(staged) for scheme, _rel, staged in sink if scheme == "scripts"}
        try:
            entry_points = list(dist.entry_points)
        except Exception as e:
            raise InstallationError(f"Unreadable entry points for {name} {version}: {e}") from e
        for ep in entry_points:
            if ep.group not in ("console_scripts", "gui_scripts"):
                continue
            for basename in self._script_basenames(ep.name):
                matching = [path for path in staged_scripts if path == basename]
                if not matching:
                    raise InstallationError(f"Script {basename!r} declared by {name} {version} was not generated")
                if os.name != "nt":
                    target = next(
                        (
                            staged
                            for scheme, _rel, staged in sink
                            if scheme == "scripts" and os.path.basename(staged) == basename
                        ),
                        None,
                    )
                    if target is None or not os.access(target, os.X_OK):
                        raise InstallationError(
                            f"Staged script {basename} for {name} {version} is missing or not executable"
                        )
        termui.logger.debug("Staged package verified: %s %s", name, version)

    def validate(self) -> None:
        """Validate the complete staged batch against the live working set."""
        from importlib.metadata import Distribution

        from packaging.requirements import Requirement as PackagingRequirement
        from packaging.utils import canonicalize_name

        marker_env = self.environment.spec.markers_with_defaults()
        removed_keys = {
            canonicalize_name(op["key"])
            for op in self.operations
            if op["kind"] == "remove"
        }
        providers: dict[str, Distribution] = {}
        for key, dist in self.environment.get_working_set().items():
            normalized = canonicalize_name(key)
            if normalized not in removed_keys:
                providers[normalized] = dist
        for op in self.operations:
            if op["kind"] == "remove":
                continue
            providers[canonicalize_name(op["key"])] = Distribution.at(op["staged_dist_info"])

        errors: list[str] = []
        for op in self.operations:
            if op["kind"] == "remove":
                continue
            dist = Distribution.at(op["staged_dist_info"])
            extras = set(op.get("extras") or ())
            for requirement in dist.requires or ():
                req = PackagingRequirement(requirement)
                marker = req.marker
                if marker is not None and not self._marker_matches(marker, marker_env, extras):
                    continue
                name = canonicalize_name(req.name)
                provider = providers.get(name)
                if provider is None:
                    errors.append(
                        f"{dist.metadata['Name']} {dist.version} requires {requirement!r} but no matching "
                        f"distribution is staged or installed"
                    )
                    continue
                if not req.specifier.contains(provider.version, prereleases=True):
                    errors.append(
                        f"{dist.metadata['Name']} {dist.version} requires {requirement!r} but "
                        f"{provider.metadata['Name']} {provider.version} is staged"
                    )
                    continue
                if req.extras:
                    provided = {canonicalize_name(x) for x in (provider.metadata.get_all("Provides-Extra") or [])}
                    missing = {canonicalize_name(x) for x in req.extras} - provided
                    if missing:
                        errors.append(
                            f"{provider.metadata['Name']} {provider.version} does not provide extras "
                            f"{sorted(missing)} required by {dist.metadata['Name']}"
                        )
        if errors:
            raise InstallationError("Staged installation failed dependency validation:\n  - " + "\n  - ".join(errors))

    @staticmethod
    def _marker_matches(marker: Any, marker_env: dict[str, Any], extras: set[str]) -> bool:
        from packaging.markers import UndefinedEnvironmentName

        for extra in extras | {""}:
            env = dict(marker_env)
            env["extra"] = extra
            try:
                if marker.evaluate(env):
                    return True
            except UndefinedEnvironmentName:
                continue
        return False

    # ---------------------------------------------------------------- commit

    def _preflight_writable(self) -> None:
        # Only probe directories that this batch actually touches: staged
        # installs publish files into their recorded scheme slots, and
        # removals/updates move files out of the library and scripts dirs.
        # System schemes such as ``stdlib`` are mapped eagerly but never
        # receive wheel files and must not block installation into a venv
        # that lives next to a read-only interpreter.
        targets: set[str] = set()
        for op in self.operations:
            if op["kind"] != "remove":
                for slot_id, _rel in op.get("files", ()):
                    targets.add(self.dir_map[slot_id])
            if op["kind"] in ("remove", "update"):
                for key in ("purelib", "platlib", "scripts"):
                    if key in self.env_paths:
                        targets.add(self.env_paths[key])
        probe = f".pdm-write-probe-{uuid.uuid4().hex[:8]}"
        for live_dir in targets:
            if not os.path.exists(live_dir):
                continue
            probe_path = os.path.join(live_dir, probe)
            try:
                with open(probe_path, "wb"):
                    pass
                os.unlink(probe_path)
            except OSError as e:
                with contextlib.suppress(OSError):
                    os.unlink(probe_path)
                raise InstallationError(
                    f"Target directory {live_dir} is not writable, refusing to start the installation: {e}"
                ) from e

    def _log_event(self, event: dict[str, str]) -> None:
        self.events.append(event)
        self._persist()

    def _promote_caches(self) -> None:
        cache = self.environment.project.package_cache
        for op in self.operations:
            candidate_path = op.get("candidate")
            if not candidate_path or not os.path.exists(candidate_path):
                op["candidate"] = None
                continue
            from pdm.models.cached_package import CachedPackage

            package = CachedPackage(candidate_path, target_path=op["cache_dest"])
            confirmed = cache.promote_candidate(package)
            confirmed_path = str(confirmed.path)
            if os.path.normcase(confirmed_path) != os.path.normcase(candidate_path):
                # Staged symlinks pointed at the candidate directory; retarget
                # them at the confirmed location now that it has been renamed.
                self._retarget_symlinks(op, candidate_path, confirmed_path)
            op["candidate"] = None
            self._log_event({"t": "promote", "path": confirmed_path})

    def _retarget_symlinks(self, op: dict[str, Any], old_root: str, new_root: str) -> None:
        old_norm = os.path.normcase(os.path.abspath(old_root))
        for slot_id, rel in op["files"]:
            staged = os.path.join(self.tree_root, slot_id, *rel.split("/"))
            if not os.path.islink(staged):
                continue
            target = os.readlink(staged)
            target_norm = os.path.normcase(os.path.abspath(os.path.join(os.path.dirname(staged), target)))
            if target_norm == old_norm or target_norm.startswith(old_norm + os.sep):
                suffix = target_norm[len(old_norm) :]
                os.unlink(staged)
                os.symlink(os.path.join(new_root, suffix.lstrip(os.sep)), staged)

    def _build_removal(self, op: dict[str, Any]) -> StashedRemovePaths:
        from importlib.metadata import Distribution

        live_dist = Distribution.at(op["old_dist_info"])
        remove_paths = StashedRemovePaths.from_dist(live_dist, self.environment, stash_root=str(self.stash_root))
        if op["kind"] == "update":
            staged_dist = Distribution.at(op["staged_dist_info"])
            new_paths = StashedRemovePaths.from_dist(
                staged_dist, self.staged_environment, stash_root=str(self.stash_root)
            )
            new_paths._paths = {NormalizedPath(self._staged_to_live(p)) for p in new_paths._paths}
            remove_paths.difference_update(new_paths)
        return remove_paths

    def _backup_pth(self, remove_paths: StashedRemovePaths) -> str | None:
        if not remove_paths._pth_entries or not os.path.exists(remove_paths._pth_file):
            return None
        backup = self.backup_root / f"easy-install-{uuid.uuid4().hex[:8]}.pth"
        shutil.copy2(remove_paths._pth_file, backup)
        return str(backup)

    def commit(self) -> None:
        if self.state == STATE_COMMITTED:
            return
        termui.logger.info("Validating staged installation of %d operations", len(self.operations))
        self.validate()
        self._preflight_writable()
        self.state = STATE_COMMITTING
        self._persist()
        try:
            self._promote_caches()
            self._publish_changes()
        except BaseException:
            self.rollback(reason="commit failed")
            raise
        self.state = STATE_COMMITTED
        with contextlib.suppress(OSError):
            self._persist()
        self._finish_cleanup()

    def _publish_changes(self) -> None:
        # 1. Move old files of removals/updates aside (journal every rename).
        for op in self.operations:
            if op["kind"] not in ("remove", "update"):
                continue
            remove_paths = self._build_removal(op)
            backup = self._backup_pth(remove_paths)
            old_refer = remove_paths.refer_to
            if backup is not None:
                self._log_event({"t": "pth", "file": remove_paths._pth_file, "backup": backup})
            try:
                self._stash_with_journal(op, remove_paths)
            except OSError as e:
                if e.errno == errno.ENOSPC:
                    raise InstallationError(f"Disk space exhausted while updating {op['key']}") from e
                raise
            if old_refer:
                CachedPackageReferrers.remove(old_refer, op["old_dist_info"])
                self._log_event({"t": "unrefer", "cache": old_refer, "dist": op["old_dist_info"]})

        # 2. Publish staged files with atomic renames.
        for op in self.operations:
            if op["kind"] == "remove":
                continue
            for slot_id, rel in sorted(op["files"], key=lambda item: item[1]):
                staged = os.path.join(self.tree_root, slot_id, *rel.split("/"))
                live = os.path.join(self.dir_map[slot_id], *rel.split("/"))
                if not os.path.exists(staged):
                    raise InstallationError(f"Staged file disappeared before commit for {op['key']}: {rel}")
                os.makedirs(os.path.dirname(live), exist_ok=True)
                self._log_event({"t": "publish", "staged": staged, "live": live})
                try:
                    os.replace(staged, live)
                except OSError as e:
                    if e.errno == errno.ENOSPC:
                        raise InstallationError(f"Disk space exhausted while installing {op['key']}") from e
                    raise
                self._log_event({"t": "published", "staged": staged, "live": live})
            if op.get("cache_dest"):
                CachedPackageReferrers.add(op["cache_dest"], op["live_dist_info"])
                self._log_event({"t": "refer", "cache": op["cache_dest"], "dist": op["live_dist_info"]})

    def _stash_with_journal(self, op: dict[str, Any], remove_paths: StashedRemovePaths) -> None:
        """Like ``StashedRemovePaths.remove()`` but journals each physical move.

        Intent and completion are logged separately so a crash between the
        two can be resolved deterministically during recovery.
        """
        from tempfile import TemporaryDirectory

        from pdm.installers.uninstallers import _get_file_root, compress_for_rename

        remove_paths._remove_pth()
        paths_to_rename = sorted(compress_for_rename(remove_paths._paths))
        prefix = os.path.abspath(self.environment.get_paths()["prefix"])
        for old_path in paths_to_rename:
            if not os.path.exists(old_path):
                continue
            is_dir = os.path.isdir(old_path) and not os.path.islink(old_path)
            if old_path.endswith(".pyc"):
                os.unlink(old_path)
                continue
            root = _get_file_root(old_path, prefix)
            if root is None:
                termui.logger.debug("File path %s is not under packages root %s, skip", old_path, prefix)
                continue
            tempdir = remove_paths._tempdirs.get(root)
            if tempdir is None:
                tempdir = TemporaryDirectory("-uninstall", "pdm-", dir=str(self.stash_root))
                remove_paths._tempdirs[root] = tempdir
            new_path = os.path.join(tempdir.name, os.path.relpath(old_path, root))
            if is_dir and os.path.isdir(new_path):
                os.rmdir(new_path)
            self._log_event({"t": "stash", "old": old_path, "new": new_path})
            renames(old_path, new_path)
            remove_paths._stashed.append((old_path, new_path))
            self._log_event({"t": "stashed", "old": old_path, "new": new_path})

    # --------------------------------------------------------------- rollback

    def rollback(self, reason: str = "failed") -> None:
        """Restore the previous environment and discard all staging state."""
        if self._finished or self.state == STATE_COMMITTED:
            return
        termui.logger.warning("Rolling back install transaction %s (%s)", self.tx_id, reason)
        if self.state == STATE_COMMITTING:
            replay_events(self.events)
        # Candidates that never made it to the confirmed cache are discarded.
        for op in self.operations:
            candidate = op.get("candidate")
            if candidate and os.path.exists(candidate):
                shutil.rmtree(candidate, ignore_errors=True)
                with contextlib.suppress(OSError):
                    Path(candidate).with_suffix(".lock").unlink()
        self.state = STATE_ROLLED_BACK
        with contextlib.suppress(OSError):
            self._persist()
        self._finish_cleanup()

    def _finish_cleanup(self) -> None:
        shutil.rmtree(self.stage_root, ignore_errors=True)
        with contextlib.suppress(OSError):
            self.journal_path.unlink()
        with contextlib.suppress(Exception):
            self.environment.project.package_cache.sweep_candidates()
        self._finished = True
        self._restore_signal_handlers()
        if self._atexit_registered:
            atexit.unregister(self._at_exit)
            self._atexit_registered = False

    # -------------------------------------------------------------- recovery

    def recover(self) -> None:
        """Roll back or finish transactions interrupted in earlier processes."""
        with contextlib.suppress(Exception):
            self.environment.project.package_cache.sweep_candidates()
        candidates = []
        if self.journal_path.is_file():
            candidates.append(self.journal_path)
        # The stage copy keeps recovery possible if the cache journal was lost.
        prefix = self.stage_root.parent
        if prefix.is_dir():
            candidates.extend(sorted(prefix.glob(f"{STAGE_PREFIX}*/tx.json")))
        for journal_file in dict.fromkeys(candidates):
            try:
                with journal_file.open() as fp:
                    payload = json.load(fp)
            except (OSError, json.JSONDecodeError):
                continue
            if payload.get("env_id") != self.env_id:
                continue
            self._recover_payload(payload)
            if journal_file != self.journal_path:
                with contextlib.suppress(OSError):
                    journal_file.unlink()

    def _recover_payload(self, payload: dict[str, Any]) -> None:
        state = payload.get("state")
        stage_root = payload.get("stage_root")
        if state == STATE_COMMITTED:
            if stage_root:
                shutil.rmtree(stage_root, ignore_errors=True)
            with contextlib.suppress(OSError):
                self.journal_path.unlink()
            return
        if state in (STATE_COMMITTING, STATE_STAGING, STATE_ROLLED_BACK):
            self.ui.echo(
                "[warning]Found an interrupted installation, restoring the previous environment...[/]",
                err=True,
            )
            if state == STATE_COMMITTING:
                replay_events(payload.get("events", []))
            if stage_root:
                shutil.rmtree(stage_root, ignore_errors=True)
            for op in payload.get("operations", []):
                candidate = op.get("candidate") if isinstance(op, dict) else None
                if candidate and os.path.exists(candidate):
                    shutil.rmtree(candidate, ignore_errors=True)
            with contextlib.suppress(OSError):
                self.journal_path.unlink()


def replay_events(events: list[dict[str, str]]) -> None:
    """Revert committed physical events in reverse order, deterministically.

    Each mutating event is logged twice (intent followed by completion). A
    completed event is undone directly; an intent without completion is
    resolved by reconciling the two recorded paths.
    """
    index = len(events) - 1
    while index >= 0:
        event = events[index]
        kind = event["t"]
        # Every mutating event is recorded as an intent/completion pair; a
        # completion event therefore skips its own intent when going reverse.
        next_index = index - 1
        try:
            if kind == "stashed":
                # Wildcard directories are journaled with a trailing separator;
                # strip it or ``shutil.move`` would move the backup *into* the
                # target directory instead of replacing it.
                old = event["old"].rstrip(os.sep) or os.sep
                new = event["new"]
                if os.path.exists(new):
                    # Published files have already been undone, so a directory
                    # recreated at the old location can only hold empty shells
                    # (directories left behind by ``makedirs``). Refuse to
                    # replace a directory that still contains real files.
                    has_files = os.path.isdir(old) and any(p.is_file() for p in Path(old).rglob("*"))
                    if has_files:
                        termui.logger.warning(
                            "Keep stashed files in %s, target directory %s still contains files",
                            new,
                            old,
                        )
                    else:
                        if os.path.isdir(old) and not os.path.islink(old):
                            shutil.rmtree(old, ignore_errors=True)
                        elif os.path.lexists(old):
                            os.unlink(old)
                        if not os.path.exists(old):
                            renames(new, old)
                next_index = index - 2
            elif kind == "stash":
                # Intent logged without completion: the rename did not happen,
                # so the old path is untouched. Never remove the stash root --
                # earlier completed moves of the same operation live there too.
                old = event["old"].rstrip(os.sep) or os.sep
                new = event["new"]
                if not os.path.exists(old) and os.path.exists(new):
                    renames(new, old)
            elif kind == "published":
                live = event["live"]
                if os.path.islink(live) or os.path.isfile(live):
                    os.unlink(live)
                next_index = index - 2
            elif kind == "publish":
                # Interrupted before os.replace(): discard the staged file.
                staged = event["staged"]
                if os.path.exists(staged) and not os.path.isdir(staged):
                    os.unlink(staged)
            elif kind == "pth":
                if os.path.exists(event["backup"]):
                    shutil.copy2(event["backup"], event["file"])
            elif kind == "refer":
                CachedPackageReferrers.remove(event["cache"], event["dist"])
            elif kind == "unrefer":
                CachedPackageReferrers.add(event["cache"], event["dist"])
                # "promote" needs no undo: a promoted package is complete and
                # content-addressed; nothing in the environment refers to it.
        except OSError as e:  # pragma: no cover - best effort recovery
            termui.logger.warning("Error while replaying rollback event %s: %s", event, e)
        index = next_index


class CachedPackageReferrers:
    """Tiny referrer bookkeeping facade with best-effort error handling."""

    @staticmethod
    def add(cache_path: str, dist_info: str) -> None:
        from pdm.models.cached_package import CachedPackage

        with contextlib.suppress(OSError):
            CachedPackage(cache_path).add_referrer(os.path.dirname(dist_info))

    @staticmethod
    def remove(cache_path: str, dist_info: str) -> None:
        from pdm.models.cached_package import CachedPackage

        with contextlib.suppress(OSError):
            CachedPackage(cache_path).remove_referrer(os.path.dirname(dist_info))


class _TransactionContext:
    def __init__(self, transaction: InstallTransaction) -> None:
        self.tx = transaction

    def __enter__(self) -> InstallTransaction:
        self.tx.begin()
        return self.tx

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc is not None and not self.tx._finished and self.tx.state != STATE_COMMITTED:
            with contextlib.suppress(Exception):
                self.tx.rollback(reason=exc_type.__name__ if exc_type else "error")
        self.tx._restore_signal_handlers()
