"""The scheduler container's command ``python -m worker.cli serve`` (backend/worker/serve.py, #336).

The schedule and the commands are checked without starting anything. The other
tests run serve in a project tree of its own (test_worker_job.Tree plus copies of
serve.py and the watchdog): a fake ``worker.cli`` routes ``serve`` and ``job`` to
those copies and scripts the steps, so no worker, network or Claude call is
involved; only the docker kill and the 21:30 -> 23:00 scenarios run the real daily
worker, on the verify fixture database with the outside-facing steps faked
(job_daily_child.py).

Like the job, serve runs on Linux only (#333): run these in the image.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import worker.job as job
import worker.serve as serve
from test_coordinator_scripts import FAKE_GH
from test_worker_job import (
    FAKE_CLI as JOB_FAKE_CLI,
    FIXTURES,
    ON_LINUX,
    Tree,
    _restamp,
    _watchdog,
    end_line,
    skipped_line,
    wait_dead,
)

ROOT = Path(__file__).resolve().parents[2]
TAIPEI = job.TAIPEI
# Free memory is not these tests' subject (the job's tests cover low_memory).
NO_MEMORY_CHECK = ("--daily-min-free-memory-gb", "0", "--news-min-free-memory-gb", "0")

SERVE_CLI = JOB_FAKE_CLI.replace(
    "\n\nmain()\n",
    r"""

def serve_or_real():
    argv = sys.argv[1:]
    if argv[:1] == ["serve"]:
        from worker import serve

        parser = argparse.ArgumentParser(prog="worker.cli")
        serve.add_arguments(parser.add_subparsers(dest="command").add_parser("serve"))
        args = parser.parse_args(argv)
        problem = serve.argument_problem(args)
        if problem:
            parser.error(problem)
        sys.exit(serve.run(args))
    real = os.environ.get("FAKE_REAL_DAILY")
    if real and argv[:1] == ["daily"]:
        # The real worker in this same process: PR_SET_PDEATHSIG survives exec.
        env = {**os.environ, "PYTHONPATH": os.environ["FAKE_REAL_BACKEND"]}
        os.execve(sys.executable, [sys.executable, "-X", "utf8", real, *argv], env)


serve_or_real()
main()
""",
)
assert SERVE_CLI != JOB_FAKE_CLI


# The event monitor and what it sources or runs (#338).
MONITOR_SCRIPTS = (
    "monitor.sh",
    "event_queue.py",
    "coordinator_lib.sh",
    "coordinator_json.py",
    "gh_auth.sh",
    "orca_wake.sh",
    "http_wake.sh",
    "http_orca.sh",
)


class ServeTree(Tree):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        worker = self.backend / "worker"
        shutil.copyfile(ROOT / "backend" / "worker" / "serve.py", worker / "serve.py")
        (worker / "cli.py").write_text(SERVE_CLI, encoding="utf-8")
        ops = self.project / "tools" / "ops"
        ops.mkdir(parents=True)
        for name in MONITOR_SCRIPTS + ("watchdog.sh", "watchdog_helper.py"):
            shutil.copyfile(ROOT / "tools" / "ops" / name, ops / name)

    def start_serve(self, *args: str, extra_env=None, **fake) -> subprocess.Popen:
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "worker.cli",
                "serve",
                "--data-dir",
                str(self.data),
                *NO_MEMORY_CHECK,
                *args,
            ],
            cwd=self.backend,
            env=self.environment(extra_env, **fake),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )


class Output:
    """The lines a serve process prints (its jobs share its stdout)."""

    def __init__(self, process: subprocess.Popen) -> None:
        self.lines: list[str] = []
        self._changed = threading.Condition()
        threading.Thread(target=self._read, args=(process.stdout,), daemon=True).start()

    def _read(self, stream) -> None:
        for line in stream:
            with self._changed:
                self.lines.append(line.rstrip("\n"))
                self._changed.notify_all()

    def wait_for(self, pattern: str, timeout: float = 90) -> str:
        regex = re.compile(pattern)
        deadline = time.monotonic() + timeout
        with self._changed:
            while True:
                found = next((line for line in self.lines if regex.search(line)), None)
                if found is not None:
                    return found
                left = deadline - time.monotonic()
                if left <= 0:
                    raise AssertionError(
                        f"no line matching {pattern!r} within {timeout} s:\n"
                        + "\n".join(self.lines)
                    )
                self._changed.wait(left)


@pytest.fixture
def serve_tree(tmp_path) -> ServeTree:
    if not ON_LINUX:
        pytest.skip("worker.serve runs on Linux only (#333)")
    return ServeTree(tmp_path)


def serve_args(*argv: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    serve.add_arguments(parser)
    return parser.parse_args(list(argv))


def in_tree(tree: ServeTree, monkeypatch, **fake) -> None:
    """Run serve in this process against TREE: its commands start the tree's job."""

    monkeypatch.setattr(serve, "ROOT", tree.project)
    for name in ("STOCK_CLAUDE_CLI", "PYTHONPATH"):
        monkeypatch.delenv(name, raising=False)
    for name, value in tree.environment(**fake).items():
        if os.environ.get(name) != value:
            monkeypatch.setenv(name, value)


def stop(process: subprocess.Popen) -> int:
    process.send_signal(signal.SIGTERM)
    return process.wait(timeout=60)


# The schedule (docs/ops/platform/windows.md: the Task Scheduler triggers) -----------------------


