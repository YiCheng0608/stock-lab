"""Round 2 of the new-strategy exploration: S1～S3, R1～R2 trade by trade (#726).

docs/spec/evidence.md 逐筆評估 and 第二輪：S1～S3、R1～R2: the hypotheses were
registered (commit ``64a5efe1``, #725, decision 6882161634) before anyone ran a
tool on the backfilled history; the design of this tool is the #726 decision
(comment 6882515208, 第二輪實作釋義).  Nothing here is a command-line option: a
change of a definition is a new code, and the golden tests lock the engine.

Every signal is one trade of its own (no account, no cap on the positions):

- the signals: S1～S3 rank the day's population (``evidence_lib.universe``
  less the stocks occupied by an open signal of the same hypothesis) and take
  the top 10; S1 and S3 make none on a day TAIEX closes at or below its MA60.
  R1／R2 are ``breakout_v3``／``pullback_v4`` without the group condition
  (``app.strategies.ablation``), recomputed on the research panel with the
  product's own evaluators (``rule_signal``): every actionable one in the
  population is a signal.
- the entry: S1～S3 a limit buy at T's close within 3 sessions
  (``enter_zone``); R1／R2 ``exit_research.enter`` (tracking_v2, 20 sessions).
  Not filled in time is abandoned: not a trade, only its share is listed.
- the exit (``settle``): the stop, the target, the holding limit; a session
  touching both is the stop; a gap fills at the open; a session locked at
  limit down delays the sale; a suspended session is not checked and delays a
  due sale; a delisted or transferred stock sells at its last close; the segment's last
  session settles what is still open.  Without suspensions, delistings and
  the segment's end it is ``exit_research.exit_trade`` (a test locks that).
- every session is a market session (``Panel.sessions``): a stock without a
  bar or suspended on a session simply cannot trade on it.

Each trade's return is net of the round trip (``exit_research._closed``); its
excess is over the same-period equal-weight population of the signal date
(bought at the fill's open, sold at the exit's close, the same costs).  The
trades of one signal date are averaged into one day; the excess mean and its
t (``evidence_lib.t_stat``, ``overlap=20``) and the mean net return are judged
by ``explore_research.explore_judge``.  The gate (the exploration once per
version, the validation once after a published exploration report) and the
ledgers (``explore-ledger.json`` beside the DB and the repository's
``tools/research/explore_ledger.json``) are ``explore_research``'s.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import statistics
import sys
import time
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

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

VERSION = 1
DESIGN = "726"
TOOL = "trade_research"
REGISTRATION_COMMIT = "64a5efe1"
DECISION = "https://github.com/YiCheng0608/stock-lab/issues/726#issuecomment-6882515208"
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
SEGMENTS = dict(ex.SEGMENTS)
MIN_SEGMENT_DAYS = dict(ex.MIN_SEGMENT_DAYS)
MIN_T = ex.MIN_T
MIN_DAYS = er.MIN_DAYS  # signal dates with a fill, per segment (#673's floor)
OVERLAP = er.OVERLAP
SLIPPAGE = er.SLIPPAGE
COST_BPS = er.COST_BPS
MIN_LOTS = lib.DEFAULT_MIN_LOTS
ROUND = 2
ROUND_SIZE = 5
CUMULATIVE = 13  # X1～X8 and S1～S3, R1～R2; H1 and #619～#689 apart
WARMUP_CALENDAR_DAYS = ex.WARMUP_CALENDAR_DAYS
ATR_WINDOW = 14
MA_WINDOW = 60  # the market filter: TAIEX's close over the mean of 60 closes
EPS = er.EPS
# Q1 (decision 6882515208): without the group condition a missing group score
# is not missing data; the evaluators still list the input as required, so a
# finite value stands in for it (the removed comparison never reads it).
GROUP_PLACEHOLDER = 0.0
RAW_DIR_NAME = ex.RAW_DIR_NAME
LEDGER_NAME = ex.LEDGER_NAME

UNDECIDED = ex.UNDECIDED
EXPLORATION_PASSED = ex.EXPLORATION_PASSED
PASSED = ex.PASSED

# The registration (docs 第二輪：S1～S3、R1～R2), word for word.  ``start`` is
# explore_research's ("session", anchor, n): the n-th market session counting
# the anchor (or the first session after it) as the first.
START = ("session", date(2014, 12, 1), 20)
HYPOTHESES: dict[str, dict[str, Any]] = {
    "S1": {
        "kind": "zone",
        "label": "大盤站上 MA60；revenue_yoy > 0、ATR14 > 0；投信 5 日買超天數、"
        "三大法人 20 日淨買超大者先，前 10 名；[收盤 − 1×ATR14, 收盤] 掛限價 3 日；"
        "停損 −2×ATR14、目標 +4×ATR14、持有 20 日",
        "market_filter": True,
        "top": 10,
        "entry_days": 3,
        "zone_atr": 1.0,
        "stop_atr": 2.0,
        "target_atr": 4.0,
        "hold": 20,
        "start": START,
    },
    "S2": {
        "kind": "zone",
        "label": "S1 拿掉大盤濾網",
        "market_filter": False,
        "top": 10,
        "entry_days": 3,
        "zone_atr": 1.0,
        "stop_atr": 2.0,
        "target_atr": 4.0,
        "hold": 20,
        "start": START,
    },
    "S3": {
        "kind": "zone",
        "label": "S1 的停損改成 −1×ATR14（R 仍是 2×ATR14，目標仍是 +4×ATR14）",
        "market_filter": True,
        "top": 10,
        "entry_days": 3,
        "zone_atr": 1.0,
        "stop_atr": 1.0,
        "target_atr": 4.0,
        "hold": 20,
        "start": START,
    },
    "R1": {
        "kind": "rule",
        "label": "breakout_v3_ablate_group（拿掉族群條件），E0 進出場",
        "strategy": ("breakout_v3", "group"),
        "entry_days": er.WINDOW,
        "hold": er.WINDOW,  # the 20th session after the signal date
        "start": START,
    },
    "R2": {
        "kind": "rule",
        "label": "pullback_v4_ablate_group（拿掉族群條件），E0 進出場",
        "strategy": ("pullback_v4", "group"),
        "entry_days": er.WINDOW,
        "hold": er.WINDOW,
        "start": START,
    },
}
SCORE_KEYS = ("trust_buy_days", "institutional_flow_20")
# feature_evidence's functions: trust_buy_days_5 is ``trust_buy_days``.
SCORE_FUNCTIONS = {
    "trust_buy_days": features.trust_buy_days,
    "institutional_flow_20": ex.FEATURE_FUNCTIONS["institutional_flow_20"],
}
REASONS = {
    **ex.REASONS,
    "too_few_trade_days": f"有成交的訊號日不足 {MIN_DAYS} 日",
}
# "transferred": the PR #738 review decision 6883149381 (轉板比照下市)
EXIT_REASONS = ("stop", "target", "time", "segment_end", "delisted", "transferred")
# A stock no longer traded on its exchange: no bar after its last one.
ENDED = ("delisted", "transferred")
EXIT_LABELS = {
    "stop": "碰停損",
    "target": "碰目標",
    "time": "持有到期",
    "segment_end": "段末結算",
    "delisted": "下市",
    "transferred": "轉板",
}
ABANDON_LABELS = {
    "not_triggered": "期限內沒有成交",
    "gap_above_target": "開盤或成交價已在目標一以上",
    "gap_below_invalid": "開盤或成交價已在失效價以下",
}


# --- the strategies of R1／R2 ---------------------------------------------------


def strategy_of(name: str):
    from app.strategies.ablation import ablated_strategy

    return ablated_strategy(*HYPOTHESES[name]["strategy"])


def definitions_sha256() -> str:
    """Hash of every fixed number the verdicts depend on: the definitions (the
    R1／R2 configurations included), the segments, the thresholds and the
    costs.  A changed tool needs a new exploration report before a validation."""

    configs = {
        name: strategy_of(name).config
        for name, spec in HYPOTHESES.items()
        if spec["kind"] == "rule"
    }
    payload = {
        "version": VERSION,
        "design": DESIGN,
        "hypotheses": HYPOTHESES,
        "configs": configs,
        "segments": SEGMENTS,
        "min_segment_days": MIN_SEGMENT_DAYS,
        "min_days": MIN_DAYS,
        "min_t": MIN_T,
        "bonferroni": [ex.BONFERRONI_AFTER, ex.ONE_SIDED],
        "round": [ROUND, ROUND_SIZE, CUMULATIVE],
        "costs": [SLIPPAGE, COST_BPS],
        "overlap": OVERLAP,
        "min_lots": MIN_LOTS,
        "atr": ATR_WINDOW,
        "market_filter": MA_WINDOW,
        "group_placeholder": GROUP_PLACEHOLDER,
        "warmup": WARMUP_CALENDAR_DAYS,
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- reading ------------------------------------------------------------------


@dataclass
class Context:
    """The research panel plus what the trades and R1／R2 read beyond it."""

    market: pr.Market
    db: Path
    end: date
    bars_before: dict[int, int] = field(default_factory=dict)  # Q2: bar_count
    statuses: dict[int, str] = field(default_factory=dict)
    last_bar: dict[int, date] = field(default_factory=dict)  # of ENDED ones
    margin_lists: dict[tuple[str, date], int] = field(default_factory=dict)
    margin_codes: dict[int, frozenset[str]] = field(default_factory=dict)
    index_days: list[date] = field(default_factory=list)
    universes: dict[int, list[tuple[lib.Series, int]]] = field(default_factory=dict)
    baselines: dict[tuple[int, int, int], dict[str, Any]] = field(default_factory=dict)

    @property
    def panel(self) -> lib.Panel:
        return self.market.panel

    # StrategyInputs of the signal date being run, shared by R1 and R2
    inputs: dict[tuple[int, int], Any] = field(default_factory=dict)

    def universe(self, s: int) -> list[tuple[lib.Series, int]]:
        if s not in self.universes:
            self.universes.clear()  # one signal date at a time
            self.inputs.clear()
            self.universes[s] = lib.universe(
                self.panel, self.panel.sessions[s], MIN_LOTS
            )
        return self.universes[s]

    def codes(self, exchange: str, day: date) -> frozenset[str] | None:
        """The stored margin-trading list of ``exchange`` on ``day``; None without one."""

        list_id = self.margin_lists.get((exchange, day))
        if list_id is None:
            return None
        if list_id not in self.margin_codes:
            con = lib.connect_read_only(self.db)
            try:
                text = con.execute(
                    "select members_json from margin_lists where id = ?", (list_id,)
                ).fetchone()[0]
            finally:
                con.close()
            members = json.loads(text) if text else {}
            self.margin_codes[list_id] = frozenset(members or {})
        return self.margin_codes[list_id]


def load(db: Path, start: date, end: date, raw_dir: Path) -> Context:
    """The panel from ``start`` to ``end``; nothing after ``end`` is read
    except the date of a delisted or transferred stock's last bar (no price)."""

    market = pr.load_market(db, start, raw_dir, fundamentals=True, end=end)
    ctx = Context(market, db, end)
    report = lib.research_report()
    types = report.BENCHMARK_TYPES
    marks = ",".join("?" * len(types))
    con = lib.connect_read_only(db)
    try:
        # The bars of research_report's exclusion list are not in the panel, so
        # they are not counted either (bar_count, the ENDED day; #839).
        ranges = report.excluded_ranges(con)
        excluded = report.excluded_bar_counts(con, ranges, start)
        ctx.bars_before = {
            instrument_id: count - excluded.get(instrument_id, 0)
            for instrument_id, count in con.execute(
                "select mb.instrument_id, count(*) from market_bars mb "
                "join instruments i on i.id = mb.instrument_id "
                f"where i.instrument_type in ({marks}) and mb.trading_date < ? "
                "group by mb.instrument_id",
                (*types, start.isoformat()),
            )
        }
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
        ctx.margin_lists = {
            (exchange, date.fromisoformat(day)): list_id
            for list_id, exchange, day in con.execute(
                "select id, exchange, trading_date from margin_lists "
                "where trading_date >= ? and trading_date <= ?",
                (start.isoformat(), end.isoformat()),
            )
        }
    finally:
        con.close()
    ctx.index_days = sorted(ctx.panel.index_close)
    return ctx


