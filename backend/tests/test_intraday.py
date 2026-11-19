"""The intraday alerts (backend/worker/intraday.py, backend/worker/fugle.py, #801).

The fixture is four stocks of the 2026-11-16 today list as #756 measured them (AC-2,
comment 6906081956), rewritten in the shape of Fugle's intraday quote: 2618 a breakout,
3374 under its stop before any entry, 8099 opening locked at the limit up above target
one, 3162 a pullback opening in its zone and then under its stop. No test asks the real
API: the HTTP is a fake opener, the clock a fake one. The runs take fcntl locks: Linux
only, like worker.job.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import socket
import sys
import urllib.error
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, enable_sqlite_foreign_keys
from app.domain import CANDIDATE_SCORE_READ_VERSIONS
from app.models import (
    CandidateRun,
    DailyCandidate,
    Instrument,
    RawPayload,
    Signal,
    TrackingPlan,
    TradingCalendarDay,
)
from worker import fugle, intraday, job

ON_LINUX = sys.platform.startswith("linux")
linux_only = pytest.mark.skipif(not ON_LINUX, reason="fcntl lock: Linux only (#333)")
TAIPEI = job.TAIPEI
FIXTURE = Path(__file__).parent / "fixtures" / "fugle_intraday" / "20261116.json"
DAY = json.loads(FIXTURE.read_text(encoding="utf-8"))
MONDAY = date(2026, 11, 16)
FRIDAY = date(2026, 11, 13)
ORDER_WORDS = ("買進", "賣出", "出場")


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _poll(index: int) -> tuple[datetime, dict[str, dict]]:
    poll = DAY["polls"][index]
    return _at(poll["at"]), poll["quotes"]


def _quote(index: int, symbol: str) -> fugle.Quote:
    quote, reason = fugle.parse(symbol, _poll(index)[1][symbol])
    assert quote is not None, reason
    return quote


def _track(symbol: str, sources=(intraday.LIST,), *, entered=False, **levels):
    values = {**DAY["levels"][symbol], **levels}
    made = intraday.track(
        f"signal:{symbol}",
        symbol,
        values["name"],
        sources,
        SimpleNamespace(**values),
        entered=entered,
    )
    assert made is not None
    return made


def _day(symbol: str, polls=(0, 1, 2), state=None, **levels) -> list[list[str]]:
    """The events of SYMBOL at each of POLLS of the fixture, in order."""

    watched = _track(symbol, **levels)
    state = state or intraday.State(entered=watched.entered)
    out = []
    for index in polls:
        events, state = intraday.judge(watched, state, _quote(index, symbol))
        out.append(events)
    return out


# --- AC-1: the Fugle adapter ----------------------------------------------------------


def test_the_quote_fields_are_read_as_the_alerts_need_them():
    quote = _quote(1, "2618")
    assert (quote.high, quote.low, quote.open) == (47.8, 47.8, 47.8)
    assert quote.last_price == 47.8
    assert quote.last_time.astimezone(TAIPEI).strftime("%H:%M:%S") == "09:00:30"
    assert quote.last_updated.astimezone(TAIPEI).strftime("%H:%M:%S") == "09:00:55"
    assert (quote.bid, quote.ask) == (47.75, 47.8)
    assert not quote.is_trial and not quote.locked_up and not quote.locked_down


def test_the_limit_flags_make_a_locked_quote():
    up = _quote(1, "8099")
    assert up.locked_up and not up.locked_down
    assert (up.bid, up.ask) == (200.0, None)
    down = _quote(2, "3374")
    assert down.locked_down and not down.locked_up
    assert (down.bid, down.ask) == (None, 467.5)
    # At the limit price without the bid there: not locked.
    body = dict(_poll(1)[1]["8099"], isLimitUpBid=False)
    assert not fugle.parse("8099", body)[0].locked_up


def test_a_trial_quote_is_parsed_and_never_judged():
    """isTrial: no lastTrade, high or low needed, and nothing judged (8099's trial has
    a high and a low at its limit up)."""

    for symbol in DAY["levels"]:
        quote, reason = fugle.parse(symbol, _poll(0)[1][symbol])
        assert quote is not None and quote.is_trial and reason == ""
        watched = _track(symbol)
        state = intraday.State()
        assert intraday.judge(watched, state, quote) == ([], state)


@pytest.mark.parametrize(
    "drop, reason",
    [
        (("highPrice",), "malformed:highPrice"),
        (("lowPrice",), "malformed:lowPrice"),
        (("lastTrade",), "malformed:lastTrade"),
        (("highPrice", "lowPrice"), "malformed:highPrice,lowPrice"),
    ],
)
def test_a_quote_without_its_fields_is_malformed(drop, reason):
    body = {k: v for k, v in _poll(2)[1]["2618"].items() if k not in drop}
    assert fugle.parse("2618", body) == (None, reason)
    fetched = fugle.Fetched("2618", "200", 5, reason=reason)
    assert fetched.outcome == fugle.DROP


def test_a_stock_not_traded_yet_is_asked_again():
    body = {"symbol": "6140", "isTrial": False, "total": {"tradeVolume": 0}}
    assert fugle.parse("6140", body) == (None, fugle.NO_TRADE)
    assert (
        fugle.Fetched("6140", "200", 5, reason=fugle.NO_TRADE).outcome == fugle.NO_TRADE
    )


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def _opener(answer):
    """A fake urlopen: ANSWER is a body (dict or bytes), or an exception to raise."""

    seen = []

    def opener(request, timeout):
        seen.append((request, timeout))
        if isinstance(answer, BaseException):
            raise answer
        data = answer if isinstance(answer, bytes) else json.dumps(answer).encode()
        return _Response(data)

    opener.seen = seen
    return opener


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://example.invalid", code, "x", {}, io.BytesIO(b"{}")
    )


@pytest.mark.parametrize(
    "answer, code, outcome, reason",
    [
        (_poll(1)[1]["2618"], "200", fugle.OK, ""),
        (_http_error(401), "401", fugle.STOP_DAY, "key_invalid"),
        (_http_error(403), "403", fugle.STOP_DAY, "plan_not_allowed"),
        (_http_error(429), "429", fugle.STOP_DAY, "rate_limited"),
        (_http_error(404), "404", fugle.DROP, ""),
        (_http_error(502), "502", fugle.SKIP, ""),
        (_http_error(500), "500", fugle.SKIP, ""),
        (
            urllib.error.URLError(socket.timeout("timed out")),
            "timeout",
            fugle.SKIP,
            "timeout",
        ),
        (TimeoutError("read timed out"), "timeout", fugle.SKIP, "timeout"),
        (
            urllib.error.URLError(ConnectionRefusedError()),
            "network",
            fugle.SKIP,
            "network:ConnectionRefusedError",
        ),
        (b"<html>", "200", fugle.DROP, "malformed:json"),
        (
            {"symbol": "2618", "isTrial": False, "openPrice": 47.8},
            "200",
            fugle.DROP,
            "malformed:highPrice,lowPrice,lastTrade",
        ),
    ],
)
def test_each_answer_has_one_outcome(answer, code, outcome, reason):
    opener = _opener(answer)
    fetched = fugle.fetch("2618", "the-key", opener=opener)
    assert (fetched.code, fetched.outcome, fetched.reason) == (code, outcome, reason)
    request, timeout = opener.seen[0]
    assert request.full_url == f"{fugle.API_BASE}/2618"
    assert request.get_header("X-api-key") == "the-key"
    assert timeout == fugle.TIMEOUT_SECONDS == 10.0


def test_at_most_fifty_stocks_a_minute_in_their_order():
    symbols = [f"{n:04d}" for n in range(1000, 1055)]
    kept, skipped = fugle.cap(symbols)
    assert kept == symbols[:50] and skipped == symbols[50:]
    assert fugle.cap(symbols[:50]) == (symbols[:50], [])


# --- AC-2: the rules ------------------------------------------------------------------


def test_2618_breaks_out_at_the_open_and_nothing_more_by_10_03():
    assert _day("2618") == [[], [intraday.ENTRY], []]


def test_3374_falls_under_its_stop_before_any_entry():
    """High 493.5 never reached 519; low 467.5 under 480.18: the entry no longer stands,
    and the stock ends for the day."""

    assert _day("3374") == [[], [], [intraday.STOP_BEFORE_ENTRY]]
    watched = _track("3374")
    state = intraday.State()
    for index in (1, 2):
        _, state = intraday.judge(watched, state, _quote(index, "3374"))
    assert state.done
    assert intraday.judge(watched, state, _quote(2, "3374"))[0] == []


def test_8099_opens_locked_above_target_one_and_is_no_entry():
    """Open 200 at the limit up, over the entry 182 and target one 198.63: gap_above_target,
    not an entry nor a target, and the stock ends for the day."""

    assert _day("8099") == [[], [intraday.GAP_ABOVE_TARGET], []]


def test_3162_enters_its_zone_and_then_falls_under_its_stop():
    assert _day("3162") == [[], [intraday.ENTRY], [intraday.STOP]]
    # A run that starts at 10:03 (its first round): the open, 74.1, was in the zone, so
    # the entry came before the stop within that round.
    assert _day("3162", polls=(2,)) == [[intraday.ENTRY, intraday.STOP]]


def test_a_breakout_whose_entry_and_stop_meet_in_one_round_has_no_known_order():
    """2618 with its entry lifted to 48.5: open 47.8 under it, high 48.95 over it and low
    47.7 under a stop of 47.75 in the same round."""

    events = _day("2618", polls=(2,), breakout_price=48.5, invalid_price=47.75)
    assert events == [[intraday.ENTRY_AND_STOP]]


def test_a_gap_under_the_stop_is_no_entry():
    """3162's open 74.1 in a wider zone is an entry; with its stop moved to 74.5 the open
    is under it: gap_below_invalid."""

    events = _day("3162", polls=(1,), pullback_low=60.0, invalid_price=59.0)
    assert events == [[intraday.ENTRY]]
    events = _day(
        "3162", polls=(1,), pullback_low=73.0, pullback_high=75.0, invalid_price=74.5
    )
    assert events == [[intraday.GAP_BELOW_INVALID]]


def _custom(high, low, *, open_=None, last=None, trial=False) -> fugle.Quote:
    return fugle.Quote(
        symbol="9999",
        high=high,
        low=low,
        open=open_ if open_ is not None else low,
        last_price=last or high,
        last_time=datetime(2026, 11, 16, 2, 0, tzinfo=timezone.utc),
        is_trial=trial,
    )


BREAKOUT = dict(
    entry_type="breakout",
    breakout_price=100.0,
    pullback_low=None,
    pullback_high=None,
    invalid_price=95.0,
    target_1=110.0,
    target_2=120.0,
)


def _watched(entered=False, **levels):
    return intraday.track(
        "plan:1",
        "9999",
        "測試",
        (intraday.TRACKING,),
        SimpleNamespace(**{**BREAKOUT, **levels}),
        entered=entered,
    )


def _rounds(watched, quotes) -> list[list[str]]:
    state = intraday.State(entered=watched.entered)
    out = []
    for quote in quotes:
        events, state = intraday.judge(watched, state, quote)
        out.append(events)
    return out


def test_a_level_counts_once_when_the_new_high_reaches_it():
    quotes = [
        _custom(99.0, 98.0),
        _custom(100.5, 98.0),  # the entry
        _custom(101.0, 98.0),  # still over it: no second entry
        _custom(110.0, 98.0),  # target one
        _custom(112.0, 98.0),
        _custom(120.0, 98.0),  # target two, then the stock ends
        _custom(121.0, 90.0),
    ]
    assert _rounds(_watched(), quotes) == [
        [],
        [intraday.ENTRY],
        [],
        [intraday.TARGET_1],
        [],
        [intraday.TARGET_2],
        [],
    ]


def test_the_stop_and_target_one_new_in_one_round_have_no_known_order():
    quotes = [_custom(101.0, 99.0), _custom(111.0, 94.0)]
    assert _rounds(_watched(), quotes) == [
        [intraday.ENTRY],
        [intraday.STOP_AND_TARGET],
    ]


def test_a_triggered_plan_counts_its_stop_and_target_from_the_start():
    """A triggered plan has entered: a low under the stop is the stop, not
    stop_before_entry, and no entry is told."""

    assert _rounds(_watched(entered=True), [_custom(99.0, 94.0)]) == [[intraday.STOP]]
    assert _rounds(_watched(entered=True), [_custom(110.0, 99.0)]) == [
        [intraday.TARGET_1]
    ]


def test_a_pending_plan_needs_its_entry_first():
    assert _rounds(_watched(), [_custom(99.0, 94.0)]) == [[intraday.STOP_BEFORE_ENTRY]]
    assert _rounds(_watched(), [_custom(99.0, 96.0), _custom(99.5, 96.0)]) == [[], []]


def test_after_target_one_only_target_two_is_watched():
    quotes = [_custom(110.0, 99.0, open_=99.0), _custom(111.0, 90.0)]
    assert _rounds(_watched(entered=True), quotes) == [[intraday.TARGET_1], []]
    # Without a target two the stock ends at target one.
    quotes = [_custom(110.0, 99.0), _custom(121.0, 90.0)]
    assert _rounds(_watched(entered=True, target_2=None), quotes) == [
        [intraday.TARGET_1],
        [],
    ]


def test_a_restarted_run_goes_on_from_the_events_sent():
    watched = _watched()
    state = intraday.resumed(watched, [intraday.ENTRY])
    assert state.entered and not state.done
    assert intraday.judge(watched, state, _custom(101.0, 94.0))[0] == [intraday.STOP]
    assert intraday.resumed(watched, [intraday.STOP_BEFORE_ENTRY]).done
    after_target = intraday.resumed(watched, [intraday.ENTRY, intraday.TARGET_1])
    assert intraday.judge(watched, after_target, _custom(121.0, 90.0))[0] == [
        intraday.TARGET_2
    ]


def test_incomplete_levels_are_no_track():
    assert _watched(invalid_price=None) is None
    assert _watched(breakout_price=111.0) is None  # over target one
    assert _watched(entry_type="conditional") is None
    assert (
        _watched(entry_type="pullback", pullback_low=101.0, pullback_high=99.0) is None
    )


# --- AC-3: the messages ---------------------------------------------------------------


def test_the_issue_example_reads_as_written():
    watched = intraday.track(
        "signal:1",
        "1802",
        "台玻",
        (intraday.LIST,),
        SimpleNamespace(
            **{
                **BREAKOUT,
                "breakout_price": 81.7,
                "invalid_price": 78.0,
                "target_1": 88.0,
            }
        ),
    )
    quote = fugle.Quote(
        symbol="1802",
        high=81.9,
        low=80.5,
        open=80.6,
        last_price=81.8,
        last_time=datetime(2026, 11, 16, 10, 12, 5, tzinfo=TAIPEI),
        is_trial=False,
    )
    polled = datetime(2026, 11, 16, 10, 12, 40, tzinfo=TAIPEI)
    assert intraday.message(watched, intraday.ENTRY, quote, polled) == (
        "1802 台玻 觸及規則進場價 81.70（10:12 前後；10:12:05 成交 81.80）\n來源：今日名單"
    )


def _fixture_message(symbol, index, event, **track):
    polled = _poll(index)[0]
    return intraday.message(
        _track(symbol, **track), event, _quote(index, symbol), polled
    )


def test_the_fixture_days_messages():
    assert _fixture_message("2618", 1, intraday.ENTRY) == (
        "2618 長榮航 觸及規則進場價 47.75（09:01 前後；09:00:30 成交 47.80）\n來源：今日名單"
    )
    assert _fixture_message("3162", 1, intraday.ENTRY).startswith(
        "3162 精確 觸及規則進場區 72.89～76.94（09:01 前後；09:00:30 成交 74.10）"
    )
    assert _fixture_message("3162", 2, intraday.STOP).startswith(
        "3162 精確 觸及停損 70.86（10:03 前後；10:02:54 成交 67.60）"
    )
    both = _fixture_message(
        "2618", 1, intraday.ENTRY, sources=(intraday.LIST, intraday.TRACKING)
    )
    assert both.endswith("\n來源：今日名單、我的追蹤")


def test_a_locked_limit_says_so_and_what_side_is_missing():
    gap = _fixture_message("8099", 1, intraday.GAP_ABOVE_TARGET)
    assert gap.splitlines() == [
        "8099 大世科 觸及規則進場價 182.00，但開盤 200.00 已在目標一 198.63 以上，"
        "依規則不算進場，今天這檔不再通知（09:01 前後；09:00:30 成交 200.00）",
        "漲停鎖住（委買 200.00，委賣取不到）",
        "來源：今日名單",
    ]
    stop = _fixture_message("3374", 2, intraday.STOP_BEFORE_ENTRY)
    assert stop.splitlines()[:2] == [
        "3374 精材 跌破停損 480.18，進場條件不再成立（10:03 前後；10:02:55 成交 467.50）",
        "跌停鎖住（委買取不到，委賣 467.50）",
    ]
    # Not locked: no such line.
    assert "鎖住" not in _fixture_message("2618", 1, intraday.ENTRY)


def test_a_quote_without_a_trade_price_says_so():
    quote = fugle.Quote("9999", 101.0, 99.0, 99.0, None, None, False)
    text = intraday.message(_watched(), intraday.ENTRY, quote, _poll(1)[0])
    assert "（09:01 前後；成交價取不到）" in text


def test_no_template_and_no_message_gives_an_order():
    for name, template in intraday.TEMPLATES.items():
        for word in ORDER_WORDS:
            assert word not in template, (name, word)
    events = [
        intraday.ENTRY,
        intraday.STOP,
        intraday.TARGET_1,
        intraday.TARGET_2,
        intraday.STOP_BEFORE_ENTRY,
        intraday.GAP_ABOVE_TARGET,
        intraday.GAP_BELOW_INVALID,
        intraday.STOP_AND_TARGET,
        intraday.ENTRY_AND_STOP,
    ]
    for symbol in DAY["levels"]:
        for event in events:
            text = _fixture_message(symbol, 2, event)
            assert not any(word in text for word in ORDER_WORDS), text
    polled = _poll(2)[0]
    notices = [
        intraday.notice(intraday.PAUSED, polled),
        intraday.notice(intraday.RESUMED, polled),
        intraday.notice(intraday.STOPPED_DAY, polled, code="401", why="API key 無效"),
        intraday.notice(
            intraday.CAPPED, polled, total=55, limit=50, skipped_count=5, skipped="a"
        ),
    ]
    assert notices[0] == "盤中報價暫停（來源回應失敗），10:03 起；改為每 5 分鐘讀一次"
    assert notices[1] == "盤中報價恢復，10:03 起"
    for text in notices:
        assert not any(word in text for word in ORDER_WORDS), text


def test_names_are_escaped_for_telegrams_html():
    watched = intraday.track(
        "plan:1", "9999", "A&B<C>", (intraday.TRACKING,), SimpleNamespace(**BREAKOUT)
    )
    text = intraday.message(watched, intraday.ENTRY, _custom(101.0, 99.0), _poll(1)[0])
    assert text.startswith("9999 A&amp;B&lt;C&gt; 觸及")


# --- the stocks of the day ------------------------------------------------------------


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def _utc(day: date, hour: int, minute: int) -> datetime:
    """A Taipei time as the models store it (UTC, naive)."""

    moment = datetime(day.year, day.month, day.day, hour, minute, tzinfo=TAIPEI)
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def _listed(db, symbols=tuple(DAY["levels"]), execution=MONDAY):
    """The today list of Friday 11/13: one candidate per symbol in rank order."""

    run = CandidateRun(
        trading_date=FRIDAY,
        score_version=CANDIDATE_SCORE_READ_VERSIONS[0],
        computed_at=_utc(FRIDAY, 21, 40),
    )
    db.add(run)
    db.flush()
    signals = {}
    for rank, symbol in enumerate(symbols, start=1):
        levels = DAY["levels"][symbol]
        instrument = Instrument(
            exchange="TPEx" if symbol != "2618" else "TWSE",
            symbol=symbol,
            name=levels["name"],
            status="active",
        )
        db.add(instrument)
        db.flush()
        signal = Signal(
            signal_key=f"analysis-{symbol}-2026-11-13",
            signal_date=FRIDAY,
            instrument_id=instrument.id,
            status="conditional",
            entry_type=levels["entry_type"],
            breakout_price=levels["breakout_price"],
            pullback_low=levels["pullback_low"],
            pullback_high=levels["pullback_high"],
            invalid_price=levels["invalid_price"],
            target_1=levels["target_1"],
            target_2=levels["target_2"],
            earliest_execution_date=execution,
        )
        db.add(signal)
        db.flush()
        db.add(
            DailyCandidate(
                candidate_run_id=run.id,
                trading_date=FRIDAY,
                instrument_id=instrument.id,
                signal_id=signal.id,
                strategy="breakout_v3",
                score_version=run.score_version,
                total_score=1.0,
                weight_coverage=1.0,
                rank=rank,
                data_as_of=FRIDAY,
            )
        )
        signals[symbol] = signal
    db.commit()
    return signals


def _plan(db, signal, *, status="pending", created=None, cancelled=None, **levels):
    values = {
        "entry_type": signal.entry_type,
        "breakout_price": signal.breakout_price,
        "pullback_low": signal.pullback_low,
        "pullback_high": signal.pullback_high,
        "invalid_price": signal.invalid_price,
        "target_1": signal.target_1,
        "target_2": signal.target_2,
        **levels,
    }
    plan = TrackingPlan(
        instrument_id=signal.instrument_id,
        signal_id=signal.id,
        source_kind="candidate",
        strategy="breakout_v3",
        tracking_version="plan_tracking_v2",
        plan_date=signal.signal_date,
        earliest_execution_date=signal.earliest_execution_date,
        status=status,
        created_at=created or _utc(FRIDAY, 22, 0),
        cancelled_at=cancelled,
        **values,
    )
    db.add(plan)
    db.commit()
    return plan


def _other_signal(db, symbol, name, day=date(2026, 11, 3)):
    instrument = Instrument(exchange="TWSE", symbol=symbol, name=name, status="active")
    db.add(instrument)
    db.flush()
    signal = Signal(
        signal_key=f"analysis-{symbol}-{day}",
        signal_date=day,
        instrument_id=instrument.id,
        status="conditional",
        **BREAKOUT,
        earliest_execution_date=day + timedelta(days=1),
    )
    db.add(signal)
    db.commit()
    return signal


NINE = datetime(2026, 11, 16, 9, 0, tzinfo=TAIPEI)


def test_the_today_list_in_rank_order_with_the_signals_own_levels(db):
    _listed(db)
    tracks = intraday.read_tracks(db, MONDAY, NINE)
    assert [t.symbol for t in tracks] == ["2618", "3374", "8099", "3162"]
    assert all(t.sources == (intraday.LIST,) for t in tracks)
    pullback = tracks[3]
    assert (pullback.zone_low, pullback.zone_high, pullback.invalid) == (
        72.89,
        76.94,
        70.86,
    )
    assert (tracks[0].breakout, tracks[0].target_1, tracks[0].target_2) == (
        47.75,
        50.05,
        52.06,
    )


def test_only_the_signals_executable_today_are_the_today_list(db):
    _listed(db, execution=date(2026, 11, 17))
    assert intraday.read_tracks(db, MONDAY, NINE) == []


def test_a_listed_stock_also_tracked_is_one_track_with_both_sources(db):
    signals = _listed(db)
    _plan(db, signals["2618"])
    tracks = intraday.read_tracks(db, MONDAY, NINE)
    assert [t.symbol for t in tracks] == ["2618", "3374", "8099", "3162"]
    assert tracks[0].sources == (intraday.LIST, intraday.TRACKING)
    assert tracks[0].key == f"signal:{signals['2618'].id}"


def test_the_open_plans_after_the_list_by_creation(db):
    _listed(db, symbols=("2618",))
    older = _other_signal(db, "2330", "台積電")
    newer = _other_signal(db, "1101", "台泥")
    triggered = _plan(
        db, newer, status="triggered", created=_utc(date(2026, 11, 5), 20, 0)
    )
    pending = _plan(db, older, created=_utc(date(2026, 11, 4), 20, 0))
    tracks = intraday.read_tracks(db, MONDAY, NINE)
    assert [(t.symbol, t.key, t.entered) for t in tracks] == [
        ("2618", tracks[0].key, False),
        ("2330", f"plan:{pending.id}", False),
        ("1101", f"plan:{triggered.id}", True),
    ]
    assert tracks[1].sources == (intraday.TRACKING,)


def test_closed_cancelled_and_intraday_plans_are_left_out(db):
    signal = _other_signal(db, "2330", "台積電")
    _plan(db, signal, status="target_hit")
    other = _other_signal(db, "1101", "台泥")
    _plan(db, other, cancelled=_utc(MONDAY, 8, 0))
    late = _other_signal(db, "2454", "聯發科")
    # Added during the session: not watched that day.
    _plan(db, late, created=_utc(MONDAY, 9, 30))
    assert intraday.read_tracks(db, MONDAY, NINE) == []


# --- AC-4: the run --------------------------------------------------------------------


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start
        self.slept = 0.0

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept += seconds
        self.now += timedelta(seconds=seconds)


def _fixture_fetch(clock):
    """The fixture's quote of the latest poll at or before the clock, 120 ms each."""

    def fetch(symbol):
        latest = max(
            (
                index
                for index, poll in enumerate(DAY["polls"])
                if _at(poll["at"]) <= clock.now
            ),
            default=0,
        )
        body = DAY["polls"][latest]["quotes"][symbol]
        quote, reason = fugle.parse(symbol, body)
        return fugle.Fetched(symbol, "200", 120, quote=quote, reason=reason)

    return fetch


