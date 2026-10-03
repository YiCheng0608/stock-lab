"""In-memory checks for both supported turnover schema upgrade paths."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app import migrations
from app.db import Base, enable_sqlite_foreign_keys
from app.models import Instrument


def _engine():
    engine = create_engine("sqlite:///:memory:")
    enable_sqlite_foreign_keys(engine)
    return engine


def _upgrade(engine, mode):
    if mode == "alembic":
        migrations.upgrade_database(engine)
    else:
        migrations._fallback_upgrade(engine)


def _legacy_rows(engine):
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Instrument(
            market="TW", exchange="TWSE", symbol="LEGACY", name="Legacy",
            instrument_type="stock", status="active",
        ))
        db.commit()
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE market_bars DROP COLUMN turnover_status")
        connection.exec_driver_sql("ALTER TABLE market_bars DROP COLUMN turnover_reason")
        for bar_id, amount in ((1, 100.0), (2, 0.0), (3, -5.0)):
            connection.exec_driver_sql(
                "INSERT INTO market_bars "
                "(id, instrument_id, trading_date, open, high, low, close, adj_close, "
                "volume, turnover, source, collected_at, is_suspended) "
                "VALUES (?, 1, ?, 100, 105, 98, 103, 103, 1000, ?, 'legacy', "
                "'2026-09-04 00:00:00', 0)",
                (bar_id, date(2026, 9, bar_id).isoformat(), amount),
            )
        connection.exec_driver_sql(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "INSERT INTO alembic_version(version_num) VALUES ('0006_news_json_defaults')"
        )


def _original_rows(engine):
    with engine.connect() as connection:
        return connection.exec_driver_sql(
            "SELECT id, instrument_id, trading_date, open, high, low, close, "
            "adj_close, volume, turnover, source FROM market_bars ORDER BY id"
        ).all()


@pytest.mark.parametrize("mode", ["alembic", "fallback"])
def test_upgrade_classifies_only_legacy_rows_and_preserves_values(mode):
    engine = _engine()
    try:
        _legacy_rows(engine)
        before = _original_rows(engine)
        _upgrade(engine, mode)
        assert _original_rows(engine) == before
        with engine.connect() as connection:
            rows = connection.exec_driver_sql(
                "SELECT id, turnover_status, turnover_reason FROM market_bars ORDER BY id"
            ).all()
            assert rows == [
                (1, "available", None),
                (2, "unknown", "legacy_zero_ambiguous"),
                (3, "unknown", "legacy_invalid"),
            ]
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE market_bars SET turnover_status='unavailable', turnover_reason='invalid' "
                "WHERE id=1"
            )
            connection.exec_driver_sql(
                "UPDATE market_bars SET turnover_status='available', turnover_reason=NULL "
                "WHERE id=2"
            )
        _upgrade(engine, mode)
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT id, turnover_status, turnover_reason FROM market_bars ORDER BY id"
            ).all() == [
                (1, "unavailable", "invalid"),
                (2, "available", None),
                (3, "unknown", "legacy_invalid"),
            ]
            if mode == "alembic":
                assert connection.exec_driver_sql(
                    "SELECT version_num FROM alembic_version"
                ).scalar() == "0008_portfolio_share_integer"
            else:
                assert connection.exec_driver_sql(
                    "SELECT count(*) FROM schema_migrations "
                    "WHERE version='0007_turnover_availability'"
                ).scalar() == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("mode", ["alembic", "fallback"])
def test_fresh_in_memory_schema_has_turnover_columns(mode):
    engine = _engine()
    try:
        _upgrade(engine, mode)
        columns = {column["name"] for column in inspect(engine).get_columns("market_bars")}
        assert {"turnover", "turnover_status", "turnover_reason"} <= columns
        _upgrade(engine, mode)
    finally:
        engine.dispose()


@pytest.mark.parametrize("mode", ["alembic", "fallback"])
def test_failed_upgrade_rolls_back_columns_and_success_marker(mode):
    engine = _engine()
    try:
        _legacy_rows(engine)
        before = _original_rows(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER block_bar_update BEFORE UPDATE ON market_bars "
                "BEGIN SELECT RAISE(ABORT, 'blocked_turnover_backfill'); END"
            )
        with pytest.raises(Exception, match="blocked_turnover_backfill"):
            _upgrade(engine, mode)
        assert _original_rows(engine) == before
        columns = {column["name"] for column in inspect(engine).get_columns("market_bars")}
        assert "turnover_status" not in columns
        assert "turnover_reason" not in columns
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar() == "0006_news_json_defaults"
            if mode == "fallback":
                assert not inspect(connection).has_table("schema_migrations")
    finally:
        engine.dispose()
