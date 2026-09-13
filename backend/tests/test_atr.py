from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.atr import (
    CorporateActionEvidence,
    OHLCBar,
    calculate_atr14,
)


UTC = timezone.utc
DEFAULT_DECISION_AT = datetime(2026, 12, 31, 8, 0, tzinfo=UTC)


def _bar(
    day: date,
    *,
    high: float = 105.0,
    low: float = 100.0,
    close: float = 102.0,
    open_: float | None = None,
    **kwargs,
) -> OHLCBar:
    price_basis = kwargs.pop("price_basis", "raw_v1")
    if "data_available_at" not in kwargs:
        kwargs["data_available_at"] = datetime.combine(day, time(8, 0), tzinfo=UTC)
    return OHLCBar(
        trading_date=day,
        open=close if open_ is None else open_,
        high=high,
        low=low,
        close=close,
        price_basis=price_basis,
        **kwargs,
    )


def _bars_for_trs(trs: list[float], *, start: date = date(2026, 1, 2), **kwargs) -> list[OHLCBar]:
    bars: list[OHLCBar] = []
    for index, true_range in enumerate(trs):
        trading_date = start + timedelta(days=index)
        bars.append(
            _bar(
                trading_date,
                high=100.0 + true_range,
                low=100.0,
                close=100.0,
                **kwargs,
            )
        )
    return bars


def _reference_atr(trs: list[float], period: int = 14) -> list[float | None]:
    """Independent reference implementation used only by the tests."""

    output: list[float | None] = []
    previous: float | None = None
    for index, true_range in enumerate(trs):
        if index + 1 < period:
            output.append(None)
        elif index + 1 == period:
            previous = sum(trs[:period]) / period
            output.append(previous)
        else:
            assert previous is not None
            previous = (previous * (period - 1) + true_range) / period
            output.append(previous)
    return output


def _calculate(bars, **kwargs):
    kwargs.setdefault("expected_sessions", [bar.trading_date for bar in bars])
    kwargs.setdefault("decision_at", DEFAULT_DECISION_AT)
    kwargs.setdefault("corporate_action_coverage", "complete")
    kwargs.setdefault("corporate_action_source_ref", "fixture://corporate-action-catalog")
    kwargs.setdefault("corporate_action_available_at", datetime(2026, 1, 1, 8, tzinfo=UTC))
    if kwargs.get("previous_close") is not None:
        kwargs.setdefault("previous_close_basis", "raw_v1")
        kwargs.setdefault("previous_close_source_ref", "fixture://previous-close")
        kwargs.setdefault("previous_close_available_at", datetime(2026, 1, 1, 8, tzinfo=UTC))
    return calculate_atr14(
        bars,
        price_basis="raw_v1",
        input_snapshot_ref="fixture://atr-test",
        **kwargs,
    )


def test_true_range_uses_gap_components_for_up_down_and_non_gap() -> None:
    up = _calculate(
        [_bar(date(2026, 1, 2), high=110, low=108, close=109)],
        previous_close=100,
    ).observations[0]
    down = _calculate(
        [_bar(date(2026, 1, 2), high=95, low=90, close=92)],
        previous_close=100,
    ).observations[0]
    no_gap = _calculate(
        [_bar(date(2026, 1, 2), high=105, low=100, close=102)],
        previous_close=102,
    ).observations[0]

    assert up.true_range == 10
    assert down.true_range == 10
    assert no_gap.true_range == 5


def test_warmup_seed_and_recurrence_match_independent_reference_not_rolling_sma() -> None:
    true_ranges = list(range(1, 17))
    artifact = _calculate(_bars_for_trs(true_ranges), true_sequence_start=True)
    actual = [observation.atr for observation in artifact.observations]
    expected = _reference_atr(true_ranges)

    for actual_value, expected_value in zip(actual, expected):
        if expected_value is None:
            assert actual_value is None
        else:
            assert actual_value == pytest.approx(expected_value)
    assert artifact.observations[12].atr is None
    assert artifact.observations[12].null_reason == "warmup_incomplete"
    assert artifact.observations[13].atr == pytest.approx(15 / 2)
    assert artifact.observations[14].atr == pytest.approx(225 / 28)
    assert artifact.observations[15].atr == pytest.approx(3373 / 392)
    assert artifact.observations[15].atr != pytest.approx(9.5)