# --- R1／R2 on the panel (decision D4) ----------------------------------------


def _number(value: float) -> float | None:
    return value if value == value and value > 0 else None


def _on_basis(item: lib.Series, raw: float, k: int, at: int) -> float | None:
    """Bar ``k``'s raw ``raw`` on bar ``at``'s raw basis (``technical_features``)."""

    if not raw or raw != raw:
        return None
    if item.scale[k] == item.scale[at]:
        return raw
    return raw * item.scale[k] / item.scale[at]


def _unsuspended(ctx: Context, item: lib.Series, at: int, count: int) -> list[int]:
    """``worker.pipeline._effective_trading_dates``: the last ``count``
    positions to ``at`` whose bar is not ``is_suspended``."""

    flags = ctx.market.raw[item.instrument_id][3]
    out: list[int] = []
    k = at
    while k >= 0 and len(out) < count:
        if not flags[k]:
            out.append(k)
        k -= 1
    return out[::-1]


def _chip_row(item: lib.Series, k: int) -> bool:
    return any(item.chips[name][k] == item.chips[name][k] for name in lib.CHIP_FIELDS)


def _chip(item: lib.Series, name: str, k: int) -> float | None:
    value = item.chips[name][k]
    return None if value != value else value


def strategy_inputs(ctx: Context, item: lib.Series, at: int):
    """``worker.pipeline._signal_context``'s StrategyInputs from the panel."""

    from app import margin_lists, margin_zero_base
    from app.domain import moving_average
    from app.strategies.base import StrategyInputs

    iid = item.instrument_id
    raw_low, raw_high, raw_close, _flags = ctx.market.raw[iid]
    first = max(0, at + 1 - MA_WINDOW)
    closes = [_on_basis(item, raw_close[k], k, at) for k in range(first, at + 1)]
    highs = [_on_basis(item, raw_high[k], k, at) for k in range(first, at + 1)]
    lows = [_on_basis(item, raw_low[k], k, at) for k in range(first, at + 1)]
    ma20 = moving_average(closes, 20)
    ma60 = moving_average(closes, 60)
    pairs = [
        (high - low)
        for high, low in zip(highs[-ATR_WINDOW:], lows[-ATR_WINDOW:])
        if high is not None and low is not None
    ]
    atr = (
        round(sum(pairs) / len(pairs), 6)
        if pairs and len(pairs) == len(highs[-ATR_WINDOW:])
        else None
    )
    prior = range(max(0, at - 20), at)
    prior_highs = [
        None
        if (value := _on_basis(item, raw_high[k], k, at)) is None
        else round(value, 6)
        for k in prior
    ]
    prior_volumes = [int(item.volume[k]) for k in prior]
    # strategy-v1 flow: five sessions' net shares over the 20-session mean volume
    flow_ratio = None
    days = _unsuspended(ctx, item, at, 20)
    if len(days) == 20 and all(item.volume[k] > 0 for k in days):
        parts = [
            [
                _chip(item, name, k)
                for name in ("foreign_buy", "trust_buy", "dealer_buy")
            ]
            for k in days[-5:]
        ]
        if all(value is not None for row in parts for value in row):
            average = sum(item.volume[k] for k in days) / len(days)
            flow = sum(value for row in parts for value in row)
            flow_ratio = flow / average if average > 0 else None
    # the margin ratio of the six unsuspended sessions to T
    six = _unsuspended(ctx, item, at, margin_lists.WINDOW_SESSIONS)
    balances = None
    if len(six) == 6 and all(_chip_row(item, k) for k in six):
        balances = (
            _chip(item, "margin_balance", six[0]),
            _chip(item, "margin_balance", six[-1]),
        )
    ratio = None
    if (
        balances is not None
        and balances[0] not in (None, 0)
        and balances[1] is not None
    ):
        ratio = (balances[1] - balances[0]) / abs(balances[0])
    zero_base = (
        None
        if ratio is not None or balances is None
        else margin_zero_base.zero_base_state(*balances)
    )
    exchange, symbol, _name = ctx.panel.symbols.get(iid, ("", "", ""))
    if ratio is not None:
        financing = margin_lists.APPLICABLE
    elif not six or six[-1] != at:
        financing = margin_lists.MISSING
    else:
        financing = margin_lists.margin_financing_state(
            symbol, ratio, [ctx.codes(exchange, item.dates[k]) for k in six]
        )
    close = _number(raw_close[at])
    return StrategyInputs(
        bar_count=ctx.bars_before.get(iid, 0) + at + 1,
        close=close,
        volume=float(item.volume[at]),
        ma20=round(ma20, 6) if ma20 is not None else None,
        ma60=round(ma60, 6) if ma60 is not None else None,
        atr14=atr,
        prior_highs=prior_highs,
        prior_volumes=prior_volumes,
        group_excess_return_20d=GROUP_PLACEHOLDER,
        institutional_flow_ratio_5d=flow_ratio,
        margin_change_ratio_5d=ratio,
        margin_financing=financing,
        margin_zero_base=zero_base,
    )


