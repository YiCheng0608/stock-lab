"""Quarterly EPS of delisted and transferred companies from the MOPS XBRL archives (Issue #781).

``t163sb04`` (``worker.quarterly_fundamentals``) is generated from today's list of
listed companies, so the research database has no quarter for a company that has
since delisted or moved market (#781 AC-1).  MOPS also keeps one zip per quarter,
``tifrs-<year>Q<n>.zip`` (``ENDPOINT``), with the XBRL instance every company filed
for that quarter: 2014Q2 holds 2,004 companies, 2384 and 2475 among them, and its
YTD ``BasicEarningsLossPerShare`` equals ``t163sb04`` for all 1,517 companies on
both (#781 6894525486).

Two commands, so the download never touches a database:

- ``fetch_archives`` downloads the quarters into a directory with a
  ``manifest.json``; a quarter already there and whole is not asked again.  At least
  ``REQUEST_INTERVAL_SECONDS`` between requests, none during ``QUIET_HOURS``.  The
  server sends no ``Content-Length`` and now and then closes the connection early,
  so an answer that is zip data cut short (or slower than ``ATTEMPT_SECONDS``) is
  asked again, at most ``ATTEMPTS_PER_QUARTER`` requests a quarter; nothing else is
  retried.  Every failed attempt is in the result (bytes, seconds, first bytes) and
  its file is kept under ``FAILED_DIR``.  ``ABORT_AFTER_FAILURES`` failed quarters in
  a row stop it.
- ``apply_archives`` writes the quarters into ``fundamental_snapshots``, one
  ``fundamental_xbrl_backfill`` run, one commit per quarter.  Only ``delisted`` and
  ``transferred`` instruments get rows (an active company is on today's list, so
  ``t163sb04`` has it, and a reused code's former company is never written onto the
  company holding it now), only quarters they lack, and only quarters with a bar of
  theirs within ``EVIDENCE_WINDOW_DAYS`` after the quarter's end.  Each quarter is
  first compared with ``t163sb04`` on the companies both have; one different EPS or
  report format stops the command before that quarter is written.  It is rerun after
  every research backfill batch that creates older instruments: rows already written
  are ``unchanged``.  The command runs only on the research DB (``research_refusal``)
  and holds maintenance mode (``worker.cli.maintenance_guarded``).

The zip is an outside file: it is read in memory member by member (never extracted
to a path), with limits on the members, each member's size and the total, and a
member declaring a DOCTYPE or an entity is refused before it is parsed.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import time
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from datetime import time as clock_time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable
from xml.etree import ElementTree

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app import config
from app.clock import utcnow
from app.db import SessionLocal
from app.models import (
    FundamentalSnapshot,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
)
from app.raw_paths import payload_file
from worker import sources
from worker.quarterly_fundamentals import (
    Quarter,
    apply_record,
    availability,
    nominal_deadline,
    roll_to_session,
)
from worker.sources import FundamentalRecord, OfficialDataError

ENDPOINT = (
    "https://mopsov.twse.com.tw/server-java/FileDownLoad?step=9"
    "&fileName=tifrs-{label}.zip&filePath=/home/html/nas/ifrs/{year}/"
)
SOURCE = "mops_tifrs_zip"
# raw_payloads.source and the raw directory: zips, apart from the JSON captures of "mops".
RAW_SOURCE = "mops_tifrs"
RUN_TYPE = "fundamental_xbrl_backfill"
T163SB04_SOURCE = "mops_t163sb04"
MANIFEST = "manifest.json"
FIRST_QUARTER = Quarter(
    2013, 1
)  # IFRS filings, and the research DB's t163sb04, start here
TAIPEI = timezone(timedelta(hours=8))

# --- download rules (#781 decision 6894481009) ----------------------------------------
REQUEST_INTERVAL_SECONDS = 5.0
# Taipei hours no request starts in: the daily's and the morning's.
QUIET_HOURS = (
    (clock_time(20, 30), clock_time(23, 30)),
    (clock_time(8, 0), clock_time(9, 0)),
)
ABORT_AFTER_FAILURES = 3
USER_AGENT = "taiwan-stock-research/0.1"
# The server answers HTTP/1.0 with no Content-Length and closed the connection early
# on 4 of 10 archives on 2026-11-16; a whole one takes about 10 minutes (#786
# 6906415391).  Only that case is asked again (decision 6906475680): a 200 whose
# file starts as a zip but has no end, or one attempt over ATTEMPT_SECONDS.
ATTEMPTS_PER_QUARTER = 3
ATTEMPT_SECONDS = 30 * 60
ZIP_LOCAL_HEADER = b"PK\x03\x04"
# Failed attempts' files, kept for reading what the server sent.
FAILED_DIR = "failed"
FAILED_HEAD_BYTES = 16

# --- limits on an archive (2014Q2: 2,037 members, the largest 1.5 MB, 0.54 GB in all) ---
MAX_ARCHIVE_BYTES = 1 << 30
MAX_MEMBERS = 5_000
MAX_MEMBER_BYTES = 32 << 20
MAX_TOTAL_BYTES = 8 << 30
READ_CHUNK = 1 << 20

MEMBER_NAME = re.compile(
    r"tifrs-fr\d-m\d-(?P<industry>[a-z]+)-(?P<kind>[a-z]+)-(?P<symbol>[0-9A-Z]{4,6})"
    r"-(?P<year>\d{4})Q(?P<quarter>[1-4])\.(?P<ext>xml|html)"
)
# The industry code of a member's name to t163sb04's report format: one to one on
# the 1,517 companies of 2014Q2 (#781 6894525486); it decides the filing deadline.
INDUSTRY_FORMATS = {
    "ci": "general",
    "basi": "bank",
    "bd": "securities",
    "fh": "holding",
    "ins": "insurance_legacy",
    "mim": "other",
}
# A company with more than one instance: consolidated, then individual, then ``er``
# (2014Q2: the 7 companies with ``cr`` and ``er`` have the same EPS in both).
REPORT_KINDS = ("cr", "ir", "er")
EPS_CONCEPT = "BasicEarningsLossPerShare"
# The check against t163sb04 stops a quarter when more than this share of the companies
# t163sb04 has cannot be compared (no member, no EPS, unreadable): 2014Q2 had 1 of
# 1,518 (6026, not in the archive; #781 6894525486).  A new layout no member can be
# read in then fails instead of passing with nothing compared (review of PR #783).
CHECK_MISSING_LIMIT = 0.01

# The research volume carries this marker next to stock.db; the production one never
# does (tools/research/history_backfill.py, docs/ops/RESEARCH_DB.md).
MARKER_NAME = "research-db.json"
MARKER_PURPOSE = "research_history"

# --- which instruments get a quarter --------------------------------------------------
TARGET_STATUSES = ("delisted", "transferred")
TARGET_TYPES = ("stock", "ipo")
# eps_growth_yield at T reads the latest known quarter L, L−1, L−4 and L−5, and L
# counts only while T is within QUARTER_STALE_DAYS of L's end
# (tools/research/evidence_lib.py; feature_evidence._quarter_eps).  So a quarter Q is
# read on days up to five quarters (at most 92 days each) and QUARTER_STALE_DAYS
# after Q's end; a bar that late or earlier makes Q needed.
EVIDENCE_QUARTERS = 5
LONGEST_QUARTER_DAYS = 92
QUARTER_STALE_DAYS = 200  # tools/research/evidence_lib.QUARTER_STALE_DAYS
WINDOW_MARGIN_DAYS = 10
EVIDENCE_WINDOW_DAYS = (
    EVIDENCE_QUARTERS * LONGEST_QUARTER_DAYS + QUARTER_STALE_DAYS + WINDOW_MARGIN_DAYS
)

_XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"
# inline XBRL number formats read as plain numbers with thousands commas.
_PLAIN_FORMATS = {"numdotdecimal", "num-dot-decimal", "numcommadot"}
_ZERO_FORMATS = {"zerodash", "fixed-zero"}


class ArchiveError(OfficialDataError):
    """A quarter's archive cannot be trusted; nothing of that quarter is used."""


