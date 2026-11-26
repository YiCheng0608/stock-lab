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
    ScheduleRun,
    TradingCalendarDay,
)
from app.preopen_news import check_rows, replace_check
from test_candidates import T, signal, stock
from test_preopen import CHECKED, _news, _recomputed, _taipei
from test_preopen import _list as _preopen_list
from worker import job, notify, notify_card, pipeline
from worker.candidates import compute_daily_candidates

ON_LINUX = sys.platform.startswith("linux")
linux_only = pytest.mark.skipif(not ON_LINUX, reason="fcntl lock: Linux only (#333)")
TOKEN = "123456789:AAFakeTokenForTestsOnly_abcdefghijk"
CHAT = "987654321"
# T (Friday 2026-09-04) is the list's day; the message is Monday's.
MONDAY = date(2026, 9, 7)


# --- the message, from the API's shapes ------------------------------------------------


def _item(rank, symbol, name, levels):
    return {
        "rank": rank,
        "instrument": {"symbol": symbol, "name": name},
        "levels": levels,
    }


def _breakout(entry, stop, target):
    return {
        "entry_type": "breakout",
        "entry": entry,
        "entry_zone": {"low": entry, "high": entry},
        "invalid_price": stop,
        "target_1": target,
    }


def _pullback(low, high, stop, target):
    return {
        "entry_type": "pullback",
        "entry": (low + high) / 2,
        "entry_zone": {"low": low, "high": high},
        "invalid_price": stop,
        "target_1": target,
    }


# The list was checked before the open (#759): the rows without overnight news show no
# mark and the card no 「尚未完成」 line.
CHECK = {"status": "checked"}
BREAKOUT = _breakout(61.1, 58.5, 65.27)
PULLBACK = _pullback(110.99, 115.21, 110.29, 121.24)
LISTING = {
    "status": "success",
    "preopen_check": CHECK,
    "candidate_count": 2,
    "items": [_item(1, "2453", "凌群", BREAKOUT), _item(2, "2882", "國泰金", PULLBACK)],
}
TITLE = "📋 <b>今日名單｜09/07（一）</b>"
BREAKOUT_LINE = "　進場 61.10｜停損 58.50｜目標 65.27"
PULLBACK_LINE = "　進場 110.99～115.21｜停損 110.29｜目標 121.24"


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


# AC-1 (#742): both sections with two rows or more, one row without its levels, a type of
# neither section, more rows than the twenty shown, and a US index up, down, flat and
# missing.
CARD_ITEMS = [
    _item(1, "2453", "凌群", BREAKOUT),
    _item(2, "2882", "國泰金", PULLBACK),
    _item(3, "2618", "長榮航", _breakout(47.75, 46.31, 50.05)),
    _item(4, "2881", "富邦金", _pullback(88.1, 90.0, 87.0, 95.5)),
    _item(5, "1101", "台泥", {**BREAKOUT, "entry": 70.0}),  # entry above the target
    _item(6, "0006", "名", BREAKOUT),
    _item(7, "9999", "別型", {**BREAKOUT, "entry_type": "reversal"}),
    *(_item(rank, f"{rank:04d}", "名", BREAKOUT) for rank in range(8, 21)),
]
CARD_US = [
    _us("SPX", 7561.67, -0.004),
    _us("IXIC", 25136.27, 0.0),
    _us("DJI", 52347.55, 0.001),
    _missing("SOX", "fetch_failed"),
]