def _closed(db, day: date) -> None:
    raw = RawPayload(
        source="twse",
        endpoint="fixture-holiday-schedule",
        sha256=f"{day:%Y%m%d}".ljust(64, "0"),
        data_as_of=day.isoformat(),
    )
    db.add(raw)
    db.flush()
    db.add(
        TradingCalendarDay(
            exchange="TWSE",
            calendar_date=day,
            year=day.year,
            kind="closed",
            name="放假",
            description="",
            source="twse_holiday_schedule",
            collected_at=datetime(2026, 1, 1),
            raw_payload_id=raw.id,
        )
    )
    db.commit()


ENV = {
    fugle.KEY_ENV: "fugle-secret-key",
    "TELEGRAM_BOT_TOKEN": "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "TELEGRAM_CHAT_ID": "42",
}


@pytest.fixture
def env(tmp_path, monkeypatch, db):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    monkeypatch.setenv("STOCK_DATA_DIR", str(data))
    monkeypatch.setattr(intraday, "_session", lambda: contextlib.nullcontext(db))
    return SimpleNamespace(data=data, logs=data / "logs", db=db)


def _args(*argv):
    parser = argparse.ArgumentParser()
    intraday.add_arguments(parser)
    args = parser.parse_args(list(argv))
    assert intraday.argument_problem(args) is None
    return args


