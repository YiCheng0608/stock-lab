"""Round 23 of the new-strategy exploration: AF1, AF2 (#1107).

docs/spec/evidence.md 第二十三輪：AF1、AF2 and 第二十三輪實作釋義: the
hypotheses were registered (commit ``eb83fc81``, #1105, decision 7217240485)
before anyone ran a tool on the backfilled history.  Nothing here is a
command-line option: a change of a definition is a new code.

They are not in ``explore_research.HYPOTHESES``, ``trade_research.HYPOTHESES``
nor ``round4_research`` .. ``round22_research``: their ``definitions_sha256``
hash the whole table, so adding them would make the validation refuse the
exploration reports already run.  Both trade on X7's event-day account
(``explore_research.simulate_events``) on K2's event days
(``round14_research.quarter_events``); the population, the loading
(``explore_research.load_context``), ``explore_judge``, the gate, the ledgers
and the ledger's write check are imported.  AF2's latest quarter is P2's
reading (``round15_research._known``) on ``quarterly_statements``.  The
overlaps take X4 (``round14_research.x4_names``: ``explore_research._rank``)
and AB1 (``round20_research.op_margin_4q`` on ``round15_research.
load_statements``, ranked as ``round20_research.plan_ab1``) on the same T, and
``round10_research``'s ``overlap_share``／``overlap_summary``.  New here are
only ``pb`` (``valuation_daily``), ``accruals_4q`` (``quarterly_statements``),
AF1's financial count and the listed numbers.

Each event day T (after its close, only T's data and before):

- AF1: ``pb`` (the official price-to-book ratio of T's own row) small first,
  20, held to the next event day.
- AF2: ``accruals_4q`` (the last 4 quarters' operating income less their
  operating cash flow, over the mean of this quarter's and the same quarter
  a year before's total assets) small first, 20, held to the next event day.

``explore_research.explore_judge`` judges with t ≥ 2 on the exploration and
the fixed Bonferroni t ≥ 3.399 (74 hypotheses) on the validation.  Before the
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
from types import SimpleNamespace
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
DESIGN = "1107"
TOOL = "round23_research"
REGISTRATION_COMMIT = "eb83fc81"
DECISION = (
    "https://github.com/YiCheng0608/stock-lab/issues/1105#issuecomment-7217240485"
)
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
SEGMENTS = dict(ex.SEGMENTS)
MIN_SEGMENT_DAYS = dict(ex.MIN_SEGMENT_DAYS)
MIN_T = ex.MIN_T  # the exploration's t ≥ 2
# docs 第二十三輪 門檻: 1 − Φ(z) = 0.025 ÷ 74, z = 3.3993, 3.399 to the 3rd
# decimal; fixed, not computed when run.
VALIDATION_MIN_T = 3.399
ROUND = 23
ROUND_SIZE = 2
# X1～X8, S1～S3, R1～R2, M1～M2, C1～C4, V1～V3, W1～W4, Y1～Y4, Z1～Z4, B1～B3,
# F1～F4, L1～L4, J1～J4, U1～U3, K1～K3, P1～P3, N1～N3, A1～A3, G1～G2, D1～D2,
# AB1～AB2, AD1, AE1, AF1～AF2
CUMULATIVE = 74
# Every segment reads the copy from its start, as round10_research ..
# round22_research: AF2 reads q − 4, X4 the EPS quarters before T.
LOAD_FROM = ex.LOAD_FROM
LOAD_RULE = "every segment from LOAD_FROM"
MIN_LOTS = lib.DEFAULT_MIN_LOTS
RAW_DIR_NAME = ex.RAW_DIR_NAME
POPULATION = pr.POPULATION
TAIEX = pr.TAIEX
EVENTS = "events"
HIGH, LOW = r5.HIGH, r5.LOW

# 共同 排序與同分、選股與調倉
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
# 第 8 點／第 9 點: the members later delisted or transferred, listed by year
DELISTED_STATUSES = ("delisted", "transferred")

# AF1 (第 1～6 點, 實作釋義「AF1 的 T 日列」)
PB_COLUMN = "pb_ratio"
PB_SOURCES = {"TWSE": "twse_bwibbu_d", "TPEx": "tpex_pe_qry_date"}
PB_DAY_RULE = (
    "the valuation_daily row of the instrument's own exchange source whose "
    "data_as_of is T; none on T: missing, no earlier day looked for; only "
    "data_as_of <= T read"
)
PB_MIN = 0.0  # pb ≤ 0: missing
PB_MISSING = "reasons in order: no row on T, pb NULL, pb <= 0; each ranked last"
AF1_START = date(2013, 5, 15)
X4 = "X4"  # the list AF1 overlaps with
# 實作釋義「金融業檔數只列出」 (only the listed column)
FINANCIAL_CODES = ("basi", "fh", "ins", "bd")
FINANCIAL_FORMATS = ("bank", "holding", "securities", "insurance_legacy", "insurance")
FORMAT_SOURCE = "mops_t163sb04"
FINANCIAL_RULE = (
    "the latest quarter with announcement_date <= T: the quarterly_statements "
    "row's industry code in FINANCIAL_CODES, or without such a row (or code) "
    "the fundamental_snapshots mops_t163sb04 row's report_format in "
    "FINANCIAL_FORMATS; neither: unknown"
)

# AF2 (第 1～5 點, 實作釋義)
STATEMENT_TABLE = "quarterly_statements"
STATEMENT_SOURCE = "mops_tifrs_zip"
OPERATING = "operating_income_ytd"
CFO = "cfo_ytd"
ASSETS = "total_assets"
INDUSTRY_KEY = "industry_code"  # in data_json
LAG = 4  # q − 4
LATEST_RULE = (
    "the latest quarter known on T (announcement_date <= T, the largest "
    "period_end of every row, round15_research._known) must be the deadline's "
    "quarter"
)
TTM_RULE = (
    "TTM(x) = x(q) when q is a Q4, else x(q) + x(the year before's Q4) - "
    "x(q-4), each YTD; q-4 and the year before's Q4 by period_end among the "
    "rows known on T"
)
ACCRUALS = (
    "(TTM(operating_income_ytd) - TTM(cfo_ytd)) / ((total_assets(q) + "
    "total_assets(q-4)) / 2); 0 and negative values by value"
)
ASSETS_MIN = 0.0  # the mean total assets ≤ 0: missing
ACCRUALS_MISSING = (
    "reasons in order: stale, financial (q's industry code in "
    "FINANCIAL_CODES), rows (a needed quarter not known), fields (a needed "
    "column NULL, not_applicable too), assets (the mean <= 0)"
)
AF2_START = date(2014, 5, 15)
AB1 = "AB1"  # the list AF2 overlaps with
# The foreign issuers' Q2 (第 10 點, #1083 決定 7217263563): only counted in the
# coverage, the rows #1101's rule moved to August 31
FOREIGN_KEY = "deadline_rule"
FOREIGN_RULE = "foreign_issuer_q2_two_months"

# The registration (docs 第二十三輪：AF1、AF2), word for word.  ``start`` as
# ``explore_research``.
HYPOTHESES: dict[str, dict[str, Any]] = {
    "AF1": {
        "engine": EVENTS,
        "direction": "基本面：價值",
        "label": "每季法定期限的事件日，T 日股價淨值比 `pb`（`valuation_daily`）小者先取 20 檔",
        "rule": "quarterly",
        "keys": (("pb", LOW),),
        "short": SHORT_RULE,
        "top": 20,
        "hold": "next_event",
        "start": ("date", AF1_START),
    },
    "AF2": {
        "engine": EVENTS,
        "direction": "基本面：盈餘品質",
        "label": "每季法定期限的事件日，`accruals_4q`（近 4 季營業利益減近 4 季營業現金流，"
        "除以本季與去年同季總資產的平均）小者先取 20 檔",
        "rule": "quarterly",
        "keys": (("accruals_4q", LOW),),
        "short": SHORT_RULE,
        "top": 20,
        "hold": "next_event",
        "start": ("date", AF2_START),
    },
}
OTHER_COMPARISONS = ex.OTHER_COMPARISONS
REASONS = dict(ex.REASONS)
LIMITS = {
    "AF1": "定義照摘要與索引頁，未讀全文；台股的文獻正反都有：Chui & Wei (1998) 的轉述是台股的 B/M 沒有解釋力，"
    "Ko, Lin, Su & Chang (2014) 的摘要寫「台股廣泛記載沒有價值溢酬」，Hsu, Lee, Chang & Fung (2015) 的摘要寫台股用 "
    "E/P、D/P 當價值指標比 B/M 好；上櫃舊年份的分母會落後，財報重編不回溯（是當時的值，不會偷看未來），存託憑證沒有值；"
    "上市的分母是「最近一季每股參考淨值」，換季跟著各家公告，期限當天仍有少數公司是舊一季，上櫃頁註沒寫用哪一期；"
    "金融業不排除，銀行的淨值比和一般業的意義不同，名單可能偏向金融股，看每個事件日名單裡金融業的檔數；"
    "和 X4 的關係：X4 是 EPS 收益率（E/P）大者先，登記時 X4 的狀態已知（前瞻觀察），AF1 不是 X4 的變形、也不是看它挑的，"
    "分母不同（E/P 用盈餘，B/M 用帳面淨值，虧損公司在 X4 排最後，在 AF1 照樣有值），看和 X4 的重疊比例",
    "AF2": "定義照摘要與索引頁，未讀全文；分子是營業利益，不是 Sloan 的盈餘，差在業外損益（利息、投資損益等）；"
    "整包存的是更正後的值：同一份季報更正過，更正後的值在原期限就被看到，同 `t163sb04` 的限制；"
    "外國發行人的 Q2：事件日用一般公司的期限（8/14），外國發行人 2021 年起的 Q2 期限是 8/31，`announcement_date` 照它算時，"
    "8/14 那天最新一季不是事件日對應的那一季，那一季它們不成訊號，只是少收、不會偷看；"
    "金融業的格式都缺值，名單只會是一般、證券以外的格式，「其他」格式沒有營業利益（例如 2207），也缺值；"
    "和 AB1 的關係：AB1 是 4 季營業利益率的水準，登記時 AB1 的狀態已知（沒有通過），AF2 不是它的變形、也不是看它挑的，"
    "AF2 比的是營業利益裡現金占多少，不是營業利益多大，看和 AB1 的重疊比例；重提 #982 的應計項目，"
    "當時不列的理由是資料的理由，#1078／#1083 補的就是資產負債表與現金流量表；和 P2 無關：P2 用毛利率的變化",
}
# The degenerate cases as the code judges them (第二十三輪實作釋義; PR #913
# review: the docs, coverage.md and summary.md say the same words, a test
# reads the docs' tool section for them).
DEGENERATE = {
    "AF1": "T 沒有 `valuation_daily` 列（以 (標的, `data_as_of`) 對 T，只讀這一檔交易所自己的來源："
    "上市 `twse_bwibbu_d`、上櫃 `tpex_pe_qry_date`；T 那天沒有列不往前找）、股價淨值比是 NULL 或 ≤ 0 時缺值、排最後；"
    "缺值的原因依序判：沒有列、NULL、≤ 0，每檔只算第一個；"
    "有值的不足 20 檔時以缺值的依雜湊補，母體不足 20 檔時餘額留現金",
    "AF2": "最新一季（`announcement_date` ≤ T 的 `quarterly_statements` 列中期末最晚的一季）不是事件日對應的那一季、"
    "q 那一列 `data_json` 的產業碼是 `basi`／`fh`／`ins`／`bd`、q、q−4 與（q 不是 Q4 時）前一年 Q4 任一季沒有 "
    "`announcement_date` ≤ T 的列、要用的欄是 NULL（含 `not_applicable`；q 的 `operating_income_ytd`、`cfo_ytd`、"
    "`total_assets`，q−4 的 `total_assets`，q 不是 Q4 時另加 q−4 與前一年 Q4 的 `operating_income_ytd`、`cfo_ytd`），"
    "或平均總資產 ≤ 0 時缺值、排最後；缺值的原因依序判：最新一季、金融業的格式、要用的季沒有列、要用的欄是 NULL、"
    "平均總資產 ≤ 0，每檔只算第一個；TTM(營業利益)＝TTM(營業現金流) 時 `accruals_4q`＝0，照值排序，不是缺值；"
    "`accruals_4q` 可以是負的（營業現金流大於營業利益），照值排序；"
    "有值的不足 20 檔時以缺值的依雜湊補，母體不足 20 檔時餘額留現金",
}
OVERLAP_NOTE = {
    "summary_only": "定義照摘要與索引頁，未讀全文",
    "AF1_X4": 'AF1 與 X4（`explore_research` 第 2 版的 `HYPOTHESES["X4"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|AF1 的名單 ∩ X4 的前 20 名| ÷ AF1 當天的名單檔數；AF1 或 X4 當天沒有名單的事件日不計。只列出、不判定",
    "AF2_AB1": 'AF2 與 AB1（`round20_research` 第 1 版的 `HYPOTHESES["AB1"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|AF2 的名單 ∩ AB1 的前 20 名| ÷ AF2 當天的名單檔數；AF2 或 AB1 當天沒有名單的事件日不計。只列出、不判定",
    "AF1_financial": "名單裡金融業的檔數：名單裡每一檔在 T 時看 `announcement_date` ≤ T 的最新一季，"
    "`quarterly_statements` 列的產業碼是 `basi`／`fh`／`ins`／`bd`，或沒有這種列（或列上沒有產業碼）、"
    "`fundamental_snapshots` 的 `mops_t163sb04` 列的 `report_format` 是 `bank`、`holding`、`securities`、"
    "`insurance_legacy`、`insurance` 之一，就記金融業；兩者都認不出的記「未知」。只列出、不影響名單",
    "delisted": "依年（T 的年）列母體裡 `status` 是 `delisted`／`transferred` 的檔次（每個事件日數一次）與其中特徵缺值的檔次，"
    "另列其他檔次（現存股）的缺值比例對照。只列出、不判定",
    "listed": "每次調倉的檔數與平均投入比例：名單檔數是取前 20 名之後，投入比例是買進那天收盤時部位占淨值的比例",
    "AF1_survivor": "- 存活者偏差（AF1）：兩個淨值比端點依當天的掛牌名單產生，含之後下市的公司；2008、2013、2018 抽樣日，"
    "上市之後下市的全部有值，上櫃 2008 年 5 檔 `N/A`、2013 年 1 檔沒有列。偏差小，不另列對照基準；"
    "依年的下市、轉板股缺值檔次在 `AF1/summary.md` 的「依年的下市、轉板股」",
    "AF2_survivor": "- 存活者偏差（AF2）：`quarterly_statements` 含之後下市、轉板的公司（季底起 670 天內有日線就寫），"
    "剩下的缺口是日線跨過季底、但整包沒有那一季的下市股，2013～2024 年 16 個公司年，偏差方向事先定不出來。"
    "不另列對照基準；依年的下市、轉板股缺值檔次在 `AF2/summary.md` 的「依年的下市、轉板股」",
}
FEATURE_LABELS = {"pb": "股價淨值比", "accruals_4q": "應計項目"}
PICK_FIELDS = {
    "AF1": ("pb", "financial"),
    "AF2": ("quarter", "accruals_4q", "operating_4q", "cfo_4q", "mean_assets"),
}
COVERAGE_KEYS = {
    "AF1": ("no_row", "null", "nonpositive"),
    "AF2": ("stale", "financial", "rows", "fields", "assets"),
    "financial": ("financial", "other", "unknown"),
}


def definitions() -> dict[str, Any]:
    return {
        "version": VERSION,
        "design": DESIGN,
        "hypotheses": HYPOTHESES,
        "order": ORDER,
        "short": SHORT_RULE,
        "sale": SALE,
        "delisted_statuses": list(DELISTED_STATUSES),
        # the event days (round14_research.quarter_events, K2's) and the
        # account (explore_research.simulate_events, X7's), with their tools
        "deadlines": [r14.DEADLINES, r14.EVENT_DAY_RULE],
        "quarter_events": [r14.VERSION, r14.definitions_sha256()],
        "simulate_events": [ex.VERSION, ex.definitions_sha256()],
        "features": {
            "pb": {
                "column": PB_COLUMN,
                "sources": PB_SOURCES,
                "day": PB_DAY_RULE,
                "min": PB_MIN,
                "missing": PB_MISSING,
                "financial": [
                    FINANCIAL_CODES,
                    FINANCIAL_FORMATS,
                    FORMAT_SOURCE,
                    FINANCIAL_RULE,
                    INDUSTRY_KEY,
                ],
            },
            "accruals_4q": {
                "table": [STATEMENT_TABLE, STATEMENT_SOURCE],
                "fields": [OPERATING, CFO, ASSETS],
                "industry": [INDUSTRY_KEY, FINANCIAL_CODES],
                "lag": LAG,
                "latest": LATEST_RULE,
                # P2's reading of the latest quarter (round15_research._known)
                "known": [r15.VERSION, r15.definitions_sha256()],
                "ttm": TTM_RULE,
                "formula": ACCRUALS,
                "assets_min": ASSETS_MIN,
                "missing": ACCRUALS_MISSING,
                "foreign": [FOREIGN_KEY, FOREIGN_RULE],
            },
            "overlaps": {
                X4: [ex.HYPOTHESES[X4], ex.VERSION, ex.definitions_sha256()],
                AB1: [r20.HYPOTHESES[AB1], r20.VERSION, r20.definitions_sha256()],
                "share": [r10.VERSION, r10.definitions_sha256()],
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
    AF1's column, sources, T's row and missing rules, AF2's table, fields,
    latest quarter, 4-quarter sums, mean assets, financial codes and missing
    rules, N, the order, the event days and the account with their tools'
    hashes, the overlaps' lists, the segments, the costs).  A changed tool
    needs a new exploration report before a validation."""

    text = json.dumps(definitions(), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- reading ----------------------------------------------------------------------


@dataclass(frozen=True)
class QuarterStatement:
    """One ``quarterly_statements`` row for AF2 (thousand NTD, YTD for the
    flows), None when the column is NULL."""

    announced: date
    period_end: date
    industry: str | None
    operating: float | None
    cfo: float | None
    assets: float | None
    foreign: bool = False  # data_json names #1101's foreign issuers' Q2 rule


@dataclass(frozen=True)
class FormatRow:
    """A ``fundamental_snapshots`` ``mops_t163sb04`` row's ``report_format``."""

    announced: date
    period_end: date
    report_format: str | None


def has_table(db: Path, name: str) -> bool:
    con = lib.connect_read_only(db)
    try:
        return (
            con.execute(
                "select 1 from sqlite_master where type = 'table' and name = ?", (name,)
            ).fetchone()
            is not None
        )
    finally:
        con.close()


def _data(text: Any) -> dict[str, Any]:
    if isinstance(text, dict):
        return text
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def load_valuations(
    db: Path, panel: lib.Panel, days: list[date]
) -> dict[int, dict[date, float | None]]:
    """AF1 第 1～3 點: the rows whose ``data_as_of`` is one of ``days`` (the
    event days), each instrument's own exchange source only; only those
    days are read (T's row, no earlier day)."""

    out: dict[int, dict[date, float | None]] = defaultdict(dict)
    if not days or not has_table(db, "valuation_daily"):
        return {}
    con = lib.connect_read_only(db)
    try:
        for start in range(0, len(days), 500):
            chunk = [day.isoformat() for day in days[start : start + 500]]
            marks = ", ".join("?" for _ in chunk)
            rows = con.execute(
                f"select instrument_id, data_as_of, {PB_COLUMN}, source "
                f"from valuation_daily where data_as_of in ({marks}) "
                "order by instrument_id, data_as_of, trading_date",
                chunk,
            )
            for instrument_id, as_of, value, source in rows:
                if instrument_id not in panel.series:
                    continue
                exchange = panel.symbols.get(instrument_id, ("", "", ""))[0]
                if PB_SOURCES.get(exchange) != source:
                    continue  # the other exchange's source: not mixed
                out[instrument_id][date.fromisoformat(as_of)] = (
                    None if value is None else float(value)
                )
    finally:
        con.close()
    return dict(out)


def load_quarter_statements(
    db: Path, series: dict[int, lib.Series], end: date
) -> dict[int, list[QuarterStatement]]:
    """AF2: every ``quarterly_statements`` row with ``announcement_date`` ≤
    ``end`` (none after it read), by announcement; no table, none."""

    out: dict[int, list[QuarterStatement]] = defaultdict(list)
    if not has_table(db, STATEMENT_TABLE):
        return {}
    con = lib.connect_read_only(db)
    try:
        rows = con.execute(
            f"select instrument_id, announcement_date, period_end, {OPERATING}, "
            f"{CFO}, {ASSETS}, data_json from {STATEMENT_TABLE} "
            "where source = ? and announcement_date is not null "
            "and announcement_date <= ? order by announcement_date, period_end",
            (STATEMENT_SOURCE, end.isoformat()),
        )
        for instrument_id, announced, period_end, op, cfo, assets, text in rows:
            if instrument_id not in series:
                continue
            data = _data(text)
            out[instrument_id].append(
                QuarterStatement(
                    date.fromisoformat(announced),
                    date.fromisoformat(period_end),
                    data.get(INDUSTRY_KEY),
                    None if op is None else float(op),
                    None if cfo is None else float(cfo),
                    None if assets is None else float(assets),
                    data.get(FOREIGN_KEY) == FOREIGN_RULE,
                )
            )
    finally:
        con.close()
    return dict(out)


def load_formats(
    db: Path, series: dict[int, lib.Series], end: date
) -> dict[int, list[FormatRow]]:
    """AF1 第 8 點 (the financial count only): each ``mops_t163sb04`` row's
    ``report_format`` with ``announcement_date`` ≤ ``end``, by announcement."""

    out: dict[int, list[FormatRow]] = defaultdict(list)
    con = lib.connect_read_only(db)
    try:
        rows = con.execute(
            "select instrument_id, announcement_date, period_end, "
            "json_extract(data_json, '$.report_format') from fundamental_snapshots "
            "where source = ? and announcement_date is not null "
            "and announcement_date <= ? order by announcement_date, period_end",
            (FORMAT_SOURCE, end.isoformat()),
        )
        for instrument_id, announced, period_end, kind in rows:
            if instrument_id in series:
                out[instrument_id].append(
                    FormatRow(
                        date.fromisoformat(announced),
                        date.fromisoformat(period_end),
                        kind,
                    )
                )
    finally:
        con.close()
    return dict(out)


@dataclass
class Context:
    """``explore_research``'s context (the market, the quotes, the EPS
    quarters X4 reads), AF1's ``pb`` on the event days and the report
    formats, AF2's statements, AB1's (``round15_research.load_statements``)
    and the instruments' status.  One panel."""

    base: ex.Context
    valuations: dict[int, dict[date, float | None]] = field(default_factory=dict)
    statements: dict[int, list[QuarterStatement]] = field(default_factory=dict)
    formats: dict[int, list[FormatRow]] = field(default_factory=dict)
    ab1_statements: dict[int, list[r15.Statement]] = field(default_factory=dict)
    statuses: dict[int, str] = field(default_factory=dict)
    tables: dict[str, bool] = field(default_factory=dict)
    seconds: Counter = field(default_factory=Counter)
    load_seconds: dict[str, float] = field(default_factory=dict)

    @property
    def ab1(self) -> SimpleNamespace:
        """What ``round20_research.op_margin_4q`` reads (its statements only)."""

        return SimpleNamespace(statements=self.ab1_statements)

    @property
    def market(self) -> pr.Market:
        return self.base.market

    @property
    def panel(self) -> lib.Panel:
        return self.base.market.panel

    def quote(self, instrument_id: int, s: int) -> pr.Quote | None:
        return self.base.quote(instrument_id, s)


def load(db: Path, start: date, end: date, raw_dir: Path) -> Context:
    """The panel, the turnovers, the EPS quarters, ``pb`` on the event days,
    the statements, the report formats and the statuses to ``end``; nothing
    after ``end`` is read."""

    started = time.monotonic()
    base = ex.load_context(db, start, end, raw_dir)
    panel = base.market.panel
    panel_seconds = time.monotonic() - started
    t0 = time.monotonic()
    days = [panel.sessions[at] for at, _q in r14.quarter_events(panel.sessions)]
    valuations = load_valuations(db, panel, [day for day in days if day <= end])
    valuation_seconds = time.monotonic() - t0
    t0 = time.monotonic()
    statements = load_quarter_statements(db, panel.series, end)
    formats = load_formats(db, panel.series, end)
    statement_seconds = time.monotonic() - t0
    t0 = time.monotonic()
    ab1_statements = r15.load_statements(db, panel.series, end)
    statuses = r15.load_statuses(db)
    return Context(
        base,
        valuations,
        statements,
        formats,
        ab1_statements,
        statuses,
        tables={
            name: has_table(db, name) for name in ("valuation_daily", STATEMENT_TABLE)
        },
        load_seconds={
            "panel": panel_seconds,
            "valuations": valuation_seconds,
            "statements": statement_seconds,
            "ab1_statements": time.monotonic() - t0,
        },
    )


# --- AF1: pb ----------------------------------------------------------------------


@dataclass(frozen=True)
class Pb:
    value: float | None
    reason: str | None = None  # "no_row", "null", "nonpositive" or None


def pb(ctx: Context, item: lib.Series, day: date) -> Pb:
    """AF1 第 2、3 點 on T (``day``): T's own row, no earlier day."""

    rows = ctx.valuations.get(item.instrument_id, {})
    if day not in rows:
        return Pb(None, "no_row")
    value = rows[day]
    if value is None:
        return Pb(None, "null")
    if value <= PB_MIN:
        return Pb(None, "nonpositive")
    return Pb(value)


_known = r15._known
_quarter_back = r15._quarter_back


def financial_kind(ctx: Context, item: lib.Series, day: date) -> str:
    """AF1 第 8 點 (實作釋義「金融業檔數只列出」): "financial", "other" or
    "unknown" on T."""

    known = _known(ctx.statements.get(item.instrument_id, []), day)
    if known:
        code = known[max(known)].industry
        if code is not None:
            return "financial" if code in FINANCIAL_CODES else "other"
    formats = _known(ctx.formats.get(item.instrument_id, []), day)
    if formats:
        kind = formats[max(formats)].report_format
        if kind is not None:
            return "financial" if kind in FINANCIAL_FORMATS else "other"
    return "unknown"


# --- AF2: accruals_4q -------------------------------------------------------------


@dataclass(frozen=True)
class Accruals:
    value: float | None
    # "stale", "financial", "rows", "fields", "assets" or None
    reason: str | None = None
    operating: float | None = None  # TTM(operating income)
    cfo: float | None = None  # TTM(operating cash flow)
    assets: float | None = None  # the mean total assets


def _year_before_q4(quarter: date) -> date:
    return date(quarter.year - 1, 12, 31)


def _ttm(now: float, q4: float | None, back: float | None, annual: bool) -> float:
    return now if annual else math.fsum((now, q4, -back))


def accruals_4q(ctx: Context, item: lib.Series, day: date, quarter: date) -> Accruals:
    """AF2 第 2～5 點 on T (``day``) for the deadline's ``quarter``."""

    known = _known(ctx.statements.get(item.instrument_id, []), day)
    if not known or max(known) != quarter:
        return Accruals(None, "stale")
    now = known[quarter]
    if now.industry in FINANCIAL_CODES:
        return Accruals(None, "financial")
    annual = quarter.month == 12
    back = known.get(_quarter_back(quarter, LAG))
    q4 = None if annual else known.get(_year_before_q4(quarter))
    if back is None or (not annual and q4 is None):
        return Accruals(None, "rows")
    needed = [now.operating, now.cfo, now.assets, back.assets]
    if not annual:
        needed += [back.operating, back.cfo, q4.operating, q4.cfo]
    if any(value is None for value in needed):
        return Accruals(None, "fields")
    operating = _ttm(
        now.operating, None if annual else q4.operating, back.operating, annual
    )
    cfo = _ttm(now.cfo, None if annual else q4.cfo, back.cfo, annual)
    assets = (now.assets + back.assets) / 2
    if assets <= ASSETS_MIN:
        return Accruals(None, "assets", operating, cfo, assets)
    return Accruals((operating - cfo) / assets, None, operating, cfo, assets)


def foreign_late(ctx: Context, item: lib.Series, day: date, quarter: date) -> bool:
    """AF2 (``--coverage-only``): the deadline's ``quarter`` has a row under
    the foreign issuers' Q2 rule announced after T (read only to count)."""

    return any(
        row.period_end == quarter and row.foreign and row.announced > day
        for row in ctx.statements.get(item.instrument_id, [])
    )


# --- the plans --------------------------------------------------------------------


def segment_window(
    sessions: list[date], segment: str, spec: dict[str, Any]
) -> tuple[int, int] | None:
    """(first, last) index of the sessions with an equity value, or None: the
    session after the first event day in the segment (as X7's)."""

    first_day, last_day = SEGMENTS[segment]
    last = bisect_left(sessions, last_day + timedelta(days=1)) - 1
    if first_day is None:
        base = ex.start_index(sessions, spec["start"])
        if base is None:
            return None
    else:
        base = max(bisect_left(sessions, first_day), 1) - 1
    found = [at for at, _q in r14.quarter_events(sessions) if at >= base]
    if not found:
        return None
    first = found[0] + 1
    return (first, last) if first <= last else None


@dataclass
class Plan:
    picks: dict[int, list[int]] = field(default_factory=dict)
    population: dict[int, list[int]] = field(default_factory=dict)
    dues: dict[int, int] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    signal_days: int = 0
    event_days: int = 0
    overlap: dict[str, dict[str, list[float]]] = field(default_factory=dict)
    rebalances: list[dict[str, Any]] = field(default_factory=list)


_year = r15._year
_add = r15._add
_pick_row = r15._pick_row


def _timed(ctx: Context, key: str, run: Callable[[], Any]) -> Any:
    t0 = time.perf_counter()
    try:
        return run()
    finally:
        ctx.seconds[key] += time.perf_counter() - t0


def x4_names(ctx: Context, day, members) -> set[int]:
    """X4's list (``round14_research.x4_names``: ``explore_research._rank``,
    ``explore_research`` 第 2 版的定義; it times ``x4_order``)."""

    return r14.x4_names(ctx, day, members)


def ab1_names(ctx: Context, day, members, quarter) -> set[int]:
    """AB1's list on ``day`` (``round20_research`` 第 1 版的定義:
    ``op_margin_4q`` on AB1's own statements, ranked as
    ``round20_research.plan_ab1``)."""

    def run() -> set[int]:
        spec = r20.HYPOTHESES[AB1]
        keys = tuple(spec["keys"])
        ab1 = ctx.ab1
        rows = sorted(
            (
                r5.order_key(
                    {keys[0][0]: r20.op_margin_4q(ab1, item, day, quarter).value},
                    keys,
                    pr.tie_break(day, item.instrument_id),
                ),
                item.instrument_id,
            )
            for item, _k in members
        )
        return {instrument_id for _key, instrument_id in rows[: spec["top"]]}

    return _timed(ctx, "ab1_order", run)


def _gone(ctx: Context, members, missing: set[int]) -> tuple[int, int]:
    """(the delisted or transferred members, those with the feature missing)."""

    gone = gone_missing = 0
    for item, _k in members:
        if ctx.statuses.get(item.instrument_id) in DELISTED_STATUSES:
            gone += 1
            gone_missing += item.instrument_id in missing
    return gone, gone_missing


def plan_events(ctx: Context, name: str, first: int, last: int, keep_rows=True) -> Plan:
    """AF1 第 1～4、8 點 or AF2 第 1～6、9 點: the event days of the segment,
    the feature in T's population small first, 20, held to the next event
    day (X7); the listed counts on the same days."""

    spec = HYPOTHESES[name]
    panel = ctx.panel
    sessions = panel.sessions
    other = "AF1_X4" if name == "AF1" else "AF2_AB1"
    out = Plan(overlap={other: {}})
    top = spec["top"]
    keys = tuple(spec["keys"])
    every = r14.quarter_events(sessions)
    following = {at: nxt for (at, _q), (nxt, _n) in zip(every, every[1:])}
    feature = keys[0][0]
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
            got = (
                pb(ctx, item, day)
                if name == "AF1"
                else accruals_4q(ctx, item, day, quarter)
            )
            reasons[got.reason] += 1
            rows.append((item, got, pr.tie_break(day, item.instrument_id)))
        ctx.seconds[feature] += time.perf_counter() - t0
        rows.sort(key=lambda row: r5.order_key({feature: row[1].value}, keys, row[2]))
        chosen = rows[:top]
        missing = {item.instrument_id for item, got, _t in rows if got.value is None}
        gone, gone_missing = _gone(ctx, members, missing)
        event = {
            "signal_date": day.isoformat(),
            "quarter": quarter.isoformat(),
            "members": len(members),
            "valued": reasons[None],
            **{key: reasons[key] for key in COVERAGE_KEYS[name]},
            "names": len(chosen),
            "named_valued": sum(1 for _i, got, _t in chosen if got.value is not None),
            "delisted": gone,
            "delisted_missing": gone_missing,
        }
        kinds: dict[int, str] = {}
        if name == "AF1":
            kinds = _timed(
                ctx,
                "financial",
                lambda: {
                    item.instrument_id: financial_kind(ctx, item, day)
                    for item, _g, _t in chosen
                },
            )
            event.update(
                {kind: sum(1 for v in kinds.values() if v == kind)
                 for kind in COVERAGE_KEYS["financial"]}
            )  # fmt: skip
        else:
            event["foreign_stale"] = _timed(
                ctx,
                "foreign",
                lambda: sum(
                    1
                    for item, got, _t in rows
                    if got.reason == "stale" and foreign_late(ctx, item, day, quarter)
                ),
            )
        for key in ("valued", "delisted", "delisted_missing"):
            _add(year, key, event[key])
        year.setdefault("events", []).append(event)
        others = (
            x4_names(ctx, day, members)
            if name == "AF1"
            else ab1_names(ctx, day, members, quarter)
        )  # timed in the coverage too
        if not keep_rows:
            continue
        names = [item.instrument_id for item, _g, _t in chosen]
        share = r10.overlap_share(names, others)
        if share is not None:
            out.overlap[other].setdefault(str(day.year), []).append(share)
        out.rebalances.append({**event, "overlap": share})
        out.picks[at + 1] = names
        out.population[at + 1] = [item.instrument_id for item, _ in members]
        due = following.get(at)
        out.dues[at + 1] = due if due is not None and due <= last else last + 1
        for place, (item, got, tie) in enumerate(chosen, 1):
            values = (
                {"pb": got.value, "financial": kinds[item.instrument_id]}
                if name == "AF1"
                else {"quarter": quarter.isoformat(), "accruals_4q": got.value,
                      "operating_4q": got.operating, "cfo_4q": got.cfo,
                      "mean_assets": got.assets}
            )  # fmt: skip
            out.rows.append(_pick_row(ctx, day, place, item.instrument_id, values, tie))
    return out


overlap_share = r10.overlap_share
overlap_summary = r10.overlap_summary
_window_facts = r5._window_facts


def delisted_by_year(coverage: dict[str, Any]) -> dict[str, Any]:
    """第 8／9 點: by year the members, those missing, the delisted or
    transferred ones and those of them missing, and the others' share."""

    out = {}
    for year, row in sorted(coverage.items()):
        members = row["members"]
        missing = members - row.get("valued", 0)
        gone, gone_missing = row.get("delisted", 0), row.get("delisted_missing", 0)
        rest = members - gone
        out[year] = {
            "events": row["days"],
            "members": members,
            "missing": missing,
            "delisted": gone,
            "delisted_missing": gone_missing,
            "delisted_share": gone_missing / gone if gone else None,
            "others_share": (missing - gone_missing) / rest if rest else None,
        }
    return out


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
) -> tuple[pr.Simulation, pr.Simulation]:
    """(the hypothesis, the population): X7's account, the same event days."""

    spec = HYPOTHESES[name]
    mine = ex.simulate_events(
        planned.picks, planned.dues, ctx.quote, first, last, spec["top"]
    )
    population = ex.simulate_events(
        planned.population, planned.dues, ctx.quote, first, last, None
    )
    return mine, population


