"""Opt-in descriptive comparison of two explicit, stable external snapshots.

No database initialization, ORM, worker, rule replay, default selection or PIT
inference. Equal subjects or raw values never establish equivalent research.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from .domain import signal_confidence_semantics
from .signal_artifact_store import (
    ReadonlySnapshotError, SignalArtifactNotFoundError, SignalArtifactStore,
    readonly_snapshot, snapshot_fingerprint,
)


class SignalComparisonError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_LEVELS = ("reference_entry", "pullback_low", "pullback_high", "breakout_price",
           "invalid_price", "target_1", "target_2")
_DATES = ("signal_date", "earliest_execution_date", "execution_date")
_SIGNAL_FIELDS = ("id", "signal_key", "instrument_id", "strategy_version_id", "status",
                  "entry_type", *_LEVELS, "confidence", "rationale", "data_cutoff",
                  "source_report", *_DATES, "execution_price", "data_quality",
                  "rule_evidence_json", "created_at")
_SCHEMA = {"signals": _SIGNAL_FIELDS, "instruments": ("id", "exchange", "symbol"),
           "strategy_versions": ("id", "name", "version")}


def _text(value: Any, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SignalComparisonError("invalid_" + field)
    return value


def _positive_id(value: Any, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise SignalComparisonError("invalid_" + field)
    return value


def _selector(value: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"artifact_key", "identity_hash", "lineage_key", "revision"}
    if not isinstance(value, Mapping) or not value or set(value) - allowed:
        raise SignalComparisonError("invalid_artifact_selector")
    result = dict(value)
    if not set(result) & {"artifact_key", "identity_hash", "lineage_key"}:
        raise SignalComparisonError("exact_artifact_selector_required")
    for key in ("artifact_key", "identity_hash", "lineage_key"):
        if key in result:
            _text(result[key], "selector_" + key)
            if result[key] != result[key].strip():
                raise SignalComparisonError("invalid_selector_" + key)
    if "revision" in result:
        _positive_id(result["revision"], "selector_revision")
    if "lineage_key" in result and "revision" not in result:
        raise SignalComparisonError("exact_revision_required")
    return result


def _legacy_schema(connection: sqlite3.Connection) -> None:
    descriptors = {row[1]: row[2] for row in connection.execute("PRAGMA table_list") if row[0] == "main"}
    for table, required in _SCHEMA.items():
        if descriptors.get(table) != "table":
            raise SignalComparisonError("invalid_legacy_schema")
        columns = {row[1]: row for row in connection.execute(f'PRAGMA table_xinfo("{table}")')}
        if any(name not in columns or columns[name][6] != 0 for name in required):
            raise SignalComparisonError("invalid_legacy_schema")


def _strict_evidence(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise SignalComparisonError("invalid_legacy_evidence")
    def reject_constant(value: str):
        raise ValueError(value)
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate object key")
            result[key] = value
        return result
    try:
        value = json.loads(raw, parse_constant=reject_constant, object_pairs_hook=unique_object)
        # Numeric exponent overflow is not routed through parse_constant.
        json.dumps(value, allow_nan=False)
    except (ValueError, TypeError, RecursionError) as exc:
        raise SignalComparisonError("invalid_legacy_evidence") from exc
    if not isinstance(value, dict):
        raise SignalComparisonError("invalid_legacy_evidence")
    return value


def _legacy_read(connection: sqlite3.Connection, signal_key: str) -> dict[str, Any] | None:
    _legacy_schema(connection)
    fields = ",".join('"' + name + '"' for name in _SIGNAL_FIELDS)
    rows = connection.execute(f"SELECT {fields} FROM signals WHERE signal_key = ? COLLATE BINARY", (signal_key,)).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise SignalComparisonError("legacy_signal_ambiguous")
    row = dict(rows[0])
    if not isinstance(row["signal_key"], str) or row["signal_key"] != signal_key:
        raise SignalComparisonError("legacy_exact_key_mismatch")
    for key in ("id", "instrument_id", "strategy_version_id"):
        _positive_id(row[key], "legacy_" + key)
    instrument = connection.execute("SELECT id,exchange,symbol FROM instruments WHERE id=?", (row["instrument_id"],)).fetchall()
    strategy = connection.execute("SELECT id,name,version FROM strategy_versions WHERE id=?", (row["strategy_version_id"],)).fetchall()
    if len(instrument) != 1 or len(strategy) != 1:
        raise SignalComparisonError("legacy_fk_missing_or_ambiguous")
    instrument, strategy = dict(instrument[0]), dict(strategy[0])
    _positive_id(instrument["id"], "legacy_instrument_id")
    _positive_id(strategy["id"], "legacy_strategy_version_id")
    for key in ("exchange", "symbol"):
        value = _text(instrument[key], "legacy_" + key)
        if value != value.strip() or value != value.upper():
            raise SignalComparisonError("noncanonical_legacy_instrument")
    for key in ("name", "version"):
        value = _text(strategy[key], "legacy_strategy_" + key)
        if value != value.strip():
            raise SignalComparisonError("noncanonical_legacy_strategy")
    count = connection.execute(
        "SELECT count(*) FROM instruments WHERE exchange=? COLLATE BINARY AND symbol=? COLLATE BINARY",
        (instrument["exchange"], instrument["symbol"])).fetchone()[0]
    if count != 1:
        raise SignalComparisonError("legacy_instrument_identity_ambiguous")
    for key in ("signal_key", "status", "entry_type", "data_quality"):
        _text(row[key], "legacy_" + key)
    for key in ("rationale", "data_cutoff", "source_report", "created_at"):
        if row[key] is not None and not isinstance(row[key], str):
            raise SignalComparisonError("invalid_legacy_" + key)
    for key in _DATES:
        value = row[key]
        if value is None and key != "signal_date":
            continue
        try:
            if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                raise ValueError(value)
        except ValueError as exc:
            raise SignalComparisonError("invalid_legacy_" + key) from exc
    for key in (*_LEVELS, "confidence", "execution_price"):
        value = row[key]
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
            raise SignalComparisonError("invalid_legacy_" + key)
    evidence = _strict_evidence(row.pop("rule_evidence_json"))
    if evidence is not None:
        for field, expected in (("strategy", strategy["name"]), ("strategy_version", strategy["version"])):
            if field in evidence and (not isinstance(evidence[field], str) or evidence[field] != expected):
                raise SignalComparisonError("legacy_identity_evidence_conflict")
    row["subject"] = {"exchange": instrument["exchange"], "symbol": instrument["symbol"],
                      "market_date": row["signal_date"], "strategy_name": strategy["name"],
                      "strategy_version": strategy["version"]}
    row["rule_evidence"] = evidence
    row["evidence_reason"] = "legacy_evidence_unavailable" if evidence is None else None
    row["confidence_semantics"] = signal_confidence_semantics(
        row["confidence"], strategy_name=strategy["name"], strategy_version=strategy["version"])
    return row


def comparison_json(report: Mapping[str, Any]) -> str:
    """Stable UTF-8-compatible JSON text; no current time or numeric coercions."""
    return json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def compare_signals(*, legacy_path: str | Path, legacy_expected_database_sha256: str,
                    legacy_signal_key: str, artifact_path: str | Path,
                    artifact_expected_database_sha256: str,
                    artifact_selector: Mapping[str, Any]) -> dict[str, Any]:
    _text(legacy_signal_key, "legacy_signal_key")
    selector = _selector(artifact_selector)
    # Required hashes cannot use the optional-fingerprint factory behavior.
    for value in (legacy_expected_database_sha256, artifact_expected_database_sha256):
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
            raise ReadonlySnapshotError("invalid_expected_database_sha256")
    legacy_before = snapshot_fingerprint(legacy_path, expected_database_sha256=legacy_expected_database_sha256)
    new_before = snapshot_fingerprint(artifact_path, expected_database_sha256=artifact_expected_database_sha256)
    if os.path.samefile(legacy_path, artifact_path):
        raise ReadonlySnapshotError("same_snapshot_pair")
    try:
        with readonly_snapshot(legacy_path, expected_database_sha256=legacy_expected_database_sha256) as (connection, _):
            legacy = _legacy_read(connection, legacy_signal_key)
        with SignalArtifactStore.open_readonly(artifact_path, expected_database_sha256=artifact_expected_database_sha256) as reader:
            try:
                new = reader.get_exact(**selector).to_dict()
            except SignalArtifactNotFoundError:
                new = None
    finally:
        # Recheck both, even when the second source or a row validation fails.
        after = [snapshot_fingerprint(legacy_path), snapshot_fingerprint(artifact_path)]
        if after != [legacy_before, new_before]:
            raise ReadonlySnapshotError("snapshot_changed")
    dimensions = {}
    both = legacy is not None and new is not None
    if both:
        payload = new["artifact"]
        subject = {"exchange": payload["instrument"]["exchange"], "symbol": payload["instrument"]["symbol"],
                   "market_date": payload["market_date"], "strategy_name": payload["strategy"]["name"],
                   "strategy_version": payload["strategy"]["version"]}
        equal = legacy["subject"] == subject
        dimensions["subject"] = {"status": "equal" if equal else "different", "legacy": legacy["subject"],
                                  "new": subject, "reasons": ["subject_equality_not_input_equivalence" if equal else "subject_mismatch"]}
        dimensions["status"] = {"status": "observational", "lexically_equal": legacy["status"] == payload["status"],
                                 "legacy": legacy["status"], "new": payload["status"], "reasons": ["raw_status_not_rule_or_lifecycle_equivalence"]}
    else:
        for key in ("subject", "status"):
            dimensions[key] = {"status": "unavailable", "reasons": ["selected_side_missing"]}
    if new is not None:
        reference = new["artifact"]["legacy_reference"]
        dimensions["linkage"] = {"status": "unknown" if reference is None else "match" if reference == legacy_signal_key else "conflict",
                                  "reasons": ["caller_linkage_unknown" if reference is None else "matching_caller_declaration_only" if reference == legacy_signal_key else "legacy_reference_conflict"]}
    else:
        dimensions["linkage"] = {"status": "unavailable", "reasons": ["new_artifact_missing"]}
    for dimension, reasons in (
        ("confidence", ["incomparable_confidence_semantics", "not_calibrated_not_probability"]),
        ("prices", ["new_levels_contract_absent"]),
        ("evidence", ["no_shared_evidence_contract"]),
        ("quality", ["no_shared_quality_contract"]),
        ("time", ["legacy_decision_at_not_persisted", "legacy_generated_at_not_persisted_with_timezone",
                  "legacy_date_only_execution_not_instant", "new_decision_asof_caller_provided_not_officially_verified",
                  "store_generation_creation_metadata_not_availability_pit_execution"]),
        ("revision", ["legacy_revision_unavailable", "lifecycle_not_trading_state"]),
        ("inputs", ["legacy_sealed_inputs_unavailable", "caller_provided_only", "not_officially_verified",
                    "no_paired_replay_or_pit_truth"]),
    ):
        dimensions[dimension] = {"status": "incomparable", "reasons": reasons}
    reasons = (["legacy_signal_missing"] if legacy is None else []) + (["new_artifact_missing"] if new is None else [])
    for dimension in dimensions.values():
        reasons.extend(code for code in dimension["reasons"] if code not in reasons)
    report = {"contract": "signal-comparison/v1", "comparable": False,
              "inputs": {"legacy": {**legacy_before, "selector": {"signal_key": legacy_signal_key}},
                         "new": {**new_before, "selector": selector}},
              "legacy": {"state": "missing" if legacy is None else "present", "reason": "legacy_signal_missing" if legacy is None else None, "snapshot": legacy},
              "new": {"state": "missing" if new is None else "present", "reason": "new_artifact_missing" if new is None else None, "artifact": new},
              "dimensions": dimensions, "reasons": reasons}
    return json.loads(comparison_json(report))
