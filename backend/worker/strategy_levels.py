"""Observation price levels of a session's signals (V1_SPEC strategy_levels_v1).

The ``strategy_levels`` step of ``worker.cli daily`` (after a successful
analyze; its failure never changes the run status) and ``worker.cli
strategy-levels``.  For every analysis signal of the date whose strategy
version and formula version are the registered ones, the strategy solves its
conditions for the next session's close and volume
(``Strategy.observation_levels``) and lists T's conditions
(``Strategy.conditions``); the result is one ``strategy_levels`` row per
signal and STRATEGY_LEVELS_VERSION.

Inputs are T's stored data only: the signal's own evidence (prior windows,
moving averages, confirmations, each strategy's state), T's bar and feature,
the bars through T and the corporate actions stored so far.  When an action
dated after T up to the next session is stored, the prices are converted to
the next session's basis (``price_basis``).  The next session is the
official calendar's (the signals' earliest execution date, #294), else the
next weekday when the stored calendar cannot answer.

``signals`` is never written.  The same date gives the same rows: a row is
written, and ``computed_at`` moved, only when a value changes.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.domain import STRATEGY_LEVELS_VERSION, RuleEvaluation
from app.models import (
    CorporateAction,
    Instrument,
    MarketBar,
    Signal,
    StrategyLevel,
    StrategyVersion,
    TechnicalFeature,
)
from app.strategies import NextSessionInputs, StrategyInputs, current_strategy
from app.strategies import levels
from worker import pipeline

SIGNAL_NAMESPACE = "analysis"
# Bars read through T: 59 closes for the pullback sums, and room for the
# previous close an action's fallback reference price needs.
HISTORY_BARS = 80


def _next_weekday(day: date) -> date:
    following = day + timedelta(days=1)
    while following.weekday() >= 5:
        following += timedelta(days=1)
    return following


def _next_session_factor(
    db: Session, instrument_id: int, signal_date: date, next_date: date, close: float
) -> tuple[float, bool]:
    """Price factor from T's basis to the next session's, and whether one applied.

    The actions dated after T up to the next session, with T's close as the
    fallback reference price, exactly as analyze will build that session's
    basis (pipeline._action_factor_by_bar).
    """

    actions = db.scalars(
        select(CorporateAction)
        .where(
            CorporateAction.instrument_id == instrument_id,
            CorporateAction.action_date > signal_date,
            CorporateAction.action_date <= next_date,
        )
        .order_by(CorporateAction.action_date, CorporateAction.id)
    ).all()
    if not actions:
        return 1.0, False
    factor, applied = pipeline._corporate_action_factor(
        list(actions),
        fallback_reference_prices={
            action.action_date: close
            for action in actions
            if action.reference_price is None and close > 0
        },
    )
    if not applied or not math.isfinite(factor) or factor <= 0:
        return 1.0, False
    return factor, factor != 1.0


def _evaluation(evidence: dict[str, Any], kind: str) -> RuleEvaluation:
    state = evidence.get(kind) if isinstance(evidence.get(kind), dict) else {}
    name = str(state.get("state") or "data_incomplete")
    return RuleEvaluation(name == "passed", name, tuple(state.get("reasons") or ()))


def _strategy_inputs(
    evidence_inputs: dict[str, Any], bar: MarketBar, atr14: float | None
) -> StrategyInputs:
    """T's strategy inputs as analyze stored them in the signal evidence."""

    raw_bar_count = evidence_inputs.get("bar_count_60d")
    try:
        bar_count = int(raw_bar_count)
    except (TypeError, ValueError):
        bar_count = 0
    return StrategyInputs(
        bar_count=bar_count,
        close=pipeline._safe_float(bar.close),
        volume=pipeline._safe_float(bar.volume),
        ma20=pipeline._safe_float(evidence_inputs.get("ma20")),
        ma60=pipeline._safe_float(evidence_inputs.get("ma60")),
        atr14=atr14,
        prior_highs=evidence_inputs.get("prior_20_highs"),
        prior_volumes=evidence_inputs.get("prior_20_volumes"),
        group_excess_return_20d=evidence_inputs.get("group_excess_return_20d"),
        institutional_flow_ratio_5d=evidence_inputs.get(
            "institutional_flow_to_turnover_ratio_5d"
        ),
        margin_change_ratio_5d=evidence_inputs.get("margin_balance_change_ratio_5d"),
    )