def fire_times(trigger, start: datetime, end: datetime) -> list[datetime]:
    times, previous, now = [], None, start
    while True:
        moment = trigger.get_next_fire_time(previous, now)
        if moment is None or moment >= end:
            return times
        times.append(moment.astimezone(TAIPEI))
        previous = now = moment


def test_the_triggers_fire_at_the_schedule_times():
    triggers = serve.triggers(serve_args())
    monday = datetime(2026, 10, 19, tzinfo=TAIPEI)
    week = (monday, monday + timedelta(days=7))
    daily = fire_times(triggers["daily"], *week)
    # #466: 21:30, with 23:00 as the retry (or the institutional refetch); no 18:30.
    assert [moment.strftime("%a %H:%M") for moment in daily] == [
        f"{day} {hm}"
        for day in ("Mon", "Tue", "Wed", "Thu", "Fri")
        for hm in ("21:30", "23:00")
    ]
    news = fire_times(triggers["news"], *week)
    assert news == [monday + timedelta(hours=2 * index) for index in range(84)]
    watchdog = fire_times(triggers["watchdog"], *week)
    assert watchdog == [
        monday + timedelta(minutes=15 + 30 * index) for index in range(7 * 48)
    ]


def test_the_triggers_follow_the_options():
    triggers = serve.triggers(
        serve_args(
            "--daily-times",
            "17:05",
            "--news-interval-hours",
            "3",
            "--watchdog-minutes",
            "0",
        )
    )
    friday = datetime(2026, 10, 23, tzinfo=TAIPEI)
    day = (friday, friday + timedelta(days=1))
    assert [t.strftime("%H:%M") for t in fire_times(triggers["daily"], *day)] == [
        "17:05"
    ]
    assert [t.hour for t in fire_times(triggers["news"], *day)] == list(range(0, 24, 3))
    assert len(fire_times(triggers["watchdog"], *day)) == 24


@pytest.mark.parametrize("hours", range(1, serve.NEWS_INTERVAL_MAX_HOURS + 1))
def test_every_allowed_news_interval_makes_a_job(tmp_path, hours):
    """#368: 24 used to pass the argument check and then crash on APScheduler's */24."""

    args = serve_args(
        "--data-dir", str(tmp_path / "data"), "--news-interval-hours", str(hours)
    )
    assert serve.argument_problem(args) is None
    runner = serve.Serve(args)
    assert {scheduled.id for scheduled in runner.scheduler().get_jobs()} == {
        "daily",
        "news",
        "watchdog",
    }
    assert all(moment is not None for moment in runner.next_times().values())
    friday = datetime(2026, 10, 23, tzinfo=TAIPEI)
    news = fire_times(serve.triggers(args)["news"], friday, friday + timedelta(days=1))
    assert [moment.hour for moment in news] == list(range(0, 24, hours))
    assert {moment.minute for moment in news} == {0}


def test_a_news_interval_starts_again_at_midnight_every_day():
    midnight = datetime(2026, 10, 23, tzinfo=TAIPEI)

    def news(hours: int, days: int) -> list[datetime]:
        trigger = serve.triggers(serve_args("--news-interval-hours", str(hours)))[
            "news"
        ]
        return fire_times(trigger, midnight, midnight + timedelta(days=days))

    # 5 does not divide the day: the last run of a day is 4 hours before the next.
    assert [moment.strftime("%d %H") for moment in news(5, 2)] == [
        f"{day} {hour:02d}" for day in (23, 24) for hour in (0, 5, 10, 15, 20)
    ]
    # A whole day is one run, at 0:00.
    assert news(24, 3) == [midnight + timedelta(days=index) for index in range(3)]


def test_an_injected_clock_moves_the_triggers():
    real = datetime(2026, 10, 29, 3, 0, tzinfo=timezone.utc)
    injected = datetime(2026, 10, 19, 21, 29, 50, tzinfo=TAIPEI)
    offset = injected - real
    daily = serve.triggers(serve_args())["daily"]
    moved = serve.shifted(daily, offset)
    # 10 seconds after the real now, the scheduler's clock reaches 21:30.
    first = moved.get_next_fire_time(None, real)
    assert first == real + timedelta(seconds=10)
    second = moved.get_next_fire_time(first, first)
    assert (second + offset).astimezone(TAIPEI) == datetime(
        2026, 10, 19, 23, 0, tzinfo=TAIPEI
    )
    assert serve.shifted(daily, timedelta(0)) is daily


# The commands (docs/ops/platform/windows.md: what Task Scheduler ran) ---------------------------


