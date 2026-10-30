"""Earliest execution date from the official trading calendar (#294).

The fixtures are TWSE's yearly holiday schedules as downloaded on
2026-10-26 (2027 was not published yet).
"""

from __future__ import annotations

import copy
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, enable_sqlite_foreign_keys
from app.models import (
    CorporateAction,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
    Signal,
    TechnicalFeature,
    TradingCalendarDay,
)
from app.trading_calendar import classify, next_session
from worker import pipeline
from worker import sources
from worker import trading_calendar
from worker.strategy_levels import compute_strategy_levels

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "trading_calendar"


def schedule(year: int) -> dict:
    return json.loads((FIXTURES / f"{year}.json").read_text(encoding="utf-8"))


def published(year: int, rows: list[list[str]]) -> dict:
    """A fixture schedule for a year TWSE has not published yet."""

    payload = copy.deepcopy(schedule(2027))
    payload.update(date=f"{year}0101", queryYear=year, data=rows, total=len(rows))
    return payload


class Fetcher:
    def __init__(self, payloads: dict[int, object]):
        self.payloads = payloads
        self.urls: list[str] = []

    def __call__(self, url, **_kwargs):
        self.urls.append(url)
        year = int(url.split("date=")[1][:4])
        payload = self.payloads.get(year)
        if isinstance(payload, Exception):
            raise payload
        return copy.deepcopy(payload)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    engine = create_engine("sqlite:///:memory:")
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


def store(db, payloads: dict[int, object], *, run_date=date(2026, 10, 26)):
    return trading_calendar.store_trading_calendar(
        db, payloads, run_date=run_date, fetcher=Fetcher(payloads)
    )


# ---- the schedule and its one classification rule ----


def test_every_row_of_the_official_schedules_is_closed_or_a_trading_notice():
    for year in (2025, 2026):
        rows = trading_calendar.parse_schedule(schedule(year), year)
        assert rows and {row.kind for row in rows} <= {"closed", "trading"}
    rows = trading_calendar.parse_schedule(schedule(2026), 2026)
    assert [row.calendar_date for row in rows if row.kind == "trading"] == [
        date(2026, 1, 2),
        date(2026, 2, 11),
        date(2026, 2, 23),
    ]
    closed = {row.calendar_date for row in rows if row.kind == "closed"}
    # The make-up holidays say 補假, not 放假.
    assert {
        date(2026, 2, 27),
        date(2026, 4, 3),
        date(2026, 4, 6),
        date(2026, 10, 9),
        date(2026, 10, 26),
    } <= closed
    # 市場無交易，僅辦理結算交割作業
    assert {date(2026, 2, 12), date(2026, 2, 13)} <= closed
    assert len(closed) == 24


@pytest.mark.parametrize(
    "name, description, kind",
    [
        ("國曆新年開始交易日", "國曆新年開始交易。", "trading"),
        ("農曆春節前最後交易日", "農曆春節前最後交易。", "trading"),
        ("國慶日", "國慶日為10月10日適逢星期六，於10月9日（星期五）補假。", "closed"),
        ("市場無交易，僅辦理結算交割作業", "", "closed"),
        ("農曆除夕前一日", "調整放假，於2月8日補行上班，但不交易亦不交割。", "closed"),
        ("颱風", "", "unknown"),
    ],
)
def test_classify(name, description, kind):
    assert classify(name, description) == kind


def test_an_unpublished_year_has_no_rows():
    assert trading_calendar.parse_schedule(schedule(2027), 2027) == []


