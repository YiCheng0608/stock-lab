"""Scoring the stored AI list readings after the close (Issue #1147).

The ``ai_list_score`` step of ``worker.cli daily`` (after ``premarket_score``,
non-blocking) and ``worker.cli ai-list-score``.  Every ``done`` reading of
``ai_list_readings`` (each trading day, prompt version and role) gets, under
``app.ai_list_score.SCORE_VERSION`` (docs/spec/ai_list.md 對答案):

* ``market``: its stance against TAIEX from D's open, ``d0`` and ``t5``;
* ``stock``: each pick's D-open hold, its 今日不適用 check, and its
  ``tracking_v2`` results on the AI's checked levels and on the rule levels
  (``t5``, ``t20``);
* ``overall``: the list against the population and the rule list (``t5``,
  ``t20``).

The bars, sessions, closures, population and market stance are
``worker.premarket_score``'s own functions, called and not changed.  A horizon
is written once its last session is stored (up to the target date) and never
again; nothing after the target date is read.
"""

from __future__ import annotations

import sys
import time
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, defer

from app import ai_list_score as score
from app import premarket_score as v1
from app.clock import utcnow
from app.models import (
    AiListPick,
    AiListReading,
    AiListScore,
    DailyCandidate,
    Instrument,
    MarketBar,
)
from app.premarket_ai import DONE
from app.tracking import TRACKING_RULES_V2, TrackBar, settle, track_path
from worker import pipeline
from worker import premarket_score as pm


def _levels(levels: Any, tracked: list[TrackBar], horizon: int) -> dict[str, Any]:
    result = (
        settle(track_path(levels, tracked, rules=TRACKING_RULES_V2), horizon)
        if tracked
        else None
    )
    return v1.settled(result) or {"status": "incomparable", "reason": v1.MISSING_BAR}


def _d_open(
    tracked: list[TrackBar], session_date: date
) -> tuple[float | None, float | None]:
    """D's official raw open and its factor; (None, None) without a usable D bar."""

    first = tracked[0] if tracked else None
    if (
        first is None
        or first.trading_date != session_date
        or v1.suspended(first)
        or not first.factor
    ):
        return None, None
    return first.open, first.factor


def pick_outcome(
    db: Session,
    reading: AiListReading,
    pick: AiListPick,
    sessions: list[date],
    horizon: int,
    facts: dict[str, Any],
) -> dict[str, Any]:
    """One pick at T+``horizon`` (``open_hold.excess`` is added with the population)."""

    _bars, tracked = pipeline._tracking_inputs(
        db,
        pick.instrument_id,
        reading.list_date,
        evaluation_cutoff=sessions[horizon - 1],
    )
    display = pick.display_levels_json
    passed = score.levels_passed(display)
    out: dict[str, Any] = {
        "symbol": pick.symbol,
        "rank": pick.rank,
        "setup": pick.setup,
        "basis": list(pick.basis_json or []),
        "basis_primary": pick.basis_primary,
        "confidence": pick.confidence,
        "on_rule_list": pick.on_rule_list,
        "levels_passed": passed,
        "corporate_action_on_session": bool(facts.get("corporate_action_on_session")),
        "open_hold": v1.open_hold(tracked, sessions, horizon),
        "open_check": None,
        "ai_levels": None,
        "ai_levels_reason": None,
        "rule_levels": None,
        "rule_levels_reason": None,
    }
    if passed:
        out["open_check"] = score.open_check(
            display, *_d_open(tracked, reading.session_date)
        )
        out["ai_levels"] = _levels(score.ai_track_levels(display), tracked, horizon)
    else:
        out["ai_levels_reason"] = score.LEVELS_CHECK_FAILED
    if v1.has_levels(pick.rule_levels_json):
        out["rule_levels"] = _levels(
            v1.original_levels(pick.rule_levels_json), tracked, horizon
        )
    else:
        out["rule_levels_reason"] = score.NO_RULE_LEVELS
    return out


