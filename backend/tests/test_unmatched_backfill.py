"""A new listing's first session, written from stored raw once its instrument exists (Issue #388).

TWSE 7710 listed on 2026-10-27 and TPEx 6938 traded on TPEx that day, but the
official lists carried neither until the next day.  The 10-27 collect recorded
their quote rows as ``unmatched_bar`` (#212); the 10-28 collect created the
instruments and nobody wrote the 10-27 bars.  The fixture rows below are the
exact rows of the production captures (raw_payloads 7842 and 7850).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import worker.instrument_repair as repair
import worker.pipeline as pipeline
import worker.sources as sources
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import (
    DataQuality,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
    TechnicalIndicator,
)
from worker.indicator_batch import compute_market_indicators

DAY1 = date(2026, 10, 27)
DAY2 = date(2026, 10, 28)
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
ROW_7710 = [
    "7710",
    "東擎科技",
    "1,496,730",
    "1,541",
    "191,331,712",
    "134.00",
    "135.00",
    "117.50",
    "128.50",
    "<p>X</p>",
    "0.00",
    "128.50",
    "1",
    "129.00",
    "7",
    "20.24",
]
ROW_6938 = [
    "6938",
    "藍新資訊",
    "79.90",
    "+11.90",
    "73.70",
    "80.00",
    "71.00",
    "75.01",
    "561,890",
    "42,145,468",
    "548",
    "79.80",
    "1",
    "79.90",
    "3",
    "14,640,000",
    "79.90",
    "9995.00",
    "0.01",
]


def _twse_row(code: str, close: str) -> list[str]:
    return [code, f"名稱{code}", "1,000", "10", "100,000", close, close, close] + [
        close,
        "+",
        "0.00",
        close,
        "1",
        close,
        "1",
        "10.00",
    ]


def _tpex_row(code: str, close: str) -> list[str]:
    return [code, f"名稱{code}", close, "0", close, close, close, close] + [
        "1,000",
        "80,000",
        "1",
        close,
        "1",
        close,
        "1",
        "1,000",
        close,
        close,
        close,
    ]


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'pipeline.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(repair, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    yield factory
    engine.dispose()


def _twse_quotes(day: date, rows: list[list[str]]) -> dict:
    return {
        "date": day.strftime("%Y%m%d"),
        "stat": "OK",
        "tables": [{"title": "每日收盤行情", "fields": TWSE_FIELDS, "data": rows}],
    }


def _tpex_quotes(day: date, rows: list[list[str]]) -> dict:
    return {
        "date": day.strftime("%Y%m%d"),
        "stat": "ok",
        "tables": [{"fields": TPEX_FIELDS, "data": rows}],
    }


def _session(day: date, twse_rows, tpex_rows):
    """The two quote captures of one session and the bars collect gets from them."""

    collected = datetime(day.year, day.month, day.day, 10, 30)  # 18:30 Taipei
    endpoint = (
        f"{sources.TWSE_DAILY_HISTORY_ENDPOINT}?date={day.strftime('%Y%m%d')}"
        "&type=ALLBUT0999&response=json"
    )
    twse = sources.capture_payload(
        "twse",
        endpoint,
        _twse_quotes(day, twse_rows),
        day.isoformat(),
        collected_at=collected,
    )
    tpex = sources.capture_payload(
        "tpex",
        sources.TPEX_HISTORY_API,
        _tpex_quotes(day, tpex_rows),
        day.isoformat(),
        collected_at=collected,
    )
    bars = sources.parse_twse_all_daily_payload(
        twse.payload,
        requested_date=day,
        data_as_of=day.isoformat(),
        payload_sha256=twse.sha256,
    ) + sources.parse_tpex_daily_rows(
        tpex.payload, data_as_of=day.isoformat(), payload_sha256=tpex.sha256
    )
    taiex = sources.BarRecord(
        symbol="TAIEX",
        trading_date=day,
        open=100,
        high=100,
        low=100,
        close=100,
        volume=0,
        turnover=0,
        exchange="TWSE",
        source="twse_index",
        data_as_of=day.isoformat(),
        payload_sha256=twse.sha256,
    )
    return [twse, tpex], [taiex, *bars]


INDEX = sources.InstrumentRecord(
    "TAIEX", "TAIEX", exchange="TWSE", instrument_type="index"
)
TSMC = sources.InstrumentRecord("2330", "台積電", exchange="TWSE", industry="24")
NEW_LISTINGS = [
    sources.InstrumentRecord(
        "7710",
        "東擎科技",
        exchange="TWSE",
        instrument_type="ipo",
        listing_date=DAY1,
        industry="25",
    ),
    sources.InstrumentRecord(
        "6938",
        "藍新資訊",
        exchange="TPEx",
        instrument_type="ipo",
        listing_date=date(2026, 10, 23),
        industry="30",
    ),
]


class FakeAdapter:
    def __init__(self, batch):
        self.batch = batch

    def fetch(self, start, end):
        return self.batch


def _collect(day: date, instruments, twse_rows, tpex_rows, *, earlier=None):
    """One collect of ``day``; ``earlier`` adds sessions to its batch (a range collect)."""

    payloads, bars = _session(day, twse_rows, tpex_rows)
    for other_day, other_twse, other_tpex in earlier or []:
        other_payloads, other_bars = _session(other_day, other_twse, other_tpex)
        payloads, bars = other_payloads + payloads, other_bars + bars
    batch = sources.OfficialBatch(
        instruments=instruments,
        bars=bars,
        chips=[],
        payloads=payloads,
        data_as_of=day.isoformat(),
        snapshot_feeds=False,
    )
    result = pipeline.collect(
        day, months_back=1 if earlier else 0, adapter=FakeAdapter(batch)
    )
    return result, payloads


def _first_session(**kwargs):
    """10-27: the lists lag, so 7710 and 6938 are recorded as unmatched_bar."""

    return _collect(
        DAY1,
        [INDEX, TSMC],
        kwargs.get("twse_rows", [_twse_row("2330", "1000.00"), ROW_7710]),
        [ROW_6938],
    )


def _second_session():
    """10-28: the lists now carry both listings."""

    return _collect(
        DAY2,
        [INDEX, TSMC, *NEW_LISTINGS],
        [_twse_row("2330", "1005.00"), _twse_row("7710", "130.00")],
        [_tpex_row("6938", "80.00")],
    )


def _second_session_without_backfill(monkeypatch):
    """10-28 as production ran it, before Issue #388."""

    with monkeypatch.context() as patch:
        patch.setattr(
            repair,
            "backfill_unmatched_bars",
            lambda db: {"rows_checked": 0, "written": [], "pending": []},
        )
        _second_session()


