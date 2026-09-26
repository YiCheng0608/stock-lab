# 協作與接手狀態

本文件只留目前角色、接手與下一步；流程依 [AGENTS](../AGENTS.md)，能力與優先順序查 [ROADMAP](ROADMAP.md)。

## 目前狀態（2026-09-27）

- 上輪 [R0-B2 Bridge B](ROADMAP_EXECUTION.md#r0-b版本化-artifact-與-atr) 的 opt-in prior volumes 接線已由統籌限制性接受為有限 review 並本地提交：`selected-bar-prior-volumes/v1` 將本次實際最多 20 筆有序歷史列封存為 `worker-analysis-capture/v3`；bridge 依 v3 產 detached candidate，caller save 仍須明示。這是目前可證的實作邊界，不代表全模組或整體功能驗收。
- 本輪 raw bytes／source version 先完成唯讀盤點：一般抓取若解析後重編碼再算 SHA，不能證原始 HTTP bytes；opt-in `STOCK_DAY_ALL` 有 body／receipt／SHA／registry pins 的基礎，但 `source_version` 只是 registry 宣告。Local `RawPayload`、selected bar／prior volumes 尚未封存逐輸入 receipt／version 或完成原始 bytes 重解析驗證。下一最小候選限 `STOCK_DAY_ALL` selected bar 唯讀證據驗證；目前實作白名單為空，prior volumes 不升格。升格時遇缺 FK、來源不唯一、SHA／receipt／version pin 不符或重解析欄位不符須拒絕；這是待驗條件，並非已實作行為。完整邊界見 [Signal artifact §10](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與下一候選)。
- 上輪程式驗證：兩份 pytest 模組 122 collected，52 個不同案例 passed，70 unrun；已有 DB 證據只涵蓋短歷史／`data_incomplete`、部分 producer／rollback 及 v3 bridge caller-save／reopen，廣泛 v1／v2 與 reader／rollback／bridge 回歸未完整。另有獨立的 `python -S -B -c` 純記憶體 AST 診斷 exit 0／30 項通過，涵蓋 strict types、日期／順序／數量／值／raw 拒絕、0／1／19／20、缺 FK unknown、nullable raw SHA、v2 selected bar、v3 pairing 與 bridge projection；不折算 pytest，也不證 DB rollback 或磁碟 roundtrip。最終修正後五個程式檔 AST parse 與 `git diff --check` exit 0，這只是語法／差異檢查。詳細命令、版本、失敗與修正證據留原 task。
- 清理未完成：上輪唯一暫存根 `C:\Users\YiCheng\AppData\Local\Temp\tsr-prior-volumes-b47052e24aeb40df847ce0ba93588320` 仍有 62 files／35,471,360 bytes。清理命令遭政策拒絕，未刪除；不繞過政策、不另建 root 或改名轉存、不提高 64 files／128 MiB 上限。目前新增落盤配額 0，僅可做零落盤／唯讀工作。後續必要磁碟驗證須待殘留以合規方式處理、重新核對餘額並由統籌恢復落盤；不能以 mock 或 memory DB 代替。
- R0-B2／R0 整體仍未完成。真正 raw bytes／source version、官方來源真實性、availability／歷史 decision／PIT、其餘衍生輸入、consumer、同 snapshot legacy-v2 paired replay 與預設切換均未驗收或核定；本地 row linkage 與宣告 SHA 不能補證上述缺口。B3-wire、B5b、B7 仍依各自 gate；實際限制見 [Signal artifact §10–11](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與下一候選)。
- R35–38 的成員與候選身分、回補範圍、來源日展示維持各自的有限 review；完整歷史回算與 PIT 仍缺，細節見[產業分類 §8–9](INDUSTRY_CLASSIFICATION.md#8-群組衍生成員報酬的身分契約有限-review)。獨立 UI 維護成果與[籌碼三部分](STOCK_RESEARCH_PAGE.md#8-籌碼三部分後續待做)的待做範圍不因本輪改變。

### 角色與寫入分工

統籌已核對本輪四個新 task ID、共同專案目錄與接手；model／reasoning 是核定配置，工具未獨立驗證實際執行設定。上輪 ID 由原 task 追溯。

| 角色 | task ID／model／reasoning | 寫入／驗收範圍 |
| --- | --- | --- |
| 統籌 | `01a0dee0-cbd9-7031-b2f7-e059913f0dd0`；`gpt-6-astra`／`high` | 核定唯讀盤點範圍、接受文件、freeze 與索引／commit 准入。 |
| 程式 | `01a0dee0-cca9-79c2-a36a-323625a473c2`；`gpt-6-sol`／`ultra` | 唯讀來源／版本證據；實作白名單為空。 |
| 文件 | `01a0dee0-cd8d-7c71-a136-b57d6dc72561`；`gpt-6-sol`／`xhigh` | 受影響契約、ROADMAP／執行清單與本交接；不改程式。 |
| 索引與 Git commit | `01a0dee0-ce75-7670-a605-b1ceb604077c`；`gpt-6-luna`／`medium` | Freeze 後更新索引、驗 coverage，並提交核准檔案；不改來源。 |

## 接續範圍

1. 已完成及驗收邊界：既有 Bridge B 接受 explicit capture→candidate adapter、v2 selected bar；v3 增加實際 prior volumes 有序本地列與 raw metadata、strict reader 及 v3 input manifest／candidate 的有限 review。短窗口與零量保留，候選不自動保存；上列 pytest 與 AST 證據不擴大為完整回歸。本輪只有 raw bytes／source version 唯讀盤點，未新增程式驗收。
2. 尚缺項：70 個未跑 pytest 與清理殘留待處理；真正 raw bytes／source version、availability／歷史 decision／PIT、其餘衍生輸入、consumer 與同 snapshot paired output 仍缺。R0-B2／R0 不得據此標完成。
3. 下一步與依賴／完成條件：先在零落盤條件下補可行的未跑 coverage，並只評估 `STOCK_DAY_ALL` selected bar 的唯讀 body／receipt／pin／重解析證據；證據符合 [Signal artifact §10](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與下一候選) 後由統籌再核定具體實作白名單。必要磁碟驗證要等殘留按政策處理、核對餘額及統籌恢復落盤。Consumer、paired replay、預設切換及 prior volumes 升格不由本輪預核；角色不自行結案或啟動下一輪。
4. 本輪文件接受、freeze、索引與 commit 准入及最終 receipt 以統籌 task 為準；接受並 freeze 後，才由索引角色更新涉及分區與 coverage，統籌複核並核准檔案後才本地 commit。不預寫完成狀態。

## 歷史與維護

舊角色 ID、交付狀態、測試及 commit 證據由[Git／原 task](README.md#歷史查閱)追溯；舊分派不覆蓋 AGENTS，也不恢復已刪除附件或舊統籌派工權。更新本文件時替換目前狀態，不追加逐輪日誌。