@pytest.mark.parametrize(
    "change, message",
    [
        ({"stat": "很抱歉，沒有符合條件的資料!"}, "stat is not ok"),
        ({"queryYear": 2025}, "queryYear"),
        ({"data": [["2025-12-31", "x", "放假"]]}, "outside the year"),
        (
            {"data": [["2026-01-01", "a", "放假"], ["2026-01-01", "b", "放假"]]},
            "listed twice",
        ),
        ({"data": [["2026-13-01", "a", "放假"]]}, "invalid date"),
        ({"data": [["2026-01-01", "", "放假"]]}, "has no name"),
        ({"fields": ["Date", "Name"]}, "fields"),
    ],
)
def test_a_payload_that_is_not_the_year_schedule_is_rejected(change, message):
    payload = schedule(2026)
    payload.update(change)
    with pytest.raises(sources.OfficialDataError, match=message):
        trading_calendar.parse_schedule(payload, 2026)


TRADING_NOTICES = [
    "2025-01-02",  # 國曆新年開始交易日
    "2025-01-22",  # 農曆春節前最後交易日
    "2025-02-03",  # 農曆春節後開始交易日
    "2026-01-02",
    "2026-02-11",
    "2026-02-23",
]
# The eight make-up holidays (補假, no 放假) the old markers missed.
MAKE_UP_HOLIDAYS = [
    "2025-05-30",
    "2025-09-29",
    "2025-10-24",
    "2026-02-27",
    "2026-04-03",
    "2026-04-06",
    "2026-10-09",
    "2026-10-26",
]


def openapi_rows(rows: list[list[str]]) -> list[dict[str, str]]:
    """The OpenAPI holidaySchedule shape the backfill reads (ROC dates)."""

    return [
        {
            "Name": name,
            "Date": f"{int(day[:4]) - 1911}{day[5:7]}{day[8:]}",
            "Weekday": "",
            "Description": description,
        }
        for day, name, description in rows
    ]


def test_the_backfill_excludes_exactly_the_closed_days_of_the_schedule():
    rows = [row for year in (2025, 2026) for row in schedule(year)["data"]]
    assert len(rows) == 51
    assert [
        row[0] for row in rows if "補假" in row[2] and "放假" not in row[2]
    ] == MAKE_UP_HOLIDAYS
    # A row neither closed nor a trading notice is not a closure (#294 review M1).
    unknown = ["2026-07-15", "颱風", ""]
    excluded = sources._official_non_trading_dates(
        openapi_rows([*rows, unknown]), date(2025, 1, 1), date(2026, 12, 31)
    )
    closed = {date.fromisoformat(row[0]) for row in rows} - {
        date.fromisoformat(day) for day in TRADING_NOTICES
    }
    assert len(closed) == 45
    assert excluded == closed
    assert {date.fromisoformat(day) for day in MAKE_UP_HOLIDAYS} <= excluded
    assert not {date.fromisoformat(day) for day in TRADING_NOTICES} & excluded
    assert date(2026, 7, 15) not in excluded


# ---- storing ----


def test_stored_rows_keep_source_raw_and_classification(db):
    result = store(db, {2026: schedule(2026), 2027: schedule(2027)})
    assert result["status"] == "success"
    assert result["years"]["2026"]["status"] == "inserted"
    assert result["years"]["2027"] == {
        "status": "unpublished",
        "raw_payload_id": result["years"]["2027"]["raw_payload_id"],
    }
    rows = db.scalars(select(TradingCalendarDay)).all()
    assert len(rows) == 27 and {row.year for row in rows} == {2026}
    raw = db.get(RawPayload, rows[0].raw_payload_id)
    assert raw.endpoint == trading_calendar.year_endpoint(2026)
    assert raw.endpoint == (
        "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule"
        "?date=20260101&response=json"
    )
    assert {row.raw_payload_id for row in rows} == {raw.id}
    assert all(row.source == "twse_holiday_schedule" for row in rows)
    assert all(row.collected_at == raw.collected_at for row in rows)
    oct26 = next(row for row in rows if row.calendar_date == date(2026, 10, 26))
    assert (oct26.kind, oct26.name) == ("closed", "臺灣光復暨金門古寧頭大捷紀念日")
    run = db.get(IngestionRun, result["run_id"])
    assert (run.run_type, run.status, run.records) == (
        "trading_calendar",
        "success",
        27,
    )


