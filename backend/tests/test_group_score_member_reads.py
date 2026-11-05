"""Group scores read each member's history once per score date (#509).

``_calculate_group_scores`` computes a member's metrics from one read of its
pre-score history, once per call, however many groups it belongs to.  These
tests pin that the shortcut gives exactly what the standalone per-member
helpers give (a member in two groups, a member without a bar on the score
date's feature volume, members with missing data), and that the price-basis
factors equal a per-bar rebuild while calling the factor only per action
prefix.
"""

from __future__ import annotations

import math
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

import worker.pipeline as pipeline
from app.db import Base, enable_sqlite_foreign_keys
from app.models import (
    ChipSnapshot,
    CorporateAction,
    GroupDailyScore,
    GroupMembership,
    Instrument,
    MarketBar,
    TechnicalFeature,
    ThemeGroup,
)

SCORE_DATE = date(2026, 9, 4)
# Ids far from every other integer parameter of the scoring queries.
IDS = {"TAIEX": 9000, "A": 9001, "B": 9002, "C": 9003, "D": 9004, "E": 9005}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as session:
        yield session
    engine.dispose()


def _seed(db: Session) -> list[date]:
    """TAIEX plus five stocks in an industry and a theme.

    A and B belong to both groups; A has a split and a cash dividend without
    a reference price and no feature volume (the score-date bar is read); C
    lacks one chip session (no flow); D has no feature row; E has ten bars.
    """

    dates = pipeline.business_days(SCORE_DATE, 26)
    for symbol, instrument_id in IDS.items():
        db.add(
            Instrument(
                id=instrument_id,
                market="TW",
                exchange="TWSE",
                symbol=symbol,
                name=symbol,
                instrument_type="index" if symbol == "TAIEX" else "stock",
                status="active",
            )
        )
    db.add_all(
        [
            ThemeGroup(
                id="ind", name="ind", group_type="official_industry", active=True
            ),
            ThemeGroup(id="theme", name="theme", group_type="theme", active=True),
        ]
    )
    db.flush()
    for group_id, symbols in (("ind", "ABCDE"), ("theme", "ABC")):
        for symbol in symbols:
            db.add(
                GroupMembership(
                    group_id=group_id,
                    instrument_id=IDS[symbol],
                    valid_from=dates[0],
                    source="fixture",
                )
            )
    for index, day in enumerate(dates):
        for offset, (symbol, instrument_id) in enumerate(IDS.items()):
            if symbol == "E" and index < len(dates) - 10:
                continue
            close = 100 * (1 + 0.003 * (offset + 1) * (1 if index % 3 else -1)) ** index
            if symbol == "A" and index >= 12:
                close /= 2  # raw price after the split
            db.add(
                MarketBar(
                    instrument_id=instrument_id,
                    trading_date=day,
                    open=close,
                    high=close * 1.01,
                    low=close * 0.99,
                    close=close,
                    adj_close=close,
                    volume=0 if symbol == "TAIEX" else 1000 + 37 * offset + 11 * index,
                    turnover=0,
                    is_suspended=symbol == "B" and index == 7,
                    source="fixture",
                )
            )
            if symbol == "TAIEX" or (symbol == "C" and index == len(dates) - 2):
                continue
            db.add(
                ChipSnapshot(
                    instrument_id=instrument_id,
                    trading_date=day,
                    foreign_buy=10 * offset - index,
                    trust_buy=offset,
                    dealer_buy=-1,
                    margin_balance=500 + 13 * index + offset,
                    margin_change=13,
                    source="twse_t86+twse_margin",
                )
            )
    db.add_all(
        [
            CorporateAction(
                instrument_id=IDS["A"],
                action_date=dates[12],
                action_type="split",
                split_ratio=2.0,
                source="fixture",
            ),
            CorporateAction(
                instrument_id=IDS["A"],
                action_date=dates[18],
                action_type="cash_dividend",
                cash_dividend=1.5,
                source="fixture",
            ),
        ]
    )
    for symbol in "ABCE":
        db.add(
            TechnicalFeature(
                instrument_id=IDS[symbol],
                trading_date=SCORE_DATE,
                features_json={}
                if symbol == "A"
                else {"volume": 1000 + 37 * list(IDS).index(symbol) + 11 * 25},
                source="fixture",
            )
        )
    db.flush()
    return dates


