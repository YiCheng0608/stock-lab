"""Daily P/B, issued shares and foreign holding of the research database.

Six feeds, one ``valuation backfill`` command (#1074 decision 7205622705; the
foreign holding ones #1117 decision 7230109916, Issue #1121):

- ``twse-pb``: TWSE ``BWIBBU_d`` (個股日本益比、殖利率及股價淨值比), one request a
  session from ``BWIBBU_FIRST_DATE``, into ``valuation_daily``.
- ``twse-shares``: TWSE ``MI_QFIIS`` (外資及陸資投資持股統計) 發行股數, one request
  a session from ``MI_QFIIS_FIRST_DATE``, into ``shares_outstanding_daily``.
- ``tpex-pb``: TPEx ``peQryDate``, one request a session, into ``valuation_daily``.
- ``tpex-shares``: the 發行股數 of the TPEx daily quote table already stored, no
  request: the capture the session's TPEx bars cite (``dailyQuotes``, or the
  OpenAPI ``tpex_mainboard_daily_close_quotes`` and its ``Capitals``).  The
  research DB's seed rows (from the production copy) cite files of the production
  volume; ``fallback_raw_dir`` reads them there, read-only.
- ``twse-foreign``: the 外資（及陸資）持股 columns of the ``MI_QFIIS`` raw that
  ``twse-shares`` stored for the session (its manifest's ``raw_payload_id``), no
  request, into ``foreign_holdings_daily``.  A session ``twse-shares`` has not
  answered is ``not_answered``.
- ``tpex-foreign``: TPEx ``insti/qfii`` (僑外資及陸資持股比例排行表), one request a
  session from ``TPEX_QFII_FIRST_DATE``, into ``foreign_holdings_daily``.

The sessions are the research DB's: the days with a TWSE or TPEx bar of a stock,
``ipo`` or ETF in the range, from each feed's first day (no request before it).
Rows go to the instruments with a bar that day only; a code of the official table
without one is counted (``unmatched``), never created, as ``STOCK_HISTORY_CREATE_UNMATCHED``
leaves it to the bars.

Each feed and session is one ``ingestion_runs`` row (``DAY_RUN_TYPE``, request key
``valuation_backfill:<feed>:<date>``): the manifest.  A session already
``success`` is not asked again, and a failed one is asked again on the next run.
``reapply`` sends no request: it rereads the stored raw of every session that has
one (a success, or a failure whose answer did not read, after the parser is fixed)
and rewrites the rows, ``changed 0`` when nothing differs; a session without an
answer is left to a run (``not_answered``).  One commit a feed and session, so a
stopped run resumes.

A table that is not one of the known layouts (``*_LAYOUTS``: the TWSE columns before
and after 2017-04-12, TPEx with and without 財報年/季), a value that does not read
as a number, a reported date other than the session or an empty table fails the
whole session; nothing of it is written and nothing is guessed.  ``-``, ``N/A``,
``null`` and blank are NULL (and 0 shares issued), never 0; 0 shares held or
available is 0.  The ``insti/qfii`` table must also hold ``totalCount`` rows.

Requests: at least ``REQUEST_INTERVAL_SECONDS`` apart on a host, none between
``QUIET_START`` and ``QUIET_END`` Taipei (the run waits), ``ABORT_AFTER_FAILURES``
failed requests in a row to one host stop it (whatever the other host answers).  Only on the research database
(``quarterly_xbrl.research_refusal``), holding maintenance mode (``worker.cli``).
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
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import urlsplit

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.models import (
    IngestionRun,
    Instrument,
    MarketBar,
    ForeignHoldingsDaily,
    RawPayload,
    SharesOutstandingDaily,
    ValuationDaily,
)
from app.raw_paths import legacy_relative, payload_file, raw_dir
from worker import pipeline, sources
from worker.sources import (
    TPEX_DAILY_ENDPOINT,
    TPEX_HISTORY_API,
    TPEX_QUOTES_FIRST_DATE,
    TWSE_QUOTES_FIRST_DATE,
    OfficialDataError,
)

BWIBBU_ENDPOINT = "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d"
MI_QFIIS_ENDPOINT = "https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS"
PE_QRY_DATE_ENDPOINT = "https://www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate"
TPEX_QFII_ENDPOINT = "https://www.tpex.org.tw/www/zh-tw/insti/qfii"

# docs/DATA_SOURCES.md 各來源最早可得 (#1074): BWIBBU_d answers 「查詢日期小於94年9月
# 2日」 before this; MI_QFIIS answers on the research DB's first TWSE session;
# peQryDate has rows from 2007-01-02, before the first TPEx bar (2007-04-23).
BWIBBU_FIRST_DATE = date(2005, 9, 2)
MI_QFIIS_FIRST_DATE = TWSE_QUOTES_FIRST_DATE
PE_QRY_DATE_FIRST_DATE = date(2007, 1, 2)
TPEX_SHARES_FIRST_DATE = TPEX_QUOTES_FIRST_DATE
# insti/qfii answers an empty table (stat ok, totalCount 0) before 96/05/10 (#1117).
TPEX_QFII_FIRST_DATE = date(2007, 5, 10)
# MI_QFIIS writes 法令投資上限比率 0.00 on every row up to this day, which the rows'
# 尚可投資比率 contradict: no data (#1117 decision 7230109916 point 4).
MI_QFIIS_NO_LIMIT_LAST_DATE = date(2004, 7, 23)

DAY_RUN_TYPE = "valuation_backfill_day"
REQUEST_KEY = "valuation_backfill:{feed}:{day}"
REQUEST_INTERVAL_SECONDS = 3.5
# Taipei: the production daily (task file of #1075).
QUIET_START = clock_time(21, 15)
QUIET_END = clock_time(23, 30)
TAIPEI = timezone(timedelta(hours=8))
ABORT_AFTER_FAILURES = 5
MAX_LISTED = 200
BAR_TYPES = ("stock", "ipo", "etf")

# ``null`` (as text): TPEx peQryDate from 2021-07-26 writes it for 6840's 本益比 and
# 股價淨值比, where the other rows write ``N/A`` (#1075).
NULL_CELLS = frozenset({"", "-", "--", "---", "N/A", "null"})

# --- layouts ------------------------------------------------------------------

TWSE_PB_LAYOUTS = (
    (
        "證券代號",
        "證券名稱",
        "收盤價",
        "殖利率(%)",
        "股利年度",
        "本益比",
        "股價淨值比",
        "財報年/季",
    ),
    ("證券代號", "證券名稱", "本益比", "殖利率(%)", "股價淨值比"),
)
TPEX_PB_LAYOUTS = (
    (
        "股票代號",
        "公司名稱",
        "本益比",
        "每股股利",
        "股利年度",
        "殖利率(%)",
        "股價淨值比",
        "財報年/季",
    ),
    (
        "股票代號",
        "公司名稱",
        "本益比",
        "每股股利",
        "股利年度",
        "殖利率(%)",
        "股價淨值比",
    ),
)
MI_QFIIS_LAYOUTS = (
    (
        "證券代號",
        "證券名稱",
        "國際證券編碼",
        "發行股數",
        "外資及陸資尚可投資股數",
        "全體外資及陸資持有股數",
        "外資及陸資尚可投資比率",
        "全體外資及陸資持股比率",
        "外資及陸資共用法令投資上限比率",
        "陸資法令投資上限比率",
        "與前日異動原因(註)",
        "最近一次上市公司申報外資及陸資持股異動日期",
    ),
    (
        "證券代號",
        "證券名稱",
        "國際證券編碼",
        "發行股數",
        "外資尚可投資股數",
        "全體外資持有股數",
        "外資尚可投資比率",
        "全體外資持股比率",
        "法令投資上限比率",
        "與前日異動原因(註)",
        "最近一次上市公司申報外資持股異動日期",
    ),
)
# The TPEx quote table's columns changed over the years (最後買量 and 最後賣量 came
# later); the ones read must be there by name, once.
TPEX_QUOTE_CODE, TPEX_QUOTE_SHARES = "代號", "發行股數"
TPEX_QUOTE_TITLE = "上櫃股票行情"
# The same answer's table of managed (全額交割) stocks: the bars of those days come
# from it too (2008-07-01: 1107, 2410, 5207 and 6 more, most delisted since).  It
# has no date of its own; the main table's is checked.
TPEX_MANAGED_TITLE = "管理股票"
_TWSE_PERIOD = re.compile(r"(\d{2,3})/([1-4])")
_TPEX_PERIOD = re.compile(r"(\d{2,3})Q([1-4])")
_ROC_DAY = re.compile(r"(\d{2,3})/(\d{1,2})/(\d{1,2})")
TPEX_QFII_LAYOUT = (
    "排行",
    "代號",
    "名稱",
    "發行股數(A)",
    "僑外資及陸資尚可投資股數B=A*F-C",
    "僑外資及陸資持有股數(C)",
    "僑外資及陸資尚可投資比率(D=B/A)",
    "僑外資及陸資持股比率(E=C/A)",
    "法令投資上限比率(F)",
    "備註",
)
_HTML_TAG = re.compile(r"<[^>]*>")
# 與前日異動原因: blank or codes (``2``, ``2 4``, ``45``; ``1`` in 2004).
_CHANGE_REASON = re.compile(r"[0-9]+(?: [0-9]+)*")


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
    requests: bool


FEEDS: dict[str, Feed] = {
    feed.name: feed
    for feed in (
        Feed("twse-pb", "TWSE", ValuationDaily, BWIBBU_FIRST_DATE, "twse", True),
        Feed(
            "twse-shares",
            "TWSE",
            SharesOutstandingDaily,
            MI_QFIIS_FIRST_DATE,
            "twse",
            True,
        ),
        Feed("tpex-pb", "TPEx", ValuationDaily, PE_QRY_DATE_FIRST_DATE, "tpex", True),
        Feed(
            "tpex-shares",
            "TPEx",
            SharesOutstandingDaily,
            TPEX_SHARES_FIRST_DATE,
            "tpex",
            False,
        ),
        # After twse-shares: it reads the raw that feed stores for the session.
        Feed(
            "twse-foreign",
            "TWSE",
            ForeignHoldingsDaily,
            MI_QFIIS_FIRST_DATE,
            "twse",
            False,
        ),
        Feed(
            "tpex-foreign",
            "TPEx",
            ForeignHoldingsDaily,
            TPEX_QFII_FIRST_DATE,
            "tpex",
            True,
        ),
    )
}
SOURCES = {
    "twse-pb": "twse_bwibbu_d",
    "twse-shares": "twse_mi_qfiis",
    "tpex-pb": "tpex_pe_qry_date",
    "twse-foreign": "twse_mi_qfiis",
    "tpex-foreign": "tpex_insti_qfii",
}
TABLES = ("valuation_daily", "shares_outstanding_daily", "foreign_holdings_daily")
# tpex-shares: by the endpoint of the capture read.
TPEX_SHARES_SOURCES = {
    TPEX_HISTORY_API: "tpex_daily_quotes",
    TPEX_DAILY_ENDPOINT: "tpex_daily_close_quotes",
}


def request_of(feed: str, day: date) -> tuple[str, str, dict[str, str] | None]:
    """(method, the endpoint kept in raw_payloads, form) of a feed's session."""

    compact = day.strftime("%Y%m%d")
    if feed == "twse-pb":
        url = f"{BWIBBU_ENDPOINT}?date={compact}&selectType=ALL&response=json"
        return "GET", url, None
    if feed == "twse-shares":
        url = f"{MI_QFIIS_ENDPOINT}?date={compact}&selectType=ALLBUT0999&response=json"
        return "GET", url, None
    tpex = {"tpex-pb": PE_QRY_DATE_ENDPOINT, "tpex-foreign": TPEX_QFII_ENDPOINT}
    if feed in tpex:
        form = {"date": day.strftime("%Y/%m/%d"), "response": "json"}
        return "POST", f"{tpex[feed]}?date={form['date']}&response=json", form
    raise ValueError(f"{feed} sends no request")


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
    if not math.isfinite(value):
        raise LayoutError(f"unreadable value {cell!r}")
    return value


