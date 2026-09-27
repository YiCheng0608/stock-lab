from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any, Iterable

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.config import (
    EXECUTION_SLIPPAGE_BPS,
    MAX_GROUP_CANDIDATES,
    MIN_GROUP_CANDIDATES,
    MIN_GROUP_MEMBERS,
    OFFICIAL_MAX_BACKFILL_DAYS,
    ROUND_TRIP_TRANSACTION_COST_BPS,
)
from app.db import SessionLocal, init_db
from app.domain import (
    CANONICAL_CONFIGS,
    ETF_CATEGORIES,
    GROUP_SCORE_WEIGHTS,
    HOT_GROUP_CONFIG,
    SIGNAL_CONFIDENCE_SEMANTICS,
    STRATEGY_CONFIGS,
    calculate_group_score,
    canonical_config_snapshot,
    evaluate_breakout_v1,
    evaluate_pullback_v1,
    group_score_quality,
    instrument_eligibility,
    moving_average,
    signal_confidence_semantics,
    validate_signal_levels,
    validate_signal_status_transition,
)
from app.models import (
    ChipSnapshot,
    CorporateAction,
    DataQuality,
    Event,
    FundamentalSnapshot,
    GroupDailyScore,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    PortfolioPosition,
    RawPayload,
    Signal,
    SignalEvaluation,
    SignalSettlement,
    StrategyVersion,
    TechnicalFeature,
    ThemeGroup,
)
from app.news import sync_news_from_events
from app.taxonomy import INDUSTRY_DISPLAY_ZH, canonical_group_id, canonical_industry_label
from worker.sources import (
    ActionRecord,
    BarRecord,
    EventRecord,
    FetchedPayload,
    FundamentalRecord,
    InstrumentRecord,
    OfficialDataError,
    OfficialMarketDataAdapter,
    OfficialBatch,
    TWSE_LISTED_ENDPOINT,
    TWSE_NEW_LISTING_ENDPOINT,
    TPEX_LISTED_ENDPOINT,
    TWSE_ETF_ENDPOINT,
    TPEX_ETF_ENDPOINT,
)


def latest_weekday(value: date | None = None) -> date:
    current = value or date.today()
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def business_days(end: date, count: int) -> list[date]:
    values: list[date] = []
    cursor = end
    while len(values) < count:
        if cursor.weekday() < 5:
            values.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(values))


def _as_datetime(value: str | None, fallback: date | None = None) -> datetime | None:
    if value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            try:
                return datetime.combine(date.fromisoformat(value[:10]), datetime.min.time())
            except ValueError:
                pass
    return datetime.combine(fallback, datetime.min.time()) if fallback else None


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _effective_memberships(db: Session, group_id: str, score_date: date) -> list[tuple[GroupMembership, Instrument]]:
    rows = db.execute(
        select(GroupMembership, Instrument)
        .join(Instrument, Instrument.id == GroupMembership.instrument_id)
        .where(
            GroupMembership.group_id == group_id,
            GroupMembership.valid_from <= score_date,
            (GroupMembership.valid_to.is_(None) | (GroupMembership.valid_to >= score_date)),
            Instrument.status == "active",
        )
    ).all()
    # Overlapping historical snapshots are possible in legacy imports.  Use
    # the latest effective period once, without deleting the old membership.
    deduped: dict[int, tuple[GroupMembership, Instrument]] = {}
    for membership, instrument in rows:
        previous = deduped.get(instrument.id)
        if previous is None or membership.valid_from > previous[0].valid_from:
            deduped[instrument.id] = (membership, instrument)
    return list(deduped.values())


def get_or_create_instrument(
    db: Session,
    symbol: str,
    name: str,
    instrument_type: str,
    etf_category: str | None,
    listing_date: date | None,
    *,
    exchange: str = "TWSE",
    industry: str | None = None,
    source: str | None = None,
) -> Instrument:
    item = db.scalar(
        select(Instrument).where(
            Instrument.market == "TW",
            Instrument.exchange == exchange,
            Instrument.symbol == symbol,
        )
    )
    if item:
        # Do not overwrite a legacy name or historical classification with an
        # empty value.  Official refreshes may update the mutable fields.
        if name and (not item.name or source == "official"):
            item.name = name
        if source == "official":
            item.exchange = exchange
            item.instrument_type = instrument_type
            item.etf_category = etf_category
            item.industry = industry or item.industry
            item.listing_date = listing_date or item.listing_date
            item.status = "active"
        return item
    item = Instrument(
        market="TW",
        exchange=exchange,
        symbol=symbol,
        name=name or symbol,
        instrument_type=instrument_type,
        etf_category=etf_category,
        industry=industry,
        listing_date=listing_date,
        is_watchlisted=symbol in {"2881", "2603", "2330"},
        status="active",
    )
    db.add(item)
    db.flush()
    return item


def _ensure_membership(
    db: Session,
    group_id: str,
    instrument_id: int,
    valid_from: date,
    *,
    source: str,
) -> None:
    exists = db.scalar(
        select(GroupMembership).where(
            GroupMembership.group_id == group_id,
            GroupMembership.instrument_id == instrument_id,
            GroupMembership.valid_from == valid_from,
        )
    )
    if not exists:
        db.add(
            GroupMembership(
                group_id=group_id,
                instrument_id=instrument_id,
                valid_from=valid_from,
                role="member",
                confidence=1.0,
                source=source,
            )
        )


def _action_factor_by_bar(db: Session, instrument_id: int, bars: list[MarketBar]) -> list[float]:
    """Return the raw price-basis factor effective at each bar date.

    A factor maps the signal-date basis to the raw basis at the bar date.  A
    split action is therefore included on the ex-date bar itself, while an
    action after a score date can never affect that score's history.
    """

    if not bars:
        return []
    actions = db.scalars(
        select(CorporateAction)
        .where(
            CorporateAction.instrument_id == instrument_id,
            CorporateAction.action_date <= bars[-1].trading_date,
        )
        .order_by(CorporateAction.action_date, CorporateAction.id)
    ).all()
    fallback_reference_prices: dict[date, float] = {}
    for action in actions:
        if action.reference_price is not None:
            continue
        previous = next(
            (
                candidate
                for candidate in reversed(bars)
                if candidate.trading_date < action.action_date and _safe_float(candidate.close) is not None
            ),
            None,
        )
        if previous and previous.close > 0:
            fallback_reference_prices[action.action_date] = previous.close
    factors: list[float] = []
    for bar in bars:
        effective = [action for action in actions if action.action_date <= bar.trading_date]
        factor, _applied = _corporate_action_factor(
            effective,
            fallback_reference_prices=fallback_reference_prices,
        )
        factors.append(factor if math.isfinite(factor) and factor > 0 else 1.0)
    return factors


def _normalized_history_for_score_date(
    db: Session,
    instrument_id: int,
    score_date: date,
) -> tuple[list[MarketBar], dict[date, dict[str, float]], float]:
    """Normalize all pre-score raw OHLC to the score-date raw price basis."""

    bars = db.scalars(
        select(MarketBar)
        .where(MarketBar.instrument_id == instrument_id, MarketBar.trading_date <= score_date)
        .order_by(MarketBar.trading_date)
    ).all()
    factors = _action_factor_by_bar(db, instrument_id, bars)
    if not bars:
        return [], {}, 1.0
    score_factor = factors[-1] if factors else 1.0
    normalized: dict[date, dict[str, float]] = {}
    for bar, bar_factor in zip(bars, factors):
        ratio = score_factor / bar_factor if bar_factor > 0 else 1.0
        normalized[bar.trading_date] = {
            "open": bar.open * ratio,
            "high": bar.high * ratio,
            "low": bar.low * ratio,
            "close": bar.close * ratio,
            # Official adapters intentionally preserve adj_close as the raw
            # close.  Derived consumers use this explicit normalized value.
            "adj_close": bar.close * ratio,
            "factor_bar_to_score": ratio,
        }
    return bars, normalized, score_factor


def _calculate_features(
    db: Session,
    instrument: Instrument,
    *,
    as_of_date: date | None = None,
    capture: Any = None,
    capture_date: date | None = None,
) -> None:
    bars = db.scalars(
        select(MarketBar)
        .where(
            MarketBar.instrument_id == instrument.id,
            *( [MarketBar.trading_date <= as_of_date] if as_of_date is not None else [] ),
        )
        .order_by(MarketBar.trading_date)
    ).all()
    factors = _action_factor_by_bar(db, instrument.id, bars)
    for index, bar in enumerate(bars):
        score_factor = factors[index] if factors else 1.0
        normalized = [
            {
                "open": item.open * score_factor / (factors[position] or 1.0),
                "high": item.high * score_factor / (factors[position] or 1.0),
                "low": item.low * score_factor / (factors[position] or 1.0),
                "close": item.close * score_factor / (factors[position] or 1.0),
            }
            for position, item in enumerate(bars[: index + 1])
        ]
        closes = [item["close"] for item in normalized]
        highs = [item["high"] for item in normalized]
        lows = [item["low"] for item in normalized]
        volumes = [item.volume for item in bars[: index + 1]]
        prior_closes = closes[:index]
        prior_volumes = volumes[:index]
        prior_highs = highs[:index]
        prior_lows = lows[:index]
        prior_20_volumes = prior_volumes[-20:] if len(prior_volumes) >= 20 else []
        ma20 = moving_average(closes, 20)
        ma60 = moving_average(closes, 60)
        atr_values = [normalized_item["high"] - normalized_item["low"] for normalized_item in normalized[-14:]]
        ma5 = moving_average(closes, 5)
        feature_values: dict[str, Any] = {
            "return_1d": round(closes[index] / closes[index - 1] - 1, 8) if index >= 1 and closes[index - 1] else None,
            "return_5d": round(closes[index] / closes[index - 5] - 1, 8) if index >= 5 and closes[index - 5] else None,
            "return_20d": round(closes[index] / closes[index - 20] - 1, 8) if index >= 20 and closes[index - 20] else None,
            "ma5": round(ma5, 6) if ma5 is not None else None,
            "ma20": round(ma20, 6) if ma20 is not None else None,
            "ma60": round(ma60, 6) if ma60 is not None else None,
            "prior_20_highs": [round(value, 6) for value in prior_highs[-20:]],
            "prior_20_lows": [round(value, 6) for value in prior_lows[-20:]],
            "prior_20_volumes": [int(value) for value in prior_volumes[-20:]],
            "high_20d": round(max(highs[-20:]), 6) if highs else None,
            "low_20d": round(min(lows[-20:]), 6) if lows else None,
            "prior_high_20d": round(max(prior_highs[-20:]), 6) if len(prior_highs) >= 20 else None,
            "prior_low_20d": round(min(prior_lows[-20:]), 6) if len(prior_lows) >= 20 else None,
            "atr14": round(sum(atr_values) / len(atr_values), 6) if atr_values else None,
            "volume": int(bar.volume),
            "volume_ratio_20d": (
                round(bar.volume / (sum(prior_20_volumes) / len(prior_20_volumes)), 6)
                if prior_20_volumes and sum(prior_20_volumes) > 0
                else None
            ),
            "bar_count": index + 1,
            "bar_count_60d": index + 1,
            "source": bar.source,
            "price_basis": "score_date_raw_basis",
            "corporate_action_factor_signal_to_score_raw": score_factor,
            "corporate_actions_applied_through": bar.trading_date.isoformat(),
        }
        feature = db.scalar(
            select(TechnicalFeature).where(
                TechnicalFeature.instrument_id == instrument.id,
                TechnicalFeature.trading_date == bar.trading_date,
            )
        )
        if not feature:
            feature = TechnicalFeature(
                instrument_id=instrument.id,
                trading_date=bar.trading_date,
                features_json=feature_values,
                source="derived",
            )
            db.add(feature)
        else:
            feature.features_json = feature_values
        if (capture is not None and capture_date == bar.trading_date
                and getattr(capture, "input_provenance", None) == "selected-bar-prior-volumes/v1"):
            db.flush()
            capture.freeze_prior_volumes(
                db, instrument=instrument, feature=feature, bars=bars, index=index,
                target_date=bar.trading_date,
                projected_values=feature_values["prior_20_volumes"],
            )


def _benchmark_instrument(db: Session) -> Instrument | None:
    return db.scalar(
        select(Instrument)
        .where(
            Instrument.symbol == "TAIEX",
            Instrument.instrument_type == "index",
            Instrument.status == "active",
        )
        .limit(1)
    )


def _price_return(
    bars: list[MarketBar],
    score_date: date,
    window: int,
    normalized: dict[date, dict[str, float]] | None = None,
) -> float | None:
    usable = [
        bar
        for bar in bars
        if bar.trading_date <= score_date
        and not bar.is_suspended
        and (normalized.get(bar.trading_date, {}).get("close", bar.close) if normalized else (bar.close or bar.adj_close))
    ]
    if len(usable) < window + 1:
        return None
    current = normalized.get(usable[-1].trading_date, {}).get("close", usable[-1].close) if normalized else (usable[-1].close or usable[-1].adj_close)
    previous = normalized.get(usable[-window - 1].trading_date, {}).get("close", usable[-window - 1].close) if normalized else (usable[-window - 1].close or usable[-window - 1].adj_close)
    if not current or not previous:
        return None
    return current / previous - 1.0


def _returns_by_window(db: Session, instrument_id: int, score_date: date) -> dict[int, float | None]:
    bars, normalized, _score_factor = _normalized_history_for_score_date(db, instrument_id, score_date)
    return {window: _price_return(bars, score_date, window, normalized) for window in (1, 5, 20)}


def _effective_trading_dates(db: Session, instrument_id: int, score_date: date, window: int = 20) -> list[date]:
    rows = db.scalars(
        select(MarketBar.trading_date)
        .where(
            MarketBar.instrument_id == instrument_id,
            MarketBar.trading_date <= score_date,
            (MarketBar.is_suspended.is_(False) | MarketBar.is_suspended.is_(None)),
        )
        .order_by(desc(MarketBar.trading_date))
        .limit(window)
    ).all()
    return list(reversed(rows))


def _validated_flow_and_turnover_inputs(
    db: Session,
    instrument_id: int,
    score_date: date,
) -> tuple[float, list[float]] | None:
    """Return validated five-session flow and twenty-session turnover inputs.

    The two canonical consumers intentionally use different turnover
    denominators, but both must consume the same complete, finite source
    observations.  A missing chip component, chip session, bar, or invalid
    turnover therefore makes the result unavailable instead of silently
    turning absent data into a neutral zero.
    """

    dates = _effective_trading_dates(db, instrument_id, score_date, 20)
    if len(dates) != 20:
        return None
    bars = db.scalars(
        select(MarketBar).where(
            MarketBar.instrument_id == instrument_id,
            MarketBar.trading_date.in_(dates),
        )
    ).all()
    bars_by_date = {bar.trading_date: bar for bar in bars}
    if len(bars_by_date) != len(dates):
        return None
    turnovers: list[float] = []
    for trading_date in dates:
        bar = bars_by_date[trading_date]
        if bar.turnover_status != "available":
            return None
        turnover = _safe_float(bar.turnover)
        if turnover is None or turnover <= 0:
            return None
        turnovers.append(turnover)

    chip_dates = dates[-5:]
    chips = db.scalars(
        select(ChipSnapshot).where(
            ChipSnapshot.instrument_id == instrument_id,
            ChipSnapshot.trading_date.in_(chip_dates),
        )
    ).all()
    chips_by_date = {chip.trading_date: chip for chip in chips}
    if len(chips_by_date) != len(chip_dates):
        return None
    flow = 0.0
    for trading_date in chip_dates:
        chip = chips_by_date[trading_date]
        components = (
            _safe_float(chip.foreign_buy),
            _safe_float(chip.trust_buy),
            _safe_float(chip.dealer_buy),
        )
        if any(component is None for component in components):
            return None
        flow += sum(component for component in components if component is not None)
    return flow, turnovers


