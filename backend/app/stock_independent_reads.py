"""Stock-only independent snapshots; read syntax does not admit sources or times."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from .decision_market_reads import read_market_date
from .stock_signal_reads import _datetime, _identity, _number, _string, read_research_json

READ_VERSION = "stock-independent-read/v1"
CHIP_NUMBERS = ("foreign_buy", "trust_buy", "dealer_buy", "margin_balance", "margin_change",
                "short_balance", "borrowed_sell", "day_trade_ratio")
CHIP_CORE = ("id", "instrument_id", "trading_date", "foreign_buy", "trust_buy", "dealer_buy",
             "margin_balance", "margin_change")


def _state(raw: Any, value: Any) -> str:
    return "known" if value is not None else "missing" if raw is None else "invalid"


def _read(fields: dict[str, str], essential: Iterable[str], invalid_core: Iterable[str] = ()) -> dict:
    invalid = sorted(key for key in set(essential) | set(invalid_core) if fields[key] == "invalid")
    missing = sorted(key for key in essential if fields[key] == "missing")
    return {"status": "invalid" if invalid else "missing" if missing else "known",
            "invalid_fields": invalid, "missing_fields": missing, "metadata_fields": dict(fields)}


@dataclass(frozen=True)
class StockFeatureRead:
    id: int | None
    instrument_id: int | None
    trading_date: date | None
    features_json: dict | None
    source: str | None
    created_at: datetime | None
    fields: dict[str, str]

    def read_state(self) -> dict:
        return _read(self.fields, ("id", "instrument_id", "trading_date", "features_json"), ("ma20", "ma60"))

    def to_dict(self) -> dict:
        return {"id": self.id, "instrument_id": self.instrument_id,
                "trading_date": self.trading_date.isoformat() if self.trading_date else None,
                "features_json": self.features_json, "source": self.source,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "row_read": self.read_state()}


@dataclass(frozen=True)
class StockChipRead:
    id: int | None
    instrument_id: int | None
    trading_date: date | None
    foreign_buy: float | None
    trust_buy: float | None
    dealer_buy: float | None
    margin_balance: float | None
    margin_change: float | None
    short_balance: float | None
    borrowed_sell: float | None
    day_trade_ratio: float | None
    source: str | None
    data_as_of: datetime | None
    collected_at: datetime | None
    raw_payload_id: int | None
    fields: dict[str, str]

    @property
    def core_valid(self) -> bool:
        return self.read_state()["status"] == "known"

    def read_state(self) -> dict:
        return _read(self.fields, CHIP_CORE)

    def to_dict(self) -> dict:
        return {"id": self.id, "instrument_id": self.instrument_id,
                "date": self.trading_date.isoformat() if self.trading_date else None,
                **{key: getattr(self, key) for key in CHIP_NUMBERS}, "source": self.source,
                "data_as_of": self.data_as_of.isoformat() if self.data_as_of else None,
                "collected_at": self.collected_at.isoformat() if self.collected_at else None,
                "raw_payload_id": self.raw_payload_id, "row_read": self.read_state()}


def project_feature(row: Any) -> StockFeatureRead:
    values, fields = {}, {}
    for key, reader in (("id", _identity), ("instrument_id", _identity), ("trading_date", read_market_date),
                        ("source", lambda value: _string(value, 120)), ("created_at", _datetime)):
        values[key] = reader(row[key])
        fields[key] = _state(row[key], values[key])
    features, fields["features_json"] = read_research_json(row["features_json"])
    if features is not None:
        features = dict(features)
    for key in ("ma20", "ma60"):
        raw = features.get(key) if features is not None else None
        value = _number(raw)
        fields[key] = _state(raw, value)
        if features is not None and key in features:
            features[key] = value
    return StockFeatureRead(**values, features_json=features, fields=fields)


def project_chip(row: Any) -> StockChipRead:
    values, fields = {}, {}
    readers = (("id", _identity), ("instrument_id", _identity), ("trading_date", read_market_date),
               ("raw_payload_id", _identity), ("source", lambda value: _string(value, 120)),
               ("data_as_of", _datetime), ("collected_at", _datetime))
    for key, reader in (*readers, *((key, _number) for key in CHIP_NUMBERS)):
        values[key] = reader(row[key])
        fields[key] = _state(row[key], values[key])
    return StockChipRead(**values, fields=fields)


@dataclass
class StockIndependentSet:
    window_limit: int
    candidates: list[Any] = field(default_factory=list)
    scanned_count: int = 0
    future_count: int = 0
    unlocated_count: int = 0
    unlocated_id: int | None = None

    def to_state(self) -> dict:
        statuses = [row.read_state()["status"] for row in self.candidates]
        status = ("invalid" if self.unlocated_count or "invalid" in statuses else
                  "missing" if not statuses or "missing" in statuses else "known")
        return {"version": READ_VERSION, "status": status, "window_limit": self.window_limit,
                "candidate_count": len(self.candidates), "candidate_order": [row.id for row in self.candidates],
                "scanned_count": self.scanned_count, "future_count": self.future_count,
                "unlocated_count": self.unlocated_count, "unlocated_id": self.unlocated_id,
                "verification": "stored_value_syntax_only"}


def independent_dates(db: Session, instrument_id: int) -> tuple[date | None, int]:
    latest, unlocated = None, 0
    for table in ("technical_features", "chip_snapshots"):
        for raw in db.execute(text(f"SELECT trading_date FROM {table} WHERE instrument_id=:id"), {"id": instrument_id}).scalars():
            day = read_market_date(raw)
            if day is None:
                unlocated += 1
            elif latest is None or day > latest:
                latest = day
    return latest, unlocated


def _load(db: Session, ids: Iterable[int], as_of: date | None, *, chips: bool) -> dict[int, StockIndependentSet]:
    ids = set(ids)
    result = {item_id: StockIndependentSet(120 if chips else 1) for item_id in ids}
    if not ids:
        return result
    # All 6/15 persisted columns bypass Date/DateTime/JSON processors; no CAST or repair.
    table = "chip_snapshots" if chips else "technical_features"
    columns = ("id,instrument_id,trading_date," + ",".join(CHIP_NUMBERS) + ",source,data_as_of,collected_at,raw_payload_id"
               if chips else "id,instrument_id,trading_date,features_json,source,created_at")
    query = text(f"SELECT {columns} FROM {table} WHERE instrument_id IN :ids "
                 "ORDER BY instrument_id,trading_date DESC,id DESC").bindparams(bindparam("ids", expanding=True))
    for row in db.execute(query, {"ids": sorted(ids)}).mappings():
        scope = result[row["instrument_id"]]
        scope.scanned_count += 1
        day = read_market_date(row["trading_date"])
        if day is None:
            scope.unlocated_count += 1
            if scope.unlocated_id is None:
                scope.unlocated_id = _identity(row["id"])
        elif as_of is not None and day > as_of:
            scope.future_count += 1
            continue
        if len(scope.candidates) < scope.window_limit:
            scope.candidates.append(project_chip(row) if chips else project_feature(row))
    return result


def load_stock_feature_reads(db: Session, instrument_id: int, as_of: date | None) -> StockIndependentSet:
    return _load(db, [instrument_id], as_of, chips=False)[instrument_id]


def load_stock_chip_reads(db: Session, instrument_ids: Iterable[int], as_of: date | None) -> dict[int, StockIndependentSet]:
    return _load(db, instrument_ids, as_of, chips=True)
