"""The daily Telegram message: ``python -m worker.cli notify`` (#728).

Each trading day at 08:45 Taipei, serve runs ``notify --send``. It sends one message to the
user's own chat: a picture card (#754, the user's choice) with the Bot API ``sendPhoto``,
and the text card of #742 with ``sendMessage`` when the picture cannot be drawn or sent.
Both come from one read of the database (``read`` gives a ``Content``), so the picture and
the text have the same rows, sections, levels and US lines, word for word:

- 今日名單: the list of the session before today (D - 1: the weekday before, skipping the
  days ``trading_calendar_days`` marks closed), as ``/api/candidates?date=D-1`` gives it
  (``app.candidate_view.candidate_list``): its date and count, then the rows in the
  sections 突破 and 回踩 (``entry_type``; any other type under 其他), each in the page's
  rank order: the code and name, the entry, the stop and the target (a pullback's entry
  「X～Y」) by the today page's rules, or 「價位不完整」. No other list stands in for a
  missing one: it reads 「無資料（…）」 with the day's daily status.
- 隔夜美股: ``app.market_overview.foreign_indices`` for today, the four indexes of the today
  page's line (``overnight_us``, #681), each up, down or flat in the Taiwan colours, with
  its freshness (美股休市, 非最新, 美股尚未更新), the close date and the source's name.

The picture (``worker.notify_card``): an HTML page in the dark terminal layout of
docs/DESIGN_SYSTEM.md, a table per section and the US block (red up, green down), drawn to
a PNG by the image's Chromium in a temporary directory that is removed afterwards, killed
past its time limit. Its caption is one line, 「今日名單 11/13（五）・突破 8、回踩 9」.

The text: ``parse_mode=HTML`` for the bold title, section heads and row names, marked 🚀
突破 and ↩️ 回踩, the US indexes 🔴 up, 🟢 down or ⚪ flat. The 4096 characters are counted
with the tags; rows are cut from the end with 「另 N 檔見今日名單頁」. The caption and the
picture's page escape the data's text too (``html.escape``: names, reasons, sources).

The token and the chat id come from ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID``, which
reach the scheduler container through compose's ``env_file`` (docs/ops/SETUP.md). Without
them the run records ``not_configured`` and is no failure. The chat id must be a positive
integer, a private chat: the US index figures go to the user's own chat only (their
licences, #1 decision 6717084453); a group or channel id is refused. The token never reaches
a log line, an error or the output: the URL that holds it is built here and never printed,
and every line is masked first.

The record is the day's log ``<logs>/notify-YYYYMMDD.log`` (the target day; no table): a
``===== start`` line, the text, the caption and the picture's size, one ``--- result
status=…`` line and a ``===== end exit=N`` line. The result is ``sent mode=photo`` (with
Telegram's largest kept size, ``photo=<w>x<h>``), ``sent mode=text reason=<why>`` (the
picture's ``render_failed:<reason>``, or ``photo_failed:<each attempt's reason>`` for a
sendPhoto refused with a 4xx or failing after its retry), ``not_configured``, ``failed``
(the text failed too: its reasons, then ``photo=<why>``) or ``skipped`` with a reason. A
run that finds ``status=sent`` of either mode in the day's log skips (``already_sent``), so
a restarted scheduler never sends twice; the lock ``<data>/locks/notify.lock`` keeps two
runs apart and is no other job's. A scheduled run (``--trigger scheduler``) sends only
between 08:45 and 13:30 Taipei and records ``skipped reason=too_late`` otherwise, whatever
APScheduler does with a missed trigger. A network failure, a timeout, a 5xx or a 429 is
tried once more (``_post``), for the photo and the text alike; another 4xx is not (a 400
``can't parse entities`` is ``parse_error``). A failure is ``failed`` with exit 1, which the
watchdog reports (``notify_failed``; ``notify_missing`` when the day has no end line;
``notify_missed`` when a trading day has only ``too_late``). ``--dry-run`` prints the
caption and the text and sends nothing; ``--image-out <path>`` draws the picture there too.

Not through ``worker.job`` (#728 decision 6881879639): the run only reads the database and
sends one message, so it needs neither the memory threshold nor the git check, and it runs
in maintenance mode too.

Only the standard library at the top: serve imports the log reading here
(``worker.notify_card`` is imported when the card is drawn).
"""

from __future__ import annotations

import argparse
import html
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

from . import job

TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
CHAT_ENV = "TELEGRAM_CHAT_ID"
API_BASE = "https://api.telegram.org"
LOCK = "notify"
LOG_PREFIX = "notify"
# serve's trigger (Monday to Friday) and the end of its catch-up: a message after the close
# is of no use for the day.
SEND_TIME = (8, 45)
CATCH_UP_END = (13, 30)
TIMEOUT_SECONDS = 20.0
# The PNG is a few hundred KB (#754 AC-1): more room for the upload.
PHOTO_TIMEOUT_SECONDS = 30.0
RETRY_DELAY_SECONDS = 30.0
ATTEMPTS = 2
# A 429 asking to wait longer is not waited for (the run records failed).
RETRY_AFTER_MAX_SECONDS = 60.0
# serve's backstop adds its own 5 minutes; two attempts and the pause take about 70 seconds.
TIME_LIMIT_MINUTES = 5.0
# Telegram's limit for one message's text.
MAX_CHARS = 4096
# The today page's cap (app.candidate_view.MAX_LIMIT).
MAX_ITEMS = 20
LOG_RETENTION_DAYS = 90
SENT = "sent"
NOT_CONFIGURED = "not_configured"
FAILED = "failed"
SKIPPED = "skipped"
# The outcomes after which the day needs no run any more (serve's catch-up).
# not_configured is not one (#728 review 6882303076): a token set before 13:30 is caught up
# the same day.
DONE_RESULTS = (SENT, "skipped reason=non_trading_day")
RESULT_LINE = re.compile(r"^--- result status=(\S+)(?: reason=(\S+))?")
TOKEN_SHAPE = re.compile(r"\d{3,}:[A-Za-z0-9_-]{20,}")
WEEKDAYS = "一二三四五六日"
# The today page's short names (frontend candidates.ts OVERNIGHT_US_LABELS).
US_LABELS = {"SPX": "S&P 500", "IXIC": "NASDAQ", "DJI": "道瓊", "SOX": "費半"}
US_FRESH = ("latest", "us_market_closed")
US_REASONS = {"not_collected": "未取得", "fetch_failed": "抓取失敗"}
# The card (#742): the list's sections in order, the indent and the separator (U+3000, a
# full-width space), the minus sign (U+2212) and the US marks.
# (entry_type, the mark before the bold head, the head).
SECTIONS = (("breakout", "🚀 ", "突破"), ("pullback", "↩️ ", "回踩"))
OTHER_SECTION = (None, "", "其他")
INDENT = "　"
MINUS = "−"
US_MARKS = {"up": "🔴", "down": "🟢", "flat": "⚪"}
INCOMPLETE = "價位不完整"
PARSE_MODE = "HTML"
# Telegram's 400 for a text its HTML parser refuses.
PARSE_ERROR_TEXT = "can't parse entities"


# --- the record --------------------------------------------------------------------


def log_path(log_dir: Path, day: date) -> Path:
    return log_dir / f"{LOG_PREFIX}-{day:%Y%m%d}.log"


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
    """Whether the day's message needs no run any more (serve's catch-up reads it)."""

    return any(result in DONE_RESULTS for result in day_results(log_dir, day))


def mask(text: str, token: str | None) -> str:
    """TEXT with the token, and anything shaped like a bot token, replaced."""

    if token:
        text = text.replace(token, "<token>")
    return TOKEN_SHAPE.sub("<token>", text)


# --- the message --------------------------------------------------------------------


def esc(value: Any) -> str:
    """Data text for Telegram's HTML (``&``, ``<``, ``>``; quotes need none outside tags)."""

    return html.escape(str(value), quote=False)


def bold(text: str) -> str:
    return f"<b>{text}</b>"


def day_label(day: date | str) -> str:
    """「11/16（一）」: the card's date."""

    if isinstance(day, str):
        day = date.fromisoformat(day)
    return f"{day:%m/%d}（{WEEKDAYS[day.weekday()]}）"


def price(value: Any) -> str:
    return f"{value:,.2f}"


def _is_price(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value == value
        and value > 0
    )


