"""Round 4 of the new-strategy exploration: C1～C4, each S1 with one layer changed (#878).

docs/spec/evidence.md 第四輪：C1～C4 and 第四輪實作釋義: the hypotheses were
registered (commit ``f39d39ea``, #874, decision 7043974968) before anyone ran a
tool on the backfilled history.  Nothing here is a command-line option: a
change of a definition is a new code, and the tests lock it.

The engine is ``trade_research``'s, imported and not changed (its version 1
stays the one round 2 ran; a golden test there locks S1～S3 and R1／R2 trade
by trade): the panel, ATR14, the market filter, the entry zone, the fills, the
exits, the population baseline, the statistics, ``run_segment``, the gate and
the ledgers.  C1～C4 are not in ``trade_research.HYPOTHESES``: they enter
through its three hook points (``trade_research.Hooks``):

- C1 族群強度: an extra condition after S1's selection, T's group among the five
  strongest official industries (``mainstream_research``'s member table, its
  instrument match and ``REMAP_2023``; the strength over T's whole population,
  the 20- and 60-session returns relative to TAIEX).
- C2 土洋同買: the first ranking key ``both_buy_days`` (sessions of the five to
  T with both the foreign and the trust figure above 0) in place of
  ``trust_buy_days``.
- C3 融資暴增排除: an extra condition after S1's selection, the six-session
  margin change at most 5% (``trade_research.margin_state``, the function R1
  and R2 read; not applicable kept, a zero base judged by its two balances,
  missing excluded).
- C4 成交量價位帶停損: the stop at the lower edge of the 60-bar volume profile's
  densest bin under T's close less 0.5×ATR14, its distance clamped to
  [1, 3]×ATR14; S1's stop when the profile cannot be computed.  R stays
  2×ATR14: the target is S1's.

``--coverage-only`` reads dates, counts and missing shares (and, for C4's
clamping, the fill of the entry zone), never a return.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_lib as lib  # noqa: E402
import explore_research as ex  # noqa: E402
import feature_evidence as features  # noqa: E402
import mainstream_research as ms  # noqa: E402
import portfolio_research as pr  # noqa: E402
import trade_research as tr  # noqa: E402

VERSION = 1
DESIGN = "878"
TOOL = "round4_research"
REGISTRATION_COMMIT = "f39d39ea"
DECISION = "https://github.com/YiCheng0608/stock-lab/issues/874#issuecomment-7043974968"
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
ROUND = 4
ROUND_SIZE = 4
CUMULATIVE = 19  # X1～X8, S1～S3, R1～R2, M1～M2, C1～C4; H1 and #619～#689 apart
RAW_DIR_NAME = ex.RAW_DIR_NAME
UNDECIDED = ex.UNDECIDED
PASSED = ex.PASSED

# C1 族群強度 (docs 第四輪 C1)
RETURN_WINDOWS = (20, 60)
GROUP_COUNT = 5
MIN_MEMBERS = 5
INDEX_CLOSES = max(RETURN_WINDOWS) + 1  # 61 TAIEX closes to T
MOMENTUM = {n: features._momentum(n) for n in RETURN_WINDOWS}
# C2 土洋同買
BOTH_WINDOW = 5  # the five bars at − 4 … at, as trust_buy_days
# C3 融資暴增排除: the product's margin_financing.maximum_balance_change_ratio
# (``lte``, app.strategies.base; a test compares the two)
MARGIN_MAX = 0.05
# C4 成交量價位帶停損
BAND_BARS = 60
BAND_BINS = 24
BAND_BUFFER_ATR = 0.5
BAND_CLAMP_ATR = (1.0, 3.0)

# The registration (docs 第四輪：C1～C4), word for word: every layer is S1's
# (``trade_research.HYPOTHESES["S1"]``; a test compares them) except the one
# ``change`` names.
S1 = {
    "kind": "zone",
    "market_filter": True,
    "top": 10,
    "entry_days": 3,
    "zone_atr": 1.0,
    "stop_atr": 2.0,  # C4's stop when its profile cannot be computed
    "target_atr": 4.0,
    "hold": 20,
    "start": tr.START,
}
HYPOTHESES: dict[str, dict[str, Any]] = {
    "C1": {
        **S1,
        "label": "S1，另只取 T 日屬於前 5 個強勢族群的股票（官方產業，"
        "成員 20 日與 60 日報酬相對 TAIEX 的平均）",
        "change": "select",
    },
    "C2": {
        **S1,
        "label": "S1 的第一排序鍵換成 both_buy_days（近 5 根外資與投信同一天都買超的根數）",
        "change": "first_key",
    },
    "C3": {
        **S1,
        "label": "S1，另排除融資 6 日變化 > 5% 的股票（零基期增加與缺值也排除，不適用照選）",
        "change": "select",
    },
    "C4": {
        **S1,
        "label": "S1 的停損改成 60 根成交量分布最集中價位帶的下緣 − 0.5×ATR14，"
        "距離夾在 [1, 3]×ATR14（R 仍是 2×ATR14，目標仍是 +4×ATR14）",
        "change": "stop",
    },
}
REASONS = dict(tr.REASONS)
OTHER_COMPARISONS = ex.OTHER_COMPARISONS
VOLATILE_KEYS = ex.VOLATILE_KEYS


def definitions() -> dict[str, Any]:
    return {
        "version": VERSION,
        "design": DESIGN,
        "hypotheses": HYPOTHESES,
        "c1": {
            "windows": list(RETURN_WINDOWS),
            "group_count": GROUP_COUNT,
            "min_members": MIN_MEMBERS,
            "index_closes": INDEX_CLOSES,
            "strength": "mean of (member mean − TAIEX) over the two windows",
            "population": "T's whole population, occupied stocks included",
            "group_key": "group_id",
            "tie": "group key, smaller first",
        },
        "c2": {"window": BOTH_WINDOW, "both": "foreign_buy > 0 and trust_buy > 0"},
        "c3": {
            "maximum": MARGIN_MAX,
            "not_applicable": "kept",
            "zero_base": {"unchanged": "kept", "increased": "excluded"},
            "missing": "excluded",
        },
        "c4": {
            "bars": BAND_BARS,
            "bins": BAND_BINS,
            "buffer_atr": BAND_BUFFER_ATR,
            "clamp_atr": list(BAND_CLAMP_ATR),
            "candidates": "upper edge <= T close",
            "tie": "the higher bin",
            "fallback": "S1's stop",
        },
        # the member table and its rules are M1／M2's (docs 第三輪 官方產業的成員)
        "members": ms.definitions()["members"],
        # the engine's numbers (trade_research): segments, floors, thresholds, costs
        "engine": {
            "tool": tr.TOOL,
            "version": tr.VERSION,
            "segments": tr.SEGMENTS,
            "min_segment_days": tr.MIN_SEGMENT_DAYS,
            "min_days": tr.MIN_DAYS,
            "min_t": tr.MIN_T,
            "bonferroni": [ex.BONFERRONI_AFTER, ex.ONE_SIDED],
            "costs": [tr.SLIPPAGE, tr.COST_BPS],
            "overlap": tr.OVERLAP,
            "min_lots": tr.MIN_LOTS,
            "atr": tr.ATR_WINDOW,
            "market_filter": tr.MA_WINDOW,
            "score_keys": list(tr.SCORE_KEYS),
            "warmup": tr.WARMUP_CALENDAR_DAYS,
        },
        "round": [ROUND, ROUND_SIZE, CUMULATIVE],
    }


def definitions_sha256() -> str:
    """Hash of every fixed number the verdicts depend on.  A changed tool needs
    a new exploration report before a validation."""

    text = json.dumps(definitions(), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- C1 族群強度 -------------------------------------------------------------------


def index_returns(ctx: tr.Context, day: date) -> tuple[float, float] | None:
    """TAIEX's 20- and 60-session returns to ``day``: its close on ``day`` over
    the earliest of its N + 1 closes, minus one; None without a close on
    ``day`` or with fewer than 61 closes."""

    at = bisect.bisect_right(ctx.index_days, day) - 1
    if at < INDEX_CLOSES - 1 or ctx.index_days[at] != day:
        return None
    now = ctx.panel.index_close[day]
    out = []
    for n in RETURN_WINDOWS:
        then = ctx.panel.index_close[ctx.index_days[at - n]]
        if not (now and then and now > 0 and then > 0):
            return None
        out.append(now / then - 1.0)
    return out[0], out[1]


def member_returns(
    universe: list[tuple[lib.Series, int]],
) -> dict[int, tuple[float, float]]:
    """The 20- and 60-session returns of the population members with both."""

    out = {}
    for item, at in universe:
        values = [MOMENTUM[n](item, at) for n in RETURN_WINDOWS]
        if all(v is not None and v == v for v in values):
            out[item.instrument_id] = (values[0], values[1])
    return out


def rank_groups(
    returns: dict[int, tuple[float, float]],
    members: dict[str, set[int]],
    index: tuple[float, float],
) -> list[tuple[float, str, int]]:
    """(strength, group id, valued members) of every group with at least 5
    valued members, strongest first, ties by the group key."""

    scored = []
    for group_id, ids in members.items():
        valued = sorted(i for i in ids if i in returns)
        if len(valued) < MIN_MEMBERS:
            continue
        relative = [
            statistics.fmean(returns[i][k] for i in valued) - index[k]
            for k in range(len(RETURN_WINDOWS))
        ]
        scored.append((sum(relative) / len(relative), group_id, len(valued)))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return scored


C1_KEYS = ("days", "universe", "grouped", "ranked_groups", "short", "taiex", "none")


class StrongGroups:
    """C1's hook: T's five strongest groups, and what the coverage counts."""

    def __init__(self, groups: ms.Context):
        self.groups = groups
        self.years: dict[str, dict[str, int]] = {}
        self.chosen: dict[date, list[tuple[float, str, int]]] = {}

    def day(self, ctx: tr.Context, s: int) -> Callable[[lib.Series, int], bool] | None:
        day = ctx.panel.sessions[s]
        universe = ctx.universe(s)
        members, _retro, _remapped = ms.group_members(self.groups, day)
        owner: dict[int, set[str]] = defaultdict(set)
        for group_id, ids in members.items():
            for instrument_id in ids:
                owner[instrument_id].add(group_id)
        year = self.years.setdefault(str(day.year), dict.fromkeys(C1_KEYS, 0))
        year["days"] += 1
        year["universe"] += len(universe)
        year["grouped"] += sum(1 for item, _ in universe if item.instrument_id in owner)
        index = index_returns(ctx, day)
        scored = rank_groups(member_returns(universe), members, index or (0.0, 0.0))
        year["ranked_groups"] += len(scored)
        if index is None:
            year["taiex"] += 1
            return None
        if not scored:
            year["none"] += 1
            return None
        if len(scored) < GROUP_COUNT:
            year["short"] += 1
        top = scored[:GROUP_COUNT]
        self.chosen[day] = top
        strong = {group_id for _strength, group_id, _n in top}
        return lambda item, at: bool(owner.get(item.instrument_id, set()) & strong)

    def hooks(self) -> tr.Hooks:
        return tr.Hooks(select=self.day)


# --- C2 土洋同買 -------------------------------------------------------------------


def both_buy_days(item: lib.Series, at: int) -> float | None:
    """Bars of the five to T (``at − 4 … at``) with ``foreign_buy > 0`` and
    ``trust_buy > 0``; None with fewer than five bars or a missing figure."""

    if at < BOTH_WINDOW - 1:
        return None
    foreign = item.chips["foreign_buy"][at + 1 - BOTH_WINDOW : at + 1]
    trust = item.chips["trust_buy"][at + 1 - BOTH_WINDOW : at + 1]
    if any(value != value for value in (*foreign, *trust)):
        return None
    return float(sum(1 for f, t in zip(foreign, trust) if f > 0 and t > 0))


# --- C3 融資暴增排除 ----------------------------------------------------------------

KEPT = "kept"
OVER = "over"  # the ratio above 5%
ZERO_BASE_INCREASED = "zero_base_increased"
MISSING = "missing"
NOT_APPLICABLE = "not_applicable"  # kept: no margin trading, no surge (#392)
MARGIN_CLASSES = (KEPT, NOT_APPLICABLE, OVER, ZERO_BASE_INCREASED, MISSING)
EXCLUDED = (OVER, ZERO_BASE_INCREASED, MISSING)


def margin_class(margin: tr.Margin) -> str:
    """C3's verdict on one stock, in the order of v3's ``judge_zero_base``:
    not applicable first, then the ratio, then the zero base, else missing."""

    from app import margin_lists, margin_zero_base

    if margin.financing == margin_lists.NOT_APPLICABLE:
        return NOT_APPLICABLE
    if margin.ratio is not None:
        return OVER if margin.ratio > MARGIN_MAX else KEPT
    if margin.zero_base == margin_zero_base.UNCHANGED:
        return KEPT
    if margin.zero_base == margin_zero_base.INCREASED:
        return ZERO_BASE_INCREASED
    return MISSING


class MarginFilter:
    """C3's hook: S1's selection less the margin surges, counted by class."""

    def __init__(self) -> None:
        self.years: dict[str, Counter] = {}

    def day(self, ctx: tr.Context, s: int) -> Callable[[lib.Series, int], bool]:
        year = self.years.setdefault(str(ctx.panel.sessions[s].year), Counter())
        year["days"] += 1

        def keep(item: lib.Series, at: int) -> bool:
            verdict = margin_class(tr.margin_state(ctx, item, at))
            year[verdict] += 1
            return verdict not in EXCLUDED

        return keep

    def hooks(self) -> tr.Hooks:
        return tr.Hooks(select=self.day)


# --- C4 成交量價位帶停損 ------------------------------------------------------------

BAND = "band"
CLAMPED_LOW = "clamped_low"  # d < 1×ATR14 (d ≤ 0 included)
CLAMPED_HIGH = "clamped_high"  # d > 3×ATR14
FALLBACK = "fallback"  # S1's stop
STOP_SOURCES = (BAND, CLAMPED_LOW, CLAMPED_HIGH, FALLBACK)
# why the profile cannot be computed (docs C4 第 7 點; the suspended one is
# the PR #877 review's: a suspended bar is loaded without a high and a low)
SHORT = "short"
SUSPENDED = "suspended_bar"
NO_RANGE = "no_high_low"
NO_CANDIDATE = "no_candidate"
FALLBACK_REASONS = (SHORT, SUSPENDED, NO_RANGE, NO_CANDIDATE)


@dataclass(frozen=True)
class Band:
    """The densest bin under T's close (``low``, ``high``), or why there is none."""

    low: float | None = None
    high: float | None = None
    volume: float | None = None
    fallback: str | None = None


