"""Telegram 通知 adapter shell。本期不進行真實推播。"""

import logging

from .base import Notifier
from ..config import get_settings

logger = logging.getLogger(__name__)


class TelegramNotifier(Notifier):
    """Telegram bot adapter（shell）。

    讀取 TELEGRAM_BOT_TOKEN 與 TELEGRAM_CHAT_ID 環境變數。
    本期為 shell 實作，不進行真實推播；後續可實装實際呼叫 Telegram Bot API。

    無 token 時降級為 no-op 並記 log；notify 永不拋例外。
    """

    def __init__(self) -> None:
        """初始化：讀取 Telegram 設定。"""
        settings = get_settings()
        self.bot_token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id

    def notify(self, subject: str, message: str) -> None:
        """發送 Telegram 通知（本期為 shell，不真推播）。

        Args:
            subject: 通知標題
            message: 通知內容

        若無 bot_token 或 chat_id，則為 no-op 並記 warning log。
        本期不進行真實網路請求；後續實装時可在此處呼叫 Telegram Bot API。
        永不拋例外。
        """
        try:
            if not self.bot_token:
                logger.warning(
                    "TELEGRAM_BOT_TOKEN not configured; "
                    "notify skipped (no-op)"
                )
                return

            if not self.chat_id:
                logger.warning(
                    "TELEGRAM_CHAT_ID not configured; "
                    "notify skipped (no-op)"
                )
                return

            # 本期只記 log，不進行真實推播
            logger.info(
                f"[TELEGRAM_SHELL] Would send notification to chat "
                f"{self.chat_id}: {subject} / {message}"
            )
        except Exception:
            # 吞掉任何例外，確保 notify 永不失敗
            logger.exception(
                "Unexpected error in TelegramNotifier.notify; "
                "continuing anyway"
            )
