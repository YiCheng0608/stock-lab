"""Exact capture-to-candidate checks on a small, isolated synthetic research DB."""

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.migrations import upgrade_database
from app.models import IngestionRun, Instrument, MarketBar
from app.rule_replay import RuleReplayBindingError
from app.signal_artifact import normalize_signal_artifact
from app.signal_artifact_store import (
    ReadonlySnapshotError, SignalArtifactCollisionError, SignalArtifactStore,
)
from worker import analysis_capture as capture
from worker import signal_artifact_bridge as bridge


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def research(tmp_path):
    source = tmp_path / "synthetic-source.db"
    engine = create_engine("sqlite:///" + source.as_posix())
    upgrade_database(engine)
    with Session(engine) as db:
        instrument = Instrument(symbol="TEST", name="Synthetic", exchange="TWSE")
        db.add(instrument)
        db.flush()
        for index in range(65):
            day = date(2026, 5, 1) + timedelta(days=index)
            price = 90 + index * 0.1
            db.add(MarketBar(
                instrument_id=instrument.id, trading_date=day,
                open=price, high=price + 1, low=price - 1,
                close=price, adj_close=price, volume=100 + index, turnover=10000,
            ))
        db.add(IngestionRun(
            run_type="collect", source="official", run_date=day,
            data_as_of=day.isoformat(), status="success",
        ))
        db.commit()
    engine.dispose()
    target = tmp_path / "research.db"
    owner = capture.create_research_database(
        source_snapshot_path=source, expected_source_sha256=_sha(source),
        research_database_path=target,
    )
    result = capture.execute_analysis_attempt(research_database_path=target, attempt_id="capture-one")
    assert result["outcome"] == "committed_verified"
    assert len(result["captures"]) == 4
    return source, target, owner, result


def _decision(result):
    times = [datetime.fromisoformat(result["receipt"]["captured_at"])]
    times.extend(datetime.fromisoformat(call["captured_at"]) for call in result["captures"])
    return max(times) + timedelta(seconds=1)


def _selected(result):
    return [
        call["ordinal"] for call in result["captures"]
        if call["evaluator"] == call["selected_strategy"]["name"]
    ]


def _candidate(target, result, ordinal, **changes):
    kwargs = {
        "research_snapshot_path": target,
        "expected_snapshot_sha256": _sha(target),
        "attempt_id": "capture-one",
        "ordinal": ordinal,
        "decision_at": _decision(result),
    }
    kwargs.update(changes)
    return bridge.build_signal_artifact_candidate(**kwargs)


def _reseal(target, change, change_receipt=None):
    """Change selected synthetic rows while retaining valid capture seals/schema."""
    with sqlite3.connect(target) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT * FROM worker_capture_calls ORDER BY ordinal").fetchall()
        receipt = json.loads(db.execute("SELECT payload FROM worker_capture_attempts").fetchone()[0])
        for table in ("worker_capture_calls", "worker_capture_attempts"):
            db.execute("DROP TRIGGER " + table + "_no_update")
        for row in rows:
            payload = json.loads(row["payload"])
            if change(payload):
                digest = capture._seal(payload)
                receipt["call_digests"][row["ordinal"]] = digest
                db.execute(
                    "UPDATE worker_capture_calls SET payload=?,digest=? WHERE ordinal=?",
                    (capture._canonical(payload), digest, row["ordinal"]),
                )
        if change_receipt is not None:
            change_receipt(receipt)
        db.execute(
            "UPDATE worker_capture_attempts SET payload=?,digest=?",
            (capture._canonical(receipt), capture._seal(receipt)),
        )
        for table in ("worker_capture_calls", "worker_capture_attempts"):
            db.execute(capture.SCHEMA[table + "_no_update"])


