from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import Engine, inspect, text

from .config import ALEMBIC_CONFIG_PATH
from .domain import (
    INSTITUTIONAL_FLOW_FORMULA_V1,
    INSTITUTIONAL_FLOW_FORMULA_V2,
    INSTITUTIONAL_FLOW_FORMULAS,
)
from .news_json_defaults import ensure_news_json_server_defaults
from .portfolio_share_migration import ensure_portfolio_share_integer
from .settlement_identity_migration import (
    preflight_settlement_identity,
    rebuild_settlement_identity,
)
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
        "turnover_status": "VARCHAR(20) NOT NULL DEFAULT 'unknown'",
        "turnover_reason": "VARCHAR(40)",
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
        if (
            index.get("unique")
            and tuple(index.get("column_names") or ()) == expected_set
        ):
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


STRATEGY_FORMULA_REVISION = "0009_strategy_formula_version"
UNCLASSIFIED_FORMULA_PREFIX = "unclassified/"
_STRATEGY_TABLE = "strategy_versions"
_STRATEGY_SCRATCH = "strategy_versions__formula_rebuild"
# Canonical snapshots shipped before the v2 institutional-flow formula
# (backend/app/domain.py at 7d9fa0e^, identical to the reviewed baseline).  The
# key is the SHA-256 of json.dumps(snapshot, sort_keys=True, separators=(",", ":")).
# The list is closed: undeclared content that is not one of these stays
# unclassified instead of being guessed as v1.
_PRE_V2_CANONICAL_DIGESTS = {
    "a68f4f98f319e387e4de71c37e4fc16c225b4406c20a189f7bfdc1515e84b7cd": (
        "breakout_v1",
        "1.0.0",
    ),
    "03998a93820a3c132110d41e2496f5a94a8a7f556774cb80be23e549d4788eff": (
        "pullback_v1",
        "1.0.0",
    ),
    "36cd82a287b2b8878c2b6efa165493ccf86b861e59dc35ffd858871c8f5c694e": (
        "hot_group_v1",
        "1.0.0",
    ),
}
_STRATEGY_LEGACY_COLUMNS = {
    "id",
    "name",
    "version",
    "kind",
    "config_json",
    "active",
    "created_at",
}
_STRATEGY_REBUILD_DDL = (
    f'CREATE TABLE "{_STRATEGY_SCRATCH}" ('
    "id INTEGER NOT NULL, "
    "name VARCHAR(60) NOT NULL, "
    "version VARCHAR(30) NOT NULL, "
    "formula_version VARCHAR(80) DEFAULT 'unclassified/unspecified' NOT NULL, "
    "kind VARCHAR(30) NOT NULL, "
    "config_json JSON NOT NULL, "
    "canonical_config_snapshot JSON DEFAULT '{}' NOT NULL, "
    "active BOOLEAN NOT NULL, "
    "created_at DATETIME NOT NULL, "
    "PRIMARY KEY (id), "
    "CONSTRAINT uq_strategy_version UNIQUE (name, version, formula_version))"
)


def _strategy_error(reason: str) -> RuntimeError:
    return RuntimeError(f"cannot migrate strategy_versions: {reason}")


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _stored_json(value):
    """Parse a stored JSON column; ``(False, None)`` when it is not valid JSON."""

    if value is None:
        return False, None
    try:
        return True, json.loads(value)
    except (TypeError, ValueError):
        return False, None


def _declared_formulas(snapshot: dict) -> list:
    """Formula identities a snapshot declares, from the two known locations."""

    declared = []
    confirmations = snapshot.get("confirmations")
    flow = (
        confirmations.get("institutional_flow")
        if isinstance(confirmations, dict)
        else None
    )
    if isinstance(flow, dict) and "formula_version" in flow:
        declared.append(flow["formula_version"])
    components = snapshot.get("components")
    flow = (
        components.get("institutional_flow") if isinstance(components, dict) else None
    )
    formula = flow.get("formula") if isinstance(flow, dict) else None
    if isinstance(formula, dict) and "formula_version" in formula:
        declared.append(formula["formula_version"])
    return declared


