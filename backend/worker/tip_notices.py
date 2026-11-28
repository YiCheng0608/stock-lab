"""臺灣50 and 臺灣中型100 constituent changes of the research database (Issue #1149).

The ``tip-notices`` feed of ``valuation backfill`` (#1130 decision 7233275054, #1
decision 7235997024): Taiwan Index Plus (臺灣指數公司, TIP) technical notices
(技術通知), the only free official record of the two indexes' changes; no whole
constituent list is published.  A module of its own: the feed reads a yearly HTML
list and then one Word ``.doc`` or PDF per notice, not one JSON table a session.
It keeps ``worker.valuation_backfill``'s manifest, pacing and quiet hours.

1. The Chinese list of each year from ``FIRST_YEAR`` (``LIST_URL``), one request a
   year: the desktop table's 檔案日期, 檔案名稱, 檔案類別 and link.  A year whose list
   was taken after the year ended is not asked again; the current one is.
2. The notices are picked by title (``notice_kind``), not by category: two periodic
   reviews (2017-12-02, 2018-03-02) are filed as 其他.
3. Each picked notice's ``/tw`` file (``FILE_URL``), one request: the text of a
   Word 97 ``.doc`` (``olefile``, the piece table read here) or of a PDF (``pypdf``,
   ``extraction_mode="layout"``), then ``parse_notice``.  Only the 臺灣50 and
   臺灣中型100 sections are written; the other indexes and the free float changes
   of a notice are not.

A notice is written whole or not at all: a periodic review must have a section for
each of the two indexes its first paragraph names, each with its additions and
deletions (``無`` is none) and as many additions as deletions; a line of a section
that does not read, a code twice, a date that does not read or an announcement date
more than ``MAX_SITE_DAYS`` from the site's date fails it, and it is left for manual
reading.  An ad hoc notice is written when it has the same sections (no count check
when it defers, ``延期``: those rows have no effective date); one that names neither
index is a success without rows (share counts, free float, other indexes); one that
names an index next to an addition or deletion in any other layout fails, for
manual reading.

``announced_date`` is the first date of the text and ``site_file_date`` the list's;
a research tool uses a notice from the session after the later of the two
(decision item 4).  ``effective_date`` is the one written (``亦即自…起生效``), a
holiday kept.  ``instrument_id`` is the research DB's TWSE instrument with a bar of
the code on the last session up to the announcement; a code without one is counted
(``unmatched``), never created.

Manifest: one ``ingestion_runs`` row a list year and a notice
(``valuation_backfill:tip-notices:list:<year>``, ``…:tip-notices:<id>``).  A notice
already ``success`` is not asked again; one whose file came but did not read is
read again from its raw without a request, as ``reapply`` does for all of them
(no request at all).  The raw of each answer is a JSON wrapper of its bytes
(``wrap_body``), as raw files are JSON or zip.  Requests: at least
``REQUEST_INTERVAL_SECONDS`` apart on a host, none between ``QUIET_START`` and
``QUIET_END`` Taipei nor within ``EVEN_HOUR_MARGIN`` of an even hour (news), and
``ABORT_AFTER_FAILURES`` failed requests in a row to a host stop the run.
"""

from __future__ import annotations

import base64
import hashlib
import html
import io
import re
import struct
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlsplit

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.models import (
    IndexConstituentChange,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
)
from worker import pipeline, sources
from worker.sources import OfficialDataError
from worker.valuation_backfill import (
    ABORT_AFTER_FAILURES,
    BAR_TYPES,
    DAY_RUN_TYPE,
    MAX_LISTED,
    QUIET_END,
    QUIET_START,
    REQUEST_INTERVAL_SECONDS,
    TAIPEI,
    in_quiet_hours,
    read_raw,
    seconds_to_quiet_end,
)

FEED = "tip-notices"
SOURCE = "tip_technical_notice"
RAW_SOURCE = "tip"  # raw_payloads.source and the raw directory
LIST_URL = (
    "https://taiwanindex.com.tw/downloads/technical_notice?page=1&year={year}&count=500"
)
LIST_COUNT = 500
FILE_URL = (
    "https://backend.taiwanindex.com.tw/api/downloadFile/TechnicalNotices/{id}/tw"
)
_FILE_ID = re.compile(
    r"https://backend\.taiwanindex\.com\.tw/api/downloadFile/TechnicalNotices/(\d+)/tw"
)
# 臺灣50 was launched 2002-10-29; the list's first notice is 2002-11-07 (#1130).
FIRST_YEAR = 2002
REQUEST_KEY = "valuation_backfill:tip-notices:{key}"
# The news runs on the even hours (docs/ops/SCHEDULING.md).
EVEN_HOUR_MARGIN = timedelta(minutes=10)
# The site's date was the text's or a day later in the #1130 samples.
MAX_SITE_DAYS = 7
# The samples took 5 to 10 sessions from announcement to effect.
MAX_EFFECTIVE_DAYS = 90

