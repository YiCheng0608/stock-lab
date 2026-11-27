"""Attention notices and disposals of the research database (Issue #1090).

Four feeds, one ``trading-notices backfill`` command (#1086 report 7208497574):

- ``twse-notice``: TWSE ``announcement/notice`` (公布注意有價證券資訊), into
  ``trading_attentions``.
- ``twse-punish``: TWSE ``announcement/punish`` (公布處置有價證券資訊), into
  ``trading_disposals``.
- ``tpex-attention``: TPEx ``bulletin/attention``, into ``trading_attentions``.
- ``tpex-disposal``: TPEx ``bulletin/disposal``, into ``trading_disposals``.

One request a feed and month, every listed security of the exchange.  The notice
queries select by the notice date: the month's window.  The disposal queries
select the periods that overlap the window, so a month's window runs to the end
of the next month: a disposal announced on the last days of a month and starting
in the next one is in it (the month's own query would miss it).  A month writes
the rows it owns only, the notices of its days and the disposals announced in it;
a row of another month in the answer is counted (``other_month``) and left to its
month, so the overlapping answers give each disposal once (exchange, code,
announced date, start date).

Every row is kept, warrants and ETFs too (#1086 decision 7208544050 D3): the row
names the stock, ``ipo`` or ETF instrument of its exchange and code, or NULL.
TPEx prints a placeholder row on a day without any notice or disposal (「本日無公布
注意交易資訊」「本日無處置資料」); it is no row but a day verified empty, kept in
the month's manifest.  The TWSE 累計 counts within the query period and is not
kept; the TPEx one is.  款次, the matching interval and prepayment are read from the
text; what does not say is NULL, never 0.

Each feed and month is one ``ingestion_runs`` row (``MONTH_RUN_TYPE``, request
key ``trading_notices_backfill:<feed>:<YYYY-MM>``): the manifest.  A month
already ``success`` is not asked again; ``reapply`` rereads its stored raw.  A
failed month is asked again on the next run; ``max_requests`` stops a run after
that many requests, for the next run to go on.  One commit a feed and month.

An answer that is not one of the known layouts, a cell that does not read, a
date outside the window or two different rows of one key fail the whole month;
nothing of it is written and nothing is guessed.

Requests: at least ``REQUEST_INTERVAL_SECONDS`` apart on a host; none between
``QUIET_START`` and ``QUIET_END`` Taipei nor within ``EVEN_HOUR_MARGIN`` of an
even hour (the run waits); ``ABORT_AFTER_FAILURES`` failed requests in a row
stop it.  Only on the research database (``quarterly_xbrl.research_refusal``),
holding maintenance mode (``worker.cli``).
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from datetime import time as clock_time
from typing import Any, Callable
from urllib.parse import urlencode

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.models import (
    IngestionRun,
    Instrument,
    RawPayload,
    TradingAttention,
    TradingDisposal,
)
from app.raw_paths import payload_file
from worker import pipeline, sources
from worker.sources import OfficialDataError

TWSE_NOTICE_ENDPOINT = "https://www.twse.com.tw/rwd/zh/announcement/notice"
TWSE_PUNISH_ENDPOINT = "https://www.twse.com.tw/rwd/zh/announcement/punish"
TPEX_ATTENTION_ENDPOINT = "https://www.tpex.org.tw/www/zh-tw/bulletin/attention"
TPEX_DISPOSAL_ENDPOINT = "https://www.tpex.org.tw/www/zh-tw/bulletin/disposal"

MONTH_RUN_TYPE = "trading_notices_month"
REQUEST_KEY = "trading_notices_backfill:{feed}:{month}"
REQUEST_INTERVAL_SECONDS = 3.5
# Taipei: the production daily, and the news runs on the even hours (Issue #1090).
QUIET_START = clock_time(21, 15)
QUIET_END = clock_time(23, 30)
EVEN_HOUR_MARGIN = timedelta(minutes=10)
TAIPEI = timezone(timedelta(hours=8))
ABORT_AFTER_FAILURES = 5
MAX_LISTED = 200
INSTRUMENT_TYPES = ("stock", "ipo", "etf")

# --- layouts ------------------------------------------------------------------

TWSE_NOTICE_FIELDS = (
    "編號",
    "證券代號",
    "證券名稱",
    "累計次數",
    "注意交易資訊",
    "日期",
    "收盤價",
    "本益比",
)
TWSE_PUNISH_FIELDS = (
    "編號",
    "公布日期",
    "證券代號",
    "證券名稱",
    "累計",
    "處置條件",
    "處置起迄時間",
    "處置措施",
    "處置內容",
    "備註",
)
TPEX_ATTENTION_FIELDS = (
    "編號",
    "證券代號",
    "證券名稱",
    "累計",
    "注意交易資訊",
    "公告日期",
    "收盤價",
    "本益比",
    "link",
)
TPEX_DISPOSAL_FIELDS = (
    "編號",
    "公布日期",
    "證券代號",
    "證券名稱",
    "累計",
    "處置起訖時間",
    "處置原因",
    "處置措施",
    "處置內容",
    "收盤價",
    "本益比",
    " ",
)
TPEX_ATTENTION_TITLE = "上櫃公布注意有價證券"
TPEX_DISPOSAL_TITLE = "上櫃處置有價證券"
# The TPEx placeholder rows of a day without any (#1086: both spellings in the old
# answers, 「本日無處置資料」 in the disposal ones).
ATTENTION_PLACEHOLDER = re.compile(r"本日無公[布佈]注意(?:交易)?資訊")
DISPOSAL_PLACEHOLDER = "本日無處置資料"

_ROC_DATE = re.compile(r"(\d{2,3})[./](\d{1,2})[./](\d{1,2})")
_TITLE_PERIOD = re.compile(
    r"\((\d{2,3}/\d{1,2}/\d{1,2})\s*至\s*(\d{2,3}/\d{1,2}/\d{1,2})\)"
)
_PERIOD_SPLIT = re.compile(r"\s*[～~]\s*")
# 款次 in brackets: TWSE 「﹝第九款﹞」, TPEx 「(第一款)」.
_CLAUSE_GROUP = re.compile(r"[﹝(（〔\[]([^﹝﹞()（）〔〕\[\]]*款)[﹞)）〕\]]")
_CLAUSE = re.compile(r"第([0-9０-９〇零一二兩三四五六七八九十百廿]+)款")
_INTERVAL = re.compile(r"每\s*([0-9０-９〇零一二兩三四五六七八九十百廿]+)\s*分鐘")
# 預收: the brokers collect the price or the securities in advance; 「應先收足款券」 too
# (TPEx 2008), never 「應收足融資自備款或融券保證金」 (the margin deposit).
_PREPAYMENT = re.compile(r"收取全部|收取.{0,12}(?:價金|款券)|收足.{0,4}款券|預收")
_TAG = re.compile(r"<[^>]*>")
_BREAK = re.compile(r"<br\s*/?>", re.I)
# TPEx disposal names carry their link: 「金麗科(../../mainboard/...html?code=3228)」.
_NAME_LINK = re.compile(r"\((?:\.\./|\./|https?://)[^()]*\)\s*$")
_DIGITS = {
    **{str(n): n for n in range(10)},
    **{chr(0xFF10 + n): n for n in range(10)},
    "〇": 0,
    "零": 0,
    "一": 1,
    "二": 2,
    "兩": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


class Refused(ValueError):
    """The arguments ask for no month this may run: nothing is requested."""


class LayoutError(OfficialDataError):
    """The month's answer is not one this reads; nothing of the month is written."""