def _standalone_member(db: Session, instrument_id: int) -> dict | None:
    """The member entry from the standalone per-member helpers, or None when skipped."""

    benchmark = pipeline._returns_by_window(db, IDS["TAIEX"], SCORE_DATE)
    returns = pipeline._returns_by_window(db, instrument_id, SCORE_DATE)
    if any(returns[w] is None or benchmark[w] is None for w in (1, 5, 20)):
        return None
    feature = db.scalar(
        select(TechnicalFeature).where(
            TechnicalFeature.instrument_id == instrument_id,
            TechnicalFeature.trading_date == SCORE_DATE,
        )
    )
    if feature is None:
        return None
    prior = pipeline._prior_20_window(db, instrument_id, SCORE_DATE)["volumes"]
    current = pipeline._safe_float(feature.features_json.get("volume"))
    if current is None:
        bar = db.scalar(
            select(MarketBar).where(
                MarketBar.instrument_id == instrument_id,
                MarketBar.trading_date == SCORE_DATE,
            )
        )
        current = float(bar.volume) if bar else None
    if not prior or current is None or sum(prior) <= 0:
        return None
    last_five = db.scalars(
        select(MarketBar.volume)
        .where(
            MarketBar.instrument_id == instrument_id,
            MarketBar.trading_date <= SCORE_DATE,
        )
        .order_by(MarketBar.trading_date.desc())
        .limit(5)
    ).all()
    average = sum(prior) / len(prior)
    volume_5d = (sum(last_five) / len(last_five)) / average
    flow, absent = pipeline._hot_group_flow_with_absent_evidence(
        db,
        instrument_id,
        SCORE_DATE,
        lambda day: pipeline._official_institutional_file_evidence(db, day).get("TWSE"),
    )
    excess = {w: float(returns[w]) - float(benchmark[w]) for w in (1, 5, 20)}
    return {
        "excess_return_1d": excess[1],
        "excess_return_5d": excess[5],
        "excess_return_20d": excess[20],
        "volume_strength_raw": 0.50 * (current / average) + 0.50 * volume_5d,
        "hot_group_institutional_flow_to_sum_volume_ratio_5d": flow,
        "institutional_flow_absent_from_official_file": absent,
        "margin_balance_change_ratio_5d": pipeline._margin_change_ratio(
            db, instrument_id, SCORE_DATE
        ),
    }


def _rows(db: Session) -> dict[str, GroupDailyScore]:
    return {
        row.group_id: row
        for row in db.scalars(
            select(GroupDailyScore).where(GroupDailyScore.trading_date == SCORE_DATE)
        )
    }


def test_members_in_two_groups_and_members_missing_data_match_the_standalone_helpers(
    db,
):
    _seed(db)
    pipeline._calculate_group_scores(db, SCORE_DATE)
    db.flush()
    rows = _rows(db)
    expected = {symbol: _standalone_member(db, IDS[symbol]) for symbol in "ABCDE"}
    # D has no feature row and E too short a history: neither is a member
    # metric; C has no flow for its missing chip session.
    assert expected["D"] is None and expected["E"] is None
    assert expected["C"]["hot_group_institutional_flow_to_sum_volume_ratio_5d"] is None
    for group_id, symbols in (("ind", "ABC"), ("theme", "ABC")):
        members = rows[group_id].details_json["member_returns"]
        assert [member["symbol"] for member in members] == list(symbols)
        for member in members:
            want = expected[member["symbol"]]
            assert {key: member[key] for key in want} == want, (group_id, member)
        coverage = rows[group_id].details_json["institutional_flow_coverage"]
        assert (coverage["available"], coverage["eligible"]) == (2, 3)
        assert coverage["member_count"] == len(symbols) + (
            2 if group_id == "ind" else 0
        )
    # The shared members' entries are equal in both groups but not one object.
    ind = rows["ind"].details_json["member_returns"]
    theme = rows["theme"].details_json["member_returns"]
    assert ind[0] == theme[0] and ind[0] is not theme[0]
    assert (
        ind[0]["institutional_flow_absent_from_official_file"]
        is not theme[0]["institutional_flow_absent_from_official_file"]
    )


