"""US index closes from FRED (Issue #547): parsing, collect's non-core step, the API.

Fixtures only: FRED answers are small CSV strings, the database is an isolated
temporary SQLite file and sockets are forbidden.
"""

from __future__ import annotations

import socket
from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import enable_sqlite_foreign_keys
from app.domain import US_INDEXES
from app.market_overview import expected_us_session, foreign_indices
from app.migrations import upgrade_database
from app.models import DataQuality, IngestionRun, Instrument, MarketBar, RawPayload
from test_daily_schedule import combined
from test_index_bars import COLLECT_DAY, IndexReportFetcher
from worker import pipeline, sources
from worker import us_index_bars as us
from worker.sources import OfficialDataError

SPX = us.SERIES_BY_SYMBOL["SPX"]


@pytest.fixture(autouse=True)
def no_network(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in US index tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'us.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    made = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield made
    engine.dispose()


@pytest.fixture
def collect_db(factory, monkeypatch):
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    return factory


def csv(series_id: str, rows: list[tuple[str, str]]) -> str:
    lines = [f"observation_date,{series_id}"] + [
        f"{day},{value}" for day, value in rows
    ]
    return "\n".join(lines) + "\n"


# Two sessions, a US holiday (blank) and a third session, all before COLLECT_DAY.
ROWS = [
    ("2026-09-01", "6400.10"),
    ("2026-09-02", "6420.50"),
    ("2026-09-03", ""),
    ("2024-09-30", "5762.48"),
]


class Fred:
    """A FRED fixture: each series answers ROWS (scaled by series), or a per-series override."""

    def __init__(self, overrides=None, rows=ROWS):
        self.calls: list[str] = []
        self.overrides = overrides or {}
        self.rows = rows

    def __call__(self, url):
        self.calls.append(url)
        query = parse_qs(urlsplit(url).query)
        series_id = query["id"][0]
        start = date.fromisoformat(query["cosd"][0])
        end = date.fromisoformat(query["coed"][0])
        override = self.overrides.get(series_id)
        if isinstance(override, Exception):
            raise override
        if callable(override):
            return override(series_id, start, end)
        if isinstance(override, str):
            return override
        scale = 1 + US_INDEXES.index(
            next(item for item in US_INDEXES if item.series_id == series_id)
        )
        rows = sorted(
            (day, f"{float(value) * scale:.2f}" if value else value)
            for day, value in self.rows
            if start <= date.fromisoformat(day) <= end
        )
        return csv(series_id, rows)


def _adapter(fred):
    fetcher = IndexReportFetcher()
    adapter = combined(fetcher)
    adapter.us_index_fetcher = fred
    return adapter


def _bars(db, symbol):
    instrument = db.scalar(
        select(Instrument).where(
            Instrument.exchange == "US", Instrument.symbol == symbol
        )
    )
    if instrument is None:
        return []
    return list(
        db.scalars(
            select(MarketBar)
            .where(MarketBar.instrument_id == instrument.id)
            .order_by(MarketBar.trading_date)
        )
    )


# --- parsing ------------------------------------------------------------------


def test_a_blank_observation_is_a_closed_day_not_a_zero():
    parsed = us.parse_csv(
        csv(
            "SP500",
            [("2026-09-01", "6400.10"), ("2026-09-02", "."), ("2026-09-03", "")],
        ),
        SPX,
        start=date(2026, 9, 1),
        end=date(2026, 9, 3),
    )

    assert [(bar.trading_date, bar.close) for bar in parsed.bars] == [
        (date(2026, 9, 1), 6400.10)
    ]
    assert parsed.closed_dates == [date(2026, 9, 2), date(2026, 9, 3)]


@pytest.mark.parametrize(
    "text, message",
    [
        ("<!DOCTYPE html><html>verify your browser</html>", "not its CSV"),
        (csv("NASDAQCOM", [("2026-09-01", "1.0")]), "not its CSV"),
        (csv("SP500", [("2026-09-04", "6400.10")]), "outside"),
        (csv("SP500", [("2026-08-31", "6400.10")]), "outside"),
        (csv("SP500", [("2026-09-01", "1"), ("2026-09-01", "2")]), "twice"),
        (csv("SP500", [("2026-09-01", "-5")]), "unreadable close"),
        (csv("SP500", [("2026-09-01", "1,2")]), "malformed"),
        (csv("SP500", []), "no observation"),
        (None, "not text"),
    ],
)
def test_an_answer_that_is_not_the_requested_csv_is_rejected_whole(text, message):
    with pytest.raises(OfficialDataError, match=message):
        us.parse_csv(text, SPX, start=date(2026, 9, 1), end=date(2026, 9, 3))


def test_the_request_window_starts_at_the_history_start_then_re_reads_ten_days():
    assert us.request_window(None, COLLECT_DAY) == (
        date(2024, 9, 30),
        COLLECT_DAY - timedelta(days=1),
    )
    assert us.request_window(date(2026, 9, 2), COLLECT_DAY) == (
        date(2026, 8, 23),
        date(2026, 9, 3),
    )
    url = us.request_url(SPX, date(2026, 8, 23), date(2026, 9, 3))
    assert url == (
        "https://fred.stlouisfed.org/graph/fredgraph.csv"
        "?id=SP500&cosd=2026-08-23&coed=2026-09-03"
    )


# --- collect --------------------------------------------------------------------


def test_collect_writes_close_only_rows_of_the_four_indexes(collect_db):
    fred = Fred()

    result = pipeline.collect(COLLECT_DAY, adapter=_adapter(fred))

    assert result["status"] == "success", result
    assert result["noncore_warnings"] == []
    # One request per series, from the history start to the day before.
    assert [parse_qs(urlsplit(url).query)["id"][0] for url in fred.calls] == [
        "SP500",
        "NASDAQCOM",
        "DJIA",
        "NASDAQSOX",
    ]
    assert all("cosd=2024-09-30&coed=2026-09-03" in url for url in fred.calls)
    with collect_db() as db:
        rows = _bars(db, "SPX")
        assert [(row.trading_date, row.close) for row in rows] == [
            (date(2024, 9, 30), 5762.48),
            (date(2026, 9, 1), 6400.10),
            (date(2026, 9, 2), 6420.50),
        ]
        for row in rows:
            assert (row.open, row.high, row.low, row.volume) == (None, None, None, None)
            assert row.price_reason == "source_missing_ohlc"
            assert (row.turnover_status, row.turnover_reason) == (
                "unavailable",
                "not_published",
            )
            assert row.source == "fred_close"
        raw = db.get(RawPayload, rows[-1].raw_payload_id)
        assert raw.source == "fred"
        assert raw.endpoint == fred.calls[0]
        assert raw.ingestion_run_id == result["run_id"]
        assert raw.data_as_of == "2026-09-02"
        instrument = db.get(Instrument, rows[0].instrument_id)
        assert (instrument.market, instrument.instrument_type, instrument.name) == (
            "US",
            "index",
            "S&P 500",
        )
        assert [len(_bars(db, item.symbol)) for item in US_INDEXES] == [3, 3, 3, 3]
        quality = db.scalar(
            select(DataQuality).where(
                DataQuality.entity_type == "us_index_series",
                DataQuality.entity_key == "US:SPX",
            )
        )
        assert quality.status == "complete"
        assert quality.as_of_date == COLLECT_DAY
        assert quality.checks_json["closed_dates"] == ["2026-09-03"]
        run = db.get(IngestionRun, result["run_id"])
        series = run.metadata_json["us_index_daily_bars"]["series"]
        assert series["SOX"]["counts"]["inserted"] == 3


def test_a_holiday_gets_no_row_and_no_zero(collect_db):
    pipeline.collect(COLLECT_DAY, adapter=_adapter(Fred()))

    with collect_db() as db:
        for item in US_INDEXES:
            rows = _bars(db, item.symbol)
            assert date(2026, 9, 3) not in {row.trading_date for row in rows}
            assert all(row.close > 0 for row in rows)


def test_a_date_outside_the_request_rejects_that_series_with_a_warning(collect_db):
    late = csv("SP500", [("2026-09-02", "6420.50"), ("2026-09-04", "6500.00")])
    fred = Fred({"SP500": late})

    result = pipeline.collect(COLLECT_DAY, adapter=_adapter(fred))

    assert result["status"] == "success", result
    assert result["core_warnings"] == []
    assert len(result["noncore_warnings"]) == 1
    assert result["noncore_warnings"][0].startswith(
        "us index bars unavailable for US SPX (SP500): OfficialDataError"
    )
    assert "2026-09-04 outside" in result["noncore_warnings"][0]
    with collect_db() as db:
        assert _bars(db, "SPX") == []
        assert len(_bars(db, "IXIC")) == 3
        # The rejected answer is kept as raw evidence.
        assert (
            db.scalar(
                select(func.count())
                .select_from(RawPayload)
                .where(RawPayload.source == "fred")
            )
            == 4
        )
        quality = db.scalar(
            select(DataQuality).where(DataQuality.entity_key == "US:SPX")
        )
        assert quality.status == "failed"
        assert "outside" in quality.checks_json["error"]


def test_a_failed_request_is_only_a_noncore_warning(collect_db):
    fred = Fred(
        {
            series.series_id: OfficialDataError("FRED answered 503")
            for series in US_INDEXES
        }
    )

    result = pipeline.collect(COLLECT_DAY, adapter=_adapter(fred))

    assert result["status"] == "success", result
    assert result["core_warnings"] == []
    assert len(result["noncore_warnings"]) == 4
    assert all(
        warning.startswith("us index bars unavailable for US ")
        for warning in result["noncore_warnings"]
    )
    with collect_db() as db:
        assert all(_bars(db, item.symbol) == [] for item in US_INDEXES)
        # The Taiwan session is unaffected.
        taiex = db.scalar(select(Instrument).where(Instrument.symbol == "TAIEX"))
        assert db.scalar(
            select(MarketBar.id).where(
                MarketBar.instrument_id == taiex.id,
                MarketBar.trading_date == COLLECT_DAY,
            )
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(Instrument)
                .where(Instrument.exchange == "US")
            )
            == 0
        )


