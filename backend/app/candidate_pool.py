"""候選池 ``candidate_pool_v1`` (Issue #1020): compute, store and read.

The spec is ``docs/spec/candidate_pool.md``; the rules are written there once
and only summarised here.  The pool is "what the pre-open AI looks at today"
(#1002, #1041), not "what the rules say can be bought": it is the union of the
sources below, each stock tagged with every source that named it (``source``,
trigger value, data date and source ids), ranked by tier and capped.

- **Evening** (the daily's ``candidate_pool`` step, after ``theme_discovery``):
  every source on trading date T; at most ``PoolConfig.evening_cap`` (40)
  selected, at most ``theme_cap`` (4) per theme except tiers 1 and 2.  The
  stocks left out are stored too, ``reject_reason`` ``cap`` or ``theme_cap``.
- **Morning** (the 08:20 ``preopen`` job): only the stocks named by news
  collected after the evening run's ``computed_at`` (the #755 window), not
  already selected in the evening, at most ``morning_cap`` (10).
- **Written once**: one run per trading date, version and phase; a rerun
  returns the stored run and writes nothing (``candidate_runs``' rule).

Nothing here is a buy or sell signal, and the today list does not read it.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from .candidate_runs import read_run
from .clock import utcnow
from .models import (
    CandidatePoolItem,
    CandidatePoolRun,
    ChipSnapshot,
    DailyCandidate,
    Event,
    GroupMembership,
    Instrument,
    MarketBar,
    MonthlyRevenue,
    NewsItem,
    PortfolioPosition,
    StrategyListItem,
    StrategyListRun,
    ThemeClusterMember,
    ThemeClusterRun,
    ThemeGroup,
    ThemeHeatRun,
    ThemeHeatScore,
)
from .theme_table import THEME_GROUP_TYPE

CANDIDATE_POOL_VERSION = "candidate_pool_v1"
EVENING = "evening"
MORNING = "morning"
PHASES = (EVENING, MORNING)
INDEX_EXCHANGE = "TWSE"
INDEX_SYMBOL = "TAIEX"
INSTRUMENT_TYPES = ("stock", "ipo")
SHARES_PER_LOT = 1000
TAIPEI_OFFSET = timedelta(hours=8)
NOT_A_SIGNAL = "不是買賣訊號"
CAP = "cap"
THEME_CAP = "theme_cap"
# Ids per IN (...) of a query (#791: SQLite's bound variable limit).
QUERY_BATCH = 900
# At most this many source ids per source (news items).
MAX_SOURCE_IDS = 5

# The sources and their tier (#1003 AC-3 §3).  A stock's tier is the best
# (smallest) of its sources'.
SOURCE_TIERS: dict[str, int] = {
    "watchlist": 1,
    "holding": 1,
    "rule_signal": 2,
    "hot_theme": 3,
    "h2": 4,
    "x4": 4,
    "cluster": 5,
    "news": 5,
    "mops_event": 5,
    "revenue": 5,
    "chips": 5,
    "volume": 5,
    "near_high_240": 5,
    "limit": 5,
    "gap": 5,
    "morning_news": 5,
}
SOURCES = tuple(SOURCE_TIERS)
EVENING_SOURCES = tuple(source for source in SOURCES if source != "morning_news")
# Tiers the theme cap does not limit (they still count toward it).
THEME_CAP_EXEMPT_TIERS = frozenset({1, 2})


@dataclass(frozen=True)
class PoolConfig:
    evening_cap: int = 40
    morning_cap: int = 10
    theme_cap: int = 4
    # The liquidity floor of the market-wide sources (candidate_score_v6's).
    liquidity_days: int = 20
    min_average_lots: float = 1000.0
    hot_theme_top: int = 5
    hot_theme_news_ratio: float = 3.0
    hot_theme_members: int = 4
    cluster_count: int = 2
    cluster_members: int = 3
    cluster_max_known_share: float = 0.5
    h2_top: int = 10
    x4_top: int = 10
    news_sessions: int = 2
    mops_min_move: float = 0.03
    mops_min_volume_ratio: float = 1.5
    revenue_min_yoy: float = 30.0
    revenue_sessions: int = 5
    chips_sessions: int = 5
    chips_top: int = 30
    volume_ratio: float = 2.5
    near_high_sessions: int = 240
    near_high_min_sessions: int = 200
    near_high_gap: float = 0.05
    limit_move: float = 0.095
    gap_min: float = 0.03
    morning_theme_members: int = 3

    @property
    def history_sessions(self) -> int:
        return self.near_high_sessions + 1

    def as_json(self) -> dict[str, Any]:
        return {
            "version": CANDIDATE_POOL_VERSION,
            "spec": "docs/spec/candidate_pool.md",
            "tiers": dict(SOURCE_TIERS),
            **asdict(self),
        }


DEFAULT_CONFIG = PoolConfig()


class CandidatePoolDataError(RuntimeError):
    """T cannot be computed (not a TAIEX session)."""


# --- the pure parts ---------------------------------------------------------


@dataclass
class Hit:
    """One source naming one stock."""

    source: str
    value: dict[str, Any]
    data_date: date | None
    source_ids: list[str]
    # The order within the tier (a list rank, a theme's rank); lower first.
    order: float = 0.0

    def as_json(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "value": _clean(self.value),
            "data_date": self.data_date.isoformat() if self.data_date else None,
            "source_ids": list(self.source_ids[:MAX_SOURCE_IDS]),
        }


@dataclass
class Entry:
    instrument_id: int
    hits: dict[str, Hit] = field(default_factory=dict)
    themes: list[dict[str, Any]] = field(default_factory=list)
    features: dict[str, Any] = field(default_factory=dict)
    selected: bool = False
    reject_reason: str | None = None
    rank: int | None = None

    def add(self, hit: Hit) -> None:
        kept = self.hits.get(hit.source)
        if kept is None:
            self.hits[hit.source] = hit
            return
        # A second hit of a source (a stock in two hot themes): keep the
        # first's value, add the ids, take the better order.
        kept.source_ids.extend(i for i in hit.source_ids if i not in kept.source_ids)
        kept.order = min(kept.order, hit.order)
        extra = kept.value.setdefault("also", [])
        extra.append(hit.value)

    @property
    def tier(self) -> int:
        return min(SOURCE_TIERS[source] for source in self.hits)

    @property
    def source_count(self) -> int:
        return len(self.hits)

    def sort_key(self) -> tuple:
        tier = self.tier
        order = min(
            (
                hit.order
                for hit in self.hits.values()
                if SOURCE_TIERS[hit.source] == tier
            ),
            default=0.0,
        )
        move = self.features.get("return_5d")
        strength = abs(move) if isinstance(move, (int, float)) else -1.0
        return (tier, -self.source_count, order, -strength, self.instrument_id)


def select_entries(
    entries: Iterable[Entry],
    cap: int,
    theme_cap: int,
    theme_counts: Counter | None = None,
) -> list[Entry]:
    """Rank and cap ``entries`` in place; every entry ordered, selected first.

    Ordered by tier, then more sources first, then the tier's own order, then
    the larger absolute 5-session return, then instrument id.  Walking that
    order: past ``cap`` selected an entry is ``cap``; one in a theme that
    already has ``theme_cap`` selected (``theme_counts`` starts the count) is
    ``theme_cap`` unless its tier is 1 or 2; otherwise it is selected and
    counts toward each of its themes.
    """

    counts = Counter() if theme_counts is None else Counter(theme_counts)
    ordered = sorted(entries, key=Entry.sort_key)
    rank = 0
    for entry in ordered:
        themes = [theme["theme_id"] for theme in entry.themes]
        if rank >= cap:
            entry.selected, entry.reject_reason = False, CAP
            continue
        if entry.tier not in THEME_CAP_EXEMPT_TIERS and any(
            counts[theme] >= theme_cap for theme in themes
        ):
            entry.selected, entry.reject_reason = False, THEME_CAP
            continue
        rank += 1
        entry.selected, entry.reject_reason, entry.rank = True, None, rank
        counts.update(themes)
    return sorted(ordered, key=lambda entry: (not entry.selected, entry.rank or 0))


def _clean(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6) if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


@dataclass
class Bars:
    """One stock's sessions, oldest first, on T's price basis; None: no bar."""

    instrument_id: int
    close: list[float | None]
    open: list[float | None]
    high: list[float | None]
    low: list[float | None]
    volume: list[float | None]
    amount: list[float | None]
    last_bar_id: int | None = None


def stock_features(
    bars: Bars, index_close: Sequence[float], config: PoolConfig
) -> dict[str, Any]:
    """The values the sources and the AI read; None when the data is missing."""

    close, volume = bars.close, bars.volume
    n = len(close)

    def ret(days: int) -> float | None:
        if n <= days or close[-1] is None or close[-1 - days] in (None, 0):
            return None
        return close[-1] / close[-1 - days] - 1.0

    def index_ret(days: int) -> float | None:
        if len(index_close) <= days or not index_close[-1 - days]:
            return None
        return index_close[-1] / index_close[-1 - days] - 1.0

    days = config.liquidity_days
    recent = volume[-days:]
    lots = (
        _mean([float(v) for v in recent]) / SHARES_PER_LOT
        if len(recent) == days and all(v is not None for v in recent)
        else None
    )
    amounts = bars.amount[-days:]
    amount_20 = (
        _mean([float(v) for v in amounts])
        if len(amounts) == days and all(v is not None for v in amounts)
        else None
    )
    prior = volume[-days - 1 : -1]
    volume_ratio = None
    if (
        len(prior) == days
        and all(v is not None for v in prior)
        and volume[-1] is not None
        and sum(prior) > 0  # type: ignore[arg-type]
    ):
        volume_ratio = float(volume[-1]) / (sum(prior) / days)  # type: ignore[arg-type]
    highs = [
        h if h is not None else c
        for h, c in zip(
            bars.high[-config.near_high_sessions :],
            close[-config.near_high_sessions :],
        )
    ]
    known = [value for value in highs if value is not None]
    high_gap = None
    if len(known) >= config.near_high_min_sessions and close[-1] is not None:
        high_gap = close[-1] / max(known) - 1.0
    gap = gap_filled = None
    if n >= 2 and bars.open[-1] is not None and close[-2]:
        gap = bars.open[-1] / close[-2] - 1.0
        if gap > 0 and bars.low[-1] is not None and bars.high[-2] is not None:
            gap_filled = not bars.low[-1] > bars.high[-2]
        elif gap < 0 and bars.high[-1] is not None and bars.low[-2] is not None:
            gap_filled = not bars.high[-1] < bars.low[-2]
    ret5, ret20 = ret(5), ret(20)
    idx5, idx20 = index_ret(5), index_ret(20)
    return {
        "close": close[-1],
        "return_1d": ret(1),
        "return_5d": ret5,
        "return_20d": ret20,
        "excess_5d": None if ret5 is None or idx5 is None else ret5 - idx5,
        "excess_20d": None if ret20 is None or idx20 is None else ret20 - idx20,
        "average_lots_20d": lots,
        "average_amount_20d": amount_20,
        "volume_ratio": volume_ratio,
        "high_gap_240": high_gap,
        "gap": gap,
        "gap_filled": gap_filled,
        "is_red": (
            close[-1] is not None
            and bars.open[-1] is not None
            and close[-1] > bars.open[-1]
        ),
    }


def is_liquid(features: Mapping[str, Any], config: PoolConfig) -> bool:
    lots = features.get("average_lots_20d")
    return lots is not None and lots >= config.min_average_lots


def _percentiles(values: Mapping[int, float | None]) -> dict[int, float]:
    """Each id's share of the others it beats (ties half); None is 0."""

    known = [value for value in values.values() if value is not None]
    out: dict[int, float] = {}
    for key, value in values.items():
        if value is None or len(known) < 2:
            out[key] = 0.0 if value is None else 1.0
            continue
        below = sum(1 for other in known if other < value)
        same = sum(1 for other in known if other == value) - 1
        out[key] = (below + same / 2) / (len(known) - 1)
    return out


