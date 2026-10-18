"""Add the hot-group score archive table.

Revision ID: 0015_group_score_archive
Revises: 0014_theme_suggestions

``group_daily_score_archive`` keeps a verbatim copy of a ``group_daily_scores``
row before a newer ``hot_group_v1`` version overwrites it (V1_SPEC
hot_group_v1).  Additive and forward-only: no existing row is read or changed.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    inspect,
)

revision = "0015_group_score_archive"
down_revision = "0014_theme_suggestions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("group_daily_score_archive"):
        return
    op.create_table(
        "group_daily_score_archive",
        Column("id", Integer, primary_key=True),
        Column("score_id", Integer, nullable=False),
        Column(
            "group_id", String(length=80), ForeignKey("theme_groups.id"), nullable=False
        ),
        Column("trading_date", Date, nullable=False),
        Column("relative_return", Float, nullable=True),
        Column("relative_return_1d", Float, nullable=True),
        Column("relative_return_5d", Float, nullable=True),
        Column("relative_return_20d", Float, nullable=True),
        Column("breadth", Float, nullable=True),
        Column("volume_strength", Float, nullable=True),
        Column("institutional_flow", Float, nullable=True),
        Column("catalyst", Float, nullable=True),
        Column("score", Float, nullable=True),
        Column("rank", Integer, nullable=True),
        Column("eligible_members", Integer, nullable=False),
        Column("data_quality", String(length=30), nullable=False),
        Column("details_json", JSON, nullable=False),
        Column("hot_group_version", String(length=30), nullable=False),
        Column("archive_reason", String(length=80), nullable=False),
        Column("archived_at", DateTime, nullable=False),
        UniqueConstraint(
            "group_id",
            "trading_date",
            "hot_group_version",
            name="uq_group_score_archive_day_version",
        ),
    )
    op.create_index(
        "ix_group_daily_score_archive_score_id",
        "group_daily_score_archive",
        ["score_id"],
    )
    op.create_index(
        "ix_group_daily_score_archive_group_id",
        "group_daily_score_archive",
        ["group_id"],
    )
    op.create_index(
        "ix_group_daily_score_archive_trading_date",
        "group_daily_score_archive",
        ["trading_date"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "The group score archive migration is forward-only to preserve scored history"
    )
