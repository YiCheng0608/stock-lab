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


def _v2(target, *, attempt_id="capture-two"):
    return capture.execute_analysis_attempt(
        research_database_path=target, attempt_id=attempt_id,
        input_provenance="selected-bar/v1",
    )


def _v3(target, *, attempt_id="capture-three"):
    return capture.execute_analysis_attempt(
        research_database_path=target, attempt_id=attempt_id,
        input_provenance=capture.PRIOR_VOLUMES_MODE,
    )


def _link_raw_metadata(target, score_date):
    with sqlite3.connect(target) as db:
        run_id = db.execute("SELECT id FROM ingestion_runs ORDER BY id DESC LIMIT 1").fetchone()[0]
        instrument_id = db.execute("SELECT id FROM instruments WHERE symbol='TEST'").fetchone()[0]
        raw_id = db.execute(
            "INSERT INTO raw_payloads (ingestion_run_id,source,endpoint,payload_path,sha256,data_as_of,collected_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (run_id, "twse", "synthetic-endpoint", "not-opened/raw.json", "b" * 64,
             score_date, "2026-09-26 01:02:03.000000"),
        ).lastrowid
        db.execute(
            "UPDATE market_bars SET source='twse',raw_payload_id=? "
            "WHERE instrument_id=? AND trading_date=?",
            (raw_id, instrument_id, score_date),
        )
    return raw_id