def theme_picks(
    members: Sequence[int],
    features: Mapping[int, Mapping[str, Any]],
    count: int,
) -> list[tuple[int, str]]:
    """The theme's leader (largest 20-session mean amount) and the strongest
    others by the percentile sum of 5-session excess and institutional ratio.

    ``members`` are the liquid ones; returns (instrument id, role)."""

    if not members or count <= 0:
        return []
    ids = sorted(members)
    leader = max(
        ids,
        key=lambda i: (features[i].get("average_amount_20d") or 0.0, -i),
    )
    rest = [i for i in ids if i != leader]
    excess = _percentiles({i: features[i].get("excess_5d") for i in rest})
    flow = _percentiles({i: features[i].get("institutional_ratio_5d") for i in rest})
    rest.sort(key=lambda i: (-(excess[i] + flow[i]), i))
    return [(leader, "leader")] + [(i, "second") for i in rest[: count - 1]]


# --- reading the inputs -----------------------------------------------------


def _batches(ids: Sequence[int]) -> Iterable[list[int]]:
    ids = list(ids)
    for start in range(0, len(ids), QUERY_BATCH):
        yield ids[start : start + QUERY_BATCH]


def index_sessions(db: Session, day: date, count: int) -> list[tuple[date, float]]:
    """The last ``count`` TAIEX sessions up to ``day`` (which must be one)."""

    rows = db.execute(
        select(MarketBar.trading_date, MarketBar.close)
        .join(Instrument, Instrument.id == MarketBar.instrument_id)
        .where(
            Instrument.instrument_type == "index",
            Instrument.exchange == INDEX_EXCHANGE,
            Instrument.symbol == INDEX_SYMBOL,
            MarketBar.trading_date <= day,
        )
        .order_by(desc(MarketBar.trading_date))
        .limit(count)
    ).all()
    if not rows or rows[0].trading_date != day:
        raise CandidatePoolDataError(f"no {INDEX_SYMBOL} bar on {day.isoformat()}")
    return [(row.trading_date, float(row.close)) for row in reversed(rows)]