def test_partial_window_requires_previous_close_unless_sequence_start_is_proven() -> None:
    bar = _bar(date(2026, 1, 2), high=110, low=108, close=109)
    without_previous = _calculate([bar]).observations[0]
    with_previous = _calculate([bar], previous_close=100).observations[0]
    proven_start = _calculate([bar], true_sequence_start=True).observations[0]
    row_previous = _calculate(
        [
            _bar(
                date(2026, 1, 2),
                high=110,
                low=108,
                close=109,
                previous_close=100,
                previous_close_basis="raw_v1",
                previous_close_source_ref="fixture://previous-close",
                previous_close_available_at=datetime(2026, 1, 1, 8, tzinfo=UTC),
            )
        ]
    ).observations[0]
    invalid_row_previous = _calculate(
        [
            _bar(
                date(2026, 1, 2),
                high=110,
                low=108,
                close=109,
                previous_close=100,
                previous_close_basis="mystery_basis",
                previous_close_source_ref="fixture://previous-close",
                previous_close_available_at=datetime(2026, 1, 1, 8, tzinfo=UTC),
            )
        ],
        true_sequence_start=True,
    ).observations[0]

    assert without_previous.true_range is None
    assert without_previous.null_reason == "missing_previous_close"
    assert with_previous.true_range == 10
    assert proven_start.true_range == 2
    assert row_previous.true_range == 10
    assert invalid_row_previous.true_range is None
    assert invalid_row_previous.null_reason == "inconsistent_previous_close_basis"


def test_missing_expected_session_is_explicit_and_valid_close_anchors_recovery() -> None:
    sessions = [date(2026, 1, 2) + timedelta(days=index) for index in range(36)]
    bars = _bars_for_trs([1] * 20, start=sessions[0], price_basis="raw_v1")
    bars = [bar for bar in bars if bar.trading_date != sessions[20]]
    bars.extend(
        _bars_for_trs(
            [6] * 15,
            start=sessions[21],
            price_basis="raw_v1",
        )
    )
    artifact = _calculate(bars, expected_sessions=sessions, true_sequence_start=True)
    by_date = {observation.trading_date: observation for observation in artifact.observations}

    assert by_date[sessions[20]].null_reason == "missing_expected_session"
    assert by_date[sessions[20]].bar_present is False
    # S22 has a valid OHLC close but no legal prior close after the gap.  Its
    # close is retained as the anchor so S23 can produce the first TR.
    assert by_date[sessions[21]].true_range is None
    assert by_date[sessions[21]].null_reason == "missing_previous_close"
    assert by_date[sessions[22]].true_range == 6
    assert by_date[sessions[35]].atr == pytest.approx(6)


def test_confirmed_suspension_preserves_state_without_zero_range_or_reset() -> None:
    sessions = [date(2026, 1, 2) + timedelta(days=index) for index in range(22)]
    bars = _bars_for_trs([4] * 20, start=sessions[0], price_basis="raw_v1")
    bars.append(
        OHLCBar(
            trading_date=sessions[20],
            open=None,
            high=None,
            low=None,
            close=None,
            price_basis="raw_v1",
            is_suspended=True,
        )
    )
    bars.append(_bar(sessions[21], high=106, low=100, close=100, price_basis="raw_v1"))
    artifact = _calculate(bars, expected_sessions=sessions, true_sequence_start=True)

    suspension = artifact.observations[20]
    resumed = artifact.observations[21]
    assert artifact.observations[19].atr == pytest.approx(4)
    assert suspension.is_suspended is True
    assert suspension.true_range is None and suspension.atr is None
    assert suspension.valid_tr_count == 14
    assert resumed.true_range == 6
    assert resumed.atr == pytest.approx(29 / 7)


