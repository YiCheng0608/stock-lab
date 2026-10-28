"""Test-process isolation for filesystem-backed application configuration.

The application creates ``data/raw`` when ``app.config`` is imported.  Set
the environment before pytest imports any test module so an adapter fixture
can never write official payloads into the repository's production data
directory.  Individual tests may still monkeypatch ``worker.sources.RAW_DIR``
to their own ``tmp_path`` when they need to inspect a capture.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

import pytest

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="taiwan-stock-research-tests-"))
_TEST_DATA_DIR = _TEST_ROOT / "data"
_TEST_RAW_DIR = _TEST_DATA_DIR / "raw"

# Assign rather than setdefault: a developer shell may have production
# values inherited from a previous CLI/probe, and tests must override them.
os.environ["STOCK_DATA_DIR"] = str(_TEST_DATA_DIR)
os.environ["STOCK_DB_PATH"] = str(_TEST_DATA_DIR / "stock.db")
os.environ["STOCK_RAW_DIR"] = str(_TEST_RAW_DIR)
# The api container sets these (Issue 343); tests of app.main expect the defaults, so they never leak in.
os.environ.pop("STOCK_API_PUBLIC_HOSTS", None)
os.environ.pop("STOCK_API_ALLOWED_ORIGINS", None)


def pytest_configure(config):
    """Expose the session paths for diagnostics without importing app.config."""

    config._taiwan_stock_test_root = _TEST_ROOT


def pytest_unconfigure(config):
    """Remove the directory this process created; roots of other runs stay.

    A failed removal only prints a warning so it never changes the test result.
    """

    if not _TEST_ROOT.exists():
        return
    engine = getattr(sys.modules.get("app.db"), "engine", None)
    if engine is not None:
        engine.dispose()
    failures = []

    def remember(function, path, error):
        failures.append((path, error))

    shutil.rmtree(_TEST_ROOT, onexc=remember)
    _warn(failures)


def _retry_writable(function, path, failures):
    """rmtree's onexc: make PATH writable and retry once; what still fails is recorded.

    A link is retried as it is: chmod follows a symlink on POSIX and would change the
    permissions of its target outside the basetemp (#290 review L2).
    """

    try:
        if not (os.path.islink(path) or os.path.isjunction(path)):
            os.chmod(path, os.lstat(path).st_mode | stat.S_IWRITE)
        function(path)
    except OSError as again:
        failures.append((path, again))


def _delete(path, failures):
    """Delete PATH; a junction or symlink as the link itself, never what it points to."""

    if os.path.isjunction(path):
        function = os.rmdir
    elif os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(
            path, onexc=lambda function, p, _: _retry_writable(function, p, failures)
        )
        return
    else:
        function = os.unlink
    try:
        function(path)
    except OSError:
        _retry_writable(function, path, failures)


def _drop_repositories(top, failures):
    """Delete every ``.git`` under TOP and return how many (#304).

    The walk is ``tools/ops/coordinator_json.py``'s ``_git_inside``, the one
    ``close_task.sh --extra-dir`` refuses a directory by: it does not enter a junction
    or symlink, so nothing outside TOP is reached.
    """

    count, stack = 0, [str(top)]
    while stack:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for entry in entries:
            if entry.name == ".git":
                _delete(entry.path, failures)
                count += 1
            elif entry.is_dir(follow_symlinks=False) and not entry.is_junction():
                stack.append(entry.path)
    return count


def _warn(failures):
    for path, error in failures:
        sys.stderr.write(
            f"warning: could not remove {path}: {type(error).__name__}: {error}\n"
        )


def pytest_sessionfinish(session, exitstatus):
    """Leave no repository in the run's basetemp, a ``--basetemp`` one included.

    Tests build repositories under tmp_path, fake (``repo/.git``, ``project/.git``) and
    real (``git init``). Left in an engineer's temp directory outside the worktree they
    make ``tools/ops/close_task.sh --extra-dir`` refuse it, and pytest keeps them even
    under tmp_path_retention_policy = "failed" (a skipped test's tmp_path, git's
    read-only object files). A green run removes the whole basetemp (#290). A run that
    fails or is interrupted keeps its files for debugging but not their ``.git``: the
    next run may take another basetemp and never clear this one (#304).
    """

    factory = getattr(session.config, "_tmp_path_factory", None)
    basetemp = getattr(factory, "_basetemp", None)
    if basetemp is None or not basetemp.is_dir():
        return
    failures = []
    if exitstatus == 0:
        shutil.rmtree(
            basetemp,
            onexc=lambda function, path, _: _retry_writable(function, path, failures),
        )
    elif count := _drop_repositories(basetemp, failures):
        sys.stderr.write(
            f"kept {basetemp} for debugging without its {count} .git (#304)\n"
        )
    _warn(failures)


@pytest.fixture(autouse=True)
def isolate_runtime_paths(tmp_path, monkeypatch):
    """Give every test its own raw/data paths after module import as well.

    At teardown the repositories the test built in its tmp_path are deleted, failed or
    not, so a run killed before pytest_sessionfinish leaves at most those of the test
    it was in (#304).
    """

    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("STOCK_DATA_DIR", str(data_dir))
    monkeypatch.setenv("STOCK_DB_PATH", str(data_dir / "stock.db"))
    monkeypatch.setenv("STOCK_RAW_DIR", str(raw_dir))

    # ``sources.RAW_DIR`` is imported by value from app.config.  Patch both
    # modules so direct captures and any config-level consumers share the same
    # per-test directory, including tests that construct an adapter directly.
    from app import config as app_config
    import worker.sources as sources

    monkeypatch.setattr(app_config, "DATA_DIR", data_dir)
    monkeypatch.setattr(app_config, "DB_PATH", data_dir / "stock.db")
    monkeypatch.setattr(app_config, "RAW_DIR", raw_dir)
    monkeypatch.setattr(sources, "RAW_DIR", raw_dir)
    yield
    failures = []
    _drop_repositories(tmp_path, failures)
    _warn(failures)