@dataclass(frozen=True)
class RuleSignal:
    status: (
        str  # conditional (actionable), observation, data_incomplete, invalid_levels
    )
    levels: Any  # app.strategies.base.SignalLevels on T's raw basis
    reasons: tuple[str, ...]
    inputs: Any

    @property
    def actionable(self) -> bool:
        return self.status not in er.NOT_ACTIONABLE


def rule_signal(ctx: Context, strategy, item: lib.Series, at: int) -> RuleSignal:
    """``worker.pipeline._write_strategy_signal``'s status and levels, without
    the group score's missing reason (Q1)."""

    from app.domain import instrument_eligibility, validate_signal_levels
    from app.strategies.base import SignalLevels

    key = (item.instrument_id, at)
    if key not in ctx.inputs:
        ctx.inputs[key] = strategy_inputs(ctx, item, at)
    inputs = ctx.inputs[key]
    selected = strategy.evaluate(inputs)
    levels = (
        strategy.actionable_levels(inputs)
        if selected.passed and inputs.close is not None
        else SignalLevels()
    )
    validation = validate_signal_levels(
        entry_type=strategy.entry_type,
        reference_entry=levels.reference_entry,
        breakout_price=levels.breakout_price,
        invalid_price=levels.invalid_price,
        target_1=levels.target_1,
        target_2=levels.target_2,
    )
    eligible, reason = instrument_eligibility(
        ctx.market.kinds.get(item.instrument_id, "stock"), inputs.bar_count, None
    )
    missing = (
        list(dict.fromkeys(selected.reasons))
        if selected.state == "data_incomplete"
        else []
    )
    if not eligible and reason:
        missing.insert(0, reason)
    if ctx.market.raw[item.instrument_id][3][at]:
        missing.append("signal_day_suspended")
    if not validation.valid and selected.passed:
        status = "invalid_levels"
    elif selected.passed and eligible and not missing:
        status = "conditional"
    elif missing or selected.state == "data_incomplete":
        status = "data_incomplete"
    else:
        status = "observation"
    if status == "observation":
        levels = SignalLevels()
    return RuleSignal(status, levels, tuple(missing or selected.reasons), inputs)


def research_levels(strategy, levels, scale: float) -> er.Levels:
    """The signal's levels on the panel's adjusted basis."""

    def on(value):
        return None if value is None else value * scale

    return er.Levels(
        strategy.entry_type,
        on(levels.breakout_price),
        on(levels.pullback_low),
        on(levels.pullback_high),
        on(levels.invalid_price),
        on(levels.target_1),
        on(levels.target_2),
    )


# --- S1～S3 ---------------------------------------------------------------------


def atr14(item: lib.Series, at: int) -> float | None:
    """The mean (high − low) of the 14 bars to T on the adjusted prices; None
    when one of them has no high or low."""

    if at + 1 < ATR_WINDOW:
        return None
    pairs = [
        item.high[k] - item.low[k]
        for k in range(at + 1 - ATR_WINDOW, at + 1)
        if item.high[k] > 0 and item.low[k] > 0
    ]
    return sum(pairs) / ATR_WINDOW if len(pairs) == ATR_WINDOW else None