# --- feeds --------------------------------------------------------------------


@dataclass(frozen=True)
class Feed:
    name: str
    exchange: str
    kind: str  # "attention" or "disposal"
    source: str  # the rows' source
    raw_source: str  # raw_payloads.source and the raw directory
    endpoint: str
    method: str
    first_month: date


FEEDS: dict[str, Feed] = {
    feed.name: feed
    for feed in (
        # docs/DATA_SOURCES.md 各來源最早可得 (#1086): no row before these months.
        Feed(
            "twse-notice",
            "TWSE",
            "attention",
            "twse_notice",
            "twse",
            TWSE_NOTICE_ENDPOINT,
            "GET",
            date(2001, 1, 1),
        ),
        Feed(
            "twse-punish",
            "TWSE",
            "disposal",
            "twse_punish",
            "twse",
            TWSE_PUNISH_ENDPOINT,
            "GET",
            date(2001, 1, 1),
        ),
        Feed(
            "tpex-attention",
            "TPEx",
            "attention",
            "tpex_attention",
            "tpex",
            TPEX_ATTENTION_ENDPOINT,
            "POST",
            date(2002, 2, 1),
        ),
        Feed(
            "tpex-disposal",
            "TPEx",
            "disposal",
            "tpex_disposal",
            "tpex",
            TPEX_DISPOSAL_ENDPOINT,
            "POST",
            date(2003, 9, 1),
        ),
    )
}


