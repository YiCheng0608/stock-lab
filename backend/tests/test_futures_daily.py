"""The TX near month from the OpenAPI DailyMarketReportFut, as CSV or JSON (Issue #586).

Since 2026-11 the report answers a UTF-8 CSV with Chinese headers instead of
JSON, and it changes to a session late (still 2026-11-06 at 2026-11-10 01:39).
The CSV rows below are copied from that answer (政府資料開放授權條款第1版, the
open-data report, not the website download whose terms forbid republishing):
the TX near and next month in both sessions, a calendar spread, and MTX.
"""

from __future__ import annotations

import json
import socket
from datetime import date, datetime

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import IngestionRun, Instrument, MarketBar, RawPayload
from worker import futures_bars, pipeline, sources
from worker.sources import OfficialDataError

HEADER = (
    "日期,契約代號,到期月份(週別),開盤價,最高價,最低價,最後成交價,漲跌價,漲跌%,"
    "合計成交量,結算價,未沖銷契約數,最後最佳買價,最後最佳賣價,歷史最高價,歷史最低價,"
    "是否因訊息面暫停交易,交易時段,價差對單式委託成交量"
)
ROWS_1106 = [
    "20261106,TX,202611,38888,40690,37694,39786,-2096,-5.00%,143277,39652,125793,39787,39807,50440,37694,,一般,",
    "20261106,TX,202611,41990,42298,38799,38936,-2946,-7.03%,89296,NULL,-,38950,38975,50440,38799,,盤後,",
    "20261106,TX,202612,38450,40711,37747,39821,-2120,-5.05%,1546,39719,5747,39836,39864,50560,27382,,一般,",
    "20261106,TX,202612,42203,42333,38844,38957,-2984,-7.11%,1064,NULL,-,38958,38992,50560,27382,,盤後,",
    "20261106,TX,202706,42859,-,-,42859,0,0.00%,1,NULL,-,39471,39900,51469,41461,,盤後,",
    "20261106,TX,202611/202612,13,71,-46,58,-,-,426,-,-,49,58,170,-46,,一般,963",
    "20261106,MTX,202611,38900,40692,37694,39776,-2106,-5.03%,247125,39652,26465,39785,39793,50445,37694,,一般,",
]
REPORT_DAY = date(2026, 11, 6)
COLLECT_DAY = date(2026, 11, 9)


def csv_answer(rows=ROWS_1106, header=HEADER) -> bytes:
    """The answer as the endpoint sends it: a byte-order mark and CRLF lines."""
    return (chr(0xFEFF) + "\r\n".join([header, *rows]) + "\r\n").encode("utf-8")


def json_answer(rows=ROWS_1106) -> list[dict[str, str]]:
    """The same rows as the JSON list the endpoint answered before."""
    names = [futures_bars.CSV_FIELDS[name] for name in HEADER.split(",")]
    return [dict(zip(names, row.split(","))) for row in rows]


