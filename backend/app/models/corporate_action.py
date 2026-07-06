"""除權息事件與股本變動（corporate_actions）。

依 docs/design.md §7：還原係數由 spec-10 依此表的除權息事件（配息／配股）自算，
本表只落抓取到的事件本身，不存算好的係數（係數屬 `daily_prices.*_adj` 的計算輸入，
不是這裡的欄位）。同一檔股票同一除權息日的配股與配息（台股常見同天）落同一列。
"""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime

from sqlalchemy import BigInteger, Date as SqlDate, DateTime, ForeignKey, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CorporateAction(Base):
    """個股除權息事件：除權息日、配股配息、股本變動。"""

    __tablename__ = "corporate_actions"
    __table_args__ = (
        UniqueConstraint(
            "security_id", "ex_rights_date", name="uq_corporate_actions_security_ex_date"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )

    # 除權息日（還原係數計算以此日為基準）
    ex_rights_date: Mapped[Date] = mapped_column(SqlDate, nullable=False)

    # 除息：現金股利（每股，元）
    cash_dividend_per_share: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    # 除權：股票股利／無償配股（每股配股數）
    stock_dividend_per_share: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)

    # 股本變動（股數，正負代表增減；變動後股本股數）
    capital_change_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    capital_after_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