def classify_strategy_formula(
    name, version, config_json, canonical_config_snapshot
) -> str:
    """Return a stored row's formula identity, or a named ``unclassified/<reason>``.

    Known formula values are taken from the snapshot itself; a snapshot without
    one is v1 only when it is byte-for-byte (canonical JSON) a pre-v2 canonical
    snapshot under its own name and version.  Nothing else is guessed.
    """

    config_ok, config = _stored_json(config_json)
    snapshot_ok, snapshot = _stored_json(canonical_config_snapshot)
    if not config_ok or not snapshot_ok:
        return UNCLASSIFIED_FORMULA_PREFIX + "invalid_json"
    if not snapshot:
        return UNCLASSIFIED_FORMULA_PREFIX + "empty_snapshot"
    if not isinstance(snapshot, dict) or not isinstance(config, dict):
        return UNCLASSIFIED_FORMULA_PREFIX + "invalid_json"
    if _canonical_json(config) != _canonical_json(snapshot):
        return UNCLASSIFIED_FORMULA_PREFIX + "config_snapshot_mismatch"
    declared = _declared_formulas(snapshot)
    if declared:
        first = declared[0]
        if (
            isinstance(first, str)
            and first in INSTITUTIONAL_FLOW_FORMULAS
            and all(isinstance(value, str) and value == first for value in declared)
        ):
            return first
        return UNCLASSIFIED_FORMULA_PREFIX + "unknown_formula_version"
    digest = hashlib.sha256(_canonical_json(snapshot).encode("utf-8")).hexdigest()
    if _PRE_V2_CANONICAL_DIGESTS.get(digest) == (name, version):
        return INSTITUTIONAL_FLOW_FORMULA_V1
    return UNCLASSIFIED_FORMULA_PREFIX + "unrecognized_snapshot"


def _strategy_formula_state(connection) -> str:
    """Read-only gate: ``absent``, ``legacy`` (unique name+version) or ``current``."""

    if any(
        name.lower() == _STRATEGY_TABLE or name.lower().startswith(_STRATEGY_SCRATCH)
        for (name,) in connection.exec_driver_sql("SELECT name FROM temp.sqlite_schema")
    ):
        raise _strategy_error("unsupported TEMP shadow object")
    objects = connection.exec_driver_sql(
        "SELECT type, name FROM main.sqlite_schema"
    ).all()
    if any(name.lower().startswith(_STRATEGY_SCRATCH) for _, name in objects):
        raise _strategy_error("occupied scratch object; manual recovery required")
    table = next(
        (kind for kind, name in objects if name.lower() == _STRATEGY_TABLE), None
    )
    if table is None:
        return "absent"
    if table != "table":
        raise _strategy_error(f"strategy_versions is a {table}, not a table")
    columns = {
        row[1]
        for row in connection.exec_driver_sql(
            f'PRAGMA main.table_xinfo("{_STRATEGY_TABLE}")'
        )
    }
    keys = set()
    for index in connection.exec_driver_sql(
        f'PRAGMA main.index_list("{_STRATEGY_TABLE}")'
    ):
        if not index[2]:
            continue
        parts = [
            row
            for row in connection.exec_driver_sql(
                f'PRAGMA main.index_xinfo("{index[1]}")'
            )
            if row[5]
        ]
        if index[4] or any(row[2] is None for row in parts):
            raise _strategy_error("partial or expression unique index")
        keys.add(tuple(row[2] for row in parts))
    identity = {
        key for key in keys if {"name", "version", "formula_version"}.intersection(key)
    }
    if "formula_version" in columns:
        if identity != {("name", "version", "formula_version")}:
            raise _strategy_error(
                "formula_version exists but the unique identity is not (name, version, formula_version)"
            )
        return "current"
    if identity != {("name", "version")}:
        raise _strategy_error("legacy table lacks the unique identity (name, version)")
    if not _STRATEGY_LEGACY_COLUMNS.issubset(
        columns
    ) or columns - _STRATEGY_LEGACY_COLUMNS - {"canonical_config_snapshot"}:
        raise _strategy_error("unsupported legacy columns")
    for kind, name, owner, body in connection.exec_driver_sql(
        "SELECT type, name, tbl_name, sql FROM main.sqlite_schema WHERE type IN ('trigger', 'view')"
    ):
        if owner.lower() == _STRATEGY_TABLE or _STRATEGY_TABLE in (body or "").lower():
            raise _strategy_error(f"unsupported dependent {kind} {name}")
    return "legacy"


SCHEDULE_RUNS_REVISION = "0011_schedule_runs"


