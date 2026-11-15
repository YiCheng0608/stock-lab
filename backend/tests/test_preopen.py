"""The pre-open check of the today list (backend/worker/preopen.py, app/preopen_news.py, #755).

The list is Friday T's (2026-09-04), computed at 21:30:00 Taipei; the check is Monday's
08:20. The window (#755 decision 6888598143, A): collected after the list's computed_at
and published from the list date's 00:00 Taipei up to the check. The relation is the
stock page's (``symbols_json``). The runs take fcntl locks: Linux only, like worker.job.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sqlite3
import sys
import time
from contextlib import closing
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import migration_revisions, migrations
from app.api import _news_symbol_filter
from app.candidate_view import candidate_list
from app.db import Base, enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import (
    CandidateRun,
    DailyCandidate,
    Instrument,
    NewsItem,
    NewsLlmResult,
    PreopenNewsCheck,
    RawPayload,
    TradingCalendarDay,
)
from app.candidate_runs import read_run
from app.domain import CANDIDATE_SCORE_READ_VERSIONS
from app.preopen_news import check_rows, list_view, overnight_news, replace_check
from test_candidates import NEWS_PROMPT_VERSION, T, signal, stock
from worker import job, pipeline, preopen
from worker.candidates import compute_daily_candidates

ON_LINUX = sys.platform.startswith("linux")
linux_only = pytest.mark.skipif(not ON_LINUX, reason="fcntl lock: Linux only (#333)")
MONDAY = date(2026, 9, 7)
# 21:30:00 Taipei on T, UTC-naive as stored.
COMPUTED = datetime(2026, 9, 4, 13, 30)
# Monday 08:20 Taipei.
CHECKED = datetime(2026, 9, 7, 0, 20)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        session.info["strategies"] = pipeline._ensure_strategies(session)
        session.commit()
        yield session
    engine.dispose()


def _list(db, symbols=("1101", "2330")):
    instruments = [stock(db, symbol) for symbol in symbols]
    for instrument in instruments:
        signal(db, instrument)
    db.commit()
    compute_daily_candidates(db, T)
    run = db.scalar(select(CandidateRun).where(CandidateRun.trading_date == T))
    run.computed_at = COMPUTED
    # Stored as the version before the current one, so that a test can add the
    # date's run of the current version: the one the page reads then (a recomputed
    # list; one run per date and version).
    _set_version(db, run, CANDIDATE_SCORE_READ_VERSIONS[1])
    db.commit()
    return run, instruments


def _set_version(db, run, version):
    run.score_version = version
    for candidate in db.scalars(
        select(DailyCandidate).where(DailyCandidate.candidate_run_id == run.id)
    ):
        candidate.score_version = version
    db.flush()


def _recomputed(db, run, computed_at, *, move=False):
    """The date's run of the current version; MOVE gives it the old run's candidates."""

    newer = CandidateRun(
        trading_date=T,
        score_version=CANDIDATE_SCORE_READ_VERSIONS[0],
        computed_at=computed_at,
    )
    db.add(newer)
    db.flush()
    if move:
        for candidate in db.scalars(
            select(DailyCandidate).where(DailyCandidate.candidate_run_id == run.id)
        ):
            candidate.candidate_run_id = newer.id
            candidate.score_version = newer.score_version
    db.commit()
    assert read_run(db, T).id == newer.id
    return newer


def _news(
    db,
    symbols,
    *,
    published=None,
    collected,
    direction="negative",
    event_date=None,
    consistency="verified",
    title="標題",
    ai_symbols=None,
    unsupported=None,
):
    item = NewsItem(
        canonical_key=f"news-{len(db.scalars(select(NewsItem)).all())}",
        source_name="鉅亨",
        source_url="https://example.com/news",
        title=title,
        published_at=None if event_date else published,
        event_date=event_date,
        display_time=datetime.combine(event_date, datetime.min.time())
        if event_date
        else published,
        time_basis="event_date" if event_date else "published",
        time_precision="date" if event_date else "datetime",
        time_consistency=consistency,
        collected_at=collected,
        symbols_json=list(symbols),
    )
    db.add(item)
    db.flush()
    if direction is not None:
        db.add(
            NewsLlmResult(
                news_item_id=item.id,
                prompt_version=NEWS_PROMPT_VERSION,
                llm_input_hash="x" * 64,
                llm_status="done",
                ai_impact_direction=direction,
                ai_unsupported=unsupported,
                ai_symbol_candidates_json=ai_symbols or [],
            )
        )
        db.flush()
    return item


def _taipei(year, month, day, hour, minute, second=0):
    """A Taipei wall time as the UTC-naive instant news rows store."""

    return datetime(year, month, day, hour, minute, second) - timedelta(hours=8)


def _ids(found, instrument):
    return [item.id for item, _ in found[instrument.id]]


# --- the window --------------------------------------------------------------------


def test_the_window_starts_at_the_lists_computed_at_and_ends_at_the_check(db):
    run, (cement, _) = _list(db)
    late = _taipei(2026, 9, 4, 22, 0)
    counted = {
        # Collected 1 second after computed_at: daily had not seen it.
        "collected_2130_01": _news(
            db,
            ["1101"],
            published=_taipei(2026, 9, 4, 21, 0),
            collected=COMPUTED + timedelta(seconds=1),
        ),
        # Published at 20:30 but only collected by the 22:00 news run (the gap A closes).
        "published_2030_collected_2200": _news(
            db, ["1101"], published=_taipei(2026, 9, 4, 20, 30), collected=late
        ),
        # The list date's 00:00 Taipei is in, as is the check's own instant.
        "published_0000": _news(
            db, ["1101"], published=_taipei(2026, 9, 4, 0, 0), collected=late
        ),
        "published_at_check": _news(db, ["1101"], published=CHECKED, collected=CHECKED),
        # A date-only item of Monday counts by its event date.
        "event_monday": _news(
            db, ["1101"], event_date=MONDAY, collected=_taipei(2026, 9, 7, 7, 0)
        ),
    }
    not_counted = {
        # Collected at computed_at or before (21:29): daily had it.
        "collected_2130_00": _news(
            db, ["1101"], published=_taipei(2026, 9, 4, 21, 0), collected=COMPUTED
        ),
        "collected_2129": _news(
            db,
            ["1101"],
            published=_taipei(2026, 9, 4, 21, 0),
            collected=_taipei(2026, 9, 4, 21, 29),
        ),
        # Published the day before the list date, collected late.
        "published_thursday": _news(
            db, ["1101"], published=_taipei(2026, 9, 3, 23, 59), collected=late
        ),
        # After the check: published, or collected.
        "published_0821": _news(
            db,
            ["1101"],
            published=CHECKED + timedelta(minutes=1),
            collected=CHECKED + timedelta(minutes=1),
        ),
        "collected_0821": _news(
            db,
            ["1101"],
            published=_taipei(2026, 9, 7, 8, 0),
            collected=CHECKED + timedelta(minutes=1),
        ),
        "event_thursday": _news(
            db, ["1101"], event_date=date(2026, 9, 3), collected=late
        ),
        "event_tuesday": _news(
            db, ["1101"], event_date=date(2026, 9, 8), collected=late
        ),
        # A time conflict is not on the stock page either.
        "conflict": _news(
            db,
            ["1101"],
            published=_taipei(2026, 9, 4, 23, 0),
            collected=late,
            consistency="conflict",
        ),
    }
    db.commit()
    found = _ids(overnight_news(db, run, CHECKED), cement)
    assert sorted(found) == sorted(item.id for item in counted.values())
    assert not set(found) & {item.id for item in not_counted.values()}


def test_a_list_computed_after_the_check_has_no_window(db):
    run, (cement, _) = _list(db)
    _news(db, ["1101"], published=_taipei(2026, 9, 7, 7, 0), collected=CHECKED)
    run.computed_at = CHECKED
    db.commit()
    assert overnight_news(db, run, CHECKED)[cement.id] == []


# --- the relation ------------------------------------------------------------------


def test_the_relation_is_the_stock_pages_rule_relation_only(db):
    run, (cement, chips) = _list(db)
    late = _taipei(2026, 9, 4, 23, 0)
    bare = _news(db, ["1101"], published=late, collected=late)
    exchange = _news(db, ["TWSE:1101"], published=late, collected=late)
    both = _news(db, ["TWSE:1101", "TWSE:2330"], published=late, collected=late)
    # Another exchange's code and a longer code are other stocks.
    _news(db, ["TPEx:1101"], published=late, collected=late)
    _news(db, ["11011"], published=late, collected=late)
    # An AI symbol candidate alone links nothing (the stock page does not list it).
    _news(
        db,
        [],
        published=late,
        collected=late,
        ai_symbols=[{"symbol": "TWSE:1101", "reason": "提到"}],
    )
    db.commit()
    found = overnight_news(db, run, CHECKED)
    assert _ids(found, cement) == [bare.id, exchange.id, both.id]
    assert _ids(found, chips) == [both.id]
    # The same items the stock page's news list selects for each stock.
    for instrument in (cement, chips):
        page = set(
            db.scalars(
                select(NewsItem.id).where(
                    _news_symbol_filter(db.get(Instrument, instrument.id)),
                    NewsItem.collected_at > COMPUTED,
                )
            )
        )
        assert set(_ids(found, instrument)) == page


# --- the rows ----------------------------------------------------------------------


def test_one_row_per_candidate_with_the_directions_and_the_unjudged(db):
    run, (cement, chips) = _list(db)
    late = _taipei(2026, 9, 4, 23, 0)
    negative = _news(db, ["1101"], published=late, collected=late)
    positive = _news(db, ["1101"], published=late, direction="positive", collected=late)
    unsupported = _news(
        db,
        ["1101"],
        published=late,
        direction="positive",
        unsupported=True,
        collected=late,
    )
    pending = _news(db, ["1101"], published=late, direction=None, collected=late)
    db.commit()
    rows = {row.instrument_id: row for row in check_rows(db, run, CHECKED)}
    assert set(rows) == {cement.id, chips.id}
    row = rows[cement.id]
    assert (row.list_date, row.candidate_run_id) == (T, run.id)
    assert (row.window_start, row.checked_at) == (COMPUTED, CHECKED)
    assert (row.news_count, row.positive, row.negative, row.mixed) == (4, 1, 1, 0)
    assert (row.unknown, row.unscored) == (1, 1)
    # Not judged yet is listed too, with no direction.
    assert row.news_json == [
        {"news_id": negative.id, "direction": "negative"},
        {"news_id": positive.id, "direction": "positive"},
        {"news_id": unsupported.id, "direction": "unknown"},
        {"news_id": pending.id, "direction": None},
    ]
    # A candidate without news still has its row.
    assert rows[chips.id].news_count == 0 and rows[chips.id].news_json == []


def test_the_list_reads_not_checked_until_its_own_run_is_checked(db):
    run, (cement, _) = _list(db)
    late = _taipei(2026, 9, 4, 23, 0)
    item = _news(db, ["1101"], published=late, direction=None, collected=late)
    db.commit()
    listing = candidate_list(db, T)
    assert listing["preopen_check"]["status"] == "not_checked"
    assert listing["preopen_check"]["definition"] == "名單產生之後才收到的新聞"
    assert all(entry["preopen_news"] is None for entry in listing["items"])

    replace_check(db, run, check_rows(db, run, CHECKED))
    db.commit()
    listing = candidate_list(db, T)
    check = listing["preopen_check"]
    assert check["status"] == "checked"
    assert check["checked_at"] == "2026-09-07T00:20:00+00:00"
    assert check["window_start"] == "2026-09-04T13:30:00+00:00"
    assert check["instruments_with_news"] == 1
    by_symbol = {entry["instrument"]["symbol"]: entry for entry in listing["items"]}
    assert by_symbol["1101"]["preopen_news"]["count"] == 1
    assert by_symbol["1101"]["preopen_news"]["items"] == [
        {
            "id": str(item.id),
            "title": "標題",
            "display_time": "2026-09-04T15:00:00+00:00",
            "event_date": None,
            "time_precision": "datetime",
            "source_name": "鉅亨",
            "source_url": "https://example.com/news",
            "direction": None,
        }
    ]
    assert by_symbol["2330"]["preopen_news"]["count"] == 0
    # A later judgment does not change the stored direction.
    db.add(
        NewsLlmResult(
            news_item_id=item.id,
            prompt_version=NEWS_PROMPT_VERSION,
            llm_input_hash="y" * 64,
            llm_status="done",
            ai_impact_direction="negative",
        )
    )
    db.commit()
    assert list_view(db, run)[1][cement.id]["items"][0]["direction"] is None

    # The list recomputed after the check: the check is not this list's.
    _recomputed(db, run, CHECKED)
    assert candidate_list(db, T)["preopen_check"]["status"] == "not_checked"


# --- the job -----------------------------------------------------------------------


def _closed(db, day: date) -> None:
    raw = RawPayload(
        source="twse",
        endpoint="fixture-holiday-schedule",
        sha256=f"{day:%Y%m%d}".ljust(64, "0"),
        data_as_of=day.isoformat(),
    )
    db.add(raw)
    db.flush()
    db.add(
        TradingCalendarDay(
            exchange="TWSE",
            calendar_date=day,
            year=day.year,
            kind="closed",
            name="放假",
            description="",
            source="twse_holiday_schedule",
            collected_at=datetime(2026, 1, 1),
            raw_payload_id=raw.id,
        )
    )
    db.commit()


@pytest.fixture
def run_env(tmp_path, monkeypatch, db):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    monkeypatch.setenv("STOCK_DATA_DIR", str(data))

    @contextlib.contextmanager
    def session():
        yield db

    monkeypatch.setattr(preopen, "_session", session)
    run, instruments = _list(db)
    late = _taipei(2026, 9, 4, 23, 0)
    _news(db, ["1101"], published=late, collected=late)
    db.commit()
    yield argparse.Namespace(data=data, logs=data / "logs", run=run, db=db)


def _args(*argv):
    parser = argparse.ArgumentParser()
    preopen.add_arguments(parser)
    return parser.parse_args(list(argv))


def _check(env, *extra, day=MONDAY, at="08:20", trigger="scheduler", wait=None):
    args = _args(
        "--now",
        f"{day.isoformat()}T{at}",
        "--trigger",
        trigger,
        "--log-dir",
        str(env.logs),
        *extra,
    )
    return preopen._Run(args, wait=wait or (lambda _path: (False, 0.0))).run()


def _log(env, day=MONDAY) -> str:
    return preopen.log_path(env.logs, day).read_text(encoding="utf-8")


def _rows(db):
    return db.scalars(select(PreopenNewsCheck).order_by(PreopenNewsCheck.rank)).all()


@linux_only
def test_a_trading_day_checks_once_and_a_rerun_keeps_the_first_result(run_env):
    db = run_env.db
    assert _check(run_env) == 0
    rows = _rows(db)
    assert len(rows) == 2 and rows[0].checked_at == CHECKED
    log = _log(run_env)
    assert "--- result status=checked list_date=2026-09-04" in log
    assert "checked_at=2026-09-07T08:20:00+08:00" in log
    assert "window_start=2026-09-04T21:30:00+08:00" in log
    assert "candidates=2 with_news=1 news=1 unscored=0" in log
    assert "--- candidate rank=" in log and "TWSE:1101 news=1" in log
    assert preopen.day_done(run_env.logs, MONDAY)
    # Again (serve's catch-up, a second trigger): the first check stays.
    assert _check(run_env, at="09:00") == 0
    assert [row.checked_at for row in _rows(db)] == [CHECKED, CHECKED]
    assert "--- result status=skipped reason=already_checked" in _log(run_env)


@linux_only
def test_force_replaces_the_day_and_logs_the_replaced_check(run_env):
    db = run_env.db
    assert _check(run_env) == 0
    assert _check(run_env, "--force", at="09:00", trigger="manual") == 0
    assert {row.checked_at for row in _rows(db)} == {CHECKED + timedelta(minutes=40)}
    assert len(_rows(db)) == 2
    assert (
        "--- overwrite checked_at=2026-09-07T08:20:00+08:00"
        f" run_id={run_env.run.id}" in _log(run_env)
    )


@linux_only
def test_a_recomputed_list_is_checked_again(run_env):
    db = run_env.db
    assert _check(run_env) == 0
    # The list recomputed after the check (the page reads the new run).
    newer = _recomputed(db, run_env.run, CHECKED - timedelta(hours=1), move=True)
    assert newer.id != run_env.run.id
    assert _check(run_env, at="09:00") == 0
    assert {row.candidate_run_id for row in _rows(db)} == {newer.id}
    assert "--- overwrite" in _log(run_env)


@linux_only
@pytest.mark.parametrize("closed", [True, False])
def test_a_closed_day_or_a_weekend_checks_nothing(run_env, closed):
    if closed:
        _closed(run_env.db, MONDAY)
        day = MONDAY
    else:
        day = date(2026, 9, 5)  # Saturday
    assert _check(run_env, day=day) == 0
    assert _rows(run_env.db) == []
    assert "--- result status=skipped reason=non_trading_day" in _log(run_env, day)
    assert preopen.day_done(run_env.logs, day)


@linux_only
def test_the_session_before_skips_the_closed_days(run_env):
    # Tuesday after a closed Monday reads Friday's list.
    _closed(run_env.db, MONDAY)
    tuesday = date(2026, 9, 8)
    assert _check(run_env, day=tuesday) == 0
    assert "list_date=2026-09-04" in _log(run_env, tuesday)
    assert len(_rows(run_env.db)) == 2


@linux_only
@pytest.mark.parametrize("at", ["08:19", "13:30", "21:00"])
def test_a_scheduled_run_outside_0820_to_1330_checks_nothing(run_env, at):
    assert _check(run_env, at=at) == 0
    assert _rows(run_env.db) == []
    assert f"--- result status=skipped reason=too_late at={at}" in _log(run_env)
    assert not preopen.day_done(run_env.logs, MONDAY)


@linux_only
def test_a_day_without_a_list_is_no_list(run_env):
    tuesday = date(2026, 9, 8)  # wants Monday's list, never computed
    assert _check(run_env, day=tuesday) == 0
    assert "--- result status=skipped reason=no_list list_date=2026-09-07" in _log(
        run_env, tuesday
    )


@linux_only
def test_maintenance_mode_and_a_busy_lock_skip(run_env):
    marker = job.maintenance_path(run_env.data)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"since_epoch": time.time(), "reason": "x"}))
    assert _check(run_env) == 0
    assert "--- result status=skipped reason=maintenance" in _log(run_env)
    marker.unlink()
    lock = job.FileLock(job.lock_path(run_env.data, preopen.LOCK))
    assert lock.acquire()
    try:
        assert _check(run_env) == 0
    finally:
        lock.release()
    assert "--- result status=skipped reason=already_running" in _log(run_env)
    assert _rows(run_env.db) == []
    assert preopen.LOCK not in job.JOBS


@linux_only
def test_news_still_running_after_the_wait_is_checked_anyway(run_env):
    assert _check(run_env, wait=lambda _path: (True, 600.0)) == 0
    log = _log(run_env)
    assert "--- news_lock waited=600s running=yes" in log
    assert "news_running=yes" in log
    assert len(_rows(run_env.db)) == 2


@linux_only
def test_the_wait_only_probes_the_news_lock_until_it_is_released(tmp_path):
    path = tmp_path / "locks" / "news.lock"
    news = job.FileLock(path)
    assert news.acquire()
    now = [0.0]
    probes = []

    def sleep(seconds):
        probes.append(seconds)
        now[0] += seconds
        if len(probes) == 3:
            news.release()  # the news run ends

    running, waited = preopen.wait_for_news(
        path, wait_seconds=600, poll_seconds=10, sleep=sleep, clock=lambda: now[0]
    )
    assert (running, waited) == (False, 30.0)
    # Not held after the wait: the next news run takes it.
    assert job.FileLock(path).acquire()


@linux_only
def test_the_wait_gives_up_after_ten_minutes(tmp_path):
    path = tmp_path / "locks" / "news.lock"
    news = job.FileLock(path)
    assert news.acquire()
    now = [0.0]

    def sleep(seconds):
        now[0] += seconds
        # While it waits, the lock stays the news job's.
        assert not job.FileLock(path).acquire()

    try:
        running, waited = preopen.wait_for_news(path, sleep=sleep, clock=lambda: now[0])
    finally:
        news.release()
    assert running is True and waited == preopen.NEWS_WAIT_SECONDS == 600.0


def test_a_free_news_lock_is_no_wait(tmp_path):
    assert (
        preopen.wait_for_news(tmp_path / "locks" / "news.lock", sleep=pytest.fail)[0]
        is False
    )


@linux_only
def test_the_dry_run_writes_nothing(run_env, capsys):
    assert _check(run_env, "--dry-run", trigger="manual") == 0
    assert _rows(run_env.db) == []
    assert not preopen.log_path(run_env.logs, MONDAY).exists()
    assert "--- result status=checked" in capsys.readouterr().out


def test_the_command_needs_a_real_date_and_time():
    assert preopen.argument_problem(_args("--date", "2026-02-30"))
    assert preopen.argument_problem(_args("--now", "08:20"))
    assert preopen.argument_problem(_args("--date", "2026-09-07")) is None


def test_serve_reads_the_day_results_from_the_log(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    path = preopen.log_path(logs, MONDAY)
    path.write_text(
        "--- result status=skipped reason=too_late at=14:00\n", encoding="utf-8"
    )
    assert not preopen.day_done(logs, MONDAY)
    path.write_text(
        "--- result status=checked list_date=2026-09-04\n", encoding="utf-8"
    )
    assert preopen.day_done(logs, MONDAY)


# --- migration 0032 ----------------------------------------------------------------


@pytest.mark.parametrize("entry", ["alembic", "fallback"])
def test_the_upgrade_adds_the_preopen_news_check_table(tmp_path, monkeypatch, entry):
    if entry == "alembic":
        pytest.importorskip("alembic")
    path = tmp_path / f"{entry}.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    if entry == "fallback":
        monkeypatch.setattr(migrations, "ALEMBIC_CONFIG_PATH", tmp_path / "absent.ini")
    try:
        upgrade_database(engine)
    finally:
        engine.dispose()
    with closing(sqlite3.connect(path)) as connection:
        columns = {
            row[1]: bool(row[3])
            for row in connection.execute("PRAGMA table_info('preopen_news_checks')")
        }
        indexes = {
            row[1]: [
                info[2] for info in connection.execute(f"PRAGMA index_info('{row[1]}')")
            ]
            for row in connection.execute("PRAGMA index_list('preopen_news_checks')")
        }
        foreign = {
            row[3]: row[2]
            for row in connection.execute(
                "PRAGMA foreign_key_list('preopen_news_checks')"
            )
        }
        marker = (
            connection.execute("SELECT version_num FROM alembic_version").fetchall()
            if entry == "alembic"
            else connection.execute(
                "SELECT version FROM schema_migrations "
                "WHERE version = '0032_preopen_news_checks'"
            ).fetchall()
        )
    assert columns == {
        "id": True,
        "list_date": True,
        "candidate_run_id": True,
        "instrument_id": True,
        "rank": True,
        "window_start": True,
        "checked_at": True,
        "news_count": True,
        "positive": True,
        "negative": True,
        "mixed": True,
        "unknown": True,
        "unscored": True,
        "news_json": True,
        "prompt_version": True,
    }
    assert indexes["ix_preopen_news_checks_list_date"] == ["list_date"]
    assert indexes["ix_preopen_news_checks_candidate_run_id"] == ["candidate_run_id"]
    assert indexes["ix_preopen_news_checks_instrument_id"] == ["instrument_id"]
    assert ["list_date", "instrument_id"] in indexes.values()
    assert foreign == {
        "candidate_run_id": "candidate_runs",
        "instrument_id": "instruments",
    }
    assert marker == [
        (
            migration_revisions.REVISIONS[-1]
            if entry == "alembic"
            else "0032_preopen_news_checks",
        )
    ]
    assert migration_revisions.REVISIONS[-1] == "0032_preopen_news_checks"
