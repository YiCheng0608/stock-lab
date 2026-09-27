from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import Base  # noqa: E402
from app import models  # noqa: E402,F401
from app.settlement_identity_migration import preflight_settlement_identity  # noqa: E402
from app.instrument_identity_migration import (  # noqa: E402
    check_sqlite_migration_integrity,
    preflight_instrument_identity,
)


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _run_sqlite_migrations(connection) -> None:
    if connection.in_transaction():
        raise RuntimeError(
            "Alembic SQLite migration requires an inactive caller connection; "
            "refusing to commit or alter its transaction"
        )
    if connection.dialect.name != "sqlite":
        raise RuntimeError("internal error: SQLite migration called for non-SQLite connection")
    original_foreign_keys = int(connection.exec_driver_sql("PRAGMA foreign_keys").scalar() or 0)
    connection.commit()
    migration_error = None
    try:
        # Rebuilds run with FK enforcement off, but whole-run FK checks below
        # reject violations before any schema/marker transaction can commit.
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        # BEGIN is issued through the driver before MigrationContext is
        # configured, so Alembic treats it as an external transaction and its
        # revision marker stays inside this same rollback boundary.
        connection.exec_driver_sql("BEGIN")
        preflight_instrument_identity(connection)
        preflight_settlement_identity(connection)
        check_sqlite_migration_integrity(connection)
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            transactional_ddl=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        check_sqlite_migration_integrity(connection)
        preflight_settlement_identity(connection)
        identity_state = preflight_instrument_identity(connection)
        identity_revisions = {
            "0002_instrument_exchange_key", "0003_backtest_run_metadata",
            "0004_product_news_themes", "0005_news_temporal_contract",
            "0006_news_json_defaults",
            "0007_turnover_availability",
        }
        if identity_revisions.intersection(context.get_context().get_current_heads()) and identity_state != "current":
            raise RuntimeError("cannot migrate instruments: revision requires current identity")
        connection.commit()
    except BaseException as error:
        migration_error = error
        connection.rollback()
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
                # The PRAGMA read above can autobegin a SQLAlchemy transaction.
                # Active caller transactions were rejected at entry, so this is
                # owned by the migration runner and can be closed here.
                connection.commit()
        except BaseException as restore_error:
            if migration_error is not None:
                raise migration_error from restore_error
            raise



def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is None:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
    if hasattr(connectable, "connect"):
        with connectable.connect() as connection:
            if connection.dialect.name == "sqlite":
                _run_sqlite_migrations(connection)
            else:
                context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
                with context.begin_transaction():
                    context.run_migrations()
                connection.commit()
    else:
        if connectable.dialect.name == "sqlite":
            _run_sqlite_migrations(connectable)
        else:
            context.configure(connection=connectable, target_metadata=target_metadata, compare_type=True)
            with context.begin_transaction():
                context.run_migrations()
            connectable.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
