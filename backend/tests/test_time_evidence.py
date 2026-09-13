"""Contract tests for the local time-evidence/v1 value object."""

from __future__ import annotations

import copy
import json
from datetime import datetime

import pytest

from app.time_evidence import (
    TIME_EVIDENCE_VERSION,
    TimeEvidence,
    TimeEvidenceContractError,
    legacy_safe,
    normalize_timestamp,
)


def _point(
    value: str | None,
    *,
    precision: str = "instant",
    status: str = "known",
    reason: str | None = None,
    role: str | None = None,
) -> dict:
    result = {
        "status": status,
        "precision": precision,
        "value": value,
        "source": "fixture-source",
        "evidence": {"kind": "raw", "id": "fixture-001"},
        "ref": "fixture://time-001",
    }
    if reason is not None:
        result["reason"] = reason
    if role is not None:
        result["role"] = role
    return result


def _root_record(**changes) -> dict:
    record = {
        "version": TIME_EVIDENCE_VERSION,
        "subject_identity": {"exchange": "TWSE", "symbol": "2330"},
        "source_identity": {"id": "fixture-source", "kind": "local"},
        "snapshot_identity": {"id": "snapshot-1", "hash": "abc"},
        "revision_identity": {"id": "revision-1", "kind": "root"},
        "market_date": {
            "status": "known",
            "precision": "date",
            "value": "2026-03-09",
            "source": "fixture-source",
            "evidence": "calendar-row",
            "ref": "fixture://market-date",
        },
        "published_at": _point("2026-03-09T00:00:00+08:00"),
        "first_available_at": _point("2026-03-09T08:00:00+08:00"),
        "collected_at": _point("2026-03-09T16:00:00+08:00"),
        "revision_available_at": _point(
            None,
            precision="none",
            status="not_applicable",
            reason="root_revision_has_no_predecessor",
        ),
        "decision_at": _point("2026-03-09T17:00:00+08:00"),
        "generated_at": _point("2026-03-09T17:01:00+08:00"),
        "earliest_execution_at": _point("2026-03-10T09:00:00+08:00"),
    }
    record.update(changes)
    return record


def test_aware_offsets_have_one_canonical_instant_and_dst_sorting() -> None:
    left = normalize_timestamp("2026-03-09T17:00:00+08:00")
    right = normalize_timestamp("2026-03-09T09:00:00Z")
    assert left == right == "2026-03-09T09:00:00+00:00"
    assert normalize_timestamp("2026-11-01T01:30:00-04:00") < normalize_timestamp("2026-11-01T06:30:01Z")

    first = TimeEvidence.from_mapping(_root_record())
    second_input = _root_record()
    for role in ("published_at", "first_available_at", "collected_at", "decision_at", "generated_at", "earliest_execution_at"):
        value = second_input[role]["value"]
        second_input[role]["value"] = normalize_timestamp(value)
    second = TimeEvidence.from_mapping(second_input)
    assert first.canonical_payload() == second.canonical_payload()
    assert first.to_dict()["decision_at"]["utc"] == "2026-03-09T09:00:00+00:00"


def test_date_only_is_not_promoted_to_midnight() -> None:
    evidence = TimeEvidence.from_mapping(_root_record())
    market_date = evidence.to_dict()["market_date"]
    assert market_date["precision"] == "date"
    assert market_date["value"] == "2026-03-09"
    assert "utc" not in market_date
    with pytest.raises(TimeEvidenceContractError):
        normalize_timestamp("2026-03-09")
    with pytest.raises(TimeEvidenceContractError):
        TimeEvidence.from_mapping(_root_record(decision_at=_point("2026-03-09T09:00:00")))


