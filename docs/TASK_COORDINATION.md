# 協作與接手狀態

流程與角色配置由 [AGENTS](../AGENTS.md) 管理；能力與優先順序見 [ROADMAP](ROADMAP.md)，工作完成條件見 [執行清單](ROADMAP_EXECUTION.md)。

## 目前：獨立文件維護

2026-10-04，使用者授權修正跨 ROUND 核心優先規則，並檢查全部文件的冗言與確定性。本次使用 master 原 checkout，起始 HEAD 為 `5ae84d2fe5ce1d82bf4d168bffdcbf1262848caa`；不是產品 round，不建立或恢復產品任務。

共同 cwd：`C:/Users/YiCheng/Desktop/taiwan-stock-research`；branch：`master`。以下實際配置已由 runtime session_meta／turn_context 及 Git 核實，兩子角色 parent 均為本次統籌。

| 角色 | session ID／實際配置 | 寫入範圍與接手 |
| --- | --- | --- |
| 維護統籌 | `01a105a2-2067-7803-a0b8-0c4d6a1b02c1`；`gpt-6.1-sol`／`xhigh` | AGENTS、根 README、docs README、ROADMAP、ROADMAP_EXECUTION、TASK_COORDINATION；負責 review／freeze。獨立維護不作產品 ultra 啟動驗收。 |
| 文件 | `01a105be-4f58-7db0-9170-3021caa0cbbb`；`gpt-6.1-sol`／`xhigh` | 其餘23份既有 Markdown，已接手；只改文件。 |
| 索引與 Git commit | `01a105be-87e7-72b2-b610-b56c24e277ca`；`gpt-6-luna`／`medium` | 已接手；接受 aggregate freeze 後刷新相關原分區、驗 coverage、提交核准檔案。 |

範圍為29份 Git 管理的 Markdown；requirements／lock 是機器設定，不修改。起始文件總量779,037 bytes，本次總量上限811,805 bytes；新增專案文件、測試、附件、暫存與測試殘留均為0，不跑 backend 或建 DB，不清舊資源。App MCP 連線成功；已有分區 ready，相關文件 metadata_changed 已補讀原文。來源審查、文件驗證、freeze、索引及最終 commit 收據留本 task，不為回寫 hash 再提交。

必要索引只刷新原 docs／frontend-full，persistence=false，不建新分區或目錄。兩個既有 DB 合計上限64 MiB，六個已知 WAL／SHM／journal合計8 MiB，工具回傳的新 logs 最多2檔／8 KiB；索引DB保留供後續查詢。只核這些 exact 路徑，不掃shared cache；只清本次工具回傳的自有成功logs，核絕對路徑、ancestors非reparse及exclusive unused後刪除，失敗分報，既有NO-RETRY項不動。

## 最近產品交付與原 roster

M3-P6e 特徵／籌碼獨立讀回隔離已有限接受，其16檔提交 `5ae84d2` 已在 master，包含主線文件維護 `453ca2b`；前輪 P6d 版本為 `0f8ac4a`。本次 Git 盤點只列 master 原 checkout；產品 session／terminal 的關閉與封存狀態沿用原 task，不從 Git 推定。

P6e 原 worktree：`C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-m3-stock-detail-independent-read-isolation-20261004`；branch 同目錄名；起始 HEAD：`0f8ac4ab3af8ec44353c2181eb18ae3c9a9fe6cb`。原可見 terminal：`term_935e0735-4482-4cda-88a7-c60a0fadcc68`。

| 原產品角色 | session ID | 已核實配置 |
| --- | --- | --- |
| 統籌 | `01a104ef-f17a-7f81-9ba6-c2d7483d6891` | `gpt-6.1-sol`／`ultra` |
| 程式 | `01a104f2-0748-74a1-bc7a-1bc97afe4433` | `gpt-6.1-sol`／`xhigh` |
| 文件 | `01a104f2-50d4-79e2-96a2-d4f9ccb864f8` | `gpt-6.1-sol`／`xhigh` |
| 索引與 Git commit | `01a104f2-91b0-7ec3-94b0-ccc982949b5a` | `gpt-6-luna`／`medium` |

原角色不作新輪 roster，已交接舊統籌不得重派。M2-P2 後的停止要求已由後續明確恢復授權解除；本次授權限獨立文件維護，不建立或接手下一產品輪。

