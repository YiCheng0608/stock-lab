"""Round 15 of the new-strategy exploration: P1～P3 (#984).

docs/spec/evidence.md 第十五輪：P1～P3 and 第十五輪實作釋義: the hypotheses
were registered (commit ``7612838a``, #982, decision 7093927348) before anyone
ran a tool on the backfilled history.  Nothing here is a command-line option:
a change of a definition is a new code.

They are not in ``explore_research.HYPOTHESES``, ``trade_research.HYPOTHESES``
nor ``round4_research`` .. ``round14_research``: their ``definitions_sha256``
hash the whole table, so adding them would make the validation refuse the
exploration reports already run.  P1 and P2 trade on X7's event-day account
(``explore_research.simulate_events``), P3 on ``portfolio_research.simulate``
(K 20); the population, the loading (``explore_research.load_context``),
``explore_judge``, the gate and the ledgers are imported.  The single quarters
are ``feature_evidence._quarter_eps``'s difference, the statutory deadlines
and their event days ``round14_research.quarter_events``, the member table
``mainstream_research``'s (``--members``, as ``round13_research``).  The
overlaps take K2 (``round14_research.eps_turn``), X4 (``explore_research``)
and Z4 (``round8_research``) on the same T, and ``round10_research``'s
``overlap_share``／``overlap_summary``.  New here are only P1's buy days and
the cash between its windows, ``eps_season_3y``, ``margins_up`` (with its own
reading of ``fundamental_snapshots.data_json``), ``nr_ratio_20_240``, P2's
reference population and the listed numbers.

Each signal date T (after its close, only T's data and before):

- P1: on 3/1, 4/15, 7/15 and 10/15 (the next Monday～Friday session), the
  first 20 by ``eps_season_3y`` high first, held to the quarter's statutory
  deadline's close; cash on both sides between the windows.
- P2: on the 4 statutory deadlines, ``margins_up`` (the three margins of the
  latest quarter above the quarter before's and the same quarter's a year
  before), 20 by the hash, held to the next event day (X7).
- P3: ``nr_ratio_20_240`` (the share of overnight-up／intraday-down bars in the
  last 20 over the 240 before) high first, 20, K 20.

``explore_research.explore_judge`` judges with t ≥ 2 on the exploration and
the fixed Bonferroni t ≥ 3.332 (58 hypotheses) on the validation.  Before the
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
from array import array
from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_lib as lib  # noqa: E402
import exit_research as er  # noqa: E402
import explore_research as ex  # noqa: E402
import feature_evidence as features  # noqa: E402
import mainstream_research as ms  # noqa: E402
import portfolio_research as pr  # noqa: E402
import round5_research as r5  # noqa: E402
import round8_research as r8  # noqa: E402
import round10_research as r10  # noqa: E402
import round14_research as r14  # noqa: E402

VERSION = 1
DESIGN = "984"
TOOL = "round15_research"
REGISTRATION_COMMIT = "7612838a"
DECISION = "https://github.com/YiCheng0608/stock-lab/issues/982#issuecomment-7093927348"
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
SEGMENTS = dict(ex.SEGMENTS)
MIN_SEGMENT_DAYS = dict(ex.MIN_SEGMENT_DAYS)
MIN_T = ex.MIN_T  # the exploration's t ≥ 2
# docs 第十五輪 門檻: 1 − Φ(z) = 0.025 ÷ 58, z = 3.3321, 3.332 to the 3rd decimal;
# fixed, not computed when run.
VALIDATION_MIN_T = 3.332
ROUND = 15
ROUND_SIZE = 3
# X1～X8, S1～S3, R1～R2, M1～M2, C1～C4, V1～V3, W1～W4, Y1～Y4, Z1～Z4, B1～B3,
# F1～F4, L1～L4, J1～J4, U1～U3, K1～K3, P1～P3
CUMULATIVE = 58
# Every segment reads the copy from its start, as round10_research ..
# round14_research: P1 reads 3 years of statements, P3 261 bars.
LOAD_FROM = ex.LOAD_FROM
LOAD_RULE = "every segment from LOAD_FROM"
MIN_LOTS = lib.DEFAULT_MIN_LOTS
RAW_DIR_NAME = ex.RAW_DIR_NAME
POPULATION = pr.POPULATION
TAIEX = pr.TAIEX
PORTFOLIO = "portfolio"
EVENTS = "events"
HIGH = r5.HIGH

# 共同 排序與同分
ORDER = (
    "P1, P3 by the feature, missing last, ties by sha256(<T>:<instrument_id>); "
    "P2 not ranked: the first N by sha256(<T>:<instrument_id>); missing fails"
)
SHORT_RULE = "cash, not filled"
# 共同 季報的事件日 (#978 決定 7086393113): a date on a Saturday make-up session
# is put off to the next Monday～Friday session, as round14_research's.
EVENT_DAY_RULE = (
    "the first Monday-to-Friday session on or after the date; a Saturday "
    "make-up session is skipped"
)
SINGLE_QUARTER = (
    "feature_evidence._quarter_eps's difference: Q1 the cumulative figure, "
    "Q2～Q4 the cumulative less the quarter before's of the same year"
)

# P1 (第 1～7 點): (month, day) of the buy day, the month its quarter ends
# and that quarter's year less the buy day's; the sale days are the quarter's
# statutory deadline (round14_research.DEADLINES, the same quarter).
BUY_DAYS = ((3, 1, 12, -1), (4, 15, 3, 0), (7, 15, 6, 0), (10, 15, 9, 0))
SEASON_YEARS = 3  # F − 1, F − 2, F − 3
RANK_RULE = (
    "each year's 4 single-quarter EPS, rounded to EPS_DIGITS decimals, ranked "
    "1..4 from the smallest, equal values the average rank; the mean of "
    "quarter q's 3 ranks"
)
# #984 決定 7095896595: a single quarter is a difference of cumulative figures
# (0.70 - 0.30 = 0.39999999999999997), so it is rounded before the ranks and
# the ties are told; EPS has 2 decimals, so different quarters stay different.
EPS_DIGITS = 6
SEASON_MISSING = "any of the 12 single-quarter values missing: missing, ranked last"
WINDOW_RULE = (
    "one account (X7): bought at the buy day's T+1 open, sold at the close of "
    "the quarter's statutory deadline; that day's new list is empty, so both "
    "sides hold cash to the next buy day; the population the same"
)
WINDOW_DAYS = "the sessions from the buy day's T+1 to the sale day (in the segment)"
P1_START = date(2016, 4, 15)

# P2 (第 1～4 點)
REVENUE = "營業收入"
GROSS = ("營業毛利（毛損）淨額", "營業毛利（毛損）")  # the first, else the second
OPERATING = "營業利益（損失）"
NET = "本期淨利（淨損）"
REPORT_FORMAT = "general"
FIELDS = (
    "revenue",
    "gross",
    "operating",
    "net",
)  # Statement's attributes, in that order
REVENUE_MIN = 0.0  # a single-quarter revenue ≤ 0 fails
LAGS = (1, 4)  # q against q − 1 and q − 4, each margin strictly higher
NUMBER_RULE = "worker.sources.parse_number on the data_json cell"
STATEMENT_RULE = (
    "fundamental_snapshots rows with announcement_date <= T; the latest is the "
    "largest period_end; a needed row (q, q-1, q-4 and the quarters before "
    "them for the single values) missing or a field null is missing; a row of "
    "another report_format fails"
)
SALE = (
    "one account (X7): bought at T+1's open, sold at the close of the next "
    "event day T' (explore_research.simulate_events), the new list bought at "
    "T'+1's open; the population on the same rule and event days"
)
REFERENCE_STATUSES = ("delisted", "transferred")
REFERENCE_RULE = (
    "T's population less the delisted or transferred instruments missing a "
    "field margins_up needs on T (a row of q, q-1, q-4 of the deadline's "
    "quarter or of the quarters before them not known, or one of the four "
    "fields null; not the stale quarter, the report_format nor the revenue "
    "<= 0); the same account and event days"
)
P2_START = date(2014, 5, 15)

# P3 (第 1～6 點)
RECENT = 20  # f20: i = at − 19 .. at
BEFORE = 240  # f240: i = at − 259 .. at − 20
REVERSAL = (
    "open[i] > close[i - 1] and close[i] < open[i], adjusted (Series.open, "
    "Series.close), both strict"
)
NR_MISSING = (
    "at < 260; a suspended bar in at-260..at; an open (at-259..at) or a close "
    "(at-260..at) missing or <= 0; f240 = 0"
)
P3_ANCHOR = date(2007, 12, 3)  # the OTC bars the tools read
K2, X4, Z4 = "K2", "X4", "Z4"  # the lists P2 and P3 overlap with

# The registration (docs 第十五輪：P1～P3), word for word.  ``start`` as
# ``explore_research``.
HYPOTHESES: dict[str, dict[str, Any]] = {
    "P1": {
        "engine": EVENTS,
        "direction": "事件：盈餘季節性",
        "label": "每季申報窗口開始日（3/1、4/15、7/15、10/15），`eps_season_3y`（對應的那一季"
        "在過去 3 年各年 4 季 EPS 裡的平均名次）大者先取 20 檔，持有到法定期限收盤，窗口之間留現金",
        "rule": "window",
        "keys": (("eps_season_3y", HIGH),),
        "short": SHORT_RULE,
        "top": 20,
        "hold": "deadline",
        "start": ("date", P1_START),
    },
    "P2": {
        "engine": EVENTS,
        "direction": "基本面：三率三升",
        "label": "每季法定期限的事件日，`margins_up`（最新一季單季毛利率、營益率、淨利率都高於上一季，"
        "也都高於去年同季）成立，以雜湊取 20 檔、不排序；持有到下一個事件日",
        "rule": "quarterly",
        "conditions": (("margins_up", "is", True),),
        "order": "the hash only",
        "short": SHORT_RULE,
        "top": 20,
        "hold": "next_event",
        "start": ("date", P2_START),
    },
    "P3": {
        "engine": PORTFOLIO,
        "direction": "投資人拉鋸：日間反轉",
        "label": "`nr_ratio_20_240`（近 20 根「隔夜漲、盤中跌」的比例 ÷ 之前 240 根的同一比例）大者先",
        "rule": "daily",
        "keys": (("nr_ratio_20_240", HIGH),),
        "short": SHORT_RULE,
        "top": 20,
        "hold": 20,
        "start": ("session", P3_ANCHOR, 1 + RECENT + BEFORE),
    },
}
OTHER_COMPARISONS = ex.OTHER_COMPARISONS
REASONS = dict(ex.REASONS)
LIMITS = {
    "P1": "窗口約 20 個交易日，探索段只有 15 個窗口，檢定力低；窗口之間兩邊都是現金，"
    "全段的超額平均約是窗口內的 p 倍、標準差約 √p 倍（p 是窗口內日子的比例），t 約等於只用窗口內的日子算；"
    "金融業等法定期限不同的公司照樣算名次，但窗口是一般公司的；名單可能集中在季節性強的少數產業，"
    "看產業分布；下市與轉板標的共 76 個公司年缺 EPS，缺的排最後，偏差方向對假設有利；"
    "驗證段最後一個窗口是 2024-07-15（2024Q2，用 2021～2023 的 EPS）",
    "P2": "存活者偏差：下市股的季報是 XBRL 整包補的，只寫了 EPS，沒有這四個欄位，"
    "期間內下市公司的季幾乎都不符合，會排除之後下市的公司，偏差方向對假設有利，比 K2 的 76 個公司年大；"
    "金融業等格式與法定期限不同的公司不會符合；2013 年的欄名由 `--coverage-only` 列",
    "P3": "日間反轉的定義照論文摘要與二手整理，未讀全文；和 Z4 的關係：Z4 買隔夜報酬最低的，"
    "P3 選隔夜常漲、盤中常跌回的，排序變數不同（頻率，不是報酬的大小）；方向由 Akbas et al. 事先定，"
    "但登記時 Z4 的狀態已知，看和 Z4 的重疊比例",
}
# The degenerate cases as the code judges them (第十五輪實作釋義; PR #913
# review: the docs, coverage.md and summary.md say the same words, a test
# reads the docs' tool section for them).
DEGENERATE = {
    "P1": "12 個單季值（F−1、F−2、F−3 年各 4 季；`announcement_date` ≤ T、EPS 有值的列，"
    "照 `feature_evidence._quarter_eps` 的差法）中任一個缺時缺值、排最後；"
    "名單不足 20 檔時餘額留現金",
    "P2": "最新一季（`announcement_date` ≤ T 的季報列中期末最晚的一季，EPS 是 null 的列也算，和 K2 不同）"
    "不是事件日對應的那一季、q、q−1、q−4 與算單季要用的前一季中任一列的 `report_format` 不是 `general`"
    "（`report_format` 是 null 的列算欄位缺）、"
    "任一列不在或四個欄位任一欄缺（毛利先用 `營業毛利（毛損）淨額`，沒有這一欄時用 `營業毛利（毛損）`），"
    "或任一季的單季營收 ≤ 0 時，不符合；6 個比較中任一個不是嚴格較高（含相等）時也不符合；"
    "符合的不足 20 檔時餘額留現金",
    "P3": "at < 260、at−260…at 的 261 根中任一根停牌、需要的開盤（at−259…at）或收盤（at−260…at）"
    "缺值或 ≤ 0，或 f240＝0 時缺值、排最後",
}
OVERLAP_NOTE = {
    "P2_K2": 'P2 與 K2（`round14_research` 第 1 版的 `HYPOTHESES["K2"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|P2 的名單 ∩ K2 的名單| ÷ P2 當天的名單檔數；P2 或 K2 當天沒有名單的事件日不計。只列出、不判定",
    "P2_X4": 'P2 與 X4（`explore_research` 第 2 版的 `HYPOTHESES["X4"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|P2 的名單 ∩ X4 的前 20 名| ÷ P2 當天的名單檔數；P2 或 X4 當天沒有名單的事件日不計。只列出、不判定",
    "P3_Z4": 'P3 與 Z4（`round8_research` 第 1 版的 `HYPOTHESES["Z4"]`，同一個 T 算）每日名單的重疊比例：'
    "|P3 的名單 ∩ Z4 的前 20 名| ÷ P3 當天的名單檔數；P3 或 Z4 當天沒有名單的日子不計。只列出、不判定",
    "P2_reference": "對照基準：當天母體去掉「缺 `margins_up` 任一所需欄位（事件日對應的那一季的 q、q−1、q−4 "
    "與算單季要用的前一季，任一列不在或四個欄位任一欄缺；不看是不是最新一季、不看 `report_format`、"
    "不看營收 ≤ 0）的 `delisted`／`transferred` 標的」，同一個帳戶規則、同一組事件日；"
    "列 P2 對它的超額與 t，只列出、不判定（判定仍只比母體）",
    "P2_survivor": "- 存活者偏差（P2）：下市股的季報只有 EPS，沒有 `margins_up` 的四個欄位，期間內下市公司的季幾乎都不符合，"
    "會排除之後下市的公司，偏差方向對假設有利。對照基準（母體去掉當天缺欄位的下市、轉板股）的超額與 t "
    "在 `P2/summary.md`「數字」表的「超額（對對照基準，只列出）」列與 `explore.md` 的「只列出、不判定」",
    "P1_window": "只算窗口日：窗口日是買進日的 T+1 到賣出日（段內）的交易日，"
    "超額是這些日子的每日組合報酬 − 每日母體報酬；只列出、不判定",
}
FEATURE_LABELS = {
    "eps_season_3y": "盈餘季節性的平均名次",
    "margins_up": "三率三升",
    "nr_ratio_20_240": "日間反轉的頻率比",
}
PICK_FIELDS = {
    "P1": ("quarter", "eps_season_3y", "ranks"),
    "P2": ("quarter", "gross_margin", "operating_margin", "net_margin"),
    "P3": ("nr_ratio_20_240", "f20", "f240", "overnight_20"),
}


def definitions() -> dict[str, Any]:
    return {
        "version": VERSION,
        "design": DESIGN,
        "hypotheses": HYPOTHESES,
        "order": ORDER,
        "short": SHORT_RULE,
        "event_day": EVENT_DAY_RULE,
        "single_quarter": [SINGLE_QUARTER, features.VERSION],
        "deadlines": [r14.DEADLINES, r14.EVENT_DAY_RULE],  # P1's sales, P2's events
        "features": {
            "eps_season_3y": {
                "buy_days": BUY_DAYS,
                "years": SEASON_YEARS,
                "rank": RANK_RULE,
                "digits": EPS_DIGITS,
                "missing": SEASON_MISSING,
                "window": WINDOW_RULE,
                "window_days": WINDOW_DAYS,
            },
            "margins_up": {
                "fields": [REVENUE, list(GROSS), OPERATING, NET],
                "report_format": REPORT_FORMAT,
                "revenue_min": REVENUE_MIN,
                "lags": LAGS,
                "number": NUMBER_RULE,
                "attributes": FIELDS,
                "statements": STATEMENT_RULE,
                "sale": SALE,
                "reference": [REFERENCE_RULE, list(REFERENCE_STATUSES)],
            },
            "nr_ratio_20_240": {
                "recent": RECENT,
                "before": BEFORE,
                "reversal": REVERSAL,
                "missing": NR_MISSING,
            },
            "overlaps": {
                K2: [r14.HYPOTHESES[K2], r14.VERSION, r14.definitions_sha256()],
                X4: [ex.HYPOTHESES[X4], ex.VERSION],
                Z4: [r8.HYPOTHESES[Z4], r8.VERSION, r8.definitions_sha256()],
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
    """Hash of every fixed number the verdicts depend on (the definitions,
    P1's buy and sale days, 3 years and the average ranks, P2's fields, format,
    lags and reference, P3's windows and missing rules, N and K, the order,
    the overlaps' lists, the segments, the costs).  A changed tool needs a new
    exploration report before a validation."""

    text = json.dumps(definitions(), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- reading ----------------------------------------------------------------------


@dataclass(frozen=True)
class Statement:
    """One ``fundamental_snapshots`` row for P2: the year's cumulative
    figures (thousands) of the four fields, None when the cell is missing."""

    announced: date
    period_end: date
    report_format: str | None
    revenue: float | None
    gross: float | None
    operating: float | None
    net: float | None
    gross_fallback: bool = False  # 營業毛利（毛損） read, no 淨額 column


def statement_of(
    announced: str, period_end: str, data: dict[str, Any], parse
) -> Statement:
    def value(name: str) -> float | None:
        return parse(data.get(name)) if name in data else None

    primary, fallback = GROSS
    return Statement(
        date.fromisoformat(announced),
        date.fromisoformat(period_end),
        data.get("report_format"),
        value(REVENUE),
        value(primary) if primary in data else value(fallback),
        value(OPERATING),
        value(NET),
        primary not in data and fallback in data,
    )


def load_statements(
    db: Path, series: dict[int, lib.Series], end: date
) -> dict[int, list[Statement]]:
    """P2: every row with an ``announcement_date`` ≤ ``end`` (none after it
    read), by announcement; ``evidence_lib`` loads only the rows with an EPS."""

    from worker.sources import parse_number

    out: dict[int, list[Statement]] = defaultdict(list)
    con = lib.connect_read_only(db)
    try:
        rows = con.execute(
            "select instrument_id, announcement_date, period_end, data_json "
            "from fundamental_snapshots where announcement_date is not null "
            "and announcement_date <= ? order by announcement_date, period_end",
            (end.isoformat(),),
        )
        for instrument_id, announced, period_end, text in rows:
            if instrument_id not in series:
                continue
            try:
                data = json.loads(text) if text else {}
            except ValueError:
                data = {}
            if not isinstance(data, dict):
                data = {}
            out[instrument_id].append(
                statement_of(announced, period_end, data, parse_number)
            )
    finally:
        con.close()
    return dict(out)


def load_statuses(db: Path) -> dict[int, str]:
    con = lib.connect_read_only(db)
    try:
        return {i: s for i, s in con.execute("select id, status from instruments")}
    finally:
        con.close()


def columns_2013(db: Path) -> dict[str, Any]:
    """P2 第 9 點 (``--coverage-only``): 2013's column names by quarter and
    report_format, and the rows with each of the fields."""

    con = lib.connect_read_only(db)
    out: dict[str, Any] = {}
    try:
        rows = con.execute(
            "select period_end, data_json from fundamental_snapshots "
            "where period_end between '2013-01-01' and '2013-12-31' "
            "order by period_end"
        )
        for period_end, text in rows:
            try:
                data = json.loads(text) if text else {}
            except ValueError:
                data = {}
            if not isinstance(data, dict):
                data = {}
            kind = str(data.get("report_format"))
            quarter = out.setdefault(period_end, {})
            part = quarter.setdefault(
                kind, {"rows": 0, "fields": Counter(), "columns": Counter()}
            )
            part["rows"] += 1
            part["columns"].update(data.keys())
            for name in (REVENUE, *GROSS, OPERATING, NET):
                part["fields"][name] += name in data
    finally:
        con.close()
    return {
        quarter: {
            kind: {
                "rows": part["rows"],
                "fields": dict(part["fields"]),
                "columns": sorted(part["columns"]),
            }
            for kind, part in sorted(kinds.items())
        }
        for quarter, kinds in sorted(out.items())
    }


@dataclass
class Context:
    """``explore_research``'s context (the market, the quotes, the EPS
    quarters), P2's statements, the instruments' status, the member table
    (P1's industries), ``round8_research``'s context for Z4.  One panel."""

    base: ex.Context
    statements: dict[int, list[Statement]] = field(default_factory=dict)
    statuses: dict[int, str] = field(default_factory=dict)
    groups: ms.Context | None = None
    z4: r8.Context | None = None
    seconds: Counter = field(default_factory=Counter)
    load_seconds: dict[str, float] = field(default_factory=dict)
    # P3: per instrument, prefix counts of the reversals and the bad prices
    reversals: dict[int, tuple[array, array, array]] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)  # group id -> label

    def __post_init__(self) -> None:
        if self.z4 is None:
            self.z4 = r8.Context(self.base)

    @property
    def market(self) -> pr.Market:
        return self.base.market

    @property
    def panel(self) -> lib.Panel:
        return self.base.market.panel

    def quote(self, instrument_id: int, s: int) -> pr.Quote | None:
        return self.base.quote(instrument_id, s)


def load(db: Path, members: Path, start: date, end: date, raw_dir: Path) -> Context:
    """The panel, the turnovers, the EPS quarters, P2's statements and the
    member snapshots to ``end``; nothing after ``end`` is read."""

    started = time.monotonic()
    base = ex.load_context(db, start, end, raw_dir)
    panel_seconds = time.monotonic() - started
    t0 = time.monotonic()
    statements = load_statements(db, base.market.panel.series, end)
    statuses = load_statuses(db)
    statement_seconds = time.monotonic() - t0
    t0 = time.monotonic()
    groups = ms.build_context(base.market, ms.read_members(members, end))
    return Context(
        base,
        statements,
        statuses,
        groups,
        load_seconds={
            "panel": panel_seconds,
            "statements": statement_seconds,
            "members": time.monotonic() - t0,
        },
    )


# --- the event days ---------------------------------------------------------------


def _event_days(sessions: list[date], table) -> list[tuple[int, date]]:
    """(index of the first Monday～Friday session from each (month, day) of
    ``table``, the end of its quarter), in date order; ``round14_research.
    quarter_events``' rule (#978 決定 7086393113) on another table.  A date
    before the first session read is no event (the copy starts in 2004, before
    every buy day used)."""

    if not sessions:
        return []
    out: list[tuple[int, date]] = []
    for year in range(sessions[0].year, sessions[-1].year + 1):
        for month, day, end_month, offset in table:
            if date(year, month, day) < sessions[0]:
                continue
            at = bisect_left(sessions, date(year, month, day))
            while at < len(sessions) and sessions[at].weekday() >= 5:
                at += 1
            if at >= len(sessions) or (out and out[-1][0] >= at):
                continue
            end_day = 31 if end_month in (3, 12) else 30
            out.append((at, date(year + offset, end_month, end_day)))
    return out


def buy_events(sessions: list[date]) -> list[tuple[int, date]]:
    """P1 第 1 點: the buy days 3/1, 4/15, 7/15, 10/15 and their quarters."""

    return _event_days(sessions, BUY_DAYS)


def sale_days(sessions: list[date]) -> dict[date, int]:
    """P1 第 1 點: the quarter's statutory deadline (``round14_research.
    quarter_events``) by the quarter's end."""

    return {quarter: at for at, quarter in r14.quarter_events(sessions)}


