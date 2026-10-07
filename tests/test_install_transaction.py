from __future__ import annotations

import errno
import os
import stat
import venv
from pathlib import Path

import pytest
from unearth import Link

from pdm.environments.base import BaseEnvironment
from pdm.environments.local import PythonLocalEnvironment
from pdm.environments.python import PythonEnvironment
from pdm.exceptions import InstallationError
from pdm.installers import InstallManager
from pdm.installers import transaction as transaction_module
from pdm.installers.transaction import InstallTransaction
from pdm.models.candidates import Candidate
from pdm.models.requirements import parse_requirement
from pdm.project.core import Project

pytestmark = pytest.mark.usefixtures("local_finder")

JMESPATH_WHEEL = "http://fixtures.test/artifacts/jmespath-0.10.0-py2.py3-none-any.whl"
DEMO_WHEEL = "http://fixtures.test/artifacts/demo-0.0.1-py2.py3-none-any.whl"
FUTURE_FSTRINGS_WHEEL = "http://fixtures.test/artifacts/future_fstrings-1.2.0-py2.py3-none-any.whl"


def _prepare_project_for_env(project: Project, env_cls: type[BaseEnvironment]):
    project._saved_python = None
    project._python = None
    if env_cls is PythonEnvironment:
        venv.create(project.root / ".venv", symlinks=True)
        project.project_config["python.use_venv"] = True


@pytest.fixture(params=(PythonEnvironment, PythonLocalEnvironment))
def tx_environment(request: pytest.RequestFixture, project: Project):
    env_cls: type[BaseEnvironment] = request.param
    _prepare_project_for_env(project, env_cls)
    return env_cls


def _candidate(line: str) -> Candidate:
    return Candidate(parse_requirement(line), link=Link(f"http://fixtures.test/artifacts/{line}"))


def test_transaction_commits_files_scripts_and_metadata(project, tx_environment):
    env = project.environment
    candidate = Candidate(parse_requirement("jmespath"), link=Link(JMESPATH_WHEEL))
    tx = InstallTransaction(env)
    tx.recover()
    manager = InstallManager(env, transaction=tx)

    with tx.activate():
        manager.install(candidate)
        tx.commit()

    working_set = env.get_working_set()
    assert "jmespath" in working_set
    script = os.path.join(env.get_paths()["scripts"], "jp.py")
    assert os.path.isfile(script)
    if os.name != "nt":
        assert os.stat(script).st_mode & stat.S_IXUSR
    # The staging area and the journal are gone after a confirmed commit.
    assert not tx.stage_root.exists()
    assert not tx.journal_path.exists()
    assert not list(project.cache("packages").glob(".*.candidate"))


def test_transaction_promotes_validated_cache_candidate(project, tx_environment):
    env = project.environment
    candidate = Candidate(
        parse_requirement("future-fstrings"),
        link=Link("http://fixtures.test/artifacts/future_fstrings-1.2.0-py2.py3-none-any.whl"),
    )
    tx = InstallTransaction(env)
    tx.recover()
    manager = InstallManager(env, use_install_cache=True, transaction=tx)

    with tx.activate():
        manager.install(candidate)
        tx.commit()

    packages = project.cache("packages")
    confirmed = packages / "future_fstrings-1.2.0-py2.py3-none-any.whl.cache"
    assert confirmed.is_dir()
    assert not list(packages.glob(".*.candidate"))
    lib_file = Path(env.get_paths()["purelib"]) / "future_fstrings.py"
    assert lib_file.exists()
    if lib_file.is_symlink():
        assert Path(os.readlink(lib_file)).exists()
    dist = env.get_working_set()["future-fstrings"]
    assert dist.read_text("RECORD")
    assert tx.state == "committed"


def test_rollback_during_staging_restores_previous_environment(project, tx_environment):
    env = project.environment
    InstallManager(env).install(Candidate(parse_requirement("demo"), link=Link(DEMO_WHEEL)))

    tx = InstallTransaction(env)
    tx.recover()
    manager = InstallManager(env, transaction=tx)
    with tx.activate():
        # A removal and a fresh install are staged but never committed.
        manager.uninstall(env.get_working_set()["demo"])
        manager.install(Candidate(parse_requirement("jmespath"), link=Link(JMESPATH_WHEEL)))
        tx.rollback("forced")

    working_set = env.get_working_set()
    assert "demo" in working_set
    assert "jmespath" not in working_set
    assert not os.path.exists(os.path.join(env.get_paths()["scripts"], "jp.py"))
    assert not tx.stage_root.exists()
    assert not tx.journal_path.exists()
    assert not list(project.cache("packages").glob(".*.candidate"))


