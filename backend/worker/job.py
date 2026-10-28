"""Scheduled worker jobs: ``python -m worker.cli job daily|news`` (#313).

What tools/Invoke-WorkerJob.ps1 did, together with what the Task Scheduler task
settings did (a run time limit, one instance at a time), so that any scheduler
only has to start one command:

- One job of each kind at a time per data directory: an exclusive lock on
  ``<data>/locks/<job>.lock`` (``msvcrt`` on Windows, ``fcntl`` elsewhere). The
  OS drops it when its holder ends, however it ends, so a killed job leaves
  nothing to clean up. A second job is skipped with reason ``already_running``;
  daily also records that row in schedule_runs.
- The checks before a run: free physical memory below --min-free-memory-gb
  (``low_memory``) and a git operation in progress in this checkout, i.e.
  index.lock or MERGE_HEAD (``git_busy``). daily records the skip through
  ``worker.cli daily --skip-reason``; news only logs it.
- The checkout is never updated here: it runs the tag tools/ops/deploy.sh
  checked out (#314). The job reads its HEAD and tag, logs them, and gives them
  to daily (``--git-head``/``--git-tag``) for the run's summary_json. A task
  registered before #314 still passes --git-pull; it is accepted and ignored.
- The worker CLI runs as a child process within the job's time limit (daily
  2.5 hours; news 90 minutes for news and news-llm together). The child and
  everything it starts end with the job: on Windows they are in a job object
  that is killed when its last handle closes, on Linux the child gets SIGKILL
  when the job dies (PR_SET_PDEATHSIG). The run row of a killed daily therefore
  names a dead PID, and the next run closes it at once (schedule_runs).
- The dated log ``<logs>/<job>-YYYYMMDD.log`` (Taipei date) with the layout of
  docs/OPERATIONS.md §6.3, the exit code, and removing logs older than
  --log-retention-days.

The news job runs ``worker.cli news`` and then ``worker.cli news-llm``; the
job's exit code is news's alone, news-llm's goes to the log as
``news_llm_exit``.

Only the standard library is imported here: the watchdog (Git Bash) takes its
lock through the same code without the backend's dependencies, with
``python -m worker.job lock <file> -- <command> ...``.
"""

from __future__ import annotations

import argparse
import ctypes
import functools
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO, Sequence

IS_WINDOWS = sys.platform == "win32"
ROOT = Path(__file__).resolve().parents[2]
TAIPEI = timezone(timedelta(hours=8))
JOBS = ("daily", "news")
TRIGGERS = ("scheduler", "manual", "simulation")
# daily: the abandoned-run limit in worker.schedule_runs, clearly shorter than
# the 3 hours between the 18:30 and 21:30 triggers. news: well inside its
# 2-hour interval.
TIME_LIMIT_MINUTES = {"daily": 150.0, "news": 90.0}
DEFAULT_MIN_FREE_MEMORY_GB = 8.0
DEFAULT_LOG_RETENTION_DAYS = 90
LOCK_SKIP_REASON = "already_running"
# `lock`: exit code when another process holds the lock (EX_TEMPFAIL).
LOCK_BUSY_EXIT = 75
# A step killed at the time limit counts as failed.
TIMEOUT_EXIT = 1
NEWLINE = os.linesep

CREATE_SUSPENDED = 0x00000004
CREATE_NO_WINDOW = 0x08000000


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
    """For ``worker.cli job``: the data paths app.config must see when imported.

    app.config reads STOCK_DATA_DIR and creates that directory on import; without
    this a scheduled task (no STOCK_* in its environment) would create ``data/``
    in the checkout. Any other command gets nothing.
    """

    if not argv or argv[0] != "job":
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
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            if IS_WINDOWS:
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        return True

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            if IS_WINDOWS:
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(fd)


class _ProcessTree:
    """Start one child; it and everything it starts end when this process ends."""

    def __init__(self) -> None:
        self._job = _windows_job() if IS_WINDOWS else None

    def start(self, argv: list[str], *, hidden: bool, **kwargs) -> subprocess.Popen:
        if IS_WINDOWS:
            # Suspended until it is in the job object, so nothing it starts escapes.
            flags = CREATE_SUSPENDED | (CREATE_NO_WINDOW if hidden else 0)
            process = subprocess.Popen(argv, creationflags=flags, **kwargs)
            try:
                _windows_adopt(self._job, process.pid)
            except OSError:
                process.kill()
                process.wait()
                raise
            return process
        if sys.platform.startswith("linux"):
            kwargs["preexec_fn"] = _die_with_parent(os.getpid())
        return subprocess.Popen(argv, start_new_session=True, **kwargs)

    def kill(self, process: subprocess.Popen) -> None:
        if IS_WINDOWS:
            _kernel32().TerminateJobObject(self._job, TIMEOUT_EXIT)
        else:
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


@functools.cache
def _kernel32():
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.GlobalMemoryStatusEx.argtypes = (ctypes.c_void_p,)
    return kernel32


