"""Round 24 of the new-strategy exploration: AG2 (#1116).

docs/spec/evidence.md 第二十四輪：AG2 and 第二十四輪實作釋義: the hypothesis
was registered (commit ``14906ed9``, #1114, decision 7229042011) before anyone
ran a tool on the backfilled history.  Nothing here is a command-line option:
a change of a definition is a new code.

It is not in ``explore_research.HYPOTHESES``, ``trade_research.HYPOTHESES``
nor ``round4_research`` .. ``round23_research``: their ``definitions_sha256``
hash the whole table, so adding it would make the validation refuse the
exploration reports already run.  AG2 trades on X7's event-day account
(``explore_research.simulate_events``) on K2's event days
(``round14_research.quarter_events``); the population, the loading
(``explore_research.load_context``), ``explore_judge``, the gate, the ledgers
and the ledger's write check are imported.  The latest quarter is AF2's
reading (``round23_research._known``, P2's ``round15_research._known``) of
``quarterly_statements`` with ``round23_research``'s table, source, financial
codes and foreign issuers' Q2 mark.  The overlaps take AF1 (``round23_research
.pb``) and AF2 (``round23_research.accruals_4q``), ranked as
``round23_research.plan_events`` on the same T, and ``round10_research``'s
``overlap_share``／``overlap_summary``.  New here are only ``cash_to_assets``,
its missing reasons and the listed numbers.

Each event day T (after its close, only T's data and before):

- AG2: ``cash_to_assets`` (the latest quarter q's quarter-end cash and cash
  equivalents over q's total assets) high first, 20, held to the next event
  day.

``explore_research.explore_judge`` judges with t ≥ 2 on the exploration and
the fixed Bonferroni t ≥ 3.403 (75 hypotheses) on the validation.  Before the
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
import round10_research as r10  # noqa: E402
import round14_research as r14  # noqa: E402
import round15_research as r15  # noqa: E402
import round23_research as r23  # noqa: E402

VERSION = 1
DESIGN = "1116"
TOOL = "round24_research"
REGISTRATION_COMMIT = "14906ed9"
DECISION = (
    "https://github.com/YiCheng0608/stock-lab/issues/1114#issuecomment-7229042011"
)
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
SEGMENTS = dict(ex.SEGMENTS)
MIN_SEGMENT_DAYS = dict(ex.MIN_SEGMENT_DAYS)
MIN_T = ex.MIN_T  # the exploration's t ≥ 2
# docs 第二十四輪 門檻: 1 − Φ(z) = 0.025 ÷ 75, z = 3.4029, 3.403 to the 3rd
# decimal; fixed, not computed when run.
VALIDATION_MIN_T = 3.403
ROUND = 24
ROUND_SIZE = 1
# X1～X8, S1～S3, R1～R2, M1～M2, C1～C4, V1～V3, W1～W4, Y1～Y4, Z1～Z4, B1～B3,
# F1～F4, L1～L4, J1～J4, U1～U3, K1～K3, P1～P3, N1～N3, A1～A3, G1～G2, D1～D2,
# AB1～AB2, AD1, AE1, AF1～AF2, AG2
CUMULATIVE = 75
# Every segment reads the copy from its start, as round10_research ..
# round23_research: AF2's list reads q − 4.
LOAD_FROM = ex.LOAD_FROM
LOAD_RULE = "every segment from LOAD_FROM"
MIN_LOTS = lib.DEFAULT_MIN_LOTS
RAW_DIR_NAME = ex.RAW_DIR_NAME
POPULATION = pr.POPULATION
TAIEX = pr.TAIEX
EVENTS = "events"
HIGH = r5.HIGH

# 共同 排序與同分、選股與調倉
ORDER = (
    "by the feature, high first (round5_research.order_key), missing last, "
    "ties by sha256(<T>:<instrument_id>)"
)
SHORT_RULE = "cash, not filled"
SALE = (
    "one account (X7): bought at T+1's open, 1/20 of the cash each, sold at "
    "the close of the next event day T' (explore_research.simulate_events), "
    "the new list bought at T'+1's open; the population on the same rule and "
    "event days"
)
# 第 8 點: the members later delisted or transferred, listed by year
DELISTED_STATUSES = ("delisted", "transferred")

# AG2 (第 1～6 點, 實作釋義): round23_research's table, source, codes and
# marks (AF2 第 2、5 點), imported
STATEMENT_TABLE = r23.STATEMENT_TABLE
STATEMENT_SOURCE = r23.STATEMENT_SOURCE
INDUSTRY_KEY = r23.INDUSTRY_KEY  # in data_json
FINANCIAL_CODES = r23.FINANCIAL_CODES
FOREIGN_KEY = r23.FOREIGN_KEY
FOREIGN_RULE = r23.FOREIGN_RULE
CASH = "cash"
ASSETS = r23.ASSETS
LATEST_RULE = (
    "the latest quarter known on T (announcement_date <= T, the largest "
    "period_end of every row, round23_research._known) must be the deadline's "
    "quarter"
)
CASH_TO_ASSETS = (
    "cash(q) / total_assets(q), q's quarter-end values only (no q-4, no "
    "average); cash 0 or negative by value"
)
ASSETS_MIN = 0.0  # total_assets(q) ≤ 0: missing
CASH_MISSING = (
    "reasons in order: stale, financial (q's industry code in "
    "FINANCIAL_CODES), rows (q has no row known on T), fields (cash or "
    "total_assets NULL, not_applicable too), assets (total_assets <= 0)"
)
AG2_START = date(2013, 5, 15)
# The lists AG2 overlaps with (第 8 點): round23_research 第 1 版
AF1, AF2 = "AF1", "AF2"
OVERLAPS = (AF1, AF2)

# The registration (docs 第二十四輪：AG2), word for word.  ``start`` as
# ``explore_research``.
HYPOTHESES: dict[str, dict[str, Any]] = {
    "AG2": {
        "engine": EVENTS,
        "direction": "基本面：現金持有",
        "label": "每季法定期限的事件日，`cash_to_assets`（本季季底現金及約當現金 ÷ "
        "本季季底總資產）大者先取 20 檔",
        "rule": "quarterly",
        "keys": (("cash_to_assets", HIGH),),
        "short": SHORT_RULE,
        "top": 20,
        "hold": "next_event",
        "start": ("date", AG2_START),
    },
}
OTHER_COMPARISONS = ex.OTHER_COMPARISONS
REASONS = dict(ex.REASONS)
LIMITS = {
    "AG2": "定義照摘要與索引頁，未讀全文；`cash` 不含短期投資：文獻常用「現金及短期投資」，"
    "`quarterly_statements` 沒有短期投資這一科，只用現金及約當現金；"
    "整包存的是更正後的值：同一份季報更正過，更正後的值在原期限就被看到，同 `t163sb04` 的限制；"
    "外國發行人的 Q2：事件日用一般公司的期限（8/14），外國發行人 2021 年起的 Q2 期限是 8/31，"
    "`announcement_date` 照它算時，8/14 那天最新一季不是事件日對應的那一季，那一季它們不成訊號，"
    "只是少收、不會偷看；金融業的格式都缺值，名單只會是一般業與「其他」格式；"
    "`cash` 的缺值比例文件沒寫，由 `--coverage-only` 先看；"
    "和前 74 個假設的關係：沒有已登記的同類，前二十三輪的資產負債表只有 AF2 用了總資產當分母，"
    "AG2 用現金的水準，AF2 用營業利益減營業現金流的流量；AF1、AF2 的結果在提問時都還沒出來，"
    "AG2 不是看它們挑的，看和 AF1、AF2 的重疊比例；不加淨值比的條件，以免變成 AF1 的子集；"
    "和 V1、Z3、U3 這類「安全股」也不同：它們用價格波動或配息紀錄",
}
# The degenerate cases as the code judges them (第二十四輪實作釋義; PR #913
# review: the docs, coverage.md and summary.md say the same words, a test
# reads the docs' tool section for them).
DEGENERATE = {
    "AG2": "最新一季（`announcement_date` ≤ T 的 `quarterly_statements` 列中期末最晚的一季）不是事件日對應的那一季、"
    "q 那一列 `data_json` 的產業碼是 `basi`／`fh`／`ins`／`bd`、q 沒有 `announcement_date` ≤ T 的列"
    "（在第 1 種之後判，實際上不會發生，那一欄都是 0）、q 的 `cash` 或 `total_assets` 是 NULL"
    "（含 `not_applicable`），或 q 的 `total_assets` ≤ 0 時缺值、排最後；缺值的原因依序判：最新一季、"
    "金融業的格式、q 沒有列、`cash` 或 `total_assets` 是 NULL、`total_assets` ≤ 0，每檔只算第一個；"
    "`cash` 是 0 時 `cash_to_assets`＝0，照值排序，不是缺值；`cash` 是負數（不該有）時也照值排序；"
    "有值的不足 20 檔時以缺值的依雜湊補，母體不足 20 檔時餘額留現金",
}
OVERLAP_NOTE = {
    "summary_only": "定義照摘要與索引頁，未讀全文",
    "AG2_AF1": 'AG2 與 AF1（`round23_research` 第 1 版的 `HYPOTHESES["AF1"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|AG2 的名單 ∩ AF1 的前 20 名| ÷ AG2 當天的名單檔數；AG2 或 AF1 當天沒有名單的事件日"
    "（AF1 的第一個訊號日 2013-05-15 以前）不計。看 AG2 有沒有變成 AF1 的子集。只列出、不判定",
    "AG2_AF2": 'AG2 與 AF2（`round23_research` 第 1 版的 `HYPOTHESES["AF2"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|AG2 的名單 ∩ AF2 的前 20 名| ÷ AG2 當天的名單檔數；AG2 或 AF2 當天沒有名單的事件日"
    "（AF2 的第一個訊號日 2014-05-15 以前）不計。只列出、不判定",
    "delisted": "依年（T 的年）列母體裡 `status` 是 `delisted`／`transferred` 的檔次（每個事件日數一次）與其中 "
    "`cash_to_assets` 缺值的檔次，另列其他檔次（現存股）的缺值比例對照。只列出、不判定",
    "AG2_foreign": "外國發行人的 Q2 期限從 2021 年起才適用，探索段這一欄都是 0；2021～2024 的值在驗證段的 `summary.md`",
    "listed": "每次調倉的檔數與平均投入比例：名單檔數是取前 20 名之後，投入比例是買進那天收盤時部位占淨值的比例",
    "AG2_survivor": "- 存活者偏差（AG2）：`quarterly_statements` 含之後下市、轉板的公司（季底起 670 天內有日線就寫），"
    "剩下的缺口是日線跨過季底、但整包沒有那一季的下市股，2013～2024 年 16 個公司年，偏差方向事先定不出來。"
    "不另列對照基準；依年的下市、轉板股缺值檔次在 `AG2/summary.md` 的「依年的下市、轉板股」",
}
PICK_FIELDS = {"AG2": ("quarter", "cash_to_assets", "cash", "total_assets")}
COVERAGE_KEYS = {"AG2": ("stale", "financial", "rows", "fields", "assets")}


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
            "cash_to_assets": {
                "table": [STATEMENT_TABLE, STATEMENT_SOURCE],
                "fields": [CASH, ASSETS],
                # read with them, for AF2's list (round23_research's columns)
                "af2_fields": [r23.OPERATING, r23.CFO],
                "industry": [INDUSTRY_KEY, FINANCIAL_CODES],
                "latest": LATEST_RULE,
                # AF2's reading of the latest quarter (round23_research._known,
                # round15_research's) and its tools
                "known": [r15.VERSION, r15.definitions_sha256()],
                "reading": [r23.VERSION, r23.definitions_sha256()],
                "formula": CASH_TO_ASSETS,
                "assets_min": ASSETS_MIN,
                "missing": CASH_MISSING,
                "foreign": [FOREIGN_KEY, FOREIGN_RULE],
            },
            "overlaps": {
                **{
                    name: [r23.HYPOTHESES[name], r23.VERSION, r23.definitions_sha256()]
                    for name in OVERLAPS
                },
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
    """Hash of every fixed number the verdicts depend on (the definition,
    AG2's table, source, fields, latest quarter, formula, financial codes
    and missing rules, N, the order, the event days and the account with
    their tools' hashes, the reading of the latest quarter, the overlaps'
    lists, the segments, the costs).  A changed tool needs a new exploration
    report before a validation."""

    text = json.dumps(definitions(), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- reading ----------------------------------------------------------------------


@dataclass(frozen=True)
class CashStatement(r23.QuarterStatement):
    """``round23_research.QuarterStatement`` (what AF2 reads) with q's
    ``cash`` (thousand NTD, None when NULL): one read serves both."""

    cash: float | None = None


has_table = r23.has_table
_data = r23._data
load_valuations = r23.load_valuations


def load_quarter_statements(
    db: Path, series: dict[int, lib.Series], end: date
) -> dict[int, list[CashStatement]]:
    """``round23_research.load_quarter_statements``'s rows (``announcement_date``
    ≤ ``end``, by announcement) with ``cash`` too; no table, none."""

    out: dict[int, list[CashStatement]] = defaultdict(list)
    if not has_table(db, STATEMENT_TABLE):
        return {}
    con = lib.connect_read_only(db)
    try:
        rows = con.execute(
            f"select instrument_id, announcement_date, period_end, {r23.OPERATING}, "
            f"{r23.CFO}, {ASSETS}, {CASH}, data_json from {STATEMENT_TABLE} "
            "where source = ? and announcement_date is not null "
            "and announcement_date <= ? order by announcement_date, period_end",
            (STATEMENT_SOURCE, end.isoformat()),
        )
        for instrument_id, announced, period_end, op, cfo, assets, cash, text in rows:
            if instrument_id not in series:
                continue
            data = _data(text)
            out[instrument_id].append(
                CashStatement(
                    date.fromisoformat(announced),
                    date.fromisoformat(period_end),
                    data.get(INDUSTRY_KEY),
                    None if op is None else float(op),
                    None if cfo is None else float(cfo),
                    None if assets is None else float(assets),
                    data.get(FOREIGN_KEY) == FOREIGN_RULE,
                    None if cash is None else float(cash),
                )
            )
    finally:
        con.close()
    return dict(out)


@dataclass
class Context:
    """``explore_research``'s context (the market, the quotes), AF1's ``pb``
    on the event days, the statements AG2 and AF2 read and the instruments'
    status.  One panel."""

    base: ex.Context
    valuations: dict[int, dict[date, float | None]] = field(default_factory=dict)
    statements: dict[int, list[CashStatement]] = field(default_factory=dict)
    statuses: dict[int, str] = field(default_factory=dict)
    tables: dict[str, bool] = field(default_factory=dict)
    seconds: Counter = field(default_factory=Counter)
    load_seconds: dict[str, float] = field(default_factory=dict)

    @property
    def market(self) -> pr.Market:
        return self.base.market

    @property
    def panel(self) -> lib.Panel:
        return self.base.market.panel

    def quote(self, instrument_id: int, s: int) -> pr.Quote | None:
        return self.base.quote(instrument_id, s)


def load(db: Path, start: date, end: date, raw_dir: Path) -> Context:
    """The panel, ``pb`` on the event days (AF1's list), the statements and
    the statuses to ``end``; nothing after ``end`` is read."""

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
    statuses = r15.load_statuses(db)
    return Context(
        base,
        valuations,
        statements,
        statuses,
        tables={
            name: has_table(db, name) for name in ("valuation_daily", STATEMENT_TABLE)
        },
        load_seconds={
            "panel": panel_seconds,
            "valuations": valuation_seconds,
            "statements": time.monotonic() - t0,
        },
    )


# --- AG2: cash_to_assets ----------------------------------------------------------


@dataclass(frozen=True)
class CashToAssets:
    value: float | None
    # "stale", "financial", "rows", "fields", "assets" or None
    reason: str | None = None
    cash: float | None = None
    assets: float | None = None


_known = r23._known


def cash_to_assets(
    ctx: Context, item: lib.Series, day: date, quarter: date
) -> CashToAssets:
    """AG2 第 2～4 點 on T (``day``) for the deadline's ``quarter``."""

    known = _known(ctx.statements.get(item.instrument_id, []), day)
    if not known or max(known) != quarter:
        return CashToAssets(None, "stale")
    now = known.get(quarter)
    if now is not None and now.industry in FINANCIAL_CODES:
        return CashToAssets(None, "financial")
    if now is None:  # after the first reason: never, counted 0
        return CashToAssets(None, "rows")
    cash, assets = now.cash, now.assets
    if cash is None or assets is None:
        return CashToAssets(None, "fields", cash, assets)
    if assets <= ASSETS_MIN:
        return CashToAssets(None, "assets", cash, assets)
    return CashToAssets(cash / assets, None, cash, assets)


def foreign_late(ctx: Context, item: lib.Series, day: date, quarter: date) -> bool:
    """``round23_research.foreign_late`` on AG2's rows (``--coverage-only``)."""

    return r23.foreign_late(ctx, item, day, quarter)


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
_timed = r23._timed
_gone = r23._gone
delisted_by_year = r23.delisted_by_year


def af_names(ctx: Context, name: str, day: date, members, quarter: date) -> set[int]:
    """AF1's or AF2's list on ``day`` (``round23_research`` 第 1 版的定義:
    ``pb`` or ``accruals_4q`` small first by ``round5_research.order_key``,
    20, as ``round23_research.plan_events``); none before its first signal
    day."""

    def run() -> set[int]:
        spec = r23.HYPOTHESES[name]
        keys = tuple(spec["keys"])
        feature = keys[0][0]
        start = ex.start_index(ctx.panel.sessions, spec["start"])
        if start is None or day < ctx.panel.sessions[start]:
            return set()
        rows = sorted(
            (
                r5.order_key(
                    {
                        feature: (
                            r23.pb(ctx, item, day)
                            if name == AF1
                            else r23.accruals_4q(ctx, item, day, quarter)
                        ).value
                    },
                    keys,
                    pr.tie_break(day, item.instrument_id),
                ),
                item.instrument_id,
            )
            for item, _k in members
        )
        return {instrument_id for _key, instrument_id in rows[: spec["top"]]}

    return _timed(ctx, f"{name.lower()}_order", run)


def plan_events(ctx: Context, name: str, first: int, last: int, keep_rows=True) -> Plan:
    """AG2 第 1～5、8 點: the event days of the segment, ``cash_to_assets`` in
    T's population high first, 20, held to the next event day (X7); the
    listed counts and AF1's, AF2's lists on the same days."""

    spec = HYPOTHESES[name]
    panel = ctx.panel
    sessions = panel.sessions
    out = Plan(overlap={f"{name}_{other}": {} for other in OVERLAPS})
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
        cash_null = 0
        for item, _k in members:
            got = cash_to_assets(ctx, item, day, quarter)
            reasons[got.reason] += 1
            cash_null += got.reason == "fields" and got.cash is None
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
            "cash_null": cash_null,
            "names": len(chosen),
            "named_valued": sum(1 for _i, got, _t in chosen if got.value is not None),
            "delisted": gone,
            "delisted_missing": gone_missing,
        }
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
        others = {
            other: af_names(ctx, other, day, members, quarter) for other in OVERLAPS
        }  # timed in the coverage too
        if not keep_rows:
            continue
        names = [item.instrument_id for item, _g, _t in chosen]
        shares = {}
        for other, listed in others.items():
            share = r10.overlap_share(names, listed)
            shares[other] = share
            if share is not None:
                out.overlap[f"{name}_{other}"].setdefault(str(day.year), []).append(
                    share
                )
        out.rebalances.append({**event, "overlap": shares})
        out.picks[at + 1] = names
        out.population[at + 1] = [item.instrument_id for item, _ in members]
        due = following.get(at)
        out.dues[at + 1] = due if due is not None and due <= last else last + 1
        for place, (item, got, tie) in enumerate(chosen, 1):
            values = {"quarter": quarter.isoformat(), "cash_to_assets": got.value,
                      "cash": got.cash, "total_assets": got.assets}  # fmt: skip
            out.rows.append(_pick_row(ctx, day, place, item.instrument_id, values, tie))
    return out


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
    """AG2 on one segment: its numbers, verdict and private parts."""

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


