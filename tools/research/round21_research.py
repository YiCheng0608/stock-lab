"""Round 21 of the new-strategy exploration: AD1 (#1067).

docs/spec/evidence.md 第二十一輪：AD1 and 第二十一輪實作釋義: the hypothesis
was registered (commit ``3b686bd2``, #1065, decision 7201658574) before
anyone ran a tool on the backfilled history.  Nothing here is a command-line
option: a change of a definition is a new code.

It is not in ``explore_research.HYPOTHESES``, ``trade_research.HYPOTHESES``
nor ``round4_research`` .. ``round20_research``: their ``definitions_sha256``
hash the whole table, so adding it would make the validation refuse the
exploration reports already run.  AD1 trades on ``portfolio_research.simulate``
(K 5) inside the filing windows only: a window's signal dates get a list, the
other sessions none, so both sides hold cash between the windows (the K
accounts still rotate every session).  The population
(``evidence_lib.universe``), the loading (``explore_research.load_context``,
its MOPS list), ``explore_judge``, the gate and the ledgers are imported; the
windows are P1's (``round15_research.buy_events`` to
``round15_research.sale_days``, i.e. ``round14_research.quarter_events``), the
reference G1's way (``round20_research._reference``), P1's list
``round15_research.plan_p1`` itself and the overlap ``round10_research``'s.
New here are only the subject rule, ``ann_date``, ``exp_date``, the window
account and the listed numbers.

Each signal date T in a window (after its close, only T's data and before):
the members whose expected announcement session (the first session on or
after ``exp_date``) is one of the 1st .. 5th sessions after T and with no
announcement of the window's quarter on or before T, the first 20 by
``sha256("<T>:<instrument_id>")``, K 5.

``explore_research.explore_judge`` judges with t ≥ 2 on the exploration and
the fixed Bonferroni t ≥ 3.388 (71 hypotheses) on the validation.  Before the
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
import re
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
import round10_research as r10  # noqa: E402
import round14_research as r14  # noqa: E402
import round15_research as r15  # noqa: E402
import round20_research as r20  # noqa: E402

VERSION = 1
DESIGN = "1067"
TOOL = "round21_research"
REGISTRATION_COMMIT = "3b686bd2"
DECISION = (
    "https://github.com/YiCheng0608/stock-lab/issues/1065#issuecomment-7201658574"
)
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
SEGMENTS = dict(ex.SEGMENTS)
MIN_SEGMENT_DAYS = dict(ex.MIN_SEGMENT_DAYS)
MIN_T = ex.MIN_T  # the exploration's t ≥ 2
# docs 第二十一輪 門檻: 1 − Φ(z) = 0.025 ÷ 71, z = 3.3879, 3.388 to the 3rd
# decimal; fixed, not computed when run.
VALIDATION_MIN_T = 3.388
ROUND = 21
ROUND_SIZE = 1
# X1～X8, S1～S3, R1～R2, M1～M2, C1～C4, V1～V3, W1～W4, Y1～Y4, Z1～Z4, B1～B3,
# F1～F4, L1～L4, J1～J4, U1～U3, K1～K3, P1～P3, N1～N3, A1～A3, G1～G2, D1～D2,
# AB1～AB2, AD1
CUMULATIVE = 71
# Every segment reads the copy from its start, as round10_research ..
# round20_research: the year before's announcements are in every segment.
LOAD_FROM = ex.LOAD_FROM
LOAD_RULE = "every segment from LOAD_FROM"
MIN_LOTS = lib.DEFAULT_MIN_LOTS
RAW_DIR_NAME = ex.RAW_DIR_NAME
POPULATION = pr.POPULATION
TAIEX = pr.TAIEX
PORTFOLIO = "portfolio"

# 共同 排序與同分
ORDER = (
    "not ranked: the first N by sha256(<T>:<instrument_id>) among the members "
    "that qualify; a condition missing does not qualify"
)
SHORT_RULE = "cash, not filled"
# G1's reference (round20_research._reference reads its own statuses: they
# are round20_research's, in its hash)
REFERENCE_STATUSES = r20.REFERENCE_STATUSES

# AD1 第 1、2 點: the subject rule
NEWS_SOURCE = ex.MOPS_SOURCE
NEWS_EVENT_TYPE = ex.MOPS_EVENT_TYPE
SUBJECT_ALL = ("董事會",)
SUBJECT_ANY = (("通過", "決議"), ("財務報告", "財務報表", "財報"))
SUBJECT_NONE = ("更正", "補充", "子公司", "取消", "延期", "重編", "自結")
# AD1 第 2 點 and 共同 季報的法定期限: (month, day, the month its quarter ends,
# that quarter's year less the deadline's), calendar days, not sessions.
DEADLINES = r14.DEADLINES
ANN_RULE = (
    "the listed date (events.event_date, a calendar day, weekends and "
    "holidays too, not the session it is put off to) of the item's first "
    "announcement matching the subject rule from the day after the quarter's "
    "end to its statutory deadline (both calendar days, the deadline in)"
)
# AD1 第 3 點
EXP_RULE = (
    "d = deadline(F-1, q) - ann_date(F-1, q) in calendar days; exp_date = "
    "deadline(F, q) - d; no ann_date(F-1, q): no exp_date"
)
EXPECTED_RULE = (
    "the first session of Panel.sessions on or after exp_date (every "
    "market's sessions, not the item's own bars); none in the panel: none"
)
AHEAD_FIRST, AHEAD_LAST = 1, 5  # the expected session is T+1 .. T+5
ANNOUNCED_RULE = (
    "an ann_date(F, q) on or before T (T at any hour) does not qualify; "
    "reasons in order: no exp_date, announced, outside T+1..T+5"
)
# AD1 第 4 點: the windows are P1's (round15_research.buy_events to
# round15_research.sale_days), the endpoints as 共同.
WINDOW_STARTS = r15.BUY_DAYS
WINDOW_RULE = (
    "the signal dates are the sessions from P1's buy day (round15_research."
    "buy_events: 3/1, 4/15, 7/15, 10/15) to the quarter's deadline session "
    "(round15_research.sale_days: round14_research.quarter_events), both in; "
    "a deadline after the panel's last session: to that session"
)
# AD1 第 5 點
CASH_RULE = (
    "portfolio_research.simulate's K accounts, the account of session s is "
    "(s - first) % K every session; no list outside the windows, so both "
    "sides hold cash there; a list on a window's last session is held its "
    "5 sessions; the population the same signal dates and K"
)
# AD1 第 7 點 (G1 第 6 點): what the reference leaves out
REFERENCE_RULE = (
    "T's population less the delisted or transferred instruments with no "
    "exp_date for the window's quarter; the same account and windows"
)
# AD1 第 8 點 (listed only)
INSIDE_RULE = (
    "a name's ann_date(F, q) with sessions[s+1] <= ann_date <= "
    "sessions[min(s+5, last)] (calendar), over the names, by T's year"
)
P1 = "P1"
P1_RULE = (
    "round15_research.plan_p1 on the same window's buy day (P1's own list), "
    "only the windows from P1's start; the share over AD1's names, the days "
    "without either list not counted"
)
AD1_START = date(2014, 4, 15)

# The registration (docs 第二十一輪：AD1), word for word.  ``start`` as
# ``explore_research``.
HYPOTHESES: dict[str, dict[str, Any]] = {
    "AD1": {
        "engine": PORTFOLIO,
        "direction": "事件：盈餘公告溢酬",
        "label": "申報窗口內的每個交易日 T，母體中預期公告的交易日（由 `exp_date` 推）落在 T 之後"
        "第 1～5 個交易日、T（含）以前這一季還沒公告的股票，以雜湊取 20 檔、不排序；窗口之間兩邊都留現金",
        "rule": "window_daily",
        "condition": "expected_ahead",
        "keys": (),
        "short": SHORT_RULE,
        "top": 20,
        "hold": 5,
        "start": ("date", AD1_START),
    },
}
OTHER_COMPARISONS = ex.OTHER_COMPARISONS
REASONS = dict(ex.REASONS)
# The degenerate cases as the code judges them (第二十一輪實作釋義; PR #913
# review: the docs, coverage.md and summary.md say the same words, a test
# reads the docs' tool section for them).
DEGENERATE = {
    "AD1": "去年同季（季底次日到法定期限，含期限當天，日曆日）沒有符合主旨規則的公告時沒有 `exp_date`，不符合；"
    "同一檔同一季有多則符合的，只取季底次日起的第一則（發言日期最早的）；季底當天或以前、法定期限之後的公告不算這一季的；"
    "`ann_date(F−1, q)` 正好是法定期限當天時 d＝0，`exp_date` 就是今年的法定期限；"
    "`Panel.sessions` 沒有 ≥ `exp_date` 的交易日時（段末之後）不符合；"
    "T 當天任何時刻（含收盤後）已有 (F, q) 的公告的不符合；不符合的原因依序判：沒有 `exp_date`、T（含）以前已公告、"
    "預期公告的交易日不在 T+1～T+5，每檔只算第一個；符合的不足 20 檔時餘額留現金，不以不符合的檔補；"
    "窗口外不產生名單，兩邊都留現金",
}
OVERLAP_NOTE = {
    "AD1_P1": 'AD1 與 P1（`round15_research` 第 1 版的 `HYPOTHESES["P1"]`，同一個窗口算）每日名單的重疊比例：'
    "|AD1 當天的名單 ∩ P1 這個窗口的名單| ÷ AD1 當天的名單檔數；P1 的名單是 `round15_research.plan_p1` "
    "在同一個窗口的開始日選的 20 檔，P1 起日（2016-04-15）以前的窗口沒有 P1 的名單；"
    "AD1 或 P1 當天沒有名單的日子不計。只列出、不判定",
    "AD1_reference": "對照基準：當天母體去掉「這個窗口對應的季沒有 `exp_date`（去年同季沒有符合主旨規則的公告）的 "
    "`delisted`／`transferred` 標的」，同一個帳戶規則、同一組窗口；列 AD1 對它的超額與 t，只列出、不判定（判定仍只比母體）",
    "AD1_survivor": "- 存活者偏差（AD1）：下市公司 2014 年起 0 則重大訊息，沒有去年的公告日就沒有 `exp_date`、不進名單，"
    "偏差方向對假設有利。對照基準（母體去掉當天沒有 `exp_date` 的下市、轉板股）的超額與 t 在 "
    "`AD1/summary.md`「數字」表的「超額（對對照基準，只列出）」列與 `explore.md` 的「只列出、不判定」",
    "AD1_listed": "每個 T 符合條件的檔數與名單檔數：符合條件是第 3 點的條件成立的母體檔數，名單檔數是以雜湊取前 20 名之後。"
    "只列出、不判定",
    "AD1_windows": "每個窗口有 `exp_date` 的檔數占母體的比例：窗口內任一個訊號日在母體裡的不同檔數為分母，"
    "其中這個窗口對應的季有 `exp_date` 的檔數為分子。只列出、不判定",
    "AD1_inside": "實際公告日落在持有期間內的比例：名單檔次中，這一季實際的 `ann_date`（日曆日）落在"
    "持有的 T+1～T+5（`Panel.sessions` 的第 T+1 與第 T+5 個交易日之間，含兩端；T+5 在段末之後時到段末）之內的檔次 "
    "÷ 名單檔次，依 T 的年列；看「去年推今年」準不準，不看報酬。只列出、不判定",
    "summary_only": "定義照摘要與索引頁，未讀全文",
    # #1067 決定 7202868880: the coverage's numbers, first among the limits
    "AD1_coverage": "`--coverage-only` 的結果（[#1067 決定 7202868880](https://github.com/YiCheng0608/stock-lab/issues/1067#issuecomment-7202868880)）："
    "每個窗口有 `ann_date`（主旨規則收到）的檔數占母體的 8.3%～20.2%（年報窗口 16.8%～20.2%，其他三季 8.3%～12.3%），有 `exp_date` 的占 7.7%～19.2%（年報窗口 16.0%～19.2%，其他三季 7.7%～11.8%）；"
    "名單平均 5～13 檔，遠小於母體，窗口內 508 個訊號日有 448 天不足 20 檔、63 天沒有名單，投入比例低，"
    "判讀結果要看實際公告日落在持有期間內的比例與投入比例；登記段「名單接近母體」那一點在這份資料上不成立，"
    "名單遠小於母體（登記段原文照留）；籠統的「董事會重要決議事項」這類主旨只看清單分不出有沒有通過財報，"
    "研究 DB 沒有說明內文，收不到；依季的則數從 2013Q2 起跳高（IFRS 之後季報提報董事會），在起日 2014-04-15 之前，不影響本輪",
}
LIMITS = {
    "AD1": OVERLAP_NOTE["AD1_coverage"]
    + "；"
    + "定義照摘要與索引頁（[EconPapers](https://econpapers.repec.org/RePEc:eee:jfinec:v:108:y:2013:i:1:p:118-138)），"
    "未讀全文；主旨規則：證交所《重大訊息之查證暨公開處理程序》第 4 條把「財務報告提報董事會」列為應發布的重大訊息，"
    "這一款從哪一年起有、各年的主旨怎麼寫，登記時沒有查，主旨規則抓不到的季看 `--coverage-only`，寫進限制、不改規則；"
    "名單接近母體：一年裡大部分公司都會在某幾天進名單，名單和母體的差只在時點，公告日集中在期限前幾天時，"
    "名單會接近當時的母體，超額會被壓小，這是設計本身；存活者偏差：下市公司 2014 年起 0 則，沒有去年的公告日就沒有"
    "預期公告日、不進名單，偏差方向對假設有利，看對對照基準的超額；金融業等法定期限不同的公司照樣算，"
    "但窗口與法定期限是一般公司的；重大訊息 2024-09-28～2026-08-01 的清單缺口落在已用段，探索段與驗證段用到的 "
    "`ann_date` 都在涵蓋內，已用段的 `exp_date` 要用 2024Q4～2026Q2 的公告日，缺的季沒有 `exp_date`；"
    "和 P1、X8、AB2 的關係：P1（同一組申報窗口、窗口之間留現金）、X8、AB2（同一張重大訊息表）的狀態登記時已知，"
    "都沒有通過；不是看結果挑的：P1 依 EPS 的季節名次選、整個窗口持有，AD1 不看 EPS，只看公告的時點、持有 5 日，"
    "不是 P1 的變形，X8 只用庫藏股的主旨，AB2 只用有無公告，AD1 是第一個用到實際公告日的，看和 P1 的重疊比例",
}
FEATURE_LABELS = {
    "ann_date": "實際公告日",
    "exp_date": "預期公告日",
}
PICK_FIELDS = {
    "AD1": ("quarter", "exp_date", "expected_session", "ann_date"),
}


def definitions() -> dict[str, Any]:
    return {
        "version": VERSION,
        "design": DESIGN,
        "hypotheses": HYPOTHESES,
        "order": ORDER,
        "short": SHORT_RULE,
        "reference_statuses": list(REFERENCE_STATUSES),
        "features": {
            "subject": {
                "source": [NEWS_SOURCE, NEWS_EVENT_TYPE],
                "all": SUBJECT_ALL,
                "any": SUBJECT_ANY,
                "none": SUBJECT_NONE,
            },
            "ann_date": {"deadlines": DEADLINES, "rule": ANN_RULE},
            "exp_date": {
                "rule": EXP_RULE,
                "expected": EXPECTED_RULE,
                "ahead": [AHEAD_FIRST, AHEAD_LAST],
                "announced": ANNOUNCED_RULE,
            },
            "windows": {
                "starts": WINDOW_STARTS,
                "deadlines": [r14.DEADLINES, r14.EVENT_DAY_RULE],
                "start_rule": r15.EVENT_DAY_RULE,
                "rule": WINDOW_RULE,
                "cash": CASH_RULE,
            },
            "reference": [
                REFERENCE_RULE,
                list(REFERENCE_STATUSES),
                r20.VERSION,
                r20.definitions_sha256(),
            ],
            "listed": {
                "inside": INSIDE_RULE,
                P1: [
                    r15.HYPOTHESES[P1],
                    r15.VERSION,
                    r15.definitions_sha256(),
                    P1_RULE,
                ],
            },
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
        "round": [ROUND, ROUND_SIZE, CUMULATIVE],
        "costs": [pr.SLIPPAGE, pr.FEE, pr.TAX],
        "min_lots": MIN_LOTS,
        "load_from": LOAD_FROM,
        "load": LOAD_RULE,
    }


def definitions_sha256() -> str:
    """Hash of every fixed number the verdicts depend on (the definition,
    the subject rule's words, ann_date's deadlines and calendar days,
    exp_date's d and expected session, T+1..T+5 and announced on T, the
    windows and their endpoints, N 20 by the hash, K 5, cash between the
    windows, the reference, P1's list, the segments, the costs).  A changed
    tool needs a new exploration report before a validation."""

    text = json.dumps(definitions(), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- the context ------------------------------------------------------------------


@dataclass
class Context:
    """``explore_research``'s context (the market, the quotes, the EPS
    quarters P1 ranks by, the MOPS list), the instruments' status and the
    context ``round15_research`` (P1) plans with (the same base).  One
    panel."""

    base: ex.Context
    statuses: dict[int, str] = field(default_factory=dict)
    p1: r15.Context | None = None
    seconds: Counter = field(default_factory=Counter)
    load_seconds: dict[str, float] = field(default_factory=dict)
    # each instrument's quarter end -> its ann_date (the first listed date)
    announced: dict[int, dict[date, date]] | None = None

    def __post_init__(self) -> None:
        if self.p1 is None:
            self.p1 = r15.Context(self.base, statuses=self.statuses)

    @property
    def market(self) -> pr.Market:
        return self.base.market

    @property
    def panel(self) -> lib.Panel:
        return self.base.market.panel

    def quote(self, instrument_id: int, s: int) -> pr.Quote | None:
        return self.base.quote(instrument_id, s)


def load(db: Path, start: date, end: date, raw_dir: Path) -> Context:
    """The panel (with the MOPS list and the EPS quarters) and the statuses
    to ``end``; nothing after ``end`` is read."""

    started = time.monotonic()
    base = ex.load_context(db, start, end, raw_dir)
    panel_seconds = time.monotonic() - started
    t0 = time.monotonic()
    statuses = r15.load_statuses(db)
    return Context(
        base,
        statuses,
        load_seconds={"panel": panel_seconds, "statuses": time.monotonic() - t0},
    )


# --- AD1: the subject rule, ann_date, exp_date ------------------------------------


def is_financial_report(title: str) -> bool:
    """AD1 第 2 點: 董事會, 通過 or 決議, 財務報告／財務報表／財報, none of
    the 7 words."""

    return (
        all(word in title for word in SUBJECT_ALL)
        and all(any(word in title for word in group) for group in SUBJECT_ANY)
        and not any(word in title for word in SUBJECT_NONE)
    )


def _quarter_end(year: int, month: int) -> date:
    return date(year, month, 31 if month in (3, 12) else 30)


def deadline_of(quarter: date) -> date:
    """The statutory deadline (a calendar day) of the quarter ending ``quarter``."""

    for month, day, end_month, offset in DEADLINES:
        if end_month == quarter.month:
            return date(quarter.year - offset, month, day)
    raise ValueError(f"{quarter} is not a quarter's end")


def quarter_of(listed: date) -> date | None:
    """The quarter whose (end, deadline] holds ``listed``, or None."""

    for year in (listed.year, listed.year + 1):
        for month, day, end_month, offset in DEADLINES:
            end = _quarter_end(year + offset, end_month)
            if end < listed <= date(year, month, day):
                return end
    return None


def announced(ctx: Context) -> dict[int, dict[date, date]]:
    """Each instrument's ann_date by quarter end: the earliest listed date of
    a matching announcement in the quarter's (end, deadline]."""

    if ctx.announced is None:
        t0 = time.perf_counter()
        found: dict[int, dict[date, date]] = defaultdict(dict)
        for _at, instrument_id, title, listed in ctx.base.announcements:
            if not is_financial_report(title):
                continue
            quarter = quarter_of(listed)
            if quarter is None:
                continue
            mine = found[instrument_id]
            if quarter not in mine or listed < mine[quarter]:
                mine[quarter] = listed
        ctx.announced = dict(found)
        ctx.seconds["ann_date"] += time.perf_counter() - t0
    return ctx.announced


