"""Create the v1 schema and add fields needed by legacy databases.

Revision ID: 0001_schema_v1
Revises:
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect, text

import app.models  # noqa: F401
from app.db import Base
from app.settlement_identity_migration import preflight_settlement_identity, rebuild_settlement_identity


revision = "0001_schema_v1"
down_revision = None
branch_labels = None
depends_on = None


def _additive_columns() -> dict[str, dict[str, str]]:
    return {
        "instruments": {
            "exchange": "VARCHAR(20) NOT NULL DEFAULT 'TWSE'",
            "industry": "VARCHAR(120)",
        },
        "market_bars": {
            "raw_payload_id": "INTEGER REFERENCES raw_payloads(id)",
            "is_suspended": "BOOLEAN NOT NULL DEFAULT 0",
        },
        "chip_snapshots": {"raw_payload_id": "INTEGER REFERENCES raw_payloads(id)"},
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
    }



def _has_unique_columns(bind, table_name: str, expected: tuple[str, ...]) -> bool:
    inspector = inspect(bind)
    wanted = tuple(expected)
    for constraint in inspector.get_unique_constraints(table_name):
        if tuple(constraint.get("column_names") or ()) == wanted:
            return True
    for index in inspector.get_indexes(table_name):
        if index.get("unique") and tuple(index.get("column_names") or ()) == wanted:
            return True
    return False


def _ensure_request_key_index(bind) -> None:
    inspector = inspect(bind)
    if not inspector.has_table("ingestion_runs"):
        return
    if _has_unique_columns(bind, "ingestion_runs", ("request_key",)):
        return
    bind.execute(
        text(
            'CREATE UNIQUE INDEX IF NOT EXISTS "ix_ingestion_runs_request_key" '
            'ON "ingestion_runs" ("request_key") WHERE "request_key" IS NOT NULL'
        )
    )


def _rebuild_signal_settlements_if_needed(connection) -> None:
    rebuild_settlement_identity(connection)



def upgrade() -> None:
    bind = op.get_bind()
    preflight_settlement_identity(bind)
    # ``Table.create`` is deliberately driven from this checked-in revision;
    # application startup no longer calls create_all directly.
    for table in Base.metadata.sorted_tables:
        table.create(bind=bind, checkfirst=True)

    inspector = inspect(bind)
    for table_name, columns in _additive_columns().items():
        if not inspector.has_table(table_name):
            continue
        existing = {column["name"] for column in inspect(bind).get_columns(table_name)}
        for column_name, definition in columns.items():
            if column_name not in existing:
                bind.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {definition}'))
    _ensure_request_key_index(bind)
    _rebuild_signal_settlements_if_needed(bind)


def downgrade() -> None:
    # The project explicitly preserves legacy data; destructive downgrades are
    # intentionally unsupported.
    raise RuntimeError("The v1 schema migration is forward-only to preserve legacy data")
