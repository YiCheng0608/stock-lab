"""Bounded action read values; classification does not establish provenance."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
import re
from typing import Any, Iterable

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


def read_market_date(value: Any) -> date | None:
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def read_market_source(value: Any) -> str | None:
    if type(value) is not str or not value or len(value) > 120:
        return None
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        return None
    if re.fullmatch(r"[\s\ufeff]+", value) or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    return value


def read_positive_price(value: Any) -> float | None:
    # SQLite affinity is already applied. Do not rescue stored TEXT/BLOB by
    # coercion; these are read classifications, not a new price admission gate.
    if type(value) not in {int, float}:
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) and number > 0 else None


@dataclass(frozen=True)
class DecisionMarketRead:
    id: int
    instrument_id: int
    trading_date: date | None
    close: float | None
    adj_close: float | None
    source: str | None
    is_suspended: bool | None
    raw_payload_id: int | None

    @property
    def invalid_fields(self) -> list[str]:
        return [field for field in ("trading_date", "close", "source", "is_suspended")
                if getattr(self, field) is None]

    @property
    def core_valid(self) -> bool:
        return not self.invalid_fields


def _project(row: Any) -> DecisionMarketRead:
    suspension = row["is_suspended"]
    raw_id = row["raw_payload_id"]
    return DecisionMarketRead(
        id=row["id"], instrument_id=row["instrument_id"],
        trading_date=read_market_date(row["trading_date"]),
        close=read_positive_price(row["close"]), adj_close=read_positive_price(row["adj_close"]),
        source=read_market_source(row["source"]),
        is_suspended=bool(suspension) if type(suspension) is int and suspension in {0, 1} else None,
        raw_payload_id=raw_id if type(raw_id) is int and raw_id > 0 else None,
    )


def load_decision_market_reads(
    db: Session, instrument_ids: Iterable[int], as_of: date | None, *, limit: int = 120,
) -> tuple[dict[int, list[DecisionMarketRead]], dict[int, DecisionMarketRead]]:
    ids = set(instrument_ids)
    if not ids:
        return {}, {}
    query = text(
        "SELECT id, instrument_id, trading_date, close, adj_close, source, is_suspended, raw_payload_id "
        "FROM market_bars WHERE instrument_id IN :ids "
        "ORDER BY instrument_id, trading_date DESC, id DESC"
    ).bindparams(bindparam("ids", expanding=True))
    candidates: dict[int, list[Any]] = {item_id: [] for item_id in ids}
    unlocated: dict[int, DecisionMarketRead] = {}
    for row in db.execute(query, {"ids": sorted(ids)}).mappings():
        trading_date = read_market_date(row["trading_date"])
        if trading_date is None:
            # A malformed date has no known position relative to the cutoff.
            # Retain its identity and block latest-price fallback even when its
            # raw text sorts outside the cutoff or the bounded history window.
            unlocated.setdefault(row["instrument_id"], _project(row))
        elif as_of is not None and trading_date > as_of:
            continue
        rows = candidates[row["instrument_id"]]
        if len(rows) < limit:
            rows.append(row)
    # Cap precedes value validation: removing bad rows must not refill history
    # from earlier rows or change the persisted ordering of a valid input set.
    return {item_id: [_project(row) for row in rows] for item_id, rows in candidates.items()}, unlocated


def market_read_status(row: DecisionMarketRead | None) -> dict[str, Any]:
    return {"status": "missing" if row is None else "known" if row.core_valid else "invalid",
            "invalid_fields": row.invalid_fields if row is not None else []}
