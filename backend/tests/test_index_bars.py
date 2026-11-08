"""Real index daily K bars: parsing, the TAIEX in-place upgrade, the TPEx index rows (Issue #552).

Payload shapes: ``index_bar_payloads`` (the 2026-11-08 captures).  AC-2: real
open/high/low/close and volume are written; a missing open/high/low stays
empty instead of the close; what reads only the TAIEX close (the session
basis, the group benchmark returns) does not change.
"""

from __future__ import annotations

import socket
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import index_bar_payloads as payloads
from app import coverage
from app.db import enable_sqlite_foreign_keys
from app.indicators import (
    MISSING_OHLC,
    MISSING_VOLUME,
    SYNTHETIC_INDEX,
    IndicatorBar,
    aggregate_weekly,
    compute_indicators,
)
from app.migrations import upgrade_database
from app.models import (
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
    TechnicalFeature,
    TechnicalIndicator,
)
from test_daily_schedule import CodedFetcher, combined
from worker import index_bars as ib
from worker import pipeline, sources
from worker.sources import BarRecord, OfficialDataError

OCT = ib.Month(2026, 10)
OCT_FIRST = date(2026, 10, 1)


@pytest.fixture(autouse=True)
def no_network(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in index bar tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'index.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    made = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield made
    engine.dispose()


# --- parsing ------------------------------------------------------------------


def test_twse_reports_give_points_shares_and_amounts():
    prices = ib.parse_twse_prices(
        payloads.twse_prices(
            OCT_FIRST,
            [(date(2026, 10, 1), 22329.65, 22446.86, 22311.33, 22390.39)],
        ),
        OCT,
    )
    volumes = ib.parse_twse_volumes(
        payloads.twse_volumes(
            OCT_FIRST, [(date(2026, 10, 1), 6546005974, 286364609840, 22390.39)]
        ),
        OCT,
    )

    assert prices == [
        ib.PriceRow(date(2026, 10, 1), 22329.65, 22446.86, 22311.33, 22390.39)
    ]
    assert volumes == [ib.VolumeRow(date(2026, 10, 1), 6546005974, 286364609840.0)]


@pytest.mark.parametrize("field", ["成交股數（仟股）", "成交張數"])
def test_both_tpex_volume_labels_are_thousand_shares(field):
    rows = ib.parse_tpex_volumes(
        payloads.tpex_volumes(
            OCT_FIRST,
            [(date(2026, 10, 1), 887960, 97634980, 270.28)],
            volume_field=field,
        ),
        OCT,
    )

    assert rows == [ib.VolumeRow(date(2026, 10, 1), 887_960_000, 97_634_980_000.0)]


def test_an_unknown_tpex_volume_label_rejects_the_month():
    payload = payloads.tpex_volumes(
        OCT_FIRST, [(date(2026, 10, 1), 1, 1, 270.0)], volume_field="成交量（股）"
    )

    with pytest.raises(OfficialDataError, match="volume field"):
        ib.parse_tpex_volumes(payload, OCT)


def test_a_row_of_another_month_rejects_the_report():
    payload = payloads.tpex_prices(
        OCT_FIRST, [(date(2026, 9, 30), 268.0, 270.0, 267.0, 269.0)]
    )

    with pytest.raises(OfficialDataError, match="outside 2026-10"):
        ib.parse_tpex_prices(payload, OCT)


def test_a_report_answering_another_month_is_rejected():
    payload = payloads.twse_prices(date(2026, 9, 1), [])

    with pytest.raises(OfficialDataError, match="reported date"):
        ib.parse_twse_prices(payload, OCT)


def test_a_missing_or_inconsistent_open_high_low_is_left_empty_with_a_reason():
    twse = ib.parse_twse_prices(
        payloads.twse_prices(
            OCT_FIRST, [(date(2026, 10, 1), None, 22446.86, 22311.33, 22390.39)]
        ),
        OCT,
    )
    tpex = ib.parse_tpex_prices(
        payloads.tpex_prices(
            OCT_FIRST, [(date(2026, 10, 1), 268.89, 269.00, 268.70, 270.28)]
        ),
        OCT,
    )

    assert twse == [
        ib.PriceRow(
            date(2026, 10, 1), None, None, None, 22390.39, ib.SOURCE_MISSING_OHLC
        )
    ]
    # The high (269.00) is below the close (270.28): not the close, empty.
    assert tpex == [
        ib.PriceRow(date(2026, 10, 1), None, None, None, 270.28, ib.SOURCE_INVALID_OHLC)
    ]


def test_explicit_no_data_answers_give_no_rows():
    for endpoint, parse in (
        (sources.TWSE_INDEX_HISTORY_ENDPOINT, ib.parse_twse_prices),
        (sources.TWSE_MARKET_TRADING_ENDPOINT, ib.parse_twse_volumes),
    ):
        assert parse(payloads.empty_report(f"{endpoint}?date=20261001"), OCT) == []
    form = {"date": "2026/10/01"}
    assert (
        ib.parse_tpex_prices(
            payloads.empty_report(sources.TPEX_INDEX_HISTORY_ENDPOINT, form), OCT
        )
        == []
    )
    assert (
        ib.parse_tpex_volumes(
            payloads.empty_report(sources.TPEX_INDEX_TRADING_ENDPOINT, form), OCT
        )
        == []
    )


def test_a_day_the_volume_report_left_out_has_no_volume():
    bars = ib.build_bars(
        "TPEx",
        [
            ib.PriceRow(date(2026, 10, 1), 268.89, 270.72, 268.70, 270.28),
            ib.PriceRow(date(2026, 10, 2), 270.25, 270.26, 266.92, 267.72),
        ],
        [ib.VolumeRow(date(2026, 10, 1), 887_960_000, 97_634_980_000.0)],
        price_sha256="p",
        volume_sha256="v",
    )

    assert [(bar.volume, bar.volume_sha256) for bar in bars] == [
        (887_960_000, "v"),
        (None, None),
    ]


# --- writing ------------------------------------------------------------------

DAYS = [date(2026, 10, 1) + timedelta(days=offset) for offset in range(40)]
SESSIONS = [day for day in DAYS if day.weekday() < 5][:25]


def _close(index: int) -> float:
    return round(22000 + 37.5 * index + (index % 3) * 11.25, 2)


def _seed_taiex(db, sessions=SESSIONS) -> Instrument:
    """TAIEX close-only rows as collect writes them, each from an MI_INDEX raw of an official collect."""
    taiex = Instrument(
        market="TW",
        exchange="TWSE",
        symbol="TAIEX",
        name="TAIEX",
        instrument_type="index",
        industry="Index",
        status="active",
    )
    db.add(taiex)
    db.flush()
    for index, day in enumerate(sessions):
        run = IngestionRun(
            run_type="collect",
            source="official",
            run_date=day,
            status="success",
            records=1,
            started_at=datetime(2026, 11, 1),
            metadata_json={"taiex_records": 1},
        )
        db.add(run)
        db.flush()
        raw = RawPayload(
            ingestion_run_id=run.id,
            source="twse",
            endpoint=f"{sources.TWSE_DAILY_HISTORY_ENDPOINT}?date={day:%Y%m%d}",
            sha256=f"mi{index:03d}",
            data_as_of=day.isoformat(),
            collected_at=datetime(2026, 11, 1),
        )
        db.add(raw)
        db.flush()
        close = _close(index)
        db.add(
            MarketBar(
                instrument_id=taiex.id,
                trading_date=day,
                open=close,
                high=close,
                low=close,
                close=close,
                adj_close=close,
                volume=0,
                turnover=0.0,
                turnover_status="unavailable",
                turnover_reason="synthetic_index",
                source="twse_index",
                data_as_of=datetime.combine(day, datetime.min.time()),
                raw_payload_id=raw.id,
            )
        )
    db.flush()
    return taiex


def _real_rows(sessions=SESSIONS, *, close_shift=0.0):
    """(day, open, high, low, close) and (day, shares, amount, close) for the sessions."""
    prices, volumes = [], []
    for index, day in enumerate(sessions):
        close = round(_close(index) + close_shift, 2)
        prices.append((day, close - 40.0, close + 55.5, close - 80.25, close))
        volumes.append((day, 9_000_000_000 + index, 400_000_000_000 + index, close))
    return prices, volumes


class ReportGet:
    """``get`` for backfill_index_bars: the four reports per month, from rows; records requests."""

    def __init__(self, twse, tpex, *, fail=()):
        self.twse, self.tpex = twse, tpex
        self.fail = set(fail)
        self.requests: list[tuple[str, str, str]] = []

    def __call__(self, request):
        month = payloads.requested_month(request.url, request.data)
        self.requests.append((request.exchange, request.kind, f"{month:%Y-%m}"))
        if (request.exchange, request.kind) in self.fail:
            raise OfficialDataError("fixture outage")
        prices, volumes = self.twse if request.exchange == "TWSE" else self.tpex
        in_month = [
            row
            for row in (prices if request.kind == "price" else volumes)
            if (row[0].year, row[0].month) == (month.year, month.month)
        ]
        if request.exchange == "TWSE":
            build = (
                payloads.twse_prices
                if request.kind == "price"
                else payloads.twse_volumes
            )
            return (
                build(month, in_month)
                if in_month
                else {"stat": "很抱歉，沒有符合條件的資料!"}
            )
        build = (
            payloads.tpex_prices if request.kind == "price" else payloads.tpex_volumes
        )
        return build(month, in_month)


def _tpex_rows(sessions=SESSIONS):
    prices = [
        (day, 260.0 + i, 262.5 + i, 259.0 + i, 261.25 + i)
        for i, day in enumerate(sessions)
    ]
    volumes = [
        (day, 900_000 + i, 100_000_000 + i, 261.25 + i)
        for i, day in enumerate(sessions)
    ]
    return prices, volumes


def _backfill(factory, get, **kwargs):
    sleeps: list[float] = []
    with factory() as db:
        result = ib.backfill_index_bars(
            db,
            first=ib.Month(2026, 10),
            last=ib.Month(2026, 11),
            get=get,
            sleep=sleeps.append,
            today=date(2026, 11, 8),
            **kwargs,
        )
    return result, sleeps


def _bars(db, exchange, symbol):
    instrument = db.scalar(
        select(Instrument).where(
            Instrument.exchange == exchange, Instrument.symbol == symbol
        )
    )
    return db.scalars(
        select(MarketBar)
        .where(MarketBar.instrument_id == instrument.id)
        .order_by(MarketBar.trading_date)
    ).all()


def test_backfill_upgrades_taiex_in_place_and_writes_tpex_rows(factory):
    with factory() as db:
        _seed_taiex(db)
        db.commit()
    get = ReportGet(_real_rows(), _tpex_rows())

    result, sleeps = _backfill(factory, get)

    assert result["status"] == "success", result
    # Two months, two exchanges, two reports each, 3 seconds apart.
    assert len(get.requests) == 8 and sleeps == [3.0] * 7
    assert result["counts"]["upgraded"] == len(SESSIONS)
    assert result["counts"]["inserted"] == len(SESSIONS)
    with factory() as db:
        run = db.get(IngestionRun, result["run_id"])
        assert (run.run_type, run.source) == ("index_bar_backfill", "official")
        taiex = _bars(db, "TWSE", "TAIEX")
        prices, volumes = _real_rows()
        assert [(b.open, b.high, b.low, b.close) for b in taiex] == [
            row[1:] for row in prices
        ]
        assert [(b.volume, b.turnover, b.turnover_status) for b in taiex] == [
            (row[1], float(row[2]), "available") for row in volumes
        ]
        assert {b.source for b in taiex} == {"twse_index_ohlcv"}
        assert all(b.price_reason is None for b in taiex)
        first = taiex[0]
        price_raw = db.get(RawPayload, first.raw_payload_id)
        volume_raw = db.get(RawPayload, first.volume_raw_payload_id)
        assert "MI_5MINS_HIST" in price_raw.endpoint and "FMTQIK" in volume_raw.endpoint
        assert price_raw.ingestion_run_id == volume_raw.ingestion_run_id == run.id
        # The old source and raw of every upgraded row are recorded.
        upgraded = run.metadata_json["upgraded_rows"]
        assert len(upgraded) == len(SESSIONS)
        assert upgraded[0]["old_source"] == "twse_index"
        old_raw = db.get(RawPayload, upgraded[0]["old_raw_payload_id"])
        assert "MI_INDEX" in old_raw.endpoint
        # Only the stored sessions: no new TAIEX day.
        assert len(taiex) == len(SESSIONS)
        tpex = _bars(db, "TPEx", "TPEX")
        instrument = db.get(Instrument, tpex[0].instrument_id)
        assert (instrument.instrument_type, instrument.name) == ("index", "櫃買指數")
        assert [(b.open, b.high, b.low, b.close) for b in tpex] == [
            row[1:] for row in _tpex_rows()[0]
        ]
        assert tpex[0].volume == 900_000_000 and tpex[0].turnover == 100_000_000_000.0
        # Indicators are rebuilt for both, as for stocks, with real KD.
        for bars in (taiex, tpex):
            rows = db.scalars(
                select(TechnicalIndicator).where(
                    TechnicalIndicator.instrument_id == bars[0].instrument_id
                )
            ).all()
            assert len(rows) == len(bars)
            last = max(rows, key=lambda row: row.trading_date)
            assert last.kd_k is not None and last.vol_ma20 is not None

    # A rerun changes nothing.
    again, _ = _backfill(factory, ReportGet(_real_rows(), _tpex_rows()))
    assert again["counts"]["unchanged"] == 2 * len(SESSIONS)
    assert again["counts"]["upgraded"] == again["counts"]["inserted"] == 0


def test_sessions_before_the_history_start_are_not_written(factory):
    days = [date(2023, 8, 30), date(2023, 8, 31), date(2023, 9, 1)]
    get = ReportGet(([], []), _tpex_rows(days))
    with factory() as db:
        result = ib.backfill_index_bars(
            db,
            first=ib.Month(2023, 8),
            last=ib.Month(2023, 9),
            get=get,
            sleep=lambda _: None,
            today=date(2023, 10, 5),
        )

    assert ib.HISTORY_START == date(2023, 9, 1)
    assert result["counts"]["inserted"] == 1
    with factory() as db:
        tpex = _bars(db, "TPEx", "TPEX")
        assert [b.trading_date for b in tpex] == [date(2023, 9, 1)]
        run = db.get(IngestionRun, result["run_id"])
        assert (
            run.metadata_json["coverage_manifest"]["2023-08:TPEx"][
                "before_history_start"
            ]
            == 2
        )
        # The features are rebuilt with the indicators, as analyze writes them.
        assert (
            db.scalar(
                select(func.count())
                .select_from(TechnicalFeature)
                .where(TechnicalFeature.instrument_id == tpex[0].instrument_id)
            )
            == 1
        )


def test_a_differing_close_is_not_upgraded(factory):
    with factory() as db:
        _seed_taiex(db)
        db.commit()

    result, _ = _backfill(
        factory, ReportGet(_real_rows(close_shift=0.01), _tpex_rows())
    )

    assert result["status"] == "partial"
    assert result["counts"]["close_mismatch"] == len(SESSIONS)
    assert result["counts"]["upgraded"] == 0
    with factory() as db:
        assert {b.source for b in _bars(db, "TWSE", "TAIEX")} == {"twse_index"}


def test_a_taiex_day_without_a_stored_row_is_not_inserted(factory):
    with factory() as db:
        _seed_taiex(db, SESSIONS[1:])
        db.commit()

    result, _ = _backfill(factory, ReportGet(_real_rows(SESSIONS), _tpex_rows()))

    assert result["skipped_dates"]["TWSE:no_close_row"] == [SESSIONS[0].isoformat()]
    with factory() as db:
        assert len(_bars(db, "TWSE", "TAIEX")) == len(SESSIONS) - 1


BASIS = coverage.SESSION_BASIS_START
# The stock history starts 2024-09-30; the index history about a year earlier.
BASIS_SESSIONS = [
    day
    for day in (BASIS + timedelta(days=offset) for offset in range(30))
    if day.weekday() < 5
]
PRE_SESSIONS = [
    day
    for day in (date(2024, 8, 1) + timedelta(days=offset) for offset in range(60))
    if day.weekday() < 5 and day < BASIS
]


def _history_rows():
    """Reports for 2024-08..2024-10: earlier sessions, then the seeded ones."""
    pre_prices = [
        (day, 21000.0 + i, 21060.0 + i, 20950.0 + i, 21010.0 + i)
        for i, day in enumerate(PRE_SESSIONS)
    ]
    pre_volumes = [
        (day, 8_000_000_000 + i, 300_000_000_000 + i, 21010.0 + i)
        for i, day in enumerate(PRE_SESSIONS)
    ]
    prices, volumes = _real_rows(BASIS_SESSIONS)
    return pre_prices + prices, pre_volumes + volumes


def _history_backfill(factory):
    with factory() as db:
        return ib.backfill_index_bars(
            db,
            first=ib.Month(2024, 8),
            last=ib.Month(2024, 10),
            get=ReportGet(_history_rows(), _tpex_rows(PRE_SESSIONS + BASIS_SESSIONS)),
            sleep=lambda _: None,
            today=date(2024, 11, 8),
        )


def test_taiex_history_before_the_stock_history_is_inserted_but_never_a_session(
    factory,
):
    with factory() as db:
        taiex = _seed_taiex(db, BASIS_SESSIONS)
        db.commit()
        before = coverage.verified_taiex_sessions(db)

    result = _history_backfill(factory)

    assert result["status"] == "success", result
    assert result["counts"]["upgraded"] == len(BASIS_SESSIONS)
    # The TAIEX days before 2024-09-30 have no MI_INDEX row to upgrade: inserted.
    assert result["counts"]["inserted"] == len(PRE_SESSIONS) + len(
        PRE_SESSIONS + BASIS_SESSIONS
    )
    with factory() as db:
        bars = _bars(db, "TWSE", "TAIEX")
        assert [b.trading_date for b in bars] == PRE_SESSIONS + BASIS_SESSIONS
        assert {b.source for b in bars} == {"twse_index_ohlcv"}
        assert all(
            "MI_5MINS_HIST" in db.get(RawPayload, b.raw_payload_id).endpoint
            for b in bars
        )
        # The session basis is still the stocks': only the seeded MI_INDEX days.
        assert before == BASIS_SESSIONS
        assert coverage.verified_taiex_sessions(db) == BASIS_SESSIONS
        assert coverage.verified_taiex_sessions(db, limit=20) == BASIS_SESSIONS[-20:]
        # The stocks' first day now has the index's longer averages.
        first_day = db.scalar(
            select(TechnicalIndicator).where(
                TechnicalIndicator.instrument_id == taiex.id,
                TechnicalIndicator.trading_date == BASIS,
            )
        )
        assert first_day.ma20 is not None
        assert len(PRE_SESSIONS) + 1 < 60 and first_day.ma60 is None
    # A rerun changes nothing.
    again = _history_backfill(factory)
    assert again["counts"]["unchanged"] == 2 * len(PRE_SESSIONS + BASIS_SESSIONS)


def test_the_collect_still_inserts_no_taiex_day(factory):
    """Only the backfill adds TAIEX history: collect keeps MI_INDEX as the basis."""
    bars = ib.build_bars(
        "TWSE",
        [ib.PriceRow(PRE_SESSIONS[0], 1.0, 3.0, 0.5, 2.0)],
        None,
        price_sha256="p",
        volume_sha256=None,
    )
    with factory() as db:
        _seed_taiex(db, BASIS_SESSIONS)
        result = ib.store_index_bars(db, bars, lambda _sha: 1)

    assert result.counts["no_close_row"] == 1 and result.counts["inserted"] == 0


def test_a_failed_volume_report_leaves_volume_empty_until_a_later_read(factory):
    with factory() as db:
        _seed_taiex(db)
        db.commit()

    first, _ = _backfill(
        factory, ReportGet(_real_rows(), _tpex_rows(), fail={("TPEx", "volume")})
    )

    assert first["status"] == "partial"
    with factory() as db:
        tpex = _bars(db, "TPEx", "TPEX")
        assert {(b.volume, b.turnover_status, b.turnover_reason) for b in tpex} == {
            (None, "unavailable", "missing")
        }
        assert all(b.volume_raw_payload_id is None for b in tpex)
        indicator = db.scalar(
            select(TechnicalIndicator)
            .where(TechnicalIndicator.instrument_id == tpex[0].instrument_id)
            .order_by(TechnicalIndicator.trading_date.desc())
        )
        assert indicator.vol_ma5 is None
        assert indicator.null_reasons["vol_ma5"] == MISSING_VOLUME
        assert indicator.kd_k is not None and indicator.ma20 is not None

    second, _ = _backfill(factory, ReportGet(_real_rows(), _tpex_rows()))

    assert second["counts"]["filled"] == len(SESSIONS)
    with factory() as db:
        tpex = _bars(db, "TPEx", "TPEX")
        assert tpex[0].volume == 900_000_000
        assert tpex[0].turnover_status == "available"
        assert tpex[0].volume_raw_payload_id is not None


def test_a_missing_open_high_low_is_stored_empty_not_as_the_close(factory):
    with factory() as db:
        _seed_taiex(db)
        db.commit()
    prices, volumes = _real_rows()
    prices[3] = (prices[3][0], None, None, None, prices[3][4])

    _backfill(factory, ReportGet((prices, volumes), _tpex_rows()))

    with factory() as db:
        day = _bars(db, "TWSE", "TAIEX")[3]
        assert (day.open, day.high, day.low) == (None, None, None)
        assert day.close == prices[3][4]
        assert day.price_reason == "source_missing_ohlc"
        assert day.source == "twse_index_ohlcv"
        last = db.scalar(
            select(TechnicalIndicator)
            .where(TechnicalIndicator.instrument_id == day.instrument_id)
            .order_by(TechnicalIndicator.trading_date.desc())
        )
        # KD reads every high/low since the first bar; the close fields do not.
        assert last.kd_k is None and last.null_reasons["kd_k"] == MISSING_OHLC
        assert last.ma20 is not None and last.vol_ma5 is not None


def test_the_backfill_refuses_a_month_after_the_current_one(factory):
    with factory() as db, pytest.raises(ValueError, match="after the current month"):
        ib.backfill_index_bars(
            db,
            first=ib.Month(2026, 11),
            last=ib.Month(2026, 12),
            get=ReportGet(([], []), ([], [])),
            sleep=lambda _: None,
            today=date(2026, 11, 8),
        )
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(IngestionRun)) == 0