def _bar(db, exchange, symbol, day):
    return db.scalar(
        select(MarketBar)
        .join(Instrument, Instrument.id == MarketBar.instrument_id)
        .where(
            Instrument.exchange == exchange,
            Instrument.symbol == symbol,
            MarketBar.trading_date == day,
        )
    )


def _quality(db, key):
    return db.scalar(
        select(DataQuality).where(
            DataQuality.entity_type == "unmatched_bar",
            DataQuality.entity_key == key,
        )
    )


def _raw_id(db, capture) -> int:
    return db.scalar(select(RawPayload.id).where(RawPayload.sha256 == capture.sha256))


# ---- AC-1: the first session is written once the instrument exists ----


def test_the_next_collect_writes_the_first_session_from_the_stored_raw(env):
    first, (twse_capture, tpex_capture) = _first_session()
    assert {(item["exchange"], item["symbol"]) for item in first["unmatched_bars"]} == {
        ("TWSE", "7710"),
        ("TPEx", "6938"),
    }
    with env() as db:
        assert _bar(db, "TWSE", "7710", DAY1) is None
        twse_raw, tpex_raw = _raw_id(db, twse_capture), _raw_id(db, tpex_capture)

    second, _ = _second_session()

    assert second["status"] == "success"
    assert sorted(
        (item["symbol"], item["raw_payload_id"])
        for item in second["unmatched_backfill"]["written"]
    ) == [("6938", tpex_raw), ("7710", twse_raw)]
    assert second["unmatched_backfill"]["pending"] == []
    assert any(
        "unmatched_bar codes written from stored raw" in n for n in second["notices"]
    )
    with env() as db:
        bar = _bar(db, "TWSE", "7710", DAY1)
        assert (bar.open, bar.high, bar.low, bar.close) == (134.0, 135.0, 117.5, 128.5)
        assert bar.volume == 1_496_730
        assert bar.turnover == 191_331_712 and bar.turnover_status == "available"
        assert bar.source == "twse"
        assert bar.data_as_of == datetime(2026, 10, 27)
        assert bar.raw_payload_id == twse_raw
        tpex_bar = _bar(db, "TPEx", "6938", DAY1)
        assert (tpex_bar.open, tpex_bar.close, tpex_bar.volume) == (73.7, 79.9, 561_890)
        assert tpex_bar.source == "tpex" and tpex_bar.raw_payload_id == tpex_raw
        # The next session's bar is the collect's own row.
        assert _bar(db, "TWSE", "7710", DAY2).close == 130.0

        quality = _quality(db, "TWSE:7710")
        assert quality.as_of_date == DAY1
        assert quality.status == "complete"
        assert quality.missing_fields_json == []
        backfill = quality.checks_json["backfill"]
        assert backfill["version"] == repair.BACKFILL_VERSION
        assert backfill["written"] == [
            {"trading_date": "2026-10-27", "raw_payload_id": twse_raw}
        ]
        assert backfill["existing"] == [] and backfill["unavailable"] == []
        # What collect recorded on 10-27 is kept beside the backfill.
        assert quality.checks_json["raw_payload_ids"] == [twse_raw]
        assert quality.checks_json["trading_dates"] == ["2026-10-27"]


