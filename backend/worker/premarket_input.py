"""The input snapshot of the pre-market AI reading (Issue #1041, docs/spec/premarket_ai.md).

One JSON object per trading day D, read from the database with nothing after
the cutoff, D 08:15 Taipei (``cutoff``):

- **News**: published (``display_time``) from the list date's 13:30 Taipei to
  the cutoff and collected by it, ``status=active``, time not in conflict, one
  story once (canonical key, dedupe cluster or content hash).  The AI reading
  of an item is the done ``news_v4`` result (or the version standing for it)
  written by the cutoff; a later one is not seen (``not_judged_by_cutoff``).
  The snapshot reads these itself, not the candidate pool's news source
  (#1048 review 7190403114: news collected before the evening pool but judged
  after it are in neither pool round).
- **Daily data** (prices, volume, institutional and margin, TAIEX, the TX
  regular session): by data date, through the list date, the session before
  D, all stored the evening before.  The four US indexes of the US session
  before D are read as collected by the cutoff (the 08:30 and 09:30 us runs
  are after it).  The TX night
  session TAIFEX files under D (#1040), which closed at 05:00 and is read when
  collected by the time the snapshot is made (the 08:15 ``night`` job writes
  it a few seconds after the cutoff).
- **Candidates**: the pool (``select_pool``: candidate_pool_v1's evening and
  morning rounds, the evening alone, or the stand-in pool when the list date has
  no evening round), each stock with its pool sources, the
  list date's prices and volume, five days of institutional and margin
  changes, its industries and themes and its overnight news.  Only a stock on
  the today list (``app.candidate_runs.read_run`` of the list date) carries
  ``strategy_levels``, the rule levels the today page shows (#1002 decision
  3a); no other stock has the key at all.  No ``extra_universe``: the AI only
  reads the pool (#1 decision 7187528140).

Everything is stored (``premarket_ai_readings.input_json``) as it was sent.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable

from sqlalchemy import desc, literal_column, or_, select
from sqlalchemy.orm import Session

from app.candidate_pool import CANDIDATE_POOL_VERSION, stored_run
from app.candidate_pool import EVENING as POOL_EVENING
from app.candidate_pool import MORNING as POOL_MORNING
from app.candidate_runs import read_run
from app.candidate_view import _levels
from app.domain import US_INDEX_EXCHANGE, US_INDEXES
from app.market_overview import (
    _closed_dates,
    _freshness,
    _quality_rows,
    expected_us_session,
)
from app.models import (
    CandidatePoolItem,
    CandidatePoolRun,
    ChipSnapshot,
    DailyCandidate,
    FuturesNightBar,
    GroupMembership,
    Instrument,
    MarketBar,
    NewsItem,
    NewsLlmResult,
    Signal,
    ThemeGroup,
)
from app.strategy_lists import stored as stored_list
from app.strategy_lists import strategy as list_strategy

from .news_llm import PROMPT_VERSION as NEWS_PROMPT_VERSION
from .news_llm import input_hash, read_versions

TAIPEI_OFFSET = timedelta(hours=8)
CUTOFF = (8, 15)
# The overnight news window opens at the list date's close.
WINDOW_OPEN = (13, 30)
POOL_CAP = 60
NEWS_TOP = 12
NEWS_TOP_MIN = 2
MARKET_NEWS_LIMIT = 60
STOCK_NEWS_LIMIT = 5
TITLE_CHARS = 100
BARS = 241
CHIP_DAYS = 5
SHARES_PER_LOT = 1000
INTERIM = "interim"
MORNING = "morning"
EVENING = "evening"
STOCK_TYPES = ("stock", "ipo")
GROUP_TYPES = ("official_industry", "theme")
TAIEX_SYMBOL = "TAIEX"
TX_EXCHANGE = "TAIFEX"
TX_SYMBOL = "TX"
SIGNAL_STATUSES = ("conditional", "active")
ANALYSIS_PREFIX = "analysis-"


def taipei_instant(day: date, hour: int, minute: int) -> datetime:
    """The UTC-naive instant of DAY hour:minute Taipei (stored instants are UTC-naive)."""

    return datetime.combine(day, time(hour, minute)) - TAIPEI_OFFSET


def cutoff(session_date: date) -> datetime:
    return taipei_instant(session_date, *CUTOFF)


def _taipei_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value + TAIPEI_OFFSET).strftime("%Y-%m-%d %H:%M")


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


@dataclass
class PoolStock:
    instrument: Instrument
    sources: list[Any] = field(default_factory=list)
    pool_item_id: int | None = None


@dataclass
class StockMeta:
    """What a per-stock row keeps of the input (``premarket_ai_stocks``)."""

    instrument_id: int
    symbol: str
    position: int
    on_today_list: bool
    daily_candidate_id: int | None
    pool_item_id: int | None
    pool_sources: list[Any]
    levels: dict[str, Any] | None


@dataclass
class Snapshot:
    session_date: date
    list_date: date
    cutoff_at: datetime
    pool_phase: str
    payload: dict[str, Any]
    stocks: list[StockMeta]
    news_ids: set[int]

    @property
    def hash(self) -> str:
        return input_hash(self.payload)


# --- news -------------------------------------------------------------------


@dataclass
class _News:
    item: NewsItem
    result: NewsLlmResult | None


def overnight_news(db: Session, list_date: date, until: datetime) -> list[_News]:
    """The overnight items, newest first, each story once (see the module docstring)."""

    opened = taipei_instant(list_date, *WINDOW_OPEN)
    rows = db.scalars(
        select(NewsItem)
        .where(
            # As app.preopen_news: keep SQLite off ix_news_items_status.
            literal_column("+news_items.status") == "active",
            or_(
                NewsItem.time_consistency.is_(None),
                NewsItem.time_consistency != "conflict",
            ),
            NewsItem.time_precision == "datetime",
            NewsItem.display_time > opened,
            NewsItem.display_time <= until,
            NewsItem.collected_at <= until,
        )
        .order_by(desc(NewsItem.display_time), desc(NewsItem.id))
    ).all()
    seen: set[str] = set()
    items: list[NewsItem] = []
    for item in rows:
        keys = {
            value
            for value in (item.canonical_key, item.dedupe_cluster_id, item.content_hash)
            if value
        }
        if keys & seen:
            continue
        seen |= keys
        items.append(item)
    versions = read_versions(NEWS_PROMPT_VERSION)
    rank = {name: position for position, name in enumerate(versions)}
    results: dict[int, NewsLlmResult] = {}
    ids = [item.id for item in items]
    for start in range(0, len(ids), 900):
        for row in db.scalars(
            select(NewsLlmResult).where(
                NewsLlmResult.news_item_id.in_(ids[start : start + 900]),
                NewsLlmResult.prompt_version.in_(versions),
                NewsLlmResult.llm_status == "done",
                NewsLlmResult.llm_run_at <= until,
            )
        ):
            kept = results.get(row.news_item_id)
            if kept is None or rank[row.prompt_version] < rank[kept.prompt_version]:
                results[row.news_item_id] = row
    return [_News(item, results.get(item.id)) for item in items]


def _direction(result: NewsLlmResult) -> str:
    if result.ai_unsupported or result.ai_impact_direction not in (
        "positive",
        "negative",
        "mixed",
    ):
        return "unknown"
    return result.ai_impact_direction


def news_object(entry: _News) -> dict[str, Any]:
    item, result = entry.item, entry.result
    out: dict[str, Any] = {
        "id": item.id,
        "time": _taipei_text(item.display_time),
        "source": item.source_name,
        "title": item.title[:TITLE_CHARS],
    }
    if result is not None:
        out["ai_summary"] = result.ai_summary
        out["ai_direction"] = _direction(result)
        out["ai_scope"] = result.ai_impact_scope
    else:
        out["ai"] = "not_judged_by_cutoff"
    if item.theme_ids_json:
        out["theme_ids"] = list(item.theme_ids_json)
    return out


def news_stats(news: list[_News]) -> dict[str, int]:
    stats: dict[str, int] = defaultdict(int)
    for entry in news:
        stats["total"] += 1
        if entry.result is None:
            stats["not_judged_by_cutoff"] += 1
            continue
        stats["ai_done"] += 1
        stats[f"ai_scope_{entry.result.ai_impact_scope}"] += 1
        stats[f"ai_direction_{_direction(entry.result)}"] += 1
    return dict(stats)


def market_news(news: list[_News]) -> list[_News]:
    """AI judged market or theme and gave a direction: the newest MARKET_NEWS_LIMIT."""

    picked = [
        entry
        for entry in news
        if entry.result is not None
        and entry.result.ai_impact_scope in ("market", "theme")
        and _direction(entry.result) != "unknown"
    ]
    return picked[:MARKET_NEWS_LIMIT]


def _tokens(instrument: Instrument) -> tuple[str, str]:
    return instrument.symbol, f"{instrument.exchange}:{instrument.symbol}"


def news_by_stock(db: Session, news: list[_News]) -> dict[int, list[_News]]:
    """Per instrument id, its items by the rule relation (``symbols_json``), newest first."""

    tokens = {str(token) for entry in news for token in entry.item.symbols_json or []}
    if not tokens:
        return {}
    bare = {token.split(":")[-1] for token in tokens}
    by_token: dict[str, list[int]] = defaultdict(list)
    for instrument in db.scalars(
        select(Instrument).where(
            Instrument.symbol.in_(sorted(bare)),
            Instrument.instrument_type.in_(STOCK_TYPES),
        )
    ):
        for token in _tokens(instrument):
            by_token[token].append(instrument.id)
    out: dict[int, list[_News]] = defaultdict(list)
    for entry in news:
        ids = {
            instrument_id
            for token in entry.item.symbols_json or []
            for instrument_id in by_token.get(str(token), ())
        }
        for instrument_id in ids:
            out[instrument_id].append(entry)
    return dict(out)


# --- the pool ---------------------------------------------------------------


def _add(pool: dict[int, PoolStock], instrument: Instrument, source: str) -> None:
    stock = pool.setdefault(instrument.id, PoolStock(instrument))
    if source not in stock.sources:
        stock.sources.append(source)


def interim_pool(
    db: Session,
    list_date: date,
    today_list: list[DailyCandidate],
    stock_news: dict[int, list[_News]],
) -> list[PoolStock]:
    """The stand-in pool (``pool_phase=interim``): the list date has no
    candidate_pool_v1 evening round.

    In this order, each stock with all its sources: the today list, the list
    date's rule signals (conditional or active), its H2 list, the watchlist,
    then the NEWS_TOP stocks with the most overnight news (at least
    NEWS_TOP_MIN); the first POOL_CAP stocks.
    """

    pool: dict[int, PoolStock] = {}
    instruments = {
        row.id: row
        for row in db.scalars(
            select(Instrument).where(
                Instrument.id.in_([row.instrument_id for row in today_list])
            )
        )
    }
    for row in today_list:
        _add(pool, instruments[row.instrument_id], f"today_list#{row.rank}")
    for signal, instrument in db.execute(
        select(Signal, Instrument)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .where(
            Signal.signal_date == list_date,
            Signal.signal_key.like(f"{ANALYSIS_PREFIX}%"),
            Signal.status.in_(SIGNAL_STATUSES),
            Instrument.instrument_type.in_(STOCK_TYPES),
        )
        .order_by(Signal.id)
    ):
        _add(pool, instrument, f"rule_signal:{signal.entry_type}:{signal.status}")
    entry = list_strategy("h2")
    _run, items = stored_list(db, entry, list_date)
    if items:
        listed = {
            row.id: row
            for row in db.scalars(
                select(Instrument).where(
                    Instrument.id.in_([item.instrument_id for item in items])
                )
            )
        }
        for item in items:
            _add(pool, listed[item.instrument_id], f"h2#{item.rank}")
    for instrument in db.scalars(
        select(Instrument)
        .where(Instrument.is_watchlisted.is_(True))
        .order_by(Instrument.exchange, Instrument.symbol)
    ):
        _add(pool, instrument, "watchlist")
    busy = sorted(
        (
            (len(entries), instrument_id)
            for instrument_id, entries in stock_news.items()
            if len(entries) >= NEWS_TOP_MIN
        ),
        key=lambda pair: (-pair[0], pair[1]),
    )[:NEWS_TOP]
    if busy:
        named = {
            row.id: row
            for row in db.scalars(
                select(Instrument).where(Instrument.id.in_([i for _n, i in busy]))
            )
        }
        for count, instrument_id in busy:
            _add(pool, named[instrument_id], f"overnight_news:{count}")
    return list(pool.values())[:POOL_CAP]


def _pool_run(db: Session, list_date: date, phase: str, assembled_at: datetime):
    """The list date's candidate_pool_v1 run of PHASE, when computed by ASSEMBLED_AT."""

    run = stored_run(db, list_date, phase)
    if run is None or run.computed_at is None or run.computed_at > assembled_at:
        return None
    return run