def _run(env, start="08:59:00", *, environ=ENV, fetch=None, mode="--send", extra=()):
    clock = Clock(_at(f"2026-11-16T{start}+08:00"))
    sent: list[str] = []

    def send(text):
        sent.append(text)
        return {"status": "sent", "attempts": 1, "message_id": str(len(sent))}

    out = io.StringIO()
    runner = intraday.Run(
        _args(mode, "--trigger", "scheduler", "--log-dir", str(env.logs), *extra),
        clock=clock,
        sleep=clock.sleep,
        fetch=fetch(clock) if fetch else _fixture_fetch(clock),
        send=send,
        environ=environ,
        out=out,
        workers=1,
    )
    code = runner.run()
    return SimpleNamespace(code=code, sent=sent, out=out.getvalue(), clock=clock)


def _log(env) -> str:
    return intraday.log_path(env.logs, MONDAY).read_text(encoding="utf-8")


def _lines(env) -> list[dict]:
    path = intraday.events_path(env.logs, MONDAY)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _jsonl(env) -> list[dict]:
    """The jsonl's events (the ``levels`` lines of #808 AC-3 left out)."""

    return [record for record in _lines(env) if intraday.LEVELS not in record]


@linux_only
def test_a_trading_day_polls_every_minute_from_0900_to_1330_and_ends(env):
    _listed(env.db)
    result = _run(env)
    assert result.code == 0
    log = _log(env)
    lines = log.splitlines()
    assert lines[0].startswith("===== 2026-11-16T08:59:00+08:00 start job=intraday")
    assert "trigger=scheduler date=2026-11-16 configured=yes dry_run=no" in lines[0]
    assert lines[1] == "--- targets tracks=4 list=4 tracking=0 both=0 symbols=4"
    polls = [line for line in lines if line.startswith("--- poll ")]
    assert len(polls) == intraday.POLLS_PER_DAY == 271
    assert polls[0].startswith("--- poll at=09:00:00 symbols=4 ok=4 codes=200:4")
    assert polls[-1].startswith("--- poll at=13:30:00 ")
    # The milliseconds and the lag of lastUpdated (09:01: 09:00:55, 5 seconds).
    assert polls[1] == (
        "--- poll at=09:01:00 symbols=4 ok=4 codes=200:4 ms_median=120 ms_max=120"
        " lag_median=5 lag_max=5"
    )
    assert lines[-2] == (
        "--- result status=finished polls=271 ok_polls=271 events=5 symbols=4"
    )
    assert lines[-1].startswith("===== 2026-11-16T13:30:00+08:00 end exit=0")
    events = [(r["symbol"], r["event"]) for r in _jsonl(env)]
    assert events == [
        ("2618", "entry"),
        ("8099", "gap_above_target"),
        ("3162", "entry"),
        ("3374", "stop_before_entry"),
        ("3162", "stop"),
    ]
    assert all(r["status"] == "sent" for r in _jsonl(env))
    assert len(result.sent) == 5
    assert "--- event key=" in log and "event=gap_above_target status=sent" in log
    # The key and the token never reach the record.
    for text in (
        log,
        intraday.events_path(env.logs, MONDAY).read_text("utf-8"),
        result.out,
    ):
        assert ENV[fugle.KEY_ENV] not in text
        assert ENV["TELEGRAM_BOT_TOKEN"] not in text


