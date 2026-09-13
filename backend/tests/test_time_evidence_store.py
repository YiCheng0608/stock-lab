"""Isolation and append-only tests for the local time-evidence store."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.time_evidence import TIME_EVIDENCE_VERSION, TimeEvidence
from app.time_evidence_store import (
    TimeEvidenceConflictError,
    TimeEvidenceIntegrityError,
    TimeEvidenceNotFoundError,
    TimeEvidenceRevisionError,
    TimeEvidenceStore,
    TimeEvidenceStoreOwnershipError,
    TimeEvidenceStoreProtectedPathError,
)
from test_time_evidence import _point, _root_record


def _revision_record(revision_id: str, parent: str, **changes) -> dict:
    record = _root_record(
        snapshot_identity={"id": f"snapshot-{revision_id}", "hash": revision_id},
        revision_identity={"id": revision_id, "kind": "revision", "supersedes": parent},
        revision_available_at=_point("2026-03-10T01:00:00+00:00"),
        decision_at=_point("2026-03-10T02:00:00+00:00"),
        generated_at=_point("2026-03-10T02:01:00+00:00"),
        earliest_execution_at=_point("2026-03-10T03:00:00+00:00"),
    )
    record.update(changes)
    return record


def test_explicit_path_initializes_owned_schema_and_retry_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "time-evidence.sqlite"
    original = _root_record()
    with TimeEvidenceStore(path) as store:
        created = store.append(original)
        assert created.outcome == "created"
        replay = store.append(original)
        assert replay.outcome == "idempotent_replay"
        assert replay.evidence_key == created.evidence_key
        assert replay.stored_at == created.stored_at
        assert store.read(created.evidence_key).evidence.to_dict() == created.evidence.to_dict()
        assert store.connection.execute("SELECT COUNT(*) FROM time_evidence_rows").fetchone()[0] == 1
    assert path.exists()


def test_same_revision_identity_changed_payload_is_collision_and_no_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "time-evidence.sqlite"
    original = _root_record()
    with TimeEvidenceStore(path) as store:
        created = store.append(original)
        changed = _root_record(
            decision_at=_point("2026-03-09T17:02:00+08:00"),
            generated_at=_point("2026-03-09T17:03:00+08:00"),
        )
        with pytest.raises(TimeEvidenceConflictError):
            store.append(changed)
        assert store.read(created.evidence_key).payload_hash == created.payload_hash
        assert store.connection.execute("SELECT COUNT(*) FROM time_evidence_rows").fetchone()[0] == 1


def test_revision_appends_new_row_preserves_root_and_has_explicit_readers(tmp_path: Path) -> None:
    path = tmp_path / "time-evidence.sqlite"
    root = _root_record()
    revision = _revision_record("revision-2", "revision-1")
    with TimeEvidenceStore(path) as store:
        first = store.append(root)
        second = store.append(revision)
        assert first.evidence_key != second.evidence_key
        assert store.read(first.evidence_key).payload_hash == first.payload_hash
        selected = store.read_revision(
            {"exchange": "TWSE", "symbol": "2330"},
            {"id": "fixture-source", "kind": "local"},
            "revision-1",
        )
        assert selected.evidence_key == first.evidence_key
        history = store.history(
            {"exchange": "TWSE", "symbol": "2330"},
            {"id": "fixture-source", "kind": "local"},
        )
        assert [row.revision_id for row in history] == ["revision-1", "revision-2"]
        assert history[0].evidence.to_dict() == first.evidence.to_dict()
        with pytest.raises(TimeEvidenceNotFoundError):
            store.read_revision("TWSE:2330", "fixture-source", "missing")


def test_missing_cross_lineage_and_self_supersedes_fail_atomically(tmp_path: Path) -> None:
    path = tmp_path / "time-evidence.sqlite"
    with TimeEvidenceStore(path) as store:
        store.append(_root_record())
        with pytest.raises(TimeEvidenceRevisionError):
            store.append(_root_record(revision_identity={"id": "second-root", "kind": "root"}, snapshot_identity={"id": "snapshot-2", "hash": "second"}))
        with pytest.raises(TimeEvidenceRevisionError):
            store.append(_revision_record("revision-2", "does-not-exist"))
        with pytest.raises(TimeEvidenceRevisionError):
            store.append(_revision_record("revision-3", "revision-3"))
        cross = _revision_record(
            "revision-other",
            "revision-1",
            subject_identity={"exchange": "TPEx", "symbol": "2330"},
        )
        with pytest.raises(TimeEvidenceRevisionError):
            store.append(cross)
        assert store.connection.execute("SELECT COUNT(*) FROM time_evidence_rows").fetchone()[0] == 1


def test_sql_update_delete_and_replace_cannot_mutate_rows(tmp_path: Path) -> None:
    with TimeEvidenceStore(tmp_path / "time-evidence.sqlite") as store:
        stored = store.append(_root_record())
        row = store.connection.execute("SELECT * FROM time_evidence_rows WHERE evidence_key = ?", (stored.evidence_key,)).fetchone()
        columns = [item[1] for item in store.connection.execute("PRAGMA table_info(time_evidence_rows)").fetchall()]
        values = [row[column] for column in columns]
        with pytest.raises(sqlite3.DatabaseError):
            store.connection.execute("UPDATE time_evidence_rows SET payload_hash = 'tampered' WHERE evidence_key = ?", (stored.evidence_key,))
        with pytest.raises(sqlite3.DatabaseError):
            store.connection.execute("DELETE FROM time_evidence_rows WHERE evidence_key = ?", (stored.evidence_key,))
        with pytest.raises(sqlite3.DatabaseError):
            store.connection.execute(
                f"INSERT OR REPLACE INTO time_evidence_rows ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                values,
            )
        assert store.read(stored.evidence_key).payload_hash == stored.payload_hash


def test_read_revalidates_payload_and_relations_when_triggers_are_bypassed(tmp_path: Path) -> None:
    with TimeEvidenceStore(tmp_path / "time-evidence.sqlite") as store:
        stored = store.append(_root_record())
        store.connection.execute("DROP TRIGGER time_evidence_rows_immutable_update")
        store.connection.execute("UPDATE time_evidence_rows SET payload_hash = 'tampered' WHERE evidence_key = ?", (stored.evidence_key,))
        with pytest.raises(TimeEvidenceIntegrityError):
            store.read(stored.evidence_key)


def test_read_rejects_a_missing_grandparent_in_a_revision_chain(tmp_path: Path) -> None:
    with TimeEvidenceStore(tmp_path / "time-evidence.sqlite") as store:
        root = store.append(_root_record())
        child = store.append(_revision_record("revision-2", "revision-1"))
        grandchild = store.append(_revision_record("revision-3", "revision-2"))
        store.connection.execute("DROP TRIGGER time_evidence_rows_immutable_delete")
        store.connection.execute("DELETE FROM time_evidence_rows WHERE evidence_key = ?", (root.evidence_key,))
        with pytest.raises(TimeEvidenceIntegrityError):
            store.read(grandchild.evidence_key)


def test_ownership_rejects_existing_empty_foreign_and_protected_paths(tmp_path: Path) -> None:
    empty = tmp_path / "empty.sqlite"
    empty.touch()
    before = empty.read_bytes()
    with pytest.raises(TimeEvidenceStoreOwnershipError):
        TimeEvidenceStore(empty)
    assert empty.read_bytes() == before

    foreign = tmp_path / "foreign.sqlite"
    with sqlite3.connect(foreign) as connection:
        connection.execute("CREATE TABLE foreign_table (id INTEGER)")
        connection.commit()
    with pytest.raises(TimeEvidenceStoreOwnershipError):
        TimeEvidenceStore(foreign)

    with pytest.raises(TimeEvidenceStoreProtectedPathError):
        TimeEvidenceStore(Path(__file__).resolve().parents[2] / ".local" / "data" / "stock.db")


def test_json_export_is_local_atomic_projection_with_full_revision_history(tmp_path: Path) -> None:
    db_path = tmp_path / "time-evidence.sqlite"
    output_path = tmp_path / "exports" / "time-evidence.json"
    with TimeEvidenceStore(db_path) as store:
        store.append(_root_record())
        store.append(_revision_record("revision-2", "revision-1"))
        result_path = store.export_json(
            output_path,
            {"exchange": "TWSE", "symbol": "2330"},
            {"id": "fixture-source", "kind": "local"},
        )
        assert result_path == output_path
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["version"] == TIME_EVIDENCE_VERSION
    assert payload["availability_truth"] == "not_asserted"
    assert [row["evidence"]["revision_id"] for row in payload["records"]] == ["revision-1", "revision-2"]
    assert payload["records"][0]["evidence"]["revision_available_at"]["status"] == "not_applicable"


def test_export_refuses_existing_target_and_active_database(tmp_path: Path) -> None:
    db_path = tmp_path / "time-evidence.sqlite"
    output_path = tmp_path / "existing.json"
    output_path.write_text("keep", encoding="utf-8")
    with TimeEvidenceStore(db_path) as store:
        store.append(_root_record())
        with pytest.raises(FileExistsError):
            store.export_json(output_path, {"exchange": "TWSE", "symbol": "2330"}, {"id": "fixture-source", "kind": "local"})
        with pytest.raises(TimeEvidenceStoreProtectedPathError):
            store.export_json(db_path, {"exchange": "TWSE", "symbol": "2330"}, {"id": "fixture-source", "kind": "local"})
    assert output_path.read_text(encoding="utf-8") == "keep"
