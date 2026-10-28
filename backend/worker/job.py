"""Scheduled worker jobs: ``python -m worker.cli job daily|news`` (#313).

What tools/Invoke-WorkerJob.ps1 did, together with what the Task Scheduler task
settings did (a run time limit, one instance at a time), so that any scheduler
only has to start one command:

- One job of each kind at a time per data directory: an exclusive ``fcntl``
  lock on ``<data>/locks/<job>.lock``. The OS drops it when its holder ends, however it ends, so a killed job leaves
  nothing to clean up. A second job is skipped with reason ``already_running``;
  daily also records that row in schedule_runs.
- The checks before a run: free physical memory below --min-free-memory-gb
  (``low_memory``), a git operation in progress in this checkout, i.e.
  index.lock or MERGE_HEAD (``git_busy``), and with --git-pull a failed
  ``git pull --ff-only`` (``git_pull_failed``). daily records the skip through
  ``worker.cli daily --skip-reason``; news only logs it.
- The worker CLI runs as a child process within the job's time limit (daily
  2.5 hours; news 90 minutes for news and news-llm together). The child and
  everything it starts end with the job: the child gets SIGKILL when the job
  dies (PR_SET_PDEATHSIG). The run row of a killed daily therefore
  names a dead PID, and the next run closes it at once (schedule_runs).
- The dated log ``<logs>/<job>-YYYYMMDD.log`` (Taipei date) with the layout of
  docs/OPERATIONS.md §6.3, the exit code, and removing logs older than
  --log-retention-days.

The news job runs ``worker.cli news`` and then ``worker.cli news-llm``; the
job's exit code is news's alone, news-llm's goes to the log as
``news_llm_exit``.

Only the standard library is imported here: the watchdog takes its lock
through the same code without the backend's dependencies, with
``python -m worker.job lock <file> -- <command> ...``.

Linux only, as in the backend image (#333): the Windows branches (msvcrt, job
objects, GlobalMemoryStatusEx, pythonw.exe) went with the Task Scheduler
wrapper. Elsewhere ``job`` and ``lock`` refuse to start (``PLATFORM_EXIT``).
"""

from __future__ import annotations

import argparse
import ctypes
import os
import signal
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
# `job` and `lock` on a system other than Linux (EX_UNAVAILABLE).
PLATFORM_EXIT = 69
NEWLINE = os.linesep


def platform_problem() -> str | None:
    if sys.platform.startswith("linux"):
        return None
    return (
        f"worker.job runs on Linux only (the backend image, #333), not {sys.platform}"
    )


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
    parser.add_argument(
        "--git-pull",
        action="store_true",
        help="起跑前在這個 checkout 跑 git pull --ff-only",
    )
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

    def git_pull(self) -> tuple[str, bool]:
        try:
            completed = subprocess.run(
                ["git", "-C", str(ROOT), "pull", "--ff-only"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=max(1.0, min(600.0, self.deadline - time.monotonic())),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"git pull failed to run: {exc}", False
        output = completed.stdout.decode("utf-8", errors="replace").strip()
        return output, completed.returncode == 0

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
        if self.args.git_pull:
            output, pulled = self.git_pull()
            if output:
                self.log(f"--- git pull --ff-only{NEWLINE}{output}")
            if not pulled:
                return "git_pull_failed", detail
        return None, detail

    def _run(self, locked: bool, lock_file: Path, free_mb: int | None):
        args, job = self.args, self.job
        run_news_llm = job == "news" and not args.skip_news_llm
        news_llm_exit = None
        if job == "news":
            news_llm_exit = "not_run" if run_news_llm else "disabled"
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


def run_locked(path: Path, command: list[str]) -> int:
    """``worker.job lock``: run COMMAND while holding the lock on PATH."""

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
