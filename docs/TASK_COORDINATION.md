# 協作與接手狀態

本文件只留目前角色、接手與下一步；流程依 [AGENTS](../AGENTS.md)，能力與優先順序查 [ROADMAP](ROADMAP.md)。

## 目前狀態（2026-09-27）

- 統籌已接受並 freeze R1-A2-P1-identity 的三個程式檔：`verified_taiex_sessions` 與 backfill `taiex_rows` 的 TAIEX／TWII index bar 計數新增 TWSE exchange 條件；TPEx 同名 index 不增加 session 分母、`taiex_rows` 或普通股票有效 bar 日。session 校驗既有日期、類型、status、provenance 與 raw fallback gate 保留；合法 TWSE benchmark 仍可供兩市場股票共用。這僅是 exchange identity 小批的有限 review，不證逐欄／全市場 coverage、真實官方 session、歷史完整性或 PIT；契約邊界見 [TAIEX session identity](DATA_SOURCES.md#taiex-session-identity)。
- 程式角色交付的獨立記憶體 runner 驗證了 TPEx-only 反例、TWSE aliases、兩市場同名股票及 raw fallback；統籌已接受該有限證據。文件角色未重跑程式測試。完整 pytest conftest／full pytest、檔案／正式 DB、capture 與 live fetch 均未執行；測試命令、版本、exit、case count、hash、zero-artifact 與 freeze 證據留原 task。新增落盤配額為 0。
- 未解逐欄問題：TAIEX close-only parser 以 close 填 O／H／L、volume／amount 填 0；legacy 缺 `TradeValue` 時 `turnover=0`，`TradeVolume` 小數可能截整。列／日期 count 不能證明欄位用途 available；須續查 model／schema／storage／consumer，本輪未修 parser、保存或產品接線。
- 上輪 R0-C4／B5b-core-1 及 R0-C2／B4b 純核心仍只在原有限 review 範圍內；完整 B5b／B4b／R0 未完成。R0-B2 的本地 selected-bar 證據 verifier 與 metadata 接線仍缺已授權可唯讀的完整 snapshot、配對 body／receipt、exact attempt／ordinal 與 registry pins tuple；依賴未變前保持待驗，不重複搜尋或建 specimen。R35–38 與獨立 UI 維護保留各自既有有限 review，歷史回算與 PIT 仍待驗。

### 角色與寫入分工

統籌已核對本輪四個新 task ID、共同專案目錄與接手；model／reasoning 採 [AGENTS](../AGENTS.md#四個角色) 核定配置。上輪 ID 由原 task 追溯。

| 角色 | task ID／model／reasoning | 寫入／驗收範圍 |
| --- | --- | --- |
| 統籌 | `01a0e18b-f544-7681-8fde-89ad38f4bdb6`；`gpt-6-astra`／`high` | 已接受並 freeze R1-A2-P1-identity 三個程式檔；負責文件 review、全輪 freeze 與索引／提交准入。 |
| 程式 | `01a0e18b-f5f6-7403-86be-19fe57dab485`；`gpt-6-sol`／`ultra` | 僅修改 `backend/app/coverage.py`、`backend/worker/backfill.py` 並新增 `backend/tests/test_taiex_session_identity.py`；不改規格、不自行結案。 |
| 文件 | `01a0e18b-f6ae-7280-98b8-922993709eb8`；`gpt-6-sol`／`xhigh` | 僅更新 `DATA_SOURCES.md`、`ROADMAP_EXECUTION.md`、`TASK_COORDINATION.md`，交統籌 review；不改程式、不提交。 |
| 索引與 Git commit | `01a0e18b-f773-7cf2-8227-f697e6ea744d`；`gpt-6-luna`／`medium` | 文件接受且全輪 freeze 後刷新涉及分區索引、驗 coverage，經統籌准入提交核准檔案；不改來源。 |

## 接續範圍

1. 已完成及驗收邊界：R1-A2-P1-identity 的 TWSE TAIEX／TWII exchange identity 窄修正已 review，三程式檔已 freeze；R1-A2 整體仍提案／未完成。既有 R0-C4／B5b-core-1、B2、B4b 成果仍各限原 review 範圍。
2. 尚缺項：R1-A2 仍需官方行情／TAIEX／法人／融資的逐市場、標的、session 及欄位用途 coverage，釐清上述合成／截斷欄位與 model／schema／storage／consumer；真實來源、availability／revision、歷史完整性與 PIT 均未驗。B2 specimen／pins 依賴與完整 B5b 等 R0 接線缺口未變。
3. 下一步與依賴／完成條件：依 [R1-A2 執行列](ROADMAP_EXECUTION.md) 核查逐欄來源至 consumer 的資料路徑，再以具名實際證據驗逐市場 coverage；缺證據保持待驗，不以日期／列數或 fixture 替代。B2 缺 specimen 時仍待驗；新增落盤測試受配額 0 限制，其餘工作依既有 gate 推進。角色不自行結案或啟動下一輪。
4. 文件差異待統籌 review 與接受；全輪 freeze、索引與 commit 尚未宣告完成。索引對既有文件為 `metadata_changed`、新增測試為 `not_tracked`，留待輪末索引角色處理。

## 歷史與維護

舊角色 ID、交付狀態、測試及 commit 證據由 [Git／原 task](README.md#歷史查閱) 追溯；舊分派不覆蓋 AGENTS，也不恢復已刪除附件或舊統籌派工權。更新本文件時替換目前狀態，不追加逐輪日誌。
