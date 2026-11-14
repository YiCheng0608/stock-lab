"""``dashboard.market_overview.indexes`` (Issue #564): the market page's index table.

Fixtures only: an isolated temporary SQLite database with TAIEX, TPEX, TX and
US index bars stored as their collectors store them, ``market_summaries`` for
the two exchanges, and ``technical_indicators`` written by the real indicator
batch.  The MA60 of every row is checked against the stored ``indicators/v1``
row and an independent mean of the last 60 closes; the TAIEX row against
``taiex_ma60`` (#561).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import api as api_module
from app import main as main_module
from app.db import enable_sqlite_foreign_keys
from app.indicators import INDICATOR_VERSION
from app.main import app
from app.market_overview import foreign_indices, index_rows, overnight_us, taiex_ma60
from app.migrations import upgrade_database
from app.models import (
    IngestionRun,
    Instrument,
    MarketBar,
    MarketSummary,
    TechnicalIndicator,
)
from worker.indicator_batch import compute_market_indicators

START = date(2026, 1, 5)  # a Monday
KEYS = ["taiex", "tpex", "tx"]


def _weekdays(count: int, start: date = START) -> list[date]:
    days, day = [], start
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


DAYS = _weekdays(80)
AS_OF = DAYS[-1]
TAIEX_CLOSES = [20000.0 + 15 * i for i in range(80)]  # rising: above MA60
TPEX_CLOSES = [300.0 - 0.5 * i for i in range(40)]  # only 40 sessions
TX_CLOSES = [20100.0 - 10 * i for i in range(80)]  # falling: below MA60
SPX_CLOSES = [
    6000.0 + (i % 7) for i in range(79)
]  # through the US session before AS_OF


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'indexes.db'}")
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


def _instrument(db, exchange, symbol, kind="index"):
    item = Instrument(
        exchange=exchange,
        symbol=symbol,
        name=symbol,
        instrument_type=kind,
        status="active",
    )
    db.add(item)
    db.flush()
    return item


def _bars(db, instrument, days, closes, source, **extra):
    for i, (day, close) in enumerate(zip(days, closes)):
        values = {
            key: value(i) if callable(value) else value for key, value in extra.items()
        }
        db.add(
            MarketBar(
                instrument_id=instrument.id,
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
                source=source,
                **values,
            )
        )


def _summary(db, exchange, day, close, change, pct, method):
    db.add(
        MarketSummary(
            exchange=exchange,
            trading_date=day,
            index_name=exchange,
            index_close=close,
            index_change=change,
            index_change_pct=pct,
            change_pct_method=method,
            turnover=1,
            turnover_scope="twse_all_securities"
            if exchange == "TWSE"
            else "tpex_stocks",
            breadth_scope="stocks",
            source="twse_mi_index"
            if exchange == "TWSE"
            else "tpex_mainborad_highlight",
        )
    )


def _seed(factory, *, tx_months=None, tpex_summary_day=AS_OF, run=True):
    """The seven series through AS_OF; ``tx_months`` gives each TX bar's contract month."""

    tx_months = tx_months or (lambda i: "202604")
    with factory() as db:
        # The TAIEX bars are fixture rows, so they are verified sessions for the TX change.
        _bars(
            db,
            _instrument(db, "TWSE", "TAIEX"),
            DAYS,
            TAIEX_CLOSES,
            "fixture_twse_index",
        )
        _bars(
            db,
            _instrument(db, "TPEx", "TPEX"),
            DAYS[-40:],
            TPEX_CLOSES,
            "tpex_index_ohlcv",
        )
        _bars(
            db,
            _instrument(db, "TAIFEX", "TX", "futures"),
            DAYS,
            TX_CLOSES,
            "taifex_daily_futures",
            contract_month=tx_months,
            open_interest=lambda i: 100000 + i,
            settlement_price=lambda i: TX_CLOSES[i],
        )
        _bars(
            db, _instrument(db, "US", "SPX"), DAYS[:-1], SPX_CLOSES, "finmind_us_index"
        )
        _summary(
            db,
            "TWSE",
            AS_OF,
            TAIEX_CLOSES[-1],
            15.0,
            15.0 / TAIEX_CLOSES[-2],
            "official",
        )
        _summary(db, "TPEx", tpex_summary_day, 280.5, -0.5, -0.5 / 281.0, "derived")
        db.flush()
        compute_market_indicators(db, as_of=AS_OF)
        if run:
            db.add(
                IngestionRun(
                    run_type="collect",
                    source="official",
                    run_date=AS_OF,
                    status="success",
                    records=1,
                    data_as_of=AS_OF.isoformat(),
                )
            )
        db.commit()


