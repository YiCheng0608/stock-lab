from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pytest

from app.artifact_provenance import (
    PROVENANCE_CONTRACT_ID,
    ProvenanceContractError,
    normalize_atr_provenance,
)
from app.artifact_store import ArtifactStore
from strict_artifact_fixture import INSTRUMENT, MARKET_DATE, make_artifact, make_provenance


def test_strict_provenance_round_trip_and_normalization_are_stable(tmp_path) -> None:
    artifact = make_artifact()
    provenance = make_provenance(artifact)
    normalized = normalize_atr_provenance(
        provenance,
        artifact=artifact,
        instrument=INSTRUMENT,
        market_date=MARKET_DATE,
    )
    assert normalize_atr_provenance(
        normalized,
        artifact=artifact,
        instrument=INSTRUMENT,
        market_date=MARKET_DATE,
    ) == normalized

    with ArtifactStore(tmp_path / "strict.sqlite") as store:
        saved = store.save_atr_artifact_strict(
            INSTRUMENT,
            MARKET_DATE,
            artifact,
            provenance=provenance,
            attempt_id="strict-1",
        )
        assert saved.dependency_manifest["contract"]["id"] == PROVENANCE_CONTRACT_ID
        assert saved.instrument_evidence["validation_status"] == "caller_supplied_only"
        assert saved.source_evidence["ordered_source_rows"][0]["sequence_position"] == 0
        assert saved.source_evidence["ordered_source_rows"][-1]["market_date"] == MARKET_DATE.isoformat()
        assert store.get_strict_by_key(saved.artifact_key).artifact.to_dict() == artifact.to_dict()


def test_strict_precommit_validation_rolls_back_all_rows_and_attempt(monkeypatch, tmp_path) -> None:
    artifact = make_artifact()
    provenance = make_provenance(artifact)
    with ArtifactStore(tmp_path / "precommit.sqlite") as store:
        def reject_before_commit(_artifact_key: str) -> None:
            raise ProvenanceContractError("forced strict pre-commit validation failure")

        monkeypatch.setattr(store, "get_strict_by_key", reject_before_commit)
        with pytest.raises(ProvenanceContractError, match="pre-commit"):
            store.save_atr_artifact_strict(
                INSTRUMENT,
                MARKET_DATE,
                artifact,
                provenance=provenance,
                attempt_id="precommit-failure",
                run_id="run-precommit-failure",
            )
        for table in (
            "feature_artifacts",
            "artifact_observations",
            "artifact_dependencies",
            "artifact_attempts",
        ):
            assert store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_old_minimal_schema1_row_is_not_promoted_to_strict(tmp_path) -> None:
    from test_artifact_store import _calculate, _save

    with ArtifactStore(tmp_path / "minimal.sqlite") as store:
        saved = _save(store, _calculate())
        with pytest.raises(ProvenanceContractError):
            store.get_strict_by_key(saved.artifact_key)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.pop("source"),
        lambda value: value["source"]["ordered_source_rows"][0].pop("availability"),
        lambda value: value["algorithm"].update({"config_digest": "wrong"}),
        lambda value: value["basis"].update({"digest": "wrong"}),
        lambda value: value["company_actions"].update({"coverage_proof": "wrong"}),
    ],
)
def test_strict_structure_is_rejected_before_any_parent_row(tmp_path, mutate) -> None:
    artifact = make_artifact()
    provenance = make_provenance(artifact)
    mutate(provenance)
    with ArtifactStore(tmp_path / "reject.sqlite") as store:
        with pytest.raises((ValueError, TypeError)):
            store.save_atr_artifact_strict(
                INSTRUMENT,
                MARKET_DATE,
                artifact,
                provenance=provenance,
                attempt_id="rejected",
            )
        assert store.connection.execute("SELECT COUNT(*) FROM feature_artifacts").fetchone()[0] == 0


def test_unknown_required_availability_cannot_wrap_non_null_atr(tmp_path) -> None:
    artifact = make_artifact()
    provenance = make_provenance(artifact)
    provenance["source"]["availability"] = {
        "status": "unknown",
        "reason": "fixture_source_availability_not_supplied",
    }
    with ArtifactStore(tmp_path / "unknown.sqlite") as store:
        with pytest.raises(ProvenanceContractError):
            store.save_atr_artifact_strict(
                INSTRUMENT,
                MARKET_DATE,
                artifact,
                provenance=provenance,
                attempt_id="unknown",
            )
        assert store.connection.execute("SELECT COUNT(*) FROM feature_artifacts").fetchone()[0] == 0


