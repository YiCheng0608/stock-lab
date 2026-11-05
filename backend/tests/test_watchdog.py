"""tools/ops/watchdog.sh with a fake gh executable (Issue #171).

Each test builds a data directory with job logs and an optional stock.db,
prepends a bin directory holding a fake ``gh`` script to PATH and runs the
real watchdog through bash. The fake records every call; the watchdog's clock
is pinned with WATCHDOG_NOW. Nothing touches GitHub or the real data
directory.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "ops" / "watchdog.sh"
# NIGHT is Monday 2026-10-19 23:15 Taipei: the first watchdog run after the 23:00
# daily trigger, when the day's daily is judged (#466).
NIGHT = int(datetime(2026, 10, 19, 15, 15, tzinfo=timezone.utc).timestamp())


def _bash() -> str | None:
    if os.name == "nt":
        git_bash = (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "Git"
            / "bin"
            / "bash.exe"
        )
        return str(git_bash) if git_bash.exists() else None
    return shutil.which("bash")


BASH = _bash()
pytestmark = [
    pytest.mark.skipif(BASH is None, reason="bash is required"),
    # The watchdog runs under the job lock of worker.job, which is Linux only.
    pytest.mark.skipif(
        not sys.platform.startswith("linux"),
        reason="worker.job runs on Linux only (#333)",
    ),
]

# The repository read of every run goes to gh_api.log, the rest to
# gh_calls.log. The file gh_mode_<subcommand>, else gh_mode, makes the call
# fail: 401 (expired GH_TOKEN), no_token (exit 4) or down (no connection).
FAKE_GH = r"""#!/usr/bin/env bash
d="$FAKE_DIR"
if [ "$1" = api ]; then
  printf '%s\n' "$*" >>"$d/gh_api.log"
else
  printf '%s\n' "$*" >>"$d/gh_calls.log"
fi
mode="$(cat "$d/gh_mode_$1" 2>/dev/null || cat "$d/gh_mode" 2>/dev/null)"
case "$mode" in
  401) echo 'HTTP 401: Bad credentials (https://api.github.com/repos/YiCheng0608/stock-lab)' >&2; exit 1 ;;
  # Only exit 4 tells: the line naming gh auth login is left out.
  no_token) echo 'Alternatively, populate the GH_TOKEN environment variable with a GitHub API authentication token.' >&2; exit 4 ;;
  down) echo 'error connecting to api.github.com' >&2; exit 1 ;;
