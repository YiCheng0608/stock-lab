"""Daily securities lending and day trades of the research database (Issue #1089).

Four feeds, one ``sbl-daytrade backfill`` command (#1085 decision 7208519530):

- ``twse-sbl``: TWSE ``TWT93U`` (信用額度總量管制餘額表) 借券賣出, one request a
  session from ``TWT93U_FIRST_DATE``, into ``securities_lending_daily``.
- ``tpex-sbl``: TPEx ``margin/sbl`` (the same table), from ``TPEX_SBL_FIRST_DATE``.
- ``twse-daytrade``: TWSE ``TWTB4U`` (當日沖銷交易標的及成交量值), from
  ``DAY_TRADE_FIRST_DATE``, into ``day_trade_daily``.
- ``tpex-daytrade``: TPEx ``intraday/stat`` (``type=Daily``), from the same day.

The sessions are the research DB's: the days with a TWSE or TPEx bar of a stock,
``ipo`` or ETF in the range, from each feed's first day (no request before it).
Rows go to the instruments with a bar that day only; a code of the official table
without one is counted (``unmatched``), never created, as
``STOCK_HISTORY_CREATE_UNMATCHED`` leaves instruments to the bars.  A barred
instrument the table does not list gets no row (``no_row``): the lending table lists
the margin securities and the day trade table that day's day-trade securities, so
an absent code is no data, never 0.

Each feed and session is one ``ingestion_runs`` row (``DAY_RUN_TYPE``, request key
``sbl_daytrade_backfill:<feed>:<date>``): the manifest.  A session already
``success`` is not asked again; ``reapply`` rereads its stored raw instead and
rewrites the rows, ``changed 0`` when nothing differs.  A failed session is asked
again on the next run.  One commit a feed and session, so a stopped run resumes.

A table that is not one of the known layouts (``*_LAYOUTS``, matched on all column
names in order: TWSE lending before and from 2012-03-19, TPEx day trades with and
without the 暫停現股賣出後現款買進當沖註記 column), a value that does not read as a
non-negative number, a reported date other than the session, a row count other than
the stated one or an empty table fails the whole session; nothing of it is written
and nothing is guessed.  A blank or ``-`` cell is NULL; 0 stays 0.

Requests: at least ``REQUEST_INTERVAL_SECONDS`` apart on a host, none between
``QUIET_START`` and ``QUIET_END`` Taipei nor within ``EVEN_HOUR_MARGIN`` of an even
hour (the run waits), ``ABORT_AFTER_FAILURES`` failed requests in a row stop it.
Only on the research database (``quarterly_xbrl.research_refusal``), holding
maintenance mode (``worker.cli``).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from datetime import time as clock_time
from typing import Any, Callable

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.models import (
    DayTradeDaily,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
    SecuritiesLendingDaily,
)
from app.raw_paths import payload_file
from worker import pipeline, sources
from worker.sources import OfficialDataError

TWT93U_ENDPOINT = "https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U"
TWTB4U_ENDPOINT = "https://www.twse.com.tw/rwd/zh/dayTrading/TWTB4U"
TPEX_SBL_ENDPOINT = "https://www.tpex.org.tw/www/zh-tw/margin/sbl"
TPEX_DAY_TRADE_ENDPOINT = "https://www.tpex.org.tw/www/zh-tw/intraday/stat"

# docs/DATA_SOURCES.md 各來源最早可得 (#1085): TWT93U answers 「查詢日期小於94年7月
# 1日」 and TWTB4U 「查詢日期小於103年1月6日」 before these; TPEx answers empty
# tables before its days.
TWT93U_FIRST_DATE = date(2005, 7, 1)
TPEX_SBL_FIRST_DATE = date(2012, 10, 2)
DAY_TRADE_FIRST_DATE = date(2014, 1, 6)

DAY_RUN_TYPE = "sbl_daytrade_backfill_day"
REQUEST_KEY = "sbl_daytrade_backfill:{feed}:{day}"
REQUEST_INTERVAL_SECONDS = 3.5
# Taipei: the production daily, and the production jobs around the even hours
# (Issue #1089).
QUIET_START = clock_time(21, 15)
QUIET_END = clock_time(23, 30)
EVEN_HOUR_MARGIN = timedelta(minutes=10)
TAIPEI = timezone(timedelta(hours=8))
ABORT_AFTER_FAILURES = 5
MAX_LISTED = 200
BAR_TYPES = ("stock", "ipo", "etf")

NULL_CELLS = frozenset({"", "-", "--", "---"})

# --- layouts ------------------------------------------------------------------
# A layout is its column names in order and, for each value read, its position:
# the lending tables name 前日餘額 (and TWSE 賣出) under both 融券 and 借券賣出.


@dataclass(frozen=True)
class Layout:
    fields: tuple[str, ...]
    at: dict[str, int | None]  # value name -> column; None: not in this layout


TWSE_SBL_LAYOUTS = (
    # From 2012-03-19 (自101年3月19日起借券賣出餘額採用新公式計算).
    Layout(
        (
            "代號",
            "名稱",
            "前日餘額",
            "賣出",
            "買進",
            "現券",
            "今日餘額",
            "次一營業日限額",
            "前日餘額",
            "當日賣出",
            "當日還券",
            "當日調整",
            "當日餘額",
            "次一營業日可限額",
            "備註",
        ),
        {"code": 0, "sell": 9, "return": 10, "balance": 12, "note": 14},
    ),
    # To 2012-03-16: 借券賣出 前日餘額、賣出、庫存異動 (履約＋還券)、今日餘額、可使用額度.
    Layout(
        (
            "代號",
            "名稱",
            "前日餘額",
            "賣出",
            "買進",
            "現券",
            "今日餘額",
            "次一營業日限額",
            "前日餘額",
            "賣出",
            "庫存異動",
            "今日餘額",
            "可使用額度",
            "備註",
        ),
        {"code": 0, "sell": 9, "return": None, "balance": 11, "note": 13},
    ),
)
TPEX_SBL_LAYOUTS = (
    Layout(
        (
            "股票代號",
            "股票名稱",
            "前日餘額",
            "賣出",
            "買進",
            "現券",
            "當日餘額",
            "限額",
            "前日餘額",
            "當日賣出",
            "當日還券",
            "當日調整數額",
            "當日餘額",
            "次一營業日可借券賣出限額",
            "備註",
        ),
        {"code": 0, "sell": 9, "return": 10, "balance": 12, "note": 14},
    ),
)
_DAY_TRADE_WITH_MARK = Layout(
    (
        "證券代號",
        "證券名稱",
        "暫停現股賣出後現款買進當沖註記",
        "當日沖銷交易成交股數",
        "當日沖銷交易買進成交金額",
        "當日沖銷交易賣出成交金額",
    ),
    {"code": 0, "mark": 2, "shares": 3, "buy": 4, "sell": 5},
)
TWSE_DAY_TRADE_LAYOUTS = (_DAY_TRADE_WITH_MARK,)
TPEX_DAY_TRADE_LAYOUTS = (
    _DAY_TRADE_WITH_MARK,
    # 2014: no 暫停現股賣出後現款買進當沖註記 column.
    Layout(
        (
            "證券代號",
            "證券名稱",
            "當日沖銷交易成交股數",
            "當日沖銷交易買進成交金額",
            "當日沖銷交易賣出成交金額",
        ),
        {"code": 0, "mark": None, "shares": 2, "buy": 3, "sell": 4},
    ),
)
TWSE_DAY_TRADE_TITLE = "當日沖銷交易標的及成交量值"
_ROC_DAY = re.compile(r"(\d{2,3})/(\d{1,2})/(\d{1,2})")
_ROC_TITLE_DAY = re.compile(r"(\d{2,3})年(\d{1,2})月(\d{1,2})日")


class LayoutError(OfficialDataError):
    """The day's table is not one this reads; nothing of the day is written."""


