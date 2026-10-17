# 台股研究專案

以免費公開資料做台股盤後研究輔助 app：每日排程更新上市／上櫃全市場行情、籌碼、國內外新聞與熱門族群，提供個股 K 線與技術指標、規則式進出點建議、明日候選清單與追蹤回看。版本範圍與進度見[開發路線](docs/ROADMAP.md)。

## 文件

| 主題 | 文件 |
| --- | --- |
| 產品方向與版本範圍 | [開發路線](docs/ROADMAP.md)、[產品規格](docs/PRODUCT_SPEC.md) |
| 前端設計 | [設計規範](docs/DESIGN_SYSTEM.md)、[文案、單位與詞彙](docs/UI_COPY_SPEC.md) |
| 資料與來源 | [資料來源](docs/DATA_SOURCES.md)、[產業分類](docs/INDUSTRY_CLASSIFICATION.md)、[新聞](docs/NEWS_SPEC.md) |
| 策略與指標 | [v1 公式與口徑](docs/V1_SPEC.md) |
| 啟動、收集、回補與排程 | [操作手冊](docs/OPERATIONS.md) |
| 協作與流程 | [協作規則](AGENTS.md)、[GitHub 工作手冊](docs/GITHUB_WORKFLOW.md)（含[本機檢查](docs/GITHUB_WORKFLOW.md#本機檢查)） |

## 開發入口

- [後端](backend/README.md)：FastAPI、SQLAlchemy／SQLite、資料 worker。
- [前端](frontend/README.md)：React、TypeScript、Vite、React Query、ECharts。
- [任務看板](https://github.com/users/YiCheng0608/projects/1)與[治理 Issue](https://github.com/YiCheng0608/stock-lab/issues/1)。

Git 只保存程式與文件，不備份本機資料庫、raw、依賴或測試產物。