def test_the_card_has_the_sections_the_levels_line_and_the_marked_us_indexes():
    listing = {
        "status": "success",
        "preopen_check": CHECK,
        "candidate_count": 23,
        "items": CARD_ITEMS,
    }
    text = notify.compose(MONDAY, T, listing, CARD_US)
    generic = [
        line
        for rank in range(8, 21)
        for line in (f"<b>{rank:04d} 名</b>", BREAKOUT_LINE)
    ]
    assert text == "\n".join(
        [
            TITLE,
            "09/04（五）收盤後產生・23 檔",
            "",
            "🚀 <b>突破（17 檔）</b>",
            "<b>2453 凌群</b>",
            BREAKOUT_LINE,
            "<b>2618 長榮航</b>",
            "　進場 47.75｜停損 46.31｜目標 50.05",
            "<b>1101 台泥</b>",
            "　價位不完整",
            "<b>0006 名</b>",
            BREAKOUT_LINE,
            *generic,
            "",
            "↩️ <b>回踩（2 檔）</b>",
            "<b>2882 國泰金</b>",
            PULLBACK_LINE,
            "<b>2881 富邦金</b>",
            "　進場 88.10～90.00｜停損 87.00｜目標 95.50",
            "",
            "<b>其他（1 檔）</b>",
            "<b>9999 別型</b>",
            "　價位不完整",
            "另 3 檔見今日名單頁",
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
    assert notify.compose(MONDAY, T, LISTING, closed) == "\n".join(
        [
            TITLE,
            "09/04（五）收盤後產生・2 檔",
            "",
            "🚀 <b>突破（1 檔）</b>",
            "<b>2453 凌群</b>",
            BREAKOUT_LINE,
            "",
            "↩️ <b>回踩（1 檔）</b>",
            "<b>2882 國泰金</b>",
            PULLBACK_LINE,
            "",
            "🌎 <b>隔夜美股</b> 美股休市（09/03 收盤）",
            *US_ROWS,
            "來源 FinMind",
        ]
    )


@pytest.mark.parametrize(
    "status, head",
    [
        ("partial", "名單：無資料（09/04（五）的名單沒有產生；daily：partial）"),
        (None, "名單：無資料（09/04（五）的名單沒有產生；daily 沒有紀錄）"),
    ],
)
def test_a_missing_list_says_no_data_and_still_sends_the_us_indexes(status, head):
    text = notify.compose(
        MONDAY, T, {"status": "not_computed", "items": []}, US, status
    )
    assert text == "\n".join(
        [
            TITLE,
            head,
            "",
            "🌎 <b>隔夜美股</b>（09/04 收盤）",
            *US_ROWS,
            "來源 FinMind",
        ]
    )


def test_an_empty_list_gives_its_reason():
    listing = {
        "status": "success",
        "preopen_check": CHECK,
        "candidate_count": 0,
        "zero_reason_text": "當日沒有成立（條件成立）的策略訊號",
        "items": [],
    }
    lines = notify.compose(MONDAY, T, listing, US).splitlines()
    assert lines[:3] == [
        TITLE,
        "09/04（五）收盤後產生・0 檔（當日沒有成立（條件成立）的策略訊號）",
        "",
    ]
    assert lines[3].startswith("🌎 ")


def test_the_data_texts_are_escaped():
    """AC-2 (#742): a name, a reason or a status with & < > reaches Telegram escaped."""

    listing = {
        "status": "success",
        "preopen_check": CHECK,
        "candidate_count": 1,
        "items": [_item(1, "1234", "A&B<C>", BREAKOUT)],
    }
    text = notify.compose(MONDAY, T, listing, US)
    assert "<b>1234 A&amp;B&lt;C&gt;</b>" in text.splitlines()
    _well_formed(text)
    empty = {
        "status": "success",
        "preopen_check": CHECK,
        "candidate_count": 0,
        "zero_reason_text": "<沒有> & 訊號",
        "items": [],
    }
    assert "（&lt;沒有&gt; &amp; 訊號）" in notify.compose(MONDAY, T, empty, US)
    missing = notify.compose(
        MONDAY, T, {"status": "not_computed", "items": []}, US, "<x>&"
    )
    assert "daily：&lt;x&gt;&amp;）" in missing
    _well_formed(missing)


def test_missing_us_indexes_say_no_data():
    nothing = [_missing(symbol) for symbol in ("SPX", "IXIC", "DJI", "SOX")]
    text = notify.compose(MONDAY, T, LISTING, nothing)
    assert text.endswith("\n🌎 <b>隔夜美股</b>：無資料（美股尚未更新）")


def test_the_us_freshness_follows_the_today_page():
    def head(lines):
        return next(line for line in lines if line.startswith("🌎 "))

    # One index behind: its own date and 非最新.
    behind = [*US[:3], _us("SOX", 10000.0, 0.01, "2026-09-03", "stale")]
    lines = notify.compose(MONDAY, T, LISTING, behind).splitlines()
    assert head(lines) == "🌎 <b>隔夜美股</b>"
    assert "🔴 費半　10,000.00　+1.00%（09/03 收盤） 非最新" in lines
    assert "🟢 S&amp;P 500　7,561.67　−0.40%（09/04 收盤）" in lines
    # None of the expected night.
    stale = [
        _us(i["symbol"], i["close"], i["change_pct"], "2026-09-02", "stale") for i in US
    ]
    lines = notify.compose(MONDAY, T, LISTING, stale).splitlines()
    assert head(lines) == "🌎 <b>隔夜美股</b> 美股尚未更新（09/02 收盤）"
    assert not any("非最新" in line for line in lines)


def test_the_us_marks_follow_the_rounded_change_and_two_sources_are_named():
    tiny = [
        _us("SPX", 7561.67, -0.00001),
        _us("IXIC", 25136.27, None),
        {**_us("DJI", 52347.55, 0.001), "source": {"label": "FRED"}},
    ]
    lines = notify.compose(MONDAY, T, LISTING, tiny).splitlines()
    # -0.001% shows as 0.00%: flat, not down.
    assert "⚪ S&amp;P 500　7,561.67　0.00%" in lines
    # An unknown change has no mark.
    assert "NASDAQ　25,136.27　—" in lines
    assert lines[-1] == "來源 FinMind；FRED"


def test_rows_past_the_twenty_shown_are_counted_in_the_last_line():
    """Review 6882303076 item 7: N is the list's count less the rows shown."""

    items = [_item(rank, f"{rank:04d}", "名", BREAKOUT) for rank in range(1, 22)]
    listing = {
        "status": "success",
        "preopen_check": CHECK,
        "candidate_count": 25,
        "items": items,
    }
    lines = notify.compose(MONDAY, T, listing, US).splitlines()
    assert lines[1] == "09/04（五）收盤後產生・25 檔"
    assert lines[3] == "🚀 <b>突破（20 檔）</b>"
    assert lines.count(BREAKOUT_LINE) == 20
    assert "<b>0021 名</b>" not in lines
    assert "另 5 檔見今日名單頁" in lines


def test_a_long_list_is_cut_to_telegrams_limit_with_its_tags():
    """AC-2 (#742): the limit counts the tags, the entities and an emoji as two."""

    assert notify.length("🚀") == 2 and notify.length("<b>&amp;</b>") == 12
    items = [
        _item(rank, f"{rank:04d}", "&" * 150, BREAKOUT if rank % 2 else PULLBACK)
        for rank in range(1, 21)
    ]
    listing = {
        "status": "success",
        "preopen_check": CHECK,
        "candidate_count": 20,
        "items": items,
    }
    text = notify.compose(MONDAY, T, listing, US)
    assert notify.length(text) <= notify.MAX_CHARS
    _well_formed(text)
    lines = text.splitlines()
    shown = sum(1 for line in lines if line.startswith("　進場"))
    assert 0 < shown < 20
    assert f"另 {20 - shown} 檔見今日名單頁" in lines
    # Cut from the end of the list: the lowest ranks go first.
    assert f"<b>{shown:04d} {'&amp;' * 150}</b>" in lines
    assert f"<b>{shown + 1:04d} {'&amp;' * 150}</b>" not in lines
    assert lines[-1] == "來源 FinMind"


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


def test_the_message_reads_the_list_of_the_session_before_and_todays_us_indexes(db):
    _list_of_t(db)
    lines = notify.message(db, MONDAY).splitlines()
    assert lines[1:8] == [
        "09/04（五）收盤後產生・1 檔",
        # No pre-open check of the list was stored (#759).
        "開盤前檢查：尚未完成",
        # Nor a pre-market AI reading (#1042).
        "今日 AI 判讀尚未完成",
        "",
        "🚀 <b>突破（1 檔）</b>",
        "<b>1101 名1101</b>",
        "　進場 100.00｜停損 98.00｜目標 103.20",
    ]
    # Only SOX is stored: the others say so; SOX is Friday's, the night before Monday.
    assert "🔴 費半　103.00　+3.00%" in lines
    assert "S&amp;P 500　無資料（未取得）" in lines
    assert lines[-1] == "來源 FinMind"


def test_no_older_list_stands_in_for_the_missing_one(db):
    _list_of_t(db)
    db.add(ScheduleRun(job="daily", target_date=date(2026, 9, 7), status="failed"))
    db.commit()
    # Tuesday's message wants Monday's list: Friday's is not shown instead.
    text = notify.message(db, date(2026, 9, 8))
    assert "名單：無資料（09/07（一）的名單沒有產生；daily：failed）" in text
    assert "1101" not in text


def test_the_session_before_skips_the_closed_days(db):
    _list_of_t(db)
    _closed(db, date(2026, 9, 7))
    assert notify.is_trading_day(db, date(2026, 9, 7)) is False
    assert notify.is_trading_day(db, date(2026, 9, 5)) is False  # Saturday
    assert notify.previous_session(db, date(2026, 9, 8)) == T
    assert "09/04（五）收盤後產生・1 檔" in notify.message(db, date(2026, 9, 8))


# AC-1 (#759): the pre-open check of the list, as /api/candidates judges it.
PENDING_HTML = '<div class="preopen-pending line">開盤前檢查：尚未完成</div>'


def _preopen_case(db, case):
    """The list of T (1101, 2330) and its pre-open check of CASE."""

    run, _ = _preopen_list(db)
    late = _taipei(2026, 9, 4, 23, 0)
    if case == "news":
        _news(db, ["1101"], published=late, collected=late)  # 可能負向
        _news(db, ["1101"], published=late, direction="positive", collected=late)
        _news(db, ["2330"], published=late, direction=None, collected=late)
        db.commit()
    if case in ("news", "no_news", "other_run"):
        replace_check(db, run, check_rows(db, run, CHECKED))
        db.commit()
    if case == "other_run":
        # The list recomputed after the check: the check is the older run's.
        _recomputed(db, run, CHECKED + timedelta(minutes=1), move=True)
    return notify.read(db, MONDAY)


def _rows_html(card):
    return [notify_card._row_html(row) for row in card.rows]


def test_rows_with_overnight_news_are_marked_as_the_today_page_marks_them(db):
    card = _preopen_case(db, "news")
    lines = notify.text(card).splitlines()
    assert "<b>1101 名1101</b>　隔夜新聞 2（可能負向 1）" in lines
    # No 可能負向 one: no brackets (the not judged yet item counts as news).
    assert "<b>2330 名2330</b>　隔夜新聞 1" in lines
    assert notify.PREOPEN_PENDING not in lines
    html = notify_card.card_html(card)
    assert PENDING_HTML not in html
    marks = {
        row.name: notify_card._row_html(row).split('<span class="preopen', 1)[1]
        for row in card.rows
    }
    assert marks == {
        "1101 名1101": ' muted line">隔夜新聞 2（<span class="down">可能負向 1</span>）'
        "</span></div>",
        "2330 名2330": ' muted line">隔夜新聞 1</span></div>',
    }
    assert all('class="row grid marked"' in row for row in _rows_html(card))


def test_a_checked_list_without_overnight_news_marks_nothing(db):
    card = _preopen_case(db, "no_news")
    text = notify.text(card)
    assert "隔夜新聞" not in text and notify.PREOPEN_PENDING not in text
    assert "<b>1101 名1101</b>" in text.splitlines()
    html = notify_card.card_html(card)
    assert PENDING_HTML not in html and "隔夜新聞" not in html
    assert all('class="row grid"' in row for row in _rows_html(card))


@pytest.mark.parametrize("case", ["none", "other_run"])
def test_a_list_without_its_own_check_says_not_done_yet(db, case):
    """No check stored, or the check of an older run of the date (the list recomputed
    after it): one 「尚未完成」 line, no older result."""

    card = _preopen_case(db, case)
    lines = notify.text(card).splitlines()
    assert lines[1].startswith("09/04（五）收盤後產生・")
    assert lines[2] == "開盤前檢查：尚未完成"
    assert "<b>1101 名1101</b>" in lines and "<b>2330 名2330</b>" in lines
    assert "隔夜新聞" not in "".join(lines)
    html = notify_card.card_html(card)
    assert html.count(PENDING_HTML) == 1 and "隔夜新聞" not in html
    assert html.index(PENDING_HTML) < html.index("</header>")


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
        "caption": "<b>今日名單 09/07（一）</b>・突破 1",
        "parse_mode": "HTML",
        "photo": ("card.png", "image/png", FAKE_PNG),
    }
    # The card was drawn from the message's one read.
    assert [card.rows[0].name for card in run_env.renders] == ["1101 名1101"]
    log = _log(run_env)
    assert (
        "--- result status=sent mode=photo attempts=1 message_id=1 photo=1080x2356"
        in log
    )
    # The text is logged as before, with the caption and the card's size.
    assert f"\n{TITLE}\n" in log
    assert "--- caption <b>今日名單 09/07（一）</b>・突破 1" in log
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
    assert out.startswith(
        "configured=yes\ncaption=<b>今日名單 09/07（一）</b>・突破 1\n" + TITLE + "\n"
    )
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


# --- the pre-market AI reading cannot break the message (#1042 review 7198038610, 1) ----


def _broken(*args, **kwargs):
    raise KeyError("output_json of another shape")


@pytest.mark.parametrize("where", ["view", "ai_view"])
def test_an_ai_reading_that_cannot_be_read_still_sends_the_list(db, monkeypatch, where):
    import app.premarket_ai

    if where == "view":
        monkeypatch.setattr(app.premarket_ai, "view", _broken)
    else:
        monkeypatch.setattr(notify, "_ai_view", _broken)
    _list_of_t(db)
    card = notify.read(db, MONDAY)
    message = notify.text(card)
    assert card.ai.status == notify.AI_ERROR and card.ai.error == "KeyError"
    assert notify.AI_UNREADABLE in message.splitlines()
    assert "<b>1101 名1101</b>" in message and "隔夜美股" in message
    html = notify_card.card_html(card)
    assert f'<div class="ai-line line">{notify.AI_UNREADABLE}</div>' in html
    assert "1101" in html and notify_card.card_height(card) > 0


@linux_only
def test_a_run_with_an_unreadable_ai_reading_is_sent(run_env, monkeypatch):
    import app.premarket_ai

    monkeypatch.setattr(app.premarket_ai, "view", _broken)
    server = run_env.telegram()
    assert _send(run_env) == 0
    assert len(server.requests) == 1
    log = _log(run_env)
    assert "--- result status=sent mode=photo" in log
    assert "--- premarket_ai unreadable error=KeyError" in log
    assert notify.AI_UNREADABLE in log
