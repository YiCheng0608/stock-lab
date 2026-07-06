"""SQLAlchemy models 套件。

匯入所有 model 模組，確保它們掛到 `Base.metadata` 上——
Alembic `env.py` 只需 `import app.models` 一次即可拿到完整的 `target_metadata`，
不必逐一列出每個 model 檔案。
"""

from app.models.base import Base
from app.models.broker_branch_trade import BrokerBranchTrade
from app.models.chip import Chip
from app.models.corporate_action import CorporateAction
from app.models.daily_price import DailyPrice
from app.models.security import Security, SecurityMarket
from app.models.user import User

__all__ = [
    "Base",
    "BrokerBranchTrade",
    "Chip",
    "CorporateAction",
    "DailyPrice",
    "Security",
    "SecurityMarket",
    "User",
]
