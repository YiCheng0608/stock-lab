"""Capital reduction stops of trading are recorded, not missing data (Issue #582).

3714 富采 (TWSE) and 4534 慶騰 (TPEx) reduced their capital: the old shares
last traded on 2026-11-04 and stopped trading 11/05～11/13, the new shares
trade from 11/16.  The official quote tables have no row for them on the
stopped sessions, so the days looked like a collection gap.  TWSE
``TWTAUU`` and TPEx ``revivt`` list each stop by its resumption day before it
begins; collect now stores the interval in ``trading_halts`` and coverage,
the stock page and the action summary name it.  The bar counts the strategy
readiness reads are unchanged: a stopped session is still no bar.

The payload shapes below are the official answers fetched 2026-11-10 (AC-1).
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
import worker.pipeline as pipeline
import worker.sources as sources
import worker.trading_halts as trading_halts
from app import migration_revisions, migrations
from app.api import _stock_trading_halt
from app.db import enable_sqlite_foreign_keys
from app.decision import build_decision_summary
from app.migrations import upgrade_database
from app.models import (
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
    TradingHalt,
)

TWSE_FIELDS = [
    "恢復買賣日期",
    "股票代號",
    "名稱",
    "停止買賣前收盤價格",
    "恢復買賣參考價",
    "漲停價格",
    "跌停價格",
    "開盤競價基準",
    "除權參考價",
    "減資原因",
    "詳細資料",
]
TWSE_3714 = [
    "115/11/16",
    "3714",
    "富采",
    "56.70",
    "96.15",
    "105.50",
    "86.60",
    "96.20",
    "--",
    "退還股款",
    "3714  ,20261104",
]
# Published before its reference price is known.
TWSE_1808 = [
    "115/11/23",
    "1808",
    "潤隆",
    "-",
    "-",
    "-",
    "-",
    "-",
    "--",
    "退還股款",
    "1808  ,20261109",
]
TPEX_FIELDS = [
    "恢復買賣日期",
    "股票代號",
    "名稱",
    "最後交易日之收盤價格",
    "減資恢復買賣開始日參考價格",
    "漲停價格",
    "跌停價格",
    "開始交易基準價",
    "除權參考價",
    "減資原因",
    "詳細資料",
]


def _tpex_detail(code, name, stopped, resumed):
    return (
        f"<table><tr><th>股票代號/股票名稱:</th><td>{code}&nbsp/&nbsp{name}</td></tr>"
        f"<tr><th>停止買賣日期:</th><td>{stopped}</td></tr>"
        f"<tr><th>恢復買賣日期:</th><td>{resumed}</td></tr>"
        "<tr><th>每壹仟股換發新股票:</th><td>792.60032000&nbsp股</td></tr>"
        "<tr><th>每股退還股款:</th><td>0.00000000&nbsp元/股</td></tr></table>"
    )


TPEX_4534 = [
    "1151116",
    "4534",
    "慶騰",
    "25.45",
    "32.11",
    "35.30",
    "28.90",
    "32.10",
    "0.00",
    "彌補虧損",
    _tpex_detail("4534", "慶騰", "115/11/05", "115/11/16"),
]
START, END = date(2026, 11, 1), date(2026, 11, 30)


def twse_payload(start, end, *rows):
    if not rows:
        return {"stat": "很抱歉，沒有符合條件的資料!"}
    return {
        "stat": "OK",
        "title": "股票減資恢復買賣參考價格",
        "fields": TWSE_FIELDS,
        "data": [list(row) for row in rows],
        "strDate": start.strftime("%Y%m%d"),
        "endDate": end.strftime("%Y%m%d"),
    }


def tpex_payload(start, end, *rows, total=None):
    return {
        "date": f"{start:%Y%m%d}~{end:%Y%m%d}",
        "tables": [
            {
                "title": "",
                "subtitle": "" if rows else "本日無資料",
                "totalCount": len(rows) if total is None else total,
                "fields": TPEX_FIELDS,
                "data": [list(row) for row in rows],
                "summary": [],
                "notes": [],
            }
        ],
        "stat": "ok",
    }


# ---- the two official tables ----


def test_twse_rows_give_the_stop_from_the_day_after_the_last_trade():
    records, rejected = sources.parse_twse_reduction_payload(
        twse_payload(START, END, TWSE_3714, TWSE_1808), start=START, end=END
    )

    assert rejected == []
    by_symbol = {record.symbol: record for record in records}
    fuchi = by_symbol["3714"]
    assert (fuchi.last_trade_date, fuchi.halt_start, fuchi.resume_date) == (
        date(2026, 11, 4),
        date(2026, 11, 5),
        date(2026, 11, 16),
    )
    assert (fuchi.exchange, fuchi.source, fuchi.reason) == (
        "TWSE",
        "twse_twtauu",
        "capital_reduction",
    )
    assert fuchi.reason_detail == "退還股款"
    assert fuchi.details["停止買賣前收盤價格"] == "56.70"
    # Listed ahead: the stop of 1808 begins after the day it was published.
    assert by_symbol["1808"].halt_start == date(2026, 11, 10)


def test_tpex_rows_give_the_stated_first_stopped_day():
    records, rejected = sources.parse_tpex_reduction_payload(
        tpex_payload(START, END, TPEX_4534), start=START, end=END
    )

    assert rejected == []
    (record,) = records
    assert (record.symbol, record.halt_start, record.resume_date) == (
        "4534",
        date(2026, 11, 5),
        date(2026, 11, 16),
    )
    assert record.last_trade_date is None
    assert (record.source, record.reason_detail) == ("tpex_revivt", "彌補虧損")


def test_empty_answers_are_an_empty_range():
    assert sources.parse_twse_reduction_payload(
        twse_payload(START, END), start=START, end=END
    ) == ([], [])
    assert sources.parse_tpex_reduction_payload(
        tpex_payload(START, END), start=START, end=END
    ) == ([], [])


@pytest.mark.parametrize(
    "exchange, payload",
    [
        # Another range than asked for.
        ("TWSE", twse_payload(START, END - timedelta(days=1), TWSE_3714)),
        ("TPEx", tpex_payload(START, END - timedelta(days=1), TPEX_4534)),
        # A truncated answer.
        ("TPEx", tpex_payload(START, END, TPEX_4534, total=2)),
        # A resumption outside the range asked for.
        ("TWSE", twse_payload(START, END, ["115/12/01", *TWSE_3714[1:]])),
        # Changed columns.
        ("TWSE", {**twse_payload(START, END, TWSE_3714), "fields": TWSE_FIELDS[:-1]}),
        ("TWSE", {"stat": "查詢日期大於今日"}),
    ],
)
def test_an_answer_that_cannot_be_trusted_is_rejected_whole(exchange, payload):
    with pytest.raises(sources.OfficialDataError):
        sources.parse_reduction_payload(
            exchange, payload, start=START, end=END, endpoint="fixture"
        )


def test_a_row_whose_own_dates_disagree_is_left_out_and_named():
    twse_wrong_code = [*TWSE_3714[:-1], "2330  ,20261104"]
    twse_late = [*TWSE_1808[:-1], "1808  ,20261123"]
    tpex_wrong_resume = [
        *TPEX_4534[:-1],
        _tpex_detail("4534", "慶騰", "115/11/05", "115/11/17"),
    ]
    tpex_no_start = [*TPEX_4534[:-1], _tpex_detail("4534", "慶騰", "", "115/11/16")]

    twse, twse_rejected = sources.parse_twse_reduction_payload(
        twse_payload(START, END, twse_wrong_code, twse_late), start=START, end=END
    )
    tpex, tpex_rejected = sources.parse_tpex_reduction_payload(
        tpex_payload(START, END, tpex_wrong_resume, tpex_no_start),
        start=START,
        end=END,
    )

    assert twse == [] and tpex == []
    assert [item.split(" ")[0] for item in twse_rejected] == ["3714", "1808"]
    assert len(tpex_rejected) == 2 and all("4534" in item for item in tpex_rejected)


# ---- collect stores the stops with their raw ----

env = harness.env
DAY = date(2026, 11, 9)
FUCHI = sources.InstrumentRecord("3714", "富采", exchange="TWSE", industry="26")
CHINGTENG = sources.InstrumentRecord("4534", "慶騰", exchange="TPEx", industry="05")


def _halt_capture(exchange, payload, day=DAY):
    start = day - timedelta(days=sources.TRADING_HALT_DAYS_BEFORE)
    end = day + timedelta(days=sources.TRADING_HALT_DAYS_AFTER)
    endpoint = sources.reduction_query(exchange, start, end)
    captured = sources.capture_payload(
        exchange.lower(),
        endpoint,
        payload(start, end),
        day.isoformat(),
        collected_at=datetime(day.year, day.month, day.day, 13, 30),
    )
    records, rejected = sources.parse_reduction_payload(
        exchange,
        captured.payload,
        start=start,
        end=end,
        endpoint=endpoint,
        payload_sha256=captured.sha256,
    )
    window = sources.TradingHaltWindow(
        exchange=exchange,
        source=sources.TRADING_HALT_SOURCES[exchange],
        endpoint=endpoint,
        start=start,
        end=end,
        payload_sha256=captured.sha256,
        rejected=tuple(rejected),
    )
    return captured, records, window


def _collect(twse_rows, tpex_rows, *, twse_quotes=(), tpex_quotes=(), day=DAY):
    quotes, bars = harness._session(
        day, [harness._twse_row("2330", "1000.00"), *twse_quotes], list(tpex_quotes)
    )
    twse = _halt_capture(
        "TWSE", lambda start, end: twse_payload(start, end, *twse_rows), day
    )
    tpex = _halt_capture(
        "TPEx", lambda start, end: tpex_payload(start, end, *tpex_rows), day
    )
    batch = sources.OfficialBatch(
        instruments=[harness.INDEX, harness.TSMC, FUCHI, CHINGTENG],
        bars=bars,
        chips=[],
        payloads=quotes + [twse[0], tpex[0]],
        data_as_of=day.isoformat(),
        snapshot_feeds=False,
        trading_halts=twse[1] + tpex[1],
        trading_halt_windows=[twse[2], tpex[2]],
    )
    result = pipeline.collect(day, months_back=0, adapter=harness.FakeAdapter(batch))
    return result, (twse[0], tpex[0])


def _halts(db):
    return {
        (row.exchange, symbol): row
        for row, symbol in db.execute(
            select(TradingHalt, Instrument.symbol).join(
                Instrument, Instrument.id == TradingHalt.instrument_id
            )
        )
    }


def test_collect_writes_each_stop_with_its_raw(env):
    result, (twse, tpex) = _collect([TWSE_3714, TWSE_1808], [TPEX_4534])

    assert result["status"] == "success", result
    with env() as db:
        halts = _halts(db)
        raws = {raw.id: raw for raw in db.scalars(select(RawPayload))}
        run = db.get(IngestionRun, result["run_id"])
    # 1808 has no stored instrument: counted, not written.
    assert set(halts) == {("TWSE", "3714"), ("TPEx", "4534")}
    fuchi, chingteng = halts[("TWSE", "3714")], halts[("TPEx", "4534")]
    assert (fuchi.halt_start, fuchi.resume_date, fuchi.last_trade_date) == (
        date(2026, 11, 5),
        date(2026, 11, 16),
        date(2026, 11, 4),
    )
    assert (chingteng.halt_start, chingteng.resume_date) == (
        date(2026, 11, 5),
        date(2026, 11, 16),
    )
    assert raws[fuchi.raw_payload_id].sha256 == twse.sha256
    assert raws[chingteng.raw_payload_id].sha256 == tpex.sha256
    assert fuchi.collected_at == raws[fuchi.raw_payload_id].collected_at
    assert fuchi.endpoint.startswith(sources.TWSE_REDUCTION_ENDPOINT)
    assert fuchi.details_json["詳細資料"] == "3714  ,20261104"
    meta = run.metadata_json["trading_halts"]
    assert meta["TWSE"]["inserted"] == 1 and meta["TWSE"]["outside_universe"] == 1
    assert meta["TPEx"]["inserted"] == 1


# A TPEx stop of a code without a stored instrument.
TPEX_OTHER = [
    "1151123",
    "9958",
    "世紀鋼",
    "-",
    "-",
    "-",
    "-",
    "-",
    "0.00",
    "彌補虧損",
    _tpex_detail("9958", "世紀鋼", "115/11/12", "115/11/23"),
]


def _resumptions(db):
    return sorted(
        (row.exchange, symbol, row.resume_date)
        for row, symbol in db.execute(
            select(TradingHalt, Instrument.symbol).join(
                Instrument, Instrument.id == TradingHalt.instrument_id
            )
        )
    )


def test_a_later_answer_rebuilds_its_range(env):
    _collect([TWSE_3714], [TPEX_4534])
    # The next day TWSE postpones 3714 by a week and TPEx no longer lists 4534
    # (it lists another stop).
    later = [
        "115/11/23",
        *TWSE_3714[1:-1],
        "3714  ,20261104",
    ]
    result, _captures = _collect([later], [TPEX_OTHER], day=date(2026, 11, 10))

    assert result["status"] == "success", result
    with env() as db:
        halts = _halts(db)
        run = db.get(IngestionRun, result["run_id"])
    assert set(halts) == {("TWSE", "3714")}
    assert halts[("TWSE", "3714")].resume_date == date(2026, 11, 23)
    meta = run.metadata_json["trading_halts"]
    assert (meta["TWSE"]["inserted"], meta["TWSE"]["removed"]) == (1, 1)
    assert (meta["TPEx"]["removed"], meta["TPEx"]["outside_universe"]) == (1, 1)


def test_an_empty_answer_keeps_the_stored_stops(env):
    # TWSE's empty answer has no range or count to check: a wrong one must not
    # lose the stops (on D = resumption + 10 they would never come back).
    _collect([TWSE_3714], [TPEX_4534])
    result, _captures = _collect([], [], day=date(2026, 11, 10))

    assert result["status"] == "success", result
    assert result["core_warnings"] == []
    window = "2026-10-31..2027-01-09"
    assert [item for item in result["noncore_warnings"] if "trading halts" in item] == [
        f"TWSE trading halts empty answer kept 1 stored rows resuming {window}",
        f"TPEx trading halts empty answer kept 1 stored rows resuming {window}",
    ]
    with env() as db:
        assert set(_halts(db)) == {("TWSE", "3714"), ("TPEx", "4534")}
        run = db.get(IngestionRun, result["run_id"])
    meta = run.metadata_json["trading_halts"]
    assert (meta["TWSE"]["removed"], meta["TWSE"]["kept_on_empty"]) == (0, 1)
    assert (meta["TPEx"]["removed"], meta["TPEx"]["kept_on_empty"]) == (0, 1)


def test_an_empty_answer_with_nothing_stored_is_quiet(env):
    result, _captures = _collect([], [])

    assert result["status"] == "success", result
    assert not [item for item in result["noncore_warnings"] if "trading halts" in item]


def test_a_rebuild_leaves_stops_resuming_outside_its_range(env):
    _collect([TWSE_3714], [TPEX_4534])
    # Two months on, 3714 reduces again; the 11/16 resumption is outside the
    # new answer's range (2027-01-01..2027-03-12); TPEx lists nothing there.
    again = ["116/01/12", *TWSE_3714[1:-1], "3714  ,20270105"]
    result, _captures = _collect([again], [], day=date(2027, 1, 11))

    assert result["status"] == "success", result
    with env() as db:
        assert _resumptions(db) == [
            ("TPEx", "4534", date(2026, 11, 16)),
            ("TWSE", "3714", date(2026, 11, 16)),
            ("TWSE", "3714", date(2027, 1, 12)),
        ]
        run = db.get(IngestionRun, result["run_id"])
    meta = run.metadata_json["trading_halts"]
    assert (meta["TWSE"]["inserted"], meta["TWSE"]["removed"]) == (1, 0)
    assert meta["TPEx"]["removed"] == 0


def test_a_failed_write_changes_neither_the_stops_nor_the_collect(env):
    # The TWSE window's capture is not among the collect's payloads, so its
    # write fails inside its savepoint: TPEx and the bars are still written.
    quotes, bars = harness._session(DAY, [harness._twse_row("2330", "1000.00")], [])
    twse = _halt_capture("TWSE", lambda start, end: twse_payload(start, end, TWSE_3714))
    tpex = _halt_capture("TPEx", lambda start, end: tpex_payload(start, end, TPEX_4534))
    batch = sources.OfficialBatch(
        instruments=[harness.INDEX, harness.TSMC, FUCHI, CHINGTENG],
        bars=bars,
        chips=[],
        payloads=quotes + [tpex[0]],
        data_as_of=DAY.isoformat(),
        snapshot_feeds=False,
        trading_halts=twse[1] + tpex[1],
        trading_halt_windows=[twse[2], tpex[2]],
    )

    result = pipeline.collect(DAY, months_back=0, adapter=harness.FakeAdapter(batch))

    assert result["status"] == "success", result
    assert [item for item in result["noncore_warnings"] if "trading halts" in item] == [
        "TWSE trading halts unavailable: ValueError: no raw payload for the TWSE "
        "capital reduction table"
    ]
    with env() as db:
        assert set(_halts(db)) == {("TPEx", "4534")}
        tsmc_bars = db.scalars(
            select(MarketBar.trading_date)
            .join(Instrument, Instrument.id == MarketBar.instrument_id)
            .where(Instrument.symbol == "2330")
        ).all()
    assert tsmc_bars == [DAY]


def test_an_unchanged_answer_keeps_the_capture_that_brought_it(env):
    _collect([TWSE_3714], [TPEX_4534])
    with env() as db:
        first = {key: row.raw_payload_id for key, row in _halts(db).items()}
    result, _captures = _collect([TWSE_3714], [TPEX_4534], day=date(2026, 11, 10))

    with env() as db:
        second = {key: row.raw_payload_id for key, row in _halts(db).items()}
        run = db.get(IngestionRun, result["run_id"])
    assert second == first
    assert run.metadata_json["trading_halts"]["TWSE"]["unchanged"] == 1


def test_a_stop_the_quote_table_contradicts_is_not_written(env):
    # 3714 has a price on 11/09, inside the stated stop, and it is not the
    # stated 停止買賣前收盤: the bar wins.  4534 (TPEx states its first
    # stopped day) has one too.
    result, _captures = _collect(
        [TWSE_3714],
        [TPEX_4534],
        twse_quotes=[harness._twse_row("3714", "60.00")],
        tpex_quotes=[harness._tpex_row("4534", "25.45")],
    )

    assert result["status"] == "success", result
    rejected = [
        item
        for item in result["noncore_warnings"]
        if item.startswith(
            ("TWSE trading halts rejected", "TPEx trading halts rejected")
        )
    ]
    assert rejected == [
        "TWSE trading halts rejected: 3714 has a bar on 2026-11-09 inside its stop "
        "2026-11-05..2026-11-16",
        "TPEx trading halts rejected: 4534 has a bar on 2026-11-09 inside its stop "
        "2026-11-05..2026-11-16",
    ]
    assert result["core_warnings"] == []
    with env() as db:
        assert _halts(db) == {}


def test_a_twse_last_trading_day_stated_a_session_early_follows_the_bar(env):
    # 4155 訊映 (2026-10): 詳細資料 20261005, but its 停止買賣前收盤 14.20 is the
    # 10/06 close; that session traded and the stop began after it.
    row = ["115/10/19", "4155", "訊映", "14.20", "14.68", "16.10", "13.25", "14.70"]
    row += ["--", "退還股款", "4155  ,20261005"]
    xunying = sources.InstrumentRecord("4155", "訊映", exchange="TWSE", industry="22")
    day = date(2026, 10, 6)
    quotes, bars = harness._session(
        day,
        [harness._twse_row("2330", "1000.00"), harness._twse_row("4155", "14.20")],
        [],
    )
    twse = _halt_capture("TWSE", lambda start, end: twse_payload(start, end, row), day)
    batch = sources.OfficialBatch(
        instruments=[harness.INDEX, harness.TSMC, xunying],
        bars=bars,
        chips=[],
        payloads=quotes + [twse[0]],
        data_as_of=day.isoformat(),
        snapshot_feeds=False,
        trading_halts=twse[1],
        trading_halt_windows=[twse[2]],
    )

    result = pipeline.collect(day, months_back=0, adapter=harness.FakeAdapter(batch))

    assert result["status"] == "success", result
    assert not [item for item in result["noncore_warnings"] if "4155" in item]
    with env() as db:
        halt = _halts(db)[("TWSE", "4155")]
        run = db.get(IngestionRun, result["run_id"])
    assert (halt.last_trade_date, halt.halt_start, halt.resume_date) == (
        date(2026, 10, 6),
        date(2026, 10, 7),
        date(2026, 10, 19),
    )
    assert halt.details_json["stated_last_trade_date"] == "2026-10-05"
    assert halt.details_json["last_trade_date_basis"] == "last_bar_before_resumption"
    assert run.metadata_json["trading_halts"]["TWSE"]["moved_past_bars"] == 1


class _HaltOutage:
    def __init__(self, fetcher):
        self.fetcher = fetcher
        self.calls = []

    def __call__(self, url, **kwargs):
        if url.startswith(
            (sources.TWSE_REDUCTION_ENDPOINT, sources.TPEX_REDUCTION_ENDPOINT)
        ):
            self.calls.append(url)
            raise sources.OfficialDataError(f"fixture outage {url}")
        return self.fetcher(url, **kwargs)


def test_the_adapters_ask_one_range_each_and_an_outage_is_noncore(
    tmp_path, monkeypatch
):
    from test_sources import FixtureFetcher

    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    fetcher = _HaltOutage(FixtureFetcher())
    adapter = sources.OfficialMarketDataAdapter(
        twse=sources.TwseAdapter(fetcher), tpex=sources.TpexAdapter(fetcher)
    )

    batch = adapter.fetch(date(2026, 9, 4), date(2026, 9, 4))

    assert fetcher.calls == [
        sources.reduction_query("TWSE", date(2026, 8, 25), date(2026, 11, 3)),
        sources.reduction_query("TPEx", date(2026, 8, 25), date(2026, 11, 3)),
    ]
    warnings = [item for item in batch.warnings if "trading halts" in item]
    assert len(warnings) == 2
    assert all(pipeline.NONCORE_WARNING_PATTERN.match(item) for item in warnings)
    assert batch.trading_halts == [] and batch.trading_halt_windows == []


# ---- coverage, the action summary and the stock page name the stop ----


def _weekdays(start: date, count: int) -> list[date]:
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


# 60 weekdays up to 2026-11-09, then the week after the resumption.
SESSIONS = _weekdays(date(2026, 8, 18), 60)
STOPPED = [date(2026, 11, 5), date(2026, 11, 6), date(2026, 11, 9)]
AFTER = _weekdays(date(2026, 11, 10), 10)  # 11/10 … 11/23


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'halts.db').as_posix()}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    make = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with make() as session:
        session.add(
            IngestionRun(
                run_type="collect",
                source="official",
                run_date=SESSIONS[-1],
                status="success",
                records=1,
                data_as_of=SESSIONS[-1].isoformat(),
                request_key="halts-fixture",
            )
        )
        session.flush()
        yield session
    engine.dispose()


def _instrument(db, symbol, *, kind="stock", exchange="TWSE"):
    row = Instrument(
        market="TW",
        exchange=exchange,
        symbol=symbol,
        name=symbol,
        instrument_type=kind,
        status="active",
    )
    db.add(row)
    db.flush()
    return row


def _bars(db, instrument, days):
    for day in days:
        db.add(
            MarketBar(
                instrument_id=instrument.id,
                trading_date=day,
                open=10,
                high=10,
                low=10,
                close=10,
                adj_close=10,
                volume=1000,
                turnover=10000,
                source="official-fixture",
            )
        )


def _halt(db, instrument, start, resume, last_trade=None):
    raw = RawPayload(
        source="twse",
        endpoint=sources.TWSE_REDUCTION_ENDPOINT,
        payload_path="fixture-halt.json",
        sha256="0" * 64,
        data_as_of=start.isoformat(),
        collected_at=datetime(2026, 11, 4, 13, 30),
    )
    db.add(raw)
    db.flush()
    db.add(
        TradingHalt(
            instrument_id=instrument.id,
            exchange=instrument.exchange,
            halt_start=start,
            resume_date=resume,
            last_trade_date=last_trade,
            reason="capital_reduction",
            reason_detail="退還股款",
            source="twse_twtauu",
            endpoint=sources.TWSE_REDUCTION_ENDPOINT,
            data_as_of=start.isoformat(),
            collected_at=raw.collected_at,
            raw_payload_id=raw.id,
            details_json={},
        )
    )


def _market(db, days):
    taiex = _instrument(db, "TAIEX", kind="index")
    _bars(db, taiex, days)
    full = _instrument(db, "2330")
    _bars(db, full, days)


def _summary(db, instrument, as_of):
    db.commit()
    db.info.clear()
    return build_decision_summary(db, instrument, as_of)


def _bar_reasons(coverage):
    return [item for item in coverage["coverage_reasons"] if item != "missing_chips"]


def test_the_stopped_sessions_are_named_not_called_unlisted(db):
    _market(db, SESSIONS)
    fuchi = _instrument(db, "3714")
    _bars(db, fuchi, [day for day in SESSIONS if day not in STOPPED])
    _halt(db, fuchi, date(2026, 11, 5), date(2026, 11, 16), date(2026, 11, 4))

    summary = _summary(db, fuchi, SESSIONS[-1])

    coverage = summary["coverage"]
    # The readiness is unchanged: a stopped session is still no bar.
    assert coverage["missing_bars_to_60"] == 3
    assert summary["action_state"] == "data_insufficient"
    assert _bar_reasons(coverage) == ["capital_reduction_halt"]
    assert coverage["halted_dates_to_60"] == [day.isoformat() for day in STOPPED]
    assert coverage["quote_not_listed_dates_to_60"] == []
    (period,) = coverage["halt_periods_to_60"]
    assert (period["first_session"], period["last_session"]) == (
        "2026-11-05",
        "2026-11-09",
    )
    assert period["resume_date"] == "2026-11-16"
    label = (
        "近 60 個交易日有 3 天減資換發新股停止買賣（2026/11/05 起，2026/11/16 恢復）"
    )
    assert summary["gap_reasons"][0] == {
        "code": "capital_reduction_halt",
        "label": label,
    }
    assert summary["primary_reason"]["label"] == label


def test_after_the_resumption_a_missing_bar_is_a_gap_again(db):
    days = SESSIONS + AFTER
    _market(db, days)
    fuchi = _instrument(db, "3714")
    stopped = STOPPED + AFTER[:4]  # 11/05 … 11/13
    late_gap = AFTER[-1]  # 11/23, a week after the resumption
    _bars(db, fuchi, [day for day in days if day not in stopped and day != late_gap])
    _halt(db, fuchi, date(2026, 11, 5), date(2026, 11, 16), date(2026, 11, 4))

    coverage = _summary(db, fuchi, days[-1])["coverage"]

    assert coverage["halted_dates_to_60"] == [day.isoformat() for day in stopped]
    assert coverage["quote_not_listed_dates_to_60"] == [late_gap.isoformat()]
    assert _bar_reasons(coverage) == ["capital_reduction_halt", "quote_not_listed"]


def test_the_coverage_report_counts_stopped_sessions_as_covered(db):
    _market(db, SESSIONS)
    fuchi = _instrument(db, "3714")
    _bars(db, fuchi, [day for day in SESSIONS if day not in STOPPED])
    _halt(db, fuchi, date(2026, 11, 5), date(2026, 11, 16), date(2026, 11, 4))
    gappy = _instrument(db, "GAPPY")
    _bars(db, gappy, [day for day in SESSIONS if day not in STOPPED])
    db.commit()

    report = backfill.coverage_report(db, SESSIONS[0], SESSIONS[-1])
    rows = {row["symbol"]: row for row in report["instrument_coverage"]}

    fuchi_row = rows["3714"]
    assert fuchi_row["missing_bars_to_20"] == 0
    assert fuchi_row["missing_bar_dates_to_60"] == []
    assert fuchi_row["halted_dates_to_20"] == [day.isoformat() for day in STOPPED]
    assert fuchi_row["bars_total"] == 57  # never turned into a price
    assert "capital_reduction_halt" in fuchi_row["coverage_reasons"]
    assert "missing_bar_dates" not in fuchi_row["coverage_reasons"]
    # Without a stop the same days are a gap.
    assert rows["GAPPY"]["missing_bars_to_20"] == 3
    assert report["summary"]["halted_to_20"] == 1
    assert report["summary"]["incomplete_to_20"] == 1
    assert report["summary"]["coverage_reason_counts"]["capital_reduction_halt"] == 1


def test_the_stock_page_says_the_stock_is_stopped_until_it_resumes(db):
    _market(db, SESSIONS + AFTER)
    fuchi = _instrument(db, "3714")
    _halt(db, fuchi, date(2026, 11, 5), date(2026, 11, 16), date(2026, 11, 4))
    db.commit()

    # By default the latest market session: 11/23, after the resumption.
    assert _stock_trading_halt(db, fuchi, None) is None
    halt = _stock_trading_halt(db, fuchi, date(2026, 11, 9))
    assert halt["reason_label"] == "減資換發新股"
    assert (halt["halt_start"], halt["resume_date"], halt["as_of"]) == (
        "2026-11-05",
        "2026-11-16",
        "2026-11-09",
    )
    assert _stock_trading_halt(db, fuchi, date(2026, 11, 13)) is not None
    assert _stock_trading_halt(db, fuchi, date(2026, 11, 16)) is None
    assert _stock_trading_halt(db, fuchi, date(2026, 11, 4)) is None


def test_the_stock_page_default_day_is_the_latest_market_session(db):
    _market(db, SESSIONS)  # up to 11/09, inside the stop
    fuchi = _instrument(db, "3714")
    _halt(db, fuchi, date(2026, 11, 5), date(2026, 11, 16), date(2026, 11, 4))
    db.commit()

    assert _stock_trading_halt(db, fuchi, None)["as_of"] == "2026-11-09"


def test_a_day_the_stock_traded_is_not_called_stopped(db):
    # TWSE's stated start can be a session early (2101, 4155); until a collect
    # moves it, the bar says the stock traded that day.
    _market(db, SESSIONS)
    fuchi = _instrument(db, "3714")
    _bars(db, fuchi, [date(2026, 11, 5)])
    _halt(db, fuchi, date(2026, 11, 5), date(2026, 11, 16), date(2026, 11, 4))
    db.commit()

    assert _stock_trading_halt(db, fuchi, date(2026, 11, 5)) is None
    assert _stock_trading_halt(db, fuchi, date(2026, 11, 6))["as_of"] == "2026-11-06"


# ---- worker.cli trading-halts ----


def test_the_cli_backfills_a_range_with_one_request_per_exchange(env):
    start, end = date(2024, 9, 1), date(2026, 11, 30)
    calls = []

    def fetcher(url, **_kwargs):
        calls.append(url)
        if url.startswith(sources.TWSE_REDUCTION_ENDPOINT):
            return twse_payload(start, end, TWSE_3714)
        return tpex_payload(start, end, TPEX_4534)

    with env() as db:
        for record in (FUCHI, CHINGTENG):
            db.add(
                Instrument(
                    market="TW",
                    exchange=record.exchange,
                    symbol=record.symbol,
                    name=record.name,
                    instrument_type="stock",
                    status="active",
                )
            )
        db.commit()

    result = trading_halts.run_trading_halts(start, end, fetcher=fetcher)

    assert result["status"] == "success", result
    assert calls == [
        sources.reduction_query("TWSE", start, end),
        sources.reduction_query("TPEx", start, end),
    ]
    assert result["records"] == 2
    with env() as db:
        halts = _halts(db)
        run = db.get(IngestionRun, result["run_id"])
        raws = db.scalars(select(RawPayload)).all()
    assert set(halts) == {("TWSE", "3714"), ("TPEx", "4534")}
    assert run.run_type == "trading_halts" and run.status == "success"
    # The day asked, not the end of the range (which can be in the future).
    assert {row.data_as_of for row in halts.values()} == {date.today().isoformat()}
    assert {raw.endpoint for raw in raws} == set(calls)

    again = trading_halts.run_trading_halts(start, end, fetcher=fetcher)
    assert again["records"] == 0
    assert again["exchanges"]["TWSE"]["unchanged"] == 1


def test_the_cli_reports_a_failed_exchange(env):
    start, end = date(2026, 11, 1), date(2026, 11, 30)

    def fetcher(url, **_kwargs):
        if url.startswith(sources.TWSE_REDUCTION_ENDPOINT):
            raise sources.OfficialDataError("fixture outage")
        return tpex_payload(start, end)

    result = trading_halts.run_trading_halts(start, end, fetcher=fetcher)

    assert result["status"] == "partial"
    assert result["exchanges"]["TWSE"]["failed"] == 0
    assert result["warnings"][0].startswith("TWSE trading halts unavailable")


# ---- migration 0030: the table, its identity and indexes ----


@pytest.mark.parametrize("entry", ["alembic", "fallback"])
def test_the_upgrade_adds_the_trading_halt_table(tmp_path, monkeypatch, entry):
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
            for row in connection.execute("PRAGMA table_info('trading_halts')")
        }
        indexes = {
            row[1]: [
                info[2] for info in connection.execute(f"PRAGMA index_info('{row[1]}')")
            ]
            for row in connection.execute("PRAGMA index_list('trading_halts')")
        }
        marker = (
            connection.execute("SELECT version_num FROM alembic_version").fetchall()
            if entry == "alembic"
            else connection.execute(
                "SELECT version FROM schema_migrations "
                "WHERE version = '0030_trading_halts'"
            ).fetchall()
        )
    assert columns == {
        "id": True,
        "instrument_id": True,
        "exchange": True,
        "halt_start": True,
        "resume_date": True,
        "last_trade_date": False,
        "reason": True,
        "reason_detail": False,
        "source": True,
        "endpoint": True,
        "data_as_of": True,
        "collected_at": True,
        "raw_payload_id": True,
        "details_json": True,
    }
    assert indexes["ix_trading_halts_halt_start"] == ["halt_start"]
    assert indexes["ix_trading_halts_resume_date"] == ["resume_date"]
    assert indexes["ix_trading_halts_raw_payload_id"] == ["raw_payload_id"]
    assert ["instrument_id", "source", "resume_date"] in indexes.values()
    assert marker == [
        (
            migration_revisions.REVISIONS[-1]
            if entry == "alembic"
            else "0030_trading_halts",
        )
    ]
