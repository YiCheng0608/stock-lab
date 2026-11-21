"""Round 8 of the new-strategy exploration: Z1～Z4 (#918).

docs/spec/evidence.md 第八輪：Z1～Z4 and 第八輪實作釋義: the hypotheses were
registered (commit ``df0aa8b5``, #915, decision 7055425946) before anyone ran a
tool on the backfilled history.  Nothing here is a command-line option: a
change of a definition is a new code.

They are not in ``explore_research.HYPOTHESES`` nor ``round5_research`` ..
``round7_research``: their ``definitions_sha256`` hash the whole table, so
adding them would make the validation refuse the exploration reports already
run.  The engine, the population, the loading (``explore_research.load_context``),
``explore_judge``, the gate, the ledgers and the high／small first order
(``round5_research.order_key``) are imported; new here are only
``abvol_5_60``, ``skew_240``, ``beta_240`` and ``overnight_20``.

Each signal date T (after its close, only T's data and before):

- Z1: ``abvol_5_60`` high first — the mean volume of the 5 bars at − 4 .. at
  over the mean volume of the 60 bars at − 64 .. at − 5 (shares).  Missing
  with at < 64, a suspended bar in the 65, or a denominator ≤ 0.  N 20, K 20.
- Z2: ``skew_240`` small first — the skewness of the 240 daily returns r_i =
  close[i] ÷ close[i − 1] − 1, i = at − 239 .. at, with the population
  moments (n = 240).  Missing with fewer than 241 bars, a close missing or ≤ 0
  or a suspended bar in the 241, or a second moment of exactly 0.  N 20, K 60.
- Z3: ``beta_240`` small first — on the 242 market sessions T − 241 .. T, the
  least squares r_j = a + b0 m_j + b1 m_{j−1} over the latest 240 days (r on
  the adjusted closes, m on the TAIEX), b0 + b1 (Dimson, one lag).  Missing
  with a session without a bar, suspended, a close missing or ≤ 0, a TAIEX
  close missing or ≤ 0, or a degenerate market part (``MARKET_DEGENERATE``).
  N 20, K 60.
- Z4: ``overnight_20`` small first — Σ ln(open[i] ÷ close[i − 1]), i = at −
  19 .. at, on the adjusted prices (the open and close of a bar share its
  factor, so an ex-dividend gap is not an overnight return).  Missing with at
  < 20, a suspended bar in the 21, or one of the 20 opens or 20 closes missing
  or ≤ 0.  N 20, K 20.

A missing key is last whether high or low first; ties by
``portfolio_research.tie_break``.  ``portfolio_research.simulate`` (K accounts,
1/20 of the account's cash each) trades; the benchmark is the same engine over
the day's whole population.  ``explore_research.explore_judge`` judges with
t ≥ 2 on the exploration and the fixed Bonferroni t ≥ 3.180 (34 hypotheses)
on the validation.  The segments, floors, public check, the gate (the
exploration once per version, the validation once after a published
exploration report, the ledger writable before anything is read) and the
ledgers (``explore-ledger.json`` beside the DB and the repository's
``tools/research/explore_ledger.json``, each entry with
``"tool": "round8_research"``) are ``explore_research``'s.

The exploration reads the copy from its start; a later segment reads 730
calendar days of warm-up before it (Z3's 242 sessions and Z2's 241 bars are
inside).  Before the used segment is loaded the validation's panel is let go
(PR #905 review).  ``--coverage-only`` writes the share of missing values per
year (Z3 also the signal dates whose market part is missing) and the time of
the features, no return at all.
"""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
import math
import statistics
import sys
import time
from array import array
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from operator import mul
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_lib as lib  # noqa: E402
import explore_research as ex  # noqa: E402
import portfolio_research as pr  # noqa: E402
import round5_research as r5  # noqa: E402