def market_filter(ctx: Context, day: date) -> bool | None:
    """TAIEX's close on ``day`` above the mean of its 60 closes to ``day``
    (strictly); None without the close or 60 closes."""

    from app.domain import moving_average

    close = ctx.panel.index_close.get(day)
    if close is None:
        return None
    at = bisect.bisect_right(ctx.index_days, day)
    window = [
        ctx.panel.index_close[d] for d in ctx.index_days[max(0, at - MA_WINDOW) : at]
    ]
    mean = moving_average(window, MA_WINDOW)
    if mean is None:
        return None
    return close > mean


def ranked(
    ctx: Context, day: date, members: list[tuple[lib.Series, int]]
) -> list[dict[str, Any]]:
    """The S members that pass, high first by the two keys, missing last, ties by hash."""

    rows = []
    for item, at in members:
        yoy = features.revenue_yoy(item, at)
        if yoy is None or yoy != yoy or not yoy > 0:
            continue
        atr = atr14(item, at)
        if atr is None or not atr > 0:
            continue
        values = {}
        for key in SCORE_KEYS:
            value = SCORE_FUNCTIONS[key](item, at)
            values[key] = None if value is None or value != value else float(value)
        tie = pr.tie_break(day, item.instrument_id)
        rows.append(
            {
                "item": item,
                "at": at,
                "atr": atr,
                "revenue_yoy": yoy,
                **values,
                "tie": tie,
                "key": pr.ranking_key(values, SCORE_KEYS, tie),
            }
        )
    rows.sort(key=lambda row: row["key"])
    return rows


# --- the trades -----------------------------------------------------------------


class TradeBars:
    """One instrument's ``exit_research.Bar`` per market session after the
    signal date to the segment's last session, built as they are read.  A
    session without a bar or with a suspended, flat or priceless one cannot
    trade (``suspended``)."""

    def __init__(self, ctx: Context, item: lib.Series, s_signal: int, s_last: int):
        self.ctx, self.item = ctx, item
        self.first, self.count = s_signal + 1, max(0, s_last - s_signal)
        self.built: dict[int, er.Bar] = {}

    def __len__(self) -> int:
        return self.count

    def __getitem__(self, key):
        if isinstance(key, slice):
            return [self[i] for i in range(*key.indices(self.count))]
        if key < 0:
            key += self.count
        if not 0 <= key < self.count:
            raise IndexError(key)
        if key not in self.built:
            self.built[key] = self._bar(self.first + key)
        return self.built[key]

    def session(self, key: int) -> int:
        return self.first + key

    def position(self, key: int) -> int | None:
        day = self.ctx.panel.sessions[self.first + key]
        return self.item.position.get(day)

    def _bar(self, s: int) -> er.Bar:
        day = self.ctx.panel.sessions[s]
        item = self.item
        at = item.position.get(day)
        nan = lib.NAN
        if at is None:
            return er.Bar(day, nan, nan, nan, nan, suspended=True)
        o, h, low, c = item.open[at], item.high[at], item.low[at], item.close[at]
        priced = all(value > 0 for value in (o, h, low, c))
        tradable = priced and not item.is_suspended(at)
        bounds = self.ctx.market.limits(item.instrument_id, at) if tradable else None
        scale = item.scale[at]
        return er.Bar(
            day,
            o,
            h,
            low,
            c,
            suspended=not tradable,
            limit_up=bounds[1] * scale if bounds else None,
            limit_down=bounds[0] * scale if bounds else None,
        )

    def last_close(self, key: int) -> tuple[int, float] | None:
        """The last bar to ``key`` with a close: (key, close)."""

        for k in range(key, -1, -1):
            bar = self[k]
            if bar.close == bar.close and bar.close > 0:
                return k, bar.close
        return None

    def ended_at(self) -> tuple[int, str] | None:
        """(key, status) of a delisted or transferred stock's last bar when it
        is in the path."""

        last = self.ctx.last_bar.get(self.item.instrument_id)
        status = self.ctx.statuses.get(self.item.instrument_id)
        if last is None or status not in ENDED:
            return None
        sessions = self.ctx.panel.sessions
        s = bisect.bisect_left(sessions, last)
        if s >= len(sessions) or sessions[s] != last:
            return None
        key = s - self.first
        return (key, status) if 0 <= key < self.count else None


def enter_zone(bars, upper: float, lower: float, days: int) -> tuple[er.Entry, bool]:
    """A limit buy at ``upper``: the first tradable session of the ``days``
    with its low at or below it fills at min(upper, open); a session locked at
    limit up does not.  The flag is a fill below ``lower`` (a gap down)."""

    blocked = 0
    for at in range(min(days, len(bars))):
        bar = bars[at]
        if bar.suspended or not bar.low <= upper:
            continue
        if bar.locked_up:
            blocked += 1
            continue
        fill = min(upper, bar.open)
        return er.Entry(
            at + 1, fill * (1.0 + SLIPPAGE), "filled", blocked
        ), fill < lower
    return er.Entry(None, None, "not_triggered", blocked), False


def rule_entry(levels: er.Levels, bars) -> tuple[er.Entry, int]:
    """``exit_research.enter`` and the key of the session it ends on (the
    fill, the gap that cancels it, or the window's last)."""

    entry = er.enter(levels, bars)
    window = min(er.WINDOW, len(bars))
    if entry.session is not None:
        return entry, entry.session - 1
    if entry.reason == "not_triggered":
        return entry, window - 1
    for k in range(1, window + 1):  # the gap's session: the first prefix that ends
        if er.enter(levels, bars[:k]).reason != "not_triggered":
            return entry, k - 1
    return entry, window - 1


@dataclass(frozen=True)
class Settled:
    exit: er.Exit
    suspension_delayed: bool = False


