"""Cheap fingerprints of stored inputs, for read models computed ahead (#476).

A GET compares the fingerprint of the inputs a stored projection was made
from with the inputs as they are now, and recomputes when they differ.  Each
part here is a small aggregate or a hash of small tables, read without
building ORM objects, so the check costs milliseconds.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# The small taxonomy and identity tables, as SQL that reads them in primary
# key order.  Memberships and groups whole: the news projection reads the
# sources and periods, group names, types and status.  Of the instruments only
# what the projections read: exchange, symbol and industry (news), status,
# type, ETF category and listing date (action tiers).  The name and the
# watchlist flag are read live by the pages, so changing them invalidates
# nothing.  Columns are read as stored, so a change by the ORM, Core or raw SQL
# shows.
_TAXONOMY_QUERIES = (
    ("group_memberships", "SELECT * FROM group_memberships ORDER BY id"),
    ("theme_groups", "SELECT * FROM theme_groups ORDER BY id"),
    (
        "instruments",
        "SELECT id, market, exchange, symbol, industry, status, instrument_type, "
        "etf_category, listing_date FROM instruments ORDER BY id",
    ),
)


def digest(value: Any) -> str:
    """SHA-256 of ``value`` as canonical JSON."""

    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def taxonomy_digest(db: Session) -> str:
    """One hash of the membership, group and instrument rows (see above)."""

    hasher = hashlib.sha256()
    for table, sql in _TAXONOMY_QUERIES:
        hasher.update(f"\x00{table}\x00".encode())
        for row in db.execute(text(sql)):
            hasher.update(repr(tuple(row)).encode("utf-8"))
            hasher.update(b"\x01")
    return hasher.hexdigest()


def aggregate(db: Session, sql: str, params: dict[str, Any] | None = None) -> list:
    """One aggregate row as a JSON-ready list."""

    row = db.execute(text(sql), params or {}).one()
    return [value if value is None else str(value) for value in row]
