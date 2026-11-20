"""Round 6 of the new-strategy exploration: W1～W4 (#903).

docs/spec/evidence.md 第六輪：W1～W4 and 第六輪實作釋義: the hypotheses were
registered (commit ``6f6142d4``, #898, decision 7049972634) before anyone ran a
tool on the backfilled history.  Nothing here is a command-line option: a
change of a definition is a new code.

They are not in ``explore_research.HYPOTHESES`` nor ``round5_research``: their
``definitions_sha256`` hash the whole table, so adding them would make the
validation refuse the exploration reports already run.  The engine, the
population, ``explore_judge``, the gate, the ledgers, the "small first" order
(``round5_research.order_key``) and the loading of the corporate actions
(``research_report.load_actions``) are imported; new here are only
``amihud_60``, ``reversal_720_240``, ``expected_ex_28`` and ``season_5y``.

Each signal date T (after its close, only T's data and before):

- W1: ``amihud_60`` high first — the mean of the 60 ``|r_i| / turnover_i``,
  i = at − 59 .. at, r on the adjusted closes, the turnover the official
  unadjusted one; missing with fewer than 61 bars, a close missing or ≤ 0, a
  suspended bar among the 61, or among the 60 a ``turnover_status`` not
  ``available`` or a turnover ≤ 0.  N 20, K 60.
- W2: ``reversal_720_240`` small first — ``close[at − 240] / close[at − 720]
  − 1`` on the stock's own bars, suspended ones counted; missing with fewer
  than 721 bars or a close missing or ≤ 0.  N 20, K 60.
- W3: ``expected_ex_28`` high first — 1 when a row with ``cash_dividend > 0``
  has ``T − 365 < action_date <= T − 365 + 28`` (calendar days), else 0 (a
  null or zero cash dividend is 0); never missing, ties by the hash fill the
  20.  N 20, K 20.
- W4: ``season_5y`` high first — the mean of r_k = P(b_k) / P(a_k) − 1, k =
  1..5, a_k = T − 365k, b_k = a_k + 28; P(d) the adjusted close of the stock's
  last bar dated d or before, no more than 7 calendar days before d; missing
  if any P is.  N 20, K 20.

A missing key is last whether high or low first; ties by
``portfolio_research.tie_break``.  ``portfolio_research.simulate`` (K accounts,
1/20 of the account's cash each) trades; the benchmark is the same engine over
the day's whole population.  ``explore_research.explore_judge`` judges with
t ≥ 2 on the exploration and the fixed Bonferroni t ≥ 3.102 (26 hypotheses)
on the validation.  The segments, floors, public check, the gate (the
exploration once per version, the validation once after a published
exploration report, the ledger writable before anything is read) and the
ledgers (``explore-ledger.json`` beside the DB and the repository's
``tools/research/explore_ledger.json``, each entry with
``"tool": "round6_research"``) are ``explore_research``'s.

Every segment reads the copy from its start (to the segment's end): W2 needs
721 of the stock's own bars and W4 five years of calendar days, more than the
730 calendar days of warm-up the other tools read before a later segment.
``--coverage-only`` writes the share of missing values per year and W3's
counts, no return at all.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
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
import portfolio_research as pr  # noqa: E402
import round5_research as r5  # noqa: E402

VERSION = 1
DESIGN = "903"
TOOL = "round6_research"
REGISTRATION_COMMIT = "6f6142d4"
DECISION = "https://github.com/YiCheng0608/stock-lab/issues/898#issuecomment-7049972634"
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
SEGMENTS = dict(ex.SEGMENTS)
MIN_SEGMENT_DAYS = dict(ex.MIN_SEGMENT_DAYS)
MIN_T = ex.MIN_T  # the exploration's t ≥ 2
# docs 第六輪 門檻: 1 − Φ(z) = 0.025 ÷ 26, z = 3.1019 to the 3rd decimal; fixed,
# not computed when run.
VALIDATION_MIN_T = 3.102
ROUND = 6
ROUND_SIZE = 4
CUMULATIVE = 26  # X1～X8, S1～S3, R1～R2, M1～M2, C1～C4, V1～V3, W1～W4; H1 apart
LOAD_FROM = ex.LOAD_FROM  # every segment reads the copy from its start
MIN_LOTS = lib.DEFAULT_MIN_LOTS
RAW_DIR_NAME = ex.RAW_DIR_NAME
POPULATION = pr.POPULATION
TAIEX = pr.TAIEX

HIGH, LOW = r5.HIGH, r5.LOW
AMIHUD_WINDOW = 60  # returns, of 61 closes
REVERSAL_RECENT, REVERSAL_FAR = 240, 720
EX_YEAR_DAYS = 365  # T − 365 < action_date <= T − 365 + 28
EX_AHEAD_DAYS = 28
SEASON_YEARS = 5
SEASON_YEAR_DAYS = 365
SEASON_SPAN_DAYS = 28
SEASON_STALE_DAYS = 7  # P(d): the last bar no more than 7 calendar days before d
# The OTC bars from 2007-04-23 to 2007-11-30 are not read (bar_exclusions.json):
# W1 and W2 count from the OTC 2007-12-03, as round 5.
OTC_ANCHOR = r5.OTC_ANCHOR

# The registration (docs 第六輪：W1～W4), word for word.  ``start`` as
# ``explore_research``: ("session", anchor, n) is the n-th session counting the
# anchor (or the first session after it) as the first; ("date", d) the first
# session from d.  ``keys``: (feature, HIGH | LOW), a missing value last either
# way, ties by ``portfolio_research.tie_break``.
HYPOTHESES: dict[str, dict[str, Any]] = {
    "W1": {
        "direction": "非流動性",
        "label": "`amihud_60`（近 60 日「|日報酬| ÷ 當日成交金額」的平均）大者先",
        "rule": "daily",
        "subset": None,
        "keys": (("amihud_60", HIGH),),
        "top": 20,
        "hold": 60,
        "start": ("session", OTC_ANCHOR, 61),
    },
    "W2": {
        "direction": "長期反轉",
        "label": "`reversal_720_240`（T 往前第 720 根到第 240 根的報酬）小者先",
        "rule": "daily",
        "subset": None,
        "keys": (("reversal_720_240", LOW),),
        "top": 20,
        "hold": 60,
        "start": ("session", OTC_ANCHOR, 721),
    },
    "W3": {
        "direction": "股利時點",
        "label": "`expected_ex_28`（一年前的接下來 4 週內有除息是 1，否則 0）大者先",
        "rule": "daily",
        "subset": None,
        "keys": (("expected_ex_28", HIGH),),
        "top": 20,
        "hold": 20,
        "start": ("date", date(2010, 1, 4)),
    },
    "W4": {
        "direction": "季節性",
        "label": "`season_5y`（過去 1～5 年同一段 4 週的報酬平均）大者先",
        "rule": "daily",
        "subset": None,
        "keys": (("season_5y", HIGH),),
        "top": 20,
        "hold": 20,
        "start": ("date", date(2012, 12, 3)),
    },
}
OTHER_COMPARISONS = ex.OTHER_COMPARISONS
REASONS = dict(ex.REASONS)
VOLATILE_KEYS = ex.VOLATILE_KEYS
LIMITS = {
    "W1": "成交金額是名目值，不同年份的同一個金額不等值；排序只在同一天之間比，不換算",
    "W3": "引擎用還原價，報酬含全額現金股利，不扣股利所得稅與二代健保補充保費，對個人投資人會高估",
}


def definitions() -> dict[str, Any]:
    return {
        "version": VERSION,
        "design": DESIGN,
        "hypotheses": HYPOTHESES,
        "features": {
            "amihud_60": {
                "returns": AMIHUD_WINDOW,
                "closes": "Series.close at-60..at",
                "ratio": "mean of |r_i| / market_bars.turnover_i, i = at-59..at",
                "missing": "fewer than 61 bars; a close missing or <= 0; a suspended "
                "bar in at-60..at; in at-59..at a turnover_status not available "
                "or a turnover <= 0",
            },
            "reversal_720_240": {
                "value": "Series.close[at-240] / Series.close[at-720] - 1",
                "bars": [REVERSAL_RECENT, REVERSAL_FAR],
                "missing": "fewer than 721 bars; either close missing or <= 0",
            },
            "expected_ex_28": {
                "window": f"T - {EX_YEAR_DAYS} < action_date <= T - {EX_YEAR_DAYS} "
                f"+ {EX_AHEAD_DAYS} (calendar days)",
                "one": "a row with cash_dividend > 0",
                "zero": "otherwise (null or 0 cash_dividend, no row)",
                "missing": None,
            },
            "season_5y": {
                "years": SEASON_YEARS,
                "a_k": f"T - {SEASON_YEAR_DAYS}k",
                "b_k": f"a_k + {SEASON_SPAN_DAYS}",
                "price": "Series.close of the last bar dated <= d, "
                f"d - date <= {SEASON_STALE_DAYS} calendar days",
                "missing": "any P missing or <= 0",
            },
            "turnover": ex.TURNOVER_AVAILABLE,
        },
        "order": "missing last for high and low first; ties sha256(<T>:<instrument_id>)",
        "segments": SEGMENTS,
        "min_segment_days": MIN_SEGMENT_DAYS,
        "min_t": MIN_T,
        "validation_min_t": VALIDATION_MIN_T,
        "round": [ROUND, ROUND_SIZE, CUMULATIVE],
        "costs": [pr.SLIPPAGE, pr.FEE, pr.TAX],
        "min_lots": MIN_LOTS,
        "load_from": LOAD_FROM,
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
    """One instrument's corporate actions by ``action_date`` and each row's
    ``cash_dividend`` as stored (None when null)."""

    dates: list[date] = field(default_factory=list)
    cash: list[float | None] = field(default_factory=list)


def actions_of(rows: list[Any]) -> Actions:
    out = Actions()
    for action in sorted(rows, key=lambda row: row.action_date):
        out.dates.append(action.action_date)
        cash = action.cash_dividend
        out.cash.append(None if cash is None else float(cash))
    return out


@dataclass
class Context:
    """``explore_research``'s context (the market, the turnovers, the quotes)
    plus the actions W3 reads."""

    base: ex.Context
    actions: dict[int, Actions] = field(default_factory=dict)

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
    return ctx


# --- features ---------------------------------------------------------------------


def amihud_60(ctx: Context, item: lib.Series, at: int) -> float | None:
    """The mean of the 60 ``|r_i| / turnover_i`` (第六輪 W1)."""

    if at < AMIHUD_WINDOW:
        return None
    first = at - AMIHUD_WINDOW
    if item.suspended[at + 1] != item.suspended[first]:
        return None  # a suspended bar in first .. at (第六輪實作釋義)
    closes = item.close[first : at + 1]
    if not all(close > 0 for close in closes):  # NaN fails too
        return None
    turnover = ctx.base.turnover.get(item.instrument_id)
    if turnover is None:
        return None
    total = 0.0
    for k in range(1, len(closes)):
        value = turnover[first + k]  # NaN: not available (explore_research)
        if not (value > 0):
            return None
        total += abs(closes[k] / closes[k - 1] - 1.0) / value
    return total / AMIHUD_WINDOW


def reversal_720_240(_ctx: Context, item: lib.Series, at: int) -> float | None:
    """``close[at − 240] / close[at − 720] − 1``, suspended bars counted."""

    if at < REVERSAL_FAR:
        return None
    far, recent = item.close[at - REVERSAL_FAR], item.close[at - REVERSAL_RECENT]
    if not (far > 0 and recent > 0):
        return None
    return recent / far - 1.0


@dataclass(frozen=True)
class Expected:
    value: float
    null_cash: bool  # a row in the window with cash_dividend null


def expected_parts(ctx: Context, item: lib.Series, at: int) -> Expected:
    day = item.dates[at]
    actions = ctx.actions.get(item.instrument_id)
    if actions is None:
        return Expected(0.0, False)
    year_ago = day - timedelta(days=EX_YEAR_DAYS)
    lo = bisect_right(actions.dates, year_ago)
    hi = bisect_right(actions.dates, year_ago + timedelta(days=EX_AHEAD_DAYS))
    window = actions.cash[lo:hi]
    one = any(cash is not None and cash > 0 for cash in window)
    return Expected(1.0 if one else 0.0, any(cash is None for cash in window))


def expected_ex_28(ctx: Context, item: lib.Series, at: int) -> float | None:
    return expected_parts(ctx, item, at).value


def price_on(item: lib.Series, day: date) -> float | None:
    """P(d): the adjusted close of the last bar dated ``day`` or before, if it
    is no more than 7 calendar days before ``day``."""

    at = bisect_right(item.dates, day) - 1
    if at < 0 or (day - item.dates[at]).days > SEASON_STALE_DAYS:
        return None
    close = item.close[at]
    return close if close > 0 else None  # NaN fails too


def season_5y(_ctx: Context, item: lib.Series, at: int) -> float | None:
    """The mean of the five ``P(b_k) / P(a_k) − 1`` (第六輪 W4)."""

    day = item.dates[at]
    returns = []
    for k in range(1, SEASON_YEARS + 1):
        a = day - timedelta(days=SEASON_YEAR_DAYS * k)
        start, end = (
            price_on(item, a),
            price_on(item, a + timedelta(days=SEASON_SPAN_DAYS)),
        )
        if start is None or end is None:
            return None
        returns.append(end / start - 1.0)
    return sum(returns) / SEASON_YEARS


FEATURES: dict[str, Callable[[Context, lib.Series, int], float | None]] = {
    "amihud_60": amihud_60,
    "reversal_720_240": reversal_720_240,
    "expected_ex_28": expected_ex_28,
    "season_5y": season_5y,
}
FEATURE_LABELS = {
    "amihud_60": "非流動性比率",
    "reversal_720_240": "第 720～240 根報酬",
    "expected_ex_28": "預期除息",
    "season_5y": "過去 5 年同期報酬",
}


def used_features(spec: dict[str, Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(name for name, _direction in spec["keys"]))


# --- the order --------------------------------------------------------------------


order_key = r5.order_key


@dataclass
class Ranked:
    rows: list[tuple[int, dict[str, float | None], str]]
    missing: Counter
    ones: int = 0  # W3: members with the key 1
    null_cash: int = 0  # W3: members with a null cash_dividend row in the window


def rank(
    ctx: Context,
    spec: dict[str, Any],
    day: date,
    members: list[tuple[lib.Series, int]],
) -> Ranked:
    """The day's members in the hypothesis's order and the counts of missing
    values."""

    names = used_features(spec)
    out = Ranked([], Counter())
    rows = []
    for item, at in members:
        values: dict[str, float | None] = {}
        for name in names:
            if name == "expected_ex_28":
                parts = expected_parts(ctx, item, at)
                values[name] = parts.value
                out.ones += parts.value == 1.0
                out.null_cash += parts.null_cash
            else:
                values[name] = FEATURES[name](ctx, item, at)
            out.missing[name] += values[name] is None
        rows.append((item.instrument_id, values, pr.tie_break(day, item.instrument_id)))
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
    coverage: dict[str, Any],
    spec: dict[str, Any],
    day: date,
    members: int,
    r: Ranked,
) -> None:
    year = coverage.setdefault(str(day.year), {"days": 0, "members": 0, "missing": {}})
    year["days"] += 1
    year["members"] += members
    for name in used_features(spec):
        year["missing"][name] = year["missing"].get(name, 0) + r.missing[name]
    if "expected_ex_28" in used_features(spec):
        year["ones"] = year.get("ones", 0) + r.ones
        year["null_cash"] = year.get("null_cash", 0) + r.null_cash
        top = r.rows[: spec["top"]]
        year["picked"] = year.get("picked", 0) + len(top)
        year["picked_ones"] = year.get("picked_ones", 0) + sum(
            1 for row in top if row[1]["expected_ex_28"] == 1.0
        )


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
    result["window"] = r5._window_facts(sessions, window)
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


# --- output -----------------------------------------------------------------------


SEGMENT_NAMES = ex.SEGMENT_NAMES
_pct = ex._pct
_t = ex._t
public = ex.public
threshold = r5.threshold
_share = r5._share


def _mean(count: int, days: int) -> str:
    return lib.num(count / days, 2) if days else "—"


def coverage_lines(name: str, coverage: dict[str, Any]) -> list[str]:
    spec = HYPOTHESES[name]
    names = used_features(spec)
    head = ["年", "日數", "母體檔次", *(f"{FEATURE_LABELS[n]} 缺值" for n in names)]
    w3 = "expected_ex_28" in names
    if w3:
        head += [
            "母體中鍵值是 1 的平均檔數",
            "窗口內有 cash_dividend 是 null 的列的檔次",
            "其日均檔數",
        ]
    lines = [
        "| " + " | ".join(head) + " |",
        "| --- | " + " | ".join("---:" for _ in head[1:]) + " |",
    ]
    for year, row in sorted(coverage.items()):
        members, days = row["members"], row["days"]
        cells = [f"{days:,}", f"{members:,}"]
        cells += [_share(row["missing"].get(n, 0), members) for n in names]
        if w3:
            cells += [
                _mean(row.get("ones", 0), days),
                f"{row.get('null_cash', 0):,}",
                _mean(row.get("null_cash", 0), days),
            ]
        lines.append(f"| {year} | " + " | ".join(cells) + " |")
    return lines


def picked_lines(coverage: dict[str, Any]) -> list[str]:
    """W3's listed count: the picks with the key 1, a day's mean by year."""

    lines = [
        "| 年 | 日數 | 選入檔次 | 其中鍵值是 1 | 每日平均檔數 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for year, row in sorted(coverage.items()):
        lines.append(
            f"| {year} | {row['days']:,} | {row.get('picked', 0):,} "
            f"| {row.get('picked_ones', 0):,} | {_mean(row.get('picked_ones', 0), row['days'])} |"
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
        f"# {name} {segment}（round6_research 第 {VERSION} 版，#{DESIGN}）",
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
    if name in LIMITS:
        lines.append(f"- 限制：{LIMITS[name]}")
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
        if name == "W3":
            lines += [
                "## 另列：每年選入的股票中鍵值是 1 的平均檔數（只列出、不判定）",
                "",
                *picked_lines(result.get("coverage") or {}),
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


TRADE_FIELDS = r5.TRADE_FIELDS


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
        f"# 新策略探索 第 {report['round']} 輪 {stage}（round6_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「第六輪：W1～W4」）：{DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        _threshold_line(segment, report["min_t"]),
        *(f"- {name} 的限制：{text}" for name, text in LIMITS.items()),
        f"- 副本：最新交易日 {report['copy']['latest']}，alembic `{report['copy']['alembic']}`",
        f"- 讀取的資料到 {report['read_until']}（之後的列不讀；從副本起點讀，供 W2、W4 的特徵）",
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
        f"# 新策略探索 第 {body['round']} 輪 W1～W4 資料覆蓋（探索段，不含報酬）",
        "",
        f"- round6_research 第 {VERSION} 版；定義雜湊 `{body['definitions_sha256']}`",
        f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}，"
        f"alembic `{body['copy']['alembic']}`",
        f"- 重現：`{body['command']}`",
        "- 缺值比例的分母是母體檔次（每個訊號日的母體加總）",
        "- W3 的鍵值沒有缺值；「母體中鍵值是 1 的平均檔數」是當年每個訊號日的檔數的平均，"
        "「窗口內有 cash_dividend 是 null 的列」看的是 W3 的窗口（T − 365 < action_date ≤ T − 337），"
        "這種列鍵值算 0",
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
    return "\n".join(lines)


_row = r5._row


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
    ctx = load(db, LOAD_FROM, end, out / RAW_DIR_NAME)
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
        body = {**public(header), "coverage_only": True, "hypotheses": coverage}
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
    ctx = load(db, LOAD_FROM, end, out / RAW_DIR_NAME)
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
        used_ctx = load(db, LOAD_FROM, SEGMENTS[USED][1], out / RAW_DIR_NAME)
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
    parser = argparse.ArgumentParser(prog="round6_research.py", description=__doc__)
    parser.add_argument(
        "--db", required=True, help="the research DB (/research/stock.db)"
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--segment", required=True, choices=STAGES)
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help="exploration only: the share of missing values per year and W3's "
        "counts, no return",
    )
    parser.add_argument(
        "--hypotheses",
        help="exploration (required, not with --coverage-only): W1, W2, W3, W4 or "
        "some of them, comma separated; each runs once per tool version",
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
    command = "python tools/research/round6_research.py " + " ".join(argv)
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
