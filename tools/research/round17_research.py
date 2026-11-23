"""Round 17 of the new-strategy exploration: A1～A3 (#1008).

docs/spec/evidence.md 第十七輪：A1～A3 and 第十七輪實作釋義: the hypotheses
were registered (commit ``cbcfd002``, #1006, decision 7109307360) before
anyone ran a tool on the backfilled history.  Nothing here is a command-line
option: a change of a definition is a new code.

They are not in ``explore_research.HYPOTHESES``, ``trade_research.HYPOTHESES``
nor ``round4_research`` .. ``round16_research``: their ``definitions_sha256``
hash the whole table, so adding them would make the validation refuse the
exploration reports already run.  A1 and A2 trade on X7's event-day account
(``explore_research.simulate_events``), A3 on ``portfolio_research.simulate``
(K 20); the population, the loading (``explore_research.load_context``),
``explore_judge``, the gate and the ledgers are imported.  A1's event days
are ``round14_research.quarter_events``, its latest quarter
``round15_research._known`` (as P2 and N2), its rows read by
``round16_research``'s reader; A2's event days ``explore_research.
event_days`` (X7's) and its months ``feature_evidence._revenues_known``.  The
overlaps take X8 (``explore_research._plan_buyback``), X7 and X4
(``explore_research._rank``, ``round14_research.x4_names``), V1
(``round5_research.rank``) and Y2 (``round7_research.rank``) on the same T,
and ``round10_research``'s ``overlap_share``／``overlap_summary``.  New here
are only ``net_issue`` (with its own reading of ``fundamental_snapshots.
data_json`` and ``corporate_actions.stock_dividend_ratio``),
``sales_growth_36``, ``vov_240``, A1's and A2's reference populations and the
listed numbers.

Each signal date T (after its close, only T's data and before):

- A1: on the 4 statutory deadlines, ``net_issue`` (the log change of the
  shares implied by the year's cumulative net income over its cumulative
  EPS, against the same quarter a year before, the stock dividends between
  taken out) small first, 20, held to the next event day (X7).
- A2: on the 10th of every month (X7's event days), ``sales_growth_36`` (the
  last 12 months' revenue over the 12 months 36 months before, less 1) small
  first, 20, held to the next event day.
- A3: ``vov_240`` (the coefficient of variation of the 12 standard
  deviations of 20 returns each, of the last 240 returns) small first, 20,
  K 20.

``explore_research.explore_judge`` judges with t ≥ 2 on the exploration and
the fixed Bonferroni t ≥ 3.359 (64 hypotheses) on the validation.  Before the
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
from array import array
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
import portfolio_research as pr  # noqa: E402
import round5_research as r5  # noqa: E402
import round7_research as r7  # noqa: E402
import round10_research as r10  # noqa: E402
import round14_research as r14  # noqa: E402
import round15_research as r15  # noqa: E402
import round16_research as r16  # noqa: E402

VERSION = 1
DESIGN = "1008"
TOOL = "round17_research"
REGISTRATION_COMMIT = "cbcfd002"
DECISION = (
    "https://github.com/YiCheng0608/stock-lab/issues/1006#issuecomment-7109307360"
)
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
SEGMENTS = dict(ex.SEGMENTS)
MIN_SEGMENT_DAYS = dict(ex.MIN_SEGMENT_DAYS)
MIN_T = ex.MIN_T  # the exploration's t ≥ 2
# docs 第十七輪 門檻: 1 − Φ(z) = 0.025 ÷ 64, z = 3.3594, 3.359 to the 3rd decimal;
# fixed, not computed when run.
VALIDATION_MIN_T = 3.359
ROUND = 17
ROUND_SIZE = 3
# X1～X8, S1～S3, R1～R2, M1～M2, C1～C4, V1～V3, W1～W4, Y1～Y4, Z1～Z4, B1～B3,
# F1～F4, L1～L4, J1～J4, U1～U3, K1～K3, P1～P3, N1～N3, A1～A3
CUMULATIVE = 64
# Every segment reads the copy from its start, as round10_research ..
# round16_research: A2 reads 48 months before T, A3 241 bars.
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

# A1 (第 1～5 點)
NET = "淨利（淨損）歸屬於母公司業主"
EPS = "基本每股盈餘（元）"
REPORT_FORMAT = "general"
THOUSANDS = 1000.0  # NET is in thousands
LAG = 4  # q against q − 4
EPS_MIN = 0.5  # |cumulative EPS| < 0.5 on q or q − 4: missing
SHARES_MIN = 0.0  # sh ≤ 0: missing
SHARES = (
    "sh(x) = cumulative NET of x * THOUSANDS / cumulative EPS of x (the year's "
    "cumulative figures, not single quarters)"
)
LATEST_RULE = (
    "the latest quarter known on T (announcement_date <= T, the largest "
    "period_end, an EPS null row too) must be the deadline's quarter"
)
NUMBER_RULE = "worker.sources.parse_number on the data_json cell"
STATEMENT_RULE = (
    "fundamental_snapshots rows with announcement_date <= T (an EPS null row "
    "too), round15_research._known: by period_end, the later announcement; a "
    "row of q or q-4 not known or a field null is missing; a row of another "
    "report_format is missing, a null report_format a missing field"
)
DIVIDEND_RULE = (
    "g = product of (1 + stock_dividend_ratio) over the corporate_actions rows "
    "with announcement_date(q-4) < action_date <= announcement_date(q) and the "
    "ratio not null and > 0, each row once; a null ratio: no stock dividend; "
    "none: g = 1"
)
NET_ISSUE = (
    "ln(sh(q) / (sh(q-4) * g)); the ratio exactly 1: 0; reasons in order: "
    "stale, format, fields, eps, shares"
)
A1_REFERENCE = (
    "T's population less the delisted or transferred instruments missing a "
    "field net_issue needs on T (a row of q or q-4 of the deadline's quarter "
    "not known, or NET or EPS null; not the stale quarter, the report_format, "
    "the EPS floor nor sh <= 0); the same account and event days"
)
A1_START = date(2014, 5, 15)
X8 = "X8"  # the list A1 overlaps with

# A2 (第 1～3 點)
RECENT_MONTHS = (0, 11)  # R1: m − 11 .. m
BASE_MONTHS = (36, 47)  # R0: m − 47 .. m − 36
GROWTH = "R1 / R0 - 1, R1 and R0 the sums of the 12 monthly revenues"
LATEST_MONTH_RULE = (
    "m: the latest revenue_month with a revenue announced by T "
    "(feature_evidence._revenues_known) must be the month before T's"
)
BASE_MIN = 0.0  # R0 ≤ 0: missing
MONTHS_MISSING = "a month of the 24 without a revenue announced by T: missing"
MONTHLY_EVENT_RULE = (
    "explore_research.event_days: the first session from the 10th of every month (X7's)"
)
A2_REFERENCE = (
    "T's population less the delisted or transferred instruments missing a "
    "month sales_growth_36 needs on T (with m the month before T's, a month "
    "of m-11..m or m-47..m-36 without a revenue announced by T; not whether "
    "the latest month is m nor R0 <= 0); the same account and event days"
)
A2_START = date(2017, 1, 10)
X7, X4 = "X7", "X4"  # the lists A2 overlaps with

# A3 (第 1～3 點)
VOV_RETURNS = 240  # 241 closes at − 240 .. at
VOV_PARTS = 12
VOV_PART_RETURNS = 20
PART_DDOF = 1  # s_j: the sample standard deviation, 19 degrees of freedom
VOV_DDOF = 1  # the s_j's: 11 degrees of freedom
VOV_RULE = (
    "r = close[k] / close[k-1] - 1 (adjusted), k = at-239 .. at, in 12 parts "
    "of 20 from the oldest; vov_240 = the sample standard deviation of the 12 "
    "s_j / their mean; the 12 s_j equal: 0"
)
VOV_MISSING = (
    "at < 240; a suspended bar in at-240..at; a close (at-240..at) missing or "
    "<= 0; the mean of the s_j 0: missing, ranked last, not dropped"
)
A3_ANCHOR = date(2007, 12, 3)  # the OTC bars the tools read
V1, Y2 = "V1", "Y2"  # the lists A3 overlaps with

# The registration (docs 第十七輪：A1～A3), word for word.  ``start`` as
# ``explore_research``.
HYPOTHESES: dict[str, dict[str, Any]] = {
    "A1": {
        "engine": EVENTS,
        "direction": "基本面：淨增發",
        "label": "每季法定期限的事件日，`net_issue`（季報推算的累計加權平均股數，本季對去年同季的對數變化，"
        "扣掉期間的配股）小者先取 20 檔",
        "rule": "quarterly",
        "keys": (("net_issue", LOW),),
        "short": SHORT_RULE,
        "top": 20,
        "hold": "next_event",
        "start": ("date", A1_START),
    },
    "A2": {
        "engine": EVENTS,
        "direction": "基本面：長期營收成長的反向",
        "label": "每月 10 日的事件日，`sales_growth_36`（最近 12 個月營收合計 ÷ 36 個月前那 12 個月的合計 − 1）"
        "小者先取 20 檔",
        "rule": "monthly",
        "keys": (("sales_growth_36", LOW),),
        "short": SHORT_RULE,
        "top": 20,
        "hold": "next_event",
        "start": ("date", A2_START),
    },
    "A3": {
        "engine": PORTFOLIO,
        "direction": "投資人偏好：波動的波動",
        "label": "`vov_240`（近 240 根日報酬切成 12 段、每段 20 根的標準差，12 個標準差的變異係數）小者先",
        "rule": "daily",
        "keys": (("vov_240", LOW),),
        "short": SHORT_RULE,
        "top": 20,
        "hold": 20,
        "start": ("session", A3_ANCHOR, 1 + VOV_RETURNS),
    },
}
OTHER_COMPARISONS = ex.OTHER_COMPARISONS
REASONS = dict(ex.REASONS)
LIMITS = {
    "A1": "股數是由淨利 ÷ EPS 推算的，不是發行股數，EPS 只到小數兩位，0.5 元時捨入的相對誤差最多 1%；"
    "EPS 下限會排除盈虧都很小的公司，名單偏向有盈虧規模的公司；配股因子 g 的窗口用 `announcement_date`"
    "（法定期限），IAS 33 追溯調整的時點與這個窗口可能差在財報發布前後的配股，不另調；彌補虧損的減資"
    "（無償減資）會讓股數變少、方向和假設相同，研究 DB 沒有減資比例，不調；存活者偏差：下市股的季報是 "
    "XBRL 整包補的，只寫了 EPS，沒有淨利，期間內下市公司的季幾乎都缺值、排最後，偏差方向對假設有利，"
    "大小同 P2、N2；金融業等格式與法定期限不同的公司不會有值；和 X8（董事會決議買回庫藏股）方向相同，"
    "登記時 X8 的狀態已知，看重疊比例；和 N2、P2 同一張表、同一份存活者偏差，但用的是淨利 ÷ EPS 的比值",
    "A2": "定義照論文摘要與二手整理，未讀全文；LSV 用的是 5 年營收成長的加權名次，本輪改成 3 年的 12 個月合計，"
    "是資料限制下的近似；存活者偏差：155 檔下市股缺月份，缺值排最後，這些公司多半成長差、之後報酬差，"
    "偏差方向對假設有利；探索段只有約 730 日、36 次調倉，檢定力比其他兩個低；和 X3、X4、X7、S 系列"
    "（近 1 個月的年增、方向是成長高的）、W2（價格的長期反轉）有關，X7 是最近 1 個月營收創 12 個月新高的條件，"
    "A2 不是它的反面，登記時 X3、X4、X7、W2 的狀態已知，看重疊比例與名單的平均 `revenue_yoy`",
    "A3": "定義照論文摘要，未讀全文；文獻用的是選擇權的隱含波動，台股個股選擇權少、研究 DB 沒有，"
    "改用實現波動的分段變化，是近似；和 V1（`vol_60` 的水準）、Y2（成交金額的變異係數）、J1 有關，"
    "變異係數已除以平均、不看水準，但仍相關，登記時 V1、Y2、J1 的狀態已知，看重疊比例與名單的平均 `vol_60`",
}
# The degenerate cases as the code judges them (第十七輪實作釋義; PR #913
# review: the docs, coverage.md and summary.md say the same words, a test
# reads the docs' tool section for them).
DEGENERATE = {
    "A1": "最新一季（`announcement_date` ≤ T 的季報列中期末最晚的一季，EPS 是 null 的列也算）不是事件日對應的那一季、"
    "q、q−4 任一列的 `report_format` 不是 `general`（`report_format` 是 null 的列算欄位缺）、"
    "任一列不在或 `淨利（淨損）歸屬於母公司業主`、`基本每股盈餘（元）` 任一欄缺、"
    "q 或 q−4 的累計 EPS 絕對值 < 0.5 元（虧損 0.5 元以上照算），或 sh(q)、sh(q−4) ≤ 0 時缺值、排最後；"
    "sh(q)＝sh(q−4) × g 時 `net_issue`＝0，照值排序；有值的不足 20 檔時以缺值的依雜湊補，母體不足 20 檔時餘額留現金",
    "A2": "最新已知月份（`announcement_date` ≤ T、有營收的最新 `revenue_month`）不是 T 的上個月、"
    "m−11…m 與 m−47…m−36 這 24 個月中任一個月沒有 `announcement_date` ≤ T 的營收，或 R0 ≤ 0 時缺值、排最後；"
    "R1＝R0 時 `sales_growth_36`＝0，照值排序；有值的不足 20 檔時以缺值的依雜湊補，母體不足 20 檔時餘額留現金",
    "A3": "at < 240（不足 241 根）、at−240…at 的 241 根中任一根停牌、需要的收盤（at−240…at）缺值或 ≤ 0，"
    "或 12 個 s_j 的平均是 0 時缺值、排最後、不剔除；12 個 s_j 全部相同（平均 > 0）時 `vov_240`＝0，照值排序",
}
OVERLAP_NOTE = {
    "A1_X8": 'A1 與 X8（`explore_research` 第 2 版的 `HYPOTHESES["X8"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|A1 的名單 ∩ X8 當天的名單| ÷ A1 當天的名單檔數；A1 或 X8 當天沒有名單的事件日不計。只列出、不判定",
    "A2_X7": 'A2 與 X7（`explore_research` 第 2 版的 `HYPOTHESES["X7"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|A2 的名單 ∩ X7 的前 20 名| ÷ A2 當天的名單檔數；A2 或 X7 當天沒有名單的事件日不計。只列出、不判定",
    "A2_X4": 'A2 與 X4（`explore_research` 第 2 版的 `HYPOTHESES["X4"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|A2 的名單 ∩ X4 的前 20 名| ÷ A2 當天的名單檔數；A2 或 X4 當天沒有名單的事件日不計。只列出、不判定",
    "A3_V1": 'A3 與 V1（`round5_research` 第 1 版的 `HYPOTHESES["V1"]`，同一個 T 算）每日名單的重疊比例：'
    "|A3 的名單 ∩ V1 的前 20 名| ÷ A3 當天的名單檔數；A3 或 V1 當天沒有名單的日子不計。只列出、不判定",
    "A3_Y2": 'A3 與 Y2（`round7_research` 第 1 版的 `HYPOTHESES["Y2"]`，同一個 T 算）每日名單的重疊比例：'
    "|A3 的名單 ∩ Y2 的前 20 名| ÷ A3 當天的名單檔數；A3 或 Y2 當天沒有名單的日子不計。只列出、不判定",
    "A1_reference": "對照基準：當天母體去掉「缺 `net_issue` 任一所需欄位（事件日對應的那一季的 q、q−4，"
    "任一列不在或兩個欄位任一欄缺；不看是不是最新一季、不看 `report_format`、不看 EPS 下限與 sh ≤ 0）的 "
    "`delisted`／`transferred` 標的」，同一個帳戶規則、同一組事件日；列 A1 對它的超額與 t，只列出、不判定（判定仍只比母體）",
    "A2_reference": "對照基準：當天母體去掉「缺 `sales_growth_36` 任一所需月份（m 取 T 的上個月，m−11…m 與 "
    "m−47…m−36 中任一個月沒有 `announcement_date` ≤ T 的營收；不看最新已知月份是不是上個月、不看 R0 ≤ 0）的 "
    "`delisted`／`transferred` 標的」，同一個帳戶規則、同一組事件日；列 A2 對它的超額與 t，只列出、不判定（判定仍只比母體）",
    "A1_survivor": "- 存活者偏差（A1）：下市股的季報只有 EPS，沒有 `淨利（淨損）歸屬於母公司業主`，期間內下市公司的季幾乎都缺值、"
    "排最後，偏差方向對假設有利。對照基準（母體去掉當天缺欄位的下市、轉板股）的超額與 t "
    "在 `A1/summary.md`「數字」表的「超額（對對照基準，只列出）」列與 `explore.md` 的「只列出、不判定」",
    "A2_survivor": "- 存活者偏差（A2）：155 檔下市股缺月份，缺值排最後，這些公司多半成長差、之後報酬差，偏差方向對假設有利。"
    "對照基準（母體去掉當天缺所需月份的下市、轉板股）的超額與 t "
    "在 `A2/summary.md`「數字」表的「超額（對對照基準，只列出）」列與 `explore.md` 的「只列出、不判定」",
    "A2_summary_only": "定義照摘要與二手整理，未讀全文；LSV 用 5 年營收成長，本輪用 3 年的 12 個月合計，"
    "是資料限制下的近似（月營收 2013-01 起，5 年要到 2018 才起得來，探索段不夠 500 日）",
    "A3_summary_only": "定義照摘要，未讀全文；文獻用選擇權的隱含波動，研究 DB 沒有，改用實現波動的分段變化，是近似",
}
FEATURE_LABELS = {
    "net_issue": "淨增發",
    "sales_growth_36": "3 年營收成長",
    "vov_240": "波動的波動",
}
PICK_FIELDS = {
    "A1": ("quarter", "net_issue", "shares_q", "shares_q4", "g"),
    "A2": ("month", "sales_growth_36", "r1", "r0", "revenue_yoy"),
    "A3": ("vov_240", "vol_60"),
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
        "deadlines": [r14.DEADLINES, r14.EVENT_DAY_RULE],  # A1's events
        "monthly": [MONTHLY_EVENT_RULE, ex.EVENT_DAY],  # A2's events
        "features": {
            "net_issue": {
                "fields": [NET, EPS],
                "report_format": REPORT_FORMAT,
                "thousands": THOUSANDS,
                "lag": LAG,
                "eps_min": EPS_MIN,
                "shares_min": SHARES_MIN,
                "shares": SHARES,
                "latest": LATEST_RULE,
                "number": NUMBER_RULE,
                "statements": STATEMENT_RULE,
                "dividends": DIVIDEND_RULE,
                "formula": NET_ISSUE,
                "reference": A1_REFERENCE,
            },
            "sales_growth_36": {
                "recent": RECENT_MONTHS,
                "base": BASE_MONTHS,
                "formula": GROWTH,
                "latest": LATEST_MONTH_RULE,
                "base_min": BASE_MIN,
                "missing": MONTHS_MISSING,
                "reference": A2_REFERENCE,
                "revenues": features.VERSION,  # _revenues_known, revenue_yoy
            },
            "vov_240": {
                "returns": VOV_RETURNS,
                "parts": VOV_PARTS,
                "part_returns": VOV_PART_RETURNS,
                "part_ddof": PART_DDOF,
                "ddof": VOV_DDOF,
                "rule": VOV_RULE,
                "missing": VOV_MISSING,
            },
            "overlaps": {
                X8: [
                    ex.HYPOTHESES[X8],
                    ex.VERSION,
                    ex.BUYBACK_ALL,
                    ex.BUYBACK_ANY,
                    ex.BUYBACK_NONE,
                    ex.BUYBACK_LOOKBACK,
                ],
                X7: [ex.HYPOTHESES[X7], ex.VERSION],
                X4: [ex.HYPOTHESES[X4], ex.VERSION],
                V1: [r5.HYPOTHESES[V1], r5.VERSION, r5.definitions_sha256()],
                Y2: [r7.HYPOTHESES[Y2], r7.VERSION, r7.definitions_sha256()],
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
    A1's fields, thousands, format, latest quarter, cumulative shares, the
    stock dividends' window, EPS floor, sh ≤ 0 and log, A2's months, latest
    month, R0 ≤ 0 and event days, A3's 240 returns in 12 parts, degrees of
    freedom and missing rules, N and K, the order, the references, the
    overlaps' lists, the segments, the costs).  A changed tool needs a new
    exploration report before a validation."""

    text = json.dumps(definitions(), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- reading ----------------------------------------------------------------------


@dataclass(frozen=True)
class ShareStatement:
    """One ``fundamental_snapshots`` row for A1: the year's cumulative net
    income to the parent (thousands) and basic EPS, None when the cell is
    missing."""

    announced: date
    period_end: date
    report_format: str | None
    net: float | None
    eps: float | None


def share_statement_of(
    announced: str, period_end: str, data: dict[str, Any], parse
) -> ShareStatement:
    def value(name: str) -> float | None:
        return parse(data.get(name)) if name in data else None

    return ShareStatement(
        date.fromisoformat(announced),
        date.fromisoformat(period_end),
        data.get("report_format"),
        value(NET),
        value(EPS),
    )


def load_share_statements(
    db: Path, series: dict[int, lib.Series], end: date
) -> dict[int, list[ShareStatement]]:
    """A1: every row with an ``announcement_date`` ≤ ``end`` (none after it
    read), by announcement; the rows ``round16_research`` reads (its
    ``_rows``／``_data``), A1's two fields."""

    from worker.sources import parse_number

    out: dict[int, list[ShareStatement]] = defaultdict(list)
    for instrument_id, announced, period_end, text in r16._rows(db, end):
        if instrument_id in series:
            out[instrument_id].append(
                share_statement_of(announced, period_end, r16._data(text), parse_number)
            )
    return dict(out)


def load_stock_dividends(
    db: Path, series: dict[int, lib.Series], end: date
) -> dict[int, list[tuple[date, float | None]]]:
    """A1 第 3 點: (action_date, stock_dividend_ratio) of every
    ``corporate_actions`` row to ``end``, by date; the null ratios kept (the
    coverage counts them)."""

    con = lib.connect_read_only(db)
    out: dict[int, list[tuple[date, float | None]]] = defaultdict(list)
    try:
        for instrument_id, day, ratio in con.execute(
            "select instrument_id, action_date, stock_dividend_ratio "
            "from corporate_actions where action_date <= ? "
            "order by instrument_id, action_date, id",
            (end.isoformat(),),
        ):
            if instrument_id in series:
                out[instrument_id].append(
                    (date.fromisoformat(day), None if ratio is None else float(ratio))
                )
    finally:
        con.close()
    return dict(out)


def columns_2013(db: Path) -> dict[str, Any]:
    """A1 第 10 點 (``--coverage-only``): 2013's column names by quarter and
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
            for name in (NET, EPS):
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
    """``explore_research``'s context (the market, the quotes, the turnovers,
    the MOPS list X8 reads), A1's statements and stock dividends, the
    instruments' status and the contexts ``round5_research`` and
    ``round7_research`` rank V1 and Y2 with (the same base).  One panel."""

    base: ex.Context
    statements: dict[int, list[ShareStatement]] = field(default_factory=dict)
    dividends: dict[int, list[tuple[date, float | None]]] = field(default_factory=dict)
    statuses: dict[int, str] = field(default_factory=dict)
    v1: r5.Context | None = None
    y2: r7.Context | None = None
    seconds: Counter = field(default_factory=Counter)
    load_seconds: dict[str, float] = field(default_factory=dict)
    # A3: per instrument, the standard deviation of the 20 returns to each bar
    parts: dict[int, array] = field(default_factory=dict)
    x8: dict[tuple[int, int], dict[int, list[int]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.v1 is None:
            self.v1 = r5.Context(self.base)
        if self.y2 is None:
            self.y2 = r7.Context(self.base)

    @property
    def market(self) -> pr.Market:
        return self.base.market

    @property
    def panel(self) -> lib.Panel:
        return self.base.market.panel

    def quote(self, instrument_id: int, s: int) -> pr.Quote | None:
        return self.base.quote(instrument_id, s)


def load(db: Path, start: date, end: date, raw_dir: Path) -> Context:
    """The panel, the turnovers, the MOPS list, A1's statements and stock
    dividends and the statuses to ``end``; nothing after ``end`` is read."""

    started = time.monotonic()
    base = ex.load_context(db, start, end, raw_dir)
    panel_seconds = time.monotonic() - started
    t0 = time.monotonic()
    series = base.market.panel.series
    statements = load_share_statements(db, series, end)
    statement_seconds = time.monotonic() - t0
    t0 = time.monotonic()
    dividends = load_stock_dividends(db, series, end)
    statuses = r15.load_statuses(db)
    return Context(
        base,
        statements,
        dividends,
        statuses,
        load_seconds={
            "panel": panel_seconds,
            "statements": statement_seconds,
            "dividends": time.monotonic() - t0,
        },
    )


# --- A1: net_issue ----------------------------------------------------------------


_known = r15._known
_quarter_back = r15._quarter_back


@dataclass(frozen=True)
class NetIssue:
    value: float | None
    # "stale", "format", "fields", "eps", "shares" or None
    reason: str | None = None
    shares_q: float | None = None
    shares_q4: float | None = None
    g: float | None = None
    null_dividends: int = 0  # rows in the window with a null ratio


def _shares(row: ShareStatement) -> float:
    return row.net * THOUSANDS / row.eps


def dividend_factor(
    rows: list[tuple[date, float | None]], after: date, until: date
) -> tuple[float, int]:
    """A1 第 3 點, 第十七輪實作釋義 (DIVIDEND_RULE): (g, the rows with a null
    ratio) over the rows with ``after`` < action_date ≤ ``until``."""

    g, nulls = 1.0, 0
    for day, ratio in rows:
        if not after < day <= until:
            continue
        if ratio is None:
            nulls += 1
        elif ratio > 0:
            g *= 1.0 + ratio
    return g, nulls


def net_issue(ctx: Context, item: lib.Series, day: date, quarter: date) -> NetIssue:
    """A1 第 1～5 點 on T (``day``) for the deadline's ``quarter``."""

    known = _known(ctx.statements.get(item.instrument_id, []), day)
    if not known or max(known) != quarter:
        return NetIssue(None, "stale")
    rows = [known.get(quarter), known.get(_quarter_back(quarter, LAG))]
    if any(
        row is not None
        and row.report_format is not None
        and row.report_format != REPORT_FORMAT
        for row in rows
    ):
        return NetIssue(None, "format")
    if any(
        row is None
        or row.report_format != REPORT_FORMAT
        or row.net is None
        or row.eps is None
        for row in rows
    ):
        return NetIssue(None, "fields")
    now, before = rows
    if abs(now.eps) < EPS_MIN or abs(before.eps) < EPS_MIN:
        return NetIssue(None, "eps")
    shares_q, shares_q4 = _shares(now), _shares(before)
    g, nulls = dividend_factor(
        ctx.dividends.get(item.instrument_id, []), before.announced, now.announced
    )
    if shares_q <= SHARES_MIN or shares_q4 <= SHARES_MIN:
        return NetIssue(None, "shares", shares_q, shares_q4, g, nulls)
    ratio = shares_q / (shares_q4 * g)
    value = 0.0 if ratio == 1.0 else math.log(ratio)
    return NetIssue(value, None, shares_q, shares_q4, g, nulls)


