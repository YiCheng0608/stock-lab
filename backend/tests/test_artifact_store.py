from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from app.artifact_store import (
    ArtifactAmbiguousError,
    ArtifactCollisionError,
    ArtifactStore,
    ArtifactStoreBusyError,
    ArtifactStoreError,
    ArtifactStoreOwnershipError,
    canonical_json,
)
from app.atr import ATRObservation, calculate_atr14


UTC = timezone.utc
DECISION = datetime(2026, 1, 31, 8, tzinfo=UTC)
GENERATED_1 = datetime(2026, 2, 1, 0, 0, 1, tzinfo=UTC)
GENERATED_2 = datetime(2026, 2, 1, 0, 0, 2, tzinfo=UTC)


def _instrument_evidence() -> dict[str, str]:
    return {
        "source_ref": "fixture://instrument-catalog/v1",
        "snapshot_id": "instrument-snapshot-1",
        "snapshot_hash": "instrument-hash-1",
        "validation_status": "caller_supplied_only",
    }


def _dependencies(*, source_revision: str = "source-1") -> dict[str, object]:
    return {
        "manifest": {
            "ordered_source_rows": ["fixture://bars/1", "fixture://bars/2"],
            "corporate_actions": "fixture://actions/1",
        },
        "instrument_evidence": _instrument_evidence(),
        "source_evidence": {
            "source_ref": "fixture://bars",
            "revision": source_revision,
            "available_at": datetime(2026, 1, 30, 8, tzinfo=UTC),
        },
        "calendar_evidence": {
            "calendar_ref": "fixture://twse-calendar/v1",
            "snapshot_hash": "calendar-hash-1",
            "available_at": datetime(2026, 1, 1, 0, tzinfo=UTC),
        },
        "halt_evidence": {
            "source_ref": "fixture://halts/v1",
            "snapshot_hash": "halt-hash-1",
            "status": "complete",
        },
        "previous_close_evidence": {
            "source_ref": "fixture://prev-close/v1",
            "snapshot_hash": "prev-close-hash-1",
            "status": "not_used_true_sequence_start",
        },
    }


