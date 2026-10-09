# GitHub 工作手冊

權責與驗收見 [AGENTS](../AGENTS.md)，產品方向見 [ROADMAP](ROADMAP.md)。本文定義操作與設定，實際配置及導入缺口見[遷移入口](TASK_COORDINATION.md)。

## 欄位與唯一來源

| 資訊 | 唯一位置 | 維護者／用法 |
| --- | --- | --- |
| 產品承諾與能力邊界 | ROADMAP 與負責規格 | 保存持久的操作、公式及驗收契約；核定版本範圍不代表功能已完成。 |
| 版本任務集合 | GitHub milestone | 全局統籌將核定版本的必要工作逐項納入；milestone 引用治理 Issue 的版本化 AC／來源對應收據，不另外在 repo 建版本任務表。 |
| 任務識別 | GitHub Issue URL／`owner/repo#number` | 沿用 GitHub 識別，不另外編一套本機 task ID；跨 repository 使用完整連結。 |
| 目標、範圍、AC、來源版本、決策、驗收收據 | Issue 本文與留言 | 全局統籌管理；任務統籌依補單規則建單、維護；AC 用 AC-1 等穩定編號，改動保留修訂及理由。 |
| 母子關係 | GitHub 原生 parent／sub-issue | 全局統籌；純容器母單不開工作區。 |
| 阻擋關係 | GitHub 原生 blocked-by／blocking | 全局統籌；可跨母單，與 parent 分開，派工前查循環與可用版本。 |
| 執行進度 | Project 的 Status、依賴與 Priority 視圖 | Status 使用待辦、開發中、測試中、待整合、完成；依賴引用上列唯一關係，任務統籌依轉移 gate 更新。版本範圍以 milestone 篩選，不用全部 Project 卡片計完成率。 |
| 優先級 | Project 的 Priority 單選 | P0 阻止現行核心使用／整合，P1 近期核心，P2 後續核心，P3 候選／改善；全局統籌排序。 |
| 工作種類 | Project 的 Kind 單選 | 功能母單、執行任務、候選；小功能選執行任務，不強造母單。 |
| 可開工 | Project 的 Ready 單選 | 是／否；全局統籌核依賴證據後設是。候選、容器、阻塞、暫停為否。 |
| 阻塞與暫停 | Project 的 Blocked、Paused 單選 | 各為是／否；原因、決策者、解除條件、原階段、檢查事件／時間留原 Issue。 |
| 當前 owner／下一角色 | Issue 最新交接留言 | 記 session 及版本，接收者確認；assignee 是可接收通知的 GitHub 帳號，不假裝每個 agent 都有獨立帳號。 |
| 整合排隊與持有者 | 一張治理 Issue 的最新整合收據 | 全局統籌唯一更新；列有序候選及最多一個持有者，不另建本機鎖表。 |
| 同時開發上限、全局停滯計數 | 同一治理 Issue | 初始上限 1；按批次驗收順序更新計數，產品母單連結該次收據。 |
| Repo／Project／整合入口 URL | 本文連結的遷移入口 | 設定完成後只留穩定入口；不抄即時狀態或 roster。 |

若 GitHub 實例不支援原生關係，在 Issue 本文固定「母單／子單」及「Blocked by／Blocking」兩欄使用完整連結，由全局統籌維護雙向一致；不得同時維護兩套權威關係。只有權限／功能確認後才選 fallback。新標籤不是 Ready 或 Status 的第二份副本。