def volume_band(item: lib.Series, at: int) -> Band:
    """The 60 bars to T: 24 equal bins from the lowest low to the highest
    high, each bar's volume spread over its [low, high] by overlap (a bar with
    high = low gives it to its price's bin, the upper one on a grid line, the
    top one at the highest high); the bin with the most volume among those
    whose upper edge is at most T's close, the higher one on a tie."""

    if at + 1 < BAND_BARS:
        return Band(fallback=SHORT)
    bars = range(at + 1 - BAND_BARS, at + 1)
    for k in bars:
        if not (item.high[k] > 0 and item.low[k] > 0):
            return Band(fallback=SUSPENDED if item.is_suspended(k) else NO_RANGE)
    bottom = min(item.low[k] for k in bars)
    top = max(item.high[k] for k in bars)
    edges = [bottom + (top - bottom) * i / BAND_BINS for i in range(BAND_BINS)]
    edges.append(top)
    volumes = [0.0] * BAND_BINS
    for k in bars:
        high, low, volume = item.high[k], item.low[k], item.volume[k]
        if not volume > 0:
            continue
        if high == low:
            volumes[min(bisect.bisect_right(edges, high) - 1, BAND_BINS - 1)] += volume
            continue
        for i in range(BAND_BINS):
            overlap = min(high, edges[i + 1]) - max(low, edges[i])
            if overlap > 0:
                volumes[i] += volume * overlap / (high - low)
    close = item.close[at]
    candidates = [i for i in range(BAND_BINS) if edges[i + 1] <= close]
    if not candidates:
        return Band(fallback=NO_CANDIDATE)
    poc = max(candidates, key=lambda i: (volumes[i], i))
    return Band(edges[poc], edges[poc + 1], volumes[poc])


