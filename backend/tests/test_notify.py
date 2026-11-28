"""The daily Telegram message (backend/worker/notify.py, #728).

No test reaches Telegram: the sends go to a stand-in HTTP server on 127.0.0.1
(``API_BASE`` points there), and the token is a fake one set with monkeypatch.
The runs take the job's fcntl lock, so like worker.job they run on Linux (the image).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import threading
from datetime import date, datetime, timedelta
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, enable_sqlite_foreign_keys
from app.domain import US_INDEX_EXCHANGE
from app.models import (
    Instrument,
    MarketBar,
    RawPayload,
    TradingCalendarDay,
)
from test_ai_list_view import _reading as _ai_reading
from test_candidates import T, signal, stock
from worker import job, notify, notify_card, pipeline
from worker.candidates import compute_daily_candidates

ON_LINUX = sys.platform.startswith("linux")
linux_only = pytest.mark.skipif(not ON_LINUX, reason="fcntl lock: Linux only (#333)")
TOKEN = "123456789:AAFakeTokenForTestsOnly_abcdefghijk"
CHAT = "987654321"
# T (Friday 2026-09-04) is the list's day; the message is Monday's.
MONDAY = date(2026, 9, 7)


# --- the message, from the API's shapes ------------------------------------------------


TITLE = "📋 <b>AI 名單 2026/09/07（一）開盤前</b> · AI 推論，未經驗證"
CAPTION = "<b>AI 名單 09/07（一）</b>・3 檔・AI 推論，未經驗證"


def _us(symbol, close, pct, day="2026-09-04", freshness="latest", series=None):
    series = (
        series
        or {"SPX": "^GSPC", "IXIC": "^IXIC", "DJI": "^DJI", "SOX": "^SOX"}[symbol]
    )
    return {
        "symbol": symbol,
        "name": symbol,
        "series_id": series,
        "status": "available",
        "trading_date": day,
        "freshness": freshness,
        "close": close,
        "change_pct": pct,
        "source": {"label": f"FinMind USStockPrice {series}"},
    }


def _missing(symbol, reason="not_collected"):
    return {"symbol": symbol, "name": symbol, "status": "unavailable", "reason": reason}


US = [
    _us("SPX", 7561.67, -0.004),
    _us("IXIC", 25136.27, -0.0091),
    _us("DJI", 52347.55, 0.001),
    _us("SOX", 10146.32, -0.0343),
]
US_ROWS = [
    "🟢 S&amp;P 500　7,561.67　−0.40%",
    "🟢 NASDAQ　25,136.27　−0.91%",
    "🔴 道瓊　52,347.55　+0.10%",
    "🟢 費半　10,146.32　−3.43%",
]


def _well_formed(text):
    """Telegram's HTML parser takes it: the only tags are <b> and </b>, paired."""

    assert text.count("<b>") == text.count("</b>")
    assert "<" not in re.sub(r"</?b>", "", text)
    assert ">" not in re.sub(r"</?b>", "", text)


RULES = {"status": "success", "candidate_count": 23, "items": []}
CARD_US = [
    _us("SPX", 7561.67, -0.004),
    _us("IXIC", 25136.27, 0.0),
    _us("DJI", 52347.55, 0.001),
    _missing("SOX", "fetch_failed"),
]


def _text(indexes, rules=RULES):
    """The text without an AI list (its own tests: test_ai_list_view.py)."""

    return notify.compose(MONDAY, None, indexes, rules)


def test_without_an_ai_list_the_text_has_one_line_the_rule_count_and_the_us_block():
    text = _text(CARD_US)
    assert text == "\n".join(
        [
            notify.AI_LIST_MISSING,
            "（規則名單 23 檔見今日名單頁）",
            "",
            "🌎 <b>隔夜美股</b>（09/04 收盤）",
            "🟢 S&amp;P 500　7,561.67　−0.40%",
            "⚪ NASDAQ　25,136.27　0.00%",
            "🔴 道瓊　52,347.55　+0.10%",
            "費半　無資料（抓取失敗）",
            "來源 FinMind",
        ]
    )
    _well_formed(text)
    # Facts only: no research status or explanation (decision 6881297699).
    assert "證據" not in text and "研究" not in text


