"""Insider holdings, pledges and transfer declarations of the research DB (Issue #1133).

Three feeds, one ``insider backfill`` command (#1129 decision 7233121423):

- ``irb110``: siis ``IRB110`` (董事、監察人、經理人及百分之十以上大股東股權異動彙總表),
  ``GET https://siis.twse.com.tw/publish/<sii|otc>/<民國年>IRB110_<MM>.HTM``, one
  request a market and month from 2003-08, into ``insider_holdings_monthly``.
- ``irb130``: the same for ``IRB130`` (質權設定彙總表), into
  ``insider_pledges_monthly``.
- ``t56sb21``: MOPS ``ajax_t56sb21`` (內部人持股轉讓事前申報彙總表), one POST a
  market and whole year from 2002, into ``insider_transfer_declarations``.

A module of its own, not ``worker.valuation_backfill``: these are monthly and
yearly HTML answers, not daily JSON (decision 7233473609).  What it shares is
imported from there: the quiet hours, the request interval and ``read_raw``.

Each feed, market and period is one ``ingestion_runs`` row (``RUN_TYPE``, request
key ``insider_backfill:<feed>:<market>:<YYYY-MM|YYYY>``): the manifest.  A month
already ``success`` is not asked again; a year is not asked again once it was
asked after it ended (the year still running is asked again, its rows replaced).
A siis 404 is ``not_published`` (a month not made yet), never a failure, and is
asked again on the next run; a ``t56sb21`` 404 fails (the endpoint moved).  ``reapply`` sends no request: it rereads the stored raw of
every unit that has one and rewrites the rows (``changed 0`` when nothing
differs).  One commit a unit, so a stopped run resumes.

Nothing is guessed: a siis file whose header 資料年月 is not the month asked, whose
columns are not the known ones or with a number that does not read, and a
``t56sb21`` answer whose rows are not its 總計 N 筆, fail the whole unit; nothing of
it is written.  An answer of MOPS's block page (查詢過於頻繁, ``BLOCK_MARKERS``)
stops the feed.  A 0 of the answer is 0, a blank is NULL; the share counts of a
``t56sb21`` row filed before ``PLACEHOLDER_BEFORE`` whose share cells are all 0
or blank are NULL (decision 7235256756).

The codes go to the research DB's instruments with a bar in the month (of the
report, or of the filing), the report's board first and the other one next (a
company that moved board that month is listed in the new one's report); a code
without one is counted (``unmatched``), never created.

Requests: at least ``REQUEST_INTERVAL_SECONDS`` apart on a host; none between
``QUIET_START`` and ``QUIET_END`` Taipei nor within ``EVEN_HOUR_MARGIN`` of an
even hour (the run waits); ``ABORT_AFTER_FAILURES`` failed requests in a row to
one host stop the run.  Only on the research database
(``quarterly_xbrl.research_refusal``), holding maintenance mode (``worker.cli``).
"""

from __future__ import annotations

import base64
import html as html_lib
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlencode

import httpx
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.models import (
    IngestionRun,
    InsiderHoldingsMonthly,
    InsiderPledgesMonthly,
    InsiderTransferDeclaration,
    Instrument,
    MarketBar,
    RawPayload,
)
from worker import pipeline, sources
from worker.monthly_revenue import BLOCK_MARKERS
from worker.sources import OfficialDataError
from worker.valuation_backfill import (
    ABORT_AFTER_FAILURES,
    MAX_LISTED,
    REQUEST_INTERVAL_SECONDS,
    TAIPEI,
    in_quiet_hours,
    read_raw,
    seconds_to_quiet_end,
)

SIIS_ENDPOINT = (
    "https://siis.twse.com.tw/publish/{market}/{roc}IRB{report}_{month:02d}.HTM"
)
T56SB21_ENDPOINT = "https://mopsov.twse.com.tw/mops/web/ajax_t56sb21"

# docs/DATA_SOURCES.md 各來源最早可得 (#1129): IRB110/IRB130 from 資料年月 9208 (a
# 404 before), t56sb21 rows from 2002-08-01 (2001 answers 無持股轉讓之情形).
IRB_FIRST_MONTH = date(2003, 8, 1)
T56SB21_FIRST_YEAR = 2002
# Decision 7235256756 (#1133): before this, a row whose share cells are all 0
# or blank is the site's placeholder; its share counts are kept NULL.
PLACEHOLDER_BEFORE = date(2003, 5, 1)

