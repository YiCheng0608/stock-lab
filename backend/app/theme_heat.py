"""題材熱度 ``theme_heat_v1`` (Issue #1017): compute, store and read.

The spec is ``docs/spec/theme_heat.md``; every rule below is written there
once and only summarised here.  The heat ranks the theme-table themes
(``group_type='theme'``) of a day by six components, each a same-board
percentile (``worker.pipeline._percentile``, hot_group_v1's function) and a
weighted mean of those present.  It only decides which themes the AI looks at
first; it is not a buy or sell signal and nothing in the today list reads it.

The arithmetic is #1003 AC-2's trial (``heat.py``) except the price basis:
returns are on the corporate-action basis (``_action_factor_by_bar``, the one
the group scores and ``mainstream_v1`` use) because the stored ``adj_close`` is
the raw close.  The pure part (``score_board``) takes the board's members as an
argument, so a recompute and the trial can be run on the same members.
"""

from __future__ import annotations

import bisect
import math
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, desc, func, select
from sqlalchemy.orm import Session

from .clock import utcnow
from .models import (
    ChipSnapshot,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    NewsItem,
    ThemeGroup,
    ThemeHeatRun,
    ThemeHeatScore,
)
from .news import is_verified_theme
from .theme_table import THEME_GROUP_TYPE, load_theme_table, theme_group_id

THEME_HEAT_VERSION = "theme_heat_v1"
THEME_HEAT_REVISION = "1.0.0"
INDEX_SYMBOL = "TAIEX"
INSTRUMENT_TYPES = ("stock", "ipo")
# The components in display order and their weights when every one has a value;
# a missing one leaves the others' weights renormalised (no news: 0.25, 0.25,
# 0.25, 0.15, 0.10, #1003 AC-2 §3's left column).
COMPONENTS = (
    "excess_5d",
    "excess_20d",
    "turnover_ratio",
    "institutional_ratio",
    "breadth",
    "news",
)
WEIGHTS: dict[str, float] = {
    "excess_5d": 0.20,
    "excess_20d": 0.20,
    "turnover_ratio": 0.20,
    "institutional_ratio": 0.12,
    "breadth": 0.08,
    "news": 0.20,
}
MIN_ELIGIBLE_MEMBERS = 3
SHORT_WINDOW = 5
LONG_WINDOW = 20
TURNOVER_RECENT = 5
TURNOVER_PRIOR = 20
FLOW_SESSIONS = 5
# Sessions of history a day needs before it: the prior 20 turnover sessions
# end 5 sessions before T.
HISTORY_SESSIONS = TURNOVER_RECENT + TURNOVER_PRIOR - 1
NEWS_RECENT_SESSIONS = 3
NEWS_PRIOR_SESSIONS = 20
NEWS_MIN_ITEMS = 3
NEWS_PRIOR_SMOOTHING = 1
NEWS_SOURCE_KIND = "media"
NEWS_RUN_TYPE = "news"
NEWS_RUN_STATUSES = ("success", "partial")
TAIPEI = timezone(timedelta(hours=8))
NOT_A_SIGNAL = "不是買賣訊號"

THEME_HEAT_CONFIG: dict[str, Any] = {
    "version": THEME_HEAT_VERSION,
    "revision": THEME_HEAT_REVISION,
    "spec": "docs/spec/theme_heat.md",
    "weights": dict(WEIGHTS),
    "min_eligible_members": MIN_ELIGIBLE_MEMBERS,
    "return_windows": [SHORT_WINDOW, LONG_WINDOW],
    "turnover_windows": [TURNOVER_RECENT, TURNOVER_PRIOR],
    "flow_sessions": FLOW_SESSIONS,
    "news": {
        "recent_sessions": NEWS_RECENT_SESSIONS,
        "prior_sessions": NEWS_PRIOR_SESSIONS,
        "min_items": NEWS_MIN_ITEMS,
        "prior_smoothing": NEWS_PRIOR_SMOOTHING,
        "source_kind": NEWS_SOURCE_KIND,
        "run_statuses": list(NEWS_RUN_STATUSES),
    },
    "price_basis": "worker.pipeline._action_factor_by_bar",
    "percentile": "worker.pipeline._percentile",
}


class ThemeHeatDataError(RuntimeError):
    """T is not a TAIEX session."""


# --- the pure parts --------------------------------------------------------