def test_selected_candidates_are_input_only_opaque_detached_and_readonly(research):
    source, target, owner, result = research
    before = _sha(target)
    files_before = sorted(path.name for path in target.parent.iterdir())
    ordinals = _selected(result)
    assert len(ordinals) == 2
    assert {result["captures"][n]["evaluator"] for n in ordinals} == {"breakout_v1", "pullback_v1"}
    for ordinal in ordinals:
        call = result["captures"][ordinal]
        candidate = _candidate(target, result, ordinal)
        assert candidate == normalize_signal_artifact(candidate, include_generated=True)
        assert candidate["status"] == call["signal_snapshot"]["status"]
        assert candidate["rule_state"] == call["actual_result"]
        assert candidate["confidence"] is None and candidate["as_of_at"] is None
        assert candidate["earliest_execution_at"] is None
        assert candidate["feature_artifact_refs"] == []
        assert candidate["basis_manifest"]["status"] == "unknown"
        assert candidate["input_snapshot"]["id"].endswith(f"/capture-one/{ordinal}")
        evidence = candidate["rule_evidence"]["capture_bridge"]
        manifest = json.loads(evidence["input_manifest_json"])
        assert candidate["input_snapshot"]["hash"] == evidence["input_manifest_digest"]
        assert candidate["input_snapshot"]["hash"] == "sha256:" + hashlib.sha256(
            evidence["input_manifest_json"].encode("utf-8")
        ).hexdigest()
        assert manifest["arguments"] == call["arguments"]
        assert manifest["config_snapshot"] == call["selected_strategy"]["config"]
        assert manifest["evaluator_binding"]["implementation"] == call["bundle"]["implementation"]
        assert not {"status", "result", "captured_at", "receipt", "research_snapshot_sha256"} & set(manifest)
        assert manifest["upstream_refs"]["original_source_container_sha256"] == owner["source_snapshot"]["sha256"]
        assert evidence["research_snapshot_sha256"] == "sha256:" + before
        assert evidence["research_snapshot_sha256"] != evidence["original_source_container_sha256"]
        with sqlite3.connect(target) as db:
            call_text, call_digest = db.execute(
                "SELECT payload,digest FROM worker_capture_calls WHERE attempt_id=? AND ordinal=?",
                ("capture-one", ordinal),
            ).fetchone()
            receipt_text = db.execute(
                "SELECT payload FROM worker_capture_attempts WHERE attempt_id=?", ("capture-one",),
            ).fetchone()[0]
        assert evidence["call_json"] == call_text
        assert evidence["call_digest"] == "sha256:" + call_digest
        assert evidence["receipt_json"] == receipt_text
        assert evidence["receipt_derived_seal"] == "sha256:" + hashlib.sha256(
            receipt_text.encode("utf-8")
        ).hexdigest()
        candidate["rule_state"]["reasons"].append("caller mutation")
        assert _candidate(target, result, ordinal)["rule_state"] == call["actual_result"]
    assert _sha(source) == owner["source_snapshot"]["sha256"]
    assert _sha(target) == before
    assert sorted(path.name for path in target.parent.iterdir()) == files_before


def test_required_hash_exact_attempt_ordinal_and_time_fail_closed(research):
    _, target, _, result = research
    selected = _selected(result)[0]
    base = dict(research_snapshot_path=target, expected_snapshot_sha256=_sha(target),
                attempt_id="capture-one", ordinal=selected, decision_at=_decision(result))
    for value in (None, "", 123, "a" * 63, "z" * 64):
        with pytest.raises(bridge.SignalArtifactBridgeError, match="expected_snapshot_sha256_required"):
            bridge.build_signal_artifact_candidate(**{**base, "expected_snapshot_sha256": value})
    for value in (True, -1, 1.0, len(result["captures"])):
        with pytest.raises(bridge.SignalArtifactBridgeError, match="invalid_ordinal|ordinal_not_found"):
            bridge.build_signal_artifact_candidate(**{**base, "ordinal": value})
    for value in (None, "2026-05-01", "2026-05-01T12:00:00", datetime(2026, 5, 1)):
        with pytest.raises(bridge.SignalArtifactBridgeError, match="invalid_decision_at"):
            bridge.build_signal_artifact_candidate(**{**base, "decision_at": value})
    for value in (result["receipt"]["captured_at"], result["captures"][selected]["captured_at"]):
        early = datetime.fromisoformat(value) - timedelta(microseconds=1)
        with pytest.raises(bridge.SignalArtifactBridgeError, match="decision_before_capture"):
            bridge.build_signal_artifact_candidate(**{**base, "decision_at": early})
    with pytest.raises(ReadonlySnapshotError, match="snapshot_hash_mismatch"):
        bridge.build_signal_artifact_candidate(**{**base, "expected_snapshot_sha256": "0" * 64})
    with pytest.raises(capture.AnalysisCaptureError, match="attempt_not_found"):
        bridge.build_signal_artifact_candidate(**{**base, "attempt_id": "missing"})
    unselected = next(call["ordinal"] for call in result["captures"]
                      if call["evaluator"] != call["selected_strategy"]["name"])
    with pytest.raises(bridge.SignalArtifactBridgeError, match="evaluator_not_selected_strategy"):
        bridge.build_signal_artifact_candidate(**{**base, "ordinal": unselected})


