"""Startup boundaries on real, externally isolated SQLite databases."""

import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import database_readiness as readiness, main, migrations
from app.db import Base, enable_sqlite_foreign_keys


def fingerprint(path):
    if not path.exists():
        return None
    stat = path.stat()
    return hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_size, stat.st_mtime_ns


@pytest.fixture
def ready_db(tmp_path):
    path = tmp_path / "ready.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    migrations.upgrade_database(engine)
    engine.dispose()
    return path


def check_unchanged(path, reason=None):
    before = fingerprint(path)
    if reason:
        with pytest.raises(readiness.DatabaseReadinessError, match=reason) as error:
            readiness.check_database_readiness(path)
        for message in ("STOCK_DATA_DIR", "STOCK_DB_PATH", "STOCK_RAW_DIR", "backup", "external copy", "init-db"):
            assert message in str(error.value)
    else:
        readiness.check_database_readiness(path)
        readiness.check_database_readiness(path)
    assert fingerprint(path) == before


def markers(path, alembic, fallback):
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE IF EXISTS alembic_version")
        connection.execute("DROP TABLE IF EXISTS schema_migrations")
        for name, column, values in (("alembic_version", "version_num", alembic), ("schema_migrations", "version", fallback)):
            if values is not None:
                # No affinity/constraints: malformed values must reach validation.
                connection.execute(f"CREATE TABLE {name} ({column})")
                connection.executemany(f"INSERT INTO {name} VALUES (?)", [(value,) for value in values])


def test_current_head_and_fallback_count_in_memory():
    assert len(readiness.REVISIONS) == 8
    assert readiness.REVISIONS[-1] == "0008_portfolio_share_integer"
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (readiness.REVISIONS[-1],))
        readiness._check_markers(connection, {"alembic_version"})
        connection.execute("UPDATE alembic_version SET version_num = ?", (readiness.REVISIONS[-2],))
        with pytest.raises(readiness.DatabaseReadinessError, match="current head revision"):
            readiness._check_markers(connection, {"alembic_version"})
        connection.execute("DROP TABLE alembic_version")
        connection.execute("CREATE TABLE schema_migrations (version TEXT)")
        connection.executemany(
            "INSERT INTO schema_migrations VALUES (?)", [(revision,) for revision in readiness.REVISIONS]
        )
        readiness._check_markers(connection, {"schema_migrations"})
        connection.execute("DELETE FROM schema_migrations WHERE version = ?", (readiness.REVISIONS[-1],))
        with pytest.raises(readiness.DatabaseReadinessError, match="all eight revisions"):
            readiness._check_markers(connection, {"schema_migrations"})
        connection.execute("INSERT INTO schema_migrations VALUES (?)", (readiness.REVISIONS[-1],))
        connection.execute("INSERT INTO schema_migrations VALUES ('future_revision')")
        with pytest.raises(readiness.DatabaseReadinessError, match="known prefix"):
            readiness._check_markers(connection, {"schema_migrations"})