def test_the_commands_are_the_ones_task_scheduler_ran(tmp_path, monkeypatch):
    monkeypatch.setenv(job.JOB_LOCK_ENV, "/inherited/daily.lock")
    data = tmp_path / "data"
    runner = serve.Serve(
        serve_args("--data-dir", str(data), "--claude-cli", "/usr/local/bin/claude")
    )
    at = runner.now()
    python = [sys.executable, "-X", "utf8", "-m", "worker.cli", "job"]
    common = ["--trigger", "scheduler", "--data-dir", str(data)]
    common += ["--log-dir", str(data / "logs")]
    daily, environment = runner.command("daily", at)
    assert daily == [
        *python,
        "daily",
        *common,
        "--min-free-memory-gb",
        "2",
        "--claude-cli",
        "/usr/local/bin/claude",
        # #466: a scheduled daily ends before the next trigger.
        "--time-limit-minutes",
        "75",
    ]
    assert environment["STOCK_DATA_DIR"] == str(data)
    assert environment["STOCK_DB_PATH"] == str(data / "stock.db")
    assert environment["PYTHONPATH"] == str(ROOT / "backend")
    # Only the job holding the lock tells its worker; serve holds none.
    assert job.JOB_LOCK_ENV not in environment
    assert "WATCHDOG_NOW" not in environment
    news, _ = runner.command("news", at)
    assert news == [
        *python,
        "news",
        *common,
        "--min-free-memory-gb",
        "1",
        "--claude-cli",
        "/usr/local/bin/claude",
    ]
    watchdog, _ = runner.command("watchdog", at)
    assert Path(watchdog[0]).stem.lower() == "bash"
    assert watchdog[1:] == [
        str(ROOT / "tools" / "ops" / "watchdog.sh"),
        "--data-dir",
        str(data),
        "--python",
        sys.executable,
    ]
    switched = serve.Serve(
        serve_args(
            "--data-dir",
            str(data),
            "--skip-news-llm",
            "--watchdog-dry-run",
            "--daily-time-limit-minutes",
            "0.5",
            "--news-time-limit-minutes",
            "3",
        )
    )
    assert switched.command("news", at)[0][-3:] == [
        "--skip-news-llm",
        "--time-limit-minutes",
        "3",
    ]
    assert switched.command("daily", at)[0][-2:] == ["--time-limit-minutes", "0.5"]
    assert switched.command("watchdog", at)[0][-1] == "--dry-run"


def test_an_injected_clock_reaches_the_daily_target_and_the_watchdog(tmp_path):
    runner = serve.Serve(
        serve_args("--data-dir", str(tmp_path), "--now", "2026-10-19T21:29:50")
    )
    at = runner.now()
    assert abs(at - datetime(2026, 10, 19, 21, 29, 50, tzinfo=TAIPEI)) < timedelta(
        seconds=30
    )
    assert runner.command("daily", at)[0][-2:] == ["--date", "2026-10-19"]
    assert "--date" not in runner.command("news", at)[0]
    _, environment = runner.command("watchdog", at)
    assert environment["WATCHDOG_NOW"] == str(int(at.timestamp()))


def test_the_backstop_is_ten_minutes_past_the_job_limit(tmp_path):
    runner = serve.Serve(serve_args("--data-dir", str(tmp_path)))
    assert runner.backstop("daily") == 85 * 60
    assert runner.backstop("news") == 100 * 60
    assert runner.backstop("watchdog") == 10 * 60
    short = serve.Serve(
        serve_args("--data-dir", str(tmp_path), "--daily-time-limit-minutes", "1")
    )
    assert short.backstop("daily") == 11 * 60


def test_a_stuck_scheduled_daily_is_killed_before_the_next_trigger(tmp_path):
    """#466: 23:00 is 90 minutes after 21:30, inside the job's own 150-minute limit.

    A 21:30 run that hangs must end, backstop included, before 23:00: otherwise
    23:00 finds the lock held, records already_running and the day is not retried.
    """

    runner = serve.Serve(serve_args("--data-dir", str(tmp_path)))
    times = serve._daily_times(serve.DAILY_TIMES)
    gaps = [
        (later[0] - earlier[0]) * 60 + later[1] - earlier[1]
        for earlier, later in zip(times, times[1:])
    ]
    assert gaps == [90]
    assert runner.backstop("daily") < min(gaps) * 60
    # A manual `job daily` keeps the job's own limit (long catch-up runs).
    assert job.TIME_LIMIT_MINUTES["daily"] == 150


def test_the_monitor_polls_every_minute_only_when_switched_on(monkeypatch):
    assert "monitor" not in serve.triggers(serve_args())
    friday = datetime(2026, 10, 23, tzinfo=TAIPEI)
    for mode in ("on", "record-only"):
        monitor = serve.triggers(serve_args("--monitor", mode))["monitor"]
        polls = fire_times(monitor, friday, friday + timedelta(days=1))
        assert polls == [friday + timedelta(minutes=m) for m in range(24 * 60)]
    # Compose sets STOCK_MONITOR (docker-compose.yml); an empty value is off.
    monkeypatch.setenv("STOCK_MONITOR", "on")
    assert serve_args().monitor == "on"
    monkeypatch.setenv("STOCK_MONITOR", "")
    assert serve_args().monitor == "off"
    monkeypatch.setenv("STOCK_MONITOR", "yes")
    assert "STOCK_MONITOR" in serve.argument_problem(serve_args())


