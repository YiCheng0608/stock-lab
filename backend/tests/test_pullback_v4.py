"""pullback_v4 (Issue #580): the RR is read at the entry zone's midpoint.

The page tells the reader to enter inside the entry zone, but up to v3 the
RR's entry (``reference_entry``) was T's close.  v4 stores the zone's
midpoint there and keeps the zone, the stop and the targets of v3, so the RR
is recomputed and the 1.5 floor judges it (decision 6745091777).
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from test_margin_not_applicable import T
from test_margin_zero_base import _zero_base_security

from app.db import Base, enable_sqlite_foreign_keys
from app.domain import (
    CANDIDATE_SCORE,
    MINIMUM_FIRST_TARGET_RISK_REWARD,
    validate_signal_levels,
)
from app.level_semantics import build_level_semantics
from app.models import Signal, StrategyVersion
from app.strategies import (
    LEGACY_RISK_LEVELS_FORMULA,
    PULLBACK_ZONE_MIDPOINT_FORMULA,
    REGISTRY,
    SUCCESSOR,
    SUPERSEDED,
    StrategyInputs,
    risk_reward_basis,
)
from app.strategy_board import risk_reward_shortfall
from worker import pipeline

V3 = SUPERSEDED["pullback_v3"]
V4 = REGISTRY["pullback_v4"]


@pytest.fixture
def db():
    # As test_margin_zero_base's (whose security helper builds the rows).
    engine = create_engine("sqlite:///:memory:")
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    pipeline._MARGIN_LIST_CACHE.clear()
    with factory() as session:
        yield session
    pipeline._MARGIN_LIST_CACHE.clear()
    engine.dispose()


def _inputs(**changes: Any) -> StrategyInputs:
    """A pullback that passes: MA20 100 over MA60 90, volume at its average."""

    values: dict[str, Any] = dict(
        bar_count=60,
        close=100.0,
        volume=1000.0,
        ma20=100.0,
        ma60=90.0,
        atr14=2.0,
        prior_highs=[101.0] * 20,
        prior_volumes=[1000] * 20,
        group_excess_return_20d=0.02,
        institutional_flow_ratio_5d=0.0,
        margin_change_ratio_5d=0.0,
    )
    values.update(changes)
    return StrategyInputs(**values)


def _rr(levels) -> float:
    return (levels.target_1 - levels.reference_entry) / (
        levels.reference_entry - levels.invalid_price
    )


def _validation(levels):
    return validate_signal_levels(
        entry_type="pullback",
        reference_entry=levels.reference_entry,
        breakout_price=levels.breakout_price,
        invalid_price=levels.invalid_price,
        target_1=levels.target_1,
        target_2=levels.target_2,
    )


# close, ATR14 -> where the close is against the zone MA20 ± max(0.5·ATR, 0.5%):
# with ATR 2 the zone is 99～101 (midpoint 100); with ATR 3 it is 98.5～101.5.
CASES = {
    # stop 95.5, target 100.7: (100.7−100)/(100−95.5) ≈ 0.16 against 1.6.
    "below": (97.5, 2.0, "lower"),
    # inside, under the midpoint: stop 97.5, target 102.7: 2.7/2.5 = 1.08.
    "inside_below_midpoint": (99.5, 2.0, "lower"),
    # inside, over the midpoint: stop 98.5, target 103.7: 3.7/1.5 ≈ 2.47.
    "inside_above_midpoint": (100.5, 2.0, "higher"),
    # above: stop 98.8, target 106.6: 6.6/1.2 = 5.5.
    "above": (101.8, 3.0, "higher"),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_rr_is_read_at_the_entry_zone_midpoint(case):
    close, atr, direction = CASES[case]
    inputs = _inputs(close=close, atr14=atr)
    assert V3.evaluate(inputs).passed and V4.evaluate(inputs).passed
    old, new = V3.actionable_levels(inputs), V4.actionable_levels(inputs)

    midpoint = round((new.pullback_low + new.pullback_high) / 2, 2)
    assert new.reference_entry == midpoint == 100.0
    assert old.reference_entry == close
    position = (
        "below"
        if close < new.pullback_low
        else "above"
        if close > new.pullback_high
        else "inside"
    )
    assert case.startswith(position)
    # The zone, the stop and the targets keep v3's definitions (around the close).
    for field in (
        "pullback_low",
        "pullback_high",
        "invalid_price",
        "target_1",
        "target_2",
    ):
        assert getattr(new, field) == getattr(old, field), field
    assert round(_rr(old), 2) == 1.6
    if direction == "lower":
        assert _rr(new) < _rr(old)
    else:
        assert _rr(new) > _rr(old)
    # The floor judges the new RR.
    validation = _validation(new)
    assert validation.valid is (_rr(new) >= MINIMUM_FIRST_TARGET_RISK_REWARD)
    if not validation.valid:
        assert validation.errors == ("target_1_risk_reward_below_minimum",)


@pytest.mark.parametrize(
    "close, atr, error",
    [
        # risk 1, target 98.6 under the midpoint 100 (zone 99.5～100.5).
        (97.0, 1.0, "target_1_must_exceed_entry"),
        # risk 1.02, stop 100.98 over the midpoint 100 (zone 99.49～100.51).
        (102.0, 1.0, "invalid_price_must_be_below_entry"),
    ],
)
def test_a_midpoint_beyond_the_target_or_the_stop_is_invalid(close, atr, error):
    inputs = _inputs(close=close, atr14=atr)
    assert V4.evaluate(inputs).passed
    levels = V4.actionable_levels(inputs)
    assert levels.reference_entry == 100.0
    assert error in _validation(levels).errors
    # v3 kept the close as the entry: valid at 1.6.
    assert _validation(V3.actionable_levels(inputs)).valid


@pytest.mark.parametrize(
    "close, atr, valid",
    [(97.0, 1.0, False), (102.0, 1.0, False), (97.5, 2.0, False), (101.8, 3.0, True)],
)
def test_analyze_records_invalid_levels_when_the_midpoint_rr_fails(
    db, tmp_path, monkeypatch, close, atr, valid
):
    instrument = _zero_base_security(db, tmp_path, monkeypatch)
    real_context = pipeline._signal_context

    def context(*args, **kwargs):
        found = real_context(*args, **kwargs)
        return dataclasses.replace(
            found,
            inputs=dataclasses.replace(
                _inputs(close=close, atr14=atr), bar_count=found.inputs.bar_count
            ),
        )

    monkeypatch.setattr(pipeline, "_signal_context", context)
    strategies = pipeline._ensure_strategies(db)
    pipeline._upsert_signal(
        db, instrument=instrument, signal_date=T, strategies=strategies
    )
    db.flush()
    row = db.scalar(
        select(Signal)
        .join(StrategyVersion, StrategyVersion.id == Signal.strategy_version_id)
        .where(Signal.signal_date == T, StrategyVersion.name == "pullback_v4")
    )
    assert row.reference_entry == 100.0
    assert row.rule_evidence_json["risk_validation"]["valid"] is valid
    if valid:
        # The fixture has no group score, so a valid pullback stays incomplete.
        assert row.status == "data_incomplete"
    else:
        assert row.status == "invalid_levels"
        assert row.rule_evidence_json["actionable"] is False
        # The levels stay on the row (the board states the RR).
        assert row.invalid_price is not None and row.target_1 is not None


def test_v4_differs_from_v3_only_in_its_identity_and_the_rr_entry():
    assert list(REGISTRY) == ["breakout_v3", "pullback_v4"]
    assert SUCCESSOR["pullback_v3"] == "pullback_v4"
    assert V4.config["supersedes"] == {"name": "pullback_v3", "version": "3.0.0"}
    assert (V4.kind, V4.entry_type) == (V3.kind, V3.entry_type)
    old, new = dict(V3.config), dict(V4.config)
    risk = dict(new.pop("risk_management"))
    assert risk.pop("risk_reward_entry") == "pullback_zone_midpoint"
    assert risk == old.pop("risk_management")
    for field in ("name", "version", "supersedes"):
        old.pop(field)
        new.pop(field)
    assert new == old
    assert V4.version == "4.0.0"
    # v3's configuration is not changed (its rows keep their snapshot).
    assert "risk_reward_entry" not in V3.config["risk_management"]
    # The candidate pool reads v4 (candidate_score_v7).
    assert CANDIDATE_SCORE["pool"]["strategies"] == ["breakout_v3", "pullback_v4"]


def test_the_level_formula_and_rr_basis_are_named_per_version():
    assert V3.level_formula_version == LEGACY_RISK_LEVELS_FORMULA
    assert V4.level_formula_version == PULLBACK_ZONE_MIDPOINT_FORMULA
    assert risk_reward_basis("pullback_v4") == "entry_zone_midpoint"
    assert risk_reward_basis("pullback_v3") == "signal_close"
    assert risk_reward_basis("pullback_v1") == "signal_close"
    assert risk_reward_basis("breakout_v3") == "entry_price"
    assert risk_reward_basis("unknown") is None
    v4 = build_level_semantics(strategy_name="pullback_v4", strategy_version="4.0.0")
    assert v4["kind"] == "rule_reference"
    assert v4["formula"]["version"] == PULLBACK_ZONE_MIDPOINT_FORMULA
    assert "(pullback_low+pullback_high)/2" in v4["formula"]["expression"]
    v3 = build_level_semantics(strategy_name="pullback_v3", strategy_version="3.0.0")
    assert v3["formula"]["version"] == LEGACY_RISK_LEVELS_FORMULA
    # A version the strategy does not have is still unknown.
    assert (
        build_level_semantics(strategy_name="pullback_v4", strategy_version="3.0.0")[
            "kind"
        ]
        == "unknown"
    )


def _invalid_levels(**changes: Any) -> Signal:
    values: dict[str, Any] = dict(
        status="invalid_levels",
        entry_type="pullback",
        reference_entry=100.0,
        pullback_low=99.0,
        pullback_high=101.0,
        invalid_price=95.5,
        target_1=100.7,
        rationale="breakout=not_triggered; pullback=passed; required inputs complete",
        rule_evidence_json={
            "risk_validation": {
                "valid": False,
                "errors": ["target_1_risk_reward_below_minimum"],
            }
        },
    )
    values.update(changes)
    return Signal(**values)


def test_the_board_reads_an_rr_shortfall_as_an_observation_with_its_rr():
    assert risk_reward_shortfall(V4, _invalid_levels()) == {
        "risk_reward": round(0.7 / 4.5, 4),
        "minimum": 1.5,
        "risk_reward_basis": "entry_zone_midpoint",
        "entry": 100.0,
        "errors": ["target_1_risk_reward_below_minimum"],
    }
    # A midpoint at or past the target has no RR to state.
    beyond = _invalid_levels(
        target_1=98.6,
        rule_evidence_json={
            "risk_validation": {
                "valid": False,
                "errors": ["target_1_must_exceed_entry"],
            }
        },
    )
    assert risk_reward_shortfall(V4, beyond)["risk_reward"] is None
    # Not a shortfall: missing inputs, another level error, another status.
    assert (
        risk_reward_shortfall(
            V4,
            _invalid_levels(rationale="pullback=passed; missing=signal_day_suspended"),
        )
        is None
    )
    assert (
        risk_reward_shortfall(
            V4,
            _invalid_levels(
                rule_evidence_json={
                    "risk_validation": {
                        "valid": False,
                        "errors": ["target_1_must_be_finite_and_positive"],
                    }
                }
            ),
        )
        is None
    )
    assert risk_reward_shortfall(V4, _invalid_levels(status="observation")) is None