def settle(
    bars,
    entry: er.Entry,
    stop: float,
    target: float | None,
    last: int,
    ended: tuple[int, str] | None = None,
    cost_bps: float = COST_BPS,
) -> Settled:
    """The exit of a filled trade (docs 逐筆評估「出場」「停牌與下市」「段的邊界」).

    ``last`` is the key of the holding limit's session, ``ended`` the key of
    a delisted or transferred stock's last bar and its status (the exit reason); ``bars`` end on the segment's last session.
    """

    if entry.session is None or entry.price is None:
        raise ValueError("no entry")
    first = entry.session - 1
    pending: str | None = None
    by_lock = by_suspension = False

    def closed(at, price, reason, **flags):
        if by_lock:
            flags["limit_delayed"] = True
        return Settled(
            er._closed(entry, bars, at, price, reason, cost_bps, **flags), by_suspension
        )

    for at in range(first, len(bars)):
        bar = bars[at]
        if at == first:  # the fill: the levels' prices, no gap, no lock
            hit_stop, hit_target = (
                bar.low <= stop,
                target is not None and bar.high >= target,
            )
            if hit_stop:
                return closed(at, stop, "stop", both_touched=hit_target)
            if hit_target:
                return closed(at, target, "target")
            if at == last:
                return closed(at, bar.close, "time")
        elif bar.suspended:
            if pending is None and at >= last:
                pending = "time"
            if pending is not None:
                by_suspension = True
        elif pending is not None:
            if bar.locked_down:
                by_lock = True
            else:
                return closed(at, bar.open, pending)
        else:
            locked = bar.locked_down
            hit_stop, hit_target = (
                bar.low <= stop,
                target is not None and bar.high >= target,
            )
            if hit_stop:
                if locked:
                    pending, by_lock = "stop", True
                else:
                    gapped = bar.open < stop
                    return closed(
                        at,
                        bar.open if gapped else stop,
                        "stop",
                        both_touched=hit_target,
                        gapped=gapped,
                    )
            elif hit_target:
                # as exit_trade: a session at the target is not locked at
                # limit down (its high is above the target), so no delay here
                gapped = bar.open > target
                return closed(
                    at, bar.open if gapped else target, "target", gapped=gapped
                )
            elif at >= last:
                if locked:
                    pending, by_lock = "time", True
                else:
                    return closed(at, bar.close, "time")
        if ended is not None and at == ended[0]:
            found = bars.last_close(at) if hasattr(bars, "last_close") else None
            price = found[1] if found else bar.close
            return closed(at, price, ended[1])
    end = len(bars) - 1
    found = bars.last_close(end) if hasattr(bars, "last_close") else None
    price = found[1] if found else bars[end].close
    return closed(end, price, "segment_end")


def baseline(ctx: Context, s: int, e: int, x: int, s_last: int) -> dict[str, Any]:
    """The equal-weight population of signal date ``s`` bought at ``e``'s open
    and sold at ``x``'s close, net of the same costs (docs 逐筆評估「超額」)."""

    key = (s, e, x)
    if key in ctx.baselines:
        return ctx.baselines[key]
    sessions = ctx.panel.sessions
    nets: list[float] = []
    unbought = 0
    for item, _at in ctx.universe(s):
        at_e = item.position.get(sessions[e])
        if (
            at_e is None
            or item.is_suspended(at_e)
            or not (item.open[at_e] > 0 and item.close[at_e] > 0)
        ):
            unbought += 1
            continue
        bought = item.open[at_e] * (1.0 + SLIPPAGE)
        price = None
        for later in range(x, s_last + 1):
            at = item.position.get(sessions[later])
            if at is None or item.is_suspended(at):
                continue
            if not (item.open[at] > 0 and item.close[at] > 0):
                continue
            price = item.close[at] if later == x else item.open[at]
            break
        if price is None:  # delisted or suspended to the end: the last close
            last = bisect.bisect_right(item.dates, sessions[s_last]) - 1
            for at in range(last, at_e - 1, -1):
                if item.close[at] > 0:
                    price = item.close[at]
                    break
        if price is None:
            unbought += 1
            continue
        nets.append(price * (1.0 - SLIPPAGE) / bought - 1.0 - COST_BPS / 10_000.0)
    result = {
        "mean": statistics.fmean(nets) if nets else None,
        "members": len(nets),
        "unbought": unbought,
    }
    ctx.baselines[key] = result
    return result


def taiex_return(ctx: Context, e: int, x: int) -> float | None:
    sessions = ctx.panel.sessions
    if e < 1:
        return None
    before = ctx.panel.index_close.get(sessions[e - 1])
    after = ctx.panel.index_close.get(sessions[x])
    if not before or not after:
        return None
    return after / before - 1.0


# --- one segment ----------------------------------------------------------------


def window(
    sessions: list[date], segment: str, spec: dict[str, Any]
) -> tuple[int, int] | None:
    """(first, last) index of the sessions whose previous session is a signal
    date of the segment (explore_research.segment_window, the daily rule)."""

    first_day, last_day = SEGMENTS[segment]
    last = bisect.bisect_left(sessions, last_day + timedelta(days=1)) - 1
    if first_day is None:
        base = ex.start_index(sessions, spec["start"])
        if base is None:
            return None
    else:
        f0 = bisect.bisect_left(sessions, first_day)
        base = max(f0, 1) - 1
    first = base + 1
    return (first, last) if first <= last else None


@dataclass
class State:
    """One hypothesis's run on one segment."""

    name: str
    spec: dict[str, Any]
    trades: list[dict[str, Any]] = field(default_factory=list)
    # instrument -> the last session it cannot be a new signal on: occupied from
    # the signal date to the abandonment or the exit (inclusive), but a signal
    # after the exit day's close counts (docs 逐筆評估「訊號與占用」)
    busy: dict[int, int] = field(default_factory=dict)
    filter_blocked: int = 0
    filter_missing: int = 0
    signal_days: int = 0
    strategy: Any = None


def _trade_row(
    ctx: Context,
    state: State,
    s: int,
    item: lib.Series,
    rank: int | None,
    bars: TradeBars,
    entry: er.Entry,
    ends: int,
    stop: float | None,
    target: float | None,
    s_last: int,
    extra: dict[str, Any],
) -> dict[str, Any]:
    sessions = ctx.panel.sessions
    exchange, symbol, _ = ctx.panel.symbols.get(item.instrument_id, ("", "", ""))
    row: dict[str, Any] = {
        "hypothesis": state.name,
        "signal_date": sessions[s],
        "instrument_id": item.instrument_id,
        "exchange": exchange,
        "symbol": symbol,
        "rank": rank,
        **extra,
        "entry_reason": entry.reason,
        "limit_blocked": entry.limit_blocked,
        "fill_date": None,
        "fill_price": None,
        "stop": stop,
        "target": target,
        "exit_date": None,
        "exit_reason": None,
        "exit_price": None,
        "net": None,
        "holding": None,
        "both_touched": False,
        "gapped": False,
        "limit_delayed": False,
        "suspension_delayed": False,
        "population": None,
        "population_members": None,
        "population_unbought": None,
        "excess": None,
        "taiex": None,
        "taiex_excess": None,
    }
    if entry.session is None:
        state.busy[item.instrument_id] = bars.session(ends)
        row["abandoned_date"] = sessions[bars.session(ends)]
        return row
    hold_last = (
        er.WINDOW - 1 if state.spec["kind"] == "rule" else ends + state.spec["hold"] - 1
    )
    done = settle(bars, entry, stop, target, hold_last, bars.ended_at())
    out = done.exit
    e, x = bars.session(ends), bars.session(out.session - 1)
    state.busy[item.instrument_id] = x - 1
    population = baseline(ctx, s, e, x, s_last)
    index = taiex_return(ctx, e, x)
    row.update(
        {
            "fill_date": sessions[e],
            "fill_price": entry.price / (1.0 + SLIPPAGE),
            "exit_date": sessions[x],
            "exit_reason": out.reason,
            "exit_price": out.price / (1.0 - SLIPPAGE),
            "net": out.net,
            "holding": out.holding,
            "both_touched": out.both_touched,
            "gapped": out.gapped,
            "limit_delayed": out.limit_delayed,
            "suspension_delayed": done.suspension_delayed,
            "population": population["mean"],
            "population_members": population["members"],
            "population_unbought": population["unbought"],
            "excess": None
            if population["mean"] is None
            else out.net - population["mean"],
            "taiex": index,
            "taiex_excess": None if index is None else out.net - index,
        }
    )
    return row


