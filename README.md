# 台股研究專案

以免費公開資料支援台股盤後研究：今日關注 → 個股研究 → 條件計畫 → 追蹤回看。

已有官方資料收集／回補、v1 規則、行動摘要、持倉、技術回測及研究介面。M1 的5／20日法人窗口與研究判定、完整交易計畫／追蹤、分點分析及經驗證 AI 預測未完成；現有訊號不代表校準勝率。支援範圍與核心優先順序見[開發路線](docs/ROADMAP.md)。

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
- [驗證方式](docs/development-baseline/README.md)：入口、副作用、驗收範圍與落盤限制。
- [協作規則](AGENTS.md)與[GitHub 工作手冊](docs/GITHUB_WORKFLOW.md)：六角色、任務狀態、獨立 QA、索引與串行整合。
- [GitHub 遷移入口](docs/TASK_COORDINATION.md)：設定缺口與歷史紀錄；即時派工和交接只在 GitHub Issues／Projects。

API 啟動執行唯讀 schema readiness，不自動 migration。設定載入、request handlers 與 worker 的寫入入口及資料路徑須依操作手冊核對授權；readiness 通過不代表整個程序唯讀。Git 保存程式與文件，不備份本機資料庫、raw、依賴或測試產物。