def _reseal(target, change, change_receipt=None, *, attempt_id="capture-one"):
    """Change selected synthetic rows while retaining valid capture seals/schema."""
    with sqlite3.connect(target) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT * FROM worker_capture_calls WHERE attempt_id=? ORDER BY ordinal",
            (attempt_id,),
        ).fetchall()
        receipt = json.loads(db.execute(
            "SELECT payload FROM worker_capture_attempts WHERE attempt_id=?", (attempt_id,),
        ).fetchone()[0])
        for table in ("worker_capture_calls", "worker_capture_attempts"):
            db.execute("DROP TRIGGER " + table + "_no_update")
        for row in rows:
            payload = json.loads(row["payload"])
            if change(payload):
                digest = capture._seal(payload)
                receipt["call_digests"][row["ordinal"]] = digest
                db.execute(
                    "UPDATE worker_capture_calls SET payload=?,digest=? WHERE attempt_id=? AND ordinal=?",
                    (capture._canonical(payload), digest, attempt_id, row["ordinal"]),
                )
        if change_receipt is not None:
            change_receipt(receipt)
        db.execute(
            "UPDATE worker_capture_attempts SET payload=?,digest=? WHERE attempt_id=?",
            (capture._canonical(receipt), capture._seal(receipt), attempt_id),
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


def test_v2_candidate_keeps_local_bar_lineage_and_global_unknowns(research):
    _, target, _, v1 = research
    v1_candidate = _candidate(target, v1, _selected(v1)[0])
    result = _v2(target)
    assert len(_selected(result)) == 2
    for ordinal in _selected(result):
        call = result["captures"][ordinal]
        candidate = _candidate(target, result, ordinal, attempt_id="capture-two")
        assert candidate == normalize_signal_artifact(candidate, include_generated=True)
        assert candidate["input_snapshot"]["id"].startswith("worker-capture-input/v2:")
        assert candidate["input_snapshot"] != v1_candidate["input_snapshot"]
        evidence = candidate["rule_evidence"]["capture_bridge"]
        assert evidence["bridge_schema"] == "worker-capture-candidate/v2"
        assert evidence["raw_bytes_verification"] == "bytes_unverified"
        assert evidence["input_provenance_digest"] == bridge.digest_text(evidence["input_provenance_json"])
        assert json.loads(evidence["input_provenance_json"]) == call["input_provenance"]
        manifest = json.loads(evidence["input_manifest_json"])
        assert manifest["schema"] == "worker-capture-input-manifest/v2"
        assert manifest["selected_bar_input"]["coverage"] == ["close", "volume"]
        assert manifest["selected_bar_input"]["bar"]["close"] == call["input_provenance"]["bar"]["close"]
        assert "collected_at" not in manifest["selected_bar_input"]["bar"]
        assert "data_as_of" not in manifest["selected_bar_input"]["bar"]
        assert manifest["selected_bar_input"]["raw_status"] == "unknown"
        assert candidate["input_snapshot"]["hash"] == bridge.digest_text(evidence["input_manifest_json"])
        assert candidate["data_quality"]["local_input_row_linkage"] == "close_volume_metadata_captured"
        assert candidate["data_quality"]["source_verification"] == "not_officially_verified"
        assert candidate["data_quality"]["availability_verification"] == "unknown"
        assert candidate["data_quality"]["historical_inputs_verification"] == "unknown"
        assert candidate["as_of_at"] is None and candidate["earliest_execution_at"] is None
        assert candidate["basis_manifest"]["status"] == "unknown"
        assert "selected_bar_raw_payload_metadata_unavailable" in candidate["missing_reasons"]
        candidate["rule_state"]["reasons"].append("caller mutation")
        assert _candidate(target, result, ordinal, attempt_id="capture-two")["rule_state"] == call["actual_result"]


def test_v2_raw_metadata_is_opaque_and_new_attempt_tracks_changed_input(research):
    _, target, _, v1 = research
    score_date = v1["receipt"]["analysis"]["date"]
    raw_id = _link_raw_metadata(target, score_date)
    first = _v2(target)
    ordinal = _selected(first)[0]
    old_candidate = _candidate(target, first, ordinal, attempt_id="capture-two")
    old_evidence = old_candidate["rule_evidence"]["capture_bridge"]
    old_provenance = json.loads(old_evidence["input_provenance_json"])
    manifest = json.loads(old_evidence["input_manifest_json"])
    assert old_provenance["bar"]["raw_payload_id"] == raw_id
    assert old_provenance["raw_payload"]["sha256"] == "b" * 64
    assert old_provenance["raw_payload"]["payload_path"] == "not-opened/raw.json"
    assert old_provenance["raw_payload"]["collected_at"] == "2026-09-26 01:02:03.000000"
    assert manifest["selected_bar_input"]["raw_payload"]["sha256"] == "b" * 64
    assert "payload_path" not in manifest["selected_bar_input"]["raw_payload"]
    assert "collected_at" not in manifest["selected_bar_input"]["raw_payload"]
    assert old_candidate["data_quality"]["source_verification"] == "not_officially_verified"
    assert old_candidate["data_quality"]["availability_verification"] == "unknown"
    assert not (target.parent / "not-opened/raw.json").exists()
    with sqlite3.connect(target) as db:
        db.execute("UPDATE raw_payloads SET sha256=? WHERE id=?", ("c" * 64, raw_id))
        db.execute("UPDATE market_bars SET close=close+1,volume=volume+1 WHERE trading_date=?", (score_date,))
    assert _candidate(target, first, ordinal, attempt_id="capture-two")["input_snapshot"] == old_candidate["input_snapshot"]
    assert capture.read_analysis_attempt(
        research_database_path=target, attempt_id="capture-two",
    )["captures"][ordinal]["input_provenance"] == old_provenance
    second = _v2(target, attempt_id="capture-three")
    new_candidate = _candidate(target, second, _selected(second)[0], attempt_id="capture-three")
    assert new_candidate["input_snapshot"]["hash"] != old_candidate["input_snapshot"]["hash"]
    assert json.loads(new_candidate["rule_evidence"]["capture_bridge"]["input_provenance_json"])["raw_payload"]["sha256"] == "c" * 64

    def bad_declared_digest(payload):
        payload["input_provenance"]["raw_payload"]["sha256"] = "not-a-sha256"
        return True

    _reseal(target, bad_declared_digest, attempt_id="capture-two")
    with pytest.raises(capture.AnalysisCaptureError, match="selected_bar_raw_digest_invalid"):
        _candidate(target, first, ordinal, attempt_id="capture-two")


def test_v2_input_hash_excludes_observation_time_status_and_container(research):
    _, target, _, _ = research
    result = _v2(target)
    ordinal = _selected(result)[0]
    first = _candidate(target, result, ordinal, attempt_id="capture-two")
    before_sha = _sha(target)

    def observation_only(payload):
        payload["captured_at"] = (
            datetime.fromisoformat(payload["captured_at"]) + timedelta(milliseconds=100)
        ).isoformat()
        payload["signal_snapshot"]["status"] = "changed_observation"
        payload["input_provenance"]["bar"]["collected_at"] = "2099-01-01 00:00:00"
        payload["input_provenance"]["bar"]["data_as_of"] = "2099-01-01 00:00:00"
        return True

    def receipt_time_only(receipt):
        receipt["captured_at"] = (
            datetime.fromisoformat(receipt["captured_at"]) + timedelta(milliseconds=200)
        ).isoformat()

    _reseal(target, observation_only, receipt_time_only, attempt_id="capture-two")
    assert _sha(target) != before_sha
    second = _candidate(target, result, ordinal, attempt_id="capture-two")
    assert second["status"] == "changed_observation"
    assert second["input_snapshot"] == first["input_snapshot"]
    assert second["rule_evidence"]["capture_bridge"]["input_provenance_digest"] != first["rule_evidence"]["capture_bridge"]["input_provenance_digest"]
    assert second["rule_evidence"]["capture_bridge"]["research_snapshot_sha256"] != first["rule_evidence"]["capture_bridge"]["research_snapshot_sha256"]


def test_v2_nonselected_corruption_and_caller_save_exact_reopen(research):
    _, target, _, v1 = research
    v1_candidate = _candidate(target, v1, _selected(v1)[0])
    result = _v2(target)
    ordinal = _selected(result)[0]
    candidate = _candidate(target, result, ordinal, attempt_id="capture-two")
    store_path = target.parent / "signal-artifacts-v2.db"
    assert not store_path.exists()
    with SignalArtifactStore(store_path) as store:
        old = store.save_artifact(
            v1_candidate, attempt_id="v1-save", run_id="capture-caller-run",
            attempted_at=v1_candidate["decision_at"],
        )
        new = store.save_artifact(
            candidate, attempt_id="v2-save", run_id="capture-caller-run",
            attempted_at=candidate["decision_at"],
        )
        assert old.artifact_key != new.artifact_key
    with SignalArtifactStore(store_path) as store:
        readback = store.get_exact(artifact_key=new.artifact_key)
        assert readback.artifact.to_mapping()["input_snapshot"] == candidate["input_snapshot"]
        assert readback.artifact.to_mapping()["rule_evidence"] == candidate["rule_evidence"]
        retry = store.save_artifact(
            candidate, attempt_id="v2-retry", run_id="capture-caller-run",
            attempted_at=candidate["decision_at"],
        )
        assert retry.artifact_key == new.artifact_key
        changed = normalize_signal_artifact(candidate, include_generated=True)
        changed["rule_state"]["state"] = "different"
        with pytest.raises(SignalArtifactCollisionError):
            store.save_artifact(
                changed, attempt_id="v2-collision", run_id="capture-caller-run",
                attempted_at=candidate["decision_at"],
            )

    def corrupt_unselected(payload):
        if payload["evaluator"] == payload["selected_strategy"]["name"]:
            return False
        payload["input_provenance"]["bar"]["close"] = 1.0
        return True

    _reseal(target, corrupt_unselected, attempt_id="capture-two")
    with pytest.raises(capture.AnalysisCaptureError, match="selected_bar_arguments_mismatch"):
        _candidate(target, result, ordinal, attempt_id="capture-two")


def test_v3_manifest_seals_ordered_prior_rows_and_caller_save_reopens(research):
    _, target, _, _ = research
    result = _v3(target)
    for ordinal in _selected(result):
        call = result['captures'][ordinal]
        candidate = _candidate(target, result, ordinal, attempt_id='capture-three')
        evidence = candidate['rule_evidence']['capture_bridge']
        manifest = json.loads(evidence['input_manifest_json'])
        prior = manifest['prior_volumes_input']
        assert candidate == normalize_signal_artifact(candidate, include_generated=True)
        assert candidate['input_snapshot']['id'].startswith('worker-capture-input/v3:')
        assert candidate['input_snapshot']['hash'] == bridge.digest_text(evidence['input_manifest_json'])
        assert evidence['bridge_schema'] == 'worker-capture-candidate/v3'
        assert manifest['schema'] == 'worker-capture-input-manifest/v3'
        assert prior['schema'] == capture.PRIOR_VOLUMES_SCHEMA
        assert prior['row_count'] == 20
        assert prior['projected_values'] == call['arguments']['prior_volumes']
        assert [item['ordinal'] for item in prior['rows']] == list(range(20))
        assert [item['bar']['volume'] for item in prior['rows']] == prior['projected_values']
        assert manifest['selected_bar_input']['coverage'] == ['close', 'volume']
        assert evidence['raw_bytes_verification'] == 'bytes_unverified'
        assert candidate['data_quality']['source_verification'] == 'not_officially_verified'
        assert candidate['data_quality']['historical_inputs_verification'] == 'unknown'
        assert 'prior_volumes_raw_bytes_and_source_versions_unverified' in candidate['missing_reasons']
        store_path = target.parent / f'prior-artifacts-{ordinal}.db'
        with SignalArtifactStore(store_path) as store:
            saved = store.save_artifact(candidate, attempt_id=f'prior-save-{ordinal}',
                                        run_id='prior-run', attempted_at=candidate['decision_at'])
        with SignalArtifactStore(store_path) as store:
            reopened = store.get_exact(artifact_key=saved.artifact_key)
            assert reopened.artifact.to_mapping()['input_snapshot'] == candidate['input_snapshot']
            assert reopened.artifact.to_mapping()['rule_evidence'] == candidate['rule_evidence']


def test_v3_manifest_hash_tracks_prior_row_but_excludes_selected_observation_fields(research):
    _, target, _, v1 = research
    score_date = v1['receipt']['analysis']['date']
    raw_id = _link_raw_metadata(target, score_date)
    first = _v3(target)
    ordinal = _selected(first)[0]
    old = _candidate(target, first, ordinal, attempt_id='capture-three')
    first_provenance = json.loads(old['rule_evidence']['capture_bridge']['input_provenance_json'])
    assert first_provenance['selected_bar']['raw_payload']['payload_path'] == 'not-opened/raw.json'
    with sqlite3.connect(target) as db:
        db.execute("UPDATE raw_payloads SET payload_path='changed/no-open.json',"
                   "collected_at='2026-09-27 00:00:00' WHERE id=?", (raw_id,))
        db.execute("UPDATE market_bars SET collected_at='2026-09-27 01:00:00' "
                   "WHERE trading_date=?", (score_date,))
    observation_only = _v3(target, attempt_id='capture-four')
    observed = _candidate(target, observation_only, _selected(observation_only)[0],
                          attempt_id='capture-four')
    assert observed['input_snapshot']['hash'] == old['input_snapshot']['hash']
    assert observed['rule_evidence']['capture_bridge']['input_provenance_digest'] != old['rule_evidence']['capture_bridge']['input_provenance_digest']
    with sqlite3.connect(target) as db:
        db.execute("UPDATE market_bars SET source='different' WHERE id=("
                   "SELECT id FROM market_bars WHERE trading_date<? ORDER BY trading_date DESC LIMIT 1)",
                   (score_date,))
    changed = _v3(target, attempt_id='capture-five')
    new_candidate = _candidate(target, changed, _selected(changed)[0],
                               attempt_id='capture-five')
    assert new_candidate['input_snapshot']['hash'] != old['input_snapshot']['hash']
    assert json.loads(new_candidate['rule_evidence']['capture_bridge']['input_manifest_json'])['prior_volumes_input']['projected_values'] == json.loads(old['rule_evidence']['capture_bridge']['input_manifest_json'])['prior_volumes_input']['projected_values']
    assert capture.read_analysis_attempt(
        research_database_path=target, attempt_id='capture-three',
    )['captures'][ordinal]['input_provenance'] == first['captures'][ordinal]['input_provenance']
