"""The margin condition of a security whose balance five sessions ago was 0 (#404).

The five-day margin change ratio ``(margin_balance[T]-margin_balance[T-5]) /
abs(margin_balance[T-5])`` has no denominator when the balance five sessions
ago was 0, so it stays null (the ratio itself is not redefined: the group
score and the candidate score read it unchanged).  The strategies whose
config carries ``data_policy.margin_zero_base`` (the v3 versions) judge the
margin condition by the two balances instead of failing closed as
``data_incomplete``:

- 0 then 0: the balance did not change, the change is 0 and the condition
  (``maximum_balance_change_ratio``) holds;
- 0 then more than 0: the balance increased from nothing, which is an
  abnormal increase (``margin_financing_increase_abnormal``).

Missing data stays missing: the state is only given when the six sessions of
the ratio all have a chip row and both balances are present.
"""

from __future__ import annotations

import math
from typing import Any

UNCHANGED = "zero_base_unchanged"
INCREASED = "zero_base_increased"
STATES = (UNCHANGED, INCREASED)

RULE: dict[str, Any] = {
    "applies_when": (
        "margin_balance[T-5] == 0 and margin_balance[T] is present, "
        "the six sessions of margin_balance_change_ratio_5d all have a chip row"
    ),
    UNCHANGED: "margin_balance[T] == 0: change 0, the margin condition holds",
    INCREASED: (
        "margin_balance[T] > 0: margin_financing_increase_abnormal, "
        "the margin condition fails"
    ),
    "otherwise": "margin_balance_change_ratio_5d as before; missing stays missing",
    "not_applicable_first": "a non-margin security stays not applicable (#392)",
}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def zero_base_state(first: Any, last: Any) -> str | None:
    """``UNCHANGED``, ``INCREASED`` or None from the window's two balances.

    ``first`` is the balance five sessions before the signal day and ``last``
    the signal day's.  None when the base is not 0 (the ratio is defined) or
    either balance is missing or invalid.
    """

    first, last = _number(first), _number(last)
    if first != 0 or last is None or last < 0:
        return None
    return UNCHANGED if last == 0 else INCREASED