def liquid_ids(
    db: Session, sessions: Sequence[date], config: PoolConfig
) -> dict[int, float]:
    """Active stock/ipo ids with a 20-session mean volume ≥ the floor.

    A session without a bar or with a null volume leaves no average (never
    read as 0)."""

    window = list(sessions[-config.liquidity_days :])
    volumes: dict[int, list[float]] = {}
    for instrument_id, volume in db.execute(
        select(MarketBar.instrument_id, MarketBar.volume)
        .join(Instrument, Instrument.id == MarketBar.instrument_id)
        .where(
            Instrument.instrument_type.in_(INSTRUMENT_TYPES),
            Instrument.status == "active",
            MarketBar.trading_date >= window[0],
            MarketBar.trading_date <= window[-1],
            MarketBar.volume.is_not(None),
        )
    ).all():
        volumes.setdefault(instrument_id, []).append(float(volume))
    out: dict[int, float] = {}
    for instrument_id, values in volumes.items():
        if len(values) != len(window):
            continue
        lots = _mean(values) / SHARES_PER_LOT
        if lots >= config.min_average_lots:
            out[instrument_id] = lots
    return out


def load_bars(
    db: Session, ids: Iterable[int], sessions: Sequence[date]
) -> dict[int, Bars]:
    """Bars of ``ids`` on ``sessions``, on the last session's price basis
    (``worker.pipeline._action_factor_by_bar``, the basis theme_heat uses)."""

    from worker.pipeline import _action_factor_by_bar

    position = {day: k for k, day in enumerate(sessions)}
    size = len(sessions)
    rows: dict[int, list[Any]] = {}
    for chunk in _batches(sorted(set(ids))):
        for row in db.execute(
            select(
                MarketBar.id,
                MarketBar.instrument_id,
                MarketBar.trading_date,
                MarketBar.open,
                MarketBar.high,
                MarketBar.low,
                MarketBar.close,
                MarketBar.volume,
                MarketBar.turnover,
            )
            .where(
                MarketBar.instrument_id.in_(chunk),
                MarketBar.trading_date >= sessions[0],
                MarketBar.trading_date <= sessions[-1],
            )
            .order_by(MarketBar.instrument_id, MarketBar.trading_date)
        ).all():
            rows.setdefault(row.instrument_id, []).append(row)
    out: dict[int, Bars] = {}
    for instrument_id, bars in rows.items():
        factors = _action_factor_by_bar(db, instrument_id, bars)
        item = Bars(instrument_id, *([None] * size for _ in range(6)))  # type: ignore[arg-type]
        for bar, factor in zip(bars, factors):
            k = position.get(bar.trading_date)
            if k is None or not factor or factor <= 0:
                continue

            def adjusted(value: float | None) -> float | None:
                return None if value is None or value <= 0 else value / factor

            item.close[k] = adjusted(bar.close)
            item.open[k] = adjusted(bar.open)
            item.high[k] = adjusted(bar.high)
            item.low[k] = adjusted(bar.low)
            item.volume[k] = None if bar.volume is None else float(bar.volume)
            if bar.turnover:
                item.amount[k] = float(bar.turnover)
            elif bar.close is not None and bar.volume is not None:
                item.amount[k] = float(bar.close) * float(bar.volume)
            if k == size - 1:
                item.last_bar_id = bar.id
        out[instrument_id] = item
    return out


def institutional_ratios(
    db: Session,
    ids: Iterable[int],
    sessions: Sequence[date],
    bars: Mapping[int, Bars],
    config: PoolConfig,
) -> dict[int, tuple[float, int | None]]:
    """Net buy of the three institutions over the last 5 sessions (shares)
    over the volume of the last 20; and the chip row id of T.  A stock needs
    a foreign value on each of the 5 sessions."""

    first = sessions[-config.chips_sessions]
    flows: dict[int, list[float]] = {}
    last_ids: dict[int, int] = {}
    for chunk in _batches(sorted(set(ids))):
        for row in db.execute(
            select(
                ChipSnapshot.id,
                ChipSnapshot.instrument_id,
                ChipSnapshot.trading_date,
                ChipSnapshot.foreign_buy,
                ChipSnapshot.trust_buy,
                ChipSnapshot.dealer_buy,
            ).where(
                ChipSnapshot.instrument_id.in_(chunk),
                ChipSnapshot.trading_date >= first,
                ChipSnapshot.trading_date <= sessions[-1],
            )
        ).all():
            if row.foreign_buy is None:
                continue
            flows.setdefault(row.instrument_id, []).append(
                (row.foreign_buy or 0.0)
                + (row.trust_buy or 0.0)
                + (row.dealer_buy or 0.0)
            )
            if row.trading_date == sessions[-1]:
                last_ids[row.instrument_id] = row.id
    out: dict[int, tuple[float, int | None]] = {}
    for instrument_id, values in flows.items():
        if len(values) != config.chips_sessions:
            continue
        item = bars.get(instrument_id)
        recent = [] if item is None else item.volume[-config.liquidity_days :]
        if not recent or any(v is None for v in recent):
            continue
        total = sum(recent)  # type: ignore[arg-type]
        if total <= 0:
            continue
        out[instrument_id] = (sum(values) / total, last_ids.get(instrument_id))
    return out


def theme_memberships(db: Session, day: date) -> dict[int, list[str]]:
    """Each stock's active themes (theme table, role member) valid on ``day``."""

    rows = db.execute(
        select(GroupMembership.instrument_id, GroupMembership.group_id)
        .join(ThemeGroup, ThemeGroup.id == GroupMembership.group_id)
        .where(
            ThemeGroup.active.is_(True),
            ThemeGroup.group_type == THEME_GROUP_TYPE,
            GroupMembership.role == "member",
            GroupMembership.valid_from <= day,
            or_(GroupMembership.valid_to.is_(None), GroupMembership.valid_to >= day),
        )
    ).all()
    out: dict[int, set[str]] = {}
    for instrument_id, group_id in rows:
        out.setdefault(instrument_id, set()).add(group_id)
    return {key: sorted(value) for key, value in out.items()}


