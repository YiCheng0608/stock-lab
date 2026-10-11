# 文件索引

## 依角色先讀

所有角色先讀 [AGENTS](../AGENTS.md) 與被派 Issue 的本文及最新交接，再按階段只讀下表；大檔用標題與搜尋定位，不整檔讀，見[讀取成本](GITHUB_WORKFLOW.md#讀取交接與證據成本)。

| 角色 | 加讀 |
| --- | --- |
| 全局／任務統籌 | [工作手冊](GITHUB_WORKFLOW.md)、[ROADMAP](ROADMAP.md)、[PRODUCT_SPEC](PRODUCT_SPEC.md)（盤點或範圍變更時） |
| 工程師 | Issue 指定的主題契約、[開發入口](development-baseline/README.md)的[版本與資料](development-baseline/README.md#版本與資料)、[後端驗證](development-baseline/README.md#後端驗證)、[OPERATIONS](OPERATIONS.md) 相關節 |
| QA | Issue 原 AC 與指定契約、手冊的[失敗分流](GITHUB_WORKFLOW.md#失敗分流與有界重驗)與[QA 模板](GITHUB_WORKFLOW.md#qa-與退修)、[測試資料庫分層](development-baseline/README.md#測試資料庫分層) |
| 文件 | 本頁「文件維護」、受影響的主題契約 |
| 索引／Git | 手冊的[程式索引](GITHUB_WORKFLOW.md#任務識別與程式索引)與[整合模板](GITHUB_WORKFLOW.md#整合與結案) |

## 按需要查契約

| 主題 | 文件 |
| --- | --- |
| 資料與來源 | [來源／coverage](DATA_SOURCES.md)、[來源准入與 capture](SOURCE_REGISTRY.md)、[產業分類／成員期間](INDUSTRY_CLASSIFICATION.md) |
| 策略與研究 | [策略設計與有效性](STRATEGIES.md)、[v1 基準](V1_SPEC.md)、[R0 實作邊界](R0_IMPLEMENTATION.md)、[術語](GLOSSARY.md) |
| 新聞與介面 | [新聞](NEWS_SPEC.md)、[文案／單位](UI_COPY_SPEC.md)、[個股研究頁](STOCK_RESEARCH_PAGE.md)、[UX review 範圍](UX_REVIEW.md) |
| 保存與重播 | [Signal artifact](SIGNAL_ARTIFACTS.md)、[離線描述比較](SIGNAL_COMPARISON.md)、[Pure-rule replay](RULE_REPLAY.md)、[Worker capture](WORKER_ANALYSIS_CAPTURE.md) |
| 開發協作 | [AGENTS](../AGENTS.md)、[GitHub 遷移入口](TASK_COORDINATION.md)、[工作手冊與模板](GITHUB_WORKFLOW.md)、[驗證入口](development-baseline/README.md)、[後端](../backend/README.md)、[前端](../frontend/README.md) |

即時任務、依賴、排序、狀態、接手及停滯紀錄只在 GitHub Issues／Projects；[遷移入口](TASK_COORDINATION.md)提供連結與歷史。

[ROADMAP_EXECUTION](ROADMAP_EXECUTION.md)（歷史 R0–R3 拆解）、[Phase 3](PHASE3_PLAN.md)、[Phase 4](PHASE4_PLAN.md)與[舊統籌交接](COORDINATOR_HANDOFF_2026-09-12.md)只保留歷史定位，不作新派工依據。

## 文件維護

依上表分工：權責與驗收寫 AGENTS，操作／欄位／模板寫 GITHUB_WORKFLOW，產品方向與能力寫 ROADMAP，精確行為及長期驗收邊界寫主題契約；其他處只放摘要與連結。文件更新依 [AGENTS](../AGENTS.md#文件與交接)，不增加功能完成度或操作授權。

## 歷史查閱

`5ae84d2` 保存整理前 29 份 Markdown，例如 `git show 5ae84d2:docs/TASK_COORDINATION.md`。更早整理前版本為 `69f62cf`、`2acc3c5`。TASK_COORDINATION、ROADMAP、ROADMAP_EXECUTION 移出的改造前歷史段，以 `46eb244` 版本為準（例如 `git show 46eb244:docs/ROADMAP.md`）。歷史收據查 Git／原 task，不作新驗收。