@dataclass
class Inputs:
    """Series on the TAIEX sessions, by session index.

    ``price`` is the close on the corporate-action basis (any common basis:
    only ratios are read); ``amount`` the day's turnover in NTD; ``flow`` the
    three institutions' net buy times the close, in NTD.  An instrument with no
    bar in the loaded range has no ``price`` / ``amount`` entry.
    """

    sessions: list[date]
    index_close: list[float | None]
    price: dict[int, list[float | None]] = field(default_factory=dict)
    amount: dict[int, list[float | None]] = field(default_factory=dict)
    flow: dict[int, list[float | None]] = field(default_factory=dict)

    def position(self, day: date) -> int:
        index = bisect.bisect_left(self.sessions, day)
        if index == len(self.sessions) or self.sessions[index] != day:
            raise ThemeHeatDataError(f"no {INDEX_SYMBOL} bar on {day.isoformat()}")
        return index


@dataclass(frozen=True)
class GroupMetrics:
    excess_5d: float | None
    excess_20d: float | None
    turnover_ratio: float | None
    institutional_ratio: float | None
    breadth: float | None
    eligible_members: int
    flow_members: int


@dataclass(frozen=True)
class NewsCount:
    recent: int
    prior: int

    @property
    def raw(self) -> float:
        """Recent daily mean over the smoothed prior daily mean; 0 below the floor."""

        if self.recent < NEWS_MIN_ITEMS:
            return 0.0
        recent = self.recent / NEWS_RECENT_SESSIONS
        prior = (self.prior + NEWS_PRIOR_SMOOTHING) / NEWS_PRIOR_SESSIONS
        return recent / prior


@dataclass
class GroupHeat:
    group_id: str
    member_count: int
    eligible_members: int
    heat: float | None = None
    rank: int | None = None
    quality: str = "insufficient_data"
    raw: dict[str, float | None] = field(default_factory=dict)
    percentile: dict[str, float | None] = field(default_factory=dict)
    available_weight: float = 0.0
    news: NewsCount | None = None
    flow_members: int = 0


def _return(series: list[float | None] | None, i: int, n: int) -> float | None:
    if series is None or i - n < 0:
        return None
    now, then = series[i], series[i - n]
    if now is None or then is None or now <= 0 or then <= 0:
        return None
    return now / then - 1.0


def group_metrics(
    members: Sequence[int], i: int, inputs: Inputs
) -> GroupMetrics | None:
    """The five market components of one group on session ``i``.

    None when fewer than ``MIN_ELIGIBLE_MEMBERS`` members have a 20-session
    return (the group is not on the board that day).
    """

    index5 = _return(inputs.index_close, i, SHORT_WINDOW)
    index20 = _return(inputs.index_close, i, LONG_WINDOW)
    if index5 is None or index20 is None:
        return None
    r5 = [
        value
        for value in (_return(inputs.price.get(m), i, SHORT_WINDOW) for m in members)
        if value is not None
    ]
    r20 = [
        value
        for value in (_return(inputs.price.get(m), i, LONG_WINDOW) for m in members)
        if value is not None
    ]
    if len(r20) < MIN_ELIGIBLE_MEMBERS:
        return None
    recent_total = 0.0
    prior_total = 0.0
    flow_total = 0.0
    flow_members = 0
    has_history = i >= HISTORY_SESSIONS
    for member in members:
        amounts = inputs.amount.get(member)
        if amounts is None:
            continue
        recent = [x for x in amounts[i - TURNOVER_RECENT + 1 : i + 1] if x is not None]
        recent_total += sum(recent) / TURNOVER_RECENT
        if has_history:
            prior = [
                x
                for x in amounts[
                    i - TURNOVER_RECENT - TURNOVER_PRIOR + 1 : i - TURNOVER_RECENT + 1
                ]
                if x is not None
            ]
            prior_total += sum(prior) / TURNOVER_PRIOR
        flows = inputs.flow.get(member)
        if flows is not None and i >= FLOW_SESSIONS - 1:
            window = flows[i - FLOW_SESSIONS + 1 : i + 1]
            if all(x is not None for x in window):
                flow_total += sum(x for x in window if x is not None)
                flow_members += 1
    turnover_ratio = (
        recent_total / prior_total if has_history and prior_total > 0 else None
    )
    institutional_ratio = (
        flow_total / (recent_total * TURNOVER_RECENT)
        if recent_total > 0 and flow_members >= len(members) // 2
        else None
    )
    return GroupMetrics(
        excess_5d=(sum(r5) / len(r5) - index5) if r5 else None,
        excess_20d=sum(r20) / len(r20) - index20,
        turnover_ratio=turnover_ratio,
        institutional_ratio=institutional_ratio,
        breadth=sum(1 for value in r20 if value > index20) / len(r20),
        eligible_members=len(r20),
        flow_members=flow_members,
    )


