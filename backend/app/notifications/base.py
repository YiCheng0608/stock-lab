"""通知 adapter 抽象基類。"""

from abc import ABC, abstractmethod


class Notifier(ABC):
    """通知 adapter 抽象基類。

    實作子類應覆寫 notify 方法以實現具體通知機制（如 Telegram、email、LINE 等）。
    設計為通用介面，不含任何通知管道的專屬概念。
    """

    @abstractmethod
    def notify(self, subject: str, message: str) -> None:
        """發送通知。

        Args:
            subject: 通知標題／主旨
            message: 通知內容

        子類實作應負責連線、格式化、錯誤處理。
        """
        pass
