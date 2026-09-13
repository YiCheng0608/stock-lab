from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, inspect, text

from .config import ALEMBIC_CONFIG_PATH
from .news_json_defaults import ensure_news_json_server_defaults
from .settlement_identity_migration import preflight_settlement_identity, rebuild_settlement_identity
from .instrument_identity_migration import (
    check_sqlite_migration_integrity,
    preflight_instrument_identity,
    rebuild_instrument_identity,
)


_ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "instruments": {
        "exchange": "VARCHAR(20) NOT NULL DEFAULT 'TWSE'",
        "industry": "VARCHAR(120)",
    },
    "market_bars": {
        "raw_payload_id": "INTEGER REFERENCES raw_payloads(id)",
        "is_suspended": "BOOLEAN NOT NULL DEFAULT 0",
    },
    "chip_snapshots": {
        "raw_payload_id": "INTEGER REFERENCES raw_payloads(id)",
    },
    "group_daily_scores": {
        "relative_return_1d": "FLOAT",
        "relative_return_5d": "FLOAT",
        "relative_return_20d": "FLOAT",
    },
    "strategy_versions": {
        "canonical_config_snapshot": "JSON NOT NULL DEFAULT '{}'",
    },
    "signals": {
        "earliest_execution_date": "DATE",
        "execution_date": "DATE",
        "execution_price": "FLOAT",
        "data_quality": "VARCHAR(30) NOT NULL DEFAULT 'complete'",
        "rule_evidence_json": "JSON NOT NULL DEFAULT '{}'",
    },
    "signal_evaluations": {
        "execution_date": "DATE",
        "execution_price": "FLOAT",
        "adjusted_ohlc_json": "JSON",
        "corporate_action_applied": "BOOLEAN",
        "suspended": "BOOLEAN",
        "comparable": "BOOLEAN",
        "trigger_order": "VARCHAR(40)",
        "data_quality": "VARCHAR(30) NOT NULL DEFAULT 'complete'",
    },
    "signal_settlements": {
        "horizon": "INTEGER NOT NULL DEFAULT 20",
        "execution_date": "DATE",
        "execution_price": "FLOAT",
        "comparable": "BOOLEAN",
        "data_quality": "VARCHAR(30) NOT NULL DEFAULT 'complete'",
    },
    "ingestion_runs": {
        "request_key": "VARCHAR(180)",
        "data_as_of": "VARCHAR(80)",
        "metadata_json": "JSON NOT NULL DEFAULT '{}'",
        "updated_at": "DATETIME",
    },
    "theme_groups": {
        "display_name_zh": "VARCHAR(120)",
        "display_description_zh": "TEXT",
        "display_category": "VARCHAR(40)",
        "name_source": "VARCHAR(500)",
        "name_status": "VARCHAR(30) NOT NULL DEFAULT 'pending'",
    },
    "news_items": {
        "event_date": "DATE",
        "time_basis": "VARCHAR(20) NOT NULL DEFAULT 'unverified'",
        "time_precision": "VARCHAR(20) NOT NULL DEFAULT 'none'",
        "time_consistency": "VARCHAR(20) NOT NULL DEFAULT 'verified'",
        "display_time": "DATETIME",
    },
}



def _column_names(connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _has_unique_columns(connection, table_name: str, expected: tuple[str, ...]) -> bool:
    inspector = inspect(connection)
    expected_set = tuple(expected)
    for constraint in inspector.get_unique_constraints(table_name):
        if tuple(constraint.get("column_names") or ()) == expected_set:
            return True
    for index in inspector.get_indexes(table_name):
        if index.get("unique") and tuple(index.get("column_names") or ()) == expected_set:
            return True
    return False


def _ensure_request_key_index(connection) -> None:
    if not inspect(connection).has_table("ingestion_runs"):
        return
    if _has_unique_columns(connection, "ingestion_runs", ("request_key",)):
        return
    # Legacy rows have NULL request keys.  A partial unique index preserves
    # those rows while making retries/concurrent workers idempotent for the
    # non-null request key used by the official collector.
    connection.execute(
        text(
            'CREATE UNIQUE INDEX IF NOT EXISTS "ix_ingestion_runs_request_key" '
            'ON "ingestion_runs" ("request_key") WHERE "request_key" IS NOT NULL'
        )
    )


def _rebuild_instruments_if_needed(connection) -> None:
    rebuild_instrument_identity(connection)


def _rebuild_signal_settlements_if_needed(connection) -> None:
    rebuild_settlement_identity(connection)



def _fallback_upgrade_on_connection(connection) -> None:
    from . import models  # noqa: F401
    from .db import Base

    if connection.dialect.name == "sqlite":
        preflight_instrument_identity(connection)
        preflight_settlement_identity(connection)
    Base.metadata.create_all(bind=connection)
    inspector = inspect(connection)
    for table_name, columns in _ADDITIVE_COLUMNS.items():
        if not inspector.has_table(table_name):
            continue
        existing = _column_names(connection, table_name)
        for column_name, definition in columns.items():
            if column_name not in existing:
                connection.execute(
                    text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {definition}')
                )
    _rebuild_instruments_if_needed(connection)
    _ensure_request_key_index(connection)
    _rebuild_signal_settlements_if_needed(connection)
    if inspect(connection).has_table("news_items"):
        connection.execute(
            text(
                'CREATE INDEX IF NOT EXISTS "ix_news_display_id" '
                'ON "news_items" ("display_time", "id")'
            )
        )
        connection.execute(
            text(
                'CREATE INDEX IF NOT EXISTS "ix_news_event_date" '
                'ON "news_items" ("event_date")'
            )
        )
        connection.execute(
            text(
                'CREATE INDEX IF NOT EXISTS "ix_news_time_consistency" '
                'ON "news_items" ("time_consistency")'
            )
        )
        ensure_news_json_server_defaults(connection)
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version VARCHAR(64) PRIMARY KEY, applied_at DATETIME NOT NULL)"
        )
    )
    connection.execute(
        text(
            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) "
            "VALUES ('0001_schema_v1', CURRENT_TIMESTAMP)"
        )
    )
    connection.execute(
        text(
            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) "
            "VALUES ('0002_instrument_exchange_key', CURRENT_TIMESTAMP)"
        )
    )
    connection.execute(
        text(
            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) "
            "VALUES ('0003_backtest_run_metadata', CURRENT_TIMESTAMP)"
        )
    )
    connection.execute(
        text(
            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) "
            "VALUES ('0004_product_news_themes', CURRENT_TIMESTAMP)"
        )
    )
    connection.execute(
        text(
            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) "
            "VALUES ('0005_news_temporal_contract', CURRENT_TIMESTAMP)"
        )
    )
    connection.execute(
        text(
            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) "
            "VALUES ('0006_news_json_defaults', CURRENT_TIMESTAMP)"
        )
    )


