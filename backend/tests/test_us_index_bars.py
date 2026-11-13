"""US index bars from FinMind (Issues #547, #568): parsing, index-bars us-collect, the API.

Fixtures only: FinMind answers are small dicts, the database is an isolated
temporary SQLite file and sockets are forbidden.
"""

from __future__ import annotations

import socket
from pathlib import Path
from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import enable_sqlite_foreign_keys
from app.domain import US_INDEXES
from app.market_overview import expected_us_session, foreign_indices, index_rows
from app.migrations import upgrade_database
from app.models import (
    DataQuality,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
    TechnicalIndicator,
)
from test_daily_schedule import combined
from test_index_bars import COLLECT_DAY, IndexReportFetcher
from worker import pipeline, sources
from worker import us_index_bars as us
from worker.sources import OfficialDataError

SPX = us.SERIES_BY_SYMBOL["SPX"]
# Taipei Tuesday 2026-09-08: the request ends Monday 09-07.
SESSION = date(2026, 9, 8)


@pytest.fixture(autouse=True)
def no_network(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in US index tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")


def _factory(path):
    engine = create_engine(f"sqlite:///{path}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def factory(tmp_path):
    made = _factory(tmp_path / "us.db")
    yield made
    made.kw["bind"].dispose()


def row(data_id: str, day: str, close: float, volume: int = 1_000_000) -> dict:
    return {
        "date": day,
        "stock_id": data_id,
        "Adj_Close": close,
        "Close": close,
        "High": close + 2,
        "Low": close - 3,
        "Open": close - 1,
        "Volume": volume,
    }


def answer(rows: list[dict]) -> dict:
    return {"msg": "success", "status": 200, "data": rows}


def weekdays(start: date, end: date, skip: tuple[date, ...] = ()) -> list[date]:
    out, day = [], start
    while day <= end:
        if day.weekday() < 5 and day not in skip:
            out.append(day)
        day += timedelta(days=1)
    return out


# The history from 2023-09-01 (Labor Day 09-04 closed) and four sessions of
# 2026-09 before SESSION, with Labor Day 2026-09-07 closed... except it is the
# last weekday of the request, so it is not yet called closed (#568 decision 1).
LABOR_DAY_2023 = date(2023, 9, 4)
HISTORY_DAYS = weekdays(date(2023, 9, 1), date(2023, 9, 22), (LABOR_DAY_2023,))
RECENT_DAYS = weekdays(date(2026, 9, 1), date(2026, 9, 4))
DAYS = HISTORY_DAYS + RECENT_DAYS


class FinMind:
    """A FinMind fixture: each index answers DAYS (scaled by index) in the window.

    ``^SOX`` answers volume 0 on every day, as FinMind does.  ``overrides`` maps
    a data_id to an answer, an exception, or a callable (data_id, start, end).
    """

    def __init__(self, overrides=None, days=DAYS, closes=None):
        self.calls: list[str] = []
        self.overrides = overrides or {}
        self.days = days
        self.closes = closes or {}

    def __call__(self, url):
        self.calls.append(url)
        query = parse_qs(urlsplit(url).query)
        assert query["dataset"] == ["USStockPrice"]
        data_id = query["data_id"][0]
        start = date.fromisoformat(query["start_date"][0])
        end = date.fromisoformat(query["end_date"][0])
        override = self.overrides.get(data_id)
        if isinstance(override, Exception):
            raise override
        if callable(override):
            return override(data_id, start, end)
        if override is not None:
            return override
        scale = 1 + [item.series_id for item in US_INDEXES].index(data_id)
        return answer(
            [
                row(
                    data_id,
                    day.isoformat(),
                    self.closes.get(day, 1000.0 + i) * scale,
                    0 if data_id == "^SOX" else 1_000_000 + i,
                )
                for i, day in enumerate(self.days)
                if start <= day <= end
            ]
        )


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


def _collect(factory, fetch, session=SESSION, **kwargs):
    with factory() as db:
        return us.collect_us_indexes(db, session=session, fetch=fetch, **kwargs)


def _windows(fetch):
    return [
        (
            parse_qs(urlsplit(url).query)["data_id"][0],
            parse_qs(urlsplit(url).query)["start_date"][0],
            parse_qs(urlsplit(url).query)["end_date"][0],
        )
        for url in fetch.calls
    ]


# --- parsing ------------------------------------------------------------------


def test_a_weekday_without_a_row_before_the_newest_row_is_a_closed_day():
    parsed = us.parse_rows(
        answer(
            [
                row("^GSPC", "2026-09-01", 6400.10),
                row("^GSPC", "2026-09-03", 6420.50),
            ]
        ),
        SPX,
        start=date(2026, 9, 1),
        end=date(2026, 9, 4),
    )

    assert [(bar.trading_date, bar.close) for bar in parsed.bars] == [
        (date(2026, 9, 1), 6400.10),
        (date(2026, 9, 3), 6420.50),
    ]
    first = parsed.bars[0]
    assert (first.open, first.high, first.low, first.volume) == (
        6399.10,
        6402.10,
        6397.10,
        1_000_000,
    )
    # 09-02 is between two sessions: closed.  09-04 is after the newest row:
    # maybe not published yet, so not called closed.
    assert parsed.closed_dates == [date(2026, 9, 2)]


@pytest.mark.parametrize(
    "payload, message",
    [
        ("<html>blocked</html>", "not a JSON object"),
        ({"msg": "error", "status": 400, "data": []}, "not a success"),
        (answer([row("^IXIC", "2026-09-01", 10.0)]), "a row of '\\^IXIC'"),
        (answer([row("^GSPC", "2026-09-05", 6400.10)]), "outside"),
        (answer([row("^GSPC", "2026-08-31", 6400.10)]), "outside"),
        (
            answer(
                [row("^GSPC", "2026-09-01", 10.0), row("^GSPC", "2026-09-01", 20.0)]
            ),
            "twice",
        ),
        (answer([{**row("^GSPC", "2026-09-01", 6400.0), "Close": -5}]), "price"),
        (answer([{**row("^GSPC", "2026-09-01", 6400.0), "High": 6000}]), "high/low"),
        (answer([{**row("^GSPC", "2026-09-01", 6400.0), "Volume": 1.5}]), "volume"),
        (answer([{**row("^GSPC", "2026-09-01", 6400.0), "date": "09/01"}]), "date"),
        (answer([]), "no row"),
    ],
)
def test_an_answer_that_is_not_the_requested_rows_is_rejected_whole(payload, message):
    with pytest.raises(OfficialDataError, match=message):
        us.parse_rows(payload, SPX, start=date(2026, 9, 1), end=date(2026, 9, 4))


def test_a_refused_answer_is_finmind_refused():
    with pytest.raises(us.FinMindRefused):
        us.parse_rows(
            {"msg": "Requests reach the upper limit.", "status": 402},
            SPX,
            start=date(2026, 9, 1),
            end=date(2026, 9, 4),
        )


def test_volume_zero_everywhere_is_no_volume_and_a_single_zero_is_named():
    window = {"start": date(2026, 9, 1), "end": date(2026, 9, 4)}
    sox = us.SERIES_BY_SYMBOL["SOX"]
    none = us.parse_rows(
        answer([row("^SOX", f"2026-09-0{d}", 9000.0, 0) for d in (1, 2, 3)]),
        sox,
        **window,
    )
    assert none.no_volume and none.zero_volume_dates == []
    assert {bar.volume for bar in none.bars} == {None}

    one = us.parse_rows(
        answer(
            [
                row("^GSPC", "2026-09-01", 6400.0, 5_000),
                row("^GSPC", "2026-09-02", 6410.0, 0),
            ]
        ),
        SPX,
        **window,
    )
    assert not one.no_volume
    assert one.zero_volume_dates == [date(2026, 9, 2)]
    assert [bar.volume for bar in one.bars] == [5_000, None]


def test_the_request_window_starts_at_the_history_start_then_re_reads_ten_days():
    start = date(2023, 9, 1)
    end = SESSION - timedelta(days=1)
    # No row: the whole history in one request.
    assert us.request_window(None, None, SESSION) == (start, end)
    # Rows from the history start: ten days before the newest one.
    assert us.request_window(start, date(2026, 9, 4), SESSION) == (
        date(2026, 8, 25),
        end,
    )
    # A series whose oldest row is later than the start (#563's case): from the start.
    assert us.request_window(date(2024, 9, 30), date(2026, 9, 4), SESSION) == (
        start,
        end,
    )
    url = us.request_url(SPX, date(2026, 8, 25), end)
    assert url == (
        "https://api.finmindtrade.com/api/v4/data?dataset=USStockPrice"
        "&data_id=%5EGSPC&start_date=2026-08-25&end_date=2026-09-07"
    )


# --- us-collect -----------------------------------------------------------------


def test_a_first_run_reads_from_2023_09_01_and_writes_full_bars(factory):
    fetch = FinMind()

    result = _collect(factory, fetch)

    assert result["status"] == "success", result
    assert result["warnings"] == []
    # One request per index, from the history start to the day before.
    assert _windows(fetch) == [
        (item.series_id, "2023-09-01", "2026-09-07") for item in US_INDEXES
    ]
    assert result["requests"] == 4
    with factory() as db:
        rows = _bars(db, "SPX")
        assert [row.trading_date for row in rows] == DAYS
        first = rows[0]
        assert (first.open, first.high, first.low, first.close) == (
            999.0,
            1002.0,
            997.0,
            1000.0,
        )
        assert first.volume == 1_000_000
        assert first.price_reason is None
        assert (first.turnover_status, first.turnover_reason) == (
            "unavailable",
            "not_published",
        )
        assert {row.source for row in rows} == {"finmind_us_index"}
        raw = db.get(RawPayload, rows[-1].raw_payload_id)
        assert raw.source == "finmind"
        assert raw.endpoint == fetch.calls[0]
        assert raw.ingestion_run_id == result["run_id"]
        assert raw.data_as_of == "2026-09-04"
        instrument = db.get(Instrument, first.instrument_id)
        assert (instrument.market, instrument.instrument_type, instrument.name) == (
            "US",
            "index",
            "S&P 500",
        )
        assert [len(_bars(db, item.symbol)) for item in US_INDEXES] == [len(DAYS)] * 4
        # SOX: FinMind's 0 is no volume.
        assert {row.volume for row in _bars(db, "SOX")} == {None}
        quality = {
            row.entity_key: row
            for row in db.scalars(
                select(DataQuality).where(DataQuality.entity_type == "us_index_series")
            )
        }
        assert quality["US:SPX"].status == "complete"
        assert quality["US:SPX"].as_of_date == SESSION
        assert quality["US:SPX"].missing_fields_json == []
        assert quality["US:SOX"].missing_fields_json == ["volume"]
        assert quality["US:SOX"].checks_json["volume"] == "not_published"
        # Closed: every weekday without a row before the newest (2023 Labor Day,
        # and the gap between the history and 2026-09-01); not 2026-09-07.
        closed = quality["US:SPX"].checks_json["closed_dates"]
        assert "2023-09-04" in closed and "2026-09-07" not in closed
        run = db.get(IngestionRun, result["run_id"])
        assert (run.run_type, run.source, run.status) == (
            "us_index_collect",
            "finmind",
            "success",
        )
        assert run.records == 4 * len(DAYS)
        assert run.metadata_json["series"]["SOX"]["counts"]["inserted"] == len(DAYS)
        # Every row gets its indicator row; with open/high/low, KD is computed
        # (no #552 close-only rule); SOX has no volume average.
        for item in US_INDEXES:
            instrument = us.find_instrument(db, item)
            indicators = list(
                db.scalars(
                    select(TechnicalIndicator)
                    .where(TechnicalIndicator.instrument_id == instrument.id)
                    .order_by(TechnicalIndicator.trading_date)
                )
            )
            assert len(indicators) == len(DAYS)
            assert indicators[-1].kd_k is not None
            assert (indicators[-1].vol_ma5 is None) == (item.symbol == "SOX")


def test_a_second_run_of_the_day_asks_nothing_and_writes_nothing(factory):
    _collect(factory, FinMind(days=DAYS + [date(2026, 9, 7)]))
    again = FinMind(days=DAYS + [date(2026, 9, 7)])

    result = _collect(factory, again)

    assert result["status"] == "already_complete"
    assert result["requests"] == 0 and again.calls == []
    with factory() as db:
        runs = list(db.scalars(select(IngestionRun).order_by(IngestionRun.id)))
        assert [run.status for run in runs] == ["success", "already_complete"]
        assert runs[-1].records == 0


def test_a_rerun_without_new_sessions_writes_no_row(factory):
    # 09-07 (Labor Day) never arrives: every run asks, but writes nothing new.
    _collect(factory, FinMind())
    with factory() as db:
        before = [(r.id, r.collected_at) for r in _bars(db, "SPX")]

    result = _collect(factory, FinMind())

    assert result["status"] == "success"
    assert result["series"]["SPX"]["counts"] == {
        "inserted": 0,
        "revised": 0,
        "unchanged": 4,
        "conflict": 0,
    }
    assert result["indicators"] == {"status": "skipped", "reason": "no_changed_bars"}
    with factory() as db:
        assert [(r.id, r.collected_at) for r in _bars(db, "SPX")] == before


def test_a_later_run_reads_only_the_recent_window_and_adds_new_dates(factory):
    _collect(factory, FinMind())
    later = FinMind(days=DAYS + [date(2026, 9, 8)])

    result = _collect(factory, later, session=date(2026, 9, 9))

    assert result["status"] == "success", result
    assert _windows(later)[0] == ("^GSPC", "2026-08-25", "2026-09-08")
    assert result["series"]["SPX"]["counts"] == {
        "inserted": 1,
        "revised": 0,
        "unchanged": 4,
        "conflict": 0,
    }
    with factory() as db:
        assert _bars(db, "SPX")[-1].trading_date == date(2026, 9, 8)
        quality = db.scalar(
            select(DataQuality).where(
                DataQuality.entity_key == "US:SPX",
                DataQuality.as_of_date == date(2026, 9, 9),
            )
        )
        # Labor Day 2026 is now between two sessions: closed.
        # (The fixture has no session in 2026-08, so those weekdays count too.)
        closed = quality.checks_json["closed_dates"]
        assert closed[-1] == "2026-09-07" and "2026-09-04" not in closed


def test_a_later_capture_revises_finmind_rows_and_records_old_and_new(factory):
    # A first value of 09-04 revised by FinMind within the 10-day re-read
    # (#568 review item 1): the stored row takes the later capture's values.
    first = _collect(factory, FinMind())
    with factory() as db:
        before = _bars(db, "SPX")[-1]
        old_raw = before.raw_payload_id
    changed = FinMind(closes={date(2026, 9, 4): 1010.0})

    result = _collect(factory, changed)

    assert result["status"] == "success"
    # The re-read window (from 08-25) holds 09-01..09-04: three unchanged, 09-04 revised.
    assert result["series"]["SPX"]["counts"] == {
        "inserted": 0,
        "revised": 1,
        "unchanged": 3,
        "conflict": 0,
    }
    assert result["value_revision_rows"] == 4  # each index's 09-04
    assert result["warnings"] == []
    with factory() as db:
        row = _bars(db, "SPX")[-1]
        assert (row.close, row.open, row.high, row.low) == (
            1010.0,
            1009.0,
            1012.0,
            1007.0,
        )
        assert row.raw_payload_id != old_raw and row.source == "finmind_us_index"
        run = db.get(IngestionRun, result["run_id"])
        spx = next(
            r for r in run.metadata_json["value_revision_rows"] if r["symbol"] == "SPX"
        )
        assert spx["trading_date"] == "2026-09-04"
        assert (
            spx["old"]["close"] == before.close
            and spx["old"]["raw_payload_id"] == old_raw
        )
        assert (
            spx["new"]["close"] == 1010.0
            and spx["new"]["raw_payload_id"] == row.raw_payload_id
        )
        # The indicators of the revised series are rebuilt.
        assert result["indicators"] != {
            "status": "skipped",
            "reason": "no_changed_bars",
        }
    assert first["status"] == "success"


def test_a_capture_older_than_the_stored_row_does_not_revise_it(factory):
    _collect(factory, FinMind())
    with factory() as db:
        stored = _bars(db, "SPX")[-1]
        result = us.store_us_index_bars(
            db,
            SPX,
            [us.UsIndexBar(stored.trading_date, 1.0, 3.0, 0.5, 2.0, 5)],
            stored.raw_payload_id,
            captured_at=stored.collected_at - timedelta(minutes=1),
        )
        assert result.counts["conflict"] == 1 and result.revisions == []
        assert _bars(db, "SPX")[-1].close == stored.close
        db.rollback()


def test_a_stored_fred_row_is_never_overwritten(factory):
    # A FRED close (#547) for 2026-09-03, as a database written before #568 has.
    with factory() as db:
        instrument = us.us_index_instrument(db, SPX)
        db.add(
            MarketBar(
                instrument_id=instrument.id,
                trading_date=date(2026, 9, 3),
                open=None,
                high=None,
                low=None,
                close=6420.5,
                adj_close=6420.5,
                volume=None,
                turnover=0.0,
                turnover_status="unavailable",
                turnover_reason="not_published",
                price_reason="source_missing_ohlc",
                source="fred_close",
            )
        )
        db.commit()

    for force in (False, True):
        result = _collect(factory, FinMind(), force=force)
        assert result["series"]["SPX"]["counts"]["conflict"] == 1, force

    with factory() as db:
        kept = next(r for r in _bars(db, "SPX") if r.trading_date == date(2026, 9, 3))
        assert (kept.source, kept.close, kept.open) == ("fred_close", 6420.5, None)
        others = [r for r in _bars(db, "SPX") if r.trading_date != date(2026, 9, 3)]
        assert {r.source for r in others} == {"finmind_us_index"}


def test_a_single_zero_volume_is_stored_null_with_a_warning(factory):
    def one_zero(data_id, start, end):
        rows = FinMind()(
            f"{us.ENDPOINT}?dataset=USStockPrice&data_id={data_id}"
            f"&start_date={start}&end_date={end}"
        )["data"]
        rows[-1]["Volume"] = 0
        return answer(rows)

    result = _collect(factory, FinMind({"^GSPC": one_zero}))

    assert result["status"] == "success"
    assert result["warnings"] == [
        "us index bars stored no volume for US SPX on 1 day(s) FinMind ^GSPC gave 0: "
        "2026-09-04"
    ]
    with factory() as db:
        assert _bars(db, "SPX")[-1].volume is None
        assert _bars(db, "SPX")[-2].volume is not None

    # FinMind publishes that day's volume later: the NULL is filled (review item 1).
    later = _collect(factory, FinMind())
    assert later["series"]["SPX"]["counts"]["revised"] == 1
    assert later["warnings"] == []
    with factory() as db:
        assert _bars(db, "SPX")[-1].volume == 1_000_000 + len(DAYS) - 1


def test_an_answer_that_is_not_json_is_rejected_and_kept_as_raw(factory, monkeypatch):
    # #568 review item 5: a 200 whose body is not JSON (a block page) comes back
    # as its text, is rejected whole and is still kept as raw.
    class Response:
        status_code = 200
        text = "<html>verify you are human</html>"

        def json(self):
            raise ValueError("not JSON")

    import httpx

    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(us.time, "sleep", lambda seconds: None)
    assert us.fetch_json(us.request_url(SPX, date(2026, 9, 1), date(2026, 9, 4))) == (
        Response.text
    )

    fetch = FinMind({"^GSPC": Response.text})
    result = _collect(factory, fetch)

    assert result["series"]["SPX"]["status"] == "failed"
    assert "not a JSON object" in result["series"]["SPX"]["error"]
    with factory() as db:
        assert _bars(db, "SPX") == []
        quality = db.scalar(
            select(DataQuality).where(DataQuality.entity_key == "US:SPX")
        )
        raw = db.get(RawPayload, quality.checks_json["raw_payload_id"])
        assert raw.source == "finmind" and raw.endpoint == fetch.calls[0]
        assert Response.text in Path(raw.payload_path).read_text(encoding="utf-8")


def test_a_rejected_or_failed_index_is_partial_and_keeps_its_raw(factory):
    fetch = FinMind(
        {
            "^GSPC": answer([row("^GSPC", "2026-09-30", 1.0)]),
            "^DJI": OfficialDataError("FinMind answered 503"),
        }
    )

    result = _collect(factory, fetch)

    assert result["status"] == "partial"
    assert result["series"]["SPX"]["status"] == "failed"
    assert "outside" in result["series"]["SPX"]["error"]
    assert result["series"]["DJI"]["status"] == "failed"
    assert result["warnings"][0].startswith(
        "us index bars unavailable for US SPX (^GSPC): OfficialDataError"
    )
    with factory() as db:
        assert _bars(db, "SPX") == [] and _bars(db, "DJI") == []
        assert len(_bars(db, "IXIC")) == len(DAYS)
        # The rejected answer is kept as raw evidence (the failed GET has none).
        assert (
            db.scalar(
                select(func.count())
                .select_from(RawPayload)
                .where(RawPayload.source == "finmind")
            )
            == 3
        )
        quality = db.scalar(
            select(DataQuality).where(DataQuality.entity_key == "US:SPX")
        )
        assert quality.status == "failed"


def test_every_index_failing_is_a_failed_run(factory):
    fetch = FinMind({item.series_id: OfficialDataError("boom") for item in US_INDEXES})

    result = _collect(factory, fetch)

    assert result["status"] == "failed"
    with factory() as db:
        run = db.get(IngestionRun, result["run_id"])
        assert run.status == "failed" and "boom" in run.error
        assert (
            db.scalar(
                select(func.count())
                .select_from(Instrument)
                .where(Instrument.exchange == "US")
            )
            == 0
        )


def test_a_refusal_stops_the_run_without_asking_the_rest(factory):
    fetch = FinMind({"^IXIC": us.FinMindRefused("FinMind answered 402")})

    result = _collect(factory, fetch)

    # ^GSPC was asked and written, ^IXIC refused, ^DJI and ^SOX never asked.
    assert [call[0] for call in _windows(fetch)] == ["^GSPC", "^IXIC"]
    assert result["status"] == "partial"
    assert result["requests"] == 2
    assert result["series"]["SOX"]["error"].startswith("OfficialDataError: not asked")


def test_a_skip_reason_records_a_skipped_run_and_asks_nothing(factory):
    fetch = FinMind()

    result = _collect(factory, fetch, skip_reason="low_memory", trigger="scheduler")

    assert result["status"] == "skipped" and fetch.calls == []
    with factory() as db:
        run = db.get(IngestionRun, result["run_id"])
        assert (run.status, run.metadata_json["skip_reason"]) == (
            "skipped",
            "low_memory",
        )
        assert run.metadata_json["trigger"] == "scheduler"
        assert _bars(db, "SPX") == []


# --- collect no longer asks for the US indexes (#568, #571) -----------------------


@pytest.fixture
def collect_db(factory, monkeypatch):
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    return factory


def test_collect_asks_no_us_index_and_writes_no_us_row(collect_db):
    adapter = combined(IndexReportFetcher())
    # The attribute #547's collect read its fetcher from: given one, it asked.
    fetch = FinMind()
    adapter.us_index_fetcher = fetch

    result = pipeline.collect(COLLECT_DAY, adapter=adapter)

    assert result["status"] == "success", result
    assert fetch.calls == []
    assert not hasattr(sources.OfficialMarketDataAdapter(), "us_index_fetcher")
    with collect_db() as db:
        run = db.get(IngestionRun, result["run_id"])
        assert "us_index_daily_bars" not in run.metadata_json
        assert (
            db.scalar(
                select(func.count())
                .select_from(Instrument)
                .where(Instrument.exchange == "US")
            )
            == 0
        )


def test_taiwan_bar_dates_skip_a_us_only_day(factory):
    # 2026-09-03 has a US bar here but no Taiwan bar (a Taiwan holiday).
    with factory() as db:
        _taiwan_sessions(db, [date(2026, 9, 2)])
    _collect(factory, FinMind(days=[date(2026, 9, 2), date(2026, 9, 3)]))
    with factory() as db:
        assert date(2026, 9, 3) in {row.trading_date for row in _bars(db, "SPX")}
        assert pipeline.taiwan_bar_dates(db, date(2026, 9, 1), date(2026, 9, 4)) == [
            date(2026, 9, 2)
        ]


def _taiwan_sessions(db, days):
    """TAIEX and one stock with a bar on each of ``days`` (Taiwan sessions)."""

    for exchange, symbol, kind in (
        ("TWSE", "TAIEX", "index"),
        ("TWSE", "2330", "stock"),
    ):
        item = Instrument(
            market="TW",
            exchange=exchange,
            symbol=symbol,
            name=symbol,
            instrument_type=kind,
            industry="Index" if kind == "index" else "24",
            status="active",
        )
        db.add(item)
        db.flush()
        for day in days:
            db.add(
                MarketBar(
                    instrument_id=item.id,
                    trading_date=day,
                    open=10,
                    high=11,
                    low=9,
                    close=10,
                    adj_close=10,
                    volume=1000,
                    turnover=10000,
                    turnover_status="available",
                    source="twse_index" if kind == "index" else "twse",
                )
            )
    db.commit()


def _session_views(factory, monkeypatch, start, end, holiday):
    """What backtest, plan tracking and the coverage report take as sessions."""

    from worker.backfill import coverage_report
    from worker.plan_tracking import _market_dates_after

    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    replayed: list[date] = []
    original = pipeline._generate_signals

    def spy(db, score_date, strategies, **kwargs):
        replayed.append(score_date)
        return original(db, score_date, strategies, **kwargs)

    monkeypatch.setattr(pipeline, "_generate_signals", spy)
    result = pipeline.backtest(start, end, force=True)
    monkeypatch.setattr(pipeline, "_generate_signals", original)
    with factory() as db:
        run = db.scalar(
            select(IngestionRun)
            .where(IngestionRun.run_type == "backtest")
            .order_by(IngestionRun.id.desc())
            .limit(1)
        )
        return {
            "backtest_status": result["run"]["status"],
            "backtest_score_dates": replayed,
            "score_session_count": run.metadata_json["score_session_count"],
            "tracking_sessions": _market_dates_after(
                db, start - timedelta(days=1), end, 40
            ),
            "coverage": coverage_report(db, start, end, known_no_data_dates={holiday}),
        }


def test_a_us_bar_on_a_taiwan_holiday_changes_no_taiwan_session_view(
    factory, monkeypatch
):
    # 2026-09-30 (Wednesday): Taiwan closed (confirmed), the US open.
    start, holiday, end = date(2026, 9, 28), date(2026, 9, 30), date(2026, 10, 2)
    taiwan = [
        date(2026, 9, 28),
        date(2026, 9, 29),
        date(2026, 10, 1),
        date(2026, 10, 2),
    ]
    with factory() as db:
        _taiwan_sessions(db, taiwan)
    before = _session_views(factory, monkeypatch, start, end, holiday)
    _collect(factory, FinMind(days=weekdays(start, end)), session=date(2026, 10, 5))
    with factory() as db:
        assert holiday in {row.trading_date for row in _bars(db, "SPX")}
    after = _session_views(factory, monkeypatch, start, end, holiday)

    assert after == before
    assert before["backtest_status"] == "success"
    assert before["backtest_score_dates"] == taiwan
    assert before["tracking_sessions"] == taiwan


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
    # us-collect's already_complete waits for the same session.
    assert us.expected_session(reference) == expected


def _fred_rows(db, closes):
    """FRED close-only rows (#547), as a database written before #568 holds them."""

    for symbol_index, series in enumerate(US_INDEXES):
        instrument = us.us_index_instrument(db, series)
        for day, close in closes:
            db.add(
                MarketBar(
                    instrument_id=instrument.id,
                    trading_date=day,
                    open=None,
                    high=None,
                    low=None,
                    close=close * (1 + symbol_index),
                    adj_close=close * (1 + symbol_index),
                    volume=None,
                    turnover=0.0,
                    turnover_status="unavailable",
                    turnover_reason="not_published",
                    price_reason="source_missing_ohlc",
                    source="fred_close",
                )
            )
    db.commit()


def test_foreign_indices_give_finmind_bars_in_the_fred_format(factory, tmp_path):
    days = [date(2026, 9, 3), date(2026, 9, 4)]
    closes = {days[0]: 6400.10, days[1]: 6420.50}
    _collect(factory, FinMind(days=days, closes=closes))
    with factory() as db:
        # Taipei Monday 09/07: the expected US session is Friday 09/04.
        items = foreign_indices(db, "2026-09-07")
        table = {row["key"]: row for row in index_rows(db, "2026-09-07", items)}

    assert [item["symbol"] for item in items] == ["SPX", "IXIC", "DJI", "SOX"]
    spx = items[0]
    assert spx["status"] == "available"
    assert (spx["trading_date"], spx["expected_date"], spx["freshness"]) == (
        "2026-09-04",
        "2026-09-04",
        "latest",
    )
    assert spx["close"] == 6420.50
    assert spx["change"] == pytest.approx(20.40)
    assert spx["change_pct"] == pytest.approx(20.40 / 6400.10, abs=1e-6)
    assert spx["previous_trading_date"] == "2026-09-03"
    assert spx["series_id"] == "^GSPC"
    assert spx["source"]["label"] == "FinMind USStockPrice ^GSPC"
    assert "S&P Dow Jones Indices" in spx["source"]["copyright"]
    assert spx["source"]["collected_at"].endswith("+00:00")
    assert table["spx"]["source"]["label"] == "FinMind"
    assert table["spx"]["source"]["detail"] == "FinMind USStockPrice ^GSPC"

    # The same days as FRED rows (#547) in another database: the same fields and
    # values; only the source differs (#568 decision 6729023767).
    fred_factory = _factory(tmp_path / "fred.db")
    with fred_factory() as db:
        _fred_rows(db, sorted(closes.items()))
        fred = foreign_indices(db, "2026-09-07")[0]
        fred_table = index_rows(db, "2026-09-07", foreign_indices(db, "2026-09-07"))
    fred_factory.kw["bind"].dispose()
    assert fred.keys() == spx.keys()
    assert fred["source"].keys() == spx["source"].keys()
    assert {k: v for k, v in fred.items() if k != "source"} == {
        k: v for k, v in spx.items() if k != "source"
    }
    assert fred["source"]["label"] == "FRED"
    fred_spx = next(row for row in fred_table if row["key"] == "spx")
    assert fred_spx.keys() == table["spx"].keys()
    assert fred_spx["source"]["label"] == "FRED"


def test_the_newest_missing_weekday_is_stale_not_closed(factory):
    # Labor Day 09-07 is the last weekday of the request: not yet called closed.
    _collect(factory, FinMind(days=[date(2026, 9, 3), date(2026, 9, 4)]))
    with factory() as db:
        spx = foreign_indices(db, "2026-09-08")[0]

    assert (spx["trading_date"], spx["expected_date"], spx["freshness"]) == (
        "2026-09-04",
        "2026-09-07",
        "stale",
    )


def test_a_recorded_holiday_makes_the_session_before_it_us_market_closed(factory):
    # The reading side only (#568 review item 4): us-collect records a holiday
    # once a later session is stored, so the page then shows that later session
    # as latest; it never stores this state itself.  The 09-08 bar is deleted
    # below to reach it.  A run whose newest row is 09-08 records Labor Day
    # 09-07 as closed.
    _collect(
        factory,
        FinMind(days=[date(2026, 9, 3), date(2026, 9, 4), date(2026, 9, 8)]),
        session=date(2026, 9, 9),
    )
    with factory() as db:
        # Read as of Taipei 09/08 without the 09-08 bar: expected 09-07, closed,
        # so the 09-04 bar is the latest session.
        spx = us.find_instrument(db, SPX)
        db.execute(
            MarketBar.__table__.delete().where(
                MarketBar.instrument_id == spx.id,
                MarketBar.trading_date == date(2026, 9, 8),
            )
        )
        db.commit()
        item = foreign_indices(db, "2026-09-08")[0]
        # Taipei Thursday 09/10: expected 09/09, no row, not recorded → stale.
        stale = foreign_indices(db, "2026-09-10")[1]

    assert (item["trading_date"], item["freshness"]) == (
        "2026-09-04",
        "us_market_closed",
    )
    assert (stale["expected_date"], stale["freshness"]) == ("2026-09-09", "stale")


def test_an_index_without_rows_says_why(factory):
    with factory() as db:
        empty = foreign_indices(db, "2026-09-08")
    _collect(factory, FinMind({"^SOX": OfficialDataError("FinMind answered 503")}))
    with factory() as db:
        after = foreign_indices(db, "2026-09-08")

    assert {item["status"] for item in empty} == {"unavailable"}
    assert {item["reason"] for item in empty} == {"not_collected"}
    assert after[3]["status"] == "unavailable"
    assert (after[3]["reason"], after[3]["last_attempt_date"]) == (
        "fetch_failed",
        "2026-09-08",
    )
    assert after[0]["status"] == "available"
