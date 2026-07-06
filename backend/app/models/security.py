"""股票基本資料（securities）。

依 docs/design.md §3：所有日價量、籌碼、分點資料都以個股為單位，本表是這些表的
**父表**——`daily_prices` / `chips` / `broker_branch_trades` 的 `security_id` 皆為
FK 關聯此表，須先有股票列才能插入那三表（見 spec-11 pipeline 執行順序）。
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SecurityMarket(str, enum.Enum):
    """市場別：上市（TWSE）／上櫃（TPEx）。"""

    LISTED = "listed"
    OTC = "otc"


class Security(Base):
    """股票基本資料，含市場別、股本等。"""

    __tablename__ = "securities"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    market: Mapped[SecurityMarket] = mapped_column(
        Enum(
            SecurityMarket,
            name="security_market",
            native_enum=True,
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
    )
    # 股本（股數），股本變動事件見 corporate_actions；此欄為目前最新值，允許先為 NULL
    # （上市時可能尚未取得，由除權息/股本變動 ingestion 回填最新股本）。
    outstanding_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
