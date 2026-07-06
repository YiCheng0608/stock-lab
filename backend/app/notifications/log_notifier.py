"""日誌通知器：以 logging 輸出通知，永不失敗。"""

import logging

from .base import Notifier

logger = logging.getLogger(__name__)


class LogNotifier(Notifier):
    """以 logging 輸出通知，供本期預設通知器。

    永遠不拋例外，即使 logging 本身出錯也吞掉。
    這保證 ingestion 流程中呼叫 notify 時不會因通知故障而中斷。
    """

    def notify(self, subject: str, message: str) -> None:
        """以 logging.info 寫出通知。

        Args:
            subject: 通知標題
            message: 通知內容

        永遠不拋例外。
        """
        try:
            logger.info(f"[NOTIFICATION] {subject}: {message}")
        except Exception:
            # 吞掉任何例外，確保 notify 永不失敗
            pass
