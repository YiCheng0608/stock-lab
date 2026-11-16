"""主流族群前 20 (``mainstream_v1``, Issue #768): compute, store and read.

A second daily list beside the today list.  It looks for the groups that have
been strongest against TAIEX over a long window, then takes the strongest
stocks of those groups, with no cap per group.  It has no price levels (no
entry zone, stop or target) and changes nothing of the today list,
``candidate_score_v7`` or ``hot_group_v1``.

Definition (AC-1 decision #768 6892019991; the parameters are fixed below,
the way ``app.domain.HOT_GROUP_VERSION`` fixes hot_group's):

- **Universe**: the research tools' common one (``tools/research/
  evidence_lib.universe``; the product cannot import tools/research, so it is
  written again here): ``stock``／``ipo`` with a non-suspended bar on T whose
  mean volume over its last 20 bars is ≥ 1,000 lots, and at least W+1 bars.
- **Return**: close of T over the close W bars earlier on T's price basis,
  minus one (``tools/research/feature_evidence.momentum_120``'s arithmetic
  with W=240).  The basis is ``worker.pipeline._action_factor_by_bar``, the
  corporate action factor the group scores and the indicators use, so a
  return across an ex-dividend or split day is the holder's; the stored
  ``adj_close`` is the raw close and cannot be used.
- **Groups**: active ``official_industry`` and ``theme`` groups (not ``etf``,
  ``daily_hot_group``), members of ``role='member'`` valid on T.  A group is
  ranked when ≥ 5 of its members are in the universe with a return; its
  strength is the mean return of its top ⌈n/3⌉ (at least 3) of those, minus
  TAIEX's W-session return.  Strongest first (group id breaks ties); a group
  whose members are ≥ 80 % in the union of the groups already chosen is
  skipped, until G are chosen.
- **Stocks**: the chosen groups' members with a return, by return (ties by
  ``sha256("<T>:<instrument_id>")``), the first 20; every chosen group a stock
  belongs to is kept.

The daily writes it after the today list (``worker.mainstream``); a rerun of
the date replaces the run and its items.  ``today_list`` (the stock's rank and
entry type in the day's today list) is read at request time, not stored.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date, timezone
from typing import Any

from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from .candidate_runs import read_run as read_candidate_run
from .candidate_view import recent_closes, recent_sessions
from .clock import utcnow
from .market_change import adjacent_change
from .models import (
    DailyCandidate,
    GroupMembership,
    Instrument,
    MainstreamItem,
    MainstreamRun,
    MarketBar,
    Signal,
    ThemeGroup,
)
from .news import is_verified_theme

MAINSTREAM_VERSION = "mainstream_v1"
WINDOW = 240
GROUP_COUNT = 5
LIST_SIZE = 20
MIN_MEMBERS = 5
TOP_SHARE_DIVISOR = 3  # the top ⌈n/3⌉ members
MIN_TOP_MEMBERS = 3
DEDUP_OVERLAP = 0.8
LIQUIDITY_BARS = 20
MIN_AVERAGE_LOTS = 1000.0
SHARES_PER_LOT = 1000
GROUP_TYPES = ("official_industry", "theme")
INSTRUMENT_TYPES = ("stock", "ipo")
INDEX_SYMBOL = "TAIEX"
MAINSTREAM_CONFIG: dict[str, Any] = {
    "window": WINDOW,
    "group_count": GROUP_COUNT,
    "list_size": LIST_SIZE,
    "min_members": MIN_MEMBERS,
    "group_strength": "mean_of_top_third_minus_taiex",
    "min_top_members": MIN_TOP_MEMBERS,
    "dedup_overlap": DEDUP_OVERLAP,
    "liquidity_bars": LIQUIDITY_BARS,
    "min_average_lots": MIN_AVERAGE_LOTS,
    "group_types": list(GROUP_TYPES),
    "instrument_types": list(INSTRUMENT_TYPES),
    "index": INDEX_SYMBOL,
    "tie_break": "sha256(<T>:<instrument_id>)",
}


class MainstreamDataError(RuntimeError):
    """T's inputs cannot give the list (no TAIEX bar or history)."""


# --- the pure ranking -----------------------------------------------------


@dataclass(frozen=True)
class RankedGroup:
    group_id: str
    strength: float
    member_count: int
    top_count: int


@dataclass(frozen=True)
class RankedItem:
    instrument_id: int
    rank: int
    return_w: float
    excess_w: float
    group_ids: tuple[str, ...]