def _shares(cell: Any) -> int | None:
    value = _number(cell)
    if value is None or value == 0:
        return None
    if value < 0 or not value.is_integer():
        raise LayoutError(f"unreadable share count {cell!r}")
    return int(value)


def _count(cell: Any) -> int | None:
    """Shares held or available: 0 is 0, blank is NULL."""

    value = _number(cell)
    if value is None:
        return None
    if value < 0 or not value.is_integer():
        raise LayoutError(f"unreadable share count {cell!r}")
    return int(value)


def _percent(cell: Any) -> float | None:
    """A TPEx ratio as ``87.8%``; blank is NULL, a number without ``%`` unread."""

    text = "" if cell is None else str(cell).strip()
    if text in NULL_CELLS:
        return None
    try:
        value = _number(text[:-1]) if text.endswith("%") else None
    except LayoutError:
        value = None
    if value is None:
        raise LayoutError(f"unreadable ratio {cell!r}")
    return value


def _change_reason(cell: Any) -> str | None:
    """與前日異動原因 without the MOPS link it is wrapped in from 2004-02-13."""

    # Only the tags go: ``<a…>2</a>3`` is ``23``, as ``45`` is written without a link.
    text = " ".join(_HTML_TAG.sub("", "" if cell is None else str(cell)).split())
    if not text:
        return None
    if not _CHANGE_REASON.fullmatch(text):
        raise LayoutError(f"unreadable change reason {cell!r}")
    return text


