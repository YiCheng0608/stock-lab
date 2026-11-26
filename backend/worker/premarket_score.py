"""Scoring the stored pre-market AI readings after the close (Issue #1043).

The ``premarket_score`` step of ``worker.cli daily`` (last, non-blocking) and
``worker.cli premarket-score``.  Every ``done`` reading (each trading day,
prompt version and role) gets, under ``app.premarket_score.SCORE_VERSION``
(docs/spec/premarket_ai.md 對答案):

* ``market``: its stance against TAIEX from D's open, ``d0`` and ``t5``;
* ``stock``: each pool stock's D-open hold and, for a today-list stock with
  rule levels, its ``tracking_v2`` result on the original levels and, for
  ``reprice``, on the levels re-priced at D's open (``t5``, ``t20``);
* ``overall``: the AI and rule versions against the population and the AI's
  value (``t5``, ``t20``).

A horizon is written once its last session is stored (up to the target date)
and never again: a row already there for the reading, scope, subject, horizon
and score version is left as it is, so a rerun of the same day writes
nothing.  Nothing after the target date is read.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import premarket_score as score
from app.clock import utcnow
from app.indicators import is_synthetic_bar
from app.models import (
    CorporateAction,
    Instrument,
    MarketBar,
    PremarketAiReading,
    PremarketAiScore,
    PremarketAiStock,
)
from app.premarket_ai import DONE
from app.tracking import TRACKING_RULES_V2, TrackBar, settle, track_path
from worker import pipeline

TAIEX_SYMBOL = "TAIEX"
MAX_SESSIONS = max(score.STOCK_HORIZONS.values())


def _sessions(db: Session, list_date: date, target: date) -> list[date]:
    """The market sessions after the list date up to the target (D first)."""

    return pipeline.taiwan_bar_dates(
        db, end=target, after=list_date, limit=MAX_SESSIONS
    )


def _taiex(db: Session) -> Instrument | None:
    return db.scalar(
        select(Instrument)
        .where(Instrument.symbol == TAIEX_SYMBOL, Instrument.instrument_type == "index")
        .order_by(Instrument.id)
        .limit(1)
    )


def _bar(db: Session, instrument_id: int, day: date) -> MarketBar | None:
    return db.scalar(
        select(MarketBar).where(
            MarketBar.instrument_id == instrument_id, MarketBar.trading_date == day
        )
    )


def market_rows(
    db: Session, reading: PremarketAiReading, sessions: list[date], horizon: str
) -> dict[str, Any]:
    market = (reading.output_json or {}).get("market") or {}
    stance, confidence = market.get("stance"), market.get("confidence")
    if sessions[0] != reading.session_date:
        return score.market_outcome(
            stance, confidence, horizon, None, None, None, missing=score.NO_SESSION
        )
    end = sessions[score.MARKET_HORIZONS[horizon] - 1]
    taiex = _taiex(db)
    first = _bar(db, taiex.id, sessions[0]) if taiex else None
    last = _bar(db, taiex.id, end) if taiex else None
    missing = None
    if (
        first is None
        or first.open is None
        or first.price_reason is not None
        or is_synthetic_bar(first.source, first.turnover_reason)
    ):
        missing = score.NO_OPEN
    elif last is None:
        missing = score.NO_CLOSE
    return score.market_outcome(
        stance,
        confidence,
        horizon,
        first.open if first is not None and missing is None else None,
        last.close if last is not None else None,
        end,
        missing=missing,
    )


def stock_outcome(
    db: Session,
    reading: PremarketAiReading,
    row: PremarketAiStock,
    sessions: list[date],
    horizon: int,
) -> dict[str, Any]:
    """One pool stock of a reading at T+``horizon``."""

    _bars, tracked = pipeline._tracking_inputs(
        db,
        row.instrument_id,
        reading.list_date,
        evaluation_cutoff=sessions[horizon - 1],
    )
    out: dict[str, Any] = {
        "symbol": row.symbol,
        "action": row.action,
        "effective_action": row.action,
        "on_today_list": row.on_today_list,
        "open_hold": score.open_hold(tracked, sessions, horizon),
        "levels": None,
    }
    levels = row.levels_json
    if not score.has_levels(levels):
        return out
    original = (
        settle(
            track_path(score.original_levels(levels), tracked, rules=TRACKING_RULES_V2),
            horizon,
        )
        if tracked
        else None
    )
    part: dict[str, Any] = {
        "original": score.settled(original)
        or {"status": "incomparable", "reason": score.MISSING_BAR},
        "repriced": None,
        "repriced_result": None,
    }
    if row.action == score.REPRICE:
        first = tracked[0] if tracked else None
        on_d = first is not None and first.trading_date == reading.session_date
        previous = _bar(db, row.instrument_id, reading.list_date)
        repriced = score.reprice(
            levels,
            row.reprice_rule_json,
            first.open / first.factor if on_d and first.factor else None,
            previous.close if previous is not None else None,
        )
        part["repriced"] = repriced
        out["effective_action"] = score.effective_action(row.action, repriced)
        if repriced["status"] == score.REPRICED:
            part["repriced_result"] = _repriced_result(tracked, repriced, horizon)
    out["levels"] = part
    return out


def _repriced_result(
    tracked: list[TrackBar], repriced: dict[str, Any], horizon: int
) -> dict[str, Any]:
    """``tracking_v2`` from a fill at D's open (``reprice`` only runs when D has a bar)."""

    if score.suspended(tracked[0]):
        return {"status": "incomparable", "reason": score.SUSPENDED_IN_WINDOW}
    path = track_path(score.repriced_levels(repriced), tracked, rules=TRACKING_RULES_V2)
    return score.settled(settle(path, horizon))


