"""The watchdog's daily data check of one trading date (Issue #390).

Each database here is written by the worker itself (``pipeline.collect``
with fixture feeds, ``_upsert_action``), with its raw captures in
``tmp_path``; a test then puts back the wrong value a past bug left
(#386 4549, #386 2330 09-16, #387 2313 10-19, #388 7710 10-27) and the check
must find it, while the database as the worker wrote it has no finding.
Nothing requests the network: the official result tables come from a
fixture fetcher.
"""

from __future__ import annotations

import importlib.util
import socket
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import worker.instrument_repair as repair
import worker.pipeline as pipeline
import worker.sources as sources
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import (
    ChipSnapshot,
    CorporateAction,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
    ScheduleRun,
    ScheduleRunStep,
)

ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location(
        "data_check", ROOT / "tools" / "ops" / "data_check.py"
    )
    module = importlib.util.module_from_spec(spec)
    # dataclasses look the module up while the class body runs.
    sys.modules["data_check"] = module
    spec.loader.exec_module(module)
    return module


data_check = _module()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in data check tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


class Database:
    def __init__(self, path: Path, factory) -> None:
        self.path = path
        self.factory = factory

    def check(self, day: date, *, official: bool = False, routes=(), limit=None):
        """The check's status line and findings."""

        engine = data_check.read_only_engine(str(self.path))
        try:
            with sessionmaker(bind=engine)() as session:
                check = data_check.DayCheck(
                    session, day, fetcher=Official(routes), official=official
                )
                check.run()
        finally:
            engine.dispose()
        return check


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "stock.db"
    engine = create_engine(f"sqlite:///{path}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(repair, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    yield Database(path, factory)
    engine.dispose()


class Official:
    """The official result tables by URL prefix; anything else is refused."""

    def __init__(self, routes) -> None:
        self.routes = list(routes)
        self.calls: list[str] = []

    def __call__(self, url, **kwargs):
        self.calls.append(url)
        for prefix, answer in self.routes:
            if url.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return answer
        raise AssertionError(f"unexpected request {url}")


def kinds(check) -> list[tuple[str, str, str]]:
    return [(item.check, item.symbol, item.field) for item in check.findings]


# --- bars and chips of a collected day (#387) ---------------------------------

from test_institutional_revisions import (  # noqa: E402
    DAY,
    FIRST,
    INITIAL,
    LATER,
    REVISED,
    Fetcher,
    collect_at,
    reopen,
    t86_capture,
)
from test_corporate_action_sync import (  # noqa: E402
    TPEX_4549,
    exdailyq,
    exdailyq_row,
    twt49u,
)


def tables(day: date, twse=(), tpex=()) -> list:
    """The day's TWT49U and exDailyQ answers."""
    return [
        (sources.TWSE_ACTION_HISTORY_ENDPOINT, twt49u(*twse)),
        (sources.TPEX_ACTION_HISTORY_ENDPOINT, exdailyq(day, day, *tpex)),
    ]


EMPTY_TABLES = tables(DAY)


def collected(database, monkeypatch) -> None:
    """DAY collected at 18:30 and again at 21:30, the second capture revised."""

    assert collect_at(monkeypatch, FIRST, Fetcher(INITIAL))["status"] == "success"
    reopen(database.factory)
    second = collect_at(monkeypatch, LATER, Fetcher(REVISED))
    assert second["value_revisions"] == 1, second


def chip(db, symbol="1101"):
    return db.scalar(
        select(ChipSnapshot)
        .join(Instrument, Instrument.id == ChipSnapshot.instrument_id)
        .where(Instrument.symbol == symbol, ChipSnapshot.trading_date == DAY)
    )


def bar(db, symbol="1101"):
    return db.scalar(
        select(MarketBar)
        .join(Instrument, Instrument.id == MarketBar.instrument_id)
        .where(Instrument.symbol == symbol, MarketBar.trading_date == DAY)
    )


def test_a_day_as_the_worker_wrote_it_has_no_finding(database, monkeypatch):
    collected(database, monkeypatch)
    check = database.check(DAY, official=True, routes=EMPTY_TABLES)
    assert check.findings == []
    assert check.facts["bars"] > 0 and check.facts["chips"] > 0
    assert data_check.status_line(check).startswith("data_check ok date=2026-09-04 ")


def test_a_bar_value_that_is_not_the_raw_one_is_found(database, monkeypatch):
    collected(database, monkeypatch)
    with database.factory() as db:
        stored = bar(db)
        raw = (stored.close, stored.volume)
        stored.close, stored.volume = 99.5, 12
        db.commit()
    check = database.check(DAY)
    assert [(i.check, i.symbol, i.field, i.raw, i.db) for i in check.findings] == [
        ("bar_value", "1101", "close", raw[0], 99.5),
        ("bar_value", "1101", "volume", raw[1], 12),
    ]


def test_a_bar_and_a_chip_row_the_raw_has_but_the_database_lacks(database, monkeypatch):
    collected(database, monkeypatch)
    with database.factory() as db:
        db.delete(chip(db))
        db.delete(bar(db))
        db.commit()
    assert ("bar_missing", "1101", "close") in kinds(database.check(DAY))
    with database.factory() as db:
        # Back to a bar without its chip row.
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "1101"))
        record = next(
            item
            for raw in db.scalars(select(RawPayload))
            if repair._is_quote_capture(raw.endpoint)
            for item in repair._quote_bars(raw, repair._load(raw))
            if item.symbol == "1101"
        )
        pipeline._upsert_official_bar(db, instrument, record, None)
        db.commit()
    found = kinds(database.check(DAY))
    assert ("chip_missing", "1101", "institutional") in found