def month_start(day: date) -> date:
    return day.replace(day=1)


def next_month(month: date) -> date:
    return (month.replace(day=28) + timedelta(days=4)).replace(day=1)


def month_end(month: date) -> date:
    return next_month(month) - timedelta(days=1)


def parse_month(text: str) -> date:
    try:
        return datetime.strptime(text, "%Y-%m").date()
    except ValueError as exc:
        raise ValueError(f"{text!r} is not YYYY-MM") from exc


def window(feed: Feed, month: date) -> tuple[date, date]:
    """The query period of a feed's month: to the next month's end for disposals."""

    if feed.kind == "disposal":
        return month, month_end(next_month(month))
    return month, month_end(month)


def request_of(feed: Feed, month: date) -> tuple[str, dict[str, str] | None]:
    """(the endpoint kept in raw_payloads, the POST form or None) of a month."""

    first, last = window(feed, month)
    if feed.name == "twse-notice":
        query = {
            "querytype": "1",
            "stockNo": "",
            "selectType": "",
            "startDate": f"{first:%Y%m%d}",
            "endDate": f"{last:%Y%m%d}",
            "sortKind": "STKNO",
            "response": "json",
        }
        return f"{feed.endpoint}?{urlencode(query)}", None
    if feed.name == "twse-punish":
        query = {
            "startDate": f"{first:%Y%m%d}",
            "endDate": f"{last:%Y%m%d}",
            "response": "json",
        }
        return f"{feed.endpoint}?{urlencode(query)}", None
    form = {
        "startDate": f"{first:%Y/%m/%d}",
        "endDate": f"{last:%Y/%m/%d}",
        "response": "json",
    }
    return f"{feed.endpoint}?{urlencode(form, safe='/')}", form


def fetch_official(feed: Feed, month: date) -> Any:
    url, form = request_of(feed, month)
    if feed.method == "POST":
        return sources.fetch_json(feed.endpoint, method="POST", data=form)
    return sources.fetch_json(url)


# --- cells --------------------------------------------------------------------


def _text(cell: Any) -> str:
    return "" if cell is None else str(cell).strip()


def clean_text(cell: Any) -> str:
    """The cell without HTML: breaks as new lines, tags dropped, entities read."""

    text = _BREAK.sub("\n", "" if cell is None else str(cell))
    text = html.unescape(_TAG.sub("", text))
    lines = [line.strip() for line in text.replace("\r", "").split("\n")]
    return "\n".join(line for line in lines if line)


def _number(cell: Any) -> float | None:
    if cell is None:
        return None
    if isinstance(cell, bool):
        raise LayoutError(f"unreadable value {cell!r}")
    text = str(cell).strip().replace(",", "")
    if text in {"", "N/A", "NA"} or re.fullmatch(r"-+", text):
        return None
    try:
        value = float(text)
    except ValueError as exc:
        raise LayoutError(f"unreadable value {cell!r}") from exc
    if not math.isfinite(value):
        raise LayoutError(f"unreadable value {cell!r}")
    return value


def _count(cell: Any) -> int | None:
    if isinstance(cell, bool):
        raise LayoutError(f"unreadable count {cell!r}")
    if isinstance(cell, int):
        return cell
    text = _text(cell)
    if text in {"", "null"}:
        return None
    if not text.isdigit():
        raise LayoutError(f"unreadable count {cell!r}")
    return int(text)


def roc_date(cell: Any) -> date:
    match = _ROC_DATE.fullmatch(_text(cell))
    if not match:
        raise LayoutError(f"unreadable date {cell!r}")
    try:
        return date(
            int(match.group(1)) + 1911, int(match.group(2)), int(match.group(3))
        )
    except ValueError as exc:
        raise LayoutError(f"unreadable date {cell!r}") from exc


def numeral(text: str) -> int | None:
    """A number in digits or Chinese numerals (五, 二十, 廿五, 二百七十); else None."""

    text = text.strip()
    if text and all(ch in _DIGITS and _DIGITS[ch] <= 9 for ch in text):
        if any(ch in "〇零一二兩三四五六七八九" for ch in text) and len(text) > 1:
            return None  # 二五 is no number this reads
        return int("".join(str(_DIGITS[ch]) for ch in text))
    total, digit = 0, None
    for ch in text.replace("廿", "二十"):
        if ch in _DIGITS:
            if digit is not None:
                return None
            digit = _DIGITS[ch]
        elif ch in "十百":
            unit = 10 if ch == "十" else 100
            total += (1 if digit is None else digit) * unit
            digit = None
        else:
            return None
    if digit is not None:
        total += digit
    return total or None


