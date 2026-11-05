"""Add the TPEx emerging-market roster table.

Revision ID: 0027_emerging_issuers
Revises: 0026_projection_snapshots

``emerging_issuers`` keeps the code, short name, market and 資料日期 of each
company on TPEx ``mopsfin_t187ap03_R`` (興櫃公司基本資料), with a link to the
raw payload (Issue #512).  collect writes it; the news API reads it only to
name an AI symbol candidate that is not a listed or OTC instrument.  Additive
and forward-only: no existing row is read or changed.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import Column, Date, ForeignKey, Integer, String, inspect

revision = "0027_emerging_issuers"
down_revision = "0026_projection_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if inspect(op.get_bind()).has_table("emerging_issuers"):
        return
    op.create_table(
        "emerging_issuers",
        Column("symbol", String(length=12), primary_key=True),
        Column("name", String(length=120), nullable=False),
        Column("market", String(length=20), nullable=False),
        Column("as_of_date", Date, nullable=False),
        Column(
            "raw_payload_id", Integer, ForeignKey("raw_payloads.id"), nullable=False
        ),
    )
    op.create_index(
        "ix_emerging_issuers_as_of_date", "emerging_issuers", ["as_of_date"]
    )
    op.create_index(
        "ix_emerging_issuers_raw_payload_id", "emerging_issuers", ["raw_payload_id"]
    )


def downgrade() -> None:
    raise RuntimeError(
        "The emerging roster migration is forward-only to preserve collected rows"
    )