def fields_missing(ctx: Context, item: lib.Series, day: date, quarter: date) -> bool:
    """A1 第 5 點 second case on the deadline's ``quarter`` (the reference's
    rule, 第十七輪實作釋義): a row of q or q − 4 not known on T or a field
    missing."""

    known = _known(ctx.statements.get(item.instrument_id, []), day)
    for end in (quarter, _quarter_back(quarter, LAG)):
        row = known.get(end)
        if row is None or row.net is None or row.eps is None:
            return True
    return False


# --- A2: sales_growth_36 ----------------------------------------------------------


def _month_back(year: int, month: int, n: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) - n
    return index // 12, index % 12 + 1


def _previous_month(day: date) -> tuple[int, int]:
    return _month_back(day.year, day.month, 1)


def _months(m: tuple[int, int], span: tuple[int, int]) -> list[tuple[int, int]]:
    return [_month_back(*m, n) for n in range(span[0], span[1] + 1)]


@dataclass(frozen=True)
class Growth:
    value: float | None
    reason: str | None = None  # "stale", "months", "base" or None
    month: str | None = None  # m, YYYY-MM
    r1: float | None = None
    r0: float | None = None


def _revenue_months(item: lib.Series, day: date) -> dict[tuple[int, int], float]:
    return {
        (month.year, month.month): revenue
        for month, revenue, _prior in features._revenues_known(item, day)
    }


