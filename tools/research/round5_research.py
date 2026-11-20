"""Round 5 of the new-strategy exploration: V1～V3 (#889).

docs/spec/evidence.md 第五輪：V1～V3 and 第五輪實作釋義: the hypotheses were
registered (commit ``ec72e67d``, #887, decision 7047319922) before anyone ran a
tool on the backfilled history.  Nothing here is a command-line option: a
change of a definition is a new code.

They are not in ``explore_research.HYPOTHESES``: its ``definitions_sha256``
hashes that whole table, so adding them would make the validation refuse the
X1～X8 exploration reports already run (the reason of round 3's own entry).
The engine, the population, the subset, ``turnover_60``, ``_momentum``,
``explore_judge``, the gate and the ledgers are imported; new here are only
``vol_60``, ``cash_yield_12m`` and the "small first" order.

Each signal date T (after its close, only T's data and before; the actions
with ``action_date <= T``):

- V1: ``vol_60`` small first — the sample standard deviation (ddof 1) of the
  60 daily returns of the 61 adjusted closes ``at - 60 .. at`` of the stock's
  own bars; missing with fewer than 61 bars, a close missing or ≤ 0, or any
  of the 61 a suspended bar.  N 20, K 60.
- V2: the 150 highest ``turnover_60`` of the population (a missing value out,
  ties by the hash), then ``momentum_20`` small first inside them (a missing
  value keeps its place in the 150, ranked last).  N 20, K 20.
- V3: ``cash_yield_12m`` high first — the cash dividends of the rows with
  ``T - 365 < action_date <= T`` over T's unadjusted close; a row with none of
  the three fields is unknown and makes the value missing, a row with only a
  stock dividend or a split counts 0, no row is 0.  N 20, K 60.

A missing key is last whether high or low first; ties by
``portfolio_research.tie_break``.  ``portfolio_research.simulate`` (K accounts,
1/20 of the account's cash each) trades; the benchmark is the same engine over
the day's whole population.  ``explore_research.explore_judge`` judges with
t ≥ 2 on the exploration and the fixed Bonferroni t ≥ 3.052 (22 hypotheses)
on the validation.  The segments, floors, public check, the gate (the
exploration once per version, the validation once after a published
exploration report) and the ledgers (``explore-ledger.json`` beside the DB
and the repository's ``tools/research/explore_ledger.json``, each entry with
``"tool": "round5_research"``) are ``explore_research``'s.  ``--coverage-only``
writes the share of missing values per year and V3's data check (rule 6), no
return at all.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
import time
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_lib as lib  # noqa: E402
import explore_research as ex  # noqa: E402
import feature_evidence as features  # noqa: E402
import portfolio_research as pr  # noqa: E402

VERSION = 1
DESIGN = "889"
TOOL = "round5_research"
REGISTRATION_COMMIT = "ec72e67d"
DECISION = "https://github.com/YiCheng0608/stock-lab/issues/887#issuecomment-7047319922"
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
SEGMENTS = dict(ex.SEGMENTS)
MIN_SEGMENT_DAYS = dict(ex.MIN_SEGMENT_DAYS)
MIN_T = ex.MIN_T  # the exploration's t ≥ 2
# docs 第五輪 門檻: 1 − Φ(z) = 0.025 ÷ 22, z = 3.0521 to the 3rd decimal; fixed,
# not computed when run.
VALIDATION_MIN_T = 3.052
ROUND = 5
ROUND_SIZE = 3
CUMULATIVE = (
    22  # X1～X8, S1～S3, R1～R2, M1～M2, C1～C4, V1～V3; H1 and #619～#689 apart
)
LOAD_FROM = ex.LOAD_FROM  # the exploration reads the copy from its start
WARMUP_CALENDAR_DAYS = ex.WARMUP_CALENDAR_DAYS
MIN_LOTS = lib.DEFAULT_MIN_LOTS
RAW_DIR_NAME = ex.RAW_DIR_NAME
POPULATION = pr.POPULATION
TAIEX = pr.TAIEX

HIGH = "high"  # high first
LOW = "low"  # small first
VOL_WINDOW = 60  # returns, of 61 closes
VOL_DDOF = 1
MOMENTUM_WINDOW = 20
YIELD_CALENDAR_DAYS = 365  # T − 365 < action_date <= T
# The OTC bars from 2007-04-23 to 2007-11-30 are not read (bar_exclusions.json):
# V1 and V2 count from the OTC 2007-12-03.
OTC_ANCHOR = date(2007, 12, 3)
DELISTED_STATUSES = ("delisted", "transferred")

# The registration (docs 第五輪：V1～V3), word for word.  ``start`` as
# ``explore_research``: ("session", anchor, n) is the n-th session counting the
# anchor (or the first session after it) as the first; ("date", d) the first
# session from d.  ``subset``: (feature, n) keeps the n highest of the
# population, a missing value out.  ``keys``: (feature, HIGH | LOW), a missing
# value last either way, ties by ``portfolio_research.tie_break``.
HYPOTHESES: dict[str, dict[str, Any]] = {
    "V1": {
        "direction": "低波動",
        "label": "`vol_60`（近 60 日日報酬的樣本標準差）小者先",
        "rule": "daily",
        "subset": None,
        "keys": (("vol_60", LOW),),
        "top": 20,
        "hold": 60,
        "start": ("session", OTC_ANCHOR, 61),
    },
    "V2": {
        "direction": "短期反轉",
        "label": "母體中 60 日平均成交金額前 150 名，依 `momentum_20`（20 日報酬）小者先",
        "rule": "daily",
        "subset": ("turnover_60", 150),
        "keys": (("momentum_20", LOW),),
        "top": 20,
        "hold": 20,
        "start": ("session", OTC_ANCHOR, 60),
    },
    "V3": {
        "direction": "股利",
        "label": "`cash_yield_12m`（近 12 個月現金股利合計 ÷ T 日未還原收盤）大者先",
        "rule": "daily",
        "subset": None,
        "keys": (("cash_yield_12m", HIGH),),
        "top": 20,
        "hold": 60,
        "start": ("date", date(2008, 12, 1)),
    },
}
OTHER_COMPARISONS = ex.OTHER_COMPARISONS
REASONS = dict(ex.REASONS)
VOLATILE_KEYS = ex.VOLATILE_KEYS
V3_LIMIT = (
    "分子是除息當時的每股股利，窗口內若有配股、分割或減資，它和 T 日未還原收盤不在同一個股本基準上"
    "（例如配股之後的股價較低，殖利率會偏高）；不換算"
)


def definitions() -> dict[str, Any]:
    return {
        "version": VERSION,
        "design": DESIGN,
        "hypotheses": HYPOTHESES,
        "features": {
            "vol_60": {
                "returns": VOL_WINDOW,
                "closes": "Series.close at-60..at",
                "ddof": VOL_DDOF,
                "missing": "fewer than 61 bars; a close missing or <= 0; a suspended bar",
            },
            "momentum_20": {"function": "feature_evidence._momentum", "sessions": 20},
            "turnover_60": {
                "function": "explore_research.turnover_60",
                "window": ex.TURNOVER_WINDOW,
                "available": ex.TURNOVER_AVAILABLE,
            },
            "cash_yield_12m": {
                "window": f"T - {YIELD_CALENDAR_DAYS} < action_date <= T (calendar days)",
                "cash": "cash_dividend; null with stock_dividend_ratio or split_ratio: 0; "
                "all three null: missing",
                "no_row": 0.0,
                "close": "market_bars.close of T (unadjusted); missing or <= 0: missing",
            },
        },
        "order": "missing last for high and low first; ties sha256(<T>:<instrument_id>)",
        "subset": "the n highest, a missing value out, ties by the hash; before the order",
        "segments": SEGMENTS,
        "min_segment_days": MIN_SEGMENT_DAYS,
        "min_t": MIN_T,
        "validation_min_t": VALIDATION_MIN_T,
        "round": [ROUND, ROUND_SIZE, CUMULATIVE],
        "costs": [pr.SLIPPAGE, pr.FEE, pr.TAX],
        "min_lots": MIN_LOTS,
        "warmup": WARMUP_CALENDAR_DAYS,
    }


def definitions_sha256() -> str:
    """Hash of every fixed number the verdicts depend on (the definitions, the
    segments, both thresholds, the costs).  A changed tool needs a new
    exploration report before a validation."""

    text = json.dumps(definitions(), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- reading ----------------------------------------------------------------------


@dataclass
class Actions:
    """One instrument's corporate actions by ``action_date``: each row's cash
    dividend (0 for a stock dividend or split only; None when all three
    fields are null)."""

    dates: list[date] = field(default_factory=list)
    cash: list[float | None] = field(default_factory=list)


def row_cash(action: Any) -> float | None:
    """The fields, not ``action_type`` (TWSE's rows are all ``corporate_action``)."""

    if action.cash_dividend is not None:
        return float(action.cash_dividend)
    if action.stock_dividend_ratio is not None or action.split_ratio is not None:
        return 0.0
    return None


def actions_of(rows: list[Any]) -> Actions:
    out = Actions()
    for action in sorted(rows, key=lambda row: row.action_date):
        out.dates.append(action.action_date)
        out.cash.append(row_cash(action))
    return out


@dataclass
class Context:
    """``explore_research``'s context (the market, the turnovers, the quotes)
    plus the actions and the statuses V3 reads."""

    base: ex.Context
    actions: dict[int, Actions] = field(default_factory=dict)
    statuses: dict[int, str] = field(default_factory=dict)
    cache: dict[tuple[str, int, int], Any] = field(default_factory=dict)

    @property
    def market(self) -> pr.Market:
        return self.base.market

    @property
    def panel(self) -> lib.Panel:
        return self.base.market.panel

    def quote(self, instrument_id: int, s: int) -> pr.Quote | None:
        return self.base.quote(instrument_id, s)


def load(db: Path, start: date, end: date, raw_dir: Path) -> Context:
    """The panel, the turnovers and the actions from ``start`` to ``end``
    (``research_report.load_actions``); nothing after ``end`` is read."""

    base = ex.load_context(db, start, end, raw_dir)
    report = lib.research_report()
    holders = {
        instrument_id: report.Instrument() for instrument_id in base.market.panel.series
    }
    report.load_actions(db, holders, start, raw_dir, end)
    ctx = Context(base)
    ctx.actions = {
        instrument_id: actions_of(holder.actions)
        for instrument_id, holder in holders.items()
        if holder.actions
    }
    con = lib.connect_read_only(db)
    try:
        ctx.statuses = {
            instrument_id: status
            for instrument_id, status in con.execute(
                "select id, status from instruments"
            )
            if instrument_id in base.market.panel.series
        }
    finally:
        con.close()
    return ctx


# --- features ---------------------------------------------------------------------


MOMENTUM_20 = features._momentum(MOMENTUM_WINDOW)


def vol_60(ctx: Context, item: lib.Series, at: int) -> float | None:
    """The sample standard deviation (ddof 1) of the 60 returns of the 61
    adjusted closes ``at - 60 .. at``; missing with fewer than 61 bars, a close
    missing or ≤ 0, or a suspended bar among the 61 (第五輪實作釋義)."""

    if at < VOL_WINDOW:
        return None
    first = at - VOL_WINDOW
    if item.suspended[at + 1] != item.suspended[first]:
        return None  # a suspended bar in first .. at
    closes = item.close[first : at + 1]
    if not all(close > 0 for close in closes):  # NaN fails too
        return None
    returns = [closes[k] / closes[k - 1] - 1.0 for k in range(1, len(closes))]
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - VOL_DDOF)
    return math.sqrt(variance)