def candidate_pool_stocks(db: Session, runs: list[CandidatePoolRun]) -> list[PoolStock]:
    """The selected stocks of RUNS (evening, then morning), each in rank order."""

    stocks: list[PoolStock] = []
    for run in runs:
        for item, instrument in db.execute(
            select(CandidatePoolItem, Instrument)
            .join(Instrument, Instrument.id == CandidatePoolItem.instrument_id)
            .where(
                CandidatePoolItem.run_id == run.id,
                CandidatePoolItem.selected.is_(True),
            )
            .order_by(CandidatePoolItem.rank, CandidatePoolItem.id)
        ):
            stocks.append(
                PoolStock(
                    instrument,
                    [
                        {
                            "source": entry.get("source"),
                            "value": entry.get("value"),
                            "data_date": entry.get("data_date"),
                        }
                        for entry in item.sources_json or []
                    ],
                    pool_item_id=item.id,
                )
            )
    return stocks


def select_pool(
    db: Session,
    list_date: date,
    today_list: list[DailyCandidate],
    stock_news: dict[int, list[_News]],
    assembled_at: datetime,
) -> tuple[str, list[PoolStock], dict[str, Any]]:
    """(pool_phase, stocks, pool summary) for the input (#1041 decisions 7188153160,
    7192367021).

    candidate_pool_v1 of the list date: its evening and morning rounds
    (``morning``) when the morning round is written by the time the snapshot is
    made, else the evening round alone (``evening``; 08:20's preopen may still
    be waiting for the news run). Without an evening round (before #1020 was
    deployed, a daily that failed) the stand-in pool (``interim``) with
    ``fallback=no_candidate_pool_evening``, so that 08:21 still reads.
    """

    evening = _pool_run(db, list_date, POOL_EVENING, assembled_at)
    if evening is None:
        stocks = interim_pool(db, list_date, today_list, stock_news)
        return (
            INTERIM,
            stocks,
            {"cap": POOL_CAP, "fallback": "no_candidate_pool_evening"},
        )
    morning = _pool_run(db, list_date, POOL_MORNING, assembled_at)
    runs = [evening] + ([morning] if morning is not None else [])
    summary = {
        "version": CANDIDATE_POOL_VERSION,
        "evening_run_id": evening.id,
        "morning_run_id": morning.id if morning is not None else None,
        "cap": sum(run.cap for run in runs),
    }
    return (
        MORNING if morning is not None else EVENING,
        candidate_pool_stocks(db, runs),
        summary,
    )