def _hot_group_institutional_flow_ratio(
    db: Session,
    instrument_id: int,
    score_date: date,
) -> float | None:
    """Compute hot_group_v1 flow: five-day flow / twenty-day turnover sum."""

    inputs = _validated_flow_and_turnover_inputs(db, instrument_id, score_date)
    if inputs is None:
        return None
    flow, turnovers = inputs
    denominator = sum(turnovers)
    return flow / denominator if denominator > 0 else None


def _strategy_institutional_flow_to_average_turnover_ratio(
    db: Session,
    instrument_id: int,
    score_date: date,
) -> float | None:
    """Compute strategy-v1 flow: five-day flow / average twenty-day turnover."""

    inputs = _validated_flow_and_turnover_inputs(db, instrument_id, score_date)
    if inputs is None:
        return None
    flow, turnovers = inputs
    average_turnover = sum(turnovers) / len(turnovers)
    return flow / average_turnover if average_turnover > 0 else None


def _margin_change_ratio(db: Session, instrument_id: int, score_date: date) -> float | None:
    dates = _effective_trading_dates(db, instrument_id, score_date, 6)
    if len(dates) < 6:
        return None
    chips = db.scalars(
        select(ChipSnapshot)
        .where(ChipSnapshot.instrument_id == instrument_id, ChipSnapshot.trading_date.in_(dates))
        .order_by(ChipSnapshot.trading_date)
    ).all()
    if len(chips) < 6 or chips[0].margin_balance in (None, 0) or chips[-1].margin_balance is None:
        return None
    return (chips[-1].margin_balance - chips[0].margin_balance) / abs(chips[0].margin_balance)


def _allowed_group_members(group: ThemeGroup, members: list[tuple[GroupMembership, Instrument]]) -> list[tuple[GroupMembership, Instrument]]:
    group_name = group.name.lower()
    is_etf_group = group.group_type in {"etf", "instrument_theme"} or "etf" in group_name
    if is_etf_group:
        return [
            (membership, instrument)
            for membership, instrument in members
            if instrument.instrument_type == "etf" and instrument.etf_category in ETF_CATEGORIES
        ]
    return [
        (membership, instrument)
        for membership, instrument in members
        if instrument.instrument_type in {"stock", "ipo"}
    ]


def _percentile(value: float | None, peers: list[float | None]) -> float | None:
    if value is None:
        return None
    valid = sorted(item for item in peers if item is not None and math.isfinite(item))
    if not valid:
        return None
    if len(valid) == 1:
        return 0.5
    less = sum(item < value for item in valid)
    equal = sum(item == value for item in valid)
    return max(0.0, min(1.0, (less + (equal - 1) / 2) / (len(valid) - 1)))


def _catalyst_value(db: Session, instrument_ids: list[int], score_date: date, trading_dates: list[date]) -> float | None:
    if not instrument_ids or not trading_dates:
        return None
    events = db.scalars(
        select(Event).where(
            Event.instrument_id.in_(instrument_ids),
            Event.event_date.in_(trading_dates),
            Event.source.in_(
                {
                    "mops_material_information",
                    "twse_tpex_official_announcement",
                    "issuer_filing",
                }
            ),
        )
    ).all()
    if not events:
        return None
    date_index = {value: index + 1 for index, value in enumerate(trading_dates)}
    counts = {1: set(), 5: set(), 20: set()}
    for event in events:
        session_no = date_index.get(event.event_date)
        if session_no is None:
            continue
        for window in counts:
            if session_no > len(trading_dates) - window:
                counts[window].add(event.id)
    weighted = 0.50 * len(counts[1]) + 0.30 * len(counts[5]) + 0.20 * len(counts[20])
    return max(0.0, min(1.0, weighted / 3.0))


def _calculate_group_scores(db: Session, score_date: date) -> None:
    benchmark = _benchmark_instrument(db)
    benchmark_returns = _returns_by_window(db, benchmark.id, score_date) if benchmark else {1: None, 5: None, 20: None}
    benchmark_dates = _effective_trading_dates(db, benchmark.id, score_date, 20) if benchmark else []
    groups = db.scalars(select(ThemeGroup).where(ThemeGroup.active.is_(True))).all()
    computed: list[dict[str, Any]] = []

    for group in groups:
        members = _allowed_group_members(group, _effective_memberships(db, group.id, score_date))
        member_metrics: list[dict[str, Any]] = []
        for _membership, instrument in members:
            returns = _returns_by_window(db, instrument.id, score_date)
            if any(returns[window] is None or benchmark_returns[window] is None for window in (1, 5, 20)):
                continue
            features = db.scalar(
                select(TechnicalFeature).where(
                    TechnicalFeature.instrument_id == instrument.id,
                    TechnicalFeature.trading_date == score_date,
                )
            )
            values = features.features_json if features else {}
            prior_volumes = values.get("prior_20_volumes") or []
            current_volume = _safe_float(values.get("volume", None))
            if current_volume is None:
                bar = db.scalar(
                    select(MarketBar).where(
                        MarketBar.instrument_id == instrument.id,
                        MarketBar.trading_date == score_date,
                    )
                )
                current_volume = float(bar.volume) if bar else None
            if not prior_volumes or current_volume is None or sum(prior_volumes) <= 0:
                continue
            excess = {
                window: float(returns[window]) - float(benchmark_returns[window])
                for window in (1, 5, 20)
            }
            volume_1d = current_volume / (sum(prior_volumes) / len(prior_volumes))
            last_five = db.scalars(
                select(MarketBar.volume)
                .where(
                    MarketBar.instrument_id == instrument.id,
                    MarketBar.trading_date <= score_date,
                )
                .order_by(desc(MarketBar.trading_date))
                .limit(5)
            ).all()
            volume_5d = (sum(last_five) / len(last_five)) / (sum(prior_volumes) / len(prior_volumes)) if len(last_five) == 5 else None
            if volume_5d is None:
                continue
            member_metrics.append(
                {
                    "instrument_id": instrument.id,
                    "exchange": instrument.exchange,
                    "symbol": instrument.symbol,
                    "instrument_type": instrument.instrument_type,
                    "etf_category": instrument.etf_category,
                    "excess": excess,
                    "relative_weighted": 0.20 * excess[1] + 0.30 * excess[5] + 0.50 * excess[20],
                    "breadth": {
                        window: 1.0 if excess[window] > 0 else 0.0 for window in (1, 5, 20)
                    },
                    "volume_raw": 0.50 * volume_1d + 0.50 * volume_5d,
                    "hot_group_flow_ratio": _hot_group_institutional_flow_ratio(db, instrument.id, score_date),
                    "margin_change_ratio": _margin_change_ratio(db, instrument.id, score_date),
                }
            )

        eligible = len(member_metrics)
        instrument_ids = [item["instrument_id"] for item in member_metrics]
        if benchmark_dates:
            trading_dates = benchmark_dates
        elif instrument_ids:
            trading_dates = _effective_trading_dates(db, instrument_ids[0], score_date, 20)
        else:
            trading_dates = []
        raw_relative = (
            sum(item["relative_weighted"] for item in member_metrics) / eligible if eligible else None
        )
        relative_1d = sum(item["excess"][1] for item in member_metrics) / eligible if eligible else None
        relative_5d = sum(item["excess"][5] for item in member_metrics) / eligible if eligible else None
        relative_20d = sum(item["excess"][20] for item in member_metrics) / eligible if eligible else None
        breadth = (
            sum(
                0.20 * item["breadth"][1] + 0.30 * item["breadth"][5] + 0.50 * item["breadth"][20]
                for item in member_metrics
            )
            / eligible
            if eligible
            else None
        )
        volume_raw = median(item["volume_raw"] for item in member_metrics) if member_metrics else None
        flow_values = [
            item["hot_group_flow_ratio"]
            for item in member_metrics
            if item["hot_group_flow_ratio"] is not None
            and math.isfinite(item["hot_group_flow_ratio"])
        ]
        flow_coverage = {
            "available": len(flow_values),
            # Coverage is measured against every type/category-eligible
            # membership, not only members that happened to have a usable
            # technical row.  Otherwise a group with 1 chip row and 99
            # missing rows could look like a complete institutional signal.
            "eligible": len(members),
            "technical_metrics": eligible,
            "ratio": len(flow_values) / len(members) if members else 0.0,
            "complete": bool(members and len(flow_values) == len(members)),
        }
        flow_raw = sum(flow_values) / len(members) if flow_coverage["complete"] else None
        catalyst = _catalyst_value(db, instrument_ids, score_date, trading_dates)
        categories = sorted(
            {
                item["etf_category"]
                for item in member_metrics
                if item["etf_category"]
            }
        )
        leaderboard = "etf:" + (categories[0] if categories else "unclassified") if group.group_type in {"etf", "instrument_theme"} or "etf" in group.name.lower() else "equity"
        candidate_rows = sorted(
            member_metrics,
            key=lambda item: (item["excess"][20], item["excess"][5], item["symbol"]),
            reverse=True,
        )
        candidates = (
            [
                {key: item[key] for key in ("instrument_id", "exchange", "symbol")}
                for item in candidate_rows[:MAX_GROUP_CANDIDATES]
            ]
            if eligible >= MIN_GROUP_MEMBERS
            else []
        )
        values: dict[str, float | None] = {
            "relative_return": raw_relative,
            "breadth": breadth,
            "volume_strength": volume_raw,
            "institutional_flow": flow_raw,
            "catalyst": catalyst,
        }
        computed.append(
            {
                "group": group,
                "eligible": eligible,
                "member_count": len(members),
                "leaderboard": leaderboard,
                "raw_values": values,
                "relative_1d": relative_1d,
                "relative_5d": relative_5d,
                "relative_20d": relative_20d,
                "member_metrics": member_metrics,
                "candidates": candidates,
                "flow_coverage": flow_coverage,
            }
        )

    # Percentiles are cross-sectional within the canonical equity/ETF
    # leaderboard, never across a mixed set of companies and ETFs.
    for item in computed:
        raw = item["raw_values"]
        peers = [other for other in computed if other["leaderboard"] == item["leaderboard"]]
        normalized = {
            "relative_return": _percentile(raw["relative_return"], [other["raw_values"]["relative_return"] for other in peers]),
            "breadth": raw["breadth"],
            "volume_strength": _percentile(raw["volume_strength"], [other["raw_values"]["volume_strength"] for other in peers]),
            "institutional_flow": _percentile(raw["institutional_flow"], [other["raw_values"]["institutional_flow"] for other in peers]),
            "catalyst": raw["catalyst"],
        }
        score_row = db.scalar(
            select(GroupDailyScore).where(
                GroupDailyScore.group_id == item["group"].id,
                GroupDailyScore.trading_date == score_date,
            )
        )
        if not score_row:
            score_row = GroupDailyScore(group_id=item["group"].id, trading_date=score_date)
            db.add(score_row)
        score_row.relative_return_1d = item["relative_1d"]
        score_row.relative_return_5d = item["relative_5d"]
        score_row.relative_return_20d = item["relative_20d"]
        score_row.relative_return = item["relative_20d"]
        score_row.breadth = normalized["breadth"]
        score_row.volume_strength = normalized["volume_strength"]
        score_row.institutional_flow = normalized["institutional_flow"]
        score_row.catalyst = normalized["catalyst"]
        if item["eligible"] < MIN_GROUP_MEMBERS:
            score_row.score = None
            score_row.rank = None
            score_row.data_quality = "insufficient_members"
        else:
            score_row.score = calculate_group_score(normalized)
            quality = group_score_quality(normalized)
            score_row.data_quality = (
                "partial" if not item["flow_coverage"]["complete"] and quality == "complete" else quality
            )
            if score_row.score is None:
                score_row.rank = None
        score_row.eligible_members = item["eligible"]
        score_row.details_json = {
            "benchmark": "TAIEX",
            "benchmark_returns": benchmark_returns,
            "member_return_identity_version": "instrument-id-v1",
            "member_returns": [
                {
                    "instrument_id": member["instrument_id"],
                    "exchange": member["exchange"],
                    "symbol": member["symbol"],
                    "excess_return_1d": member["excess"][1],
                    "excess_return_5d": member["excess"][5],
                    "excess_return_20d": member["excess"][20],
                    "volume_strength_raw": member["volume_raw"],
                    # Keep the legacy field for consumers of the group detail
                    # payload, while explicitly recording the hot-group
                    # denominator so it cannot be confused with a strategy
                    # evaluator's average-daily-turnover ratio.
                    "institutional_flow_to_turnover_ratio_5d": member["hot_group_flow_ratio"],
                    "hot_group_institutional_flow_to_sum_turnover_ratio_5d": member["hot_group_flow_ratio"],
                    "institutional_flow_ratio_denominator": "sum_turnover_20d",
                    "margin_balance_change_ratio_5d": member["margin_change_ratio"],
                }
                for member in item["member_metrics"]
            ],
            "candidate_identity_version": "instrument-id-v1",
            "candidate_instruments": (
                item["candidates"][:MAX_GROUP_CANDIDATES]
                if score_row.score is not None
                else []
            ),
            "candidate_symbols": (
                [candidate["symbol"] for candidate in item["candidates"][:MAX_GROUP_CANDIDATES]]
                if score_row.score is not None
                else []
            ),
            "minimum_candidate_policy": [MIN_GROUP_CANDIDATES, MAX_GROUP_CANDIDATES],
            "raw_values": raw,
            "normalized_values": normalized,
            "institutional_flow_coverage": item["flow_coverage"],
            "leaderboard": item["leaderboard"],
            "weights": GROUP_SCORE_WEIGHTS,
            "methodology": HOT_GROUP_CONFIG["components"],
        }
        item["score_row"] = score_row

    for item in computed:
        if item.get("score_row") is None or item["score_row"].score is None:
            continue
        peers = [
            other["score_row"]
            for other in computed
            if other["leaderboard"] == item["leaderboard"]
            and other.get("score_row") is not None
            and other["score_row"].score is not None
        ]
        for rank, row in enumerate(sorted(peers, key=lambda value: value.score, reverse=True), start=1):
            row.rank = rank


def _ensure_strategies(db: Session) -> dict[str, StrategyVersion]:
    snapshots = canonical_config_snapshot()
    versions: dict[str, StrategyVersion] = {}
    for key, config in CANONICAL_CONFIGS.items():
        strategy = db.scalar(
            select(StrategyVersion).where(
                StrategyVersion.name == config["name"],
                StrategyVersion.version == config["version"],
            )
        )
        if not strategy:
            strategy = StrategyVersion(
                name=config["name"],
                version=config["version"],
                kind=config["kind"],
                config_json=snapshots[key],
                canonical_config_snapshot=snapshots[key],
            )
            db.add(strategy)
        elif not strategy.canonical_config_snapshot:
            # Populate the audit snapshot only; never mutate a legacy 1.0
            # config in place.  The canonical 1.0.0 row is a new version.
            strategy.canonical_config_snapshot = snapshots[key]
        versions[key] = strategy
    db.flush()
    return versions


