# 文件索引

## 先讀這四份

| 文件 | 負責的問題 |
| --- | --- |
| [PRODUCT_SPEC](PRODUCT_SPEC.md) | 使用者、產品方向、主要流程與範圍。 |
| [ROADMAP](ROADMAP.md) | 目前能力、優先順序與待決定事項。 |
| [ROADMAP_EXECUTION](ROADMAP_EXECUTION.md) | 工作 ID、依賴、狀態與驗收完成條件。 |
| [OPERATIONS](OPERATIONS.md) | 啟動、資料路徑、CLI、收集／回補與診斷。 |

## 按需要查契約

| 主題 | 文件 |
| --- | --- |
| 資料與來源 | [來源／coverage](DATA_SOURCES.md)、[來源准入與 capture](SOURCE_REGISTRY.md)、[產業分類／成員期間](INDUSTRY_CLASSIFICATION.md) |
| 策略與研究 | [策略設計與有效性](STRATEGIES.md)、[v1 基準](V1_SPEC.md)、[R0 實作邊界](R0_IMPLEMENTATION.md)、[術語](GLOSSARY.md) |
| 新聞與介面 | [新聞](NEWS_SPEC.md)、[文案／單位](UI_COPY_SPEC.md)、[個股研究頁](STOCK_RESEARCH_PAGE.md)、[UX review 範圍](UX_REVIEW.md) |
| 保存與重播 | [Signal artifact](SIGNAL_ARTIFACTS.md)、[離線描述比較](SIGNAL_COMPARISON.md)、[Pure-rule replay](RULE_REPLAY.md)、[Worker capture](WORKER_ANALYSIS_CAPTURE.md) |
| 開發協作 | [AGENTS](../AGENTS.md)、[接手狀態](TASK_COORDINATION.md)、[驗證入口](development-baseline/README.md)、[後端](../backend/README.md)、[前端](../frontend/README.md) |

角色模型與 Reasoning 以 [AGENTS「四個角色」](../AGENTS.md#四個角色)為準；新建或恢復角色時須核對該配置。實際 session／建立參數、接手與暫停狀態由[協作紀錄](TASK_COORDINATION.md)負責，修改規則不會自動切換既有 chat，也不改寫舊 session 的實際紀錄。

[Phase 3](PHASE3_PLAN.md)、[Phase 4](PHASE4_PLAN.md)與[舊統籌交接](COORDINATOR_HANDOFF_2026-09-12.md)只保留歷史定位，不作新派工依據。

## 文件維護

同一規則只在上表的負責文件詳述，其他處放摘要與連結；更新與交接依 [AGENTS](../AGENTS.md#文件與交接)。`已 review` 僅代表具名有限驗收，文件整理不增加功能完成度或操作授權。

## 歷史查閱

2026-09-14 精簡前的文件在 Git `69f62cf`；本次全面整理前的版本在 `2acc3c5`，例如 `git show 2acc3c5:docs/TASK_COORDINATION.md`。歷史命令、測試數與逐輪交付由 Git／原 task 追溯，不作目前來源的新驗收，也不能恢復已刪除的 Temp 附件。