def test_a_fixture_adapter_without_a_fred_fetcher_asks_nothing(collect_db):
    result = pipeline.collect(COLLECT_DAY, adapter=combined(IndexReportFetcher()))

    assert result["status"] == "success", result
    with collect_db() as db:
        run = db.get(IngestionRun, result["run_id"])
        assert run.metadata_json["us_index_daily_bars"] == {}


def _run(db):
    run = IngestionRun(
        run_type="collect", source="official", run_date=COLLECT_DAY, status="running"
    )
    db.add(run)
    db.flush()
    return run


def test_a_later_collect_re_reads_ten_days_and_adds_only_new_dates(factory):
    first = Fred()
    with factory() as db:
        us.collect_us_index_bars(
            db, _run(db), COLLECT_DAY, first, pipeline._upsert_raw_payload, []
        )
        db.commit()
    later_day = date(2026, 9, 8)
    second = Fred(rows=ROWS + [("2026-09-04", "6450.00")])
    warnings: list[str] = []
    with factory() as db:
        result = us.collect_us_index_bars(
            db, _run(db), later_day, second, pipeline._upsert_raw_payload, warnings
        )
        db.commit()
        assert warnings == []
        assert "cosd=2026-08-23&coed=2026-09-07" in second.calls[0]
        assert result["SPX"]["counts"] == {
            "inserted": 1,
            "replaced": 0,
            "unchanged": 2,
            "conflict": 0,
        }
        assert [row.trading_date for row in _bars(db, "SPX")][-1] == date(2026, 9, 4)


