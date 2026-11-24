"""Which master row an AI symbol candidate stands for (#264, #512).

The model often gets the exchange wrong (#264), so a code whose master has
exactly one active row is that row, whatever exchange was written.  Otherwise
the written exchange's row is used, or the code's only row when the written
exchange has none.  The news pages (``app.api._candidate_instrument``) and the
theme heat (``app.theme_heat``) read candidates by this one rule.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

Row = TypeVar("Row", bound=Sequence[object])

# The master status a row has to have to be the active row of its code.
ACTIVE = "active"


def candidate_row(rows: Sequence[Row], written: str, status_at: int) -> Row | None:
    """The row of ``rows`` (the master's rows of one code) the candidate is.

    ``rows[n][0]`` is the exchange and ``rows[n][status_at]`` the status;
    ``written`` is the exchange the model wrote.  ``None`` when the master
    cannot name the code (no row, or several rows and none on ``written``).
    """

    exact = next((row for row in rows if row[0] == written), None)
    if exact is not None and exact[status_at] == ACTIVE:
        return exact
    active = [row for row in rows if row[status_at] == ACTIVE]
    if len(active) == 1:
        return active[0]
    if exact is not None:
        return exact
    if len(rows) == 1:
        return rows[0]
    return None