def momentum_20(_ctx: Context, item: lib.Series, at: int) -> float | None:
    value = MOMENTUM_20(item, at)
    return None if value is None or value != value else float(value)


def turnover_60(ctx: Context, item: lib.Series, at: int) -> float | None:
    return ex.turnover_60(ctx.base, item, at)


@dataclass(frozen=True)
class Yield:
    value: float | None
    unknown_row: bool  # a row in the window with all three fields null
    no_close: bool  # T's unadjusted close missing or ≤ 0


def cash_yield_parts(ctx: Context, item: lib.Series, at: int) -> Yield:
    day = item.dates[at]
    actions = ctx.actions.get(item.instrument_id)
    total, unknown = 0.0, False
    if actions is not None:
        lo = bisect_right(actions.dates, day - timedelta(days=YIELD_CALENDAR_DAYS))
        hi = bisect_right(actions.dates, day)
        for cash in actions.cash[lo:hi]:
            if cash is None:
                unknown = True
            else:
                total += cash
    close = ctx.market.raw[item.instrument_id][2][at]
    no_close = not (close > 0)
    value = None if unknown or no_close else total / close
    return Yield(value, unknown, no_close)


def cash_yield_12m(ctx: Context, item: lib.Series, at: int) -> float | None:
    return cash_yield_parts(ctx, item, at).value


