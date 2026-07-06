"""日價量（daily_prices）：雙價格制。

依 docs/design.md §7：資料庫同時存**原始價**（`*_raw`，看盤軟體一致、分點成本估算用）
與**除權息還原價**（`*_adj`，指標/篩選/回測用）。還原價由本 model 落地欄位，
實際數值由 spec-10（`app.pricing.adjustment`）依 `corporate_actions` 自算回填，
本期 ingestion 只落原始價，`*_adj` 允許先為 NULL。
"""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime

from sqlalchemy import BigInteger, Date as SqlDate, DateTime, ForeignKey, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

_PRICE = Numeric(12, 4)


class DailyPrice(Base):
    """個股日 OHLCV，含原始價與除權息還原價兩組欄位。"""

    __tablename__ = "daily_prices"
    __table_args__ = (
        UniqueConstraint("security_id", "date", name="uq_daily_prices_security_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[Date] = mapped_column(SqlDate, nullable=False)

    # --- 原始價（看盤軟體一致、分點成本估算用）---
    open_raw: Mapped[float] = mapped_column(_PRICE, nullable=False)
    high_raw: Mapped[float] = mapped_column(_PRICE, nullable=False)
    low_raw: Mapped[float] = mapped_column(_PRICE, nullable=False)
    close_raw: Mapped[float] = mapped_column(_PRICE, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # --- 除權息還原價（指標/篩選/回測用）；本期允許 NULL，由 spec-10 回填 ---
    open_adj: Mapped[float | None] = mapped_column(_PRICE, nullable=True)
    high_adj: Mapped[float | None] = mapped_column(_PRICE, nullable=True)
    low_adj: Mapped[float | None] = mapped_column(_PRICE, nullable=True)
    close_adj: Mapped[float | None] = mapped_column(_PRICE, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
