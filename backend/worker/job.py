"""Scheduled worker jobs: ``python -m worker.cli job daily|news`` (#313).

What tools/Invoke-WorkerJob.ps1 did, together with what the Task Scheduler task
settings did (a run time limit, one instance at a time), so that any scheduler
only has to start one command:

- One job of each kind at a time per data directory: an exclusive ``fcntl``
  lock on ``<data>/locks/<job>.lock``. The OS drops it when its holder ends, however it ends, so a killed job leaves
  nothing to clean up. A second job is skipped with reason ``already_running``;
  daily also records that row in schedule_runs.
- The checks before a run: free physical memory below --min-free-memory-gb
  (``low_memory``) and a git operation in progress in this checkout, i.e.
  index.lock or MERGE_HEAD (``git_busy``). daily records the skip through
  ``worker.cli daily --skip-reason``; news only logs it.
- The code is never updated here: it is the image tools/ops/deploy.sh built
  and started (#340). The job logs that image and its commit
  (``STOCK_IMAGE_TAG``, ``STOCK_GIT_HEAD``); daily records the same two in the
  run's ``summary_json.runtime`` (worker.schedule_runs). A task registered
  before #314 still passes --git-pull; it is accepted and ignored.
- The worker CLI runs as a child process within the job's time limit (daily
  2.5 hours; news 90 minutes for news and news-llm together). The child and
  everything it starts end with the job: the child gets SIGKILL when the job
  dies (PR_SET_PDEATHSIG). The run row of a killed daily therefore
  names a dead PID, and the next run closes it at once (schedule_runs). The
  worker gets the lock's path in ``STOCK_JOB_LOCK`` while the job holds it:
  whoever holds that lock next knows the row's process is gone, even in a
  restarted container with another hostname (#336).
- The dated log ``<logs>/<job>-YYYYMMDD.log`` (Taipei date) with the layout of
  docs/ops/SCHEDULING.md 日誌與 run 記錄, the exit code, and removing logs older than
  --log-retention-days.

The news job runs ``worker.cli news`` and then ``worker.cli news-llm``; the
job's exit code is news's alone, news-llm's goes to the log as
``news_llm_exit``.

Maintenance mode (#468): while the marker ``<data>/locks/maintenance`` exists
(``worker.cli maintenance on``), a daily or news job only logs ``skipped
reason=maintenance`` and ends 0. It starts no worker, so it writes nothing to the
database, not even the skipped row a daily records for its other skips: a
backfill, a backtest or an ``init-db`` can have the database alone while serve
keeps running the watchdog and the event monitor. The marker is checked after the
job's lock is taken, so once ``maintenance on`` has written it, a job that holds
the lock either is shown by ``maintenance status`` (it started before) or skips.
The backfill and backtest commands hold it themselves (``MaintenanceHold``): on as
they start, a heartbeat every minute, off in their ``finally``; serve expires a
marker whose heartbeat stopped for 10 minutes (``expire_stale_maintenance``: a
holder killed by SIGKILL or the OOM killer); a holder that finds its marker gone
stops (exit 70). ``maintenance on`` by hand has no heartbeat, stays on until
``off`` (tools/ops/deploy.sh turns it off after a deploy), and the backfill and
backtest commands refuse to start under it. Every change of the marker is made under
``<data>/locks/maintenance.lock`` and logged in ``<data>/logs/maintenance.log``. While serve
runs it holds ``<data>/locks/serve.lock`` (``maintenance status`` shows it).

Only the standard library is imported here: the watchdog takes its lock
through the same code without the backend's dependencies, with
``python -m worker.job lock <file> -- <command> ...``. tools/ops/deploy.sh
holds the three locks in the running scheduler container with
``lock --keep-stdin``: the command reads the deploy's stdin and ends when the
deploy closes it, or dies (#340).

Linux only, as in the backend image (#333): the Windows branches (msvcrt, job
objects, GlobalMemoryStatusEx, pythonw.exe) went with the Task Scheduler
wrapper. Elsewhere ``job`` and ``lock`` refuse to start (``PLATFORM_EXIT``).
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO, Sequence

ROOT = Path(__file__).resolve().parents[2]
TAIPEI = timezone(timedelta(hours=8))
JOBS = ("daily", "news")
TRIGGERS = ("scheduler", "manual", "simulation")
# daily: the abandoned-run limit in worker.schedule_runs; a manual run's limit, as
# serve passes its scheduled runs 80 minutes, which end before the 23:00 trigger
# (#466). news: well inside its 2-hour interval.
TIME_LIMIT_MINUTES = {"daily": 150.0, "news": 90.0}
DEFAULT_MIN_FREE_MEMORY_GB = 8.0
DEFAULT_LOG_RETENTION_DAYS = 90
LOCK_SKIP_REASON = "already_running"
# `lock`: exit code when another process holds the lock (EX_TEMPFAIL).
LOCK_BUSY_EXIT = 75
# A step killed at the time limit counts as failed.
TIMEOUT_EXIT = 1
# `job` and `lock` on a system other than Linux (EX_UNAVAILABLE).
PLATFORM_EXIT = 69
NEWLINE = os.linesep
# worker.schedule_runs.JOB_LOCK_ENV, IMAGE_TAG_ENV and GIT_HEAD_ENV: this module
# imports only the standard library.
JOB_LOCK_ENV = "STOCK_JOB_LOCK"
IMAGE_TAG_ENV = "STOCK_IMAGE_TAG"
GIT_HEAD_ENV = "STOCK_GIT_HEAD"
# Maintenance mode (#468): the marker in locks/, its log, the skip reason, and the lock
# serve holds for as long as it runs (lock_path names both).
MAINTENANCE_MARKER = "maintenance"
MAINTENANCE_LOG = "maintenance.log"
MAINTENANCE_SKIP_REASON = "maintenance"
SERVE_LOCK = "serve"
# A backfill or backtest refused by MaintenanceHold (EX_TEMPFAIL, as `lock`).
MAINTENANCE_REFUSED_EXIT = 75
# A command holding maintenance mode beats this often; serve expires a marker whose
# beat is older than MAINTENANCE_STALE_SECONDS (the holder died without its finally).
MAINTENANCE_HEARTBEAT_SECONDS = 60.0
MAINTENANCE_STALE_SECONDS = 600.0
# How long a change of the marker waits for the marker lock (_MarkerLock).
MAINTENANCE_LOCK_TIMEOUT_SECONDS = 60.0
# A holder that lost maintenance mode while it ran stops with this (EX_SOFTWARE).
MAINTENANCE_LOST_EXIT = 70


def platform_problem(module: str = "worker.job") -> str | None:
    if sys.platform.startswith("linux"):
        return None
    return f"{module} runs on Linux only (the backend image, #333), not {sys.platform}"


def default_data_dir() -> Path:
    value = os.environ.get("STOCK_DATA_DIR")
    return Path(value) if value else Path.home() / "stock-lab-data"


def resolve_data_dir(value: str | None) -> Path:
    return Path(os.path.abspath(value.rstrip("\\/") if value else default_data_dir()))


def data_environment(data_dir: Path) -> dict[str, str]:
    return {
        "STOCK_DATA_DIR": str(data_dir),
        "STOCK_DB_PATH": str(data_dir / "stock.db"),
        "STOCK_RAW_DIR": str(data_dir / "raw"),
    }


def cli_environment(argv: Sequence[str]) -> dict[str, str]:
    """For ``worker.cli job``, ``serve`` and ``maintenance``: the data paths app.config must see.

    app.config reads STOCK_DATA_DIR and creates that directory on import; without
    this a scheduled task (no STOCK_* in its environment) would create ``data/``
    in the checkout. Any other command gets nothing.
    """

    if not argv or argv[0] not in ("job", "serve", "maintenance"):
        return {}
    value = None
    for index, arg in enumerate(argv):
        if arg == "--data-dir" and index + 1 < len(argv):
            value = argv[index + 1]
        elif arg.startswith("--data-dir="):
            value = arg.split("=", 1)[1]
    return data_environment(resolve_data_dir(value))


def lock_path(data_dir: Path, name: str) -> Path:
    return data_dir / "locks" / f"{name}.lock"


class FileLock:
    """An exclusive, non-blocking lock on a file; the OS drops it with its holder."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        import fcntl

        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        return True

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is not None:
            os.close(fd)