def test_leading_confirmed_suspension_does_not_make_next_bar_an_ipo_start() -> None:
    sessions = [date(2026, 1, 2), date(2026, 1, 5)]
    bars = [
        OHLCBar(
            trading_date=sessions[0],
            open=None,
            high=None,
            low=None,
            close=None,
            price_basis="raw_v1",
            is_suspended=True,
            data_available_at=datetime(2026, 1, 2, 8, tzinfo=UTC),
        ),
        _bar(sessions[1], high=110, low=108, close=109),
    ]
    artifact = _calculate(bars, expected_sessions=sessions)

    assert artifact.observations[0].null_reason == "session_suspended"
    assert artifact.observations[1].true_range is None
    assert artifact.observations[1].null_reason == "missing_previous_close"


def test_external_previous_close_without_same_basis_provenance_is_not_used() -> None:
    artifact = calculate_atr14(
        [_bar(date(2026, 1, 2), price_basis="raw_v1")],
        price_basis="raw_v1",
        input_snapshot_ref="fixture://missing-prev-evidence",
        expected_sessions=[date(2026, 1, 2)],
        decision_at=DEFAULT_DECISION_AT,
        corporate_action_coverage="complete",
        corporate_action_source_ref="fixture://corporate-action-catalog",
        corporate_action_available_at=datetime(2026, 1, 1, 8, tzinfo=UTC),
        previous_close=100,
        previous_close_basis="raw_v1",
    )

    assert artifact.observations[0].true_range is None
    assert artifact.observations[0].null_reason == "previous_close_provenance_missing"


def test_missing_global_as_of_session_or_action_coverage_evidence_is_rejected() -> None:
    bar = _bar(date(2026, 1, 2))
    common = {
        "price_basis": "raw_v1",
        "input_snapshot_ref": "fixture://required-evidence",
    }

    with pytest.raises(ValueError):
        calculate_atr14([bar], **common, decision_at=DEFAULT_DECISION_AT)
    with pytest.raises(ValueError):
        calculate_atr14(
            [bar],
            **common,
            expected_sessions=[bar.trading_date],
        )
    with pytest.raises(ValueError):
        calculate_atr14(
            [bar],
            **common,
            expected_sessions=[bar.trading_date],
            decision_at=DEFAULT_DECISION_AT,
        )


@pytest.mark.parametrize(
    "bad_bar",
    [
        _bar(date(2026, 1, 7), high=float("nan")),
        _bar(date(2026, 1, 7), high=float("inf")),
        _bar(date(2026, 1, 7), low=0),
        _bar(date(2026, 1, 7), high=99, low=100),
        _bar(date(2026, 1, 7), open_=106),
        OHLCBar(
            date(2026, 1, 7),
            open=True,
            high=105,
            low=100,
            close=102,
            price_basis="raw_v1",
            data_available_at=datetime(2026, 1, 7, 8, tzinfo=UTC),
        ),
    ],
)
def test_invalid_ohlc_is_fail_closed_and_resets_warmup(bad_bar: OHLCBar) -> None:
    artifact = _calculate(
        _bars_for_trs([1] * 14)[:5]
        + [bad_bar]
        + _bars_for_trs([1] * 2, start=date(2026, 1, 8)),
        true_sequence_start=True,
    )

    bad = artifact.observations[5]
    assert bad.true_range is None and bad.atr is None
    assert bad.null_reason == "invalid_ohlc"
    assert artifact.observations[6].atr is None
    assert artifact.observations[6].null_reason == "missing_previous_close"