def test_an_unchanged_payload_is_not_captured_or_written_again(db):
    first = store(db, {2026: schedule(2026), 2027: schedule(2027)})
    raws = db.scalar(select(func.count(RawPayload.id)))
    again = store(db, {2026: schedule(2026), 2027: schedule(2027)})
    assert again["years"]["2026"] == {
        "status": "unchanged",
        "raw_payload_id": first["years"]["2026"]["raw_payload_id"],
    }
    assert again["records"] == 0
    assert db.scalar(select(func.count(RawPayload.id))) == raws


def test_an_amended_year_replaces_its_rows_and_records_the_difference(db):
    store(db, {2026: schedule(2026)})
    amended = schedule(2026)
    amended["data"] = [row for row in amended["data"] if row[0] != "2026-12-25"]
    amended["data"].append(["2026-11-12", "國父誕辰紀念日", "依規定放假1日。"])
    amended["data"].sort()
    result = store(db, {2026: amended})
    year = result["years"]["2026"]
    assert (year["status"], year["added"], year["removed"], year["changed"]) == (
        "updated",
        ["2026-11-12"],
        ["2026-12-25"],
        [],
    )
    rows = db.scalars(select(TradingCalendarDay)).all()
    assert {row.raw_payload_id for row in rows} == {year["raw_payload_id"]}
    assert next_session(db, date(2026, 11, 11)).date == date(2026, 11, 13)
    assert next_session(db, date(2026, 12, 24)).date == date(2026, 12, 25)


def test_an_empty_answer_for_a_stored_year_keeps_the_rows_and_warns(db):
    store(db, {2026: schedule(2026)})
    result = store(db, {2026: published(2026, [])})
    assert result["status"] == "partial"
    assert result["years"]["2026"]["status"] == "kept"
    assert "came back empty" in result["warnings"][0]
    assert db.scalar(select(func.count(TradingCalendarDay.id))) == 27


def test_a_failed_or_rejected_year_writes_nothing_and_warns(db):
    bad = schedule(2026)
    bad["queryYear"] = 2025
    result = store(
        db, {2026: bad, 2027: sources.OfficialDataError("official endpoint failed")}
    )
    assert result["status"] == "failed"
    assert {year["status"] for year in result["years"].values()} == {"failed"}
    assert len(result["warnings"]) == 2
    assert db.scalar(select(func.count(TradingCalendarDay.id))) == 0
    run = db.get(IngestionRun, result["run_id"])
    assert run.status == "failed" and "queryYear" in run.error


def test_the_cli_runner_asks_for_the_target_year_and_the_next(db, monkeypatch):
    factory = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    fetcher = Fetcher({2026: schedule(2026), 2027: schedule(2027)})
    result = trading_calendar.run_trading_calendar(date(2026, 10, 26), fetcher=fetcher)
    assert result["status"] == "success"
    assert fetcher.urls == [
        trading_calendar.year_endpoint(2026),
        trading_calendar.year_endpoint(2027),
    ]


# ---- the next session ----


@pytest.mark.parametrize(
    "day, expected",
    [
        (date(2026, 10, 16), date(2026, 10, 19)),  # Friday -> Monday
        (date(2026, 10, 8), date(2026, 10, 12)),  # 10/9 make-up holiday, weekend
        (date(2026, 2, 11), date(2026, 2, 23)),  # Lunar New Year closure
        (date(2026, 2, 26), date(2026, 3, 2)),  # 2/27 make-up holiday
        (date(2026, 12, 24), date(2026, 12, 28)),  # 12/25 holiday, weekend
        (date(2026, 1, 1), date(2026, 1, 2)),  # a trading notice is a session
        # 10/23 was a typhoon closure (daily run 11, non_trading_day): not in
        # the official schedule, so not known on 10/22's night (V1_SPEC).
        (date(2026, 10, 22), date(2026, 10, 23)),
        (date(2026, 10, 23), date(2026, 10, 27)),  # weekend, 10/26 make-up
    ],
)
def test_the_next_session_follows_the_official_schedule(db, day, expected):
    store(db, {2026: schedule(2026), 2027: schedule(2027)})
    answer = next_session(db, day)
    assert (answer.date, answer.reason) == (expected, None)
    assert answer.raw_payload_ids == (
        db.scalar(select(TradingCalendarDay.raw_payload_id).limit(1)),
    )


