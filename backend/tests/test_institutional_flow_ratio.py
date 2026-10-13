"""RAM-only boundary tests for the exact institutional-flow ratio consumer.

These fixtures prove validation and arithmetic only.  They do not stand in for a
real source, the exchange trading-day calendar, or the 2026-10-05 / 2026-10-06
seven-stock acceptance, which need independently obtained real inputs.
"""

import copy
from datetime import date, timedelta
from fractions import Fraction

import pytest

from app import domain
from app.institutional_flow_ratio import (
    FORMULA_VERSION,
    PURPOSE_HOT_GROUP_RATIO,
    PURPOSE_STRATEGY_GATE,
    InstitutionalFlowRatioError,
    InstitutionalFlowRatioResult,
    compute_institutional_flow_ratio,
)

CUTOFF = date(2026, 10, 5)


def _window_dates(cutoff: date = CUTOFF, count: int = 20) -> list[date]:
    days: list[date] = []
    day = cutoff
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return list(reversed(days))


def make_payload(
    volumes: list[int] | None = None,
    flows: tuple[int, int, int] = (-1, -1, -1),
    purpose: str = PURPOSE_STRATEGY_GATE,
) -> dict:
    dates = _window_dates()
    volumes = [1000] * 20 if volumes is None else volumes
    return {
        "formula_version": FORMULA_VERSION,
        "purpose": purpose,
        "cutoff_date": CUTOFF.isoformat(),
        "flow": {
            "unit": "shares",
            "window_trading_days": 5,
            "basis": "inclusive_cutoff",
            "window_start": dates[-5].isoformat(),
            "window_end": dates[-1].isoformat(),
            "foreign_net_shares": flows[0],
            "investment_trust_net_shares": flows[1],
            "dealer_net_shares": flows[2],
            "total_net_shares": sum(flows),
        },
        "volume": {
            "unit": "shares",
            "window_trading_days": 20,
            "basis": "inclusive_cutoff",
            "daily": [{"date": d.isoformat(), "shares": v} for d, v in zip(dates, volumes)],
        },
    }


def reject(payload, code):
    with pytest.raises(InstitutionalFlowRatioError) as failure:
        compute_institutional_flow_ratio(payload)
    assert failure.value.code == code
    return failure.value


# --- positive path --------------------------------------------------------


def test_strategy_gate_divides_net_shares_by_the_twenty_day_mean_exactly():
    volumes = [1000 + 37 * index for index in range(20)]
    payload = make_payload(volumes, flows=(123456, -23456, 1000))
    result = compute_institutional_flow_ratio(payload)

    expected = Fraction(101000) / Fraction(sum(volumes), 20)
    assert isinstance(result, InstitutionalFlowRatioResult)
    assert result.ratio == expected
    assert (result.ratio_numerator, result.ratio_denominator) == (expected.numerator, expected.denominator)
    assert result.flow_net_shares == 101000
    assert result.volume_shares_sum == sum(volumes)
    assert result.cutoff_date == CUTOFF
    assert result.formula_version == FORMULA_VERSION
    assert result.gate_passed is True


def test_gate_boundary_is_exact_greater_or_equal_at_minus_three_thousandths():
    exactly = compute_institutional_flow_ratio(make_payload(flows=(-1, -1, -1)))
    below = compute_institutional_flow_ratio(make_payload(flows=(-2, -1, -1)))
    above = compute_institutional_flow_ratio(make_payload(flows=(5, -2, -3)))

    assert exactly.ratio == Fraction(-3, 1000) == exactly.threshold
    assert exactly.gate_passed is True
    assert below.ratio == Fraction(-4, 1000) and below.gate_passed is False
    assert above.ratio == 0 and above.gate_passed is True
    # The binary double for -0.003 is not -3/1000; the threshold must be exact.
    assert Fraction(-0.003) != Fraction(-3, 1000)