def ann_date(ctx: Context, instrument_id: int, quarter: date) -> date | None:
    return announced(ctx).get(instrument_id, {}).get(quarter)


def year_before(quarter: date) -> date:
    return quarter.replace(year=quarter.year - 1)


def exp_date(ctx: Context, instrument_id: int, quarter: date) -> date | None:
    """AD1 第 3 點: deadline(F, q) − (deadline(F−1, q) − ann_date(F−1, q))."""

    before = year_before(quarter)
    last = ann_date(ctx, instrument_id, before)
    if last is None:
        return None
    d = (deadline_of(before) - last).days
    return deadline_of(quarter) - timedelta(days=d)


def expected_session(sessions: list[date], expected: date | None) -> int | None:
    """The first session on or after ``expected`` (``Panel.sessions``)."""

    if expected is None:
        return None
    at = bisect_left(sessions, expected)
    return at if at < len(sessions) else None


@dataclass(frozen=True)
class Ahead:
    qualifies: bool
    # "no_exp", "announced", "outside" or None
    reason: str | None = None
    exp: date | None = None
    expected: int | None = None


def expected_ahead(ctx: Context, instrument_id: int, s: int, quarter: date) -> Ahead:
    """AD1 第 3 點 on T (session ``s``) for the window's ``quarter``."""

    sessions = ctx.panel.sessions
    exp = exp_date(ctx, instrument_id, quarter)
    if exp is None:
        return Ahead(False, "no_exp")
    expected = expected_session(sessions, exp)
    now = ann_date(ctx, instrument_id, quarter)
    if now is not None and now <= sessions[s]:
        return Ahead(False, "announced", exp, expected)
    if expected is None or not s + AHEAD_FIRST <= expected <= s + AHEAD_LAST:
        return Ahead(False, "outside", exp, expected)
    return Ahead(True, None, exp, expected)