VERSION = 1
DESIGN = "918"
TOOL = "round8_research"
REGISTRATION_COMMIT = "df0aa8b5"
DECISION = "https://github.com/YiCheng0608/stock-lab/issues/915#issuecomment-7055425946"
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
SEGMENTS = dict(ex.SEGMENTS)
MIN_SEGMENT_DAYS = dict(ex.MIN_SEGMENT_DAYS)
MIN_T = ex.MIN_T  # the exploration's t ≥ 2
# docs 第八輪 門檻: 1 − Φ(z) = 0.025 ÷ 34, z = 3.1804 to the 3rd decimal; fixed,
# not computed when run.
VALIDATION_MIN_T = 3.180
ROUND = 8
ROUND_SIZE = 4
# X1～X8, S1～S3, R1～R2, M1～M2, C1～C4, V1～V3, W1～W4, Y1～Y4, Z1～Z4
CUMULATIVE = 34
LOAD_FROM = ex.LOAD_FROM  # the exploration reads the copy from its start
WARMUP_CALENDAR_DAYS = ex.WARMUP_CALENDAR_DAYS
MIN_LOTS = lib.DEFAULT_MIN_LOTS
RAW_DIR_NAME = ex.RAW_DIR_NAME
POPULATION = pr.POPULATION
TAIEX = pr.TAIEX

HIGH, LOW = r5.HIGH, r5.LOW
ABVOL_RECENT = 5  # volume[at − 4 .. at]
ABVOL_BASE = 60  # volume[at − 64 .. at − 5]
SKEW_RETURNS = 240  # r_i, i = at − 239 .. at (241 closes)
BETA_SESSIONS = 242  # market sessions T − 241 .. T
BETA_DAYS = 240  # the latest 240 sampling days in the regression
OVERNIGHT_TERMS = 20  # ln(open[i] ÷ close[i − 1]), i = at − 19 .. at
# The OTC bars from 2007-04-23 to 2007-11-30 are not read (bar_exclusions.json):
# Z1～Z4 count from the OTC 2007-12-03, as rounds 5 to 7.
OTC_ANCHOR = r5.OTC_ANCHOR

# The criteria the program uses for the degenerate cases (docs 第八輪實作釋義
# 退化情況寫實際的判準); coverage.md and the tool's docs section say the same.
SKEW_DEGENERATE = (
    "算出的二階動差 m2＝1/n Σ(rᵢ − r̄)² 剛好是 0.0（浮點值相等）；接近 0 但不是 0 不另攔"
)
MARKET_DEGENERATE = (
    "大盤兩欄去平均後的平方和 S₀₀＝Σ(mⱼ − m̄)²、S₁₁＝Σ(mⱼ₋₁ − m̄₋₁)² 任一個不是 > 0，"
    "或 det＝S₀₀·S₁₁ − S₀₁² 不是 > 0（S₀₁ 是兩欄去平均後的交叉積和；完全共線時 det 是 0）；"
    "近似共線（det > 0 但很小）不另攔"
)

# The registration (docs 第八輪：Z1～Z4), word for word.  ``start`` as
# ``explore_research``: ("session", anchor, n) is the n-th session counting the
# anchor (or the first session after it) as the first.  ``keys``: (feature,
# HIGH | LOW), a missing value last either way, ties by
# ``portfolio_research.tie_break``.
HYPOTHESES: dict[str, dict[str, Any]] = {
    "Z1": {
        "direction": "能見度",
        "label": "`abvol_5_60`（近 5 根的平均成交量 ÷ 再往前 60 根的平均成交量）大者先",
        "rule": "daily",
        "subset": None,
        "keys": (("abvol_5_60", HIGH),),
        "top": 20,
        "hold": 20,
        "start": ("session", OTC_ANCHOR, 65),
    },
    "Z2": {
        "direction": "彩券偏好",
        "label": "`skew_240`（近 240 個日報酬的偏態）小者先",
        "rule": "daily",
        "subset": None,
        "keys": (("skew_240", LOW),),
        "top": 20,
        "hold": 60,
        "start": ("session", OTC_ANCHOR, 241),
    },
    "Z3": {
        "direction": "低風險",
        "label": "`beta_240`（近 240 日對加權指數的 Dimson beta，含 1 個落後項）小者先",
        "rule": "daily",
        "subset": None,
        "keys": (("beta_240", LOW),),
        "top": 20,
        "hold": 60,
        "start": ("session", OTC_ANCHOR, 242),
    },
    "Z4": {
        "direction": "投資人情緒",
        "label": "`overnight_20`（近 20 根「前一根收盤 → 當根開盤」的對數報酬加總）小者先",
        "rule": "daily",
        "subset": None,
        "keys": (("overnight_20", LOW),),
        "top": 20,
        "hold": 20,
        "start": ("session", OTC_ANCHOR, 21),
    },
}
OTHER_COMPARISONS = ex.OTHER_COMPARISONS
REASONS = dict(ex.REASONS)
VOLATILE_KEYS = ex.VOLATILE_KEYS
LIMITS = {
    "Z1": "選到的股票常在漲停附近，T+1 漲停鎖死買不到的檔照引擎略過、不遞補，名單不足 20 檔的餘額留現金",
    "Z2": "漲跌幅限制 2015-06-01 起由 ±7% 放寬到 ±10%，兩邊的尾巴都被截斷，偏態的分布跨年不同；"
    "排序只在同一天之間比，名單不受影響，但不同年份的特徵值不能直接比",
    "Z3": "上櫃股也用加權指數當大盤（兩市場同一個基準，不混用櫃買指數），同 Y3；加權指數是價格指數、不含股利。"
    "Frazzini & Pedersen 的 BAB 是多空、以 beta 加權槓桿；這裡只做多、等權，"
    "測的是「低 beta 的 20 檔贏不贏母體」，不是 BAB 因子本身",
}


