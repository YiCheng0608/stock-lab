"""daily's window backfill of the newest quarters and months (Issue #536).

The pages are the #529／#530 fixtures (test_quarterly_fundamentals,
test_monthly_revenue); the daily run's handling of this step's outcome is in
test_daily_schedule.
"""

from __future__ import annotations

import socket
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import IngestionRun, Instrument
from test_monthly_revenue import NoDataFetcher as NoDataMonths
from test_monthly_revenue import PageFetcher as MonthPages
from test_quarterly_fundamentals import PageFetcher as QuarterPages
from worker import period_backfill as pb
from worker import pipeline, quarterly_fundamentals, sources
from worker.monthly_revenue import Month

# 2026-11-06 12:00 Taipei: inside 115Q3's window (10/31～12/13) and 115/10's
# (11/01～11/20).
NOW = datetime(2026, 11, 6, 4, 0)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch, frozen_utcnow):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in period backfill tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    frozen_utcnow.at = NOW
    return frozen_utcnow


@pytest.fixture
def factory(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'period.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    made = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with made() as db:
        for exchange, symbol in (
            ("TWSE", "2330"),
            ("TWSE", "1101"),
            ("TPEx", "6488"),
            ("TPEx", "1240"),
        ):
            db.add(
                Instrument(
                    market="TW",
                    exchange=exchange,
                    symbol=symbol,
                    name=symbol,
                    instrument_type="stock",
                    status="active",
                )
            )
        db.commit()
    monkeypatch.setattr(pipeline, "SessionLocal", made)
    yield made
    engine.dispose()


def refuse(*_args, **_kwargs):
    raise AssertionError("no request outside the windows")


def labels(today: date) -> tuple[list[str], list[str]]:
    return (
        [quarter.label for quarter in pb.due_quarters(today)],
        [month.label for month in pb.due_months(today)],
    )


@pytest.mark.parametrize(
    ("today", "quarters", "months"),
    [
        # 115Q3: deadlines 11/14 (general) to 11/29 (holding companies).
        (date(2026, 10, 30), [], []),
        (date(2026, 10, 31), ["2026Q2", "2026Q3"], []),
        (date(2026, 11, 6), ["2026Q2", "2026Q3"], ["2026-09", "2026-10"]),
        (date(2026, 11, 20), ["2026Q2", "2026Q3"], ["2026-09", "2026-10"]),
        (date(2026, 11, 21), ["2026Q2", "2026Q3"], []),
        (date(2026, 12, 13), ["2026Q2", "2026Q3"], ["2026-10", "2026-11"]),
        (date(2026, 12, 14), [], ["2026-10", "2026-11"]),
        (date(2026, 12, 21), [], []),
        # The annual report (3/31) is due after Q1 has ended.
        (date(2027, 3, 16), [], ["2027-01", "2027-02"]),
        (date(2027, 3, 21), ["2026Q3", "2026Q4"], []),
        (date(2027, 3, 17), ["2026Q3", "2026Q4"], ["2027-01", "2027-02"]),
        (date(2027, 4, 14), ["2026Q3", "2026Q4"], ["2027-02", "2027-03"]),
        (date(2027, 4, 15), [], ["2027-02", "2027-03"]),
        (date(2027, 4, 30), [], []),
        (date(2027, 5, 1), ["2026Q4", "2027Q1"], ["2027-03", "2027-04"]),
        (date(2027, 6, 13), ["2026Q4", "2027Q1"], ["2027-04", "2027-05"]),
        (date(2027, 6, 14), [], ["2027-04", "2027-05"]),
        (date(2027, 7, 31), ["2027Q1", "2027Q2"], []),
        (date(2027, 9, 14), ["2027Q1", "2027Q2"], ["2027-07", "2027-08"]),
        (date(2027, 9, 15), [], ["2027-07", "2027-08"]),
        (date(2027, 1, 1), [], ["2026-11", "2026-12"]),
    ],
)
def test_the_windows_surround_each_statutory_deadline(today, quarters, months):
    assert labels(today) == (quarters, months)


def test_a_year_of_days_never_asks_for_more_than_twelve_pages():
    day, pages, busy = date(2027, 1, 1), [], 0
    while day.year == 2027:
        quarters, months = pb.due_quarters(day), pb.due_months(day)
        assert len(quarters) <= pb.QUARTERS and len(months) <= pb.MONTHS
        # Consecutive periods, so each part is one backfill with an end and a count.
        assert all(b.previous() == a for a, b in zip(quarters, quarters[1:]))
        assert all(a.next() == b for a, b in zip(months, months[1:]))
        count = 2 * len(quarters) + 4 * len(months)
        pages.append(count)
        busy += count > 0
        day += timedelta(days=1)
    assert max(pages) == 12
    assert 0 < busy < 365


def test_outside_every_window_nothing_is_requested(factory):
    result = pb.run_period_backfill(
        date(2026, 10, 30),
        today=date(2026, 10, 30),
        quarter_fetcher=refuse,
        month_fetcher=refuse,
        sleep=refuse,
    )
    assert (result["status"], result["reason"]) == ("skipped", "outside_window")
    assert (result["requests"], result["quarters"], result["months"]) == (0, [], [])
    with factory() as db:
        assert db.scalars(select(IngestionRun)).all() == []
    assert pb.noncore_warning(result) is None
    assert pb.summary(result)["reason"] == "outside_window"


def test_in_the_window_the_latest_two_periods_are_backfilled(factory):
    quarters, months = QuarterPages(), MonthPages()
    result = pb.run_period_backfill(
        date(2026, 11, 5),
        quarter_fetcher=quarters,
        month_fetcher=months,
        sleep=lambda _seconds: None,
    )
    assert result["today"] == "2026-11-06"
    assert (result["status"], result["requests"]) == ("success", 12)
    assert [(form["TYPEK"], form["season"]) for form in quarters.forms] == [
        ("sii", "02"),
        ("otc", "02"),
        ("sii", "03"),
        ("otc", "03"),
    ]
    assert [url.rsplit("/", 2)[-2:] for url in months.urls] == [
        ["sii", "t21sc03_115_9_0.html"],
        ["sii", "t21sc03_115_9_1.html"],
        ["otc", "t21sc03_115_9_0.html"],
        ["otc", "t21sc03_115_9_1.html"],
        ["sii", "t21sc03_115_10_0.html"],
        ["sii", "t21sc03_115_10_1.html"],
        ["otc", "t21sc03_115_10_0.html"],
        ["otc", "t21sc03_115_10_1.html"],
    ]
    assert result["records"] > 0
    assert result["fundamentals"]["start_quarter"] == "2026Q2"
    assert result["revenue"]["end_month"] == "2026-10"
    with factory() as db:
        runs = db.scalars(select(IngestionRun).order_by(IngestionRun.id)).all()
    assert [(run.run_type, run.status) for run in runs] == [
        ("fundamental_backfill", "success"),
        ("revenue_backfill", "success"),
    ]
    assert {run.metadata_json["trigger"] for run in runs} == {"daily"}
    kept = pb.summary(result)
    assert kept["fundamentals"] == {
        "status": "success",
        "run_id": runs[0].id,
        "requests": 4,
        "changed": result["fundamentals"]["changed"],
    }
    assert kept["revenue"]["requests"] == 8
    assert pb.noncore_warning(result) is None

    # Idempotent: the next day's run changes nothing.
    again = pb.run_period_backfill(
        quarter_fetcher=QuarterPages(),
        month_fetcher=MonthPages(),
        sleep=lambda _seconds: None,
    )
    assert (again["status"], again["requests"], again["records"]) == ("success", 12, 0)


def test_on_the_first_of_the_month_the_unfiled_month_is_no_warning(factory, isolated):
    # 12-01: November's window opens, but nobody has filed November yet; its
    # pages answer 「查無資料」 (200, measured 2026-11-06 on a month not yet
    # filed, #539 AC-2).  Before its 12-10 deadline that is empty, not failed.
    isolated.at = datetime(2026, 12, 1, 4, 0)
    months = NoDataMonths({Month(2026, 11)})
    result = pb.run_period_backfill(
        quarter_fetcher=QuarterPages(), month_fetcher=months, sleep=lambda _s: None
    )
    assert result["months"] == ["2026-10", "2026-11"]
    assert (result["status"], result["requests"]) == ("success", 12)
    assert result["revenue"]["status"] == "success"
    assert pb.noncore_warning(result) is None


def test_a_source_outage_is_partial_and_names_the_failed_part(factory):
    outage = QuarterPages(
        fail={(market, 2026, q) for market in ("sii", "otc") for q in (2, 3)}
    )
    result = pb.run_period_backfill(
        quarter_fetcher=outage, month_fetcher=MonthPages(), sleep=lambda _s: None
    )
    # Three failed market-quarters in a row stop the fundamentals (#529).
    assert result["fundamentals"]["status"] == "partial"
    assert "stopped after 3 failures" in result["fundamentals"]["aborted"]
    assert result["revenue"]["status"] == "success"
    assert (result["status"], result["requests"]) == ("partial", 11)
    warning = pb.noncore_warning(result)
    assert warning.startswith("MOPS period backfill partial: fundamentals partial")


def test_a_crash_in_one_part_fails_it_and_the_other_part_still_runs(
    factory, monkeypatch
):
    def crash(*_args, **_kwargs):
        raise RuntimeError("fixture crash")

    monkeypatch.setattr(
        quarterly_fundamentals, "backfill_quarterly_fundamentals", crash
    )
    result = pb.run_period_backfill(
        quarter_fetcher=refuse, month_fetcher=MonthPages(), sleep=lambda _s: None
    )
    assert result["fundamentals"] == {
        "status": "failed",
        "error": "RuntimeError: fixture crash",
    }
    assert result["revenue"]["status"] == "success"
    assert result["status"] == "partial"

    monkeypatch.setattr(pb.monthly_revenue, "backfill_monthly_revenues", crash)
    failed = pb.run_period_backfill(
        quarter_fetcher=refuse, month_fetcher=refuse, sleep=lambda _s: None
    )
    assert (failed["status"], failed["requests"]) == ("failed", 0)
    assert pb.noncore_warning(failed) == (
        "MOPS period backfill failed: fundamentals failed: RuntimeError: fixture"
        " crash; revenue failed: RuntimeError: fixture crash"
    )


def test_no_request_starts_after_the_time_budget(factory):
    ticks = iter(range(0, 10_000, 60))
    quarters, months = QuarterPages(), MonthPages()
    result = pb.run_period_backfill(
        quarter_fetcher=quarters,
        month_fetcher=months,
        sleep=lambda _s: None,
        clock=lambda: next(ticks),
        budget_seconds=150,
    )
    # Each clock read is a minute later: the fundamentals get one request, and
    # nothing is left for the revenue.
    assert len(quarters.forms) == 1 and months.urls == []
    assert result["fundamentals"]["aborted"].startswith("time budget")
    assert (
        result["revenue"]["aborted"] == "time budget 0 s used up before 2026-09:sii:0"
    )
    assert (result["status"], result["requests"]) == ("partial", 1)
