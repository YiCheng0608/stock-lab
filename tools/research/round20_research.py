"""Round 20 of the new-strategy exploration: AB1, AB2 (#1057).

docs/spec/evidence.md 第二十輪：AB1、AB2 and 第二十輪實作釋義: the hypotheses
were registered (commit ``eb8df844``, #1053, decision 7196822123) before
anyone ran a tool on the backfilled history.  Nothing here is a command-line
option: a change of a definition is a new code.

They are not in ``explore_research.HYPOTHESES``, ``trade_research.HYPOTHESES``
nor ``round4_research`` .. ``round19_research``: their ``definitions_sha256``
hash the whole table, so adding them would make the validation refuse the
exploration reports already run.  AB1 trades on X7's event-day account
(``explore_research.simulate_events``), AB2 on ``portfolio_research.simulate``
(K 20); the population, the loading (``explore_research.load_context``, its
MOPS list too), ``explore_judge``, the gate and the ledgers are imported.
AB1's event days are ``round14_research.quarter_events``, its rows P2's own
(``round15_research.load_statements``), its latest quarter
``round15_research._known`` and its single quarters
``round15_research.single_quarter`` (as P2, N2 and G1); AB2's
``momentum_20`` is ``round5_research.momentum_20``.  The overlaps take P2
(``round16_research.p2_names``), G1 (``round18_research.nonop_q`` on
``round18_research.load_nonop_statements``), X4
(``round14_research.x4_names``), V2 (``round5_research.rank``) and Y4
(``round7_research.rank``, the member table) on the same T, and
``round10_research``'s ``overlap_share``／``overlap_summary``; AB1's
industries ``round11_research.industry_count``／``industries_summary`` on
``mainstream_research.group_members``.  New here are only ``op_margin_4q``,
``no_news_20``, AB1's reference population and the listed numbers.

Each signal date T (after its close, only T's data and before):

- AB1: on the 4 statutory deadlines, ``op_margin_4q`` (the last 4 single
  quarters' operating income over their revenue) high first, 20, held to
  the next event day (X7).
- AB2: the members with ``no_news_20`` (no material information on any
  calendar day of (session T − 20, T]), ``momentum_20`` small first, 20,
  K 20.

``explore_research.explore_judge`` judges with t ≥ 2 on the exploration and
the fixed Bonferroni t ≥ 3.384 (70 hypotheses) on the validation.  Before the
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
from bisect import bisect_left, bisect_right
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
import round7_research as r7  # noqa: E402
import round10_research as r10  # noqa: E402
import round11_research as r11  # noqa: E402
import round14_research as r14  # noqa: E402
import round15_research as r15  # noqa: E402
import round16_research as r16  # noqa: E402
import round18_research as r18  # noqa: E402

VERSION = 1
DESIGN = "1057"
TOOL = "round20_research"
REGISTRATION_COMMIT = "eb8df844"
DECISION = (
    "https://github.com/YiCheng0608/stock-lab/issues/1053#issuecomment-7196822123"
)
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
SEGMENTS = dict(ex.SEGMENTS)
MIN_SEGMENT_DAYS = dict(ex.MIN_SEGMENT_DAYS)
MIN_T = ex.MIN_T  # the exploration's t ≥ 2
# docs 第二十輪 門檻: 1 − Φ(z) = 0.025 ÷ 70, z = 3.3840, 3.384 to the 3rd decimal;
# fixed, not computed when run.
VALIDATION_MIN_T = 3.384
ROUND = 20
ROUND_SIZE = 2
# X1～X8, S1～S3, R1～R2, M1～M2, C1～C4, V1～V3, W1～W4, Y1～Y4, Z1～Z4, B1～B3,
# F1～F4, L1～L4, J1～J4, U1～U3, K1～K3, P1～P3, N1～N3, A1～A3, G1～G2, D1～D2,
# AB1～AB2
CUMULATIVE = 70
# Every segment reads the copy from its start, as round10_research ..
# round19_research.
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
    "by the feature (round5_research.order_key), missing last, ties by "
    "sha256(<T>:<instrument_id>); a condition missing does not qualify"
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

# AB1 (第 1～6 點)
OPERATING = r15.OPERATING  # 營業利益（損失）, read by round15_research.statement_of
REVENUE = r15.REVENUE  # 營業收入
REPORT_FORMAT = "general"
FIELDS = ("operating", "revenue")  # round15_research.Statement's attributes
QUARTERS = 4  # q, q − 1, q − 2, q − 3
REVENUE_MIN = 0.0  # Σ rev ≤ 0: missing
LATEST_RULE = (
    "the latest quarter known on T (announcement_date <= T, the largest "
    "period_end, an EPS null row too; round15_research._known, P2's) must be "
    "the deadline's quarter"
)
NEEDED_RULE = (
    "q, q-1, q-2, q-3 and, for each that is not a Q1, the quarter before it "
    "of the same year (its cumulative figures for the single quarter)"
)
STATEMENT_RULE = (
    "round15_research.load_statements (P2's rows: announcement_date <= T, an "
    "EPS null row too), by period_end the later announcement; a needed row "
    "not known or a field null is missing; a needed row of another "
    "report_format is missing, a null report_format a missing field"
)
OP_MARGIN = (
    "math.fsum(op(q-k), k=0..3) / math.fsum(rev(q-k), k=0..3), single "
    "quarters; the sum of op 0: 0, not missing; a negative op or a single "
    "rev <= 0 with the sum > 0 by value; reasons in order: stale, format, "
    "fields, revenue"
)
AB1_REFERENCE = (
    "T's population less the delisted or transferred instruments missing a "
    "field op_margin_4q needs on T (a needed row of q .. q-3 of the "
    "deadline's quarter not known, or OPERATING or REVENUE null, so no single "
    "quarter; not the stale quarter, the report_format nor the sum of rev <= "
    "0); the same account and event days"
)
AB1_START = date(2014, 3, 31)
INDUSTRY_RULE = (
    "mainstream_research.group_members on T (the latest snapshot <= T), each "
    "instrument in its smallest group id (L4's); round11_research."
    "industry_count of the list"
)
P2, G1, X4 = "P2", "G1", "X4"  # the lists AB1 overlaps with

# AB2 (第 1～5 點)
NEWS_SOURCE = ex.MOPS_SOURCE
NEWS_EVENT_TYPE = ex.MOPS_EVENT_TYPE
NEWS_SESSIONS = 20  # the window opens after session T − 20
NEWS_RULE = (
    "the calendar days d with sessions[s-20] < d <= T (s is T's index in "
    "Panel.sessions, every market's sessions, not the item's own bars), "
    "weekends and holidays too, T itself at any hour; any title, several on a "
    "day once; the list's date (events.event_date), not the session it is "
    "put off to; s < 20: from sessions[0]"
)
NEWS_MISSING = "no row is no news; no_news_20 is never missing"
MOMENTUM_RULE = (
    "round5_research.momentum_20 (V2's), small first among the members with "
    "no_news_20, missing last, not dropped"
)
OTC_ANCHOR = date(2007, 12, 3)  # the OTC bars the tools read
AB2_SESSIONS = r5.MOMENTUM_WINDOW + 1  # momentum_20 needs 21 bars
DELISTED_STATUS = "delisted"  # AB2 第 7 點: the list's later delisted names
V2, Y4 = "V2", "Y4"  # the lists AB2 overlaps with

# The registration (docs 第二十輪：AB1、AB2), word for word.  ``start`` as
# ``explore_research``.
HYPOTHESES: dict[str, dict[str, Any]] = {
    "AB1": {
        "engine": EVENTS,
        "direction": "基本面：營業利益率",
        "label": "每季法定期限的事件日，`op_margin_4q`（最近 4 季單季營業利益合計 ÷ 最近 4 季單季營業收入合計）"
        "大者先取 20 檔",
        "rule": "quarterly",
        "keys": (("op_margin_4q", HIGH),),
        "short": SHORT_RULE,
        "top": 20,
        "hold": "next_event",
        "start": ("date", AB1_START),
    },
    "AB2": {
        "engine": PORTFOLIO,
        "direction": "短期反轉：無消息",
        "label": "`no_news_20`（近 20 個交易日的日曆區間內沒有任何一則重大訊息）成立，依 `momentum_20`"
        "（20 日報酬）小者先",
        "rule": "daily",
        "condition": "no_news_20",
        "keys": (("momentum_20", LOW),),
        "short": SHORT_RULE,
        "top": 20,
        "hold": 20,
        "start": ("session", OTC_ANCHOR, AB2_SESSIONS),
    },
}
OTHER_COMPARISONS = ex.OTHER_COMPARISONS
REASONS = dict(ex.REASONS)
LIMITS = {
    "AB1": "定義照摘要與索引頁（[EconPapers](https://econpapers.repec.org/RePEc:eee:jfinec:v:117:y:2015:i:2:p:225-248)），"
    "未讀全文；分母是代理：文獻除以淨值或總資產，研究 DB 沒有資產負債表，以營收當分母是代理，不是文獻的量，"
    "Ball 等指出分母的選法本身會改變結果，前例是 N2、G1 用營收當分母；營業利益率高低大半由產業決定，"
    "名單可能集中在少數產業，看名單涉及的產業數；存活者偏差：下市股的季報是 XBRL 整包補的，只寫了 EPS，"
    "沒有這兩個欄位，期間內下市公司的季幾乎都缺值、排最後，偏差方向對假設有利，大小同 P2、N2、A1、G1；"
    "金融業等格式與法定期限不同的公司不會有值；2013 年的欄名由 `--coverage-only` 列，有值檔數偏少的季寫在資料覆蓋；"
    "和 P2、G1、X4 同一張季報表、同一份存活者偏差（X4 用 EPS），P2、G1、X4 的狀態登記時已知；"
    "不是看結果挑的：P2 看三個利潤率的變化方向，AB1 只看營益率最近 4 季的水準、不看變化，不是 P2 的變形，"
    "G1 用同一張表的另一欄，X4 用 EPS 收益率，看重疊比例",
    "AB2": "定義照摘要與索引頁（[EconPapers](https://econpapers.repec.org/RePEc:eee:jfinec:v:70:y:2003:i:2:p:223-260)），"
    "未讀全文；消息的代理：文獻的消息是媒體標題，MOPS 重大訊息含很多例行公告（代子公司公告、股東會、取得資產），"
    "所以「無消息」比文獻嚴，大型股可能幾乎都有消息，看 `no_news_20` 成立的檔數與比例；"
    "文獻說效果集中在小型、流動性低的股票，母體的 20 日均量 ≥ 1,000 張會去掉一部分這類股票；"
    "存活者偏差（方向和前幾輪相反）：登記段寫 2014 年起才有，`--coverage-only` 查到 2008 年起就有"
    "（2008～2013 年下市公司有公告的也只有 2～9 檔，2014 年起與驗證段 0 則），之後下市的公司幾乎一律被當成無消息、"
    "會進名單，對假設不利（推論），看名單裡之後下市的比例；和 V2、Y4、X8 有關：V2、Y4 都是短期反轉，"
    "X8 用了同一張重大訊息表（只用庫藏股的主旨），三個的狀態登記時都已知；V2、Y4 都沒有通過，不是從好結果裡挑，"
    "新的是以「有沒有消息」分開延續與反轉，看重疊比例",
}
# The degenerate cases as the code judges them (第二十輪實作釋義; PR #913
# review: the docs, coverage.md and summary.md say the same words, a test
# reads the docs' tool section for them).
DEGENERATE = {
    "AB1": "最新一季（`announcement_date` ≤ T 的季報列中期末最晚的一季，EPS 是 null 的列也算）不是事件日對應的那一季、"
    "q～q−3 與它們各自的同年前一季（Q1 不用）任一列的 `report_format` 不是 `general`（`report_format` 是 null 的列算欄位缺）、"
    "任一列不在或 `營業利益（損失）`、`營業收入` 任一欄缺（含算單季要用的同年前一季累計缺），"
    "或 4 季營收合計 Σrev ≤ 0 時缺值、排最後；單一季的單季營收 ≤ 0 或營業利益為負不算缺值，只看 4 季合計；"
    "Σop＝0 時 `op_margin_4q`＝0，照值排序，不是缺值；有值的不足 20 檔時以缺值的依雜湊補，母體不足 20 檔時餘額留現金",
    "AB2": "`no_news_20` 沒有缺值：窗口內沒有重大訊息的列就是無消息；`momentum_20` 缺值（不足 21 根、收盤缺值，"
    "照 V2 的 `round5_research.momentum_20`）時排在成立的檔的最後、不剔除；"
    "T 往前不足 20 個全市場交易日時，窗口取到 `Panel.sessions` 的第一天（起日以後不會發生）；"
    "成立的不足 20 檔時餘額留現金，不以不成立的檔補",
}
OVERLAP_NOTE = {
    "AB1_P2": 'AB1 與 P2（`round15_research` 第 1 版的 `HYPOTHESES["P2"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|AB1 的名單 ∩ P2 當天的名單| ÷ AB1 當天的名單檔數；AB1 或 P2 當天沒有名單的事件日不計。只列出、不判定",
    "AB1_G1": 'AB1 與 G1（`round18_research` 第 1 版的 `HYPOTHESES["G1"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|AB1 的名單 ∩ G1 的前 20 名| ÷ AB1 當天的名單檔數；AB1 或 G1 當天沒有名單的事件日不計。只列出、不判定",
    "AB1_X4": 'AB1 與 X4（`explore_research` 第 2 版的 `HYPOTHESES["X4"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|AB1 的名單 ∩ X4 的前 20 名| ÷ AB1 當天的名單檔數；AB1 或 X4 當天沒有名單的事件日不計。只列出、不判定",
    "AB2_V2": 'AB2 與 V2（`round5_research` 第 1 版的 `HYPOTHESES["V2"]`，同一個 T 算）每日名單的重疊比例：'
    "|AB2 的名單 ∩ V2 的前 20 名| ÷ AB2 當天的名單檔數；AB2 或 V2 當天沒有名單的日子不計。只列出、不判定",
    "AB2_Y4": 'AB2 與 Y4（`round7_research` 第 1 版的 `HYPOTHESES["Y4"]`，同一個 T 算）每日名單的重疊比例：'
    "|AB2 的名單 ∩ Y4 的前 20 名| ÷ AB2 當天的名單檔數；AB2 或 Y4 當天沒有名單的日子不計。只列出、不判定",
    "AB1_reference": "對照基準：當天母體去掉「缺 `op_margin_4q` 任一所需欄位（事件日對應的那一季 q～q−3 與它們各自的同年前一季，"
    "任一列不在或兩個欄位任一欄缺，算不出單季；不看是不是最新一季、不看 `report_format`、不看 Σrev ≤ 0）的 "
    "`delisted`／`transferred` 標的」，同一個帳戶規則、同一組事件日；列 AB1 對它的超額與 t，只列出、不判定（判定仍只比母體）",
    "AB1_survivor": "- 存活者偏差（AB1）：下市股的季報是 XBRL 整包補的，只寫了 EPS，沒有 `營業利益（損失）`、`營業收入`，"
    "期間內下市公司的季幾乎都缺值、排最後，偏差方向對假設有利。對照基準（母體去掉當天缺所需欄位的下市、轉板股）的超額與 t "
    "在 `AB1/summary.md`「數字」表的「超額（對對照基準，只列出）」列與 `explore.md` 的「只列出、不判定」",
    "AB1_proxy": "以營收當分母是代理：文獻除以淨值或總資產；研究 DB 沒有資產負債表，以營收當分母，不是文獻的量",
    "AB1_listed": "每次調倉的檔數與平均投入比例、每個事件日母體中有 `op_margin_4q` 的檔數：名單檔數是取前 20 名之後，"
    "投入比例是買進那天收盤時部位占淨值的比例。只列出、不判定",
    "AB1_industries": "名單涉及的產業數：每個事件日名單裡的檔在官方產業的逐月成員表（`snapshot_date` ≤ T 的最新一份）"
    "所屬的產業數，同時屬於幾個產業的檔算它產業代號最小的那一個，不在成員表的檔不計（`round11_research.industry_count`，"
    "L4 第 7 點）。只列出、不判定",
    "AB2_survivor": "- 存活者偏差（AB2，方向和前幾輪相反）：登記段寫 2014 年起才有，`--coverage-only` 查到 2008 年起就有："
    "2008～2013 年每年有日線的下市公司 141～160 檔中，當年有重大訊息的只有 2～9 檔，2014 年起 0 則，"
    "驗證段（2020～2024 年，每年 24～76 檔）也是 0 則"
    "（[#1057 提問 7198433431](https://github.com/YiCheng0608/stock-lab/issues/1057#issuecomment-7198433431)、"
    "[回報 7198426915](https://github.com/YiCheng0608/stock-lab/issues/1057#issuecomment-7198426915)）；"
    "所以兩段裡之後下市的公司幾乎一律被當成無消息、會進名單。它們實際上多半有消息，依文獻有消息的跌會延續，"
    "這對假設不利，這是推論；名單裡之後下市的比例依年列在 `AB2/summary.md`",
    "AB2_listed": "每天母體裡 `no_news_20` 成立的檔數與比例：成立的檔次 ÷ 母體檔次，依年加總。只列出、不判定",
    "AB2_delisted": "名單裡之後下市的檔次比例：每天名單裡標的 `status` 是 `delisted` 的檔次 ÷ 名單檔次，依年加總。"
    "只列出、不判定",
    "summary_only": "定義照摘要與索引頁，未讀全文",
}
FEATURE_LABELS = {
    "op_margin_4q": "營業利益率（最近 4 季）",
    "no_news_20": "近 20 日無重大訊息",
    "momentum_20": "20 日報酬",
}
PICK_FIELDS = {
    "AB1": ("quarter", "op_margin_4q", "operating_4q", "revenue_4q"),
    "AB2": ("no_news_20", "momentum_20"),
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
        "deadlines": [r14.DEADLINES, r14.EVENT_DAY_RULE],  # AB1's events
        "features": {
            "op_margin_4q": {
                "fields": [OPERATING, REVENUE],
                "attributes": FIELDS,
                "quarters": QUARTERS,
                "report_format": REPORT_FORMAT,
                "revenue_min": REVENUE_MIN,
                "latest": LATEST_RULE,
                "needed": NEEDED_RULE,
                "number": r15.NUMBER_RULE,
                "statements": STATEMENT_RULE,
                "formula": OP_MARGIN,
                "reference": AB1_REFERENCE,
            },
            "no_news_20": {
                "source": [NEWS_SOURCE, NEWS_EVENT_TYPE],
                "sessions": NEWS_SESSIONS,
                "window": NEWS_RULE,
                "missing": NEWS_MISSING,
            },
            "momentum_20": {
                "window": r5.MOMENTUM_WINDOW,
                "rule": MOMENTUM_RULE,
                "tool": [r5.VERSION, r5.definitions_sha256()],
            },
            "overlaps": {
                P2: [r15.HYPOTHESES[P2], r15.VERSION, r15.definitions_sha256()],
                G1: [r18.HYPOTHESES[G1], r18.VERSION, r18.definitions_sha256()],
                X4: [ex.HYPOTHESES[X4], ex.VERSION],
                V2: [r5.HYPOTHESES[V2], r5.VERSION, r5.definitions_sha256()],
                Y4: [r7.HYPOTHESES[Y4], r7.VERSION, r7.definitions_sha256()],
            },
            "listed": [INDUSTRY_RULE, DELISTED_STATUS],
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
    AB1's two fields, format, latest quarter, 4 quarters, needed rows, single
    quarters, Σrev ≤ 0 and the reference; AB2's source, 20 sessions,
    calendar window with T, momentum_20; N and K, the order, the overlaps'
    lists, the segments, the costs).  A changed tool needs a new exploration
    report before a validation."""

    text = json.dumps(definitions(), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- the context ------------------------------------------------------------------


@dataclass
class Context:
    """``explore_research``'s context (the market, the quotes, the EPS
    quarters, the MOPS list), AB1's and P2's statements
    (``round15_research.load_statements``), G1's
    (``round18_research.load_nonop_statements``), the instruments' status,
    the member table, and the contexts ``round15_research`` (P2),
    ``round5_research`` (V2) and ``round7_research`` (Y4) rank with (the same
    base).  One panel."""

    base: ex.Context
    statements: dict[int, list[r15.Statement]] = field(default_factory=dict)
    nonop_statements: dict[int, list[r18.NonopStatement]] = field(default_factory=dict)
    statuses: dict[int, str] = field(default_factory=dict)
    groups: ms.Context | None = None
    p2: r15.Context | None = None
    v2: r5.Context | None = None
    y4: r7.Context | None = None
    seconds: Counter = field(default_factory=Counter)
    load_seconds: dict[str, float] = field(default_factory=dict)
    # AB2: each instrument's sorted dates with an announcement (once)
    news: dict[int, list[date]] | None = None
    # AB1: T's instrument -> group (L4's smallest group id), by T
    industries: dict[date, dict[int, str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.p2 is None:
            self.p2 = r15.Context(self.base, self.statements, self.statuses)
        if self.v2 is None:
            self.v2 = r5.Context(self.base)
        if self.y4 is None:
            self.y4 = r7.Context(self.base, self.groups)

    @property
    def g1(self) -> SimpleNamespace:
        """What ``round18_research.nonop_q`` reads (its statements only)."""

        return SimpleNamespace(statements=self.nonop_statements)

    @property
    def market(self) -> pr.Market:
        return self.base.market

    @property
    def panel(self) -> lib.Panel:
        return self.base.market.panel

    def quote(self, instrument_id: int, s: int) -> pr.Quote | None:
        return self.base.quote(instrument_id, s)


def load(db: Path, members: Path, start: date, end: date, raw_dir: Path) -> Context:
    """The panel (with the MOPS list), the turnovers, the EPS quarters,
    AB1's and P2's statements, G1's, the statuses and the member snapshots
    to ``end``; nothing after ``end`` is read."""

    started = time.monotonic()
    base = ex.load_context(db, start, end, raw_dir)
    panel_seconds = time.monotonic() - started
    t0 = time.monotonic()
    series = base.market.panel.series
    statements = r15.load_statements(db, series, end)
    statuses = r15.load_statuses(db)
    statement_seconds = time.monotonic() - t0
    t0 = time.monotonic()
    nonop_statements = r18.load_nonop_statements(db, series, end)
    list_seconds = time.monotonic() - t0
    t0 = time.monotonic()
    groups = ms.build_context(base.market, ms.read_members(members, end))
    return Context(
        base,
        statements,
        nonop_statements,
        statuses,
        groups,
        load_seconds={
            "panel": panel_seconds,
            "statements": statement_seconds,
            "lists": list_seconds,
            "members": time.monotonic() - t0,
        },
    )


def columns_2013(db: Path) -> dict[str, Any]:
    """AB1 (``--coverage-only``): 2013's column names by quarter and
    report_format, and the rows with each field (``round15_research``'s, P2's
    table: AB1 reads two of its fields)."""

    return r15.columns_2013(db)


# --- AB1: op_margin_4q ------------------------------------------------------------


_known = r15._known
_quarter_before = r15._quarter_before
_quarter_back = r15._quarter_back
single_quarter = r15.single_quarter


def _quarters(quarter: date) -> list[date]:
    """q, q − 1, q − 2, q − 3."""

    return [_quarter_back(quarter, k) for k in range(QUARTERS)]


def _needed(quarter: date) -> list[date]:
    """q .. q − 3 and the quarter before each that is not a Q1."""

    out = []
    for end in _quarters(quarter):
        out.append(end)
        if end.month != 3:
            out.append(_quarter_before(end))
    return list(dict.fromkeys(out))


def _singles(known: dict[date, r15.Statement], quarter: date):
    """([op(q − k)], [rev(q − k)]) for k = 0 .. 3, or None when one is missing."""

    out = []
    for name in FIELDS:
        cumulative = {
            end: getattr(row, name)
            for end, row in known.items()
            if getattr(row, name) is not None
        }
        values = [single_quarter(cumulative, end) for end in _quarters(quarter)]
        if any(value is None for value in values):
            return None
        out.append(values)
    return tuple(out)


@dataclass(frozen=True)
class Margin:
    value: float | None
    # "stale", "format", "fields", "revenue" or None
    reason: str | None = None
    operating: float | None = None  # Σ op(q − k)
    revenue: float | None = None  # Σ rev(q − k)


def op_margin_4q(ctx: Context, item: lib.Series, day: date, quarter: date) -> Margin:
    """AB1 第 1～4 點 on T (``day``) for the deadline's ``quarter``."""

    known = _known(ctx.statements.get(item.instrument_id, []), day)
    if not known or max(known) != quarter:
        return Margin(None, "stale")
    rows = [known.get(end) for end in _needed(quarter)]
    if any(
        row is not None
        and row.report_format is not None
        and row.report_format != REPORT_FORMAT
        for row in rows
    ):
        return Margin(None, "format")
    if any(
        row is None
        or row.report_format != REPORT_FORMAT
        or any(getattr(row, name) is None for name in FIELDS)
        for row in rows
    ):
        return Margin(None, "fields")
    singles = _singles(known, quarter)
    if singles is None:
        return Margin(None, "fields")
    operating, revenue = (math.fsum(values) for values in singles)
    if revenue <= REVENUE_MIN:
        return Margin(None, "revenue", operating, revenue)
    return Margin(operating / revenue, None, operating, revenue)


def fields_missing(ctx: Context, item: lib.Series, day: date, quarter: date) -> bool:
    """AB1 第 3 點 second case on the deadline's ``quarter`` (the reference's
    rule, 第二十輪實作釋義): a needed row not known on T or a field missing."""

    known = _known(ctx.statements.get(item.instrument_id, []), day)
    for end in _needed(quarter):
        row = known.get(end)
        if row is None or any(getattr(row, name) is None for name in FIELDS):
            return True
    return _singles(known, quarter) is None


# --- AB2: no_news_20 --------------------------------------------------------------


def news_days(ctx: Context) -> dict[int, list[date]]:
    """Each instrument's sorted dates with at least one announcement
    (``explore_research.load_context``'s MOPS list, its listed date, any
    title; several on a day once)."""

    if ctx.news is None:
        days: dict[int, set[date]] = defaultdict(set)
        for _at, instrument_id, _title, listed in ctx.base.announcements:
            days[instrument_id].add(listed)
        ctx.news = {i: sorted(found) for i, found in days.items()}
    return ctx.news


def no_news_20(ctx: Context, instrument_id: int, s: int) -> bool:
    """AB2 第 2 點 on T (session ``s``): no announcement on any calendar day
    of (session s − 20, T]."""

    sessions = ctx.panel.sessions
    day = sessions[s]
    found = news_days(ctx).get(instrument_id)
    if not found:
        return True
    if s >= NEWS_SESSIONS:
        lo = bisect_right(found, sessions[s - NEWS_SESSIONS])
    else:
        lo = bisect_left(found, sessions[0])
    return not (lo < len(found) and found[lo] <= day)


# --- the plans --------------------------------------------------------------------


def segment_window(
    sessions: list[date], segment: str, spec: dict[str, Any]
) -> tuple[int, int] | None:
    """(first, last) index of the sessions with an equity value, or None.
    AB1's equity starts the session after its first event day in the segment
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
    reference: dict[int, list[int]] = field(default_factory=dict)  # AB1
    dues: dict[int, int] = field(default_factory=dict)  # AB1
    rows: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    signal_days: int = 0
    event_days: int = 0
    overlap: dict[str, dict[str, list[float]]] = field(default_factory=dict)
    industries: dict[str, list[int]] = field(default_factory=dict)  # AB1, by year
    delisted: dict[str, list[int]] = field(default_factory=dict)  # AB2: [names, gone]
    rebalances: list[dict[str, Any]] = field(default_factory=list)  # AB1


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
    on P2's own statements, the first 20 by the hash; it times ``p2_order``)."""

    return r16.p2_names(ctx, day, members, quarter)


def g1_names(ctx: Context, day, members, quarter) -> set[int]:
    """G1's list on ``day`` (``round18_research`` 第 1 版的定義: ``nonop_q`` on
    G1's own statements, ranked as ``round18_research.plan_g1``)."""

    def run() -> set[int]:
        spec = r18.HYPOTHESES[G1]
        keys = tuple(spec["keys"])
        g1 = ctx.g1
        rows = sorted(
            (
                r5.order_key(
                    {keys[0][0]: r18.nonop_q(g1, item, day, quarter).value},
                    keys,
                    pr.tie_break(day, item.instrument_id),
                ),
                item.instrument_id,
            )
            for item, _k in members
        )
        return {instrument_id for _key, instrument_id in rows[: spec["top"]]}

    return _timed(ctx, "g1_order", run)


def x4_names(ctx: Context, day, members) -> set[int]:
    """X4's list (``round14_research.x4_names``: ``explore_research._rank``)."""

    return r14.x4_names(ctx, day, members)


def v2_names(ctx: Context, day, members) -> set[int]:
    """V2's list on ``day`` (``round5_research`` 第 1 版的定義, not rewritten)."""

    def run() -> set[int]:
        spec = r5.HYPOTHESES[V2]
        rows = r5.rank(ctx.v2, spec, day, members).rows
        return {row[0] for row in rows[: spec["top"]]}

    return _timed(ctx, "v2_order", run)


def y4_names(ctx: Context, day, members) -> set[int]:
    """Y4's list on ``day`` (``round7_research`` 第 1 版的定義, not rewritten)."""

    def run() -> set[int]:
        spec = r7.HYPOTHESES[Y4]
        rows = r7.rank(ctx.y4, spec, day, members).rows
        return {row[0] for row in rows[: spec["top"]]}

    return _timed(ctx, "y4_order", run)


def groups_of(ctx: Context, day: date) -> dict[int, str] | None:
    """T's instrument -> group (the smallest group id, L4's); None without a
    member table."""

    if ctx.groups is None:
        return None
    found = ctx.industries.get(day)
    if found is None:
        found = {}
        for group_id, ids in ms.group_members(ctx.groups, day)[0].items():
            for instrument_id in ids:
                if instrument_id not in found or group_id < found[instrument_id]:
                    found[instrument_id] = group_id
        ctx.industries = {day: found}  # one T at a time
    return found


def industry_count(ctx: Context, day: date, names: list[int]) -> int | None:
    """AB1 第 8 點: the industries of the list (``round11_research.industry_count``)."""

    t0 = time.perf_counter()
    try:
        groups = groups_of(ctx, day)
        return None if groups is None else r11.industry_count(names, groups)
    finally:
        ctx.seconds["industries"] += time.perf_counter() - t0


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


def plan_ab1(
    ctx: Context, spec: dict[str, Any], first: int, last: int, keep_rows=True
) -> Plan:
    """AB1 第 1～8 點: the event days of the segment, ``op_margin_4q`` in T's
    population high first, 20, held to the next event day (X7); the
    reference population on the same days."""

    panel = ctx.panel
    sessions = panel.sessions
    out = Plan(overlap={"AB1_P2": {}, "AB1_G1": {}, "AB1_X4": {}})
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
            got = op_margin_4q(ctx, item, day, quarter)
            reasons[got.reason] += 1
            rows.append((item, got, pr.tie_break(day, item.instrument_id)))
        ctx.seconds["op_margin_4q"] += time.perf_counter() - t0
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
            "negative": sum(1 for got in valued if got.value < 0),
        }
        for key in ("valued", "delisted", "delisted_missing", "zero", "negative"):
            _add(year, key, event[key])
        year.setdefault("events", []).append(event)
        others = {
            "AB1_P2": p2_names(ctx, day, members, quarter),
            "AB1_G1": g1_names(ctx, day, members, quarter),
            "AB1_X4": x4_names(ctx, day, members),
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
        count = industry_count(ctx, day, names)
        if count is not None:
            out.industries.setdefault(str(day.year), []).append(count)
        out.rebalances.append(
            {**event, "p2_overlap": shares["AB1_P2"], "g1_overlap": shares["AB1_G1"],
             "x4_overlap": shares["AB1_X4"], "industries": count}
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
                    {"quarter": quarter.isoformat(), "op_margin_4q": got.value,
                     "operating_4q": got.operating, "revenue_4q": got.revenue},
                    tie,
                )
            )  # fmt: skip
    return out


def plan_ab2(
    ctx: Context, spec: dict[str, Any], first: int, last: int, keep_rows=True
) -> Plan:
    """AB2 第 1～5、7 點 on the signal dates ``first − 1`` .. ``last − 1``."""

    panel = ctx.panel
    out = Plan(overlap={"AB2_V2": {}, "AB2_Y4": {}})
    top = spec["top"]
    keys = tuple(spec["keys"])
    for at in range(first - 1, last):
        day = panel.sessions[at]
        members = lib.universe(panel, day, MIN_LOTS)
        year = _year(out.coverage, day, len(members))
        out.signal_days += 1
        t0 = time.perf_counter()
        found = [
            (item, k) for item, k in members if no_news_20(ctx, item.instrument_id, at)
        ]
        ctx.seconds["no_news_20"] += time.perf_counter() - t0
        t0 = time.perf_counter()
        rows = []
        for item, k in found:
            value = r5.momentum_20(ctx.v2, item, k)
            rows.append((item, value, pr.tie_break(day, item.instrument_id)))
        ctx.seconds["momentum_20"] += time.perf_counter() - t0
        rows.sort(key=lambda row: r5.order_key({keys[0][0]: row[1]}, keys, row[2]))
        chosen = rows[:top]
        hits_gone = sum(
            1
            for item, _k in found
            if ctx.statuses.get(item.instrument_id) == DELISTED_STATUS
        )
        _add(year, "hits", len(found))
        _add(year, "hits_delisted", hits_gone)
        _add(
            year, "momentum_missing", sum(1 for _i, value, _t in rows if value is None)
        )
        _add(year, "names", len(chosen))
        _add(year, "short_days", int(len(found) < top))
        _add(year, "empty_days", int(not found))
        others = {
            "AB2_V2": v2_names(ctx, day, members),
            "AB2_Y4": y4_names(ctx, day, members),
        }  # timed in the coverage too
        if not keep_rows:
            continue
        names = [item.instrument_id for item, _v, _t in chosen]
        for key, other in others.items():
            share = r10.overlap_share(names, other)
            if share is not None:
                out.overlap[key].setdefault(str(day.year), []).append(share)
        counts = out.delisted.setdefault(str(day.year), [0, 0])
        counts[0] += len(names)
        counts[1] += sum(1 for i in names if ctx.statuses.get(i) == DELISTED_STATUS)
        out.picks[at + 1] = names
        out.population[at + 1] = [item.instrument_id for item, _ in members]
        for place, (item, value, tie) in enumerate(chosen, 1):
            out.rows.append(
                _pick_row(ctx, day, place, item.instrument_id,
                          {"no_news_20": True, "momentum_20": value}, tie)
            )  # fmt: skip
    return out


def planner(name: str) -> Callable[..., Plan]:
    return {"AB1": plan_ab1, "AB2": plan_ab2}[name]


overlap_share = r10.overlap_share
overlap_summary = r10.overlap_summary
industries_summary = r11.industries_summary
_window_facts = r5._window_facts


def delisted_summary(by_year: dict[str, list[int]]) -> dict[str, Any]:
    """AB2 第 7 點: the list's later delisted names over its names, by year
    and over the segment."""

    names = sum(n for n, _g in by_year.values())
    gone = sum(g for _n, g in by_year.values())
    return {
        "names": names,
        "delisted": gone,
        "share": gone / names if names else None,
        "years": {
            year: {"names": n, "delisted": g, "share": g / n if n else None}
            for year, (n, g) in sorted(by_year.items())
        },
    }


def news_by_year(ctx: Context) -> dict[str, dict[str, int]]:
    """AB2 (``--coverage-only``): the MOPS list's rows by year of the listed
    date, the instruments with one and those later delisted among them."""

    rows: Counter = Counter()
    ids: dict[str, set[int]] = defaultdict(set)
    for _at, instrument_id, _title, listed in ctx.base.announcements:
        rows[str(listed.year)] += 1
        ids[str(listed.year)].add(instrument_id)
    return {
        year: {
            "rows": rows[year],
            "instruments": len(ids[year]),
            "delisted": sum(
                1 for i in ids[year] if ctx.statuses.get(i) == DELISTED_STATUS
            ),
        }
        for year in sorted(rows)
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
) -> tuple[pr.Simulation, pr.Simulation, pr.Simulation | None]:
    """(the hypothesis, the population, the reference): AB1 X7's account with
    its reference, AB2 K accounts."""

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
    """AB1 or AB2 on one segment: its numbers, verdict and private parts."""

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
    if spec["engine"] == EVENTS:
        result["industries"] = industries_summary(planned.industries)
    else:
        result["delisted"] = delisted_summary(planned.delisted)
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


def _point(name: str) -> str:
    return "AB1 第 8 點" if name == "AB1" else "AB2 第 7 點"


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
    """AB1 each event day and by year, AB2 by year."""

    if name == "AB1":
        head = ["事件日", "對應的季", "母體檔次", "有 `op_margin_4q` 的檔數", "缺值的檔數",
                "名單檔數", "最新一季不是對應的那一季", "`report_format` 不是 `general`",
                "4 季中有欄位缺", "（比例）", "分母 ≤ 0", "母體裡的下市、轉板股",
                "（其中缺所需欄位）", "Σop＝0", "Σop < 0"]  # fmt: skip
        lines = [
            "| " + " | ".join(head) + " |",
            "| --- | --- | " + " | ".join("---:" for _ in head[2:]) + " |",
        ]
        for _year_, row in sorted(coverage.items()):
            for e in row.get("events", []):
                lines.append(
                    f"| {e['signal_date']} | {e['quarter']} | {e['members']:,} | {e['valued']:,} "
                    f"| {e['members'] - e['valued']:,} | {e['names']:,} | {e['stale']:,} "
                    f"| {e['format']:,} | {e['fields']:,} | {_share(e['fields'], e['members'])} "
                    f"| {e['revenue']:,} | {e['delisted']:,} | {e['delisted_missing']:,} "
                    f"| {e['zero']:,} | {e['negative']:,} |"
                )
        lines += ["", "依年：", "",
                  "| 年 | 事件日 | 母體檔次 | 有 `op_margin_4q` 的檔次 | 母體裡的下市、轉板股檔次 "
                  "| 其中缺 `op_margin_4q` 所需欄位（對照基準去掉的） | Σop＝0 的檔次 | Σop < 0 的檔次 |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]  # fmt: skip
        for year, row in sorted(coverage.items()):
            lines.append(
                f"| {year} | {row['days']:,} | {row['members']:,} | {row.get('valued', 0):,} "
                f"| {row.get('delisted', 0):,} | {row.get('delisted_missing', 0):,} "
                f"| {row.get('zero', 0):,} | {row.get('negative', 0):,} |"
            )
        return lines
    head = ["年", "日數", "母體檔次", "`no_news_20` 成立的檔次", "（比例）",
            "其中之後下市的檔次", "成立的檔中 `momentum_20` 缺值", "名單檔次",
            "成立的不足 20 檔的訊號日", "沒有一檔成立的訊號日"]  # fmt: skip
    lines = [
        "| " + " | ".join(head) + " |",
        "| --- | " + " | ".join("---:" for _ in head[1:]) + " |",
    ]
    for year, row in sorted(coverage.items()):
        members, hits = row["members"], row.get("hits", 0)
        lines.append(
            f"| {year} | {row['days']:,} | {members:,} | {hits:,} | {_share(hits, members)} "
            f"| {row.get('hits_delisted', 0):,} | {row.get('momentum_missing', 0):,} "
            f"| {row.get('names', 0):,} | {row.get('short_days', 0):,} "
            f"| {row.get('empty_days', 0):,} |"
        )
    return lines


def news_lines(news: dict[str, dict[str, int]]) -> list[str]:
    lines = [
        "| 年 | 則數 | 有公告的檔數 | 其中之後下市的檔數 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for year, row in news.items():
        lines.append(
            f"| {year} | {row['rows']:,} | {row['instruments']:,} | {row['delisted']:,} |"
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
        f"# {name} {segment}（round20_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- {OVERLAP_NOTE['summary_only']}",
    ]
    if name == "AB1":
        lines += [OVERLAP_NOTE["AB1_survivor"], f"- {OVERLAP_NOTE['AB1_proxy']}"]
    else:
        lines += [OVERLAP_NOTE["AB2_survivor"]]
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
        "## 每次調倉（AB1 第 8 點，只列出、不判定）",
        "",
        OVERLAP_NOTE["AB1_listed"] + "；" + OVERLAP_NOTE["AB1_industries"] + "。",
        "",
        "| 事件日 | 對應的季 | 母體檔次 | 有 `op_margin_4q` | 名單檔數 | 投入比例 | 產業數 "
        "| 和 P2 的重疊 | 和 G1 的重疊 | 和 X4 的重疊 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *(
            f"| {e['signal_date']} | {e['quarter']} | {e['members']:,} | {e['valued']:,} "
            f"| {e['names']:,} | {_pct(e.get('invested'), 1)} "
            f"| {'—' if e['industries'] is None else e['industries']} "
            f"| {_pct(e['p2_overlap'], 1)} | {_pct(e['g1_overlap'], 1)} "
            f"| {_pct(e['x4_overlap'], 1)} |"
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


def _delisted_lines(summary: dict[str, Any]) -> list[str]:
    lines = [
        "## 名單裡之後下市的比例（AB2 第 7 點，只列出、不判定）",
        "",
        OVERLAP_NOTE["AB2_delisted"] + "。",
        "",
        "| 年 | 名單檔次 | 之後下市的檔次 | 比例 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for year, row in summary["years"].items():
        lines.append(
            f"| {year} | {row['names']:,} | {row['delisted']:,} | {_pct(row['share'], 1)} |"
        )
    lines += [
        f"| 全段 | {summary['names']:,} | {summary['delisted']:,} "
        f"| {_pct(summary['share'], 1)} |",
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
        lines += _yearly_lines(
            f"## 和 {key.split('_')[1]} 的重疊（{_point(name)}）",
            OVERLAP_NOTE[key],
            summary,
            lambda v: _pct(v, 1),
        )
    if result.get("industries"):
        lines += _yearly_lines(
            f"## 名單涉及的產業數（{_point(name)}，只列出、不判定）",
            OVERLAP_NOTE["AB1_industries"],
            result["industries"],
            lambda v: lib.num(v, 1),
        )
    if result.get("delisted"):
        lines += _delisted_lines(result["delisted"])
    if result.get("coverage"):
        lines += ["## 資料覆蓋（不含報酬）", ""]
        if name == "AB2":
            lines += [OVERLAP_NOTE["AB2_listed"] + "。", ""]
        lines += [*coverage_lines(name, result["coverage"]), ""]
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
    if result.get("industries"):
        row["industries"] = {k: result["industries"][k] for k in ("days", "mean")}
    if result.get("delisted"):
        row["delisted"] = {
            k: result["delisted"][k] for k in ("names", "delisted", "share")
        }
    if "reference" in (result.get("excess") or {}):
        row["reference_excess"] = result["excess"]["reference"]
    if result.get("rebalances"):
        row["names"] = statistics.fmean(e["names"] for e in result["rebalances"])
        row["valued"] = statistics.fmean(e["valued"] for e in result["rebalances"])
    if result.get("coverage") and result["engine"] == PORTFOLIO:
        members = sum(y["members"] for y in result["coverage"].values())
        hits = sum(y.get("hits", 0) for y in result["coverage"].values())
        row["hits_share"] = hits / members if members else None
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
        f"# 新策略探索 第 {report['round']} 輪 {stage}（round20_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「第二十輪：AB1、AB2」）：{DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        _threshold_line(segment, report["min_t"]),
        "- 引擎：AB1 是 X7 的事件日帳戶（`explore_research.simulate_events`），AB2 是組合引擎"
        "（`portfolio_research.simulate`，K＝20）；日數是有淨值的交易日",
        f"- AB1、AB2：{OVERLAP_NOTE['summary_only']}",
        f"- AB1：{OVERLAP_NOTE['AB1_proxy']}",
        OVERLAP_NOTE["AB1_survivor"],
        OVERLAP_NOTE["AB2_survivor"],
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
                f"- {name} 每次調倉的名單檔數：平均 {lib.num(row['names'], 1)}；"
                f"每個事件日有 `op_margin_4q` 的檔數：平均 {lib.num(row.get('valued'), 1)}"
            )
        if row.get("industries"):
            part = row["industries"]
            listed.append(
                f"- {name} 名單涉及的產業數：平均 {lib.num(part['mean'], 1)}（{part['days']:,} 個事件日）"
            )
        for other in (P2, G1, X4, V2, Y4):
            part = row.get(f"overlap_{other.lower()}")
            if part:
                listed.append(
                    f"- {name} 和 {other} 的重疊：平均 {_pct(part['mean'], 1)}（{part['days']:,} 個訊號日）"
                )
        if row.get("hits_share") is not None:
            listed.append(
                f"- {name} 母體裡 `no_news_20` 成立的比例：{_pct(row['hits_share'], 1)}"
            )
        if row.get("delisted"):
            part = row["delisted"]
            listed.append(
                f"- {name} 名單裡之後下市的比例：{_pct(part['share'], 1)}"
                f"（{part['delisted']:,}／{part['names']:,} 檔次）"
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
    f"- AB1：{DEGENERATE['AB1']}。每個事件日一列，缺值的原因依序判（最新一季、格式、4 季中有欄位缺、分母 ≤ 0），"
    "每檔只算第一個；「母體裡的下市、轉板股」是 `status` 為 `delisted`／`transferred` 的母體檔次，"
    "「其中缺所需欄位」是對照基準去掉的檔次；「Σop＝0」「Σop < 0」只數有 `op_margin_4q` 的檔；"
    "`p2_order`、`g1_order`、`x4_order` 是同一個 T 算 P2、G1、X4 名單的時間"
    "（X4 的 `_rank` 另記它自己的特徵），`--coverage-only` 不算重疊比例、產業數與投入比例，各段的 `summary.md` 才列",
    f"- AB2：{DEGENERATE['AB2']}。依年一列：「`no_news_20` 成立的檔次」與比例（分母是母體檔次）、"
    "其中標的 `status` 是 `delisted` 的檔次（之後下市）、成立的檔中 `momentum_20` 缺值的檔次、名單檔次、"
    "成立的不足 20 檔與沒有一檔成立的訊號日數；重大訊息依清單日期的年列則數、有公告的檔數與其中之後下市的檔數"
    "（`explore_research.load_context` 讀的 `events`，讀到探索段最後一天）；`v2_order`、`y4_order` 是同一個 T "
    "算 V2、Y4 名單的時間，`--coverage-only` 不算重疊比例與名單裡之後下市的比例，各段的 `summary.md` 才列",
    "- 各假設用自己的訊號日（起日寫在各段標題）",
)


def columns_lines(columns: dict[str, Any]) -> list[str]:
    fields = (OPERATING, REVENUE)
    lines = [
        "| 季 | `report_format` | 列數 | "
        + " | ".join(f"`{n}`" for n in fields)
        + " |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for quarter, kinds in columns.items():
        for kind, part in kinds.items():
            lines.append(
                f"| {quarter} | {kind} | {part['rows']:,} | "
                + " | ".join(f"{part['fields'].get(n, 0):,}" for n in fields)
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
        f"# 新策略探索 第 {body['round']} 輪 AB1、AB2 資料覆蓋（探索段，不含報酬）",
        "",
        f"- round20_research 第 {VERSION} 版；定義雜湊 `{body['definitions_sha256']}`",
        f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}，"
        f"alembic `{body['copy']['alembic']}`",
        f"- 重現：`{body['command']}`",
        f"- 耗時 {body.get('elapsed_seconds', 0):.0f} 秒（載入 {body.get('load_seconds', 0):.0f} 秒，"
        f"其中 panel（含重大訊息清單）{load_seconds.get('panel', 0):.0f} 秒、季報其他欄位（AB1、P2）與標的狀態 "
        f"{load_seconds.get('statements', 0):.0f} 秒、重疊用的季報（G1）"
        f"{load_seconds.get('lists', 0):.0f} 秒、成員表 {load_seconds.get('members', 0):.0f} 秒；"
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
    if body.get("news"):
        lines += [
            "## AB2：重大訊息依年（`events` 的 `material_information`，清單日期的年）",
            "",
            *news_lines(body["news"]),
            "",
        ]
    if body.get("columns_2013"):
        lines += [
            "## AB1：2013 年各季的欄名（`fundamental_snapshots.data_json`，期末在 2013 年的列）",
            "",
            *columns_lines(body["columns_2013"]),
            "",
        ]
    lines += [
        "有明顯斷點或缺值比例異常的年份、AB1 某個事件日有值的檔數不到 20、2013 年的欄名不是 "
        "`營業利益（損失）`／`營業收入`、AB2 某一年 `no_news_20` 成立的比例接近 0 或接近 100%，"
        "或 2014 年前後重大訊息的則數或有公告的檔數有斷點時，先在工具單提問、不跑探索段。",
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
    news = news_by_year(ctx)
    t0 = time.monotonic()
    columns = columns_2013(db)
    body = {
        **public(header),
        "coverage_only": True,
        "hypotheses": hypotheses,
        "news": news,
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
    parser = argparse.ArgumentParser(prog="round20_research.py", description=__doc__)
    parser.add_argument(
        "--db", required=True, help="the research DB (/research/stock.db)"
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--segment", required=True, choices=STAGES)
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    parser.add_argument(
        "--members",
        help="the #779 member table (default: research/industry_members/"
        "industry_members_v1.json beside the DB); AB1's industries and AB2's "
        "overlap with Y4 only",
    )
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help="exploration only: counts of dates, members and missing values "
        "and the time of the features, no return",
    )
    parser.add_argument(
        "--hypotheses",
        help="exploration (required, not with --coverage-only): AB1, AB2 or "
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
    command = "python tools/research/round20_research.py " + " ".join(argv)
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
