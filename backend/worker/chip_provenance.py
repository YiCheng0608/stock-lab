"""Fill the per-group provenance of stored chip rows from their raw captures (Issue #395).

Before #395 a chip row had one provenance.  A row whose institutional and
margin values came from one collect is labelled ``<institutional>+<margin>``
but links only the institutional capture; a row whose margin was filled by a
later collect (every trading day from 2026-10-19 until #466 dropped the 18:30
daily: the 18:30 collect had no margin yet) is labelled and linked as
institutional only, and the filling capture is recorded only in that run's
``value_fill_groups``.

This writes both groups of every such row.  Nothing is fetched:

- The institutional group is the row's own provenance, which #387 keeps on the
  latest institutional capture; its values are checked against that capture,
  and a row they differ from is listed and makes the run ``partial``.
- The margin group is the stored margin capture that wrote the values: the
  capture of the collect run that ``value_fill_groups`` records for the row,
  else the earliest capture of that exchange and date.  Its values for the
  symbol must equal the stored ones; a row with no such capture keeps its
  stored provenance and is listed as unmatched (``partial``).
- Each group's ``collected_at`` is when it was written into the row
  (``_written_at``), so the row-level ``collected_at`` never moves earlier.

Only rows whose groups are missing or lack a raw payload are read, so a rerun
writes nothing.  Each trading date is committed on its own with ``apply``;
the run is recorded as one ``chip_provenance`` ingestion run.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, timezone
from typing import Any, Callable

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app import chip_provenance as groups_of
from app.raw_paths import payload_file
from app.chip_provenance import INSTITUTIONAL, MARGIN, GroupProvenance
from app.clock import utcnow
from app.domain import OFFICIAL_MARGIN_CHIP_SOURCES
from app.models import ChipSnapshot, IngestionRun, Instrument, RawPayload
from worker import pipeline
from worker.sources import (
    TPEX_CHIP_HISTORY_ENDPOINT,
    TPEX_MARGIN_HISTORY_ENDPOINT,
    TWSE_CHIP_ENDPOINT,
    TWSE_MARGIN_HISTORY_ENDPOINT,
    ChipRecord,
    OfficialDataError,
    _require_reported_date,
    parse_tpex_institutional_rows,
    parse_tpex_margin_rows,
    parse_twse_institutional_rows,
    parse_twse_margin_rows,
)

RUN_TYPE = "chip_provenance"
VERSION = "chip_provenance_v1"
MAX_SAMPLES = 50
# (exchange, group) -> (endpoint, parser)
CAPTURES: dict[tuple[str, str], tuple[str, Callable[..., list[ChipRecord]]]] = {
    ("TWSE", INSTITUTIONAL): (TWSE_CHIP_ENDPOINT, parse_twse_institutional_rows),
    ("TPEx", INSTITUTIONAL): (
        TPEX_CHIP_HISTORY_ENDPOINT,
        parse_tpex_institutional_rows,
    ),
    ("TWSE", MARGIN): (TWSE_MARGIN_HISTORY_ENDPOINT, parse_twse_margin_rows),
    ("TPEx", MARGIN): (TPEX_MARGIN_HISTORY_ENDPOINT, parse_tpex_margin_rows),
}
ENDPOINT_GROUP = {
    endpoint: (exchange, group)
    for (exchange, group), (endpoint, _parser) in CAPTURES.items()
}


class ProvenanceError(Exception):
    """A stored file does not match its SHA-256; nothing is written."""


def _pending_filter() -> Any:
    """Rows whose group provenance is missing or has no raw payload."""

    inst_values = or_(
        ChipSnapshot.foreign_buy.is_not(None),
        ChipSnapshot.trust_buy.is_not(None),
        ChipSnapshot.dealer_buy.is_not(None),
    )
    margin_values = or_(
        ChipSnapshot.margin_balance.is_not(None),
        ChipSnapshot.margin_change.is_not(None),
    )
    return or_(
        and_(
            ChipSnapshot.institutional_source.is_(None),
            ChipSnapshot.margin_source.is_(None),
        ),
        and_(
            ChipSnapshot.institutional_source.is_not(None),
            ChipSnapshot.institutional_raw_payload_id.is_(None),
        ),
        and_(
            ChipSnapshot.margin_source.is_not(None),
            ChipSnapshot.margin_raw_payload_id.is_(None),
        ),
        and_(ChipSnapshot.institutional_source.is_(None), inst_values),
        and_(ChipSnapshot.margin_source.is_(None), margin_values),
    )


def _load(capture: RawPayload) -> Any:
    """The capture's payload for its date; None when it reports another date."""

    content = payload_file(capture.payload_path).read_bytes()
    if hashlib.sha256(content).hexdigest() != capture.sha256:
        raise ProvenanceError(
            f"raw payload {capture.id} does not match its SHA-256: {capture.payload_path}"
        )
    payload = json.loads(content.decode("utf-8"))
    try:
        _require_reported_date(
            payload,
            date.fromisoformat((capture.data_as_of or "")[:10]),
            capture.endpoint.split("?", 1)[0],
        )
    except OfficialDataError:
        return None
    return payload