def test_snapshot_sidecar_and_nonselected_corruption_fail_closed(research):
    _, target, _, result = research
    selected = _selected(result)[0]
    sidecar = Path(str(target) + "-wal")
    sidecar.write_bytes(b"")
    try:
        with pytest.raises(ReadonlySnapshotError, match="snapshot_sidecar_present"):
            _candidate(target, result, selected)
    finally:
        sidecar.unlink()
    unselected = next(call["ordinal"] for call in result["captures"]
                      if call["evaluator"] != call["selected_strategy"]["name"])
    with sqlite3.connect(target) as db:
        db.execute("DROP TRIGGER worker_capture_calls_no_update")
        db.execute("UPDATE worker_capture_calls SET digest=? WHERE ordinal=?", ("0" * 64, unselected))
        db.execute(capture.SCHEMA["worker_capture_calls_no_update"])
    with pytest.raises(capture.AnalysisCaptureError, match="invalid_sealed_payload"):
        _candidate(target, result, selected)


def test_subject_normalization_and_binding_fail_closed(research):
    _, target, _, result = research
    selected = _selected(result)[0]

    def lower_exchange(payload):
        payload["subject"]["exchange"] = "twse"
        payload["signal_snapshot"]["signal_key"] = payload["signal_snapshot"]["signal_key"].replace("TWSE", "twse")
        return True

    _reseal(target, lower_exchange)
    assert capture.read_analysis_attempt(research_database_path=target, attempt_id="capture-one")["outcome"] == "committed_verified"
    with pytest.raises(bridge.SignalArtifactBridgeError, match="subject_normalization_required"):
        _candidate(target, result, selected)


def test_bad_pinned_runtime_rejected_even_in_unselected_row(research):
    _, target, _, result = research
    selected = _selected(result)[0]
    unselected = next(call["ordinal"] for call in result["captures"]
                      if call["evaluator"] != call["selected_strategy"]["name"])

    def bad_binding(payload):
        if payload["ordinal"] != unselected:
            return False
        payload["bundle"]["implementation"]["runtime"]["version"] = "unbound"
        return True

    _reseal(target, bad_binding)
    with pytest.raises(RuleReplayBindingError, match="unsupported_implementation_binding"):
        _candidate(target, result, selected)


def test_input_hash_ignores_observation_status_time_and_current_container(research):
    _, target, _, result = research
    selected = _selected(result)[0]
    first = _candidate(target, result, selected)
    original_snapshot_sha = _sha(target)
    signal_id = result["captures"][selected]["signal_snapshot"]["id"]

    def observation_only(payload):
        if payload["signal_snapshot"]["id"] != signal_id:
            return False
        payload["signal_snapshot"]["status"] = "observed_changed_status"
        payload["captured_at"] = (
            datetime.fromisoformat(payload["captured_at"]) + timedelta(milliseconds=100)
        ).isoformat()
        return True

    def receipt_time_only(receipt):
        receipt["captured_at"] = (
            datetime.fromisoformat(receipt["captured_at"]) + timedelta(milliseconds=200)
        ).isoformat()

    _reseal(target, observation_only, receipt_time_only)
    # A mutable unrelated legacy row changes the container bytes, not the
    # exact captured input manifest or its verified sealed call relation.
    with sqlite3.connect(target) as db:
        db.execute("UPDATE instruments SET name='Renamed synthetic row' WHERE symbol='TEST'")
    assert _sha(target) != original_snapshot_sha
    second = _candidate(target, result, selected)
    assert second["status"] == "observed_changed_status"
    assert second["input_snapshot"] == first["input_snapshot"]
    assert second["rule_evidence"]["capture_bridge"]["input_manifest_json"] == first["rule_evidence"]["capture_bridge"]["input_manifest_json"]
    assert second["rule_evidence"]["capture_bridge"]["research_snapshot_sha256"] != first["rule_evidence"]["capture_bridge"]["research_snapshot_sha256"]
    assert second["rule_evidence"]["capture_bridge"]["call_json"] != first["rule_evidence"]["capture_bridge"]["call_json"]
    assert second["rule_evidence"]["capture_bridge"]["receipt_json"] != first["rule_evidence"]["capture_bridge"]["receipt_json"]