def sales_growth_36(item: lib.Series, day: date) -> Growth:
    """A2 第 1～3 點 on T (``day``)."""

    months = _revenue_months(item, day)
    if not months:
        return Growth(None, "stale")
    latest = max(months)
    if latest != _previous_month(day):
        return Growth(None, "stale")
    label = f"{latest[0]:04d}-{latest[1]:02d}"
    recent = [months.get(m) for m in _months(latest, RECENT_MONTHS)]
    base = [months.get(m) for m in _months(latest, BASE_MONTHS)]
    if any(value is None for value in (*recent, *base)):
        return Growth(None, "months", label)
    r1, r0 = math.fsum(recent), math.fsum(base)
    if r0 <= BASE_MIN:
        return Growth(None, "base", label, r1, r0)
    return Growth(r1 / r0 - 1.0, None, label, r1, r0)


def months_missing(item: lib.Series, day: date) -> bool:
    """A2 第 3 點 second case with m the month before T's (the reference's
    rule, 第十七輪實作釋義)."""

    months = _revenue_months(item, day)
    m = _previous_month(day)
    return any(
        key not in months
        for key in (*_months(m, RECENT_MONTHS), *_months(m, BASE_MONTHS))
    )


# --- A3: vov_240 ------------------------------------------------------------------