def test_a_different_close_for_a_stored_day_is_kept_and_warned(factory):
    with factory() as db:
        us.collect_us_index_bars(
            db, _run(db), COLLECT_DAY, Fred(), pipeline._upsert_raw_payload, []
        )
        db.commit()
    changed = csv("SP500", [("2026-09-01", "6400.10"), ("2026-09-02", "9999.00")])
    warnings: list[str] = []
    with factory() as db:
        us.collect_us_index_bars(
            db,
            _run(db),
            COLLECT_DAY,
            Fred({"SP500": changed}),
            pipeline._upsert_raw_payload,
            warnings,
        )
        db.commit()
        assert _bars(db, "SPX")[-1].close == 6420.50
    assert warnings == [
        "us index bars kept 1 stored US SPX close(s) that differ from FRED SP500"
    ]
    assert pipeline.NONCORE_WARNING_PATTERN.match(warnings[0])


def test_a_us_close_on_a_taiwan_holiday_is_not_a_backtest_session(factory):
    # 2026-09-03 has a US close here but no Taiwan bar (a Taiwan holiday).
    holiday = Fred(rows=[("2026-09-02", "6420.50"), ("2026-09-03", "6430.00")])
    with factory() as db:
        taiex = Instrument(
            market="TW",
            exchange="TWSE",
            symbol="TAIEX",
            name="加權指數",
            instrument_type="index",
            industry="Index",
            status="active",
        )
        db.add(taiex)
        db.flush()
        db.add(
            MarketBar(
                instrument_id=taiex.id,
                trading_date=date(2026, 9, 2),
                open=1,
                high=1,
                low=1,
                close=1,
                adj_close=1,
                volume=1,
                source="twse_index",
            )
        )
        us.collect_us_index_bars(
            db, _run(db), COLLECT_DAY, holiday, pipeline._upsert_raw_payload, []
        )
        db.commit()
        assert date(2026, 9, 3) in {row.trading_date for row in _bars(db, "SPX")}
        assert pipeline.taiwan_bar_dates(db, date(2026, 9, 1), date(2026, 9, 4)) == [
            date(2026, 9, 2)
        ]