esac
[ "$1" = api ] && { echo 'YiCheng0608/stock-lab'; exit 0; }
# gh_fail (#390): the comment fails with a message that is not an auth error.
[ -f "$d/gh_fail" ] && { echo boom >&2; exit 1; }
while [ $# -gt 0 ]; do
  [ "$1" = --body-file ] && { cat "$2"; echo '-----'; } >>"$d/gh_bodies.txt"
  shift
done
echo "https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-1"
"""


class Watchdog:
    def __init__(self, root: Path, data_name: str = "data") -> None:
        self.root = root
        self.bin = root / "bin"
        self.fake = root / "fake"
        self.data = root / data_name
        self.logs = self.data / "logs"
        for directory in (self.bin, self.fake, self.logs):
            directory.mkdir(parents=True)
        path = self.bin / "gh"
        path.write_text(FAKE_GH, encoding="utf-8", newline="\n")
        path.chmod(0o755)

    def run(
        self,
        *args: str,
        now: int = NIGHT,
        python: str | None = None,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        wrapper: list[str] | None = None,
        **extra: str,
    ) -> subprocess.CompletedProcess[str]:
        # env (a dict, #340) and keyword variables (#390) both reach the script;
        # wrapper (#448) is the command that starts it, as worker.job lock does.
        extra = {**(env or {}), **extra}
        env = dict(os.environ)
        # Not the image's version unless the test says so (the docker CI job runs in one).
        env.pop("STOCK_IMAGE_TAG", None)
        env.pop("STOCK_GIT_HEAD", None)
        env.update(
            PATH=str(self.bin) + os.pathsep + env.get("PATH", ""),
            FAKE_DIR=self.fake.as_posix(),
            STOCK_DATA_DIR=self.data.as_posix(),
            STOCK_PYTHON=python or Path(sys.executable).as_posix(),
            WATCHDOG_NOW=str(now),
            # The data check requests no official table in tests (#390).
            WATCHDOG_DATA_CHECK_ARGS="--offline",
        )
        env.update(extra)
        result = subprocess.run(
            [*(wrapper or []), BASH, SCRIPT.as_posix(), *args],
            env=env,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result

    def text(self, name: str) -> str:
        path = self.fake / name
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def log(self) -> str:
        return (self.logs / "watchdog.log").read_text(encoding="utf-8")

    def events(self) -> list[str]:
        return [line.split()[1] for line in self.log().splitlines()]


@pytest.fixture
def wd(tmp_path) -> Watchdog:
    return Watchdog(tmp_path)


def _ingestion_runs(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ingestion_runs (id INTEGER PRIMARY KEY, run_type TEXT,"
        " status TEXT, started_at DATETIME, metadata_json TEXT)"
    )


def _utc_text(epoch: int) -> str:
    # The jobs store naive UTC timestamps.
    return (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        .replace(tzinfo=None)
        .isoformat(sep=" ")
    )


def _news_llm_db(path: Path, batches: list[list[str]]) -> None:
    with sqlite3.connect(path) as conn:
        _ingestion_runs(conn)
        conn.execute(
            "INSERT INTO ingestion_runs (run_type, status, metadata_json) VALUES ('news', 'success', '{}')"
        )
        for statuses in batches:
            metadata = {
                "batches": [
                    {"batch": n, "status": s} for n, s in enumerate(statuses, start=1)
                ]
            }
            conn.execute(
                "INSERT INTO ingestion_runs (run_type, status, started_at, metadata_json)"
                " VALUES ('news_llm', 'partial', ?, ?)",
                (_utc_text(NIGHT - 3600), json.dumps(metadata)),
            )
    conn.close()


def _news_llm_runs(path: Path, runs: list[tuple[str, int]]) -> None:
    """news_llm runs without batches: (status, started seconds before NIGHT)."""

    with sqlite3.connect(path) as conn:
        _ingestion_runs(conn)
        for status, age in runs:
            conn.execute(
                "INSERT INTO ingestion_runs (run_type, status, started_at, metadata_json)"
                " VALUES ('news_llm', ?, ?, '{}')",
                (status, _utc_text(NIGHT - age)),
            )
    conn.close()


def _daily_db(
    path: Path, runs: list[tuple[str, dict]], day: str = "2026-10-19"
) -> None:
    """schedule_runs rows for one target date: (status, summary)."""

    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schedule_runs (id INTEGER PRIMARY KEY, job TEXT,"
            " target_date DATE, status TEXT, started_at DATETIME, summary_json TEXT)"
        )
        for status, summary in runs:
            conn.execute(
                "INSERT INTO schedule_runs (job, target_date, status, started_at, summary_json)"
                " VALUES ('daily', ?, ?, ?, ?)",
                (day, status, _utc_text(NIGHT - 3600), json.dumps(summary)),
            )
    conn.close()


def _daily_log_done(wd: Watchdog) -> None:
    (wd.logs / "daily-20261019.log").write_text(
        "===== s start\n===== e end exit=0 seconds=9\n", encoding="utf-8"
    )


def _anomaly_fixtures(wd: Watchdog) -> None:
    (wd.logs / "daily-20261016.log").write_text(
        "===== x start\n===== y end exit=0 seconds=1\n", encoding="utf-8"
    )
    (wd.logs / "daily-20261019.log").write_text(
        "===== 2026-10-19T21:30:00+08:00 start job=daily\n", encoding="utf-8"
    )
    news = wd.logs / "news-20261019.log"
    news.write_text("===== start job=news\n", encoding="utf-8")
    os.utime(news, (NIGHT - 7 * 3600, NIGHT - 7 * 3600))
    _news_llm_db(wd.data / "stock.db", [["done", "pending"], ["pending"], ["pending"]])


def test_anomalies_dry_run_prints_comments(wd):
    _anomaly_fixtures(wd)
    db = wd.data / "stock.db"
    before = (db.read_bytes(), db.stat().st_mtime_ns)
    result = wd.run("--dry-run")
    assert result.stdout.count("將在 #1 留言：") == 3
    assert (
        "待使用者：daily 排程：台北 20261019 已過 23:00 的重試" in result.stdout
        and "沒有結束列" in result.stdout
    )
    assert "待使用者：news 排程：最新日誌寫於" in result.stdout
    assert "待使用者：news_llm：最近連續 3 批判讀都是 pending" in result.stdout
    assert wd.text("gh_calls.log") == ""
    assert (db.read_bytes(), db.stat().st_mtime_ns) == before


def test_anomaly_comment_at_most_once_per_day(wd):
    _anomaly_fixtures(wd)
    wd.run()
    calls = wd.text("gh_calls.log").splitlines()
    assert len(calls) == 3 and all(
        call.startswith("issue comment 1 --repo YiCheng0608/stock-lab")
        for call in calls
    )
    assert wd.text("gh_bodies.txt").count("待使用者：") == 3
    wd.run(now=NIGHT + 15 * 60)
    assert len(wd.text("gh_calls.log").splitlines()) == 3
    assert wd.events().count("anomaly_already_commented") == 3


def test_missing_daily_log_on_weekday_night_is_reported(wd):
    (wd.logs / "daily-20261016.log").write_text(
        "===== s start\n===== e end exit=0 seconds=9\n", encoding="utf-8"
    )
    result = wd.run("--dry-run")
    assert "daily-20261019.log` 不存在（今日未執行）" in result.stdout


def test_no_anomaly_when_jobs_are_healthy_or_not_scheduled(wd):
    _news_llm_db(wd.data / "stock.db", [["pending", "pending"], ["done"]])
    wd.run()  # no daily/news logs yet: jobs not scheduled, nothing to report
    (wd.logs / "daily-20261019.log").write_text(
        "===== s start\n===== e end exit=0 seconds=9\n", encoding="utf-8"
    )
    news = wd.logs / "news-20261019.log"
    news.write_text("===== start\n", encoding="utf-8")
    os.utime(news, (NIGHT - 3600, NIGHT - 3600))
    result = wd.run()
    assert "將在 #1 留言" not in result.stdout
    assert wd.text("gh_calls.log") == ""
    assert wd.events() == ["schedules_ok", "schedules_ok"]


def test_missing_python_still_checks_logs(wd):
    _anomaly_fixtures(wd)
    result = wd.run("--dry-run", python=(wd.root / "no-python.exe").as_posix())
    assert wd.events()[0] == "python_missing"
    assert result.stdout.count("將在 #1 留言：") == 2
    assert "news_llm：最近" not in result.stdout


# The base interpreter: worker.job is standard library only, and under a Windows
# venv sys.executable is a launcher in front of the process that holds the lock.
BASE_PYTHON = getattr(sys, "_base_executable", None) or sys.executable


def _hold_lock(wd: Watchdog) -> tuple[subprocess.Popen, int]:
    """A process holding the watchdog lock (worker.job lock), and its child's pid."""

    started = wd.root / "holder.pid"
    child = (
        "import os, time; open(os.environ['HOLDER_PID'], 'w').write(str(os.getpid()));"
        " time.sleep(120)"
    )
    holder = subprocess.Popen(
        [
            BASE_PYTHON,
            "-m",
            "worker.job",
            "lock",
            str(wd.data / "locks" / "watchdog.lock"),
            "--",
            BASE_PYTHON,
            "-c",
            child,
        ],
        cwd=ROOT / "backend",
        env={**os.environ, "HOLDER_PID": str(started)},
    )
    deadline = time.monotonic() + 60
    while not (started.exists() and started.read_text()):
        assert time.monotonic() < deadline, "the lock holder did not start"
        time.sleep(0.05)
    return holder, int(started.read_text())


def _force_kill(pid: int) -> None:
    os.kill(pid, signal.SIGKILL)


def test_a_running_watchdog_keeps_the_next_one_out(wd):
    holder, _child = _hold_lock(wd)
    try:
        result = wd.run()
    finally:
        holder.kill()
        holder.wait(timeout=30)
    assert wd.events() == ["locked"], result.stdout + result.stderr
    assert wd.text("gh_calls.log") == ""


def test_a_killed_watchdog_leaves_no_lock_behind(wd):
    # #224: a run killed by the task's time limit left logs/watchdog.lock/ and
    # every run for the next 30 minutes was skipped. The OS drops a file lock
    # with its holder, and the holder's child goes with it.
    from worker.schedule_runs import _pid_alive

    holder, child = _hold_lock(wd)
    _force_kill(holder.pid)
    holder.wait(timeout=30)
    deadline = time.monotonic() + 15
    while _pid_alive(child):
        assert time.monotonic() < deadline, "the holder's child outlived it"
        time.sleep(0.1)
    # A lock directory left by the old watchdog does not count either.
    (wd.logs / "watchdog.lock").mkdir()
    wd.run()
    assert wd.events() == ["schedules_ok"]


def test_a_run_leaves_no_work_directory(wd):
    _anomaly_fixtures(wd)
    wd.run()
    assert [path.name for path in wd.logs.iterdir() if path.name.startswith(".")] == []


# The real Python; a call of the helper (watchdog_helper.py) notes the STOCK_DATA_DIR
# it runs with, as data_check.py reads it to find the stored raw files.
RECORDING_PYTHON = r"""#!/usr/bin/env bash
case "$*" in
  *watchdog_helper.py*) printf '%s\n' "${STOCK_DATA_DIR:-}" >>"$FAKE_DIR/helper_data_dir.log" ;;
esac
exec "$REAL_PYTHON" "$@"
"""


@pytest.mark.parametrize("given", ["option", "variable", "colon"])
def test_a_relative_data_directory_is_one_place_for_lock_log_and_database(
    tmp_path, given
):
    # #326: the run that takes the lock starts the locked run from backend/, so a
    # relative --data-dir, STOCK_DATA_DIR or --monitor-dir named one place for the
    # lock (the caller's directory) and another for the log, the database and the
    # heartbeat (backend/). The names are unique because backend/ has a data
    # directory of its own. "colon" (#448): a relative name like a:b is not a
    # Windows drive path, so it is made absolute too.
    token = uuid.uuid4().hex[:8]
    data_name = f"wd326-{token}" if given != "colon" else f"w:wd448-{token}"
    wd = Watchdog(tmp_path, data_name=data_name)
    queue = f"wd326-{token}-queue"
    stray = ROOT / "backend" / wd.data.name
    recording = wd.bin / "recpy"
    recording.write_text(RECORDING_PYTHON, encoding="utf-8", newline="\n")
    recording.chmod(0o755)
    try:
        _anomaly_fixtures(wd)
        (tmp_path / queue).mkdir()
        (tmp_path / queue / "monitor-heartbeat.json").write_text(
            _beat_at(NIGHT - 601), encoding="utf-8"
        )
        arguments = ["--dry-run", "--monitor-dir", queue]
        environment = {"REAL_PYTHON": Path(sys.executable).as_posix()}
        if given != "variable":
            arguments += ["--data-dir", wd.data.name]
        else:
            environment["STOCK_DATA_DIR"] = wd.data.name
        result = wd.run(
            *arguments, cwd=tmp_path, python=recording.as_posix(), **environment
        )
        assert (wd.data / "locks" / "watchdog.lock").is_file()
        # The log files, the database and the heartbeat were all found: each of
        # these anomalies is read from one of them.
        for key in ("daily_no_end", "news_no_log", "news_llm_pending", "monitor_stale"):
            assert f"anomaly_planned key={key} " in result.stdout, result.stdout
        assert "anomaly_planned key=monitor_stale " in wd.log()
        # The helpers saw the same directory, not the relative spelling.
        seen = set(wd.text("helper_data_dir.log").split())
        assert seen == {wd.data.as_posix()}, seen
        assert not stray.exists()
    finally:
        shutil.rmtree(stray, ignore_errors=True)


def _left_work_directory(wd: Watchdog, name: str) -> Path:
    path = wd.logs / name
    path.mkdir()
    (path / "comment.md").write_text(
        "待使用者：left by a killed run\n", encoding="utf-8"
    )
    return path


def test_work_directories_a_killed_run_left_are_removed_by_the_next_run(wd):
    # #326: SIGKILL skips the EXIT trap, so logs/.watchdog.XXXXXX stayed for good.
    _anomaly_fixtures(wd)
    left = [
        _left_work_directory(wd, ".watchdog.k3Jd9a"),
        _left_work_directory(wd, ".watchdog.000000"),
    ]
    # What mktemp -d ".watchdog.XXXXXX" does not make stays: other names, a file
    # of that name, and a link to a directory (neither removed nor followed).
    kept = [
        _left_work_directory(wd, ".watchdog.abcdefg"),
        _left_work_directory(wd, ".watchdog.abc"),
        _left_work_directory(wd, ".other.k3Jd9a"),
    ]
    (wd.logs / ".watchdog.file01").write_text("not a directory\n", encoding="utf-8")
    elsewhere = wd.root / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "precious.txt").write_text("keep\n", encoding="utf-8")
    (wd.logs / ".watchdog.link01").symlink_to(elsewhere, target_is_directory=True)

    wd.run()

    assert [path.exists() for path in left] == [False, False]
    assert all(path.is_dir() for path in kept)
    assert (wd.logs / ".watchdog.file01").is_file()
    assert (wd.logs / ".watchdog.link01").is_symlink()
    assert (elsewhere / "precious.txt").read_text(encoding="utf-8") == "keep\n"
    assert wd.events()[0] == "stale_work_removed"
    assert "count=2 " in wd.log().splitlines()[0]
    assert ".watchdog.000000" in wd.log().splitlines()[0]
    # The run's own work directory was not among them: its comments went out.
    assert wd.text("gh_bodies.txt").count("待使用者：") == 3
    wd.run(now=NIGHT + 15 * 60)
    assert wd.events().count("stale_work_removed") == 1


def test_a_dry_run_only_says_which_work_directories_it_would_remove(wd):
    left = _left_work_directory(wd, ".watchdog.k3Jd9a")
    result = wd.run("--dry-run")
    assert "stale_work_planned count=1 " in result.stdout
    assert ".watchdog.k3Jd9a" in result.stdout
    assert (left / "comment.md").is_file()
    wd.run()
    assert not left.exists()


def test_a_run_that_cannot_take_the_lock_leaves_the_running_ones_work_directory(wd):
    # The run holding the lock has a work directory of its own; the next run is
    # turned away at the lock, before it looks at the logs directory.
    holder, _child = _hold_lock(wd)
    running = _left_work_directory(wd, ".watchdog.run123")
    try:
        result = wd.run()
    finally:
        holder.kill()
        holder.wait(timeout=30)
    assert wd.events() == ["locked"], result.stdout + result.stderr
    assert (running / "comment.md").is_file()


def test_a_run_without_the_lock_removes_no_work_directory(wd):
    # Without Python nothing holds the lock: another run may be going, and the
    # directory may be its own.
    other = _left_work_directory(wd, ".watchdog.run123")
    wd.run(python=(wd.root / "no-python.exe").as_posix())
    assert wd.events()[0] == "python_missing"
    assert "stale_work_removed" not in wd.events()
    assert (other / "comment.md").is_file()


def _lock_runner(lock_file: Path) -> list[str]:
    """What worker.job lock puts in front of the watchdog, for any lock file."""

    return [
        BASE_PYTHON,
        "-X",
        "utf8",
        "-m",
        "worker.job",
        "lock",
        str(lock_file),
        "--",
    ]


# #448: WATCHDOG_LOCK_HELD, the flag the lock-taking run sets for the run it starts,
# was also the only proof that a run holds the lock. Typed by hand it skipped the
# lock and still removed the work directories, among them the running one's.


def test_a_flag_typed_by_hand_does_not_remove_the_running_ones_work_directory(wd):
    holder, _child = _hold_lock(wd)
    running = _left_work_directory(wd, ".watchdog.run123")
    try:
        result = wd.run(WATCHDOG_LOCK_HELD="1")
    finally:
        holder.kill()
        holder.wait(timeout=30)
    assert (running / "comment.md").is_file(), result.stdout + result.stderr
    assert "stale_work_removed" not in wd.events()
    assert "lock_unverified" in wd.events()