@dataclass(frozen=True)
class Vov:
    value: float | None
    reason: str | None = None  # "short", "suspended", "price", "zero"


def _part_sd(values: list[float]) -> float:
    mean = math.fsum(values) / len(values)
    return math.sqrt(
        math.fsum((v - mean) ** 2 for v in values) / (len(values) - PART_DDOF)
    )


def part_deviations(item: lib.Series) -> array:
    """s of the 20 returns to each bar k (k − 19 .. k, each return its close
    over the bar before's); NaN before bar 20 or with a close in k − 20 .. k
    missing or ≤ 0.  Each from its own 20 values, so equal parts give equal
    s exactly."""

    closes = item.close
    n = len(closes)
    good = [close > 0 for close in closes]  # NaN fails too
    bad = [0] * (n + 1)
    for k in range(n):
        bad[k + 1] = bad[k] + (not good[k])
    returns = [lib.NAN] + [
        closes[k] / closes[k - 1] - 1.0 if good[k] and good[k - 1] else lib.NAN
        for k in range(1, n)
    ]
    out = array("d", [lib.NAN]) * n
    width = VOV_PART_RETURNS
    for k in range(width, n):
        if bad[k + 1] - bad[k - width]:
            continue
        out[k] = _part_sd(returns[k - width + 1 : k + 1])
    return out