FEATURES: dict[str, Callable[[Context, lib.Series, int], float | None]] = {
    "vol_60": vol_60,
    "momentum_20": momentum_20,
    "turnover_60": turnover_60,
    "cash_yield_12m": cash_yield_12m,
}
FEATURE_LABELS = {
    "vol_60": "近 60 日報酬標準差",
    "momentum_20": "20 日報酬",
    "turnover_60": "60 日平均成交金額",
    "cash_yield_12m": "近 12 個月現金殖利率",
}


def used_features(spec: dict[str, Any]) -> tuple[str, ...]:
    names: list[str] = []
    if spec["subset"]:
        names.append(spec["subset"][0])
    names += [name for name, _direction in spec["keys"]]
    return tuple(dict.fromkeys(names))


# --- the order --------------------------------------------------------------------


def order_key(
    values: dict[str, float | None], keys: tuple[tuple[str, str], ...], tie: str
) -> tuple:
    """Each key high or small first, a missing value last either way (not the
    negated key with the missing ones first); then the neutral tie-break.
    With every key high first it is ``portfolio_research.ranking_key``."""

    out: list[Any] = []
    for name, direction in keys:
        value = values[name]
        if value is None:
            out += [True, 0.0]
        else:
            out += [False, -value if direction == HIGH else value]
    out.append(tie)
    return tuple(out)


@dataclass
class Ranked:
    rows: list[tuple[int, dict[str, float | None], str]]
    missing: Counter
    subset: int = 0  # members in the subset
    subset_missing: Counter = field(default_factory=Counter)
    unknown_rows: int = 0  # V3: a row with all three fields null
    no_close: int = 0  # V3: T's unadjusted close missing or ≤ 0


def rank(
    ctx: Context,
    spec: dict[str, Any],
    day: date,
    members: list[tuple[lib.Series, int]],
) -> Ranked:
    """The day's members in the hypothesis's order (the subset first) and the
    counts of missing values.  The cache holds this signal date only."""

    ctx.cache.clear()
    names = used_features(spec)
    out = Ranked([], Counter())
    rows = []
    for item, at in members:
        values: dict[str, float | None] = {}
        for name in names:
            if name == "cash_yield_12m":
                parts = cash_yield_parts(ctx, item, at)
                values[name] = parts.value
                out.unknown_rows += parts.unknown_row
                out.no_close += parts.no_close
            else:
                values[name] = FEATURES[name](ctx, item, at)
            out.missing[name] += values[name] is None
        rows.append((item.instrument_id, values, pr.tie_break(day, item.instrument_id)))
    if spec["subset"]:
        name, size = spec["subset"]
        kept = [row for row in rows if row[1][name] is not None]
        kept.sort(key=lambda row: (-row[1][name], row[2]))
        rows = kept[:size]
        out.subset = len(rows)
        for key, _direction in spec["keys"]:
            out.subset_missing[key] += sum(1 for row in rows if row[1][key] is None)
    keys = tuple(spec["keys"])
    rows.sort(key=lambda row: order_key(row[1], keys, row[2]))
    out.rows = rows
    return out


# --- one segment ------------------------------------------------------------------


def segment_window(
    sessions: list[date], segment: str, spec: dict[str, Any]
) -> tuple[int, int] | None:
    """(first, last) index of the sessions with an equity value, or None
    (``explore_research.segment_window`` on this tool's segments)."""

    first_day, last_day = SEGMENTS[segment]
    last = bisect_left(sessions, last_day + timedelta(days=1)) - 1
    if first_day is None:
        base = ex.start_index(sessions, spec["start"])
        if base is None:
            return None
    else:
        base = max(bisect_left(sessions, first_day), 1) - 1
    first = base + 1
    return (first, last) if first <= last else None


@dataclass
class Plan:
    picks: dict[int, list[int]] = field(default_factory=dict)
    population: dict[int, list[int]] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    signal_days: int = 0


def _coverage_add(
    coverage: dict[str, Any], spec: dict[str, Any], day: date, members: int, r: Ranked
) -> None:
    year = coverage.setdefault(str(day.year), {"days": 0, "members": 0, "missing": {}})
    year["days"] += 1
    year["members"] += members
    for name in used_features(spec):
        year["missing"][name] = year["missing"].get(name, 0) + r.missing[name]
    if spec["subset"]:
        year["subset"] = year.get("subset", 0) + r.subset
        missing = year.setdefault("subset_missing", {})
        for name, _direction in spec["keys"]:
            missing[name] = missing.get(name, 0) + r.subset_missing[name]
    if "cash_yield_12m" in used_features(spec):
        year["unknown_rows"] = year.get("unknown_rows", 0) + r.unknown_rows
        year["no_close"] = year.get("no_close", 0) + r.no_close