def signal_day(ctx: Context, state: State, s: int, s_last: int) -> None:
    """The signals of one hypothesis on signal date ``s``, each traded at once."""

    sessions = ctx.panel.sessions
    day = sessions[s]
    spec = state.spec
    if spec["kind"] == "zone" and spec["market_filter"]:
        passed = market_filter(ctx, day)
        if passed is None:
            state.filter_missing += 1
            return
        if not passed:
            state.filter_blocked += 1
            return
    members = [
        (item, at)
        for item, at in ctx.universe(s)
        if state.busy.get(item.instrument_id, -1) < s
    ]
    made = 0
    if spec["kind"] == "zone":
        for rank, row in enumerate(ranked(ctx, day, members)[: spec["top"]], start=1):
            item, at = row["item"], row["at"]
            close, atr = item.close[at], row["atr"]
            upper, lower = close, close - spec["zone_atr"] * atr
            bars = TradeBars(ctx, item, s, s_last)
            entry, below = enter_zone(bars, upper, lower, spec["entry_days"])
            ends = (
                entry.session - 1
                if entry.session is not None
                else min(spec["entry_days"], len(bars)) - 1
            )
            fill = None if entry.price is None else entry.price / (1.0 + SLIPPAGE)
            state.trades.append(
                _trade_row(
                    ctx,
                    state,
                    s,
                    item,
                    rank,
                    bars,
                    entry,
                    ends,
                    None if fill is None else fill - spec["stop_atr"] * atr,
                    None if fill is None else fill + spec["target_atr"] * atr,
                    s_last,
                    {
                        "atr14": atr,
                        "zone_low": lower,
                        "zone_high": upper,
                        "below_lower": below,
                        "trust_buy_days": row["trust_buy_days"],
                        "institutional_flow_20": row["institutional_flow_20"],
                        "revenue_yoy": row["revenue_yoy"],
                    },
                )
            )
            made += 1
    else:
        strategy = state.strategy
        for item, at in members:
            signal = rule_signal(ctx, strategy, item, at)
            if not signal.actionable:
                continue
            levels = research_levels(strategy, signal.levels, item.scale[at])
            bars = TradeBars(ctx, item, s, s_last)
            entry, ends = rule_entry(levels, bars)
            state.trades.append(
                _trade_row(
                    ctx,
                    state,
                    s,
                    item,
                    None,
                    bars,
                    entry,
                    ends,
                    levels.invalid_price,
                    levels.target_1,
                    s_last,
                    {
                        "breakout_price": levels.breakout_price,
                        "pullback_low": levels.pullback_low,
                        "pullback_high": levels.pullback_high,
                    },
                )
            )
            made += 1
    state.signal_days += made > 0


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def series(trades: list[dict[str, Any]], key: str) -> list[float]:
    """The mean of ``key`` over each signal date's filled trades, by date."""

    days: dict[date, list[float]] = defaultdict(list)
    for trade in trades:
        if trade["net"] is not None and trade[key] is not None:
            days[trade["signal_date"]].append(trade[key])
    return [statistics.fmean(values) for _day, values in sorted(days.items())]


def stats(state: State) -> dict[str, Any]:
    """The judged and the listed numbers of one hypothesis on one segment."""

    trades = state.trades
    filled = [trade for trade in trades if trade["net"] is not None]
    nets = [trade["net"] for trade in filled]
    net_days = series(trades, "net")
    excess_days = series(trades, "excess")
    taiex_days = series(trades, "taiex_excess")
    reasons = Counter(trade["exit_reason"] for trade in filled)
    abandoned = Counter(
        trade["entry_reason"] for trade in trades if trade["net"] is None
    )
    won = [value for value in nets if value > 0]
    lost = [value for value in nets if value < 0]
    baselines = {
        (trade["signal_date"], trade["fill_date"], trade["exit_date"]): trade[
            "population_unbought"
        ]
        for trade in filled
    }
    return {
        "taiex_excess": {
            "days": len(taiex_days),
            "mean": _mean(taiex_days),
            "t": lib.t_stat(taiex_days, overlap=OVERLAP),
        },
        "excess": {
            "days": len(excess_days),
            "mean": _mean(excess_days),
            "t": lib.t_stat(excess_days, overlap=OVERLAP),
        },
        "absolute": {"days": len(net_days), "mean": _mean(net_days)},
        "signals": len(trades),
        "signal_days": state.signal_days,
        "trade_days": len(net_days),
        "trades": len(filled),
        "net_mean": _mean(nets),
        "net_median": statistics.median(nets) if nets else None,
        "win_rate": len(won) / len(filled) if filled else None,
        "zero": sum(1 for value in nets if value == 0),
        "won_mean": _mean(won),
        "lost_mean": _mean(lost),
        "won": len(won),
        "lost": len(lost),
        "exit_share": {
            reason: (reasons[reason] / len(filled) if filled else None)
            for reason in EXIT_REASONS
        },
        "exits": {reason: reasons[reason] for reason in EXIT_REASONS},
        "both_touched": sum(trade["both_touched"] for trade in filled),
        "gapped": sum(trade["gapped"] for trade in filled),
        "limit_delayed": sum(trade["limit_delayed"] for trade in filled),
        "suspension_delayed": sum(trade["suspension_delayed"] for trade in filled),
        "holding_mean": _mean([trade["holding"] for trade in filled]),
        "abandoned": sum(abandoned.values()),
        "abandon_rate": sum(abandoned.values()) / len(trades) if trades else None,
        "abandon_reasons": dict(sorted(abandoned.items())),
        "entry_limit_blocked": sum(trade["limit_blocked"] for trade in trades),
        "below_lower": sum(1 for trade in filled if trade.get("below_lower")),
        "filter_blocked_days": state.filter_blocked,
        "filter_missing_days": state.filter_missing,
        "population_unbought": sum(value or 0 for value in baselines.values()),
    }


