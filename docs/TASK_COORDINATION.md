# 協作與接手狀態

本文件保留目前維護角色、接手與停止要求，以及最近產品交付的實際 roster／驗收邊界；流程依 [AGENTS](../AGENTS.md)，能力與優先順序查 [ROADMAP](ROADMAP.md)。

## 目前：獨立角色模型設定維護，產品續作停止要求保留

使用者已核定後續角色模型與 Reasoning 調整，完整配置只由 [AGENTS「四個角色」](../AGENTS.md#四個角色)負責。新建或恢復角色須核對新配置；修改文件不會自動切換既有 chat，舊 session 的實際參數保留原值。

這是已授權的獨立文件維護，不建立無程式工作的程式角色，也不恢復產品 round。M2-P2 完成並提交後，使用者要求「這裡做完可以先停止一下」；已建立的 M1-P4a chat 仍受此停止要求約束。本次只整理角色規則及已核實交付狀態，不增加產品、資料來源、PIT 或研究模型完成度。

共同 repo：`C:\Users\YiCheng\Desktop\taiwan-stock-research`、`master` 原 checkout；接手 HEAD：`054ecad7fb0860797ef6c61f7b9da759b398fc2e`。主 chat 與兩個本 session 新建的 subagent 已核對共同 repo／HEAD、乾淨接手及互不衝突的寫入白名單；各角色不自行結案或啟動下一任務。

| 維護角色 | 實際 session／建立參數與接手 | 寫入／驗收範圍 |
| --- | --- | --- |
| 維護主 chat | session `01a0ffb0-9855-7e62-9c71-28234f1167ff`；實際 `gpt-6.1-sol`／`xhigh`（已核實 turn_context），不是新產品統籌 runtime 切換 | 修改 `AGENTS.md` 的角色配置及規則；核定既有文件狀態、review／freeze 與提交範圍。 |
| 文件 | canonical ID `/root/role_docs`；子 session `01a0ffb5-5ca2-7251-a5e5-a14422b71399`；`gpt-6.1-sol`／`xhigh`；已接手 | `docs/TASK_COORDINATION.md`、`docs/README.md`、`docs/ROADMAP.md`、`docs/ROADMAP_EXECUTION.md`；另僅修正 `docs/PRODUCT_SPEC.md`、`docs/STOCK_RESEARCH_PAGE.md`、`docs/development-baseline/README.md` 的 M2-P2 舊待 freeze 字樣。不改 AGENTS、程式、Git 或索引。 |
| 索引與 Git commit | canonical ID `/root/role_index`；子 session `01a0ffb5-954e-76f0-97cd-9b25f7399e9a`；`gpt-6-luna`／`medium`；已接手 | 接受文件並 freeze 後才刷新涉及分區、驗 coverage；只 stage／commit 核准檔案，不改來源或 push。 |

本次文件增補總量上限 **16 KiB**，本次文件／測試附件、暫存與其殘留配額均為 **0**；只驗差異、連結及一致性，不跑 backend 測試。所有現有專案 Markdown 須核對角色相關內容；未受影響的契約與研究模型只回報已核對，不製造 diff。索引引擎必要管理儲存與 log 依原 task 的有界核定，不當附件，也不宣稱零寫入。維護的驗證、freeze／索引／本地 commit receipt 留原 task，不另建附件或為回寫 hash 再改文件。下一步僅完成本次維護驗收；產品續作須有恢復授權，再核對角色配置、接手與精確範圍。

## 最近產品交付：M2-P2 官方事件清單搜尋與研究往返有限接受，已版本封存

該輪依使用者「根據你的建議繼續做下去吧」執行。M1-P1、M1-P2a、M1-P2b、M1-P3a、M1-P3b、後續依賴唯讀審查及 M2-P1 已有限接受並版本封存；完整 5／20 交易日窗口與研究條件仍等待外部來源或完整證據。來源統籌 session `01a0ff66-f44d-72c3-877c-10eac148f33b` 已完成前輪交接並停止派工，前輪已 freeze／索引／本地 commit，最終 receipt 留原 task，文件中的候選字樣不表示尚未提交。該輪新統籌依 [M2](ROADMAP.md#接下來的順序近期產品里程碑) 核定 M2-P2「官方事件清單搜尋與研究往返」，不增加完整 M1／M2 或 PIT 完成度；本地 commit 不含 push 或歷史重寫。

共同 repo：`C:\Users\YiCheng\Desktop\taiwan-stock-research`、`master` 原 checkout；接手時乾淨 HEAD：`240ac377bf86a6f82704c1eaaa514df426967171`。該輪統籌 session `01a0ff98-7580-7f03-a0d7-a2c75aa3edea`、三個子 session、共同 repo、HEAD 與乾淨工作目錄已由統籌核對；該統籌實際為 `gpt-6-astra`／`high`，已依來源 session 的 turn_context 核實。三個 subagent 均為該統籌 session 以 `fork_turns=none` 新建且已正式確認接手，canonical ID 相同字樣不代表沿用前輪角色。

### 該輪 roster 與寫入範圍

| 角色 | 該輪 ID／實際建立參數 | 寫入／驗收範圍 |
| --- | --- | --- |
| 統籌 | session `01a0ff98-7580-7f03-a0d7-a2c75aa3edea`；實際 `gpt-6-astra`／`high`（已核實來源 turn_context） | 核定 M2-P2 搜尋／返回契約、來源與時間語意，負責真原件／API、桌面／窄版操作及數值／來源驗收；接受程式與文件後才 freeze。 |
| 程式 | canonical agent ID `/root/implementation`；子 session `01a0ff99-4430-7b32-b655-c0bfda2b6556`；建立參數 `fork_turns=none`、`gpt-6.1-sol`／`ultra` | `backend/app/api.py`、`backend/app/official_events.py`、`backend/tests/test_official_event_focus.py`、`frontend/src/App.tsx`、`frontend/src/api.ts`、`frontend/src/types.ts`、`frontend/src/styles.css`；依核定契約接搜尋／數量／研究往返及必要記憶體驗證。不改 docs、AGENTS、consumer／manifest／pins、DB／legacy、索引或 Git，不自行修改規格。 |
| 文件 | canonical agent ID `/root/documentation`；子 session `01a0ff99-8f83-79c2-a023-9449a8017148`；建立參數 `fork_turns=none`、`gpt-6.1-sol`／`xhigh` | `docs/TASK_COORDINATION.md`、`docs/ROADMAP.md`、`docs/ROADMAP_EXECUTION.md`、`docs/STOCK_RESEARCH_PAGE.md`、`docs/SOURCE_REGISTRY.md`、`docs/PRODUCT_SPEC.md`、`docs/development-baseline/README.md`；依實作與統籌 review 更新受影響既有文件及接手狀態。不改程式、AGENTS、manifest、索引或 Git。 |
| 索引與 Git commit | canonical agent ID `/root/index_commit`；子 session `01a0ff99-d535-7790-96e1-d94ec73a4757`；建立參數 `fork_turns=none`、`gpt-6-luna`／`medium` | freeze 後才刷新涉及分區、驗 coverage，並只 stage／commit 統籌核准檔案；不改來源或 push。 |

runtime 提供 canonical ID 與上述子 session ID，未提供 agent UUID。文件角色以環境 `CODEX_THREAD_ID` 核對自身子 session；建立參數及統籌實際 model／reasoning 已核對；這是該輪實際紀錄，不能倒改成後續的新配置。所有角色不得自行結案或啟動下一任務；共同 repo、HEAD、乾淨接手與互不衝突的精確寫入白名單已由統籌核對。

### 接手成果、缺口與下一步

1. **完成及驗收邊界**：先前獨立文件維護已接受文件流程與一致性，不增加產品完成度。R1-A2-P1-identity 與 P2+ 成交額政策、程式補強保留原有限 review；缺額／明確零的單一離線 fixture capture→SQLite→API 已有限驗收並版本封存，不升格官方真實樣本、全市場或 R1-A2 整體完成。詳細契約見 [DATA_SOURCES](DATA_SOURCES.md#r1-a2-p2-成交金額可得狀態有限接受)。
2. **完成及驗收邊界、尚缺項**：M1-P1 的 TWSE 1101／2330、2026-10-01 單日 selected 真實價格六欄、detail／總覽 API 一致、指定截止排除與晚於價格提示、桌面／窄版具名操作及後端邊界回歸、前端 SSR／型別／production build 已有限 review；保留大型 JS chunk 警告，精確契約及支持範圍見[個股頁 §9](STOCK_RESEARCH_PAGE.md#9-m1-p1截止一致與來源可追溯總覽)。M1-P2a 的單來源 manifest、capture／selected 摘要 library／CLI、單日兩檔數值與具名負向已有限接受並版本封存。M1-P2b 的 TPEx 3105／6488、2026-10-02 原件→實際 API 二十個數值、端點一致與追溯欄位、桌面／窄版具名操作已有限 review 並版本封存；精確契約及支持範圍見[個股頁 §10](STOCK_RESEARCH_PAGE.md#10-m1-p2b單日法人原件總覽接線)。P2b 未跑完整 backend／production Vite build，記憶體全 App bundle 不作 production 驗收，該輪不重驗。M1-P3a 程式、當次 TWSE 0056（ETF）／1449／1463 未來生效預告的原件／實際 CLI、缺 selected 拒收與記憶體靶向回歸已有限接受，精確支持範圍見[來源契約 §9](SOURCE_REGISTRY.md#9-m1-p3atwt48u-selected-官方事件原件摘要)；source gate 縮窄後只跑必要複驗，現完整案例與完整 backend 未重跑，本次 live 不能離線重播。完整 M1 的 5／20 交易日窗口、完整事件 coverage 與研究條件仍缺；selected 總覽接線由前輪 P3b 有限交付並版本封存。R1-A2 的 legacy migration、其他 invalid／拒收磁碟整合、正式 DB、逐市場／session／欄位 coverage、availability／歷史／PIT 與量截整／TAIEX 合成欄位風險不變。其餘 R0 與 B2 snapshot／body／receipt／attempt／ordinal／pins 缺口維持原邊界，不重複搜尋或建 specimen。
3. **完成及驗收邊界 → 尚缺項 → 下一步與依賴／完成條件**：前輪 M1-P3b 的 selected 真原件四欄、追溯、截止排除、端點一致、同 process cache 與具名桌面／窄版操作已有限接受並版本封存；精確範圍見[個股頁 §11](STOCK_RESEARCH_PAGE.md#11-m1-p3bselected-官方事件總覽接線)。完整 M1 的 5／20 交易日基準、多日法人原件與研究條件門檻的唯讀審查已接受；相關窗口／條件等待外部來源或完整證據，非使用者暫停，也不推論 ROADMAP 全部餘項受阻。恢復須可信完整交易日基準、已准入多日法人原件與範圍／缺日 coverage，研究條件另須必要輸入／來源／時間／分類 gate；主缺口與詳細來源審查見 [ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)及[來源 §10](SOURCE_REGISTRY.md#10-m1-後續依賴審查來源候選與等待邊界)。前輪 M2-P1 程式、一次 exact TWT48U 真原件 58 列／58 股的四欄與列序→API、相同截止的 M1 0056（ETF）／1449／1463，以及具名桌面／窄版操作已有限接受；主契約與驗收範圍見[個股頁 §12](STOCK_RESEARCH_PAGE.md#12-m2-p1官方事件關注清單接個股總覽)。測試 memory catalogue 只提供上述三標的 metadata，其餘 55 股保留來源身分與事件但無連結，不是正式行情／DB coverage。合法空 feed、同股多事件、100 股截斷與拒收是 fixture 邊界，不冒充本次 live 情境；原件未保存，不能離線重播。下一步由新統籌依里程碑核定下一個可用子能力及所需來源／時間／分類 gate；不沿用該輪角色，未滿足的完整 M1／M2／M3 保持原驗收條件。
4. **該輪完成及驗收邊界 → 尚缺項**：M2-P2 程式、必要記憶體／前端驗證、一次真原件 58 列／58 股→API、具名搜尋、桌面 M1 改截止後返回原條件及窄版搜尋／清除／往返已由統籌有限接受。空原件、101 股以上先搜尋再截斷、匹配外壞列及同股名稱／完整事件仍是 fixture 邊界，不冒充 live；3 個 memory catalogue 標的不代表真行情／正式 DB，原件未保存、不能離線重播。完整 backend／production Vite build 未跑，完整 M1／M2／M3 與 PIT gate 不變；精確契約和具名範圍見[個股頁 §13](STOCK_RESEARCH_PAGE.md#13-m2-p2官方事件清單搜尋與研究往返)。
5. **freeze／索引／commit**：前輪 M2-P1 及該輪 M2-P2 均已 freeze、索引與本地 commit，原統籌已確認 M2-P2 的 14 個核准檔、9 aliases coverage、提交與乾淨工作區；最終 receipt 留原 task，不為回寫 commit hash 反覆改文件。M1-P4a 統籌 chat 已建立，使用者其後要求停止產品續作；不得以本次模型維護恢復。新角色仍須依 [AGENTS](../AGENTS.md#每輪流程) 核對接手與互斥白名單，不沿用該輪角色；目前停止要求與後續核對見上方維護狀態。

該輪 M2-P2 支援 M2／R2-D1，解除完整合格原件搜尋與 M1 返回原條件的斷點；先驗全原件再搜尋／套上限，固定返回路徑，不新增來源、排名、金融推論、PIT 或 DB 寫入。詳細 query／計數／空值／返回規則只由[個股頁 §13](STOCK_RESEARCH_PAGE.md#13-m2-p2官方事件清單搜尋與研究往返)負責，不把 M1 窗口外部 gate 套到本批獨立能力。

下一輪候選為 **M1-P4a「TWSE 單日法人官方來源有界可行性與准入」**，先核實官方 exact 來源、用途權利、實際欄位／日期／單位、完整回應與 selected 可驗性；gate 滿足後才由新統籌核定最小 consumer → M1 總覽能力，來源不足則具名等待，不無限重搜或把規劃當交付。詳細範圍、依賴及 M3 評估見[里程碑下一步](ROADMAP.md#接下來的順序近期產品里程碑)。M1-P4a 統籌 chat 已建立，但產品續作受使用者停止要求約束；本次維護不恢復；恢復授權後再核對新配置、session、子角色與精確白名單，不沿用該輪角色。

該輪文件只修改白名單內既有檔案，總增補上限 **32 KiB**，文件角色額外附件／暫存配額為 **0**；文件只做差異、連結與一致性檢查，不跑 backend 測試。程式的純記憶體 fixture 與真原件／API／UI 驗收分報，完整 backend／production build 未跑不得稱通過。該輪不執行 collect／backfill 入口或正式 DB 操作；只核定統籌一次 exact 公開 TWT48U memory capture，驗收 catalogue 限 0056（ETF）／1449／1463 路由 metadata，不當真行情或 DB coverage。既有落盤 entries 已超配額，該輪額外產物及殘留上限均為 **0**，不換根或改名繞過限制。已接受的 capture 契約維持 `source-memory-capture/v1`、`storage=memory_only`，不宣稱磁碟 artifact 或持久化。舊殘留及自動審核阻擋保持原樣，不重試清理；禁止 `KeepArtifacts`，測試與清理分報，中斷、占用或自動審核拒絕不得冒稱已刪除，也不得繞過拒絕。

該輪測試與清理分報：78 個後端記憶體靶向測試、前端型別／最終 16 組 SSR／全 App 記憶體 bundle，以及真原件／API／具名桌面／窄版操作已有限接受；Unicode 空白／0000 年修正後必要前端複驗已接受，完整 backend／production Vite build 未跑。測試 helper 首輪 11 個失敗及 SSR helper 首次模組 path 失敗，修正後才有通過結果；原始失敗／成功與不同 Node 版本分報留 task，不改報首跑通過。QA tab 已關閉、viewport 已還原；專用 backend／frontend 自有進程均正常 exit 0，來源 request 共 1 次，memory body 隨程序釋放。新增附件／暫存及 owned 待清產物為 0；文件角色未跑測試、未建附件。命令、版本、exit、hash 與清理收據留 task；這不表示下列舊殘留已清理。

M1-P2a 輪因未先辨識 conftest 建構副作用，已知殘留（均含該根）為 `C:\Users\YiCheng\AppData\Local\Temp\taiwan-stock-m1p2a-01a0fe7e` **243 entries／11 files／993,443 bytes**；其中 `code-tests` **240 entries／10 files／125,120 bytes**、`live` **2 entries／1 file／868,323 bytes**。該輪統一根上限 **200 entries／20 MiB**、`code-tests` 子目錄上限 **100 entries／10 MiB**，entries 已超配額；兩處 exact 清理皆在 CreateProcess 前被自動審核拒絕（`blocked by policy`），未執行。停止新增落盤測試，不能換根繞過上限；不為重驗 live 而造檔。conftest 另在 default Temp 建立一個 `_TEST_ROOT`，確切名稱及其內數量／大小未核實，獨列為未知，不能聲稱空目錄、已清理或掃 Temp 猜測 owned。該輪首跑有一個測試 assertion 失敗，其修正、既有 fixture 唯讀復核、純記憶體回歸及測試／清理分開收據留來源 task；未完整重跑該落盤 pytest，首跑不能改報全通過。清理限制不否定已接受的真實數值與有效測試證據。

較早一輪 `C:\Users\YiCheng\AppData\Local\Temp\taiwan-stock-m1-01a0fe5a` 殘留 **118 entries／105 files／17,319,956 bytes**；UI 與 code-tests 清理被自動審核拒絕，未執行，確切收據留來源 task。該輪不再嘗試繞過拒絕；有效驗收不因清理失敗被否定，後續保持隔離，不冒稱已刪除。

## 歷史與維護

舊角色 ID、交付狀態、測試及 commit 證據由 [Git／原 task](README.md#歷史查閱) 追溯；舊分派不覆蓋 AGENTS，也不恢復已刪除附件或舊統籌派工權。更新本文件時替換目前狀態，不追加逐輪日誌。