@pytest.fixture(autouse=True)
def no_network(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in futures daily tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


# --- AC-1: CSV and JSON give the same near-month bar -----------------------------


def test_the_csv_and_the_json_answer_give_the_same_near_month_bar():
    from_csv = futures_bars.parse_near_month(csv_answer())
    from_json = futures_bars.parse_near_month(json_answer())

    assert from_csv == from_json
    # The near month's regular session: not after-hours, 202612, the spread or MTX.
    assert from_csv.trading_date == REPORT_DAY
    assert from_csv.contract_month == "202611"
    assert (from_csv.open, from_csv.high, from_csv.low, from_csv.close) == (
        38888.0,
        40690.0,
        37694.0,
        39786.0,
    )
    assert (from_csv.volume, from_csv.settlement_price, from_csv.open_interest) == (
        143277,
        39652.0,
        125793,
    )
    assert from_csv.price_reason is None


def test_the_csv_capture_is_stored_as_text_and_reads_back_the_same():
    payload = futures_bars.capture_form(csv_answer())

    assert payload["format"] == "csv" and payload["encoding"] == "utf-8"
    assert payload["csv"].startswith("日期,契約代號")  # no byte-order mark
    # The raw file is JSON: the capture survives the round trip.
    stored = json.loads(json.dumps(payload, ensure_ascii=False))
    assert futures_bars.report_date(stored) == REPORT_DAY
    assert futures_bars.parse_near_month(stored) == futures_bars.parse_near_month(
        csv_answer()
    )
    # A JSON answer stays the list it is.
    assert futures_bars.capture_form(json_answer()) == json_answer()


def test_empty_values_of_the_csv_are_read_as_missing():
    rows = [ROWS_1106[0].replace("38888,40690,37694", "-,NULL,")]

    bar = futures_bars.parse_near_month(csv_answer(rows))

    assert (bar.open, bar.high, bar.low, bar.close) == (None, None, None, 39786.0)
    assert bar.price_reason == futures_bars.SOURCE_MISSING_OHLC


@pytest.mark.parametrize(
    "answer,message",
    [
        (b"<html>error</html>", "HTML page"),
        (csv_answer(header=HEADER.replace("交易時段", "時段")), "no 交易時段 column"),
        (csv_answer(rows=["20261106,TX,202611"]), "row has 3 columns"),
        (b"", "answered nothing"),
        (bytes([0xB0, 0xA1, 0xFF]), "neither a JSON list nor a UTF-8 CSV"),
        (
            csv_answer(rows=[ROWS_1106[0], "20261109" + ROWS_1106[2][8:]]),
            "do not share one readable date",
        ),
        (csv_answer(rows=ROWS_1106[1:]), "has 0 TX 202611 regular rows"),
    ],
    ids=[
        "html",
        "no-session-column",
        "short-row",
        "empty",
        "not-utf8",
        "two-dates",
        "no-near-month",
    ],
)
def test_an_unreadable_answer_is_refused(answer, message):
    with pytest.raises(OfficialDataError, match=message):
        futures_bars.parse_near_month(futures_bars.capture_form(answer))


def test_fetch_json_hands_back_the_csv_bytes_only_when_asked(monkeypatch):
    monkeypatch.setattr(sources, "_throttle_official_host", lambda url: None)
    url = sources.TAIFEX_DAILY_FUTURES_ENDPOINT
    monkeypatch.setattr(
        sources.httpx,
        "get",
        lambda *args, **kwargs: httpx.Response(
            200, content=csv_answer(), request=httpx.Request("GET", url)
        ),
    )

    assert sources.fetch_json(url, text_fallback=True) == csv_answer()
    with pytest.raises(OfficialDataError, match="non-JSON"):
        sources.fetch_json(url)


def test_the_collect_read_of_a_csv_answer_gives_the_bar(monkeypatch):
    """The production fetcher (fetch_json) with the CSV answer: the #552 warning is gone."""
    monkeypatch.setattr(sources, "_throttle_official_host", lambda url: None)
    url = sources.TAIFEX_DAILY_FUTURES_ENDPOINT
    monkeypatch.setattr(
        sources.httpx,
        "get",
        lambda *args, **kwargs: httpx.Response(
            200, content=csv_answer(), request=httpx.Request("GET", url)
        ),
    )

    bars, payloads, warnings = sources.fetch_latest_futures(
        sources.fetch_json, REPORT_DAY
    )

    assert warnings == []
    assert [bar.trading_date for bar in bars] == [REPORT_DAY]
    assert bars[0].payload_sha256 == payloads[0].sha256
    assert (payloads[0].source, payloads[0].data_as_of) == ("taifex", "2026-11-06")
    assert payloads[0].payload["format"] == "csv"


# --- AC-2: the session the report holds -----------------------------------------


def test_a_report_of_an_earlier_session_gives_that_session_and_a_warning():
    bars, payloads, warnings = sources.fetch_latest_futures(
        lambda url, **kwargs: csv_answer(), COLLECT_DAY
    )

    assert [bar.trading_date for bar in bars] == [REPORT_DAY]
    assert warnings == [
        "futures bars not yet published for TAIFEX TX 2026-11-09: "
        "DailyMarketReportFut reports 2026-11-06"
    ]
    # Non-core: the collect stays successful.
    assert pipeline.split_collect_warnings(warnings) == ([], warnings)
    # The report of the collect day itself has no warning.
    assert sources.fetch_latest_futures(lambda url: json_answer(), REPORT_DAY)[2] == []


def _seed_session(db, day: date) -> None:
    """A verified TAIEX session (a fixture-source row counts, app.coverage)."""
    taiex = db.scalar(select(Instrument).where(Instrument.symbol == "TAIEX"))
    if taiex is None:
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
    db.add(
        MarketBar(
            instrument_id=taiex.id,
            trading_date=day,
            open=24000.0,
            high=24000.0,
            low=24000.0,
            close=24000.0,
            adj_close=24000.0,
            volume=0,
            turnover=0.0,
            source="twse_fixture",
            data_as_of=datetime.combine(day, datetime.min.time()),
        )
    )
    db.flush()


def _raw(db, sha: str) -> int:
    run = IngestionRun(
        run_type="collect",
        source="official",
        run_date=COLLECT_DAY,
        status="running",
        started_at=datetime(2026, 11, 9, 13, 30),
    )
    db.add(run)
    db.flush()
    raw = RawPayload(
        ingestion_run_id=run.id,
        source="taifex",
        endpoint=sources.TAIFEX_DAILY_FUTURES_ENDPOINT,
        sha256=sha,
        data_as_of=REPORT_DAY.isoformat(),
        collected_at=datetime(2026, 11, 9, 13, 30),
    )
    db.add(raw)
    db.flush()
    return raw.id


def _tx(db) -> list[MarketBar]:
    return db.scalars(
        select(MarketBar)
        .join(Instrument, Instrument.id == MarketBar.instrument_id)
        .where(Instrument.exchange == "TAIFEX", Instrument.symbol == "TX")
        .order_by(MarketBar.trading_date)
    ).all()


def _store(db, bars, **kwargs):
    warnings: list[str] = []
    raw_id = _raw(db, "csv")
    result = pipeline.store_collect_futures_bars(
        db, bars, lambda _sha: raw_id, warnings, **kwargs
    )
    return result, warnings


def test_the_report_session_is_written_when_verified_and_missing(db):
    _seed_session(db, REPORT_DAY)
    bar = futures_bars.parse_near_month(csv_answer())

    result, warnings = _store(db, [bar])

    assert warnings == []
    assert result["counts"]["inserted"] == 1
    assert result["report_dates"] == ["2026-11-06"]
    [row] = _tx(db)
    assert (row.trading_date, row.source, row.close) == (
        REPORT_DAY,
        "taifex_daily_futures",
        39786.0,
    )


def test_a_report_session_already_stored_is_not_rewritten(db):
    _seed_session(db, REPORT_DAY)
    bar = futures_bars.parse_near_month(csv_answer())
    # The website history stored the session first, with the same values.
    raw_id = _raw(db, "site")
    futures_bars.store_futures_bars(
        db, [bar], lambda _sha: raw_id, source="taifex_futdatadown"
    )
    stored = _tx(db)[0]
    before = (stored.source, stored.raw_payload_id, stored.collected_at)

    result, warnings = _store(db, [bar], force=True)

    assert warnings == []  # the same session from both reports: no conflict
    assert result["counts"]["kept_other_source"] == 1
    assert result["counts"]["inserted"] == result["counts"]["replaced"] == 0
    [row] = _tx(db)
    assert (row.source, row.raw_payload_id, row.collected_at) == before

    # A second collect of the same report keeps its own row as it is.
    db.delete(row)
    db.flush()
    _store(db, [bar])
    again, warnings = _store(db, [bar])
    assert again["counts"]["unchanged"] == 1 and warnings == []


def test_a_report_session_that_is_not_verified_is_not_written(db):
    bar = futures_bars.parse_near_month(csv_answer())

    result, warnings = _store(db, [bar])

    assert _tx(db) == []
    assert result["unverified_dates"] == ["2026-11-06"]
    assert warnings == [
        "futures bars skipped TAIFEX TX 2026-11-06: not a verified session"
    ]
    assert pipeline.split_collect_warnings(warnings) == ([], warnings)


def test_the_collect_own_taiex_day_counts_as_verified(db):
    # The collect's TAIEX row is in its own run, still running: not yet verified.
    bar = futures_bars.parse_near_month(csv_answer())

    result, warnings = _store(db, [bar], current_sessions={REPORT_DAY})

    assert warnings == [] and result["counts"]["inserted"] == 1
    assert [row.trading_date for row in _tx(db)] == [REPORT_DAY]
