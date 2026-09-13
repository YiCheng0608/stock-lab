from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.signal_artifact import SignalArtifactContractError, digest_text
from app.signal_artifact_store import (
    SignalArtifactAmbiguousError,
    SignalArtifactCollisionError,
    SignalArtifactIntegrityError,
    SignalArtifactNotFoundError,
    SignalArtifactRevisionError,
    SignalArtifactStore,
    SignalArtifactStoreOwnershipError,
    SignalArtifactStoreProtectedPathError,
)
from test_signal_artifact import NOW, _artifact


def _save(store: SignalArtifactStore, **changes: Any):
    return store.save(
        _artifact(**changes),
        attempt_id=changes.pop("attempt_id", None),
        run_id=changes.pop("run_id", None),
        generated_at=changes.pop("generated_at", None),
    )


def test_explicit_external_owned_store_replay_keeps_first_generated_and_records_attempts(tmp_path: Path) -> None:
    path = tmp_path / "signals.sqlite"
    with SignalArtifactStore(path) as store:
        first = store.save(_artifact(), attempt_id="attempt-1", run_id="run-1")
        second = store.save(
            _artifact(),
            attempt_id="attempt-2",
            run_id="run-1",
            generated_at="2026-01-01T02:00:00+00:00",
        )
        assert second.outcome == "idempotent_replay"
        assert second.first_generated_at == first.first_generated_at == NOW
        assert store.connection.execute("SELECT COUNT(*) FROM signal_artifact_attempts").fetchone()[0] == 2
        assert store.connection.execute("SELECT COUNT(*) FROM signal_artifact_run_relations").fetchone()[0] == 2
    with SignalArtifactStore(path) as reopened:
        assert reopened.read(first.artifact_key).first_generated_at == NOW


def test_same_input_changed_rule_result_is_collision_and_rolls_back(tmp_path: Path) -> None:
    with SignalArtifactStore(tmp_path / "signals.sqlite") as store:
        first = store.save(_artifact(), attempt_id="attempt-1")
        before = [
            store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "signal_artifacts",
                "signal_artifact_feature_refs",
                "signal_artifact_lifecycle",
                "signal_artifact_attempts",
            )
        ]
        with pytest.raises(SignalArtifactCollisionError):
            store.save(_artifact(status="observation", rule_evidence={"matched_rule": "other"}), attempt_id="attempt-2")
        after = [
            store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "signal_artifacts",
                "signal_artifact_feature_refs",
                "signal_artifact_lifecycle",
                "signal_artifact_attempts",
            )
        ]
        assert after == before
        assert store.read(first.artifact_key).first_generated_at == NOW


def test_two_asof_inputs_and_two_strategy_versions_are_independent_roots(tmp_path: Path) -> None:
    with SignalArtifactStore(tmp_path / "signals.sqlite") as store:
        asof_1 = store.save(_artifact(as_of_at="2025-12-31T23:00:00+00:00"), attempt_id="a1")
        asof_2 = store.save(_artifact(as_of_at="2026-01-01T00:00:00+00:00"), attempt_id="a2")
        version_2 = store.save(
            _artifact(
                strategy={"name": "demo_rule", "version": "2.0.0"},
                implementation_digest=digest_text("implementation:v2"),
                implementation_ref={
                    "mode": "caller_provided_only",
                    "verification": "not_officially_verified",
                    "ref": "local:rules/demo-v2.py",
                    "digest": digest_text("implementation:v2"),
                },
            ),
            attempt_id="a3",
        )
        assert len({asof_1.lineage_key, asof_2.lineage_key, version_2.lineage_key}) == 3
        assert len(store.list_artifacts(exchange="TWSE", symbol="2330")) == 3
        with pytest.raises(ValueError):
            store.list_artifacts()


