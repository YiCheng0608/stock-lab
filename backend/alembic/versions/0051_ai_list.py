"""Add the AI list tables.

Revision ID: 0051_ai_list
Revises: 0042_quarterly_statements

``ai_list_readings`` (one row per run of a day, prompt version and role) and
``ai_list_picks`` (each pick of a done reading) keep the AI list of Issue #1145
(``worker.ai_list``, docs/spec/ai_list.md).  Additive: no existing row is read or
changed, and ``premarket_ai_*`` are left as they are.  The number is 0051, not
0043: the research database's migrations 0043 to 0050 are still queued (#1145,
「migration 的排隊」).  The downgrade drops the two tables and their rows, which
cannot be made again: a list is only valid on the morning it was made.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    inspect,
)

revision = "0051_ai_list"
down_revision = "0042_quarterly_statements"
branch_labels = None
depends_on = None

READINGS = "ai_list_readings"
PICKS = "ai_list_picks"
INDEXES = {
    READINGS: ("session_date",),
    PICKS: ("reading_id", "session_date", "instrument_id"),
}


def upgrade() -> None:
    names = set(inspect(op.get_bind()).get_table_names())
    if READINGS not in names:
        op.create_table(
            READINGS,
            Column("id", Integer, primary_key=True),
            Column("session_date", Date, nullable=False),
            Column("list_date", Date, nullable=False),
            Column("role", String(length=20), nullable=False),
            Column("sequence", Integer, nullable=False),
            Column("trigger", String(length=20), nullable=False),
            Column("prompt_version", String(length=40), nullable=False),
            Column("prompt_sha256", String(length=64), nullable=False),
            Column("schema_sha256", String(length=64), nullable=False),
            Column("model_alias", String(length=40), nullable=False),
            Column("llm_model", String(length=80), nullable=True),
            Column("pool_phase", String(length=20), nullable=False),
            Column("cutoff_at", DateTime, nullable=False),
            Column("input_hash", String(length=64), nullable=False),
            Column("input_json", JSON, nullable=False),
            Column("status", String(length=20), nullable=False),
            Column("reason", String(length=60), nullable=True),
            Column("error", Text, nullable=True),
            Column("output_json", JSON, nullable=True),
            Column("market_method_json", JSON, nullable=True),
            Column("checks_json", JSON, nullable=False),
            Column("attempts", Integer, nullable=False),
            Column("attempts_json", JSON, nullable=False),
            Column("duration_ms", Integer, nullable=False),
            Column("usage_json", JSON, nullable=False),
            Column(
                "ingestion_run_id",
                Integer,
                ForeignKey("ingestion_runs.id"),
                nullable=True,
            ),
            Column("started_at", DateTime, nullable=False),
            Column("finished_at", DateTime, nullable=False),
            UniqueConstraint(
                "session_date",
                "prompt_version",
                "role",
                "sequence",
                name="uq_ai_list_reading_run",
            ),
        )
        _indexes(READINGS)
    if PICKS not in names:
        op.create_table(
            PICKS,
            Column("id", Integer, primary_key=True),
            Column("reading_id", Integer, ForeignKey(f"{READINGS}.id"), nullable=False),
            Column("session_date", Date, nullable=False),
            Column("prompt_version", String(length=40), nullable=False),
            Column("role", String(length=20), nullable=False),
            Column("rank", Integer, nullable=False),
            Column(
                "instrument_id", Integer, ForeignKey("instruments.id"), nullable=False
            ),
            Column("symbol", String(length=30), nullable=False),
            Column("pool_item_id", Integer, nullable=True),
            Column("pool_sources_json", JSON, nullable=False),
            Column("on_rule_list", Boolean, nullable=False),
            Column("setup", String(length=40), nullable=False),
            Column("basis_json", JSON, nullable=False),
            Column("basis_primary", String(length=20), nullable=False),
            Column("confidence", String(length=20), nullable=False),
            Column("levels_json", JSON, nullable=False),
            Column("levels_check_json", JSON, nullable=False),
            Column("display_levels_json", JSON, nullable=True),
            Column("risk_reward", Float, nullable=True),
            Column("valid_sessions", Integer, nullable=False),
            Column("valid_until", Date, nullable=True),
            Column("exit_conditions_json", JSON, nullable=False),
            Column("reasons_json", JSON, nullable=False),
            Column("rule_levels_json", JSON, nullable=True),
            UniqueConstraint("reading_id", "rank", name="uq_ai_list_pick_rank"),
            UniqueConstraint(
                "reading_id", "instrument_id", name="uq_ai_list_pick_stock"
            ),
        )
        _indexes(PICKS)


def _indexes(table: str) -> None:
    for column in INDEXES[table]:
        op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    names = set(inspect(op.get_bind()).get_table_names())
    for table in (PICKS, READINGS):
        if table not in names:
            continue
        for column in INDEXES[table]:
            op.drop_index(f"ix_{table}_{column}", table_name=table)
        op.drop_table(table)