def ensure_strategy_formula_version(connection) -> bool:
    """Add ``strategy_versions.formula_version`` and widen the unique identity.

    Every legacy row is kept with its id, version, config and snapshot untouched;
    only the new column is filled (a known formula, or ``unclassified/<reason>``)
    and rows that are not the current v2 formula are deactivated.  Returns False
    when there is nothing to do, so a repeat run changes nothing.  SQLite only
    (the application database); the caller owns the transaction, the marker row
    and turning ``PRAGMA foreign_keys`` off, as for the other table rebuilds.
    """

    if connection.dialect.name != "sqlite":
        return False
    if _strategy_formula_state(connection) != "legacy":
        return False
    if int(connection.exec_driver_sql("PRAGMA foreign_keys").scalar() or 0):
        raise _strategy_error(
            "requires PRAGMA foreign_keys=OFF, owned by the migration runner"
        )
    columns = {
        row[1]
        for row in connection.exec_driver_sql(
            f'PRAGMA main.table_xinfo("{_STRATEGY_TABLE}")'
        )
    }
    snapshot_column = (
        '"canonical_config_snapshot"'
        if "canonical_config_snapshot" in columns
        else "'{}'"
    )
    legacy = connection.exec_driver_sql(
        'SELECT "id", "name", "version", "kind", "config_json", '
        + snapshot_column
        + ', "active", "created_at" '
        f'FROM "{_STRATEGY_TABLE}" ORDER BY "id"'
    ).all()
    connection.exec_driver_sql(_STRATEGY_REBUILD_DDL)
    migrated = []
    for row_id, name, version, kind, config, snapshot, active, created_at in legacy:
        formula = classify_strategy_formula(name, version, config, snapshot)
        migrated.append(
            (
                row_id,
                name,
                version,
                formula,
                kind,
                config,
                snapshot,
                active if formula == INSTITUTIONAL_FLOW_FORMULA_V2 else 0,
                created_at,
            )
        )
    if migrated:
        connection.exec_driver_sql(
            f'INSERT INTO "{_STRATEGY_SCRATCH}" '
            "(id, name, version, formula_version, kind, config_json, canonical_config_snapshot, active, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            migrated,
        )
    connection.exec_driver_sql(f'DROP TABLE "{_STRATEGY_TABLE}"')
    connection.exec_driver_sql(
        f'ALTER TABLE "{_STRATEGY_SCRATCH}" RENAME TO "{_STRATEGY_TABLE}"'
    )
    connection.exec_driver_sql(
        f'CREATE INDEX "ix_strategy_versions_name" ON "{_STRATEGY_TABLE}" ("name")'
    )
    kept = [
        row[0]
        for row in connection.exec_driver_sql(
            f'SELECT "id" FROM "{_STRATEGY_TABLE}" ORDER BY "id"'
        )
    ]
    if (
        kept != [row[0] for row in legacy]
        or _strategy_formula_state(connection) != "current"
    ):
        raise _strategy_error("post-rebuild identity mismatch")
    if inspect(connection).has_table("signals") and connection.exec_driver_sql(
        'PRAGMA foreign_key_check("signals")'
    ).fetchmany(1):
        raise _strategy_error("post-rebuild foreign-key violation from signals")
    return True