def plan(
    ctx: Context, spec: dict[str, Any], first: int, last: int, keep_rows: bool = True
) -> Plan:
    """The picks, the population and the coverage on the signal dates
    ``first − 1`` .. ``last − 1`` (only T's data and before is read)."""

    panel = ctx.panel
    out = Plan()
    top = spec["top"]
    names = used_features(spec)
    for at in range(first - 1, last):
        day = panel.sessions[at]
        members = lib.universe(panel, day, MIN_LOTS)
        ranked = rank(ctx, spec, day, members)
        _coverage_add(out.coverage, spec, day, len(members), ranked)
        out.signal_days += 1
        out.picks[at + 1] = [row[0] for row in ranked.rows]
        out.population[at + 1] = [item.instrument_id for item, _ in members]
        if not keep_rows:
            continue
        for place, (instrument_id, values, tie) in enumerate(ranked.rows[:top], 1):
            exchange, symbol, _ = panel.symbols.get(instrument_id, ("", "", ""))
            out.rows.append(
                {
                    "signal_date": day.isoformat(),
                    "rank": place,
                    "exchange": exchange,
                    "symbol": symbol,
                    **{name: values[name] for name in names},
                    "tie": tie[:12],
                }
            )
    return out


def _window_facts(sessions: list[date], window: tuple[int, int]) -> dict[str, Any]:
    first, last = window
    return {
        "first_signal": sessions[first - 1].isoformat(),
        "first_session": sessions[first].isoformat(),
        "last_session": sessions[last].isoformat(),
        "days": last - first + 1,
    }


def run_one(
    ctx: Context,
    db: Path,
    name: str,
    segment: str,
    coverage_only: bool = False,
    min_t: float = MIN_T,
) -> dict[str, Any]:
    """One hypothesis on one segment: its numbers, verdict and private parts."""

    spec = HYPOTHESES[name]
    sessions = ctx.panel.sessions
    result: dict[str, Any] = {
        "hypothesis": name,
        "segment": segment,
        "verdict": None if segment == USED else ex.UNDECIDED,
        "reason": None,
        "window": {"days": 0},
        "prerequisites": None,
    }
    window = segment_window(sessions, segment, spec)
    if window is None:
        result["reason"] = "no_sessions"
        return result
    first, last = window
    days = last - first + 1
    result["window"] = _window_facts(sessions, window)
    if segment != USED and not coverage_only:
        need = MIN_SEGMENT_DAYS[segment]
        delisted = ex.delisted_count(db, sessions[first], sessions[last])
        result["prerequisites"] = {
            "days": days,
            "min_days": need,
            "delisted": delisted,
            "ok": days >= need and delisted > 0,
        }
        if not result["prerequisites"]["ok"]:
            result["reason"] = "segment_too_short" if days < need else "no_delisted"
            return result  # not run (docs 段長下限、先決條件)
    planned = plan(ctx, spec, first, last, keep_rows=not coverage_only)
    result["window"]["signal_days"] = planned.signal_days
    result["coverage"] = planned.coverage
    if coverage_only:
        return result
    mine = pr.simulate(planned.picks, ctx.quote, first, last, spec["hold"], spec["top"])
    population = pr.simulate(
        planned.population, ctx.quote, first, last, spec["hold"], None
    )
    returns = pr.daily_returns(mine.equity)
    others = pr.daily_returns(population.equity)
    taiex = ex._taiex(ctx.panel, first, last)
    excess = {
        POPULATION: pr.excess_metrics([a - b for a, b in zip(returns, others)]),
        TAIEX: pr.excess_metrics(
            [a - b for a, b in zip(returns, taiex) if b is not None]
        ),
    }
    absolute = statistics.fmean(returns) if returns else None
    result["excess"] = excess
    result["absolute"] = {"days": len(returns), "mean": absolute}
    result["curves"] = {
        name: pr.curve_metrics(returns, mine.invested, ex._turnover(mine)),
        POPULATION: pr.curve_metrics(
            others, population.invested, ex._turnover(population)
        ),
        TAIEX: pr.curve_metrics([v for v in taiex if v is not None], [1.0], [0.0]),
    }
    result["win"] = ex.win_rate(mine)
    result["counts"] = {name: dict(mine.counts), POPULATION: dict(population.counts)}
    if segment != USED:
        result["min_t"] = min_t
        result["verdict"] = ex.explore_judge(
            segment, days, True, excess[POPULATION], absolute, min_t
        )
    result["_dates"] = sessions[first : last + 1]
    result["_equity"] = (mine.equity, population.equity)
    result["_positions"] = mine.positions
    result["_rows"] = planned.rows
    return result


# --- V3's data check (rule 6) -----------------------------------------------------


def action_coverage(ctx: Context, last_day: date) -> dict[str, dict[str, int]]:
    """By year to ``last_day``: the stock／ipo instruments with a bar read that
    year, delisted or transferred and all, and how many of them have any
    corporate-action row (of any kind) dated that year."""

    out: dict[str, dict[str, int]] = {}
    for instrument_id, item in ctx.panel.series.items():
        years = {day.year for day in item.dates if day <= last_day}
        actions = ctx.actions.get(instrument_id)
        acted = {day.year for day in actions.dates} if actions else set()
        gone = ctx.statuses.get(instrument_id) in DELISTED_STATUSES
        for year in years:
            row = out.setdefault(
                str(year),
                {"delisted": 0, "delisted_acted": 0, "all": 0, "all_acted": 0},
            )
            row["all"] += 1
            row["all_acted"] += year in acted
            if gone:
                row["delisted"] += 1
                row["delisted_acted"] += year in acted
    return dict(sorted(out.items()))


# --- output -----------------------------------------------------------------------


SEGMENT_NAMES = ex.SEGMENT_NAMES
_pct = ex._pct
_t = ex._t
public = ex.public


def threshold(value: float) -> str:
    """2 → "2", 3.052 → "3.052" (not rounded to 3.05)."""

    return f"{value:.3f}".rstrip("0").rstrip(".")