def _windows_job() -> int:
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimits),
            ("IoInfo", ctypes.c_uint64 * 6),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = _kernel32()
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = ExtendedLimits()
    job_object_limit_kill_on_job_close = 0x2000
    limits.BasicLimitInformation.LimitFlags = job_object_limit_kill_on_job_close
    job_object_extended_limit_information = 9
    if not kernel32.SetInformationJobObject(
        job,
        job_object_extended_limit_information,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    # The handle stays open for the life of this process; when the process
    # ends, however it ends, the system closes it and kills the job.
    return job


def _windows_adopt(job: int, pid: int) -> None:
    """Put the suspended process PID in JOB, then let it run."""

    from ctypes import wintypes

    kernel32 = _kernel32()
    ntdll = ctypes.WinDLL("ntdll")
    ntdll.NtResumeProcess.argtypes = (wintypes.HANDLE,)
    process_terminate, process_set_quota, process_suspend_resume = 0x1, 0x100, 0x800
    handle = kernel32.OpenProcess(
        process_terminate | process_set_quota | process_suspend_resume, False, pid
    )
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not kernel32.AssignProcessToJobObject(job, handle):
            raise ctypes.WinError(ctypes.get_last_error())
        status = ntdll.NtResumeProcess(handle)
        if status != 0:
            raise OSError(f"NtResumeProcess failed: NTSTATUS {status & 0xFFFFFFFF:#x}")
    finally:
        kernel32.CloseHandle(handle)


def free_memory_mb() -> int | None:
    """Available physical memory, never through WMI (#246); None when unknown."""

    if IS_WINDOWS:
        from ctypes import wintypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_uint64),
                ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64),
                ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64),
                ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64),
            ]

        status = MemoryStatus(dwLength=ctypes.sizeof(MemoryStatus))
        if not _kernel32().GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return int(status.ullAvailPhys // 2**20)
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


def git_executable() -> str:
    return os.environ.get("STOCK_GIT") or "git"


def _git(directory: Path, *args: str) -> str | None:
    """One read-only git command on DIRECTORY; its output, or None when it fails."""

    try:
        completed = subprocess.run(
            [git_executable(), f"--git-dir={directory}", *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW if IS_WINDOWS else 0,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = completed.stdout.decode("utf-8", errors="replace").strip()
    return output if completed.returncode == 0 and output else None


def checkout_version(root: Path) -> tuple[str | None, str | None]:
    """HEAD and the tag at HEAD of the checkout at ROOT; None for what is unknown.

    git is given the checkout's own git dir, so a tree that is no repository
    never reads one above it (#207).
    """

    directory = git_dir(root)
    if directory is None:
        return None, None
    head = _git(directory, "rev-parse", "--verify", "HEAD")
    if head is None:
        return None, None
    return head, _git(directory, "describe", "--tags", "--exact-match", "HEAD")


def child_python() -> str:
    """The console interpreter: the registered task may run pythonw.exe (no window)."""

    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        console = executable.with_name("python.exe")
        if console.is_file():
            return str(console)
    return str(executable)


def worker_command(step_args: list[str]) -> list[str]:
    return [child_python(), "-X", "utf8", "-m", "worker.cli", *step_args]


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
        "--claude-cli", help="原生 claude.exe，以 STOCK_CLAUDE_CLI 傳給子程序"
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
                hidden=True,
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
        head, tag = checkout_version(ROOT)
        self.log(f"--- checkout HEAD={head or 'unknown'} tag={tag or 'none'}")
        if args.git_pull:
            self.log(
                "--- --git-pull ignored: the checkout stays at its deployed tag (#314)"
            )
        skip_reason, detail = self._skip_reason(locked, lock_file, free_mb)
        if skip_reason:
            self.log(f"===== skipped reason={skip_reason} ({detail})")
        if skip_reason and job != "daily":
            # Only daily records a skipped run in the database.
            code = 0
        else:
            step_args = [job]
            if job == "daily":
                step_args += ["--trigger", args.trigger]
                if args.force:
                    step_args.append("--force")
                if head:
                    step_args += ["--git-head", head]
                if tag:
                    step_args += ["--git-tag", tag]
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

    job = _Job(args)
    code, news_llm_exit = job.run()
    summary = f"{args.job} exit={code}"
    if news_llm_exit is not None:
        summary += f" news_llm_exit={news_llm_exit}"
    if sys.stdout is not None:  # pythonw.exe has none
        print(f"{summary} log={job.log_path}", flush=True)
    return code


def run_locked(path: Path, command: list[str]) -> int:
    """``worker.job lock``: run COMMAND while holding the lock on PATH."""

    lock = FileLock(path)
    if not lock.acquire():
        print(f"locked: {path}", file=sys.stderr)
        return LOCK_BUSY_EXIT
    try:
        tree = _ProcessTree()
        # Explicit handles: without them a Windows child gets none of a pipe's.
        process = tree.start(
            command,
            hidden=False,
            stdin=subprocess.DEVNULL,
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
    lock_parser = subparsers.add_parser("lock", help="持有 FILE 的鎖執行命令")
    lock_parser.add_argument("file")
    lock_parser.add_argument("run", nargs=argparse.REMAINDER, help="-- 命令 參數…")
    args = parser.parse_args(argv)
    command = args.run[1:] if args.run[:1] == ["--"] else args.run
    if not command:
        parser.error("lock needs a command after --")
    return run_locked(Path(args.file), command)


if __name__ == "__main__":
    sys.exit(main())