def run_segment(
    ctx: Context,
    db: Path,
    names: list[str],
    segment: str,
    min_t: float = MIN_T,
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, dict[str, Any]]:
    """Every hypothesis of ``names`` on ``segment``: its numbers and verdict."""

    sessions = ctx.panel.sessions
    results: dict[str, dict[str, Any]] = {}
    states: list[State] = []
    bounds: dict[str, tuple[int, int]] = {}
    for name in names:
        spec = HYPOTHESES[name]
        result: dict[str, Any] = {
            "hypothesis": name,
            "segment": segment,
            "verdict": None if segment == USED else UNDECIDED,
            "reason": None,
            "window": {"days": 0},
            "prerequisites": None,
        }
        results[name] = result
        span = window(sessions, segment, spec)
        if span is None:
            result["reason"] = "no_sessions"
            continue
        first, last = span
        days = last - first + 1
        result["window"] = {
            "first_signal": sessions[first - 1].isoformat(),
            "first_session": sessions[first].isoformat(),
            "last_session": sessions[last].isoformat(),
            "days": days,
        }
        if segment != USED:
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
                continue  # not run (docs 段長下限、先決條件)
        state = State(name, spec)
        if spec["kind"] == "rule":
            state.strategy = strategy_of(name)
        states.append(state)
        bounds[name] = (first, last)
    if states:
        start = min(bounds[state.name][0] for state in states) - 1
        stop = max(bounds[state.name][1] for state in states) - 1
        for s in range(start, stop + 1):
            for state in states:
                first, last = bounds[state.name]
                if first - 1 <= s <= last - 1:
                    signal_day(ctx, state, s, last)
            if (s - start) % 250 == 0:
                progress(f"{segment} {sessions[s].isoformat()}")
    for state in states:
        result = results[state.name]
        numbers = stats(state)
        result.update(numbers)
        result["_trades"] = state.trades
        if segment == USED:
            continue
        result["min_t"] = min_t
        if numbers["trade_days"] < MIN_DAYS:
            result["reason"] = "too_few_trade_days"
            result["verdict"] = UNDECIDED
        else:
            result["verdict"] = ex.explore_judge(
                segment,
                result["window"]["days"],
                True,
                numbers["excess"],
                numbers["absolute"]["mean"],
                min_t,
            )
    return results


# --- output ---------------------------------------------------------------------