# --- features ---------------------------------------------------------------------


def _quarter_before(end: date) -> date:
    month = end.month - 3
    if month <= 0:
        return date(end.year - 1, 12, 31)
    return date(end.year, month, 31 if month == 3 else 30)


def _quarter_back(end: date, n: int) -> date:
    for _ in range(n):
        end = _quarter_before(end)
    return end


def single_quarter(cumulative: dict[date, float], end: date) -> float | None:
    """The single quarter ending ``end`` from the year's cumulative figures by
    ``feature_evidence._quarter_eps`` itself (its difference, not rewritten):
    the figures to ``end`` are its quarters as known on ``end``."""

    if end not in cumulative:
        return None
    rows = sorted((e, e, value) for e, value in cumulative.items() if e <= end)
    parts = features._quarter_eps(SimpleNamespace(dates=[end], quarters=rows), 0)
    return None if parts is None else parts[0]


@dataclass(frozen=True)
class Season:
    value: float | None
    ranks: tuple[float, ...] = ()


def _average_rank(values: list[float], at: int) -> float:
    """1 + the smaller ones + half of the other equal ones (ties averaged)."""

    mine = values[at]
    smaller = sum(1 for v in values if v < mine)
    equal = sum(1 for v in values if v == mine)
    return 1 + smaller + (equal - 1) / 2