def test_a_close_only_mi_index_row_never_replaces_a_real_bar(factory):
    with factory() as db:
        _seed_taiex(db)
        db.commit()
    _backfill(factory, ReportGet(_real_rows(), _tpex_rows()))
    with factory() as db:
        taiex = db.scalar(select(Instrument).where(Instrument.symbol == "TAIEX"))
        day = SESSIONS[0]
        close = _close(0)
        conflicts: list = []
        for overwrite in (False, True):
            pipeline._upsert_official_bar(
                db,
                taiex,
                BarRecord(
                    symbol="TAIEX",
                    trading_date=day,
                    open=close,
                    high=close,
                    low=close,
                    close=close + (1 if overwrite else 0),
                    adj_close=close,
                    volume=0,
                    turnover=0.0,
                    turnover_status="unavailable",
                    turnover_reason="synthetic_index",
                    exchange="TWSE",
                    source="twse_index",
                ),
                None,
                overwrite=overwrite,
                conflicts=conflicts,
            )
        bar = _bars(db, "TWSE", "TAIEX")[0]
        assert bar.source == "twse_index_ohlcv"
        assert bar.open == _real_rows()[0][0][1]
        assert [item["field"] for item in conflicts] == ["close"]


# --- what reads only the TAIEX close ------------------------------------------