def test_the_card_on_a_us_holiday():
    closed = [
        _us(i["symbol"], i["close"], i["change_pct"], "2026-09-03", "us_market_closed")
        for i in US
    ]
    assert _text(closed).splitlines()[2:] == [
        "",
        "🌎 <b>隔夜美股</b> 美股休市（09/03 收盤）",
        *US_ROWS,
        "來源 FinMind",
    ]


def test_a_rule_list_not_computed_says_no_data():
    text = _text(US, {"status": "not_computed", "items": []})
    assert text.splitlines()[1] == notify.RULE_LIST_MISSING
    assert _text(US, {"status": "success", "candidate_count": 0}).splitlines()[1] == (
        "（規則名單 0 檔見今日名單頁）"
    )


def test_missing_us_indexes_say_no_data():
    nothing = [_missing(symbol) for symbol in ("SPX", "IXIC", "DJI", "SOX")]
    assert _text(nothing).endswith("\n🌎 <b>隔夜美股</b>：無資料（美股尚未更新）")


def test_the_us_freshness_follows_the_today_page():
    def head(lines):
        return next(line for line in lines if line.startswith("🌎 "))

    # One index behind: its own date and 非最新.
    behind = [*US[:3], _us("SOX", 10000.0, 0.01, "2026-09-03", "stale")]
    lines = _text(behind).splitlines()
    assert head(lines) == "🌎 <b>隔夜美股</b>"
    assert "🔴 費半　10,000.00　+1.00%（09/03 收盤） 非最新" in lines
    assert "🟢 S&amp;P 500　7,561.67　−0.40%（09/04 收盤）" in lines
    # None of the expected night.
    stale = [
        _us(i["symbol"], i["close"], i["change_pct"], "2026-09-02", "stale") for i in US
    ]
    lines = _text(stale).splitlines()
    assert head(lines) == "🌎 <b>隔夜美股</b> 美股尚未更新（09/02 收盤）"
    assert not any("非最新" in line for line in lines)


def test_the_us_marks_follow_the_rounded_change_and_two_sources_are_named():
    tiny = [
        _us("SPX", 7561.67, -0.00001),
        _us("IXIC", 25136.27, None),
        {**_us("DJI", 52347.55, 0.001), "source": {"label": "FRED"}},
    ]
    lines = _text(tiny).splitlines()
    # -0.001% shows as 0.00%: flat, not down.
    assert "⚪ S&amp;P 500　7,561.67　0.00%" in lines
    # An unknown change has no mark.
    assert "NASDAQ　25,136.27　—" in lines
    assert lines[-1] == "來源 FinMind；FRED"


def test_the_length_counts_the_tags_entities_and_an_emoji_as_two():
    assert notify.length("🚀") == 2 and notify.length("<b>&amp;</b>") == 12


# --- the message, from the database ---------------------------------------------------


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        session.info["strategies"] = pipeline._ensure_strategies(session)
        session.commit()
        yield session
    engine.dispose()


def _us_bars(db, symbol="SOX", closes=((date(2026, 9, 3), 100.0), (T, 103.0))):
    index = Instrument(
        exchange=US_INDEX_EXCHANGE,
        symbol=symbol,
        name="費城半導體指數",
        instrument_type="index",
        status="active",
    )
    db.add(index)
    db.flush()
    for day, close in closes:
        db.add(
            MarketBar(
                instrument_id=index.id,
                trading_date=day,
                open=close,
                high=close,
                low=close,
                close=close,
                adj_close=close,
                source="finmind_us_index",
            )
        )
    db.flush()


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
    db.flush()


def _list_of_t(db):
    signal(db, stock(db, "1101"))
    db.commit()
    compute_daily_candidates(db, T)
    _us_bars(db)
    db.commit()


def test_the_message_reads_the_ai_list_the_rule_count_of_the_session_before_and_us(db):
    _list_of_t(db)
    _ai_reading(db)
    lines = notify.message(db, MONDAY).splitlines()
    assert lines[0] == TITLE
    assert "<b>1. 1477 聚陽</b>｜突破｜把握中" in lines
    assert "（規則名單 1 檔見今日名單頁）" in lines
    # Only SOX is stored: the others say so; SOX is Friday's, the night before Monday.
    assert "🔴 費半　103.00　+3.00%" in lines
    assert "S&amp;P 500　無資料（未取得）" in lines
    assert lines[-1] == "來源 FinMind"