建議視圖：產品母單排序、Ready 待辦、進行中（含阻塞）、待整合、候選。Project 以 Issue 為卡，PR 連回 Issue。WIP 依 [AGENTS](../AGENTS.md#建立任務與派工)計算與釋放；未裝自動化不聲稱系統強制上限。

## 版本範圍與完成判定

正式產品派工（含試跑）前，全局統籌須完整盤點 V1 流程、能力與編號 AC，將既有契約、必要依賴、後版候選及未決範圍交使用者核定，再去重補齊必要工作；核定前不得稱清單完整。近期拆至可獨立驗收，遠期保留功能概述，不逐段造單或重開已驗能力。

[治理 #1](https://github.com/YiCheng0608/stock-lab/issues/1)保存版本化 AC 與 coverage 收據，由 milestone 引用：「來源章節／完整版本 → 能力／AC → 已整合證據、既有 Issue、待補缺口或核定後版／不做決策」。來源規格仍為產品契約，不在 repo 複製即時矩陣。**盤點缺口為 0** 指每項 AC 均有具名 Issue、適用已驗證據或使用者核定的排除決策；不代表功能、依賴或發布 gate 通過。後版決策須列明排除的來源 AC；待核、unknown、缺證據仍算缺口。

milestone 是唯一版本任務集合，Project 可以保留未來版本或候選 Issue。母單橫跨版本時，先辨識 V1 必要 AC，必要時拆對應子單，不把整張跨版本母單丟進 V1；每個子單的 milestone 須逐項核對，不推定繼承母單。取消／重複結案不算已接受能力，原來的必要 AC 仍須映射到承接 Issue 或有效證據。

新增必要前置／缺陷由全局統籌列受阻的既定 AC、版本及依賴影響，記決策後納入 V1；新能力、市場、策略或降低 AC 須使用者核定，pending 不默認接受。後版想法不延長 V1，建單不增加 WIP 或解除暫停。必要來源缺失且無新取得路徑時，保留原階段並記阻塞／解除條件，不以 unknown 替代來源交付。

進度以已驗能力、剩餘 AC、未解除依賴及發布 gate 回報；能力數不得重複計母子單、PR 或維護工作，Issue closed 比例不能定義完成。全局統籌須在已整合 master 確認全部 V1 必要 AC 通過、必要執行單完成、完整端到端流程（含磁碟保存及跨程序讀回）受獨立 QA 驗證、required CI／文件齊全、阻擋缺陷為 0，才寫發布驗收收據並關 milestone。未來待辦及跨版本母單可保持 open；部署另需授權。

## 待辦涵蓋與補單

全局統籌以 PRODUCT_SPEC、ROADMAP、V1_SPEC、ROADMAP_EXECUTION 及文件索引所指的現行契約，對照 open／closed Issues、PR、已整合及未合併成果，依[版本基線](#版本範圍與完成判定)補齊對應。寬泛母單標題、程式存在或 closed 狀態不證 AC 通過；archive branch 按能力／版本去重，已驗證據須適用於本版的標的、來源、操作及程式版本。逐契約核對完成前不宣稱遷移完成。

| 時機 | 責任與動作 |
| --- | --- |
| 初次建立版本基線 | 依上節核定範圍、去重補單及 coverage；完成後才允許正式產品派工。 |
| 每日第一次開始工作／恢復全局統籌 | 先讀暫停／交接及治理決策，再核新增／變動需求、Ready 任務、依賴與名額；有缺口才補單，不為日期換新而造單。這不是排程，未授權時不建立定時 worker。 |
| 可開工待辦不足以補滿已核定名額 | 全局統籌細化下一個近期子能力、查可實際解除的依賴；沒有可行工作就回報阻塞／待決，不硬標 Ready。 |
| 任務驗收或母單整體驗收 | 全局統籌核剩餘 AC、實際新能力、下一個依賴與未覆蓋契約，必要時補單；原 AC 失敗留原單退修。 |
| 規格、ROADMAP 或產品決策改變 | 全局統籌更新來源對應、去重並調整既有單或建新單；保存 AC 修訂與重新驗證範圍。 |
| 執行中發現獨立前置／無關 bug／新想法 | 發現者立即回報原單，不等任務結束；任務統籌查 open／closed Issues 與未合併成果去重，再建關聯前置／候選，附來源、證據與阻擋方向，交全局統籌排序、核版本範圍、Ready／派工。原 AC 失敗仍在原單退修，不能自行追加 worker。 |

全局統籌依 [WIP 規則](../AGENTS.md#建立任務與派工)按空位補派；補單本身不授權執行。

## 任務識別與程式索引

Issue ID 識別任務，commit SHA 識別版本，codebase-memory 查來源及相依關係。純管理／派工不要求建索引，索引不保存任務狀態。

1. 查程式前先 `list_projects`，再核所選 project 的 `index_status(verbose=true)`、`root_path`、Git context 及目標路徑 coverage。確認 root 確實位於本任務 worktree 的指定分區；名稱含 Issue 編號或 branch 不足以證明指向正確。
2. 任務統籌在原 Issue 指定索引／Git 角色負責刷新。同一 worktree／分區的角色共用一份索引；只有缺適用索引時才建必要分區，不為每個角色或新 Issue 複製整庫。不同 worktree 需要索引時使用不同 project 名稱，例如 `<repo>-<worktree-key>-<scope>`；worktree-key 綁唯一絕對根路徑，建立前查同名占用，不能把別人的 project 改綁本根。維持共用 runtime／cache，不另複製 cache。
3. 主線或另一 worktree 的現成索引可供基線探索，但不得當作本候選的 coverage／完成證據。對照 base→candidate 及未提交差異後，受影響路徑以本任務原檔確認；索引缺口、解析不足或 stale 不妨礙此 fallback，也不代表 GitHub 任務找不到。
4. 最終 freeze 後只刷新受影響分區，記 project、絕對 root／scope、branch、被索引的候選 SHA 或凍結內容依據、generation、coverage 與刷新者。`index_status` 當下的 Git HEAD 不是 generation 當時內容版本的證明；刷新前後核來源未變，未提交內容需記凍結路徑及內容雜湊於原 Issue，不另存 manifest。
5. 後續 commit 若只改 HEAD 而凍結檔案內容完全相同，可將該 generation 關聯最終 SHA；來源、scope 或 worktree 變動則重新核受影響索引。`metadata_changed` 等限制如實保留並讀原檔，不反覆全庫刷新或宣稱完整 coverage。任務索引不直接升格為正式 master 索引；合併後由整合入口的索引負責者核正式 root／合併版本並刷新受影響分區。

## 執行資源與服務版本

任務統籌在啟動測試服務前登記 UI／API／auditor 的預計埠、測試資料／輸出目錄及各資源 owner；全局統籌在原 Issue 或治理 Issue 的派工收據核跨任務衝突。同機埠及共用可寫資料不受 worktree 隔離。埠已占用時先核 owner，不搶占、不終止別人的程序；用已核定替代埠，不能隔離者排成順序驗證。

QA 與合併後檢查都須核：

- 被測 API／UI／auditor 的 PID、啟動時間、啟動命令、實際來源 worktree、埠及 UI proxy 的 upstream；不只看 cwd 或網址能開。QA 讀回實際頁面／API 對應的服務。
- 程式載入／bundle 建立時的 candidate SHA、來源範圍與必要內容雜湊、設定及資料版本。入口已有版本 receipt 時使用並核對；沒有時，從凍結來源的啟動／建置收據與實際 PID、bundle 雜湊建立對應，不虛構服務回報了 Git SHA。純文件或不啟動服務的測試列不適用及理由。
- code／設定修改、重啟、重新 bundle 或 upstream 改變後，重核服務對應與受影響驗證。沿用其他任務服務須其 owner 同意、用途授權及載入來源與本候選相關範圍相符的證據；只有 Git 工作樹乾淨、port、package version 或位元組長度都不足。
- 若無法證明正在執行的版本，該項列未驗；在既有授權內重建／啟動正確服務，或記阻塞取得必要條件。不得藉重啟重取已用完 quota 的來源、恢復已釋放原件或繞過 NO-RETRY。無法重取的資料須先安排 QA 可用的合法生命週期與保留範圍。

現有 chips API／preview 預設埠為 8799／8800，preview 的 `--api-port` 預設 8799，而且 bundle 在啟動時建立；換 UI 埠不會自動切換 API，commit 也不會更新已啟動 bundle。可用既有 `--port`／`--api-port` 指定核定埠，仍須讀回實際服務；入口見 [API](../tools/tpex-chips-series-api.py)、[preview](../tools/tpex-chips-series-preview.cjs)。本規則不要求所有測試另建環境；已有隔離目錄的入口沿用其契約。

## Projects 與關單自動化

導入時逐項核對並記設定收據：

- Status 只保留五個約定值；阻塞與暫停使用獨立欄位。
- 關閉會把 PR merged／Issue closed 直接轉 Done 的 automation，以及 Status Done 自動 close Issue 的 workflow；取消／重複單不能被轉成成功完成。
- PR 本文及 commit 不使用 `Closes`、`Fixes`、`Resolves` 加 Issue 編號的關單語法，使用 `Refs #<number>`；人工也不提前關單。
- 任務統籌確認合併後檢查通過後才手動關 Issue、更新 Status；若其中一步失敗，記已完成動作與待同步欄位，重試前讀回，避免重複操作。
- 依核准權限配置 master 的 PR review／必要 checks、禁止直接推送／強推／刪除及可寫入主線的整合者；必要 checks 依變更類型選定，不杜撰尚不存在的 CI。設定未驗證就記未設，不能把程序規則說成技術保護。

GitHub 支援自動關單關鍵字，Projects 也有關閉／合併時改狀態的內建 automation，故必須核對這些設定：[連結 PR 與 Issue](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue)、[Projects 內建自動化](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-built-in-automations)。

## GitHub CI 與本機 review／QA

[CI workflow](../.github/workflows/ci.yml) 在往 master 的 PR 建立／更新及 master push 時執行。使用標準 GitHub-hosted Ubuntu runner、唯讀 repository 權限，不取得行情、私人資料、正式 DB 或部署憑證，不啟用付費 Copilot。Actions 的工具安裝、依賴與 build 只在一次性 runner 工作區；不上傳測試產物或另建持久 cache。

| 檢查 | 範圍與限制 |
| --- | --- |
| `repository` | 每個 PR／master push 檢查差異空白、變更檔案 UTF-8、Python 語法、JSON／YAML 語法、Markdown 相對檔案連結；Python 變更另跑 Ruff 的 E9／F63／F7／F82。外部網址、標題 anchor 與文件語意仍由 review 核對；不為既有風格差異批量重排產品程式。 |
| `backend` | backend／工具／CI 或驗證依賴異動時，使用既有 chips API 的五個 `--check` profiles，驗記憶體 fixture、計算及 API 邊界；guard 禁來源 GET、DB 與檔案寫入。不等於完整 backend suite、真實來源或磁碟驗收。 |
| `frontend` | frontend／backend／工具／CI 異動時，以 pnpm frozen lock 安裝，跑既有 units、search、routes、presentation、stockChart 五個 standalone 回歸模組及 TypeScript／Vite production build。不等於可信瀏覽器操作或所有專用 guarded frontend 測試。 |
| `required` | 固定名稱的彙整檢查，永遠核對變更分類與所有適用工作的結果；只有不適用的工作可 skipped。失敗、取消、未執行或分類失敗均不得放行。 |

master ruleset 要求來源為 GitHub Actions 的 `required` check，並要求 PR 與最新 base 一致；檢查必須在實際首次成功後配置並讀回，不能把 YAML 存在當作技術保護已啟用。Workflow 本身不使用 paths-ignore，避免必要檢查整體消失；文件-only 的變更仍執行 repository／required，省略產品測試。合併後 master CI 失敗，依 AGENTS 暫停整合並回原 Issue 處理。

CI 不取代本機獨立 review／QA：review 查邏輯、差異與規格；QA 依原 AC 驗指定版本及真實操作。可用既有獨立 session，意見由任務統籌處理；不啟用付費雲端 AI reviewer。

CI 是初始回歸範圍，新增功能的涵蓋檢查依[流程檢查與滾動調整](#流程檢查與滾動調整)辦理。外部來源、磁碟、跨程序及可信 UI 仍按本機 gate 授權，不能為 CI 而縮減原 AC。CI 設定或 helper 變更會重跑兩個產品檢查工作；前端依賴與後端驗證版本清單各觸發其所屬檢查，backend 來源變更亦驗前端契約。

### PR CI 失敗與接手

任務統籌須核適用 run 的完成結果，或取得下一具名 owner 的 ACK；離線／中斷前記 owner、重新檢查事件／時間與接手確認，未接手如實記缺口，背景命令或未回讀通知不算交接。Git 角色在原 Issue 記 run URL、attempt、job／step、原 error／exit、base／head 完整 SHA 及實際 test SHA；任務統籌核最新 required 對應目前候選／base，指定下一角色。

- 產品程式、測試或 CI helper 有問題：回開發中，在原 branch 修正，保留原失敗收據；自測／review 後由獨立 QA 重驗受影響 AC，再交文件、索引／Git、freeze，回待整合，在原 PR 推核准候選並重跑適用 CI。不能刪測試、skip 適用工作或改 expected 只為湊綠；驗收語意變更按範圍決策 gate 處理。
- 有證據的 runner／network 暫態失敗：可對同一 base／head SHA 重試一次，保存兩次 run／attempt。再次失敗即記 Blocked=是，保留原階段、owner、原 exit、解除條件及重新檢查事件／時間；外部條件改變後由任務統籌記新證據再核重試，不無限重跑。沒有暫態證據或程式版本已變就不能套用此重試。
- cancelled 或 stale head 的 run 不直接當產品 bug，也不能作通過證據；最新候選的 required 缺失、未完成或不成功都不得合併。master 變動後重新核 base／candidate、差異、適用 QA 及 CI，舊核准不自動延續。
- 合併前失敗：核正式 master 未寫入後，全局統籌釋放整合入口並重排；WIP 另依掛起／停寫規則處理。合併後 master 失敗依 [AGENTS](../AGENTS.md#合併與-git-結案)保留待整合、停止其他整合並回原單修正／重驗。

這些是工作事件及明確 owner 的交接，不建立背景自動喚醒、定時監看或未授權重跑。

## 流程檢查與滾動調整

全局統籌負責追蹤、排序及調整決策；任務統籌在原 Issue 收觀察與版本化證據，各角色依下表檢查。[治理 #1](https://github.com/YiCheng0608/stock-lab/issues/1)只留待接手項目、決策及原 Issue 證據連結。未任命產品全局統籌時保持「待接手／待 ACK」；流程維護統籌可登錄觀察，不能代填 owner 或恢復產品。新任／恢復的全局統籌讀清單並回覆實際 session、接受項目及下次檢查事件後，才算接手。

每次在原 Issue 記負責 owner／session、觸發、版本／證據、處置與下次事件，再由全局統籌連回治理 #1。清單勾選不免除後續檢查；日期更換、補單或改文件不解除暫停，也不授權每日排程。

| 檢查項目 | 負責角色 | 觸發事件 | 必備證據 | 處置 |
| --- | --- | --- | --- | --- |
| CI 回歸涵蓋 | 工程師提案例、QA 核原 AC；任務統籌收據，全局統籌決定跨任務政策 | 功能 PR 建立／更新，或 AC、CI 入口改變 | 原 AC、PR／候選 SHA、案例與缺口、CI run／結果、本機驗收項 | 同 PR 擴充可穩定重建案例，由 QA review；沿用[現有 runner／本機 QA](#github-ci-與本機-reviewqa)，無法自動化者保留本機 gate，不縮減 AC。 |
| 拆單粒度 | 任務統籌回報範圍／隱藏依賴，全局統籌決策 | 首張完整產品任務驗收後；派工前發現無法獨立驗收 | 原 AC、實作／驗收範圍、隱藏依賴及無法獨立驗收的操作 | 下次派工前決定拆分、補前置或維持，保留原 AC 及承接關係。 |
| 角色與槽位 | 任務統籌核階段／寫入權，全局統籌排容量 | 角色啟動、恢復、交接或容量不足／變動 | 實際 session／模型／reasoning／cwd／branch／HEAD、白名單、原 owner 停寫與 ACK、QA 與實作者不同 session | 依[角色規則](../AGENTS.md#六種角色)按階段啟動、空閒停寫，容量不足時順序交接。 |
| 交接冗餘與缺漏 | 任務統籌／文件檢查，全局統籌決定欄位調整 | 首張完整試跑後；交接重複／缺漏；採用調整後的交接 | 原交接／ACK、缺失的版本／責任及重複欄位例證 | 刪重複，保留 owner、AC 修訂、完整 SHA、停寫與 ACK；治理決策連回模板差異，不另建附件。 |
| 並行資源 | 全局統籌與兩位任務統籌 | WIP 1 → 2 前；跨任務資源改變或恢復 | 共用檔案／白名單、UI／API／auditor 埠、可寫資料／輸出路徑、服務版本、索引 root／scope／版本、整合入口 owner 及隔離證據 | 隔離不足安排順序驗證，缺口未處置不開第二張；master 整合一次一張。不同 worktree 不證隔離。 |
| 測試產物上限與歷史文件 | 任務統籌核定、QA 核執行；文件核歷史連結，全局統籌排候選 | 落盤測試前；修改相關歷史文件時 | 核定數量／大小、絕對路徑、授權、建立／清理方式與殘留；連結目標／失效證據 | 依[資料／暫存規則](../AGENTS.md#驗證資料與暫存)沿用有界入口，實際不足才提工具改善。歷史連結觸及時處理；既有問題沿用候選 [#27](https://github.com/YiCheng0608/stock-lab/issues/27)，不納 V1。 |

一般改善可明確延後；只有影響既定 AC、安全、啟動送達或並行隔離者阻擋對應動作。原 AC 失敗回原單退修；獨立改善由全局統籌去重、列候選及排序，不自動納 V1 或取得派工授權。

首次完整產品任務須驗派工、Orca 可見工作區／session、工程實作／自測、獨立 QA、文件、freeze、索引／coverage、Git 候選 commit、經授權推送／PR／CI、串行整合、master 必要檢查、關單與名額釋放，逐階段核 owner、版本及接手證據。流程維護 PR／CI 成功或本機 mock 回歸不算這次產品試跑。未實際發生的啟動失敗、退修、阻塞、CI 異常及 owner 中斷以桌上走讀核處置並標「非實測」，不刻意破壞產品或啟動資源。完整單任務通過並完成 WIP 2 准入後，才實際驗兩任務的交接與串行整合；不在 WIP 1 或產品暫停時先跑並行實驗。

## 模板入口

- [產品功能母單](../.github/ISSUE_TEMPLATE/feature.md)：功能及整體 AC，不自動派工。
- [執行任務](../.github/ISSUE_TEMPLATE/task.md)：子單或獨立小功能，派工前完成全部必要欄位。
- [候選 bug／想法](../.github/ISSUE_TEMPLATE/candidate.md)：先分流；違反當前任務 AC 的問題仍回原單退修。
- [PR](../.github/pull_request_template.md)：指定版本、證據、整合授權及合併後檢查；不自動關單。

以下文字直接貼原 Issue 留言，不另建交接附件。每次填實值、完整 SHA 和可定位證據，未驗寫未驗，不以空白勾選當通過。

### 範圍基線與補單

```text
事件：初次基線／需求變更／執行發現／驗收補單；版本／milestone：
使用者範圍核定／尚待決事項及收據：
來源文件、章節、完整 SHA／規格版本：
能力／版本化 AC：
對應 Issue／適用的已整合 SHA 與驗收證據／待補缺口：
後版或不做決策／核准者／保留的原 AC：
跨版本母子單與各子單 milestone 核對／取消重複的 AC 承接：
必要前置或缺陷支持的既定 AC／影響／納入決策：
coverage 盤點缺口數及原因（不表示功能完成）：
剩餘 AC／未解除依賴／發布 gate／下一步：
暫停與 owner 核對／正式派工 gate 是否滿足：
```

### CI 失敗收據

```text
Issue／PR／run URL／attempt／完成時間或接手 owner ACK：
job／step／原始 error／exit／證據：
base SHA／head SHA／實際 test SHA／最新 required 結果：
分類：source／test／helper／有證暫態／cancelled／stale head：
原階段／退修或 Blocked／owner／下一角色及動作：
同 SHA 暫態重試次數／重試 run／解除條件與重新檢查事件：
修正候選／受影響 QA／文件／索引／freeze／同 PR CI：
master 是否寫入／整合入口釋放與重排或停止其他整合／WIP 處理：
```

### 派工與接手

新任務分兩次留收據：全局統籌先記派工／建立授權，session 填「待建立」、接手填「待確認」；建好後核 Orca 註冊路徑、branch、起始 SHA、可見 terminal 及實際 runtime。終端就緒才傳 UTF-8 任務，背景 API 成功不證可見送達。接收者讀回 Issue、版本、白名單並再核派工授權／名額有效，確認後才轉開發中、派工程師。啟動中維持待辦並占 WIP；恢復先核原 session ID，不重建或代填。

送達未知時保留名額。釋放須確認未送達且無可執行 session，或已撤權並核已建 session 停寫；逾時／ACK 遺失不足以釋放或重派。

建立前保留精確 worktree 的唯讀 terminal／session 基線，基線不完整就不建立。`terminal create` 逾時、非 JSON 或錯誤不證未建立；只在原 worktree 唯讀對帳 handle／session、可見及可執行狀態，無法唯一確認就記 unknown／候選與限制。不重複 `create`、不終止其他 session，也不因候選出現而取得 ownership。未呼叫 `turn/start` 記 `not sent`；已呼叫但回覆不明記送達未證。兩者皆依上段核 WIP，不憑 `not sent` 釋放。失敗收據須含原錯誤、對帳證據、handle／session（含未知）、是否送出、殘留及下一 owner／動作。

本機啟動工具的 mock 回歸在 repo root 執行 `python -B -X utf8 tools/test_coordinator_startup.py --helper C:/Users/YiCheng/.local/bin/codex-session-control.py`，明示核定的實際 helper；指定路徑不可讀即失敗，未選外部 helper 的自動探索不執行該 suite。測試隔離外部呼叫，不建立真實 terminal／產品服務、不存取來源或 DB，也不落盤測試產物；原 Issue 記 helper 雜湊、命令與結果。Repo 保存可重建測試，不部署該共用本機 helper；雲端 CI 通過不證本機 helper 已安裝、版本相符或真實啟動已實測，後者仍依正式派工與可見接手收據核驗。

```text
事件：派工與建立授權／交接／接手確認；時間：
Issue／AC 修訂：
活動名額：預留／啟動中／已接手／失敗保留或釋放（送達、授權與停寫證據）：
目前核心缺口／新增操作／必要依賴與可用證據：
交付者 → 接收者角色／session：
下一動作／完成條件：
repo／worktree／branch／base SHA／candidate SHA：
Orca terminal handle／實際 session／模型／reasoning／cwd 核對：
寫入白名單／共用檔案協調／原 owner 停寫：
執行資源：UI／API／auditor 埠、資料／輸出目錄、owner／衝突排程（不適用理由）：
程式索引：既有 project／絕對 root／scope／版本依據／刷新者或無適用索引的處理：
資料與測試授權／產物數量大小／建立及清理方法：
既有驗收／失敗／未驗／不可重建證據位置：
freeze／索引與 coverage／commit／PR／merge：
全局停滯收據／計數：
接收者讀回版本並確認／未接手原因：
```

### QA 與退修

```text
事件：QA 結果；QA session（不同於工程師）：
Issue／原始 AC 修訂／candidate 完整 SHA／工作樹乾淨：
服務身分：PID／啟動時間／命令／來源 worktree／埠／實際 proxy upstream（不適用理由）：
載入版本：啟動或建置來源 SHA／內容與 bundle 雜湊／設定版本／實際服務核對證據：
跨任務服務沿用：owner 同意／授權／版本適用證據，或不沿用：
資料版本／日期／市場標的／用途／授權：
AC-1：通過／退回／未驗；操作或命令；版本／原 exit；證據：
AC-2：通過／退回／未驗；實際與預期；復現：
真實數值／API／可信 UI／磁碟跨程序：適用項與證據，不適用理由：
沿用證據與差異分析／未驗與限制：
產物／清理結果／殘留路徑大小與原因：
結論：通過或退回（必要 AC 未驗不能通過）
下一角色／動作／版本／接手確認：
```

### 阻塞與決策

```text
Issue／原階段／Blocked 或 Paused：
原因／阻擋 Issue／實際證據：
決策者／需決定事項／影響：
解除條件／重新檢查事件或時間：
下一角色／動作：
AC 是否變更／核准者與修訂／需重驗項：
```

### 整合與結案

```text
事件：排隊／取得整合權／合併／檢查／釋放整合權
Issue／PR／整合執行者／使用者授權收據／開始時間：
正式 remote／master base SHA／candidate SHA：
最新 master 合入任務 branch／衝突處理者／差異與 QA：
文件 freeze／索引 project、絕對 root／scope、branch、內容版本依據、generation／coverage 限制／刷新者：
核准者／核准 SHA／合併前 base 再核：
合併後 master SHA／必要檢查命令、原 exit、證據：
合併後被測服務版本收據／正式 root 的受影響索引核對：
新增能力／實際解除依賴／可靠性改善／剩餘缺口：
全局停滯計數前後／下一步理由：
Issue 關閉與 Project 狀態同步：
清理另行授權／執行或未執行／殘留：
整合權釋放／失敗時暫停及接管安排：
```

## 導入順序與驗收

1. **本機流程改造**：讀 AGENTS、ROADMAP、Git 狀態及模型配置；保留既有修改。完成規則、模板、歷史狀態交接與文件一致性，存本機流程 branch／commit。這不算產品試跑。
2. **GitHub 設定**：確認 repository／Project 所屬、可見性、現有帳號及登入授權，先唯讀盤點現有 Issues／PR／Project。取得外部寫入、必要 repo 設定的授權後，配置欄位、關係、治理 Issue 及整合入口，核對 automation／權限。不得把內含本機路徑或 session 資訊的歷史 repo 未經檢查發布到公開 repository。
3. **版本基線與狀態遷移**：依[版本範圍](#版本範圍與完成判定)及[補單規則](#待辦涵蓋與補單)完成核定、去重、coverage 及 milestone 對應後，才進產品試跑。舊「已 review」須核正式主線、原證據及缺口，不能直接換 Done；舊暫停／NO-RETRY／私人資料保護保持，無新授權不恢復。
4. **停滯與 owner 交接**：核最近兩個實作批次及 Git／原 task，確認全局計數，不因流程改造歸零。GitHub 明確指定新 owner；舊 session 不再有自動接續權，不必為遷移關閉／刪除它們。將實際 Repo／Project／治理 Issue URL 回寫遷移入口後，不再於 repo 更新任務狀態。
5. **單任務試跑**：選依賴可用、有實際能力增量的近期 Issue，依[完整試跑契約](#流程檢查與滾動調整)驗各階段，完成後檢查拆單粒度及交接欄位。
6. **開放最多兩張**：全局統籌確認完整試跑沒有 owner、版本、狀態同步或權限缺口，再與兩位任務統籌完成[並行資源檢查](#流程檢查與滾動調整)，在治理 Issue 記證據並調 WIP 1 → 2。隔離不足者先排順序驗證；未完成准入就維持 1，不先跑兩任務實驗，不自動部署或清理。

授權可一次明確涵蓋指定 repo／branch／任務範圍，記錄後沿用；「同意流程」本身不等於同意登入、推送、PR、合併、部署或刪除。要詢問時先備妥確切對象、版本、檔案及預計動作，讓使用者核准具體結果。
