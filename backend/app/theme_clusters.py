"""量價共振分群 (Issue #1018): compute, store and read a day's clusters.

The method is #1003 AC-2 §2 方法一 (comment 7107953147), the evaluation's
``cluster.py`` written again for the product; the thresholds are
``ClusterConfig`` and every run stores the ones it used.

- **Sessions**: the TAIEX (``index`` ``TWSE:TAIEX``) bars; the trading date
  must have one.  The window is the last ``history_days`` (41) sessions up to
  the trading date.
- **Universe**: ``stock``／``ipo`` instruments with a positive ``adj_close`` on
  every session of the window.
- **Screen**: mean volume of the last 20 sessions ≥ 1,000 lots; the 20-session
  return minus TAIEX's ≥ 10%; the mean trading value (``turnover``, else close
  × volume) of the last 5 sessions over the mean of the 20 before them ≥ 1.3
  (the base mean is at least 1).
- **Clusters**: the Pearson correlation of the screened stocks' daily excess
  returns (stock minus TAIEX) over the last 40 sessions (0 when a series is
  constant); average-linkage agglomeration, merging the most correlated pair
  of clusters while its average correlation is ≥ 0.45; a cluster needs at
  least 3 stocks.  Ties merge the pair listed first, the stocks being listed
  by instrument id, so a rerun gives the same clusters.
- **Order**: the largest cluster is 1; same size, the one with the smaller
  first instrument id first.

A rerun of the same date and version replaces the run and its members.  The
clusters are research input only: nothing here is scored, ranked or named;
``worker.theme_discovery`` sends some of them to the LLM for a theme
candidate.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from .models import Instrument, MarketBar, ThemeClusterMember, ThemeClusterRun

THEME_CLUSTER_VERSION = "theme_cluster_v1"
INDEX_EXCHANGE = "TWSE"
INDEX_SYMBOL = "TAIEX"
INSTRUMENT_TYPES = ("stock", "ipo")
SHARES_PER_LOT = 1000


class ThemeClusterDataError(RuntimeError):
    """The trading date cannot be clustered (no TAIEX bar, short history)."""


@dataclass(frozen=True)
class ClusterConfig:
    liquidity_days: int = 20
    min_average_lots: float = 1000.0
    excess_days: int = 20
    min_excess_return: float = 0.10
    amount_recent_days: int = 5
    amount_base_days: int = 20
    min_amount_ratio: float = 1.3
    correlation_days: int = 40
    link_threshold: float = 0.45
    min_cluster_size: int = 3

    @property
    def history_days(self) -> int:
        return max(
            self.liquidity_days,
            self.excess_days + 1,
            self.amount_recent_days + self.amount_base_days,
            self.correlation_days + 1,
        )

    def as_json(self) -> dict[str, Any]:
        return {
            "version": THEME_CLUSTER_VERSION,
            "index": f"{INDEX_EXCHANGE}:{INDEX_SYMBOL}",
            "history_days": self.history_days,
            **asdict(self),
        }


DEFAULT_CONFIG = ClusterConfig()


@dataclass
class Series:
    """One stock's window, oldest first; ``None`` where it has no bar."""

    instrument_id: int
    prices: list[float | None]
    volumes: list[float] = field(default_factory=list)
    amounts: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class Screened:
    instrument_id: int
    excess_return_20d: float
    amount_ratio_5_20: float
    average_lots_20d: float
    excess_returns: tuple[float, ...]


@dataclass(frozen=True)
class ClusterMember:
    instrument_id: int
    member_mean_corr: float
    excess_return_20d: float
    amount_ratio_5_20: float
    average_lots_20d: float


