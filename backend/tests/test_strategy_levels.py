"""Observation price levels strategy_levels_v1 (V1_SPEC strategy_levels_v1, #273)."""

from __future__ import annotations

import inspect
from datetime import date, datetime
from fractions import Fraction
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import api as api_module
from app import decision
from app.db import Base, enable_sqlite_foreign_keys
from app.domain import STRATEGY_LEVELS_VERSION
from app.models import (
    CorporateAction,
    Instrument,
    MarketBar,
    Signal,
    StrategyLevel,
    StrategyVersion,
    TechnicalFeature,
)
from app.strategies import REGISTRY, Condition, NextSessionInputs
from app.strategies import levels
from app.tracking_plans import PlanRequestError, create_plan
from worker import pipeline
from worker.strategy_levels import compute_strategy_levels

BREAKOUT = next(s for s in REGISTRY.values() if s.entry_type == "breakout")
PULLBACK = next(s for s in REGISTRY.values() if s.entry_type == "pullback")
BACKEND = Path(__file__).resolve().parents[1]

# ---- version and tick ladder are pinned ----


def test_the_levels_version_and_tick_ladder_are_pinned():
    # Changing either is a formula change: it needs a new STRATEGY_LEVELS_VERSION.
    assert STRATEGY_LEVELS_VERSION == "strategy_levels_v1"
    assert levels.TICK_LADDERS == {
        "stock": (
            ("10", "0.01"),
            ("50", "0.05"),
            ("100", "0.1"),
            ("500", "0.5"),
            ("1000", "1"),
            (None, "5"),
        ),
        "etf": (("50", "0.01"), (None, "0.05")),
    }
    assert levels.DAILY_PRICE_LIMIT == Fraction(1, 10)


@pytest.mark.parametrize(
    "kind, value, strict, expected",
    [
        # stock: every band edge, strictly above and at
        ("stock", 9.99, True, 10.0),
        ("stock", 9.995, False, 10.0),
        ("stock", 10.0, True, 10.05),
        ("stock", 10.0, False, 10.0),
        ("stock", 49.95, True, 50.0),
        ("stock", 50.0, True, 50.1),
        ("stock", 99.9, True, 100.0),
        ("stock", 100.0, True, 100.5),
        ("stock", 499.5, True, 500.0),
        ("stock", 500.0, True, 501.0),
        ("stock", 999.0, True, 1000.0),
        ("stock", 1000.0, True, 1005.0),
        ("stock", 99.87, True, 99.9),  # an adjusted high between ticks
        ("ipo", 100.2, False, 100.5),  # IPOs use the stock ladder
        # ETF
        ("etf", 49.99, True, 50.0),
        ("etf", 50.0, True, 50.05),
        ("etf", 8.896777, True, 8.9),
        ("etf", 120.01, False, 120.05),
    ],
)
def test_tick_ceil_takes_the_next_legal_price(kind, value, strict, expected):
    assert levels.tick_ceil(value, kind, strict=strict) == expected


@pytest.mark.parametrize(
    "kind, value, expected",
    [
        ("stock", 9.999, 9.99),
        ("stock", 49.99, 49.95),
        ("stock", 100.37, 100.0),
        ("stock", 999.9, 999.0),
        ("stock", 1003.0, 1000.0),
        ("etf", 49.999, 49.99),
        ("etf", 50.07, 50.05),
    ],
)
def test_tick_floor_takes_the_legal_price_at_or_below(kind, value, expected):
    assert levels.tick_floor(value, kind) == expected


# ---- pure formulas ----

VOLUMES = (1001,) * 20  # average 1001 shares


def next_inputs(**values) -> NextSessionInputs:
    base = dict(
        instrument_type="stock",
        etf_category=None,
        bar_count=120,
        is_suspended=False,
        close=99.0,
        atr14=2.0,
        closes=(90.0,) * 40 + (100.0,) * 19,
        highs=(95.0,) * 19 + (100.0,),
        volumes=VOLUMES,
        group_excess_return_20d=0.01,
        institutional_flow_ratio_5d=0.0,
        margin_change_ratio_5d=0.0,
    )
    base.update(values)
    return NextSessionInputs(**base)