def clauses_of(detail: str) -> str | None:
    """款次 in brackets as "1,9", ascending; None when the text names none."""

    numbers: set[int] = set()
    for group in _CLAUSE_GROUP.findall(detail):
        for value in _CLAUSE.findall(group):
            number = numeral(value)
            if number is None:
                raise LayoutError(f"unreadable clause {value!r}")
            numbers.add(number)
    return ",".join(str(n) for n in sorted(numbers)) or None


def interval_of(detail: str | None) -> int | None:
    """The 約每 N 分鐘撮合一次 of the text; None when it names none or several."""

    if not detail:
        return None
    values = {numeral(value) for value in _INTERVAL.findall(detail)}
    values.discard(None)
    return values.pop() if len(values) == 1 else None


def prepayment_of(detail: str | None) -> bool | None:
    if not detail:
        return None
    return bool(_PREPAYMENT.search(detail))


def security_name(cell: Any) -> str:
    return _NAME_LINK.sub("", _text(cell)).strip()


# --- parsers -------------------------------------------------------------------


@dataclass
class Parsed:
    """A month's answer: rows by key, days verified empty.

    ``placeholder_with_rows`` are the days TPEx printed a placeholder row and data
    rows for (#1092 review: 2004-06-07 of the attentions): not verified empty.
    """

    rows: dict[tuple, dict[str, Any]]
    empty_days: set[date]
    answer_rows: int
    placeholder_with_rows: set[date] = field(default_factory=set)


def _tpex_parsed(
    rows: dict[tuple, dict[str, Any]], placeholders: set[date], answer_rows: int
) -> Parsed:
    """The days of a placeholder row that also have data rows are not empty."""

    with_rows = placeholders & {key[1] for key in rows}
    return Parsed(rows, placeholders - with_rows, answer_rows, with_rows)


def _records(fields: Any, data: Any, layout: tuple[str, ...]) -> list[dict]:
    if not isinstance(fields, list) or tuple(fields) != layout:
        raise LayoutError(f"unknown columns {fields!r}")
    if not isinstance(data, list):
        raise LayoutError("the answer has no data list")
    records = []
    for row in data:
        if not isinstance(row, list) or len(row) != len(fields):
            raise LayoutError(f"a row does not match the columns: {row!r}")
        records.append(dict(zip(fields, row)))
    return records


def _twse_body(payload: Any, first: date, last: date) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LayoutError("the answer is not a JSON object")
    if payload.get("stat") != "OK":
        raise LayoutError(f"stat {payload.get('stat')!r}")
    params = payload.get("params")
    if isinstance(params, dict):
        answered = (params.get("startDate"), params.get("endDate"))
    else:
        # punish has no params; its title names the period: 「(109/11/01 至 109/12/31)」.
        found = _TITLE_PERIOD.search(str(payload.get("title") or ""))
        answered = (
            tuple(f"{roc_date(day):%Y%m%d}" for day in found.groups())
            if found
            else None
        )
    if answered != (f"{first:%Y%m%d}", f"{last:%Y%m%d}"):
        raise LayoutError(f"answered period {answered!r} is not {first}～{last}")
    total = payload.get("total")
    data = payload.get("data")
    if total is not None and isinstance(data, list) and total != len(data):
        raise LayoutError(f"total {total!r} but {len(data)} rows")
    return payload


def _tpex_table(payload: Any, title: str, first: date, last: date) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LayoutError("the answer is not a JSON object")
    if str(payload.get("stat") or "").lower() != "ok":
        raise LayoutError(f"stat {payload.get('stat')!r}")
    if str(payload.get("date") or "") != f"{first:%Y%m%d}~{last:%Y%m%d}":
        raise LayoutError(f"answered period {payload.get('date')!r}")
    tables = payload.get("tables")
    if not isinstance(tables, list) or len(tables) != 1:
        raise LayoutError("the answer is not one table")
    table = tables[0]
    if not isinstance(table, dict) or table.get("title") != title:
        raise LayoutError(
            f"table {table.get('title') if isinstance(table, dict) else table!r}"
        )
    return table


def _within(day: date, first: date, last: date) -> date:
    if not first <= day <= last:
        raise LayoutError(f"{day} is outside the query period {first}～{last}")
    return day


