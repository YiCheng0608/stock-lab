# 協作與接手狀態

本文件只留目前角色、接手與下一步；流程依 [AGENTS](../AGENTS.md)，能力與優先順序查 [ROADMAP](ROADMAP.md)。

## 本輪：M1 後續依賴審查完成，窗口與研究條件等待

使用者最新明示「這一個索引任務結束後，幫我commit，commit完請開始執行roadmap的階段任務了。」M1-P1、M1-P2a、M1-P2b、M1-P3a 與 M1-P3b 的具名能力已有限接受並版本封存；新統籌依此接手 [M1](ROADMAP.md#接下來的順序近期產品里程碑)。來源統籌 session `01a0fee0-541b-7b22-8e0e-15d4d7ca2cde` 已結案交接並停止派工，前輪已本地 commit `298b8cdc3233c2d2b966aaa305ebb213abd12177`，最終 receipt 由原 task 追溯；本地 commit 不含 push 或歷史重寫。

共同 repo：`C:\Users\YiCheng\Desktop\taiwan-stock-research`、`master` 原 checkout；接手時乾淨 HEAD：`298b8cdc3233c2d2b966aaa305ebb213abd12177`。本輪統籌 session `01a0ff0d-27c3-7ea0-963d-5f608d418859`、三個子 session、共同 repo、HEAD 與乾淨工作目錄已由統籌核對；runtime 未提供可核實的統籌 model／reasoning，不猜測。三個 subagent 均為本 session 以 `fork_turns=none` 新建且已正式確認接手，canonical ID 相同字樣不代表沿用前輪角色。

### 本輪 roster 與寫入範圍

| 角色 | 本輪 ID／實際建立參數 | 寫入／驗收範圍 |
| --- | --- | --- |
| 統籌 | session `01a0ff0d-27c3-7ea0-963d-5f608d418859`；runtime 未提供可核實的 model／reasoning | 已接受完整 5／20 交易日基準、多日法人原件與研究條件來源門檻的唯讀審查；核定相關能力等待外部來源或完整證據，接受文件後才 freeze。 |
| 程式 | canonical agent ID `/root/m1_code`；子 session `01a0ff0e-7498-7fb2-ba83-766052146bc1`；建立參數 `fork_turns=none`、`gpt-6.1-sol`／`ultra` | 本次來源寫入白名單為空；唯讀 M1 依賴審查及限制已由統籌接受，無來源／功能變更。不改來源、docs、AGENTS、manifest／pins、DB／legacy、索引或 Git，不自行修改規格。 |
| 文件 | canonical agent ID `/root/m1_docs`；子 session `01a0ff0e-ac7a-7b72-9fb5-a15051ad2812`；建立參數 `fork_turns=none`、`gpt-6.1-sol`／`xhigh` | `docs/TASK_COORDINATION.md`、`docs/ROADMAP.md`、`docs/ROADMAP_EXECUTION.md`、`docs/SOURCE_REGISTRY.md`；依統籌接受的審查更新結果、等待邊界與恢復條件。不改程式、AGENTS、manifest、索引或 Git。 |
| 索引與 Git commit | canonical agent ID `/root/m1_index`；子 session `01a0ff0e-e383-7940-8696-e12a35d1b92f`；建立參數 `fork_turns=none`、`gpt-6-luna`／`medium` | freeze 後才刷新涉及分區、驗 coverage，並只 stage／commit 統籌核准檔案；不改來源或 push。 |

runtime 提供 canonical ID 與上述子 session ID，未提供 agent UUID。文件角色以環境 `CODEX_THREAD_ID` 核對自身子 session；建立參數由統籌核對，不猜測 runtime 未證實的 effective model／reasoning。所有角色不得自行結案或啟動下一任務；共同 repo、HEAD、乾淨接手與互不衝突的精確寫入白名單已由統籌核對。

### 接手成果、缺口與下一步

1. **完成及驗收邊界**：獨立文件維護已接受文件流程與一致性，不增加產品完成度。R1-A2-P1-identity 與 P2+ 成交額政策、程式補強保留原有限 review；缺額／明確零的單一離線 fixture capture→SQLite→API 已有限驗收並版本封存，不升格官方真實樣本、全市場或 R1-A2 整體完成。詳細契約見 [DATA_SOURCES](DATA_SOURCES.md#r1-a2-p2-成交金額可得狀態有限接受)。
2. **完成及驗收邊界、尚缺項**：M1-P1 的 TWSE 1101／2330、2026-10-01 單日 selected 真實價格六欄、detail／總覽 API 一致、指定截止排除與晚於價格提示、桌面／窄版具名操作及後端邊界回歸、前端 SSR／型別／production build 已有限 review；保留大型 JS chunk 警告，精確契約及支持範圍見[個股頁 §9](STOCK_RESEARCH_PAGE.md#9-m1-p1截止一致與來源可追溯總覽)。M1-P2a 的單來源 manifest、capture／selected 摘要 library／CLI、單日兩檔數值與具名負向已有限接受並版本封存。M1-P2b 的 TPEx 3105／6488、2026-10-02 原件→實際 API 二十個數值、端點一致與追溯欄位、桌面／窄版具名操作已有限 review 並版本封存；精確契約及支持範圍見[個股頁 §10](STOCK_RESEARCH_PAGE.md#10-m1-p2b單日法人原件總覽接線)。P2b 未跑完整 backend／production Vite build，記憶體全 App bundle 不作 production 驗收，本輪不重驗。M1-P3a 程式、當次 TWSE 0056（ETF）／1449／1463 未來生效預告的原件／實際 CLI、缺 selected 拒收與記憶體靶向回歸已有限接受，精確支持範圍見[來源契約 §9](SOURCE_REGISTRY.md#9-m1-p3atwt48u-selected-官方事件原件摘要)；source gate 縮窄後只跑必要複驗，現完整案例與完整 backend 未重跑，本次 live 不能離線重播。完整 M1 的 5／20 交易日窗口、完整事件 coverage 與研究條件仍缺；selected 總覽接線由前輪 P3b 有限交付並版本封存。R1-A2 的 legacy migration、其他 invalid／拒收磁碟整合、正式 DB、逐市場／session／欄位 coverage、availability／歷史／PIT 與量截整／TAIEX 合成欄位風險不變。其餘 R0 與 B2 snapshot／body／receipt／attempt／ordinal／pins 缺口維持原邊界，不重複搜尋或建 specimen。
3. **完成及驗收邊界 → 尚缺項 → 下一步與依賴／完成條件**：前輪 M1-P3b 程式、TWSE 0056（ETF）／1449／1463 當次真原件四欄與追溯、截止排除、detail／獨立總覽一致、同 process cache 再用，以及桌面三個標的／日期／來源／授權與窄版 details／表格自身捲動已有限接受並版本封存；精確範圍見[個股頁 §11](STOCK_RESEARCH_PAGE.md#11-m1-p3bselected-官方事件總覽接線)。後端靶向回歸、前端型別／SSR／記憶體全 App bundle 通過；完整 backend／production Vite build 未跑，前次 live 不可離線重播。發布／首次可得／修訂仍 unknown，不推論價格影響，原四來源 manifest／pins 不變；無新 calendar、DB／legacy／預設來源或 PIT 完成。本輪完整 5／20 交易日基準、多日法人原件與研究條件來源門檻的唯讀審查已由統籌接受；本次選題、既有授權與現有證據下沒有可解除依賴的新實作，不增加能力完成度。相關窗口與研究條件等待外部來源或完整證據，非使用者暫停，也不推論 ROADMAP 全部餘項受阻。恢復須可信完整交易日基準、已准入多日法人原件與範圍／缺日 coverage，研究條件另須滿足必要輸入／來源／時間／分類 gate；候選服務恢復後只先作有界可行性核實，不等於 gate 通過。主缺口見 [ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)，詳細來源審查見[來源 §10](SOURCE_REGISTRY.md#10-m1-後續依賴審查來源候選與等待邊界)。
4. **freeze／索引／commit**：前輪 M1-P3b 已 freeze、索引與本地 commit，receipt 留前輪 task。本輪唯讀審查已接受；最終文件為 freeze 候選，尚未 freeze、刷新或 commit。統籌接受文件後才 freeze；其後由索引角色刷新、驗 coverage，統籌核准提交檔案後本地 commit。最終 receipt 留本輪 task，不為回寫 commit hash 反覆改文件。進入可實作狀態後依 [AGENTS](../AGENTS.md#每輪流程) 建立新統籌 session 及三個新 subagent，再核定共同 repo、接手與互斥白名單；目前尚未建立，不開空轉輪次，所有角色不自行結案或啟動下一任務。

本輪文件只修改白名單內既有檔案，總增補上限 **32 KiB**，文件角色額外附件／暫存配額為 **0**；文件只做差異、連結與一致性檢查，純文件且無來源／功能變更，不跑 backend 測試。本輪不 collect、不操作正式 DB。既有落盤 entries 已超配額，本輪新增產物及殘留上限均為 **0**，不換根或改名繞過限制；實作須待依賴解除與統籌另行核定。已接受的 capture 契約維持 `source-memory-capture/v1`、`storage=memory_only`，不因本輪審查宣稱磁碟 artifact 或持久化。舊殘留及自動審核阻擋保持原樣，不重試清理；禁止 `KeepArtifacts`，測試與清理分報，中斷、占用或自動審核拒絕不得冒稱已刪除，也不得繞過拒絕。

前輪驗收清理已另核對：測試 tab 關閉／viewport 還原，三次專用 frontend server 與 backend process 均已終止，memory body 隨 process 釋放；無新增 owned 測試附件待刪除。這不表示下列舊殘留已清理；失敗／退修與成功後複驗的原始 exit／收據分開留原 task。

M1-P2a 輪因未先辨識 conftest 建構副作用，已知殘留（均含該根）為 `C:\Users\YiCheng\AppData\Local\Temp\taiwan-stock-m1p2a-01a0fe7e` **243 entries／11 files／993,443 bytes**；其中 `code-tests` **240 entries／10 files／125,120 bytes**、`live` **2 entries／1 file／868,323 bytes**。該輪統一根上限 **200 entries／20 MiB**、`code-tests` 子目錄上限 **100 entries／10 MiB**，entries 已超配額；兩處 exact 清理皆在 CreateProcess 前被自動審核拒絕（`blocked by policy`），未執行。停止新增落盤測試，不能換根繞過上限；不為重驗 live 而造檔。conftest 另在 default Temp 建立一個 `_TEST_ROOT`，確切名稱及其內數量／大小未核實，獨列為未知，不能聲稱空目錄、已清理或掃 Temp 猜測 owned。該輪首跑有一個測試 assertion 失敗，其修正、既有 fixture 唯讀復核、純記憶體回歸及測試／清理分開收據留來源 task；未完整重跑該落盤 pytest，首跑不能改報全通過。清理限制不否定已接受的真實數值與有效測試證據。

較早一輪 `C:\Users\YiCheng\AppData\Local\Temp\taiwan-stock-m1-01a0fe5a` 殘留 **118 entries／105 files／17,319,956 bytes**；UI 與 code-tests 清理被自動審核拒絕，未執行，確切收據留來源 task。本輪不再嘗試繞過拒絕；有效驗收不因清理失敗被否定，後續保持隔離，不冒稱已刪除。

## 歷史與維護

舊角色 ID、交付狀態、測試及 commit 證據由 [Git／原 task](README.md#歷史查閱) 追溯；舊分派不覆蓋 AGENTS，也不恢復已刪除附件或舊統籌派工權。更新本文件時替換目前狀態，不追加逐輪日誌。
