"""Read one exact worker capture into an opt-in signal-artifact candidate.

The candidate is a new research observation. Capture timestamps, the original
source-container hash and an opaque legacy Signal are not historical PIT proof.
This module never opens a SignalArtifactStore or writes to the research DB.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re
import sqlite3

from app.rule_replay import _canonical
from app.signal_artifact import (
    CALLER_PROVIDED_ONLY,
    EARLIEST_EXECUTION_UNAVAILABLE_REASON,
    SIGNAL_ARTIFACT_VERSION,
    SIGNAL_CONFIDENCE_SEMANTICS_VERSION,
    SignalArtifactContractError,
    _timestamp,
    digest_json,
    digest_text,
    normalize_signal_artifact,
)
from app.signal_artifact_store import readonly_snapshot
from worker.analysis_capture import (
    AnalysisCaptureError, KIND_V2, SELECTED_BAR_SCHEMA, _read_analysis_attempt, _seal,
)


INPUT_MANIFEST_SCHEMA = "worker-capture-input-manifest/v1"
INPUT_SNAPSHOT_ID_PREFIX = "worker-capture-input/v1"
INPUT_MANIFEST_SCHEMA_V2 = "worker-capture-input-manifest/v2"
INPUT_SNAPSHOT_ID_PREFIX_V2 = "worker-capture-input/v2"


class SignalArtifactBridgeError(ValueError):
    """An exact capture cannot be mapped to the narrow candidate contract."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _decision_time(value: datetime | str) -> str:
    try:
        return _timestamp(value, "decision_at")
    except SignalArtifactContractError as exc:
        raise SignalArtifactBridgeError("invalid_decision_at") from exc


def _unchanged_subject(subject: dict) -> None:
    for key in ("market", "exchange", "symbol"):
        value = subject[key]
        if type(value) is not str or not value or value != value.strip().upper():
            raise SignalArtifactBridgeError("subject_normalization_required")


def _strict_attempt(connection: sqlite3.Connection, path, attempt_id: str) -> dict:
    try:
        return _read_analysis_attempt(
            research_database_path=path, attempt_id=attempt_id, _connection=connection,
        )
    except AnalysisCaptureError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, sqlite3.Error) as exc:
        # Match the public capture reader's malformed-record boundary.
        raise AnalysisCaptureError("capture_integrity_error", detail=type(exc).__name__) from exc


def _selected_bar_manifest_projection(provenance: dict) -> dict:
    """Hash only stable input-row claims, never observation time or raw path."""
    bar, raw = provenance["bar"], provenance["raw_payload"]
    return {
        "schema": SELECTED_BAR_SCHEMA,
        "coverage": ["close", "volume"],
        "bar": {key: bar[key] for key in (
            "id", "instrument_id", "trading_date", "close", "volume", "source", "raw_payload_id",
        )},
        "raw_payload": ({key: raw[key] for key in (
            "id", "source", "endpoint", "sha256", "ingestion_run_id",
        )} if raw is not None else None),
        "raw_status": provenance["raw_status"],
        "raw_reason": provenance["raw_reason"],
    }