def test_rollback_after_publish_failure_restores_environment(project, tx_environment, monkeypatch):
    env = project.environment
    InstallManager(env).install(Candidate(parse_requirement("demo"), link=Link(DEMO_WHEEL)))
    purelib = os.path.normcase(os.path.abspath(env.get_paths()["purelib"]))

    tx = InstallTransaction(env)
    tx.recover()
    real_replace = os.replace
    calls = {"n": 0}

    def fail_on_third_replace(src, dst):
        if os.path.normcase(str(dst)).startswith(purelib):
            calls["n"] += 1
            if calls["n"] == 3:
                raise OSError(errno.ENOSPC, "simulated disk full")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_on_third_replace)
    manager = InstallManager(env, transaction=tx)
    with tx.activate():
        manager.uninstall(env.get_working_set()["demo"])
        manager.install(Candidate(parse_requirement("jmespath"), link=Link(JMESPATH_WHEEL)))
        with pytest.raises(InstallationError, match="Disk space"):
            tx.commit()

    working_set = env.get_working_set()
    assert "demo" in working_set
    assert "jmespath" not in working_set
    assert not os.path.exists(os.path.join(env.get_paths()["scripts"], "jp.py"))
    assert not tx.stage_root.exists()
    assert not tx.journal_path.exists()
    # Confirmed cache entries created before the failure are valid and reusable.
    confirmed = project.cache("packages") / "jmespath-0.10.0-py2.py3-none-any.whl.cache"
    assert not confirmed.exists() or (confirmed / "RECORD").exists()


def test_recovery_restores_environment_after_dead_process(project, tx_environment, monkeypatch):
    import tempfile

    env = project.environment
    InstallManager(env).install(Candidate(parse_requirement("demo"), link=Link(DEMO_WHEEL)))
    InstallManager(env).install(Candidate(parse_requirement("jmespath"), link=Link(JMESPATH_WHEEL)))

    # Simulate a hard kill: TemporaryDirectory finalizers must not clean the
    # stash when the managed process disappears. On Python 3.12 the weakref
    # finalizer calls ``_rmtree`` directly, so neutralize both entry points.
    class PersistentTemporaryDirectory(tempfile.TemporaryDirectory):
        def cleanup(self) -> None:
            pass

        @classmethod
        def _rmtree(cls, name, *args, **kwargs) -> None:  # type: ignore[override]
            pass

    monkeypatch.setattr(tempfile, "TemporaryDirectory", PersistentTemporaryDirectory)

    tx = InstallTransaction(env)
    tx.recover()
    tx.begin()
    tx.queue_remove(env.get_working_set()["demo"])
    tx.state = transaction_module.STATE_COMMITTING
    tx._persist()

    # Simulate the process dying after one stash completed and the next move
    # failed halfway (intent logged, completion missing).
    real_renames = transaction_module.renames
    state = {"calls": 0}

    def flaky_renames(old, new):
        state["calls"] += 1
        if state["calls"] == 2:
            raise OSError("interrupted")
        return real_renames(old, new)

    monkeypatch.setattr(transaction_module, "renames", flaky_renames)
    with pytest.raises(OSError):
        tx._publish_changes()
    tx._finished = True  # the original process is gone; atexit must not act

    # A brand new process discovers the journal and finishes the rollback.
    next_tx = InstallTransaction(env)
    next_tx.recover()

    working_set = env.get_working_set()
    assert "demo" in working_set
    assert "jmespath" in working_set
    assert not tx.stage_root.exists()
    assert not next_tx.journal_path.exists()


def test_readonly_environment_is_rejected_before_any_change(project, tx_environment):
    env = project.environment
    purelib = Path(env.get_paths()["purelib"])
    purelib.mkdir(parents=True, exist_ok=True)
    os.chmod(purelib, 0o555)
    tx = InstallTransaction(env)
    try:
        manager = InstallManager(env, transaction=tx)
        with (
            pytest.raises(InstallationError, match="not writable"),
            tx.activate(),
        ):
            manager.install(Candidate(parse_requirement("jmespath"), link=Link(JMESPATH_WHEEL)))
            tx.commit()
        assert "jmespath" not in env.get_working_set()
        assert not tx.stage_root.exists()
    finally:
        os.chmod(purelib, 0o755)


def test_incomplete_confirmed_cache_is_discarded_and_rebuilt(project, tx_environment):
    env = project.environment
    prepared = Candidate(parse_requirement("demo"), link=Link(DEMO_WHEEL)).prepare(env)
    wheel = prepared.build()
    cache = project.package_cache

    poisoned = cache._confirmed_path(wheel)
    poisoned.mkdir(parents=True)
    (poisoned / "partial-file").write_text("truncated")
    package = cache.cache_wheel(wheel)
    assert package.is_complete()
    assert package.dist_info.is_dir()
    assert not (poisoned / "partial-file").exists()