def _keep(
    rows: dict[tuple, dict[str, Any]], key: tuple, values: dict[str, Any]
) -> None:
    if key in rows and rows[key] != values:
        raise LayoutError(f"two different rows of {key!r}")
    rows[key] = values


def parse_twse_notice(payload: Any, first: date, last: date) -> Parsed:
    body = _twse_body(payload, first, last)
    rows: dict[tuple, dict[str, Any]] = {}
    records = _records(body.get("fields"), body.get("data"), TWSE_NOTICE_FIELDS)
    for record in records:
        code = _text(record["證券代號"])
        if not code:
            raise LayoutError(f"a row without a code: {record!r}")
        day = _within(roc_date(record["日期"]), first, last)
        detail = clean_text(record["注意交易資訊"])
        if not detail:
            raise LayoutError(f"a notice without its text: {record!r}")
        _keep(
            rows,
            (code, day),
            {
                "security_name": security_name(record["證券名稱"]),
                "detail": detail,
                "clauses": clauses_of(detail),
                "close_price": _number(record["收盤價"]),
                "pe_ratio": _number(record["本益比"]),
                # 累計次數 counts within the query period: not kept.
                "cumulative_count": None,
            },
        )
    return Parsed(rows, set(), len(records))


def parse_tpex_attention(payload: Any, first: date, last: date) -> Parsed:
    table = _tpex_table(payload, TPEX_ATTENTION_TITLE, first, last)
    rows: dict[tuple, dict[str, Any]] = {}
    empty: set[date] = set()
    records = _records(table.get("fields"), table.get("data"), TPEX_ATTENTION_FIELDS)
    for record in records:
        code = _text(record["證券代號"])
        day = _within(roc_date(record["公告日期"]), first, last)
        detail = clean_text(record["注意交易資訊"])
        if not code:
            if not ATTENTION_PLACEHOLDER.fullmatch(detail):
                raise LayoutError(f"a row without a code: {record!r}")
            empty.add(day)
            continue
        if not detail:
            raise LayoutError(f"a notice without its text: {record!r}")
        _keep(
            rows,
            (code, day),
            {
                "security_name": security_name(record["證券名稱"]),
                "detail": detail,
                "clauses": clauses_of(detail),
                "close_price": _number(record["收盤價"]),
                "pe_ratio": _number(record["本益比"]),
                "cumulative_count": _count(record["累計"]),
            },
        )
    return _tpex_parsed(rows, empty, len(records))


def _period(cell: Any) -> tuple[date, date]:
    parts = _PERIOD_SPLIT.split(_text(cell))
    if len(parts) != 2:
        raise LayoutError(f"unreadable period {cell!r}")
    start, end = roc_date(parts[0]), roc_date(parts[1])
    if end < start:
        raise LayoutError(f"period {cell!r} ends before it starts")
    return start, end


def _disposal(record: dict, period_key: str, reason_key: str) -> dict[str, Any]:
    start, end = _period(record[period_key])
    detail = clean_text(record["處置內容"]) or None
    return {
        "start_date": start,
        "end_date": end,
        "security_name": security_name(record["證券名稱"]),
        "measure": _text(record["處置措施"]) or None,
        "reason": clean_text(record[reason_key]) or None,
        "match_interval_minutes": interval_of(detail),
        "prepayment": prepayment_of(detail),
        "detail": detail,
    }


def parse_twse_punish(payload: Any, first: date, last: date) -> Parsed:
    body = _twse_body(payload, first, last)
    rows: dict[tuple, dict[str, Any]] = {}
    records = _records(body.get("fields"), body.get("data"), TWSE_PUNISH_FIELDS)
    for record in records:
        code = _text(record["證券代號"])
        if not code:
            raise LayoutError(f"a row without a code: {record!r}")
        announced = roc_date(record["公布日期"])
        values = _disposal(record, "處置起迄時間", "處置條件")
        # 累計 counts within the query period: not kept.
        values["cumulative_count"] = None
        _keep(rows, (code, announced, values["start_date"]), values)
    return Parsed(rows, set(), len(records))


def parse_tpex_disposal(payload: Any, first: date, last: date) -> Parsed:
    table = _tpex_table(payload, TPEX_DISPOSAL_TITLE, first, last)
    rows: dict[tuple, dict[str, Any]] = {}
    empty: set[date] = set()
    records = _records(table.get("fields"), table.get("data"), TPEX_DISPOSAL_FIELDS)
    for record in records:
        code = _text(record["證券代號"])
        announced = roc_date(record["公布日期"])
        if not code:
            if clean_text(record["處置內容"]) != DISPOSAL_PLACEHOLDER:
                raise LayoutError(f"a row without a code: {record!r}")
            empty.add(_within(announced, first, last))
            continue
        values = _disposal(record, "處置起訖時間", "處置原因")
        values["cumulative_count"] = _count(record["累計"])
        _keep(rows, (code, announced, values["start_date"]), values)
    return _tpex_parsed(rows, empty, len(records))


