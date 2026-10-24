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
    assert wd.events() == ["news_llm_check_failed", "invariants_check_failed"]
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


def test_daily_result_waits_until_22_and_for_a_running_trigger(wd):
    _daily_log_done(wd)
    # 18:30 partial, the 21:30 trigger still running.
    _daily_db(wd.data / "stock.db", [("partial", {}), ("running", {})])
    wd.run(now=NIGHT - 20 * 60)  # 21:40: not judged yet
    wd.run()  # 22:00: the 21:30 run is still running
    assert wd.text("gh_calls.log") == ""
    # A run still marked running past the 2.5-hour task limit has died.
    wd.run(now=NIGHT + 100 * 60)  # 23:40, 2 h 40 min after it started
    assert "daily 結果是 `failed`" in wd.text("gh_bodies.txt")


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
    wd.run(now=NIGHT - 24 * 3600)  # Sunday 22:00
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
        _news_end("10-18T20:00:30", "0")
        + "\n"
        + _news_end("10-18T22:00:30", "1")
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