# --- the windows ------------------------------------------------------------------


def windows(sessions: list[date]) -> list[tuple[int, int, date]]:
    """AD1 第 4 點: (the first signal session, the last, the quarter) of each
    window, P1's buy day to the quarter's deadline session."""

    sales = r15.sale_days(sessions)
    out = []
    for at, quarter in r15.buy_events(sessions):
        end = sales.get(quarter, len(sessions) - 1)
        if end >= at:
            out.append((at, end, quarter))
    return out


def segment_window(
    sessions: list[date], segment: str, spec: dict[str, Any]
) -> tuple[int, int] | None:
    """(first, last) index of the sessions with an equity value, or None.
    The equity starts the session after the first window's first signal
    date in the segment (as P1's)."""

    first_day, last_day = SEGMENTS[segment]
    last = bisect_left(sessions, last_day + timedelta(days=1)) - 1
    if first_day is None:
        base = ex.start_index(sessions, spec["start"])
        if base is None:
            return None
    else:
        base = max(bisect_left(sessions, first_day), 1) - 1
    found = [at for at, _end, _q in windows(sessions) if at >= base]
    if not found:
        return None
    first = found[0] + 1
    return (first, last) if first <= last else None


# --- the plan ---------------------------------------------------------------------


@dataclass
class Plan:
    picks: dict[int, list[int]] = field(default_factory=dict)
    population: dict[int, list[int]] = field(default_factory=dict)
    reference: dict[int, list[int]] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    windows: list[dict[str, Any]] = field(default_factory=list)
    days: list[dict[str, Any]] = field(default_factory=list)
    signal_days: int = 0
    event_days: int = 0
    overlap: dict[str, dict[str, list[float]]] = field(default_factory=dict)
    inside: dict[str, list[int]] = field(default_factory=dict)  # year: [names, in]


