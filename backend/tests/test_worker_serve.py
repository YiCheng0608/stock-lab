"""The scheduler container's command ``python -m worker.cli serve`` (backend/worker/serve.py, #336).

The schedule and the commands are checked without starting anything. The other
tests run serve in a project tree of its own (test_worker_job.Tree plus copies of
serve.py and the watchdog): a fake ``worker.cli`` routes ``serve`` and ``job`` to
those copies and scripts the steps, so no worker, network or Claude call is
involved; only the docker kill scenario runs the real daily worker, on the verify
fixture database with the outside-facing steps faked (job_daily_child.py).

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


# The schedule (OPERATIONS §6.2: the Task Scheduler triggers) -----------------------


def fire_times(trigger, start: datetime, end: datetime) -> list[datetime]:
    times, previous, now = [], None, start
    while True:
        moment = trigger.get_next_fire_time(previous, now)
        if moment is None or moment >= end:
            return times
        times.append(moment.astimezone(TAIPEI))
        previous = now = moment


def test_the_triggers_fire_when_task_scheduler_did():
    triggers = serve.triggers(serve_args())
    monday = datetime(2026, 10, 19, tzinfo=TAIPEI)
    week = (monday, monday + timedelta(days=7))
    daily = fire_times(triggers["daily"], *week)
    assert [moment.strftime("%a %H:%M") for moment in daily] == [
        f"{day} {hm}"
        for day in ("Mon", "Tue", "Wed", "Thu", "Fri")
        for hm in ("18:30", "21:30")
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
    injected = datetime(2026, 10, 19, 18, 29, 50, tzinfo=TAIPEI)
    offset = injected - real
    daily = serve.triggers(serve_args())["daily"]
    moved = serve.shifted(daily, offset)
    # 10 seconds after the real now, the scheduler's clock reaches 18:30.
    first = moved.get_next_fire_time(None, real)
    assert first == real + timedelta(seconds=10)
    second = moved.get_next_fire_time(first, first)
    assert (second + offset).astimezone(TAIPEI) == datetime(
        2026, 10, 19, 21, 30, tzinfo=TAIPEI
    )
    assert serve.shifted(daily, timedelta(0)) is daily


# The commands (OPERATIONS §6.2: what Task Scheduler ran) ---------------------------


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
        serve_args("--data-dir", str(tmp_path), "--now", "2026-10-19T18:29:50")
    )
    at = runner.now()
    assert abs(at - datetime(2026, 10, 19, 18, 29, 50, tzinfo=TAIPEI)) < timedelta(
        seconds=30
    )
    assert runner.command("daily", at)[0][-2:] == ["--date", "2026-10-19"]
    assert "--date" not in runner.command("news", at)[0]
    _, environment = runner.command("watchdog", at)
    assert environment["WATCHDOG_NOW"] == str(int(at.timestamp()))


def test_the_backstop_is_ten_minutes_past_the_job_limit(tmp_path):
    runner = serve.Serve(serve_args("--data-dir", str(tmp_path)))
    assert runner.backstop("daily") == 160 * 60
    assert runner.backstop("news") == 100 * 60
    assert runner.backstop("watchdog") == 10 * 60
    short = serve.Serve(
        serve_args("--data-dir", str(tmp_path), "--daily-time-limit-minutes", "1")
    )
    assert short.backstop("daily") == 11 * 60


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
    # Monday 2026-10-19: the watchdog at 22:15 Taipei reads the Windows wrapper's
    # logs (fixtures, test_worker_job), written from 21:15 on.
    fire = datetime(2026, 10, 19, 22, 15, tzinfo=TAIPEI)
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
    # Friday 2026-10-16 18:30 on the injected clock; collect then waits for a file
    # that never comes, so the run row stays running.
    killed = tree.start_serve(
        "--now",
        "2026-10-16T18:29:58",
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
    restarted = tree.start_serve(
        "--now", "2026-10-16T21:29:58", *claude, extra_env=real
    )
    out = Output(restarted)
    try:
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


def test_a_stopped_serve_ends_its_jobs(serve_tree):
    process = serve_tree.start_serve("--now", "2026-10-19T18:29:58", daily_sleep=120)
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
