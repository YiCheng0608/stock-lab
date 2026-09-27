# 協作與接手狀態

本文件只留目前角色、接手與下一步；流程依 [AGENTS](../AGENTS.md)，能力與優先順序查 [ROADMAP](ROADMAP.md)。

## 目前狀態（2026-09-27）

- 既有 [R0-B2 Bridge B](ROADMAP_EXECUTION.md#r0-b版本化-artifact-與-atr) 的 opt-in prior volumes 接線已由統籌限制性接受為有限 review 並本地提交：`selected-bar-prior-volumes/v1` 將本次實際最多 20 筆有序歷史列封存為 `worker-analysis-capture/v3`；bridge 依 v3 產 detached candidate，caller save 仍須明示。這是目前可證的實作邊界，不代表全模組或整體功能驗收。
- 上一輪獨立 `STOCK_DAY_ALL` selected-bar verifier 六檔成果已由統籌限制性接受、freeze、更新索引並本地提交 `4d2cf2f17b0a068682951ba15887e8c4352aa3a7`；這是本輪既有基線，不是待提交工作。`verify_selected_bar_evidence` 對 caller 指定的 current snapshot SHA、exact attempt／ordinal、raw FK 所指 `body.bin`／同目錄 `receipt.json`，以及外部 receipt SHA／registry version／digest pins 作唯讀核對；成功只回 detached `stock-day-selected-bar-evidence/v1`／`local_evidence_consistent`／`selected_bar_only`。v2／v3 只驗 selected bar，v3 prior volumes 不升格；既有 capture／bridge／consumer 未改，`bytes_unverified` 不變。Receipt 外部 pin 不能證 capture 當時原件；registry `source_version` 只證本次本地規格 pin，不證官方或歷史真實性。完整 API、拒絕條件與限制見 [Signal artifact §10](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與-bridge-b-有限成果)。
- 上一輪 verifier 的執行證據來自使用者在當時統籌 task 的回報：bundled Python `-B` 直接執行 unittest 12 項 passed（避開會建立暫存資料夾的 pytest／conftest），兩檔 AST parse 與 trailing whitespace 檢查通過；統籌與文件角色均未重跑。案例只涵蓋純記憶體 payload／helper 與 mock 檔案控制邏輯；真實路徑、SQLite snapshot、公開入口端到端、sidecar／實際零寫入及競態整合未驗。大整數 volume 的 helper 測試不能外推既有 sealed reader 的 canonical integer 範圍。當輪 pytest 未跑，未記錄完整命令或版本；詳細原始證據留當時統籌 task，本輪也未重跑。
- 既有 prior volumes 程式驗證：兩份 pytest 模組 122 collected，52 個不同案例 passed，70 unrun；已有 DB 證據只涵蓋短歷史／`data_incomplete`、部分 producer／rollback 及 v3 bridge caller-save／reopen，廣泛 v1／v2 與 reader／rollback／bridge 回歸未完整。另有獨立的 `python -S -B -c` 純記憶體 AST 診斷 exit 0／30 項通過，涵蓋 strict types、日期／順序／數量／值／raw 拒絕、0／1／19／20、缺 FK unknown、nullable raw SHA、v2 selected bar、v3 pairing 與 bridge projection；不折算 pytest，也不證 DB rollback 或磁碟 roundtrip。最終修正後五個程式檔 AST parse 與 `git diff --check` exit 0，這只是語法／差異檢查。詳細命令、版本、失敗與修正證據留原 task，本輪未重跑。
- 暫存狀態依使用者上次確認：原 Temp 路徑 `C:\Users\YiCheng\AppData\Local\Temp\tsr-prior-volumes-b47052e24aeb40df847ce0ba93588320` 已移除；原 62 files／35,471,360 bytes 資料仍在 Windows 回收筒，可復原，尚非永久刪除。本輪未重掃回收筒。新增落盤配額仍為 0；必要磁碟驗證須由統籌重新核對餘額並明示恢復，不能以 mock 或 memory DB 代替。
- 本輪已接受的限定盤點：只查 Git tracked `docs/` 與 `backend/tests/fixtures/`，列出 26 個文件（含 lock 文字檔）及 3 個 fixture；限定文字搜尋與 [Signal artifact §10](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與-bridge-b-有限成果) 核對後，未找到已授權可唯讀使用的現存完整 research snapshot／`body.bin`／`receipt.json`／registry manifest pins tuple，因此獨立 verifier 的實際整合保持待驗。這不推論專案外或全磁碟不存在。64 位 hash regex 搜尋命令失敗，未用作否定證據。索引 coverage 是 best-effort；相關 docs 顯示 `metadata_changed`，一個 fixture 顯示 `parse_partial`，已以限定 Git 文字搜尋補查，索引不保證完整性。盤點排除 `.local`、gitignored／untracked DB 與資料、專案外磁碟、正式 DB、Temp／回收筒；本輪未執行 verifier 或測試，亦無程式變更。
- [SOURCE_REGISTRY §7](SOURCE_REGISTRY.md#7-review-receipt-與未完成範圍) 已記載 `registry_version=r1-a1-c009-2026-09-12.1` 與 canonical `content_digest=sha256:eb6c290d7716300c4117bb2cdc61a66cbf8d62e344870928933b44b77461f87b`；[OPERATIONS §4](OPERATIONS.md#4-source-registry-與-capture) 參照 `backend/worker/source_registry.json` 與 `free_public_local`。這些文件值與路徑範例存在，但 manifest 檔案在本輪讀取範圍外，且未配對具名 specimen；不得升格為實際整合通過。仍缺已授權可讀 current snapshot 路徑／SHA、exact attempt／ordinal、配對 body／receipt 與外部 receipt SHA，以及對該 specimen 核實的 manifest／pins 完整組合。契約與 API 範例不是實際 tuple。
- R0-B2／R0 整體仍未完成。本輪候選因缺已授權現存完整 specimen 與配對 pins／路徑而等待；在依賴未改變前不建立後續空轉輪次，也不擴大搜尋或建立資料。這不表示 ROADMAP 整體完成或其他工作均受阻。獨立 verifier 尚缺實際整合；歷史原件、上游修訂、官方來源真實性、availability／歷史 decision／PIT、其餘衍生輸入、consumer、同 snapshot legacy-v2 paired replay 與預設切換均未驗收或核定。本地 row linkage、宣告 SHA 與 detached verdict 不能補證上述缺口。B3-wire、B5b、B7 仍依各自 gate；實際限制見 [Signal artifact §10–11](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與-bridge-b-有限成果)。
- R35–38 的成員與候選身分、回補範圍、來源日展示維持各自的有限 review；完整歷史回算與 PIT 仍缺，細節見[產業分類 §8–9](INDUSTRY_CLASSIFICATION.md#8-群組衍生成員報酬的身分契約有限-review)。獨立 UI 維護成果與[籌碼三部分](STOCK_RESEARCH_PAGE.md#8-籌碼三部分後續待做)的待做範圍不因本輪改變。

### 角色與寫入分工

統籌已核對本輪四個新 task ID、共同專案目錄與接手；model／reasoning 是核定配置，工具未獨立驗證實際執行設定。上輪 ID 由原 task 追溯。

| 角色 | task ID／model／reasoning | 寫入／驗收範圍 |
| --- | --- | --- |
| 統籌 | `01a0e11c-ba1e-7f60-a451-9db8fcb43d52`；`gpt-6-astra`／`high` | 已接受限定盤點並核定等待邊界；負責本文件驗收、全輪 freeze 與索引／提交准入。 |
| 程式 | `01a0e11c-badc-7813-be21-6c04d3cea37d`；`gpt-6-sol`／`ultra` | 僅盤點 Git tracked `docs/`／`backend/tests/fixtures/` 並交付證據；本輪不改程式、不跑測試。 |
| 文件 | `01a0e11c-bb93-76d1-bd65-7d67a59f221b`；`gpt-6-sol`／`xhigh` | 僅更新本交接文件，核對既有契約與有限結論；交統籌 review，不改其他文件或程式。 |
| 索引與 Git commit | `01a0e11c-bc54-75e0-b9ce-3ae630af9b0e`；`gpt-6-luna`／`medium` | 本文件接受且全輪 freeze 後更新涉及分區索引、驗 coverage，並提交核准檔案；不改來源。 |

## 接續範圍

1. 已完成及驗收邊界：既有 Bridge B 的 explicit capture→candidate adapter、v2 selected bar 與 v3 prior volumes 有序本地列／raw metadata 仍只有限 review，候選不自動保存。上一輪獨立 verifier 六檔已接受、freeze／索引並本地提交；其 12 項 unittest 與兩檔靜態檢查不構成真實檔案、SQLite 或完整回歸驗收。本輪只接受上述限定盤點，未執行新測試或更動程式。
2. 尚缺項：既有 70 個 pytest 案例未跑；缺已授權現存完整 specimen 與對應 pins／路徑，verifier 的真實 tuple／實際零寫入整合仍待驗。歷史原件／上游版本、availability／歷史 decision／PIT、其餘衍生輸入、consumer 與同 snapshot paired output 仍缺；R0-B2／R0 不得據此標完成。回收筒狀態只依使用者先前回報，本輪未核查。
3. 下一步與依賴／完成條件：等待外部具名准入已存在、可唯讀使用的 current research snapshot 路徑／SHA、exact attempt／ordinal、配對 `body.bin`／`receipt.json` 與外部 receipt SHA，及對該 specimen 核實的 manifest／registry pins，再按 [Signal artifact §10](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與-bridge-b-有限成果)評估獨立 verifier 實際整合。依賴未改變時保持待驗，不建後續空轉輪次、不擴大搜尋或建立 fixture／附件；其他 ROADMAP 工作仍依各自 gate。必要磁碟驗證須另滿足既有配額條件。Consumer、paired replay、預設切換及 prior volumes 升格不由本輪預核；角色不自行結案或啟動下一輪。
4. 本輪唯一變更白名單為本文件；文件驗收後由統籌 freeze，索引角色輪末更新涉及分區並驗 coverage，經統籌准入後本地 commit。最終 freeze／coverage／commit 與本輪驗收結果以統籌 task receipt 為準，不為回寫最終 hash 再修改來源。

## 歷史與維護

舊角色 ID、交付狀態、測試及 commit 證據由[Git／原 task](README.md#歷史查閱)追溯；舊分派不覆蓋 AGENTS，也不恢復已刪除附件或舊統籌派工權。更新本文件時替換目前狀態，不追加逐輪日誌。
