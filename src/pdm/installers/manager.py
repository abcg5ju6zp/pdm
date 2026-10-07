from __future__ import annotations

from importlib.metadata import Distribution
from typing import TYPE_CHECKING, Any

from pdm import termui
from pdm.exceptions import UninstallError
from pdm.installers.installers import install_wheel
from pdm.installers.uninstallers import BaseRemovePaths, StashedRemovePaths

if TYPE_CHECKING:
    from pdm.environments import BaseEnvironment
    from pdm.installers.transaction import InstallTransaction
    from pdm.models.cached_package import CachedPackage
    from pdm.models.candidates import Candidate


class InstallManager:
    """The manager that performs the installation and uninstallation actions."""

    def __init__(
        self,
        environment: BaseEnvironment,
        *,
        use_install_cache: bool = False,
        rename_pth: bool = False,
        transaction: InstallTransaction | None = None,
    ) -> None:
        self.environment = environment
        self.use_install_cache = use_install_cache
        self.rename_pth = rename_pth
        # When bound to a transaction, installs land in the validated
        # staging tree and removals/updates are deferred until commit time.
        self.transaction = transaction

    def install(self, candidate: Candidate) -> Distribution:
        """Install a candidate into the environment, return the distribution"""
        _op, distribution = self._perform_install(candidate)
        return distribution

    def _perform_install(self, candidate: Candidate) -> tuple[dict | None, Distribution]:
        prepared = candidate.prepare(self.environment)
        wheel = prepared.build()
        tx = self.transaction
        install_links = self.use_install_cache and not candidate.req.editable
        cached_package: CachedPackage | None = None
        if install_links and tx is not None:
            # The non-transactional path acquires the cache inside
            # ``install_wheel`` to preserve its original call sequence.
            cached_package = tx.acquire_candidate(wheel)
        target_environment = tx.staged_environment if tx is not None else self.environment
        record_sink: list[tuple[str, str, str]] | None = [] if tx is not None else None
        install_kwargs: dict[str, Any] = {
            "direct_url": prepared.direct_url(),
            "install_links": install_links,
            "rename_pth": self.rename_pth if tx is None else False,
            "requested": candidate.requested,
        }
        if tx is not None:
            install_kwargs.update(
                cached_package=cached_package,
                record_sink=record_sink,
                defer_referrer=True,
            )
        try:
            dist_info = install_wheel(wheel, target_environment, **install_kwargs)
        except BaseException:
            if tx is not None:
                tx.discard_attempt(record_sink, cached_package)
            raise
        if tx is not None:
            extras = set(getattr(candidate.req, "extras", None) or ())
            try:
                op = tx.register_install(candidate, dist_info, record_sink or [], cached_package, extras)
            except BaseException:
                tx.discard_attempt(record_sink, cached_package)
                raise
            return op, Distribution.at(op["staged_dist_info"])
        return None, Distribution.at(dist_info)

    def get_paths_to_remove(self, dist: Distribution) -> BaseRemovePaths:
        """Get the path collection to be removed from the disk"""
        return StashedRemovePaths.from_dist(dist, environment=self.environment)

    def uninstall(self, dist: Distribution) -> None:
        """Perform the uninstallation for a given distribution"""
        if self.transaction is not None:
            self.transaction.queue_remove(dist)
            return
        remove_path = self.get_paths_to_remove(dist)
        dist_name = dist.metadata.get("Name")
        termui.logger.info("Removing distribution %s", dist_name)
        try:
            remove_path.remove()
            remove_path.commit()
        except OSError as e:
            termui.logger.warning("Error occurred during uninstallation, roll back the changes now.")
            remove_path.rollback()
            raise UninstallError(e) from e

    def overwrite(self, dist: Distribution, candidate: Candidate) -> None:
        """An in-place update to overwrite the distribution with a new candidate"""
        tx = self.transaction
        if tx is not None:
            # Staged install first; the old files are moved at commit time and
            # reconciled against the new file set by the transaction.
            op, _installed = self._perform_install(candidate)
            assert op is not None
            try:
                tx.queue_update(op, dist)
            except BaseException:
                tx.discard_op(op)
                raise
            return
        paths_to_remove = self.get_paths_to_remove(dist)
        termui.logger.info("Overwriting distribution %s", dist.metadata.get("Name"))
        installed = self.install(candidate)
        installed_paths = self.get_paths_to_remove(installed)
        # Remove the paths that are in the new distribution
        paths_to_remove.difference_update(installed_paths)
        try:
            paths_to_remove.remove()
            paths_to_remove.commit()
        except OSError as e:
            termui.logger.warning("Error occurred during overwriting, roll back the changes now.")
            paths_to_remove.rollback()
            raise UninstallError(e) from e
