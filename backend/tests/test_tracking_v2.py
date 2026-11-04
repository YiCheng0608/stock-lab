"""tracking_v2 (#444, docs/spec/tracking.md 口徑版本): T+N only uses a fill by session N,
and a fill session that opens beyond the first target or the invalid price is not entered.

Imports only names the tracking_v1 module also has, so the same file runs against the
old rules (the AC-1 red run) and fails by assertion rather than at collection.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.tracking import (
    ROUND_TRIP_TRANSACTION_COST_BPS,
    TrackBar,
    TrackLevels,
    settle,
    track_path,
)

PLAN_DAY = date(2026, 9, 1)  # a Tuesday
COST = ROUND_TRIP_TRANSACTION_COST_BPS / 10_000.0
BUY = 1.0005  # 5 bps adverse fill
SELL = 0.9995

# (open, high, low, close) against breakout 100, invalid 98, target 103.2.
FLAT = (99.0, 99.5, 98.5, 99.0)
FILL = (99.5, 100.5, 99.2, 100.2)
INSIDE = (100.0, 101.0, 99.0, 101.0)
TARGET = (101.0, 103.5, 100.5, 103.0)
STOP = (99.0, 99.5, 97.5, 98.0)
BOTH = (100.0, 104.0, 97.0, 100.0)

LEVELS = TrackLevels("breakout", 100.0, None, None, 98.0, 103.2)


def sessions_after(day: date, count: int) -> list[date]:
    days, cursor = [], day
    while len(days) < count:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            days.append(cursor)
    return days


def track_bar(day, ohlc):
    o, h, low, c = ohlc
    return TrackBar(
        trading_date=day,
        open=o,
        high=h,
        low=low,
        close=c,
        adj_close=c,
        volume=1000,
        is_suspended=False,
        source="fixture-bars",
        data_time=None,
        factor=1.0,
        action_applied=False,
        suspension_gap=False,
    )


def path_of(*ohlcs, levels=LEVELS):
    days = sessions_after(PLAN_DAY, len(ohlcs))
    return track_path(levels, [track_bar(d, o) for d, o in zip(days, ohlcs)])


# 6221 in #318: breakout 28.15, first target 28.6, the fill session opened at 30.97.
GAP_LEVELS = TrackLevels("breakout", 28.15, None, None, 27.5, 28.6)
GAP_6221 = (30.97, 31.2, 30.1, 30.5)
ZONE = TrackLevels("pullback", None, 99.0, 101.0, 97.0, 104.0)


def test_a_fill_after_the_horizon_is_not_a_t_plus_n_result():
    # FLAT x5, then the fill on session 6: no fill on or before T+5.
    path = path_of(*[FLAT] * 5, FILL, INSIDE)
    result = settle(path, 5)
    assert result["comparable"] is False
    assert result["final_status"] == "incomparable"
    assert result["incomparable_reason"] == "not_filled_by_horizon"
    assert result["return_or_risk"] is None
    # Nothing from after T+5 leaks into the T+5 row.
    assert result["execution_date"] is None and result["execution_price"] is None
    assert result["first_trigger"] is None
    assert result["settlement_date"] == sessions_after(PLAN_DAY, 5)[4]
    # The same path is a T+6 result: filled on session 6.
    assert settle(path, 6)["comparable"] is True


def test_a_gap_open_at_or_above_the_first_target_is_not_entered():
    path = path_of(GAP_6221, (29.0, 29.5, 28.0, 28.4), levels=GAP_LEVELS)
    assert not path.executed and path.first_outcome is None
    assert path.execution_price is None and path.outcome_price is None
    assert [s.status for s in path.sessions] == ["not_entered", "not_entered"]
    # Not entering is final: a later session inside the levels does not fill.
    assert path.sessions[1].execution_price is None
    result = settle(path, 2)
    assert result["comparable"] is False and result["return_or_risk"] is None
    assert result["incomparable_reason"] == "gap_above_target"
    # Exactly at the target counts as at or above it.
    at_target = path_of((103.2, 104.0, 102.0, 103.5), INSIDE)
    assert not at_target.executed
    assert settle(at_target, 2)["incomparable_reason"] == "gap_above_target"


def test_a_gap_open_at_or_below_the_invalid_price_is_not_entered():
    # Breakout: opens under the invalid price 98, then trades up through 100.
    breakout = path_of((97.5, 100.5, 97.0, 100.2), INSIDE, TARGET)
    assert not breakout.executed and breakout.first_outcome is None
    assert breakout.sessions[0].status == "not_entered"
    assert settle(breakout, 3)["incomparable_reason"] == "gap_below_invalid"
    # Pullback: opens under the invalid price 97, then trades into the zone.
    pullback = path_of((96.5, 99.5, 96.0, 99.2), levels=ZONE)
    assert not pullback.executed and pullback.sessions[0].status == "not_entered"
    assert settle(pullback, 1)["incomparable_reason"] == "gap_below_invalid"


def test_a_gap_after_the_horizon_is_reported_as_not_filled_by_then():
    path = path_of(FLAT, FLAT, (104.0, 105.0, 103.5, 104.5))
    assert settle(path, 2)["incomparable_reason"] == "not_filled_by_horizon"
    assert settle(path, 3)["incomparable_reason"] == "gap_above_target"


def expected_row(day, status, trigger, value, execution_day, price):
    return {
        "settlement_date": day,
        "final_status": status,
        "first_trigger": trigger,
        "return_or_risk": pytest.approx(value),
        "incomparable_reason": None,
        "source": "fixture-bars",
        "data_time": None,
        "execution_date": execution_day,
        "execution_price": pytest.approx(price),
        "comparable": True,
        "data_quality": "complete",
    }


def without_rules(row):
    return {key: value for key, value in row.items() if key != "tracking_rules"}


def test_a_path_filled_by_the_horizon_settles_exactly_as_before():
    days = sessions_after(PLAN_DAY, 6)
    target = path_of(FLAT, FILL, INSIDE, TARGET, STOP, INSIDE)
    assert [s.status for s in target.sessions] == [
        "not_triggered",
        "active",
        "active",
        "target_1_hit",
        "target_1_hit",
        "target_1_hit",
    ]
    assert without_rules(settle(target, 5)) == expected_row(
        days[4],
        "target_1_hit",
        "target_1_hit",
        (103.2 * SELL) / (100.0 * BUY) - 1 - COST,
        days[1],
        100.0 * BUY,
    )
    # T+3 holds at the close; the later target is still the path's first outcome.
    assert without_rules(settle(target, 3)) == expected_row(
        days[2],
        "active",
        "target_1_hit",
        101.0 / (100.0 * BUY) - 1 - COST,
        days[1],
        100.0 * BUY,
    )
    # A fill on the horizon session itself is a fill by the horizon.
    on_horizon = path_of(FLAT, FLAT, FILL)
    assert without_rules(settle(on_horizon, 3)) == expected_row(
        days[2],
        "active",
        None,
        100.2 / (100.0 * BUY) - 1 - COST,
        days[2],
        100.0 * BUY,
    )
    stop = path_of(FILL, STOP)
    assert without_rules(settle(stop, 2)) == expected_row(
        days[1],
        "invalidated",
        "invalidated",
        (98.0 * SELL) / (100.0 * BUY) - 1 - COST,
        days[0],
        100.0 * BUY,
    )
    # A gap open between the breakout and the target still fills at the open.
    gap_inside = path_of((101.0, 102.0, 100.8, 101.5), INSIDE)
    assert without_rules(settle(gap_inside, 2)) == expected_row(
        days[1],
        "active",
        None,
        101.0 / (101.0 * BUY) - 1 - COST,
        days[0],
        101.0 * BUY,
    )
    zone = path_of((102.0, 102.5, 100.5, 101.0), levels=ZONE)
    assert without_rules(settle(zone, 1)) == expected_row(
        days[0],
        "active",
        None,
        101.0 / (101.0 * BUY) - 1 - COST,
        days[0],
        101.0 * BUY,
    )


ORDINARY_PATHS = [
    (FLAT, FILL, INSIDE, TARGET, STOP, INSIDE),
    (FILL, STOP, TARGET),
    (FILL, BOTH, TARGET),
    (FLAT, FLAT, FILL),
    ((101.0, 102.0, 100.8, 101.5), INSIDE, INSIDE),
]


@pytest.mark.parametrize("ohlcs", ORDINARY_PATHS)
def test_tracking_v2_equals_v1_on_every_path_filled_by_the_horizon(ohlcs):
    days = sessions_after(PLAN_DAY, len(ohlcs))
    bars = [track_bar(d, o) for d, o in zip(days, ohlcs)]
    old = track_path(LEVELS, bars, rules="tracking_v1")
    new = track_path(LEVELS, bars, rules="tracking_v2")
    assert old.sessions == new.sessions
    first = next(s.session_no for s in new.sessions if s.execution_date)
    for horizon in range(first, len(ohlcs) + 1):
        old_row, new_row = settle(old, horizon), settle(new, horizon)
        assert (old_row["tracking_rules"], new_row["tracking_rules"]) == (
            "tracking_v1",
            "tracking_v2",
        )
        assert without_rules(old_row) == without_rules(new_row)


def test_tracking_v1_keeps_the_late_fill_and_the_gap_exit():
    days = sessions_after(PLAN_DAY, 6)
    late_bars = [track_bar(d, o) for d, o in zip(days, [*[FLAT] * 5, FILL])]
    assert settle(track_path(LEVELS, late_bars, rules="tracking_v1"), 5)["comparable"]
    assert not settle(track_path(LEVELS, late_bars), 5)["comparable"]
    gap = [track_bar(days[0], GAP_6221)]
    v1_gap = track_path(GAP_LEVELS, gap, rules="tracking_v1")
    assert v1_gap.first_outcome == "target_1_hit" and v1_gap.skip_reason is None
    assert settle(v1_gap, 1)["return_or_risk"] < 0
    with pytest.raises(ValueError):
        track_path(LEVELS, [], rules="tracking_v9")


def test_every_plan_tracking_version_names_known_rules():
    from app.domain import PLAN_TRACKING_RULES, PLAN_TRACKING_VERSION
    from app.tracking import TRACKING_RULE_VERSIONS, TRACKING_RULES

    assert PLAN_TRACKING_VERSION == "plan_tracking_v2"
    assert set(PLAN_TRACKING_RULES.values()) <= set(TRACKING_RULE_VERSIONS)
    assert PLAN_TRACKING_RULES[PLAN_TRACKING_VERSION] == TRACKING_RULES