def test_breakout_trigger_is_the_next_tick_above_the_high_and_volume_rounds_up():
    result = BREAKOUT.observation_levels(next_inputs())
    assert result.availability == "levels"
    # High 100.0 is itself a legal price: strictly above it is 100.5.
    assert result.trigger_price == 100.5
    # 1.2 x 1001 = 1201.2 shares, rounded up.
    assert result.min_volume == 1202
    assert result.max_volume is None
    # legacy-risk-levels/v1 on the trigger with T's ATR14 2.0
    assert (
        result.reference_entry,
        result.invalid_price,
        result.target_1,
        result.target_2,
        result.risk_reward,
    ) == (100.5, 98.5, 103.7, 106.5, 1.6)
    # Limit up from close 99.0 is 108.9.
    assert result.reachable_next_session is True
    assert result.next_session["breakout_price"] == {
        "min_close": 100.5,
        "gap": round(100.5 / 99 - 1, 6),
    }


def test_a_trigger_beyond_the_daily_limit_is_not_reachable():
    # Limit up from 90.0 is 99.0, below the trigger 100.5.
    result = BREAKOUT.observation_levels(next_inputs(close=90.0))
    assert result.trigger_price == 100.5
    assert result.reachable_next_session is False


def test_an_etf_reachability_is_not_judged():
    result = BREAKOUT.observation_levels(
        next_inputs(instrument_type="etf", etf_category="broad_market", close=50.0)
    )
    assert result.availability == "levels"
    assert result.trigger_price == 100.05  # ETF ladder: 0.05 above 50
    assert result.reachable_next_session is None


@pytest.mark.parametrize(
    "closes, close, low, high, position, entry",
    [
        # S19 = 1900, S59 = 5500: L = max(ceil(96.847), ceil(93.220)) = 96.9,
        # U = floor(102.107) = 102.0 (0.5 ticks from 100)
        ((90.0,) * 40 + (100.0,) * 19, 100.0, 96.9, 102.0, "inside", 100.0),
        # S19 = 1910, S59 = 5510: L = 97.4 (97.357), U = 102.5 (102.645)
        ((90.0,) * 40 + (100.0,) * 18 + (110.0,), 110.0, 97.4, 102.5, "above", 102.5),
        # S19 = 1894, S59 = 5494: L = 96.6 (96.541), U = 101.5 (101.785)
        ((90.0,) * 40 + (100.0,) * 18 + (94.0,), 94.0, 96.6, 101.5, "below", 96.6),
        # MA60 bound wins: S19 = 1919, S59 = 5900 (means 101 and 100), so
        # close >= S59/59 = 100.0 beats the zone's 97.9 (97.815) and the trend's
        # 71.6 (71.5); U = 103.0 (103.128)
        ((99.525,) * 40 + (101.0,) * 19, 101.0, 100.0, 103.0, "inside", 101.0),
    ],
)
def test_pullback_close_range_and_reference_entry(
    closes, close, low, high, position, entry
):
    result = PULLBACK.observation_levels(next_inputs(closes=closes, close=close))
    assert result.availability == "levels"
    assert (result.zone_low, result.zone_high) == (low, high)
    assert result.next_session["pullback_support_zone"]["position"] == position
    assert result.reference_entry == entry
    # 0.6 x 1001 = 600.6 rounds up, 1.2 x 1001 = 1201.2 rounds down.
    assert (result.min_volume, result.max_volume) == (601, 1201)
    # Entry zone around the MA20 the entry close would make, as actionable_levels.
    ma20 = (sum(closes[-19:]) + entry) / 20
    width = max(2.0 * 0.5, entry * 0.005)
    assert (result.entry_low, result.entry_high) == (
        round(ma20 - width, 2),
        round(ma20 + width, 2),
    )
    assert result.reachable_next_session is True
    gap = result.next_session["pullback_support_zone"]["gap"]
    assert (
        gap
        == {
            "inside": 0.0,
            "above": round(102.5 / 110 - 1, 6),
            "below": round(96.6 / 94 - 1, 6),
        }[position]
    )