def level_parts(levels: dict[str, Any]) -> tuple[str, str, str] | None:
    """The rule's entry, stop and target (the today page's rules, frontend entryPlan.ts),
    a pullback's entry 「X～Y」; None when they are incomplete."""

    stop, target = levels.get("invalid_price"), levels.get("target_1")
    if _is_price(stop) and _is_price(target):
        if levels.get("entry_type") == "breakout":
            entry = levels.get("entry")
            if entry is None:
                entry = (levels.get("entry_zone") or {}).get("low")
            if _is_price(entry) and stop < entry < target:
                return price(entry), price(stop), price(target)
        elif levels.get("entry_type") == "pullback":
            zone = levels.get("entry_zone") or {}
            low, high = zone.get("low"), zone.get("high")
            if _is_price(low) and _is_price(high) and low <= high and stop < target:
                return f"{price(low)}～{price(high)}", price(stop), price(target)
    return None


@dataclass(frozen=True)
class Row:
    """One row of the list, as the text and the card show it (raw text: each escapes)."""

    kind: str | None
    name: str
    entry: str | None = None
    stop: str | None = None
    target: str | None = None

    @property
    def levels(self) -> str:
        if self.entry is None:
            return INCOMPLETE
        return f"進場 {self.entry}｜停損 {self.stop}｜目標 {self.target}"


@dataclass(frozen=True)
class UsRow:
    """One US index: its close, change and tone, or no close and the reason in NOTE."""

    label: str
    close: str | None
    change: str = ""
    tone: str | None = None  # up, down, flat; None when the change is unknown
    note: str = (
        ""  # 「（09/03 收盤） 非最新」, or 「無資料（抓取失敗）」 without a close
    )


@dataclass(frozen=True)
class UsView:
    missing: str | None  # 「無資料（美股尚未更新）」 when no index has a close
    status: str = ""  # 美股休市, 美股尚未更新
    closed: str = ""  # 「（09/04 收盤）」 when the indexes share one close date
    rows: tuple[UsRow, ...] = ()
    source: str | None = None


@dataclass(frozen=True)
class Content:
    """The day's message, read once (#754): the text and the card are drawn from it."""

    today: date
    list_date: date
    computed: bool
    count: int
    zero_reason: str | None
    daily_status: str | None
    rows: tuple[Row, ...]
    total: (
        int  # what the list has (past MAX_ITEMS too); 「另 N 檔」 is total less shown
    )
    us: UsView

    @property
    def head(self) -> str:
        """The list's head line (raw)."""

        if not self.computed:
            return f"名單：無資料（{self.missing_reason}）"
        head = f"{day_label(self.list_date)}收盤後產生・{self.count} 檔"
        return f"{head}（{self.zero_reason}）" if self.zero_reason else head

    @property
    def missing_reason(self) -> str:
        why = f"daily：{self.daily_status}" if self.daily_status else "daily 沒有紀錄"
        return f"{day_label(self.list_date)}的名單沒有產生；{why}"

    @property
    def sub(self) -> str:
        """The card's line under its title."""

        if not self.computed:
            return "名單無資料"
        return f"{day_label(self.list_date)}收盤後產生"

    @property
    def note(self) -> str | None:
        """The card's reason line: no list, or an empty one."""

        return self.missing_reason if not self.computed else self.zero_reason


def list_rows(listing: dict[str, Any]) -> tuple[Row, ...]:
    """The list's rows in rank order (at most MAX_ITEMS)."""

    rows = []
    for item in (listing.get("items") or [])[:MAX_ITEMS]:
        instrument = item.get("instrument") or {}
        levels = item.get("levels") or {}
        name = f"{instrument.get('symbol', '')} {instrument.get('name', '')}".strip()
        rows.append(Row(levels.get("entry_type"), name, *(level_parts(levels) or ())))
    return tuple(rows)


def sections(rows: Iterable[Row]) -> list[tuple[str, str, list[Row]]]:
    """The rows by section (突破, 回踩, then 其他), each in rank order, as (mark, head,
    rows); an empty one is left out."""

    rows = list(rows)
    known = [kind for kind, _, _ in SECTIONS]
    out = []
    for kind, mark, title in (*SECTIONS, OTHER_SECTION):
        members = [
            row for row in rows if (row.kind == kind if kind else row.kind not in known)
        ]
        if members:
            out.append((mark, title, members))
    return out


def section_lines(rows: Iterable[Row]) -> list[str]:
    """The text's sections: a bold head with the count, then each row's two lines."""

    lines = []
    for mark, title, members in sections(rows):
        lines += ["", f"{mark}{bold(f'{title}（{len(members)} 檔）')}"]
        for row in members:
            lines += [bold(esc(row.name)), f"{INDENT}{row.levels}"]
    return lines