def definitions() -> dict[str, Any]:
    return {
        "version": VERSION,
        "design": DESIGN,
        "hypotheses": HYPOTHESES,
        "features": {
            "abvol_5_60": {
                "value": "mean volume[at-4..at] / mean volume[at-64..at-5] (Series.volume)",
                "recent": ABVOL_RECENT,
                "base": ABVOL_BASE,
                "missing": "at < 64; a suspended bar in at-64..at; a denominator <= 0",
            },
            "skew_240": {
                "value": "(1/n sum (r - mean)^3) / (1/n sum (r - mean)^2)^(3/2), "
                "r_i = close[i] / close[i-1] - 1, i = at-239..at (Series.close)",
                "returns": SKEW_RETURNS,
                "moments": "population, n = 240",
                "missing": "at < 240; a close missing or <= 0 or a suspended bar in "
                "at-240..at",
                "degenerate": SKEW_DEGENERATE,
            },
            "beta_240": {
                "points": "Panel.sessions T-241..T",
                "sessions": BETA_SESSIONS,
                "days": BETA_DAYS,
                "value": "b0 + b1 of the least squares r_j = a + b0 m_j + b1 m_j-1 "
                "over the latest 240 days; r on Series.close, m on Panel.index_close",
                "missing": "a session without a bar, suspended, a close missing or "
                "<= 0; a TAIEX close missing or <= 0",
                "degenerate": MARKET_DEGENERATE,
            },
            "overnight_20": {
                "value": "sum ln(open[i] / close[i-1]), i = at-19..at (Series.open, "
                "Series.close, one factor per bar)",
                "terms": OVERNIGHT_TERMS,
                "missing": "at < 20; a suspended bar in at-20..at; an open at-19..at "
                "or a close at-20..at-1 missing or <= 0",
            },
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
        "warmup": WARMUP_CALENDAR_DAYS,
    }


def definitions_sha256() -> str:
    """Hash of every fixed number the verdicts depend on (the definitions, the
    segments, both thresholds, the costs).  A changed tool needs a new
    exploration report before a validation."""

    text = json.dumps(definitions(), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- reading ----------------------------------------------------------------------


@dataclass(frozen=True)
class Closes:
    """One series' daily returns and the running count of bad closes, built
    once and shared by Z2 and Z3."""

    returns: array  # returns[k] = close[k] ÷ close[k − 1] − 1 (NaN when not both > 0)
    bad: array  # bad[k]: closes missing or ≤ 0 before position k


@dataclass(frozen=True)
class BetaMarket:
    """Z3's part shared by every stock on T: the first sampling session and the
    weights w over the stock's 240 returns r_j with Σ wⱼ rⱼ = b₀ (``same``),
    b₁ (``lag``) or b₀ + b₁ (``weights``); the market columns are centred, so
    the intercept drops out."""

    first: int  # session index of T − 241
    same: tuple[float, ...]  # b0 = Σ same_j · r_j
    lag: tuple[float, ...]  # b1 = Σ lag_j · r_j
    weights: tuple[float, ...]  # b0 + b1


@dataclass
class Context:
    """``explore_research``'s context (the market, the quotes), the returns of
    each series, Z3's market part by T's session and the time of each feature."""

    base: ex.Context
    closes: dict[int, Closes] = field(default_factory=dict)
    beta_market: dict[int, BetaMarket | None] = field(default_factory=dict)
    seconds: Counter = field(default_factory=Counter)

    @property
    def market(self) -> pr.Market:
        return self.base.market

    @property
    def panel(self) -> lib.Panel:
        return self.base.market.panel

    def quote(self, instrument_id: int, s: int) -> pr.Quote | None:
        return self.base.quote(instrument_id, s)


def load(db: Path, start: date, end: date, raw_dir: Path) -> Context:
    """The panel from ``start`` to ``end``; nothing after ``end`` is read."""

    return Context(ex.load_context(db, start, end, raw_dir))


# --- features ---------------------------------------------------------------------


def _suspended_in(item: lib.Series, first: int, last: int) -> bool:
    """A suspended bar in positions ``first`` .. ``last``."""

    return item.suspended[last + 1] != item.suspended[first]


def abvol_5_60(_ctx: Context, item: lib.Series, at: int) -> float | None:
    """The mean volume of at − 4 .. at over the mean of at − 64 .. at − 5 (docs
    第八輪 Z1 第 1～2 點)."""

    first = at - ABVOL_RECENT - ABVOL_BASE + 1
    if first < 0 or _suspended_in(item, first, at):
        return None
    volume = item.volume
    base = sum(volume[first : at - ABVOL_RECENT + 1]) / ABVOL_BASE
    if not base > 0:
        return None
    return sum(volume[at - ABVOL_RECENT + 1 : at + 1]) / ABVOL_RECENT / base


def closes_of(ctx: Context, item: lib.Series) -> Closes:
    got = ctx.closes.get(item.instrument_id)
    if got is None:
        close = item.close
        returns = array("d", [lib.NAN]) * len(close)
        bad = array("i", [0])
        count, previous = 0, lib.NAN
        for k, value in enumerate(close):
            good = value > 0  # NaN fails too
            if not good:
                count += 1
            elif previous > 0:
                returns[k] = value / previous - 1.0
            bad.append(count)
            previous = value
        got = ctx.closes[item.instrument_id] = Closes(returns, bad)
    return got


def skew_240(ctx: Context, item: lib.Series, at: int) -> float | None:
    """The skewness of the 240 returns at − 239 .. at with the population
    moments (docs 第八輪 Z2 第 1～2 點)."""

    first = at - SKEW_RETURNS  # the first of the 241 closes
    if first < 0 or _suspended_in(item, first, at):
        return None
    parts = closes_of(ctx, item)
    if parts.bad[at + 1] != parts.bad[first]:
        return None
    window = parts.returns[first + 1 : at + 1]
    mean = sum(window) / SKEW_RETURNS
    deviations = [value - mean for value in window]
    squares = list(map(mul, deviations, deviations))
    second = sum(squares) / SKEW_RETURNS
    if second == 0.0:  # SKEW_DEGENERATE
        return None
    third = sum(map(mul, squares, deviations)) / SKEW_RETURNS
    return third / second**1.5


def beta_market(ctx: Context, s: int) -> BetaMarket | None:
    """T's market part (T is session ``s``); None when a sampling session is
    before the copy, a TAIEX close is missing or ≤ 0, or the market part is
    degenerate (``MARKET_DEGENERATE``)."""

    if s in ctx.beta_market:
        return ctx.beta_market[s]
    out = None
    first = s - BETA_SESSIONS + 1
    if first >= 0:
        sessions, index = ctx.panel.sessions, ctx.panel.index_close
        closes = [index.get(sessions[p]) for p in range(first, s + 1)]
        if all(close is not None and close > 0 for close in closes):
            # m[j] is the TAIEX return of sampling day j (j = 1 .. 241), m[0] none
            m = [lib.NAN] + [
                closes[j] / closes[j - 1] - 1.0 for j in range(1, len(closes))
            ]
            same = m[BETA_SESSIONS - BETA_DAYS :]  # m_j, j = 2 .. 241
            lag = m[BETA_SESSIONS - BETA_DAYS - 1 : -1]  # m_{j−1}
            weights = market_weights(same, lag)
            if weights is not None:
                w0, w1 = weights
                out = BetaMarket(first, w0, w1, tuple(map(sum, zip(w0, w1))))
    ctx.beta_market[s] = out
    return out


def market_weights(
    same: list[float], lag: list[float]
) -> tuple[tuple[float, ...], tuple[float, ...]] | None:
    """The rows of (C'C)⁻¹C' for the centred columns C = (mⱼ, mⱼ₋₁), so b =
    (C'C)⁻¹C'r; None when degenerate (``MARKET_DEGENERATE``)."""

    n = len(same)
    same_mean, lag_mean = sum(same) / n, sum(lag) / n
    c0 = [value - same_mean for value in same]
    c1 = [value - lag_mean for value in lag]
    s00 = sum(map(mul, c0, c0))
    s11 = sum(map(mul, c1, c1))
    s01 = sum(map(mul, c0, c1))
    det = s00 * s11 - s01 * s01
    if not (s00 > 0 and s11 > 0 and det > 0):
        return None
    w0 = tuple((s11 * a - s01 * b) / det for a, b in zip(c0, c1))
    w1 = tuple((s00 * b - s01 * a) / det for a, b in zip(c0, c1))
    return w0, w1


def _beta_window(ctx: Context, item: lib.Series, at: int):
    """(T's market part, the stock's 240 returns) or None (docs 第八輪 Z3 第
    1～4 點)."""

    market = beta_market(ctx, item.session[at])
    if market is None:
        return None
    first = at - BETA_SESSIONS + 1
    # 242 bars of this stock ending on T span exactly the 242 sampling
    # sessions only when none of them is without a bar
    if first < 0 or item.session[first] != market.first:
        return None
    if _suspended_in(item, first, at):
        return None
    parts = closes_of(ctx, item)
    if parts.bad[at + 1] != parts.bad[first]:
        return None
    return market, parts.returns[at - BETA_DAYS + 1 : at + 1]


def dimson(ctx: Context, item: lib.Series, at: int) -> tuple[float, float] | None:
    """(b₀, b₁) of the regression; ``beta_240`` is their sum."""

    got = _beta_window(ctx, item, at)
    if got is None:
        return None
    market, returns = got
    return sum(map(mul, market.same, returns)), sum(map(mul, market.lag, returns))


def beta_240(ctx: Context, item: lib.Series, at: int) -> float | None:
    got = _beta_window(ctx, item, at)
    if got is None:
        return None
    market, returns = got
    return sum(map(mul, market.weights, returns))


def overnight_20(_ctx: Context, item: lib.Series, at: int) -> float | None:
    """Σ ln(open[i] ÷ close[i − 1]), i = at − 19 .. at, adjusted (docs 第八輪 Z4
    第 1～3 點)."""

    first = at - OVERNIGHT_TERMS
    if first < 0 or _suspended_in(item, first, at):
        return None
    opens, closes = item.open, item.close
    total = 0.0
    for i in range(first + 1, at + 1):
        opened, closed = opens[i], closes[i - 1]
        if not (opened > 0 and closed > 0):  # NaN fails too
            return None
        total += math.log(opened / closed)
    return total


FEATURES: dict[str, Callable[[Context, lib.Series, int], float | None]] = {
    "abvol_5_60": abvol_5_60,
    "skew_240": skew_240,
    "beta_240": beta_240,
    "overnight_20": overnight_20,
}
FEATURE_LABELS = {
    "abvol_5_60": "近 5 根 ÷ 前 60 根平均成交量",
    "skew_240": "240 個日報酬的偏態",
    "beta_240": "Dimson beta",
    "overnight_20": "20 根隔夜對數報酬加總",
}


def used_features(spec: dict[str, Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(name for name, _direction in spec["keys"]))


# --- the order --------------------------------------------------------------------


order_key = r5.order_key


@dataclass
class Ranked:
    rows: list[tuple[int, dict[str, float | None], str]]
    missing: Counter
    no_market: bool = False  # Z3: T's market part missing


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
            started = time.perf_counter()
            values[name] = FEATURES[name](ctx, item, at)
            ctx.seconds[name] += time.perf_counter() - started
            out.missing[name] += values[name] is None
        rows.append((item.instrument_id, values, pr.tie_break(day, item.instrument_id)))
    if "beta_240" in names and members:
        item, at = members[0]
        out.no_market = beta_market(ctx, item.session[at]) is None
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
    names = used_features(spec)
    for name in names:
        year["missing"][name] = year["missing"].get(name, 0) + r.missing[name]
    if "beta_240" in names:
        year["no_market_days"] = year.get("no_market_days", 0) + r.no_market


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
        if not keep_rows:
            continue
        out.picks[at + 1] = [row[0] for row in ranked.rows]
        out.population[at + 1] = [item.instrument_id for item, _ in members]
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
    ctx.seconds.clear()
    started = time.monotonic()
    planned = plan(ctx, spec, first, last, keep_rows=not coverage_only)
    result["window"]["signal_days"] = planned.signal_days
    result["coverage"] = planned.coverage
    result["seconds"] = {
        "plan": time.monotonic() - started,
        **{key: ctx.seconds[key] for key in used_features(spec)},
    }
    if coverage_only:
        return result
    started = time.monotonic()
    mine = pr.simulate(planned.picks, ctx.quote, first, last, spec["hold"], spec["top"])
    population = pr.simulate(
        planned.population, ctx.quote, first, last, spec["hold"], None
    )
    result["seconds"]["simulate"] = time.monotonic() - started
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
_share = r5._share
TRADE_FIELDS = r5.TRADE_FIELDS
_row = r5._row
# The wording shared by coverage.md and the tool's docs section (#913 review).
MISSING_SHARE_NOTE = "缺值比例的分母是母體檔次（每個訊號日的母體加總）"
NO_MARKET_NOTE = (
    "Z3 的「大盤部分缺值的訊號日」：242 個取樣日中最早的一天早於副本、任一天加權指數收盤缺值或 ≤ 0，"
    f"或大盤欄退化（{MARKET_DEGENERATE}）；這些訊號日母體中每一檔的 `beta_240` 都缺值"
)


def threshold(value: float) -> str:
    """2 → "2", 3.180 → "3.180" as registered (``round5_research.threshold``
    would cut it to "3.18")."""

    return f"{value:g}" if value == int(value) else f"{value:.3f}"


def coverage_lines(name: str, coverage: dict[str, Any]) -> list[str]:
    spec = HYPOTHESES[name]
    names = used_features(spec)
    head = ["年", "日數", "母體檔次", *(f"{FEATURE_LABELS[n]} 缺值" for n in names)]
    z3 = "beta_240" in names
    if z3:
        head += ["大盤部分缺值的訊號日"]
    lines = [
        "| " + " | ".join(head) + " |",
        "| --- | " + " | ".join("---:" for _ in head[1:]) + " |",
    ]
    for year, row in sorted(coverage.items()):
        members = row["members"]
        cells = [f"{row['days']:,}", f"{members:,}"]
        cells += [_share(row["missing"].get(n, 0), members) for n in names]
        if z3:
            cells.append(f"{row.get('no_market_days', 0):,}")
        lines.append(f"| {year} | " + " | ".join(cells) + " |")
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
        f"# {name} {segment}（round8_research 第 {VERSION} 版，#{DESIGN}）",
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
    if result.get("coverage"):
        lines += [
            "## 資料覆蓋（不含報酬）",
            "",
            f"{MISSING_SHARE_NOTE}。",
            *([f"{NO_MARKET_NOTE}。"] if name == "Z3" else []),
            "",
            *coverage_lines(name, result["coverage"]),
            "",
        ]
    return "\n".join(lines)


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
    _write_csvs(out, result, header, spec)


def _write_csvs(
    out: Path, result: dict[str, Any], header: dict[str, Any], spec: dict[str, Any]
) -> None:
    name = result["hypothesis"]
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
        f"# 新策略探索 第 {report['round']} 輪 {stage}（round8_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「第八輪：Z1～Z4」）：{DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        _threshold_line(segment, report["min_t"]),
        *(f"- {name} 的限制：{text}" for name, text in LIMITS.items()),
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


def seconds_lines(body: dict[str, Any]) -> list[str]:
    """The time of each hypothesis's signal dates and of its features."""

    lines = [
        "| 代號 | 訊號日 | 排序與覆蓋（秒） | 特徵計算（秒） | 每個訊號日（毫秒） |",
        "| --- | ---: | ---: | --- | ---: |",
    ]
    for name, row in body["hypotheses"].items():
        seconds = row.get("seconds") or {}
        days = (row["window"] or {}).get("signal_days", 0)
        parts = "、".join(
            f"`{key}` {value:.1f}" for key, value in seconds.items() if key != "plan"
        )
        per_day = lib.num(seconds.get("plan", 0.0) * 1000 / days, 1) if days else "—"
        lines.append(
            f"| {name} | {days:,} | {seconds.get('plan', 0.0):.1f} | {parts or '—'} "
            f"| {per_day} |"
        )
    return lines


def coverage_markdown(body: dict[str, Any]) -> str:
    lines = [
        f"# 新策略探索 第 {body['round']} 輪 Z1～Z4 資料覆蓋（探索段，不含報酬）",
        "",
        f"- round8_research 第 {VERSION} 版；定義雜湊 `{body['definitions_sha256']}`",
        f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}，"
        f"alembic `{body['copy']['alembic']}`",
        f"- 重現：`{body['command']}`",
        f"- 耗時 {body.get('elapsed_seconds', 0):.0f} 秒（載入 {body.get('load_seconds', 0):.0f} 秒），"
        f"峰值記憶體 {lib.num(body.get('peak_memory_gb'), 2)} GB，"
        f"日線 {body.get('bars', 0):,} 根",
        f"- {MISSING_SHARE_NOTE}",
        f"- {NO_MARKET_NOTE}",
        f"- Z2 的退化：{SKEW_DEGENERATE}",
        "- 各假設用自己的訊號日（起日寫在各段標題）；特徵計算的秒數含第一次用到時建各檔日報酬的時間"
        "（Z2、Z3 共用，先跑的那個算進去）",
        "",
        "## 耗時",
        "",
        *seconds_lines(body),
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


def _peak_memory_gb() -> float | None:
    return lib._load("backtest_research").peak_memory_gb()


def _finish(out: Path, report: dict[str, Any], started: float) -> str:
    report["elapsed_seconds"] = time.monotonic() - started
    report["peak_memory_gb"] = _peak_memory_gb()
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
    names: list[str] | tuple[str, ...],
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
    loaded = time.monotonic() - started
    header = _header(db, EXPLORATION, command, end)
    header["_panel"] = ctx.panel
    if coverage_only:
        coverage = {}
        for name in HYPOTHESES:
            result = run_one(ctx, db, name, EXPLORATION, coverage_only=True)
            seconds = result.get("seconds", {})
            coverage[name] = {
                "window": result["window"],
                "coverage": result.get("coverage", {}),
                "seconds": seconds,
            }
            progress(f"{name} coverage ({seconds.get('plan', 0.0):.1f}s)")
        body = {
            **public(header),
            "coverage_only": True,
            "hypotheses": coverage,
            "load_seconds": loaded,
            "elapsed_seconds": time.monotonic() - started,
            "peak_memory_gb": _peak_memory_gb(),
            "bars": sum(len(item.dates) for item in ctx.panel.series.values()),
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
    result: dict[str, Any] = {}
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
        # Let the validation's panel go before the used one is loaded, so only
        # one panel is held at a time (PR #905 review 7053124013).
        header.pop("_panel", None)
        report.pop("_panel", None)
        del ctx, result
        gc.collect()
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
    parser = argparse.ArgumentParser(prog="round8_research.py", description=__doc__)
    parser.add_argument(
        "--db", required=True, help="the research DB (/research/stock.db)"
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--segment", required=True, choices=STAGES)
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help="exploration only: the share of missing values per year (Z3 also "
        "the signal dates without a market part) and the time of the features, "
        "no return",
    )
    parser.add_argument(
        "--hypotheses",
        help="exploration (required, not with --coverage-only): Z1, Z2, Z3, Z4 or "
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
    problems = list(lib._load("exit_research").refusals(db, args.min_free_gb))
    names: list[str] = []
    if args.segment == EXPLORATION and not args.coverage_only:
        chosen, names = ex.exploration_problems(
            db, args.hypotheses, HYPOTHESES, VERSION
        )
        problems = [*problems, *chosen]
    if problems:
        print(json.dumps({"refused": problems}, ensure_ascii=False))
        return 2
    command = "python tools/research/round8_research.py " + " ".join(argv)
    progress = lambda text: print(text, file=sys.stderr, flush=True)  # noqa: E731
    if args.segment == EXPLORATION:
        line = run_exploration(
            db,
            Path(args.out),
            names,
            command,
            args.coverage_only,
            progress=progress,
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
