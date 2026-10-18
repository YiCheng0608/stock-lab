"""tools/ops/watchdog.sh with a fake gh executable (Issue #171).

Each test builds a data directory with job logs and an optional stock.db,
prepends a bin directory holding a fake ``gh`` script to PATH and runs the
real watchdog through bash. The fake records every call; the watchdog's clock
is pinned with WATCHDOG_NOW. Nothing touches GitHub or the real data
directory.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "ops" / "watchdog.sh"
# NIGHT is Monday 2026-10-19 22:00 Taipei.
NIGHT = int(datetime(2026, 10, 19, 14, 0, tzinfo=timezone.utc).timestamp())


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
pytestmark = pytest.mark.skipif(BASH is None, reason="bash is required")

FAKE_GH = r"""#!/usr/bin/env bash
d="$FAKE_DIR"
printf '%s\n' "$*" >>"$d/gh_calls.log"
while [ $# -gt 0 ]; do
  [ "$1" = --body-file ] && { cat "$2"; echo '-----'; } >>"$d/gh_bodies.txt"
  shift
done
echo "https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-1"
"""


class Watchdog:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.bin = root / "bin"
        self.fake = root / "fake"
        self.data = root / "data"
        self.logs = self.data / "logs"
        for directory in (self.bin, self.fake, self.logs):
            directory.mkdir(parents=True)
        path = self.bin / "gh"
        path.write_text(FAKE_GH, encoding="utf-8", newline="\n")
        path.chmod(0o755)

    def run(
        self, *args: str, now: int = NIGHT, python: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env.update(
            PATH=str(self.bin) + os.pathsep + env.get("PATH", ""),
            FAKE_DIR=self.fake.as_posix(),
            STOCK_DATA_DIR=self.data.as_posix(),
            STOCK_PYTHON=python or Path(sys.executable).as_posix(),
            WATCHDOG_NOW=str(now),
        )
        result = subprocess.run(
            [BASH, SCRIPT.as_posix(), *args],
            env=env,
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


def _news_llm_db(path: Path, batches: list[list[str]]) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE ingestion_runs (id INTEGER PRIMARY KEY, run_type TEXT, metadata_json TEXT)"
        )
        conn.execute(
            "INSERT INTO ingestion_runs (run_type, metadata_json) VALUES ('news', '{}')"
        )
        for statuses in batches:
            metadata = {
                "batches": [
                    {"batch": n, "status": s} for n, s in enumerate(statuses, start=1)
                ]
            }
            conn.execute(
                "INSERT INTO ingestion_runs (run_type, metadata_json) VALUES ('news_llm', ?)",
                (json.dumps(metadata),),
            )
    conn.close()


def _anomaly_fixtures(wd: Watchdog) -> None:
    (wd.logs / "daily-20261016.log").write_text(
        "===== x start\n===== y end exit=0 seconds=1\n", encoding="utf-8"
    )
    (wd.logs / "daily-20261019.log").write_text(
        "===== 2026-10-19T18:30:00+08:00 start job=daily\n", encoding="utf-8"
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
        "待使用者：daily 排程：台北 20261019 已過 21:30" in result.stdout
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


def test_lock_prevents_reentry_and_stale_lock_is_removed(wd):
    lock = wd.logs / "watchdog.lock"
    lock.mkdir()
    wd.run()
    assert wd.events() == ["locked"]
    old = time.time() - 31 * 60
    os.utime(lock, (old, old))
    wd.run()
    assert wd.events()[1:] == ["lock_stale_removed", "schedules_ok"]
    assert not lock.exists()


def test_unreadable_database_is_logged_and_not_reported_ok(wd):
    (wd.data / "stock.db").write_bytes(b"not a database")
    wd.run()
    assert wd.events() == ["news_llm_check_failed"]
    assert wd.text("gh_calls.log") == ""