def test_a_pullback_range_beyond_the_daily_limit_is_not_reachable():
    # S19 = 1940, S59 = 5540: L = 98.9 (98.896), U = 104.0 (104.257).  From
    # close 140.0 the limit down is 126.0, above U: no close in range next session.
    result = PULLBACK.observation_levels(
        next_inputs(closes=(90.0,) * 40 + (100.0,) * 18 + (140.0,), close=140.0)
    )
    assert result.availability == "levels"
    assert (result.zone_low, result.zone_high) == (98.9, 104.0)
    assert levels.price_limits(next_inputs(close=140.0)) == (126.0, 154.0)
    assert result.reachable_next_session is False


def test_a_pullback_whose_trend_cannot_pass_gets_no_price_levels():
    # S59 = 6700, S19 = 1900: MA20 > MA60 needs a close above
    # (6700 - 5700) / 2 = 500 (strictly: 501), but the zone ends at 102.0.
    result = PULLBACK.observation_levels(
        next_inputs(closes=(120.0,) * 40 + (100.0,) * 19, close=100.0)
    )
    assert result.availability == "trend_unreachable"
    assert result.missing_inputs == ("trend_cannot_pass_within_support_zone",)
    assert all(
        value is None
        for value in (
            result.zone_low,
            result.zone_high,
            result.reference_entry,
            result.invalid_price,
            result.target_1,
            result.min_volume,
            result.max_volume,
            result.reachable_next_session,
        )
    )
    assert result.next_session["pullback_trend"] == {"min_close": 501.0}
    # 6700 / 59 = 113.559, rounded up on the 0.5 ticks of 100-500.
    assert result.next_session["pullback_above_ma60"] == {"min_close": 114.0}
    assert result.next_session["pullback_support_zone"]["max_close"] == 102.0


def test_missing_inputs_are_listed_instead_of_levels():
    result = BREAKOUT.observation_levels(
        next_inputs(highs=(100.0,) * 19, institutional_flow_ratio_5d=None)
    )
    assert result.availability == "data_incomplete"
    assert result.missing_inputs == (
        "prior_20_highs_missing_or_invalid",
        "institutional_flow_to_turnover_ratio_5d_missing_or_non_finite",
    )
    assert result.trigger_price is None
    short = PULLBACK.observation_levels(next_inputs(bar_count=50, volumes=VOLUMES[:5]))
    assert short.availability == "data_incomplete"
    assert short.missing_inputs == (
        "history_under_60_bars",
        "prior_20_volumes_missing_or_invalid",
    )


def test_an_excluded_etf_category_is_not_applicable():
    for strategy in (BREAKOUT, PULLBACK):
        result = strategy.observation_levels(
            next_inputs(instrument_type="etf", etf_category="bond")
        )
        assert result.availability == "not_applicable"
        assert result.missing_inputs == (
            "etf_category_excluded_from_actionable_signals:bond",
        )
        assert result.trigger_price is None and result.zone_low is None


def test_an_ipo_under_60_bars_next_session_gets_no_levels():
    young = next_inputs(instrument_type="ipo", bar_count=40)
    for strategy in (BREAKOUT, PULLBACK):
        result = strategy.observation_levels(young)
        assert result.availability == "data_incomplete"
        assert result.missing_inputs == ("ipo_observation_only_under_60_bars",)
    # 59 bars through T is 60 next session: eligible, so levels are given.
    ready = next_inputs(instrument_type="ipo", bar_count=59)
    assert BREAKOUT.observation_levels(ready).availability == "levels"
    assert PULLBACK.observation_levels(ready).availability == "levels"


def test_a_suspended_signal_day_gets_no_levels():
    for strategy in (BREAKOUT, PULLBACK):
        result = strategy.observation_levels(next_inputs(is_suspended=True))
        assert result.availability == "suspended"
        assert result.missing_inputs == ("signal_day_suspended",)


# ---- worker step on a small database ----