def test_the_monitor_command_is_one_poll_of_monitor_sh(tmp_path):
    data = tmp_path / "data"
    runner = serve.Serve(serve_args("--data-dir", str(data), "--monitor", "on"))
    at = runner.now()
    monitor, environment = runner.command("monitor", at)
    assert Path(monitor[0]).stem.lower() == "bash"
    assert monitor[1:] == [
        str(ROOT / "tools" / "ops" / "monitor.sh"),
        "--once",
        "--data-dir",
        str(data),
        "--queue-dir",
        "/coordination",
        "--python",
        sys.executable,
        # Orca is on the Windows host: both go through its wake listener (B3).
        "--orca",
        str(ROOT / "tools" / "ops" / "http_orca.sh"),
        "--waker",
        str(ROOT / "tools" / "ops" / "http_wake.sh"),
    ]
    assert "MONITOR_NOW" not in environment
    # The watchdog reads the monitor's heartbeat where the monitor writes it.
    watchdog, _ = runner.command("watchdog", at)
    assert watchdog[-2:] == ["--monitor-dir", "/coordination"]
    assert (
        "--monitor-dir"
        not in serve.Serve(serve_args("--data-dir", str(data))).command("watchdog", at)[
            0
        ]
    )
    assert runner.backstop("monitor") == 10 * 60
    other = serve.Serve(
        serve_args(
            "--data-dir",
            str(data),
            "--monitor",
            "record-only",
            "--monitor-dir",
            str(tmp_path / "queue"),
            "--monitor-waker",
            "/app/tools/ops/orca_wake.sh",
            "--monitor-orca",
            "orca",
            "--now",
            "2026-10-25T20:01:57",
        )
    )
    at = other.now()
    monitor, environment = other.command("monitor", at)
    assert monitor[5:7] == ["--queue-dir", str(tmp_path / "queue")]
    assert monitor[-5:] == [
        "--orca",
        "orca",
        "--waker",
        "/app/tools/ops/orca_wake.sh",
        "--record-only",
    ]
    assert environment["MONITOR_NOW"] == str(int(at.timestamp()))


@pytest.mark.parametrize(
    "argv, message",
    [
        (["--daily-times", "25:00"], "not a time of day"),
        (["--daily-times", "18"], "not HH:MM"),
        (
            ["--news-interval-hours", "0"],
            "--news-interval-hours must be between 1 and 24",
        ),
        (
            ["--news-interval-hours", "25"],
            "--news-interval-hours must be between 1 and 24",
        ),
        (
            ["--news-interval-hours", "-1"],
            "--news-interval-hours must be between 1 and 24",
        ),
        (["--daily-time-limit-minutes", "0"], "--daily-time-limit-minutes"),
        (["--news-min-free-memory-gb", "-1"], "--news-min-free-memory-gb"),
        (["--now", "yesterday"], "isoformat"),
    ],
)
def test_bad_arguments_are_refused(argv, message):
    assert message in serve.argument_problem(serve_args(*argv))


@pytest.mark.parametrize("hours", ["0", "25"])
def test_the_cli_refuses_a_news_interval_outside_the_range_with_exit_2(tmp_path, hours):
    """The real worker.cli: the argument check ends the process before any scheduling."""

    names = ("STOCK_DATA_DIR", "STOCK_DB_PATH", "STOCK_RAW_DIR")
    completed = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "worker.cli",
            "serve",
            "--data-dir",
            str(tmp_path / "data"),
            "--news-interval-hours",
            hours,
        ],
        cwd=ROOT / "backend",
        env={key: value for key, value in os.environ.items() if key not in names},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert completed.returncode == 2, completed.stdout + completed.stderr
    assert "--news-interval-hours must be between 1 and 24" in completed.stderr
    assert "serve ready" not in completed.stdout


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_serve_refuses_to_start_off_linux(tmp_path, monkeypatch, capsys, platform):
    monkeypatch.setattr(job.sys, "platform", platform)
    data = tmp_path / "serve-data"
    assert serve.run(serve_args("--data-dir", str(data))) == job.PLATFORM_EXIT
    assert (
        f"worker.serve runs on Linux only (the backend image, #333), not {platform}"
        in capsys.readouterr().err
    )
    assert not data.exists()


# Time limits (AC-3) ------------------------------------------------------------------


@pytest.mark.parametrize("name", ["daily", "news"])
def test_a_job_started_by_serve_ends_at_its_time_limit(
    serve_tree, monkeypatch, capsys, name
):
    in_tree(serve_tree, monkeypatch, **{f"{name}_sleep": 120})
    runner = serve.Serve(
        serve_args(
            "--data-dir",
            str(serve_tree.data),
            *NO_MEMORY_CHECK,
            f"--{name}-time-limit-minutes",
            "0.05",
        )
    )
    started = time.monotonic()
    assert runner.fire(name) == job.TIMEOUT_EXIT
    assert time.monotonic() - started < 60
    log = serve_tree.log(name)
    prefix = "news " if name == "news" else ""
    assert (
        f"--- {prefix}timeout: killed at the 0.05 minute limit of the {name} job"
        f" (exit={job.TIMEOUT_EXIT})" in log
    )
    expected = (str(job.TIMEOUT_EXIT), "timeout" if name == "news" else "")
    assert [groups[1:] for groups in end_line(log)] == [expected]
    if name == "news":
        assert "--- news-llm timeout: not started" in log
    assert wait_dead(serve_tree.calls()[0]["pid"])
    assert re.search(
        rf" serve end job={name} pid=\d+ exit={job.TIMEOUT_EXIT} seconds=\d+$",
        capsys.readouterr().out,
        re.MULTILINE,
    )


def test_a_run_past_the_backstop_is_killed_with_its_worker(
    serve_tree, monkeypatch, capsys
):
    in_tree(serve_tree, monkeypatch, daily_sleep=120)
    monkeypatch.setattr(serve.Serve, "backstop", lambda self, name: 2.0)
    runner = serve.Serve(
        serve_args("--data-dir", str(serve_tree.data), *NO_MEMORY_CHECK)
    )
    assert runner.fire("daily") is None
    out = capsys.readouterr().out
    assert re.search(
        r" serve killed job=daily pid=\d+ reason=still_running_after_", out
    )
    assert re.search(r" serve end job=daily pid=\d+ exit=killed ", out)
    assert wait_dead(serve_tree.calls()[0]["pid"]), "the worker outlived its job"
    # Killed: the log has a start line and no end line, and the lock is free.
    assert end_line(serve_tree.log("daily")) == []
    lock = job.FileLock(job.lock_path(serve_tree.data, "daily"))
    assert lock.acquire()
    lock.release()


