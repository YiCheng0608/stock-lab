"""Bounded file-backed turnover migration checks; run via the dedicated tool.

The canonical legacy fixture keeps the current identity schemas and removes
only the two 0007 availability columns. The NULL case explicitly changes a
copied turnover column to nullable; it is a synthetic compatibility boundary,
not evidence that the current ORM schema or a production database allows NULL.
No captured payload body or existing database is read or copied.
"""

from __future__ import annotations

import json
import os
import platform
import sqlite3
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

VALIDATION_ROOT = os.environ.get("TURNOVER_MIGRATION_VALIDATION_ROOT")
if __name__ == "__main__" and not VALIDATION_ROOT:
    raise SystemExit("Run tools/Invoke-TurnoverMigrationValidation.ps1")

import alembic
import sqlalchemy
from sqlalchemy import MetaData, create_engine, event, inspect, select
from sqlalchemy.pool import NullPool

from app import migrations
from app.db import Base, enable_sqlite_foreign_keys
from app import models  # noqa: F401: register the canonical empty schema


PREVIOUS_REVISIONS = (
    "0001_schema_v1", "0002_instrument_exchange_key", "0003_backtest_run_metadata",
    "0004_product_news_themes", "0005_news_temporal_contract", "0006_news_json_defaults",
)
CURRENT_REVISION = "0007_turnover_availability"
AVAILABILITY_COLUMNS = {"turnover_status", "turnover_reason"}
PRESERVED_TABLES = ("instruments", "raw_payloads", "market_bars")
PEAKS = {"files": 0, "directories": 0, "bytes": 0, "db_bytes": 0}


