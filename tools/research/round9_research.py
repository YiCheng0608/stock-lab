"""Round 9 of the new-strategy exploration: B1～B3 (#926).

docs/spec/evidence.md 第九輪：B1～B3 and 第九輪實作釋義: the hypotheses were
registered (commit ``00be010c``, #920, decision 7056123326) before anyone ran a
tool on the backfilled history.  Nothing here is a command-line option: a
change of a definition is a new code.

They are not in ``explore_research.HYPOTHESES``, ``trade_research.HYPOTHESES``
nor ``round4_research`` .. ``round8_research``: their ``definitions_sha256``
hash the whole table, so adding them would make the validation refuse the
exploration reports already run.  B1 and B3 trade on the portfolio engine
(``portfolio_research.simulate``) with the population, the loading
(``explore_research.load_context``), ``explore_judge``, the "high first" order
(``round5_research.order_key``), the gate and the ledgers imported; B2 is
judged trade by trade with ``trade_research``'s trades (``TradeBars``,
``settle``, ``baseline``, ``stats``, the occupancy of ``State``) and
``exit_research``'s limits.  New here are only ``short_margin_ratio``,
``x_start``, ``limit_up_close`` and B2's exit without a stop or a target
(``settle`` with a stop no bar reaches and no target: the holding limit, the
delays, a delisting and the segment's end).

Each signal date T (after its close, only T's data and before; the margin
lists of T and the market session before it):

- B1: ``short_margin_ratio`` high first — short_balance[at] ÷
  margin_balance[at] (both in lots, not converted).  Missing without T's chip
  row, with a null balance or a margin_balance ≤ 0; 0 with no short and a
  margin balance > 0.  N 20, K 20.
- B2: every member of the population (less the occupied ones) with
  ``x_start`` and ``short_margin_ratio`` ≥ 0.3 (a missing ratio does not
  qualify) — ``x_start``: T's list of the stock's exchange has it with a note
  containing ``X`` and the previous market session's list of the same
  exchange does not have it, or not with ``X``.  Without either list the
  exchange makes no signal that day (the days are listed).  Bought at T+1's
  open (deadline one session: not tradable or locked at limit up abandons it,
  the two reasons apart), sold at the close of the 5th session counting the
  fill as the 1st (``trade_research.settle``'s delays, delisting and segment
  end).
- B3: every member of the population whose unadjusted close on T is at or
  above T's limit-up price (``portfolio_research.Market.limits``: the
  previous bar's close on T's basis, ``exit_research.price_limits`` by the
  date, ``tick_floor``), not ranked, the first 20 by
  ``sha256("<T>:<instrument_id>")``; fewer leave cash.  Missing (not
  qualifying) when T or the bar before is suspended, a close is missing or
  ≤ 0, or no limit can be computed.  N 20, K 5, from 2015-06-01.

``explore_research.explore_judge`` judges with t ≥ 2 on the exploration and
the fixed Bonferroni t ≥ 3.205 (37 hypotheses) on the validation; B2 also
needs 60 signal dates with a fill (``trade_research.MIN_DAYS``).  Before the
used segment is loaded the validation's panel is let go (PR #905 review).
``--coverage-only`` writes counts of dates, members and missing values per
year and the time of the features, no return at all.
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
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_lib as lib  # noqa: E402
import exit_research as er  # noqa: E402
import explore_research as ex  # noqa: E402
import portfolio_research as pr  # noqa: E402
import round5_research as r5  # noqa: E402
import trade_research as tr  # noqa: E402

VERSION = 1
DESIGN = "926"
TOOL = "round9_research"
REGISTRATION_COMMIT = "00be010c"
DECISION = "https://github.com/YiCheng0608/stock-lab/issues/920#issuecomment-7056123326"
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
SEGMENTS = dict(ex.SEGMENTS)
MIN_SEGMENT_DAYS = dict(ex.MIN_SEGMENT_DAYS)
MIN_T = ex.MIN_T  # the exploration's t ≥ 2
# docs 第九輪 門檻: 1 − Φ(z) = 0.025 ÷ 37, z = 3.2048, 3.205 to the 3rd decimal;
# fixed, not computed when run.
VALIDATION_MIN_T = 3.205
ROUND = 9
ROUND_SIZE = 3
# X1～X8, S1～S3, R1～R2, M1～M2, C1～C4, V1～V3, W1～W4, Y1～Y4, Z1～Z4, B1～B3
CUMULATIVE = 37
MIN_DAYS = tr.MIN_DAYS  # B2: signal dates with a fill, per segment
OVERLAP = tr.OVERLAP
LOAD_FROM = ex.LOAD_FROM  # the exploration reads the copy from its start
WARMUP_CALENDAR_DAYS = ex.WARMUP_CALENDAR_DAYS
MIN_LOTS = lib.DEFAULT_MIN_LOTS
RAW_DIR_NAME = ex.RAW_DIR_NAME
POPULATION = pr.POPULATION
TAIEX = pr.TAIEX
PORTFOLIO, TRADE = "portfolio", "trade"

HIGH = r5.HIGH
MIN_RATIO = 0.3  # B2: short_margin_ratio ≥ 0.3
X_NOTE = "X"  # 停止融券: a note of margin_lists.members_json containing it
# #926 decision 7056755897: an exchange whose list adds X to at least 80% of
# its members on T (a market-wide measure, 2008-09-30) makes no B2 signal.
MARKET_WIDE_SHARE = 0.8
# B2's exit has no stop and no target: a stop no bar's low reaches (settle
# compares ``low <= stop``) and ``target=None`` leave the holding limit, the
# delays, a delisting and the segment's end.
NO_STOP = float("-inf")
LIMIT_EPS = er.EPS  # B3: close ≥ limit up − 1e-9, as the engine's lock
# The OTC bars from 2007-04-23 to 2007-11-30 are not read (bar_exclusions.json):
# B1 and B2 count from the OTC 2007-12-03, as rounds 5～8.
OTC_ANCHOR = r5.OTC_ANCHOR
B3_START = date(2015, 6, 1)
MARKETS = {"TWSE": "上市", "TPEx": "上櫃"}
TOP_X_DAYS = 5  # coverage: the days with the most new X per exchange

# The registration (docs 第九輪：B1～B3), word for word.  ``start`` as
# ``explore_research``: ("session", anchor, n) is the n-th session counting the
# anchor (or the first session after it) as the first; ("date", d) the first
# session from d.  ``keys``: (feature, HIGH), a missing value last, ties by
# ``portfolio_research.tie_break``; ``condition``: the members meeting it, not
# ranked, by the tie only.
HYPOTHESES: dict[str, dict[str, Any]] = {
    "B1": {
        "engine": PORTFOLIO,
        "direction": "散戶融券",
        "label": "`short_margin_ratio`（T 日融券餘額 ÷ T 日融資餘額，券資比）大者先",
        "rule": "daily",
        "keys": (("short_margin_ratio", HIGH),),
        "condition": None,
        "top": 20,
        "hold": 20,
        "start": ("session", OTC_ANCHOR, 20),
    },
    "B2": {
        "engine": TRADE,
        "kind": "event",  # trade_research._trade_row: hold counts from the fill
        "direction": "事件：停止融券前的強制回補",
        "label": "名單上第一次出現停止融券註記 `X`（`x_start`）、券資比 ≥ 0.3，全部符合的訊號；"
        "T+1 開盤成交（期限 1 日）、沒有停損與目標、持有 5 日",
        "market_filter": False,
        "min_ratio": MIN_RATIO,
        "entry_days": 1,
        "stop": None,
        "target": None,
        "hold": 5,
        "start": ("session", OTC_ANCHOR, 20),
    },
    "B3": {
        "engine": PORTFOLIO,
        "direction": "價格限制",
        "label": "T 日收盤等於漲停價（`limit_up_close`），不排序、依雜湊取前 20 名",
        "rule": "daily",
        "keys": (),
        "condition": "limit_up_close",
        "top": 20,
        "hold": 5,
        "start": ("date", B3_START),
    },
}
OTHER_COMPARISONS = ex.OTHER_COMPARISONS
REASONS = dict(tr.REASONS)  # explore_research's and too_few_trade_days
VOLATILE_KEYS = ex.VOLATILE_KEYS
LIMITS = {
    "B1": "停止融券期間（股東會、除權息前）融券強制回補到 0，那幾天那些股票的值是 0、排不進前 20，"
    "名單有季節性；融資餘額很小的股票比值會很大，母體有 1,000 張均量門檻，但沒有另設融資下限，"
    "是登記時事先定的寫法；2008 年 10 月有平盤以下禁止融券的暫時措施，那段的券資比和其他年份不同",
    "B2": "停止融券的原因不只股東會與除權息（暫時措施、主管機關的處置也可能出現 `X`），DB 沒有原因欄，"
    "全部照同一規則；逐筆平均假設每個訊號都買得到、每筆等額，不是一個帳戶的資金曲線；"
    "持有期間互相重疊，t 以「日數 ÷ 20」計只是保守的下限",
    "B3": "T+1 開盤若漲停鎖死就買不到，照引擎略過、不遞補，筆數照列；持有 5 日、換手高，成本負擔大，"
    "持有期間是依文獻的效應期間（幾天）事先定的；新上市股票前幾天沒有漲跌幅限制，"
    "但母體要 20 日均量，多半不在母體",
}
# The degenerate cases as the code judges them (第九輪實作釋義; PR #913 review:
# the docs, coverage.md and summary.md say the same words, a test reads the
# docs' tool section for them).
DEGENERATE = {
    "B1": "T 那一根沒有籌碼列、`short_balance` 或 `margin_balance` 是 null，"
    "或 margin_balance ≤ 0 時缺值，排最後；融券 0、融資 > 0 時是 0",
    "B2": "T 或前一個交易日，這一檔交易所在 `margin_lists` 沒有那天的列時，"
    "那天這個交易所不產生訊號，天數另列；券資比缺值不符合",
    "B2_market_wide": "某交易所某天整份名單新增 `X` 的檔數 ≥ 該天名單檔數的 80% 時，"
    "那天那個交易所不產生訊號，日子另列",
    "B3": "T 或前一根停牌、收盤缺值或 ≤ 0，或算不出漲停價時不符合；"
    "收盤 ≥ 漲停價 − 1e-9 就成立",
}
ABANDON_LABELS = {
    "not_tradable": "T+1 不可成交（停牌、沒有日線）",
    "limit_up": "T+1 漲停鎖死",
}
FEATURE_LABELS = {
    "short_margin_ratio": "券資比",
    "limit_up_close": "收盤等於漲停價",
}


def definitions() -> dict[str, Any]:
    return {
        "version": VERSION,
        "design": DESIGN,
        "hypotheses": HYPOTHESES,
        "features": {
            "short_margin_ratio": {
                "value": "chip_snapshots.short_balance[at] / margin_balance[at], "
                "lots over lots, not converted",
                "missing": "no chip row on at; a null short_balance or margin_balance; "
                "margin_balance <= 0",
                "zero": "short_balance 0 and margin_balance > 0: 0",
            },
            "x_start": {
                "lists": "margin_lists.members_json of the stock's exchange "
                "(panel.symbols) on T and on the market session before T",
                "note": X_NOTE,
                "value": "on T's list with a note containing X; not on the previous "
                "list, or on it without X",
                "missing": "no list of the exchange on T or on the session before: "
                "no signal of that exchange that day, the days listed",
                "min_ratio": MIN_RATIO,
                "ratio_missing": "does not qualify",
                "market_wide": "new X on the whole list (on T with X, not with X the session before) >= MARKET_WIDE_SHARE of T's list: no signal of that exchange that day",
                "market_wide_share": MARKET_WIDE_SHARE,
            },
            "limit_up_close": {
                "value": "raw close of at >= portfolio_research.Market.limits(at)[1] "
                "- EPS (exit_research.price_limits by the date, tick_floor)",
                "eps": LIMIT_EPS,
                "limit": [
                    str(er.LIMIT_BEFORE_WIDENING),
                    str(er.LIMIT_WIDENED_ON),
                    str(er.LIMIT),
                ],  # exit_research.daily_limit by the bar's date (#922)
                "missing": "at or at-1 suspended; a close of at or at-1 missing or "
                "<= 0; no limit (an ETF, no reference)",
                "pick": "not ranked; the first 20 by sha256(<T>:<instrument_id>)",
            },
        },
        "markets": sorted(MARKETS),  # B2: the exchanges whose lists make signals
        "b2_exit": {
            "entry": "T+1 open, one session; not tradable or locked at limit up "
            "abandons",
            "stop": "none (settle with NO_STOP)",
            "no_stop": str(NO_STOP),
            "target": "none",
            "hold": "the 5th market session counting the fill as the 1st; "
            "trade_research.settle's delays, delisting and segment end",
            "trade_research": [tr.VERSION, tr.DESIGN],
        },
        "order": "missing last; ties sha256(<T>:<instrument_id>)",
        "segments": SEGMENTS,
        "min_segment_days": MIN_SEGMENT_DAYS,
        "min_t": MIN_T,
        "validation_min_t": VALIDATION_MIN_T,
        "min_days": MIN_DAYS,
        "overlap": OVERLAP,
        "round": [ROUND, ROUND_SIZE, CUMULATIVE],
        "costs": [pr.SLIPPAGE, pr.FEE, pr.TAX, tr.SLIPPAGE, tr.COST_BPS],
        "min_lots": MIN_LOTS,
        "load_from": LOAD_FROM,
        "warmup": WARMUP_CALENDAR_DAYS,
    }


def definitions_sha256() -> str:
    """Hash of every fixed number the verdicts depend on (the definitions, the
    segments, both thresholds, the costs).  A changed tool needs a new
    exploration report before a validation."""

    text = json.dumps(definitions(), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- reading ----------------------------------------------------------------------


@dataclass
class MarginLists:
    """The stored ``margin_lists`` of the window: which (exchange, day) have a
    list, the symbols whose note contains ``X``, the list's size and every
    note seen (for the coverage)."""

    present: set[tuple[str, date]] = field(default_factory=set)
    x: dict[tuple[str, date], frozenset[str]] = field(default_factory=dict)
    members: dict[tuple[str, date], int] = field(default_factory=dict)
    notes: Counter = field(default_factory=Counter)

    def has(self, exchange: str, day: date | None) -> bool:
        return day is not None and (exchange, day) in self.present


def read_margin_lists(db: Path, start: date, end: date) -> MarginLists:
    """Every list from ``start`` to ``end`` (nothing after ``end``)."""

    out = MarginLists()
    con = lib.connect_read_only(db)
    try:
        for exchange, day, text in con.execute(
            "select exchange, trading_date, members_json from margin_lists "
            "where trading_date >= ? and trading_date <= ?",
            (start.isoformat(), end.isoformat()),
        ):
            key = (exchange, date.fromisoformat(day))
            members = json.loads(text) if text else {}
            members = members or {}
            out.present.add(key)
            out.members[key] = len(members)
            marked = []
            for symbol, note in members.items():
                note = note or ""
                out.notes[note] += 1
                if X_NOTE in note:
                    marked.append(symbol)
            out.x[key] = frozenset(marked)
    finally:
        con.close()
    return out


def trade_context(market: pr.Market, db: Path, end: date) -> tr.Context:
    """``trade_research.Context`` on ``market`` with what B2's trades read
    beyond the panel: the statuses and the last bar of a delisted or
    transferred stock (dates only), as ``trade_research.load`` reads them; a
    test compares the two."""

    ctx = tr.Context(market, db, end)
    report = lib.research_report()
    types = report.BENCHMARK_TYPES
    marks = ",".join("?" * len(types))
    con = lib.connect_read_only(db)
    try:
        ranges = report.excluded_ranges(con)
        ctx.statuses = dict(con.execute("select id, status from instruments"))
        ctx.last_bar = {
            instrument_id: date.fromisoformat(day)
            for instrument_id, day in con.execute(
                "select i.id, max(mb.trading_date) from instruments i "
                "join market_bars mb on mb.instrument_id = i.id "
                f"where i.instrument_type in ({marks}) and i.status in ('delisted', 'transferred') "
                "group by i.id",
                types,
            )
        }
        for instrument_id, day in report.last_kept_bars(
            con, ranges, ctx.last_bar
        ).items():
            if day is None:
                del ctx.last_bar[instrument_id]
            else:
                ctx.last_bar[instrument_id] = day
    finally:
        con.close()
    ctx.index_days = sorted(ctx.panel.index_close)
    return ctx


@dataclass
class Context:
    """``explore_research``'s context (the market, the quotes), the trade
    context on the same market (B2), the margin lists and the time of each
    feature.  One panel."""

    base: ex.Context
    trade: tr.Context
    lists: MarginLists
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
    """The panel, the trade context and the margin lists from ``start`` to
    ``end``; nothing after ``end`` is read but the date of a delisted or
    transferred stock's last bar (no price)."""

    started = time.monotonic()
    base = ex.load_context(db, start, end, raw_dir)
    panel_seconds = time.monotonic() - started
    trade = trade_context(base.market, db, end)
    listed = time.monotonic()
    lists = read_margin_lists(db, start, end)
    return Context(
        base,
        trade,
        lists,
        load_seconds={
            "panel": panel_seconds,
            "margin_lists": time.monotonic() - listed,
        },
    )


