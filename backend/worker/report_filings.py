"""Upload times of the quarterly reports from the TWSE e-book page (Issue #1100).

``fundamental_snapshots.announcement_date`` of a backfilled quarter is the
statutory deadline, the same day for every company.  The TWSE e-book page
``t57sb01`` (電子資料查詢作業, ``ENDPOINT``) lists every file a company uploaded for
a year's quarters with its upload time to the second, delisted, merged and
transferred companies too (#1096 report 7211851841).  One POST asks for one
company and one year (``request_form``); ``check2858=Y`` makes a financial
holding company answer its own table instead of a menu of its subsidiaries.

Four commands (``worker.cli filings``), so the requests never touch a database:

- ``plan_targets`` / ``write_plan``: every code and year from ``FIRST_YEAR`` with
  a quarter in the research database's ``fundamental_snapshots``, into
  ``PLAN`` of a directory.  Read only.
- ``fetch_pages``: asks for the plan's pages into the directory (``raw/``,
  ``MANIFEST``, ``REQUESTS``).  A page already there and whole is not asked
  again: a stopped run goes on where it stopped.  At least
  ``REQUEST_INTERVAL_SECONDS`` between requests, none in ``quiet_until``'s Taipei
  windows (the run waits).  A rate-limit page (「查詢過量」), HTTP 403/429, a page
  that is not the company table nor 「查無所需資料」, or no answer is a failure,
  never an empty page; ``ABORT_AFTER_FAILURES`` in a row stop the run with the
  last page that succeeded.  Failed answers are kept under ``FAILED_DIR``.
- ``write_filings``: reads the stored pages into ``financial_report_filings``, one
  ``RUN_TYPE`` run.  Only the research database (``quarterly_xbrl
  .research_refusal``), holding maintenance mode (``worker.cli``).
- ``coverage``: the quarters with a snapshot that have a filing date, by year and
  instrument status.  Read only.

What is written (#1100 decision 7214693152):

- The page's 公司名稱 must match the instrument's name (``names_match``) or be in
  the accepted list; a code reused by a later company answers the company of
  today.  A target whose name does not match writes nothing and is listed.
- Rows of the pre-IFRS kinds (``OLD_KINDS``: 母公司財報, 母子公司合併報表 and their
  English versions) are counted and not written; a quarter left with no Chinese
  IFRSs row by that is ``old_layout`` and writes nothing.  A 資料細節說明 of no known
  kind fails the whole page.
- ``filing_date`` is the rule for a quarter's actual filing time.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from datetime import time as clock_time
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.db import SessionLocal
from app.models import (
    FinancialReportFiling,
    FundamentalSnapshot,
    IngestionRun,
    Instrument,
    RawPayload,
)
from app.raw_paths import payload_file
from worker import sources
from worker.sources import OfficialDataError

ENDPOINT = "https://doc.twse.com.tw/server-java/t57sb01"
SOURCE = "twse_doc_t57sb01"
# raw_payloads.source and the raw directory.
RAW_SOURCE = "twse_doc"
RUN_TYPE = "financial_report_filings_backfill"
# IFRS filings, and the research DB's quarterly reports, start here (#1096 decision).
FIRST_YEAR = 2013
ENCODING = "big5hkscs"
USER_AGENT = "taiwan-stock-research/0.1"
TAIPEI = timezone(timedelta(hours=8))

# --- request rules (#1100 scope 4) ---------------------------------------------
# 3.5 to 5 seconds got 「查詢過量」 after about 12 requests a minute (#1096).
REQUEST_INTERVAL_SECONDS = 6.0
# Taipei: the production daily (21:30) and the MOPS maintenance hours.
QUIET_HOURS = (
    (clock_time(20, 30), clock_time(23, 30)),
    (clock_time(8, 0), clock_time(9, 0)),
)
# The news runs on the even hours.
EVEN_HOUR_MARGIN = timedelta(minutes=10)
ABORT_AFTER_FAILURES = 3
REQUEST_TIMEOUT_SECONDS = 60.0
MAX_PAGE_BYTES = 2 << 20

# --- the directory --------------------------------------------------------------
PLAN = "targets.json"
MANIFEST = "manifest.json"
REQUESTS = "requests.jsonl"
RAW_SUBDIR = "raw"
FAILED_DIR = "failed"

# --- the page -------------------------------------------------------------------
RATE_LIMITED_TEXT = "查詢過量"
NO_DATA_TEXT = "查無所需資料"
HEADER = (
    "證券代號",
    "資料年度",
    "資料類型",
    "結案類型",
    "性質",
    "資料細節說明",
    "備註",
    "電子檔案",
    "檔案大小",
    "上傳日期",
    "財務報告更(補)正",
)
QUARTERS = {"一": 1, "二": 2, "三": 3, "四": 4}
# IFRSs合併財報, IFRSs英文版-個體財報, IFRSs合併財報(重編), IFRSs合併財報(第二次重編), ...
IFRS_KIND = re.compile(
    r"IFRSs(?P<english>英文版-)?(?P<statement>合併|個別|個體)財報"
    r"(?P<restated>\((?:第.次)?重編\))?"
)
# Written, never a filing date (decision 7214693152 point 3).
SUPPLEMENTARY_KINDS = frozenset({"關係企業合併報表", "外國企業實際營運地之個體財報"})
# Pre-IFRS: counted, never written.
OLD_KINDS = frozenset(
    {"母公司財報", "母子公司合併報表", "英文版-母公司財報", "英文版-母子公司合併報表"}
)
# The kinds of a quarter's actual filing date: the Chinese statements themselves,
# no English version, no restatement, no supplementary report (decision
# 7214693152 point 3; 個別 is the statement of a company without subsidiaries,
# question 7214707188, decision 7214724744).
FILING_DATE_KINDS = frozenset({"IFRSs合併財報", "IFRSs個別財報", "IFRSs個體財報"})

_NAME = re.compile(r"公司名稱：([^<\r\n]*)")
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<t([dh])[^>]*>(.*?)</t[dh]>", re.S | re.I)
_TAG = re.compile(r"<[^>]*>")
_YEAR = re.compile(r"(\d{2,3})\s*年\s*第([一二三四])季")
_FILE = re.compile(r"(\d{4})(0[1-4])_([0-9A-Za-z]+)_([0-9A-Z]+)\.([0-9A-Za-z]+)")
_UPLOADED = re.compile(r"(\d{2,3})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2}):(\d{2})")
_SIZE = re.compile(r"\d{1,3}(?:,\d{3})*|\d+")
# What a byte Big5 does not read decodes to.
REPLACEMENT = chr(0xFFFD)
_CORRECTION_LINK = re.compile(r"location\.href='([^']+)'")


class LayoutError(OfficialDataError):
    """The page is not one this reads; nothing of it is written."""


class Refused(ValueError):
    """The directory or arguments are not ones this may run on."""


# --- targets --------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    symbol: str
    year: int

    @property
    def roc_year(self) -> int:
        return self.year - 1911

    @property
    def key(self) -> str:
        return f"{self.symbol}/{self.roc_year}"


def request_form(target: Target) -> dict[str, str]:
    return {
        "step": "1",
        "colorchg": "1",
        "co_id": target.symbol,
        "year": str(target.roc_year),
        "mtype": "A",
        "check2858": "Y",
    }


def request_endpoint(target: Target) -> str:
    """The endpoint kept in raw_payloads: the POST form as a query."""

    return f"{ENDPOINT}?{urlencode(request_form(target))}"


@dataclass
class TargetInstrument:
    id: int
    exchange: str
    name: str
    status: str
    quarters: set[int] = field(default_factory=set)


def plan_targets(
    db: Session, first_year: int = FIRST_YEAR
) -> dict[Target, list[TargetInstrument]]:
    """Every code and year with a quarterly report in the database, and its instruments.

    A code on two instruments (a transfer between the exchanges) is one request.
    """

    rows = db.execute(
        select(
            Instrument.id,
            Instrument.exchange,
            Instrument.symbol,
            Instrument.name,
            Instrument.status,
            FundamentalSnapshot.period_end,
        )
        .join(FundamentalSnapshot, FundamentalSnapshot.instrument_id == Instrument.id)
        .where(FundamentalSnapshot.period_end >= date(first_year, 1, 1))
    ).all()
    targets: dict[Target, dict[int, TargetInstrument]] = defaultdict(dict)
    for iid, exchange, symbol, name, status, period_end in rows:
        quarter = _quarter_of(period_end)
        if quarter is None:
            continue
        target = Target(symbol, period_end.year)
        item = targets[target].setdefault(
            iid, TargetInstrument(iid, exchange, name, status)
        )
        item.quarters.add(quarter)
    return {
        target: sorted(items.values(), key=lambda item: item.id)
        for target, items in sorted(
            targets.items(), key=lambda pair: (pair[0].symbol, pair[0].year)
        )
    }


def _quarter_of(period_end: date) -> int | None:
    if (period_end.month, period_end.day) in {(3, 31), (6, 30), (9, 30), (12, 31)}:
        return period_end.month // 3
    return None


def write_plan(directory: Path, db: Session, first_year: int = FIRST_YEAR) -> dict:
    targets = plan_targets(db, first_year)
    directory.mkdir(parents=True, exist_ok=True)
    plan = {
        "endpoint": ENDPOINT,
        "first_year": first_year,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "targets": [
            {
                "symbol": target.symbol,
                "year": target.year,
                "instruments": [
                    {
                        "id": item.id,
                        "exchange": item.exchange,
                        "name": item.name,
                        "status": item.status,
                    }
                    for item in items
                ],
            }
            for target, items in targets.items()
        ],
    }
    _write_json(directory / PLAN, plan)
    years = Counter(target.year for target in targets)
    return {
        "status": "success",
        "targets": len(targets),
        "by_year": dict(sorted(years.items())),
        "plan": str(directory / PLAN),
    }


def read_plan(directory: Path) -> list[Target]:
    path = directory / PLAN
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        targets = [
            Target(str(item["symbol"]), int(item["year"])) for item in stored["targets"]
        ]
    except FileNotFoundError as exc:
        raise Refused(f"{path} does not exist: run filings plan first") from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise Refused(f"{path} is not a plan") from exc
    if any(target.year < FIRST_YEAR for target in targets):
        raise Refused(f"{path} asks for a year before {FIRST_YEAR}")
    return targets


# --- the directory --------------------------------------------------------------


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def read_manifest(directory: Path) -> dict[str, Any]:
    path = directory / MANIFEST
    if not path.exists():
        return {"pages": {}}
    stored = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(stored, dict) or not isinstance(stored.get("pages"), dict):
        raise Refused(f"{path} is not a manifest")
    return stored


def raw_name(target: Target) -> str:
    return f"{RAW_SUBDIR}/{target.symbol}/{target.roc_year}.json"


def stored_page(
    directory: Path, target: Target, manifest: dict[str, Any]
) -> bytes | None:
    """The stored envelope of TARGET when it is whole and still a page, else None.

    Whole: the manifest's sha256.  Still a page: ``classify`` passes it today, so a
    page an older rule stored and this one refuses (cut short, PR #1104 review
    suggestion) is asked again by the next fetch and not read by ``write``.
    """

    entry = manifest["pages"].get(target.key)
    if not entry:
        return None
    path = directory / entry["path"]
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
        return None
    try:
        stored, body = read_envelope(data)
    except (ValueError, KeyError, TypeError):
        return None
    if classify(stored.get("status"), body) is not None:
        return None
    return data


def _set_aside(directory: Path, target: Target, manifest: dict[str, Any]) -> None:
    """A stored file no longer taken as the page moves to ``FAILED_DIR``, never deleted."""

    entry = manifest["pages"].get(target.key)
    if not entry:
        return
    path = directory / entry["path"]
    if path.exists():
        kept = directory / FAILED_DIR / target.symbol
        kept.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        os.replace(path, kept / f"{target.roc_year}.{stamp}.stale.json")
    del manifest["pages"][target.key]
    _write_json(directory / MANIFEST, manifest)


def envelope(
    target: Target, status: int, content_type: str, body: bytes, fetched_at: datetime
) -> bytes:
    """The raw capture: the request, the answer's status and its bytes as sent."""

    return json.dumps(
        {
            "endpoint": ENDPOINT,
            "method": "POST",
            "form": request_form(target),
            "status": status,
            "content_type": content_type,
            "encoding": ENCODING,
            "fetched_at": fetched_at.astimezone(timezone.utc).isoformat(),
            "body_base64": base64.b64encode(body).decode("ascii"),
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")


def read_envelope(data: bytes) -> tuple[dict[str, Any], bytes]:
    stored = json.loads(data.decode("utf-8"))
    return stored, base64.b64decode(stored["body_base64"], validate=True)


# --- the page -------------------------------------------------------------------


@dataclass(frozen=True)
class FilingRow:
    symbol: str
    year: int
    quarter: int
    report_kind: str
    file_name: str
    file_size: int
    uploaded_at: datetime
    correction: str

    @property
    def period_end(self) -> date:
        return {
            1: date(self.year, 3, 31),
            2: date(self.year, 6, 30),
            3: date(self.year, 9, 30),
            4: date(self.year, 12, 31),
        }[self.quarter]


@dataclass(frozen=True)
class Page:
    """``company`` None and no rows: 「查無所需資料」, an answered empty year."""

    company: str | None
    rows: tuple[FilingRow, ...]


def decode(body: bytes) -> str:
    return body.decode(ENCODING, errors="replace")


def _cell_text(cell: str) -> str:
    return html.unescape(_TAG.sub("", cell)).replace("\xa0", " ").strip()


def classify(status: int | None, body: bytes) -> str | None:
    """Why a fetched answer is a failure; None for a page this stores.

    A stored page is the company table or 「查無所需資料」; the reader
    (``parse_page``) checks the rows later.
    """

    if status is None:
        return "no answer"
    if status in {403, 429}:
        return f"blocked: HTTP {status}"
    if status != 200:
        return f"HTTP {status}"
    if not body:
        return "empty answer"
    if len(body) > MAX_PAGE_BYTES:
        return f"answer over {MAX_PAGE_BYTES} bytes"
    text = decode(body)
    if RATE_LIMITED_TEXT in text:
        return "blocked: 查詢過量"
    if "setCoid(" in text:
        # A financial holding company's menu: check2858 was not honoured.
        return "unexpected: subsidiary menu"
    if _NAME.search(text):
        if tuple(_header(text) or ()) != HEADER:
            return "unexpected: no filing table"
        return None
    if NO_DATA_TEXT in text and "電子資料查詢作業" in text:
        return None
    return "unexpected page"


def _table(text: str) -> tuple[list[str], str] | None:
    """The filing table: its header cells and the HTML of its rows after the header.

    The first row of header cells starts it; it ends at the next ``</table>`` (the
    notes below the table are another table).  None without that end: an answer
    cut short would lose its last rows (PR #1104 review suggestion 2).
    """

    for match in _ROW.finditer(text):
        cells = _CELL.findall(match.group(1))
        if cells and all(kind.lower() == "h" for kind, _ in cells):
            rest = text[match.end() :]
            end = rest.lower().find("</table>")
            if end < 0:
                return None
            return [_cell_text(cell) for _, cell in cells], rest[:end]
    return None


def _header(text: str) -> list[str] | None:
    table = _table(text)
    return table[0] if table else None


def parse_page(body: bytes, target: Target) -> Page:
    """The rows of one stored page; raise LayoutError when it cannot be trusted."""

    reason = classify(200, body)
    if reason is not None:
        raise LayoutError(f"{target.key}: {reason}")
    text = decode(body)
    match = _NAME.search(text)
    if match is None:
        return Page(None, ())
    company = _cell_text(match.group(1))
    if not company or REPLACEMENT in company:
        raise LayoutError(f"{target.key}: unreadable company name {company!r}")
    table = _table(text)
    assert table is not None  # classify checked the header
    rows: list[FilingRow] = []
    for row in _ROW.findall(table[1]):
        cells = _CELL.findall(row)
        if not cells:
            continue
        if any(kind.lower() != "d" for kind, _ in cells) or len(cells) != len(HEADER):
            raise LayoutError(f"{target.key}: a row of {len(cells)} cells")
        rows.append(_row(target, [cell for _, cell in cells]))
    if not rows:
        raise LayoutError(f"{target.key}: a company table without rows")
    seen: dict[str, FilingRow] = {}
    for item in rows:
        other = seen.setdefault(item.file_name, item)
        if other != item:
            raise LayoutError(f"{target.key}: two rows of {item.file_name}")
    return Page(company, tuple(seen.values()))


def _row(target: Target, cells: list[str]) -> FilingRow:
    texts = [_cell_text(cell) for cell in cells]
    label = f"{target.key} {texts[7] or texts[1]}"
    if texts[0] != target.symbol:
        raise LayoutError(f"{label}: code {texts[0]!r}")
    year = _YEAR.fullmatch(texts[1])
    if year is None or int(year.group(1)) != target.roc_year:
        raise LayoutError(f"{label}: 資料年度 {texts[1]!r}")
    quarter = QUARTERS[year.group(2)]
    kind = texts[5]
    if not (
        IFRS_KIND.fullmatch(kind) or kind in SUPPLEMENTARY_KINDS or kind in OLD_KINDS
    ):
        raise LayoutError(f"{label}: unknown 資料細節說明 {kind!r}")
    file_match = _FILE.fullmatch(texts[7])
    if (
        file_match is None
        or int(file_match.group(1)) != target.year
        or int(file_match.group(2)) != quarter
    ):
        raise LayoutError(f"{label}: file name {texts[7]!r}")
    if not _SIZE.fullmatch(texts[8]):
        raise LayoutError(f"{label}: file size {texts[8]!r}")
    uploaded = _UPLOADED.fullmatch(texts[9])
    if uploaded is None:
        raise LayoutError(f"{label}: 上傳日期 {texts[9]!r}")
    try:
        uploaded_at = datetime(
            int(uploaded.group(1)) + 1911,
            *(int(part) for part in uploaded.groups()[1:]),
        )
    except ValueError as exc:
        raise LayoutError(f"{label}: 上傳日期 {texts[9]!r}") from exc
    link = _CORRECTION_LINK.search(cells[10])
    if link is not None:
        correction = html.unescape(link.group(1))
    elif texts[10] == "無":
        correction = "無"
    else:
        raise LayoutError(f"{label}: 財務報告更(補)正 {texts[10]!r}")
    return FilingRow(
        symbol=target.symbol,
        year=target.year,
        quarter=quarter,
        report_kind=kind,
        file_name=texts[7],
        file_size=int(texts[8].replace(",", "")),
        uploaded_at=uploaded_at,
        correction=correction,
    )


def is_chinese_ifrs(kind: str) -> bool:
    match = IFRS_KIND.fullmatch(kind)
    return match is not None and not match.group("english")


def filing_date(filings: Iterable[Any]) -> datetime | None:
    """A quarter's actual filing time: the earliest upload of its Chinese statements.

    FILINGS are one company's rows of one quarter (``FinancialReportFiling`` or
    ``FilingRow``).  Only ``FILING_DATE_KINDS`` count: the Chinese 合併, 個別 and 個體
    statements.  English versions, restatements (``(重編)``) and supplementary
    reports (關係企業合併報表, 外國企業實際營運地之個體財報) never do, even when
    uploaded earlier: the filing date stands for the quarter's own figures first
    made public (decision 7214693152 point 3).  None when there is none: no
    deadline or other source fills it.  The upload is usable after that day ends.
    """

    times = [row.uploaded_at for row in filings if row.report_kind in FILING_DATE_KINDS]
    return min(times) if times else None


def filing_dates(db: Session) -> dict[tuple[int, date], datetime]:
    """``filing_date`` of every instrument and quarter in ``financial_report_filings``."""

    grouped: dict[tuple[int, date], list[Any]] = defaultdict(list)
    # Only the four columns the rule reads, not ORM objects (about 150,000 rows).
    for row in db.execute(
        select(
            FinancialReportFiling.instrument_id,
            FinancialReportFiling.period_end,
            FinancialReportFiling.report_kind,
            FinancialReportFiling.uploaded_at,
        )
    ):
        grouped[(row.instrument_id, row.period_end)].append(row)
    result = {}
    for key, rows in grouped.items():
        moment = filing_date(rows)
        if moment is not None:
            result[key] = moment
    return result


# --- names ----------------------------------------------------------------------

_NAME_NOISE = re.compile(r"[\s　*＊]")
_NAME_PREFIX = re.compile(r"^F-")
_NAME_SUFFIX = re.compile(r"(?:-KY|-創)+$")
MIN_NAME_LENGTH = 2


def normalize_name(name: str) -> str:
    text = _NAME_NOISE.sub("", name)
    text = _NAME_PREFIX.sub("", text)
    return _NAME_SUFFIX.sub("", text)


def names_match(db_name: str, page_name: str) -> bool:
    """The same company name: equal, or one starting the other, once normalized.

    Each side must keep at least ``MIN_NAME_LENGTH`` characters (decision
    7214693152 point 4): 「台」 never matches 「台積電」.
    """

    left, right = normalize_name(db_name), normalize_name(page_name)
    if len(left) < MIN_NAME_LENGTH or len(right) < MIN_NAME_LENGTH:
        return False
    return left == right or left.startswith(right) or right.startswith(left)


def read_accepted_names(path: str | None) -> frozenset[tuple[str, str, str]]:
    """(code, page name, database name) a person checked; each with its reason."""

    if not path:
        return frozenset()
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, list):
        raise Refused(f"{path} is not a list")
    accepted = set()
    for item in loaded:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(name), str) and item[name].strip()
            for name in ("symbol", "page_name", "db_name", "reason")
        ):
            raise Refused(
                f"{path}: every item needs symbol, page_name, db_name and reason"
            )
        accepted.add((item["symbol"], item["page_name"], item["db_name"]))
    return frozenset(accepted)


