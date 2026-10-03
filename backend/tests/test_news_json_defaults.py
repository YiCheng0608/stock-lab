"""Regression tests for the 0006 NewsItem JSON server-default repair."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app import migrations as migrations_module
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.news_json_defaults import ensure_news_json_server_defaults


REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "backend" / "alembic.ini"
OLD_REVISION = "0005_news_temporal_contract"
NEW_REVISION = "0006_news_json_defaults"
CURRENT_HEAD = "0008_portfolio_share_integer"


def _normalize_default(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    while value.startswith("(") and value.endswith(")"):
        value = value[1:-1].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return value.replace("''", "'")


def _old_005_engine(
    tmp_path: Path, *, foreign_keys: int = 1, filename: str = "old-005.db"
) -> Engine:
    engine = create_engine(f"sqlite:///{(tmp_path / filename).as_posix()}")
    with engine.connect() as connection:
        connection.exec_driver_sql(f"PRAGMA foreign_keys={foreign_keys}")
        connection.commit()
        connection.exec_driver_sql(
            "CREATE TABLE alembic_version "
            "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE instruments "
            "(id INTEGER NOT NULL PRIMARY KEY, market VARCHAR(20) NOT NULL, "
            "exchange VARCHAR(20) NOT NULL DEFAULT 'TWSE', symbol VARCHAR(30) NOT NULL, "
            "name VARCHAR(120) NOT NULL, instrument_type VARCHAR(20) NOT NULL, "
            "etf_category VARCHAR(30), industry VARCHAR(120), listing_date DATE, "
            "is_watchlisted BOOLEAN NOT NULL, status VARCHAR(20) NOT NULL, "
            "created_at DATETIME NOT NULL, "
            "CONSTRAINT uq_instrument_exchange_symbol UNIQUE(exchange, symbol))"
        )
        # Empty prerequisites for the fixture's existing 0005 identity claim.
        connection.exec_driver_sql("CREATE TABLE signals (id INTEGER NOT NULL PRIMARY KEY)")
        connection.exec_driver_sql(
            """CREATE TABLE signal_settlements (
id INTEGER NOT NULL PRIMARY KEY, signal_id INTEGER NOT NULL,
horizon INTEGER NOT NULL DEFAULT 20, settlement_date DATE NOT NULL,
final_status VARCHAR(80), first_trigger VARCHAR(120), return_or_risk FLOAT,
incomparable_reason TEXT, source VARCHAR(500), data_time VARCHAR(80),
execution_date DATE, execution_price FLOAT, comparable BOOLEAN,
data_quality VARCHAR(30) NOT NULL DEFAULT 'complete',
CONSTRAINT uq_signal_settlement_horizon UNIQUE(signal_id,horizon),
FOREIGN KEY(signal_id) REFERENCES signals(id))"""
        )
        connection.exec_driver_sql(
            "CREATE TABLE events "
            "(id INTEGER NOT NULL PRIMARY KEY, instrument_id INTEGER, "
            "FOREIGN KEY(instrument_id) REFERENCES instruments(id))"
        )
        connection.exec_driver_sql(
            "CREATE TABLE news_items ("
            "id INTEGER NOT NULL PRIMARY KEY, "
            "canonical_key VARCHAR(300) NOT NULL, "
            "source_name VARCHAR(120) NOT NULL, "
            "title VARCHAR(300) NOT NULL, "
            "collected_at DATETIME NOT NULL, "
            "symbols_json JSON NOT NULL, "
            "theme_ids_json JSON NOT NULL, "
            "custom_note TEXT NOT NULL DEFAULT 'REFERENCES news_items(id)', "
            "event_id INTEGER, "
            "supersedes_id INTEGER, "
            "CONSTRAINT uq_news_canonical_key UNIQUE(canonical_key), "
            "FOREIGN KEY(event_id) REFERENCES events(id), "
            "FOREIGN KEY(supersedes_id) REFERENCES news_items(id)"
            ")"
        )
        connection.exec_driver_sql(
            "CREATE INDEX custom_news_title ON news_items(title, id)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE news_audit (id INTEGER PRIMARY KEY, news_id INTEGER, note TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TRIGGER custom_news_audit AFTER UPDATE OF title ON news_items "
            "BEGIN INSERT INTO news_audit(news_id, note) VALUES (NEW.id, NEW.title); END"
        )
        connection.exec_driver_sql(
            "INSERT INTO instruments "
            "(id, market, exchange, symbol, name, instrument_type, is_watchlisted, status, created_at) "
            "VALUES (1, 'TW', 'TWSE', '2330', 'fixture', 'stock', 0, 'active', '2026-09-10')"
        )
        connection.exec_driver_sql("INSERT INTO events(id, instrument_id) VALUES (1, 1)")
        connection.exec_driver_sql(
            "INSERT INTO news_items "
            "(id, canonical_key, source_name, title, collected_at, symbols_json, "
            "theme_ids_json, custom_note, event_id, supersedes_id) "
            "VALUES (1, 'old:1', 'fixture', 'first', '2026-09-10 08:00:00', "
            "x'5B313233305D', x'5B34325D', 'preserve-this', 1, NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO news_items "
            "(id, canonical_key, source_name, title, collected_at, symbols_json, "
            "theme_ids_json, custom_note, event_id, supersedes_id) "
            "VALUES (2, 'old:2', 'fixture', 'second', '2026-09-10 08:01:00', "
            "x'5B373738385D', x'5B395D', 'preserve-this-too', 1, 1)"
        )
        connection.exec_driver_sql(
            f"INSERT INTO alembic_version(version_num) VALUES ('{OLD_REVISION}')"
        )
        connection.commit()
    return engine


def _alembic_config(engine: Engine) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str((REPO_ROOT / "backend" / "alembic").as_posix()))
    config.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False))
    config.attributes["connection"] = engine
    return config


def _news_signature(connection) -> tuple[Any, ...]:
    objects = connection.execute(
        text(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE (tbl_name = 'news_items' OR name IN ('news_items', 'news_audit')) "
            "AND sql IS NOT NULL ORDER BY type, name"
        )
    ).all()
    rows = connection.exec_driver_sql(
        "SELECT id, hex(symbols_json), hex(theme_ids_json), custom_note, "
        "event_id, supersedes_id FROM news_items ORDER BY id"
    ).all()
    return tuple(objects), tuple(rows)


def _assert_json_defaults(connection) -> None:
    columns = {
        column["name"]: _normalize_default(column.get("default"))
        for column in inspect(connection).get_columns("news_items")
    }
    assert columns["symbols_json"] == "[]"
    assert columns["theme_ids_json"] == "[]"


@pytest.mark.parametrize("migration_path", ["alembic", "fallback"])
@pytest.mark.parametrize("foreign_keys", [0, 1])
def test_old_005_repair_preserves_bytes_self_fk_custom_objects_and_is_idempotent(
    tmp_path, monkeypatch, migration_path, foreign_keys
):
    engine = _old_005_engine(tmp_path, foreign_keys=foreign_keys)
    if migration_path == "fallback":
        monkeypatch.setattr(
            migrations_module,
            "ALEMBIC_CONFIG_PATH",
            tmp_path / "missing-alembic.ini",
        )

    with engine.connect() as connection:
        before_rows = connection.exec_driver_sql(
            "SELECT id, hex(symbols_json), hex(theme_ids_json), custom_note, "
            "event_id, supersedes_id FROM news_items ORDER BY id"
        ).all()

    upgrade_database(engine)
    with engine.connect() as connection:
        _assert_json_defaults(connection)
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == foreign_keys
        assert connection.exec_driver_sql(
            "SELECT id, hex(symbols_json), hex(theme_ids_json), custom_note, "
            "event_id, supersedes_id FROM news_items ORDER BY id"
        ).all() == before_rows
        assert connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'custom_news_title'"
        ).scalar_one() == "custom_news_title"
        assert connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name = 'custom_news_audit'"
        ).scalar_one() == "custom_news_audit"
        custom_defaults = {
            column["name"]: _normalize_default(column.get("default"))
            for column in inspect(connection).get_columns("news_items")
        }
        assert custom_defaults["custom_note"] == "REFERENCES news_items(id)"

        connection.execute(text("UPDATE news_items SET title = 'changed' WHERE id = 1"))
        connection.commit()
        assert connection.exec_driver_sql(
            "SELECT news_id, note FROM news_audit"
        ).all() == [(1, "changed")]

        connection.execute(
            text(
                "INSERT INTO news_items "
                "(canonical_key, source_name, title, collected_at) "
                "VALUES ('omitted:both', 'fixture', 'omitted', '2026-09-10 09:00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO news_items "
                "(canonical_key, source_name, title, collected_at, symbols_json) "
                "VALUES ('omitted:theme', 'fixture', 'omitted', '2026-09-10 09:01:00', '[]')"
            )
        )
        connection.commit()
        assert connection.exec_driver_sql(
            "SELECT symbols_json, theme_ids_json FROM news_items "
            "WHERE canonical_key LIKE 'omitted:%' ORDER BY id"
        ).all() == [("[]", "[]"), ("[]", "[]")]

        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO news_items "
                    "(canonical_key, source_name, title, collected_at) "
                    "VALUES ('old:1', 'fixture', 'duplicate', '2026-09-10 09:02:00')"
                )
            )
        connection.rollback()
        if foreign_keys:
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO news_items "
                        "(canonical_key, source_name, title, collected_at, event_id) "
                        "VALUES ('bad:fk', 'fixture', 'bad', '2026-09-10 09:03:00', 999)"
                    )
                )
            connection.rollback()
        first_signature = _news_signature(connection)

    upgrade_database(engine)
    with engine.connect() as connection:
        assert _news_signature(connection) == first_signature
        _assert_json_defaults(connection)
        if migration_path == "alembic":
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == CURRENT_HEAD
        else:
            versions = {
                row[0]
                for row in connection.execute(text("SELECT version FROM schema_migrations"))
            }
            assert NEW_REVISION in versions
    engine.dispose()


@pytest.mark.parametrize("migration_path", ["alembic", "fallback"])
@pytest.mark.parametrize("foreign_keys", [0, 1])
def test_fresh_schema_has_json_server_defaults_and_new_head(
    tmp_path, monkeypatch, migration_path, foreign_keys
):
    engine = create_engine(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}")
    with engine.connect() as connection:
        connection.exec_driver_sql(f"PRAGMA foreign_keys={foreign_keys}")
        connection.commit()
    if migration_path == "fallback":
        monkeypatch.setattr(
            migrations_module,
            "ALEMBIC_CONFIG_PATH",
            tmp_path / "missing-alembic.ini",
        )
    upgrade_database(engine)
    with engine.connect() as connection:
        _assert_json_defaults(connection)
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == foreign_keys
        connection.execute(
            text(
                "INSERT INTO news_items "
                "(canonical_key, source_name, title, collected_at) "
                "VALUES ('fresh:both', 'fixture', 'fresh', '2026-09-10 10:00:00')"
            )
        )
        connection.commit()
        assert connection.exec_driver_sql(
            "SELECT symbols_json, theme_ids_json FROM news_items"
        ).all() == [("[]", "[]")]
        if migration_path == "alembic":
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == CURRENT_HEAD
        else:
            assert connection.execute(
                text("SELECT version FROM schema_migrations WHERE version = :version"),
                {"version": NEW_REVISION},
            ).scalar_one() == NEW_REVISION
    engine.dispose()


@pytest.mark.parametrize("migration_path", ["alembic", "fallback"])
@pytest.mark.parametrize("foreign_keys", [0, 1])
def test_fresh_failure_has_no_half_created_schema(tmp_path, monkeypatch, migration_path, foreign_keys):
    engine = create_engine(f"sqlite:///{(tmp_path / 'fresh-failure.db').as_posix()}")
    with engine.connect() as connection:
        connection.exec_driver_sql(f"PRAGMA foreign_keys={foreign_keys}")
        connection.commit()
    if migration_path == "fallback":
        monkeypatch.setattr(
            migrations_module,
            "ALEMBIC_CONFIG_PATH",
            tmp_path / "missing-alembic.ini",
        )
        def fail_before_repair(connection, **kwargs):
            raise RuntimeError("injected fresh failure")
        monkeypatch.setattr(migrations_module, "ensure_news_json_server_defaults", fail_before_repair)
    else:
        import app.news_json_defaults as news_json_defaults
        def fail_before_repair(connection, **kwargs):
            raise RuntimeError("injected fresh failure")
        monkeypatch.setattr(news_json_defaults, "ensure_news_json_server_defaults", fail_before_repair)

    with pytest.raises(RuntimeError, match="injected fresh failure"):
        upgrade_database(engine)
    with engine.connect() as connection:
        assert inspect(connection).get_table_names() == []
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == foreign_keys
    engine.dispose()


@pytest.mark.parametrize("foreign_keys", [0, 1])
def test_alembic_external_connection_is_atomic_reusable_and_preserves_fk_mode(
    tmp_path, foreign_keys
):
    engine = _old_005_engine(
        tmp_path, foreign_keys=foreign_keys, filename="external-connection.db"
    )
    with engine.connect() as connection:
        config = _alembic_config(engine)
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        assert connection.in_transaction() is False
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == foreign_keys
        connection.rollback()

        second_config = _alembic_config(engine)
        second_config.attributes["connection"] = connection
        command.upgrade(second_config, "head")
        assert connection.in_transaction() is False
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == foreign_keys
        connection.rollback()

    active_engine = _old_005_engine(
        tmp_path, foreign_keys=foreign_keys, filename="active-connection.db"
    )
    with active_engine.connect() as connection:
        connection.exec_driver_sql("BEGIN")
        config = _alembic_config(active_engine)
        config.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="inactive caller connection"):
            command.upgrade(config, "head")
        assert connection.in_transaction() is True
        connection.rollback()
    active_engine.dispose()
    engine.dispose()


@pytest.mark.parametrize("migration_path", ["alembic", "fallback"])
def test_failed_repair_rolls_back_schema_rows_revision_and_markers_then_retries(
    tmp_path, monkeypatch, migration_path
):
    engine = _old_005_engine(tmp_path, foreign_keys=1)
    if migration_path == "fallback":
        monkeypatch.setattr(
            migrations_module,
            "ALEMBIC_CONFIG_PATH",
            tmp_path / "missing-alembic.ini",
        )
        with engine.connect() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE schema_migrations "
                "(version VARCHAR(64) PRIMARY KEY, applied_at DATETIME NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO schema_migrations VALUES "
                "('0005_news_temporal_contract', '2026-09-10')"
            )
            connection.exec_driver_sql(
                "CREATE TRIGGER block_schema_marker BEFORE INSERT ON schema_migrations "
                "WHEN NEW.version = '0006_news_json_defaults' "
                "BEGIN SELECT RAISE(ABORT, 'marker SQL failure'); END"
            )
            connection.commit()
    else:
        with engine.connect() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER block_alembic_marker BEFORE UPDATE ON alembic_version "
                "WHEN NEW.version_num = '0006_news_json_defaults' "
                "BEGIN SELECT RAISE(ABORT, 'marker SQL failure'); END"
            )
            connection.commit()

    with engine.connect() as connection:
        before = _news_signature(connection)
        before_objects = connection.execute(
            text("SELECT type, name, sql FROM sqlite_master ORDER BY type, name")
        ).all()
        before_markers = {
            table: connection.execute(text(f"SELECT * FROM {table} ORDER BY 1")).all()
            for table in ("alembic_version", "schema_migrations")
            if inspect(connection).has_table(table)
        }

    with pytest.raises(Exception, match="marker SQL failure"):
        upgrade_database(engine)
    with engine.connect() as connection:
        assert _news_signature(connection) == before
        assert connection.execute(
            text("SELECT type, name, sql FROM sqlite_master ORDER BY type, name")
        ).all() == before_objects
        after_markers = {
            table: connection.execute(text(f"SELECT * FROM {table} ORDER BY 1")).all()
            for table in ("alembic_version", "schema_migrations")
            if inspect(connection).has_table(table)
        }
        assert after_markers == before_markers
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1

    with engine.connect() as connection:
        if migration_path == "fallback":
            connection.exec_driver_sql("DROP TRIGGER block_schema_marker")
        else:
            connection.exec_driver_sql("DROP TRIGGER block_alembic_marker")
        connection.commit()
    if migration_path == "fallback":
        monkeypatch.setattr(
            migrations_module,
            "ALEMBIC_CONFIG_PATH",
            tmp_path / "missing-alembic.ini",
        )
    upgrade_database(engine)
    with engine.connect() as connection:
        _assert_json_defaults(connection)
    engine.dispose()


def test_custom_view_and_autoincrement_are_rejected_before_mutation(tmp_path):
    engine = _old_005_engine(tmp_path, foreign_keys=1)
    with engine.connect() as connection:
        connection.exec_driver_sql(
            "CREATE VIEW news_items_view AS SELECT id, title FROM news_items"
        )
        connection.commit()
        before = _news_signature(connection)
        with pytest.raises(RuntimeError, match="dependent view"):
            ensure_news_json_server_defaults(connection)
        assert _news_signature(connection) == before
    engine.dispose()

    external_engine = _old_005_engine(tmp_path, foreign_keys=1, filename="external.db")
    with external_engine.connect() as connection:
        connection.exec_driver_sql("CREATE TABLE aux(id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TRIGGER aux_news_dependency AFTER INSERT ON aux "
            "BEGIN UPDATE news_items SET title = title WHERE id = NEW.id; END"
        )
        connection.commit()
        before = _news_signature(connection)
        with pytest.raises(RuntimeError, match="external trigger"):
            ensure_news_json_server_defaults(connection)
        assert _news_signature(connection) == before
    external_engine.dispose()

    auto_engine = create_engine(f"sqlite:///{(tmp_path / 'auto.db').as_posix()}")
    with auto_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE news_items (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "symbols_json JSON NOT NULL, theme_ids_json JSON NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO news_items(id, symbols_json, theme_ids_json) VALUES (100, x'5B5D', x'5B5D')"
        )
        connection.exec_driver_sql("DELETE FROM news_items WHERE id = 100")
    with auto_engine.connect() as connection:
        before_sql = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE name = 'news_items'"
        ).scalar_one()
        with pytest.raises(RuntimeError, match="AUTOINCREMENT"):
            ensure_news_json_server_defaults(connection)
        assert connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE name = 'news_items'"
        ).scalar_one() == before_sql
        assert connection.exec_driver_sql(
            "SELECT seq FROM sqlite_sequence WHERE name = 'news_items'"
        ).scalar_one() == 100
    auto_engine.dispose()


def test_actual_0004_fixture_reaches_new_head_without_changing_json_defaults(tmp_path, monkeypatch):
    from test_migration_recovery import _load_fixed_fixture

    for migration_path in ("alembic", "fallback"):
        database = tmp_path / f"fixture-{migration_path}.db"
        _load_fixed_fixture(database)
        engine = create_engine(f"sqlite:///{database.as_posix()}")
        enable_sqlite_foreign_keys(engine)
        if migration_path == "fallback":
            monkeypatch.setattr(
                migrations_module,
                "ALEMBIC_CONFIG_PATH",
                tmp_path / f"missing-{migration_path}.ini",
            )
        upgrade_database(engine)
        with engine.connect() as connection:
            _assert_json_defaults(connection)
            if migration_path == "alembic":
                assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == CURRENT_HEAD
            else:
                assert connection.execute(
                    text("SELECT version FROM schema_migrations WHERE version = :version"),
                    {"version": NEW_REVISION},
                ).scalar_one() == NEW_REVISION
        engine.dispose()
