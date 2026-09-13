"""Regression assets for the fixed 0004 -> 0005 migration and SQLite recovery.

The SQL fixture is intentionally a small, checked-in synthetic slice.  It is
not generated from ``Base.metadata`` and is not a copy of the production
database or a claim to represent the complete historical schema.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db import enable_sqlite_foreign_keys


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "migrations"
FIXTURE_SQL = FIXTURE_ROOT / "synthetic_prehead_0004_news_slice.sql"
FIXTURE_MANIFEST = FIXTURE_ROOT / "synthetic_prehead_0004_news_slice.json"
ALEMBIC_INI = REPO_ROOT / "backend" / "alembic.ini"


def _manifest() -> dict[str, Any]:
    return json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))


def _new_engine(path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    return engine


def _load_fixed_fixture(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(FIXTURE_SQL.read_text(encoding="utf-8"))
        # Test-only prerequisites; the fixed six-table SQL/manifest stays intact.
        connection.execute("CREATE TABLE signals (id INTEGER NOT NULL PRIMARY KEY)")
        connection.execute("""CREATE TABLE signal_settlements (
id INTEGER NOT NULL PRIMARY KEY, signal_id INTEGER NOT NULL,
horizon INTEGER NOT NULL DEFAULT 20, settlement_date DATE NOT NULL,
final_status VARCHAR(80), first_trigger VARCHAR(120), return_or_risk FLOAT,
incomparable_reason TEXT, source VARCHAR(500), data_time VARCHAR(80),
execution_date DATE, execution_price FLOAT, comparable BOOLEAN,
data_quality VARCHAR(30) NOT NULL DEFAULT 'complete',
CONSTRAINT uq_signal_settlement_horizon UNIQUE(signal_id,horizon),
FOREIGN KEY(signal_id) REFERENCES signals(id))""")


def _alembic_config(engine: Engine) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str((REPO_ROOT / "backend" / "alembic").as_posix()))
    config.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False))
    # The checked-in env.py reuses this engine and commits SQLite's version
    # table after non-transactional DDL completes.
    config.attributes["connection"] = engine
    return config


def _upgrade_to_fixture_revision(engine: Engine) -> None:
    config = _alembic_config(engine)
    command.upgrade(config, _manifest()["revision_after"])


def _normalize_default(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    while normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1].strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in "'\"":
        normalized = normalized[1:-1]
    return normalized.replace("''", "'")


def _canonical_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"bytes": bytes(value).hex()}
    return value


def _column_contract(connection, table_name: str) -> dict[str, dict[str, Any]]:
    return {
        column["name"]: {
            "type": str(column["type"]).upper(),
            "nullable": bool(column["nullable"]),
            "server_default": _normalize_default(column.get("default")),
        }
        for column in inspect(connection).get_columns(table_name)
    }


def _foreign_key_signatures(connection, table_name: str) -> set[tuple[Any, ...]]:
    return {
        (
            table_name,
            tuple(foreign_key.get("constrained_columns") or ()),
            foreign_key.get("referred_table"),
            tuple(foreign_key.get("referred_columns") or ()),
        )
        for foreign_key in inspect(connection).get_foreign_keys(table_name)
    }


def _unique_signatures(connection, table_name: str) -> set[tuple[Any, ...]]:
    inspector = inspect(connection)
    signatures = {
        (table_name, tuple(constraint.get("column_names") or ()))
        for constraint in inspector.get_unique_constraints(table_name)
    }
    signatures.update(
        (table_name, tuple(index.get("column_names") or ()))
        for index in inspector.get_indexes(table_name)
        if index.get("unique")
    )
    return signatures


def _schema_descriptor(connection, tables: list[str]) -> dict[str, Any]:
    inspector = inspect(connection)
    descriptor: dict[str, Any] = {}
    for table_name in sorted(tables):
        indexes = [
            {
                "name": index.get("name"),
                "unique": bool(index.get("unique")),
                "columns": list(index.get("column_names") or ()),
            }
            for index in inspector.get_indexes(table_name)
        ]
        unique_constraints = [
            {
                "name": constraint.get("name"),
                "columns": list(constraint.get("column_names") or ()),
            }
            for constraint in inspector.get_unique_constraints(table_name)
        ]
        foreign_keys = [
            {
                "columns": list(foreign_key.get("constrained_columns") or ()),
                "referred_table": foreign_key.get("referred_table"),
                "referred_columns": list(foreign_key.get("referred_columns") or ()),
            }
            for foreign_key in inspector.get_foreign_keys(table_name)
        ]
        descriptor[table_name] = {
            "columns": _column_contract(connection, table_name),
            "primary_key": {
                "name": inspector.get_pk_constraint(table_name).get("name"),
                "columns": list(inspector.get_pk_constraint(table_name).get("constrained_columns") or ()),
            },
            "indexes": sorted(indexes, key=lambda item: (item["name"] or "", item["columns"])),
            "unique_constraints": sorted(
                unique_constraints,
                key=lambda item: (item["name"] or "", item["columns"]),
            ),
            "foreign_keys": sorted(
                foreign_keys,
                key=lambda item: (
                    item["referred_table"] or "",
                    item["columns"],
                    item["referred_columns"],
                ),
            ),
        }
    return descriptor


def _database_fingerprint(connection, tables: list[str]) -> str:
    inspector = inspect(connection)
    table_payload: dict[str, Any] = {}
    for table_name in sorted(tables):
        columns = [column["name"] for column in inspector.get_columns(table_name)]
        quoted_columns = ", ".join(f'"{column}"' for column in columns)
        rows = connection.execute(text(f'SELECT {quoted_columns} FROM "{table_name}"')).fetchall()
        canonical_rows = [
            [_canonical_value(value) for value in row]
            for row in rows
        ]
        canonical_rows.sort(key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True, default=str))
        table_payload[table_name] = canonical_rows
    payload = {
        "schema": _schema_descriptor(connection, tables),
        "rows": table_payload,
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _common_rows_fingerprint(connection, manifest: dict[str, Any]) -> str:
    tables = [table for table in manifest["common_columns"] if table != "alembic_version"]
    payload: dict[str, Any] = {}
    for table_name in sorted(tables):
        columns = manifest["common_columns"][table_name]
        quoted_columns = ", ".join(f'"{column}"' for column in columns)
        rows = connection.execute(text(f'SELECT {quoted_columns} FROM "{table_name}"')).fetchall()
        canonical_rows = [
            [_canonical_value(value) for value in row]
            for row in rows
        ]
        canonical_rows.sort(key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True, default=str))
        payload[table_name] = {"columns": columns, "rows": canonical_rows}
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _integrity_checks(connection) -> None:
    assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    assert connection.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
    assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []


def _revision(connection) -> list[str]:
    return [
        row[0]
        for row in connection.execute(
            text("SELECT version_num FROM alembic_version ORDER BY version_num")
        )
    ]


def _row_counts(connection, manifest: dict[str, Any]) -> dict[str, int]:
    return {
        table_name: connection.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar_one()
        for table_name in manifest["expected_row_counts"]
    }


def _assert_required_constraints(connection, manifest: dict[str, Any]) -> None:
    inspector = inspect(connection)
    actual_primary_keys = {
        table_name: tuple(inspector.get_pk_constraint(table_name).get("constrained_columns") or ())
        for table_name, _columns in manifest["required_primary_keys"]
    }
    expected_primary_keys = {
        table_name: tuple(columns)
        for table_name, columns in manifest["required_primary_keys"]
    }
    assert actual_primary_keys == expected_primary_keys, (
        "primary key contract mismatch: "
        f"expected={expected_primary_keys!r} actual={actual_primary_keys!r}"
    )

    actual_foreign_keys = set()
    for table_name in manifest["tables"]:
        if inspector.has_table(table_name):
            actual_foreign_keys.update(_foreign_key_signatures(connection, table_name))
    expected_foreign_keys = {
        (table_name, tuple(columns), referred_table, tuple(referred_columns))
        for table_name, columns, referred_table, referred_columns in manifest["required_foreign_keys"]
    }
    assert expected_foreign_keys <= actual_foreign_keys

    actual_unique = set()
    for table_name, _columns in manifest["required_unique_columns"]:
        actual_unique.update(_unique_signatures(connection, table_name))
    expected_unique = {
        (table_name, tuple(columns))
        for table_name, columns in manifest["required_unique_columns"]
    }
    assert expected_unique <= actual_unique


def _assert_upgraded_temporal_contract(connection, manifest: dict[str, Any]) -> None:
    inspector = inspect(connection)
    news_columns = _column_contract(connection, "news_items")
    for name, expected in manifest["target_columns"].items():
        assert name in news_columns
        assert news_columns[name] == expected

    actual_indexes = {
        index.get("name"): tuple(index.get("column_names") or ())
        for index in inspector.get_indexes("news_items")
    }
    for index_name, columns in manifest["required_upgrade_indexes"]:
        assert actual_indexes.get(index_name) == tuple(columns)

    _assert_required_constraints(connection, manifest)
    expected_values = manifest["expected_temporal_values"]
    target_names = list(manifest["target_columns"])
    selected = ", ".join(["id", *[f'"{name}"' for name in target_names]])
    rows = connection.execute(text(f'SELECT {selected} FROM "news_items" ORDER BY id')).mappings().all()
    actual_values = {
        str(row["id"]): {name: row[name] for name in target_names}
        for row in rows
    }
    assert actual_values == expected_values


def _news_schema_contract(connection) -> dict[str, Any]:
    inspector = inspect(connection)
    required_index_columns = {
        ("display_time", "id"),
        ("event_date",),
        ("time_consistency",),
    }
    actual_index_columns = {
        tuple(index.get("column_names") or ())
        for index in inspector.get_indexes("news_items")
    }
    return {
        "columns": _column_contract(connection, "news_items"),
        "primary_key": tuple(inspector.get_pk_constraint("news_items").get("constrained_columns") or ()),
        "foreign_keys": sorted(_foreign_key_signatures(connection, "news_items")),
        "unique_columns": sorted(_unique_signatures(connection, "news_items")),
        "required_index_columns": sorted(required_index_columns & actual_index_columns),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sqlite_backup(source: Path, destination: Path) -> None:
    with sqlite3.connect(source) as source_connection, sqlite3.connect(destination) as destination_connection:
        source_connection.backup(destination_connection)


def _assert_restored_database(path: Path, manifest: dict[str, Any], expected_fingerprint: str) -> None:
    engine = _new_engine(path)
    try:
        with engine.connect() as connection:
            actual_tables = set(inspect(connection).get_table_names())
            missing_tables = set(manifest["tables"]) - actual_tables
            assert not missing_tables, f"restored database missing table(s): {sorted(missing_tables)}"
            _integrity_checks(connection)
            assert _revision(connection) == [manifest["revision_after"]]
            _assert_required_constraints(connection, manifest)
            assert _database_fingerprint(connection, manifest["tables"]) == expected_fingerprint, (
                "restored full-content schema-and-row fingerprint differs from backup"
            )
            _assert_upgraded_temporal_contract(connection, manifest)
    finally:
        engine.dispose()


def test_fixed_0004_prehead_upgrade_preserves_rows_and_is_idempotent(tmp_path):
    manifest = _manifest()
    database_path = tmp_path / "synthetic-prehead-0004.db"
    engine = _new_engine(database_path)
    try:
        _load_fixed_fixture(database_path)
        with engine.connect() as connection:
            inspector = inspect(connection)
            assert _revision(connection) == [manifest["revision_before"]]
            assert not (
                set(manifest["target_columns"]) & set(_column_contract(connection, "news_items"))
            ), "0004 fixture must genuinely lack every 0005 target column"
            assert _row_counts(connection, manifest) == manifest["expected_row_counts"]
            before_rows = _common_rows_fingerprint(connection, manifest)

        _upgrade_to_fixture_revision(engine)
        with engine.connect() as connection:
            assert _revision(connection) == [manifest["revision_after"]]
            assert _row_counts(connection, manifest) == manifest["expected_row_counts"]
            assert _common_rows_fingerprint(connection, manifest) == before_rows
            _assert_upgraded_temporal_contract(connection, manifest)
            _integrity_checks(connection)
            first_upgrade_fingerprint = _database_fingerprint(connection, manifest["tables"])

        # A second real Alembic command must not drift either schema or rows.
        _upgrade_to_fixture_revision(engine)
        with engine.connect() as connection:
            assert _revision(connection) == [manifest["revision_after"]]
            assert _database_fingerprint(connection, manifest["tables"]) == first_upgrade_fingerprint
            assert _common_rows_fingerprint(connection, manifest) == before_rows
            _assert_upgraded_temporal_contract(connection, manifest)
            _integrity_checks(connection)
    finally:
        engine.dispose()


def test_fresh_contract_has_no_known_default_drift_after_model_fix(tmp_path):
    manifest = _manifest()
    upgraded_path = tmp_path / "synthetic-upgraded.db"
    fresh_path = tmp_path / "fresh-head.db"
    upgraded = _new_engine(upgraded_path)
    fresh = _new_engine(fresh_path)
    try:
        _load_fixed_fixture(upgraded_path)
        _upgrade_to_fixture_revision(upgraded)
        _upgrade_to_fixture_revision(fresh)
        with upgraded.connect() as upgraded_connection, fresh.connect() as fresh_connection:
            upgraded_contract = _news_schema_contract(upgraded_connection)
            fresh_contract = _news_schema_contract(fresh_connection)
            assert upgraded_contract == fresh_contract
            assert upgraded_contract["foreign_keys"] == fresh_contract["foreign_keys"]
            assert upgraded_contract["unique_columns"] == fresh_contract["unique_columns"]
            assert upgraded_contract["required_index_columns"] == fresh_contract["required_index_columns"]

            expected_drift = {}
            assert set(upgraded_contract["columns"]) == set(fresh_contract["columns"])
            assert upgraded_contract["primary_key"] == fresh_contract["primary_key"]
            actual_drift = {}
            for column_name in upgraded_contract["columns"]:
                upgraded_column = upgraded_contract["columns"][column_name]
                fresh_column = fresh_contract["columns"][column_name]
                assert upgraded_column["type"] == fresh_column["type"], (
                    f"unexpected fresh type drift for {column_name}: "
                    f"{upgraded_column['type']!r} != {fresh_column['type']!r}"
                )
                assert upgraded_column["nullable"] == fresh_column["nullable"], (
                    f"unexpected fresh nullability drift for {column_name}: "
                    f"{upgraded_column['nullable']!r} != {fresh_column['nullable']!r}"
                )
                if upgraded_column["server_default"] != fresh_column["server_default"]:
                    actual_drift[column_name] = {
                        "upgraded_server_default": upgraded_column["server_default"],
                        "fresh_server_default": fresh_column["server_default"],
                    }
                else:
                    assert column_name not in expected_drift
            assert actual_drift == expected_drift

            # Reproduce the semantic consequence, not just inspector output:
            # both the upgraded historical schema and a fresh current-Base
            # schema accept raw inserts that omit both JSON columns.
            omission_insert = text(
                "INSERT INTO news_items "
                "(canonical_key, source_name, title, collected_at) "
                "VALUES (:canonical_key, :source_name, :title, :collected_at)"
            )
            upgraded_connection.execute(
                omission_insert,
                {
                    "canonical_key": "synthetic:omission:upgraded",
                    "source_name": "synthetic_fixture",
                    "title": "Synthetic omission default",
                    "collected_at": "2026-09-10 08:00:02",
                },
            )
            upgraded_connection.commit()
            upgraded_values = upgraded_connection.execute(
                text(
                    "SELECT symbols_json, theme_ids_json FROM news_items "
                    "WHERE canonical_key = 'synthetic:omission:upgraded'"
                )
            ).one()
            assert tuple(upgraded_values) == ("[]", "[]")
            fresh_connection.execute(
                omission_insert,
                {
                    "canonical_key": "synthetic:omission:fresh",
                    "source_name": "synthetic_fixture",
                    "title": "Synthetic omission default",
                    "collected_at": "2026-09-10 08:00:02",
                },
            )
            fresh_connection.commit()
            fresh_values = fresh_connection.execute(
                text(
                    "SELECT symbols_json, theme_ids_json FROM news_items "
                    "WHERE canonical_key = 'synthetic:omission:fresh'"
                )
            ).one()
            assert tuple(fresh_values) == ("[]", "[]")
            assert _revision(upgraded_connection) == [manifest["revision_after"]]
            assert _revision(fresh_connection) == [manifest["revision_after"]]
            _integrity_checks(upgraded_connection)
            _integrity_checks(fresh_connection)
    finally:
        upgraded.dispose()
        fresh.dispose()


def test_isolated_sqlite_backup_restore_round_trip_and_fault_detection(tmp_path):
    manifest = _manifest()
    source_path = tmp_path / "upgraded-source.db"
    backup_path = tmp_path / "consistent-backup.db"
    faulty_update_path = tmp_path / "faulty-update-copy.db"
    faulty_delete_path = tmp_path / "faulty-delete-copy.db"
    faulty_constraint_path = tmp_path / "faulty-constraint-copy.db"
    restored_path = tmp_path / "restored-new-path.db"
    fixture_hashes_before = {_path.name: _sha256(_path) for _path in (FIXTURE_SQL, FIXTURE_MANIFEST)}

    source_engine = _new_engine(source_path)
    try:
        _load_fixed_fixture(source_path)
        _upgrade_to_fixture_revision(source_engine)
        with source_engine.connect() as connection:
            source_fingerprint = _database_fingerprint(connection, manifest["tables"])
            _integrity_checks(connection)

        # The source is stable before the backup, and the backup contains rows
        # and post-migration schema rather than only an empty schema shell.
        _sqlite_backup(source_path, backup_path)
        backup_hash_before = _sha256(backup_path)
        _assert_restored_database(backup_path, manifest, source_fingerprint)

        # Mutate a different isolated copy to prove restore does not merely
        # reopen the failed copy or accept a row-count-only match.
        _sqlite_backup(backup_path, faulty_update_path)
        with sqlite3.connect(faulty_update_path) as faulty_connection:
            faulty_connection.execute("PRAGMA foreign_keys=ON")
            faulty_connection.execute(
                "UPDATE news_items SET title='CORRUPTED BY DRILL' WHERE id=1"
            )
        with pytest.raises(AssertionError, match="fingerprint"):
            _assert_restored_database(faulty_update_path, manifest, source_fingerprint)

        # A deletion is also rejected independently; this is a separate
        # failure mode so the content hash is not masked by row-count change.
        _sqlite_backup(backup_path, faulty_delete_path)
        with sqlite3.connect(faulty_delete_path) as faulty_connection:
            faulty_connection.execute("PRAGMA foreign_keys=ON")
            faulty_connection.execute("DELETE FROM news_items WHERE id=2")
        with pytest.raises(AssertionError, match="fingerprint"):
            _assert_restored_database(faulty_delete_path, manifest, source_fingerprint)

        # Drop the primary key/FKs/indexes from a temporary copy while keeping
        # the same rows.  The schema descriptor must reject this constraint
        # defect before it can be mistaken for a valid restore.
        _sqlite_backup(backup_path, faulty_constraint_path)
        with sqlite3.connect(faulty_constraint_path) as faulty_connection:
            faulty_connection.execute("PRAGMA foreign_keys=OFF")
            faulty_connection.execute(
                "CREATE TABLE news_items_without_constraints AS SELECT * FROM news_items"
            )
            faulty_connection.execute("DROP TABLE news_items")
            faulty_connection.execute(
                "ALTER TABLE news_items_without_constraints RENAME TO news_items"
            )
            faulty_connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(AssertionError, match="primary key contract"):
            _assert_restored_database(faulty_constraint_path, manifest, source_fingerprint)

        # Recovery is a new path populated through SQLite's backup API; the
        # original source/backup are never overwritten.
        _sqlite_backup(backup_path, restored_path)
        _assert_restored_database(restored_path, manifest, source_fingerprint)
        assert _sha256(backup_path) == backup_hash_before
        with source_engine.connect() as connection:
            assert _database_fingerprint(connection, manifest["tables"]) == source_fingerprint
        assert fixture_hashes_before == {
            _path.name: _sha256(_path) for _path in (FIXTURE_SQL, FIXTURE_MANIFEST)
        }
    finally:
        source_engine.dispose()


def test_restore_validation_rejects_bad_backup_and_wrong_schema(tmp_path):
    manifest = _manifest()
    expected_fingerprint = "not-a-valid-fingerprint"
    bad_backup = tmp_path / "bad-backup.db"
    bad_backup.write_bytes(b"not a SQLite database")
    with pytest.raises((AssertionError, sqlite3.DatabaseError, DBAPIError)):
        _assert_restored_database(bad_backup, manifest, expected_fingerprint)

    wrong_schema = tmp_path / "wrong-schema.db"
    with sqlite3.connect(wrong_schema) as connection:
        connection.execute(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY NOT NULL)"
        )
        connection.execute("INSERT INTO alembic_version(version_num) VALUES ('0005_news_temporal_contract')")
    with pytest.raises(AssertionError, match="missing table"):
        _assert_restored_database(wrong_schema, manifest, expected_fingerprint)