def test_hot_group_ratio_divides_by_the_twenty_day_sum_and_has_no_gate():
    volumes = [900 + 11 * index for index in range(20)]
    flows = (400, -150, 70)
    hot = compute_institutional_flow_ratio(make_payload(volumes, flows, PURPOSE_HOT_GROUP_RATIO))
    strategy = compute_institutional_flow_ratio(make_payload(volumes, flows))

    assert hot.ratio == Fraction(320, sum(volumes))
    assert hot.threshold is None and hot.gate_passed is None
    assert strategy.ratio == hot.ratio * 20


def test_compute_does_not_mutate_the_payload():
    payload = make_payload([1000 + index for index in range(20)])
    snapshot = copy.deepcopy(payload)
    compute_institutional_flow_ratio(payload)
    assert payload == snapshot


# --- AC4 rejections: unit / window / basis / version / purpose -----------------


def _set(path, value):
    def apply(payload):
        target = payload
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return apply


def _drop(path):
    def apply(payload):
        target = payload
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]
    return apply


def _drop_row(payload):
    del payload["volume"]["daily"][0]


def _add_row(payload):
    payload["volume"]["daily"].append({"date": "2026-10-06", "shares": 1000})


def _swap_rows(payload):
    rows = payload["volume"]["daily"]
    rows[3], rows[4] = rows[4], rows[3]


def _duplicate_date(payload):
    rows = payload["volume"]["daily"]
    rows[10]["date"] = rows[9]["date"]


UNIT_WINDOW_VERSION_CASES = [
    ("original_v1_version", _set(("formula_version",), "institutional-flow/v1-shares-per-twd-turnover"), "formula_version_mismatch"),
    ("unknown_version", _set(("formula_version",), "institutional-flow/v3"), "formula_version_mismatch"),
    ("tpex_twd_purpose", _set(("purpose",), "shares_div_TWD_as_dimensionless_strategy_gate"), "unsupported_purpose"),
    ("unknown_purpose", _set(("purpose",), "backtest"), "unsupported_purpose"),
    ("twd_denominator_upper", _set(("volume", "unit"), "TWD"), "volume_unit_not_shares"),
    ("twd_denominator_lower", _set(("volume", "unit"), "twd"), "volume_unit_not_shares"),
    ("lots_denominator", _set(("volume", "unit"), "lots"), "volume_unit_not_shares"),
    ("twd_numerator", _set(("flow", "unit"), "TWD"), "flow_unit_not_shares"),
    ("flow_window_4", _set(("flow", "window_trading_days"), 4), "flow_window_unsupported"),
    ("flow_window_20", _set(("flow", "window_trading_days"), 20), "flow_window_unsupported"),
    ("flow_window_bool", _set(("flow", "window_trading_days"), True), "flow_window_unsupported"),
    ("volume_window_19", _set(("volume", "window_trading_days"), 19), "volume_window_unsupported"),
    ("volume_window_60", _set(("volume", "window_trading_days"), 60), "volume_window_unsupported"),
    ("prior20_basis", _set(("volume", "basis"), "prior20_exclusive_cutoff"), "volume_basis_unsupported"),
    ("flow_basis_exclusive", _set(("flow", "basis"), "exclusive_cutoff"), "flow_basis_unsupported"),
]


@pytest.mark.parametrize("name,mutate,code", UNIT_WINDOW_VERSION_CASES, ids=[c[0] for c in UNIT_WINDOW_VERSION_CASES])
def test_unit_window_basis_version_and_purpose_mismatches_are_rejected(name, mutate, code):
    payload = make_payload()
    mutate(payload)
    reject(payload, code)


def test_prior20_window_shifted_one_day_is_rejected_not_reinterpreted():
    # A prior-20 window ends the day before the cutoff: its last date no longer
    # equals the cutoff, so it cannot pass as an inclusive window.
    payload = make_payload()
    dates = _window_dates(date(2026, 10, 2))
    payload["volume"]["daily"] = [{"date": d.isoformat(), "shares": 1000} for d in dates]
    reject(payload, "date_mismatch")


# --- AC4 rejections: dates ----------------------------------------------------