def top_count(member_count: int) -> int:
    """⌈n/3⌉ and at least 3 (never more than n)."""

    return min(
        member_count,
        max(MIN_TOP_MEMBERS, math.ceil(member_count / TOP_SHARE_DIVISOR)),
    )


def tie_key(day: date, instrument_id: int) -> str:
    return hashlib.sha256(f"{day.isoformat()}:{instrument_id}".encode()).hexdigest()


def rank_groups(
    returns: dict[int, float],
    members: dict[str, set[int]],
    index_return: float,
) -> tuple[list[RankedGroup], int]:
    """The chosen groups in rank order, and how many groups were ranked."""

    scored: list[tuple[float, str, list[int]]] = []
    for group_id, ids in members.items():
        valued = sorted((i for i in ids if i in returns), key=lambda i: -returns[i])
        if len(valued) < MIN_MEMBERS:
            continue
        top = valued[: top_count(len(valued))]
        strength = sum(returns[i] for i in top) / len(top) - index_return
        scored.append((strength, group_id, valued))
    scored.sort(key=lambda row: (-row[0], row[1]))
    chosen: list[RankedGroup] = []
    covered: set[int] = set()
    for strength, group_id, valued in scored:
        if len(chosen) == GROUP_COUNT:
            break
        ids = set(valued)
        if len(ids & covered) / len(ids) >= DEDUP_OVERLAP:
            continue
        chosen.append(
            RankedGroup(group_id, strength, len(valued), top_count(len(valued)))
        )
        covered |= ids
    return chosen, len(scored)


def rank_items(
    day: date,
    returns: dict[int, float],
    members: dict[str, set[int]],
    groups: list[RankedGroup],
    index_return: float,
) -> list[RankedItem]:
    owners: dict[int, list[str]] = {}
    for group in groups:
        for instrument_id in members[group.group_id]:
            if instrument_id in returns:
                owners.setdefault(instrument_id, []).append(group.group_id)
    ordered = sorted(owners, key=lambda i: (-returns[i], tie_key(day, i)))
    return [
        RankedItem(
            instrument_id=instrument_id,
            rank=rank,
            return_w=returns[instrument_id],
            excess_w=returns[instrument_id] - index_return,
            group_ids=tuple(owners[instrument_id]),
        )
        for rank, instrument_id in enumerate(ordered[:LIST_SIZE], start=1)
    ]


# --- reading the inputs ---------------------------------------------------


def _window_return(db: Session, instrument_id: int, bars: list[Any]) -> float | None:
    """Close of the last bar over the close ``WINDOW`` bars before, on its basis."""

    # Imported here: worker.pipeline imports app modules at load time.  Its
    # factor is the one the group scores and indicators use (#394).
    from worker.pipeline import _action_factor_by_bar

    factors = _action_factor_by_bar(db, instrument_id, bars)
    then, now = bars[-1 - WINDOW], bars[-1]
    then_factor, now_factor = factors[-1 - WINDOW], factors[-1]
    if not (then.close and now.close and then.close > 0 and now.close > 0):
        return None
    if not (then_factor > 0 and now_factor > 0):
        return None
    return now.close / (then.close * now_factor / then_factor) - 1.0


def universe_returns(db: Session, day: date) -> dict[int, float]:
    """The universe's W-session returns on ``day`` (see the module docstring)."""

    candidates = db.scalars(
        select(MarketBar.instrument_id)
        .join(Instrument, Instrument.id == MarketBar.instrument_id)
        .where(
            MarketBar.trading_date == day,
            Instrument.instrument_type.in_(INSTRUMENT_TYPES),
            MarketBar.is_suspended.is_(False),
        )
    ).all()
    returns: dict[int, float] = {}
    for instrument_id in candidates:
        bars = list(
            reversed(
                db.execute(
                    select(
                        MarketBar.trading_date,
                        MarketBar.close,
                        MarketBar.volume,
                        MarketBar.is_suspended,
                    )
                    .where(
                        MarketBar.instrument_id == instrument_id,
                        MarketBar.trading_date <= day,
                    )
                    .order_by(desc(MarketBar.trading_date))
                    .limit(WINDOW + 1)
                ).all()
            )
        )
        if len(bars) < max(WINDOW + 1, LIQUIDITY_BARS):
            continue
        volumes = [bar.volume or 0 for bar in bars[-LIQUIDITY_BARS:]]
        if sum(volumes) / LIQUIDITY_BARS / SHARES_PER_LOT < MIN_AVERAGE_LOTS:
            continue
        value = _window_return(db, instrument_id, bars)
        if value is not None and math.isfinite(value):
            returns[instrument_id] = value
    return returns