@pytest.mark.parametrize("python", ["real", "missing"])
def test_a_flag_typed_by_hand_removes_no_work_directory_without_the_lock(wd, python):
    left = _left_work_directory(wd, ".watchdog.k3Jd9a")
    exe = None if python == "real" else (wd.root / "no-python.exe").as_posix()
    result = wd.run(python=exe, WATCHDOG_LOCK_HELD="1")
    assert (left / "comment.md").is_file(), result.stdout + result.stderr
    assert "stale_work_removed" not in wd.events()
    if python == "real":
        assert "lock_unverified" in wd.events()


def test_a_run_started_under_another_lock_removes_no_work_directory(wd):
    # Its parent is a worker.job lock, but of some other file: no lock of the
    # watchdog is held by it.
    left = _left_work_directory(wd, ".watchdog.k3Jd9a")
    other = wd.root / "other.lock"
    result = wd.run(
        "--data-dir",
        wd.data.as_posix(),
        wrapper=_lock_runner(other),
        cwd=ROOT / "backend",
        WATCHDOG_LOCK_HELD="1",
    )
    assert other.is_file()
    assert (left / "comment.md").is_file(), result.stdout + result.stderr
    assert "stale_work_removed" not in wd.events()
    assert "lock_unverified" in wd.events()


def test_a_run_started_under_the_watchdog_lock_removes_the_work_directories(wd):
    # The proof is the parent, not the way it was started: any worker.job lock of
    # the watchdog's own lock file will do.
    left = _left_work_directory(wd, ".watchdog.k3Jd9a")
    result = wd.run(
        "--data-dir",
        wd.data.as_posix(),
        wrapper=_lock_runner(wd.data / "locks" / "watchdog.lock"),
        cwd=ROOT / "backend",
        WATCHDOG_LOCK_HELD="1",
    )
    assert not left.exists(), result.stdout + result.stderr
    assert wd.events()[0] == "stale_work_removed"
    assert "lock_unverified" not in wd.events()


def _absolute(value: str, cwd: Path) -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    function = re.search(r"^absolute\(\) \{.*?^\}$", source, re.S | re.M)
    assert function, "absolute() is not in watchdog.sh"
    result = subprocess.run(
        [
            BASH,
            "-c",
            function.group(0) + '\ncd "$2" && absolute "$1"',
            "bash",
            value,
            str(cwd),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize(
    ("given", "relative"),
    [
        ("data", True),
        ("./data", True),
        ("a:b", True),
        ("ab:c", True),
        ("C:", True),
        ("/x/y", False),
        ("C:/x", False),
        ("c:\\x\\y", False),
        ("D:/", False),
    ],
)
def test_absolute_takes_only_a_drive_with_a_separator_for_a_full_path(
    tmp_path, given, relative
):
    # #448: a:b is a name relative to the current directory, not the drive a.
    expected = f"{tmp_path}/{given.removeprefix('./')}" if relative else given
    assert _absolute(given, tmp_path) == expected


def test_unreadable_database_is_logged_and_not_reported_ok(wd):
    (wd.data / "stock.db").write_bytes(b"not a database")
    wd.run()
    assert wd.events() == [
        "news_llm_check_failed",
        "llm_auth_check_failed",
        "invariants_check_failed",
    ]
    assert wd.text("gh_calls.log") == ""


# --- daily result from schedule_runs (Issue #185) --------------------------


@pytest.mark.parametrize(
    ("runs", "commented"),
    [
        ([("skipped", {"reason": "low_memory"})], "`skipped:low_memory`"),
        ([("partial", {"reason": "official_collection_incomplete"})], "`partial`"),
        (
            [("failed", {"steps": {"collect": "success", "analyze": "failed"}})],
            "`failed`",
        ),
        ([("success", {"steps": {"catchup": "success", "collect": "success"}})], None),
    ],
    ids=["skipped", "partial", "failed", "success"],
)
def test_daily_result_comments_only_when_not_complete_and_once_a_day(
    wd, runs, commented
):
    _daily_log_done(wd)
    _daily_db(wd.data / "stock.db", runs)
    wd.run()
    wd.run(now=NIGHT + 15 * 60)
    bodies = wd.text("gh_bodies.txt")
    if commented is None:
        assert wd.text("gh_calls.log") == ""
        assert wd.events() == ["schedules_ok", "schedules_ok"]
    else:
        assert len(wd.text("gh_calls.log").splitlines()) == 1
        assert f"daily 排程：台北 2026-10-19 的 daily 結果是 {commented}" in bodies
        assert wd.events()[-1] == "anomaly_already_commented"


def _add_daily_run(
    path: Path, status: str, started: int, day: str = "2026-10-19", summary=None
) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO schedule_runs (job, target_date, status, started_at, summary_json)"
            " VALUES ('daily', ?, ?, ?, ?)",
            (day, status, _utc_text(started), json.dumps(summary or {})),
        )
    conn.close()


def _set_last_daily_run(path: Path, status: str) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE schedule_runs SET status = ? WHERE id = (SELECT max(id) FROM schedule_runs)",
            (status,),
        )
    conn.close()


AT_2130 = NIGHT - 105 * 60
AT_2300 = NIGHT - 15 * 60


def test_a_failed_2130_daily_waits_for_the_2300_retry_that_succeeds(wd):
    """#466 AC-2: 21:30 partial, 23:00 success: no comment on the way."""

    _daily_log_done(wd)
    db = wd.data / "stock.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE schedule_runs (id INTEGER PRIMARY KEY, job TEXT,"
            " target_date DATE, status TEXT, started_at DATETIME, summary_json TEXT)"
        )
    conn.close()
    _add_daily_run(db, "partial", AT_2130)
    for minutes in (-90, -60, -30):  # 21:45, 22:15, 22:45: before the retry
        wd.run(now=NIGHT + minutes * 60)
    _add_daily_run(db, "running", AT_2300)
    wd.run()  # 23:15: the retry is still running
    _set_last_daily_run(db, "success")
    wd.run(now=LAST_RUN)  # 23:45
    wd.run(now=AT_0045)  # Tuesday: the day before ended success
    assert wd.text("gh_calls.log") == ""
    assert not [event for event in wd.events() if event.startswith("anomaly")]


def test_an_abandoned_2130_daily_and_a_2300_success_are_not_reported(wd):
    """Decision 6638008818: 21:30 stuck, killed at 22:50 and recorded abandoned by 23:00."""

    _daily_log_done(wd)
    db = wd.data / "stock.db"
    _daily_db(db, [])
    # The abandoned row is failed (its error names the lock; the helper reads the status).
    _add_daily_run(db, "failed", AT_2130)
    _add_daily_run(db, "success", AT_2300)
    wd.run()
    wd.run(now=LAST_RUN)
    assert wd.text("gh_calls.log") == ""
    assert not [event for event in wd.events() if event.startswith("anomaly")]


def test_a_failed_2300_retry_is_commented_once(wd):
    _daily_log_done(wd)
    _daily_db(
        wd.data / "stock.db",
        [("partial", {"reason": "official_collection_incomplete"}), ("failed", {})],
    )
    wd.run(now=NIGHT - 30 * 60)  # 22:45: not judged yet
    assert wd.text("gh_calls.log") == ""
    wd.run()  # 23:15
    wd.run(now=LAST_RUN)
    assert len(wd.text("gh_calls.log").splitlines()) == 1
    assert "daily 結果是 `failed`" in wd.text("gh_bodies.txt")


def test_a_daily_still_running_past_the_task_limit_has_died(wd):
    _daily_log_done(wd)
    db = wd.data / "stock.db"
    _daily_db(db, [("partial", {})])
    # The retry still marked running 2 h 40 min after it started (the 2.5-hour limit).
    _add_daily_run(db, "running", NIGHT - 160 * 60)
    wd.run()
    assert "daily 結果是 `failed`" in wd.text("gh_bodies.txt")


# --- the previous trading day, from 00:30 (#466 review 6641540634) ---------------------

AT_0015 = NIGHT + 60 * 60  # Tuesday 2026-10-20 00:15 Taipei
AT_0045 = NIGHT + 90 * 60
AT_0115 = NIGHT + 120 * 60


@pytest.mark.parametrize("stuck", ["2300_retry", "2145_catchup"])
def test_a_retry_stuck_past_midnight_is_reported_once_after_0030(wd, stuck):
    """21:30 failed and the run after it hangs: it is judged running all night."""

    _daily_log_done(wd)
    db = wd.data / "stock.db"
    _daily_db(db, [])
    _add_daily_run(db, "failed", AT_2130)
    if stuck == "2300_retry":
        # The 23:00 retry hangs in collect; the job ends it at 00:20, the row stays running.
        _add_daily_run(db, "running", AT_2300)
    else:
        # serve restarted at 21:45 and its catch-up hangs (ended at 23:05); the 23:00
        # trigger found the lock held.
        _add_daily_run(db, "running", NIGHT - 90 * 60)
        _add_daily_run(db, "skipped", AT_2300, summary={"reason": "already_running"})
    for now in (NIGHT, LAST_RUN, AT_0015):  # 23:15, 23:45, 00:15: still running
        wd.run(now=now)
    assert wd.text("gh_calls.log") == ""
    wd.run(now=AT_0045)
    wd.run(now=AT_0115)
    assert len(wd.text("gh_calls.log").splitlines()) == 1
    body = wd.text("gh_bodies.txt")
    assert "daily 排程：台北 2026-10-19（前一個交易日）的 daily 結果是 `failed`" in body
    assert " anomaly_commented key=daily_result_20261019 date=20261020 " in wd.log()


def test_a_day_reported_that_night_is_not_reported_again_after_midnight(wd):
    _daily_log_done(wd)
    _daily_db(wd.data / "stock.db", [("partial", {}), ("failed", {})])
    wd.run()  # 23:15: both runs failed, commented
    wd.run(now=AT_0045)
    wd.run(now=AT_0115)
    assert len(wd.text("gh_calls.log").splitlines()) == 1


