"""The overnight news sample of past lists (tools/research/overnight_news_sample.py, #855 AC-4).

The list is test_preopen's: Friday T (2026-09-04), computed 21:30 Taipei; E is
Monday 09-07 and the rebuilt check is E's 08:20 Taipei (``CHECKED``).
"""

from __future__ import annotations

import importlib.util
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, enable_sqlite_foreign_keys
from app.preopen_news import check_rows, replace_check

from test_preopen import (
    CHECKED,
    COMPUTED,
    MONDAY,
    _closed,
    _list,
    _news,
    _taipei,
)
from test_candidates import T
from worker import pipeline

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "tools" / "research" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sample = _load("overnight_news_sample")


@pytest.fixture
def db():
    """test_preopen's in-memory database."""

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        session.info["strategies"] = pipeline._ensure_strategies(session)
        session.commit()
        yield session
    engine.dispose()


def test_the_check_instant_is_e_at_0820_taipei():
    assert sample.check_instant(MONDAY) == CHECKED
    assert T == date(2026, 9, 4) and MONDAY == date(2026, 9, 7)


def test_e_is_the_next_weekday_the_calendar_does_not_close(db):
    assert sample.next_trading_day(db, T) == MONDAY
    _closed(db, MONDAY)
    assert sample.next_trading_day(db, T) == date(2026, 9, 8)


def test_a_rebuilt_list_counts_the_preopen_window(db):
    run, (cement, chips) = _list(db)
    late = _taipei(2026, 9, 4, 22, 0)
    # In the window: two for 1101 (one negative, one positive), one unjudged for 2330.
    _news(db, ["1101"], published=_taipei(2026, 9, 4, 21, 0), collected=late)
    _news(
        db,
        ["1101"],
        published=_taipei(2026, 9, 5, 9, 0),
        collected=late,
        direction="positive",
    )
    _news(
        db,
        ["2330"],
        published=_taipei(2026, 9, 6, 9, 0),
        collected=late,
        direction=None,
    )
    # Collected before the list (daily saw it) and after the check: not counted.
    _news(
        db,
        ["2330"],
        published=_taipei(2026, 9, 4, 12, 0),
        collected=COMPUTED - timedelta(seconds=1),
    )
    _news(
        db,
        ["2330"],
        published=_taipei(2026, 9, 7, 8, 30),
        collected=CHECKED + timedelta(minutes=10),
    )
    db.commit()

    result = sample.build(db)
    (item,) = result["lists"]
    assert (item["list_date"], item["entry_day"], item["checked_at"]) == (
        T,
        MONDAY,
        CHECKED,
    )
    assert not item["pending"] and item["stored"] is None
    assert (item["rows"], item["rows_with_news"], item["rows_with_negative"]) == (
        2,
        2,
        1,
    )
    assert (item["news"], item["negative"], item["positive"], item["unscored"]) == (
        3,
        1,
        1,
        1,
    )
    totals = result["totals"]
    assert totals["lists"] == 1 and totals["first_list_with_news"] == T
    assert totals["rows_with_negative"] == 1 and totals["news"] == 3
    # All linked news from the list to the check, overnight or not (only listed):
    # the item collected before the list and the one after the check are outside.
    assert result["all_directions"] == {
        "positive": 1,
        "negative": 1,
        "mixed": 0,
        "unknown": 0,
        "unscored": 1,
    }
    assert result["unreadable_lists"] == []

    # The stored check of the same run sits beside the rebuild.
    replace_check(db, run, check_rows(db, run, CHECKED))
    db.commit()
    (item,) = sample.build(db)["lists"]
    assert item["stored"]["rows_with_news"] == 2 and item["stored"]["news"] == 3
    assert sample.build(db)["stored_compared"] == {
        "lists": 1,
        "same_rows_with_news": 1,
        "same_news": 1,
    }


def test_a_list_whose_check_is_after_the_newest_news_is_pending(db):
    _list(db)
    _news(db, ["1101"], published=_taipei(2026, 9, 4, 21, 0), collected=COMPUTED)
    db.commit()
    result = sample.build(db)
    assert result["lists"][0]["pending"]
    assert result["totals"]["lists"] == 0 and result["totals"]["pending_lists"] == 1


