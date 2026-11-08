"""``dashboard.market_overview.taiex_ma60`` (Issue #561): TAIEX against its stored MA60.

Fixtures only: an isolated temporary SQLite database, TAIEX bars stored as the
index parsers store them and ``technical_indicators`` written by the real
indicator batch.  Every day of each fixture is also checked against the
research filter R3 (``app.strategies.regime.TaiexCloses``), the definition the
page follows.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import api as api_module
from app import main as main_module
from app import market_overview as overview_module
from app.db import enable_sqlite_foreign_keys
from app.indicators import INDICATOR_VERSION
from app.main import app
from app.market_overview import taiex_ma60
from app.migrations import upgrade_database
from app.models import IngestionRun, Instrument, MarketBar, TechnicalIndicator
from app.strategies.regime import TaiexCloses
from worker.indicator_batch import compute_market_indicators

START = date(2026, 1, 5)  # a Monday


def _weekdays(count: int) -> list[date]:
    days, day = [], START
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


# 100 sessions: rising (above MA60 from the 60th close), a drop below it, a
# recovery above it, then one last close below it.
RISE = [100.0 + i for i in range(70)]  # 100..169
DROP = [120.0] * 15  # far below the ~150 average
RECOVER = [200.0] * 14
LAST = [100.0]
CLOSES = RISE + DROP + RECOVER + LAST
DAYS = _weekdays(len(CLOSES))


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ma60.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    made = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield made
    engine.dispose()


@pytest.fixture
def client(factory, monkeypatch):
    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)

    def override_get_db():
        with factory() as db:
            yield db

    app.dependency_overrides[api_module.get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(api_module.get_db, None)


def _seed(factory, closes, *, days=None, as_of=None, indicators=True):
    """TAIEX bars (close only, as ``twse_index`` stores them) and their indicator rows."""

    days = days or _weekdays(len(closes))
    with factory() as db:
        index = Instrument(
            exchange="TWSE",
            symbol="TAIEX",
            name="發行量加權股價指數",
            instrument_type="index",
            status="active",
        )
        db.add(index)
        db.flush()
        for day, close in zip(days, closes):
            db.add(
                MarketBar(
                    instrument_id=index.id,
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
                )
            )
        db.flush()
        if indicators:
            compute_market_indicators(db, as_of=days[-1])
        if as_of:
            db.add(
                IngestionRun(
                    run_type="collect",
                    source="official",
                    run_date=as_of,
                    status="success",
                    records=1,
                    data_as_of=as_of.isoformat(),
                )
            )
        db.commit()
    return days


def _stored_ma60(factory, day):
    with factory() as db:
        return db.scalar(
            select(TechnicalIndicator.ma60)
            .join(Instrument, Instrument.id == TechnicalIndicator.instrument_id)
            .where(
                Instrument.symbol == "TAIEX",
                TechnicalIndicator.trading_date == day,
                TechnicalIndicator.formula_version == INDICATOR_VERSION,
            )
        )


def _r3(days, closes):
    return TaiexCloses(dict(zip(days, closes))).states("r3", days)


def _r3_runs(days, states):
    """Runs of consecutive days R3 passes on, newest first."""

    runs, current = [], None
    for day in days:
        if states[day].passed:
            if current is None:
                current = [day, day]
                runs.append(current)
            current[1] = day
        else:
            current = None
    return [(start.isoformat(), end.isoformat()) for start, end in reversed(runs)]


def _assert_matches_r3(factory, days, closes):
    """Every day: the same state as R3, and the runs R3 passes on through that day."""

    states = _r3(days, closes)
    with factory() as db:
        for position, day in enumerate(days):
            result = taiex_ma60(db, day.isoformat())
            state = states[day]
            if state.state == "data_incomplete":
                assert result["status"] == "insufficient", day
                assert "above" not in result
                continue
            assert result["status"] == "available", day
            assert result["above"] is state.passed, day
            expected = _r3_runs(days[: position + 1], states)
            got = [(item["start"], item["end"]) for item in result["segments"]]
            assert got == expected[: overview_module.MAX_SEGMENTS], day


# ---- AC-1: the three cases through the API ----


def test_close_above_ma60(factory, client):
    days = _seed(factory, CLOSES[:70], as_of=DAYS[69])

    body = client.get("/api/dashboard").json()["market_overview"]["taiex_ma60"]

    assert body["status"] == "available"
    assert body["trading_date"] == "2026-04-10"
    assert body["close"] == 169.0
    # The stored indicators/v1 value, not a formula of its own.
    assert body["ma60"] == _stored_ma60(factory, days[69]) == 139.5
    assert body["above"] is True and body["position"] == "above"
    assert body["close_count"] == 70 and body["required_closes"] == 60
    # Above from the 60th close (2026-03-27) through today.
    assert body["segments"] == [
        {
            "start": "2026-03-27",
            "end": "2026-04-10",
            "sessions": 11,
            "ongoing": True,
            "starts_before_window": False,
        }
    ]
    assert body["segment_window"] == {
        "start": "2026-01-05",
        "end": "2026-04-10",
        "sessions": 70,
        "max_segments": 3,
    }
    assert body["source"]["label"] == "臺灣證券交易所"
    assert body["source"]["bar_source"] == "twse_index"
    assert body["source"]["formula_version"] == "indicators/v1"
    assert body["source"]["data_as_of"] == "2026-04-10"
    _assert_matches_r3(factory, days, CLOSES[:70])


def test_close_below_ma60_lists_the_earlier_runs(factory, client):
    _seed(factory, CLOSES, as_of=DAYS[-1])

    body = client.get("/api/dashboard").json()["market_overview"]["taiex_ma60"]

    assert body["status"] == "available"
    assert body["trading_date"] == "2026-05-22"
    assert body["close"] == 100.0
    assert body["ma60"] == _stored_ma60(factory, DAYS[-1])
    assert body["close"] < body["ma60"]
    assert body["above"] is False and body["position"] == "below"
    assert body["segments"] == [
        {
            # The first 200 close is above the ~141.5 average already.
            "start": "2026-05-04",
            "end": "2026-05-21",
            "sessions": 14,
            "ongoing": False,
            "starts_before_window": False,
        },
        {
            "start": "2026-03-27",
            "end": "2026-04-10",
            "sessions": 11,
            "ongoing": False,
            "starts_before_window": False,
        },
    ]
    _assert_matches_r3(factory, DAYS, CLOSES)


def test_close_equal_to_ma60_is_not_above(factory, client):
    # 60 equal closes: MA60 equals the close, and R3 (strictly above) fails.
    closes = [100.0] * 65
    days = _seed(factory, closes, as_of=_weekdays(65)[-1])

    body = client.get("/api/dashboard").json()["market_overview"]["taiex_ma60"]

    assert body["status"] == "available"
    assert body["close"] == body["ma60"] == _stored_ma60(factory, days[-1]) == 100.0
    assert body["above"] is False and body["position"] == "equal"
    assert body["segments"] == []
    _assert_matches_r3(factory, days, closes)


def test_fewer_than_60_closes_is_insufficient(factory, client):
    days = _seed(factory, CLOSES[:59], as_of=DAYS[58])

    body = client.get("/api/dashboard").json()["market_overview"]["taiex_ma60"]

    assert _stored_ma60(factory, days[-1]) is None
    assert body == {
        "trading_date": "2026-03-26",
        "required_closes": 60,
        "status": "insufficient",
        "reason": "insufficient_closes",
        "close_count": 59,
    }
    _assert_matches_r3(factory, days, CLOSES[:59])


# ---- the window and the unavailable reasons ----


def test_a_run_reaching_the_window_start_says_it_started_earlier(factory, monkeypatch):
    days = _seed(factory, CLOSES[:70])
    monkeypatch.setattr(overview_module, "SEGMENT_SESSIONS", 5)
    with factory() as db:
        result = taiex_ma60(db, days[-1].isoformat())
        cut = taiex_ma60(db, days[63].isoformat())
    assert result["segment_window"]["start"] == days[65].isoformat()
    assert result["segments"] == [
        {
            "start": days[65].isoformat(),
            "end": days[69].isoformat(),
            "sessions": 5,
            "ongoing": True,
            "starts_before_window": True,
        }
    ]
    # Window days[59..63]: the run starts at the first above-MA60 close, on the
    # window's first day, with no earlier run before it.
    assert cut["segments"][0]["start"] == days[59].isoformat()
    assert cut["segments"][0]["starts_before_window"] is False


def test_only_the_newest_three_runs_are_returned(factory):
    # Above, below, above, ... after the first 60 closes: one-day runs.
    closes = [100.0] * 60 + [200.0, 50.0] * 5
    days = _seed(factory, closes)
    with factory() as db:
        result = taiex_ma60(db, days[-2].isoformat())
    assert [item["start"] for item in result["segments"]] == [
        days[-2].isoformat(),
        days[-4].isoformat(),
        days[-6].isoformat(),
    ]
    assert result["segments"][0]["ongoing"] is True
    _assert_matches_r3(factory, days, closes)


def test_unavailable_reasons(factory):
    with factory() as db:
        assert taiex_ma60(db, None)["reason"] == "no_verified_session"
        assert taiex_ma60(db, "2026-04-10")["reason"] == "not_collected"
    days = _seed(factory, CLOSES[:70], indicators=False)
    with factory() as db:
        missing = taiex_ma60(db, days[-1].isoformat())
        later = taiex_ma60(db, (days[-1] + timedelta(days=3)).isoformat())
    assert missing["status"] == "unavailable"
    assert missing["reason"] == "indicator_not_computed"
    # A later dashboard date never falls back to an older bar.
    assert later == {
        "trading_date": "2026-04-13",
        "required_closes": 60,
        "status": "unavailable",
        "reason": "row_date_mismatch",
        "latest_trading_date": "2026-04-10",
    }