def test_unknown_required_availability_can_preserve_all_null_fail_closed_outputs(tmp_path) -> None:
    artifact = make_artifact()
    null_observations = tuple(
        replace(item, true_range=None, atr=None, null_reason="source_availability_unknown")
        for item in artifact.observations
    )
    artifact = replace(artifact, observations=null_observations)
    provenance = make_provenance(artifact)
    provenance["source"]["availability"] = {
        "status": "unknown",
        "reason": "fixture_source_availability_not_supplied",
    }
    with ArtifactStore(tmp_path / "null.sqlite") as store:
        saved = store.save_atr_artifact_strict(
            INSTRUMENT,
            MARKET_DATE,
            artifact,
            provenance=provenance,
            attempt_id="null",
        )
        assert all(item.atr is None for item in saved.observations)


def test_external_snapshot_hash_and_algorithm_have_explicit_legal_shape(tmp_path) -> None:
    artifact = make_artifact()
    provenance = make_provenance(artifact)
    provenance["source"]["snapshot"]["hash"] = "not-a-sha256"
    with ArtifactStore(tmp_path / "bad-hash.sqlite") as store:
        with pytest.raises(ProvenanceContractError):
            store.save_atr_artifact_strict(INSTRUMENT, MARKET_DATE, artifact, provenance=provenance)

    provenance = make_provenance(artifact)
    provenance["source"]["snapshot"]["hash_algorithm"] = "not-a-real-hash"
    with ArtifactStore(tmp_path / "bad-algorithm.sqlite") as store:
        with pytest.raises(ProvenanceContractError):
            store.save_atr_artifact_strict(INSTRUMENT, MARKET_DATE, artifact, provenance=provenance)


def test_unknown_row_and_halt_status_cannot_wrap_active_atr(tmp_path) -> None:
    artifact = make_artifact()
    provenance = make_provenance(artifact)
    provenance["source"]["ordered_source_rows"][0]["availability"] = {
        "status": "unknown",
        "reason": "row_availability_not_supplied",
    }
    with ArtifactStore(tmp_path / "unknown-row.sqlite") as store:
        with pytest.raises(ProvenanceContractError):
            store.save_atr_artifact_strict(INSTRUMENT, MARKET_DATE, artifact, provenance=provenance)