def _calculate(*, decision_at: datetime = DECISION, snapshot_id: str = "bars-snapshot-1"):
    start = date(2026, 1, 2)
    sessions = [start + timedelta(days=index) for index in range(16)]
    bars = [
        {
            "trading_date": trading_date,
            "open": 100 + index,
            "high": 105 + index,
            "low": 100 + index,
            "close": 102 + index,
            "price_basis": "raw_v1",
            "data_available_at": datetime.combine(trading_date, datetime.min.time(), tzinfo=UTC),
        }
        for index, trading_date in enumerate(sessions)
    ]
    return calculate_atr14(
        bars,
        price_basis="raw_v1",
        input_snapshot_ref=snapshot_id,
        expected_sessions=sessions,
        decision_at=decision_at,
        true_sequence_start=True,
        corporate_action_coverage="complete",
        corporate_action_source_ref="fixture://actions/v1",
        corporate_action_available_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _save(store: ArtifactStore, artifact, **kwargs):
    dependencies = _dependencies(**kwargs.pop("dependency_kwargs", {}))
    instrument = kwargs.pop(
        "instrument",
        {"exchange": "TWSE", "symbol": "2330", "legacy_reference": "legacy:technical:2330"},
    )
    market_date = kwargs.pop("market_date", date(2026, 1, 17))
    return store.save_atr_artifact(
        instrument,
        market_date,
        artifact,
        snapshot_hash=kwargs.pop("snapshot_hash", "bars-hash-1"),
        implementation_digest=kwargs.pop("implementation_digest", "atr.py-sha256-1"),
        dependency_manifest=dependencies["manifest"],
        instrument_evidence=dependencies["instrument_evidence"],
        source_evidence=dependencies["source_evidence"],
        calendar_evidence=dependencies["calendar_evidence"],
        halt_evidence=dependencies["halt_evidence"],
        previous_close_evidence=dependencies["previous_close_evidence"],
        calculation_config=kwargs.pop(
            "calculation_config",
            {"period": 14, "algorithm": "wilder", "precision": "float64", "smoothing": "wilder", "seed": "simple_mean"},
        ),
        feature_name=kwargs.pop("feature_name", "atr14"),
        generated_at=kwargs.pop("generated_at", GENERATED_1),
        attempt_id=kwargs.pop("attempt_id", None),
        run_id=kwargs.pop("run_id", None),
        attempted_at=kwargs.pop("attempted_at", None),
        **kwargs,
    )


def test_real_atr_round_trip_persists_observations_and_evidence(tmp_path) -> None:
    path = tmp_path / "artifacts.sqlite"
    artifact = _calculate()

    with ArtifactStore(path) as store:
        saved = _save(store, artifact, attempt_id="attempt-1", run_id="run-1")
        assert saved.artifact_key
        assert saved.instrument == {"exchange": "TWSE", "symbol": "2330"}
        assert saved.legacy_reference == "legacy:technical:2330"
        assert saved.feature_version == "technical_v2_atr14_wilder"
        assert saved.observations[-1].atr == pytest.approx(5.0)
        assert saved.instrument_evidence["validation_status"] == "caller_supplied_only"
        assert saved.source_evidence["source_ref"] == "fixture://bars"
        assert saved.dependency_manifest["ordered_source_rows"] == [
            "fixture://bars/1",
            "fixture://bars/2",
        ]
        payload = json.loads(
            store.connection.execute(
                "SELECT research_payload_json FROM feature_artifacts WHERE artifact_key = ?",
                (saved.artifact_key,),
            ).fetchone()[0]
        )
        assert "generated_at" not in payload
        assert "attempt-1" not in json.dumps(payload)
        assert store.attempts_for(saved.artifact_key)[0].run_id == "run-1"


def test_same_day_different_asof_and_feature_version_coexist(tmp_path) -> None:
    with ArtifactStore(tmp_path / "artifacts.sqlite") as store:
        first = _save(store, _calculate(), attempt_id="first")
        second_artifact = replace(
            _calculate(decision_at=datetime(2026, 2, 1, 8, tzinfo=UTC), snapshot_id="bars-snapshot-2"),
            feature_version="technical_v3_atr14_wilder",
        )
        second = _save(
            store,
            second_artifact,
            snapshot_hash="bars-hash-2",
            attempt_id="second",
        )
        assert first.artifact_key != second.artifact_key
        assert store.connection.execute("SELECT COUNT(*) FROM feature_artifacts").fetchone()[0] == 2
        assert store.get_atr(
            {"exchange": "twse", "symbol": "2330"},
            date(2026, 1, 17),
            feature_version=first.feature_version,
            snapshot_id=first.snapshot_id,
            snapshot_hash=first.snapshot_hash,
            decision_at=first.decision_at,
        ).artifact_key == first.artifact_key


def test_retry_preserves_first_generated_at_and_records_separate_usage(tmp_path) -> None:
    with ArtifactStore(tmp_path / "artifacts.sqlite") as store:
        first = _save(
            store,
            _calculate(),
            generated_at=GENERATED_1,
            attempt_id="attempt-1",
            run_id="run-1",
        )
        retry = _save(
            store,
            _calculate(),
            generated_at=GENERATED_2,
            attempt_id="attempt-2",
            run_id="run-2",
            attempted_at=GENERATED_2,
        )
        assert retry.artifact_key == first.artifact_key
        assert retry.generated_at == GENERATED_1
        attempts = store.attempts_for(first.artifact_key)
        assert [attempt.outcome for attempt in attempts] == ["created", "idempotent_replay"]
        assert [attempt.run_id for attempt in attempts] == ["run-1", "run-2"]


def test_payload_collision_rolls_back_without_orphan_attempt_or_rows(tmp_path) -> None:
    with ArtifactStore(tmp_path / "artifacts.sqlite") as store:
        original = _save(store, _calculate(), attempt_id="original")
        changed_observations = list(original.artifact.observations)
        changed_observations[-1] = replace(changed_observations[-1], atr=999.0)
        changed = replace(original.artifact, observations=tuple(changed_observations))
        with pytest.raises(ArtifactCollisionError):
            _save(store, changed, attempt_id="collision")
        assert store.get_by_key(original.artifact_key).artifact.observations[-1].atr == pytest.approx(5.0)
        assert [a.attempt_id for a in store.attempts_for(original.artifact_key)] == ["original"]
        assert store.connection.execute("SELECT COUNT(*) FROM feature_artifacts").fetchone()[0] == 1
        assert store.connection.execute("SELECT COUNT(*) FROM artifact_observations").fetchone()[0] == 16


def test_null_warmup_observation_is_preserved(tmp_path) -> None:
    source = _calculate()
    null_observation = replace(
        source.observations[0],
        true_range=None,
        atr=None,
        null_reason="missing_previous_close",
        valid_tr_count=0,
    )
    artifact = replace(source, observations=(null_observation, *source.observations[1:]))
    with ArtifactStore(tmp_path / "artifacts.sqlite") as store:
        saved = _save(store, artifact)
        assert saved.observations[0].true_range is None
        assert saved.observations[0].atr is None
        assert saved.observations[0].null_reason == "missing_previous_close"


def test_canonical_json_is_stable_and_rejects_invalid_numbers_or_naive_timestamps() -> None:
    left = canonical_json({"b": [2, 1], "a": {"available_at": "2026-01-01T08:00:00+08:00"}})
    right = canonical_json({"a": {"available_at": "2026-01-01T00:00:00Z"}, "b": [2, 1]})
    assert left == right
    assert hashlib.sha256(left.encode()).hexdigest() == hashlib.sha256(right.encode()).hexdigest()
    with pytest.raises(ValueError):
        canonical_json({"value": float("nan")})
    with pytest.raises(ValueError):
        canonical_json({"value": float("inf")})
    with pytest.raises(ValueError):
        canonical_json({"decision_at": "2026-01-01T08:00:00"})


def test_invalid_artifact_payload_is_rejected_before_write(tmp_path) -> None:
    source = _calculate()
    invalid_observations = list(source.observations)
    invalid_observations[-1] = replace(invalid_observations[-1], atr=float("nan"))
    with ArtifactStore(tmp_path / "artifacts.sqlite") as store:
        with pytest.raises(ValueError):
            _save(store, replace(source, observations=tuple(invalid_observations)))
        assert store.connection.execute("SELECT COUNT(*) FROM feature_artifacts").fetchone()[0] == 0


def test_observation_null_policy_and_nonnegative_ranges_are_fail_closed(tmp_path) -> None:
    source = _calculate()
    with ArtifactStore(tmp_path / "artifacts.sqlite") as store:
        missing_reason = replace(source.observations[0], atr=None, true_range=None, null_reason=None)
        with pytest.raises(ValueError):
            _save(store, replace(source, observations=(missing_reason, *source.observations[1:])))
        negative_tr = replace(source.observations[0], true_range=-1.0)
        with pytest.raises(ValueError):
            _save(store, replace(source, observations=(negative_tr, *source.observations[1:])))
        negative_atr = replace(source.observations[-1], atr=-1.0)
        with pytest.raises(ValueError):
            _save(store, replace(source, observations=(*source.observations[:-1], negative_atr)))
        assert store.connection.execute("SELECT COUNT(*) FROM feature_artifacts").fetchone()[0] == 0


def test_sqlite_foreign_keys_and_immutable_update_delete_are_enforced(tmp_path) -> None:
    with ArtifactStore(tmp_path / "artifacts.sqlite") as store:
        saved = _save(store, _calculate())
        with pytest.raises(sqlite3.IntegrityError):
            store.connection.execute(
                "INSERT INTO artifact_observations VALUES (?, 0, '2026-01-01', NULL, NULL, NULL, 0, 0, 0, NULL)",
                ("missing",),
            )
        with pytest.raises(sqlite3.DatabaseError):
            store.connection.execute(
                "UPDATE feature_artifacts SET symbol = '9999' WHERE artifact_key = ?",
                (saved.artifact_key,),
            )
        with pytest.raises(sqlite3.DatabaseError):
            store.connection.execute(
                "DELETE FROM feature_artifacts WHERE artifact_key = ?",
                (saved.artifact_key,),
            )
        with pytest.raises(sqlite3.DatabaseError):
            store.connection.execute(
                "INSERT OR REPLACE INTO feature_artifacts SELECT * FROM feature_artifacts WHERE artifact_key = ?",
                (saved.artifact_key,),
            )
        columns = [row[1] for row in store.connection.execute("PRAGMA table_info(feature_artifacts)")]
        values = list(
            store.connection.execute(
                "SELECT * FROM feature_artifacts WHERE artifact_key = ?", (saved.artifact_key,)
            ).fetchone()
        )
        values[0] = "different-key"
        placeholders = ",".join("?" for _ in columns)
        with pytest.raises(sqlite3.DatabaseError):
            store.connection.execute(
                f"INSERT OR REPLACE INTO feature_artifacts ({','.join(columns)}) VALUES ({placeholders})",
                values,
            )
        with pytest.raises(sqlite3.DatabaseError):
            store.connection.execute(
                "INSERT INTO artifact_observations VALUES (?, 999, '2099-01-01', NULL, NULL, 'extra', 0, 0, 0, NULL)",
                (saved.artifact_key,),
            )
        with pytest.raises(sqlite3.DatabaseError):
            store.connection.execute(
                "INSERT INTO artifact_dependencies VALUES (?, 'unexpected', '{}', 'hash')",
                (saved.artifact_key,),
            )
        assert store.get_by_key(saved.artifact_key).symbol == "2330"


def test_existing_non_artifact_database_is_rejected_without_changes(tmp_path) -> None:
    path = tmp_path / "research.sqlite"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE legacy_data (id INTEGER PRIMARY KEY, value TEXT)")
    connection.execute("INSERT INTO legacy_data(value) VALUES ('keep')")
    connection.commit()
    connection.close()
    before = path.read_bytes()
    with pytest.raises(ArtifactStoreOwnershipError):
        ArtifactStore(path)
    assert path.read_bytes() == before
    check = sqlite3.connect(path)
    assert check.execute("SELECT * FROM legacy_data").fetchall() == [(1, "keep")]
    assert check.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall() == [("legacy_data",)]
    check.close()


def test_close_and_reopen_preserves_history(tmp_path) -> None:
    path = tmp_path / "artifacts.sqlite"
    with ArtifactStore(path) as store:
        saved = _save(store, _calculate())
        key = saved.artifact_key
    with ArtifactStore(path) as reopened:
        restored = reopened.get_by_key(key)
        assert restored is not None
        assert restored.generated_at == GENERATED_1
        assert restored.artifact.to_dict() == saved.artifact.to_dict()


def test_existing_empty_or_view_only_database_is_rejected_unchanged(tmp_path) -> None:
    empty_path = tmp_path / "empty.sqlite"
    empty_path.touch()
    empty_before = empty_path.read_bytes()
    with pytest.raises(ArtifactStoreOwnershipError):
        ArtifactStore(empty_path)
    assert empty_path.read_bytes() == empty_before

    view_path = tmp_path / "view-only.sqlite"
    connection = sqlite3.connect(view_path)
    connection.execute("CREATE VIEW external_view AS SELECT 1 AS value")
    connection.commit()
    connection.close()
    view_before = view_path.read_bytes()
    with pytest.raises(ArtifactStoreOwnershipError):
        ArtifactStore(view_path)
    assert view_path.read_bytes() == view_before


def test_unsupported_schema_version_is_rejected_without_changes(tmp_path) -> None:
    path = tmp_path / "unsupported.sqlite"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE artifact_store_metadata (store_kind TEXT PRIMARY KEY, schema_version INTEGER NOT NULL, created_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO artifact_store_metadata VALUES (?, 999, ?)",
        ("taiwan-stock-research.feature-artifact", GENERATED_1.isoformat()),
    )
    connection.commit()
    connection.close()
    before_bytes = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns
    with pytest.raises(ArtifactStoreOwnershipError):
        ArtifactStore(path)
    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime


def test_invalid_attempt_timestamp_rolls_back_parent_children_dependencies_and_attempt(tmp_path) -> None:
    with ArtifactStore(tmp_path / "artifacts.sqlite") as store:
        with pytest.raises(ValueError):
            _save(
                store,
                _calculate(),
                attempt_id="invalid-time",
                attempted_at=datetime(2026, 2, 1, 0, 0),
            )
        counts = {
            table: store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "feature_artifacts",
                "artifact_observations",
                "artifact_dependencies",
                "artifact_attempts",
            )
        }
        assert counts == {
            "feature_artifacts": 0,
            "artifact_observations": 0,
            "artifact_dependencies": 0,
            "artifact_attempts": 0,
        }


