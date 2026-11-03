"""Tables of one research backtest run for the #318 report, read only.

Reads the database ``--db`` (the ``tools/ops/copy_db.py`` copy the run of
``backtest_research.py`` wrote) through a ``mode=ro`` connection with
``query_only`` on, and writes to ``--out``:

- ``summary.md``: the tables of the report (counts, return distributions,
  the two benchmarks, the ablations, the days without a conditional signal);
- ``tables.json``: the same numbers, and the run, seed and draws they came from;
- ``daily.csv``: actionable signals per strategy and session;
- ``benchmark_means.csv``: the mean of every draw of benchmark one;
- ``returns.svg``, ``ablations.svg``: the charts of the report.

Strategy results are the run's comparable T+5／T+20 settlements
(``signal_settlements``, V1_SPEC「Tracking 與 technical backtest 口徑」).

Benchmark one draws, for every signal date, as many instruments as the
strategy has comparable settlements that date, without replacement, from the
instruments with a ``market_bars`` row that date whose ``instrument_type`` is
``stock`` or ``ipo`` (not ``status``: an instrument delisted since was listed
then), ``--draws`` times with the seeded ``random.Random(--seed)``.  A drawn
instrument is bought at the open of the next session with the tracking's
5 bps buy slippage and valued at the close of its T+N session, both on the
signal date's price basis (the corporate-action factor of
``worker.pipeline._corporate_action_factor``), less the 30 bps round trip.
Its return is comparable, as a strategy settlement is, only when it has N
sessions after the signal date, none of them suspended (``is_suspended`` or a
zero-volume flat bar) and none of the market's sessions missing; draws come
from the comparable ones.  Benchmark two is TAIEX: its close on the signal
date to its close N market sessions later, per comparable settlement.

Refuses the production database as ``backtest_research.py`` does.  Never
writes the database.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import importlib.util
import json
import os
import random
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HORIZONS = (5, 20)
BENCHMARK_TYPES = ("stock", "ipo")
INDEX_SYMBOL = "TAIEX"
BUY_SLIPPAGE = 5.0 / 10_000.0
ROUND_TRIP_COST = 30.0 / 10_000.0
QUANTILES = (0.10, 0.25, 0.50, 0.75, 0.90)


def _research_module():
    spec = importlib.util.spec_from_file_location(
        "backtest_research", ROOT / "tools" / "research" / "backtest_research.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research_report.py", description=__doc__)
    parser.add_argument("--db", required=True, help="the copy the research run wrote")
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--out", required=True)
    parser.add_argument("--draws", type=int, default=200)
    parser.add_argument("--seed", type=int, default=318)
    return parser


def connect_read_only(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=1")
    return con


def quantile(values: Sequence[float], q: float) -> float:
    """Linear interpolation between closest ranks (numpy's default)."""

    ordered = sorted(values)
    if not ordered:
        raise ValueError("no values")
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def distribution(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "std": statistics.pstdev(values),
        **{f"p{round(q * 100):02d}": quantile(values, q) for q in QUANTILES},
    }


# --- benchmark one -------------------------------------------------------


@dataclass
class Bar:
    trading_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    is_suspended: bool

    @property
    def suspended(self) -> bool:
        return bool(
            self.is_suspended
            or (self.volume == 0 and self.open == self.high == self.low == self.close)
        )


@dataclass
class Instrument:
    bars: list[Bar] = field(default_factory=list)
    actions: list[Any] = field(default_factory=list)

    def dates(self) -> list[date]:
        return [bar.trading_date for bar in self.bars]


def benchmark_return(
    instrument: Instrument,
    signal_date: date,
    horizon: int,
    sessions: Sequence[date],
    factor_of,
) -> float | None:
    """Buy at T+1's open, value at T+``horizon``'s close; None when not comparable.

    ``sessions`` are the market's sessions in order; ``factor_of(actions)``
    is the cumulative corporate-action factor of ``actions``.
    """

    dates = instrument.dates()
    at = bisect.bisect_right(dates, signal_date)
    if at == 0 or dates[at - 1] != signal_date:
        return None
    window = instrument.bars[at : at + horizon]
    if len(window) < horizon:
        return None
    market_at = bisect.bisect_right(sessions, signal_date)
    expected = list(sessions[market_at : market_at + horizon])
    if [bar.trading_date for bar in window] != expected:
        return None  # a market session without a bar: not comparable
    if any(bar.suspended for bar in window):
        return None
    first, last = window[0], window[-1]
    if not (first.open and first.open > 0 and last.close and last.close > 0):
        return None

    def factor(day: date) -> float:
        applied = [
            action
            for action in instrument.actions
            if signal_date < action.action_date <= day
        ]
        return factor_of(applied, signal_date, instrument) if applied else 1.0

    entry = first.open * (1.0 + BUY_SLIPPAGE) / factor(first.trading_date)
    exit_ = last.close / factor(last.trading_date)
    return exit_ / entry - 1.0 - ROUND_TRIP_COST


def draw_means(
    counts: dict[date, int],
    pools: dict[date, list[float]],
    draws: int,
    rng: random.Random,
) -> tuple[list[float], list[float], int]:
    """Mean and median of each draw; the number of instruments each draw holds."""

    means: list[float] = []
    medians: list[float] = []
    size = 0
    days = sorted(counts)
    for _ in range(draws):
        values: list[float] = []
        for day in days:
            pool = pools.get(day) or []
            values.extend(rng.sample(pool, min(counts[day], len(pool))))
        size = len(values)
        if values:
            means.append(statistics.fmean(values))
            medians.append(statistics.median(values))
    return means, medians, size


def rank(value: float, sample: Sequence[float]) -> float | None:
    """Share of ``sample`` at or below ``value``."""

    if not sample:
        return None
    return sum(1 for item in sample if item <= value) / len(sample)


# --- reading the run -----------------------------------------------------


def run_strategies(con: sqlite3.Connection, prefix: str) -> list[dict[str, Any]]:
    rows = con.execute(
        "select sv.id, sv.name, sv.version, sv.kind, sv.config_json "
        "from strategy_versions sv where sv.id in "
        "(select distinct strategy_version_id from signals where signal_key like ?) "
        "order by sv.id",
        (prefix,),
    ).fetchall()
    result = []
    for strategy_id, name, version, kind, config in rows:
        config = json.loads(config) if isinstance(config, str) else (config or {})
        ablation = config.get("ablation") or {}
        result.append(
            {
                "id": strategy_id,
                "name": name,
                "version": version,
                "kind": kind,
                "base": ablation.get("base_strategy"),
                "removed": ablation.get("removed_condition"),
            }
        )
    return result


def settlements(con: sqlite3.Connection, prefix: str) -> list[tuple]:
    return con.execute(
        "select sv.name, s.signal_date, s.instrument_id, st.horizon, st.comparable, "
        "st.return_or_risk, st.final_status, st.execution_date, st.incomparable_reason "
        "from signal_settlements st join signals s on s.id = st.signal_id "
        "join strategy_versions sv on sv.id = s.strategy_version_id "
        "where s.signal_key like ?",
        (prefix,),
    ).fetchall()


def daily_counts(con: sqlite3.Connection, prefix: str) -> list[tuple]:
    return con.execute(
        "select sv.name, s.signal_date, count(*), "
        "sum(case when json_extract(s.rule_evidence_json, '$.actionable') = 1 "
        "then 1 else 0 end), "
        "sum(case when s.status = 'data_incomplete' then 1 else 0 end) "
        "from signals s join strategy_versions sv on sv.id = s.strategy_version_id "
        "where s.signal_key like ? group by sv.name, s.signal_date",
        (prefix,),
    ).fetchall()


def level_distances(con: sqlite3.Connection, prefix: str) -> list[tuple]:
    """Entry, invalid and first-target prices of every actionable signal."""

    return con.execute(
        "select sv.name, coalesce(s.breakout_price, s.reference_entry), "
        "s.invalid_price, s.target_1, s.target_2 "
        "from signals s join strategy_versions sv on sv.id = s.strategy_version_id "
        "where s.signal_key like ? "
        "and json_extract(s.rule_evidence_json, '$.actionable') = 1",
        (prefix,),
    ).fetchall()


def zero_day_reasons(
    con: sqlite3.Connection, prefix: str, name: str, kind: str, days: Iterable[date]
) -> tuple[Counter, Counter, int]:
    """Failed-condition reasons and statuses of ``name``'s signals on ``days``."""

    reasons: Counter = Counter()
    statuses: Counter = Counter()
    total = 0
    for day in days:
        for status, kind_reasons, rationale in con.execute(
            "select s.status, json_extract(s.rule_evidence_json, ?), s.rationale "
            "from signals s join strategy_versions sv "
            "on sv.id = s.strategy_version_id "
            "where s.signal_key like ? and sv.name = ? and s.signal_date = ?",
            (f"$.{kind}.reasons", prefix, name, day.isoformat()),
        ):
            total += 1
            statuses[status] += 1
            for reason in json.loads(kind_reasons or "[]"):
                reasons[reason] += 1
            missing = (rationale or "").rpartition("missing=")[2]
            if "missing=" in (rationale or ""):
                for reason in missing.split(","):
                    if reason:
                        reasons[f"missing:{reason}"] += 1
    return reasons, statuses, total


def market_sessions(con: sqlite3.Connection, start: date) -> list[date]:
    rows = con.execute(
        "select distinct mb.trading_date from market_bars mb "
        "join instruments i on i.id = mb.instrument_id "
        "where i.instrument_type = 'stock' and mb.trading_date >= ? order by 1",
        (start.isoformat(),),
    ).fetchall()
    return [date.fromisoformat(row[0]) for row in rows]


def index_closes(con: sqlite3.Connection, start: date) -> dict[date, float]:
    rows = con.execute(
        "select mb.trading_date, mb.close from market_bars mb "
        "join instruments i on i.id = mb.instrument_id "
        "where i.instrument_type = 'index' and i.symbol = ? and mb.trading_date >= ?",
        (INDEX_SYMBOL, start.isoformat()),
    ).fetchall()
    return {date.fromisoformat(day): close for day, close in rows}


def benchmark_universe(
    con: sqlite3.Connection, start: date
) -> tuple[dict[int, Instrument], dict[date, list[int]]]:
    """Bars and actions of stock／ipo instruments from ``start`` on, by id."""

    instruments: dict[int, Instrument] = defaultdict(Instrument)
    listed: dict[date, list[int]] = defaultdict(list)
    for row in con.execute(
        "select mb.instrument_id, mb.trading_date, mb.open, mb.high, mb.low, "
        "mb.close, mb.volume, mb.is_suspended from market_bars mb "
        "join instruments i on i.id = mb.instrument_id "
        f"where i.instrument_type in ({','.join('?' * len(BENCHMARK_TYPES))}) "
        "and mb.trading_date >= ? order by mb.instrument_id, mb.trading_date",
        (*BENCHMARK_TYPES, start.isoformat()),
    ):
        instrument_id, day, *prices, volume, suspended = row
        day = date.fromisoformat(day)
        instruments[instrument_id].bars.append(
            Bar(day, *prices, volume or 0, bool(suspended))
        )
        listed[day].append(instrument_id)
    return instruments, listed


def load_actions(db: Path, instruments: dict[int, Instrument], start: date):
    """CorporateAction rows after ``start`` and the product's factor function."""

    os.environ["STOCK_DB_PATH"] = str(db.resolve())
    os.environ["STOCK_DATA_DIR"] = str(db.resolve().parent)
    os.environ["STOCK_RAW_DIR"] = str(db.resolve().parent / "raw")
    sys.path.insert(0, str(ROOT / "backend"))
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.models import CorporateAction, MarketBar
    from worker.pipeline import _corporate_action_factor

    engine = create_engine(
        "sqlite://", creator=lambda: connect_read_only(db), future=True
    )
    fallback: dict[tuple[int, date], float] = {}
    with Session(engine) as session:
        for action in session.scalars(
            select(CorporateAction).where(CorporateAction.action_date > start)
        ):
            if action.instrument_id not in instruments:
                continue
            session.expunge(action)
            instruments[action.instrument_id].actions.append(action)
            if action.reference_price is None:
                previous = session.scalar(
                    select(MarketBar.close)
                    .where(
                        MarketBar.instrument_id == action.instrument_id,
                        MarketBar.trading_date < action.action_date,
                    )
                    .order_by(MarketBar.trading_date.desc())
                    .limit(1)
                )
                if previous and previous > 0:
                    fallback[(action.instrument_id, action.action_date)] = previous
    engine.dispose()

    def factor_of(actions, _signal_date, _instrument):
        references = {
            action.action_date: fallback[(action.instrument_id, action.action_date)]
            for action in actions
            if (action.instrument_id, action.action_date) in fallback
        }
        return _corporate_action_factor(
            list(actions), fallback_reference_prices=references
        )[0]

    return factor_of


# --- the report ----------------------------------------------------------


def pct(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def build(
    db: Path, run_id: int, draws: int, seed: int
) -> tuple[dict[str, Any], list[tuple], dict[str, list[float]]]:
    con = connect_read_only(db)
    run = con.execute(
        "select id, status, request_key, started_at, finished_at, metadata_json "
        "from ingestion_runs where id = ? and run_type = 'backtest'",
        (run_id,),
    ).fetchone()
    if not run:
        raise SystemExit(f"no backtest run {run_id} in {db}")
    prefix = f"backtest-{run_id}-%"
    strategies = run_strategies(con, prefix)
    rows = settlements(con, prefix)
    daily = daily_counts(con, prefix)
    signal_days = sorted({date.fromisoformat(row[1]) for row in daily})
    start, end = signal_days[0], signal_days[-1]
    sessions = market_sessions(con, start)
    closes = index_closes(con, start)

    # strategy returns and their dates
    returns: dict[tuple[str, int], list[float]] = defaultdict(list)
    counts: dict[tuple[str, int], Counter] = defaultdict(Counter)
    outcomes: dict[tuple[str, int], Counter] = defaultdict(Counter)
    incomparable: dict[tuple[str, int], Counter] = defaultdict(Counter)
    index_returns: dict[tuple[str, int], list[float]] = defaultdict(list)
    for (
        name,
        day,
        _instrument,
        horizon,
        comparable,
        value,
        status,
        executed,
        why,
    ) in rows:
        key = (name, horizon)
        day = date.fromisoformat(day)
        if comparable and value is not None:
            returns[key].append(value)
            counts[key][day] += 1
            outcomes[key][status] += 1
            at = bisect.bisect_right(sessions, day)
            if day in closes and at + horizon - 1 < len(sessions):
                later = closes.get(sessions[at + horizon - 1])
                if later:
                    index_returns[key].append(later / closes[day] - 1.0)
        elif executed is None:
            incomparable[key]["not_executed"] += 1
        elif "only" in (why or "") and "trading sessions available" in (why or ""):
            incomparable[key]["too_few_sessions"] += 1
        else:
            incomparable[key]["suspended_or_ambiguous"] += 1

    # benchmark one
    instruments, listed = benchmark_universe(con, start)
    factor_of = load_actions(db, instruments, start)
    pools: dict[tuple[int, date], list[float]] = {}
    universe_size: dict[date, int] = {}
    for day in signal_days:
        universe_size[day] = len(listed.get(day, []))
        for horizon in HORIZONS:
            pool = []
            for instrument_id in listed.get(day, []):
                value = benchmark_return(
                    instruments[instrument_id], day, horizon, sessions, factor_of
                )
                if value is not None:
                    pool.append(value)
            pools[(horizon, day)] = pool

    rng = random.Random(seed)
    table: dict[str, Any] = {}
    benchmark_means: dict[str, list[float]] = {}
    for item in strategies:
        for horizon in HORIZONS:
            key = (item["name"], horizon)
            values = returns.get(key, [])
            day_pools = {day: pools[(horizon, day)] for day in counts[key]}
            means, medians, size = draw_means(counts[key], day_pools, draws, rng)
            benchmark_means[f"{item['name']}:T+{horizon}"] = means
            stats = distribution(values)
            table[f"{item['name']}:T+{horizon}"] = {
                "strategy": item["name"],
                "horizon": horizon,
                "returns": stats,
                "outcomes": dict(outcomes[key]),
                "incomparable": dict(incomparable[key]),
                "signal_dates": len(counts[key]),
                "benchmark": {
                    "draws": len(means),
                    "instruments_per_draw": size,
                    "mean_of_means": statistics.fmean(means) if means else None,
                    "means_p025": quantile(means, 0.025) if means else None,
                    "means_p975": quantile(means, 0.975) if means else None,
                    "median_of_medians": statistics.median(medians)
                    if medians
                    else None,
                    "strategy_mean_rank": rank(stats["mean"], means)
                    if stats["n"]
                    else None,
                    "strategy_median_rank": rank(stats["p50"], medians)
                    if stats["n"]
                    else None,
                },
                "taiex": distribution(index_returns.get(key, [])),
            }

    # actionable signals per session; days without one (AC-5)
    per_day: dict[str, dict[date, tuple[int, int, int]]] = defaultdict(dict)
    for name, day, total, actionable, incomplete in daily:
        per_day[name][date.fromisoformat(day)] = (total, actionable or 0, incomplete)
    canonical = [item for item in strategies if not item["base"]]
    zero: dict[str, Any] = {}
    for item in canonical:
        days = [
            day
            for day in signal_days
            if per_day[item["name"]].get(day, (0, 0, 0))[1] == 0
        ]
        binding: Counter = Counter()
        for day in days:
            for other in strategies:
                if (
                    other["base"] == item["name"]
                    and per_day[other["name"]].get(day, (0, 0, 0))[1]
                ):
                    binding[other["removed"]] += 1
            if not any(
                per_day[other["name"]].get(day, (0, 0, 0))[1]
                for other in strategies
                if other["base"] == item["name"]
            ):
                binding["(no single removal)"] += 1
        reasons, statuses, total = zero_day_reasons(
            con, prefix, item["name"], item["kind"], days
        )
        actionable_per_day = [
            per_day[item["name"]].get(day, (0, 0, 0))[1] for day in signal_days
        ]
        zero[item["name"]] = {
            "sessions": len(signal_days),
            "zero_days": len(days),
            "dates": [day.isoformat() for day in days],
            "by_month": dict(Counter(day.strftime("%Y-%m") for day in days)),
            "single_removal_gives_a_signal": dict(binding),
            "signals_on_zero_days": total,
            "statuses_on_zero_days": dict(statuses),
            "reasons_on_zero_days": dict(reasons.most_common()),
            "actionable_per_day": distribution(actionable_per_day),
        }
    both = [
        day
        for day in signal_days
        if all(per_day[item["name"]].get(day, (0, 0, 0))[1] == 0 for item in canonical)
    ]
    zero["all_canonical"] = {
        "zero_days": len(both),
        "dates": [day.isoformat() for day in both],
    }

    # signal counts and level distances
    signal_totals: dict[str, dict[str, int]] = defaultdict(Counter)
    for name, _day, total, actionable, incomplete in daily:
        signal_totals[name]["signals"] += total
        signal_totals[name]["actionable"] += actionable or 0
        signal_totals[name]["data_incomplete"] += incomplete
    distances: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for name, entry, invalid, target_1, target_2 in level_distances(con, prefix):
        if entry and invalid and entry > invalid:
            risk = entry - invalid
            distances[name]["risk_pct"].append(risk / entry)
            if target_1:
                distances[name]["target_1_r"].append((target_1 - entry) / risk)
            if target_2:
                distances[name]["target_2_r"].append((target_2 - entry) / risk)
    executed = Counter()
    for name, _day, _instrument, horizon, _c, _v, _s, executed_at, _w in rows:
        if horizon == HORIZONS[0] and executed_at is not None:
            executed[name] += 1
    whole_taiex = None
    if start in closes and sessions and closes.get(sessions[-1]):
        whole_taiex = closes[sessions[-1]] / closes[start] - 1.0
    con.close()
    result = {
        "db": str(db.resolve()),
        "run": {
            "id": run[0],
            "status": run[1],
            "request_key": run[2],
            "started_at": run[3],
            "finished_at": run[4],
        },
        "signal_dates": {
            "first": start.isoformat(),
            "last": end.isoformat(),
            "sessions": len(signal_days),
        },
        "seed": seed,
        "draws": draws,
        "strategies": strategies,
        "signal_totals": {
            name: {**values, "executed": executed[name]}
            for name, values in signal_totals.items()
        },
        "levels": {
            name: {key: distribution(values) for key, values in items.items()}
            for name, items in distances.items()
        },
        "universe_per_day": distribution(list(universe_size.values())),
        "taiex_whole_window": whole_taiex,
        "results": table,
        "zero_days": zero,
    }
    daily_rows = [
        (name, day.isoformat(), *values)
        for name, items in sorted(per_day.items())
        for day, values in sorted(items.items())
    ]
    return result, daily_rows, benchmark_means


def markdown(result: dict[str, Any], command: str) -> str:
    lines: list[str] = []
    add = lines.append
    run = result["run"]
    add(f"# 研究回測表格：run {run['id']}")
    add("")
    add(f"- 副本：`{result['db']}`")
    add(
        f"- run：`{run['request_key']}`（{run['status']}，{run['started_at']}～{run['finished_at']}）"
    )
    span = result["signal_dates"]
    add(f"- 訊號日：{span['first']}～{span['last']}，{span['sessions']} 個交易日")
    add(
        f"- 基準一：每個訊號日抽與策略同數的 `stock`／`ipo`，{result['draws']} 次，seed {result['seed']}"
    )
    add(f"- 產生命令：`{command}`")
    add("")
    add("## 觸發數")
    add("")
    add("| 策略 | 訊號列 | 條件成立（actionable） | 有成交 | data_incomplete |")
    add("| --- | ---: | ---: | ---: | ---: |")
    for item in result["strategies"]:
        totals = result["signal_totals"].get(item["name"], {})
        add(
            f"| `{item['name']}` | {totals.get('signals', 0):,} | {totals.get('actionable', 0):,} "
            f"| {totals.get('executed', 0):,} | {totals.get('data_incomplete', 0):,} |"
        )
    add("")
    add("## 報酬分佈與基準（可比較的 settlement，扣 30 bps 成本）")
    add("")
    add(
        "| 策略 | T+N | n | 平均 | p10 | p25 | 中位數 | p75 | p90 "
        "| 基準一平均（95% 區間） | 策略平均在基準一的百分位 | TAIEX 同期平均 |"
    )
    add(
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |"
    )
    for key, row in result["results"].items():
        stats, bench, taiex = row["returns"], row["benchmark"], row["taiex"]
        if not stats["n"]:
            add(f"| `{row['strategy']}` | T+{row['horizon']} | 0 | | | | | | | | | |")
            continue
        add(
            f"| `{row['strategy']}` | T+{row['horizon']} | {stats['n']:,} | {pct(stats['mean'])} "
            f"| {pct(stats['p10'])} | {pct(stats['p25'])} | {pct(stats['p50'])} | {pct(stats['p75'])} "
            f"| {pct(stats['p90'])} | {pct(bench['mean_of_means'])}（{pct(bench['means_p025'])}～{pct(bench['means_p975'])}） "
            f"| {pct(bench['strategy_mean_rank'], 0)} | {pct(taiex.get('mean'))} |"
        )
    add("")
    add("## 出場方式與不可比較的原因")
    add("")
    add("| 策略 | T+N | 出場狀態（可比較） | 不可比較 |")
    add("| --- | --- | --- | --- |")
    for row in result["results"].values():
        outcomes = "、".join(f"{k} {v:,}" for k, v in sorted(row["outcomes"].items()))
        bad = "、".join(f"{k} {v:,}" for k, v in sorted(row["incomparable"].items()))
        add(f"| `{row['strategy']}` | T+{row['horizon']} | {outcomes} | {bad} |")
    add("")
    add("## 價位距離（actionable 訊號）")
    add("")
    add("| 策略 | 失效價距進場（中位數） | 目標一 R（中位數） | 目標二 R（中位數） |")
    add("| --- | ---: | ---: | ---: |")
    for name, items in result["levels"].items():
        risk = items.get("risk_pct", {})
        t1 = items.get("target_1_r", {})
        t2 = items.get("target_2_r", {})
        add(
            f"| `{name}` | {pct(risk.get('p50'))} | {t1.get('p50', 0):.2f} | {t2.get('p50', 0):.2f} |"
        )
    add("")
    add("## 沒有條件成立訊號的交易日（AC-5）")
    add("")
    for name, item in result["zero_days"].items():
        if name == "all_canonical":
            add(f"- 兩個策略都沒有：{item['zero_days']} 天 {', '.join(item['dates'])}")
            continue
        add(f"### `{name}`：{item['zero_days']}／{item['sessions']} 天")
        add("")
        per_day = item["actionable_per_day"]
        if per_day.get("n"):
            add(
                f"- 每日條件成立數：中位數 {per_day['p50']:.0f}、p10 {per_day['p10']:.0f}、p90 {per_day['p90']:.0f}"
            )
        add(f"- 月份：{json.dumps(item['by_month'], ensure_ascii=False)}")
        add(
            "- 只移除一個條件就有訊號的天數："
            + json.dumps(item["single_removal_gives_a_signal"], ensure_ascii=False)
        )
        add(
            f"- 這些天的訊號狀態：{json.dumps(item['statuses_on_zero_days'], ensure_ascii=False)}"
        )
        top = list(item["reasons_on_zero_days"].items())[:12]
        add(
            "- 未通過原因（訊號列數，前 12）："
            + "、".join(f"`{k}` {v:,}" for k, v in top)
        )
        add("")
    return "\n".join(lines) + "\n"


# --- charts --------------------------------------------------------------


def svg_returns(result: dict[str, Any], benchmark_means: dict[str, list[float]]) -> str:
    """Benchmark one's draw means per canonical strategy and horizon, the strategy's mean marked."""

    panels = [
        (key, row)
        for key, row in result["results"].items()
        if not next(
            item for item in result["strategies"] if item["name"] == row["strategy"]
        )["base"]
    ]
    width, height, pad = 360, 220, 40
    columns = 2
    rows = (len(panels) + columns - 1) // columns
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width * columns}" '
        f'height="{height * rows}" font-family="sans-serif" font-size="11">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]
    for index, (key, row) in enumerate(panels):
        x0 = (index % columns) * width
        y0 = (index // columns) * height
        means = benchmark_means.get(key, [])
        strategy_mean = row["returns"].get("mean")
        taiex = row["taiex"].get("mean")
        values = [*means, *(v for v in (strategy_mean, taiex) if v is not None)]
        parts.append(
            f'<text x="{x0 + pad}" y="{y0 + 16}" font-weight="bold">{row["strategy"]} T+{row["horizon"]}</text>'
        )
        if not values:
            continue
        low, high = min(values), max(values)
        span = (high - low) or 1e-9
        low -= span * 0.05
        high += span * 0.05
        plot_w, plot_h = width - 2 * pad, height - 2 * pad

        def sx(value: float) -> float:
            return x0 + pad + (value - low) / (high - low) * plot_w

        bins = 20
        hist = [0] * bins
        for value in means:
            hist[min(int((value - low) / (high - low) * bins), bins - 1)] += 1
        top = max(hist) or 1
        for b, count in enumerate(hist):
            bar_h = count / top * (plot_h - 20)
            parts.append(
                f'<rect x="{x0 + pad + b * plot_w / bins:.1f}" y="{y0 + pad + plot_h - bar_h:.1f}" '
                f'width="{plot_w / bins - 1:.1f}" height="{bar_h:.1f}" fill="#9db4cf"/>'
            )
        baseline = y0 + pad + plot_h
        parts.append(
            f'<line x1="{x0 + pad}" y1="{baseline}" x2="{x0 + pad + plot_w}" y2="{baseline}" stroke="#333"/>'
        )
        for tick in range(5):
            value = low + (high - low) * tick / 4
            parts.append(
                f'<text x="{sx(value):.1f}" y="{baseline + 14}" text-anchor="middle">{value * 100:.1f}%</text>'
            )
        for value, color, label in (
            (strategy_mean, "#c0392b", "策略平均"),
            (taiex, "#27ae60", "TAIEX"),
        ):
            if value is None:
                continue
            parts.append(
                f'<line x1="{sx(value):.1f}" y1="{y0 + pad}" x2="{sx(value):.1f}" y2="{baseline}" '
                f'stroke="{color}" stroke-width="2"/>'
            )
            parts.append(
                f'<text x="{sx(value) + 3:.1f}" y="{y0 + pad + (10 if color == "#c0392b" else 24)}" fill="{color}">{label}</text>'
            )
        parts.append(
            f'<text x="{x0 + pad}" y="{y0 + 30}" fill="#555">藍：基準一 {len(means)} 次抽樣的平均報酬</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def svg_ablations(result: dict[str, Any]) -> str:
    """Per ablation: actionable signals relative to its strategy, and the T+5／T+20 mean."""

    totals = result["signal_totals"]
    rows = []
    for item in result["strategies"]:
        if not item["base"]:
            continue
        base = totals.get(item["base"], {}).get("actionable") or 0
        own = totals.get(item["name"], {}).get("actionable") or 0
        means = [
            result["results"]
            .get(f"{item['name']}:T+{h}", {})
            .get("returns", {})
            .get("mean")
            for h in HORIZONS
        ]
        base_means = [
            result["results"]
            .get(f"{item['base']}:T+{h}", {})
            .get("returns", {})
            .get("mean")
            for h in HORIZONS
        ]
        rows.append((item["name"], own / base if base else None, means, base_means))
    line_h, left, width = 22, 260, 760
    height = 60 + line_h * len(rows)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        'font-family="sans-serif" font-size="11">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="10" y="16" font-weight="bold">移除單一條件：條件成立數相對原策略（倍），與 T+5／T+20 平均報酬</text>',
    ]
    ratios = [ratio for _, ratio, _, _ in rows if ratio]
    top = max(ratios + [1.0])
    for index, (name, ratio, means, base_means) in enumerate(rows):
        y = 40 + index * line_h
        parts.append(f'<text x="10" y="{y + 12}">{name}</text>')
        if ratio:
            w = ratio / top * 220
            parts.append(
                f'<rect x="{left}" y="{y}" width="{w:.1f}" height="14" fill="#9db4cf"/>'
            )
            parts.append(
                f'<text x="{left + w + 4:.1f}" y="{y + 12}">{ratio:.2f}×</text>'
            )
        text = "　".join(
            f"T+{h} {pct(m)}（原 {pct(b)}）"
            for h, m, b in zip(HORIZONS, means, base_means)
        )
        parts.append(f'<text x="{left + 280}" y="{y + 12}">{text}</text>')
    one = left + 1.0 / top * 220
    parts.append(
        f'<line x1="{one:.1f}" y1="34" x2="{one:.1f}" y2="{height - 10}" stroke="#c0392b" stroke-dasharray="3,3"/>'
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _parser().parse_args(argv)
    db = Path(args.db)
    problem = _research_module().production_problem(db, dict(os.environ))
    if problem or not db.is_file():
        print(json.dumps({"refused": [problem or f"{db} does not exist"]}))
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result, daily_rows, benchmark_means = build(db, args.run_id, args.draws, args.seed)
    command = "python tools/research/research_report.py " + " ".join(argv)
    result["command"] = command
    (out / "tables.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (out / "summary.md").write_text(markdown(result, command), encoding="utf-8")
    with (out / "daily.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["strategy", "signal_date", "signals", "actionable", "data_incomplete"]
        )
        writer.writerows(daily_rows)
    with (out / "benchmark_means.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(["strategy_horizon", "draw", "mean"])
        for key, means in benchmark_means.items():
            writer.writerows((key, index, value) for index, value in enumerate(means))
    (out / "returns.svg").write_text(
        svg_returns(result, benchmark_means), encoding="utf-8"
    )
    (out / "ablations.svg").write_text(svg_ablations(result), encoding="utf-8")
    print(
        json.dumps(
            {"out": str(out.resolve()), "run": result["run"]}, ensure_ascii=False
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