def eps_season_3y(item: lib.Series, day: date, quarter: date) -> Season:
    """P1 第 3、4 點: the mean of quarter q's ranks among the 4 single-quarter
    EPS of each of F − 1 .. F − 3 (``announcement_date`` ≤ T), each rounded to
    ``EPS_DIGITS`` decimals first (#984 決定 7095896595)."""

    cumulative = {end: eps for announced, end, eps in item.quarters if announced <= day}
    q = quarter.month // 3
    ranks = []
    for back in range(1, SEASON_YEARS + 1):
        year = quarter.year - back
        ends = [
            date(year, 3, 31),
            date(year, 6, 30),
            date(year, 9, 30),
            date(year, 12, 31),
        ]
        values = [single_quarter(cumulative, end) for end in ends]
        if any(value is None for value in values):
            return Season(None)
        rounded = [round(value, EPS_DIGITS) for value in values]
        ranks.append(_average_rank(rounded, q - 1))
    return Season(statistics.fmean(ranks), tuple(ranks))


@dataclass(frozen=True)
class Margins:
    qualifies: bool
    # "stale", "format", "fields", "revenue", "lower" or None
    reason: str | None = None
    rates: tuple[tuple[float, float, float], ...] = ()  # q, q − 1, q − 4


def _known(rows: list[Statement], day: date) -> dict[date, Statement]:
    return {row.period_end: row for row in rows if row.announced <= day}


