from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import pytest

from app.signal_artifact import (
    CALLER_PROVIDED_ONLY,
    EARLIEST_EXECUTION_UNAVAILABLE_REASON,
    SIGNAL_CONFIDENCE_SEMANTICS_VERSION,
    SignalArtifactContractError,
    canonical_json,
    digest_json,
    digest_text,
    normalize_signal_artifact,
)


NOW = "2026-01-01T01:00:00+00:00"


def _artifact(**changes: Any) -> dict[str, Any]:
    basis = {
        "mode": CALLER_PROVIDED_ONLY,
        "verification": "not_officially_verified",
        "status": "provided",
        "value": "raw_close",
        "reason": None,
    }
    dependency = {
        "mode": CALLER_PROVIDED_ONLY,
        "verification": "not_officially_verified",
        "references": ["fixture:bars"],
        "unknown_reasons": [],
    }
    implementation_digest = digest_text("implementation:v1")
    result: dict[str, Any] = {
        "contract": "signal-artifact/v1",
        "lineage_subject": "signal",
        "instrument": {"exchange": "TWSE", "symbol": "2330"},
        "market_date": "2026-01-01",
        "strategy": {"name": "demo_rule", "version": "1.0.0"},
        "signal_output_semantics": {
            "version": SIGNAL_CONFIDENCE_SEMANTICS_VERSION,
            "kind": "rule_only",
            "is_calibrated": False,
            "is_probability": False,
        },
        "status": "conditional",
        "rule_state": {"matched": True},
        "feature_artifact_refs": ["feature:v1:atr"],
        "input_snapshot": {"id": "snapshot-1", "hash": digest_text("snapshot-1")},
        "ruleset_snapshot": {"threshold": 1},
        "basis_manifest": basis,
        "dependency_manifest": dependency,
        "implementation_digest": implementation_digest,
        "implementation_ref": {
            "mode": CALLER_PROVIDED_ONLY,
            "verification": "not_officially_verified",
            "ref": "local:rules/demo.py",
            "digest": implementation_digest,
        },
        "rule_evidence": {"matched_rule": "breakout"},
        "data_quality": {"status": "complete"},
        "missing_reasons": [],
        "decision_at": NOW,
        "as_of_at": "2025-12-31T23:00:00+00:00",
        "confidence": None,
        "confidence_semantics": {
            "version": SIGNAL_CONFIDENCE_SEMANTICS_VERSION,
            "kind": "not_calibrated",
            "is_calibrated": False,
            "is_probability": False,
            "display_label_zh": "未校準；非預測勝率",
        },
        "earliest_execution_at": None,
        "earliest_execution_reason": EARLIEST_EXECUTION_UNAVAILABLE_REASON,
        "revision": 1,
        "supersedes_artifact_key": None,
        "source_mode": CALLER_PROVIDED_ONLY,
        "implementation_mode": CALLER_PROVIDED_ONLY,
        "lifecycle_state": "active",
        "generated_at": NOW,
    }
    result.update(changes)
    if "ruleset_snapshot" in changes and "ruleset_digest" not in changes:
        result.pop("ruleset_digest", None)
    if "basis_manifest" in changes and "basis_digest" not in changes:
        result.pop("basis_digest", None)
    if "dependency_manifest" in changes and "dependency_digest" not in changes:
        result.pop("dependency_digest", None)
    return result


def test_valid_contract_recomputes_embedded_digests_and_forces_null_execution() -> None:
    normalized = normalize_signal_artifact(_artifact())
    assert normalized["signal_output_semantics"] == {
        "version": SIGNAL_CONFIDENCE_SEMANTICS_VERSION,
        "kind": "rule_only",
        "is_calibrated": False,
        "is_probability": False,
    }
    assert normalized["confidence"] is None
    assert normalized["earliest_execution_at"] is None
    assert normalized["ruleset_digest"] == digest_json(normalized["ruleset_snapshot"])
    assert normalized["basis_digest"] == digest_json(normalized["basis_manifest"])
    assert normalized["dependency_digest"] == digest_json(normalized["dependency_manifest"])
    assert canonical_json(normalized)


@pytest.mark.parametrize(
    "field,value",
    [
        ("confidence_semantics", {"version": SIGNAL_CONFIDENCE_SEMANTICS_VERSION, "kind": "not_calibrated", "is_calibrated": 0, "is_probability": False, "display_label_zh": "未校準；非預測勝率"}),
        ("confidence_semantics", {"version": SIGNAL_CONFIDENCE_SEMANTICS_VERSION, "kind": "probability", "is_calibrated": False, "is_probability": False, "display_label_zh": "99%"}),
        ("signal_output_semantics", {"version": "signal-probability/v1", "kind": "probability", "is_calibrated": True, "is_probability": True}),
        ("ruleset_snapshot", 42),
        ("basis_manifest", None),
        ("dependency_manifest", 7),
        ("earliest_execution_at", NOW),
        ("earliest_execution_reason", "anything"),
    ],
)
def test_contract_rejects_probability_scalar_or_execution_shortcuts(field: str, value: Any) -> None:
    with pytest.raises((SignalArtifactContractError, TypeError, ValueError)):
        normalize_signal_artifact(_artifact(**{field: value}))


def test_contract_rejects_bad_digest_nan_naive_time_and_unknown_field() -> None:
    with pytest.raises(SignalArtifactContractError):
        normalize_signal_artifact(_artifact(contract="signal-artifact/v99"))
    with pytest.raises(SignalArtifactContractError):
        normalize_signal_artifact(_artifact(implementation_digest="sha256:not-hex"))
    with pytest.raises(SignalArtifactContractError):
        normalize_signal_artifact(_artifact(rule_state={"score": math.nan}))
    with pytest.raises(SignalArtifactContractError):
        normalize_signal_artifact(_artifact(decision_at="2026-01-01T01:00:00"))
    with pytest.raises(SignalArtifactContractError):
        normalize_signal_artifact(_artifact(unexpected_field=True))


def test_alias_conflicts_are_not_silently_preferred() -> None:
    with pytest.raises(SignalArtifactContractError):
        normalize_signal_artifact(
            _artifact(
                strategy_name="other_rule",
                strategy_version="1.0.0",
            )
        )
    with pytest.raises(SignalArtifactContractError):
        normalize_signal_artifact(
            _artifact(
                input_snapshot_id="other-snapshot",
            )
        )
    with pytest.raises(SignalArtifactContractError):
        normalize_signal_artifact(
            _artifact(signal_output_semantics_version="signal-output/rule-only/v1")
        )


def test_strict_manifest_shapes_require_explicit_unknown_reasons() -> None:
    unknown_basis = {
        "mode": CALLER_PROVIDED_ONLY,
        "verification": "not_officially_verified",
        "status": "unknown",
        "value": None,
        "reason": "fixture has no verified basis",
    }
    unknown_dependency = {
        "mode": CALLER_PROVIDED_ONLY,
        "verification": "not_officially_verified",
        "references": [],
        "unknown_reasons": ["source availability not supplied"],
    }
    normalized = normalize_signal_artifact(
        _artifact(basis_manifest=unknown_basis, dependency_manifest=unknown_dependency)
    )
    assert normalized["basis_manifest"]["status"] == "unknown"
    assert normalized["dependency_manifest"]["unknown_reasons"]
    with pytest.raises(SignalArtifactContractError):
        normalize_signal_artifact(
            _artifact(
                basis_manifest={
                    "mode": CALLER_PROVIDED_ONLY,
                    "verification": "not_officially_verified",
                    "status": "unknown",
                    "value": "pretend",
                    "reason": None,
                }
            )
        )