def _theme_names(db: Session, group_ids: Iterable[str]) -> dict[str, str]:
    ids = sorted(set(group_ids))
    if not ids:
        return {}
    return {
        row.id: row.display_name_zh or row.name
        for row in db.scalars(select(ThemeGroup).where(ThemeGroup.id.in_(ids)))
    }


def _taipei_date(value: datetime) -> date:
    return (value + TAIPEI_OFFSET).date()


def _taipei_day_start_utc(day: date) -> datetime:
    return datetime.combine(day, time.min) - TAIPEI_OFFSET


def _symbol_index(db: Session) -> dict[str, list[int]]:
    """Active stock/ipo ids by bare code and by ``exchange:code``."""

    index: dict[str, list[int]] = {}
    for instrument_id, exchange, symbol in db.execute(
        select(Instrument.id, Instrument.exchange, Instrument.symbol).where(
            Instrument.instrument_type.in_(INSTRUMENT_TYPES),
            Instrument.status == "active",
        )
    ).all():
        index.setdefault(symbol, []).append(instrument_id)
        index.setdefault(f"{exchange}:{symbol}", []).append(instrument_id)
    return index


def _directions(db: Session, news_ids: Sequence[int]) -> dict[int, str]:
    from worker.news_llm import PROMPT_VERSION, done_results

    from .preopen_news import direction_of

    out: dict[int, str] = {}
    for chunk in _batches(news_ids):
        for news_id, result in done_results(db, chunk, PROMPT_VERSION).items():
            direction = direction_of(result)
            if direction is not None:
                out[news_id] = direction
    return out


# --- the evening sources ----------------------------------------------------


@dataclass
class Context:
    day: date
    sessions: list[date]
    index_close: list[float]
    liquid: dict[int, float]
    features: dict[int, dict[str, Any]]
    bar_ids: dict[int, int | None]
    themes: dict[int, list[str]]
    config: PoolConfig
    ratios: dict[int, tuple[float, int | None]] = field(default_factory=dict)
    status: dict[str, str] = field(default_factory=dict)


def _bar_hit(ctx: Context, source: str, instrument_id: int, value: dict) -> Hit:
    bar_id = ctx.bar_ids.get(instrument_id)
    return Hit(
        source,
        value,
        ctx.day,
        [f"market_bar:{bar_id}"] if bar_id else [],
    )


def personal_hits(db: Session, ctx: Context) -> list[tuple[int, Hit]]:
    hits: list[tuple[int, Hit]] = []
    for instrument_id in db.scalars(
        select(Instrument.id).where(Instrument.is_watchlisted.is_(True))
    ):
        hits.append(
            (
                instrument_id,
                Hit("watchlist", {}, ctx.day, [f"instrument:{instrument_id}"]),
            )
        )
    for position in db.scalars(
        select(PortfolioPosition).where(PortfolioPosition.shares > 0)
    ):
        hits.append(
            (
                position.instrument_id,
                Hit(
                    "holding",
                    {"shares": position.shares},
                    ctx.day,
                    [f"portfolio_position:{position.id}"],
                ),
            )
        )
    return hits


def rule_signal_hits(db: Session, ctx: Context) -> list[tuple[int, Hit]]:
    run = read_run(db, ctx.day)
    if run is None:
        ctx.status["rule_signal"] = "no_candidate_run"
        return []
    ctx.status["rule_signal"] = "available"
    return [
        (
            row.instrument_id,
            Hit(
                "rule_signal",
                {
                    "rank": row.rank,
                    "strategy": row.strategy,
                    "score_version": row.score_version,
                    "signal_id": row.signal_id,
                },
                row.data_as_of,
                [f"daily_candidate:{row.id}"],
                order=row.rank,
            ),
        )
        for row in db.scalars(
            select(DailyCandidate)
            .where(DailyCandidate.candidate_run_id == run.id)
            .order_by(DailyCandidate.rank)
        )
    ]


def strategy_list_hits(
    db: Session, ctx: Context, key: str, top: int
) -> list[tuple[int, Hit]]:
    run = db.scalar(
        select(StrategyListRun)
        .where(StrategyListRun.strategy == key, StrategyListRun.trading_date == ctx.day)
        .order_by(desc(StrategyListRun.id))
        .limit(1)
    )
    if run is None:
        ctx.status[key] = "no_list"
        return []
    ctx.status[key] = "available"
    return [
        (
            row.instrument_id,
            Hit(
                key,
                {"rank": row.rank, "version": row.version},
                row.trading_date,
                [f"strategy_list_item:{row.id}"],
                order=row.rank,
            ),
        )
        for row in db.scalars(
            select(StrategyListItem)
            .where(StrategyListItem.run_id == run.id, StrategyListItem.rank <= top)
            .order_by(StrategyListItem.rank)
        )
    ]


def hot_theme_hits(db: Session, ctx: Context) -> list[tuple[int, Hit]]:
    from .theme_heat import THEME_HEAT_VERSION

    config = ctx.config
    run = db.scalar(
        select(ThemeHeatRun).where(
            ThemeHeatRun.trading_date == ctx.day,
            ThemeHeatRun.version == THEME_HEAT_VERSION,
        )
    )
    if run is None:
        ctx.status["hot_theme"] = "no_heat_run"
        return []
    ctx.status["hot_theme"] = "available"
    scores = db.scalars(
        select(ThemeHeatScore)
        .where(ThemeHeatScore.run_id == run.id, ThemeHeatScore.rank.is_not(None))
        .order_by(ThemeHeatScore.rank)
    ).all()
    chosen: list[tuple[ThemeHeatScore, str]] = []
    for score in scores:
        news = (score.components_json or {}).get("news") or {}
        ratio = news.get("raw")
        if score.rank <= config.hot_theme_top:
            chosen.append((score, "top"))
        elif ratio is not None and ratio >= config.hot_theme_news_ratio:
            chosen.append((score, "news_surge"))
    by_theme: dict[str, list[int]] = {}
    for instrument_id, groups in ctx.themes.items():
        if instrument_id not in ctx.liquid:
            continue
        for group_id in groups:
            by_theme.setdefault(group_id, []).append(instrument_id)
    hits: list[tuple[int, Hit]] = []
    for score, reason in chosen:
        picks = theme_picks(
            by_theme.get(score.group_id, []), ctx.features, config.hot_theme_members
        )
        for position, (instrument_id, role) in enumerate(picks):
            hits.append(
                (
                    instrument_id,
                    Hit(
                        "hot_theme",
                        {
                            "theme_id": score.group_id,
                            "heat": score.heat,
                            "theme_rank": score.rank,
                            "reason": reason,
                            "role": role,
                            "news_ratio": (
                                (score.components_json or {}).get("news") or {}
                            ).get("raw"),
                        },
                        score.trading_date,
                        [f"theme_heat_score:{score.id}"],
                        order=score.rank * 10 + position,
                    ),
                )
            )
    return hits


