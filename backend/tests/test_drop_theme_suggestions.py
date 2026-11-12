"""Migration 0031 (Issue #629): the news theme suggestion tables are dropped.

Both upgrade entries are covered: Alembic and the built-in fallback used when
Alembic cannot be loaded.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest
from sqlalchemy import create_engine

from app import migration_revisions, migrations
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from worker import schedule_runs

HEAD = "0031_drop_theme_suggestions"
TABLES = ("theme_suggestions", "theme_suggestion_news")
PREVIOUS = "0030_trading_halts"
INDEXES = (
    "ix_theme_suggestions_last_news_date",
    "ix_theme_suggestion_news_suggestion_id",
    "ix_theme_suggestion_news_news_item_id",
)
# The two tables with the columns, foreign keys, unique constraints and indexes of
# revision 0014, for the fallback entry (it cannot stop at 0030 to let 0014 make them).
OLD_SCHEMA = """
CREATE TABLE theme_suggestions (
    id INTEGER NOT NULL PRIMARY KEY, theme_key VARCHAR(80) NOT NULL,
    display_name VARCHAR(80) NOT NULL, prompt_version VARCHAR(40) NOT NULL,
    aggregation_version VARCHAR(40) NOT NULL, llm_models_json JSON NOT NULL,
    news_count INTEGER NOT NULL, first_news_date DATE NOT NULL,
    last_news_date DATE NOT NULL, matched_group_id VARCHAR(80),
    status VARCHAR(30) NOT NULL, computed_at DATETIME NOT NULL,
    CONSTRAINT uq_theme_suggestion_prompt_key UNIQUE (prompt_version, theme_key)
);
CREATE INDEX ix_theme_suggestions_last_news_date
    ON theme_suggestions (last_news_date);
CREATE TABLE theme_suggestion_news (
    id INTEGER NOT NULL PRIMARY KEY,
    suggestion_id INTEGER NOT NULL REFERENCES theme_suggestions (id),
    news_item_id INTEGER NOT NULL REFERENCES news_items (id),
    news_llm_result_id INTEGER NOT NULL REFERENCES news_llm_results (id),
    theme_text VARCHAR(80) NOT NULL, reason TEXT, news_date DATE NOT NULL,
    CONSTRAINT uq_theme_suggestion_news_item UNIQUE (suggestion_id, news_item_id)
);
CREATE INDEX ix_theme_suggestion_news_suggestion_id
    ON theme_suggestion_news (suggestion_id);
CREATE INDEX ix_theme_suggestion_news_news_item_id
    ON theme_suggestion_news (news_item_id);