PARSERS: dict[str, Callable[[Any, date, date], Parsed]] = {
    "twse-notice": parse_twse_notice,
    "twse-punish": parse_twse_punish,
    "tpex-attention": parse_tpex_attention,
    "tpex-disposal": parse_tpex_disposal,
}


def parse(feed: Feed, payload: Any, month: date) -> Parsed:
    first, last = window(feed, month)
    return PARSERS[feed.name](payload, first, last)


# --- the database ---------------------------------------------------------------


def _instruments(db: Session, exchange: str) -> dict[str, int]:
    return dict(
        db.execute(
            select(Instrument.symbol, Instrument.id).where(
                Instrument.exchange == exchange,
                Instrument.instrument_type.in_(INSTRUMENT_TYPES),
            )
        ).all()
    )


def _month_run(db: Session, feed: Feed, month: date) -> IngestionRun:
    key = REQUEST_KEY.format(feed=feed.name, month=f"{month:%Y-%m}")
    run = db.scalar(select(IngestionRun).where(IngestionRun.request_key == key))
    if run is None:
        first, last = window(feed, month)
        run = IngestionRun(
            run_type=MONTH_RUN_TYPE,
            source=feed.name,
            run_date=month,
            status="running",
            request_key=key,
            data_as_of=f"{first.isoformat()}~{last.isoformat()}",
            metadata_json={},
        )
        db.add(run)
        db.flush()
    return run


def write_month(
    db: Session,
    feed: Feed,
    month: date,
    parsed: Parsed,
    raw: RawPayload,
    instruments: dict[str, int],
) -> dict[str, Any]:
    """Make the feed's rows of ``month`` the parsed ones; the counts."""

    last = month_end(month)
    if feed.kind == "attention":
        model, day_column, date_names = (
            TradingAttention,
            TradingAttention.attention_date,
            ("attention_date",),
        )
    else:
        model, day_column, date_names = (
            TradingDisposal,
            TradingDisposal.announced_date,
            ("announced_date", "start_date"),
        )
    owned = {
        key: values for key, values in parsed.rows.items() if month <= key[1] <= last
    }
    kept = {
        (row.symbol, *(getattr(row, name) for name in date_names)): row
        for row in db.scalars(
            select(model).where(
                model.source == feed.source,
                day_column >= month,
                day_column <= last,
            )
        )
    }
    counts: Counter = Counter()
    unmatched: set[str] = set()
    for key, values in owned.items():
        code = key[0]
        instrument_id = instruments.get(code)
        if instrument_id is None:
            unmatched.add(code)
        fields = {
            **values,
            "instrument_id": instrument_id,
            "data_as_of": key[1],
            "raw_payload_id": raw.id,
            "collected_at": raw.collected_at,
        }
        row = kept.pop(key, None)
        if row is None:
            db.add(
                model(
                    exchange=feed.exchange,
                    symbol=code,
                    source=feed.source,
                    # The disposal's start_date is among its values.
                    **{date_names[0]: key[1]},
                    **fields,
                )
            )
            counts["inserted"] += 1
            continue
        changed = {
            name: value for name, value in fields.items() if getattr(row, name) != value
        }
        for name, value in changed.items():
            setattr(row, name, value)
        # A new capture alone is no change of the row: it cites the newest one.
        if set(changed) - {"raw_payload_id", "collected_at"}:
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1
    for row in kept.values():
        db.delete(row)
        counts["removed"] += 1
    nulls: Counter = Counter()
    for values in owned.values():
        for name in ("clauses", "match_interval_minutes", "prepayment", "detail"):
            if name in values and values[name] is None:
                nulls[name] += 1
    return {
        "answer_rows": parsed.answer_rows,
        "rows": len(owned),
        "other_month": len(parsed.rows) - len(owned),
        "inserted": counts["inserted"],
        "updated": counts["updated"],
        "removed": counts["removed"],
        "unchanged": counts["unchanged"],
        "unmatched": len(unmatched),
        "unmatched_codes": sorted(unmatched)[:MAX_LISTED],
        "empty_days": sorted(
            day.isoformat() for day in parsed.empty_days if month <= day <= last
        ),
        "placeholder_with_rows": sorted(
            day.isoformat()
            for day in parsed.placeholder_with_rows
            if month <= day <= last
        ),
        "nulls": dict(sorted(nulls.items())),
    }