# --- per stock --------------------------------------------------------------


def _bars(db: Session, instrument_id: int, list_date: date):
    return db.scalars(
        select(MarketBar)
        .where(
            MarketBar.instrument_id == instrument_id,
            MarketBar.trading_date <= list_date,
        )
        .order_by(desc(MarketBar.trading_date))
        .limit(BARS)
    ).all()


def _ratio(now: float | None, then: float | None) -> float | None:
    if now is None or not then:
        return None
    return round(now / then - 1, 4)


def price_object(bars: list[MarketBar], list_date: date) -> dict[str, Any]:
    """The list date's bar and moves on raw closes (``basis=raw``)."""

    if not bars or bars[0].trading_date != list_date:
        return {"status": "missing"}
    latest = bars[0]
    closes = [bar.close for bar in bars]
    volumes = [bar.volume for bar in bars[1:21] if bar.volume]
    highs = [bar.high if bar.high is not None else bar.close for bar in bars]
    return {
        "date": latest.trading_date.isoformat(),
        "open": latest.open,
        "high": latest.high,
        "low": latest.low,
        "close": latest.close,
        "change_pct_1d": _ratio(closes[0], closes[1]) if len(closes) > 1 else None,
        "ret_5d": _ratio(closes[0], closes[5]) if len(closes) > 5 else None,
        "ret_20d": _ratio(closes[0], closes[20]) if len(closes) > 20 else None,
        "volume_lots": round((latest.volume or 0) / SHARES_PER_LOT),
        "volume_ratio_20d": round(latest.volume / (sum(volumes) / len(volumes)), 2)
        if volumes and latest.volume
        else None,
        "high_240_gap": _ratio(closes[0], max(highs)),
        "basis": "raw",
        "source": latest.source,
    }