# 00967B (TPEx) bars 2026-09-21 .. 10-21: (date, high, close, volume).  Its
# 10/22 ex-dividend (cash 0.033, reference 8.87) was stored before 10/22's
# analyze, which rebased the prior highs: the max 8.93 became 8.896777.
BARS_00967B = [
    (date(2026, 9, 21), 8.87, 8.79, 106966),
    (date(2026, 9, 22), 8.79, 8.78, 117579),
    (date(2026, 9, 23), 8.81, 8.80, 164189),
    (date(2026, 9, 24), 8.73, 8.68, 171294),
    (date(2026, 9, 29), 8.68, 8.52, 1133581),
    (date(2026, 9, 30), 8.54, 8.53, 252451),
    (date(2026, 10, 1), 8.51, 8.51, 333562),
    (date(2026, 10, 2), 8.66, 8.51, 791166),
    (date(2026, 10, 5), 8.63, 8.47, 690284),
    (date(2026, 10, 6), 8.44, 8.42, 515998),
    (date(2026, 10, 7), 8.79, 8.42, 539724),
    (date(2026, 10, 8), 8.43, 8.42, 280241),
    (date(2026, 10, 12), 8.56, 8.55, 443496),
    (date(2026, 10, 13), 8.63, 8.62, 305154),
    (date(2026, 10, 14), 8.69, 8.65, 282687),
    (date(2026, 10, 15), 8.81, 8.80, 936408),
    (date(2026, 10, 16), 8.89, 8.85, 654514),
    (date(2026, 10, 19), 8.93, 8.90, 668977),
    (date(2026, 10, 20), 8.87, 8.87, 562497),
    (date(2026, 10, 21), 8.93, 8.87, 345172),
]
T = date(2026, 10, 21)
EX_DATE = date(2026, 10, 22)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


def seed(db, *, category="broad_market", ex_dividend=True, suspended=False):
    """00967B's bars and T's two analysis signals; the category is a fixture choice.

    The real 00967B is a bond ETF (not_applicable); the default category makes
    its numbers produce levels so the basis conversion is visible.
    """

    instrument = Instrument(
        market="TW",
        exchange="TPEx",
        symbol="00967B",
        name="fixture",
        instrument_type="etf",
        etf_category=category,
        status="active",
    )
    db.add(instrument)
    db.flush()
    for day, high, close, volume in BARS_00967B:
        db.add(
            MarketBar(
                instrument_id=instrument.id,
                trading_date=day,
                open=close,
                high=high,
                low=close,
                close=close,
                adj_close=close,
                volume=volume,
                turnover=volume * close,
                source="fixture",
                is_suspended=suspended and day == T,
            )
        )
    db.add(
        TechnicalFeature(
            instrument_id=instrument.id,
            trading_date=T,
            features_json={"atr14": 0.05},
            source="derived",
        )
    )
    if ex_dividend:
        db.add(
            CorporateAction(
                instrument_id=instrument.id,
                action_date=EX_DATE,
                action_type="ex_dividend",
                cash_dividend=0.033,
                stock_dividend_ratio=0.0,
                reference_price=8.87,
                source="fixture",
            )
        )
    versions = pipeline._ensure_strategies(db)
    evidence_inputs = {
        "prior_20_highs": [8.86] + [high for _d, high, _c, _v in BARS_00967B[:-1]],
        "prior_20_volumes": [127448] + [v for _d, _h, _c, v in BARS_00967B[:-1]],
        "group_excess_return_20d": 0.01,
        "institutional_flow_to_turnover_ratio_5d": 0.0,
        "margin_balance_change_ratio_5d": 0.0,
        "bar_count_60d": 20,
        "ma20": 8.7,
        "ma60": None,
    }
    states = {
        BREAKOUT.kind: {
            "state": "rejected",
            "reasons": ["close_not_above_prior_20_day_high", "volume_ratio_below_1_20"],
        },
        PULLBACK.kind: {
            "state": "data_incomplete",
            "reasons": ["history_under_60_bars"],
        },
    }
    signals = {}
    for key, strategy in REGISTRY.items():
        version = versions[key]
        signal = Signal(
            signal_key=f"analysis-TPEx-00967B-{T.isoformat()}-{key}-{version.version}",
            signal_date=T,
            instrument_id=instrument.id,
            strategy_version_id=version.id,
            status="observation",
            entry_type=strategy.entry_type,
            rationale="fixture",
            rule_evidence_json={**states, "inputs": evidence_inputs},
        )
        db.add(signal)
        signals[strategy.entry_type] = signal
    db.flush()
    return instrument, signals


