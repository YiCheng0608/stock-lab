# 協作與接手狀態

本文件只留目前角色、接手與下一步；流程依 [AGENTS](../AGENTS.md)，能力與優先順序查 [ROADMAP](ROADMAP.md)。

## 本輪：M2-P1 官方事件關注清單有限接受，文件待 freeze

使用者最新明示「根據你的建議繼續做下去吧」。M1-P1、M1-P2a、M1-P2b、M1-P3a、M1-P3b 與後續依賴唯讀審查已有限接受並版本封存；完整 5／20 交易日窗口與研究條件仍等待外部來源或完整證據。來源統籌 session `01a0ff0d-27c3-7ea0-963d-5f608d418859` 已完成前輪交接並停止派工，前輪本地 commit 與最終 receipt 由原 task 追溯。本輪新統籌依 [M2](ROADMAP.md#接下來的順序近期產品里程碑) 核定 M2-P1「官方事件關注清單 → M1 個股總覽」，不增加完整 M1／M2 或 PIT 完成度；本地 commit 不含 push 或歷史重寫。

共同 repo：`C:\Users\YiCheng\Desktop\taiwan-stock-research`、`master` 原 checkout；接手時乾淨 HEAD：`007f363ed56f1536d69c49e4fa97577fda62d49a`。本輪統籌 session `01a0ff66-f44d-72c3-877c-10eac148f33b`、三個子 session、共同 repo、HEAD 與乾淨工作目錄已由統籌核對；runtime 未提供可核實的統籌 model／reasoning，不猜測。三個 subagent 均為本 session 以 `fork_turns=none` 新建且已正式確認接手，canonical ID 相同字樣不代表沿用前輪角色。

### 本輪 roster 與寫入範圍

| 角色 | 本輪 ID／實際建立參數 | 寫入／驗收範圍 |
| --- | --- | --- |
| 統籌 | session `01a0ff66-f44d-72c3-877c-10eac148f33b`；runtime 未提供可核實的 model／reasoning | 核定 M2-P1 範圍、來源與時間語意，負責真原件／API、桌面／窄版操作及數值／來源驗收；接受程式與文件後才 freeze。 |
| 程式 | canonical agent ID `/root/m2_code`；子 session `01a0ff6e-2504-7590-a7fa-98d54ef0ce2d`；建立參數 `fork_turns=none`、`gpt-6.1-sol`／`ultra` | `backend/app/official_events.py`、`backend/app/api.py`、`backend/worker/twse_action_capture.py`、`backend/tests/test_official_event_focus.py`、`backend/tests/test_official_events.py`、`frontend/src/App.tsx`、`frontend/src/api.ts`、`frontend/src/types.ts`、`frontend/src/styles.css`；核定 consumer、關注 API／UI 與具名記憶體／來源操作已有限接受。不改 docs、AGENTS、manifest／pins、DB／legacy、索引或 Git，不自行修改規格。 |
| 文件 | canonical agent ID `/root/m2_docs`；子 session `01a0ff6e-6727-7ec0-8ba7-93dd6bdfc818`；建立參數 `fork_turns=none`、`gpt-6.1-sol`／`xhigh` | `docs/TASK_COORDINATION.md`、`docs/ROADMAP.md`、`docs/ROADMAP_EXECUTION.md`、`docs/STOCK_RESEARCH_PAGE.md`、`docs/SOURCE_REGISTRY.md`、`docs/PRODUCT_SPEC.md`，驗證入口受影響時另含 `docs/development-baseline/README.md`；依實作與統籌 review 更新受影響既有文件及接手狀態。不改程式、AGENTS、manifest、索引或 Git。 |
| 索引與 Git commit | canonical agent ID `/root/m2_index`；子 session `01a0ff6e-a886-7901-ab35-8faa63f8a341`；建立參數 `fork_turns=none`、`gpt-6-luna`／`medium` | freeze 後才刷新涉及分區、驗 coverage，並只 stage／commit 統籌核准檔案；不改來源或 push。 |

runtime 提供 canonical ID 與上述子 session ID，未提供 agent UUID。文件角色以環境 `CODEX_THREAD_ID` 核對自身子 session；建立參數由統籌核對，不猜測 runtime 未證實的 effective model／reasoning。所有角色不得自行結案或啟動下一任務；共同 repo、HEAD、乾淨接手與互不衝突的精確寫入白名單已由統籌核對。

### 接手成果、缺口與下一步

1. **完成及驗收邊界**：獨立文件維護已接受文件流程與一致性，不增加產品完成度。R1-A2-P1-identity 與 P2+ 成交額政策、程式補強保留原有限 review；缺額／明確零的單一離線 fixture capture→SQLite→API 已有限驗收並版本封存，不升格官方真實樣本、全市場或 R1-A2 整體完成。詳細契約見 [DATA_SOURCES](DATA_SOURCES.md#r1-a2-p2-成交金額可得狀態有限接受)。
2. **完成及驗收邊界、尚缺項**：M1-P1 的 TWSE 1101／2330、2026-10-01 單日 selected 真實價格六欄、detail／總覽 API 一致、指定截止排除與晚於價格提示、桌面／窄版具名操作及後端邊界回歸、前端 SSR／型別／production build 已有限 review；保留大型 JS chunk 警告，精確契約及支持範圍見[個股頁 §9](STOCK_RESEARCH_PAGE.md#9-m1-p1截止一致與來源可追溯總覽)。M1-P2a 的單來源 manifest、capture／selected 摘要 library／CLI、單日兩檔數值與具名負向已有限接受並版本封存。M1-P2b 的 TPEx 3105／6488、2026-10-02 原件→實際 API 二十個數值、端點一致與追溯欄位、桌面／窄版具名操作已有限 review 並版本封存；精確契約及支持範圍見[個股頁 §10](STOCK_RESEARCH_PAGE.md#10-m1-p2b單日法人原件總覽接線)。P2b 未跑完整 backend／production Vite build，記憶體全 App bundle 不作 production 驗收，本輪不重驗。M1-P3a 程式、當次 TWSE 0056（ETF）／1449／1463 未來生效預告的原件／實際 CLI、缺 selected 拒收與記憶體靶向回歸已有限接受，精確支持範圍見[來源契約 §9](SOURCE_REGISTRY.md#9-m1-p3atwt48u-selected-官方事件原件摘要)；source gate 縮窄後只跑必要複驗，現完整案例與完整 backend 未重跑，本次 live 不能離線重播。完整 M1 的 5／20 交易日窗口、完整事件 coverage 與研究條件仍缺；selected 總覽接線由前輪 P3b 有限交付並版本封存。R1-A2 的 legacy migration、其他 invalid／拒收磁碟整合、正式 DB、逐市場／session／欄位 coverage、availability／歷史／PIT 與量截整／TAIEX 合成欄位風險不變。其餘 R0 與 B2 snapshot／body／receipt／attempt／ordinal／pins 缺口維持原邊界，不重複搜尋或建 specimen。
3. **完成及驗收邊界 → 尚缺項 → 下一步與依賴／完成條件**：前輪 M1-P3b 的 selected 真原件四欄、追溯、截止排除、端點一致、同 process cache 與具名桌面／窄版操作已有限接受並版本封存；精確範圍見[個股頁 §11](STOCK_RESEARCH_PAGE.md#11-m1-p3bselected-官方事件總覽接線)。完整 M1 的 5／20 交易日基準、多日法人原件與研究條件門檻的唯讀審查已接受；相關窗口／條件等待外部來源或完整證據，非使用者暫停，也不推論 ROADMAP 全部餘項受阻。恢復須可信完整交易日基準、已准入多日法人原件與範圍／缺日 coverage，研究條件另須必要輸入／來源／時間／分類 gate；主缺口與詳細來源審查見 [ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)及[來源 §10](SOURCE_REGISTRY.md#10-m1-後續依賴審查來源候選與等待邊界)。本輪 M2-P1 程式、一次 exact TWT48U 真原件 58 列／58 股的四欄與列序→API、相同截止的 M1 0056（ETF）／1449／1463，以及具名桌面／窄版操作已有限接受；主契約與驗收範圍見[個股頁 §12](STOCK_RESEARCH_PAGE.md#12-m2-p1官方事件關注清單接個股總覽)。測試 memory catalogue 只提供上述三標的 metadata，其餘 55 股保留來源身分與事件但無連結，不是正式行情／DB coverage。合法空 feed、同股多事件、100 股截斷與拒收是 fixture 邊界，不冒充本次 live 情境；原件未保存，不能離線重播。下一步由新統籌依里程碑核定下一個可用子能力及所需來源／時間／分類 gate；不沿用本輪角色，未滿足的完整 M1／M2／M3 保持原驗收條件。
4. **freeze／索引／commit**：前輪已 freeze、索引與本地 commit，receipt 留前輪 task。本輪程式與具名驗收已有限接受；最終文件為 freeze 候選，尚未 freeze、刷新或 commit。統籌接受文件後才 freeze；其後由索引角色刷新、驗 coverage，統籌核准提交檔案後本地 commit。最終 receipt 留本輪 task，不為回寫 commit hash 反覆改文件。所有角色不自行結案或啟動下一任務；下一輪仍按 [AGENTS](../AGENTS.md#每輪流程) 建立新統籌 session 與三個新 subagent，核定接手與互斥白名單，目前尚未建立下一輪。

下一輪交接候選為 **M2-P2「官方事件清單搜尋與研究往返」**，支援 M2／R2-D1；全原件驗證先於按原件代碼／名稱搜尋，符合結果再套 100 股上限，明列原件／符合／顯示數與截斷。從 M1 返回須保留同一 `as_of` 與搜尋條件；不新增來源、排名、金融推論、PIT 或 DB 寫入，精確 API 搜尋契約與操作／上限邊界由新統籌核定，不等待 M1 窗口外部 gate。程式候選範圍為 `backend/app/api.py`、`backend/app/official_events.py`、`backend/tests/test_official_event_focus.py`、`frontend/src/App.tsx`、`frontend/src/api.ts`、`frontend/src/types.ts`、`frontend/src/styles.css`；consumer／pins 無需變更，文件沿用本輪七個既有檔案，索引只輪末刷新。下一輪統籌尚未建立；新 session 及三個新子角色仍須重新核對 ID、共同 repo、接手與精確互斥白名單，不能由這段候選自動沿用本輪角色。

本輪文件只修改白名單內既有檔案，總增補上限 **32 KiB**，文件角色額外附件／暫存配額為 **0**；文件只做差異、連結與一致性檢查，不跑 backend 測試。程式的純記憶體 fixture 與真原件／API／UI 驗收分報，完整 backend／production build 未跑不得稱通過。本輪不執行 collect／backfill 入口或正式 DB 操作；只核定一次官方事件 memory capture。既有落盤 entries 已超配額，本輪額外產物及殘留上限均為 **0**，不換根或改名繞過限制。已接受的 capture 契約維持 `source-memory-capture/v1`、`storage=memory_only`，不宣稱磁碟 artifact 或持久化。舊殘留及自動審核阻擋保持原樣，不重試清理；禁止 `KeepArtifacts`，測試與清理分報，中斷、占用或自動審核拒絕不得冒稱已刪除，也不得繞過拒絕。

本輪測試與清理分報：後端純記憶體必要回歸、前端型別／SSR／記憶體 bundle 及真原件／API／具名桌面／窄版操作已接受；完整 backend／production Vite build 未跑。非 available 回應與新聞區矛盾文案退修後，必要回歸及同一 live cache 真畫面複驗已接受，原始失敗／退修與成功收據留 task，不改報首版通過。QA tab 已關閉、viewport 已還原；backend、最後一次及先前兩次專用 frontend 自有進程均已終止、exit 0，memory body 隨 process 釋放。新增附件／暫存為 0，無新增 owned 測試附件待刪除；這不表示下列舊殘留已清理。

M1-P2a 輪因未先辨識 conftest 建構副作用，已知殘留（均含該根）為 `C:\Users\YiCheng\AppData\Local\Temp\taiwan-stock-m1p2a-01a0fe7e` **243 entries／11 files／993,443 bytes**；其中 `code-tests` **240 entries／10 files／125,120 bytes**、`live` **2 entries／1 file／868,323 bytes**。該輪統一根上限 **200 entries／20 MiB**、`code-tests` 子目錄上限 **100 entries／10 MiB**，entries 已超配額；兩處 exact 清理皆在 CreateProcess 前被自動審核拒絕（`blocked by policy`），未執行。停止新增落盤測試，不能換根繞過上限；不為重驗 live 而造檔。conftest 另在 default Temp 建立一個 `_TEST_ROOT`，確切名稱及其內數量／大小未核實，獨列為未知，不能聲稱空目錄、已清理或掃 Temp 猜測 owned。該輪首跑有一個測試 assertion 失敗，其修正、既有 fixture 唯讀復核、純記憶體回歸及測試／清理分開收據留來源 task；未完整重跑該落盤 pytest，首跑不能改報全通過。清理限制不否定已接受的真實數值與有效測試證據。

較早一輪 `C:\Users\YiCheng\AppData\Local\Temp\taiwan-stock-m1-01a0fe5a` 殘留 **118 entries／105 files／17,319,956 bytes**；UI 與 code-tests 清理被自動審核拒絕，未執行，確切收據留來源 task。本輪不再嘗試繞過拒絕；有效驗收不因清理失敗被否定，後續保持隔離，不冒稱已刪除。

## 歷史與維護

舊角色 ID、交付狀態、測試及 commit 證據由 [Git／原 task](README.md#歷史查閱) 追溯；舊分派不覆蓋 AGENTS，也不恢復已刪除附件或舊統籌派工權。更新本文件時替換目前狀態，不追加逐輪日誌。