_year = r15._year
_add = r15._add
_pick_row = r15._pick_row
_reference = r20._reference


def p1_lists(ctx: Context, first: int, last: int) -> dict[int, set[int]]:
    """P1's list by its buy day's session (``round15_research.plan_p1``, its
    own definition), the windows from P1's start only."""

    t0 = time.perf_counter()
    try:
        spec = r15.HYPOTHESES[P1]
        start = ex.start_index(ctx.panel.sessions, spec["start"])
        if start is None:
            return {}
        planned = r15.plan_p1(ctx.p1, spec, max(first, start + 1), last)
        return {at - 1: set(names) for at, names in planned.picks.items()}
    finally:
        ctx.seconds["p1_order"] += time.perf_counter() - t0


def inside_holding(sessions: list[date], s: int, actual: date | None) -> bool:
    """AD1 第 8 點: the actual ann_date in T+1 .. T+5 (calendar, to the last
    session when T+5 is after it)."""

    if actual is None or s + 1 >= len(sessions):
        return False
    return sessions[s + 1] <= actual <= sessions[min(s + 5, len(sessions) - 1)]


def plan_ad1(
    ctx: Context, spec: dict[str, Any], first: int, last: int, keep_rows=True
) -> Plan:
    """AD1 第 1～8 點 on the windows' signal dates in ``first − 1`` ..
    ``last − 1``: the members that qualify, the first 20 by the hash; the
    population and the reference on the same dates; nothing between the
    windows."""

    panel = ctx.panel
    sessions = panel.sessions
    out = Plan(overlap={"AD1_P1": {}})
    top = spec["top"]
    announced(ctx)
    p1 = p1_lists(ctx, first, last)
    for start, end, quarter in windows(sessions):
        lo, hi = max(start, first - 1), min(end, last - 1)
        if lo > hi:
            continue
        window = {
            "quarter": quarter.isoformat(),
            "first_signal": sessions[lo].isoformat(),
            "last_signal": sessions[hi].isoformat(),
            "signal_days": hi - lo + 1,
            "members": 0,
            "with_ann": 0,
            "with_exp": 0,
            "qualified": 0,
            "names": 0,
        }
        seen: set[int] = set()
        p1_names = p1.get(start, set())
        out.event_days += 1
        for at in range(lo, hi + 1):
            day = sessions[at]
            members = lib.universe(panel, day, MIN_LOTS)
            year = _year(out.coverage, day, len(members))
            out.signal_days += 1
            t0 = time.perf_counter()
            rows, reasons = [], Counter()
            for item, _k in members:
                got = expected_ahead(ctx, item.instrument_id, at, quarter)
                reasons[got.reason] += 1
                if got.qualifies:
                    rows.append((pr.tie_break(day, item.instrument_id), item, got))
            ctx.seconds["condition"] += time.perf_counter() - t0
            for item, _k in members:
                if item.instrument_id not in seen:
                    seen.add(item.instrument_id)
                    window["members"] += 1
                    window["with_ann"] += int(
                        ann_date(ctx, item.instrument_id, quarter) is not None
                    )
                    window["with_exp"] += int(
                        exp_date(ctx, item.instrument_id, quarter) is not None
                    )
            t0 = time.perf_counter()
            gone, gone_missing, excluded = _reference(
                ctx,
                members,
                lambda item: exp_date(ctx, item.instrument_id, quarter) is None,
            )
            ctx.seconds["reference"] += time.perf_counter() - t0
            rows.sort(key=lambda row: row[0])
            chosen = rows[:top]
            qualified = len(rows)
            window["qualified"] += qualified
            window["names"] += len(chosen)
            for key in ("no_exp", "announced", "outside"):
                _add(year, key, reasons[key])
            _add(year, "qualified", qualified)
            _add(year, "names", len(chosen))
            _add(year, "short_days", int(qualified < top))
            _add(year, "empty_days", int(not qualified))
            _add(year, "delisted", gone)
            _add(year, "delisted_missing", gone_missing)
            if not keep_rows:
                continue
            names = [item.instrument_id for _t, item, _g in chosen]
            out.days.append(
                {
                    "signal_date": day.isoformat(),
                    "quarter": quarter.isoformat(),
                    "members": len(members),
                    "qualified": qualified,
                    "names": len(names),
                }
            )
            share = r10.overlap_share(names, p1_names)
            if share is not None:
                out.overlap["AD1_P1"].setdefault(str(day.year), []).append(share)
            counts = out.inside.setdefault(str(day.year), [0, 0])
            for _t, item, got in chosen:
                actual = ann_date(ctx, item.instrument_id, quarter)
                counts[0] += 1
                counts[1] += int(inside_holding(sessions, at, actual))
            out.picks[at + 1] = names
            out.population[at + 1] = [item.instrument_id for item, _ in members]
            out.reference[at + 1] = [
                item.instrument_id
                for item, _ in members
                if item.instrument_id not in excluded
            ]
            for place, (tie, item, got) in enumerate(chosen, 1):
                actual = ann_date(ctx, item.instrument_id, quarter)
                out.rows.append(
                    _pick_row(
                        ctx, day, place, item.instrument_id,
                        {"quarter": quarter.isoformat(), "exp_date": got.exp.isoformat(),
                         "expected_session": sessions[got.expected].isoformat(),
                         "ann_date": "" if actual is None else actual.isoformat()},
                        tie,
                    )
                )  # fmt: skip
        window["exp_share"] = (
            window["with_exp"] / window["members"] if window["members"] else None
        )
        out.windows.append(window)
    return out