def vov_240(ctx: Context, item: lib.Series, at: int) -> Vov:
    """A3 第 1～3 點 on the item's bar ``at`` (T): the 12 parts' s_j (ddof 1)
    and their coefficient of variation (ddof 1)."""

    first = at - VOV_RETURNS
    if first < 0:
        return Vov(None, "short")
    if item.suspended[at + 1] != item.suspended[first]:
        return Vov(None, "suspended")
    closes = item.close[first : at + 1]
    if not all(close > 0 for close in closes):  # NaN fails too
        return Vov(None, "price")
    parts = ctx.parts.get(item.instrument_id)
    if parts is None:
        parts = ctx.parts[item.instrument_id] = part_deviations(item)
    s = [
        parts[first + VOV_PART_RETURNS * j] for j in range(1, VOV_PARTS + 1)
    ]  # part j: first + 20(j − 1) + 1 .. first + 20j
    mean = math.fsum(s) / VOV_PARTS
    if mean == 0:
        return Vov(None, "zero")
    if max(s) == min(s):
        return Vov(0.0)
    sd = math.sqrt(math.fsum((v - mean) ** 2 for v in s) / (VOV_PARTS - VOV_DDOF))
    return Vov(sd / mean)


# --- the plans --------------------------------------------------------------------


def segment_window(
    sessions: list[date], segment: str, spec: dict[str, Any]
) -> tuple[int, int] | None:
    """(first, last) index of the sessions with an equity value, or None.
    A1's and A2's equity starts the session after their first event day in
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
        events = [at for at, _q in r14.quarter_events(sessions)]
    elif spec["rule"] == "monthly":
        events = ex.event_days(sessions)
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
    reference: dict[int, list[int]] = field(default_factory=dict)  # A1, A2
    dues: dict[int, int] = field(default_factory=dict)  # A1, A2
    rows: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    signal_days: int = 0
    event_days: int = 0
    overlap: dict[str, dict[str, list[float]]] = field(default_factory=dict)
    means: dict[str, list[float]] = field(default_factory=dict)  # A2, A3
    rebalances: list[dict[str, Any]] = field(default_factory=list)  # A1, A2


_year = r15._year
_add = r15._add
_pick_row = r15._pick_row


def x8_names(ctx: Context, first: int, last: int) -> dict[int, list[int]]:
    """X8's lists by T + 1 on the segment (``explore_research`` 第 2 版的定義:
    ``_plan_buyback`` itself, its record from X8's own start), once per
    segment."""

    key = (first, last)
    if key not in ctx.x8:
        t0 = time.perf_counter()
        spec = ex.HYPOTHESES[X8]
        ctx.x8[key] = ex._plan_buyback(ctx.base, spec, first, last, ex.Plan()).picks
        ctx.seconds["x8_order"] += time.perf_counter() - t0
    return ctx.x8[key]


def x7_names(
    ctx: Context, day: date, members: list[tuple[lib.Series, int]]
) -> set[int]:
    """X7's list on ``day`` (``explore_research`` 第 2 版的定義, not rewritten)."""

    t0 = time.perf_counter()
    spec = ex.HYPOTHESES[X7]
    rows, _missing = ex._rank(ctx.base, spec, day, members)
    ctx.seconds["x7_order"] += time.perf_counter() - t0
    return {row[0] for row in rows[: spec["top"]]}


def x4_names(ctx, day, members) -> set[int]:
    """X4's list (``round14_research.x4_names``: ``explore_research._rank``)."""

    return r14.x4_names(ctx, day, members)


def v1_names(
    ctx: Context, day: date, members: list[tuple[lib.Series, int]]
) -> set[int]:
    """V1's list on ``day`` (``round5_research`` 第 1 版的定義, not rewritten)."""

    t0 = time.perf_counter()
    spec = r5.HYPOTHESES[V1]
    rows = r5.rank(ctx.v1, spec, day, members).rows
    ctx.seconds["v1_order"] += time.perf_counter() - t0
    return {row[0] for row in rows[: spec["top"]]}


def y2_names(
    ctx: Context, day: date, members: list[tuple[lib.Series, int]]
) -> set[int]:
    """Y2's list on ``day`` (``round7_research`` 第 1 版的定義, not rewritten)."""

    t0 = time.perf_counter()
    spec = r7.HYPOTHESES[Y2]
    rows = r7.rank(ctx.y2, spec, day, members).rows
    ctx.seconds["y2_order"] += time.perf_counter() - t0
    return {row[0] for row in rows[: spec["top"]]}


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


