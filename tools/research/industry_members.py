"""Official industry members, month by month, for research (Issue #779).

The MOPS monthly revenue pages (``t21sc03``) are regenerated from today's
company list: no delisted company is on them, and every company carries its
current industry (#779 AC-1).  The exchanges' own per-industry close quotes
are snapshots of the day: TWSE ``MI_INDEX`` by ``type`` and TPEx's legacy
``stk_wn1430_result.php`` by ``se`` list every stock listed in that industry
that day, suspended or not, later delisted or not, under the industry it had
then (probe of 2015-01-05 in #779 6894326371).

Two steps, both run in a detached container:

* ``fetch``: for each month from ``--start`` to ``--end``, the last trading
  day D (the last weekday whose TWSE ``type=01`` answers rows), then every
  industry code the period lists (``CODE_PERIODS``) on D for both markets.
  Each answer's bytes go to ``<out>/raw/<exchange>/<YYYYMMDD>/<code>.json``
  and one line to ``<out>/requests.jsonl``; a rerun skips what is stored.
  Requests to one host are ``MIN_INTERVAL_SECONDS`` apart; the two hosts run
  in parallel.  None is sent from 20:30 to 23:30 or 08:00 to 09:00 Taipei
  (``BLACKOUTS``: the production daily's collect and the morning jobs).  The
  first refusal (a block page, HTTP 403/429, a refused connection) or three
  failed answers in a row on one host (not 200, empty, not JSON, a maintenance
  page) stop the run with exit 2; nothing is retried by itself.  A failed
  answer's body goes to ``<out>/failed/``.
* ``build``: reads only the raw, and writes ``industry_members_v1.json`` (byte
  for byte the same from the same raw) and its manifest.  Every answer is
  checked: the date it reports, the code's category name (``CATEGORY_NAMES``),
  the column header; a code the period lists that answers no row, a month
  without its snapshot, or a code whose months with rows have a gap fails the
  build.

A member row is (snapshot date, exchange, industry code, category name as
published, group label, group id, symbol, name, retroactive_category).  TWSE
answers today's category on past days too; ``retroactive_category`` marks the
TWSE 35-38 rows before 2023-07-03, codes the exchange did not have then.  The research tools take the
latest snapshot with ``snapshot_date <= T``: the close quotes of D are public
on D's evening (docs/ops/RESEARCH_DB.md).  The group label is the product's
English label (``app.taxonomy``) and the id ``canonical_group_id("industry",
label)``, both written out here (the product is not imported, so a product
change cannot change this table silently; backend/tests compares them).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import time as time_module
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

TAIPEI = timezone(timedelta(hours=8))
TABLE_NAME = "industry_members_v1.json"
MANIFEST_NAME = "industry_members_v1.manifest.json"
REQUESTS_NAME = "requests.jsonl"
RAW_DIR = "raw"
# Bodies of failed answers, kept to read why (never parsed as raw).
FAILED_DIR = "failed"
FORMAT_VERSION = 1
TWSE = "TWSE"
TPEX = "TPEx"
EXCHANGES = (TWSE, TPEX)
HOSTS = {TWSE: "www.twse.com.tw", TPEX: "www.tpex.org.tw"}
TWSE_URL = (
    "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
    "?date={yyyymmdd}&type={code}&response=json"
)
TPEX_URL = (
    "https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/"
    "stk_wn1430_result.php?l=zh-tw&d={roc}&se={code}"
)
USER_AGENT = "taiwan-stock-research/0.1"
# Decided in #779 6894468607: at least five seconds per host, #702's backfill
# also asks both hosts.
MIN_INTERVAL_SECONDS = 5.0
TIMEOUT_SECONDS = 60.0
FAILURES_TO_STOP = 3
BLACKOUTS = ((time(20, 30), time(23, 30)), (time(8, 0), time(9, 0)))
# The TWSE code that answers the day's rows on every trading day: it decides D.
DAY_PROBE_CODE = "01"
DAY_PROBE_CATEGORY = "水泥工業"
# Pages that are not an answer.  The source refusing us (``BLOCKED_MARKERS``,
# HTTP ``BLOCKED_STATUSES``, a refused connection) stops the run at once (#779
# decision 6905102853: #702 and #790 ask the same hosts); a maintenance page
# (TWSE 2016-12-30, #779 6905069704) is one failed answer like the others.
BLOCKED_MARKERS = (
    "FOR SECURITY REASONS",
    "查詢過於頻繁",
    "THE PAGE CANNOT BE ACCESSED",
)
MAINTENANCE_MARKERS = ("網站維護中",)
BLOCK_MARKERS = BLOCKED_MARKERS + MAINTENANCE_MARKERS
BLOCKED_STATUSES = (403, 429)
TWSE_NO_DATA = "沒有符合條件的資料"
STOP_EXIT = 2
FAILED_EXIT = 1

# Industry code -> the product's English label (app.taxonomy, TWSE B.12.00
# Appendix 3 and TPEx V12.14 Appendix 3).  TPEx 34 電子商務 ended 2023-07-03
# and has no product label.
GROUP_LABELS: dict[str, dict[str, str]] = {
    TWSE: {
        "01": "Cement",
        "02": "Food",
        "03": "Plastic",
        "04": "Textile",
        "05": "Electrical Machinery",
        "06": "Electrical Cable",
        "08": "Glass",
        "09": "Paper",
        "10": "Iron and Steel",
        "11": "Rubber",
        "12": "Automobile",
        "14": "Construction",
        "15": "Shipping",
        "16": "Tourism",
        "17": "Financial",
        "18": "Wholesale and Retail",
        "19": "Composite",
        "20": "Other",
        "21": "Chemical",
        "22": "Biotechnology",
        "23": "Oil, Gas and Electricity",
        "24": "Semiconductor",
        "25": "Computer and Peripherals",
        "26": "Optoelectronics",
        "27": "Communications",
        "28": "Electronic Parts",
        "29": "Electronic Distribution",
        "30": "Information Service",
        "31": "Other Electronics",
        "35": "Green Energy",
        "36": "Digital Cloud",
        "37": "Sports and Leisure",
        "38": "Household",
    },
    TPEX: {
        "02": "Food",
        "03": "Plastic",
        "04": "Textile",
        "05": "Electrical Machinery",
        "06": "Electrical Cable",
        "08": "Glass",
        "10": "Iron and Steel",
        "11": "Rubber",
        "14": "Construction",
        "15": "Shipping",
        "16": "Tourism",
        "17": "Financial",
        "18": "Wholesale and Retail",
        "20": "Other",
        "21": "Chemical",
        "22": "Biotechnology",
        "23": "Oil, Gas and Electricity",
        "24": "Semiconductor",
        "25": "Computer and Peripherals",
        "26": "Optoelectronics",
        "27": "Communications",
        "28": "Electronic Parts",
        "29": "Electronic Distribution",
        "30": "Information Service",
        "31": "Other Electronics",
        "32": "Cultural Innovation",
        "33": "Agriculture Technology",
        "34": "E-commerce",
        "35": "Green Energy",
        "36": "Digital Cloud",
        "37": "Sports and Leisure",
        "38": "Household",
    },
}

# The category name each code answers with (TWSE: the table title's
# parentheses; TPEx: ``category``), from the sweep of 2013-01-31, 2023-06-30 and
# 2024-09-30 (#779 6904909658); a name not here fails the build.  TPEx 33 and
# 34 answer rows with an empty ``category``: ``""`` lets only them through
# (decision 6904973827), any other code answering it still fails.
CATEGORY_NAMES: dict[str, dict[str, frozenset[str]]] = {
    TWSE: {
        "01": frozenset({"水泥工業"}),
        "02": frozenset({"食品工業"}),
        "03": frozenset({"塑膠工業"}),
        "04": frozenset({"紡織纖維"}),
        "05": frozenset({"電機機械"}),
        "06": frozenset({"電器電纜"}),
        "08": frozenset({"玻璃陶瓷"}),
        "09": frozenset({"造紙工業"}),
        "10": frozenset({"鋼鐵工業"}),
        "11": frozenset({"橡膠工業"}),
        "12": frozenset({"汽車工業"}),
        "14": frozenset({"建材營造"}),
        "15": frozenset({"航運業"}),
        "16": frozenset({"觀光餐旅"}),
        "17": frozenset({"金融保險"}),
        "18": frozenset({"貿易百貨"}),
        "19": frozenset({"綜合"}),
        "20": frozenset({"其他"}),
        "21": frozenset({"化學工業"}),
        "22": frozenset({"生技醫療業"}),
        "23": frozenset({"油電燃氣業"}),
        "24": frozenset({"半導體業"}),
        "25": frozenset({"電腦及週邊設備業"}),
        "26": frozenset({"光電業"}),
        "27": frozenset({"通信網路業"}),
        "28": frozenset({"電子零組件業"}),
        "29": frozenset({"電子通路業"}),
        "30": frozenset({"資訊服務業"}),
        "31": frozenset({"其他電子業"}),
        "35": frozenset({"綠能環保"}),
        "36": frozenset({"數位雲端"}),
        "37": frozenset({"運動休閒"}),
        "38": frozenset({"居家生活"}),
    },
    TPEX: {
        "02": frozenset({"食品工業"}),
        "03": frozenset({"塑膠工業"}),
        "04": frozenset({"紡織纖維"}),
        "05": frozenset({"電機機械"}),
        "06": frozenset({"電器電纜"}),
        "08": frozenset({"玻璃陶瓷"}),
        "10": frozenset({"鋼鐵工業"}),
        "11": frozenset({"橡膠工業"}),
        "14": frozenset({"建材營造"}),
        "15": frozenset({"航運業"}),
        "16": frozenset({"觀光餐旅"}),
        "17": frozenset({"金融業"}),
        "18": frozenset({"貿易百貨"}),
        "20": frozenset({"其他"}),
        "21": frozenset({"化學工業"}),
        "22": frozenset({"生技醫療類"}),
        "23": frozenset({"油電燃氣類"}),
        "24": frozenset({"半導體類"}),
        "25": frozenset({"電腦及週邊類"}),
        "26": frozenset({"光電業類"}),
        "27": frozenset({"通信網路類"}),
        "28": frozenset({"電子零組件類"}),
        "29": frozenset({"電子通路類"}),
        "30": frozenset({"資訊服務類"}),
        "31": frozenset({"其他電子類"}),
        "32": frozenset({"文化創意業"}),
        "33": frozenset({""}),
        "34": frozenset({""}),
        "35": frozenset({"綠能環保"}),
        "36": frozenset({"數位雲端"}),
        "37": frozenset({"運動休閒"}),
        "38": frozenset({"居家生活"}),
    },
}

# TWSE MI_INDEX answers each stock under its current (or last) category on
# every past day too (#779 6904648128: 0 of 736 stocks changed between
# 2013-01-31 and 2023-06-30, and these four codes, new on 2023-07-03, already
# have members on 2013-01-31).  Their rows before that day are flagged
# ``retroactive_category`` (decision 6904679034).
RETROACTIVE_CODES: dict[str, frozenset[str]] = {
    TWSE: frozenset({"35", "36", "37", "38"}),
}
RETROACTIVE_BEFORE = "2023-07-03"

# (first month, last month, exchange, codes): the codes each month asks for.
# Filled from the per-year category lists confirmed before the full fetch.
#
# From the sweep of 2013-01-31, 2023-06-30, 2024-09-30, the bisections and the
# yearly check (#779 6904909658, 6904942765, 6905069704; confirmed 6905102853).
# A bisection assumes a code, once it has rows, keeps them until it ends for
# good.  TPEx 18 and 34 ending and 35-38 starting are put at 2023-07-03, the
# day TPEx changed its codes.  The build fails when a listed code has no rows
# (18 or 34 in 2023-06, 35-38 in 2023-07); a code not listed that still has
# rows is not asked, and only completeness ``missing`` can show its stocks.
# Not asked: TWSE 19 and TPEx 08 (no row on any day checked).
_TWSE_CODES = tuple(
    f"{number:02d}"
    for number in (*range(1, 7), *range(8, 13), *range(14, 19), *range(20, 32))
) + ("35", "36", "37", "38")
_TPEX_2013 = tuple(
    f"{number:02d}" for number in (*range(2, 7), 10, 11, *range(14, 19), *range(20, 32))
)


def _tpex(*, add: tuple[str, ...] = (), drop: tuple[str, ...] = ()) -> tuple[str, ...]:
    return tuple(sorted((set(_TPEX_2013) | set(add)) - set(drop)))


CODE_PERIODS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("2013-01", "2024-09", TWSE, _TWSE_CODES),
    ("2013-01", "2013-12", TPEX, _tpex()),
    ("2014-01", "2016-08", TPEX, _tpex(add=("32",))),
    ("2016-09", "2018-02", TPEX, _tpex(add=("32", "33"))),
    ("2018-03", "2022-06", TPEX, _tpex(add=("32", "33", "34"))),
    ("2022-07", "2023-06", TPEX, _tpex(add=("32", "33", "34"), drop=("11",))),
    (
        "2023-07",
        "2024-09",
        TPEX,
        _tpex(add=("32", "33", "35", "36", "37", "38"), drop=("11", "18")),
    ),
)


# --- definitions --------------------------------------------------------------


def group_id(label: str) -> str:
    """``app.taxonomy.canonical_group_id("industry", label)``, written out."""

    digest = hashlib.sha1(f"industry:{label.lower()}".encode("utf-8")).hexdigest()
    return f"official-industry-{digest[:16]}"


def definitions() -> dict:
    return {
        "format_version": FORMAT_VERSION,
        "group_labels": GROUP_LABELS,
        "category_names": {
            exchange: {code: sorted(names) for code, names in sorted(table.items())}
            for exchange, table in sorted(CATEGORY_NAMES.items())
        },
        "code_periods": [list(period) for period in CODE_PERIODS],
        "rules": [
            "snapshot: last TWSE trading day of the month (type 01 answers rows)",
            "members: every row of the code's table on the snapshot day",
            "available: snapshot_date <= T",
            "retroactive_category: a RETROACTIVE_CODES row before RETROACTIVE_BEFORE",
        ],
        "retroactive_codes": {
            exchange: sorted(codes)
            for exchange, codes in sorted(RETROACTIVE_CODES.items())
        },
        "retroactive_before": RETROACTIVE_BEFORE,
    }


def definitions_sha256() -> str:
    text = json.dumps(definitions(), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- months and codes ---------------------------------------------------------


def parse_month(text: str) -> tuple[int, int]:
    year, month = text.split("-")
    if len(year) != 4 or len(month) != 2 or not 1 <= int(month) <= 12:
        raise ValueError(f"month {text!r} is not YYYY-MM")
    return int(year), int(month)


def months(first: str, last: str) -> list[str]:
    year, month = parse_month(first)
    end = parse_month(last)
    if (year, month) > end:
        raise ValueError(f"{first} is after {last}")
    result = []
    while (year, month) <= end:
        result.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def codes_for(
    month: str,
    exchange: str,
    periods: Iterable[tuple[str, str, str, tuple[str, ...]]] | None = None,
) -> tuple[str, ...]:
    """The codes ``month`` asks ``exchange`` for; exactly one period must cover it."""

    found = [
        codes
        for first, last, name, codes in (CODE_PERIODS if periods is None else periods)
        if name == exchange and first <= month <= last
    ]
    if len(found) != 1:
        raise ValueError(f"{len(found)} code periods cover {exchange} {month}")
    return found[0]


def weekdays_back(month: str) -> list[date]:
    """The month's weekdays, the last one first."""

    year, number = parse_month(month)
    day = date(year, number, monthrange(year, number)[1])
    result = []
    while day.month == number:
        if day.weekday() < 5:
            result.append(day)
        day -= timedelta(days=1)
    return result


