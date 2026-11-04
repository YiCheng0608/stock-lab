"""Index the two orderings of ingestion_runs the pages read.

Revision ID: 0024_ingestion_run_indexes
Revises: 0023_settlement_tracking_rules

``ingestion_runs.metadata_json`` sits before ``updated_at`` in the stored rows
and is large (about 300 KB per official collect run, 172 MB in all on the
production copy), so every ``ORDER BY updated_at`` without an index walked the
metadata of each row (Issue #462): the latest official run that every page
reads took 0.04 s warm and 0.36 s cold, and ``/api/ingestion-runs`` 1.3 s.

* ``ix_ingestion_runs_latest`` on ``(run_type, source, status, updated_at)``
  answers ``app.decision.latest_official_run`` from the index.
* ``ix_ingestion_runs_updated_at`` on ``(updated_at)`` gives the run list its
  order (``updated_at desc, id desc``) without sorting whole rows.

Additive and forward-only: no row is read or changed.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

# The same statements as the fallback step (app.migrations), so both entries
# store the same index SQL.
INDEXES = (
    (
        "ix_ingestion_runs_latest",
        'CREATE INDEX IF NOT EXISTS "ix_ingestion_runs_latest" ON "ingestion_runs" '
        '("run_type", "source", "status", "updated_at")',
    ),
    (
        "ix_ingestion_runs_updated_at",
        'CREATE INDEX IF NOT EXISTS "ix_ingestion_runs_updated_at" '
        'ON "ingestion_runs" ("updated_at")',
    ),
)
COLUMNS = {"run_type", "source", "status", "updated_at"}

revision = "0024_ingestion_run_indexes"
down_revision = "0023_settlement_tracking_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    # A partial legacy schema in the migration tests may lack the table or a
    # column; every real database has both.
    if not inspector.has_table("ingestion_runs"):
        return
    if not COLUMNS <= {
        column["name"] for column in inspector.get_columns("ingestion_runs")
    }:
        return
    for _name, statement in INDEXES:
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("0024_ingestion_run_indexes is forward-only")
