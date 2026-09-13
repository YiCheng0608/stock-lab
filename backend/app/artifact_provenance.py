"""Strict, caller-provided provenance contract for persisted ATR artifacts.

The schema-1 artifact store predates the full provenance contract and must keep
reading those rows.  This module therefore provides an opt-in v2 contract and
never treats an old or incomplete payload as a v2 payload merely because it is
stored in the same SQLite database.

The contract records declarations made by the caller.  It does not validate
that a source is official, that a digest was computed from the claimed source,
or that point-in-time availability is true; those are source-wire/time gates.
It does, however, require enough explicit structure to make such declarations
auditable and refuses to attach a complete ATR value to unknown required input
metadata.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .atr import ATRArtifact


PROVENANCE_CONTRACT_NAME = "atr-provenance"
PROVENANCE_CONTRACT_VERSION = 2
PROVENANCE_CONTRACT_ID = f"{PROVENANCE_CONTRACT_NAME}/v{PROVENANCE_CONTRACT_VERSION}"
PROVENANCE_MODE = "caller_provided_only"
INSTRUMENT_VALIDATION_STATUS = "caller_supplied_only"
MARKET_TIMEZONE = ZoneInfo("Asia/Taipei")
_UTC = timezone.utc
_MISSING = object()


class ProvenanceContractError(ValueError):
    """The explicit v2 provenance object is missing or structurally invalid."""


def _error(field: str, message: str) -> ProvenanceContractError:
    return ProvenanceContractError(f"{field}: {message}")


def _required_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise _error(field, "must be a non-empty object")
    return value


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(field, "is required")
    return value.strip()


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field)


def _digest_text(value: Any, algorithm: str, field: str) -> str:
    digest = _required_text(value, field).casefold()
    normalized_algorithm = algorithm.casefold().replace("-", "")
    expected_lengths = {"sha256": 64, "sha512": 128}
    if normalized_algorithm not in expected_lengths:
        raise _error(field, "digest algorithm must be sha256 or sha512")
    if len(digest) != expected_lengths[normalized_algorithm] or any(
        char not in "0123456789abcdef" for char in digest
    ):
        raise _error(field, f"must be a {algorithm} hexadecimal digest")
    return digest


def _canonical(value: Any, field: str = "value") -> Any:
    if isinstance(value, datetime):
        return _timestamp(value, field)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _error(field, "mapping keys must be strings")
            child = f"{field}.{key}"
            if key.endswith("_at") or key in {"decision_at", "generated_at"}:
                result[key] = None if item is None else _timestamp(item, child)
            else:
                result[key] = _canonical(item, child)
        return result
    if isinstance(value, (list, tuple)):
        return [_canonical(item, f"{field}[]") for item in value]
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise _error(field, "must not be NaN or infinite")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise _error(field, f"unsupported JSON value {type(value).__name__}")


def _canonical_json(value: Any, field: str = "value") -> str:
    try:
        return json.dumps(
            _canonical(value, field),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise _error(field, "cannot be canonically encoded") from exc


def _timestamp(value: datetime | str, field: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise _error(field, "must be an ISO timestamp with timezone") from exc
    else:
        raise _error(field, "must be a timezone-aware datetime or ISO timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _error(field, "must not be naive")
    return parsed.astimezone(_UTC).isoformat()


def _market_date(value: date | str | datetime, field: str = "market_date") -> date:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise _error(field, "must not be naive")
        return value.astimezone(MARKET_TIMEZONE).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise _error(field, "must be an ISO date") from exc
    raise _error(field, "must be a date, ISO date, or aware datetime")


def _coverage_window(value: Any, field: str, *, terminal: date | None = None) -> dict[str, Any]:
    obj = _required_mapping(value, field)
    start = _market_date(obj.get("start_date"), f"{field}.start_date")
    end = _market_date(obj.get("end_date"), f"{field}.end_date")
    terminal_date = _market_date(
        obj.get("terminal_market_date"), f"{field}.terminal_market_date"
    )
    if end < start or not start <= terminal_date <= end:
        raise _error(field, "start/end/terminal dates are not an ordered window")
    if terminal is not None and terminal_date != terminal:
        raise _error(f"{field}.terminal_market_date", "does not match artifact market date")
    result = dict(_canonical(obj, field))
    result.update(
        {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "terminal_market_date": terminal_date.isoformat(),
        }
    )
    return result


def _snapshot(value: Any, field: str) -> dict[str, Any]:
    obj = _required_mapping(value, field)
    result = dict(_canonical(obj, field))
    hash_algorithm = _required_text(
        obj.get("hash_algorithm"), f"{field}.hash_algorithm"
    ).casefold().replace("-", "")
    if hash_algorithm not in {"sha256", "sha512"}:
        raise _error(f"{field}.hash_algorithm", "must be sha256 or sha512")
    result.update({
        "id": _required_text(obj.get("id"), f"{field}.id"),
        "hash": _digest_text(obj.get("hash"), hash_algorithm, f"{field}.hash"),
        "source_ref": _required_text(obj.get("source_ref"), f"{field}.source_ref"),
        "hash_algorithm": hash_algorithm,
    })
    version = obj.get("version")
    if version is not None:
        result["version"] = _required_text(version, f"{field}.version")
    return result


def _availability(value: Any, field: str) -> dict[str, Any]:
    obj = _required_mapping(value, field)
    status = _required_text(obj.get("status"), f"{field}.status").casefold()
    if status not in {"available", "unknown", "unavailable"}:
        raise _error(field, "status must be available, unknown, or unavailable")
    reason = _optional_text(obj.get("reason"), f"{field}.reason")
    if status in {"unknown", "unavailable"} and reason is None:
        raise _error(field, "unknown/unavailable status requires reason")
    result: dict[str, Any] = dict(_canonical(obj, field))
    result["status"] = status
    if reason is not None:
        result["reason"] = reason
    if "available_at" in obj and obj["available_at"] is not None:
        result["available_at"] = _timestamp(obj["available_at"], f"{field}.available_at")
    elif status == "available":
        raise _error(field, "available status requires available_at")
    source_ref = obj.get("source_ref")
    if source_ref is not None:
        result["source_ref"] = _required_text(source_ref, f"{field}.source_ref")
    return result


def _versioned_evidence(value: Any, field: str, *, reference_key: str) -> dict[str, Any]:
    obj = _required_mapping(value, field)
    version = _required_text(obj.get("version"), f"{field}.version")
    source_ref = _required_text(obj.get("source_ref"), f"{field}.source_ref")
    snapshot = _snapshot(obj.get("snapshot"), f"{field}.snapshot")
    availability = _availability(obj.get("availability"), f"{field}.availability")
    result = dict(_canonical(obj, field))
    result.update({
        reference_key: version,
        "version": version,
        "source_ref": source_ref,
        "snapshot": snapshot,
        "snapshot_id": snapshot["id"],
        "snapshot_hash": snapshot["hash"],
        "availability": availability,
        "coverage_window": _coverage_window(obj.get("coverage_window"), f"{field}.coverage_window"),
    })
    return result


def _instrument(value: Any) -> dict[str, Any]:
    obj = _required_mapping(value, "instrument")
    exchange = _required_text(obj.get("exchange"), "instrument.exchange").upper()
    symbol = _required_text(obj.get("symbol"), "instrument.symbol").upper()
    if obj.get("validation_status") != INSTRUMENT_VALIDATION_STATUS:
        raise _error(
            "instrument.validation_status",
            f"must be {INSTRUMENT_VALIDATION_STATUS}",
        )
    source = _required_mapping(obj.get("source"), "instrument.source")
    source_ref = _required_text(source.get("source_ref"), "instrument.source.source_ref")
    snapshot = _snapshot(source.get("snapshot"), "instrument.source.snapshot")
    source_identity = _required_mapping(obj.get("source_identity"), "instrument.source_identity")
    source_identity_type = _required_text(
        source_identity.get("type"), "instrument.source_identity.type"
    )
    source_identity_value = _required_text(
        source_identity.get("value"), "instrument.source_identity.value"
    )
    source_normalized = dict(_canonical(source, "instrument.source"))
    source_normalized.update({
        "source_ref": source_ref,
        "snapshot": snapshot,
        "snapshot_id": snapshot["id"],
        "snapshot_hash": snapshot["hash"],
    })
    result: dict[str, Any] = dict(_canonical(obj, "instrument"))
    result.update({
        "exchange": exchange,
        "symbol": symbol,
        "source_ref": source_ref,
        "source": source_normalized,
        "source_identity": {
            **dict(_canonical(source_identity, "instrument.source_identity")),
            "type": source_identity_type,
            "value": source_identity_value,
        },
        "snapshot": snapshot,
        "snapshot_id": snapshot["id"],
        "snapshot_hash": snapshot["hash"],
        "validation_status": INSTRUMENT_VALIDATION_STATUS,
    })
    legacy_reference = obj.get("legacy_reference")
    if legacy_reference is not None:
        result["legacy_reference"] = _required_text(
            legacy_reference, "instrument.legacy_reference"
        )
    return result


def _ordered_source_rows(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise _error(field, "must be a non-empty ordered list")
    rows: list[dict[str, Any]] = []
    previous_date: date | None = None
    for index, item in enumerate(value):
        row = _required_mapping(item, f"{field}[{index}]")
        position = row.get("sequence_position")
        if isinstance(position, bool) or not isinstance(position, int) or position != index:
            raise _error(
                f"{field}[{index}].sequence_position",
                "must be the zero-based position in ordered_source_rows",
            )
        row_ref = _required_text(row.get("row_ref"), f"{field}[{index}].row_ref")
        row_date = _market_date(row.get("market_date"), f"{field}[{index}].market_date")
        session = _required_text(row.get("market_session"), f"{field}[{index}].market_session")
        snapshot_id = _required_text(row.get("snapshot_id"), f"{field}[{index}].snapshot_id")
        price_basis = _required_text(row.get("price_basis"), f"{field}[{index}].price_basis")
        row_status = _required_text(row.get("row_status"), f"{field}[{index}].row_status").casefold()
        if row_status not in {"bar", "no_bar", "suspended", "unknown"}:
            raise _error(f"{field}[{index}].row_status", "has an unsupported value")
        row_reason = _optional_text(row.get("reason"), f"{field}[{index}].reason")
        if row_status == "unknown" and row_reason is None:
            raise _error(f"{field}[{index}]", "unknown row status requires reason")
        availability = _availability(
            row.get("availability"), f"{field}[{index}].availability"
        )
        row_digest = _optional_text(row.get("row_digest"), f"{field}[{index}].row_digest")
        if row_digest is None and row_ref is None:
            raise _error(f"{field}[{index}]", "requires row_ref or row_digest")
        if previous_date is not None and row_date <= previous_date:
            raise _error(field, "rows must retain strict market-date order")
        previous_date = row_date
        normalized = dict(_canonical(row, f"{field}[{index}]"))
        normalized.update({
            "sequence_position": index,
            "row_ref": row_ref,
            "market_date": row_date.isoformat(),
            "market_session": session,
            "snapshot_id": snapshot_id,
            "price_basis": price_basis,
            "row_status": row_status,
            "availability": availability,
        })
        if row_reason is not None:
            normalized["reason"] = row_reason
        if row_digest is not None:
            normalized["row_digest"] = row_digest
        rows.append(normalized)
    return rows


def _session_entries(
    value: Any,
    field: str,
    *,
    allowed_statuses: set[str] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise _error(field, "must be a non-empty ordered list")
    entries: list[dict[str, Any]] = []
    previous_date: date | None = None
    for index, item in enumerate(value):
        row = _required_mapping(item, f"{field}[{index}]")
        position = row.get("sequence_position")
        if isinstance(position, bool) or not isinstance(position, int) or position != index:
            raise _error(f"{field}[{index}].sequence_position", "must match list position")
        session_date = _market_date(row.get("session_date"), f"{field}[{index}].session_date")
        if previous_date is not None and session_date <= previous_date:
            raise _error(field, "session entries must be strictly ordered")
        previous_date = session_date
        session_ref = _required_text(row.get("session_ref"), f"{field}[{index}].session_ref")
        snapshot_id = _required_text(row.get("snapshot_id"), f"{field}[{index}].snapshot_id")
        source_ref = _required_text(row.get("source_ref"), f"{field}[{index}].source_ref")
        status = _required_text(row.get("status"), f"{field}[{index}].status").casefold()
        statuses = allowed_statuses or {"open", "bar", "no_bar", "suspended", "unknown", "closed"}
        if status not in statuses:
            raise _error(f"{field}[{index}].status", "has an unsupported value")
        reason = _optional_text(row.get("reason"), f"{field}[{index}].reason")
        if status == "unknown" and reason is None:
            raise _error(f"{field}[{index}]", "unknown status requires reason")
        entry = dict(_canonical(row, f"{field}[{index}]"))
        entry.update(
            {
                "sequence_position": index,
                "session_date": session_date.isoformat(),
                "session_ref": session_ref,
                "snapshot_id": snapshot_id,
                "source_ref": source_ref,
                "status": status,
                "availability": _availability(
                    row.get("availability"), f"{field}[{index}].availability"
                ),
            }
        )
        if reason is not None:
            entry["reason"] = reason
        entries.append(entry)
    return entries


def _algorithm(value: Any, artifact: ATRArtifact) -> dict[str, Any]:
    obj = _required_mapping(value, "algorithm")
    name = _required_text(obj.get("name"), "algorithm.name")
    if name != artifact.algorithm:
        raise _error("algorithm.name", "must match ATRArtifact.algorithm")
    algorithm_version = _required_text(obj.get("version"), "algorithm.version")
    period = obj.get("period")
    if isinstance(period, bool) or not isinstance(period, int) or period <= 0:
        raise _error("algorithm.period", "must be a positive integer")
    if period != artifact.period:
        raise _error("algorithm.period", "must match ATRArtifact.period")
    smoothing = _required_text(obj.get("smoothing"), "algorithm.smoothing")
    seed = _required_text(obj.get("seed"), "algorithm.seed")
    precision = _required_text(obj.get("precision"), "algorithm.precision")
    config = _required_mapping(obj.get("config"), "algorithm.config")
    normalized_config = json.loads(_canonical_json(config, "algorithm.config"))
    required_config = {
        "algorithm": name,
        "period": period,
        "smoothing": smoothing,
        "seed": seed,
    }
    for key, expected in required_config.items():
        if normalized_config.get(key) != expected:
            raise _error(f"algorithm.config.{key}", f"must equal algorithm.{key}")
    config_precision = normalized_config.get("precision", normalized_config.get("precision_policy"))
    if config_precision != precision:
        raise _error("algorithm.config.precision", "must equal algorithm.precision")
    config_digest = _required_text(obj.get("config_digest"), "algorithm.config_digest").casefold()
    expected_config_digest = hashlib.sha256(
        _canonical_json(normalized_config, "algorithm.config").encode("utf-8")
    ).hexdigest()
    if config_digest != expected_config_digest:
        raise _error("algorithm.config_digest", "does not match canonical algorithm.config")
    implementation_obj = _required_mapping(obj.get("implementation"), "algorithm.implementation")
    digest_algorithm = _required_text(
        implementation_obj.get("digest_algorithm"),
        "algorithm.implementation.digest_algorithm",
    ).casefold().replace("-", "")
    implementation = dict(_canonical(implementation_obj, "algorithm.implementation"))
    implementation.update({
        "name": _required_text(implementation_obj.get("name"), "algorithm.implementation.name"),
        "version": _required_text(
            implementation_obj.get("version"), "algorithm.implementation.version"
        ),
        "digest": _digest_text(
            implementation_obj.get("digest"),
            digest_algorithm,
            "algorithm.implementation.digest",
        ),
        "source_ref": _required_text(
            implementation_obj.get("source_ref"), "algorithm.implementation.source_ref"
        ),
        "digest_algorithm": digest_algorithm,
    })
    result = dict(_canonical(obj, "algorithm"))
    result.update({
        "name": name,
        "version": algorithm_version,
        "period": period,
        "smoothing": smoothing,
        "seed": seed,
        "precision": precision,
        "config": normalized_config,
        "config_digest": config_digest,
        "implementation": implementation,
    })
    return result


def _basis(value: Any, artifact: ATRArtifact) -> dict[str, Any]:
    obj = _required_mapping(value, "basis")
    price_basis = _required_text(obj.get("price_basis"), "basis.price_basis")
    if price_basis != artifact.price_basis:
        raise _error("basis.price_basis", "must match ATRArtifact.price_basis")
    scope = _coverage_window(obj.get("scope"), "basis.scope")
    evidence_ref = _required_text(obj.get("evidence_ref"), "basis.evidence_ref")
    result = dict(_canonical(obj, "basis"))
    result.update({
        "price_basis": price_basis,
        "version": _required_text(obj.get("version"), "basis.version"),
        "digest": _required_text(obj.get("digest"), "basis.digest").casefold(),
        "source_ref": _required_text(obj.get("source_ref"), "basis.source_ref"),
        "evidence_ref": evidence_ref,
        "scope": scope,
        "availability": _availability(obj.get("availability"), "basis.availability"),
    })
    digest_payload = {
        "price_basis": result["price_basis"],
        "version": result["version"],
        "source_ref": result["source_ref"],
        "evidence_ref": result["evidence_ref"],
        "scope": result["scope"],
    }
    expected_digest = hashlib.sha256(
        _canonical_json(digest_payload, "basis.digest_payload").encode("utf-8")
    ).hexdigest()
    if result["digest"] != expected_digest:
        raise _error("basis.digest", "does not match canonical basis evidence")
    return result


def _previous_close(value: Any, artifact: ATRArtifact) -> dict[str, Any]:
    obj = _required_mapping(value, "previous_close")
    status = _required_text(
        obj.get("selection_status", obj.get("status")),
        "previous_close.selection_status",
    ).casefold()
    allowed = {"used", "not_used", "not_used_true_sequence_start", "unknown", "unavailable"}
    if status not in allowed:
        raise _error("previous_close.selection_status", "has an unsupported value")
    reason = _optional_text(obj.get("reason"), "previous_close.reason")
    if status in {"unknown", "unavailable", "not_used", "not_used_true_sequence_start"} and reason is None:
        raise _error("previous_close", "status requires an explicit reason")
    result: dict[str, Any] = dict(_canonical(obj, "previous_close"))
    result["status"] = status
    result["selection_status"] = status
    if reason is not None:
        result["reason"] = reason
    candidates = obj.get("candidates")
    if not isinstance(candidates, list):
        raise _error("previous_close.candidates", "must be a list")
    normalized_candidates: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        item = _required_mapping(candidate, f"previous_close.candidates[{index}]")
        normalized = dict(_canonical(item, f"previous_close.candidates[{index}]"))
        normalized["selection_status"] = _required_text(
            item.get("selection_status"),
            f"previous_close.candidates[{index}].selection_status",
        ).casefold()
        normalized["row_ref"] = _required_text(
            item.get("row_ref"), f"previous_close.candidates[{index}].row_ref"
        )
        normalized["market_date"] = _market_date(
            item.get("market_date"), f"previous_close.candidates[{index}].market_date"
        ).isoformat()
        if item.get("value") is not None:
            number = item["value"]
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                raise _error(f"previous_close.candidates[{index}].value", "must be numeric or null")
            if number != number or number in (float("inf"), float("-inf")):
                raise _error(f"previous_close.candidates[{index}].value", "must be finite")
            normalized["value"] = float(number)
        if item.get("basis") is not None:
            normalized["basis"] = _required_text(item["basis"], f"previous_close.candidates[{index}].basis")
        if item.get("source_ref") is not None:
            normalized["source_ref"] = _required_text(
                item["source_ref"], f"previous_close.candidates[{index}].source_ref"
            )
        if item.get("snapshot") is not None:
            normalized["snapshot"] = _snapshot(
                item["snapshot"], f"previous_close.candidates[{index}].snapshot"
            )
        if item.get("availability") is not None:
            normalized["availability"] = _availability(
                item["availability"], f"previous_close.candidates[{index}].availability"
            )
        normalized_candidates.append(normalized)
    if status == "used":
        selected_value = obj.get("selected")
        if isinstance(selected_value, Mapping):
            selected_items = [selected_value]
        elif isinstance(selected_value, list):
            selected_items = selected_value
        else:
            raise _error("previous_close.selected", "must be a non-empty list")
        if not selected_items:
            raise _error("previous_close.selected", "must contain at least one selected row")
        normalized_selected: list[dict[str, Any]] = []
        seen_current: set[tuple[str, str]] = set()
        for index, selected in enumerate(selected_items):
            selected = _required_mapping(selected, f"previous_close.selected[{index}]")
            selected_normalized = dict(_canonical(selected, f"previous_close.selected[{index}]"))
            number = selected.get("value")
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                raise _error(f"previous_close.selected[{index}].value", "must be a finite positive number")
            if number != number or number in (float("inf"), float("-inf")) or number <= 0:
                raise _error(f"previous_close.selected[{index}].value", "must be a finite positive number")
            basis = _required_text(selected.get("basis"), f"previous_close.selected[{index}].basis")
            if basis != artifact.price_basis:
                raise _error(f"previous_close.selected[{index}].basis", "must match artifact price_basis")
            selected_normalized["value"] = float(number)
            selected_normalized["basis"] = basis
            selected_normalized["selection_status"] = _required_text(
                selected.get("selection_status", "used"),
                f"previous_close.selected[{index}].selection_status",
            ).casefold()
            selected_normalized["row_ref"] = _required_text(
                selected.get("row_ref"), f"previous_close.selected[{index}].row_ref"
            )
            selected_normalized["source_ref"] = _required_text(
                selected.get("source_ref"), f"previous_close.selected[{index}].source_ref"
            )
            selected_normalized["snapshot"] = _snapshot(
                selected.get("snapshot"), f"previous_close.selected[{index}].snapshot"
            )
            selected_normalized["availability"] = _availability(
                selected.get("availability"), f"previous_close.selected[{index}].availability"
            )
            current_ref = _required_mapping(
                selected.get("current"), f"previous_close.selected[{index}].current"
            )
            current_date = _market_date(
                current_ref.get("market_date"), f"previous_close.selected[{index}].current.market_date"
            )
            predecessor_ref = _required_mapping(
                selected.get("predecessor"), f"previous_close.selected[{index}].predecessor"
            )
            predecessor_date = _market_date(
                predecessor_ref.get("market_date"),
                f"previous_close.selected[{index}].predecessor.market_date",
            )
            if predecessor_date >= current_date:
                raise _error(f"previous_close.selected[{index}]", "predecessor must precede current row")
            normalized_current = dict(_canonical(current_ref, f"previous_close.selected[{index}].current"))
            normalized_predecessor = dict(_canonical(predecessor_ref, f"previous_close.selected[{index}].predecessor"))
            for relation, relation_ref, normalized_ref, relation_date in (
                ("current", current_ref, normalized_current, current_date),
                ("predecessor", predecessor_ref, normalized_predecessor, predecessor_date),
            ):
                normalized_ref["row_ref"] = _required_text(
                    relation_ref.get("row_ref"),
                    f"previous_close.selected[{index}].{relation}.row_ref",
                )
                normalized_ref["market_date"] = relation_date.isoformat()
                normalized_ref["snapshot_id"] = _required_text(
                    relation_ref.get("snapshot_id"),
                    f"previous_close.selected[{index}].{relation}.snapshot_id",
                )
                normalized_ref["snapshot_hash"] = _digest_text(
                    relation_ref.get("snapshot_hash"),
                    "sha256",
                    f"previous_close.selected[{index}].{relation}.snapshot_hash",
                )
                normalized_ref["price_basis"] = _required_text(
                    relation_ref.get("price_basis", artifact.price_basis),
                    f"previous_close.selected[{index}].{relation}.price_basis",
                )
                if normalized_ref["price_basis"] != artifact.price_basis:
                    raise _error(f"previous_close.selected[{index}].{relation}.price_basis", "must match artifact basis")
                selected_normalized[relation] = normalized_ref
            current_key = (
                selected_normalized["current"]["row_ref"],
                selected_normalized["current"]["market_date"],
            )
            if current_key in seen_current:
                raise _error("previous_close.selected", "contains duplicate current row references")
            seen_current.add(current_key)
            normalized_selected.append(selected_normalized)
        result["selected"] = normalized_selected
        selected_source_refs = {item["source_ref"] for item in normalized_selected}
        if len(selected_source_refs) == 1:
            result["source_ref"] = next(iter(selected_source_refs))
    elif obj.get("selected") is not None:
        raise _error("previous_close.selected", "is only allowed for selection_status=used")
    result["candidates"] = normalized_candidates
    return result


def _company_actions(value: Any) -> dict[str, Any]:
    obj = _required_mapping(value, "company_actions")
    manifest_value = obj.get("manifest")
    if not isinstance(manifest_value, Sequence) or isinstance(manifest_value, (str, bytes)):
        raise _error("company_actions.manifest", "must be a list")
    manifest: list[dict[str, Any]] = []
    for index, item in enumerate(manifest_value):
        action = _required_mapping(item, f"company_actions.manifest[{index}]")
        normalized = dict(_canonical(action, f"company_actions.manifest[{index}]"))
        action_digest_algorithm = _required_text(
            action.get("digest_algorithm"),
            f"company_actions.manifest[{index}].digest_algorithm",
        ).casefold().replace("-", "")
        normalized.update({
            "action_ref": _required_text(
                action.get("action_ref"), f"company_actions.manifest[{index}].action_ref"
            ),
            "digest": _digest_text(
                action.get("digest"),
                action_digest_algorithm,
                f"company_actions.manifest[{index}].digest",
            ),
            "digest_algorithm": action_digest_algorithm,
            "instrument": dict(
                _canonical(
                    _required_mapping(
                        action.get("instrument"),
                        f"company_actions.manifest[{index}].instrument",
                    ),
                    f"company_actions.manifest[{index}].instrument",
                )
            ),
            "action_date": _market_date(
                action.get("action_date"), f"company_actions.manifest[{index}].action_date"
            ).isoformat(),
            "ex_date": _market_date(
                action.get("ex_date"), f"company_actions.manifest[{index}].ex_date"
            ).isoformat(),
            "action_type": _required_text(
                action.get("action_type"), f"company_actions.manifest[{index}].action_type"
            ),
            "source_ref": _required_text(
                action.get("source_ref"), f"company_actions.manifest[{index}].source_ref"
            ),
            "parameters": dict(
                _canonical(
                    _required_mapping(
                        action.get("parameters"),
                        f"company_actions.manifest[{index}].parameters",
                    ),
                    f"company_actions.manifest[{index}].parameters",
                )
            ),
            "from_basis": _required_text(
                action.get("from_basis"), f"company_actions.manifest[{index}].from_basis"
            ),
            "to_basis": _required_text(
                action.get("to_basis"), f"company_actions.manifest[{index}].to_basis"
            ),
            "applicable_scope": _coverage_window(
                action.get("applicable_scope"),
                f"company_actions.manifest[{index}].applicable_scope",
            ),
            "availability": _availability(
                action.get("availability"),
                f"company_actions.manifest[{index}].availability",
            ),
        })
        manifest.append(normalized)
    digest = _required_text(obj.get("digest"), "company_actions.digest")
    coverage = _required_text(obj.get("coverage"), "company_actions.coverage").casefold()
    if coverage not in {"complete", "partial", "unknown", "unavailable"}:
        raise _error("company_actions.coverage", "has an unsupported value")
    reason = _optional_text(obj.get("reason"), "company_actions.reason")
    if coverage != "complete" and reason is None:
        raise _error("company_actions", "non-complete coverage requires reason")
    coverage_window = _coverage_window(obj.get("coverage_window"), "company_actions.coverage_window")
    missing_or_unknown = obj.get("missing_or_unknown")
    if not isinstance(missing_or_unknown, list):
        raise _error("company_actions.missing_or_unknown", "must be a list")
    if not manifest and coverage == "complete":
        if obj.get("coverage_proof") != "complete_none":
            raise _error(
                "company_actions.coverage_proof",
                "empty complete manifest requires complete_none proof",
            )
        _required_text(obj.get("no_actions_reason"), "company_actions.no_actions_reason")
    source_obj = _required_mapping(obj.get("source"), "company_actions.source")
    source = dict(_canonical(source_obj, "company_actions.source"))
    source.update({
        "source_ref": _required_text(source_obj.get("source_ref"), "company_actions.source.source_ref"),
        "version": _required_text(source_obj.get("version"), "company_actions.source.version"),
        "snapshot": _snapshot(source_obj.get("snapshot"), "company_actions.source.snapshot"),
    })
    source["snapshot_id"] = source["snapshot"]["id"]
    source["snapshot_hash"] = source["snapshot"]["hash"]
    availability = _availability(obj.get("availability"), "company_actions.availability")
    result: dict[str, Any] = dict(_canonical(obj, "company_actions"))
    result.update({
        "manifest": manifest,
        "digest": digest,
        "coverage": coverage,
        "coverage_window": coverage_window,
        "missing_or_unknown": missing_or_unknown,
        "source": source,
        "availability": availability,
    })
    if reason is not None:
        result["reason"] = reason
    expected_digest = hashlib.sha256(
        _canonical_json(manifest, "company_actions.manifest").encode("utf-8")
    ).hexdigest()
    if digest.casefold() != expected_digest:
        raise _error("company_actions.digest", "does not match canonical manifest")
    return result


def normalize_atr_provenance(
    provenance: Mapping[str, Any],
    *,
    artifact: ATRArtifact,
    instrument: Mapping[str, Any] | str,
    market_date: date | str | datetime,
) -> dict[str, Any]:
    """Validate and normalize an explicit ``atr-provenance/v2`` object.

    The returned mapping is safe to persist as caller-provided evidence.  No
    source truth or point-in-time claim is inferred.  Required fields must be
    present even when a caller declares an unavailable input; unavailable and
    unknown statuses must carry a reason.
    """

    if not isinstance(provenance, Mapping):
        raise _error("provenance", "must be an object")
    required = {
        "contract",
        "feature",
        "instrument",
        "source",
        "algorithm",
        "basis",
        "calendar",
        "sessions",
        "halts",
        "previous_close",
        "company_actions",
    }
    missing = sorted(required - set(provenance))
    if missing:
        raise _error("provenance", f"missing required sections: {', '.join(missing)}")

    contract_obj = _required_mapping(provenance.get("contract"), "contract")
    if contract_obj.get("name") != PROVENANCE_CONTRACT_NAME:
        raise _error("contract.name", f"must be {PROVENANCE_CONTRACT_NAME}")
    if contract_obj.get("version") != PROVENANCE_CONTRACT_VERSION:
        raise _error("contract.version", f"must be {PROVENANCE_CONTRACT_VERSION}")
    if contract_obj.get("id") != PROVENANCE_CONTRACT_ID:
        raise _error("contract.id", f"must be {PROVENANCE_CONTRACT_ID}")
    if contract_obj.get("mode") != PROVENANCE_MODE:
        raise _error("contract.mode", f"must be {PROVENANCE_MODE}")
    contract = {
        "name": PROVENANCE_CONTRACT_NAME,
        "version": PROVENANCE_CONTRACT_VERSION,
        "id": PROVENANCE_CONTRACT_ID,
        "mode": PROVENANCE_MODE,
    }

    feature_obj = _required_mapping(provenance.get("feature"), "feature")
    feature_name = _required_text(feature_obj.get("name"), "feature.name")
    feature_version = _required_text(feature_obj.get("version"), "feature.version")
    if feature_version != artifact.feature_version:
        raise _error("feature.version", "must match ATRArtifact.feature_version")
    feature = dict(_canonical(feature_obj, "feature"))
    feature.update({"name": feature_name, "version": feature_version})

    normalized_instrument = _instrument(provenance.get("instrument"))
    supplied_instrument = instrument
    if isinstance(supplied_instrument, str):
        pieces = supplied_instrument.strip().split(":", 1)
        if len(pieces) != 2:
            raise _error("instrument", "caller instrument must include exchange:symbol")
        supplied_exchange, supplied_symbol = pieces
    else:
        supplied_exchange = supplied_instrument.get("exchange")
        supplied_symbol = supplied_instrument.get("symbol")
    if (
        normalized_instrument["exchange"] != _required_text(supplied_exchange, "instrument.exchange").upper()
        or normalized_instrument["symbol"] != _required_text(supplied_symbol, "instrument.symbol").upper()
    ):
        raise _error("instrument", "contract identity does not match writer identity")

    normalized_market_date = _market_date(market_date)
    source_obj = _required_mapping(provenance.get("source"), "source")
    source_snapshot = _snapshot(source_obj.get("snapshot"), "source.snapshot")
    source = dict(_canonical(source_obj, "source"))
    source.update({
        "source_ref": _required_text(source_obj.get("source_ref"), "source.source_ref"),
        "version": _required_text(source_obj.get("version"), "source.version"),
        "snapshot": source_snapshot,
        "snapshot_id": source_snapshot["id"],
        "snapshot_hash": source_snapshot["hash"],
        "coverage_window": _coverage_window(
            source_obj.get("coverage_window"),
            "source.coverage_window",
            terminal=normalized_market_date,
        ),
        "ordered_source_rows": _ordered_source_rows(
            source_obj.get("ordered_source_rows"), "source.ordered_source_rows"
        ),
        "availability": _availability(source_obj.get("availability"), "source.availability"),
    })

    algorithm = _algorithm(provenance.get("algorithm"), artifact)
    basis = _basis(provenance.get("basis"), artifact)
    if basis["scope"]["terminal_market_date"] != normalized_market_date.isoformat():
        raise _error("basis.scope", "terminal_market_date must match market_date")
    calendar = _versioned_evidence(
        provenance.get("calendar"), "calendar", reference_key="calendar_ref"
    )
    calendar["coverage_window"] = _coverage_window(
        provenance["calendar"].get("coverage_window"),
        "calendar.coverage_window",
        terminal=normalized_market_date,
    )
    sessions_obj = _required_mapping(provenance.get("sessions"), "sessions")
    sessions = _versioned_evidence(sessions_obj, "sessions", reference_key="session_ref")
    sessions["coverage_window"] = _coverage_window(
        sessions_obj.get("coverage_window"),
        "sessions.coverage_window",
        terminal=normalized_market_date,
    )
    normalized_sessions = _session_entries(
        sessions_obj.get("ordered_sessions"), "sessions.ordered_sessions"
    )
    if [entry["session_date"] for entry in normalized_sessions] != [
        observation.trading_date.isoformat() for observation in artifact.observations
    ]:
        raise _error("sessions.ordered_sessions", "must match ATRArtifact observation dates")
    sessions["ordered_sessions"] = normalized_sessions
    halts_obj = _required_mapping(provenance.get("halts"), "halts")
    halts = _versioned_evidence(halts_obj, "halts", reference_key="halt_ref")
    halts["coverage_window"] = _coverage_window(
        halts_obj.get("coverage_window"),
        "halts.coverage_window",
        terminal=normalized_market_date,
    )
    halts["session_statuses"] = _session_entries(
        halts_obj.get("session_statuses"),
        "halts.session_statuses",
        allowed_statuses={"no_halt", "halted", "resumed", "unknown"},
    )
    if [entry["session_date"] for entry in halts["session_statuses"]] != [
        entry["session_date"] for entry in normalized_sessions
    ]:
        raise _error("halts.session_statuses", "must cover the same ordered sessions")
    previous_close = _previous_close(provenance.get("previous_close"), artifact)
    company_actions = _company_actions(provenance.get("company_actions"))
    if company_actions["coverage_window"]["terminal_market_date"] != normalized_market_date.isoformat():
        raise _error(
            "company_actions.coverage_window",
            "terminal_market_date must match market_date",
        )
    if normalized_market_date != artifact.observations[-1].trading_date:
        raise _error("market_date", "must match the final ATR observation")
    if artifact.input_snapshot_ref.strip() != source_snapshot["id"]:
        raise _error("source.snapshot.id", "must match ATRArtifact.input_snapshot_ref")

    observation_dates = [observation.trading_date.isoformat() for observation in artifact.observations]
    if len(source["ordered_source_rows"]) != len(observation_dates):
        raise _error("source.ordered_source_rows", "must cover every ATR observation")
    for index, row in enumerate(source["ordered_source_rows"]):
        if row["market_date"] != observation_dates[index]:
            raise _error("source.ordered_source_rows", "row dates must match ATR observations")
        if row["snapshot_id"] != source_snapshot["id"]:
            raise _error(f"source.ordered_source_rows[{index}].snapshot_id", "does not match source snapshot")
        if row["price_basis"] != artifact.price_basis:
            raise _error(f"source.ordered_source_rows[{index}].price_basis", "does not match artifact basis")
        observation = artifact.observations[index]
        expected_status = (
            "suspended"
            if observation.is_suspended
            else "bar"
            if observation.bar_present
            else "no_bar"
        )
        if row["row_status"] != expected_status and row["row_status"] != "unknown":
            raise _error(f"source.ordered_source_rows[{index}].row_status", "does not match observation")
        session_entry = normalized_sessions[index]
        if session_entry["status"] not in {"open", expected_status, "closed"}:
            raise _error(f"sessions.ordered_sessions[{index}].status", "does not match observation")
        if expected_status == "suspended" and session_entry["status"] == "open":
            raise _error(f"sessions.ordered_sessions[{index}].status", "cannot mark a suspended observation open")
        if expected_status != "suspended" and session_entry["status"] == "suspended":
            raise _error(f"sessions.ordered_sessions[{index}].status", "cannot mark an active observation suspended")
        halt_entry = halts["session_statuses"][index]
        if observation.is_suspended and halt_entry["status"] not in {"halted", "resumed"}:
            raise _error(f"halts.session_statuses[{index}].status", "does not explain suspended observation")
        if not observation.is_suspended and halt_entry["status"] == "halted":
            raise _error(f"halts.session_statuses[{index}].status", "conflicts with non-suspended observation")

    # A selected current row is an input to the ATR sequence and must be
    # traceable to the ordered source rows.  A predecessor may legitimately
    # come from an external previous-close snapshot; when it declares the
    # current source snapshot and lies inside its covered window, however, its
    # date, snapshot and row reference must also resolve exactly.
    source_rows_by_key = {
        (row["market_date"], row["snapshot_id"], row["row_ref"]): row
        for row in source["ordered_source_rows"]
    }
    source_window = source["coverage_window"]
    source_start = date.fromisoformat(source_window["start_date"])
    source_end = date.fromisoformat(source_window["end_date"])
    selected_previous = previous_close.get("selected") or []
    if isinstance(selected_previous, Mapping):
        selected_previous = [selected_previous]
    for index, selected in enumerate(selected_previous):
        current = selected["current"]
        current_key = (
            current["market_date"],
            current["snapshot_id"],
            current["row_ref"],
        )
        if current["snapshot_id"] != source_snapshot["id"] or current["snapshot_hash"] != source_snapshot["hash"]:
            raise _error(
                f"previous_close.selected[{index}].current",
                "must use the source snapshot for the selected current row",
            )
        if current_key not in source_rows_by_key:
            raise _error(
                f"previous_close.selected[{index}].current",
                "date, snapshot and row_ref must match an ordered source row",
            )
        predecessor = selected["predecessor"]
        predecessor_date = date.fromisoformat(predecessor["market_date"])
        if (
            predecessor["snapshot_id"] == source_snapshot["id"]
            and source_start <= predecessor_date <= source_end
        ):
            predecessor_key = (
                predecessor["market_date"],
                predecessor["snapshot_id"],
                predecessor["row_ref"],
            )
            if predecessor["snapshot_hash"] != source_snapshot["hash"] or predecessor_key not in source_rows_by_key:
                raise _error(
                    f"previous_close.selected[{index}].predecessor",
                    "date, snapshot and row_ref must match an ordered source row when within its source window",
                )

    action_exchange, action_symbol = normalized_instrument["exchange"], normalized_instrument["symbol"]
    artifact_actions = [dict(action) for action in artifact.corporate_actions]
    action_refs = {str(action.get("source_ref")) for action in artifact_actions}
    if not company_actions["manifest"] and artifact.corporate_actions:
        raise _error("company_actions.manifest", "empty manifest conflicts with ATRArtifact actions")
    for index, action in enumerate(company_actions["manifest"]):
        action_instrument = action["instrument"]
        if (
            _required_text(action_instrument.get("exchange"), f"company_actions.manifest[{index}].instrument.exchange").upper()
            != action_exchange
            or _required_text(action_instrument.get("symbol"), f"company_actions.manifest[{index}].instrument.symbol").upper()
            != action_symbol
        ):
            raise _error(f"company_actions.manifest[{index}].instrument", "does not match artifact instrument")
        if action["to_basis"] != artifact.price_basis and action["from_basis"] != artifact.price_basis:
            raise _error(f"company_actions.manifest[{index}]", "from/to basis does not reference artifact basis")
        matches = [item for item in artifact_actions if item.get("source_ref") == action["source_ref"]]
        if not matches:
            raise _error(f"company_actions.manifest[{index}].source_ref", "does not reference ATRArtifact action")
        matching_action = matches[0]
        artifact_action_date = matching_action.get("action_date", matching_action.get("date"))
        if artifact_action_date is None or _market_date(artifact_action_date).isoformat() != action["action_date"]:
            raise _error(f"company_actions.manifest[{index}].action_date", "does not match ATRArtifact action")
        artifact_ex_date = matching_action.get("ex_date")
        if artifact_ex_date is not None and _market_date(artifact_ex_date).isoformat() != action["ex_date"]:
            raise _error(f"company_actions.manifest[{index}].ex_date", "does not match ATRArtifact action")
        artifact_type = matching_action.get("action_type", matching_action.get("type"))
        if artifact_type != action["action_type"]:
            raise _error(f"company_actions.manifest[{index}].action_type", "does not match ATRArtifact action")
        artifact_basis = matching_action.get("price_basis")
        if artifact_basis is not None and artifact_basis != action["to_basis"]:
            raise _error(f"company_actions.manifest[{index}].to_basis", "does not match ATRArtifact action")
        artifact_coverage = matching_action.get("coverage")
        if artifact_coverage is not None and str(artifact_coverage).casefold() != "complete":
            raise _error(f"company_actions.manifest[{index}]", "artifact action coverage is not complete")
        action_available_at = matching_action.get("available_at")
        declared_available_at = company_actions["manifest"][index]["availability"].get("available_at")
        if declared_available_at is not None:
            if action_available_at is None or _timestamp(action_available_at, f"artifact.corporate_actions[{index}].available_at") != declared_available_at:
                raise _error(f"company_actions.manifest[{index}].availability", "does not match ATRArtifact action")

    incomplete_sections: list[str] = []
    for section, value in {
        "source": source,
        "basis": basis,
        "calendar": calendar,
        "sessions": sessions,
        "halts": halts,
        "previous_close": previous_close,
        "company_actions": company_actions,
    }.items():
        availability = value.get("availability")
        if isinstance(availability, Mapping) and availability.get("status") in {"unknown", "unavailable"}:
            incomplete_sections.append(section)
    for index, row in enumerate(source["ordered_source_rows"]):
        if row["row_status"] == "unknown":
            incomplete_sections.append(f"source.ordered_source_rows[{index}]")
        if row["availability"].get("status") in {"unknown", "unavailable"}:
            incomplete_sections.append(f"source.ordered_source_rows[{index}].availability")
    for index, row in enumerate(normalized_sessions):
        if row["status"] == "unknown" or row["availability"].get("status") in {"unknown", "unavailable"}:
            incomplete_sections.append(f"sessions.ordered_sessions[{index}]")
    for index, row in enumerate(halts["session_statuses"]):
        if row["status"] == "unknown" or row["availability"].get("status") in {"unknown", "unavailable"}:
            incomplete_sections.append(f"halts.session_statuses[{index}]")
    selected_previous = previous_close.get("selected") or []
    if isinstance(selected_previous, Mapping):
        selected_previous = [selected_previous]
    for index, selected in enumerate(selected_previous):
        if selected.get("availability", {}).get("status") in {"unknown", "unavailable"}:
            incomplete_sections.append(f"previous_close.selected[{index}].availability")
    for index, action in enumerate(company_actions["manifest"]):
        if action["availability"].get("status") in {"unknown", "unavailable"}:
            incomplete_sections.append(f"company_actions.manifest[{index}].availability")
    if company_actions["coverage"] != "complete":
        incomplete_sections.append("company_actions.coverage")
    if previous_close["status"] in {"unknown", "unavailable"}:
        incomplete_sections.append("previous_close")
    if incomplete_sections and any(
        observation.atr is not None or observation.true_range is not None
        for observation in artifact.observations
    ):
        raise _error(
            "artifact",
            "complete ATR values cannot be persisted with unknown/unavailable required provenance; preserve null/incomplete outputs",
        )

    normalized = {
        "contract": contract,
        "feature": feature,
        "instrument": normalized_instrument,
        "source": source,
        "algorithm": algorithm,
        "basis": basis,
        "calendar": calendar,
        "sessions": sessions,
        "halts": halts,
        "previous_close": previous_close,
        "company_actions": company_actions,
    }
    return json.loads(_canonical_json(normalized, "provenance"))


def validate_stored_atr_provenance(
    value: Mapping[str, Any],
    *,
    artifact: ATRArtifact,
    instrument: Mapping[str, Any],
    market_date: date | str | datetime,
) -> dict[str, Any]:
    """Validate the persisted v2 marker and all structure on strict reads."""

    if not isinstance(value, Mapping):
        raise _error("stored.provenance", "must be an object")
    contract = value.get("contract")
    if not isinstance(contract, Mapping) or contract.get("id") != PROVENANCE_CONTRACT_ID:
        raise _error("stored.provenance.contract", "strict v2 marker is missing or invalid")
    return normalize_atr_provenance(
        value,
        artifact=artifact,
        instrument=instrument,
        market_date=market_date,
    )


def provenance_digest(value: Mapping[str, Any]) -> str:
    """Return a deterministic digest useful for comparison provenance output."""

    return hashlib.sha256(_canonical_json(value, "provenance").encode("utf-8")).hexdigest()


__all__ = [
    "PROVENANCE_CONTRACT_ID",
    "PROVENANCE_CONTRACT_NAME",
    "PROVENANCE_CONTRACT_VERSION",
    "PROVENANCE_MODE",
    "ProvenanceContractError",
    "normalize_atr_provenance",
    "provenance_digest",
    "validate_stored_atr_provenance",
]
