# 文件索引

## 先讀這四份

| 文件 | 負責的問題 |
| --- | --- |
| [PRODUCT_SPEC](PRODUCT_SPEC.md) | 使用者、產品方向、主要流程與範圍。 |
| [ROADMAP](ROADMAP.md) | 目前能力、優先順序與待決定事項。 |
| [ROADMAP_EXECUTION](ROADMAP_EXECUTION.md) | 歷史工作 ID、拆解與驗收邊界；不管理即時任務狀態。 |
| [OPERATIONS](OPERATIONS.md) | 啟動、資料路徑、CLI、收集／回補與診斷。 |

## 按需要查契約

| 主題 | 文件 |
| --- | --- |
| 資料與來源 | [來源／coverage](DATA_SOURCES.md)、[來源准入與 capture](SOURCE_REGISTRY.md)、[產業分類／成員期間](INDUSTRY_CLASSIFICATION.md) |
| 策略與研究 | [策略設計與有效性](STRATEGIES.md)、[v1 基準](V1_SPEC.md)、[R0 實作邊界](R0_IMPLEMENTATION.md)、[術語](GLOSSARY.md) |
| 新聞與介面 | [新聞](NEWS_SPEC.md)、[文案／單位](UI_COPY_SPEC.md)、[個股研究頁](STOCK_RESEARCH_PAGE.md)、[UX review 範圍](UX_REVIEW.md) |
| 保存與重播 | [Signal artifact](SIGNAL_ARTIFACTS.md)、[離線描述比較](SIGNAL_COMPARISON.md)、[Pure-rule replay](RULE_REPLAY.md)、[Worker capture](WORKER_ANALYSIS_CAPTURE.md) |
| 開發協作 | [AGENTS](../AGENTS.md)、[GitHub 遷移入口](TASK_COORDINATION.md)、[工作手冊與模板](GITHUB_WORKFLOW.md)、[驗證入口](development-baseline/README.md)、[後端](../backend/README.md)、[前端](../frontend/README.md) |

角色配置、核心選題與停滯判定以 [AGENTS](../AGENTS.md) 為準；即時任務、母子／依賴、優先級、狀態、session 接手及停滯紀錄只在 GitHub Issues／Projects 管理。[遷移入口](TASK_COORDINATION.md)保留連結與舊紀錄，不作即時台帳。

[Phase 3](PHASE3_PLAN.md)、[Phase 4](PHASE4_PLAN.md)與[舊統籌交接](COORDINATOR_HANDOFF_2026-09-12.md)只保留歷史定位，不作新派工依據。

## 文件維護

按上表分工：流程規則寫 AGENTS，欄位與模板寫 GITHUB_WORKFLOW，產品方向與能力寫 ROADMAP，精確行為及長期驗收邊界寫主題契約；任務條件、排序、狀態、決策及交接只寫 GitHub Issue／Project。ROADMAP_EXECUTION、TASK_COORDINATION 的舊紀錄供追溯，其他處放摘要與連結。文件更新依 [AGENTS](../AGENTS.md#文件與交接)，不增加功能完成度或操作授權。

## 歷史查閱

本次整理前的29份 Markdown 在 Git `5ae84d2`，例如 `git show 5ae84d2:docs/TASK_COORDINATION.md`。更早整理前版本為 `69f62cf`、`2acc3c5`。歷史命令、測試數、實際 roster 與逐輪收據查 Git／原 task；不作目前來源的新驗收。