def test_strategy_version_binding_rejects_changed_settings_or_implementation(tmp_path: Path) -> None:
    with SignalArtifactStore(tmp_path / "signals.sqlite") as store:
        store.save(_artifact(), attempt_id="a1")
        changed_settings = _artifact(ruleset_snapshot={"threshold": 2})
        with pytest.raises(SignalArtifactCollisionError):
            store.save(changed_settings, attempt_id="a2")
        changed_impl_digest = digest_text("implementation:v2")
        with pytest.raises(SignalArtifactCollisionError):
            store.save(
                _artifact(
                    implementation_digest=changed_impl_digest,
                    implementation_ref={
                        "mode": "caller_provided_only",
                        "verification": "not_officially_verified",
                        "ref": "local:rules/demo-v2.py",
                        "digest": changed_impl_digest,
                    },
                ),
                attempt_id="a3",
            )


def test_linear_withdrawal_revision_requires_same_research_payload_and_exact_parent(tmp_path: Path) -> None:
    with SignalArtifactStore(tmp_path / "signals.sqlite") as store:
        root = store.save(_artifact(), attempt_id="root", generated_at=NOW)
        withdrawn = store.save(
            _artifact(
                revision=2,
                supersedes_artifact_key=root.artifact_key,
                lifecycle_state="withdrawn",
                lifecycle_reason="manual review",
                lifecycle_at="2026-01-01T02:00:00+00:00",
                generated_at="2026-01-01T02:00:00+00:00",
            ),
            attempt_id="withdraw",
        )
        assert [row.revision for row in store.history(root.lineage_key)] == [1, 2]
        assert withdrawn.artifact.lifecycle_state == "withdrawn"
        with pytest.raises((SignalArtifactRevisionError, SignalArtifactCollisionError)):
            store.save(
                _artifact(
                    revision=2,
                    supersedes_artifact_key=root.artifact_key,
                    lifecycle_state="withdrawn",
                    lifecycle_reason="second branch",
                    lifecycle_at="2026-01-01T03:00:00+00:00",
                    generated_at="2026-01-01T03:00:00+00:00",
                ),
                attempt_id="branch",
            )
        with pytest.raises(SignalArtifactRevisionError):
            store.save(
                _artifact(
                    revision=3,
                    supersedes_artifact_key=withdrawn.artifact_key,
                    lifecycle_state="withdrawn",
                    lifecycle_reason="cycle",
                    lifecycle_at="2026-01-01T04:00:00+00:00",
                    generated_at="2026-01-01T04:00:00+00:00",
                ),
                attempt_id="terminal-child",
            )


def test_changed_input_cannot_be_smuggled_as_a_child_revision(tmp_path: Path) -> None:
    with SignalArtifactStore(tmp_path / "signals.sqlite") as store:
        root = store.save(_artifact(), attempt_id="root")
        with pytest.raises(SignalArtifactRevisionError):
            store.save(
                _artifact(
                    as_of_at="2026-01-01T00:00:00+00:00",
                    revision=2,
                    supersedes_artifact_key=root.artifact_key,
                    lifecycle_state="withdrawn",
                    lifecycle_reason="wrong input lineage",
                    lifecycle_at="2026-01-01T02:00:00+00:00",
                    generated_at="2026-01-01T02:00:00+00:00",
                ),
                attempt_id="wrong-child",
            )
        assert store.connection.execute("SELECT COUNT(*) FROM signal_artifacts").fetchone()[0] == 1


def test_failed_precommit_rolls_back_new_attempt_and_run_relations(tmp_path: Path) -> None:
    with SignalArtifactStore(tmp_path / "signals.sqlite") as store:
        first = store.save(_artifact(), attempt_id="first")
        with pytest.raises(RuntimeError):
            store.save(
                _artifact(),
                attempt_id="failed-replay",
                run_id="failed-run",
                _pre_commit_validator=lambda connection: (_ for _ in ()).throw(RuntimeError("inject")),
            )
        assert store.connection.execute("SELECT COUNT(*) FROM signal_artifact_attempts").fetchone()[0] == 1
        assert store.connection.execute("SELECT COUNT(*) FROM signal_artifact_run_relations").fetchone()[0] == 0
        assert store.read(first.artifact_key).first_generated_at == NOW