def test_the_session_basis_and_benchmark_returns_do_not_change(factory):
    with factory() as db:
        taiex = _seed_taiex(db)
        db.commit()
        score_date = SESSIONS[-1]
        before = (
            coverage.verified_taiex_sessions(db),
            pipeline._returns_by_window(db, taiex.id, score_date),
            pipeline._effective_trading_dates(db, taiex.id, score_date, 20),
            coverage.has_backfill_manifest(db),
        )

    _backfill(factory, ReportGet(_real_rows(), _tpex_rows()))

    with factory() as db:
        assert {b.source for b in _bars(db, "TWSE", "TAIEX")} == {"twse_index_ohlcv"}
        after = (
            coverage.verified_taiex_sessions(db),
            pipeline._returns_by_window(db, taiex.id, score_date),
            pipeline._effective_trading_dates(db, taiex.id, score_date, 20),
            coverage.has_backfill_manifest(db),
        )
    assert before[0] == SESSIONS
    assert after == before
    # The index_bar_backfill run is not a bounded-backfill manifest.
    assert after[3] is False


def _basis(db, taiex_id):
    """What reads only the TAIEX close: the sessions, benchmark returns and window."""
    score_date = SESSIONS[-1]
    return (
        coverage.verified_taiex_sessions(db),
        pipeline._returns_by_window(db, taiex_id, score_date),
        pipeline._effective_trading_dates(db, taiex_id, score_date, 20),
    )