"""
# One row each, pointing at news item 7 and LLM result 9 (made by _add_news).
OLD_ROWS = """
INSERT INTO theme_suggestions VALUES (
    1, '液冷', '液冷', 'news_v3', 'theme_suggestion_v1', '["m"]', 1,
    '2026-10-16', '2026-10-16', NULL, 'new', '2026-10-16 10:00:00'
);
INSERT INTO theme_suggestion_news VALUES (1, 1, 7, 9, '液冷', NULL, '2026-10-16');
"""


def _add_row(connection, table, values):
    """Insert a row, filling the other NOT NULL columns by their type."""

    fill = {"INTEGER": 0, "JSON": "[]", "DATETIME": "2026-10-16 10:00:00"}
    row = {
        name: fill.get(kind.split("(")[0], "x")
        for _, name, kind, required, default, _ in connection.execute(
            f"PRAGMA table_info({table})"
        )
        if required and default is None
    }
    row.update(values)
    connection.execute(
        f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
        tuple(row.values()),
    )


def _add_news(connection):
    _add_row(connection, "news_items", {"id": 7})
    _add_row(connection, "news_llm_results", {"id": 9, "news_item_id": 7})


def _alembic_upgrade(path, revision):
    from alembic import command
    from alembic.config import Config

    config_path = migrations.ALEMBIC_CONFIG_PATH
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    config = Config(str(config_path))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path.as_posix()}")
    config.set_main_option("script_location", str(config_path.parent / "alembic"))
    config.attributes["connection"] = engine
    try:
        command.upgrade(config, revision)
    finally:
        engine.dispose()


def _indexes(connection):
    # SQLite's own indexes for unique constraints go with their table.
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        )
        if not row[0].startswith("sqlite_autoindex_")
    }


def _upgrade(path, entry, tmp_path, monkeypatch):
    if entry == "fallback":
        monkeypatch.setattr(migrations, "ALEMBIC_CONFIG_PATH", tmp_path / "absent.ini")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    try:
        upgrade_database(engine)
    finally:
        engine.dispose()


def _tables(connection):
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def _marker(connection, entry):
    if entry == "alembic":
        return connection.execute("SELECT version_num FROM alembic_version").fetchall()
    return connection.execute(
        "SELECT version FROM schema_migrations WHERE version = ?", (HEAD,)
    ).fetchall()


@pytest.mark.parametrize("entry", ["alembic", "fallback"])
def test_a_new_database_has_no_theme_suggestion_tables(tmp_path, monkeypatch, entry):
    if entry == "alembic":
        pytest.importorskip("alembic")
    path = tmp_path / f"{entry}.db"
    _upgrade(path, entry, tmp_path, monkeypatch)
    with closing(sqlite3.connect(path)) as connection:
        assert not _tables(connection) & set(TABLES)
        assert _marker(connection, entry) == [(HEAD,)]


@pytest.mark.parametrize("entry", ["alembic", "fallback"])
def test_an_older_database_loses_only_the_two_tables(tmp_path, monkeypatch, entry):
    if entry == "alembic":
        pytest.importorskip("alembic")
    path = tmp_path / f"{entry}.db"
    assert migration_revisions.REVISIONS[-2:] == (PREVIOUS, HEAD)
    if entry == "alembic":
        # The database as it stood before this change: revision 0014 itself made the tables.
        _alembic_upgrade(path, PREVIOUS)
    else:
        # The fallback entry has no way to stop at 0030: upgrade, then put the two
        # tables back as 0014 made them and undo the head marker.
        _upgrade(path, entry, tmp_path, monkeypatch)
        with closing(sqlite3.connect(path)) as connection:
            connection.executescript(OLD_SCHEMA)
            connection.execute(
                "DELETE FROM schema_migrations WHERE version = ?", (HEAD,)
            )
            connection.commit()
    with closing(sqlite3.connect(path)) as connection:
        _add_news(connection)
        connection.executescript(OLD_ROWS)
        connection.commit()
        before, indexes_before = _tables(connection), _indexes(connection)
    assert set(TABLES) <= before and set(INDEXES) <= indexes_before

    _upgrade(path, entry, tmp_path, monkeypatch)

    with closing(sqlite3.connect(path)) as connection:
        assert _tables(connection) == before - set(TABLES)
        assert _indexes(connection) == indexes_before - set(INDEXES)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert _marker(connection, entry) == [(HEAD,)]
        # The news rows the suggestions pointed at are untouched.
        assert connection.execute("SELECT id FROM news_items").fetchall() == [(7,)]
        assert connection.execute(
            "SELECT id, news_item_id FROM news_llm_results"
        ).fetchall() == [(9, 7)]


def test_the_fallback_drops_the_tables_only_once(tmp_path, monkeypatch):
    path = tmp_path / "fallback.db"
    _upgrade(path, "fallback", tmp_path, monkeypatch)
    # After the 0031 marker a table of that name is no longer this migration's to drop.
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE theme_suggestions (id INTEGER PRIMARY KEY)")
        connection.commit()

    _upgrade(path, "fallback", tmp_path, monkeypatch)

    with closing(sqlite3.connect(path)) as connection:
        assert "theme_suggestions" in _tables(connection)


def test_the_daily_job_has_no_theme_suggestion_step():
    assert "theme_suggestions" not in schedule_runs.DAILY_STEPS
    assert "theme_suggestions" not in schedule_runs.STEP_REQUIRES


def test_the_api_and_the_cli_command_are_gone(monkeypatch, capsys):
    from app.api import router
    from worker import cli

    paths = {route.path for route in router.routes}
    assert not any("theme-suggestions" in path for path in paths)
    monkeypatch.setattr("sys.argv", ["worker.cli", "theme-suggestions"])
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 2
    assert "invalid choice: 'theme-suggestions'" in capsys.readouterr().err