def _fill_runs(db: Session) -> dict[tuple[str, str, str], list[int]]:
    """(exchange, date, symbol) -> collect runs that filled the row's margin values."""

    raw_run = dict(db.execute(select(RawPayload.id, RawPayload.ingestion_run_id)).all())
    runs: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for (metadata,) in db.execute(
        select(IngestionRun.metadata_json).where(
            func.json_extract(IngestionRun.metadata_json, "$.value_fill_groups").is_not(
                None
            )
        )
    ):
        for fill in (metadata or {}).get("value_fill_groups") or []:
            if fill.get("table") != "chip_snapshots" or not set(
                fill.get("fields") or []
            ) & set(groups_of.GROUP_FIELDS[MARGIN]):
                continue
            run_id = raw_run.get(fill.get("raw_payload_id"))
            if run_id is None:
                continue
            for symbol in fill.get("symbols") or []:
                runs[(fill["exchange"], fill["trading_date"], symbol)].append(run_id)
    return runs


class _Captures:
    """The stored captures of one trading date, parsed once each."""

    def __init__(self, db: Session, trading_date: date) -> None:
        self.by_group: dict[tuple[str, str], list[RawPayload]] = defaultdict(list)
        self.values: dict[int, dict[str, ChipRecord] | None] = {}
        self.unreadable: list[dict[str, Any]] = []
        rows = db.scalars(
            select(RawPayload)
            .where(RawPayload.data_as_of == trading_date.isoformat())
            .order_by(RawPayload.collected_at, RawPayload.id)
        ).all()
        for row in rows:
            key = ENDPOINT_GROUP.get((row.endpoint or "").split("?", 1)[0])
            if key is not None:
                self.by_group[key].append(row)
        self.trading_date = trading_date

    def records(
        self, key: tuple[str, str], capture: RawPayload
    ) -> dict[str, ChipRecord]:
        if capture.id not in self.values:
            try:
                payload = _load(capture)
            except (OSError, ValueError) as exc:
                self.unreadable.append(
                    {"raw_payload_id": capture.id, "error": str(exc)}
                )
                payload = None
            parser = CAPTURES[key][1]
            self.values[capture.id] = (
                None
                if payload is None
                else {
                    record.symbol: record
                    for record in parser(
                        payload,
                        trading_date=self.trading_date,
                        data_as_of=self.trading_date.isoformat(),
                        payload_sha256=capture.sha256,
                    )
                }
            )
        return self.values[capture.id] or {}


def _equal(row: ChipSnapshot, record: ChipRecord | None, group: str) -> bool:
    if record is None:
        return False
    return all(
        getattr(row, name) == pipeline._safe_float(getattr(record, name))
        for name in groups_of.GROUP_FIELDS[group]
    )


def _margin_capture(
    row: ChipSnapshot,
    exchange: str,
    symbol: str,
    captures: _Captures,
    fill_runs: list[int],
) -> tuple[RawPayload | None, str]:
    """The margin capture that wrote the row's margin values, and how it was found."""

    key = (exchange, MARGIN)
    candidates = captures.by_group.get(key, [])
    for run_id in fill_runs:
        for capture in candidates:
            if capture.ingestion_run_id == run_id and _equal(
                row, captures.records(key, capture).get(symbol), MARGIN
            ):
                return capture, "fill_run"
    for capture in candidates:
        if _equal(row, captures.records(key, capture).get(symbol), MARGIN):
            return capture, "earliest_equal"
    return None, "unmatched"


def _written_at(
    stored: GroupProvenance | None, capture: RawPayload, row: ChipSnapshot
) -> Any:
    """The time the margin group was written into the row (DATA_SOURCES 籌碼來源).

    A group the row already names keeps its time: the row-level
    ``collected_at`` the old code wrote with it.  A group the row did not name
    (its margin filled by a later collect) was written by the collect that
    captured the file, so the capture time stands in for the unrecorded write
    time; never earlier than the row's own time, so the row-level summary only
    stays or moves later.
    """

    if stored is not None and stored.collected_at is not None:
        return stored.collected_at
    times = [t for t in (capture.collected_at, row.collected_at) if t is not None]
    return max(times) if times else None