def _needed(quarter: date) -> list[date]:
    """q, q − 1, q − 4 and the quarter before each (not before a Q1)."""

    out = []
    for lag in (0, *LAGS):
        end = _quarter_back(quarter, lag)
        out.append(end)
        if end.month != 3:
            out.append(_quarter_before(end))
    return list(dict.fromkeys(out))


def _singles(known: dict[date, Statement], quarter: date):
    """Each field's single quarters q, q − 1, q − 4, or None when one is missing."""

    out = []
    for name in FIELDS:
        cumulative = {
            end: getattr(row, name)
            for end, row in known.items()
            if getattr(row, name) is not None
        }
        values = [
            single_quarter(cumulative, _quarter_back(quarter, lag))
            for lag in (0, *LAGS)
        ]
        if any(value is None for value in values):
            return None
        out.append(values)
    return out


def fields_missing(ctx: Context, item: lib.Series, day: date, quarter: date) -> bool:
    """P2 第 3 點 second case on the deadline's ``quarter`` (the reference's
    rule, 第十五輪實作釋義): a needed row not known on T or a field missing."""

    known = _known(ctx.statements.get(item.instrument_id, []), day)
    for end in _needed(quarter):
        row = known.get(end)
        if row is None or any(getattr(row, name) is None for name in FIELDS):
            return True
    return _singles(known, quarter) is None


def margins_up(ctx: Context, item: lib.Series, day: date, quarter: date) -> Margins:
    """P2 第 1～3 點 on T (``day``) for the deadline's ``quarter``."""

    known = _known(ctx.statements.get(item.instrument_id, []), day)
    if not known or max(known) != quarter:
        return Margins(False, "stale")
    rows = [known.get(end) for end in _needed(quarter)]
    if any(
        row is not None
        and row.report_format is not None
        and row.report_format != REPORT_FORMAT
        for row in rows
    ):
        return Margins(False, "format")
    if any(
        row is None
        or row.report_format != REPORT_FORMAT
        or any(getattr(row, name) is None for name in FIELDS)
        for row in rows
    ):
        return Margins(False, "fields")
    singles = _singles(known, quarter)
    if singles is None:
        return Margins(False, "fields")
    revenue, gross, operating, net = singles
    if any(value <= REVENUE_MIN for value in revenue):
        return Margins(False, "revenue")
    rates = tuple(
        (gross[k] / revenue[k], operating[k] / revenue[k], net[k] / revenue[k])
        for k in range(1 + len(LAGS))
    )
    up = all(
        rates[0][j] > rates[k][j] for k in range(1, 1 + len(LAGS)) for j in range(3)
    )
    return Margins(up, None if up else "lower", rates)


def _reversal_prefix(ctx: Context, item: lib.Series) -> tuple[array, array, array]:
    """Prefix counts before position k: reversals, opens and closes missing or ≤ 0."""

    parts = ctx.reversals.get(item.instrument_id)
    if parts is None:
        opens, closes = item.open, item.close
        reversal, bad_open, bad_close = (
            array("i", [0]),
            array("i", [0]),
            array("i", [0]),
        )
        for i in range(len(item.dates)):
            o, c = opens[i], closes[i]
            hit = i > 0 and o > closes[i - 1] and c < o
            reversal.append(reversal[-1] + hit)
            bad_open.append(bad_open[-1] + (not o > 0))  # NaN fails too
            bad_close.append(bad_close[-1] + (not c > 0))
        parts = (reversal, bad_open, bad_close)
        ctx.reversals[item.instrument_id] = parts
    return parts


@dataclass(frozen=True)
class Ratio:
    value: float | None
    reason: str | None = None  # "short", "suspended", "price", "f240_zero"
    f20: float | None = None
    f240: float | None = None


def nr_ratio_20_240(ctx: Context, item: lib.Series, at: int) -> Ratio:
    """P3 第 1～3 點 on the item's bar ``at`` (T)."""

    first = at - RECENT - BEFORE  # at − 260
    if first < 0:
        return Ratio(None, "short")
    if r8._suspended_in(item, first, at):
        return Ratio(None, "suspended")
    reversal, bad_open, bad_close = _reversal_prefix(ctx, item)
    if bad_open[at + 1] != bad_open[first + 1] or bad_close[at + 1] != bad_close[first]:
        return Ratio(None, "price")
    split = at - RECENT + 1  # at − 19
    f20 = (reversal[at + 1] - reversal[split]) / RECENT
    f240 = (reversal[split] - reversal[first + 1]) / BEFORE
    if f240 == 0:
        return Ratio(None, "f240_zero", f20, f240)
    return Ratio(f20 / f240, None, f20, f240)


# --- the plans --------------------------------------------------------------------


def segment_window(
    sessions: list[date], segment: str, spec: dict[str, Any]
) -> tuple[int, int] | None:
    """(first, last) index of the sessions with an equity value, or None.
    P1's and P2's equity starts the session after their first event day in
    the segment (as X7's)."""

    first_day, last_day = SEGMENTS[segment]
    last = bisect_left(sessions, last_day + timedelta(days=1)) - 1
    if first_day is None:
        base = ex.start_index(sessions, spec["start"])
        if base is None:
            return None
    else:
        base = max(bisect_left(sessions, first_day), 1) - 1
    events = None
    if spec["rule"] == "quarterly":
        events = r14.quarter_events(sessions)
    elif spec["rule"] == "window":
        events = buy_events(sessions)
    if events is not None:
        found = [at for at, _q in events if at >= base]
        if not found:
            return None
        base = found[0]
    first = base + 1
    return (first, last) if first <= last else None


@dataclass
class Plan:
    picks: dict[int, list[int]] = field(default_factory=dict)
    population: dict[int, list[int]] = field(default_factory=dict)
    reference: dict[int, list[int]] = field(default_factory=dict)  # P2
    dues: dict[int, int] = field(default_factory=dict)  # P1, P2
    rows: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    signal_days: int = 0
    event_days: int = 0
    overlap: dict[str, dict[str, list[float]]] = field(default_factory=dict)
    overnight: dict[str, list[float]] = field(default_factory=dict)  # P3
    windows: list[dict[str, Any]] = field(default_factory=list)  # P1
    industries: Counter = field(default_factory=Counter)  # P1
    industry_windows: int = 0
    rebalances: list[dict[str, Any]] = field(default_factory=list)  # P2


def _year(coverage: dict[str, Any], day: date, members: int) -> dict[str, Any]:
    year = coverage.setdefault(str(day.year), {"days": 0, "members": 0})
    year["days"] += 1
    year["members"] += members
    return year


def _add(row: dict[str, Any], key: str, value: int) -> None:
    row[key] = row.get(key, 0) + value


