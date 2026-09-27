# 協作與接手狀態

本文件只留目前角色、接手與下一步；流程依 [AGENTS](../AGENTS.md)，能力與優先順序查 [ROADMAP](ROADMAP.md)。

## 目前狀態（2026-09-27）

- 上輪 [R0-B2 Bridge B](ROADMAP_EXECUTION.md#r0-b版本化-artifact-與-atr) 的 opt-in prior volumes 接線已由統籌限制性接受為有限 review 並本地提交：`selected-bar-prior-volumes/v1` 將本次實際最多 20 筆有序歷史列封存為 `worker-analysis-capture/v3`；bridge 依 v3 產 detached candidate，caller save 仍須明示。這是目前可證的實作邊界，不代表全模組或整體功能驗收。
- 本輪統籌已限制性接受獨立 `STOCK_DAY_ALL` selected-bar verifier 的兩檔程式成果並核定 code-only freeze。`verify_selected_bar_evidence` 對 caller 指定的 current snapshot SHA、exact attempt／ordinal、raw FK 所指 `body.bin`／同目錄 `receipt.json`，以及外部 receipt SHA／registry version／digest pins 作唯讀核對；成功只回 detached `stock-day-selected-bar-evidence/v1`／`local_evidence_consistent`／`selected_bar_only`。v2／v3 只驗 selected bar，v3 prior volumes 不升格；既有 capture／bridge／consumer 未改，`bytes_unverified` 不變。Receipt 外部 pin 不能證 capture 當時原件；registry `source_version` 只證本次本地規格 pin，不證官方或歷史真實性。完整 API、拒絕條件與限制見 [Signal artifact §10](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與-bridge-b-有限成果)。
- 本輪 verifier 的執行證據來自使用者在統籌 task 的回報：bundled Python `-B` 直接執行 unittest 12 項 passed（避開會建立暫存資料夾的 pytest／conftest），兩檔 AST parse 與 trailing whitespace 檢查通過；統籌與文件角色均未重跑。案例只涵蓋純記憶體 payload／helper 與 mock 檔案控制邏輯；真實路徑、SQLite snapshot、公開入口端到端、sidecar／實際零寫入及競態整合未驗。大整數 volume 的 helper 測試不能外推既有 sealed reader 的 canonical integer 範圍。本輪 pytest 未跑，未記錄完整命令或版本；詳細原始證據留統籌 task。
- 上輪程式驗證：兩份 pytest 模組 122 collected，52 個不同案例 passed，70 unrun；已有 DB 證據只涵蓋短歷史／`data_incomplete`、部分 producer／rollback 及 v3 bridge caller-save／reopen，廣泛 v1／v2 與 reader／rollback／bridge 回歸未完整。另有獨立的 `python -S -B -c` 純記憶體 AST 診斷 exit 0／30 項通過，涵蓋 strict types、日期／順序／數量／值／raw 拒絕、0／1／19／20、缺 FK unknown、nullable raw SHA、v2 selected bar、v3 pairing 與 bridge projection；不折算 pytest，也不證 DB rollback 或磁碟 roundtrip。最終修正後五個程式檔 AST parse 與 `git diff --check` exit 0，這只是語法／差異檢查。詳細命令、版本、失敗與修正證據留原 task。
- 暫存狀態依使用者上次確認：原 Temp 路徑 `C:\Users\YiCheng\AppData\Local\Temp\tsr-prior-volumes-b47052e24aeb40df847ce0ba93588320` 已移除；原 62 files／35,471,360 bytes 資料仍在 Windows 回收筒，可復原，尚非永久刪除。本輪未重掃回收筒。新增落盤配額仍為 0；必要磁碟驗證須由統籌重新核對餘額並明示恢復，不能以 mock 或 memory DB 代替。
- R0-B2／R0 整體仍未完成。獨立 verifier 尚缺已授權現存 research snapshot／body／receipt／registry pins 的實際整合證據；歷史原件、上游修訂、官方來源真實性、availability／歷史 decision／PIT、其餘衍生輸入、consumer、同 snapshot legacy-v2 paired replay 與預設切換均未驗收或核定。本地 row linkage、宣告 SHA 與本輪 detached verdict 不能補證上述缺口。B3-wire、B5b、B7 仍依各自 gate；實際限制見 [Signal artifact §10–11](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與-bridge-b-有限成果)。
- R35–38 的成員與候選身分、回補範圍、來源日展示維持各自的有限 review；完整歷史回算與 PIT 仍缺，細節見[產業分類 §8–9](INDUSTRY_CLASSIFICATION.md#8-群組衍生成員報酬的身分契約有限-review)。獨立 UI 維護成果與[籌碼三部分](STOCK_RESEARCH_PAGE.md#8-籌碼三部分後續待做)的待做範圍不因本輪改變。

### 角色與寫入分工

統籌已核對本輪四個新 task ID、共同專案目錄與接手；model／reasoning 是核定配置，工具未獨立驗證實際執行設定。上輪 ID 由原 task 追溯。

| 角色 | task ID／model／reasoning | 寫入／驗收範圍 |
| --- | --- | --- |
| 統籌 | `01a0e0e7-b26a-74a3-b104-2828fa6249d8`；`gpt-6-astra`／`high` | 已接受 verifier 有限成果並核定 code-only freeze；待 review 文件、全輪 freeze 與索引／commit 准入。 |
| 程式 | `01a0e0e7-b31d-7b31-a3ff-e043135c0708`；`gpt-6-sol`／`ultra` | 兩檔核准程式實作／證據已交付且 freeze；不修改文件。 |
| 文件 | `01a0e0e8-9b5f-7431-b07f-ab5da4c57478`；`gpt-6-sol`／`xhigh` | 僅更新受影響契約、ROADMAP／執行清單與本交接；交統籌 review，不改程式。 |
| 索引與 Git commit | `01a0e0e8-9c0d-7ec1-a7a8-5996b1e2bc29`；`gpt-6-luna`／`medium` | 全輪 freeze 後更新索引、驗 coverage，並提交核准檔案；不改來源。 |

## 接續範圍

1. 已完成及驗收邊界：既有 Bridge B 的 explicit capture→candidate adapter、v2 selected bar 與 v3 prior volumes 有序本地列／raw metadata 仍只有限 review，候選不自動保存。本輪獨立 verifier 的 API、拒絕類別與純記憶體／mock 案例經統籌限制性接受並 code-only freeze；12 項 unittest 與兩檔靜態檢查不構成真實檔案、SQLite 或完整回歸驗收。
2. 尚缺項：上輪 70 個既有 pytest 案例未跑；verifier 的真實 tuple／實際零寫入整合、歷史原件／上游版本、availability／歷史 decision／PIT、其餘衍生輸入、consumer 與同 snapshot paired output 仍缺。回收筒資料可復原，新增落盤配額仍為 0；R0-B2／R0 不得據此標完成。
3. 下一步與依賴／完成條件：尋找已授權可唯讀的現存 research snapshot／body／receipt／registry pins tuple，按 [Signal artifact §10](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與-bridge-b-有限成果)驗獨立 verifier；若 specimen 或 pins 不齊，保持待驗，不建附件或 fixture。零落盤條件下只補可行的唯讀 coverage；需要新增磁碟測試須由統籌重新核對配額並明示恢復。Consumer、paired replay、預設切換及 prior volumes 升格不由本輪預核；角色不自行結案或啟動下一輪。
4. 程式已 code-only freeze，文件待統籌 review／接受；整輪 freeze、索引、commit 准入與最終 receipt 尚未核發。文件接受後才由統籌 freeze，索引角色輪末更新涉及分區及驗 coverage，統籌核准檔案後才本地 commit；不預寫完成狀態或 hash。

## 歷史與維護

舊角色 ID、交付狀態、測試及 commit 證據由[Git／原 task](README.md#歷史查閱)追溯；舊分派不覆蓋 AGENTS，也不恢復已刪除附件或舊統籌派工權。更新本文件時替換目前狀態，不追加逐輪日誌。
