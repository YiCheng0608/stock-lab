"""The daily Telegram message: ``python -m worker.cli notify`` (#728).

Each trading day at 08:45 Taipei, serve runs ``notify --send``. It sends one plain-text
message (no ``parse_mode``: a stock name or number never needs escaping) to the user's own
chat with the Telegram Bot API ``sendMessage``:

- 今日名單: the list of the session before today (D - 1: the weekday before, skipping the
  days ``trading_calendar_days`` marks closed), as ``/api/candidates?date=D-1`` gives it
  (``app.candidate_view.candidate_list``): its date and count, each row's code, name and the
  rule's entry (price or zone), stop and target with the today page's words. No other list
  stands in for a missing one: it reads 「無資料（…）」 with the day's daily status.
- 隔夜美股: ``app.market_overview.foreign_indices`` for today, the four indexes of the today
  page's line (``overnight_us``, #681), with its freshness (美股休市, 非最新, 美股尚未更新),
  the data date and the source.

The token and the chat id come from ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID``, which
reach the scheduler container through compose's ``env_file`` (docs/ops/SETUP.md). Without
them the run records ``not_configured`` and is no failure. The chat id must be a positive
integer, a private chat: the US index figures go to the user's own chat only (their
licences, #1 decision 6717084453); a group or channel id is refused. The token never reaches
a log line, an error or the output: the URL that holds it is built here and never printed,
and every line is masked first.

The record is the day's log ``<logs>/notify-YYYYMMDD.log`` (the target day; no table): a
``===== start`` line, one ``--- result status=…`` line (sent, not_configured, failed or
skipped with a reason) and a ``===== end exit=N`` line. A run that finds ``status=sent`` in
the day's log skips (``already_sent``), so a restarted scheduler never sends twice; the lock
``<data>/locks/notify.lock`` keeps two runs apart and is no other job's. A scheduled run
(``--trigger scheduler``) sends only between 08:45 and 13:30 Taipei and records
``skipped reason=too_late`` otherwise, whatever APScheduler does with a missed trigger. A
network failure, a timeout, a 5xx or a 429 is tried once more (``_attempt``); another 4xx is
not. A failure is ``failed`` with every attempt's reason and exit 1, which the watchdog
reports (``notify_failed``; ``notify_missing`` when the day has no end line;
``notify_missed`` when a trading day has only ``too_late``).

Not through ``worker.job`` (#728 decision 6881879639): the run only reads the database and
sends one request, so it needs neither the memory threshold nor the git check, and it runs
in maintenance mode too.

Only the standard library at the top: serve imports the log reading here.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

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


def day_label(day: date | str) -> str:
    if isinstance(day, str):
        day = date.fromisoformat(day)
    return f"{day:%Y/%m/%d}（{WEEKDAYS[day.weekday()]}）"


def price(value: Any) -> str:
    return f"{value:,.2f}"


def _is_price(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value == value
        and value > 0
    )


def level_text(levels: dict[str, Any]) -> str:
    """The rule's entry, stop and target in the today page's words (frontend entryPlan.ts)."""

    stop, target = levels.get("invalid_price"), levels.get("target_1")
    if _is_price(stop) and _is_price(target):
        tail = f"／停損 {price(stop)}／目標 {price(target)}"
        if levels.get("entry_type") == "breakout":
            entry = levels.get("entry")
            if entry is None:
                entry = (levels.get("entry_zone") or {}).get("low")
            if _is_price(entry) and stop < entry < target:
                return f"規則進場價 {price(entry)}{tail}"
        elif levels.get("entry_type") == "pullback":
            zone = levels.get("entry_zone") or {}
            low, high = zone.get("low"), zone.get("high")
            if _is_price(low) and _is_price(high) and low <= high and stop < target:
                return f"規則進場區 {price(low)}～{price(high)}{tail}"
    return "價位不完整"


def list_lines(
    list_date: date, listing: dict[str, Any], daily_status: str | None
) -> tuple[str, list[str]]:
    """The list's head line and its rows (two lines each)."""

    if listing.get("status") == "not_computed":
        why = f"daily：{daily_status}" if daily_status else "daily 沒有紀錄"
        return f"名單：無資料（{day_label(list_date)}的名單沒有產生；{why}）", []
    count = listing.get("candidate_count") or 0
    head = f"名單：{day_label(list_date)}收盤後產生，{count} 檔"
    if not count and listing.get("zero_reason_text"):
        head += f"（{listing['zero_reason_text']}）"
    rows = []
    for item in (listing.get("items") or [])[:MAX_ITEMS]:
        instrument = item.get("instrument") or {}
        rows.append(
            [
                f"{item.get('rank')}. {instrument.get('symbol', '')} {instrument.get('name', '')}".rstrip(),
                f"   {level_text(item.get('levels') or {})}",
            ]
        )
    return head, rows


def _change(index: dict[str, Any]) -> str:
    value = index.get("change_pct")
    if not isinstance(value, (int, float)) or value != value:
        return "—"
    return f"{value * 100:+.2f}%"


def _source(indexes: list[dict[str, Any]]) -> str | None:
    """「FinMind USStockPrice（^GSPC、^IXIC、^DJI、^SOX）」: each source once, its series."""

    groups: dict[str, list[str]] = {}
    for index in indexes:
        label = ((index.get("source") or {}).get("label") or "").strip()
        if not label:
            continue
        series = index.get("series_id") or ""
        if series and label.endswith(f" {series}"):
            groups.setdefault(label[: -len(series) - 1], []).append(series)
        else:
            groups.setdefault(label, [])
    if not groups:
        return None
    return "；".join(
        f"{name}（{'、'.join(series)}）" if series else name
        for name, series in groups.items()
    )


