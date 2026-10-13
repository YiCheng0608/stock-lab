"""Exact institutional-flow ratio consumer for the ``institutional-flow/v2`` formula.

The ratio is the five-trading-day net institutional flow in shares (foreign
investors excluding foreign dealers, investment trust, and dealers' own plus
hedging accounts) divided by trading volume in shares over the twenty trading
days ending on, and including, the cutoff day.  The strategy gate divides by
the twenty-day *mean* and applies ``ratio >= -0.003``; the hot-group variant
divides by the twenty-day *sum* and has no gate.

This module is pure: no I/O, database, network, clock, or floating point.  The
result is an exact ``fractions.Fraction`` built from integer inputs, and the
gate comparison is exact.  Every unit, window, basis, date, or version mismatch
is rejected with a stable ``code``; nothing is converted, defaulted, or filled
with zero.  The consumer can only check the internal consistency of the dates
it is given; that they are the complete exchange trading days is evidence the
caller supplies.

Input payload (all keys required, no extras)::

    {
      "formula_version": "institutional-flow/v2-shares-per-share-volume",
      "purpose": "strategy_gate" | "hot_group_ratio",
      "cutoff_date": "YYYY-MM-DD",
      "flow": {
        "unit": "shares", "window_trading_days": 5, "basis": "inclusive_cutoff",
        "window_start": "YYYY-MM-DD", "window_end": "YYYY-MM-DD",
        "foreign_net_shares": int, "investment_trust_net_shares": int,
        "dealer_net_shares": int, "total_net_shares": int,
      },
      "volume": {
        "unit": "shares", "window_trading_days": 20, "basis": "inclusive_cutoff",
        "daily": [{"date": "YYYY-MM-DD", "shares": int}, ...],  # 20 rows, ascending
      },
    }
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
import math
from typing import Any

from .domain import (
    INSTITUTIONAL_FLOW_FORMULA_VERSION,
    STRATEGY_CONFIGS,
)

FORMULA_VERSION = INSTITUTIONAL_FLOW_FORMULA_VERSION
PURPOSE_STRATEGY_GATE = "strategy_gate"
PURPOSE_HOT_GROUP_RATIO = "hot_group_ratio"
PURPOSES = frozenset({PURPOSE_STRATEGY_GATE, PURPOSE_HOT_GROUP_RATIO})
UNIT_SHARES = "shares"
BASIS_INCLUSIVE_CUTOFF = "inclusive_cutoff"
FLOW_WINDOW_TRADING_DAYS = 5
VOLUME_WINDOW_TRADING_DAYS = 20
INT64_MAX = 2**63 - 1

_TOP_KEYS = frozenset({"formula_version", "purpose", "cutoff_date", "flow", "volume"})
_FLOW_KEYS = frozenset({
    "unit", "window_trading_days", "basis", "window_start", "window_end",
    "foreign_net_shares", "investment_trust_net_shares", "dealer_net_shares", "total_net_shares",
})
_VOLUME_KEYS = frozenset({"unit", "window_trading_days", "basis", "daily"})
_ROW_KEYS = frozenset({"date", "shares"})
_CATEGORY_KEYS = ("foreign_net_shares", "investment_trust_net_shares", "dealer_net_shares")


class InstitutionalFlowRatioError(ValueError):
    """Rejected input or config; ``code`` is a stable reason, ``where`` the field."""

    def __init__(self, code: str, where: str = ""):
        self.code = code
        self.where = where
        super().__init__(f"{code} ({where})" if where else code)


@dataclass(frozen=True)
class InstitutionalFlowRatioResult:
    formula_version: str
    purpose: str
    cutoff_date: date
    flow_net_shares: int
    volume_shares_sum: int
    ratio: Fraction
    threshold: Fraction | None
    gate_passed: bool | None

    @property
    def ratio_numerator(self) -> int:
        return self.ratio.numerator

    @property
    def ratio_denominator(self) -> int:
        return self.ratio.denominator


def _fail(code: str, where: str = "") -> InstitutionalFlowRatioError:
    return InstitutionalFlowRatioError(code, where)


def _mapping(value: Any, keys: frozenset[str], where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _fail("invalid_input_shape", where)
    missing = sorted(key for key in keys if key not in value or value[key] is None)
    if missing:
        raise _fail("missing_value", f"{where}.{missing[0]}" if where else missing[0])
    extra = sorted(str(key) for key in value if key not in keys)
    if extra:
        raise _fail("unexpected_field", f"{where}.{extra[0]}" if where else extra[0])
    return value


def _integer(value: Any, where: str) -> int:
    if value is None:
        raise _fail("missing_value", where)
    if isinstance(value, float) and not math.isfinite(value):
        raise _fail("nonfinite_value", where)
    # Floats (even integral ones), strings, bools, and Decimals are never
    # converted: share counts must arrive as exact integers.
    if type(value) is not int:
        raise _fail("non_integer_value", where)
    if not -INT64_MAX - 1 <= value <= INT64_MAX:
        raise _fail("value_out_of_range", where)
    return value


def _iso_date(value: Any, where: str) -> date:
    if not isinstance(value, str):
        raise _fail("invalid_date", where)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise _fail("invalid_date", where) from None
    if parsed.isoformat() != value:
        raise _fail("invalid_date", where)
    return parsed


def _gate_threshold() -> Fraction:
    """Return the exact strategy threshold, bound to the domain config."""

    configs = [STRATEGY_CONFIGS[name]["confirmations"]["institutional_flow"] for name in ("breakout_v1", "pullback_v1")]
    config = configs[0]
    if configs[0] != configs[1]:
        raise _fail("config_binding_mismatch", "strategy_configs_disagree")
    if (
        config.get("formula_version") != FORMULA_VERSION
        or config.get("normalizer") != "average_daily_volume_20d"
        or config.get("flow_unit") != UNIT_SHARES
        or config.get("normalizer_unit") != UNIT_SHARES
        or config.get("flow_window_trading_days") != FLOW_WINDOW_TRADING_DAYS
        or config.get("normalizer_window_trading_days") != VOLUME_WINDOW_TRADING_DAYS
        or config.get("normalizer_window_basis") != "inclusive_signal_day"
        or config.get("operator") != "gte"
    ):
        raise _fail("config_binding_mismatch", "institutional_flow")
    raw = config.get("minimum_net_flow_to_turnover_ratio")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
        raise _fail("config_binding_mismatch", "minimum_net_flow_to_turnover_ratio")
    # ``str`` of a float is its shortest round-trip decimal, so -0.003 becomes
    # exactly -3/1000 instead of the nearest binary double.
    return Fraction(str(raw))


def compute_institutional_flow_ratio(payload: Mapping[str, Any]) -> InstitutionalFlowRatioResult:
    """Validate ``payload`` and return the exact ratio and, for the strategy, the gate."""

    top = _mapping(payload, _TOP_KEYS, "")
    if top["formula_version"] != FORMULA_VERSION:
        raise _fail("formula_version_mismatch", "formula_version")
    purpose = top["purpose"]
    if not isinstance(purpose, str) or purpose not in PURPOSES:
        raise _fail("unsupported_purpose", "purpose")
    cutoff = _iso_date(top["cutoff_date"], "cutoff_date")

    flow = _mapping(top["flow"], _FLOW_KEYS, "flow")
    volume = _mapping(top["volume"], _VOLUME_KEYS, "volume")

    if flow["unit"] != UNIT_SHARES:
        raise _fail("flow_unit_not_shares", "flow.unit")
    if volume["unit"] != UNIT_SHARES:
        raise _fail("volume_unit_not_shares", "volume.unit")
    if type(flow["window_trading_days"]) is not int or flow["window_trading_days"] != FLOW_WINDOW_TRADING_DAYS:
        raise _fail("flow_window_unsupported", "flow.window_trading_days")
    if type(volume["window_trading_days"]) is not int or volume["window_trading_days"] != VOLUME_WINDOW_TRADING_DAYS:
        raise _fail("volume_window_unsupported", "volume.window_trading_days")
    if flow["basis"] != BASIS_INCLUSIVE_CUTOFF:
        raise _fail("flow_basis_unsupported", "flow.basis")
    if volume["basis"] != BASIS_INCLUSIVE_CUTOFF:
        raise _fail("volume_basis_unsupported", "volume.basis")

    rows = volume["daily"]
    if not isinstance(rows, (list, tuple)):
        raise _fail("invalid_input_shape", "volume.daily")
    if len(rows) != VOLUME_WINDOW_TRADING_DAYS:
        raise _fail("volume_row_count_mismatch", "volume.daily")
    volume_dates: list[date] = []
    volumes: list[int] = []
    for index, row in enumerate(rows):
        where = f"volume.daily[{index}]"
        row = _mapping(row, _ROW_KEYS, where)
        volume_dates.append(_iso_date(row["date"], f"{where}.date"))
        shares = _integer(row["shares"], f"{where}.shares")
        if shares == 0:
            raise _fail("zero_volume_row", f"{where}.shares")
        if shares < 0:
            raise _fail("negative_volume_row", f"{where}.shares")
        volumes.append(shares)
    if any(later <= earlier for earlier, later in zip(volume_dates, volume_dates[1:])):
        raise _fail("volume_dates_unordered", "volume.daily")

    window_start = _iso_date(flow["window_start"], "flow.window_start")
    window_end = _iso_date(flow["window_end"], "flow.window_end")
    if window_end != cutoff or volume_dates[-1] != cutoff:
        raise _fail("date_mismatch", "cutoff_date")
    if window_start != volume_dates[-FLOW_WINDOW_TRADING_DAYS]:
        raise _fail("date_mismatch", "flow.window_start")

    categories = [_integer(flow[key], f"flow.{key}") for key in _CATEGORY_KEYS]
    total = _integer(flow["total_net_shares"], "flow.total_net_shares")
    if total != sum(categories):
        raise _fail("flow_total_mismatch", "flow.total_net_shares")

    volume_sum = sum(volumes)
    if purpose == PURPOSE_STRATEGY_GATE:
        threshold = _gate_threshold()
        # net / (sum / 20) without ever forming the mean as a float.
        ratio = Fraction(total * VOLUME_WINDOW_TRADING_DAYS, volume_sum)
        gate_passed: bool | None = ratio >= threshold
        return InstitutionalFlowRatioResult(
            FORMULA_VERSION, purpose, cutoff, total, volume_sum, ratio, threshold, gate_passed,
        )
    return InstitutionalFlowRatioResult(
        FORMULA_VERSION, purpose, cutoff, total, volume_sum, Fraction(total, volume_sum), None, None,
    )