# One job of a kind at a time (AC-5) --------------------------------------------------


def test_an_overlapping_daily_trigger_records_already_running(serve_tree, monkeypatch):
    from apscheduler.triggers.interval import IntervalTrigger

    release = serve_tree.root / "release"
    in_tree(serve_tree, monkeypatch, daily_until=release, daily_sleep=90)
    # The real scheduler set-up, with daily due every second.
    monkeypatch.setattr(
        serve,
        "triggers",
        lambda args: {"daily": IntervalTrigger(seconds=1, timezone=TAIPEI)},
    )
    runner = serve.Serve(
        serve_args("--data-dir", str(serve_tree.data), *NO_MEMORY_CHECK)
    )
    scheduler = runner.scheduler()
    thread = threading.Thread(target=scheduler.start, daemon=True)
    thread.start()
    try:
        first = serve_tree.wait_for_call(1)
        second = serve_tree.wait_for_call(2)
    finally:
        release.touch()
        scheduler.shutdown(wait=True)
        thread.join(timeout=60)
    assert first["argv"] == ["daily", "--trigger", "scheduler"]
    assert second["argv"] == [
        "daily",
        "--trigger",
        "scheduler",
        "--skip-reason",
        "already_running",
    ]
    # The second job's worker started while the first still ran.
    assert wait_dead(first["pid"])
    skipped = skipped_line(serve_tree.log("daily"))
    assert skipped.group(1) == "already_running"
    assert skipped.group(2) == f"lock={job.lock_path(serve_tree.data, 'daily')}"


# The watchdog (AC-2) ------------------------------------------------------------------


@pytest.mark.parametrize("daily_ended", [True, False], ids=["daily-ended", "daily-cut"])
def test_the_watchdog_started_by_serve_decides_as_watchdog_sh(
    serve_tree, tmp_path, daily_ended
):
    # Monday 2026-10-19: the watchdog at 23:15 Taipei reads the Windows wrapper's
    # logs (fixtures, test_worker_job), written from 22:15 on.
    fire = datetime(2026, 10, 19, 23, 15, tzinfo=TAIPEI)
    first = fire.timestamp() - 3600
    day = "20261019"
    datas = [serve_tree.data, tmp_path / "direct"]
    for data in datas:
        logs = data / "logs"
        logs.mkdir(parents=True)
        daily = _restamp(
            (FIXTURES / "wrapper_daily.txt").read_text(encoding="utf-8"), first
        )
        if not daily_ended:
            daily = daily.splitlines(keepends=True)[0]
        (logs / f"daily-{day}.log").write_text(daily, encoding="utf-8")
        news = logs / f"news-{day}.log"
        news.write_text(
            _restamp(
                (FIXTURES / "wrapper_news.txt").read_text(encoding="utf-8"), first
            ),
            encoding="utf-8",
        )
        os.utime(news, (fire.timestamp() - 600,) * 2)
    process = serve_tree.start_serve(
        "--now", (fire - timedelta(seconds=3)).isoformat(), "--watchdog-dry-run"
    )
    out = Output(process)
    try:
        out.wait_for(r" serve end job=watchdog pid=\d+ exit=0 ")
    finally:
        assert stop(process) == 0
    out.wait_for(r" serve stopped$")
    # The moment the watchdog judged: WATCHDOG_NOW, the first stamp of its log.
    stamp = (serve_tree.data / "logs" / "watchdog.log").read_text().split()[0]
    now = int(
        datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )
    assert 0 <= now - fire.timestamp() < 30
    by_serve = [
        line.replace(serve_tree.data.as_posix(), "<data>")
        for line in out.lines
        if " serve " not in line
    ]
    assert by_serve == _watchdog(datas[1], now)
    keys = re.findall(r" anomaly_planned key=(\S+)", "\n".join(by_serve))
    assert keys == (
        ["news_llm_failed"] if daily_ended else ["daily_no_end", "news_llm_failed"]
    )


# docker kill (AC-4, #224) and docker stop --------------------------------------------


def _rows(db: Path) -> list[tuple]:
    with sqlite3.connect(db) as conn:
        return conn.execute(
            "SELECT id, status, error, host, pid, summary_json FROM schedule_runs"
            " WHERE target_date = '2026-10-16' ORDER BY id"
        ).fetchall()


def _wait_for_running_row(db: Path, timeout: float = 120) -> tuple:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        running = [row for row in _rows(db) if row[1] == "running"]
        if running:
            return running[0]
        time.sleep(0.1)
    raise AssertionError(f"no running row within {timeout} s: {_rows(db)}")