def test_2313_holding_the_1830_flow_after_the_2130_capture_is_found(
    database, monkeypatch
):
    # #387: 2313 2026-10-19 kept the 18:30 trust flow -162,968 while the
    # 21:30 capture had 1,133,032 (the fixture row carries 2313's numbers).
    collected(database, monkeypatch)
    with database.factory() as db:
        row = chip(db)
        row.trust_buy = -162968.0
        row.raw_payload_id = row.institutional_raw_payload_id = t86_capture(db, FIRST)
        later = t86_capture(db, LATER)
        db.commit()
    check = database.check(DAY)
    assert [(i.check, i.field, i.raw, i.db) for i in check.findings] == [
        ("chip_revision", "trust_buy", 1133032.0, -162968.0)
    ]
    assert f"raw_payload {later}" in check.findings[0].note


def test_a_margin_value_that_no_capture_has_is_found(database, monkeypatch):
    collected(database, monkeypatch)
    with database.factory() as db:
        row = chip(db)
        expected, row.margin_balance = row.margin_balance, 1.0
        db.commit()
    check = database.check(DAY)
    assert [(i.check, i.field, i.raw, i.db) for i in check.findings] == [
        ("chip_value", "margin_balance", expected, 1.0)
    ]


# --- corporate actions (#386, #402 review) ----------------------------------

DAY_4549 = date(2026, 9, 8)
DAY_2330 = date(2026, 9, 16)


def instrument(db, exchange, symbol, *, status="active", kind="stock"):
    item = Instrument(
        exchange=exchange,
        symbol=symbol,
        name=symbol,
        instrument_type=kind,
        status=status,
    )
    db.add(item)
    db.flush()
    return item


def stored_capture(db, source, endpoint, payload, as_of: date) -> RawPayload:
    """A raw capture on disk and in raw_payloads, as collect records one."""

    capture = sources.capture_payload(
        source,
        endpoint,
        payload,
        as_of.isoformat(),
        collected_at=datetime(as_of.year, as_of.month, as_of.day, 10, 30),
    )
    run = IngestionRun(
        run_type="collect", source="official", run_date=as_of, status="success"
    )
    db.add(run)
    db.flush()
    return pipeline._upsert_raw_payload(db, run, capture)