def test_alembic_head_repeat_and_migration_bombs(ready_db, monkeypatch):
    def bomb(*args, **kwargs):
        raise AssertionError("startup must not mutate schema")

    monkeypatch.setattr(migrations, "upgrade_database", bomb)
    monkeypatch.setattr(migrations, "_fallback_upgrade", bomb)
    monkeypatch.setattr(Base.metadata, "create_all", bomb)
    from app import db, news_json_defaults
    monkeypatch.setattr(db, "init_db", bomb)
    monkeypatch.setattr(news_json_defaults, "ensure_news_json_server_defaults", bomb)
    check_unchanged(ready_db)
    monkeypatch.setattr(readiness, "DB_PATH", ready_db)
    before = fingerprint(ready_db)
    with TestClient(main.app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
    assert fingerprint(ready_db) == before


def test_actual_forced_fallback_eight_revisions(tmp_path, monkeypatch):
    path = tmp_path / "fallback.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    monkeypatch.setattr(migrations, "ALEMBIC_CONFIG_PATH", tmp_path / "absent.ini")
    migrations.upgrade_database(engine)
    engine.dispose()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall() == [(v,) for v in readiness.REVISIONS]
        assert not connection.execute("SELECT name FROM sqlite_schema WHERE name='alembic_version'").fetchall()
    check_unchanged(path)


@pytest.mark.parametrize("prefix", range(1, 9))
def test_head_with_known_fallback_prefix(ready_db, prefix):
    markers(ready_db, [readiness.REVISIONS[-1]], readiness.REVISIONS[:prefix])
    check_unchanged(ready_db)


@pytest.mark.parametrize("alembic", [[], [None], [6], [b"0007_turnover_availability"], ["unknown"], [readiness.REVISIONS[-2]], [readiness.REVISIONS[-1]] * 2])
def test_bad_alembic_cannot_be_overridden_by_full_fallback(ready_db, alembic):
    markers(ready_db, alembic, readiness.REVISIONS)
    check_unchanged(ready_db, "Alembic")


@pytest.mark.parametrize("alembic", [None, [readiness.REVISIONS[-1]]])
@pytest.mark.parametrize("fallback", [[], [None], [6], [b"0001_schema_v1"], ["unknown"], [readiness.REVISIONS[1]], [readiness.REVISIONS[0]] * 2, [readiness.REVISIONS[0], readiness.REVISIONS[2]], [*readiness.REVISIONS, "future"]])
def test_bad_fallback_markers(ready_db, alembic, fallback):
    markers(ready_db, alembic, fallback)
    check_unchanged(ready_db, "fallback")


@pytest.mark.parametrize("prefix", range(1, 8))
def test_fallback_only_stale_prefix(ready_db, prefix):
    markers(ready_db, None, readiness.REVISIONS[:prefix])
    check_unchanged(ready_db, "all eight")


@pytest.mark.parametrize("kind", ["missing", "zero", "tableless", "unversioned", "not_sqlite", "directory"])
def test_unready_files(tmp_path, kind):
    path = tmp_path / "unready.db"
    if kind == "zero":
        path.touch()
    elif kind == "tableless":
        with sqlite3.connect(path) as connection:
            connection.execute("VACUUM")
    elif kind == "unversioned":
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE example (id INTEGER)")
    elif kind == "not_sqlite":
        path.write_bytes(b"not a SQLite database")
    elif kind == "directory":
        path.mkdir()
        with pytest.raises(readiness.DatabaseReadinessError, match="regular file"):
            readiness.check_database_readiness(path)
        assert path.is_dir() and not list(path.iterdir())
        return
    check_unchanged(path, "Database is not ready")


@pytest.mark.parametrize("marker,column", [("alembic_version", "version_num"), ("schema_migrations", "version")])
def test_marker_view_or_malformed_table(ready_db, marker, column):
    with sqlite3.connect(ready_db) as connection:
        connection.execute(f"DROP TABLE IF EXISTS {marker}")
        connection.execute(f"CREATE VIEW {marker} AS SELECT '0007_turnover_availability' AS {column}")
    check_unchanged(ready_db, "real table")
    with sqlite3.connect(ready_db) as connection:
        connection.execute(f"DROP VIEW {marker}")
        connection.execute(f"CREATE TABLE {marker} (wrong_column)")
    check_unchanged(ready_db, "cannot read")


@pytest.mark.parametrize("defect", ["table", "view", "column", "pk", "fk", "unique", "partial_unique", "default", "expression_default"])
def test_finite_schema_faults(ready_db, defect):
    with sqlite3.connect(ready_db) as connection:
        if defect in ("table", "view"):
            connection.execute("DROP TABLE data_quality")
            if defect == "view":
                connection.execute("CREATE VIEW data_quality AS SELECT 1 AS id")
        elif defect == "column":
            connection.execute("ALTER TABLE data_quality RENAME COLUMN source TO custom_source")
        elif defect in ("unique", "partial_unique"):
            connection.execute("DROP INDEX ix_signals_signal_key")
            if defect == "partial_unique":
                connection.execute("CREATE UNIQUE INDEX ix_signals_signal_key ON signals(signal_key) WHERE id > 0")
        else:
            table = "portfolio_positions" if defect in ("pk", "fk") else "news_items"
            ddl = connection.execute("SELECT sql FROM sqlite_schema WHERE name=?", (table,)).fetchone()[0]
            if defect == "pk":
                ddl = ddl.replace("PRIMARY KEY (id),", "")
            elif defect == "fk":
                ddl = ddl.replace("FOREIGN KEY(instrument_id) REFERENCES instruments (id)", "CHECK (1=1)")
            else:
                ddl = ddl.replace("DEFAULT '[]'", "" if defect == "default" else "DEFAULT (json_array())")
            connection.execute(f"DROP TABLE {table}")
            connection.execute(ddl)
    check_unchanged(ready_db, "Database is not ready")


def test_extra_schema_is_allowed(ready_db):
    with sqlite3.connect(ready_db) as connection:
        connection.execute("ALTER TABLE data_quality ADD COLUMN custom_note TEXT")
        connection.execute("CREATE TABLE custom_audit (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE INDEX custom_source_index ON data_quality(source)")
    check_unchanged(ready_db)


def test_uri_characters_and_relative_path(ready_db, tmp_path, monkeypatch):
    # ?, * are unavailable in Windows filenames. # and % still exercise URI escaping.
    path = tmp_path / "中文 # percent%20.db"
    shutil.copy2(ready_db, path)
    monkeypatch.chdir(tmp_path)
    check_unchanged(Path(path.name))


def test_locked_database_has_bounded_read_failure(ready_db):
    before = fingerprint(ready_db)
    with sqlite3.connect(ready_db) as writer:
        writer.execute("BEGIN EXCLUSIVE")
        start = time.monotonic()
        with pytest.raises(readiness.DatabaseReadinessError, match="locked"):
            readiness.check_database_readiness(ready_db)
        assert time.monotonic() - start < 5
        writer.rollback()
    assert fingerprint(ready_db) == before


def test_read_connection_and_single_transaction(ready_db, monkeypatch):
    connect = sqlite3.connect
    statements = []
    def observe(database, **kwargs):
        assert database.endswith("?mode=ro") and kwargs["uri"] is True
        assert kwargs["timeout"] == readiness.READ_TIMEOUT_SECONDS
        connection = connect(database, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection
    monkeypatch.setattr(readiness.sqlite3, "connect", observe)
    readiness.check_database_readiness(ready_db)
    assert statements[:2] == ["PRAGMA query_only=ON", "BEGIN"]
    assert sum(statement == "BEGIN" for statement in statements) == 1
    assert all(statement.startswith(("SELECT ", "PRAGMA ", "BEGIN")) for statement in statements)


def test_unreadable_connection_fails_without_retry(ready_db, monkeypatch):
    calls = []
    def denied(*args, **kwargs):
        calls.append(args)
        raise sqlite3.OperationalError("unable to open database file")
    monkeypatch.setattr(readiness.sqlite3, "connect", denied)
    check_unchanged(ready_db, "unable to open")
    assert len(calls) == 1


def test_invalid_startup_does_not_serve(tmp_path, monkeypatch):
    path = tmp_path / "absent.db"
    monkeypatch.setattr(readiness, "DB_PATH", path)
    with pytest.raises(readiness.DatabaseReadinessError):
        with TestClient(main.app):
            pytest.fail("startup must fail before serving")
    assert not path.exists()


def test_explicit_cli_init_then_real_startup(tmp_path):
    root = Path(__file__).resolve().parents[2]
    data = tmp_path / "explicit"
    env = dict(os.environ, STOCK_DATA_DIR=str(data), STOCK_DB_PATH=str(data / "stock.db"), STOCK_RAW_DIR=str(data / "raw"), PYTHONDONTWRITEBYTECODE="1")
    env["PYTHONPATH"] = os.pathsep.join([str(root / "backend"), str(root / "backend/.deps"), *sys.path])
    initialized = subprocess.run([sys.executable, "-m", "worker.cli", "init-db"], env=env, cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert initialized.returncode == 0, initialized.stdout + initialized.stderr
    before = fingerprint(data / "stock.db")
    code = "from fastapi.testclient import TestClient; from app.main import app\nwith TestClient(app) as client: assert client.get('/api/health').json()['status']=='ok'"
    started = subprocess.run([sys.executable, "-c", code], env=env, cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert started.returncode == 0, started.stdout + started.stderr
    assert fingerprint(data / "stock.db") == before


def test_readiness_revision_constants_match_checked_in_single_chain():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "backend/alembic.ini"))
    config.set_main_option("script_location", str(root / "backend/alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [readiness.REVISIONS[-1]]
    chain = list(reversed(list(script.walk_revisions())))
    assert tuple(revision.revision for revision in chain) == readiness.REVISIONS
    assert tuple(revision.down_revision for revision in chain) == (None, *readiness.REVISIONS[:-1])


@pytest.mark.parametrize("ddl", [
    'CREATE UNIQUE INDEX "ix_ingestion_runs_request_key" ON "ingestion_runs" ("request_key") WHERE "request_key" IS NOT NULL',
    'create unique index ix_ingestion_runs_request_key on ingestion_runs(request_key) where request_key is not null',
    'CREATE\nUNIQUE INDEX "ix_ingestion_runs_request_key" ON ingestion_runs ( request_key )\nWHERE "request_key" IS NOT NULL',
])
def test_known_legacy_partial_unique_is_accepted(ready_db, ddl):
    with sqlite3.connect(ready_db) as connection:
        connection.execute("DROP INDEX ix_ingestion_runs_request_key")
        connection.execute(ddl)
    check_unchanged(ready_db)


@pytest.mark.parametrize("tail", [
    'ON ingestion_runs(request_key) WHERE request_key IS NULL',
    'ON ingestion_runs(request_key) WHERE request_key IS NOT NULL AND request_key != \'excluded\'',
    'ON ingestion_runs(request_key) WHERE request_key IS NOT NULL OR id > 0',
    'ON ingestion_runs(request_key) WHERE request_key != \'excluded\'',
    'ON ingestion_runs(request_key) WHERE id > 0 /* WHERE request_key IS NOT NULL */',
    'ON ingestion_runs(request_key) WHERE request_key = \'WHERE request_key IS NOT NULL\'',
    'ON ingestion_runs(source) WHERE request_key IS NOT NULL',
    'ON raw_payloads(source) WHERE source IS NOT NULL',
])
def test_partial_unique_spoofs_are_rejected(ready_db, tail):
    with sqlite3.connect(ready_db) as connection:
        connection.execute("DROP INDEX ix_ingestion_runs_request_key")
        connection.execute("CREATE UNIQUE INDEX ix_ingestion_runs_request_key " + tail)
    check_unchanged(ready_db, "unique identities")


@pytest.mark.parametrize("partial", [False, True])
def test_known_partial_and_full_unique_enforce_nonnull_keys(tmp_path, partial):
    path = tmp_path / "unique-semantics.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE ingestion_runs (request_key TEXT)")
        connection.execute("CREATE UNIQUE INDEX ix_ingestion_runs_request_key ON ingestion_runs(request_key)" + (" WHERE request_key IS NOT NULL" if partial else ""))
        connection.execute("INSERT INTO ingestion_runs VALUES (NULL), (NULL), ('one')")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO ingestion_runs VALUES ('one')")
        assert connection.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone() == (3,)
