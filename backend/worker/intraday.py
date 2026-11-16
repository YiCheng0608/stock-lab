"""The intraday alerts: ``python -m worker.cli intraday`` (#801).

Each trading day serve starts ``intraday --send --trigger scheduler`` at 08:59 Taipei. It
reads its stocks once, then from 09:00 to 13:30 asks Fugle for each stock's intraday quote
once a minute (``worker.fugle``) and sends a Telegram message to the user's own chat
(``worker.notify.send``) when a stock touches a rule level of the page. It ends after the
13:30 round, by 13:31.

- **Stocks** (read once, read-only, at the start): the today list, the candidates of the
  run the today page shows (``app.candidate_runs.read_run`` of the session before today,
  at most the page's 20, in rank order) whose signal's ``earliest_execution_date`` is
  today; and my tracking's open plans (``pending``, ``triggered``, not cancelled) created
  before 09:00. A plan of a listed signal with the very same levels is one track, both
  sources on its messages; with other levels (the signal rewritten after the plan was made)
  each is a track of its own. At most ``fugle.MAX_SYMBOLS`` stocks a minute: the list by
  rank first, then the plans by creation; the others are logged and told once a day.
- **Levels**: the signal's own (``signals``), as the page shows them
  (``app.candidate_view._levels``): a breakout's ``breakout_price``, a pullback's
  ``pullback_low``～``pullback_high``, ``invalid_price``, ``target_1``, ``target_2``; a
  plan's own copy of them. Not ``strategy_levels`` (the T+1 thresholds of a new signal).
- **Rules** (``judge``, a pure function): see its docstring. Each event of a track is sent
  once a day.
- **Record**: the day's log ``<logs>/intraday-YYYYMMDD.log`` (``===== start``, the stocks,
  one ``--- poll`` line a round with the time, the stocks, the successes, the HTTP codes,
  the milliseconds and the lag of ``lastUpdated``, each event, one ``--- result`` line and
  ``===== end``), and the day's events ``<logs>/intraday-YYYYMMDD.jsonl``, one JSON line
  each, which a restarted run reads first so that it never sends one twice, and one
  ``levels`` line a round (each track's high, low and last trade, no key, no event),
  which it reads as its first round's ``before`` (#808 AC-3); a track without one takes
  the high and low since the open and is logged in ``--- levels_restored``. The lock
  ``<data>/locks/intraday.lock`` is no other job's. Logs are kept 90 days. No database
  writes, no migration; maintenance mode does not stop it.
- **Failures** (Fugle): ``worker.fugle``'s outcomes. Five failed rounds in a row (no answer
  of any stock) slow the rounds to one every 5 minutes with one message; the first answer
  after that ends it with another (each once a day). A 401, 403 or 429 stops the day's
  reading with a message. A 404 or a malformed quote drops that stock for the day.
- **Without a key**: no ``FUGLE_API_KEY`` (or, with ``--send``, no Telegram token or chat)
  records ``not_configured`` and ends.

``--dry-run`` (#801 AC-6) asks Fugle the same way but sends nothing and writes no file: the
log lines and the messages go to stdout; ``--minutes`` ends it early. It takes no lock, so
it must not run beside the scheduled run (both would count against the key's 60 a minute).

Only the standard library at the top: serve imports the log reading here.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from . import fugle, job, notify

LOCK = "intraday"
LOG_PREFIX = "intraday"
# serve's trigger, the first and the last round, and the end (#801 scope 6).
START_TIME = (8, 59)
FIRST_POLL = (9, 0)
LAST_POLL = (13, 30)
END_TIME = (13, 31)
# 08:59 to 13:31 and a few minutes for a slow last round; serve's backstop adds 5.
TIME_LIMIT_MINUTES = 280.0
# The rounds of a full day: 09:00 to 13:30, one a minute.
POLLS_PER_DAY = 271
FAILED_ROUNDS_BEFORE_SLOW = 5
SLOW_MINUTES = 5
FETCH_WORKERS = 10
LOG_RETENTION_DAYS = 90
LIST = "今日名單"
TRACKING = "我的追蹤"
# Results.
FINISHED = "finished"
STOPPED = "stopped"
NOT_CONFIGURED = "not_configured"
FAILED = "failed"
SKIPPED = "skipped"
# The results after which the day needs no run any more (serve's catch-up). As notify's,
# not_configured is not one: a key set later the same morning is caught up.
DONE_RESULTS = (
    FINISHED,
    STOPPED,
    "skipped reason=non_trading_day",
    "skipped reason=no_targets",
)
RESULT_LINE = re.compile(r"^--- result status=(\S+)(?: reason=(\S+))?")

# --- events ---------------------------------------------------------------------------

ENTRY = "entry"
STOP = "stop"
TARGET_1 = "target_1"
TARGET_2 = "target_2"
STOP_BEFORE_ENTRY = "stop_before_entry"
GAP_ABOVE_TARGET = "gap_above_target"
GAP_BELOW_INVALID = "gap_below_invalid"
STOP_AND_TARGET = "stop_and_target_1"
ENTRY_AND_STOP = "entry_and_stop"
# Events after which the track is not judged again that day.
FINAL = {
    STOP,
    TARGET_2,
    STOP_BEFORE_ENTRY,
    GAP_ABOVE_TARGET,
    GAP_BELOW_INVALID,
    STOP_AND_TARGET,
    ENTRY_AND_STOP,
}
# The run's own notices (key OPS in the jsonl), each once a day.
OPS = "ops"
PAUSED = "paused"
RESUMED = "resumed"
STOPPED_DAY = "stopped"
CAPPED = "capped"
# The jsonl's line of a round's high, low and last trade by track (#808 AC-3): no key and
# no event, so ``sent_events`` never reads it as one.
LEVELS = "levels"

# Every message's words (#801 scope 5): only the rule's levels, never an order
# (「買進」「賣出」「出場」; ROADMAP 價位陳述規則價位、不寫成下單指示). The test scans them all.
TEMPLATES = {
    ENTRY + ":breakout": "{head} 觸及規則進場價 {entry}（{when}）",
    ENTRY + ":pullback": "{head} 觸及規則進場區 {entry}（{when}）",
    STOP: "{head} 觸及停損 {stop}（{when}）",
    TARGET_1: "{head} 觸及目標一 {target_1}（{when}）",
    TARGET_2: "{head} 觸及目標二 {target_2}（{when}）",
    STOP_BEFORE_ENTRY: "{head} 跌破停損 {stop}，進場條件不再成立（{when}）",
    GAP_ABOVE_TARGET: (
        "{head} 觸及規則進場{entry_word} {entry}，但開盤 {open} 已在目標一 {target_1} 以上，"
        "依規則不算進場，今天這檔不再通知（{when}）"
    ),
    GAP_BELOW_INVALID: (
        "{head} 觸及規則進場{entry_word} {entry}，但開盤 {open} 已在停損 {stop} 以下，"
        "依規則不算進場，今天這檔不再通知（{when}）"
    ),
    STOP_AND_TARGET: "{head} 同一分鐘內觸及停損 {stop} 與目標一 {target_1}，先後不明（{when}）",
    ENTRY_AND_STOP: (
        "{head} 同一分鐘內觸及規則進場{entry_word} {entry} 與停損 {stop}，先後不明，"
        "今天這檔不再通知（{when}）"
    ),
    "when": "{minute} 前後；{trade}",
    "trade": "{time} 成交 {price}",
    "no_trade": "成交價取不到",
    "sources": "來源：{sources}",
    "locked_up": "漲停鎖住（{bid}，{ask}）",
    "locked_down": "跌停鎖住（{bid}，{ask}）",
    "bid": "委買 {price}",
    "ask": "委賣 {price}",
    "bid_none": "委買取不到",
    "ask_none": "委賣取不到",
    "unavailable": "取不到",
    PAUSED: "盤中報價暫停（來源回應失敗），{minute} 起；改為每 {slow} 分鐘讀一次",
    RESUMED: "盤中報價恢復，{minute} 起",
    STOPPED_DAY: "盤中報價今天停止讀取（富果回應 {code}：{why}），{minute} 起",
    CAPPED: (
        "盤中通知今天有 {total} 檔，超過每分鐘 {limit} 檔的上限，"
        "略過 {skipped_count} 檔：{skipped}"
    ),
}
STOP_WHY = {
    "key_invalid": "API key 無效",
    "plan_not_allowed": "方案不支援",
    "rate_limited": "超過呼叫上限",
}


@dataclass(frozen=True)
class Track:
    """One stock's levels to watch, from the list's signal or a plan (or both)."""

    key: str  # signal:<id> or plan:<id>: the jsonl's key of its events
    symbol: str
    name: str
    sources: tuple[str, ...]
    entry_type: str
    breakout: float | None
    zone_low: float | None
    zone_high: float | None
    invalid: float
    target_1: float
    target_2: float | None
    # A triggered plan has entered already: its stop and target count from the start.
    entered: bool = False

    @property
    def head(self) -> str:
        return f"{self.symbol} {self.name}".strip()


@dataclass
class State:
    """What a track has done today; HIGH and LOW are the last round's."""

    entered: bool = False
    done: bool = False
    target_1: bool = False
    high: float | None = None
    low: float | None = None
    last: float | None = None  # the last round's trade price


