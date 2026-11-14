"""New-strategy exploration: the registered X1～X8, judged by ``explore_judge`` (#703).

docs/spec/evidence.md 新策略探索: the hypotheses were registered (commit
``0ba48e9``, #697) and their segments and verdict table fixed (decision
6873866312) before anyone ran a tool on the backfilled history; the design of
this tool is the #703 decision (comment 6874888073).  Nothing here is a
command-line option: a change of a definition is a new code (X9…), and the
golden test of every hypothesis fails on any change of the engine.

The engine is ``portfolio_research.simulate`` (K accounts, T's close, T+1's
open, the K-th session's close, the costs, limits, delays and adjusted
prices); X7 trades on event days (``simulate_events``: one account, the 10th
of each month to the next).  The benchmark is the same engine over the day's
whole population (``evidence_lib.universe``); TAIEX is only listed.

``--segment exploration`` reads nothing after 2019-12-31 (``load_market``'s
``end``); every hypothesis is run and the report is written to be published.
``--segment validation`` runs once, only after the exploration report was
published, and only on the research DB (#701's marker ``research-db.json``
beside it; the volume mounted at ``/research``, not under ``STOCK_DATA_DIR``,
docs 第 2 步的工具): it needs the report, the sha256 quoted in the public comment and
the comment's link, runs only the hypotheses the report passed, and writes a
"started" entry in ``<DB directory>/explore-ledger.json`` before it reads any
validation data; a hypothesis in that ledger or in the repository's
``tools/research/explore_ledger.json`` is refused.  The used segment
(2024-09-30～2026-11-13) is listed only for the hypotheses the validation
passed.  ``--coverage-only`` (exploration) writes the share of missing feature
values per year and no return at all.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import statistics
import subprocess
import sys
import time
from array import array
from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_lib as lib  # noqa: E402
import feature_evidence as features  # noqa: E402
import portfolio_research as pr  # noqa: E402

VERSION = 1
DESIGN = "703"
REGISTRATION_COMMIT = "0ba48e9"
DECISION = "https://github.com/YiCheng0608/stock-lab/issues/703#issuecomment-6874888073"
EXPLORATION = "exploration"
VALIDATION = "validation"
USED = "used"
STAGES = (EXPLORATION, VALIDATION)
# (first day or None for the hypothesis's own start, last day), docs 新策略探索 分段.
SEGMENTS: dict[str, tuple[date | None, date]] = {
    EXPLORATION: (None, date(2019, 12, 31)),
    VALIDATION: (date(2020, 1, 2), date(2024, 9, 27)),
    USED: (date(2024, 9, 30), date(2026, 11, 13)),
}
MIN_SEGMENT_DAYS = {EXPLORATION: 500, VALIDATION: 250}
MIN_T = pr.MIN_T
ROUND = 1
ROUND_SIZE = 8
CUMULATIVE = 8  # X1～X8; H1 and #619～#689 are counted apart
BONFERRONI_AFTER = 20
ONE_SIDED = 0.025
LOAD_FROM = date(1990, 1, 1)  # the exploration reads the copy from its start
WARMUP_CALENDAR_DAYS = 730  # bars before a later segment, for the features only
MIN_LOTS = lib.DEFAULT_MIN_LOTS
EVENT_DAY = 10  # monthly revenues are due on the 10th (rolled to the next session)
TURNOVER_WINDOW = 60
TURNOVER_AVAILABLE = "available"
MOPS_SOURCE = "mops_material_information"
MOPS_EVENT_TYPE = "material_information"
BUYBACK_ALL = ("董事會", "買回")
BUYBACK_ANY = (("決議", "通過"), ("庫藏股", "股份"))
BUYBACK_NONE = (
    "註銷",
    "轉讓",
    "執行情形",
    "執行完畢",
    "已執行",
    "執行期限",
    "辦法",
    "減資",
    "屆滿",
    "完畢",
    "達",
    "變更",
    "公司債",
    "子公司",
    "更正",
    "補充",
    "取消",
)
BUYBACK_LOOKBACK = 20  # sessions before T in which a pick is skipped
LEDGER_NAME = "explore-ledger.json"
# history_backfill's research marker (#701): the validation needs it beside the DB
MARKER_NAME = "research-db.json"
MARKER_PURPOSE = "research_history"
ROOT = Path(__file__).resolve().parents[2]
REPO_LEDGER = ROOT / "tools" / "research" / "explore_ledger.json"
URL_PATTERNS = (
    re.compile(
        r"^https://github\.com/YiCheng0608/stock-lab/issues/\d+#issuecomment-\d+$"
    ),
    re.compile(
        r"^https://github\.com/YiCheng0608/stock-lab/(blob|tree)/pr-assets/\S+$"
    ),
)
RAW_DIR_NAME = "raw"
POPULATION = pr.POPULATION
TAIEX = pr.TAIEX

UNDECIDED = "無法判定"
EXPLORATION_FAILED = "沒有通過（探索段）"
EXPLORATION_PASSED = "探索通過"
PASSED = "通過"
REVERSED = "驗證段反轉"
VALIDATION_FAILED = "沒有通過（驗證段）"
VERDICTS = (
    UNDECIDED,
    EXPLORATION_FAILED,
    EXPLORATION_PASSED,
    PASSED,
    REVERSED,
    VALIDATION_FAILED,
)

# The registration table (docs 第一輪：X1～X8), word for word.  ``start``:
# ("session", anchor, n) is the n-th market session counting the anchor (or the
# first session after it) as the first; ("date", d) the first session from d.
# ``subset``: (feature, n) keeps the n highest of the population, a missing
# value out.  ``filters``: (feature, op, value), a missing value fails.  ``keys``:
# high first, a missing value last, ties by ``portfolio_research.tie_break``.
HYPOTHESES: dict[str, dict[str, Any]] = {
    "X1": {
        "direction": "持有較久、低換手",
        "label": "`momentum_120`（120 日報酬）大者先",
        "rule": "daily",
        "subset": None,
        "filters": (),
        "keys": ("momentum_120",),
        "top": 20,
        "hold": 60,
        "start": ("session", date(2007, 4, 23), 120),
    },
    "X2": {
        "direction": "持有較久、低換手",
        "label": "`high_gap_240`（收盤 ÷ 240 日最高價 − 1）大者先",
        "rule": "daily",
        "subset": None,
        "filters": (),
        "keys": ("high_gap_240",),
        "top": 20,
        "hold": 60,
        "start": ("session", date(2007, 4, 23), 240),
    },
    "X3": {
        "direction": "籌碼＋基本面",
        "label": "只取 `revenue_yoy` > 0，依 `institutional_flow_20` 大者先",
        "rule": "daily",
        "subset": None,
        "filters": (("revenue_yoy", ">", 0.0),),
        "keys": ("institutional_flow_20",),
        "top": 10,
        "hold": 20,
        "start": ("session", date(2014, 12, 1), 20),
    },
    "X4": {
        "direction": "籌碼＋基本面",
        "label": (
            "只取 `revenue_yoy` > 0 且 `eps_growth_yield` > 0，"
            "依最新一季 EPS × 4 ÷ T 日未還原收盤大者先"
        ),
        "rule": "daily",
        "subset": None,
        "filters": (("revenue_yoy", ">", 0.0), ("eps_growth_yield", ">", 0.0)),
        "keys": ("eps_yield_raw",),
        "top": 20,
        "hold": 60,
        "start": ("date", date(2014, 8, 14)),
    },
    "X5": {
        "direction": "大型股傾向",
        "label": "母體中 60 日平均成交金額前 50 名，全部等權買進、不排序",
        "rule": "daily",
        "subset": ("turnover_60", 50),
        "filters": (),
        "keys": (),
        "top": 50,
        "hold": 60,
        "start": ("session", date(2007, 4, 23), 60),
    },
    "X6": {
        "direction": "大型股傾向",
        "label": "母體中 60 日平均成交金額前 150 名，依 `institutional_flow_20` 大者先",
        "rule": "daily",
        "subset": ("turnover_60", 150),
        "filters": (),
        "keys": ("institutional_flow_20",),
        "top": 10,
        "hold": 20,
        "start": ("session", date(2014, 12, 1), 60),
    },
    "X7": {
        "direction": "事件：月營收公布",
        "label": (
            "事件日（每月 10 日，休市順延）只取最新已知月份是上個月且 "
            "`revenue_high_12`＝1，依 `revenue_yoy` 大者先；持有到下一個事件日收盤"
        ),
        "rule": "monthly",
        "subset": None,
        "filters": (
            ("revenue_previous_month", "==", 1.0),
            ("revenue_high_12", "==", 1.0),
        ),
        "keys": ("revenue_yoy",),
        "top": 20,
        "hold": "next_event",
        "start": ("date", date(2014, 1, 10)),
    },
    "X8": {
        "direction": "事件：重大訊息",
        "label": "董事會決議買回庫藏股（主旨規則），T+1 開盤買、持有 20 日",
        "rule": "buyback",
        "subset": None,
        "filters": (),
        "keys": (),
        "top": 20,
        "hold": 20,
        "start": ("session", date(2007, 4, 23), 20),
    },
}
OTHER_COMPARISONS = (
    "前瞻 H1：1 組（#691）",
    "#673 出場規則：14 組",
    "#682 組合層級回測：18 組",
    "#689 評分改版：108 組",
    "#619／#643 特徵判定：組數見各自報告",
)


# --- features ---------------------------------------------------------------

FEATURE_FUNCTIONS = {key: function for key, _l, _g, function in features.FEATURES}


@dataclass
class Context:
    """The market plus what the definitions read beyond ``portfolio_research``."""

    market: pr.Market
    turnover: dict[int, array] = field(default_factory=dict)
    # (session index of T, instrument id, title, listed date), by T
    announcements: list[tuple[int, int, str, date]] = field(default_factory=list)
    cache: dict[tuple[str, int, int], float | None] = field(default_factory=dict)
    quotes: dict[int, pr.Quote | None] = field(default_factory=dict)
    quotes_session: int = -1

    def quote(self, instrument_id: int, s: int) -> pr.Quote | None:
        """``Market.quote``, remembered for the session being simulated: K
        accounts ask for the same bar K times (the engine goes session by
        session, so only one session is kept)."""

        if s != self.quotes_session:
            self.quotes.clear()
            self.quotes_session = s
        if instrument_id not in self.quotes:
            self.quotes[instrument_id] = self.market.quote(instrument_id, s)
        return self.quotes[instrument_id]


def turnover_60(ctx: Context, item: lib.Series, at: int) -> float | None:
    """Mean official turnover of the 60 bars to T inclusive; a bar whose
    ``turnover_status`` is not ``available`` makes it missing (#703 decision)."""

    if at + 1 < TURNOVER_WINDOW:
        return None
    values = ctx.turnover.get(item.instrument_id)
    if values is None:
        return None
    window = values[at + 1 - TURNOVER_WINDOW : at + 1]
    if any(value != value for value in window):
        return None
    return sum(window) / TURNOVER_WINDOW


def eps_yield_raw(ctx: Context, item: lib.Series, at: int) -> float | None:
    """``eps_yield`` over T's unadjusted close (``market_bars.close``)."""

    eps = features._quarter_eps(item, at)
    close = ctx.market.raw[item.instrument_id][2][at]
    return eps[0] * 4.0 / close if eps and close and close > 0 else None


def _previous_month(day: date) -> tuple[int, int]:
    return (day.year - 1, 12) if day.month == 1 else (day.year, day.month - 1)


def revenue_previous_month(ctx: Context, item: lib.Series, at: int) -> float | None:
    """1 when the latest month known at T is the month before T's, else 0."""

    rows = features._revenues_known(item, item.dates[at])
    if not rows:
        return None
    latest = rows[-1][0]
    return (
        1.0 if (latest.year, latest.month) == _previous_month(item.dates[at]) else 0.0
    )


def _existing(key: str) -> Callable[[Context, lib.Series, int], float | None]:
    function = FEATURE_FUNCTIONS[key]

    def feature(_ctx: Context, item: lib.Series, at: int) -> float | None:
        value = function(item, at)
        return None if value is None or value != value else float(value)

    return feature


FEATURES: dict[str, Callable[[Context, lib.Series, int], float | None]] = {
    "momentum_120": _existing("momentum_120"),
    "high_gap_240": _existing("high_gap_240"),
    "revenue_yoy": _existing("revenue_yoy"),
    "institutional_flow_20": _existing("institutional_flow_20"),
    "eps_growth_yield": _existing("eps_growth_yield"),
    "revenue_high_12": _existing("revenue_high_12"),
    "eps_yield_raw": eps_yield_raw,
    "turnover_60": turnover_60,
    "revenue_previous_month": revenue_previous_month,
}


def used_features(spec: dict[str, Any]) -> tuple[str, ...]:
    names: list[str] = []
    if spec["subset"]:
        names.append(spec["subset"][0])
    names += [name for name, _op, _value in spec["filters"]]
    names += list(spec["keys"])
    return tuple(dict.fromkeys(names))


def value_of(ctx: Context, name: str, item: lib.Series, at: int) -> float | None:
    key = (name, item.instrument_id, at)
    if key not in ctx.cache:
        ctx.cache[key] = FEATURES[name](ctx, item, at)
    return ctx.cache[key]


def passes(value: float | None, op: str, threshold: float) -> bool:
    if value is None:
        return False
    return value > threshold if op == ">" else value == threshold


def is_buyback(title: str) -> bool:
    """The registered subject rule of X8 (docs 定義細節 X8 主旨規則)."""

    return (
        all(word in title for word in BUYBACK_ALL)
        and all(any(word in title for word in group) for group in BUYBACK_ANY)
        and not any(word in title for word in BUYBACK_NONE)
    )


# --- the verdict ------------------------------------------------------------


def validation_min_t(cumulative: int) -> float:
    """t ≥ 2 to 20 hypotheses; beyond, Bonferroni on the one-sided 0.025."""

    if cumulative <= BONFERRONI_AFTER:
        return MIN_T
    return statistics.NormalDist().inv_cdf(1.0 - ONE_SIDED / cumulative)


def explore_judge(
    stage: str,
    days: int,
    has_delisted: bool,
    excess: dict[str, Any],
    absolute: float | None,
    min_t: float = MIN_T,
) -> str:
    """The docs 新策略探索 判定 table, first matching row from the top."""

    if days < MIN_SEGMENT_DAYS[stage] or not has_delisted:
        return UNDECIDED
    mean, t = excess.get("mean"), excess.get("t")
    passed = (
        mean is not None
        and mean > 0
        and t is not None
        and t >= min_t
        and absolute is not None
        and absolute > 0
    )
    if stage == EXPLORATION:
        return EXPLORATION_PASSED if passed else EXPLORATION_FAILED
    if passed:
        return PASSED
    if mean is not None and mean < 0:
        return REVERSED
    return VALIDATION_FAILED


# --- the event-day engine (X7) -----------------------------------------------


def simulate_events(
    picks: dict[int, list[int]],
    dues: dict[int, int],
    quote: Callable[[int, int], pr.Quote | None],
    first: int,
    last: int,
    top: int | None,
) -> pr.Simulation:
    """One account: buy ``picks[s]`` at the open of ``s`` with the cash there
    (each 1/``top`` of it, ``None`` equal shares of all), sell at the close of
    ``dues[s]`` (the next event day); limits, delays and costs as ``simulate``.
    A delayed sale goes first at its open, so its cash is in that session's
    buys when the session is T′+1, later it waits for the next event day.
    Equity starts at 1."""

    cash = [1.0]
    held: list[pr.Position] = []
    result = pr.Simulation([], [], [])
    for s in range(first, last + 1):
        for position in held:
            if position.due < s and position.sold is None:
                q = quote(position.instrument_id, s)
                if q is not None and q.tradable and not q.locked_down:
                    pr._sell(position, s, q.open, "delayed", cash)
        names = picks.get(s, [])
        if top is not None:
            names = names[:top]
        bought = 0.0
        if names:
            share = cash[0] / (top if top is not None else len(names))
            for instrument_id in names:
                q = quote(instrument_id, s)
                if q is None or not q.tradable:
                    result.counts["not_tradable"] += 1
                    continue
                if q.locked_up:
                    result.counts["limit_up"] += 1
                    continue
                position = pr.Position(
                    0,
                    instrument_id,
                    pr.buy_units(share, q.open),
                    s,
                    dues[s],
                    share,
                    q.open,
                )
                cash[0] -= share
                bought += share
                held.append(position)
                result.positions.append(position)
                result.counts["bought"] += 1
        value = 0.0
        for position in held:
            if position.sold is not None:
                continue
            q = quote(position.instrument_id, s)
            if q is not None and q.tradable:
                position.mark = q.close
            if position.due == s:
                if q is not None and q.tradable and not q.locked_down:
                    pr._sell(position, s, q.close, "close", cash)
                    continue
                result.counts["limit_down" if q and q.locked_down else "sale_held"] += 1
            value += position.units * position.mark
        held = [position for position in held if position.sold is None]
        equity = sum(cash) + value
        result.equity.append(equity)
        result.invested.append(value / equity if equity > 0 else 0.0)
        result.bought.append(bought)
    for position in held:
        position.how = "unsold"
        result.counts["unsold"] += 1
    return result


# --- reading ----------------------------------------------------------------


def load_context(db: Path, start: date, end: date, raw_dir: Path) -> Context:
    """The panel from ``start`` to ``end`` with turnovers and the MOPS list;
    nothing after ``end`` is read."""

    market = pr.load_market(db, start, raw_dir, fundamentals=True, end=end)
    ctx = Context(market)
    series = market.panel.series
    for instrument_id, item in series.items():
        ctx.turnover[instrument_id] = array("d", [lib.NAN]) * len(item.dates)
    report = lib.research_report()
    types = report.BENCHMARK_TYPES
    con = lib.connect_read_only(db)
    try:
        for instrument_id, day, turnover, status in con.execute(
            "select mb.instrument_id, mb.trading_date, mb.turnover, mb.turnover_status "
            "from market_bars mb join instruments i on i.id = mb.instrument_id "
            f"where i.instrument_type in ({','.join('?' * len(types))}) "
            "and mb.trading_date >= ? and mb.trading_date <= ?",
            (*types, start.isoformat(), end.isoformat()),
        ):
            item = series.get(instrument_id)
            at = None if item is None else item.position.get(date.fromisoformat(day))
            if at is None or status != TURNOVER_AVAILABLE or turnover is None:
                continue
            ctx.turnover[instrument_id][at] = float(turnover)
        sessions = market.panel.sessions
        for instrument_id, day, title in con.execute(
            "select instrument_id, event_date, title from events "
            "where source = ? and event_type = ? and instrument_id is not null "
            "and event_date >= ? and event_date <= ? "
            "order by event_date, instrument_id, id",
            (MOPS_SOURCE, MOPS_EVENT_TYPE, start.isoformat(), end.isoformat()),
        ):
            listed = date.fromisoformat(day)
            at = bisect_left(sessions, listed)  # not a session: the next one
            if at < len(sessions):
                ctx.announcements.append((at, instrument_id, title or "", listed))
    finally:
        con.close()
    return ctx


def delisted_count(db: Path, first: date, last: date) -> int:
    """Stock／ipo instruments marked ``delisted`` whose last bar is in the window
    (dates only, no price is read)."""

    types = lib.research_report().BENCHMARK_TYPES
    con = lib.connect_read_only(db)
    try:
        return con.execute(
            "select count(*) from (select i.id, max(mb.trading_date) as last_day "
            "from instruments i join market_bars mb on mb.instrument_id = i.id "
            f"where i.instrument_type in ({','.join('?' * len(types))}) "
            "and i.status = 'delisted' group by i.id) "
            "where last_day >= ? and last_day <= ?",
            (*types, first.isoformat(), last.isoformat()),
        ).fetchone()[0]
    finally:
        con.close()


# --- one hypothesis on one segment ------------------------------------------


def start_index(sessions: list[date], rule: tuple) -> int | None:
    """The first signal date's index: the anchor (or the session after it) is
    the first session (#703 decision 7)."""

    if rule[0] == "session":
        at = bisect_left(sessions, rule[1]) + rule[2] - 1
    else:
        at = bisect_left(sessions, rule[1])
    return at if at < len(sessions) else None


def event_days(sessions: list[date]) -> list[int]:
    """Index of the first session from the 10th of every month."""

    if not sessions:
        return []
    out: list[int] = []
    year, month = sessions[0].year, sessions[0].month
    while date(year, month, 1) <= sessions[-1]:
        at = bisect_left(sessions, date(year, month, EVENT_DAY))
        if at < len(sessions) and (not out or out[-1] != at):
            out.append(at)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def segment_window(
    sessions: list[date], segment: str, spec: dict[str, Any]
) -> tuple[int, int] | None:
    """(first, last) index of the sessions with an equity value, or None.

    The exploration's signal dates run from the hypothesis's start; a later
    segment's from the session before its first day (its first buy on that
    first day).  X7's equity starts the session after its first event day.
    """

    first_day, last_day = SEGMENTS[segment]
    last = bisect_left(sessions, last_day + timedelta(days=1)) - 1
    if first_day is None:
        base = start_index(sessions, spec["start"])
        if base is None:
            return None
    else:
        f0 = bisect_left(sessions, first_day)
        base = max(f0, 1) - 1
    if spec["rule"] == "monthly":
        events = [at for at in event_days(sessions) if at >= base]
        if not events:
            return None
        base = events[0]
    first = base + 1
    return (first, last) if first <= last else None


def _rank(
    ctx: Context, spec: dict[str, Any], day: date, members: list[tuple[lib.Series, int]]
) -> tuple[list[tuple[int, dict[str, float | None], str]], dict[str, int]]:
    """The day's members in the hypothesis's order (the filters and subset
    applied) and the count of missing values of each feature used.

    The feature cache holds this signal date only: a value is asked for once
    per member and day, and a run of 3,000 days × 1,500 members × 3 features
    kept whole would be millions of entries (#706 review)."""

    ctx.cache.clear()
    names = used_features(spec)
    missing = Counter()
    rows = []
    for item, at in members:
        values = {name: value_of(ctx, name, item, at) for name in names}
        for name, value in values.items():
            missing[name] += value is None
        rows.append((item.instrument_id, values, pr.tie_break(day, item.instrument_id)))
    if spec["subset"]:
        name, size = spec["subset"]
        kept = [row for row in rows if row[1][name] is not None]
        kept.sort(key=lambda row: (-row[1][name], row[2]))
        rows = kept[:size]
    rows = [
        row
        for row in rows
        if all(passes(row[1][name], op, value) for name, op, value in spec["filters"])
    ]
    rows.sort(key=lambda row: pr.ranking_key(row[1], tuple(spec["keys"]), row[2]))
    return rows, dict(missing)


@dataclass
class Plan:
    picks: dict[int, list[int]] = field(default_factory=dict)
    population: dict[int, list[int]] = field(default_factory=dict)
    dues: dict[int, int] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    signal_days: int = 0


def _coverage_add(
    coverage: dict[str, Any], day: date, members: int, missing: dict[str, int]
):
    year = coverage.setdefault(str(day.year), {"days": 0, "members": 0, "missing": {}})
    year["days"] += 1
    year["members"] += members
    for name, count in missing.items():
        year["missing"][name] = year["missing"].get(name, 0) + count


def _pick_row(ctx: Context, day: date, rank: int, instrument_id, values, tie):
    exchange, symbol, _ = ctx.market.panel.symbols.get(instrument_id, ("", "", ""))
    return {
        "signal_date": day.isoformat(),
        "rank": rank,
        "exchange": exchange,
        "symbol": symbol,
        **values,
        "tie": tie[:12],
    }


def plan(ctx: Context, spec: dict[str, Any], first: int, last: int) -> Plan:
    """The picks, the population and the coverage on the signal dates
    ``first − 1`` .. ``last − 1`` (only T's data and before is read)."""

    panel = ctx.market.panel
    sessions = panel.sessions
    out = Plan()
    top = spec["top"]
    if spec["rule"] == "buyback":
        return _plan_buyback(ctx, spec, first, last, out)
    if spec["rule"] == "monthly":
        events = [at for at in event_days(sessions) if first - 1 <= at <= last - 1]
        following = {
            at: nxt for at, nxt in zip(event_days(sessions), event_days(sessions)[1:])
        }
        days = events
    else:
        days = list(range(first - 1, last))
    for at in days:
        day = sessions[at]
        members = lib.universe(panel, day, MIN_LOTS)
        rows, missing = _rank(ctx, spec, day, members)
        _coverage_add(out.coverage, day, len(members), missing)
        out.signal_days += 1
        out.picks[at + 1] = [row[0] for row in rows]
        out.population[at + 1] = [item.instrument_id for item, _ in members]
        if spec["rule"] == "monthly":
            due = following.get(at)
            out.dues[at + 1] = due if due is not None and due <= last else last + 1
        for rank, (instrument_id, values, tie) in enumerate(rows[:top], 1):
            out.rows.append(_pick_row(ctx, day, rank, instrument_id, values, tie))
    return out


def _plan_buyback(
    ctx: Context, spec: dict[str, Any], first: int, last: int, out: Plan
) -> Plan:
    """X8: the matching announcements of T in T's population, the ones picked
    in the 20 sessions before T skipped, then at most 20 by the hash.  The
    record of picks runs from the hypothesis's start (or the first session
    read), not from the segment."""

    panel = ctx.market.panel
    sessions = panel.sessions
    begin = start_index(sessions, spec["start"]) or 0
    by_day: dict[int, list[tuple[int, str, date]]] = defaultdict(list)
    for at, instrument_id, title, listed in ctx.announcements:
        by_day[at].append((instrument_id, title, listed))
    picked_at: dict[int, int] = {}
    for at in range(first - 1, last):
        day = sessions[at]
        out.population[at + 1] = [
            item.instrument_id for item, _ in lib.universe(panel, day, MIN_LOTS)
        ]
        out.signal_days += 1
    for at in sorted(by_day):
        if at < begin or at > last - 1:
            continue
        day = sessions[at]
        members = {item.instrument_id for item, _ in lib.universe(panel, day, MIN_LOTS)}
        matched, rolled, inside = 0, 0, set()
        for instrument_id, title, listed in by_day[at]:
            if not is_buyback(title):
                continue
            matched += 1
            rolled += listed != day
            if instrument_id in members:
                inside.add(instrument_id)
        fresh = [
            instrument_id
            for instrument_id in inside
            if at - picked_at.get(instrument_id, -(10**9)) > BUYBACK_LOOKBACK
        ]
        chosen = sorted(fresh, key=lambda i: pr.tie_break(day, i))[: spec["top"]]
        for instrument_id in chosen:
            picked_at[instrument_id] = at
        if at >= first - 1:
            year = out.coverage.setdefault(
                str(day.year),
                {"announcements": 0, "rolled": 0, "in_population": 0, "picked": 0},
            )
            year["announcements"] += matched
            year["rolled"] += rolled
            year["in_population"] += len(inside)
            year["picked"] += len(chosen)
            if chosen:
                out.picks[at + 1] = chosen
            for rank, instrument_id in enumerate(chosen, 1):
                out.rows.append(
                    _pick_row(
                        ctx,
                        day,
                        rank,
                        instrument_id,
                        {},
                        pr.tie_break(day, instrument_id),
                    )
                )
    return out


def _taiex(panel: lib.Panel, first: int, last: int) -> list[float | None]:
    out = []
    for s in range(first, last + 1):
        now = panel.index_close.get(panel.sessions[s])
        before = panel.index_close.get(panel.sessions[s - 1])
        out.append(now / before - 1.0 if now and before and before > 0 else None)
    return out


def _turnover(simulation: pr.Simulation) -> list[float]:
    previous = [1.0] + simulation.equity[:-1]
    return [b / p if p > 0 else 0.0 for b, p in zip(simulation.bought, previous)]


def win_rate(simulation: pr.Simulation) -> dict[str, Any]:
    """Share of the buys worth more than their cost: sold at the proceeds, the
    unsold at their last close without the sale's costs (#703 decision 19)."""

    won = unsold = 0
    for position in simulation.positions:
        value = position.proceeds
        if value is None:
            unsold += 1
            value = position.units * position.mark
        won += value / position.cost - 1.0 > 0
    bought = len(simulation.positions)
    return {
        "bought": bought,
        "won": won,
        "rate": won / bought if bought else None,
        "unsold": unsold,
    }


def run_one(
    ctx: Context,
    db: Path,
    name: str,
    segment: str,
    coverage_only: bool = False,
    min_t: float = MIN_T,
) -> dict[str, Any]:
    """One hypothesis on one segment: its numbers, verdict and private parts."""

    spec = HYPOTHESES[name]
    panel = ctx.market.panel
    sessions = panel.sessions
    result: dict[str, Any] = {
        "hypothesis": name,
        "segment": segment,
        "verdict": None if segment == USED else UNDECIDED,
        "reason": None,
        "window": None,
        "prerequisites": None,
    }
    window = segment_window(sessions, segment, spec)
    if window is None:
        result["reason"] = "no_sessions"
        result["window"] = {"days": 0}
        return result
    first, last = window
    days = last - first + 1
    result["window"] = {
        "first_signal": sessions[first - 1].isoformat(),
        "first_session": sessions[first].isoformat(),
        "last_session": sessions[last].isoformat(),
        "days": days,
    }
    if segment != USED and not coverage_only:
        need = MIN_SEGMENT_DAYS[segment]
        delisted = delisted_count(db, sessions[first], sessions[last])
        result["prerequisites"] = {
            "days": days,
            "min_days": need,
            "delisted": delisted,
            "ok": days >= need and delisted > 0,
        }
        if not result["prerequisites"]["ok"]:
            result["reason"] = "segment_too_short" if days < need else "no_delisted"
            return result  # not run (docs 段長下限、先決條件)
    planned = plan(ctx, spec, first, last)
    result["window"]["signal_days"] = planned.signal_days
    result["coverage"] = planned.coverage
    if coverage_only:
        return result
    quote = ctx.quote
    if spec["rule"] == "monthly":
        mine = simulate_events(
            planned.picks, planned.dues, quote, first, last, spec["top"]
        )
        population = simulate_events(
            planned.population, planned.dues, quote, first, last, None
        )
    else:
        mine = pr.simulate(planned.picks, quote, first, last, spec["hold"], spec["top"])
        population = pr.simulate(
            planned.population, quote, first, last, spec["hold"], None
        )
    returns = pr.daily_returns(mine.equity)
    others = pr.daily_returns(population.equity)
    taiex = _taiex(panel, first, last)
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
        name: pr.curve_metrics(returns, mine.invested, _turnover(mine)),
        POPULATION: pr.curve_metrics(
            others, population.invested, _turnover(population)
        ),
        TAIEX: pr.curve_metrics([v for v in taiex if v is not None], [1.0], [0.0]),
    }
    result["win"] = win_rate(mine)
    result["counts"] = {name: dict(mine.counts), POPULATION: dict(population.counts)}
    if segment != USED:
        result["min_t"] = min_t
        result["verdict"] = explore_judge(
            segment, days, True, excess[POPULATION], absolute, min_t
        )
    result["_dates"] = sessions[first : last + 1]
    result["_equity"] = (mine.equity, population.equity)
    result["_positions"] = mine.positions
    result["_rows"] = planned.rows
    return result