def the_4549_row(database, *, ratio=None) -> None:
    """4549 2026-09-08 written from its tpex_exright_daily capture."""

    with database.factory() as db:
        item = instrument(db, "TPEx", "4549")
        raw = stored_capture(
            db, "tpex", sources.TPEX_ACTION_ENDPOINT, [TPEX_4549], DAY_4549
        )
        record = sources.parse_tpex_action_rows(
            [TPEX_4549], as_of=DAY_4549, payload_sha256=raw.sha256
        )[0]
        pipeline._upsert_action(db, record, {("TPEx", "4549"): item}, raw.id)
        db.flush()
        if ratio is not None:
            # Written before the parser read StockDivdendThousandShares.
            db.scalar(select(CorporateAction)).stock_dividend_ratio = ratio
        db.commit()


def test_the_4549_ratio_stored_as_a_rights_value_is_found(database):
    the_4549_row(database, ratio=2.02941)
    check = database.check(DAY_4549)
    assert [(i.check, i.symbol, i.field, i.db) for i in check.findings] == [
        ("action_value", "4549", "stock_dividend_ratio", 2.02941)
    ]
    assert check.findings[0].raw == pytest.approx(0.02, abs=1e-6)


def test_the_4549_row_written_by_the_current_parser_passes(database):
    the_4549_row(database)
    official = tables(DAY_4549, tpex=[exdailyq_row(TPEX_4549)])
    check = database.check(DAY_4549, official=True, routes=official)
    assert check.findings == []
    assert check.facts["official_actions"] == 1


def test_the_4549_wrong_ratio_also_disagrees_with_the_official_table(database):
    the_4549_row(database, ratio=2.02941)
    official = tables(DAY_4549, tpex=[exdailyq_row(TPEX_4549)])
    check = database.check(DAY_4549, official=True, routes=official)
    assert [(i.check, i.note) for i in check.findings] == [
        ("action_value", "raw_payload 1"),
        ("action_value", "官方結果表"),
    ]


# 2330's 2026-09-16 cash dividend as TWT48U announced it on 2026-09-09.
TWT48U_2330 = {
    "Date": "1150916",
    "Code": "2330",
    "Name": "台積電",
    "Exdividend": "息",
    "StockDividendRatio": "",
    "CashDividend": "7.00000000",
    "SubscriptionRatio": "",
}
TWT49U_2330 = ["115年09月16日", "2330", "台積電", "1000.00", "993.00", "7.000000", "息", "1090.00", "894.00", "993.00", "993.00", "", "115年第2季", "1.00", "1.00"]  # fmt: skip


def announced_2330(database, *, written=False, cash=None) -> None:
    with database.factory() as db:
        item = instrument(db, "TWSE", "2330")
        raw = stored_capture(
            db,
            "twse",
            sources.TWSE_ACTION_ENDPOINT,
            [TWT48U_2330],
            date(2026, 9, 9),
        )
        if written:
            # The 09-16 daily: TWT48U lists the event on its ex-date.
            today = stored_capture(
                db, "twse", sources.TWSE_ACTION_ENDPOINT, [TWT48U_2330], DAY_2330
            )
            record = sources.parse_twse_action_rows(
                [TWT48U_2330], as_of=DAY_2330, payload_sha256=today.sha256
            )[0]
            pipeline._upsert_action(db, record, {("TWSE", "2330"): item}, today.id)
            db.flush()
            if cash is not None:
                db.scalar(select(CorporateAction)).cash_dividend = cash
        assert raw.id
        db.commit()


