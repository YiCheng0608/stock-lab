# 台股研究專案

以免費公開資料做台股盤後研究輔助 app：每日排程更新上市／上櫃全市場行情、籌碼、國內外新聞與熱門族群，提供個股 K 線與技術指標、規則式進出點建議、明日候選清單與追蹤回看。版本範圍與進度見[開發路線](docs/ROADMAP.md)。

## 文件

| 主題 | 文件 |
| --- | --- |
| 產品方向與版本範圍 | [開發路線](docs/ROADMAP.md)、[目前產品能力](docs/CAPABILITIES.md)、[產品規格](docs/PRODUCT_SPEC.md) |
| 前端設計 | [設計規範](docs/DESIGN_SYSTEM.md)、[文案、單位與詞彙](docs/UI_COPY_SPEC.md) |
| 資料與來源 | [資料來源](docs/DATA_SOURCES.md)、[產業分類](docs/INDUSTRY_CLASSIFICATION.md)、[新聞](docs/NEWS_SPEC.md) |
| 策略與指標 | [v1 公式與口徑](docs/spec/README.md)（[breakout／pullback](docs/spec/breakout_pullback.md)、[hot_group](docs/spec/hot_group.md)、[candidate_score](docs/spec/candidate_score.md)、[strategy_levels](docs/spec/strategy_levels.md)、[技術指標](docs/spec/indicators.md)、[tracking](docs/spec/tracking.md)、[題材建議](docs/spec/theme_suggestions.md)） |
| 啟動、收集、回補與排程 | [環境、啟停與資料庫](docs/ops/SETUP.md)、[worker CLI](docs/ops/CLI.md)、[排程](docs/ops/SCHEDULING.md)、[看門狗](docs/ops/WATCHDOG.md)、[事件 monitor](docs/ops/MONITOR.md)、[Windows 回退](docs/ops/platform/windows.md)、[本機路徑](docs/ops/LOCAL.md) |
| 協作與流程 | [協作規則](AGENTS.md)、[GitHub 工作手冊](docs/WORKFLOW.md)（含[本機檢查](docs/WORKFLOW.md#本機檢查)）、[統籌手冊](docs/COORDINATOR.md)、[規則與強制手段](docs/GUARDRAILS.md)、[發佈與部署](docs/RELEASE.md) |

## 開發入口

- [後端](backend/README.md)：FastAPI、SQLAlchemy／SQLite、資料 worker。
- [前端](frontend/README.md)：React、TypeScript、Vite、React Query、ECharts。
- [任務看板](https://github.com/users/YiCheng0608/projects/1)與[治理 Issue](https://github.com/YiCheng0608/stock-lab/issues/1)。

Git 只保存程式與文件，不備份本機資料庫、raw、依賴或測試產物。