def test_a_member_in_two_groups_has_its_history_read_once_per_call(db):
    _seed(db)
    reads: dict[tuple[str, int], int] = {}

    def count(conn, cursor, statement, parameters, context, executemany):
        table = next(
            (
                name
                for name in ("market_bars", "corporate_actions", "chip_snapshots")
                if f"FROM {name}" in statement
            ),
            None,
        )
        if table is None:
            return
        for instrument_id in IDS.values():
            if instrument_id in (parameters or ()):
                reads[(table, instrument_id)] = reads.get((table, instrument_id), 0) + 1

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", count)
    try:
        pipeline._calculate_group_scores(db, SCORE_DATE)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    for symbol in "ABC":
        instrument_id = IDS[symbol]
        assert reads[("market_bars", instrument_id)] == 1, symbol
        assert reads[("corporate_actions", instrument_id)] == 1, symbol
        # The five flow sessions and the six margin sessions.
        assert reads[("chip_snapshots", instrument_id)] <= 2, symbol


def _per_bar_rebuild(actions, bars):
    """The pre-#509 body: every bar filters the actions and rebuilds its factor."""

    fallback: dict[date, float] = {}
    for action in actions:
        if action.reference_price is not None:
            continue
        previous = next(
            (
                bar
                for bar in reversed(bars)
                if bar.trading_date < action.action_date
                and pipeline._safe_float(bar.close) is not None
            ),
            None,
        )
        if previous and previous.close > 0:
            fallback[action.action_date] = previous.close
    factors = []
    for bar in bars:
        effective = [a for a in actions if a.action_date <= bar.trading_date]
        factor, _ = pipeline._corporate_action_factor(
            effective, fallback_reference_prices=fallback
        )
        factors.append(factor if math.isfinite(factor) and factor > 0 else 1.0)
    return factors


def test_action_factors_equal_a_per_bar_rebuild_with_one_factor_per_prefix(
    db, monkeypatch
):
    dates = _seed(db)
    instrument_id = IDS["A"]
    # Add a pre-history action, two actions on one date, one on a weekend
    # between bars and one with a published reference price.
    db.add_all(
        [
            CorporateAction(
                instrument_id=instrument_id,
                action_date=date(2026, 1, 5),
                action_type="cash_dividend",
                cash_dividend=0.5,
                reference_price=80.0,
                source="fixture",
            ),
            CorporateAction(
                instrument_id=instrument_id,
                action_date=dates[18],
                action_type="stock_dividend",
                stock_dividend_ratio=0.1,
                source="fixture",
            ),
            CorporateAction(
                instrument_id=instrument_id,
                action_date=date(2026, 8, 23),
                action_type="capital_reduction",
                details_json={"price_factor": 1.25},
                source="fixture",
            ),
        ]
    )
    db.flush()
    bars = db.scalars(
        select(MarketBar)
        .where(MarketBar.instrument_id == instrument_id)
        .order_by(MarketBar.trading_date)
    ).all()
    actions = db.scalars(
        select(CorporateAction)
        .where(CorporateAction.instrument_id == instrument_id)
        .order_by(CorporateAction.action_date, CorporateAction.id)
    ).all()
    expected = _per_bar_rebuild(actions, bars)

    calls = SimpleNamespace(n=0)
    original = pipeline._corporate_action_factor

    def counted(*args, **kwargs):
        calls.n += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "_corporate_action_factor", counted)
    assert pipeline._action_factor_by_bar(db, instrument_id, bars) == expected
    # Prefixes seen by the bars: the pre-history action, + the split, + the
    # weekend action, + the two actions of dates[18].
    assert len(set(expected)) > 1
    assert calls.n == 4