def _stored_ma60(factory, exchange, symbol, day):
    with factory() as db:
        return db.scalar(
            select(TechnicalIndicator.ma60)
            .join(Instrument, Instrument.id == TechnicalIndicator.instrument_id)
            .where(
                Instrument.exchange == exchange,
                Instrument.symbol == symbol,
                TechnicalIndicator.trading_date == day,
                TechnicalIndicator.formula_version == INDICATOR_VERSION,
            )
        )


def _rows(factory, as_of=AS_OF):
    with factory() as db:
        value = as_of.isoformat() if as_of else None
        return {row["key"]: row for row in index_rows(db, value)}


# ---- AC-3: the MA60 of each row is the stored indicators/v1 ma60; TAIEX is taiex_ma60 ----


def test_the_table_is_three_rows_in_order_through_the_dashboard(factory, client):
    _seed(factory)

    overview = client.get("/api/dashboard").json()["market_overview"]
    rows = overview["indexes"]

    assert [row["key"] for row in rows] == KEYS
    # No US row since #681 (the today page's overnight_us), none on the page since #633.
    assert [row["group"] for row in rows] == ["tw"] * 3
    assert "foreign_indices" not in overview
    taiex = rows[0]
    assert taiex["status"] == "available" and taiex["freshness"] == "latest"
    assert taiex["trading_date"] == AS_OF.isoformat()
    # The 大盤概況 numbers (market_summaries), not a change of its own.
    assert taiex["close"] == TAIEX_CLOSES[-1] and taiex["change"] == 15.0
    assert taiex["change_pct_method"] == "official"
    assert taiex["source"] == {
        "label": "臺灣證券交易所",
        "detail": "臺灣證券交易所 MI_INDEX",
    }
    # The TAIEX row and the #561 strip are one judgement.
    strip = overview["taiex_ma60"]
    for field in ("status", "close", "ma60", "above", "position", "close_count"):
        assert taiex["ma60"][field] == strip[field], field
    assert taiex["ma60"]["trading_date"] == strip["trading_date"]
    assert taiex["ma60"]["position"] == "above"


def test_each_ma60_is_the_stored_indicator_and_the_mean_of_60_closes(factory):
    _seed(factory)
    rows = _rows(factory)

    cases = [
        ("taiex", "TWSE", "TAIEX", AS_OF, TAIEX_CLOSES, "above"),
        ("tx", "TAIFEX", "TX", AS_OF, TX_CLOSES, "below"),
    ]
    for key, exchange, symbol, day, closes, position in cases:
        item = rows[key]["ma60"]
        stored = _stored_ma60(factory, exchange, symbol, day)
        assert item["status"] == "available", key
        assert item["trading_date"] == day.isoformat(), key
        assert item["ma60"] == stored, key
        assert item["ma60"] == pytest.approx(sum(closes[-60:]) / 60), key
        assert item["close"] == closes[-1], key
        assert item["above"] is (closes[-1] > stored), key
        if position:
            assert item["position"] == position, key
    with factory() as db:
        strip = taiex_ma60(db, AS_OF.isoformat())
    assert rows["taiex"]["ma60"]["ma60"] == strip["ma60"]


def test_too_few_closes_is_insufficient_and_no_series_is_unavailable(factory):
    _seed(factory)
    rows = _rows(factory)

    assert rows["tpex"]["status"] == "available"
    assert rows["tpex"]["ma60"] == {
        "trading_date": AS_OF.isoformat(),
        "required_closes": 60,
        "status": "insufficient",
        "reason": "insufficient_closes",
        "close_count": 40,
    }
    # No US row (#681), whether its series is stored (SPX) or not.
    assert list(rows) == KEYS


# ---- dates: 非最新 and the US session ----