def cluster_hits(db: Session, ctx: Context) -> list[tuple[int, Hit]]:
    from .theme_clusters import THEME_CLUSTER_VERSION

    config = ctx.config
    run = db.scalar(
        select(ThemeClusterRun).where(
            ThemeClusterRun.trading_date == ctx.day,
            ThemeClusterRun.version == THEME_CLUSTER_VERSION,
        )
    )
    if run is None:
        ctx.status["cluster"] = "no_cluster_run"
        return []
    ctx.status["cluster"] = "available"
    grouped: dict[int, list[ThemeClusterMember]] = {}
    for row in db.scalars(
        select(ThemeClusterMember)
        .where(ThemeClusterMember.theme_cluster_run_id == run.id)
        .order_by(ThemeClusterMember.cluster_no, ThemeClusterMember.instrument_id)
    ):
        grouped.setdefault(row.cluster_no, []).append(row)
    hits: list[tuple[int, Hit]] = []
    taken = 0
    for cluster_no in sorted(grouped):
        members = grouped[cluster_no]
        # Not yet named: no theme holds more than the share of its members
        # (theme_discovery's test, themes only: candidates are not themes).
        counts = Counter(
            group_id
            for row in members
            for group_id in ctx.themes.get(row.instrument_id, ())
        )
        if (
            counts
            and max(counts.values()) / len(members) > config.cluster_max_known_share
        ):
            continue
        taken += 1
        if taken > config.cluster_count:
            break
        best = sorted(
            members, key=lambda row: (-row.excess_return_20d, row.instrument_id)
        )
        for position, row in enumerate(best[: config.cluster_members]):
            hits.append(
                (
                    row.instrument_id,
                    Hit(
                        "cluster",
                        {
                            "cluster_no": cluster_no,
                            "cluster_size": row.cluster_size,
                            "member_mean_corr": row.member_mean_corr,
                            "excess_return_20d": row.excess_return_20d,
                        },
                        row.trading_date,
                        [f"theme_cluster_member:{row.id}"],
                        order=cluster_no * 10 + position,
                    ),
                )
            )
    return hits


def news_hits(db: Session, ctx: Context) -> list[tuple[int, Hit]]:
    """Media items of the last ``news_sessions`` sessions' Taipei days whose
    rule relation (``symbols_json``) names a liquid stock and that have a done
    AI reading."""

    first = ctx.sessions[-ctx.config.news_sessions]
    since = _taipei_day_start_utc(first)
    until = _taipei_day_start_utc(ctx.day + timedelta(days=1))
    when = func.coalesce(NewsItem.published_at, NewsItem.collected_at)
    items = db.execute(
        select(NewsItem.id, NewsItem.symbols_json, when.label("at")).where(
            NewsItem.status == "active",
            NewsItem.source_kind == "media",
            when >= since,
            when < until,
        )
    ).all()
    directions = _directions(db, [row.id for row in items])
    symbols = _symbol_index(db)
    found: dict[int, list[tuple[int, date]]] = {}
    for row in items:
        if row.id not in directions:
            continue
        ids = {
            i for token in row.symbols_json or [] for i in symbols.get(str(token), ())
        }
        for instrument_id in ids & set(ctx.liquid):
            found.setdefault(instrument_id, []).append((row.id, _taipei_date(row.at)))
    hits: list[tuple[int, Hit]] = []
    for instrument_id, entries in found.items():
        entries.sort(key=lambda pair: (pair[1], pair[0]), reverse=True)
        counted = Counter(directions[news_id] for news_id, _day in entries)
        hits.append(
            (
                instrument_id,
                Hit(
                    "news",
                    {
                        "news_count": len(entries),
                        "directions": dict(sorted(counted.items())),
                    },
                    entries[0][1],
                    [f"news_item:{news_id}" for news_id, _day in entries],
                ),
            )
        )
    return hits


def mops_hits(db: Session, ctx: Context) -> list[tuple[int, Hit]]:
    config = ctx.config
    hits: list[tuple[int, Hit]] = []
    for event in db.scalars(
        select(Event)
        .where(Event.event_type == "material_information", Event.event_date == ctx.day)
        .order_by(Event.id)
    ):
        features = ctx.features.get(event.instrument_id or 0)
        if event.instrument_id not in ctx.liquid or features is None:
            continue
        move, ratio = features.get("return_1d"), features.get("volume_ratio")
        if not (
            (move is not None and abs(move) >= config.mops_min_move)
            or (ratio is not None and ratio >= config.mops_min_volume_ratio)
        ):
            continue
        hits.append(
            (
                event.instrument_id,
                Hit(
                    "mops_event",
                    {"title": event.title, "return_1d": move, "volume_ratio": ratio},
                    event.event_date,
                    [f"event:{event.id}"],
                ),
            )
        )
    return hits


def revenue_hits(db: Session, ctx: Context) -> list[tuple[int, Hit]]:
    config = ctx.config
    first = ctx.sessions[-config.revenue_sessions]
    rows = db.scalars(
        select(MonthlyRevenue).where(
            MonthlyRevenue.announcement_date >= first,
            MonthlyRevenue.announcement_date <= ctx.day,
            MonthlyRevenue.yoy.is_not(None),
        )
    ).all()
    rows = [row for row in rows if row.instrument_id in ctx.liquid]
    previous: dict[tuple[int, date], float | None] = {}
    months = {(row.instrument_id, _month_before(row.revenue_month)) for row in rows}
    for chunk in _batches(sorted({key[0] for key in months})):
        for instrument_id, month, yoy in db.execute(
            select(
                MonthlyRevenue.instrument_id,
                MonthlyRevenue.revenue_month,
                MonthlyRevenue.yoy,
            ).where(MonthlyRevenue.instrument_id.in_(chunk))
        ).all():
            if (instrument_id, month) in months:
                previous[(instrument_id, month)] = yoy
    hits: list[tuple[int, Hit]] = []
    for row in sorted(rows, key=lambda r: (r.instrument_id, r.revenue_month)):
        prior = previous.get((row.instrument_id, _month_before(row.revenue_month)))
        if row.yoy >= config.revenue_min_yoy:
            rule = "yoy_threshold"
        elif row.yoy > 0 and prior is not None and prior < 0:
            rule = "turned_positive"
        else:
            continue
        hits.append(
            (
                row.instrument_id,
                Hit(
                    "revenue",
                    {
                        "yoy": row.yoy,
                        "prior_month_yoy": prior,
                        "revenue_month": row.revenue_month.isoformat()[:7],
                        "rule": rule,
                    },
                    row.announcement_date,
                    [f"monthly_revenue:{row.id}"],
                ),
            )
        )
    return hits