def test_a_friday_reported_on_saturday_is_not_reported_again_on_monday(wd):
    friday = NIGHT + 4 * 86400  # 2026-10-23 23:15 Taipei
    (wd.logs / "daily-20261023.log").write_text(
        "===== s start\n===== e end exit=2 seconds=9\n", encoding="utf-8"
    )
    db = wd.data / "stock.db"
    _daily_db(db, [])
    _add_daily_run(db, "failed", friday - 105 * 60, day="2026-10-23")
    _add_daily_run(db, "running", friday - 15 * 60, day="2026-10-23")
    wd.run(now=friday)
    for days in (1, 2, 3):  # Saturday, Sunday and Monday 00:45
        wd.run(now=friday + 90 * 60 + (days - 1) * 86400)
    assert len(wd.text("gh_calls.log").splitlines()) == 1
    assert "台北 2026-10-23（前一個交易日）" in wd.text("gh_bodies.txt")


def test_a_missing_daily_log_waits_for_the_2300_retry(wd):
    (wd.logs / "daily-20261016.log").write_text(
        "===== x start\n===== y end exit=0 seconds=1\n", encoding="utf-8"
    )
    for minutes in (-90, -60, -30):  # 21:45, 22:15, 22:45: 23:00 may still run it
        wd.run(now=NIGHT + minutes * 60)
    assert "daily_no_end" not in wd.log()
    wd.run()  # 23:15: neither trigger ran
    body = wd.text("gh_bodies.txt")
    assert (
        "daily 排程：台北 20261019 已過 23:00 的重試" in body
        and "不存在（今日未執行）" in body
    )


def test_daily_result_reads_the_complete_run_of_the_day(wd):
    _daily_log_done(wd)
    _daily_db(
        wd.data / "stock.db",
        [
            ("success", {"steps": {"collect": "success"}}),
            ("skipped", {"reason": "already_complete", "related_run_id": 1}),
            ("skipped", {"reason": "low_memory"}),
        ],
    )
    wd.run()
    assert wd.text("gh_calls.log") == ""


def test_daily_result_reports_unconfirmed_no_session_and_incomplete_catchup(wd):
    _daily_log_done(wd)
    _daily_db(
        wd.data / "stock.db",
        [("non_trading_unconfirmed", {"reason": "official_no_session_unconfirmed"})],
    )
    result = wd.run("--dry-run")
    assert "daily 結果是 `non_trading_unconfirmed`" in result.stdout
    (wd.data / "stock.db").unlink()
    _daily_db(
        wd.data / "stock.db",
        [("success", {"steps": {"catchup": "partial", "collect": "success"}})],
    )
    result = wd.run("--dry-run")
    assert "補抓前幾個交易日沒有補齊（catchup）" in result.stdout


def test_daily_result_is_not_judged_on_weekends(wd):
    _daily_log_done(wd)
    _daily_db(wd.data / "stock.db", [("failed", {})], day="2026-10-18")
    wd.run(now=NIGHT - 24 * 3600)  # Sunday 23:15
    assert wd.text("gh_calls.log") == ""


# --- news_llm failures without batches (Issue #185) ------------------------


def test_three_failed_news_llm_runs_are_reported(wd):
    # cli_not_found / api_key_env_refused write a failed run without batches;
    # a run killed by the task limit stays running.
    _news_llm_runs(
        wd.data / "stock.db",
        [("success", 9000), ("failed", 7200), ("failed", 3600), ("running", 5800)],
    )
    result = wd.run("--dry-run")
    assert (
        "news_llm：24 小時內最近 3 筆 `run_type=news_llm` 的 run 都是 failed"
        in result.stdout
    )


def test_recent_running_news_llm_run_is_not_counted_as_failed(wd):
    _news_llm_runs(
        wd.data / "stock.db", [("failed", 9000), ("failed", 7200), ("running", 600)]
    )
    wd.run()
    assert wd.text("gh_calls.log") == ""


def _news_end(taipei: str, news_llm_exit: str) -> str:
    return f"===== 2026-{taipei}.1234567+08:00 end exit=0 seconds=5 news_llm_exit={news_llm_exit}"


def test_news_llm_exit_codes_in_news_logs_are_reported(wd):
    # news_llm_results missing: news-llm exits 1 without writing a run.
    (wd.logs / "news-20261018.log").write_text(
        _news_end("10-18T21:30:30", "0")
        + "\n"
        + _news_end("10-18T23:30:30", "1")
        + "\n",
        encoding="utf-8",
    )
    news = wd.logs / "news-20261019.log"
    news.write_text(
        _news_end("10-19T18:00:30", "wrapper_error")
        + "\r\n"
        + _news_end("10-19T20:00:30", "1")
        + "\r\n",
        encoding="utf-8",
    )
    os.utime(news, (NIGHT - 600, NIGHT - 600))
    result = wd.run("--dry-run")
    assert (
        "news 日誌 24 小時內最後 3 次的 `news_llm_exit` 是 1 wrapper_error 1"
        in result.stdout
    )
    news.write_text(
        _news_end("10-19T18:00:30", "1")
        + "\n"
        + _news_end("10-19T20:00:30", "2")
        + "\n",
        encoding="utf-8",
    )
    os.utime(news, (NIGHT - 600, NIGHT - 600))
    assert "news_llm_exit" not in wd.run("--dry-run").stdout


def test_news_llm_failures_older_than_a_day_are_not_reported_again(wd):
    # Three failures in yesterday's log, all more than 24 hours ago.
    (wd.logs / "news-20261018.log").write_text(
        "\n".join(_news_end(f"10-18T{hour}:00:30", "1") for hour in (16, 18, 20))
        + "\n",
        encoding="utf-8",
    )
    stale = NIGHT - 2 * 86400
    os.utime(wd.logs / "news-20261018.log", (stale, stale))
    _news_llm_runs(
        wd.data / "stock.db",
        [("failed", 3 * 86400), ("failed", 2 * 86400 + 600), ("failed", 2 * 86400)],
    )
    result = wd.run("--dry-run")
    assert "news_llm：" not in result.stdout
    # The stopped job itself is reported by the news log check.
    assert "news 排程：最新日誌寫於" in result.stdout


# --- data invariants (Issue #229) -------------------------------------------

# Latest bars of NIGHT's Taipei day 2026-10-19; an older day's unknown source
# is outside the provenance check.
HEALTHY_BARS = [
    ("2026-10-16", "unknown", None),
    ("2026-10-19", "twse_stock_day_all", "2026-10-19 00:00:00.000000"),
    ("2026-10-19", "tpex_daily_close", "2026-10-19 00:00:00.000000"),
]
# Pending rows have no model yet.
HEALTHY_LLM = [("done", "claude-sonnet-5-5", "news-v3"), ("pending", None, "news-v3")]


def _invariant_db(
    path: Path,
    bars: list[tuple[str, str | None, str | None]],
    llm: list[tuple[str, str | None, str | None]],
) -> None:
    """market_bars (trading_date, source, data_as_of) and news_llm_results
    (llm_status, llm_model, prompt_version) rows."""

    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE market_bars (id INTEGER PRIMARY KEY, trading_date DATE,"
            " source VARCHAR(120), data_as_of DATETIME)"
        )
        conn.executemany(
            "INSERT INTO market_bars (trading_date, source, data_as_of) VALUES (?, ?, ?)",
            bars,
        )
        conn.execute(
            "CREATE TABLE news_llm_results (id INTEGER PRIMARY KEY,"
            " llm_status VARCHAR(20), llm_model VARCHAR(80), prompt_version VARCHAR(40))"
        )
        conn.executemany(
            "INSERT INTO news_llm_results (llm_status, llm_model, prompt_version)"
            " VALUES (?, ?, ?)",
            llm,
        )
    conn.close()


def test_invariants_hold_on_healthy_data(wd):
    _invariant_db(wd.data / "stock.db", HEALTHY_BARS, HEALTHY_LLM)
    result = wd.run()
    assert wd.text("gh_calls.log") == ""
    assert wd.events() == ["schedules_ok"]
    assert (
        "invariant future_trading_date ok max_trading_date=2026-10-19 today=2026-10-19\n"
        "invariant latest_bar_provenance ok trading_date=2026-10-19 bars=2"
        " unknown_source=0 null_data_as_of=0\n"
        "invariant llm_done_provenance ok done=1 missing_model=0"
        " empty_prompt_version=0\n"
    ) in result.stdout


def test_invariants_skip_empty_tables(wd):
    _invariant_db(wd.data / "stock.db", [], [])
    result = wd.run()
    assert wd.events() == ["schedules_ok"]
    assert "invariant future_trading_date skip reason=no_market_bars" in result.stdout
    assert "invariant llm_done_provenance ok done=0" in result.stdout


@pytest.mark.parametrize(
    ("bars", "llm", "commented"),
    [
        (
            [*HEALTHY_BARS, ("2026-10-20", "twse_stock_day_all", "2026-10-20")],
            HEALTHY_LLM,
            "資料不變量：`market_bars` 最新 `trading_date` 是 2026-10-20，晚於台北今日 2026-10-19",
        ),
        (
            [*HEALTHY_BARS, ("2026-10-19", "unknown", "2026-10-19")],
            HEALTHY_LLM,
            "資料不變量：最新交易日 2026-10-19 的 3 列 `market_bars` 中，1 列 `source` 是 `unknown` 或空、0 列沒有 `data_as_of`",
        ),
        (
            [*HEALTHY_BARS, ("2026-10-19", "twse_stock_day_all", None)],
            HEALTHY_LLM,
            "資料不變量：最新交易日 2026-10-19 的 3 列 `market_bars` 中，0 列 `source` 是 `unknown` 或空、1 列沒有 `data_as_of`",
        ),
        (
            HEALTHY_BARS,
            [*HEALTHY_LLM, ("done", None, "news-v3")],
            "資料不變量：`news_llm_results` 的 2 列 `llm_status=done` 中，1 列沒有 `llm_model`、0 列 `prompt_version` 為空",
        ),
        (
            HEALTHY_BARS,
            [*HEALTHY_LLM, ("done", "claude-sonnet-5-5", "")],
            "資料不變量：`news_llm_results` 的 2 列 `llm_status=done` 中，0 列沒有 `llm_model`、1 列 `prompt_version` 為空",
        ),
    ],
    ids=[
        "future_date",
        "unknown_source",
        "null_data_as_of",
        "null_llm_model",
        "empty_prompt_version",
    ],
)
def test_invariant_violation_is_commented_once_a_day(wd, bars, llm, commented):
    _invariant_db(wd.data / "stock.db", bars, llm)
    db = wd.data / "stock.db"
    before = (db.read_bytes(), db.stat().st_mtime_ns)
    dry = wd.run("--dry-run")
    assert f"將在 #1 留言：\n待使用者：{commented}" in dry.stdout
    assert " violation " in dry.stdout
    assert wd.text("gh_calls.log") == ""
    wd.run()
    wd.run(now=NIGHT + 15 * 60)
    assert len(wd.text("gh_calls.log").splitlines()) == 1
    assert f"待使用者：{commented}" in wd.text("gh_bodies.txt")
    assert wd.events()[-1] == "anomaly_already_commented"
    # The watchdog only reads the database.
    assert (db.read_bytes(), db.stat().st_mtime_ns) == before