def build_signal_artifact_candidate(
    *, research_snapshot_path, expected_snapshot_sha256, attempt_id, ordinal, decision_at,
) -> dict:
    """Return one detached candidate after validating the complete exact attempt.

    ``expected_snapshot_sha256`` is for the *current* owned research snapshot.
    The owner's original source SHA is only an upstream container reference.
    Saving and choosing an artifact attempt/run remain the caller's work.
    """
    if type(expected_snapshot_sha256) is not str or re.fullmatch(
        r"[0-9a-fA-F]{64}", expected_snapshot_sha256,
    ) is None:
        raise SignalArtifactBridgeError("expected_snapshot_sha256_required")
    if type(ordinal) is not int or ordinal < 0:
        raise SignalArtifactBridgeError("invalid_ordinal")
    adopted_at = _decision_time(decision_at)

    with readonly_snapshot(
        research_snapshot_path, expected_database_sha256=expected_snapshot_sha256,
    ) as (connection, fingerprint):
        verified = _strict_attempt(connection, research_snapshot_path, attempt_id)
        calls = verified["captures"]
        if ordinal >= len(calls):
            raise SignalArtifactBridgeError("ordinal_not_found")
        call = calls[ordinal]
        receipt = verified["receipt"]
        version_two = receipt["kind"] == KIND_V2
        selected = call["selected_strategy"]
        signal = call["signal_snapshot"]
        bundle = call["bundle"]
        subject = call["subject"]

        if call["evaluator"] != selected["name"]:
            raise SignalArtifactBridgeError("evaluator_not_selected_strategy")
        _unchanged_subject(subject)
        if signal["status"] != signal["status"].strip():
            raise SignalArtifactBridgeError("status_normalization_required")
        if any(
            datetime.fromisoformat(adopted_at) < datetime.fromisoformat(item["captured_at"])
            for item in (call, receipt)
        ):
            raise SignalArtifactBridgeError("decision_before_capture")

        config = selected["config"]
        config_digest = digest_json(config, field_name="selected_strategy.config")
        if config_digest != bundle["config_digest"]:
            raise SignalArtifactBridgeError("config_digest_mismatch")
        implementation = bundle["implementation"]
        if implementation["id"] != "domain-rules/v1":
            raise SignalArtifactBridgeError("implementation_binding_mismatch")

        # A versioned input-only manifest: no result, status, captured/receipt
        # time or current research-container SHA enters this digest.
        manifest = {
            "schema": INPUT_MANIFEST_SCHEMA_V2 if version_two else INPUT_MANIFEST_SCHEMA,
            "subject": subject,
            "market_date": call["observed_market_date"],
            "strategy": {"id": selected["id"], "name": selected["name"],
                         "version": selected["version"]},
            "evaluator": call["evaluator"],
            "arguments": call["arguments"],
            "config_snapshot": config,
            "evaluator_binding": {
                "schema_version": bundle["schema_version"],
                "strategy_version": bundle["strategy_version"],
                "implementation": implementation,
                "config_digest": bundle["config_digest"],
                "arguments_digest": bundle["arguments_digest"],
            },
            "upstream_refs": {
                "original_source_container_sha256": receipt["source_snapshot"]["sha256"],
                "source_collection_run_id": receipt["source_collection_run_id"],
                "legacy_signal": {"id": signal["id"], "signal_key": signal["signal_key"]},
            },
        }
        if version_two:
            manifest["selected_bar_input"] = _selected_bar_manifest_projection(call["input_provenance"])
        manifest_json = _canonical(manifest)
        manifest_digest = digest_text(manifest_json)
        # Re-decode and re-encode at the candidate boundary, where the exact
        # manifest becomes the only stated basis for input_snapshot.hash.
        if digest_text(_canonical(json.loads(manifest_json))) != manifest_digest:
            raise SignalArtifactBridgeError("input_manifest_digest_mismatch")

        call_row = connection.execute(
            "SELECT payload,digest FROM worker_capture_calls WHERE attempt_id=? AND ordinal=?",
            (attempt_id, ordinal),
        ).fetchone()
        receipt_row = connection.execute(
            "SELECT payload,digest FROM worker_capture_attempts WHERE attempt_id=?",
            (attempt_id,),
        ).fetchone()
        if (call_row is None or receipt_row is None
                or call_row["digest"] != receipt["call_digests"][ordinal]
                or call_row["digest"] != _seal(call)
                or receipt_row["digest"] != _seal(receipt)):
            raise SignalArtifactBridgeError("capture_seal_mismatch")

        evidence = {
            "bridge_schema": "worker-capture-candidate/v2" if version_two else "worker-capture-candidate/v1",
            "input_manifest_json": manifest_json,
            "input_manifest_digest": manifest_digest,
            "call_json": call_row["payload"],
            "call_digest": "sha256:" + call_row["digest"],
            "receipt_json": receipt_row["payload"],
            "receipt_derived_seal": "sha256:" + hashlib.sha256(
                receipt_row["payload"].encode("utf-8")
            ).hexdigest(),
            "research_snapshot_path": fingerprint["path"],
            "research_snapshot_sha256": "sha256:" + fingerprint["sha256"],
            "original_source_container_sha256": "sha256:" + receipt["source_snapshot"]["sha256"],
        }
        if version_two:
            provenance_json = _canonical(call["input_provenance"])
            evidence.update({
                "input_provenance_json": provenance_json,
                "input_provenance_digest": digest_text(provenance_json),
                "raw_bytes_verification": "bytes_unverified",
            })
        missing = [
            "remaining_raw_input_rows_and_source_versions_unavailable" if version_two
                else "raw_input_rows_and_source_versions_unavailable",
            "input_availability_unverified",
            "historical_decision_time_unavailable",
            "price_basis_unverified",
            "adapter_pipeline_legacy_status_levels_implementation_unbound",
        ]
        if version_two:
            missing.insert(1, "selected_bar_raw_bytes_and_source_version_unverified")
            if call["input_provenance"]["raw_status"] == "unknown":
                missing.insert(2, "selected_bar_raw_payload_metadata_unavailable")
        candidate = normalize_signal_artifact({
            "contract": SIGNAL_ARTIFACT_VERSION,
            "instrument": {"exchange": subject["exchange"], "symbol": subject["symbol"]},
            "market_date": call["observed_market_date"],
            "strategy": {"name": selected["name"], "version": selected["version"]},
            "signal_output_semantics": SIGNAL_CONFIDENCE_SEMANTICS_VERSION,
            "status": signal["status"],
            "rule_state": call["actual_result"],
            "confidence": None,
            "feature_artifact_refs": [],
            "input_snapshot": {
                "id": f"{INPUT_SNAPSHOT_ID_PREFIX_V2 if version_two else INPUT_SNAPSHOT_ID_PREFIX}:{receipt['database_id']}/{attempt_id}/{ordinal}",
                "hash": manifest_digest,
            },
            "ruleset_snapshot": config,
            "ruleset_digest": config_digest,
            "implementation_digest": implementation["source_sha256"],
            "implementation_ref": {
                "mode": CALLER_PROVIDED_ONLY,
                "verification": "not_officially_verified",
                "ref": implementation["id"],
                "digest": implementation["source_sha256"],
            },
            "basis_manifest": {
                "mode": CALLER_PROVIDED_ONLY,
                "verification": "not_officially_verified",
                "status": "unknown", "value": None,
                "reason": "price_basis_unverified_from_capture",
            },
            "dependency_manifest": {
                "mode": CALLER_PROVIDED_ONLY,
                "verification": "not_officially_verified",
                "references": (["domain-rules/v1", KIND_V2, SELECTED_BAR_SCHEMA]
                               if version_two else ["domain-rules/v1", "worker-analysis-capture/v1"]),
                "unknown_reasons": missing,
            },
            "rule_evidence": {"capture_bridge": evidence},
            "data_quality": {
                "scope": "new_research_capture_candidate_only",
                "source_verification": "not_officially_verified",
                "availability_verification": "unknown",
                "historical_inputs_verification": "unknown",
                **({
                    "local_input_row_linkage": "close_volume_metadata_captured",
                    "raw_payload_metadata": call["input_provenance"]["raw_status"],
                    "raw_bytes_verification": "bytes_unverified",
                } if version_two else {}),
            },
            "missing_reasons": missing,
            "decision_at": adopted_at,
            "as_of_at": None,
            "earliest_execution_at": None,
            "earliest_execution_reason": EARLIEST_EXECUTION_UNAVAILABLE_REASON,
            "legacy_reference": f"worker-capture-legacy-signal/v1:{receipt['database_id']}/{signal['id']}",
            "generated_at": adopted_at,
        }, include_generated=True)
        normalized_evidence = candidate["rule_evidence"]["capture_bridge"]
        if (candidate["input_snapshot"]["hash"] != digest_text(normalized_evidence["input_manifest_json"])
                or normalized_evidence != evidence
                or (version_two and digest_text(normalized_evidence["input_provenance_json"])
                    != normalized_evidence["input_provenance_digest"])
                or candidate["status"] != signal["status"]
                or candidate["rule_state"] != call["actual_result"]):
            raise SignalArtifactBridgeError("candidate_projection_mismatch")
        return candidate


__all__ = ["SignalArtifactBridgeError", "build_signal_artifact_candidate"]