def test_sql_immutable_and_reader_revalidates_tampered_payload(tmp_path: Path) -> None:
    with SignalArtifactStore(tmp_path / "signals.sqlite") as store:
        first = store.save(_artifact(), attempt_id="first")
        with pytest.raises(sqlite3.DatabaseError):
            store.connection.execute(
                "UPDATE signal_artifacts SET payload_hash = 'tampered' WHERE artifact_key = ?",
                (first.artifact_key,),
            )
        store.connection.execute("DROP TRIGGER signal_artifacts_immutable_update")
        store.connection.execute(
            "UPDATE signal_artifacts SET payload_hash = 'sha256:' || printf('%064d', 1) WHERE artifact_key = ?",
            (first.artifact_key,),
        )
        with pytest.raises(SignalArtifactIntegrityError):
            store.read(first.artifact_key)


def test_reader_revalidates_run_relation_key_and_attempt_time(tmp_path: Path) -> None:
    with SignalArtifactStore(tmp_path / "signals.sqlite") as store:
        first = store.save(_artifact(), attempt_id="attempt", run_id="run")
        store.connection.execute("DROP TRIGGER signal_artifact_run_relations_immutable_update")
        store.connection.execute(
            "UPDATE signal_artifact_run_relations SET run_id = 'tampered-run' WHERE artifact_key = ?",
            (first.artifact_key,),
        )
        with pytest.raises(SignalArtifactIntegrityError):
            store.read(first.artifact_key)


def test_insert_or_replace_without_rowid_is_blocked_for_all_owned_rows(tmp_path: Path) -> None:
    path = tmp_path / "signals.sqlite"
    with SignalArtifactStore(path) as store:
        first = store.save(_artifact(), attempt_id="attempt", run_id="run")
        for table in (
            "signal_artifacts",
            "signal_artifact_bindings",
            "signal_artifact_feature_refs",
            "signal_artifact_lifecycle",
            "signal_artifact_attempts",
            "signal_artifact_run_relations",
        ):
            with pytest.raises(sqlite3.DatabaseError):
                store.connection.execute(
                    f'INSERT OR REPLACE INTO "{table}" SELECT * FROM "{table}"'
                )
        assert store.read(first.artifact_key).artifact_key == first.artifact_key


def test_external_default_connection_blocks_explicit_rowid_and_alternate_unique_replace_with_child(
    tmp_path: Path,
) -> None:
    path = tmp_path / "signals.sqlite"
    with SignalArtifactStore(path) as store:
        root = store.save(_artifact(), attempt_id="root", run_id="root-run")
        store.save(
            _artifact(
                revision=2,
                supersedes_artifact_key=root.artifact_key,
                lifecycle_state="withdrawn",
                lifecycle_reason="fixture withdrawal",
                lifecycle_at="2026-01-01T02:00:00+00:00",
                generated_at="2026-01-01T02:00:00+00:00",
            ),
            attempt_id="child",
            run_id="child-run",
        )

    def snapshot(connection: sqlite3.Connection, table: str) -> list[tuple[Any, ...]]:
        return connection.execute(f'SELECT rowid, * FROM "{table}" ORDER BY rowid').fetchall()

    def replacement(value: Any) -> Any:
        if isinstance(value, int) and not isinstance(value, bool):
            return value + 1000
        return f"{value}-replacement"

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 0
        assert connection.execute("PRAGMA recursive_triggers").fetchone()[0] == 0
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            ).fetchall()
            if row[0] != "signal_artifact_store_metadata" and not row[0].startswith("sqlite_")
        ]
        before = {table: snapshot(connection, table) for table in tables}
        for table in tables:
            info = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            names = [item[1] for item in info]
            rows = connection.execute(f'SELECT * FROM "{table}"').fetchall()
            indexes = connection.execute(f'PRAGMA index_list("{table}")').fetchall()
            unique_sets = [
                [item[2] for item in connection.execute(f'PRAGMA index_info("{index[1]}")').fetchall()]
                for index in indexes
                if index[2]
            ]
            for unique_columns in unique_sets:
                for original in rows:
                    candidate = dict(zip(names, original))
                    if any(candidate[column] is None for column in unique_columns):
                        continue
                    all_unique_columns = {column for columns in unique_sets for column in columns}
                    for column in all_unique_columns - set(unique_columns):
                        candidate[column] = replacement(candidate[column])
                    sql = (
                        f'INSERT OR REPLACE INTO "{table}" '
                        f'({",".join(f"\"{name}\"" for name in names)}) '
                        f'VALUES ({",".join("?" for _ in names)})'
                    )
                    with pytest.raises(sqlite3.DatabaseError):
                        connection.execute(sql, [candidate[name] for name in names])
                    connection.rollback()
            for original_with_rowid in connection.execute(
                f'SELECT rowid, * FROM "{table}"'
            ).fetchall():
                rowid, *original = original_with_rowid
                candidate = dict(zip(names, original))
                all_unique_columns = {column for columns in unique_sets for column in columns}
                for column in all_unique_columns:
                    candidate[column] = replacement(candidate[column])
                sql = (
                    f'INSERT OR REPLACE INTO "{table}" (rowid, '
                    f'{",".join(f"\"{name}\"" for name in names)}) '
                    f'VALUES ({",".join("?" for _ in range(len(names) + 1))})'
                )
                with pytest.raises(sqlite3.DatabaseError):
                    connection.execute(sql, [rowid] + [candidate[name] for name in names])
                connection.rollback()
        after = {table: snapshot(connection, table) for table in tables}
        assert after == before