class Killed(ReportGet):
    """The process is stopped (container stop, low memory, Ctrl+C) at the third request."""

    def __call__(self, request):
        if len(self.requests) == 2:
            raise KeyboardInterrupt
        return super().__call__(request)


def test_a_backfill_killed_midway_changes_no_row(factory):
    with factory() as db:
        taiex = _seed_taiex(db)
        db.commit()
        before = _basis(db, taiex.id)

    with pytest.raises(KeyboardInterrupt):
        _backfill(factory, Killed(_real_rows(), _tpex_rows()))

    with factory() as db:
        run = db.scalar(
            select(IngestionRun).where(IngestionRun.run_type == ib.RUN_TYPE)
        )
        assert run.status == "running"
        assert {b.source for b in _bars(db, "TWSE", "TAIEX")} == {"twse_index"}
        assert db.scalar(select(Instrument).where(Instrument.symbol == "TPEX")) is None
        assert _basis(db, taiex.id) == before


def test_a_backfill_failing_while_writing_changes_no_row(factory, monkeypatch):
    with factory() as db:
        taiex = _seed_taiex(db)
        db.commit()
        before = _basis(db, taiex.id)
    calls = []
    real = ib.store_index_bars

    def store_then_fail(*args, **kwargs):
        calls.append(1)
        if len(calls) == 3:
            raise RuntimeError("disk full")
        return real(*args, **kwargs)

    monkeypatch.setattr(ib, "store_index_bars", store_then_fail)

    with pytest.raises(RuntimeError, match="disk full"):
        _backfill(factory, ReportGet(_real_rows(), _tpex_rows()))

    with factory() as db:
        run = db.scalar(
            select(IngestionRun).where(IngestionRun.run_type == ib.RUN_TYPE)
        )
        assert run.status == "failed" and "disk full" in run.error
        # The first month was stored before the failure, and rolled back with it.
        assert {b.source for b in _bars(db, "TWSE", "TAIEX")} == {"twse_index"}
        assert _basis(db, taiex.id) == before