def _percentile(value: float | None, peers: list[float | None]) -> float | None:
    # Imported here: worker.pipeline imports app modules at load time.  The
    # same function as hot_group_v1's components (#1003 AC-2 §3).
    from worker.pipeline import _percentile as hot_group_percentile

    return hot_group_percentile(value, peers)


def score_board(
    members: Mapping[str, Sequence[int]],
    i: int,
    inputs: Inputs,
    news: Mapping[str, NewsCount] | None,
) -> list[GroupHeat]:
    """Every group of the board on session ``i``, ranked ones first by rank.

    ``news`` is None when the day's news is not covered (no news run on T, or
    the window starts before the first one): the news component is then null
    for every group, never 0.  A group missing from a non-None ``news`` has 0
    items.
    """

    rows: dict[str, GroupHeat] = {}
    metrics: dict[str, GroupMetrics] = {}
    for group_id, ids in members.items():
        row = GroupHeat(group_id, member_count=len(ids), eligible_members=0)
        rows[group_id] = row
        value = group_metrics(ids, i, inputs)
        if value is not None:
            metrics[group_id] = value
            row.eligible_members = value.eligible_members
            row.flow_members = value.flow_members
    raw: dict[str, dict[str, float | None]] = {}
    for group_id, value in metrics.items():
        count = None if news is None else news.get(group_id, NewsCount(0, 0))
        rows[group_id].news = count
        raw[group_id] = {
            "excess_5d": value.excess_5d,
            "excess_20d": value.excess_20d,
            "turnover_ratio": value.turnover_ratio,
            "institutional_ratio": value.institutional_ratio,
            "breadth": value.breadth,
            "news": None if count is None else count.raw,
        }
    for component in COMPONENTS:
        peers = [raw[group_id][component] for group_id in metrics]
        for group_id in metrics:
            value = raw[group_id][component]
            percentile = _percentile(value, peers)
            # hot_group's catalyst rule: below the item floor is a fixed 0,
            # not the middle rank of the ties.
            if component == "news" and value == 0.0:
                percentile = 0.0
            rows[group_id].percentile[component] = percentile
    for group_id in metrics:
        row = rows[group_id]
        row.raw = raw[group_id]
        present = [c for c in COMPONENTS if row.percentile.get(c) is not None]
        weight = sum(WEIGHTS[c] for c in present)
        row.available_weight = weight
        if weight > 0:
            row.heat = (
                sum(WEIGHTS[c] * float(row.percentile[c] or 0.0) for c in present)
                / weight
            )
            row.quality = "complete" if len(present) == len(COMPONENTS) else "partial"
    ranked = sorted(
        (row for row in rows.values() if row.heat is not None),
        key=lambda row: (-float(row.heat or 0.0), row.group_id),
    )
    for rank, row in enumerate(ranked, start=1):
        row.rank = rank
    unranked = sorted(
        (row for row in rows.values() if row.heat is None), key=lambda r: r.group_id
    )
    return ranked + unranked


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def keyword_matches(text: str, keywords: Mapping[str, Sequence[str]]) -> set[str]:
    """The groups any of whose keywords is in ``text`` (NFKC, case-folded)."""

    folded = _fold(text)
    return {
        group_id
        for group_id, words in keywords.items()
        if any(word and _fold(word) in folded for word in words)
    }


@dataclass(frozen=True)
class NewsEntry:
    day: date
    keyword_groups: frozenset[str]
    instruments: frozenset[int]