def test_same_basis_adjusted_prices_do_not_create_split_or_dividend_gap() -> None:
    decision_at = datetime(2026, 1, 7, 8, 0, tzinfo=UTC)
    bars = [
        _bar(
            date(2026, 1, 2),
            high=102,
            low=98,
            close=100,
            price_basis="adjusted_v1",
            data_available_at=datetime(2026, 1, 2, 8, tzinfo=UTC),
        ),
        _bar(
            date(2026, 1, 5),
            high=102,
            low=98,
            close=100,
            price_basis="adjusted_v1",
            data_available_at=datetime(2026, 1, 5, 7, tzinfo=UTC),
        ),
    ]
    action = CorporateActionEvidence(
        action_date=date(2026, 1, 5),
        action_type="split",
        price_basis="adjusted_v1",
        coverage="complete",
        source_ref="fixture://corporate-action/1",
        available_at=datetime(2026, 1, 5, 7, 30, tzinfo=UTC),
    )
    artifact = calculate_atr14(
        bars,
        price_basis="adjusted_v1",
        input_snapshot_ref="fixture://adjusted-bars",
        expected_sessions=[bar.trading_date for bar in bars],
        decision_at=decision_at,
        corporate_actions=[action],
        corporate_action_coverage="complete",
        corporate_action_source_ref="fixture://corporate-action-catalog",
        corporate_action_available_at=datetime(2026, 1, 2, 9, tzinfo=UTC),
        previous_close=100,
        previous_close_basis="adjusted_v1",
        previous_close_source_ref="fixture://previous-close",
        previous_close_available_at=datetime(2026, 1, 2, 9, tzinfo=UTC),
    )

    assert [observation.true_range for observation in artifact.observations] == [4, 4]
    assert artifact.corporate_actions[0]["validation_issue"] is None


def test_incomplete_or_future_corporate_action_is_excluded_at_decision() -> None:
    decision_at = datetime(2026, 1, 7, 8, 0, tzinfo=UTC)
    bars = [
        _bar(
            date(2026, 1, 2),
            price_basis="adjusted_v1",
            data_available_at=datetime(2026, 1, 2, 8, tzinfo=UTC),
        ),
        _bar(
            date(2026, 1, 5),
            price_basis="adjusted_v1",
            data_available_at=datetime(2026, 1, 5, 7, tzinfo=UTC),
        ),
        _bar(
            date(2026, 1, 6),
            price_basis="adjusted_v1",
            data_available_at=datetime(2026, 1, 6, 7, tzinfo=UTC),
        ),
    ]
    action = {
        "action_date": date(2026, 1, 5),
        "action_type": "ex_dividend",
        "price_basis": "adjusted_v1",
        "coverage": "partial",
        "source_ref": "fixture://corporate-action/2",
        "available_at": datetime(2026, 1, 6, 7, tzinfo=UTC),
    }
    artifact = calculate_atr14(
        bars,
        price_basis="adjusted_v1",
        input_snapshot_ref="fixture://future-action",
        expected_sessions=[bar.trading_date for bar in bars],
        decision_at=decision_at,
        corporate_actions=[action],
        corporate_action_coverage="complete",
        corporate_action_source_ref="fixture://corporate-action-catalog",
        corporate_action_available_at=datetime(2026, 1, 2, 9, tzinfo=UTC),
        previous_close=100,
        previous_close_basis="adjusted_v1",
        previous_close_source_ref="fixture://previous-close",
        previous_close_available_at=datetime(2026, 1, 2, 9, tzinfo=UTC),
    )

    assert all(observation.true_range is None for observation in artifact.observations)
    assert [observation.null_reason for observation in artifact.observations] == [
        "corporate_action_coverage_incomplete",
        "corporate_action_coverage_incomplete",
        "corporate_action_coverage_incomplete",
    ]
    assert artifact.corporate_actions[0]["validation_issue"] == "corporate_action_coverage_incomplete"

    future_only = CorporateActionEvidence(
        action_date=date(2026, 1, 5),
        action_type="split",
        price_basis="adjusted_v1",
        coverage="complete",
        source_ref="fixture://corporate-action/3",
        available_at=datetime(2026, 1, 8, 7, tzinfo=UTC),
    )
    future_artifact = calculate_atr14(
        bars,
        price_basis="adjusted_v1",
        input_snapshot_ref="fixture://future-action-only",
        expected_sessions=[bar.trading_date for bar in bars],
        decision_at=decision_at,
        corporate_actions=[future_only],
        corporate_action_coverage="complete",
        corporate_action_source_ref="fixture://corporate-action-catalog",
        corporate_action_available_at=datetime(2026, 1, 2, 9, tzinfo=UTC),
        previous_close=100,
        previous_close_basis="adjusted_v1",
        previous_close_source_ref="fixture://previous-close",
        previous_close_available_at=datetime(2026, 1, 2, 9, tzinfo=UTC),
    )
    assert future_artifact.observations[1].null_reason == "corporate_action_not_available_at_decision"