def _status_sync_rows(path: Path, rows: list[tuple[str, str, str, str]]) -> None:
    """data_quality instrument_status_sync rows
    (entity_key, status, as_of_date, checks_json)."""

    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE data_quality (id INTEGER PRIMARY KEY,"
            " entity_type VARCHAR(40), entity_key VARCHAR(160), as_of_date DATE,"
            " status VARCHAR(30), checks_json JSON)"
        )
        conn.executemany(
            "INSERT INTO data_quality"
            " (entity_type, entity_key, status, as_of_date, checks_json)"
            " VALUES ('instrument_status_sync', ?, ?, ?, ?)",
            rows,
        )
    conn.close()


def test_a_skipped_status_sync_is_commented_until_a_later_sync_applies(wd):
    db = wd.data / "stock.db"
    _invariant_db(db, HEALTHY_BARS, HEALTHY_LLM)
    _status_sync_rows(
        db,
        [
            # superseded by a later sync
            ("TWSE", "skipped", "2026-10-15", '{"absent": 90, "dormant": 0}'),
            ("TWSE", "applied", "2026-10-16", '{"absent": 1, "dormant": 0}'),
            ("TPEx", "applied", "2026-10-15", '{"absent": 0, "dormant": 0}'),
            ("TPEx", "skipped", "2026-10-16", '{"absent": 3, "dormant": 60}'),
        ],
    )
    dry = wd.run("--dry-run")
    assert (
        "invariant instrument_status_sync violation exchanges=2"
        " skipped=TPEx@2026-10-16:absent=3,dormant=60"
    ) in dry.stdout
    assert (
        "待使用者：資料不變量：最近一次標的狀態同步被防呆略過"
        "（TPEx@2026-10-16:absent=3,dormant=60；"
    ) in dry.stdout

    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO data_quality (entity_type, entity_key, status, as_of_date)"
            " VALUES ('instrument_status_sync', 'TPEx', 'applied', '2026-10-19')"
        )
    conn.close()
    result = wd.run()
    assert "invariant instrument_status_sync ok exchanges=2 skipped=none" in (
        result.stdout
    )
    assert wd.events()[-1] == "schedules_ok"
    assert wd.text("gh_calls.log") == ""


CALENDAR_EVIDENCE = (
    '{"execution": {"earliest": null, "calendar": {"source": "twse_holiday_schedule",'
    ' "raw_payload_ids": [7676], "missing_reason": null}}}'
)
# A signal written before the calendar-based analyze (no execution.calendar).
OLD_EVIDENCE = '{"execution": {"earliest": null}}'


def _signal_rows(path: Path, rows: list[tuple[str, str, str | None, str]]) -> None:
    """trading_calendar_days (empty: the table marks a migrated database) and
    signals (signal_key, signal_date, earliest_execution_date,
    rule_evidence_json) rows."""

    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS trading_calendar_days (id INTEGER PRIMARY KEY)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS signals (id INTEGER PRIMARY KEY,"
            " signal_key VARCHAR(220), signal_date DATE, earliest_execution_date DATE,"
            " rule_evidence_json JSON)"
        )
        conn.executemany(
            "INSERT INTO signals (signal_key, signal_date, earliest_execution_date,"
            " rule_evidence_json) VALUES (?, ?, ?, ?)",
            rows,
        )
    conn.close()


def test_signals_without_an_execution_date_are_commented(wd):
    # #294: the calendar step is non-blocking, so a missing year shows here.
    db = wd.data / "stock.db"
    _invariant_db(db, HEALTHY_BARS, HEALTHY_LLM)
    assert "invariant execution_calendar skip reason=no_trading_calendar" in (
        wd.run("--dry-run").stdout
    )
    # Migrated to 0020, but the latest signals predate the calendar and are
    # never backfilled: not a violation (#294 review L3).
    _signal_rows(
        db,
        [
            ("analysis-TWSE-2330-2026-10-16-a", "2026-10-16", None, OLD_EVIDENCE),
            ("analysis-TWSE-2330-2026-10-16-b", "2026-10-16", None, OLD_EVIDENCE),
        ],
    )
    dry = wd.run("--dry-run")
    assert (
        "invariant execution_calendar skip reason=signals_before_calendar"
        " signal_date=2026-10-16 signals=2"
    ) in dry.stdout
    assert "待使用者" not in dry.stdout
    _signal_rows(
        db,
        [
            # Another namespace is outside the check.
            (
                "backtest-7-TWSE-2330-2026-10-19-a",
                "2026-10-19",
                None,
                CALENDAR_EVIDENCE,
            ),
            (
                "analysis-TWSE-2330-2026-10-19-a",
                "2026-10-19",
                "2026-10-20",
                CALENDAR_EVIDENCE,
            ),
            ("analysis-TWSE-2330-2026-10-19-b", "2026-10-19", None, CALENDAR_EVIDENCE),
        ],
    )
    dry = wd.run("--dry-run")
    assert (
        "invariant execution_calendar violation signal_date=2026-10-19"
        " signals=2 without_date=1"
    ) in dry.stdout
    assert (
        "待使用者：資料不變量：最新訊號日 2026-10-19 的 2 筆 analysis 訊號中，"
        "1 筆沒有規則最早執行日"
    ) in dry.stdout

    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE signals SET earliest_execution_date='2026-10-20'"
            " WHERE signal_key='analysis-TWSE-2330-2026-10-19-b'"
        )
    conn.close()
    result = wd.run()
    assert (
        "invariant execution_calendar ok signal_date=2026-10-19"
        " signals=2 without_date=0"
    ) in result.stdout
    assert wd.events()[-1] == "schedules_ok"


def _levels_steps(path: Path, rows: list[tuple[str, str, str | None]]) -> None:
    """Daily runs of 2026-10-19 with a strategy_levels step: (run status, step
    status, finished_at)."""

    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schedule_runs (id INTEGER PRIMARY KEY, job TEXT,"
            " target_date DATE, status TEXT, started_at DATETIME, finished_at DATETIME,"
            " summary_json TEXT)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schedule_run_steps (id INTEGER PRIMARY KEY,"
            " schedule_run_id INTEGER, step VARCHAR(40), status VARCHAR(30))"
        )
        for run_status, step_status, finished in rows:
            run_id = conn.execute(
                "INSERT INTO schedule_runs (job, target_date, status, started_at,"
                " finished_at, summary_json) VALUES ('daily', '2026-10-19', ?, ?, ?, '{}')",
                (run_status, _utc_text(NIGHT - 3600), finished),
            ).lastrowid
            conn.execute(
                "INSERT INTO schedule_run_steps (schedule_run_id, step, status)"
                " VALUES (?, 'strategy_levels', ?)",
                (run_id, step_status),
            )
    conn.close()


def test_a_failed_strategy_levels_step_is_commented(wd):
    # #274 (#293 review L2): the step never changes the run status.
    db = wd.data / "stock.db"
    _invariant_db(db, HEALTHY_BARS, HEALTHY_LLM)
    assert "invariant strategy_levels skip reason=no_schedule_run_steps" in (
        wd.run("--dry-run").stdout
    )
    done = _utc_text(NIGHT - 1800)
    _levels_steps(db, [("success", "failed", done)])
    dry = wd.run("--dry-run")
    assert (
        "invariant strategy_levels violation target_date=2026-10-19 run_id=1"
        " status=failed"
    ) in dry.stdout
    assert (
        "待使用者：資料不變量：daily run 1（目標日 2026-10-19）的 strategy_levels"
        " 步驟是 `failed`"
    ) in dry.stdout
    # A run still in progress is not judged; the last finished one still is.
    _levels_steps(db, [("running", "running", None)])
    assert "invariant strategy_levels violation target_date=2026-10-19 run_id=1" in (
        wd.run("--dry-run").stdout
    )
    # skipped (analyze failed) is the run's own anomaly, not this line's.
    _levels_steps(db, [("failed", "skipped", done)])
    assert (
        "invariant strategy_levels ok target_date=2026-10-19 run_id=3 status=skipped"
    ) in wd.run("--dry-run").stdout
    _levels_steps(db, [("success", "success", done)])
    result = wd.run()
    assert (
        "invariant strategy_levels ok target_date=2026-10-19 run_id=4 status=success"
    ) in result.stdout
    assert "invariant_strategy_levels" not in wd.text("gh_calls.log")


def _monitor_beat(wd: Watchdog, text: str) -> None:
    (wd.logs / "monitor-heartbeat.json").write_text(text, encoding="utf-8")


def _beat_at(epoch: int) -> str:
    at = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return json.dumps({"written_at": at, "mode": "live", "gh_calls": 2, "pid": 1})


def test_a_stopped_event_monitor_is_commented_once_a_day(wd):
    # No heartbeat file: the monitor is not registered, nothing to judge.
    wd.run()
    _monitor_beat(wd, _beat_at(NIGHT - 600))
    wd.run()
    assert wd.text("gh_calls.log") == ""
    assert wd.events() == ["schedules_ok", "schedules_ok"]

    _monitor_beat(wd, _beat_at(NIGHT - 601))
    wd.run()
    assert len(wd.text("gh_calls.log").splitlines()) == 1
    body = wd.text("gh_bodies.txt")
    assert (
        "待使用者：事件 monitor：最後一次輪詢在 2026-10-19T15:04:59Z（10 分鐘前）"
        in body
    )
    assert "\\stock-lab\\monitor" in body and "monitor.log" in body
    assert "key=monitor_stale" in wd.log()
    wd.run(now=NIGHT + 15 * 60)
    assert len(wd.text("gh_calls.log").splitlines()) == 1
    assert wd.events()[-1] == "anomaly_already_commented"