def _fallback_upgrade_on_connection(connection) -> None:
    from . import models  # noqa: F401
    from .db import Base

    if connection.dialect.name == "sqlite":
        preflight_instrument_identity(connection)
        preflight_settlement_identity(connection)
    # news_llm_results (0012) and the theme suggestion tables (0014) reference
    # news_items, and the 0006 repair below refuses to rebuild a referenced
    # news_items; create them after that repair.
    after_news_repair = [
        Base.metadata.tables[name]
        for name in ("news_llm_results", "theme_suggestions", "theme_suggestion_news")
    ]
    Base.metadata.create_all(
        bind=connection,
        tables=[
            table
            for table in Base.metadata.sorted_tables
            if table not in after_news_repair
        ],
    )
    inspector = inspect(connection)
    # A pre-existing status is authoritative. Only rows from a schema that
    # lacked it receive the one-time legacy classification below.
    had_turnover_status = inspector.has_table(
        "market_bars"
    ) and "turnover_status" in _column_names(connection, "market_bars")
    for table_name, columns in _ADDITIVE_COLUMNS.items():
        if not inspector.has_table(table_name):
            continue
        existing = _column_names(connection, table_name)
        for column_name, definition in columns.items():
            if column_name not in existing:
                connection.execute(
                    text(
                        f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {definition}'
                    )
                )
    if inspector.has_table("market_bars") and not had_turnover_status:
        connection.execute(
            text(
                "UPDATE market_bars SET turnover_status = 'available' WHERE turnover > 0"
            )
        )
        connection.execute(
            text(
                "UPDATE market_bars SET turnover_reason = 'legacy_zero_ambiguous' "
                "WHERE turnover = 0"
            )
        )
        connection.execute(
            text(
                "UPDATE market_bars SET turnover_reason = 'legacy_invalid' "
                "WHERE turnover < 0 OR turnover IS NULL"
            )
        )
    _rebuild_instruments_if_needed(connection)
    _ensure_request_key_index(connection)
    _rebuild_signal_settlements_if_needed(connection)
    ensure_portfolio_share_integer(connection)
    ensure_strategy_formula_version(connection)
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
    for table in after_news_repair:
        table.create(bind=connection, checkfirst=True)
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
    connection.execute(
        text(
            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) "
            "VALUES ('0007_turnover_availability', CURRENT_TIMESTAMP)"
        )
    )
    connection.execute(
        text(
            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) "
            "VALUES ('0008_portfolio_share_integer', CURRENT_TIMESTAMP)"
        )
    )
    connection.execute(
        text(
            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) "
            f"VALUES ('{STRATEGY_FORMULA_REVISION}', CURRENT_TIMESTAMP)"
        )
    )
    # 0010 only adds technical_indicators, which create_all above already made.
    connection.execute(
        text(
            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) "
            "VALUES ('0010_technical_indicators', CURRENT_TIMESTAMP)"
        )
    )
    # 0011 only adds schedule_runs/schedule_run_steps, also made by create_all.
    connection.execute(
        text(
            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) "
            f"VALUES ('{SCHEDULE_RUNS_REVISION}', CURRENT_TIMESTAMP)"
        )
    )
    # 0012 only adds news_llm_results, created above after the news repair.
    connection.execute(
        text(
            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) "
            "VALUES ('0012_news_llm', CURRENT_TIMESTAMP)"
        )
    )
    # 0013 only adds candidate_runs/daily_candidates, also made by create_all.
    connection.execute(
        text(
            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) "
            "VALUES ('0013_candidates', CURRENT_TIMESTAMP)"
        )
    )
    # 0014 only adds theme_suggestions/theme_suggestion_news, created above
    # after the news repair.
    connection.execute(
        text(
            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) "
            "VALUES ('0014_theme_suggestions', CURRENT_TIMESTAMP)"
        )
    )
    # 0015 only adds candidate_llm_notes, also made by create_all.
    connection.execute(
        text(
            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) "
            "VALUES ('0015_candidate_llm_notes', CURRENT_TIMESTAMP)"
        )
    )
    # 0016 only adds group_daily_score_archive, also made by create_all.
    connection.execute(
        text(
            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) "
            "VALUES ('0016_group_score_archive', CURRENT_TIMESTAMP)"
        )
    )
    # 0017 only adds tracking_plans/tracking_plan_sessions, also made by create_all.
    connection.execute(
        text(
            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) "
            "VALUES ('0017_tracking_plans', CURRENT_TIMESTAMP)"
        )
    )
    # 0018 only adds strategy_levels, also made by create_all.
    connection.execute(
        text(
            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) "
            "VALUES ('0018_strategy_levels', CURRENT_TIMESTAMP)"
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
                    raise RuntimeError(
                        "cannot migrate settlements: missing current identity after fallback"
                    )
                if preflight_instrument_identity(connection) != "current":
                    raise RuntimeError(
                        "cannot migrate instruments: missing current identity after fallback"
                    )
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


def _escape_config_value(value: str) -> str:
    """Escape ``%`` so ConfigParser interpolation reads the value back verbatim.

    ``Config.set_main_option`` hands the value to ``ConfigParser.set``, which
    rejects a bare ``%`` and would expand a ``%(name)s`` token inside a path.
    """

    return value.replace("%", "%%")


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
    config.set_main_option(
        "sqlalchemy.url",
        _escape_config_value(target_engine.url.render_as_string(hide_password=False)),
    )
    config.set_main_option(
        "script_location", _escape_config_value(str(config_path.parent / "alembic"))
    )
    # Reuse the configured engine so its SQLite foreign-key listener remains
    # active and tests can migrate an isolated database without touching the
    # production stock.db.
    config.attributes["connection"] = target_engine
    command.upgrade(config, "head")