def chips_object(db: Session, instrument_id: int, list_date: date) -> dict[str, Any]:
    rows = db.scalars(
        select(ChipSnapshot)
        .where(
            ChipSnapshot.instrument_id == instrument_id,
            ChipSnapshot.trading_date <= list_date,
        )
        .order_by(desc(ChipSnapshot.trading_date))
        .limit(CHIP_DAYS)
    ).all()
    if not rows:
        return {"status": "missing"}

    def lots(name: str) -> int | None:
        values = [getattr(row, name) for row in rows if getattr(row, name) is not None]
        return round(sum(values) / SHARES_PER_LOT) if values else None

    first = rows[0].foreign_buy
    margins = [row.margin_change for row in rows if row.margin_change is not None]
    return {
        "as_of": rows[0].trading_date.isoformat(),
        "days": len(rows),
        "foreign_net_lots_1d": round(first / SHARES_PER_LOT)
        if first is not None
        else None,
        "foreign_net_lots_5d": lots("foreign_buy"),
        "trust_net_lots_5d": lots("trust_buy"),
        "dealer_net_lots_5d": lots("dealer_buy"),
        "margin_change_5d": sum(margins) if margins else None,
        "source": rows[0].source,
    }


def groups_of(
    db: Session, instrument_ids: Iterable[int], list_date: date
) -> dict[int, list[dict[str, str]]]:
    out: dict[int, list[dict[str, str]]] = defaultdict(list)
    ids = list(instrument_ids)
    if not ids:
        return {}
    for membership, group in db.execute(
        select(GroupMembership, ThemeGroup)
        .join(ThemeGroup, ThemeGroup.id == GroupMembership.group_id)
        .where(
            GroupMembership.instrument_id.in_(ids),
            GroupMembership.role == "member",
            GroupMembership.valid_from <= list_date,
            or_(
                GroupMembership.valid_to.is_(None),
                GroupMembership.valid_to >= list_date,
            ),
            ThemeGroup.active.is_(True),
            ThemeGroup.group_type.in_(GROUP_TYPES),
        )
        .order_by(GroupMembership.instrument_id, ThemeGroup.id)
    ):
        entry = {
            "group_id": group.id,
            "name": group.display_name_zh or group.name,
            "type": group.group_type,
        }
        if entry not in out[membership.instrument_id]:
            out[membership.instrument_id].append(entry)
    return dict(out)