INDEXES = {"臺灣50指數": "TW50", "臺灣中型100指數": "TWMC100"}
# Every section heading of a review notice; any ends the one before.
SECTION_NAMES = frozenset(
    {
        *INDEXES,
        "臺灣資訊科技指數",
        "臺灣發達指數",
        "臺灣高股息指數",
        "公眾流通量調整",
    }
)
ACTIONS = ("add", "delete", "reserve")

LIST_COLUMNS = ("檔案日期", "檔案名稱", "檔案類別", "連結")


class NoticeError(OfficialDataError):
    """The notice (or list) is not one this reads; nothing of it is written."""


# --- the list ------------------------------------------------------------------


@dataclass(frozen=True)
class ListedNotice:
    doc_id: str
    site_date: date
    title: str
    category: str
    url: str


def _cell(fragment: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", text).strip()


def parse_list(page: str, year: int) -> list[ListedNotice]:
    """The rows of a year's list page (the desktop table, ``d-lg-table``)."""

    tables = re.findall(
        r'<table class="[^"]*\bd-lg-table\b[^"]*"[^>]*>(.*?)</table>', page, re.S
    )
    if len(tables) != 1:
        raise NoticeError(f"{len(tables)} list tables, expected 1")
    table = tables[0]
    head = re.search(r"<thead[^>]*>(.*?)</thead>", table, re.S)
    columns = tuple(
        _cell(th)
        for th in re.findall(
            r"<th[^>]*>(.*?)</th>", head.group(1) if head else "", re.S
        )
    )
    if columns != LIST_COLUMNS:
        raise NoticeError(f"unknown list columns {columns!r}")
    body = re.search(r"<tbody[^>]*>(.*?)</tbody>", table, re.S)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", body.group(1) if body else "", re.S)
    if len(rows) >= LIST_COUNT:
        raise NoticeError(f"{len(rows)} rows: the list may be cut at {LIST_COUNT}")
    listed: list[ListedNotice] = []
    seen: set[str] = set()
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) != len(LIST_COLUMNS):
            raise NoticeError(f"a list row of {len(cells)} cells")
        text = [_cell(c) for c in cells]
        try:
            site_date = datetime.strptime(text[0], "%Y/%m/%d").date()
        except ValueError as exc:
            raise NoticeError(f"unreadable list date {text[0]!r}") from exc
        if site_date.year != year:
            raise NoticeError(f"list of {year} has a row of {site_date}")
        link = re.search(r'href="([^"]+)"', cells[3])
        url = html.unescape(link.group(1)) if link else ""
        match = _FILE_ID.fullmatch(url)
        if not match:
            # Not a Chinese file of the notices: kept out, counted by the run.
            listed.append(ListedNotice("", site_date, text[1], text[2], url))
            continue
        if match.group(1) in seen:
            raise NoticeError(f"notice {match.group(1)} is listed twice")
        seen.add(match.group(1))
        listed.append(ListedNotice(match.group(1), site_date, text[1], text[2], url))
    return listed


_SERIES = re.compile(r"臺灣指數系列|臺灣50指數|臺灣中型100指數")
_REVIEW = re.compile(r"審核")
_NOT_A_REVIEW = re.compile(r"規則|期程|日程|時間")


def notice_kind(title: str, category: str) -> str | None:
    """``periodic``, ``ad_hoc`` or None (not of 臺灣50 or 中型100), by the title.

    The category is not read for a review: 2017-12-02 and 2018-03-02 are 其他.  An
    ad hoc notice is any other of the series filed as 其他 (rules, schedules and
    the TIP indexes are not the series).
    """

    flat = re.sub(r"\s+", "", title)
    if not _SERIES.search(flat):
        return None
    if _REVIEW.search(flat) and not _NOT_A_REVIEW.search(flat):
        return "periodic"
    if category == "其他" and not re.search(r"規則", flat):
        return "ad_hoc"
    return None


# --- raw ------------------------------------------------------------------------


def wrap_body(url: str, body: bytes) -> dict[str, Any]:
    return {
        "url": url,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "base64": base64.b64encode(body).decode("ascii"),
    }


def unwrap_body(payload: Any) -> bytes:
    if not isinstance(payload, dict) or not isinstance(payload.get("base64"), str):
        raise NoticeError("the raw is not a wrapped file")
    try:
        body = base64.b64decode(payload["base64"], validate=True)
    except ValueError as exc:
        raise NoticeError("the raw's base64 does not read") from exc
    if hashlib.sha256(body).hexdigest() != payload.get("sha256"):
        raise NoticeError("the raw's body is not its sha256")
    return body


