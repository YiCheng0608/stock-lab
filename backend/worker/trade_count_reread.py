"""Fill ``market_bars.trade_count`` of the research DB from the stored quote captures (#1094).

``worker.cli trade-count reread`` reads, for every ``twse`` / ``tpex`` bar whose
``trade_count`` is still null, the capture the bar itself cites
(``market_bars.raw_payload_id``), never one found by ``raw_payloads.data_as_of``:
a ``STOCK_DAY_ALL`` captured at 18:30 can still be the day before's table (#1093
report 7210725240).  The capture is read and parsed as instrument repair reads it
(``instrument_repair._quote_bars``: the SHA-256 is checked, the reported date
too, and the same parser as collect, so the value is the one collect would have
written), and the bar takes the trade count of its own row, matched by exchange,
symbol and trading date, only when the row's volume equals the bar's.

A file missing from this volume (the seed rows copied from production, and
2024-09-30 onwards) is read from ``--fallback-raw-dir`` (the production volume's
``raw`` mounted read-only) under the same path relative to its raw directory,
as ``tools/audit/raw_files.py --fallback-raw-dir`` finds it.

Only fills nulls; one transaction a calendar month, so a stopped run resumes and
a second run writes nothing.  Sends no request.  Only on the research database
(``quarterly_xbrl.research_refusal``), holding maintenance mode (worker.cli).
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import bindparam, func, select
from sqlalchemy.orm import Session

from app.models import Instrument, MarketBar, RawPayload
from app.raw_paths import legacy_relative, payload_file
from app.raw_paths import raw_dir as stored_raw_dir
from worker.instrument_repair import _is_quote_capture, _quote_bars
from worker.quarterly_xbrl import research_refusal
from worker.sources import BarRecord, OfficialDataError

SOURCES = ("twse", "tpex")
# Bars of a source are matched only to rows of its own exchange.
EXCHANGE_OF_SOURCE = {"twse": "TWSE", "tpex": "TPEx"}
# Why a bar got no value; the counts and the first samples go in the result.
RAW_MISSING = "no_raw_payload_id"
RAW_ROW_MISSING = "raw_payload_row_missing"
NOT_QUOTE = "not_a_quote_capture"
FILE_MISSING = "raw_file_missing"
SHA_MISMATCH = "raw_sha256_mismatch"
UNREADABLE = "raw_unreadable"
REJECTED = "raw_rejected"
NO_ROW = "no_row_in_raw"
BLANK = "blank_in_raw"
VOLUME_MISMATCH = "volume_mismatch"
MAX_SAMPLES = 20

_TABLE = MarketBar.__table__
_FILL = (
    _TABLE.update()
    .where(_TABLE.c.id == bindparam("bar_id"), _TABLE.c.trade_count.is_(None))
    .values(trade_count=bindparam("value"))
)


def _months(first: date, last: date) -> list[tuple[date, date]]:
    """[start, end) of every calendar month from FIRST's to LAST's."""

    result = []
    month = date(first.year, first.month, 1)
    while month <= last:
        following = (
            date(month.year + 1, 1, 1)
            if month.month == 12
            else date(month.year, month.month + 1, 1)
        )
        result.append((month, following))
        month = following
    return result


def _fallback_file(payload_path: str, path: Path, fallback: Path) -> Path | None:
    """PAYLOAD_PATH's file under FALLBACK, as tools/audit/raw_files.py relates them."""

    relative = legacy_relative(payload_path)
    if relative is None:
        try:
            relative = PurePosixPath(path.relative_to(stored_raw_dir()).as_posix())
        except ValueError:
            return None
    return fallback.joinpath(*relative.parts)