# --- features ---------------------------------------------------------------------


def short_margin_ratio(item: lib.Series, at: int) -> float | None:
    """short_balance[at] ÷ margin_balance[at] (docs 第九輪 B1 第 1～3 點)."""

    shorts = item.chips.get("short_balance")
    margins = item.chips.get("margin_balance")
    if shorts is None or margins is None:
        return None
    short, margin = shorts[at], margins[at]
    if short != short or margin != margin:  # no chip row, or a null balance
        return None
    if not margin > 0:
        return None
    return short / margin


def x_start(
    lists: MarginLists, exchange: str, symbol: str, day: date, before: date | None
) -> bool | None:
    """On ``day``'s list with ``X`` and not with ``X`` on ``before``'s (docs
    第九輪 B2 第 1、2 點); None without either list."""

    if not lists.has(exchange, day) or not lists.has(exchange, before):
        return None
    return (
        symbol in lists.x[(exchange, day)] and symbol not in lists.x[(exchange, before)]
    )


def new_x(lists: MarginLists, exchange: str, day: date, before: date | None) -> int:
    """The symbols of the whole list with ``x_start`` on ``day`` (both lists
    present; 0 otherwise)."""

    if not lists.has(exchange, day) or not lists.has(exchange, before):
        return 0
    return len(lists.x[(exchange, day)] - lists.x[(exchange, before)])


