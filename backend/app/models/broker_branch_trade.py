"""券商分點買賣日報表（broker_branch_trades）：PostgreSQL 原生按月分區。

依 docs/design.md §3、§4：分點資料量大且只會持續累積（錯過即永久缺洞、只增不減），
按 `date` 月分區便於未來依時間範圍裁剪查詢與汰舊；(security, broker_branch, date)
是查詢與去重的關鍵鍵，須建索引。

分區本身（`PARTITION BY RANGE (date)` 與各月子表）由對應 migration 以 raw SQL /
`postgresql_partition_by` table option 建立——ORM 層只表達「這是一張分區表」與其
欄位、鍵，不表達子分區的存在（子分區不是獨立 model，見 migration）。

PostgreSQL 要求分區表的每個唯一鍵/主鍵都必須包含分區鍵（`date`），因此主鍵是
`(id, date)` 而非單獨的 `id`；業務去重鍵 `(security_id, broker_branch_code, date)`
另建 `UniqueConstraint`。
"""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Date as SqlDate,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BrokerBranchTrade(Base):
    """個股券商分點日買賣量。"""

    __tablename__ = "broker_branch_trades"
    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "broker_branch_code",
            "date",
            name="uq_broker_branch_trades_security_branch_date",
        ),
        {"postgresql_partition_by": "RANGE (date)"},
    )

    # 分區表主鍵須含分區鍵，故 (id, date) 為主鍵，id 本身不單獨唯一。
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[Date] = mapped_column(SqlDate, primary_key=True)

    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    broker_branch_code: Mapped[str] = mapped_column(String(16), nullable=False)
    broker_branch_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    buy_volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sell_volume: Mapped[int] = mapped_column(BigInteger, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