# --- text of a file ---------------------------------------------------------------

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
WORD_IDENT = 0xA5EC
# FibRgFcLcb97 pair 33 (fcClx, lcbClx); FibRgLw97 item 3 (ccpText).
FC_CLX_PAIR = 33
CCP_TEXT_ITEM = 3
_COMPRESSED = 0x40000000


def doc_text(data: bytes) -> str:
    """The main text of a Word 97-2003 ``.doc`` through its piece table ([MS-DOC])."""

    import olefile

    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
    except Exception as exc:  # a damaged file of the source, never a crash
        raise NoticeError(f"not an OLE file: {exc}") from exc
    try:
        if not ole.exists("WordDocument"):
            raise NoticeError("no WordDocument stream")
        word = ole.openstream("WordDocument").read()
        if len(word) < 34 or struct.unpack_from("<H", word, 0)[0] != WORD_IDENT:
            raise NoticeError("not a Word 97 document")
        flags = struct.unpack_from("<H", word, 0x0A)[0]
        if flags & 0x0100:
            raise NoticeError("the document is encrypted")
        table_name = "1Table" if flags & 0x0200 else "0Table"
        if not ole.exists(table_name):
            raise NoticeError(f"no {table_name} stream")
        table = ole.openstream(table_name).read()
    except NoticeError:
        raise
    except Exception as exc:
        raise NoticeError(f"unreadable OLE streams: {exc}") from exc
    finally:
        ole.close()
    try:
        at = 32
        csw = struct.unpack_from("<H", word, at)[0]
        at += 2 + csw * 2
        cslw = struct.unpack_from("<H", word, at)[0]
        if cslw <= CCP_TEXT_ITEM:
            raise NoticeError("the FIB has no ccpText")
        ccp_text = struct.unpack_from("<i", word, at + 2 + CCP_TEXT_ITEM * 4)[0]
        at += 2 + cslw * 4
        pairs = struct.unpack_from("<H", word, at)[0]
        if pairs <= FC_CLX_PAIR:
            raise NoticeError("the FIB has no CLX")
        fc_clx, lcb_clx = struct.unpack_from("<II", word, at + 2 + FC_CLX_PAIR * 8)
    except struct.error as exc:
        raise NoticeError("the FIB is cut short") from exc
    clx = table[fc_clx : fc_clx + lcb_clx]
    if lcb_clx == 0 or len(clx) != lcb_clx:
        raise NoticeError("the CLX is outside the table stream")
    i = 0
    # RgPrc: property modifiers (clxt 1), skipped.
    while i < len(clx) and clx[i] == 1:
        if i + 3 > len(clx):
            raise NoticeError("the CLX does not read")
        i += 3 + struct.unpack_from("<H", clx, i + 1)[0]
    if i + 5 > len(clx) or clx[i] != 2:
        raise NoticeError("the CLX has no piece table")
    size = struct.unpack_from("<I", clx, i + 1)[0]
    plc = clx[i + 5 : i + 5 + size]
    if len(plc) != size or (size - 4) % 12 or size < 16:
        raise NoticeError("the piece table does not read")
    pieces = (size - 4) // 12
    cps = struct.unpack_from(f"<{pieces + 1}I", plc, 0)
    if cps[0] != 0 or any(b < a for a, b in zip(cps, cps[1:])):
        raise NoticeError("the piece table's positions do not read")
    parts = []
    for k in range(pieces):
        fc = struct.unpack_from("<I", plc, (pieces + 1) * 4 + k * 8 + 2)[0]
        length = cps[k + 1] - cps[k]
        if fc & _COMPRESSED:
            start = (fc & ~_COMPRESSED) // 2
            chunk = word[start : start + length]
            if len(chunk) != length:
                raise NoticeError("a piece is outside the document")
            parts.append(chunk.decode("cp1252", errors="replace"))
        else:
            chunk = word[fc : fc + 2 * length]
            if len(chunk) != 2 * length:
                raise NoticeError("a piece is outside the document")
            parts.append(chunk.decode("utf-16-le", errors="replace"))
    text = "".join(parts)
    if 0 < ccp_text <= len(text):
        text = text[:ccp_text]
    return _word_controls(text)


def _word_controls(text: str) -> str:
    # A field keeps its result: drop from the begin mark (0x13) to the separator
    # (0x14), and the end mark (0x15).
    text = re.sub("\x13[^\x13\x14\x15]*\x14", "", text)
    text = re.sub("\x13[^\x13\x14\x15]*\x15", "", text)
    text = text.replace("\x15", "")
    for mark in ("\r", "\x07", "\x0b", "\x0c"):
        text = text.replace(mark, "\n")
    text = text.replace("\x1e", "-").replace("\x1f", "")
    return re.sub("[\x00-\x08\x0e-\x1f]", "", text)


def pdf_text(data: bytes) -> str:
    import pypdf

    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise NoticeError("the PDF is encrypted")
        return "\n".join(
            page.extract_text(extraction_mode="layout") for page in reader.pages
        )
    except NoticeError:
        raise
    except Exception as exc:  # a damaged file of the source, never a crash
        raise NoticeError(f"unreadable PDF: {exc}") from exc