def _month_before(month: date) -> date:
    return (month.replace(day=1) - timedelta(days=1)).replace(day=1)


def chips_hits(
    ctx: Context, ratios: Mapping[int, tuple[float, int | None]]
) -> list[tuple[int, Hit]]:
    ranked = sorted(
        (
            (ratio, instrument_id, chip_id)
            for instrument_id, (ratio, chip_id) in ratios.items()
            if instrument_id in ctx.liquid and ratio > 0
        ),
        key=lambda item: (-item[0], item[1]),
    )[: ctx.config.chips_top]
    return [
        (
            instrument_id,
            Hit(
                "chips",
                {"institutional_ratio_5d": ratio, "rank": rank},
                ctx.day,
                [f"chip_snapshot:{chip_id}"] if chip_id else [],
                order=rank,
            ),
        )
        for rank, (ratio, instrument_id, chip_id) in enumerate(ranked, start=1)
    ]


def price_hits(ctx: Context, personal: set[int]) -> list[tuple[int, Hit]]:
    config = ctx.config
    hits: list[tuple[int, Hit]] = []
    for instrument_id in sorted(set(ctx.liquid) | personal):
        features = ctx.features.get(instrument_id)
        if features is None:
            continue
        liquid = instrument_id in ctx.liquid
        ratio = features.get("volume_ratio")
        if (
            liquid
            and ratio is not None
            and ratio >= config.volume_ratio
            and features.get("is_red")
        ):
            hits.append(_pair(ctx, "volume", instrument_id, {"volume_ratio": ratio}))
        gap_high = features.get("high_gap_240")
        if liquid and gap_high is not None and gap_high >= -config.near_high_gap:
            hits.append(
                _pair(ctx, "near_high_240", instrument_id, {"high_gap_240": gap_high})
            )
        move = features.get("return_1d")
        if move is not None and (
            (liquid and move >= config.limit_move)
            or (instrument_id in personal and move <= -config.limit_move)
        ):
            hits.append(
                _pair(
                    ctx,
                    "limit",
                    instrument_id,
                    {"return_1d": move, "direction": "up" if move > 0 else "down"},
                )
            )
        gap = features.get("gap")
        if (
            liquid
            and gap is not None
            and abs(gap) >= config.gap_min
            and features.get("gap_filled") is False
        ):
            hits.append(
                _pair(
                    ctx,
                    "gap",
                    instrument_id,
                    {"gap": gap, "direction": "up" if gap > 0 else "down"},
                )
            )
    return hits


def _pair(
    ctx: Context, source: str, instrument_id: int, value: dict
) -> tuple[int, Hit]:
    return instrument_id, _bar_hit(ctx, source, instrument_id, value)


FEATURE_KEYS = (
    "close",
    "return_1d",
    "return_5d",
    "return_20d",
    "excess_5d",
    "excess_20d",
    "average_lots_20d",
    "volume_ratio",
    "institutional_ratio_5d",
    "high_gap_240",
    "gap",
)


def build_context(
    db: Session, day: date, config: PoolConfig, extra: Iterable[int]
) -> Context:
    """Sessions, liquidity, features (liquid ids and ``extra``) and themes of ``day``."""

    sessions_rows = index_sessions(db, day, config.history_sessions)
    sessions = [session for session, _close in sessions_rows]
    if len(sessions) < config.liquidity_days + 1:
        raise CandidatePoolDataError(
            f"{INDEX_SYMBOL} has {len(sessions)} sessions to {day.isoformat()}"
        )
    index_close = [close for _session, close in sessions_rows]
    liquid = liquid_ids(db, sessions, config)
    ids = set(liquid) | set(extra)
    bars = load_bars(db, ids, sessions)
    features = {
        instrument_id: stock_features(item, index_close, config)
        for instrument_id, item in bars.items()
    }
    ctx = Context(
        day=day,
        sessions=sessions,
        index_close=index_close,
        liquid=liquid,
        features=features,
        bar_ids={key: item.last_bar_id for key, item in bars.items()},
        themes=theme_memberships(db, day),
        config=config,
    )
    ctx.ratios = institutional_ratios(db, ids, sessions, bars, config)
    for instrument_id, (ratio, _chip) in ctx.ratios.items():
        if instrument_id in features:
            features[instrument_id]["institutional_ratio_5d"] = ratio
    return ctx


def _personal_ids(db: Session, day: date) -> set[int]:
    ids = set(
        db.scalars(select(Instrument.id).where(Instrument.is_watchlisted.is_(True)))
    )
    ids |= set(
        db.scalars(
            select(PortfolioPosition.instrument_id).where(PortfolioPosition.shares > 0)
        )
    )
    run = read_run(db, day)
    if run is not None:
        ids |= set(
            db.scalars(
                select(DailyCandidate.instrument_id).where(
                    DailyCandidate.candidate_run_id == run.id
                )
            )
        )
    return ids


def evening_entries(
    db: Session, day: date, config: PoolConfig
) -> tuple[Context, list[Entry]]:
    """Every source's hits on ``day`` merged per stock (not yet ranked)."""

    personal = _personal_ids(db, day)
    ctx = build_context(db, day, config, personal)
    pairs: list[tuple[int, Hit]] = []
    pairs += personal_hits(db, ctx)
    pairs += rule_signal_hits(db, ctx)
    pairs += hot_theme_hits(db, ctx)
    pairs += strategy_list_hits(db, ctx, "h2", config.h2_top)
    pairs += strategy_list_hits(db, ctx, "x4", config.x4_top)
    pairs += cluster_hits(db, ctx)
    pairs += news_hits(db, ctx)
    pairs += mops_hits(db, ctx)
    pairs += revenue_hits(db, ctx)
    pairs += chips_hits(ctx, ctx.ratios)
    watch = {i for i, hit in pairs if hit.source in ("watchlist", "holding")}
    pairs += price_hits(ctx, watch)
    return ctx, _merge(db, ctx, pairs)


def _merge(db: Session, ctx: Context, pairs: Sequence[tuple[int, Hit]]) -> list[Entry]:
    entries: dict[int, Entry] = {}
    for instrument_id, hit in pairs:
        entry = entries.get(instrument_id)
        if entry is None:
            entry = entries[instrument_id] = Entry(instrument_id)
        entry.add(hit)
    names = _theme_names(db, {g for ids in ctx.themes.values() for g in ids})
    for entry in entries.values():
        entry.themes = [
            {"theme_id": group_id, "name": names.get(group_id, group_id)}
            for group_id in ctx.themes.get(entry.instrument_id, [])
        ]
        features = ctx.features.get(entry.instrument_id, {})
        entry.features = {key: features.get(key) for key in FEATURE_KEYS}
    return list(entries.values())