def news_counts(
    entries: Iterable[NewsEntry],
    sessions: Sequence[date],
    i: int,
    members: Mapping[str, Sequence[int]],
) -> dict[str, NewsCount]:
    """Items per group in the recent and the prior window of session ``i``.

    An item dated D (Taipei) counts in the window of the first session on or
    after D: the recent window is (S[i-3], S[i]], the prior one
    (S[i-23], S[i-3]].  An item counts once per group, when a keyword of the
    group is in it or the AI reading of it names a member of the group on T.
    """

    recent_start = sessions[i - NEWS_RECENT_SESSIONS]
    prior_start = sessions[i - NEWS_RECENT_SESSIONS - NEWS_PRIOR_SESSIONS]
    end = sessions[i]
    member_sets = {group_id: set(ids) for group_id, ids in members.items()}
    recent: dict[str, int] = {group_id: 0 for group_id in members}
    prior: dict[str, int] = {group_id: 0 for group_id in members}
    for entry in entries:
        if not prior_start < entry.day <= end:
            continue
        target = recent if entry.day > recent_start else prior
        for group_id, ids in member_sets.items():
            if group_id in entry.keyword_groups or ids & entry.instruments:
                target[group_id] += 1
    return {
        group_id: NewsCount(recent[group_id], prior[group_id]) for group_id in members
    }


# --- reading the inputs ---------------------------------------------------


def index_sessions(db: Session, last_day: date) -> list[tuple[date, float]]:
    rows = db.execute(
        select(MarketBar.trading_date, MarketBar.close)
        .join(Instrument, Instrument.id == MarketBar.instrument_id)
        .where(
            Instrument.instrument_type == "index",
            Instrument.exchange == "TWSE",
            Instrument.symbol == INDEX_SYMBOL,
            MarketBar.trading_date <= last_day,
        )
        .order_by(MarketBar.trading_date)
    ).all()
    return [(row.trading_date, row.close) for row in rows]


@dataclass(frozen=True)
class Membership:
    group_id: str
    instrument_id: int
    valid_from: date
    valid_to: date | None


def theme_memberships(db: Session) -> list[Membership]:
    """Members of the active theme groups (stock / ipo), every period."""

    rows = db.execute(
        select(
            GroupMembership.group_id,
            GroupMembership.instrument_id,
            GroupMembership.valid_from,
            GroupMembership.valid_to,
        )
        .join(ThemeGroup, ThemeGroup.id == GroupMembership.group_id)
        .join(Instrument, Instrument.id == GroupMembership.instrument_id)
        .where(
            ThemeGroup.active.is_(True),
            ThemeGroup.group_type == THEME_GROUP_TYPE,
            GroupMembership.role == "member",
            Instrument.instrument_type.in_(INSTRUMENT_TYPES),
        )
    ).all()
    return [Membership(*row) for row in rows]


def members_on(memberships: Iterable[Membership], day: date) -> dict[str, list[int]]:
    """The board of ``day``: memberships valid on it (no backdating)."""

    members: dict[str, set[int]] = {}
    for row in memberships:
        if row.valid_from <= day and (row.valid_to is None or row.valid_to >= day):
            members.setdefault(row.group_id, set()).add(row.instrument_id)
    return {group_id: sorted(ids) for group_id, ids in sorted(members.items())}


