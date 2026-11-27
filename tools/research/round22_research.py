"""Round 22 of the new-strategy exploration: AE1 (#1080).

docs/spec/evidence.md 第二十二輪：AE1 and 第二十二輪實作釋義: the hypothesis
was registered (commit ``f43c86f2``, #1073, decision 7205488990) before
anyone ran a tool on the backfilled history.  Nothing here is a command-line
option: a change of a definition is a new code.

It is not in ``explore_research.HYPOTHESES``, ``trade_research.HYPOTHESES``
nor ``round4_research`` .. ``round21_research``: their ``definitions_sha256``
hash the whole table, so adding it would make the validation refuse the
exploration reports already run.  AE1 is judged trade by trade as J3: the
trades, their settlement, the occupancy and the numbers are
``trade_research``'s (``TradeBars``, ``_trade_row``, ``settle``,
``baseline``, ``stats``, ``State``), the exit without a stop or a target
``round9_research``'s (``enter_next_open``, ``NO_STOP``, ``trade_context``).
The population (``evidence_lib.universe``), the loading
(``explore_research.load_context``, its MOPS list), ``explore_judge``, the
gate and the ledgers are imported; ``ann_date`` and the subject rule are
``round21_research``'s (``announced``, ``ann_date``) word for word, AD1's
list ``round21_research.plan_ad1`` itself, the reference's leaving out
``round21_research._reference`` (G1's) and the overlap
``round10_research``'s.  New here are only the announcement session a,
EAR, AE1's signals, the reference's baseline and the listed numbers.

Each (F, q) with an ``ann_date``: a is the first session on or after it,
EAR is close(a+1) ÷ close(a−2) − 1 less the equal-weight mean of the same
window over T's population (T = a+1, only the members with both closes);
EAR > 0 is a signal on T, bought at T+1's open (one session; not tradable
or locked at limit up abandons it), sold at the close of the 60th session
counting the fill as the 1st.

``explore_research.explore_judge`` judges with t ≥ 2 on the exploration and
the fixed Bonferroni t ≥ 3.392 (72 hypotheses) on the validation; it also
needs 60 signal dates with a fill (``trade_research.MIN_DAYS``).  Before the
used segment is loaded the validation's panel is let go (PR #905 review).
``--coverage-only`` writes counts of dates, members and missing values and
the time of the features, no return at all.
"""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
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
import exit_research as er  # noqa: E402
import explore_research as ex  # noqa: E402
import portfolio_research as pr  # noqa: E402
import round5_research as r5  # noqa: E402
import round9_research as r9  # noqa: E402
import round10_research as r10  # noqa: E402
import round21_research as r21  # noqa: E402
import trade_research as tr  # noqa: E402

VERSION = 1
DESIGN = "1080"
TOOL = "round22_research"
REGISTRATION_COMMIT = "f43c86f2"
DECISION = (
    "https://github.com/YiCheng0608/stock-lab/issues/1073#issuecomment-7205488990"
)
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
SEGMENTS = dict(ex.SEGMENTS)
MIN_SEGMENT_DAYS = dict(ex.MIN_SEGMENT_DAYS)
MIN_T = ex.MIN_T  # the exploration's t ≥ 2
# docs 第二十二輪 門檻: 1 − Φ(z) = 0.025 ÷ 72, z = 3.3918, 3.392 to the 3rd
# decimal; fixed, not computed when run.
VALIDATION_MIN_T = 3.392
ROUND = 22
ROUND_SIZE = 1
# X1～X8, S1～S3, R1～R2, M1～M2, C1～C4, V1～V3, W1～W4, Y1～Y4, Z1～Z4, B1～B3,
# F1～F4, L1～L4, J1～J4, U1～U3, K1～K3, P1～P3, N1～N3, A1～A3, G1～G2, D1～D2,
# AB1～AB2, AD1, AE1
CUMULATIVE = 72
MIN_DAYS = tr.MIN_DAYS  # signal dates with a fill, per segment
OVERLAP = tr.OVERLAP  # t_stat's overlap, 20 (a floor for a 60-day hold)
# Every segment reads the copy from its start, as round10_research ..
# round21_research.
LOAD_FROM = ex.LOAD_FROM
LOAD_RULE = "every segment from LOAD_FROM"
MIN_LOTS = lib.DEFAULT_MIN_LOTS
RAW_DIR_NAME = ex.RAW_DIR_NAME
POPULATION = pr.POPULATION
TAIEX = pr.TAIEX
TRADE = "trade"
NO_STOP = r9.NO_STOP  # AE1's exit has no stop and no target

# AE1 第 2 點: a, the first session on or after ann_date (calendar day)
SESSION_RULE = (
    "a = the first session of Panel.sessions on or after ann_date(F, q) "
    "(every market's sessions, not the item's own bars); none in the panel: "
    "no signal"
)
# AE1 第 3 點: close(a + 1) ÷ close(a − 2) − 1, the sessions of Panel.sessions
EAR_BEFORE, EAR_AFTER = 2, 1
CLOSE_RULE = (
    "a close on session k: the item has a bar on Panel.sessions[k], not "
    "suspended, its adjusted close > 0; else missing (a session before the "
    "first or after the last: missing)"
)
MEAN_RULE = (
    "EAR = the item's window return less the equal-weight mean of the window "
    "returns of T's population (evidence_lib.universe(panel, T, MIN_LOTS), "
    "the occupied members and the item itself too), only the members with "
    "both closes; no such member: the mean and EAR missing"
)
EAR_MIN = 0.0  # AE1 第 4 點: EAR > 0, strictly
# AE1 第 4 點
SIGNAL_AFTER = 1  # T = a + 1
SIGNAL_RULE = (
    "T = a + 1, after its close; the item in T's population and not occupied "
    "(trade_research.State.busy); every signal of the day, not ranked, no "
    "cap; reasons in order: not in T's population, occupied, EAR missing, "
    "EAR <= 0"
)
# 第二十二輪實作釋義: ann_date is the first matching one, so one signal per
# item and quarter; two quarters of one item on one T go in the quarters'
# order, the later one is then occupied.
SAME_DAY_RULE = "one item's two quarters on one T: the earlier quarter first"
AE1_START = date(2013, 4, 1)  # 2013Q1's day after the quarter's end
START_RULE = (
    "only the ann_dates on or after the start (2013Q1's day after the "
    "quarter's end): the quarters before are not signals"
)
# AE1 第 6 點 (G1 第 6 點, AD1 第 7 點): what the reference leaves out
REFERENCE_STATUSES = r21.REFERENCE_STATUSES
REFERENCE_RULE = (
    "T's population less the delisted or transferred members with no "
    "ann_date for the signal's quarter (round21_research._reference); "
    "trade_research.baseline on it with the trade's fill and exit sessions"
)
# AE1 第 7 點 (listed only)
AD1 = "AD1"
AD1_RULE = (
    "round21_research.plan_ad1 (AD1's own list) on the segment's sessions from "
    "AD1's start; a name of AD1 in a quarter: on any list of that quarter's "
    "window; the share over AE1's signals of each quarter with an AD1 list "
    "(round10_research.overlap_share), the quarters by T's year"
)

