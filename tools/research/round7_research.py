"""Round 7 of the new-strategy exploration: Y1～Y4 (#912).

docs/spec/evidence.md 第七輪：Y1～Y4 and 第七輪實作釋義: the hypotheses were
registered (commit ``a5d32c89``, #910, decision 7054127449) before anyone ran a
tool on the backfilled history.  Nothing here is a command-line option: a
change of a definition is a new code.

They are not in ``explore_research.HYPOTHESES``, ``round5_research`` nor
``round6_research``: their ``definitions_sha256`` hash the whole table, so
adding them would make the validation refuse the exploration reports already
run.  The engine, the population, ``explore_judge``, the gate, the ledgers, the
"small first" order (``round5_research.order_key``), ``turnover_60``,
``feature_evidence._momentum``／``_mean_volume`` and the member table
(``mainstream_research``: ``group_members``, ``instrument_on``, ``group_of``
with ``REMAP_2023``, as C1) are imported; new here are only
``margin_flow_20``, ``turnover_cv_240``, ``delay_52w`` and ``ind_rev_20``.

Each signal date T (after its close, only T's data and before; the member
snapshot with ``snapshot_date <= T``):

- Y1: ``margin_flow_20`` small first — (margin_balance[at] − margin_balance[at
  − 20]) × 1,000 ÷ ``_mean_volume`` (the 20 bars before T, shares); the
  balance is in lots of 1,000 shares.  Missing with at < 20, no chip row or a
  null balance on either bar, or a mean volume missing or ≤ 0; both balances
  0 is 0.  N 20, K 60.
- Y2: ``turnover_cv_240`` small first — the sample standard deviation (ddof
  1) over the mean of the 240 official unadjusted turnovers at − 239 .. at;
  missing with fewer than 240 bars, a ``turnover_status`` not ``available``,
  a suspended bar, or a mean ≤ 0.  N 20, K 60.
- Y3: ``delay_52w`` high first — on the market sessions s_j = T − 5j, j = 0 ..
  52, the weekly returns r_j (adjusted closes) and m_j (TAIEX), j = 0 .. 51;
  over j = 0 .. 47, 1 − R²(r on m_j) ÷ R²(r on m_j .. m_{j+4}).  Missing with
  any of the 53 points without a bar, suspended, a close missing or ≤ 0, a
  TAIEX close missing, or R²(unrestricted) ≤ 0.  N 20, K 60.
- Y4: the 150 highest ``turnover_60`` of the population (a missing value out,
  ties by the hash), then ``ind_rev_20`` small first inside them —
  ``momentum_20`` minus the mean ``momentum_20`` of T's whole population in
  the same group (this one included); missing without ``momentum_20``,
  without a group, or with fewer than 5 valued in the group; a missing value
  keeps its place in the 150, ranked last.  N 20, K 20.

A missing key is last whether high or low first; ties by
``portfolio_research.tie_break``.  ``portfolio_research.simulate`` (K accounts,
1/20 of the account's cash each) trades; the benchmark is the same engine over
the day's whole population.  ``explore_research.explore_judge`` judges with
t ≥ 2 on the exploration and the fixed Bonferroni t ≥ 3.144 (30 hypotheses)
on the validation.  The segments, floors, public check, the gate (the
exploration once per version, the validation once after a published
exploration report, the ledger writable before anything is read) and the
ledgers (``explore-ledger.json`` beside the DB and the repository's
``tools/research/explore_ledger.json``, each entry with
``"tool": "round7_research"``) are ``explore_research``'s; the member table
and its refusal are ``mainstream_research``'s.

The exploration reads the copy from its start; a later segment reads 730
calendar days of warm-up before it (as round 5: Y3's 261 sessions and Y2's
240 bars are inside).  Before the used segment is loaded the validation's
panel is let go (PR #905 review).  ``--coverage-only`` writes the share of
missing values per year (Y1 also per market) and the time of the features, no
return at all.
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
from bisect import bisect_left
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
import round5_research as r5  # noqa: E402

VERSION = 1
DESIGN = "912"
TOOL = "round7_research"
REGISTRATION_COMMIT = "a5d32c89"
DECISION = "https://github.com/YiCheng0608/stock-lab/issues/910#issuecomment-7054127449"
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
SEGMENTS = dict(ex.SEGMENTS)
MIN_SEGMENT_DAYS = dict(ex.MIN_SEGMENT_DAYS)
MIN_T = ex.MIN_T  # the exploration's t ≥ 2
# docs 第七輪 門檻: 1 − Φ(z) = 0.025 ÷ 30, z = 3.1440 to the 3rd decimal; fixed,
# not computed when run.
VALIDATION_MIN_T = 3.144
ROUND = 7
ROUND_SIZE = 4
CUMULATIVE = 30  # X1～X8, S1～S3, R1～R2, M1～M2, C1～C4, V1～V3, W1～W4, Y1～Y4
LOAD_FROM = ex.LOAD_FROM  # the exploration reads the copy from its start
WARMUP_CALENDAR_DAYS = ex.WARMUP_CALENDAR_DAYS
MIN_LOTS = lib.DEFAULT_MIN_LOTS
RAW_DIR_NAME = ex.RAW_DIR_NAME
POPULATION = pr.POPULATION
TAIEX = pr.TAIEX

HIGH, LOW = r5.HIGH, r5.LOW
MARGIN_WINDOW = 20  # margin_balance[at] − margin_balance[at − 20]
LOT_SHARES = 1000  # margin_balance is in lots, the volume in shares
CV_WINDOW = 240  # turnovers at − 239 .. at
CV_DDOF = 1
DELAY_STEP = 5  # market sessions a week
DELAY_POINTS = 53  # s_0 .. s_52
DELAY_WEEKS = 48  # j = 0 .. 47 in the regressions
DELAY_LAGS = 4  # m_{j+1} .. m_{j+4}
MOMENTUM_WINDOW = 20
SUBSET_SIZE = 150
MIN_PEERS = 5  # valued members of the group, this one included
# The OTC bars from 2007-04-23 to 2007-11-30 are not read (bar_exclusions.json):
# Y1～Y3 count from the OTC 2007-12-03, as rounds 5 and 6.
OTC_ANCHOR = r5.OTC_ANCHOR
MARKETS = {"TWSE": "上市", "TPEx": "上櫃"}

# The registration (docs 第七輪：Y1～Y4), word for word.  ``start`` as
# ``explore_research``: ("session", anchor, n) is the n-th session counting the
# anchor (or the first session after it) as the first; ("date", d) the first
# session from d.  ``subset``: (feature, n) keeps the n highest of the
# population, a missing value out.  ``keys``: (feature, HIGH | LOW), a missing
# value last either way, ties by ``portfolio_research.tie_break``.
HYPOTHESES: dict[str, dict[str, Any]] = {
    "Y1": {
        "direction": "散戶槓桿",
        "label": "`margin_flow_20`（近 20 根的融資餘額變化 ÷ T 之前 20 根的平均成交量）小者先",
        "rule": "daily",
        "subset": None,
        "keys": (("margin_flow_20", LOW),),
        "top": 20,
        "hold": 60,
        "start": ("session", OTC_ANCHOR, 21),
    },
    "Y2": {
        "direction": "交易活動的變異",
        "label": "`turnover_cv_240`（近 240 根每日成交金額的變異係數）小者先",
        "rule": "daily",
        "subset": None,
        "keys": (("turnover_cv_240", LOW),),
        "top": 20,
        "hold": 60,
        "start": ("session", OTC_ANCHOR, 240),
    },
    "Y3": {
        "direction": "價格延遲",
        "label": "`delay_52w`（個股週報酬加入 4 週大盤落後項後多解釋的比例）大者先",
        "rule": "daily",
        "subset": None,
        "keys": (("delay_52w", HIGH),),
        "top": 20,
        "hold": 60,
        "start": ("session", OTC_ANCHOR, 261),
    },
    "Y4": {
        "direction": "短期反轉",
        "label": "母體中 60 日平均成交金額前 150 名，依 `ind_rev_20`"
        "（20 日報酬 − 同產業母體的 20 日報酬平均）小者先",
        "rule": "daily",
        "subset": ("turnover_60", SUBSET_SIZE),
        "keys": (("ind_rev_20", LOW),),
        "top": 20,
        "hold": 20,
        "start": ("date", date(2013, 2, 1)),
    },
}
OTHER_COMPARISONS = ex.OTHER_COMPARISONS
REASONS = dict(ex.REASONS)
VOLATILE_KEYS = ex.VOLATILE_KEYS
LIMITS = {
    "Y1": "融資大減常發生在股價急跌、斷頭之後，選到的可能是剛重挫的股票，和 V2 的短期反轉有重疊；"
    "V2 只看價格，Y1 看的是誰在賣",
    "Y3": "上櫃股也用加權指數當大盤（兩市場同一個基準，不混用櫃買指數）；加權指數是價格指數、不含股利。"
    "Hou & Moskowitz 用週三到週三的週報酬，這裡每 5 個全市場交易日一週，遇休市不補，是登記時事先定的寫法",
    "Y4": "上市的產業是回溯的（官方產業的逐月成員表的限制），同 C1、M1；成員表只到 2024-09，"
    "驗證段最後一天 2024-09-27 用 2024-08 那一份，已用段一律用 2024-09 那一份，"
    "之後的分類變動與新上市股票看不到",
}
# Listed in picks.csv beside a key (Y4's parts, to recompute it).
PICK_EXTRAS = {"ind_rev_20": ("momentum_20", "industry_20", "peers")}


def definitions() -> dict[str, Any]:
    return {
        "version": VERSION,
        "design": DESIGN,
        "hypotheses": HYPOTHESES,
        "features": {
            "margin_flow_20": {
                "value": "(margin_balance[at] - margin_balance[at-20]) * 1000 / "
                "feature_evidence._mean_volume",
                "window": MARGIN_WINDOW,
                "lot_shares": LOT_SHARES,
                "missing": "at < 20; no chip row or a null margin_balance on at or "
                "at-20; the mean volume missing or <= 0",
                "zero": "both balances 0: 0",
            },
            "turnover_cv_240": {
                "value": "stdev(ddof 1) / mean of market_bars.turnover at-239..at",
                "window": CV_WINDOW,
                "ddof": CV_DDOF,
                "missing": "fewer than 240 bars; a turnover_status not available; "
                "a suspended bar; a mean <= 0",
            },
            "delay_52w": {
                "points": "Panel.sessions T - 5j, j = 0..52",
                "step": DELAY_STEP,
                "count": DELAY_POINTS,
                "weeks": DELAY_WEEKS,
                "lags": DELAY_LAGS,
                "value": "1 - R2(r_j = a + b m_j) / R2(r_j = a + b m_j + c1 m_j+1 "
                ".. c4 m_j+4), j = 0..47; r on Series.close, m on Panel.index_close",
                "missing": "a point without a bar, suspended, a close missing or "
                "<= 0; a TAIEX close missing or <= 0; R2(unrestricted) <= 0 or "
                "undefined (no variance of r, a singular market design)",
            },
            "ind_rev_20": {
                "value": "momentum_20 - mean momentum_20 of T's whole population "
                "in the group with a value, this one included",
                "momentum": "feature_evidence._momentum",
                "sessions": MOMENTUM_WINDOW,
                "min_peers": MIN_PEERS,
                "groups": "mainstream_research.group_members (snapshot_date <= T)",
                "several_groups": "the smallest group id",
                "missing": "momentum_20 missing; no group on T; fewer than 5 valued "
                "in the group",
            },
            "turnover_60": {
                "function": "explore_research.turnover_60",
                "window": ex.TURNOVER_WINDOW,
                "available": ex.TURNOVER_AVAILABLE,
            },
        },
        # the member table and its rules are M1／M2's (docs 第三輪 官方產業的成員)
        "members": ms.definitions()["members"],
        "order": "missing last for high and low first; ties sha256(<T>:<instrument_id>)",
        "subset": "the n highest, a missing value out, ties by the hash; before the "
        "order; a missing key keeps its place",
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
    member table, the segments, both thresholds, the costs).  A changed tool
    needs a new exploration report before a validation."""

    text = json.dumps(definitions(), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- reading ----------------------------------------------------------------------


@dataclass
class Context:
    """``explore_research``'s context (the market, the turnovers, the quotes),
    the member snapshots (``mainstream_research``'s context on the same
    market), Y3's market part by T's session and the time of each feature."""

    base: ex.Context
    groups: ms.Context | None = None
    delay_market: dict[int, Any] = field(default_factory=dict)
    seconds: Counter = field(default_factory=Counter)

    @property
    def market(self) -> pr.Market:
        return self.base.market

    @property
    def panel(self) -> lib.Panel:
        return self.base.market.panel

    def quote(self, instrument_id: int, s: int) -> pr.Quote | None:
        return self.base.quote(instrument_id, s)


def load(db: Path, members: Path, start: date, end: date, raw_dir: Path) -> Context:
    """The panel, the turnovers and the member snapshots from ``start`` to
    ``end``; nothing after ``end`` is read."""

    base = ex.load_context(db, start, end, raw_dir)
    return Context(base, ms.build_context(base.market, ms.read_members(members, end)))


# --- features ---------------------------------------------------------------------


MOMENTUM_20 = features._momentum(MOMENTUM_WINDOW)


def margin_flow_20(_ctx: Context, item: lib.Series, at: int) -> float | None:
    """(margin_balance[at] − margin_balance[at − 20]) × 1,000 ÷ the mean volume
    of the 20 bars before T (docs 第七輪 Y1 第 1～4 點)."""

    if at < MARGIN_WINDOW:
        return None
    balance = item.chips.get("margin_balance")
    if balance is None:
        return None
    now, then = balance[at], balance[at - MARGIN_WINDOW]
    if now != now or then != then:  # no chip row, or a null balance
        return None
    volume = features._mean_volume(item, at)
    if volume is None or not volume > 0:
        return None
    return (now - then) * LOT_SHARES / volume


def turnover_cv_240(ctx: Context, item: lib.Series, at: int) -> float | None:
    """The sample standard deviation (ddof 1) over the mean of the 240
    unadjusted turnovers ``at − 239 .. at`` (docs 第七輪 Y2 第 1～2 點)."""

    first = at + 1 - CV_WINDOW
    if first < 0:
        return None
    if item.suspended[at + 1] != item.suspended[first]:
        return None  # a suspended bar in first .. at
    values = ctx.base.turnover.get(item.instrument_id)
    if values is None:
        return None
    window = values[first : at + 1]
    if any(value != value for value in window):  # not available
        return None
    mean = sum(window) / CV_WINDOW
    if not mean > 0:
        return None
    variance = sum((value - mean) ** 2 for value in window) / (CV_WINDOW - CV_DDOF)
    return math.sqrt(variance) / mean


@dataclass(frozen=True)
class DelayMarket:
    """Y3's part shared by every stock on T: the sample points, the centred
    market regressors over the 48 weeks and the inverse of their cross
    products."""

    points: tuple[int, ...]  # session indexes s_0 .. s_52
    columns: tuple[tuple[float, ...], ...]  # centred m_{j+k}, k = 0..4
    inverse: tuple[tuple[float, ...], ...]  # (C'C)^-1, 5 × 5
    own: float  # Σ (m_j − mean)², the restricted model's


def _inverse(matrix: list[list[float]]) -> list[list[float]] | None:
    """Gauss-Jordan with partial pivoting; None when singular."""

    n = len(matrix)
    a = [
        row[:] + [1.0 if i == j else 0.0 for j in range(n)]
        for i, row in enumerate(matrix)
    ]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-300:
            return None
        a[col], a[pivot] = a[pivot], a[col]
        head = a[col][col]
        a[col] = [value / head for value in a[col]]
        for r in range(n):
            if r != col and a[r][col] != 0.0:
                factor = a[r][col]
                a[r] = [x - factor * y for x, y in zip(a[r], a[col])]
    return [row[n:] for row in a]


def delay_market(ctx: Context, s: int) -> DelayMarket | None:
    """T's sample points and market regressors (T is session ``s``); None when
    a point is before the copy or a TAIEX close is missing."""

    if s in ctx.delay_market:
        return ctx.delay_market[s]
    out = None
    points = tuple(s - DELAY_STEP * j for j in range(DELAY_POINTS))
    if points[-1] >= 0:
        sessions, index = ctx.panel.sessions, ctx.panel.index_close
        closes = [index.get(sessions[p]) for p in points]
        if all(close is not None and close > 0 for close in closes):
            m = [closes[j] / closes[j + 1] - 1.0 for j in range(DELAY_POINTS - 1)]
            columns = []
            for k in range(DELAY_LAGS + 1):
                column = m[k : k + DELAY_WEEKS]
                mean = sum(column) / DELAY_WEEKS
                columns.append(tuple(value - mean for value in column))
            cross = [
                [sum(x * y for x, y in zip(a, b)) for b in columns] for a in columns
            ]
            inverse = _inverse(cross)
            if inverse is not None and cross[0][0] > 0:
                out = DelayMarket(
                    points,
                    tuple(columns),
                    tuple(tuple(row) for row in inverse),
                    cross[0][0],
                )
    ctx.delay_market[s] = out
    return out


def delay_52w(ctx: Context, item: lib.Series, at: int) -> float | None:
    """1 − R²(restricted) ÷ R²(unrestricted) over the 48 weeks (docs 第七輪 Y3
    第 1～4 點); with centred regressors R² = (q' (C'C)^-1 q) ÷ Σ (r − mean)²,
    q = C' r."""

    market = delay_market(ctx, item.session[at])
    if market is None:
        return None
    sessions, position = ctx.panel.sessions, item.position
    closes = []
    for p in market.points:
        k = position.get(sessions[p])
        if k is None or item.suspended[k + 1] != item.suspended[k]:
            return None
        close = item.close[k]
        if not close > 0:  # NaN fails too
            return None
        closes.append(close)
    r = [closes[j] / closes[j + 1] - 1.0 for j in range(DELAY_WEEKS)]
    mean = sum(r) / DELAY_WEEKS
    total = sum((value - mean) ** 2 for value in r)
    if not total > 0:
        return None  # R² undefined
    q = [sum(x * y for x, y in zip(column, r)) for column in market.columns]
    explained = sum(
        q[i] * sum(row[j] * q[j] for j in range(len(q)))
        for i, row in enumerate(market.inverse)
    )
    unrestricted = explained / total
    if not unrestricted > 0:
        return None
    restricted = q[0] * q[0] / market.own / total
    return 1.0 - restricted / unrestricted


def momentum_20(_ctx: Context, item: lib.Series, at: int) -> float | None:
    value = MOMENTUM_20(item, at)
    return None if value is None or value != value else float(value)


def turnover_60(ctx: Context, item: lib.Series, at: int) -> float | None:
    return ex.turnover_60(ctx.base, item, at)


@dataclass(frozen=True)
class Industry:
    value: float | None  # ind_rev_20
    momentum: float | None
    group: str | None
    mean: float | None  # the group's mean momentum_20
    peers: int  # valued members of the group, this one included
    groups: int  # how many groups the instrument is in on T


def industry_day(
    ctx: Context, day: date, members: list[tuple[lib.Series, int]]
) -> dict[int, Industry]:
    """``ind_rev_20`` of every member of T's population (docs 第七輪 Y4 第 2～5
    點): the group averages run over the whole population, not the subset."""

    momentum = {item.instrument_id: momentum_20(ctx, item, at) for item, at in members}
    groups_of: dict[int, list[str]] = defaultdict(list)
    if ctx.groups is not None:
        grouped, _retro, _remapped = ms.group_members(ctx.groups, day)
        for group_id, ids in grouped.items():
            for instrument_id in ids:
                if instrument_id in momentum:
                    groups_of[instrument_id].append(group_id)
    totals: dict[str, list[float]] = defaultdict(list)
    for instrument_id, groups in groups_of.items():
        value = momentum[instrument_id]
        if value is not None:
            for group_id in groups:
                totals[group_id].append(value)
    out = {}
    for instrument_id, value in momentum.items():
        groups = sorted(groups_of.get(instrument_id, ()))
        group = groups[0] if groups else None
        peers = len(totals.get(group, ())) if group is not None else 0
        mean = statistics.fmean(totals[group]) if peers else None
        rev = (
            value - mean
            if value is not None and group is not None and peers >= MIN_PEERS
            else None
        )
        out[instrument_id] = Industry(rev, value, group, mean, peers, len(groups))
    return out


FEATURES: dict[str, Callable[[Context, lib.Series, int], float | None]] = {
    "margin_flow_20": margin_flow_20,
    "turnover_cv_240": turnover_cv_240,
    "delay_52w": delay_52w,
    "turnover_60": turnover_60,
}
FEATURE_LABELS = {
    "margin_flow_20": "融資餘額 20 根變化 ÷ 均量",
    "turnover_cv_240": "240 根成交金額變異係數",
    "delay_52w": "價格延遲",
    "turnover_60": "60 日平均成交金額",
    "ind_rev_20": "20 日報酬 − 同產業平均",
}


def used_features(spec: dict[str, Any]) -> tuple[str, ...]:
    names: list[str] = []
    if spec["subset"]:
        names.append(spec["subset"][0])
    names += [name for name, _direction in spec["keys"]]
    return tuple(dict.fromkeys(names))


# --- the order --------------------------------------------------------------------


order_key = r5.order_key


@dataclass
class Ranked:
    rows: list[tuple[int, dict[str, float | None], str]]
    missing: Counter
    subset: int = 0  # members in the subset
    subset_missing: Counter = field(default_factory=Counter)
    markets: dict[str, Counter] = field(default_factory=dict)  # Y1: by exchange
    reasons: Counter = field(default_factory=Counter)  # Y4: why ind_rev_20 is missing
    no_index: bool = False  # Y3: T's market part missing


def rank(
    ctx: Context,
    spec: dict[str, Any],
    day: date,
    members: list[tuple[lib.Series, int]],
) -> Ranked:
    """The day's members in the hypothesis's order (the subset first) and the
    counts of missing values."""

    names = used_features(spec)
    out = Ranked([], Counter())
    industry: dict[int, Industry] = {}
    if "ind_rev_20" in names:
        started = time.perf_counter()
        industry = industry_day(ctx, day, members)
        ctx.seconds["ind_rev_20"] += time.perf_counter() - started
    rows = []
    for item, at in members:
        values: dict[str, float | None] = {}
        for name in names:
            started = time.perf_counter()
            if name == "ind_rev_20":
                parts = industry[item.instrument_id]
                values[name] = parts.value
                values["momentum_20"] = parts.momentum
                values["industry_20"] = parts.mean
                values["peers"] = parts.peers
                if parts.value is None:
                    out.reasons[
                        "momentum"
                        if parts.momentum is None
                        else "no_group"
                        if parts.group is None
                        else "few_peers"
                    ] += 1
                out.reasons["several_groups"] += parts.groups > 1
            else:
                values[name] = FEATURES[name](ctx, item, at)
            ctx.seconds[name] += time.perf_counter() - started
            out.missing[name] += values[name] is None
        if "margin_flow_20" in names:
            exchange = ctx.panel.symbols.get(item.instrument_id, ("",))[0]
            market = out.markets.setdefault(exchange, Counter())
            market["members"] += 1
            market["missing"] += values["margin_flow_20"] is None
        rows.append((item.instrument_id, values, pr.tie_break(day, item.instrument_id)))
    if "delay_52w" in names and members:
        out.no_index = delay_market(ctx, members[0][0].session[members[0][1]]) is None
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
    names = used_features(spec)
    for name in names:
        year["missing"][name] = year["missing"].get(name, 0) + r.missing[name]
    if spec["subset"]:
        year["subset"] = year.get("subset", 0) + r.subset
        missing = year.setdefault("subset_missing", {})
        for name, _direction in spec["keys"]:
            missing[name] = missing.get(name, 0) + r.subset_missing[name]
    if "margin_flow_20" in names:
        markets = year.setdefault("markets", {})
        for exchange, counts in r.markets.items():
            row = markets.setdefault(exchange, {"members": 0, "missing": 0})
            row["members"] += counts["members"]
            row["missing"] += counts["missing"]
    if "ind_rev_20" in names:
        reasons = year.setdefault("reasons", {})
        for key in ("momentum", "no_group", "few_peers", "several_groups"):
            reasons[key] = reasons.get(key, 0) + r.reasons[key]
    if "delay_52w" in names:
        year["no_index_days"] = year.get("no_index_days", 0) + r.no_index


def plan(
    ctx: Context, spec: dict[str, Any], first: int, last: int, keep_rows: bool = True
) -> Plan:
    """The picks, the population and the coverage on the signal dates
    ``first − 1`` .. ``last − 1`` (only T's data and before is read)."""

    panel = ctx.panel
    out = Plan()
    top = spec["top"]
    names = used_features(spec)
    extras = pick_extras(spec)
    for at in range(first - 1, last):
        day = panel.sessions[at]
        members = lib.universe(panel, day, MIN_LOTS)
        ranked = rank(ctx, spec, day, members)
        _coverage_add(out.coverage, spec, day, len(members), ranked)
        out.signal_days += 1
        if keep_rows:
            out.picks[at + 1] = [row[0] for row in ranked.rows]
            out.population[at + 1] = [item.instrument_id for item, _ in members]
        else:
            continue
        for place, (instrument_id, values, tie) in enumerate(ranked.rows[:top], 1):
            exchange, symbol, _ = panel.symbols.get(instrument_id, ("", "", ""))
            out.rows.append(
                {
                    "signal_date": day.isoformat(),
                    "rank": place,
                    "exchange": exchange,
                    "symbol": symbol,
                    **{name: values[name] for name in (*names, *extras)},
                    "tie": tie[:12],
                }
            )
    return out


def pick_extras(spec: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        extra for name in used_features(spec) for extra in PICK_EXTRAS.get(name, ())
    )


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
TRADE_FIELDS = r5.TRADE_FIELDS
_row = r5._row


def _mean(count: int, days: int) -> str:
    return lib.num(count / days, 2) if days else "—"


def coverage_lines(name: str, coverage: dict[str, Any]) -> list[str]:
    spec = HYPOTHESES[name]
    names = used_features(spec)
    head = ["年", "日數", "母體檔次", *(f"{FEATURE_LABELS[n]} 缺值" for n in names)]
    keys = [key for key, _direction in spec["keys"]]
    if spec["subset"]:
        head += ["子集合檔次", *(f"子集合內 {FEATURE_LABELS[k]} 缺值" for k in keys)]
    y4 = "ind_rev_20" in names
    if y4:
        head += [
            "母體中 20 日報酬缺值",
            "母體中 T 日沒有族群",
            "母體中同族群有值 < 5",
            "母體中屬於多個族群的檔次",
        ]
    if "delay_52w" in names:
        head += ["加權指數缺值的日數"]
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
        if y4:
            reasons = row.get("reasons", {})
            cells += [
                _share(reasons.get(key, 0), members)
                for key in ("momentum", "no_group", "few_peers")
            ]
            cells.append(f"{reasons.get('several_groups', 0):,}")
        if "delay_52w" in names:
            cells.append(f"{row.get('no_index_days', 0):,}")
        lines.append(f"| {year} | " + " | ".join(cells) + " |")
    return lines


def market_lines(coverage: dict[str, Any]) -> list[str]:
    """Y1 第 6 點: the share of missing ``margin_flow_20`` by year and market."""

    lines = [
        "| 年 | 上市母體檔次 | 上市缺值 | 上櫃母體檔次 | 上櫃缺值 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for year, row in sorted(coverage.items()):
        cells = []
        for exchange in MARKETS:
            counts = row.get("markets", {}).get(exchange, {"members": 0, "missing": 0})
            cells += [
                f"{counts['members']:,}",
                _share(counts["missing"], counts["members"]),
            ]
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
        f"# {name} {segment}（round7_research 第 {VERSION} 版，#{DESIGN}）",
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
    if name == "Y4":
        lines.append(ms._members_line())
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
            *coverage_lines(name, result["coverage"]),
            "",
        ]
        if name == "Y1":
            lines += [
                "### Y1 依市場的缺值比例",
                "",
                *market_lines(result["coverage"]),
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
    fields = [
        "signal_date",
        "rank",
        "exchange",
        "symbol",
        *used_features(spec),
        *pick_extras(spec),
        "tie",
    ]
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
        f"# 新策略探索 第 {report['round']} 輪 {stage}（round7_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「第七輪：Y1～Y4」）：{DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`；成員表 sha256 `{ms.MEMBERS_SHA256}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        _threshold_line(segment, report["min_t"]),
        *(f"- {name} 的限制：{text}" for name, text in LIMITS.items()),
        ms._members_line(),
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
        f"# 新策略探索 第 {body['round']} 輪 Y1～Y4 資料覆蓋（探索段，不含報酬）",
        "",
        f"- round7_research 第 {VERSION} 版；定義雜湊 `{body['definitions_sha256']}`",
        f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}，"
        f"alembic `{body['copy']['alembic']}`",
        f"- 重現：`{body['command']}`",
        f"- 耗時 {body.get('elapsed_seconds', 0):.0f} 秒（載入 {body.get('load_seconds', 0):.0f} 秒），"
        f"峰值記憶體 {lib.num(body.get('peak_memory_gb'), 2)} GB，"
        f"日線 {body.get('bars', 0):,} 根",
        "- 缺值比例的分母是母體檔次（每個訊號日的母體加總）；子集合內的比例分母是子集合檔次",
        "- Y4 的三種缺值原因依序判（20 日報酬缺值、T 日沒有族群、同族群有值 < 5），一檔只算一種；"
        "「屬於多個族群」另列，取族群代號最小的那個",
        "- 各假設用自己的訊號日（起日寫在各段標題）",
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
        if name == "Y1":  # docs 第七輪 Y1 第 6 點
            lines += [
                "### Y1 第 6 點：依年、依市場的 `margin_flow_20` 缺值比例",
                "",
                "分母是該市場的母體檔次；某一年某一市場缺值異常高時，先在工具單提問、"
                "不跑 Y1 的探索段。",
                "",
                *market_lines(row["coverage"]),
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
        "members_sha256": ms.MEMBERS_SHA256,
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
    members: Path,
    command: str = "",
    coverage_only: bool = False,
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, Any]:
    """``names`` on the exploration segment (every hypothesis for the
    coverage); nothing after its end read."""

    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    end = SEGMENTS[EXPLORATION][1]
    ctx = load(db, members, load_from(EXPLORATION), end, out / RAW_DIR_NAME)
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
    end = SEGMENTS[VALIDATION][1]
    ctx = load(db, members, load_from(VALIDATION), end, out / RAW_DIR_NAME)
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
        used_ctx = load(
            db, members, load_from(USED), SEGMENTS[USED][1], out / RAW_DIR_NAME
        )
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
    parser = argparse.ArgumentParser(prog="round7_research.py", description=__doc__)
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
        help="exploration only: the share of missing values per year (Y1 also "
        "per market) and the time of the features, no return",
    )
    parser.add_argument(
        "--hypotheses",
        help="exploration (required, not with --coverage-only): Y1, Y2, Y3, Y4 or "
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
    members = Path(args.members) if args.members else ms.members_path(db)
    problems = [
        *lib._load("exit_research").refusals(db, args.min_free_gb),
        *ms.members_problems(members),
    ]
    names: list[str] = []
    if args.segment == EXPLORATION and not args.coverage_only:
        chosen, names = ex.exploration_problems(
            db, args.hypotheses, HYPOTHESES, VERSION
        )
        problems = [*problems, *chosen]
    if problems:
        print(json.dumps({"refused": problems}, ensure_ascii=False))
        return 2
    command = "python tools/research/round7_research.py " + " ".join(argv)
    progress = lambda text: print(text, file=sys.stderr, flush=True)  # noqa: E731
    if args.segment == EXPLORATION:
        line = run_exploration(
            db,
            Path(args.out),
            names,
            members,
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
            members,
            command,
            progress=progress,
        )
    print(json.dumps(line, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
