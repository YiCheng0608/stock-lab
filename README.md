# 台股研究專案

以免費公開市場資料支援台股盤後研究：新聞事件 → 族群／題材 → 個股證據 → 行動與持倉追蹤。

目前已有官方資料收集與回補、固定突破／回踩規則、行動摘要、持倉、技術回測和研究介面。可信媒體／國際新聞、分點分析、完整交易計畫及經驗證的 AI 預測仍待完成；現有訊號不代表校準勝率。

## 從這裡開始

| 想了解 | 入口 |
| --- | --- |
| 產品要解決什麼問題 | [產品規格](docs/PRODUCT_SPEC.md) |
| 現在做到哪裡、接下來做什麼 | [開發路線](docs/ROADMAP.md) |
| 如何啟動、收集、回補與診斷 | [操作手冊](docs/OPERATIONS.md) |
| 查完整契約與術語 | [文件索引](docs/README.md) |

## 開發入口

- [後端](backend/README.md)：FastAPI、SQLAlchemy／SQLite、資料 worker。
- [前端](frontend/README.md)：React、TypeScript、Vite、React Query、ECharts。
- [驗證方式](docs/development-baseline/README.md)：依變更選測試；現行入口仍會建立隔離目錄。
- [協作規則](AGENTS.md)與[接手狀態](docs/TASK_COORDINATION.md)：角色、驗收、索引、Git 及暫存政策。

API 啟動只做唯讀 schema readiness，不自動 migration；request handlers、worker 與設定載入仍可能寫入。啟動前依操作手冊確認資料路徑及授權。Git 保存程式與文件，不備份本機資料庫、raw、依賴或測試產物。