# The registration (docs 第二十二輪：AE1), word for word.  ``start`` as
# ``explore_research``; ``kind`` "event": trade_research._trade_row counts the
# hold from the fill.
HYPOTHESES: dict[str, dict[str, Any]] = {
    "AE1": {
        "engine": TRADE,
        "kind": "event",
        "event": "ear_positive",
        "direction": "事件：公告期間報酬的漂移",
        "label": "(F, q) 這一季的公告交易日 a（`ann_date` 起第一個交易日）前後 a−1～a+1 的報酬"
        "減去同一窗口母體的等權平均（EAR）> 0，T＝a+1 收盤後成訊號，全部符合的訊號；"
        "T+1 開盤成交（期限 1 日）、沒有停損與目標、持有 60 日",
        "market_filter": False,
        "entry_days": 1,
        "stop": None,
        "target": None,
        "hold": 60,
        "start": ("date", AE1_START),
    },
}
OTHER_COMPARISONS = ex.OTHER_COMPARISONS
REASONS = dict(tr.REASONS)  # explore_research's and too_few_trade_days
# The degenerate cases as the code judges them (第二十二輪實作釋義; PR #913
# review: the docs, coverage.md and summary.md say the same words, a test
# reads the docs' tool section for them).
DEGENERATE = {
    "AE1": "這一季（季底次日到法定期限，含期限當天，日曆日）沒有符合主旨規則的公告時沒有 `ann_date`，不成訊號；"
    "同一檔同一季有多則符合的，只取季底次日起的第一則（發言日期最早的）；起日 2013-04-01 以前的 `ann_date`（2012Q4 以前的季）不成訊號；"
    "`Panel.sessions` 沒有 ≥ `ann_date` 的交易日，或 a+1 在 panel 最後一天之後時不成訊號；"
    "這一檔在 a−2 或 a+1 沒有日線、停牌或還原收盤 ≤ 0 時窗口報酬缺值，EAR 缺值、不符合；"
    "母體平均只取 T 的母體（`evidence_lib.universe`，占用中的與這一檔自己都算）裡 a−2 與 a+1 都有收盤的成員，"
    "一個都沒有時平均缺值，EAR 缺值、不符合；EAR 剛好等於 0 不符合；"
    "不符合的原因依序判：T 不在母體、占用中、EAR 缺值、EAR ≤ 0，每筆只算第一個；"
    "同一檔兩季的訊號落在同一個 T 時先算較早的季，較晚的季因占用中不成立；每天的訊號全部進場，不排序、不設上限",
}
OVERLAP_NOTE = {
    "summary_only": "定義照摘要與索引頁，未讀全文；來源只找到工作論文版本",
    "AE1_survivor": "- 存活者偏差（AE1）：下市公司 2014 年起 0 則重大訊息，沒有 `ann_date` 就不成訊號，"
    "偏差方向對假設有利。對照基準（母體去掉這一季沒有 `ann_date` 的下市、轉板股）的超額與 t 在 "
    "`AE1/summary.md`「數字」表的「超額（對對照基準，只列出）」列與 `explore.md` 的「只列出、不判定」",
    "AE1_reference": "對照基準：訊號日 T 的母體去掉「這筆訊號的季沒有 `ann_date` 的 `delisted`／`transferred` 標的」，"
    "同一套逐筆評估（`trade_research.baseline`，同一筆的成交日與出場日）算的基準；列 AE1 對它的超額與 t，"
    "只列出、不判定（判定仍只比母體）",
    "AE1_AD1": 'AE1 與 AD1（`round21_research` 第 1 版的 `HYPOTHESES["AD1"]`，同一季算）名單的重疊比例：'
    "每一季 |AE1 這一季的訊號 ∩ AD1 這一季的名單| ÷ AE1 這一季的訊號數（同一檔同一季算一次）；"
    "AD1 這一季的名單是 `round21_research.plan_ad1` 在這一季的窗口裡任一天選進的檔，"
    "AD1 起日（2014-04-15）以前的季與 AD1 沒有名單的季不計；依 T 的年列各季的平均，另列合計的檔數。只列出、不判定",
    "AE1_listed": "依年（T 的年）、依季（財報的季）：母體裡有 `ann_date` 的檔數（T 在母體裡的 (F, q)）、"
    "其中 EAR 缺值的檔數、EAR > 0 的訊號數與訊號日數（有訊號的不同 T）。只列出、不判定",
}
LIMITS = {
    "AE1": "定義照摘要與轉述（[Quantpedia 摘要](https://quantpedia.com/strategies/post-earnings-announcement-effect/)），"
    "未讀全文；來源①只找到工作論文版本，沒有找到期刊版本；"
    "涵蓋低：主旨規則每個窗口只收到母體的 8.3%～20.2%（#1067 7202828781），名單只會是「會發這則重大訊息的公司」，"
    "不能推到整個母體；存活者偏差：下市公司 2014 年起 0 則，沒有 `ann_date` 不成訊號，偏差方向對假設有利，看對對照基準的超額；"
    "持有 60 日的逐筆之間重疊比 20 日多，t 照逐筆評估用 `overlap=20`、不改，以「日數 ÷ 20」計只是保守的下限，"
    "持有 60 日時實際的重疊更多，t 高估獨立樣本數；"
    "金融業等法定期限不同的公司照樣算，但 `ann_date` 的區間是一般公司的法定期限（同 AD1）；"
    "重大訊息 2024-09-28～2026-08-01 的清單缺口落在已用段，探索段與驗證段（到 2024-09-27）用到的 `ann_date` 都在涵蓋內，"
    "驗證段最後幾筆持有到段末結算；"
    "和 AD1 的關係：同一條主旨規則、同一個 `ann_date`，AD1 的狀態登記時已知（沒有通過），不是 AD1 的變形、也不是看結果挑的："
    "AD1 依去年推的預期公告日、在公告之前持有 5 日，AE1 只在實際公告之後買、依市場對公告的價格反應選、持有 60 日，看和 AD1 的重疊比例；"
    "和 V2、AB2、X4 的關係：V2、AB2 是 20 日報酬小者先（反轉），AE1 是公告的 3 日、EAR 為正的方向（漂移），"
    "窗口與機制都不同；X4 用 EPS 收益率，AE1 不讀季報",
}
ABANDON_LABELS = r9.ABANDON_LABELS
FEATURE_LABELS = {
    "ann_date": "實際公告日",
    "ear": "公告期間的超額報酬（a−1～a+1）",
}
COVERAGE_KEYS = (
    "with_ann",
    "not_member",
    "occupied",
    "missing",
    "not_positive",
    "signals",
    "signal_days",
)