def level_of(db, signal) -> StrategyLevel:
    return db.scalar(select(StrategyLevel).where(StrategyLevel.signal_id == signal.id))


def conditions_of(db, signal, strategy) -> list[dict]:
    """The full condition list of a stored row (conditions_json is compact)."""

    return levels.expand_conditions(strategy, level_of(db, signal).conditions_json)


def test_a_stored_next_session_ex_dividend_rebases_the_trigger(db):
    _instrument, signals = seed(db)
    result = compute_strategy_levels(db, T, now=datetime(2026, 10, 21, 22, 0))
    assert result["status"] == "success"
    assert (result["signals"], result["rows_written"]) == (2, 2)
    row = level_of(db, signals["breakout"])
    assert row.levels_version == STRATEGY_LEVELS_VERSION
    assert row.next_session_date == EX_DATE
    assert row.price_basis == "next_session_raw_basis"
    # 8.93 x (8.87 - 0.033) / 8.87 = 8.896777: the next ETF tick above is 8.90.
    # 10/22 closed at 8.90, and its analyze did not reject the price.
    assert row.trigger_price == 8.9
    # ceil(1.2 x 9,295,940 / 20) shares
    assert row.min_volume == 557757
    assert row.availability == "levels"
    assert row.reachable_next_session is None  # ETF
    pullback = level_of(db, signals["pullback"])
    assert pullback.availability == "data_incomplete"
    assert pullback.missing_inputs_json == ["history_under_60_bars"]
    assert pullback.price_basis == "next_session_raw_basis"


def test_without_a_stored_action_the_signal_day_basis_is_kept(db):
    _instrument, signals = seed(db, ex_dividend=False)
    compute_strategy_levels(db, T)
    row = level_of(db, signals["breakout"])
    assert row.price_basis == "score_date_raw_basis"
    # Unconverted, the trigger is above 8.93 and 10/22's 8.90 close misses it.
    assert row.trigger_price == 8.94
    assert row.next_session_date == EX_DATE  # next weekday, no later bar stored


def test_the_real_bond_category_is_not_applicable(db):
    _instrument, signals = seed(db, category="bond")
    compute_strategy_levels(db, T)
    for signal in signals.values():
        row = level_of(db, signal)
        assert row.availability == "not_applicable"
        assert row.missing_inputs_json == [
            "etf_category_excluded_from_actionable_signals:bond"
        ]
        assert row.trigger_price is None and row.zone_low is None


def test_a_suspended_day_is_recorded_in_levels_and_conditions(db):
    _instrument, signals = seed(db, suspended=True)
    compute_strategy_levels(db, T)
    row = level_of(db, signals["breakout"])
    assert row.availability == "suspended"
    eligibility = conditions_of(db, signals["breakout"], BREAKOUT)[0]
    assert eligibility["code"] == "eligibility"
    assert eligibility["satisfied"] is False
    assert eligibility["reasons"] == ["signal_day_suspended"]