def _price(value: float | None) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def track(
    key: str,
    symbol: str,
    name: str,
    sources: tuple[str, ...],
    levels: Any,
    *,
    entered: bool = False,
) -> Track | None:
    """A track of LEVELS (a ``signals`` or ``tracking_plans`` row: entry_type,
    breakout_price, pullback_low, pullback_high, invalid_price, target_1, target_2), or
    None when they are incomplete by the page's rules (notify.level_parts)."""

    kind = getattr(levels, "entry_type", None)
    stop, target = (
        getattr(levels, "invalid_price", None),
        getattr(levels, "target_1", None),
    )
    if not (_price(stop) and _price(target)):
        return None
    breakout = getattr(levels, "breakout_price", None)
    low, high = (
        getattr(levels, "pullback_low", None),
        getattr(levels, "pullback_high", None),
    )
    if kind == "breakout":
        if not (_price(breakout) and stop < breakout < target):
            return None
        low = high = None
    elif kind == "pullback":
        if not (_price(low) and _price(high) and low <= high and stop < target):
            return None
        breakout = None
    else:
        return None
    target_2 = getattr(levels, "target_2", None)
    return Track(
        key=key,
        symbol=symbol,
        name=name,
        sources=sources,
        entry_type=kind,
        breakout=breakout,
        zone_low=low,
        zone_high=high,
        invalid=stop,
        target_1=target,
        target_2=target_2 if _price(target_2) else None,
        entered=entered,
    )