def read_raw(row: RawPayload) -> Any:
    """The JSON of a stored capture, its SHA-256 checked."""

    path = payload_file(row.payload_path)
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise OfficialDataError(f"raw payload {row.id} is missing: {path}") from exc
    if hashlib.sha256(content).hexdigest() != row.sha256:
        raise OfficialDataError(f"raw payload {row.id} is not its SHA-256: {path}")
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OfficialDataError(f"raw payload {row.id} is not JSON: {path}") from exc


# --- the clock ------------------------------------------------------------------


def _taipei(moment: datetime) -> datetime:
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return aware.astimezone(TAIPEI)


def seconds_to_wait(moment: datetime) -> float:
    """How long a request at ``moment`` waits: quiet hours and even hours."""

    start = local = _taipei(moment)
    for _ in range(4):
        now = local.time()
        if QUIET_START <= now < QUIET_END:
            local = local.replace(
                hour=QUIET_END.hour, minute=QUIET_END.minute, second=0, microsecond=0
            )
            continue
        hour = local.replace(minute=0, second=0, microsecond=0)
        nearest = hour + timedelta(hours=1) if local.minute >= 30 else hour
        if nearest.hour % 2 == 0 and abs(local - nearest) < EVEN_HOUR_MARGIN:
            local = nearest + EVEN_HOUR_MARGIN
            continue
        break
    return (local - start).total_seconds()


def latest_complete_month(moment: datetime) -> date:
    return month_start(month_start(_taipei(moment).date()) - timedelta(days=1))


# --- the run --------------------------------------------------------------------


def _empty_counts(feed: Feed) -> dict[str, Any]:
    return {
        "months": 0,
        "done_before": 0,
        "requested": 0,
        "reapplied": 0,
        "success": 0,
        "failed": 0,
        "failed_months": [],
        "answer_rows": 0,
        "rows": 0,
        "inserted": 0,
        "updated": 0,
        "removed": 0,
        "unchanged": 0,
        "unmatched": 0,
        "empty_days": 0,
        "placeholder_with_rows": 0,
        "first_month": f"{feed.first_month:%Y-%m}",
    }


