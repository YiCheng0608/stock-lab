"""Where the stored history starts: the production default, or a research DB's (Issue #692).

The production database keeps the stock history from 2024-09-30 and the index
history from 2023-09-01.  A separate research database (its own volume, raw and
locks; docs/ops/RESEARCH_DB.md) is backfilled to the first day each official
source answers, so these starts are read from the environment once, when the
process imports ``app.coverage`` / ``worker.index_bars``.  Unset (or blank)
gives the production values exactly; a value may only move a start earlier,
never later, and the index history may not start after the stock history.

``STOCK_HISTORY_CREATE_UNMATCHED=1`` lets a collect create the instrument of an
official quote row whose ordinary-share or ETF code has none (a company that
left the lists before the database was built) instead of recording an
``unmatched_bar`` row per batch (worker.pipeline.create_history_instrument).
Only a research database sets it.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from datetime import date

SESSION_BASIS_START_ENV = "STOCK_SESSION_BASIS_START"
INDEX_HISTORY_START_ENV = "STOCK_INDEX_HISTORY_START"
CREATE_UNMATCHED_ENV = "STOCK_HISTORY_CREATE_UNMATCHED"

# The first session of the stock history (#1 6714433517).
DEFAULT_SESSION_BASIS_START = date(2024, 9, 30)
# The index history starts about a year earlier (Issue #563).
DEFAULT_INDEX_HISTORY_START = date(2023, 9, 1)

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _history_date(name: str, default: date, environ: Mapping[str, str]) -> date:
    raw = (environ.get(name) or "").strip()
    if not raw:
        return default
    if not _ISO_DATE.fullmatch(raw):
        raise ValueError(f"{name} must be YYYY-MM-DD, got {raw!r}")
    value = date.fromisoformat(raw)
    if value > default:
        raise ValueError(
            f"{name}={raw} is after the production start {default.isoformat()}; "
            "a research history may only start earlier"
        )
    return value


def session_basis_start(environ: Mapping[str, str] = os.environ) -> date:
    """The first session of the stock history."""

    return _history_date(SESSION_BASIS_START_ENV, DEFAULT_SESSION_BASIS_START, environ)


def index_history_start(environ: Mapping[str, str] = os.environ) -> date:
    """The first session the index history (worker.index_bars) writes."""

    value = _history_date(INDEX_HISTORY_START_ENV, DEFAULT_INDEX_HISTORY_START, environ)
    basis = session_basis_start(environ)
    if value > basis:
        raise ValueError(
            f"{INDEX_HISTORY_START_ENV}={value.isoformat()} is after the stock "
            f"history start {basis.isoformat()}"
        )
    return value


def create_unmatched_instruments(environ: Mapping[str, str] = os.environ) -> bool:
    """Whether a collect creates the instrument of an unmatched quote code."""

    raw = (environ.get(CREATE_UNMATCHED_ENV) or "").strip()
    if raw in ("", "0"):
        return False
    if raw == "1":
        return True
    raise ValueError(f"{CREATE_UNMATCHED_ENV} must be 0 or 1, got {raw!r}")