def fill_provenance(db: Session, *, apply: bool = False) -> dict[str, Any]:
    """Fill the group columns of every pending row; commit per date with ``apply``."""

    pending = _pending_filter()
    sources_before = dict(
        db.execute(
            select(ChipSnapshot.source, func.count()).group_by(ChipSnapshot.source)
        ).all()
    )
    dates = list(
        db.scalars(
            select(ChipSnapshot.trading_date)
            .where(pending)
            .distinct()
            .order_by(ChipSnapshot.trading_date)
        )
    )
    fill_runs = _fill_runs(db)
    counts: dict[str, int] = defaultdict(int)
    unmatched: list[dict[str, Any]] = []
    institutional_mismatch: list[dict[str, Any]] = []
    unreadable: list[dict[str, Any]] = []
    written_dates: list[str] = []
    for trading_date in dates:
        captures = _Captures(db, trading_date)
        rows = db.execute(
            select(ChipSnapshot, Instrument.exchange, Instrument.symbol)
            .join(Instrument, Instrument.id == ChipSnapshot.instrument_id)
            .where(ChipSnapshot.trading_date == trading_date, pending)
            .order_by(Instrument.exchange, Instrument.symbol)
        ).all()
        day_written = 0
        for row, exchange, symbol in rows:
            counts["rows_examined"] += 1
            stored = groups_of.stored_groups(row)
            groups = dict(stored)
            label = {
                "exchange": exchange,
                "symbol": symbol,
                "trading_date": trading_date.isoformat(),
                "source": row.source,
            }
            institutional = stored[INSTITUTIONAL]
            if institutional is not None:
                capture = (
                    db.get(RawPayload, institutional.raw_payload_id)
                    if institutional.raw_payload_id is not None
                    else None
                )
                key = (exchange, INSTITUTIONAL)
                if capture is None or not _equal(
                    row, captures.records(key, capture).get(symbol), INSTITUTIONAL
                ):
                    counts["institutional_mismatch"] += 1
                    if len(institutional_mismatch) < MAX_SAMPLES:
                        institutional_mismatch.append(
                            {**label, "raw_payload_id": institutional.raw_payload_id}
                        )
            elif any(
                getattr(row, name) is not None
                for name in groups_of.GROUP_FIELDS[INSTITUTIONAL]
            ):
                counts["institutional_unsourced"] += 1
            margin_held = any(
                getattr(row, name) is not None
                for name in groups_of.GROUP_FIELDS[MARGIN]
            )
            if margin_held or stored[MARGIN] is not None:
                capture, how = _margin_capture(
                    row,
                    exchange,
                    symbol,
                    captures,
                    fill_runs.get((exchange, trading_date.isoformat(), symbol), []),
                )
                counts[f"margin_{how}"] += 1
                if capture is None:
                    if len(unmatched) < MAX_SAMPLES:
                        unmatched.append(label)
                    groups[MARGIN] = stored[MARGIN]
                else:
                    groups[MARGIN] = GroupProvenance(
                        OFFICIAL_MARGIN_CHIP_SOURCES[exchange],
                        capture.id,
                        pipeline._as_datetime(capture.data_as_of, trading_date),
                        _written_at(stored[MARGIN], capture, row),
                    )
            if groups == groups_of.explicit_groups(row) and groups_of.has_group_columns(
                row
            ):
                continue
            groups_of.write_groups(row, groups)
            counts["rows_written"] += 1
            day_written += 1
        unreadable.extend(captures.unreadable)
        if day_written:
            written_dates.append(trading_date.isoformat())
        if apply:
            db.commit()
        else:
            db.flush()
    sources_after = dict(
        db.execute(
            select(ChipSnapshot.source, func.count()).group_by(ChipSnapshot.source)
        ).all()
    )
    still_pending = db.scalar(select(func.count()).where(pending))
    result: dict[str, Any] = {
        "status": (
            "partial"
            if unmatched or unreadable or institutional_mismatch
            else "success"
        ),
        "version": VERSION,
        "applied": apply,
        "dates": len(dates),
        "first_date": dates[0].isoformat() if dates else None,
        "last_date": dates[-1].isoformat() if dates else None,
        "written_dates": len(written_dates),
        **dict(sorted(counts.items())),
        "pending_after": still_pending,
        "sources_before": sources_before,
        "sources_after": sources_after,
        "unmatched_samples": unmatched,
        "institutional_mismatch_samples": institutional_mismatch,
        "unreadable_captures": unreadable,
    }
    if not apply:
        db.rollback()
        return result
    now = utcnow()
    db.add(
        IngestionRun(
            run_type=RUN_TYPE,
            source="official",
            run_date=now.replace(tzinfo=timezone.utc)
            .astimezone(pipeline.TAIPEI)
            .date(),
            status=result["status"],
            records=counts["rows_written"],
            data_as_of=result["last_date"],
            metadata_json=result,
            started_at=now,
            finished_at=utcnow(),
        )
    )
    db.commit()
    return result


def run_fill_provenance(*, apply: bool = False) -> dict[str, Any]:
    with pipeline.SessionLocal() as db:
        try:
            return fill_provenance(db, apply=apply)
        except ProvenanceError as exc:
            db.rollback()
            return {"status": "failed", "error": str(exc), "applied": False}