def _change(index: dict[str, Any]) -> tuple[str, str | None]:
    """The change and its tone: up, down, flat (the Taiwan colours); none when it is
    unknown."""

    value = index.get("change_pct")
    if not isinstance(value, (int, float)) or value != value:
        return "—", None
    pct = round(value * 100, 2)
    if pct > 0:
        return f"+{pct:.2f}%", "up"
    if pct < 0:
        return f"{MINUS}{-pct:.2f}%", "down"
    return "0.00%", "flat"


def _close_label(day: date | str) -> str:
    if isinstance(day, str):
        day = date.fromisoformat(day)
    return f"（{day:%m/%d} 收盤）"


def _source(indexes: list[dict[str, Any]]) -> str | None:
    """「FinMind」: each source's name once (the label's first word, no series)."""

    names: list[str] = []
    for index in indexes:
        label = ((index.get("source") or {}).get("label") or "").strip()
        name = label.split()[0] if label else ""
        if name and name not in names:
            names.append(name)
    return "；".join(names) or None


def us_view(indexes: list[dict[str, Any]]) -> UsView:
    """The 隔夜美股 block, by the today page's rules (frontend overnightUsView)."""

    available = [
        index
        for index in indexes
        if index.get("status") == "available" and _is_price(index.get("close"))
    ]
    fresh = [index for index in available if index.get("freshness") in US_FRESH]
    if not available:
        return UsView(missing="無資料（美股尚未更新）")
    days = sorted({index["trading_date"] for index in available})
    status = ""
    if not fresh:
        status = "美股尚未更新"
    elif all(index.get("freshness") == "us_market_closed" for index in fresh):
        status = "美股休市"
    rows = []
    for index in indexes:
        label = US_LABELS.get(index.get("symbol"), index.get("name") or "")
        if index not in available:
            reason = US_REASONS.get(index.get("reason"), "未取得")
            rows.append(UsRow(label, None, note=f"無資料（{reason}）"))
            continue
        change, tone = _change(index)
        note = _close_label(index["trading_date"]) if len(days) > 1 else ""
        if fresh and index.get("freshness") == "stale":
            note += " 非最新"
        rows.append(UsRow(label, price(index["close"]), change, tone, note))
    return UsView(
        missing=None,
        status=status,
        closed=_close_label(days[0]) if len(days) == 1 else "",
        rows=tuple(rows),
        source=_source(available),
    )


def us_lines(view: UsView) -> list[str]:
    """The text's 隔夜美股 block."""

    title = f"🌎 {bold('隔夜美股')}"
    if view.missing:
        return [f"{title}：{view.missing}"]
    head = title + (f" {view.status}" if view.status else "") + view.closed
    lines = [head]
    for row in view.rows:
        label = esc(row.label)
        if row.close is None:
            lines.append(f"{label}{INDENT}{row.note}")
            continue
        line = f"{label}{INDENT}{row.close}{INDENT}{row.change}{esc(row.note)}"
        mark = US_MARKS.get(row.tone or "")
        lines.append(f"{mark} {line}" if mark else line)
    if view.source:
        lines.append(f"來源 {esc(view.source)}")
    return lines


def length(text: str) -> int:
    """TEXT's length as Telegram counts it at most: UTF-16 code units (an emoji is two),
    the tags and entities included."""

    return len(text.encode("utf-16-le")) // 2


def content(
    today: date,
    list_date: date,
    listing: dict[str, Any],
    indexes: list[dict[str, Any]],
    daily_status: str | None = None,
) -> Content:
    """The day's message from the API's shapes (``candidate_list``, ``foreign_indices``)."""

    computed = listing.get("status") != "not_computed"
    rows = list_rows(listing) if computed else ()
    count = (listing.get("candidate_count") or 0) if computed else 0
    zero = listing.get("zero_reason_text") if computed and not count else None
    return Content(
        today=today,
        list_date=list_date,
        computed=computed,
        count=count,
        zero_reason=zero or None,
        daily_status=None if computed else daily_status,
        rows=rows,
        total=max(len(rows), count),
        us=us_view(indexes),
    )


def text(card: Content) -> str:
    """The text message (Telegram HTML), at most MAX_CHARS with its tags: rows are cut
    from the end of the list (the lowest ranks) with 「另 N 檔」."""

    top = [f"📋 {bold(f'今日名單｜{day_label(card.today)}')}", esc(card.head)]
    bottom = ["", *us_lines(card.us)]
    shown = len(card.rows)
    while True:
        lines = [*top, *section_lines(card.rows[:shown])]
        if shown < card.total:
            lines.append(f"另 {card.total - shown} 檔見今日名單頁")
        message_text = "\n".join([*lines, *bottom])
        if length(message_text) <= MAX_CHARS or shown == 0:
            return message_text[:MAX_CHARS]
        shown -= 1