def test_force_rewrites_a_differing_close_and_records_it(factory):
    with factory() as db:
        _seed_taiex(db)
        db.commit()
    _backfill(factory, ReportGet(_real_rows(), _tpex_rows()))
    shifted = _tpex_rows()
    shifted = ([(d, o, h, low, c + 1) for d, o, h, low, c in shifted[0]], shifted[1])

    result, _ = _backfill(factory, ReportGet(_real_rows(), shifted), force=True)

    assert result["conflicts"] == len(SESSIONS)
    with factory() as db:
        run = db.get(IngestionRun, result["run_id"])
        forced = run.metadata_json["conflicts"]
        assert {item["forced"] for item in forced} == {True}
        assert _bars(db, "TPEx", "TPEX")[0].close == shifted[0][0][4]


def test_a_monthly_report_verifies_only_sessions_of_its_month_up_to_its_last_row():
    raw = RawPayload(
        ingestion_run_id=1,
        source="twse",
        endpoint=f"{sources.TWSE_INDEX_HISTORY_ENDPOINT}?date=20261001&response=json",
        data_as_of="2026-10-30",
    )

    def verified(day):
        return coverage._raw_is_date_verified(raw, run_ids={1}, trading_date=day)

    assert verified(date(2026, 10, 1)) and verified(date(2026, 10, 30))
    assert not verified(date(2026, 10, 31))
    assert not verified(date(2026, 9, 30))
    assert not coverage._raw_is_date_verified(
        raw, run_ids={2}, trading_date=date(2026, 10, 1)
    )