def lock_held(path: Path) -> bool:
    """Whether another process holds the lock on PATH (a missing file is not held).

    It takes the lock for a moment: a job starting in that moment would find it busy.
    The maintenance checks call it only for serve's lock, and for the job locks only
    with maintenance on, when such a job skips for maintenance before it looks at its
    lock (``_Job._skip_reason``).
    """

    if not path.is_file():
        return False
    probe = FileLock(path)
    if not probe.acquire():
        return True
    probe.release()
    return False


def maintenance_path(data_dir: Path) -> Path:
    return data_dir / "locks" / MAINTENANCE_MARKER


def maintenance_state(data_dir: Path) -> dict | None:
    """The maintenance marker of DATA_DIR, or None when maintenance is off.

    The file being there is what counts: a marker that cannot be read still holds the
    jobs back (``readable`` false), dated by its modification time.
    """

    path = maintenance_path(data_dir)
    try:
        text = path.read_text(encoding="utf-8")
        modified = path.stat().st_mtime
    except FileNotFoundError:
        return None
    except OSError as exc:
        return {"since_epoch": None, "reason": f"unreadable: {exc}", "readable": False}
    try:
        state = json.loads(text)
        since = float(state["since_epoch"])
        reason = str(state.get("reason") or "")
    except (ValueError, KeyError, TypeError):
        return {"since_epoch": modified, "reason": "unreadable", "readable": False}
    return {**state, "since_epoch": since, "reason": reason, "readable": True}