def test_late_action_invalidates_pre_event_seed_but_later_as_of_can_recompute() -> None:
    sessions = [date(2026, 1, 2) + timedelta(days=index) for index in range(15)]
    bars = [
        _bar(
            trading_date,
            high=105,
            low=100,
            close=102,
            price_basis="adjusted_v1",
        )
        for trading_date in sessions
    ]
    action = CorporateActionEvidence(
        action_date=sessions[-1],
        action_type="split",
        price_basis="adjusted_v1",
        coverage="complete",
        source_ref="fixture://late-action",
        available_at=datetime(2026, 1, 20, 8, tzinfo=UTC),
    )
    common = {
        "price_basis": "adjusted_v1",
        "input_snapshot_ref": "fixture://late-action-basis",
        "expected_sessions": sessions,
        "corporate_actions": [action],
        "corporate_action_coverage": "complete",
        "corporate_action_source_ref": "fixture://corporate-action-catalog",
        "corporate_action_available_at": datetime(2026, 1, 1, 8, tzinfo=UTC),
        "previous_close": 100,
        "previous_close_basis": "adjusted_v1",
        "previous_close_source_ref": "fixture://previous-close",
        "previous_close_available_at": datetime(2026, 1, 2, 8, tzinfo=UTC),
    }
    early = calculate_atr14(
        bars,
        **common,
        decision_at=datetime(2026, 1, 17, 8, tzinfo=UTC),
    )
    early_snapshot = early.to_dict()
    later = calculate_atr14(
        bars,
        **common,
        decision_at=datetime(2026, 1, 21, 8, tzinfo=UTC),
    )

    assert all(observation.atr is None for observation in early.observations)
    assert all(observation.null_reason == "corporate_action_not_available_at_decision" for observation in early.observations)
    assert later.observations[-1].atr == pytest.approx(5)
    assert early.to_dict() == early_snapshot


def test_suspended_price_bar_conflict_fails_closed_instead_of_silently_ignoring_prices() -> None:
    sessions = [date(2026, 1, 2) + timedelta(days=index) for index in range(4)]
    bars = _bars_for_trs([4, 4], start=sessions[0])
    bars.append(
        _bar(
            sessions[2],
            high=106,
            low=100,
            close=102,
            is_suspended=True,
        )
    )
    bars.append(_bar(sessions[3], high=105, low=100, close=102))
    artifact = _calculate(bars, expected_sessions=sessions, true_sequence_start=True)

    assert artifact.observations[2].null_reason == "suspension_price_conflict"
    assert artifact.observations[2].true_range is None
    assert artifact.observations[3].null_reason == "missing_previous_close"


def test_missing_suspended_session_without_a_bar_preserves_previous_state() -> None:
    sessions = [date(2026, 1, 2) + timedelta(days=index) for index in range(3)]
    bars = _bars_for_trs([4, 6], start=sessions[0])
    bars.pop(1)
    bars.append(_bar(sessions[2], high=106, low=100, close=100))
    artifact = _calculate(
        bars,
        expected_sessions=sessions,
        suspended_sessions=[sessions[1]],
        true_sequence_start=True,
    )

    assert artifact.observations[1].null_reason == "session_suspended"
    assert artifact.observations[2].true_range == 6