def rule_outcomes(
    db: Session,
    reading: AiListReading,
    sessions: list[date],
    horizon: int,
    candidates: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """The list date's rule list (the today list the input read) at T+``horizon``.

    The levels are the input's ``strategy_levels`` of the stock, the ones the
    picks' ``rule_levels_json`` keep.
    """

    pool = (reading.input_json or {}).get("pool") or {}
    run_id = pool.get("today_list_run_id")
    if run_id is None:
        return []
    out = []
    for row, symbol in db.execute(
        select(DailyCandidate, Instrument.symbol)
        .join(Instrument, Instrument.id == DailyCandidate.instrument_id)
        .where(DailyCandidate.candidate_run_id == run_id)
        .order_by(DailyCandidate.rank)
    ):
        _bars, tracked = pipeline._tracking_inputs(
            db,
            row.instrument_id,
            reading.list_date,
            evaluation_cutoff=sessions[horizon - 1],
        )
        levels = (candidates.get(symbol) or {}).get("strategy_levels")
        out.append(
            {
                "symbol": symbol,
                "rank": row.rank,
                "open_hold": v1.open_hold(tracked, sessions, horizon),
                "levels": _levels(v1.original_levels(levels), tracked, horizon)
                if v1.has_levels(levels)
                else None,
            }
        )
    return out


def _existing(db: Session, reading_id: int) -> set[tuple[str, str, str]]:
    return {
        (scope, subject, horizon)
        for scope, subject, horizon in db.execute(
            select(AiListScore.scope, AiListScore.subject, AiListScore.horizon).where(
                AiListScore.reading_id == reading_id,
                AiListScore.score_version == score.SCORE_VERSION,
            )
        )
    }


FINISHED = pm.FINISHED


def score_reading(
    db: Session,
    reading: AiListReading,
    target: date,
    *,
    now: datetime,
    population_cache: dict[tuple[date, int], dict[str, Any]],
) -> list[AiListScore] | None:
    """The rows of one reading that are due by ``target`` and not yet written.

    None when the reading is already finished (nothing was read for it).
    """

    have = _existing(db, reading.id)
    if FINISHED <= have:
        return None
    sessions = pm._sessions(db, reading.list_date, target)
    if not sessions:
        return []
    no_session = sessions[0] != reading.session_date
    if no_session and not pm._closed(db, reading.session_date):
        return []
    rows: list[AiListScore] = []

    def add(scope: str, subject: str, horizon: str, outcome, pick_id=None):
        rows.append(
            AiListScore(
                reading_id=reading.id,
                pick_id=pick_id,
                session_date=reading.session_date,
                prompt_version=reading.prompt_version,
                role=reading.role,
                scope=scope,
                subject=subject,
                horizon=horizon,
                score_version=score.SCORE_VERSION,
                outcome_json=outcome,
                computed_at=now,
            )
        )

    basis = list(reading.market_method_json or [])
    for horizon, length in score.MARKET_HORIZONS.items():
        key = (score.MARKET, score.MARKET, horizon)
        if key in have or (len(sessions) < length and not no_session):
            continue
        outcome = pm.market_rows(db, reading, sessions, horizon)
        outcome.update(basis=basis, basis_primary=basis[0] if basis else None)
        add(score.MARKET, score.MARKET, horizon, outcome)
    if no_session:
        for horizon in score.STOCK_HORIZONS:
            if (score.OVERALL, score.OVERALL, horizon) not in have:
                add(
                    score.OVERALL,
                    score.OVERALL,
                    horizon,
                    {"status": score.NO_DATA, "reason": v1.NO_SESSION},
                )
        return rows
    picks = list(
        db.scalars(
            select(AiListPick)
            .where(AiListPick.reading_id == reading.id)
            .order_by(AiListPick.rank)
        )
    )
    candidates: dict[str, dict[str, Any]] | None = None
    for horizon, length in score.STOCK_HORIZONS.items():
        wanted = [(score.STOCK, pick.symbol, horizon) for pick in picks]
        wanted.append((score.OVERALL, score.OVERALL, horizon))
        if all(key in have for key in wanted) or len(sessions) < length:
            continue
        if candidates is None:
            # input_json is deferred: read once, for the facts and the rule levels.
            candidates = {
                item.get("symbol"): item
                for item in (reading.input_json or {}).get("candidates") or []
            }
        cache_key = (reading.session_date, length)
        if cache_key not in population_cache:
            population_cache[cache_key] = pm.population(
                db, reading.list_date, sessions, length
            )
        population = population_cache[cache_key]
        outcomes = []
        for pick in picks:
            facts = (candidates.get(pick.symbol) or {}).get("level_facts") or {}
            outcome = pick_outcome(db, reading, pick, sessions, length, facts)
            outcome["open_hold"] = score.with_excess(
                outcome["open_hold"], population.get("mean")
            )
            outcomes.append((pick, outcome))
        for pick, outcome in outcomes:
            if (score.STOCK, pick.symbol, horizon) not in have:
                add(score.STOCK, pick.symbol, horizon, outcome, pick_id=pick.id)
        if (score.OVERALL, score.OVERALL, horizon) not in have:
            overall = score.overall_outcome(
                [outcome for _pick, outcome in outcomes],
                rule_outcomes(db, reading, sessions, length, candidates),
                population,
                pool_phase=reading.pool_phase,
            )
            overall["reading_id"] = reading.id
            # The horizon's last session: the month the report counts it in.
            overall["end_date"] = sessions[length - 1].isoformat()
            add(score.OVERALL, score.OVERALL, horizon, overall)
    return rows


def score_readings(
    db: Session,
    target: date,
    *,
    now: datetime | None = None,
    stats: dict[str, int] | None = None,
) -> list[AiListScore]:
    """Every due, unwritten row of the done readings through ``target`` (not added)."""

    stamp = now or utcnow()
    readings = db.scalars(
        select(AiListReading)
        .options(
            defer(AiListReading.input_json),
            defer(AiListReading.checks_json),
            defer(AiListReading.attempts_json),
            defer(AiListReading.error),
        )
        .where(AiListReading.status == DONE, AiListReading.session_date <= target)
        .order_by(
            AiListReading.session_date,
            AiListReading.role,
            AiListReading.prompt_version,
            AiListReading.id,
        )
    ).all()
    cache: dict[tuple[date, int], dict[str, Any]] = {}
    rows: list[AiListScore] = []
    finished = 0
    for reading in readings:
        due = score_reading(db, reading, target, now=stamp, population_cache=cache)
        if due is None:
            finished += 1
        else:
            rows.extend(due)
    if stats is not None:
        stats.update(readings_checked=len(readings), readings_finished=finished)
    return rows


def _failed(day: date | None, exc: Exception) -> dict[str, Any]:
    error = f"{type(exc).__name__}: {exc}"
    print(
        f"warning: {score.SCORE_VERSION} {day.isoformat() if day else '-'} failed: {error}",
        file=sys.stderr,
        flush=True,
    )
    return {
        "status": "failed",
        "date": day.isoformat() if day else None,
        "score_version": score.SCORE_VERSION,
        "error": error,
        "records": 0,
    }


def run_ai_list_score(
    target: date | None = None, *, dry_run: bool = False
) -> dict[str, Any]:
    """Score the readings due by ``target`` (default: the latest stored session).

    Never raises: a failure is a ``warning:`` line on stderr and a ``failed``
    result, which the daily keeps on the step row only.
    """

    try:
        return _run(target, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001 - a warning, the daily goes on
        return _failed(target, exc)


def _run(target: date | None, *, dry_run: bool) -> dict[str, Any]:
    started = time.monotonic()
    with pipeline.SessionLocal() as db:
        day = target or db.scalar(
            select(MarketBar.trading_date)
            .order_by(MarketBar.trading_date.desc())
            .limit(1)
        )
        if day is None:
            return {"status": "no_data", "reason": "no_market_bars", "records": 0}
        stats: dict[str, int] = {"readings_checked": 0, "readings_finished": 0}
        rows = score_readings(db, day, stats=stats)
        counts: dict[str, int] = {}
        for row in rows:
            counts[row.scope] = counts.get(row.scope, 0) + 1
        result: dict[str, Any] = {
            "status": "success",
            "date": day.isoformat(),
            "score_version": score.SCORE_VERSION,
            "dry_run": dry_run,
            **stats,
            "rows": counts,
            "readings": sorted({row.reading_id for row in rows}),
            "records": 0 if dry_run else len(rows),
        }
        if dry_run:
            result["outcomes"] = [
                {
                    "reading_id": row.reading_id,
                    "session_date": row.session_date.isoformat(),
                    "prompt_version": row.prompt_version,
                    "role": row.role,
                    "scope": row.scope,
                    "subject": row.subject,
                    "horizon": row.horizon,
                    "outcome": row.outcome_json,
                }
                for row in rows
            ]
            db.rollback()
        else:
            db.add_all(rows)
            db.commit()
    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    return result