def _share(count: int, total: int) -> str:
    return _pct(count / total, 1) if total else "—"


def coverage_lines(name: str, coverage: dict[str, Any]) -> list[str]:
    spec = HYPOTHESES[name]
    names = used_features(spec)
    head = ["年", "日數", "母體檔次", *(f"{FEATURE_LABELS[n]} 缺值" for n in names)]
    keys = [key for key, _direction in spec["keys"]]
    if spec["subset"]:
        head += ["子集合檔次", *(f"子集合內 {FEATURE_LABELS[k]} 缺值" for k in keys)]
    if "cash_yield_12m" in names:
        head += ["窗口內有三欄都是 null 的列", "T 日未還原收盤缺值或 ≤ 0"]
    lines = [
        "| " + " | ".join(head) + " |",
        "| --- | " + " | ".join("---:" for _ in head[1:]) + " |",
    ]
    for year, row in sorted(coverage.items()):
        members = row["members"]
        cells = [f"{row['days']:,}", f"{members:,}"]
        cells += [_share(row["missing"].get(n, 0), members) for n in names]
        if spec["subset"]:
            subset = row.get("subset", 0)
            cells.append(f"{subset:,}")
            cells += [_share(row["subset_missing"].get(k, 0), subset) for k in keys]
        if "cash_yield_12m" in names:
            cells += [
                _share(row.get("unknown_rows", 0), members),
                _share(row.get("no_close", 0), members),
            ]
        lines.append(f"| {year} | " + " | ".join(cells) + " |")
    return lines


