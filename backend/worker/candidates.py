"""Daily candidate list scored with the current candidate_score version (V1_SPEC).

Runs after ``analyze``: it reads the trading date's signals of the
strategies the score version's pool lists, keeps the ones analyze judged
actionable (conditional) on that date, whatever tracking status they reached
since, with legal price levels on common stocks, scores them on four
components (technical, chips, news sentiment, group) and stores the top of
the list with rule-based reasons.

The score only orders signals the strategies already judged; it never
changes a strategy decision and is not a win rate or expected return.
Missing inputs stay null: a component is the weighted mean of its available
items, the total the weighted mean of its available components, and the
covered weight is stored next to it.

One ``candidate_runs`` row per trading date and score version, including a
day with zero candidates and its reason.  A rerun of the same date and
version returns the stored run without adding or rewriting rows.
"""

from __future__ import annotations

import math
import string
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.config import MIN_GROUP_MEMBERS
from app.domain import (
    CANDIDATE_SCORE,
    CANDIDATE_SCORE_VERSION,
    validate_signal_levels,
    weighted_available_mean,
)
from app.models import (
    CandidateRun,
    ChipSnapshot,
    DailyCandidate,
    GroupDailyScore,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    NewsItem,
    NewsLlmResult,
    Signal,
    StrategyVersion,
    ThemeGroup,
)
from app.strategies import REGISTRY

from . import pipeline
from .pipeline import _group_board, _percentile, _safe_float

GROUP_BOARD_LABELS = {"industry": "產業", "theme": "題材"}
NEWS_TIME_BASES = ("published", "event", "event_date")

# Rule-based reason codes; the Chinese copy is UI_COPY_SPEC §10.  Every code
# belongs to one component, which orders it by weighted contribution.  A
# strategy names its technical code (Strategy.candidate_reason); the code is
# given only when every value its template needs is available.
REASON_TEMPLATES: dict[str, tuple[str, str]] = {
    "breakout_20d_high": ("technical", "突破 20 日高點，量比 {volume_ratio}"),
    "pullback_ma20_support": (
        "technical",
        "回測 20 日均線，距均線 {distance}，量比 {volume_ratio}",
    ),
    "foreign_trust_net_buy_5d": ("chips", "外資＋投信 5 日淨買超"),
    "institutional_net_buy_5d": (
        "chips",
        "三大法人 5 日淨買超，約 20 日均量的 {ratio} 倍",
    ),
    "institutional_net_buy_20d": ("chips", "三大法人 20 日淨買超"),
    "margin_decrease_5d": ("chips", "融資 5 日減少 {ratio}"),
    "news_positive_3d": ("news_sentiment", "近 3 日 {positive} 則偏多新聞（推論）"),
    "hot_group_rank": ("group", "所屬{board}「{name}」熱度第 {rank}"),
}
REASON_ORDER = tuple(REASON_TEMPLATES)


@dataclass
class _PoolEntry:
    signal: Signal
    instrument: Instrument
    strategy: str
    technical: dict[str, float | None]
    components: dict[str, dict[str, Any]] = field(default_factory=dict)
    total: float | None = None
    coverage: float = 0.0
    groups: list[dict[str, Any]] = field(default_factory=list)


def _actionable_on_signal_date(signal: Signal, pool_config: dict[str, Any]) -> bool:
    evidence = (
        signal.rule_evidence_json if isinstance(signal.rule_evidence_json, dict) else {}
    )
    if "actionable" in evidence:
        return evidence["actionable"] is True
    return signal.status in pool_config["legacy_actionable_statuses"]


def _finite(value: Any) -> float | None:
    number = _safe_float(value)
    return number if number is not None and math.isfinite(number) else None


def _directed_percentile(
    value: float | None, peers: list[float | None], better: str
) -> float | None:
    """Same-day mid-rank percentile where 1 is always the better end."""

    if better == "lower":
        flipped = None if value is None else -value
        return _percentile(flipped, [None if peer is None else -peer for peer in peers])
    return _percentile(value, peers)


