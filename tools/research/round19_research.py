"""Round 19 of the new-strategy exploration: D1, D2 (#1047).

docs/spec/evidence.md 第十九輪：D1、D2 and 第十九輪實作釋義: the hypotheses
were registered (commit ``e064372b``, #1038, decision 7188394589) before
anyone ran a tool on the backfilled history.  Nothing here is a command-line
option: a change of a definition is a new code.

They are not in ``explore_research.HYPOTHESES``, ``trade_research.HYPOTHESES``
nor ``round4_research`` .. ``round18_research``: their ``definitions_sha256``
hash the whole table, so adding them would make the validation refuse the
exploration reports already run.  D1 trades on ``portfolio_research.simulate``
(K 60), D2 on X7's event-day account (``explore_research.simulate_events``);
the population, the loading (``explore_research.load_context``),
``explore_judge``, the gate and the ledgers are imported.  D2's event days
are ``round14_research.quarter_events``, its latest quarter K2's reading
(``round14_research.eps_turn``: the rows with an EPS) and its single quarters
``round15_research.single_quarter`` (``feature_evidence._quarter_eps``
itself).  The overlaps take Z2 (``round8_research.rank``), W2
(``round6_research.rank``), V1 (``round5_research.rank``), X4
(``round14_research.x4_names``), K2 (``round15_research.k2_names``) and P2
(``round16_research.p2_names``) on the same T, and ``round10_research``'s
``overlap_share``／``overlap_summary``; the listed means ``skew_240``,
``vol_60`` and ``reversal_720_240`` are round8's, round5's and round6's.  New
here are only ``tk_60``, ``eps_streak_4`` and the listed numbers.

Each signal date T (after its close, only T's data and before):

- D1: ``tk_60`` (the cumulative prospect theory value of the 60 twenty-day
  excess returns over the TAIEX of the last 1,200 market sessions) small
  first, 20, K 60.
- D2: on the 4 statutory deadlines, ``eps_streak_4`` (the latest 4 single
  quarters each above the same quarter's a year before), 20 by the hash,
  held to the next event day (X7).

``explore_research.explore_judge`` judges with t ≥ 2 on the exploration and
the fixed Bonferroni t ≥ 3.376 (68 hypotheses) on the validation.  Before the
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
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_lib as lib  # noqa: E402
import exit_research as er  # noqa: E402
import explore_research as ex  # noqa: E402
import feature_evidence as features  # noqa: E402
import portfolio_research as pr  # noqa: E402
import round5_research as r5  # noqa: E402
import round6_research as r6  # noqa: E402
import round8_research as r8  # noqa: E402
import round10_research as r10  # noqa: E402
import round14_research as r14  # noqa: E402
import round15_research as r15  # noqa: E402
import round16_research as r16  # noqa: E402

VERSION = 1
DESIGN = "1047"
TOOL = "round19_research"
REGISTRATION_COMMIT = "e064372b"
DECISION = (
    "https://github.com/YiCheng0608/stock-lab/issues/1038#issuecomment-7188394589"
)
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
SEGMENTS = dict(ex.SEGMENTS)
MIN_SEGMENT_DAYS = dict(ex.MIN_SEGMENT_DAYS)
MIN_T = ex.MIN_T  # the exploration's t ≥ 2
# docs 第十九輪 門檻: 1 − Φ(z) = 0.025 ÷ 68, z = 3.3761, 3.376 to the 3rd decimal;
# fixed, not computed when run.
VALIDATION_MIN_T = 3.376
ROUND = 19
ROUND_SIZE = 2
# X1～X8, S1～S3, R1～R2, M1～M2, C1～C4, V1～V3, W1～W4, Y1～Y4, Z1～Z4, B1～B3,
# F1～F4, L1～L4, J1～J4, U1～U3, K1～K3, P1～P3, N1～N3, A1～A3, G1～G2, D1～D2
CUMULATIVE = 68
# Every segment reads the copy from its start, as round10_research ..
# round18_research: D1 reads 1,201 sessions.
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
    "D1 by the feature, small first (round5_research.order_key), missing last; "
    "D2 not ranked, the first N qualifying by the hash; ties and the "
    "qualifying ones by sha256(<T>:<instrument_id>); a missing condition fails"
)
SHORT_RULE = "cash, not filled"
SALE = (
    "D2 one account (X7): bought at T+1's open, 1/20 of the cash each, sold at "
    "the close of the next event day T' (explore_research.simulate_events), the "
    "new list bought at T'+1's open; the population on the same rule and event "
    "days"
)
REFERENCE_STATUSES = ("delisted", "transferred")  # D2's coverage, listed only
SINGLE_QUARTER = r15.SINGLE_QUARTER

# D1 (第 1～5 點)
TK_SESSIONS = 61  # s_0 .. s_60
TK_STEP = 20  # market sessions between two sampling days
TK_SEGMENTS = 60  # x_1 .. x_60, each 1/60
ALPHA = 0.88
LAMBDA = 2.25
GAMMA = 0.61  # w+
DELTA = 0.69  # w-
ZERO_SIDE = "gain"  # x_k = 0 is on the gains' side
TK_SAMPLE = (
    "s_j = Panel.sessions T - 1200 + 20 j, j = 0 .. 60 (market sessions, not "
    "the item's bars); the item's adjusted close (Series.close) on each, a "
    "suspended bar with a close counted; bars between the sampling days not "
    "read; the TAIEX close (twse_index) on the same days"
)
TK_RETURNS = (
    "r_k = close(s_k) / close(s_(k-1)) - 1, m_k the TAIEX's, x_k = r_k - m_k, "
    "k = 1 .. 60"
)
TK_VALUE = "v(x) = x^alpha (x >= 0), -lambda (-x)^alpha (x < 0)"
TK_WEIGHT = "w(P) = P^c / (P^c + (1 - P)^c)^(1/c); w+ c = gamma, w- c = delta"
TK_RULE = (
    "x sorted ascending, m losses (x < 0) and n gains (x >= 0), ties side by "
    "side each 1/60; TK = sum_i v(x_(-i)) [w-((m-i+1)/60) - w-((m-i)/60)] + "
    "sum_i v(x_(i)) [w+((n-i+1)/60) - w+((n-i)/60)]: the losses cumulated from "
    "the worst, the gains from the best; all 0: 0, not missing; m = 0 or n = 0: "
    "only the side there is"
)
TK_MISSING = (
    "a sampling day before the copy or a TAIEX close missing or <= 0 (every "
    "member that day); a sampling day without the item's bar; an adjusted close "
    "missing or <= 0 on one: missing, ranked last, not dropped"
)
MARKET_RULE = "the market part (the 61 sampling days, m_k) once per T, shared"
OTC_ANCHOR = date(2007, 12, 3)  # the OTC bars the tools read
Z2, W2, V1 = "Z2", "W2", "V1"  # the lists D1 overlaps with

# D2 (第 1～5 點)
EPS_FIELD = "eps"  # fundamental_snapshots.eps, the year's cumulative
STREAK_QUARTERS = 4  # e(q - k) > e(q - k - 4), k = 0 .. 3
YEAR_LAG = 4  # the same quarter a year before
LATEST_RULE = (
    "K2's reading (round14_research.eps_turn): the latest quarter among the rows "
    "with announcement_date <= T and an EPS (the largest period_end) must be the "
    "deadline's quarter"
)
# #1047 決定 7190372315: each single quarter rounded to round15_research's
# EPS_DIGITS before the comparison (as P1, #984 決定 7095896595), so a
# floating remainder of the cumulative difference is not a rise.
EPS_DIGITS = r15.EPS_DIGITS
STREAK_RULE = (
    "round(e(q-k), EPS_DIGITS) > round(e(q-k-4), EPS_DIGITS) for k = 0 .. 3, all "
    "four, strictly; an equal pair fails; the sign and size of the EPS not read; "
    "not over the price"
)
STREAK_MISSING = (
    "the latest quarter not the deadline's; a single quarter of q .. q-7 missing "
    "(the cumulative of the quarter before in the same year missing too): does "
    "not qualify"
)
D2_START = date(2015, 3, 31)
X4, K2, P2 = "X4", "K2", "P2"  # the lists D2 overlaps with

# The registration (docs 第十九輪：D1、D2), word for word.  ``start`` as
# ``explore_research``.
HYPOTHESES: dict[str, dict[str, Any]] = {
    "D1": {
        "engine": PORTFOLIO,
        "direction": "投資人偏好：展望理論值",
        "label": "`tk_60`（近 1,200 個全市場交易日切成 60 段、每段 20 日，各段對加權指數的超額報酬的"
        "累積展望理論值）小者先",
        "rule": "daily",
        "keys": (("tk_60", LOW),),
        "short": SHORT_RULE,
        "top": 20,
        "hold": 60,
        "start": ("session", OTC_ANCHOR, 1201),
    },
    "D2": {
        "engine": EVENTS,
        "direction": "基本面：盈餘連續成長",
        "label": "每季法定期限的事件日，`eps_streak_4`（最新一季起連續 4 季，單季 EPS 都高於去年同季）"
        "成立，以雜湊取 20 檔、不排序",
        "rule": "quarterly",
        "conditions": (("eps_streak_4", "is", True),),
        "order": "the hash only",
        "short": SHORT_RULE,
        "top": 20,
        "hold": "next_event",
        "start": ("date", D2_START),
    },
}
OTHER_COMPARISONS = ex.OTHER_COMPARISONS
REASONS = dict(ex.REASONS)
LIMITS = {
    "D1": "定義照摘要與索引頁（[EconPapers](https://econpapers.repec.org/RePEc:oup:rfinst:v:29:y:2016:i:11:p:3068-3107.)），"
    "未讀全文；參考點由統籌在登記時事先定；20 日一段不對齊曆月；要有 1,200 日的歷史，上市未滿約 5 年的股票不會進名單；"
    "加權指數是價格指數、不含股利，同 Z3、G2；和 Z2、W2、V1、N1 的關係：Z2 的機率權重是同一個機制，名單會和 Z2 重疊，"
    "TK 也含過去 5 年報酬的水準（和 W2 長期反轉相關）與損失趨避（懲罰波動，方向和 V1 低波動相反），N1 是另一種行為權重，"
    "這四個的狀態登記時都已知，看重疊比例與名單的平均 `skew_240`、`vol_60`、`reversal_720_240`",
    "D2": "定義照摘要與索引頁（[EconPapers](https://econpapers.repec.org/RePEc:inm:ormnsc:v:58:y:2012:i:7:p:1305-1321)），"
    "未讀全文；存活者偏差：下市、轉板股仍有 76 個公司年沒有 EPS，那些季缺值、不符合，偏差方向對假設有利，缺口小，"
    "不另列對照基準；金融業等格式與法定期限不同的公司，照事件日讀不到對應的那一季時不符合，同 K2；和 X4、K2、P4 的關係："
    "X4 的 `eps_growth_yield` > 0 就是 e(q) > e(q−4)，D2 的名單都滿足它，X4、K2 的狀態登記時已知，看重疊比例",
}
# The degenerate cases as the code judges them (第十九輪實作釋義; PR #913
# review: the docs, coverage.md and summary.md say the same words, a test
# reads the docs' tool section for them).
DEGENERATE = {
    "D1": "T−1200、T−1180、…、T 這 61 個全市場交易日（`Panel.sessions`）中任一天在副本起點之前或加權指數收盤缺值或 ≤ 0"
    "（那一天母體每一檔都缺值），或任一天這一檔沒有日線，或那一根的還原收盤缺值或 ≤ 0 時缺值、排最後、不剔除；"
    "停牌根有收盤的照算，取樣日之間的停牌或缺日線不影響；60 個 xₖ 全是 0 時 `tk_60`＝0，照值排序，不是缺值；"
    "全是獲利（m＝0）或全是損失（n＝0）時只算有的那一邊；有值的不足 20 檔時以缺值的依雜湊補，母體不足 20 檔時餘額留現金",
    "D2": "最新一季（`announcement_date` ≤ T、EPS 有值的列中期末最晚的一季）不是事件日對應的那一季，"
    "或 q～q−7 任一季的單季 EPS 缺（含算單季要用的同年前一季累計缺）時不符合；e(q−k)＝e(q−k−4) 算不成長，"
    "四個之一相等就不成立；符合的不足 20 檔時餘額留現金",
}
OVERLAP_NOTE = {
    "D1_Z2": 'D1 與 Z2（`round8_research` 第 1 版的 `HYPOTHESES["Z2"]`，同一個 T 算）每日名單的重疊比例：'
    "|D1 的名單 ∩ Z2 的前 20 名| ÷ D1 當天的名單檔數；D1 或 Z2 當天沒有名單的日子不計。只列出、不判定",
    "D1_W2": 'D1 與 W2（`round6_research` 第 1 版的 `HYPOTHESES["W2"]`，同一個 T 算）每日名單的重疊比例：'
    "|D1 的名單 ∩ W2 的前 20 名| ÷ D1 當天的名單檔數；D1 或 W2 當天沒有名單的日子不計。只列出、不判定",
    "D1_V1": 'D1 與 V1（`round5_research` 第 1 版的 `HYPOTHESES["V1"]`，同一個 T 算）每日名單的重疊比例：'
    "|D1 的名單 ∩ V1 的前 20 名| ÷ D1 當天的名單檔數；D1 或 V1 當天沒有名單的日子不計。只列出、不判定",
    "D2_X4": 'D2 與 X4（`explore_research` 第 2 版的 `HYPOTHESES["X4"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|D2 的名單 ∩ X4 的前 20 名| ÷ D2 當天的名單檔數；D2 或 X4 當天沒有名單的事件日不計。只列出、不判定",
    "D2_K2": 'D2 與 K2（`round14_research` 第 1 版的 `HYPOTHESES["K2"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|D2 的名單 ∩ K2 當天的名單| ÷ D2 當天的名單檔數；D2 或 K2 當天沒有名單的事件日不計。只列出、不判定",
    "D2_P2": 'D2 與 P2（`round15_research` 第 1 版的 `HYPOTHESES["P2"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|D2 的名單 ∩ P2 當天的名單| ÷ D2 當天的名單檔數；D2 或 P2 當天沒有名單的事件日不計。只列出、不判定",
    "D1_listed": "名單的平均 `skew_240`、`vol_60`、`reversal_720_240`：每天名單中有值的檔的 "
    "`round8_research.skew_240`、`round5_research.vol_60`、`round6_research.reversal_720_240` 平均；"
    "加權指數缺值的訊號日，母體每一檔都缺值。只列出、不判定",
    "D2_listed": "每次調倉的檔數與平均投入比例、每個事件日母體中 `eps_streak_4` 成立的檔數：名單檔數是取前 20 檔之後，"
    "投入比例是買進那天收盤時部位占淨值的比例。只列出、不判定",
    "D1_reference": "- 參考點（D1）：對加權指數的超額報酬，由統籌在登記時事先定（台股母體多數期間大盤報酬為正，"
    "用原始報酬時 TK 主要反映大盤）",
    "D2_survivor": "- 存活者偏差（D2）：EPS 是研究 DB 唯一一個下市股幾乎補齊的財報欄位，但下市、轉板股仍有 76 個公司年"
    "沒有 EPS，那些季缺值、不符合，偏差方向對假設有利；缺口小，不另列對照基準（統籌決定 7188394589）",
    "summary_only": "定義照摘要與索引頁，未讀全文",
}
FEATURE_LABELS = {
    "tk_60": "展望理論值",
    "eps_streak_4": "單季 EPS 連 4 季年增",
    # the listed means (D1 第 7 點)
    "skew_240": "名單的平均 `skew_240`",
    "vol_60": "名單的平均 `vol_60`",
    "reversal_720_240": "名單的平均 `reversal_720_240`",
}
PICK_FIELDS = {
    "D1": ("tk_60", "skew_240", "vol_60", "reversal_720_240"),
    "D2": ("quarter", "eps_q", "eps_q1", "eps_q2", "eps_q3",
           "eps_q4", "eps_q5", "eps_q6", "eps_q7"),
}  # fmt: skip


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
        "deadlines": [r14.DEADLINES, r14.EVENT_DAY_RULE],  # D2's events
        "features": {
            "tk_60": {
                "sessions": TK_SESSIONS,
                "step": TK_STEP,
                "segments": TK_SEGMENTS,
                "parameters": [ALPHA, LAMBDA, GAMMA, DELTA],
                "zero": ZERO_SIDE,
                "sample": TK_SAMPLE,
                "returns": TK_RETURNS,
                "value": TK_VALUE,
                "weight": TK_WEIGHT,
                "formula": TK_RULE,
                "missing": TK_MISSING,
                "market": MARKET_RULE,
            },
            "eps_streak_4": {
                "field": EPS_FIELD,
                "quarters": STREAK_QUARTERS,
                "year_lag": YEAR_LAG,
                "latest": LATEST_RULE,
                "formula": STREAK_RULE,
                "digits": EPS_DIGITS,
                "missing": STREAK_MISSING,
                # K2's reading of the latest quarter
                "k2": [r14.VERSION, r14.definitions_sha256()],
            },
            "overlaps": {
                Z2: [r8.HYPOTHESES[Z2], r8.VERSION, r8.definitions_sha256()],
                W2: [r6.HYPOTHESES[W2], r6.VERSION, r6.definitions_sha256()],
                V1: [r5.HYPOTHESES[V1], r5.VERSION, r5.definitions_sha256()],
                X4: [ex.HYPOTHESES[X4], ex.VERSION],
                K2: [r14.HYPOTHESES[K2], r14.VERSION, r14.definitions_sha256()],
                P2: [r15.HYPOTHESES[P2], r15.VERSION, r15.definitions_sha256()],
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
    D1's 61 sampling days 20 apart from ``Panel.sessions``, the excess over
    the TAIEX, α λ γ δ, the zero on the gains' side, the cumulative weights,
    the missing rules; D2's EPS, K2's latest quarter, the single quarters,
    the four strict >, the 8 quarters; N and K, the order, the overlaps'
    lists, the segments, the costs).  A changed tool needs a new exploration
    report before a validation."""

    text = json.dumps(definitions(), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- the context ------------------------------------------------------------------


@dataclass(frozen=True)
class TkMarket:
    """D1's market part on T (once per T, every stock's): the 61 sampling
    sessions and the TAIEX's 60 returns m_k."""

    samples: tuple[int, ...]
    m: tuple[float, ...]


@dataclass
class Context:
    """``explore_research``'s context (the market, the quotes, the EPS
    quarters), the instruments' status, P2's statements and the contexts
    ``round8_research`` (Z2, ``skew_240``), ``round6_research`` (W2),
    ``round5_research`` (V1) and ``round15_research`` (P2) rank with (the same
    base).  One panel."""

    base: ex.Context
    statuses: dict[int, str] = field(default_factory=dict)
    p2_statements: dict[int, list[r15.Statement]] = field(default_factory=dict)
    z: r8.Context | None = None
    w2: r6.Context | None = None
    v1: r5.Context | None = None
    p2: r15.Context | None = None
    seconds: Counter = field(default_factory=Counter)
    load_seconds: dict[str, float] = field(default_factory=dict)
    # D1: T's market part by session, or the reason it is missing
    markets: dict[int, TkMarket | str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.z is None:
            self.z = r8.Context(self.base)
        if self.w2 is None:
            self.w2 = r6.Context(self.base)
        if self.v1 is None:
            self.v1 = r5.Context(self.base)
        if self.p2 is None:
            self.p2 = r15.Context(
                self.base, self.p2_statements, self.statuses, z4=self.z
            )

    @property
    def market(self) -> pr.Market:
        return self.base.market

    @property
    def panel(self) -> lib.Panel:
        return self.base.market.panel

    def quote(self, instrument_id: int, s: int) -> pr.Quote | None:
        return self.base.quote(instrument_id, s)


def load(db: Path, start: date, end: date, raw_dir: Path) -> Context:
    """The panel, the turnovers, the EPS quarters, the statuses and P2's
    statements to ``end``; nothing after ``end`` is read."""

    started = time.monotonic()
    base = ex.load_context(db, start, end, raw_dir)
    panel_seconds = time.monotonic() - started
    t0 = time.monotonic()
    statuses = r15.load_statuses(db)
    status_seconds = time.monotonic() - t0
    t0 = time.monotonic()
    p2_statements = r15.load_statements(db, base.market.panel.series, end)
    return Context(
        base,
        statuses,
        p2_statements,
        load_seconds={
            "panel": panel_seconds,
            "statuses": status_seconds,
            "lists": time.monotonic() - t0,
        },
    )


# --- D1: tk_60 --------------------------------------------------------------------


def probability_weight(p: float, c: float) -> float:
    """w(P) = P^c ÷ (P^c + (1 − P)^c)^(1/c) (Tversky & Kahneman 1992)."""

    a, b = p**c, (1.0 - p) ** c
    return a / (a + b) ** (1.0 / c)


@lru_cache(maxsize=None)
def decision_weights(
    gamma: float, delta: float, segments: int
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """(the losses' weights from the worst, the gains' from the best): the
    j-th is w((j + 1) ÷ n) − w(j ÷ n), w⁻ with δ and w⁺ with γ.  Once per
    parameter set, every stock's."""

    def table(c: float) -> tuple[float, ...]:
        cumulative = [probability_weight(j / segments, c) for j in range(segments + 1)]
        return tuple(cumulative[j + 1] - cumulative[j] for j in range(segments))

    return table(delta), table(gamma)


def tk_value(excess: list[float]) -> float:
    """D1 第 3 點 on the 60 x_k: losses (x < 0) weighted from the worst,
    gains (x ≥ 0, the zeros too) from the best."""

    xs = sorted(excess)
    n = len(xs)
    minus, plus = decision_weights(GAMMA, DELTA, TK_SEGMENTS)
    losses = bisect_left(xs, 0.0)  # m; a 0 is a gain
    return math.fsum(
        [
            *(-LAMBDA * (-xs[p]) ** ALPHA * minus[p] for p in range(losses)),
            *(xs[p] ** ALPHA * plus[n - 1 - p] for p in range(losses, n)),
        ]
    )


def tk_market(ctx: Context, s: int) -> TkMarket | str:
    """T's market part (T is session ``s``), or "index" when a sampling day
    is before the copy or a TAIEX close on one is missing or ≤ 0."""

    got = ctx.markets.get(s)
    if got is not None:
        return got
    first = s - TK_STEP * (TK_SESSIONS - 1)
    out: TkMarket | str = "index"
    if first >= 0:
        samples = tuple(range(first, s + 1, TK_STEP))
        sessions, index = ctx.panel.sessions, ctx.panel.index_close
        closes = [index.get(sessions[p]) for p in samples]
        if all(close is not None and close > 0 for close in closes):
            m = tuple(closes[k] / closes[k - 1] - 1.0 for k in range(1, len(closes)))
            out = TkMarket(samples, m)
    ctx.markets[s] = out
    return out


@dataclass(frozen=True)
class Tk:
    value: float | None
    reason: str | None = None  # "index", "bar", "price" or None
    # "bar" only, listed in the coverage: the item's first bar is after T − 1200
    young: bool = False


def tk_60(ctx: Context, item: lib.Series, at: int) -> Tk:
    """D1 第 1～4 點 on the item's bar ``at`` (T): only the 61 sampling days'
    closes, the bars between them not read (第十九輪實作釋義「D1 的取樣」)."""

    market = tk_market(ctx, item.session[at])
    if isinstance(market, str):
        return Tk(None, market)
    session, close = item.session, item.close
    closes = []
    for s in market.samples:
        bar = bisect_left(session, s, 0, at + 1)
        if bar > at or session[bar] != s:
            return Tk(None, "bar", young=session[0] > market.samples[0])
        closes.append(close[bar])
    if not all(value > 0 for value in closes):  # NaN fails too
        return Tk(None, "price")
    excess = [
        closes[k] / closes[k - 1] - 1.0 - market.m[k - 1] for k in range(1, len(closes))
    ]
    return Tk(tk_value(excess))


# --- D2: eps_streak_4 -------------------------------------------------------------


single_quarter = r15.single_quarter
_quarter_back = r15._quarter_back


@dataclass(frozen=True)
class Streak:
    qualifies: bool
    reason: str | None = None  # "stale" or "missing"
    singles: tuple[float, ...] = ()  # e(q) .. e(q − 7)


def eps_streak_4(item: lib.Series, at: int, quarter: date) -> Streak:
    """D2 第 1～4 點 on the item's bar ``at`` (T) for the deadline's
    ``quarter``: the latest quarter as K2 reads it (``round14_research.eps_turn``
    on the rows with an EPS), then the 8 single quarters q .. q − 7."""

    if r14.eps_turn(item, at, quarter).reason == "stale":
        return Streak(False, "stale")
    day = item.dates[at]
    cumulative = {end: eps for announced, end, eps in item.quarters if announced <= day}
    singles = [
        single_quarter(cumulative, _quarter_back(quarter, lag))
        for lag in range(STREAK_QUARTERS + YEAR_LAG)
    ]
    if any(value is None for value in singles):
        return Streak(False, "missing")
    rounded = [round(value, EPS_DIGITS) for value in singles]
    grows = all(rounded[k] > rounded[k + YEAR_LAG] for k in range(STREAK_QUARTERS))
    return Streak(grows, None, tuple(singles))


# --- the plans --------------------------------------------------------------------


def segment_window(
    sessions: list[date], segment: str, spec: dict[str, Any]
) -> tuple[int, int] | None:
    """(first, last) index of the sessions with an equity value, or None.
    D2's equity starts the session after its first event day in the segment
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
    dues: dict[int, int] = field(default_factory=dict)  # D2
    rows: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    signal_days: int = 0
    event_days: int = 0
    overlap: dict[str, dict[str, list[float]]] = field(default_factory=dict)
    # the listed means by year: D1 skew_240, vol_60, reversal_720_240
    means: dict[str, dict[str, list[float]]] = field(default_factory=dict)
    rebalances: list[dict[str, Any]] = field(default_factory=list)  # D2


_year = r15._year
_add = r15._add
_pick_row = r15._pick_row


def _timed(ctx: Context, key: str, run: Callable[[], set[int]]) -> set[int]:
    t0 = time.perf_counter()
    try:
        return run()
    finally:
        ctx.seconds[key] += time.perf_counter() - t0


def z2_names(ctx: Context, day, members) -> set[int]:
    """Z2's list on ``day`` (``round8_research`` 第 1 版的定義, not rewritten)."""

    def run() -> set[int]:
        spec = r8.HYPOTHESES[Z2]
        rows = r8.rank(ctx.z, spec, day, members).rows
        return {row[0] for row in rows[: spec["top"]]}

    return _timed(ctx, "z2_order", run)


def w2_names(ctx: Context, day, members) -> set[int]:
    """W2's list on ``day`` (``round6_research`` 第 1 版的定義, not rewritten)."""

    def run() -> set[int]:
        spec = r6.HYPOTHESES[W2]
        rows = r6.rank(ctx.w2, spec, day, members).rows
        return {row[0] for row in rows[: spec["top"]]}

    return _timed(ctx, "w2_order", run)


def v1_names(ctx: Context, day, members) -> set[int]:
    """V1's list on ``day`` (``round5_research`` 第 1 版的定義, not rewritten)."""

    def run() -> set[int]:
        spec = r5.HYPOTHESES[V1]
        rows = r5.rank(ctx.v1, spec, day, members).rows
        return {row[0] for row in rows[: spec["top"]]}

    return _timed(ctx, "v1_order", run)


def x4_names(ctx: Context, day, members) -> set[int]:
    """X4's list (``round14_research.x4_names``: ``explore_research._rank``)."""

    return r14.x4_names(ctx, day, members)


def k2_names(ctx: Context, day, members, quarter) -> set[int]:
    """K2's list (``round15_research.k2_names``: ``round14_research.eps_turn``,
    the first 20 by the hash)."""

    return r15.k2_names(ctx, day, members, quarter)


def p2_names(ctx: Context, day, members, quarter) -> set[int]:
    """P2's list (``round16_research.p2_names``: ``round15_research.margins_up``
    on P2's own statements, the first 20 by the hash)."""

    return r16.p2_names(ctx, day, members, quarter)


def plan_d1(
    ctx: Context, spec: dict[str, Any], first: int, last: int, keep_rows=True
) -> Plan:
    """D1 第 1～5、7 點 on the signal dates ``first − 1`` .. ``last − 1``."""

    panel = ctx.panel
    out = Plan(
        overlap={"D1_Z2": {}, "D1_W2": {}, "D1_V1": {}},
        means={"skew_240": {}, "vol_60": {}, "reversal_720_240": {}},
    )
    top = spec["top"]
    keys = tuple(spec["keys"])
    for at in range(first - 1, last):
        day = panel.sessions[at]
        members = lib.universe(panel, day, MIN_LOTS)
        year = _year(out.coverage, day, len(members))
        out.signal_days += 1
        t0 = time.perf_counter()
        market = tk_market(ctx, at)
        if isinstance(market, str):  # every member missing that day
            _add(year, f"{market}_days", 1)
        rows, missing = [], Counter()
        for item, k in members:
            got = tk_60(ctx, item, k)
            if got.value is None:
                missing["tk_60"] += 1
                missing[got.reason] += 1
                missing["young"] += got.young
            rows.append((item, k, got, pr.tie_break(day, item.instrument_id)))
        ctx.seconds["tk_60"] += time.perf_counter() - t0
        rows.sort(
            key=lambda row: r5.order_key({keys[0][0]: row[2].value}, keys, row[3])
        )
        chosen = rows[:top]
        missing_year = year.setdefault("missing", {})
        for key, count in missing.items():
            missing_year[key] = missing_year.get(key, 0) + count
        valued = len(members) - missing["tk_60"]
        _add(year, "valued", valued)
        if members and not valued:
            _add(year, "empty_days", 1)
        others = {
            "D1_Z2": z2_names(ctx, day, members),
            "D1_W2": w2_names(ctx, day, members),
            "D1_V1": v1_names(ctx, day, members),
        }  # timed in the coverage too
        if not keep_rows:
            continue
        names = [item.instrument_id for item, _k, _g, _t in chosen]
        for key, other in others.items():
            share = r10.overlap_share(names, other)
            if share is not None:
                out.overlap[key].setdefault(str(day.year), []).append(share)
        t0 = time.perf_counter()
        listed = {
            "skew_240": [r8.skew_240(ctx.z, item, k) for item, k, _g, _t in chosen],
            "vol_60": [r5.vol_60(ctx.v1, item, k) for item, k, _g, _t in chosen],
            "reversal_720_240": [
                r6.reversal_720_240(ctx.w2, item, k) for item, k, _g, _t in chosen
            ],
        }
        ctx.seconds["listed"] += time.perf_counter() - t0
        for key, values in listed.items():
            present = [v for v in values if v is not None]
            if present:
                out.means[key].setdefault(str(day.year), []).append(
                    statistics.fmean(present)
                )
        out.picks[at + 1] = names
        out.population[at + 1] = [item.instrument_id for item, _ in members]
        for place, (item, _k, got, tie) in enumerate(chosen, 1):
            out.rows.append(
                _pick_row(
                    ctx, day, place, item.instrument_id,
                    {"tk_60": got.value,
                     **{key: values[place - 1] for key, values in listed.items()}},
                    tie,
                )
            )  # fmt: skip
    return out


def plan_d2(
    ctx: Context, spec: dict[str, Any], first: int, last: int, keep_rows=True
) -> Plan:
    """D2 第 1～5、7 點: the event days of the segment, ``eps_streak_4`` in T's
    population, 20 by the hash, held to the next event day (X7)."""

    panel = ctx.panel
    sessions = panel.sessions
    out = Plan(overlap={"D2_X4": {}, "D2_K2": {}, "D2_P2": {}})
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
        gone = gone_missing = 0
        for item, k in members:
            got = eps_streak_4(item, k, quarter)
            reasons[got.reason] += 1
            if got.qualifies:
                found.append((pr.tie_break(day, item.instrument_id), item, got))
            if ctx.statuses.get(item.instrument_id) in REFERENCE_STATUSES:
                gone += 1
                gone_missing += got.reason is not None
        ctx.seconds["eps_streak_4"] += time.perf_counter() - t0
        found.sort(key=lambda row: row[0])
        chosen = found[:top]
        event = {
            "signal_date": day.isoformat(),
            "quarter": quarter.isoformat(),
            "members": len(members),
            "hits": len(found),
            "not": reasons[None] - len(found),
            "stale": reasons["stale"],
            "missing": reasons["missing"],
            "names": len(chosen),
            "delisted": gone,
            "delisted_missing": gone_missing,
        }
        for key in ("hits", "not", "stale", "missing", "delisted", "delisted_missing"):
            _add(year, key, event[key])
        year.setdefault("events", []).append(event)
        others = {
            "D2_X4": x4_names(ctx, day, members),
            "D2_K2": k2_names(ctx, day, members, quarter),
            "D2_P2": p2_names(ctx, day, members, quarter),
        }  # timed in the coverage too
        if not keep_rows:
            continue
        names = [item.instrument_id for _t, item, _g in chosen]
        shares = {}
        for key, other in others.items():
            share = r10.overlap_share(names, other)
            shares[key] = share
            if share is not None:
                out.overlap[key].setdefault(str(day.year), []).append(share)
        out.rebalances.append(
            {**event, "x4_overlap": shares["D2_X4"], "k2_overlap": shares["D2_K2"],
             "p2_overlap": shares["D2_P2"]}
        )  # fmt: skip
        out.picks[at + 1] = names
        out.population[at + 1] = [item.instrument_id for item, _ in members]
        due = following.get(at)
        out.dues[at + 1] = due if due is not None and due <= last else last + 1
        for place, (tie, item, got) in enumerate(chosen, 1):
            out.rows.append(
                _pick_row(
                    ctx, day, place, item.instrument_id,
                    {"quarter": quarter.isoformat(), "eps_q": got.singles[0],
                     **{f"eps_q{lag}": got.singles[lag]
                        for lag in range(1, len(got.singles))}},
                    tie,
                )
            )  # fmt: skip
    return out


def planner(name: str) -> Callable[..., Plan]:
    return {"D1": plan_d1, "D2": plan_d2}[name]


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
) -> tuple[pr.Simulation, pr.Simulation]:
    """(the hypothesis, the population): D1 K accounts, D2 X7's account."""

    spec = HYPOTHESES[name]
    if spec["engine"] == EVENTS:
        mine = ex.simulate_events(
            planned.picks, planned.dues, ctx.quote, first, last, spec["top"]
        )
        population = ex.simulate_events(
            planned.population, planned.dues, ctx.quote, first, last, None
        )
        return mine, population
    mine = pr.simulate(planned.picks, ctx.quote, first, last, spec["hold"], spec["top"])
    population = pr.simulate(
        planned.population, ctx.quote, first, last, spec["hold"], None
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
    """D1 or D2 on one segment: its numbers, verdict and private parts."""

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
    return f"{name} 第 7 點"


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


COVERAGE_KEYS = ("index", "bar", "young", "price")


def coverage_lines(name: str, coverage: dict[str, Any]) -> list[str]:
    """D1 by year, D2 each event day and by year."""

    if name == "D2":
        head = ["事件日", "對應的季", "母體檔次", "`eps_streak_4` 成立", "不成立", "缺值",
                "（最新一季不是對應的那一季）", "（8 季中有單季 EPS 缺）", "名單檔數",
                "母體裡的下市、轉板股", "（其中缺 EPS）"]  # fmt: skip
        lines = [
            "| " + " | ".join(head) + " |",
            "| --- | --- | " + " | ".join("---:" for _ in head[2:]) + " |",
        ]
        for _year_, row in sorted(coverage.items()):
            for e in row.get("events", []):
                lines.append(
                    f"| {e['signal_date']} | {e['quarter']} | {e['members']:,} | {e['hits']:,} "
                    f"| {e['not']:,} | {_share(e['stale'] + e['missing'], e['members'])} "
                    f"| {e['stale']:,} | {e['missing']:,} | {e['names']:,} "
                    f"| {e['delisted']:,} | {e['delisted_missing']:,} |"
                )
        lines += ["", "依年：", "",
                  "| 年 | 事件日 | 母體檔次 | `eps_streak_4` 成立 | 不成立 | 最新一季不是對應的那一季 "
                  "| 8 季中有單季 EPS 缺 | 母體裡的下市、轉板股檔次 | 其中缺 EPS 的檔次 |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]  # fmt: skip
        for year, row in sorted(coverage.items()):
            lines.append(
                f"| {year} | {row['days']:,} | {row['members']:,} | {row.get('hits', 0):,} "
                f"| {row.get('not', 0):,} | {row.get('stale', 0):,} | {row.get('missing', 0):,} "
                f"| {row.get('delisted', 0):,} | {row.get('delisted_missing', 0):,} |"
            )
        return lines
    head = ["年", "日數", "母體檔次", "有 `tk_60` 的檔次", "缺值", "（加權指數缺值）",
            "（取樣日沒有日線）", "（其中第一根日線晚於 T−1200）", "（收盤缺值或 ≤ 0）",
            "加權指數缺值的訊號日",
            "一檔都沒有值的訊號日"]  # fmt: skip
    lines = [
        "| " + " | ".join(head) + " |",
        "| --- | " + " | ".join("---:" for _ in head[1:]) + " |",
    ]
    for year, row in sorted(coverage.items()):
        members, missing = row["members"], row.get("missing", {})
        lines.append(
            f"| {year} | {row['days']:,} | {members:,} | {row.get('valued', 0):,} "
            f"| {_share(missing.get('tk_60', 0), members)} "
            + " ".join(
                f"| {_share(missing.get(key, 0), members)}" for key in COVERAGE_KEYS
            )
            + f" | {row.get('index_days', 0):,} | {row.get('empty_days', 0):,} |"
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
        f"# {name} {segment}（round19_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- {OVERLAP_NOTE['summary_only']}",
        OVERLAP_NOTE["D1_reference" if name == "D1" else "D2_survivor"],
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
        "## 每次調倉（D2 第 7 點，只列出、不判定）",
        "",
        OVERLAP_NOTE["D2_listed"] + "。",
        "",
        "| 事件日 | 對應的季 | 母體檔次 | `eps_streak_4` 成立 | 名單檔數 | 投入比例 "
        "| 和 X4 的重疊 | 和 K2 的重疊 | 和 P2 的重疊 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *(
            f"| {e['signal_date']} | {e['quarter']} | {e['members']:,} | {e['hits']:,} "
            f"| {e['names']:,} | {_pct(e.get('invested'), 1)} "
            f"| {_pct(e['x4_overlap'], 1)} | {_pct(e['k2_overlap'], 1)} "
            f"| {_pct(e['p2_overlap'], 1)} |"
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
        lines += _rebalance_lines(result["rebalances"])
    for key, summary in (result.get("overlap") or {}).items():
        other = key.split("_")[1]
        lines += _yearly_lines(
            f"## 和 {other} 的重疊（{_point(name)}）",
            OVERLAP_NOTE[key],
            summary,
            lambda v: _pct(v, 1),
        )
    for key, summary in (result.get("means") or {}).items():
        lines += _yearly_lines(
            f"## {FEATURE_LABELS[key]}（{_point(name)}，只列出、不判定）",
            OVERLAP_NOTE["D1_listed"],
            summary,
            lambda v: lib.num(v, 3),
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
    if result.get("rebalances"):
        row["names"] = statistics.fmean(e["names"] for e in result["rebalances"])
        row["hits"] = statistics.fmean(e["hits"] for e in result["rebalances"])
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
        f"# 新策略探索 第 {report['round']} 輪 {stage}（round19_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「第十九輪：D1、D2」）：{DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        _threshold_line(segment, report["min_t"]),
        "- 引擎：D1 是組合引擎（`portfolio_research.simulate`，K＝60），D2 是 X7 的事件日帳戶"
        "（`explore_research.simulate_events`）；日數是有淨值的交易日",
        f"- D1、D2：{OVERLAP_NOTE['summary_only']}",
        OVERLAP_NOTE["D1_reference"],
        OVERLAP_NOTE["D2_survivor"],
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
                f"- {name} 每次調倉的名單檔數：平均 {lib.num(row['names'], 1)}；"
                f"每個事件日 `eps_streak_4` 成立的檔數：平均 {lib.num(row['hits'], 1)}"
            )
        for other in (Z2, W2, V1, X4, K2, P2):
            part = row.get(f"overlap_{other.lower()}")
            if part:
                listed.append(
                    f"- {name} 和 {other} 的重疊：平均 {_pct(part['mean'], 1)}（{part['days']:,} 個訊號日）"
                )
        for key in ("skew_240", "vol_60", "reversal_720_240"):
            part = row.get(f"mean_{key}")
            if part:
                listed.append(
                    f"- {name} {FEATURE_LABELS[key]}：{lib.num(part['mean'], 3)}"
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
    f"- D1：{DEGENERATE['D1']}。依年一列，缺值的原因依序判（加權指數缺值、取樣日沒有日線、收盤缺值或 ≤ 0），"
    "每檔只算第一個；「其中第一根日線晚於 T−1200」是取樣日沒有日線的檔次中，這一檔的第一根日線在 T−1200 之後（上市或研究 DB 的日線晚於第一個取樣日）的檔次，其餘是取樣日剛好沒有日線；「加權指數缺值的訊號日」是那一天母體每一檔都缺值的訊號日數，「一檔都沒有值的訊號日」"
    "是母體有檔、卻沒有一檔有 `tk_60` 的訊號日數；`z2_order`、`w2_order`、`v1_order` 是同一個 T 算 Z2、W2、V1 "
    "名單的時間，`--coverage-only` 不算重疊比例與平均 `skew_240`、`vol_60`、`reversal_720_240`，各段的 `summary.md` 才列",
    f"- D2：{DEGENERATE['D2']}。每個事件日一列，缺值的原因依序判（最新一季、8 季中有單季 EPS 缺），"
    "每檔只算第一個；「不成立」是 8 季都有值、四個比較不全成立的檔數；「母體裡的下市、轉板股」是 `status` 為 "
    "`delisted`／`transferred` 的母體檔次，「其中缺 EPS」是其中 `eps_streak_4` 缺值的檔次；`x4_order`、"
    "`k2_order`、`p2_order` 是同一個 T 算 X4、K2、P2 名單的時間（X4 的 `_rank` 另記它自己的特徵），"
    "`--coverage-only` 不算重疊比例與投入比例，各段的 `summary.md` 才列",
    "- 各假設用自己的訊號日（起日寫在各段標題）",
)


def coverage_markdown(body: dict[str, Any]) -> str:
    load_seconds = body.get("load_seconds_parts", {})
    lines = [
        f"# 新策略探索 第 {body['round']} 輪 D1、D2 資料覆蓋（探索段，不含報酬）",
        "",
        f"- round19_research 第 {VERSION} 版；定義雜湊 `{body['definitions_sha256']}`",
        f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}，"
        f"alembic `{body['copy']['alembic']}`",
        f"- 重現：`{body['command']}`",
        f"- 耗時 {body.get('elapsed_seconds', 0):.0f} 秒（載入 {body.get('load_seconds', 0):.0f} 秒，"
        f"其中 panel {load_seconds.get('panel', 0):.0f} 秒、標的狀態 "
        f"{load_seconds.get('statuses', 0):.0f} 秒、重疊用的季報（P2） "
        f"{load_seconds.get('lists', 0):.0f} 秒），"
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
    lines += [
        "有明顯斷點或缺值比例異常的年份，或 D1 某個訊號日一檔都沒有值、加權指數缺值讓整天缺值，"
        "或 D2 某個事件日成立的檔數是 0 時，先在工具單提問、不跑探索段。",
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
    body = {
        **public(header),
        "coverage_only": True,
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="round19_research.py", description=__doc__)
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
        help="exploration (required, not with --coverage-only): D1, D2 or "
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
    command = "python tools/research/round19_research.py " + " ".join(argv)
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
