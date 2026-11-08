"""TX near-month history from the TAIFEX website download futDataDown (Issue #563).

The CSV fixtures copy the format of the #552 probe (19 columns, cp950, the
regular and after-hours rows of every contract month, calendar spreads, a
trailing empty column), but every number is made up: the TAIFEX terms do not
allow its website content to be republished, and this repository is public.
"""

from __future__ import annotations

import socket
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import coverage
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import (
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
    TechnicalIndicator,
)
from worker import futures_bars, sources
from worker import futures_history as fh
from worker.index_bars import Month
from worker.sources import OfficialDataError

HEADER = ",".join(fh.FIELDS)
# 2024-10: the third Wednesday is 10/16, 202410's last trading day.
OCT = Month(2024, 10)
OCT_SESSIONS = [
    day
    for day in (date(2024, 10, 1) + timedelta(days=offset) for offset in range(31))
    if day.weekday() < 5 and day != date(2024, 10, 10)  # National Day
]


@pytest.fixture(autouse=True)
def no_network(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in futures history tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'futures.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    made = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield made
    engine.dispose()


def _close(day: date, contract: str) -> int:
    """A made-up close: rises one point a day, ten points per later contract."""
    offset = (int(contract[:4]) * 12 + int(contract[4:])) - (day.year * 12 + day.month)
    return 20000 + day.toordinal() % 1000 + 10 * offset


def _row(day: date, month: str, session: str, close: int | None = None, **cells) -> str:
    close = _close(day, month[:6]) if close is None else close
    regular = session == "一般"
    values = {
        "交易日期": f"{day:%Y/%m/%d}",
        "契約": "TX",
        # The site pads the month column with spaces.
        "到期月份(週別)": f"{month}  ",
        "開盤價": str(close - 30),
        "最高價": str(close + 40),
        "最低價": str(close - 50),
        "收盤價": str(close),
        "漲跌價": "12",
        "漲跌%": "0.06%",
        "成交量": str(50000 if regular else 20000),
        "結算價": str(close - 2) if regular else "-",
        "未沖銷契約數": "60000" if regular else "-",
        "最後最佳買價": str(close - 1),
        "最後最佳賣價": str(close + 1),
        "歷史最高價": "24000",
        "歷史最低價": "17000",
        "是否因訊息面暫停交易": "",
        "交易時段": session,
        "價差對單式委託成交量": "",
    }
    values.update(cells)
    # Every data row ends with an empty 20th column, as the download does.
    return ",".join(values[name] for name in fh.FIELDS) + ","


def _session_rows(day: date) -> list[str]:
    near = futures_bars.near_month(day)
    year, month = int(near[:4]), int(near[4:])
    following = f"{year + (month == 12):04d}{month % 12 + 1:02d}"
    previous = f"{day.year:04d}{day.month:02d}"
    rows = []
    # On and after the roll the expiring month is still listed, before the near one.
    if previous != near:
        rows += [_row(day, previous, "一般"), _row(day, previous, "盤後")]
    rows += [
        _row(day, near, "一般"),
        _row(day, near, "盤後"),
        _row(day, following, "一般"),
        _row(day, following, "盤後"),
        # A calendar spread of the near month: never the near month itself.
        _row(day, f"{near}/{following}  ", "一般", close=45),
    ]
    return rows


def csv_text(days, extra=()) -> str:
    lines = [HEADER]
    for day in days:
        lines += _session_rows(day)
    lines += list(extra)
    return "\r\n".join(lines) + "\r\n"


def csv_bytes(days, extra=()) -> bytes:
    return csv_text(days, extra).encode("cp950")


def _request(month=OCT, today=date(2026, 11, 9)):
    return fh.request_for(month, today)


# --- parsing ------------------------------------------------------------------


def test_the_near_month_regular_row_is_taken_around_the_third_wednesday():
    parsed = fh.parse_month(fh.decode(csv_bytes(OCT_SESSIONS)), _request())

    by_day = {bar.trading_date: bar for bar in parsed.bars}
    assert sorted(by_day) == OCT_SESSIONS and parsed.unusable_dates == []
    # The day before the roll is 202410, the last trading day already 202411.
    assert by_day[date(2024, 10, 15)].contract_month == "202410"
    assert by_day[date(2024, 10, 16)].contract_month == "202411"
    assert by_day[date(2024, 10, 17)].contract_month == "202411"
    bar = by_day[date(2024, 10, 16)]
    close = _close(date(2024, 10, 16), "202411")
    # The regular session, not the expiring month, after-hours or the spread.
    assert (bar.open, bar.high, bar.low, bar.close) == (
        close - 30,
        close + 40,
        close - 50,
        close,
    )
    assert (bar.volume, bar.settlement_price, bar.open_interest) == (
        50000,
        close - 2,
        60000,
    )
    assert bar.price_reason is None


def test_december_rolls_into_january_of_the_next_year():
    december = Month(2023, 12)
    days = [date(2023, 12, 19), date(2023, 12, 20)]  # third Wednesday 12/20

    parsed = fh.parse_month(fh.decode(csv_bytes(days)), _request(december))

    assert [bar.contract_month for bar in parsed.bars] == ["202312", "202401"]


def test_the_answer_is_read_as_cp950():
    content = csv_bytes([date(2024, 10, 1)])

    assert "交易時段".encode("cp950") in content
    with pytest.raises(UnicodeDecodeError):
        content.decode("utf-8")
    assert fh.decode(content).startswith("交易日期,契約,到期月份(週別)")
    with pytest.raises(OfficialDataError, match="cp950"):
        fh.decode(b"\xff\xfe\xfa")


def test_a_missing_open_is_left_empty_and_a_day_without_close_is_listed():
    day, other = date(2024, 10, 1), date(2024, 10, 2)
    text = csv_text([]) + "\r\n".join(
        [
            _row(day, "202410", "一般", 開盤價="-"),
            _row(other, "202410", "一般", 收盤價="-", 成交量="0"),
        ]
    )

    parsed = fh.parse_month(text, _request())

    assert [(b.open, b.high, b.low) for b in parsed.bars] == [(None, None, None)]
    assert parsed.bars[0].price_reason == "source_missing_ohlc"
    assert parsed.unusable_dates == [other.isoformat()]


def test_a_day_with_after_hours_rows_only_is_not_a_gap():
    """Before a session trades, the CSV already files the evening before under it (11/09 01:15)."""
    friday, monday = date(2024, 10, 4), date(2024, 10, 7)
    text = csv_text(
        [friday],
        [_row(monday, "202410", "盤後"), _row(monday, "202411", "盤後")],
    )

    parsed = fh.parse_month(text, _request())

    assert [bar.trading_date for bar in parsed.bars] == [friday]
    assert parsed.unusable_dates == []
    assert parsed.after_hours_only_dates == [monday.isoformat()]


def test_a_day_with_regular_rows_but_no_near_month_is_listed():
    day = date(2024, 10, 4)
    text = csv_text([], [_row(day, "202411", "一般"), _row(day, "202410", "盤後")])

    parsed = fh.parse_month(text, _request())

    assert parsed.bars == [] and parsed.unusable_dates == [day.isoformat()]


@pytest.mark.parametrize(
    "text,message",
    [
        (
            '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN">\r\n<html>日期時間錯誤</html>',
            "HTML",
        ),
        ("交易日期,契約,到期月份\r\n", "header"),
        (HEADER + "\r\n2024/10/01,TX,202410\r\n", "columns"),
        (csv_text([date(2024, 9, 30)]), "outside"),
        (csv_text([], [_row(date(2024, 10, 1), "202410", "一般", 契約="MTX")]), "MTX"),
        ("", "nothing"),
    ],
)
def test_an_answer_that_is_not_the_month_csv_is_rejected_whole(text, message):
    with pytest.raises(OfficialDataError, match=message):
        fh.parse_month(text, _request())


def test_a_month_is_one_request_and_never_past_today():
    request = fh.request_for(Month(2026, 11), date(2026, 11, 9))

    assert request.form == {
        "down_type": "1",
        "commodity_id": "TX",
        "queryStartDate": "2026/11/01",
        "queryEndDate": "2026/11/09",
    }
    assert request.endpoint.startswith(fh.ENDPOINT + "?down_type=1&commodity_id=TX")
    assert fh.request_for(OCT, date(2026, 11, 9)).end == date(2024, 10, 31)


# --- backfill -------------------------------------------------------------------


class SiteGet:
    """``get`` for the backfill: one month's CSV from the sessions; records requests."""

    def __init__(self, sessions, *, fail=()):
        self.sessions = sessions
        self.fail = set(fail)
        self.requests: list[tuple[str, str]] = []

    def __call__(self, request):
        self.requests.append(
            (request.form["queryStartDate"], request.form["queryEndDate"])
        )
        if request.month.label in self.fail:
            return "<html>日期時間錯誤</html>".encode("cp950")
        days = [d for d in self.sessions if request.start <= d <= request.end]
        return csv_bytes(days)


SEP_OCT = [
    day
    for day in (date(2024, 9, 2) + timedelta(days=offset) for offset in range(60))
    if day.weekday() < 5 and day.month in (9, 10) and day != date(2024, 10, 10)
]


def _seed_openapi(db, day: date) -> None:
    """A TX row the OpenAPI collect wrote (taifex_daily_futures, raw source taifex)."""
    run = IngestionRun(
        run_type="collect",
        source="official",
        run_date=day,
        status="success",
        started_at=datetime(2026, 11, 9),
    )
    db.add(run)
    db.flush()
    raw = RawPayload(
        ingestion_run_id=run.id,
        source="taifex",
        endpoint=sources.TAIFEX_DAILY_FUTURES_ENDPOINT,
        sha256="openapi",
        data_as_of=day.isoformat(),
        collected_at=datetime(2026, 11, 9),
    )
    db.add(raw)
    db.flush()
    bar = futures_bars.FuturesBar(
        trading_date=day,
        contract_month=futures_bars.near_month(day),
        open=1.0,
        high=3.0,
        low=0.5,
        close=2.0,
        volume=7,
        settlement_price=2.0,
        open_interest=9,
        price_reason=None,
        payload_sha256="openapi",
    )
    futures_bars.store_futures_bars(db, [bar], lambda _sha: raw.id)
    db.commit()


def _backfill(factory, get, *, first=Month(2024, 9), last=Month(2024, 10), **kwargs):
    sleeps: list[float] = []
    with factory() as db:
        result = fh.backfill_futures_history(
            db,
            first=first,
            last=last,
            get=get,
            sleep=sleeps.append,
            today=date(2026, 11, 9),
            **kwargs,
        )
    return result, sleeps


def _tx(db):
    return db.scalars(
        select(MarketBar)
        .join(Instrument, Instrument.id == MarketBar.instrument_id)
        .where(Instrument.exchange == "TAIFEX", Instrument.symbol == "TX")
        .order_by(MarketBar.trading_date)
    ).all()


def test_the_backfill_writes_its_own_source_and_stops_before_the_openapi_rows(
    factory,
):
    first_openapi = date(2024, 10, 21)
    with factory() as db:
        _seed_openapi(db, first_openapi)
    get = SiteGet(SEP_OCT)

    result, sleeps = _backfill(factory, get)

    assert result["status"] == "success", result
    # One request per calendar month, 3 seconds apart.
    assert get.requests == [("2024/09/01", "2024/09/30"), ("2024/10/01", "2024/10/31")]
    assert sleeps == [3.0]
    assert result["openapi_first_day"] == first_openapi.isoformat()
    history = [day for day in SEP_OCT if day < first_openapi]
    assert result["counts"]["inserted"] == len(history)
    with factory() as db:
        rows = _tx(db)
        # The history, then the OpenAPI row: no overlap, no gap.
        assert [row.trading_date for row in rows] == history + [first_openapi]
        assert {row.source for row in rows[:-1]} == {"taifex_futdatadown"}
        assert rows[-1].source == "taifex_daily_futures"
        assert rows[-1].close == 2.0  # untouched
        raw = db.get(RawPayload, rows[0].raw_payload_id)
        run = db.get(IngestionRun, result["run_id"])
        assert (raw.source, raw.ingestion_run_id) == ("taifex_web", run.id)
        assert raw.endpoint.startswith(fh.ENDPOINT)
        assert raw.data_as_of == "2024-09-30"
        assert (run.run_type, run.source) == ("futures_bar_backfill", "official")
        manifest = run.metadata_json["coverage_manifest"]
        assert manifest["2024-10"]["from_openapi_day"] == len(
            [day for day in SEP_OCT if day >= first_openapi]
        )
        assert [row.contract_month for row in rows if row.trading_date.month == 10][
            :3
        ] == ["202410", "202410", "202410"]
        # Indicators are rebuilt over the whole TX series.
        assert db.scalar(
            select(func.count())
            .select_from(TechnicalIndicator)
            .where(TechnicalIndicator.instrument_id == rows[0].instrument_id)
        ) == len(rows)
        # A TX row is never a session of the stocks.
        assert coverage.verified_taiex_sessions(db) == []

    # A rerun changes nothing.
    again, _ = _backfill(factory, SiteGet(SEP_OCT))
    assert again["counts"]["unchanged"] == len(history)
    assert again["counts"]["inserted"] == 0


def test_without_openapi_rows_the_history_runs_to_the_requested_end(factory):
    result, _ = _backfill(factory, SiteGet(SEP_OCT))

    assert result["counts"]["inserted"] == len(SEP_OCT)
    assert result["openapi_first_day"] is None


def test_without_openapi_rows_today_is_left_to_the_daily(factory):
    """PR #565 review: today's session is the daily's OpenAPI row, not the site's."""
    today = date(2024, 10, 18)
    sessions = [day for day in SEP_OCT if day <= today]
    with factory() as db:
        result = fh.backfill_futures_history(
            db,
            first=Month(2024, 10),
            last=Month(2024, 10),
            get=SiteGet(sessions),
            sleep=lambda _: None,
            today=today,
        )

    assert (
        result["counts"]["inserted"] == len([d for d in sessions if d.month == 10]) - 1
    )
    with factory() as db:
        assert _tx(db)[-1].trading_date == date(2024, 10, 17)


def test_the_site_is_spaced_like_every_official_host(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(sources, "_throttle_official_host", calls.append)

    class Response:
        status_code = 200
        content = b"x"

    import httpx

    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: Response())

    assert fh.fetch_month(_request()) == b"x"
    assert calls == [fh.ENDPOINT]
    assert sources.OFFICIAL_HOST_MIN_INTERVAL_SECONDS["www.taifex.com.tw"] == 3.0


def test_the_openapi_collect_never_overwrites_a_history_row(factory):
    _backfill(factory, SiteGet(SEP_OCT))
    day = SEP_OCT[-1]
    with factory() as db:
        before = _tx(db)[-1]
        stored = (before.source, before.close, before.raw_payload_id)
        bar = futures_bars.FuturesBar(
            trading_date=day,
            contract_month=futures_bars.near_month(day),
            open=1.0,
            high=3.0,
            low=0.5,
            close=2.0,
            volume=7,
            settlement_price=2.0,
            open_interest=9,
            price_reason=None,
        )
        result = futures_bars.store_futures_bars(
            db, [bar], lambda _sha: before.raw_payload_id, force=True
        )
        db.flush()
        after = _tx(db)[-1]

        assert result.counts["conflict"] == 1
        assert result.conflicts[0]["stored"]["source"] == "taifex_futdatadown"
        assert (after.source, after.close, after.raw_payload_id) == stored


def test_a_rejected_month_is_a_warning_and_the_other_months_are_written(factory):
    result, _ = _backfill(factory, SiteGet(SEP_OCT, fail={"2024-09"}))

    assert result["status"] == "partial"
    assert result["warnings"][0].startswith(
        "futures history unavailable for TAIFEX TX 2024-09"
    )
    with factory() as db:
        assert {row.trading_date.month for row in _tx(db)} == {10}
        run = db.get(IngestionRun, result["run_id"])
        failed = run.metadata_json["coverage_manifest"]["2024-09"]
        assert failed["status"] == "failed" and "HTML" in failed["error"]
        # The HTML answer is kept as raw evidence.
        assert db.get(RawPayload, failed["raw_payload_id"]).source == "taifex_web"


def test_days_before_the_history_start_are_not_written(factory):
    august = [date(2023, 8, 30), date(2023, 8, 31), date(2023, 9, 1)]

    result, _ = _backfill(
        factory, SiteGet(august), first=Month(2023, 8), last=Month(2023, 9)
    )

    assert fh.HISTORY_START == date(2023, 9, 1)
    with factory() as db:
        assert [row.trading_date for row in _tx(db)] == [date(2023, 9, 1)]
    assert result["counts"]["inserted"] == 1


class Stopped(SiteGet):
    def __call__(self, request):
        if self.requests:
            raise KeyboardInterrupt
        return super().__call__(request)


def test_a_backfill_stopped_midway_changes_no_row(factory):
    with pytest.raises(KeyboardInterrupt):
        _backfill(factory, Stopped(SEP_OCT))

    with factory() as db:
        assert _tx(db) == []
        run = db.scalar(
            select(IngestionRun).where(IngestionRun.run_type == fh.RUN_TYPE)
        )
        assert run.status == "running"


def test_the_backfill_refuses_a_month_after_the_current_one(factory):
    with factory() as db, pytest.raises(ValueError, match="after the current month"):
        fh.backfill_futures_history(
            db,
            first=Month(2026, 11),
            last=Month(2026, 12),
            get=SiteGet([]),
            sleep=lambda _: None,
            today=date(2026, 11, 9),
        )


@pytest.mark.parametrize("command", ["backfill", "us-history", "futures-history"])
def test_the_history_commands_hold_maintenance_mode(command):
    from argparse import Namespace

    from worker.cli import maintenance_guarded

    args = Namespace(command="index-bars", index_bars_command=command)

    assert maintenance_guarded(args) == f"index-bars {command}"