def _technical_inputs(
    signal: Signal, strategy: str, bar: MarketBar
) -> dict[str, float | None]:
    evidence = (
        signal.rule_evidence_json if isinstance(signal.rule_evidence_json, dict) else {}
    )
    inputs = evidence.get("inputs") if isinstance(evidence.get("inputs"), dict) else {}
    close = _finite(bar.close)
    volume = _finite(bar.volume)
    prior_volumes = [_finite(item) for item in inputs.get("prior_20_volumes") or []]
    volume_ratio = None
    if (
        volume is not None
        and len(prior_volumes) == 20
        and all(item is not None for item in prior_volumes)
    ):
        average = sum(prior_volumes) / 20
        volume_ratio = volume / average if average > 0 else None
    rule = REGISTRY[strategy]
    distance = rule.candidate_distance(close, inputs) if close is not None else None
    entry = _finite(getattr(signal, rule.level_fields["trigger_price"]))
    invalid = _finite(signal.invalid_price)
    target = _finite(signal.target_1)
    risk_reward = None
    if (
        entry is not None
        and invalid is not None
        and target is not None
        and entry > invalid
    ):
        risk_reward = (target - entry) / (entry - invalid)
    return {
        "volume_ratio": volume_ratio,
        "distance": distance,
        "risk_reward": risk_reward,
    }


def _chip_inputs(
    db: Session, instrument_id: int, trading_date: date
) -> dict[str, float | None]:
    """Chips inputs on the trading date's last 20 non-suspended sessions.

    Same sessions, units and fail-closed rules as the strategy inputs
    (``pipeline._validated_flow_and_volume_inputs`` and
    ``pipeline._margin_change_ratio``); additionally the latest session must
    be the trading date itself so no older day stands in for it.
    """

    empty = {
        "institutional_flow_5d": None,
        "institutional_flow_20d": None,
        "margin_change_5d": None,
        "foreign_5d": None,
        "trust_5d": None,
    }
    bars = db.execute(
        select(MarketBar.trading_date, MarketBar.volume)
        .where(
            MarketBar.instrument_id == instrument_id,
            MarketBar.trading_date <= trading_date,
            (MarketBar.is_suspended.is_(False) | MarketBar.is_suspended.is_(None)),
        )
        .order_by(desc(MarketBar.trading_date))
        .limit(20)
    ).all()
    bars = list(reversed(bars))
    if not bars or bars[-1].trading_date != trading_date:
        return empty
    dates = [row.trading_date for row in bars]
    chips = {
        chip.trading_date: chip
        for chip in db.scalars(
            select(ChipSnapshot).where(
                ChipSnapshot.instrument_id == instrument_id,
                ChipSnapshot.trading_date.in_(dates),
            )
        )
    }
    result = dict(empty)
    if len(dates) >= 6:
        window = dates[-6:]
        if all(day in chips for day in window):
            first = chips[window[0]].margin_balance
            last = chips[window[-1]].margin_balance
            if first not in (None, 0) and last is not None:
                result["margin_change_5d"] = (last - first) / abs(first)
    volumes = [_finite(row.volume) for row in bars]
    if len(dates) != 20 or any(volume is None or volume <= 0 for volume in volumes):
        return result
    average_volume = sum(volumes) / 20

    def flow(window: list[date]) -> tuple[float, float, float] | None:
        foreign = trust = total = 0.0
        for day in window:
            chip = chips.get(day)
            if chip is None:
                return None
            parts = (
                _finite(chip.foreign_buy),
                _finite(chip.trust_buy),
                _finite(chip.dealer_buy),
            )
            if any(part is None for part in parts):
                return None
            foreign += parts[0]
            trust += parts[1]
            total += sum(parts)
        return foreign, trust, total

    five = flow(dates[-5:])
    if five is not None:
        result["foreign_5d"], result["trust_5d"] = five[0], five[1]
        result["institutional_flow_5d"] = five[2] / average_volume
    twenty = flow(dates)
    if twenty is not None:
        result["institutional_flow_20d"] = twenty[2] / average_volume
    return result


