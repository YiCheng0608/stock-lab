"""Stored daily action tiers: write after the daily, read on the pages (#476).

``decision.daily_action_tiers`` (the day's data half of the action tiers) is
stored per trading day in ``action_tier_snapshots`` with the fingerprint of
the inputs it was computed from.  The dashboard and the action list read it
and apply holdings, the watchlist and names live
(``decision.compose_action_tier_rows``); without a row for the day, or when
the inputs changed since (a daily rerun, a manual analyze, candidates or
strategy-levels, a version bump of the rules, membership or instrument
changes), they compute the tiers live and say so in ``source``.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .candidate_runs import read_run as read_candidate_run
from .clock import utcnow
from .config import MAX_GROUP_CANDIDATES
from .decision import (
    ACTION_NEAR_PRICE_GAP,
    ACTION_NEAR_SILENT_KINDS,
    ACTION_NEAR_UNMET_KINDS,
    ACTION_TIER_BAR_SESSIONS,
    ACTION_TIER_VERSION,
    ActionTierRow,
    DailyTier,
    compose_action_tier_rows,
    daily_action_tiers,
)
from .domain import CANDIDATE_SCORE_VERSION, ETF_CATEGORIES, STRATEGY_LEVELS_VERSION
from .fingerprints import aggregate, digest, taxonomy_digest
from .models import ActionTierSnapshot
from .strategies import NEWER_VERSIONS, REGISTRY

# Bump when daily_action_tiers (or what it reads) changes in a way the basis
# below does not show, e.g. a new input table: stored days then stop matching
# and the pages compute live until ``worker.cli action-tiers`` rewrites them.
ACTION_TIER_STORE_VERSION = "action_tier_store_v1"
# DailyTier fields in rows_json order, after the instrument id.
_FIELDS = (
    "tier",
    "candidate_rank",
    "candidate_score",
    "group_rank",
    "unmet_conditions",
    "price_gap",
    "nearness",
)
# How far back the group scores' JSON is summed: _latest_group_scores reads
# each group's newest score on or before the day, which is that day for every
# scored group; older rows count by number, id and rank.
_GROUP_DETAIL_DAYS = 14

_SIGNALS = (
    "SELECT count(*), max(id), total(strategy_version_id), "
    "total(CASE WHEN status = 'conditional' THEN id END), "
    "total(CASE WHEN status = 'observation' THEN id END), "
    "total(CASE WHEN data_quality = 'complete' THEN id END), "
    "total(instrument_id), total(length(signal_key)) "
    "FROM signals WHERE signal_date = :day"
)
_STRATEGY_VERSIONS = (
    "SELECT count(*), max(id), total(length(name)), total(length(version)), "
    "total(length(formula_version)) FROM strategy_versions"
)
_LEVELS = (
    "SELECT count(*), max(levels.id), max(levels.computed_at), "
    "total(length(levels.availability)), total(length(levels.conditions_json)), "
    "total(levels.reachable_next_session) "
    "FROM strategy_levels AS levels JOIN signals ON signals.id = levels.signal_id "
    "WHERE signals.signal_date = :day AND levels.levels_version = :version"
)
_CANDIDATES = (
    "SELECT count(*), total(rank), total(instrument_id), total(total_score) "
    "FROM daily_candidates WHERE candidate_run_id = :run"
)
_GROUP_SCORES = (
    "SELECT count(*), max(id), total(rank), total(eligible_members), "
    "total(length(data_quality)) FROM group_daily_scores WHERE trading_date <= :day"
)
_GROUP_DETAILS = (
    "SELECT total(length(details_json)), total(score) FROM group_daily_scores "
    "WHERE trading_date BETWEEN :start AND :day"
)
_EVENTS = (
    "SELECT count(*), max(id), total(instrument_id) FROM events "
    "WHERE instrument_id IS NOT NULL AND event_date BETWEEN :start AND :day"
)
_BARS = "SELECT max(id) FROM market_bars"


def action_tier_basis(db: Session, as_of: date) -> dict[str, Any]:
    """The inputs of ``daily_action_tiers(db, as_of)``, as cheap aggregates."""

    day = as_of.isoformat()
    run = read_candidate_run(db, as_of)
    return {
        "versions": {
            "store": ACTION_TIER_STORE_VERSION,
            "tier": ACTION_TIER_VERSION,
            "levels": STRATEGY_LEVELS_VERSION,
            "candidate_score": CANDIDATE_SCORE_VERSION,
            "registry": sorted(REGISTRY),
            "newer_versions": sorted(
                (name, sorted(newer)) for name, newer in NEWER_VERSIONS.items()
            ),
            "rules": [
                ACTION_TIER_BAR_SESSIONS,
                sorted(ACTION_NEAR_PRICE_GAP.items()),
                list(ACTION_NEAR_UNMET_KINDS),
                list(ACTION_NEAR_SILENT_KINDS),
                sorted(ETF_CATEGORIES),
                MAX_GROUP_CANDIDATES,
            ],
        },
        "signals": aggregate(db, _SIGNALS, {"day": day}),
        "strategy_versions": aggregate(db, _STRATEGY_VERSIONS),
        "levels": aggregate(
            db, _LEVELS, {"day": day, "version": STRATEGY_LEVELS_VERSION}
        ),
        "candidate_run": None
        if run is None
        else [
            run.id,
            run.status,
            str(run.computed_at),
            run.candidate_count,
            *aggregate(db, _CANDIDATES, {"run": run.id}),
        ],
        "group_scores": aggregate(db, _GROUP_SCORES, {"day": day})
        + aggregate(
            db,
            _GROUP_DETAILS,
            {
                "start": (as_of - timedelta(days=_GROUP_DETAIL_DAYS)).isoformat(),
                "day": day,
            },
        ),
        "events": aggregate(
            db,
            _EVENTS,
            {"start": (as_of - timedelta(days=7)).isoformat(), "day": day},
        ),
        "bars": aggregate(db, _BARS),
        "taxonomy": taxonomy_digest(db),
    }


def _encode(tiers: dict[int, DailyTier]) -> list[list[Any]]:
    return [
        [item_id, *(asdict(tier)[field] for field in _FIELDS)]
        for item_id, tier in sorted(tiers.items())
    ]


def _decode(rows: list[list[Any]]) -> dict[int, DailyTier]:
    return {
        int(row[0]): DailyTier(**dict(zip(_FIELDS, row[1:], strict=True)))
        for row in rows
    }


def write_action_tier_snapshot(db: Session, as_of: date) -> ActionTierSnapshot:
    """Compute the day's tiers and store them with their basis (caller commits)."""

    # The basis first, in the same transaction: the tiers then cannot be
    # newer than the fingerprint they are stored with.
    basis = action_tier_basis(db, as_of)
    tiers = daily_action_tiers(db, as_of)
    row = db.scalar(
        select(ActionTierSnapshot).where(
            ActionTierSnapshot.trading_date == as_of,
            ActionTierSnapshot.store_version == ACTION_TIER_STORE_VERSION,
        )
    )
    if row is None:
        row = ActionTierSnapshot(
            trading_date=as_of, store_version=ACTION_TIER_STORE_VERSION
        )
        db.add(row)
    row.fingerprint = digest(basis)
    row.basis_json = basis
    row.rows_json = _encode(tiers)
    row.row_count = len(tiers)
    row.computed_at = utcnow()
    db.flush()
    return row