def plan_a1(
    ctx: Context, spec: dict[str, Any], first: int, last: int, keep_rows=True
) -> Plan:
    """A1 第 1～6、8、9 點: the event days of the segment, ``net_issue`` in T's
    population small first, 20, held to the next event day (X7); the
    reference population on the same days."""

    panel = ctx.panel
    sessions = panel.sessions
    out = Plan(overlap={"A1_X8": {}})
    top = spec["top"]
    keys = tuple(spec["keys"])
    every = r14.quarter_events(sessions)
    following = {at: nxt for (at, _q), (nxt, _n) in zip(every, every[1:])}
    x8 = x8_names(ctx, first, last)  # timed in the coverage too
    big = math.log(10.0)
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
            got = net_issue(ctx, item, day, quarter)
            reasons[got.reason] += 1
            rows.append((item, got, pr.tie_break(day, item.instrument_id)))
        ctx.seconds["net_issue"] += time.perf_counter() - t0
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
            **{
                key: reasons[key]
                for key in ("stale", "format", "fields", "eps", "shares")
            },
            "names": len(chosen),
            "delisted": gone,
            "delisted_missing": gone_missing,
            "g_not_1": sum(1 for got in valued if got.g != 1.0),
            "null_dividends": sum(1 for got in valued if got.null_dividends),
            "tenfold": sum(1 for got in valued if abs(got.value) >= big),
        }
        for key in ("valued", "delisted", "delisted_missing", "g_not_1",
                    "null_dividends", "tenfold"):  # fmt: skip
            _add(year, key, event[key])
        year.setdefault("events", []).append(event)
        if not keep_rows:
            continue
        names = [item.instrument_id for item, _g, _t in chosen]
        share = r10.overlap_share(names, set(x8.get(at + 1, ())))
        if share is not None:
            out.overlap["A1_X8"].setdefault(str(day.year), []).append(share)
        out.rebalances.append({**event, "x8_overlap": share})
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
                    {"quarter": quarter.isoformat(), "net_issue": got.value,
                     "shares_q": got.shares_q, "shares_q4": got.shares_q4, "g": got.g},
                    tie,
                )
            )  # fmt: skip
    return out


