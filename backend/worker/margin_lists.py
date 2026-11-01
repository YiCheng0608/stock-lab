"""Official margin-trading lists from stored margin reports (Issue #392).

The margin balance report collect already stores for every session lists the
session's credit-trading securities: TWSE MI_MARGN ``selectType=ALL``
(table 融資融券彙總, columns 代號／註記) and TPEx 上櫃股票融資融券餘額 (columns
代號／備註).  A code that is absent from a stored list is not a
margin-financing security that day; analyze then records the margin condition
as not applicable (app.margin_lists) instead of missing data.

Nothing is fetched.  For each exchange and session the latest stored capture
that reports that date and has rows is the list; a list whose codes and notes
equal the stored one is not rewritten.  A session with no such capture, or
whose list is more than 5% shorter than the previous stored one, gets no row,
and analyze keeps its margin data missing.  collect runs this for the
sessions it stored; ``worker.cli margin-lists`` backfills a date range.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MarginList, RawPayload
from worker.sources import (
    TPEX_MARGIN_HISTORY_ENDPOINT,
    TWSE_MARGIN_HISTORY_ENDPOINT,
    OfficialDataError,
    _require_reported_date,
)

RUN_TYPE = "margin_lists"
# exchange -> (raw_payloads.source, endpoint without the query, list source)
CAPTURES: dict[str, tuple[str, str, str]] = {
    "TWSE": ("twse", TWSE_MARGIN_HISTORY_ENDPOINT, "twse_margin"),
    "TPEx": ("tpex", TPEX_MARGIN_HISTORY_ENDPOINT, "tpex_margin"),
}
MAX_SAMPLES = 50
# A list more than this share shorter than the exchange's previous stored list
# is not written (``suspicious_drop``): a truncated report would make the
# missing codes "not applicable" and loosen the rule (#407 review).  The real
# lists of 2024-09-30～2026-10-30 never shrank by more than 0.24% a day.
MAX_MEMBER_DROP = 0.05


def _table(payload: Any, exchange: str) -> dict[str, Any] | None:
    """The per-security table of a margin report; None when it has none."""

    if not isinstance(payload, dict) or not isinstance(payload.get("tables"), list):
        return None
    note_field = "註記" if exchange == "TWSE" else "備註"
    for table in payload["tables"]:
        fields = table.get("fields") if isinstance(table, dict) else None
        if (
            isinstance(fields, list)
            and fields
            and str(fields[0]).strip() == "代號"
            and str(fields[-1]).strip() == note_field
        ):
            return table
    return None


def parse_margin_list(payload: Any, exchange: str) -> dict[str, str] | None:
    """Code -> stripped note of every security row; None without such rows.

    Rows without a code (TPEx's 合計 rows) are not securities.  A report whose
    table is missing or empty gives None, never an empty list: an empty list
    would make every security "not a margin security".
    """

    table = _table(payload, exchange)
    if table is None:
        return None
    members: dict[str, str] = {}
    for row in table.get("data") or []:
        if not isinstance(row, list) or not row:
            continue
        code = str(row[0] or "").strip()
        if not code:
            continue
        members[code] = str(row[-1] or "").strip()
    return members or None


class MarginListError(Exception):
    """A stored file is unreadable, not JSON or not its SHA-256; that session
    is not written."""


def _load(capture: RawPayload, trading_date: date) -> Any:
    try:
        content = Path(capture.payload_path or "").read_bytes()
    except OSError as exc:
        raise MarginListError(
            f"raw payload {capture.id} cannot be read: {capture.payload_path}: {exc}"
        ) from exc
    if hashlib.sha256(content).hexdigest() != capture.sha256:
        raise MarginListError(
            f"raw payload {capture.id} does not match its SHA-256: "
            f"{capture.payload_path}"
        )
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarginListError(
            f"raw payload {capture.id} is not JSON: {capture.payload_path}: {exc}"
        ) from exc
    try:
        _require_reported_date(payload, trading_date, capture.endpoint.split("?")[0])
    except OfficialDataError:
        return None
    return payload


def _captures(db: Session, exchange: str, trading_date: date) -> list[RawPayload]:
    source, endpoint, _list_source = CAPTURES[exchange]
    rows = db.scalars(
        select(RawPayload)
        .where(
            RawPayload.source == source,
            RawPayload.endpoint.like(f"{endpoint}%"),
            RawPayload.data_as_of.like(f"{trading_date.isoformat()}%"),
        )
        .order_by(RawPayload.collected_at.desc(), RawPayload.id.desc())
    ).all()
    # ``like`` also matches a longer path; keep the endpoint itself.
    return [row for row in rows if row.endpoint.split("?")[0] == endpoint]


def _session_dates(db: Session, start: date | None, end: date | None) -> list[date]:
    """Sessions with a stored margin capture of either exchange, in order."""

    found: set[date] = set()
    for source, endpoint, _list_source in CAPTURES.values():
        query = select(RawPayload.data_as_of).where(
            RawPayload.source == source, RawPayload.endpoint.like(f"{endpoint}%")
        )
        for (value,) in db.execute(query).all():
            try:
                day = date.fromisoformat((value or "")[:10])
            except ValueError:
                continue
            if (start is None or day >= start) and (end is None or day <= end):
                found.add(day)
    return sorted(found)


def store_margin_list(db: Session, exchange: str, trading_date: date) -> str:
    """Write one exchange's list of one session from stored raw.

    Returns ``written``, ``unchanged``, ``missing`` (no capture of the date
    with rows) or ``suspicious_drop`` (more than MAX_MEMBER_DROP shorter than
    the previous stored list).  Nothing is written in the last two cases and
    an earlier row of the date stays.
    """

    _source, _endpoint, list_source = CAPTURES[exchange]
    for capture in _captures(db, exchange, trading_date):
        payload = _load(capture, trading_date)
        members = parse_margin_list(payload, exchange) if payload is not None else None
        if members is None:
            continue
        row = db.scalar(
            select(MarginList).where(
                MarginList.exchange == exchange,
                MarginList.trading_date == trading_date,
            )
        )
        if row is not None and row.members_json == members:
            return "unchanged"
        previous = db.scalar(
            select(MarginList.member_count)
            .where(
                MarginList.exchange == exchange,
                MarginList.trading_date < trading_date,
            )
            .order_by(MarginList.trading_date.desc())
            .limit(1)
        )
        if previous and len(members) < previous * (1 - MAX_MEMBER_DROP):
            return "suspicious_drop"
        if row is None:
            row = MarginList(exchange=exchange, trading_date=trading_date)
            db.add(row)
        row.source = list_source
        row.endpoint = capture.endpoint
        row.data_as_of = trading_date.isoformat()
        row.collected_at = capture.collected_at
        row.raw_payload_id = capture.id
        row.member_count = len(members)
        row.members_json = members
        db.flush()
        return "written"
    return "missing"


def sync_margin_lists(
    db: Session,
    dates: Iterable[date] | None = None,
    *,
    start: date | None = None,
    end: date | None = None,
    commit_each: bool = False,
) -> dict[str, Any]:
    """Store both exchanges' lists of ``dates`` (default: every stored session).

    ``commit_each`` commits each session on its own (the backfill CLI);
    collect leaves the commit to its own transaction.  A file that cannot be
    read, is not JSON or does not match its SHA-256 stops the run at that
    session (earlier sessions stay written when committed) and the result is
    ``failed`` with ``failed_date``.  A session without a list or with a
    suspicious drop makes it ``partial``.
    """

    days = sorted(set(dates)) if dates is not None else _session_dates(db, start, end)
    counts = {"written": 0, "unchanged": 0, "missing": 0, "suspicious_drop": 0}
    missing: list[str] = []
    suspicious: list[str] = []
    for day in days:
        try:
            for exchange in CAPTURES:
                outcome = store_margin_list(db, exchange, day)
                counts[outcome] += 1
                samples = {"missing": missing, "suspicious_drop": suspicious}
                if outcome in samples and len(samples[outcome]) < MAX_SAMPLES:
                    samples[outcome].append(f"{exchange}:{day.isoformat()}")
        except MarginListError as exc:
            if commit_each:
                db.rollback()
            return {
                "status": "failed",
                "error": str(exc),
                "failed_date": day.isoformat(),
                "dates": len(days),
                **counts,
                "missing_samples": missing,
                "suspicious_drop_samples": suspicious,
            }
        if commit_each:
            db.commit()
    return {
        "status": "success"
        if counts["missing"] == counts["suspicious_drop"] == 0
        else "partial",
        "dates": len(days),
        "first_date": days[0].isoformat() if days else None,
        "last_date": days[-1].isoformat() if days else None,
        **counts,
        "missing_samples": missing,
        "suspicious_drop_samples": suspicious,
    }


def run_margin_lists(
    start: date | None = None, end: date | None = None
) -> dict[str, Any]:
    """``worker.cli margin-lists``: backfill the lists from stored raw."""

    from worker import pipeline  # pipeline imports this module

    with pipeline.SessionLocal() as db:
        return sync_margin_lists(db, start=start, end=end, commit_each=True)