overlap_share = r10.overlap_share
overlap_summary = r10.overlap_summary
_window_facts = r5._window_facts


def inside_summary(by_year: dict[str, list[int]]) -> dict[str, Any]:
    """AD1 第 8 點: the names whose actual ann_date is in T+1 .. T+5, by year
    and over the segment."""

    names = sum(n for n, _i in by_year.values())
    inside = sum(i for _n, i in by_year.values())
    return {
        "names": names,
        "inside": inside,
        "share": inside / names if names else None,
        "years": {
            year: {"names": n, "inside": i, "share": i / n if n else None}
            for year, (n, i) in sorted(by_year.items())
        },
    }


# --- --coverage-only: the subject rule's counts -----------------------------------


def _plain(title: str, names: tuple[str, ...]) -> str:
    """A subject without the company's name, symbol and the numbers (dates,
    years, quarters)."""

    for name in names:
        if name:
            title = title.replace(name, "〈公司〉")
    return " ".join(re.sub(r"[0-9０-９]+", "#", title).split())


def subject_counts(ctx: Context) -> dict[str, Any]:
    """``--coverage-only``: the subject rule's rows and companies by year and
    calendar quarter of the listed date; the near misses (董事會 and 通過／
    決議 without the report words) by year and their 20 commonest plain
    subjects; the rows each of the 7 words keeps out."""

    rows: Counter = Counter()
    companies: dict[str, set[int]] = defaultdict(set)
    near: Counter = Counter()
    near_titles: Counter = Counter()
    blocked: Counter = Counter()
    symbols = ctx.panel.symbols
    board, decided = SUBJECT_ALL, SUBJECT_ANY[0]
    for _at, instrument_id, title, listed in ctx.base.announcements:
        key = f"{listed.year}Q{(listed.month - 1) // 3 + 1}"
        if is_financial_report(title):
            rows[key] += 1
            companies[key].add(instrument_id)
            continue
        has_board = all(w in title for w in board) and any(w in title for w in decided)
        if not has_board:
            continue
        if any(word in title for word in SUBJECT_ANY[1]):
            for word in SUBJECT_NONE:
                blocked[word] += int(word in title)
            continue
        near[str(listed.year)] += 1
        _exchange, symbol, name = symbols.get(instrument_id, ("", "", ""))
        near_titles[_plain(title, (name or "", symbol or ""))] += 1
    years: dict[str, dict[str, int]] = {}
    for key in sorted(rows):
        year = years.setdefault(key[:4], {"rows": 0, "companies": 0})
        year["rows"] += rows[key]
    by_year: dict[str, set[int]] = defaultdict(set)
    for key, ids in companies.items():
        by_year[key[:4]] |= ids
    for year, ids in by_year.items():
        years[year]["companies"] = len(ids)
    return {
        "quarters": {
            key: {"rows": rows[key], "companies": len(companies[key])}
            for key in sorted(rows)
        },
        "years": dict(sorted(years.items())),
        "near_miss": dict(sorted(near.items())),
        "near_miss_subjects": near_titles.most_common(20),
        "blocked": {word: blocked[word] for word in SUBJECT_NONE},
    }


# --- one hypothesis on one segment ------------------------------------------------


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


def engines(
    ctx: Context, name: str, planned: Plan, first: int, last: int
) -> tuple[pr.Simulation, pr.Simulation, pr.Simulation]:
    """(AD1, the population, the reference): K accounts, the lists on the
    windows' signal dates only."""

    spec = HYPOTHESES[name]
    mine = pr.simulate(planned.picks, ctx.quote, first, last, spec["hold"], spec["top"])
    population = pr.simulate(
        planned.population, ctx.quote, first, last, spec["hold"], None
    )
    reference = pr.simulate(
        planned.reference, ctx.quote, first, last, spec["hold"], None
    )
    return mine, population, reference