# --- the rules ------------------------------------------------------------------------


def _up(level: float | None, high: float, before: float | None) -> bool:
    """The new high reaches LEVEL: this round's and not the last one's."""

    return level is not None and high >= level and (before is None or before < level)


def _down(level: float, low: float, before: float | None) -> bool:
    return low <= level and (before is None or before > level)


def _meets_zone(track: Track, low: float | None, high: float | None) -> bool:
    if low is None or high is None:
        return False
    return low <= track.zone_high and high >= track.zone_low


def _entry_hit(track: Track, state: State, high: float, low: float) -> bool:
    if track.entry_type == "breakout":
        return _up(track.breakout, high, state.high)
    return _meets_zone(track, low, high) and not _meets_zone(
        track, state.low, state.high
    )


def _entry_first(track: Track, state: State, quote: fugle.Quote) -> bool:
    """Whether the entry came before the stop within one round: the round starts at the
    open (the first round) or the last round's trade, and from there the price meets the
    entry first when it is in it already, or, for a pullback, above the zone (it passes
    the zone on its way down to the stop)."""

    start = quote.open if state.high is None else state.last
    if not _price(start):
        return False
    if track.entry_type == "breakout":
        return start >= track.breakout
    return start >= track.zone_low


def judge(track: Track, state: State, quote: fugle.Quote) -> tuple[list[str], State]:
    """The events of one round and the state after it (#801 scope 4).

    - A trial quote (``isTrial``) or one without a high and a low is not judged.
    - Touching is by the high and the low: a level counts when this round's high (low)
      reaches it and the last round's did not; the first round of a track takes the high
      and low since the open.
    - Entry: a breakout's high ≥ the entry; a pullback's [low, high] meets the zone.
    - Gaps (``plan_tracking_v2``): on the entry round, an open at or above target one is
      ``gap_above_target``, at or below the stop ``gap_below_invalid``: no entry, the
      stock ends for the day.
    - Before the entry, a low at or below the stop is ``stop_before_entry`` (the entry no
      longer stands), and the stock ends for the day. Both on one round: the entry and
      then the stop when the entry came first (``_entry_first``: the open of a pullback
      already in the zone, as 3162 on 11/16), else ``entry_and_stop`` (the order is
      unknown) and the stock ends.
    - After the entry (a ``triggered`` plan from the start): the stop, target one and
      then target two. The stop and target one new on one round is ``incomparable`` as
      the tracking has it (``stop_and_target_1``). The stop or target two ends the stock;
      after target one only target two is watched. Targets new on the entry round count.
    """

    if quote.is_trial or quote.high is None or quote.low is None or state.done:
        return [], state
    high, low = quote.high, quote.low
    after = replace(state, high=high, low=low, last=quote.last_price)
    events: list[str] = []
    if not state.entered:
        if not _entry_hit(track, state, high, low):
            if _down(track.invalid, low, state.low):
                after.done = True
                return [STOP_BEFORE_ENTRY], after
            return [], after
        if quote.open is not None and quote.open >= track.target_1:
            after.done = True
            return [GAP_ABOVE_TARGET], after
        if quote.open is not None and quote.open <= track.invalid:
            after.done = True
            return [GAP_BELOW_INVALID], after
        if _down(track.invalid, low, state.low) and not _entry_first(
            track, state, quote
        ):
            after.done = True
            return [ENTRY_AND_STOP], after
        events.append(ENTRY)
        after.entered = True
    stop = not state.target_1 and _down(track.invalid, low, state.low)
    target_1 = not state.target_1 and _up(track.target_1, high, state.high)
    if stop and target_1:
        after.done = True
        return [*events, STOP_AND_TARGET], after
    if stop:
        after.done = True
        return [*events, STOP], after
    if target_1:
        events.append(TARGET_1)
        after.target_1 = True
    if after.target_1 and _up(track.target_2, high, state.high):
        events.append(TARGET_2)
        after.done = True
    if after.target_1 and track.target_2 is None:
        after.done = True
    return events, after


def resumed(track: Track, sent: Iterable[str], levels: tuple | None = None) -> State:
    """The state of TRACK after the events SENT today (a restarted run). LEVELS, the
    (high, low, last) of its last round recorded (``day_levels``), are the ``before`` of
    the first round after the restart; without them that round takes the high and low
    since the open, as a first round does (#808 AC-3)."""

    state = State(entered=track.entered)
    if levels is not None:
        state.high, state.low, state.last = levels
    for event in sent:
        if event == ENTRY:
            state.entered = True
        elif event == TARGET_1:
            state.entered = state.target_1 = True
        if event in FINAL:
            state.done = True
    if state.target_1 and track.target_2 is None:
        state.done = True
    return state


# --- the messages ---------------------------------------------------------------------


def _fmt(value: float | None) -> str:
    return notify.price(value) if _price(value) else TEMPLATES["unavailable"]


def _taipei(moment: datetime) -> datetime:
    return moment.astimezone(job.TAIPEI)