def test_the_watchdog_reads_the_heartbeat_of_the_monitor_dir(wd):
    """#338: in the scheduler container the monitor's files are in the bind mounted
    queue directory, not in the data directory's logs."""
    queue = wd.root / "coordination"
    queue.mkdir()
    (queue / "monitor-heartbeat.json").write_text(_beat_at(NIGHT - 601), "utf-8")
    _monitor_beat(wd, _beat_at(NIGHT - 60))  # a beat left in the data directory
    result = wd.run("--dry-run")
    assert "monitor_stale" not in result.stdout
    result = wd.run("--dry-run", "--monitor-dir", queue.as_posix())
    assert "anomaly_planned key=monitor_stale" in result.stdout
    assert f"{queue.as_posix()}/monitor.log" in result.stdout


def test_an_unreadable_monitor_heartbeat_is_commented(wd):
    _monitor_beat(wd, '{"written_at": ')
    result = wd.run("--dry-run")
    assert "待使用者：事件 monitor：" in result.stdout
    assert "monitor-heartbeat.json` 讀不出輪詢時間" in result.stdout


def test_a_monitor_whose_gh_calls_keep_failing_is_commented(wd):
    beat = json.loads(_beat_at(NIGHT - 60))
    beat.update(gh_failed_polls=9, gh_failed_since="2026-10-19T13:50:00Z")
    _monitor_beat(wd, json.dumps(beat))
    wd.run()
    assert wd.text("gh_calls.log") == ""
    beat.update(gh_failed_polls=10, gh_error="HTTP 401: Bad credentials")
    _monitor_beat(wd, json.dumps(beat))
    wd.run()
    body = wd.text("gh_bodies.txt")
    assert (
        "待使用者：事件 monitor：gh 從 2026-10-19T13:50:00Z 起連續 10 輪失敗"
        "（最後的錯誤：HTTP 401: Bad credentials）"
    ) in body
    assert "`gh auth status`" in body and "`gh api rate_limit`" in body
    assert "key=monitor_gh_failed" in wd.log()
    beat.update(json.loads(_beat_at(NIGHT + 14 * 60)), gh_failed_polls=25)
    _monitor_beat(wd, json.dumps(beat))
    wd.run(now=NIGHT + 15 * 60)
    assert len(wd.text("gh_calls.log").splitlines()) == 1