def rule_levels(db: Session, row: DailyCandidate) -> dict[str, Any] | None:
    """The today page's rule levels of a today-list row (``candidate_view._levels``)."""

    signal = db.get(Signal, row.signal_id)
    if signal is None:
        return None
    return {"rank": row.rank, "strategy": row.strategy, **_levels(signal, row.strategy)}


# --- indexes ----------------------------------------------------------------


def _instrument(
    db: Session, exchange: str | None, symbol: str, kind: str | None = None
):
    query = select(Instrument).where(Instrument.symbol == symbol)
    if exchange is not None:
        query = query.where(Instrument.exchange == exchange)
    if kind is not None:
        query = query.where(Instrument.instrument_type == kind)
    return db.scalar(query.order_by(Instrument.id).limit(1))


def _two_bars(
    db: Session,
    instrument: Instrument | None,
    through: date,
    until: datetime | None = None,
):
    """The two newest bars through THROUGH; collected by UNTIL when given (US)."""

    if instrument is None:
        return []
    conditions = [
        MarketBar.instrument_id == instrument.id,
        MarketBar.trading_date <= through,
    ]
    if until is not None:
        conditions.append(MarketBar.collected_at <= until)
    return db.scalars(
        select(MarketBar)
        .where(*conditions)
        .order_by(desc(MarketBar.trading_date))
        .limit(2)
    ).all()