def test_an_unpublished_next_year_leaves_no_date(db):
    store(db, {2026: schedule(2026), 2027: schedule(2027)})
    answer = next_session(db, date(2026, 12, 31))
    assert (answer.date, answer.reason, answer.missing_year) == (
        None,
        "calendar_year_missing",
        2027,
    )
    db.info.clear()
    # Once TWSE publishes 2027 (fixture rows), the walk crosses the year.
    stored = store(
        db,
        {
            2027: published(
                2027, [["2027-01-01", "中華民國開國紀念日", "依規定放假1日。"]]
            )
        },
    )
    answer = next_session(db, date(2026, 12, 31))
    assert (answer.date, answer.reason) == (date(2027, 1, 4), None)
    # Only 2027's rows were read (1/1 to 1/4).
    assert answer.raw_payload_ids == (stored["years"]["2027"]["raw_payload_id"],)


def test_no_calendar_or_an_unknown_row_leaves_no_date(db):
    assert next_session(db, date(2026, 10, 8)).reason == "calendar_year_missing"
    db.info.clear()
    store(db, {2026: published(2026, [["2026-10-09", "颱風", ""]])})
    answer = next_session(db, date(2026, 10, 8))
    assert (answer.date, answer.reason) == (None, "calendar_row_unknown")


# ---- signals: the earliest execution date does not need later bars ----

D = date(2026, 10, 8)  # Thursday before the 10/9 make-up holiday


def weekdays_before(day: date, count: int) -> list[date]:
    result: list[date] = []
    cursor = day
    while len(result) < count:
        if cursor.weekday() < 5:
            result.append(cursor)
        cursor -= timedelta(days=1)
    return sorted(result)


def seed_stock(db, *, later_bars=()) -> Instrument:
    instrument = Instrument(
        market="TW",
        exchange="TWSE",
        symbol="2330",
        name="fixture",
        instrument_type="stock",
        status="active",
    )
    db.add(instrument)
    db.flush()
    for day in [*weekdays_before(D, 25), *later_bars]:
        db.add(
            MarketBar(
                instrument_id=instrument.id,
                trading_date=day,
                open=100,
                high=101,
                low=99,
                close=100,
                adj_close=100,
                volume=1000,
                turnover=100000,
                turnover_status="available",
                source="fixture",
            )
        )
    db.add(
        TechnicalFeature(
            instrument_id=instrument.id,
            trading_date=D,
            features_json={"bar_count_60d": 25, "volume": 1000, "atr14": 2},
            source="fixture",
        )
    )
    db.flush()
    return instrument


def signal_dates(db) -> list[tuple]:
    db.flush()
    return [
        (
            signal.earliest_execution_date,
            signal.rule_evidence_json["execution"]["earliest"],
            signal.rule_evidence_json["execution"]
            .get("calendar", {})
            .get("missing_reason", "absent"),
        )
        for signal in db.scalars(select(Signal).order_by(Signal.id)).all()
    ]


@pytest.mark.parametrize(
    "later_bars",
    [
        (),  # the night of D: no later bar yet
        # A replay with later bars stored; the stock itself has no 10/12 bar
        # (suspended), which must not move the market's next session.
        (date(2026, 10, 13), date(2026, 10, 14)),
    ],
)
def test_a_signal_gets_the_next_session_with_or_without_later_bars(db, later_bars):
    store(db, {2026: schedule(2026), 2027: schedule(2027)})
    instrument = seed_stock(db, later_bars=later_bars)
    assert pipeline._upsert_signal(
        db,
        instrument=instrument,
        signal_date=D,
        strategies=pipeline._ensure_strategies(db),
    )
    dates = signal_dates(db)
    assert len(dates) == 2
    assert set(dates) == {(date(2026, 10, 12), "2026-10-12", None)}