def run_portfolio(
    ctx: Context,
    db: Path,
    name: str,
    segment: str,
    coverage_only: bool = False,
    min_t: float = MIN_T,
) -> dict[str, Any]:
    """AF1 or AF2 on one segment: its numbers, verdict and private parts."""

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
    planned = plan_events(ctx, name, first, last, keep_rows=not coverage_only)
    result["window"]["signal_days"] = planned.signal_days
    result["window"]["event_days"] = planned.event_days
    result["coverage"] = planned.coverage
    result["delisted"] = delisted_by_year(planned.coverage)
    result["seconds"] = {"plan": time.monotonic() - started, **ctx.seconds}
    if coverage_only:
        return result
    result["overlap"] = {
        key: overlap_summary(by_year) for key, by_year in planned.overlap.items()
    }
    mine, population = engines(ctx, name, planned, first, last)
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


def _point(name: str) -> str:
    return "AF1 第 8 點" if name == "AF1" else "AF2 第 9 點"


def coverage_lines(name: str, coverage: dict[str, Any]) -> list[str]:
    """Each event day, then the delisted or transferred members by year."""

    if name == "AF1":
        head = ["事件日", "母體檔次", "有 `pb` 的檔數", "名單檔數", "（其中有值）",
                "沒有列", "NULL", "≤ 0", "缺值比例", "名單裡金融業", "（其他）", "（未知）",
                "母體裡的下市、轉板股", "（其中缺值）"]  # fmt: skip
    else:
        head = ["事件日", "對應的季", "母體檔次", "有 `accruals_4q` 的檔數", "名單檔數",
                "（其中有值）", "最新一季不是對應的那一季", "金融業的格式", "要用的季沒有列",
                "要用的欄是 NULL", "平均總資產 ≤ 0", "缺值比例", "外國發行人 Q2（8/14）",
                "母體裡的下市、轉板股", "（其中缺值）"]  # fmt: skip
    lines = [
        "| " + " | ".join(head) + " |",
        "| --- | "
        + ("--- | " if name == "AF2" else "")
        + " | ".join("---:" for _ in head[(2 if name == "AF2" else 1) :])
        + " |",
    ]
    for _year_, row in sorted(coverage.items()):
        for e in row.get("events", []):
            missing = e["members"] - e["valued"]
            if name == "AF1":
                cells = [e["signal_date"], f"{e['members']:,}", f"{e['valued']:,}",
                         f"{e['names']:,}", f"{e['named_valued']:,}", f"{e['no_row']:,}",
                         f"{e['null']:,}", f"{e['nonpositive']:,}",
                         _share(missing, e["members"]), f"{e['financial']:,}",
                         f"{e['other']:,}", f"{e['unknown']:,}", f"{e['delisted']:,}",
                         f"{e['delisted_missing']:,}"]  # fmt: skip
            else:
                foreign = (
                    f"{e['foreign_stale']:,}" if e["quarter"][5:7] == "06" else "—"
                )
                cells = [e["signal_date"], e["quarter"], f"{e['members']:,}",
                         f"{e['valued']:,}", f"{e['names']:,}", f"{e['named_valued']:,}",
                         f"{e['stale']:,}", f"{e['financial']:,}", f"{e['rows']:,}",
                         f"{e['fields']:,}", f"{e['assets']:,}",
                         _share(missing, e["members"]), foreign, f"{e['delisted']:,}",
                         f"{e['delisted_missing']:,}"]  # fmt: skip
            lines.append("| " + " | ".join(cells) + " |")
    return lines