def _next_execution_date(
    db: Session,
    instrument_id: int,
    signal_date: date,
    *,
    max_date: date | None = None,
) -> date | None:
    return db.scalar(
        select(MarketBar.trading_date)
        .where(
            MarketBar.instrument_id == instrument_id,
            MarketBar.trading_date > signal_date,
            *([MarketBar.trading_date <= max_date] if max_date is not None else []),
        )
        .order_by(MarketBar.trading_date)
        .limit(1)
    )


def _best_group_for_signal(db: Session, instrument_id: int, signal_date: date) -> GroupDailyScore | None:
    """Return a usable as-of group return for an individual strategy.

    ``hot_group_v1`` may be unranked when one of its discovery components
    (for example full-membership institutional coverage or catalyst events)
    is incomplete.  Breakout/pullback only require the verified group excess
    return, so the product ranking gate must not turn those unrelated
    components into strategy input failures.  Keep the membership, active
    group, TAIEX provenance, minimum-member, and finite-return gates here;
    the product ``/themes`` and action qualification gates remain stricter.
    """
    rows = db.execute(
        select(GroupDailyScore)
        .join(GroupMembership, GroupMembership.group_id == GroupDailyScore.group_id)
        .join(ThemeGroup, ThemeGroup.id == GroupDailyScore.group_id)
        .where(
            GroupMembership.instrument_id == instrument_id,
            GroupMembership.valid_from <= signal_date,
            (GroupMembership.valid_to.is_(None) | (GroupMembership.valid_to >= signal_date)),
            ThemeGroup.active.is_(True),
            GroupDailyScore.trading_date == signal_date,
            GroupDailyScore.relative_return_20d.is_not(None),
            GroupDailyScore.eligible_members >= MIN_GROUP_MEMBERS,
        )
        .order_by(desc(GroupDailyScore.score), desc(GroupDailyScore.relative_return_20d))
    ).scalars().all()
    for row in rows:
        details = row.details_json or {}
        if details.get("benchmark") != "TAIEX":
            continue
        if _safe_float(row.relative_return_20d) is None:
            continue
        return row
    return None


def _resolve_group_member_return(
    db: Session, group_score: GroupDailyScore | None, instrument: Instrument, signal_date: date,
) -> tuple[int | float | None, dict[str, Any]]:
    """Resolve versioned member evidence without guessing an exchange identity."""
    requested = {"instrument_id": instrument.id, "exchange": instrument.exchange, "symbol": instrument.symbol}
    audit = {
        "version": "group-member-return-lookup/v1",
        "member_return_identity_version": None,
        "group_id": group_score.group_id if group_score else None,
        "group_score_date": group_score.trading_date.isoformat() if group_score else None,
        "requested": requested, "matched": None, "mode": "rejected", "reason": None,
    }

    def finish(reason: str, value: int | float | None = None):
        audit["reason"] = reason
        if value is None:
            audit["mode"] = "rejected"
        if value is not None:
            audit["matched"] = dict(requested)
        return value, audit

    if group_score is None:
        return finish("group_missing")
    if group_score.trading_date != signal_date:
        return finish("score_date_mismatch")
    details = group_score.details_json
    if not isinstance(details, dict):
        return finish("invalid_details")
    marker = details.get("member_return_identity_version")
    audit["member_return_identity_version"] = marker
    rows = details.get("member_returns")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        return finish("invalid_member_returns")
    if "member_return_identity_version" in details:
        audit["mode"] = "instrument_id"
        if marker != "instrument-id-v1":
            return finish("unsupported_identity_version")
        ids, pairs = set(), set()
        for row in rows:
            row_id, exchange, symbol = row.get("instrument_id"), row.get("exchange"), row.get("symbol")
            if (type(row_id) is not int or row_id <= 0 or type(exchange) is not str
                    or not exchange or type(symbol) is not str or not symbol):
                return finish("invalid_member_identity")
            if row_id in ids or (exchange, symbol) in pairs:
                return finish("duplicate_member_identity")
            ids.add(row_id)
            pairs.add((exchange, symbol))
        matches = [row for row in rows if row["instrument_id"] == instrument.id]
        if not matches:
            return finish("member_not_found")
        member = matches[0]
        if member["exchange"] != instrument.exchange or member["symbol"] != instrument.symbol:
            return finish("member_identity_conflict")
    else:
        audit["mode"] = "legacy_symbol_unique"
        if any("instrument_id" in row or "exchange" in row for row in rows):
            return finish("unversioned_member_identity")
        if any(type(row.get("symbol")) is not str or not row["symbol"] for row in rows):
            return finish("invalid_legacy_identity")
        group = db.get(ThemeGroup, group_score.group_id)
        if group is None:
            return finish("group_missing")
        members = _allowed_group_members(group, _effective_memberships(db, group.id, signal_date))
        matching_ids = {item.id for _membership, item in members if item.symbol == instrument.symbol}
        if matching_ids != {instrument.id}:
            return finish("legacy_membership_ambiguous_or_missing")
        matches = [row for row in rows if row["symbol"] == instrument.symbol]
        if len(matches) != 1:
            return finish("legacy_return_ambiguous_or_missing")
        member = matches[0]
    value = member.get("excess_return_20d")
    if type(value) not in (int, float):
        return finish("invalid_member_return")
    try:
        if not math.isfinite(value):
            return finish("invalid_member_return")
    except OverflowError:
        return finish("invalid_member_return")
    return finish("matched", value)


def _risk_levels(entry: float, atr: float | None) -> tuple[float, float, float, float]:
    risk = max((atr or entry * 0.02) * 1.0, entry * 0.01)
    invalid = max(0.01, entry - risk)
    target_1 = entry + risk * 1.6
    target_2 = entry + risk * 3.0
    return round(entry, 2), round(invalid, 2), round(target_1, 2), round(target_2, 2)


def _set_signal_status(signal: Signal, next_status: str) -> None:
    if signal.status == next_status:
        return
    # A later retry may fill data that was previously incomplete.  Follow the
    # declared lifecycle through observation before promoting it to a new
    # actionable state; never bypass the domain transition contract.
    if signal.status in {"data_incomplete", "invalid_levels"} and next_status == "conditional":
        signal.status = "observation"
    # Tracking may discover an outcome on the first executable session.  The
    # canonical lifecycle still requires conditional -> active before moving
    # to target/invalid/incomparable, so explicitly walk those intermediate
    # states instead of bypassing the domain contract.
    if next_status in {"active", "target_1_hit", "target_2_hit", "invalidated", "incomparable"}:
        if signal.status in {"data_incomplete", "invalid_levels"}:
            signal.status = "observation"
        if signal.status == "observation":
            signal.status = "conditional"
        if signal.status == "conditional" and next_status != "active":
            signal.status = "active"
    result = validate_signal_status_transition(signal.status, next_status)
    if result.valid:
        signal.status = next_status


def _upsert_signal_for_strategy(
    db: Session,
    *,
    instrument: Instrument,
    signal_date: date,
    strategies: dict[str, StrategyVersion],
    strategy_key: str,
    namespace: str = "analysis",
    data_cutoff: date | None = None,
    capture: Any = None,
) -> bool:
    bar = db.scalar(
        select(MarketBar).where(
            MarketBar.instrument_id == instrument.id,
            MarketBar.trading_date == signal_date,
        )
    )
    if not bar:
        return False
    feature = db.scalar(
        select(TechnicalFeature).where(
            TechnicalFeature.instrument_id == instrument.id,
            TechnicalFeature.trading_date == signal_date,
        )
    )
    values = feature.features_json if feature else {}
    raw_bar_count = values.get("bar_count_60d", values.get("bar_count", 0))
    try:
        bar_count = int(raw_bar_count)
    except (TypeError, ValueError):
        bar_count = 0
    eligible, eligibility_reason = instrument_eligibility(
        instrument.instrument_type,
        bar_count,
        instrument.etf_category,
    )
    group_score = _best_group_for_signal(db, instrument.id, signal_date)
    group_excess, group_member_return_lookup = _resolve_group_member_return(db, group_score, instrument, signal_date)
    strategy_flow_ratio = _strategy_institutional_flow_to_average_turnover_ratio(
        db,
        instrument.id,
        signal_date,
    )
    margin_ratio = _margin_change_ratio(db, instrument.id, signal_date)
    prior_highs = values.get("prior_20_highs")
    prior_volumes = values.get("prior_20_volumes")
    close = _safe_float(bar.close)
    volume = _safe_float(bar.volume)
    ma20 = _safe_float(values.get("ma20"))
    ma60 = _safe_float(values.get("ma60"))
    breakout_arguments = dict(
        close=close,
        prior_highs=prior_highs,
        volume=volume,
        prior_volumes=prior_volumes,
        group_excess_return_20d=group_excess,
        institutional_flow_to_turnover_ratio_5d=strategy_flow_ratio,
        margin_balance_change_ratio_5d=margin_ratio,
    )
    input_provenance = None
    capture_mode = getattr(capture, "input_provenance", None) if capture is not None else None
    if capture_mode in ("selected-bar/v1", "selected-bar-prior-volumes/v1"):
        selected_bar = capture.selected_bar_provenance(
            db, bar=bar, instrument=instrument, signal_date=signal_date,
            close=close, volume=volume,
        )
        input_provenance = selected_bar
        if capture_mode == "selected-bar-prior-volumes/v1":
            prior_input = capture.prior_volumes_provenance(
                db, instrument=instrument, feature=feature, signal_date=signal_date,
                arguments=breakout_arguments,
            )
            input_provenance = {"selected_bar": selected_bar, "prior_volumes": prior_input}
    if capture is not None:
        if input_provenance is None:
            capture.before("breakout_v1", breakout_arguments)
        else:
            capture.before("breakout_v1", breakout_arguments, input_provenance=input_provenance)
    breakout = evaluate_breakout_v1(**breakout_arguments)
    if capture is not None:
        capture.after("breakout_v1", breakout)
    pullback_arguments = dict(
        bar_count=bar_count,
        close=close,
        ma20=ma20,
        ma60=ma60,
        volume=volume,
        prior_volumes=prior_volumes,
        group_excess_return_20d=group_excess,
        institutional_flow_to_turnover_ratio_5d=strategy_flow_ratio,
        margin_balance_change_ratio_5d=margin_ratio,
    )
    if capture is not None:
        if input_provenance is None:
            capture.before("pullback_v1", pullback_arguments)
        else:
            capture.before("pullback_v1", pullback_arguments, input_provenance=input_provenance)
    pullback = evaluate_pullback_v1(**pullback_arguments)
    if capture is not None:
        capture.after("pullback_v1", pullback)
    chosen_kind = "breakout" if strategy_key == "breakout_v1" else "pullback"
    selected = breakout if strategy_key == "breakout_v1" else pullback
    chosen = selected
    if not chosen.passed:
        chosen = None

    atr = _safe_float(values.get("atr14"))
    reference_entry: float | None = None
    breakout_price: float | None = None
    pullback_low: float | None = None
    pullback_high: float | None = None
    invalid_price: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    if chosen is not None and close is not None:
        if chosen_kind == "breakout":
            prior_high = max(prior_highs[-20:]) if prior_highs and len(prior_highs) >= 20 else close
            entry, invalid_price, target_1, target_2 = _risk_levels(max(close, float(prior_high)), atr)
            breakout_price = entry
        else:
            entry = round(close, 2)
            support = ma20 or close
            zone_width = max((atr or close * 0.01) * 0.5, close * 0.005)
            pullback_low = round(max(0.01, support - zone_width), 2)
            pullback_high = round(support + zone_width, 2)
            reference_entry, invalid_price, target_1, target_2 = _risk_levels(entry, atr)
    entry_type = chosen_kind
    validation = validate_signal_levels(
        entry_type=entry_type,
        reference_entry=reference_entry,
        breakout_price=breakout_price,
        invalid_price=invalid_price,
        target_1=target_1,
        target_2=target_2,
    )
    missing_reasons = list(
        dict.fromkeys(
            list(chosen.reasons if chosen is not None and chosen.state == "data_incomplete" else ())
            + list(
                breakout.reasons
                if strategy_key == "breakout_v1" and breakout.state == "data_incomplete"
                else pullback.reasons
                if strategy_key == "pullback_v1" and pullback.state == "data_incomplete"
                else ()
            )
        )
    )
    if not eligible and eligibility_reason:
        missing_reasons.insert(0, eligibility_reason)
    if group_score is None:
        missing_reasons.append("effective_group_score_missing_or_under_minimum_members")
    if bar.is_suspended:
        missing_reasons.append("signal_day_suspended")

    if not validation.valid and chosen is not None:
        status = "invalid_levels"
    elif chosen is not None and chosen.passed and eligible and not missing_reasons:
        status = "conditional"
    elif missing_reasons or selected.state == "data_incomplete":
        status = "data_incomplete"
    else:
        status = "observation"
    # An observation with no actionable setup is still a valid contract output;
    # it must not receive fabricated price levels or a confidence score.
    if status == "observation":
        reference_entry = breakout_price = pullback_low = pullback_high = None
        invalid_price = target_1 = target_2 = None

    strategy = strategies[strategy_key]
    signal_key = (
        f"{namespace}-{instrument.exchange}-{instrument.symbol}-"
        f"{signal_date.isoformat()}-{strategy.name}-{strategy.version}"
    )
    signal = db.scalar(select(Signal).where(Signal.signal_key == signal_key))
    existing_confidence = signal.confidence if signal else None
    existing_evidence = (
        dict(signal.rule_evidence_json)
        if signal and isinstance(signal.rule_evidence_json, dict)
        else {}
    )
    if not signal:
        # SQLAlchemy applies mapped-column defaults at INSERT time.  Set the
        # lifecycle's initial state explicitly so the domain transition from
        # observation to conditional is evaluated for a brand-new signal too.
        signal = Signal(
            signal_key=signal_key,
            signal_date=signal_date,
            instrument_id=instrument.id,
            status="observation",
        )
        db.add(signal)
    _set_signal_status(signal, status)
    signal.signal_date = signal_date
    signal.instrument_id = instrument.id
    signal.strategy_version_id = strategies[strategy_key].id
    signal.entry_type = entry_type
    signal.reference_entry = reference_entry
    signal.pullback_low = pullback_low
    signal.pullback_high = pullback_high
    signal.breakout_price = breakout_price
    signal.invalid_price = invalid_price
    signal.target_1 = target_1
    signal.target_2 = target_2
    # New rows deliberately leave the nullable legacy field empty.  If a
    # same-key historical row already has a numeric value, keep it intact so a
    # rerun cannot rewrite v1's stored result; the evidence marker makes its
    # non-calibrated meaning explicit to readers.
    if existing_confidence is None:
        signal.confidence = None
        confidence_semantics = dict(SIGNAL_CONFIDENCE_SEMANTICS)
    else:
        signal.confidence = existing_confidence
        confidence_semantics = signal_confidence_semantics(
            existing_confidence,
            existing_evidence,
            strategy_name=strategy.name,
            strategy_version=strategy.version,
        )
    signal.rationale = "; ".join(
        [
            f"breakout={breakout.state}:{','.join(breakout.reasons)}",
            f"pullback={pullback.state}:{','.join(pullback.reasons)}",
            f"group={group_score.group_id if group_score else 'missing'}",
            f"missing={','.join(missing_reasons)}" if missing_reasons else "required inputs complete",
        ]
    )
    signal.data_cutoff = f"{signal_date.isoformat()} 13:30 Asia/Taipei"
    signal.source_report = bar.source
    signal.earliest_execution_date = _next_execution_date(
        db,
        instrument.id,
        signal_date,
        max_date=data_cutoff,
    )
    signal.data_quality = "complete" if status in {"conditional", "observation"} and not missing_reasons else "incomplete"
    signal.rule_evidence_json = {
        # Preserve legacy/audit-only keys while refreshing the canonical fields
        # below for the current evaluation.
        **existing_evidence,
        "strategy": strategy_key,
        "strategy_version": strategy.version,
        "group_member_return_lookup": group_member_return_lookup,
        "confidence_semantics": confidence_semantics,
        "actionable": status == "conditional",
        "breakout": {"state": breakout.state, "reasons": breakout.reasons},
        "pullback": {"state": pullback.state, "reasons": pullback.reasons},
        "inputs": {
            "prior_20_highs": prior_highs,
            "prior_20_volumes": prior_volumes,
            "group_excess_return_20d": group_excess,
            # The strategy contract normalizes five-day institutional flow by
            # average daily turnover across the prior twenty sessions.  This
            # is intentionally different from hot_group_v1's sum-turnover
            # denominator, and the denominator is persisted with the evidence.
            "institutional_flow_to_turnover_ratio_5d": strategy_flow_ratio,
            "strategy_institutional_flow_to_average_turnover_ratio_5d": strategy_flow_ratio,
            "institutional_flow_ratio_denominator": "average_daily_turnover_20d",
            "margin_balance_change_ratio_5d": margin_ratio,
            "bar_count_60d": bar_count,
            "ma20": ma20,
            "ma60": ma60,
        },
        "risk_validation": {"valid": validation.valid, "errors": validation.errors},
        "execution": {
            "signal_time": "T_close",
            "earliest": signal.earliest_execution_date.isoformat() if signal.earliest_execution_date else None,
            "fill_policy": "next_session_open_or_better_plus_adverse_slippage",
            "execution_slippage_bps": EXECUTION_SLIPPAGE_BPS,
            "round_trip_transaction_cost_bps": ROUND_TRIP_TRANSACTION_COST_BPS,
            "return_measure": "adjusted_close_divided_by_filled_entry_minus_one_minus_round_trip_cost",
        },
    }
    if capture is not None:
        capture.persist(db, signal=signal, instrument=instrument, strategy=strategy,
                        strategy_key=strategy_key, namespace=namespace)
    return True


