import pytest

from datetime import date

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app import migrations as migrations_module
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import Event, Instrument


def test_v1_schema_has_new_tables_unique_settlements_and_sqlite_foreign_keys(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'schema.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)

    expected_tables = {
        "instruments",
        "market_bars",
        "raw_payloads",
        "ingestion_runs",
        "corporate_actions",
        "fundamental_snapshots",
        "events",
        "news_items",
        "data_quality",
        "signal_evaluations",
        "signal_settlements",
    }
    inspector = inspect(engine)
    assert expected_tables.issubset(set(inspector.get_table_names()))
    settlement_uniques = {
        tuple(constraint.get("column_names") or ())
        for constraint in inspector.get_unique_constraints("signal_settlements")
    }
    assert ("signal_id", "horizon") in settlement_uniques
    theme_columns = {column["name"] for column in inspector.get_columns("theme_groups")}
    assert {"display_name_zh", "display_description_zh", "display_category", "name_source", "name_status"}.issubset(theme_columns)

    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO market_bars "
                    "(instrument_id, trading_date, open, high, low, close, adj_close, volume, turnover, source) "
                    "VALUES (999999, '2026-09-04', 1, 1, 1, 1, 1, 1, 1, 'fixture')"
                )
            )


def _legacy_instrument_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE instruments (
                id INTEGER NOT NULL PRIMARY KEY,
                market VARCHAR(20) NOT NULL,
                symbol VARCHAR(30) NOT NULL,
                name VARCHAR(120) NOT NULL,
                instrument_type VARCHAR(20) NOT NULL,
                etf_category VARCHAR(30),
                listing_date DATE,
                is_watchlisted BOOLEAN NOT NULL DEFAULT 0,
                status VARCHAR(20) NOT NULL,
                created_at DATETIME NOT NULL,
                CONSTRAINT uq_instrument_market_symbol UNIQUE (market, symbol)
            )
            """
        )
        connection.execute(
            text(
                "INSERT INTO instruments "
                "(id, market, symbol, name, instrument_type, status, created_at) "
                "VALUES (17, 'TW', '6423', 'Legacy row', 'stock', 'active', CURRENT_TIMESTAMP)"
            )
        )
    enable_sqlite_foreign_keys(engine)
    return engine


def _assert_legacy_instrument_identity(engine):
    inspector = inspect(engine)
    unique_columns = {
        tuple(constraint.get("column_names") or ())
        for constraint in inspector.get_unique_constraints("instruments")
    }
    assert ("exchange", "symbol") in unique_columns
    assert ("market", "symbol") not in unique_columns
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT id, exchange, symbol FROM instruments WHERE symbol = '6423'")
        ).one()
        assert tuple(row) == (17, "TWSE", "6423")


@pytest.mark.parametrize("migration_path", ["alembic", "fallback"])
def test_legacy_instrument_identity_migrates_forward_without_losing_rows(
    tmp_path, monkeypatch, migration_path
):
    engine = _legacy_instrument_engine(tmp_path)

    if migration_path == "alembic":
        try:
            from alembic import command as alembic_command
        except ImportError:
            pytest.skip("Alembic is not installed in this runtime")
        assert hasattr(alembic_command, "upgrade")
    else:
        # Exercise the compatibility path explicitly, even when the test
        # environment also has the Alembic dependency installed.
        monkeypatch.setattr(
            migrations_module,
            "ALEMBIC_CONFIG_PATH",
            tmp_path / "missing-alembic.ini",
        )

    upgrade_database(engine)

    _assert_legacy_instrument_identity(engine)
    inspector = inspect(engine)
    with engine.connect() as connection:
        if migration_path == "alembic":
            assert inspector.has_table("alembic_version")
            revisions = [
                item[0]
                for item in connection.execute(
                    text("SELECT version_num FROM alembic_version ORDER BY version_num")
                )
            ]
            assert revisions == ["0006_news_json_defaults"]
            assert not inspector.has_table("schema_migrations")
        else:
            assert inspector.has_table("schema_migrations")
            versions = {
                item[0]
                for item in connection.execute(text("SELECT version FROM schema_migrations"))
            }
            assert versions == {
                "0001_schema_v1",
                "0002_instrument_exchange_key",
                "0003_backtest_run_metadata",
                "0004_product_news_themes",
                "0005_news_temporal_contract",
                "0006_news_json_defaults",
            }
            assert not inspector.has_table("alembic_version")


def test_product_migration_preserves_existing_official_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'official.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO instruments "
                "(market, exchange, symbol, name, instrument_type, is_watchlisted, status, created_at) "
                "VALUES ('TW', 'TWSE', '2330', 'Official fixture', 'stock', 0, 'active', CURRENT_TIMESTAMP)"
            )
        )
        instrument_id = connection.execute(
            text("SELECT id FROM instruments WHERE symbol = '2330'")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO events "
                "(instrument_id, event_date, event_type, title, details_json, source, data_as_of, collected_at) "
                "VALUES (:instrument_id, '2026-09-08', 'material_information', 'Official event', '{}', 'mops_material_information', '2026-09-08', CURRENT_TIMESTAMP)"
            ),
            {"instrument_id": instrument_id},
        )

    upgrade_database(engine)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM instruments WHERE symbol = '2330'")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM events WHERE title = 'Official event'")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM news_items")).scalar_one() == 0
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
