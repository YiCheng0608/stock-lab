"""Record the institutional and margin provenance of a chip row separately.

Revision ID: 0021_chip_source_groups
Revises: 0020_trading_calendar

Adds ``institutional_*`` and ``margin_*`` source, raw payload, data date and
collection time columns to ``chip_snapshots`` (Issue #395).  Additive and
forward-only: no existing row is read or changed here.  Existing rows are
filled from their stored raw captures by ``worker.cli chip-provenance``
(OPERATIONS §3); until then readers derive the groups from the row-level
fields (``app.chip_provenance.legacy_groups``).
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import Column, DateTime, Integer, String, inspect

revision = "0021_chip_source_groups"
down_revision = "0020_trading_calendar"
branch_labels = None
depends_on = None

COLUMNS = (
    ("institutional_source", String(40)),
    ("institutional_raw_payload_id", Integer),
    ("institutional_data_as_of", DateTime),
    ("institutional_collected_at", DateTime),
    ("margin_source", String(40)),
    ("margin_raw_payload_id", Integer),
    ("margin_data_as_of", DateTime),
    ("margin_collected_at", DateTime),
)


def upgrade() -> None:
    bind = op.get_bind()
    existing = {
        column["name"] for column in inspect(bind).get_columns("chip_snapshots")
    }
    for name, kind in COLUMNS:
        if name in existing:
            continue
        if name.endswith("_raw_payload_id"):
            # SQLite adds a REFERENCES column in place only through raw DDL.
            bind.exec_driver_sql(
                f'ALTER TABLE chip_snapshots ADD COLUMN "{name}" '
                "INTEGER REFERENCES raw_payloads(id)"
            )
        else:
            op.add_column("chip_snapshots", Column(name, kind, nullable=True))


def downgrade() -> None:
    raise RuntimeError("Chip source group migration is forward-only")