def stored_action_tiers(
    db: Session, as_of: date | None
) -> tuple[dict[int, DailyTier] | None, dict[str, Any]]:
    """The stored tiers of ``as_of`` when still current, and where they came from.

    ``source`` is ``precomputed`` with the row's ``computed_at``, or ``live``
    with ``reason``: ``no_as_of`` (no official day), ``missing`` (no row for
    the day) or ``stale`` (the inputs changed since it was written).
    """

    if as_of is None:
        return None, {"source": "live", "reason": "no_as_of", "computed_at": None}
    row = db.scalar(
        select(ActionTierSnapshot).where(
            ActionTierSnapshot.trading_date == as_of,
            ActionTierSnapshot.store_version == ACTION_TIER_STORE_VERSION,
        )
    )
    if row is None:
        return None, {"source": "live", "reason": "missing", "computed_at": None}
    if row.fingerprint != digest(action_tier_basis(db, as_of)):
        return None, {
            "source": "live",
            "reason": "stale",
            "computed_at": row.computed_at.isoformat() + "Z",
        }
    return _decode(row.rows_json), {
        "source": "precomputed",
        "reason": None,
        "computed_at": row.computed_at.isoformat() + "Z",
    }


def read_action_tier_rows(
    db: Session, as_of: date | None
) -> tuple[list[ActionTierRow], dict[str, Any]]:
    """``decision.action_tier_rows(db, as_of)``, from the stored day when current."""

    tiers, source = stored_action_tiers(db, as_of)
    if tiers is None:
        tiers = daily_action_tiers(db, as_of)
    return compose_action_tier_rows(db, tiers), {
        "trading_date": as_of.isoformat() if as_of else None,
        **source,
    }
