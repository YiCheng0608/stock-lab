"""Official no-trade days are not missing data (Issue #454).

The official daily quote tables (TWSE ``MI_INDEX``, TPEx ``dailyQuotes``) list
a thinly traded security on a day it did not trade, with its open, high, low
and close blank.  The bar parsers drop such a row, so coverage used to see
only "no bar" and counted the day as a gap.  The row is now kept as a
``no_trade_days`` record with its source; coverage reports it apart from a
real gap and never turns it into a price.

The row shapes below are copied from the production raw files sampled in
AC-1 of #454 (raw 6394, 9533 and 7999).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import test_unmatched_backfill as harness
import worker.backfill as backfill
import worker.no_trade_days as no_trade_days
import worker.pipeline as pipeline
import worker.sources as sources
from app.db import enable_sqlite_foreign_keys
from app import migration_revisions, migrations
from app.migrations import upgrade_database
from app.models import IngestionRun, Instrument, MarketBar, NoTradeDay, RawPayload

TPEX_FIELDS = [
    "代號",
    "名稱",
    "收盤",
    "漲跌",
    "開盤",
    "最高",
    "最低",
    "均價",
    "成交股數",
    "成交金額(元)",
    "成交筆數",
    "最後買價",
    "最後買量(張數)",
    "最後賣價",
    "最後賣量(張數)",
    "發行股數",
    "次日 參考價",
    "次日 漲停價",
    "次日 跌停價",
]
TWSE_FIELDS = [
    "證券代號",
    "證券名稱",
    "成交股數",
    "成交筆數",
    "成交金額",
    "開盤價",
    "最高價",
    "最低價",
    "收盤價",
    "漲跌(+/-)",
    "漲跌價差",
    "最後揭示買價",
    "最後揭示買量",
    "最後揭示賣價",
    "最後揭示賣量",
    "本益比",
]
# raw 6394 (TPEx dailyQuotes, 2026-10-07): 00734B has a row, prices "---".
TPEX_NO_TRADE = [
    "00734B",
    "台新JPM新興債",
    " ---",
    "--- ",
    "---",
    "---",
    "---",
    "14.79",
    "346",
    "5,117",
    "1",
    "14.81",
    "1",
    "14.83",
    "48",
    "24,979,000",
    "14.81",
    "9999.95",
    "0.01",
]
TPEX_TRADED = [
    "1259",
    "安心",
    "65.50",
    "-0.50",
    "66.00",
    "66.00",
    "65.50",
    "65.62",
    "1,067",
    "70,019",
    "3",
    "65.50",
    "1",
    "66.00",
    "2",
    "32,389,500",
    "65.50",
    "72.00",
    "59.00",
]
# A row with only some prices blank is malformed, not an official no-trade day.
TPEX_PARTIAL = ["3115", "富榮綱", "8.00", "--- ", "---", "---", "---"] + TPEX_TRADED[7:]
# raw 9533 (TWSE MI_INDEX, 2026-11-03): 1413 traded 0 shares, prices "--".
TWSE_NO_TRADE = [
    "1413",
    "宏洲",
    "0",
    "0",
    "0",
    "--",
    "--",
    "--",
    "--",
    "<p> </p>",
    "0.00",
    "9.10",
    "2",
    "9.32",
    "14",
    "30.06",
]
# raw 7999 (TWSE MI_INDEX, 2026-10-28): odd lots only, regular prices "--".
TWSE_ODD_LOT_ONLY = [
    "00647L",
    "元大S&P500正2",
    "464",
    "17",
    "65,482",
    "--",
    "--",
    "--",
    "--",
    "<p> </p>",
    "0.00",
    "140.70",
    "31",
    "140.85",
    "1",
    "0.00",
]
TWSE_TRADED = [
    "2330",
    "台積電",
    "1,000",
    "10",
    "1,000,000",
    "1,000.00",
    "1,005.00",
    "995.00",
    "1,000.00",
    "<p style= color:red>+</p>",
    "5.00",
    "1,000.00",
    "1",
    "1,005.00",
    "1",
    "20.00",
]


def _tpex_payload(*rows):
    return {
        "date": "20261007",
        "stat": "ok",
        "tables": [
            {"title": "上櫃股票行情", "fields": TPEX_FIELDS, "data": list(rows)}
        ],
    }


def _twse_payload(day, *rows):
    return {
        "date": day.strftime("%Y%m%d"),
        "stat": "OK",
        "tables": [
            {"title": "價格指數", "fields": ["指數", "收盤指數"], "data": []},
            {
                "title": "每日收盤行情(全部(不含權證、牛熊證、可展延牛熊證))",
                "fields": TWSE_FIELDS,
                "data": list(rows),
            },
        ],
    }


# ---- parsers: the blank-price row becomes a no-trade record, not a bar ----


def test_tpex_blank_price_row_is_a_no_trade_record_not_a_bar():
    payload = _tpex_payload(TPEX_NO_TRADE, TPEX_TRADED, TPEX_PARTIAL)

    bars = sources.parse_tpex_daily_rows(
        payload, data_as_of="2026-10-07", payload_sha256="sha-tpex"
    )
    no_trade = sources.parse_tpex_no_trade_rows(
        payload, data_as_of="2026-10-07", payload_sha256="sha-tpex"
    )

    assert {bar.symbol for bar in bars} == {"1259"}
    assert no_trade == [
        sources.NoTradeRecord(
            symbol="00734B",
            trading_date=date(2026, 10, 7),
            exchange="TPEx",
            source="tpex",
            data_as_of="2026-10-07",
            payload_sha256="sha-tpex",
        )
    ]


def test_twse_blank_price_rows_are_no_trade_records_with_or_without_odd_lots():
    day = date(2026, 11, 3)
    payload = _twse_payload(day, TWSE_NO_TRADE, TWSE_ODD_LOT_ONLY, TWSE_TRADED)

    bars = sources.parse_twse_all_daily_payload(
        payload, requested_date=day, payload_sha256="sha-twse"
    )
    no_trade = sources.parse_twse_all_daily_no_trade_payload(
        payload, requested_date=day, payload_sha256="sha-twse"
    )

    assert {bar.symbol for bar in bars} == {"2330"}
    assert [(item.symbol, item.trading_date, item.exchange) for item in no_trade] == [
        ("1413", day, "TWSE"),
        ("00647L", day, "TWSE"),
    ]
    assert {item.source for item in no_trade} == {"twse"}
    assert {item.payload_sha256 for item in no_trade} == {"sha-twse"}


# ---- coverage: no-trade day, real gap, newly listed ----


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'no_trade.db').as_posix()}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    make = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with make() as session:
        yield session
    engine.dispose()


def _sessions(count: int) -> list[date]:
    days: list[date] = []
    cursor = date(2026, 9, 1)
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _instrument(db, symbol, *, kind="stock", exchange="TPEx", listing=None):
    row = Instrument(
        market="TW",
        exchange=exchange,
        symbol=symbol,
        name=symbol,
        instrument_type=kind,
        listing_date=listing,
        status="active",
    )
    db.add(row)
    db.flush()
    return row


def _bar(db, item, day):
    db.add(
        MarketBar(
            instrument_id=item.id,
            trading_date=day,
            open=10,
            high=10,
            low=10,
            close=10,
            adj_close=10,
            volume=1000,
            turnover=10000,
            source="fixture",
        )
    )


def _no_trade(db, item, day):
    raw = RawPayload(
        source="tpex",
        endpoint=sources.TPEX_HISTORY_API,
        payload_path=f"fixture-{item.symbol}-{day.isoformat()}.json",
        sha256="0" * 64,
        data_as_of=day.isoformat(),
        collected_at=datetime(day.year, day.month, day.day, 10, 30),
    )
    db.add(raw)
    db.flush()
    db.add(
        NoTradeDay(
            instrument_id=item.id,
            trading_date=day,
            source="tpex",
            endpoint=sources.TPEX_HISTORY_API,
            data_as_of=day.isoformat(),
            collected_at=raw.collected_at,
            raw_payload_id=raw.id,
        )
    )


def _bar_reasons(row):
    """Reasons about bars; the fixtures store no chip rows."""

    return [item for item in row["coverage_reasons"] if item != "missing_chips"]


def _report(db, days):
    taiex = _instrument(db, "TAIEX", kind="index", exchange="TWSE")
    for day in days:
        _bar(db, taiex, day)
    db.commit()
    return backfill.coverage_report(db, days[0], days[-1])


def test_no_trade_day_real_gap_and_new_listing_are_counted_apart(db):
    days = _sessions(65)
    no_trade_day, gap_day = days[-3], days[-5]
    quiet = _instrument(db, "QUIET")  # bar missing, official row without prices
    gappy = _instrument(db, "GAPPY")  # bar missing, no evidence at all
    fresh = _instrument(db, "FRESH", kind="ipo", listing=days[-10])
    full = _instrument(db, "FULL")
    for day in days:
        if day != no_trade_day:
            _bar(db, quiet, day)
        if day != gap_day:
            _bar(db, gappy, day)
        if day >= fresh.listing_date:
            _bar(db, fresh, day)
        _bar(db, full, day)
    _no_trade(db, quiet, no_trade_day)
    # A bar outranks a no-trade record of the same day (a later correction).
    _no_trade(db, full, days[-2])
    # Before listing the day is not eligible at all.
    _no_trade(db, fresh, days[-12])

    report = _report(db, days)
    rows = {row["symbol"]: row for row in report["instrument_coverage"]}
    summary = report["summary"]

    assert rows["QUIET"]["missing_bars_to_20"] == 0
    assert rows["QUIET"]["missing_bar_dates_to_20"] == []
    assert rows["QUIET"]["no_trade_bars_to_20"] == 1
    assert rows["QUIET"]["no_trade_dates_to_20"] == [no_trade_day.isoformat()]
    assert rows["QUIET"]["bars_total"] == 64  # never turned into a price
    assert _bar_reasons(rows["QUIET"]) == ["official_no_trade"]

    assert rows["GAPPY"]["missing_bars_to_20"] == 1
    assert rows["GAPPY"]["missing_bar_dates_to_20"] == [gap_day.isoformat()]
    assert rows["GAPPY"]["no_trade_bars_to_20"] == 0
    assert _bar_reasons(rows["GAPPY"]) == ["missing_bar_dates"]

    assert rows["FRESH"]["missing_bars_to_20"] == 10
    assert rows["FRESH"]["no_trade_bars_to_20"] == 0
    assert "listed_under_threshold" in rows["FRESH"]["coverage_reasons"]

    assert rows["FULL"]["no_trade_bars_to_20"] == 0
    assert _bar_reasons(rows["FULL"]) == []

    assert summary["incomplete_to_20"] == 2  # GAPPY and FRESH, not QUIET
    assert summary["no_trade_to_20"] == 1
    assert summary["no_trade_to_60"] == 1
    assert summary["incomplete_to_60"] == 2
    assert summary["coverage_reason_counts"]["official_no_trade"] == 1


def test_a_no_trade_day_does_not_hide_a_real_gap_of_the_same_instrument(db):
    days = _sessions(65)
    quiet = _instrument(db, "MIXED")
    for day in days:
        if day not in {days[-3], days[-7]}:
            _bar(db, quiet, day)
    _no_trade(db, quiet, days[-3])

    report = _report(db, days)
    row = report["instrument_coverage"][0]

    assert row["missing_bars_to_20"] == 1
    assert row["missing_bar_dates_to_20"] == [days[-7].isoformat()]
    assert row["no_trade_dates_to_20"] == [days[-3].isoformat()]
    assert _bar_reasons(row) == ["missing_bar_dates", "official_no_trade"]
    assert report["summary"]["incomplete_to_20"] == 1
    assert report["summary"]["no_trade_to_20"] == 1


# ---- collect and the stored-raw sync write the evidence with its source ----

env = harness.env
DAY1 = harness.DAY1
QUIET_TWSE = sources.InstrumentRecord("1413", "宏洲", exchange="TWSE", industry="14")
QUIET_TPEX = sources.InstrumentRecord(
    "00734B",
    "台新JPM新興債",
    exchange="TPEx",
    instrument_type="etf",
    etf_category="bond",
)
# 00647L has a blank-price row but no stored instrument: counted, not written.
DAY1_TWSE = [harness._twse_row("2330", "1000.00"), TWSE_NO_TRADE, TWSE_ODD_LOT_ONLY]
DAY1_TPEX = [harness._tpex_row("6938", "80.00"), TPEX_NO_TRADE]


def _rows(db):
    return {
        (exchange, symbol): row
        for row, exchange, symbol in db.execute(
            select(NoTradeDay, Instrument.exchange, Instrument.symbol).join(
                Instrument, Instrument.id == NoTradeDay.instrument_id
            )
        )
    }


def _collect_day1():
    return harness._collect(
        DAY1,
        [harness.INDEX, harness.TSMC, QUIET_TWSE, QUIET_TPEX],
        DAY1_TWSE,
        DAY1_TPEX,
    )


def test_collect_writes_official_no_trade_days_with_their_raw(env):
    _result, payloads = _collect_day1()

    with env() as db:
        rows = _rows(db)
        raws = {raw.id: raw for raw in db.scalars(select(RawPayload))}
        runs = db.scalars(select(IngestionRun)).all()
        bar_symbols = set(
            db.scalars(
                select(Instrument.symbol)
                .join(MarketBar, MarketBar.instrument_id == Instrument.id)
                .where(MarketBar.trading_date == DAY1)
            )
        )

    assert set(rows) == {("TWSE", "1413"), ("TPEx", "00734B")}
    twse, tpex = rows[("TWSE", "1413")], rows[("TPEx", "00734B")]
    assert raws[twse.raw_payload_id].sha256 == payloads[0].sha256
    assert raws[tpex.raw_payload_id].sha256 == payloads[1].sha256
    assert (twse.source, tpex.source) == ("twse", "tpex")
    assert twse.endpoint.startswith(sources.TWSE_DAILY_HISTORY_ENDPOINT)
    assert tpex.endpoint == sources.TPEX_HISTORY_API
    assert {twse.data_as_of, tpex.data_as_of} == {DAY1.isoformat()}
    assert twse.collected_at == raws[twse.raw_payload_id].collected_at
    # Evidence, never a price.
    assert "1413" not in bar_symbols and "00734B" not in bar_symbols
    summary = next(
        run.metadata_json["no_trade_days"]
        for run in runs
        if "no_trade_days" in (run.metadata_json or {})
    )
    assert summary["status"] == "success"
    assert (summary["rows"], summary["unmatched"]) == (2, 1)
    assert summary["unmatched_samples"] == ["TWSE:00647L:2026-10-27"]


def test_sync_rebuilds_a_session_from_the_latest_capture_and_rewrites_nothing_else(
    env,
):
    _collect_day1()
    with env() as db:
        again = no_trade_days.sync_no_trade_days(db, [DAY1])
        db.commit()
    assert (again["unchanged"], again["written"]) == (2, 0)

    # A later TPEx capture of the day prices 00734B: its row goes.
    corrected = list(TPEX_NO_TRADE)
    corrected[2] = corrected[4] = corrected[5] = corrected[6] = "14.80"
    later = sources.capture_payload(
        "tpex",
        sources.TPEX_HISTORY_API,
        harness._tpex_quotes(DAY1, [corrected]),
        DAY1.isoformat(),
        collected_at=datetime(2026, 10, 27, 13, 30),
    )
    with env() as db:
        run = db.scalar(select(IngestionRun).order_by(IngestionRun.id))
        pipeline._upsert_raw_payload(db, run, later)
        # A bar of the day from another feed outranks the TWSE evidence.
        quiet = db.scalar(select(Instrument).where(Instrument.symbol == "1413"))
        _bar(db, quiet, DAY1)
        db.commit()
        result = no_trade_days.sync_no_trade_days(db, [DAY1])
        db.commit()
        rows = _rows(db)

    assert result["status"] == "success"
    assert result["written"] == 2
    assert rows == {}


def test_sync_stops_at_a_file_that_does_not_match_its_sha256(env):
    _collect_day1()
    with env() as db:
        raw = db.scalar(
            select(RawPayload).where(
                RawPayload.endpoint == sources.TPEX_HISTORY_API,
                RawPayload.data_as_of.like(f"{DAY1.isoformat()}%"),
            )
        )
        path = no_trade_days.payload_file(raw.payload_path)
        path.write_bytes(path.read_bytes() + b" ")
        result = no_trade_days.sync_no_trade_days(db, [DAY1], commit_each=True)
        rows = _rows(db)

    assert result["status"] == "failed"
    assert result["failed_date"] == DAY1.isoformat()
    assert "SHA-256" in result["error"]
    # The rows collect wrote stay; nothing was rebuilt from the bad file.
    assert set(rows) == {("TWSE", "1413"), ("TPEx", "00734B")}


def test_a_holidays_empty_answers_are_no_data_not_missing(env):
    _collect_day1()
    holiday = date(2026, 10, 26)  # 光復節補假: both exchanges answered empty
    endpoint = (
        f"{sources.TWSE_DAILY_HISTORY_ENDPOINT}?date=20261026"
        "&type=ALLBUT0999&response=json"
    )
    at = datetime(2026, 10, 26, 10, 30)
    empty = [
        sources.capture_payload(
            "twse",
            endpoint,
            {"stat": "很抱歉，沒有符合條件的資料!"},
            holiday.isoformat(),
            collected_at=at,
        ),
        sources.capture_payload(
            "tpex",
            sources.TPEX_HISTORY_API,
            harness._tpex_quotes(holiday, []),
            holiday.isoformat(),
            collected_at=at,
        ),
    ]
    with env() as db:
        run = db.scalar(select(IngestionRun).order_by(IngestionRun.id))
        for capture in empty:
            pipeline._upsert_raw_payload(db, run, capture)
        db.commit()
        result = no_trade_days.sync_no_trade_days(db, [holiday, date(2026, 10, 29)])

    assert result["no_data"] == 2  # the holiday, both exchanges
    assert result["missing"] == 2  # 10-29: nothing stored at all
    assert result["status"] == "partial"
    assert result["missing_samples"] == ["TWSE:2026-10-29", "TPEx:2026-10-29"]
    with env() as db:
        only_holiday = no_trade_days.sync_no_trade_days(db, [holiday])
    assert (only_holiday["status"], only_holiday["no_data"]) == ("success", 2)


def test_a_capture_without_a_security_table_leaves_the_days_rows_alone(env):
    # #482 review: a later TPEx capture of the day that has rows but no quote
    # table is not usable; it must not clear the day's evidence.
    _collect_day1()
    odd = sources.capture_payload(
        "tpex",
        sources.TPEX_HISTORY_API,
        {
            "date": "20261027",
            "stat": "ok",
            "tables": [{"title": "說明", "fields": ["說明"], "data": [["維護中"]]}],
        },
        DAY1.isoformat(),
        collected_at=datetime(2026, 10, 27, 13, 30),
    )
    with env() as db:
        run = db.scalar(select(IngestionRun).order_by(IngestionRun.id))
        pipeline._upsert_raw_payload(db, run, odd)
        db.commit()
        result = no_trade_days.sync_no_trade_days(db, [DAY1])
        db.commit()
        rows = _rows(db)

    assert result["status"] == "success"
    assert (result["unchanged"], result["written"]) == (2, 0)
    assert set(rows) == {("TWSE", "1413"), ("TPEx", "00734B")}


# ---- migration 0025: the table, its identity and indexes ----


@pytest.mark.parametrize("entry", ["alembic", "fallback"])
def test_the_upgrade_adds_the_no_trade_day_table(tmp_path, monkeypatch, entry):
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
            for row in connection.execute("PRAGMA table_info('no_trade_days')")
        }
        indexes = {
            row[1]: [
                info[2] for info in connection.execute(f"PRAGMA index_info('{row[1]}')")
            ]
            for row in connection.execute("PRAGMA index_list('no_trade_days')")
        }
        marker = (
            connection.execute("SELECT version_num FROM alembic_version").fetchall()
            if entry == "alembic"
            else connection.execute(
                "SELECT version FROM schema_migrations "
                "WHERE version = '0025_no_trade_days'"
            ).fetchall()
        )
    assert columns == {
        "id": True,
        "instrument_id": True,
        "trading_date": True,
        "source": True,
        "endpoint": True,
        "data_as_of": True,
        "collected_at": True,
        "raw_payload_id": True,
    }
    assert indexes["ix_no_trade_days_trading_date"] == ["trading_date"]
    assert indexes["ix_no_trade_days_raw_payload_id"] == ["raw_payload_id"]
    assert ["instrument_id", "trading_date"] in indexes.values()
    # alembic_version holds only the head; the fallback keeps every marker.
    assert marker == [
        (
            migration_revisions.REVISIONS[-1]
            if entry == "alembic"
            else "0025_no_trade_days",
        )
    ]