# --- feeds --------------------------------------------------------------------


@dataclass(frozen=True)
class Feed:
    name: str
    exchange: str
    table: type
    first_date: date
    raw_source: str  # raw_payloads.source and the raw directory
    source: str  # the rows' source


FEEDS: dict[str, Feed] = {
    feed.name: feed
    for feed in (
        Feed(
            "twse-sbl",
            "TWSE",
            SecuritiesLendingDaily,
            TWT93U_FIRST_DATE,
            "twse",
            "twse_twt93u",
        ),
        Feed(
            "tpex-sbl",
            "TPEx",
            SecuritiesLendingDaily,
            TPEX_SBL_FIRST_DATE,
            "tpex",
            "tpex_sbl",
        ),
        Feed(
            "twse-daytrade",
            "TWSE",
            DayTradeDaily,
            DAY_TRADE_FIRST_DATE,
            "twse",
            "twse_twtb4u",
        ),
        Feed(
            "tpex-daytrade",
            "TPEx",
            DayTradeDaily,
            DAY_TRADE_FIRST_DATE,
            "tpex",
            "tpex_intraday_stat",
        ),
    )
}


def request_of(feed: str, day: date) -> tuple[str, str, dict[str, str] | None]:
    """(method, the endpoint kept in raw_payloads, form) of a feed's session."""

    compact = day.strftime("%Y%m%d")
    slashed = day.strftime("%Y/%m/%d")
    if feed == "twse-sbl":
        return "GET", f"{TWT93U_ENDPOINT}?date={compact}&response=json", None
    if feed == "twse-daytrade":
        url = f"{TWTB4U_ENDPOINT}?date={compact}&selectType=All&response=json"
        return "GET", url, None
    if feed == "tpex-sbl":
        form = {"date": slashed, "response": "json"}
        return "POST", f"{TPEX_SBL_ENDPOINT}?date={slashed}&response=json", form
    if feed == "tpex-daytrade":
        form = {"date": slashed, "type": "Daily", "response": "json"}
        url = f"{TPEX_DAY_TRADE_ENDPOINT}?date={slashed}&type=Daily&response=json"
        return "POST", url, form
    raise ValueError(f"unknown feed {feed}")