def band_stop(band: Band, atr: float, fill: float) -> tuple[float, str]:
    """(the stop, its source) for a fill: the band's lower edge less 0.5×ATR14,
    its distance from the fill clamped to [1, 3]×ATR14; S1's without a band."""

    if band.fallback is not None:
        return fill - S1["stop_atr"] * atr, FALLBACK
    initial = band.low - BAND_BUFFER_ATR * atr
    distance = fill - initial
    low, high = BAND_CLAMP_ATR
    if distance < low * atr:
        return fill - low * atr, CLAMPED_LOW
    if distance > high * atr:
        return fill - high * atr, CLAMPED_HIGH
    return initial, BAND


def c4_stop(
    item: lib.Series, at: int, atr: float, fill: float | None
) -> tuple[float | None, dict[str, Any]]:
    band = volume_band(item, at)
    fields: dict[str, Any] = {
        "band_low": band.low,
        "band_high": band.high,
        "band_fallback": band.fallback,
        "band_stop": None
        if band.low is None
        else band.low - BAND_BUFFER_ATR * atr,  # before the clamp
    }
    if fill is None:
        return None, {**fields, "stop_source": None}
    stop, source = band_stop(band, atr, fill)
    return stop, {**fields, "stop_source": source}


# --- the hooks of one run ----------------------------------------------------------