def test_a_code_still_without_an_instrument_is_left_as_recorded(env):
    _first_session(
        twse_rows=[_twse_row("2330", "1000.00"), ROW_7710, _twse_row("7867", "50.00")]
    )
    with env() as db:
        before = _quality(db, "TWSE:7867").checks_json

    second, _ = _second_session()

    assert "7867" not in {
        item["symbol"] for item in second["unmatched_backfill"]["written"]
    }
    with env() as db:
        quality = _quality(db, "TWSE:7867")
        assert quality.status == "missing"
        assert quality.checks_json == before
        assert db.scalar(select(Instrument).where(Instrument.symbol == "7867")) is None


# ---- AC-2: idempotent, never overwrites, a lost capture leaves the row open ----


def test_a_rerun_writes_nothing_again(env):
    _first_session()
    _second_session()
    with env() as db:
        bars = db.scalar(select(func.count(MarketBar.id)))
        checked = _quality(db, "TWSE:7710").checks_json

    with env() as db:
        again = repair.backfill_unmatched_bars(db)
        db.commit()

    assert again["written"] == [] and again["pending"] == []
    assert again["rows_checked"] == 0
    with env() as db:
        assert db.scalar(select(func.count(MarketBar.id))) == bars
        assert _quality(db, "TWSE:7710").checks_json == checked


def test_a_stored_bar_is_not_overwritten(env):
    _first_session()
    with env() as db:
        listing = Instrument(
            market="TW",
            exchange="TWSE",
            symbol="7710",
            name="東擎科技",
            instrument_type="ipo",
            status="active",
        )
        db.add(listing)
        db.flush()
        db.add(
            MarketBar(
                instrument_id=listing.id,
                trading_date=DAY1,
                open=1,
                high=1,
                low=1,
                close=1,
                adj_close=1,
                volume=1,
                source="manual",
            )
        )
        db.commit()

    with env() as db:
        result = repair.backfill_unmatched_bars(db)
        db.commit()

    assert [item["symbol"] for item in result["written"]] == []
    with env() as db:
        bar = _bar(db, "TWSE", "7710", DAY1)
        assert (bar.close, bar.volume, bar.source, bar.raw_payload_id) == (
            1,
            1,
            "manual",
            None,
        )
        quality = _quality(db, "TWSE:7710")
        assert quality.status == "complete"
        assert quality.checks_json["backfill"]["existing"] == ["2026-10-27"]
        assert quality.checks_json["backfill"]["written"] == []
        # 6938 has no instrument in this test and is left alone.
        assert _quality(db, "TPEx:6938").status == "missing"