def market_wide(
    lists: MarginLists, exchange: str, day: date, before: date | None
) -> bool:
    """New ``X`` on at least ``MARKET_WIDE_SHARE`` of ``day``'s list (#926
    decision 7056755897): a market-wide measure, not the registered event."""

    size = lists.members.get((exchange, day), 0)
    if not size:
        return False
    share = Fraction(str(MARKET_WIDE_SHARE))
    return new_x(lists, exchange, day, before) >= share * size


def limit_up_price(
    market: pr.Market, item: lib.Series, at: int
) -> tuple[float, float] | None:
    """(T's unadjusted close, T's limit-up price), or None (docs 第九輪 B3 第 1～3
    點): T or the bar before suspended, a close missing or ≤ 0, no limit."""

    if at < 1 or item.is_suspended(at) or item.is_suspended(at - 1):
        return None
    raw_close = market.raw[item.instrument_id][2][at]
    if not raw_close > 0 or not item.close[at] > 0 or not item.close[at - 1] > 0:
        return None
    bounds = market.limits(item.instrument_id, at)  # the bar before is at − 1
    if bounds is None:
        return None
    return raw_close, bounds[1]


def limit_up_close(market: pr.Market, item: lib.Series, at: int) -> bool | None:
    parts = limit_up_price(market, item, at)
    if parts is None:
        return None
    return parts[0] >= parts[1] - LIMIT_EPS