@dataclass
class Run:
    """The hook objects of one segment's run, kept for their listings."""

    groups: ms.Context
    made: dict[str, Any] = field(default_factory=dict)

    def __call__(self, name: str) -> tr.Hooks:
        if name == "C1":
            hook = self.made[name] = StrongGroups(self.groups)
            return hook.hooks()
        if name == "C2":
            return tr.Hooks(first_key=("both_buy_days", both_buy_days))
        if name == "C3":
            hook = self.made[name] = MarginFilter()
            return hook.hooks()
        if name == "C4":
            return tr.Hooks(stop=c4_stop)
        raise KeyError(name)


def listed(name: str, run: Run, trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Each hypothesis's own listed numbers (docs 第四輪 「另列」)."""

    if name == "C1":
        hook = run.made.get("C1")
        return {"c1": {"years": hook.years if hook else {}}}
    if name == "C2":
        top = [trade for trade in trades if trade.get("rank") is not None]
        return {
            "c2": {
                "signals": len(top),
                "first_key_missing": sum(
                    1 for trade in top if trade.get("both_buy_days") is None
                ),
            }
        }
    if name == "C3":
        hook = run.made.get("C3")
        years = {
            year: dict(counts) for year, counts in (hook.years if hook else {}).items()
        }
        return {"c3": {"years": years}}
    filled = [trade for trade in trades if trade["net"] is not None]
    return {
        "c4": {
            "trades": len(filled),
            "sources": {
                source: sum(1 for t in filled if t.get("stop_source") == source)
                for source in STOP_SOURCES
            },
            "fallbacks": {
                reason: sum(1 for t in filled if t.get("band_fallback") == reason)
                for reason in FALLBACK_REASONS
            },
        }
    }


# --- reading -----------------------------------------------------------------------


@dataclass
class Loaded:
    ctx: tr.Context
    groups: ms.Context


def load(db: Path, members: Path, start: date, end: date, raw_dir: Path) -> Loaded:
    """``trade_research.load`` and the member snapshots to ``end``; nothing
    after ``end`` is read."""

    ctx = tr.load(db, start, end, raw_dir)
    return Loaded(ctx, ms.build_context(ctx.market, ms.read_members(members, end)))


def load_from(segment: str) -> date:
    """The first day read: the warm-up before the segment (the exploration's
    anchor for its first signal), as ``trade_research``."""

    first_day = tr.SEGMENTS[segment][0]
    if first_day is None:
        first_day = min(spec["start"][1] for spec in HYPOTHESES.values())
    return first_day - timedelta(days=tr.WARMUP_CALENDAR_DAYS)


def run_segment(
    loaded: Loaded,
    db: Path,
    names: list[str],
    segment: str,
    min_t: float = tr.MIN_T,
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, dict[str, Any]]:
    """``trade_research.run_segment`` on C1～C4 through the hooks, plus each
    one's listed numbers."""

    run = Run(loaded.groups)
    results = tr.run_segment(
        loaded.ctx,
        db,
        names,
        segment,
        min_t=min_t,
        progress=progress,
        hypotheses=HYPOTHESES,
        hooks=run,
    )
    for name in names:
        result = results[name]
        if "_trades" in result:
            result["listed"] = listed(name, run, result["_trades"])
    return results


# --- --coverage-only ---------------------------------------------------------------


def coverage(
    loaded: Loaded,
    segment: str = EXPLORATION,
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, Any]:
    """Every signal date of the segment, without the market filter and without
    the occupancy (nothing is held: no exit is simulated), counted by year:
    C1's groups, C2's missing first key in the top 10, C3's classes among S1's
    selection, C4's band and stop source of S1's top 10 (the fill of the entry
    zone only).  No return is computed."""

    ctx = loaded.ctx
    sessions = ctx.panel.sessions
    span = tr.window(sessions, segment, HYPOTHESES["C1"])
    if span is None:
        return {"window": {"days": 0}, "years": {}}
    first, last = span
    groups = StrongGroups(loaded.groups)
    margins = MarginFilter()
    c2 = tr.Hooks(first_key=("both_buy_days", both_buy_days))
    years: dict[str, Counter] = {}
    for s in range(first - 1, last):
        day = sessions[s]
        year = years.setdefault(str(day.year), Counter())
        year["days"] += 1
        passed = tr.market_filter(ctx, day)
        year[
            "filter_missing"
            if passed is None
            else "filter_passed"
            if passed
            else "filter_blocked"
        ] += 1
        universe = ctx.universe(s)
        groups.day(ctx, s)
        keep = margins.day(ctx, s)
        selected = tr.ranked(ctx, day, universe)
        year["selected"] += len(selected)
        for row in selected:
            keep(row["item"], row["at"])
        for row in tr.ranked(ctx, day, universe, c2)[: S1["top"]]:
            year["c2_top"] += 1
            year["c2_missing"] += row["both_buy_days"] is None
        for row in selected[: S1["top"]]:
            item, at, atr = row["item"], row["at"], row["atr"]
            band = volume_band(item, at)
            year["c4_top"] += 1
            if band.fallback is not None:
                year[f"c4_no_band_{band.fallback}"] += 1
            close = item.close[at]
            bars = tr.TradeBars(ctx, item, s, last)
            entry, _below = tr.enter_zone(
                bars, close, close - S1["zone_atr"] * atr, S1["entry_days"]
            )
            if entry.price is None:
                year["c4_unfilled"] += 1
                continue
            _stop, source = band_stop(band, atr, entry.price / (1.0 + tr.SLIPPAGE))
            year[f"c4_source_{source}"] += 1
        if (s - first + 1) % 250 == 0:
            progress(f"coverage {day.isoformat()}")
    return {
        "window": {
            "first_signal": sessions[first - 1].isoformat(),
            "last_signal": sessions[last - 1].isoformat(),
            "days": last - first + 1,
        },
        "years": {year: dict(counts) for year, counts in sorted(years.items())},
        "c1": groups.years,
        "c3": {year: dict(counts) for year, counts in sorted(margins.years.items())},
    }


# --- output ------------------------------------------------------------------------

_pct, _t, public = ex._pct, ex._t, ex.public
TRADE_FIELDS = (
    "signal_date",
    "exchange",
    "symbol",
    "rank",
    "atr14",
    "zone_low",
    "zone_high",
    "trust_buy_days",  # S1's first key (C1, C3, C4)
    "both_buy_days",  # C2's
    "institutional_flow_20",
    "revenue_yoy",
    "band_low",  # C4: the densest bin, the stop before the clamp, its source
    "band_high",
    "band_stop",
    "band_fallback",
    "stop_source",
    *tr.TRADE_FIELDS[tr.TRADE_FIELDS.index("entry_reason") :],
)
SOURCE_LABELS = {
    BAND: "價位帶",
    CLAMPED_LOW: "被夾住（下限 1×ATR14）",
    CLAMPED_HIGH: "被夾住（上限 3×ATR14）",
    FALLBACK: "退回 S1",
}
FALLBACK_LABELS = {
    SHORT: "不足 60 根",
    SUSPENDED: "停牌根缺高低價",
    NO_RANGE: "其他根缺高低價",
    NO_CANDIDATE: "沒有候選格（T 收盤在最低格）",
}
MARGIN_LABELS = {
    OVER: "排除：> 5%",
    ZERO_BASE_INCREASED: "排除：零基期增加",
    MISSING: "排除：缺值",
    NOT_APPLICABLE: "不適用（照選）",
    KEPT: "可選",
}


def _share(part: int, whole: int) -> str:
    return _pct(part / whole, 1) if whole else "—"


def c1_lines(years: dict[str, dict[str, int]]) -> list[str]:
    lines = [
        "| 年 | 訊號日 | 母體中有族群的比例 | 可排名的族群（日均） | 湊不滿 5 個族群的天數 "
        "| 不選：TAIEX 不足 | 不選：沒有可排名的族群 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for year, row in sorted(years.items()):
        n = row["days"] or 1
        lines.append(
            f"| {year} | {row['days']:,} | {_share(row['grouped'], row['universe'])} "
            f"| {row['ranked_groups'] / n:,.1f} | {row['short']:,} "
            f"| {row['taiex']:,} | {row['none']:,} |"
        )
    return lines


def c3_lines(years: dict[str, dict[str, int]]) -> list[str]:
    classes = (OVER, ZERO_BASE_INCREASED, MISSING, NOT_APPLICABLE, KEPT)
    lines = [
        "| 年 | 訊號日 | " + " | ".join(MARGIN_LABELS[c] for c in classes) + " |",
        "| --- | ---: | " + " | ".join("---:" for _ in classes) + " |",
    ]
    for year, row in sorted(years.items()):
        lines.append(
            f"| {year} | {row.get('days', 0):,} | "
            + " | ".join(f"{row.get(c, 0):,}" for c in classes)
            + " |"
        )
    return lines


def listed_lines(name: str, listed_: dict[str, Any]) -> list[str]:
    if name == "C1":
        return [
            "## C1 的另列（正式跑：大盤濾網通過的日子；族群強弱用整個母體，不扣占用）",
            "",
            *c1_lines(listed_["c1"]["years"]),
        ]
    if name == "C2":
        c2 = listed_["c2"]
        return [
            "## C2 的另列（正式跑的前 10 名：濾網通過的日子、扣占用）",
            "",
            f"- 前 10 名裡第一鍵（`both_buy_days`）缺值的筆數："
            f"{c2['first_key_missing']:,}／{c2['signals']:,}",
        ]
    if name == "C3":
        return [
            "## C3 的另列（正式跑：濾網通過的日子，S1 選股之後、排序之前的檔次，扣占用）",
            "",
            *c3_lines(listed_["c3"]["years"]),
        ]
    c4 = listed_["c4"]
    lines = [
        "## C4 的另列（正式跑有成交的筆：濾網通過的日子、扣占用）",
        "",
        "| 停損來源 | 筆數 |",
        "| --- | ---: |",
    ]
    for source in STOP_SOURCES:
        lines.append(
            f"| {SOURCE_LABELS[source]} | {c4['sources'][source]:,}"
            f"（{_share(c4['sources'][source], c4['trades'])}） |"
        )
    for reason in FALLBACK_REASONS:
        lines.append(
            f"| 退回 S1：{FALLBACK_LABELS[reason]} | {c4['fallbacks'][reason]:,} |"
        )
    lines += ["", "每筆的帶上下緣、夾住前的停損與停損來源在 `trades.csv`。"]
    return lines


def hypothesis_markdown(result: dict[str, Any], header: dict[str, Any]) -> str:
    """``trade_research.hypothesis_markdown``'s sections, this tool's header,
    and the hypothesis's own listed numbers."""

    name = result["hypothesis"]
    spec = HYPOTHESES[name]
    segment = ex.SEGMENT_NAMES[result["segment"]]
    window_ = result["window"] or {}
    verdict = result["verdict"] or "只列出、不判定"
    lines = [
        f"# {name} {segment}（round4_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 判定：**{verdict}**"
        + (f"（{REASONS[result['reason']]}）" if result["reason"] else ""),
        f"- 假設：{spec['label']}",
        f"- 登記 commit `{REGISTRATION_COMMIT}`；定義雜湊 `{header['definitions_sha256'][:16]}…`",
        f"- 引擎：trade_research 第 {tr.VERSION} 版（S1 的其餘各層）",
        f"- 期間：訊號日 {window_.get('first_signal', '—')} 起，成交日 "
        f"{window_.get('first_session', '—')}～{window_.get('last_session', '—')}，共 "
        f"{window_.get('days', 0)} 個交易日",
    ]
    if name == "C1":
        lines.append(ms._members_line())
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
    if "excess" not in result:
        return "\n".join(lines)
    x, e, a = result["taiex_excess"], result["excess"], result["absolute"]
    lines += [
        "## 數字（訊號日序列：同一訊號日的各筆先平均）",
        "",
        "| 量 | 訊號日數 | 平均 | t |",
        "| --- | ---: | ---: | ---: |",
        f"| 超額（對加權指數，只列出） | {x['days']} | {_pct(x['mean'], 3)} | {_t(x['t'])} |",
        f"| 超額（對母體，判定） | {e['days']} | {_pct(e['mean'], 3)} | {_t(e['t'])} |",
        f"| 扣成本報酬（判定） | {a['days']} | {_pct(a['mean'], 3)} | — |",
        "",
        f"門檻：t ≥ {result.get('min_t', tr.MIN_T):.2f}（`t_stat(…, overlap={tr.OVERLAP})`）；"
        f"有成交的訊號日至少 {tr.MIN_DAYS} 日。",
        "",
        "## 只列出",
        "",
        "| 項目 | 值 |",
        "| --- | ---: |",
        f"| 訊號數 | {result['signals']:,} |",
        f"| 有訊號的日數 | {result['signal_days']:,} |",
        f"| 成交筆數 | {result['trades']:,} |",
        f"| 每筆平均（扣成本） | {_pct(result['net_mean'], 3)} |",
        f"| 每筆中位（扣成本） | {_pct(result['net_median'], 3)} |",
        f"| 勝率（> 0 ÷ 成交筆數） | {_pct(result['win_rate'], 1)} |",
        f"| 賺的筆數／平均 | {result['won']:,}／{_pct(result['won_mean'], 3)} |",
        f"| 賠的筆數／平均 | {result['lost']:,}／{_pct(result['lost_mean'], 3)} |",
        f"| 報酬剛好 0 的筆數 | {result['zero']:,} |",
        f"| 平均持有天數 | {lib.num(result['holding_mean'], 2)} |",
        f"| 放棄比例（放棄 ÷ 訊號） | {_pct(result['abandon_rate'], 1)}"
        f"（{result['abandoned']:,}） |",
    ]
    for reason, count in result["abandon_reasons"].items():
        lines.append(f"| 放棄：{tr.ABANDON_LABELS.get(reason, reason)} | {count:,} |")
    for reason in tr.EXIT_REASONS:
        lines.append(
            f"| 出場：{tr.EXIT_LABELS[reason]} | {_pct(result['exit_share'][reason], 1)}"
            f"（{result['exits'][reason]:,}） |"
        )
    lines += [
        f"| 同一根兩邊都碰到（算停損） | {result['both_touched']:,} |",
        f"| 跳空成交 | {result['gapped']:,} |",
        f"| 跌停順延 | {result['limit_delayed']:,} |",
        f"| 停牌順延 | {result['suspension_delayed']:,} |",
        f"| 進場遇漲停鎖死的日子 | {result['entry_limit_blocked']:,} |",
        f"| 母體在 e 買不進的檔次 | {result['population_unbought']:,} |",
        f"| 低於下緣成交 | {result['below_lower']:,} |",
        f"| 大盤濾網擋下的天數 | {result['filter_blocked_days']:,} |",
        f"| 大盤濾網缺值的天數 | {result['filter_missing_days']:,} |",
        "",
        *listed_lines(name, result["listed"]),
        "",
        "限制：逐筆平均假設每個訊號都買得到、每筆等額，不是一個帳戶的資金曲線；"
        "持有期間互相重疊，t 以「日數 ÷ 20」計只是保守的下限。",
    ]
    if name == "C1":
        lines.append(
            "C1 的限制：成員表一個月一份；上市的分類除了 2023 年那一次仍是回溯的；"
            f"成員表只到 {ms.MEMBERS_LAST}，之後的 T 都用那一份。"
        )
    lines.append("")
    return "\n".join(lines)


def _cell(value: Any) -> str:
    return tr._cell(value)


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
        "parameters": {key: value for key, value in spec.items() if key != "label"},
        **public(result),
    }
    (out / "tables.json").write_text(
        json.dumps(body, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (out / "summary.md").write_text(
        hypothesis_markdown(result, header), encoding="utf-8"
    )
    trades = result.get("_trades")
    if trades is None:
        return
    with (out / "trades.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(TRADE_FIELDS)
        for trade in trades:
            writer.writerow([_cell(trade.get(key)) for key in TRADE_FIELDS])
    days: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        if trade["net"] is not None:
            days[trade["signal_date"]].append(trade)
    with (out / "days.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["signal_date", "trades", "net", "excess", "taiex_excess"])
        for day, rows in sorted(days.items()):
            cells = []
            for key in ("net", "excess", "taiex_excess"):
                values = [row[key] for row in rows if row[key] is not None]
                cells.append(_cell(statistics.fmean(values)) if values else "")
            writer.writerow([day.isoformat(), len(rows), *cells])


def overview_markdown(report: dict[str, Any], sha256: str) -> str:
    segment = report["segment"]
    stage = ex.SEGMENT_NAMES[segment]
    lines = [
        f"explore.json 的 sha256：`{sha256}`",
        "",
        f"# 新策略探索 第 {report['round']} 輪 {stage}（round4_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「第四輪：C1～C4」"
        f"「第四輪實作釋義」「逐筆評估」）；釋義 {DECISION}",
        f"- 引擎：trade_research 第 {tr.VERSION} 版；C1～C4 各只改 S1 的一層",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        f"- 門檻：對母體超額 > 0 且 t ≥ {report['min_t']:.2f}，且扣成本報酬 > 0（訊號日序列）；"
        f"段長下限 {tr.MIN_SEGMENT_DAYS.get(segment, '—')} 日、有成交的訊號日至少 {tr.MIN_DAYS} 日；"
        "研究 DB 要有段內已下市公司",
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
            f"- 前瞻觀察：對母體超額 > 0 但 t < {report['min_t']:.2f}，且扣成本報酬 > 0；"
            "只當紀錄，不算通過、不進產品"
        )
        source = report["exploration"]
        lines.append(f"- 探索段報告：{source['url']}（sha256 `{source['sha256']}`）")
    header = (
        "| 代號 | 段內交易日 | 有成交的訊號日 | 對加權指數超額 | t | 對母體超額 | t "
        "| 扣成本報酬 | 成交筆數 | 放棄比例 | 判定 |"
    )
    rule = (
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"
    )
    lines += ["", "## 判定", "", header, rule]
    for name, row in report["hypotheses"].items():
        lines.append(tr._overview_line(name, row, judged=True))
    if report.get("used"):
        lines += ["", "## 已用段（驗證通過的假設，只列出、不判定）", "", header, rule]
        for name, row in report["used"].items():
            lines.append(tr._overview_line(name, row, judged=False))
    lines += [
        "",
        "各假設的數字、只列出的欄位與各自的另列見 `<代號>/summary.md`，逐筆見 `<代號>/trades.csv`。",
        "",
    ]
    return "\n".join(lines)


def coverage_markdown(body: dict[str, Any]) -> str:
    window_ = body["window"] or {}
    years = body["years"]
    lines = [
        f"# 新策略探索 第 {body['round']} 輪 C1～C4 資料覆蓋（探索段，不含報酬）",
        "",
        f"- round4_research 第 {VERSION} 版；定義雜湊 `{body['definitions_sha256']}`",
        ms._members_line(),
        f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}，"
        f"alembic `{body['copy']['alembic']}`",
        f"- 訊號日 {window_.get('first_signal', '—')}～{window_.get('last_signal', '—')}，"
        f"{window_.get('days', 0)} 日",
        "- 口徑（#878 決定 7045084254）：探索段每個訊號日都數，不套大盤濾網（擋下與缺值的天數"
        "另列）、不扣占用；C1 用整個母體，C2、C4 是當天不扣占用的前 10 名，C3 數 S1 選股"
        "（`revenue_yoy` > 0、ATR14 > 0）之後的檔次。和正式跑 `summary.md` 的另列"
        "（濾網通過的日子、扣占用）不是同一個口徑",
        "- C4（#878 決定 7045083358）：只跑進場（`trade_research.enter_zone`，T 之後最多 3 根），"
        "用成交價判夾住；沒跑出場，不算報酬、淨值或勝率，不記占用，不寫成交價。"
        "每筆的進場與停損算法和正式跑相同；樣本差在不套大盤濾網、不扣占用",
        f"- 重現：`{body['command']}`",
        "",
        "## 大盤濾網（S1 的）",
        "",
        "| 年 | 訊號日 | 通過 | 擋下 | 缺值 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for year, row in years.items():
        lines.append(
            f"| {year} | {row.get('days', 0):,} | {row.get('filter_passed', 0):,} "
            f"| {row.get('filter_blocked', 0):,} | {row.get('filter_missing', 0):,} |"
        )
    lines += [
        "",
        "## C1 族群（整個母體）",
        "",
        *c1_lines(body["c1"]),
        "",
        "## C2 前 10 名裡第一鍵缺值",
        "",
        "| 年 | 前 10 名的檔次 | `both_buy_days` 缺值 | 比例 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for year, row in years.items():
        top, missing = row.get("c2_top", 0), row.get("c2_missing", 0)
        lines.append(f"| {year} | {top:,} | {missing:,} | {_share(missing, top)} |")
    lines += [
        "",
        "## C3 融資（S1 選股之後的檔次）",
        "",
        *c3_lines(body["c3"]),
        "",
        "## C4 價位帶（S1 的前 10 名，只用 T 以前的資料）",
        "",
        "| 年 | 前 10 名 | 算得出價位帶 | 退回 S1："
        + " | 退回 S1：".join(FALLBACK_LABELS[reason] for reason in FALLBACK_REASONS)
        + " |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for year, row in years.items():
        top = row.get("c4_top", 0)
        fallbacks = [row.get(f"c4_no_band_{reason}", 0) for reason in FALLBACK_REASONS]
        lines.append(
            f"| {year} | {top:,} | {top - sum(fallbacks):,} | "
            + " | ".join(f"{value:,}（{_share(value, top)}）" for value in fallbacks)
            + " |"
        )
    lines += [
        "",
        "## C4 停損來源（上表中進場區有成交的；夾住用成交價，不算報酬）",
        "",
        "| 年 | 有成交 | "
        + " | ".join(SOURCE_LABELS[s] for s in STOP_SOURCES)
        + " | 沒有成交 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for year, row in years.items():
        cells = [row.get(f"c4_source_{source}", 0) for source in STOP_SOURCES]
        filled = sum(cells)
        lines.append(
            f"| {year} | {filled:,} | "
            + " | ".join(f"{value:,}（{_share(value, filled)}）" for value in cells)
            + f" | {row.get('c4_unfilled', 0):,} |"
        )
    lines.append("")
    return "\n".join(lines)


def _row(result: dict[str, Any]) -> dict[str, Any]:
    return tr._row(result)


# --- the runs ----------------------------------------------------------------------


def _header(db: Path, segment: str, command: str, read_until: date) -> dict[str, Any]:
    return {
        "tool": TOOL,
        "version": VERSION,
        "design": DESIGN,
        "registration_commit": REGISTRATION_COMMIT,
        "engine": {"tool": tr.TOOL, "version": tr.VERSION},
        "segment": segment,
        "round": ROUND,
        "round_size": ROUND_SIZE,
        "cumulative": CUMULATIVE,
        "definitions_sha256": definitions_sha256(),
        "members_sha256": ms.MEMBERS_SHA256,
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


def run_coverage(
    db: Path,
    out: Path,
    members: Path,
    command: str = "",
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, Any]:
    """``--coverage-only``: the exploration segment's coverage, no return, no ledger."""

    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    end = tr.SEGMENTS[EXPLORATION][1]
    loaded = load(db, members, load_from(EXPLORATION), end, out / RAW_DIR_NAME)
    header = _header(db, EXPLORATION, command, end)
    body = {
        **header,
        "coverage_only": True,
        **coverage(loaded, EXPLORATION, progress),
        "elapsed_seconds": time.monotonic() - started,
    }
    (out / "coverage.json").write_text(
        json.dumps(body, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (out / "coverage.md").write_text(coverage_markdown(body), encoding="utf-8")
    return {"out": str(out.resolve()), "coverage_only": True}


def run_exploration(
    db: Path,
    out: Path,
    names: list[str],
    members: Path,
    command: str = "",
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, Any]:
    """``names`` on the exploration segment; nothing after its end read."""

    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    end = tr.SEGMENTS[EXPLORATION][1]
    loaded = load(db, members, load_from(EXPLORATION), end, out / RAW_DIR_NAME)
    header = _header(db, EXPLORATION, command, end)
    report = {**header, "min_t": tr.MIN_T, "selected": list(names), "hypotheses": {}}
    results = run_segment(loaded, db, list(names), EXPLORATION, progress=progress)
    for name in names:
        write_hypothesis(out / name, results[name], header)
        report["hypotheses"][name] = _row(results[name])
        progress(f"{name}: {results[name]['verdict']}")
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
    members: Path,
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
    end = tr.SEGMENTS[VALIDATION][1]
    loaded = load(db, members, load_from(VALIDATION), end, out / RAW_DIR_NAME)
    header = _header(db, VALIDATION, command, end)
    min_t = ex.validation_min_t(CUMULATIVE)
    report = {**header, "min_t": min_t, "exploration": source, "hypotheses": {}}
    results = run_segment(loaded, db, names, VALIDATION, min_t=min_t, progress=progress)
    for name in names:
        write_hypothesis(out / name, results[name], header)
        report["hypotheses"][name] = _row(results[name])
        progress(f"{name}: {results[name]['verdict']}")
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
    passed = [name for name in names if report["hypotheses"][name]["verdict"] == PASSED]
    if passed:  # the used segment only for the passed ones
        used_end = tr.SEGMENTS[USED][1]
        used = load(db, members, load_from(USED), used_end, out / RAW_DIR_NAME)
        results = run_segment(used, db, passed, USED, progress=progress)
        report["used"] = {}
        for name in passed:
            write_hypothesis(out / name / USED, results[name], header)
            report["used"][name] = _row(results[name])
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
    parser = argparse.ArgumentParser(prog="round4_research.py", description=__doc__)
    parser.add_argument(
        "--db", required=True, help="the research DB (/research/stock.db)"
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--segment", required=True, choices=STAGES)
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    parser.add_argument(
        "--members",
        help="the #779 member table (default: research/industry_members/"
        f"{ms.MEMBERS_NAME} beside the DB); its sha256 must be MEMBERS_SHA256",
    )
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help="exploration only: dates, counts and missing shares, no return",
    )
    parser.add_argument(
        "--hypotheses",
        help="exploration (required, not with --coverage-only): the registered "
        "hypotheses, comma separated, e.g. C1,C2; each runs once per tool version",
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
    members = Path(args.members) if args.members else ms.members_path(db)
    problems = [*tr.er.refusals(db, args.min_free_gb), *ms.members_problems(members)]
    names: list[str] = []
    if args.segment == EXPLORATION and not args.coverage_only:
        chosen, names = ex.exploration_problems(
            db, args.hypotheses, HYPOTHESES, VERSION
        )
        problems = [*problems, *chosen]
    if problems:
        print(json.dumps({"refused": problems}, ensure_ascii=False))
        return 2
    command = "python tools/research/round4_research.py " + " ".join(argv)
    progress = lambda text: print(text, file=sys.stderr, flush=True)  # noqa: E731
    if args.segment == EXPLORATION and args.coverage_only:
        line = run_coverage(db, Path(args.out), members, command, progress=progress)
    elif args.segment == EXPLORATION:
        line = run_exploration(
            db, Path(args.out), names, members, command, progress=progress
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
            members,
            command,
            progress=progress,
        )
    print(json.dumps(line, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
