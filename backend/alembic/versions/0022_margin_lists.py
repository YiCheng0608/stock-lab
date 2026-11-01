"""Add the official margin-trading list table.

Revision ID: 0022_margin_lists
Revises: 0021_chip_source_groups

``margin_lists`` keeps, per exchange and session, the codes of that day's
official margin balance report with their notes and a link to the raw payload
(Issue #392).  ``worker.margin_lists`` writes it from stored raw only (collect
and ``worker.cli margin-lists``); analyze reads it to tell a security that is
not a margin-financing security (不適用) from missing margin data.  Also adds
the index ``ix_signals_instrument_date`` on ``signals(instrument_id,
signal_date)`` for app.signal_versions (#407 review M1).  Additive and
forward-only: no existing row is read or changed.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    inspect,
)

revision = "0022_margin_lists"
down_revision = "0021_chip_source_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # The pages read a superseded strategy's signal only on an instrument-day
    # without a registered one; that check looks up one instrument-day.
    if "ix_signals_instrument_date" not in {
        index["name"] for index in inspect(bind).get_indexes("signals")
    }:
        op.create_index(
            "ix_signals_instrument_date", "signals", ["instrument_id", "signal_date"]
        )
    if inspect(bind).has_table("margin_lists"):
        return
    op.create_table(
        "margin_lists",
        Column("id", Integer, primary_key=True),
        Column("exchange", String(length=20), nullable=False),
        Column("trading_date", Date, nullable=False),
        Column("source", String(length=120), nullable=False),
        Column("endpoint", String(length=500), nullable=False),
        Column("data_as_of", String(length=40), nullable=False),
        Column("collected_at", DateTime, nullable=False),
        Column(
            "raw_payload_id", Integer, ForeignKey("raw_payloads.id"), nullable=False
        ),
        Column("member_count", Integer, nullable=False),
        Column("members_json", JSON, nullable=False),
        UniqueConstraint("exchange", "trading_date", name="uq_margin_list_day"),
    )
    op.create_index("ix_margin_lists_trading_date", "margin_lists", ["trading_date"])
    op.create_index(
        "ix_margin_lists_raw_payload_id", "margin_lists", ["raw_payload_id"]
    )


def downgrade() -> None:
    raise RuntimeError(
        "The margin list migration is forward-only to preserve collected rows"
    )