# --- B1 and B3: the portfolio engine ----------------------------------------------


order_key = r5.order_key


def segment_window(
    sessions: list[date], segment: str, spec: dict[str, Any]
) -> tuple[int, int] | None:
    """(first, last) index of the sessions with an equity value (or, for B2,
    the sessions after a signal date), or None (``explore_research``'s
    ``segment_window`` on this tool's segments)."""

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


@dataclass
class Ranked:
    rows: list[tuple[int, dict[str, float | None], str]]
    missing: int = 0
    zero: int = 0  # B1: a ratio of 0
    hits: int = 0  # B3: members meeting the condition


def rank(
    ctx: Context, spec: dict[str, Any], day: date, members: list[tuple[lib.Series, int]]
) -> Ranked:
    """The day's members in the hypothesis's order (B1) or those meeting its
    condition by the tie (B3), and the counts of missing values."""

    out = Ranked([])
    rows = []
    if spec["condition"] == "limit_up_close":
        started = time.perf_counter()
        for item, at in members:
            parts = limit_up_price(ctx.market, item, at)
            if parts is None:
                out.missing += 1
                continue
            if parts[0] >= parts[1] - LIMIT_EPS:
                rows.append(
                    (
                        item.instrument_id,
                        {
                            "limit_up_close": 1.0,
                            "close": parts[0],
                            "limit_up": parts[1],
                        },
                        pr.tie_break(day, item.instrument_id),
                    )
                )
        ctx.seconds["limit_up_close"] += time.perf_counter() - started
        rows.sort(key=lambda row: row[2])
        out.hits = len(rows)
    else:
        name = spec["keys"][0][0]
        started = time.perf_counter()
        for item, at in members:
            value = short_margin_ratio(item, at)
            out.missing += value is None
            out.zero += value == 0
            rows.append(
                (
                    item.instrument_id,
                    {name: value},
                    pr.tie_break(day, item.instrument_id),
                )
            )
        ctx.seconds[name] += time.perf_counter() - started
        keys = tuple(spec["keys"])
        rows.sort(key=lambda row: order_key(row[1], keys, row[2]))
    out.rows = rows
    return out


@dataclass
class Plan:
    picks: dict[int, list[int]] = field(default_factory=dict)
    population: dict[int, list[int]] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    signal_days: int = 0


def _coverage_add(
    coverage: dict[str, Any], spec: dict[str, Any], day: date, members: int, r: Ranked
) -> None:
    year = coverage.setdefault(str(day.year), {"days": 0, "members": 0, "missing": 0})
    year["days"] += 1
    year["members"] += members
    year["missing"] += r.missing
    if spec["condition"] == "limit_up_close":
        year["hits"] = year.get("hits", 0) + r.hits
        year["over_top_days"] = year.get("over_top_days", 0) + (r.hits > spec["top"])
        year["max_hits"] = max(year.get("max_hits", 0), r.hits)
    else:
        year["zero"] = year.get("zero", 0) + r.zero


PICK_FIELDS = {
    "B1": ("short_margin_ratio",),
    "B3": ("close", "limit_up"),
}


def plan(
    ctx: Context, spec: dict[str, Any], name: str, first: int, last: int, keep_rows=True
) -> Plan:
    """The picks, the population and the coverage on the signal dates
    ``first − 1`` .. ``last − 1`` (only T's data and before is read)."""

    panel = ctx.panel
    out = Plan()
    top = spec["top"]
    for at in range(first - 1, last):
        day = panel.sessions[at]
        members = lib.universe(panel, day, MIN_LOTS)
        ranked = rank(ctx, spec, day, members)
        _coverage_add(out.coverage, spec, day, len(members), ranked)
        out.signal_days += 1
        if not keep_rows:
            continue
        out.picks[at + 1] = [row[0] for row in ranked.rows]
        out.population[at + 1] = [item.instrument_id for item, _ in members]
        for place, (instrument_id, values, tie) in enumerate(ranked.rows[:top], 1):
            exchange, symbol, _ = panel.symbols.get(instrument_id, ("", "", ""))
            out.rows.append(
                {
                    "signal_date": day.isoformat(),
                    "rank": place,
                    "exchange": exchange,
                    "symbol": symbol,
                    **{key: values.get(key) for key in PICK_FIELDS[name]},
                    "tie": tie[:12],
                }
            )
    return out


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


