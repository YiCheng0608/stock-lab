"""The stock page 「財務」 tab reads the stock API's ``fundamentals`` (#528).

A report whose 出表日 (``announcement_date``) is after the research cutoff must not
reach the page, even when its period ended before the cutoff; one without an
出表日 cannot be placed in time and is left out under a cutoff too. ROE the feed
does not carry stays null, never 0.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import api
from app.db import Base, enable_sqlite_foreign_keys
from app.models import FundamentalSnapshot, Instrument, MarketBar


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()
    engine.dispose()


def _report(instrument_id, period_end, fiscal_period, announced, eps):
    return FundamentalSnapshot(
        instrument_id=instrument_id,
        period_end=period_end,
        fiscal_period=fiscal_period,
        announcement_date=announced,
        revenue=1_000_000.0,
        eps=eps,
        roe=None,
        source="mops_fundamental",
        data_as_of=period_end.isoformat(),
    )


@pytest.fixture
def stock(db):
    instrument = Instrument(id=1, exchange="TWSE", symbol="2330", name="台積電")
    db.add(instrument)
    db.flush()
    db.add_all(
        [
            MarketBar(
                instrument_id=1,
                trading_date=date(2026, 11, 5),
                open=1,
                high=1,
                low=1,
                close=1,
                adj_close=1,
                source="twse",
            ),
            _report(1, date(2026, 3, 31), "Q1", date(2026, 5, 15), 20.0),
            _report(1, date(2026, 6, 30), "Q2", date(2026, 8, 14), 49.33),
            # Q3 ended before 11/05 but its 出表日 is 11/05: hidden under a 11/04 cutoff.
            _report(1, date(2026, 9, 30), "Q3", date(2026, 11, 5), 70.0),
            _report(1, date(2025, 12, 31), "Q4", None, 60.0),
        ]
    )
    db.commit()
    return instrument


def _periods(payload):
    return [row["fiscal_period"] for row in payload["fundamentals"]]


def test_cutoff_hides_reports_published_after_it(db, stock):
    payload = api.stock_detail("TWSE", "2330", db, as_of=date(2026, 11, 4))
    assert _periods(payload) == ["Q2", "Q1"]
    assert all(
        row["announcement_date"] <= "2026-11-04" for row in payload["fundamentals"]
    )
    # The day it was published, it shows, newest period first.
    published = api.stock_detail("TWSE", "2330", db, as_of=date(2026, 11, 5))
    assert _periods(published) == ["Q3", "Q2", "Q1"]
    # Before the first 出表日 nothing is left: the page writes its reason sentence.
    assert (
        api.stock_detail("TWSE", "2330", db, as_of=date(2026, 5, 14))["fundamentals"]
        == []
    )


def test_latest_uses_the_latest_market_date_as_cutoff(db, stock):
    payload = api.stock_detail("TWSE", "2330", db)
    assert _periods(payload) == ["Q3", "Q2", "Q1"]
    assert payload["fundamentals"][0] == {
        "period_end": "2026-09-30",
        "fiscal_period": "Q3",
        "announcement_date": "2026-11-05",
        "revenue": 1_000_000.0,
        "eps": 70.0,
        "roe": None,
        "source": "mops_fundamental",
        "data_as_of": "2026-09-30",
    }


def test_missing_roe_stays_null(db, stock):
    rows = api.stock_detail("TWSE", "2330", db)["fundamentals"]
    assert [row["roe"] for row in rows] == [None, None, None]