def test_unknown_and_not_applicable_require_explicit_reason_and_none_precision() -> None:
    record = _root_record(
        published_at=_point(None, precision="none", status="unknown", reason="source_did_not_publish_time"),
        first_available_at=_point(None, precision="none", status="unknown", reason="not_recorded"),
        collected_at=_point(None, precision="none", status="unknown", reason="not_collected"),
    )
    evidence = TimeEvidence.from_mapping(record)
    assert evidence.to_dict()["published_at"]["precision"] == "none"
    assert evidence.to_dict()["published_at"]["value"] is None
    assert evidence.to_dict()["revision_available_at"]["status"] == "not_applicable"

    with pytest.raises(TimeEvidenceContractError):
        TimeEvidence.from_mapping(_root_record(published_at=_point(None, precision="none", status="unknown")))
    with pytest.raises(TimeEvidenceContractError):
        TimeEvidence.from_mapping(_root_record(revision_available_at=_point(None, precision="none", status="unknown", reason="no_parent")))
    with pytest.raises(TimeEvidenceContractError):
        TimeEvidence.from_mapping(_root_record(revision_available_at=_point("2026-03-09T08:00:00+00:00")))

    revision_with_unknown_timing = _root_record(
        revision_identity={"id": "revision-2", "kind": "revision", "supersedes": "revision-1"},
        revision_available_at=_point(
            None,
            precision="none",
            status="unknown",
            reason="source_revision_time_not_observed",
        ),
    )
    assert TimeEvidence.from_mapping(revision_with_unknown_timing).to_dict()["revision_available_at"]["status"] == "unknown"
    with pytest.raises(TimeEvidenceContractError):
        TimeEvidence.from_mapping(
            {
                **revision_with_unknown_timing,
                "revision_available_at": _point(
                    None,
                    precision="none",
                    status="not_applicable",
                    reason="incorrectly_not_applicable",
                ),
            }
        )


def test_strict_input_requires_all_roles_provenance_and_nonconflicting_aliases() -> None:
    with pytest.raises(TimeEvidenceContractError):
        TimeEvidence.from_mapping({key: value for key, value in _root_record().items() if key != "generated_at"})
    with pytest.raises(TimeEvidenceContractError):
        TimeEvidence.from_mapping(_root_record(decision_at={**_point("2026-03-09T09:00:00+00:00"), "source": {}}))
    with pytest.raises(TimeEvidenceContractError):
        TimeEvidence.from_mapping(_root_record(decision_at={**_point("2026-03-09T09:00:00+00:00"), "source": None}))
    with pytest.raises(TimeEvidenceContractError):
        TimeEvidence.from_mapping(_root_record(decision_at={**_point("2026-03-09T09:00:00+00:00"), "source": False}))
    with pytest.raises(TimeEvidenceContractError):
        TimeEvidence.from_mapping(_root_record(decision_at={**_point("2026-03-09T09:00:00+00:00"), "source": ["source"]}))
    with pytest.raises(TimeEvidenceContractError):
        TimeEvidence.from_mapping(_root_record(decision_at={**_point("2026-03-09T09:00:00+00:00"), "evidence": []}))
    with pytest.raises(TimeEvidenceContractError):
        TimeEvidence.from_mapping(_root_record(decision_at={**_point("2026-03-09T09:00:00+00:00"), "evidence": None}))
    with pytest.raises(TimeEvidenceContractError):
        TimeEvidence.from_mapping(_root_record(decision_at={**_point("2026-03-09T09:00:00+00:00"), "ref": "   "}))
    with pytest.raises(TimeEvidenceContractError):
        TimeEvidence.from_mapping(_root_record(decision_at={**_point("2026-03-09T09:00:00+00:00"), "precision": "none"}))
    with pytest.raises(TimeEvidenceContractError):
        TimeEvidence.from_mapping(_root_record(decision_at={**_point("2026-03-09T09:00:00+00:00"), "role": "published_at"}))
    with pytest.raises(TimeEvidenceContractError):
        TimeEvidence.from_mapping(_root_record(decision_at={**_point("2026-03-09T09:00:00+00:00"), "value": "2026-03-09T09:00:00+00:00", "utc": "2026-03-09T10:00:00+00:00"}))
    with pytest.raises(TimeEvidenceContractError):
        TimeEvidence.from_mapping(_root_record(decision_at={**_point("2026-03-09T09:00:00+00:00"), "source_id": "other"}))
    with pytest.raises(TimeEvidenceContractError):
        TimeEvidence.from_mapping(_root_record(revision_id="other"))


def test_legacy_projection_is_safe_and_does_not_mutate_or_infer_availability() -> None:
    legacy = {
        "signal_date": "2026-03-09",
        "data_cutoff": "2026-03-09 13:30",
        "earliest_execution_date": "2026-03-10",
        "created_at": datetime(2026, 3, 9, 13, 30),
        "nested": {"naive": datetime(2026, 3, 9, 13, 30)},
    }
    before = copy.deepcopy(legacy)
    projected = legacy_safe(legacy)
    json.dumps(projected)
    assert legacy == before
    assert projected["legacy"]["created_at"] == "2026-03-09T13:30:00"
    assert projected["market_date"]["precision"] == "date"
    assert projected["first_available_at"]["status"] == "unknown"
    assert projected["decision_at"]["status"] == "unknown"
    assert projected["earliest_execution_at"]["reason"] == "legacy_earliest_execution_date_is_date_only"
    assert projected["legacy_semantics"]["availability_asserted"] is False