def _helper_module():
    spec = importlib.util.spec_from_file_location(
        "watchdog_helper", SCRIPT.with_name("watchdog_helper.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_helper_connection_refuses_writes(tmp_path):
    # Every helper check, the invariants included, reads through _connect.
    helper = _helper_module()
    db = tmp_path / "stock.db"
    _invariant_db(db, HEALTHY_BARS, HEALTHY_LLM)
    conn = helper._connect(str(db))
    try:
        assert conn.execute("PRAGMA query_only").fetchone() == (1,)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("UPDATE market_bars SET source='unknown'")
        # mode=ro still refuses with query_only switched off.
        conn.execute("PRAGMA query_only=OFF")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("UPDATE market_bars SET source='unknown'")
    finally:
        conn.close()
    assert "unknown_source=0" in helper.invariants(str(db), "2026-10-19")


# claude -p and gh authentication (#337) ------------------------------------------


def _llm_runs(path: Path, runs: list[tuple[str, int, list[str | None]]]) -> None:
    """LLM runs: (run_type, started seconds before NIGHT, batch reasons)."""

    with sqlite3.connect(path) as conn:
        _ingestion_runs(conn)
        for run_type, age, reasons in runs:
            batches = [
                {"batch": n, "status": "done" if reason is None else "pending"}
                | ({} if reason is None else {"reason": reason})
                for n, reason in enumerate(reasons, start=1)
            ]
            conn.execute(
                "INSERT INTO ingestion_runs (run_type, status, started_at, metadata_json)"
                " VALUES (?, 'failed', ?, ?)",
                (run_type, _utc_text(NIGHT - age), json.dumps({"batches": batches})),
            )
    conn.close()


def test_an_auth_error_of_the_latest_llm_run_is_commented_once_a_taipei_day(wd):
    db = wd.data / "stock.db"
    _llm_runs(
        db,
        [
            ("candidate_notes", 7200, [None]),
            ("candidate_notes", 3600, ["not_logged_in"]),
            ("news_llm", 1800, ["timeout", "not_logged_in"]),
        ],
    )
    wd.run()
    bodies = wd.text("gh_bodies.txt")
    assert bodies.count("待使用者：Claude Code 認證：") == 1
    assert "最近一次 run：news_llm run 3、candidate_notes run 2。" in bodies
    assert "`claude setup-token`" in bodies and "`CLAUDE_CODE_OAUTH_TOKEN`" in bodies
    wd.run(now=NIGHT + 1800)
    assert wd.text("gh_bodies.txt").count("Claude Code 認證：") == 1
    assert "anomaly_already_commented" in wd.events()


def test_an_llm_auth_error_that_a_later_run_of_its_step_cleared_is_not_commented(wd):
    db = wd.data / "stock.db"
    _llm_runs(
        db,
        [
            ("candidate_notes", 3600, ["not_logged_in"]),
            ("candidate_notes", 1800, [None]),
            ("news_llm", 7200, ["not_logged_in"]),
            ("news_llm", 600, ["rate_limited"]),
        ],
    )
    result = wd.run()
    assert "Claude Code 認證" not in wd.text("gh_bodies.txt") + result.stdout
    assert _helper_module().llm_auth(str(db), str(NIGHT)) == ""
    empty = wd.root / "empty.db"
    sqlite3.connect(empty).close()
    assert _helper_module().llm_auth(str(empty), str(NIGHT)) == "skip"


def test_an_llm_auth_error_older_than_a_day_is_not_commented(wd):
    # The latest run of each step failed authentication; only the window keeps
    # a step that stopped running (news-llm switched off) from a comment a day.
    db = wd.data / "stock.db"
    _llm_runs(
        db,
        [
            ("news_llm", 24 * 3600 + 60, ["not_logged_in"]),
            ("candidate_notes", 24 * 3600 - 60, ["not_logged_in"]),
        ],
    )
    helper = _helper_module()
    assert helper.llm_auth(str(db), str(NIGHT)) == "candidate_notes run_id=2"
    assert helper.llm_auth(str(db), str(NIGHT + 120)) == ""
    wd.run(now=NIGHT + 120)
    assert "Claude Code 認證" not in wd.text("gh_bodies.txt")
    assert wd.events() == ["schedules_ok"]


@pytest.mark.parametrize("mode,code", [("401", 1), ("no_token", 4)])
def test_a_refused_gh_is_commented_once_gh_is_accepted_again(wd, mode, code):
    # AC-2: the watchdog cannot comment while GitHub refuses gh; the runs of the
    # outage are logged and the first accepted run posts one comment a day.
    start = NIGHT - 6 * 3600  # 17:15 Taipei: the whole day 1 stays on 10/19
    (wd.fake / "gh_mode").write_text(mode, encoding="utf-8")
    wd.run(now=start)
    wd.run(now=start + 1800)
    assert wd.text("gh_calls.log") == ""
    assert len(wd.text("gh_api.log").splitlines()) == 2
    assert wd.events() == ["gh_auth_failed", "gh_auth_failed"]
    assert f"gh_auth_failed exit={code} date=20261019" in wd.log()

    (wd.fake / "gh_mode").unlink()
    wd.run(now=start + 3600)
    bodies = wd.text("gh_bodies.txt")
    assert bodies.count("待使用者：gh 認證：") == 1
    assert (
        "2026-10-19T09:15:00Z 到 2026-10-19T09:45:00Z 的 2 次看門狗執行" in bodies
        and "期間沒有其他異常" in bodies
        and "`GH_TOKEN`" in bodies
    )
    wd.run(now=start + 5400)  # nothing new since the comment
    assert len(wd.text("gh_calls.log").splitlines()) == 1

    # A second outage the same Taipei day waits for the next day's comment.
    (wd.fake / "gh_mode").write_text(mode, encoding="utf-8")
    wd.run(now=start + 7200)
    (wd.fake / "gh_mode").unlink()
    wd.run(now=start + 9000)
    assert len(wd.text("gh_calls.log").splitlines()) == 1
    assert wd.events()[-1] == "anomaly_already_commented"
    next_day = start + 86400
    wd.run(now=next_day)
    bodies = wd.text("gh_bodies.txt")
    assert bodies.count("待使用者：gh 認證：") == 2
    assert "2026-10-19T11:15:00Z 到 2026-10-19T11:15:00Z 的 1 次看門狗執行" in bodies
    wd.run(now=next_day + 1800)
    assert len(wd.text("gh_calls.log").splitlines()) == 2


def test_anomalies_held_back_by_a_refused_gh_are_posted_with_the_gh_comment(wd):
    _anomaly_fixtures(wd)
    (wd.fake / "gh_mode").write_text("401", encoding="utf-8")
    wd.run()
    assert wd.text("gh_calls.log") == ""
    assert wd.events().count("anomaly_not_commented") == 3
    (wd.fake / "gh_mode").unlink()
    wd.run(now=NIGHT + 900)
    bodies = wd.text("gh_bodies.txt")
    assert bodies.count("待使用者：") == 4
    assert bodies.index("待使用者：gh 認證：") < bodies.index("待使用者：daily 排程")
    assert (
        "期間沒能留言的異常：`daily_no_end`、`news_no_log`、`news_llm_pending`"
        in bodies
    )


def test_a_comment_refused_for_its_credentials_holds_back_the_rest(wd):
    # The repository read passed, the comment got 401: the token expired between.
    _anomaly_fixtures(wd)
    (wd.fake / "gh_mode_issue").write_text("401", encoding="utf-8")
    wd.run()
    assert len(wd.text("gh_calls.log").splitlines()) == 1
    events = wd.events()
    assert events.count("gh_auth_failed") == 1
    assert events.count("anomaly_not_commented") == 3
    assert "anomaly_comment_failed" not in events


def test_a_gh_network_error_is_not_taken_for_an_auth_error(wd):
    (wd.fake / "gh_mode").write_text("down", encoding="utf-8")
    wd.run()
    assert wd.events() == ["gh_probe_failed", "schedules_ok"]
    _anomaly_fixtures(wd)
    wd.run(now=NIGHT + 900)
    events = wd.events()
    assert "gh_auth_failed" not in events
    assert events.count("anomaly_comment_failed") == 3


def test_a_dry_run_makes_no_gh_call(wd):
    (wd.fake / "gh_mode").write_text("401", encoding="utf-8")
    _anomaly_fixtures(wd)
    wd.run("--dry-run")
    assert wd.text("gh_api.log") == wd.text("gh_calls.log") == ""
    assert "gh_auth_failed" not in wd.events()


def test_an_expired_claude_token_leaves_the_notes_pending_and_comments_on_1(
    wd, monkeypatch
):
    # AC-1 end to end: candidate_notes with the fake claude answering as an
    # expired CLAUDE_CODE_OAUTH_TOKEN does, then the watchdog on that database.
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.db import Base, enable_sqlite_foreign_keys
    from app.models import CandidateLlmNote
    from test_candidate_notes import FAKE_CLI, RUN_DATE, T, _candidates
    from worker import news_llm, pipeline
    from worker.candidate_notes import BATCH_SIZE, run_candidate_notes

    monkeypatch.setenv(news_llm.CLI_ENV, json.dumps([sys.executable, str(FAKE_CLI)]))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(wd.root / "fake_claude.jsonl"))
    monkeypatch.setenv("FAKE_CLAUDE_MODES", "token_expired")
    for key in news_llm.API_KEY_ENV:
        monkeypatch.delenv(key, raising=False)
    engine = create_engine(f"sqlite:///{(wd.data / 'stock.db').as_posix()}")
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    try:
        with Session(engine, autoflush=False, expire_on_commit=False) as db:
            db.info["strategies"] = pipeline._ensure_strategies(db)
            db.commit()
            _candidates(db, BATCH_SIZE + 2)
            result = run_candidate_notes(db, T, run_date=RUN_DATE)
            notes = db.scalars(select(CandidateLlmNote)).all()
    finally:
        engine.dispose()
    assert result["status"] == "failed"
    assert result["batches"][0]["reason"] == "not_logged_in"
    assert result["skipped_batches"][0]["reason"] == "stopped_after_not_logged_in"
    assert len(notes) == BATCH_SIZE
    assert {note.llm_status for note in notes} == {"pending"}

    wd.run(now=int(time.time()))
    bodies = wd.text("gh_bodies.txt")
    assert bodies.count("待使用者：Claude Code 認證：") == 1
    assert f"candidate_notes run {result['run_id']}" in bodies


# The deployed version (#314 AC-3; #340: the image, not a checkout) -----------------

IMAGE = "stock-lab-backend:v1.1.0"
HEAD = "c" * 40


def _deploy_record(wd: Watchdog, image: str = IMAGE, head: str = HEAD) -> None:
    record = {"tag": "v1.1.0", "HEAD": head, "image": image}
    (wd.logs / "deploy.json").write_text(json.dumps(record), encoding="utf-8")


def _in_image(image: str = IMAGE, head: str = HEAD) -> dict[str, str]:
    """The scheduler container's environment (backend/Dockerfile ENV)."""
    return {"STOCK_IMAGE_TAG": image, "STOCK_GIT_HEAD": head}


def test_the_image_the_watchdog_runs_in_is_checked_against_the_deploy_record(wd):
    # Never deployed: nothing to compare with.
    result = wd.run("--dry-run", env=_in_image())
    assert "invariant deploy_image skip reason=no_deploy_record" in result.stdout
    assert "將在 #1 留言" not in result.stdout
    _deploy_record(wd)
    result = wd.run(env=_in_image())
    assert (
        f"invariant deploy_image ok image={IMAGE} recorded={IMAGE}"
        f" head={HEAD} recorded_head={HEAD} tag=v1.1.0" in result.stdout
    )
    assert wd.events()[-1] == "schedules_ok" and wd.text("gh_calls.log") == ""
    # Rebuilt outside deploy.sh (`docker compose up -d --build`): compose's default tag.
    rebuilt = "stock-lab-backend:latest"
    dry = wd.run("--dry-run", env=_in_image(rebuilt, ""))
    assert (
        f"invariant deploy_image violation image={rebuilt} recorded={IMAGE}"
        f" head=unknown recorded_head={HEAD} tag=v1.1.0" in dry.stdout
    )
    assert f"待使用者：部署不變量：scheduler 跑的 image 是 `{rebuilt}`" in dry.stdout
    wd.run(env=_in_image(rebuilt, ""))
    wd.run(env=_in_image(rebuilt, ""))
    assert wd.text("gh_calls.log").count("issue comment 1") == 1


def test_the_same_tag_built_from_another_commit_is_a_violation(wd):
    _deploy_record(wd)
    dry = wd.run("--dry-run", env=_in_image(head="d" * 40))
    assert "invariant deploy_image violation" in dry.stdout
    assert f"recorded_head={HEAD}" in dry.stdout


def test_outside_an_image_or_with_an_unreadable_record_it_is_commented(wd):
    # The checkout's git is never read (#340, PR #365 review suggestion 2).
    _deploy_record(wd)
    dry = wd.run("--dry-run", env={"STOCK_IMAGE_TAG": "", "STOCK_GIT_HEAD": ""})
    assert (
        f"invariant deploy_image violation image=unknown recorded={IMAGE}" in dry.stdout
    )
    (wd.logs / "deploy.json").write_text("{not json", encoding="utf-8")
    dry = wd.run("--dry-run", env=_in_image())
    assert "invariant deploy_image violation reason=unreadable_record" in dry.stdout
    assert "待使用者：部署不變量：部署記錄" in dry.stdout and "讀不懂" in dry.stdout
    # #314's record (a checkout and its HEAD, no image) cannot be checked either.
    record = {"tag": "v1.1.0", "HEAD": HEAD, "checkout": "/release"}
    (wd.logs / "deploy.json").write_text(json.dumps(record), encoding="utf-8")
    dry = wd.run("--dry-run", env=_in_image())
    assert "invariant deploy_image violation reason=unreadable_record" in dry.stdout


# --- daily data check (Issue #390) -------------------------------------------


def _checked_day_db(path: Path, refetch: str | None) -> None:
    """A full-schema database whose 2026-10-19 daily succeeded, with the 23:00
    refetch step ``refetch`` (None: no refetch)."""

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.migrations import upgrade_database
    from app.models import ScheduleRun, ScheduleRunStep

    engine = create_engine(f"sqlite:///{path.as_posix()}")
    try:
        upgrade_database(engine)
        with Session(engine) as db:
            db.add(
                ScheduleRun(
                    job="daily",
                    target_date=datetime(2026, 10, 19).date(),
                    status="success",
                    summary_json={"steps": {"collect": "success"}},
                )
            )
            if refetch is not None:
                skipped = ScheduleRun(
                    job="daily",
                    target_date=datetime(2026, 10, 19).date(),
                    status="skipped",
                    summary_json={"reason": "already_complete", "related_run_id": 1},
                )
                db.add(skipped)
                db.flush()
                db.add(
                    ScheduleRunStep(
                        schedule_run_id=skipped.id,
                        step="institutional_refetch",
                        status=refetch,
                        error="TPEx: official endpoint retry exhausted"
                        if refetch != "running"
                        else None,
                    )
                )
            db.commit()
    finally:
        engine.dispose()


def _set_refetch(path: Path, status: str) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE schedule_run_steps SET status=?", (status,))
    conn.close()


def _data_check_events(wd: Watchdog) -> list[str]:
    return [event for event in wd.events() if event.startswith("data_check")]


def test_a_clean_trading_day_is_checked_once(wd):
    _daily_log_done(wd)
    _checked_day_db(wd.data / "stock.db", "success")
    wd.run()
    wd.run(now=NIGHT + 15 * 60)
    assert _data_check_events(wd) == ["data_check_done"]
    assert " data_check_done date=2026-10-19 findings=0 " in wd.log()
    assert wd.text("gh_calls.log") == ""


def test_a_failed_refetch_is_commented_once_with_its_details(wd):
    _daily_log_done(wd)
    _checked_day_db(wd.data / "stock.db", "partial")
    wd.run()
    wd.run(now=NIGHT + 15 * 60)
    assert _data_check_events(wd) == ["data_check_done"]
    assert len(wd.text("gh_calls.log").splitlines()) == 1
    body = wd.text("gh_bodies.txt")
    assert (
        "當日資料核對：交易日 2026-10-19 寫進 DB 的資料與官方 raw 有 1 筆不一致" in body
    )
    assert "- 法人重抓失敗或沒有執行（`institutional_refetch`）：1 筆" in body
    assert (
        "| `institutional_refetch` | - | - | 2026-10-19 | `status` | success | partial |"
        in body
    )
    assert "TPEx: official endpoint retry exhausted" in body


def test_a_running_refetch_is_checked_after_it_ends(wd):
    _daily_log_done(wd)
    db = wd.data / "stock.db"
    _checked_day_db(db, "running")
    wd.run()
    assert _data_check_events(wd) == ["data_check_pending"]
    _set_refetch(db, "success")
    wd.run(now=NIGHT + 15 * 60)
    wd.run(now=NIGHT + 30 * 60)
    assert _data_check_events(wd) == ["data_check_pending", "data_check_done"]


def test_a_dry_run_does_not_settle_the_day(wd):
    _daily_log_done(wd)
    _checked_day_db(wd.data / "stock.db", "failed")
    dry = wd.run("--dry-run")
    assert "將在 #1 留言" in dry.stdout and "`institutional_refetch`" in dry.stdout
    wd.run(now=NIGHT + 15 * 60)
    assert _data_check_events(wd) == ["data_check_done", "data_check_done"]
    assert len(wd.text("gh_calls.log").splitlines()) == 1


def test_the_data_check_waits_for_23_10_and_a_successful_daily(wd):
    _daily_log_done(wd)
    db = wd.data / "stock.db"
    _checked_day_db(db, "failed")
    wd.run(now=NIGHT - 30 * 60)  # 22:45: before the 23:00 refetch
    assert _data_check_events(wd) == []
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE schedule_runs SET status='partial' WHERE status='success'")
    conn.close()
    wd.run()
    assert _data_check_events(wd) == []


# #408 review: a day is settled only by a posted comment, never silently.

LAST_RUN = NIGHT + 30 * 60  # 23:45 Taipei, the night's last run
AFTER_MIDNIGHT = NIGHT + 60 * 60  # Tuesday 2026-10-20 00:15 Taipei

FAKE_PYTHON = r"""#!/usr/bin/env bash
# The real Python, except data-check as FAKE_HELPER says.
prev=""
for a in "$@"; do
  [ "$prev" = --scratch ] && mkdir -p "$a/data-check-fake"
  prev="$a"
done
case " $* " in
  *" data-check "*)
    case "$FAKE_HELPER" in
      hang) exec sleep 30 ;;
      fail) echo "boom from the helper" >&2; exit 3 ;;
      garbage) echo "garbage"; exit 0 ;;
    esac ;;
esac
exec "$REAL_PYTHON" "$@"
"""


def _fake_python(wd: Watchdog) -> str:
    path = wd.bin / "fakepy"
    path.write_text(FAKE_PYTHON, encoding="utf-8", newline="\n")
    path.chmod(0o755)
    return path.as_posix()


def _helper_as(wd: Watchdog, mode: str, now: int) -> subprocess.CompletedProcess[str]:
    return wd.run(
        now=now,
        python=_fake_python(wd),
        FAKE_HELPER=mode,
        REAL_PYTHON=Path(sys.executable).as_posix(),
        WATCHDOG_DATA_CHECK_TIMEOUT="3",
    )


def test_a_failed_comment_leaves_the_day_to_the_next_run(wd):
    _daily_log_done(wd)
    _checked_day_db(wd.data / "stock.db", "partial")
    (wd.fake / "gh_fail").write_text("", encoding="utf-8")
    wd.run()
    assert "anomaly_comment_failed" in wd.events()
    assert _data_check_events(wd) == []
    (wd.fake / "gh_fail").unlink()
    wd.run(now=NIGHT + 15 * 60)
    assert _data_check_events(wd) == ["data_check_done"]
    assert "`institutional_refetch`" in wd.text("gh_bodies.txt")
    assert len(wd.text("gh_calls.log").splitlines()) == 2


@pytest.mark.parametrize(
    ("mode", "event", "reason"),
    [
        ("hang", "data_check_failed date=2026-10-19 exit=124", "逾時（3 秒）"),
        ("fail", "data_check_failed date=2026-10-19 exit=3", "boom from the helper"),
        ("garbage", "data_check_failed date=2026-10-19 ", "輸出無法判讀（garbage）"),
    ],
)
def test_a_check_that_cannot_finish_is_retried_then_commented_at_2345(
    wd, mode, event, reason
):
    _daily_log_done(wd)
    _checked_day_db(wd.data / "stock.db", "success")
    _helper_as(wd, mode, NIGHT)
    assert event in wd.log()
    assert wd.text("gh_calls.log") == ""
    _helper_as(wd, mode, LAST_RUN)
    body = wd.text("gh_bodies.txt")
    assert "當日資料核對：交易日 2026-10-19 沒有核對完，原因：" in body
    assert reason in body
    # Settled by the comment: no further check, no second comment.
    _helper_as(wd, mode, AFTER_MIDNIGHT)
    assert len(wd.text("gh_calls.log").splitlines()) == 1
    assert _data_check_events(wd) == ["data_check_failed", "data_check_failed"]
    # The killed helper's temporary directory went with the work directory.
    assert not list(wd.logs.glob(".watchdog.*"))


def test_a_refetch_running_all_night_is_commented_at_2345(wd):
    _daily_log_done(wd)
    _checked_day_db(wd.data / "stock.db", "running")
    wd.run()
    wd.run(now=LAST_RUN)
    assert _data_check_events(wd) == ["data_check_pending", "data_check_pending"]
    assert "原因：法人重抓一直是 running" in wd.text("gh_bodies.txt")


def test_a_day_the_night_did_not_check_is_checked_after_midnight(wd):
    _daily_log_done(wd)
    _checked_day_db(wd.data / "stock.db", "partial")
    wd.run(now=AFTER_MIDNIGHT)
    assert _data_check_events(wd) == ["data_check_done"]
    assert "交易日 2026-10-19 寫進 DB 的資料與官方 raw 有 1 筆不一致" in wd.text(
        "gh_bodies.txt"
    )


def test_a_day_the_night_left_failing_is_commented_on_its_one_catch_up(wd):
    _daily_log_done(wd)
    _checked_day_db(wd.data / "stock.db", "success")
    _helper_as(wd, "fail", AFTER_MIDNIGHT)
    assert "交易日 2026-10-19 沒有核對完" in wd.text("gh_bodies.txt")


# --- maintenance mode (#468) ------------------------------------------------------------


def _maintenance_on(
    wd: Watchdog, since: int, reason: str = "技術回測 2025-11～2026-11"
):
    """What ``worker.cli maintenance on`` writes (the format in backend/worker/job.py)."""

    path = wd.data / "locks" / "maintenance"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"since_epoch": since, "reason": reason}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _maintenance_daily_log(wd: Watchdog, day: str = "20261019") -> None:
    """The 21:30 and 23:00 dailies of a day in maintenance: skipped, no run row."""

    skip = (
        "===== {at} start job=daily trigger=scheduler date=default\n"
        "--- version image=stock-lab-backend:v1.3.0 head=abc\n"
        "===== skipped reason=maintenance (since=2026-10-19T21:00:00+08:00, reason=回測)\n"
        "===== {at} end exit=0 seconds=0\n"
    )
    (wd.logs / f"daily-{day}.log").write_text(
        skip.format(at="2026-10-19T21:30:00+08:00")
        + skip.format(at="2026-10-19T23:00:00+08:00"),
        encoding="utf-8",
    )


