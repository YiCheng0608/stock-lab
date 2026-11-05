"""Stock strategy board (``strategy_board`` of ``GET /api/stocks/{exchange}/{symbol}``).

One row per registered strategy for the stock's latest analysis signal date on
or before the cutoff (#274, #268 design §3).  The row's status comes from the
signal: judged actionable on its date (``conditional``; evaluate may have
moved the status since), ``observation``, ``data_incomplete`` or
``not_applicable`` (an ETF category without general signals).  Levels never
mix: an actionable row reads the signal's own levels (``kind=actionable``), an
observation row reads its ``strategy_levels`` row (``kind=observation``), any
other row has none.  A ``strategy_levels`` row of a conditional or later
signal is read only for its condition list.  Nothing is computed or filled
at request time: a signal without a levels row (a date before the table, or a
failed step) has ``levels=null`` and ``levels_missing=true``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .candidate_runs import read_run
from .candidate_view import liquidity_exclusions
from .domain import CANDIDATE_SCORE, STRATEGY_LEVELS_VERSION
from .liquidity import average_volumes
from .models import Instrument, Signal, StrategyLevel, StrategyVersion
from .presentation import display_reason
from .signal_versions import readable_signal
from .strategies import REGISTRY, Strategy, current_strategy, registry_key
from .strategies import levels as level_rules

SIGNAL_NAMESPACE = "analysis"
OBSERVATION_LABEL = "條件未成立・觀察價位"
ETF_EXCLUDED_PREFIX = level_rules.ETF_EXCLUDED_PREFIX
# Statuses only a signal judged conditional on its date can reach, for rows
# written before analyze stored the ``actionable`` flag (candidate pool rule).
LEGACY_ACTIONABLE_STATUSES = frozenset(
    CANDIDATE_SCORE["pool"]["legacy_actionable_statuses"]
)


def _actionable(signal: Signal) -> bool:
    evidence = (
        signal.rule_evidence_json if isinstance(signal.rule_evidence_json, dict) else {}
    )
    if "actionable" in evidence:
        return evidence["actionable"] is True
    return signal.status in LEGACY_ACTIONABLE_STATUSES


def _missing(signal: Signal) -> list[str]:
    """The reasons analyze recorded for an incomplete signal (rationale ``missing=``)."""

    for part in (signal.rationale or "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == "missing":
            return [item for item in value.split(",") if item]
    return []


def _status(signal: Signal) -> tuple[str, list[str]]:
    if _actionable(signal):
        return "conditional", []
    if signal.status == "observation":
        return "observation", []
    missing = _missing(signal)
    if signal.status == "invalid_levels":
        missing = [*missing, "invalid_levels"]
    if any(reason.startswith(ETF_EXCLUDED_PREFIX) for reason in missing):
        return "not_applicable", missing
    return "data_incomplete", missing


def _actionable_levels(strategy: Strategy, signal: Signal) -> dict[str, Any]:
    entry = (
        signal.breakout_price
        if strategy.entry_type == "breakout"
        else signal.reference_entry
    )
    risk_reward = None
    if (
        entry is not None
        and signal.invalid_price is not None
        and signal.target_1 is not None
        and entry > signal.invalid_price
    ):
        risk_reward = round(
            (signal.target_1 - entry) / (entry - signal.invalid_price), 4
        )
    return {
        "kind": "actionable",
        "entry_type": strategy.entry_type,
        "trigger_price": signal.breakout_price,
        "reference_entry": signal.reference_entry,
        "entry_low": signal.pullback_low,
        "entry_high": signal.pullback_high,
        "invalid_price": signal.invalid_price,
        "target_1": signal.target_1,
        "target_2": signal.target_2,
        "risk_reward": risk_reward,
    }


def _observation_levels(row: StrategyLevel) -> dict[str, Any]:
    return {
        "kind": "observation",
        "display_label": OBSERVATION_LABEL,
        "availability": row.availability,
        "next_session_date": row.next_session_date.isoformat()
        if row.next_session_date
        else None,
        "trigger_price": row.trigger_price,
        "zone_low": row.zone_low,
        "zone_high": row.zone_high,
        "min_volume": row.min_volume,
        "max_volume": row.max_volume,
        "reference_entry": row.reference_entry,
        "entry_low": row.entry_low,
        "entry_high": row.entry_high,
        "invalid_price": row.invalid_price,
        "target_1": row.target_1,
        "target_2": row.target_2,
        "risk_reward": row.risk_reward,
        "reachable_next_session": row.reachable_next_session,
        "price_basis": row.price_basis,
        "missing_inputs": list(row.missing_inputs_json or []),
        "missing_labels": list(
            dict.fromkeys(
                display_reason(item) for item in row.missing_inputs_json or []
            )
        ),
    }


def _row(
    db: Session, strategy: Strategy, signal: Signal | None, day: Any
) -> dict[str, Any]:
    base = {
        "strategy": strategy.key,
        "label": strategy.label_zh,
        "version": strategy.version,
        "entry_type": strategy.entry_type,
    }
    if signal is None:
        return {
            **base,
            "status": "data_incomplete",
            "signal_id": None,
            "signal_date": day.isoformat() if day else None,
            "earliest_execution_date": None,
            "levels": None,
            "levels_missing": False,
            "unmet": [],
            "missing": ["signal_not_computed"],
            "missing_labels": [display_reason("signal_not_computed")],
            "conditions": [],
        }
    status, missing = _status(signal)
    stored = db.scalar(
        select(StrategyLevel).where(
            StrategyLevel.signal_id == signal.id,
            StrategyLevel.levels_version == STRATEGY_LEVELS_VERSION,
        )
    )
    conditions = (
        level_rules.expand_conditions(strategy, stored.conditions_json)
        if stored
        else []
    )
    levels: dict[str, Any] | None = None
    if status == "conditional":
        levels = _actionable_levels(strategy, signal)
    elif status == "observation" and stored is not None:
        levels = _observation_levels(stored)
    return {
        **base,
        "status": status,
        "signal_id": signal.id,
        "signal_date": signal.signal_date.isoformat(),
        "earliest_execution_date": signal.earliest_execution_date.isoformat()
        if signal.earliest_execution_date
        else None,
        "levels": levels,
        # An observation without its row: the levels step did not run for
        # this date (before the table existed, or it failed).  Not filled.
        "levels_missing": status == "observation" and stored is None,
        "unmet": [item["code"] for item in conditions if item["satisfied"] is False],
        "missing": missing,
        "missing_labels": list(dict.fromkeys(display_reason(item) for item in missing)),
        "conditions": conditions,
    }


def _candidate(candidate: dict[str, Any] | None, day: Any) -> dict[str, Any] | None:
    """The as-of day's candidate row only; an older run's row is not this board's."""

    if not candidate or day is None or candidate.get("trading_date") != day.isoformat():
        return None
    return {
        "rank": candidate.get("rank"),
        "total_score": candidate.get("total_score"),
        "score_version": candidate.get("score_version"),
        "strategy": candidate.get("strategy"),
        "llm_note": candidate.get("llm_note"),
    }