def heartbeat_age(state: dict | None, now: float | None = None) -> float | None:
    """Seconds since the holding command's last beat; None for a marker without one
    (turned on by hand, or unreadable): that one never expires."""

    beat = state.get("heartbeat_epoch") if state else None
    if isinstance(beat, bool) or not isinstance(beat, (int, float)):
        return None
    return (time.time() if now is None else now) - beat


def _taipei(epoch: float | None) -> str:
    if epoch is None:
        return "unknown"
    return datetime.fromtimestamp(epoch, TAIPEI).isoformat(timespec="seconds")


def _write_marker(path: Path, marker: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Unique across containers too: a `compose run` container's PID is often 1.
    temporary = path.with_name(
        f".{path.name}.{socket.gethostname()}.{os.getpid()}.{time.time_ns()}"
    )
    temporary.write_text(json.dumps(marker, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


class _MarkerLock:
    """Every change of the marker under one blocking flock (#468 review 6647096392):
    taking it, a beat, a release, an expiry, ``on`` and ``off``. Two commands starting
    at once, or a beat racing serve's expiry, then read and write in turn. Not
    reentrant: hold it once per change. No-op off Linux (no fcntl)."""

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "locks" / f"{MAINTENANCE_MARKER}.lock"
        self._fd: int | None = None

    def __enter__(self) -> "_MarkerLock":
        if not sys.platform.startswith("linux"):
            return self
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        deadline = time.monotonic() + MAINTENANCE_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() > deadline:
                    os.close(self._fd)
                    self._fd = None
                    raise TimeoutError(f"{self.path} held for over a minute") from None
                time.sleep(0.05)

    def __exit__(self, *_exc) -> None:
        fd, self._fd = self._fd, None
        if fd is not None:
            os.close(fd)


def _maintenance_log(data_dir: Path, record: dict) -> None:
    logs = data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with open(logs / MAINTENANCE_LOG, "a", encoding="utf-8", newline="\n") as log:
        log.write(json.dumps(record, ensure_ascii=False) + "\n")


def running_jobs(data_dir: Path) -> list[str]:
    if not sys.platform.startswith("linux"):
        return []  # no fcntl; serve and its jobs run on Linux only (#333)
    return [name for name in JOBS if lock_held(lock_path(data_dir, name))]


def maintenance_status(data_dir: Path) -> dict:
    """``worker.cli maintenance status``: what the jobs and serve see."""

    state = maintenance_state(data_dir)
    out: dict = {
        "maintenance": "on" if state else "off",
        "marker": str(maintenance_path(data_dir)),
        "serve_running": sys.platform.startswith("linux")
        and lock_held(lock_path(data_dir, SERVE_LOCK)),
    }
    if state:
        since = state["since_epoch"]
        age = heartbeat_age(state)
        out.update(
            since=_taipei(since),
            hours=None if since is None else round((time.time() - since) / 3600, 2),
            reason=state["reason"],
            readable=state["readable"],
            owner=state.get("command") or state.get("owner") or "unknown",
            host=state.get("host"),
            pid=state.get("pid"),
            heartbeat_age_seconds=None if age is None else round(age),
            # Probed only now: a job that starts meanwhile skips for maintenance.
            running_jobs=running_jobs(data_dir),
        )
    return out


def maintenance_on(data_dir: Path, reason: str) -> dict:
    """Turn it on by hand (kept as it is when already on). No heartbeat: it stays on
    until ``maintenance off`` (tools/ops/deploy.sh's), and the watchdog reports it past
    12 hours. Backfills and backtests refuse to start under it."""

    now = time.time()
    with _MarkerLock(data_dir):
        already = maintenance_state(data_dir) is not None
        if not already:
            _write_marker(
                maintenance_path(data_dir),
                {
                    "since": _taipei(now),
                    "since_epoch": now,
                    "reason": reason,
                    "owner": "manual",
                    "host": socket.gethostname(),
                },
            )
    _maintenance_log(
        data_dir,
        {
            "at": _taipei(now),
            "event": "on_again" if already else "on",
            "reason": reason,
            "host": socket.gethostname(),
        },
    )
    return {**maintenance_status(data_dir), "already_on": already}


def _off(data_dir: Path, reason: str, only_manual: bool) -> tuple[dict | None, bool]:
    """The marker as read and whether it was removed, under the marker lock."""

    now = time.time()
    with _MarkerLock(data_dir):
        state = maintenance_state(data_dir)
        if state and only_manual and heartbeat_age(state) is not None:
            return state, False
        if state:
            maintenance_path(data_dir).unlink(missing_ok=True)
    since = state["since_epoch"] if state else None
    _maintenance_log(
        data_dir,
        {
            "at": _taipei(now),
            "event": "off" if state else "off_again",
            "reason": reason,
            "owner": (state.get("command") or state.get("owner")) if state else None,
            "since": _taipei(since) if state else None,
            "hours": None if since is None else round((now - since) / 3600, 2),
            "host": socket.gethostname(),
        },
    )
    return state, state is not None


def maintenance_off(data_dir: Path, reason: str) -> dict:
    """Remove the marker and log it with how long maintenance was on."""

    state, _ = _off(data_dir, reason, only_manual=False)
    return {**maintenance_status(data_dir), "was_on": state is not None}


def maintenance_off_if_manual(data_dir: Path, reason: str) -> dict:
    """``maintenance off --only-manual``: what tools/ops/deploy.sh runs once its new
    containers check out (#468 decision 6646032625). A maintenance mode turned on by
    hand for init-db ends with the deploy; one a command holds (a heartbeat) is left to
    that command. ``deploy_maintenance`` says which: turned_off, none or
    kept_command_held."""

    state, removed = _off(data_dir, reason, only_manual=True)
    if state is None:
        outcome = "none"
    elif not removed:
        outcome = "kept_command_held"
    else:
        outcome = "turned_off"
    return {**maintenance_status(data_dir), "deploy_maintenance": outcome}


def expire_stale_maintenance(data_dir: Path, now: float | None = None) -> dict | None:
    """Turn off maintenance whose command stopped beating (#468 AC-5), or None.

    Killed by the OOM killer or SIGKILL, a command never reaches its ``finally``; after
    MAINTENANCE_STALE_SECONDS without a beat its marker is removed and an ``expired``
    record logged, which the watchdog reports. A marker without a heartbeat (on by
    hand) never expires. Under the marker lock: a beat cannot bring back a marker
    removed here, and the holder that finds it gone stops (``MaintenanceHold``).
    """

    if heartbeat_age(maintenance_state(data_dir)) is None:
        return None  # off, or on by hand: no lock taken every minute for nothing
    with _MarkerLock(data_dir):
        state = maintenance_state(data_dir)
        moment = time.time() if now is None else now
        age = heartbeat_age(state, moment)
        if age is None or age <= MAINTENANCE_STALE_SECONDS:
            return None
        maintenance_path(data_dir).unlink(missing_ok=True)
    record = {
        "at": _taipei(moment),
        "event": "expired",
        "owner": state.get("command") or state.get("owner"),
        "host": state.get("host"),
        "pid": state.get("pid"),
        "reason": state["reason"],
        "since": _taipei(state["since_epoch"]),
        "heartbeat": _taipei(state["heartbeat_epoch"]),
        "heartbeat_age_minutes": round(age / 60, 1),
        "hours": round((moment - state["since_epoch"]) / 3600, 2),
    }
    _maintenance_log(data_dir, record)
    return record


class MaintenanceRefused(Exception):
    """A command that needs maintenance mode cannot take it now (exit 75)."""


class MaintenanceLost(BaseException):
    """The holder lost maintenance mode while it ran (exit 70): its marker expired or
    was removed, or its heartbeat failed. A BaseException, like KeyboardInterrupt, so
    that the command's own ``except Exception`` does not carry on writing."""


class MaintenanceHold:
    """Maintenance mode held by the command that needs it (#468 AC-5).

    ``with MaintenanceHold(data_dir, "backfill"):`` takes maintenance mode under the
    marker lock, beats every MAINTENANCE_HEARTBEAT_SECONDS from a thread, and turns it
    off in its ``finally`` however the command ends; SIGTERM becomes SystemExit so that
    ``docker stop`` reaches it too. A command killed outright stops beating and serve
    expires its marker (``expire_stale_maintenance``).

    Refused (MaintenanceRefused): another command with a live heartbeat holds it; it
    was turned on by hand (a deploy's init-db, which deploy.sh turns off underneath a
    command); or a daily or news job that started before it is still running.

    Lost (MaintenanceLost, raised in the main thread through SIGUSR1): the beat finds
    the marker gone or someone else's (expired after the machine slept, turned off) or
    cannot write it. The command stops then, rather than write alongside a daily.
    """

    def __init__(
        self,
        data_dir: Path,
        command: str,
        reason: str | None = None,
        heartbeat_seconds: float | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.command = command
        self.reason = reason or command
        self.heartbeat_seconds = heartbeat_seconds or MAINTENANCE_HEARTBEAT_SECONDS
        self.token = f"{socket.gethostname()}:{os.getpid()}:{time.time_ns()}"
        self.owned = False
        self.state: dict | None = None
        self.lost: str | None = None
        self._stop = None
        self._thread = None
        self._previous = {}

    def __enter__(self) -> "MaintenanceHold":
        import threading

        now = time.time()
        with _MarkerLock(self.data_dir):
            state = maintenance_state(self.data_dir)
            age = heartbeat_age(state, now)
            if state and age is None:
                raise MaintenanceRefused(
                    f"{self.command}: 目前是手動維護（部署中，原因：{state['reason']}，自"
                    f" {_taipei(state['since_epoch'])}），請等部署完成（deploy.sh 會關掉它）"
                    "再跑；python -m worker.cli maintenance status 可查。"
                )
            if state and age <= MAINTENANCE_STALE_SECONDS:
                raise MaintenanceRefused(
                    f"{self.command}: maintenance mode is held by {state.get('command')}"
                    f" (pid {state.get('pid')} on {state.get('host')}, since"
                    f" {_taipei(state['since_epoch'])}): one backfill or backtest at a"
                    " time; python -m worker.cli maintenance status shows it."
                )
            self.state = {
                "since": _taipei(now),
                "since_epoch": now,
                "reason": self.reason,
                "owner": "command",
                "command": self.command,
                "host": socket.gethostname(),
                "pid": os.getpid(),
                "token": self.token,
                "heartbeat_epoch": now,
            }
            _write_marker(maintenance_path(self.data_dir), self.state)
            self.owned = True
        record = {
            "at": _taipei(now),
            "event": "held",
            "owner": self.command,
            "reason": self.reason,
            "host": socket.gethostname(),
            "pid": os.getpid(),
        }
        if state:
            # A holder that stopped beating and has not expired yet.
            record["took_over_from"] = state.get("command")
        _maintenance_log(self.data_dir, record)
        busy = running_jobs(self.data_dir)
        if busy:
            self._release(f"refused: {' and '.join(busy)} still running")
            raise MaintenanceRefused(
                f"{self.command}: a {' and a '.join(busy)} job that started before"
                " maintenance mode is still running; start again once it has ended"
                " (python -m worker.cli maintenance status shows running_jobs)."
            )
        self._main = threading.current_thread() is threading.main_thread()
        if self._main:
            self._previous = {
                signal.SIGTERM: signal.signal(signal.SIGTERM, _sigterm_exit),
                signal.SIGUSR1: signal.signal(signal.SIGUSR1, self._lost_signal),
            }
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._beat, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, _traceback) -> bool:
        self._stop.set()
        self._thread.join(timeout=30)
        for signum, handler in self._previous.items():
            signal.signal(signum, handler)
        if exc_type is None:
            outcome = "success"
        elif issubclass(exc_type, SystemExit):
            outcome = f"exit {exc.code}"
        elif issubclass(exc_type, MaintenanceLost):
            outcome = f"lost: {exc}"
        else:
            outcome = f"{exc_type.__name__}: {exc}"[:300]
        self._release(outcome)
        return False

    def _lost_signal(self, _signum, _frame) -> None:
        if self.lost and not self._stop.is_set():
            raise MaintenanceLost(self.lost)

    def _beat(self) -> None:
        while not self._stop.wait(self.heartbeat_seconds):
            try:
                with _MarkerLock(self.data_dir):
                    current = maintenance_state(self.data_dir)
                    if not current or current.get("token") != self.token:
                        reason = (
                            "maintenance mode is no longer held by this run (expired"
                            " after a pause, or turned off)"
                        )
                    else:
                        _write_marker(
                            maintenance_path(self.data_dir),
                            {**self.state, "heartbeat_epoch": time.time()},
                        )
                        continue
            except Exception as exc:  # the beat itself failed: it would expire unseen
                reason = f"the heartbeat failed: {type(exc).__name__}: {exc}"
            self._lose(reason)
            return

    def _lose(self, reason: str) -> None:
        """Stop the command: it must not write once daily and news may run again."""

        import _thread

        self.lost = reason
        print(
            f"{self.command}: {reason}; stopping (exit 70)", file=sys.stderr, flush=True
        )
        _maintenance_log(
            self.data_dir,
            {
                "at": _taipei(time.time()),
                "event": "lost",
                "owner": self.command,
                "reason": reason,
                "host": socket.gethostname(),
                "pid": os.getpid(),
            },
        )
        if self._stop.is_set():
            return
        if self._main:
            os.kill(
                os.getpid(), signal.SIGUSR1
            )  # wakes a main thread blocked in a call
        else:
            _thread.interrupt_main()

    def _release(self, outcome: str) -> None:
        if not self.owned:
            return
        self.owned = False
        try:
            with _MarkerLock(self.data_dir):
                current = maintenance_state(self.data_dir)
                if not current or current.get("token") != self.token:
                    return  # expired meanwhile, or another holder: not ours to remove
                maintenance_path(self.data_dir).unlink(missing_ok=True)
        except OSError as exc:
            print(
                f"{self.command}: could not release maintenance mode: {exc}",
                file=sys.stderr,
            )
            return
        now = time.time()
        _maintenance_log(
            self.data_dir,
            {
                "at": _taipei(now),
                "event": "released",
                "owner": self.command,
                "outcome": outcome,
                "since": _taipei(self.state["since_epoch"]),
                "hours": round((now - self.state["since_epoch"]) / 3600, 2),
                "host": socket.gethostname(),
                "pid": os.getpid(),
            },
        )


def _sigterm_exit(signum, _frame) -> None:
    raise SystemExit(128 + signum)


class _ProcessTree:
    """Start one child; it and everything it starts end when this process ends."""

    def start(self, argv: list[str], **kwargs) -> subprocess.Popen:
        kwargs["preexec_fn"] = _die_with_parent(os.getpid())
        return subprocess.Popen(argv, start_new_session=True, **kwargs)

    def kill(self, process: subprocess.Popen) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def _die_with_parent(parent: int):
    def preexec() -> None:
        pr_set_pdeathsig = 1
        ctypes.CDLL(None, use_errno=True).prctl(pr_set_pdeathsig, signal.SIGKILL)
        if os.getppid() != parent:  # the job died before prctl took effect
            os._exit(1)

    return preexec


def free_memory_mb() -> int | None:
    """MemAvailable in /proc/meminfo, never through WMI (#246); None when unknown."""

    try:
        with open("/proc/meminfo", encoding="ascii") as meminfo:
            for line in meminfo:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def git_dir(root: Path) -> Path | None:
    """The checkout's git dir; ``.git`` is a file pointing at it in a linked worktree."""

    dot_git = root / ".git"
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():
        first = dot_git.read_text(encoding="utf-8").splitlines()[:1]
        if first and first[0].startswith("gitdir:"):
            return Path(os.path.abspath(root / first[0][len("gitdir:") :].strip()))
    return None


def worker_command(step_args: list[str]) -> list[str]:
    return [sys.executable, "-X", "utf8", "-m", "worker.cli", *step_args]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("job", choices=JOBS)
    parser.add_argument(
        "--data-dir", help="資料目錄；預設 STOCK_DATA_DIR，再來是 ~/stock-lab-data"
    )
    parser.add_argument("--log-dir", help="日誌目錄；預設 <資料目錄>/logs")
    parser.add_argument(
        "--date",
        dest="run_date",
        help="YYYY-MM-DD；news-llm 不帶（它的 --date 是篩選）",
    )
    parser.add_argument("--trigger", choices=TRIGGERS, default="scheduler")
    parser.add_argument("--force", action="store_true", help="只給 daily")
    # Passed by tasks registered before #314; the checkout is no longer pulled.
    parser.add_argument("--git-pull", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--claude-cli", help="Claude Code CLI，以 STOCK_CLAUDE_CLI 傳給子程序"
    )
    parser.add_argument(
        "--skip-news-llm", action="store_true", help="只給 news：不跑 news-llm"
    )
    parser.add_argument(
        "--log-retention-days",
        type=int,
        default=DEFAULT_LOG_RETENTION_DAYS,
        help="只清 <job>-*.log（1～3650，預設 90）",
    )
    parser.add_argument(
        "--min-free-memory-gb",
        type=float,
        default=DEFAULT_MIN_FREE_MEMORY_GB,
        help="可用實體記憶體低於此值記 low_memory（預設 8）",
    )
    parser.add_argument(
        "--time-limit-minutes",
        type=float,
        help="單次上限；預設 daily 150、news 90（news 與 news-llm 合計）",
    )


def argument_problem(args: argparse.Namespace) -> str | None:
    if args.job != "news" and args.skip_news_llm:
        return "--skip-news-llm applies only to the news job"
    if args.job != "daily" and args.force:
        return "--force applies only to the daily job"
    if not 1 <= args.log_retention_days <= 3650:
        return "--log-retention-days must be between 1 and 3650"
    if not 0 <= args.min_free_memory_gb <= 1024:
        return "--min-free-memory-gb must be between 0 and 1024"
    if args.time_limit_minutes is not None and args.time_limit_minutes <= 0:
        return "--time-limit-minutes must be positive"
    return None


class _Job:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.job: str = args.job
        self.data_dir = resolve_data_dir(args.data_dir)
        self.log_dir = Path(os.path.abspath(args.log_dir or self.data_dir / "logs"))
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.started = datetime.now(TAIPEI)
        self.log_path = self.log_dir / f"{self.job}-{self.started:%Y%m%d}.log"
        minutes = args.time_limit_minutes or TIME_LIMIT_MINUTES[self.job]
        self.limit = timedelta(minutes=minutes)
        self.deadline = time.monotonic() + self.limit.total_seconds()
        self.tree = _ProcessTree()
        environment = {
            **os.environ,
            **data_environment(self.data_dir),
            "PYTHONPATH": str(ROOT / "backend"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        environment.pop(JOB_LOCK_ENV, None)
        if args.claude_cli:
            environment["STOCK_CLAUDE_CLI"] = args.claude_cli
        self.environment = environment

    def log(self, text: str) -> None:
        with open(self.log_path, "a", encoding="utf-8", newline="") as log:
            log.write(text + NEWLINE)

    def step(self, step: str, step_args: list[str]) -> int:
        """Run one worker CLI step; its stdout and stderr go to the log."""

        prefix = f"{step} " if self.job == "news" else ""
        with (
            tempfile.TemporaryFile(dir=self.log_dir, prefix=f".{step}-") as out,
            tempfile.TemporaryFile(dir=self.log_dir, prefix=f".{step}-") as err,
        ):
            process = self.tree.start(
                worker_command(step_args),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                cwd=ROOT,
                env=self.environment,
            )
            timed_out = False
            try:
                code = process.wait(timeout=max(0.0, self.deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                self.tree.kill(process)
                timed_out, code = True, TIMEOUT_EXIT
            for name, part in (("stdout", out), ("stderr", err)):
                text = _read(part)
                if text:
                    self.log(f"--- {prefix}{name}{NEWLINE}{text}")
        if timed_out:
            self.log(
                f"--- {prefix}timeout: killed at the {_minutes(self.limit)} minute"
                f" limit of the {self.job} job (exit={TIMEOUT_EXIT})"
            )
        return code

    def run(self) -> tuple[int, str | None]:
        """Run the job; returns its exit code and, for news, ``news_llm_exit``."""

        free_mb = free_memory_mb()
        lock = FileLock(lock_path(self.data_dir, self.job))
        locked = lock.acquire()
        if locked:
            self.environment[JOB_LOCK_ENV] = str(lock.path)
        try:
            self.log(self._header(free_mb))
            try:
                return self._run(locked, lock.path, free_mb)
            except Exception as exc:
                self.log(f"===== wrapper error: {exc}")
                raise
        finally:
            lock.release()
            self._remove_old_logs(self.args.log_retention_days)

    def _header(self, free_mb: int | None) -> str:
        args = self.args
        header = (
            f"===== {self.started.isoformat()} start job={self.job}"
            f" trigger={args.trigger} date={args.run_date or 'default'}"
            f" force={bool(args.force)} db={self.data_dir / 'stock.db'}"
            f" free_mb={'unknown' if free_mb is None else free_mb}"
        )
        if self.job == "news":
            header += f" news_llm={'off' if args.skip_news_llm else 'on'}"
        return header

    def _skip_reason(self, locked: bool, lock_file: Path, free_mb: int | None):
        """The reason not to run the worker and the detail for the log, or None."""

        # Read once the lock is taken (or found held), and ahead of already_running: in
        # maintenance a daily that finds the lock held records nothing either
        # (already_running would be a row in the database).
        maintenance = maintenance_state(self.data_dir)
        if maintenance:
            return MAINTENANCE_SKIP_REASON, (
                f"since={_taipei(maintenance['since_epoch'])}"
                f", reason={maintenance['reason']}"
                f", marker={maintenance_path(self.data_dir)}"
            )
        if not locked:
            return LOCK_SKIP_REASON, f"lock={lock_file}"
        min_free_mb = int(self.args.min_free_memory_gb * 1024)
        checkout_git = git_dir(ROOT)
        detail = f"min_free_mb={min_free_mb}, git_dir={checkout_git or ''}"
        if free_mb is not None and free_mb < min_free_mb:
            return "low_memory", detail
        if checkout_git and any(
            (checkout_git / marker).exists() for marker in ("index.lock", "MERGE_HEAD")
        ):
            return "git_busy", detail
        return None, detail

    def _run(self, locked: bool, lock_file: Path, free_mb: int | None):
        args, job = self.args, self.job
        run_news_llm = job == "news" and not args.skip_news_llm
        news_llm_exit = None
        if job == "news":
            news_llm_exit = "not_run" if run_news_llm else "disabled"
        image = os.environ.get(IMAGE_TAG_ENV) or "unknown"
        head = os.environ.get(GIT_HEAD_ENV) or "unknown"
        self.log(f"--- version image={image} head={head}")
        if args.git_pull:
            self.log("--- --git-pull ignored: the code is the deployed image's (#340)")
        skip_reason, detail = self._skip_reason(locked, lock_file, free_mb)
        if skip_reason:
            self.log(f"===== skipped reason={skip_reason} ({detail})")
        if skip_reason and (job != "daily" or skip_reason == MAINTENANCE_SKIP_REASON):
            # Only daily records a skipped run in the database, and not in maintenance
            # mode: then nothing is written there (#468).
            code = 0
        else:
            step_args = [job]
            if job == "daily":
                step_args += ["--trigger", args.trigger]
                if args.force:
                    step_args.append("--force")
                if skip_reason:
                    step_args += ["--skip-reason", skip_reason]
            if args.run_date:
                step_args += ["--date", args.run_date]
            started = time.monotonic()
            code = self.step(job, step_args)
            if job == "news":
                self.log(f"--- news end exit={code} seconds={_since(started)}")
            if run_news_llm:
                news_llm_exit = self._news_llm()
        finished = datetime.now(TAIPEI)
        seconds = round((finished - self.started).total_seconds())
        end = f"===== {finished.isoformat()} end exit={code} seconds={seconds}"
        if job == "news":
            end += f" news_llm_exit={news_llm_exit}"
        self.log(end)
        return code, news_llm_exit

    def _news_llm(self) -> int | str:
        """Runs whatever news's result was and never changes it."""

        started = time.monotonic()
        claude_shown = (
            self.args.claude_cli
            or os.environ.get("STOCK_CLAUDE_CLI")
            or "claude (PATH)"
        )
        self.log(f"--- news-llm start claude_cli={claude_shown}")
        result: int | str
        if time.monotonic() >= self.deadline:
            result = "timeout"
            self.log(
                f"--- news-llm timeout: not started, the {_minutes(self.limit)} minute"
                " limit of the news job is used up"
            )
        else:
            try:
                # No --date: for news-llm it selects that day's items.
                result = self.step("news-llm", ["news-llm"])
            except Exception as exc:
                result = "wrapper_error"
                self.log(f"--- news-llm wrapper error: {exc}")
        self.log(f"--- news-llm end exit={result} seconds={_since(started)}")
        return result

    def _remove_old_logs(self, days: int) -> None:
        cutoff = time.time() - days * 86400
        for path in self.log_dir.glob(f"{self.job}-*.log"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass


def _read(part: BinaryIO) -> str:
    part.seek(0)
    return part.read().decode("utf-8", errors="replace")


def _since(started: float) -> int:
    return round(time.monotonic() - started)


def _minutes(limit: timedelta) -> str:
    return f"{limit.total_seconds() / 60:g}"


def run(args: argparse.Namespace) -> int:
    """``worker.cli job``: run one job and return its exit code."""

    problem = platform_problem()
    if problem:
        print(problem, file=sys.stderr)
        return PLATFORM_EXIT
    job = _Job(args)
    code, news_llm_exit = job.run()
    summary = f"{args.job} exit={code}"
    if news_llm_exit is not None:
        summary += f" news_llm_exit={news_llm_exit}"
    print(f"{summary} log={job.log_path}", flush=True)
    return code


def run_locked(path: Path, command: list[str], keep_stdin: bool = False) -> int:
    """``worker.job lock``: run COMMAND while holding the lock on PATH.

    COMMAND gets no stdin unless KEEP_STDIN: then it reads this process's.
    """

    problem = platform_problem()
    if problem:
        print(problem, file=sys.stderr)
        return PLATFORM_EXIT
    lock = FileLock(path)
    if not lock.acquire():
        print(f"locked: {path}", file=sys.stderr)
        return LOCK_BUSY_EXIT
    try:
        tree = _ProcessTree()
        process = tree.start(
            command,
            stdin=None if keep_stdin else subprocess.DEVNULL,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        try:
            return process.wait()
        except KeyboardInterrupt:
            tree.kill(process)
            return 130
    finally:
        lock.release()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m worker.job",
        description="排程鎖：持有鎖時執行命令；別的程序持有時不執行並以 75 結束",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    # tools/ops/watchdog.sh (parent_holds_lock, #448) tells that its parent is the
    # lock runner of its lock by this command line: `-m worker.job lock FILE --`,
    # FILE before `--`, no option between. Another shape, or a rename, makes the
    # watchdog stop removing the work directories that killed runs left; it only
    # logs lock_unverified. test_watchdog.py fails then (the tests that remove them).
    lock_parser = subparsers.add_parser("lock", help="持有 FILE 的鎖執行命令")
    lock_parser.add_argument(
        "--keep-stdin",
        action="store_true",
        help="命令讀這個程序的 stdin（deploy.sh 關閉 stdin 時結束，#340）",
    )
    lock_parser.add_argument("file")
    lock_parser.add_argument("run", nargs=argparse.REMAINDER, help="-- 命令 參數…")
    args = parser.parse_args(argv)
    command = args.run[1:] if args.run[:1] == ["--"] else args.run
    if not command:
        parser.error("lock needs a command after --")
    return run_locked(Path(args.file), command, args.keep_stdin)


if __name__ == "__main__":
    sys.exit(main())