def index_window_return(db: Session, day: date) -> float:
    """TAIEX's close of ``day`` over its close ``WINDOW`` bars before, minus one."""

    rows = db.execute(
        select(MarketBar.trading_date, MarketBar.close)
        .join(Instrument, Instrument.id == MarketBar.instrument_id)
        .where(
            Instrument.instrument_type == "index",
            Instrument.exchange == "TWSE",
            Instrument.symbol == INDEX_SYMBOL,
            MarketBar.trading_date <= day,
        )
        .order_by(desc(MarketBar.trading_date))
        .limit(WINDOW + 1)
    ).all()
    if not rows or rows[0].trading_date != day:
        raise MainstreamDataError(f"no {INDEX_SYMBOL} bar on {day.isoformat()}")
    if len(rows) < WINDOW + 1 or not (rows[0].close > 0 and rows[-1].close > 0):
        raise MainstreamDataError(
            f"{INDEX_SYMBOL} has fewer than {WINDOW + 1} closes to {day.isoformat()}"
        )
    return rows[0].close / rows[-1].close - 1.0


def group_members(db: Session, day: date) -> dict[str, set[int]]:
    rows = db.execute(
        select(GroupMembership.group_id, GroupMembership.instrument_id)
        .join(ThemeGroup, ThemeGroup.id == GroupMembership.group_id)
        .where(
            ThemeGroup.active.is_(True),
            ThemeGroup.group_type.in_(GROUP_TYPES),
            GroupMembership.role == "member",
            GroupMembership.valid_from <= day,
            (GroupMembership.valid_to.is_(None)) | (GroupMembership.valid_to >= day),
        )
    ).all()
    members: dict[str, set[int]] = {}
    for group_id, instrument_id in rows:
        members.setdefault(group_id, set()).add(instrument_id)
    return members


# --- writing --------------------------------------------------------------


def compute_mainstream(db: Session, day: date) -> MainstreamRun:
    """Compute ``day``'s list and replace any stored run of the date and version."""

    index_return = index_window_return(db, day)
    returns = universe_returns(db, day)
    members = group_members(db, day)
    groups, ranked = rank_groups(returns, members, index_return)
    items = rank_items(day, returns, members, groups, index_return)
    types = dict(
        db.execute(
            select(ThemeGroup.id, ThemeGroup.group_type).where(
                ThemeGroup.id.in_([group.group_id for group in groups])
            )
        ).all()
    )

    old = db.scalars(
        select(MainstreamRun.id).where(
            MainstreamRun.trading_date == day,
            MainstreamRun.version == MAINSTREAM_VERSION,
        )
    ).all()
    if old:
        db.execute(
            delete(MainstreamItem).where(MainstreamItem.mainstream_run_id.in_(old))
        )
        db.execute(delete(MainstreamRun).where(MainstreamRun.id.in_(old)))
        db.flush()
    run = MainstreamRun(
        trading_date=day,
        version=MAINSTREAM_VERSION,
        status="computed" if groups else "zero",
        window=WINDOW,
        group_count=GROUP_COUNT,
        universe_count=len(returns),
        ranked_group_count=ranked,
        item_count=len(items),
        index_return=index_return,
        groups_json=[
            {
                "group_id": group.group_id,
                "group_type": types.get(group.group_id),
                "strength": group.strength,
                "rank": rank,
                "member_count": group.member_count,
                "top_count": group.top_count,
            }
            for rank, group in enumerate(groups, start=1)
        ],
        config_json=dict(MAINSTREAM_CONFIG),
        computed_at=utcnow(),
    )
    db.add(run)
    db.flush()
    db.add_all(
        MainstreamItem(
            mainstream_run_id=run.id,
            trading_date=day,
            instrument_id=item.instrument_id,
            version=MAINSTREAM_VERSION,
            rank=item.rank,
            return_w=item.return_w,
            excess_w=item.excess_w,
            group_ids_json=list(item.group_ids),
        )
        for item in items
    )
    db.commit()
    return run


# --- reading for /api/mainstream ------------------------------------------


def _group_name(group: ThemeGroup | None) -> str:
    # The product's rule (api._group_display_name): an unverified name is not shown.
    if group is not None and is_verified_theme(group):
        return group.display_name_zh.strip()
    return "族群待確認"