def _liquidity(db: Session, instrument: Instrument, day: Any) -> dict[str, Any] | None:
    """The board day's 20-session average volume in lots (#490).

    The value is the one the day's candidate run read when the run left the
    stock out for the floor (``summary_json.liquidity``), otherwise it is
    computed with the same rule (``app.liquidity``).  ``minimum_lots`` comes
    from the day's run, so a day scored by a version without the floor has
    none and the page shows no floor note.
    """

    if day is None:
        return None
    run = read_run(db, day)
    floor = (
        ((run.config_json or {}).get("pool") or {}).get("liquidity") if run else None
    )
    excluded = liquidity_exclusions(run).get(instrument.id)
    if excluded is not None:
        lots, state = excluded["average_volume_lots_20d"], excluded["state"]
    else:
        average = average_volumes(db, [instrument], day)[instrument.id]
        lots, state = average.as_json()["average_volume_lots_20d"], average.state
    minimum = floor.get("minimum_lots") if isinstance(floor, dict) else None
    return {
        "average_volume_lots_20d": lots,
        "state": state,
        "unit": "lots",
        "data_as_of": day.isoformat(),
        "minimum_lots": minimum,
        "below_minimum": (
            lots < minimum if lots is not None and minimum is not None else None
        ),
        # low_volume / liquidity_data_missing when the day's run left the
        # stock's conditional signal out of the candidates for the floor.
        "candidate_exclusion": excluded["exclusion"] if excluded else None,
        "score_version": run.score_version if run else None,
    }


def strategy_board(
    db: Session,
    instrument: Instrument,
    cutoff: Any,
    candidate: dict[str, Any] | None,
) -> dict[str, Any]:
    analysis = (
        Signal.instrument_id == instrument.id,
        Signal.signal_key.like(f"{SIGNAL_NAMESPACE}-%"),
    )
    day = (
        db.scalar(
            select(func.max(Signal.signal_date)).where(
                *analysis, Signal.signal_date <= cutoff
            )
        )
        if cutoff
        else None
    )
    # Registered strategy -> (the signal's own strategy, signal).  The day's
    # rows are those the other pages read (app.signal_versions): a superseded
    # version's signal, with its own conditions, only on a day without a
    # registered one (#392).
    signals: dict[str, tuple[Strategy, Signal]] = {}
    if day is not None:
        for signal, version in db.execute(
            select(Signal, StrategyVersion)
            .join(StrategyVersion, StrategyVersion.id == Signal.strategy_version_id)
            .where(*analysis, Signal.signal_date == day, readable_signal())
            .order_by(desc(Signal.id))
        ).all():
            strategy = current_strategy(
                version.name, version.version, version.formula_version
            )
            key = registry_key(strategy.key) if strategy is not None else None
            if key is not None:
                signals.setdefault(key, (strategy, signal))
    return {
        "as_of": day.isoformat() if day else None,
        "levels_version": STRATEGY_LEVELS_VERSION,
        "candidate": _candidate(candidate, day),
        "liquidity": _liquidity(db, instrument, day),
        "strategies": [
            _row(db, *signals[key], day)
            if key in signals
            else _row(db, strategy, None, day)
            for key, strategy in REGISTRY.items()
        ],
    }
