# 協作與接手狀態

本文件只留目前角色、接手與下一步；流程依 [AGENTS](../AGENTS.md)，能力與優先順序查 [ROADMAP](ROADMAP.md)。

## 本輪：M1-P3a TWT48U selected 官方事件原件摘要

使用者最新明示「這一個索引任務結束後，幫我commit，commit完請開始執行roadmap的階段任務了。」M1-P1、M1-P2a 與 M1-P2b 的具名能力已有限接受並版本封存；新統籌依此接手 [M1](ROADMAP.md#接下來的順序近期產品里程碑)。來源統籌 session `01a0fe9e-201a-7660-8298-4df80014dc90` 已結案交接並停止派工，最終 receipt 由原 task 追溯；本地 commit 不含 push 或歷史重寫。

共同 repo：`C:\Users\YiCheng\Desktop\taiwan-stock-research`；接手時乾淨 HEAD：`5d49edb3dcce3379097442402a15e79b8bdce292`。本輪統籌 session `01a0fec3-c81d-7f93-bc57-5a4bc2b5ef1c`、共同 repo、HEAD 與乾淨工作目錄已由統籌核對；runtime 未提供可核實的統籌 model／reasoning，不猜測。三個有效 subagent 皆在本 session 明確指定建立參數並確認接手，未沿用舊角色。

### 本輪 roster 與寫入範圍

| 角色 | 本輪 ID／實際建立參數 | 寫入／驗收範圍 |
| --- | --- | --- |
| 統籌 | session `01a0fec3-c81d-7f93-bc57-5a4bc2b5ef1c`；runtime 未提供可核實的 model／reasoning | 核定 M1-P3a 的 TWT48U selected 原件與記憶體 capture／摘要契約，接受有限 live 來源／欄位、CLI／邊界驗證與文件後才 freeze；總覽接線留 P3b。 |
| 程式 | canonical agent ID `/root/m1_code`；`gpt-6.1-sol`／`ultra` | `backend/worker/source_runtime.py`、`backend/worker/twse_action_capture.py`、`backend/tests/test_twse_action_capture.py`；程式總增補上限 80 KiB。不改 docs、舊四來源 manifest／pins、DB／legacy 或自行修改規格。 |
| 文件 | canonical agent ID `/root/m1_docs`；`gpt-6.1-sol`／`xhigh` | `docs/TASK_COORDINATION.md`、`docs/ROADMAP.md`、`docs/ROADMAP_EXECUTION.md`、`docs/SOURCE_REGISTRY.md`、`docs/NEWS_SPEC.md`；依統籌核定實作與具名驗收更新成果、契約及交接。不改程式、AGENTS、索引或 Git。 |
| 索引與 Git commit | canonical agent ID `/root/m1_index`；`gpt-6-luna`／`medium` | freeze 後才刷新涉及分區、驗 coverage，並只 stage／commit 統籌核准檔案；不改來源或 push。 |

runtime 僅提供 subagent canonical ID，未提供 agent UUID。所有角色不得自行結案或啟動下一任務；共同 repo、接手狀態與互不衝突的精確寫入白名單已由統籌核對。

### 接手成果、缺口與下一步

1. **完成及驗收邊界**：獨立文件維護已接受文件流程與一致性，不增加產品完成度。R1-A2-P1-identity 與 P2+ 成交額政策、程式補強保留原有限 review；缺額／明確零的單一離線 fixture capture→SQLite→API 已有限驗收並版本封存，不升格官方真實樣本、全市場或 R1-A2 整體完成。詳細契約見 [DATA_SOURCES](DATA_SOURCES.md#r1-a2-p2-成交金額可得狀態有限接受)。
2. **完成及驗收邊界、尚缺項**：M1-P1 的 TWSE 1101／2330、2026-10-01 單日 selected 真實價格六欄、detail／總覽 API 一致、指定截止排除與晚於價格提示、桌面／窄版具名操作及後端邊界回歸、前端 SSR／型別／production build 已有限 review；保留大型 JS chunk 警告，精確契約及支持範圍見[個股頁 §9](STOCK_RESEARCH_PAGE.md#9-m1-p1截止一致與來源可追溯總覽)。M1-P2a 的單來源 manifest、capture／selected 摘要 library／CLI、單日兩檔數值與具名負向已有限接受並版本封存。M1-P2b 的 TPEx 3105／6488、2026-10-02 原件→實際 API 二十個數值、端點一致與追溯欄位、桌面／窄版具名操作已有限 review 並版本封存；精確契約及支持範圍見[個股頁 §10](STOCK_RESEARCH_PAGE.md#10-m1-p2b單日法人原件總覽接線)。P2b 未跑完整 backend／production Vite build，記憶體全 App bundle 不作 production 驗收，本輪不重驗。M1-P3a 程式、當次 TWSE 0056（ETF）／1449／1463 未來生效預告的原件／實際 CLI、缺 selected 拒收與記憶體靶向回歸已有限接受，精確支持範圍見[來源契約 §9](SOURCE_REGISTRY.md#9-m1-p3atwt48u-selected-官方事件原件摘要)；source gate 縮窄後只跑必要複驗，現完整案例與完整 backend 未重跑，本次 live 不能離線重播。完整 M1 的 5／20 交易日窗口、事件總覽接線與研究條件仍缺。R1-A2 的 legacy migration、其他 invalid／拒收磁碟整合、正式 DB、逐市場／session／欄位 coverage、availability／歷史／PIT 與量截整／TAIEX 合成欄位風險不變。其餘 R0 與 B2 snapshot／body／receipt／attempt／ordinal／pins 缺口維持原邊界，不重複搜尋或建 specimen。
3. **下一步與依賴／完成條件**：先由統籌複核文件並完成 freeze／索引／commit；下一個 M1-P3b 須核定來源取得方式、觀測截止／事件日語意、追溯與 API／UI 操作範圍，再把已有限接受的 selected 事件接到總覽。發布／首次可得／修訂仍 unknown，不推論價格影響；原四來源 manifest／pins 不變。本輪無新 calendar 准入、DB／legacy／預設來源或 PIT 完成。5／20 交易日窗口仍需交易日基準、缺日判準與完整多日原件；TWSE T86 准入仍未知，不由 P3a 宣稱 M2 就緒，後續依 [M1 接線映射](ROADMAP_EXECUTION.md#21-近期里程碑接線映射) 核定可行子能力。
4. **freeze／索引／commit**：程式與具名有限功能驗收已接受，文件待統籌複核；本輪尚未 freeze、刷新或 commit。統籌接受文件後才 freeze；其後由索引角色刷新、驗 coverage，統籌核准提交檔案後本地 commit。上一輪最終 receipt 在來源 task；本輪 freeze／索引／commit 最終 receipt 留本輪 task，不為回寫 hash 反覆改文件。

本輪文件只修改白名單內既有檔案，總增補上限 **32 KiB**，文件角色額外附件／暫存配額為 **0**；文件只做差異、連結與一致性檢查。本輪不 collect、不操作正式 DB。既有落盤 entries 已超配額，本輪額外落盤測試配額為 **0**，不換根或改名繞過限制；其餘唯讀、記憶體驗證與實作可持續。新 capture 的 schema 為 `source-memory-capture/v1`、`storage=memory_only`，原件只在記憶體、摘要只輸出 stdout，不宣稱磁碟 artifact 或持久化。所有本輪新增附件／測試產物為 **0**，舊殘留及自動審核阻擋保持原樣，不重試清理；禁止 `KeepArtifacts`，測試與清理分報，中斷、占用或自動審核拒絕不得冒稱已刪除，也不得繞過拒絕。

前輪因未先辨識 conftest 建構副作用，已知殘留（均含該根）為 `C:\Users\YiCheng\AppData\Local\Temp\taiwan-stock-m1p2a-01a0fe7e` **243 entries／11 files／993,443 bytes**；其中 `code-tests` **240 entries／10 files／125,120 bytes**、`live` **2 entries／1 file／868,323 bytes**。前輪統一根上限 **200 entries／20 MiB**、`code-tests` 子目錄上限 **100 entries／10 MiB**，entries 已超配額；兩處 exact 清理皆在 CreateProcess 前被自動審核拒絕（`blocked by policy`），未執行。停止新增落盤測試，不能換根繞過上限；不為重驗 live 而造檔。conftest 另在 default Temp 建立一個 `_TEST_ROOT`，確切名稱及其內數量／大小未核實，獨列為未知，不能聲稱空目錄、已清理或掃 Temp 猜測 owned。前輪首跑有一個測試 assertion 失敗，其修正、既有 fixture 唯讀復核、純記憶體回歸及測試／清理分開收據留來源 task；未完整重跑該落盤 pytest，首跑不能改報全通過。清理限制不否定已接受的真實數值與有效測試證據。

較早一輪 `C:\Users\YiCheng\AppData\Local\Temp\taiwan-stock-m1-01a0fe5a` 殘留 **118 entries／105 files／17,319,956 bytes**；UI 與 code-tests 清理被自動審核拒絕，未執行，確切收據留來源 task。本輪不再嘗試繞過拒絕；有效驗收不因清理失敗被否定，後續保持隔離，不冒稱已刪除。

## 歷史與維護

舊角色 ID、交付狀態、測試及 commit 證據由 [Git／原 task](README.md#歷史查閱) 追溯；舊分派不覆蓋 AGENTS，也不恢復已刪除附件或舊統籌派工權。更新本文件時替換目前狀態，不追加逐輪日誌。