def fetch_official(feed: str, day: date) -> Any:
    method, url, form = request_of(feed, day)
    if method == "POST":
        return sources.fetch_json(url.split("?")[0], method="POST", data=form)
    return sources.fetch_json(url)


# --- cells --------------------------------------------------------------------


def _number(cell: Any) -> float | None:
    if cell is None:
        return None
    if isinstance(cell, bool):
        raise LayoutError(f"unreadable value {cell!r}")
    text = str(cell).strip().replace(",", "")
    if text in NULL_CELLS:
        return None
    try:
        value = float(text)
    except ValueError as exc:
        raise LayoutError(f"unreadable value {cell!r}") from exc
    if not math.isfinite(value) or value < 0:
        raise LayoutError(f"unreadable value {cell!r}")
    return value


def _shares(cell: Any) -> int | None:
    value = _number(cell)
    if value is None:
        return None
    if not value.is_integer():
        raise LayoutError(f"unreadable share count {cell!r}")
    return int(value)


def _mark(cell: Any) -> str | None:
    text = "" if cell is None else str(cell).strip()
    if len(text) > 20:
        raise LayoutError(f"unreadable mark {cell!r}")
    return text or None


def _roc(match: re.Match[str] | None) -> date | None:
    if not match:
        return None
    try:
        return date(
            int(match.group(1)) + 1911, int(match.group(2)), int(match.group(3))
        )
    except ValueError:
        return None


def _count(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).replace(",", ""))
    except ValueError as exc:
        raise LayoutError(f"unreadable row count {value!r}") from exc


# --- parsers: {code: values} ----------------------------------------------------


def _layout_rows(
    fields: Any, data: Any, layouts: tuple[Layout, ...], stated: Any
) -> tuple[Layout, list[list[Any]]]:
    layout = next(
        (
            item
            for item in layouts
            if isinstance(fields, list) and tuple(fields) == item.fields
        ),
        None,
    )
    if layout is None:
        raise LayoutError(f"unknown columns {fields!r}")
    if not isinstance(data, list) or not data:
        raise LayoutError("the table has no rows")
    count = _count(stated)
    if count is not None and count != len(data):
        raise LayoutError(f"stated {count} rows but {len(data)} came")
    for row in data:
        if not isinstance(row, list) or len(row) != len(layout.fields):
            raise LayoutError(f"a row does not match the columns: {row!r}")
    return layout, data