def file_text(data: bytes) -> tuple[str, str]:
    """(format, text) of a notice file: ``doc`` or ``pdf``."""

    if data.startswith(OLE_MAGIC):
        return "doc", doc_text(data)
    if data.startswith(b"%PDF"):
        return "pdf", pdf_text(data)
    raise NoticeError(f"not a .doc or PDF file: {data[:8]!r}")


# --- the notice -------------------------------------------------------------------


@dataclass(frozen=True)
class Entry:
    symbol: str
    name: str
    free_float_pct: float | None


@dataclass
class ParsedNotice:
    announced: date
    effective: date | None
    # {index code: {action: entries}}; only the two indexes.
    sections: dict[str, dict[str, list[Entry]]] = field(default_factory=dict)
    deferred: bool = False


_DATE = re.compile(r"(?<!\d)(\d{4}|\d{2,3})年(\d{1,2})月(\d{1,2})日")
_EFFECTIVE = re.compile(
    r"亦即自((?:(?:\d{4}|\d{2,3})年)?\d{1,2}月\d{1,2}日)(?:[（(][^）)]*[）)])?起?生效"
)
_AD_HOC_EFFECTIVE = re.compile(
    r"自((?:(?:\d{4}|\d{2,3})年)?\d{1,2}月\d{1,2}日)(?:[（(][^）)]*[）)])?起生效"
)
_PART_DATE = re.compile(r"(?:(\d{4}|\d{2,3})年)?(\d{1,2})月(\d{1,2})日")
_NUMBERING = re.compile(
    r"^(?:[一二三四五六七八九十]+[、.．]|[（(][一二三四五六七八九十\d]+[）)]|\d+[.、．])"
)
# Only these number a section; ``(一)`` and ``1.`` number lines inside one.
_SECTION_NUMBER = re.compile(r"^[一二三四五六七八九十]+[、.．]")
_PART = re.compile(
    r"^(?:成[分份]股)?(納入|刪除|剔除|候補名單|候補)(?:成[分份]股)?[：:]?"
)
_FREE_FLOAT = re.compile(r"公眾流通量(?:係數)?\s*為\s*([\d.]+)\s*%")
_CODE = r"\d{4,6}[A-Z]?"
_CODE_FIRST = re.compile(rf"^({_CODE})\s*(\D.*?)$")
_NAME_FIRST = re.compile(rf"^(.*?\D)\s*({_CODE})$")
_MENTIONS_INDEX = re.compile(r"臺灣50|中型100")
_MEMBERSHIP = re.compile(r"納入|刪除|剔除|遞補")
_NONE = "無"


def _year(text: str) -> int:
    value = int(text)
    if len(text) == 4:
        if not 1990 <= value <= 2100:
            raise NoticeError(f"unreadable year {text}")
        return value
    if not 80 <= value <= 200:
        raise NoticeError(f"unreadable year {text}")
    return value + 1911


