"""Whether the margin condition applies to a security (Issue #392).

The official margin balance report of a session lists that session's
credit-trading securities (``margin_lists``, written by
``worker.margin_lists``).  The five-day margin change ratio of a security
that is not on the list has no meaning: the condition is not applicable
(不適用), which is not missing data.  Missing data stays missing: a list that
was not stored, or a listed security without margin values.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Sequence

APPLICABLE = "applicable"
NOT_APPLICABLE = "not_applicable"
MISSING = "missing"
STATES = (APPLICABLE, NOT_APPLICABLE, MISSING)
# The reason code of the margin condition of a security it does not apply to.
NOT_APPLICABLE_REASON = "margin_financing_not_applicable"
# The ratio's window: the signal day and the five sessions before it.
WINDOW_SESSIONS = 6

RULE = {
    "source": "margin_lists",
    "list_sources": {
        "TWSE": "twse_margin MI_MARGN selectType=ALL 融資融券彙總",
        "TPEx": "tpex_margin 上櫃股票融資融券餘額",
    },
    "applicable": "margin_balance_change_ratio_5d is finite",
    "not_applicable": [
        "the signal day's list is stored and does not list the security",
        "every list of the six-session window is stored and one does not list it",
    ],
    "otherwise": "missing",
    "notes_ignored": ["O", "X", "@", "%", "!"],
}


def margin_financing_state(
    symbol: str,
    ratio: float | None,
    window_lists: Sequence[Collection[str] | None],
) -> str:
    """``applicable``, ``not_applicable`` or ``missing`` for one signal day.

    ``window_lists`` are the stored lists of the ratio's sessions, oldest
    first and the signal day last (None: no list stored for that session).
    A computable ratio is always applicable.  Notes such as ``O`` (停止融資)
    are not read: they describe the next session, and a stopped security's
    balance still moves with repayments.
    """

    if ratio is not None and not isinstance(ratio, bool):
        try:
            if math.isfinite(float(ratio)):
                return APPLICABLE
        except (TypeError, ValueError):
            pass
    if not window_lists or window_lists[-1] is None:
        return MISSING
    if symbol not in window_lists[-1]:
        return NOT_APPLICABLE
    if (
        len(window_lists) == WINDOW_SESSIONS
        and all(item is not None for item in window_lists)
        and any(symbol not in item for item in window_lists)
    ):
        # Listed only from part of the window: no ratio over it is defined.
        return NOT_APPLICABLE
    return MISSING