def _pick_row(ctx: Context, day: date, rank: int, instrument_id: int, values, tie):
    exchange, symbol, _ = ctx.panel.symbols.get(instrument_id, ("", "", ""))
    return {
        "signal_date": day.isoformat(),
        "rank": rank,
        "exchange": exchange,
        "symbol": symbol,
        **values,
        "tie": tie[:12],
    }


def _group_labels(groups: ms.Context) -> dict[str, str]:
    return {
        member.group_id: member.label
        for rows in groups.snapshots.values()
        for member in rows
    }


def industries_of(ctx: Context, day: date, names: list[int]) -> Counter | None:
    """P1 第 8 點: the list's industries on T (``mainstream_research.
    group_members``), each name once per group; None after the table's last
    month (not listed)."""

    if ctx.groups is None or day > date.fromisoformat(ms.MEMBERS_LAST):
        return None
    t0 = time.perf_counter()
    grouped = ms.group_members(ctx.groups, day)[0]
    if not ctx.labels:
        ctx.labels = _group_labels(ctx.groups)
    labels = ctx.labels
    out: Counter = Counter()
    for instrument_id in names:
        found = [g for g, ids in grouped.items() if instrument_id in ids]
        for group_id in found:
            out[labels.get(group_id, group_id)] += 1
        if not found:
            out["（不在成員表）"] += 1
    ctx.seconds["industries"] += time.perf_counter() - t0
    return out


def plan_p1(
    ctx: Context, spec: dict[str, Any], first: int, last: int, keep_rows=True
) -> Plan:
    """P1 第 1～4 點: on each buy day T of the segment, T's population by
    ``eps_season_3y`` high first, 20, held to the quarter's deadline."""

    panel = ctx.panel
    sessions = panel.sessions
    out = Plan()
    top = spec["top"]
    keys = tuple(name for name, _direction in spec["keys"])
    sales = sale_days(sessions)
    for at, quarter in buy_events(sessions):
        if not first - 1 <= at <= last - 1:
            continue
        day = sessions[at]
        members = lib.universe(panel, day, MIN_LOTS)
        out.signal_days += 1
        out.event_days += 1
        t0 = time.perf_counter()
        rows = []
        for item, _k in members:
            season = eps_season_3y(item, day, quarter)
            rows.append(
                (item.instrument_id, season, pr.tie_break(day, item.instrument_id))
            )
        ctx.seconds["eps_season_3y"] += time.perf_counter() - t0
        rows.sort(key=lambda row: pr.ranking_key({keys[0]: row[1].value}, keys, row[2]))
        chosen = rows[:top]
        sale = sales.get(quarter)
        due = sale if sale is not None and sale <= last else last + 1
        window = {
            "signal_date": day.isoformat(),
            "quarter": quarter.isoformat(),
            "sale_date": sessions[sale].isoformat() if sale is not None else None,
            "members": len(members),
            "valued": sum(1 for _i, s, _t in rows if s.value is not None),
            "missing": sum(1 for _i, s, _t in rows if s.value is None),
            "names": len(chosen),
            "days": min(due, last) - at,
        }
        out.coverage.setdefault("windows", []).append(window)
        if not keep_rows:
            continue
        names = [instrument_id for instrument_id, _s, _t in chosen]
        found = industries_of(ctx, day, names)
        if found is not None:
            out.industries.update(found)
            out.industry_windows += 1
        out.windows.append({**window, "first": at + 1, "last": min(due, last)})
        out.picks[at + 1] = names
        out.population[at + 1] = [item.instrument_id for item, _ in members]
        out.dues[at + 1] = due
        for place, (instrument_id, season, tie) in enumerate(chosen, 1):
            out.rows.append(
                _pick_row(
                    ctx, day, place, instrument_id,
                    {"quarter": quarter.isoformat(), "eps_season_3y": season.value,
                     "ranks": ";".join(lib.num(r, 1) for r in season.ranks)},
                    tie,
                )
            )  # fmt: skip
    return out


def k2_names(
    ctx: Context, day: date, members: list[tuple[lib.Series, int]], quarter: date
) -> set[int]:
    """K2's list on ``day`` (``round14_research`` 第 1 版的定義: ``eps_turn``,
    the first 20 by the hash)."""

    t0 = time.perf_counter()
    spec = r14.HYPOTHESES[K2]
    found = sorted(
        (pr.tie_break(day, item.instrument_id), item.instrument_id)
        for item, k in members
        if r14.eps_turn(item, k, quarter).qualifies
    )
    ctx.seconds["k2_order"] += time.perf_counter() - t0
    return {instrument_id for _t, instrument_id in found[: spec["top"]]}


def x4_names(
    ctx: Context, day: date, members: list[tuple[lib.Series, int]]
) -> set[int]:
    """X4's list on ``day`` (``explore_research`` 第 2 版的定義, as
    ``round14_research.x4_names``)."""

    return r14.x4_names(ctx, day, members)


def plan_p2(
    ctx: Context, spec: dict[str, Any], first: int, last: int, keep_rows=True
) -> Plan:
    """P2 第 1～4、7 點: the event days of the segment, ``margins_up`` in T's
    population, 20 by the hash, held to the next event day (X7); the
    reference population on the same days."""

    panel = ctx.panel
    sessions = panel.sessions
    out = Plan(overlap={"P2_K2": {}, "P2_X4": {}})
    top = spec["top"]
    every = r14.quarter_events(sessions)
    following = {at: nxt for (at, _q), (nxt, _n) in zip(every, every[1:])}
    for at, quarter in every:
        if not first - 1 <= at <= last - 1:
            continue
        day = sessions[at]
        members = lib.universe(panel, day, MIN_LOTS)
        year = _year(out.coverage, day, len(members))
        out.signal_days += 1
        out.event_days += 1
        t0 = time.perf_counter()
        found, reasons = [], Counter()
        for item, _k in members:
            got = margins_up(ctx, item, day, quarter)
            reasons[got.reason] += 1
            if got.qualifies:
                found.append((pr.tie_break(day, item.instrument_id), item, got))
        ctx.seconds["margins_up"] += time.perf_counter() - t0
        t0 = time.perf_counter()
        gone = gone_missing = 0
        excluded = set()
        for item, _k in members:
            if ctx.statuses.get(item.instrument_id) in REFERENCE_STATUSES:
                gone += 1
                if fields_missing(ctx, item, day, quarter):
                    gone_missing += 1
                    excluded.add(item.instrument_id)
        ctx.seconds["reference"] += time.perf_counter() - t0
        found.sort(key=lambda row: row[0])
        chosen = found[:top]
        event = {
            "signal_date": day.isoformat(),
            "quarter": quarter.isoformat(),
            "members": len(members),
            "hits": len(found),
            **{
                key: reasons[key]
                for key in ("stale", "format", "fields", "revenue", "lower")
            },
            "names": len(chosen),
            "delisted": gone,
            "delisted_missing": gone_missing,
            "fallback": sum(
                1
                for item, _k in members
                for row in ctx.statements.get(item.instrument_id, ())
                if row.period_end == quarter
                and row.announced <= day
                and row.gross_fallback
            ),
        }
        for key in ("hits", "delisted", "delisted_missing"):
            _add(year, key, event[key])
        year.setdefault("events", []).append(event)
        other_k2 = k2_names(ctx, day, members, quarter)  # timed in the coverage too
        other_x4 = x4_names(ctx, day, members)
        if not keep_rows:
            continue
        names = [item.instrument_id for _t, item, _m in chosen]
        shares = {}
        for key, other in (("P2_K2", other_k2), ("P2_X4", other_x4)):
            share = r10.overlap_share(names, other)
            shares[key] = share
            if share is not None:
                out.overlap.setdefault(key, {}).setdefault(str(day.year), []).append(
                    share
                )
        out.rebalances.append(
            {**event, "k2_overlap": shares["P2_K2"], "x4_overlap": shares["P2_X4"]}
        )
        out.picks[at + 1] = names
        out.population[at + 1] = [item.instrument_id for item, _ in members]
        out.reference[at + 1] = [
            item.instrument_id
            for item, _ in members
            if item.instrument_id not in excluded
        ]
        due = following.get(at)
        out.dues[at + 1] = due if due is not None and due <= last else last + 1
        for place, (tie, item, got) in enumerate(chosen, 1):
            out.rows.append(
                _pick_row(
                    ctx, day, place, item.instrument_id,
                    {"quarter": quarter.isoformat(), "gross_margin": got.rates[0][0],
                     "operating_margin": got.rates[0][1], "net_margin": got.rates[0][2]},
                    tie,
                )
            )  # fmt: skip
    return out


