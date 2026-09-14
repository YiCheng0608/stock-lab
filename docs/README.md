# 文件索引與維護規則

產品方向查 [PRODUCT_SPEC](PRODUCT_SPEC.md)，進度與優先順序查 [ROADMAP](ROADMAP.md)，分批驗收查 [ROADMAP_EXECUTION](ROADMAP_EXECUTION.md)。

## 依工作選文件

| 工作 | 文件與責任 |
| --- | --- |
| 本機開發、測試、Git 基準 | [開發入口](development-baseline/README.md)、[操作手冊](OPERATIONS.md)；不要使用已刪除的 Temp 環境。 |
| 產品與研究流程 | [產品規格](PRODUCT_SPEC.md)、[個股研究頁](STOCK_RESEARCH_PAGE.md)、[UX review](UX_REVIEW.md)。 |
| 官方資料與時間來源 | [資料來源](DATA_SOURCES.md)、[來源 registry](SOURCE_REGISTRY.md)、[產業分類](INDUSTRY_CLASSIFICATION.md)。 |
| 新聞與事件 | [新聞契約](NEWS_SPEC.md)：來源、去重、時間、關聯及摘要邊界。 |
| 策略與研究有效性 | [策略](STRATEGIES.md)、[v1 基準](V1_SPEC.md)、[R0 實作契約](R0_IMPLEMENTATION.md)。 |
| 版本化研究資料 | [Signal artifact](SIGNAL_ARTIFACTS.md)、[離線比較](SIGNAL_COMPARISON.md)、[Pure-rule replay](RULE_REPLAY.md)、[Worker analysis capture](WORKER_ANALYSIS_CAPTURE.md)。 |
| 畫面用語 | [UI 文案](UI_COPY_SPEC.md)、[詞彙表](GLOSSARY.md)。 |
| 角色分工與每輪流程 | [AGENTS](../AGENTS.md)：模型、分派、驗收、索引、Git commit 與交接的唯一規則；[協作紀錄](TASK_COORDINATION.md)：角色 ID 與目前狀態。 |

## 現行能力與歷史資料

- 新舊策略版本分開。新 ATR 純核心不代表 worker 已切換，固定 confidence 不代表校準勝率。
- `signal-comparison/v1` 是 caller 指定快照的描述性比較；`rule-replay-bundle/v1` 是固定 source/config/CPython 下的 caller-input replay；Round34 worker capture只在 explicit external owned research DB保存actual legacy analysis calls。三者都不代表SignalArtifact bridge、完整B2/B7、PIT、default worker或產品接線已完成。
- 程式 schema head 是 `0006_news_json_defaults`；程式版本不證明某個實際資料庫已升級。實際 DB 狀態以有日期的驗證紀錄為準，不從舊 B6/0005 副本驗收推算現況。
- [Phase 3](PHASE3_PLAN.md)、[Phase 4](PHASE4_PLAN.md)、[舊統籌交接](COORDINATOR_HANDOFF_2026-09-12.md) 與協作紀錄的舊輪段落均屬歷史，不作目前派工指令。
- 2026-09-14 已移除不再使用的 Temp 歸檔及副本。舊文件中的 external/Temp 路徑、manifest、測試筆數只描述當時驗收，不表示附件仍存在，也不能當作新驗證結果。接手使用現行原始碼、測試與 Git 基準。

## 更新規則

變更時更新負責該契約的文件、ROADMAP 狀態及 ROADMAP_EXECUTION 對應項目；README 只維護入口。驗收註明日期、版本、範圍、結果與限制。來源未知、外部決策或前瞻觀測不足時保留待驗，不以 mock、較小範圍或歷史測試計數改稱完成。

文件與測試不是資料庫 migration、收集、服務重啟、排程、付費、帳戶或交易的操作授權。