@linux_only
def test_a_restarted_run_reads_the_days_events_and_sends_nothing_twice(env):
    _listed(env.db)
    first = _run(env)
    assert len(first.sent) == 5
    # Recreated at 11:00: the same day, the same stocks, nothing new.
    again = _run(env, start="11:00:10")
    assert again.sent == []
    assert intraday.day_results(env.logs, MONDAY) == [intraday.FINISHED] * 2
    assert len(_jsonl(env)) == 5
    # Of the tracks still watched (2618; 3374, 8099 and 3162 ended), all go on from
    # their last round: restored + missing is the tracks asked and not done.
    assert "--- levels_restored restored=1 missing=-" in _log(env)


@linux_only
def test_a_run_killed_midway_goes_on_without_resending(env):
    _listed(env.db)
    # Killed after the 09:01 round: three events sent, the jsonl has them.
    _run(env, extra=())  # a full day first, to fill the jsonl
    records = _jsonl(env)
    path = intraday.events_path(env.logs, MONDAY)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records[:3]),
        encoding="utf-8",
    )
    again = _run(env, start="10:30:00")
    assert len(again.sent) == 2
    assert again.sent[0].startswith("3374 精材 跌破停損 480.18")
    assert again.sent[1].startswith("3162 精確 觸及停損 70.86")
    assert len(_jsonl(env)) == 5
    # The cut jsonl had no levels line: the tracks still watched are logged.
    assert "--- levels_restored restored=0 missing=" in _log(env)


def _pullback_after_its_high(clock):
    """3162 (zone 72.89～76.94, stop 70.86, target one 81.37): it opens at 79, reaches 82
    (over target one) by 13:25 before any entry, then from 13:26 falls into the zone (the
    entry); its high since the open stays 82, no new high."""

    def fetch(symbol):
        before = clock.now < _at("2026-11-16T13:26:00+08:00")
        low, last = (78.0, 78.5) if before else (75.0, 76.0)
        body = dict(
            DAY["polls"][2]["quotes"][symbol],
            openPrice=79.0,
            highPrice=82.0,
            lowPrice=low,
            lastPrice=last,
            lastTrade={"price": last, "size": 1, "time": 1794806700000000},
        )
        quote, reason = fugle.parse(symbol, body)
        return fugle.Fetched(symbol, "200", 10, quote=quote, reason=reason)

    return fetch