class TruncatedArchive(ArchiveError):
    """The download ended before the archive did (or took too long); asked again."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class MemberError(ValueError):
    """One company's instance cannot be read; that company is skipped and counted."""


# --- quarters and paths -------------------------------------------------------------


def archive_url(quarter: Quarter) -> str:
    return ENDPOINT.format(label=quarter.label, year=quarter.year)


def archive_name(quarter: Quarter) -> str:
    return f"tifrs-{quarter.label}.zip"


def quarters_between(start: Quarter, end: Quarter) -> list[Quarter]:
    if start < FIRST_QUARTER:
        raise ValueError(f"the archives start at {FIRST_QUARTER.label}")
    if end < start:
        raise ValueError(f"{end.label} is before {start.label}")
    result = [end]
    while result[-1] > start:
        result.append(result[-1].previous())
    return sorted(result)


def in_quiet_hours(moment: datetime) -> bool:
    local = moment.astimezone(TAIPEI).time()
    return any(begin <= local < finish for begin, finish in QUIET_HOURS)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(READ_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest(directory: Path) -> dict[str, Any]:
    path = directory / MANIFEST
    if not path.exists():
        return {"quarters": {}}
    stored = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(stored, dict) or not isinstance(stored.get("quarters"), dict):
        raise ValueError(f"{path} is not a manifest")
    return stored


def _write_manifest(directory: Path, manifest: dict[str, Any]) -> None:
    path = directory / MANIFEST
    temporary = path.with_name(f".{MANIFEST}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def whole_archive(directory: Path, quarter: Quarter, manifest: dict[str, Any]) -> bool:
    entry = manifest["quarters"].get(quarter.label)
    path = directory / archive_name(quarter)
    if not entry or not path.exists() or path.stat().st_size != entry.get("bytes"):
        return False
    return _sha256_file(path) == entry.get("sha256")


# --- the archive ----------------------------------------------------------------------


@dataclass(frozen=True)
class Member:
    name: str
    industry: str
    kind: str
    symbol: str
    info: zipfile.ZipInfo


def archive_members(archive: zipfile.ZipFile, quarter: Quarter) -> list[Member]:
    """Every member, checked: count, names, and the quarter the names say."""

    infos = archive.infolist()
    if not infos:
        raise ArchiveError(f"{quarter.label} archive has no member")
    if len(infos) > MAX_MEMBERS:
        raise ArchiveError(
            f"{quarter.label} archive has {len(infos)} members (limit {MAX_MEMBERS})"
        )
    members = []
    for info in infos:
        match = MEMBER_NAME.fullmatch(info.filename)
        if match is None:
            raise ArchiveError(
                f"{quarter.label} archive has an unexpected member {info.filename!r}"
            )
        if (int(match["year"]), int(match["quarter"])) != (
            quarter.year,
            quarter.quarter,
        ):
            raise ArchiveError(
                f"{quarter.label} archive has another quarter's member {info.filename!r}"
            )
        members.append(
            Member(
                info.filename, match["industry"], match["kind"], match["symbol"], info
            )
        )
    return members


def check_archive(path: Path, quarter: Quarter) -> int:
    """The member count of a downloaded archive; raises ArchiveError when it is not one.

    ``TruncatedArchive`` when the file starts as a zip but is not a whole one: the
    connection closed before the end.  Anything else (HTML, a block page) is not.
    """

    try:
        with zipfile.ZipFile(path) as archive:
            return len(archive_members(archive, quarter))
    except zipfile.BadZipFile as exc:
        with path.open("rb") as handle:
            started_as_zip = handle.read(len(ZIP_LOCAL_HEADER)) == ZIP_LOCAL_HEADER
        error = TruncatedArchive if started_as_zip else ArchiveError
        raise error(f"{quarter.label} is not a whole zip: {exc}") from exc


class ReadBudget:
    """The uncompressed bytes one quarter may read, counted as they are read."""

    def __init__(self, limit: int = MAX_TOTAL_BYTES) -> None:
        self.limit = limit
        self.used = 0

    def read(self, archive: zipfile.ZipFile, member: Member) -> bytes:
        parts: list[bytes] = []
        size = 0
        try:
            with archive.open(member.info) as handle:
                while True:
                    chunk = handle.read(READ_CHUNK)
                    if not chunk:
                        break
                    size += len(chunk)
                    self.used += len(chunk)
                    if size > MAX_MEMBER_BYTES:
                        raise ArchiveError(
                            f"{member.name} is over {MAX_MEMBER_BYTES} bytes uncompressed"
                        )
                    if self.used > self.limit:
                        raise ArchiveError(
                            f"the archive is over {self.limit} bytes uncompressed"
                        )
                    parts.append(chunk)
        except ArchiveError:
            raise
        # A bad CRC (BadZipFile), an unsupported method (NotImplementedError), an
        # encrypted member (RuntimeError) or a broken stream: the archive is not whole.
        except (
            zipfile.BadZipFile,
            NotImplementedError,
            RuntimeError,
            zlib.error,
            EOFError,
            OSError,
            ValueError,
        ) as exc:
            raise ArchiveError(f"{member.name} cannot be read: {exc!r}") from exc
        return b"".join(parts)


def best_members(members: Iterable[Member]) -> dict[str, Member]:
    """One member per company: the first kind of ``REPORT_KINDS`` it has."""

    result: dict[str, Member] = {}
    seen: dict[tuple[str, str], str] = {}
    for member in members:
        if member.kind not in REPORT_KINDS:
            continue
        key = (member.symbol, member.kind)
        if key in seen:
            raise ArchiveError(
                f"two {member.kind} instances of {member.symbol}: "
                f"{seen[key]}, {member.name}"
            )
        seen[key] = member.name
        held = result.get(member.symbol)
        if held is None or REPORT_KINDS.index(member.kind) < REPORT_KINDS.index(
            held.kind
        ):
            result[member.symbol] = member
    return result


# --- one instance ---------------------------------------------------------------------


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _year_to_date(root: ElementTree.Element, quarter: Quarter) -> set[str]:
    """Ids of the contexts from 1 January to the quarter's end, without dimensions."""

    start, end = date(quarter.year, 1, 1).isoformat(), quarter.period_end.isoformat()
    found = set()
    for element in root.iter():
        if _local(element.tag) != "context":
            continue
        names = {_local(child.tag): child for child in element.iter()}
        if "segment" in names or "scenario" in names:
            continue
        begin, finish = names.get("startDate"), names.get("endDate")
        if begin is None or finish is None:
            continue
        if (begin.text or "").strip() == start and (finish.text or "").strip() == end:
            found.add(element.get("id") or "")
    return found


def _inline_value(element: ElementTree.Element) -> Decimal | None:
    if element.get(_XSI_NIL) == "true":
        return None
    text = "".join(element.itertext()).strip()
    style = (element.get("format") or "").rsplit(":", 1)[-1]
    if style in _ZERO_FORMATS:
        value = Decimal(0)
    elif style in _PLAIN_FORMATS or not style:
        try:
            value = Decimal(text.replace(",", ""))
        except InvalidOperation as exc:
            raise MemberError(f"EPS {text!r} is not a number") from exc
    else:
        raise MemberError(f"unknown inline XBRL format {element.get('format')!r}")
    scale = element.get("scale")
    if scale:
        try:
            value = value.scaleb(int(scale))
        except ValueError as exc:
            raise MemberError(f"scale {scale!r} is not an integer") from exc
    if element.get("sign") == "-":
        value = -value
    return value


def _plain_value(element: ElementTree.Element) -> Decimal | None:
    if element.get(_XSI_NIL) == "true":
        return None
    text = (element.text or "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise MemberError(f"EPS {text!r} is not a number") from exc


def parse_eps(data: bytes, quarter: Quarter) -> tuple[float | None, str | None]:
    """The year-to-date basic EPS of one instance (``.xml`` or inline ``.html``).

    Returns (EPS, the context ids read, joined by commas); (None, None) when the
    instance has no such fact.  Every fact of a year-to-date context (the statement
    and a note; a first quarter's three-month context too) must agree.
    """

    if data.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in data:
        raise MemberError("instance is UTF-16 or holds a NUL byte")
    upper = data.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise MemberError("instance declares a DOCTYPE or an entity")
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise MemberError(f"instance is not XML: {exc}") from exc
    contexts = _year_to_date(root, quarter)
    values: set[Decimal | None] = set()
    used: set[str] = set()
    for element in root.iter():
        local = _local(element.tag)
        if local == EPS_CONCEPT:
            value = _plain_value(element)
        elif (
            local == "nonFraction"
            and (element.get("name") or "").rsplit(":", 1)[-1] == EPS_CONCEPT
        ):
            value = _inline_value(element)
        else:
            continue
        context = element.get("contextRef") or ""
        if context in contexts:
            values.add(value)
            used.add(context)
    if not used:
        return None, None
    # A first quarter's three-month context is also its year to date.
    context = ",".join(sorted(used))
    known = {value for value in values if value is not None}
    if len(known) > 1:
        raise MemberError(f"year-to-date facts ({context}) disagree")
    if not known:
        return None, context
    return float(known.pop()), context


# --- download -------------------------------------------------------------------------


def download(
    url: str,
    target: Path,
    max_bytes: int,
    *,
    max_seconds: float = ATTEMPT_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """GET URL into TARGET (at most MAX_BYTES, else ArchiveError); the status code.

    Through ``sources._throttle_official_host`` as every official request; the
    command's own interval (``REQUEST_INTERVAL_SECONDS``) is the longer one.  Over
    MAX_SECONDS in all is ``TruncatedArchive`` (the 300 s timeout is per read).
    """

    sources._throttle_official_host(url)
    started = clock()
    with httpx.stream(
        "GET", url, headers={"User-Agent": USER_AGENT}, timeout=300
    ) as response:
        if response.status_code != 200:
            return response.status_code
        size = 0
        with target.open("wb") as handle:
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise ArchiveError(f"{url} is over {max_bytes} bytes")
                handle.write(chunk)
                if clock() - started > max_seconds:
                    raise TruncatedArchive(
                        f"{url} took over {max_seconds:.0f} s ({size} bytes)",
                        status=200,
                    )
            handle.flush()
            os.fsync(handle.fileno())
        return 200


def fetch_archives(
    directory: Path,
    start: Quarter,
    end: Quarter,
    *,
    getter: Callable[[str, Path, int], int] = download,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict[str, Any]:
    """Download the quarters' archives into DIRECTORY; never asks for one it has whole."""

    targets = quarters_between(start, end)
    directory.mkdir(parents=True, exist_ok=True)
    manifest = read_manifest(directory)
    result: dict[str, Any] = {
        "downloaded": [],
        "kept": [],
        "failed": {},
        "requests": 0,
        "attempts": {},
    }
    failures_in_a_row = 0
    last_request: float | None = None
    stopped: str | None = None
    for quarter in targets:
        if whole_archive(directory, quarter, manifest):
            result["kept"].append(quarter.label)
            continue
        url = archive_url(quarter)
        final = directory / archive_name(quarter)
        partial = final.with_name(final.name + ".part")
        failed_attempts: list[dict[str, Any]] = []
        error: str | None = None
        _set_aside_stale(directory, partial, quarter)
        for attempt in range(1, ATTEMPTS_PER_QUARTER + 1):
            if last_request is not None:
                wait = REQUEST_INTERVAL_SECONDS - (clock() - last_request)
                if wait > 0:
                    sleep(wait)
            moment = now()
            if in_quiet_hours(moment):
                stopped = (
                    f"quiet hours at {moment.astimezone(TAIPEI):%H:%M} Taipei before "
                    f"{quarter.label}; run the same command again after them"
                )
                break
            last_request = clock()
            result["requests"] += 1
            status: int | None = None
            try:
                status = getter(url, partial, MAX_ARCHIVE_BYTES)
                if status != 200:
                    raise ArchiveError(f"{quarter.label}: HTTP {status}")
                if not partial.exists() or partial.stat().st_size == 0:
                    raise ArchiveError(f"{quarter.label}: empty response")
                members = check_archive(partial, quarter)
            except (ArchiveError, httpx.HTTPError, OSError) as exc:
                error = str(exc)
                status = getattr(exc, "status", None) or status
                failed_attempts.append(
                    _failed_attempt(
                        directory,
                        partial,
                        quarter,
                        attempt,
                        moment,
                        status,
                        exc,
                        clock() - last_request,
                    )
                )
                if isinstance(exc, TruncatedArchive):
                    # The interval before asking again counts from the end of the
                    # cut answer, not from its start (review of PR #797).
                    last_request = clock()
                    continue
                break
            error = None
            break
        if failed_attempts:
            result["attempts"][quarter.label] = failed_attempts
        if error is None and stopped is None:
            failures_in_a_row = 0
            os.replace(partial, final)
            manifest["quarters"][quarter.label] = {
                "url": url,
                "status": status,
                "bytes": final.stat().st_size,
                "sha256": _sha256_file(final),
                "members": members,
                "fetched_at": moment.astimezone(timezone.utc).isoformat(),
                "requests": len(failed_attempts) + 1,
            }
            _write_manifest(directory, manifest)
            result["downloaded"].append(quarter.label)
            continue
        if error is not None:
            result["failed"][quarter.label] = error
        if stopped is not None:
            break
        failures_in_a_row += 1
        if failures_in_a_row >= ABORT_AFTER_FAILURES:
            stopped = (
                f"{failures_in_a_row} quarters failed in a row at {quarter.label}; "
                "停下來問"
            )
            break
    if stopped and failures_in_a_row >= ABORT_AFTER_FAILURES:
        status_text = "failed"
    elif stopped or result["failed"]:
        status_text = "partial"
    else:
        status_text = "success"
    return {
        "status": status_text,
        "start_quarter": targets[0].label,
        "end_quarter": targets[-1].label,
        "stopped": stopped,
        **result,
    }


def _set_aside_stale(directory: Path, partial: Path, quarter: Quarter) -> None:
    """A ``.part`` left by a stopped run moves to ``FAILED_DIR``: never read as this run's."""

    if not partial.exists():
        return
    kept_dir = directory / FAILED_DIR
    kept_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    os.replace(partial, kept_dir / f"{archive_name(quarter)}.{stamp}-stale.part")


def _failed_attempt(
    directory: Path,
    partial: Path,
    quarter: Quarter,
    attempt: int,
    moment: datetime,
    status: int | None,
    exc: Exception,
    seconds: float,
) -> dict[str, Any]:
    """One failed request for the result; its file moves to ``FAILED_DIR``, never deleted."""

    record: dict[str, Any] = {
        "attempt": attempt,
        "at": moment.astimezone(timezone.utc).isoformat(),
        "status": status,
        "error": str(exc),
        # Only a truncated answer is asked again (while attempts are left).
        "truncated": isinstance(exc, TruncatedArchive),
        "seconds": round(seconds, 1),
        "bytes": 0,
        "head": "",
        "kept": None,
    }
    if partial.exists():
        record["bytes"] = partial.stat().st_size
        with partial.open("rb") as handle:
            record["head"] = handle.read(FAILED_HEAD_BYTES).hex()
        kept_dir = directory / FAILED_DIR
        kept_dir.mkdir(exist_ok=True)
        kept = kept_dir / (
            f"{archive_name(quarter)}.{moment.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}"
            f"-{attempt}.part"
        )
        os.replace(partial, kept)
        record["kept"] = f"{FAILED_DIR}/{kept.name}"
    return record


# --- apply ----------------------------------------------------------------------------


@dataclass
class QuarterCounts:
    members: int = 0
    companies: int = 0
    with_eps: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    dated: int = 0
    would_insert: int = 0
    existing_other_source: int = 0
    not_in_db: int = 0
    not_target: int = 0
    outside_window: int = 0
    excluded: int = 0
    # Excluded now but written by an earlier run (docs/ops/RESEARCH_DB.md: how to delete).
    excluded_already_written: int = 0
    unknown_format: int = 0
    unreadable: int = 0
    no_eps: int = 0
    check_same: int = 0
    check_different: int = 0
    check_missing: int = 0
    check_format_mismatch: int = 0
    errors: list[str] = field(default_factory=list)
    used_members: dict[str, str] = field(default_factory=dict)


def _bar_within(db: Session, instrument_id: int, quarter: Quarter) -> bool:
    first = quarter.period_end
    last = first + timedelta(days=EVIDENCE_WINDOW_DAYS)
    return (
        db.scalar(
            select(MarketBar.id)
            .where(
                MarketBar.instrument_id == instrument_id,
                MarketBar.trading_date >= first,
                MarketBar.trading_date <= last,
            )
            .limit(1)
        )
        is not None
    )


def _raw_row(
    db: Session,
    run: IngestionRun,
    quarter: Quarter,
    data: bytes,
    digest: str,
    fetched_at: datetime,
) -> RawPayload:
    """The quarter's raw_payloads row, citing the zip itself (#781 decision 6894553670)."""

    url = archive_url(quarter)
    target = (
        sources.RAW_DIR / RAW_SOURCE / fetched_at.strftime("%Y/%m/%d") / f"{digest}.zip"
    )
    row = db.scalar(
        select(RawPayload)
        .where(
            RawPayload.source == RAW_SOURCE,
            RawPayload.endpoint == url,
            RawPayload.sha256 == digest,
        )
        .order_by(RawPayload.id)
        .limit(1)
    )
    if row is not None and row.payload_path:
        target = payload_file(row.payload_path)
    state = sources.ensure_raw_file(
        target,
        data,
        {
            "source": RAW_SOURCE,
            "endpoint": url,
            "sha256": digest,
            "data_as_of": quarter.period_end.isoformat(),
            "collected_at": fetched_at.isoformat(),
        },
    )
    if state not in (None, sources.RAW_MISSING):
        sources.warn_raw(f"raw archive {target} was {state}; rewrote it")
    if row is not None:
        return row
    row = RawPayload(
        ingestion_run_id=run.id,
        source=RAW_SOURCE,
        endpoint=url,
        payload_path=str(target),
        sha256=digest,
        data_as_of=quarter.period_end.isoformat(),
        collected_at=fetched_at.astimezone(timezone.utc).replace(tzinfo=None),
    )
    db.add(row)
    db.flush()
    return row


def _taipei_day(moment: datetime) -> date:
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return aware.astimezone(TAIPEI).date()


def apply_quarter(
    db: Session,
    run: IngestionRun | None,
    quarter: Quarter,
    data: bytes,
    digest: str,
    fetched_at: datetime,
    *,
    excluded: frozenset[int] = frozenset(),
) -> QuarterCounts:
    """Check one quarter against t163sb04, then write its missing rows (``run`` None: dry run).

    Raises ArchiveError when the archive cannot be trusted, and ``MismatchError`` when
    a company both sources have differs; nothing of the quarter is written then.
    """

    counts = QuarterCounts()
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ArchiveError(f"{quarter.label} is not a whole zip: {exc}") from exc
    with archive:
        members = archive_members(archive, quarter)
        counts.members = len(members)
        chosen = best_members(members)
        counts.companies = len(chosen)
        budget = ReadBudget()
        parsed: dict[str, tuple[Member, float | None, str | None, str]] = {}

        def read(symbol: str) -> tuple[Member, float | None, str | None, str] | None:
            if symbol in parsed:
                return parsed[symbol]
            member = chosen.get(symbol)
            if member is None:
                return None
            content = budget.read(archive, member)
            try:
                eps, context = parse_eps(content, quarter)
            except MemberError as exc:
                counts.unreadable += 1
                counts.errors.append(f"{member.name}: {exc}")
                parsed[symbol] = (member, None, None, "")
                return parsed[symbol]
            parsed[symbol] = (
                member,
                eps,
                context,
                hashlib.sha256(content).hexdigest(),
            )
            return parsed[symbol]

        # 1. The check: every company t163sb04 has for the quarter.
        checked = db.execute(
            select(
                Instrument.symbol,
                FundamentalSnapshot.eps,
                FundamentalSnapshot.data_json,
            )
            .join(Instrument, Instrument.id == FundamentalSnapshot.instrument_id)
            .where(
                FundamentalSnapshot.source == T163SB04_SOURCE,
                FundamentalSnapshot.period_end == quarter.period_end,
                FundamentalSnapshot.fiscal_period == f"Q{quarter.quarter}",
            )
        ).all()
        for symbol, stored_eps, details in checked:
            found = read(symbol)
            if found is None or found[1] is None or stored_eps is None:
                counts.check_missing += 1
                continue
            member, eps = found[0], found[1]
            if eps == stored_eps:
                counts.check_same += 1
            else:
                counts.check_different += 1
            stored_format = (details or {}).get("report_format")
            if stored_format and INDUSTRY_FORMATS.get(member.industry) != stored_format:
                counts.check_format_mismatch += 1
        compared = len(checked)
        if (
            counts.check_different
            or counts.check_format_mismatch
            or (compared and counts.check_same == 0)
            or counts.check_missing > compared * CHECK_MISSING_LIMIT
        ):
            raise MismatchError(quarter, counts)

        # 2. The targets: delisted and transferred instruments the archive has.
        instruments: dict[str, list[Instrument]] = {}
        for item in db.scalars(
            select(Instrument).where(Instrument.instrument_type.in_(TARGET_TYPES))
        ):
            instruments.setdefault(item.symbol, []).append(item)
        stored = {
            (row.instrument_id, row.source)
            for row in db.execute(
                select(
                    FundamentalSnapshot.instrument_id, FundamentalSnapshot.source
                ).where(
                    FundamentalSnapshot.period_end == quarter.period_end,
                    FundamentalSnapshot.fiscal_period == f"Q{quarter.quarter}",
                )
            )
        }
        stored_ids = {instrument_id for instrument_id, _source in stored}
        own_ids = {i for i, source in stored if source == SOURCE}
        first_seen = _taipei_day(fetched_at)
        deadlines: dict[str, tuple[date, str]] = {}
        raw: RawPayload | None = None
        for symbol in sorted(chosen):
            member = chosen[symbol]
            candidates = instruments.get(symbol, [])
            if not candidates:
                counts.not_in_db += 1
                continue
            targets = [c for c in candidates if c.status in TARGET_STATUSES]
            if not targets:
                counts.not_target += 1
                continue
            report_format = INDUSTRY_FORMATS.get(member.industry)
            if report_format is None:
                counts.unknown_format += 1
                continue
            for instrument in sorted(targets, key=lambda item: item.id):
                if instrument.id in excluded:
                    counts.excluded += 1
                    if instrument.id in own_ids:
                        counts.excluded_already_written += 1
                    continue
                if instrument.id in stored_ids and instrument.id not in own_ids:
                    counts.existing_other_source += 1
                    continue
                if not _bar_within(db, instrument.id, quarter):
                    counts.outside_window += 1
                    continue
                found = read(symbol)
                if found is None or not found[3]:
                    continue  # unreadable, counted by read
                _member, eps, context, member_sha = found
                if eps is None:
                    counts.no_eps += 1
                    continue
                counts.with_eps += 1
                if run is None:
                    if instrument.id in own_ids:
                        counts.unchanged += 1
                    else:
                        counts.would_insert += 1
                    continue
                if raw is None:
                    raw = _raw_row(db, run, quarter, data, digest, fetched_at)
                if report_format not in deadlines:
                    deadlines[report_format] = roll_to_session(
                        db, nominal_deadline(report_format, quarter)
                    )
                deadline, calendar = deadlines[report_format]
                available, basis = availability(deadline, first_seen)
                record = FundamentalRecord(
                    symbol=symbol,
                    period_end=quarter.period_end,
                    fiscal_period=f"Q{quarter.quarter}",
                    announcement_date=available,
                    eps=eps,
                    details={
                        "member": member.name,
                        "member_sha256": member_sha,
                        "archive_sha256": digest,
                        "industry_code": member.industry,
                        "report_kind": member.kind,
                        "report_format": report_format,
                        "concept": EPS_CONCEPT,
                        "context": context,
                        "announcement_basis": basis,
                        "statutory_deadline": deadline.isoformat(),
                        "deadline_calendar": calendar,
                    },
                    exchange=instrument.exchange,
                    source=SOURCE,
                    payload_sha256=digest,
                )
                outcome = apply_record(db, record, instrument, raw.id)
                setattr(counts, outcome, getattr(counts, outcome) + 1)
                counts.used_members[member.name] = member_sha
    return counts


class MismatchError(ArchiveError):
    """The archive and t163sb04 differ on a company both have."""

    def __init__(self, quarter: Quarter, counts: QuarterCounts) -> None:
        super().__init__(
            f"{quarter.label}: archive and {T163SB04_SOURCE} differ "
            f"(same {counts.check_same}, different {counts.check_different}, "
            f"format mismatch {counts.check_format_mismatch}, "
            f"missing {counts.check_missing}); 停下來問"
        )
        self.counts = counts


def _summary(counts: QuarterCounts) -> dict[str, Any]:
    return {
        name: value
        for name, value in vars(counts).items()
        if name not in {"errors", "used_members"}
    } | {
        "errors": counts.errors[:20],
        "used_members": dict(sorted(counts.used_members.items())),
    }


def apply_archives(
    db: Session,
    directory: Path,
    start: Quarter,
    end: Quarter,
    *,
    dry_run: bool = False,
    excluded: frozenset[int] = frozenset(),
) -> dict[str, Any]:
    """Write the quarters of DIRECTORY's archives; stops at the first untrusted quarter."""

    targets = quarters_between(start, end)
    manifest = read_manifest(directory)
    absent = [
        quarter.label
        for quarter in targets
        if quarter.label not in manifest["quarters"]
        or not (directory / archive_name(quarter)).exists()
    ]
    if absent:
        return {"status": "failed", "error": f"not downloaded: {', '.join(absent)}"}
    run: IngestionRun | None = None
    if not dry_run:
        now = utcnow()
        run = IngestionRun(
            run_type=RUN_TYPE,
            source="official",
            run_date=_taipei_day(now),
            status="running",
            started_at=now,
            data_as_of=targets[-1].period_end.isoformat(),
            metadata_json={
                "start_quarter": targets[0].label,
                "end_quarter": targets[-1].label,
                "directory": str(directory),
                "excluded_instruments": sorted(excluded),
            },
        )
        db.add(run)
        db.commit()
    coverage: dict[str, Any] = {}
    try:
        aborted = _apply_each(db, run, directory, targets, manifest, coverage, excluded)
    except Exception as exc:
        # Anything unexpected still ends the run as failed (as monthly_revenue does).
        db.rollback()
        if run is not None:
            run.status = "failed"
            run.error = f"error: {exc!r}"
            run.finished_at = utcnow()
            run.metadata_json = {
                **run.metadata_json,
                "coverage_manifest": dict(coverage),
            }
            flag_modified(run, "metadata_json")
            db.commit()
        raise
    status = "failed" if aborted else "success"
    if run is not None:
        run.status = status
        run.error = aborted
        run.finished_at = utcnow()
        db.commit()
    totals: dict[str, int] = {}
    for item in coverage.values():
        for name, value in item.items():
            if isinstance(value, int) and not isinstance(value, bool):
                totals[name] = totals.get(name, 0) + value
    return {
        "status": status,
        "dry_run": dry_run,
        "run_id": run.id if run is not None else None,
        "start_quarter": targets[0].label,
        "end_quarter": targets[-1].label,
        "aborted": aborted,
        "totals": totals,
        "quarters": {
            label: {k: v for k, v in item.items() if k != "used_members"}
            for label, item in coverage.items()
        },
    }


def _apply_each(
    db: Session,
    run: IngestionRun | None,
    directory: Path,
    targets: list[Quarter],
    manifest: dict[str, Any],
    coverage: dict[str, Any],
    excluded: frozenset[int],
) -> str | None:
    """Apply the quarters oldest first; the reason of the first that stopped, or None."""

    aborted: str | None = None
    for quarter in targets:
        entry = manifest["quarters"][quarter.label]
        path = directory / archive_name(quarter)
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        try:
            if digest != entry.get("sha256"):
                raise ArchiveError(
                    f"{quarter.label}: {path.name} sha256 {digest} is not the manifest's"
                )
            counts = apply_quarter(
                db,
                run,
                quarter,
                data,
                digest,
                datetime.fromisoformat(entry["fetched_at"]),
                excluded=excluded,
            )
        except MismatchError as exc:
            db.rollback()
            coverage[quarter.label] = {"status": "failed", **_summary(exc.counts)}
            aborted = str(exc)
        except ArchiveError as exc:
            db.rollback()
            coverage[quarter.label] = {"status": "failed", "error": str(exc)}
            aborted = str(exc)
        else:
            coverage[quarter.label] = {
                "status": "success",
                "archive_sha256": digest,
                **_summary(counts),
            }
        if run is not None:
            # A JSON column does not see the dict change in place, and with
            # expire_on_commit=False an equal new dict is not written either
            # (pipeline.py does the same; review of PR #783).
            run.metadata_json = {
                **run.metadata_json,
                "coverage_manifest": dict(coverage),
            }
            flag_modified(run, "metadata_json")
            run.records = sum(
                item.get("inserted", 0) + item.get("updated", 0) + item.get("dated", 0)
                for item in coverage.values()
            )
            db.commit()
        if aborted:
            break
    return aborted


# --- commands -------------------------------------------------------------------------


def research_refusal(db_path: Path | None = None) -> str | None:
    """Why ``xbrl-apply`` may not run on this database; None for the research one.

    Inside the container both volumes are ``/data/stock.db``; only the research
    volume has ``MARKER_NAME`` next to it (as tools/research/history_backfill.py).
    """

    db = Path(db_path or config.DB_PATH)
    marker = db.parent / MARKER_NAME
    try:
        purpose = json.loads(marker.read_text(encoding="utf-8")).get("purpose")
    except (OSError, ValueError, AttributeError):
        purpose = None
    if purpose != MARKER_PURPOSE:
        return (
            f"{marker} is missing or not a research marker "
            f'(expected {{"purpose": "{MARKER_PURPOSE}"}}): not a research database'
        )
    if not db.is_file():
        return f"{db} does not exist"
    return None


def run_xbrl_fetch(directory: str, start: str, end: str) -> dict[str, Any]:
    try:
        return fetch_archives(Path(directory), Quarter.parse(start), Quarter.parse(end))
    except ValueError as exc:
        return {"status": "failed", "error": str(exc)}


def run_xbrl_apply(
    directory: str,
    start: str,
    end: str,
    *,
    dry_run: bool = False,
    exclude_file: str | None = None,
) -> dict[str, Any]:
    try:
        targets = (Quarter.parse(start), Quarter.parse(end))
        excluded: frozenset[int] = frozenset()
        if exclude_file:
            loaded = json.loads(Path(exclude_file).read_text(encoding="utf-8"))
            if not isinstance(loaded, list) or not all(
                isinstance(item, int) for item in loaded
            ):
                raise ValueError(f"{exclude_file} is not a list of instrument ids")
            excluded = frozenset(loaded)
    except ValueError as exc:
        return {"status": "failed", "error": str(exc)}
    with SessionLocal() as db:
        try:
            return apply_archives(
                db, Path(directory), *targets, dry_run=dry_run, excluded=excluded
            )
        except ValueError as exc:
            db.rollback()
            return {"status": "failed", "error": str(exc)}