def definitions() -> dict[str, Any]:
    return {
        "version": VERSION,
        "design": DESIGN,
        "hypotheses": HYPOTHESES,
        "features": {
            # the subject rule and ann_date are round21_research's own: its
            # version and hash change when either does
            "ann_date": [
                "round21_research.announced",
                r21.VERSION,
                r21.definitions_sha256(),
            ],
            "session": SESSION_RULE,
            "start": [AE1_START, START_RULE],
            "ear": {
                "window": [EAR_BEFORE, EAR_AFTER],
                "close": CLOSE_RULE,
                "mean": MEAN_RULE,
                "min": EAR_MIN,
            },
            "signal": {
                "after": SIGNAL_AFTER,
                "rule": SIGNAL_RULE,
                "same_day": SAME_DAY_RULE,
            },
            "reference": [
                REFERENCE_RULE,
                list(REFERENCE_STATUSES),
                r21.VERSION,
                r21.definitions_sha256(),
            ],
            "listed": {
                AD1: [r21.HYPOTHESES[AD1], r21.VERSION, AD1_RULE],
                "overlap": [r10.VERSION, r10.DESIGN],
            },
        },
        "event_exit": {
            "entry": "T+1 open, one session; not tradable or locked at limit up "
            "abandons, locked at limit down fills (round9_research.enter_next_open)",
            "stop": "none (settle with NO_STOP)",
            "no_stop": str(NO_STOP),
            "target": "none",
            "hold": "the hold-th market session counting the fill as the 1st; "
            "trade_research.settle's delays, delisting and segment end",
            "trade_research": [tr.VERSION, tr.DESIGN, tr.definitions_sha256()],
            "round9_research": [r9.VERSION, r9.DESIGN, r9.definitions_sha256()],
        },
        "limit": [
            str(er.LIMIT_BEFORE_WIDENING),
            str(er.LIMIT_WIDENED_ON),
            str(er.LIMIT),
        ],  # exit_research.daily_limit by the bar's date (#922)
        "segments": SEGMENTS,
        "min_segment_days": MIN_SEGMENT_DAYS,
        "min_t": MIN_T,
        "validation_min_t": VALIDATION_MIN_T,
        "min_days": MIN_DAYS,
        "overlap": OVERLAP,
        "round": [ROUND, ROUND_SIZE, CUMULATIVE],
        "costs": [tr.SLIPPAGE, tr.COST_BPS],
        "min_lots": MIN_LOTS,
        "load_from": LOAD_FROM,
        "load": LOAD_RULE,
    }