def test_without_the_calendar_the_date_stays_empty_even_with_later_bars(db):
    instrument = seed_stock(db, later_bars=(date(2026, 10, 12),))
    pipeline._upsert_signal(
        db,
        instrument=instrument,
        signal_date=D,
        strategies=pipeline._ensure_strategies(db),
    )
    assert set(signal_dates(db)) == {(None, None, "calendar_year_missing")}


def analyze_day(db, day: date) -> dict:
    db.add(
        IngestionRun(
            run_type="collect",
            source="official",
            run_date=day,
            status="success",
            data_as_of=day.isoformat(),
        )
    )
    db.flush()
    return pipeline._analyze_session(db)


def test_analyze_records_the_calendar_status_and_the_signals_without_a_date(db):
    seed_stock(db)
    missing = analyze_day(db, D)
    assert missing["status"] == "success" and missing["signals_upserted"] == 1
    assert missing["execution_calendar"] == {
        "status": "unavailable",
        "reason": "calendar_year_missing",
        "missing_year": 2026,
        "next_session": None,
        "raw_payload_ids": [],
        "signals_without_date": 2,
    }
    store(db, {2026: schedule(2026), 2027: schedule(2027)})
    complete = analyze_day(db, D)
    assert complete["execution_calendar"] == {
        "status": "available",
        "reason": None,
        "missing_year": None,
        "next_session": "2026-10-12",
        "raw_payload_ids": [
            db.scalar(select(TradingCalendarDay.raw_payload_id).limit(1))
        ],
        "signals_without_date": 0,
    }


# ---- strategy_levels: a holiday before an ex-dividend session (#293 L5) ----


def test_strategy_levels_convert_an_action_on_the_session_after_a_holiday(db):
    from test_strategy_levels import T, seed

    # Fixture schedule: 10/22 closed, so T's next session is 10/23, the
    # ex-dividend date.  Without a calendar it was the next weekday (10/22)
    # and the stored 10/23 action was not converted.
    store(
        db,
        {
            2026: published(2026, [["2026-10-22", "fixture", "依規定放假1日。"]]),
            2027: schedule(2027),
        },
    )
    instrument, signals = seed(db, ex_dividend=False)
    db.add(
        CorporateAction(
            instrument_id=instrument.id,
            action_date=date(2026, 10, 23),
            action_type="ex_dividend",
            cash_dividend=0.033,
            stock_dividend_ratio=0.0,
            reference_price=8.87,
            source="fixture",
        )
    )
    db.flush()
    compute_strategy_levels(db, T, now=datetime(2026, 10, 21, 22, 0))
    from test_strategy_levels import level_of

    row = level_of(db, signals["breakout"])
    assert (row.next_session_date, row.price_basis, row.trigger_price) == (
        date(2026, 10, 23),
        "next_session_raw_basis",
        8.9,
    )


# Timestamps written below (#376). `frozen_utcnow` (conftest) makes app.clock answer one
# instant to every caller, so a stamp taken from local time or the real clock stores a
# value other than the one asserted here.


def test_a_calendar_run_and_its_capture_are_stamped_with_the_clock(db, frozen_utcnow):
    first = frozen_utcnow.at
    result = store(db, {2026: schedule(2026)})

    run = db.get(IngestionRun, result["run_id"])
    assert (run.started_at, run.finished_at) == (first, first)
    rows = db.scalars(select(TradingCalendarDay)).all()
    assert rows and {row.collected_at for row in rows} == {first}
    assert db.get(RawPayload, rows[0].raw_payload_id).collected_at == first