def roc_slash(day: date) -> str:
    return f"{day.year - 1911}/{day.month:02d}/{day.day:02d}"


def url_for(exchange: str, day: date, code: str) -> str:
    if exchange == TWSE:
        return TWSE_URL.format(yyyymmdd=day.strftime("%Y%m%d"), code=code)
    return TPEX_URL.format(roc=roc_slash(day), code=code)


def raw_path(out: Path, exchange: str, day: date, code: str) -> Path:
    return out / RAW_DIR / exchange / day.strftime("%Y%m%d") / f"{code}.json"


def failed_path(out: Path, exchange: str, day: date, code: str) -> Path:
    """A new file for one failed answer's body; earlier ones are kept."""

    folder = out / FAILED_DIR / exchange / day.strftime("%Y%m%d")
    number = 1
    while (folder / f"{code}.{number}.body").exists():
        number += 1
    return folder / f"{code}.{number}.body"


# --- answers ------------------------------------------------------------------


class AnswerError(ValueError):
    """An answer that cannot be read as the page asked for."""


class Blocked(AnswerError):
    """The source refused the request: the run stops at the first one."""


@dataclass(frozen=True)
class Answer:
    """One code's table on one day.  ``no_data``: the day has no quotes."""

    category: str | None
    rows: tuple[tuple[str, str], ...]
    no_data: bool = False