def plan_a2(
    ctx: Context, spec: dict[str, Any], first: int, last: int, keep_rows=True
) -> Plan:
    """A2 第 1～4、7、8 點: X7's event days of the segment, ``sales_growth_36``
    in T's population small first, 20, held to the next event day; the
    reference population on the same days."""

    panel = ctx.panel
    sessions = panel.sessions
    out = Plan(overlap={"A2_X7": {}, "A2_X4": {}})
    top = spec["top"]
    keys = tuple(spec["keys"])
    every = ex.event_days(sessions)
    following = dict(zip(every, every[1:]))
    yoy = ex.FEATURES["revenue_yoy"]
    for at in every:
        if not first - 1 <= at <= last - 1:
            continue
        day = sessions[at]
        members = lib.universe(panel, day, MIN_LOTS)
        year = _year(out.coverage, day, len(members))
        out.signal_days += 1
        out.event_days += 1
        t0 = time.perf_counter()
        rows, reasons = [], Counter()
        for item, k in members:
            got = sales_growth_36(item, day)
            reasons[got.reason] += 1
            rows.append((item, k, got, pr.tie_break(day, item.instrument_id)))
        ctx.seconds["sales_growth_36"] += time.perf_counter() - t0
        t0 = time.perf_counter()
        gone, gone_missing, excluded = _reference(
            ctx, members, lambda item: months_missing(item, day)
        )
        ctx.seconds["reference"] += time.perf_counter() - t0
        rows.sort(
            key=lambda row: r5.order_key({keys[0][0]: row[2].value}, keys, row[3])
        )
        chosen = rows[:top]
        event = {
            "signal_date": day.isoformat(),
            "members": len(members),
            "valued": reasons[None],
            **{key: reasons[key] for key in ("stale", "months", "base")},
            "names": len(chosen),
            "delisted": gone,
            "delisted_missing": gone_missing,
        }
        for key in ("valued", "delisted", "delisted_missing"):
            _add(year, key, event[key])
        year.setdefault("events", []).append(event)
        others = {
            "A2_X7": x7_names(ctx, day, members),
            "A2_X4": x4_names(ctx, day, members),
        }  # timed in the coverage too
        if not keep_rows:
            continue
        names = [item.instrument_id for item, _k, _g, _t in chosen]
        shares = {}
        for key, other in others.items():
            share = r10.overlap_share(names, other)
            shares[key] = share
            if share is not None:
                out.overlap[key].setdefault(str(day.year), []).append(share)
        t0 = time.perf_counter()
        growths = [yoy(ctx.base, item, k) for item, k, _g, _t in chosen]
        ctx.seconds["revenue_yoy"] += time.perf_counter() - t0
        present = [v for v in growths if v is not None]
        mean = statistics.fmean(present) if present else None
        if mean is not None:
            out.means.setdefault(str(day.year), []).append(mean)
        out.rebalances.append(
            {**event, "x7_overlap": shares["A2_X7"], "x4_overlap": shares["A2_X4"],
             "revenue_yoy": mean}
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
        for place, ((item, _k, got, tie), growth) in enumerate(zip(chosen, growths), 1):
            out.rows.append(
                _pick_row(
                    ctx, day, place, item.instrument_id,
                    {"month": got.month, "sales_growth_36": got.value, "r1": got.r1,
                     "r0": got.r0, "revenue_yoy": growth},
                    tie,
                )
            )  # fmt: skip
    return out


def plan_a3(
    ctx: Context, spec: dict[str, Any], first: int, last: int, keep_rows=True
) -> Plan:
    """A3 第 1～4、6 點 on the signal dates ``first − 1`` .. ``last − 1``."""

    panel = ctx.panel
    out = Plan(overlap={"A3_V1": {}, "A3_Y2": {}})
    top = spec["top"]
    keys = tuple(spec["keys"])
    for at in range(first - 1, last):
        day = panel.sessions[at]
        members = lib.universe(panel, day, MIN_LOTS)
        year = _year(out.coverage, day, len(members))
        out.signal_days += 1
        t0 = time.perf_counter()
        rows, missing = [], Counter()
        for item, k in members:
            got = vov_240(ctx, item, k)
            if got.value is None:
                missing["vov_240"] += 1
                missing[got.reason] += 1
            rows.append((item, k, got, pr.tie_break(day, item.instrument_id)))
        ctx.seconds["vov_240"] += time.perf_counter() - t0
        rows.sort(
            key=lambda row: r5.order_key({keys[0][0]: row[2].value}, keys, row[3])
        )
        chosen = rows[:top]
        missing_year = year.setdefault("missing", {})
        for key, count in missing.items():
            missing_year[key] = missing_year.get(key, 0) + count
        _add(year, "valued", len(members) - missing["vov_240"])
        others = {
            "A3_V1": v1_names(ctx, day, members),
            "A3_Y2": y2_names(ctx, day, members),
        }  # timed in the coverage too
        if not keep_rows:
            continue
        names = [item.instrument_id for item, _k, _g, _t in chosen]
        for key, other in others.items():
            share = r10.overlap_share(names, other)
            if share is not None:
                out.overlap[key].setdefault(str(day.year), []).append(share)
        t0 = time.perf_counter()
        vols = [r5.vol_60(ctx.v1, item, k) for item, k, _g, _t in chosen]
        ctx.seconds["vol_60"] += time.perf_counter() - t0
        present = [v for v in vols if v is not None]
        if present:
            out.means.setdefault(str(day.year), []).append(statistics.fmean(present))
        out.picks[at + 1] = names
        out.population[at + 1] = [item.instrument_id for item, _ in members]
        for place, ((item, _k, got, tie), vol) in enumerate(zip(chosen, vols), 1):
            out.rows.append(
                _pick_row(ctx, day, place, item.instrument_id,
                          {"vov_240": got.value, "vol_60": vol}, tie)
            )  # fmt: skip
    return out


def planner(name: str) -> Callable[..., Plan]:
    return {"A1": plan_a1, "A2": plan_a2, "A3": plan_a3}[name]


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
    """(the hypothesis, the population, the reference): A1 and A2 X7's
    account with their references, A3 K accounts."""

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


def _mean_key(name: str) -> str | None:
    """The listed mean of the list (A2 第 8 點, A3 第 6 點)."""

    return {"A2": "revenue_yoy", "A3": "vol_60"}.get(name)


def run_portfolio(
    ctx: Context,
    db: Path,
    name: str,
    segment: str,
    coverage_only: bool = False,
    min_t: float = MIN_T,
) -> dict[str, Any]:
    """A1, A2 or A3 on one segment: its numbers, verdict and private parts."""

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
    if _mean_key(name):
        result[_mean_key(name)] = overlap_summary(planned.means)
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
    """A1 and A2 each event day and by year, A3 by year."""

    if name == "A1":
        head = ["事件日", "對應的季", "母體檔次", "有 `net_issue` 的檔數", "名單檔數",
                "最新一季不是對應的那一季", "`report_format` 不是 `general`", "欄位缺",
                "（比例）", "EPS 絕對值 < 0.5 元", "sh ≤ 0", "母體裡的下市、轉板股",
                "（其中缺所需欄位）", "g ≠ 1", "窗口內有 null 配股列", "\\|`net_issue`\\| ≥ ln 10"]  # fmt: skip
        lines = [
            "| " + " | ".join(head) + " |",
            "| --- | --- | " + " | ".join("---:" for _ in head[2:]) + " |",
        ]
        for _year_, row in sorted(coverage.items()):
            for e in row.get("events", []):
                lines.append(
                    f"| {e['signal_date']} | {e['quarter']} | {e['members']:,} | {e['valued']:,} "
                    f"| {e['names']:,} | {e['stale']:,} | {e['format']:,} | {e['fields']:,} "
                    f"| {_share(e['fields'], e['members'])} | {e['eps']:,} | {e['shares']:,} "
                    f"| {e['delisted']:,} | {e['delisted_missing']:,} | {e['g_not_1']:,} "
                    f"| {e['null_dividends']:,} | {e['tenfold']:,} |"
                )
        lines += ["", "依年：", "",
                  "| 年 | 事件日 | 母體檔次 | 有 `net_issue` 的檔次 | 母體裡的下市、轉板股檔次 "
                  "| 其中缺 `net_issue` 所需欄位 | g ≠ 1 的檔次 | 窗口內有 null 配股列的檔次 "
                  "| \\|`net_issue`\\| ≥ ln 10 的檔次 |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]  # fmt: skip
        for year, row in sorted(coverage.items()):
            lines.append(
                f"| {year} | {row['days']:,} | {row['members']:,} | {row.get('valued', 0):,} "
                f"| {row.get('delisted', 0):,} | {row.get('delisted_missing', 0):,} "
                f"| {row.get('g_not_1', 0):,} | {row.get('null_dividends', 0):,} "
                f"| {row.get('tenfold', 0):,} |"
            )
        return lines
    if name == "A2":
        head = ["事件日", "母體檔次", "有 `sales_growth_36` 的檔數", "名單檔數",
                "最新已知月份不是上個月", "月份缺", "（比例）", "R0 ≤ 0",
                "母體裡的下市、轉板股", "（其中缺所需月份）"]  # fmt: skip
        lines = [
            "| " + " | ".join(head) + " |",
            "| --- | " + " | ".join("---:" for _ in head[1:]) + " |",
        ]
        for _year_, row in sorted(coverage.items()):
            for e in row.get("events", []):
                lines.append(
                    f"| {e['signal_date']} | {e['members']:,} | {e['valued']:,} "
                    f"| {e['names']:,} | {e['stale']:,} | {e['months']:,} "
                    f"| {_share(e['months'], e['members'])} | {e['base']:,} "
                    f"| {e['delisted']:,} | {e['delisted_missing']:,} |"
                )
        lines += ["", "依年：", "",
                  "| 年 | 事件日 | 母體檔次 | 有 `sales_growth_36` 的檔次 | 母體裡的下市、轉板股檔次 "
                  "| 其中缺 `sales_growth_36` 所需月份 |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"]  # fmt: skip
        for year, row in sorted(coverage.items()):
            lines.append(
                f"| {year} | {row['days']:,} | {row['members']:,} | {row.get('valued', 0):,} "
                f"| {row.get('delisted', 0):,} | {row.get('delisted_missing', 0):,} |"
            )
        return lines
    head = ["年", "日數", "母體檔次", "有 `vov_240` 的檔次", "缺值", "（不足 241 根）",
            "（停牌）", "（收盤缺值或 ≤ 0）", "（s_j 的平均是 0）"]  # fmt: skip
    lines = [
        "| " + " | ".join(head) + " |",
        "| --- | " + " | ".join("---:" for _ in head[1:]) + " |",
    ]
    for year, row in sorted(coverage.items()):
        members, missing = row["members"], row.get("missing", {})
        lines.append(
            f"| {year} | {row['days']:,} | {members:,} | {row.get('valued', 0):,} "
            f"| {_share(missing.get('vov_240', 0), members)} "
            f"| {_share(missing.get('short', 0), members)} "
            f"| {_share(missing.get('suspended', 0), members)} "
            f"| {_share(missing.get('price', 0), members)} "
            f"| {_share(missing.get('zero', 0), members)} |"
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
        f"# {name} {segment}（round17_research 第 {VERSION} 版，#{DESIGN}）",
        "",
    ]
    if name in ("A1", "A2"):
        lines += [OVERLAP_NOTE[f"{name}_survivor"], ""]
    if name in ("A2", "A3"):
        lines += [f"- {OVERLAP_NOTE[f'{name}_summary_only']}", ""]
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


def _rebalance_lines(name: str, rebalances: list[dict[str, Any]]) -> list[str]:
    point = "A1 第 9 點" if name == "A1" else "A2 第 8 點"
    lines = [
        f"## 每次調倉（{point}，只列出、不判定）",
        "",
        "名單檔數是取前 20 名之後；投入比例是買進那天收盤時，部位占淨值的比例。",
        "",
    ]
    if name == "A1":
        lines += [
            "| 事件日 | 對應的季 | 母體檔次 | 有 `net_issue` | 名單檔數 | 投入比例 | 和 X8 的重疊 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
            *(
                f"| {e['signal_date']} | {e['quarter']} | {e['members']:,} | {e['valued']:,} "
                f"| {e['names']:,} | {_pct(e.get('invested'), 1)} | {_pct(e['x8_overlap'], 1)} |"
                for e in rebalances
            ),
        ]
    else:
        lines += [
            "| 事件日 | 母體檔次 | 有 `sales_growth_36` | 名單檔數 | 投入比例 | 和 X7 的重疊 "
            "| 和 X4 的重疊 | 名單的平均 `revenue_yoy` |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            *(
                f"| {e['signal_date']} | {e['members']:,} | {e['valued']:,} | {e['names']:,} "
                f"| {_pct(e.get('invested'), 1)} | {_pct(e['x7_overlap'], 1)} "
                f"| {_pct(e['x4_overlap'], 1)} | {_pct(e['revenue_yoy'], 1)} |"
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
        lines += _rebalance_lines(name, result["rebalances"])
    for key, title in (
        ("A1_X8", "## 和 X8 的重疊（A1 第 9 點）"),
        ("A2_X7", "## 和 X7 的重疊（A2 第 8 點）"),
        ("A2_X4", "## 和 X4 的重疊（A2 第 8 點）"),
        ("A3_V1", "## 和 V1 的重疊（A3 第 6 點）"),
        ("A3_Y2", "## 和 Y2 的重疊（A3 第 6 點）"),
    ):
        if key in result.get("overlap", {}):
            lines += _yearly_lines(
                title, OVERLAP_NOTE[key], result["overlap"][key], lambda v: _pct(v, 1)
            )
    if result.get("revenue_yoy"):
        lines += _yearly_lines(
            "## 名單的平均 `revenue_yoy`（A2 第 8 點，只列出、不判定）",
            "每個事件日名單中有值的檔的 `revenue_yoy`（`explore_research` 的 `revenue_yoy`，即 "
            "`feature_evidence.revenue_yoy`）平均",
            result["revenue_yoy"],
            lambda v: _pct(v, 1),
        )
    if result.get("vol_60"):
        lines += _yearly_lines(
            "## 名單的平均 `vol_60`（A3 第 6 點，只列出、不判定）",
            "每天名單中有值的檔的 `vol_60`（`round5_research.vol_60`）平均",
            result["vol_60"],
            lambda v: _pct(v, 2),
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
    for key in ("revenue_yoy", "vol_60"):
        if result.get(key):
            row[key] = {k: result[key][k] for k in ("days", "mean")}
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
        f"# 新策略探索 第 {report['round']} 輪 {stage}（round17_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「第十七輪：A1～A3」）：{DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        _threshold_line(segment, report["min_t"]),
        "- 引擎：A1、A2 是 X7 的事件日帳戶（`explore_research.simulate_events`），A3 是組合引擎"
        "（`portfolio_research.simulate`，K＝20）；日數是有淨值的交易日",
        OVERLAP_NOTE["A1_survivor"],
        OVERLAP_NOTE["A2_survivor"],
        f"- A2：{OVERLAP_NOTE['A2_summary_only']}",
        f"- A3：{OVERLAP_NOTE['A3_summary_only']}",
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
        for key, label in (
            ("overlap_x8", "X8"),
            ("overlap_x7", "X7"),
            ("overlap_x4", "X4"),
            ("overlap_v1", "V1"),
            ("overlap_y2", "Y2"),
        ):
            part = row.get(key)
            if part:
                listed.append(
                    f"- {name} 和 {label} 的重疊：平均 {_pct(part['mean'], 1)}（{part['days']:,} 個訊號日）"
                )
        if row.get("revenue_yoy"):
            listed.append(
                f"- {name} 名單的平均 `revenue_yoy`：{_pct(row['revenue_yoy']['mean'], 1)}"
            )
        if row.get("vol_60"):
            listed.append(
                f"- {name} 名單的平均 `vol_60`：{_pct(row['vol_60']['mean'], 2)}"
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
    f"- A1：{DEGENERATE['A1']}。每個事件日一列，缺值的原因依序判（最新一季、格式、欄位缺、EPS 下限、sh ≤ 0），"
    "每檔只算第一個；「母體裡的下市、轉板股」是 `status` 為 `delisted`／`transferred` 的母體檔次，"
    "「其中缺所需欄位」是對照基準去掉的檔次；「g ≠ 1」「窗口內有 null 配股列」「\\|`net_issue`\\| ≥ ln 10」"
    "（推算股數和去年同季差 10 倍以上）只數有 `net_issue` 的檔；`x8_order` 是整段算一次 X8 名單的時間，"
    "`--coverage-only` 不算重疊比例，各段的 `summary.md` 才列",
    f"- A2：{DEGENERATE['A2']}。每個事件日一列，缺值的原因依序判（最新已知月份、月份缺、R0），"
    "每檔只算第一個；「其中缺所需月份」是對照基準去掉的檔次；`x7_order`、`x4_order` 是同一個 T 算 X7、X4 名單的時間"
    "（X4 的 `_rank` 另記它自己的特徵），`--coverage-only` 不算重疊比例與平均 `revenue_yoy`，各段的 `summary.md` 才列",
    f"- A3：{DEGENERATE['A3']}。依年一列；`v1_order`、`y2_order` 是同一個 T 算 V1、Y2 名單的時間，"
    "`--coverage-only` 不算重疊比例與平均 `vol_60`，各段的 `summary.md` 才列",
    "- 各假設用自己的訊號日（起日寫在各段標題）",
)


def columns_lines(columns: dict[str, Any]) -> list[str]:
    lines = [
        "| 季 | `report_format` | 列數 | "
        + " | ".join(f"`{n}`" for n in (NET, EPS))
        + " |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for quarter, kinds in columns.items():
        for kind, part in kinds.items():
            lines.append(
                f"| {quarter} | {kind} | {part['rows']:,} | "
                + " | ".join(f"{part['fields'].get(n, 0):,}" for n in (NET, EPS))
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
        f"# 新策略探索 第 {body['round']} 輪 A1～A3 資料覆蓋（探索段，不含報酬）",
        "",
        f"- round17_research 第 {VERSION} 版；定義雜湊 `{body['definitions_sha256']}`",
        f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}，"
        f"alembic `{body['copy']['alembic']}`",
        f"- 重現：`{body['command']}`",
        f"- 耗時 {body.get('elapsed_seconds', 0):.0f} 秒（載入 {body.get('load_seconds', 0):.0f} 秒，"
        f"其中 panel {load_seconds.get('panel', 0):.0f} 秒、季報其他欄位（A1）"
        f"{load_seconds.get('statements', 0):.0f} 秒、除權息與標的狀態 "
        f"{load_seconds.get('dividends', 0):.0f} 秒；"
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
            "## A1：2013 年各季的欄名（`fundamental_snapshots.data_json`，期末在 2013 年的列）",
            "",
            *columns_lines(body["columns_2013"]),
            "",
        ]
    lines += [
        "有明顯斷點，或缺值比例有異常的年份或欄位，或 2013 年的欄名和現在不同、讀不到兩個欄位，"
        "或 A1 推算股數有明顯不合理的值（例如 sh 和去年同季差 10 倍以上的檔次很多），"
        "或某個事件日一檔都沒有值時，先在工具單提問、不跑探索段。",
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
    parser = argparse.ArgumentParser(prog="round17_research.py", description=__doc__)
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
        help="exploration (required, not with --coverage-only): A1, A2, A3 or "
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
    command = "python tools/research/round17_research.py " + " ".join(argv)
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