def test_same_attempt_replay_keeps_first_usage_and_conflicting_run_fails(tmp_path) -> None:
    with ArtifactStore(tmp_path / "artifacts.sqlite") as store:
        saved = _save(
            store,
            _calculate(),
            attempt_id="same-attempt",
            run_id="run-1",
            attempted_at=GENERATED_1,
        )
        replay = _save(
            store,
            _calculate(),
            generated_at=GENERATED_2,
            attempt_id="same-attempt",
            run_id="run-1",
            attempted_at=GENERATED_1,
        )
        assert replay.artifact_key == saved.artifact_key
        attempts = store.attempts_for(saved.artifact_key)
        assert len(attempts) == 1
        assert attempts[0].outcome == "created"
        with pytest.raises(ArtifactStoreError):
            _save(
                store,
                _calculate(),
                attempt_id="same-attempt",
                run_id="run-2",
                attempted_at=GENERATED_1,
            )
        assert len(store.attempts_for(saved.artifact_key)) == 1


def test_locked_second_connection_returns_bounded_retryable_error(tmp_path) -> None:
    path = tmp_path / "artifacts.sqlite"
    with ArtifactStore(path) as first, ArtifactStore(path) as second:
        first.connection.execute("BEGIN IMMEDIATE")
        second.connection.execute("PRAGMA busy_timeout = 50")
        with pytest.raises(ArtifactStoreBusyError):
            _save(second, _calculate(), attempt_id="blocked")
        assert second.connection.execute("SELECT COUNT(*) FROM feature_artifacts").fetchone()[0] == 0
        first.connection.execute("ROLLBACK")