def load_inputs(
    db: Session, instrument_ids: Iterable[int], first_day: date, last_day: date
) -> Inputs:
    """Bars and chips of ``instrument_ids`` for the sessions ``first_day``..``last_day``.

    The series start ``HISTORY_SESSIONS`` sessions before ``first_day``.
    """

    # Imported here: worker.pipeline imports app modules at load time.
    from worker.pipeline import _action_factor_by_bar

    index_rows = index_sessions(db, last_day)
    all_days = [day for day, _close in index_rows]
    first = bisect.bisect_left(all_days, first_day)
    start = max(0, first - HISTORY_SESSIONS)
    index_rows = index_rows[start:]
    sessions = [day for day, _close in index_rows]
    inputs = Inputs(
        sessions=sessions,
        index_close=[close for _day, close in index_rows],
    )
    if not sessions:
        return inputs
    position = {day: n for n, day in enumerate(sessions)}
    size = len(sessions)
    for instrument_id in sorted(set(instrument_ids)):
        bars = db.execute(
            select(
                MarketBar.trading_date,
                MarketBar.close,
                MarketBar.volume,
                MarketBar.turnover,
            )
            .where(
                MarketBar.instrument_id == instrument_id,
                MarketBar.trading_date >= sessions[0],
                MarketBar.trading_date <= sessions[-1],
            )
            .order_by(MarketBar.trading_date)
        ).all()
        if not bars:
            continue
        factors = _action_factor_by_bar(db, instrument_id, bars)
        price: list[float | None] = [None] * size
        amount: list[float | None] = [None] * size
        closes: dict[date, float] = {}
        for bar, factor in zip(bars, factors):
            n = position.get(bar.trading_date)
            if n is None:
                continue
            close = bar.close
            if close is not None and close > 0 and factor > 0:
                price[n] = close / factor
            if close is not None:
                closes[bar.trading_date] = close
            if bar.turnover:
                amount[n] = float(bar.turnover)
            elif close is not None and bar.volume is not None:
                amount[n] = float(close) * float(bar.volume)
        inputs.price[instrument_id] = price
        inputs.amount[instrument_id] = amount
        flow: list[float | None] = [None] * size
        for day, foreign, trust, dealer in db.execute(
            select(
                ChipSnapshot.trading_date,
                ChipSnapshot.foreign_buy,
                ChipSnapshot.trust_buy,
                ChipSnapshot.dealer_buy,
            ).where(
                ChipSnapshot.instrument_id == instrument_id,
                ChipSnapshot.trading_date >= sessions[0],
                ChipSnapshot.trading_date <= sessions[-1],
            )
        ).all():
            n = position.get(day)
            if n is None or foreign is None or day not in closes:
                continue
            flow[n] = ((foreign or 0.0) + (trust or 0.0) + (dealer or 0.0)) * closes[
                day
            ]
        inputs.flow[instrument_id] = flow
    return inputs


def _taipei_day(value: datetime) -> date:
    return value.replace(tzinfo=timezone.utc).astimezone(TAIPEI).date()


@dataclass
class NewsInputs:
    """The media items and news runs a range of days reads."""

    entries: list[NewsEntry]
    run_days: set[date]
    first_run_day: date | None
    through_id: int | None


def theme_keywords(table: Mapping[str, Any] | None = None) -> dict[str, list[str]]:
    """``keywords`` of the theme table by group id (they are not in the DB)."""

    data = table if table is not None else load_theme_table()
    return {
        theme_group_id(theme["id"]): [str(word) for word in theme.get("keywords") or []]
        for theme in data.get("themes", [])
    }


def load_news(
    db: Session,
    sessions: Sequence[date],
    first: int,
    last: int,
    keywords: Mapping[str, Sequence[str]],
) -> NewsInputs:
    """Media items dated in the news windows of sessions ``first``..``last``."""

    # Imported here: worker.news_llm imports app modules at load time.
    from worker.news_llm import PROMPT_VERSION, done_results

    runs = db.execute(
        select(IngestionRun.run_date).where(
            IngestionRun.run_type == NEWS_RUN_TYPE,
            IngestionRun.status.in_(NEWS_RUN_STATUSES),
        )
    ).all()
    run_days = {row.run_date for row in runs}
    first_run_day = min(run_days) if run_days else None
    lowest = first - NEWS_RECENT_SESSIONS - NEWS_PRIOR_SESSIONS
    if lowest < 0 or not run_days:
        return NewsInputs([], run_days, first_run_day, None)
    # A day's items, Taipei, can be stored up to 8 hours earlier in UTC.
    since = datetime.combine(sessions[lowest], datetime.min.time()) - timedelta(hours=8)
    until = datetime.combine(sessions[last] + timedelta(days=1), datetime.min.time())
    when = func.coalesce(NewsItem.published_at, NewsItem.collected_at)
    items = db.execute(
        select(NewsItem.id, NewsItem.title, NewsItem.summary, when.label("at")).where(
            NewsItem.status == "active",
            NewsItem.source_kind == NEWS_SOURCE_KIND,
            when >= since,
            when < until,
        )
    ).all()
    ai = done_results(db, [row.id for row in items], PROMPT_VERSION)
    codes: set[tuple[str, str]] = set()
    for result in ai.values():
        for candidate in result.ai_symbol_candidates_json or []:
            exchange, _, symbol = str(candidate.get("symbol", "")).partition(":")
            if exchange and symbol:
                codes.add((exchange, symbol))
    instrument_ids: dict[tuple[str, str], int] = {}
    if codes:
        for instrument_id, exchange, symbol in db.execute(
            select(Instrument.id, Instrument.exchange, Instrument.symbol).where(
                Instrument.symbol.in_({symbol for _exchange, symbol in codes})
            )
        ).all():
            if (exchange, symbol) in codes:
                instrument_ids[(exchange, symbol)] = instrument_id
    entries: list[NewsEntry] = []
    for row in items:
        named: set[int] = set()
        result = ai.get(row.id)
        if result is not None:
            for candidate in result.ai_symbol_candidates_json or []:
                exchange, _, symbol = str(candidate.get("symbol", "")).partition(":")
                found = instrument_ids.get((exchange, symbol))
                if found is not None:
                    named.add(found)
        entries.append(
            NewsEntry(
                day=_taipei_day(row.at),
                keyword_groups=frozenset(
                    keyword_matches(f"{row.title} {row.summary or ''}", keywords)
                ),
                instruments=frozenset(named),
            )
        )
    through = max((row.id for row in items), default=None)
    return NewsInputs(entries, run_days, first_run_day, through)


