"""Use exchange+symbol as the instrument identity.

Revision ID: 0002_instrument_exchange_key
Revises: 0001_schema_v1
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect


revision = "0002_instrument_exchange_key"
down_revision = "0001_schema_v1"
branch_labels = None
depends_on = None


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


def _rebuild_sqlite_instruments(bind) -> None:
    from app.instrument_identity_migration import rebuild_instrument_identity

    rebuild_instrument_identity(bind)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # env.py owns the transaction/FK boundary, including our marker.
        _rebuild_sqlite_instruments(bind)
    else:
        if _has_unique_columns(bind, "instruments", ("market", "symbol")):
            op.drop_constraint("uq_instrument_market_symbol", "instruments", type_="unique")
        if not _has_unique_columns(bind, "instruments", ("exchange", "symbol")):
            op.create_unique_constraint(
                "uq_instrument_exchange_symbol",
                "instruments",
                ["exchange", "symbol"],
            )


def downgrade() -> None:
    raise RuntimeError("The instrument identity migration is forward-only")