def test_the_2330_event_twt48u_announced_but_the_table_lacks_is_found(database):
    # #386 A2: 09-10..10-16 had no daily snapshot, so 2330's 09-16 event that
    # the 09-09 TWT48U announced never reached corporate_actions.
    announced_2330(database)
    check = database.check(DAY_2330)
    assert kinds(check) == [("action_missing", "2330", "action_date")]
    assert check.findings[0].note == "raw_payload 1"
    official = tables(DAY_2330, [TWT49U_2330])
    check = database.check(DAY_2330, official=True, routes=official)
    assert [(i.check, i.note) for i in check.findings] == [
        ("action_missing", "raw_payload 1"),
        ("action_missing", "官方結果表"),
    ]


def test_the_2330_event_written_on_its_ex_date_passes(database):
    announced_2330(database, written=True)
    official = tables(DAY_2330, [TWT49U_2330])
    check = database.check(DAY_2330, official=True, routes=official)
    assert check.findings == []


def test_a_twt48u_row_is_checked_against_the_official_prices(database):
    # TWT48U has no official prices, so the write guard cannot check it;
    # the result table of the ex-date can.
    announced_2330(database, written=True, cash=70.0)
    official = tables(DAY_2330, [TWT49U_2330])
    check = database.check(DAY_2330, official=True, routes=official)
    assert [(i.check, i.field, i.raw) for i in check.findings] == [
        ("action_value", "cash_dividend", 7.0),
        ("action_factor", "factor", 0.993),
    ]
    assert check.findings[1].db == pytest.approx(0.93)


def test_a_stored_event_the_official_tables_lack_is_found(database):
    announced_2330(database, written=True)
    check = database.check(DAY_2330, official=True, routes=tables(DAY_2330))
    assert kinds(check) == [("action_not_official", "2330", "action_type")]


def test_an_official_table_that_cannot_be_read_is_a_finding(database):
    announced_2330(database, written=True)
    routes = [
        (
            sources.TWSE_ACTION_HISTORY_ENDPOINT,
            sources.OfficialDataError("official endpoint retry exhausted (503)"),
        )
    ]
    check = database.check(DAY_2330, official=True, routes=routes)
    assert kinds(check) == [
        ("action_official_unavailable", "-", "TWT49U/exDailyQ"),
    ]


# --- 7710: a new listing's first session (#388) ------------------------------

from test_unmatched_backfill import (  # noqa: E402
    DAY1,
    DAY2,
    _first_session,
    _second_session,
    _second_session_without_backfill,
)


def test_7710_still_unmatched_after_its_instrument_exists_is_found(
    database, monkeypatch
):
    _first_session()
    _second_session_without_backfill(monkeypatch)
    check = database.check(DAY2)
    assert sorted((i.check, i.symbol, i.day) for i in check.findings) == [
        ("unmatched_bar", "6938", DAY1.isoformat()),
        ("unmatched_bar", "7710", DAY1.isoformat()),
    ]


def test_7710_written_from_the_stored_raw_passes(database):
    _first_session()
    _second_session()
    assert database.check(DAY2).findings == []
    assert database.check(DAY1).findings == []


# --- row counts --------------------------------------------------------------

SESSIONS = [date(2026, 10, day) for day in (19, 20, 21, 22, 23, 26)]


def counted(database, today: int, *, before: int = 100) -> None:
    with database.factory() as db:
        items = [instrument(db, "TWSE", f"{1000 + n}") for n in range(before)]
        etf = instrument(db, "TWSE", "0050", kind="etf")
        for day in SESSIONS:
            rows = items if day != SESSIONS[-1] else items[:today]
            for item in [*rows, etf]:
                db.add(
                    MarketBar(
                        instrument_id=item.id,
                        trading_date=day,
                        open=1,
                        high=1,
                        low=1,
                        close=1,
                        adj_close=1,
                        volume=1,
                        source="twse",
                    )
                )
        db.commit()


