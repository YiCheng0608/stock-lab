"""籌碼（chips）：三大法人買賣超、融資券餘額、借券賣出餘額。

依 docs/design.md §3：來源穩定好爬，(security, date) 為唯一鍵，一表涵蓋三大法人、
融資券、借券三類每日數據（單一 security 單一 date 只有一列，正規化程度足夠、
不必為此再拆三表）。
"""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime

from sqlalchemy import BigInteger, Date as SqlDate, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Chip(Base):
    """個股日籌碼：三大法人買賣超（股數）、融資券與借券餘額。"""

    __tablename__ = "chips"
    __table_args__ = (
        UniqueConstraint("security_id", "date", name="uq_chips_security_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[Date] = mapped_column(SqlDate, nullable=False)

    # --- 三大法人買賣超（股數，正負代表買超/賣超）---
    foreign_net: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    investment_trust_net: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dealer_net: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # --- 融資券餘額（股數）---
    margin_balance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    short_balance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # --- 借券賣出餘額（股數）---
    securities_lending_balance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
