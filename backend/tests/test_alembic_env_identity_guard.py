"""Behavior lock for the instrument identity guard at the end of alembic/env.py.

The preflight that runs after the migrations reads the same revision list and refuses
first, so with the real preflight the env.py guard is unreachable. These tests replace
that preflight with a stub and drive the real env.py over no-op revision files written
under tmp_path, so only the env.py guard decides the outcome.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from app import instrument_identity_migration as identity
from app.db import Base
from app import models  # noqa: F401
from app.migration_revisions import REVISIONS

ROOT = Path(__file__).resolve().parents[2]
GUARD_MESSAGE = 'cannot migrate instruments: revision requires current identity'
UNLISTED = '9000_unlisted_fixture'
# Derived from the chain, never from INSTRUMENT_IDENTITY_REVISIONS: a mutated guard list
# must not be able to move its own expectation.
GATED = REVISIONS[1:]
REVISION_FILE = '''revision = {revision!r}
down_revision = {down_revision!r}
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
'''


class _Preflight:
    """Stands in for the instrument preflight: fixed identity state, counted calls."""

    def __init__(self, state):
        self.state = state
        self.calls = 0

    def __call__(self, connection):
        self.calls += 1
        return self.state


def _stub_preflight(monkeypatch, state):
    stub = _Preflight(state)
    # env.py imports the name again on every run, so it picks the stub up.
    monkeypatch.setattr(identity, 'preflight_instrument_identity', stub)
    return stub


def _config(connection, versions):
    cfg = Config(str(ROOT / 'backend/alembic.ini'))
    cfg.set_main_option('script_location', str(ROOT / 'backend/alembic'))
    # path_separator is the current name; version_path_separator covers alembic < 1.16.
    cfg.set_main_option('path_separator', 'os')
    cfg.set_main_option('version_path_separator', 'os')
    cfg.set_main_option('version_locations', str(versions))
    cfg.attributes['connection'] = connection
    return cfg


def _upgrade(engine, versions, target):
    with engine.connect() as connection:
        try:
            command.upgrade(_config(connection, versions), target)
        finally:
            assert not connection.in_transaction()


def _markers(engine):
    # Independent reader; a rolled back run leaves no version row (or no table).
    with closing(sqlite3.connect(engine.url.database)) as connection:
        found = connection.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name='alembic_version'").fetchone()
        if found is None:
            return []
        return [row[0] for row in connection.execute('SELECT version_num FROM alembic_version')]


@pytest.fixture()
def engine(tmp_path):
    # A current-identity schema keeps the real settlement preflight from refusing the stamp.
    engine = create_engine('sqlite:///' + str(tmp_path / 'guard.db'))
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def versions(tmp_path):
    directory = tmp_path / 'versions'
    directory.mkdir()
    for previous, revision in zip((None, *REVISIONS), REVISIONS):
        (directory / (revision + '.py')).write_text(
            REVISION_FILE.format(revision=revision, down_revision=previous), encoding='utf8')
    (directory / (UNLISTED + '.py')).write_text(
        REVISION_FILE.format(revision=UNLISTED, down_revision=REVISIONS[0]), encoding='utf8')
    return directory


def test_expected_gate_is_every_revision_after_the_first():
    assert REVISIONS[0] == '0001_schema_v1'
    assert GATED == REVISIONS[1:] and GATED
    assert UNLISTED not in REVISIONS


@pytest.mark.parametrize('state', ['legacy', 'absent'])
@pytest.mark.parametrize('revision', GATED)
def test_guard_refuses_gated_revision_without_current_identity(engine, versions, monkeypatch, revision, state):
    preflight = _stub_preflight(monkeypatch, state)
    with pytest.raises(RuntimeError) as error:
        _upgrade(engine, versions, revision)
    assert str(error.value) == GUARD_MESSAGE
    assert preflight.calls == 2  # before and after the migrations, so the guard line was reached
    assert _markers(engine) == []


@pytest.mark.parametrize('revision', GATED)
def test_guard_allows_gated_revision_with_current_identity(engine, versions, monkeypatch, revision):
    preflight = _stub_preflight(monkeypatch, 'current')
    _upgrade(engine, versions, revision)
    assert preflight.calls == 2
    assert _markers(engine) == [revision]


@pytest.mark.parametrize('revision', [REVISIONS[0], UNLISTED], ids=['0001', 'unlisted'])
def test_guard_ignores_revisions_outside_the_gated_set(engine, versions, monkeypatch, revision):
    preflight = _stub_preflight(monkeypatch, 'legacy')
    _upgrade(engine, versions, revision)
    assert preflight.calls == 2
    assert _markers(engine) == [revision]