def _make_date(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise NoticeError(f"unreadable date {year}-{month}-{day}") from exc


def _effective(flat: str, announced: date, kind: str) -> date | None:
    match = _EFFECTIVE.search(flat)
    if match is None and kind == "ad_hoc":
        match = _AD_HOC_EFFECTIVE.search(flat)
    if match is None:
        return None
    part = _PART_DATE.fullmatch(match.group(1))
    if part is None:
        raise NoticeError(f"unreadable effective date {match.group(1)!r}")
    month, day = int(part.group(2)), int(part.group(3))
    if part.group(1):
        year = _year(part.group(1))
    else:
        year = announced.year + (1 if month < announced.month else 0)
    effective = _make_date(year, month, day)
    if not announced <= effective <= announced + timedelta(days=MAX_EFFECTIVE_DAYS):
        raise NoticeError(f"effective date {effective} is far from {announced}")
    return effective


def _normalize(text: str) -> list[str]:
    text = text.replace("　", " ").replace("\xa0", " ").replace("\t", " ")
    return [line.rstrip() for line in text.splitlines()]


def _heading(line: str) -> str | None:
    """The section a heading line opens, ``""`` for a numbered unknown one."""

    flat = re.sub(r"\s+", "", line)
    numbered = _NUMBERING.match(flat)
    name = flat[numbered.end() :] if numbered else flat
    name = name.rstrip("：:")
    if name in SECTION_NAMES:
        return name
    if _SECTION_NUMBER.match(flat):
        return ""
    return None


def _entry(line: str) -> Entry:
    ratio = None
    ratios = _FREE_FLOAT.findall(line)
    if len(ratios) > 1:
        raise NoticeError(f"two free floats in {line.strip()!r}")
    if ratios:
        try:
            ratio = float(ratios[0])
        except ValueError as exc:
            raise NoticeError(f"unreadable free float in {line.strip()!r}") from exc
        if not 0 < ratio <= 100:
            raise NoticeError(f"free float {ratio} in {line.strip()!r}")
    rest = _FREE_FLOAT.sub(" ", line)
    rest = re.sub(r"[，,、；;]", " ", rest)
    rest = re.sub(r"\s+", " ", rest).strip()
    match = _CODE_FIRST.fullmatch(rest)
    if match:
        symbol, name = match.group(1), match.group(2)
    else:
        match = _NAME_FIRST.fullmatch(rest)
        if not match:
            raise NoticeError(f"unreadable line {line.strip()!r}")
        name, symbol = match.group(1), match.group(2)
    name = name.strip()
    if not name or re.search(rf"(?<!\d){_CODE}(?!\d)", name):
        raise NoticeError(f"unreadable line {line.strip()!r}")
    return Entry(symbol, name, ratio)


def _sections(lines: list[str]) -> tuple[int, dict[str, dict[str, list[Entry] | None]]]:
    """(index of the first heading, {index code: {action: entries, None if absent}})."""

    first = len(lines)
    found: dict[str, dict[str, list[Entry] | None]] = {}
    current: dict[str, list[Entry] | None] | None = None
    action: str | None = None
    # (index, action) written as 無.
    none: set[tuple[str, str]] = set()
    code = ""
    for at, line in enumerate(lines):
        if not line.strip():
            continue
        heading = _heading(line)
        if heading is not None:
            first = min(first, at)
            action = None
            if heading in INDEXES:
                code = INDEXES[heading]
                if code in found:
                    raise NoticeError(f"{heading} appears twice")
                current = found[code] = dict.fromkeys(ACTIONS)
            else:
                current = None
            continue
        if current is None:
            continue
        flat = _NUMBERING.sub("", re.sub(r"\s+", "", line))
        part = _PART.match(flat)
        content = line
        if part:
            word = part.group(1)
            action = {"納入": "add", "刪除": "delete", "剔除": "delete"}.get(
                word, "reserve"
            )
            if current[action] is not None:
                raise NoticeError(f"{code} {word} appears twice")
            current[action] = []
            # What follows the heading on its line (``成分股刪除：無``).
            colon = re.search(r"[：:]", line)
            content = line[colon.end() :] if colon else ""
            if not content.strip():
                continue
        if action is None:
            raise NoticeError(f"a line before any part: {line.strip()!r}")
        entries = current[action]
        assert entries is not None
        if (code, action) in none:
            raise NoticeError(f"{code} {action}: a line after {_NONE}")
        if content.strip() == _NONE:
            if entries:
                raise NoticeError(f"{code} {action}: {_NONE} after entries")
            none.add((code, action))
            continue
        entries.append(_entry(content))
    return first, found


def parse_notice(text: str, kind: str, site_date: date) -> ParsedNotice:
    lines = _normalize(text)
    flat = re.sub(r"\s+", "", "\n".join(lines))
    first_date = _DATE.search(flat)
    if first_date is None:
        raise NoticeError("no date in the notice")
    announced = _make_date(
        _year(first_date.group(1)), int(first_date.group(2)), int(first_date.group(3))
    )
    if abs((site_date - announced).days) > MAX_SITE_DAYS:
        raise NoticeError(f"announced {announced} but listed {site_date}")
    effective = _effective(flat, announced, kind)
    first, found = _sections(lines)
    intro = re.sub(r"\s+", "", "\n".join(lines[:first]))
    deferred = "延期" in flat
    for code, parts in found.items():
        for name, entries in parts.items():
            symbols = [e.symbol for e in entries or []]
            if len(symbols) != len(set(symbols)):
                raise NoticeError(f"a code twice in {code} {name}")
    if kind == "periodic":
        if effective is None:
            raise NoticeError("a review without an effective date")
        expected = {code for heading, code in INDEXES.items() if heading in intro}
        if not expected:
            raise NoticeError("the review names neither 臺灣50 nor 中型100")
        missing = sorted(expected - set(found))
        if missing:
            raise NoticeError(f"no section of {missing}")
    elif not found:
        if _MENTIONS_INDEX.search(flat) and _MEMBERSHIP.search(flat):
            raise NoticeError(
                "an index change not in a known layout: left for manual reading"
            )
        return ParsedNotice(announced, effective, {}, deferred)
    sections: dict[str, dict[str, list[Entry]]] = {}
    for code, parts in found.items():
        if kind == "periodic" and (parts["add"] is None or parts["delete"] is None):
            raise NoticeError(f"{code} has no additions or deletions part")
        adds, deletes = parts["add"] or [], parts["delete"] or []
        if (kind == "periodic" or not deferred) and len(adds) != len(deletes):
            raise NoticeError(
                f"{code}: {len(adds)} additions but {len(deletes)} deletions"
            )
        sections[code] = {
            "add": adds,
            "delete": deletes,
            "reserve": parts["reserve"] or [],
        }
    return ParsedNotice(
        announced,
        None if deferred and kind == "ad_hoc" else effective,
        sections,
        deferred,
    )


# --- the database -------------------------------------------------------------------


def _barred_before(db: Session, day: date) -> dict[str, int]:
    """{code: id} of the TWSE instruments with a bar on the last session up to day."""

    session = db.scalar(
        select(func.max(MarketBar.trading_date))
        .join(Instrument, Instrument.id == MarketBar.instrument_id)
        .where(
            Instrument.exchange == "TWSE",
            Instrument.instrument_type.in_(BAR_TYPES),
            MarketBar.trading_date <= day,
            MarketBar.trading_date > day - timedelta(days=14),
        )
    )
    if session is None:
        return {}
    return dict(
        db.execute(
            select(Instrument.symbol, Instrument.id)
            .join(MarketBar, MarketBar.instrument_id == Instrument.id)
            .where(
                Instrument.exchange == "TWSE",
                Instrument.instrument_type.in_(BAR_TYPES),
                MarketBar.trading_date == session,
            )
        ).all()
    )


def write_notice(
    db: Session,
    notice: ListedNotice,
    kind: str,
    parsed: ParsedNotice,
    raw: RawPayload,
) -> dict[str, Any]:
    """Make the notice's rows the parsed ones; the counts."""

    barred = _barred_before(db, parsed.announced)
    wanted: dict[tuple[str, str, str], dict[str, Any]] = {}
    for index_code, parts in parsed.sections.items():
        for action, entries in parts.items():
            for entry in entries:
                wanted[(index_code, entry.symbol, action)] = {
                    "instrument_id": barred.get(entry.symbol),
                    "name_in_source": entry.name,
                    "review_kind": kind,
                    "announced_date": parsed.announced,
                    "site_file_date": notice.site_date,
                    "announced_time": None,
                    "effective_date": parsed.effective,
                    "free_float_pct": entry.free_float_pct,
                    "source": SOURCE,
                    "data_as_of": parsed.announced,
                    "raw_payload_id": raw.id,
                    "collected_at": raw.collected_at,
                }
    counts: Counter[str] = Counter()
    kept = {}
    for row in db.scalars(
        select(IndexConstituentChange).where(
            IndexConstituentChange.source_doc_id == notice.doc_id
        )
    ):
        key = (row.index_code, row.symbol, row.action)
        if key in wanted and row.announced_date == parsed.announced:
            kept[key] = row
        else:
            db.delete(row)
            counts["removed"] += 1
    if counts["removed"]:
        db.flush()
    for key, values in wanted.items():
        row = kept.get(key)
        if row is None:
            index_code, symbol, action = key
            db.add(
                IndexConstituentChange(
                    index_code=index_code,
                    symbol=symbol,
                    action=action,
                    source_doc_id=notice.doc_id,
                    **values,
                )
            )
            counts["inserted"] += 1
        elif any(getattr(row, name) != value for name, value in values.items()):
            for name, value in values.items():
                setattr(row, name, value)
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1
    unmatched = [symbol for (_i, symbol, _a) in wanted if symbol not in barred]
    by_action = Counter(action for (_i, _s, action) in wanted)
    return {
        "rows": len(wanted),
        "add": by_action["add"],
        "delete": by_action["delete"],
        "reserve": by_action["reserve"],
        "inserted": counts["inserted"],
        "updated": counts["updated"],
        "removed": counts["removed"],
        "unchanged": counts["unchanged"],
        # Rows without an instrument; the codes once.
        "unmatched": len(unmatched),
        "unmatched_codes": sorted(set(unmatched))[:MAX_LISTED],
    }


def _run(db: Session, key: str, run_date: date, *, create: bool) -> IngestionRun | None:
    request_key = REQUEST_KEY.format(key=key)
    run = db.scalar(select(IngestionRun).where(IngestionRun.request_key == request_key))
    if run is None and create:
        run = IngestionRun(
            run_type=DAY_RUN_TYPE,
            source=FEED,
            run_date=run_date,
            status="running",
            request_key=request_key,
            data_as_of=run_date.isoformat(),
            metadata_json={},
        )
        db.add(run)
        # Committed: a failure later rolls back the rows, never the manifest.
        db.commit()
    return run


def _fail(
    db: Session, run: IngestionRun, error: str, raw: RawPayload | None, **extra
) -> None:
    run.status = "failed"
    run.error = error
    run.finished_at = utcnow()
    metadata = {**(run.metadata_json or {}), **extra, "error": error}
    if raw is not None:
        metadata["raw_payload_id"] = raw.id
    run.metadata_json = metadata
    db.commit()


# --- requests -----------------------------------------------------------------------


def fetch_file(url: str) -> bytes:
    body = sources.fetch_json(url, text_fallback=True)
    if not isinstance(body, bytes):
        raise OfficialDataError(f"{url} answered JSON, not a page or file")
    return body


def _taipei(moment: datetime) -> datetime:
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return aware.astimezone(TAIPEI)


def seconds_to_window_end(moment: datetime) -> float:
    """Seconds to wait before a request at ``moment``: quiet hours, even hours."""

    if in_quiet_hours(moment):
        return seconds_to_quiet_end(moment)
    local = _taipei(moment)
    top = local.replace(minute=0, second=0, microsecond=0)
    for hour in (top, top + timedelta(hours=1)):
        if hour.hour % 2 == 0 and abs(local - hour) < EVEN_HOUR_MARGIN:
            return (hour + EVEN_HOUR_MARGIN - local).total_seconds()
    return 0.0


class Pacer:
    """At least ``interval`` seconds between two requests to a host, outside the
    quiet hours and the even hours."""

    def __init__(
        self,
        now: Callable[[], datetime],
        sleep: Callable[[float], None],
        monotonic: Callable[[], float],
        interval: float = REQUEST_INTERVAL_SECONDS,
    ) -> None:
        self.now, self.sleep, self.monotonic = now, sleep, monotonic
        self.interval = interval
        self.last: dict[str, float] = {}
        self.waited = 0.0

    def before(self, url: str) -> None:
        while True:
            wait = seconds_to_window_end(self.now())
            if wait <= 0:
                break
            self.sleep(wait)
            self.waited += wait
        host = urlsplit(url).hostname or ""
        previous = self.last.get(host)
        if previous is not None:
            gap = self.interval - (self.monotonic() - previous)
            if gap > 0:
                self.sleep(gap)
        self.last[host] = self.monotonic()


# --- the run ------------------------------------------------------------------------


def _empty_counts() -> dict[str, Any]:
    return {
        "first_year": FIRST_YEAR,
        "list_years": 0,
        "list_done_before": 0,
        "list_requested": 0,
        "list_reapplied": 0,
        "list_not_answered": 0,
        "list_failed": 0,
        "list_failed_years": [],
        "listed": 0,
        "no_file": 0,
        "picked": 0,
        "periodic": 0,
        "ad_hoc": 0,
        "out_of_range": 0,
        "done_before": 0,
        "requested": 0,
        "reapplied": 0,
        "not_answered": 0,
        "success": 0,
        "without_rows": 0,
        "failed": 0,
        "failed_notices": [],
        "rows": 0,
        "inserted": 0,
        "updated": 0,
        "removed": 0,
        "unchanged": 0,
        "unmatched": 0,
        "unmatched_codes": [],
        "formats": {},
    }


def _list_is_final(raw: RawPayload, year: int) -> bool:
    return _taipei(raw.collected_at).date() > date(year, 12, 31)


def backfill(
    db: Session,
    start: date,
    end: date,
    *,
    reapply: bool = False,
    fetch: Callable[[str], bytes] = fetch_file,
    now: Callable[[], datetime] = utcnow,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    if end < start:
        raise ValueError("--end is before --start")
    if not inspect(db.get_bind()).has_table(IndexConstituentChange.__tablename__):
        raise ValueError("index_constituent_changes is missing: run init-db first")
    started = time.monotonic()
    pacer = Pacer(now, sleep, monotonic)
    counts = _empty_counts()
    requests = 0
    failures_in_a_row: Counter[str] = Counter()
    aborted: str | None = None
    formats: Counter[str] = Counter()
    unmatched_codes: set[str] = set()

    def request(url: str) -> bytes:
        nonlocal requests
        host = urlsplit(url).hostname or ""
        pacer.before(url)
        requests += 1
        try:
            body = fetch(url)
        except Exception as exc:  # the source's failure, never a crash
            failures_in_a_row[host] += 1
            raise OfficialDataError(f"request failed: {exc}") from exc
        failures_in_a_row[host] = 0
        return body

    def blocked() -> str | None:
        hosts = [h for h, n in failures_in_a_row.items() if n >= ABORT_AFTER_FAILURES]
        return (
            f"{ABORT_AFTER_FAILURES} failed requests in a row to {hosts[0]}"
            if hosts
            else None
        )

    picked: list[tuple[ListedNotice, str]] = []
    for year in range(max(FIRST_YEAR, start.year), end.year + 1):
        counts["list_years"] += 1
        run = _run(db, f"list:{year}", date(year, 1, 1), create=not reapply)
        if run is None:
            counts["list_not_answered"] += 1
            continue
        stored = (run.metadata_json or {}).get("raw_payload_id")
        raw = db.get(RawPayload, stored) if stored else None
        url = LIST_URL.format(year=year)
        try:
            if reapply or (
                run.status == "success"
                and raw is not None
                and _list_is_final(raw, year)
            ):
                if raw is None:
                    counts["list_not_answered"] += 1
                    continue
                if reapply:
                    counts["list_reapplied"] += 1
                else:
                    counts["list_done_before"] += 1
                body = unwrap_body(read_raw(raw))
            else:
                counts["list_requested"] += 1
                raw = None
                body = request(url)
                captured = sources.capture_payload(
                    RAW_SOURCE, url, wrap_body(url, body), str(year)
                )
                raw = pipeline._upsert_raw_payload(db, run, captured)
                db.commit()
            try:
                page = body.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise NoticeError("the list page is not UTF-8") from exc
            listed = parse_list(page, year)
        except OfficialDataError as exc:
            db.rollback()
            _fail(db, run, str(exc), raw)
            counts["list_failed"] += 1
            counts["list_failed_years"].append({"year": year, "error": str(exc)})
            aborted = blocked()
            if aborted:
                break
            continue
        run.status = "success"
        run.error = None
        run.records = len(listed)
        run.finished_at = utcnow()
        run.metadata_json = {"raw_payload_id": raw.id, "rows": len(listed)}
        db.commit()
        for notice in listed:
            counts["listed"] += 1
            if not notice.doc_id:
                counts["no_file"] += 1
                continue
            kind = notice_kind(notice.title, notice.category)
            if kind is None:
                continue
            if not start <= notice.site_date <= end:
                counts["out_of_range"] += 1
                continue
            counts["picked"] += 1
            counts[kind] += 1
            picked.append((notice, kind))
    picked.sort(key=lambda item: (item[0].site_date, int(item[0].doc_id)))
    for notice, kind in [] if aborted else picked:
        about = {"title": notice.title, "category": notice.category, "kind": kind}
        run = _run(db, notice.doc_id, notice.site_date, create=not reapply)
        if run is None:
            counts["not_answered"] += 1
            continue
        if run.status == "success" and not reapply:
            counts["done_before"] += 1
            continue
        stored = (run.metadata_json or {}).get("raw_payload_id")
        raw = db.get(RawPayload, stored) if stored else None
        try:
            if raw is None and reapply:
                counts["not_answered"] += 1
                continue
            if raw is not None:
                # reapply, or a file that came and did not read: no request.
                counts["reapplied"] += 1
                body = unwrap_body(read_raw(raw))
            else:
                counts["requested"] += 1
                url = FILE_URL.format(id=notice.doc_id)
                body = request(url)
                captured = sources.capture_payload(
                    RAW_SOURCE, url, wrap_body(url, body), notice.site_date.isoformat()
                )
                raw = pipeline._upsert_raw_payload(db, run, captured)
                db.commit()
            fmt, text = file_text(body)
            formats[fmt] += 1
            parsed = parse_notice(text, kind, notice.site_date)
            written = write_notice(db, notice, kind, parsed, raw)
        except OfficialDataError as exc:
            db.rollback()
            _fail(db, run, str(exc), raw, **about)
            counts["failed"] += 1
            if len(counts["failed_notices"]) < MAX_LISTED:
                counts["failed_notices"].append(
                    {
                        "id": notice.doc_id,
                        "site_date": notice.site_date.isoformat(),
                        "kind": kind,
                        "error": str(exc),
                    }
                )
            aborted = blocked()
            if aborted:
                break
            continue
        run.status = "success"
        run.error = None
        run.records = written["rows"]
        run.finished_at = utcnow()
        run.metadata_json = {
            "raw_payload_id": raw.id,
            "source": SOURCE,
            **about,
            "format": fmt,
            "announced_date": parsed.announced.isoformat(),
            "effective_date": parsed.effective.isoformat()
            if parsed.effective
            else None,
            "deferred": parsed.deferred,
            **written,
        }
        db.commit()
        counts["success"] += 1
        if not written["rows"]:
            counts["without_rows"] += 1
        for key in ("rows", "inserted", "updated", "removed", "unchanged", "unmatched"):
            counts[key] += written[key]
        unmatched_codes.update(written["unmatched_codes"])
    counts["unmatched_codes"] = sorted(unmatched_codes)[:MAX_LISTED]
    counts["formats"] = dict(sorted(formats.items()))
    counts["changed"] = counts["inserted"] + counts["updated"] + counts["removed"]
    counts["waited_seconds"] = round(pacer.waited, 1)
    failed = counts["failed"] + counts["list_failed"]
    return {
        "status": "partial" if failed or aborted else "success",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "requests": requests,
        "aborted": aborted,
        "changed": counts["changed"],
        "feeds": {FEED: counts},
        "duration_seconds": round(time.monotonic() - started, 1),
    }


__all__ = [
    "FEED",
    "QUIET_END",
    "QUIET_START",
    "backfill",
    "file_text",
    "notice_kind",
    "parse_list",
    "parse_notice",
]