def test_postflight_change_and_protected_alias_paths_fail_closed(research, monkeypatch):
    _, target, _, result = research
    selected = _selected(result)[0]
    original_normalize = bridge.normalize_signal_artifact

    def touch_during_read(*args, **kwargs):
        stat = target.stat()
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        return original_normalize(*args, **kwargs)

    monkeypatch.setattr(bridge, "normalize_signal_artifact", touch_during_read)
    with pytest.raises(ReadonlySnapshotError, match="snapshot_changed"):
        _candidate(target, result, selected)
    monkeypatch.setattr(bridge, "normalize_signal_artifact", original_normalize)

    protected = Path(__file__).resolve()
    with pytest.raises(ReadonlySnapshotError, match="protected_snapshot_path"):
        _candidate(target, result, selected, research_snapshot_path=protected,
                   expected_snapshot_sha256=_sha(protected))
    alias = target.parent / "research-hardlink.db"
    os.link(target, alias)
    try:
        with pytest.raises(ReadonlySnapshotError, match="snapshot_path_alias"):
            _candidate(target, result, selected, research_snapshot_path=alias)
    finally:
        alias.unlink()
    with sqlite3.connect(target) as db:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    assert not Path(str(target) + "-wal").exists()
    with pytest.raises(ReadonlySnapshotError, match="snapshot_wal_header"):
        _candidate(target, result, selected)


def test_candidate_manifest_mismatch_is_rejected_before_return(research, monkeypatch):
    _, target, _, result = research
    selected = _selected(result)[0]
    original = bridge.normalize_signal_artifact

    def corrupt_projection(*args, **kwargs):
        candidate = original(*args, **kwargs)
        candidate["rule_evidence"]["capture_bridge"]["input_manifest_json"] += " "
        return candidate

    monkeypatch.setattr(bridge, "normalize_signal_artifact", corrupt_projection)
    with pytest.raises(bridge.SignalArtifactBridgeError, match="candidate_projection_mismatch"):
        _candidate(target, result, selected)


def test_candidate_and_caller_save_are_separate_with_exact_reopen_and_collision(research):
    _, target, _, result = research
    candidate = _candidate(target, result, _selected(result)[0])
    store_path = target.parent / "signal-artifacts.db"
    assert not store_path.exists()
    with SignalArtifactStore(store_path) as store:
        first = store.save_artifact(candidate, attempt_id="caller-save-1", run_id="caller-run-1",
                                    attempted_at=candidate["decision_at"])
        assert first.attempt_id == "caller-save-1"
        assert first.first_generated_at == candidate["generated_at"]
    with SignalArtifactStore(store_path) as store:
        readback = store.get_exact(artifact_key=first.artifact_key)
        assert readback.artifact.to_mapping()["input_snapshot"] == candidate["input_snapshot"]
        assert readback.artifact.to_mapping()["rule_evidence"] == candidate["rule_evidence"]
        replay = store.save_artifact(candidate, attempt_id="caller-save-2", run_id="caller-run-1",
                                     attempted_at=candidate["decision_at"])
        assert replay.artifact_key == first.artifact_key
        assert replay.first_generated_at == first.first_generated_at
        changed = normalize_signal_artifact(candidate, include_generated=True)
        changed["rule_state"]["state"] = "different"
        with pytest.raises(SignalArtifactCollisionError):
            store.save_artifact(changed, attempt_id="caller-save-3", run_id="caller-run-1",
                                attempted_at=candidate["decision_at"])
    with sqlite3.connect(store_path) as db:
        attempts = {row[0] for row in db.execute("SELECT attempt_id FROM signal_artifact_attempts")}
        relations = {row[0] for row in db.execute("SELECT attempt_id FROM signal_artifact_run_relations")}
    assert attempts == relations == {"caller-save-1", "caller-save-2"}
    assert "capture-one" not in attempts