def _filing_day(cell: Any) -> date | None:
    """最近一次申報日期 as ``92/09/16``; the number ``0`` (never filed) is NULL."""

    text = "" if cell is None else str(cell).strip()
    if text in NULL_CELLS or text == "0":
        return None
    day = _roc_day(text)
    if day is None:
        raise LayoutError(f"unreadable filing date {cell!r}")
    return day


def _period(cell: Any, pattern: re.Pattern[str]) -> str | None:
    text = "" if cell is None else str(cell).strip()
    if text in NULL_CELLS:
        return None
    match = pattern.fullmatch(text)
    if not match:
        raise LayoutError(f"unreadable statement period {cell!r}")
    return f"{int(match.group(1)) + 1911}Q{match.group(2)}"


def _roc_day(text: Any) -> date | None:
    match = _ROC_DAY.fullmatch(str(text or "").strip())
    if not match:
        return None
    try:
        return date(
            int(match.group(1)) + 1911, int(match.group(2)), int(match.group(3))
        )
    except ValueError:
        return None


def _code(cell: Any) -> str:
    return str(cell or "").strip()


# --- parsers: {code: values} ----------------------------------------------------


def _rows(
    fields: Any, data: Any, layouts: tuple[tuple[str, ...], ...]
) -> list[dict[str, Any]]:
    if not isinstance(fields, list) or tuple(fields) not in layouts:
        raise LayoutError(f"unknown columns {fields!r}")
    if not isinstance(data, list) or not data:
        raise LayoutError("the table has no rows")
    rows = []
    for row in data:
        if not isinstance(row, list) or len(row) != len(fields):
            raise LayoutError(f"a row does not match the columns: {row!r}")
        rows.append(dict(zip(fields, row)))
    return rows


