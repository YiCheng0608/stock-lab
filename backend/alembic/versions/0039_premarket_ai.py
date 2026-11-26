"""Add the pre-market AI reading tables.

Revision ID: 0039_premarket_ai
Revises: 0038_futures_night_bars

``premarket_ai_readings`` (one row per run of a day, prompt version and
role), ``premarket_ai_stocks`` (each stock of a done reading) and
``premarket_ai_scores`` (the scored outcomes #1043 writes) keep the
pre-market AI reading of Issue #1041 (``worker.premarket_ai``,
docs/spec/premarket_ai.md).  Additive: no existing row is read or changed.
The downgrade drops the three tables and their rows, which cannot be made
again: a reading is only valid on the morning it was made.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    inspect,
)

revision = "0039_premarket_ai"
down_revision = "0038_futures_night_bars"
branch_labels = None
depends_on = None

READINGS = "premarket_ai_readings"
STOCKS = "premarket_ai_stocks"
SCORES = "premarket_ai_scores"
INDEXES = {
    READINGS: ("session_date",),
    STOCKS: ("reading_id", "session_date", "instrument_id"),
    SCORES: ("reading_id", "session_date"),
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
                name="uq_premarket_ai_reading_run",
            ),
        )
        _indexes(READINGS)
    if STOCKS not in names:
        op.create_table(
            STOCKS,
            Column("id", Integer, primary_key=True),
            Column(
                "reading_id",
                Integer,
                ForeignKey(f"{READINGS}.id"),
                nullable=False,
            ),
            Column("session_date", Date, nullable=False),
            Column("prompt_version", String(length=40), nullable=False),
            Column("role", String(length=20), nullable=False),
            Column(
                "instrument_id", Integer, ForeignKey("instruments.id"), nullable=False
            ),
            Column("symbol", String(length=30), nullable=False),
            Column("position", Integer, nullable=False),
            Column("on_today_list", Boolean, nullable=False),
            Column(
                "daily_candidate_id",
                Integer,
                ForeignKey("daily_candidates.id"),
                nullable=True,
            ),
            Column("pool_item_id", Integer, nullable=True),
            Column("pool_sources_json", JSON, nullable=False),
            Column("levels_json", JSON, nullable=True),
            Column("action", String(length=20), nullable=False),
            Column("reprice_rule_json", JSON, nullable=True),
            Column("reasons_json", JSON, nullable=False),
            UniqueConstraint(
                "reading_id", "instrument_id", name="uq_premarket_ai_stock_reading"
            ),
        )
        _indexes(STOCKS)
    if SCORES not in names:
        op.create_table(
            SCORES,
            Column("id", Integer, primary_key=True),
            Column(
                "reading_id",
                Integer,
                ForeignKey(f"{READINGS}.id"),
                nullable=False,
            ),
            Column("stock_id", Integer, ForeignKey(f"{STOCKS}.id"), nullable=True),
            Column("session_date", Date, nullable=False),
            Column("prompt_version", String(length=40), nullable=False),
            Column("role", String(length=20), nullable=False),
            Column("scope", String(length=20), nullable=False),
            Column("subject", String(length=40), nullable=False),
            Column("horizon", String(length=20), nullable=False),
            Column("score_version", String(length=40), nullable=False),
            Column("outcome_json", JSON, nullable=False),
            Column("computed_at", DateTime, nullable=False),
            UniqueConstraint(
                "reading_id",
                "scope",
                "subject",
                "horizon",
                "score_version",
                name="uq_premarket_ai_score",
            ),
        )
        _indexes(SCORES)


def _indexes(table: str) -> None:
    for column in INDEXES[table]:
        op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    names = set(inspect(op.get_bind()).get_table_names())
    for table in (SCORES, STOCKS, READINGS):
        if table not in names:
            continue
        for column in INDEXES[table]:
            op.drop_index(f"ix_{table}_{column}", table_name=table)
        op.drop_table(table)