def test_a_monthly_report_verifies_no_session_before_the_stock_history():
    """Issue #563: the September 2024 report covers 09/02..09/30, only 09/30 is a session."""
    raw = RawPayload(
        ingestion_run_id=1,
        source="twse",
        endpoint=f"{sources.TWSE_INDEX_HISTORY_ENDPOINT}?date=20240901&response=json",
        data_as_of="2024-09-30",
    )

    def verified(day):
        return coverage._raw_is_date_verified(raw, run_ids={1}, trading_date=day)

    assert coverage.SESSION_BASIS_START == date(2024, 9, 30)
    assert verified(date(2024, 9, 30))
    assert not verified(date(2024, 9, 27))
    assert not verified(date(2024, 9, 2))


# --- indicators ---------------------------------------------------------------


def _indicator_bars(missing_range=(), missing_volume=(), synthetic=()):
    bars = []
    for index in range(30):
        close = 100.0 + index
        bars.append(
            IndicatorBar(
                date(2026, 1, 1) + timedelta(days=index),
                None if index in missing_range else close - 1,
                None if index in missing_range else close + 2,
                None if index in missing_range else close - 2,
                close,
                None if index in missing_volume else 1000.0 + index,
                synthetic=index in synthetic,
                missing_range=index in missing_range,
                missing_volume=index in missing_volume,
            )
        )
    return bars


