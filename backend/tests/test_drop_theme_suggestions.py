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
# The two tables as 0014 made them, with one row each.
OLD_SCHEMA = """
CREATE TABLE theme_suggestions (
    id INTEGER PRIMARY KEY, theme_key VARCHAR(80) NOT NULL,
    display_name VARCHAR(80) NOT NULL, prompt_version VARCHAR(40) NOT NULL,
    news_count INTEGER NOT NULL
);
CREATE TABLE theme_suggestion_news (
    id INTEGER PRIMARY KEY,
    suggestion_id INTEGER NOT NULL REFERENCES theme_suggestions(id),
    theme_text VARCHAR(80) NOT NULL
);
INSERT INTO theme_suggestions VALUES (1, '液冷', '液冷', 'news_v3', 1);
INSERT INTO theme_suggestion_news VALUES (1, 1, '液冷');
"""


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
    _upgrade(path, entry, tmp_path, monkeypatch)
    # Put the database back to 0030: the two tables with rows, the head marker undone.
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(OLD_SCHEMA)
        if entry == "alembic":
            connection.execute(
                "UPDATE alembic_version SET version_num = ?",
                (migration_revisions.REVISIONS[-2],),
            )
        else:
            connection.execute(
                "DELETE FROM schema_migrations WHERE version = ?", (HEAD,)
            )
        connection.commit()
        before = _tables(connection)
    assert set(TABLES) <= before

    _upgrade(path, entry, tmp_path, monkeypatch)

    with closing(sqlite3.connect(path)) as connection:
        assert _tables(connection) == before - set(TABLES)
        assert _marker(connection, entry) == [(HEAD,)]


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