def _today_list(
    db: Session, day: date, instrument_ids: list[int]
) -> dict[int, dict[str, Any]]:
    run = read_candidate_run(db, day)
    if run is None or not instrument_ids:
        return {}
    rows = db.execute(
        select(DailyCandidate.instrument_id, DailyCandidate.rank, Signal.entry_type)
        .join(Signal, Signal.id == DailyCandidate.signal_id)
        .where(
            DailyCandidate.candidate_run_id == run.id,
            DailyCandidate.instrument_id.in_(instrument_ids),
        )
    ).all()
    return {
        row.instrument_id: {
            "rank": row.rank,
            "entry_type": row.entry_type,
            "score_version": run.score_version,
        }
        for row in rows
    }


def _empty(status: str, day: date | None) -> dict[str, Any]:
    return {
        "status": status,
        "trading_date": day.isoformat() if day else None,
        "version": MAINSTREAM_VERSION,
        "window": WINDOW,
        "group_count": GROUP_COUNT,
        "computed_at": None,
        "index_return": None,
        "groups": [],
        "items": [],
    }


def mainstream_list(db: Session, trading_date: date | None) -> dict[str, Any]:
    """The stored list of ``trading_date`` (the latest when None)."""

    query = select(MainstreamRun).where(MainstreamRun.version == MAINSTREAM_VERSION)
    if trading_date is not None:
        query = query.where(MainstreamRun.trading_date == trading_date)
    run = db.scalar(
        query.order_by(desc(MainstreamRun.trading_date), desc(MainstreamRun.id)).limit(
            1
        )
    )
    if run is None:
        return _empty("missing", trading_date)

    stored_groups = run.groups_json or []
    group_rows = {
        group.id: group
        for group in db.scalars(
            select(ThemeGroup).where(
                ThemeGroup.id.in_([group["group_id"] for group in stored_groups])
            )
        )
    }
    groups = [
        {
            "id": group["group_id"],
            "name": _group_name(group_rows.get(group["group_id"])),
            "group_type": group.get("group_type"),
            "strength": group["strength"],
            "rank": group["rank"],
            "member_count": group.get("member_count"),
            "top_count": group.get("top_count"),
        }
        for group in stored_groups
    ]
    by_id = {group["id"]: group for group in groups}

    rows = db.execute(
        select(
            MainstreamItem.instrument_id,
            MainstreamItem.rank,
            MainstreamItem.return_w,
            MainstreamItem.excess_w,
            MainstreamItem.group_ids_json,
        )
        .where(MainstreamItem.mainstream_run_id == run.id)
        .order_by(MainstreamItem.rank)
    ).all()
    ids = [row.instrument_id for row in rows]
    instruments = {
        row.id: row
        for row in db.execute(
            select(
                Instrument.id,
                Instrument.exchange,
                Instrument.symbol,
                Instrument.name,
                Instrument.instrument_type,
                Instrument.listing_date,
            ).where(Instrument.id.in_(ids))
        )
    }
    bars = {
        bar.instrument_id: bar
        for bar in db.scalars(
            select(MarketBar).where(
                MarketBar.instrument_id.in_(ids),
                MarketBar.trading_date == run.trading_date,
            )
        )
    }
    days = recent_sessions(db, run.trading_date)
    closes = recent_closes(db, ids, days)
    sessions: dict[date, list[date]] = {run.trading_date: days[-2:]}
    today = _today_list(db, run.trading_date, ids)
    items = []
    for row in rows:
        instrument = instruments[row.instrument_id]
        items.append(
            {
                "rank": row.rank,
                "instrument": {
                    "id": instrument.id,
                    "exchange": instrument.exchange,
                    "symbol": instrument.symbol,
                    "name": instrument.name,
                    "instrument_type": instrument.instrument_type,
                },
                "groups": [
                    {
                        key: by_id[group_id][key]
                        for key in ("id", "name", "group_type", "rank")
                    }
                    for group_id in row.group_ids_json or []
                    if group_id in by_id
                ],
                "return_w": row.return_w,
                "excess_w": row.excess_w,
                "market": adjacent_change(
                    db,
                    row.instrument_id,
                    run.trading_date,
                    bars.get(row.instrument_id),
                    sessions,
                    listing_date=instrument.listing_date,
                ),
                "recent_closes": closes[row.instrument_id],
                "today_list": today.get(row.instrument_id),
            }
        )
    return {
        "status": run.status,
        "trading_date": run.trading_date.isoformat(),
        "version": run.version,
        "window": run.window,
        "group_count": run.group_count,
        # computed_at is UTC-naive; the instant carries its offset.
        "computed_at": run.computed_at.replace(tzinfo=timezone.utc).isoformat()
        if run.computed_at
        else None,
        "index_return": run.index_return,
        "universe_count": run.universe_count,
        "ranked_group_count": run.ranked_group_count,
        "groups": groups,
        "items": items,
    }
