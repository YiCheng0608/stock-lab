# 協作與接手狀態

本文件只留目前角色、接手與下一步；流程依 [AGENTS](../AGENTS.md)，能力與優先順序查 [ROADMAP](ROADMAP.md)。

## 目前狀態（2026-09-27）

- 統籌已接受並 freeze R0-C4／B5b-core-1 的兩個程式檔：`caller-availability-cutoff/v1` 對 caller 宣告的必要輸入與 `time-evidence/v1` 精確配對，只檢查 UTC 決策截止時間；revision 與 live 分別加驗修訂可得及收集時間。unknown、date-only、粗精度、naive 與配對不全均 fail closed，並回傳逐輸入原因。結果固定 `required_inputs_completeness=caller_declared_only`、`availability_truth=not_asserted`、`point_in_time_status=not_asserted`。16 項純記憶體 unittest 通過，作為本輪純核心的有限驗收；確切命令、版本、exit、SHA、coverage 與 freeze 證據留原 task，文件角色未重跑。完整 B5b 尚未完成；契約見 [R0 實作 §7.3](R0_IMPLEMENTATION.md#73-r0-c4b5b-caller-declared-time-cutoff-純核心有限-review)。
- 既有 R0-C2／B4b 僅有 caller-input 盤後 long 假設純核心有限 review，不證 PIT 或成交。R0-B2 的 Bridge B、selected bar／prior volumes 本地 metadata 接線與獨立 verifier 各有限成果；verifier 只判定指定本地 selected-bar 證據一致，不證官方來源、歷史原件、其他衍生輸入或真實整合。精確範圍見 [Signal artifact §10](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與-bridge-b-有限成果)。
- B2 實際整合仍缺已授權可唯讀的完整 research snapshot、配對 body／receipt、exact attempt／ordinal 與 registry pins tuple。依賴未變前不重複搜尋、不建 specimen 或空轉輪次；既有未跑回歸維持待驗。新增落盤配額仍為 0，必要磁碟驗證須由統籌核對殘留並明示恢復；先前可復原的回收筒資料本輪未核查。
- R0／B2／B4b／B5b／B7 整體仍未完成。R35–38 成員與候選身分、回補範圍、來源日展示及獨立 UI 維護維持各自既有有限 review；完整歷史回算與 PIT 仍待驗。

### 角色與寫入分工

統籌已核對本輪四個新 task ID、共同專案目錄與接手；model／reasoning 採 [AGENTS](../AGENTS.md#四個角色) 核定配置。上輪 ID 由原 task 追溯。

| 角色 | task ID／model／reasoning | 寫入／驗收範圍 |
| --- | --- | --- |
| 統籌 | `01a0e161-e6b7-7c80-9c6a-84ad6c4dcc1e`；`gpt-6-astra`／`high` | 已接受並 freeze R0-C4 純核心有限程式範圍；負責文件 review、全輪 freeze 與索引／提交准入。 |
| 程式 | `01a0e162-205c-7731-9faf-24fde7479bd1`；`gpt-6-sol`／`ultra` | 僅新增 `backend/app/availability_gate.py`、`backend/tests/test_availability_gate.py`，交付純核心與測試證據；不改規格、不自行結案。 |
| 文件 | `01a0e162-210d-7c00-b9cf-ecfaa99e936e`；`gpt-6-sol`／`xhigh` | 僅更新本輪核准的四份既有文件與交接，交統籌 review；不改程式、不提交。 |
| 索引與 Git commit | `01a0e162-2203-7390-86e5-c6347fbe4a12`；`gpt-6-luna`／`medium` | 文件接受且全輪 freeze 後刷新涉及分區索引、驗 coverage，經統籌准入提交核准檔案；不改來源。 |

## 接續範圍

1. 已完成及驗收邊界：R0-C4／B5b-core-1 只完成 caller-supplied time-cutoff 純核心有限 review；逐輸入 cutoff 通過也只表示宣告集合在宣告時間內。既有 B2、B4b 成果仍各限原 review 範圍，R0 整體未完成。
2. 尚缺項：完整 B5b 仍需實際必要依賴、來源真實性與首次可得證據、store／worker／產品接線、修訂／回補及歷史決策驗證、合法 earliest execution 與 PIT gate；B2 仍缺完整 specimen／pins tuple、實際整合及同 snapshot legacy-v2 paired replay。純核心結果不證成交或正式交易核准。
3. 下一步與依賴／完成條件：依 [執行清單 R0-C4／C5](ROADMAP_EXECUTION.md#r0-c價位時間與-paired-replay) 接續可追溯來源與完整依賴的 B5b 整合驗收，再與 B2／B4b 進 B7 同 snapshot 比較；缺 specimen 時 B2 保持待驗，不開空轉輪次。必要磁碟驗證仍受配額限制，其他工作依各自 gate 推進。角色不自行結案或啟動下一輪。
4. 本輪文件僅更新統籌白名單，待統籌 review 與接受；全輪 freeze、索引與 commit 尚未宣告完成。

## 歷史與維護

舊角色 ID、交付狀態、測試及 commit 證據由 [Git／原 task](README.md#歷史查閱) 追溯；舊分派不覆蓋 AGENTS，也不恢復已刪除附件或舊統籌派工權。更新本文件時替換目前狀態，不追加逐輪日誌。