def _bar_object(bars, expected: date) -> dict[str, Any]:
    if not bars:
        return {"status": "missing", "expected_date": expected.isoformat()}
    latest = bars[0]
    previous = bars[1] if len(bars) > 1 else None
    return {
        "date": latest.trading_date.isoformat(),
        "close": latest.close,
        "change_pct": _ratio(latest.close, previous.close) if previous else None,
        "freshness": "latest" if latest.trading_date == expected else "stale",
        "source": latest.source,
        "collected_at": _taipei_text(latest.collected_at),
    }


def taiex_object(db: Session, list_date: date) -> dict[str, Any]:
    instrument = _instrument(db, None, TAIEX_SYMBOL, "index")
    return _bar_object(_two_bars(db, instrument, list_date), list_date)


def us_object(db: Session, session_date: date, until: datetime) -> dict[str, Any]:
    expected = expected_us_session(session_date)
    out: dict[str, Any] = {"expected_date": expected.isoformat()}
    for series in US_INDEXES:
        instrument = _instrument(db, US_INDEX_EXCHANGE, series.symbol)
        bars = _two_bars(db, instrument, expected, until)
        value = _bar_object(bars, expected)
        if bars:
            value["freshness"] = _freshness(
                bars[0].trading_date, expected, _closed_dates(_quality_rows(db, series))
            )
            value["trading_date"] = value.pop("date")
        out[series.symbol] = value
    return out


def tx_day_object(db: Session, list_date: date) -> dict[str, Any]:
    instrument = _instrument(db, TX_EXCHANGE, TX_SYMBOL)
    bars = _two_bars(db, instrument, list_date)
    value = _bar_object(bars, list_date)
    if bars:
        latest = bars[0]
        value.update(
            open=latest.open,
            high=latest.high,
            low=latest.low,
            contract_month=latest.contract_month,
            settlement_price=latest.settlement_price,
        )
        if len(bars) > 1 and bars[1].contract_month != latest.contract_month:
            # Bars are not adjusted across a roll: no change.
            value["change_pct"] = None
            value["change_status"] = "contract_roll"
    return value


def tx_night_object(
    db: Session, session_date: date, assembled_at: datetime
) -> dict[str, Any]:
    bar = db.scalar(
        select(FuturesNightBar).where(
            FuturesNightBar.symbol == TX_SYMBOL,
            FuturesNightBar.trading_date == session_date,
            FuturesNightBar.collected_at <= assembled_at,
        )
    )
    if bar is None:
        return {"status": "missing", "expected_date": session_date.isoformat()}
    settlement = bar.close - bar.change if bar.change is not None else None
    return {
        "date": bar.trading_date.isoformat(),
        "session": "15:00-05:00",
        "contract_month": bar.contract_month,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "change_vs_settlement": bar.change,
        "change_pct": _ratio(bar.close, settlement) if settlement else None,
        "volume": bar.volume,
        "source": bar.source,
        "collected_at": _taipei_text(bar.collected_at),
    }


# --- the snapshot -----------------------------------------------------------