@dataclass(frozen=True)
class Cluster:
    cluster_no: int
    mean_corr: float
    members: tuple[ClusterMember, ...]

    @property
    def instrument_ids(self) -> list[int]:
        return [member.instrument_id for member in self.members]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def screen(
    index_prices: list[float], series: list[Series], config: ClusterConfig
) -> list[Screened]:
    """The stocks passing the screen, by instrument id."""

    n = len(index_prices)
    if n < config.history_days:
        raise ThemeClusterDataError(
            f"{INDEX_SYMBOL} has {n} sessions, {config.history_days} needed"
        )
    index_returns = [
        index_prices[k] / index_prices[k - 1] - 1.0
        for k in range(n - config.correlation_days, n)
    ]
    index_excess = index_prices[-1] / index_prices[-1 - config.excess_days]
    passed: list[Screened] = []
    for item in sorted(series, key=lambda value: value.instrument_id):
        window = item.prices[-config.history_days :]
        if len(window) < config.history_days or any(
            price is None or price <= 0 for price in window
        ):
            continue
        prices: list[float] = item.prices  # type: ignore[assignment]
        lots = _mean(item.volumes[-config.liquidity_days :]) / SHARES_PER_LOT
        if lots < config.min_average_lots:
            continue
        excess = prices[-1] / prices[-1 - config.excess_days] - index_excess
        recent = item.amounts[-config.amount_recent_days :]
        base = item.amounts[
            -(config.amount_recent_days + config.amount_base_days) : -(
                config.amount_recent_days
            )
        ]
        ratio = _mean(recent) / max(_mean(base), 1.0)
        if excess < config.min_excess_return or ratio < config.min_amount_ratio:
            continue
        returns = tuple(
            (prices[k] / prices[k - 1] - 1.0) - index_returns[offset]
            for offset, k in enumerate(range(n - config.correlation_days, n))
        )
        passed.append(Screened(item.instrument_id, excess, ratio, lots, returns))
    return passed