def _upsert_signal(
    db: Session,
    *,
    instrument: Instrument,
    signal_date: date,
    strategies: dict[str, StrategyVersion],
    namespace: str = "analysis",
    data_cutoff: date | None = None,
    capture: Any = None,
) -> bool:
    """Persist one auditable result per canonical strategy and session."""

    written = False
    for strategy_key in ("breakout_v1", "pullback_v1"):
        written = (
            _upsert_signal_for_strategy(
                db,
                instrument=instrument,
                signal_date=signal_date,
                strategies=strategies,
                strategy_key=strategy_key,
                namespace=namespace,
                data_cutoff=data_cutoff,
                capture=capture,
            )
            or written
        )
    return written


def _generate_signals(
    db: Session,
    signal_date: date,
    strategies: dict[str, StrategyVersion],
    *,
    namespace: str = "analysis",
    data_cutoff: date | None = None,
    capture: Any = None,
) -> int:
    instruments = db.scalars(
        select(Instrument).where(Instrument.instrument_type.in_({"stock", "etf", "ipo"}), Instrument.status == "active")
    ).all()
    count = 0
    for instrument in instruments:
        count += int(
            _upsert_signal(
                db,
                instrument=instrument,
                signal_date=signal_date,
                strategies=strategies,
                namespace=namespace,
                data_cutoff=data_cutoff,
                capture=capture,
            )
        )
    return count


def _upsert_raw_payload(db: Session, run: IngestionRun, payload: FetchedPayload) -> RawPayload:
    # SQLAlchemy's timestamp default must not turn missing capture evidence
    # into an apparently valid observation time.
    if not isinstance(payload.collected_at, datetime):
        raise OfficialDataError("raw capture timestamp is missing or invalid")
    row = db.scalar(
        select(RawPayload).where(
            RawPayload.ingestion_run_id == run.id,
            RawPayload.source == payload.source,
            RawPayload.endpoint == payload.endpoint,
            RawPayload.sha256 == payload.sha256,
        )
    )
    if row:
        return row
    row = RawPayload(
        ingestion_run_id=run.id,
        source=payload.source,
        endpoint=payload.endpoint,
        payload_path=str(payload.payload_path),
        sha256=payload.sha256,
        data_as_of=payload.data_as_of,
        collected_at=(payload.collected_at.astimezone(timezone.utc).replace(tzinfo=None)
                      if payload.collected_at.tzinfo is not None else payload.collected_at),
    )
    db.add(row)
    db.flush()
    return row


def _upsert_official_instrument(db: Session, record: InstrumentRecord) -> Instrument:
    return get_or_create_instrument(
        db,
        record.symbol,
        record.name,
        record.instrument_type,
        record.etf_category,
        record.listing_date,
        exchange=record.exchange,
        industry=record.industry,
        source="official",
    )


def _upsert_official_bar(db: Session, instrument: Instrument, record: BarRecord, raw_payload_id: int | None) -> MarketBar:
    bar = db.scalar(
        select(MarketBar).where(
            MarketBar.instrument_id == instrument.id,
            MarketBar.trading_date == record.trading_date,
        )
    )
    if not bar:
        bar = MarketBar(instrument_id=instrument.id, trading_date=record.trading_date)
        db.add(bar)
    bar.open = record.open
    bar.high = record.high
    bar.low = record.low
    bar.close = record.close
    bar.adj_close = record.adj_close or record.close
    bar.volume = record.volume
    bar.turnover = record.turnover
    bar.turnover_status = record.turnover_status
    bar.turnover_reason = record.turnover_reason
    bar.source = record.source
    bar.data_as_of = _as_datetime(record.data_as_of, record.trading_date)
    bar.collected_at = datetime.utcnow()
    bar.raw_payload_id = raw_payload_id
    bar.is_suspended = record.is_suspended
    return bar


def _upsert_official_chip(
    db: Session,
    record: Any,
    instruments: dict[tuple[str, str], Instrument],
    raw_payload_id: int | None,
) -> bool:
    """Persist one official chip snapshot without manufacturing missing values."""

    instrument = instruments.get((record.exchange, record.symbol))
    if not instrument or instrument.instrument_type == "index":
        return False
    row = db.scalar(
        select(ChipSnapshot).where(
            ChipSnapshot.instrument_id == instrument.id,
            ChipSnapshot.trading_date == record.trading_date,
        )
    )
    if not row:
        row = ChipSnapshot(
            instrument_id=instrument.id,
            trading_date=record.trading_date,
        )
        db.add(row)
    row.foreign_buy = _safe_float(record.foreign_buy)
    row.trust_buy = _safe_float(record.trust_buy)
    row.dealer_buy = _safe_float(record.dealer_buy)
    row.margin_balance = _safe_float(record.margin_balance)
    row.margin_change = _safe_float(record.margin_change)
    row.source = record.source
    row.data_as_of = _as_datetime(record.data_as_of, record.trading_date)
    row.collected_at = datetime.utcnow()
    row.raw_payload_id = raw_payload_id
    return True


def _upsert_action(db: Session, action: ActionRecord, instruments: dict[tuple[str, str], Instrument], raw_payload_id: int | None) -> None:
    instrument = instruments.get((action.exchange, action.symbol))
    if not instrument:
        return
    row = db.scalar(
        select(CorporateAction).where(
            CorporateAction.instrument_id == instrument.id,
            CorporateAction.action_date == action.action_date,
            CorporateAction.action_type == action.action_type,
        )
    )
    if not row:
        row = CorporateAction(
            instrument_id=instrument.id,
            action_date=action.action_date,
            action_type=action.action_type,
        )
        db.add(row)
    row.cash_dividend = action.cash_dividend
    row.stock_dividend_ratio = action.stock_dividend_ratio
    row.split_ratio = action.split_ratio
    row.reference_price = action.reference_price
    row.details_json = action.details
    row.source = action.exchange.lower()
    row.raw_payload_id = raw_payload_id
    row.data_as_of = action.action_date.isoformat()


def _upsert_fundamental(
    db: Session,
    fundamental: FundamentalRecord,
    instruments: dict[tuple[str, str], Instrument],
    raw_payload_id: int | None,
) -> None:
    instrument = instruments.get((fundamental.exchange, fundamental.symbol))
    if not instrument:
        return
    row = db.scalar(
        select(FundamentalSnapshot).where(
            FundamentalSnapshot.instrument_id == instrument.id,
            FundamentalSnapshot.period_end == fundamental.period_end,
            FundamentalSnapshot.fiscal_period == fundamental.fiscal_period,
        )
    )
    if not row:
        row = FundamentalSnapshot(
            instrument_id=instrument.id,
            period_end=fundamental.period_end,
            fiscal_period=fundamental.fiscal_period,
        )
        db.add(row)
    row.announcement_date = fundamental.announcement_date
    row.revenue = fundamental.revenue
    row.eps = fundamental.eps
    row.roe = fundamental.roe
    row.data_json = fundamental.details
    row.source = fundamental.source
    row.raw_payload_id = raw_payload_id
    row.data_as_of = fundamental.period_end.isoformat()
    row.collected_at = datetime.utcnow()


def _upsert_event(
    db: Session,
    event: EventRecord,
    instruments: dict[tuple[str, str], Instrument],
    raw_payload_id: int | None,
) -> None:
    instrument = instruments.get((event.exchange, event.symbol))
    if not instrument:
        return
    row = db.scalar(
        select(Event).where(
            Event.instrument_id == instrument.id,
            Event.event_date == event.event_date,
            Event.event_type == event.event_type,
            Event.title == event.title,
        )
    )
    if not row:
        row = Event(
            instrument_id=instrument.id,
            event_date=event.event_date,
            event_type=event.event_type,
            title=event.title,
        )
        db.add(row)
    row.description = event.description
    row.details_json = event.details
    row.source = event.source
    row.endpoint = event.endpoint
    row.raw_payload_id = raw_payload_id
    row.data_as_of = event.event_date.isoformat()
    row.collected_at = datetime.utcnow()


_OFFICIAL_INDUSTRY_NAMES_ZH = dict(INDUSTRY_DISPLAY_ZH)

_ETF_CATEGORY_NAMES_ZH = {
    "equity": "股票型 ETF",
    "bond": "債券型 ETF",
    "commodity": "商品型 ETF",
    "leveraged": "槓桿型 ETF",
    "inverse": "反向型 ETF",
    "mixed": "多元資產 ETF",
}


def _official_industry_label(value: str | None, exchange: str | None = None) -> str | None:
    """Return the exchange-normalised official industry label.

    ``exchange`` is optional only for compatibility with older callers that
    already pass a canonical English label.  Numeric source values must carry
    their exchange so TWSE and TPEx code namespaces cannot collide.
    """

    return canonical_industry_label(exchange, value)


def _official_group_id(exchange: str, kind: str, label: str) -> str:
    # Industry and ETF leaderboards are market-wide.  The exchange is kept on
    # the membership provenance rather than partitioning the group identity.
    del exchange
    return canonical_group_id(kind, label)


def _industry_observations(
    db: Session,
    records: Iterable[InstrumentRecord],
    instruments: dict[tuple[str, str], Instrument],
    payloads: Iterable[FetchedPayload],
    score_date: date,
    observed_now: datetime,
    run_id: int | None,
) -> dict[str, Any]:
    """Preflight then project current industry observations, never effective history."""
    def utc(value: datetime) -> datetime:
        if not isinstance(value, datetime):
            raise OfficialDataError("industry observation requires a capture timestamp")
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    now = utc(observed_now)
    captures = list(payloads)
    plans = []
    receipts = []
    seen = set()
    official = "TWSE/TPEx official OpenAPI"
    for record in records:
        if record.instrument_type not in {"stock", "ipo", "etf", "index"}:
            raise OfficialDataError("unsupported instrument type for official membership")
        key = (record.exchange, record.symbol)
        if key in seen:
            raise OfficialDataError("duplicate industry observation for instrument")
        seen.add(key)
        if record.instrument_type not in {"stock", "ipo"}:
            continue
        instrument = instruments.get(key)
        if instrument is None:
            raise OfficialDataError("industry observation has no normalized instrument")
        endpoints = {
            "TWSE": {TWSE_LISTED_ENDPOINT, TWSE_NEW_LISTING_ENDPOINT} if record.instrument_type == "ipo" else {TWSE_LISTED_ENDPOINT},
            "TPEx": {TPEX_LISTED_ENDPOINT},
        }.get(record.exchange, set())
        matches = [p for p in captures if record.payload_sha256 and p.sha256 == record.payload_sha256
                   and p.source == record.exchange.lower() and p.endpoint in endpoints]
        if len(matches) != 1:
            raise OfficialDataError("industry observation requires one authoritative universe capture")
        capture = matches[0]
        captured = utc(capture.collected_at)
        if captured > now:
            raise OfficialDataError("industry observation capture is in the future")
        day = captured.astimezone(timezone(timedelta(hours=8))).date()
        raw = db.scalar(select(RawPayload).where(
            RawPayload.ingestion_run_id == run_id, RawPayload.source == capture.source,
            RawPayload.endpoint == capture.endpoint, RawPayload.sha256 == capture.sha256,
        )) if run_id is not None else None
        if run_id is not None and raw is None:
            raise OfficialDataError("industry observation has no persisted raw capture")
        new_listing_only = capture.endpoint == TWSE_NEW_LISTING_ENDPOINT
        value = str(record.industry or "").strip()
        if not new_listing_only and not value:
            raise OfficialDataError("missing industry classification evidence")
        if not new_listing_only and not (value.isascii() and value.isdigit()):
            raise OfficialDataError("ambiguous nonnumeric industry classification evidence")
        label = canonical_industry_label(record.exchange, value) if value.isascii() and value.isdigit() else None
        receipt = {
            "exchange": record.exchange, "symbol": record.symbol,
            "source": capture.source, "endpoint": capture.endpoint, "sha256": capture.sha256,
            "captured_at_utc": captured.isoformat(), "observed_date": day.isoformat(),
            "score_date": score_date.isoformat(), "raw_payload_id": raw.id if raw else None,
            "stored_raw_collected_at_utc": utc(raw.collected_at).isoformat() if raw else None,
            "time_semantics": "current_source_observation_not_classification_effective_date",
            "raw_time_relationship": "stored_raw_may_be_earlier_identical_content_capture",
            "raw_classification": record.industry,
            "classification_status": "unresolved" if new_listing_only else ("known" if label else "unknown_special_or_unsupported"),
            "status": "unresolved_new_listing_only" if new_listing_only else ("skipped_after_score_date" if day > score_date else "applied"),
        }
        receipts.append(receipt)
        if new_listing_only or day > score_date:
            continue
        target_id = canonical_group_id("industry", label) if label else None
        group = db.get(ThemeGroup, target_id) if target_id else None
        if group and (group.name != f"Industry · {label}" or group.group_type != "official_industry"
                      or group.definition_version != "official-v1" or group.source != official
                      or not group.active):
            raise OfficialDataError("canonical industry group identity conflict")
        periods = db.execute(select(GroupMembership, ThemeGroup).join(ThemeGroup).where(
            GroupMembership.instrument_id == instrument.id,
        )).all()
        history = []
        expected_source = f"{official}; exchange={record.exchange}"
        for membership, parent in periods:
            if membership.source not in {official, f"{official}; exchange=TWSE", f"{official}; exchange=TPEx"}:
                # A manual row at the same unique key cannot be repurposed.
                if target_id == membership.group_id and membership.valid_from == day:
                    raise OfficialDataError("manual membership conflicts with industry observation")
                continue
            if parent.group_type != "official_industry" and not parent.id.startswith("official-industry-"):
                continue
            if membership.source not in {official, expected_source}:
                raise OfficialDataError("official industry membership exchange conflict")
            if membership.valid_from > day or (membership.valid_to is not None and membership.valid_to < membership.valid_from):
                raise OfficialDataError("future or inverted industry membership period")
            history.append(membership)
        history.sort(key=lambda row: row.valid_from)
        for previous, current in zip(history, history[1:]):
            if previous.valid_to is None or previous.valid_to >= current.valid_from:
                raise OfficialDataError("overlapping official industry membership periods")
        active = [row for row in history if row.valid_to is None or row.valid_to >= day]
        current = active[0] if active else None
        if current and current.valid_to is not None:
            raise OfficialDataError("closed industry period overlaps observation")
        if current and current.group_id != target_id and current.valid_from == day:
            raise OfficialDataError("same-day industry transition cannot preserve daily history")
        plans.append((instrument, day, label, target_id, group, current, expected_source))

    # No membership or group mutation until every ordinary record passes.
    for instrument, day, label, target_id, group, current, source in plans:
        if current and current.group_id == target_id:
            continue
        if current:
            current.valid_to = day - timedelta(days=1)
        if target_id:
            if group is None:
                group = db.get(ThemeGroup, target_id)
            if group is None:
                db.add(ThemeGroup(
                    id=target_id, name=f"Industry · {label}", group_type="official_industry",
                    definition_version="official-v1", source=official, active=True,
                    display_name_zh=INDUSTRY_DISPLAY_ZH[label],
                    display_description_zh="依官方共同產業分類建立的市場族群。",
                    display_category="股票族群", name_source="TWSE/TPEx official classification", name_status="official",
                ))
                db.flush()
            _ensure_membership(db, target_id, instrument.id, day, source=source)
            db.flush()
    skipped = sum(r["status"] == "skipped_after_score_date" for r in receipts)
    unresolved = sum(r["status"] == "unresolved_new_listing_only" for r in receipts)
    return {"version": "industry-observation-v1", "observations": receipts,
            "status": "partial" if skipped or unresolved else "observed",
            "scope": "ordinary_industry_only", "skipped_count": skipped, "unresolved_count": unresolved,
            "warnings": (["industry_observation_after_score_date"] if skipped else [])
                        + (["industry_unresolved_new_listing_only"] if unresolved else [])}