def delisted_lines(name: str, rows: dict[str, Any]) -> list[str]:
    feature = HYPOTHESES[name]["keys"][0][0]
    lines = [
        f"| 年 | 事件日 | 母體檔次 | `{feature}` 缺值的檔次 | 母體裡的下市、轉板股檔次 "
        "| 其中缺值的檔次 | 下市、轉板股的缺值比例 | 其他檔次的缺值比例 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for year, row in rows.items():
        lines.append(
            f"| {year} | {row['events']:,} | {row['members']:,} | {row['missing']:,} "
            f"| {row['delisted']:,} | {row['delisted_missing']:,} "
            f"| {_pct(row['delisted_share'], 1)} | {_pct(row['others_share'], 1)} |"
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
        f"# {name} {segment}（round23_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- {OVERLAP_NOTE['summary_only']}",
        OVERLAP_NOTE[f"{name}_survivor"],
        "",
        f"- 判定：**{verdict}**"
        + (f"（{REASONS[result['reason']]}）" if result["reason"] else ""),
        f"- 假設：{spec['direction']}；{spec['label']}；N＝{spec['top']}、持有到下一個事件日",
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


def _rebalance_lines(name: str, rebalances: list[dict[str, Any]]) -> list[str]:
    other = "X4" if name == "AF1" else "AB1"
    note = OVERLAP_NOTE["listed"]
    if name == "AF1":
        note += "；" + OVERLAP_NOTE["AF1_financial"]
    lines = [
        f"## 每次調倉（{_point(name)}，只列出、不判定）",
        "",
        note + "。",
        "",
    ]
    if name == "AF1":
        lines += [
            "| 事件日 | 母體檔次 | 有 `pb` | 名單檔數 | 投入比例 | 名單裡金融業 | （未知） | 和 X4 的重疊 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            *(
                f"| {e['signal_date']} | {e['members']:,} | {e['valued']:,} | {e['names']:,} "
                f"| {_pct(e.get('invested'), 1)} | {e['financial']:,} | {e['unknown']:,} "
                f"| {_pct(e['overlap'], 1)} |"
                for e in rebalances
            ),
        ]
    else:
        lines += [
            "| 事件日 | 對應的季 | 母體檔次 | 有 `accruals_4q` | 名單檔數 | 投入比例 | 和 AB1 的重疊 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
            *(
                f"| {e['signal_date']} | {e['quarter']} | {e['members']:,} | {e['valued']:,} "
                f"| {e['names']:,} | {_pct(e.get('invested'), 1)} | {_pct(e['overlap'], 1)} |"
                for e in rebalances
            ),
        ]
    invested = [e["invested"] for e in rebalances if e.get("invested") is not None]
    names = [e["names"] for e in rebalances]
    lines += [
        "",
        f"平均每次調倉 {lib.num(statistics.fmean(names), 1)} 檔、平均投入比例 "
        f"{_pct(statistics.fmean(invested) if invested else None, 1)}"
        f"（和 {other} 的重疊見下）。",
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
            f"（{w['won']:,}／{w['bought']:,}，期末未賣 {w['unsold']:,}，"
            f"期末未賣的比例 {_pct(result.get('unsold_share'), 1)}）。",
            f"成交計數：買進 {counts.get('bought', 0):,}、漲停買不到 "
            f"{counts.get('limit_up', 0):,}、不可交易 {counts.get('not_tradable', 0):,}、"
            f"跌停順延 {counts.get('limit_down', 0):,}、停牌／缺日線順延 "
            f"{counts.get('sale_held', 0):,}、期末未賣 {counts.get('unsold', 0):,}。",
            "",
        ]
    if result.get("rebalances"):
        lines += _rebalance_lines(name, result["rebalances"])
    for key, title in (
        ("AF1_X4", "## 和 X4 的重疊（AF1 第 8 點）"),
        ("AF2_AB1", "## 和 AB1 的重疊（AF2 第 9 點）"),
    ):
        if key in result.get("overlap", {}):
            lines += _yearly_lines(
                title, OVERLAP_NOTE[key], result["overlap"][key], lambda v: _pct(v, 1)
            )
    if result.get("delisted"):
        lines += [
            f"## 依年的下市、轉板股（{_point(name)}，只列出、不判定）",
            "",
            OVERLAP_NOTE["delisted"] + "。",
            "",
            *delisted_lines(name, result["delisted"]),
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
    if result.get("rebalances"):
        events = result["rebalances"]
        row["names"] = statistics.fmean(e["names"] for e in events)
        if result["hypothesis"] == "AF1":
            row["financial"] = statistics.fmean(e["financial"] for e in events)
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
        f"# 新策略探索 第 {report['round']} 輪 {stage}（round23_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- {OVERLAP_NOTE['summary_only']}",
        OVERLAP_NOTE["AF1_survivor"],
        OVERLAP_NOTE["AF2_survivor"],
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「第二十三輪：AF1、AF2」）：{DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        _threshold_line(segment, report["min_t"]),
        "- 引擎：AF1、AF2 都是 X7 的事件日帳戶（`explore_research.simulate_events`），"
        "事件日是 `round14_research.quarter_events`；日數是有淨值的交易日",
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
        if row.get("names") is not None:
            listed.append(
                f"- {name} 每次調倉的名單檔數：平均 {lib.num(row['names'], 1)}"
            )
        if row.get("financial") is not None:
            listed.append(
                f"- {name} 名單裡金融業的檔數：平均 {lib.num(row['financial'], 1)}"
            )
        for key, label in (("overlap_x4", "X4"), ("overlap_ab1", "AB1")):
            part = row.get(key)
            if part:
                listed.append(
                    f"- {name} 和 {label} 的重疊：平均 {_pct(part['mean'], 1)}（{part['days']:,} 個訊號日）"
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
    "- 缺值比例的分母是母體檔次（每個事件日的母體）；每個事件日都數；不跑模擬、不算報酬",
    f"- AF1：{DEGENERATE['AF1']}。每個事件日一列；「名單裡金融業」「（其他）」「（未知）」是取前 20 名之後的名單"
    "（只列出、不影響名單）；`x4_order` 是同一個 T 算 X4 名單的時間，`--coverage-only` 不算重疊比例，各段的 "
    "`summary.md` 才列",
    f"- AF2：{DEGENERATE['AF2']}。每個事件日一列；「外國發行人 Q2（8/14）」是 8/14 事件日因最新一季不是對應的那一季缺值、"
    "而那一季的列照外國發行人的 Q2 期限（`data_json` 的 `deadline_rule`）在 T 之後才可得的檔數，只數、不讀它的值；"
    "`ab1_order` 是同一個 T 算 AB1 名單的時間，`--coverage-only` 不算重疊比例，各段的 `summary.md` 才列",
    "- 「依年的下市、轉板股」：" + OVERLAP_NOTE["delisted"],
    "- 各假設用自己的事件日（起日寫在各段標題）",
)


def coverage_markdown(body: dict[str, Any]) -> str:
    load_seconds = body.get("load_seconds_parts", {})
    tables = body.get("tables", {})
    lines = [
        f"# 新策略探索 第 {body['round']} 輪 AF1、AF2 資料覆蓋（探索段，不含報酬）",
        "",
        f"- round23_research 第 {VERSION} 版；定義雜湊 `{body['definitions_sha256']}`",
        f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}，"
        f"alembic `{body['copy']['alembic']}`",
        "- 表："
        + "、".join(
            f"`{name}` {'有' if present else '沒有（全部缺值）'}"
            for name, present in tables.items()
        ),
        f"- 重現：`{body['command']}`",
        f"- 耗時 {body.get('elapsed_seconds', 0):.0f} 秒（載入 {body.get('load_seconds', 0):.0f} 秒，"
        f"其中 panel {load_seconds.get('panel', 0):.0f} 秒、事件日的 `pb`（AF1）"
        f"{load_seconds.get('valuations', 0):.0f} 秒、`quarterly_statements` 與 `t163sb04` 的格式 "
        f"{load_seconds.get('statements', 0):.0f} 秒、AB1 的季報與標的狀態 "
        f"{load_seconds.get('ab1_statements', 0):.0f} 秒），"
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
            "依年的下市、轉板股：",
            "",
            *delisted_lines(name, row["delisted"]),
            "",
        ]
    lines += [
        "有明顯斷點或缺值比例異常的年份或事件日、某個事件日能進名單的檔數（有值的檔數）不到 20，"
        "或下市、轉板股的缺值比例明顯高於現存股時，先在工具單提問、不跑探索段。",
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
        "engines": {"explore_research": "simulate_events"},
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
            "delisted": result.get("delisted", {}),
            "seconds": result.get("seconds", {}),
        }
        hypotheses[name] = row
        progress(f"{name} coverage ({row['seconds'].get('plan', 0.0):.1f}s)")
    body = {
        **public(header),
        "coverage_only": True,
        "tables": ctx.tables,
        "hypotheses": hypotheses,
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


def table_problems(db: Path) -> list[str]:
    """The exploration and the validation need both tables: without one
    every value would be missing, not a run of the registration."""

    return [
        f"{db} has no {name} table: run the exploration after its data is in "
        "(docs/spec/evidence.md 第二十三輪「需要的資料」)"
        for name in ("valuation_daily", STATEMENT_TABLE)
        if not has_table(db, name)
    ]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="round23_research.py", description=__doc__)
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
        help="exploration (required, not with --coverage-only): AF1, AF2 or one "
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
    command = "python tools/research/round23_research.py " + " ".join(argv)
    progress = lambda text: print(text, file=sys.stderr, flush=True)  # noqa: E731
    if args.segment == EXPLORATION:
        if args.coverage_only:
            line = run_coverage(db, Path(args.out), command, progress=progress)
        else:
            problems = table_problems(db)
            if problems:
                print(json.dumps({"refused": problems}, ensure_ascii=False))
                return 2
            line = run_exploration(
                db, Path(args.out), names, command, progress=progress
            )
    else:
        problems, names, _report = ex.validation_problems(
            db, *gate, HYPOTHESES, DESIGN, definitions_sha256()
        )
        if not problems:
            problems = table_problems(db)
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