def _json(content: bytes, label: str) -> dict:
    if not content.strip():
        raise AnswerError(f"{label} is empty")
    text = content.decode("utf-8", errors="replace")
    upper = text.upper()
    if any(marker.upper() in upper for marker in BLOCKED_MARKERS):
        raise Blocked(f"{label} was refused by the source")
    if any(marker.upper() in upper for marker in MAINTENANCE_MARKERS):
        raise AnswerError(f"{label} is a maintenance page")
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise AnswerError(f"{label} is not JSON") from exc
    if not isinstance(payload, dict):
        raise AnswerError(f"{label} is not a JSON object")
    return payload


def _rows(data: object, label: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(data, list):
        raise AnswerError(f"{label} has no data list")
    rows = []
    seen = set()
    for item in data:
        if not isinstance(item, list) or len(item) < 2:
            raise AnswerError(f"{label} has a malformed row")
        symbol, name = str(item[0]).strip(), str(item[1]).strip()
        if not symbol or symbol in seen:
            raise AnswerError(f"{label} lists {symbol!r} twice or empty")
        seen.add(symbol)
        rows.append((symbol, name))
    return tuple(rows)


def parse_twse(content: bytes, day: date, code: str) -> Answer:
    """``MI_INDEX`` with ``type=<code>``: the table 「…每日收盤行情(<category>)」."""

    label = f"TWSE MI_INDEX {day.isoformat()} type={code}"
    payload = _json(content, label)
    stat = str(payload.get("stat", ""))
    if stat != "OK":
        if TWSE_NO_DATA in stat:
            return Answer(None, (), no_data=True)
        raise AnswerError(f"{label} answered stat {stat!r}")
    if payload.get("date") != day.strftime("%Y%m%d"):
        raise AnswerError(f"{label} reports date {payload.get('date')!r}")
    prefix = f"{day.year - 1911}年{day.month:02d}月{day.day:02d}日 每日收盤行情("
    tables = [
        table
        for table in payload.get("tables") or []
        if isinstance(table, dict) and "每日收盤行情" in str(table.get("title") or "")
    ]
    if not tables:
        return Answer(None, ())
    if len(tables) != 1:
        raise AnswerError(f"{label} has {len(tables)} quote tables")
    table = tables[0]
    title = str(table["title"]).strip()
    if not (title.startswith(prefix) and title.endswith(")")):
        raise AnswerError(f"{label} has the title {title!r}")
    fields = table.get("fields") or []
    if list(fields[:2]) != ["證券代號", "證券名稱"]:
        raise AnswerError(f"{label} columns changed: {fields[:2]!r}")
    return Answer(title[len(prefix) : -1], _rows(table.get("data"), label))


def parse_tpex(content: bytes, day: date, code: str) -> Answer:
    """Legacy ``stk_wn1430_result.php`` with ``se=<code>``: one table."""

    label = f"TPEx stk_wn1430 {day.isoformat()} se={code}"
    payload = _json(content, label)
    tables = payload.get("tables")
    if not isinstance(tables, list) or len(tables) != 1:
        raise AnswerError(f"{label} has no single table")
    table = tables[0]
    reported = str(table.get("date") or "")
    data = table.get("data") or []
    if not data:
        return Answer(str(table.get("category") or "").strip() or None, ())
    if reported != roc_slash(day):
        raise AnswerError(f"{label} reports date {reported!r}")
    fields = [str(field).strip() for field in table.get("fields") or []]
    if fields[:2] != ["代號", "名稱"]:
        raise AnswerError(f"{label} columns changed: {fields[:2]!r}")
    category = str(table.get("category") or "").strip()
    if not category and "" not in CATEGORY_NAMES.get(TPEX, {}).get(code, ()):
        raise AnswerError(f"{label} has no category")
    rows = _rows(data, label)
    if table.get("totalCount") not in (None, len(rows)):
        raise AnswerError(f"{label} totalCount {table.get('totalCount')} != rows")
    return Answer(category or None, rows)


PARSERS: dict[str, Callable[[bytes, date, str], Answer]] = {
    TWSE: parse_twse,
    TPEX: parse_tpex,
}


# --- fetch --------------------------------------------------------------------


def blackout_seconds(now: datetime) -> float:
    """Seconds until requests may be sent again (0 outside ``BLACKOUTS``)."""

    local = now.astimezone(TAIPEI)
    for start, end in BLACKOUTS:
        if start <= local.time() < end:
            resume = datetime.combine(local.date(), end, TAIPEI)
            return (resume - local).total_seconds()
    return 0.0


class Stop(RuntimeError):
    """A host was blocked or failed ``FAILURES_TO_STOP`` answers in a row.

    ``followed``: this host stopped only because the other one did.
    """

    def __init__(self, message: str, *, followed: bool = False) -> None:
        super().__init__(message)
        self.followed = followed


@dataclass
class Fetched:
    status: int
    content: bytes


def http_get(url: str) -> Fetched:  # pragma: no cover - network
    import httpx

    try:
        response = httpx.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS
        )
    except httpx.ConnectError as exc:
        raise Blocked(f"{url}: connection refused ({exc})") from exc
    return Fetched(response.status_code, response.content)


