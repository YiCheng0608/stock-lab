"""A candidate's plain-language entry plan reads its strategy_levels row (#491).

``entry_plan`` of ``/api/candidates`` and of the stock detail's candidate is
the candidate signal's ``strategy_levels`` row of the current levels version,
passed through as stored (docs/spec/strategy_levels.md); the candidate's own
``levels`` (the signal's) do not change.  No row means no plan, never a
guessed price.
"""

from __future__ import annotations

import test_candidates
from test_candidates import T, signal, stock

from app.domain import STRATEGY_LEVELS_VERSION
from app.models import StrategyLevel
from app.strategies import REGISTRY
from app.strategies.levels import condition_defaults
from worker.candidates import compute_daily_candidates

# The candidate tests' in-memory database and API client.
db = test_candidates.db
client = test_candidates.client

NEXT = "2026-09-07"


def levels_row(db, signal_row, **values):
    defaults = dict(
        signal_id=signal_row.id,
        levels_version=STRATEGY_LEVELS_VERSION,
        availability="levels",
        next_session_date=T.replace(day=7),
        conditions_json=[],
        missing_inputs_json=[],
        price_basis="score_date_raw_basis",
    )
    row = StrategyLevel(**{**defaults, **values})
    db.add(row)
    db.flush()
    return row


def listed(client):
    return {
        item["instrument"]["symbol"]: item
        for item in client.get("/api/candidates").json()["items"]
    }


def test_breakout_and_pullback_plans_are_the_stored_levels(db, client):
    a, b = stock(db, "1101"), stock(db, "1102")
    breakout = signal(db, a, volume_ratio=2.0)
    pullback = signal(db, b, "pullback_v3", volume_ratio=0.8)
    levels_row(
        db,
        breakout,
        trigger_price=101.5,
        min_volume=1_210_400,
        reference_entry=101.5,
        invalid_price=98.3,
        target_1=106.6,
        target_2=111.1,
        risk_reward=1.6,
        reachable_next_session=True,
        conditions_json=[
            {
                "code": "breakout_price",
                "satisfied": True,
                "actual": 100.0,
                "next_session": {"min_close": 101.5, "gap": 0.015},
            },
            {"code": "breakout_volume", "satisfied": True, "actual": 2.0},
        ],
    )
    levels_row(
        db,
        pullback,
        zone_low=98.55,
        zone_high=101.2,
        min_volume=600_000,
        max_volume=1_200_000,
        reference_entry=100.0,
        entry_low=99.0,
        entry_high=101.0,
        invalid_price=96.8,
        target_1=105.1,
        target_2=109.6,
        risk_reward=1.6,
        reachable_next_session=True,
    )
    db.commit()
    compute_daily_candidates(db, T)

    items = listed(client)
    plan = items["1101"]["entry_plan"]
    assert {
        key: plan[key]
        for key in (
            "levels_version",
            "entry_type",
            "availability",
            "next_session_date",
            "trigger_price",
            "min_volume",
            "invalid_price",
            "target_1",
            "target_2",
            "reachable_next_session",
        )
    } == {
        "levels_version": STRATEGY_LEVELS_VERSION,
        "entry_type": "breakout",
        "availability": "levels",
        "next_session_date": NEXT,
        "trigger_price": 101.5,
        "min_volume": 1_210_400,
        "invalid_price": 98.3,
        "target_1": 106.6,
        "target_2": 111.1,
        "reachable_next_session": True,
    }
    # The full condition list, the stored compact rows expanded with the
    # strategy's defaults (kind, operator, threshold).
    defaults = condition_defaults(REGISTRY["breakout_v3"])
    assert [item["code"] for item in plan["conditions"]] == [
        "breakout_price",
        "breakout_volume",
    ]
    price, volume = plan["conditions"]
    assert price["next_session"] == {"min_close": 101.5, "gap": 0.015}
    assert price["kind"] == defaults["breakout_price"]["kind"]
    assert volume["threshold"] == defaults["breakout_volume"]["threshold"]
    # The signal's own levels are unchanged by the plan.
    assert items["1101"]["levels"]["entry"] == 100.0
    assert items["1101"]["levels"]["invalid_price"] == 98.0

    pull = items["1102"]["entry_plan"]
    assert (pull["entry_type"], pull["zone_low"], pull["zone_high"]) == (
        "pullback",
        98.55,
        101.2,
    )
    assert (pull["min_volume"], pull["max_volume"], pull["invalid_price"]) == (
        600_000,
        1_200_000,
        96.8,
    )

    detail = client.get("/api/stocks/TWSE/1101").json()
    assert detail["candidate"]["entry_plan"] == plan


def test_a_plan_without_levels_carries_the_reason(db, client):
    a = stock(db, "1101")
    pullback = signal(db, a, "pullback_v3", volume_ratio=0.8)
    levels_row(
        db,
        pullback,
        availability="trend_unreachable",
        missing_inputs_json=["trend_cannot_pass_within_support_zone"],
    )
    db.commit()
    compute_daily_candidates(db, T)

    plan = listed(client)["1101"]["entry_plan"]
    assert plan["availability"] == "trend_unreachable"
    assert (plan["zone_low"], plan["zone_high"], plan["invalid_price"]) == (
        None,
        None,
        None,
    )
    assert plan["missing_inputs"] == ["trend_cannot_pass_within_support_zone"]
    assert plan["missing_labels"] and all(plan["missing_labels"])


def test_a_signal_without_a_current_levels_row_has_no_plan(db, client):
    a, b = stock(db, "1101"), stock(db, "1102")
    signal(db, a, volume_ratio=2.0)
    other = signal(db, b, volume_ratio=2.0)
    # Another levels version is not this version's plan.
    levels_row(db, other, levels_version="strategy_levels_v0", trigger_price=1.0)
    db.commit()
    compute_daily_candidates(db, T)

    items = listed(client)
    assert items["1101"]["entry_plan"] is None
    assert items["1102"]["entry_plan"] is None