@pytest.mark.parametrize(("today", "found"), [(96, True), (97, False), (100, False)])
def test_common_stock_rows_more_than_3_percent_below_the_median(database, today, found):
    counted(database, today)
    check = database.check(SESSIONS[-1])
    drops = [item for item in check.findings if item.check == "row_count"]
    assert check.facts["twse_stock_bars"] == today
    if found:
        assert [(i.exchange, i.raw, i.db) for i in drops] == [("TWSE", 100, 96)]
    else:
        assert drops == []


# --- the 21:30 institutional refetch (#396) ---------------------------------


def refetched(database, status: str, *, error: str | None = None) -> None:
    with database.factory() as db:
        success = ScheduleRun(job="daily", target_date=DAY, status="success")
        skipped = ScheduleRun(
            job="daily",
            target_date=DAY,
            status="skipped",
            summary_json={"reason": "already_complete"},
        )
        db.add_all([success, skipped])
        db.flush()
        db.add(
            ScheduleRunStep(
                schedule_run_id=skipped.id,
                step="institutional_refetch",
                status=status,
                error=error,
            )
        )
        db.commit()


@pytest.mark.parametrize("status", ["failed", "partial"])
def test_a_refetch_that_did_not_succeed_is_found(database, status):
    refetched(database, status, error="TPEx: official endpoint retry exhausted")
    check = database.check(DAY)
    assert [(i.check, i.db) for i in check.findings] == [
        ("institutional_refetch", status)
    ]
    assert "TPEx: official endpoint retry exhausted" in check.findings[0].note


def test_a_refetch_still_running_leaves_the_day_pending(database):
    refetched(database, "running")
    check = database.check(DAY)
    assert check.pending and check.findings == []
    assert data_check.status_line(check).startswith("data_check pending ")


def test_a_successful_refetch_passes(database):
    refetched(database, "success")
    check = database.check(DAY)
    assert check.findings == [] and check.facts["refetch"] == "success"


# --- read only, and the comment's list --------------------------------------


def test_the_check_reads_the_database_read_only(database, monkeypatch):
    collected(database, monkeypatch)
    before = (database.path.read_bytes(), database.path.stat().st_mtime_ns)
    out = data_check.data_check(
        str(database.path), DAY.isoformat(), fetcher=Official(EMPTY_TABLES)
    )
    assert out.startswith("data_check ok ")
    assert (database.path.read_bytes(), database.path.stat().st_mtime_ns) == before
    engine = data_check.read_only_engine(str(database.path))
    try:
        with engine.connect() as conn:
            raw = conn.connection.dbapi_connection
            assert raw.execute("PRAGMA query_only").fetchone() == (1,)
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                raw.execute("UPDATE market_bars SET close = 1")
            # mode=ro still refuses with query_only switched off.
            raw.execute("PRAGMA query_only=OFF")
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                raw.execute("DELETE FROM chip_snapshots")
    finally:
        engine.dispose()


def test_the_comment_lists_the_first_20_findings_and_the_total(database):
    counted(database, 96)
    check = database.check(SESSIONS[-1])
    findings = [
        data_check.Finding("bar_value", "TWSE", f"{n}", "2026-10-26", "close", n, n + 1)
        for n in range(25)
    ]
    check.findings = findings
    text = data_check.details(check)
    rows = [line for line in text.splitlines() if line.startswith("| `bar_value`")]
    assert len(rows) == 20
    assert rows[0] == "| `bar_value` | TWSE | 0 | 2026-10-26 | `close` | 0 | 1 |  |"
    assert "只列前 20 筆，共 25 筆" in text
    assert "日線 raw 與 DB 不符（`bar_value`）：25 筆" in text
    assert len(data_check.details(check, limit=None).splitlines()) > len(
        text.splitlines()
    )


def test_a_database_without_the_checked_tables_is_skipped(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE schedule_runs (id INTEGER PRIMARY KEY)")
    conn.close()
    out = data_check.data_check(str(path), "2026-10-19", official=False)
    assert out.startswith("data_check skip date=2026-10-19 missing_tables=")
    assert "market_bars" in out