def test_a_missing_range_or_volume_nulls_only_the_fields_that_read_it():
    plain = compute_indicators(_indicator_bars())
    gaps = compute_indicators(_indicator_bars(missing_range={3}, missing_volume={27}))

    last, plain_last = gaps[-1], plain[-1]
    assert last.values["kd_k"] is None and last.reasons["kd_k"] == MISSING_OHLC
    assert last.values["vol_ma5"] is None and last.reasons["vol_ma5"] == MISSING_VOLUME
    # vol_ma20's window (10..29) holds the day without volume too.
    assert last.reasons["vol_ma20"] == MISSING_VOLUME
    for name in ("ma5", "ma20", "macd_dif", "rsi6", "boll_mid"):
        assert last.values[name] == plain_last.values[name], name
    # Before the missing volume, the volume averages are back.
    assert gaps[26].values["vol_ma5"] == plain[26].values["vol_ma5"]
    # A synthetic day still names itself first.
    both = compute_indicators(_indicator_bars(missing_range={3}, synthetic={5}))
    assert both[-1].reasons["kd_k"] == SYNTHETIC_INDEX


def test_a_week_with_a_missing_range_has_no_open_high_low():
    weeks = aggregate_weekly(_indicator_bars(missing_range={3}, missing_volume={10}))

    week_of = {week.week_start: week for week in weeks}
    missing = next(w for w in weeks if w.week_start <= date(2026, 1, 4) <= w.week_end)
    assert (missing.open, missing.high, missing.low) == (None, None, None)
    assert missing.close == 103.0
    no_volume = next(
        w for w in weeks if w.week_start <= date(2026, 1, 11) <= w.week_end
    )
    assert no_volume.volume is None and no_volume.high is not None
    assert len(week_of) == len(weeks)


def test_features_of_an_index_day_without_range_or_volume_are_left_empty(factory):
    with factory() as db:
        taiex = _seed_taiex(db)
        bars = _bars(db, "TWSE", "TAIEX")
        bars[-1].open = bars[-1].high = bars[-1].low = None
        bars[-1].volume = None
        bars[-1].source = "twse_index_ohlcv"
        db.flush()

        pipeline._calculate_features(db, taiex)
        db.flush()

        feature = db.scalar(
            select(TechnicalFeature).where(
                TechnicalFeature.instrument_id == taiex.id,
                TechnicalFeature.trading_date == SESSIONS[-1],
            )
        ).features_json
        assert feature["volume"] is None and feature["volume_ratio_20d"] is None
        assert feature["high_20d"] is None and feature["atr14"] is None
        assert feature["return_1d"] is not None and feature["ma20"] is not None


# --- TX near month (TAIFEX open data) -------------------------------------------


@pytest.mark.parametrize(
    "day,contract",
    [
        # 2026-10: the third Wednesday is 10/21 (202610's last trading day).
        (date(2026, 10, 20), "202610"),
        (date(2026, 10, 21), "202611"),
        (date(2026, 10, 22), "202611"),
        # 2024-10: 10/16.
        (date(2024, 10, 15), "202410"),
        (date(2024, 10, 16), "202411"),
        # December rolls into January of the next year.
        (date(2026, 12, 16), "202701"),
        (date(2026, 12, 15), "202612"),
    ],
)
def test_the_near_month_rolls_on_the_third_wednesday(day, contract):
    from worker.futures_bars import near_month

    assert near_month(day) == contract


def test_the_near_month_regular_row_is_read_around_the_roll():
    from worker.futures_bars import parse_near_month

    before = parse_near_month(
        payloads.taifex_report(date(2026, 10, 20)), requested_date=date(2026, 10, 20)
    )
    on = parse_near_month(
        payloads.taifex_report(date(2026, 10, 21)), requested_date=date(2026, 10, 21)
    )

    assert (before.contract_month, on.contract_month) == ("202610", "202611")
    # The regular-session row, not the after-hours one, the spread or MTX.
    assert (on.open, on.high, on.low, on.close, on.volume) == (
        24000.0,
        24100.0,
        23900.0,
        24050.0,
        100000,
    )
    assert (on.settlement_price, on.open_interest) == (24040.0, 80000)


def test_a_report_of_another_session_is_rejected():
    from worker.futures_bars import parse_near_month

    with pytest.raises(OfficialDataError, match="instead of 2026-11-09"):
        parse_near_month(
            payloads.taifex_report(date(2026, 11, 6)), requested_date=date(2026, 11, 9)
        )


def test_a_missing_tx_open_is_left_empty():
    from worker.futures_bars import parse_near_month

    report = payloads.taifex_report(date(2026, 11, 6))
    report[0]["Open"] = "-"

    bar = parse_near_month(report, requested_date=date(2026, 11, 6))

    assert (bar.open, bar.high, bar.low, bar.close) == (None, None, None, 24050.0)
    assert bar.price_reason == "source_missing_ohlc"


# --- collect --------------------------------------------------------------------

COLLECT_DAY = date(2026, 9, 4)  # FixtureFetcher's session; TAIEX close 24000


