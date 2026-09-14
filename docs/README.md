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

[Phase 3](PHASE3_PLAN.md)、[Phase 4](PHASE4_PLAN.md)與[舊統籌交接](COORDINATOR_HANDOFF_2026-09-12.md)只保留歷史定位，不作新派工依據。

## 文件維護

- 同一規則只在負責的契約詳述，其他文件放摘要與連結；ROADMAP 管優先順序，執行清單管驗收，協作紀錄只保留接手必要資訊。
- 更新現行段落，不把每輪敘事、測試筆數、長雜湊、Temp 路徑或完整交付報告反覆追加。原始命令、結果、限制與 commit receipt 留在 task。
- 保留有效公式、欄位、錯誤語意、未完成項及來源日期；`已 review` 只代表具名有限範圍，不把 schema、fixture 或歷史測試數當成產品完成。
- 2026-09-14 精簡前的完整文件位於 Git `69f62cf`，例如 `git show 69f62cf:docs/TASK_COORDINATION.md`。這能取閱舊文字，不能恢復已清除的 Temp 附件，也不代表它們仍可作新驗收證據。
- 文件整理不包含 DB 操作、服務重啟、排程、採購、帳戶或交易授權。暫存與測試選擇依 [AGENTS](../AGENTS.md#驗證資料與暫存)。
