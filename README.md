# 台股研究專案

以免費公開資料做台股盤後研究輔助 app：每日排程更新上市／上櫃全市場行情、籌碼、國內外新聞與熱門族群，提供個股 K 線與技術指標、規則式進出點建議、明日候選清單與追蹤回看。版本範圍與進度見[開發路線](docs/ROADMAP.md)。

## 從這裡開始

| 想了解 | 入口 |
| --- | --- |
| 產品要解決什麼問題 | [產品規格](docs/PRODUCT_SPEC.md) |
| 現在做到哪裡、接下來做什麼 | [開發路線](docs/ROADMAP.md) |
| 前端長什麼樣子 | [設計規範](docs/DESIGN_SYSTEM.md) |
| 如何啟動、收集、回補與診斷 | [操作手冊](docs/OPERATIONS.md) |
| 查完整契約與術語 | [文件索引](docs/README.md) |

## 開發入口

- [後端](backend/README.md)：FastAPI、SQLAlchemy／SQLite、資料 worker。
- [前端](frontend/README.md)：React、TypeScript、Vite、React Query、ECharts。
- [本機檢查](docs/GITHUB_WORKFLOW.md#本機檢查)：後端、前端與 repo 檢查命令。
- [協作規則](AGENTS.md)與[GitHub 工作手冊](docs/GITHUB_WORKFLOW.md)：統籌＋工程師兩角色、Issue → worktree → PR → CI → merge。
- [任務看板](https://github.com/users/YiCheng0608/projects/1)與[治理 Issue](https://github.com/YiCheng0608/stock-lab/issues/1)。

Git 只保存程式與文件，不備份本機資料庫、raw、依賴或測試產物。API 啟動只做唯讀 schema readiness，不自動 migration。