def coverage_lines(name: str, coverage: dict[str, Any]) -> list[str]:
    """Each event day, then the delisted or transferred members by year."""

    head = ["事件日", "對應的季", "母體檔次", "有 `cash_to_assets` 的檔數", "名單檔數",
            "（其中有值）", "最新一季不是對應的那一季", "金融業的格式", "q 沒有列",
            "`cash` 或 `total_assets` 是 NULL", "（其中 `cash` 是 NULL）", "`total_assets` ≤ 0",
            "缺值比例", "外國發行人 Q2（8/14）", "母體裡的下市、轉板股", "（其中缺值）"]  # fmt: skip
    lines = [
        "| " + " | ".join(head) + " |",
        "| --- | --- | " + " | ".join("---:" for _ in head[2:]) + " |",
    ]
    for _year_, row in sorted(coverage.items()):
        for e in row.get("events", []):
            missing = e["members"] - e["valued"]
            foreign = f"{e['foreign_stale']:,}" if e["quarter"][5:7] == "06" else "—"
            cells = [e["signal_date"], e["quarter"], f"{e['members']:,}",
                     f"{e['valued']:,}", f"{e['names']:,}", f"{e['named_valued']:,}",
                     f"{e['stale']:,}", f"{e['financial']:,}", f"{e['rows']:,}",
                     f"{e['fields']:,}", f"{e['cash_null']:,}", f"{e['assets']:,}",
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
        f"# {name} {segment}（round24_research 第 {VERSION} 版，#{DESIGN}）",
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
    lines = [
        f"## 每次調倉（{name} 第 8 點，只列出、不判定）",
        "",
        OVERLAP_NOTE["listed"] + "。",
        "",
        "| 事件日 | 對應的季 | 母體檔次 | 有 `cash_to_assets` | 名單檔數 | 投入比例 "
        "| 和 AF1 的重疊 | 和 AF2 的重疊 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        *(
            f"| {e['signal_date']} | {e['quarter']} | {e['members']:,} | {e['valued']:,} "
            f"| {e['names']:,} | {_pct(e.get('invested'), 1)} "
            f"| {_pct(e['overlap'][AF1], 1)} | {_pct(e['overlap'][AF2], 1)} |"
            for e in rebalances
        ),
    ]
    invested = [e["invested"] for e in rebalances if e.get("invested") is not None]
    names = [e["names"] for e in rebalances]
    lines += [
        "",
        f"平均每次調倉 {lib.num(statistics.fmean(names), 1)} 檔、平均投入比例 "
        f"{_pct(statistics.fmean(invested) if invested else None, 1)}"
        "（和 AF1、AF2 的重疊見下）。",
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
    for other in OVERLAPS:
        key = f"{name}_{other}"
        if key in result.get("overlap", {}):
            lines += _yearly_lines(
                f"## 和 {other} 的重疊（{name} 第 8 點）",
                OVERLAP_NOTE[key],
                result["overlap"][key],
                lambda v: _pct(v, 1),
            )
    if result.get("delisted"):
        lines += [
            f"## 依年的下市、轉板股（{name} 第 8 點，只列出、不判定）",
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
        f"# 新策略探索 第 {report['round']} 輪 {stage}（round24_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- {OVERLAP_NOTE['summary_only']}",
        OVERLAP_NOTE["AG2_survivor"],
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「第二十四輪：AG2」）：{DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        _threshold_line(segment, report["min_t"]),
        "- 引擎：AG2 是 X7 的事件日帳戶（`explore_research.simulate_events`），"
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
        for other in OVERLAPS:
            part = row.get(f"overlap_{other.lower()}")
            if part:
                listed.append(
                    f"- {name} 和 {other} 的重疊：平均 {_pct(part['mean'], 1)}（{part['days']:,} 個訊號日）"
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
    f"- AG2：{DEGENERATE['AG2']}。每個事件日一列；「（其中 `cash` 是 NULL）」是「`cash` 或 `total_assets` 是 NULL」"
    "裡 `cash` 是 NULL 的檔數；「外國發行人 Q2（8/14）」是 8/14 事件日因最新一季不是對應的那一季缺值、"
    "而那一季的列照外國發行人的 Q2 期限（`data_json` 的 `deadline_rule`）在 T 之後才可得的檔數，只數、不讀它的值（"
    + OVERLAP_NOTE["AG2_foreign"]
    + "）；`af1_order`、`af2_order` 是同一個 T 算 AF1、AF2 名單的時間，`--coverage-only` 不算重疊比例，"
    "各段的 `summary.md` 才列",
    "- 「依年的下市、轉板股」：" + OVERLAP_NOTE["delisted"],
)


def coverage_markdown(body: dict[str, Any]) -> str:
    load_seconds = body.get("load_seconds_parts", {})
    tables = body.get("tables", {})
    lines = [
        f"# 新策略探索 第 {body['round']} 輪 AG2 資料覆蓋（探索段，不含報酬）",
        "",
        f"- round24_research 第 {VERSION} 版；定義雜湊 `{body['definitions_sha256']}`",
        f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}，"
        f"alembic `{body['copy']['alembic']}`",
        "- 表："
        + "、".join(
            f"`{name}` {'有' if present else '沒有（全部缺值）'}"
            for name, present in tables.items()
        ),
        f"- 重現：`{body['command']}`",
        f"- 耗時 {body.get('elapsed_seconds', 0):.0f} 秒（載入 {body.get('load_seconds', 0):.0f} 秒，"
        f"其中 panel {load_seconds.get('panel', 0):.0f} 秒、事件日的 `pb`（AF1 的名單）"
        f"{load_seconds.get('valuations', 0):.0f} 秒、`quarterly_statements` 與標的狀態 "
        f"{load_seconds.get('statements', 0):.0f} 秒），"
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
        "有明顯斷點或缺值比例異常的年份或事件日（含 `cash` 是 NULL 的比例）、某個事件日能進名單的檔數"
        "（有值的檔數）不到 20，或下市、轉板股的缺值比例明顯高於現存股時，先在工具單提問、不跑探索段。",
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
    """The exploration and the validation need both tables: without
    ``quarterly_statements`` every value would be missing, without
    ``valuation_daily`` AF1's list (the overlap) would be the hash's."""

    return [
        f"{db} has no {name} table: run the exploration after its data is in "
        "(docs/spec/evidence.md 第二十四輪「需要的資料」)"
        for name in ("valuation_daily", STATEMENT_TABLE)
        if not has_table(db, name)
    ]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="round24_research.py", description=__doc__)
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
        help="exploration (required, not with --coverage-only): AG2; each runs "
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
    command = "python tools/research/round24_research.py " + " ".join(argv)
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