def test_basis_mismatch_unknown_basis_and_future_bar_fail_closed() -> None:
    mismatch = _calculate(
        [_bar(date(2026, 1, 2), price_basis="adjusted_v1")],
        previous_close=100,
    ).observations[0]
    unknown = calculate_atr14(
        [_bar(date(2026, 1, 2), price_basis="mystery_basis")],
        price_basis="mystery_basis",
        input_snapshot_ref="fixture://unknown-basis",
        expected_sessions=[date(2026, 1, 2)],
        decision_at=DEFAULT_DECISION_AT,
        corporate_action_coverage="complete",
        corporate_action_source_ref="fixture://corporate-action-catalog",
        corporate_action_available_at=datetime(2026, 1, 1, 8, tzinfo=UTC),
        previous_close=100,
        previous_close_basis="mystery_basis",
        previous_close_source_ref="fixture://previous-close",
        previous_close_available_at=datetime(2026, 1, 1, 8, tzinfo=UTC),
    ).observations[0]
    missing = _calculate(
        [
            OHLCBar(
                trading_date=date(2026, 1, 2),
                open=102,
                high=105,
                low=100,
                close=102,
                data_available_at=datetime(2026, 1, 2, 8, tzinfo=UTC),
            )
        ],
        previous_close=100,
    ).observations[0]
    future = _calculate(
        [
            _bar(
                date(2026, 1, 2),
                data_available_at=datetime(2026, 1, 6, 8, tzinfo=UTC),
            )
        ],
        decision_at=datetime(2026, 1, 5, 8, tzinfo=UTC),
        previous_close=100,
    ).observations[0]

    assert mismatch.null_reason == "inconsistent_price_basis"
    assert unknown.null_reason == "unknown_price_basis"
    assert missing.null_reason == "unknown_price_basis"
    assert future.null_reason == "data_not_available_at_decision"


def test_bar_after_decision_date_is_not_made_point_in_time_valid_by_old_availability() -> None:
    artifact = _calculate(
        [
            _bar(
                date(2026, 1, 2),
                data_available_at=datetime(2026, 1, 1, 8, tzinfo=UTC),
            )
        ],
        decision_at=datetime(2026, 1, 1, 8, tzinfo=UTC),
        previous_close=100,
    )

    assert artifact.observations[0].true_range is None
    assert artifact.observations[0].null_reason == "bar_after_decision_date"


def test_large_finite_prices_seed_a_finite_atr_without_mean_overflow() -> None:
    sessions = [date(2026, 1, 2) + timedelta(days=index) for index in range(14)]
    bars = [
        _bar(
            trading_date,
            high=1e308,
            low=1.0,
            open_=100.0,
            close=100.0,
        )
        for trading_date in sessions
    ]
    artifact = _calculate(bars, expected_sessions=sessions, true_sequence_start=True)
    seed = artifact.observations[-1].atr

    assert seed is not None
    assert seed == pytest.approx(1e308)
    json.loads(artifact.to_json())


@pytest.mark.parametrize(
    "call",
    [
        lambda: _calculate(
            [_bar(date(2026, 1, 2), data_available_at=datetime(2026, 1, 2, 8))]
        ),
        lambda: _calculate(
            [_bar(date(2026, 1, 2))],
            decision_at=datetime(2026, 1, 5, 8),
        ),
        lambda: _calculate(
            [_bar(date(2026, 1, 2))],
            expected_sessions=[date(2026, 1, 3), date(2026, 1, 2)],
        ),
        lambda: _calculate(
            [_bar(date(2026, 1, 3), previous_close=100)],
            expected_sessions=[date(2026, 1, 2)],
        ),
    ],
)
def test_naive_timestamps_and_unpairable_or_unsorted_sessions_are_rejected(call) -> None:
    with pytest.raises(ValueError):
        call()


def test_duplicate_and_out_of_order_bar_dates_are_rejected_without_silent_reorder() -> None:
    first = _bar(date(2026, 1, 2))
    duplicate = _bar(date(2026, 1, 2))
    later = _bar(date(2026, 1, 3))

    with pytest.raises(ValueError):
        _calculate([first, duplicate])
    with pytest.raises(ValueError):
        _calculate([later, first])


def test_artifact_is_versioned_and_json_serializable() -> None:
    artifact = _calculate(
        _bars_for_trs([1, 2], price_basis="raw_v1"),
        true_sequence_start=True,
    )
    encoded = artifact.to_json()
    decoded = json.loads(encoded)

    assert decoded == artifact.to_dict()
    assert decoded["feature_version"] == "technical_v2_atr14_wilder"
    assert decoded["algorithm"] == "wilder"
    assert decoded["period"] == 14
    assert decoded["input_snapshot_ref"] == "fixture://atr-test"
    assert decoded["price_basis"] == "raw_v1"
    assert decoded["observations"][0]["tr"] == 1
    assert decoded["observations"][0]["atr"] is None