def test_a_day_without_its_ai_list_sends_the_one_before_with_the_reason(db):
    _list_of_t(db)
    _ai_reading(db)
    # Tuesday has no row: Monday's list, with the reason.
    lines = notify.message(db, date(2026, 9, 8)).splitlines()
    assert lines[:2] == [
        "今天的 AI 名單沒有產出（沒有產出紀錄）；以下是 09/07 的名單",
        TITLE,
    ]
    # Tuesday wants Monday's rule list: Friday's is not counted instead.
    assert notify.RULE_LIST_MISSING in lines


def test_the_session_before_skips_the_closed_days(db):
    _list_of_t(db)
    _closed(db, date(2026, 9, 7))
    assert notify.is_trading_day(db, date(2026, 9, 7)) is False
    assert notify.is_trading_day(db, date(2026, 9, 5)) is False  # Saturday
    assert notify.previous_session(db, date(2026, 9, 8)) == T
    assert "（規則名單 1 檔見今日名單頁）" in notify.message(db, date(2026, 9, 8))


# --- the runs --------------------------------------------------------------------------


INCOMPLETE = {"ok": True}


FAKE_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(range(256)) * 4
# Telegram's answer to a photo: the sizes it keeps (#754).
PHOTO_SIZES = [
    {"file_id": "a", "width": 90, "height": 196},
    {"file_id": "b", "width": 1080, "height": 2356},
    {"file_id": "c", "width": 587, "height": 1280},
]


def _form(content_type: str, body: bytes) -> dict:
    """A multipart/form-data body as {name: text, or (filename, type, bytes)}."""

    message = BytesParser().parsebytes(
        f"Content-Type: {content_type}\r\n\r\n".encode() + body
    )
    assert message.is_multipart()
    form = {}
    for part in message.get_payload():
        name = part.get_param("name", header="content-disposition")
        data = part.get_payload(decode=True)
        filename = part.get_filename()
        form[name] = (
            (filename, part.get_content_type(), data)
            if filename
            else data.decode("utf-8")
        )
    return form


