# 協作與接手狀態

本文件只留目前角色、接手與下一步；流程依 [AGENTS](../AGENTS.md)，能力與優先順序查 [ROADMAP](ROADMAP.md)。

## 目前狀態（2026-09-16）

- ROADMAP 停在 R39：SignalArtifact bridge A 的映射／缺口已有限 review，B adapter 尚未實作；本次維護不恢復或啟動下一輪。
- R35–38 的成員與候選身分、回補範圍、來源日展示已分別有限 review；完整歷史回算與 PIT 仍缺，細節見[產業分類 §8–9](INDUSTRY_CLASSIFICATION.md#8-群組衍生成員報酬的身分契約有限-review)。
- 獨立 UI 維護已完成繁中、法人命名、空數值、表外單位及官方分點入口；[籌碼三部分](STOCK_RESEARCH_PAGE.md#8-籌碼三部分後續待做)已列後續待做，尚未接入分點交易資料。

### 獨立文件整理（非 ROADMAP round）

本次已檢查 29 份專案文件，精簡重複規則與歷史敘事；保留有效規格、驗收邊界及待辦，未修改程式或資料。統籌已接受各組交付與獨立唯讀 review，完成差異、連結及結構檢查後 freeze；最終索引／Git receipt 留本 task。

| 角色 | task ID | 寫入／驗收範圍 |
| --- | --- | --- |
| 統籌 | `01a0a59b-e010-7af1-955c-3ba6fbbdf247`（`/root`） | 治理、入口、路線與交接文件；統整差異、連結與範圍驗收。 |
| 文件：產品 | `/root/docs_product_cleanup` | 產品、新聞、策略、v1、詞彙、文案、個股頁、UX。 |
| 文件：資料 | `/root/docs_data_cleanup` | 資料來源、產業分類、來源准入、操作手冊。 |
| 文件：保存與重播 | `/root/docs_replay_cleanup` | R0、Signal artifact、比較、replay、worker capture。 |
| 索引／Git | `/root` 代執行 | 協作工具因任務數上限無法啟動索引角色；由統籌在驗收／freeze 後更新索引，只提交核准文件。 |

## 接續範圍

1. 文件整理完成後維持現有 ROADMAP 狀態，最終 freeze／索引／commit receipt 留本 task。
2. 下一個開發候選仍是[執行清單 R0-B2](ROADMAP_EXECUTION.md#r0-b版本化-artifact-與-atr)：先核定具明確路徑／雜湊、attempt／ordinal 及新研究決策的 capture→candidate adapter。Candidate 與 caller save 分開，不預核 consumer、paired replay 或預設切換。
3. 來源、可得時間、完整歷史輸入、PIT 及 B7 仍待驗；capture receipt 或 owner source hash 不能代替來源與輸入證據。完整邊界見 [Signal artifact §10](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與下一候選)。

## 歷史與維護

舊角色 ID、交付狀態、測試及 commit 證據由[Git／原 task](README.md#歷史查閱)追溯；舊分派不覆蓋 AGENTS，也不恢復已刪除附件或舊統籌派工權。更新本文件時替換目前狀態，不追加逐輪日誌。