# --- the morning sources ----------------------------------------------------


def morning_news(
    db: Session, evening: CandidatePoolRun, checked_at: datetime
) -> list[NewsItem]:
    """News collected after the evening run and up to ``checked_at`` (UTC-naive),
    published from the trading date's 00:00 Taipei up to it: the #755 window
    (``app.preopen_news``)."""

    from .preopen_news import _in_window

    if evening.computed_at is None or evening.computed_at >= checked_at:
        return []
    items = db.scalars(
        select(NewsItem)
        .where(
            NewsItem.status == "active",
            or_(
                NewsItem.time_consistency.is_(None),
                NewsItem.time_consistency != "conflict",
            ),
            NewsItem.collected_at > evening.computed_at,
            NewsItem.collected_at <= checked_at,
        )
        .order_by(NewsItem.id)
    ).all()
    return [
        item for item in items if _in_window(item, evening.trading_date, checked_at)
    ]


def morning_entries(
    db: Session,
    evening: CandidatePoolRun,
    checked_at: datetime,
    config: PoolConfig,
) -> tuple[list[Entry], dict[str, Any]]:
    from .theme_heat import keyword_matches, theme_keywords

    items = morning_news(db, evening, checked_at)
    summary: dict[str, Any] = {
        "window_start": evening.computed_at.isoformat(),
        "checked_at": checked_at.isoformat(),
        "news_items": len(items),
    }
    in_evening = set(
        db.scalars(
            select(CandidatePoolItem.instrument_id).where(
                CandidatePoolItem.run_id == evening.id,
                CandidatePoolItem.selected.is_(True),
            )
        )
    )
    symbols = _symbol_index(db)
    keywords = theme_keywords()
    by_symbol: dict[int, list[NewsItem]] = {}
    by_theme: dict[str, list[NewsItem]] = {}
    for item in items:
        for instrument_id in {
            i for token in item.symbols_json or [] for i in symbols.get(str(token), ())
        }:
            by_symbol.setdefault(instrument_id, []).append(item)
        for group_id in keyword_matches(f"{item.title} {item.summary or ''}", keywords):
            by_theme.setdefault(group_id, []).append(item)
    ctx = build_context(db, evening.trading_date, config, by_symbol)
    directions = _directions(db, [item.id for item in items])
    pairs: list[tuple[int, Hit]] = []

    def hit(news: list[NewsItem], value: dict[str, Any], order: float) -> Hit:
        news = sorted(news, key=lambda n: n.id, reverse=True)
        counted = Counter(directions.get(n.id, "not_judged") for n in news)
        return Hit(
            "morning_news",
            {
                "news_count": len(news),
                "directions": dict(sorted(counted.items())),
                **value,
            },
            max(
                (
                    n.event_date
                    if n.time_precision == "date"
                    else _taipei_date(n.display_time)
                )
                for n in news
                if n.display_time is not None or n.event_date is not None
            ),
            [f"news_item:{n.id}" for n in news],
            order=order,
        )

    for instrument_id, news in by_symbol.items():
        if instrument_id in in_evening or instrument_id not in ctx.liquid:
            continue
        pairs.append((instrument_id, hit(news, {"via": "symbol"}, -len(news))))
    members: dict[str, list[int]] = {}
    for instrument_id, groups in ctx.themes.items():
        if instrument_id in ctx.liquid:
            for group_id in groups:
                members.setdefault(group_id, []).append(instrument_id)
    for group_id, news in sorted(by_theme.items()):
        picks = theme_picks(
            members.get(group_id, []), ctx.features, config.morning_theme_members
        )
        for instrument_id, role in picks:
            if instrument_id in in_evening:
                continue
            pairs.append(
                (
                    instrument_id,
                    hit(
                        news,
                        {"via": "theme", "theme_id": group_id, "role": role},
                        -len(news),
                    ),
                )
            )
    summary["symbol_stocks"] = len(by_symbol)
    summary["themes"] = sorted(by_theme)
    entries = _merge(db, ctx, pairs)
    # One morning source: more news first (``order``), then the 5-day move.
    return entries, summary


# --- writing and reading ----------------------------------------------------


def stored_run(db: Session, day: date, phase: str) -> CandidatePoolRun | None:
    return db.scalar(
        select(CandidatePoolRun).where(
            CandidatePoolRun.trading_date == day,
            CandidatePoolRun.version == CANDIDATE_POOL_VERSION,
            CandidatePoolRun.phase == phase,
        )
    )


def _counts(entries: Sequence[Entry]) -> dict[str, Any]:
    sources = Counter(source for entry in entries for source in entry.hits)
    selected = Counter(
        source for entry in entries if entry.selected for source in entry.hits
    )
    by_count = Counter(entry.source_count for entry in entries)
    return {
        "sources": {
            source: sources.get(source, 0) for source in SOURCES if source in sources
        },
        "selected_sources": {
            source: selected.get(source, 0) for source in SOURCES if source in selected
        },
        "multi_source": sum(n for k, n in by_count.items() if k >= 2),
        "by_source_count": {str(k): by_count[k] for k in sorted(by_count)},
        "rejected": dict(
            sorted(Counter(e.reject_reason for e in entries if e.reject_reason).items())
        ),
        "tiers": {
            str(k): n
            for k, n in sorted(Counter(e.tier for e in entries if e.selected).items())
        },
    }


def _write(
    db: Session,
    day: date,
    phase: str,
    entries: list[Entry],
    *,
    cap: int,
    config: PoolConfig,
    computed_at: datetime,
    summary: dict[str, Any],
    base_run_id: int | None = None,
) -> CandidatePoolRun:
    selected = sum(1 for entry in entries if entry.selected)
    counts = _counts(entries)
    run = CandidatePoolRun(
        trading_date=day,
        version=CANDIDATE_POOL_VERSION,
        phase=phase,
        status="computed" if entries else "zero",
        cap=cap,
        union_count=len(entries),
        selected_count=selected,
        source_counts_json=counts["sources"],
        summary_json=_clean({**counts, **summary}),
        config_json=config.as_json(),
        base_run_id=base_run_id,
        computed_at=computed_at,
    )
    db.add(run)
    db.flush()
    db.add_all(
        CandidatePoolItem(
            run_id=run.id,
            trading_date=day,
            version=CANDIDATE_POOL_VERSION,
            phase=phase,
            instrument_id=entry.instrument_id,
            rank=entry.rank,
            tier=entry.tier,
            selected=entry.selected,
            reject_reason=entry.reject_reason,
            source_count=entry.source_count,
            sources_json=[
                entry.hits[source].as_json()
                for source in SOURCES
                if source in entry.hits
            ],
            themes_json=entry.themes,
            features_json=_clean(entry.features),
        )
        for entry in entries
    )
    db.commit()
    return run