def _observe_disk() -> None:
    root = Path(VALIDATION_ROOT)
    files, directories, total_bytes = 0, 1, 0
    db_path = root / "data" / "legacy.db"
    allowed_files = {db_path, Path(str(db_path) + "-journal")}
    allowed_directories = {root / "data", root / "raw"}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"Validation refuses a symlink: {path}")
        if path.is_dir():
            directories += 1
            if path not in allowed_directories:
                raise RuntimeError(f"Unexpected validation directory: {path}")
        else:
            files += 1
            total_bytes += path.stat().st_size
            if path not in allowed_files:
                raise RuntimeError(f"Unexpected validation file: {path}")
    db_bytes = db_path.stat().st_size if db_path.exists() else 0
    for key, value in (("files", files), ("directories", directories),
                       ("bytes", total_bytes), ("db_bytes", db_bytes)):
        PEAKS[key] = max(PEAKS[key], value)
    if files > 2 or directories > 3 or total_bytes > 2 * 1024 * 1024 or db_bytes > 1024 * 1024:
        raise RuntimeError(f"Validation disk budget exceeded: {PEAKS}")


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class FileMigrationCases:
    """Four cases shared by the two supported upgrade paths."""

    mode: str

    def setUp(self) -> None:
        self.root = Path(VALIDATION_ROOT).resolve()
        self.db_path = self.root / "data" / "legacy.db"
        self.assertEqual(Path(os.environ["STOCK_DATA_DIR"]).resolve(), self.root / "data")
        self.assertEqual(Path(os.environ["STOCK_RAW_DIR"]).resolve(), self.root / "raw")
        self.assertEqual(Path(os.environ["STOCK_DB_PATH"]).resolve(), self.db_path)
        self.assertFalse(self.db_path.exists(), "The runner must remove the previous owned DB")
        self.engine = None
        self._new_engine()

    def tearDown(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
        _observe_disk()

    def _new_engine(self) -> None:
        self.engine = create_engine(f"sqlite:///{self.db_path.as_posix()}", poolclass=NullPool)
        enable_sqlite_foreign_keys(self.engine)

        @event.listens_for(self.engine, "connect")
        def limit_file(dbapi_connection, _record) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=DELETE")
                if cursor.fetchone()[0] != "delete":
                    raise RuntimeError("Validation requires SQLite DELETE journaling")
                cursor.execute("PRAGMA page_size=4096")
                cursor.execute("PRAGMA page_size")
                if cursor.fetchone()[0] != 4096:
                    raise RuntimeError("Validation requires 4096-byte SQLite pages")
                cursor.execute("PRAGMA max_page_count=256")
                if cursor.fetchone()[0] != 256:
                    raise RuntimeError("Validation cannot enforce the 1 MiB DB limit")
            finally:
                cursor.close()
            _observe_disk()

        @event.listens_for(self.engine, "after_cursor_execute")
        def observe_statement(*_args) -> None:
            _observe_disk()

    def _reopen(self) -> None:
        old_engine = self.engine
        old_engine.dispose()
        self._new_engine()
        self.assertIsNot(self.engine, old_engine)

    def _fixture(self, *, nullable_turnover: bool = False, existing_status: bool = False) -> None:
        metadata = MetaData()
        for table in Base.metadata.sorted_tables:
            table.to_metadata(metadata)
        metadata.tables["market_bars"].c.turnover.nullable = nullable_turnover
        self.assertFalse(Base.metadata.tables["market_bars"].c.turnover.nullable)
        metadata.create_all(self.engine)
        captured_at = datetime(2026, 9, 4, 12, 34, 56)
        with self.engine.begin() as connection:
            if not existing_status:
                for name in sorted(AVAILABILITY_COLUMNS):
                    connection.exec_driver_sql(f"ALTER TABLE market_bars DROP COLUMN {_quote(name)}")
            connection.execute(metadata.tables["instruments"].insert().values(
                id=17, market="TW", exchange="TWSE", symbol="LEGACY", name="Legacy fixture",
                instrument_type="stock", industry="fixture", listing_date=date(2020, 1, 2),
                is_watchlisted=True, status="active", created_at=captured_at,
            ))
            connection.execute(metadata.tables["raw_payloads"].insert().values(
                id=23, ingestion_run_id=None, source="legacy-fixture",
                endpoint="fixture://turnover", payload_path=None, sha256=None,
                data_as_of="2026-09-04", collected_at=captured_at,
            ))
            amounts = (12345.5, 0.0, -5.25, None) if nullable_turnover else (12345.5, 0.0, -5.25)
            fields = [column.name for column in metadata.tables["market_bars"].columns
                      if column.name not in AVAILABILITY_COLUMNS]
            sql = ("INSERT INTO market_bars (" + ", ".join(map(_quote, fields)) + ") VALUES ("
                   + ", ".join("?" for _ in fields) + ")")
            for index, amount in enumerate(amounts, start=1):
                values = {
                    "id": index, "instrument_id": 17, "trading_date": date(2026, 9, index).isoformat(),
                    "open": 100.25 + index, "high": 106.5 + index, "low": 98.75 + index,
                    "close": 103.5 + index, "adj_close": 102.5 + index,
                    "volume": 1000 + index, "turnover": amount, "source": "legacy-fixture",
                    "data_as_of": None if index == 2 else captured_at.isoformat(" "),
                    "collected_at": (captured_at + timedelta(seconds=index)).isoformat(" "),
                    "raw_payload_id": 23, "is_suspended": index == 3,
                }
                connection.exec_driver_sql(sql, tuple(values[name] for name in fields))
            if existing_status:
                connection.exec_driver_sql(
                    "UPDATE market_bars SET turnover_status='unavailable', turnover_reason='invalid' WHERE id=1"
                )
                connection.exec_driver_sql(
                    "UPDATE market_bars SET turnover_status='available', turnover_reason=NULL WHERE id=2"
                )
                connection.exec_driver_sql(
                    "UPDATE market_bars SET turnover_status='unknown', turnover_reason='legacy_invalid' WHERE id=3"
                )
            if self.mode == "alembic":
                connection.exec_driver_sql(
                    "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
                )
                connection.exec_driver_sql("INSERT INTO alembic_version VALUES (?)", (PREVIOUS_REVISIONS[-1],))
            else:
                connection.exec_driver_sql(
                    "CREATE TABLE schema_migrations (version VARCHAR(64) PRIMARY KEY, applied_at DATETIME NOT NULL)"
                )
                for revision in PREVIOUS_REVISIONS:
                    connection.exec_driver_sql(
                        "INSERT INTO schema_migrations VALUES (?, ?)", (revision, captured_at.isoformat(" ")),
                    )
        _observe_disk()

    def _original_state(self):
        state = {}
        with self.engine.connect() as connection:
            for name in PRESERVED_TABLES:
                columns = [column for column in Base.metadata.tables[name].columns
                           if column.name not in AVAILABILITY_COLUMNS]
                typed_rows = connection.execute(select(*columns).order_by(columns[0])).all()
                state[name + ":typed"] = tuple(
                    tuple((type(value).__name__, value) for value in row) for row in typed_rows
                )
                names = [column.name for column in columns]
                expressions = [_quote(column) for column in names]
                expressions += [f"typeof({_quote(column)})" for column in names]
                state[name + ":storage"] = tuple(connection.exec_driver_sql(
                    "SELECT " + ", ".join(expressions) + f" FROM {_quote(name)} ORDER BY id"
                ).all())
                state[name + ":columns"] = tuple(
                    row for row in connection.exec_driver_sql(f"PRAGMA table_xinfo({_quote(name)})")
                    if row[1] not in AVAILABILITY_COLUMNS
                )
                state[name + ":foreign_keys"] = tuple(connection.exec_driver_sql(
                    f"PRAGMA foreign_key_list({_quote(name)})"
                ).all())
                state[name + ":indexes"] = tuple(connection.exec_driver_sql(
                    f"PRAGMA index_list({_quote(name)})"
                ).all())
            state["raw_relationship"] = tuple(connection.exec_driver_sql(
                "SELECT b.id, b.instrument_id, i.exchange, i.symbol, b.raw_payload_id, "
                "r.source, r.endpoint, r.payload_path, r.sha256, r.data_as_of, r.collected_at "
                "FROM market_bars b JOIN instruments i ON i.id=b.instrument_id "
                "JOIN raw_payloads r ON r.id=b.raw_payload_id ORDER BY b.id"
            ).all())
        return state

    def _schema_and_markers(self):
        with self.engine.connect() as connection:
            schema = tuple(connection.exec_driver_sql(
                "SELECT type, name, tbl_name, sql FROM sqlite_schema ORDER BY type, name"
            ).all())
            if self.mode == "alembic":
                markers = tuple(connection.exec_driver_sql("SELECT * FROM alembic_version").all())
            else:
                markers = tuple(connection.exec_driver_sql("SELECT * FROM schema_migrations ORDER BY version").all())
        return schema, markers

    def _upgrade(self) -> None:
        if self.mode == "alembic":
            self.assertTrue(Path(migrations.ALEMBIC_CONFIG_PATH).is_file())
            # A missing dependency/config must fail this case, never quietly exercise fallback.
            with patch.object(migrations, "_fallback_upgrade", side_effect=AssertionError("Unexpected fallback")):
                migrations.upgrade_database(self.engine)
        else:
            migrations._fallback_upgrade(self.engine)
        _observe_disk()

    def _assert_integrity(self) -> None:
        with self.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql("PRAGMA foreign_keys").scalar(), 1)
            self.assertEqual(connection.exec_driver_sql("PRAGMA integrity_check").scalar(), "ok")
            self.assertEqual(connection.exec_driver_sql("PRAGMA foreign_key_check").all(), [])

    def _assert_markers(self, *, upgraded: bool) -> None:
        with self.engine.connect() as connection:
            inspector = inspect(connection)
            if self.mode == "alembic":
                self.assertFalse(inspector.has_table("schema_migrations"))
                self.assertEqual(connection.exec_driver_sql("SELECT version_num FROM alembic_version").all(),
                                 [(CURRENT_REVISION if upgraded else PREVIOUS_REVISIONS[-1],)])
            else:
                self.assertFalse(inspector.has_table("alembic_version"))
                expected = PREVIOUS_REVISIONS + ((CURRENT_REVISION,) if upgraded else ())
                self.assertEqual(connection.exec_driver_sql(
                    "SELECT version, count(*) FROM schema_migrations GROUP BY version ORDER BY version"
                ).all(), [(revision, 1) for revision in expected])

    def _statuses(self):
        with self.engine.connect() as connection:
            return connection.exec_driver_sql(
                "SELECT id, turnover_status, turnover_reason FROM market_bars ORDER BY id"
            ).all()

    def _assert_persisted(self, before, expected) -> None:
        self._reopen()
        self.assertEqual(self._original_state(), before)
        self.assertEqual(self._statuses(), expected)
        self._assert_integrity()
        self._assert_markers(upgraded=True)

    def test_legacy_values_survive_reopen_and_rerun(self) -> None:
        self._fixture()
        before = self._original_state()
        self._reopen()
        self._upgrade()
        expected = [(1, "available", None), (2, "unknown", "legacy_zero_ambiguous"),
                    (3, "unknown", "legacy_invalid")]
        self._assert_persisted(before, expected)
        self._upgrade()
        self._assert_persisted(before, expected)

    def test_synthetic_nullable_legacy_null_is_unverified(self) -> None:
        self._fixture(nullable_turnover=True)
        before = self._original_state()
        self._reopen()
        self._upgrade()
        expected = [(1, "available", None), (2, "unknown", "legacy_zero_ambiguous"),
                    (3, "unknown", "legacy_invalid"), (4, "unknown", "legacy_invalid")]
        self._assert_persisted(before, expected)
        self._upgrade()
        self._assert_persisted(before, expected)

    def test_initial_existing_status_is_authoritative(self) -> None:
        self._fixture(existing_status=True)
        before, expected = self._original_state(), self._statuses()
        self._reopen()
        self._upgrade()
        self._assert_persisted(before, expected)
        self._upgrade()
        self._assert_persisted(before, expected)

    def test_failed_backfill_reopens_unchanged_and_retries_same_file(self) -> None:
        self._fixture()
        before = self._original_state()
        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER block_bar_update BEFORE UPDATE ON market_bars "
                "BEGIN SELECT RAISE(ABORT, 'blocked_turnover_backfill'); END"
            )
        schema_and_markers = self._schema_and_markers()
        self._reopen()
        with self.assertRaisesRegex(sqlalchemy.exc.DBAPIError, "blocked_turnover_backfill"):
            self._upgrade()
        self._reopen()
        self.assertEqual(self._original_state(), before)
        self.assertEqual(self._schema_and_markers(), schema_and_markers)
        columns = {column["name"] for column in inspect(self.engine).get_columns("market_bars")}
        self.assertTrue(AVAILABILITY_COLUMNS.isdisjoint(columns))
        self._assert_integrity()
        self._assert_markers(upgraded=False)
        with self.engine.begin() as connection:
            connection.exec_driver_sql("DROP TRIGGER block_bar_update")
        self._upgrade()
        self._assert_persisted(before, [(1, "available", None), (2, "unknown", "legacy_zero_ambiguous"),
                                        (3, "unknown", "legacy_invalid")])
        self._upgrade()
        self._assert_persisted(before, [(1, "available", None), (2, "unknown", "legacy_zero_ambiguous"),
                                        (3, "unknown", "legacy_invalid")])


@unittest.skipUnless(VALIDATION_ROOT, "Use tools/Invoke-TurnoverMigrationValidation.ps1")
class AlembicFileMigrationTests(FileMigrationCases, unittest.TestCase):
    mode = "alembic"


@unittest.skipUnless(VALIDATION_ROOT, "Use tools/Invoke-TurnoverMigrationValidation.ps1")
class FallbackFileMigrationTests(FileMigrationCases, unittest.TestCase):
    mode = "fallback"


if __name__ == "__main__":
    program = unittest.main(verbosity=2, exit=False)
    print("R1A2_METRICS=" + json.dumps({
        "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
        "sqlalchemy": sqlalchemy.__version__, "alembic": alembic.__version__,
        "tests_run": program.result.testsRun, "skipped": len(program.result.skipped),
        "peaks": PEAKS,
    }, sort_keys=True))
    raise SystemExit(0 if program.result.wasSuccessful() and not program.result.skipped else 1)