P6e 已接受兩表讀回隔離、必要 API／App、六個具名桌面操作與同 fixture 六表不變；原生／DOM.click 範圍見[個股頁 §17](STOCK_RESEARCH_PAGE.md#17-m3-p6e個股特徵籌碼獨立區塊讀回隔離)。未增加多日法人、新 Plan 或完整 M1／M3。P6c 有效歷史窄版溢出未通過，physical canvas、真正截止表單提交及其他未覆蓋 typed／legacy 讀回仍待驗。正式 DB、官方／availability／PIT、正向原件及必要磁碟 gate 保留。

## 下一核心目標與跨輪停滯

| 接手項目 | 狀態與動作 |
| --- | --- |
| 優先核心目標 | M1：接通5／20交易日法人窗口。第一缺口是所採市場／標的的多日原件與完整交易日證據；計算及 API／UI 接線完成後，使用者才能在同一截止查看可追溯窗口。 |
| 派工前條件 | 新產品統籌依啟動流程建立並接手，再核實來源取得路徑、用途准入、日期／單位／修訂／缺日 coverage，核定單一批次與完成條件。未取得證據不宣稱依賴解除。 |
| 改選條件 | M1 沒有新的可執行取得路徑時，選必要 gate 已滿足的最小 M3 計畫操作，列具名資料與合法執行／保存條件；仍無可執行核心項時記等待，不建立隔離或重複審查輪。 |
| 最近兩個已驗收交付 | P6d、P6e 均為讀回可靠性改善；未接多日法人或新 Plan，未解除已列核心來源／時間依賴。 |
| 連續未推進核心批次 | 至少2批：上述兩輪各有已接受實作，依新規則均不計核心操作或核心依賴解除；更早批次未重算。下一批派工前須重新選題；新統籌繼承此下限，不歸零。 |
| 本次維護 | 文件規則變更，不是產品實作批次；不增加或重置上述計數。 |

M1 的來源、計算、產品驗收與 M3 的必要 gate 見[執行清單 §2.1](ROADMAP_EXECUTION.md#21-近期里程碑接線映射)。新統籌確認核心目標、依賴、完成條件與停滯紀錄後才派工；改選理由留原 task。

## 未解驗證與資源限制

下表沿用整理前最後已知收據；本次未重新盤點或清理，不作即時刪除 gate。已刪除項不重做；審核拒絕項不得重試、換工具、掃共享目錄或刪父目錄。精確歷史收據由 Git `5ae84d2:docs/TASK_COORDINATION.md` 與對應原 task 查閱。

| 項目 | 最後已知結果／後續限制 |
| --- | --- |
| R0-B2 verifier | 完整 snapshot／body／receipt／registry pins tuple 未齊，真實檔案／snapshot 整合待驗，70個既有案例未跑；不重複搜尋或建 fixture 冒稱來源接入。 |
| P6d 五 DB 刪前流程 | 五 DB／十五 aux 與兩 logs 刪後缺席已驗；刪前只核 leaf／exclusive open，未核 all ancestors 與十五 aux。不得追認完整刪前 gate；不補刪除或重試。 |
| P6c blocked logs | 兩個 logs 共717 bytes（295／422 bytes）；immediate gate／刪除均在 CreateProcess 前被拒，未執行，NO-RETRY。兩完整路徑見下方。 |
| P4 blocked logs | 兩個 logs 共713 bytes（293／420 bytes）；刪除被拒，未執行，NO-RETRY。兩完整路徑見下方。 |
| P2 HAR | `C:/Users/YiCheng/.agent-browser/tmp/har/har-1791044803009.har`，64,885 bytes；清理遭審核拒絕，未執行，NO-RETRY。 |
| P1 index logs | 3個共1,139 bytes；295 bytes 項刪除被拒，另兩個各422 bytes未嘗試。精確路徑留原 storage task；未清，不得推定全清。 |
| M1 成交量舊 worktree | `C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-m1-volume-exact-presentation-20261003`，最後3,528,690 bytes；worktree／branch移除被拒，NO-RETRY。索引／logs已清不代表該根已清。 |
| legacy volume 整合空根 | `C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-r1-a2-legacy-volume-integration-20261003`，最後0 bytes；空目錄被占用，刪除失敗，不重試。PTY終止未核。 |
| selected-invalid 空根／logs | `C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-r1-a2-selected-invalid-20261003`，最後0 bytes；空根被占用，刪除失敗。兩logs共628 bytes被拒，未刪；更早兩logs共545 bytes亦被拒。路徑留原task，NO-RETRY。 |
| M1-P2a 測試根 | `C:/Users/YiCheng/AppData/Local/Temp/taiwan-stock-m1p2a-01a0fe7e`，243 entries／11 files／993,443 bytes，已超原entries上限；code-tests／live清理被拒，未執行。conftest另建的default Temp _TEST_ROOT名稱／大小未知，不掃Temp猜測。 |
| 更早 M1 測試根 | `C:/Users/YiCheng/AppData/Local/Temp/taiwan-stock-m1-01a0fe5a`，118 entries／105 files／17,319,956 bytes；UI／code-tests清理被拒，未執行。 |
| 後續落盤 | 繼承原零新增測試／附件／暫存／殘留限制。必要磁碟驗收保持待驗；不得換session、根目錄或改名重置上限。 |

四個已知 blocked log 的完整路徑：

- `C:/Users/YiCheng/cbm-cache/logs/taiwan-stock-research-roadmap-m3-stock-detail-quote-read-isolation-20261004-backend-tests-1791076431.log`
- `C:/Users/YiCheng/cbm-cache/logs/taiwan-stock-research-roadmap-m3-stock-detail-quote-read-isolation-20261004-tools-1791076500.log`
- `C:/Users/YiCheng/cbm-cache/logs/taiwan-stock-research-roadmap-m3-portfolio-value-read-validation-20261004-backend-tests-1791054858.log`
- `C:/Users/YiCheng/cbm-cache/logs/taiwan-stock-research-roadmap-m3-portfolio-value-read-validation-20261004-tools-1791054866.log`

## 歷史與維護

只更新現況、下一核心交接與未解限制，不追加逐輪流水。歷史 roster／實際模型、首跑失敗／補驗、freeze／索引／commit／merge 及清理收據留 Git／原 task；舊分派不恢復派工權。查閱方式見[文件索引](README.md#歷史查閱)。