def definitions_sha256() -> str:
    """Hash of every fixed number the verdicts depend on (the definition,
    round21_research's ann_date and subject rule by its hash, a, the EAR
    window, its closes and mean, EAR > 0, T = a+1, one per quarter, the
    entry, the 60-day hold, the reference, AD1's list, the start, the
    segments, the thresholds, the costs).  A changed tool needs a new
    exploration report before a validation."""

    text = json.dumps(definitions(), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- the context ------------------------------------------------------------------


@dataclass
class Context:
    """``explore_research``'s context (the market, the quotes, the MOPS
    list), the trade context on the same market and ``round21_research``'s
    context (``ann_date``, AD1's list) on the same base.  One panel."""

    base: ex.Context
    trade: tr.Context
    ad1: r21.Context | None = None
    seconds: Counter = field(default_factory=Counter)
    load_seconds: dict[str, float] = field(default_factory=dict)
    # T's session -> [(instrument, quarter end, a)]
    events: dict[int, list[tuple[int, date, int]]] | None = None
    # T's session -> (the population mean of the window, the members in it)
    means: dict[int, tuple[float | None, int]] = field(default_factory=dict)
    # the members of the signal date being counted, by instrument
    member_map: dict[int, dict[int, lib.Series]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.ad1 is None:
            self.ad1 = r21.Context(self.base, statuses=self.trade.statuses)

    @property
    def market(self) -> pr.Market:
        return self.base.market

    @property
    def panel(self) -> lib.Panel:
        return self.base.market.panel

    @property
    def statuses(self) -> dict[int, str]:
        return self.trade.statuses


def load(db: Path, start: date, end: date, raw_dir: Path) -> Context:
    """The panel (with the MOPS list) and the trade context to ``end``;
    nothing after ``end`` is read but the date of a delisted or transferred
    stock's last bar (no price)."""

    started = time.monotonic()
    base = ex.load_context(db, start, end, raw_dir)
    panel_seconds = time.monotonic() - started
    t0 = time.monotonic()
    trade = r9.trade_context(base.market, db, end)
    return Context(
        base,
        trade,
        load_seconds={"panel": panel_seconds, "trade": time.monotonic() - t0},
    )


# --- AE1: a, EAR and the signals --------------------------------------------------


def quarter_label(quarter: date) -> str:
    return f"{quarter.year}Q{quarter.month // 3}"


def announcement_session(sessions: list[date], listed: date) -> int | None:
    """AE1 第 2 點: the first session on or after ``listed``."""

    at = bisect_left(sessions, listed)
    return at if at < len(sessions) else None


def events(ctx: Context) -> dict[int, list[tuple[int, date, int]]]:
    """Every (F, q) with an ``ann_date`` on or after the start, by T = a + 1:
    (instrument, quarter end, a), the quarters' order within a day."""

    if ctx.events is None:
        t0 = time.perf_counter()
        found = r21.announced(ctx.ad1)
        ctx.seconds["ann_date"] += time.perf_counter() - t0
        t0 = time.perf_counter()
        sessions = ctx.panel.sessions
        out: dict[int, list[tuple[int, date, int]]] = defaultdict(list)
        for instrument_id, quarters in found.items():
            for quarter, listed in quarters.items():
                if listed < AE1_START:
                    continue
                a = announcement_session(sessions, listed)
                if a is None or a + SIGNAL_AFTER >= len(sessions):
                    continue
                out[a + SIGNAL_AFTER].append((instrument_id, quarter, a))
        for rows in out.values():
            rows.sort(key=lambda row: (row[1], row[0]))
        ctx.events = dict(out)
        ctx.seconds["session"] += time.perf_counter() - t0
    return ctx.events


def close_on(item: lib.Series, sessions: list[date], k: int) -> float | None:
    """The adjusted close on session ``k``, None without a usable one."""

    if not 0 <= k < len(sessions):
        return None
    at = item.position.get(sessions[k])
    if at is None or item.is_suspended(at):
        return None
    close = item.close[at]
    return close if close > 0 else None


def window_return(item: lib.Series, sessions: list[date], a: int) -> float | None:
    """AE1 第 3 點: close(a + 1) ÷ close(a − 2) − 1."""

    before = close_on(item, sessions, a - EAR_BEFORE)
    if before is None:
        return None
    after = close_on(item, sessions, a + EAR_AFTER)
    if after is None:
        return None
    return after / before - 1.0


def population_mean(ctx: Context, s: int) -> tuple[float | None, int]:
    """The equal-weight mean of the window of a = s − 1 over T's population,
    only the members with both closes: (mean or None, members in it)."""

    if s not in ctx.means:
        t0 = time.perf_counter()
        sessions = ctx.panel.sessions
        a = s - SIGNAL_AFTER
        values = [
            value
            for item, _at in ctx.trade.universe(s)
            if (value := window_return(item, sessions, a)) is not None
        ]
        ctx.means[s] = (statistics.fmean(values) if values else None, len(values))
        ctx.seconds["population_mean"] += time.perf_counter() - t0
    return ctx.means[s]


@dataclass(frozen=True)
class Ear:
    # "not_member", "occupied", "missing", "not_positive" or None (a signal)
    reason: str | None
    value: float | None = None
    own: float | None = None
    mean: float | None = None
    item: lib.Series | None = None


def ear(
    ctx: Context, s: int, instrument_id: int, busy: dict[int, int] | None = None
) -> Ear:
    """AE1 第 3、4 點 on T (session ``s``): the first reason that fails, or a
    signal.  ``busy`` is the occupancy (None: not traded, coverage)."""

    if s not in ctx.member_map:
        ctx.member_map.clear()  # one signal date at a time
        ctx.member_map[s] = {
            item.instrument_id: item for item, _at in ctx.trade.universe(s)
        }
    item = ctx.member_map[s].get(instrument_id)
    if item is None:
        return Ear("not_member")
    if busy is not None and busy.get(instrument_id, -1) >= s:
        return Ear("occupied", item=item)
    t0 = time.perf_counter()
    own = window_return(item, ctx.panel.sessions, s - SIGNAL_AFTER)
    ctx.seconds["ear"] += time.perf_counter() - t0
    mean, _n = population_mean(ctx, s)
    if own is None or mean is None:
        return Ear("missing", own=own, mean=mean, item=item)
    value = own - mean
    if not value > EAR_MIN:
        return Ear("not_positive", value, own, mean, item)
    return Ear(None, value, own, mean, item)


def segment_window(
    sessions: list[date], segment: str, spec: dict[str, Any]
) -> tuple[int, int] | None:
    """(first, last) index of the sessions after a signal date of the
    segment (``round12_research.segment_window`` on this tool's segments)."""

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


# --- the listed numbers -----------------------------------------------------------


_reference = r21._reference
overlap_share = r10.overlap_share
overlap_summary = r10.overlap_summary
_window_facts = r5._window_facts
enter_next_open = r9.enter_next_open


@dataclass
class Listed:
    """AE1 第 7 點 by year (T's) and quarter (the report's): the counts, the
    distinct signal dates, the reference's delisted members."""

    years: dict[str, Counter] = field(default_factory=dict)
    quarters: dict[str, Counter] = field(default_factory=dict)
    days: dict[str, set[int]] = field(default_factory=lambda: defaultdict(set))
    quarter_days: dict[str, set[int]] = field(default_factory=lambda: defaultdict(set))

    def add(self, day: date, quarter: date, key: str) -> None:
        self.years.setdefault(str(day.year), Counter())[key] += 1
        self.quarters.setdefault(quarter_label(quarter), Counter())[key] += 1

    def signal(self, s: int, day: date, quarter: date) -> None:
        self.days[str(day.year)].add(s)
        self.quarter_days[quarter_label(quarter)].add(s)

    def tables(self) -> dict[str, Any]:
        def rows(counts, days):
            out = {}
            for key, counter in sorted(counts.items()):
                row = {name: counter.get(name, 0) for name in COVERAGE_KEYS}
                row["signal_days"] = len(days.get(key, ()))
                for extra in ("delisted", "delisted_missing"):
                    row[extra] = counter.get(extra, 0)
                out[key] = row
            return out

        return {
            "years": rows(self.years, self.days),
            "quarters": rows(self.quarters, self.quarter_days),
        }


def count_day(
    ctx: Context,
    listed: Listed,
    s: int,
    busy: dict[int, int] | None = None,
    traded: Callable[[int, date, int, Ear], None] | None = None,
) -> list[tuple[int, date, int, Ear]]:
    """The events of T (session ``s``) counted in ``listed``, in the
    quarters' order; the signals back.  ``traded`` trades each signal before
    the next event is judged, so one item's later quarter on the same T is
    occupied by the earlier one.  ``busy`` None: coverage, no occupancy (the
    signals are not traded, so a later one is never occupied)."""

    day = ctx.panel.sessions[s]
    out = []
    for instrument_id, quarter, a in events(ctx).get(s, ()):
        got = ear(ctx, s, instrument_id, busy)
        if got.reason == "not_member":
            listed.add(day, quarter, "not_member")
            continue
        listed.add(day, quarter, "with_ann")
        if got.reason is not None:
            listed.add(day, quarter, got.reason)
            continue
        listed.add(day, quarter, "signals")
        listed.signal(s, day, quarter)
        out.append((instrument_id, quarter, a, got))
        if traded is not None:
            traded(instrument_id, quarter, a, got)
    return out


def reference_counts(ctx: Context, listed: Listed, s: int, quarters: set[date]) -> None:
    """AE1 第 6 點 (listed only): T's delisted or transferred members and
    those the reference leaves out, once per T and quarter with a signal."""

    t0 = time.perf_counter()
    day = ctx.panel.sessions[s]
    members = ctx.trade.universe(s)
    for quarter in sorted(quarters):
        gone, gone_missing, _excluded = _reference(
            ctx.trade,
            members,
            lambda item: r21.ann_date(ctx.ad1, item.instrument_id, quarter) is None,
        )
        for key, value in (("delisted", gone), ("delisted_missing", gone_missing)):
            listed.years.setdefault(str(day.year), Counter())[key] += value
            listed.quarters.setdefault(quarter_label(quarter), Counter())[key] += value
    ctx.seconds["reference"] += time.perf_counter() - t0


class ReferenceView:
    """``trade_research.baseline``'s context for one quarter: T's population
    less the delisted or transferred members without that quarter's
    ``ann_date`` (``round21_research._reference``), its own cache."""

    def __init__(self, ctx: Context, quarter: date):
        self.ctx, self.quarter = ctx, quarter
        self.baselines: dict[tuple[int, int, int], dict[str, Any]] = {}
        self.universes: dict[int, list[tuple[lib.Series, int]]] = {}

    @property
    def panel(self) -> lib.Panel:
        return self.ctx.panel

    def universe(self, s: int) -> list[tuple[lib.Series, int]]:
        if s not in self.universes:
            self.universes.clear()
            members = self.ctx.trade.universe(s)
            _g, _m, excluded = _reference(
                self.ctx.trade,
                members,
                lambda item: r21.ann_date(
                    self.ctx.ad1, item.instrument_id, self.quarter
                )
                is None,
            )
            self.universes[s] = [
                m for m in members if m[0].instrument_id not in excluded
            ]
        return self.universes[s]


def ad1_names(ctx: Context, first: int, last: int) -> dict[date, set[int]]:
    """AD1's names by quarter: ``round21_research.plan_ad1`` (its own
    definition) on the segment's sessions from AD1's start."""

    t0 = time.perf_counter()
    try:
        spec = r21.HYPOTHESES[AD1]
        sessions = ctx.panel.sessions
        start = ex.start_index(sessions, spec["start"])
        if start is None:
            return {}
        planned = r21.plan_ad1(ctx.ad1, spec, max(first, start + 1), last)
        index = {day: at for at, day in enumerate(sessions)}
        out: dict[date, set[int]] = defaultdict(set)
        for row in planned.days:
            at = index[date.fromisoformat(row["signal_date"])]
            out[date.fromisoformat(row["quarter"])] |= set(
                planned.picks.get(at + 1, ())
            )
        return dict(out)
    finally:
        ctx.seconds["ad1_order"] += time.perf_counter() - t0


def ad1_overlap(
    trades: list[dict[str, Any]], names: dict[date, set[int]]
) -> dict[str, Any]:
    """AE1 第 7 點: per quarter |AE1's signals ∩ AD1's names| ÷ AE1's signals,
    the quarters by T's year; the quarters without an AD1 list not counted."""

    mine: dict[date, list[int]] = defaultdict(list)
    year_of: dict[date, str] = {}
    for trade in trades:
        quarter = date.fromisoformat(trade["quarter"])
        mine[quarter].append(trade["instrument_id"])
        year_of.setdefault(quarter, str(trade["signal_date"].year))
    by_year: dict[str, list[float]] = {}
    signals = both = 0
    for quarter in sorted(mine):
        theirs = names.get(quarter, set())
        share = overlap_share(mine[quarter], theirs)
        if share is None:
            continue
        by_year.setdefault(year_of[quarter], []).append(share)
        signals += len(mine[quarter])
        both += len(set(mine[quarter]) & theirs)
    return {
        **overlap_summary(by_year),
        "signals": signals,
        "both": both,
        "share": both / signals if signals else None,
    }


# --- one segment ------------------------------------------------------------------


def _result(name: str, segment: str) -> dict[str, Any]:
    return {
        "hypothesis": name,
        "engine": HYPOTHESES[name]["engine"],
        "segment": segment,
        "verdict": None if segment == USED else ex.UNDECIDED,
        "reason": None,
        "window": {"days": 0},
        "prerequisites": None,
    }


def _prerequisites(
    db: Path, result: dict[str, Any], segment: str, sessions, first: int, last: int
) -> bool:
    """docs 段長下限、先決條件: False (not run) when they fail."""

    days = last - first + 1
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
        return False
    return True


def trade_signal(
    ctx: Context,
    state: tr.State,
    s: int,
    s_last: int,
    quarter: date,
    a: int,
    got: Ear,
    views: dict[date, ReferenceView],
) -> dict[str, Any]:
    """One signal traded at once: T+1's open, the 60th session's close, the
    population's and the reference's baseline on the same sessions."""

    trade, sessions = ctx.trade, ctx.panel.sessions
    item = got.item
    bars = tr.TradeBars(trade, item, s, s_last)
    entry = enter_next_open(bars)
    listed = r21.ann_date(ctx.ad1, item.instrument_id, quarter)
    row = tr._trade_row(
        trade,
        state,
        s,
        item,
        None,
        bars,
        entry,
        0,
        NO_STOP,
        None,
        s_last,
        {
            "quarter": quarter.isoformat(),
            "ann_date": listed.isoformat() if listed else "",
            "announcement_session": sessions[a].isoformat(),
            "window_return": got.own,
            "population_window": got.mean,
            "ear": got.value,
            "t1_locked_down": entry.session is not None and bars[0].locked_down,
        },
    )
    row["stop"] = None  # no stop: NO_STOP is only settle's argument
    row["reference"] = row["reference_excess"] = None
    if row["net"] is not None:
        t0 = time.perf_counter()
        e = bisect_left(sessions, row["fill_date"])
        x = bisect_left(sessions, row["exit_date"])
        view = views.setdefault(quarter, ReferenceView(ctx, quarter))
        base = tr.baseline(view, s, e, x, s_last)
        row["reference"] = base["mean"]
        if base["mean"] is not None:
            row["reference_excess"] = row["net"] - base["mean"]
        ctx.seconds["reference"] += time.perf_counter() - t0
    return row


def run_trades(
    ctx: Context,
    db: Path,
    name: str,
    segment: str,
    min_t: float = MIN_T,
) -> dict[str, Any]:
    """AE1 on one segment (docs 逐筆評估): its numbers, verdict and trades."""

    spec = HYPOTHESES[name]
    sessions = ctx.panel.sessions
    result = _result(name, segment)
    window = segment_window(sessions, segment, spec)
    if window is None:
        result["reason"] = "no_sessions"
        return result
    first, last = window
    result["window"] = _window_facts(sessions, window)
    if segment != USED:
        if not _prerequisites(db, result, segment, sessions, first, last):
            return result
    ctx.seconds.clear()
    ctx.events = ctx.ad1.announced = None  # timed on each segment
    ctx.means.clear()
    started = time.monotonic()
    state = tr.State(name, spec)
    listed = Listed()
    views: dict[date, ReferenceView] = {}
    locked_down = 0
    for s in range(first - 1, last):

        def traded(_iid: int, quarter: date, a: int, got: Ear) -> None:
            nonlocal locked_down
            row = trade_signal(ctx, state, s, last, quarter, a, got, views)
            locked_down += bool(row["t1_locked_down"])
            state.trades.append(row)  # its occupancy is set: before the next

        signals = count_day(ctx, listed, s, state.busy, traded)
        if signals:
            reference_counts(ctx, listed, s, {row[1] for row in signals})
        state.signal_days += bool(signals)
    result["window"]["signal_days"] = last - first + 1
    numbers = tr.stats(state)
    reference_days = tr.series(state.trades, "reference_excess")
    numbers["reference_excess"] = {
        "days": len(reference_days),
        "mean": statistics.fmean(reference_days) if reference_days else None,
        "t": lib.t_stat(reference_days, overlap=OVERLAP),
    }
    result.update(numbers)
    result["listed"] = {**listed.tables(), "t1_locked_down_fills": locked_down}
    names = ad1_names(ctx, first, last)
    result["overlap"] = {"AE1_AD1": ad1_overlap(state.trades, names)}
    result["seconds"] = {"run": time.monotonic() - started, **ctx.seconds}
    result["_trades"] = state.trades
    if segment == USED:
        return result
    result["min_t"] = min_t
    if numbers["trade_days"] < MIN_DAYS:
        result["reason"] = "too_few_trade_days"
        result["verdict"] = ex.UNDECIDED
    else:
        result["verdict"] = ex.explore_judge(
            segment,
            result["window"]["days"],
            True,
            numbers["excess"],
            numbers["absolute"]["mean"],
            min_t,
        )
    return result


def run_one(
    ctx: Context, db: Path, name: str, segment: str, min_t: float = MIN_T
) -> dict[str, Any]:
    return run_trades(ctx, db, name, segment, min_t)


# --- --coverage-only --------------------------------------------------------------


def event_coverage(ctx: Context, name: str = "AE1") -> dict[str, Any]:
    """AE1 第 7 點 on the exploration without trading: by year and quarter
    the members with an ``ann_date``, EAR missing, the signals and signal
    dates, the reference's delisted members; AD1's list timed.  Every
    signal counts, without the occupancy (nothing is traded)."""

    spec = HYPOTHESES[name]
    sessions = ctx.panel.sessions
    window = segment_window(sessions, EXPLORATION, spec)
    if window is None:
        return {"window": {"days": 0}, "years": {}, "quarters": {}}
    first, last = window
    ctx.seconds.clear()
    ctx.events = ctx.ad1.announced = None
    ctx.means.clear()
    started = time.monotonic()
    listed = Listed()
    for s in range(first - 1, last):
        signals = count_day(ctx, listed, s)
        if signals:
            reference_counts(ctx, listed, s, {row[1] for row in signals})
    ad1_names(ctx, first, last)  # timed only: no overlap without trades
    out: dict[str, Any] = {
        "window": {**_window_facts(sessions, window), "signal_days": last - first + 1},
        **listed.tables(),
    }
    out["estimate"] = trade_days_estimate(out["years"])
    out["seconds"] = {"plan": time.monotonic() - started, **ctx.seconds}
    return out


def trade_days_estimate(years: dict[str, Any]) -> dict[str, Any]:
    """The exploration's signal dates (a date with a fill is one of them) and
    the validation's estimate (the full years' mean × the validation's
    years; the validation's data is not read).  As round14_research's K1."""

    full = [
        row["signal_days"] for key, row in years.items() if key != str(AE1_START.year)
    ]
    first, last = SEGMENTS[VALIDATION]
    length = ((last - first).days + 1) / 365.25
    mean = statistics.fmean(full) if full else None
    return {
        "exploration": sum(row["signal_days"] for row in years.values()),
        "full_years": len(full),
        "per_year": mean,
        "validation_years": length,
        "validation": None if mean is None else mean * length,
        "min_days": MIN_DAYS,
    }


# --- output -----------------------------------------------------------------------


SEGMENT_NAMES = ex.SEGMENT_NAMES
_pct = ex._pct
_t = ex._t
public = ex.public
threshold = r5.threshold
_share = r5._share
seconds_lines = r10.seconds_lines
EVENT_FIELDS = {
    "AE1": (
        "quarter",
        "ann_date",
        "announcement_session",
        "window_return",
        "population_window",
        "ear",
        "t1_locked_down",
    )
}
EVENT_TRADE_TAIL = r10.EVENT_TRADE_TAIL


def event_trade_fields(name: str) -> tuple[str, ...]:
    return (
        "signal_date",
        "exchange",
        "symbol",
        *EVENT_FIELDS[name],
        *EVENT_TRADE_TAIL,
        "reference",
        "reference_excess",
    )


def _threshold_line(segment: str, min_t: float) -> str:
    return (
        f"- 門檻：超額日均 > 0 且 t ≥ {threshold(min_t)}，且絕對報酬日均 > 0；"
        f"段長下限 {MIN_SEGMENT_DAYS.get(segment, '—')} 日；研究 DB 要有段內已下市公司；"
        f"另要有成交的訊號日至少 {MIN_DAYS} 日（逐筆評估）。"
        f"探索段 t ≥ {threshold(MIN_T)}，驗證段 t ≥ {threshold(VALIDATION_MIN_T)}"
        f"（Bonferroni，累計 {CUMULATIVE} 個：1 − Φ(z)＝0.025 ÷ {CUMULATIVE}，寫死不重算）"
    )


def _watch_line(min_t: float) -> str:
    return (
        f"- 前瞻觀察：超額 > 0 但 t < {threshold(min_t)}（沒有 t 下限），且絕對報酬 > 0；"
        "只當紀錄，不算通過、不進產品"
    )


def listed_lines(rows: dict[str, Any], label: str) -> list[str]:
    """AE1 第 7 點: the counts by year or quarter."""

    head = [label, "母體裡有 `ann_date` 的檔數", "EAR 缺值", "（比例）", "EAR ≤ 0",
            "占用中", "EAR > 0 的訊號數", "訊號日數", "`ann_date` 但 T 不在母體",
            "母體裡的下市、轉板股", "其中這一季沒有 `ann_date`（對照基準去掉的）"]  # fmt: skip
    lines = [
        "| " + " | ".join(head) + " |",
        "| --- | " + " | ".join("---:" for _ in head[1:]) + " |",
    ]
    for key, row in rows.items():
        lines.append(
            f"| {key} | {row['with_ann']:,} | {row['missing']:,} "
            f"| {_share(row['missing'], row['with_ann'])} | {row['not_positive']:,} "
            f"| {row['occupied']:,} | {row['signals']:,} | {row['signal_days']:,} "
            f"| {row['not_member']:,} | {row['delisted']:,} | {row['delisted_missing']:,} |"
        )
    return lines


def _head_lines(
    result: dict[str, Any], header: dict[str, Any], spec: dict[str, Any]
) -> list[str]:
    name = result["hypothesis"]
    segment = SEGMENT_NAMES[result["segment"]]
    window = result["window"] or {}
    verdict = result["verdict"] or "只列出、不判定"
    lines = [
        f"# {name} {segment}（round22_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- {OVERLAP_NOTE['summary_only']}",
        OVERLAP_NOTE["AE1_survivor"],
        "",
        f"- 判定：**{verdict}**"
        + (f"（{REASONS[result['reason']]}）" if result["reason"] else ""),
        f"- 假設：{spec['direction']}；{spec['label']}；全部符合、持有 {spec['hold']} 日",
        f"- 登記 commit `{REGISTRATION_COMMIT}`；{DECISION}；"
        f"定義雜湊 `{header['definitions_sha256'][:16]}…`",
        f"- 期間：訊號日 {window.get('first_signal', '—')} 起，成交日"
        f" {window.get('first_session', '—')}～{window.get('last_session', '—')}，共 "
        f"{window.get('days', 0)} 個交易日",
        f"- 退化：{DEGENERATE[name]}",
        f"- 限制：{LIMITS[name]}",
    ]
    prerequisites = result.get("prerequisites")
    if prerequisites:
        lines.append(
            f"- 先決條件：段長 {prerequisites['days']}／下限 {prerequisites['min_days']} 日；"
            f"段內已下市公司 {prerequisites['delisted']} 檔"
        )
    if result["segment"] == VALIDATION:
        lines.append(_watch_line(result.get("min_t", VALIDATION_MIN_T)))
    lines += [
        f"- 副本：最新交易日 {header['copy']['latest']}，alembic `{header['copy']['alembic']}`",
        f"- 重現：`{header['command']}`",
        "",
    ]
    return lines


def _overlap_lines(summary: dict[str, Any]) -> list[str]:
    return [
        "## 和 AD1 的重疊（AE1 第 7 點，只列出、不判定）",
        "",
        OVERLAP_NOTE["AE1_AD1"] + "。",
        "",
        f"各季平均：{_pct(summary['mean'], 1)}（{summary['days']:,} 季）；合計："
        f"{summary['both']:,}／{summary['signals']:,} 筆訊號（{_pct(summary['share'], 1)}）。",
        "",
        "| 年 | 季數 | 各季平均 |",
        "| --- | ---: | ---: |",
        *(
            f"| {year} | {row['days']:,} | {_pct(row['mean'], 1)} |"
            for year, row in summary["years"].items()
        ),
        "",
    ]


def event_markdown(result: dict[str, Any], header: dict[str, Any]) -> str:
    name = result["hypothesis"]
    spec = HYPOTHESES[name]
    lines = _head_lines(result, header, spec)
    if "excess" not in result:
        return "\n".join(lines)
    x, e, a = result["taiex_excess"], result["excess"], result["absolute"]
    r = result["reference_excess"]
    lines += [
        "## 數字（訊號日序列：同一訊號日的各筆先平均）",
        "",
        "| 量 | 訊號日數 | 平均 | t |",
        "| --- | ---: | ---: | ---: |",
        f"| 超額（對加權指數，只列出） | {x['days']} | {_pct(x['mean'], 3)} | {_t(x['t'])} |",
        f"| 超額（對母體，判定） | {e['days']} | {_pct(e['mean'], 3)} | {_t(e['t'])} |",
        f"| 超額（對對照基準，只列出） | {r['days']} | {_pct(r['mean'], 3)} | {_t(r['t'])} |",
        f"| 扣成本報酬（判定） | {a['days']} | {_pct(a['mean'], 3)} | — |",
        "",
        f"門檻：t ≥ {threshold(result.get('min_t', MIN_T))}（`t_stat(…, overlap={OVERLAP})`，"
        f"持有 {spec['hold']} 日時只是保守的下限）；有成交的訊號日至少 {MIN_DAYS} 日。",
        "",
        OVERLAP_NOTE["AE1_reference"] + "。",
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
    for reason, label in ABANDON_LABELS.items():
        lines.append(
            f"| 放棄：{label} | {result['abandon_reasons'].get(reason, 0):,} |"
        )
    listed = result.get("listed", {})
    lines.append(
        f"| T+1 跌停鎖死、照常以開盤價成交 | {listed.get('t1_locked_down_fills', 0):,} |"
    )
    for reason in tr.EXIT_REASONS:
        if reason in ("stop", "target"):
            continue  # neither
        lines.append(
            f"| 出場：{tr.EXIT_LABELS[reason]} | {_pct(result['exit_share'][reason], 1)}"
            f"（{result['exits'][reason]:,}） |"
        )
    lines += [
        f"| 跌停順延 | {result['limit_delayed']:,} |",
        f"| 停牌順延 | {result['suspension_delayed']:,} |",
        f"| 母體在 e 買不進的檔次 | {result['population_unbought']:,} |",
        "",
        "## 依年、依季的檔數與訊號數（AE1 第 7 點，只列出、不判定）",
        "",
        OVERLAP_NOTE["AE1_listed"] + "。",
        "",
        *listed_lines(listed.get("years", {}), "年（T）"),
        "",
        *listed_lines(listed.get("quarters", {}), "季"),
        "",
    ]
    overlap = (result.get("overlap") or {}).get("AE1_AD1")
    if overlap:
        lines += _overlap_lines(overlap)
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
    (out / "summary.md").write_text(event_markdown(result, header), encoding="utf-8")
    if "_trades" in result:
        _write_trades(out, name, result["_trades"])


def _write_trades(out: Path, name: str, trades: list[dict[str, Any]]) -> None:
    fields = event_trade_fields(name)
    with (out / "trades.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        for trade in trades:
            writer.writerow([_cell(trade.get(key)) for key in fields])
    days: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        if trade["net"] is not None:
            days[trade["signal_date"]].append(trade)
    with (out / "days.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "signal_date",
                "trades",
                "net",
                "excess",
                "taiex_excess",
                "reference_excess",
            ]
        )
        for day, rows in sorted(days.items()):
            cells = []
            for key in ("net", "excess", "taiex_excess", "reference_excess"):
                values = [row[key] for row in rows if row[key] is not None]
                cells.append(_cell(statistics.fmean(values)) if values else "")
            writer.writerow([day.isoformat(), len(rows), *cells])


def _row(result: dict[str, Any]) -> dict[str, Any]:
    """The overview's row: the trades' excess and the listed parts."""

    row = {"engine": TRADE, **tr._row(result)}
    if result.get("reference_excess"):
        row["reference_excess"] = result["reference_excess"]
    listed = result.get("listed") or {}
    if "t1_locked_down_fills" in listed:
        row["t1_locked_down_fills"] = listed["t1_locked_down_fills"]
    overlap = (result.get("overlap") or {}).get("AE1_AD1")
    if overlap:
        row["overlap_ad1"] = {
            k: overlap[k] for k in ("days", "mean", "signals", "both", "share")
        }
    if "win_rate" in result:
        row["win_rate"] = result["win_rate"]
    return row


def overview_markdown(report: dict[str, Any], sha256: str) -> str:
    segment = report["segment"]
    stage = SEGMENT_NAMES[segment]
    lines = [
        f"explore.json 的 sha256：`{sha256}`",
        "",
        f"# 新策略探索 第 {report['round']} 輪 {stage}（round22_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- {OVERLAP_NOTE['summary_only']}",
        OVERLAP_NOTE["AE1_survivor"],
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「第二十二輪：AE1」）：{DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        _threshold_line(segment, report["min_t"]),
        "- 引擎：逐筆評估（`trade_research`，日數是段內交易日，超額與 t 在訊號日序列上，"
        f"`overlap={OVERLAP}`）",
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
        lines.append(_watch_line(report["min_t"]))
        source = report["exploration"]
        lines.append(f"- 探索段報告：{source['url']}（sha256 `{source['sha256']}`）")
    head = (
        "| 代號 | 方向 | 引擎 | 日數 | 有成交的訊號日 | 對加權指數超額 | t | 對母體超額 | t "
        "| 絕對報酬 | 判定 |"
    )
    rule = "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"
    lines += ["", "## 判定", "", head, rule]
    for name, row in report["hypotheses"].items():
        lines.append(_overview_line(name, row, judged=True))
    listed = []
    for name, row in report["hypotheses"].items():
        if row.get("reference_excess"):
            e = row["reference_excess"]
            listed.append(
                f"- {name} 對對照基準的超額：平均 {_pct(e['mean'], 3)}、t {_t(e['t'])}（{e['days']:,} 個訊號日）"
            )
        part = row.get("overlap_ad1")
        if part:
            listed.append(
                f"- {name} 和 AD1 的重疊：各季平均 {_pct(part['mean'], 1)}（{part['days']:,} 季），"
                f"合計 {part['both']:,}／{part['signals']:,} 筆訊號"
            )
        if row.get("trades") is not None:
            listed.append(
                f"- {name} 的成交筆數 {row['trades']:,}、勝率 {_pct(row.get('win_rate'), 1)}、"
                f"放棄比例 {_pct(row.get('abandon_rate'), 1)}"
            )
    if listed:
        lines += ["", "只列出、不判定：", "", *listed]
    if report.get("used"):
        lines += [
            "",
            "## 已用段（驗證通過的假設，只列出、不判定）",
            "",
            head,
            rule,
        ]
        for name, row in report["used"].items():
            lines.append(_overview_line(name, row, judged=False))
    lines += [
        "",
        "各假設的數字、只列出的指標與資料覆蓋見 `<代號>/summary.md`。",
        "",
    ]
    return "\n".join(lines)


def _overview_line(name: str, row: dict[str, Any], judged: bool) -> str:
    spec = HYPOTHESES[name]
    e = row.get("excess") or {}
    x = row.get("taiex_excess") or {}
    verdict = (row["verdict"] or "—") if judged else "只列出"
    if row.get("reason"):
        verdict += f"（{REASONS[row['reason']]}）"
    return (
        f"| {name} | {spec['direction']} | 逐筆 | {row['days']} "
        f"| {row.get('trade_days') or 0} "
        f"| {_pct(x.get('mean'), 3)} | {_t(x.get('t'))} "
        f"| {_pct(e.get('mean'), 3)} | {_t(e.get('t'))} "
        f"| {_pct(row.get('absolute_mean'), 3)} | {verdict} |"
    )


COVERAGE_NOTES = (
    "- 每個訊號日都數，不扣占用（沒有模擬成交，「占用中」一欄是 0）；只數段內的訊號日；不跑模擬、不算報酬，"
    "EAR 只看正負與缺值、不列值",
    f"- AE1：{DEGENERATE['AE1']}。依年是 T 的年、依季是財報的季（`ann_date` 所屬的季）；"
    "「母體裡有 `ann_date` 的檔數」是 T 在母體裡的 (F, q)，EAR 缺值比例的分母是它；"
    "「母體裡的下市、轉板股」是每個有訊號的 (T, 季) 的母體裡 `status` 為 `delisted`／`transferred` 的檔次，"
    "「其中這一季沒有 `ann_date`」是對照基準去掉的檔次；`ad1_order` 是同一段算 AD1 名單"
    "（`round21_research.plan_ad1`，含它自己的 P1 名單）的時間，`--coverage-only` 只計時、不算重疊比例，各段的 `summary.md` 才列",
    "- 有成交的訊號日的估計：探索段是有訊號的不同 T 的個數（不扣占用與放棄，有成交的訊號日不會多於這個數）；"
    "驗證段是探索段的完整年（起日那年以外）平均每年的訊號日數 × 驗證段的年數，不讀驗證段的資料",
)


def coverage_markdown(body: dict[str, Any]) -> str:
    load_seconds = body.get("load_seconds_parts", {})
    lines = [
        f"# 新策略探索 第 {body['round']} 輪 AE1 資料覆蓋（探索段，不含報酬）",
        "",
        f"- round22_research 第 {VERSION} 版；定義雜湊 `{body['definitions_sha256']}`",
        f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}，"
        f"alembic `{body['copy']['alembic']}`",
        f"- 重現：`{body['command']}`",
        f"- 耗時 {body.get('elapsed_seconds', 0):.0f} 秒（載入 {body.get('load_seconds', 0):.0f} 秒，"
        f"其中 panel（含重大訊息清單與季報 EPS）{load_seconds.get('panel', 0):.0f} 秒、逐筆的標的狀態 "
        f"{load_seconds.get('trade', 0):.0f} 秒），"
        f"峰值記憶體 {lib.num(body.get('peak_memory_gb'), 2)} GB，"
        f"日線 {body.get('bars', 0):,} 根，重大訊息 {body.get('announcements', 0):,} 則",
        *COVERAGE_NOTES,
        "",
        "## 耗時",
        "",
        *seconds_lines(body),
        "",
    ]
    for name, row in body["hypotheses"].items():
        window = row["window"] or {}
        coverage = row["coverage"]
        estimate = coverage.get("estimate") or {}
        lines += [
            f"## {name}（訊號日 {window.get('first_signal', '—')} 起，{window.get('days', 0)} 日）",
            "",
            "依年（T 的年）：",
            "",
            *listed_lines(coverage.get("years", {}), "年（T）"),
            "",
            "依季（財報的季）：",
            "",
            *listed_lines(coverage.get("quarters", {}), "季"),
            "",
            "有成交的訊號日的估計：",
            "",
            f"- 探索段有訊號的訊號日 {estimate.get('exploration', 0):,} 日（有成交的訊號日不會多於這個數）；"
            f"下限 {estimate.get('min_days', MIN_DAYS)} 日",
            f"- 驗證段估計 {lib.num(estimate.get('validation'), 0)} 日：探索段 {estimate.get('full_years', 0)} 個"
            f"完整年平均每年 {lib.num(estimate.get('per_year'), 1)} 日 × 驗證段 "
            f"{lib.num(estimate.get('validation_years'), 2)} 年（不讀驗證段的資料）",
            "",
        ]
    lines += [
        "有明顯斷點或缺值比例異常的年份或季、探索段或驗證段估計有成交的訊號日不到 60，"
        "或 2013 年某一季母體裡有 `ann_date` 的檔數不到 20 時，先在工具單提問、不跑探索段。",
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
        "engines": {"trade_research": tr.VERSION},
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


def run_coverage(
    db: Path,
    out: Path,
    command: str = "",
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, Any]:
    """``--coverage-only``: counts of the exploration, no return."""

    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    end = SEGMENTS[EXPLORATION][1]
    ctx = load(db, LOAD_FROM, end, out / RAW_DIR_NAME)
    loaded = time.monotonic() - started
    progress(f"loaded ({loaded:.1f}s)")
    header = _header(db, EXPLORATION, command, end)
    hypotheses = {}
    for name in HYPOTHESES:
        coverage = event_coverage(ctx, name)
        hypotheses[name] = {
            "window": coverage.pop("window"),
            "seconds": coverage.pop("seconds", {}),
            "coverage": coverage,
        }
        progress(
            f"{name} coverage ({hypotheses[name]['seconds'].get('plan', 0.0):.1f}s)"
        )
    body = {
        **public(header),
        "coverage_only": True,
        "hypotheses": hypotheses,
        "load_seconds": loaded,
        "load_seconds_parts": ctx.load_seconds,
        "elapsed_seconds": time.monotonic() - started,
        "peak_memory_gb": _peak_memory_gb(),
        "bars": sum(len(item.dates) for item in ctx.panel.series.values()),
        "announcements": len(ctx.base.announcements),
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
    names: list[str] | tuple[str, ...],
    command: str = "",
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, Any]:
    """``names`` on the exploration segment; nothing after its end read."""

    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    end = SEGMENTS[EXPLORATION][1]
    ctx = load(db, LOAD_FROM, end, out / RAW_DIR_NAME)
    header = _header(db, EXPLORATION, command, end)
    report = {**header, "min_t": MIN_T, "selected": list(names), "hypotheses": {}}
    for name in names:
        t0 = time.monotonic()
        result = run_one(ctx, db, name, EXPLORATION)
        write_hypothesis(out / name, result, header)
        report["hypotheses"][name] = _row(result)
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
        del ctx, result
        gc.collect()
        used_ctx = load(db, LOAD_FROM, SEGMENTS[USED][1], out / RAW_DIR_NAME)
        report["used"] = {}
        for name in passed:
            result = run_one(used_ctx, db, name, USED)
            write_hypothesis(out / name / USED, result, header)
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
    parser = argparse.ArgumentParser(prog="round22_research.py", description=__doc__)
    parser.add_argument(
        "--db", required=True, help="the research DB (/research/stock.db)"
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--segment", required=True, choices=STAGES)
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help="exploration only: counts of dates, members and missing values "
        "and the time of the features, no return",
    )
    parser.add_argument(
        "--hypotheses",
        help="exploration (required, not with --coverage-only): AE1; it runs "
        "once per tool version",
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
    problems = list(er.refusals(db, args.min_free_gb))
    names: list[str] = []
    if args.segment == EXPLORATION and not args.coverage_only:
        chosen, names = ex.exploration_problems(
            db, args.hypotheses, HYPOTHESES, VERSION
        )
        problems = [*problems, *chosen]
    if problems:
        print(json.dumps({"refused": problems}, ensure_ascii=False))
        return 2
    command = "python tools/research/round22_research.py " + " ".join(argv)
    progress = lambda text: print(text, file=sys.stderr, flush=True)  # noqa: E731
    if args.segment == EXPLORATION:
        if args.coverage_only:
            line = run_coverage(db, Path(args.out), command, progress=progress)
        else:
            line = run_exploration(
                db, Path(args.out), names, command, progress=progress
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
