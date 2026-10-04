"""Stock-detail read classification; known syntax never proves price provenance."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import math
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from .decision_market_reads import read_market_date, read_positive_price
from .portfolio_quotes import read_record
from .units import volume_exact_text


@dataclass(frozen=True)
class StockMarketRead:
    id: int
    instrument_id: int
    trading_date: date | None
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    adj_close: float | None
    volume: int | None
    turnover: float | None
    turnover_status: str | None
    turnover_reason: str | None
    source: str | None
    data_as_of: datetime | None
    collected_at: datetime | None
    raw_payload_id: int | None
    is_suspended: bool | None
    fields: dict[str, str]

    def read_state(self) -> dict[str, Any]:
        core = ("trading_date", "open", "high", "low", "close", "volume", "source", "is_suspended", "ohlc")
        invalid = [key for key in core if self.fields.get(key) == "invalid"]
        missing = [key for key in core if self.fields.get(key) == "missing"]
        return {"status": "invalid" if invalid else "missing" if missing else "known",
                "invalid_fields": invalid, "missing_fields": missing,
                "metadata_fields": {key: state for key, state in self.fields.items() if key not in core}}

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "date": self.trading_date.isoformat() if self.trading_date else None,
                **{key: getattr(self, key) for key in ("open", "high", "low", "close", "adj_close", "volume",
                    "turnover", "turnover_status", "turnover_reason", "source", "is_suspended")},
                "volume_exact": volume_exact_text(self.volume),
                "data_as_of": self.data_as_of.isoformat() if self.data_as_of else None,
                "collected_at": self.collected_at.isoformat() if self.collected_at else None,
                "market_read": self.read_state()}


def _project(row: Any) -> StockMarketRead:
    values: dict[str, Any] = {"id": row["id"], "instrument_id": row["instrument_id"]}
    states: dict[str, str] = {}

    def classify(key: str, value: Any) -> None:
        values[key] = value
        states[key] = "known" if value is not None else "missing" if row[key] is None else "invalid"

    classify("trading_date", read_market_date(row["trading_date"]))
    for key in ("open", "high", "low", "close", "adj_close"):
        classify(key, read_positive_price(row[key]))
    volume = row["volume"]
    classify("volume", volume if type(volume) is int and 0 <= volume <= 9223372036854775807 else None)
    turnover = row["turnover"]
    classify("turnover", turnover if type(turnover) in {int, float} and math.isfinite(turnover) and turnover >= 0 else None)
    status = row["turnover_status"]
    classify("turnover_status", status if type(status) is str and status in {"available", "unavailable", "unknown"} else None)
    reason = row["turnover_reason"]
    text_reason, _ = read_record(reason, "source")
    classify("turnover_reason", text_reason if text_reason is not None and len(text_reason) <= 40 else None)
    source, _ = read_record(row["source"], "source")
    classify("source", source)
    for key in ("data_as_of", "collected_at"):
        value, _ = read_record(row[key], key)
        classify(key, datetime.fromisoformat(value) if value is not None else None)
    raw_id, suspension = row["raw_payload_id"], row["is_suspended"]
    classify("raw_payload_id", raw_id if type(raw_id) is int and raw_id > 0 else None)
    classify("is_suspended", bool(suspension) if type(suspension) is int and suspension in {0, 1} else None)
    prices = [values[key] for key in ("open", "high", "low", "close")]
    states["ohlc"] = ("known" if None not in prices and
        values["low"] <= min(values["open"], values["close"]) <= max(values["open"], values["close"]) <= values["high"]
        else "invalid")
    return StockMarketRead(**values, fields=states)


def stock_market_dates(db: Session, instrument_id: int) -> tuple[date | None, int, int]:
    """Unknown dates prevent a default cutoff; never use a typed Date aggregate."""
    latest, total, unlocated = None, 0, 0
    for raw_date in db.execute(text("SELECT trading_date FROM market_bars WHERE instrument_id=:id"), {"id": instrument_id}).scalars():
        total += 1
        day = read_market_date(raw_date)
        if day is None:
            unlocated += 1
        elif latest is None or day > latest:
            latest = day
    return latest, total, unlocated


def load_stock_market_reads(db: Session, instrument_id: int, as_of: date | None, *, limit: int = 120) -> tuple[list[StockMarketRead], dict[str, Any]]:
    query = text("SELECT id,instrument_id,trading_date,open,high,low,close,adj_close,volume,turnover,"
                 "turnover_status,turnover_reason,source,data_as_of,collected_at,raw_payload_id,is_suspended "
                 "FROM market_bars WHERE instrument_id=:id ORDER BY trading_date DESC,id DESC")
    candidates, unlocated, unlocated_id = [], 0, None
    for row in db.execute(query, {"id": instrument_id}).mappings():
        day = read_market_date(row["trading_date"])
        if day is None:
            unlocated += 1
            if unlocated_id is None:
                unlocated_id = row["id"]
        elif as_of is not None and day > as_of:
            continue
        if len(candidates) < limit:
            candidates.append(_project(row))
    # Validation does not remove slots or refill the persisted 120-row window.
    state = candidates[0].read_state() if candidates else {"status": "missing", "invalid_fields": [], "missing_fields": ["market_bar"], "metadata_fields": {}}
    if unlocated:
        state = {**state, "status": "invalid", "invalid_fields": list(dict.fromkeys(["trading_date", *state["invalid_fields"]]))}
    return candidates, {**state, "candidate_count": len(candidates), "window_limit": limit,
                        "unlocated_count": unlocated, "unlocated_market_bar_id": unlocated_id,
                        "verification": "stored_value_syntax_only"}