def test_exact_readers_do_not_guess_latest_and_history_order_is_stable(tmp_path: Path) -> None:
    with SignalArtifactStore(tmp_path / "signals.sqlite") as store:
        first = store.save(_artifact(), attempt_id="first")
        with pytest.raises(ValueError):
            store.get_exact(lineage_key=first.lineage_key)
        assert store.get_exact(lineage_key=first.lineage_key, revision=1).artifact_key == first.artifact_key
        with pytest.raises(SignalArtifactNotFoundError):
            store.get_exact(identity_hash="sha256:" + "0" * 64)
        with pytest.raises(SignalArtifactNotFoundError):
            # A broad subject query is deliberately not an exact reader.
            store.get_exact(artifact_key=first.artifact_key, lineage_key=first.lineage_key, revision=2)


def test_ownership_rejects_existing_empty_foreign_and_workspace_paths(tmp_path: Path) -> None:
    empty = tmp_path / "empty.sqlite"
    empty.touch()
    before = empty.read_bytes()
    with pytest.raises(SignalArtifactStoreOwnershipError):
        SignalArtifactStore(empty)
    assert empty.read_bytes() == before

    foreign = tmp_path / "foreign.sqlite"
    with sqlite3.connect(foreign) as connection:
        connection.execute("CREATE TABLE foreign_table (id INTEGER)")
    with pytest.raises(SignalArtifactStoreOwnershipError):
        SignalArtifactStore(foreign)

    workspace_path = Path(__file__).resolve().parents[2] / "data" / "signal-artifacts.sqlite"
    with pytest.raises(SignalArtifactStoreProtectedPathError):
        SignalArtifactStore(workspace_path)


def test_concurrent_same_identity_is_one_canonical_row(tmp_path: Path) -> None:
    path = tmp_path / "signals.sqlite"

    def worker(attempt: str):
        with SignalArtifactStore(path) as store:
            return store.save(_artifact(), attempt_id=attempt)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, ["concurrent-1", "concurrent-2"]))
    assert {result.artifact_key for result in results}.__len__() == 1
    with SignalArtifactStore(path) as store:
        assert store.connection.execute("SELECT COUNT(*) FROM signal_artifacts").fetchone()[0] == 1
        assert store.connection.execute("SELECT COUNT(*) FROM signal_artifact_attempts").fetchone()[0] == 2