def test_a_killed_serve_leaves_no_lock_and_the_next_daily_closes_its_run_at_once(
    serve_tree,
):
    tree = serve_tree
    built = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "verify" / "fixture_db.py"),
            "--dest",
            str(tree.data),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert built.returncode == 0, built.stderr
    db = tree.data / "stock.db"
    real = {
        "FAKE_REAL_DAILY": str(Path(__file__).with_name("job_daily_child.py")),
        "FAKE_REAL_BACKEND": str(ROOT / "backend"),
    }
    claude = ("--claude-cli", str(tree.root / "no-claude"))
    # Friday 2026-10-16 21:30 on the injected clock; collect then waits for a file
    # that never comes, so the run row stays running.
    killed = tree.start_serve(
        "--now",
        "2026-10-16T21:29:58",
        *claude,
        extra_env={**real, "JOB_DAILY_CHILD_HOLD": str(tree.root / "never")},
    )
    out = Output(killed)
    try:
        row_id, _, _, host, worker_pid, _ = _wait_for_running_row(db)
    except BaseException:
        killed.kill()
        raise
    os.kill(killed.pid, signal.SIGKILL)  # docker kill: SIGKILL to the whole container
    killed.wait(timeout=30)
    (job_pid,) = tree.job_pids()
    assert wait_dead(job_pid) and wait_dead(worker_pid), "a job outlived serve"
    assert not [line for line in out.lines if " serve end " in line]
    lock_file = job.lock_path(tree.data, "daily")
    lock = job.FileLock(lock_file)
    assert lock.acquire(), "the killed run left its lock held"
    lock.release()
    # The new container: another hostname, and its PIDs start over, so the
    # killed worker's PID may belong to a live process (this test's own).
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE schedule_runs SET host = '0123456789ab', pid = ? WHERE id = ?",
            (os.getpid(), row_id),
        )
    started = time.monotonic()
    # 22:10, between the two triggers and off the news hours: the restarted serve
    # runs the day's daily at once, as its 21:30 run did not complete (#342,
    # decision 5).
    restarted = tree.start_serve(
        "--now", "2026-10-16T22:10:00", *claude, extra_env=real
    )
    out = Output(restarted)
    try:
        out.wait_for(r" serve catchup job=daily reason=not_complete$", timeout=60)
        end = out.wait_for(r" serve end job=daily ", timeout=300)
    finally:
        assert stop(restarted) == 0
    assert time.monotonic() - started < 300
    assert " exit=0 " in end, "\n".join(out.lines)
    old, new = [row for row in _rows(db) if row[0] >= row_id]
    assert old[1] == "failed"
    assert old[2] == (
        f"abandoned: process {os.getpid()} on 0123456789ab no longer holds {lock_file}"
    )
    assert new[1] == "success" and new[3] == host
    assert json.loads(new[5])["runtime"]["job_lock"] == str(lock_file)
    log = tree.log("daily")
    assert log.count(" start job=daily trigger=scheduler date=2026-10-16") == 2
    assert [groups[1:] for groups in end_line(log)] == [("0", "")]


def _fire_scheduled_daily(tree: ServeTree, at: str) -> list[str]:
    """Run the real scheduler from AT (Taipei) until its daily trigger has run once.

    The start-up catch-up is dropped: this is the serve that has been running all
    evening, so 23:00 is its trigger, not a restart. Returns serve's lines.
    """

    from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

    runner = serve.Serve(
        serve_args(
            "--data-dir",
            str(tree.data),
            *NO_MEMORY_CHECK,
            "--claude-cli",
            str(tree.root / "no-claude"),
            "--now",
            at,
        )
    )
    upcoming = runner.next_times()["daily"]
    assert upcoming is not None and upcoming - runner.now() < timedelta(seconds=30), (
        f"the next daily from {at} is at {upcoming}"
    )
    scheduler = runner.scheduler()
    if scheduler.get_job("daily-catchup"):
        scheduler.remove_job("daily-catchup")
    done = threading.Event()
    scheduler.add_listener(
        lambda event: event.job_id == "daily" and done.set(),
        EVENT_JOB_EXECUTED | EVENT_JOB_ERROR,
    )
    thread = threading.Thread(target=scheduler.start, daemon=True)
    thread.start()
    try:
        assert done.wait(timeout=300), f"no daily trigger from {at} within 300 s"
    finally:
        scheduler.shutdown(wait=True)
        thread.join(timeout=60)
    return [line for line in tree.log("daily").splitlines() if " start job=" in line]


@pytest.mark.parametrize("first", ["success", "partial"])
def test_what_the_2300_trigger_runs_after_the_2130_run(
    serve_tree, monkeypatch, first
):
    """#466 AC-1: 23:00 after 21:30, on the verify fixture database.

    21:30 success: 23:00 is a skipped already_complete row whose only step is the
    institutional refetch (#396; faked here, no request). 21:30 partial (the margin
    file not out yet, say): 23:00 is a full daily of the same date again.
    """

    tree = serve_tree
    built = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "verify" / "fixture_db.py"),
            "--dest",
            str(tree.data),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert built.returncode == 0, built.stderr
    db = tree.data / "stock.db"
    with sqlite3.connect(db) as conn:
        before = conn.execute("SELECT coalesce(max(id), 0) FROM schedule_runs").fetchone()[0]
    conn.close()
    in_tree(
        tree,
        monkeypatch,
        real_daily=Path(__file__).with_name("job_daily_child.py"),
        real_backend=ROOT / "backend",
    )
    partial = tree.root / "collect-partial"
    if first == "partial":
        partial.touch()
    monkeypatch.setenv("JOB_DAILY_CHILD_COLLECT_PARTIAL", str(partial))
    # Friday 2026-10-16 on the injected clock.
    _fire_scheduled_daily(tree, "2026-10-16T21:29:58")
    partial.unlink(missing_ok=True)
    starts = _fire_scheduled_daily(tree, "2026-10-16T22:59:58")
    assert len(starts) == 2
    assert all(" trigger=scheduler date=2026-10-16 " in line for line in starts)
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT id, status, summary_json FROM schedule_runs"
            " WHERE job = 'daily' AND id > ? ORDER BY id",
            (before,),
        ).fetchall()
        steps = {
            run_id: [
                step
                for (step,) in conn.execute(
                    "SELECT step FROM schedule_run_steps WHERE schedule_run_id = ?"
                    " ORDER BY id",
                    (run_id,),
                )
            ]
            for run_id, _, _ in rows
        }
    conn.close()
    (first_id, first_status, _), (second_id, second_status, raw) = rows
    second = json.loads(raw)
    assert first_status == first
    assert "collect" in steps[first_id]
    if first == "success":
        assert second_status == "skipped"
        assert second["reason"] == "already_complete"
        assert second["related_run_id"] == first_id
        assert steps[second_id] == ["institutional_refetch"]
        assert second["institutional_refetch"]["status"] == "success"
    else:
        assert second_status == "success"
        assert "collect" in steps[second_id] and "analyze" in steps[second_id]
        assert "institutional_refetch" not in steps[second_id]