def run_portfolio(
    ctx: Context,
    db: Path,
    name: str,
    segment: str,
    coverage_only: bool = False,
    min_t: float = MIN_T,
) -> dict[str, Any]:
    """AD1 on one segment: its numbers, verdict and private parts."""

    spec = HYPOTHESES[name]
    sessions = ctx.panel.sessions
    result = _result(name, segment)
    window = segment_window(sessions, segment, spec)
    if window is None:
        result["reason"] = "no_sessions"
        return result
    first, last = window
    days = last - first + 1
    result["window"] = _window_facts(sessions, window)
    if segment != USED and not coverage_only:
        if not _prerequisites(db, result, segment, sessions, first, last):
            return result
    ctx.seconds.clear()
    ctx.announced = None  # timed on each segment
    started = time.monotonic()
    planned = plan_ad1(ctx, spec, first, last, keep_rows=not coverage_only)
    result["window"]["signal_days"] = planned.signal_days
    result["window"]["event_days"] = planned.event_days
    result["coverage"] = planned.coverage
    result["windows"] = planned.windows
    result["seconds"] = {"plan": time.monotonic() - started, **ctx.seconds}
    if coverage_only:
        return result
    result["days_listed"] = planned.days
    result["overlap"] = {
        key: overlap_summary(by_year) for key, by_year in planned.overlap.items()
    }
    result["inside"] = inside_summary(planned.inside)
    mine, population, reference = engines(ctx, name, planned, first, last)
    returns = pr.daily_returns(mine.equity)
    others = pr.daily_returns(population.equity)
    base = pr.daily_returns(reference.equity)
    taiex = ex._taiex(ctx.panel, first, last)
    differences = [a - b for a, b in zip(returns, others)]
    excess = {
        POPULATION: pr.excess_metrics(differences),
        TAIEX: pr.excess_metrics(
            [a - b for a, b in zip(returns, taiex) if b is not None]
        ),
        "reference": pr.excess_metrics([a - b for a, b in zip(returns, base)]),
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
    bought = len(mine.positions)
    result["unsold_share"] = mine.counts.get("unsold", 0) / bought if bought else None
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


def run_one(
    ctx: Context, db: Path, name: str, segment: str, min_t: float = MIN_T
) -> dict[str, Any]:
    return run_portfolio(ctx, db, name, segment, min_t=min_t)


# --- output -----------------------------------------------------------------------


SEGMENT_NAMES = ex.SEGMENT_NAMES
_pct = ex._pct
_t = ex._t
public = ex.public
threshold = r5.threshold
_share = r5._share
PORTFOLIO_TRADE_FIELDS = r5.TRADE_FIELDS
_yearly_lines = r15._yearly_lines
_excess_line = r15._excess_line


def _threshold_line(segment: str, min_t: float) -> str:
    return (
        f"- 門檻：超額日均 > 0 且 t ≥ {threshold(min_t)}，且絕對報酬日均 > 0；"
        f"段長下限 {MIN_SEGMENT_DAYS.get(segment, '—')} 日；研究 DB 要有段內已下市公司。"
        f"探索段 t ≥ {threshold(MIN_T)}，驗證段 t ≥ {threshold(VALIDATION_MIN_T)}"
        f"（Bonferroni，累計 {CUMULATIVE} 個：1 − Φ(z)＝0.025 ÷ {CUMULATIVE}，寫死不重算）"
    )


def _watch_line(min_t: float) -> str:
    return (
        f"- 前瞻觀察：超額 > 0 但 t < {threshold(min_t)}（沒有 t 下限），且絕對報酬 > 0；"
        "只當紀錄，不算通過、不進產品"
    )


def seconds_lines(body: dict[str, Any]) -> list[str]:
    """The time of the signal dates (the windows' only, not the equity's
    sessions) and of the features (PR #1068 review: not round10's, which
    divides by the equity's sessions)."""

    lines = [
        "| 代號 | 訊號日（窗口內） | 有淨值的交易日 | 排序與覆蓋（秒） | 特徵計算（秒） "
        "| 每個訊號日（毫秒） |",
        "| --- | ---: | ---: | ---: | --- | ---: |",
    ]
    for name, row in body["hypotheses"].items():
        seconds = row.get("seconds") or {}
        window = row["window"] or {}
        signals, days = window.get("signal_days", 0), window.get("days", 0)
        parts = "、".join(
            f"`{key}` {value:.1f}" for key, value in seconds.items() if key != "plan"
        )
        plan = seconds.get("plan", 0.0)
        per_day = lib.num(plan * 1000 / signals, 1) if signals else "—"
        lines.append(
            f"| {name} | {signals:,} | {days:,} | {plan:.1f} | {parts or '—'} "
            f"| {per_day} |"
        )
    return lines


def coverage_lines(name: str, coverage: dict[str, Any]) -> list[str]:
    """AD1 by year of the signal dates (the windows' only)."""

    head = ["年", "訊號日", "母體檔次", "沒有 `exp_date`", "（比例）", "T（含）以前已公告",
            "預期公告日不在 T+1～T+5", "符合條件的檔次", "名單檔次", "符合的不足 20 檔的訊號日",
            "沒有一檔符合的訊號日", "母體裡的下市、轉板股", "其中沒有 `exp_date`（對照基準去掉的）"]  # fmt: skip
    lines = [
        "| " + " | ".join(head) + " |",
        "| --- | " + " | ".join("---:" for _ in head[1:]) + " |",
    ]
    for year, row in sorted(coverage.items()):
        members = row["members"]
        lines.append(
            f"| {year} | {row['days']:,} | {members:,} | {row.get('no_exp', 0):,} "
            f"| {_share(row.get('no_exp', 0), members)} | {row.get('announced', 0):,} "
            f"| {row.get('outside', 0):,} | {row.get('qualified', 0):,} "
            f"| {row.get('names', 0):,} | {row.get('short_days', 0):,} "
            f"| {row.get('empty_days', 0):,} | {row.get('delisted', 0):,} "
            f"| {row.get('delisted_missing', 0):,} |"
        )
    return lines


def window_lines(found: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| 對應的季 | 第一個訊號日 | 最後一個訊號日 | 訊號日 | 母體的檔數 | 有 `ann_date` | 有 `exp_date` "
        "| `exp_date` 的比例 | 平均符合的檔數 | 平均名單檔數 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for w in found:
        days = w["signal_days"]
        lines.append(
            f"| {w['quarter']} | {w['first_signal']} | {w['last_signal']} | {days:,} "
            f"| {w['members']:,} | {w['with_ann']:,} | {w['with_exp']:,} "
            f"| {_pct(w['exp_share'], 1)} | {lib.num(w['qualified'] / days, 1)} "
            f"| {lib.num(w['names'] / days, 1)} |"
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
        f"# {name} {segment}（round21_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- {OVERLAP_NOTE['summary_only']}",
        OVERLAP_NOTE["AD1_survivor"],
        "",
        f"- 判定：**{verdict}**"
        + (f"（{REASONS[result['reason']]}）" if result["reason"] else ""),
        f"- 假設：{spec['direction']}；{spec['label']}；N＝{spec['top']}、K＝{spec['hold']}",
        f"- 登記 commit `{REGISTRATION_COMMIT}`；{DECISION}；"
        f"定義雜湊 `{header['definitions_sha256'][:16]}…`",
        f"- 期間：訊號日 {window.get('first_signal', '—')} 起，有淨值的交易日"
        f" {window.get('first_session', '—')}～{window.get('last_session', '—')}，共 "
        f"{window.get('days', 0)} 個交易日（窗口之間的現金日也算）",
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


def _inside_lines(summary: dict[str, Any]) -> list[str]:
    lines = [
        "## 實際公告日落在持有期間內的比例（AD1 第 8 點，只列出、不判定）",
        "",
        OVERLAP_NOTE["AD1_inside"] + "。",
        "",
        "| 年 | 名單檔次 | 落在 T+1～T+5 的檔次 | 比例 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for year, row in summary["years"].items():
        lines.append(
            f"| {year} | {row['names']:,} | {row['inside']:,} | {_pct(row['share'], 1)} |"
        )
    lines += [
        f"| 全段 | {summary['names']:,} | {summary['inside']:,} "
        f"| {_pct(summary['share'], 1)} |",
        "",
    ]
    return lines


def _days_lines(found: list[dict[str, Any]]) -> list[str]:
    return [
        "## 每個 T 符合條件的檔數與名單檔數（AD1 第 8 點，只列出、不判定）",
        "",
        OVERLAP_NOTE["AD1_listed"] + "。",
        "",
        "| 訊號日 | 對應的季 | 母體檔次 | 符合條件 | 名單檔數 |",
        "| --- | --- | ---: | ---: | ---: |",
        *(
            f"| {d['signal_date']} | {d['quarter']} | {d['members']:,} "
            f"| {d['qualified']:,} | {d['names']:,} |"
            for d in found
        ),
        "",
    ]


def portfolio_markdown(result: dict[str, Any], header: dict[str, Any]) -> str:
    name = result["hypothesis"]
    spec = HYPOTHESES[name]
    lines = _head_lines(result, header, spec)
    if "excess" in result:
        e, a = result["excess"], result["absolute"]
        lines += [
            "## 數字",
            "",
            "| 量 | 日數 | 日均 | 年化 | t |",
            "| --- | ---: | ---: | ---: | ---: |",
            _excess_line("超額（對加權指數，只列出）", e[TAIEX]),
            _excess_line("超額（對母體，判定）", e[POPULATION]),
            _excess_line("超額（對對照基準，只列出）", e["reference"]),
            f"| 絕對報酬（扣成本，判定） | {a['days']} | {_pct(a['mean'], 3)} "
            f"| {_pct(None if a['mean'] is None else a['mean'] * pr.TRADING_DAYS)} | — |",
            "",
            f"門檻：t ≥ {threshold(result.get('min_t', MIN_T))}。",
            "",
            OVERLAP_NOTE["AD1_reference"] + "。",
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
            f"（{w['won']:,}／{w['bought']:,}，期末未賣 {w['unsold']:,}，"
            f"期末未賣的比例 {_pct(result.get('unsold_share'), 1)}）。",
            f"成交計數：買進 {counts.get('bought', 0):,}、漲停買不到 "
            f"{counts.get('limit_up', 0):,}、不可交易 {counts.get('not_tradable', 0):,}、"
            f"跌停順延 {counts.get('limit_down', 0):,}、停牌／缺日線順延 "
            f"{counts.get('sale_held', 0):,}、期末未賣 {counts.get('unsold', 0):,}。",
            "",
        ]
    if result.get("windows"):
        lines += [
            "## 每個窗口（AD1 第 8 點，只列出、不判定）",
            "",
            OVERLAP_NOTE["AD1_windows"] + "。",
            "",
            *window_lines(result["windows"]),
            "",
        ]
    if result.get("inside"):
        lines += _inside_lines(result["inside"])
    for key, summary in (result.get("overlap") or {}).items():
        lines += _yearly_lines(
            "## 和 P1 的重疊（AD1 第 8 點）",
            OVERLAP_NOTE[key],
            summary,
            lambda v: _pct(v, 1),
        )
    if result.get("days_listed"):
        lines += _days_lines(result["days_listed"])
    if result.get("coverage"):
        lines += [
            "## 資料覆蓋（不含報酬）",
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
        portfolio_markdown(result, header), encoding="utf-8"
    )
    if "_dates" in result:
        _write_portfolio(out, result, header)


def _write_portfolio(out: Path, result: dict[str, Any], header: dict[str, Any]) -> None:
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
    fields = ["signal_date", "rank", "exchange", "symbol", *PICK_FIELDS[name], "tie"]
    with (out / "picks.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(result["_rows"])
    sessions = panel.sessions
    with (out / "trades.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(PORTFOLIO_TRADE_FIELDS)
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


def _row(result: dict[str, Any]) -> dict[str, Any]:
    """The overview's row: the excess and the listed parts."""

    row = {"engine": result["engine"], **r5._row(result)}
    for key, part in (result.get("overlap") or {}).items():
        row[f"overlap_{key.split('_')[1].lower()}"] = {
            k: part[k] for k in ("days", "mean")
        }
    if "reference" in (result.get("excess") or {}):
        row["reference_excess"] = result["excess"]["reference"]
    if result.get("days_listed"):
        found = result["days_listed"]
        row["qualified"] = statistics.fmean(d["qualified"] for d in found)
        row["names"] = statistics.fmean(d["names"] for d in found)
    if result.get("windows"):
        shares = [
            w["exp_share"] for w in result["windows"] if w["exp_share"] is not None
        ]
        row["exp_share"] = statistics.fmean(shares) if shares else None
    if result.get("inside"):
        row["inside"] = {k: result["inside"][k] for k in ("names", "inside", "share")}
    if "curves" in result:
        row["invested"] = result["curves"][result["hypothesis"]].get("invested")
        row["unsold_share"] = result.get("unsold_share")
    return row


def overview_markdown(report: dict[str, Any], sha256: str) -> str:
    segment = report["segment"]
    stage = SEGMENT_NAMES[segment]
    lines = [
        f"explore.json 的 sha256：`{sha256}`",
        "",
        f"# 新策略探索 第 {report['round']} 輪 {stage}（round21_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- {OVERLAP_NOTE['summary_only']}",
        OVERLAP_NOTE["AD1_survivor"],
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「第二十一輪：AD1」）：{DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        _threshold_line(segment, report["min_t"]),
        "- 引擎：組合引擎（`portfolio_research.simulate`，K＝5），申報窗口內的每個訊號日買，"
        "窗口之間兩邊都留現金；日數是有淨值的交易日（窗口之間的現金日也算）",
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
        "| 代號 | 方向 | 日數 | 對加權指數超額 | t | 對母體超額 | t | 絕對報酬 | 判定 |"
    )
    rule = "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"
    lines += ["", "## 判定", "", head, rule]
    for name, row in report["hypotheses"].items():
        lines.append(_overview_line(name, row, judged=True))
    listed = []
    for name, row in report["hypotheses"].items():
        if row.get("reference_excess"):
            e = row["reference_excess"]
            listed.append(
                f"- {name} 對對照基準的超額：日均 {_pct(e['mean'], 3)}、t {_t(e['t'])}（{e['days']:,} 日）"
            )
        if row.get("names") is not None:
            listed.append(
                f"- {name} 每個訊號日符合條件的檔數：平均 {lib.num(row.get('qualified'), 1)}；"
                f"名單檔數：平均 {lib.num(row['names'], 1)}"
            )
        if row.get("exp_share") is not None:
            listed.append(
                f"- {name} 每個窗口有 `exp_date` 的比例：平均 {_pct(row['exp_share'], 1)}"
            )
        if row.get("inside"):
            part = row["inside"]
            listed.append(
                f"- {name} 實際公告日落在持有期間內的比例：{_pct(part['share'], 1)}"
                f"（{part['inside']:,}／{part['names']:,} 檔次）"
            )
        part = row.get("overlap_p1")
        if part:
            listed.append(
                f"- {name} 和 P1 的重疊：平均 {_pct(part['mean'], 1)}（{part['days']:,} 個訊號日）"
            )
        if row.get("invested") is not None:
            listed.append(
                f"- {name} 的平均投入比例 {_pct(row['invested'], 1)}、期末未賣的比例 "
                f"{_pct(row.get('unsold_share'), 1)}"
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
        f"| {name} | {spec['direction']} | {row['days']} "
        f"| {_pct(x.get('mean'), 3)} | {_t(x.get('t'))} "
        f"| {_pct(e.get('mean'), 3)} | {_t(e.get('t'))} "
        f"| {_pct(row.get('absolute_mean'), 3)} | {verdict} |"
    )


COVERAGE_NOTES = (
    "- 缺值比例的分母是母體檔次（窗口內每個訊號日的母體加總）；只數窗口內的訊號日；不跑模擬、不算報酬",
    f"- AD1：{DEGENERATE['AD1']}。依年一列：不符合的原因依序判（沒有 `exp_date`、T（含）以前已公告、"
    "預期公告日不在 T+1～T+5），每檔只算第一個；「母體裡的下市、轉板股」是 `status` 為 `delisted`／`transferred` "
    "的母體檔次，「其中沒有 `exp_date`」是對照基準去掉的檔次；每個窗口一列：窗口內任一個訊號日在母體裡的不同檔數，"
    "與其中這個窗口對應的季有 `ann_date`、有 `exp_date` 的檔數（`ann_date` 讀到探索段最後一天）；"
    "`p1_order` 是同一個窗口算 P1 名單（`round15_research.plan_p1`）的時間，`--coverage-only` 不算重疊比例與"
    "實際公告日落在持有期間內的比例，各段的 `summary.md` 才列",
    "- 主旨規則依清單日期的年與季（日曆季）列則數與公司數；「董事會」＋「通過／決議」但沒有財報那組詞的主旨"
    "（幫助判讀，不改規則）依年列則數，最常見的 20 個主旨把公司名稱、代號換成「〈公司〉」、數字換成「#」；"
    "不含的 7 個詞各擋掉的則數，只數含「董事會」＋「通過／決議」＋財報那組詞的主旨，一則含兩個詞時各算一次",
)


def subject_lines(subjects: dict[str, Any]) -> list[str]:
    lines = [
        "| 年 | 則數 | 公司數 |",
        "| --- | ---: | ---: |",
        *(
            f"| {year} | {row['rows']:,} | {row['companies']:,} |"
            for year, row in subjects["years"].items()
        ),
        "",
        "依季（清單日期的日曆季）：",
        "",
        "| 季 | 則數 | 公司數 |",
        "| --- | ---: | ---: |",
        *(
            f"| {key} | {row['rows']:,} | {row['companies']:,} |"
            for key, row in subjects["quarters"].items()
        ),
        "",
        "「董事會」＋「通過／決議」、沒有財報那組詞的主旨依年的則數（幫助判讀，不改規則）：",
        "",
        "| 年 | 則數 |",
        "| --- | ---: |",
        *(f"| {year} | {count:,} |" for year, count in subjects["near_miss"].items()),
        "",
        "其中最常見的 20 個主旨（公司名稱、代號換成「〈公司〉」，數字換成「#」）：",
        "",
        "| 主旨 | 則數 |",
        "| --- | ---: |",
        *(
            f"| {text.replace('|', '｜')} | {count:,} |"
            for text, count in subjects["near_miss_subjects"]
        ),
        "",
        "不含的 7 個詞各擋掉的則數：",
        "",
        "| 詞 | 則數 |",
        "| --- | ---: |",
        *(f"| {word} | {count:,} |" for word, count in subjects["blocked"].items()),
    ]
    return lines


def coverage_markdown(body: dict[str, Any]) -> str:
    load_seconds = body.get("load_seconds_parts", {})
    lines = [
        f"# 新策略探索 第 {body['round']} 輪 AD1 資料覆蓋（探索段，不含報酬）",
        "",
        f"- round21_research 第 {VERSION} 版；定義雜湊 `{body['definitions_sha256']}`",
        f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}，"
        f"alembic `{body['copy']['alembic']}`",
        f"- 重現：`{body['command']}`",
        f"- 耗時 {body.get('elapsed_seconds', 0):.0f} 秒（載入 {body.get('load_seconds', 0):.0f} 秒，"
        f"其中 panel（含重大訊息清單與季報 EPS）{load_seconds.get('panel', 0):.0f} 秒、標的狀態 "
        f"{load_seconds.get('statuses', 0):.0f} 秒；主旨規則的計數 {body.get('subjects_seconds', 0):.1f} 秒），"
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
        lines += [
            f"## {name}（訊號日 {window.get('first_signal', '—')} 起，窗口內的訊號日 "
            f"{window.get('signal_days', 0):,} 日、有淨值的交易日 {window.get('days', 0):,} 日）",
            "",
            *coverage_lines(name, row["coverage"]),
            "",
            "每個窗口：",
            "",
            *window_lines(row.get("windows") or []),
            "",
        ]
    if body.get("subjects"):
        lines += [
            "## AD1：符合主旨規則的重大訊息（`events` 的 `material_information`，清單日期）",
            "",
            *subject_lines(body["subjects"]),
            "",
        ]
    lines += [
        "有明顯斷點或缺值比例異常的年份、2013、2014 年符合主旨規則的公司數不到母體的一半、"
        "某個窗口有 `exp_date` 的檔數不到 20，或「另列」看得出常見的財報董事會公告寫法沒被主旨規則收到時，"
        "先在工具單提問、不跑探索段。",
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
        "engines": {"portfolio_research": "simulate"},
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
        result = run_portfolio(ctx, db, name, EXPLORATION, coverage_only=True)
        hypotheses[name] = {
            "window": result["window"],
            "coverage": result.get("coverage", {}),
            "windows": result.get("windows", []),
            "seconds": result.get("seconds", {}),
        }
        progress(
            f"{name} coverage ({hypotheses[name]['seconds'].get('plan', 0.0):.1f}s)"
        )
    t0 = time.monotonic()
    subjects = subject_counts(ctx)
    body = {
        **public(header),
        "coverage_only": True,
        "hypotheses": hypotheses,
        "subjects": subjects,
        "subjects_seconds": time.monotonic() - t0,
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
    header["_panel"] = ctx.panel
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
    parser = argparse.ArgumentParser(prog="round21_research.py", description=__doc__)
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
        help="exploration (required, not with --coverage-only): AD1; it runs "
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
    command = "python tools/research/round21_research.py " + " ".join(argv)
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