def _fallback_upgrade(target_engine: Engine) -> None:
    """Upgrade with SQLAlchemy when Alembic is unavailable in the runtime.

    This path is intentionally additive so a desktop installation can open a
    legacy database without deleting or rewriting historical rows.  Normal
    deployments use the Alembic revision in ``backend/alembic/versions``.
    """

    if target_engine.dialect.name != "sqlite":
        with target_engine.begin() as connection:
            _fallback_upgrade_on_connection(connection)
        return

    # Parent-table rebuilds cannot run while SQLite foreign-key enforcement is
    # on.  A named savepoint keeps the complete compatibility upgrade atomic,
    # including SQLite DDL and schema_migrations marker writes.  The pragma is
    # toggled only outside the savepoint and restored to its original state.
    with target_engine.connect() as connection:
        connection.commit()
        original_foreign_keys = int(
            connection.exec_driver_sql("PRAGMA foreign_keys").scalar() or 0
        )
        connection.commit()
        savepoint = "fallback_upgrade"
        migration_error = None
        try:
            if original_foreign_keys:
                connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                connection.commit()
            connection.exec_driver_sql(f'SAVEPOINT "{savepoint}"')
            try:
                preflight_instrument_identity(connection)
                preflight_settlement_identity(connection)
                check_sqlite_migration_integrity(connection)
                _fallback_upgrade_on_connection(connection)
                check_sqlite_migration_integrity(connection)
                if preflight_settlement_identity(connection) != "current":
                    raise RuntimeError("cannot migrate settlements: missing current identity after fallback")
                if preflight_instrument_identity(connection) != "current":
                    raise RuntimeError("cannot migrate instruments: missing current identity after fallback")
                connection.exec_driver_sql(f'RELEASE SAVEPOINT "{savepoint}"')
                connection.commit()
            except BaseException:
                try:
                    connection.exec_driver_sql(f'ROLLBACK TO SAVEPOINT "{savepoint}"')
                finally:
                    connection.exec_driver_sql(f'RELEASE SAVEPOINT "{savepoint}"')
                connection.rollback()
                raise
        except BaseException as error:
            migration_error = error
            raise
        finally:
            try:
                if connection.in_transaction():
                    connection.rollback()
                current_foreign_keys = int(
                    connection.exec_driver_sql("PRAGMA foreign_keys").scalar() or 0
                )
                if current_foreign_keys != original_foreign_keys:
                    connection.exec_driver_sql(
                        f"PRAGMA foreign_keys={'ON' if original_foreign_keys else 'OFF'}"
                    )
                    connection.commit()
                elif connection.in_transaction():
                    connection.commit()
            except BaseException as restore_error:
                if migration_error is not None:
                    raise migration_error from restore_error
                raise



def upgrade_database(target_engine: Engine) -> None:
    """Run the checked-in Alembic migration, with a local compatibility path."""

    try:
        from alembic import command
        from alembic.config import Config
    except ImportError:
        _fallback_upgrade(target_engine)
        return

    config_path = Path(ALEMBIC_CONFIG_PATH)
    if not config_path.exists():
        _fallback_upgrade(target_engine)
        return

    config = Config(str(config_path))
    config.set_main_option("sqlalchemy.url", target_engine.url.render_as_string(hide_password=False))
    config.set_main_option("script_location", str(config_path.parent / "alembic"))
    # Reuse the configured engine so its SQLite foreign-key listener remains
    # active and tests can migrate an isolated database without touching the
    # production stock.db.
    config.attributes["connection"] = target_engine
    command.upgrade(config, "head")