def population(
    db: Session, list_date: date, sessions: list[date], horizon: int
) -> dict[str, Any]:
    """The D-open hold of every stock／ipo with a D bar not suspended, equal weight."""

    day, end = sessions[0], sessions[horizon - 1]
    members = (
        select(MarketBar.instrument_id)
        .join(Instrument, Instrument.id == MarketBar.instrument_id)
        .where(
            Instrument.instrument_type.in_(score.POPULATION_TYPES),
            MarketBar.trading_date == day,
        )
    )
    rows = db.scalars(
        select(MarketBar)
        .where(
            MarketBar.instrument_id.in_(members),
            MarketBar.trading_date >= day,
            MarketBar.trading_date <= end,
        )
        .order_by(MarketBar.instrument_id, MarketBar.trading_date)
    ).all()
    by_instrument: dict[int, list[MarketBar]] = {}
    for bar in rows:
        by_instrument.setdefault(bar.instrument_id, []).append(bar)
    with_actions = set(
        db.scalars(
            select(CorporateAction.instrument_id)
            .where(
                CorporateAction.instrument_id.in_(members),
                CorporateAction.action_date > list_date,
                CorporateAction.action_date <= end,
            )
            .distinct()
        )
    )
    results = []
    for instrument_id, bars in by_instrument.items():
        if instrument_id in with_actions:
            _raw, tracked = pipeline._tracking_inputs(
                db, instrument_id, list_date, evaluation_cutoff=end
            )
        else:
            tracked = [pipeline._track_bar(bar, 1.0, False, False) for bar in bars]
        if not tracked or tracked[0].trading_date != day or score.suspended(tracked[0]):
            continue
        results.append(score.open_hold(tracked, sessions, horizon))
    out = score.summary(results)
    out["members"] = out.pop("n")
    return out


def _existing(db: Session, reading_id: int) -> set[tuple[str, str, str]]:
    return {
        (row.scope, row.subject, row.horizon)
        for row in db.scalars(
            select(PremarketAiScore).where(
                PremarketAiScore.reading_id == reading_id,
                PremarketAiScore.score_version == score.SCORE_VERSION,
            )
        )
    }


