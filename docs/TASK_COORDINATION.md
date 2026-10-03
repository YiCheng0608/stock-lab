# 協作與接手狀態

本文件保留目前角色、接手與執行狀態，以及最近產品交付的實際 roster／驗收邊界；流程依 [AGENTS](../AGENTS.md)，能力與優先順序查 [ROADMAP](ROADMAP.md)。

## 目前：M3-P1 既有庫存股數精確呈現與失精輸入拒收已有限接受

使用者已明確要求開始產品輪並持續推進 [ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)。本輪「M3-P1 既有可信庫存股數→精確張／零股／原股呈現與失精輸入拒收」的九個程式檔、必要記憶體／實際 HTTP／前端驗證及具名桌面／390px 庫存操作已由統籌有限接受；支援 M3／R2-C1 的既有庫存單位基線，採現有 Float 的可信安全整數、精確字串相容表示及 commit 前拒收，不是完整 M3 或精確大數存儲。主契約與具名支持範圍集中見 [UI 文案 §10.3](UI_COPY_SPEC.md#m3-p1-既有庫存股數的有限呈現契約)，正常估值／決策／計畫不改。QA tab／兩個自有程序與 listener 已核實關閉或不存在，新增測試產物／殘留為 0，測試與清理 exit 0 分報。角色配置依 [AGENTS「四個角色」](../AGENTS.md#四個角色)，三個 subagent 均由本輪統籌在其 session 以 `fork_turns=none` 新建；canonical 名稱相同不代表沿用舊角色。各角色不自行結案或啟動下一任務。

前輪「M1／R1-A2 成交量 HTTP→JavaScript→個股精確呈現」的 15 個核定程式檔、必要記憶體／HTTP／完整字串邊界複驗與 TWSE／TPEx 具名操作已有限接受；20 個核准檔已 freeze、更新五個索引分區、本地提交 `40ec36c2933ba96887893b6ad7f683280bdfe4b6`（parent `b608710c301ed26321289d0851aba89e31ebb46b`），並由統籌確認 fast-forward 合併至乾淨 `master`。本輪接手 HEAD 即該已驗收版本，最終 commit／merge receipt 留原 task。前輪新增測試產物／殘留為 0，自有 tab／程序／listener 已核實關閉或不存在；兩個 serve 的 exit 1 與測試 exit 0 分報，不增加完整 M1 完成度。精確支持範圍集中見[個股頁 §14](STOCK_RESEARCH_PAGE.md#14-m1r1-a2成交量-httpjavascript個股精確呈現)，fixture 不外推真官方／live 或正式 DB。

更早「R1-A2 legacy 成交量 gate→capture／collect／SQLite／reopen／API 精確保存與拒收保留」的七個核准檔案已有限接受、freeze、索引、本地提交並合併至 `master`。有效證據為 1 compound unittest／0 skip、兩次 force collect／60 個 HTTP 回應，test／cleanup／process exit 均為 0、核定測試根已核實不存在、產品來源 diff 為 0。兩市場合法整數／拒收與磁碟重開／HTTP token 的精確支持範圍見[資料來源](DATA_SOURCES.md#r1-a2-legacy-成交量磁碟整合)，入口副作用與配額見[開發入口](development-baseline/README.md#r1-a2-legacy-成交量的磁碟整合驗證入口)；首次直接 `& .ps1` 的載入前 policy 失敗留原 task，不稱首個命令通過。

更早 legacy 成交量 parser gate、selected invalid／拒收磁碟整合及 migration 均保留原有限接受與提交／合併邊界，仍對應目前來源的有效證據不因換 session 重跑；詳見[資料來源](DATA_SOURCES.md)及[開發入口](development-baseline/README.md)。M1-P4a 有界來源與程式唯讀審查已接受，TWSE exact 單日法人來源仍未准入，`local_fetch`／`raw_store`／`summarize` 權利仍 unknown，未取得法人原件、未核定 consumer 或產品接線，既有 pins／抓取範圍不變；缺證與恢復條件集中見[來源 §12](SOURCE_REGISTRY.md#12-m1-p4atwse-單日法人有界審查與准入缺口)。完整 5／20 日窗口、研究條件、M2／M3 與 PIT 保留原驗收範圍。

共同 repo／worktree：`C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-m3-share-quantity-exact-presentation-20261003`；branch：`roadmap-m3-share-quantity-exact-presentation-20261003`；起始 HEAD：`40ec36c2933ba96887893b6ad7f683280bdfe4b6`，與最新已驗收且乾淨的 `master` 相同。獨立 worktree／branch 已先建立；統籌已獨立核實四角色實際 runtime cwd、branch、起始 HEAD、model／reasoning、三子角色 parent、乾淨接手及互斥白名單，啟動 gate 已通過。

Orca 可見性已核實：本輪原 terminal `term_f77477d5-6a3c-49c9-b86f-bd174e906473`，tab `eaa811e6-6717-4927-b5a3-66317350ac36`／pane 1，已核得 `connected`、`writable` 及 `nonorphaned`。統籌從該原可見 terminal 的 `/subagents` 核對 Main／root 與三角色，四個 ID 與下表一致；可見性及配置由實際 terminal、runtime 與 Git 核實。

本輪 pinned 共用 helper 首次實際 exit 0，startup verified／surface visible；本輪無啟動失敗、替代或重複啟動。唯一 UTF-8 任務讀回可讀，共 9,835 字，SHA-256 `a8835d6dfd1cb0acaf0e3b3564804bace8f347f12aef79eecfeea206948e2ddd`；turn ID `01a101f4-659f-7fe1-bd1b-2f908ab5f4e4` 已實核 `inProgress`。前輪統籌已核實附帶 fallback shell `term_521f092c-7f5b-433c-bb14-95151898a378` 關閉，`ptyKilled=true`。

| 角色 | 本輪 ID／實際配置與接手 | 寫入／驗收範圍 |
| --- | --- | --- |
| 統籌 | canonical ID `/root`；session `01a101f4-61f7-78e2-aa11-1aae57db5b65`；實際 `gpt-6.1-sol`／`ultra`；已核實並接手 | 已核定 M3-P1 用途、資料範圍、最小契約、必要依賴與完成條件，以及互斥白名單與零落盤驗證。負責產品及數值／來源驗收，接受程式及文件後 freeze，複核索引，分別明確核准 commit／本地 merge；已接手前輪外部清理。 |
| 程式 | canonical ID `/root/implementation`；子 thread `01a101f5-f5c8-7e30-970c-ed7725a928cd`；實際 `gpt-6.1-sol`／`xhigh`；已核實並接手 | 僅九檔：`backend/app/units.py`、`backend/app/api.py`、新增 `backend/tests/test_share_quantity_exact_presentation.py`；`frontend/src/units.ts`、`frontend/src/units.test.ts`、`frontend/src/types.ts`、`frontend/src/App.tsx`、`frontend/src/styles.css`（只窄版庫存）；新增 `tools/share-quantity-exact-preview.cjs`。程式及核定證據已有限接受，不自改規格、文件、來源 gate、索引或 Git，交付後等統籌 freeze。 |
| 文件 | canonical ID `/root/documentation`；子 thread `01a101f6-4255-7f31-8b2b-1d1245e96777`；實際 `gpt-6.1-sol`／`xhigh`；已核實並接手 | 僅 `docs/TASK_COORDINATION.md`、`docs/UI_COPY_SPEC.md`、`docs/ROADMAP.md`、`docs/ROADMAP_EXECUTION.md`、`docs/development-baseline/README.md`，依統籌有限接受結論更新主契約、實際支持範圍、未驗與接手；最終文件待統籌 review／freeze。不改程式、其他文件、AGENTS、索引或 Git。 |
| 索引與 Git commit | canonical ID `/root/index_commit`；子 thread `01a101f6-8dee-7980-990e-fb88af1e987a`；實際 `gpt-6-luna`／`medium`；已核實並接手 | 來源寫入白名單為空；freeze 後才統一更新涉及分區及驗 coverage，commit／本地 merge 各待統籌明確授權。不輪初／中途刷新，不 push 或重寫歷史。 |

上述實際 model／reasoning 均由統籌獨立讀取 UTF-8 runtime `session_meta`／`turn_context` 核實，三個子 thread 的 parent 均為本輪統籌。各子角色 `CODEX_THREAD_ID` 為自身子 thread ID，runtime `session_id` 才是 root；不能把繼承環境值或 Rpc 的 root `sessionId` 當成子角色 ID。舊 session 的實際參數保留 Git／原 task 及下方既有紀錄，不因本輪配置倒改。

本輪文件增補總量上限 **32 KiB**，文件附件／暫存與新增測試產物配額均為 **0**；文件只驗差異、UTF-8 讀回、連結及一致性，不跑 backend 或建 DB。文件角色 App codebase-memory list／index_status verbose／coverage 成功：主線 docs 索引 ready，本輪 worktree 尚無 alias，`TASK_COORDINATION.md` 為 `no_recorded_issue`／`metadata_changed`，scope 僅刻意排除 `.codebase-memory`、`has_more=false`，因此原文補核。尚未本輪 freeze／刷新，待統籌接受後由索引角色統一更新；連線、索引與 coverage 分開留 task。

**完成及驗收邊界 → 尚缺項 → 下一步與依賴／完成條件**：本輪九個程式檔、5 direct tests／0 skip／145 actual router HTTP requests、必要前端型別／units／14 組 Portfolio SSR／記憶體 bundle、51 個 product fetch HTTP，以及主契約具名兩市場桌面／390px 操作已有限接受；測試及清理各 exit 0，QA 還原／tab 關閉、自有程序／listener 不存在、新增測試產物／殘留 0 已獨立核實；首跑非有限拒收的 error JSON 修正後才通過，原始失敗與工具點擊／refs 限制留 task，不稱首跑或未生效操作通過 → ORM Float 只支持目前可信值 `0..SAFE`、寫入只 `1..SAFE`；純 int／ASCII 字串顯示支持 int64 MAX 另證，不代表 ODD／MAX DB 保存，記憶體 commit／refresh／GET 不等磁碟重開。正式 DB、真官方／live、估值、新計畫、完整 backend／production build、完整 M3、歷史／availability／PIT 與原 M1／M2 gate 保留 → 下一具名候選可信整數保存／legacy unsafe migration 證據與磁碟重開，須本輪合併後新統籌有界核依賴、修法與完成條件，詳見 [ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)，本輪不固定方案。**freeze／索引／commit／merge**：程式、必要證據與產品操作已有限接受，最終五文件待統籌 review；尚未 freeze／刷新／提交／合併，commit／merge 各待統籌明確授權，最終 receipt 留 task，不為回寫 hash 反覆刷新或提交。PRODUCT_SPEC 的精確股數／CRUD／每股成本與風險未知不給張數已核對，契約未變，不製造 diff。

前輪 `roadmap-m1-volume-exact-presentation-20261003` 的外部清理由本輪統籌接手，收據與功能驗收分報：統籌先 actual Rpc 逐四 ID 核 latest completed，舊 terminal 關閉 exit 0、`ptyKilled=true`；再核四 ID 後 archive 前輪 root `01a101b2-fde9-7a01-ba04-40a584a21915`，`cascade=true`，獨立 helper Rpc 的 includeTurns／loaded list 讀回四 ID 均為 `archived_sessions`／`notLoaded`／`loaded=false`／latest completed。terminal 另核 `orphaned=true`／`connected=false`／`writable=false`／`paneRuntime=-1`／`exitCause=operator_close`。worktree／branch 移除的整個 exec 在 CreateProcess 前遭 automatic review 拒絕（`blocked by policy`），未執行、不重試或換工具；Git／Orca 登錄與 branch 仍存在，HEAD 為 `40ec36c2933ba96887893b6ad7f683280bdfe4b6`。exact 根 `C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-m1-volume-exact-presentation-20261003` 已核為 non-reparse、**208 files／14 directories／3,528,690 bytes**，無子 reparse；這是 owned worktree 資源殘留，不是測試產物，不否定已確認的功能與合併。該輪五 aliases 的 `delete_project` 均回 `deleted`，兩個 exact logs（**287／414 bytes**）的 native `Remove-Item` exit 0；統籌獨立 App list 核 total 8／`has_more=false` 且僅原八 aliases，exact M1 prefix 的 cache DB／aux 與 logs 均為空清單。五 cache DB 的 **33,947,648 bytes** 加兩 logs 的 **701 bytes**，合計 **7 files／33,948,349 bytes** 已全部核實不存在，新增目錄為 0；此結果不表示 worktree／branch 已清。舊 **1,173 bytes** 審核拒絕 logs、未核占用者的空根、歷史資料與其他測試殘留未動，不重試或掃描其他資源。下列更早清理的實際結果保留，本輪資源須待交接或結案及外部負責者接手後處理。

前輪 `roadmap-r1-a2-legacy-volume-integration-20261003` 的指定外部清理已由索引角色執行、統籌獨立複核：四個 exact ID 皆為 `archived_sessions`／`notLoaded`／`loaded=false`／latest completed；Orca tab 已關閉且 terminal 斷線，`closeMode=tab`／`ptyKilled=false`、`orphaned=true`／`connected=false`／`writable=false`／`paneRuntime=-1`／`exitCause=operator_close`，PTY 終止未核，不宣稱已終止。Git worktree 登錄及 branch 已無該輪，三個 cache DB 共 **19,529,728 bytes** 與兩個指定 logs 共 **707 bytes** 均核實不存在，App list 僅原八分區／`has_more=false`。原絕對 worktree 根 `C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-r1-a2-legacy-volume-integration-20261003` 仍為 **0 entries／0 files／0 bytes** 的非 reparse 空目錄；一次 exact `Remove-Item` 因其他程序占用的 `IOException` 失敗，不重試，不能稱根已清。這是資源空根殘留，不是測試產物；前輪實際模型及完整收據留 Git／原 task，不倒改。更早遭自動審核拒絕的四個 logs／**1,173 bytes**、selected-invalid 空根、歷史資料及其他舊資源未動；本輪資源待交接或結案及外部清理負責者接手後處理。

更早 legacy volume gate 的實際參數保留：worktree／branch `roadmap-r1-a2-volume-integer-20261003`，起始 HEAD `04b99aecc5a1d2ed8d4514b4d3cb60c7b8336450`；統籌 `01a1015e-1855-7281-9413-1fdf8c276dbf`、`gpt-6.1-sol`／`ultra`，程式 `01a10160-0520-7261-8351-1fc4b7b14598` 與文件 `01a10160-50d4-7a12-9465-7172b859a2f2` 均為 `gpt-6.1-sol`／`xhigh`，索引 `01a10160-8e36-78c2-a903-93ad634fc10c` 為 `gpt-6-luna`／`medium`，原 terminal `term_dde103f5-44a4-4932-8483-3bc792338c55`。原統籌已接受該輪指定外部清理：先關閉舊 terminal、`ptyKilled=true`，再 archive 舊 root cascade；三次子角色單獨 archive 曾回 `no rollout found`，但統籌隨後逐四個 exact ID 獨立讀回均為 `archived_sessions`／`notLoaded`／`loaded=false`／latest completed，已解除封存核實限制，無需重複 archive。Orca 移除回 `removed=true`，統籌另核原絕對 worktree 不存在、Git 登錄與 branch 不存在，當時 `master` 為 `9013884d0dfeae811a02ff858cba42b7ab4bebd5`；三個 aliases 經共用同引擎 CLI 刪除，list 僅原八分區，三個 cache DB 與該輪 **279 bytes** exact log 均核實不存在。該輪指定資源已清，不表示更早殘留已清；新舊 session 不共用派工權。

更早 selected invalid／拒收的清理保留原收據：原 terminal 已關閉、`ptyKilled=true`；舊統籌被使用者 resume 時先暫緩封存，最新 turn completed 後四 ID 均已核得 `archived_sessions`／`notLoaded`／`loaded=false`。Orca worktree 移除 exit 1（runtime unavailable／connection closed），其後核對 Orca selector 與 Git worktree 登錄均已不存在，已合併的 branch 另以 `git branch -d` 移除；source 已移除，但原絕對根 `C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-r1-a2-selected-invalid-20261003` 仍為 **0 files／0 bytes** 的非 reparse 空目錄，exact 空目錄清理 exit 1，因其他 process 占用，未核得占用者、未終止其他程序，不能冒稱目錄已清。該輪三個索引 aliases 已刪除、三 cache DB 不存在，當時 list 僅原八分區；兩個該輪 index logs 共 **628 bytes** 清理遭自動審核拒絕，未執行且不重試／換工具繞過。更早 legacy migration 已核實的 session／worktree／branch／索引清理保留原紀錄，另有兩個舊 logs 共 **545 bytes** 的既有審核拒絕殘留未動。這些資源殘留與本輪產物分開；exact 路徑與命令收據留原 task，清理失敗不停止產品工作。舊維護 session、歷史資料與既有測試殘留不納入本輪清理；本輪資源待交接或結案及外部清理負責者接手後再核實處理。

### 先前協作流程維護的實際參數

該次為使用者已授權的協作流程文件維護，共同 repo 為 `C:/Users/YiCheng/Desktop/taiwan-stock-research`、`master` 原 checkout，乾淨接手 HEAD `553d83e5a684b2ca576edafb955ab848f185a7d8`。該次獨立維護未恢復產品 round，M1-P4a 與既有 roster 保留原實際紀錄；後續產品 round 適用 [AGENTS「每輪流程」](../AGENTS.md#每輪流程)。

| 角色 | 本次 ID／已核實實際配置 | 寫入／驗收範圍 |
| --- | --- | --- |
| 統籌 | session `01a10067-5cd7-7d21-bbe7-3d0d4229ae05`；`gpt-6.1-sol`／`ultra` | 核定治理範圍、roster、白名單及配額；review 文件及程式唯讀審查後 freeze，複核索引與提交。 |
| 程式 | canonical ID `/root/docs_rule_review`；子 thread `01a10088-08d9-7bd1-9c41-ebcfa90761bd`；`gpt-6.1-sol`／`xhigh` | 僅唯讀審查規則一致性；寫入白名單為空。 |
| 文件 | canonical ID `/root/docs_update`；子 thread `01a10087-73b2-7b73-9522-849266e482fd`；`gpt-6.1-sol`／`xhigh` | 僅 `AGENTS.md`、`docs/TASK_COORDINATION.md`；依核定範圍更新，差異、連結及一致性檢查。 |
| 索引與 Git commit | canonical ID `/root/index_git_finish`；子 thread `01a1009a-9863-7902-b04c-0ed8cae02967`；`gpt-6-luna`／`medium` | 接手複查索引連線；freeze 後更新涉及分區、驗 coverage，只 stage／commit 統籌核准檔案。 |

統籌以 runtime `session_meta`／`turn_context` 核實共同 cwd、parent thread 與上述實際 model／reasoning；表列 subagent 均由本統籌以 `fork_turns=none` 新建、已接手，白名單互斥。文件增補上限 **12 KiB**，附件、暫存、測試新增產物與殘留配額均為 **0**；只驗文件，不跑 backend、不建 DB。先前 codebase-memory MCP 未暴露，合法 stdio／同引擎 CLI 路徑均遭 DACL 阻擋；使用者已授權新索引角色接手複查，同引擎 CLI 重試尚無成功收據。文件驗收後 freeze，索引／coverage 與 commit 待實際驗證，收據留本 task。

原索引角色 `/root/index_git_update`、子 thread `01a10087-bb76-7ae3-b191-795ba2562b2f`、`gpt-6-luna`／`medium` 的實際參數及未完成收據保留原 task；本次依使用者授權由上述新索引角色接手。

### 前次獨立維護：共用環境與新輪啟動

使用者曾明確授權跨專案共用環境修復及新輪啟動順序修正。該次共同 repo 為 `C:/Users/YiCheng/Desktop/taiwan-stock-research`、`master` 原 checkout，未改專案產品來源、不算產品 round；下列角色為該次維護實際 roster，未沿用至本輪，既有 session 的實際參數保留原值。

| 角色 | 本次 ID／實際配置 | 寫入／驗收範圍 |
| --- | --- | --- |
| 統籌 | session `01a100cc-7538-7c00-8c36-1eb12378d00e`；實際 `gpt-6.1-sol`／`xhigh`（已核實 runtime）；不作為下一輪統籌 | 核定本次共用環境修復與文件驗收；維護本機兩份 CBM config、全域 AGENTS 及 session control 工具，不改專案產品來源。 |
| 程式 | canonical ID `/root/cbm_runtime_fix`；子 thread `01a100f3-674c-76e1-81d8-fcc645393662`；建立參數 `fork_turns=none`、`gpt-6.1-sol`／`xhigh` | 僅本機 `.local/bin` 的 CBM 三個 launcher 與相關 User env；不改專案來源、索引或 Git。 |
| 文件 | canonical ID `/root/docs_handoff_limit`；子 thread `01a100d9-a2d0-7af3-939b-70c2077348d4`；`gpt-6.1-sol`／`xhigh`，沿既有 follow-up 配置 | 僅 `AGENTS.md`、`docs/TASK_COORDINATION.md`；依統籌核定邊界更新、檢查差異及一致性，不改程式、索引或 Git。 |
| 索引與 Git commit | canonical ID `/root/index_commit`；子 thread `01a100d0-ed35-7bc0-9d2d-a294a1f094c7`；實際 spawn 配置 `gpt-6-luna`／`medium` | source freeze 後才更新涉及分區、驗 coverage；核准來源僅 `AGENTS.md`、`docs/TASK_COORDINATION.md`，核准後才 stage／commit。 |

**維護接受邊界**：CLI 遭 DACL 阻擋的直接原因已核定為 npm shim 未繼承 MCP config env；本機共用 Node／`.cmd` 入口已固定 runtime／cache，Codex App 與 Orca CBM config 統一使用該入口。User env 持久化已接受，新程序可從 User registry 取得環境；既有 App process 不會自動繼承，共用絕對路徑入口不依賴舊 process env。支持 reload 後本次統籌的 runtime 由 failed 恢復 connected，連續三次成功列出全部八個索引分區，coverage／read／search 亦成功。雙 stdio client 的初始化、三輪並發 list 各列出八分區、關閉 A 後 B 仍可 list，以及 A／B 各正常 exit 0 已接受。這支持缺失 env 的修正、健康檢查、重載恢復與 CLI 備援可用；舊 daemon 消失的原始原因尚未證明，不宣稱已修 upstream daemon 或永不斷線。共用入口、status／reload 的完整路徑與命令由全域 AGENTS 及原 task 保存，專案不重寫全域修復規則。

**啟動 guard 的有限接受範圍**：AGENTS 第 1／5 步的順序修正已 review 接受。本機工具對原 checkout／`master` 的實測為拒絕（exit 1），未建立 session；記憶體 gate 驗證接受一個合法 worktree 情境，拒絕分支錯誤、master SHA 過時、工作區不乾淨及 worktree 未註冊四個情境，均未建立 session。維護當時只接受這些有限 guard 證據，實際產品 worktree 與新統籌 runtime 的驗收由本輪另行完成，見上方目前狀態。

**維護交接**：PowerShell launcher 的 UTF-8 stdin 保護及必要中文輸入複驗已接受，三個共用 launcher source 已 freeze，未建立測試附件或額外殘留。流程與索引維護已本地提交，最終 receipt 留原 task，不為回寫 hash 再改文件。產品接手已由獨立 worktree 及實際 `gpt-6.1-sol`／`ultra` runtime 驗證解除；不等待未證明的 daemon 原始根因，也未沿用該次 root 或維護 roster。當時由產品統籌接手的舊維護四個 session 已關閉／封存，實際收據留原 task。

### 新產品 round 接手：啟動待辦已解除（2026-10-03）

流程及索引維護已本地提交，新輪啟動嘗試前 `master` 工作區乾淨。先前嘗試先建立統籌 session、尚未建立產品 branch／worktree，操作順序錯誤；Codex TUI task `01a100d2-c509-7f72-a122-4e26ae104794` 實際為 `gpt-6.1-sol`／`xhigh`，不符合統籌的 `gpt-6.1-sol`／`ultra`，未作為本輪統籌。這些實際參數保留，不倒改。

先前 TUI readiness 限制仍按原收據保留：Orca 替代終端雖顯示 `ultra`，`tui-idle` 等待 60 秒及 90 秒均逾時；依 orca-cli 技能指南未送 task prompt，已關閉空終端 `term_12e18c58-da4f-4e15-887c-31fa56d464f1`。本輪已先建立獨立產品 branch／worktree，再啟動並核實新統籌 runtime、新建三角色及確認接手；先前啟動限制已解除，現行 roster 與範圍見上方，舊維護統籌不再派工。

啟動 gate 與接手條件由 [AGENTS「每輪流程」](../AGENTS.md#每輪流程)詳述；實際產品接手及 Orca 可見性核實已解除該次限制。前輪 R1-A2 legacy migration 指定磁碟驗收已接受，本輪 selected invalid／拒收整合與接手狀態見上方。M1-P4a 的 exact 來源及權利仍等待證據，維持原准入與驗收邊界；新輪啟動本身不增加產品完成度。

上次模型設定維護的接手 HEAD `054ecad7fb0860797ef6c61f7b9da759b398fc2e` 與實際參數保留為歷史：主 chat `01a0ffb0-9855-7e62-9c71-28234f1167ff`、`gpt-6.1-sol`／`xhigh`（已核實 turn_context）；文件 `/root/role_docs`、`01a0ffb5-5ca2-7251-a5e5-a14422b71399`、`gpt-6.1-sol`／`xhigh`；索引 `/root/role_index`、`01a0ffb5-954e-76f0-97cd-9b25f7399e9a`、`gpt-6-luna`／`medium`。該次未恢復產品 round；範圍及 receipt 留 Git／原 task，沒有沿用上述舊角色或倒改既有實際配置。

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
5. **freeze／索引／commit**：前輪 M2-P1 及該輪 M2-P2 均已 freeze、索引與本地 commit，原統籌已確認 M2-P2 的 14 個核准檔、9 aliases coverage、提交與乾淨工作區；最終 receipt 留原 task，不為回寫 commit hash 反覆改文件。M2-P2 後的停止要求曾約束已建立的 M1-P4a chat，上次模型維護未恢復產品；本次使用者已明確恢復，新的三角色配置、接手與互斥白名單已核對，目前狀態見上方。

該輪 M2-P2 支援 M2／R2-D1，解除完整合格原件搜尋與 M1 返回原條件的斷點；先驗全原件再搜尋／套上限，固定返回路徑，不新增來源、排名、金融推論、PIT 或 DB 寫入。詳細 query／計數／空值／返回規則只由[個股頁 §13](STOCK_RESEARCH_PAGE.md#13-m2-p2官方事件清單搜尋與研究往返)負責，不把 M1 窗口外部 gate 套到本批獨立能力。

M2-P2 交接候選 **M1-P4a「TWSE 單日法人官方來源有界可行性與准入」** 已由後續輪完成有界審查並接受，exact 來源及權利仍等待證據。R1-A2 legacy migration 的前輪驗收與本輪 selected invalid／拒收整合、角色及接手範圍見上方；詳細里程碑、依賴及 M3 評估見[里程碑下一步](ROADMAP.md#接下來的順序近期產品里程碑)。

該輪文件只修改白名單內既有檔案，總增補上限 **32 KiB**，文件角色額外附件／暫存配額為 **0**；文件只做差異、連結與一致性檢查，不跑 backend 測試。程式的純記憶體 fixture 與真原件／API／UI 驗收分報，完整 backend／production build 未跑不得稱通過。該輪不執行 collect／backfill 入口或正式 DB 操作；只核定統籌一次 exact 公開 TWT48U memory capture，驗收 catalogue 限 0056（ETF）／1449／1463 路由 metadata，不當真行情或 DB coverage。既有落盤 entries 已超配額，該輪額外產物及殘留上限均為 **0**，不換根或改名繞過限制。已接受的 capture 契約維持 `source-memory-capture/v1`、`storage=memory_only`，不宣稱磁碟 artifact 或持久化。舊殘留及自動審核阻擋保持原樣，不重試清理；禁止 `KeepArtifacts`，測試與清理分報，中斷、占用或自動審核拒絕不得冒稱已刪除，也不得繞過拒絕。

該輪測試與清理分報：78 個後端記憶體靶向測試、前端型別／最終 16 組 SSR／全 App 記憶體 bundle，以及真原件／API／具名桌面／窄版操作已有限接受；Unicode 空白／0000 年修正後必要前端複驗已接受，完整 backend／production Vite build 未跑。測試 helper 首輪 11 個失敗及 SSR helper 首次模組 path 失敗，修正後才有通過結果；原始失敗／成功與不同 Node 版本分報留 task，不改報首跑通過。QA tab 已關閉、viewport 已還原；專用 backend／frontend 自有進程均正常 exit 0，來源 request 共 1 次，memory body 隨程序釋放。新增附件／暫存及 owned 待清產物為 0；文件角色未跑測試、未建附件。命令、版本、exit、hash 與清理收據留 task；這不表示下列舊殘留已清理。

M1-P2a 輪因未先辨識 conftest 建構副作用，已知殘留（均含該根）為 `C:\Users\YiCheng\AppData\Local\Temp\taiwan-stock-m1p2a-01a0fe7e` **243 entries／11 files／993,443 bytes**；其中 `code-tests` **240 entries／10 files／125,120 bytes**、`live` **2 entries／1 file／868,323 bytes**。該輪統一根上限 **200 entries／20 MiB**、`code-tests` 子目錄上限 **100 entries／10 MiB**，entries 已超配額；兩處 exact 清理皆在 CreateProcess 前被自動審核拒絕（`blocked by policy`），未執行。停止新增落盤測試，不能換根繞過上限；不為重驗 live 而造檔。conftest 另在 default Temp 建立一個 `_TEST_ROOT`，確切名稱及其內數量／大小未核實，獨列為未知，不能聲稱空目錄、已清理或掃 Temp 猜測 owned。該輪首跑有一個測試 assertion 失敗，其修正、既有 fixture 唯讀復核、純記憶體回歸及測試／清理分開收據留來源 task；未完整重跑該落盤 pytest，首跑不能改報全通過。清理限制不否定已接受的真實數值與有效測試證據。

較早一輪 `C:\Users\YiCheng\AppData\Local\Temp\taiwan-stock-m1-01a0fe5a` 殘留 **118 entries／105 files／17,319,956 bytes**；UI 與 code-tests 清理被自動審核拒絕，未執行，確切收據留來源 task。該輪不再嘗試繞過拒絕；有效驗收不因清理失敗被否定，後續保持隔離，不冒稱已刪除。

## 歷史與維護

舊角色 ID、交付狀態、測試及 commit 證據由 [Git／原 task](README.md#歷史查閱) 追溯；舊分派不覆蓋 AGENTS，也不恢復已刪除附件或舊統籌派工權。更新本文件時替換目前狀態，不追加逐輪日誌。