def test_conditions_carry_t_results_and_the_next_session_requirement(db):
    _instrument, signals = seed(db)
    compute_strategy_levels(db, T)
    by_code = {
        item["code"]: item for item in conditions_of(db, signals["breakout"], BREAKOUT)
    }
    assert list(by_code) == [
        "eligibility",
        "required_inputs",
        "breakout_price",
        "breakout_volume",
        "group_relative_strength",
        "institutional_flow",
        "margin_financing",
    ]
    price = by_code["breakout_price"]
    assert price["satisfied"] is False
    assert (price["actual"], price["threshold"], price["operator"]) == (
        8.87,
        8.93,
        "gt",
    )
    # The gap is from T's close in the next session's basis (8.87 x factor).
    factor = (8.87 - 0.033) / 8.87
    assert price["next_session"] == {
        "min_close": 8.9,
        "gap": round(8.9 / (8.87 * factor) - 1, 6),
    }
    volume = by_code["breakout_volume"]
    assert volume["satisfied"] is False
    assert volume["next_session"] == {"min_volume": 557757}
    assert by_code["group_relative_strength"]["satisfied"] is True
    pullback = {
        item["code"]: item for item in conditions_of(db, signals["pullback"], PULLBACK)
    }
    assert pullback["required_inputs"]["satisfied"] is False
    assert pullback["required_inputs"]["reasons"] == ["history_under_60_bars"]
    assert pullback["pullback_history"]["satisfied"] is False
    assert pullback["pullback_trend"]["satisfied"] is None


# ---- conditions_json is stored without each strategy's defaults (#274, L3) ----


# Each levels version's condition defaults: the fields a stored row omits.
# Rows of a version read back with that version's defaults, so changing a
# default without a new STRATEGY_LEVELS_VERSION key here fails (#274 review L1).
_COMMON_DEFAULTS = {
    "eligibility": {
        "code": "eligibility",
        "kind": "eligibility",
        "satisfied": True,
    },
    "required_inputs": {
        "code": "required_inputs",
        "kind": "data",
        "satisfied": False,
    },
}
_CONFIRMATION_DEFAULTS = {
    "group_relative_strength": {
        "code": "group_relative_strength",
        "kind": "confirmation",
        "threshold": 0.0,
        "operator": "gt",
    },
    "institutional_flow": {
        "code": "institutional_flow",
        "kind": "confirmation",
        "threshold": -0.003,
        "operator": "gte",
    },
    "margin_financing": {
        "code": "margin_financing",
        "kind": "confirmation",
        "threshold": 0.05,
        "operator": "lte",
    },
}
PINNED_CONDITION_DEFAULTS = {
    "strategy_levels_v1": {
        "breakout_v1": {
            **_COMMON_DEFAULTS,
            "breakout_price": {
                "code": "breakout_price",
                "kind": "price",
                "operator": "gt",
            },
            "breakout_volume": {
                "code": "breakout_volume",
                "kind": "volume",
                "threshold": 1.2,
                "operator": "gte",
            },
            **_CONFIRMATION_DEFAULTS,
        },
        "pullback_v1": {
            **_COMMON_DEFAULTS,
            "pullback_history": {
                "code": "pullback_history",
                "kind": "data",
                "satisfied": False,
                "actual": 0,
                "threshold": 60,
                "operator": "gte",
                "next_session": {"bar_count": 1},
            },
            "pullback_trend": {
                "code": "pullback_trend",
                "kind": "trend",
                "operator": "gt",
            },
            "pullback_above_ma60": {
                "code": "pullback_above_ma60",
                "kind": "trend",
                "operator": "gte",
            },
            "pullback_support_zone": {
                "code": "pullback_support_zone",
                "kind": "price",
                "operator": "between",
            },
            "pullback_volume": {
                "code": "pullback_volume",
                "kind": "volume",
                "threshold": 0.6,
                "threshold_high": 1.2,
                "operator": "between",
            },
            **_CONFIRMATION_DEFAULTS,
        },
    },
}


def test_the_condition_defaults_are_pinned_to_the_levels_version():
    assert STRATEGY_LEVELS_VERSION in PINNED_CONDITION_DEFAULTS, (
        "a new levels version needs its condition defaults pinned here"
    )
    filled = {
        key: {
            code: {k: v for k, v in item.items() if v not in (None, [])}
            for code, item in levels.condition_defaults(strategy).items()
        }
        for key, strategy in REGISTRY.items()
    }
    assert filled == PINNED_CONDITION_DEFAULTS[STRATEGY_LEVELS_VERSION]