def correlation(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    mean_a, mean_b = _mean(list(a)), _mean(list(b))
    var_a = sum((x - mean_a) ** 2 for x in a)
    var_b = sum((y - mean_b) ** 2 for y in b)
    if not var_a or not var_b:
        return 0.0
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    return cov / math.sqrt(var_a * var_b)


def cluster(screened: list[Screened], config: ClusterConfig) -> list[Cluster]:
    """Average-linkage clusters of the screened stocks (see the module doc)."""

    items = sorted(screened, key=lambda value: value.instrument_id)
    count = len(items)
    corr = [[0.0] * count for _ in range(count)]
    for i in range(count):
        for j in range(i + 1, count):
            corr[i][j] = corr[j][i] = correlation(
                items[i].excess_returns, items[j].excess_returns
            )
    groups: list[list[int]] = [[i] for i in range(count)]
    # link[a][b]: the average correlation between groups a and b, kept with the
    # Lance-Williams update (the mean over every cross pair).
    link = {a: {b: corr[a][b] for b in range(count) if b != a} for a in range(count)}
    alive = list(range(count))
    while True:
        best: tuple[float, int, int] | None = None
        for x, a in enumerate(alive):
            for b in alive[x + 1 :]:
                value = link[a][b]
                if value >= config.link_threshold and (best is None or value > best[0]):
                    best = (value, a, b)
        if best is None:
            break
        _value, a, b = best
        size_a, size_b = len(groups[a]), len(groups[b])
        for c in alive:
            if c in (a, b):
                continue
            merged = (size_a * link[a][c] + size_b * link[b][c]) / (size_a + size_b)
            link[a][c] = link[c][a] = merged
            del link[c][b]
        groups[a].extend(groups[b])
        alive.remove(b)
    kept = [
        sorted(groups[a]) for a in alive if len(groups[a]) >= config.min_cluster_size
    ]
    kept.sort(key=lambda members: (-len(members), items[members[0]].instrument_id))
    clusters: list[Cluster] = []
    for number, members in enumerate(kept, start=1):
        pairs = [corr[i][j] for x, i in enumerate(members) for j in members[x + 1 :]]
        clusters.append(
            Cluster(
                cluster_no=number,
                mean_corr=_mean(pairs),
                members=tuple(
                    ClusterMember(
                        instrument_id=items[i].instrument_id,
                        member_mean_corr=_mean(
                            [corr[i][j] for j in members if j != i]
                        ),
                        excess_return_20d=items[i].excess_return_20d,
                        amount_ratio_5_20=items[i].amount_ratio_5_20,
                        average_lots_20d=items[i].average_lots_20d,
                    )
                    for i in members
                ),
            )
        )
    return clusters


# --- reading the bars -----------------------------------------------------


def index_sessions(db: Session, day: date, count: int) -> list[tuple[date, float]]:
    """The last ``count`` TAIEX sessions up to ``day``, oldest first."""

    rows = db.execute(
        select(MarketBar.trading_date, MarketBar.adj_close, MarketBar.close)
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
        raise ThemeClusterDataError(f"no {INDEX_SYMBOL} bar on {day.isoformat()}")
    sessions = []
    for row in reversed(rows):
        price = row.adj_close if row.adj_close is not None else row.close
        if price is None or price <= 0:
            raise ThemeClusterDataError(
                f"{INDEX_SYMBOL} has no close on {row.trading_date.isoformat()}"
            )
        sessions.append((row.trading_date, float(price)))
    return sessions


def load_series(db: Session, sessions: list[date]) -> list[Series]:
    position = {day: k for k, day in enumerate(sessions)}
    count = len(sessions)
    series: dict[int, Series] = {}
    rows = db.execute(
        select(
            MarketBar.instrument_id,
            MarketBar.trading_date,
            MarketBar.adj_close,
            MarketBar.volume,
            MarketBar.turnover,
            MarketBar.close,
        )
        .join(Instrument, Instrument.id == MarketBar.instrument_id)
        .where(
            Instrument.instrument_type.in_(INSTRUMENT_TYPES),
            MarketBar.trading_date >= sessions[0],
            MarketBar.trading_date <= sessions[-1],
        )
    ).all()
    for instrument_id, day, adj_close, volume, turnover, close in rows:
        k = position.get(day)
        if k is None:
            continue
        item = series.get(instrument_id)
        if item is None:
            item = series[instrument_id] = Series(
                instrument_id, [None] * count, [0.0] * count, [0.0] * count
            )
        item.prices[k] = adj_close
        item.volumes[k] = float(volume or 0)
        item.amounts[k] = float(turnover or (close or 0) * (volume or 0))
    return list(series.values())


def compute_clusters(
    db: Session, day: date, config: ClusterConfig = DEFAULT_CONFIG
) -> tuple[list[Screened], list[Cluster]]:
    sessions = index_sessions(db, day, config.history_days)
    if len(sessions) < config.history_days:
        raise ThemeClusterDataError(
            f"{INDEX_SYMBOL} has {len(sessions)} sessions to {day.isoformat()}, "
            f"{config.history_days} needed"
        )
    series = load_series(db, [session for session, _price in sessions])
    screened = screen([price for _session, price in sessions], series, config)
    return screened, cluster(screened, config)


# --- writing and reading --------------------------------------------------


def store_clusters(
    db: Session, day: date, config: ClusterConfig = DEFAULT_CONFIG
) -> ThemeClusterRun:
    """Compute and commit ``day``'s clusters, replacing a previous run."""

    screened, clusters = compute_clusters(db, day, config)
    old = db.scalars(
        select(ThemeClusterRun.id).where(
            ThemeClusterRun.trading_date == day,
            ThemeClusterRun.version == THEME_CLUSTER_VERSION,
        )
    ).all()
    if old:
        db.execute(
            delete(ThemeClusterMember).where(
                ThemeClusterMember.theme_cluster_run_id.in_(old)
            )
        )
        db.execute(delete(ThemeClusterRun).where(ThemeClusterRun.id.in_(old)))
    run = ThemeClusterRun(
        trading_date=day,
        version=THEME_CLUSTER_VERSION,
        status="computed" if screened else "zero",
        screened_count=len(screened),
        cluster_count=len(clusters),
        config_json=config.as_json(),
    )
    db.add(run)
    db.flush()
    for item in clusters:
        for member in item.members:
            db.add(
                ThemeClusterMember(
                    theme_cluster_run_id=run.id,
                    trading_date=day,
                    instrument_id=member.instrument_id,
                    version=THEME_CLUSTER_VERSION,
                    cluster_no=item.cluster_no,
                    cluster_size=len(item.members),
                    cluster_mean_corr=item.mean_corr,
                    member_mean_corr=member.member_mean_corr,
                    excess_return_20d=member.excess_return_20d,
                    amount_ratio_5_20=member.amount_ratio_5_20,
                    average_lots_20d=member.average_lots_20d,
                )
            )
    db.commit()
    return run


def stored_clusters(db: Session, run: ThemeClusterRun) -> list[Cluster]:
    """A stored run's clusters, in cluster order (members by instrument id)."""

    rows = db.scalars(
        select(ThemeClusterMember)
        .where(ThemeClusterMember.theme_cluster_run_id == run.id)
        .order_by(ThemeClusterMember.cluster_no, ThemeClusterMember.instrument_id)
    ).all()
    grouped: dict[int, list[ThemeClusterMember]] = {}
    for row in rows:
        grouped.setdefault(row.cluster_no, []).append(row)
    return [
        Cluster(
            cluster_no=number,
            mean_corr=members[0].cluster_mean_corr,
            members=tuple(
                ClusterMember(
                    instrument_id=row.instrument_id,
                    member_mean_corr=row.member_mean_corr,
                    excess_return_20d=row.excess_return_20d,
                    amount_ratio_5_20=row.amount_ratio_5_20,
                    average_lots_20d=row.average_lots_20d,
                )
                for row in members
            ),
        )
        for number, members in grouped.items()
    ]