def backfill(
    db: Session,
    start: date | None = None,
    end: date | None = None,
    *,
    feeds: list[str] | None = None,
    reapply: bool = False,
    max_requests: int | None = None,
    fetch: Callable[[Feed, date], Any] = fetch_official,
    now: Callable[[], datetime] = utcnow,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    latest = latest_complete_month(now())
    end = month_start(end) if end else latest
    if end > latest:
        raise Refused(
            f"{end:%Y-%m} is not a complete month yet; the latest is {latest:%Y-%m}"
        )
    names = feeds or list(FEEDS)
    unknown = [name for name in names if name not in FEEDS]
    if unknown:
        raise Refused(f"unknown feeds {unknown}; known: {list(FEEDS)}")
    if max_requests is not None and max_requests < 0:
        raise Refused("--max-requests is negative")
    if start is not None and month_start(start) > end:
        raise Refused(f"--start-month {start:%Y-%m} is after {end:%Y-%m}")
    for table in ("trading_attentions", "trading_disposals"):
        if not inspect(db.get_bind()).has_table(table):
            raise ValueError(f"{table} is missing: run init-db first")
    started = time.monotonic()
    result = {name: _empty_counts(FEEDS[name]) for name in names}
    plan: dict[date, list[Feed]] = {}
    for name in names:
        feed = FEEDS[name]
        month = max(month_start(start) if start else feed.first_month, feed.first_month)
        while month <= end:
            plan.setdefault(month, []).append(feed)
            result[name]["months"] += 1
            month = next_month(month)
    instruments = {
        exchange: _instruments(db, exchange)
        for exchange in {FEEDS[name].exchange for name in names}
    }
    requests = 0
    failures_in_a_row = 0
    stopped = None
    for month in sorted(plan):
        for feed in plan[month]:
            counts = result[feed.name]
            run = _month_run(db, feed, month)
            done = run.status == "success"
            if done and not reapply:
                counts["done_before"] += 1
                continue
            if not done and max_requests is not None and requests >= max_requests:
                stopped = f"--max-requests {max_requests} reached"
                break
            raw: RawPayload | None = None
            try:
                if done:
                    counts["reapplied"] += 1
                    raw = db.get(
                        RawPayload, (run.metadata_json or {}).get("raw_payload_id")
                    )
                    if raw is None:
                        raise OfficialDataError("the stored month has no raw payload")
                    payload = read_raw(raw)
                else:
                    wait = seconds_to_wait(now())
                    if wait > 0:
                        sleep(wait)
                    endpoint, _form = request_of(feed, month)
                    requests += 1
                    counts["requested"] += 1
                    try:
                        payload = fetch(feed, month)
                    except Exception as exc:  # the source's failure, never a crash
                        failures_in_a_row += 1
                        raise OfficialDataError(f"request failed: {exc}") from exc
                    failures_in_a_row = 0
                    captured = sources.capture_payload(
                        feed.raw_source,
                        endpoint,
                        payload,
                        window(feed, month)[1].isoformat(),
                    )
                    raw = pipeline._upsert_raw_payload(db, run, captured)
                    # The capture stays cited by the month even when it does not read.
                    run.metadata_json = {
                        **(run.metadata_json or {}),
                        "raw_payload_id": raw.id,
                    }
                    db.commit()
                parsed = parse(feed, payload, month)
                written = write_month(
                    db, feed, month, parsed, raw, instruments[feed.exchange]
                )
            except OfficialDataError as exc:
                db.rollback()
                run = _month_run(db, feed, month)
                run.status = "failed"
                run.error = str(exc)
                run.finished_at = utcnow()
                run.metadata_json = {**(run.metadata_json or {}), "error": str(exc)}
                db.commit()
                counts["failed"] += 1
                if len(counts["failed_months"]) < MAX_LISTED:
                    counts["failed_months"].append(
                        {"month": f"{month:%Y-%m}", "error": str(exc)}
                    )
                if failures_in_a_row >= ABORT_AFTER_FAILURES:
                    stopped = f"{failures_in_a_row} failed requests in a row"
                    break
                continue
            run.status = "success"
            run.error = None
            run.records = written["rows"]
            run.finished_at = utcnow()
            run.metadata_json = {"raw_payload_id": raw.id, **written}
            db.commit()
            counts["success"] += 1
            for key in (
                "answer_rows",
                "rows",
                "inserted",
                "updated",
                "removed",
                "unchanged",
                "unmatched",
            ):
                counts[key] += written[key]
            counts["empty_days"] += len(written["empty_days"])
            counts["placeholder_with_rows"] += len(written["placeholder_with_rows"])
        if stopped:
            break
    remaining = 0
    for counts in result.values():
        counts["changed"] = counts["inserted"] + counts["updated"] + counts["removed"]
    for month, month_feeds in plan.items():
        for feed in month_feeds:
            key = REQUEST_KEY.format(feed=feed.name, month=f"{month:%Y-%m}")
            status = db.scalar(
                select(IngestionRun.status).where(IngestionRun.request_key == key)
            )
            remaining += status != "success"
    failed = sum(counts["failed"] for counts in result.values())
    return {
        "status": "partial" if failed or stopped or remaining else "success",
        "start": f"{min(plan):%Y-%m}" if plan else None,
        "end": f"{end:%Y-%m}",
        "requests": requests,
        "stopped": stopped,
        "remaining_months": remaining,
        "changed": sum(counts["changed"] for counts in result.values()),
        "feeds": result,
        "duration_seconds": round(time.monotonic() - started, 1),
    }


def run_trading_notices_backfill(
    start_month: str | None = None,
    end_month: str | None = None,
    *,
    feeds: list[str] | None = None,
    reapply: bool = False,
    max_requests: int | None = None,
) -> dict[str, Any]:
    from app.db import SessionLocal

    try:
        first = parse_month(start_month) if start_month else None
        last = parse_month(end_month) if end_month else None
    except ValueError as exc:
        return {"status": "refused", "error": str(exc)}
    previous = sources.set_minimum_host_interval(REQUEST_INTERVAL_SECONDS)
    try:
        with SessionLocal() as db:
            try:
                return backfill(
                    db,
                    first,
                    last,
                    feeds=feeds,
                    reapply=reapply,
                    max_requests=max_requests,
                )
            except Refused as exc:
                return {"status": "refused", "error": str(exc)}
            except ValueError as exc:
                db.rollback()
                return {"status": "failed", "error": str(exc)}
    finally:
        sources.set_minimum_host_interval(previous)