DATE_CASES = [
    ("flow_end_not_cutoff", _set(("flow", "window_end"), "2026-10-02"), "date_mismatch"),
    ("flow_start_not_fifth_last", _set(("flow", "window_start"), "2026-09-28"), "date_mismatch"),
    ("cutoff_not_volume_last", _set(("cutoff_date",), "2026-10-06"), "date_mismatch"),
    ("duplicate_volume_date", _duplicate_date, "volume_dates_unordered"),
    ("unordered_volume_dates", _swap_rows, "volume_dates_unordered"),
    ("short_volume_rows", _drop_row, "volume_row_count_mismatch"),
    ("long_volume_rows", _add_row, "volume_row_count_mismatch"),
    ("non_zero_padded_date", _set(("cutoff_date",), "2026-10-5"), "invalid_date"),
    ("compact_date", _set(("flow", "window_end"), "20261005"), "invalid_date"),
    ("date_object", _set(("cutoff_date",), CUTOFF), "invalid_date"),
    ("impossible_date", _set(("volume", "daily", 0, "date"), "2026-02-30"), "invalid_date"),
]


@pytest.mark.parametrize("name,mutate,code", DATE_CASES, ids=[c[0] for c in DATE_CASES])
def test_date_inconsistencies_are_rejected(name, mutate, code):
    payload = make_payload()
    mutate(payload)
    reject(payload, code)


# --- AC4 rejections: values ---------------------------------------------------

VALUE_CASES = [
    ("missing_top_key", _drop(("purpose",)), "missing_value"),
    ("missing_flow_key", _drop(("flow", "dealer_net_shares")), "missing_value"),
    ("missing_total", _drop(("flow", "total_net_shares")), "missing_value"),
    ("none_category", _set(("flow", "foreign_net_shares"), None), "missing_value"),
    ("none_volume", _set(("volume", "daily", 7, "shares"), None), "missing_value"),
    ("missing_volume_row_key", _drop(("volume", "daily", 7, "shares")), "missing_value"),
    ("unexpected_top_key", _set(("note",), "x"), "unexpected_field"),
    ("unexpected_flow_key", _set(("flow", "turnover_twd"), 1), "unexpected_field"),
    ("nan_volume", _set(("volume", "daily", 3, "shares"), float("nan")), "nonfinite_value"),
    ("inf_volume", _set(("volume", "daily", 3, "shares"), float("inf")), "nonfinite_value"),
    ("neg_inf_flow", _set(("flow", "foreign_net_shares"), float("-inf")), "nonfinite_value"),
    ("float_volume", _set(("volume", "daily", 3, "shares"), 1000.0), "non_integer_value"),
    ("float_flow", _set(("flow", "dealer_net_shares"), -1.0), "non_integer_value"),
    ("string_volume", _set(("volume", "daily", 3, "shares"), "1000"), "non_integer_value"),
    ("bool_volume", _set(("volume", "daily", 3, "shares"), True), "non_integer_value"),
    ("zero_volume_row", _set(("volume", "daily", 19, "shares"), 0), "zero_volume_row"),
    ("zero_volume_first_row", _set(("volume", "daily", 0, "shares"), 0), "zero_volume_row"),
    ("negative_volume_row", _set(("volume", "daily", 5, "shares"), -1000), "negative_volume_row"),
    ("huge_volume", _set(("volume", "daily", 5, "shares"), 2**63), "value_out_of_range"),
    ("total_not_sum", _set(("flow", "total_net_shares"), -2), "flow_total_mismatch"),
]


@pytest.mark.parametrize("name,mutate,code", VALUE_CASES, ids=[c[0] for c in VALUE_CASES])
def test_missing_nonfinite_non_integer_and_zero_or_negative_volume_are_rejected(name, mutate, code):
    payload = make_payload()
    mutate(payload)
    reject(payload, code)


@pytest.mark.parametrize("payload", [None, [], "payload", 3, ()])
def test_non_mapping_payload_is_rejected(payload):
    reject(payload, "invalid_input_shape")


def test_volume_rows_must_be_a_sequence_of_mappings():
    payload = make_payload()
    payload["volume"]["daily"] = {"2026-10-05": 1000}
    reject(payload, "invalid_input_shape")
    payload = make_payload()
    payload["volume"]["daily"][4] = 1000
    reject(payload, "invalid_input_shape")