@pytest.mark.parametrize(
    ("damage", "reason"),
    [
        (lambda path: path.unlink(), "raw_file_missing"),
        (lambda path: path.write_bytes(b'{"tampered": true}'), "raw_unreadable"),
    ],
    ids=["file_gone", "content_changed"],
)
def test_a_lost_capture_leaves_the_row_unmatched_and_writes_no_value(
    env, damage, reason
):
    _, (twse_capture, _tpex) = _first_session()
    damage(Path(twse_capture.payload_path))

    second, _ = _second_session()

    [pending] = second["unmatched_backfill"]["pending"]
    assert (pending["symbol"], pending["status"]) == ("7710", "missing")
    assert pending["unavailable"] == ["2026-10-27"]
    with env() as db:
        assert _bar(db, "TWSE", "7710", DAY1) is None
        # The other listing's capture is intact and is written.
        assert _bar(db, "TPEx", "6938", DAY1) is not None
        quality = _quality(db, "TWSE:7710")
        assert quality.status == "missing"
        assert quality.missing_fields_json == ["raw_payload"]
        [unavailable] = quality.checks_json["backfill"]["unavailable"]
        assert unavailable["trading_date"] == "2026-10-27"
        assert unavailable["raws"][0]["reason"].startswith(reason)

    # Still open: the next run tries again and still writes nothing.
    with env() as db:
        again = repair.backfill_unmatched_bars(db)
        db.commit()
        assert again["written"] == [] and again["rows_checked"] == 1
        assert _bar(db, "TWSE", "7710", DAY1) is None
        assert _quality(db, "TWSE:7710").status == "missing"


def test_the_same_code_on_the_other_exchange_is_not_written(env):
    _first_session()
    with env() as db:
        db.add(
            Instrument(
                market="TW",
                exchange="TPEx",
                symbol="7710",
                name="上櫃 7710",
                instrument_type="stock",
                status="transferred",
            )
        )
        db.commit()
        before = _quality(db, "TWSE:7710").checks_json

    with env() as db:
        result = repair.backfill_unmatched_bars(db)
        db.commit()

    assert result == {
        "version": repair.BACKFILL_VERSION,
        "rows_checked": 0,
        "written": [],
        "pending": [],
        "chips_checked": 0,
        "chips_written": [],
        "chips_pending": [],
    }
    with env() as db:
        assert _bar(db, "TPEx", "7710", DAY1) is None
        quality = _quality(db, "TWSE:7710")
        assert quality.status == "missing" and quality.checks_json == before


def test_each_date_of_a_row_is_written_from_its_own_capture(env):
    # A range collect records one row with two sessions and two captures.
    DAY3 = date(2026, 10, 29)
    first, payloads = _collect(
        DAY2,
        [INDEX, TSMC],
        [_twse_row("2330", "1005.00"), _twse_row("7710", "130.00")],
        [],
        earlier=[(DAY1, [_twse_row("2330", "1000.00"), ROW_7710], [])],
    )
    day1_capture, day2_capture = payloads[0], payloads[2]
    with env() as db:
        quality = _quality(db, "TWSE:7710")
        day1_raw, day2_raw = _raw_id(db, day1_capture), _raw_id(db, day2_capture)
    assert quality.as_of_date == DAY2
    assert quality.checks_json["trading_dates"] == ["2026-10-27", "2026-10-28"]
    assert quality.checks_json["raw_payload_ids"] == [day1_raw, day2_raw]

    third, _ = _collect(
        DAY3,
        [INDEX, TSMC, *NEW_LISTINGS],
        [_twse_row("2330", "1010.00"), _twse_row("7710", "131.00")],
        [],
    )

    assert [
        (item["trading_date"], item["raw_payload_id"])
        for item in third["unmatched_backfill"]["written"]
    ] == [("2026-10-27", day1_raw), ("2026-10-28", day2_raw)]
    with env() as db:
        first_bar, second_bar = (
            _bar(db, "TWSE", "7710", DAY1),
            _bar(db, "TWSE", "7710", DAY2),
        )
        assert (first_bar.close, first_bar.volume) == (128.5, 1_496_730)
        assert first_bar.raw_payload_id == day1_raw
        assert (second_bar.close, second_bar.volume) == (130.0, 1000)
        assert second_bar.raw_payload_id == day2_raw
        assert _quality(db, "TWSE:7710").status == "complete"


# ---- a backfill error never fails the day's collect ----