def test_abandoned_candidate_directories_are_swept(project, tx_environment):
    env = project.environment
    prepared = Candidate(parse_requirement("demo"), link=Link(DEMO_WHEEL)).prepare(env)
    wheel = prepared.build()
    cache = project.package_cache
    package = cache.acquire_candidate(wheel)
    assert package.path.name.endswith(".candidate")
    assert package.path.exists()
    # Simulate the owning transaction dying without promoting the candidate.
    assert cache.sweep_candidates() == 1
    assert not package.path.exists()


def test_editable_install_remains_compatible_with_transaction(project, tx_environment, tmp_path_factory):
    env = project.environment
    editable_path: Path = tmp_path_factory.mktemp("editable-project")
    (editable_path / "setup.py").write_text(
        """
from setuptools import setup

setup(name='editable-project',
      version='0.1.0',
      description='',
      py_modules=['module'],
)
"""
    )
    (editable_path / "module.py").write_text("VALUE = 42\n")

    req = parse_requirement(f"{editable_path.as_uri()}#egg=editable-project", True)
    candidate = Candidate(req)
    tx = InstallTransaction(env)
    tx.recover()
    manager = InstallManager(env, use_install_cache=True, transaction=tx)
    with tx.activate():
        manager.install(candidate)
        tx.commit()

    assert "editable-project" in env.get_working_set()
    lib_path = Path(env.get_paths()["purelib"])
    pth_files = list(lib_path.glob("*editable_project*.pth"))
    assert pth_files and all(p.is_file() and not p.is_symlink() for p in pth_files)
    cache_path = project.cache("packages") / "editable_project-0.1.0-0.editable-py3-none-any.whl.cache"
    assert not cache_path.is_dir()


# --------------------------------------------------------------- sync level


def test_failed_job_is_retried_deterministically_within_transaction(project, pdm, monkeypatch):
    project.project_config["install.parallel"] = False
    project.add_dependencies([f"future-fstrings @ {FUTURE_FSTRINGS_WHEEL}"])
    project.add_dependencies([f"jmespath @ {JMESPATH_WHEEL}"])

    import pdm.installers.manager as manager_module

    real_install_wheel = manager_module.install_wheel
    attempts = {"jmespath": 0}

    def flaky_install_wheel(wheel, environment, **kwargs):
        if wheel.name.startswith("jmespath"):
            attempts["jmespath"] += 1
            if attempts["jmespath"] == 1:
                raise OSError(errno.ENOSPC, "simulated disk full")
        return real_install_wheel(wheel, environment, **kwargs)

    monkeypatch.setattr(manager_module, "install_wheel", flaky_install_wheel)
    pdm(["install", "--no-self"], obj=project, strict=True)

    assert attempts["jmespath"] == 2
    working_set = project.environment.get_working_set()
    assert "future-fstrings" in working_set
    assert "jmespath" in working_set


def test_failed_batch_rolls_back_and_retry_installs_everything(project, pdm, monkeypatch):
    project.project_config["install.parallel"] = False
    project.add_dependencies([f"future-fstrings @ {FUTURE_FSTRINGS_WHEEL}"])
    project.add_dependencies([f"jmespath @ {JMESPATH_WHEEL}"])

    import pdm.installers.manager as manager_module

    real_install_wheel = manager_module.install_wheel
    state = {"fail": True}

    def maybe_fail(wheel, environment, **kwargs):
        if state["fail"] and wheel.name.startswith("jmespath"):
            raise RuntimeError("jmespath never installs")
        return real_install_wheel(wheel, environment, **kwargs)

    monkeypatch.setattr(manager_module, "install_wheel", maybe_fail)
    # cleanup=False keeps the shared client session alive between the two
    # in-process command invocations (a real retry uses a fresh process).
    result = pdm(["install", "--no-self"], obj=project, cleanup=False)
    assert result.exit_code == 1

    # Nothing from the failed batch is visible in the active environment.
    working_set = project.environment.get_working_set()
    assert "future-fstrings" not in working_set
    assert "jmespath" not in working_set
    assert not list(project.cache("packages").glob(".*.candidate"))

    state["fail"] = False
    pdm(["install", "--no-self"], obj=project, strict=True)
    working_set = project.environment.get_working_set()
    assert "future-fstrings" in working_set
    assert "jmespath" in working_set
