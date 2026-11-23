"""Round 16 of the new-strategy exploration: N1～N3 (#994).

docs/spec/evidence.md 第十六輪：N1～N3 and 第十六輪實作釋義: the hypotheses
were registered (commit ``0eade4ce``, #991, decision 7098889427) before anyone
ran a tool on the backfilled history.  Nothing here is a command-line option:
a change of a definition is a new code.

They are not in ``explore_research.HYPOTHESES``, ``trade_research.HYPOTHESES``
nor ``round4_research`` .. ``round15_research``: their ``definitions_sha256``
hash the whole table, so adding them would make the validation refuse the
exploration reports already run.  N1 trades on ``portfolio_research.simulate``
(K 20), N2 and N3 on X7's event-day account (``explore_research.
simulate_events``); the population, the loading (``explore_research.
load_context``), ``explore_judge``, the gate and the ledgers are imported.
The single quarters are ``feature_evidence._quarter_eps``'s difference
(``round15_research.single_quarter``), N2's event days ``round14_research.
quarter_events``, N3's flow ``feature_evidence._flow``, P1's window
excess ``round15_research.window_excess``.  The overlaps take V2
(``round5_research.rank``), Y4 (``round7_research.rank``, the member table),
Z2 (``round8_research.rank``), P2 (``round15_research.margins_up`` on its
own statements), K2 and X4 (``round15_research.k2_names``／``x4_names``) and
J2 (``round12_research.rank_j2``) on the same T, and ``round10_research``'s
``overlap_share``／``overlap_summary``.  New here are only ``st_20`` with the
daily population mean m_s, ``tax_mom`` (with its own reading of
``fundamental_snapshots.data_json``), N3's quarter-end windows, N2's
reference population and the listed numbers.

Each signal date T (after its close, only T's data and before):

- N1: ``st_20`` (the covariance of the 20 returns with their salience
  weights against T's population mean of each day) small first, 20, K 20.
- N2: on the 4 statutory deadlines, ``tax_mom`` (the latest quarter's
  income tax less the same quarter's a year before, over that one's
  revenue) high first, 20, held to the next event day (X7).
- N3: the 11th session back from each quarter's last session, ``trust_flow_60``
  high first, 20, held to the quarter's last close; cash on both sides
  between the windows.

``explore_research.explore_judge`` judges with t ≥ 2 on the exploration and
the fixed Bonferroni t ≥ 3.346 (61 hypotheses) on the validation.  Before the
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
import exit_research as er  # noqa: E402
import explore_research as ex  # noqa: E402
import feature_evidence as features  # noqa: E402
import mainstream_research as ms  # noqa: E402
import portfolio_research as pr  # noqa: E402
import round5_research as r5  # noqa: E402
import round7_research as r7  # noqa: E402
import round8_research as r8  # noqa: E402
import round10_research as r10  # noqa: E402
import round12_research as r12  # noqa: E402
import round14_research as r14  # noqa: E402
import round15_research as r15  # noqa: E402

VERSION = 1
DESIGN = "994"
TOOL = "round16_research"
REGISTRATION_COMMIT = "0eade4ce"
DECISION = "https://github.com/YiCheng0608/stock-lab/issues/991#issuecomment-7098889427"
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
SEGMENTS = dict(ex.SEGMENTS)
MIN_SEGMENT_DAYS = dict(ex.MIN_SEGMENT_DAYS)
MIN_T = ex.MIN_T  # the exploration's t ≥ 2
# docs 第十六輪 門檻: 1 − Φ(z) = 0.025 ÷ 61, z = 3.3461, 3.346 to the 3rd decimal;
# fixed, not computed when run.
VALIDATION_MIN_T = 3.346
ROUND = 16
ROUND_SIZE = 3
# X1～X8, S1～S3, R1～R2, M1～M2, C1～C4, V1～V3, W1～W4, Y1～Y4, Z1～Z4, B1～B3,
# F1～F4, L1～L4, J1～J4, U1～U3, K1～K3, P1～P3, N1～N3
CUMULATIVE = 61
# Every segment reads the copy from its start, as round10_research ..
# round15_research: N1 reads 21 bars and the population of each, N3 80.
LOAD_FROM = ex.LOAD_FROM
LOAD_RULE = "every segment from LOAD_FROM"
MIN_LOTS = lib.DEFAULT_MIN_LOTS
RAW_DIR_NAME = ex.RAW_DIR_NAME
POPULATION = pr.POPULATION
TAIEX = pr.TAIEX
PORTFOLIO = "portfolio"
EVENTS = "events"
HIGH, LOW = r5.HIGH, r5.LOW

# 共同 排序與同分
ORDER = (
    "by the feature, missing last, ties by sha256(<T>:<instrument_id>); "
    "N1 small first (round5_research.order_key), N2 and N3 high first "
    "(portfolio_research.ranking_key)"
)
SHORT_RULE = "cash, not filled"
SINGLE_QUARTER = (
    "feature_evidence._quarter_eps's difference (round15_research."
    "single_quarter): Q1 the cumulative figure, Q2～Q4 the cumulative less "
    "the quarter before's of the same year"
)

# N1 (第 1～5 點)
RETURNS = 20  # r_s on at − 19 .. at: 21 closes at − 20 .. at
THETA = 0.1
DELTA = 0.7
MARKET_RULE = (
    "m_s: the equal-weighted mean of the daily returns (close[k] / close[k-1] "
    "- 1, adjusted) of evidence_lib.universe(panel, s, MIN_LOTS)'s members on "
    "session s; counted only when bar k-1 is on the market's session s-1 "
    "(panel.sessions), not suspended, and both closes > 0 (#994 decision "
    "7099966724); no member counted: missing; once per session, the whole "
    "panel before the plan"
)
SALIENCE = "sigma_s = |r_s - m_s| / (|r_s| + |m_s| + THETA)"
RANK_RULE = (
    "k_s = 1..20 by sigma_s from the largest, equal values the earlier date first"
)
WEIGHT_RULE = "omega_s = DELTA ** k_s / (sum of DELTA ** k_s / 20), mean 1"
COVARIANCE_RULE = (
    "st_20 = sum((omega_s - 1) * (r_s - mean r)) / 20 (the population "
    "covariance); 20 equal r_s: 0"
)
ST_MISSING = (
    "at < 20; a suspended bar in at-20..at; a close (at-20..at) missing or "
    "<= 0; an m_s missing: missing, ranked last, not dropped"
)
N1_ANCHOR = date(2007, 12, 3)  # the OTC bars the tools read
V2, Y4, Z2 = "V2", "Y4", "Z2"  # the lists N1 overlaps with

# N2 (第 1～5 點)
REVENUE = "營業收入"
TAX = "所得稅費用（利益）"
REPORT_FORMAT = "general"
FIELDS = ("revenue", "tax")  # TaxStatement's attributes, in that order
LAG = 4  # q against q − 4
REVENUE_MIN = 0.0  # rev(q − 4) ≤ 0: missing
TAX_MOM = (
    "(tax(q) - tax(q-4)) / rev(q-4), single quarters; a negative tax counted as it is"
)
NUMBER_RULE = "worker.sources.parse_number on the data_json cell"
STATEMENT_RULE = (
    "fundamental_snapshots rows with announcement_date <= T (an EPS null row "
    "too); the latest is the largest period_end and must be the deadline's "
    "quarter; a needed row (q, q-4 and the quarters before them for the "
    "single values) missing or a field null is missing; a row of another "
    "report_format is missing"
)
SALE = (
    "one account (X7): bought at T+1's open, sold at the close of the next "
    "event day T' (explore_research.simulate_events), the new list bought at "
    "T'+1's open; the population on the same rule and event days"
)
REFERENCE_STATUSES = ("delisted", "transferred")
REFERENCE_RULE = (
    "T's population less the delisted or transferred instruments missing a "
    "field tax_mom needs on T (a row of q, q-4 of the deadline's quarter or "
    "of the quarters before them not known, or one of the two fields null; "
    "not the stale quarter, the report_format nor rev(q-4) <= 0); the same "
    "account and event days"
)
N2_START = date(2014, 5, 15)
P2, K2, X4 = "P2", "K2", "X4"  # the lists N2 overlaps with

# N3 (第 1～3 點)
QUARTER_MONTHS = (3, 6, 9, 12)
QUARTER_END_RULE = (
    "the last session of a quarter's month in the copy's market calendar "
    "(research_report.market_sessions, dates only, the whole copy); a month "
    "counts only when the calendar has a session after it"
)
WINDOW_SESSIONS = 10  # T + 1 .. the quarter's last session; T the 11th back
WINDOW_RULE = (
    "one account (X7): bought at T+1's open, sold at the close of the "
    "quarter's last session; that day's new list is empty, so both sides "
    "hold cash to the next T+1; a quarter end after the segment: its last "
    "close; the population the same"
)
WINDOW_DAYS = "the sessions from T+1 to the quarter's last session (in the segment)"
TRUST_COLUMNS = ("trust_buy",)
TRUST_WINDOW = 60
TRUST_FLOW_60 = features._flow(TRUST_COLUMNS, TRUST_WINDOW)
TRUST_MISSING = (
    "feature_evidence._flow: a missing trust_buy on any of the 60 bars, "
    "at < 59, or the mean volume of the 20 bars before T missing or <= 0: "
    "missing, ranked last; <= 0 ranked by its value"
)
N3_ANCHOR = date(2014, 12, 1)  # the OTC institutional table's first day
J2 = "J2"  # the list N3 overlaps with
SPLIT_MONTHS = ((6, 12), (3, 9))  # 第 7 點: the half-year／year ends, the others

# The registration (docs 第十六輪：N1～N3), word for word.  ``start`` as
# ``explore_research``.
HYPOTHESES: dict[str, dict[str, Any]] = {
    "N1": {
        "engine": PORTFOLIO,
        "direction": "投資人注意力：顯著性理論",
        "label": "`st_20`（近 20 根日報酬，以相對當天母體的顯著程度加權後，權重與報酬的共變異數）小者先",
        "rule": "daily",
        "keys": (("st_20", LOW),),
        "short": SHORT_RULE,
        "top": 20,
        "hold": 20,
        "start": ("session", N1_ANCHOR, 1 + RETURNS),
    },
    "N2": {
        "engine": EVENTS,
        "direction": "基本面：稅費動能",
        "label": "每季法定期限的事件日，`tax_mom`（最新一季單季所得稅費用減去年同季，除以去年同季單季營收）"
        "大者先取 20 檔",
        "rule": "quarterly",
        "keys": (("tax_mom", HIGH),),
        "short": SHORT_RULE,
        "top": 20,
        "hold": "next_event",
        "start": ("date", N2_START),
    },
    "N3": {
        "engine": EVENTS,
        "direction": "事件：投信季底作帳",
        "label": "每季最後一個交易日往前 10 個交易日的窗口，窗口前一天 T 依 `trust_flow_60`"
        "（近 60 根投信淨買超 ÷ T 之前 20 根平均量）大者先取 20 檔，持有到季底收盤，窗口之間留現金",
        "rule": "quarter_end",
        "keys": (("trust_flow_60", HIGH),),
        "short": SHORT_RULE,
        "top": 20,
        "hold": "quarter_end",
        "start": ("session", N3_ANCHOR, TRUST_WINDOW),
    },
}
OTHER_COMPARISONS = ex.OTHER_COMPARISONS
REASONS = dict(ex.REASONS)
LIMITS = {
    "N1": "定義照論文摘要與二手整理，未讀全文；θ、δ 的值與「權重以名次的 δ 次方、正規化到平均 1」來自 BGS 2012 "
    "的寫法與二手整理，市場報酬用當日母體等權、同值以日期早者先；ST 和上個月的報酬相關，低 ST 的名單會偏向近期跌的，"
    "和 V2、Y4（短期反轉）、Z2（偏態）有關，登記時三個的狀態已知，看重疊比例",
    "N2": "定義照論文摘要與二手整理，未讀全文，分母和文獻可能不同；存活者偏差：下市股的季報是 XBRL 整包補的，"
    "只寫了 EPS，沒有這兩個欄位，期間內下市公司的季幾乎都缺值、排最後，偏差方向對假設有利，大小同 P2；"
    "金融業等格式與法定期限不同的公司不會有值；和 P2 同一張表、同一份存活者偏差，欄位不同，登記時 P2 的狀態已知，"
    "看重疊比例",
    "N3": "和 J2 同用投信買賣超，J2 是每天、`turnover_60` 前 150 名以外、`trust_flow_20` > 0、持有 20 日，"
    "N3 只在季底窗口、全母體、60 根累計，登記時 J2 的狀態已知，看重疊比例；窗口 10 個交易日是依台股慣例事先定的；"
    "`trust_flow_60` 任一根缺就缺值，中小型股缺值的比例可能高；探索段只有 20 個窗口，檢定力低；"
    "窗口之間兩邊都是現金，全段的超額平均約是窗口內的 p 倍、標準差約 √p 倍，t 約等於只用窗口內的日子算；"
    "探索段 `trust_flow_60` 的缺值比例跟窗口的 60 根裡有沒有週六補班日一致：有的 9 個窗口缺值 18.4%～32.7%，"
    "沒有的 11 個 4.0%～17.3%，9 個日期是 2014-12-27、2016-01-30、2016-06-04、2016-09-10、2017-02-18、"
    "2017-06-03、2017-09-30、2018-03-31、2018-12-22；那天官方表只列有法人進出的證券，平常有投信進出、"
    "只是那天沒有的檔會在那個窗口缺值、排最後（#994 只讀查詢 7101963059，只讀日期與檔數、沒讀報酬）；"
    "驗證段（2020Q1～2024Q3）的窗口有沒有碰到週六補班日沒有查",
}
# The degenerate cases as the code judges them (第十六輪實作釋義; PR #913
# review: the docs, coverage.md and summary.md say the same words, a test
# reads the docs' tool section for them).
DEGENERATE = {
    "N1": "at < 20（不足 21 根）、at−20…at 的 21 根中任一根停牌、需要的收盤（at−20…at）缺值或 ≤ 0，"
    "或 20 個 m_s 中任一個缺（那天母體沒有任何一檔在上一個全市場交易日有非停牌日線、且兩根收盤都 > 0）時缺值、排最後、不剔除；"
    "20 個 r_s 全部相同時 `st_20`＝0，照值排序",
    "N2": "最新一季（`announcement_date` ≤ T 的季報列中期末最晚的一季，EPS 是 null 的列也算）不是事件日對應的那一季、"
    "q、q−4 與算單季要用的前一季中任一列的 `report_format` 不是 `general`（`report_format` 是 null 的列算欄位缺）、"
    "任一列不在或 `所得稅費用（利益）`、`營業收入` 任一欄缺，或 rev(q−4) ≤ 0 時缺值、排最後；"
    "tax(q)＝tax(q−4) 時 `tax_mom`＝0，照值排序；有值的不足 20 檔時以缺值的依雜湊補，母體不足 20 檔時餘額留現金",
    "N3": "60 根（at−59…at）中任一根投信缺值、at < 59，或 T 之前 20 根的均量（`feature_evidence._flow` 的分母）"
    "缺值或 ≤ 0 時缺值、排最後；`trust_flow_60` ≤ 0 的檔照值排序，不剔除；母體不足 20 檔時餘額留現金",
}
OVERLAP_NOTE = {
    "N1_V2": 'N1 與 V2（`round5_research` 第 1 版的 `HYPOTHESES["V2"]`，同一個 T 算）每日名單的重疊比例：'
    "|N1 的名單 ∩ V2 的前 20 名| ÷ N1 當天的名單檔數；N1 或 V2 當天沒有名單的日子不計。只列出、不判定",
    "N1_Y4": 'N1 與 Y4（`round7_research` 第 1 版的 `HYPOTHESES["Y4"]`，同一個 T 算）每日名單的重疊比例：'
    "|N1 的名單 ∩ Y4 的前 20 名| ÷ N1 當天的名單檔數；N1 或 Y4 當天沒有名單的日子不計。只列出、不判定",
    "N1_Z2": 'N1 與 Z2（`round8_research` 第 1 版的 `HYPOTHESES["Z2"]`，同一個 T 算）每日名單的重疊比例：'
    "|N1 的名單 ∩ Z2 的前 20 名| ÷ N1 當天的名單檔數；N1 或 Z2 當天沒有名單的日子不計。只列出、不判定",
    "N2_P2": 'N2 與 P2（`round15_research` 第 1 版的 `HYPOTHESES["P2"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|N2 的名單 ∩ P2 的名單| ÷ N2 當天的名單檔數；N2 或 P2 當天沒有名單的事件日不計。只列出、不判定",
    "N2_K2": 'N2 與 K2（`round14_research` 第 1 版的 `HYPOTHESES["K2"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|N2 的名單 ∩ K2 的名單| ÷ N2 當天的名單檔數；N2 或 K2 當天沒有名單的事件日不計。只列出、不判定",
    "N2_X4": 'N2 與 X4（`explore_research` 第 2 版的 `HYPOTHESES["X4"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|N2 的名單 ∩ X4 的前 20 名| ÷ N2 當天的名單檔數；N2 或 X4 當天沒有名單的事件日不計。只列出、不判定",
    "N3_J2": 'N3 與 J2（`round12_research` 第 1 版的 `HYPOTHESES["J2"]`，同一個 T 算）每個窗口訊號日 T 名單的重疊比例：'
    "|N3 的名單 ∩ J2 的前 20 名| ÷ N3 當天的名單檔數；N3 或 J2 當天沒有名單的窗口不計。只列出、不判定",
    "N2_reference": "對照基準：當天母體去掉「缺 `tax_mom` 任一所需欄位（事件日對應的那一季的 q、q−4 "
    "與算單季要用的前一季，任一列不在或兩個欄位任一欄缺；不看是不是最新一季、不看 `report_format`、"
    "不看 rev(q−4) ≤ 0）的 `delisted`／`transferred` 標的」，同一個帳戶規則、同一組事件日；"
    "列 N2 對它的超額與 t，只列出、不判定（判定仍只比母體）",
    "N2_survivor": "- 存活者偏差（N2）：下市股的季報只有 EPS，沒有 `tax_mom` 的兩個欄位，期間內下市公司的季幾乎都缺值、排最後，"
    "偏差方向對假設有利。對照基準（母體去掉當天缺欄位的下市、轉板股）的超額與 t "
    "在 `N2/summary.md`「數字」表的「超額（對對照基準，只列出）」列與 `explore.md` 的「只列出、不判定」",
    "summary_only": "定義照摘要與二手整理，未讀全文",
    "N3_window": "只算窗口日：窗口日是 T+1 到季底日（段內）的交易日，"
    "超額是這些日子的每日組合報酬 − 每日母體報酬；6 月與 12 月窗口、3 月與 9 月窗口另各算一次；只列出、不判定",
}
FEATURE_LABELS = {
    "st_20": "顯著性加權的共變異數",
    "tax_mom": "稅費動能",
    "trust_flow_60": "投信 60 根淨買超 ÷ 均量",
}
PICK_FIELDS = {
    "N1": ("st_20", "momentum_20"),
    "N2": ("quarter", "tax_mom", "tax_q", "tax_q4", "revenue_q4"),
    "N3": ("quarter_end", "trust_flow_60", "trust_flow_20"),
}


def definitions() -> dict[str, Any]:
    return {
        "version": VERSION,
        "design": DESIGN,
        "hypotheses": HYPOTHESES,
        "order": ORDER,
        "short": SHORT_RULE,
        "single_quarter": [SINGLE_QUARTER, features.VERSION],
        "deadlines": [r14.DEADLINES, r14.EVENT_DAY_RULE],  # N2's events
        "features": {
            "st_20": {
                "returns": RETURNS,
                "theta": THETA,
                "delta": DELTA,
                "market": MARKET_RULE,
                "salience": SALIENCE,
                "rank": RANK_RULE,
                "weight": WEIGHT_RULE,
                "covariance": COVARIANCE_RULE,
                "missing": ST_MISSING,
            },
            "tax_mom": {
                "fields": [REVENUE, TAX],
                "attributes": FIELDS,
                "report_format": REPORT_FORMAT,
                "lag": LAG,
                "revenue_min": REVENUE_MIN,
                "formula": TAX_MOM,
                "number": NUMBER_RULE,
                "statements": STATEMENT_RULE,
                "sale": SALE,
                "reference": [REFERENCE_RULE, list(REFERENCE_STATUSES)],
            },
            "trust_flow_60": {
                "months": QUARTER_MONTHS,
                "quarter_end": QUARTER_END_RULE,
                "window_sessions": WINDOW_SESSIONS,
                "window": WINDOW_RULE,
                "window_days": WINDOW_DAYS,
                "columns": list(TRUST_COLUMNS),
                "sessions": TRUST_WINDOW,
                "missing": TRUST_MISSING,
                "split": SPLIT_MONTHS,
            },
            "overlaps": {
                V2: [r5.HYPOTHESES[V2], r5.VERSION, r5.definitions_sha256()],
                Y4: [r7.HYPOTHESES[Y4], r7.VERSION, r7.definitions_sha256()],
                Z2: [r8.HYPOTHESES[Z2], r8.VERSION, r8.definitions_sha256()],
                P2: [r15.HYPOTHESES[P2], r15.VERSION, r15.definitions_sha256()],
                K2: [r14.HYPOTHESES[K2], r14.VERSION, r14.definitions_sha256()],
                X4: [ex.HYPOTHESES[X4], ex.VERSION],
                J2: [r12.HYPOTHESES[J2], r12.VERSION, r12.definitions_sha256()],
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
    N1's returns, θ, δ, m_s, ranks, weights and covariance, N2's fields,
    format, lag, formula and reference, N3's months, window, sale and flow,
    the missing rules, N and K, the order, the overlaps' lists, the segments,
    the costs).  A changed tool needs a new exploration report before a
    validation."""

    text = json.dumps(definitions(), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- reading ----------------------------------------------------------------------


@dataclass(frozen=True)
class TaxStatement:
    """One ``fundamental_snapshots`` row for N2: the year's cumulative
    revenue and income tax (thousands), None when the cell is missing."""

    announced: date
    period_end: date
    report_format: str | None
    revenue: float | None
    tax: float | None


def tax_statement_of(
    announced: str, period_end: str, data: dict[str, Any], parse
) -> TaxStatement:
    def value(name: str) -> float | None:
        return parse(data.get(name)) if name in data else None

    return TaxStatement(
        date.fromisoformat(announced),
        date.fromisoformat(period_end),
        data.get("report_format"),
        value(REVENUE),
        value(TAX),
    )


def _rows(db: Path, end: date):
    con = lib.connect_read_only(db)
    try:
        yield from con.execute(
            "select instrument_id, announcement_date, period_end, data_json "
            "from fundamental_snapshots where announcement_date is not null "
            "and announcement_date <= ? order by announcement_date, period_end",
            (end.isoformat(),),
        )
    finally:
        con.close()


def _data(text: str | None) -> dict[str, Any]:
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def load_tax_statements(
    db: Path, series: dict[int, lib.Series], end: date
) -> dict[int, list[TaxStatement]]:
    """N2: every row with an ``announcement_date`` ≤ ``end`` (none after it
    read), by announcement; ``round15_research.load_statements`` reads P2's
    four fields only, ``evidence_lib`` the rows with an EPS only."""

    from worker.sources import parse_number

    out: dict[int, list[TaxStatement]] = defaultdict(list)
    for instrument_id, announced, period_end, text in _rows(db, end):
        if instrument_id in series:
            out[instrument_id].append(
                tax_statement_of(announced, period_end, _data(text), parse_number)
            )
    return dict(out)


def load_calendar(db: Path) -> list[date]:
    """N3 第 1 點 (QUARTER_END_RULE): the copy's market sessions, dates only,
    to its last; the quarters' last sessions are read from it, so a quarter
    ending after the segment (2024-09-30) still has its own T."""

    con = lib.connect_read_only(db)
    try:
        return lib.research_report().market_sessions(con, LOAD_FROM)
    finally:
        con.close()


def _sign(value: float | None) -> str:
    if value is None:
        return "missing"
    return "positive" if value > 0 else "negative" if value < 0 else "zero"


def columns_2013(db: Path) -> dict[str, Any]:
    """N2 第 9 點 (``--coverage-only``): 2013's column names by quarter and
    report_format, the rows with each field and the signs of the tax."""

    from worker.sources import parse_number

    con = lib.connect_read_only(db)
    out: dict[str, Any] = {}
    try:
        rows = con.execute(
            "select period_end, data_json from fundamental_snapshots "
            "where period_end between '2013-01-01' and '2013-12-31' "
            "order by period_end"
        )
        for period_end, text in rows:
            data = _data(text)
            kind = str(data.get("report_format"))
            quarter = out.setdefault(period_end, {})
            part = quarter.setdefault(
                kind,
                {
                    "rows": 0,
                    "fields": Counter(),
                    "columns": Counter(),
                    "signs": Counter(),
                },
            )
            part["rows"] += 1
            part["columns"].update(data.keys())
            for name in (REVENUE, TAX):
                part["fields"][name] += name in data
            if TAX in data:
                part["signs"][_sign(parse_number(data.get(TAX)))] += 1
    finally:
        con.close()
    return {
        quarter: {
            kind: {
                "rows": part["rows"],
                "fields": dict(part["fields"]),
                "signs": dict(part["signs"]),
                "columns": sorted(part["columns"]),
            }
            for kind, part in sorted(kinds.items())
        }
        for quarter, kinds in sorted(out.items())
    }


def tax_signs(statements: dict[int, list[TaxStatement]]) -> dict[str, Counter]:
    """N2 第 9 點: the sign of the cumulative tax of every ``general`` row by
    the year of its quarter (does the sign convention hold across years)."""

    out: dict[str, Counter] = defaultdict(Counter)
    for rows in statements.values():
        for row in rows:
            if row.report_format == REPORT_FORMAT:
                out[str(row.period_end.year)][_sign(row.tax)] += 1
    return {year: dict(counts) for year, counts in sorted(out.items())}


@dataclass
class Context:
    """``explore_research``'s context (the market, the quotes, the turnovers),
    N2's statements and P2's (``round15_research.load_statements``), the
    instruments' status, the member table (Y4), the market calendar (N3) and
    the contexts ``round5_research``, ``round7_research`` and
    ``round8_research`` rank V2, Y4 and Z2 with (the same base).  One panel."""

    base: ex.Context
    statements: dict[int, list[TaxStatement]] = field(default_factory=dict)
    p2_statements: dict[int, list[r15.Statement]] = field(default_factory=dict)
    statuses: dict[int, str] = field(default_factory=dict)
    groups: ms.Context | None = None
    calendar: list[date] = field(default_factory=list)
    v2: r5.Context | None = None
    y4: r7.Context | None = None
    z2: r8.Context | None = None
    p2: r15.Context | None = None
    seconds: Counter = field(default_factory=Counter)
    load_seconds: dict[str, float] = field(default_factory=dict)
    market_mean: list[float | None] | None = None  # N1: m_s by session
    market_excluded: Counter = field(default_factory=Counter)  # N1: by year

    def __post_init__(self) -> None:
        if self.v2 is None:
            self.v2 = r5.Context(self.base)
        if self.y4 is None:
            self.y4 = r7.Context(self.base, self.groups)
        if self.z2 is None:
            self.z2 = r8.Context(self.base)
        if self.p2 is None:
            self.p2 = r15.Context(self.base, self.p2_statements, z4=self.z2)

    @property
    def market(self) -> pr.Market:
        return self.base.market

    @property
    def panel(self) -> lib.Panel:
        return self.base.market.panel

    def quote(self, instrument_id: int, s: int) -> pr.Quote | None:
        return self.base.quote(instrument_id, s)


def load(db: Path, members: Path, start: date, end: date, raw_dir: Path) -> Context:
    """The panel, the turnovers, the EPS quarters, N2's and P2's statements,
    the statuses, the member snapshots to ``end`` and the market calendar
    (dates only); nothing else after ``end`` is read."""

    started = time.monotonic()
    base = ex.load_context(db, start, end, raw_dir)
    panel_seconds = time.monotonic() - started
    t0 = time.monotonic()
    series = base.market.panel.series
    statements = load_tax_statements(db, series, end)
    p2_statements = r15.load_statements(db, series, end)
    statuses = r15.load_statuses(db)
    statement_seconds = time.monotonic() - t0
    t0 = time.monotonic()
    groups = ms.build_context(base.market, ms.read_members(members, end))
    member_seconds = time.monotonic() - t0
    t0 = time.monotonic()
    calendar = load_calendar(db)
    return Context(
        base,
        statements,
        p2_statements,
        statuses,
        groups,
        calendar,
        load_seconds={
            "panel": panel_seconds,
            "statements": statement_seconds,
            "members": member_seconds,
            "calendar": time.monotonic() - t0,
        },
    )


# --- N1: st_20 --------------------------------------------------------------------


def daily_return(item: lib.Series, at: int) -> float | None:
    """The bar's adjusted return over the market's session before (#994 決定
    7099966724): None when the item has no bar on the session before (bar
    ``at − 1`` is not on session ``item.session[at] − 1``), that bar is
    suspended or a close is missing or ≤ 0."""

    if at < 1 or item.session[at - 1] != item.session[at] - 1:
        return None
    if item.is_suspended(at - 1):
        return None
    before, now = item.close[at - 1], item.close[at]
    if not (before > 0 and now > 0):  # NaN fails too
        return None
    return now / before - 1.0


def market_means(
    panel: lib.Panel, last: int, excluded: Counter | None = None
) -> list[float | None]:
    """N1 第 1 點, 第十六輪實作釋義 (MARKET_RULE): m_s of every session
    0 .. ``last``, the equal-weighted mean of the day's population members
    with a return; computed once for the whole panel.  ``excluded`` counts
    the members left out by year (``--coverage-only``)."""

    out: list[float | None] = []
    for s in range(min(last + 1, len(panel.sessions))):
        members = lib.universe(panel, panel.sessions[s], MIN_LOTS)
        values = [
            value
            for item, at in members
            if (value := daily_return(item, at)) is not None
        ]
        if excluded is not None:
            excluded[str(panel.sessions[s].year)] += len(members) - len(values)
        out.append(math.fsum(values) / len(values) if values else None)
    return out


@dataclass(frozen=True)
class Salience:
    value: float | None
    reason: str | None = None  # "short", "suspended", "price", "market"


def _weights() -> list[float]:
    """ω by rank 1..20: δ^k over the mean of δ^1 .. δ^20."""

    powers = [DELTA**k for k in range(1, RETURNS + 1)]
    mean = math.fsum(powers) / RETURNS
    return [p / mean for p in powers]


def st_20(item: lib.Series, at: int, means: list[float | None]) -> Salience:
    """N1 第 1～4 點 on the item's bar ``at`` (T): its own 20 returns, each
    day's m_s (``means`` by session), σ_s, the ranks, ω_s and the covariance."""

    first = at - RETURNS
    if first < 0:
        return Salience(None, "short")
    if item.suspended[at + 1] != item.suspended[first]:
        return Salience(None, "suspended")
    closes = item.close[first : at + 1]
    if not all(close > 0 for close in closes):  # NaN fails too
        return Salience(None, "price")
    returns, market = [], []
    for k in range(1, RETURNS + 1):
        s = item.session[first + k]
        m = means[s] if 0 <= s < len(means) else None
        if m is None:
            return Salience(None, "market")
        returns.append(closes[k] / closes[k - 1] - 1.0)
        market.append(m)
    if max(returns) == min(returns):
        return Salience(0.0)
    sigma = [abs(r - m) / (abs(r) + abs(m) + THETA) for r, m in zip(returns, market)]
    order = sorted(range(RETURNS), key=lambda k: (-sigma[k], k))  # earlier first
    weights = _weights()
    omega = [0.0] * RETURNS
    for rank, k in enumerate(order):
        omega[k] = weights[rank]
    mean = math.fsum(returns) / RETURNS
    return Salience(
        math.fsum((w - 1.0) * (r - mean) for w, r in zip(omega, returns)) / RETURNS
    )


# --- N2: tax_mom ------------------------------------------------------------------


_known = r15._known
_quarter_before = r15._quarter_before
_quarter_back = r15._quarter_back
single_quarter = r15.single_quarter


def _needed(quarter: date) -> list[date]:
    """q, q − 4 and the quarter before each (not before a Q1)."""

    out = []
    for lag in (0, LAG):
        end = _quarter_back(quarter, lag)
        out.append(end)
        if end.month != 3:
            out.append(_quarter_before(end))
    return list(dict.fromkeys(out))


def _singles(known: dict[date, TaxStatement], quarter: date):
    """(revenue, tax) single quarters of q and q − 4, or None when one is missing."""

    out = []
    for name in FIELDS:
        cumulative = {
            end: getattr(row, name)
            for end, row in known.items()
            if getattr(row, name) is not None
        }
        values = [
            single_quarter(cumulative, _quarter_back(quarter, lag)) for lag in (0, LAG)
        ]
        if any(value is None for value in values):
            return None
        out.append(values)
    return out


@dataclass(frozen=True)
class TaxMomentum:
    value: float | None
    # "stale", "format", "fields", "revenue" or None
    reason: str | None = None
    tax_q: float | None = None
    tax_q4: float | None = None
    revenue_q4: float | None = None


def tax_mom(ctx: Context, item: lib.Series, day: date, quarter: date) -> TaxMomentum:
    """N2 第 1～4 點 on T (``day``) for the deadline's ``quarter``."""

    known = _known(ctx.statements.get(item.instrument_id, []), day)
    if not known or max(known) != quarter:
        return TaxMomentum(None, "stale")
    rows = [known.get(end) for end in _needed(quarter)]
    if any(
        row is not None
        and row.report_format is not None
        and row.report_format != REPORT_FORMAT
        for row in rows
    ):
        return TaxMomentum(None, "format")
    if any(
        row is None
        or row.report_format != REPORT_FORMAT
        or any(getattr(row, name) is None for name in FIELDS)
        for row in rows
    ):
        return TaxMomentum(None, "fields")
    singles = _singles(known, quarter)
    if singles is None:
        return TaxMomentum(None, "fields")
    (_revenue_q, revenue_q4), (tax_q, tax_q4) = singles
    if revenue_q4 <= REVENUE_MIN:
        return TaxMomentum(None, "revenue", tax_q, tax_q4, revenue_q4)
    return TaxMomentum((tax_q - tax_q4) / revenue_q4, None, tax_q, tax_q4, revenue_q4)


def fields_missing(ctx: Context, item: lib.Series, day: date, quarter: date) -> bool:
    """N2 第 3 點 second case on the deadline's ``quarter`` (the reference's
    rule, 第十六輪實作釋義): a needed row not known on T or a field missing."""

    known = _known(ctx.statements.get(item.instrument_id, []), day)
    for end in _needed(quarter):
        row = known.get(end)
        if row is None or any(getattr(row, name) is None for name in FIELDS):
            return True
    return _singles(known, quarter) is None


# --- N3: the quarter-end windows --------------------------------------------------


def quarter_ends(calendar: list[date]) -> list[date]:
    """N3 第 1 點 (QUARTER_END_RULE): the last session of each month in
    ``QUARTER_MONTHS``, when the calendar has a session after that month."""

    out = []
    for at, day in enumerate(calendar):
        if day.month not in QUARTER_MONTHS:
            continue
        following = calendar[at + 1] if at + 1 < len(calendar) else None
        if following is not None and (following.year, following.month) != (
            day.year,
            day.month,
        ):
            out.append(day)
    return out


@dataclass(frozen=True)
class Window:
    signal: int  # T's index in the panel's sessions
    due: int | None  # the quarter end's index there, None after the panel
    quarter_end: date


def windows_of(calendar: list[date], sessions: list[date]) -> list[Window]:
    """N3 第 1 點: per quarter end, T is the 11th session back counting the
    quarter end as the 1st (``WINDOW_SESSIONS`` + 1); T+1 .. the quarter end
    are 10 sessions.  Counted on the calendar; a T not in the panel is no
    window (the panel reads to the segment's last day only)."""

    index = {day: at for at, day in enumerate(sessions)}
    position = {day: at for at, day in enumerate(calendar)}
    out = []
    for end in quarter_ends(calendar):
        back = position[end] - WINDOW_SESSIONS
        if back < 0:
            continue
        signal = index.get(calendar[back])
        if signal is None:
            continue
        out.append(Window(signal, index.get(end), end))
    return out


def trust_flow_60(item: lib.Series, at: int) -> float | None:
    """N3 第 3 點: ``feature_evidence._flow(("trust_buy",), 60)``; a missing
    trust on any of the 60 bars or a missing mean volume is missing."""

    if "trust_buy" not in item.chips:
        return None
    value = TRUST_FLOW_60(item, at)
    return None if value is None or value != value else float(value)


# --- the plans --------------------------------------------------------------------


def segment_window(
    sessions: list[date], segment: str, spec: dict[str, Any], calendar=None
) -> tuple[int, int] | None:
    """(first, last) index of the sessions with an equity value, or None.
    N2's equity starts the session after its first event day in the segment
    (as X7's); N3's on the exploration after its first window's T, on the
    later segments from the segment's first session (第十六輪實作釋義)."""

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
        events = [at for at, _q in r14.quarter_events(sessions)]
    elif spec["rule"] == "quarter_end" and first_day is None:
        events = [w.signal for w in windows_of(calendar or sessions, sessions)]
    if events is not None:
        found = [at for at in events if at >= base]
        if not found:
            return None
        base = found[0]
    first = base + 1
    return (first, last) if first <= last else None


@dataclass
class Plan:
    picks: dict[int, list[int]] = field(default_factory=dict)
    population: dict[int, list[int]] = field(default_factory=dict)
    reference: dict[int, list[int]] = field(default_factory=dict)  # N2
    dues: dict[int, int] = field(default_factory=dict)  # N2, N3
    rows: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    signal_days: int = 0
    event_days: int = 0
    overlap: dict[str, dict[str, list[float]]] = field(default_factory=dict)
    momentum: dict[str, list[float]] = field(default_factory=dict)  # N1
    trust20: dict[str, list[float]] = field(default_factory=dict)  # N3
    windows: list[dict[str, Any]] = field(default_factory=list)  # N3
    rebalances: list[dict[str, Any]] = field(default_factory=list)  # N2


_year = r15._year
_add = r15._add
_pick_row = r15._pick_row


def v2_names(
    ctx: Context, day: date, members: list[tuple[lib.Series, int]]
) -> set[int]:
    """V2's list on ``day`` (``round5_research`` 第 1 版的定義, not rewritten)."""

    t0 = time.perf_counter()
    spec = r5.HYPOTHESES[V2]
    rows = r5.rank(ctx.v2, spec, day, members).rows
    ctx.seconds["v2_order"] += time.perf_counter() - t0
    return {row[0] for row in rows[: spec["top"]]}


def y4_names(
    ctx: Context, day: date, members: list[tuple[lib.Series, int]]
) -> set[int]:
    """Y4's list on ``day`` (``round7_research`` 第 1 版的定義, not rewritten)."""

    t0 = time.perf_counter()
    spec = r7.HYPOTHESES[Y4]
    rows = r7.rank(ctx.y4, spec, day, members).rows
    ctx.seconds["y4_order"] += time.perf_counter() - t0
    return {row[0] for row in rows[: spec["top"]]}


def z2_names(
    ctx: Context, day: date, members: list[tuple[lib.Series, int]]
) -> set[int]:
    """Z2's list on ``day`` (``round8_research`` 第 1 版的定義, not rewritten)."""

    t0 = time.perf_counter()
    spec = r8.HYPOTHESES[Z2]
    rows = r8.rank(ctx.z2, spec, day, members).rows
    ctx.seconds["z2_order"] += time.perf_counter() - t0
    return {row[0] for row in rows[: spec["top"]]}


def _means(ctx: Context, last: int) -> list[float | None]:
    """m_s to ``last``, once per panel (MARKET_RULE)."""

    if ctx.market_mean is None or len(ctx.market_mean) < min(
        last + 1, len(ctx.panel.sessions)
    ):
        t0 = time.perf_counter()
        ctx.market_excluded = Counter()
        ctx.market_mean = market_means(ctx.panel, last, ctx.market_excluded)
        ctx.seconds["m_s"] += time.perf_counter() - t0
    return ctx.market_mean


def plan_n1(
    ctx: Context, spec: dict[str, Any], first: int, last: int, keep_rows=True
) -> Plan:
    """N1 第 1～5、7 點 on the signal dates ``first − 1`` .. ``last − 1``."""

    panel = ctx.panel
    out = Plan(overlap={"N1_V2": {}, "N1_Y4": {}, "N1_Z2": {}})
    top = spec["top"]
    keys = tuple(spec["keys"])
    means = _means(ctx, last)
    market_missing = out.coverage.setdefault("_market", Counter())
    market_days = out.coverage.setdefault("_market_days", Counter())
    for s in range(min(last + 1, len(means))):
        market_days[str(panel.sessions[s].year)] += 1
        if means[s] is None:
            market_missing[str(panel.sessions[s].year)] += 1
    out.coverage["_excluded"] = dict(getattr(ctx, "market_excluded", None) or {})
    for at in range(first - 1, last):
        day = panel.sessions[at]
        members = lib.universe(panel, day, MIN_LOTS)
        year = _year(out.coverage, day, len(members))
        out.signal_days += 1
        t0 = time.perf_counter()
        rows, missing = [], Counter()
        for item, k in members:
            got = st_20(item, k, means)
            if got.value is None:
                missing["st_20"] += 1
                missing[got.reason] += 1
            rows.append((item, k, got, pr.tie_break(day, item.instrument_id)))
        ctx.seconds["st_20"] += time.perf_counter() - t0
        rows.sort(key=lambda row: r5.order_key({"st_20": row[2].value}, keys, row[3]))
        chosen = rows[:top]
        missing_year = year.setdefault("missing", {})
        for key, count in missing.items():
            missing_year[key] = missing_year.get(key, 0) + count
        _add(year, "valued", len(members) - missing["st_20"])
        others = {
            "N1_V2": v2_names(ctx, day, members),
            "N1_Y4": y4_names(ctx, day, members),
            "N1_Z2": z2_names(ctx, day, members),
        }  # timed in the coverage too
        if not keep_rows:
            continue
        names = [item.instrument_id for item, _k, _g, _t in chosen]
        for key, other in others.items():
            share = r10.overlap_share(names, other)
            if share is not None:
                out.overlap[key].setdefault(str(day.year), []).append(share)
        t0 = time.perf_counter()
        moves = [r5.momentum_20(None, item, k) for item, k, _g, _t in chosen]
        ctx.seconds["momentum_20"] += time.perf_counter() - t0
        valued = [v for v in moves if v is not None]
        if valued:
            out.momentum.setdefault(str(day.year), []).append(statistics.fmean(valued))
        out.picks[at + 1] = names
        out.population[at + 1] = [item.instrument_id for item, _ in members]
        for place, ((item, _k, got, tie), move) in enumerate(zip(chosen, moves), 1):
            out.rows.append(
                _pick_row(ctx, day, place, item.instrument_id,
                          {"st_20": got.value, "momentum_20": move}, tie)
            )  # fmt: skip
    return out


def p2_names(
    ctx: Context, day: date, members: list[tuple[lib.Series, int]], quarter: date
) -> set[int]:
    """P2's list on ``day`` (``round15_research`` 第 1 版的定義:
    ``margins_up`` on its own statements, the first 20 by the hash)."""

    t0 = time.perf_counter()
    spec = r15.HYPOTHESES[P2]
    found = sorted(
        (pr.tie_break(day, item.instrument_id), item.instrument_id)
        for item, _k in members
        if r15.margins_up(ctx.p2, item, day, quarter).qualifies
    )
    ctx.seconds["p2_order"] += time.perf_counter() - t0
    return {instrument_id for _t, instrument_id in found[: spec["top"]]}


def k2_names(ctx, day, members, quarter) -> set[int]:
    """K2's list (``round15_research.k2_names``: ``round14_research.eps_turn``)."""

    return r15.k2_names(ctx, day, members, quarter)


def x4_names(ctx, day, members) -> set[int]:
    """X4's list (``round15_research.x4_names``: ``round14_research.x4_names``)."""

    return r15.x4_names(ctx, day, members)


def plan_n2(
    ctx: Context, spec: dict[str, Any], first: int, last: int, keep_rows=True
) -> Plan:
    """N2 第 1～5、7、8 點: the event days of the segment, ``tax_mom`` in T's
    population high first, 20, held to the next event day (X7); the
    reference population on the same days."""

    panel = ctx.panel
    sessions = panel.sessions
    out = Plan(overlap={"N2_P2": {}, "N2_K2": {}, "N2_X4": {}})
    top = spec["top"]
    keys = tuple(name for name, _direction in spec["keys"])
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
        rows, reasons = [], Counter()
        for item, _k in members:
            got = tax_mom(ctx, item, day, quarter)
            reasons[got.reason] += 1
            rows.append((item, got, pr.tie_break(day, item.instrument_id)))
        ctx.seconds["tax_mom"] += time.perf_counter() - t0
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
        rows.sort(key=lambda row: pr.ranking_key({keys[0]: row[1].value}, keys, row[2]))
        chosen = rows[:top]
        event = {
            "signal_date": day.isoformat(),
            "quarter": quarter.isoformat(),
            "members": len(members),
            "valued": reasons[None],
            **{key: reasons[key] for key in ("stale", "format", "fields", "revenue")},
            "names": len(chosen),
            "delisted": gone,
            "delisted_missing": gone_missing,
        }
        for key in ("valued", "delisted", "delisted_missing"):
            _add(year, key, event[key])
        year.setdefault("events", []).append(event)
        others = {
            "N2_P2": p2_names(ctx, day, members, quarter),
            "N2_K2": k2_names(ctx, day, members, quarter),
            "N2_X4": x4_names(ctx, day, members),
        }  # timed in the coverage too
        if not keep_rows:
            continue
        names = [item.instrument_id for item, _g, _t in chosen]
        shares = {}
        for key, other in others.items():
            share = r10.overlap_share(names, other)
            shares[key] = share
            if share is not None:
                out.overlap[key].setdefault(str(day.year), []).append(share)
        out.rebalances.append(
            {**event, "p2_overlap": shares["N2_P2"], "k2_overlap": shares["N2_K2"],
             "x4_overlap": shares["N2_X4"]}
        )  # fmt: skip
        out.picks[at + 1] = names
        out.population[at + 1] = [item.instrument_id for item, _ in members]
        out.reference[at + 1] = [
            item.instrument_id
            for item, _ in members
            if item.instrument_id not in excluded
        ]
        due = following.get(at)
        out.dues[at + 1] = due if due is not None and due <= last else last + 1
        for place, (item, got, tie) in enumerate(chosen, 1):
            out.rows.append(
                _pick_row(
                    ctx, day, place, item.instrument_id,
                    {"quarter": quarter.isoformat(), "tax_mom": got.value, "tax_q": got.tax_q,
                     "tax_q4": got.tax_q4, "revenue_q4": got.revenue_q4},
                    tie,
                )
            )  # fmt: skip
    return out


def j2_names(
    ctx: Context, day: date, members: list[tuple[lib.Series, int]]
) -> set[int]:
    """J2's list on ``day`` (``round12_research`` 第 1 版的定義, not rewritten)."""

    t0 = time.perf_counter()
    spec = r12.HYPOTHESES[J2]
    rows = r12.rank_j2(ctx, spec, day, members).rows
    ctx.seconds["j2_order"] += time.perf_counter() - t0
    return {row[0] for row in rows[: spec["top"]]}


def plan_n3(
    ctx: Context, spec: dict[str, Any], first: int, last: int, keep_rows=True
) -> Plan:
    """N3 第 1～3、7 點: on each window's T of the segment, T's population by
    ``trust_flow_60`` high first, 20, held to the quarter end's close."""

    panel = ctx.panel
    sessions = panel.sessions
    out = Plan(overlap={"N3_J2": {}})
    top = spec["top"]
    keys = tuple(name for name, _direction in spec["keys"])
    for window in windows_of(ctx.calendar or sessions, sessions):
        at = window.signal
        if not first - 1 <= at <= last - 1:
            continue
        day = sessions[at]
        members = lib.universe(panel, day, MIN_LOTS)
        year = _year(out.coverage, day, len(members))
        out.signal_days += 1
        out.event_days += 1
        t0 = time.perf_counter()
        rows = []
        for item, k in members:
            rows.append(
                (item, k, trust_flow_60(item, k), pr.tie_break(day, item.instrument_id))
            )
        ctx.seconds["trust_flow_60"] += time.perf_counter() - t0
        rows.sort(key=lambda row: pr.ranking_key({keys[0]: row[2]}, keys, row[3]))
        chosen = rows[:top]
        due = window.due if window.due is not None and window.due <= last else last + 1
        valued = sum(1 for row in rows if row[2] is not None)
        facts = {
            "signal_date": day.isoformat(),
            "quarter_end": window.quarter_end.isoformat(),
            "members": len(members),
            "valued": valued,
            "missing": len(members) - valued,
            "names": len(chosen),
            "days": min(due, last) - at,
        }
        _add(year, "valued", valued)
        out.coverage.setdefault("windows", []).append(facts)
        other = j2_names(ctx, day, members)  # timed in the coverage too
        if not keep_rows:
            continue
        names = [item.instrument_id for item, _k, _v, _t in chosen]
        share = r10.overlap_share(names, other)
        if share is not None:
            out.overlap["N3_J2"].setdefault(str(day.year), []).append(share)
        t0 = time.perf_counter()
        flows = [r12.trust_flow_20(item, k) for item, k, _v, _t in chosen]
        ctx.seconds["trust_flow_20"] += time.perf_counter() - t0
        present = [v for v in flows if v is not None]
        mean20 = statistics.fmean(present) if present else None
        if mean20 is not None:
            out.trust20.setdefault(str(day.year), []).append(mean20)
        out.windows.append(
            {**facts, "first": at + 1, "last": min(due, last), "j2_overlap": share,
             "trust_flow_20": mean20}
        )  # fmt: skip
        out.picks[at + 1] = names
        out.population[at + 1] = [item.instrument_id for item, _ in members]
        out.dues[at + 1] = due
        for place, ((item, _k, value, tie), flow) in enumerate(zip(chosen, flows), 1):
            out.rows.append(
                _pick_row(ctx, day, place, item.instrument_id,
                          {"quarter_end": window.quarter_end.isoformat(),
                           "trust_flow_60": value, "trust_flow_20": flow}, tie)
            )  # fmt: skip
    return out


def planner(name: str) -> Callable[..., Plan]:
    return {"N1": plan_n1, "N2": plan_n2, "N3": plan_n3}[name]


overlap_share = r10.overlap_share
overlap_summary = r10.overlap_summary
window_excess = r15.window_excess
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
    """(the hypothesis, the population, N2's reference): N2 and N3 X7's
    account, N1 K accounts."""

    spec = HYPOTHESES[name]
    if spec["engine"] == EVENTS:
        mine = ex.simulate_events(
            planned.picks, planned.dues, ctx.quote, first, last, spec["top"]
        )
        population = ex.simulate_events(
            planned.population, planned.dues, ctx.quote, first, last, None
        )
        reference = None
        if name == "N2":
            reference = ex.simulate_events(
                planned.reference, planned.dues, ctx.quote, first, last, None
            )
        return mine, population, reference
    mine = pr.simulate(planned.picks, ctx.quote, first, last, spec["hold"], spec["top"])
    population = pr.simulate(
        planned.population, ctx.quote, first, last, spec["hold"], None
    )
    return mine, population, None


def window_parts(
    windows: list[dict[str, Any]], first: int, differences: list[float]
) -> dict[str, Any]:
    """N3 第 7 點: the excess on the window days, of each window and of the
    6／12 and 3／9 month windows apart (``window_excess`` on each subset)."""

    out = {"all": window_excess(windows, first, differences)}
    for months in SPLIT_MONTHS:
        chosen = [
            w for w in windows if date.fromisoformat(w["quarter_end"]).month in months
        ]
        out["/".join(str(m) for m in months)] = window_excess(
            chosen, first, differences
        )
    for w in windows:
        w["excess"] = window_excess([w], first, differences)
    return out


def run_portfolio(
    ctx: Context,
    db: Path,
    name: str,
    segment: str,
    coverage_only: bool = False,
    min_t: float = MIN_T,
) -> dict[str, Any]:
    """N1, N2 or N3 on one segment: its numbers, verdict and private parts."""

    spec = HYPOTHESES[name]
    sessions = ctx.panel.sessions
    result = _result(name, segment)
    window = segment_window(sessions, segment, spec, getattr(ctx, "calendar", None))
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
    if name == "N1":
        result["momentum_20"] = overlap_summary(planned.momentum)
    if name == "N3":
        result["trust_flow_20"] = overlap_summary(planned.trust20)
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
    if name == "N3":
        parts = window_parts(planned.windows, first, differences)
        for w in planned.windows:
            s = w["first"]
            w["invested"] = mine.invested[s - first] if s <= last else None
            w["population_invested"] = (
                population.invested[s - first] if s <= last else None
            )
        result["windows"] = [
            {key: value for key, value in w.items() if key not in ("first", "last")}
            for w in planned.windows
        ]
        result["window_excess"] = parts["all"]
        result["window_split"] = {k: v for k, v in parts.items() if k != "all"}
        result["window_days"] = sum(w["days"] for w in planned.windows)
    if name == "N2":
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


def _hold_text(hold: Any) -> str:
    return {
        "next_event": "持有到下一個事件日",
        "quarter_end": "持有到季底收盤，窗口之間留現金",
    }.get(hold, f"K＝{hold}")


def coverage_lines(name: str, coverage: dict[str, Any]) -> list[str]:
    """N1 by year, N2 each event day and by year, N3 each window and by year."""

    if name == "N1":
        head = ["年", "日數", "母體檔次", "有 `st_20` 的檔次", "缺值", "（不足 21 根）",
                "（停牌）", "（收盤缺值或 ≤ 0）", "（m_s 缺）", "m_s 缺的天數",
                "不計入 m_s 的檔次（每日平均）"]  # fmt: skip
        lines = [
            "| " + " | ".join(head) + " |",
            "| --- | " + " | ".join("---:" for _ in head[1:]) + " |",
        ]
        market = coverage.get("_market", {})
        market_days = coverage.get("_market_days", {})
        excluded = coverage.get("_excluded", {})
        years = sorted({*(y for y in coverage if not y.startswith("_")), *market_days})
        for year in years:
            row = coverage.get(year, {"days": 0, "members": 0})
            members, missing = row["members"], row.get("missing", {})
            lines.append(
                f"| {year} | {row['days']:,} | {members:,} | {row.get('valued', 0):,} "
                f"| {_share(missing.get('st_20', 0), members)} "
                f"| {_share(missing.get('short', 0), members)} "
                f"| {_share(missing.get('suspended', 0), members)} "
                f"| {_share(missing.get('price', 0), members)} "
                f"| {_share(missing.get('market', 0), members)} "
                f"| {market.get(year, 0):,} "
                f"| {lib.num(excluded.get(year, 0) / market_days[year] if market_days.get(year) else None, 1)} |"
            )
        return lines
    if name == "N2":
        head = ["事件日", "對應的季", "母體檔次", "有 `tax_mom` 的檔數", "名單檔數",
                "最新一季不是對應的那一季", "`report_format` 不是 `general`", "欄位缺",
                "（比例）", "rev(q−4) ≤ 0", "母體裡的下市、轉板股", "（其中缺所需欄位）"]  # fmt: skip
        lines = [
            "| " + " | ".join(head) + " |",
            "| --- | --- | " + " | ".join("---:" for _ in head[2:]) + " |",
        ]
        for _year_, row in sorted(coverage.items()):
            for e in row.get("events", []):
                lines.append(
                    f"| {e['signal_date']} | {e['quarter']} | {e['members']:,} | {e['valued']:,} "
                    f"| {e['names']:,} | {e['stale']:,} | {e['format']:,} | {e['fields']:,} "
                    f"| {_share(e['fields'], e['members'])} | {e['revenue']:,} "
                    f"| {e['delisted']:,} | {e['delisted_missing']:,} |"
                )
        lines += ["", "依年：", "",
                  "| 年 | 事件日 | 母體檔次 | 有 `tax_mom` 的檔次 | 母體裡的下市、轉板股檔次 | 其中缺 `tax_mom` 所需欄位 |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"]  # fmt: skip
        for year, row in sorted(coverage.items()):
            lines.append(
                f"| {year} | {row['days']:,} | {row['members']:,} | {row.get('valued', 0):,} "
                f"| {row.get('delisted', 0):,} | {row.get('delisted_missing', 0):,} |"
            )
        return lines
    head = ["訊號日 T", "季底日", "母體檔次", "有 `trust_flow_60` 的檔數", "缺值",
            "（比例）", "名單檔數", "窗口內的交易日"]  # fmt: skip
    lines = [
        "| " + " | ".join(head) + " |",
        "| --- | --- | " + " | ".join("---:" for _ in head[2:]) + " |",
    ]
    for w in coverage.get("windows", []):
        lines.append(
            f"| {w['signal_date']} | {w['quarter_end']} | {w['members']:,} | {w['valued']:,} "
            f"| {w['missing']:,} | {_share(w['missing'], w['members'])} | {w['names']:,} "
            f"| {w['days']:,} |"
        )
    lines += ["", "依年（各窗口的訊號日 T 加總）：", "",
              "| 年 | 窗口 | 母體檔次 | 有 `trust_flow_60` 的檔次 | 缺值比例 |",
              "| --- | ---: | ---: | ---: | ---: |"]  # fmt: skip
    for year, row in sorted((k, v) for k, v in coverage.items() if k != "windows"):
        lines.append(
            f"| {year} | {row['days']:,} | {row['members']:,} | {row.get('valued', 0):,} "
            f"| {_share(row['members'] - row.get('valued', 0), row['members'])} |"
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
        f"# {name} {segment}（round16_research 第 {VERSION} 版，#{DESIGN}）",
        "",
    ]
    if name == "N2":
        lines += [OVERLAP_NOTE["N2_survivor"], ""]
    if name in ("N1", "N2"):
        lines += [f"- {OVERLAP_NOTE['summary_only']}", ""]
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


def _split_label(key: str) -> str:
    return {"6/12": "6 月與 12 月窗口", "3/9": "3 月與 9 月窗口"}[key]


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
            for key, part in result["window_split"].items():
                lines.append(
                    _excess_line(
                        f"超額（對母體，只算{_split_label(key)}，只列出）", part
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
            lines += [OVERLAP_NOTE["N2_reference"] + "。", ""]
        if result.get("window_excess"):
            lines += [OVERLAP_NOTE["N3_window"] + "。", ""]
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
            "## 每個窗口（N3 第 7 點，只列出、不判定）",
            "",
            f"窗口內的交易日共 {result['window_days']:,} 日（{WINDOW_DAYS}）。"
            "投入比例是 T+1 收盤時部位占淨值的比例；超額與 t 只算這個窗口的日子。",
            "",
            "| 訊號日 T | 季底日 | 母體檔次 | 有值的檔數 | 名單檔數 | 窗口內的交易日 | 投入比例 "
            "| 母體投入比例 | 超額日均 | t | 和 J2 的重疊 | 名單的平均 `trust_flow_20` |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            *(
                f"| {w['signal_date']} | {w['quarter_end']} | {w['members']:,} | {w['valued']:,} "
                f"| {w['names']:,} | {w['days']:,} | {_pct(w.get('invested'), 1)} "
                f"| {_pct(w.get('population_invested'), 1)} | {_pct(w['excess']['mean'], 3)} "
                f"| {_t(w['excess']['t'])} | {_pct(w['j2_overlap'], 1)} "
                f"| {lib.num(w['trust_flow_20'], 4)} |"
                for w in result["windows"]
            ),
            "",
        ]
    for key, title in (
        ("N1_V2", "## 和 V2 的重疊（N1 第 7 點）"),
        ("N1_Y4", "## 和 Y4 的重疊（N1 第 7 點）"),
        ("N1_Z2", "## 和 Z2 的重疊（N1 第 7 點）"),
        ("N2_P2", "## 和 P2 的重疊（N2 第 8 點）"),
        ("N2_K2", "## 和 K2 的重疊（N2 第 8 點）"),
        ("N2_X4", "## 和 X4 的重疊（N2 第 8 點）"),
        ("N3_J2", "## 和 J2 的重疊（N3 第 7 點）"),
    ):
        if key in result.get("overlap", {}):
            lines += _yearly_lines(
                title, OVERLAP_NOTE[key], result["overlap"][key], lambda v: _pct(v, 1)
            )
    if result.get("momentum_20"):
        lines += _yearly_lines(
            "## 名單的平均 `momentum_20`（N1 第 7 點，只列出、不判定）",
            "每天名單中有值的檔的 `momentum_20`（`round5_research.momentum_20`）平均",
            result["momentum_20"],
            lambda v: _pct(v, 2),
        )
    if result.get("trust_flow_20"):
        lines += _yearly_lines(
            "## 名單的平均 `trust_flow_20`（N3 第 7 點，只列出、不判定）",
            "每個窗口的訊號日 T，名單中有值的檔的 `trust_flow_20`（`round12_research.trust_flow_20`）平均",
            result["trust_flow_20"],
            lambda v: lib.num(v, 4),
        )
    if result.get("rebalances"):
        lines += [
            "## 每次調倉（N2 第 8 點，只列出、不判定）",
            "",
            "名單檔數是取前 20 名之後；投入比例是買進那天收盤時，部位占淨值的比例。",
            "",
            "| 事件日 | 對應的季 | 母體檔次 | 有 `tax_mom` | 名單檔數 | 投入比例 | 和 P2 的重疊 "
            "| 和 K2 的重疊 | 和 X4 的重疊 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            *(
                f"| {e['signal_date']} | {e['quarter']} | {e['members']:,} | {e['valued']:,} "
                f"| {e['names']:,} | {_pct(e.get('invested'), 1)} | {_pct(e['p2_overlap'], 1)} "
                f"| {_pct(e['k2_overlap'], 1)} | {_pct(e['x4_overlap'], 1)} |"
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
    for key in ("momentum_20", "trust_flow_20"):
        if result.get(key):
            row[key] = {k: result[key][k] for k in ("days", "mean")}
    if "reference" in (result.get("excess") or {}):
        row["reference_excess"] = result["excess"]["reference"]
    if "window_excess" in result:
        row["window_excess"] = result["window_excess"]
        row["window_split"] = result["window_split"]
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
        f"# 新策略探索 第 {report['round']} 輪 {stage}（round16_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「第十六輪：N1～N3」）：{DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        _threshold_line(segment, report["min_t"]),
        "- 引擎：N1 是組合引擎（`portfolio_research.simulate`，K＝20），N2、N3 是 X7 的事件日帳戶"
        "（`explore_research.simulate_events`，N3 窗口之間兩邊都留現金）；日數是有淨值的交易日",
        f"- N1、N2：{OVERLAP_NOTE['summary_only']}",
        OVERLAP_NOTE["N2_survivor"],
        *(f"- {name} 的限制：{text}" for name, text in LIMITS.items()),
        f"- 副本：最新交易日 {report['copy']['latest']}，alembic `{report['copy']['alembic']}`",
        f"- 讀取的資料到 {report['read_until']}（之後的列不讀；N3 的季底日另讀整份副本的交易日曆，只有日期）",
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
            for key, part in row["window_split"].items():
                listed.append(
                    f"- {name} 只算{_split_label(key)}的超額：日均 {_pct(part['mean'], 3)}、"
                    f"t {_t(part['t'])}（{part['days']:,} 日）"
                )
        if row.get("names") is not None:
            listed.append(
                f"- {name} 每次調倉的名單檔數：平均 {lib.num(row['names'], 1)}"
            )
        for key, label in (
            ("overlap_v2", "V2"),
            ("overlap_y4", "Y4"),
            ("overlap_z2", "Z2"),
            ("overlap_p2", "P2"),
            ("overlap_k2", "K2"),
            ("overlap_x4", "X4"),
            ("overlap_j2", "J2"),
        ):
            part = row.get(key)
            if part:
                listed.append(
                    f"- {name} 和 {label} 的重疊：平均 {_pct(part['mean'], 1)}（{part['days']:,} 個訊號日）"
                )
        if row.get("momentum_20"):
            listed.append(
                f"- {name} 名單的平均 `momentum_20`：{_pct(row['momentum_20']['mean'], 2)}"
            )
        if row.get("trust_flow_20"):
            listed.append(
                f"- {name} 名單的平均 `trust_flow_20`：{lib.num(row['trust_flow_20']['mean'], 4)}"
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
    f"- N1：{DEGENERATE['N1']}。依年一列；m_s 每個交易日只算一次（整段先算好，計時是 `m_s`），"
    "「m_s 缺的天數」是當天母體沒有任何一檔有日報酬的交易日數，「不計入 m_s 的檔次」是當天母體中"
    "上一個全市場交易日沒有非停牌日線或收盤缺值／≤ 0 的檔次的每日平均（panel 到段末的每個交易日都數）；"
    "`v2_order`、`y4_order`、`z2_order` 是同一個 T 算 V2、Y4、Z2 名單的時間，"
    "`--coverage-only` 不算重疊比例與平均 `momentum_20`，各段的 `summary.md` 才列",
    f"- N2：{DEGENERATE['N2']}。每個事件日一列，缺值的原因依序判（最新一季、格式、欄位缺、營收），"
    "每檔只算第一個；「母體裡的下市、轉板股」是 `status` 為 `delisted`／`transferred` 的母體檔次，"
    "「其中缺所需欄位」是對照基準去掉的檔次；`p2_order`、`k2_order`、`x4_order` 是同一個 T 算 P2、K2、X4 名單的時間，"
    "`--coverage-only` 不算重疊比例，各段的 `summary.md` 才列",
    f"- N3：{DEGENERATE['N3']}。每個窗口一列（訊號日 T、季底日、母體檔次、有值的檔數、名單檔數、窗口內的交易日），"
    "另依年加總各窗口的 T；`j2_order` 是同一個 T 算 J2 名單的時間，"
    "`--coverage-only` 不算重疊比例與平均 `trust_flow_20`，各段的 `summary.md` 才列",
    "- 各假設用自己的訊號日（起日寫在各段標題）",
)


def columns_lines(columns: dict[str, Any], signs: dict[str, Any]) -> list[str]:
    lines = [
        "| 季 | `report_format` | 列數 | "
        + " | ".join(f"`{n}`" for n in (REVENUE, TAX))
        + " | 稅費為正 | 為負 | 為 0 | 讀不到數字 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for quarter, kinds in columns.items():
        for kind, part in kinds.items():
            s = part.get("signs", {})
            lines.append(
                f"| {quarter} | {kind} | {part['rows']:,} | "
                + " | ".join(f"{part['fields'].get(n, 0):,}" for n in (REVENUE, TAX))
                + f" | {s.get('positive', 0):,} | {s.get('negative', 0):,} "
                f"| {s.get('zero', 0):,} | {s.get('missing', 0):,} |"
            )
    lines.append("")
    for quarter, kinds in columns.items():
        for kind, part in kinds.items():
            lines.append(f"- {quarter} `{kind}` 的欄名：" + "、".join(part["columns"]))
    lines += [
        "",
        f"`{TAX}` 累計值的正負號，依季的年（`report_format`＝`general`、`announcement_date` 到段末的列）：",
        "",
        "| 年 | 為正 | 為負 | 為 0 | 欄位缺或讀不到數字 |",
        "| --- | ---: | ---: | ---: | ---: |",
        *(
            f"| {year} | {c.get('positive', 0):,} | {c.get('negative', 0):,} "
            f"| {c.get('zero', 0):,} | {c.get('missing', 0):,} |"
            for year, c in signs.items()
        ),
    ]
    return lines


def coverage_markdown(body: dict[str, Any]) -> str:
    load_seconds = body.get("load_seconds_parts", {})
    lines = [
        f"# 新策略探索 第 {body['round']} 輪 N1～N3 資料覆蓋（探索段，不含報酬）",
        "",
        f"- round16_research 第 {VERSION} 版；定義雜湊 `{body['definitions_sha256']}`",
        f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}，"
        f"alembic `{body['copy']['alembic']}`",
        f"- 重現：`{body['command']}`",
        f"- 耗時 {body.get('elapsed_seconds', 0):.0f} 秒（載入 {body.get('load_seconds', 0):.0f} 秒，"
        f"其中 panel {load_seconds.get('panel', 0):.0f} 秒、季報其他欄位（N2 與 P2）與標的狀態 "
        f"{load_seconds.get('statements', 0):.0f} 秒、成員表 {load_seconds.get('members', 0):.0f} 秒、"
        f"交易日曆 {load_seconds.get('calendar', 0):.0f} 秒；"
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
            "## N2：2013 年各季的欄名與稅費的正負號（`fundamental_snapshots.data_json`，期末在 2013 年的列）",
            "",
            *columns_lines(body["columns_2013"], body.get("tax_signs", {})),
            "",
        ]
    lines += [
        "有明顯斷點，或缺值比例有異常的年份或欄位，或 2013 年的欄名讀不到兩個欄位，"
        "或稅費的正負號寫法跨年不一致，或 N3 有窗口的 T 一檔都沒有值時，先在工具單提問、不跑探索段。",
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
        "tax_signs": tax_signs(ctx.statements),
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
    parser = argparse.ArgumentParser(prog="round16_research.py", description=__doc__)
    parser.add_argument(
        "--db", required=True, help="the research DB (/research/stock.db)"
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--segment", required=True, choices=STAGES)
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    parser.add_argument(
        "--members",
        help="the #779 member table (default: research/industry_members/"
        "industry_members_v1.json beside the DB); N1's overlap with Y4 only",
    )
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help="exploration only: counts of dates, members and missing values "
        "and the time of the features, no return",
    )
    parser.add_argument(
        "--hypotheses",
        help="exploration (required, not with --coverage-only): N1, N2, N3 or "
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
    command = "python tools/research/round16_research.py " + " ".join(argv)
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