def _by_code(
    layout: Layout,
    rows: list[list[Any]],
    values: Callable[[Layout, list[Any]], dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = str(row[layout.at["code"]] or "").strip()
        if not code:
            raise LayoutError(f"a row without a code: {row!r}")
        if code in result:
            raise LayoutError(f"code {code} is listed twice")
        result[code] = values(layout, row)
    return result


def _cell(layout: Layout, row: list[Any], name: str) -> Any:
    at = layout.at[name]
    return None if at is None else row[at]


def _lending(layout: Layout, row: list[Any]) -> dict[str, Any]:
    return {
        "sbl_sell_shares": _shares(_cell(layout, row, "sell")),
        "sbl_return_shares": _shares(_cell(layout, row, "return")),
        "sbl_balance_shares": _shares(_cell(layout, row, "balance")),
        "note": _mark(_cell(layout, row, "note")),
    }


def _day_trade(layout: Layout, row: list[Any]) -> dict[str, Any]:
    return {
        "day_trade_shares": _shares(_cell(layout, row, "shares")),
        "day_trade_buy_value": _number(_cell(layout, row, "buy")),
        "day_trade_sell_value": _number(_cell(layout, row, "sell")),
        "sell_first_suspended": _mark(_cell(layout, row, "mark")),
    }


def _twse_body(payload: Any, day: date) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LayoutError("the answer is not a JSON object")
    if payload.get("stat") != "OK":
        raise LayoutError(f"stat {payload.get('stat')!r}")
    if str(payload.get("date") or "") != day.strftime("%Y%m%d"):
        raise LayoutError(f"reported date {payload.get('date')!r} is not {day}")
    return payload


def _tpex_tables(payload: Any, day: date) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise LayoutError("the answer is not a JSON object")
    if str(payload.get("stat") or "").lower() != "ok":
        raise LayoutError(f"stat {payload.get('stat')!r}")
    if str(payload.get("date") or "") != day.strftime("%Y%m%d"):
        raise LayoutError(f"reported date {payload.get('date')!r} is not {day}")
    tables = payload.get("tables")
    if not isinstance(tables, list) or not all(isinstance(t, dict) for t in tables):
        raise LayoutError("the answer has no tables")
    for table in tables:
        if _roc(_ROC_DAY.fullmatch(str(table.get("date") or "").strip())) != day:
            raise LayoutError(f"table date {table.get('date')!r} is not {day}")
    return tables


def parse_twse_sbl(payload: Any, day: date) -> dict[str, dict[str, Any]]:
    body = _twse_body(payload, day)
    layout, rows = _layout_rows(
        body.get("fields"), body.get("data"), TWSE_SBL_LAYOUTS, body.get("total")
    )
    return _by_code(layout, rows, _lending)


def parse_tpex_sbl(payload: Any, day: date) -> dict[str, dict[str, Any]]:
    tables = _tpex_tables(payload, day)
    if len(tables) != 1:
        raise LayoutError(f"{len(tables)} tables, expected 1")
    table = tables[0]
    layout, rows = _layout_rows(
        table.get("fields"),
        table.get("data"),
        TPEX_SBL_LAYOUTS,
        table.get("totalCount"),
    )
    return _by_code(layout, rows, _lending)


def _the_security_table(
    tables: list[dict[str, Any]], layouts: tuple[Layout, ...]
) -> dict[str, Any]:
    """The one table with a security code column; the other is the market's."""

    names = {name for layout in layouts for name in layout.fields[:1]}
    found = [
        table
        for table in tables
        if isinstance(table.get("fields"), list)
        and table["fields"][:1]
        and table["fields"][0] in names
    ]
    if len(found) != 1:
        raise LayoutError(f"{len(found)} security tables, expected 1")
    return found[0]


def parse_twse_day_trade(payload: Any, day: date) -> dict[str, dict[str, Any]]:
    body = _twse_body(payload, day)
    tables = body.get("tables")
    if not isinstance(tables, list) or not all(isinstance(t, dict) for t in tables):
        raise LayoutError("the answer has no tables")
    table = _the_security_table(tables, TWSE_DAY_TRADE_LAYOUTS)
    title = str(table.get("title") or "")
    if TWSE_DAY_TRADE_TITLE not in title:
        raise LayoutError(f"title {title!r}")
    if _roc(_ROC_TITLE_DAY.search(title)) != day:
        raise LayoutError(f"table title date {title!r} is not {day}")
    layout, rows = _layout_rows(
        table.get("fields"),
        table.get("data"),
        TWSE_DAY_TRADE_LAYOUTS,
        table.get("total"),
    )
    return _by_code(layout, rows, _day_trade)


def parse_tpex_day_trade(payload: Any, day: date) -> dict[str, dict[str, Any]]:
    table = _the_security_table(_tpex_tables(payload, day), TPEX_DAY_TRADE_LAYOUTS)
    layout, rows = _layout_rows(
        table.get("fields"),
        table.get("data"),
        TPEX_DAY_TRADE_LAYOUTS,
        table.get("totalCount"),
    )
    return _by_code(layout, rows, _day_trade)


PARSERS: dict[str, Callable[[Any, date], dict[str, dict[str, Any]]]] = {
    "twse-sbl": parse_twse_sbl,
    "tpex-sbl": parse_tpex_sbl,
    "twse-daytrade": parse_twse_day_trade,
    "tpex-daytrade": parse_tpex_day_trade,
}


# --- the database ---------------------------------------------------------------


def _sessions(db: Session, exchange: str, start: date, end: date) -> list[date]:
    return list(
        db.scalars(
            select(MarketBar.trading_date)
            .join(Instrument, Instrument.id == MarketBar.instrument_id)
            .where(
                Instrument.exchange == exchange,
                Instrument.instrument_type.in_(BAR_TYPES),
                MarketBar.trading_date >= start,
                MarketBar.trading_date <= end,
            )
            .distinct()
            .order_by(MarketBar.trading_date)
        )
    )


def _barred(db: Session, exchange: str, day: date) -> dict[str, int]:
    """{code: instrument id} of the exchange's instruments with a bar on ``day``."""

    return dict(
        db.execute(
            select(Instrument.symbol, Instrument.id)
            .join(MarketBar, MarketBar.instrument_id == Instrument.id)
            .where(
                Instrument.exchange == exchange,
                Instrument.instrument_type.in_(BAR_TYPES),
                MarketBar.trading_date == day,
            )
        ).all()
    )


def _day_run(db: Session, feed: str, day: date) -> IngestionRun:
    key = REQUEST_KEY.format(feed=feed, day=day.isoformat())
    run = db.scalar(select(IngestionRun).where(IngestionRun.request_key == key))
    if run is None:
        run = IngestionRun(
            run_type=DAY_RUN_TYPE,
            source=feed,
            run_date=day,
            status="running",
            request_key=key,
            data_as_of=day.isoformat(),
            metadata_json={},
        )
        db.add(run)
        db.flush()
    return run


def write_rows(
    db: Session,
    feed: Feed,
    day: date,
    parsed: dict[str, dict[str, Any]],
    raw: RawPayload,
) -> dict[str, Any]:
    """Make the feed's rows of ``day`` the parsed ones; the counts."""

    barred = _barred(db, feed.exchange, day)
    model = feed.table
    counts = Counter()
    kept = {
        row.instrument_id: row
        for row in db.scalars(
            select(model).where(model.trading_date == day, model.source == feed.source)
        )
    }
    unmatched = sorted(code for code in parsed if code not in barred)
    written: set[int] = set()
    nulls = Counter()
    for code, values in parsed.items():
        instrument_id = barred.get(code)
        if instrument_id is None:
            continue
        written.add(instrument_id)
        for name, value in values.items():
            if value is None:
                nulls[name] += 1
        fields = {
            **values,
            "source": feed.source,
            "data_as_of": day,
            "raw_payload_id": raw.id,
            "collected_at": raw.collected_at,
        }
        row = kept.get(instrument_id)
        if row is None:
            db.add(model(instrument_id=instrument_id, trading_date=day, **fields))
            counts["inserted"] += 1
        elif any(getattr(row, name) != value for name, value in fields.items()):
            for name, value in fields.items():
                setattr(row, name, value)
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1
    for instrument_id, row in kept.items():
        if instrument_id not in written:
            db.delete(row)
            counts["removed"] += 1
    return {
        "rows": len(parsed),
        "written": len(written),
        "inserted": counts["inserted"],
        "updated": counts["updated"],
        "removed": counts["removed"],
        "unchanged": counts["unchanged"],
        "unmatched": len(unmatched),
        "unmatched_codes": unmatched[:MAX_LISTED],
        "no_row": len(set(barred) - set(parsed)),
        "nulls": dict(sorted(nulls.items())),
    }


# --- stored raw -----------------------------------------------------------------


def read_raw(row: RawPayload) -> Any:
    """The JSON of a stored capture, its SHA-256 checked."""

    path = payload_file(row.payload_path)
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise OfficialDataError(
            f"raw payload {row.id} is missing: {row.payload_path}"
        ) from exc
    if hashlib.sha256(content).hexdigest() != row.sha256:
        raise OfficialDataError(f"raw payload {row.id} is not its SHA-256: {path}")
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OfficialDataError(f"raw payload {row.id} is not JSON: {path}") from exc


# --- the run --------------------------------------------------------------------


def _taipei(moment: datetime) -> datetime:
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return aware.astimezone(TAIPEI)


def quiet_wait_seconds(moment: datetime) -> float:
    """Seconds until a request may go; 0 outside the quiet times.

    Quiet: ``QUIET_START`` to ``QUIET_END`` Taipei, and ``EVEN_HOUR_MARGIN`` before
    and after every even hour (00:00, 02:00 ... 22:00).
    """

    local = _taipei(moment)
    free = local
    while True:
        moved = False
        start = free.replace(
            hour=QUIET_START.hour, minute=QUIET_START.minute, second=0, microsecond=0
        )
        end = free.replace(
            hour=QUIET_END.hour, minute=QUIET_END.minute, second=0, microsecond=0
        )
        if start <= free < end:
            free, moved = end, True
        hour = free.replace(minute=0, second=0, microsecond=0)
        for even in (hour, hour + timedelta(hours=1)):
            if (
                even.hour % 2 == 0
                and even - EVEN_HOUR_MARGIN <= free < even + EVEN_HOUR_MARGIN
            ):
                free, moved = even + EVEN_HOUR_MARGIN, True
        if not moved:
            return (free - local).total_seconds()


def _empty_counts(feed: Feed) -> dict[str, Any]:
    return {
        "sessions": 0,
        "not_published": 0,
        "done_before": 0,
        "requested": 0,
        "reapplied": 0,
        "success": 0,
        "failed": 0,
        "failed_days": [],
        "inserted": 0,
        "updated": 0,
        "removed": 0,
        "unchanged": 0,
        "unmatched": 0,
        "no_row": 0,
        "first_date": feed.first_date.isoformat(),
    }


def backfill(
    db: Session,
    start: date,
    end: date,
    *,
    feeds: list[str] | None = None,
    reapply: bool = False,
    fetch: Callable[[str, date], Any] = fetch_official,
    now: Callable[[], datetime] = utcnow,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if end < start:
        raise ValueError("--end is before --start")
    names = list(dict.fromkeys(feeds or FEEDS))
    unknown = [name for name in names if name not in FEEDS]
    if unknown:
        raise ValueError(f"unknown feeds {unknown}; known: {list(FEEDS)}")
    for table in ("securities_lending_daily", "day_trade_daily"):
        if not inspect(db.get_bind()).has_table(table):
            raise ValueError(f"{table} is missing: run init-db first")
    started = time.monotonic()
    result = {name: _empty_counts(FEEDS[name]) for name in names}
    plan: dict[date, list[str]] = {}
    sessions = {
        exchange: _sessions(db, exchange, start, end)
        for exchange in {FEEDS[name].exchange for name in names}
    }
    for name in names:
        feed = FEEDS[name]
        for day in sessions[feed.exchange]:
            result[name]["sessions"] += 1
            if day < feed.first_date:
                result[name]["not_published"] += 1
                continue
            plan.setdefault(day, []).append(name)
    requests = 0
    failures_in_a_row = 0
    aborted = None
    for day in sorted(plan):
        for name in plan[day]:
            feed = FEEDS[name]
            counts = result[name]
            run = _day_run(db, name, day)
            done = run.status == "success"
            if done and not reapply:
                counts["done_before"] += 1
                continue
            raw: RawPayload | None = None
            try:
                if not done:
                    wait = quiet_wait_seconds(now())
                    if wait > 0:
                        sleep(wait)
                    _method, endpoint, _form = request_of(name, day)
                    requests += 1
                    counts["requested"] += 1
                    try:
                        payload = fetch(name, day)
                    except Exception as exc:  # the source's failure, never a crash
                        failures_in_a_row += 1
                        raise OfficialDataError(f"request failed: {exc}") from exc
                    failures_in_a_row = 0
                    captured = sources.capture_payload(
                        feed.raw_source, endpoint, payload, day.isoformat()
                    )
                    raw = pipeline._upsert_raw_payload(db, run, captured)
                else:
                    counts["reapplied"] += 1
                    raw = db.get(
                        RawPayload, (run.metadata_json or {}).get("raw_payload_id")
                    )
                    if raw is None:
                        raise OfficialDataError("the stored session has no raw payload")
                    payload = read_raw(raw)
                parsed = PARSERS[name](payload, day)
                written = write_rows(db, feed, day, parsed, raw)
            except OfficialDataError as exc:
                run.status = "failed"
                run.error = str(exc)
                run.finished_at = utcnow()
                # A session that was a success keeps its capture's id; a new
                # capture that does not read is kept for reading what came.
                metadata = {**(run.metadata_json or {}), "error": str(exc)}
                if raw is not None:
                    metadata["raw_payload_id"] = raw.id
                run.metadata_json = metadata
                db.commit()
                counts["failed"] += 1
                if len(counts["failed_days"]) < MAX_LISTED:
                    counts["failed_days"].append(
                        {"date": day.isoformat(), "error": str(exc)}
                    )
                if failures_in_a_row >= ABORT_AFTER_FAILURES:
                    aborted = f"{failures_in_a_row} failed requests in a row"
                    break
                continue
            run.status = "success"
            run.error = None
            run.records = written["written"]
            run.finished_at = utcnow()
            run.metadata_json = {
                "raw_payload_id": raw.id,
                "source": feed.source,
                **written,
            }
            db.commit()
            counts["success"] += 1
            for key in (
                "inserted",
                "updated",
                "removed",
                "unchanged",
                "unmatched",
                "no_row",
            ):
                counts[key] += written[key]
        if aborted:
            break
    for counts in result.values():
        counts["changed"] = counts["inserted"] + counts["updated"] + counts["removed"]
    failed = sum(counts["failed"] for counts in result.values())
    return {
        "status": "partial" if failed or aborted else "success",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "requests": requests,
        "aborted": aborted,
        "changed": sum(counts["changed"] for counts in result.values()),
        "feeds": result,
        "duration_seconds": round(time.monotonic() - started, 1),
    }


def run_sbl_daytrade_backfill(
    start: str,
    end: str,
    *,
    feeds: list[str] | None = None,
    reapply: bool = False,
) -> dict[str, Any]:
    from app.db import SessionLocal

    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError as exc:
        return {"status": "failed", "error": str(exc)}
    previous = sources.set_minimum_host_interval(REQUEST_INTERVAL_SECONDS)
    try:
        with SessionLocal() as db:
            try:
                return backfill(db, first, last, feeds=feeds, reapply=reapply)
            except ValueError as exc:
                db.rollback()
                return {"status": "failed", "error": str(exc)}
    finally:
        sources.set_minimum_host_interval(previous)