class Host:
    """One host's pace, blackout and failure count; ``ask`` sends one request."""

    def __init__(
        self,
        exchange: str,
        out: Path,
        get: Callable[[str], Fetched],
        now: Callable[[], datetime],
        sleep: Callable[[float], None],
        log: Callable[[dict], None],
        stopped: threading.Event,
        pace: dict[str, float],
    ) -> None:
        self.exchange = exchange
        self.out = out
        self.get = get
        self.now = now
        self.sleep = sleep
        self.log = log
        self.stopped = stopped
        self.failures = 0
        self.failed = 0
        self.sent = 0
        # The last request's ``time.monotonic`` per exchange, shared by the runs
        # of one process (``bisect`` makes several), so none starts early.
        self.pace = pace

    def _wait(self) -> None:
        while True:
            wait = blackout_seconds(self.now())
            if wait <= 0:
                break
            self.log({"event": "blackout", "exchange": self.exchange, "wait": wait})
            self.sleep(wait)
        last = self.pace.get(self.exchange)
        if last is not None:
            elapsed = time_module.monotonic() - last
            if elapsed < MIN_INTERVAL_SECONDS:
                self.sleep(MIN_INTERVAL_SECONDS - elapsed)

    def answer(
        self, day: date, code: str, *, require_rows: bool = False
    ) -> Answer | None:
        """The stored or fetched answer; None when this request failed.

        ``require_rows``: an answer without rows is a failed one (``fetch``
        asks only codes the period lists; ``sweep`` and ``bisect`` need the
        empty answers).
        """

        path = raw_path(self.out, self.exchange, day, code)
        parse = PARSERS[self.exchange]
        if path.is_file():
            return parse(path.read_bytes(), day, code)
        if self.stopped.is_set():
            raise Stop(f"{self.exchange}: stopped", followed=True)
        self._wait()
        url = url_for(self.exchange, day, code)
        entry: dict = {
            "event": "request",
            "exchange": self.exchange,
            "date": day.isoformat(),
            "code": code,
            "url": url,
            "at": self.now().astimezone(timezone.utc).isoformat(),
        }
        self.pace[self.exchange] = time_module.monotonic()
        self.sent += 1
        fetched = None
        try:
            fetched = self.get(url)
            entry.update(status=fetched.status, bytes=len(fetched.content))
            if fetched.status in BLOCKED_STATUSES:
                raise Blocked(f"{url} answered {fetched.status}")
            if fetched.status != 200:
                raise AnswerError(f"{url} answered {fetched.status}")
            result = parse(fetched.content, day, code)
            if require_rows and not result.rows:
                raise AnswerError(
                    f"{self.exchange} {day.isoformat()} {code} is listed but "
                    "answered no rows"
                )
        except Exception as exc:  # any failure counts; nothing is retried here
            self.failures += 1
            self.failed += 1
            entry.update(outcome="failed", error=str(exc)[:300])
            if fetched is not None and fetched.content:
                body = failed_path(self.out, self.exchange, day, code)
                body.parent.mkdir(parents=True, exist_ok=True)
                body.write_bytes(fetched.content)
                entry.update(
                    body=body.relative_to(self.out).as_posix(),
                    sha256=hashlib.sha256(fetched.content).hexdigest(),
                )
            self.log(entry)
            if isinstance(exc, Blocked):
                self.stopped.set()
                raise Stop(f"{self.exchange}: blocked: {exc}") from exc
            if self.failures >= FAILURES_TO_STOP:
                self.stopped.set()
                raise Stop(
                    f"{self.exchange}: {self.failures} failed answers in a row"
                ) from exc
            return None
        self.failures = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".part")
        partial.write_bytes(fetched.content)
        os.replace(partial, path)
        entry.update(
            outcome="no_data" if result.no_data else "stored",
            sha256=hashlib.sha256(fetched.content).hexdigest(),
            rows=len(result.rows),
        )
        self.log(entry)
        return result