def test_company_action_manifest_is_cross_checked_against_artifact_action(tmp_path) -> None:
    source_artifact = make_artifact()
    action = {
        "action_ref": "fixture://actions/1",
        "digest": hashlib.sha256(b"action-row-1").hexdigest(),
        "digest_algorithm": "sha256",
        "instrument": {"exchange": "TWSE", "symbol": "2330"},
        "action_date": "2026-01-05",
        "ex_date": "2026-01-06",
        "action_type": "split",
        "source_ref": "fixture://actions/1",
        "parameters": {"ratio": 2},
        "from_basis": "raw_v1",
        "to_basis": "raw_v1",
        "applicable_scope": {
            "start_date": "2026-01-02",
            "end_date": "2026-01-17",
            "terminal_market_date": "2026-01-17",
        },
        "availability": {
            "status": "available",
            "available_at": "2026-01-01T00:00:00+00:00",
        },
    }
    manifest_digest = hashlib.sha256(
        json.dumps([action], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    provenance = make_provenance(source_artifact)
    provenance["company_actions"] = {
        "manifest": [action],
        "digest": manifest_digest,
        "coverage": "complete",
        "missing_or_unknown": [],
        "coverage_window": provenance["source"]["coverage_window"],
        "source": provenance["company_actions"]["source"],
        "availability": provenance["company_actions"]["availability"],
    }
    artifact = replace(
        source_artifact,
        corporate_actions=(
            {
                "source_ref": "fixture://actions/1",
                "action_type": "split",
                "price_basis": "raw_v1",
                "action_date": "2026-01-05",
                "ex_date": "2026-01-06",
                "coverage": "complete",
                "available_at": "2026-01-01T00:00:00+00:00",
            },
        ),
    )
    with ArtifactStore(tmp_path / "action.sqlite") as store:
        saved = store.save_atr_artifact_strict(
            INSTRUMENT, MARKET_DATE, artifact, provenance=provenance
        )
        assert saved.dependency_manifest["company_actions"]["manifest"][0]["source_ref"] == "fixture://actions/1"


def test_multiple_selected_previous_close_rows_round_trip_and_duplicate_current_fails(tmp_path) -> None:
    artifact = make_artifact()
    provenance = make_provenance(artifact)
    previous_snapshot = {
        "id": "previous-close-snapshot-1",
        "hash": hashlib.sha256(b"previous-close-snapshot-1").hexdigest(),
        "hash_algorithm": "sha256",
        "source_ref": "fixture://previous-close",
    }
    selected = []
    for index, current_date in enumerate(("2026-01-02", "2026-01-03")):
        if index == 0:
            predecessor = {
                "row_ref": "fixture://previous-close/preceding/0",
                "market_date": "2026-01-01",
                "snapshot_id": previous_snapshot["id"],
                "snapshot_hash": previous_snapshot["hash"],
                "price_basis": "raw_v1",
            }
        else:
            predecessor = {
                "row_ref": "fixture://bars/1",
                "market_date": "2026-01-02",
                "snapshot_id": "bars-snapshot-1",
                "snapshot_hash": provenance["source"]["snapshot"]["hash"],
                "price_basis": "raw_v1",
            }
        selected.append(
            {
                "selection_status": "used",
                "value": 100 + index,
                "basis": "raw_v1",
                "row_ref": f"fixture://previous-close/selected/{index}",
                "source_ref": "fixture://previous-close",
                "snapshot": previous_snapshot,
                "availability": {
                    "status": "available",
                    "available_at": "2026-01-01T00:00:00+00:00",
                },
                "predecessor": predecessor,
                "current": {
                    "row_ref": f"fixture://bars/{index + 1}",
                    "market_date": current_date,
                    "snapshot_id": "bars-snapshot-1",
                    "snapshot_hash": provenance["source"]["snapshot"]["hash"],
                    "price_basis": "raw_v1",
                },
            }
        )
    provenance["previous_close"] = {
        "selection_status": "used",
        "candidates": [],
        "selected": selected,
    }
    with ArtifactStore(tmp_path / "previous-close.sqlite") as store:
        saved = store.save_atr_artifact_strict(INSTRUMENT, MARKET_DATE, artifact, provenance=provenance)
        assert len(saved.dependency_manifest["previous_close"]["selected"]) == 2

    wrong_current = make_provenance(artifact)
    wrong_selected = deepcopy(selected)
    wrong_selected[0]["current"]["row_ref"] = "fixture://bars/not-present"
    wrong_current["previous_close"] = {
        "selection_status": "used",
        "candidates": [],
        "selected": wrong_selected,
    }
    with ArtifactStore(tmp_path / "previous-close-wrong-current.sqlite") as store:
        with pytest.raises(ProvenanceContractError, match="ordered source row"):
            store.save_atr_artifact_strict(
                INSTRUMENT,
                MARKET_DATE,
                artifact,
                provenance=wrong_current,
            )

    duplicate = make_provenance(artifact)
    duplicate["previous_close"] = {
        "selection_status": "used",
        "candidates": [],
        "selected": [selected[0], selected[0]],
    }
    with ArtifactStore(tmp_path / "previous-close-duplicate.sqlite") as store:
        with pytest.raises(ProvenanceContractError):
            store.save_atr_artifact_strict(INSTRUMENT, MARKET_DATE, artifact, provenance=duplicate)


def test_strict_read_rejects_ordinary_writer_projection_mismatch(tmp_path) -> None:
    artifact = make_artifact()
    provenance = make_provenance(artifact)
    normalized = normalize_atr_provenance(
        provenance,
        artifact=artifact,
        instrument=INSTRUMENT,
        market_date=MARKET_DATE,
    )
    with ArtifactStore(tmp_path / "spoof.sqlite") as store:
        saved = store.save_atr_artifact(
            INSTRUMENT,
            MARKET_DATE,
            artifact,
            snapshot_hash=normalized["source"]["snapshot_hash"],
            implementation_digest=normalized["algorithm"]["implementation"]["digest"],
            dependency_manifest=normalized,
            instrument_evidence=normalized["instrument"],
            source_evidence={
                "source_ref": "fixture://wrong-source",
                "snapshot_id": "wrong-source-snapshot",
                "snapshot_hash": hashlib.sha256(b"wrong-source").hexdigest(),
            },
            calendar_evidence=normalized["calendar"],
            halt_evidence=normalized["halts"],
            previous_close_evidence=normalized["previous_close"],
            calculation_config=normalized["algorithm"]["config"],
        )
        assert store.get_by_key(saved.artifact_key) is not None
        with pytest.raises(ProvenanceContractError):
            store.get_strict_by_key(saved.artifact_key)

    provenance = make_provenance(artifact)
    provenance["halts"]["session_statuses"][0]["status"] = "halted"
    with ArtifactStore(tmp_path / "halt-mismatch.sqlite") as store:
        with pytest.raises(ProvenanceContractError):
            store.save_atr_artifact_strict(INSTRUMENT, MARKET_DATE, artifact, provenance=provenance)
