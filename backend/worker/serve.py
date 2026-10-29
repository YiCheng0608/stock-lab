"""The scheduler container's command: ``python -m worker.cli serve`` (#336).

It takes over from Windows Task Scheduler (tools/Register-WorkerSchedule.ps1,
tools/ops/Register-Watchdog.ps1): APScheduler starts, on Taipei time, the
commands those tasks ran.

- daily: Monday to Friday 18:30 and 21:30, ``worker.cli job daily --trigger
  scheduler --min-free-memory-gb 2``.
- news: every 2 hours on the hour, ``worker.cli job news --min-free-memory-gb
  1`` (news, then news-llm).
- watchdog: at :15 and :45, ``tools/ops/watchdog.sh``.
- monitor: every minute, one poll of the coordinator's event monitor
  ``tools/ops/monitor.sh --once`` (#338), only with ``--monitor`` (or
  STOCK_MONITOR) on or record-only. Its queue is the host directory
  ``--monitor-dir`` (compose bind mounts it at /coordination), where patrol.sh
  on Windows reads it; the job logs it reads stay in the data directory. It
  reaches Orca, on the Windows host, through the host's wake listener
  (tools/ops/wake_listener.py): http_wake.sh wakes, http_orca.sh lists the
  task worktrees.

Each run is a child process, and the job does what it did under Task
Scheduler: its lock (one job of a kind at a time), the checks before a run,
the time limit, the log and the exit code (worker.job, docs/OPERATIONS.md §6).
So an overlapping trigger starts the job too, and the job records
``already_running``; this scheduler keeps no lock of its own. As the task's
own limit did, a run still going 10 minutes past its job's limit is killed
with its process group. No ``--git-pull``: the image fixes the code.

The children end with this process (PR_SET_PDEATHSIG, worker.job): a killed
or stopped container leaves no job behind, and the next daily that holds the
lock closes the killed run's row at once (worker.schedule_runs).

``--now`` injects the time: the scheduler's clock starts there and runs on in
real time. The jobs see it too: daily gets ``--date`` of that Taipei day and
the watchdog ``WATCHDOG_NOW``. Log names and stamps stay on the real clock.

Linux only, like worker.job (the backend image, #333).
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import job

ROOT = job.ROOT
TAIPEI = job.TAIPEI
JOBS = ("daily", "news", "watchdog", "monitor")
DAILY_TIMES = "18:30,21:30"
NEWS_INTERVAL_HOURS = 2
WATCHDOG_MINUTES = "15,45"
# The values Register-WorkerSchedule.ps1 registered (OPERATIONS §6.2).
DAILY_MIN_FREE_MEMORY_GB = 2.0
NEWS_MIN_FREE_MEMORY_GB = 1.0
# Register-Watchdog.ps1's limit; daily and news have the job's own.
WATCHDOG_TIME_LIMIT_MINUTES = 10.0
# A poll past this is hung: monitor.sh takes a lock over after 10 minutes without a beat.
MONITOR_TIME_LIMIT_MINUTES = 10.0
MONITOR_MODES = ("off", "record-only", "on")
# The host directory compose bind mounts for the queue (docs/OPERATIONS.md §6.8).
MONITOR_DIR = "/coordination"
# Past the job's own limit, as Task Scheduler's limit was the job's plus 10 minutes.
BACKSTOP_MINUTES = 10.0
# An overlapping trigger still starts its job, which records already_running.
MAX_INSTANCES = 3


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-dir", help="資料目錄；預設 STOCK_DATA_DIR，再來是 ~/stock-lab-data"
    )
    parser.add_argument("--log-dir", help="日誌目錄；預設 <資料目錄>/logs")
    parser.add_argument("--claude-cli", help="Claude Code CLI，交給 daily、news 的 job")
    parser.add_argument(
        "--skip-news-llm", action="store_true", help="news 不跑 news-llm"
    )
    parser.add_argument(
        "--daily-times",
        default=DAILY_TIMES,
        help=f"daily 的台北時間 HH:MM，逗號分隔（預設 {DAILY_TIMES}，週一至週五）",
    )
    parser.add_argument(
        "--news-interval-hours",
        type=int,
        default=NEWS_INTERVAL_HOURS,
        help=f"news 間隔小時，整點起跑（預設 {NEWS_INTERVAL_HOURS}）",
    )
    parser.add_argument(
        "--watchdog-minutes",
        default=WATCHDOG_MINUTES,
        help=f"看門狗在每小時的哪幾分（預設 {WATCHDOG_MINUTES}）",
    )
    parser.add_argument(
        "--watchdog-dry-run", action="store_true", help="看門狗只判定、不留言"
    )
    parser.add_argument(
        "--monitor",
        choices=MONITOR_MODES,
        default=os.environ.get("STOCK_MONITOR") or "off",
        help="事件 monitor 每分鐘一輪：off（預設，或 STOCK_MONITOR）、record-only、on",
    )
    parser.add_argument(
        "--monitor-dir",
        default=MONITOR_DIR,
        help=f"monitor 的佇列目錄（主機 bind mount；預設 {MONITOR_DIR}）",
    )
    parser.add_argument(
        "--monitor-waker",
        default=str(ROOT / "tools" / "ops" / "http_wake.sh"),
        help="喚醒統籌的命令（monitor.sh --waker；預設 http_wake.sh，經主機的 wake listener）",
    )
    parser.add_argument(
        "--monitor-orca",
        default=str(ROOT / "tools" / "ops" / "http_orca.sh"),
        help="monitor 讀 task worktree 用的 orca（預設 http_orca.sh，經主機的 wake listener；none 不讀）",
    )
    parser.add_argument(
        "--daily-min-free-memory-gb",
        type=float,
        default=DAILY_MIN_FREE_MEMORY_GB,
        help=f"交給 job daily（預設 {DAILY_MIN_FREE_MEMORY_GB:g}）",
    )
    parser.add_argument(
        "--news-min-free-memory-gb",
        type=float,
        default=NEWS_MIN_FREE_MEMORY_GB,
        help=f"交給 job news（預設 {NEWS_MIN_FREE_MEMORY_GB:g}）",
    )
    parser.add_argument(
        "--daily-time-limit-minutes", type=float, help="交給 job daily（預設 150）"
    )
    parser.add_argument(
        "--news-time-limit-minutes", type=float, help="交給 job news（預設 90）"
    )
    parser.add_argument(
        "--now",
        help="時間注入：排程的時鐘從這個時間起算（ISO 8601，沒有時區時為台北時間）",
    )


def _daily_times(value: str) -> list[tuple[int, int]]:
    times = []
    for item in value.split(","):
        hour, _, minute = item.strip().partition(":")
        if not (hour.isdigit() and minute.isdigit()):
            raise ValueError(f"--daily-times: not HH:MM: {item!r}")
        if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
            raise ValueError(f"--daily-times: not a time of day: {item!r}")
        times.append((int(hour), int(minute)))
    return times


def _injected(value: str | None) -> datetime | None:
    if not value:
        return None
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=TAIPEI)


def argument_problem(args: argparse.Namespace) -> str | None:
    try:
        _daily_times(args.daily_times)
        _injected(args.now)
    except ValueError as exc:
        return str(exc)
    # argparse checks the choices of a given --monitor, not of the STOCK_MONITOR default.
    if args.monitor not in MONITOR_MODES:
        return f"--monitor (STOCK_MONITOR) must be one of {', '.join(MONITOR_MODES)}"
    if not 1 <= args.news_interval_hours <= 24:
        return "--news-interval-hours must be between 1 and 24"
    for name in ("daily_time_limit_minutes", "news_time_limit_minutes"):
        value = getattr(args, name)
        if value is not None and value <= 0:
            return f"--{name.replace('_', '-')} must be positive"
    for name in ("daily_min_free_memory_gb", "news_min_free_memory_gb"):
        if not 0 <= getattr(args, name) <= 1024:
            return f"--{name.replace('_', '-')} must be between 0 and 1024"
    return None


def triggers(args: argparse.Namespace) -> dict[str, object]:
    """The trigger of each job, on the scheduler's (injected) clock."""

    from apscheduler.triggers.combining import OrTrigger
    from apscheduler.triggers.cron import CronTrigger

    daily = [
        CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute, timezone=TAIPEI)
        for hour, minute in _daily_times(args.daily_times)
    ]
    out = {
        "daily": daily[0] if len(daily) == 1 else OrTrigger(daily),
        "news": CronTrigger(
            hour=f"*/{args.news_interval_hours}", minute=0, timezone=TAIPEI
        ),
        "watchdog": CronTrigger(minute=args.watchdog_minutes, timezone=TAIPEI),
    }
    if args.monitor != "off":
        # monitor.sh --interval's 60 seconds, one poll per run.
        out["monitor"] = CronTrigger(minute="*", timezone=TAIPEI)
    return out


