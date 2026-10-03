"""Read legacy Float values without repairing or guessing their provenance."""
from __future__ import annotations

import math
from typing import Any, Literal


def read_portfolio_value(value: Any) -> tuple[float | None, Literal["known", "missing", "invalid"]]:
    if value is None:
        return None, "missing"
    if type(value) not in {int, float}:
        return None, "invalid"
    try:
        number = float(value)
    except OverflowError:
        return None, "invalid"
    if not math.isfinite(number) or number < 0:
        return None, "invalid"
    return number, "known"