def test_a_stopped_serve_ends_its_jobs(serve_tree):
    process = serve_tree.start_serve("--now", "2026-10-19T21:29:58", daily_sleep=120)
    out = Output(process)
    worker = serve_tree.wait_for_call(1)
    assert stop(process) == 0  # docker stop: SIGTERM to serve (tini forwards it)
    out.wait_for(r" serve stopping signal=SIGTERM$")
    out.wait_for(r" serve stop_kill pid=\d+$")
    out.wait_for(r" serve stopped$")
    assert wait_dead(worker["pid"]), "the worker outlived serve"
    lock = job.FileLock(job.lock_path(serve_tree.data, "daily"))
    assert lock.acquire()
    lock.release()


# The event monitor (#338) ------------------------------------------------------------


def test_a_restarted_serve_does_not_wake_again_for_the_events_it_queued(
    serve_tree, tmp_path
):
    """AC-1: serve's monitor job wakes once for an event; the scheduler container
    restarted (serve stopped and started again) polls the same answers and does not."""
    fake, bin_dir, queue = tmp_path / "fake", tmp_path / "bin", tmp_path / "queue"
    for directory in (fake, bin_dir, queue):
        directory.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH, encoding="utf-8", newline="\n")
    gh.chmod(0o755)
    (fake / "gh_pr_list.json").write_text(
        json.dumps([{"number": 7, "title": "t", "url": "u", "headRefOid": "c" * 40}]),
        encoding="utf-8",
    )
    (queue / "coordinator-heartbeat.json").write_text(
        json.dumps(
            {
                "session_id": "coord",
                "terminal_handle": "term_coord",
                "written_at": "2026-10-25T11:55:00Z",
            }
        ),
        encoding="utf-8",
    )
    waker = tmp_path / "waker.sh"
    waker.write_text(
        f'printf "%s\\n" "$1" >>"{fake / "woken.log"}"\n',
        encoding="utf-8",
        newline="\n",
    )
    env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_DIR": str(fake)}
    args = (
        "--monitor",
        "on",
        "--monitor-dir",
        str(queue),
        "--monitor-waker",
        str(waker),
    )
    # 20:02 and 20:03 Taipei: no other job fires then.
    for at in ("2026-10-25T20:01:57", "2026-10-25T20:02:57"):
        process = serve_tree.start_serve(*args, "--now", at, extra_env=env)
        out = Output(process)
        try:
            end = out.wait_for(r" serve end job=monitor pid=\d+ ")
        finally:
            assert stop(process) == 0
        assert " exit=0 " in end, "\n".join(out.lines)
    events = [
        json.loads(line)
        for line in (queue / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [e["id"] for e in events if e["type"] == "event"] == ["pr:7"]
    assert [(e["ok"], e["upto"]) for e in events if e["type"] == "wake"] == [(True, 1)]
    assert (fake / "woken.log").read_text(encoding="utf-8") == "term_coord\n"
    log = (queue / "monitor.log").read_text(encoding="utf-8").splitlines()
    polls = [line.split()[0] for line in log if " poll " in line]
    # MONITOR_NOW: each poll judged at its trigger time on serve's (injected) clock.
    assert polls == ["2026-10-25T12:02:00Z", "2026-10-25T12:03:00Z"]
    assert not (serve_tree.data / "logs" / "events.jsonl").exists()


# #342: news-llm switched off from the env file, and the day's missed daily at start ------


@pytest.mark.parametrize(
    "value, skipped",
    [
        ("1", True),
        ("true", True),
        ("YES", True),
        (" on ", True),
        ("", False),
        ("0", False),
        ("false", False),
        ("Off", False),
        (None, False),
    ],
)
def test_stock_skip_news_llm_switches_news_llm_off(
    tmp_path, monkeypatch, value, skipped
):
    """Decision 6 of #342: the env file (compose env_file) reaches serve's environment."""

    if value is None:
        monkeypatch.delenv(serve.SKIP_NEWS_LLM_ENV, raising=False)
    else:
        monkeypatch.setenv(serve.SKIP_NEWS_LLM_ENV, value)
    args = serve_args("--data-dir", str(tmp_path))
    assert serve.argument_problem(args) is None
    runner = serve.Serve(args)
    news, _ = runner.command("news", runner.now())
    assert ("--skip-news-llm" in news) is skipped
    daily, _ = runner.command("daily", runner.now())
    assert "--skip-news-llm" not in daily


def test_the_option_skips_news_llm_whatever_the_variable_says(tmp_path, monkeypatch):
    monkeypatch.setenv(serve.SKIP_NEWS_LLM_ENV, "0")
    runner = serve.Serve(serve_args("--data-dir", str(tmp_path), "--skip-news-llm"))
    assert "--skip-news-llm" in runner.command("news", runner.now())[0]


@pytest.mark.parametrize("value", ["2", "skip", "y"])
def test_a_bad_stock_skip_news_llm_is_refused(monkeypatch, value):
    monkeypatch.setenv(serve.SKIP_NEWS_LLM_ENV, value)
    problem = serve.argument_problem(serve_args())
    assert problem and serve.SKIP_NEWS_LLM_ENV in problem


def test_the_env_example_documents_stock_skip_news_llm():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^STOCK_SKIP_NEWS_LLM=$", text, re.M), text


# A Monday and a Saturday (Taipei).
MONDAY = "2026-11-02"
SATURDAY = "2026-11-07"


def _runs_db(data: Path, *rows: tuple[str, str]) -> None:
    data.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(data / "stock.db") as conn:
        conn.execute(
            "CREATE TABLE schedule_runs (id INTEGER PRIMARY KEY, job TEXT, "
            "target_date DATE, status TEXT)"
        )
        conn.executemany(
            "INSERT INTO schedule_runs (job, target_date, status) VALUES ('daily', ?, ?)",
            rows,
        )
    conn.close()


def _catchup(data: Path, now: str):
    runner = serve.Serve(serve_args("--data-dir", str(data), "--now", now))
    jobs = {job.id: job for job in runner.scheduler().get_jobs()}
    return runner.missed_daily(), jobs.get("daily-catchup")


@pytest.mark.parametrize(
    "rows, now, reason",
    [
        # Started after 21:30 (#466) on a weekday with no complete daily of the day:
        # run it once.
        ((), f"{MONDAY}T21:35", "not_complete"),
        (((MONDAY, "running"),), f"{MONDAY}T21:30", "not_complete"),
        # 21:30 failed, restarted before 23:00: no wait for the 23:00 retry.
        (((MONDAY, "failed"), (MONDAY, "skipped")), f"{MONDAY}T22:10", "not_complete"),
        (((MONDAY, "non_trading_unconfirmed"),), f"{MONDAY}T22:00", "not_complete"),
        # 21:30 and 23:00 both incomplete, restarted after 23:00.
        (((MONDAY, "partial"), (MONDAY, "failed")), f"{MONDAY}T23:20", "not_complete"),
        # The day before does not count.
        (((("2026-10-30", "success")),), f"{MONDAY}T21:35", "not_complete"),
        # Complete, too early, or a weekend: nothing at start.
        (((MONDAY, "failed"), (MONDAY, "success")), f"{MONDAY}T21:50", None),
        (((MONDAY, "non_trading_day"),), f"{MONDAY}T22:00", None),
        # 21:30 succeeded; the 23:00 refetch is not caught up after a restart.
        (((MONDAY, "success"), (MONDAY, "skipped")), f"{MONDAY}T23:20", None),
        # Before 21:30: the old 18:30 time no longer counts.
        ((), f"{MONDAY}T19:05", None),
        ((), f"{MONDAY}T21:29", None),
        ((), f"{SATURDAY}T21:35", None),
    ],
)
def test_serve_runs_the_missed_daily_of_the_day_once_at_start(
    tmp_path, rows, now, reason
):
    """Decision 5 of #342: a scheduler (re)created after 21:30 runs that day's daily."""

    _runs_db(tmp_path / "data", *rows)
    missed, catchup = _catchup(tmp_path / "data", now)
    assert missed == reason
    if reason is None:
        assert catchup is None
    else:
        assert catchup is not None and catchup.args == ("daily",)
        assert type(catchup.trigger).__name__ == "DateTrigger"
        # As soon as the scheduler starts, on the real clock.
        wait = catchup.trigger.run_date - datetime.now(TAIPEI)
        assert abs(wait.total_seconds()) < 60


def test_a_volume_without_a_database_runs_no_daily_at_start(tmp_path):
    assert _catchup(tmp_path / "data", f"{MONDAY}T21:35") == (None, None)


def test_an_unreadable_run_table_still_runs_the_daily_at_start(tmp_path):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    sqlite3.connect(data / "stock.db").close()
    missed, catchup = _catchup(data, f"{MONDAY}T21:35")
    assert missed == "unreadable:OperationalError"
    assert catchup is not None


def test_the_catchup_reads_the_statuses_a_daily_counts_as_complete():
    from worker.schedule_runs import COMPLETE_STATUSES

    assert set(serve.DAILY_COMPLETE_STATUSES) == set(COMPLETE_STATUSES)


def test_the_catchup_follows_the_first_daily_time(tmp_path):
    _runs_db(tmp_path / "data")
    runner = serve.Serve(
        serve_args(
            "--data-dir",
            str(tmp_path / "data"),
            "--daily-times",
            "21:30,17:00",
            "--now",
            f"{MONDAY}T17:10",
        )
    )
    assert runner.missed_daily() == "not_complete"
