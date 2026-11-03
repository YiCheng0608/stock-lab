"""Test-process isolation for filesystem-backed application configuration.

The application creates ``data/raw`` when ``app.config`` is imported.  Set
the environment before pytest imports any test module so an adapter fixture
can never write official payloads into the repository's production data
directory.  Individual tests may still monkeypatch ``worker.sources.RAW_DIR``
to their own ``tmp_path`` when they need to inspect a capture.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

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
# Set by worker.job for the worker it runs (Issue 336); never inherited by a test.
os.environ.pop("STOCK_JOB_LOCK", None)
# compose hands the env file's tokens to the api container (Issue 337), where the local checks
# run the tests (Issue 339): a real token never reaches a test, and the tests see what CI's
# jobs (no env file) do.
os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
os.environ.pop("GH_TOKEN", None)
# The event monitor's wake token (Issue 338): no test wakes the coordinator with the real one.
os.environ.pop("STOCK_WAKE_TOKEN", None)


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


# A session that is killed (a command timeout, a reaped background task, a closed
# terminal) never reaches pytest_sessionfinish, so the fake repository of the test it was
# in stays in its basetemp, and a later run on another basetemp never visits it: #386,
# #394 and #392 each had close_task.sh --extra-dir refuse t<issue>/ for it (#422).
# Every session therefore records itself where the next session, whatever its basetemp,
# finds it: a record <token>.json in the runs directory naming the basetemp, and a marker
# file .pytest-run-<token> in that basetemp, locked for as long as the session lives.
# The OS drops the lock with a dead process, so a free lock means the session died.
_RUNS_ENV = "PYTEST_RUNS_DIR"
_MARKER = ".pytest-run-"


def _runs_dir():
    return Path(os.environ.get(_RUNS_ENV) or Path.home() / ".stock-lab-pytest-runs")


def _hold(path, create=False):
    """An exclusive lock on PATH as an open descriptor, or None when it is not free."""

    try:
        fd = os.open(path, os.O_RDWR | (os.O_CREAT if create else 0), 0o644)
    except OSError:
        return None
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def _let_go(fd):
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(fd)


def _unlink(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError as error:
        return (path, error)
    return None


def _register(basetemp, runs_dir):
    """Record this session: lock a marker in BASETEMP, then write the record naming it."""

    token = uuid.uuid4().hex
    marker = Path(basetemp) / f"{_MARKER}{token}"
    fd = _hold(marker, create=True)
    if fd is None:
        return None
    record = Path(runs_dir) / f"{token}.json"
    try:
        record.parent.mkdir(parents=True, exist_ok=True)
        part = record.with_suffix(".part")
        part.write_text(json.dumps({"basetemp": str(basetemp)}), encoding="utf-8")
        os.replace(part, record)
    except OSError:
        _let_go(fd)
        _unlink(marker)
        raise
    return SimpleNamespace(fd=fd, marker=marker, record=record)


def _sweep_dead_runs(runs_dir, failures):
    """Delete the ``.git`` in the basetemp of every recorded session that died (#422).

    A session counts as dead when the marker it locked in its basetemp is free. A record
    whose marker is gone (the basetemp was emptied or reused since) is dropped without
    touching the directory: nothing says it is still the basetemp of that session. What
    is deleted is what ``_drop_repositories`` deletes at the end of a failed run; the
    other files stay for debugging.
    """

    try:
        records = [e.path for e in os.scandir(runs_dir) if e.name.endswith(".json")]
    except OSError:
        return
    for record in sorted(records):
        try:
            with open(record, encoding="utf-8") as stream:
                basetemp = Path(json.load(stream)["basetemp"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        marker = basetemp / f"{_MARKER}{Path(record).stem}"
        if not os.path.lexists(marker):
            _unlink(record)
            continue
        fd = _hold(marker)
        if fd is None:
            continue
        left = []
        count = _drop_repositories(basetemp, left)
        _let_go(fd)
        failures.extend(left)
        if count:
            sys.stderr.write(
                f"removed {count} .git left in {basetemp} by a pytest run that died "
                "before it finished (#422)\n"
            )
        if not left:
            # Kept for the next run when a .git would not go.
            _unlink(marker)
            _unlink(record)


def pytest_sessionstart(session):
    """Remove what earlier sessions that died left, then record this one (#422).

    A failure here only prints a warning: it never changes the result of the run.
    """

    config, failures = session.config, []
    try:
        basetemp = config._tmp_path_factory.getbasetemp()
        runs_dir = _runs_dir()
        _sweep_dead_runs(runs_dir, failures)
        config._stock_lab_run = _register(basetemp, runs_dir)
    except Exception as error:
        sys.stderr.write(
            f"warning: this pytest run is not recorded: {type(error).__name__}: {error}\n"
        )
    _warn(failures)


def pytest_sessionfinish(session, exitstatus):
    """Leave no repository in the run's basetemp, a ``--basetemp`` one included.

    Tests build repositories under tmp_path, fake (``repo/.git``, ``project/.git``) and
    real (``git init``). Left in an engineer's temp directory outside the worktree they
    make ``tools/ops/close_task.sh --extra-dir`` refuse it, and pytest keeps them even
    under tmp_path_retention_policy = "failed" (a skipped test's tmp_path, git's
    read-only object files). A green run removes the whole basetemp (#290). A run that
    fails or is interrupted keeps its files for debugging but not their ``.git``: the
    next run may take another basetemp and never clear this one (#304). A run that dies
    before this hook is cleared by the next run's pytest_sessionstart (#422).
    """

    run = getattr(session.config, "_stock_lab_run", None)
    if run is not None and run.fd is not None:
        # An open file cannot be deleted on Windows; the record stays until the
        # basetemp is clean, so a failed deletion below is retried by the next run.
        _let_go(run.fd)
        run.fd = None
    failures = []
    factory = getattr(session.config, "_tmp_path_factory", None)
    basetemp = getattr(factory, "_basetemp", None)
    if basetemp is not None and basetemp.is_dir():
        if exitstatus == 0:
            shutil.rmtree(
                basetemp,
                onexc=lambda function, path, _: _retry_writable(
                    function, path, failures
                ),
            )
        elif count := _drop_repositories(basetemp, failures):
            sys.stderr.write(
                f"kept {basetemp} for debugging without its {count} .git (#304)\n"
            )
    _warn(failures)
    if run is not None and not failures:
        _unlink(run.marker)
        _unlink(run.record)


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


# Naive UTC, with microseconds no real clock reads. 01:04 on 2026-10-30 in Taipei, so
# the UTC date (10/29) and the Taipei date differ.
FROZEN_AT = datetime(2026, 10, 29, 17, 4, 5, 678901)


class FrozenClock:
    """The instant a test's clocks answer; assign ``at`` (naive UTC) to move it (#376)."""

    def __init__(self) -> None:
        self.at = FROZEN_AT

    def datetime_class(self) -> type:
        """A ``datetime`` whose ``now`` reads this clock, in the zone asked for.

        ``now()`` without a zone is naive UTC, as on a machine set to UTC, so a clock
        read that skipped the zone gives the same answer on every developer machine.
        """

        clock = self

        class Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return clock.at
                return clock.at.replace(tzinfo=timezone.utc).astimezone(tz)

        return Frozen


@pytest.fixture
def frozen_utcnow(monkeypatch) -> FrozenClock:
    """``app.clock.utcnow`` answers ``FROZEN_AT`` to every caller (#376).

    Worker modules bound the function with ``from app.clock import utcnow``, so patching
    that name would reach none of them; the class ``app.clock`` reads is the one place
    they all share. A write that takes its time from anywhere else stores a value other
    than ``FROZEN_AT``. Models' column defaults call the same function.
    """

    from app import clock

    frozen = FrozenClock()
    monkeypatch.setattr(clock, "datetime", frozen.datetime_class())
    return frozen