def _history(db: Session, instrument_id: int, signal_date: date) -> list[MarketBar]:
    """The last HISTORY_BARS bars through T, oldest first."""

    return list(
        reversed(
            db.scalars(
                select(MarketBar)
                .where(
                    MarketBar.instrument_id == instrument_id,
                    MarketBar.trading_date <= signal_date,
                )
                .order_by(desc(MarketBar.trading_date))
                .limit(HISTORY_BARS)
            ).all()
        )
    )


def _next_session_inputs(
    db: Session,
    instrument: Instrument,
    bars: list[MarketBar],
    next_date: date,
    inputs: StrategyInputs,
) -> NextSessionInputs:
    bar = bars[-1]
    signal_date = bar.trading_date
    factors = pipeline._action_factor_by_bar(db, instrument.id, bars)
    factor, converted = _next_session_factor(
        db, instrument.id, signal_date, next_date, float(bar.close or 0)
    )
    # Each bar in the next session's basis: T's factor over the bar's, times
    # the factor of the actions between T and the next session.
    ratios = [
        factors[-1] / bar_factor * factor if bar_factor > 0 else factor
        for bar_factor in factors
    ]
    close = pipeline._safe_float(bar.close)
    return NextSessionInputs(
        instrument_type=instrument.instrument_type,
        etf_category=instrument.etf_category,
        bar_count=inputs.bar_count,
        is_suspended=bool(bar.is_suspended),
        close=close * factor if close is not None else None,
        atr14=inputs.atr14 * factor if inputs.atr14 is not None else None,
        closes=tuple(
            item.close * ratio for item, ratio in zip(bars[-59:], ratios[-59:])
        ),
        highs=tuple(
            round(item.high * ratio, 6) for item, ratio in zip(bars[-20:], ratios[-20:])
        ),
        volumes=tuple(int(item.volume) for item in bars[-20:]),
        group_excess_return_20d=inputs.group_excess_return_20d,
        institutional_flow_ratio_5d=inputs.institutional_flow_ratio_5d,
        margin_change_ratio_5d=inputs.margin_change_ratio_5d,
        price_basis=levels.PRICE_BASIS_NEXT_SESSION
        if converted
        else levels.PRICE_BASIS_SIGNAL_DAY,
    )


def _write(db: Session, signal: Signal, values: dict[str, Any], now: datetime) -> bool:
    """Insert or update the signal's row; True when anything was written."""

    row = db.scalar(
        select(StrategyLevel).where(
            StrategyLevel.signal_id == signal.id,
            StrategyLevel.levels_version == STRATEGY_LEVELS_VERSION,
        )
    )
    if row is None:
        db.add(
            StrategyLevel(
                signal_id=signal.id,
                levels_version=STRATEGY_LEVELS_VERSION,
                computed_at=now,
                **values,
            )
        )
        return True
    changed = False
    for key, value in values.items():
        if getattr(row, key) != value:
            setattr(row, key, value)
            changed = True
    if changed:
        row.computed_at = now
    return changed


