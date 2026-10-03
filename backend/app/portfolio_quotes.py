"""Read local portfolio inputs without claiming source or market-date evidence."""
from __future__ import annotations

from datetime import date, datetime
import math
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def read_close(value: Any) -> tuple[float | None, str]:
    if value is None:
        return None, "missing"
    if type(value) not in {int, float}:
        return None, "invalid"
    try:
        number = float(value)
    except OverflowError:
        return None, "invalid"
    return (number, "known") if math.isfinite(number) and number > 0 else (None, "invalid")


def read_record(value: Any, field: str) -> tuple[str | None, str]:
    """Classify the current stored text, never its admission or date evidence."""
    if value is None:
        return None, "missing"
    if type(value) is not str or not value:
        return None, "invalid"
    try:
        value.encode("utf-8", errors="strict")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            return None, "invalid"
        if field == "date":
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) or date.fromisoformat(value).isoformat() != value:
                return None, "invalid"
        elif field in {"data_as_of", "collected_at"}:
            if len(value) > 64:
                return None, "invalid"
            matched = re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ]([0-9]{2}):([0-9]{2}):([0-9]{2})"
                r"(?:[.,][0-9]+)?(?:Z|[+-]([0-9]{2}):([0-9]{2})(?::([0-9]{2})(?:[.,][0-9]+)?)?)?", value)
            if not matched or any(int(component) >= limit for component, limit in zip(matched.groups(), (24, 60, 60, 24, 60, 60))
                                  if component is not None):
                return None, "invalid"
            datetime.fromisoformat(value)
        elif field == "source":
            if re.fullmatch(r"[\s\ufeff]+", value) or len(value) > 120:
                return None, "invalid"
        else:
            return None, "invalid"
    except (ValueError, UnicodeError):
        return None, "invalid"
    return value, "known"


def portfolio_quote(db: Session, instrument_id: int) -> tuple[dict, dict | None]:
    # Untyped columns deliberately avoid ORM Date/DateTime result processors.
    # Do not cast numeric text to a price, fetch irrelevant OHLC/volume, or
    # fall back to an earlier row when the latest stored row is malformed.
    row = db.execute(text(
        "SELECT close, trading_date, source, data_as_of, collected_at "
        "FROM market_bars WHERE instrument_id = :instrument_id "
        "ORDER BY trading_date DESC, id DESC LIMIT 1"
    ), {"instrument_id": instrument_id}).mappings().first()
    close, close_status = read_close(row["close"] if row is not None else None)
    records = {field: read_record(row["trading_date" if field == "date" else field] if row is not None else None, field)
               for field in ("date", "source", "data_as_of", "collected_at")}
    quote = {
        "close": close, "close_status": close_status,
        "recorded": {field: value for field, (value, _status) in records.items()},
        "record_status": {field: status for field, (_value, status) in records.items()},
        "source_verification": "unverified", "date_verification": "unverified",
    }
    # Portfolio-only compatibility projection; this is not a complete Bar.
    projected = {"close": close, **quote["recorded"]} if row is not None else None
    return quote, projected