def test_a_capture_the_parser_chokes_on_keeps_only_its_row_open(env, monkeypatch):
    _first_session()

    def broken(raw, payload):
        raise KeyError("收盤價")

    with monkeypatch.context() as patch:
        patch.setattr(repair, "_quote_bars", broken)
        second, _ = _second_session()

    assert second["status"] == "success"
    assert second["unmatched_backfill"]["status"] == "success"
    assert {item["symbol"] for item in second["unmatched_backfill"]["pending"]} == {
        "7710",
        "6938",
    }
    with env() as db:
        # The day's own quotes are written.
        assert _bar(db, "TWSE", "7710", DAY2).close == 130.0
        assert _bar(db, "TWSE", "2330", DAY2).close == 1005.0
        assert _bar(db, "TWSE", "7710", DAY1) is None
        quality = _quality(db, "TWSE:7710")
        assert quality.status == "missing"
        [unavailable] = quality.checks_json["backfill"]["unavailable"]
        assert unavailable["raws"][0]["reason"].startswith("raw_unparsed: KeyError")


def test_a_failing_backfill_drops_only_its_own_writes(env, monkeypatch):
    _first_session()

    def broken(*args, **kwargs):
        raise RuntimeError("data_quality write failed")

    with monkeypatch.context() as patch:
        # Fails after the first bar of the backfill was staged.
        patch.setattr(repair, "_upsert_quality", broken)
        second, _ = _second_session()

    assert second["status"] == "success"
    backfill = second["unmatched_backfill"]
    assert backfill["status"] == "failed"
    assert backfill["error"] == "RuntimeError: data_quality write failed"
    assert backfill["written"] == []
    assert any("unmatched_bar backfill failed" in n for n in second["notices"])
    with env() as db:
        assert _bar(db, "TWSE", "7710", DAY2).close == 130.0
        assert _bar(db, "TPEx", "6938", DAY2) is not None
        assert _bar(db, "TWSE", "7710", DAY1) is None
        assert _bar(db, "TPEx", "6938", DAY1) is None
        for key in ("TWSE:7710", "TPEx:6938"):
            quality = _quality(db, key)
            assert quality.status == "missing"
            assert "backfill" not in quality.checks_json
        run = db.scalar(select(IngestionRun).where(IngestionRun.id == second["run_id"]))
        assert run.status == "success"
        assert run.metadata_json["unmatched_backfill"]["status"] == "failed"

    # The rows stay open, so the next run writes them.
    with env() as db:
        assert len(repair.backfill_unmatched_bars(db)["written"]) == 2
        db.commit()
        assert _bar(db, "TWSE", "7710", DAY1).close == 128.5


# ---- indicators are recomputed from the first session ----


def test_the_indicators_are_rewritten_from_the_first_session(env, monkeypatch):
    # The production state: the 10-28 collect created the instruments without
    # writing 10-27, and the indicator batch ran on that.
    _first_session()
    _second_session_without_backfill(monkeypatch)
    with env() as db:
        compute_market_indicators(db, as_of=DAY2)
        db.commit()
        listing = db.scalar(select(Instrument).where(Instrument.symbol == "7710"))
        assert db.scalars(
            select(TechnicalIndicator.trading_date).where(
                TechnicalIndicator.instrument_id == listing.id
            )
        ).all() == [DAY2]

    with env() as db:
        assert len(repair.backfill_unmatched_bars(db)["written"]) == 2
        db.commit()
    with env() as db:
        result = compute_market_indicators(db, as_of=DAY2)
        db.commit()
        rows = db.scalars(
            select(TechnicalIndicator)
            .where(TechnicalIndicator.instrument_id == listing.id)
            .order_by(TechnicalIndicator.trading_date)
        ).all()
    assert result["instruments_rewritten"] == 2
    assert [(row.trading_date, row.bar_count) for row in rows] == [
        (DAY1, 1),
        (DAY2, 2),
    ]


# ---- the CLI entry: dry-run by default ----


def test_the_cli_entry_is_a_dry_run_unless_applied(env, monkeypatch):
    _first_session()
    _second_session_without_backfill(monkeypatch)

    dry = repair.run_unmatched_backfill()
    assert dry["status"] == "dry_run" and len(dry["written"]) == 2
    with env() as db:
        assert _bar(db, "TWSE", "7710", DAY1) is None
        assert _quality(db, "TWSE:7710").status == "missing"

    applied = repair.run_unmatched_backfill(apply=True)
    assert applied["status"] == "applied" and len(applied["written"]) == 2
    with env() as db:
        assert _bar(db, "TWSE", "7710", DAY1).close == 128.5

    assert repair.run_unmatched_backfill(apply=True)["status"] == "no_change"
