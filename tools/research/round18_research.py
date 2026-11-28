"""Round 18 of the new-strategy exploration: G1, G2 (#1029).

docs/spec/evidence.md 第十八輪：G1、G2 and 第十八輪實作釋義: the hypotheses
were registered (commit ``c985ca64``, #1025, decision 7115607959) before
anyone ran a tool on the backfilled history.  Nothing here is a command-line
option: a change of a definition is a new code.

They are not in ``explore_research.HYPOTHESES``, ``trade_research.HYPOTHESES``
nor ``round4_research`` .. ``round17_research``: their ``definitions_sha256``
hash the whole table, so adding them would make the validation refuse the
exploration reports already run.  G1 trades on X7's event-day account
(``explore_research.simulate_events``), G2 on ``portfolio_research.simulate``
(K 60); the population, the loading (``explore_research.load_context``),
``explore_judge``, the gate and the ledgers are imported.  G1's event days
are ``round14_research.quarter_events``, its latest quarter
``round15_research._known`` and its single quarters
``round15_research.single_quarter`` (as P2 and N2), its rows read by
``round16_research``'s reader; G2's sampling days and returns are Z3's
(``round8_research.closes_of``).  The overlaps take P2
(``round15_research.margins_up`` through ``round16_research.p2_names``), N2
(``round16_research.tax_mom``), A1 (``round17_research.net_issue``), X4
(``round14_research.x4_names``), Z2 and Z3 (``round8_research.rank``) on the
same T, and ``round10_research``'s ``overlap_share``／``overlap_summary``.
New here are only ``nonop_q`` (with its own reading of
``fundamental_snapshots.data_json``), ``coskew_240``, G1's reference
population and the listed numbers.

Each signal date T (after its close, only T's data and before):

- G1: on the 4 statutory deadlines, ``nonop_q`` (the latest quarter's single
  quarter non-operating income and expenses over its single quarter
  revenue) small first, 20, held to the next event day (X7).
- G2: ``coskew_240`` (the standardised coskewness of the last 240 daily
  returns with the TAIEX's) small first, 20, K 60.

``explore_research.explore_judge`` judges with t ≥ 2 on the exploration and
the fixed Bonferroni t ≥ 3.368 (66 hypotheses) on the validation.  Before the
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
from operator import mul
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_lib as lib  # noqa: E402
import exit_research as er  # noqa: E402
import explore_research as ex  # noqa: E402
import feature_evidence as features  # noqa: E402
import portfolio_research as pr  # noqa: E402
import round5_research as r5  # noqa: E402
import round8_research as r8  # noqa: E402
import round10_research as r10  # noqa: E402
import round14_research as r14  # noqa: E402
import round15_research as r15  # noqa: E402
import round16_research as r16  # noqa: E402
import round17_research as r17  # noqa: E402

VERSION = 1
DESIGN = "1029"
TOOL = "round18_research"
REGISTRATION_COMMIT = "c985ca64"
DECISION = (
    "https://github.com/YiCheng0608/stock-lab/issues/1025#issuecomment-7115607959"
)
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
SEGMENTS = dict(ex.SEGMENTS)
MIN_SEGMENT_DAYS = dict(ex.MIN_SEGMENT_DAYS)
MIN_T = ex.MIN_T  # the exploration's t ≥ 2
# docs 第十八輪 門檻: 1 − Φ(z) = 0.025 ÷ 66, z = 3.3678, 3.368 to the 3rd decimal;
# fixed, not computed when run.
VALIDATION_MIN_T = 3.368
ROUND = 18
ROUND_SIZE = 2
# X1～X8, S1～S3, R1～R2, M1～M2, C1～C4, V1～V3, W1～W4, Y1～Y4, Z1～Z4, B1～B3,
# F1～F4, L1～L4, J1～J4, U1～U3, K1～K3, P1～P3, N1～N3, A1～A3, G1～G2
CUMULATIVE = 66
# Every segment reads the copy from its start, as round10_research ..
# round17_research: G2 reads 241 sessions.
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
    "by the feature, small first (round5_research.order_key), missing last, "
    "ties by sha256(<T>:<instrument_id>)"
)
SHORT_RULE = "cash, not filled"
SALE = (
    "one account (X7): bought at T+1's open, 1/20 of the cash each, sold at "
    "the close of the next event day T' (explore_research.simulate_events), "
    "the new list bought at T'+1's open; the population on the same rule and "
    "event days"
)
REFERENCE_STATUSES = ("delisted", "transferred")
SINGLE_QUARTER = r15.SINGLE_QUARTER

# G1 (第 1～5 點)
NONOP = "營業外收入及支出"
REVENUE = "營業收入"
REPORT_FORMAT = "general"
FIELDS = ("nonop", "revenue")  # NonopStatement's attributes, in that order
REVENUE_MIN = 0.0  # rev(q) ≤ 0: missing
LATEST_RULE = (
    "the latest quarter known on T (announcement_date <= T, the largest "
    "period_end, an EPS null row too) must be the deadline's quarter"
)
NEEDED_RULE = (
    "q and, when q is not a Q1, the quarter before q of the same year (its "
    "cumulative figures for the single quarter)"
)
NUMBER_RULE = "worker.sources.parse_number on the data_json cell"
STATEMENT_RULE = (
    "fundamental_snapshots rows with announcement_date <= T (an EPS null row "
    "too), round15_research._known: by period_end, the later announcement; a "
    "needed row not known or a field null is missing; a needed row of another "
    "report_format is missing, a null report_format a missing field"
)
NONOP_Q = (
    "nonop(q) / rev(q), single quarters; nonop(q) 0: 0, not missing; reasons "
    "in order: stale, format, fields, revenue"
)
G1_REFERENCE = (
    "T's population less the delisted or transferred instruments missing a "
    "field nonop_q needs on T (a needed row of the deadline's quarter not "
    "known, or NONOP or REVENUE null, so no single quarter; not the stale "
    "quarter, the report_format nor rev(q) <= 0); the same account and event "
    "days"
)
G1_START = date(2013, 5, 15)
P2, N2, A1, X4 = "P2", "N2", "A1", "X4"  # the lists G1 overlaps with

# G2 (第 1～3 點)
COSKEW_SESSIONS = 241  # market sessions T − 240 .. T
COSKEW_DAYS = 240  # the returns j = 2 .. 241, each mean over 240
REGRESSION = (
    "r_j = a + b m_j by least squares, with an intercept and no lag; e_j the "
    "residuals; b = sum(d_j (r_j - mean r)) / sum(d_j^2)"
)
COSKEW_RULE = (
    "d_j = m_j - mean m; coskew_240 = mean(e_j d_j^2) / (sqrt(mean(e_j^2)) "
    "mean(d_j^2)), each mean over the 240 days (divided by 240); mean(e_j "
    "d_j^2) 0: 0, not missing"
)
COSKEW_SAMPLE = (
    "Panel.sessions T-240 .. T; the item's last 241 bars to T, the first on "
    "session T-240 exactly (Z3's beta_240 comparison); r_j the adjusted "
    "close over the bar before's, m_j the TAIEX close (twse_index) over the "
    "session before's"
)
COSKEW_MISSING = (
    "fewer than 241 bars; a session of the 241 without the item's bar; a "
    "suspended bar; a close missing or <= 0; a TAIEX close missing or <= 0; "
    "sum d_j^2 not > 0 (every member that day); sum e_j^2 not > 0: missing, "
    "ranked last, not dropped"
)
MARKET_RULE = "the market part (mean m, d_j, d_j^2, sum d_j^2) once per T, shared"
OTC_ANCHOR = date(2007, 12, 3)  # the OTC bars the tools read
Z2, Z3 = "Z2", "Z3"  # the lists G2 overlaps with

# The registration (docs 第十八輪：G1、G2), word for word.  ``start`` as
# ``explore_research``.
HYPOTHESES: dict[str, dict[str, Any]] = {
    "G1": {
        "engine": EVENTS,
        "direction": "基本面：業外損益的反向",
        "label": "每季法定期限的事件日，`nonop_q`（最新一季單季 `營業外收入及支出` ÷ 單季 `營業收入`）"
        "小者先取 20 檔",
        "rule": "quarterly",
        "keys": (("nonop_q", LOW),),
        "short": SHORT_RULE,
        "top": 20,
        "hold": "next_event",
        "start": ("date", G1_START),
    },
    "G2": {
        "engine": PORTFOLIO,
        "direction": "風險溢酬：共偏態",
        "label": "`coskew_240`（近 240 個全市場交易日的日報酬，對加權指數的標準化共偏態）小者先",
        "rule": "daily",
        "keys": (("coskew_240", LOW),),
        "short": SHORT_RULE,
        "top": 20,
        "hold": 60,
        "start": ("session", OTC_ANCHOR, COSKEW_SESSIONS),
    },
}
OTHER_COMPARISONS = ex.OTHER_COMPARISONS
REASONS = dict(ex.REASONS)
LIMITS = {
    "G1": "定義照摘要與索引頁（[EconPapers](https://econpapers.repec.org/RePEc:bla:joares:v:40:y:2002:i:3:p:585-612)），"
    "未讀全文；代理：文獻的特殊項目是重組、減損等一次性項目，台股綜合損益表沒有「特殊項目」一欄，以營業外收支代理，"
    "營業外收支除了一次性的處分與減損，也含利息收支、權益法投資收益這類持續性較高的項目；分母是單季營收，"
    "名單可能偏向本業規模小、業外大的公司，看名單的平均單季營收；存活者偏差：下市股的季報是 XBRL 整包補的，"
    "只寫了 EPS，沒有這兩個欄位，期間內下市公司的季幾乎都缺值、排最後，偏差方向對假設有利，大小同 P2、N2、A1；"
    "金融業等格式與法定期限不同的公司不會有值；有值檔數偏少的季寫在資料覆蓋；和 P2、N2、A1、X4 同一張季報表、"
    "同一份存活者偏差，登記時它們的狀態已知，用到的欄位不同，看重疊比例",
    "G2": "定義照摘要與索引頁（[EconPapers](https://econpapers.repec.org/RePEc:bla:jfinan:v:55:y:2000:i:3:p:1263-1295)），"
    "未讀全文；日報酬有非同步交易（小型股慢反應），共偏態會被低估，三階共動差沒有通用的落後修正，本輪不加；"
    "加權指數是價格指數、不含股利，同 Z3；和 Z2（總偏態小者先）、Z3（beta 小者先）有關，共偏態是總偏態裡和大盤"
    "連動的部分，名單會和 Z2 重疊，登記時 Z2、Z3 的狀態已知，看重疊比例與名單的平均 `skew_240`、`beta_240`",
}
# The degenerate cases as the code judges them (第十八輪實作釋義; PR #913
# review: the docs, coverage.md and summary.md say the same words, a test
# reads the docs' tool section for them).
DEGENERATE = {
    "G1": "最新一季（`announcement_date` ≤ T 的季報列中期末最晚的一季，EPS 是 null 的列也算）不是事件日對應的那一季、"
    "q 與同年前一季（q 是 Q1 時只有 q）任一列的 `report_format` 不是 `general`（`report_format` 是 null 的列算欄位缺）、"
    "任一列不在或 `營業外收入及支出`、`營業收入` 任一欄缺（含算單季要用的同年前一季累計缺），或 rev(q) ≤ 0 時缺值、排最後；"
    "nonop(q)＝0 時 `nonop_q`＝0，照值排序，不是缺值；有值的不足 20 檔時以缺值的依雜湊補，母體不足 20 檔時餘額留現金",
    "G2": "T−240…T 這 241 個全市場交易日中任一天這一檔沒有日線（這一檔到 T 為止的最後 241 根，最早那一根不在 T−240）、"
    "不足 241 根、任一根停牌、還原收盤缺值或 ≤ 0，或任一天加權指數收盤缺值或 ≤ 0，或 Σdⱼ² 不是 > 0"
    "（大盤欄退化，那一天母體每一檔都缺值），或 Σεⱼ² 不是 > 0 時缺值、排最後、不剔除；"
    "Σdⱼ² 接近 0 但 > 0、Σεⱼ² 很小但 > 0 不另攔；mean(εⱼ·dⱼ²)＝0 時 `coskew_240`＝0，照值排序，不是缺值",
}
OVERLAP_NOTE = {
    "G1_P2": 'G1 與 P2（`round15_research` 第 1 版的 `HYPOTHESES["P2"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|G1 的名單 ∩ P2 當天的名單| ÷ G1 當天的名單檔數；G1 或 P2 當天沒有名單的事件日不計。只列出、不判定",
    "G1_N2": 'G1 與 N2（`round16_research` 第 1 版的 `HYPOTHESES["N2"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|G1 的名單 ∩ N2 的前 20 名| ÷ G1 當天的名單檔數；G1 或 N2 當天沒有名單的事件日不計。只列出、不判定",
    "G1_A1": 'G1 與 A1（`round17_research` 第 1 版的 `HYPOTHESES["A1"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|G1 的名單 ∩ A1 的前 20 名| ÷ G1 當天的名單檔數；G1 或 A1 當天沒有名單的事件日不計。只列出、不判定",
    "G1_X4": 'G1 與 X4（`explore_research` 第 2 版的 `HYPOTHESES["X4"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|G1 的名單 ∩ X4 的前 20 名| ÷ G1 當天的名單檔數；G1 或 X4 當天沒有名單的事件日不計。只列出、不判定",
    "G2_Z2": 'G2 與 Z2（`round8_research` 第 1 版的 `HYPOTHESES["Z2"]`，同一個 T 算）每日名單的重疊比例：'
    "|G2 的名單 ∩ Z2 的前 20 名| ÷ G2 當天的名單檔數；G2 或 Z2 當天沒有名單的日子不計。只列出、不判定",
    "G2_Z3": 'G2 與 Z3（`round8_research` 第 1 版的 `HYPOTHESES["Z3"]`，同一個 T 算）每日名單的重疊比例：'
    "|G2 的名單 ∩ Z3 的前 20 名| ÷ G2 當天的名單檔數；G2 或 Z3 當天沒有名單的日子不計。只列出、不判定",
    "G1_reference": "對照基準：當天母體去掉「缺 `nonop_q` 任一所需欄位（事件日對應的那一季 q 與同年前一季，"
    "任一列不在或兩個欄位任一欄缺，算不出單季；不看是不是最新一季、不看 `report_format`、不看 rev(q) ≤ 0）的 "
    "`delisted`／`transferred` 標的」，同一個帳戶規則、同一組事件日；列 G1 對它的超額與 t，只列出、不判定（判定仍只比母體）",
    "G1_survivor": "- 存活者偏差（G1）：下市股的季報是 XBRL 整包補的，只寫了 EPS，沒有 `營業外收入及支出`、`營業收入`，"
    "期間內下市公司的季幾乎都缺值、排最後，偏差方向對假設有利。對照基準（母體去掉當天缺所需欄位的下市、轉板股）的超額與 t "
    "在 `G1/summary.md`「數字」表的「超額（對對照基準，只列出）」列與 `explore.md` 的「只列出、不判定」",
    "G1_proxy": "代理：文獻的特殊項目是重組、減損等一次性項目；台股綜合損益表沒有「特殊項目」一欄，以營業外收支代理。"
    "營業外收支除了一次性的處分與減損，也含利息收支、權益法投資收益這類持續性較高的項目",
    "G1_listed": "名單的平均單季營收：每個事件日名單中有值的檔的 rev(q)（千元）平均；業外為負的比例：名單中有 `nonop_q` "
    "的檔裡 nonop(q) < 0 的比例。只列出、不判定",
    "G2_listed": "名單的平均 `skew_240`、`beta_240`：每天名單中有值的檔的 `round8_research.skew_240`、"
    "`round8_research.beta_240` 平均；大盤欄退化或加權指數缺值的訊號日，母體每一檔都缺值。只列出、不判定",
    "summary_only": "定義照摘要與索引頁，未讀全文",
}
FEATURE_LABELS = {
    "nonop_q": "業外損益占營收",
    "coskew_240": "共偏態",
    # the listed means (G1 第 7 點, G2 第 6 點)
    "revenue": "名單的平均單季營收（千元）",
    "negative": "名單裡業外為負的比例",
    "skew_240": "名單的平均 `skew_240`",
    "beta_240": "名單的平均 `beta_240`",
}
PICK_FIELDS = {
    "G1": ("quarter", "nonop_q", "nonop", "revenue"),
    "G2": ("coskew_240", "skew_240", "beta_240"),
}


def definitions() -> dict[str, Any]:
    return {
        "version": VERSION,
        "design": DESIGN,
        "hypotheses": HYPOTHESES,
        "order": ORDER,
        "short": SHORT_RULE,
        "sale": SALE,
        "reference_statuses": list(REFERENCE_STATUSES),
        "single_quarter": [SINGLE_QUARTER, features.SHARED_VERSION],
        "deadlines": [r14.DEADLINES, r14.EVENT_DAY_RULE],  # G1's events
        "features": {
            "nonop_q": {
                "fields": [NONOP, REVENUE],
                "attributes": FIELDS,
                "report_format": REPORT_FORMAT,
                "revenue_min": REVENUE_MIN,
                "latest": LATEST_RULE,
                "needed": NEEDED_RULE,
                "number": NUMBER_RULE,
                "statements": STATEMENT_RULE,
                "formula": NONOP_Q,
                "reference": G1_REFERENCE,
            },
            "coskew_240": {
                "sessions": COSKEW_SESSIONS,
                "days": COSKEW_DAYS,
                "regression": REGRESSION,
                "formula": COSKEW_RULE,
                "sample": COSKEW_SAMPLE,
                "missing": COSKEW_MISSING,
                "market": MARKET_RULE,
            },
            "overlaps": {
                P2: [r15.HYPOTHESES[P2], r15.VERSION, r15.definitions_sha256()],
                N2: [r16.HYPOTHESES[N2], r16.VERSION, r16.definitions_sha256()],
                A1: [r17.HYPOTHESES[A1], r17.VERSION, r17.definitions_sha256()],
                X4: [ex.HYPOTHESES[X4], ex.VERSION],
                Z2: [r8.HYPOTHESES[Z2], r8.VERSION, r8.definitions_sha256()],
                Z3: [r8.HYPOTHESES[Z3], r8.VERSION, r8.definitions_sha256()],
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
    G1's two fields, format, latest quarter, needed rows, single quarters,
    rev(q) ≤ 0 and the reference, G2's 241 sessions, regression, 240 as the
    means' divisor, sampling and missing rules, N and K, the order, the
    overlaps' lists, the segments, the costs).  A changed tool needs a new
    exploration report before a validation."""

    text = json.dumps(definitions(), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- reading ----------------------------------------------------------------------


@dataclass(frozen=True)
class NonopStatement:
    """One ``fundamental_snapshots`` row for G1: the year's cumulative
    non-operating income and expenses and revenue (thousands), None when the
    cell is missing."""

    announced: date
    period_end: date
    report_format: str | None
    nonop: float | None
    revenue: float | None


def nonop_statement_of(
    announced: str, period_end: str, data: dict[str, Any], parse
) -> NonopStatement:
    def value(name: str) -> float | None:
        return parse(data.get(name)) if name in data else None

    return NonopStatement(
        date.fromisoformat(announced),
        date.fromisoformat(period_end),
        data.get("report_format"),
        value(NONOP),
        value(REVENUE),
    )


def load_nonop_statements(
    db: Path, series: dict[int, lib.Series], end: date
) -> dict[int, list[NonopStatement]]:
    """G1: every row with an ``announcement_date`` ≤ ``end`` (none after it
    read), by announcement; the rows ``round16_research`` reads (its
    ``_rows``／``_data``), G1's two fields."""

    from worker.sources import parse_number

    out: dict[int, list[NonopStatement]] = defaultdict(list)
    for instrument_id, announced, period_end, text in r16._rows(db, end):
        if instrument_id in series:
            out[instrument_id].append(
                nonop_statement_of(announced, period_end, r16._data(text), parse_number)
            )
    return dict(out)


def columns_2013(db: Path) -> dict[str, Any]:
    """G1 (``--coverage-only``): 2013's column names by quarter and
    report_format, and the rows with each of the two fields."""

    con = lib.connect_read_only(db)
    out: dict[str, Any] = {}
    try:
        rows = con.execute(
            "select period_end, data_json from fundamental_snapshots "
            "where period_end between '2013-01-01' and '2013-12-31' "
            "order by period_end"
        )
        for period_end, text in rows:
            data = r16._data(text)
            kind = str(data.get("report_format"))
            quarter = out.setdefault(period_end, {})
            part = quarter.setdefault(
                kind, {"rows": 0, "fields": Counter(), "columns": Counter()}
            )
            part["rows"] += 1
            part["columns"].update(data.keys())
            for name in (NONOP, REVENUE):
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


@dataclass(frozen=True)
class CoskewMarket:
    """G2's market part on T (第十八輪實作釋義: once per T, every stock's):
    the first sampling session, d_j = m_j − m̄, d_j² and Σd_j²."""

    first: int  # session index of T − 240
    d: tuple[float, ...]
    d2: tuple[float, ...]
    sdd: float


@dataclass
class Context:
    """``explore_research``'s context (the market, the quotes, the EPS
    quarters), G1's statements, the instruments' status, the contexts
    ``round16_research`` (N2's statements and P2's, ``round15_research``'s
    context), ``round17_research`` (A1's statements and stock dividends) and
    ``round8_research`` (Z2, Z3, the returns G2 reads) rank with (the same
    base).  One panel."""

    base: ex.Context
    statements: dict[int, list[NonopStatement]] = field(default_factory=dict)
    statuses: dict[int, str] = field(default_factory=dict)
    p2_statements: dict[int, list[r15.Statement]] = field(default_factory=dict)
    tax_statements: dict[int, list[r16.TaxStatement]] = field(default_factory=dict)
    share_statements: dict[int, list[r17.ShareStatement]] = field(default_factory=dict)
    dividends: dict[int, list[tuple[date, float | None]]] = field(default_factory=dict)
    z: r8.Context | None = None
    n2: r16.Context | None = None
    a1: r17.Context | None = None
    seconds: Counter = field(default_factory=Counter)
    load_seconds: dict[str, float] = field(default_factory=dict)
    # G2: T's market part by session, or the reason it is missing
    markets: dict[int, CoskewMarket | str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.z is None:
            self.z = r8.Context(self.base)
        if self.n2 is None:
            self.n2 = r16.Context(
                self.base,
                self.tax_statements,
                self.p2_statements,
                self.statuses,
                z2=self.z,
            )
        if self.a1 is None:
            self.a1 = r17.Context(
                self.base, self.share_statements, self.dividends, self.statuses
            )

    @property
    def p2(self) -> r15.Context:
        return self.n2.p2

    @property
    def market(self) -> pr.Market:
        return self.base.market

    @property
    def panel(self) -> lib.Panel:
        return self.base.market.panel

    def quote(self, instrument_id: int, s: int) -> pr.Quote | None:
        return self.base.quote(instrument_id, s)


def load(db: Path, start: date, end: date, raw_dir: Path) -> Context:
    """The panel, the turnovers, the EPS quarters, G1's statements, P2's,
    N2's and A1's statements, A1's stock dividends and the statuses to
    ``end``; nothing after ``end`` is read."""

    started = time.monotonic()
    base = ex.load_context(db, start, end, raw_dir)
    panel_seconds = time.monotonic() - started
    t0 = time.monotonic()
    series = base.market.panel.series
    statements = load_nonop_statements(db, series, end)
    statuses = r15.load_statuses(db)
    statement_seconds = time.monotonic() - t0
    t0 = time.monotonic()
    p2_statements = r15.load_statements(db, series, end)
    tax_statements = r16.load_tax_statements(db, series, end)
    share_statements = r17.load_share_statements(db, series, end)
    dividends = r17.load_stock_dividends(db, series, end)
    return Context(
        base,
        statements,
        statuses,
        p2_statements,
        tax_statements,
        share_statements,
        dividends,
        load_seconds={
            "panel": panel_seconds,
            "statements": statement_seconds,
            "lists": time.monotonic() - t0,
        },
    )


# --- G1: nonop_q ------------------------------------------------------------------


_known = r15._known
_quarter_before = r15._quarter_before
single_quarter = r15.single_quarter


def _needed(quarter: date) -> list[date]:
    """q and, when q is not a Q1, the quarter before it (the same year)."""

    return [quarter] if quarter.month == 3 else [quarter, _quarter_before(quarter)]


def _singles(known: dict[date, NonopStatement], quarter: date):
    """(nonop(q), rev(q)), or None when one is missing."""

    out = []
    for name in FIELDS:
        cumulative = {
            end: getattr(row, name)
            for end, row in known.items()
            if getattr(row, name) is not None
        }
        value = single_quarter(cumulative, quarter)
        if value is None:
            return None
        out.append(value)
    return tuple(out)


@dataclass(frozen=True)
class Nonop:
    value: float | None
    # "stale", "format", "fields", "revenue" or None
    reason: str | None = None
    nonop: float | None = None  # nonop(q)
    revenue: float | None = None  # rev(q)


def nonop_q(ctx: Context, item: lib.Series, day: date, quarter: date) -> Nonop:
    """G1 第 1～4 點 on T (``day``) for the deadline's ``quarter``."""

    known = _known(ctx.statements.get(item.instrument_id, []), day)
    if not known or max(known) != quarter:
        return Nonop(None, "stale")
    rows = [known.get(end) for end in _needed(quarter)]
    if any(
        row is not None
        and row.report_format is not None
        and row.report_format != REPORT_FORMAT
        for row in rows
    ):
        return Nonop(None, "format")
    if any(
        row is None
        or row.report_format != REPORT_FORMAT
        or any(getattr(row, name) is None for name in FIELDS)
        for row in rows
    ):
        return Nonop(None, "fields")
    singles = _singles(known, quarter)
    if singles is None:
        return Nonop(None, "fields")
    nonop, revenue = singles
    if revenue <= REVENUE_MIN:
        return Nonop(None, "revenue", nonop, revenue)
    return Nonop(nonop / revenue, None, nonop, revenue)


def fields_missing(ctx: Context, item: lib.Series, day: date, quarter: date) -> bool:
    """G1 第 3 點 second case on the deadline's ``quarter`` (the reference's
    rule, 第十八輪實作釋義): a needed row not known on T or a field missing."""

    known = _known(ctx.statements.get(item.instrument_id, []), day)
    for end in _needed(quarter):
        row = known.get(end)
        if row is None or any(getattr(row, name) is None for name in FIELDS):
            return True
    return _singles(known, quarter) is None


# --- G2: coskew_240 ---------------------------------------------------------------


def coskew_market(ctx: Context, s: int) -> CoskewMarket | str:
    """T's market part (T is session ``s``), or why it is missing: "index"
    (a sampling session before the copy, a TAIEX close missing or ≤ 0) or
    "degenerate" (Σd_j² not > 0)."""

    got = ctx.markets.get(s)
    if got is not None:
        return got
    first = s - COSKEW_SESSIONS + 1
    out: CoskewMarket | str = "index"
    if first >= 0:
        sessions, index = ctx.panel.sessions, ctx.panel.index_close
        closes = [index.get(sessions[p]) for p in range(first, s + 1)]
        if all(close is not None and close > 0 for close in closes):
            m = [closes[j] / closes[j - 1] - 1.0 for j in range(1, len(closes))]
            mean = math.fsum(m) / COSKEW_DAYS
            d = tuple(value - mean for value in m)
            d2 = tuple(map(mul, d, d))
            sdd = math.fsum(d2)
            out = CoskewMarket(first, d, d2, sdd) if sdd > 0 else "degenerate"
    ctx.markets[s] = out
    return out


@dataclass(frozen=True)
class Coskew:
    value: float | None
    # "index", "degenerate", "short", "gap", "suspended", "price", "flat"
    reason: str | None = None


def coskew_of(returns, market: CoskewMarket) -> Coskew:
    """G2 第 2 點 on the 240 returns r_j and T's market part."""

    mean = math.fsum(returns) / COSKEW_DAYS
    centred = [value - mean for value in returns]
    b = math.fsum(map(mul, market.d, centred)) / market.sdd
    e = [r - b * d for r, d in zip(centred, market.d)]
    see = math.fsum(map(mul, e, e))
    if not see > 0:
        return Coskew(None, "flat")
    numerator = math.fsum(map(mul, e, market.d2)) / COSKEW_DAYS
    return Coskew(
        numerator / (math.sqrt(see / COSKEW_DAYS) * (market.sdd / COSKEW_DAYS))
    )


def coskew_240(ctx: Context, item: lib.Series, at: int) -> Coskew:
    """G2 第 1～3 點 on the item's bar ``at`` (T)."""

    market = coskew_market(ctx, item.session[at])
    if isinstance(market, str):
        return Coskew(None, market)
    first = at - COSKEW_SESSIONS + 1
    if first < 0:
        return Coskew(None, "short")
    # 241 bars of this stock ending on T span exactly the 241 sampling
    # sessions only when none of them is without a bar (Z3's comparison)
    if item.session[first] != market.first:
        return Coskew(None, "gap")
    if r8._suspended_in(item, first, at):
        return Coskew(None, "suspended")
    parts = r8.closes_of(ctx.z, item)
    if parts.bad[at + 1] != parts.bad[first]:
        return Coskew(None, "price")
    return coskew_of(parts.returns[first + 1 : at + 1], market)


# --- the plans --------------------------------------------------------------------


def segment_window(
    sessions: list[date], segment: str, spec: dict[str, Any]
) -> tuple[int, int] | None:
    """(first, last) index of the sessions with an equity value, or None.
    G1's equity starts the session after its first event day in the segment
    (as X7's)."""

    first_day, last_day = SEGMENTS[segment]
    last = bisect_left(sessions, last_day + timedelta(days=1)) - 1
    if first_day is None:
        base = ex.start_index(sessions, spec["start"])
        if base is None:
            return None
    else:
        base = max(bisect_left(sessions, first_day), 1) - 1
    if spec["rule"] == "quarterly":
        found = [at for at, _q in r14.quarter_events(sessions) if at >= base]
        if not found:
            return None
        base = found[0]
    first = base + 1
    return (first, last) if first <= last else None


@dataclass
class Plan:
    picks: dict[int, list[int]] = field(default_factory=dict)
    population: dict[int, list[int]] = field(default_factory=dict)
    reference: dict[int, list[int]] = field(default_factory=dict)  # G1
    dues: dict[int, int] = field(default_factory=dict)  # G1
    rows: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    signal_days: int = 0
    event_days: int = 0
    overlap: dict[str, dict[str, list[float]]] = field(default_factory=dict)
    # the listed means by year: G1 revenue, negative; G2 skew_240, beta_240
    means: dict[str, dict[str, list[float]]] = field(default_factory=dict)
    rebalances: list[dict[str, Any]] = field(default_factory=list)  # G1


_year = r15._year
_add = r15._add
_pick_row = r15._pick_row


def _timed(ctx: Context, key: str, run: Callable[[], set[int]]) -> set[int]:
    t0 = time.perf_counter()
    try:
        return run()
    finally:
        ctx.seconds[key] += time.perf_counter() - t0


def p2_names(ctx: Context, day, members, quarter) -> set[int]:
    """P2's list (``round16_research.p2_names``: ``round15_research.margins_up``
    on P2's own statements, the first 20 by the hash)."""

    return _timed(ctx, "p2_order", lambda: r16.p2_names(ctx.n2, day, members, quarter))


def n2_names(ctx: Context, day, members, quarter) -> set[int]:
    """N2's list on ``day`` (``round16_research`` 第 1 版的定義: ``tax_mom``
    on N2's own statements, ranked as ``round16_research.plan_n2``)."""

    def run() -> set[int]:
        spec = r16.HYPOTHESES[N2]
        keys = tuple(name for name, _direction in spec["keys"])
        rows = sorted(
            (
                pr.ranking_key(
                    {keys[0]: r16.tax_mom(ctx.n2, item, day, quarter).value},
                    keys,
                    pr.tie_break(day, item.instrument_id),
                ),
                item.instrument_id,
            )
            for item, _k in members
        )
        return {instrument_id for _key, instrument_id in rows[: spec["top"]]}

    return _timed(ctx, "n2_order", run)


def a1_names(ctx: Context, day, members, quarter) -> set[int]:
    """A1's list on ``day`` (``round17_research`` 第 1 版的定義: ``net_issue``
    on A1's own statements and stock dividends, ranked as
    ``round17_research.plan_a1``)."""

    def run() -> set[int]:
        spec = r17.HYPOTHESES[A1]
        keys = tuple(spec["keys"])
        rows = sorted(
            (
                r5.order_key(
                    {keys[0][0]: r17.net_issue(ctx.a1, item, day, quarter).value},
                    keys,
                    pr.tie_break(day, item.instrument_id),
                ),
                item.instrument_id,
            )
            for item, _k in members
        )
        return {instrument_id for _key, instrument_id in rows[: spec["top"]]}

    return _timed(ctx, "a1_order", run)


def x4_names(ctx: Context, day, members) -> set[int]:
    """X4's list (``round14_research.x4_names``: ``explore_research._rank``)."""

    return r14.x4_names(ctx, day, members)


def z_names(ctx: Context, name: str, day, members) -> set[int]:
    """Z2's or Z3's list on ``day`` (``round8_research`` 第 1 版的定義, not
    rewritten)."""

    def run() -> set[int]:
        spec = r8.HYPOTHESES[name]
        rows = r8.rank(ctx.z, spec, day, members).rows
        return {row[0] for row in rows[: spec["top"]]}

    return _timed(ctx, f"{name.lower()}_order", run)


def _reference(ctx, members, missing: Callable[[lib.Series], bool]):
    """(the delisted or transferred members, those missing a field, the
    instruments the reference leaves out)."""

    gone = gone_missing = 0
    excluded = set()
    for item, _k in members:
        if ctx.statuses.get(item.instrument_id) in REFERENCE_STATUSES:
            gone += 1
            if missing(item):
                gone_missing += 1
                excluded.add(item.instrument_id)
    return gone, gone_missing, excluded


def _listed_g1(chosen) -> tuple[float | None, float | None]:
    """(the list's mean rev(q) where known, the share of nonop(q) < 0 among
    the list's members with a ``nonop_q``)."""

    revenues = [got.revenue for _i, got, _t in chosen if got.revenue is not None]
    valued = [got for _i, got, _t in chosen if got.value is not None]
    mean = statistics.fmean(revenues) if revenues else None
    negative = (
        sum(1 for got in valued if got.nonop < 0) / len(valued) if valued else None
    )
    return mean, negative


def plan_g1(
    ctx: Context, spec: dict[str, Any], first: int, last: int, keep_rows=True
) -> Plan:
    """G1 第 1～7 點: the event days of the segment, ``nonop_q`` in T's
    population small first, 20, held to the next event day (X7); the
    reference population on the same days."""

    panel = ctx.panel
    sessions = panel.sessions
    out = Plan(
        overlap={"G1_P2": {}, "G1_N2": {}, "G1_A1": {}, "G1_X4": {}},
        means={"revenue": {}, "negative": {}},
    )
    top = spec["top"]
    keys = tuple(spec["keys"])
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
            got = nonop_q(ctx, item, day, quarter)
            reasons[got.reason] += 1
            rows.append((item, got, pr.tie_break(day, item.instrument_id)))
        ctx.seconds["nonop_q"] += time.perf_counter() - t0
        t0 = time.perf_counter()
        gone, gone_missing, excluded = _reference(
            ctx, members, lambda item: fields_missing(ctx, item, day, quarter)
        )
        ctx.seconds["reference"] += time.perf_counter() - t0
        rows.sort(
            key=lambda row: r5.order_key({keys[0][0]: row[1].value}, keys, row[2])
        )
        chosen = rows[:top]
        valued = [got for _i, got, _t in rows if got.value is not None]
        event = {
            "signal_date": day.isoformat(),
            "quarter": quarter.isoformat(),
            "members": len(members),
            "valued": reasons[None],
            **{key: reasons[key] for key in ("stale", "format", "fields", "revenue")},
            "names": len(chosen),
            "delisted": gone,
            "delisted_missing": gone_missing,
            "zero": sum(1 for got in valued if got.value == 0),
            "negative": sum(1 for got in valued if got.nonop < 0),
        }
        for key in ("valued", "delisted", "delisted_missing", "zero", "negative"):
            _add(year, key, event[key])
        year.setdefault("events", []).append(event)
        others = {
            "G1_P2": p2_names(ctx, day, members, quarter),
            "G1_N2": n2_names(ctx, day, members, quarter),
            "G1_A1": a1_names(ctx, day, members, quarter),
            "G1_X4": x4_names(ctx, day, members),
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
        revenue, negative = _listed_g1(chosen)
        for key, value in (("revenue", revenue), ("negative", negative)):
            if value is not None:
                out.means[key].setdefault(str(day.year), []).append(value)
        out.rebalances.append(
            {**event, "p2_overlap": shares["G1_P2"], "n2_overlap": shares["G1_N2"],
             "a1_overlap": shares["G1_A1"], "x4_overlap": shares["G1_X4"],
             "revenue_mean": revenue, "negative_share": negative}
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
                    {"quarter": quarter.isoformat(), "nonop_q": got.value,
                     "nonop": got.nonop, "revenue": got.revenue},
                    tie,
                )
            )  # fmt: skip
    return out


def plan_g2(
    ctx: Context, spec: dict[str, Any], first: int, last: int, keep_rows=True
) -> Plan:
    """G2 第 1～4、6 點 on the signal dates ``first − 1`` .. ``last − 1``."""

    panel = ctx.panel
    out = Plan(
        overlap={"G2_Z2": {}, "G2_Z3": {}},
        means={"skew_240": {}, "beta_240": {}},
    )
    top = spec["top"]
    keys = tuple(spec["keys"])
    for at in range(first - 1, last):
        day = panel.sessions[at]
        members = lib.universe(panel, day, MIN_LOTS)
        year = _year(out.coverage, day, len(members))
        out.signal_days += 1
        t0 = time.perf_counter()
        market = coskew_market(ctx, at)
        if isinstance(market, str):  # every member missing that day
            _add(year, f"{market}_days", 1)
        rows, missing = [], Counter()
        for item, k in members:
            got = coskew_240(ctx, item, k)
            if got.value is None:
                missing["coskew_240"] += 1
                missing[got.reason] += 1
            rows.append((item, k, got, pr.tie_break(day, item.instrument_id)))
        ctx.seconds["coskew_240"] += time.perf_counter() - t0
        rows.sort(
            key=lambda row: r5.order_key({keys[0][0]: row[2].value}, keys, row[3])
        )
        chosen = rows[:top]
        missing_year = year.setdefault("missing", {})
        for key, count in missing.items():
            missing_year[key] = missing_year.get(key, 0) + count
        _add(year, "valued", len(members) - missing["coskew_240"])
        others = {
            "G2_Z2": z_names(ctx, Z2, day, members),
            "G2_Z3": z_names(ctx, Z3, day, members),
        }  # timed in the coverage too
        if not keep_rows:
            continue
        names = [item.instrument_id for item, _k, _g, _t in chosen]
        for key, other in others.items():
            share = r10.overlap_share(names, other)
            if share is not None:
                out.overlap[key].setdefault(str(day.year), []).append(share)
        t0 = time.perf_counter()
        skews = [r8.skew_240(ctx.z, item, k) for item, k, _g, _t in chosen]
        betas = [r8.beta_240(ctx.z, item, k) for item, k, _g, _t in chosen]
        ctx.seconds["skew_beta"] += time.perf_counter() - t0
        for key, values in (("skew_240", skews), ("beta_240", betas)):
            present = [v for v in values if v is not None]
            if present:
                out.means[key].setdefault(str(day.year), []).append(
                    statistics.fmean(present)
                )
        out.picks[at + 1] = names
        out.population[at + 1] = [item.instrument_id for item, _ in members]
        for place, ((item, _k, got, tie), skew, beta) in enumerate(
            zip(chosen, skews, betas), 1
        ):
            out.rows.append(
                _pick_row(ctx, day, place, item.instrument_id,
                          {"coskew_240": got.value, "skew_240": skew, "beta_240": beta},
                          tie)
            )  # fmt: skip
    return out


def planner(name: str) -> Callable[..., Plan]:
    return {"G1": plan_g1, "G2": plan_g2}[name]


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
    """(the hypothesis, the population, the reference): G1 X7's account with
    its reference, G2 K accounts."""

    spec = HYPOTHESES[name]
    if spec["engine"] == EVENTS:
        mine = ex.simulate_events(
            planned.picks, planned.dues, ctx.quote, first, last, spec["top"]
        )
        population = ex.simulate_events(
            planned.population, planned.dues, ctx.quote, first, last, None
        )
        reference = ex.simulate_events(
            planned.reference, planned.dues, ctx.quote, first, last, None
        )
        return mine, population, reference
    mine = pr.simulate(planned.picks, ctx.quote, first, last, spec["hold"], spec["top"])
    population = pr.simulate(
        planned.population, ctx.quote, first, last, spec["hold"], None
    )
    return mine, population, None


def run_portfolio(
    ctx: Context,
    db: Path,
    name: str,
    segment: str,
    coverage_only: bool = False,
    min_t: float = MIN_T,
) -> dict[str, Any]:
    """G1 or G2 on one segment: its numbers, verdict and private parts."""

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
    result["means"] = {
        key: overlap_summary(by_year) for key, by_year in planned.means.items()
    }
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
    if planned.rebalances:
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


def _overlap_title(key: str) -> tuple[str, str]:
    """(the other list, the registration's point) of an overlap key."""

    return key.split("_")[1], "G1 第 7 點" if key.startswith("G1") else "G2 第 6 點"


def _mean_text(key: str, value: float | None) -> str:
    if key == "revenue":
        return lib.num(value, 0)
    if key == "negative":
        return _pct(value, 1)
    return lib.num(value, 3)


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
    return {"next_event": "持有到下一個事件日"}.get(hold, f"K＝{hold}")


def coverage_lines(name: str, coverage: dict[str, Any]) -> list[str]:
    """G1 each event day and by year, G2 by year."""

    if name == "G1":
        head = ["事件日", "對應的季", "母體檔次", "有 `nonop_q` 的檔數", "名單檔數",
                "最新一季不是對應的那一季", "`report_format` 不是 `general`", "欄位缺",
                "（比例）", "rev(q) ≤ 0", "母體裡的下市、轉板股", "（其中缺所需欄位）",
                "nonop(q)＝0", "nonop(q) < 0"]  # fmt: skip
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
                    f"| {e['delisted']:,} | {e['delisted_missing']:,} | {e['zero']:,} "
                    f"| {e['negative']:,} |"
                )
        lines += ["", "依年：", "",
                  "| 年 | 事件日 | 母體檔次 | 有 `nonop_q` 的檔次 | 母體裡的下市、轉板股檔次 "
                  "| 其中缺 `nonop_q` 所需欄位 | nonop(q)＝0 的檔次 | nonop(q) < 0 的檔次 |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]  # fmt: skip
        for year, row in sorted(coverage.items()):
            lines.append(
                f"| {year} | {row['days']:,} | {row['members']:,} | {row.get('valued', 0):,} "
                f"| {row.get('delisted', 0):,} | {row.get('delisted_missing', 0):,} "
                f"| {row.get('zero', 0):,} | {row.get('negative', 0):,} |"
            )
        return lines
    head = ["年", "日數", "母體檔次", "有 `coskew_240` 的檔次", "缺值",
            "（加權指數缺值）", "（大盤欄退化）", "（不足 241 根）", "（有交易日沒有日線）",
            "（停牌）", "（收盤缺值或 ≤ 0）", "（Σεⱼ² 不是 > 0）",
            "加權指數缺值的訊號日", "大盤欄退化的訊號日"]  # fmt: skip
    lines = [
        "| " + " | ".join(head) + " |",
        "| --- | " + " | ".join("---:" for _ in head[1:]) + " |",
    ]
    for year, row in sorted(coverage.items()):
        members, missing = row["members"], row.get("missing", {})
        lines.append(
            f"| {year} | {row['days']:,} | {members:,} | {row.get('valued', 0):,} "
            f"| {_share(missing.get('coskew_240', 0), members)} "
            + " ".join(
                f"| {_share(missing.get(key, 0), members)}"
                for key in (
                    "index",
                    "degenerate",
                    "short",
                    "gap",
                    "suspended",
                    "price",
                    "flat",
                )
            )  # fmt: skip
            + f" | {row.get('index_days', 0):,} | {row.get('degenerate_days', 0):,} |"
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
        f"# {name} {segment}（round18_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- {OVERLAP_NOTE['summary_only']}",
    ]
    if name == "G1":
        lines += [OVERLAP_NOTE["G1_survivor"], f"- {OVERLAP_NOTE['G1_proxy']}"]
    lines += [
        "",
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


def _rebalance_lines(rebalances: list[dict[str, Any]]) -> list[str]:
    lines = [
        "## 每次調倉（G1 第 7 點，只列出、不判定）",
        "",
        "名單檔數是取前 20 名之後；投入比例是買進那天收盤時，部位占淨值的比例；"
        + OVERLAP_NOTE["G1_listed"]
        + "。",
        "",
        "| 事件日 | 對應的季 | 母體檔次 | 有 `nonop_q` | 名單檔數 | 投入比例 | 平均單季營收（千元） "
        "| 業外為負的比例 | 和 P2 的重疊 | 和 N2 的重疊 | 和 A1 的重疊 | 和 X4 的重疊 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *(
            f"| {e['signal_date']} | {e['quarter']} | {e['members']:,} | {e['valued']:,} "
            f"| {e['names']:,} | {_pct(e.get('invested'), 1)} "
            f"| {lib.num(e['revenue_mean'], 0)} | {_pct(e['negative_share'], 1)} "
            f"| {_pct(e['p2_overlap'], 1)} | {_pct(e['n2_overlap'], 1)} "
            f"| {_pct(e['a1_overlap'], 1)} | {_pct(e['x4_overlap'], 1)} |"
            for e in rebalances
        ),
    ]
    invested = [e["invested"] for e in rebalances if e.get("invested") is not None]
    names = [e["names"] for e in rebalances]
    lines += [
        "",
        f"平均每次調倉 {lib.num(statistics.fmean(names), 1)} 檔、平均投入比例 "
        f"{_pct(statistics.fmean(invested) if invested else None, 1)}。",
        "",
    ]
    return lines


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
        lines += [
            f"| 絕對報酬（扣成本，判定） | {a['days']} | {_pct(a['mean'], 3)} "
            f"| {_pct(None if a['mean'] is None else a['mean'] * pr.TRADING_DAYS)} | — |",
            "",
            f"門檻：t ≥ {threshold(result.get('min_t', MIN_T))}。",
            "",
        ]
        if "reference" in e:
            lines += [OVERLAP_NOTE[f"{name}_reference"] + "。", ""]
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
    if result.get("rebalances"):
        lines += _rebalance_lines(result["rebalances"])
    for key, summary in (result.get("overlap") or {}).items():
        other, point = _overlap_title(key)
        lines += _yearly_lines(
            f"## 和 {other} 的重疊（{point}）",
            OVERLAP_NOTE[key],
            summary,
            lambda v: _pct(v, 1),
        )
    point = "G1 第 7 點" if name == "G1" else "G2 第 6 點"
    note = OVERLAP_NOTE["G1_listed" if name == "G1" else "G2_listed"]
    for key, summary in (result.get("means") or {}).items():
        lines += _yearly_lines(
            f"## {FEATURE_LABELS[key]}（{point}，只列出、不判定）",
            note,
            summary,
            lambda v, key=key: _mean_text(key, v),
        )
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
    for key, part in (result.get("means") or {}).items():
        row[f"mean_{key}"] = {k: part[k] for k in ("days", "mean")}
    if "reference" in (result.get("excess") or {}):
        row["reference_excess"] = result["excess"]["reference"]
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
        f"# 新策略探索 第 {report['round']} 輪 {stage}（round18_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「第十八輪：G1、G2」）：{DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        _threshold_line(segment, report["min_t"]),
        "- 引擎：G1 是 X7 的事件日帳戶（`explore_research.simulate_events`），G2 是組合引擎"
        "（`portfolio_research.simulate`，K＝60）；日數是有淨值的交易日",
        f"- G1、G2：{OVERLAP_NOTE['summary_only']}",
        OVERLAP_NOTE["G1_survivor"],
        f"- G1 的{OVERLAP_NOTE['G1_proxy']}",
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
                f"- {name} 每次調倉的名單檔數：平均 {lib.num(row['names'], 1)}"
            )
        for other in (P2, N2, A1, X4, Z2, Z3):
            part = row.get(f"overlap_{other.lower()}")
            if part:
                listed.append(
                    f"- {name} 和 {other} 的重疊：平均 {_pct(part['mean'], 1)}（{part['days']:,} 個訊號日）"
                )
        for key in ("revenue", "negative", "skew_240", "beta_240"):
            part = row.get(f"mean_{key}")
            if part:
                listed.append(
                    f"- {name} {FEATURE_LABELS[key]}：{_mean_text(key, part['mean'])}"
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
    f"- G1：{DEGENERATE['G1']}。每個事件日一列，缺值的原因依序判（最新一季、格式、欄位缺、rev(q) ≤ 0），"
    "每檔只算第一個；「母體裡的下市、轉板股」是 `status` 為 `delisted`／`transferred` 的母體檔次，"
    "「其中缺所需欄位」是對照基準去掉的檔次；「nonop(q)＝0」「nonop(q) < 0」只數有 `nonop_q` 的檔；"
    "`p2_order`、`n2_order`、`a1_order`、`x4_order` 是同一個 T 算 P2、N2、A1、X4 名單的時間"
    "（X4 的 `_rank` 另記它自己的特徵），`--coverage-only` 不算重疊比例、平均單季營收與業外為負的比例，"
    "各段的 `summary.md` 才列",
    f"- G2：{DEGENERATE['G2']}。依年一列，缺值的原因依序判（加權指數缺值、大盤欄退化、不足 241 根、"
    "有交易日沒有日線、停牌、收盤缺值或 ≤ 0、Σεⱼ² 不是 > 0），每檔只算第一個；「加權指數缺值的訊號日」"
    "「大盤欄退化的訊號日」是那一天母體每一檔都缺值的訊號日數；`z2_order`、`z3_order` 是同一個 T 算 Z2、Z3 "
    "名單的時間，`--coverage-only` 不算重疊比例與平均 `skew_240`、`beta_240`，各段的 `summary.md` 才列",
    "- 各假設用自己的訊號日（起日寫在各段標題）",
)


def columns_lines(columns: dict[str, Any]) -> list[str]:
    lines = [
        "| 季 | `report_format` | 列數 | "
        + " | ".join(f"`{n}`" for n in (NONOP, REVENUE))
        + " |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for quarter, kinds in columns.items():
        for kind, part in kinds.items():
            lines.append(
                f"| {quarter} | {kind} | {part['rows']:,} | "
                + " | ".join(f"{part['fields'].get(n, 0):,}" for n in (NONOP, REVENUE))
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
        f"# 新策略探索 第 {body['round']} 輪 G1、G2 資料覆蓋（探索段，不含報酬）",
        "",
        f"- round18_research 第 {VERSION} 版；定義雜湊 `{body['definitions_sha256']}`",
        f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}，"
        f"alembic `{body['copy']['alembic']}`",
        f"- 重現：`{body['command']}`",
        f"- 耗時 {body.get('elapsed_seconds', 0):.0f} 秒（載入 {body.get('load_seconds', 0):.0f} 秒，"
        f"其中 panel {load_seconds.get('panel', 0):.0f} 秒、季報其他欄位（G1）與標的狀態 "
        f"{load_seconds.get('statements', 0):.0f} 秒、重疊用的季報（P2、N2、A1）與配股 "
        f"{load_seconds.get('lists', 0):.0f} 秒；"
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
            "## G1：2013 年各季的欄名（`fundamental_snapshots.data_json`，期末在 2013 年的列）",
            "",
            *columns_lines(body["columns_2013"]),
            "",
        ]
    lines += [
        "2013 年同一個會計科目用了別的欄名，或有明顯斷點、缺值比例有異常的年份或欄位，或某個事件日一檔都沒有值，"
        "或 G2 有大盤欄退化的訊號日時，先在工具單提問、不跑探索段。",
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
    parser = argparse.ArgumentParser(prog="round18_research.py", description=__doc__)
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
        help="exploration (required, not with --coverage-only): G1, G2 or "
        "both, comma separated; each runs once per tool version",
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
    command = "python tools/research/round18_research.py " + " ".join(argv)
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