class IndexReportFetcher(CodedFetcher):
    """FixtureFetcher plus the September reports: TAIEX 09/04 at 24000 and the TPEx index."""

    def __call__(self, url, **kwargs):
        if payloads.is_index_report(url):
            self.calls.append(url)
            month = payloads.requested_month(url, kwargs.get("data"))
            if month.month != 9:
                return payloads.empty_report(url, kwargs.get("data"))
            if url.startswith(sources.TWSE_INDEX_HISTORY_ENDPOINT):
                return payloads.twse_prices(
                    month, [(COLLECT_DAY, 23950.0, 24100.5, 23880.25, 24000.0)]
                )
            if url.startswith(sources.TWSE_MARKET_TRADING_ENDPOINT):
                return payloads.twse_volumes(
                    month, [(COLLECT_DAY, 8_000_000_000, 500_000_000_000, 24000.0)]
                )
            if url.startswith(sources.TPEX_INDEX_HISTORY_ENDPOINT):
                return payloads.tpex_prices(
                    month, [(COLLECT_DAY, 259.0, 261.0, 258.5, 260.0)]
                )
            return payloads.tpex_volumes(
                month, [(COLLECT_DAY, 700_000, 150_000_000, 260.0)]
            )
        return super().__call__(url, **kwargs)


@pytest.fixture
def collect_db(factory, monkeypatch):
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    return factory


def test_collect_upgrades_the_day_and_writes_the_tpex_index(collect_db):
    fetcher = IndexReportFetcher()

    result = pipeline.collect(COLLECT_DAY, adapter=combined(fetcher))

    assert result["status"] == "success", result
    assert result["noncore_warnings"] == []
    assert result["taiex_records"] >= 1
    # The first week of September also reads August (no session there).
    asked = [url for url in fetcher.calls if payloads.is_index_report(url)]
    assert len(asked) == 8
    with collect_db() as db:
        taiex = _bars(db, "TWSE", "TAIEX")[-1]
        assert (taiex.open, taiex.high, taiex.low, taiex.close) == (
            23950.0,
            24100.5,
            23880.25,
            24000.0,
        )
        assert taiex.volume == 8_000_000_000
        raw = db.get(RawPayload, taiex.raw_payload_id)
        assert raw.ingestion_run_id == result["run_id"]
        assert raw.data_as_of == COLLECT_DAY.isoformat()
        tpex = _bars(db, "TPEx", "TPEX")
        assert [(b.close, b.volume) for b in tpex] == [(260.0, 700_000_000)]
        run = db.get(IngestionRun, result["run_id"])
        counts = run.metadata_json["index_daily_bars"]["counts"]
        assert (counts["upgraded"], counts["inserted"]) == (1, 1)
        # The upgraded day is still a verified session.
        assert COLLECT_DAY in coverage.verified_taiex_sessions(db)
        # The TX near month (09/04 is before 09/16): its own futures instrument.
        tx = _bars(db, "TAIFEX", "TX")
        assert [(b.contract_month, b.close, b.open_interest) for b in tx] == [
            ("202609", 24050.0, 80000)
        ]
        future = db.get(Instrument, tx[0].instrument_id)
        assert future.instrument_type == "futures"
        tx_raw = db.get(RawPayload, tx[0].raw_payload_id)
        assert (tx_raw.source, tx_raw.endpoint) == (
            "taifex",
            sources.TAIFEX_DAILY_FUTURES_ENDPOINT,
        )
        assert run.metadata_json["futures_daily_bars"]["counts"]["inserted"] == 1


def test_a_futures_report_of_another_day_is_a_noncore_warning(collect_db):
    class Stale(IndexReportFetcher):
        def __call__(self, url, **kwargs):
            if url == sources.TAIFEX_DAILY_FUTURES_ENDPOINT:
                self.calls.append(url)
                return payloads.taifex_report(date(2026, 9, 3))
            return super().__call__(url, **kwargs)

    result = pipeline.collect(COLLECT_DAY, adapter=combined(Stale()))

    assert result["status"] == "success", result
    assert [w.split(":")[0] for w in result["noncore_warnings"]] == [
        "futures bars unavailable for TAIFEX TX"
    ]
    with collect_db() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Instrument)
                .where(Instrument.exchange == "TAIFEX")
            )
            == 0
        )
        # The answer is still kept as raw evidence.
        assert (
            db.scalar(
                select(func.count())
                .select_from(RawPayload)
                .where(RawPayload.source == "taifex")
            )
            == 1
        )


def test_a_failed_index_report_is_a_noncore_warning(collect_db):
    class Outage(IndexReportFetcher):
        def __call__(self, url, **kwargs):
            if url.startswith(sources.TWSE_INDEX_HISTORY_ENDPOINT):
                raise OfficialDataError("fixture outage")
            return super().__call__(url, **kwargs)

    result = pipeline.collect(COLLECT_DAY, adapter=combined(Outage()))

    assert result["status"] == "success", result
    assert result["core_warnings"] == []
    assert result["noncore_warnings"]
    assert all(w.startswith("index bars ") for w in result["noncore_warnings"])
    with collect_db() as db:
        assert _bars(db, "TWSE", "TAIEX")[-1].source == "twse_index"