def test_two_store_connections_are_idempotent_for_same_identity(tmp_path) -> None:
    path = tmp_path / "artifacts.sqlite"
    with ArtifactStore(path) as first, ArtifactStore(path) as second:
        first_saved = _save(first, _calculate(), attempt_id="first")
        second_saved = _save(second, _calculate(), attempt_id="second")
        assert second_saved.artifact_key == first_saved.artifact_key
        assert second.connection.execute("SELECT COUNT(*) FROM feature_artifacts").fetchone()[0] == 1
        assert len(second.attempts_for(first_saved.artifact_key)) == 2


def test_explicit_reader_does_not_guess_latest_and_reports_ambiguity(tmp_path) -> None:
    with ArtifactStore(tmp_path / "artifacts.sqlite") as store:
        first = _save(store, _calculate(), attempt_id="first")
        second = _save(
            store,
            _calculate(),
            dependency_kwargs={"source_revision": "source-2"},
            attempt_id="second",
        )
        with pytest.raises(ArtifactAmbiguousError):
            store.get_atr(
                "TWSE:2330",
                first.market_date,
                feature_version=first.feature_version,
                snapshot_id=first.snapshot_id,
                snapshot_hash=first.snapshot_hash,
                decision_at=first.decision_at,
            )
        assert store.get_by_key(second.artifact_key).artifact.to_dict() == first.artifact.to_dict()


def test_missing_exchange_or_evidence_is_fail_closed(tmp_path) -> None:
    with ArtifactStore(tmp_path / "artifacts.sqlite") as store:
        with pytest.raises(ValueError):
            _save(store, _calculate(), instrument={"symbol": "2330"})
        with pytest.raises(ValueError):
            store.save_atr_artifact(
                "TWSE:2330",
                date(2026, 1, 17),
                _calculate(),
                snapshot_hash="hash",
                implementation_digest="impl",
                dependency_manifest={},
            )
        with pytest.raises(ValueError):
            _save(store, _calculate(), market_date=date(2026, 1, 16))
        with pytest.raises(ValueError):
            _save(store, _calculate(), calculation_config={"algorithm": "wilder"})