def closed(answer: Answer) -> bool:
    """A ``DAY_PROBE_CODE`` answer of a day without trading.

    TWSE says 「沒有符合條件的資料」 on most such weekdays, but on some (2014-02-28,
    a holiday) answers ``stat`` OK with the day's cement table and no row.
    """

    return answer.no_data or (not answer.rows and answer.category == DAY_PROBE_CATEGORY)


def snapshot_day(host: Host, month: str) -> date | None:
    """The month's last weekday on which TWSE ``DAY_PROBE_CODE`` has rows."""

    for day in weekdays_back(month):
        result = host.answer(day, DAY_PROBE_CODE)
        if result is None:
            return None
        if result.rows:
            return day
        if not closed(result):
            raise AnswerError(
                f"TWSE {day.isoformat()} type={DAY_PROBE_CODE} has no rows but "
                "does not say no data"
            )
    raise AnswerError(f"{month} has no TWSE trading day")


PACE: dict[str, float] = {}


def run_plan(
    month_list: list[str],
    codes_of: Callable[[str, str], tuple[str, ...]],
    out: Path,
    *,
    get: Callable[[str], Fetched] = http_get,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    sleep: Callable[[float], None] = time_module.sleep,
    max_requests: int | None = None,
    pace: dict[str, float] | None = None,
    require_rows: bool = False,
) -> dict:
    """Each month's snapshot day, then ``codes_of(month, exchange)`` on it.

    What is stored already is read, not fetched.  The counts, the snapshot
    days and whether a host stopped the run.
    """

    out.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    log_path = out / REQUESTS_NAME

    def log(entry: dict) -> None:
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        with lock, log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(line, flush=True)

    stopped = threading.Event()
    shared = PACE if pace is None else pace
    hosts = {
        exchange: Host(exchange, out, get, now, sleep, log, stopped, shared)
        for exchange in EXCHANGES
    }
    for month in month_list:
        for exchange in EXCHANGES:
            codes_of(month, exchange)  # refuse an uncovered month before any request
    # ``stopped``: why the run stopped; ``followed``: the hosts that stopped
    # only because of it, whichever thread got the lock first.
    summary: dict = {
        "months": len(month_list),
        "failed": 0,
        "stopped": None,
        "followed": [],
    }
    days: dict[str, date] = {}
    try:
        for month in month_list:
            day = snapshot_day(hosts[TWSE], month)
            if day is None:
                continue
            days[month] = day
    except Stop as exc:
        summary["stopped"] = str(exc)
    errors: list[str] = []

    def work(exchange: str) -> None:
        host = hosts[exchange]
        try:
            for month, day in days.items():
                for code in codes_of(month, exchange):
                    if max_requests is not None and host.sent >= max_requests:
                        return
                    host.answer(day, code, require_rows=require_rows)
        except Stop as exc:
            with lock:
                if exc.followed:
                    summary["followed"].append(str(exc))
                else:
                    summary["stopped"] = summary["stopped"] or str(exc)
        except Exception as exc:
            with lock:
                errors.append(f"{exchange}: {exc}")
            stopped.set()

    if summary["stopped"] is None:
        threads = [
            threading.Thread(target=work, args=(exchange,)) for exchange in EXCHANGES
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    if summary["stopped"] is None and summary["followed"]:
        # The other host raised an error, not a ``Stop``: still a stopped run.
        summary["stopped"] = summary["followed"][0]
    summary["errors"] = errors
    summary["sent"] = {exchange: hosts[exchange].sent for exchange in EXCHANGES}
    # Every failed request, including the one that stopped a host.
    summary["failed"] = sum(hosts[exchange].failed for exchange in EXCHANGES)
    summary["snapshot_days"] = len(days)
    summary["days"] = {month: day.isoformat() for month, day in days.items()}
    log({"event": "summary", **summary})
    return summary


def fetch(first: str, last: str, out: Path, **options) -> dict:
    """Every month's codes (``CODE_PERIODS``) from ``first`` to ``last``."""

    return run_plan(
        months(first, last), codes_for, out, **{"require_rows": True, **options}
    )


def all_codes(month: str, exchange: str) -> tuple[str, ...]:
    """Every code ``GROUP_LABELS`` knows: what ``sweep`` asks for."""

    return tuple(GROUP_LABELS[exchange])


def sweep(
    month_list: list[str],
    out: Path,
    only: Iterable[tuple[str, str]] = (),
    **options,
) -> dict:
    """Every known code on each month's snapshot day (the code-list check).

    ``only``: (exchange, code) pairs to ask instead of every code.
    """

    wanted = set(only)
    for exchange, code in wanted:
        if code not in GROUP_LABELS.get(exchange, {}):
            raise ValueError(f"{exchange} {code} is not a known code")

    def codes_of(month: str, exchange: str) -> tuple[str, ...]:
        codes = all_codes(month, exchange)
        if not wanted:
            return codes
        return tuple(code for code in codes if (exchange, code) in wanted)

    return run_plan(month_list, codes_of, out, **options)


def stored_answer(out: Path, exchange: str, day: date, code: str) -> Answer | None:
    path = raw_path(out, exchange, day, code)
    if not path.is_file():
        return None
    return PARSERS[exchange](path.read_bytes(), day, code)


def bisect(
    exchange: str, code: str, present: str, absent: str, out: Path, **options
) -> dict:
    """The boundary month of a code that has rows on one side only.

    ``present`` has rows and ``absent`` none (either order).  The search
    assumes the code has rows on one side of a single boundary and none on the
    other (#779 6894583678).  Each step asks for the month's snapshot day and
    the code; the stored answers are reused by ``fetch``.
    """

    month_list = months(min(present, absent), max(present, absent))
    ends = present < absent  # rows first, then none: the code ends

    def has_rows(month: str) -> bool | None:
        summary = run_plan(
            [month],
            lambda _, name: (code,) if name == exchange else (),
            out,
            **options,
        )
        if summary["stopped"] or month not in summary["days"]:
            return None
        day = date.fromisoformat(summary["days"][month])
        answer = stored_answer(out, exchange, day, code)
        return None if answer is None else bool(answer.rows)

    for month, expected in ((present, True), (absent, False)):
        state = has_rows(month)
        if state is None:
            return {"stopped": True, "month": month}
        if state is not expected:
            raise AnswerError(f"{exchange} {code} {month}: rows={state}")
    # Invariant: month_list[low] is on the left side, month_list[high] the right.
    low, high = 0, len(month_list) - 1
    steps = []
    while high - low > 1:
        middle = (low + high) // 2
        state = has_rows(month_list[middle])
        if state is None:
            return {"stopped": True, "month": month_list[middle], "steps": steps}
        steps.append([month_list[middle], state])
        if state == ends:
            low = middle
        else:
            high = middle
    result = {"exchange": exchange, "code": code, "stopped": False, "steps": steps}
    if ends:
        result["last_with_rows"] = month_list[low]
    else:
        result["first_with_rows"] = month_list[high]
    return result


def report(out: Path) -> list[dict]:
    """Every stored answer: exchange, day, code, category, rows."""

    result = []
    root = out / RAW_DIR
    for exchange in EXCHANGES:
        folder = root / exchange
        if not folder.is_dir():
            continue
        for day_dir in sorted(folder.iterdir()):
            day = datetime.strptime(day_dir.name, "%Y%m%d").date()
            for path in sorted(day_dir.glob("*.json")):
                answer = PARSERS[exchange](path.read_bytes(), day, path.stem)
                result.append(
                    {
                        "exchange": exchange,
                        "date": day.isoformat(),
                        "code": path.stem,
                        "category": answer.category,
                        "rows": len(answer.rows),
                        "no_data": answer.no_data,
                    }
                )
    return result


# --- build --------------------------------------------------------------------


class BuildError(ValueError):
    """The raw cannot give a complete, trusted table."""


def retroactive(exchange: str, code: str, day: str) -> bool:
    """A category the exchange did not have on ``day``, filled in afterwards."""

    return code in RETROACTIVE_CODES.get(exchange, ()) and day < RETROACTIVE_BEFORE


def build_rows(out: Path, first: str, last: str) -> tuple[list[list], dict]:
    """Every member row from the raw, sorted; and per-answer provenance."""

    rows: list[list] = []
    sources: list[dict] = []
    filled: dict[tuple[str, str], list[str]] = {}
    for month in months(first, last):
        day = None
        for candidate in weekdays_back(month):
            path = raw_path(out, TWSE, candidate, DAY_PROBE_CODE)
            if not path.is_file():
                # fetch walks back from the last weekday: a later day without
                # its probe would make an earlier day the snapshot.
                raise BuildError(f"TWSE {candidate} type 01 is not in the raw")
            answer = parse_twse(path.read_bytes(), candidate, DAY_PROBE_CODE)
            if answer.rows:
                day = candidate
                break
            if not closed(answer):
                raise BuildError(f"TWSE {candidate} type 01 has no rows")
        if day is None:
            raise BuildError(f"{month} has no snapshot day in the raw")
        for exchange in EXCHANGES:
            for code in codes_for(month, exchange):
                path = raw_path(out, exchange, day, code)
                if not path.is_file():
                    raise BuildError(f"{exchange} {day} {code} is not in the raw")
                content = path.read_bytes()
                try:
                    answer = PARSERS[exchange](content, day, code)
                except AnswerError as exc:
                    raise BuildError(str(exc)) from exc
                if answer.no_data or not answer.rows:
                    raise BuildError(f"{exchange} {day} {code} answered no rows")
                names = CATEGORY_NAMES.get(exchange, {}).get(code, frozenset())
                if (answer.category or "") not in names:
                    raise BuildError(
                        f"{exchange} {day} {code} is {answer.category!r}, "
                        f"not one of {sorted(names)}"
                    )
                label = GROUP_LABELS[exchange][code]
                filled.setdefault((exchange, code), []).append(month)
                sources.append(
                    {
                        "exchange": exchange,
                        "snapshot_date": day.isoformat(),
                        "code": code,
                        "path": path.relative_to(out).as_posix(),
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "rows": len(answer.rows),
                    }
                )
                for symbol, name in answer.rows:
                    rows.append(
                        [
                            day.isoformat(),
                            exchange,
                            code,
                            answer.category or "",
                            label,
                            group_id(label),
                            symbol,
                            name,
                            retroactive(exchange, code, day.isoformat()),
                        ]
                    )
    all_months = months(first, last)
    for (exchange, code), filled_months in filled.items():
        span = all_months[
            all_months.index(filled_months[0]) : all_months.index(filled_months[-1]) + 1
        ]
        if span != filled_months:
            missing = sorted(set(span) - set(filled_months))
            raise BuildError(f"{exchange} {code} has a gap: {missing[:3]}")
    rows.sort()
    return rows, {"answers": sources}


ROW_FIELDS = (
    "snapshot_date",
    "exchange",
    "industry_code",
    "category",
    "group_label",
    "group_id",
    "symbol",
    "name",
    "retroactive_category",
)


def table_bytes(rows: list[list], first: str, last: str) -> bytes:
    document = {
        "format_version": FORMAT_VERSION,
        "definitions_sha256": definitions_sha256(),
        "months": [first, last],
        "fields": list(ROW_FIELDS),
        "rows": rows,
    }
    text = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    return (text + "\n").encode("utf-8")


def members_on(rows: list[list], day: date) -> list[list]:
    """The rows of the latest snapshot on or before ``day`` (none before the first).

    A snapshot is the close quotes of its day, public that evening, so a
    research day T (a trading day, after the close) may use ``snapshot_date <=
    T``.
    """

    text = day.isoformat()
    latest = max((row[0] for row in rows if row[0] <= text), default=None)
    return [row for row in rows if row[0] == latest]


def yearly(rows: list[list]) -> dict[str, dict[str, int]]:
    """Per snapshot year: rows, distinct (exchange, symbol), distinct groups."""

    result: dict[str, dict[str, set | int]] = {}
    for row in rows:
        year = row[0][:4]
        entry = result.setdefault(
            year, {"rows": 0, "companies": set(), "groups": set()}
        )
        entry["rows"] += 1
        entry["companies"].add((row[1], row[6]))
        entry["groups"].add(row[5])
    return {
        year: {
            "rows": entry["rows"],
            "companies": len(entry["companies"]),
            "groups": len(entry["groups"]),
        }
        for year, entry in sorted(result.items())
    }


# --- completeness -------------------------------------------------------------

TWSE_ALL_URL = (
    "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
    "?date={yyyymmdd}&type=ALLBUT0999&response=json"
)
TPEX_ALL_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
# TWSE depositary receipts are 91xx(xx); they are in no industry table.
COMMON_STOCK = re.compile(r"[1-9][0-9]{3}")
BACKEND = Path(__file__).resolve().parents[2] / "backend"


def _raw_file(payload_path: str, sha256: str) -> Path | None:
    """The stored file of a research DB raw row, checked against its sha256.

    Through ``app.raw_paths.payload_file`` like every reader of a stored
    capture (backend/tests/test_raw_paths.py): the research volume's old
    Windows paths map under ``STOCK_RAW_DIR``.
    """

    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from app.raw_paths import payload_file

    path = payload_file(payload_path)
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == sha256:
        return path
    return None


def common_stocks(exchange: str, payload: dict) -> set[str]:
    """Common-stock codes of a full-market close-quote answer."""

    codes = set()
    for table in payload.get("tables") or []:
        if not isinstance(table, dict) or not table.get("data"):
            continue
        title = str(table.get("title") or "")
        if exchange == TWSE and "每日收盤行情" not in title:
            continue
        for item in table["data"]:
            symbol = str(item[0]).strip()
            if COMMON_STOCK.fullmatch(symbol) and not (
                exchange == TWSE and symbol.startswith("91")
            ):
                codes.add(symbol)
    return codes


def completeness(rows: list[list], research_db: Path | None) -> dict:
    """Common stocks of the day's full-market quotes that are in no industry.

    The research DB's stored ``ALLBUT0999`` (TWSE) and ``dailyQuotes`` (TPEx)
    answers of each snapshot day, when it has them.  Each day is counted by
    reason: ``checked``, ``no_stored_answer`` (the DB has no such answer) or
    ``raw_missing`` (it has one, but its file is not found or its sha256
    differs: a wrong mount, PR #785 review 6905527404).  Read only
    (``mode=ro``, ``query_only``).
    """

    members: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        members.setdefault((row[1], row[0]), set()).add(row[6])
    result: dict = {"checked": 0, "no_stored_answer": 0, "raw_missing": 0, "days": []}
    connection = None
    if research_db is not None:
        if not Path(research_db).is_file():
            raise BuildError(f"research DB {research_db} is not a file")
        connection = sqlite3.connect(f"file:{research_db}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only=1")
    try:
        for exchange, day in sorted(members):
            entry: dict = {"exchange": exchange, "date": day, "checked": False}
            found = None
            if connection is not None:
                if exchange == TWSE:
                    url = TWSE_ALL_URL.format(yyyymmdd=day.replace("-", ""))
                    query = "endpoint = ?", (url,)
                else:
                    query = "endpoint = ? and data_as_of = ?", (TPEX_ALL_URL, day)
                found = connection.execute(
                    "select payload_path, sha256 from raw_payloads where "
                    f"{query[0]} order by id desc limit 1",
                    query[1],
                ).fetchone()
            path = _raw_file(found[0], found[1]) if found else None
            if path is None:
                reason = "no_stored_answer" if not found else "raw_missing"
                entry["reason"] = reason
                if found:
                    entry["payload_path"] = found[0]
                result[reason] += 1
            else:
                payload = json.loads(path.read_text(encoding="utf-8"))
                stocks = common_stocks(exchange, payload)
                entry.update(
                    checked=True,
                    stocks=len(stocks),
                    missing=sorted(stocks - members[(exchange, day)]),
                )
                result["checked"] += 1
            result["days"].append(entry)
    finally:
        if connection is not None:
            connection.close()
    result["unchecked"] = result["no_stored_answer"] + result["raw_missing"]
    result["days_with_missing"] = sum(
        bool(day.get("missing")) for day in result["days"]
    )
    return result


def build(
    out: Path,
    first: str,
    last: str,
    command: list[str],
    *,
    research_db: Path | None = None,
    allow_raw_missing: bool = False,
) -> dict:
    """The table and its manifest, written only after every check passed."""

    rows, provenance = build_rows(out, first, last)
    content = table_bytes(rows, first, last)
    check = completeness(rows, research_db)
    if check["raw_missing"] and not allow_raw_missing:
        example = next(
            day for day in check["days"] if day.get("reason") == "raw_missing"
        )
        raise BuildError(
            f"{check['raw_missing']} days have a stored answer whose file is not "
            f"found (e.g. {example['exchange']} {example['date']} "
            f"{example['payload_path']}): check the mounts, or pass "
            "--allow-raw-missing"
        )
    manifest = {
        "table": TABLE_NAME,
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
        "command": command,
        "commit": os.environ.get("STOCK_RESEARCH_COMMIT", ""),
        "definitions_sha256": definitions_sha256(),
        "definitions": definitions(),
        "months": [first, last],
        "yearly": yearly(rows),
        "retroactive_rows": sum(bool(row[8]) for row in rows),
        "completeness": check,
        **provenance,
    }
    text = json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True)
    (out / TABLE_NAME).write_bytes(content)
    (out / MANIFEST_NAME).write_text(text + "\n", encoding="utf-8")
    summary = {
        key: manifest[key] for key in ("sha256", "bytes", "yearly", "retroactive_rows")
    }
    summary["completeness"] = {
        key: check[key]
        for key in (
            "checked",
            "no_stored_answer",
            "raw_missing",
            "unchecked",
            "days_with_missing",
        )
    }
    return summary


