# 協作與接手狀態

本文件保留目前角色、接手與執行狀態，以及最近產品交付的實際 roster／驗收邊界；流程依 [AGENTS](../AGENTS.md)，能力與優先順序查 [ROADMAP](ROADMAP.md)。

## 目前：M3-P4 可信讀回與非法停損隔離已有限接受，待成果文件 review／freeze

本輪先由 M3-P3 已封存 master 建獨立 worktree／branch，再啟動可見統籌；四角色 runtime／Git／原 terminal 的 /subagents 與接手已核實，下文保留 roster。M3-P4 九檔實作、必要零落盤驗證及具名操作已有限接受，支援 M3／R2-C1；主契約與支持範圍見 [UI 文案](UI_COPY_SPEC.md#m3-p4-既有庫存價值可信讀回與非法停損隔離)。五成果文件待統籌 review／freeze，不升格完整 M3；各角色不自行結案或啟動下一任務。

共同 repo／worktree：`C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-m3-portfolio-value-read-validation-20261004`；branch：`roadmap-m3-portfolio-value-read-validation-20261004`；起始 HEAD：`fa6f66fe16cc75c79057fb233871222638f0404a`，與接手時最新已驗收且乾淨的 `master` 相同。前輪 M3-P3 的十二個核准檔已提交該 SHA（parent `ee376aae9cacb1d21279b4fdb27ab8da6d14dbe4`），統籌已確認 ff-only 合併後 `master` 為同一 SHA 且乾淨；最終 receipt 留原 task。

本輪原可見 terminal 為 `term_977b6540-3e8a-4d52-9b93-87b6ea3e0824`，tab `49292d5f-bcb2-40a7-926f-743e1fa40cdd`／pane 1。統籌已從該 terminal 的 `/subagents` 讀回 Main／root 與下表三角色，四個 exact ID 一致；外部已獨立讀回同組四 ID 及完整差異，正式接手已確認。Pinned 共用啟動 helper 只執行一次，exec `60761`／exit 0；runtime 核得唯一 UTF-8 任務可讀，共 **12,475 字元**，SHA-256 `e395ee6d7f2938d95286757a51bc99b99346d892a80264144a3180e5cf66e5a4`，turn ID `01a102ff-c247-7ff0-b793-5f1a49d74867`。

| 角色 | 本輪 ID／實際配置與接手 | 核定寫入／驗收範圍 |
| --- | --- | --- |
| 統籌 | canonical ID `/root`；session `01a102ff-bad5-7940-be22-d811426f8b8a`；實際 `gpt-6.1-sol`／`ultra`；parent 為 null，已核實並接手 | 已核定 M3-P4 九檔實作／五檔文件與零新增測試落盤；已有限接受三態、非法停損隔離、原 gate 優先及具名產品操作，九檔來源 SHA 核一致。接受成果文件後才 freeze／輪末索引，commit／本地 merge 分別明授；前輪指定 session／worktree／branch／索引檔清理已完成，舊 HAR／review-blocked／occupied 資源排除。 |
| 程式 | canonical ID `/root/implementation`；子 thread `01a10301-2f61-7842-b406-5ac154243d59`；實際 `gpt-6.1-sol`／`xhigh`；已核實並接手 | 寫入限九檔：新增 `backend/app/portfolio_values.py`；`backend/app/api.py`、`backend/app/decision.py`、`backend/app/level_semantics.py`、`frontend/src/types.ts`、`frontend/src/portfolioValues.ts`、`frontend/src/App.tsx`、`backend/tests/test_share_quantity_exact_presentation.py`、`tools/share-quantity-exact-preview.cjs`。九檔實作與必要零落盤 direct／前端／actual HTTP 及具名操作已由統籌有限接受，待成果文件 review 後 aggregate freeze；不改規格、文件、索引或 Git。 |
| 文件 | canonical ID `/root/documentation`；子 thread `01a10301-6a55-7ad0-b9b9-3d3fe6416b7f`；實際 `gpt-6.1-sol`／`xhigh`；已自核並接手 | 白名單限五份既有文件：`docs/TASK_COORDINATION.md`、`docs/UI_COPY_SPEC.md`、`docs/ROADMAP.md`、`docs/ROADMAP_EXECUTION.md`、`docs/development-baseline/README.md`。初始 roster 已由統籌及外部原 terminal／差異複核接受；五份成果文件已依實作及統籌接受結論更新主契約、有限成果、未驗項與下一候選待裁定狀態，交付後停寫待 review／freeze。整輪增補上限 32 KiB、附件 0，只驗差異、UTF-8 讀回、連結與一致性，不改程式、其他文件、索引或 Git。 |
| 索引與 Git commit | canonical ID `/root/index_commit`；子 thread `01a10301-a365-7332-ae7d-520a028e50f4`；實際 `gpt-6-luna`／`medium`；已核實並接手 | 來源寫入白名單為空；本輪尚未 freeze，不刷新／commit／merge。只在統籌接受文件與 aggregate freeze 後更新核定分區、驗 coverage，commit／本地 merge 各待明授；不 push 或重寫歷史。 |

三個 subagent 均由本輪統籌在其 session 以 `fork_turns=none` 新建，parent 均為 `01a102ff-bad5-7940-be22-d811426f8b8a`；各自 `CODEX_THREAD_ID`／runtime `id` 為子 thread，runtime `session_id` 為 root。統籌已獨立以 Rpc `thread/read` 與 runtime `session_meta`／`turn_context` 核配置、parent、cwd 及 Git 起點；canonical 名稱相同不代表沿用舊角色，不倒改前輪實際參數。

輪初 CBM App 連線成功，`list_projects` 列出 **13 個既有分區**，本輪 worktree 尚未登錄；baseline docs 索引 ready、395 nodes／394 edges，無 recorded parse／skip gap。本 worktree 的 `AGENTS.md`、`docs/TASK_COORDINATION.md` coverage 為 `outside_project`／freshness unavailable，因此直接補讀本輪原文。連線、索引與 coverage 分報，沒有輪初刷新；待來源及文件接受並 freeze 後才由索引角色更新涉及分區。

本輪新增測試落盤、附件、暫存及殘留配額維持 **0**，文件增補總量上限 **32 KiB**；必要索引另核獨立配額，不解除測試限制。前輪 HAR `C:/Users/YiCheng/.agent-browser/tmp/har/har-1791044803009.har` 的 **1 file／64,885 bytes** 及其他既有 review-blocked／occupied／未知殘留維持原收據，全部排除本輪正常 owned cleanup，不重試或換工具、不掃 shared 目錄、不以新 session 重置配額；未清理不得稱已刪除。

本輪 freeze 後的必要索引計畫只限 prefix `taiwan-stock-research-roadmap-m3-portfolio-value-read-validation-20261004-` 的 **五個 unique partitions**：`backend-app`→`backend/app`、`backend-tests`→`backend/tests`、`frontend-src`→`frontend/src`、`tools`→`tools`、`docs`→`docs`（均為本 worktree 下的 exact root），full index／`persistence=false`。五個 DB 合計最多 **64 MiB**、tool-returned logs 最多 **5 files／8 KiB**、十五個已知 aux 最多 **15 files／8 MiB**；new directories／`.codebase-memory` 均 **0**。目前統籌已核該 prefix 的五個 DB／十五個已知 aux 不存在、cache 及 ancestors non-reparse、App 原八 aliases，未刷新。文件接受並 aggregate freeze 後才授權索引角色執行；各分區 coverage 核 exact paths 及 `scopes=['.']`、`limit=500`／`offset=0`，parse partial 與 coverage 均為 best-effort，不當功能驗收。此為 index 的獨立 cap，不解除測試／附件 cap 0 或舊資源 no-retry 排除。

前輪 M3-P3 的指定外部清理已完成，與功能／合併驗收分報。四個 exact ID（下方保留）經立即 Rpc 逐一核 latest completed 後，關閉原 terminal `term_7fdc0cfd-af6a-453f-8a9b-3998a8133864`，actual exit 0／`ptyKilled=true`；再次立即核四 ID latest completed 後 archive 舊 root cascade，回 `archived=true`，統籌獨立逐四 ID 核得 `archived_sessions`／`notLoaded`／`loaded=false`／latest completed。唯一 worktree `C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-m3-portfolio-value-validation-20261004`／同名 branch，刪前已核根與 ancestors 為 non-reparse、**214 files／14 directories／3,694,122 bytes**、乾淨 HEAD `fa6f66fe16cc75c79057fb233871222638f0404a` 為已合併 `master` ancestor 且未使用；Orca remove actual exit 0／`removed=true`，統籌另核根不存在、Git worktree／branch 空，Orca show exit 1／`selector_not_found` 是不存在的預期，不改報 exit 0。

五個 aliases 只限 prefix `taiwan-stock-research-roadmap-m3-portfolio-value-validation-20261004-` 的 `backend-app`／`backend-tests`／`frontend-src`／`tools`／`docs`，App delete 全回 `deleted`，DB 合計 **34,930,688 bytes**。Returned logs **僅兩個**：`C:/Users/YiCheng/cbm-cache/logs/taiwan-stock-research-roadmap-m3-portfolio-value-validation-20261004-backend-tests-1791051187.log`（**288 bytes**）與 `C:/Users/YiCheng/cbm-cache/logs/taiwan-stock-research-roadmap-m3-portfolio-value-validation-20261004-tools-1791051238.log`（**415 bytes**），Remove-Item 各 exit 0。統籌與角色兩次實測 **7 owned files／34,931,391 bytes** 均與前輪 receipt 相同；統籌另核 **22 個 exact DB／sidecar／log 路徑均不存在**，App list total 8、只剩原 aliases／`has_more=false`。HAR、其他舊 review-blocked／occupied 資源、歷史及其他 worktrees 全部排除，不重試或換工具；前輪 empty default shell 雖先前已觀測退出，沒有 actual PTY kill 證據，保留原收據，不推論已終止 PTY。

本輪新增的空 default shell `term_87c16b57-b3be-4e51-8dd7-c2aaa305b0d1` 經原 prompt 唯讀核實後關閉，exit 0／`ptyKilled=true`；目前仍可由 list 讀得 disconnected／non-writable／`exitCause=operator_close`，不宣稱已從 list 消失。原四角色 terminal 不在這次關閉範圍。

必要零落盤 direct／前端驗證已有限接受，版本、測試數、入口及支持範圍見[開發入口](development-baseline/README.md#m3-p4-庫存價值可信讀回的零落盤驗證入口)。後端首次 exit 1 是測試誤讀 instruments decision_summary，只改為既有 quality_summary.research 後才通過；既有 SSR／TestClient warnings 分報，不稱首跑或 production build 通過。

Actual HTTP 首次 exit 1 為工具誤取 result.meta.total，只改 assertion 為 result.pagination.total；複跑 17 GET／十四列／十四個完整 decisions／0 mutations、exit 0。最後 SQL snapshot 首次 exit 1 為誤取 sha256，改取 whole_row_sha256 後 exit 0，全十四列全欄／note／updated_at／typeof 前後同 hash。工具修正未改產品；最終來源 SHA、SQL hash、命令留原 task。具名操作只由 [UI 文案](UI_COPY_SPEC.md#m3-p4-既有庫存價值可信讀回與非法停損隔離)負責。

QA 原 tab 首次 snapshot／eval 各 runtime_unavailable、exit 1，原 tab focus 後恢復；其他失敗 probe 留原 task。Offscreen click exit 0 卻沒導頁，未接受；捲至可見並 fresh read 後實際導頁才接受。Scoped memory fetch 三個 GET／200、mutation／external 0，Orca console messages=[] 僅支持該擷取；本輪未測保存／刪除，窄版 mobile=false，不稱硬體手機／觸控驗收。

測試與清理分報：QA 還原 actual 1365×900、document 寬均 1350，原 tab close exit 0／list 空。先核 exact owned command lines，再自有 shutdown 8778／8777，各 exit 0、兩 serve exec final exit 0／Python unexpected_denials=[]；統籌另核 owned PIDs／listeners／children 空。未開 HAR capture，新磁碟產物／附件／暫存／殘留 0；舊 HAR／blocked／occupied 排除。詳細 PIDs／exec 與收據留原 task，文件角色未重跑產品測試。

下一候選 M3-P5「可信庫存股數與既有估值／持倉判定一致」支援 M3／R2-C1；P4 依賴已解除，raw Float 估值／held 判定尚未一致。合併後交新 worktree／新統籌有界核必要 caller、正數／zero／unknown、篩選／計數及超 JS safe integer 邊界，再裁定最小能力／互斥白名單；完整範圍與限制見[ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)。候選未實作／驗收，不預定修法或把 unknown 當 0／未持倉，不縮減原磁碟契約。

**完成及驗收邊界 → 尚缺項 → 下一步與依賴／完成條件 → freeze／索引／commit／merge**：M3-P4 九檔實作、必要零落盤 direct／前端／actual HTTP 與具名桌面／390px 操作已有限接受，自有資源已清、新產物 0；M3-P3 已封存及指定清理完成 → 五成果文件待 review／freeze；正式 DB／磁碟重開、官方／live、全估值／風險行動、Decimal exact、完整 backend／production build、new Plan／完整 M3／PIT 未驗，舊殘留排除 → 合併後新 worktree／新統籌有界核 M3-P5 caller、範圍／完成條件及互斥白名單，不沿用本輪角色 → 本輪未 aggregate freeze／索引／commit／merge；接受文件後才輪末索引／coverage，複核後各別明授本地 commit／merge，最終 receipt 留 task。

## 前輪 M3-P3：輸入檢核與拒收保留已有限接受並版本封存

前輪 M3-P3 的七個程式檔／五文件共十二檔已接受、freeze／索引／版本封存，本地 commit 與乾淨 master 為 fa6f66fe16cc75c79057fb233871222638f0404a。有限支持 UI 原字串、actual upsert helper 序列化前 gate、raw HTTP 拒收與完整列／draft 保留，主契約見 [UI 文案](UI_COPY_SPEC.md#m3-p3-庫存成本停損風險輸入可信檢核與拒收保留)。必要記憶體／JSON／HTTP 與具名兩市場操作、自有 QA／程序／listeners 清理、新磁碟產物 0 已接受；首次失敗、warnings 及未驗正式 DB／磁碟重開、所有估值／風險行動／完整 M3／PIT 的邊界見[開發入口](development-baseline/README.md#m3-p3-庫存價值輸入的零落盤驗證入口)與原 task，不重跑或改報首次通過。指定外部清理見上方；HAR／其他舊殘留未動。

前輪實際配置保留：統籌 `01a102bf-c30f-7183-84db-3bd75b154c53` 為 `gpt-6.1-sol`／`ultra`；程式 `01a102c4-1758-7f30-97fc-4c5a02f07416`、文件 `01a102c4-68f7-7762-bcf0-25e130d8ea49` 均為 `gpt-6.1-sol`／`xhigh`；索引 `01a102c4-c120-7111-b1e2-0479dd1fb502` 為 `gpt-6-luna`／`medium`。前輪從 `ee376aae9cacb1d21279b4fdb27ab8da6d14dbe4` 起始，原 terminal `term_7fdc0cfd-af6a-453f-8a9b-3998a8133864` 的 runtime／同組四 ID 可見性已核實；原 helper 首次 exit 1、同 session 恢復接手的邊界不倒改。前輪已完成 M3-P2 指定 session／worktree／branch／索引清理，HAR 及其他舊殘留未動；詳細驗收、清理與版本封存 receipt 由 Git／原 task 追溯。

## 前輪 M3-P2：已有限接受並版本封存，實際驗收邊界

使用者已明確要求開始產品輪並持續推進 [ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)。本輪由已驗收的 M3-P1 版本建立獨立 worktree／branch，接手、roster／有界 discovery 與核定 M3-P2 的 26 個程式檔、必要記憶體／磁碟／HTTP／兩市場桌面與 390px 操作已有限接受，支援 M3／R2-C1 股數保存基線及必要 R0 migration／readiness 依賴。程式 26 檔已 freeze，7 個文件已依接受結論更新；本輪 33 個核准檔依統籌 review、aggregate freeze→輪末索引→commit→merge 版本封存，實際最終收據與接手以原 task 為準。角色配置依 [AGENTS「四個角色」](../AGENTS.md#四個角色)，三個 subagent 均由本輪統籌在其 session 以 `fork_turns=none` 新建；canonical 名稱相同不代表沿用舊角色。各角色不自行結案或啟動下一任務。

前輪「M3-P1 既有可信庫存股數→精確張／零股／原股呈現與失精輸入拒收」的九個程式檔、必要記憶體／實際 HTTP／前端驗證及具名桌面／390px 庫存操作已有限接受並版本封存；支援 M3／R2-C1 的既有庫存單位基線，採現有 Float 的可信安全整數、精確字串相容表示及 commit 前拒收，不是完整 M3 或精確大數存儲。主契約與具名支持範圍集中見 [UI 文案 §10.3](UI_COPY_SPEC.md#m3-p1-既有庫存股數的有限呈現契約)，正常估值／決策／計畫不改。QA tab／兩個自有程序與 listener 已核實關閉或不存在，新增測試產物／殘留為 0，測試與清理 exit 0 分報；前輪實際參數與必要檢查失敗的版本封存邊界見下方。

前次「M1／R1-A2 成交量 HTTP→JavaScript→個股精確呈現」的 15 個核定程式檔、必要記憶體／HTTP／完整字串邊界複驗與 TWSE／TPEx 具名操作已有限接受；20 個核准檔已 freeze、更新五個索引分區、本地提交 `40ec36c2933ba96887893b6ad7f683280bdfe4b6`（parent `b608710c301ed26321289d0851aba89e31ebb46b`），並由統籌確認 fast-forward 合併至乾淨 `master`。M3-P1 接手 HEAD 即該已驗收版本，最終 commit／merge receipt 留原 task。該輪新增測試產物／殘留為 0，自有 tab／程序／listener 已核實關閉或不存在；兩個 serve 的 exit 1 與測試 exit 0 分報，不增加完整 M1 完成度。精確支持範圍集中見[個股頁 §14](STOCK_RESEARCH_PAGE.md#14-m1r1-a2成交量-httpjavascript個股精確呈現)，fixture 不外推真官方／live 或正式 DB。

更早「R1-A2 legacy 成交量 gate→capture／collect／SQLite／reopen／API 精確保存與拒收保留」的七個核准檔案已有限接受、freeze、索引、本地提交並合併至 `master`。有效證據為 1 compound unittest／0 skip、兩次 force collect／60 個 HTTP 回應，test／cleanup／process exit 均為 0、核定測試根已核實不存在、產品來源 diff 為 0。兩市場合法整數／拒收與磁碟重開／HTTP token 的精確支持範圍見[資料來源](DATA_SOURCES.md#r1-a2-legacy-成交量磁碟整合)，入口副作用與配額見[開發入口](development-baseline/README.md#r1-a2-legacy-成交量的磁碟整合驗證入口)；首次直接 `& .ps1` 的載入前 policy 失敗留原 task，不稱首個命令通過。

更早 legacy 成交量 parser gate、selected invalid／拒收磁碟整合及 migration 均保留原有限接受與提交／合併邊界，仍對應目前來源的有效證據不因換 session 重跑；詳見[資料來源](DATA_SOURCES.md)及[開發入口](development-baseline/README.md)。M1-P4a 有界來源與程式唯讀審查已接受，TWSE exact 單日法人來源仍未准入，`local_fetch`／`raw_store`／`summarize` 權利仍 unknown，未取得法人原件、未核定 consumer 或產品接線，既有 pins／抓取範圍不變；缺證與恢復條件集中見[來源 §12](SOURCE_REGISTRY.md#12-m1-p4atwse-單日法人有界審查與准入缺口)。完整 5／20 日窗口、研究條件、M2／M3 與 PIT 保留原驗收範圍。

共同 repo／worktree：`C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-m3-share-quantity-storage-20261003`；branch：`roadmap-m3-share-quantity-storage-20261003`；起始 HEAD：`deaf2d4965d32e14e81338b69dfb2dd5ec773230`，與最新已驗收且乾淨的 `master` 相同。獨立 worktree／branch 已先建立；統籌已獨立核實四角色實際 runtime cwd、branch、起始 HEAD、model／reasoning、三子角色 parent、乾淨接手及互斥白名單，啟動 gate 已通過。

Orca 可見性已核實：本輪原 terminal `term_44630ded-dccc-47c0-a79d-5257df220480`，tab `34de190f-30c8-405a-b60f-6b3809a411a5`／pane 1，已核得 `connected`、`writable` 及 `nonorphaned`。統籌從該原可見 terminal 的 `/subagents` 核對 Main／root 與三角色，四個 ID 與下表一致；可見性及配置由實際 terminal、runtime 與 Git 核實。

本輪 pinned 共用 helper 首次實際 exit 1，因 terminal handle 等待逾時，逾時前未送任務；原 terminal 恢復後沿用同一 session，沒有重複啟動。外部啟動收據與本輪統籌獨立讀取 runtime 均核得唯一 UTF-8 任務可讀，共 12,310 字元，SHA-256 `5709ab3fa070e26b260903f1885edbbe9638e99f6e63320d296c21725d314cc7`；turn ID `01a1025d-6a39-7d71-832e-e93259f66230` 的 `inProgress` 由外部收據核實。本輪統籌另獨立核實 runtime、Git 及原 terminal 可見性。附帶 default shell 已由外部收據核實關閉、`ptyKilled=true`，不能把恢復後接手倒寫成 helper 首跑通過。

| 角色 | 本輪 ID／實際配置與接手 | 寫入／驗收範圍 |
| --- | --- | --- |
| 統籌 | canonical ID `/root`；session `01a10250-3fa0-7752-8399-d678bf3714d8`；實際 `gpt-6.1-sol`／`ultra`；已核實並接手 | 已核定 M3-P2 契約、26 檔實作／7 檔文件與必要配額，接受有限程式／磁碟／HTTP／產品操作並 freeze 程式 26 檔；33 檔依統籌 review 後 aggregate freeze、輪末索引、複核後分別明授 commit／本地 merge。已接手並完成前輪指定外部清理，殘留分報如下。 |
| 程式 | canonical ID `/root/implementation`；子 thread `01a1025e-ede7-73d2-a19c-c2dffb43df17`；實際 `gpt-6.1-sol`／`xhigh`；已核實並接手 | 初始讀寫白名單為空；有界唯讀 discovery 已核定後，寫入限 26 檔：`backend/app/` 的 `models.py`、`units.py`、`api.py`、`migrations.py`、`database_readiness.py`、`instrument_identity_migration.py`、`settlement_identity_migration.py`、新增 `portfolio_share_migration.py`；`backend/alembic/env.py`、新增 `backend/alembic/versions/0008_portfolio_share_integer.py`；`frontend/src/` 的 `App.tsx`、`types.ts`、`units.ts`、`units.test.ts`；`backend/tests/` 的 `test_units.py`、`test_share_quantity_exact_presentation.py`、`test_schema.py`、`test_database_readiness.py`、`test_turnover_availability_migration.py`、`test_instrument_identity_migration.py`、新增 `test_share_quantity_storage.py`、`test_turnover_availability_file_migration.py`、`test_settlement_identity_migration.py`、`test_news_json_defaults.py`、`test_tpex_corporate_action_mapping.py`；`tools/share-quantity-exact-preview.cjs`。追加四個測試檔只作必要 head 一致性：保留 0006 fixture／0007 availability 的歷史範圍，改新 HEAD 8 與 through 8 斷言；settlement 的 REVISIONS 尾端加 8；news JSON defaults 只改 CURRENT_HEAD 0008，歷史 OLD／NEW fixture 不變；TPEx corporate action mapping 只改 fresh upgrade／head assertion 0008。既有磁碟矩陣未重跑，不稱本輪重新驗收舊功能。必要記憶體／磁碟／HTTP／具名操作已接受，26 檔已由統籌核 freeze；無後續來源寫入授權。不自改規格、文件、來源 gate、索引或 Git，交付後等統籌。 |
| 文件 | canonical ID `/root/documentation`；子 thread `01a1025f-377c-7921-bfe3-6bca385c9879`；實際 `gpt-6.1-sol`／`xhigh`；已核實並接手 | 白名單限 `docs/TASK_COORDINATION.md`、`docs/UI_COPY_SPEC.md`、`docs/ROADMAP.md`、`docs/ROADMAP_EXECUTION.md`、`docs/development-baseline/README.md`、`docs/R0_IMPLEMENTATION.md`，另加 `docs/OPERATIONS.md` 只供 current head／chain 與新有限保存契約連結的必要一致性補正。7 檔已依統籌接受的實作／驗證更新最終契約、成果與交接；隨 33 個核准檔依統籌 review 後 aggregate freeze 與版本封存。不改程式、其他文件、AGENTS、索引或 Git。 |
| 索引與 Git commit | canonical ID `/root/index_commit`；子 thread `01a1025f-9021-7522-aa92-058fe3c432fa`；實際 `gpt-6-luna`／`medium`；已核實並接手 | 來源寫入白名單為空；freeze 後才統一更新涉及分區及驗 coverage，commit／本地 merge 各待統籌明確授權。不輪初／中途刷新，不 push 或重寫歷史。 |

上述實際 model／reasoning 均由統籌獨立讀取 UTF-8 runtime `session_meta`／`turn_context` 核實，三個子 thread 的 parent 均為本輪統籌。各子角色 `CODEX_THREAD_ID` 為自身子 thread ID，runtime `session_id` 才是 root；不能把繼承環境值或 Rpc 的 root `sessionId` 當成子角色 ID。舊 session 的實際參數保留 Git／原 task 及下方既有紀錄，不因本輪配置倒改。

本輪文件增補總量上限 **32 KiB**，文件附件／暫存與新增測試產物配額均為 **0**；文件只驗差異、UTF-8 讀回、連結及一致性，不跑 backend 或建 DB。輪初 App codebase-memory list／index_status verbose／coverage 成功：master docs 索引 ready、HEAD 與本輪起始 HEAD 相同，無 recorded parse／skip gap；當時本輪 worktree 尚未 tracking，master 的 `TASK_COORDINATION.md` 為 `no_recorded_issue`／`metadata_changed`，scope 只列被設計排除的 `.codebase-memory`，因此原文補核。沒有輪初刷新；待本輪來源及文件接受並 freeze 後才由索引角色統一更新涉及分區、驗 coverage。連線、索引、coverage 與功能驗收分報，實際收據留 task。

本輪有限接受的核心為保留 Float 相容欄、另存 SQLite int64、一次可信 legacy backfill、四種互斥數字／精確字串輸入，以及 UI 全字串保存／呈現／拒收保留。完整 current 契約只由 [UI 文案 §10.3](UI_COPY_SPEC.md#m3-p2-可信整數保存與磁碟重開契約)負責；必要 0008／八枚 markers、普通 nullable INTEGER 與 atomic rollback 規則由 [R0 §8.11](R0_IMPLEMENTATION.md#811-m3-p2持倉精確整數-migrationreadiness有限接受)負責；入口、副作用與驗收限制由[開發入口](development-baseline/README.md#m3-p2-可信整數保存與磁碟重開驗證入口)負責。Unsafe legacy 保留 NULL／原 Float、不還原捨入原值，正常有限金融計算不改，大數金融估值不宣稱 exact 或完整驗收；external Connection 共用接線只由 source 核對，本輪沒有重新驗收該入口。

必要記憶體證據：5 direct tests／0 skip／193 actual router requests，五次預期 audit 阻擋／`unexpected_denials=[]`、exit 0；首個 storage 合併 suite 為 13 tests／12 pass／1 重複 audit probe skip，由 direct 0 skip 覆蓋，不稱全 pass／0 skip。Fixture 修正後另 9 個 storage memory tests exit 0；正常來源未改的 memory／前端不因 disk runner 修正重跑。Node 20.19.4／TypeScript 5.9.3 的 full src noEmit、units／14 組 Portfolio SSR／whole main 記憶體 bundle exit 0，已知 warnings 分報；舊磁碟矩陣與完整 backend／production Vite build 未跑。

核定唯一磁碟根 `C:/Users/YiCheng/AppData/Local/Temp/taiwan-stock-m3-share-storage-01a10250`，ancestor／根均核 non-reparse；最多 **2 files**（`data/quantity.db`、`data/quantity.db-journal`）、**3 directories**（root、`data`、`raw`）、總 **2 MiB**、DB **1 MiB**、殘留同 cap，禁止 WAL、pycache、一般附件與 `KeepArtifacts`。Runner review 後已明授 disk：首次 `--disk` 實際 exit 1／test 1／cleanup 1，Alembic normal 保存與重開內部 assert 已通過，但 native SQLite context 未 close，finally 出 WinError32，留下 **1 file／3 directories／417,792 bytes**，其餘三案例未完成；兩處改 `contextlib.closing` 後先 `--cleanup` exit 0並核根不存在。第二次 exit 1／test 1／cleanup 0，fallback fixture 混 marker，stale Alembic 0007 被正確拒絕；清理後根不存在。Fixture 修後第三次實際 exit 0／test 0／cleanup 0，1 compound unittest／0 skip、四個 sequential cases 全過：Alembic 0007→0008 normal／fault 各 **417,792 bytes**，fallback-only prefix 1..7→1..8 normal／fault 各 **425,984 bytes**；peak **1 file／3 directories／425,984 bytes**、`unexpected_denials=[]`／根不存在。前兩失敗均是 runner／fixture，不改原 exit 或冒稱首次通過，也不是 automatic review 拒絕；資源釋放與 fixture 修正未改產品。

產品證據：`--prepare` exit 0；首個 actual `app.main`／lifespan／readonly readiness 程序 PID 45208，以及 actual fetch／Response.json 的 75 個 get／upsert／delete HTTP exit 0，數字相容、四字串表示與 422 完整列保留已驗。實際桌面 `1365×900` 的 TWSE NEW ODD／TPEx NEW MAX 均 POST 200、完整原股數／993 或 807 餘股正確；首程序 shutdown 最終 exit 0／audit 空、PID／listener 不存在。Closed `--inspect` exit 0 證 ODD／MAX 的 SQLite typeof INTEGER、unsafe legacy NULL；DB **417,792 bytes**、SHA-256 `3acdd767f0c58a5323eb1f0a793edcaa1ad96cf88f0e43c64622c053291e9a24`。第二程序 PID 4740 開同一檔，actual lifespan 通過；GET 200 的兩列完整 NEW JSON（含 updated_at）與關閉前相同，390px reload 的完整數字正確。原生 MAX+1 股／超限張數不送 POST（`2→2`）、完整兩列不變；最大合法張數保存 200、exact `9223372036854775000`／零股 0。14 卡／28 數量元素 client／scroll width 均 273、document 均 375、editor 305，未觀測溢出；兩列原生 DELETE 200，再 GET 200／items 空／cards 0。

本次 UI 擷取範圍 32 requests（27 GET／3 POST／2 DELETE）均為自有 8780、status 200、外網空；reload 後 16 performance resources 均同 origin，不作完整 session log。Console 7 entries 為 3 React DevTools info／4 已知 Router future warnings，無 error，不稱空 console。Orca 首 capture／goto 的 runtime_unavailable、hidden 頁面未生效的 first click、blank viewport 都不算通過；沿同原 tab 恢復、focus 後的 actual 保存與正確 post-navigation viewport 才接受。PS5 Invoke-RestMethod 首次中文 mojibake 不作文字核實，actual browser fetch UTF-8 正確；live Get-FileHash 占用失敗不宣通過，只有 closed inspect 的 SHA 已取得。

本輪測試與清理分報：QA viewport 已還原 `1365×900`、tab `da9c1ec0-e225-4adc-82a2-1c106e0889c7` 已關閉；先核 exact command 後，第二 API 4740／Node 43304 與 esbuild child 49160 自有 shutdown 的兩 exec 最終 exit 0，API `unexpected_denials=[]`。Closed `--inspect` exit 0 只剩原 12 rows，unsafe NULL、zero／safe INTEGER，DB **417,792 bytes**／SHA-256 `cdb47b620ec1667fdc103731f61775c43d17e56c7ee6d1a781812b99e6df5bea`；final `--cleanup` 實際 exit 0／test 0／cleanup 0／retain false。統籌另獨立核 exact 根不存在、owned PIDs（45208／4740／43304／49160）與 Node children／8779、8780 listeners 空、本輪 Orca tabs 空；隔離 DB 產物／殘留為 0，不宣稱下方 HAR 已清。

**額外 HAR 例外**：統籌漏核 capture stop 的自動落盤，tool 回 `C:/Users/YiCheng/.agent-browser/tmp/har/har-1791044803009.har`／requestCount 24；actual exact file 為 non-reparse／Archive、parents 普通 directories，**1 file／64,885 bytes**，超過原附件配額 0。Exact 單檔 `Remove-Item` 整個 exec 在 CreateProcess 前遭 automatic review 拒絕（`blocked by policy`），未執行；不重試／換工具、不掃 shared HAR dir、不刪 parent、不複製其他成果或造 manifest。統籌已明確承認此副作用；隔離 DB 已清，但本輪 HAR 殘留尚在，待外部變化／使用者處置，不把它交下一輪當正常 owned cleanup 重試。既有殘留已達上限，停止新增測試落盤，不藉新 session 重置配額；有效產品證據仍有限接受，其餘有界零輸出工作繼續。

**完成及驗收邊界 → 尚缺項 → 下一步與依賴／完成條件 → freeze／索引／commit／merge**：核定 26 個程式檔及上述必要證據／具名產品操作已接受，統籌核 freeze SHA 與程式交付一致、UTF-8／LF／單 EOF newline／trailing whitespace／Python AST 與白名單外來源空，HEAD 仍為起始 `deaf2d4965d32e14e81338b69dfb2dd5ec773230` → 7 文件已依接受結論更新，本輪 33 個核准檔依統籌 review、aggregate freeze→索引→commit→merge 版本封存，實際最終收據與接手見原 task；HAR 仍在，不外推正式 DB／migration／production deployment、真官方／live、大數金融估值、新 Plan、完整 backend／Vite production build、完整 M3、歷史／availability／PIT 或原來源 gate → 下一具名候選既有庫存成本／停損／風險輸入可信檢核與拒收保留，合併後交新統籌先 memory／唯讀核來源、所有 caller、Float 相容、副作用／資料與完成條件，不固定修法、不沿用 fixture／ports 或重置殘留限制；必要 disk 先核既有殘留與授權處理 → 文件接受後才 aggregate freeze、輪末索引，複核後各別明授 commit／本地 merge，最終 receipt 留 task，不為回寫 hash 反覆更新文件。PRODUCT_SPEC、來源／tick／risk sizing／new Plan／source pins 與穩定 PIT gates 未變，不製造 diff。

輪末索引核定範圍（只於文件接受／aggregate freeze 後執行，實際結果依原 task）：只建本輪 prefix `taiwan-stock-research-roadmap-m3-share-quantity-storage-20261003-` 的 **6 partitions**（backend-app、backend-tests、backend-alembic、frontend-src、tools、docs），`persistence=false`，原八分區不改。Six DB 合計最多 **64 MiB**，tool-returned logs 最多 **6 files／8 KiB**，必要已知 aux 最多 **12 files／8 MiB**，不新增目錄或 `.codebase-memory`；只 native 核 exact owned DB／known aux／tool-returned logs，不掃其他 cache。這是必要 index 的獨立配額，不是測試落盤，也不解除 HAR 殘留／零附件限制；索引成功不當功能驗收。

### 前輪 M3-P1 的實際參數與版本封存邊界

共同 worktree／branch 為 `roadmap-m3-share-quantity-exact-presentation-20261003`，起始 HEAD `40ec36c2933ba96887893b6ad7f683280bdfe4b6`；原 terminal `term_f77477d5-6a3c-49c9-b86f-bd174e906473`，tab `eaa811e6-6717-4927-b5a3-66317350ac36`／pane 1。該輪統籌 `/root`、session `01a101f4-61f7-78e2-aa11-1aae57db5b65` 實際 `gpt-6.1-sol`／`ultra`；程式 `/root/implementation`、`01a101f5-f5c8-7e30-970c-ed7725a928cd` 與文件 `/root/documentation`、`01a101f6-4255-7f31-8b2b-1d1245e96777` 均實際 `gpt-6.1-sol`／`xhigh`；索引 `/root/index_commit`、`01a101f6-8dee-7980-990e-fb88af1e987a` 實際 `gpt-6-luna`／`medium`。這些已核實參數保留原值，不沿用為本輪角色。

該輪九個程式檔、5 direct tests／0 skip／145 actual router HTTP requests、必要前端型別／units／14 組 Portfolio SSR／記憶體 bundle、51 個 product fetch HTTP，以及主契約具名兩市場桌面／390px 操作已有限接受；測試及清理各 exit 0，QA 還原／tab 關閉、自有程序／listener 不存在、新增測試產物／殘留 0 已獨立核實。首跑非有限拒收的 error JSON 修正後才通過，原始失敗與工具點擊／refs 限制留 task，不稱首跑或未生效操作通過。ORM Float 只支持目前可信值 `0..SAFE`、寫入只 `1..SAFE`；純 int／ASCII 字串顯示支持 int64 MAX 另證，不代表 ODD／MAX DB 保存，記憶體 commit／refresh／GET 不等磁碟重開。正式 DB、真官方／live、估值、新計畫、完整 backend／production build、完整 M3、歷史／availability／PIT 與原 M1／M2 gate 保留。

該輪程式、必要證據、產品操作與五文件已接受，14 檔初次 freeze／索引後提交 `b953bcdd78c210680039f71b005f635ff95fe05f`（parent `40ec36c2933ba96887893b6ad7f683280bdfe4b6`）。首個 `git diff --check` 未涵蓋當時 untracked 的新 preview；stage 後 `git diff --cached --check` 在該檔第 316 行的 EOF 多餘空行回 exit 1，索引角色仍作首個提交，統籌當時未接受合併，不把首次 cached check 當通過。必要退修只刪 preview 最後一個 LF byte（18,332→18,331 bytes），保留單個 final newline；Node 20.19.4 `--check` 與相對首提交的 tool diff check 均 exit 0，UTF-8／LF／單個 final newline 已核，未改行為或其他凍結來源，未重跑 Python／HTTP／UI／完整 Node 驗證或新增產物。preview 與本文件補正已接受、重新 freeze、更新 tools／docs 索引並完成正常 follow-up commit `deaf2d4965d32e14e81338b69dfb2dd5ec773230`；統籌已確認 fast-forward 合併至乾淨 `master`，最終 receipt 留原 task，不為回寫 hash 追加刷新或提交。

本輪統籌已完成 M3-P1 的指定外部清理，與功能／合併驗收分報：先以 actual Rpc 逐四 ID 核 latest completed，再關閉原 terminal，exit 0、`ptyKilled=true`；另逐四 ID 核 latest completed 後 archive 舊 root，回 `true`，統籌再獨立 Rpc 逐四路徑核得 `archived_sessions`／`notLoaded`／`loaded=false`／latest completed，cascade 已核實。移除前已獨立核 exact worktree 為 non-reparse、**210 files／14 directories／3,583,704 bytes**、乾淨 HEAD `deaf2d4965d32e14e81338b69dfb2dd5ec773230`、為已合併 master 的 ancestor，以及四 ID latest completed；Orca 移除 exit 0、`removed=true`，另核根不存在、Git worktree／branch 無該輪、Orca selector 為 `selector_not_found`。本輪 storage worktree 仍存在且正在實作，沒有清理本輪來源。

M3-P1 的五個 unique aliases 已刪除，統籌獨立 App list 核只剩原八分區；exact cache DB 及 WAL／SHM／journal 均不存在，共 **34,996,224 bytes** 已除。三個 returned logs 合計 **1,139 bytes** 仍存在，統籌另核 Archive 屬性：第一個 **295 bytes** 的 `Remove-Item` 整個 exec 在 CreateProcess 前遭 automatic review 拒絕（`blocked by policy`），未執行且不重試／換工具；另兩個各 **422 bytes** 尚未嘗試。exact paths／receipt 留原 task，保留歷史、不另建附件；這些 logs 尚未清，不把 session／worktree／索引清理推論成全部資源清零。較早 **1,173 bytes** 的 logs、下方 M1 被拒 worktree 與其他空根／舊殘留未動、不重試或換工具繞過，不等待這些清理才推進產品。

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