@linux_only
def test_a_restarted_run_goes_on_from_the_last_rounds_high_and_low(env):
    """#808 AC-3: a pullback entered after its high of the day over target one. Restarted,
    its first round compares with the last round's high (82, over target one already),
    not the open's (none): no 觸及目標一."""

    _listed(env.db, symbols=("3162",))
    first = _run(env, start="13:25:00", fetch=_pullback_after_its_high)
    assert [r["event"] for r in _jsonl(env)] == [intraday.ENTRY]
    assert len(first.sent) == 1
    key = _jsonl(env)[0]["key"]
    levels = [r for r in _lines(env) if intraday.LEVELS in r]
    assert len(levels) == 6  # 13:25 to 13:30, one line a round
    rules = ["pullback", None, 72.89, 76.94, 70.86, 81.37, 87.03]
    assert levels[-1][intraday.LEVELS] == {
        key: {"high": 82.0, "low": 75.0, "last": 76.0, "levels": rules}
    }
    assert intraday.day_levels(intraday.events_path(env.logs, MONDAY)) == {
        key: intraday.Saved(82.0, 75.0, 76.0, tuple(rules))
    }
    # The levels lines are no event (sent_events) and no result (day_results).
    assert intraday.sent_events(intraday.events_path(env.logs, MONDAY)) == {
        key: [intraday.ENTRY]
    }
    assert intraday.day_results(env.logs, MONDAY) == [intraday.FINISHED]

    again = _run(env, start="13:28:10", fetch=_pullback_after_its_high)
    assert again.sent == []
    assert [r["event"] for r in _jsonl(env)] == [intraday.ENTRY]
    assert "--- levels_restored restored=1 missing=-" in _log(env)


@linux_only
def test_without_the_last_rounds_levels_the_first_round_takes_the_open(env):
    """A jsonl of the events only (a run of before #808): the restarted run goes on as it
    did, from the high and low since the open, and says which tracks had no levels."""

    _listed(env.db, symbols=("3162",))
    _run(env, start="13:25:00", fetch=_pullback_after_its_high)
    path = intraday.events_path(env.logs, MONDAY)
    events = _jsonl(env)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in events),
        encoding="utf-8",
    )
    again = _run(env, start="13:28:10", fetch=_pullback_after_its_high)
    assert [text.split("（")[0] for text in again.sent] == [
        "3162 精確 觸及目標一 81.37"
    ]
    assert f"--- levels_restored restored=0 missing={events[0]['key']}" in _log(env)


@linux_only
def test_a_plan_whose_levels_changed_takes_the_open_after_a_restart(env):
    """#808 review 6912722520 item 1: the user lowers a plan's target one from 85 to 81
    after its last round (high 82). The restarted run does not compare with the 82 of
    the old levels (that would never tell 觸及目標一): its first round takes the high
    since the open, 82 ≥ 81."""

    signal = _listed(env.db, symbols=("3162",), execution=FRIDAY)["3162"]
    plan = _plan(env.db, signal, target_1=85.0)
    _run(env, start="13:25:00", fetch=_pullback_after_its_high)
    assert [r["event"] for r in _jsonl(env)] == [intraday.ENTRY]
    assert _jsonl(env)[0]["key"] == f"plan:{plan.id}"
    plan.target_1 = 81.0
    env.db.commit()
    again = _run(env, start="13:28:10", fetch=_pullback_after_its_high)
    assert [text.split("（")[0] for text in again.sent] == [
        "3162 精確 觸及目標一 81.00"
    ]
    assert f"--- levels_restored restored=0 missing=plan:{plan.id}" in _log(env)


def test_the_levels_read_back_are_the_last_rounds(tmp_path):
    rules = '"levels": ["breakout", 100.0, null, null, 95.0, 110.0, 120.0]'
    path = tmp_path / "intraday.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"at": "09:00", "levels": {"plan:1": {"high": 10, "low": 9, "last": 9.5, '
                + rules
                + "}}}",
                '{"at": "09:00", "key": "plan:1", "symbol": "9999", "event": "entry"}',
                "not json",
                '{"at": "09:01", "levels": {"plan:1": {"high": 11, "low": 9, "last": null, '
                + rules
                + '}, "plan:2": {"high": null, "low": 5, "last": 5, '
                + rules
                + '}, "plan:3": {"high": 6, "low": 5, "last": 5}}}',
                '{"at": "09:02", "levels": "broken"}',
                # plan:1 not judged on 09:03 (a timeout): its 09:01 line stands.
                '{"at": "09:03", "levels": {"plan:4": {"high": 7, "low": 6, "last": 6, '
                + rules
                + "}}}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    breakout = ("breakout", 100.0, None, None, 95.0, 110.0, 120.0)
    assert intraday.day_levels(path) == {
        "plan:1": intraday.Saved(11, 9, None, breakout),
        "plan:4": intraday.Saved(7, 6, 6, breakout),
    }
    assert intraday.sent_events(path) == {"plan:1": [intraday.ENTRY]}
    assert intraday.day_levels(tmp_path / "missing.jsonl") == {}
    watched = _watched()
    assert intraday.rule_levels(watched) == breakout
    saved = intraday.Saved(111.0, 99.0, 100.0, breakout)
    state = intraday.resumed(watched, [intraday.ENTRY], saved)
    assert (state.entered, state.high, state.low, state.last) == (
        True,
        111.0,
        99.0,
        100.0,
    )
    # Over target one already on the last round: no 觸及目標一 again.
    assert intraday.judge(watched, state, _custom(112.0, 99.0))[0] == []
    # Recorded by other levels: as without them.
    other = intraday.Saved(111.0, 99.0, 100.0, (*breakout[:5], 115.0, 120.0))
    assert intraday.resumed(watched, [intraday.ENTRY], other).high is None


def test_a_line_cut_off_is_ended_before_the_next_is_added(tmp_path):
    path = tmp_path / "intraday.jsonl"
    path.write_text('{"at": "09:00", "key": "plan:1", "event": "entry"}\n{"at": "09:0')
    intraday._append(path, '{"at": "09:01", "key": "plan:1", "event": "target_1"}')
    intraday._append(path, '{"at": "09:02", "key": "plan:1", "event": "target_2"}')
    assert path.read_text().splitlines()[1:] == [
        '{"at": "09:0',
        '{"at": "09:01", "key": "plan:1", "event": "target_1"}',
        '{"at": "09:02", "key": "plan:1", "event": "target_2"}',
    ]
    assert intraday.sent_events(path) == {
        "plan:1": [intraday.ENTRY, intraday.TARGET_1, intraday.TARGET_2]
    }
    fresh = tmp_path / "fresh.jsonl"
    intraday._append(fresh, "{}")
    assert fresh.read_bytes() == b"{}\n"


@linux_only
def test_a_closed_day_logs_one_line_and_ends(env):
    _listed(env.db)
    _closed(env.db, MONDAY)
    result = _run(env)
    assert result.code == 0 and result.sent == []
    results = [line for line in _log(env).splitlines() if line.startswith("--- ")]
    assert results == ["--- result status=skipped reason=non_trading_day"]
    assert result.clock.slept == 0
    assert intraday.day_done(env.logs, MONDAY)


@linux_only
def test_without_a_key_the_run_records_not_configured_and_ends(env):
    _listed(env.db)
    environ = {k: v for k, v in ENV.items() if k != fugle.KEY_ENV}
    result = _run(env, environ=environ)
    assert result.code == 0 and result.sent == []
    assert intraday.day_results(env.logs, MONDAY) == [intraday.NOT_CONFIGURED]
    assert "--- result status=not_configured missing=FUGLE_API_KEY" in _log(env)
    # Not done: a key set later the same morning is caught up by serve.
    assert not intraday.day_done(env.logs, MONDAY)
    environ = {k: v for k, v in ENV.items() if k != "TELEGRAM_CHAT_ID"}
    _run(env, environ=environ)
    assert "missing=TELEGRAM_CHAT_ID" in _log(env)