def compute_strategy_levels(
    db: Session, signal_date: date, *, now: datetime | None = None
) -> dict[str, Any]:
    """Write the levels of every analysis signal of ``signal_date`` (caller commits)."""

    stamp = now or datetime.utcnow()
    rows = db.execute(
        select(Signal, StrategyVersion, Instrument)
        .join(StrategyVersion, StrategyVersion.id == Signal.strategy_version_id)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .where(
            Signal.signal_date == signal_date,
            Signal.signal_key.like(f"{SIGNAL_NAMESPACE}-%"),
        )
        .order_by(Signal.instrument_id, Signal.id)
    ).all()
    by_instrument: dict[int, list[tuple[Signal, StrategyVersion, Instrument]]] = (
        defaultdict(list)
    )
    for row in rows:
        by_instrument[row[2].id].append(row)
    availability: dict[str, Counter[str]] = defaultdict(Counter)
    processed = written = skipped = 0
    for group in by_instrument.values():
        instrument = group[0][2]
        current = [
            (signal, strategy)
            for signal, version, _instrument in group
            if (
                strategy := current_strategy(
                    version.name, version.version, version.formula_version
                )
            )
            is not None
        ]
        skipped += len(group) - len(current)
        if not current:
            continue
        # Every strategy's row of one analyze run holds the same inputs.
        evidence = current[0][0].rule_evidence_json or {}
        feature = db.scalar(
            select(TechnicalFeature).where(
                TechnicalFeature.instrument_id == instrument.id,
                TechnicalFeature.trading_date == signal_date,
            )
        )
        atr14 = pipeline._safe_float(
            (feature.features_json or {}).get("atr14") if feature else None
        )
        bars = _history(db, instrument.id, signal_date)
        if not bars or bars[-1].trading_date != signal_date:
            skipped += len(current)
            continue
        bar = bars[-1]
        inputs = _strategy_inputs(evidence.get("inputs") or {}, bar, atr14)
        next_date = pipeline._next_execution_date(
            db, signal_date
        ).date or _next_weekday(signal_date)
        next_inputs = _next_session_inputs(db, instrument, bars, next_date, inputs)
        for signal, strategy in current:
            signal_evidence = signal.rule_evidence_json or {}
            evaluation = _evaluation(signal_evidence, strategy.kind)
            observation = strategy.observation_levels(next_inputs)
            conditions = [
                *levels.common_conditions(
                    instrument_type=instrument.instrument_type,
                    etf_category=instrument.etf_category,
                    bar_count=inputs.bar_count,
                    is_suspended=bool(bar.is_suspended),
                    evaluation=evaluation,
                ),
                *strategy.conditions(inputs, evaluation, observation),
            ]
            values = {
                **levels.as_json(observation),
                "next_session_date": next_date,
                "conditions_json": levels.compact_conditions(strategy, conditions),
                "price_basis": next_inputs.price_basis,
            }
            written += int(_write(db, signal, values, stamp))
            processed += 1
            availability[strategy.key][observation.availability] += 1
    db.flush()
    return {
        "status": "success",
        "date": signal_date.isoformat(),
        "levels_version": STRATEGY_LEVELS_VERSION,
        "signals": processed,
        "rows_written": written,
        "rows_unchanged": processed - written,
        "signals_skipped": skipped,
        "availability": {
            key: dict(sorted(counts.items())) for key, counts in availability.items()
        },
        "records": processed,
    }


def run_strategy_levels(target: date | None = None) -> dict[str, Any]:
    """Levels for ``target``'s signals (default: the latest analysis signal date)."""

    # pipeline.SessionLocal, like the other daily steps (and their test patches).
    with pipeline.SessionLocal() as db:
        day = target or db.scalar(
            select(func.max(Signal.signal_date)).where(
                Signal.signal_key.like(f"{SIGNAL_NAMESPACE}-%")
            )
        )
        if day is None or not db.scalar(
            select(Signal.id)
            .where(
                Signal.signal_date == day,
                Signal.signal_key.like(f"{SIGNAL_NAMESPACE}-%"),
            )
            .limit(1)
        ):
            return {
                "status": "no_data",
                "reason": "no_signals_for_date",
                "date": day.isoformat() if day else None,
                "signals": 0,
                "rows_written": 0,
                "records": 0,
            }
        result = compute_strategy_levels(db, day)
        db.commit()
    return result
