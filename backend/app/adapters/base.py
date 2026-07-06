"""資料源 adapter 的抽象契約。

所有具體 adapter（日價量、籌碼、券商分點、除權息…）都必須實作這裡定義的 ABC，
而不是各自發明介面。核心設計要求（見 docs/design.md §2 原則 1、§3）：

- **抓取（碰網路）與解析（純函式）分離**：`fetch` 允許有 I/O 副作用、不保證可重試；
  `parse` 必須是純函式，只吃 `fetch` 回傳的原始資料、吐正規化列，因此可以用固定樣本
  做單元測試而不打外網。
- **`BrokerBranchSource` 是明列的未來替換縫**：分點資料目前自爬 `bsr.twse.com.tw`，
  未來可能全部或部分換成 FinMind 贊助方案回補。只要新舊實作都遵守這個 ABC，
  下游（pipeline、DB 寫入、排程）不必更動。
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from typing import Any

# 正規化後的一列資料。不同 adapter 產出的欄位形狀天差地遠（日價量 vs 分點 vs 除權息），
# 在具體 schema（見後續任務的 app.models）出現前，用 dict 保持契約層的中立、不預設欄位。
NormalizedRow = dict[str, Any]


class DataSource(ABC):
    """所有資料源 adapter 的共同契約。

    子類別必須把「向外部系統要原始資料」與「把原始資料轉成正規化列」分成兩個方法，
    好讓後者能在沒有網路、沒有外部服務的情況下用固定樣本測試。
    """

    @abstractmethod
    def fetch(self, target: Any, date: dt.date) -> Any:
        """向外部來源取得 `target`（由子類別定義其型別與語意，如股票代號）
        在 `date` 當天的原始資料。可能碰網路、可能失敗、不要求是純函式。

        回傳值的型別由子類別自訂（例如 HTML 字串、bytes、解析過的 JSON），
        僅需與同一子類別的 `parse` 方法約定一致的形狀。
        """

    @abstractmethod
    def parse(self, raw: Any) -> list[NormalizedRow]:
        """把 `fetch` 回傳的原始資料轉成正規化列的清單。

        必須是純函式：只依賴輸入的 `raw`，不觸發任何 I/O、不讀外部狀態。
        這是本契約存在的主因——讓解析邏輯可以用固定樣本做單元測試。
        """


class BrokerBranchSource(DataSource):
    """券商分點（買賣日報表）資料源的專用契約。

    是 docs/design.md §3 明列的未來替換縫：目前自爬 `bsr.twse.com.tw`，
    日後可能整條或部分換成 FinMind 付費方案回補歷史 / 補自爬缺洞。
    只要新舊實作都繼承此類別，下游不需要因為換來源而改動。

    把「驗證碼求解」「節流」「來源本身」三者都抽象在介面之後：
    - 來源本身：本類別即是該抽象。
    - 驗證碼：透過建構子注入 `CaptchaSolver`，換求解方案不影響來源邏輯。
    - 節流：留給具體實作內部處理（不同來源的節流策略、限速規則不同，
      不適合在契約層統一規定節奏，只要求其存在於 `fetch` 的責任範圍內）。
    """

    def __init__(self, captcha_solver: CaptchaSolver) -> None:
        """注入驗證碼求解器。自爬與未來 FinMind 等實作都經此注入點取得求解能力，
        換求解方案（例如 OCR 模型升級）不必更動分點來源本身的程式碼。
        """
        self._captcha_solver = captcha_solver

    @property
    def captcha_solver(self) -> CaptchaSolver:
        """目前注入的驗證碼求解器。"""
        return self._captcha_solver

    @abstractmethod
    def fetch(self, target: str, date: dt.date) -> Any:
        """取得 `target`（股票代號）在 `date` 當天的券商分點原始資料（買賣日報表）。

        官方頁面一次只能查一檔、每檔可能多頁、頁面帶驗證碼——分頁與節流由實作內部處理，
        遇到驗證碼時應呼叫 `self.captcha_solver.solve(...)`。
        """

    @abstractmethod
    def parse(self, raw: Any) -> list[NormalizedRow]:
        """把分點原始資料轉成正規化列。純函式，可用固定樣本單元測試而不打外網、不用真驗證碼。"""


class CaptchaSolver(ABC):
    """驗證碼求解契約，供 `BrokerBranchSource` 之類需要跨過驗證碼的來源注入使用。

    預設（可用的）實作在後續任務提供；本任務只定義介面。
    """

    @abstractmethod
    def solve(self, image: bytes) -> str:
        """給定驗證碼圖片的原始位元組，回傳辨識出的文字。"""