RUN_TYPE = "insider_backfill_period"
REQUEST_KEY = "insider_backfill:{feed}:{market}:{period}"
MARKETS = {"sii": "TWSE", "otc": "TPEx"}
OTHER_EXCHANGE = {"TWSE": "TPEx", "TPEx": "TWSE"}
INSTRUMENT_TYPES = ("stock", "ipo")
# Around each even hour the production news job runs (task file of #1133).
EVEN_HOUR_MARGIN = timedelta(minutes=10)
RETRY_DELAYS_SECONDS = (5.0, 10.0, 20.0)
USER_AGENT = "taiwan-stock-research/0.1"
NO_TRANSFER = "無持股轉讓之情形"


class LayoutError(OfficialDataError):
    """The answer is not one this reads; nothing of the unit is written."""


class Blocked(OfficialDataError):
    """MOPS answered its block page: the feed stops."""


@dataclass(frozen=True)
class Feed:
    name: str
    yearly: bool
    table: type
    source: str  # the rows' source
    raw_source: str  # raw_payloads.source and the raw directory


FEEDS: dict[str, Feed] = {
    feed.name: feed
    for feed in (
        Feed("irb110", False, InsiderHoldingsMonthly, "siis_irb110", "siis"),
        Feed("irb130", False, InsiderPledgesMonthly, "siis_irb130", "siis"),
        Feed("t56sb21", True, InsiderTransferDeclaration, "mops_t56sb21", "mops"),
    )
}


@dataclass(frozen=True)
class Answer:
    status: int
    content: bytes


# --- requests -------------------------------------------------------------------


def request_of(
    feed: str, market: str, period: date
) -> tuple[str, str, dict[str, str] | None]:
    """(method, url, form) of a unit; ``period`` is the month's or year's first day."""

    roc = period.year - 1911
    if feed == "t56sb21":
        form = {
            "step": "1",
            "TYPEK": market,
            "year": str(roc),
            "smonth": "01",
            "emonth": "12",
            "sstep": "1",
            "firstin": "true",
        }
        return "POST", T56SB21_ENDPOINT, form
    url = SIIS_ENDPOINT.format(
        market=market, roc=roc, report=feed[3:], month=period.month
    )
    return "GET", url, None


def raw_endpoint(url: str, form: dict[str, str] | None) -> str:
    """The endpoint kept in raw_payloads: a POST's form after ``?``."""

    return f"{url}?{urlencode(form)}" if form else url