def test_rejection_reports_the_failing_field():
    payload = make_payload()
    payload["volume"]["daily"][11]["shares"] = 0
    assert reject(payload, "zero_volume_row").where == "volume.daily[11].shares"


# --- config / identity binding -------------------------------------------------


def _institutional_flow_config(name="breakout_v1"):
    return domain.STRATEGY_CONFIGS[name]["confirmations"]["institutional_flow"]


def test_domain_config_declares_the_shares_over_shares_formula_with_unchanged_threshold():
    for name in ("breakout_v1", "pullback_v1"):
        config = _institutional_flow_config(name)
        assert config["formula_version"] == FORMULA_VERSION
        assert config["normalizer"] == "average_daily_volume_20d"
        assert (config["flow_unit"], config["normalizer_unit"]) == ("shares", "shares")
        assert (config["flow_window_trading_days"], config["normalizer_window_trading_days"]) == (5, 20)
        assert config["normalizer_window_basis"] == "inclusive_signal_day"
        assert config["minimum_net_flow_to_turnover_ratio"] == -0.003
        assert config["operator"] == "gte"
    hot = domain.HOT_GROUP_CONFIG["components"]["institutional_flow"]["formula"]
    assert hot["formula_version"] == FORMULA_VERSION
    assert hot["metric"] == "sum(foreign_buy + trust_buy + dealer_buy, 5d) / sum(volume, 20d)"
    assert (hot["flow_unit"], hot["denominator_unit"]) == ("shares", "shares")
    assert (hot["flow_window_trading_days"], hot["denominator_window_trading_days"]) == (5, 20)
    assert hot["denominator_window_basis"] == "inclusive_signal_day"


def test_original_twd_formula_is_retained_as_a_distinct_identity_and_not_current():
    formulas = domain.INSTITUTIONAL_FLOW_FORMULAS
    original = formulas[domain.INSTITUTIONAL_FLOW_FORMULA_V1]
    current = formulas[domain.INSTITUTIONAL_FLOW_FORMULA_V2]

    assert domain.INSTITUTIONAL_FLOW_FORMULA_V1 != domain.INSTITUTIONAL_FLOW_FORMULA_V2
    assert FORMULA_VERSION == domain.INSTITUTIONAL_FLOW_FORMULA_V2
    assert original["strategy_normalizer"] == "average_daily_turnover_20d"
    assert original["hot_group_normalizer"] == "sum_turnover_20d"
    assert (original["numerator_unit"], original["denominator_unit"]) == ("shares", "twd")
    assert original["dimensionless"] is False
    assert original["status"] == "original_canonical_retained"
    assert current["strategy_normalizer"] == _institutional_flow_config()["normalizer"]
    assert (current["numerator_unit"], current["denominator_unit"]) == ("shares", "shares")
    assert current["dimensionless"] is True


def test_strategy_gate_rejects_a_drifted_or_inconsistent_domain_config(monkeypatch):
    config = _institutional_flow_config()
    monkeypatch.setitem(config, "normalizer", "average_daily_turnover_20d")
    reject(make_payload(), "config_binding_mismatch")
    # The hot-group variant has no gate and does not consult the strategy config.
    assert compute_institutional_flow_ratio(make_payload(purpose=PURPOSE_HOT_GROUP_RATIO)).gate_passed is None


def test_strategy_gate_rejects_a_changed_threshold_type_and_disagreeing_strategies(monkeypatch):
    config = _institutional_flow_config()
    monkeypatch.setitem(config, "minimum_net_flow_to_turnover_ratio", "-0.003")
    reject(make_payload(), "config_binding_mismatch")
    monkeypatch.setitem(config, "minimum_net_flow_to_turnover_ratio", -0.003)
    pullback = domain.STRATEGY_CONFIGS["pullback_v1"]
    monkeypatch.setitem(pullback, "confirmations", {
        **pullback["confirmations"],
        "institutional_flow": {**config, "minimum_net_flow_to_turnover_ratio": -0.004},
    })
    reject(make_payload(), "config_binding_mismatch")