def _when(polled: datetime, quote: fugle.Quote) -> str:
    if _price(quote.last_price) and quote.last_time is not None:
        trade = TEMPLATES["trade"].format(
            time=f"{_taipei(quote.last_time):%H:%M:%S}", price=_fmt(quote.last_price)
        )
    else:
        trade = TEMPLATES["no_trade"]
    return TEMPLATES["when"].format(minute=f"{_taipei(polled):%H:%M}", trade=trade)


def _entry(track: Track) -> str:
    if track.entry_type == "breakout":
        return _fmt(track.breakout)
    return f"{_fmt(track.zone_low)}～{_fmt(track.zone_high)}"


def message(track: Track, event: str, quote: fugle.Quote, polled: datetime) -> str:
    """The Telegram text of EVENT (parse_mode HTML: the name is escaped)."""

    template = TEMPLATES[f"{ENTRY}:{track.entry_type}" if event == ENTRY else event]
    line = template.format(
        head=notify.esc(track.head),
        entry=_entry(track),
        entry_word="價" if track.entry_type == "breakout" else "區",
        stop=_fmt(track.invalid),
        target_1=_fmt(track.target_1),
        target_2=_fmt(track.target_2),
        open=_fmt(quote.open),
        when=_when(polled, quote),
    )
    lines = [line]
    if quote.locked_up or quote.locked_down:
        # What the quote has, as it is: no price is inferred for a missing side.
        sides = {
            side: TEMPLATES[side].format(price=_fmt(value))
            if _price(value)
            else TEMPLATES[f"{side}_none"]
            for side, value in (("bid", quote.bid), ("ask", quote.ask))
        }
        lines.append(
            TEMPLATES["locked_up" if quote.locked_up else "locked_down"].format(**sides)
        )
    lines.append(TEMPLATES["sources"].format(sources="、".join(track.sources)))
    return "\n".join(lines)


def notice(kind: str, polled: datetime, **fields: Any) -> str:
    return TEMPLATES[kind].format(
        minute=f"{_taipei(polled):%H:%M}", slow=SLOW_MINUTES, **fields
    )


# --- the stocks -----------------------------------------------------------------------


LEVEL_FIELDS = (
    "entry_type",
    "breakout_price",
    "pullback_low",
    "pullback_high",
    "invalid_price",
    "target_1",
    "target_2",
)


def _levels(row: Any) -> tuple:
    return tuple(getattr(row, name, None) for name in LEVEL_FIELDS)


def read_tracks(db, today: date, before: datetime) -> list[Track]:
    """The day's tracks in priority order: the today list by rank, then the open plans
    created before BEFORE (aware) by creation. A plan of a listed signal with the same
    levels joins that signal's track; with other levels it is a track of its own."""

    from sqlalchemy import select

    from app.candidate_runs import read_run
    from app.candidate_view import MAX_LIMIT
    from app.domain import PLAN_OPEN_STATUSES
    from app.models import DailyCandidate, Instrument, Signal, TrackingPlan

    names: dict[int, tuple[str, str]] = {}

    def instrument(instrument_id: int) -> tuple[str, str]:
        if instrument_id not in names:
            row = db.get(Instrument, instrument_id)
            names[instrument_id] = (row.symbol, row.name) if row else ("", "")
        return names[instrument_id]

    cutoff = before.astimezone(timezone.utc).replace(tzinfo=None)
    plans = db.scalars(
        select(TrackingPlan)
        .where(
            TrackingPlan.status.in_(sorted(PLAN_OPEN_STATUSES)),
            TrackingPlan.cancelled_at.is_(None),
            TrackingPlan.created_at < cutoff,
        )
        .order_by(TrackingPlan.created_at, TrackingPlan.id)
    ).all()
    # A plan joins its listed signal's track only with the very same levels: a plan keeps
    # its own copy (#801 scope 3), and a signal rewritten after the plan was made has
    # other levels, so then each is a track of its own (#802 review 6910820856 item 2).
    plan_signals = {plan.signal_id: plan for plan in plans}
    tracks: list[Track] = []
    listed: set[int] = set()
    run = read_run(db, notify.previous_session(db, today))
    if run is not None:
        rows = db.execute(
            select(DailyCandidate, Signal)
            .join(Signal, Signal.id == DailyCandidate.signal_id)
            .where(DailyCandidate.candidate_run_id == run.id)
            .order_by(DailyCandidate.rank)
            .limit(MAX_LIMIT)
        ).all()
        for candidate, signal in rows:
            if signal.earliest_execution_date != today:
                continue
            symbol, name = instrument(candidate.instrument_id)
            plan = plan_signals.get(signal.id)
            same = plan is not None and _levels(plan) == _levels(signal)
            made = track(
                f"signal:{signal.id}",
                symbol,
                name,
                (LIST, TRACKING) if same else (LIST,),
                signal,
                entered=same and plan.status == "triggered",
            )
            if same:
                listed.add(signal.id)
            if made is not None:
                tracks.append(made)
    for plan in plans:
        if plan.signal_id in listed:
            continue
        if plan.earliest_execution_date and plan.earliest_execution_date > today:
            continue
        symbol, name = instrument(plan.instrument_id)
        made = track(
            f"plan:{plan.id}",
            symbol,
            name,
            (TRACKING,),
            plan,
            entered=plan.status == "triggered",
        )
        if made is not None:
            tracks.append(made)
    return tracks


