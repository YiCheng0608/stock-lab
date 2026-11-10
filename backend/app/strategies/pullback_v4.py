"""``pullback_v4``: ``pullback_v3`` whose RR is read at the entry zone's midpoint.

The page tells the reader to enter inside the entry zone (MA20 ± width), but
up to v3 ``reference_entry``, the entry every RR is computed from, was T's
close, which can lie outside that zone (Issue #580).  v4 stores the zone's
midpoint there; the zone, the invalid price and the targets keep v3's
definitions (``risk_levels`` around the close), so the RR is recomputed and
the 1.5 floor (``validate_signal_levels``) judges it.  Every condition and
threshold is v3's, and v3 is not changed.
"""

from __future__ import annotations

import copy
import dataclasses
from typing import Any

from .base import (
    PULLBACK_ZONE_MIDPOINT_FORMULA,
    RISK_REWARD_ZONE_MIDPOINT,
    NextSessionInputs,
    ObservationLevels,
    SignalLevels,
    StrategyInputs,
)
from .pullback_v3 import CONFIG as V3_CONFIG
from .pullback_v3 import PullbackV3

CONFIG: dict[str, Any] = copy.deepcopy(V3_CONFIG)
CONFIG["name"] = "pullback_v4"
CONFIG["version"] = "4.0.0"
CONFIG["supersedes"] = {"name": "pullback_v3", "version": "3.0.0"}
CONFIG["risk_management"]["risk_reward_entry"] = "pullback_zone_midpoint"


def zone_midpoint(low: float | None, high: float | None) -> float | None:
    """The entry zone's midpoint to two decimals; None without both edges."""

    if low is None or high is None:
        return None
    return round((low + high) / 2, 2)


def risk_reward(
    entry: float | None, invalid: float | None, target: float | None
) -> float | None:
    """(target − entry)／(entry − invalid) to two decimals, only for invalid < entry < target."""

    if entry is None or invalid is None or target is None:
        return None
    if not invalid < entry < target:
        return None
    return round((target - entry) / (entry - invalid), 2)


class PullbackV4(PullbackV3):
    config = CONFIG
    level_formula_version = PULLBACK_ZONE_MIDPOINT_FORMULA
    risk_reward_basis = RISK_REWARD_ZONE_MIDPOINT

    def actionable_levels(self, inputs: StrategyInputs) -> SignalLevels:
        levels = super().actionable_levels(inputs)
        return dataclasses.replace(
            levels,
            reference_entry=zone_midpoint(levels.pullback_low, levels.pullback_high),
        )

    def observation_levels(self, inputs: NextSessionInputs) -> ObservationLevels:
        levels = super().observation_levels(inputs)
        if levels.availability != "levels":
            return levels
        entry = zone_midpoint(levels.entry_low, levels.entry_high)
        return dataclasses.replace(
            levels,
            reference_entry=entry,
            risk_reward=risk_reward(entry, levels.invalid_price, levels.target_1),
        )


PULLBACK_V4 = PullbackV4()
