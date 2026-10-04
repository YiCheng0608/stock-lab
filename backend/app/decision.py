"""Product-layer decision summaries.

The functions in this module consume persisted canonical signals and official
data.  They do not create or alter strategy rules; their job is to make the
two per-strategy results legible as one auditable action card while preserving
conflicts and data-quality blockers.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .coverage import verified_taiex_sessions
from .decision_market_reads import DecisionMarketRead, load_decision_market_reads, market_read_status
from .config import MAX_GROUP_CANDIDATES
from .domain import ETF_CATEGORIES, signal_confidence_semantics
from .level_semantics import build_level_semantics, build_stop_price_semantics, utc_now_iso
from .presentation import display_action_label, display_reason, primary_reason
from .product_time import build_action_product_time, build_signal_product_time
from .portfolio_values import read_portfolio_value
from .units import position_held
from .stock_signal_reads import StockSignalRead, load_stock_signal_reads
from .stock_independent_reads import StockChipRead, load_stock_chip_reads
from .models import (
    ChipSnapshot,
    DataQuality,
    Event,
    GroupDailyScore,
    GroupMembership,
    IngestionRun,
    Instrument,
    PortfolioPosition,
    Signal,
    StrategyVersion,
    ThemeGroup,
)


ACTION_LABELS = {
    "conditional_entry": "條件進場",
    "wait_breakout": "等待突破",
    "wait_pullback": "等待回踩",
    "hold_observe": "持有觀察",
    "reduce_exit": "減碼／退場",
    "data_insufficient": "資料不足",
    "no_condition": "暫無條件",
    "manual_review": "需人工判讀",
}


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _same_adjustment_basis(left: DecisionMarketRead, right: DecisionMarketRead) -> bool:
    """Check that two closes can be compared without inventing an adjustment.

    MarketBar keeps both raw ``close`` and the persisted ``adj_close``.  The
    ratio is a compact basis marker for feeds that provide an adjusted close;
    if either side cannot establish the same ratio, the product deliberately
    withholds a percentage change.
    """

    left_close = _finite(left.close)
    right_close = _finite(right.close)
    left_adjusted = _finite(left.adj_close)
    right_adjusted = _finite(right.adj_close)
    if None in (left_close, right_close, left_adjusted, right_adjusted):
        return False
    if min(left_close, right_close, left_adjusted, right_adjusted) <= 0:
        return False
    left_ratio = _finite(left_adjusted / left_close)
    right_ratio = _finite(right_adjusted / right_close)
    if left_ratio is None or right_ratio is None or min(left_ratio, right_ratio) <= 0:
        return False
    return math.isclose(
        left_ratio,
        right_ratio,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )


def _trusted_bar_for_display(row: DecisionMarketRead) -> bool:
    source = str(row.source or "").casefold()
    return bool(source) and not any(token in source for token in ("legacy", "demo", "fake"))


def _verified_adjacent_change(
    db: Session,
    instrument: Instrument,
    bar: DecisionMarketRead | None,
    bars: list[DecisionMarketRead],
    as_of: date | None,
) -> tuple[float | None, float | None, float | None]:
    """Return a change only for the previous verified TAIEX session.

    A bar immediately before the current row is not enough: a holiday,
    suspension, missing row, or adjustment-basis change must result in the
    explicit ``unverified`` UI state.
    """

    if bar is None or not bar.core_valid or not as_of or not _trusted_bar_for_display(bar) or bar.is_suspended:
        return None, None, None
    current_close = _finite(bar.close)
    if current_close is None or current_close <= 0:
        return None, None, None
    session_cache = db.info.setdefault("_decision_taiex_dates", {})
    session_key = bar.trading_date.isoformat()
    if session_key not in session_cache:
        session_cache[session_key] = verified_taiex_sessions(
            db,
            end_date=bar.trading_date,
            require_provenance=True,
            limit=120,
        )
    sessions = session_cache[session_key]
    try:
        index = sessions.index(bar.trading_date)
    except ValueError:
        return None, None, None
    if index <= 0:
        return None, None, None
    previous_date = sessions[index - 1]
    previous = next((row for row in bars if row.trading_date == previous_date), None)
    if previous is None or not previous.core_valid or previous.is_suspended or not _trusted_bar_for_display(previous):
        return None, None, None
    previous_close = _finite(previous.close)
    if previous_close is None or previous_close <= 0 or not _same_adjustment_basis(previous, bar):
        return None, None, None
    change = current_close - previous_close
    percent = _finite(change / previous_close)
    if _finite(change) is None or percent is None:
        return None, None, None
    return previous_close, change, percent


def _date_from_as_of(value: str | date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def latest_official_run(db: Session) -> IngestionRun | None:
    return db.scalar(
        select(IngestionRun)
        .where(IngestionRun.run_type == "collect", IngestionRun.source == "official")
        .order_by(desc(IngestionRun.updated_at), desc(IngestionRun.id))
        .limit(1)
    )


def latest_official_as_of(db: Session) -> tuple[IngestionRun | None, date | None]:
    cache = db.info.setdefault("_decision_official", {})
    if "value" in cache:
        return cache["value"]
    run = latest_official_run(db)
    value = (run, _date_from_as_of(run.data_as_of if run else None))
    cache["value"] = value
    return value


def _prepare_decision_context(
    db: Session,
    as_of: date | None,
    instrument_ids: Iterable[int],
    *, stock_research_reads: bool = False,
) -> dict[str, Any]:
    """Batch-load the read-only context shared by a page of action cards."""

    ids = {int(item_id) for item_id in instrument_ids}
    key = as_of.isoformat() if as_of else "none"
    contexts = db.info.setdefault("_decision_contexts", {})
    existing = contexts.get(key)
    if existing is not None and ids.issubset(existing["instrument_ids"]) and existing.get("stock_research_reads", False) == stock_research_reads:
        return existing
    # A larger later request replaces the context for this as-of date.  This
    # keeps direct single-instrument calls and paged API calls compatible.
    instrument_rows = db.scalars(select(Instrument).where(Instrument.id.in_(ids))).all() if ids else []
    bars_by_instrument, unlocated_bars_by_instrument = load_decision_market_reads(db, ids, as_of)

    chips_by_instrument: dict[int, list[ChipSnapshot | StockChipRead]] = defaultdict(list)
    chip_reads = load_stock_chip_reads(db, ids, as_of) if stock_research_reads else {}
    if stock_research_reads:
        chips_by_instrument.update((item_id, reads.candidates) for item_id, reads in chip_reads.items())
    elif ids:
        chip_query = select(ChipSnapshot).where(ChipSnapshot.instrument_id.in_(ids))
        if as_of:
            chip_query = chip_query.where(ChipSnapshot.trading_date <= as_of)
        for row in db.scalars(
            chip_query.order_by(ChipSnapshot.instrument_id, desc(ChipSnapshot.trading_date), desc(ChipSnapshot.id))
        ).all():
            if len(chips_by_instrument[row.instrument_id]) < 120:
                chips_by_instrument[row.instrument_id].append(row)

    signals_by_instrument: dict[int, dict[str, Signal]] = defaultdict(dict)
    strategy_versions_by_instrument: dict[int, dict[str, StrategyVersion]] = defaultdict(dict)
    research_reads = load_stock_signal_reads(db, ids, as_of) if stock_research_reads else {}
    if stock_research_reads:
        for instrument_id, reads in research_reads.items():
            for name, signal in reads.latest.items():
                signals_by_instrument[instrument_id][name] = signal
                strategy_versions_by_instrument[instrument_id][name] = signal.strategy
    elif ids:
        signal_query = (
            select(Signal, StrategyVersion)
            .join(StrategyVersion, StrategyVersion.id == Signal.strategy_version_id)
            .where(Signal.instrument_id.in_(ids))
        )
        if as_of:
            signal_query = signal_query.where(Signal.signal_date <= as_of)
        for signal, strategy_version in db.execute(
            signal_query.order_by(desc(Signal.signal_date), desc(Signal.id))
        ).all():
            if strategy_version.name in {"breakout_v1", "pullback_v1"}:
                signals_by_instrument[signal.instrument_id].setdefault(strategy_version.name, signal)
                strategy_versions_by_instrument[signal.instrument_id].setdefault(strategy_version.name, strategy_version)

    groups_by_instrument: dict[int, list[tuple[ThemeGroup, GroupDailyScore, GroupMembership]]] = defaultdict(list)
    if ids:
        group_query = (
            select(ThemeGroup, GroupDailyScore, GroupMembership)
            .join(GroupDailyScore, GroupDailyScore.group_id == ThemeGroup.id)
            .join(GroupMembership, GroupMembership.group_id == ThemeGroup.id)
            .where(
                ThemeGroup.active.is_(True),
                GroupMembership.instrument_id.in_(ids),
                GroupMembership.valid_from <= (as_of or date.max),
                (GroupMembership.valid_to.is_(None) | (GroupMembership.valid_to >= (as_of or date.max))),
                GroupDailyScore.trading_date <= (as_of or date.max),
            )
            .order_by(desc(GroupDailyScore.trading_date), desc(GroupDailyScore.id))
        )
        seen_groups: set[tuple[int, str]] = set()
        for group, score, membership in db.execute(group_query).all():
            marker = (membership.instrument_id, group.id)
            if marker in seen_groups:
                continue
            seen_groups.add(marker)
            groups_by_instrument[membership.instrument_id].append((group, score, membership))

    quality_by_key: dict[str, DataQuality] = {}
    # DataQuality is also the audit store for every daily ingestion domain and
    # can therefore be much larger than the action page.  The decision
    # summary only needs instrument-level rows for this page; loading the
    # entire 160k-row table here made an otherwise batched action request spend
    # seconds hydrating unrelated JSON blobs.
    quality_keys = [f"{row.exchange}:{row.symbol}" for row in instrument_rows]
    quality_query = select(DataQuality).where(
        DataQuality.entity_type == "instrument",
        DataQuality.entity_key.in_(quality_keys) if quality_keys else False,
    )
    if as_of:
        quality_query = quality_query.where(DataQuality.as_of_date <= as_of)
    for row in db.scalars(quality_query.order_by(desc(DataQuality.as_of_date), desc(DataQuality.id))).all():
        quality_by_key.setdefault(row.entity_key, row)

    positions_by_instrument: dict[int, PortfolioPosition] = {}
    if ids:
        for row in db.scalars(
            select(PortfolioPosition).where(PortfolioPosition.instrument_id.in_(ids))
        ).all():
            positions_by_instrument.setdefault(row.instrument_id, row)

    events_by_instrument: dict[int, list[Event]] = defaultdict(list)
    if ids:
        event_query = select(Event).where(Event.instrument_id.in_(ids))
        if as_of:
            event_query = event_query.where(Event.event_date <= as_of)
        for row in db.scalars(event_query.order_by(desc(Event.event_date), desc(Event.id))).all():
            events_by_instrument[row.instrument_id].append(row)

    context = {
        "instrument_ids": ids,
        "stock_research_reads": stock_research_reads,
        "research_reads_by_instrument": research_reads,
        "chip_reads_by_instrument": chip_reads,
        "bars_by_instrument": bars_by_instrument,
        "unlocated_bars_by_instrument": unlocated_bars_by_instrument,
        "chips_by_instrument": chips_by_instrument,
        "signals_by_instrument": signals_by_instrument,
        "strategy_versions_by_instrument": strategy_versions_by_instrument,
        "groups_by_instrument": groups_by_instrument,
        "quality_by_key": quality_by_key,
        "positions_by_instrument": positions_by_instrument,
        "events_by_instrument": events_by_instrument,
        "instruments": {row.id: row for row in instrument_rows},
    }
    contexts[key] = context
    return context


def _latest_bar(db: Session, instrument_id: int, as_of: date | None) -> DecisionMarketRead | None:
    context = db.info.get("_decision_contexts", {}).get(as_of.isoformat() if as_of else "none")
    if context and instrument_id in context["instrument_ids"]:
        rows = context["bars_by_instrument"].get(instrument_id, [])
        return context["unlocated_bars_by_instrument"].get(instrument_id) or (rows[0] if rows else None)
    rows_by_id, unlocated = load_decision_market_reads(db, [instrument_id], as_of, limit=1)
    rows = rows_by_id[instrument_id]
    return unlocated.get(instrument_id) or (rows[0] if rows else None)


def _bars(db: Session, instrument_id: int, as_of: date | None, limit: int = 120) -> list[DecisionMarketRead]:
    context = db.info.get("_decision_contexts", {}).get(as_of.isoformat() if as_of else "none")
    if context and instrument_id in context["instrument_ids"]:
        return list(reversed(context["bars_by_instrument"].get(instrument_id, [])[:limit]))
    rows_by_id, _unlocated = load_decision_market_reads(db, [instrument_id], as_of, limit=limit)
    return list(reversed(rows_by_id[instrument_id]))


def _instrument_coverage(
    db: Session,
    instrument: Instrument,
    as_of: date | None,
    bars: list[DecisionMarketRead],
) -> dict[str, Any]:
    """Return as-of effective bar/chip gaps for product decisions.

    The calculation uses verified TAIEX dates as the session denominator and
    applies the instrument listing date before measuring 20/60-day readiness.
    It intentionally does not use calendar days or the number of rows in a
    broad market scan.
    """

    def unknown_coverage() -> dict[str, Any]:
        return {
            "coverage_status": "unknown",
            "verified_taiex_sessions": None,
            "eligible_sessions": None,
            "effective_bar_sessions": None,
            "effective_chip_sessions": None,
            "missing_bars_to_20": None,
            "missing_bars_to_60": None,
            "missing_chips_to_20": None,
            "missing_chips_to_60": None,
            "missing_bar_dates_to_20": [],
            "missing_bar_dates_to_60": [],
            "missing_chip_dates_to_20": [],
            "missing_chip_dates_to_60": [],
            "coverage_reasons": ["coverage_baseline_unknown"],
            "ipo_stage": None,
        }

    if not as_of:
        return unknown_coverage()

    cache = db.info.setdefault("_decision_taiex_dates", {})
    cache_key = as_of.isoformat()
    if cache_key not in cache:
        cache[cache_key] = verified_taiex_sessions(
            db,
            end_date=as_of,
            require_provenance=True,
            limit=120,
        )
    sessions = list(dict.fromkeys(cache[cache_key]))
    if not sessions:
        return unknown_coverage()
    eligible_sessions = [
        trading_date
        for trading_date in sessions
        if instrument.listing_date is None or trading_date >= instrument.listing_date
    ]
    bar_dates = {
        row.trading_date
        for row in bars
        if row.core_valid and (instrument.listing_date is None or row.trading_date >= instrument.listing_date)
    }
    context = db.info.get("_decision_contexts", {}).get(as_of.isoformat())
    if context and instrument.id in context["instrument_ids"]:
        chip_dates = {row.trading_date for row in context["chips_by_instrument"].get(instrument.id, [])
                      if not context.get("stock_research_reads") or row.core_valid}
    else:
        chip_dates = set(
            db.scalars(
                select(ChipSnapshot.trading_date)
                .where(
                    ChipSnapshot.instrument_id == instrument.id,
                    ChipSnapshot.trading_date <= as_of,
                )
                .order_by(desc(ChipSnapshot.trading_date), desc(ChipSnapshot.id))
                .limit(120)
            ).all()
        )
    bar_dates &= set(eligible_sessions)
    chip_dates &= set(eligible_sessions)
    suspension_cache = db.info.setdefault("_decision_suspension_dates", {})
    if instrument.id not in suspension_cache:
        if context and instrument.id in context["instrument_ids"]:
            event_rows = context["events_by_instrument"].get(instrument.id, [])
        else:
            event_rows = db.scalars(
                select(Event).where(
                    Event.instrument_id == instrument.id,
                    Event.event_date <= as_of,
                )
            ).all()
        suspension_cache[instrument.id] = {
            event.event_date
            for event in event_rows
            if any(
                token in (event.event_type or "").casefold()
                for token in ("suspension", "停牌")
            )
        }
    suspension_dates = set(suspension_cache[instrument.id])
    missing_bars: dict[str, int] = {}
    missing_chips: dict[str, int] = {}
    missing_bar_dates: dict[str, list[str]] = {}
    missing_chip_dates: dict[str, list[str]] = {}
    for horizon in (20, 60):
        window = eligible_sessions[-horizon:]
        missing_bar_dates[horizon] = sorted(
            day.isoformat() for day in set(window) - bar_dates
        )
        missing_chip_dates[horizon] = sorted(
            day.isoformat() for day in set(window) - chip_dates
        )
        missing_bars[horizon] = (
            max(0, horizon - len(bar_dates))
            if len(eligible_sessions) < horizon
            else len(missing_bar_dates[horizon])
        )
        missing_chips[horizon] = (
            max(0, horizon - len(chip_dates))
            if len(eligible_sessions) < horizon
            else len(missing_chip_dates[horizon])
        )
    reasons: list[str] = []
    if not sessions:
        reasons.append("missing_taiex")
    if missing_bars[20] or missing_bars[60]:
        missing_days = {
            date.fromisoformat(item)
            for values in missing_bar_dates.values()
            for item in values
        }
        if missing_days.intersection(suspension_dates):
            reasons.append("suspended_or_no_trade")
        elif instrument.instrument_type == "ipo" and len(bar_dates) < 60:
            reasons.append("listed_under_threshold")
        else:
            reasons.append("missing_bar_dates")
    if missing_chips[20] or missing_chips[60]:
        reasons.append("missing_chips")
    if instrument.instrument_type == "etf" and instrument.etf_category in {"bond", "leveraged", "inverse"}:
        reasons.append("etf_not_general_action_eligible")
    if instrument.instrument_type == "ipo":
        ipo_stage = (
            "not_observable" if len(bar_dates) < 20
            else "observation_only" if len(bar_dates) < 60
            else "actionable_eligible"
        )
    else:
        ipo_stage = None
    return {
        "coverage_status": "verified",
        "verified_taiex_sessions": len(sessions),
        "eligible_sessions": len(eligible_sessions),
        "effective_bar_sessions": len(bar_dates),
        "effective_chip_sessions": len(chip_dates),
        "missing_bars_to_20": missing_bars[20],
        "missing_bars_to_60": missing_bars[60],
        "missing_chips_to_20": missing_chips[20],
        "missing_chips_to_60": missing_chips[60],
        "missing_bar_dates_to_20": missing_bar_dates[20],
        "missing_bar_dates_to_60": missing_bar_dates[60],
        "missing_chip_dates_to_20": missing_chip_dates[20],
        "missing_chip_dates_to_60": missing_chip_dates[60],
        "coverage_reasons": list(dict.fromkeys(reasons)),
        "ipo_stage": ipo_stage,
    }


def _latest_strategy_signals(db: Session, instrument_id: int, as_of: date | None) -> dict[str, Signal]:
    context = db.info.get("_decision_contexts", {}).get(as_of.isoformat() if as_of else "none")
    if context and instrument_id in context["instrument_ids"]:
        return dict(context["signals_by_instrument"].get(instrument_id, {}))
    query = (
        select(Signal, StrategyVersion.name)
        .join(StrategyVersion, StrategyVersion.id == Signal.strategy_version_id)
        .where(Signal.instrument_id == instrument_id)
    )
    if as_of:
        query = query.where(Signal.signal_date <= as_of)
    rows = db.execute(query.order_by(desc(Signal.signal_date), desc(Signal.id))).all()
    result: dict[str, Signal] = {}
    for signal, name in rows:
        if name in {"breakout_v1", "pullback_v1"}:
            result.setdefault(name, signal)
    return result


def _chips_complete(db: Session, instrument_id: int, as_of: date | None) -> tuple[bool, list[str], list[ChipSnapshot | StockChipRead]]:
    context = db.info.get("_decision_contexts", {}).get(as_of.isoformat() if as_of else "none")
    if context and instrument_id in context["instrument_ids"]:
        rows = list(reversed(context["chips_by_instrument"].get(instrument_id, [])[:5]))
    else:
        query = select(ChipSnapshot).where(ChipSnapshot.instrument_id == instrument_id)
        if as_of:
            query = query.where(ChipSnapshot.trading_date <= as_of)
        rows = list(
            reversed(
                db.scalars(
                    query.order_by(desc(ChipSnapshot.trading_date), desc(ChipSnapshot.id)).limit(5)
                ).all()
            )
        )
    missing: list[str] = []
    raw_scope = context.get("chip_reads_by_instrument", {}).get(instrument_id) if context else None
    if raw_scope and (raw_scope.unlocated_count or any(not row.core_valid for row in rows)):
        missing.append("institutional_flow_5d")
    if len({row.trading_date for row in rows}) < 5:
        missing.append("institutional_flow_5d")
    for field in ("foreign_buy", "trust_buy", "dealer_buy", "margin_balance", "margin_change"):
        if len(rows) < 5 or any(_finite(getattr(row, field)) is None for row in rows):
            missing.append(field)
    return not missing, list(dict.fromkeys(missing)), rows


def _effective_groups_for_instrument(db: Session, instrument_id: int, as_of: date | None) -> list[tuple[ThemeGroup, GroupDailyScore, GroupMembership]]:
    if not as_of:
        return []
    context = db.info.get("_decision_contexts", {}).get(as_of.isoformat())
    if context and instrument_id in context["instrument_ids"]:
        return list(context["groups_by_instrument"].get(instrument_id, []))
    rows = db.execute(
        select(ThemeGroup, GroupDailyScore, GroupMembership)
        .join(GroupDailyScore, GroupDailyScore.group_id == ThemeGroup.id)
        .join(GroupMembership, GroupMembership.group_id == ThemeGroup.id)
        .where(
            ThemeGroup.active.is_(True),
            GroupMembership.instrument_id == instrument_id,
            GroupMembership.valid_from <= as_of,
            (GroupMembership.valid_to.is_(None) | (GroupMembership.valid_to >= as_of)),
            GroupDailyScore.trading_date <= as_of,
        )
        .order_by(desc(GroupDailyScore.trading_date), desc(GroupDailyScore.id))
    ).all()
    result: list[tuple[ThemeGroup, GroupDailyScore, GroupMembership]] = []
    seen: set[str] = set()
    for group, score, membership in rows:
        if group.id in seen:
            continue
        seen.add(group.id)
        result.append((group, score, membership))
    return result


def _qualified_groups_for_instrument(db: Session, instrument: Instrument, as_of: date | None) -> list[tuple[ThemeGroup, GroupDailyScore, GroupMembership]]:
    result = []
    for group, score, membership in _effective_groups_for_instrument(db, instrument.id, as_of):
        details = score.details_json or {}
        leaderboard = details.get("leaderboard")
        # ETF and company leaderboards are deliberately not mixed.  The group
        # score itself also has to be complete; a non-null score is not enough.
        expected_etf = instrument.instrument_type == "etf"
        if expected_etf != (group.group_type == "etf"):
            continue
        if score.data_quality != "complete" or (score.eligible_members or 0) < 3:
            continue
        if score.rank is None or details.get("benchmark") != "TAIEX":
            continue
        if expected_etf and leaderboard not in {None, "etf"}:
            continue
        if not expected_etf and leaderboard == "etf":
            continue
        result.append((group, score, membership))
    return result


def _signal_levels(signal: Signal, strategy_name: str) -> dict[str, float | None]:
    return {
        "trigger_price": _finite(signal.breakout_price if strategy_name == "breakout_v1" else signal.reference_entry),
        "entry_low": _finite(signal.pullback_low if strategy_name == "pullback_v1" else None),
        "entry_high": _finite(signal.pullback_high if strategy_name == "pullback_v1" else None),
        "invalid_price": _finite(signal.invalid_price),
        "target_1": _finite(signal.target_1),
        "target_2": _finite(signal.target_2),
    }


def _risk_reward(signal: Signal, levels: dict[str, float | None]) -> float | None:
    evidence = signal.rule_evidence_json if isinstance(signal, StockSignalRead) else signal.rule_evidence_json or {}
    candidates = [] if isinstance(signal, StockSignalRead) and evidence is None else [
        evidence.get("risk_reward"),
        evidence.get("risk_reward_ratio"),
        (evidence.get("levels") or {}).get("risk_reward") if isinstance(evidence.get("levels"), dict) else None,
    ]
    for candidate in candidates:
        value = _finite(candidate)
        if value is not None:
            return value
    entry = levels.get("trigger_price") or levels.get("entry_high") or levels.get("entry_low")
    stop = levels.get("invalid_price")
    target = levels.get("target_1")
    if entry is None or stop is None or target is None or entry <= stop or target <= entry:
        return None
    ratio = (target - entry) / (entry - stop)
    return _finite(ratio) if isinstance(signal, StockSignalRead) else ratio


def _strategy_result(
    signal: Signal | None,
    name: str,
    as_of: date | None,
    *,
    strategy_version: StrategyVersion | None = None,
    response_generated_at: str | None = None,
) -> dict[str, Any] | None:
    if not signal:
        return None
    levels = _signal_levels(signal, name)
    missing: list[str] = []
    signal_read = signal.read_state() if isinstance(signal, StockSignalRead) else None
    if signal_read and signal_read["status"] != "known":
        missing.append("signal_read_" + signal_read["status"])
    if signal.data_quality != "complete":
        missing.append("signal_data_quality")
    if signal.status in {"data_incomplete", "invalid_levels"}:
        missing.append(signal.status)
    required_level_keys = (
        ("trigger_price", "invalid_price", "target_1")
        if name == "breakout_v1"
        else ("entry_low", "entry_high", "invalid_price", "target_1")
    )
    level_missing: list[str] = []
    for key in required_level_keys:
        value = levels.get(key)
        if value is None:
            level_missing.append(key)
    rr = _risk_reward(signal, levels)
    if rr is None or rr < 1.5:
        level_missing.append("risk_reward")
    # Observation is a valid, complete rule result even when the rule did not
    # produce a trigger/entry/target.  Those absent levels describe why there
    # is no waiting instruction; they are not missing source data.  Conditional
    # and incomplete results still treat the same fields as hard blockers.
    complete_observation = signal.status == "observation" and signal.data_quality == "complete"
    wait_missing = list(dict.fromkeys(level_missing)) if complete_observation else []
    if not complete_observation:
        missing.extend(level_missing)
    if as_of and signal.data_cutoff and str(signal.data_cutoff)[:10] > as_of.isoformat():
        missing.append("data_cutoff")
    evidence = signal.rule_evidence_json if isinstance(signal, StockSignalRead) else signal.rule_evidence_json or {}
    evidence_strategy_version = None if isinstance(signal, StockSignalRead) and evidence is None else (
        evidence.get("strategy_version") if isinstance(evidence.get("strategy_version"), str) else None
    )
    confidence_semantics = signal_confidence_semantics(
        signal.confidence,
        evidence,
        strategy_name=name,
        strategy_version=evidence_strategy_version,
    )
    level_semantics = build_level_semantics(
        strategy_name=name,
        strategy_version=strategy_version.version if strategy_version else None,
        field_mapping=(
            {
                "trigger_price": "breakout_price",
                "invalid_price": "invalid_price",
                "target_1": "target_1",
                "target_2": "target_2",
            }
            if name == "breakout_v1"
            else {
                "trigger_price": "reference_entry",
                "entry_low": "pullback_low",
                "entry_high": "pullback_high",
                "invalid_price": "invalid_price",
                "target_1": "target_1",
                "target_2": "target_2",
            }
        ),
        response_generated_at=response_generated_at,
    )
    product_time = build_signal_product_time(
        signal,
        response_generated_at=response_generated_at,
    )
    inputs = evidence.get("inputs") if isinstance(evidence, dict) and isinstance(evidence.get("inputs"), dict) else {}
    for field in (
        "group_excess_return_20d",
        "institutional_flow_to_turnover_ratio_5d",
        "margin_balance_change_ratio_5d",
    ):
        if field in inputs and _finite(inputs.get(field)) is None:
            missing.append(field)
    return {
        "strategy": name,
        "signal_id": signal.id,
        "signal_key": signal.signal_key,
        "signal_date": None if isinstance(signal, StockSignalRead) and signal.signal_date is None else signal.signal_date.isoformat(),
        "status": signal.status,
        "data_quality": signal.data_quality,
        "rationale": signal.rationale,
        "levels": levels,
        "risk_reward": rr,
        "confidence_semantics": confidence_semantics,
        "level_semantics": level_semantics,
        "product_time": product_time,
        "response_generated_at": product_time["response_generated_at"],
        "earliest_execution_date": signal.earliest_execution_date.isoformat() if signal.earliest_execution_date else None,
        "missing": list(dict.fromkeys(missing)),
        "wait_missing": wait_missing,
        "evidence": evidence,
        **({"signal_read": signal_read} if signal_read is not None else {}),
    }


def _strategy_has_valid_levels(result: dict[str, Any] | None) -> bool:
    return bool(
        result
        and not result.get("missing")
        and result.get("status") in {"conditional", "observation"}
        and (result.get("status") != "observation" or not result.get("wait_missing"))
    )


def _strategy_is_actionable(result: dict[str, Any] | None) -> bool:
    """Return whether one persisted strategy can drive an action card.

    A strategy result is the canonical unit of actionability.  The other
    strategy is useful context, but its optional/observation-only levels must
    not invalidate a complete conditional setup.
    """

    return bool(
        result
        and result.get("status") == "conditional"
        and result.get("data_quality") == "complete"
        and not result.get("missing")
    )


def _group_ids_and_blockers(
    db: Session, instrument: Instrument, as_of: date | None
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    groups = _effective_groups_for_instrument(db, instrument.id, as_of)
    qualified = _qualified_groups_for_instrument(db, instrument, as_of)
    group_ids = [group.id for group, _score, _membership in groups]
    if not groups:
        return [], ["theme_membership"], []
    if not qualified:
        return group_ids, ["qualified_theme"], []
    evidence = [
        {
            "theme_id": group.id,
            "trading_date": score.trading_date.isoformat(),
            "benchmark": (score.details_json or {}).get("benchmark"),
            "data_quality": score.data_quality,
            "eligible_members": score.eligible_members,
            "relative_return_20d": score.relative_return_20d,
        }
        for group, score, _membership in qualified
    ]
    return [group.id for group, _score, _membership in qualified], [], evidence


def _quality_blockers(db: Session, instrument: Instrument, as_of: date | None) -> list[str]:
    if not as_of:
        return ["data_as_of"]
    context = db.info.get("_decision_contexts", {}).get(as_of.isoformat())
    if context and instrument.id in context["instrument_ids"]:
        quality = context["quality_by_key"].get(f"{instrument.exchange}:{instrument.symbol}")
    else:
        quality = db.scalar(
            select(DataQuality)
            .where(
                DataQuality.entity_type == "instrument",
                DataQuality.entity_key == f"{instrument.exchange}:{instrument.symbol}",
                DataQuality.as_of_date <= as_of,
            )
            .order_by(desc(DataQuality.as_of_date), desc(DataQuality.id))
            .limit(1)
        )
    if quality and quality.status in {"missing", "partial", "insufficient", "data_incomplete"}:
        return list(quality.missing_fields_json or [])
    return []


def _priority_missing(fields: Iterable[str], *, held: bool) -> list[dict[str, str]]:
    priority_by_field = {
        "data_as_of": "market_base",
        "market_bar": "market_base",
        "bars_20d": "market_base",
        "bars_60d": "market_base",
        "benchmark": "theme_discovery",
        "theme_membership": "theme_discovery",
        "qualified_theme": "theme_discovery",
        "institutional_flow_5d": "hot_candidate",
        "foreign_buy": "hot_candidate",
        "trust_buy": "hot_candidate",
        "dealer_buy": "hot_candidate",
        "margin_balance": "hot_candidate",
        "margin_change": "hot_candidate",
        "risk_reward": "action_validation",
        "invalid_price": "action_validation",
        "target_1": "action_validation",
        "signal_data_quality": "action_validation",
        "signal": "action_validation",
    }
    labels = {
        "market_base": "市場基礎層",
        "theme_discovery": "族群發現",
        "hot_candidate": "熱門候選",
        "action_validation": "行動驗證",
    }
    result = []
    for field in dict.fromkeys(str(item) for item in fields if item):
        priority = priority_by_field.get(field, "action_validation")
        if held and priority == "action_validation":
            priority = "持倉風險"
        result.append({"field": field, "priority": priority, "priority_label": labels.get(priority, priority), "reason": "尚未取得足以支持此用途的完整資料"})
    return result


def build_decision_summary(db: Session, instrument: Instrument, as_of: date | None = None, *, stock_research_reads: bool = False) -> dict[str, Any]:
    run, official_as_of = latest_official_as_of(db)
    if as_of is None:
        as_of = official_as_of
    _prepare_decision_context(db, as_of, [instrument.id], stock_research_reads=stock_research_reads)
    context = db.info.get("_decision_contexts", {}).get(as_of.isoformat() if as_of else "none")
    if context and instrument.id in context["instrument_ids"]:
        held_position = context["positions_by_instrument"].get(instrument.id)
    else:
        held_position = db.scalar(select(PortfolioPosition).where(PortfolioPosition.instrument_id == instrument.id))
    held = position_held(held_position.shares, held_position.shares_integer) if held_position else False
    quantity_status = "absent" if held_position is None else "unknown" if held is None else "known"
    unknown_quantity = quantity_status == "unknown"
    position_stop, position_stop_status = read_portfolio_value(held_position.stop_price if held_position else None)
    invalid_held_stop = held and position_stop_status == "invalid"
    watchlisted = bool(instrument.is_watchlisted)
    bar = _latest_bar(db, instrument.id, as_of)
    quote_read = market_read_status(bar)
    bars = _bars(db, instrument.id, as_of)
    coverage = _instrument_coverage(db, instrument, as_of, bars)
    signals = _latest_strategy_signals(db, instrument.id, as_of)
    generated_at = utc_now_iso()
    decision_context = db.info.get("_decision_contexts", {}).get(as_of.isoformat() if as_of else "none")
    strategy_versions = (
        decision_context.get("strategy_versions_by_instrument", {}).get(instrument.id, {})
        if decision_context and instrument.id in decision_context["instrument_ids"]
        else {
            name: db.get(StrategyVersion, signal.strategy_version_id) if signal.strategy_version_id else None
            for name, signal in signals.items()
        }
    )
    strategy_results = {
        name: _strategy_result(
            signals.get(name),
            name,
            as_of,
            strategy_version=strategy_versions.get(name),
            response_generated_at=generated_at,
        )
        for name in ("breakout_v1", "pullback_v1")
    }
    strategy_results = {name: result for name, result in strategy_results.items() if result is not None}
    valid_results = [result for result in strategy_results.values() if _strategy_has_valid_levels(result)]
    conditional = [result for result in valid_results if result["status"] == "conditional"]
    observation = [result for result in valid_results if result["status"] == "observation"]
    complete_observations = [
        result
        for result in strategy_results.values()
        if result.get("status") == "observation"
        and result.get("data_quality") == "complete"
        and not result.get("missing")
    ]
    actionable_conditionals = [result for result in conditional if _strategy_is_actionable(result)]
    missing: list[str] = []
    research_reads = context.get("research_reads_by_instrument", {}).get(instrument.id) if stock_research_reads and context else None
    if research_reads and research_reads.unlocated_count:
        missing.append("signal_date_unlocated")
    if research_reads and research_reads.identity_unlocated_count:
        missing.append("strategy_identity_unlocated")
    if run is None or run.status != "success" or not official_as_of:
        missing.append("data_as_of")
    if bar is None:
        missing.append("market_bar")
    elif quote_read["status"] == "invalid":
        missing.append("market_bar_read_invalid")
    if coverage["coverage_status"] == "unknown":
        missing.append("taiex_session_baseline")
        # Keep the product-level blocker explicit even though the numeric
        # coverage fields remain null (unknown is not zero measured sessions).
        missing.extend(["bars_20d", "bars_60d"])
    if coverage["missing_bars_to_20"] is not None and coverage["missing_bars_to_20"] > 0:
        missing.append("bars_20d")
    if coverage["missing_bars_to_60"] is not None and coverage["missing_bars_to_60"] > 0:
        missing.append("bars_60d")
    if not strategy_results and bar is not None and len(bars) < 20:
        missing.append("signal")
    chip_complete, chip_missing, chip_rows = _chips_complete(db, instrument.id, as_of)
    # A persisted complete conditional signal already records the validated
    # canonical inputs used to create it.  Do not re-apply a broad instrument
    # chip gate to that result here; doing so made a valid action disappear
    # when the alternate strategy or a non-actionable background snapshot was
    # incomplete.  When no actionable conditional exists, keep the
    # fail-closed chip check for a possible observation/wait decision.
    if strategy_results and not actionable_conditionals and not complete_observations and not chip_complete:
        missing.extend(chip_missing)
    group_ids, group_missing, group_evidence = _group_ids_and_blockers(db, instrument, as_of)
    # A qualified theme is discovery context, not an additional hard gate for
    # a canonical individual strategy.  The strategy's persisted
    # group-relative input remains visible in its evidence and is validated by
    # _strategy_result/pipeline before reaching this layer.
    if not actionable_conditionals and not complete_observations:
        # If there is no complete rule result that can explain the current
        # state, preserve every real strategy/data blocker and fail closed.
        # Complete observation is intentionally excluded: missing trigger or
        # target levels are expected when its rule simply did not pass.
        for result in strategy_results.values():
            missing.extend(result.get("missing", []))
        missing.extend(_quality_blockers(db, instrument, as_of))
    missing = list(dict.fromkeys(missing))
    complete = not missing and bool(strategy_results)
    # A fully scanned instrument may legitimately have no passing setup.  In
    # that case the action is ``no_condition`` but the source data can still be
    # complete; absence of a Signal row is not itself a recommendation.
    data_quality = "complete" if not missing and run is not None and run.status == "success" and bar else ("missing" if not bar and not official_as_of else "partial")

    current_price = bar.close if bar and bar.core_valid else None
    price_as_of = bar.trading_date.isoformat() if bar and bar.core_valid else None
    previous_close, price_change, price_change_pct = _verified_adjacent_change(
        db,
        instrument,
        bar,
        bars,
        as_of,
    )
    levels: dict[str, Any] = {
        "trigger_kind": None,
        "trigger_price": None,
        "entry_low": None,
        "entry_high": None,
        "invalid_price": None,
        "stop_price": None,
        "target_1": None,
        "target_2": None,
        "risk_reward": None,
        "earliest_execution_date": None,
    }
    conflicts: list[str] = []
    if len(conditional) >= 2:
        first, second = conditional[0], conditional[1]
        first_price = first["levels"].get("trigger_price")
        second_price = second["levels"].get("trigger_price")
        if first_price and second_price and abs(first_price - second_price) / max(first_price, second_price) > 0.05:
            conflicts.append("兩個策略的觸發價差異超過 5%")
    if conditional and observation:
        breakout = next((item for item in valid_results if item["strategy"] == "breakout_v1"), None)
        pullback = next((item for item in valid_results if item["strategy"] == "pullback_v1"), None)
        if breakout and pullback and pullback["levels"].get("entry_low") and breakout["levels"].get("trigger_price"):
            if breakout["levels"]["trigger_price"] < pullback["levels"]["entry_low"]:
                conflicts.append("突破觸發價低於回踩區")

    selected: dict[str, Any] | None = None
    if conditional:
        selected = next((item for item in conditional if item["strategy"] == "breakout_v1"), conditional[0])
    elif observation:
        selected = next((item for item in observation if item["strategy"] == "pullback_v1"), observation[0])
    if complete and selected:
        selected_levels = selected["levels"]
        levels.update(
            {
                "trigger_kind": "breakout" if selected["strategy"] == "breakout_v1" else "pullback",
                "trigger_price": selected_levels.get("trigger_price"),
                "entry_low": selected_levels.get("entry_low"),
                "entry_high": selected_levels.get("entry_high"),
                "invalid_price": selected_levels.get("invalid_price"),
                "stop_price": position_stop if position_stop_status != "missing" else selected_levels.get("invalid_price"),
                "target_1": selected_levels.get("target_1"),
                "target_2": selected_levels.get("target_2"),
                "risk_reward": selected.get("risk_reward"),
                "earliest_execution_date": selected.get("earliest_execution_date"),
            }
        )

    context = db.info.get("_decision_contexts", {}).get(as_of.isoformat() if as_of else "none")
    if context and instrument.id in context["instrument_ids"]:
        related_events = context["events_by_instrument"].get(instrument.id, [])[:5]
    else:
        related_events = db.scalars(
            select(Event)
            .where(Event.instrument_id == instrument.id, Event.event_date <= (as_of or date.max))
            .order_by(desc(Event.event_date), desc(Event.id))
            .limit(5)
        ).all()
    recent_event_cutoff = (as_of - timedelta(days=7)) if as_of else date.min
    has_recent_event = any(
        event.event_date >= recent_event_cutoff
        and (event.source or "").casefold().startswith(("mops", "twse", "tpex", "official"))
        for event in related_events
    )
    product_time = build_action_product_time(
        as_of=as_of,
        price_as_of=price_as_of,
        earliest_execution_date=levels.get("earliest_execution_date"),
        related_events=related_events,
        collected_at=run.finished_at if run else None,
        response_generated_at=generated_at,
        legacy_generated_at=generated_at,
    )

    if not complete:
        action_state = "data_insufficient" if missing else "no_condition"
    elif unknown_quantity:
        action_state = "manual_review"
    elif invalid_held_stop:
        action_state = "manual_review"
    elif held and current_price is not None and levels.get("stop_price") is not None and current_price <= levels["stop_price"]:
        action_state = "reduce_exit"
    elif held:
        action_state = "hold_observe"
    elif conflicts:
        action_state = "manual_review"
    elif conditional:
        action_state = "conditional_entry"
    elif observation:
        action_state = "wait_pullback" if selected and selected["strategy"] == "pullback_v1" else "wait_breakout"
    else:
        action_state = "no_condition"

    if action_state == "reduce_exit":
        priority = 0
    elif action_state == "data_insufficient":
        priority = 1 if held or unknown_quantity else (4 if watchlisted or has_recent_event else 6)
    elif action_state == "conditional_entry":
        priority = 2
    elif action_state in {"wait_breakout", "wait_pullback", "manual_review"}:
        priority = 3
    elif action_state == "hold_observe":
        priority = 4
    else:
        priority = 5

    if action_state == "data_insufficient":
        action_instruction = "現在：先不行動"
        coverage_gaps: list[str] = []
        if coverage["coverage_status"] == "unknown":
            data_gap = "尚無可核實交易日基準，尚不能計算進場、失效與目標價。"
        else:
            if coverage["missing_bars_to_20"] is not None and coverage["missing_bars_to_20"] > 0:
                coverage_gaps.append(f"20 日基準還缺 {coverage['missing_bars_to_20']} 個有效交易日")
            if coverage["missing_bars_to_60"] is not None and coverage["missing_bars_to_60"] > 0:
                coverage_gaps.append(f"60 日基準還缺 {coverage['missing_bars_to_60']} 個有效交易日")
            if coverage_gaps:
                data_gap = "；".join(coverage_gaps) + "，尚不能計算進場、失效與目標價。"
            elif any(field in missing for field in ("institutional_flow_5d", "foreign_buy", "trust_buy", "dealer_buy", "margin_balance", "margin_change")):
                data_gap = "官方籌碼資料尚未完整，尚不能驗證進場、失效與目標價。"
            elif any(field in missing for field in ("theme_membership", "qualified_theme")):
                data_gap = "官方族群資料尚未完整，尚不能驗證進場、失效與目標價。"
            else:
                data_gap = "研究資料尚未完整，尚不能計算進場、失效與目標價。"
    elif action_state == "conditional_entry":
        action_instruction = "現在：條件成立；僅在觸發價與風險條件同時符合時行動。"
        data_gap = None
    elif action_state == "wait_breakout":
        action_instruction = "現在：等待突破觸發。"
        data_gap = None
    elif action_state == "wait_pullback":
        action_instruction = "現在：等待回踩區與重新轉強。"
        data_gap = None
    elif action_state == "reduce_exit":
        action_instruction = "現在：檢查減碼／退場條件。"
        data_gap = None
    elif action_state == "hold_observe":
        action_instruction = "現在：持有觀察，等待條件或風險變化。"
        data_gap = None
    elif action_state == "manual_review":
        action_instruction = ("庫存股數待核實，先核對原記錄。" if unknown_quantity else
                              "庫存停損待核實，先核對原記錄。" if invalid_held_stop else
                              "現在：先人工核對互相衝突的條件。")
        data_gap = None
    else:
        action_instruction = "現在：先觀察，尚無成立條件。"
        data_gap = None

    reasons: list[str] = []
    if action_state == "data_insufficient":
        reasons.append("策略判斷資料尚未齊備，暫時不能形成可執行條件")
    if held and action_state == "reduce_exit":
        reasons.append("持倉現價已觸及持倉停損／策略失效界線")
    if action_state == "manual_review" and invalid_held_stop:
        reasons.append("庫存停損待核實，先核對原記錄。")
    if action_state == "manual_review" and unknown_quantity:
        reasons.append("庫存股數待核實，先核對原記錄。")
    if selected and selected.get("rationale"):
        reasons.append(str(selected["rationale"]))
    if group_evidence:
        reasons.append("至少一個有效族群具備 TAIEX 相對強弱與成員門檻")
    if conflicts:
        reasons.append("兩個策略條件存在衝突，保留兩者供人工判讀")
    if not strategy_results and action_state == "no_condition":
        reasons.append("截至目前沒有 canonical 策略條件成立")
    reasons = reasons[:3]

    display_reasons = [display_reason(reason) for reason in reasons]
    selected_strategy = selected.get("strategy") if selected else None
    if action_state == "data_insufficient":
        display_instruction = "目前無法產生研究動作。"
        if data_gap:
            display_instruction += " " + data_gap
    elif action_state == "conditional_entry":
        display_instruction = "僅在觸發價與資料條件同時成立時研究進場；最早下一個可判定交易日（T+1）再檢查。"
    elif action_state == "wait_breakout":
        display_instruction = "等待收盤符合突破觀察門檻後，再重新核對量能、族群與籌碼。"
    elif action_state == "wait_pullback":
        display_instruction = "等待回到觀察區間後，再重新核對趨勢、量能與籌碼。"
    elif action_state == "hold_observe":
        display_instruction = "目前未見已核實的減碼／退場條件；持續留意失效價、使用者停損與資料更新。"
    elif action_state == "reduce_exit":
        display_instruction = "已碰到既定風險條件，請依自己的風險規畫重新研究減碼或退場。"
    elif action_state == "manual_review":
        display_instruction = ("庫存股數待核實，先核對原記錄。" if unknown_quantity else
                               "庫存停損待核實，先核對原記錄。" if invalid_held_stop else
                               "資料截止、價位或研究條件存在無法自動調和的衝突，先人工核對證據。")
    else:
        display_instruction = "資料足夠，但目前尚未符合研究條件；持續觀察。"

    action_field_mapping = {
        "trigger_price": (
            "breakout_price"
            if selected and selected.get("strategy") == "breakout_v1"
            else "reference_entry"
            if selected and selected.get("strategy") == "pullback_v1"
            else "trigger_price"
        ),
        "entry_low": "pullback_low",
        "entry_high": "pullback_high",
        "invalid_price": "invalid_price",
        "target_1": "target_1",
        "target_2": "target_2",
    }
    selected_level_semantics = (
        selected.get("level_semantics")
        if selected
        and action_state != "manual_review"
        and isinstance(selected.get("level_semantics"), dict)
        else None
    )
    if selected_level_semantics is None:
        selected_level_semantics = build_level_semantics(
            strategy_name=selected.get("level_semantics", {}).get("strategy", {}).get("name") if selected and action_state != "manual_review" else None,
            strategy_version=selected.get("level_semantics", {}).get("strategy", {}).get("version") if selected and action_state != "manual_review" else None,
            field_mapping=action_field_mapping,
            response_generated_at=generated_at,
        )
    stop_price_semantics = build_stop_price_semantics(
        has_position_stop=position_stop_status == "known",
        has_rule_fallback=bool(
            position_stop_status == "missing"
            and levels.get("stop_price") is not None
        ),
        rule_semantics_known=selected_level_semantics.get("kind") == "rule_reference",
        invalid_position_stop=position_stop_status == "invalid",
    )

    primary_levels: dict[str, Any] = {}
    if action_state == "conditional_entry":
        primary_levels = {
            "kind": "trigger_invalid",
            "trigger": levels.get("trigger_price"),
            "invalid": levels.get("invalid_price"),
        }
    elif action_state == "wait_breakout":
        primary_levels = {"kind": "breakout_observation", "trigger": levels.get("trigger_price")}
    elif action_state == "wait_pullback":
        primary_levels = {
            "kind": "pullback_observation",
            "low": levels.get("entry_low"),
            "high": levels.get("entry_high"),
        }
    elif action_state in {"hold_observe", "reduce_exit"}:
        primary_levels = {"kind": "risk", "stop": levels.get("stop_price")}
    if primary_levels:
        semantic_fields = selected_level_semantics.get("fields", {})
        primary_levels["semantics"] = {
            "trigger": semantic_fields.get("trigger_price"),
            "invalid": semantic_fields.get("invalid_price"),
            "low": semantic_fields.get("entry_low"),
            "high": semantic_fields.get("entry_high"),
            "stop": stop_price_semantics if "stop" in primary_levels else None,
        }

    context_badges: list[str] = []
    if held:
        context_badges.append("持倉")
    elif unknown_quantity:
        context_badges.append("股數待核實")
    if watchlisted:
        context_badges.append("自選")
    if has_recent_event:
        context_badges.append("已核實個股公告")
    if group_evidence:
        context_badges.append("族群觀察")

    evidence_refs = []
    if run:
        evidence_refs.append(f"ingestion_run:{run.id}")
    if bar:
        evidence_refs.append(f"market_bar:{bar.id}")
        if bar.raw_payload_id:
            evidence_refs.append(f"raw_payload:{bar.raw_payload_id}")
    for row in chip_rows:
        if row.raw_payload_id:
            evidence_refs.append(f"raw_payload:{row.raw_payload_id}")
    for result in strategy_results.values():
        evidence_refs.append(f"signal:{result['signal_id']}")
    evidence_refs.extend(f"theme:{group_id}" for group_id in group_ids)
    evidence_refs = list(dict.fromkeys(evidence_refs))
    return {
        "instrument": {
            "id": instrument.id,
            "exchange": instrument.exchange,
            "symbol": instrument.symbol,
            "name": instrument.name,
            "instrument_type": instrument.instrument_type,
            "etf_category": instrument.etf_category,
        },
        "as_of": as_of.isoformat() if as_of else None,
        "generated_at": generated_at,
        "product_time": product_time,
        "response_generated_at": product_time["response_generated_at"],
        "level_semantics": selected_level_semantics,
        "action_state": action_state,
        "action_label_zh": ACTION_LABELS[action_state],
        "action_instruction": action_instruction,
        "display_action": display_action_label(action_state),
        "display_instruction": display_instruction,
        "display_reasons": display_reasons,
        "primary_reason": primary_reason(
            action_state=action_state,
            reasons=reasons,
            missing=missing,
            strategy=selected_strategy,
        ),
        "primary_levels": primary_levels,
        "data_status": {
            "source": "official_snapshot" if bar and bar.core_valid and not str(bar.source or "").lower().startswith("fixture") else "snapshot_pending",
            "market": "complete" if quote_read["status"] == "known" else "partial" if bar else "missing",
            "strategy": "complete" if data_quality == "complete" else "partial",
        },
        "context_badges": context_badges[:3],
        "detail_url": f"/stocks/{instrument.exchange}/{instrument.symbol}",
        "data_gap": data_gap,
        "priority": priority,
        "held": held,
        "position_quantity_status": quantity_status,
        "watchlisted": watchlisted,
        "current_price": current_price if bar else None,
        "market_read": quote_read,
        "price_as_of": price_as_of,
        "previous_close": previous_close,
        "price_change": price_change,
        "price_change_pct": price_change_pct,
        **levels,
        "primary_strategy": selected.get("strategy") if selected else None,
        "alternative_strategies": [result["strategy"] for result in strategy_results.values() if not selected or result["strategy"] != selected["strategy"]],
        "strategies": list(strategy_results.values()),
        "reasons": reasons,
        "conflicts": conflicts,
        "evidence_refs": evidence_refs,
        "data_quality": data_quality,
        "blocking_reasons": missing,
        "missing_data_priority": _priority_missing(missing, held=held is True),
        "theme_ids": group_ids,
        "event_ids": [event.id for event in related_events],
        "data_cutoff": as_of.isoformat() if as_of else None,
        "coverage": coverage,
        "stop_price_semantics": stop_price_semantics,
        **({"research_read": research_reads.to_state()} if research_reads is not None else {}),
    }


def _latest_group_scores(db: Session, as_of: date | None) -> list[tuple[ThemeGroup, GroupDailyScore]]:
    if not as_of:
        return []
    rows = db.execute(
        select(ThemeGroup, GroupDailyScore)
        .join(GroupDailyScore, GroupDailyScore.group_id == ThemeGroup.id)
        .where(ThemeGroup.active.is_(True), GroupDailyScore.trading_date <= as_of)
        .order_by(desc(GroupDailyScore.trading_date), desc(GroupDailyScore.id))
    ).all()
    result: list[tuple[ThemeGroup, GroupDailyScore]] = []
    seen: set[str] = set()
    for group, score in rows:
        if group.id not in seen:
            seen.add(group.id)
            result.append((group, score))
    return result


def _group_candidate_ids(
    db: Session, group: ThemeGroup, score: GroupDailyScore, as_of: date,
) -> set[int]:
    """Resolve score-day identities, then retain the same current members.

    Instrument status/type/category are current metadata, not historical
    truth. Inactive rows remain in source-day ambiguity checks; otherwise
    today's status could make an ambiguous old symbol appear unique.
    """
    details = score.details_json
    if not isinstance(details, dict):
        return set()
    symbols = details.get("candidate_symbols")
    if (not isinstance(symbols, list) or len(symbols) > MAX_GROUP_CANDIDATES
            or any(type(symbol) is not str or not symbol.strip() for symbol in symbols)):
        return set()
    versioned = "candidate_identity_version" in details
    candidates = details.get("candidate_instruments")
    if versioned:
        if details["candidate_identity_version"] != "instrument-id-v1":
            return set()
        if not isinstance(candidates, list) or len(candidates) > MAX_GROUP_CANDIDATES:
            return set()
        ids, pairs = set(), set()
        for candidate in candidates:
            if not isinstance(candidate, dict):
                return set()
            item_id = candidate.get("instrument_id")
            exchange, symbol = candidate.get("exchange"), candidate.get("symbol")
            if (type(item_id) is not int or item_id <= 0
                    or type(exchange) is not str or not exchange.strip()
                    or type(symbol) is not str or not symbol.strip()):
                return set()
            if item_id in ids or (exchange, symbol) in pairs:
                return set()
            ids.add(item_id)
            pairs.add((exchange, symbol))
        if [candidate["symbol"] for candidate in candidates] != symbols:
            return set()
    elif "candidate_instruments" in details:
        return set()
    if not symbols:
        return set()

    # Small projections only: this runs before action-center pagination.
    rows = db.execute(
        select(Instrument.id, Instrument.exchange, Instrument.symbol,
               Instrument.status, Instrument.instrument_type, Instrument.etf_category,
               GroupMembership.valid_from, GroupMembership.valid_to)
        .join(GroupMembership, GroupMembership.instrument_id == Instrument.id)
        .where(GroupMembership.group_id == group.id,
               GroupMembership.valid_from <= as_of,
               (GroupMembership.valid_to.is_(None)
                | (GroupMembership.valid_to >= score.trading_date)))
    ).all()
    is_etf_group = group.group_type in {"etf", "instrument_theme"} or "etf" in group.name.lower()
    source_members, current_ids = {}, set()
    for item_id, exchange, symbol, status, kind, category, start, end in rows:
        allowed = (kind == "etf" and category in ETF_CATEGORIES) if is_etf_group else kind in {"stock", "ipo"}
        if not allowed:
            continue
        if start <= score.trading_date and (end is None or end >= score.trading_date):
            source_members[item_id] = (exchange, symbol)
        if start <= as_of and (end is None or end >= as_of) and status == "active":
            current_ids.add(item_id)
    if versioned:
        for candidate in candidates:
            if source_members.get(candidate["instrument_id"]) != (candidate["exchange"], candidate["symbol"]):
                return set()
        return {candidate["instrument_id"] for candidate in candidates} & current_ids

    # A repeated legacy symbol cannot prove which ranked slot it represented.
    result = set()
    for symbol in set(symbols):
        if symbols.count(symbol) != 1:
            continue
        matches = {item_id for item_id, pair in source_members.items() if pair[1] == symbol}
        if len(matches) == 1:
            result.update(matches & current_ids)
    return result


def position_holding_ids(db: Session, instrument_ids: Iterable[int] | None = None) -> tuple[set[int], set[int], set[int]]:
    """Read cheap quantity projections; record existence never proves holding."""
    query = select(PortfolioPosition.instrument_id, PortfolioPosition.shares, PortfolioPosition.shares_integer).join(
        Instrument, Instrument.id == PortfolioPosition.instrument_id).where(Instrument.status == "active")
    if instrument_ids is not None:
        query = query.where(PortfolioPosition.instrument_id.in_(list(instrument_ids)))
    held_ids, unknown_ids, recorded_ids = set(), set(), set()
    for instrument_id, legacy, integer in db.execute(query):
        recorded_ids.add(instrument_id)
        held = position_held(legacy, integer)
        if held is True:
            held_ids.add(instrument_id)
        elif held is None:
            unknown_ids.add(instrument_id)
    return held_ids, unknown_ids, recorded_ids


def prioritized_instrument_ids(db: Session, as_of: date | None) -> list[int]:
    """Return a deterministic, cheap action-center candidate order.

    Only small identity/status projections run here.  The expensive decision
    builder is called after the API has selected a page, so a 20-row request
    never evaluates every scoped instrument.
    """

    def sort_ids(ids: set[int], keys: dict[int, tuple[str, str, int]]) -> list[int]:
        return sorted(ids, key=lambda item_id: keys.get(item_id, ("", "", item_id)))

    held_ids, unknown_ids, recorded_ids = position_holding_ids(db)
    if not as_of:
        rows = db.execute(
            select(Instrument.id, Instrument.exchange, Instrument.symbol)
            .join(PortfolioPosition, PortfolioPosition.instrument_id == Instrument.id, isouter=True)
            .where(Instrument.status == "active", (PortfolioPosition.id.is_not(None) | Instrument.is_watchlisted.is_(True)))
        ).all()
        keys = {int(item_id): (str(exchange), str(symbol), int(item_id)) for item_id, exchange, symbol in rows}
        return sorted(keys, key=lambda item_id: (
            0 if item_id in held_ids else 1 if item_id in unknown_ids else
            3 if item_id in recorded_ids else 2, keys[item_id]))
    watch_ids: set[int] = set(
        db.scalars(select(Instrument.id).where(Instrument.status == "active", Instrument.is_watchlisted.is_(True))).all()
    )
    # A canonical conditional signal is an action candidate even when its
    # instrument is not one of the currently qualified theme's displayed
    # candidates.  Theme ranking is discovery context and must not hide a
    # valid individual setup from the action center.
    conditional_ids: set[int] = set(
        db.scalars(
            select(Signal.instrument_id)
            .join(StrategyVersion, StrategyVersion.id == Signal.strategy_version_id)
            .join(Instrument, Instrument.id == Signal.instrument_id)
            .where(
                Instrument.status == "active",
                Signal.signal_date == as_of,
                Signal.status == "conditional",
                Signal.data_quality == "complete",
                StrategyVersion.name.in_({"breakout_v1", "pullback_v1"}),
            )
        ).all()
    )
    observation_ids: set[int] = set(
        db.scalars(
            select(Signal.instrument_id)
            .join(StrategyVersion, StrategyVersion.id == Signal.strategy_version_id)
            .join(Instrument, Instrument.id == Signal.instrument_id)
            .where(
                Instrument.status == "active",
                Signal.signal_date == as_of,
                Signal.status == "observation",
                Signal.data_quality == "complete",
                StrategyVersion.name.in_({"breakout_v1", "pullback_v1"}),
            )
        ).all()
    )
    candidate_ids: set[int] = set()
    for group, score in _latest_group_scores(db, as_of):
        if score.data_quality != "complete" or (score.eligible_members or 0) < 3 or score.rank is None:
            continue
        details = score.details_json
        if not isinstance(details, dict) or details.get("benchmark") != "TAIEX":
            continue
        candidate_ids.update(_group_candidate_ids(db, group, score, as_of))
    # Events are useful context but should not elevate the whole market.  Keep
    # only recent official event-linked instruments.
    recent_cutoff = as_of - timedelta(days=7)
    event_ids: set[int] = set(
        db.scalars(
            select(Event.instrument_id).where(
                Event.instrument_id.is_not(None),
                Event.event_date >= recent_cutoff,
                Event.event_date <= as_of,
            )
        ).all()
    )
    all_ids = recorded_ids | watch_ids | conditional_ids | observation_ids | candidate_ids | event_ids
    if not all_ids:
        return []
    rows = db.execute(
        select(Instrument.id, Instrument.exchange, Instrument.symbol)
        .where(Instrument.id.in_(all_ids), Instrument.status == "active")
    ).all()
    keys = {int(item_id): (str(exchange), str(symbol), int(item_id)) for item_id, exchange, symbol in rows}
    # Approximate the exact product order using persisted state categories;
    # stable secondary keys keep cursor traversal deterministic.
    ordered_ids: list[int] = []
    seen: set[int] = set()
    for bucket in (
        held_ids,
        unknown_ids,
        conditional_ids,
        observation_ids,
        event_ids | watch_ids,
        candidate_ids,
        recorded_ids,
        all_ids,
    ):
        for item_id in sort_ids(bucket - seen, keys):
            seen.add(item_id)
            ordered_ids.append(item_id)
    return ordered_ids


def build_action_summaries(db: Session, as_of: date | None = None, instrument_ids: Iterable[int] | None = None) -> list[dict[str, Any]]:
    if as_of is None:
        _run, as_of = latest_official_as_of(db)
    ids = list(instrument_ids) if instrument_ids is not None else prioritized_instrument_ids(db, as_of)
    if not ids:
        return []
    instruments = db.scalars(select(Instrument).where(Instrument.id.in_(ids), Instrument.status == "active")).all()
    _prepare_decision_context(db, as_of, ids)
    summaries = [build_decision_summary(db, instrument, as_of) for instrument in instruments]
    summaries.sort(
        key=lambda item: (
            item.get("priority", 99),
            not item.get("held", False),
            item.get("position_quantity_status") != "unknown",
            not item.get("watchlisted", False),
            (item.get("instrument") or {}).get("exchange", ""),
            (item.get("instrument") or {}).get("symbol", ""),
        )
    )
    # Defensive dedupe guarantees the product invariant even if a legacy
    # database contains overlapping membership or strategy rows.
    unique: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    for item in summaries:
        instrument = item.get("instrument") or {}
        key = (str(instrument.get("exchange")), str(instrument.get("symbol")), item.get("as_of"))
        unique.setdefault(key, item)
    return list(unique.values())