def symbols_of(tracks: Iterable[Track]) -> list[str]:
    """The stocks of TRACKS, once each, in their order."""

    return list(dict.fromkeys(track.symbol for track in tracks))


# --- the record -----------------------------------------------------------------------


def log_path(log_dir: Path, day: date) -> Path:
    return log_dir / f"{LOG_PREFIX}-{day:%Y%m%d}.log"


def events_path(log_dir: Path, day: date) -> Path:
    return log_dir / f"{LOG_PREFIX}-{day:%Y%m%d}.jsonl"


def day_results(log_dir: Path, day: date) -> list[str]:
    """The day's ``--- result`` lines as ``status`` or ``skipped reason=<reason>``."""

    try:
        text = log_path(log_dir, day).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    results = []
    for line in text.splitlines():
        match = RESULT_LINE.match(line)
        if match:
            status, reason = match.groups()
            results.append(f"{status} reason={reason}" if status == SKIPPED else status)
    return results


def day_done(log_dir: Path, day: date) -> bool:
    """Whether the day needs no run any more (serve's catch-up reads it)."""

    return any(result in DONE_RESULTS for result in day_results(log_dir, day))


def _records(path: Path) -> list[dict]:
    """The JSON objects of the day's jsonl (unreadable lines are skipped)."""

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            out.append(record)
    return out


def sent_events(path: Path) -> dict[str, list[str]]:
    """The events of the day's jsonl by key: the lines with a key and an event (the
    ``levels`` lines have neither)."""

    out: dict[str, list[str]] = {}
    for record in _records(path):
        if record.get("key") and record.get("event"):
            out.setdefault(str(record["key"]), []).append(str(record["event"]))
    return out


def _number(value: Any) -> float | None:
    return value if _price(value) else None


def day_levels(path: Path) -> dict[str, tuple]:
    """Each track's (high, low, last) of its last round in the day's jsonl: the latest
    ``levels`` line that has it (#808 AC-3). A track without a high or a low is left
    out."""

    out: dict[str, tuple] = {}
    for record in _records(path):
        levels = record.get(LEVELS)
        if not isinstance(levels, dict):
            continue
        for key, values in levels.items():
            if not isinstance(values, dict):
                continue
            high, low = _number(values.get("high")), _number(values.get("low"))
            if high is not None and low is not None:
                out[str(key)] = (high, low, _number(values.get("last")))
    return out


def in_run_window(moment: datetime) -> bool:
    """Between START_TIME and LAST_POLL Taipei: when a run still has rounds to do."""

    return START_TIME <= (moment.hour, moment.minute) < LAST_POLL


# --- the run --------------------------------------------------------------------------


def add_arguments(parser: argparse.ArgumentParser) -> None:
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="照常讀富果、判斷，但不送 Telegram、不寫日誌與 jsonl（印到 stdout）、不取鎖",
    )
    mode.add_argument(
        "--send", action="store_true", help="送出（鎖、日誌、jsonl 同排程）"
    )
    parser.add_argument(
        "--now",
        help="時間注入（serve 的 --now）：ISO 8601，沒有時區時為台北時間；時鐘從這裡往前走",
    )
    parser.add_argument(
        "--trigger",
        choices=job.TRIGGERS,
        default="manual",
        help="scheduler 在台北 13:30 以後啟動時記 skipped reason=too_late（預設 manual）",
    )
    parser.add_argument("--log-dir", help="日誌目錄；預設 <資料目錄>/logs")
    parser.add_argument(
        "--minutes", type=int, help="只配 --dry-run：跑幾分鐘就結束（AC-6 實測用）"
    )


def argument_problem(args: argparse.Namespace) -> str | None:
    if args.minutes is not None and not args.dry_run:
        return "--minutes goes with --dry-run only"
    if args.minutes is not None and args.minutes <= 0:
        return "--minutes must be positive"
    if args.now:
        try:
            datetime.fromisoformat(args.now)
        except ValueError:
            return f"--now must be an ISO 8601 time, got {args.now!r}"
    return None


def _injected(value: str | None) -> datetime | None:
    if not value:
        return None
    moment = datetime.fromisoformat(value)
    return (moment if moment.tzinfo else moment.replace(tzinfo=job.TAIPEI)).astimezone(
        job.TAIPEI
    )


def _read_only_session():
    """A session on the database opened read-only (``mode=ro``)."""

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.config import DB_PATH

    # SQLAlchemy hands sqlite3 ``file:<path>?mode=ro`` as a URI with uri=true.
    path = Path(DB_PATH).resolve().as_posix()
    engine = create_engine(f"sqlite:///file:{path}?mode=ro&uri=true")
    return _ClosingSession(Session(engine), engine)


class _ClosingSession:
    def __init__(self, session, engine) -> None:
        self.session, self.engine = session, engine

    def __enter__(self):
        return self.session

    def __exit__(self, *_exc) -> None:
        self.session.close()
        self.engine.dispose()


def _session():
    return _read_only_session()


def _minute(moment: datetime, hm: tuple[int, int]) -> datetime:
    return moment.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)


def _median(values: list[float]) -> str:
    return f"{statistics.median(values):.0f}" if values else "-"


