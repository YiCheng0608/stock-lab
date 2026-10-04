"""Stock-only raw research projections; syntax never proves source or availability."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import json
import math
import re
from typing import Any, Iterable

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from .decision_market_reads import read_market_date
from .domain import signal_confidence_semantics
from .level_semantics import build_level_semantics, canonical_evidence
from .product_time import build_signal_product_time

READ_VERSION = "stock-research-read/v1"
STRATEGIES = ("breakout_v1", "pullback_v1")
JSON_BYTES, JSON_DEPTH, JSON_NODES = 65536, 32, 16384


def _identity(value: Any) -> int | None:
    return value if type(value) is int and 0 < value <= 9223372036854775807 else None


def _string(value: Any, limit: int, *, empty: bool = False) -> str | None:
    if type(value) is not str or len(value) > limit or (not empty and not value):
        return None
    try:
        value.encode("utf-8", "strict")
    except UnicodeError:
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in value) or (value and not value.strip(" \t\r\n\ufeff")):
        return None
    return value


def _number(value: Any, *, positive: bool = False) -> float | None:
    if type(value) not in {int, float}:
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) and (not positive or number > 0) else None


def _datetime(value: Any) -> datetime | None:
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})?", value):
        return None
    if re.search(r"[+-][0-9]{2}:[0-9]{2}$", value) and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def read_research_json(value: Any) -> tuple[dict[str, Any] | None, str]:
    """Retain SQL NULL separately from present malformed or non-object JSON."""
    if value is None:
        return None, "missing"
    if type(value) is not str:
        return None, "invalid"

    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = item
        return result

    def constant(_token):
        raise ValueError("non-finite JSON constant")

    try:
        if len(value.encode("utf-8", "strict")) > JSON_BYTES:
            return None, "invalid"
        parsed = json.loads(value, object_pairs_hook=pairs, parse_constant=constant)
        if type(parsed) is not dict:
            return None, "invalid"
        pending, nodes = [(parsed, 0)], 0
        while pending:
            item, depth = pending.pop()
            nodes += 1
            if nodes > JSON_NODES or depth > JSON_DEPTH:
                return None, "invalid"
            if type(item) is dict:
                pending.extend((child, depth + 1) for child in item.values())
                pending.extend((key, depth + 1) for key in item)
            elif type(item) is list:
                pending.extend((child, depth + 1) for child in item)
            elif type(item) is str:
                item.encode("utf-8", "strict")
            elif type(item) in {int, float} and _number(item) is None:
                return None, "invalid"
        return parsed, "known"
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        return None, "invalid"


def _state(raw: Any, projected: Any) -> str:
    return "known" if projected is not None else "missing" if raw is None else "invalid"


@dataclass(frozen=True)
class StockStrategyRead:
    id: int | None
    name: str | None
    version: str | None
    kind: str | None
    config_json: dict | None
    canonical_config_snapshot: dict | None
    active: bool | None
    created_at: datetime | None
    fields: dict[str, str]


@dataclass(frozen=True)
class StockSignalRead:
    id: int | None
    instrument_id: int | None
    signal_key: str | None
    signal_date: date | None
    strategy_version_id: int | None
    status: str | None
    data_quality: str | None
    entry_type: str | None
    reference_entry: float | None
    pullback_low: float | None
    pullback_high: float | None
    breakout_price: float | None
    invalid_price: float | None
    target_1: float | None
    target_2: float | None
    confidence: float | None
    rationale: str | None
    data_cutoff: str | None
    source_report: str | None
    earliest_execution_date: date | None
    execution_date: date | None
    execution_price: float | None
    rule_evidence_json: dict | None
    created_at: datetime | None
    strategy: StockStrategyRead
    fields: dict[str, str]

    def read_state(self) -> dict:
        essential = {"id", "instrument_id", "signal_key", "signal_date", "strategy_version_id", "status", "data_quality", "strategy.id", "strategy.name", "strategy.version"}
        effective = ({"breakout_price", "invalid_price", "target_1", "target_2"} if self.strategy.name == "breakout_v1" else
                     {"reference_entry", "pullback_low", "pullback_high", "invalid_price", "target_1", "target_2"} if self.strategy.name == "pullback_v1" else set())
        core = essential | effective | {"rule_evidence", "data_cutoff", "earliest_execution_date"}
        core.update(key for key in self.fields if key.startswith("rule_evidence."))
        invalid = sorted(key for key in core if self.fields.get(key) == "invalid")
        missing = sorted(key for key in essential if self.fields.get(key) == "missing")
        return {"status": "invalid" if invalid else "missing" if missing else "known",
                "invalid_fields": invalid, "missing_fields": missing,
                # Nullable consumed fields retain their missing state without a new required gate.
                "metadata_fields": dict(self.fields)}

    def to_dict(self, instrument: dict | None) -> dict:
        semantics = build_level_semantics(strategy_name=self.strategy.name, strategy_version=self.strategy.version)
        product_time = build_signal_product_time(self)
        return {"id": self.id, "instrument_id": self.instrument_id, "strategy_version_id": self.strategy_version_id,
                "signal_key": self.signal_key, "signal_date": self.signal_date.isoformat() if self.signal_date else None,
                "instrument": instrument,
                **{key: getattr(self, key) for key in ("status", "data_quality", "entry_type", "reference_entry", "pullback_low", "pullback_high", "breakout_price", "invalid_price", "target_1", "target_2", "confidence", "rationale", "data_cutoff", "source_report", "execution_price")},
                "earliest_execution_date": self.earliest_execution_date.isoformat() if self.earliest_execution_date else None,
                "execution_date": self.execution_date.isoformat() if self.execution_date else None,
                "confidence_semantics": signal_confidence_semantics(self.confidence, self.rule_evidence_json, strategy_name=self.strategy.name, strategy_version=self.strategy.version),
                "level_semantics": semantics, "product_time": product_time,
                "response_generated_at": product_time["response_generated_at"],
                "rule_evidence": canonical_evidence(self.rule_evidence_json, semantics) if self.rule_evidence_json is not None else None,
                "strategy": {"name": self.strategy.name, "version": self.strategy.version, "kind": self.strategy.kind,
                             "canonical_config_snapshot": self.strategy.canonical_config_snapshot},
                "signal_read": self.read_state()}


def _project(row: Any) -> StockSignalRead:
    values, states = {}, {}

    def put(key, value):
        values[key] = value
        states[key] = _state(row[key], value)

    for key in ("id", "instrument_id", "strategy_version_id"):
        put(key, _identity(row[key]))
    for key in ("signal_date", "earliest_execution_date", "execution_date"):
        put(key, read_market_date(row[key]))
    for key, limit in (("signal_key", 160), ("status", 40), ("data_quality", 30), ("entry_type", 30),
                       ("rationale", 8192), ("data_cutoff", 80), ("source_report", 500)):
        put(key, _string(row[key], limit, empty=key == "rationale"))
    for key in ("reference_entry", "pullback_low", "pullback_high", "breakout_price", "invalid_price", "target_1", "target_2", "execution_price"):
        put(key, _number(row[key], positive=True))
    put("confidence", _number(row["confidence"]))
    put("created_at", _datetime(row["created_at"]))
    evidence, evidence_state = read_research_json(row["rule_evidence_json"])
    values["rule_evidence_json"], states["rule_evidence"] = evidence, evidence_state
    if evidence is not None:
        for key in ("inputs", "levels"):
            if key in evidence and type(evidence[key]) is not dict:
                states["rule_evidence." + key] = "invalid"
        consumed = [("risk_reward", evidence), ("risk_reward_ratio", evidence)]
        if type(evidence.get("levels")) is dict:
            consumed.append(("risk_reward", evidence["levels"]))
        if type(evidence.get("inputs")) is dict:
            consumed.extend((key, evidence["inputs"]) for key in ("group_excess_return_20d", "institutional_flow_to_turnover_ratio_5d", "margin_balance_change_ratio_5d"))
        for key, container in consumed:
            if key in container:
                prefix = "inputs." if container is evidence.get("inputs") else "levels." if container is evidence.get("levels") else ""
                states["rule_evidence." + prefix + key] = _state(container[key], _number(container[key]))
    version_values, version_states = {}, {}
    for key, converter in (("id", _identity), ("name", lambda value: _string(value, 60)), ("version", lambda value: _string(value, 30)),
                           ("kind", lambda value: _string(value, 30)), ("created_at", _datetime)):
        raw = row["version_" + key]
        projected = converter(raw)
        version_values[key], version_states[key] = projected, _state(raw, projected)
    for key in ("config_json", "canonical_config_snapshot"):
        version_values[key], version_states[key] = read_research_json(row["version_" + key])
    active = row["version_active"]
    version_values["active"] = bool(active) if type(active) is int and active in {0, 1} else None
    version_states["active"] = _state(active, version_values["active"])
    states.update(("strategy." + key, state) for key, state in version_states.items())
    return StockSignalRead(**values, strategy=StockStrategyRead(**version_values, fields=version_states), fields=states)


@dataclass
class StockSignalSet:
    candidates: list[StockSignalRead] = field(default_factory=list)
    latest: dict[str, StockSignalRead] = field(default_factory=dict)
    unlocated_count: int = 0
    unlocated_signal_id: int | None = None
    identity_unlocated_count: int = 0
    identity_unlocated_signal_id: int | None = None
    scanned_count: int = 0
    future_count: int = 0

    @property
    def instrument_blocked(self) -> bool:
        return bool(self.unlocated_count or self.identity_unlocated_count)

    def to_state(self) -> dict:
        slots = {name: {"signal_id": signal.id if signal else None,
                        "signal_date": signal.signal_date.isoformat() if signal and signal.signal_date else None,
                        "strategy_version_id": signal.strategy_version_id if signal else None,
                        "read": signal.read_state() if signal else {"status": "missing", "invalid_fields": [], "missing_fields": ["signal"], "metadata_fields": {}}}
                 for name in STRATEGIES for signal in [self.latest.get(name)]}
        blocked = [name for name in STRATEGIES if name in self.latest and self.latest[name].read_state()["status"] != "known"]
        invalid = any(row.read_state()["status"] != "known" for row in self.candidates)
        return {"version": READ_VERSION, "status": "invalid" if self.instrument_blocked or invalid else "known" if self.candidates else "missing",
                "candidate_count": len(self.candidates), "candidate_order": [row.id for row in self.candidates], "window_limit": 20,
                "scanned_count": self.scanned_count, "future_count": self.future_count,
                "unlocated_count": self.unlocated_count, "unlocated_signal_id": self.unlocated_signal_id,
                "identity_unlocated_count": self.identity_unlocated_count, "identity_unlocated_signal_id": self.identity_unlocated_signal_id,
                "latest": slots, "blocked_strategies": blocked,
                "decision_block_scope": "instrument" if self.instrument_blocked else "slots" if blocked else "none",
                "verification": "stored_value_syntax_only"}


def stock_signal_dates(db: Session, instrument_id: int) -> tuple[date | None, int]:
    latest, unlocated = None, 0
    for raw in db.execute(text("SELECT signal_date FROM signals WHERE instrument_id=:id"), {"id": instrument_id}).scalars():
        day = read_market_date(raw)
        if day is None:
            unlocated += 1
        elif latest is None or day > latest:
            latest = day
    return latest, unlocated


def load_stock_signal_reads(db: Session, instrument_ids: Iterable[int], as_of: date | None) -> dict[int, StockSignalSet]:
    ids = set(instrument_ids)
    result = {item_id: StockSignalSet() for item_id in ids}
    if not ids:
        return result
    query = text("SELECT s.*,v.id AS version_id,v.name AS version_name,v.version AS version_version,"
                 "v.kind AS version_kind,v.config_json AS version_config_json,v.canonical_config_snapshot AS version_canonical_config_snapshot,"
                 "v.active AS version_active,v.created_at AS version_created_at FROM signals s "
                 "LEFT JOIN strategy_versions v ON v.id=s.strategy_version_id WHERE s.instrument_id IN :ids "
                 "ORDER BY s.instrument_id,s.signal_date DESC,s.id DESC").bindparams(bindparam("ids", expanding=True))
    for row in db.execute(query, {"ids": sorted(ids)}).mappings():
        scope = result[row["instrument_id"]]
        scope.scanned_count += 1
        day = read_market_date(row["signal_date"])
        if day is None:
            scope.unlocated_count += 1
            if scope.unlocated_signal_id is None:
                scope.unlocated_signal_id = _identity(row["id"])
        elif as_of is not None and day > as_of:
            scope.future_count += 1
            continue
        name = _string(row["version_name"], 60)
        if _identity(row["strategy_version_id"]) is None or _identity(row["version_id"]) is None or name is None:
            scope.identity_unlocated_count += 1
            if scope.identity_unlocated_signal_id is None:
                scope.identity_unlocated_signal_id = _identity(row["id"])
        # The detail window and per-name latest scope intentionally differ.
        in_window = len(scope.candidates) < 20
        latest_slot = name in STRATEGIES and name not in scope.latest
        if in_window or latest_slot:
            projected = _project(row)
            if in_window:
                scope.candidates.append(projected)
            if latest_slot:
                scope.latest[name] = projected
    return result