def action_lines(rows: dict[str, dict[str, int]]) -> list[str]:
    lines = [
        "| 年 | 有日線的下市、轉板股 | 其中當年有除權息列 | 比例 | 有日線的全部股票 | 其中當年有除權息列 | 比例 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for year, row in rows.items():
        lines.append(
            f"| {year} | {row['delisted']:,} | {row['delisted_acted']:,} "
            f"| {_share(row['delisted_acted'], row['delisted'])} | {row['all']:,} "
            f"| {row['all_acted']:,} | {_share(row['all_acted'], row['all'])} |"
        )
    return lines


def _threshold_line(segment: str, min_t: float) -> str:
    return (
        f"- 門檻：超額日均 > 0 且 t ≥ {threshold(min_t)}，且絕對報酬日均 > 0；"
        f"段長下限 {MIN_SEGMENT_DAYS.get(segment, '—')} 日；研究 DB 要有段內已下市公司。"
        f"探索段 t ≥ {threshold(MIN_T)}，驗證段 t ≥ {threshold(VALIDATION_MIN_T)}"
        f"（Bonferroni，累計 {CUMULATIVE} 個：1 − Φ(z)＝0.025 ÷ {CUMULATIVE}，寫死不重算）"
    )


def hypothesis_markdown(result: dict[str, Any], header: dict[str, Any]) -> str:
    name = result["hypothesis"]
    spec = HYPOTHESES[name]
    segment = SEGMENT_NAMES[result["segment"]]
    window = result["window"] or {}
    verdict = result["verdict"] or "只列出、不判定"
    lines = [
        f"# {name} {segment}（round5_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 判定：**{verdict}**"
        + (f"（{REASONS[result['reason']]}，不跑）" if result["reason"] else ""),
        f"- 假設：{spec['direction']}；{spec['label']}；N＝{spec['top']}、K＝{spec['hold']}",
        f"- 登記 commit `{REGISTRATION_COMMIT}`；{DECISION}；"
        f"定義雜湊 `{header['definitions_sha256'][:16]}…`",
        f"- 期間：訊號日 {window.get('first_signal', '—')} 起，有淨值的交易日 "
        f"{window.get('first_session', '—')}～{window.get('last_session', '—')}，共 "
        f"{window.get('days', 0)} 日",
    ]
    if name == "V3":
        lines.append(f"- 限制：{V3_LIMIT}")
    prerequisites = result.get("prerequisites")
    if prerequisites:
        lines.append(
            f"- 先決條件：段長 {prerequisites['days']}／下限 {prerequisites['min_days']} 日；"
            f"段內已下市公司 {prerequisites['delisted']} 檔"
        )
    lines += [
        f"- 副本：最新交易日 {header['copy']['latest']}，alembic `{header['copy']['alembic']}`",
        f"- 重現：`{header['command']}`",
        "",
    ]
    if "excess" in result:
        e, a = result["excess"], result["absolute"]
        lines += [
            "## 數字",
            "",
            "| 量 | 日數 | 日均 | 年化 | t |",
            "| --- | ---: | ---: | ---: | ---: |",
            f"| 超額（對加權指數，只列出） | {e[TAIEX]['days']} | {_pct(e[TAIEX]['mean'], 3)} "
            f"| {_pct(e[TAIEX]['annual'])} | {_t(e[TAIEX]['t'])} |",
            f"| 超額（對母體，判定） | {e[POPULATION]['days']} | {_pct(e[POPULATION]['mean'], 3)} "
            f"| {_pct(e[POPULATION]['annual'])} | {_t(e[POPULATION]['t'])} |",
            f"| 絕對報酬（扣成本，判定） | {a['days']} | {_pct(a['mean'], 3)} "
            f"| {_pct(None if a['mean'] is None else a['mean'] * pr.TRADING_DAYS)} | — |",
            "",
            f"門檻：t ≥ {threshold(result.get('min_t', MIN_T))}。",
            "",
            "## 只列出",
            "",
            "| 組合 | 日數 | 年化報酬 | 年化波動 | 最大回撤 | 平均投入 | 年化換手 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        labels = {name: name, POPULATION: "母體（基準）", TAIEX: "加權指數（價格指數）"}
        for key in (TAIEX, name, POPULATION):
            c = result["curves"][key]
            held = (
                "| — | — |"
                if key == TAIEX
                else f"| {_pct(c.get('invested'), 1)} | {lib.num(c.get('turnover'), 1)} |"
            )
            lines.append(
                f"| {labels[key]} | {c['days']} | {_pct(c.get('annual'))} "
                f"| {_pct(c.get('volatility'))} | {_pct(c.get('max_drawdown'))} " + held
            )
        w = result["win"]
        counts = result["counts"][name]
        lines += [
            "",
            f"勝率（買進的每一筆，期末未賣以最後收盤計）：{_pct(w['rate'], 1)}"
            f"（{w['won']:,}／{w['bought']:,}，期末未賣 {w['unsold']:,}）。",
            f"成交計數：買進 {counts.get('bought', 0):,}、漲停買不到 "
            f"{counts.get('limit_up', 0):,}、不可交易 {counts.get('not_tradable', 0):,}、"
            f"跌停順延 {counts.get('limit_down', 0):,}、停牌／缺日線順延 "
            f"{counts.get('sale_held', 0):,}、期末未賣 {counts.get('unsold', 0):,}。",
            "",
        ]
    if result.get("coverage"):
        lines += [
            "## 資料覆蓋（不含報酬）",
            "",
            *coverage_lines(name, result["coverage"]),
            "",
        ]
    return "\n".join(lines)


TRADE_FIELDS = (
    "account",
    "exchange",
    "symbol",
    "bought",
    "due",
    "sold",
    "how",
    "cost",
    "proceeds",
)


def write_hypothesis(out: Path, result: dict[str, Any], header: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    name = result["hypothesis"]
    spec = HYPOTHESES[name]
    body = {
        **{
            key: header[key]
            for key in ("tool", "version", "design", "definitions_sha256")
        },
        "label": spec["label"],
        "direction": spec["direction"],
        "parameters": {
            key: value
            for key, value in spec.items()
            if key not in ("label", "direction")
        },
        **public(result),
    }
    (out / "tables.json").write_text(
        json.dumps(body, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (out / "summary.md").write_text(
        hypothesis_markdown(result, header), encoding="utf-8"
    )
    if "_dates" not in result:
        return
    panel = header["_panel"]
    mine, population = result["_equity"]
    with (out / "equity.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", name, POPULATION, "taiex_close"])
        for at, day in enumerate(result["_dates"]):
            writer.writerow(
                [
                    day.isoformat(),
                    f"{mine[at]:.8f}",
                    f"{population[at]:.8f}",
                    panel.index_close.get(day),
                ]
            )
    fields = ["signal_date", "rank", "exchange", "symbol", *used_features(spec), "tie"]
    with (out / "picks.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(result["_rows"])
    sessions = panel.sessions
    with (out / "trades.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(TRADE_FIELDS)
        for position in result["_positions"]:
            exchange, symbol, _ = panel.symbols.get(
                position.instrument_id, ("", "", "")
            )
            writer.writerow(
                [
                    position.account,
                    exchange,
                    symbol,
                    sessions[position.bought].isoformat(),
                    sessions[position.due].isoformat()
                    if position.due < len(sessions)
                    else "",
                    sessions[position.sold].isoformat()
                    if position.sold is not None
                    else "",
                    position.how,
                    f"{position.cost:.10f}",
                    "" if position.proceeds is None else f"{position.proceeds:.10f}",
                ]
            )


def overview_markdown(report: dict[str, Any], sha256: str) -> str:
    segment = report["segment"]
    stage = SEGMENT_NAMES[segment]
    lines = [
        f"explore.json 的 sha256：`{sha256}`",
        "",
        f"# 新策略探索 第 {report['round']} 輪 {stage}（round5_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「第五輪：V1～V3」）：{DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        _threshold_line(segment, report["min_t"]),
        f"- V3 的限制：{V3_LIMIT}",
        f"- 副本：最新交易日 {report['copy']['latest']}，alembic `{report['copy']['alembic']}`",
        f"- 讀取的資料到 {report['read_until']}（之後的列不讀）",
        f"- 耗時 {report.get('elapsed_seconds', 0):.0f} 秒，峰值記憶體 "
        f"{lib.num(report.get('peak_memory_gb'), 2)} GB",
        f"- 重現：`{report['command']}`",
    ]
    if segment == EXPLORATION:
        lines.append("- 本次跑的假設：" + "、".join(report.get("selected") or []))
    if segment == VALIDATION:
        lines.append(
            f"- 前瞻觀察：超額日均 > 0 但 t < {threshold(report['min_t'])}，且絕對報酬日均 > 0；"
            "只當紀錄，不算通過、不進產品"
        )
        source = report["exploration"]
        lines.append(f"- 探索段報告：{source['url']}（sha256 `{source['sha256']}`）")
    lines += [
        "",
        "## 判定",
        "",
        "| 代號 | 方向 | N／K | 日數 | 對加權指數超額日均 | t | 對母體超額日均 | t | 絕對報酬日均 | 判定 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for name, row in report["hypotheses"].items():
        spec = HYPOTHESES[name]
        e = row.get("excess") or {}
        x = row.get("taiex_excess") or {}
        verdict = row["verdict"] + (
            f"（{REASONS[row['reason']]}）" if row.get("reason") else ""
        )
        lines.append(
            f"| {name} | {spec['direction']} | {spec['top']}／{spec['hold']} | {row['days']} "
            f"| {_pct(x.get('mean'), 3)} | {_t(x.get('t'))} "
            f"| {_pct(e.get('mean'), 3)} | {_t(e.get('t'))} "
            f"| {_pct(row.get('absolute_mean'), 3)} | {verdict} |"
        )
    if report.get("used"):
        lines += [
            "",
            "## 已用段（驗證通過的假設，只列出、不判定）",
            "",
            "| 代號 | 日數 | 對加權指數超額日均 | t | 對母體超額日均 | t | 絕對報酬日均 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for name, row in report["used"].items():
            e = row.get("excess") or {}
            x = row.get("taiex_excess") or {}
            lines.append(
                f"| {name} | {row['days']} | {_pct(x.get('mean'), 3)} | {_t(x.get('t'))} "
                f"| {_pct(e.get('mean'), 3)} | {_t(e.get('t'))} "
                f"| {_pct(row.get('absolute_mean'), 3)} |"
            )
    lines += [
        "",
        "各假設的數字、只列出的指標與資料覆蓋見 `<代號>/summary.md`。",
        "",
    ]
    return "\n".join(lines)


def coverage_markdown(body: dict[str, Any]) -> str:
    lines = [
        f"# 新策略探索 第 {body['round']} 輪 V1～V3 資料覆蓋（探索段，不含報酬）",
        "",
        f"- round5_research 第 {VERSION} 版；定義雜湊 `{body['definitions_sha256']}`",
        f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}，"
        f"alembic `{body['copy']['alembic']}`",
        f"- 重現：`{body['command']}`",
        "- 缺值比例的分母是母體檔次（每個訊號日的母體加總）；子集合內的比例分母是子集合檔次",
        "- 各欄不互斥：V3 的「三欄都是 null」與「未還原收盤缺值」各自計數，"
        "一檔可同時落在兩欄，總缺值是「近 12 個月現金殖利率 缺值」那一欄",
        "- 各假設用自己的訊號日（起日寫在各段標題）",
        "",
    ]
    for name, row in body["hypotheses"].items():
        window = row["window"] or {}
        lines += [
            f"## {name}（訊號日 {window.get('first_signal', '—')} 起，{window.get('days', 0)} 日）",
            "",
            *coverage_lines(name, row["coverage"]),
            "",
        ]
    lines += [
        "## V3 的資料檢查：當年有除權息列的比例",
        "",
        "下市、轉板股是 `status` 為 `delisted` 或 `transferred` 的 `stock`／`ipo`；"
        "「當年有日線」是工具讀到的日線（已扣日線排除清單）；"
        "除權息列不分種類（含只配股、分割與三欄都是 null 的列）。"
        f"V3 的第一個訊號日是 {HYPOTHESES['V3']['start'][1].isoformat()} 起第一個交易日。"
        "上櫃除權息 2007-12 起才有來源，2008 以前的上櫃列本來就少，不算異常。",
        "",
        *action_lines(body["actions"]),
        "",
    ]
    return "\n".join(lines)


def _row(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "verdict": result["verdict"],
        "reason": result["reason"],
        "days": (result["window"] or {}).get("days", 0),
        "taiex_excess": (result.get("excess") or {}).get(TAIEX),
        "excess": (result.get("excess") or {}).get(POPULATION),
        "absolute_mean": (result.get("absolute") or {}).get("mean"),
        "prerequisites": result.get("prerequisites"),
    }


# --- the runs ---------------------------------------------------------------------


def _header(db: Path, segment: str, command: str, read_until: date) -> dict[str, Any]:
    return {
        "tool": TOOL,
        "version": VERSION,
        "design": DESIGN,
        "registration_commit": REGISTRATION_COMMIT,
        "segment": segment,
        "round": ROUND,
        "round_size": ROUND_SIZE,
        "cumulative": CUMULATIVE,
        "validation_min_t": VALIDATION_MIN_T,
        "definitions_sha256": definitions_sha256(),
        "tool_commit": ex.tool_commit(),
        "command": command,
        "copy": pr.copy_facts(db),
        "read_until": read_until.isoformat(),
    }


def _finish(out: Path, report: dict[str, Any], started: float) -> str:
    report["elapsed_seconds"] = time.monotonic() - started
    report["peak_memory_gb"] = lib._load("backtest_research").peak_memory_gb()
    path = out / "explore.json"
    path.write_text(
        json.dumps(public(report), ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    sha256 = ex.file_sha256(path)
    (out / "explore.md").write_text(overview_markdown(report, sha256), encoding="utf-8")
    return sha256


def load_from(segment: str) -> date:
    """The first day read: the copy's start for the exploration (as
    ``explore_research``), the warm-up before a later segment."""

    first_day = SEGMENTS[segment][0]
    if first_day is None:
        return LOAD_FROM
    return first_day - timedelta(days=WARMUP_CALENDAR_DAYS)


def run_exploration(
    db: Path,
    out: Path,
    names: list[str] | tuple[str, ...] = (),
    command: str = "",
    coverage_only: bool = False,
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, Any]:
    """``names`` on the exploration segment (every hypothesis for the
    coverage); nothing after its end read."""

    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    end = SEGMENTS[EXPLORATION][1]
    ctx = load(db, load_from(EXPLORATION), end, out / RAW_DIR_NAME)
    header = _header(db, EXPLORATION, command, end)
    header["_panel"] = ctx.panel
    if coverage_only:
        coverage = {}
        for name in HYPOTHESES:
            result = run_one(ctx, db, name, EXPLORATION, coverage_only=True)
            coverage[name] = {
                "window": result["window"],
                "coverage": result.get("coverage", {}),
            }
            progress(f"{name} coverage")
        body = {
            **public(header),
            "coverage_only": True,
            "hypotheses": coverage,
            "actions": action_coverage(ctx, end),
        }
        (out / "coverage.json").write_text(
            json.dumps(body, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        (out / "coverage.md").write_text(coverage_markdown(body), encoding="utf-8")
        return {"out": str(out.resolve()), "coverage_only": True}
    report = {**header, "min_t": MIN_T, "selected": list(names), "hypotheses": {}}
    for name in names:
        t0 = time.monotonic()
        result = run_one(ctx, db, name, EXPLORATION)
        write_hypothesis(out / name, result, header)
        report["hypotheses"][name] = {
            **_row(result),
            "coverage": result.get("coverage"),
        }
        progress(f"{name}: {result['verdict']} ({time.monotonic() - t0:.1f}s)")
    sha256 = _finish(out, report, started)
    # Only a finished run with its report written counts as the one run (#721).
    commit, finished = ex.tool_commit(), ex._now()
    mine = [
        {
            "hypothesis": name,
            "tool": TOOL,
            "round": ROUND,
            "segment": EXPLORATION,
            "version": VERSION,
            "status": "finished",
            "finished_at": finished,
            "report_sha256": sha256,
            "tool_commit": commit,
            "definitions_sha256": report["definitions_sha256"],
            "verdict": report["hypotheses"][name]["verdict"],
        }
        for name in names
    ]
    ledger = ex.ledger_path(db)
    ex.write_ledger(ledger, ex.read_ledger(ledger) + mine)
    ex.write_ledger(out / "ledger-entries.json", mine)
    return {
        "out": str(out.resolve()),
        "segment": EXPLORATION,
        "sha256": sha256,
        "verdicts": {
            name: row["verdict"] for name, row in report["hypotheses"].items()
        },
    }


def run_validation(
    db: Path,
    out: Path,
    names: list[str],
    source: dict[str, str],
    command: str = "",
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, Any]:
    """``names`` on the validation segment, once: the ledger first, then the data."""

    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    commit = ex.tool_commit()
    ledger = ex.ledger_path(db)
    entries = ex.read_ledger(ledger)
    for name in names:
        entries.append(
            {
                "hypothesis": name,
                "tool": TOOL,
                "round": ROUND,
                "segment": VALIDATION,
                "version": VERSION,
                "status": "started",
                "started_at": ex._now(),
                "report_sha256": source["sha256"],
                "url": source["url"],
                "tool_commit": commit,
                "definitions_sha256": definitions_sha256(),
            }
        )
    ex.write_ledger(ledger, entries)  # before any validation data is read
    end = SEGMENTS[VALIDATION][1]
    ctx = load(db, load_from(VALIDATION), end, out / RAW_DIR_NAME)
    header = _header(db, VALIDATION, command, end)
    header["_panel"] = ctx.panel
    min_t = VALIDATION_MIN_T
    report = {**header, "min_t": min_t, "exploration": source, "hypotheses": {}}
    for name in names:
        result = run_one(ctx, db, name, VALIDATION, min_t=min_t)
        write_hypothesis(out / name, result, header)
        report["hypotheses"][name] = _row(result)
        progress(f"{name}: {result['verdict']}")
    for entry in entries:
        if (
            entry.get("tool") == TOOL
            and entry["status"] == "started"
            and entry["hypothesis"] in report["hypotheses"]
        ):
            entry["status"] = "finished"
            entry["finished_at"] = ex._now()
            entry["verdict"] = report["hypotheses"][entry["hypothesis"]]["verdict"]
    ex.write_ledger(ledger, entries)
    passed = [
        name for name in names if report["hypotheses"][name]["verdict"] == ex.PASSED
    ]
    if passed:  # the used segment only for the passed ones
        used_ctx = load(db, load_from(USED), SEGMENTS[USED][1], out / RAW_DIR_NAME)
        used_header = {**header, "_panel": used_ctx.panel}
        report["used"] = {}
        for name in passed:
            result = run_one(used_ctx, db, name, USED)
            write_hypothesis(out / name / USED, result, used_header)
            report["used"][name] = _row(result)
    sha256 = _finish(out, report, started)
    mine = [
        entry
        for entry in entries
        if entry.get("tool") == TOOL
        and entry["hypothesis"] in names
        and entry.get("segment") == VALIDATION
    ]
    ex.write_ledger(out / "ledger-entries.json", mine)
    return {
        "out": str(out.resolve()),
        "segment": VALIDATION,
        "sha256": sha256,
        "verdicts": {
            name: row["verdict"] for name, row in report["hypotheses"].items()
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="round5_research.py", description=__doc__)
    parser.add_argument(
        "--db", required=True, help="the research DB (/research/stock.db)"
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--segment", required=True, choices=STAGES)
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help="exploration only: the share of missing values per year and V3's "
        "data check, no return",
    )
    parser.add_argument(
        "--hypotheses",
        help="exploration (required, not with --coverage-only): V1, V2, V3 or some "
        "of them, comma separated; each runs once per tool version",
    )
    parser.add_argument(
        "--exploration-report", help="validation: the exploration explore.json"
    )
    parser.add_argument(
        "--exploration-sha256",
        help="validation: the sha256 quoted in the public comment",
    )
    parser.add_argument(
        "--exploration-url", help="validation: the public comment or pr-assets link"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = _parser()
    args = parser.parse_args(argv)
    gate = (args.exploration_report, args.exploration_sha256, args.exploration_url)
    if args.segment == EXPLORATION and any(gate):
        parser.error("--exploration-* go with --segment validation only")
    if args.segment == VALIDATION and args.coverage_only:
        parser.error("--coverage-only goes with --segment exploration only")
    if args.hypotheses is not None and (
        args.segment == VALIDATION or args.coverage_only
    ):
        parser.error(
            "--hypotheses goes with --segment exploration only, not --coverage-only"
        )
    db = Path(args.db)
    problems = lib._load("exit_research").refusals(db, args.min_free_gb)
    names: list[str] = []
    if args.segment == EXPLORATION and not args.coverage_only:
        chosen, names = ex.exploration_problems(
            db, args.hypotheses, HYPOTHESES, VERSION
        )
        problems = [*problems, *chosen]
    if problems:
        print(json.dumps({"refused": problems}, ensure_ascii=False))
        return 2
    command = "python tools/research/round5_research.py " + " ".join(argv)
    progress = lambda text: print(text, file=sys.stderr, flush=True)  # noqa: E731
    if args.segment == EXPLORATION:
        line = run_exploration(
            db, Path(args.out), names, command, args.coverage_only, progress=progress
        )
    else:
        problems, names, _report = ex.validation_problems(
            db, *gate, HYPOTHESES, DESIGN, definitions_sha256()
        )
        if problems:
            print(json.dumps({"refused": problems}, ensure_ascii=False))
            return 2
        line = run_validation(
            db,
            Path(args.out),
            names,
            {
                "sha256": args.exploration_sha256.strip().lower(),
                "url": args.exploration_url,
            },
            command,
            progress=progress,
        )
    print(json.dumps(line, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