def _by_code(
    rows: list[dict[str, Any]],
    key: str,
    values: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = _code(row[key])
        if not code:
            raise LayoutError(f"a row without a code: {row!r}")
        if code in result:
            raise LayoutError(f"code {code} is listed twice")
        result[code] = values(row)
    return result


def _twse_header(payload: Any, day: date) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LayoutError("the answer is not a JSON object")
    if payload.get("stat") != "OK":
        raise LayoutError(f"stat {payload.get('stat')!r}")
    if str(payload.get("date") or "") != day.strftime("%Y%m%d"):
        raise LayoutError(f"reported date {payload.get('date')!r} is not {day}")
    total = payload.get("total")
    data = payload.get("data")
    if total is not None and isinstance(data, list) and total != len(data):
        raise LayoutError(f"total {total!r} but {len(data)} rows")
    return payload


def parse_twse_pb(payload: Any, day: date) -> dict[str, dict[str, Any]]:
    body = _twse_header(payload, day)
    rows = _rows(body.get("fields"), body.get("data"), TWSE_PB_LAYOUTS)
    return _by_code(
        rows,
        "證券代號",
        lambda row: {
            "pb_ratio": _number(row["股價淨值比"]),
            "pe_ratio": _number(row["本益比"]),
            "dividend_yield": _number(row["殖利率(%)"]),
            "report_period": _period(row.get("財報年/季"), _TWSE_PERIOD),
        },
    )


def parse_twse_shares(payload: Any, day: date) -> dict[str, dict[str, Any]]:
    body = _twse_header(payload, day)
    rows = _rows(body.get("fields"), body.get("data"), MI_QFIIS_LAYOUTS)
    return _by_code(
        rows, "證券代號", lambda row: {"shares_issued": _shares(row["發行股數"])}
    )


def parse_twse_foreign(payload: Any, day: date) -> dict[str, dict[str, Any]]:
    """The 外資 (to 2009-04-30) or 外資及陸資 (from 2009-05-04) columns."""

    body = _twse_header(payload, day)
    rows = _rows(body.get("fields"), body.get("data"), MI_QFIIS_LAYOUTS)
    mainland = "全體外資及陸資持有股數" in body["fields"]
    who = "外資及陸資" if mainland else "外資"
    limit_name = "外資及陸資共用法令投資上限比率" if mainland else "法令投資上限比率"

    def values(row: dict[str, Any]) -> dict[str, Any]:
        limit = _number(row[limit_name])
        if limit == 0 and day <= MI_QFIIS_NO_LIMIT_LAST_DATE:
            limit = None
        return {
            "shares_issued": _shares(row["發行股數"]),
            "foreign_shares_held": _count(row[f"全體{who}持有股數"]),
            "foreign_held_pct": _number(row[f"全體{who}持股比率"]),
            "foreign_available_shares": _count(row[f"{who}尚可投資股數"]),
            "foreign_limit_pct": limit,
            "mainland_limit_pct": _number(row["陸資法令投資上限比率"])
            if mainland
            else None,
            "change_reason": _change_reason(row["與前日異動原因(註)"]),
            "last_filing_date": _filing_day(
                row[f"最近一次上市公司申報{who}持股異動日期"]
            ),
            "note": None,
        }

    return _by_code(rows, "證券代號", values)


def _tpex_table(payload: Any, day: date, *, title: str | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LayoutError("the answer is not a JSON object")
    if str(payload.get("stat") or "").lower() != "ok":
        raise LayoutError(f"stat {payload.get('stat')!r}")
    if str(payload.get("date") or "") != day.strftime("%Y%m%d"):
        raise LayoutError(f"reported date {payload.get('date')!r} is not {day}")
    tables = payload.get("tables")
    if not isinstance(tables, list):
        raise LayoutError("the answer has no tables")
    if title is not None:
        tables = [t for t in tables if isinstance(t, dict) and t.get("title") == title]
    if len(tables) != 1 or not isinstance(tables[0], dict):
        raise LayoutError(f"{len(tables)} tables, expected 1")
    table = tables[0]
    if _roc_day(table.get("date")) != day:
        raise LayoutError(f"table date {table.get('date')!r} is not {day}")
    return table


def parse_tpex_pb(payload: Any, day: date) -> dict[str, dict[str, Any]]:
    table = _tpex_table(payload, day)
    data = table.get("data")
    count = table.get("totalCount")
    if count is not None and isinstance(data, list) and count != len(data):
        raise LayoutError(f"totalCount {count!r} but {len(data)} rows")
    rows = _rows(table.get("fields"), data, TPEX_PB_LAYOUTS)
    return _by_code(
        rows,
        "股票代號",
        lambda row: {
            "pb_ratio": _number(row["股價淨值比"]),
            "pe_ratio": _number(row["本益比"]),
            "dividend_yield": _number(row["殖利率(%)"]),
            "report_period": _period(row.get("財報年/季"), _TPEX_PERIOD),
        },
    )


def parse_tpex_foreign(payload: Any, day: date) -> dict[str, dict[str, Any]]:
    table = _tpex_table(payload, day)
    data = table.get("data")
    count = table.get("totalCount")
    if not isinstance(data, list) or isinstance(count, bool) or count != len(data):
        raise LayoutError(
            f"totalCount {count!r} but "
            f"{len(data) if isinstance(data, list) else 'no'} rows"
        )
    rows = _rows(table.get("fields"), data, (TPEX_QFII_LAYOUT,))
    return _by_code(
        rows,
        "代號",
        lambda row: {
            "shares_issued": _shares(row["發行股數(A)"]),
            "foreign_shares_held": _count(row["僑外資及陸資持有股數(C)"]),
            "foreign_held_pct": _percent(row["僑外資及陸資持股比率(E=C/A)"]),
            "foreign_available_shares": _count(row["僑外資及陸資尚可投資股數B=A*F-C"]),
            "foreign_limit_pct": _percent(row["法令投資上限比率(F)"]),
            "mainland_limit_pct": None,
            "change_reason": None,
            "last_filing_date": None,
            "note": _note(row["備註"]),
        },
    )


def _note(cell: Any) -> str | None:
    text = "" if cell is None else str(cell).strip()
    return None if text in NULL_CELLS else text


def parse_tpex_quote_shares(payload: Any, day: date) -> dict[str, dict[str, Any]]:
    """發行股數 of a stored TPEx quote table: ``dailyQuotes`` (with its 管理股票 table)
    or the OpenAPI list."""

    if isinstance(payload, list):
        roc = f"{day.year - 1911}{day:%m%d}"
        if not payload:
            raise LayoutError("the table has no rows")
        rows = []
        for row in payload:
            if (
                not isinstance(row, dict)
                or "SecuritiesCompanyCode" not in row
                or "Capitals" not in row
            ):
                raise LayoutError(
                    f"a row without SecuritiesCompanyCode or Capitals: {row!r}"
                )
            if str(row.get("Date") or "").strip() != roc:
                raise LayoutError(f"row date {row.get('Date')!r} is not {day}")
            rows.append(row)
        return _by_code(
            rows,
            "SecuritiesCompanyCode",
            lambda row: {"shares_issued": _shares(row["Capitals"])},
        )
    table = _tpex_table(payload, day, title=TPEX_QUOTE_TITLE)
    if not isinstance(table.get("data"), list) or not table["data"]:
        raise LayoutError("the table has no rows")
    managed = [
        t
        for t in payload["tables"]
        if isinstance(t, dict) and t.get("title") == TPEX_MANAGED_TITLE
    ]
    if len(managed) > 1:
        raise LayoutError(f"{len(managed)} {TPEX_MANAGED_TITLE} tables, expected 1")
    rows = []
    for each in [table, *managed]:
        fields = each.get("fields")
        data = each.get("data")
        if not isinstance(fields, list) or any(
            fields.count(name) != 1 for name in (TPEX_QUOTE_CODE, TPEX_QUOTE_SHARES)
        ):
            raise LayoutError(f"unknown columns {fields!r}")
        if not isinstance(data, list):
            raise LayoutError(f"{each.get('title')} has no rows list")
        code_at = fields.index(TPEX_QUOTE_CODE)
        shares_at = fields.index(TPEX_QUOTE_SHARES)
        for row in data:
            if not isinstance(row, list) or len(row) != len(fields):
                raise LayoutError(f"a row does not match the columns: {row!r}")
            rows.append({"code": row[code_at], "shares": row[shares_at]})
    return _by_code(rows, "code", lambda row: {"shares_issued": _shares(row["shares"])})


PARSERS: dict[str, Callable[[Any, date], dict[str, dict[str, Any]]]] = {
    "twse-pb": parse_twse_pb,
    "twse-shares": parse_twse_shares,
    "tpex-pb": parse_tpex_pb,
    "tpex-shares": parse_tpex_quote_shares,
    "twse-foreign": parse_twse_foreign,
    "tpex-foreign": parse_tpex_foreign,
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


def _day_run(
    db: Session, feed: str, day: date, *, create: bool = True
) -> IngestionRun | None:
    key = REQUEST_KEY.format(feed=feed, day=day.isoformat())
    run = db.scalar(select(IngestionRun).where(IngestionRun.request_key == key))
    if run is None and create:
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
    source: str,
    day: date,
    parsed: dict[str, dict[str, Any]],
    raw: RawPayload,
) -> dict[str, Any]:
    """Make the feed's rows of ``day`` the parsed ones; the counts."""

    barred = _barred(db, feed.exchange, day)
    model = feed.table
    counts = Counter()
    kept: dict[int, Any] = {}
    for row in db.scalars(
        select(model).where(
            model.trading_date == day, model.source.in_(_feed_sources(feed))
        )
    ):
        if row.source == source:
            kept[row.instrument_id] = row
        else:  # the session's other TPEx quote table, read before
            db.delete(row)
            counts["removed"] += 1
    unmatched = sorted(code for code in parsed if code not in barred)
    written: set[int] = set()
    for code, values in parsed.items():
        instrument_id = barred.get(code)
        if instrument_id is None:
            continue
        written.add(instrument_id)
        fields = {
            **values,
            "source": source,
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
    nulls = Counter()
    for code, values in parsed.items():
        if code in barred:
            for name, value in values.items():
                if value is None:
                    nulls[name] += 1
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


def _shares_raw_id(db: Session, day: date) -> int | None:
    """The raw payload id of the ``twse-shares`` manifest row of ``day``."""

    run = _day_run(db, "twse-shares", day, create=False)
    return (run.metadata_json or {}).get("raw_payload_id") if run else None


def _shares_capture(db: Session, day: date) -> RawPayload:
    """The ``MI_QFIIS`` capture ``twse-shares`` stored for ``day``."""

    stored = _shares_raw_id(db, day)
    raw = db.get(RawPayload, stored) if stored is not None else None
    if raw is None or raw.endpoint.split("?")[0] != MI_QFIIS_ENDPOINT:
        raise OfficialDataError(
            f"the twse-shares session {day} cites raw payload {stored}, not MI_QFIIS"
        )
    return raw


def _feed_sources(feed: Feed) -> set[str]:
    if feed.name == "tpex-shares":
        return set(TPEX_SHARES_SOURCES.values())
    return {SOURCES[feed.name]}


# --- stored raw -----------------------------------------------------------------


def read_raw(row: RawPayload, fallback_raw_dir: Path | None = None) -> Any:
    """The JSON of a stored capture, its SHA-256 checked.

    A file not whole where ``payload_path`` points is looked for at the same path
    under ``fallback_raw_dir`` (the production volume's ``raw``, mounted read-only),
    when the path is under this volume's raw directory or is an old Windows path
    (``app.raw_paths.legacy_relative``): the seed rows captured before the Docker
    cutover keep ``C:\\Users\\...\\raw\\...`` (#1075).
    """

    primary = payload_file(row.payload_path)
    candidates = [primary]
    if fallback_raw_dir is not None and row.payload_path:
        # The file payload_file gives, relative to its raw directory (as
        # tools/audit/raw_files.relative_to_raw); an old Windows path by its prefix.
        relative: PurePosixPath | None = legacy_relative(row.payload_path)
        if relative is None:
            try:
                relative = PurePosixPath(primary.relative_to(raw_dir()).as_posix())
            except ValueError:
                relative = None
        if relative is not None:
            candidates.append(Path(fallback_raw_dir).joinpath(*relative.parts))
    for path in candidates:
        try:
            content = path.read_bytes()
        except OSError:
            continue
        if hashlib.sha256(content).hexdigest() != row.sha256:
            continue
        try:
            return json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OfficialDataError(
                f"raw payload {row.id} is not JSON: {path}"
            ) from exc
    raise OfficialDataError(
        f"raw payload {row.id} is missing or not its SHA-256: {row.payload_path}"
    )


def _quote_capture(db: Session, day: date) -> RawPayload:
    """The capture the most TPEx bars of ``day`` cite."""

    cited = db.execute(
        select(MarketBar.raw_payload_id, func.count())
        .join(Instrument, Instrument.id == MarketBar.instrument_id)
        .where(
            Instrument.exchange == "TPEx",
            Instrument.instrument_type.in_(BAR_TYPES),
            MarketBar.trading_date == day,
            MarketBar.raw_payload_id.is_not(None),
        )
        .group_by(MarketBar.raw_payload_id)
        .order_by(func.count().desc(), MarketBar.raw_payload_id.desc())
    ).first()
    if cited is None:
        raise OfficialDataError(f"no TPEx bar of {day} cites a capture")
    raw = db.get(RawPayload, cited[0])
    if raw is None or raw.endpoint.split("?")[0] not in TPEX_SHARES_SOURCES:
        raise OfficialDataError(
            f"the TPEx bars of {day} cite raw payload {cited[0]}, not a quote table"
        )
    return raw


# --- the run --------------------------------------------------------------------


def in_quiet_hours(moment: datetime) -> bool:
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    now = aware.astimezone(TAIPEI).time()
    return QUIET_START <= now < QUIET_END


def seconds_to_quiet_end(moment: datetime) -> float:
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    local = aware.astimezone(TAIPEI)
    end = local.replace(
        hour=QUIET_END.hour, minute=QUIET_END.minute, second=0, microsecond=0
    )
    return max(0.0, (end - local).total_seconds())


def _empty_counts(feed: Feed) -> dict[str, Any]:
    return {
        "sessions": 0,
        "not_published": 0,
        "done_before": 0,
        "requested": 0,
        "reapplied": 0,
        "not_answered": 0,
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
    fallback_raw_dir: Path | None = None,
    fetch: Callable[[str, date], Any] = fetch_official,
    now: Callable[[], datetime] = utcnow,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if end < start:
        raise ValueError("--end is before --start")
    names = feeds or list(FEEDS)
    unknown = [name for name in names if name not in FEEDS]
    if unknown:
        raise ValueError(f"unknown feeds {unknown}; known: {list(FEEDS)}")
    for table in TABLES:
        if not inspect(db.get_bind()).has_table(table):
            raise ValueError(f"{table} is missing: run init-db first")
    started = time.monotonic()
    result = {name: _empty_counts(FEEDS[name]) for name in names}
    plan: dict[date, list[str]] = {}
    sessions = {
        exchange: _sessions(db, exchange, start, end)
        for exchange in {FEEDS[name].exchange for name in names}
    }
    # FEEDS order within a session: twse-foreign reads what twse-shares stores.
    for name in sorted(names, key=list(FEEDS).index):
        feed = FEEDS[name]
        for day in sessions[feed.exchange]:
            result[name]["sessions"] += 1
            if day < feed.first_date:
                result[name]["not_published"] += 1
                continue
            plan.setdefault(day, []).append(name)
    requests = 0
    # Failed requests in a row, per host: one host blocking while the other
    # answers must still stop the run (review of PR #1108).
    failures_in_a_row: Counter[str] = Counter()
    aborted = None
    for day in sorted(plan):
        for name in plan[day]:
            feed = FEEDS[name]
            counts = result[name]
            # A twse-shares session without a capture: nothing to read yet.
            if name == "twse-foreign" and _shares_raw_id(db, day) is None:
                counts["not_answered"] += 1
                continue
            # reapply asks nothing, so a session never asked gets no manifest row.
            run = _day_run(db, name, day, create=not (reapply and feed.requests))
            if run is None:
                counts["not_answered"] += 1
                continue
            done = run.status == "success"
            if done and not reapply:
                counts["done_before"] += 1
                continue
            stored = (run.metadata_json or {}).get("raw_payload_id")
            if reapply and feed.requests and not done and stored is None:
                # reapply sends no request: a session never answered waits for a run.
                counts["not_answered"] += 1
                continue
            raw: RawPayload | None = None
            try:
                if feed.requests and not reapply:
                    if in_quiet_hours(now()):
                        sleep(seconds_to_quiet_end(now()))
                    _method, endpoint, _form = request_of(name, day)
                    host = urlsplit(endpoint).hostname or ""
                    requests += 1
                    counts["requested"] += 1
                    try:
                        payload = fetch(name, day)
                    except Exception as exc:  # the source's failure, never a crash
                        failures_in_a_row[host] += 1
                        raise OfficialDataError(f"request failed: {exc}") from exc
                    failures_in_a_row[host] = 0
                    captured = sources.capture_payload(
                        feed.raw_source, endpoint, payload, day.isoformat()
                    )
                    raw = pipeline._upsert_raw_payload(db, run, captured)
                    source = SOURCES[name]
                else:
                    counts["reapplied"] += 1
                    if feed.requests:
                        raw = db.get(RawPayload, stored)
                        if raw is None:
                            raise OfficialDataError(
                                "the stored session has no raw payload"
                            )
                        source = SOURCES[name]
                    elif name == "twse-foreign":
                        raw = _shares_capture(db, day)
                        source = SOURCES[name]
                    else:
                        raw = _quote_capture(db, day)
                        source = TPEX_SHARES_SOURCES[raw.endpoint.split("?")[0]]
                    payload = read_raw(raw, fallback_raw_dir)
                parsed = PARSERS[name](payload, day)
                written = write_rows(db, feed, source, day, parsed, raw)
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
                blocked = [
                    host
                    for host, count in failures_in_a_row.items()
                    if count >= ABORT_AFTER_FAILURES
                ]
                if blocked:
                    aborted = f"{ABORT_AFTER_FAILURES} failed requests in a row to {blocked[0]}"
                    break
                continue
            run.status = "success"
            run.error = None
            run.records = written["written"]
            run.finished_at = utcnow()
            run.metadata_json = {
                "raw_payload_id": raw.id,
                "source": source,
                **{k: v for k, v in written.items() if k != "unmatched_codes"},
                "unmatched_codes": written["unmatched_codes"],
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


def run_valuation_backfill(
    start: str,
    end: str,
    *,
    feeds: list[str] | None = None,
    reapply: bool = False,
    fallback_raw_dir: str | None = None,
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
                return backfill(
                    db,
                    first,
                    last,
                    feeds=feeds,
                    reapply=reapply,
                    fallback_raw_dir=Path(fallback_raw_dir)
                    if fallback_raw_dir
                    else None,
                )
            except ValueError as exc:
                db.rollback()
                return {"status": "failed", "error": str(exc)}
    finally:
        sources.set_minimum_host_interval(previous)