def compute_evening(
    db: Session, day: date, config: PoolConfig | None = None, *, write: bool = True
) -> tuple[CandidatePoolRun, bool]:
    """``day``'s evening run and whether this call wrote it.

    A stored run is returned as it is (written once).  ``write=False``
    computes without writing (a dry run): the run is not added.  ``config``
    defaults to ``DEFAULT_CONFIG``."""

    config = config or DEFAULT_CONFIG
    stored = stored_run(db, day, EVENING)
    if stored is not None:
        return stored, False
    # Before any read: the morning window starts here, so news collected while
    # this runs is still counted in the morning.
    computed_at = utcnow()
    ctx, entries = evening_entries(db, day, config)
    entries = select_entries(entries, config.evening_cap, config.theme_cap)
    summary = {
        "inputs": dict(sorted(ctx.status.items())),
        "liquid_universe": len(ctx.liquid),
    }
    if not write:
        return _unsaved(
            day, EVENING, entries, config.evening_cap, config, computed_at, summary
        ), False
    return (
        _write(
            db,
            day,
            EVENING,
            entries,
            cap=config.evening_cap,
            config=config,
            computed_at=computed_at,
            summary=summary,
        ),
        True,
    )


def compute_morning(
    db: Session,
    day: date,
    checked_at: datetime,
    config: PoolConfig | None = None,
    *,
    write: bool = True,
) -> tuple[CandidatePoolRun | None, bool]:
    """The morning run of trading date ``day`` (the evening's date) at
    ``checked_at`` (UTC-naive); None without an evening run (nothing written)."""

    config = config or DEFAULT_CONFIG
    stored = stored_run(db, day, MORNING)
    if stored is not None:
        return stored, False
    evening = stored_run(db, day, EVENING)
    if evening is None:
        return None, False
    computed_at = utcnow() if write else checked_at
    entries, summary = morning_entries(db, evening, checked_at, config)
    counts = Counter(
        theme["theme_id"]
        for theme_list in db.scalars(
            select(CandidatePoolItem.themes_json).where(
                CandidatePoolItem.run_id == evening.id,
                CandidatePoolItem.selected.is_(True),
            )
        )
        for theme in theme_list or []
    )
    entries = select_entries(entries, config.morning_cap, config.theme_cap, counts)
    if not write:
        return _unsaved(
            day,
            MORNING,
            entries,
            config.morning_cap,
            config,
            computed_at,
            summary,
            evening.id,
        ), False
    return (
        _write(
            db,
            day,
            MORNING,
            entries,
            cap=config.morning_cap,
            config=config,
            computed_at=computed_at,
            summary=summary,
            base_run_id=evening.id,
        ),
        True,
    )


def _unsaved(
    day: date,
    phase: str,
    entries: list[Entry],
    cap: int,
    config: PoolConfig,
    computed_at: datetime,
    summary: dict[str, Any],
    base_run_id: int | None = None,
) -> CandidatePoolRun:
    counts = _counts(entries)
    run = CandidatePoolRun(
        trading_date=day,
        version=CANDIDATE_POOL_VERSION,
        phase=phase,
        status="computed" if entries else "zero",
        cap=cap,
        union_count=len(entries),
        selected_count=sum(1 for e in entries if e.selected),
        source_counts_json=counts["sources"],
        summary_json=_clean({**counts, **summary}),
        config_json=config.as_json(),
        base_run_id=base_run_id,
        computed_at=computed_at,
    )
    run.unsaved_entries = entries  # type: ignore[attr-defined]
    return run


# --- the API ----------------------------------------------------------------


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat() + "Z"


def _run_meta(run: CandidatePoolRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "run_id": run.id,
        "phase": run.phase,
        "status": run.status,
        "computed_at": _iso(run.computed_at),
        "cap": run.cap,
        "union_count": run.union_count,
        "selected_count": run.selected_count,
        "source_counts": run.source_counts_json,
        "summary": run.summary_json,
        "base_run_id": run.base_run_id,
    }


def candidate_pool(
    db: Session, requested: date | None, *, include_rejected: bool = False
) -> dict[str, Any]:
    """The stored pool of ``requested`` (the latest evening when None).

    ``phases.morning`` is null until the morning run is written: the evening
    never stands in for it.  ``items`` are the selected ones, evening then
    morning; ``include_rejected`` adds the ones left out (``selected=false``).
    """

    day = requested
    if day is None:
        day = db.scalar(
            select(func.max(CandidatePoolRun.trading_date)).where(
                CandidatePoolRun.version == CANDIDATE_POOL_VERSION,
                CandidatePoolRun.phase == EVENING,
            )
        )
    runs = {phase: stored_run(db, day, phase) if day else None for phase in PHASES}
    meta = {
        "version": CANDIDATE_POOL_VERSION,
        "requested_date": requested.isoformat() if requested else None,
        "trading_date": day.isoformat() if day and runs[EVENING] else None,
        "not_a_signal": NOT_A_SIGNAL,
        "spec": "docs/spec/candidate_pool.md",
        "phases": {phase: _run_meta(run) for phase, run in runs.items()},
        "empty_reason": None if runs[EVENING] else "not_computed",
    }
    run_ids = [run.id for run in runs.values() if run is not None]
    items: list[dict[str, Any]] = []
    if run_ids:
        query = (
            select(CandidatePoolItem, Instrument)
            .join(Instrument, Instrument.id == CandidatePoolItem.instrument_id)
            .where(CandidatePoolItem.run_id.in_(run_ids))
        )
        if not include_rejected:
            query = query.where(CandidatePoolItem.selected.is_(True))
        phase_order = {EVENING: 0, MORNING: 1}
        rows = sorted(
            db.execute(query).all(),
            key=lambda row: (
                phase_order[row[0].phase],
                not row[0].selected,
                row[0].rank or 0,
                row[0].tier,
                -row[0].source_count,
                row[0].instrument_id,
            ),
        )
        for item, instrument in rows:
            items.append(
                {
                    "id": item.id,
                    "phase": item.phase,
                    "instrument": {
                        "id": instrument.id,
                        "exchange": instrument.exchange,
                        "symbol": instrument.symbol,
                        "name": instrument.name,
                        "industry": instrument.industry,
                    },
                    "rank": item.rank,
                    "tier": item.tier,
                    "selected": item.selected,
                    "reject_reason": item.reject_reason,
                    "source_count": item.source_count,
                    "sources": item.sources_json,
                    "themes": item.themes_json,
                    "features": item.features_json,
                }
            )
    return {"meta": meta, "items": items}