def score_reading(
    db: Session,
    reading: PremarketAiReading,
    target: date,
    *,
    now: datetime,
    population_cache: dict[tuple[date, int], dict[str, Any]],
) -> list[PremarketAiScore]:
    """The rows of one reading that are due by ``target`` and not yet written."""

    sessions = _sessions(db, reading.list_date, target)
    if not sessions:
        return []
    have = _existing(db, reading.id)
    rows: list[PremarketAiScore] = []

    def add(scope: str, subject: str, horizon: str, outcome, stock_id=None):
        rows.append(
            PremarketAiScore(
                reading_id=reading.id,
                stock_id=stock_id,
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

    no_session = sessions[0] != reading.session_date
    for horizon, length in score.MARKET_HORIZONS.items():
        key = (score.MARKET, score.MARKET, horizon)
        if key in have or (len(sessions) < length and not no_session):
            continue
        add(
            score.MARKET,
            score.MARKET,
            horizon,
            market_rows(db, reading, sessions, horizon),
        )
    stocks = list(
        db.scalars(
            select(PremarketAiStock)
            .where(PremarketAiStock.reading_id == reading.id)
            .order_by(PremarketAiStock.position)
        )
    )
    pool = (reading.input_json or {}).get("pool") or {}
    for horizon, length in score.STOCK_HORIZONS.items():
        wanted = [(score.STOCK, row.symbol, horizon) for row in stocks]
        wanted.append((score.OVERALL, score.OVERALL, horizon))
        if all(key in have for key in wanted):
            continue
        if no_session:
            key = (score.OVERALL, score.OVERALL, horizon)
            if key not in have:
                add(
                    score.OVERALL,
                    score.OVERALL,
                    horizon,
                    {"status": score.NO_DATA, "reason": score.NO_SESSION},
                )
            continue
        if len(sessions) < length:
            continue
        outcomes = [
            (row, stock_outcome(db, reading, row, sessions, length)) for row in stocks
        ]
        for row, outcome in outcomes:
            if (score.STOCK, row.symbol, horizon) not in have:
                add(score.STOCK, row.symbol, horizon, outcome, stock_id=row.id)
        if (score.OVERALL, score.OVERALL, horizon) not in have:
            cache_key = (reading.session_date, length)
            if cache_key not in population_cache:
                population_cache[cache_key] = population(
                    db, reading.list_date, sessions, length
                )
            overall = score.overall_outcome(
                [outcome for _row, outcome in outcomes],
                population_cache[cache_key],
                pool_phase=reading.pool_phase,
                today_list_count=pool.get("today_list_count"),
            )
            overall["reading_id"] = reading.id
            add(score.OVERALL, score.OVERALL, horizon, overall)
    return rows


def score_readings(
    db: Session, target: date, *, now: datetime | None = None
) -> list[PremarketAiScore]:
    """Every due, unwritten row of the done readings through ``target`` (added, not committed)."""

    stamp = now or utcnow()
    readings = db.scalars(
        select(PremarketAiReading)
        .where(
            PremarketAiReading.status == DONE,
            PremarketAiReading.session_date <= target,
        )
        .order_by(
            PremarketAiReading.session_date,
            PremarketAiReading.role,
            PremarketAiReading.prompt_version,
            PremarketAiReading.id,
        )
    ).all()
    cache: dict[tuple[date, int], dict[str, Any]] = {}
    rows: list[PremarketAiScore] = []
    for reading in readings:
        rows.extend(
            score_reading(db, reading, target, now=stamp, population_cache=cache)
        )
    return rows


def run_premarket_score(
    target: date | None = None, *, dry_run: bool = False
) -> dict[str, Any]:
    """Score the readings due by ``target`` (default: the latest stored session)."""

    started = time.monotonic()
    with pipeline.SessionLocal() as db:
        day = target or db.scalar(
            select(MarketBar.trading_date)
            .order_by(MarketBar.trading_date.desc())
            .limit(1)
        )
        if day is None:
            return {"status": "no_data", "reason": "no_market_bars", "records": 0}
        readings = db.scalar(
            select(PremarketAiReading.id)
            .where(PremarketAiReading.status == DONE)
            .limit(1)
        )
        rows = score_readings(db, day) if readings is not None else []
        counts: dict[str, int] = {}
        for row in rows:
            counts[row.scope] = counts.get(row.scope, 0) + 1
        result: dict[str, Any] = {
            "status": "success",
            "date": day.isoformat(),
            "score_version": score.SCORE_VERSION,
            "dry_run": dry_run,
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