# --- fetch ----------------------------------------------------------------------


def quiet_until(moment: datetime) -> datetime | None:
    """The end of the Taipei window MOMENT is in, when no request may start; else None."""

    local = moment.astimezone(TAIPEI)
    end: datetime | None = None
    for begin, finish in QUIET_HOURS:
        if begin <= local.time() < finish:
            end = local.replace(
                hour=finish.hour, minute=finish.minute, second=0, microsecond=0
            )
    hour = local.replace(minute=0, second=0, microsecond=0)
    for even in (hour, hour + timedelta(hours=1)):
        if even.hour % 2 == 0 and -EVEN_HOUR_MARGIN <= local - even < EVEN_HOUR_MARGIN:
            candidate = even + EVEN_HOUR_MARGIN
            end = candidate if end is None else max(end, candidate)
    return end


def next_allowed(moment: datetime) -> datetime:
    """MOMENT, or the first moment after it outside every quiet window."""

    current = moment
    while True:
        end = quiet_until(current)
        if end is None:
            return current
        current = end


def post_page(form: dict[str, str]) -> tuple[int, str, bytes]:
    """POST one page; (status, content type, body)."""

    sources._throttle_official_host(ENDPOINT)
    response = httpx.post(
        ENDPOINT,
        data=form,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    return (
        response.status_code,
        response.headers.get("content-type", ""),
        response.content,
    )


def fetch_pages(
    directory: Path,
    *,
    max_requests: int | None = None,
    getter: Callable[[dict[str, str]], tuple[int, str, bytes]] = post_page,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict[str, Any]:
    """Ask for the plan's pages not yet stored whole; never touches a database."""

    targets = read_plan(directory)
    manifest = read_manifest(directory)
    counts: Counter[str] = Counter()
    failed: dict[str, str] = {}
    failures_in_a_row = 0
    last_request: float | None = None
    last_success: str | None = manifest.get("last_success")
    stopped: str | None = None
    requests = 0
    for target in targets:
        if stored_page(directory, target, manifest) is not None:
            counts["kept"] += 1
            continue
        _set_aside(directory, target, manifest)
        if max_requests is not None and requests >= max_requests:
            stopped = f"max requests {max_requests} reached before {target.key}"
            break
        if last_request is not None:
            wait = REQUEST_INTERVAL_SECONDS - (clock() - last_request)
            if wait > 0:
                sleep(wait)
        moment = now()
        allowed = next_allowed(moment)
        if allowed > moment:
            sleep((allowed - moment).total_seconds())
            moment = now()
        last_request = clock()
        requests += 1
        status: int | None = None
        content_type = ""
        body = b""
        try:
            status, content_type, body = getter(request_form(target))
            reason = classify(status, body)
        except httpx.HTTPError as exc:
            reason = f"no answer: {exc.__class__.__name__}"
        record: dict[str, Any] = {
            "at": moment.astimezone(TAIPEI).isoformat(),
            "key": target.key,
            "form": request_form(target),
            "status": status,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        }
        if reason is None:
            data = envelope(target, status or 200, content_type, body, moment)
            path = directory / raw_name(target)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
            temporary.write_bytes(data)
            os.replace(temporary, path)
            kind = "no_data" if _NAME.search(decode(body)) is None else "filings"
            manifest["pages"][target.key] = {
                "path": raw_name(target),
                "sha256": hashlib.sha256(data).hexdigest(),
                "kind": kind,
                "fetched_at": moment.astimezone(timezone.utc).isoformat(),
            }
            manifest["last_success"] = last_success = target.key
            _write_json(directory / MANIFEST, manifest)
            counts[kind] += 1
            failures_in_a_row = 0
        else:
            failures_in_a_row += 1
            failed[target.key] = reason
            record["error"] = reason
            if body:
                kept = directory / FAILED_DIR / target.symbol
                kept.mkdir(parents=True, exist_ok=True)
                name = f"{target.roc_year}.{moment.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}.body"
                (kept / name).write_bytes(body)
                record["body"] = f"{FAILED_DIR}/{target.symbol}/{name}"
        with (directory / REQUESTS).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        if failures_in_a_row >= ABORT_AFTER_FAILURES:
            stopped = (
                f"{failures_in_a_row} failed requests in a row at {target.key} "
                f"({reason}); last success {last_success}; 停下來回報，不加長間隔續跑"
            )
            break
    remaining = sum(1 for target in targets if target.key not in manifest["pages"])
    if stopped and failures_in_a_row >= ABORT_AFTER_FAILURES:
        status_text = "failed"
    elif stopped or failed or remaining:
        status_text = "partial"
    else:
        status_text = "success"
    return {
        "status": status_text,
        "targets": len(targets),
        "requests": requests,
        "counts": dict(counts),
        "failed": failed,
        "remaining": remaining,
        "last_success": last_success,
        "stopped": stopped,
    }


# --- write ----------------------------------------------------------------------


@dataclass
class WriteCounts:
    targets: int = 0
    not_fetched: int = 0
    no_data: int = 0
    pages: int = 0
    page_failed: int = 0
    name_mismatch: int = 0
    rows: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    old_kind_rows: int = 0
    old_layout_quarters: int = 0
    unassigned_rows: int = 0
    lists: dict[str, list[Any]] = field(
        default_factory=lambda: {
            "not_fetched": [],
            "no_data": [],
            "page_failed": [],
            "name_mismatch": [],
            "old_layout": [],
            "unassigned": [],
        }
    )

    def add(self, other: WriteCounts) -> None:
        for name, value in vars(other).items():
            if name == "lists":
                for key, items in value.items():
                    self.lists[key].extend(items)
            else:
                setattr(self, name, getattr(self, name) + value)


def _raw_row(
    db: Session, run: IngestionRun, target: Target, data: bytes, fetched_at: datetime
) -> RawPayload:
    """The page's raw_payloads row, the envelope copied into the raw directory."""

    digest = hashlib.sha256(data).hexdigest()
    endpoint = request_endpoint(target)
    row = db.scalar(
        select(RawPayload)
        .where(
            RawPayload.source == RAW_SOURCE,
            RawPayload.endpoint == endpoint,
            RawPayload.sha256 == digest,
        )
        .order_by(RawPayload.id)
        .limit(1)
    )
    target_path = (
        sources.RAW_DIR
        / RAW_SOURCE
        / fetched_at.strftime("%Y/%m/%d")
        / f"{digest}.json"
    )
    if row is not None and row.payload_path:
        target_path = payload_file(row.payload_path)
    state = sources.ensure_raw_file(
        target_path,
        data,
        {
            "source": RAW_SOURCE,
            "endpoint": endpoint,
            "sha256": digest,
            "data_as_of": _taipei_day(fetched_at).isoformat(),
            "collected_at": fetched_at.isoformat(),
        },
    )
    if state not in (None, sources.RAW_MISSING):
        sources.warn_raw(f"raw page {target_path} was {state}; rewrote it")
    if row is not None:
        return row
    row = RawPayload(
        ingestion_run_id=run.id,
        source=RAW_SOURCE,
        endpoint=endpoint,
        payload_path=str(target_path),
        sha256=digest,
        data_as_of=_taipei_day(fetched_at).isoformat(),
        collected_at=fetched_at.astimezone(timezone.utc).replace(tzinfo=None),
    )
    db.add(row)
    db.flush()
    return row


def _taipei_day(moment: datetime) -> date:
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return aware.astimezone(TAIPEI).date()


def _assign(
    quarter: int, instruments: list[TargetInstrument]
) -> TargetInstrument | None:
    """The instrument a quarter's rows belong to: the one with that quarter, else the only one."""

    having = [item for item in instruments if quarter in item.quarters]
    if len(having) == 1:
        return having[0]
    if not having and len(instruments) == 1:
        return instruments[0]
    return None


def write_target(
    db: Session,
    run: IngestionRun | None,
    target: Target,
    instruments: list[TargetInstrument],
    data: bytes,
    counts: WriteCounts,
    accepted: frozenset[tuple[str, str, str]],
) -> None:
    """Write one stored page; RUN None is a dry run.  LayoutError leaves nothing written."""

    stored, body = read_envelope(data)
    fetched_at = datetime.fromisoformat(stored["fetched_at"])
    page = parse_page(body, target)
    if page.company is None:
        counts.no_data += 1
        counts.lists["no_data"].append(target.key)
        return
    counts.pages += 1
    matched = []
    for item in instruments:
        if names_match(item.name, page.company) or (
            (target.symbol, page.company, item.name) in accepted
        ):
            matched.append(item)
        else:
            counts.name_mismatch += 1
            counts.lists["name_mismatch"].append(
                {
                    "key": target.key,
                    "instrument_id": item.id,
                    "status": item.status,
                    "db_name": item.name,
                    "page_name": page.company,
                }
            )
    if not matched:
        return
    by_quarter: dict[int, list[FilingRow]] = defaultdict(list)
    for row in page.rows:
        by_quarter[row.quarter].append(row)
    raw: RawPayload | None = None
    for quarter, rows in sorted(by_quarter.items()):
        old = [row for row in rows if row.report_kind in OLD_KINDS]
        kept = [row for row in rows if row.report_kind not in OLD_KINDS]
        counts.old_kind_rows += len(old)
        if old and not any(is_chinese_ifrs(row.report_kind) for row in kept):
            counts.old_layout_quarters += 1
            counts.lists["old_layout"].append(f"{target.key}Q{quarter}")
            continue
        # Every instrument of the code decides whose quarter it is; one whose name
        # does not match is listed in name_mismatch and gets nothing, and its
        # quarters never move to the other instrument (PR #1104 review 1).
        owner = _assign(quarter, instruments)
        if owner is None:
            counts.unassigned_rows += len(kept)
            counts.lists["unassigned"].append(f"{target.key}Q{quarter}")
            continue
        if owner not in matched:
            continue
        for row in kept:
            counts.rows += 1
            if run is None:
                continue
            if raw is None:
                raw = _raw_row(db, run, target, data, fetched_at)
            _upsert(db, owner.id, row, raw, fetched_at, counts)


def _upsert(
    db: Session,
    instrument_id: int,
    row: FilingRow,
    raw: RawPayload,
    fetched_at: datetime,
    counts: WriteCounts,
) -> None:
    values = {
        "period_end": row.period_end,
        "fiscal_period": f"Q{row.quarter}",
        "report_kind": row.report_kind,
        "uploaded_at": row.uploaded_at,
        "file_size": row.file_size,
        "correction": row.correction,
        "source": SOURCE,
    }
    existing = db.scalar(
        select(FinancialReportFiling).where(
            FinancialReportFiling.instrument_id == instrument_id,
            FinancialReportFiling.file_name == row.file_name,
        )
    )
    if existing is not None and all(
        getattr(existing, name) == value for name, value in values.items()
    ):
        counts.unchanged += 1
        return
    provenance = {
        "data_as_of": _taipei_day(fetched_at),
        "raw_payload_id": raw.id,
        "collected_at": fetched_at.astimezone(timezone.utc).replace(tzinfo=None),
    }
    if existing is None:
        db.add(
            FinancialReportFiling(
                instrument_id=instrument_id,
                file_name=row.file_name,
                **values,
                **provenance,
            )
        )
        counts.inserted += 1
        return
    for name, value in (values | provenance).items():
        setattr(existing, name, value)
    counts.updated += 1


COMMIT_EVERY = 200


def write_filings(
    db: Session,
    directory: Path,
    *,
    dry_run: bool = False,
    accepted: frozenset[tuple[str, str, str]] = frozenset(),
) -> dict[str, Any]:
    """Write every stored page of the database's targets; reruns change nothing."""

    manifest = read_manifest(directory)
    targets = plan_targets(db)
    run: IngestionRun | None = None
    if not dry_run:
        started = utcnow()
        run = IngestionRun(
            run_type=RUN_TYPE,
            source="official",
            run_date=_taipei_day(started),
            status="running",
            started_at=started,
            metadata_json={
                "directory": str(directory),
                "accepted_names": len(accepted),
            },
        )
        db.add(run)
        db.commit()
    counts = WriteCounts()
    try:
        for index, (target, instruments) in enumerate(targets.items(), start=1):
            counts.targets += 1
            data = stored_page(directory, target, manifest)
            if data is None:
                counts.not_fetched += 1
                counts.lists["not_fetched"].append(target.key)
                continue
            local = WriteCounts()
            try:
                with db.begin_nested():
                    write_target(db, run, target, instruments, data, local, accepted)
            except (LayoutError, ValueError, KeyError) as exc:
                # Nothing of the page is written, nor counted.
                counts.page_failed += 1
                counts.lists["page_failed"].append(
                    {"key": target.key, "error": str(exc)}
                )
            else:
                counts.add(local)
            if run is not None and index % COMMIT_EVERY == 0:
                db.commit()
    except Exception as exc:
        db.rollback()
        if run is not None:
            run.status = "failed"
            run.error = f"error: {exc!r}"
            run.finished_at = utcnow()
            db.commit()
        raise
    summary = _summary(counts)
    if run is not None:
        run.status = "success"
        run.records = counts.inserted + counts.updated
        run.finished_at = utcnow()
        run.metadata_json = {**run.metadata_json, "summary": summary}
        db.commit()
    return {
        "status": "success",
        "dry_run": dry_run,
        "run_id": run.id if run is not None else None,
        **summary,
    }


def _summary(counts: WriteCounts) -> dict[str, Any]:
    totals = {name: value for name, value in vars(counts).items() if name != "lists"}
    lists = dict(counts.lists)
    # The not-fetched keys can be thousands before the fetch ends.
    lists["not_fetched"] = lists["not_fetched"][:50]
    return {"counts": totals, "lists": lists}


# --- coverage -------------------------------------------------------------------


def coverage(db: Session, first_year: int = FIRST_YEAR) -> dict[str, Any]:
    """By year and instrument status: companies and quarters with a filing date.

    The quarters are the ``fundamental_snapshots`` ones; a quarter is covered when
    ``filing_date`` gives it a time.
    """

    dates = filing_dates(db)
    rows = db.execute(
        select(
            FundamentalSnapshot.instrument_id,
            FundamentalSnapshot.period_end,
            Instrument.status,
        )
        .join(Instrument, Instrument.id == FundamentalSnapshot.instrument_id)
        .where(FundamentalSnapshot.period_end >= date(first_year, 1, 1))
    ).all()
    table: dict[tuple[int, str], dict[str, Any]] = {}
    missing: dict[tuple[int, str], list[int]] = defaultdict(list)
    for iid, period_end, status in rows:
        if _quarter_of(period_end) is None:
            continue
        cell = table.setdefault(
            (period_end.year, status),
            {
                "companies": set(),
                "covered_companies": set(),
                "quarters": 0,
                "covered": 0,
            },
        )
        cell["companies"].add(iid)
        cell["quarters"] += 1
        if (iid, period_end) in dates:
            cell["covered"] += 1
            cell["covered_companies"].add(iid)
    result = []
    for (year, status), cell in sorted(table.items()):
        missing_ids = sorted(cell["companies"] - cell["covered_companies"])
        missing[(year, status)] = missing_ids
        result.append(
            {
                "year": year,
                "status": status,
                "companies": len(cell["companies"]),
                "companies_with_filing": len(cell["covered_companies"]),
                "quarters": cell["quarters"],
                "quarters_with_filing": cell["covered"],
                "quarter_coverage": round(cell["covered"] / cell["quarters"], 4),
                "companies_without_filing": missing_ids,
            }
        )
    return {"status": "success", "source": SOURCE, "by_year_status": result}


# --- commands -------------------------------------------------------------------


def run_plan(directory: str) -> dict[str, Any]:
    with SessionLocal() as db:
        return write_plan(Path(directory), db)


def run_fetch(directory: str, max_requests: int | None = None) -> dict[str, Any]:
    try:
        return fetch_pages(Path(directory), max_requests=max_requests)
    except Refused as exc:
        return {"status": "failed", "error": str(exc)}


def run_write(
    directory: str, *, dry_run: bool = False, accept_names: str | None = None
) -> dict[str, Any]:
    try:
        accepted = read_accepted_names(accept_names)
        manifest_dir = Path(directory)
        read_manifest(manifest_dir)
    except (Refused, ValueError, OSError) as exc:
        return {"status": "failed", "error": str(exc)}
    with SessionLocal() as db:
        return write_filings(db, manifest_dir, dry_run=dry_run, accepted=accepted)


def run_coverage() -> dict[str, Any]:
    with SessionLocal() as db:
        return coverage(db)