def build(
    db: Session, session_date: date, list_date: date, assembled_at: datetime
) -> Snapshot:
    """The snapshot of SESSION_DATE (UTC-naive ``assembled_at``: when it is made)."""

    until = cutoff(session_date)
    news = overnight_news(db, list_date, until)
    stock_news = news_by_stock(db, news)
    run = read_run(db, list_date)
    today_list = (
        list(
            db.scalars(
                select(DailyCandidate)
                .where(DailyCandidate.candidate_run_id == run.id)
                .order_by(DailyCandidate.rank)
            )
        )
        if run is not None
        else []
    )
    listed = {row.instrument_id: row for row in today_list}
    phase, pool, pool_summary = select_pool(
        db, list_date, today_list, stock_news, assembled_at
    )
    groups = groups_of(db, [stock.instrument.id for stock in pool], list_date)
    picked_market = market_news(news)
    news_ids = {entry.item.id for entry in picked_market}
    candidates: list[dict[str, Any]] = []
    metas: list[StockMeta] = []
    symbols: set[str] = set()
    for stock in pool:
        instrument = stock.instrument
        if instrument.symbol in symbols:
            # The output names a stock by its code: a second listing of a code is left out.
            continue
        symbols.add(instrument.symbol)
        own_news = stock_news.get(instrument.id, [])[:STOCK_NEWS_LIMIT]
        news_ids |= {entry.item.id for entry in own_news}
        row = listed.get(instrument.id)
        item: dict[str, Any] = {
            "symbol": instrument.symbol,
            "exchange": instrument.exchange,
            "name": instrument.name,
            "pool_sources": list(stock.sources),
            "on_today_list": row is not None,
            "price": price_object(_bars(db, instrument.id, list_date), list_date),
            "chips": chips_object(db, instrument.id, list_date),
            "groups": groups.get(instrument.id, []),
            "news": [news_object(entry) for entry in own_news],
        }
        levels = rule_levels(db, row) if row is not None else None
        if row is not None:
            item["strategy_levels"] = levels or {"status": "no_levels"}
        candidates.append(item)
        metas.append(
            StockMeta(
                instrument_id=instrument.id,
                symbol=instrument.symbol,
                position=len(metas) + 1,
                on_today_list=row is not None,
                daily_candidate_id=row.id if row is not None else None,
                pool_item_id=stock.pool_item_id,
                pool_sources=list(stock.sources),
                levels=levels,
            )
        )
    group_names: dict[str, str] = {}
    for item in candidates:
        for group in item["groups"]:
            group_names[group["group_id"]] = group["name"]
    theme_ids = {
        str(theme)
        for entry in picked_market
        for theme in entry.item.theme_ids_json or []
    } - set(group_names)
    if theme_ids:
        for group in db.scalars(
            select(ThemeGroup).where(ThemeGroup.id.in_(sorted(theme_ids)))
        ):
            group_names[group.id] = group.display_name_zh or group.name
    payload = {
        "session_date": session_date.isoformat(),
        "list_date": list_date.isoformat(),
        "cutoff_taipei": f"{session_date.isoformat()} {CUTOFF[0]:02d}:{CUTOFF[1]:02d}",
        "pool": {
            "phase": phase,
            "count": len(candidates),
            "today_list_count": sum(1 for item in candidates if item["on_today_list"]),
            "today_list_run_id": run.id if run is not None else None,
            **pool_summary,
        },
        "taiex": taiex_object(db, list_date),
        "us_indices": us_object(db, session_date, until),
        "tx_futures": {
            "day": tx_day_object(db, list_date),
            "night": tx_night_object(db, session_date, assembled_at),
        },
        "overnight_news_stats": news_stats(news),
        "market_news": [news_object(entry) for entry in picked_market],
        "groups": dict(sorted(group_names.items())),
        "candidates": candidates,
    }
    return Snapshot(
        session_date=session_date,
        list_date=list_date,
        cutoff_at=until,
        pool_phase=phase,
        payload=payload,
        stocks=metas,
        news_ids=news_ids,
    )