def test_stored_conditions_omit_the_defaults_and_read_back_whole(db):
    _instrument, signals = seed(db)
    compute_strategy_levels(db, T)
    for entry_type, strategy in (("breakout", BREAKOUT), ("pullback", PULLBACK)):
        stored = level_of(db, signals[entry_type]).conditions_json
        defaults = levels.condition_defaults(strategy)
        # No stored field repeats the strategy's default, and no field is null.
        for item in stored:
            for key, value in item.items():
                if key != "code":
                    assert value != defaults[item["code"]][key], (item["code"], key)
                    assert value is not None, (item["code"], key)
            assert "kind" not in item and "operator" not in item
        full = levels.expand_conditions(strategy, stored)
        assert [set(item) for item in full] == [set(defaults["eligibility"])] * len(
            full
        )
        # Compacting the full list gives the stored one back, and an older
        # full row reads the same as its compact form.
        assert (
            levels.compact_conditions(
                strategy, [Condition(**_condition_args(item)) for item in full]
            )
            == stored
        )
        assert levels.expand_conditions(strategy, full) == full
    price = {
        item["code"]: item for item in level_of(db, signals["breakout"]).conditions_json
    }["breakout_price"]
    # T's prior high is per row, so it stays; the operator is the default.
    assert price["threshold"] == 8.93 and "operator" not in price


def _condition_args(item: dict) -> dict:
    return {**item, "reasons": tuple(item["reasons"])}


def test_conditions_of_an_unknown_code_are_kept_whole():
    unknown = {"code": "future_condition", "kind": "price", "satisfied": True}
    assert levels.expand_conditions(BREAKOUT, [unknown, "noise"]) == [
        {
            "code": "future_condition",
            "kind": "price",
            "satisfied": True,
            "actual": None,
            "threshold": None,
            "threshold_high": None,
            "operator": None,
            "reasons": [],
            "next_session": None,
        }
    ]
    assert levels.expand_conditions(BREAKOUT, None) == []


def signal_rows(db) -> list[dict]:
    return [
        {column.name: getattr(row, column.name) for column in Signal.__table__.columns}
        for row in db.scalars(select(Signal).order_by(Signal.id))
    ]


def test_signals_are_never_changed_and_a_rerun_writes_nothing(db):
    _instrument, signals = seed(db)
    before = signal_rows(db)
    first = datetime(2026, 10, 21, 22, 0)
    compute_strategy_levels(db, T, now=first)
    assert signal_rows(db) == before
    again = compute_strategy_levels(db, T, now=datetime(2026, 10, 22, 22, 0))
    assert (again["rows_written"], again["rows_unchanged"]) == (0, 2)
    assert all(level_of(db, s).computed_at == first for s in signals.values())
    assert signal_rows(db) == before
    # A changed input (the action withdrawn) rewrites the row and its time.
    db.delete(db.scalar(select(CorporateAction)))
    db.flush()
    changed = compute_strategy_levels(db, T, now=datetime(2026, 10, 23, 22, 0))
    assert changed["rows_written"] == 2
    row = level_of(db, signals["breakout"])
    assert (row.trigger_price, row.computed_at) == (8.94, datetime(2026, 10, 23, 22, 0))
    assert db.query(StrategyLevel).count() == 2


def test_a_signal_of_another_strategy_version_is_skipped(db):
    _instrument, signals = seed(db)
    version = signals["breakout"].strategy_version_id
    db.get(StrategyVersion, version).version = "0.9.0"
    db.flush()
    result = compute_strategy_levels(db, T)
    assert (result["signals"], result["signals_skipped"]) == (1, 1)
    assert level_of(db, signals["breakout"]) is None


def test_a_signal_of_another_formula_version_is_skipped(db):
    # #274 review L1: today's condition defaults are not that formula's.
    _instrument, signals = seed(db)
    version = signals["breakout"].strategy_version_id
    db.get(StrategyVersion, version).formula_version = "institutional-flow/v1-old"
    db.flush()
    result = compute_strategy_levels(db, T)
    assert (result["signals"], result["signals_skipped"]) == (1, 1)
    assert level_of(db, signals["breakout"]) is None