def caption(card: Content) -> str:
    """The photo's one line (Telegram HTML): 「今日名單 11/13（五）・突破 8、回踩 9」."""

    title = bold(f"今日名單 {day_label(card.today)}")
    if not card.computed:
        return f"{title}・名單無資料"
    if not card.rows:
        return f"{title}・{card.count} 檔"
    counts = "、".join(
        f"{esc(head)} {len(members)}" for _mark, head, members in sections(card.rows)
    )
    return f"{title}・{counts}"


def compose(
    today: date,
    list_date: date,
    listing: dict[str, Any],
    indexes: list[dict[str, Any]],
    daily_status: str | None = None,
) -> str:
    """The text message of the API's shapes (``content`` then ``text``)."""

    return text(content(today, list_date, listing, indexes, daily_status))


# --- the database reads --------------------------------------------------------------


def _closed(db, day: date) -> bool:
    from sqlalchemy import select

    from app.models import TradingCalendarDay
    from app.trading_calendar import CALENDAR_EXCHANGE

    kind = db.scalar(
        select(TradingCalendarDay.kind).where(
            TradingCalendarDay.exchange == CALENDAR_EXCHANGE,
            TradingCalendarDay.calendar_date == day,
        )
    )
    return kind == "closed"


def is_trading_day(db, day: date) -> bool:
    """A weekday the stored calendar does not mark closed (unknown or missing: trading)."""

    return day.weekday() < 5 and not _closed(db, day)


def previous_session(db, day: date) -> date:
    """The weekday before DAY that the stored calendar does not mark closed."""

    cursor = day - timedelta(days=1)
    for _ in range(31):
        if is_trading_day(db, cursor):
            return cursor
        cursor -= timedelta(days=1)
    return cursor


def daily_status(db, day: date) -> str | None:
    from sqlalchemy import desc, select

    from app.models import ScheduleRun

    return db.scalar(
        select(ScheduleRun.status)
        .where(ScheduleRun.job == "daily", ScheduleRun.target_date == day)
        .order_by(desc(ScheduleRun.id))
        .limit(1)
    )


def read(db, today: date) -> Content:
    """Today's message from the database (the list of D - 1 and the overnight US
    indexes), read once for the card and the text."""

    from app.candidate_view import candidate_list
    from app.market_overview import foreign_indices

    list_date = previous_session(db, today)
    listing = candidate_list(db, list_date, limit=MAX_ITEMS)
    status = (
        daily_status(db, list_date) if listing["status"] == "not_computed" else None
    )
    return content(
        today, list_date, listing, foreign_indices(db, today.isoformat()), status
    )


def message(db, today: date) -> str:
    """Today's text message from the database."""

    return text(read(db, today))


# --- sending -------------------------------------------------------------------------


def configured(environ=os.environ) -> bool:
    return bool(
        environ.get(TOKEN_ENV, "").strip() and environ.get(CHAT_ENV, "").strip()
    )


def private_chat_id(value: str) -> int | None:
    """The chat id when it is a private chat's (a positive integer), else None."""

    value = value.strip()
    return int(value) if value.isdigit() and int(value) > 0 else None


def _attempt(token: str, chat_id: int, text: str) -> tuple[bool, str, float | None]:
    """One sendMessage (``_post``)."""

    body = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": PARSE_MODE,
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")
    return _post(token, "sendMessage", body, "application/json", TIMEOUT_SECONDS)


def multipart(
    fields: dict[str, str], files: dict[str, tuple[str, str, bytes]]
) -> tuple[bytes, str]:
    """A multipart/form-data body and its Content-Type: FIELDS as text, FILES as
    (file name, content type, bytes)."""

    boundary = f"stock-lab-{uuid.uuid4().hex}"
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            + value.encode("utf-8")
            + b"\r\n"
        )
    for name, (filename, kind, data) in files.items():
        parts.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}";'
                f' filename="{filename}"\r\nContent-Type: {kind}\r\n\r\n'
            ).encode()
            + data
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _attempt_photo(
    token: str, chat_id: int, photo: bytes, caption_text: str
) -> tuple[bool, str, float | None]:
    """One sendPhoto (``_post``): the PNG as ``photo`` with its one-line caption."""

    body, kind = multipart(
        {"chat_id": str(chat_id), "caption": caption_text, "parse_mode": PARSE_MODE},
        {"photo": ("card.png", "image/png", photo)},
    )
    return _post(token, "sendPhoto", body, kind, PHOTO_TIMEOUT_SECONDS)