def test_a_daily_skipped_for_maintenance_is_not_reported(wd):
    """AC-2: no run row for the day, as a worker that could not start; not an anomaly."""

    _maintenance_daily_log(wd)
    _daily_db(wd.data / "stock.db", [])
    marker = _maintenance_on(wd, NIGHT - 2 * 3600)
    news = wd.logs / "news-20261019.log"
    news.write_text("===== skipped reason=maintenance\n", encoding="utf-8")
    os.utime(news, (NIGHT - 3600, NIGHT - 3600))
    wd.run()  # 23:15
    wd.run(now=LAST_RUN)  # 23:45
    marker.unlink()  # off after midnight: the day before is judged at 00:30
    wd.run(now=AT_0045)
    assert wd.text("gh_calls.log") == ""
    events = wd.events()
    assert not [event for event in events if event.startswith("anomaly")]
    assert events.count("maintenance_on") == 2
    assert events.count("daily_maintenance") == 3
    assert " maintenance_on since=2026-10-19T13:15:00Z hours=2 " in wd.log()


def test_a_day_with_no_run_row_and_no_maintenance_skip_is_still_reported(wd):
    (wd.logs / "daily-20261019.log").write_text(
        "===== s start\n===== e end exit=1 seconds=1\n", encoding="utf-8"
    )
    _daily_db(wd.data / "stock.db", [])
    _maintenance_on(wd, NIGHT - 3600)  # turned on after a daily that never wrote a row
    wd.run()
    assert "沒有這一天的 run（worker 未能啟動）" in wd.text("gh_bodies.txt")


def test_maintenance_on_past_12_hours_is_commented_once_a_day(wd):
    """AC-2: a maintenance mode left on is reported, so it is not forgotten."""

    _maintenance_on(wd, NIGHT - 11 * 3600 - 59 * 60)
    wd.run(now=NIGHT)  # 11 h 59 min: not yet
    assert wd.text("gh_calls.log") == ""
    wd.run(now=NIGHT + 2 * 60)  # 12 h 1 min
    wd.run(now=LAST_RUN)
    assert len(wd.text("gh_calls.log").splitlines()) == 1
    body = wd.text("gh_bodies.txt")
    assert (
        "維護模式：自 2026-10-19T03:16:00Z 開啟已 12 小時（上限 12 小時；原因：技術回測 2025-11～2026-11）"
        in body
    )
    assert "maintenance off" in body
    assert " anomaly_already_commented key=maintenance_long " in wd.log()


def test_an_unreadable_marker_is_dated_by_its_file(wd):
    path = _maintenance_on(wd, NIGHT)
    path.write_text("{broken", encoding="utf-8")
    os.utime(path, (NIGHT - 13 * 3600, NIGHT - 13 * 3600))
    result = wd.run("--dry-run")
    assert "開啟已 13 小時（上限 12 小時；原因：unreadable）" in result.stdout
    # Without Python the marker is not read, only dated.
    result = wd.run("--dry-run", python=(wd.root / "no-python.exe").as_posix())
    assert "開啟已 13 小時（上限 12 小時；原因：unknown）" in result.stdout


def test_a_maintenance_mode_serve_expired_is_commented_once(wd):
    """#468 AC-5: serve removed the marker of a holder that stopped beating."""

    expired_at = datetime.fromtimestamp(NIGHT - 30 * 60, tz=timezone.utc).astimezone(
        timezone(timedelta(hours=8))
    )
    (wd.logs / "maintenance.log").write_text(
        json.dumps(
            {"at": "2026-10-19T10:00:00+08:00", "event": "held", "owner": "backtest"}
        )
        + "\n"
        + json.dumps(
            {
                "at": expired_at.isoformat(timespec="seconds"),
                "event": "expired",
                "owner": "backtest",
                "pid": 4242,
                "reason": "backtest --start-date 2025-11-04",
                "heartbeat_age_minutes": 10.5,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    wd.run()
    wd.run(now=LAST_RUN)
    assert len(wd.text("gh_calls.log").splitlines()) == 1
    body = wd.text("gh_bodies.txt")
    assert (
        "維護模式：`backtest`（pid 4242，`backtest --start-date 2025-11-04`）的心跳停了 10.5 分鐘"
        in body
    )
    assert "serve 在 2026-10-19T14:45:00Z 自動解除維護模式" in body
    # A day later the record is out of the window: nothing more.
    wd.run(now=NIGHT + 86400 + 3600)
    assert len(wd.text("gh_calls.log").splitlines()) == 1