# --- definitions, the gate and the ledger -----------------------------------


def definitions_sha256() -> str:
    """Hash of every fixed number the verdicts depend on: the definitions, the
    segments, the thresholds and the costs.  A changed tool needs a new
    exploration report before a validation."""

    payload = {
        "version": VERSION,
        "hypotheses": HYPOTHESES,
        "segments": SEGMENTS,
        "min_segment_days": MIN_SEGMENT_DAYS,
        "min_t": MIN_T,
        "bonferroni": [BONFERRONI_AFTER, ONE_SIDED],
        "round": [ROUND, ROUND_SIZE, CUMULATIVE],
        "costs": [pr.SLIPPAGE, pr.FEE, pr.TAX],
        "min_lots": MIN_LOTS,
        "turnover": [TURNOVER_WINDOW, TURNOVER_AVAILABLE],
        "events": [EVENT_DAY, MOPS_SOURCE, MOPS_EVENT_TYPE],
        "buyback": [BUYBACK_ALL, BUYBACK_ANY, BUYBACK_NONE, BUYBACK_LOOKBACK],
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("entries", [])


def write_ledger(path: Path, entries: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps({"entries": entries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def ledger_path(db: Path) -> Path:
    return db.resolve().parent / LEDGER_NAME


def validation_problems(
    db: Path, report: str | None, sha256: str | None, url: str | None
) -> tuple[list[str], list[str], dict[str, Any] | None]:
    """(refusals, hypotheses to validate, the report) before anything is read."""

    problems: list[str] = []
    if not report or not sha256 or not url:
        return (
            [
                "--segment validation needs --exploration-report, "
                "--exploration-sha256 and --exploration-url"
            ],
            [],
            None,
        )
    marker = db.resolve().parent / MARKER_NAME
    try:
        purpose = json.loads(marker.read_text(encoding="utf-8")).get("purpose")
    except (OSError, ValueError, AttributeError):
        purpose = None
    if purpose != MARKER_PURPOSE:
        # Only the research DB runs the validation, and its ledger stays in
        # the research volume: a copy elsewhere would lose it (#706 review).
        return (
            [
                f"{marker} is missing or not a research marker "
                f'(expected {{"purpose": "{MARKER_PURPOSE}"}}): the validation '
                "runs on the research DB only"
            ],
            [],
            None,
        )
    path = Path(report)
    if not path.is_file():
        return [f"{path} does not exist"], [], None
    if file_sha256(path) != sha256.strip().lower():
        problems.append(
            "the exploration report's sha256 is not the published one "
            "(--exploration-sha256)"
        )
    if not any(pattern.match(url) for pattern in URL_PATTERNS):
        problems.append(
            "--exploration-url is not an Issue comment or a pr-assets link of the repository"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return problems + [f"{path} is not JSON"], [], None
    if data.get("segment") != EXPLORATION or data.get("design") != DESIGN:
        problems.append("the report is not an exploration report of this tool")
    if data.get("definitions_sha256") != definitions_sha256():
        problems.append(
            "the report's definitions_sha256 is not this tool's: run the exploration again"
        )
    passed = [
        name
        for name in HYPOTHESES
        if data.get("hypotheses", {}).get(name, {}).get("verdict") == EXPLORATION_PASSED
    ]
    if not passed:
        problems.append("no hypothesis passed the exploration: nothing to validate")
    for where in (ledger_path(db), REPO_LEDGER):
        done = {entry.get("hypothesis") for entry in read_ledger(where)}
        again = [name for name in passed if name in done]
        if again:
            problems.append(
                f"{', '.join(again)} already in {where}: the validation runs once"
            )
    return problems, passed, data


def tool_commit() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except Exception:  # noqa: BLE001 - a container without git or .git
        return "unknown"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- output -----------------------------------------------------------------


SEGMENT_NAMES = {EXPLORATION: "探索段", VALIDATION: "驗證段", USED: "已用段"}
REASONS = {
    "no_sessions": "段內沒有可用的交易日",
    "segment_too_short": "段長不足",
    "no_delisted": "研究 DB 在段內沒有已下市公司",
}
FEATURE_LABELS = {
    "momentum_120": "120 日報酬",
    "high_gap_240": "距 240 日最高價",
    "revenue_yoy": "月營收年增率",
    "institutional_flow_20": "三大法人 20 日淨買超 ÷ 均量",
    "eps_growth_yield": "單季 EPS 年增額 ÷ 股價",
    "revenue_high_12": "月營收創 12 個月新高",
    "eps_yield_raw": "EPS 年化 ÷ 未還原收盤",
    "turnover_60": "60 日平均成交金額",
    "revenue_previous_month": "最新已知月份是上個月",
}
VOLATILE_KEYS = ("command", "tool_commit", "elapsed_seconds", "peak_memory_gb")


def _pct(value: float | None, digits: int = 2) -> str:
    return lib.pct(value, digits)


def _t(value: float | None) -> str:
    return lib.num(value, 2)


def public(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if not key.startswith("_")}


def coverage_lines(name: str, coverage: dict[str, Any]) -> list[str]:
    spec = HYPOTHESES[name]
    if spec["rule"] == "buyback":
        lines = [
            "| 年 | 符合主旨的公告 | 日期順延 | 在母體 | 選入 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for year, row in sorted(coverage.items()):
            lines.append(
                f"| {year} | {row['announcements']:,} | {row['rolled']:,} "
                f"| {row['in_population']:,} | {row['picked']:,} |"
            )
        return lines
    names = used_features(spec)
    lines = [
        "| 年 | 日數 | 母體檔次 | "
        + " | ".join(f"{FEATURE_LABELS[n]} 缺值" for n in names)
        + " |",
        "| --- | ---: | ---: | " + " | ".join("---:" for _ in names) + " |",
    ]
    for year, row in sorted(coverage.items()):
        members = row["members"]
        cells = [
            _pct(row["missing"].get(n, 0) / members, 1) if members else "—"
            for n in names
        ]
        lines.append(
            f"| {year} | {row['days']:,} | {members:,} | " + " | ".join(cells) + " |"
        )
    return lines


def hypothesis_markdown(result: dict[str, Any], header: dict[str, Any]) -> str:
    name = result["hypothesis"]
    spec = HYPOTHESES[name]
    segment = SEGMENT_NAMES[result["segment"]]
    window = result["window"] or {}
    verdict = result["verdict"] or "只列出、不判定"
    lines = [
        f"# {name} {segment}（explore_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 判定：**{verdict}**"
        + (f"（{REASONS[result['reason']]}，不跑）" if result["reason"] else ""),
        f"- 假設：{spec['direction']}；{spec['label']}；N＝{spec['top']}、K＝"
        + ("到下一個事件日" if spec["hold"] == "next_event" else str(spec["hold"])),
        f"- 登記 commit `{REGISTRATION_COMMIT}`；定義雜湊 `{header['definitions_sha256'][:16]}…`",
        f"- 期間：訊號日 {window.get('first_signal', '—')} 起，有淨值的交易日 "
        f"{window.get('first_session', '—')}～{window.get('last_session', '—')}，共 "
        f"{window.get('days', 0)} 日",
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
    if "excess" in result:
        e, a = result["excess"], result["absolute"]
        lines += [
            "## 判定用的數字",
            "",
            "| 量 | 日數 | 日均 | 年化 | t |",
            "| --- | ---: | ---: | ---: | ---: |",
            f"| 超額（對母體，判定） | {e[POPULATION]['days']} | {_pct(e[POPULATION]['mean'], 3)} "
            f"| {_pct(e[POPULATION]['annual'])} | {_t(e[POPULATION]['t'])} |",
            f"| 絕對報酬（扣成本，判定） | {a['days']} | {_pct(a['mean'], 3)} "
            f"| {_pct(None if a['mean'] is None else a['mean'] * pr.TRADING_DAYS)} | — |",
            f"| 超額（對加權指數，只列出） | {e[TAIEX]['days']} | {_pct(e[TAIEX]['mean'], 3)} "
            f"| {_pct(e[TAIEX]['annual'])} | {_t(e[TAIEX]['t'])} |",
            "",
            f"門檻：t ≥ {result.get('min_t', MIN_T):.2f}。",
            "",
            "## 只列出",
            "",
            "| 組合 | 日數 | 年化報酬 | 年化波動 | 最大回撤 | 平均投入 | 年化換手 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        labels = {name: name, POPULATION: "母體（基準）", TAIEX: "加權指數（價格指數）"}
        for key in (name, POPULATION, TAIEX):
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
            *coverage_lines(name, result["coverage"]),
            "",
        ]
    return "\n".join(lines)


def write_hypothesis(out: Path, result: dict[str, Any], header: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    name = result["hypothesis"]
    spec = HYPOTHESES[name]
    body = {
        **{key: header[key] for key in ("version", "design", "definitions_sha256")},
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
        hypothesis_markdown(result, header), encoding="utf-8"
    )
    if "_dates" not in result:
        return
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
    fields = ["signal_date", "rank", "exchange", "symbol", *used_features(spec), "tie"]
    with (out / "picks.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(result["_rows"])
    sessions = panel.sessions
    with (out / "trades.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "account",
                "exchange",
                "symbol",
                "bought",
                "due",
                "sold",
                "how",
                "cost",
                "proceeds",
            ]
        )
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


def overview_markdown(report: dict[str, Any], sha256: str) -> str:
    segment = report["segment"]
    stage = SEGMENT_NAMES[segment]
    lines = [
        f"explore.json 的 sha256：`{sha256}`",
        "",
        f"# 新策略探索 第 {report['round']} 輪 {stage}（explore_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「新策略探索」）；"
        f"工具設計 {DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        f"- 門檻：超額日均 > 0 且 t ≥ {report['min_t']:.2f}，且絕對報酬日均 > 0；"
        f"段長下限 {MIN_SEGMENT_DAYS.get(segment, '—')} 日；研究 DB 要有段內已下市公司",
        f"- 副本：最新交易日 {report['copy']['latest']}，alembic `{report['copy']['alembic']}`",
        f"- 讀取的資料到 {report['read_until']}（之後的列不讀）",
        f"- 耗時 {report.get('elapsed_seconds', 0):.0f} 秒，峰值記憶體 "
        f"{lib.num(report.get('peak_memory_gb'), 2)} GB",
        f"- 重現：`{report['command']}`",
    ]
    if segment == VALIDATION:
        source = report["exploration"]
        lines.append(f"- 探索段報告：{source['url']}（sha256 `{source['sha256']}`）")
    lines += [
        "",
        "## 判定",
        "",
        "| 代號 | 方向 | N／K | 日數 | 超額日均 | t | 絕對報酬日均 | 判定 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for name, row in report["hypotheses"].items():
        spec = HYPOTHESES[name]
        hold = "事件" if spec["hold"] == "next_event" else spec["hold"]
        e = row.get("excess") or {}
        verdict = row["verdict"] + (
            f"（{REASONS[row['reason']]}）" if row.get("reason") else ""
        )
        lines.append(
            f"| {name} | {spec['direction']} | {spec['top']}／{hold} | {row['days']} "
            f"| {_pct(e.get('mean'), 3)} | {_t(e.get('t'))} "
            f"| {_pct(row.get('absolute_mean'), 3)} | {verdict} |"
        )
    if report.get("used"):
        lines += [
            "",
            "## 已用段（驗證通過的假設，只列出、不判定）",
            "",
            "| 代號 | 日數 | 超額日均 | t | 絕對報酬日均 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for name, row in report["used"].items():
            e = row.get("excess") or {}
            lines.append(
                f"| {name} | {row['days']} | {_pct(e.get('mean'), 3)} | {_t(e.get('t'))} "
                f"| {_pct(row.get('absolute_mean'), 3)} |"
            )
    lines += [
        "",
        "各假設的數字、只列出的指標與資料覆蓋見 `<代號>/summary.md`。",
        "",
    ]
    return "\n".join(lines)


def _row(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "verdict": result["verdict"],
        "reason": result["reason"],
        "days": (result["window"] or {}).get("days", 0),
        "excess": (result.get("excess") or {}).get(POPULATION),
        "absolute_mean": (result.get("absolute") or {}).get("mean"),
        "prerequisites": result.get("prerequisites"),
    }


# --- the runs ---------------------------------------------------------------


def _header(db: Path, segment: str, command: str, read_until: date) -> dict[str, Any]:
    return {
        "version": VERSION,
        "design": DESIGN,
        "registration_commit": REGISTRATION_COMMIT,
        "segment": segment,
        "round": ROUND,
        "round_size": ROUND_SIZE,
        "cumulative": CUMULATIVE,
        "definitions_sha256": definitions_sha256(),
        "tool_commit": tool_commit(),
        "command": command,
        "copy": pr.copy_facts(db),
        "read_until": read_until.isoformat(),
    }


def _finish(out: Path, report: dict[str, Any], started: float) -> str:
    report["elapsed_seconds"] = time.monotonic() - started
    report["peak_memory_gb"] = lib._load("backtest_research").peak_memory_gb()
    path = out / "explore.json"
    path.write_text(
        json.dumps(public(report), ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    sha256 = file_sha256(path)
    (out / "explore.md").write_text(overview_markdown(report, sha256), encoding="utf-8")
    return sha256


def run_exploration(
    db: Path,
    out: Path,
    command: str = "",
    coverage_only: bool = False,
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, Any]:
    """Every hypothesis on the exploration segment; nothing after its end read."""

    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    end = SEGMENTS[EXPLORATION][1]
    ctx = load_context(db, LOAD_FROM, end, out / RAW_DIR_NAME)
    header = _header(db, EXPLORATION, command, end)
    header["_panel"] = ctx.market.panel
    report = {**header, "min_t": MIN_T, "hypotheses": {}}
    if coverage_only:
        coverage = {}
        for name in HYPOTHESES:
            result = run_one(ctx, db, name, EXPLORATION, coverage_only=True)
            coverage[name] = {
                "window": result["window"],
                "coverage": result.get("coverage", {}),
            }
            progress(f"{name} coverage")
        body = {**public(header), "coverage_only": True, "hypotheses": coverage}
        (out / "coverage.json").write_text(
            json.dumps(body, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        (out / "coverage.md").write_text(coverage_markdown(body), encoding="utf-8")
        return {"out": str(out.resolve()), "coverage_only": True}
    for name in HYPOTHESES:
        t0 = time.monotonic()
        result = run_one(ctx, db, name, EXPLORATION)
        write_hypothesis(out / name, result, header)
        report["hypotheses"][name] = {
            **_row(result),
            "coverage": result.get("coverage"),
        }
        progress(f"{name}: {result['verdict']} ({time.monotonic() - t0:.1f}s)")
    sha256 = _finish(out, report, started)
    return {
        "out": str(out.resolve()),
        "segment": EXPLORATION,
        "sha256": sha256,
        "verdicts": {
            name: row["verdict"] for name, row in report["hypotheses"].items()
        },
    }


def coverage_markdown(body: dict[str, Any]) -> str:
    lines = [
        f"# 新策略探索 第 {body['round']} 輪 資料覆蓋（探索段，不含報酬）",
        "",
        f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}",
        f"- 重現：`{body['command']}`",
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
    return "\n".join(lines)


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
    commit = tool_commit()
    ledger = ledger_path(db)
    entries = read_ledger(ledger)
    for name in names:
        entries.append(
            {
                "hypothesis": name,
                "round": ROUND,
                "status": "started",
                "started_at": _now(),
                "report_sha256": source["sha256"],
                "url": source["url"],
                "tool_commit": commit,
                "definitions_sha256": definitions_sha256(),
            }
        )
    write_ledger(ledger, entries)  # before any validation data is read
    first_day, end = SEGMENTS[VALIDATION]
    ctx = load_context(
        db,
        first_day - timedelta(days=WARMUP_CALENDAR_DAYS),
        end,
        out / RAW_DIR_NAME,
    )
    header = _header(db, VALIDATION, command, end)
    header["_panel"] = ctx.market.panel
    min_t = validation_min_t(CUMULATIVE)
    report = {**header, "min_t": min_t, "exploration": source, "hypotheses": {}}
    for name in names:
        result = run_one(ctx, db, name, VALIDATION, min_t=min_t)
        write_hypothesis(out / name, result, header)
        report["hypotheses"][name] = _row(result)
        progress(f"{name}: {result['verdict']}")
    for entry in entries:
        if entry["status"] == "started" and entry["hypothesis"] in report["hypotheses"]:
            entry["status"] = "finished"
            entry["finished_at"] = _now()
            entry["verdict"] = report["hypotheses"][entry["hypothesis"]]["verdict"]
    write_ledger(ledger, entries)
    passed = [name for name in names if report["hypotheses"][name]["verdict"] == PASSED]
    if passed:  # the used segment only for the passed ones (decision 9)
        first_used, end_used = SEGMENTS[USED]
        used_ctx = load_context(
            db,
            first_used - timedelta(days=WARMUP_CALENDAR_DAYS),
            end_used,
            out / RAW_DIR_NAME,
        )
        used_header = {**header, "_panel": used_ctx.market.panel}
        report["used"] = {}
        for name in passed:
            result = run_one(used_ctx, db, name, USED)
            write_hypothesis(out / name / USED, result, used_header)
            report["used"][name] = _row(result)
    sha256 = _finish(out, report, started)
    mine = [entry for entry in entries if entry["hypothesis"] in names]
    write_ledger(out / "ledger-entries.json", mine)
    return {
        "out": str(out.resolve()),
        "segment": VALIDATION,
        "sha256": sha256,
        "verdicts": {
            name: row["verdict"] for name, row in report["hypotheses"].items()
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="explore_research.py", description=__doc__)
    parser.add_argument("--db", required=True, help="a copy of the research DB")
    parser.add_argument("--out", required=True)
    parser.add_argument("--segment", required=True, choices=STAGES)
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help="exploration only: the share of missing feature values per year, no return",
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
    db = Path(args.db)
    problems = lib._load("exit_research").refusals(db, args.min_free_gb)
    if problems:
        print(json.dumps({"refused": problems}, ensure_ascii=False))
        return 2
    command = "python tools/research/explore_research.py " + " ".join(argv)
    progress = lambda text: print(text, file=sys.stderr, flush=True)  # noqa: E731
    if args.segment == EXPLORATION:
        line = run_exploration(
            db, Path(args.out), command, args.coverage_only, progress=progress
        )
    else:
        problems, names, _report = validation_problems(db, *gate)
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