def test_an_older_summary_is_stale_and_its_ma60_is_of_that_day(factory):
    _seed(factory, tpex_summary_day=DAYS[-2])
    rows = _rows(factory)

    tpex = rows["tpex"]
    assert tpex["freshness"] == "stale"
    assert tpex["trading_date"] == DAYS[-2].isoformat()
    assert tpex["expected_date"] == AS_OF.isoformat()
    assert tpex["ma60"]["trading_date"] == DAYS[-2].isoformat()
    assert tpex["ma60"]["close_count"] == 39


def test_overnight_us_is_foreign_indices_of_the_day_after_the_list(factory):
    """#681: the today page's 隔夜美股 reads foreign_indices; a list of day L is
    read before the open of the weekday after L, whose US session is L's."""

    _seed(factory)
    list_date = DAYS[-2]
    with factory() as db:
        foreign = foreign_indices(db, AS_OF.isoformat())
        us = overnight_us(db, list_date)
        friday = next(day for day in reversed(DAYS) if day.weekday() == 4)
        after_friday = overnight_us(db, friday)
    assert us["reference_date"] == AS_OF.isoformat()
    assert us["expected_date"] == list_date.isoformat()
    assert us["indexes"] == foreign
    spx = us["indexes"][0]
    assert spx["symbol"] == "SPX" and spx["freshness"] == "latest"
    assert spx["trading_date"] == list_date.isoformat()
    assert spx["change"] == pytest.approx(SPX_CLOSES[-1] - SPX_CLOSES[-2], abs=1e-4)
    assert spx["source"]["label"] == "FinMind USStockPrice ^GSPC"
    assert [item["symbol"] for item in us["indexes"]] == ["SPX", "IXIC", "DJI", "SOX"]
    assert [item["reason"] for item in us["indexes"][1:]] == ["not_collected"] * 3
    assert us["group_links"] == {
        "SOX": [
            "official-industry-1858340d045a575f",
            "theme-cowos",
            "theme-memory",
            "theme-semiconductor-equipment",
        ]
    }
    # Friday's list is read on Monday, before which the US session is Friday's.
    assert after_friday["reference_date"] == (friday + timedelta(days=3)).isoformat()
    assert after_friday["expected_date"] == friday.isoformat()


def test_the_sox_groups_are_the_official_semiconductor_industry_and_three_themes():
    from app.domain import US_INDEX_GROUP_LINKS
    from app.taxonomy import canonical_group_id

    assert (
        canonical_group_id("industry", "Semiconductor") in US_INDEX_GROUP_LINKS["SOX"]
    )
    assert list(US_INDEX_GROUP_LINKS) == ["SOX"]


def test_without_a_session_the_taiwan_rows_say_so(factory):
    _seed(factory, run=False)
    rows = _rows(factory, as_of=None)

    for key in ("taiex", "tpex", "tx"):
        assert rows[key]["status"] == "unavailable", key
        assert rows[key]["reason"] == "no_verified_session", key
        assert rows[key]["ma60"] is None, key


# ---- the TX change: adjacent verified sessions, none on a roll day ----


def test_tx_change_against_the_previous_session(factory):
    _seed(factory)
    tx = _rows(factory)["tx"]

    assert tx["status"] == "available" and tx["freshness"] == "latest"
    assert tx["close"] == TX_CLOSES[-1]
    assert tx["change"] == pytest.approx(-10.0)
    assert tx["change_pct"] == pytest.approx(-10.0 / TX_CLOSES[-2])
    assert tx["change_status"] == "known"
    assert tx["contract_month"] == "202604" and tx["previous_contract_month"] is None
    assert tx["open_interest"] == 100079
    assert tx["source"] == {"label": "臺灣期貨交易所", "detail": "taifex_daily_futures"}


def test_tx_roll_day_has_no_change(factory):
    _seed(factory, tx_months=lambda i: "202604" if i < 79 else "202605")
    tx = _rows(factory)["tx"]

    assert tx["change"] is None and tx["change_pct"] is None
    assert tx["change_status"] == "contract_roll"
    assert tx["contract_month"] == "202605"
    assert tx["previous_contract_month"] == "202604"
    # The MA60 is still the stored one (bars are not adjusted across a roll).
    assert tx["ma60"]["ma60"] == _stored_ma60(factory, "TAIFEX", "TX", AS_OF)