# --- API --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reference, expected",
    [
        (date(2026, 9, 8), date(2026, 9, 7)),  # Tuesday → Monday
        (date(2026, 9, 7), date(2026, 9, 4)),  # Monday → Friday
        (date(2026, 9, 6), date(2026, 9, 4)),  # Sunday → Friday
    ],
)
def test_the_expected_us_session_is_the_weekday_before(reference, expected):
    assert expected_us_session(reference) == expected


def _seed(db, session=COLLECT_DAY, fred=None):
    us.collect_us_index_bars(
        db, _run(db), session, fred or Fred(), pipeline._upsert_raw_payload, []
    )
    db.commit()


def test_foreign_indices_give_the_latest_close_and_its_change(factory):
    with factory() as db:
        _seed(db)
        # Taipei Thursday 09/03: the expected US session is 09/02.
        items = foreign_indices(db, "2026-09-03")

    assert [item["symbol"] for item in items] == ["SPX", "IXIC", "DJI", "SOX"]
    spx = items[0]
    assert spx["status"] == "available"
    assert (spx["trading_date"], spx["expected_date"], spx["freshness"]) == (
        "2026-09-02",
        "2026-09-02",
        "latest",
    )
    assert spx["close"] == 6420.50
    assert spx["change"] == pytest.approx(20.40)
    assert spx["change_pct"] == pytest.approx(20.40 / 6400.10, abs=1e-6)
    assert spx["previous_trading_date"] == "2026-09-01"
    assert spx["source"]["label"] == "FRED SP500"
    assert "S&P Dow Jones Indices" in spx["source"]["copyright"]
    assert spx["source"]["collected_at"].endswith("+00:00")


def test_an_older_close_is_stale_unless_the_expected_day_was_a_us_holiday(factory):
    with factory() as db:
        _seed(db)
        # Taipei Friday 09/04: expected 09/03, a FRED blank → the 09/02 close is the latest session.
        closed = foreign_indices(db, "2026-09-04")[0]
        # Taipei Tuesday 09/08: expected Monday 09/07, not a blank → stale.
        stale = foreign_indices(db, "2026-09-08")[0]

    assert (closed["trading_date"], closed["freshness"]) == (
        "2026-09-02",
        "us_market_closed",
    )
    assert (stale["expected_date"], stale["freshness"]) == ("2026-09-07", "stale")


def test_an_index_without_rows_says_why(factory):
    fred = Fred({"NASDAQSOX": OfficialDataError("FRED answered 503")})
    with factory() as db:
        empty = foreign_indices(db, "2026-09-04")
        _seed(db, fred=fred)
        after = foreign_indices(db, "2026-09-04")

    assert {item["status"] for item in empty} == {"unavailable"}
    assert {item["reason"] for item in empty} == {"not_collected"}
    assert after[3]["status"] == "unavailable"
    assert (after[3]["reason"], after[3]["last_attempt_date"]) == (
        "fetch_failed",
        "2026-09-04",
    )
    assert after[0]["status"] == "available"