class Telegram:
    """The stand-in Bot API: answers each sendMessage or sendPhoto with the next scripted
    reply."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests: list[dict] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                kind = self.headers["Content-Type"]
                photo = self.path.endswith("/sendPhoto")
                owner.requests.append(
                    {
                        "path": self.path,
                        "method": self.path.rsplit("/", 1)[-1],
                        "content_type": kind,
                        "body": _form(kind, body) if photo else json.loads(body),
                    }
                )
                code, payload = owner.replies.pop(0) if owner.replies else (200, None)
                if payload is None:
                    result = {"message_id": len(owner.requests)}
                    if photo:
                        result["photo"] = PHOTO_SIZES
                    payload = {"ok": True, "result": result}
                data = json.dumps(payload).encode("utf-8")
                # INCOMPLETE: the connection ends before the body (IncompleteRead).
                length = len(data) + 100 if payload is INCOMPLETE else len(data)
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(length))
                self.end_headers()
                self.wfile.write(data)
                if payload is INCOMPLETE:
                    self.close_connection = True

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def run_env(tmp_path, monkeypatch, db):
    """A data directory, the fake token, the stand-in server and the session."""

    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    monkeypatch.setenv("STOCK_DATA_DIR", str(data))
    monkeypatch.setenv(notify.TOKEN_ENV, TOKEN)
    monkeypatch.setenv(notify.CHAT_ENV, CHAT)
    monkeypatch.setattr(notify, "RETRY_DELAY_SECONDS", 0.0)

    @contextlib.contextmanager
    def session():
        yield db

    monkeypatch.setattr(notify, "_session", session)
    # The card is drawn by a stand-in (the real drawing: test_notify_card.py); RENDERS
    # holds what it was given, DRAWN what it returns.
    renders = []
    drawn = {"value": notify_card.Rendered(FAKE_PNG, None, 0.1, 1080, 2356)}

    def render(card):
        renders.append(card)
        return drawn["value"]

    monkeypatch.setattr(notify_card, "render", render)
    servers = []

    def telegram(*replies):
        server = Telegram(replies)
        servers.append(server)
        monkeypatch.setattr(notify, "API_BASE", server.base)
        return server

    _list_of_t(db)
    _ai_reading(db)

    def fail_render(reason):
        drawn["value"] = notify_card.Rendered(None, reason, 30.0)

    yield argparse.Namespace(
        data=data,
        logs=data / "logs",
        telegram=telegram,
        renders=renders,
        fail_render=fail_render,
    )
    for server in servers:
        server.close()


def _args(*argv):
    parser = argparse.ArgumentParser()
    notify.add_arguments(parser)
    return parser.parse_args(list(argv))


def _send(env, day=MONDAY, trigger="scheduler", at="08:45"):
    """A run of DAY at AT Taipei (serve's --now), as serve starts it."""

    return notify.run(
        _args(
            "--send",
            "--now",
            f"{day.isoformat()}T{at}",
            "--trigger",
            trigger,
            "--log-dir",
            str(env.logs),
        )
    )


def _log(env, day=MONDAY) -> str:
    return notify.log_path(env.logs, day).read_text(encoding="utf-8")


@linux_only
def test_a_trading_day_sends_once_and_a_restart_does_not_send_again(run_env, capsys):
    server = run_env.telegram()
    assert _send(run_env) == 0
    assert len(server.requests) == 1
    request = server.requests[0]
    # The card (#754 AC-2): sendPhoto, multipart, with the one-line caption.
    assert request["path"] == f"/bot{TOKEN}/sendPhoto"
    assert request["content_type"].startswith("multipart/form-data; boundary=")
    assert request["body"] == {
        "chat_id": CHAT,
        "caption": CAPTION,
        "parse_mode": "HTML",
        "photo": ("card.png", "image/png", FAKE_PNG),
    }
    # The card was drawn from the message's one read.
    assert [card.ai.picks[0].name for card in run_env.renders] == ["1477 聚陽"]
    log = _log(run_env)
    assert (
        "--- result status=sent mode=photo attempts=1 message_id=1 photo=1080x2356"
        in log
    )
    # The text is logged as before, with the caption and the card's size.
    assert f"\n{TITLE}\n" in log
    assert f"--- caption {CAPTION}" in log
    assert f"--- card width=1080 height=2356 bytes={len(FAKE_PNG)} seconds=0.1" in log
    # Again the same day (a restarted scheduler's catch-up, a second trigger): no send.
    assert _send(run_env) == 0
    assert len(server.requests) == 1
    assert "--- result status=skipped reason=already_sent" in _log(run_env)
    assert notify.day_done(run_env.logs, MONDAY)
    # The log has the start and end lines the watchdog reads.
    assert _log(run_env).count("end exit=0") == 2


@linux_only
def test_a_closed_day_sends_nothing(run_env, db):
    server = run_env.telegram()
    _closed(db, MONDAY)
    db.commit()
    assert _send(run_env) == 0
    assert server.requests == []
    assert "--- result status=skipped reason=non_trading_day" in _log(run_env)
    assert notify.day_done(run_env.logs, MONDAY)
    # A Saturday too (a manual run).
    assert _send(run_env, date(2026, 9, 5), "manual") == 0
    assert server.requests == []


def _methods(server):
    return [request["method"] for request in server.requests]


@linux_only
@pytest.mark.parametrize("reason", ["timeout", "no_browser", "exit_1", "empty_png"])
def test_a_card_that_cannot_be_drawn_sends_the_text(run_env, reason):
    """AC-2 (#754): the text goes instead, and the log says which and why."""

    server = run_env.telegram()
    run_env.fail_render(reason)
    assert _send(run_env) == 0
    assert _methods(server) == ["sendMessage"]
    assert server.requests[0]["body"]["text"].startswith(TITLE + "\n")
    assert server.requests[0]["body"]["parse_mode"] == "HTML"
    assert (
        f"--- result status=sent mode=text reason=render_failed:{reason}"
        " attempts=1 message_id=1"
    ) in _log(run_env)
    # One message a day, whichever it was.
    assert _send(run_env) == 0
    assert len(server.requests) == 1
    assert "--- result status=skipped reason=already_sent" in _log(run_env)


@linux_only
@pytest.mark.parametrize("broken", ["render", "import"])
def test_an_error_while_drawing_sends_the_text(run_env, monkeypatch, broken):
    """Review 6888784128 必修 1: an exception from the drawing, or a notify_card that
    cannot be imported, is render_failed and the text goes, not a failed day."""

    server = run_env.telegram()
    if broken == "render":

        def render(_card):
            raise RuntimeError("boom")

        monkeypatch.setattr(notify_card, "render", render)
        reason = "error:RuntimeError"
    else:
        monkeypatch.setitem(sys.modules, "worker.notify_card", None)
        # None in sys.modules: ModuleNotFoundError, an ImportError.
        reason = "error:ModuleNotFoundError"
    assert _send(run_env) == 0
    assert _methods(server) == ["sendMessage"]
    assert (
        f"--- result status=sent mode=text reason=render_failed:{reason}"
        " attempts=1 message_id=1"
    ) in _log(run_env)


@linux_only
def test_a_sent_photo_with_an_odd_answer_is_still_sent(run_env):
    """Review 6888784128 建議 3: only the size is unknown then."""

    server = run_env.telegram(
        (200, {"ok": True, "result": {"message_id": 7, "photo": 5}})
    )
    assert _send(run_env) == 0
    assert _methods(server) == ["sendPhoto"]
    log = _log(run_env)
    assert "--- result status=sent mode=photo attempts=1 message_id=7\n" in log


@linux_only
def test_a_photo_refused_with_a_400_sends_the_text_at_once(run_env):
    server = run_env.telegram(
        (400, {"ok": False, "description": "Bad Request: PHOTO_INVALID_DIMENSIONS"})
    )
    assert _send(run_env) == 0
    assert _methods(server) == ["sendPhoto", "sendMessage"]
    log = _log(run_env)
    assert (
        "--- result status=sent mode=text reason=photo_failed:http_400"
        " attempts=1 message_id=2"
    ) in log
    assert "--- photo failed http_400 Bad Request: PHOTO_INVALID_DIMENSIONS" in log


@linux_only
def test_a_photo_failing_twice_sends_the_text(run_env):
    server = run_env.telegram(
        (502, {"ok": False, "description": "Bad Gateway"}), (502, None)
    )
    assert _send(run_env) == 0
    assert _methods(server) == ["sendPhoto", "sendPhoto", "sendMessage"]
    assert (
        "--- result status=sent mode=text reason=photo_failed:http_502,http_502"
        " attempts=1 message_id=3"
    ) in _log(run_env)


@linux_only
def test_a_failed_send_is_tried_once_more_then_recorded_as_failed(run_env, capsys):
    server = run_env.telegram(
        (400, {"ok": False, "description": "Bad Request"}),
        (502, {"ok": False, "description": "Bad Gateway"}),
        (502, None),
    )
    assert _send(run_env) == 1
    assert _methods(server) == ["sendPhoto", "sendMessage", "sendMessage"]
    log = _log(run_env)
    # Both attempts' reasons, in order (review 6882303076 item 4), then the photo's.
    assert (
        "--- result status=failed reason=http_502,http_502 attempts=2"
        " photo=photo_failed:http_400 detail="
    ) in log
    assert "end exit=1" in log
    assert not notify.day_done(run_env.logs, MONDAY)
    # The next try (catch-up or by hand) sends.
    assert _send(run_env, trigger="manual") == 0
    assert "--- result status=sent" in _log(run_env)


@linux_only
def test_a_first_failure_then_success_is_sent(run_env):
    server = run_env.telegram((500, {"ok": False, "description": "Internal"}))
    assert _send(run_env) == 0
    assert len(server.requests) == 2
    assert "--- result status=sent mode=photo attempts=2" in _log(run_env)


@linux_only
@pytest.mark.parametrize("code", [400, 401, 403])
def test_a_permanent_error_is_not_retried(run_env, code):
    """A wrong token or chat id stays wrong (review 6882303076 item 3)."""

    refused = (code, {"ok": False, "description": "Unauthorized"})
    server = run_env.telegram(refused, refused)
    assert _send(run_env) == 1
    # Once as a photo, once as the text (#754).
    assert _methods(server) == ["sendPhoto", "sendMessage"]
    assert (
        f"--- result status=failed reason=http_{code} attempts=1"
        f" photo=photo_failed:http_{code}"
    ) in _log(run_env)


@linux_only
def test_a_text_telegram_cannot_parse_is_a_parse_error_sent_once(run_env):
    """AC-2 (#742): the same HTML is refused again, so it is not retried."""

    refused = (
        400,
        {
            "ok": False,
            "error_code": 400,
            "description": "Bad Request: can't parse entities: Unsupported start"
            ' tag "x" at byte offset 12',
        },
    )
    server = run_env.telegram(refused, refused)
    assert _send(run_env) == 1
    assert _methods(server) == ["sendPhoto", "sendMessage"]
    assert server.requests[0]["body"]["parse_mode"] == "HTML"
    assert server.requests[1]["body"]["parse_mode"] == "HTML"
    log = _log(run_env)
    assert (
        "--- result status=failed reason=parse_error attempts=1"
        " photo=photo_failed:parse_error"
    ) in log
    assert "detail=parse_error http_400 Bad Request: can't parse entities" in log
    assert not notify.day_done(run_env.logs, MONDAY)


@linux_only
def test_a_429_waits_its_retry_after_when_it_is_short(run_env, monkeypatch):
    waits = []
    monkeypatch.setattr(notify.time, "sleep", waits.append)
    server = run_env.telegram(
        (429, {"ok": False, "parameters": {"retry_after": 7}}),
    )
    assert _send(run_env) == 0
    assert len(server.requests) == 2 and waits == [7.0]


@linux_only
def test_a_429_with_a_long_retry_after_fails_without_waiting(run_env, monkeypatch):
    waits = []
    monkeypatch.setattr(notify.time, "sleep", waits.append)
    too_many = (
        429,
        {
            "ok": False,
            "description": "Too Many",
            "parameters": {"retry_after": 3600},
        },
    )
    server = run_env.telegram(too_many, too_many)
    assert _send(run_env) == 1
    assert _methods(server) == ["sendPhoto", "sendMessage"] and waits == []
    assert (
        "reason=http_429 attempts=1 photo=photo_failed:http_429"
        " detail=http_429 Too Many retry_after=3600"
    ) in _log(run_env)


@linux_only
def test_a_cut_answer_is_retried(run_env):
    """http.client.IncompleteRead is no OSError: it is a network failure too."""

    server = run_env.telegram((200, INCOMPLETE))
    assert _send(run_env) == 0
    assert len(server.requests) == 2
    assert "--- result status=sent mode=photo attempts=2" in _log(run_env)


@linux_only
@pytest.mark.parametrize("at", ["20:00", "13:30", "08:44"])
def test_a_scheduled_run_outside_0845_to_1330_does_not_send(run_env, at):
    """A missed 08:45 that APScheduler runs as the host wakes at 20:00 (review
    6882303076 item 1): the job's own rule, not APScheduler's settings."""

    server = run_env.telegram()
    assert _send(run_env, at=at) == 0
    assert server.requests == []
    assert f"--- result status=skipped reason=too_late at={at}" in _log(run_env)
    assert not notify.day_done(run_env.logs, MONDAY)
    # 13:29 is still in the window.
    assert _send(run_env, at="13:29") == 0
    assert len(server.requests) == 1


@linux_only
def test_a_manual_run_sends_after_the_close(run_env):
    server = run_env.telegram()
    assert _send(run_env, trigger="manual", at="20:00") == 0
    assert len(server.requests) == 1


@linux_only
def test_a_closed_day_after_the_close_is_a_non_trading_day_not_too_late(run_env, db):
    """too_late marks a missed trading day only (review 6882535482): the watchdog reports
    it, so a holiday's scheduled run at 20:00 records non_trading_day."""

    server = run_env.telegram()
    _closed(db, MONDAY)
    db.commit()
    assert _send(run_env, at="20:00") == 0
    assert server.requests == []
    log = _log(run_env)
    assert "--- result status=skipped reason=non_trading_day" in log
    assert "too_late" not in log


@linux_only
def test_the_token_is_in_no_log_output_or_error(run_env, monkeypatch, capsys):
    # Answers that echo the token, then the network gone (a closed port): the photo's
    # two attempts and the text's (#754 AC-2).
    echo = (500, {"ok": False, "description": f"bad bot{TOKEN}"})
    server = run_env.telegram(echo, echo, echo)
    original = notify._post

    def then_offline(token, *args):
        if len(server.requests) == 3:
            monkeypatch.setattr(notify, "API_BASE", "http://127.0.0.1:9")
        return original(token, *args)

    monkeypatch.setattr(notify, "_post", then_offline)
    code = _send(run_env)
    out = capsys.readouterr()
    log = _log(run_env)
    assert code == 1
    assert _methods(server) == ["sendPhoto", "sendPhoto", "sendMessage"]
    assert "reason=http_500,network:" in log and "http_500 bad bot<token>" in log
    assert "photo=photo_failed:http_500,http_500" in log
    assert "--- photo failed http_500 bad bot<token> | http_500 bad bot<token>" in log
    for text in (log, out.out, out.err):
        assert TOKEN not in text
        assert TOKEN.split(":")[1] not in text
    assert notify.mask(f"https://api.telegram.org/bot{TOKEN}/x", None) == (
        "https://api.telegram.org/bot<token>/x"
    )


@linux_only
@pytest.mark.parametrize("unset", [notify.TOKEN_ENV, notify.CHAT_ENV])
def test_without_the_variables_the_run_is_not_configured_and_no_failure(
    run_env, monkeypatch, unset
):
    server = run_env.telegram()
    monkeypatch.setenv(unset, "")
    assert _send(run_env) == 0
    assert server.requests == []
    assert f"--- result status=not_configured missing={unset}" in _log(run_env)
    # Not the end of the day (review 6882303076 item 5): a token set before 13:30 is
    # caught up.
    assert not notify.day_done(run_env.logs, MONDAY)


@linux_only
@pytest.mark.parametrize("chat", ["-1001234567890", "@channel", "0"])
def test_a_group_or_channel_chat_is_refused(run_env, monkeypatch, chat):
    """The US index figures go to the user's own chat only (#1 decision 6717084453)."""

    server = run_env.telegram()
    monkeypatch.setenv(notify.CHAT_ENV, chat)
    assert _send(run_env) == 1
    assert server.requests == []
    assert "--- result status=failed reason=chat_not_private" in _log(run_env)


@linux_only
def test_a_run_that_finds_the_lock_held_skips(run_env):
    server = run_env.telegram()
    lock = job.FileLock(job.lock_path(run_env.data, notify.LOCK))
    assert lock.acquire()
    try:
        assert _send(run_env) == 0
    finally:
        lock.release()
    assert server.requests == []
    assert "--- result status=skipped reason=already_running" in _log(run_env)
    assert not notify.day_done(run_env.logs, MONDAY)
    # The other jobs' locks are not its own.
    assert notify.LOCK not in job.JOBS


def test_the_dry_run_prints_the_message_and_sends_and_writes_nothing(run_env, capsys):
    server = run_env.telegram()
    assert notify.run(_args("--dry-run", "--date", MONDAY.isoformat())) == 0
    out = capsys.readouterr().out
    # The caption, then the text as it is sent, with its tags (#742, #754).
    assert out.startswith(f"configured=yes\ncaption={CAPTION}\n" + TITLE + "\n")
    assert TOKEN not in out and CHAT not in out
    assert server.requests == []
    assert not run_env.logs.exists()
    # No card unless asked for.
    assert run_env.renders == []


def test_the_dry_run_draws_the_card_with_image_out(run_env, tmp_path, capsys):
    server = run_env.telegram()
    target = tmp_path / "card.png"
    argv = ("--dry-run", "--date", MONDAY.isoformat(), "--image-out", str(target))
    assert notify.run(_args(*argv)) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[1] == (
        f"image={target} width=1080 height=2356 bytes={len(FAKE_PNG)} seconds=0.1"
    )
    assert lines[2].startswith("caption=") and lines[3] == TITLE
    assert target.read_bytes() == FAKE_PNG
    assert server.requests == [] and not run_env.logs.exists()
    # A card that cannot be drawn: exit 1, the text still printed.
    run_env.fail_render("timeout")
    assert notify.run(_args(*argv)) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[1] == "image=failed reason=timeout" and lines[3] == TITLE
    # Only with --dry-run.
    assert notify.argument_problem(_args("--send", "--image-out", str(target)))


def test_the_dry_run_says_not_configured_and_a_closed_day(
    run_env, monkeypatch, db, capsys
):
    monkeypatch.delenv(notify.TOKEN_ENV)
    _closed(db, MONDAY)
    db.commit()
    assert notify.run(_args("--dry-run", "--date", MONDAY.isoformat())) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[:2] == ["configured=no", "non_trading_day=2026-09-07（排程這天不送）"]


def test_the_command_needs_dry_run_or_send_and_a_real_date():
    with pytest.raises(SystemExit):
        _args()
    with pytest.raises(SystemExit):
        _args("--dry-run", "--send")
    assert notify.argument_problem(_args("--dry-run", "--date", "2026-02-30"))
    assert notify.argument_problem(_args("--dry-run", "--date", "2026-11-16")) is None


def test_old_logs_are_removed_after_90_days(run_env, tmp_path):
    run_env.logs.mkdir(parents=True, exist_ok=True)
    old = run_env.logs / "notify-20260101.log"
    old.write_text("x\n", encoding="utf-8")
    stamp = (datetime.now() - timedelta(days=91)).timestamp()

    os.utime(old, (stamp, stamp))
    runner = notify._Run(_args("--send", "--log-dir", str(run_env.logs)))
    runner._remove_old_logs()
    assert not old.exists()


def test_serve_reads_the_day_results_from_the_log(tmp_path):
    logs = tmp_path
    path = notify.log_path(logs, MONDAY)
    path.write_text(
        "===== start\n--- result status=failed reason=http_502 attempts=2\n"
        "===== end exit=1 seconds=31\n"
        "===== start\n--- result status=skipped reason=already_running\n",
        encoding="utf-8",
    )
    assert notify.day_results(logs, MONDAY) == [
        "failed",
        "skipped reason=already_running",
    ]
    assert not notify.day_done(logs, MONDAY)
    assert notify.day_results(logs, date(2026, 9, 8)) == []
    assert Path(path).name == "notify-20260907.log"


# --- the AI list cannot break the message (as #1042 review 7198038610, 1) -------------


def _broken(*args, **kwargs):
    raise KeyError("output_json of another shape")


@pytest.mark.parametrize("where", ["view", "ai_list"])
def test_an_ai_list_that_cannot_be_read_still_sends_the_rest(db, monkeypatch, where):
    import app.ai_list

    if where == "view":
        monkeypatch.setattr(app.ai_list, "view", _broken)
    else:
        monkeypatch.setattr(notify, "_ai_list", _broken)
    _list_of_t(db)
    card = notify.read(db, MONDAY)
    message = notify.text(card)
    assert card.ai.status == notify.AI_ERROR and card.ai.error == "KeyError"
    assert notify.AI_UNREADABLE in message.splitlines()
    assert "（規則名單 1 檔見今日名單頁）" in message and "隔夜美股" in message
    html = notify_card.card_html(card)
    assert notify.AI_UNREADABLE in html and notify_card.card_height(card) > 0


@linux_only
def test_a_run_with_an_unreadable_ai_list_is_sent(run_env, monkeypatch):
    import app.ai_list

    monkeypatch.setattr(app.ai_list, "view", _broken)
    server = run_env.telegram()
    assert _send(run_env) == 0
    assert len(server.requests) == 1
    log = _log(run_env)
    assert "--- result status=sent mode=photo" in log
    assert "--- ai_list unreadable error=KeyError" in log
    assert notify.AI_UNREADABLE in log