def news_status(news: NewsInputs, sessions: Sequence[date], i: int) -> str:
    """``available``, ``no_news_run`` (none on T) or ``history_short``."""

    if sessions[i] not in news.run_days:
        return "no_news_run"
    lowest = i - NEWS_RECENT_SESSIONS - NEWS_PRIOR_SESSIONS
    if lowest < 0 or news.first_run_day is None:
        return "history_short"
    # The prior window's first calendar day must be on or after the first run.
    if news.first_run_day > sessions[lowest] + timedelta(days=1):
        return "history_short"
    return "available"


# --- writing --------------------------------------------------------------


def _round(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, 6)


def _write_day(
    db: Session,
    day: date,
    rows: list[GroupHeat],
    status_of_news: str,
    news_through_id: int | None,
) -> ThemeHeatRun:
    old = db.scalars(
        select(ThemeHeatRun.id).where(
            ThemeHeatRun.trading_date == day,
            ThemeHeatRun.version == THEME_HEAT_VERSION,
        )
    ).all()
    if old:
        db.execute(delete(ThemeHeatScore).where(ThemeHeatScore.run_id.in_(old)))
        db.execute(delete(ThemeHeatRun).where(ThemeHeatRun.id.in_(old)))
        db.flush()
    ranked = sum(1 for row in rows if row.rank is not None)
    run = ThemeHeatRun(
        trading_date=day,
        version=THEME_HEAT_VERSION,
        status="computed" if ranked else "zero",
        theme_count=len(rows),
        ranked_count=ranked,
        news_status=status_of_news,
        news_through_id=news_through_id,
        config_json=dict(THEME_HEAT_CONFIG),
        computed_at=utcnow(),
    )
    db.add(run)
    db.flush()
    db.add_all(
        ThemeHeatScore(
            run_id=run.id,
            trading_date=day,
            group_id=row.group_id,
            version=THEME_HEAT_VERSION,
            rank=row.rank,
            heat=_round(row.heat),
            quality=row.quality,
            member_count=row.member_count,
            eligible_members=row.eligible_members,
            available_weight=_round(row.available_weight),
            components_json={
                component: {
                    "raw": _round(row.raw.get(component)),
                    "percentile": _round(row.percentile.get(component)),
                }
                for component in COMPONENTS
            },
            details_json={
                "flow_members": row.flow_members,
                "news_recent": None if row.news is None else row.news.recent,
                "news_prior": None if row.news is None else row.news.prior,
            },
        )
        for row in rows
    )
    db.commit()
    return run


def compute_range(
    db: Session,
    first_day: date,
    last_day: date,
    *,
    keywords: Mapping[str, Sequence[str]] | None = None,
) -> list[ThemeHeatRun]:
    """Compute and store every TAIEX session from ``first_day`` to ``last_day``.

    Each day reads the members valid on it; a day without any is stored as a
    ``zero`` run.  A rerun of a day replaces its run and scores.
    """

    memberships = theme_memberships(db)
    inputs = load_inputs(
        db, (row.instrument_id for row in memberships), first_day, last_day
    )
    days = [day for day in inputs.sessions if first_day <= day <= last_day]
    if not days:
        raise ThemeHeatDataError(
            f"no {INDEX_SYMBOL} bar from {first_day.isoformat()} "
            f"to {last_day.isoformat()}"
        )
    first = inputs.position(days[0])
    last = inputs.position(days[-1])
    news = load_news(
        db,
        inputs.sessions,
        first,
        last,
        theme_keywords() if keywords is None else keywords,
    )
    runs: list[ThemeHeatRun] = []
    for i in range(first, last + 1):
        day = inputs.sessions[i]
        members = members_on(memberships, day)
        status_of_news = news_status(news, inputs.sessions, i)
        counts = (
            news_counts(news.entries, inputs.sessions, i, members)
            if status_of_news == "available"
            else None
        )
        rows = score_board(members, i, inputs, counts)
        runs.append(
            _write_day(
                db,
                day,
                rows,
                status_of_news,
                news.through_id if counts is not None else None,
            )
        )
    return runs