@linux_only
def test_maintenance_mode_does_not_stop_it(env):
    _listed(env.db)
    marker = job.maintenance_path(env.data)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps({"since_epoch": 0, "reason": "回補"}), encoding="utf-8"
    )
    result = _run(env, start="13:28:00")
    assert len(result.sent) == 5
    assert intraday.day_results(env.logs, MONDAY) == [intraday.FINISHED]


@linux_only
def test_a_busy_lock_and_a_late_start_skip(env):
    _listed(env.db)
    holder = job.FileLock(job.lock_path(env.data, intraday.LOCK))
    assert holder.acquire()
    try:
        _run(env)
    finally:
        holder.release()
    _run(env, start="13:30:00")
    assert intraday.day_results(env.logs, MONDAY) == [
        "skipped reason=already_running",
        "skipped reason=too_late",
    ]


@linux_only
def test_a_day_without_stocks_ends_at_once(env):
    result = _run(env)
    assert intraday.day_results(env.logs, MONDAY) == ["skipped reason=no_targets"]
    assert result.clock.slept == 0


def _failing(answers):
    """A fetch that answers with ANSWERS[i] (a code) on the i-th round, the last after."""

    def make(clock):
        rounds: list[datetime] = []

        def fetch(symbol):
            if not rounds or rounds[-1] != clock.now:
                rounds.append(clock.now)
            code = answers[min(len(rounds), len(answers)) - 1]
            if code == "200":
                return _fixture_fetch(clock)(symbol)
            reason = fugle.STOP_DAY_CODES.get(int(code), "") if code.isdigit() else code
            return fugle.Fetched(symbol, code, 10000, reason=reason)

        return fetch

    return make


@linux_only
@pytest.mark.parametrize(
    "code, why",
    [("401", "API key 無效"), ("403", "方案不支援"), ("429", "超過呼叫上限")],
)
def test_a_refused_key_stops_the_days_reading_with_one_message(env, code, why):
    _listed(env.db)
    result = _run(env, fetch=_failing(["200", "200", code]))
    assert (
        result.sent[-1] == f"盤中報價今天停止讀取（富果回應 {code}：{why}），09:02 起"
    )
    log = _log(env)
    assert len([line for line in log.splitlines() if line.startswith("--- poll ")]) == 3
    assert (
        f"--- result status=stopped reason={fugle.STOP_DAY_CODES[int(code)]} code={code}"
        in log
    )
    assert intraday.day_done(env.logs, MONDAY)


@linux_only
def test_five_failed_rounds_slow_down_and_tell_once_each_way(env):
    _listed(env.db)
    answers = ["200"] + ["timeout"] * 7 + ["200"] * 3 + ["502"] * 6 + ["200"]
    result = _run(env, fetch=_failing(answers), mode="--send")
    ops = [text for text in result.sent if text.startswith("盤中報價")]
    assert ops == [
        "盤中報價暫停（來源回應失敗），09:05 起；改為每 5 分鐘讀一次",
        "盤中報價恢復，09:20 起",
    ]
    log = _log(env)
    polls = [
        line.split()[2] for line in log.splitlines() if line.startswith("--- poll ")
    ]
    # 09:00 ok, 09:01-09:05 failed (slow from then), 09:10, 09:15 failed, 09:20 back.
    assert polls[:10] == [
        "at=09:00:00",
        "at=09:01:00",
        "at=09:02:00",
        "at=09:03:00",
        "at=09:04:00",
        "at=09:05:00",
        "at=09:10:00",
        "at=09:15:00",
        "at=09:20:00",
        "at=09:21:00",
    ]
    assert "--- paused at=09:05:00 failed_rounds=5" in log
    assert "--- resumed at=09:20:00" in log
    # The second outage slows down again, without a second pair of messages.
    assert log.count("--- paused ") == 2


@linux_only
def test_a_404_or_a_malformed_quote_drops_only_that_stock(env):
    _listed(env.db)

    def make(clock):
        good = _fixture_fetch(clock)

        def fetch(symbol):
            if symbol == "3374":
                return fugle.Fetched(symbol, "404", 50)
            if symbol == "8099":
                return fugle.Fetched(symbol, "200", 50, reason="malformed:lastTrade")
            return good(symbol)

        return fetch

    result = _run(env, fetch=make)
    log = _log(env)
    assert "--- dropped symbol=3374 reason=http_404" in log
    assert "--- dropped symbol=8099 reason=malformed:lastTrade" in log
    polls = [line for line in log.splitlines() if line.startswith("--- poll ")]
    assert polls[0].split()[3:5] == ["symbols=4", "ok=2"]
    assert polls[1].split()[3:5] == ["symbols=2", "ok=2"]
    assert [text.split()[0] for text in result.sent] == ["2618", "3162", "3162"]


@linux_only
def test_over_fifty_stocks_keep_the_first_fifty_and_tell_once(env):
    symbols = [f"{n}" for n in range(1100, 1155)]
    base = DAY["levels"]["2618"]
    DAY["levels"].update({s: dict(base, name=f"名{s}") for s in symbols})
    try:
        _listed(env.db, symbols=symbols)

        def make(clock):
            def fetch(symbol):
                body = dict(DAY["polls"][2]["quotes"]["2618"], symbol=symbol)
                return fugle.Fetched(
                    symbol, "200", 10, quote=fugle.parse(symbol, body)[0]
                )

            return fetch

        # read_tracks keeps the page's 20: more stocks come from the plans.
        assert len(intraday.read_tracks(env.db, MONDAY, NINE)) == 20
        for signal in env.db.query(Signal).all()[20:]:
            _plan(env.db, signal)
        result = _run(env, start="13:29:00", fetch=make)
        again = _run(env, start="13:29:30", fetch=make)
    finally:
        for s in symbols:
            DAY["levels"].pop(s)
    capped = [text for text in result.sent if text.startswith("盤中通知")]
    assert capped == [
        "盤中通知今天有 55 檔，超過每分鐘 50 檔的上限，略過 5 檔："
        + "、".join(symbols[50:])
    ]
    assert not any(text.startswith("盤中通知") for text in again.sent)
    log = _log(env)
    assert f"--- capped kept=50 skipped={','.join(symbols[50:])}" in log
    assert "--- poll at=13:29:00 symbols=50 ok=50" in log
    # The restarted run counts the 50 asked, not the 5 never asked (#808 AC-3).
    assert "--- levels_restored restored=50 missing=-" in log


def test_a_dry_run_sends_nothing_and_writes_no_file(env, monkeypatch):
    _listed(env.db)
    result = _run(env, start="10:02:30", mode="--dry-run", extra=("--minutes", "2"))
    assert result.sent == []
    assert not env.logs.exists()
    polls = [line for line in result.out.splitlines() if line.startswith("--- poll ")]
    assert [line.split()[2] for line in polls] == ["at=10:03:00", "at=10:04:00"]
    messages = [
        line for line in result.out.splitlines() if line.startswith("--- message ")
    ]
    # 10:03, each stock's first round: 2618 entry, 3374 stop before entry, 8099 gap,
    # 3162 entry and stop.
    assert len(messages) == 5
    assert all('"status": "dry_run"' in line for line in messages)


# --- #833: the terminal and the log show none of Fugle's values -----------------------

# The Telegram texts of the fixture's day as the run before #833 sent them (AC-3): the
# masking is of what is shown, never of what is sent.
SENT_BEFORE_833 = [
    "2618 長榮航 觸及規則進場價 47.75（09:01 前後；09:00:30 成交 47.80）\n來源：今日名單",
    "8099 大世科 觸及規則進場價 182.00，但開盤 200.00 已在目標一 198.63 以上，"
    "依規則不算進場，今天這檔不再通知（09:01 前後；09:00:30 成交 200.00）\n"
    "漲停鎖住（委買 200.00，委賣取不到）\n來源：今日名單",
    "3162 精確 觸及規則進場區 72.89～76.94（09:01 前後；09:00:30 成交 74.10）\n來源：今日名單",
    "3374 精材 跌破停損 480.18，進場條件不再成立（10:03 前後；10:02:55 成交 467.50）\n"
    "跌停鎖住（委買取不到，委賣 467.50）\n來源：今日名單",
    "3162 精確 觸及停損 70.86（10:03 前後；10:02:54 成交 67.60）\n來源：今日名單",
]