def test_a_registered_strategy_without_level_formulas_is_not_applicable(
    db, monkeypatch
):
    from test_strategy_registry import FAKE_CONFIG, FakeStrategy

    monkeypatch.setitem(REGISTRY, FAKE_CONFIG["name"], FakeStrategy())
    _instrument, signals = seed(db)
    result = compute_strategy_levels(db, T)
    assert result["signals"] == 3
    fake = db.scalar(
        select(StrategyLevel)
        .join(Signal, Signal.id == StrategyLevel.signal_id)
        .where(Signal.signal_key.contains(FAKE_CONFIG["name"]))
    )
    assert fake.availability == "not_applicable"
    assert fake.missing_inputs_json == ["observation_levels_not_defined"]
    assert [item["code"] for item in fake.conditions_json] == [
        "eligibility",
        "required_inputs",
    ]


# ---- nothing actionable reads the table ----


def test_an_observation_with_levels_cannot_become_a_tracking_plan(db):
    _instrument, signals = seed(db)
    compute_strategy_levels(db, T)
    assert level_of(db, signals["breakout"]).trigger_price == 8.9
    with pytest.raises(PlanRequestError) as error:
        create_plan(db, signals["breakout"].id)
    assert error.value.code == "signal_not_conditional"


def test_decision_today_and_tracking_code_does_not_read_the_table():
    # The action page list may read conditions_json (#277); the decision
    # summary, the today page, candidates and tracking plans may not.
    endpoints = {
        route.path: route.endpoint
        for route in api_module.router.routes
        if getattr(route, "path", None) in {"/api/dashboard", "/api/candidates"}
    }
    sources = {
        "decision.build_decision_summary": inspect.getsource(
            decision.build_decision_summary
        ),
        **{
            f"api {path}": inspect.getsource(endpoint)
            for path, endpoint in endpoints.items()
        },
        **{
            name: (BACKEND / name).read_text(encoding="utf-8")
            for name in (
                "app/candidate_view.py",
                "app/tracking.py",
                "app/tracking_plans.py",
                "worker/candidates.py",
                "worker/plan_tracking.py",
            )
        },
    }
    assert set(endpoints) == {"/api/dashboard", "/api/candidates"}
    readers = [
        name
        for name, source in sources.items()
        if "StrategyLevel" in source or "strategy_levels" in source
    ]
    assert readers == []


def _without_clock(value):
    """Drop the response times, the only fields that differ between two builds."""

    if isinstance(value, dict):
        return {
            k: _without_clock(v)
            for k, v in value.items()
            if not k.endswith("generated_at")
        }
    if isinstance(value, list):
        return [_without_clock(item) for item in value]
    return value


def test_action_summaries_are_the_same_with_strategy_levels(tmp_path, monkeypatch):
    from test_product import (
        _add_base_fixture,
        _add_decision_history,
        _add_signal_pair,
    )

    from app.migrations import upgrade_database

    engine = create_engine(f"sqlite:///{tmp_path / 'levels.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        with factory() as session:
            as_of, alpha, _beta, _etf = _add_base_fixture(session)
            _add_decision_history(session, alpha, as_of)
            # A conditional breakout and an observation pullback.
            _add_signal_pair(session, alpha, as_of)
            session.commit()
            before = decision.build_action_summaries(session)
            signal_ids = session.scalars(select(Signal.id)).all()
            assert signal_ids
            for signal_id in signal_ids:
                session.add(
                    StrategyLevel(
                        signal_id=signal_id,
                        levels_version=STRATEGY_LEVELS_VERSION,
                        availability="levels",
                        trigger_price=1.0,
                        zone_low=1.0,
                        zone_high=2.0,
                        reference_entry=1.0,
                        invalid_price=0.5,
                        target_1=2.0,
                        conditions_json=[{"code": "breakout_price"}],
                        missing_inputs_json=[],
                        price_basis="score_date_raw_basis",
                    )
                )
            session.commit()
            session.info.clear()
            after = decision.build_action_summaries(session)
        assert len(before) == 1 and before[0]["action_state"] == "conditional_entry"
        assert _without_clock(after) == _without_clock(before)
    finally:
        engine.dispose()