def shifted(trigger, offset: timedelta):
    """TRIGGER on a clock OFFSET ahead of the real one (--now)."""

    if not offset:
        return trigger
    from apscheduler.triggers.base import BaseTrigger

    class Shifted(BaseTrigger):
        def get_next_fire_time(self, previous_fire_time, now):
            previous = previous_fire_time + offset if previous_fire_time else None
            upcoming = trigger.get_next_fire_time(previous, now + offset)
            return None if upcoming is None else upcoming - offset

        def __str__(self) -> str:
            return f"{trigger} shifted by {offset}"

    return Shifted()


class Serve:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.data_dir = job.resolve_data_dir(args.data_dir)
        self.log_dir = Path(os.path.abspath(args.log_dir or self.data_dir / "logs"))
        injected = _injected(args.now)
        self.offset = injected - datetime.now(TAIPEI) if injected else timedelta(0)
        self.tree = job._ProcessTree()
        self._running: dict[int, subprocess.Popen] = {}
        self._lock = threading.Lock()
        self._stopping = False

    def now(self) -> datetime:
        """The scheduler's clock: the real time, moved by --now."""

        return datetime.now(TAIPEI) + self.offset

    def say(self, event: str, **fields) -> None:
        values = " ".join(f"{key}={value}" for key, value in fields.items())
        print(f"{self.now().isoformat()} serve {event} {values}".rstrip(), flush=True)

    def command(self, name: str, at: datetime) -> tuple[list[str], dict[str, str]]:
        """The command of NAME and its environment, as Task Scheduler ran it."""

        args = self.args
        environment = {
            **os.environ,
            **job.data_environment(self.data_dir),
            "PYTHONPATH": str(ROOT / "backend"),
        }
        environment.pop(job.JOB_LOCK_ENV, None)
        if name == "monitor":
            argv = [
                shutil.which("bash") or "/bin/bash",
                str(ROOT / "tools" / "ops" / "monitor.sh"),
                "--once",
                "--data-dir",
                str(self.data_dir),
                "--queue-dir",
                args.monitor_dir,
                "--python",
                sys.executable,
                "--orca",
                args.monitor_orca,
                "--waker",
                args.monitor_waker,
            ]
            if args.monitor == "record-only":
                argv.append("--record-only")
            if self.offset:
                environment["MONITOR_NOW"] = str(int(at.timestamp()))
            return argv, environment
        if name == "watchdog":
            argv = [
                shutil.which("bash") or "/bin/bash",
                str(ROOT / "tools" / "ops" / "watchdog.sh"),
                "--data-dir",
                str(self.data_dir),
                "--python",
                sys.executable,
            ]
            if args.monitor != "off":
                argv += ["--monitor-dir", args.monitor_dir]
            if args.watchdog_dry_run:
                argv.append("--dry-run")
            if self.offset:
                environment["WATCHDOG_NOW"] = str(int(at.timestamp()))
            return argv, environment
        argv = [
            *job.worker_command(["job", name]),
            "--trigger",
            "scheduler",
            "--data-dir",
            str(self.data_dir),
            "--log-dir",
            str(self.log_dir),
            "--min-free-memory-gb",
            f"{getattr(args, f'{name}_min_free_memory_gb'):g}",
        ]
        if args.claude_cli:
            argv += ["--claude-cli", args.claude_cli]
        if name == "news" and args.skip_news_llm:
            argv.append("--skip-news-llm")
        limit = getattr(args, f"{name}_time_limit_minutes")
        if limit is not None:
            argv += ["--time-limit-minutes", f"{limit:g}"]
        if self.offset and name == "daily":
            argv += ["--date", at.date().isoformat()]
        return argv, environment

    def backstop(self, name: str) -> float:
        """Seconds after which serve kills a run of NAME that is still going."""

        if name == "watchdog":
            return WATCHDOG_TIME_LIMIT_MINUTES * 60
        if name == "monitor":
            return MONITOR_TIME_LIMIT_MINUTES * 60
        limit = getattr(self.args, f"{name}_time_limit_minutes")
        minutes = limit or job.TIME_LIMIT_MINUTES[name]
        return (minutes + BACKSTOP_MINUTES) * 60

    def fire(self, name: str) -> int | None:
        """Run NAME once and wait for it; returns its exit code (None if killed)."""

        at = self.now()
        argv, environment = self.command(name, at)
        with self._lock:
            if self._stopping:
                return None
            process = self.tree.start(
                argv,
                stdin=subprocess.DEVNULL,
                cwd=ROOT / "backend",
                env=environment,
            )
            self._running[process.pid] = process
        started = time.monotonic()
        self.say("start", job=name, pid=process.pid)
        code: int | None
        try:
            code = process.wait(timeout=self.backstop(name))
        except subprocess.TimeoutExpired:
            self.tree.kill(process)
            code = None
            self.say(
                "killed",
                job=name,
                pid=process.pid,
                reason=f"still_running_after_{self.backstop(name) / 60:g}_minutes",
            )
        finally:
            with self._lock:
                self._running.pop(process.pid, None)
        self.say(
            "end",
            job=name,
            pid=process.pid,
            exit="killed" if code is None else code,
            seconds=round(time.monotonic() - started),
        )
        return code

    def stop(self) -> None:
        """End every running job with its process group (docker stop)."""

        with self._lock:
            self._stopping = True
            running = list(self._running.values())
        for process in running:
            self.say("stop_kill", pid=process.pid)
            self.tree.kill(process)

    def scheduler(self):
        from apscheduler.executors.pool import ThreadPoolExecutor
        from apscheduler.schedulers.blocking import BlockingScheduler

        scheduler = BlockingScheduler(
            timezone=TAIPEI,
            executors={"default": ThreadPoolExecutor(max_workers=10)},
            job_defaults={
                "coalesce": True,
                "max_instances": MAX_INSTANCES,
                # As Task Scheduler's StartWhenAvailable: a time missed while the
                # machine slept runs once when it wakes.
                "misfire_grace_time": None,
            },
        )
        for name, trigger in triggers(self.args).items():
            scheduler.add_job(
                self.fire,
                shifted(trigger, self.offset),
                args=[name],
                id=name,
                name=name,
            )
        return scheduler

    def next_times(self) -> dict[str, datetime | None]:
        """The next time of each job on the scheduler's clock."""

        now = self.now()
        return {
            name: trigger.get_next_fire_time(None, now)
            for name, trigger in triggers(self.args).items()
        }


def run(args: argparse.Namespace) -> int:
    """``worker.cli serve``: schedule the jobs until stopped."""

    problem = job.platform_problem("worker.serve")
    if problem:
        print(problem, file=sys.stderr)
        return job.PLATFORM_EXIT
    logging.basicConfig(
        level=logging.WARNING, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    serve = Serve(args)
    serve.log_dir.mkdir(parents=True, exist_ok=True)
    scheduler = serve.scheduler()

    def stop(signum, _frame) -> None:
        serve.say("stopping", signal=signal.Signals(signum).name)
        serve.stop()
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    serve.say(
        "ready",
        data=serve.data_dir,
        offset_seconds=round(serve.offset.total_seconds()),
        **{
            f"next_{name}": moment.isoformat() if moment else "none"
            for name, moment in serve.next_times().items()
        },
    )
    scheduler.start()
    serve.say("stopped")
    return 0