def _done(day: date, negative_rows: int) -> dict:
    return {"list_date": day, "pending": False, "rows_with_negative": negative_rows}


def _weekdays_from(start: date, count: int) -> list[date]:
    days, day = [], start
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def test_the_estimate_extrapolates_the_recent_rate_to_both_reference_lines(db):
    assert (sample.NEGATIVE_ROWS, sample.NEGATIVE_DATES) == (100, 60)
    days = _weekdays_from(date(2026, 9, 1), 10)
    # 2 negative rows on every list: 20 rows, 10 dates.  Rows need 40 more
    # lists, dates 50: the dates decide.
    guess = sample.estimate([_done(day, 2) for day in days], db)
    assert (guess["negative_rows"], guess["negative_dates"]) == (20, 10)
    assert guess["lists_needed"] == 50 and not guess["reached"]
    assert guess["estimated_list_date"] == _weekdays_from(days[-1], 51)[-1]
    # A closed day in the stored calendar is skipped.
    _closed(db, date(2026, 9, 15))
    assert (
        sample.estimate([_done(day, 2) for day in days], db)["estimated_list_date"]
        == _weekdays_from(days[-1], 52)[-1]
    )
    # No negative row lately: no date from the rate, but the floor without one:
    # 60 more lists, one date each at best.
    none = sample.estimate([_done(day, 0) for day in days], db)
    assert none["lists_needed"] is None and none["estimated_list_date"] is None
    assert none["earliest_lists_needed"] == 60
    # 60 trading days after the last list, the 2026-09-15 closure skipped.
    assert none["earliest_list_date"] == _weekdays_from(days[-1], 62)[-1]
    # 10 dates already: 50 more at best.
    assert guess["earliest_lists_needed"] == 50
    # Enough already.
    full = sample.estimate([_done(day, 2) for day in _weekdays_from(days[0], 60)], db)
    assert full["reached"] and full["estimated_list_date"] is None
    # A pending list is not counted.
    assert (
        sample.estimate([{**_done(days[0], 5), "pending": True}], db)["negative_rows"]
        == 0
    )


def test_the_cli_reads_a_copy_and_writes_the_tables(tmp_path):
    path = tmp_path / "copy" / "stock.db"
    path.parent.mkdir()
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.commit()
    engine.dispose()
    before = {
        name: os.environ.get(name) for name in ("STOCK_DATA_DIR", "STOCK_RAW_DIR")
    }
    out = tmp_path / "out"
    assert sample.main(["--db", str(path), "--out", str(out)]) == 0
    assert {name: os.environ.get(name) for name in before} == before
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert summary.startswith("# 隔夜新聞樣本（#855 AC-4")
    assert "限制（先讀）" in summary and "參考線" in summary
    tables = json.loads((out / "tables.json").read_text(encoding="utf-8"))
    assert tables["totals"]["lists"] == 0
    assert (out / "lists.csv").read_text(encoding="utf-8").startswith("list_date,")
    assert path.with_name("stock.db-wal").exists() is False


def test_the_cli_refuses_the_production_database(tmp_path):
    production = tmp_path / "stock-lab-data" / "stock.db"
    production.parent.mkdir()
    production.write_bytes(b"")
    out = tmp_path / "o"
    assert sample.main(["--db", str(production), "--out", str(out)]) == 2
    assert not out.exists()


@pytest.mark.parametrize("day", [datetime(2026, 9, 7), None])
def test_taipei_formatting(day):
    assert sample._taipei(day) == ("2026-09-07 08:00" if day else "—")


def test_a_list_of_a_version_the_page_no_longer_reads_is_left_out(db):
    from app.models import CandidateRun

    _list(db)
    old = date(2026, 9, 3)
    db.add(CandidateRun(trading_date=old, score_version="candidate_score_v0"))
    db.commit()
    result = sample.build(db)
    assert result["unreadable_lists"] == [old]
    assert [item["list_date"] for item in result["lists"]] == [T]
