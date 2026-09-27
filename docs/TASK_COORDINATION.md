# 協作與接手狀態

本文件只留目前角色、接手與下一步；流程依 [AGENTS](../AGENTS.md)，能力與優先順序查 [ROADMAP](ROADMAP.md)。

## 目前狀態（2026-09-27）

- 上輪 [R0-B2 Bridge B](ROADMAP_EXECUTION.md#r0-b版本化-artifact-與-atr) 的 opt-in prior volumes 接線已由統籌限制性接受為有限 review 並本地提交：`selected-bar-prior-volumes/v1` 將本次實際最多 20 筆有序歷史列封存為 `worker-analysis-capture/v3`；bridge 依 v3 產 detached candidate，caller save 仍須明示。這是目前可證的實作邊界，不代表全模組或整體功能驗收。
- 本輪 `STOCK_DAY_ALL` selected bar 只有靜態來源 review：抓取端有 identity raw body／receipt／SHA／registry pins，loader 有全列日期／symbol 與 selected 數值解析，但會落盤；pipeline 的 raw id 暫存 key 不含 endpoint，digest 查找也可能跨來源選錯。Analysis capture／bridge 只有本地 row／FK／path／宣告 SHA，未精確綁定 body／receipt／version，仍標 `bytes_unverified`。未取得實際 body／receipt 與 research snapshot 對照，未新增程式驗收。下一步先核定獨立零寫入 verifier 的 API、範圍與拒絕條件；實作白名單仍空，prior volumes 不升格。完整證據及未來拒絕條件見 [Signal artifact §10](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與-bridge-b-有限成果)。
- 上輪程式驗證：兩份 pytest 模組 122 collected，52 個不同案例 passed，70 unrun；已有 DB 證據只涵蓋短歷史／`data_incomplete`、部分 producer／rollback 及 v3 bridge caller-save／reopen，廣泛 v1／v2 與 reader／rollback／bridge 回歸未完整。另有獨立的 `python -S -B -c` 純記憶體 AST 診斷 exit 0／30 項通過，涵蓋 strict types、日期／順序／數量／值／raw 拒絕、0／1／19／20、缺 FK unknown、nullable raw SHA、v2 selected bar、v3 pairing 與 bridge projection；不折算 pytest，也不證 DB rollback 或磁碟 roundtrip。最終修正後五個程式檔 AST parse 與 `git diff --check` exit 0，這只是語法／差異檢查。詳細命令、版本、失敗與修正證據留原 task。
- 暫存狀態依使用者上次確認：原 Temp 路徑 `C:\Users\YiCheng\AppData\Local\Temp\tsr-prior-volumes-b47052e24aeb40df847ce0ba93588320` 已移除；原 62 files／35,471,360 bytes 資料仍在 Windows 回收筒，可復原，尚非永久刪除。本輪未重掃回收筒。新增落盤配額仍為 0；必要磁碟驗證須由統籌重新核對餘額並恢復落盤，不能以 mock 或 memory DB 代替。
- R0-B2／R0 整體仍未完成。真正 raw bytes／source version、官方來源真實性、availability／歷史 decision／PIT、其餘衍生輸入、consumer、同 snapshot legacy-v2 paired replay 與預設切換均未驗收或核定；本地 row linkage 與宣告 SHA 不能補證上述缺口。B3-wire、B5b、B7 仍依各自 gate；實際限制見 [Signal artifact §10–11](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與-bridge-b-有限成果)。
- R35–38 的成員與候選身分、回補範圍、來源日展示維持各自的有限 review；完整歷史回算與 PIT 仍缺，細節見[產業分類 §8–9](INDUSTRY_CLASSIFICATION.md#8-群組衍生成員報酬的身分契約有限-review)。獨立 UI 維護成果與[籌碼三部分](STOCK_RESEARCH_PAGE.md#8-籌碼三部分後續待做)的待做範圍不因本輪改變。

### 角色與寫入分工

統籌已核對本輪四個新 task ID、共同專案目錄與接手；model／reasoning 是核定配置，工具未獨立驗證實際執行設定。上輪 ID 由原 task 追溯。

| 角色 | task ID／model／reasoning | 寫入／驗收範圍 |
| --- | --- | --- |
| 統籌 | `01a0e093-982e-70c2-ab1e-a64f7e692d5d`；`gpt-6-astra`／`high` | 核定 selected bar 靜態來源 review、接受文件、freeze 與索引／commit 准入。 |
| 程式 | `01a0e093-991e-79e0-acfe-e981f9c97911`；`gpt-6-sol`／`ultra` | 唯讀程式 evidence；實作白名單為空。 |
| 文件 | `01a0e093-9a2e-7dc1-bf40-70ba5c1bb131`；`gpt-6-sol`／`xhigh` | 受影響契約、ROADMAP／執行清單與本交接；不改程式。 |
| 索引與 Git commit | `01a0e093-9b2b-7b12-8f0a-00106017d776`；`gpt-6-luna`／`medium` | Freeze 後更新索引、驗 coverage，並提交核准檔案；不改來源。 |

## 接續範圍

1. 已完成及驗收邊界：既有 Bridge B 接受 explicit capture→candidate adapter、v2 selected bar；v3 增加實際 prior volumes 有序本地列與 raw metadata、strict reader 及 v3 input manifest／candidate 的有限 review。短窗口與零量保留，候選不自動保存；上列 pytest 與 AST 證據不擴大為完整回歸。本輪 selected bar 只有靜態來源 review，沒有實際資料或 runtime 驗收。
2. 尚缺項：70 個未跑 pytest；真正逐輸入 raw bytes／source version、availability／歷史 decision／PIT、其餘衍生輸入、consumer 與同 snapshot paired output 仍缺。回收筒資料可復原，落盤配額仍為 0。R0-B2／R0 不得據此標完成。
3. 下一步與依賴／完成條件：先核定獨立零寫入 `STOCK_DAY_ALL` selected-bar verifier 的 API、輸入範圍、唯一 body／receipt／registry 綁定及拒絕條件，見 [Signal artifact §10](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與-bridge-b-有限成果)；統籌再決定程式白名單。零落盤條件下可補可行的未跑 coverage；必要磁碟驗證須重新核對餘額並由統籌恢復落盤。Consumer、paired replay、預設切換及 prior volumes 升格不由本輪預核；角色不自行結案或啟動下一輪。
4. 本輪文件接受、freeze、索引與 commit 准入及最終 receipt 以統籌 task 為準；接受並 freeze 後，才由索引角色更新涉及分區與 coverage，統籌複核並核准檔案後才本地 commit。不預寫完成狀態。

## 歷史與維護

舊角色 ID、交付狀態、測試及 commit 證據由[Git／原 task](README.md#歷史查閱)追溯；舊分派不覆蓋 AGENTS，也不恢復已刪除附件或舊統籌派工權。更新本文件時替換目前狀態，不追加逐輪日誌。