class _Unreadable(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


def _load(raw: RawPayload, fallback: Path | None) -> tuple[Any, bool]:
    """The capture's JSON and whether it was read from FALLBACK."""

    if not raw.payload_path or not raw.sha256:
        raise _Unreadable(UNREADABLE, "missing payload path or sha256")
    path = payload_file(raw.payload_path)
    from_fallback = False
    if not path.is_file() and fallback is not None:
        candidate = _fallback_file(raw.payload_path, path, fallback)
        if candidate is not None and candidate.is_file():
            path, from_fallback = candidate, True
    try:
        encoded = path.read_bytes()
    except FileNotFoundError:
        raise _Unreadable(FILE_MISSING, str(path)) from None
    except OSError as exc:
        raise _Unreadable(UNREADABLE, f"{path}: {exc}") from None
    if hashlib.sha256(encoded).hexdigest() != raw.sha256:
        raise _Unreadable(SHA_MISMATCH, str(path))
    try:
        return json.loads(encoded), from_fallback
    except ValueError as exc:
        raise _Unreadable(UNREADABLE, f"{path}: {exc}") from None


Rows = dict[tuple[str, str, date], BarRecord]


def _capture_rows(
    db: Session, raw_id: int, fallback: Path | None, read: Counter[str]
) -> Rows | _Unreadable:
    raw = db.get(RawPayload, raw_id)
    if raw is None:
        return _Unreadable(RAW_ROW_MISSING)
    if not _is_quote_capture(raw.endpoint):
        return _Unreadable(NOT_QUOTE, raw.endpoint)
    try:
        payload, from_fallback = _load(raw, fallback)
    except _Unreadable as exc:
        return exc
    try:
        records = _quote_bars(raw, payload)
    except OfficialDataError as exc:
        return _Unreadable(REJECTED, str(exc)[:200])
    except Exception as exc:
        # A parser failure on one old capture leaves only its bars null.
        return _Unreadable(UNREADABLE, f"{type(exc).__name__}: {exc}"[:200])
    read["fallback" if from_fallback else "volume"] += 1
    return {
        (record.exchange, record.symbol, record.trading_date): record
        for record in records
    }


def _month(
    db: Session,
    start: date,
    end: date,
    fallback: Path | None,
    written: Counter[tuple[int, str]],
    missed: Counter[str],
    samples: list[dict[str, Any]],
    read: Counter[str],
) -> int:
    """Fill one month's null trade counts in one transaction; return the bars written."""

    bars = db.execute(
        select(
            MarketBar.id,
            MarketBar.trading_date,
            MarketBar.raw_payload_id,
            MarketBar.source,
            MarketBar.volume,
            Instrument.symbol,
        )
        .join(Instrument, Instrument.id == MarketBar.instrument_id)
        .where(
            MarketBar.source.in_(SOURCES),
            MarketBar.trade_count.is_(None),
            MarketBar.trading_date >= start,
            MarketBar.trading_date < end,
        )
        .order_by(MarketBar.raw_payload_id, MarketBar.id)
    ).all()
    by_raw: dict[int | None, list[Any]] = defaultdict(list)
    for bar in bars:
        by_raw[bar.raw_payload_id].append(bar)

    def miss(reason: str, bar: Any, detail: str = "") -> None:
        missed[reason] += 1
        if len(samples) < MAX_SAMPLES:
            samples.append(
                {
                    "reason": reason,
                    "bar_id": bar.id,
                    "symbol": bar.symbol,
                    "trading_date": bar.trading_date.isoformat(),
                    "raw_payload_id": bar.raw_payload_id,
                    **({"detail": detail} if detail else {}),
                }
            )

    fills: list[dict[str, int]] = []
    for raw_id, group in by_raw.items():
        if raw_id is None:
            for bar in group:
                miss(RAW_MISSING, bar)
            continue
        rows = _capture_rows(db, raw_id, fallback, read)
        if isinstance(rows, _Unreadable):
            for bar in group:
                miss(rows.reason, bar, rows.detail)
            continue
        for bar in group:
            record = rows.get(
                (EXCHANGE_OF_SOURCE[bar.source], bar.symbol, bar.trading_date)
            )
            if record is None:
                miss(NO_ROW, bar)
            elif record.volume != bar.volume:
                miss(VOLUME_MISMATCH, bar, f"{bar.volume} != {record.volume}")
            elif record.trade_count is None:
                miss(BLANK, bar)
            else:
                fills.append({"bar_id": bar.id, "value": record.trade_count})
                written[(bar.trading_date.year, bar.source)] += 1
    if fills:
        db.execute(_FILL, fills)
    db.commit()
    return len(fills)


def reread(
    db: Session,
    first: date | None = None,
    last: date | None = None,
    *,
    fallback_raw_dir: str | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    fallback = Path(fallback_raw_dir) if fallback_raw_dir else None
    if fallback is not None and not fallback.is_dir():
        return {"status": "failed", "error": f"{fallback} is not a directory"}
    if first is None or last is None:
        low, high = db.execute(
            select(
                func.min(MarketBar.trading_date), func.max(MarketBar.trading_date)
            ).where(MarketBar.source.in_(SOURCES))
        ).one()
        first, last = first or low, last or high
    if first is None or last is None:
        return {"status": "success", "written": 0, "months": 0, "by_year": {}}
    if first > last:
        return {"status": "failed", "error": "--from must not be after --to"}
    written: Counter[tuple[int, str]] = Counter()
    missed: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    read: Counter[str] = Counter()
    months = _months(first, last)
    for start, end in months:
        count = _month(
            db,
            max(start, first),
            min(end, date.fromordinal(last.toordinal() + 1)),
            fallback,
            written,
            missed,
            samples,
            read,
        )
        # One progress line a month on stderr; stdout keeps the one JSON result.
        print(
            json.dumps(
                {
                    "month": start.strftime("%Y-%m"),
                    "written": count,
                    "not_written": sum(missed.values()),
                    "seconds": round(time.monotonic() - started, 1),
                }
            ),
            file=sys.stderr,
            flush=True,
        )
    by_year: dict[str, dict[str, int]] = {}
    for (year, source), count in sorted(written.items()):
        by_year.setdefault(str(year), {})[source] = count
    return {
        "status": "partial" if missed else "success",
        "from": first.isoformat(),
        "to": last.isoformat(),
        "months": len(months),
        "written": sum(written.values()),
        "by_year": by_year,
        "not_written": dict(sorted(missed.items())),
        "samples": samples,
        "captures_read": {
            "volume": read["volume"],
            "fallback": read["fallback"],
        },
        "fallback_raw_dir": None if fallback is None else str(fallback),
        "seconds": round(time.monotonic() - started, 1),
    }


def run_trade_count_reread(
    start: str | None = None,
    end: str | None = None,
    *,
    fallback_raw_dir: str | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """``worker.cli trade-count reread``: refused (exit 2) off the research DB."""

    from app.db import SessionLocal

    refused = research_refusal(db_path)
    if refused is not None:
        return {"status": "refused", "error": refused}
    try:
        first = date.fromisoformat(start) if start else None
        last = date.fromisoformat(end) if end else None
    except ValueError as exc:
        return {"status": "failed", "error": str(exc)}
    with SessionLocal() as db:
        return reread(db, first, last, fallback_raw_dir=fallback_raw_dir)