@dataclass
class _Round:
    polled: datetime
    fetched: list[fugle.Fetched] = field(default_factory=list)

    @property
    def answered(self) -> bool:
        return any(item.code == "200" for item in self.fetched)

    @property
    def ok(self) -> int:
        return sum(1 for item in self.fetched if item.outcome == fugle.OK)


class Run:
    """One day's run. CLOCK, SLEEP, FETCH and SEND are injected by the tests."""

    def __init__(
        self,
        args: argparse.Namespace,
        *,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        fetch: Callable[[str], fugle.Fetched] | None = None,
        send: Callable[[str], dict[str, Any]] | None = None,
        environ=os.environ,
        out=None,
        workers: int = FETCH_WORKERS,
    ) -> None:
        self.args = args
        injected = _injected(args.now)
        offset = injected - datetime.now(job.TAIPEI) if injected else timedelta(0)
        self.clock = clock or (lambda: datetime.now(job.TAIPEI) + offset)
        self.sleep = sleep
        self.environ = environ
        self.key = environ.get(fugle.KEY_ENV, "").strip()
        self.fetch = fetch or (lambda symbol: fugle.fetch(symbol, self.key))
        self.send_text = send
        self.out = out or sys.stdout
        self.workers = workers
        self.today = self.clock().date()
        self.data_dir = job.resolve_data_dir(None)
        self.log_dir = Path(os.path.abspath(args.log_dir or self.data_dir / "logs"))
        self.path = log_path(self.log_dir, self.today)
        self.events = events_path(self.log_dir, self.today)
        self.sent: dict[str, list[str]] = {}
        self.telegram_token = environ.get(notify.TOKEN_ENV, "").strip()

    # The record.

    def mask(self, text: str) -> str:
        text = notify.mask(text, self.telegram_token)
        return text.replace(self.key, "<key>") if self.key else text

    def log(self, text: str) -> None:
        text = self.mask(text)
        if self.args.dry_run:
            print(text, file=self.out, flush=True)
            return
        with open(self.path, "a", encoding="utf-8", newline="") as log:
            log.write(text + "\n")

    def record(self, key: str, symbol: str, event: str, text: str, status: str) -> None:
        self.sent.setdefault(key, []).append(event)
        line = json.dumps(
            {
                "at": self.clock().isoformat(timespec="seconds"),
                "key": key,
                "symbol": symbol,
                "event": event,
                "status": status,
                "text": text,
            },
            ensure_ascii=False,
        )
        if self.args.dry_run:
            print(f"--- message {line}", file=self.out, flush=True)
            return
        with open(self.events, "a", encoding="utf-8", newline="") as handle:
            handle.write(self.mask(line) + "\n")

    def deliver(self, key: str, symbol: str, event: str, text: str) -> None:
        """Send TEXT once a day per (KEY, EVENT); log and record it."""

        if event in self.sent.get(key, []):
            return
        if self.args.dry_run:
            status = "dry_run"
        else:
            outcome = self.send_text(text) if self.send_text else {"status": "failed"}
            status = outcome.get("status", FAILED)
            if status != notify.SENT:
                self.log(
                    f"--- send_failed key={key} event={event}"
                    f" reasons={'|'.join(outcome.get('reasons') or []) or '-'}"
                )
        self.log(f"--- event key={key} symbol={symbol} event={event} status={status}")
        self.record(key, symbol, event, text, status)

    # The steps.

    def run(self) -> int:
        if not self.args.dry_run:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        started = self.clock()
        lock = job.FileLock(job.lock_path(self.data_dir, LOCK))
        locked = True if self.args.dry_run else lock.acquire()
        try:
            self.log(
                f"===== {started.isoformat()} start job=intraday trigger={self.args.trigger}"
                f" date={self.today.isoformat()}"
                f" configured={'yes' if self.key else 'no'}"
                f" dry_run={'yes' if self.args.dry_run else 'no'}"
            )
            try:
                code, result = self._run(locked)
            except Exception as exc:  # logged as the day's failure
                code, result = 1, f"status={FAILED} reason=error:{type(exc).__name__}"
            self.log(f"--- result {result}")
            finished = self.clock()
            self.log(
                f"===== {finished.isoformat()} end exit={code}"
                f" seconds={round((finished - started).total_seconds())}"
            )
        finally:
            if locked and not self.args.dry_run:
                lock.release()
                self._remove_old_logs()
        print(
            self.mask(f"intraday {result} exit={code} log={self.path}"),
            file=self.out,
            flush=True,
        )
        return code

    def _missing(self) -> list[str]:
        missing = [] if self.key else [fugle.KEY_ENV]
        if not self.args.dry_run:
            missing += [
                name
                for name in (notify.TOKEN_ENV, notify.CHAT_ENV)
                if not self.environ.get(name, "").strip()
            ]
        return missing

    def _run(self, locked: bool) -> tuple[int, str]:
        if not locked:
            return 0, f"status={SKIPPED} reason=already_running"
        with _session() as db:
            if not notify.is_trading_day(db, self.today):
                return 0, f"status={SKIPPED} reason=non_trading_day"
            now = self.clock()
            if self.args.trigger == "scheduler" and not in_run_window(now):
                return 0, f"status={SKIPPED} reason=too_late at={now:%H:%M}"
            missing = self._missing()
            if missing:
                return 0, f"status={NOT_CONFIGURED} missing={','.join(missing)}"
            if not self.args.dry_run:
                chat_id = notify.private_chat_id(self.environ[notify.CHAT_ENV])
                if chat_id is None:
                    return 1, f"status={FAILED} reason=chat_not_private"
                if self.send_text is None:
                    token = self.telegram_token
                    self.send_text = lambda text: notify.send(token, chat_id, text)
            tracks = read_tracks(db, self.today, _minute(now, FIRST_POLL))
        return self._watch(tracks)

    def _watch(self, tracks: list[Track]) -> tuple[int, str]:
        listed = sum(1 for item in tracks if LIST in item.sources)
        self.log(
            f"--- targets tracks={len(tracks)} list={listed}"
            f" tracking={sum(1 for item in tracks if TRACKING in item.sources)}"
            f" both={sum(1 for item in tracks if len(item.sources) > 1)}"
            f" symbols={len(symbols_of(tracks))}"
        )
        for item in tracks:
            self.log(
                f"--- target key={item.key} symbol={item.symbol}"
                f" sources={'+'.join(item.sources)} type={item.entry_type}"
                f" entry={_entry(item)} stop={item.invalid} target_1={item.target_1}"
                f" target_2={item.target_2} entered={'yes' if item.entered else 'no'}"
            )
        if not tracks:
            return 0, f"status={SKIPPED} reason=no_targets"
        levels: dict[str, tuple] = {}
        if not self.args.dry_run:
            self.sent = sent_events(self.events)
            levels = day_levels(self.events)
        states = {
            item.key: resumed(item, self.sent.get(item.key, []), levels.get(item.key))
            for item in tracks
        }
        if not self.args.dry_run and self.events.exists():
            # A restarted run: the tracks without a last round recorded take the high and
            # low since the open on their first round (#808 AC-3).
            missing = [
                item.key
                for item in tracks
                if item.key not in levels and not states[item.key].done
            ]
            self.log(
                f"--- levels_restored restored={sum(1 for item in tracks if item.key in levels)}"
                f" missing={','.join(missing) or '-'}"
            )
        symbols, skipped = fugle.cap(symbols_of(tracks))
        if skipped:
            self.log(f"--- capped kept={len(symbols)} skipped={','.join(skipped)}")
            self.deliver(
                OPS,
                "",
                CAPPED,
                notice(
                    CAPPED,
                    self.clock(),
                    total=len(symbols) + len(skipped),
                    limit=fugle.MAX_SYMBOLS,
                    skipped_count=len(skipped),
                    skipped="、".join(skipped),
                ),
            )
        by_symbol: dict[str, list[Track]] = {}
        for item in tracks:
            by_symbol.setdefault(item.symbol, []).append(item)
        start = self.clock()
        deadline = (
            start + timedelta(minutes=self.args.minutes)
            if self.args.dry_run and self.args.minutes
            else None
        )
        due = max(_minute(start, FIRST_POLL), start.replace(second=0, microsecond=0))
        if due < start:
            due += timedelta(minutes=1)
        last = _minute(start, LAST_POLL)
        polls = ok_polls = failed_in_row = 0
        slow = False
        stale: set[str] = set()
        while due <= last and symbols and (deadline is None or due <= deadline):
            self._sleep_until(due)
            woken = self._woken(due, last)
            if woken is None:
                break
            due = woken
            current = _Round(self.clock())
            current.fetched = self._fetch_all(symbols)
            polls += 1
            ok_polls += 1 if current.ok else 0
            self._log_round(current, len(symbols))
            stop = next(
                (item for item in current.fetched if item.outcome == fugle.STOP_DAY),
                None,
            )
            judged: list[str] = []
            for item in current.fetched:
                if item.outcome == fugle.DROP:
                    reason = item.reason or f"http_{item.code}"
                    self.log(f"--- dropped symbol={item.symbol} reason={reason}")
                    symbols = [symbol for symbol in symbols if symbol != item.symbol]
                elif item.outcome == fugle.OK:
                    if item.quote.day != self.today.isoformat():
                        # Another day's quote (a session called off by a typhoon, which
                        # the stored calendar does not have): its high and low are not
                        # today's, so nothing is judged (#802 review item 3).
                        if item.symbol not in stale:
                            stale.add(item.symbol)
                            self.log(
                                f"--- stale_quote symbol={item.symbol}"
                                f" date={item.quote.day or '-'}"
                            )
                        continue
                    for watched in by_symbol.get(item.symbol, []):
                        self._judge(watched, states, item.quote, current.polled)
                        judged.append(watched.key)
            self._record_levels(judged, states)
            if stop is not None:
                why = stop.reason or f"http_{stop.code}"
                self.log(
                    f"--- stopped symbol={stop.symbol} code={stop.code} reason={why}"
                )
                self.deliver(
                    OPS,
                    "",
                    STOPPED_DAY,
                    notice(
                        STOPPED_DAY,
                        current.polled,
                        code=stop.code,
                        why=STOP_WHY.get(why, why),
                    ),
                )
                return 0, (
                    f"status={STOPPED} reason={why} code={stop.code}"
                    f" polls={polls} ok_polls={ok_polls}"
                )
            if current.answered:
                failed_in_row = 0
                if slow:
                    slow = False
                    self.log(f"--- resumed at={current.polled:%H:%M:%S}")
                    self.deliver(OPS, "", RESUMED, notice(RESUMED, current.polled))
            else:
                failed_in_row += 1
                if failed_in_row >= FAILED_ROUNDS_BEFORE_SLOW and not slow:
                    slow = True
                    self.log(
                        f"--- paused at={current.polled:%H:%M:%S}"
                        f" failed_rounds={failed_in_row}"
                    )
                    self.deliver(OPS, "", PAUSED, notice(PAUSED, current.polled))
            due = self._next_due(due, SLOW_MINUTES if slow else 1, last)
        events = sum(len(items) for key, items in self.sent.items() if key != OPS)
        return 0, (
            f"status={FINISHED} polls={polls} ok_polls={ok_polls} events={events}"
            f" symbols={len(symbols)}"
        )

    def _next_due(self, due: datetime, minutes: int, last: datetime) -> datetime:
        """The round after DUE: MINUTES later, or, when the run is behind (a host asleep,
        a slow send, many timeouts), the next whole minute still ahead. The minutes
        passed meanwhile are skipped, not caught up: a stock is asked at most once a
        minute (#802 review 6910820856 item 1), and they are no poll of the day."""

        planned = due + timedelta(minutes=minutes)
        now = self.clock()
        if now < planned:
            return planned
        ahead = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        self._skipped(planned, min(ahead - timedelta(minutes=1), last))
        return ahead

    def _skipped(self, first: datetime, to: datetime) -> None:
        if first <= to:
            self.log(
                f"--- skipped_rounds from={first:%H:%M} to={to:%H:%M}"
                f" minutes={round((to - first).total_seconds() / 60) + 1}"
            )

    def _woken(self, due: datetime, last: datetime) -> datetime | None:
        """The round's minute after the sleep: DUE, or the minute the run woke in when it
        slept past DUE (a host asleep); the minutes between are skipped. None past LAST."""

        minute = self.clock().replace(second=0, microsecond=0)
        if minute <= due:
            return due
        self._skipped(due, min(minute - timedelta(minutes=1), last))
        return minute if minute <= last else None

    def _judge(
        self, watched: Track, states: dict[str, State], quote, polled: datetime
    ) -> None:
        events, states[watched.key] = judge(watched, states[watched.key], quote)
        for event in events:
            self.deliver(
                watched.key,
                watched.symbol,
                event,
                message(watched, event, quote, polled),
            )

    def _record_levels(self, keys: list[str], states: dict[str, State]) -> None:
        """One jsonl line of the round: the high, low and last trade of each track of
        KEYS judged on it and still watched, which a restarted run reads back
        (``day_levels``, #808 AC-3). Not in a dry run (it writes no file)."""

        levels = {
            key: {"high": state.high, "low": state.low, "last": state.last}
            for key in keys
            if (state := states[key]).high is not None and not state.done
        }
        if self.args.dry_run or not levels:
            return
        line = json.dumps(
            {"at": self.clock().isoformat(timespec="seconds"), LEVELS: levels},
            ensure_ascii=False,
        )
        with open(self.events, "a", encoding="utf-8", newline="") as handle:
            handle.write(line + "\n")

    def _sleep_until(self, due: datetime) -> None:
        while True:
            left = (due - self.clock()).total_seconds()
            if left <= 0:
                return
            self.sleep(min(left, 30.0))

    def _fetch_all(self, symbols: list[str]) -> list[fugle.Fetched]:
        if self.workers <= 1 or len(symbols) <= 1:
            return [self.fetch(symbol) for symbol in symbols]
        with ThreadPoolExecutor(max_workers=min(self.workers, len(symbols))) as pool:
            return list(pool.map(self.fetch, symbols))

    def _log_round(self, current: _Round, asked: int) -> None:
        codes: dict[str, int] = {}
        for item in current.fetched:
            codes[item.code] = codes.get(item.code, 0) + 1
        ms = [item.ms for item in current.fetched]
        received = current.polled
        lags = [
            (received - item.quote.last_updated).total_seconds()
            for item in current.fetched
            if item.quote is not None and item.quote.last_updated is not None
        ]
        self.log(
            f"--- poll at={current.polled:%H:%M:%S} symbols={asked} ok={current.ok}"
            f" codes={','.join(f'{code}:{count}' for code, count in sorted(codes.items()))}"
            f" ms_median={_median(ms)} ms_max={max(ms) if ms else '-'}"
            f" lag_median={_median(lags)} lag_max={f'{max(lags):.0f}' if lags else '-'}"
        )

    def _remove_old_logs(self) -> None:
        cutoff = time.time() - LOG_RETENTION_DAYS * 86400
        for pattern in (f"{LOG_PREFIX}-*.log", f"{LOG_PREFIX}-*.jsonl"):
            for path in self.log_dir.glob(pattern):
                try:
                    if path.is_file() and path.stat().st_mtime < cutoff:
                        path.unlink()
                except OSError:
                    pass


def run(args: argparse.Namespace) -> int:
    """``worker.cli intraday``."""

    problem = job.platform_problem("worker.intraday")
    if problem and not args.dry_run:
        print(problem, file=sys.stderr)
        return job.PLATFORM_EXIT
    return Run(args).run()
