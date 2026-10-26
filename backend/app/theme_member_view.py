"""Columns and sorts of the theme member table (#280, UI_COPY_SPEC §8.5).

Read-only: the change uses the candidate ``market`` rule
(``market_change.adjacent_change``), the relative returns are the day's group
score ``member_returns``, and the badges read the day's candidate list and
complete conditional signals. A member whose latest bar is older than
``as_of`` keeps that bar but gets no change or turnover for ``as_of``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import CANDIDATE_SCORE_VERSION
from .market_change import adjacent_change
from .models import (
    CandidateRun,
    DailyCandidate,
    GroupDailyScore,
    Instrument,
    MarketBar,
    Signal,
    StrategyVersion,
)
from .strategies import REGISTRY

# Descending by value, null last, then by symbol. ``name`` and ``symbol`` sort
# ascending; ``symbol`` keeps the exchange first as before #280.
VALUE_SORTS = {
    "turnover": lambda item: item["turnover"],
    "change_pct": lambda item: item["change_pct"],
    "return_5d": lambda item: item["excess_return_5d"],
    "return_20d": lambda item: item["excess_return_20d"],
    "price": lambda item: (item["latest_bar"] or {}).get("close"),
}


def _finite(value: Any) -> float | None:
    if type(value) not in (int, float):
        return None
    return float(value) if math.isfinite(value) else None


def _member_returns(
    score: GroupDailyScore | None, as_of: date | None
) -> dict[int, dict[str, Any]]:
    """The day's ``member_returns`` rows keyed by instrument id."""

    if score is None or as_of is None or score.trading_date != as_of:
        return {}
    details = score.details_json if isinstance(score.details_json, dict) else {}
    rows = details.get("member_returns")
    if details.get("member_return_identity_version") != "instrument-id-v1":
        return {}
    if not isinstance(rows, list):
        return {}
    return {
        row["instrument_id"]: row
        for row in rows
        if isinstance(row, dict) and type(row.get("instrument_id")) is int
    }


def member_context(
    db: Session,
    as_of: date | None,
    score: GroupDailyScore | None,
    instrument_ids: Iterable[int],
) -> dict[str, Any]:
    ids = list(instrument_ids)
    ranks: dict[int, int] = {}
    conditional: set[int] = set()
    if as_of is not None and ids:
        run = db.scalar(
            select(CandidateRun).where(
                CandidateRun.score_version == CANDIDATE_SCORE_VERSION,
                CandidateRun.trading_date == as_of,
            )
        )
        if run is not None:
            ranks = dict(
                db.execute(
                    select(DailyCandidate.instrument_id, DailyCandidate.rank).where(
                        DailyCandidate.candidate_run_id == run.id,
                        DailyCandidate.instrument_id.in_(ids),
                    )
                ).all()
            )
        # Same rule as the action center's conditional bucket (decision.py).
        conditional = set(
            db.scalars(
                select(Signal.instrument_id)
                .join(StrategyVersion, StrategyVersion.id == Signal.strategy_version_id)
                .where(
                    Signal.instrument_id.in_(ids),
                    Signal.signal_date == as_of,
                    Signal.status == "conditional",
                    Signal.data_quality == "complete",
                    StrategyVersion.name.in_(list(REGISTRY)),
                )
            ).all()
        )
    return {
        "as_of": as_of,
        "returns": _member_returns(score, as_of),
        "ranks": ranks,
        "conditional": conditional,
        # One TAIEX session lookup for the whole table.
        "sessions": {},
    }


def member_columns(
    db: Session,
    instrument: Instrument,
    latest_bar: MarketBar | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    as_of = context["as_of"]
    bar = (
        latest_bar
        if latest_bar is not None
        and as_of is not None
        and latest_bar.trading_date == as_of
        else None
    )
    if as_of is not None:
        market = adjacent_change(db, instrument.id, as_of, bar, context["sessions"])
    else:
        market = {"change": None, "change_pct": None, "change_status": "missing"}
    turnover_status = bar.turnover_status if bar is not None else "missing"
    row = context["returns"].get(instrument.id)
    if row is not None and (
        row.get("exchange") != instrument.exchange
        or row.get("symbol") != instrument.symbol
    ):
        row = None
    return {
        "change": market["change"],
        "change_pct": market["change_pct"],
        "change_status": market["change_status"],
        # Only a source-stated amount is a value; 0 with another status is not.
        "turnover": _finite(bar.turnover)
        if bar is not None and turnover_status == "available"
        else None,
        "turnover_status": turnover_status,
        "excess_return_5d": _finite(row.get("excess_return_5d")) if row else None,
        "excess_return_20d": _finite(row.get("excess_return_20d")) if row else None,
        "candidate_rank": context["ranks"].get(instrument.id),
        "conditional": instrument.id in context["conditional"],
    }


def sort_members(members: list[dict[str, Any]], sort: str) -> None:
    value = VALUE_SORTS.get(sort)
    if value is not None:
        members.sort(
            key=lambda item: (
                value(item) is None,
                -(value(item) or 0),
                item["symbol"],
                item["exchange"],
            )
        )
    elif sort == "name":
        members.sort(key=lambda item: (item["name"], item["symbol"]))
    else:
        members.sort(key=lambda item: (item["exchange"], item["symbol"]))