def compute_theme_heat(
    db: Session, day: date, *, keywords: Mapping[str, Sequence[str]] | None = None
) -> ThemeHeatRun:
    """Compute and store ``day``; raises when it is not a TAIEX session."""

    runs = compute_range(db, day, day, keywords=keywords)
    if runs[0].trading_date != day:
        raise ThemeHeatDataError(f"no {INDEX_SYMBOL} bar on {day.isoformat()}")
    return runs[0]


# --- reading for /api/theme-heat ------------------------------------------


def _group_name(group: ThemeGroup | None) -> str:
    if group is not None and is_verified_theme(group):
        return (group.display_name_zh or "").strip()
    return "族群待確認"


def _empty(requested: date | None, reason: str) -> dict[str, Any]:
    return {
        "meta": {
            "version": THEME_HEAT_VERSION,
            "requested_date": requested.isoformat() if requested else None,
            "trading_date": None,
            "computed_at": None,
            "news_status": None,
            "weights": dict(WEIGHTS),
            "theme_count": 0,
            "ranked_count": 0,
            "not_a_signal": NOT_A_SIGNAL,
            "empty_reason": reason,
        },
        "items": [],
    }


def theme_heat(db: Session, requested: date | None) -> dict[str, Any]:
    """The stored heat of ``requested`` (the latest run on or before it)."""

    query = select(ThemeHeatRun).where(ThemeHeatRun.version == THEME_HEAT_VERSION)
    if requested is not None:
        query = query.where(ThemeHeatRun.trading_date <= requested)
    run = db.scalar(query.order_by(desc(ThemeHeatRun.trading_date)).limit(1))
    if run is None:
        return _empty(requested, "not_computed")
    scores = db.scalars(
        select(ThemeHeatScore).where(ThemeHeatScore.run_id == run.id)
    ).all()
    groups = {
        group.id: group
        for group in db.scalars(
            select(ThemeGroup).where(
                ThemeGroup.id.in_([score.group_id for score in scores])
            )
        ).all()
    }
    ordered = sorted(
        scores,
        key=lambda score: (score.rank is None, score.rank or 0, score.group_id),
    )
    items = []
    for score in ordered:
        group = groups.get(score.group_id)
        # Only active groups are shown (as the boards do).
        if group is None or not group.active:
            continue
        details = score.details_json or {}
        items.append(
            {
                "theme_id": score.group_id,
                "display_name": _group_name(group),
                "rank": score.rank,
                "heat": score.heat,
                "quality": score.quality,
                "member_count": score.member_count,
                "eligible_members": score.eligible_members,
                "available_weight": score.available_weight,
                "components": {
                    component: (score.components_json or {})
                    .get(component, {})
                    .get("percentile")
                    for component in COMPONENTS
                },
                "raw": {
                    component: (score.components_json or {})
                    .get(component, {})
                    .get("raw")
                    for component in COMPONENTS
                },
                "news_items": {
                    "recent": details.get("news_recent"),
                    "prior": details.get("news_prior"),
                },
            }
        )
    return {
        "meta": {
            "version": THEME_HEAT_VERSION,
            "requested_date": requested.isoformat() if requested else None,
            "trading_date": run.trading_date.isoformat(),
            "computed_at": run.computed_at.replace(tzinfo=timezone.utc).isoformat(),
            "news_status": run.news_status,
            "weights": dict(WEIGHTS),
            "theme_count": len(items),
            "ranked_count": sum(1 for item in items if item["rank"] is not None),
            "not_a_signal": NOT_A_SIGNAL,
            "empty_reason": None if items else "no_theme",
        },
        "items": items,
    }