def fetch_official(
    method: str,
    url: str,
    form: dict[str, str] | None,
    *,
    timeout_seconds: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[Answer, int]:
    """One request (its retries); the answer and the retries made.

    A transport error, 429 or 5xx is asked again after ``RETRY_DELAYS_SECONDS``;
    a 200 or 404 is the answer; any other status fails.
    """

    retries = 0
    for attempt in range(len(RETRY_DELAYS_SECONDS) + 1):
        try:
            if method == "POST":
                response = httpx.post(
                    url,
                    data=form,
                    timeout=timeout_seconds,
                    headers={"User-Agent": USER_AGENT},
                )
            else:
                response = httpx.get(
                    url, timeout=timeout_seconds, headers={"User-Agent": USER_AGENT}
                )
        except httpx.TransportError as exc:
            if attempt >= len(RETRY_DELAYS_SECONDS):
                raise OfficialDataError(f"transport retry exhausted: {url}") from exc
        else:
            if response.status_code in (200, 404):
                return Answer(response.status_code, response.content), retries
            if response.status_code != 429 and response.status_code < 500:
                raise OfficialDataError(
                    f"official endpoint answered {response.status_code}: {url}"
                )
            if attempt >= len(RETRY_DELAYS_SECONDS):
                raise OfficialDataError(
                    f"retry exhausted ({response.status_code}): {url}"
                )
        sleep(RETRY_DELAYS_SECONDS[attempt])
        retries += 1
    raise OfficialDataError(f"retry budget exhausted: {url}")


def seconds_to_wait(moment: datetime) -> float:
    """How long to wait before a request at ``moment``: 0 when it may go."""

    if in_quiet_hours(moment):
        return max(1.0, seconds_to_quiet_end(moment))
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    local = aware.astimezone(TAIPEI)
    hour = local.replace(minute=0, second=0, microsecond=0)
    nearest_even = hour if hour.hour % 2 == 0 else hour + timedelta(hours=1)
    if nearest_even - EVEN_HOUR_MARGIN <= local < nearest_even + EVEN_HOUR_MARGIN:
        return max(1.0, (nearest_even + EVEN_HOUR_MARGIN - local).total_seconds())
    return 0.0


# --- the stored answer ------------------------------------------------------------


def raw_document(
    method: str, url: str, form: dict[str, str] | None, answer: Answer
) -> dict[str, Any]:
    """What the raw keeps: the request and the answer's bytes as they came."""

    return {
        "endpoint": url,
        "method": method,
        "form": form,
        "status": answer.status,
        "content_base64": base64.b64encode(answer.content).decode("ascii"),
    }


def answer_bytes(document: Any) -> bytes:
    if not isinstance(document, dict) or not isinstance(
        document.get("content_base64"), str
    ):
        raise LayoutError("the raw is not an insider_backfill capture")
    return base64.b64decode(document["content_base64"], validate=True)


def decode_siis(content: bytes) -> tuple[str, str]:
    """(text, encoding) of a siis file: UTF-16 by its BOM, else Big5 (cp950).

    The Big5 files have a few characters cp950 does not map in company names
    (#1129); those become U+FFFD, the codes and numbers are ASCII.
    """

    if content[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return content.decode("utf-16"), "utf-16"
    return content.decode("cp950", errors="replace"), "cp950"


# --- cells --------------------------------------------------------------------

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_SHARES = re.compile(r"\d{1,3}(?:,\d{3})*|\d+")
_PCT = re.compile(r"\d+(?:\.\d+)?")
_ROC_DAY = re.compile(r"(\d{2,3})/(\d{1,2})/(\d{1,2})")
_CODE = re.compile(r"(\d{4,6})(\D.*)?", re.S)


def cell_text(cell: str) -> str:
    text = html_lib.unescape(_TAG.sub(" ", cell)).replace("\xa0", " ")
    return _SPACE.sub(" ", text).strip()


def shares(text: str) -> int | None:
    if text == "":
        return None
    if not _SHARES.fullmatch(text):
        raise LayoutError(f"unreadable share count {text!r}")
    return int(text.replace(",", ""))


def percent(text: str) -> float | None:
    if text == "":
        return None
    if not _PCT.fullmatch(text):
        raise LayoutError(f"unreadable percentage {text!r}")
    return float(text)


def roc_day(text: str) -> date:
    match = _ROC_DAY.fullmatch(text.strip())
    if not match:
        raise LayoutError(f"unreadable date {text!r}")
    try:
        return date(
            int(match.group(1)) + 1911, int(match.group(2)), int(match.group(3))
        )
    except ValueError as exc:
        raise LayoutError(f"unreadable date {text!r}") from exc


def _rows_of(table: str, tag: str) -> list[list[str]]:
    """The cells (``tag``: td or th) of each ``<tr>`` of ``table``, as raw HTML."""

    cell = re.compile(rf"<{tag}\b[^>]*>(.*?)</{tag}>", re.S | re.I)
    return [
        cell.findall(row)
        for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table, re.S | re.I)
    ]


# --- siis IRB110 / IRB130 -------------------------------------------------------

# The header rows' text without spaces and tags, as the files of 9208..11510 have
# it (#1129: 15 files, 2003..2026, both boards, both encodings).
IRB_HEADERS = {
    "irb110": (
        "公司名稱|實際發行股票總額|董事、監察人本月份|佔股份總額%|經理人本月份實際持有股數"
        "|百分之十以上大股東本月份實際持有股數|增加股數|減少股數|實際持有股數"
    ),
    "irb130": (
        "公司名稱|董事、監察人本月份|佔持股比例%|經理人本月份實際持有股數"
        "|百分之十以上大股東本月份實際持有股數|經理人及百分之十以上大股東已設定股數"
        "|佔持股比例%|實際持有股數|設定股數|解除股數|累計設定股數"
    ),
}
IRB_COLUMNS = {
    "irb110": (
        ("shares_issued", shares),
        ("director_increase", shares),
        ("director_decrease", shares),
        ("director_held", shares),
        ("director_held_pct", percent),
        ("manager_held", shares),
        ("major_holder_held", shares),
    ),
    "irb130": (
        ("director_held", shares),
        ("director_pledge_set", shares),
        ("director_pledge_released", shares),
        ("director_pledged", shares),
        ("director_pledged_pct", percent),
        ("manager_held", shares),
        ("major_holder_held", shares),
        ("manager_major_pledged", shares),
        ("manager_major_pledged_pct", percent),
    ),
}
_YM = re.compile(r"資\s*料\s*年\s*月\s*[:：]\s*(\d{4,5})")
_DATA_DAY = re.compile(r"資\s*料\s*日\s*期\s*[:：]\s*(\d{2,3}/\d{1,2}/\d{1,2})")
_REPORT = re.compile(r"\[(IRB\d{3})\]")


def _header_text(cells: list[str]) -> str:
    return "|".join(_SPACE.sub("", cell_text(c)) for c in cells)


def parse_irb(feed: str, content: bytes, month: date) -> dict[str, Any]:
    """{encoding, data_as_of, rows: {code: values}, names_replaced} of a siis file."""

    text, encoding = decode_siis(content)
    text = re.sub(r"<script\b.*?</script>", "", text, flags=re.S | re.I)
    report = _REPORT.search(text)
    if not report or report.group(1).lower() != feed:
        raise LayoutError(f"not an {feed.upper()} file")
    ym = _YM.search(text)
    if not ym:
        raise LayoutError("no 資料年月")
    roc_ym = ym.group(1)
    reported = (int(roc_ym[:-2]) + 1911, int(roc_ym[-2:]))
    if reported != (month.year, month.month):
        raise LayoutError(f"資料年月 {roc_ym} is not {month:%Y-%m}")
    day = _DATA_DAY.search(text)
    if not day:
        raise LayoutError("no 資料日期")
    data_as_of = roc_day(day.group(1))
    tables = re.findall(
        r"<table\s+border\s+align=center\s*>(.*?)</table>", text, re.S | re.I
    )
    if len(tables) != 1:
        raise LayoutError(f"{len(tables)} data tables, expected 1")
    rows = _rows_of(tables[0], "td")
    columns = IRB_COLUMNS[feed]
    if (
        len(rows) < 2
        or "|".join(_header_text(r) for r in rows[:2]) != IRB_HEADERS[feed]
    ):
        raise LayoutError("unknown columns")
    parsed: dict[str, dict[str, Any]] = {}
    replaced = 0
    for cells in rows[2:]:
        if len(cells) != len(columns) + 1:
            raise LayoutError(f"a row of {len(cells)} cells: {cells[:1]!r}")
        first = cell_text(cells[0])
        match = _CODE.fullmatch(first)
        if not match:
            raise LayoutError(f"a row without a code: {first[:12]!r}")
        code = match.group(1)
        if code in parsed:
            raise LayoutError(f"code {code} is listed twice")
        if "\ufffd" in first:
            replaced += 1
        parsed[code] = {
            name: read(cell_text(cell))
            for (name, read), cell in zip(columns, cells[1:])
        }
    if not parsed:
        raise LayoutError("the table has no rows")
    return {
        "encoding": encoding,
        "data_as_of": data_as_of,
        "rows": parsed,
        "names_replaced": replaced,
    }


# --- MOPS t56sb21 ----------------------------------------------------------------

T56_HEADERS = (
    "異動情形|申報日期|公司代號|公司名稱|申報人身分|姓名|預定轉讓方式及股數"
    "|每日於盤中交易最大得轉讓股數|受讓人|目前持有股數|預定轉讓總股數|預定轉讓後持股"
    "|有效轉讓期間|是否申報持股未完成轉讓"
    "|轉讓方式|轉讓股數|自有持股|保留運用決定權信託股數|自有持股|保留運用決定權信託股數"
    "|自有持股|保留運用決定權信託股數"
)
T56_CELLS = 18
_TOTAL = re.compile(r"總計[:：]\s*([\d,]+)\s*筆")
_PERIOD = re.compile(r"(\d{2,3}/\d{1,2}/\d{1,2})\s*~\s*(\d{2,3}/\d{1,2}/\d{1,2})")
SHARE_FIELDS = (
    "intraday_max_shares",
    "held_own",
    "held_trust",
    "planned_own",
    "planned_trust",
    "after_own",
    "after_trust",
)

_ROLE = re.compile(
    r"(?P<sub>子公司)?(?P<corp>法人)?(?P<base>董事|監察人|經理人|大股東|特定人)"
    r"(?P<rep>代表人)?(?P<rel>本人|配偶|未成年子女|利用他人名義持有者)"
    r"(?P<trust>\s*及由受託人持有者)?"
)
_BASE = {
    "董事": "director",
    "監察人": "supervisor",
    "經理人": "manager",
    "大股東": "major_holder",
    "特定人": "specific_person",
}
_RELATION = {
    "本人": "self",
    "配偶": "spouse",
    "未成年子女": "minor_child",
    "利用他人名義持有者": "nominee",
}


def split_role(role: str) -> tuple[str | None, str | None, int]:
    """(insider_type, relation, via_trustee) of a 申報人身分; NULLs when it does not split.

    ``法人董事代表人本人`` is a director's ``representative``; its 配偶, 未成年子女
    and 利用他人名義持有者 ``representative_spouse``, ``representative_minor_child``
    and ``representative_nominee``.
    """

    via_trustee = 1 if "及由受託人持有者" in role else 0
    match = _ROLE.fullmatch(role)
    if not match or bool(match["corp"]) != bool(match["rep"]):
        return None, None, via_trustee
    if match["corp"] and match["base"] not in ("董事", "監察人"):
        return None, None, via_trustee
    insider_type = ("subsidiary_" if match["sub"] else "") + _BASE[match["base"]]
    relation = _RELATION[match["rel"]]
    if match["corp"]:
        relation = (
            "representative" if relation == "self" else f"representative_{relation}"
        )
    return insider_type, relation, via_trustee


def _blocked(text: str) -> bool:
    upper = text.upper()
    return any(marker.upper() in upper for marker in BLOCK_MARKERS)


def parse_t56sb21(content: bytes, year: int) -> dict[str, Any]:
    """{rows: [values with code], no_transfer, placeholder_rows} of a year's answer."""

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LayoutError("the answer is not UTF-8") from exc
    if _blocked(text):
        raise Blocked("MOPS answered its block page (查詢過於頻繁)")
    total = _TOTAL.findall(text)
    if not total:
        if NO_TRANSFER in text and "<td" not in text.lower():
            return {"rows": [], "no_transfer": True, "placeholder_rows": 0}
        raise LayoutError("no 總計 and no 無持股轉讓之情形")
    if len(total) != 1:
        raise LayoutError(f"{len(total)} 總計 lines")
    head = "|".join(_header_text(cells) for cells in _rows_of(text, "th") if cells)
    if head != T56_HEADERS:
        raise LayoutError("unknown columns")
    rows: list[dict[str, Any]] = []
    placeholders = 0
    for cells in _rows_of(text, "td"):
        if not cells:
            continue
        if len(cells) != T56_CELLS:
            raise LayoutError(f"a row of {len(cells)} cells")
        t = [cell_text(c) for c in cells]
        filed = roc_day(t[1])
        if filed.year != year:
            raise LayoutError(f"filed {filed} is not in {year}")
        code = t[2]
        if not re.fullmatch(r"\d{4,6}", code):
            raise LayoutError(f"unreadable code {code!r}")
        if not t[4] or not t[5] or not t[6]:
            raise LayoutError(f"a row without 身分, 姓名 or 轉讓方式 ({filed} {code})")
        method_shares = t[7] or None
        if method_shares is not None:
            for part in method_shares.split(" "):
                shares(part)
        values: dict[str, Any] = dict(
            zip(SHARE_FIELDS, (shares(x) for x in (t[8], *t[10:16])))
        )
        period = t[16]
        if period:
            match = _PERIOD.fullmatch(period)
            if not match:
                raise LayoutError(f"unreadable 有效轉讓期間 {period!r}")
            start, end = roc_day(match.group(1)), roc_day(match.group(2))
        else:
            start = end = None
        if t[17] not in ("", "是"):
            raise LayoutError(f"unreadable 是否申報持股未完成轉讓 {t[17]!r}")
        if filed < PLACEHOLDER_BEFORE:
            cells_of_shares = [*(method_shares or "").split(" "), t[8], *t[10:16]]
            if all(re.fullmatch(r"0*", c) for c in cells_of_shares):
                values = dict.fromkeys(SHARE_FIELDS)
                method_shares = None
                placeholders += 1
        insider_type, relation, via_trustee = split_role(t[4])
        rows.append(
            {
                "row_no": len(rows) + 1,
                "code": code,
                "filed_date": filed,
                "role_raw": t[4],
                "insider_type": insider_type,
                "relation": relation,
                "via_trustee": via_trustee,
                "person_name": t[5],
                "transferee": t[9] or None,
                "method_raw": t[6],
                "method_shares_raw": method_shares,
                **values,
                "period_start": start,
                "period_end": end,
                "unfinished_declared": 1 if t[17] == "是" else None,
                "change_note": t[0] or None,
            }
        )
    expected = int(total[0].replace(",", ""))
    if expected != len(rows):
        raise LayoutError(f"總計 {expected} 筆 but {len(rows)} rows")
    return {"rows": rows, "no_transfer": False, "placeholder_rows": placeholders}


# --- the database ---------------------------------------------------------------


def month_end(month: date) -> date:
    following = date(month.year + month.month // 12, month.month % 12 + 1, 1)
    return following - timedelta(days=1)


def barred_in_month(db: Session, month: date) -> dict[tuple[str, str], int]:
    """{(exchange, code): instrument id} of the instruments with a bar in the month."""

    return {
        (exchange, symbol): instrument_id
        for instrument_id, exchange, symbol in db.execute(
            select(Instrument.id, Instrument.exchange, Instrument.symbol)
            .join(MarketBar, MarketBar.instrument_id == Instrument.id)
            .where(
                Instrument.instrument_type.in_(INSTRUMENT_TYPES),
                MarketBar.trading_date >= month,
                MarketBar.trading_date <= month_end(month),
            )
            .distinct()
        )
    }


def match_code(
    barred: dict[tuple[str, str], int], market: str, code: str
) -> tuple[int | None, bool]:
    """(instrument id, from the other board) of a report's code."""

    exchange = MARKETS[market]
    if (exchange, code) in barred:
        return barred[(exchange, code)], False
    other = barred.get((OTHER_EXCHANGE[exchange], code))
    return other, other is not None


def _unit_run(
    db: Session, feed: str, market: str, period: date, *, create: bool
) -> IngestionRun | None:
    label = str(period.year) if FEEDS[feed].yearly else f"{period:%Y-%m}"
    key = REQUEST_KEY.format(feed=feed, market=market, period=label)
    run = db.scalar(select(IngestionRun).where(IngestionRun.request_key == key))
    if run is None and create:
        run = IngestionRun(
            run_type=RUN_TYPE,
            source=feed,
            run_date=period,
            status="running",
            request_key=key,
            data_as_of=label,
            metadata_json={"market": market},
        )
        db.add(run)
        db.flush()
    return run


def _sync(
    db: Session,
    existing: dict[Any, Any],
    wanted: dict[Any, dict[str, Any]],
    make: Callable[[dict[str, Any]], Any],
) -> Counter[str]:
    """Make the unit's rows ``wanted``: insert, update, delete; the counts."""

    counts: Counter[str] = Counter()
    for key, fields in wanted.items():
        row = existing.get(key)
        if row is None:
            db.add(make(fields))
            counts["inserted"] += 1
        elif any(getattr(row, name) != value for name, value in fields.items()):
            for name, value in fields.items():
                setattr(row, name, value)
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1
    for key, row in existing.items():
        if key not in wanted:
            db.delete(row)
            counts["removed"] += 1
    return counts


def write_monthly(
    db: Session,
    feed: Feed,
    market: str,
    month: date,
    parsed: dict[str, Any],
    raw: RawPayload,
) -> dict[str, Any]:
    model = feed.table
    barred = barred_in_month(db, month)
    rows = db.scalars(
        select(model).where(model.period_month == month, model.source == feed.source)
    ).all()
    existing = {row.instrument_id: row for row in rows if row.market == market}
    other_board = {row.instrument_id for row in rows if row.market != market}
    wanted: dict[int, dict[str, Any]] = {}
    unmatched: list[str] = []
    duplicate: list[str] = []
    cross = 0
    for code, values in parsed["rows"].items():
        instrument_id, crossed = match_code(barred, market, code)
        if instrument_id is None:
            unmatched.append(code)
            continue
        if instrument_id in other_board or instrument_id in wanted:
            # The other board's report already has this company this month.
            duplicate.append(code)
            continue
        cross += crossed
        wanted[instrument_id] = {
            **values,
            "instrument_id": instrument_id,
            "period_month": month,
            "market": market,
            "source": feed.source,
            "data_as_of": parsed["data_as_of"],
            "raw_payload_id": raw.id,
            "collected_at": raw.collected_at,
        }
    counts = _sync(db, existing, wanted, lambda fields: model(**fields))
    return {
        "rows": len(parsed["rows"]),
        "written": len(wanted),
        **{k: counts[k] for k in ("inserted", "updated", "removed", "unchanged")},
        "unmatched": len(unmatched),
        "unmatched_codes": sorted(unmatched)[:MAX_LISTED],
        "cross_market": cross,
        "duplicate": len(duplicate),
        "duplicate_codes": sorted(duplicate)[:MAX_LISTED],
        "encoding": parsed["encoding"],
        "data_as_of": parsed["data_as_of"].isoformat(),
        "names_replaced": parsed["names_replaced"],
    }


def write_yearly(
    db: Session,
    feed: Feed,
    market: str,
    year: date,
    parsed: dict[str, Any],
    raw: RawPayload,
) -> dict[str, Any]:
    model = feed.table
    existing = {
        (row.raw_payload_id, row.row_no): row
        for row in db.scalars(
            select(model).where(
                model.source == feed.source,
                model.market == market,
                model.filed_date >= year,
                model.filed_date <= date(year.year, 12, 31),
            )
        )
    }
    months: dict[date, dict[tuple[str, str], int]] = {}
    wanted: dict[tuple[int, int], dict[str, Any]] = {}
    unmatched: Counter[str] = Counter()
    cross = 0
    for values in parsed["rows"]:
        values = dict(values)
        code = values.pop("code")
        month = values["filed_date"].replace(day=1)
        if month not in months:
            months[month] = barred_in_month(db, month)
        instrument_id, crossed = match_code(months[month], market, code)
        if instrument_id is None:
            unmatched[code] += 1
            continue
        cross += crossed
        wanted[(raw.id, values["row_no"])] = {
            **values,
            "instrument_id": instrument_id,
            "market": market,
            "source": feed.source,
            "data_as_of": values["filed_date"],
            "raw_payload_id": raw.id,
            "collected_at": raw.collected_at,
        }
    counts = _sync(db, existing, wanted, lambda fields: model(**fields))
    return {
        "rows": len(parsed["rows"]),
        "written": len(wanted),
        **{k: counts[k] for k in ("inserted", "updated", "removed", "unchanged")},
        "unmatched": sum(unmatched.values()),
        "unmatched_codes": sorted(unmatched)[:MAX_LISTED],
        "cross_market": cross,
        "no_transfer": parsed["no_transfer"],
        "placeholder_rows": parsed["placeholder_rows"],
    }


# --- the run --------------------------------------------------------------------


def periods(feed: Feed, start: date, end: date) -> list[date]:
    if feed.yearly:
        return [date(year, 1, 1) for year in range(start.year, end.year + 1)]
    result, month = [], start.replace(day=1)
    while month <= end:
        result.append(month)
        month = date(month.year + month.month // 12, month.month % 12 + 1, 1)
    return result


def published(feed: Feed, period: date) -> bool:
    if feed.yearly:
        return period.year >= T56SB21_FIRST_YEAR
    return period >= IRB_FIRST_MONTH


def _taipei_day(moment: datetime) -> date:
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return aware.astimezone(TAIPEI).date()


def _done(feed: Feed, run: IngestionRun, period: date) -> bool:
    """A success not to ask again: a month, or a year asked after it ended."""

    if run.status != "success":
        return False
    if not feed.yearly:
        return True
    asked = (run.metadata_json or {}).get("asked_on")
    return bool(asked) and date.fromisoformat(asked).year > period.year


def _empty_counts() -> dict[str, Any]:
    return {
        "units": 0,
        "not_published": 0,
        "done_before": 0,
        "requested": 0,
        "retries": 0,
        "reapplied": 0,
        "not_answered": 0,
        "success": 0,
        "failed": 0,
        "failed_units": [],
        "rows": 0,
        "written": 0,
        "inserted": 0,
        "updated": 0,
        "removed": 0,
        "unchanged": 0,
        "unmatched": 0,
        "cross_market": 0,
        "duplicate": 0,
        "placeholder_rows": 0,
        "no_transfer": 0,
        "blocked": None,
    }


class _Pacer:
    """Keeps requests to one host ``REQUEST_INTERVAL_SECONDS`` apart and out of
    the quiet hours."""

    def __init__(
        self,
        now: Callable[[], datetime],
        sleep: Callable[[float], None],
        monotonic: Callable[[], float],
    ) -> None:
        self.now, self.sleep, self.monotonic = now, sleep, monotonic
        self.last: dict[str, float] = {}

    def before(self, host: str) -> None:
        while (wait := seconds_to_wait(self.now())) > 0:
            self.sleep(wait)
        previous = self.last.get(host)
        if previous is not None:
            gap = self.monotonic() - previous
            if gap < REQUEST_INTERVAL_SECONDS:
                self.sleep(REQUEST_INTERVAL_SECONDS - gap)
        self.last[host] = self.monotonic()


def backfill(
    db: Session,
    start: date,
    end: date,
    *,
    feeds: list[str] | None = None,
    markets: list[str] | None = None,
    reapply: bool = False,
    fetch: Callable[..., tuple[Answer, int]] = fetch_official,
    now: Callable[[], datetime] = utcnow,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    if end < start:
        raise ValueError("--end is before --start")
    names = feeds or list(FEEDS)
    unknown = [name for name in names if name not in FEEDS]
    if unknown:
        raise ValueError(f"unknown feeds {unknown}; known: {list(FEEDS)}")
    boards = markets or list(MARKETS)
    if any(market not in MARKETS for market in boards):
        raise ValueError(f"unknown markets {boards}; known: {list(MARKETS)}")
    for name in names:
        table = FEEDS[name].table.__tablename__
        if not inspect(db.get_bind()).has_table(table):
            raise ValueError(f"{table} is missing: run init-db first")
    started = monotonic()
    pacer = _Pacer(now, sleep, monotonic)
    result = {name: _empty_counts() for name in names}
    requests = 0
    failures_in_a_row: Counter[str] = Counter()
    aborted = None
    for name in names:
        feed = FEEDS[name]
        counts = result[name]
        for period in periods(feed, start, end):
            for market in boards:
                if aborted or counts["blocked"]:
                    break
                counts["units"] += 1
                if not published(feed, period):
                    counts["not_published"] += 1
                    continue
                run = _unit_run(db, name, market, period, create=not reapply)
                if run is None:
                    counts["not_answered"] += 1
                    continue
                if not reapply and _done(feed, run, period):
                    counts["done_before"] += 1
                    continue
                stored = (run.metadata_json or {}).get("raw_payload_id")
                if reapply and stored is None:
                    counts["not_answered"] += 1
                    continue
                method, url, form = request_of(name, market, period)
                host = re.sub(r"^https://([^/]+)/.*$", r"\1", url)
                raw: RawPayload | None = None
                asked_on = None
                try:
                    if not reapply:
                        pacer.before(host)
                        requests += 1
                        counts["requested"] += 1
                        try:
                            answer, retries = fetch(method, url, form, sleep=sleep)
                        except Exception as exc:  # the source's, never a crash
                            failures_in_a_row[host] += 1
                            raise OfficialDataError(f"request failed: {exc}") from exc
                        failures_in_a_row[host] = 0
                        counts["retries"] += retries
                        if answer.status == 404 and feed.yearly:
                            # The MOPS ajax endpoint is not a file that comes
                            # later: a 404 means it moved.
                            raise OfficialDataError(
                                f"official endpoint answered 404: {url}"
                            )
                        if answer.status == 404:
                            counts["not_published"] += 1
                            run.status = "not_published"
                            run.error = None
                            run.finished_at = utcnow()
                            run.metadata_json = {
                                **(run.metadata_json or {}),
                                "status_code": 404,
                                "asked_on": _taipei_day(now()).isoformat(),
                            }
                            db.commit()
                            continue
                        asked_on = _taipei_day(now()).isoformat()
                        captured = sources.capture_payload(
                            feed.raw_source,
                            raw_endpoint(url, form),
                            raw_document(method, url, form, answer),
                            period.isoformat(),
                        )
                        raw = pipeline._upsert_raw_payload(db, run, captured)
                        content = answer.content
                    else:
                        counts["reapplied"] += 1
                        raw = db.get(RawPayload, stored)
                        if raw is None:
                            raise OfficialDataError(
                                "the stored unit has no raw payload"
                            )
                        asked_on = (run.metadata_json or {}).get("asked_on")
                        content = answer_bytes(read_raw(raw))
                    if feed.yearly:
                        parsed = parse_t56sb21(content, period.year)
                        written = write_yearly(db, feed, market, period, parsed, raw)
                    else:
                        parsed = parse_irb(name, content, period)
                        written = write_monthly(db, feed, market, period, parsed, raw)
                except OfficialDataError as exc:
                    # Parsing fails before any row is written; the capture is kept.
                    run.status = "failed"
                    run.error = str(exc)
                    run.finished_at = utcnow()
                    metadata = {**(run.metadata_json or {}), "error": str(exc)}
                    if raw is not None:
                        metadata["raw_payload_id"] = raw.id
                    if asked_on:
                        metadata["asked_on"] = asked_on
                    run.metadata_json = metadata
                    db.commit()
                    counts["failed"] += 1
                    if len(counts["failed_units"]) < MAX_LISTED:
                        counts["failed_units"].append(
                            {
                                "market": market,
                                "period": run.data_as_of,
                                "error": str(exc),
                            }
                        )
                    if isinstance(exc, Blocked):
                        counts["blocked"] = str(exc)
                    if failures_in_a_row[host] >= ABORT_AFTER_FAILURES:
                        aborted = (
                            f"{ABORT_AFTER_FAILURES} failed requests in a row to {host}"
                        )
                    continue
                run.status = "success"
                run.error = None
                run.records = written["written"]
                run.finished_at = utcnow()
                run.metadata_json = {
                    "market": market,
                    "raw_payload_id": raw.id,
                    "source": feed.source,
                    "asked_on": asked_on,
                    **written,
                }
                db.commit()
                counts["success"] += 1
                for key in (
                    "rows",
                    "written",
                    "inserted",
                    "updated",
                    "removed",
                    "unchanged",
                    "unmatched",
                    "cross_market",
                    "duplicate",
                    "placeholder_rows",
                ):
                    counts[key] += written.get(key, 0)
                counts["no_transfer"] += int(written.get("no_transfer", False))
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
        "duration_seconds": round(monotonic() - started, 1),
    }


def _month(text: str) -> date:
    return (
        date.fromisoformat(f"{text}-01") if len(text) == 7 else date.fromisoformat(text)
    )


def run_insider_backfill(
    start: str,
    end: str,
    *,
    feeds: list[str] | None = None,
    markets: list[str] | None = None,
    reapply: bool = False,
) -> dict[str, Any]:
    from app.db import SessionLocal

    try:
        first, last = _month(start), _month(end)
    except ValueError as exc:
        return {"status": "failed", "error": str(exc)}
    with SessionLocal() as db:
        try:
            return backfill(
                db, first, last, feeds=feeds, markets=markets, reapply=reapply
            )
        except ValueError as exc:
            db.rollback()
            return {"status": "failed", "error": str(exc)}