def _photo_size(result: dict[str, Any]) -> str:
    """「1280x2370」: the largest size Telegram keeps of a sent photo (#754)."""

    sizes = [
        size
        for size in result.get("photo") or []
        if isinstance(size, dict)
        and isinstance(size.get("width"), int)
        and isinstance(size.get("height"), int)
    ]
    if not sizes:
        return ""
    largest = max(sizes, key=lambda size: size["width"] * size["height"])
    return f"{largest['width']}x{largest['height']}"


def _post(
    token: str, method: str, data: bytes, kind: str, timeout: float
) -> tuple[bool, str, float | None]:
    """One Bot API request: (ok, message id or reason, seconds before a retry or None).
    A sent photo's id is followed by ``photo=<width>x<height>``, the largest size kept.

    Retried (#728 review 6882303076): a connection or read failure, a timeout, a 5xx, and
    a 429 within RETRY_AFTER_MAX_SECONDS of its ``retry_after``. A timeout or a cut
    connection after the request went out may have been delivered already, so the retry
    can send the message twice; the coordinator prefers a duplicate to a missing one.
    Not retried: any other 4xx (a wrong token or chat id stays wrong; a 400 ``can't parse
    entities`` is ``parse_error``, #742) and a 200 whose body does not say ok (the request
    was answered). Nothing here holds the URL.
    """

    request = urllib.request.Request(
        f"{API_BASE}/bot{token}/{method}",
        data=data,
        headers={"Content-Type": kind},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        answer: dict[str, Any] = {}
        try:
            loaded = json.loads(exc.read().decode("utf-8"))
            answer = loaded if isinstance(loaded, dict) else {}
        except Exception:  # the status alone is the reason then
            pass
        description = str(answer.get("description") or "")
        reason = f"http_{exc.code} {description}".strip()
        if exc.code == 400 and PARSE_ERROR_TEXT in description.lower():
            # The text, not the network (#742): the same text is refused again.
            return False, f"parse_error {reason}", None
        if exc.code >= 500:
            return False, reason, RETRY_DELAY_SECONDS
        if exc.code == 429:
            wait = (answer.get("parameters") or {}).get("retry_after")
            wait = (
                float(wait) if isinstance(wait, (int, float)) else RETRY_DELAY_SECONDS
            )
            if wait <= RETRY_AFTER_MAX_SECONDS:
                return False, reason, max(wait, 0.0)
            return False, f"{reason} retry_after={wait:g}", None
        return False, reason, None
    except urllib.error.URLError as exc:
        cause = exc.reason
        name = type(cause).__name__ if isinstance(cause, BaseException) else "URLError"
        return False, f"network:{name}", RETRY_DELAY_SECONDS
    except (TimeoutError, OSError, http.client.HTTPException) as exc:
        return False, f"network:{type(exc).__name__}", RETRY_DELAY_SECONDS
    except ValueError as exc:
        return False, f"bad_response:{type(exc).__name__}", None
    if not isinstance(body, dict) or body.get("ok") is not True:
        description = body.get("description") if isinstance(body, dict) else None
        return False, f"not_ok {description or ''}".strip(), None
    result = body.get("result") or {}
    if not isinstance(result, dict):
        return True, "", None
    detail = str(result.get("message_id", ""))
    size = _photo_size(result)
    return True, f"{detail} photo={size}" if size else detail, None


def send(
    token: str,
    chat_id: int,
    text: str,
    *,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Send TEXT; a retryable failure (``_attempt``) is tried once more."""

    return _retried(lambda: _attempt(token, chat_id, text), token, sleep)


def send_photo(
    token: str,
    chat_id: int,
    photo: bytes,
    caption_text: str,
    *,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Send the PNG with its caption; retried as ``send`` is."""

    return _retried(
        lambda: _attempt_photo(token, chat_id, photo, caption_text), token, sleep
    )


def _retried(
    call: Callable[[], tuple[bool, str, float | None]],
    token: str,
    sleep: Callable[[float], None] | None,
) -> dict[str, Any]:
    reasons = []
    for attempt in range(1, ATTEMPTS + 1):
        ok, detail, wait = call()
        if ok:
            return {"status": SENT, "attempts": attempt, "message_id": detail}
        reasons.append(mask(detail, token))
        if wait is None or attempt == ATTEMPTS:
            break
        (sleep or time.sleep)(wait)
    return {"status": FAILED, "attempts": len(reasons), "reasons": reasons}


# --- the command ---------------------------------------------------------------------


def add_arguments(parser: argparse.ArgumentParser) -> None:
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run", action="store_true", help="只印出這天會送的內容，不送、不寫日誌"
    )
    mode.add_argument(
        "--send", action="store_true", help="送出（鎖、同一天不重送、日誌同排程）"
    )
    parser.add_argument("--date", help="台北日 YYYY-MM-DD（預設 --now 的台北日）")
    parser.add_argument(
        "--now",
        help="時間注入（serve 的 --now）：ISO 8601，沒有時區時為台北時間；預設現在",
    )
    parser.add_argument(
        "--trigger",
        choices=job.TRIGGERS,
        default="manual",
        help=(
            "scheduler 只在台北 08:45～13:30 送，其他時刻記 skipped reason=too_late"
            "（預設 manual，任何時刻都送）"
        ),
    )
    parser.add_argument("--log-dir", help="日誌目錄；預設 <資料目錄>/logs")
    parser.add_argument(
        "--image-out",
        help="只配 --dry-run：把圖片卡片畫成 PNG 寫到這個路徑（不送）",
    )


def argument_problem(args: argparse.Namespace) -> str | None:
    if getattr(args, "image_out", None) and not args.dry_run:
        return "--image-out goes with --dry-run only"
    if args.date:
        try:
            date.fromisoformat(args.date)
        except ValueError:
            return f"--date must be YYYY-MM-DD, got {args.date!r}"
    if args.now:
        try:
            datetime.fromisoformat(args.now)
        except ValueError:
            return f"--now must be an ISO 8601 time, got {args.now!r}"
    return None


def _clock(args: argparse.Namespace) -> datetime:
    """The Taipei time of the run: --now, else the real clock."""

    if not getattr(args, "now", None):
        return datetime.now(job.TAIPEI)
    moment = datetime.fromisoformat(args.now)
    return (moment if moment.tzinfo else moment.replace(tzinfo=job.TAIPEI)).astimezone(
        job.TAIPEI
    )


def _today(args: argparse.Namespace) -> date:
    return date.fromisoformat(args.date) if args.date else _clock(args).date()


def in_send_window(moment: datetime) -> bool:
    """Between SEND_TIME and CATCH_UP_END Taipei: when a scheduled run may send."""

    return SEND_TIME <= (moment.hour, moment.minute) < CATCH_UP_END


def _session():
    from app.db import SessionLocal

    return SessionLocal()


def _codes(outcome: dict[str, Any]) -> str:
    """Every attempt's reason, in order (#728 review 6882303076): http_401,network:… ."""

    return ",".join(item.split(" ", 1)[0] for item in outcome["reasons"]) or "unknown"


def dry_run(args: argparse.Namespace, out=None) -> int:
    """Print the caption and the text; with --image-out, draw the card there too. Exit 1
    when the card was asked for and could not be drawn."""

    out = out or sys.stdout
    today = _today(args)
    with _session() as db:
        trading = is_trading_day(db, today)
        card = read(db, today)
    print(f"configured={'yes' if configured() else 'no'}", file=out)
    if not trading:
        print(f"non_trading_day={today.isoformat()}（排程這天不送）", file=out)
    code = 0
    if getattr(args, "image_out", None):
        from .notify_card import render

        drawn = render(card)
        if drawn.png is None:
            print(f"image=failed reason={drawn.reason}", file=out)
            code = 1
        else:
            target = Path(args.image_out)
            target.write_bytes(drawn.png)
            print(
                f"image={target} width={drawn.width} height={drawn.height}"
                f" bytes={len(drawn.png)} seconds={drawn.seconds}",
                file=out,
            )
    print(f"caption={caption(card)}", file=out)
    print(text(card), file=out, flush=True)
    return code


class _Run:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.today = _today(args)
        self.data_dir = job.resolve_data_dir(None)
        self.log_dir = Path(os.path.abspath(args.log_dir or self.data_dir / "logs"))
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = log_path(self.log_dir, self.today)
        self.token = os.environ.get(TOKEN_ENV, "").strip()

    def log(self, text: str) -> None:
        with open(self.path, "a", encoding="utf-8", newline="") as log:
            log.write(mask(text, self.token) + "\n")

    def run(self) -> int:
        started = datetime.now(job.TAIPEI)
        lock = job.FileLock(job.lock_path(self.data_dir, LOCK))
        locked = lock.acquire()
        try:
            already = day_results(self.log_dir, self.today)
            self.log(
                f"===== {started.isoformat()} start job=notify trigger={self.args.trigger}"
                f" date={self.today.isoformat()} configured={'yes' if configured() else 'no'}"
            )
            try:
                code, result = self._run(locked, already)
            except Exception as exc:  # logged as the day's failure
                code, result = 1, f"status={FAILED} reason=error:{type(exc).__name__}"
            self.log(f"--- result {result}")
            finished = datetime.now(job.TAIPEI)
            self.log(
                f"===== {finished.isoformat()} end exit={code}"
                f" seconds={round((finished - started).total_seconds())}"
            )
        finally:
            lock.release()
            self._remove_old_logs()
        print(
            mask(f"notify {result} exit={code} log={self.path}", self.token), flush=True
        )
        return code

    def _run(self, locked: bool, already: list[str]) -> tuple[int, str]:
        if not locked:
            return 0, f"status={SKIPPED} reason=already_running"
        if SENT in already:
            return 0, f"status={SKIPPED} reason=already_sent"
        with _session() as db:
            if not is_trading_day(db, self.today):
                return 0, f"status={SKIPPED} reason=non_trading_day"
            if self.args.trigger == "scheduler":
                # The job's own rule, whatever APScheduler does with a missed 08:45 (a
                # host asleep at 08:45 runs it as it wakes, #728 review 6882303076): no
                # message of the morning after the close. After the trading-day check, so
                # that too_late marks a missed trading day only, which the watchdog
                # reports (notify_missed, review 6882535482).
                moment = _clock(self.args)
                if not in_send_window(moment):
                    return 0, (
                        f"status={SKIPPED} reason=too_late"
                        f" at={moment.strftime('%H:%M')}"
                    )
            if not configured():
                missing = [
                    name
                    for name in (TOKEN_ENV, CHAT_ENV)
                    if not os.environ.get(name, "").strip()
                ]
                return 0, f"status={NOT_CONFIGURED} missing={','.join(missing)}"
            chat_id = private_chat_id(os.environ[CHAT_ENV])
            if chat_id is None:
                return 1, f"status={FAILED} reason=chat_not_private"
            card = read(db, self.today)
        body, line = text(card), caption(card)
        self.log(
            f"--- message chars={len(body)}\n{body}\n--- message end\n"
            f"--- caption {line}"
        )
        # The card first (#754); the text when it cannot be drawn or sent.
        from .notify_card import render

        drawn = render(card)
        if drawn.png is None:
            fallback = f"render_failed:{drawn.reason}"
        else:
            self.log(
                f"--- card width={drawn.width} height={drawn.height}"
                f" bytes={len(drawn.png)} seconds={drawn.seconds}"
            )
            photo = send_photo(self.token, chat_id, drawn.png, line)
            if photo["status"] == SENT:
                return 0, (
                    f"status={SENT} mode=photo attempts={photo['attempts']}"
                    f" message_id={photo['message_id']}"
                )
            fallback = f"photo_failed:{_codes(photo)}"
            self.log(f"--- photo failed {' | '.join(photo['reasons'])}")
        outcome = send(self.token, chat_id, body)
        if outcome["status"] == SENT:
            return 0, (
                f"status={SENT} mode=text reason={fallback}"
                f" attempts={outcome['attempts']} message_id={outcome['message_id']}"
            )
        detail = " | ".join(outcome["reasons"])
        return (
            1,
            f"status={FAILED} reason={_codes(outcome)}"
            f" attempts={outcome['attempts']} photo={fallback} detail={detail}",
        )

    def _remove_old_logs(self) -> None:
        cutoff = time.time() - LOG_RETENTION_DAYS * 86400
        for path in self.log_dir.glob(f"{LOG_PREFIX}-*.log"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass


def run(args: argparse.Namespace) -> int:
    """``worker.cli notify``."""

    if args.dry_run:
        return dry_run(args)
    problem = job.platform_problem("worker.notify")
    if problem:
        print(problem, file=sys.stderr)
        return job.PLATFORM_EXIT
    return _Run(args).run()