def _nonindustry_observations(
    db: Session,
    records: list[InstrumentRecord],
    instruments: dict[tuple[str, str], Instrument],
    captures: list[FetchedPayload],
    score_date: date,
    observed_now: datetime,
    run_id: int | None,
) -> dict[str, Any]:
    """Project ETF heuristics and bounded listing observations in separate domains."""
    official = "TWSE/TPEx official OpenAPI"
    hot_id = canonical_group_id("new-listings", "new-listings")
    results: dict[str, Any] = {
        domain: {"version": f"{domain}-observation-v1", "scope": domain,
                 "observations": [], "status": "observed", "skipped_count": 0,
                 "unresolved_count": 0}
        for domain in ("etf", "newlisting")
    }
    plans = []

    def utc(value: datetime) -> datetime:
        if not isinstance(value, datetime):
            raise OfficialDataError("membership observation requires a capture timestamp")
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    now = utc(observed_now)
    for record in records:
        key = (record.exchange, record.symbol)
        if record.instrument_type == "index":
            for domain in results:
                results[domain]["observations"].append({
                    "exchange": record.exchange, "symbol": record.symbol,
                    "status": "unresolved_synthetic_index", "score_date": score_date.isoformat(),
                    "reason": "no authoritative universe type-transition evidence; history retained",
                })
            continue
        instrument = instruments.get(key)
        if instrument is None:
            raise OfficialDataError("membership observation has no normalized instrument")
        endpoints = ({"TWSE": {TWSE_ETF_ENDPOINT}, "TPEx": {TPEX_ETF_ENDPOINT}}
                     if record.instrument_type == "etf" else
                     {"TWSE": {TWSE_LISTED_ENDPOINT, TWSE_NEW_LISTING_ENDPOINT}
                      if record.instrument_type == "ipo" else {TWSE_LISTED_ENDPOINT},
                      "TPEx": {TPEX_LISTED_ENDPOINT}}).get(record.exchange, set())
        matches = [p for p in captures if record.payload_sha256 and p.sha256 == record.payload_sha256
                   and p.source == record.exchange.lower() and p.endpoint in endpoints]
        if len(matches) != 1:
            raise OfficialDataError("ETF/listing observation requires one authoritative universe capture")
        capture = matches[0]
        captured = utc(capture.collected_at)
        if captured > now:
            raise OfficialDataError("ETF/listing observation capture is in the future")
        day = captured.astimezone(timezone(timedelta(hours=8))).date()
        raw = db.scalar(select(RawPayload).where(
            RawPayload.ingestion_run_id == run_id, RawPayload.source == capture.source,
            RawPayload.endpoint == capture.endpoint, RawPayload.sha256 == capture.sha256,
        )) if run_id is not None else None
        if run_id is not None and raw is None:
            raise OfficialDataError("ETF/listing observation has no persisted raw capture")
        evidence = {
            "exchange": record.exchange, "symbol": record.symbol, "instrument_type": record.instrument_type,
            "source": capture.source, "endpoint": capture.endpoint, "sha256": capture.sha256,
            "captured_at_utc": captured.isoformat(), "observed_date": day.isoformat(),
            "score_date": score_date.isoformat(), "raw_payload_id": raw.id if raw else None,
            "stored_raw_collected_at_utc": utc(raw.collected_at).isoformat() if raw else None,
            "raw_time_relationship": "stored_raw_may_be_earlier_identical_content_capture",
        }
        for domain in results:
            receipt = {**evidence, "status": "applied", "action": "unchanged",
                       "time_semantics": "current_source_observation_not_classification_effective_date"}
            results[domain]["observations"].append(receipt)
            if domain == "etf":
                receipt.update(classification_method="local_heuristic_from_official_universe",
                               classification_method_version="normalize_etf_category-v1",
                               normalized_category=record.etf_category)
            else:
                receipt.update(listing_date=record.listing_date.isoformat() if record.listing_date else None,
                               window_days=60, window_end_inclusive=True,
                               time_semantics="observed_listing_window_no_pre_capture_membership_claim")
            if day > score_date:
                receipt["status"] = "skipped_after_score_date"
                continue
            target_id = None
            expiry = None
            name = None
            if domain == "etf" and record.instrument_type == "etf":
                if record.etf_category not in ETF_CATEGORIES:
                    raise OfficialDataError("missing or ambiguous ETF classification evidence")
                target_id = canonical_group_id("etf", record.etf_category)
                name = f"ETF · {record.etf_category}"
            elif domain == "newlisting" and record.instrument_type in {"stock", "ipo"}:
                if record.listing_date is None:
                    receipt["status"] = "unresolved_missing_listing_date"
                    continue
                expiry = record.listing_date + timedelta(days=60)
                receipt["window_expires_on"] = expiry.isoformat()
                if record.listing_date <= day <= expiry:
                    target_id = hot_id
                    name = "New listings"
            group_type = "etf" if domain == "etf" else "daily_hot_group"
            if domain == "newlisting" and record.instrument_type == "etf" and record.listing_date:
                expiry = record.listing_date + timedelta(days=60)
            group = db.get(ThemeGroup, target_id) if target_id else None
            if group and (group.name != name or group.group_type != group_type
                          or group.definition_version != "official-v1" or group.source != official
                          or not group.active):
                raise OfficialDataError(f"canonical {domain} group identity conflict")
            history = []
            expected_source = f"{official}; exchange={record.exchange}"
            for membership, parent in db.execute(select(GroupMembership, ThemeGroup).join(ThemeGroup).where(
                GroupMembership.instrument_id == instrument.id,
            )).all():
                if membership.source not in {official, f"{official}; exchange=TWSE", f"{official}; exchange=TPEx"}:
                    if membership.group_id == target_id and membership.valid_from == day:
                        raise OfficialDataError(f"manual membership conflicts with {domain} observation")
                    continue
                in_domain = parent.id.startswith("official-etf-") if domain == "etf" else parent.id == hot_id
                if not in_domain:
                    continue
                expected_name = (next((f"ETF · {category}" for category in ETF_CATEGORIES
                                       if canonical_group_id("etf", category) == parent.id), None)
                                 if domain == "etf" else "New listings")
                if (parent.group_type != group_type or parent.source != official
                        or parent.definition_version != "official-v1" or not parent.active
                        or parent.name != expected_name):
                    raise OfficialDataError(f"canonical {domain} history identity conflict")
                if membership.source not in {official, expected_source}:
                    raise OfficialDataError(f"official {domain} membership exchange conflict")
                if membership.valid_from > day or (membership.valid_to is not None and membership.valid_to < membership.valid_from):
                    raise OfficialDataError(f"future or inverted {domain} membership period")
                history.append(membership)
            history.sort(key=lambda row: row.valid_from)
            for previous, current in zip(history, history[1:]):
                if previous.valid_to is None or previous.valid_to >= current.valid_from:
                    raise OfficialDataError(f"overlapping official {domain} membership periods")
            if (record.instrument_type in {"stock", "ipo"} and record.listing_date
                    and record.listing_date > day and history):
                raise OfficialDataError(f"future listing date conflicts with existing {domain} history")
            active = [row for row in history if row.valid_to is None or row.valid_to >= day]
            current = active[0] if active else None
            if current and current.valid_to is not None:
                if not (domain == "newlisting" and current.valid_to == expiry
                        and (target_id == current.group_id or record.instrument_type == "etf")):
                    raise OfficialDataError(f"closed {domain} period overlaps observation or conflicts with expiry")
            if current and current.group_id != target_id and current.valid_from == day:
                raise OfficialDataError(f"same-day {domain} transition cannot preserve daily history")
            # An expired bounded listing row is immutable evidence.  Re-observing
            # the same known event must not extend it into a second interval.
            if domain == "newlisting" and target_id and not current and history:
                if history[-1].valid_to != expiry:
                    raise OfficialDataError("newlisting expiry conflicts with closed history")
            plans.append((domain, instrument, day, target_id, name, group_type, group,
                          current, expiry, expected_source, receipt))

    for domain, instrument, day, target_id, name, group_type, group, current, expiry, source, receipt in plans:
        if current and current.group_id == target_id:
            if domain == "newlisting" and current.valid_to is None:
                current.valid_to = expiry
                receipt["action"] = "legacy_window_cap"
                receipt["historical_limit"] = "existing_start_retained_not_validated_as_point_in_time"
            continue
        if current:
            current.valid_to = day - timedelta(days=1)
            receipt["action"] = "closed_at_observation"
            if domain == "newlisting" and expiry is not None and day > expiry:
                receipt["action"] = "legacy_forward_close"
                receipt["historical_limit"] = "past_out_of_window_membership_retained_not_rewritten"
        if not target_id:
            continue
        group = group or db.get(ThemeGroup, target_id)
        if group is None:
            db.add(ThemeGroup(
                id=target_id, name=name, group_type=group_type, definition_version="official-v1",
                source=official, active=True,
                display_name_zh=(_ETF_CATEGORY_NAMES_ZH.get(name.split("·", 1)[-1].strip(), f"ETF 分類：{name.split('·', 1)[-1].strip()}")
                                 if domain == "etf" else "新上市標的"),
                display_description_zh=("依官方來源文字、代號與名稱推定的本地 ETF 分類。" if domain == "etf"
                                        else "依觀測到的上市日期建立至第 60 日的短期觀察族群。"),
                display_category="ETF" if domain == "etf" else "新上市",
                name_source="local heuristic from official universe" if domain == "etf" else "TWSE/TPEx official listing date",
                name_status="inferred" if domain == "etf" else "official",
            ))
            db.flush()
        db.add(GroupMembership(group_id=target_id, instrument_id=instrument.id, valid_from=day,
                               valid_to=expiry if domain == "newlisting" else None,
                               role="member", confidence=1.0, source=source))
        receipt["action"] = "transitioned" if current else "opened"
        db.flush()
    for result in results.values():
        result["skipped_count"] = sum(r["status"] == "skipped_after_score_date" for r in result["observations"])
        result["unresolved_count"] = sum(r["status"].startswith("unresolved_") for r in result["observations"])
        result["status"] = "partial" if result["skipped_count"] or result["unresolved_count"] else "observed"
    return results


def _ensure_official_groups(
    db: Session,
    records: Iterable[InstrumentRecord],
    instruments: dict[tuple[str, str], Instrument],
    start_date: date,
    score_date: date,
    *,
    payloads: Iterable[FetchedPayload],
    observed_now: datetime,
    run_id: int | None = None,
) -> dict[str, Any]:
    """Atomically project independently scoped industry, ETF and listing evidence.

    begin_nested flushes the caller's pending instrument/bar writes before the
    savepoint; the collector's outer rollback still owns those earlier writes.
    Membership/group mutations made here are rolled back even for direct callers.
    """
    del start_date  # Requested history is never an observation timestamp.
    records, captures = list(records), list(payloads)
    connection = db.connection()
    if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
        # sqlite3 legacy mode does not BEGIN for SELECT or SAVEPOINT.  Without
        # a physical outer transaction, RELEASE would commit this helper's
        # changes even when the caller subsequently rolls back its Session.
        connection.exec_driver_sql("BEGIN")
    with db.begin_nested():
        result = _industry_observations(db, records, instruments, captures, score_date, observed_now, run_id)
        result.update(_nonindustry_observations(db, records, instruments, captures, score_date, observed_now, run_id))
        db.flush()
    return result


def _upsert_quality(
    db: Session,
    entity_type: str,
    entity_key: str,
    as_of_date: date,
    status: str,
    missing_fields: list[str],
    checks: dict[str, Any],
    source: str | None = None,
) -> None:
    row = db.scalar(
        select(DataQuality).where(
            DataQuality.entity_type == entity_type,
            DataQuality.entity_key == entity_key,
            DataQuality.as_of_date == as_of_date,
        )
    )
    if not row:
        row = DataQuality(
            entity_type=entity_type,
            entity_key=entity_key,
            as_of_date=as_of_date,
        )
        db.add(row)
    row.status = status
    row.missing_fields_json = missing_fields
    row.checks_json = checks
    row.source = source
    row.checked_at = datetime.utcnow()


def _official_start_date(end_date: date, months_back: int) -> date:
    if not isinstance(months_back, int) or isinstance(months_back, bool) or not 0 <= months_back <= 3:
        raise ValueError("months_back must be an integer between 0 and 3")
    start = end_date - timedelta(days=30 * months_back)
    if (end_date - start).days > OFFICIAL_MAX_BACKFILL_DAYS:
        raise ValueError("official backfill exceeds the three-month limit")
    return start


def _raw_id_for_digest(raw_ids: dict[tuple[str, str], int], digest: str | None) -> int | None:
    if not digest:
        return None
    for (_source, payload_digest), raw_id in raw_ids.items():
        if payload_digest == digest:
            return raw_id
    return None