def _taipei_news_date(item: NewsItem) -> date | None:
    """Taipei calendar date of a verified news time; date-only stays a date."""

    if item.time_precision == "date":
        return item.event_date or (
            item.display_time.date() if item.display_time else None
        )
    if item.time_precision == "datetime" and item.display_time is not None:
        # app.news stores publication/event instants as UTC-naive values.
        return (item.display_time + timedelta(hours=8)).date()
    return None


def _news_inputs(
    db: Session,
    trading_date: date,
    universe: list[Instrument],
    config: dict[str, Any],
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    news_config = config["components"]["news_sentiment"]
    days = int(news_config["window_calendar_days"])
    window_start = trading_date - timedelta(days=days - 1)
    summary: dict[str, Any] = {
        "window": [window_start.isoformat(), trading_date.isoformat()],
        "llm_prompt_version": news_config["llm_prompt_version"],
    }
    collected = db.scalar(
        select(func.count(IngestionRun.id)).where(
            IngestionRun.run_type == "news",
            IngestionRun.status.in_(("success", "partial")),
            IngestionRun.run_date >= window_start,
            IngestionRun.run_date <= trading_date,
        )
    )
    summary["news_collection_runs"] = int(collected or 0)
    if not collected:
        summary["null_reason"] = "news_collection_missing"
        return {}, summary

    by_token: dict[str, list[int]] = defaultdict(list)
    for instrument in universe:
        by_token[instrument.symbol].append(instrument.id)
        by_token[f"{instrument.exchange}:{instrument.symbol}"].append(instrument.id)
    items = db.scalars(
        select(NewsItem).where(
            NewsItem.status == "active",
            NewsItem.time_consistency == "verified",
            NewsItem.time_basis.in_(NEWS_TIME_BASES),
            NewsItem.display_time.is_not(None),
            NewsItem.display_time
            >= datetime.combine(window_start - timedelta(days=1), datetime.min.time()),
            NewsItem.display_time
            < datetime.combine(trading_date + timedelta(days=1), datetime.min.time()),
        )
    ).all()
    items = [
        item
        for item in items
        if (day := _taipei_news_date(item)) and window_start <= day <= trading_date
    ]
    directions: dict[int, str] = {}
    if items:
        for row in db.scalars(
            select(NewsLlmResult).where(
                NewsLlmResult.news_item_id.in_([item.id for item in items]),
                NewsLlmResult.prompt_version == news_config["llm_prompt_version"],
                NewsLlmResult.llm_status == "done",
            )
        ):
            if row.ai_impact_direction:
                directions[row.news_item_id] = row.ai_impact_direction
    values = news_config["direction_values"]
    stats: dict[int, dict[str, Any]] = {
        instrument.id: {
            "linked": 0,
            "positive": 0,
            "negative": 0,
            "mixed": 0,
            "unscored": 0,
            "news_ids": [],
        }
        for instrument in universe
    }
    for item in items:
        linked: set[int] = set()
        for token in item.symbols_json or []:
            linked.update(by_token.get(str(token), ()))
        direction = directions.get(item.id)
        for instrument_id in linked:
            row = stats[instrument_id]
            row["linked"] += 1
            row["news_ids"].append(item.id)
            if direction in values:
                row[direction] += 1
            else:
                row["unscored"] += 1
    for row in stats.values():
        row["raw"] = (
            row["positive"] * values["positive"] + row["negative"] * values["negative"]
        )
    summary.update(
        news_items_in_window=len(items),
        llm_scored_items=sum(1 for item in items if directions.get(item.id) in values),
        instruments_with_news=sum(1 for row in stats.values() if row["linked"]),
    )
    return stats, summary


def _group_inputs(
    db: Session, trading_date: date
) -> tuple[dict[int, list[dict[str, Any]]], dict[str, Any]]:
    """Every stock's industry/theme groups on the trading date, best first.

    A group is qualified with the same rule as
    ``app.decision._qualified_groups_for_instrument`` (complete quality, at
    least three eligible members, ranked, TAIEX benchmark, equity board), and
    its score row must be dated the trading date itself.
    """

    scores = {
        row.group_id: row
        for row in db.scalars(
            select(GroupDailyScore).where(GroupDailyScore.trading_date == trading_date)
        )
    }
    board_sizes: dict[tuple[Any, Any], int] = defaultdict(int)
    for row in scores.values():
        details = row.details_json or {}
        if row.rank is not None:
            board_sizes[(details.get("leaderboard"), details.get("board"))] += 1
    memberships = db.execute(
        select(GroupMembership.instrument_id, ThemeGroup)
        .join(ThemeGroup, ThemeGroup.id == GroupMembership.group_id)
        .where(
            ThemeGroup.active.is_(True),
            GroupMembership.valid_from <= trading_date,
            (
                GroupMembership.valid_to.is_(None)
                | (GroupMembership.valid_to >= trading_date)
            ),
        )
    ).all()
    result: dict[int, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[int, str]] = set()
    for instrument_id, group in memberships:
        board = _group_board(group)
        if board not in GROUP_BOARD_LABELS or (instrument_id, group.id) in seen:
            continue
        seen.add((instrument_id, group.id))
        score = scores.get(group.id)
        details = (score.details_json or {}) if score is not None else {}
        qualified = (
            score is not None
            and score.rank is not None
            and score.data_quality == "complete"
            and (score.eligible_members or 0) >= MIN_GROUP_MEMBERS
            and details.get("benchmark") == "TAIEX"
            and details.get("leaderboard") != "etf"
        )
        size = (
            board_sizes[(details.get("leaderboard"), details.get("board"))]
            if qualified
            else None
        )
        percentile = None
        if qualified:
            percentile = 0.5 if size == 1 else 1 - (score.rank - 1) / (size - 1)
        result[instrument_id].append(
            {
                "group_id": group.id,
                "name": group.display_name_zh or group.name,
                "board": board,
                "qualified": qualified,
                "rank": score.rank if qualified else None,
                "board_size": size,
                "board_percentile": percentile,
                "score": score.score if qualified else None,
                "data_quality": score.data_quality if score is not None else None,
                "score_date": trading_date.isoformat() if score is not None else None,
            }
        )
    for groups in result.values():
        groups.sort(
            key=lambda item: (
                item["board_percentile"] is None,
                -(item["board_percentile"] or 0.0),
                item["board"],
                item["group_id"],
            )
        )
    summary = {
        "boards": {
            f"{leaderboard}:{board}": count
            for (leaderboard, board), count in sorted(
                board_sizes.items(), key=lambda item: str(item[0])
            )
        }
    }
    return result, summary


def _item(
    value: float | None,
    percentile: float | None,
    weight: float,
    better: Any,
    reason: str | None,
) -> dict[str, Any]:
    return {
        "value": value,
        "percentile": percentile,
        "weight": weight,
        "better": better,
        "null_reason": None if value is not None else reason,
    }


def _component(
    items: dict[str, dict[str, Any]],
    weight: float,
    *,
    inference: bool,
    null_reason: str,
) -> dict[str, Any]:
    score, coverage = weighted_available_mean(
        {key: item["percentile"] for key, item in items.items()},
        {key: item["weight"] for key, item in items.items()},
    )
    return {
        "score": score,
        "weight": weight,
        "inference": inference,
        "item_coverage": coverage,
        "null_reason": None if score is not None else null_reason,
        "items": items,
    }


def _format_percent(value: float) -> str:
    return f"{abs(value) * 100:.1f}%"


def _reasons(entry: _PoolEntry, config: dict[str, Any]) -> list[dict[str, Any]]:
    technical = entry.components["technical"]["items"]
    chips = entry.components["chips"]["items"]
    chip_raw = entry.components["chips"]["raw"]
    news = entry.components["news_sentiment"]
    found: list[tuple[str, dict[str, Any]]] = []
    volume_ratio = technical["volume_ratio"]["value"]
    distance = technical["distance"]["value"]
    technical_code = REGISTRY[entry.strategy].candidate_reason
    if technical_code is not None:
        values = {
            "volume_ratio": None if volume_ratio is None else f"{volume_ratio:.1f}",
            "distance": None if distance is None else _format_percent(distance),
        }
        fields = [
            name
            for _text, name, _spec, _conversion in string.Formatter().parse(
                REASON_TEMPLATES[technical_code][1]
            )
            if name
        ]
        if all(values[name] is not None for name in fields):
            found.append((technical_code, {name: values[name] for name in fields}))
    foreign, trust = chip_raw.get("foreign_5d"), chip_raw.get("trust_5d")
    flow5 = chips["institutional_flow_5d"]["value"]
    if foreign is not None and trust is not None and foreign > 0 and trust > 0:
        found.append(("foreign_trust_net_buy_5d", {}))
    elif flow5 is not None and flow5 > 0:
        found.append(("institutional_net_buy_5d", {"ratio": f"{flow5:.2f}"}))
    flow20 = chips["institutional_flow_20d"]["value"]
    if flow20 is not None and flow20 > 0:
        found.append(("institutional_net_buy_20d", {}))
    margin = chips["margin_change_5d"]["value"]
    if margin is not None and margin < 0:
        found.append(("margin_decrease_5d", {"ratio": _format_percent(margin)}))
    if (
        news["items"]["net_direction"]["value"] is not None
        and news["items"]["net_direction"]["value"] > 0
    ):
        found.append(
            ("news_positive_3d", {"positive": str(news["counts"]["positive"])})
        )
    best_group = next((group for group in entry.groups if group["qualified"]), None)
    if best_group is not None:
        found.append(
            (
                "hot_group_rank",
                {
                    "board": GROUP_BOARD_LABELS[best_group["board"]],
                    "name": best_group["name"],
                    "rank": str(best_group["rank"]),
                },
            )
        )

    def contribution(code: str) -> float:
        component = entry.components[REASON_TEMPLATES[code][0]]
        return (
            -1.0
            if component["score"] is None
            else component["score"] * component["weight"]
        )

    # The best reason of every component first, ordered by the component's
    # weighted contribution; remaining reasons fill the rest in the same order.
    found.sort(key=lambda item: (-contribution(item[0]), REASON_ORDER.index(item[0])))
    leads: list[tuple[str, dict[str, Any]]] = []
    seen_components: set[str] = set()
    for item in found:
        component = REASON_TEMPLATES[item[0]][0]
        if component not in seen_components:
            seen_components.add(component)
            leads.append(item)
    found = leads + [item for item in found if item not in leads]
    return [
        {
            "code": code,
            "component": REASON_TEMPLATES[code][0],
            "text": REASON_TEMPLATES[code][1].format(**params),
            "params": params,
            "inference": entry.components[REASON_TEMPLATES[code][0]]["inference"],
        }
        for code, params in found[: int(config["max_reasons"])]
    ]


def _sort_key(entry: _PoolEntry) -> tuple:
    technical = entry.components["technical"]["score"]
    chips = entry.components["chips"]["score"]
    return (
        -(entry.total or 0.0),
        technical is None,
        -(technical or 0.0),
        chips is None,
        -(chips or 0.0),
        entry.instrument.exchange,
        entry.instrument.symbol,
    )


def _existing_result(run: CandidateRun) -> dict[str, Any]:
    return {
        "status": "success",
        "already_complete": True,
        "candidate_run_id": run.id,
        "trading_date": run.trading_date.isoformat(),
        "score_version": run.score_version,
        "evaluated_signals": run.evaluated_signals,
        "pool_count": run.pool_count,
        "candidate_count": run.candidate_count,
        "records": 0,
        "zero_reason": run.zero_reason,
    }


def compute_daily_candidates(
    db: Session,
    trading_date: date,
    *,
    config: dict[str, Any] = CANDIDATE_SCORE,
) -> dict[str, Any]:
    """Score, rank and store one trading date's candidates (committed)."""

    started = time.perf_counter()
    version = str(config["name"])
    existing = db.scalar(
        select(CandidateRun).where(
            CandidateRun.trading_date == trading_date,
            CandidateRun.score_version == version,
        )
    )
    if existing is not None:
        return _existing_result(existing)

    pool_config = config["pool"]
    rows = db.execute(
        select(Signal, StrategyVersion, Instrument)
        .join(StrategyVersion, StrategyVersion.id == Signal.strategy_version_id)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .where(
            Signal.signal_date == trading_date,
            Signal.signal_key.like(f"{pool_config['signal_namespace']}-%"),
            StrategyVersion.name.in_(pool_config["strategies"]),
        )
        .order_by(Signal.id)
    ).all()
    if not rows:
        return {
            "status": "no_data",
            "reason": "no_signals_for_date",
            "trading_date": trading_date.isoformat(),
            "score_version": version,
            "records": 0,
        }

    status_counts: dict[str, int] = defaultdict(int)
    exclusions: dict[str, int] = defaultdict(int)
    pool: list[_PoolEntry] = []
    actionable = 0
    for signal, strategy, instrument in rows:
        status_counts[signal.status] += 1
        if not _actionable_on_signal_date(signal, pool_config):
            continue
        actionable += 1
        if not strategy.active:
            exclusions["inactive_strategy_formula"] += 1
            continue
        if instrument.instrument_type not in pool_config["instrument_types"]:
            exclusions[f"instrument_type_excluded:{instrument.instrument_type}"] += 1
            continue
        if instrument.status != "active":
            exclusions["instrument_inactive"] += 1
            continue
        validation = validate_signal_levels(
            entry_type=signal.entry_type,
            reference_entry=signal.reference_entry,
            breakout_price=signal.breakout_price,
            invalid_price=signal.invalid_price,
            target_1=signal.target_1,
            target_2=signal.target_2,
        )
        if (
            signal.entry_type != REGISTRY[strategy.name].entry_type
            or not validation.valid
        ):
            exclusions["invalid_levels"] += 1
            continue
        bar = db.scalar(
            select(MarketBar).where(
                MarketBar.instrument_id == instrument.id,
                MarketBar.trading_date == trading_date,
            )
        )
        if bar is None or bar.is_suspended:
            exclusions["signal_day_suspended_or_missing"] += 1
            continue
        pool.append(
            _PoolEntry(
                signal=signal,
                instrument=instrument,
                strategy=strategy.name,
                technical=_technical_inputs(signal, strategy.name, bar),
            )
        )

    summary: dict[str, Any] = {
        # Current statuses; the pool uses the actionable flag set on T.
        "signal_status_counts": dict(sorted(status_counts.items())),
        "actionable_signals": actionable,
    }
    zero_reason = None
    selected: list[_PoolEntry] = []
    if not pool:
        zero_reason = "no_actionable_signals" if actionable == 0 else "all_excluded"
    else:
        selected = _score_pool(db, trading_date, pool, config, summary, exclusions)
        if not selected:
            zero_reason = "all_excluded"

    run = CandidateRun(
        trading_date=trading_date,
        score_version=version,
        status="success",
        evaluated_signals=len(rows),
        pool_count=len(pool),
        candidate_count=len(selected),
        zero_reason=zero_reason,
        exclusions_json=dict(sorted(exclusions.items())),
        config_json=config,
        summary_json=summary,
        computed_at=datetime.utcnow(),
    )
    db.add(run)
    db.flush()
    for rank, entry in enumerate(selected, start=1):
        db.add(
            DailyCandidate(
                candidate_run_id=run.id,
                trading_date=trading_date,
                instrument_id=entry.instrument.id,
                signal_id=entry.signal.id,
                strategy=entry.strategy,
                score_version=version,
                total_score=round(entry.total, 6),
                weight_coverage=round(entry.coverage, 6),
                rank=rank,
                components_json=entry.components,
                reasons_json=_reasons(entry, config),
                groups_json=entry.groups,
                data_as_of=trading_date,
            )
        )
    elapsed = round(time.perf_counter() - started, 3)
    run.summary_json = {**summary, "elapsed_seconds": elapsed}
    db.commit()
    return {
        "status": "success",
        "already_complete": False,
        "candidate_run_id": run.id,
        "trading_date": trading_date.isoformat(),
        "score_version": version,
        "evaluated_signals": len(rows),
        "pool_count": len(pool),
        "candidate_count": len(selected),
        "records": len(selected),
        "zero_reason": zero_reason,
        "exclusions": dict(sorted(exclusions.items())),
        "elapsed_seconds": elapsed,
    }


def _score_pool(
    db: Session,
    trading_date: date,
    pool: list[_PoolEntry],
    config: dict[str, Any],
    summary: dict[str, Any],
    exclusions: dict[str, int],
) -> list[_PoolEntry]:
    weights = config["weights"]
    components = config["components"]
    universe = db.scalars(
        select(Instrument)
        .where(
            Instrument.instrument_type.in_(config["pool"]["instrument_types"]),
            Instrument.status == "active",
        )
        .order_by(Instrument.id)
    ).all()

    # technical: percentiles within the same strategy's pool.
    technical_items = components["technical"]["items"]
    for strategy in config["pool"]["strategies"]:
        peers = [entry for entry in pool if entry.strategy == strategy]
        for entry in peers:
            items = {}
            for key, spec in technical_items.items():
                better = (
                    spec["better"][strategy]
                    if isinstance(spec["better"], dict)
                    else spec["better"]
                )
                value = entry.technical[key]
                percentile = _directed_percentile(
                    value, [peer.technical[key] for peer in peers], better
                )
                items[key] = _item(
                    value,
                    percentile,
                    float(spec["weight"]),
                    better,
                    "signal_evidence_missing",
                )
            entry.components["technical"] = {
                **_component(
                    items,
                    weights["technical"],
                    inference=False,
                    null_reason="technical_inputs_missing",
                ),
                "population": len(peers),
            }

    # chips: percentiles across the whole market's stocks on the date.
    chip_items = components["chips"]["items"]
    chips = {
        instrument.id: _chip_inputs(db, instrument.id, trading_date)
        for instrument in universe
    }
    chip_peers = {key: [row[key] for row in chips.values()] for key in chip_items}
    summary["chips_population"] = {
        key: sum(value is not None for value in values)
        for key, values in chip_peers.items()
    }
    for entry in pool:
        raw = chips.get(entry.instrument.id) or _chip_inputs(
            db, entry.instrument.id, trading_date
        )
        items = {
            key: _item(
                raw[key],
                _directed_percentile(raw[key], chip_peers[key], spec["better"]),
                float(spec["weight"]),
                spec["better"],
                "chip_or_volume_sessions_incomplete",
            )
            for key, spec in chip_items.items()
        }
        entry.components["chips"] = {
            **_component(
                items,
                weights["chips"],
                inference=False,
                null_reason="chip_inputs_missing",
            ),
            "population": {key: summary["chips_population"][key] for key in chip_items},
            "raw": {"foreign_5d": raw["foreign_5d"], "trust_5d": raw["trust_5d"]},
        }

    # news_sentiment: LLM direction of rule-linked news, market percentile.
    news_stats, news_summary = _news_inputs(db, trading_date, list(universe), config)
    summary["news"] = news_summary
    news_peers = [row["raw"] for row in news_stats.values()]
    for entry in pool:
        row = news_stats.get(entry.instrument.id)
        value = None if row is None else float(row["raw"])
        null_reason = news_summary.get("null_reason", "instrument_not_in_universe")
        items = {
            "net_direction": _item(
                value,
                _directed_percentile(value, news_peers, "higher"),
                1.0,
                "higher",
                null_reason,
            )
        }
        entry.components["news_sentiment"] = {
            **_component(
                items,
                weights["news_sentiment"],
                inference=True,
                null_reason=null_reason,
            ),
            "population": len(news_peers),
            "instruments_with_news": news_summary.get("instruments_with_news"),
            "counts": {
                key: row[key]
                for key in ("linked", "positive", "negative", "mixed", "unscored")
            }
            if row is not None
            else None,
            "news_ids": row["news_ids"] if row is not None else [],
        }

    # group: best board percentile among qualified industry/theme groups.
    groups, group_summary = _group_inputs(db, trading_date)
    summary["groups"] = group_summary
    for entry in pool:
        entry.groups = groups.get(entry.instrument.id, [])
        best = next((group for group in entry.groups if group["qualified"]), None)
        value = best["board_percentile"] if best else None
        items = {
            "board_percentile": _item(value, value, 1.0, "higher", "no_qualified_group")
        }
        entry.components["group"] = {
            **_component(
                items,
                weights["group"],
                inference=False,
                null_reason="no_qualified_group",
            ),
            "source": None
            if best is None
            else {
                key: best[key]
                for key in ("group_id", "name", "board", "rank", "board_size")
            },
        }

    eligible: list[_PoolEntry] = []
    minimum = float(config["minimum_weight_coverage"])
    for entry in pool:
        entry.total, entry.coverage = weighted_available_mean(
            {key: entry.components[key]["score"] for key in weights},
            weights,
        )
        missing_required = [
            key
            for key in config["required_components"]
            if entry.components[key]["score"] is None
        ]
        if entry.total is None or missing_required or entry.coverage + 1e-12 < minimum:
            exclusions["insufficient_score_coverage"] += 1
            continue
        eligible.append(entry)

    best_by_instrument: dict[int, _PoolEntry] = {}
    alternatives: dict[int, list[_PoolEntry]] = defaultdict(list)
    strategy_order = config["pool"]["strategies"]
    for entry in sorted(
        eligible,
        key=lambda item: (-(item.total or 0.0), strategy_order.index(item.strategy)),
    ):
        if entry.instrument.id in best_by_instrument:
            alternatives[entry.instrument.id].append(entry)
            exclusions["same_instrument_lower_scored_strategy"] += 1
            continue
        best_by_instrument[entry.instrument.id] = entry
    for instrument_id, entry in best_by_instrument.items():
        entry.components["alternatives"] = [
            {
                "strategy": other.strategy,
                "signal_id": other.signal.id,
                "total_score": round(other.total, 6),
            }
            for other in alternatives.get(instrument_id, [])
        ]
    ranked = sorted(best_by_instrument.values(), key=_sort_key)
    maximum = int(config["list_size"]["maximum"])
    if len(ranked) > maximum:
        exclusions["below_list_cutoff"] += len(ranked) - maximum
    return ranked[:maximum]


def latest_signal_date(db: Session) -> date | None:
    return db.scalar(
        select(func.max(Signal.signal_date)).where(
            Signal.signal_key.like(f"{CANDIDATE_SCORE['pool']['signal_namespace']}-%")
        )
    )


def run_candidates(target: date | None = None) -> dict[str, Any]:
    """Compute one trading date's list with the current score version."""

    # pipeline.SessionLocal, like the other daily steps (and their test patches).
    with pipeline.SessionLocal() as db:
        trading_date = target or latest_signal_date(db)
        if trading_date is None:
            return {
                "status": "no_data",
                "reason": "no_signals_for_date",
                "score_version": CANDIDATE_SCORE_VERSION,
                "records": 0,
            }
        return compute_daily_candidates(db, trading_date)
