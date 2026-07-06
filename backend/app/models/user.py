"""使用者概念（user）。

依 docs/design.md §2 原則 2：自選股、策略等未來功能從第一天掛在 user 概念下，
即使目前只有一筆 user，schema 也不得寫死單一使用者。本期只需此表存在，
供日後功能以 `user_id` FK 掛載。
"""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    """使用者。第一期不做認證/權限，僅提供 user 概念的掛載點。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
