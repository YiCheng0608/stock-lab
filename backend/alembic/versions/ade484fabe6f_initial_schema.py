"""initial schema

建立第一期 ingestion pipeline 所需全部資料表（見 docs/design.md §2/§3/§4/§7）：

- `users`：user 概念掛載點，其餘表若涉及使用者關聯一律走 `user_id` FK（本期尚無
  表格需要，先備妥此表供未來自選股/策略掛載，不寫死單一使用者）。
- `securities`：股票基本資料，`daily_prices`/`chips`/`broker_branch_trades` 的父表。
- `daily_prices`：雙價格制（`*_raw` 原始價 + `*_adj` 還原價，`*_adj` 本期允許 NULL，
  由 spec-10 回填）。
- `chips`：三大法人買賣超、融資券、借券餘額，(security, date) 唯一鍵。
- `corporate_actions`：除權息事件/股本變動，供 spec-10 計算還原係數。
- `broker_branch_trades`：PostgreSQL 原生按 `date` 月分區（`PARTITION BY RANGE`），
  (security, broker_branch, date) 唯一鍵/索引。分區為 raw SQL 建立（ORM/`op.create_table`
  的 `postgresql_partition_by` 只建父表，子分區必須另外 `CREATE TABLE ... PARTITION OF`）。

Revision ID: ade484fabe6f
Revises:
Create Date: 2026-07-06 14:29:11.355138

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ade484fabe6f'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


BROKER_BRANCH_TABLE = "broker_branch_trades"
# 分點資料自 pipeline 上線日起累積（見 design.md §3），這裡先鋪好近三年的月分區；
# 落在區間外的資料（理論上不應發生）落入 default 分區兜底，不擋 upgrade。
BROKER_BRANCH_PARTITION_START = (2025, 1)
BROKER_BRANCH_PARTITION_END = (2027, 12)


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    if month == 12:
        return f"{year:04d}-12-01", f"{year + 1:04d}-01-01"
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month + 1:02d}-01"


def _create_monthly_partitions(table: str, start: tuple[int, int], end: tuple[int, int]) -> None:
    """為 `table`（須已是 `PARTITION BY RANGE (date)` 的分區表）建立
    `[start, end]`（含端點）區間內逐月分區，命名為 `{table}_YYYY_MM`。
    """
    year, month = start
    end_year, end_month = end
    while (year, month) <= (end_year, end_month):
        lo, hi = _month_bounds(year, month)
        partition_name = f"{table}_{year:04d}_{month:02d}"
        op.execute(
            f"CREATE TABLE {partition_name} PARTITION OF {table} "
            f"FOR VALUES FROM ('{lo}') TO ('{hi}')"
        )
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1


def upgrade() -> None:
    """Upgrade schema."""

    # --- users：user 概念掛載點 ---
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    # --- securities：父表 ---
    security_market = sa.Enum("listed", "otc", name="security_market")
    op.create_table(
        "securities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("market", security_market, nullable=False),
        sa.Column("outstanding_shares", sa.BigInteger(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("symbol", name="uq_securities_symbol"),
    )

    # --- daily_prices：雙價格制 ---
    op.create_table(
        "daily_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "security_id",
            sa.Integer(),
            sa.ForeignKey("securities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open_raw", sa.Numeric(12, 4), nullable=False),
        sa.Column("high_raw", sa.Numeric(12, 4), nullable=False),
        sa.Column("low_raw", sa.Numeric(12, 4), nullable=False),
        sa.Column("close_raw", sa.Numeric(12, 4), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("open_adj", sa.Numeric(12, 4), nullable=True),
        sa.Column("high_adj", sa.Numeric(12, 4), nullable=True),
        sa.Column("low_adj", sa.Numeric(12, 4), nullable=True),
        sa.Column("close_adj", sa.Numeric(12, 4), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "security_id", "date", name="uq_daily_prices_security_date"
        ),
    )

    # --- chips：三大法人/融資券/借券，(security, date) 唯一鍵 ---
    op.create_table(
        "chips",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "security_id",
            sa.Integer(),
            sa.ForeignKey("securities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("foreign_net", sa.BigInteger(), nullable=True),
        sa.Column("investment_trust_net", sa.BigInteger(), nullable=True),
        sa.Column("dealer_net", sa.BigInteger(), nullable=True),
        sa.Column("margin_balance", sa.BigInteger(), nullable=True),
        sa.Column("short_balance", sa.BigInteger(), nullable=True),
        sa.Column("securities_lending_balance", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("security_id", "date", name="uq_chips_security_date"),
    )

    # --- corporate_actions：除權息事件/股本變動 ---
    op.create_table(
        "corporate_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "security_id",
            sa.Integer(),
            sa.ForeignKey("securities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ex_rights_date", sa.Date(), nullable=False),
        sa.Column("cash_dividend_per_share", sa.Numeric(10, 4), nullable=True),
        sa.Column("stock_dividend_per_share", sa.Numeric(10, 4), nullable=True),
        sa.Column("capital_change_shares", sa.BigInteger(), nullable=True),
        sa.Column("capital_after_shares", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "security_id",
            "ex_rights_date",
            name="uq_corporate_actions_security_ex_date",
        ),
    )

    # --- broker_branch_trades：按月分區 ＋ (security, broker_branch, date) 索引 ---
    # 分區表的每個唯一鍵都必須包含分區鍵 date，故主鍵為 (id, date)；
    # 業務去重鍵另建 UniqueConstraint(security_id, broker_branch_code, date)，
    # 該 UniqueConstraint 同時滿足「索引」要求。
    op.create_table(
        BROKER_BRANCH_TABLE,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column(
            "security_id",
            sa.Integer(),
            sa.ForeignKey("securities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("broker_branch_code", sa.String(16), nullable=False),
        sa.Column("broker_branch_name", sa.String(128), nullable=True),
        sa.Column("buy_volume", sa.BigInteger(), nullable=False),
        sa.Column("sell_volume", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "security_id",
            "broker_branch_code",
            "date",
            name="uq_broker_branch_trades_security_branch_date",
        ),
        postgresql_partition_by="RANGE (date)",
    )
    _create_monthly_partitions(
        BROKER_BRANCH_TABLE, BROKER_BRANCH_PARTITION_START, BROKER_BRANCH_PARTITION_END
    )
    op.execute(
        f"CREATE TABLE {BROKER_BRANCH_TABLE}_default PARTITION OF {BROKER_BRANCH_TABLE} DEFAULT"
    )


def downgrade() -> None:
    """Downgrade schema."""
    # DROP TABLE 父表會連帶砍掉所有分區子表（PostgreSQL 原生行為），不必逐一 DROP。
    op.drop_table(BROKER_BRANCH_TABLE)
    op.drop_table("corporate_actions")
    op.drop_table("chips")
    op.drop_table("daily_prices")
    op.drop_table("securities")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS security_market")