_pct, _t, public = ex._pct, ex._t, ex.public
VOLATILE_KEYS = ex.VOLATILE_KEYS
TRADE_FIELDS = (
    "signal_date",
    "exchange",
    "symbol",
    "rank",
    "atr14",
    "zone_low",
    "zone_high",
    "trust_buy_days",
    "institutional_flow_20",
    "revenue_yoy",
    "breakout_price",
    "pullback_low",
    "pullback_high",
    "entry_reason",
    "limit_blocked",
    "below_lower",
    "abandoned_date",
    "fill_date",
    "fill_price",
    "stop",
    "target",
    "exit_date",
    "exit_reason",
    "exit_price",
    "net",
    "holding",
    "both_touched",
    "gapped",
    "limit_delayed",
    "suspension_delayed",
    "population",
    "population_members",
    "population_unbought",
    "excess",
    "taiex",
    "taiex_excess",
)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return f"{value:.10f}"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def hypothesis_markdown(result: dict[str, Any], header: dict[str, Any]) -> str:
    name = result["hypothesis"]
    spec = HYPOTHESES[name]
    segment = ex.SEGMENT_NAMES[result["segment"]]
    window_ = result["window"] or {}
    verdict = result["verdict"] or "只列出、不判定"
    lines = [
        f"# {name} {segment}（trade_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 判定：**{verdict}**"
        + (f"（{REASONS[result['reason']]}）" if result["reason"] else ""),
        f"- 假設：{spec['label']}",
        f"- 登記 commit `{REGISTRATION_COMMIT}`；定義雜湊 `{header['definitions_sha256'][:16]}…`",
        f"- 期間：訊號日 {window_.get('first_signal', '—')} 起，成交日 "
        f"{window_.get('first_session', '—')}～{window_.get('last_session', '—')}，共 "
        f"{window_.get('days', 0)} 個交易日",
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
    if "excess" not in result:
        return "\n".join(lines)
    x, e, a = result["taiex_excess"], result["excess"], result["absolute"]
    lines += [
        # the TAIEX excess first, the verdict still on the population (#721)
        "## 數字（訊號日序列：同一訊號日的各筆先平均）",
        "",
        "| 量 | 訊號日數 | 平均 | t |",
        "| --- | ---: | ---: | ---: |",
        f"| 超額（對加權指數，只列出） | {x['days']} | {_pct(x['mean'], 3)} | {_t(x['t'])} |",
        f"| 超額（對母體，判定） | {e['days']} | {_pct(e['mean'], 3)} | {_t(e['t'])} |",
        f"| 扣成本報酬（判定） | {a['days']} | {_pct(a['mean'], 3)} | — |",
        "",
        f"門檻：t ≥ {result.get('min_t', MIN_T):.2f}（`t_stat(…, overlap={OVERLAP})`）；"
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
    for reason, count in result["abandon_reasons"].items():
        lines.append(f"| 放棄：{ABANDON_LABELS.get(reason, reason)} | {count:,} |")
    for reason in EXIT_REASONS:
        lines.append(
            f"| 出場：{EXIT_LABELS[reason]} | {_pct(result['exit_share'][reason], 1)}"
            f"（{result['exits'][reason]:,}） |"
        )
    lines += [
        f"| 同一根兩邊都碰到（算停損） | {result['both_touched']:,} |",
        f"| 跳空成交 | {result['gapped']:,} |",
        f"| 跌停順延 | {result['limit_delayed']:,} |",
        f"| 停牌順延 | {result['suspension_delayed']:,} |",
        f"| 進場遇漲停鎖死的日子 | {result['entry_limit_blocked']:,} |",
        f"| 母體在 e 買不進的檔次 | {result['population_unbought']:,} |",
    ]
    if spec["kind"] == "zone":
        lines.append(f"| 低於下緣成交 | {result['below_lower']:,} |")
        if spec["market_filter"]:
            lines += [
                f"| 大盤濾網擋下的天數 | {result['filter_blocked_days']:,} |",
                f"| 大盤濾網缺值的天數 | {result['filter_missing_days']:,} |",
            ]
    lines += [
        "",
        "限制：逐筆平均假設每個訊號都買得到、每筆等額，不是一個帳戶的資金曲線；"
        "持有期間互相重疊，t 以「日數 ÷ 20」計只是保守的下限。",
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
        "parameters": {key: value for key, value in spec.items() if key != "label"},
        **public(result),
    }
    (out / "tables.json").write_text(
        json.dumps(body, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (out / "summary.md").write_text(
        hypothesis_markdown(result, header), encoding="utf-8"
    )
    trades = result.get("_trades")
    if trades is None:
        return
    with (out / "trades.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(TRADE_FIELDS)
        for trade in trades:
            writer.writerow([_cell(trade.get(key)) for key in TRADE_FIELDS])
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


def _row(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "verdict": result["verdict"],
        "reason": result["reason"],
        "days": (result["window"] or {}).get("days", 0),
        "trade_days": result.get("trade_days", 0),
        "taiex_excess": result.get("taiex_excess"),
        "excess": result.get("excess"),
        "absolute_mean": (result.get("absolute") or {}).get("mean"),
        "trades": result.get("trades"),
        "abandon_rate": result.get("abandon_rate"),
        "prerequisites": result.get("prerequisites"),
    }


def overview_markdown(report: dict[str, Any], sha256: str) -> str:
    segment = report["segment"]
    stage = ex.SEGMENT_NAMES[segment]
    lines = [
        f"explore.json 的 sha256：`{sha256}`",
        "",
        f"# 新策略探索 第 {report['round']} 輪 {stage}（trade_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「第二輪：S1～S3、R1～R2」"
        f"「逐筆評估」）；工具設計 {DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(ex.OTHER_COMPARISONS),
        f"- 門檻：對母體超額 > 0 且 t ≥ {report['min_t']:.2f}，且扣成本報酬 > 0（訊號日序列）；"
        f"段長下限 {MIN_SEGMENT_DAYS.get(segment, '—')} 日、有成交的訊號日至少 {MIN_DAYS} 日；"
        "研究 DB 要有段內已下市公司",
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
            f"- 前瞻觀察：對母體超額 > 0 但 t < {report['min_t']:.2f}，且扣成本報酬 > 0；"
            "只當紀錄，不算通過、不進產品"
        )
        source = report["exploration"]
        lines.append(f"- 探索段報告：{source['url']}（sha256 `{source['sha256']}`）")
    header = (
        "| 代號 | 段內交易日 | 有成交的訊號日 | 對加權指數超額 | t | 對母體超額 | t "
        "| 扣成本報酬 | 成交筆數 | 放棄比例 | 判定 |"
    )
    lines += [
        "",
        "## 判定",
        "",
        header,
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for name, row in report["hypotheses"].items():
        lines.append(_overview_line(name, row, judged=True))
    if report.get("used"):
        lines += [
            "",
            "## 已用段（驗證通過的假設，只列出、不判定）",
            "",
            header,
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
        for name, row in report["used"].items():
            lines.append(_overview_line(name, row, judged=False))
    lines += [
        "",
        "各假設的數字與只列出的欄位見 `<代號>/summary.md`，逐筆見 `<代號>/trades.csv`。",
        "",
    ]
    return "\n".join(lines)


def _overview_line(name: str, row: dict[str, Any], judged: bool) -> str:
    e = row.get("excess") or {}
    x = row.get("taiex_excess") or {}
    verdict = (row["verdict"] or "—") if judged else "只列出"
    if row.get("reason"):
        verdict += f"（{REASONS[row['reason']]}）"
    trades = row.get("trades")
    return (
        f"| {name} | {row['days']} | {row.get('trade_days') or 0} "
        f"| {_pct(x.get('mean'), 3)} | {_t(x.get('t'))} "
        f"| {_pct(e.get('mean'), 3)} | {_t(e.get('t'))} "
        f"| {_pct(row.get('absolute_mean'), 3)} "
        f"| {'—' if trades is None else f'{trades:,}'} "
        f"| {_pct(row.get('abandon_rate'), 1)} | {verdict} |"
    )


# --- the runs -------------------------------------------------------------------


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
        "definitions_sha256": definitions_sha256(),
        "tool_commit": ex.tool_commit(),
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
    sha256 = ex.file_sha256(path)
    (out / "explore.md").write_text(overview_markdown(report, sha256), encoding="utf-8")
    return sha256


def load_from(segment: str) -> date:
    """The first day read: the warm-up before the segment (the exploration's
    anchor for its first signal)."""

    first_day = SEGMENTS[segment][0]
    if first_day is None:
        first_day = min(spec["start"][1] for spec in HYPOTHESES.values())
    return first_day - timedelta(days=WARMUP_CALENDAR_DAYS)


def run_exploration(
    db: Path,
    out: Path,
    names: list[str],
    command: str = "",
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, Any]:
    """``names`` on the exploration segment; nothing after its end read."""

    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    end = SEGMENTS[EXPLORATION][1]
    ctx = load(db, load_from(EXPLORATION), end, out / RAW_DIR_NAME)
    header = _header(db, EXPLORATION, command, end)
    report = {**header, "min_t": MIN_T, "selected": list(names), "hypotheses": {}}
    results = run_segment(ctx, db, list(names), EXPLORATION, progress=progress)
    for name in names:
        write_hypothesis(out / name, results[name], header)
        report["hypotheses"][name] = _row(results[name])
        progress(f"{name}: {results[name]['verdict']}")
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
    min_t = ex.validation_min_t(CUMULATIVE)
    report = {**header, "min_t": min_t, "exploration": source, "hypotheses": {}}
    results = run_segment(ctx, db, names, VALIDATION, min_t=min_t, progress=progress)
    for name in names:
        write_hypothesis(out / name, results[name], header)
        report["hypotheses"][name] = _row(results[name])
        progress(f"{name}: {results[name]['verdict']}")
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
    passed = [name for name in names if report["hypotheses"][name]["verdict"] == PASSED]
    if passed:  # the used segment only for the passed ones
        used_end = SEGMENTS[USED][1]
        used_ctx = load(db, load_from(USED), used_end, out / RAW_DIR_NAME)
        used = run_segment(used_ctx, db, passed, USED, progress=progress)
        report["used"] = {}
        for name in passed:
            write_hypothesis(out / name / USED, used[name], header)
            report["used"][name] = _row(used[name])
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
    parser = argparse.ArgumentParser(prog="trade_research.py", description=__doc__)
    parser.add_argument(
        "--db", required=True, help="the research DB (/research/stock.db)"
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--segment", required=True, choices=STAGES)
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    parser.add_argument(
        "--hypotheses",
        help="exploration (required): the registered hypotheses whose data is "
        "accepted, comma separated, e.g. S1,R1; each runs once per tool version",
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
    if args.hypotheses is not None and args.segment == VALIDATION:
        parser.error("--hypotheses goes with --segment exploration only")
    db = Path(args.db)
    problems = er.refusals(db, args.min_free_gb)
    names: list[str] = []
    if args.segment == EXPLORATION:
        chosen, names = ex.exploration_problems(
            db, args.hypotheses, HYPOTHESES, VERSION
        )
        problems = [*problems, *chosen]
    if problems:
        print(json.dumps({"refused": problems}, ensure_ascii=False))
        return 2
    command = "python tools/research/trade_research.py " + " ".join(argv)
    progress = lambda text: print(text, file=sys.stderr, flush=True)  # noqa: E731
    if args.segment == EXPLORATION:
        line = run_exploration(db, Path(args.out), names, command, progress=progress)
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