def run_portfolio(
    ctx: Context,
    db: Path,
    name: str,
    segment: str,
    coverage_only: bool = False,
    min_t: float = MIN_T,
) -> dict[str, Any]:
    """B1 or B3 on one segment: its numbers, verdict and private parts."""

    spec = HYPOTHESES[name]
    sessions = ctx.panel.sessions
    result = _result(name, segment)
    window = segment_window(sessions, segment, spec)
    if window is None:
        result["reason"] = "no_sessions"
        return result
    first, last = window
    days = last - first + 1
    result["window"] = r5._window_facts(sessions, window)
    if segment != USED and not coverage_only:
        if not _prerequisites(db, result, segment, sessions, first, last):
            return result
    ctx.seconds.clear()
    started = time.monotonic()
    planned = plan(ctx, spec, name, first, last, keep_rows=not coverage_only)
    result["window"]["signal_days"] = planned.signal_days
    result["coverage"] = planned.coverage
    feature = spec["condition"] or spec["keys"][0][0]
    result["seconds"] = {
        "plan": time.monotonic() - started,
        feature: ctx.seconds[feature],
    }
    if coverage_only:
        return result
    mine = pr.simulate(planned.picks, ctx.quote, first, last, spec["hold"], spec["top"])
    population = pr.simulate(
        planned.population, ctx.quote, first, last, spec["hold"], None
    )
    returns = pr.daily_returns(mine.equity)
    others = pr.daily_returns(population.equity)
    taiex = ex._taiex(ctx.panel, first, last)
    excess = {
        POPULATION: pr.excess_metrics([a - b for a, b in zip(returns, others)]),
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


# --- B2: trade by trade -----------------------------------------------------------


def enter_next_open(bars: tr.TradeBars) -> er.Entry:
    """T+1's open, a deadline of one session: not tradable (suspended, no bar)
    or locked at limit up abandons the signal (docs 第九輪 B2 進場區與成交)."""

    bar = bars[0]
    if bar.suspended:
        return er.Entry(None, None, "not_tradable", 0)
    if bar.locked_up:
        return er.Entry(None, None, "limit_up", 1)
    return er.Entry(1, bar.open * (1.0 + tr.SLIPPAGE), "filled", 0)


@dataclass
class EventState:
    """B2's run: ``trade_research.State`` (the trades, the occupancy) plus the
    days without a list and the signals by year and exchange."""

    state: tr.State
    missing_days: Counter = field(default_factory=Counter)  # by exchange
    years: dict[str, Counter] = field(default_factory=dict)
    # (day, exchange, new X, list size) of the market-wide days excluded
    market_wide: list[dict[str, Any]] = field(default_factory=list)


def _signals(
    ctx: Context,
    s: int,
    members: list[tuple[lib.Series, int]],
    missing: Counter,
    excluded: list[dict[str, Any]] | None = None,
) -> list[tuple[lib.Series, int, float]]:
    """B2's signals of signal date ``s`` among ``members`` (item, at, ratio);
    ``missing`` counts the exchanges without the two lists, ``excluded``
    gets the market-wide days."""

    panel, lists = ctx.panel, ctx.lists
    day = panel.sessions[s]
    before = panel.sessions[s - 1] if s > 0 else None
    open_ = {}
    for exchange in MARKETS:
        open_[exchange] = lists.has(exchange, day) and lists.has(exchange, before)
        missing[exchange] += not open_[exchange]
        if open_[exchange] and market_wide(lists, exchange, day, before):
            open_[exchange] = False
            if excluded is not None:
                excluded.append(
                    {
                        "date": day.isoformat(),
                        "exchange": exchange,
                        "new_x": new_x(lists, exchange, day, before),
                        "list_members": lists.members[(exchange, day)],
                    }
                )
    out = []
    started = time.perf_counter()
    for item, at in members:
        exchange, symbol, _ = panel.symbols.get(item.instrument_id, ("", "", ""))
        if not open_.get(exchange):
            continue
        if not x_start(lists, exchange, symbol, day, before):
            continue
        ratio = short_margin_ratio(item, at)
        if ratio is not None and ratio >= MIN_RATIO:
            out.append((item, at, ratio))
    ctx.seconds["x_start"] += time.perf_counter() - started
    return out


def event_day(ctx: Context, run: EventState, s: int, s_last: int) -> None:
    """B2's signals on signal date ``s``, each traded at once."""

    trade, state = ctx.trade, run.state
    members = [
        (item, at)
        for item, at in trade.universe(s)
        if state.busy.get(item.instrument_id, -1) < s
    ]
    day = ctx.panel.sessions[s]
    made = 0
    for item, at, ratio in _signals(ctx, s, members, run.missing_days, run.market_wide):
        bars = tr.TradeBars(trade, item, s, s_last)
        entry = enter_next_open(bars)
        row = tr._trade_row(
            trade,
            state,
            s,
            item,
            None,
            bars,
            entry,
            0,  # the fill (or the abandonment) is T+1, key 0
            NO_STOP,
            None,
            s_last,
            {
                "short_margin_ratio": ratio,
                "short_balance": item.chips["short_balance"][at],
                "margin_balance": item.chips["margin_balance"][at],
            },
        )
        row["stop"] = None  # no stop: NO_STOP is only settle's argument
        state.trades.append(row)
        exchange = row["exchange"]
        year = run.years.setdefault(str(day.year), Counter())
        year[f"{exchange}:signals"] += 1
        made += 1
    state.signal_days += made > 0


def run_trades(
    ctx: Context, db: Path, name: str, segment: str, min_t: float = MIN_T
) -> dict[str, Any]:
    """B2 on one segment (docs 逐筆評估): its numbers, verdict and trades."""

    spec = HYPOTHESES[name]
    sessions = ctx.panel.sessions
    result = _result(name, segment)
    window = segment_window(sessions, segment, spec)
    if window is None:
        result["reason"] = "no_sessions"
        return result
    first, last = window
    result["window"] = r5._window_facts(sessions, window)
    if segment != USED:
        if not _prerequisites(db, result, segment, sessions, first, last):
            return result
    ctx.seconds.clear()
    started = time.monotonic()
    run = EventState(tr.State(name, spec))
    for s in range(first - 1, last):
        event_day(ctx, run, s, last)
    result["window"]["signal_days"] = last - first + 1
    numbers = tr.stats(run.state)
    result.update(numbers)
    result["listed"] = {
        "missing_list_days": {
            exchange: run.missing_days[exchange] for exchange in MARKETS
        },
        "years": {year: dict(counts) for year, counts in sorted(run.years.items())},
        "market_wide": run.market_wide,
    }
    result["seconds"] = {
        "run": time.monotonic() - started,
        "x_start": ctx.seconds["x_start"],
    }
    result["_trades"] = run.state.trades
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
    if HYPOTHESES[name]["engine"] == TRADE:
        return run_trades(ctx, db, name, segment, min_t)
    return run_portfolio(ctx, db, name, segment, min_t=min_t)


# --- --coverage-only for B2 -------------------------------------------------------


def event_coverage(ctx: Context, name: str = "B2") -> dict[str, Any]:
    """B2 第 5、6 點 on every signal date of the exploration, without the
    occupancy (nothing is traded): by year and exchange the signal dates, the
    dates without a list, the new ``X`` on the whole list, the ``x_start`` of
    the population and the signals; the days with the most new ``X``."""

    spec = HYPOTHESES[name]
    panel, lists = ctx.panel, ctx.lists
    sessions = panel.sessions
    window = segment_window(sessions, EXPLORATION, spec)
    if window is None:
        return {"window": {"days": 0}, "years": {}, "top_days": {}}
    first, last = window
    ctx.seconds.clear()
    started = time.monotonic()
    years: dict[str, dict[str, Any]] = {}
    days_x: dict[str, list[tuple[int, str, int]]] = {
        exchange: [] for exchange in MARKETS
    }
    for s in range(first - 1, last):
        day = sessions[s]
        before = sessions[s - 1] if s > 0 else None
        year = years.setdefault(
            str(day.year),
            {"days": 0, "markets": {exchange: Counter() for exchange in MARKETS}},
        )
        year["days"] += 1
        for exchange in MARKETS:
            market = year["markets"][exchange]
            if not (lists.has(exchange, day) and lists.has(exchange, before)):
                market["missing_list_days"] += 1
                continue
            new = new_x(lists, exchange, day, before)
            market["new_x"] += new
            market["market_wide_days"] += market_wide(lists, exchange, day, before)
            market["max_new_x"] = max(market["max_new_x"], new)
            days_x[exchange].append(
                (new, day.isoformat(), lists.members[(exchange, day)])
            )
        members = lib.universe(panel, day, MIN_LOTS)
        t0 = time.perf_counter()
        for item, at in members:
            exchange, symbol, _ = panel.symbols.get(item.instrument_id, ("", "", ""))
            if exchange not in MARKETS:
                continue
            market = year["markets"][exchange]
            market["members"] += 1
            if not x_start(lists, exchange, symbol, day, before):
                continue
            market["x_start"] += 1
            ratio = short_margin_ratio(item, at)
            if ratio is None:
                market["ratio_missing"] += 1
            elif ratio >= MIN_RATIO:
                wide = market_wide(lists, exchange, day, before)
                market["market_wide_signals" if wide else "signals"] += 1
        ctx.seconds["x_start"] += time.perf_counter() - t0
    top_days = {
        exchange: [
            {"date": day, "new_x": new, "list_members": size}
            for new, day, size in sorted(rows, key=lambda row: (-row[0], row[1]))[
                :TOP_X_DAYS
            ]
        ]
        for exchange, rows in days_x.items()
    }
    return {
        "window": r5._window_facts(sessions, window),
        "years": {
            key: {
                "days": row["days"],
                "markets": {
                    exchange: dict(counts)
                    for exchange, counts in row["markets"].items()
                },
            }
            for key, row in sorted(years.items())
        },
        "top_days": top_days,
        "notes": dict(
            sorted(lists.notes.items(), key=lambda item: (-item[1], item[0]))
        ),
        "seconds": {
            "plan": time.monotonic() - started,
            "x_start": ctx.seconds["x_start"],
        },
    }


# --- output -----------------------------------------------------------------------


SEGMENT_NAMES = ex.SEGMENT_NAMES
_pct = ex._pct
_t = ex._t
public = ex.public
threshold = r5.threshold
_share = r5._share
PORTFOLIO_TRADE_FIELDS = r5.TRADE_FIELDS
EVENT_TRADE_FIELDS = (
    "signal_date",
    "exchange",
    "symbol",
    "short_margin_ratio",
    "short_balance",
    "margin_balance",
    "entry_reason",
    "limit_blocked",
    "abandoned_date",
    "fill_date",
    "fill_price",
    "exit_date",
    "exit_reason",
    "exit_price",
    "net",
    "holding",
    "limit_delayed",
    "suspension_delayed",
    "population",
    "population_members",
    "population_unbought",
    "excess",
    "taiex",
    "taiex_excess",
)


def _threshold_line(segment: str, min_t: float) -> str:
    return (
        f"- 門檻：超額日均 > 0 且 t ≥ {threshold(min_t)}，且絕對報酬日均 > 0；"
        f"段長下限 {MIN_SEGMENT_DAYS.get(segment, '—')} 日；研究 DB 要有段內已下市公司；"
        f"B2 另要有成交的訊號日至少 {MIN_DAYS} 日（逐筆評估）。"
        f"探索段 t ≥ {threshold(MIN_T)}，驗證段 t ≥ {threshold(VALIDATION_MIN_T)}"
        f"（Bonferroni，累計 {CUMULATIVE} 個：1 − Φ(z)＝0.025 ÷ {CUMULATIVE}，寫死不重算）"
    )


def portfolio_coverage_lines(name: str, coverage: dict[str, Any]) -> list[str]:
    """B1: missing and 0 ratios; B3: the members meeting the condition, the
    days with more than 20 and the missing share (分母是母體檔次)."""

    if name == "B1":
        head = ["年", "日數", "母體檔次", "券資比缺值", "券資比是 0"]
    else:
        head = [
            "年",
            "日數",
            "母體檔次",
            "收盤等於漲停價的檔日",
            "每日平均檔數",
            "一天最多",
            "超過 20 檔的天數",
            "缺值（不符合）",
        ]
    lines = [
        "| " + " | ".join(head) + " |",
        "| --- | " + " | ".join("---:" for _ in head[1:]) + " |",
    ]
    for year, row in sorted(coverage.items()):
        members, days = row["members"], row["days"]
        cells = [f"{days:,}", f"{members:,}"]
        if name == "B1":
            cells += [
                _share(row["missing"], members),
                _share(row.get("zero", 0), members),
            ]
        else:
            hits = row.get("hits", 0)
            cells += [
                f"{hits:,}",
                lib.num(hits / days, 2) if days else "—",
                f"{row.get('max_hits', 0):,}",
                f"{row.get('over_top_days', 0):,}",
                _share(row["missing"], members),
            ]
        lines.append(f"| {year} | " + " | ".join(cells) + " |")
    return lines


def event_coverage_lines(coverage: dict[str, Any]) -> list[str]:
    """B2 第 5、6 點 by year and exchange."""

    head = ["年", "訊號日"]
    for label in MARKETS.values():
        head += [
            f"{label}母體檔次",
            f"{label}名單缺列的天數",
            f"{label}名單新增 X（檔次）",
            f"{label}一天新增 X 最多",
            f"{label}母體中 x_start",
            f"{label}其中券資比缺值",
            f"{label}訊號數（券資比 ≥ 0.3）",
            f"{label}全市場措施日",
            f"{label}措施日排除的訊號",
        ]
    lines = [
        "| " + " | ".join(head) + " |",
        "| --- | " + " | ".join("---:" for _ in head[1:]) + " |",
    ]
    for year, row in coverage.get("years", {}).items():
        cells = [f"{row['days']:,}"]
        for exchange in MARKETS:
            m = row["markets"].get(exchange, {})
            cells += [
                f"{m.get(key, 0):,}"
                for key in (
                    "members",
                    "missing_list_days",
                    "new_x",
                    "max_new_x",
                    "x_start",
                    "ratio_missing",
                    "signals",
                    "market_wide_days",
                    "market_wide_signals",
                )
            ]
        lines.append(f"| {year} | " + " | ".join(cells) + " |")
    return lines


def top_days_lines(coverage: dict[str, Any]) -> list[str]:
    lines = [
        "| 交易所 | 日期 | 名單新增 X 的檔數 | 名單檔數 | 占名單 |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for exchange, rows in coverage.get("top_days", {}).items():
        for row in rows:
            lines.append(
                f"| {MARKETS[exchange]} | {row['date']} | {row['new_x']:,} "
                f"| {row['list_members']:,} | {_share(row['new_x'], row['list_members'])} |"
            )
    return lines


def _head_lines(
    result: dict[str, Any], header: dict[str, Any], spec: dict[str, Any]
) -> list[str]:
    name = result["hypothesis"]
    segment = SEGMENT_NAMES[result["segment"]]
    window = result["window"] or {}
    verdict = result["verdict"] or "只列出、不判定"
    sizes = (
        f"全部符合、持有 {spec['hold']} 日"
        if spec["engine"] == TRADE
        else f"N＝{spec['top']}、K＝{spec['hold']}"
    )
    lines = [
        f"# {name} {segment}（round9_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 判定：**{verdict}**"
        + (f"（{REASONS[result['reason']]}）" if result["reason"] else ""),
        f"- 假設：{spec['direction']}；{spec['label']}；{sizes}",
        f"- 登記 commit `{REGISTRATION_COMMIT}`；{DECISION}；"
        f"定義雜湊 `{header['definitions_sha256'][:16]}…`",
        f"- 期間：訊號日 {window.get('first_signal', '—')} 起，"
        + ("成交日" if spec["engine"] == TRADE else "有淨值的交易日")
        + f" {window.get('first_session', '—')}～{window.get('last_session', '—')}，共 "
        f"{window.get('days', 0)} 個交易日",
        f"- 退化：{DEGENERATE[name]}"
        + (f"；{DEGENERATE['B2_market_wide']}" if name == "B2" else ""),
        f"- 限制：{LIMITS[name]}",
    ]
    prerequisites = result.get("prerequisites")
    if prerequisites:
        lines.append(
            f"- 先決條件：段長 {prerequisites['days']}／下限 {prerequisites['min_days']} 日；"
            f"段內已下市公司 {prerequisites['delisted']} 檔"
        )
    lines += [
        f"- 副本：最新交易日 {header['copy']['latest']}，alembic `{header['copy']['alembic']}`",
        f"- 重現：`{header['command']}`",
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
            f"| 超額（對加權指數，只列出） | {e[TAIEX]['days']} | {_pct(e[TAIEX]['mean'], 3)} "
            f"| {_pct(e[TAIEX]['annual'])} | {_t(e[TAIEX]['t'])} |",
            f"| 超額（對母體，判定） | {e[POPULATION]['days']} | {_pct(e[POPULATION]['mean'], 3)} "
            f"| {_pct(e[POPULATION]['annual'])} | {_t(e[POPULATION]['t'])} |",
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
            f"（{w['won']:,}／{w['bought']:,}，期末未賣 {w['unsold']:,}）。",
            f"成交計數：買進 {counts.get('bought', 0):,}、漲停買不到 "
            f"{counts.get('limit_up', 0):,}、不可交易 {counts.get('not_tradable', 0):,}、"
            f"跌停順延 {counts.get('limit_down', 0):,}、停牌／缺日線順延 "
            f"{counts.get('sale_held', 0):,}、期末未賣 {counts.get('unsold', 0):,}。",
            "",
        ]
    if result.get("coverage"):
        lines += [
            "## 資料覆蓋（不含報酬）",
            "",
            *portfolio_coverage_lines(name, result["coverage"]),
            "",
        ]
    return "\n".join(lines)


def event_markdown(result: dict[str, Any], header: dict[str, Any]) -> str:
    name = result["hypothesis"]
    spec = HYPOTHESES[name]
    lines = _head_lines(result, header, spec)
    if "excess" not in result:
        return "\n".join(lines)
    x, e, a = result["taiex_excess"], result["excess"], result["absolute"]
    lines += [
        "## 數字（訊號日序列：同一訊號日的各筆先平均）",
        "",
        "| 量 | 訊號日數 | 平均 | t |",
        "| --- | ---: | ---: | ---: |",
        f"| 超額（對加權指數，只列出） | {x['days']} | {_pct(x['mean'], 3)} | {_t(x['t'])} |",
        f"| 超額（對母體，判定） | {e['days']} | {_pct(e['mean'], 3)} | {_t(e['t'])} |",
        f"| 扣成本報酬（判定） | {a['days']} | {_pct(a['mean'], 3)} | — |",
        "",
        f"門檻：t ≥ {threshold(result.get('min_t', MIN_T))}（`t_stat(…, overlap={OVERLAP})`）；"
        f"有成交的訊號日至少 {MIN_DAYS} 日。",
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
    for reason in tr.EXIT_REASONS:
        if reason in ("stop", "target"):
            continue  # B2 has neither
        lines.append(
            f"| 出場：{tr.EXIT_LABELS[reason]} | {_pct(result['exit_share'][reason], 1)}"
            f"（{result['exits'][reason]:,}） |"
        )
    listed = result.get("listed", {})
    lines += [
        f"| 跌停順延 | {result['limit_delayed']:,} |",
        f"| 停牌順延 | {result['suspension_delayed']:,} |",
        f"| 母體在 e 買不進的檔次 | {result['population_unbought']:,} |",
        *(
            f"| {label}名單缺列的天數（T 或前一個交易日） | "
            f"{listed.get('missing_list_days', {}).get(exchange, 0):,} |"
            for exchange, label in MARKETS.items()
        ),
        "",
        "### 全市場措施日（排除，#926 決定 7056755897）",
        "",
        f"{DEGENERATE['B2_market_wide']}。",
        "",
        "| 日期 | 交易所 | 名單新增 X | 名單檔數 |",
        "| --- | --- | ---: | ---: |",
        *(
            f"| {row['date']} | {MARKETS[row['exchange']]} | {row['new_x']:,} "
            f"| {row['list_members']:,} |"
            for row in listed.get("market_wide", [])
        ),
        "",
        "### 每年的訊號數",
        "",
        "| 年 | 上市 | 上櫃 |",
        "| --- | ---: | ---: |",
    ]
    for year, counts in listed.get("years", {}).items():
        lines.append(
            f"| {year} | {counts.get('TWSE:signals', 0):,} | {counts.get('TPEx:signals', 0):,} |"
        )
    lines.append("")
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
    trade = spec["engine"] == TRADE
    (out / "summary.md").write_text(
        event_markdown(result, header) if trade else portfolio_markdown(result, header),
        encoding="utf-8",
    )
    if trade and "_trades" in result:
        _write_trades(out, result["_trades"])
    elif "_dates" in result:
        _write_portfolio(out, result, header)


def _write_trades(out: Path, trades: list[dict[str, Any]]) -> None:
    with (out / "trades.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(EVENT_TRADE_FIELDS)
        for trade in trades:
            writer.writerow([_cell(trade.get(key)) for key in EVENT_TRADE_FIELDS])
    days: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        if trade["net"] is not None:
            days[trade["signal_date"]].append(trade)
    with (out / "days.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["signal_date", "trades", "net", "excess", "taiex_excess"])
        for day, rows in sorted(days.items()):
            cells = []
            for key in ("net", "excess", "taiex_excess"):
                values = [row[key] for row in rows if row[key] is not None]
                cells.append(_cell(statistics.fmean(values)) if values else "")
            writer.writerow([day.isoformat(), len(rows), *cells])


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
    """The overview's row: the portfolio engine's excess, or the trades'."""

    if result["engine"] == TRADE:
        return {"engine": TRADE, **tr._row(result)}
    return {"engine": PORTFOLIO, **r5._row(result)}


def overview_markdown(report: dict[str, Any], sha256: str) -> str:
    segment = report["segment"]
    stage = SEGMENT_NAMES[segment]
    lines = [
        f"explore.json 的 sha256：`{sha256}`",
        "",
        f"# 新策略探索 第 {report['round']} 輪 {stage}（round9_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「第九輪：B1～B3」）：{DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        _threshold_line(segment, report["min_t"]),
        "- 引擎：B1、B3 是組合引擎（`portfolio_research.simulate`，日數是有淨值的交易日）；"
        "B2 是逐筆評估（`trade_research`，日數是段內交易日，超額與 t 在訊號日序列上）",
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
        lines.append(
            f"- 前瞻觀察：超額 > 0 但 t < {threshold(report['min_t'])}，且絕對報酬 > 0；"
            "只當紀錄，不算通過、不進產品"
        )
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
    trade = row.get("engine") == TRADE
    return (
        f"| {name} | {spec['direction']} | {'逐筆' if trade else '組合'} | {row['days']} "
        f"| {(row.get('trade_days') or 0) if trade else '—'} "
        f"| {_pct(x.get('mean'), 3)} | {_t(x.get('t'))} "
        f"| {_pct(e.get('mean'), 3)} | {_t(e.get('t'))} "
        f"| {_pct(row.get('absolute_mean'), 3)} | {verdict} |"
    )


def seconds_lines(body: dict[str, Any]) -> list[str]:
    """The time of each hypothesis's signal dates and of its feature."""

    lines = [
        "| 代號 | 訊號日 | 排序與覆蓋（秒） | 特徵計算（秒） | 每個訊號日（毫秒） |",
        "| --- | ---: | ---: | --- | ---: |",
    ]
    for name, row in body["hypotheses"].items():
        seconds = row.get("seconds") or {}
        days = (row["window"] or {}).get("days", 0)
        parts = "、".join(
            f"`{key}` {value:.1f}" for key, value in seconds.items() if key != "plan"
        )
        per_day = lib.num(seconds.get("plan", 0.0) * 1000 / days, 1) if days else "—"
        lines.append(
            f"| {name} | {days:,} | {seconds.get('plan', 0.0):.1f} | {parts or '—'} "
            f"| {per_day} |"
        )
    return lines


COVERAGE_NOTES = (
    "- 缺值比例的分母是母體檔次（每個訊號日的母體加總）",
    f"- B1：`short_margin_ratio` 在 {DEGENERATE['B1']}；另列「是 0」的比例",
    f"- B2：{DEGENERATE['B2']}；{DEGENERATE['B2_market_wide']}"
    "（訊號數不含這些日子，另列「措施日排除的訊號」）。每個訊號日都數，不扣占用（沒有模擬成交）。"
    "「名單新增 X」數的是整份名單（不限母體）上 T 有 `X`、前一個交易日沒有 `X` 的檔數；"
    "`x_start`、券資比缺值與訊號數只數母體",
    f"- B3：`limit_up_close` 在 {DEGENERATE['B3']}；漲停價是 "
    "`portfolio_research.Market.limits` 的上限（前一根收盤換到 T 的未還原基準，"
    "`exit_research.price_limits` 依日期、`tick_floor`）",
    "- 各假設用自己的訊號日（起日寫在各段標題）",
)


def coverage_markdown(body: dict[str, Any]) -> str:
    load_seconds = body.get("load_seconds_parts", {})
    lines = [
        f"# 新策略探索 第 {body['round']} 輪 B1～B3 資料覆蓋（探索段，不含報酬）",
        "",
        f"- round9_research 第 {VERSION} 版；定義雜湊 `{body['definitions_sha256']}`",
        f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}，"
        f"alembic `{body['copy']['alembic']}`",
        f"- 重現：`{body['command']}`",
        f"- 耗時 {body.get('elapsed_seconds', 0):.0f} 秒（載入 {body.get('load_seconds', 0):.0f} 秒，"
        f"其中名單 {load_seconds.get('margin_lists', 0):.0f} 秒），"
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
        ]
        if HYPOTHESES[name]["engine"] == TRADE:
            lines += [
                "### B2 第 5、6 點：依年、依交易所",
                "",
                *event_coverage_lines(row["coverage"]),
                "",
                f"### 名單新增 X 最多的 {TOP_X_DAYS} 天（依交易所）",
                "",
                "全市場同時出現 `X` 的日子（例如暫時措施）先在工具單提問、不跑 B2 的探索段。",
                "",
                *top_days_lines(row["coverage"]),
                "",
                "### 讀到的名單註記（整份名單，全部的值與次數）",
                "",
                "| 註記 | 次數 |",
                "| --- | ---: |",
                *(
                    f"| `{note}` | {count:,} |" if note else f"| （空白） | {count:,} |"
                    for note, count in row["coverage"].get("notes", {}).items()
                ),
                "",
            ]
        else:
            lines += [*portfolio_coverage_lines(name, row["coverage"]), ""]
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
            "trade_research": tr.VERSION,
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


def load_from(segment: str) -> date:
    """The first day read: the copy's start for the exploration (as
    ``explore_research``), the warm-up before a later segment."""

    first_day = SEGMENTS[segment][0]
    if first_day is None:
        return LOAD_FROM
    return first_day - timedelta(days=WARMUP_CALENDAR_DAYS)


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
    ctx = load(db, load_from(EXPLORATION), end, out / RAW_DIR_NAME)
    loaded = time.monotonic() - started
    header = _header(db, EXPLORATION, command, end)
    hypotheses = {}
    for name, spec in HYPOTHESES.items():
        if spec["engine"] == TRADE:
            coverage = event_coverage(ctx, name)
            row = {
                "window": coverage.pop("window"),
                "seconds": coverage.pop("seconds", {}),
                "coverage": coverage,
            }
        else:
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
    ctx = load(db, load_from(EXPLORATION), end, out / RAW_DIR_NAME)
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
    ctx = load(db, load_from(VALIDATION), end, out / RAW_DIR_NAME)
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
        used_ctx = load(db, load_from(USED), SEGMENTS[USED][1], out / RAW_DIR_NAME)
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
    parser = argparse.ArgumentParser(prog="round9_research.py", description=__doc__)
    parser.add_argument(
        "--db", required=True, help="the research DB (/research/stock.db)"
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--segment", required=True, choices=STAGES)
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help="exploration only: counts of dates, members and missing values per "
        "year (B2 also per exchange) and the time of the features, no return",
    )
    parser.add_argument(
        "--hypotheses",
        help="exploration (required, not with --coverage-only): B1, B2, B3 or "
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
    command = "python tools/research/round9_research.py " + " ".join(argv)
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