def z4_names(
    ctx: Context, day: date, members: list[tuple[lib.Series, int]]
) -> set[int]:
    """Z4's list on ``day`` (``round8_research`` 第 1 版的定義, not rewritten)."""

    t0 = time.perf_counter()
    spec = r8.HYPOTHESES[Z4]
    rows = r8.rank(ctx.z4, spec, day, members).rows
    ctx.seconds["z4_order"] += time.perf_counter() - t0
    return {row[0] for row in rows[: spec["top"]]}


def plan_p3(
    ctx: Context, spec: dict[str, Any], first: int, last: int, keep_rows=True
) -> Plan:
    """P3 第 1～5 點 on the signal dates ``first − 1`` .. ``last − 1``."""

    panel = ctx.panel
    out = Plan(overlap={"P3_Z4": {}})
    top = spec["top"]
    keys = tuple(name for name, _direction in spec["keys"])
    for at in range(first - 1, last):
        day = panel.sessions[at]
        members = lib.universe(panel, day, MIN_LOTS)
        year = _year(out.coverage, day, len(members))
        out.signal_days += 1
        t0 = time.perf_counter()
        rows, missing = [], Counter()
        for item, k in members:
            ratio = nr_ratio_20_240(ctx, item, k)
            if ratio.value is None:
                missing["nr_ratio_20_240"] += 1
                missing[ratio.reason] += 1
            rows.append((item, k, ratio, pr.tie_break(day, item.instrument_id)))
        ctx.seconds["nr_ratio_20_240"] += time.perf_counter() - t0
        rows.sort(key=lambda row: pr.ranking_key({keys[0]: row[2].value}, keys, row[3]))
        chosen = rows[:top]
        missing_year = year.setdefault("missing", {})
        for key, count in missing.items():
            missing_year[key] = missing_year.get(key, 0) + count
        _add(year, "valued", len(members) - missing["nr_ratio_20_240"])
        other = z4_names(ctx, day, members)  # timed in the coverage too
        if not keep_rows:
            continue
        names = [item.instrument_id for item, _k, _r, _t in chosen]
        share = r10.overlap_share(names, other)
        if share is not None:
            out.overlap.setdefault("P3_Z4", {}).setdefault(str(day.year), []).append(
                share
            )
        t0 = time.perf_counter()
        nights = [r8.overnight_20(ctx.z4, item, k) for item, k, _r, _t in chosen]
        ctx.seconds["overnight_20"] += time.perf_counter() - t0
        valued = [v for v in nights if v is not None]
        if valued:
            out.overnight.setdefault(str(day.year), []).append(statistics.fmean(valued))
        out.picks[at + 1] = names
        out.population[at + 1] = [item.instrument_id for item, _ in members]
        for place, ((item, _k, ratio, tie), night) in enumerate(zip(chosen, nights), 1):
            out.rows.append(
                _pick_row(
                    ctx, day, place, item.instrument_id,
                    {"nr_ratio_20_240": ratio.value, "f20": ratio.f20,
                     "f240": ratio.f240, "overnight_20": night},
                    tie,
                )
            )  # fmt: skip
    return out


def planner(name: str) -> Callable[..., Plan]:
    return {"P1": plan_p1, "P2": plan_p2, "P3": plan_p3}[name]


overlap_share = r10.overlap_share
overlap_summary = r10.overlap_summary
_window_facts = r5._window_facts


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
) -> tuple[pr.Simulation, pr.Simulation, pr.Simulation | None]:
    """(the hypothesis, the population, P2's reference): P1 and P2 X7's
    account, P3 K accounts."""

    spec = HYPOTHESES[name]
    if spec["engine"] == EVENTS:
        mine = ex.simulate_events(
            planned.picks, planned.dues, ctx.quote, first, last, spec["top"]
        )
        population = ex.simulate_events(
            planned.population, planned.dues, ctx.quote, first, last, None
        )
        reference = None
        if name == "P2":
            reference = ex.simulate_events(
                planned.reference, planned.dues, ctx.quote, first, last, None
            )
        return mine, population, reference
    mine = pr.simulate(planned.picks, ctx.quote, first, last, spec["hold"], spec["top"])
    population = pr.simulate(
        planned.population, ctx.quote, first, last, spec["hold"], None
    )
    return mine, population, None


def window_excess(
    windows: list[dict[str, Any]], first: int, differences: list[float]
) -> dict[str, Any]:
    """P1 第 8 點: the excess on the window days only (``WINDOW_DAYS``)."""

    inside = set()
    for window in windows:
        inside.update(range(window["first"], window["last"] + 1))
    picked = [d for i, d in enumerate(differences) if first + i in inside]
    return pr.excess_metrics(picked)


def run_portfolio(
    ctx: Context,
    db: Path,
    name: str,
    segment: str,
    coverage_only: bool = False,
    min_t: float = MIN_T,
) -> dict[str, Any]:
    """P1, P2 or P3 on one segment: its numbers, verdict and private parts."""

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
    started = time.monotonic()
    planned = planner(name)(ctx, spec, first, last, keep_rows=not coverage_only)
    result["window"]["signal_days"] = planned.signal_days
    result["window"]["event_days"] = planned.event_days
    result["coverage"] = planned.coverage
    result["seconds"] = {"plan": time.monotonic() - started, **ctx.seconds}
    if coverage_only:
        return result
    result["overlap"] = {
        key: overlap_summary(by_year) for key, by_year in planned.overlap.items()
    }
    if name == "P3":
        result["overnight"] = overlap_summary(planned.overnight)
    mine, population, reference = engines(ctx, name, planned, first, last)
    returns = pr.daily_returns(mine.equity)
    others = pr.daily_returns(population.equity)
    taiex = ex._taiex(ctx.panel, first, last)
    differences = [a - b for a, b in zip(returns, others)]
    excess = {
        POPULATION: pr.excess_metrics(differences),
        TAIEX: pr.excess_metrics(
            [a - b for a, b in zip(returns, taiex) if b is not None]
        ),
    }
    if reference is not None:
        base = pr.daily_returns(reference.equity)
        excess["reference"] = pr.excess_metrics([a - b for a, b in zip(returns, base)])
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
    if name == "P1":
        result["windows"] = [
            {key: value for key, value in w.items() if key not in ("first", "last")}
            for w in planned.windows
        ]
        result["window_excess"] = window_excess(planned.windows, first, differences)
        result["window_days"] = sum(w["days"] for w in planned.windows)
        result["industries"] = (
            {
                "windows": planned.industry_windows,
                "names": sum(planned.industries.values()),
                "counts": dict(planned.industries.most_common()),
            }
            if planned.industry_windows
            else None
        )
    if name == "P2":
        for event in planned.rebalances:
            s = sessions.index(date.fromisoformat(event["signal_date"])) + 1
            event["invested"] = mine.invested[s - first] if s <= last else None
        result["rebalances"] = planned.rebalances
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
seconds_lines = r10.seconds_lines


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


def _hold_text(hold: Any) -> str:
    return {
        "deadline": "持有到法定期限收盤，窗口之間留現金",
        "next_event": "持有到下一個事件日",
    }.get(hold, f"K＝{hold}")