def _fixture_values() -> tuple[set[str], set[str]]:
    """The fixture's quote prices (as notify.price and as Python prints them) and trade
    times (HH:MM:SS Taipei): what fugle.parse reads and a message or a levels line can
    carry. A price that is also a rule level (2618's high at the open is its breakout
    price) is left out: the level is ours and is shown; so is a time of a whole minute."""

    prices: set[float] = set()
    times: set[str] = set()
    for poll in DAY["polls"]:
        for body in poll["quotes"].values():
            for name in ("openPrice", "highPrice", "lowPrice", "lastPrice"):
                if body.get(name) is not None:
                    prices.add(body[name])
            for name in ("lastTrade", "lastTrial"):
                trade = body.get(name) or {}
                for part in ("price", "bid", "ask"):
                    if trade.get(part) is not None:
                        prices.add(trade[part])
                if trade.get("time"):
                    moment = datetime.fromtimestamp(trade["time"] / 1e6, TAIPEI)
                    times.add(f"{moment:%H:%M:%S}")
            for side in ("bids", "asks"):
                prices.update(level["price"] for level in body.get(side) or [])
    rules = {
        value
        for levels in DAY["levels"].values()
        for value in levels.values()
        if isinstance(value, float)
    }
    prices -= rules
    # A trade at a whole minute reads as a round of ours (--- poll at=10:02:00).
    times = {value for value in times if not value.endswith(":00")}
    assert len(prices) >= 10 and len(times) >= 4
    shown = {intraday.notify.price(value) for value in prices} | {
        str(value) for value in prices
    }
    return shown, times


def _shown_values(text: str) -> list[str]:
    """The fixture's quote values in TEXT, each as a whole number (47.8 is not 47.80's
    start, and a value is not a piece of another)."""

    prices, times = _fixture_values()
    found = []
    for value in sorted(prices | times):
        if re.search(rf"(?<![0-9.,:]){re.escape(value)}(?![0-9:]|\.[0-9])", text):
            found.append(value)
    return found


@linux_only
def test_a_dry_run_shows_no_quote_of_fugle(env):
    """#833 AC-1: a dry run through the fixture's three rounds prints all five messages
    with <價> and <時間> and none of the values; the poll and event lines and the rule
    levels stay."""

    _listed(env.db)
    dry = _run(env, mode="--dry-run", extra=("--minutes", "70"))
    assert not env.logs.exists()
    assert _shown_values(dry.out) == []
    lines = dry.out.splitlines()
    messages = [
        json.loads(line.removeprefix("--- message "))
        for line in lines
        if line.startswith("--- message ")
    ]
    assert [m["text"] for m in messages] == [
        "2618 長榮航 觸及規則進場價 47.75（09:01 前後；<時間> 成交 <價>）\n來源：今日名單",
        "8099 大世科 觸及規則進場價 182.00，但開盤 <價> 已在目標一 198.63 以上，"
        "依規則不算進場，今天這檔不再通知（09:01 前後；<時間> 成交 <價>）\n"
        "漲停鎖住（委買 <價>，委賣取不到）\n來源：今日名單",
        "3162 精確 觸及規則進場區 72.89～76.94（09:01 前後；<時間> 成交 <價>）\n來源：今日名單",
        "3374 精材 跌破停損 480.18，進場條件不再成立（10:03 前後；<時間> 成交 <價>）\n"
        "跌停鎖住（委買取不到，委賣 <價>）\n來源：今日名單",
        "3162 精確 觸及停損 70.86（10:03 前後；<時間> 成交 <價>）\n來源：今日名單",
    ]
    # Where a Fugle value goes, a placeholder is, whatever the value (_shown_values
    # leaves out a quote equal to a rule level and a trade at a whole minute).
    for message in messages:
        text = message["text"]
        assert re.search(r"（[0-9]{2}:[0-9]{2} 前後；<時間> 成交 <價>）", text), text
        assert not re.search(r"(?:開盤|委買|委賣|成交) (?!<價>)[0-9]", text), text
    assert sum(line.startswith("--- poll at=") for line in lines) == 70
    assert sum(line.startswith("--- event key=") for line in lines) == 5
    assert "--- target key=signal:" in dry.out and "stop=46.31" in dry.out


@linux_only
def test_the_log_shows_no_quote_of_fugle(env):
    """#833 AC-1: the full day's log (sending, and a run restarted at 11:00 that reads
    the levels lines back) and the terminal have none of the values; the poll, event
    and levels_restored lines and the rule levels stay."""

    _listed(env.db)
    sent = _run(env)
    again = _run(env, start="11:00:10")
    log = _log(env)
    assert _shown_values(log) == []
    assert _shown_values(sent.out) == [] and _shown_values(again.out) == []
    assert log.count("--- event key=") == 5
    assert log.count("--- poll at=") == 271 + 150
    assert "--- levels_restored restored=1 missing=-" in log
    assert "stop=480.18" in log
    # The values are in the day's jsonl (and the Telegram texts): the check sees them.
    assert _shown_values(intraday.events_path(env.logs, MONDAY).read_text("utf-8"))


@linux_only
def test_the_telegram_texts_are_as_before_and_the_jsonl_keeps_them(env):
    """#833 AC-2, AC-3: what is sent is word for word the text before #833; the jsonl
    keeps it and the levels lines keep the high, low and last (a restart reads them)."""

    _listed(env.db)
    result = _run(env)
    assert result.sent == SENT_BEFORE_833
    assert [r["text"] for r in _jsonl(env)] == SENT_BEFORE_833
    levels = [r[intraday.LEVELS] for r in _lines(env) if intraday.LEVELS in r]
    assert levels and all(
        isinstance(values["high"], float) for line in levels for values in line.values()
    )


@linux_only
def test_a_raw_file_has_the_values_and_the_terminal_does_not(env, tmp_path):
    """#833 AC-2: --raw-file gets the jsonl's lines (the messages as sent, the levels),
    the terminal the masked ones; without it a dry run writes no file."""

    _listed(env.db)
    raw = tmp_path / "raw" / "dry-raw.jsonl"
    dry = _run(env, mode="--dry-run", extra=("--minutes", "70", "--raw-file", str(raw)))
    assert _shown_values(dry.out) == []
    assert f"raw={raw}" in dry.out.splitlines()[-1]
    assert not env.logs.exists()
    records = [json.loads(line) for line in raw.read_text("utf-8").splitlines()]
    texts = [r["text"] for r in records if intraday.LEVELS not in r]
    assert texts == SENT_BEFORE_833
    assert all(r["status"] == "dry_run" for r in records if "text" in r)
    # 70 rounds, of which 09:00 is a trial (nothing judged): 69 levels lines.
    assert sum(intraday.LEVELS in r for r in records) == 69
    assert ENV[fugle.KEY_ENV] not in raw.read_text("utf-8")