def collect(
    end_date: date | None = None,
    *,
    months_back: int = 0,
    adapter: OfficialMarketDataAdapter | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Run official TWSE/TPEx ingestion."""

    init_db()
    score_date = latest_weekday(end_date)
    start_date = _official_start_date(score_date, months_back)
    request_key = f"official-ohlcv:{start_date.isoformat()}:{score_date.isoformat()}"
    now = datetime.utcnow()
    with SessionLocal() as db:
        run = db.scalar(select(IngestionRun).where(IngestionRun.request_key == request_key))
        stored_metadata = (run.metadata_json or {}) if run else {}
        # A market snapshot is not complete merely because security OHLCV
        # rows exist.  TAIEX is the verified-session baseline used by the
        # bounded backfill, so an older successful run without a TAIEX row
        # must be allowed to re-fetch rather than being hidden by the
        # idempotency shortcut.
        if (
            run
            and run.status == "success"
            and run.records > 0
            and int(stored_metadata.get("taiex_records", 0) or 0) > 0
            and not force
        ):
            stored_raw_payloads = db.scalar(
                select(func.count(RawPayload.id)).where(RawPayload.ingestion_run_id == run.id)
            ) or 0
            return {
                "status": "success",
                "date": score_date.isoformat(),
                "data_as_of": run.data_as_of,
                "records": run.records,
                "taiex_records": int(stored_metadata.get("taiex_records", 0) or 0),
                "chips": int(stored_metadata.get("chips", 0) or 0),
                "actions": int(stored_metadata.get("actions", 0) or 0),
                "events": int(stored_metadata.get("events", 0) or 0),
                "fundamentals": int(stored_metadata.get("fundamentals", 0) or 0),
                "raw_payloads": stored_raw_payloads,
                "run_id": run.id,
                "idempotent_reuse": True,
                "industry_membership_observations": stored_metadata.get("industry_membership_observations", {"status": "not_recorded"}),
                "warnings": list(stored_metadata.get("warnings", []) or []),
                "no_data_dates": list(stored_metadata.get("no_data_dates", []) or []),
            }
        if not run:
            run = IngestionRun(
                run_type="collect",
                source="official",
                run_date=score_date,
                status="running",
                records=0,
                request_key=request_key,
                started_at=now,
            )
            db.add(run)
            db.flush()
        else:
            run.run_type = "collect"
            run.source = "official"
            run.run_date = score_date
            run.status = "running"
            run.records = 0
            run.error = None
            run.started_at = now
            run.finished_at = None
        db.commit()
        batch: OfficialBatch | None = None
        active_adapter = adapter or OfficialMarketDataAdapter()
        raw_payload_count = 0
        try:
            batch = active_adapter.fetch(start_date, score_date)
            batch_no_data_dates = sorted(
                {
                    item
                    for item in (batch.no_data_dates or [])
                    if start_date <= item <= score_date
                }
            )
            if not batch.instruments or (not batch.bars and not batch_no_data_dates):
                raise OfficialDataError("official batch contained no instruments or OHLCV")
            if not batch.payloads:
                raise OfficialDataError("official batch did not include raw payload captures")
            raw_ids: dict[tuple[str, str], int] = {}
            stored_raw_ids: set[int] = set()
            for payload in batch.payloads:
                raw = _upsert_raw_payload(db, run, payload)
                raw_ids[(payload.source, payload.sha256)] = raw.id
                stored_raw_ids.add(raw.id)
            raw_payload_count = len(stored_raw_ids)
            # Commit captures before normalization.  If a later parser or
            # upsert fails, the exact source payloads and their run link remain
            # auditable instead of disappearing in the rollback.
            db.commit()
            instruments: dict[tuple[str, str], Instrument] = {}
            for record in batch.instruments:
                instruments[(record.exchange, record.symbol)] = _upsert_official_instrument(db, record)
            normalized_bars = 0
            normalized_non_index_bars = 0
            normalized_index_bars = 0
            normalized_chips = 0
            normalized_dates: list[date] = []
            normalized_instruments: set[tuple[str, str]] = set()
            for record in batch.bars:
                if not start_date <= record.trading_date <= score_date:
                    continue
                instrument = instruments.get((record.exchange, record.symbol))
                if not instrument:
                    continue
                _upsert_official_bar(
                    db,
                    instrument,
                    record,
                    _raw_id_for_digest(raw_ids, record.payload_sha256),
                )
                normalized_bars += 1
                normalized_dates.append(record.trading_date)
                normalized_instruments.add((record.exchange, record.symbol))
                if instrument.instrument_type != "index":
                    normalized_non_index_bars += 1
                else:
                    normalized_index_bars += 1
            normalized_date_set = set(normalized_dates)
            verified_no_data_dates = sorted(
                item for item in batch_no_data_dates if item not in normalized_date_set
            )
            if (
                (normalized_bars == 0 or normalized_non_index_bars == 0)
                and not verified_no_data_dates
            ):
                raise OfficialDataError("official payloads contained no normalized security OHLCV rows")
            for chip in batch.chips:
                normalized_chips += int(
                    _upsert_official_chip(
                        db,
                        chip,
                        instruments,
                        _raw_id_for_digest(raw_ids, chip.payload_sha256),
                    )
                )
            for action in batch.actions:
                _upsert_action(db, action, instruments, _raw_id_for_digest(raw_ids, action.payload_sha256))
            for fundamental in batch.fundamentals:
                _upsert_fundamental(
                    db,
                    fundamental,
                    instruments,
                    _raw_id_for_digest(raw_ids, fundamental.payload_sha256),
                )
            for event in batch.events:
                _upsert_event(
                    db,
                    event,
                    instruments,
                    _raw_id_for_digest(raw_ids, event.payload_sha256),
                )
            event_coverage = dict(batch.event_coverage or {})
            if not event_coverage:
                event_coverage = {
                    "status": "unsupported",
                    "denominator": "date_scoped_event_queries",
                    "verified_dates": [],
                    "empty_dates": [],
                    "unsupported_dates": [],
                    "partial_dates": [],
                    "observed_event_dates": sorted({
                        item.event_date.isoformat() for item in batch.events
                    }),
                    "reason": "event feed did not provide date-scoped coverage evidence",
                }
            industry_result = _ensure_official_groups(
                db,
                batch.instruments,
                instruments,
                start_date,
                score_date,
                payloads=batch.payloads,
                observed_now=datetime.utcnow(),
                run_id=run.id,
            )
            # Project official Events only after memberships are in place so
            # the NewsItem relation carries the effective theme IDs.  The
            # projection is idempotent and retains Event/raw provenance.
            sync_news_from_events(db)
            expected_chip_dates = {
                record.trading_date
                for record in batch.bars
                if start_date <= record.trading_date <= score_date
                and record.exchange in {"TWSE", "TPEx"}
                and record.symbol != "TAIEX"
            }
            expected_chip_symbols = {
                (record.exchange, record.symbol)
                for record in batch.instruments
                if record.instrument_type in {"stock", "etf", "ipo"}
            }
            for exchange in ("TWSE", "TPEx"):
                expected_keys = {
                    (exchange, symbol)
                    for source_exchange, symbol in expected_chip_symbols
                    if source_exchange == exchange
                }
                observed = {
                    (record.exchange, record.symbol, record.trading_date)
                    for record in batch.chips
                    if record.exchange == exchange
                }
                complete_rows = sum(
                    1
                    for record in batch.chips
                    if record.exchange == exchange
                    and all(
                        _safe_float(value) is not None
                        for value in (
                            record.foreign_buy,
                            record.trust_buy,
                            record.dealer_buy,
                            record.margin_balance,
                            record.margin_change,
                        )
                    )
                )
                expected_count = len(expected_chip_dates) * len(expected_keys)
                chip_complete = bool(
                    expected_count
                    and len(observed) >= expected_count
                    and complete_rows == len(observed)
                )
                _upsert_quality(
                    db,
                    "chip_snapshots",
                    exchange,
                    score_date,
                    "complete" if chip_complete else ("partial" if observed else "missing"),
                    [] if chip_complete else ["institutional_flow", "margin_balance"],
                    {
                        "records": sum(1 for record in batch.chips if record.exchange == exchange),
                        "complete_records": complete_rows,
                        "expected_records": expected_count,
                        "coverage": len(observed) / expected_count if expected_count else 0.0,
                        "data_as_of": sorted({record.trading_date.isoformat() for record in batch.chips if record.exchange == exchange}),
                    },
                    source=exchange.lower(),
                )
            for exchange in ("TWSE", "TPEx"):
                event_count = sum(item.exchange == exchange for item in batch.events)
                fundamental_count = sum(item.exchange == exchange for item in batch.fundamentals)
                event_status = event_coverage.get("status")
                event_complete = event_status in {"complete", "verified_empty"}
                _upsert_quality(
                    db,
                    "mops_events",
                    exchange,
                    score_date,
                    "complete" if event_complete else "partial",
                    [] if event_complete else ["events"],
                    {
                        "records": event_count,
                        "endpoint": "official MOPS material information",
                        "coverage": event_coverage,
                    },
                    source=exchange.lower(),
                )
                _upsert_quality(
                    db,
                    "mops_fundamentals",
                    exchange,
                    score_date,
                    "complete" if fundamental_count else "partial",
                    [] if fundamental_count else ["fundamental_snapshots"],
                    {"records": fundamental_count, "endpoint": "official MOPS EPS"},
                    source=exchange.lower(),
                )
            for instrument in instruments.values():
                has_ohlcv = (instrument.exchange, instrument.symbol) in normalized_instruments
                _upsert_quality(
                    db,
                    "instrument",
                    f"{instrument.exchange}:{instrument.symbol}",
                    score_date,
                    "complete" if has_ohlcv else "missing",
                    [] if has_ohlcv else ["ohlcv"],
                    {"source": instrument.exchange, "backfill_start": start_date.isoformat()},
                    source=instrument.exchange.lower(),
                )
            latest_bar_date = max(normalized_dates) if normalized_dates else None
            # A source warning means the official snapshot is usable only as
            # a partial, explicitly qualified state. In particular, a
            # historical MI_INDEX CDN failure must not appear complete merely
            # because the latest requested date happened to be present.
            if latest_bar_date is None and verified_no_data_dates:
                run.status = "skipped"
            else:
                run.status = (
                    "success"
                    if latest_bar_date == score_date
                    and normalized_index_bars > 0
                    and not batch.warnings
                    and not verified_no_data_dates
                    else "partial"
                )
            run.records = normalized_bars
            run.data_as_of = latest_bar_date.isoformat() if latest_bar_date else None
            run.error = None
            run.finished_at = datetime.utcnow()
            run.metadata_json = {
                "records": normalized_bars,
                "taiex_records": normalized_index_bars,
                "chips": normalized_chips,
                "actions": len(batch.actions),
                "events": len(batch.events),
                "fundamentals": len(batch.fundamentals),
                "raw_payloads": raw_payload_count,
                "warnings": list(batch.warnings),
                "no_data_dates": [item.isoformat() for item in verified_no_data_dates],
                "event_coverage": event_coverage,
                "industry_membership_observations": industry_result,
                "industry_observation_history": list(stored_metadata.get("industry_observation_history", [])) + ([stored_metadata["industry_membership_observations"]] if "industry_membership_observations" in stored_metadata else []),
                "industry_failed_attempts": list(stored_metadata.get("industry_failed_attempts", [])),
            }
            missing_run_fields: list[str] = []
            if run.status != "success":
                if latest_bar_date != score_date and not verified_no_data_dates:
                    missing_run_fields.append("requested_session")
                if normalized_index_bars == 0:
                    missing_run_fields.append("taiex")
                if batch.warnings:
                    missing_run_fields.append("official_warnings")
                if verified_no_data_dates:
                    missing_run_fields.append("skipped_non_trading")
            _upsert_quality(
                db,
                "ingestion_run",
                request_key,
                score_date,
                run.status,
                missing_run_fields,
                {
                    "records": normalized_bars,
                    "taiex_records": normalized_index_bars,
                    "chips": normalized_chips,
                    "raw_payloads": raw_payload_count,
                    "requested_data_as_of": batch.data_as_of or score_date.isoformat(),
                    "data_as_of": run.data_as_of,
                    "warnings": batch.warnings,
                    "no_data_dates": [item.isoformat() for item in verified_no_data_dates],
                    "event_coverage": event_coverage,
                },
                source="official",
            )
            db.commit()
            return {
                "status": run.status,
                "date": score_date.isoformat(),
                "start_date": start_date.isoformat(),
                "data_as_of": run.data_as_of,
                "requested_data_as_of": batch.data_as_of or score_date.isoformat(),
                "records": normalized_bars,
                "taiex_records": normalized_index_bars,
                "chips": normalized_chips,
                "chip_records": len(batch.chips),
                "raw_payloads": raw_payload_count,
                "actions": len(batch.actions),
                "events": len(batch.events),
                "fundamentals": len(batch.fundamentals),
                "event_coverage": event_coverage,
                "run_id": run.id,
                "industry_membership_observations": industry_result,
                "warnings": batch.warnings,
                "no_data_dates": [item.isoformat() for item in verified_no_data_dates],
            }
        except Exception as exc:
            db.rollback()
            failed_run = db.get(IngestionRun, run.id)
            if failed_run:
                try:
                    # A failure before the capture commit should still retain
                    # payload metadata.  Official adapters expose captures
                    # made before a later endpoint failed; this keeps the
                    # failed run auditable instead of orphaning raw evidence.
                    captured_payloads = (
                        batch.payloads
                        if batch is not None
                        else list(getattr(active_adapter, "captured_payloads", []))
                    )
                    captured_raw_ids: set[int] = set()
                    raw_persistence_errors: list[dict[str, Any]] = []
                    if captured_payloads:
                        for payload in captured_payloads:
                            try:
                                # A bad capture must not prevent recording the
                                # failed run or persisting the other captures.
                                with db.begin_nested():
                                    captured_raw_id = _upsert_raw_payload(db, failed_run, payload).id
                                captured_raw_ids.add(captured_raw_id)
                            except Exception as raw_exc:
                                raw_persistence_errors.append({"source": payload.source,
                                    "endpoint": payload.endpoint, "sha256": payload.sha256,
                                    "payload_path": str(payload.payload_path),
                                    "reason": f"{type(raw_exc).__name__}: {raw_exc}"})
                    raw_payload_count = len(captured_raw_ids)
                    failed_attempt = {"status": "failed", "error": str(exc), "attempted_at_utc": datetime.utcnow().isoformat(),
                                      "raw_payload_ids": sorted(captured_raw_ids), "raw_persistence_errors": raw_persistence_errors,
                                      "captures": [{"source": p.source, "endpoint": p.endpoint, "sha256": p.sha256, "payload_path": str(p.payload_path),
                                                    "collected_at": p.collected_at.isoformat() if isinstance(p.collected_at, datetime) else None,
                                                    "invalid_timestamp_value": str(p.collected_at) if p.collected_at is not None and not isinstance(p.collected_at, datetime) else None,
                                                    "timestamp_status": "provided" if isinstance(p.collected_at, datetime) else "missing_or_invalid"}
                                                   for p in captured_payloads]}
                    failed_run.metadata_json = {**stored_metadata, "industry_observation_attempt": failed_attempt,
                                                "industry_failed_attempts": list(stored_metadata.get("industry_failed_attempts", [])) + [failed_attempt]}
                    failed_run.status = "failed"
                    failed_run.records = 0
                    failed_run.error = f"{type(exc).__name__}: {exc}"
                    failed_run.finished_at = datetime.utcnow()
                    failed_run.data_as_of = None
                    _upsert_quality(
                        db,
                        "ingestion_run",
                        request_key,
                        score_date,
                        "failed",
                        ["official_payload_normalization"],
                        {"error": failed_run.error, "raw_payloads": raw_payload_count},
                        source="official",
                    )
                    db.commit()
                except Exception:
                    db.rollback()
            return {
                "status": "failed",
                "date": score_date.isoformat(),
                "start_date": start_date.isoformat(),
                "records": 0,
                "raw_payloads": raw_payload_count,
                "run_id": run.id,
                "error": f"{type(exc).__name__}: {exc}",
                "warnings": getattr(locals().get("batch"), "warnings", []),
                "no_data_dates": [
                    item.isoformat()
                    for item in getattr(locals().get("batch"), "no_data_dates", [])
                ],
            }


def analyze() -> dict[str, Any]:
    init_db()
    with SessionLocal() as db:
        result = _analyze_session(db)
        if result.get("status") == "success":
            db.commit()
        return result


def _analyze_session(db: Session, *, capture: Any = None) -> dict[str, Any]:
    """Run analysis in the caller's transaction; only explicit callers capture."""
    latest_run = db.scalar(
        select(IngestionRun).where(
            IngestionRun.run_type == "collect",
            IngestionRun.source == "official",
        )
        .order_by(desc(IngestionRun.updated_at), desc(IngestionRun.id))
        .limit(1)
    )
    if latest_run:
        if latest_run.status != "success" or not latest_run.data_as_of:
            return {
                "status": "skipped",
                "reason": "latest_official_collection_is_not_complete",
                "date": latest_run.data_as_of,
                "signals_upserted": 0,
            }
        try:
            score_date = date.fromisoformat(latest_run.data_as_of[:10])
        except ValueError:
            return {
                "status": "skipped",
                "reason": "latest_official_collection_has_invalid_data_as_of",
                "date": latest_run.data_as_of,
                "signals_upserted": 0,
            }
    else:
        return {"status": "no_data", "signals_upserted": 0}
    instruments = db.scalars(select(Instrument).where(Instrument.status == "active")).all()
    for instrument in instruments:
        if capture is not None and getattr(capture, "input_provenance", None) == "selected-bar-prior-volumes/v1":
            _calculate_features(db, instrument, capture=capture, capture_date=score_date)
        else:
            _calculate_features(db, instrument)
    db.flush()
    _calculate_group_scores(db, score_date)
    strategies = _ensure_strategies(db)
    signals_upserted = _generate_signals(db, score_date, strategies, capture=capture)
    return {"status": "success", "date": score_date.isoformat(), "signals_upserted": signals_upserted}


def _corporate_action_factor(
    actions: list[CorporateAction],
    *,
    fallback_reference_prices: dict[date, float] | None = None,
) -> tuple[float, bool]:
    factor = 1.0
    applied = False
    for action in actions:
        details = action.details_json or {}
        explicit = _safe_float(details.get("price_factor"))
        if explicit is not None and explicit > 0:
            factor *= explicit
            applied = True
            continue
        if action.split_ratio and action.split_ratio > 0:
            # Feeds differ: some publish the ratio as 2 (two post-split
            # shares per old share), while fixtures/normalized records may
            # already publish the raw-price factor 0.5.  Both represent the
            # same signal-basis -> post-action-basis direction.
            factor = factor / action.split_ratio if action.split_ratio > 1 else factor * action.split_ratio
            applied = True
        if action.stock_dividend_ratio and action.stock_dividend_ratio > 0:
            factor /= 1.0 + action.stock_dividend_ratio
            applied = True
        reference_price = action.reference_price
        if reference_price is None and fallback_reference_prices:
            reference_price = fallback_reference_prices.get(action.action_date)
        if (
            action.cash_dividend
            and reference_price
            and reference_price > action.cash_dividend
        ):
            factor *= (reference_price - action.cash_dividend) / reference_price
            applied = True
    return factor, applied


def _buy_fill_with_slippage(price: float | None) -> float | None:
    """Model a documented adverse fill for a long position.

    The source OHLC remains untouched.  The adjusted execution price is only
    used for tracking returns and is recorded in the signal evidence so a
    reviewer can reproduce the net result.
    """

    if price is None or not math.isfinite(price) or price <= 0:
        return None
    return round(price * (1.0 + EXECUTION_SLIPPAGE_BPS / 10_000.0), 8)


def _sell_fill_with_slippage(price: float | None) -> float | None:
    """Model an adverse sell fill for a long position."""

    if price is None or not math.isfinite(price) or price <= 0:
        return None
    return round(price * (1.0 - EXECUTION_SLIPPAGE_BPS / 10_000.0), 8)


def _upsert_evaluation(db: Session, signal: Signal, bar: MarketBar, data: dict[str, Any]) -> SignalEvaluation:
    evaluation = db.scalar(
        select(SignalEvaluation).where(
            SignalEvaluation.signal_id == signal.id,
            SignalEvaluation.session_date == bar.trading_date,
        )
    )
    if not evaluation:
        evaluation = SignalEvaluation(signal_id=signal.id, session_date=bar.trading_date)
        db.add(evaluation)
    for key, value in data.items():
        setattr(evaluation, key, value)
    return evaluation


def _upsert_settlement(db: Session, signal: Signal, horizon: int, data: dict[str, Any]) -> SignalSettlement:
    settlement = db.scalar(
        select(SignalSettlement).where(
            SignalSettlement.signal_id == signal.id,
            SignalSettlement.horizon == horizon,
        )
    )
    if not settlement:
        settlement = SignalSettlement(signal_id=signal.id, horizon=horizon)
        db.add(settlement)
    for key, value in data.items():
        setattr(settlement, key, value)
    return settlement


def _suspension_gap_between(
    db: Session,
    instrument_id: int,
    previous_date: date,
    current_date: date,
) -> bool:
    """Detect an official suspension interval hidden by a missing bar."""

    if current_date <= previous_date:
        return False
    events = db.scalars(
        select(Event).where(
            Event.instrument_id == instrument_id,
            Event.event_type == "suspension",
            Event.event_date <= current_date,
        )
    ).all()
    for event in events:
        details = event.details_json or {}
        start = event.event_date
        end_text = details.get("resumed_date") or details.get("interval_end")
        try:
            end = date.fromisoformat(str(end_text)[:10]) if end_text else current_date
        except ValueError:
            end = current_date
        if start > previous_date and start <= current_date and end >= start:
            return True
        if start <= previous_date < end and end >= current_date:
            return True
    return False


def _evaluate_signal_tracking(
    db: Session,
    signal: Signal,
    *,
    evaluation_cutoff: date | None = None,
) -> tuple[int, int]:
    bars = db.scalars(
        select(MarketBar)
        .where(
            MarketBar.instrument_id == signal.instrument_id,
            MarketBar.trading_date > signal.signal_date,
            *(
                [MarketBar.trading_date <= evaluation_cutoff]
                if evaluation_cutoff is not None
                else []
            ),
        )
        .order_by(MarketBar.trading_date)
        .limit(20)
    ).all()
    if not bars:
        if evaluation_cutoff is not None:
            for horizon in (5, 20):
                _upsert_settlement(
                    db,
                    signal,
                    horizon,
                    {
                        "settlement_date": evaluation_cutoff,
                        "final_status": "incomparable",
                        "first_trigger": None,
                        "return_or_risk": None,
                        "incomparable_reason": "no post-signal session available before backtest cutoff",
                        "source": signal.source_report,
                        "data_time": evaluation_cutoff.isoformat(),
                        "execution_date": None,
                        "execution_price": None,
                        "comparable": False,
                        "data_quality": "incomplete",
                    },
                )
            signal.data_quality = "incomplete"
            return 0, 2
        return 0, 0
    instrument = db.get(Instrument, signal.instrument_id)
    if not instrument:
        return 0, 0
    prior_bars = db.scalars(
        select(MarketBar)
        .where(
            MarketBar.instrument_id == signal.instrument_id,
            MarketBar.trading_date <= signal.signal_date,
        )
        .order_by(desc(MarketBar.trading_date))
        .limit(20)
    ).all()
    prior_volume_values = [bar.volume for bar in prior_bars if bar.volume and bar.volume > 0]
    prior_volume_average = (
        sum(prior_volume_values) / len(prior_volume_values)
        if len(prior_volume_values) == 20
        else None
    )
    action_rows = db.scalars(
        select(CorporateAction).where(
            CorporateAction.instrument_id == signal.instrument_id,
            CorporateAction.action_date > signal.signal_date,
            CorporateAction.action_date <= bars[-1].trading_date,
            *(
                [CorporateAction.action_date <= evaluation_cutoff]
                if evaluation_cutoff is not None
                else []
            ),
        )
    ).all()
    # TWSE's daily corporate-action feed usually carries the cash/stock
    # amounts but not the pre-ex reference price.  Use the last official bar
    # before the action as a deterministic fallback; without this, a cash
    # dividend would be stored yet silently left unadjusted in OOS returns.
    fallback_reference_prices: dict[date, float] = {}
    for action in action_rows:
        if action.reference_price is not None:
            continue
        previous_bar = db.scalar(
            select(MarketBar)
            .where(
                MarketBar.instrument_id == signal.instrument_id,
                MarketBar.trading_date < action.action_date,
            )
            .order_by(desc(MarketBar.trading_date))
            .limit(1)
        )
        if previous_bar:
            previous_close = _safe_float(previous_bar.close)
            if previous_close and previous_close > 0:
                fallback_reference_prices[action.action_date] = previous_close
    evaluations: list[SignalEvaluation] = []
    executed = False
    execution_date: date | None = None
    execution_price: float | None = None
    first_outcome: str | None = None
    outcome_session_no: int | None = None
    outcome_price: float | None = None
    execution_factor: float | None = None
    outcome_factor: float | None = None
    factor_by_session: dict[int, float] = {}
    ambiguous = False
    signal.data_quality = signal.data_quality or "complete"
    previous_observed_date = signal.signal_date
    for session_no, bar in enumerate(bars, start=1):
        actions = [action for action in action_rows if action.action_date <= bar.trading_date]
        factor, action_applied = _corporate_action_factor(
            actions,
            fallback_reference_prices=fallback_reference_prices,
        )
        factor_by_session[session_no] = factor
        # ``factor`` maps the signal-date price basis to the current raw
        # basis (for a 2-for-1 split, signal level 100 -> raw level 50 and
        # factor=0.5).  Keep raw OHLC untouched for execution and trigger
        # checks; ``adjusted_ohlc_json`` is explicitly the inverse mapping,
        # normalized back to the signal-date basis for return comparison.
        adjusted = {
            "basis": "signal_date_normalized",
            "factor_signal_to_raw": factor,
            "open": round(bar.open / factor, 8),
            "high": round(bar.high / factor, 8),
            "low": round(bar.low / factor, 8),
            "close": round(bar.close / factor, 8),
            "adj_close": round((bar.adj_close or bar.close) / factor, 8),
        }
        suspension_gap = _suspension_gap_between(
            db,
            signal.instrument_id,
            previous_observed_date,
            bar.trading_date,
        )
        suspended = bool(
            bar.is_suspended
            or (bar.volume == 0 and bar.open == bar.high == bar.low == bar.close)
            or suspension_gap
        )
        previous_observed_date = bar.trading_date
        breakout_level_raw = signal.breakout_price * factor if signal.breakout_price is not None else None
        pullback_low_level_raw = signal.pullback_low * factor if signal.pullback_low is not None else None
        pullback_high_level_raw = signal.pullback_high * factor if signal.pullback_high is not None else None
        invalid_level_raw = signal.invalid_price * factor if signal.invalid_price is not None else None
        target_level_raw = signal.target_1 * factor if signal.target_1 is not None else None
        breakout_trigger = False
        pullback_trigger = False
        target_trigger = False
        invalid_trigger = False
        status = "pending"
        reason = ""
        comparable = not suspended
        current_execution_price = execution_price
        if suspended:
            status = "suspended"
            reason = (
                "official suspension interval contains a missing market session; "
                "no price trigger inferred"
                if suspension_gap
                else "trading suspended; no price trigger inferred"
            )
            comparable = False
        else:
            if not executed:
                if signal.entry_type == "breakout" and signal.breakout_price is not None:
                    breakout_trigger = breakout_level_raw is not None and bar.high >= breakout_level_raw
                    if breakout_trigger:
                        raw_execution_price = (
                            max(bar.open, breakout_level_raw)
                            if bar.open >= breakout_level_raw
                            else breakout_level_raw
                        )
                        current_execution_price = _buy_fill_with_slippage(raw_execution_price)
                elif signal.entry_type == "pullback" and signal.pullback_low is not None and signal.pullback_high is not None:
                    pullback_trigger = (
                        pullback_low_level_raw is not None
                        and pullback_high_level_raw is not None
                        and bar.low <= pullback_high_level_raw
                        and bar.high >= pullback_low_level_raw
                    )
                    if pullback_trigger:
                        raw_execution_price = (
                            bar.open
                            if pullback_low_level_raw <= bar.open <= pullback_high_level_raw
                            else min(max(bar.open, pullback_low_level_raw), pullback_high_level_raw)
                        )
                        current_execution_price = _buy_fill_with_slippage(raw_execution_price)
                if breakout_trigger or pullback_trigger:
                    executed = True
                    execution_date = bar.trading_date
                    execution_price = current_execution_price
                    execution_factor = factor
                    signal.execution_date = execution_date
                    signal.execution_price = execution_price
                    status = "active"
                    reason = "earliest executable fill from T+1"
                else:
                    status = "not_triggered"
                    reason = "conditional entry was not reached"
            if executed and execution_price is not None:
                if ambiguous:
                    status = "ambiguous"
                    reason = "same-session stop and target both touched; order is unknowable"
                    comparable = False
                elif first_outcome is not None:
                    # Once an exit is observed, later bars cannot overwrite
                    # the first outcome or introduce look-ahead bias.
                    status = first_outcome
                    reason = "position already closed on first observed outcome"
                else:
                    invalid_trigger = invalid_level_raw is not None and bar.low <= invalid_level_raw
                    target_trigger = target_level_raw is not None and bar.high >= target_level_raw
                    if invalid_trigger and target_trigger:
                        status = "ambiguous"
                        reason = "same-session stop and target both touched; order is unknowable"
                        comparable = False
                        ambiguous = True
                    elif invalid_trigger:
                        status = "invalidated"
                        reason = "invalid price touched"
                        first_outcome = "invalidated"
                        outcome_session_no = session_no
                        outcome_price = _sell_fill_with_slippage(invalid_level_raw)
                        outcome_factor = factor
                    elif target_trigger:
                        status = "target_1_hit"
                        reason = "first target touched"
                        first_outcome = "target_1_hit"
                        outcome_session_no = session_no
                        outcome_price = _sell_fill_with_slippage(target_level_raw)
                        outcome_factor = factor
                    else:
                        status = "active"
                        reason = "position remains within defined levels"
        chip = db.scalar(
            select(ChipSnapshot).where(
                ChipSnapshot.instrument_id == signal.instrument_id,
                ChipSnapshot.trading_date == bar.trading_date,
            )
        )
        flow_confirmation = "missing"
        margin_confirmation = "missing"
        if chip and all(
            _safe_float(value) is not None
            for value in (chip.foreign_buy, chip.trust_buy, chip.dealer_buy)
        ):
            flow_confirmation = "available"
            margin_confirmation = "available" if _safe_float(chip.margin_balance) is not None else "missing"
        group_confirmation = "available" if _best_group_for_signal(db, signal.instrument_id, signal.signal_date) else "missing"
        evaluation = _upsert_evaluation(
            db,
            signal,
            bar,
            {
                "session_no": session_no,
                "ohlc_json": {
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "adj_close": bar.adj_close,
                },
                "volume": bar.volume,
                "volume_ratio_20d": (
                    bar.volume / prior_volume_average
                    if prior_volume_average and bar.volume is not None
                    else None
                ),
                "pullback_price_trigger": pullback_trigger,
                "breakout_price_trigger": breakout_trigger,
                "target_price_trigger": target_trigger,
                "invalid_price_trigger": invalid_trigger,
                "institutional_confirmation": flow_confirmation,
                "leverage_confirmation": margin_confirmation,
                "subgroup_confirmation": group_confirmation,
                "full_confirmation": flow_confirmation == "available" and margin_confirmation == "available" and group_confirmation == "available",
                "status": status,
                "reason": reason,
                "source": bar.source,
                "data_time": bar.data_as_of.isoformat() if bar.data_as_of else None,
                "execution_date": execution_date,
                "execution_price": execution_price,
                "adjusted_ohlc_json": adjusted,
                "corporate_action_applied": action_applied,
                "suspended": suspended,
                "comparable": comparable,
                "trigger_order": "ambiguous" if ambiguous else (first_outcome or "none"),
                "data_quality": "incomplete" if not comparable else "complete",
            },
        )
        evaluations.append(evaluation)
    if not executed:
        # A daily run may only have a partial post-signal history.  Keep the
        # conditional/observation state until the full 20-session window is
        # available; otherwise a T+5 run would permanently block T+20 OOS.
        if len(bars) >= 20:
            _set_signal_status(signal, "expired")
    elif ambiguous:
        _set_signal_status(signal, "incomparable")
    elif first_outcome == "invalidated":
        _set_signal_status(signal, "invalidated")
    elif first_outcome == "target_1_hit":
        _set_signal_status(signal, "target_1_hit")
    else:
        _set_signal_status(signal, "active")
    if ambiguous or any(item.comparable is False for item in evaluations):
        signal.data_quality = "incomplete"

    settlement_count = 0
    for horizon in (5, 20):
        if len(evaluations) < horizon:
            settlement_date = evaluations[-1].session_date
            settlement_data = {
                "settlement_date": settlement_date,
                "final_status": "incomparable",
                "first_trigger": first_outcome,
                "return_or_risk": None,
                "incomparable_reason": f"only {len(evaluations)} trading sessions available; {horizon} required",
                "source": evaluations[-1].source,
                "data_time": evaluations[-1].data_time,
                "execution_date": execution_date,
                "execution_price": execution_price,
                "comparable": False,
                "data_quality": "incomplete",
            }
        else:
            horizon_eval = evaluations[horizon - 1]
            window_has_non_comparable_session = any(
                item.comparable is False for item in evaluations[:horizon]
            )
            comparable = bool(
                horizon_eval.comparable
                and execution_price
                and not ambiguous
                and not window_has_non_comparable_session
            )
            return_value = None
            if comparable and execution_price:
                has_early_outcome = outcome_session_no is not None and outcome_session_no <= horizon
                entry_factor = execution_factor or 1.0
                # Execution/outcome prices are actual raw fills.  Convert
                # both to the signal-date basis (raw / factor) before the
                # return calculation; a split must not manufacture a loss.
                comparable_entry = execution_price / entry_factor
                if has_early_outcome and outcome_price is not None:
                    exit_factor = outcome_factor or 1.0
                    comparable_exit = outcome_price / exit_factor
                else:
                    comparable_exit = (horizon_eval.adjusted_ohlc_json or {}).get("close")
                if comparable_exit is not None and comparable_entry > 0:
                    gross_return = comparable_exit / comparable_entry - 1.0
                    return_value = gross_return - ROUND_TRIP_TRANSACTION_COST_BPS / 10_000.0
            final_status = horizon_eval.status if comparable else "incomparable"
            incomparable_reason = None
            if not comparable:
                incomparable_reason = (
                    "suspended or otherwise non-comparable session in horizon"
                    if window_has_non_comparable_session
                    else horizon_eval.reason or "price path is not comparable"
                )
            settlement_data = {
                "settlement_date": horizon_eval.session_date,
                "final_status": final_status,
                "first_trigger": first_outcome,
                "return_or_risk": return_value,
                "incomparable_reason": incomparable_reason,
                "source": horizon_eval.source,
                "data_time": horizon_eval.data_time,
                "execution_date": execution_date,
                "execution_price": execution_price,
                "comparable": comparable,
                "data_quality": "complete" if comparable else "incomplete",
            }
        _upsert_settlement(db, signal, horizon, settlement_data)
        settlement_count += 1
    return len(evaluations), settlement_count


def evaluate() -> dict[str, Any]:
    init_db()
    with SessionLocal() as db:
        signals = db.scalars(
            select(Signal).where(
                Signal.status.in_(
                    {"conditional", "active", "target_1_hit", "invalidated", "observation", "incomparable"}
                )
            )
        ).all()
        if not signals:
            return {"status": "no_data", "signals_checked": 0, "evaluations_written": 0, "settlements_written": 0}
        evaluations = 0
        settlements = 0
        for signal in signals:
            current_evaluations, current_settlements = _evaluate_signal_tracking(db, signal)
            evaluations += current_evaluations
            settlements += current_settlements
        db.commit()
        latest_date = db.scalar(select(func.max(MarketBar.trading_date)))
        return {
            "status": "success",
            "date": latest_date.isoformat() if latest_date else None,
            "signals_checked": len(signals),
            "evaluations_written": evaluations,
            "settlements_written": settlements,
        }


def _backtest_assessment(metadata: dict[str, Any], *, status: str) -> str:
    """Return the run-level assessment even when no actionable group exists."""

    if status == "failed":
        return "failed"
    sample_days = metadata.get("score_session_count")
    try:
        sample_days = int(sample_days)
    except (TypeError, ValueError):
        sample_days = 0
    covered_days: int | None = None
    try:
        covered_days = (
            date.fromisoformat(str(metadata.get("end_date")))
            - date.fromisoformat(str(metadata.get("start_date")))
        ).days
    except (TypeError, ValueError):
        pass
    # A range of 93 calendar days or less is the technical three-month
    # verification boundary.  It remains insufficient even if a fixture has
    # many score sessions or no actionable signal at all.
    if sample_days < 60 or covered_days is None or covered_days <= 93:
        return "insufficient_sample"
    return "technical_only"


def summarize_backtest(db: Session, run_id: int | None = None) -> dict[str, Any]:
    """Summarize technical backtest settlements without claiming evidence."""

    run = db.get(IngestionRun, run_id) if run_id is not None else db.scalar(
        select(IngestionRun)
        .where(IngestionRun.run_type == "backtest")
        .order_by(desc(IngestionRun.id))
        .limit(1)
    )
    if not run:
        return {
            "run": None,
            "groups": [],
            "assessment": "no_run",
            "zero_actionable_count": 0,
        }
    expected_prefix = f"backtest-{run.id}-"
    signals = [
        signal
        for signal in db.scalars(select(Signal).where(Signal.signal_key.like("backtest-%"))).all()
        if signal.signal_key.startswith(expected_prefix)
    ]
    actionable_signals = [
        signal for signal in signals if (signal.rule_evidence_json or {}).get("actionable")
    ]
    zero_actionable_count = len(signals) - len(actionable_signals)
    grouped: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    for signal in actionable_signals:
        # Backtest keeps observation/data_incomplete rows for rule audit, but
        # only a conditional setup is a performance sample.  This guard also
        # protects summaries of legacy runs that may contain settlements for
        # non-actionable rows.
        strategy = db.get(StrategyVersion, signal.strategy_version_id) if signal.strategy_version_id else None
        instrument = db.get(Instrument, signal.instrument_id)
        if not strategy or not instrument:
            continue
        settlements = db.scalars(
            select(SignalSettlement).where(SignalSettlement.signal_id == signal.id)
        ).all()
        for settlement in settlements:
            key = (strategy.name, strategy.version, instrument.instrument_type, settlement.horizon)
            row = grouped.setdefault(
                key,
                {
                    "strategy": strategy.name,
                    "version": strategy.version,
                    "instrument_type": instrument.instrument_type,
                    "horizon": settlement.horizon,
                    "sample": 0,
                    "comparable": 0,
                    "incomparable": 0,
                },
            )
            row["sample"] += 1
            if settlement.comparable:
                row["comparable"] += 1
            else:
                row["incomparable"] += 1
    metadata = dict(run.metadata_json or {})
    assessment = _backtest_assessment(metadata, status=run.status)
    for row in grouped.values():
        row["assessment"] = assessment
        row["interpretation"] = (
            "Technical workflow completed; sample is insufficient for a research conclusion."
            if row["assessment"] == "insufficient_sample"
            else "Technical workflow only; no optimization or OOS conclusion."
        )
    return {
        "run": {
            "id": run.id,
            "status": run.status,
            "run_type": run.run_type,
            "request_key": run.request_key,
            "run_date": run.run_date.isoformat() if run.run_date else None,
            "data_as_of": run.data_as_of,
            "metadata": metadata,
            "assessment": assessment,
            "zero_actionable_count": zero_actionable_count,
        },
        "groups": sorted(
            grouped.values(),
            key=lambda row: (row["strategy"], row["instrument_type"], row["horizon"]),
        ),
        "assessment": assessment,
        "zero_actionable_count": zero_actionable_count,
    }


def backtest(
    start_date: date,
    end_date: date,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Replay canonical fixed-version rules with a strict daily as-of cutoff."""

    if start_date > end_date:
        raise ValueError("backtest start date must not be after end date")
    init_db()
    request_key = f"technical-backtest:v1:{start_date.isoformat()}:{end_date.isoformat()}"
    with SessionLocal() as db:
        run = db.scalar(select(IngestionRun).where(IngestionRun.request_key == request_key))
        if run and run.status == "success" and not force:
            summary = summarize_backtest(db, run.id)
            summary["idempotent_reuse"] = True
            return summary
        if not run:
            run = IngestionRun(
                run_type="backtest",
                source="technical_backtest",
                run_date=end_date,
                status="running",
                request_key=request_key,
            )
            db.add(run)
            db.flush()
        else:
            run.run_type = "backtest"
            run.source = "technical_backtest"
            run.run_date = end_date
            run.status = "running"
            run.records = 0
            run.error = None
        # Persist the audit row before doing any work that may fail.  A
        # rollback during the first failed execution must not erase the run
        # itself, otherwise there is no durable failed audit record to
        # inspect or resume by request_key.
        metadata: dict[str, Any] = {
            "workflow": "technical_backtest_v1",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "data_cutoff": f"T close through {end_date.isoformat()} 13:30 Asia/Taipei",
            "execution": "signal at T close; earliest fill T+1; settlement T+5/T+20",
            "signal_confidence_semantics": dict(SIGNAL_CONFIDENCE_SEMANTICS),
        }
        run.metadata_json = metadata
        db.commit()
        try:
            strategies = _ensure_strategies(db)
            metadata["strategy_versions"] = {
                key: {
                    "name": strategy.name,
                    "version": strategy.version,
                    "canonical_config_snapshot": strategy.canonical_config_snapshot,
                }
                for key, strategy in strategies.items()
            }
            run.metadata_json = metadata
            db.commit()
            instruments = db.scalars(
                select(Instrument).where(
                    Instrument.instrument_type.in_({"stock", "etf", "ipo"}),
                    Instrument.status == "active",
                )
            ).all()
            for instrument in instruments:
                _calculate_features(db, instrument, as_of_date=end_date)
            # The application session intentionally disables autoflush.  Make
            # derived as-of features visible to the subsequent group/signal
            # queries before replaying each score date.
            db.flush()
            score_dates = db.scalars(
                select(MarketBar.trading_date)
                .where(MarketBar.trading_date >= start_date, MarketBar.trading_date <= end_date)
                .distinct()
                .order_by(MarketBar.trading_date)
            ).all()
            metadata["score_session_count"] = len(score_dates)
            metadata["as_of_rule"] = "all feature/group inputs are bounded by score_date"
            signal_count = 0
            for score_date in score_dates:
                _calculate_group_scores(db, score_date)
                db.flush()
                signal_count += _generate_signals(
                    db,
                    score_date,
                    strategies,
                    namespace=f"backtest-{run.id}",
                    data_cutoff=end_date,
                )
            # The session intentionally uses autoflush=False.  Flush the
            # final score date before auditing the run, otherwise the last
            # day's strategy rows disappear from signal_count and
            # zero_actionable_count until after the run has been committed.
            db.flush()
            backtest_signals = db.scalars(
                select(Signal).where(Signal.signal_key.like(f"backtest-{run.id}-%"))
            ).all()
            signal_count = len(backtest_signals)
            evaluations = 0
            settlements = 0
            for signal in backtest_signals:
                if not (signal.rule_evidence_json or {}).get("actionable"):
                    continue
                current_evaluations, current_settlements = _evaluate_signal_tracking(
                    db,
                    signal,
                    evaluation_cutoff=end_date,
                )
                evaluations += current_evaluations
                settlements += current_settlements
            zero_actionable_count = sum(
                1
                for signal in backtest_signals
                if not (signal.rule_evidence_json or {}).get("actionable")
            )
            run.status = "success"
            run.records = len(backtest_signals)
            run.data_as_of = end_date.isoformat()
            run.metadata_json = {
                **metadata,
                "signals": signal_count,
                "evaluations": evaluations,
                "settlements": settlements,
                "zero_actionable_count": zero_actionable_count,
            }
            run.metadata_json["assessment"] = _backtest_assessment(
                run.metadata_json,
                status="success",
            )
            run.finished_at = datetime.utcnow()
            db.commit()
            return summarize_backtest(db, run.id)
        except Exception as exc:
            db.rollback()
            failed = db.get(IngestionRun, run.id)
            if failed:
                failed.status = "failed"
                failed.error = f"{type(exc).__name__}: {exc}"
                failed.metadata_json = {
                    **metadata,
                    "assessment": "failed",
                    "zero_actionable_count": 0,
                }
                failed.finished_at = datetime.utcnow()
                db.commit()
            return {
                "run": {
                    "id": run.id,
                    "status": "failed",
                    "request_key": request_key,
                    "assessment": "failed",
                    "zero_actionable_count": 0,
                },
                "groups": [],
                "assessment": "failed",
                "zero_actionable_count": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }


def run_daily(end_date: date | None = None, *, months_back: int = 0) -> dict[str, Any]:
    collected = collect(end_date, months_back=months_back)
    if collected.get("status") != "success":
        return {
            "collect": collected,
            "analyze": {"status": "skipped", "reason": "official_collection_failed"},
            "evaluate": {"status": "skipped", "reason": "official_collection_failed"},
        }
    analyzed = analyze()
    if analyzed.get("status") != "success":
        return {
            "collect": collected,
            "analyze": analyzed,
            "evaluate": {"status": "skipped", "reason": "analysis_failed"},
        }
    evaluated = evaluate()
    return {"collect": collected, "analyze": analyzed, "evaluate": evaluated}