def us_lines(indexes: list[dict[str, Any]]) -> list[str]:
    """The 隔夜美股 block, by the today page's rules (frontend overnightUsView)."""

    available = [
        index
        for index in indexes
        if index.get("status") == "available" and _is_price(index.get("close"))
    ]
    fresh = [index for index in available if index.get("freshness") in US_FRESH]
    if not available:
        return ["隔夜美股：無資料（美股尚未更新）"]
    days = sorted({index["trading_date"] for index in available})
    head = "隔夜美股"
    if not fresh:
        head += " 美股尚未更新"
    elif all(index.get("freshness") == "us_market_closed" for index in fresh):
        head += " 美股休市"
    if len(days) == 1:
        head += f"（資料日 {day_label(days[0])}）"
    lines = [head]
    for index in indexes:
        label = US_LABELS.get(index.get("symbol"), index.get("name") or "")
        if index not in available:
            reason = US_REASONS.get(index.get("reason"), "未取得")
            lines.append(f"{label} 無資料（{reason}）")
            continue
        line = f"{label} {price(index['close'])} {_change(index)}"
        if len(days) > 1:
            line += f"（{day_label(index['trading_date'])}）"
        if fresh and index.get("freshness") == "stale":
            line += " 非最新"
        lines.append(line)
    source = _source(available)
    if source:
        lines.append(f"來源：{source}")
    return lines


def compose(
    today: date,
    list_date: date,
    listing: dict[str, Any],
    indexes: list[dict[str, Any]],
    daily_status: str | None = None,
) -> str:
    """The message, at most MAX_CHARS: rows are cut from the end with 「另 N 檔」."""

    head, rows = list_lines(list_date, listing, daily_status)
    top = [f"stock-lab 今日名單 {day_label(today)}", "", head]
    bottom = ["", *us_lines(indexes)]
    # Past MAX_ITEMS or cut for the length: N is what the list has and the message omits.
    total = max(len(rows), listing.get("candidate_count") or 0)
    shown = len(rows)
    while True:
        lines = [*top, *(line for row in rows[:shown] for line in row)]
        if shown < total:
            lines.append(f"另 {total - shown} 檔見今日名單頁")
        text = "\n".join([*lines, *bottom])
        if len(text) <= MAX_CHARS or shown == 0:
            return text[:MAX_CHARS]
        shown -= 1


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


def message(db, today: date) -> str:
    """Today's message from the database (the list of D - 1 and the overnight US indexes)."""

    from app.candidate_view import candidate_list
    from app.market_overview import foreign_indices

    list_date = previous_session(db, today)
    listing = candidate_list(db, list_date, limit=MAX_ITEMS)
    status = (
        daily_status(db, list_date) if listing["status"] == "not_computed" else None
    )
    return compose(
        today, list_date, listing, foreign_indices(db, today.isoformat()), status
    )


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
    """One sendMessage: (ok, message id or reason, seconds before a retry or None).

    Retried (#728 review 6882303076): a connection or read failure, a timeout, a 5xx, and
    a 429 within RETRY_AFTER_MAX_SECONDS of its ``retry_after``. A timeout or a cut
    connection after the request went out may have been delivered already, so the retry
    can send the message twice; the coordinator prefers a duplicate to a missing one.
    Not retried: any other 4xx (a wrong token or chat id stays wrong) and a 200 whose body
    does not say ok (the request was answered). Nothing here holds the URL.
    """

    request = urllib.request.Request(
        f"{API_BASE}/bot{token}/sendMessage",
        data=json.dumps(
            {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        answer: dict[str, Any] = {}
        try:
            loaded = json.loads(exc.read().decode("utf-8"))
            answer = loaded if isinstance(loaded, dict) else {}
        except Exception:  # the status alone is the reason then
            pass
        reason = f"http_{exc.code} {answer.get('description') or ''}".strip()
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
    message_id = result.get("message_id", "") if isinstance(result, dict) else ""
    return True, str(message_id), None


def send(
    token: str,
    chat_id: int,
    text: str,
    *,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Send TEXT; a retryable failure (``_attempt``) is tried once more."""

    reasons = []
    for attempt in range(1, ATTEMPTS + 1):
        ok, detail, wait = _attempt(token, chat_id, text)
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


def argument_problem(args: argparse.Namespace) -> str | None:
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


def dry_run(args: argparse.Namespace, out=None) -> int:
    out = out or sys.stdout
    today = _today(args)
    with _session() as db:
        trading = is_trading_day(db, today)
        text = message(db, today)
    print(f"configured={'yes' if configured() else 'no'}", file=out)
    if not trading:
        print(f"non_trading_day={today.isoformat()}（排程這天不送）", file=out)
    print(text, file=out, flush=True)
    return 0


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
            text = message(db, self.today)
        self.log(f"--- message chars={len(text)}\n{text}\n--- message end")
        outcome = send(self.token, chat_id, text)
        if outcome["status"] == SENT:
            return 0, (
                f"status={SENT} attempts={outcome['attempts']}"
                f" message_id={outcome['message_id']}"
            )
        # Every attempt's reason, in order (#728 review 6882303076): http_401,network:… .
        reason = ",".join(item.split(" ", 1)[0] for item in outcome["reasons"])
        detail = " | ".join(outcome["reasons"])
        return (
            1,
            f"status={FAILED} reason={reason or 'unknown'}"
            f" attempts={outcome['attempts']} detail={detail}",
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