def test_a_raw_file_goes_with_a_dry_run_outside_a_checkout(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCK_DATA_DIR", str(tmp_path / "data"))
    parser = argparse.ArgumentParser()
    intraday.add_arguments(parser)
    outside = str(tmp_path / "raw.jsonl")
    args = parser.parse_args(["--send", "--raw-file", outside])
    assert intraday.argument_problem(args).startswith("--raw-file goes with --dry-run")
    assert intraday.argument_problem(parser.parse_args(["--dry-run"])) is None
    args = parser.parse_args(["--dry-run", "--raw-file", outside])
    assert intraday.argument_problem(args) is None
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    inside = str(tmp_path / "repo" / "logs" / "raw.jsonl")
    args = parser.parse_args(["--dry-run", "--raw-file", inside])
    assert (
        intraday.argument_problem(args) == "--raw-file must be outside a git checkout"
    )
    # Empty (an unset shell variable): it would write nothing and say nothing.
    for empty in ("", " "):
        args = parser.parse_args(["--dry-run", "--raw-file", empty])
        assert intraday.argument_problem(args) == "--raw-file must not be empty"


@pytest.mark.parametrize(
    "where",
    [
        "elsewhere/intraday-20261116.jsonl",  # named as the day's jsonl
        "elsewhere/intraday-20261116.log",
        "data/logs/raw.jsonl",  # under the scheduled run's logs
        "data/logs/sub/raw.jsonl",
        "mine/raw.jsonl",  # under this run's --log-dir
    ],
)
def test_a_raw_file_is_never_a_file_the_scheduled_run_reads(
    tmp_path, monkeypatch, where
):
    # #842 review: the scheduled run would read a dry run's lines as its own (its
    # dry_run events as sent, its high and low as the last round).
    monkeypatch.setenv("STOCK_DATA_DIR", str(tmp_path / "data"))
    parser = argparse.ArgumentParser()
    intraday.add_arguments(parser)
    argv = ["--dry-run", "--log-dir", str(tmp_path / "mine")]
    args = parser.parse_args([*argv, "--raw-file", str(tmp_path / where)])
    assert intraday.argument_problem(args) == (
        "--raw-file must not be a log or jsonl of intraday, nor in the logs"
    )
    args = parser.parse_args([*argv, "--raw-file", str(tmp_path / "other/raw.jsonl")])
    assert intraday.argument_problem(args) is None


@linux_only
def test_a_raw_file_that_cannot_be_made_ends_with_a_result_line(env, tmp_path):
    _listed(env.db)
    (tmp_path / "a_file").write_text("", encoding="utf-8")
    raw = tmp_path / "a_file" / "raw.jsonl"
    dry = _run(env, mode="--dry-run", extra=("--minutes", "2", "--raw-file", str(raw)))
    assert dry.code == 1
    assert "--- result status=failed reason=error:" in dry.out


def test_the_arguments():
    parser = argparse.ArgumentParser()
    intraday.add_arguments(parser)
    args = parser.parse_args(["--send", "--minutes", "5"])
    assert intraday.argument_problem(args) == "--minutes goes with --dry-run only"
    args = parser.parse_args(["--dry-run", "--now", "not a time"])
    assert intraday.argument_problem(args).startswith("--now must be")
    with pytest.raises(SystemExit):
        parser.parse_args([])


# --- serve's catch-up reads the day's log ---------------------------------------------


@pytest.mark.parametrize(
    "results, done",
    [
        ((), False),
        (("status=finished polls=271 ok_polls=271 events=0 symbols=4",), True),
        (("status=stopped reason=key_invalid code=401",), True),
        (("status=skipped reason=non_trading_day",), True),
        (("status=skipped reason=no_targets",), True),
        (("status=not_configured missing=FUGLE_API_KEY",), False),
        (("status=skipped reason=already_running",), False),
        (("status=failed reason=error:OperationalError",), False),
    ],
)
def test_the_days_that_need_no_run_any_more(tmp_path, results, done):
    tmp_path.joinpath(f"intraday-{MONDAY:%Y%m%d}.log").write_text(
        "".join(f"===== start\n--- result {r}\n===== end exit=0\n" for r in results),
        encoding="utf-8",
    )
    assert intraday.day_done(tmp_path, MONDAY) is done


# --- #802 review 6910820856 -----------------------------------------------------------


def _counting(clock, *, seconds=0.0, jump=None):
    """The fixture's fetch that records (symbol, minute) per request; each request takes
    SECONDS on the clock, and JUMP=(at, seconds) moves the clock once when it passes AT
    (a host asleep)."""

    good = _fixture_fetch(clock)
    asked: list[tuple[str, str]] = []

    def fetch(symbol):
        asked.append((symbol, f"{clock.now:%H:%M}"))
        answer = good(symbol)
        clock.now += timedelta(seconds=seconds)
        if jump and clock.now >= jump[0] and not jump[2:]:
            clock.now += timedelta(seconds=jump[1])
            jump.append("done")
        return answer

    fetch.asked = asked
    return fetch


@linux_only
def test_a_slow_round_skips_the_minutes_it_took_and_asks_once_a_minute(env):
    """Each request takes 40 s: a round of 4 stocks takes 160 s, so the next starts at the
    next whole minute still ahead, never in a minute already asked."""

    _listed(env.db)
    made = {}

    def make(clock):
        made["fetch"] = _counting(clock, seconds=40)
        return made["fetch"]

    _run(env, start="13:20:00", fetch=make)
    asked = made["fetch"].asked
    starts = [minute for symbol, minute in asked if symbol == "2618"]
    assert len(starts) == len(set(starts))  # one request per stock per minute
    for symbol in DAY["levels"]:
        minutes = [minute for s, minute in asked if s == symbol]
        assert len(minutes) == len(set(minutes)), symbol
    log = _log(env)
    polls = [
        line.split()[2] for line in log.splitlines() if line.startswith("--- poll ")
    ]
    assert polls[:3] == ["at=13:20:00", "at=13:23:00", "at=13:26:00"]
    assert "--- skipped_rounds from=13:21 to=13:22 minutes=2" in log
    assert f"polls={len(polls)} ok_polls={len(polls)}" in log


@linux_only
def test_a_host_asleep_for_an_hour_does_not_catch_up_the_hour(env):
    _listed(env.db)
    made = {}

    def make(clock):
        jump = [_at("2026-11-16T10:00:00+08:00"), 3600]
        made["fetch"] = _counting(clock, jump=jump)
        return made["fetch"]

    _run(env, start="09:58:00", fetch=make)
    asked = made["fetch"].asked
    per_minute: dict[str, int] = {}
    for _symbol, minute in asked:
        per_minute[minute] = per_minute.get(minute, 0) + 1
    assert max(per_minute.values()) == 4  # the 4 stocks once each
    log = _log(env)
    assert "--- skipped_rounds from=10:01 to=11:00 minutes=60" in log
    polls = [line for line in log.splitlines() if line.startswith("--- poll ")]
    # 09:58 to 10:00, then 11:01 to 13:30: the hour is no poll of the day.
    assert len(polls) == 3 + 150
    assert "--- poll at=11:01:00 " in log


@linux_only
def test_a_quote_of_another_day_is_not_judged(env):
    """A session called off (a typhoon the stored calendar does not have): Fugle answers
    with the last session's quote, whose high and low are not today's."""

    _listed(env.db)

    def make(clock):
        def fetch(symbol):
            body = dict(DAY["polls"][2]["quotes"][symbol], date="2026-11-13")
            return fugle.Fetched(symbol, "200", 10, quote=fugle.parse(symbol, body)[0])

        return fetch

    result = _run(env, start="13:28:00", fetch=make)
    assert result.sent == []
    log = _log(env)
    assert log.count("--- stale_quote symbol=2618 date=2026-11-13") == 1
    assert "--- result status=finished polls=3 ok_polls=3 events=0" in log
    assert fugle.parse("2618", DAY["polls"][2]["quotes"]["2618"])[0].day == "2026-11-16"


def test_a_plan_with_other_levels_than_its_signal_is_a_track_of_its_own(db):
    """The plan keeps its own copy (#801 scope 3): the signal rewritten after the plan was
    made gives two tracks of the stock, each with its own levels and source."""

    signals = _listed(db)
    plan = _plan(db, signals["2618"], invalid_price=46.0, target_1=51.0)
    tracks = intraday.read_tracks(db, MONDAY, NINE)
    mine = [t for t in tracks if t.symbol == "2618"]
    assert [(t.key, t.sources, t.invalid, t.target_1) for t in mine] == [
        (f"signal:{signals['2618'].id}", (intraday.LIST,), 46.31, 50.05),
        (f"plan:{plan.id}", (intraday.TRACKING,), 46.0, 51.0),
    ]
    assert intraday.symbols_of(tracks) == ["2618", "3374", "8099", "3162"]


def test_the_read_only_session_reads_and_refuses_to_write(tmp_path, monkeypatch):
    import sqlite3

    import app.config

    path = tmp_path / "stock.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (7)")
    conn.close()
    monkeypatch.setattr(app.config, "DB_PATH", path)
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    with intraday._read_only_session() as session:
        assert session.execute(text("SELECT x FROM t")).scalar() == 7
        with pytest.raises(OperationalError, match="readonly"):
            session.execute(text("INSERT INTO t VALUES (8)"))