def coverage_lines(name: str, coverage: dict[str, Any]) -> list[str]:
    """P1 each window, P2 each event day, P3 by year."""

    if name == "P1":
        head = ["買進日", "對應的季", "賣出日", "母體檔次", "有 `eps_season_3y` 的檔數",
                "因缺單季值而缺值", "（比例）", "名單檔數", "窗口內的交易日"]  # fmt: skip
        lines = [
            "| " + " | ".join(head) + " |",
            "| --- | --- | --- | " + " | ".join("---:" for _ in head[3:]) + " |",
        ]
        for w in coverage.get("windows", []):
            lines.append(
                f"| {w['signal_date']} | {w['quarter']} | {w['sale_date'] or '—'} "
                f"| {w['members']:,} | {w['valued']:,} | {w['missing']:,} "
                f"| {_share(w['missing'], w['members'])} | {w['names']:,} | {w['days']:,} |"
            )
        return lines
    if name == "P2":
        head = ["事件日", "對應的季", "母體檔次", "符合 `margins_up`", "名單檔數",
                "最新一季不是對應的那一季", "`report_format` 不是 `general`", "欄位缺",
                "（比例）", "單季營收 ≤ 0", "比較不成立", "毛利用備用欄名",
                "母體裡的下市、轉板股", "（其中缺所需欄位）"]  # fmt: skip
        lines = [
            "| " + " | ".join(head) + " |",
            "| --- | --- | " + " | ".join("---:" for _ in head[2:]) + " |",
        ]
        for _year_, row in sorted(coverage.items()):
            for e in row.get("events", []):
                lines.append(
                    f"| {e['signal_date']} | {e['quarter']} | {e['members']:,} | {e['hits']:,} "
                    f"| {e['names']:,} | {e['stale']:,} | {e['format']:,} | {e['fields']:,} "
                    f"| {_share(e['fields'], e['members'])} | {e['revenue']:,} | {e['lower']:,} "
                    f"| {e['fallback']:,} | {e['delisted']:,} | {e['delisted_missing']:,} |"
                )
        lines += ["", "依年：", "",
                  "| 年 | 事件日 | 母體檔次 | 符合 `margins_up` | 母體裡的下市、轉板股檔次 | 其中缺 `margins_up` 所需欄位 |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"]  # fmt: skip
        for year, row in sorted(coverage.items()):
            lines.append(
                f"| {year} | {row['days']:,} | {row['members']:,} | {row.get('hits', 0):,} "
                f"| {row.get('delisted', 0):,} | {row.get('delisted_missing', 0):,} |"
            )
        return lines
    head = ["年", "日數", "母體檔次", "有 `nr_ratio_20_240` 的檔次", "缺值", "（at < 260）",
            "（停牌）", "（開盤或收盤缺值或 ≤ 0）", "（f240＝0）"]  # fmt: skip
    lines = [
        "| " + " | ".join(head) + " |",
        "| --- | " + " | ".join("---:" for _ in head[1:]) + " |",
    ]
    for year, row in sorted(coverage.items()):
        members, missing = row["members"], row.get("missing", {})
        lines.append(
            f"| {year} | {row['days']:,} | {members:,} | {row.get('valued', 0):,} "
            f"| {_share(missing.get('nr_ratio_20_240', 0), members)} "
            f"| {_share(missing.get('short', 0), members)} "
            f"| {_share(missing.get('suspended', 0), members)} "
            f"| {_share(missing.get('price', 0), members)} "
            f"| {_share(missing.get('f240_zero', 0), members)}（{missing.get('f240_zero', 0):,} 檔次） |"
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
        f"# {name} {segment}（round15_research 第 {VERSION} 版，#{DESIGN}）",
        "",
    ]
    if name == "P2":
        lines += [OVERLAP_NOTE["P2_survivor"], ""]
    lines += [
        f"- 判定：**{verdict}**"
        + (f"（{REASONS[result['reason']]}）" if result["reason"] else ""),
        f"- 假設：{spec['direction']}；{spec['label']}；N＝{spec['top']}、{_hold_text(spec['hold'])}",
        f"- 登記 commit `{REGISTRATION_COMMIT}`；{DECISION}；"
        f"定義雜湊 `{header['definitions_sha256'][:16]}…`",
        f"- 期間：訊號日 {window.get('first_signal', '—')} 起，有淨值的交易日"
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


def _yearly_lines(title: str, note: str, summary: dict[str, Any], fmt) -> list[str]:
    return [
        title,
        "",
        note + "。",
        "",
        f"全段平均：{fmt(summary['mean'])}（{summary['days']:,} 個訊號日）。",
        "",
        "| 年 | 訊號日 | 平均 |",
        "| --- | ---: | ---: |",
        *(
            f"| {year} | {row['days']:,} | {fmt(row['mean'])} |"
            for year, row in summary["years"].items()
        ),
        "",
    ]


def _excess_line(label: str, e: dict[str, Any]) -> str:
    return (
        f"| {label} | {e['days']} | {_pct(e['mean'], 3)} "
        f"| {_pct(e['annual'])} | {_t(e['t'])} |"
    )


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
        ]
        if "reference" in e:
            lines.append(_excess_line("超額（對對照基準，只列出）", e["reference"]))
        if result.get("window_excess"):
            lines.append(
                _excess_line(
                    "超額（對母體，只算窗口日，只列出）", result["window_excess"]
                )
            )
        lines += [
            f"| 絕對報酬（扣成本，判定） | {a['days']} | {_pct(a['mean'], 3)} "
            f"| {_pct(None if a['mean'] is None else a['mean'] * pr.TRADING_DAYS)} | — |",
            "",
            f"門檻：t ≥ {threshold(result.get('min_t', MIN_T))}。",
            "",
        ]
        if "reference" in e:
            lines += [OVERLAP_NOTE["P2_reference"] + "。", ""]
        if result.get("window_excess"):
            lines += [OVERLAP_NOTE["P1_window"] + "。", ""]
        lines += [
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
            "## 每個窗口（P1 第 8 點，只列出、不判定）",
            "",
            f"窗口內的交易日共 {result['window_days']:,} 日（{WINDOW_DAYS}）。",
            "",
            "| 買進日 | 對應的季 | 賣出日 | 母體檔次 | 有值的檔數 | 名單檔數 | 窗口內的交易日 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: |",
            *(
                f"| {w['signal_date']} | {w['quarter']} | {w['sale_date'] or '—'} | {w['members']:,} "
                f"| {w['valued']:,} | {w['names']:,} | {w['days']:,} |"
                for w in result["windows"]
            ),
            "",
        ]
    if name == "P1" and "excess" in result:
        found = result.get("industries")
        lines += ["## 名單的產業分布（P1 第 8 點，只列出、不判定）", ""]
        if not found:
            lines += [f"成員表到 {ms.MEMBERS_LAST}，本段的窗口在那之後，不列。", ""]
        else:
            lines += [
                f"{found['windows']} 個窗口、{found['names']:,} 個名單檔次（一檔屬於多個產業時各算一次；"
                f"成員表到 {ms.MEMBERS_LAST}，之後的窗口不列）。",
                "",
                "| 產業 | 檔次 | 比例 |",
                "| --- | ---: | ---: |",
                *(
                    f"| {label} | {count:,} | {_share(count, found['names'])} |"
                    for label, count in found["counts"].items()
                ),
                "",
            ]
    for key, title, fmt in (
        ("P2_K2", "## 和 K2 的重疊（P2 第 8 點）", lambda v: _pct(v, 1)),
        ("P2_X4", "## 和 X4 的重疊（P2 第 8 點）", lambda v: _pct(v, 1)),
        ("P3_Z4", "## 和 Z4 的重疊（P3 第 7 點）", lambda v: _pct(v, 1)),
    ):
        if key in result.get("overlap", {}):
            lines += _yearly_lines(
                title, OVERLAP_NOTE[key], result["overlap"][key], fmt
            )
    if result.get("overnight"):
        lines += _yearly_lines(
            "## 名單的平均 `overnight_20`（P3 第 7 點，只列出、不判定）",
            "每天名單中有值的檔的 `overnight_20`（`round8_research.overnight_20`）平均",
            result["overnight"],
            lambda v: lib.num(v, 4),
        )
    if result.get("rebalances"):
        lines += [
            "## 每次調倉（P2 第 8 點，只列出、不判定）",
            "",
            "名單檔數是取前 20 名之後；投入比例是買進那天收盤時，部位占淨值的比例。",
            "",
            "| 事件日 | 對應的季 | 母體檔次 | 符合 `margins_up` | 名單檔數 | 投入比例 | 和 K2 的重疊 | 和 X4 的重疊 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            *(
                f"| {e['signal_date']} | {e['quarter']} | {e['members']:,} | {e['hits']:,} "
                f"| {e['names']:,} | {_pct(e.get('invested'), 1)} | {_pct(e['k2_overlap'], 1)} "
                f"| {_pct(e['x4_overlap'], 1)} |"
                for e in result["rebalances"]
            ),
            "",
        ]
        invested = [
            e["invested"] for e in result["rebalances"] if e.get("invested") is not None
        ]
        names = [e["names"] for e in result["rebalances"]]
        lines += [
            f"平均每次調倉 {lib.num(statistics.fmean(names), 1)} 檔、平均投入比例 "
            f"{_pct(statistics.fmean(invested) if invested else None, 1)}。",
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
    """The overview's row: the engine's excess and the listed parts."""

    row = {"engine": result["engine"], **r5._row(result)}
    for key, part in (result.get("overlap") or {}).items():
        row[f"overlap_{key.split('_')[1].lower()}"] = {
            k: part[k] for k in ("days", "mean")
        }
    if result.get("overnight"):
        row["overnight_20"] = {k: result["overnight"][k] for k in ("days", "mean")}
    if "reference" in (result.get("excess") or {}):
        row["reference_excess"] = result["excess"]["reference"]
    if "window_excess" in result:
        row["window_excess"] = result["window_excess"]
        row["windows"] = len(result["windows"])
        row["window_days"] = result["window_days"]
    if result.get("rebalances"):
        row["names"] = statistics.fmean(e["names"] for e in result["rebalances"])
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
        f"# 新策略探索 第 {report['round']} 輪 {stage}（round15_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「第十五輪：P1～P3」）：{DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        _threshold_line(segment, report["min_t"]),
        "- 引擎：P1、P2 是 X7 的事件日帳戶（`explore_research.simulate_events`，P1 窗口之間兩邊都留現金），"
        "P3 是組合引擎（`portfolio_research.simulate`，K＝20）；日數是有淨值的交易日",
        OVERLAP_NOTE["P2_survivor"],
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
        if row.get("window_excess"):
            e = row["window_excess"]
            listed.append(
                f"- {name} 只算窗口日的超額：日均 {_pct(e['mean'], 3)}、t {_t(e['t'])}"
                f"（{row['windows']} 個窗口、{row['window_days']:,} 日）"
            )
        if row.get("names") is not None:
            listed.append(
                f"- {name} 每次調倉的名單檔數：平均 {lib.num(row['names'], 1)}"
            )
        for key, label in (
            ("overlap_k2", "K2"),
            ("overlap_x4", "X4"),
            ("overlap_z4", "Z4"),
        ):
            part = row.get(key)
            if part:
                listed.append(
                    f"- {name} 和 {label} 的重疊：平均 {_pct(part['mean'], 1)}（{part['days']:,} 個訊號日）"
                )
        if row.get("overnight_20"):
            part = row["overnight_20"]
            listed.append(
                f"- {name} 名單的平均 `overnight_20`：{lib.num(part['mean'], 4)}"
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
    "- 缺值比例的分母是母體檔次（每個訊號日的母體加總）；每個訊號日都數；不跑模擬、不算報酬",
    f"- P1：{DEGENERATE['P1']}。每個窗口一列；窗口內的交易日是買進日的 T+1 到賣出日（段內）",
    f"- P2：{DEGENERATE['P2']}。每個事件日一列，不符合的原因依序判（最新一季、格式、欄位缺、營收、比較），"
    "每檔只算第一個；「母體裡的下市、轉板股」是 `status` 為 `delisted`／`transferred` 的母體檔次，"
    "「其中缺所需欄位」是對照基準去掉的檔次；`k2_order`、`x4_order` 是同一個 T 算 K2、X4 名單的時間，"
    "`--coverage-only` 不算重疊比例，各段的 `summary.md` 才列",
    f"- P3：{DEGENERATE['P3']}。`z4_order` 是同一個 T 算 Z4 名單的時間，"
    "`--coverage-only` 不算重疊比例與平均 `overnight_20`，各段的 `summary.md` 才列",
    "- 各假設用自己的訊號日（起日寫在各段標題）",
)


def columns_lines(columns: dict[str, Any]) -> list[str]:
    lines = [
        "| 季 | `report_format` | 列數 | "
        + " | ".join(f"`{n}`" for n in (REVENUE, *GROSS, OPERATING, NET))
        + " |",
        "| --- | --- | ---: | " + " | ".join("---:" for _ in range(5)) + " |",
    ]
    for quarter, kinds in columns.items():
        for kind, part in kinds.items():
            lines.append(
                f"| {quarter} | {kind} | {part['rows']:,} | "
                + " | ".join(
                    f"{part['fields'].get(n, 0):,}"
                    for n in (REVENUE, *GROSS, OPERATING, NET)
                )
                + " |"
            )
    lines.append("")
    for quarter, kinds in columns.items():
        for kind, part in kinds.items():
            lines.append(f"- {quarter} `{kind}` 的欄名：" + "、".join(part["columns"]))
    return lines


def coverage_markdown(body: dict[str, Any]) -> str:
    load_seconds = body.get("load_seconds_parts", {})
    lines = [
        f"# 新策略探索 第 {body['round']} 輪 P1～P3 資料覆蓋（探索段，不含報酬）",
        "",
        f"- round15_research 第 {VERSION} 版；定義雜湊 `{body['definitions_sha256']}`",
        f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}，"
        f"alembic `{body['copy']['alembic']}`",
        f"- 重現：`{body['command']}`",
        f"- 耗時 {body.get('elapsed_seconds', 0):.0f} 秒（載入 {body.get('load_seconds', 0):.0f} 秒，"
        f"其中 panel {load_seconds.get('panel', 0):.0f} 秒、季報其他欄位與標的狀態 "
        f"{load_seconds.get('statements', 0):.0f} 秒、成員表 {load_seconds.get('members', 0):.0f} 秒；"
        f"2013 年的欄名 {body.get('columns_seconds', 0):.0f} 秒），"
        f"峰值記憶體 {lib.num(body.get('peak_memory_gb'), 2)} GB，"
        f"日線 {body.get('bars', 0):,} 根",
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
            f"## {name}（訊號日 {window.get('first_signal', '—')} 起，{window.get('days', 0)} 日）",
            "",
            *coverage_lines(name, row["coverage"]),
            "",
        ]
    if body.get("columns_2013"):
        lines += [
            "## P2：2013 年各季的欄名（`fundamental_snapshots.data_json`，期末在 2013 年的列）",
            "",
            *columns_lines(body["columns_2013"]),
            "",
        ]
    lines += [
        "有明顯斷點，或缺值比例有異常的年份或欄位，或 2013 年的欄名讀不到四個欄位，"
        "或 P1 有窗口一檔都沒有值時，先在工具單提問、不跑探索段。",
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
        "engines": {
            "portfolio_research": "simulate",
            "explore_research": "simulate_events",
        },
        "tool_commit": ex.tool_commit(),
        "command": command,
        "copy": pr.copy_facts(db),
        "read_until": read_until.isoformat(),
        "members_sha256": ms.MEMBERS_SHA256,
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
    members: Path,
    command: str = "",
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, Any]:
    """``--coverage-only``: counts of the exploration, no return."""

    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    end = SEGMENTS[EXPLORATION][1]
    ctx = load(db, members, LOAD_FROM, end, out / RAW_DIR_NAME)
    loaded = time.monotonic() - started
    progress(f"loaded ({loaded:.1f}s)")
    header = _header(db, EXPLORATION, command, end)
    hypotheses = {}
    for name in HYPOTHESES:
        result = run_portfolio(ctx, db, name, EXPLORATION, coverage_only=True)
        row = {
            "window": result["window"],
            "coverage": result.get("coverage", {}),
            "seconds": result.get("seconds", {}),
        }
        hypotheses[name] = row
        progress(f"{name} coverage ({row['seconds'].get('plan', 0.0):.1f}s)")
    t0 = time.monotonic()
    columns = columns_2013(db)
    body = {
        **public(header),
        "coverage_only": True,
        "hypotheses": hypotheses,
        "columns_2013": columns,
        "columns_seconds": time.monotonic() - t0,
        "load_seconds": loaded,
        "load_seconds_parts": ctx.load_seconds,
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


def run_exploration(
    db: Path,
    out: Path,
    names: list[str] | tuple[str, ...],
    members: Path,
    command: str = "",
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, Any]:
    """``names`` on the exploration segment; nothing after its end read."""

    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    end = SEGMENTS[EXPLORATION][1]
    ctx = load(db, members, LOAD_FROM, end, out / RAW_DIR_NAME)
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
    ctx = load(db, members, LOAD_FROM, end, out / RAW_DIR_NAME)
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
        used_ctx = load(db, members, LOAD_FROM, SEGMENTS[USED][1], out / RAW_DIR_NAME)
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
    parser = argparse.ArgumentParser(prog="round15_research.py", description=__doc__)
    parser.add_argument(
        "--db", required=True, help="the research DB (/research/stock.db)"
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--segment", required=True, choices=STAGES)
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    parser.add_argument(
        "--members",
        help="the #779 member table (default: research/industry_members/"
        "industry_members_v1.json beside the DB); P1's industries only",
    )
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help="exploration only: counts of dates, members and missing values "
        "and the time of the features, no return",
    )
    parser.add_argument(
        "--hypotheses",
        help="exploration (required, not with --coverage-only): P1, P2, P3 or "
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
    problems = [*er.refusals(db, args.min_free_gb), *ms.members_problems(members)]
    names: list[str] = []
    if args.segment == EXPLORATION and not args.coverage_only:
        chosen, names = ex.exploration_problems(
            db, args.hypotheses, HYPOTHESES, VERSION
        )
        problems = [*problems, *chosen]
    if problems:
        print(json.dumps({"refused": problems}, ensure_ascii=False))
        return 2
    command = "python tools/research/round15_research.py " + " ".join(argv)
    progress = lambda text: print(text, file=sys.stderr, flush=True)  # noqa: E731
    if args.segment == EXPLORATION:
        if args.coverage_only:
            line = run_coverage(db, Path(args.out), members, command, progress=progress)
        else:
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