# --- command line -------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="step", required=True)
    for name in ("fetch", "build"):
        step = sub.add_parser(name)
        step.add_argument("--start", required=True, help="first month, YYYY-MM")
        step.add_argument("--end", required=True, help="last month, YYYY-MM")
        step.add_argument("--out", required=True, type=Path)
        if name == "fetch":
            step.add_argument("--max-requests", type=int, default=None)
        else:
            step.add_argument("--research-db", type=Path, default=None)
            step.add_argument(
                "--allow-raw-missing",
                action="store_true",
                help="write the table even when a stored full-market answer's "
                "file is not found",
            )
    step = sub.add_parser("sweep", help="every known code on each month's day")
    step.add_argument("--months", required=True, help="YYYY-MM,YYYY-MM,...")
    step.add_argument("--out", required=True, type=Path)
    step.add_argument(
        "--only", action="append", default=[], help="EXCHANGE:CODE, repeatable"
    )
    step = sub.add_parser("bisect", help="the month a code starts or ends")
    step.add_argument("--exchange", required=True, choices=EXCHANGES)
    step.add_argument("--code", required=True)
    step.add_argument("--present", required=True, help="a month with rows")
    step.add_argument("--absent", required=True, help="a month without rows")
    step.add_argument("--out", required=True, type=Path)
    step = sub.add_parser("report", help="every stored answer")
    step.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.step in ("fetch", "sweep"):
        if args.step == "fetch":
            summary = fetch(
                args.start, args.end, args.out, max_requests=args.max_requests
            )
        else:
            only = [tuple(item.split(":", 1)) for item in args.only]
            summary = sweep(args.months.split(","), args.out, only=only)
        if summary["stopped"]:
            return STOP_EXIT
        return FAILED_EXIT if summary["failed"] or summary["errors"] else 0
    if args.step == "bisect":
        result = bisect(args.exchange, args.code, args.present, args.absent, args.out)
        print(json.dumps(result, ensure_ascii=False))
        return STOP_EXIT if result["stopped"] else 0
    if args.step == "report":
        for entry in report(args.out):
            print(json.dumps(entry, ensure_ascii=False, sort_keys=True))
        return 0
    try:
        result = build(
            args.out,
            args.start,
            args.end,
            ["build", *(argv if argv is not None else sys.argv[1:])[1:]],
            research_db=args.research_db,
            allow_raw_missing=args.allow_raw_missing,
        )
    except (BuildError, AnswerError, ValueError, sqlite3.Error) as exc:
        print(f"build failed: {exc}", file=sys.stderr)
        return FAILED_EXIT
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
