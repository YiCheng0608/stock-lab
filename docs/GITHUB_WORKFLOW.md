# GitHub 工作手冊

[AGENTS](../AGENTS.md)管權責與驗收，[ROADMAP](ROADMAP.md)管產品方向。本文管操作、欄位、模板；配置與缺口見[遷移入口](TASK_COORDINATION.md)。

## 欄位與唯一來源

| 資訊 | 唯一位置 | 維護者／用法 |
| --- | --- | --- |
| 產品承諾與能力邊界 | ROADMAP／負責規格 | 操作、公式、驗收契約；核定範圍不證完成。 |
| 版本任務集合 | GitHub milestone | 全局納入必要工作，引用治理 Issue 的版本化 AC／來源收據；repo 不另建表。 |
| 任務識別 | Issue URL／`owner/repo#number` | 不另編 task ID；跨 repo 用完整連結。 |
| 目標、範圍、AC、來源版本、決策、收據 | Issue 本文／留言 | 全局管理、任務統籌依補單規則維護；穩定 AC 編號，改動留修訂／理由。 |
| 母子關係 | 原生 parent／sub-issue | 全局；純容器不建工作區。 |
| 阻擋關係 | 原生 blocked-by／blocking | 全局；與 parent 分開，可跨母單，派工前核循環及可用版本。 |
| 執行進度 | Project Status／依賴／Priority 視圖 | 五階段依 AGENTS gate 轉移；版本按 milestone 篩選，不用全部卡片算完成率。 |
| 優先級 | Project Priority | P0 阻現行核心／整合、P1 近期核心、P2 後續核心、P3 候選／改善；全局排序。 |
| 工作種類 | Project Kind | 功能母單／執行任務／候選；小功能可獨立成單。 |
| 可開工 | Project Ready | 全局核真正前置、授權及驗證方案後設是；本單交付／QA 留後驗。候選、容器、阻塞、暫停為否。 |
| 阻塞／暫停 | Project Blocked／Paused | 是／否；原單列原因、決策者、解除條件、原階段、重查事件／時間。 |
| owner／下一角色 | Issue 最新交接 | session、版本、ACK；assignee 是通知帳號，不冒每 agent 獨立帳號。 |
| 整合排隊／持有者 | 治理 Issue 本文摘要；收據在留言 | 全局唯一更新，有序候選、最多一位持有者，不建本機鎖表。 |
| WIP／停滯計數 | 同一治理 Issue 本文摘要；收據在留言 | 上限／實占／空位／處置，規則依 [AGENTS](../AGENTS.md#建立任務與派工)。停滯按批次驗收順序，母單連收據。 |
| Repo／Project／整合入口 URL | 遷移入口 | 只留穩定入口，不抄即時 roster／狀態。 |

原生關係確定不支援時才用 Issue「母單／子單」及「Blocked by／Blocking」完整連結，全局核雙向一致；不維護兩套權威關係或以 label 複製 Ready／Status。

建議視圖：產品母單、Ready 待辦、進行中、待整合、已暫停、候選。進行中含 Paused=否的阻塞單，已暫停為 Paused=是；卡片／回報顯示 Status／Blocked／Paused。卡片用 Issue、PR 回原單；未設自動化不稱技術強制 WIP。

## 版本範圍與完成判定

正式派工（含試跑）前，全局盤點 V1 流程、能力、編號 AC、必要依賴、後版候選及未決範圍，交使用者核定後去重補單。近期拆至可獨立驗收，遠期保留功能概述，不逐段造單或重開已驗能力。

[治理 #1](https://github.com/YiCheng0608/stock-lab/issues/1)留版本化 AC／coverage，由 milestone 引用「來源章節／完整版本 → 能力／AC → 已整合證據、既有 Issue、缺口或核定後版／不做決策」。來源規格仍是契約，不複製 repo 即時矩陣。盤點缺口 0 只代表每項 AC 有具名單、適用已驗證據或使用者核定排除；不證功能／依賴／發布通過。排除須列原 AC，待核／unknown／缺證據仍算缺口；未逐項完成不稱清單完整。

milestone 是唯一版本集合。跨版母單按 V1 必要 AC 拆子單，不整張納入；逐子核 milestone，不推定繼承。Project 可留後版／候選；取消／重複不算能力，必要 AC 須映射承接單或有效證據。

既定 AC 的必要前置／缺陷由全局列受阻 AC、版本、依賴影響並決定納入 V1；新能力或降 AC 依 [AGENTS](../AGENTS.md#疑問阻塞與範圍變更)由使用者核定。後版想法不延長 V1，建單不占 WIP／解除暫停。缺來源且無新路徑時保留階段、記阻塞／解除條件，不用 unknown 代交付。

進度報已驗能力、剩餘 AC、未解除依賴、發布 gate，不重複計母子／PR／維護或按 closed 比例算完成。發布條件見 [ROADMAP V1-G7](ROADMAP.md#v1-範圍基線2026-10-09-已核定邊界)；後版／跨版母單可 open。

## 待辦涵蓋與補單

以 PRODUCT_SPEC、ROADMAP、V1_SPEC、文件索引所指現行契約（ROADMAP_EXECUTION 只作歷史 R0–R3 拆解對照），對照 open／closed Issues、PR、已整合／未合併成果，依[版本基線](#版本範圍與完成判定)去重補缺。母單標題、程式存在、closed 不證 AC；archive 按能力／版本去重，證據須適用本版標的、來源、操作、程式。逐契約核完才稱遷移完成。

| 時機 | 責任與動作 |
| --- | --- |
| 初次基線 | 核定範圍、去重、coverage 完成才派產品。 |
| 每日開始／恢復全局 | 先核暫停、owner 交接、治理決策，再查需求／Ready／依賴／空位，有缺口才補單；不因日期造單或未授權建定時 worker。 |
| 空位而 Ready 不足；任務進 QA／退修／阻塞／掛起 | 立即查其他 Ready、拆獨立近期子能力／必要前置；保留母 AC，缺可行方案則列缺口、owner、下一步，不硬標 Ready 或等前單結案。 |
| 任務／母單驗收 | 核剩餘 AC、新能力、依賴、未覆蓋契約，必要時補單；原 AC 失敗原單退修。 |
| 規格／ROADMAP／決策變更 | 更新來源對應，去重調單／補單，留 AC 修訂及重驗範圍。 |
| 發現獨立前置／無關 bug／想法 | 立即回原單；任務統籌查 open／closed、未合併成果去重，建關聯前置／候選、附來源／證據／阻擋方向，全局核範圍／優先級／Ready／派工。不得自行加 worker 或把原 AC 失敗拆走。 |

### 平行派工與補位

WIP、ACK、session 分別是已派 Issue、接手確認、角色資源。[AGENTS](../AGENTS.md#建立任務與派工)的上限及補派規則適用。等待只約束該單及真正依賴，共用檔案／服務／整合排程只約束相關操作；補單本身不授權開工。

治理收據記「上限／實占／空位 → Ready／必要前置 → 隔離／角色安排 → 派工或阻擋／解除事件」。Project 連現行規則、治理單，舊限制明示歷史。規則未整合時全局交版本化決策／差異給受影響 owner 讀回，不改被測樹或把管理候選當產品 base。

### 資料與功能拆線

| 線 | 開工前置 | 交付證據 |
| --- | --- | --- |
| 資料線：取得、准入、樣本交付 | 合法可執行方案；不要求先有下游 UI | 適用標的／日期／欄位／品質、資料版本、保存位置與生命週期、一個最小正向讀用 |
| 功能線：計算、API、UI | 穩定資料契約：欄位、型別、單位、日期語意、缺值與錯誤 | fixture／RAM 的本地技術證據；不冒真來源 |
| 整合線：真資料 → 下游 → 獨立 QA | 兩線交付版本覆蓋本單用途 | 具名操作、跨程序保存或可信 UI 的實際結果 |

- 資料線與功能線互不為開工前置；整合線依兩者實際交付版本。依賴按用途、標的、日期、欄位核實，Done 不證可用，禁止循環。
- 至少維持一條「真實取得 → 樣本交付 → 最小下游 → 獨立 QA」完整路徑，其他無依賴工作照常並行。
- Ready 不足時依序查既有來源單、未合併成果、可獨立子能力，最後才補必要前置。同一資料契約已有只差真資料的功能單時，先推資料線與整合線，不再開同契約的新功能單。
- 後版暫停項不當 V1 解鎖條件。進度只按可讀用資料、跨程序保存或具名操作計；流程文件、測試數不算核心增量。

## 任務識別與程式索引

Issue ID 管任務、SHA 管版本、codebase-memory 查來源／相依；純管理／派工不要求建索引，索引不存狀態。

1. 先 `list_projects`，再核 `index_status(verbose=true)`、root、Git context、目標 coverage；root 須屬本 worktree 指定分區，名稱不作證據。
2. 任務統籌指定索引／Git 刷新者。同 worktree／分區共用一索引，缺適用索引才建必要分區，不逐角色／Issue 複製。跨 worktree 用不同 project 名（如 `<repo>-<worktree-key>-<scope>`），key 綁唯一絕對 root；先查同名占用，不改綁他人 project，共用 runtime／cache。
3. 他 worktree／主線索引只供探索，不證本候選 coverage。核 base→candidate／未提交差異後，以本任務原檔查受影響處；缺口、解析不足、stale 可 fallback，不代表找不到任務。
4. final freeze 只刷受影響分區，原 Issue 記 project、絕對 root／scope、branch、候選 SHA 或內容 hash、generation、coverage、刷新者。當下 HEAD 不證 generation 內容；刷新前後核來源未變，未提交 freeze 記路徑／hash，不另存 manifest。
5. commit 只換 HEAD、內容相同可綁 generation 至最終 SHA；來源／scope／worktree 變則重核。metadata_changed 如實報、讀原檔，不反覆全庫刷或稱完整 coverage。合併後入口索引 owner 核正式 root／版本、刷受影響分區，不將任務索引直接升格 master。

## 執行資源與服務版本

開服務前登記 UI／API／auditor 埠、資料／輸出目錄、owner；全局核跨任務衝突。worktree 不隔離同機埠／共用可寫資料；占用先查 owner，不搶埠或殺他人程序，改用核定埠或順序驗證。

QA／合併後檢查須核：
- PID、啟動時間／命令、來源 worktree、埠、UI proxy upstream，以及實際頁面／API 對應，不只看 cwd／URL。
- 載入／建置 candidate SHA、來源範圍／必要 hash、設定／資料版本。核既有 receipt；無 receipt 則以 freeze 啟動／建置、PID、bundle hash 建映射，不冒服務回報 SHA。純文件／不開服務列不適用理由。
- code／設定／重啟／bundle／upstream 改動須重核對應及受影響項。跨任務沿用須 owner 同意、用途授權、相關載入來源一致；clean／port／package version／長度不足。
- 無法證版本列未驗，在授權內建正確服務或記阻塞。不得重啟重取 SPENT、恢復已釋原件或繞 NO-RETRY；不可重取資料先安排合法 QA 生命周期／保留範圍。

QA 用核定埠並讀回；chips-series API／preview 預設埠與 `--port`／`--api-port` 見[開發入口](development-baseline/README.md#m1-chips-stock-scope-7-daily-net-trend-20-1006-1-七股每日淨超的零落盤驗證入口)。不要求逐測試新建環境，隔離入口沿原契約。

## 角色 provider 與啟動參數

角色對應見 [AGENTS](../AGENTS.md#六種角色)。全局在派工收據記 provider；切換或恢復沿[派工與接手](#派工與接手)，讀回實際值才算接手。

| provider | 啟動 | 恢復 |
| --- | --- | --- |
| Codex | 統籌：`codex-session-control.py start-coordinator`；其他角色：Orca 可見 terminal、目標 worktree 啟動，模型與 reasoning 依角色表 | 原 session `--remote … resume <ID>` |
| Claude | Orca 可見 terminal、目標 worktree：`claude --model <完整 ID> --effort <level>` | `claude --resume <ID> --effort <level>`，讀回模型／effort，不同則記錄並由全局處置 |

- 只用完整模型 ID（如 `claude-opus-5-5`）。無效 ID（如 `opus-5.5`）啟動不擋，首次請求才被拒，故收據須含已完成的 turn。
- effort 只收 `low`／`medium`／`high`／`xhigh`／`max`。無效值只警告並改用預設，不讓啟動失敗。
- `--resume` 保留模型，effort 回預設，故恢復須帶原 `--effort`。
- 讀回：session 內 `CLAUDE_CODE_SESSION_ID`／`CLAUDE_EFFORT`；模型只以 transcript `~/.claude/projects/<cwd-key>/<ID>.jsonl` 的 assistant `model` 欄位核對，effort 亦可核 `effort` 欄位。模型自述、banner、命令列不作證據；讀不到記未驗。
- 從 Git Bash 用 `orca terminal send` 送 `/` 開頭指令須設 `MSYS_NO_PATHCONV=1`，否則被轉成路徑送出。

## Projects 與關單自動化

導入設定須讀回收據：
- Status 五值，Blocked／Paused 獨立欄位。
- 停用 PR merged／Issue closed → Done、Done → close Issue 的 automation；取消／重複不算成功。
- PR／commit 用 `Refs #<number>`，不用 `Closes`／`Fixes`／`Resolves` 關單，人工不提前關。
- 合併後檢查通過才由任務統籌關 Issue／更新 Status（無 repo 變更依 [AGENTS](../AGENTS.md#狀態與驗收責任)由測試中直接關單）；任一步失敗記已做／待同步，重試前讀回。
- 依授權配置 master review／適用 checks、禁止直推／強推／刪除、整合寫入者；未驗設定記未設，不冒技術保護或不存在的 CI。

配置參考：[PR 與 Issue](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue)、[Projects automation](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-built-in-automations)。

## GitHub CI 與本機 review／QA

[CI](../.github/workflows/ci.yml)於 master PR 建立／更新、master push 執行，GitHub-hosted Ubuntu／唯讀權限。行情、私人資料、正式 DB、部署憑證、付費 Copilot 不使用；安裝／build 限一次性 runner，不上傳產物或建持久 cache。

| 檢查 | 範圍與限制 |
| --- | --- |
| `repository` | 每 PR／master push 驗 diff 空白、變更檔 UTF-8、Python／JSON／YAML 語法、Markdown 相對檔案連結；Python 另驗 Ruff E9／F63／F7／F82。外部 URL／anchor／語意由 review 核，不批量改既有風格。 |
| `backend` | backend／工具／CI／驗證依賴變更：chips API 五個 `--check` profiles，RAM fixture／計算／API 邊界；guard 禁 GET／DB／寫檔。另跑 identity／news／product 三檔 pytest（tmp SQLite、測試設計不取源、無此 guard），[standalone-only 檔](development-baseline/README.md#不由-pytest-收集的-standalone-only-測試檔)不由 pytest 收集。不證完整 suite、真源、磁碟。 |
| `frontend` | frontend／backend／工具／CI 變更：pnpm frozen lock、units／search／routes／presentation／stockChart 五個 standalone 回歸、TypeScript／Vite build。不證可信瀏覽器或全部 guarded 測試。 |
| `required` | 固定彙整，永遠核分類及適用工作；僅不適用可 skipped，失敗／取消／未跑／分類失敗不放行。 |

master ruleset 要求 GitHub Actions `required` 及最新 base；設定以讀回為準，未讀回記未設，不以 YAML 存在冒設定。workflow 無 paths-ignore；文件-only 跑 repository／required，省產品測試。master CI 失敗按 AGENTS 停整合／原單退修。

CI 不替代本機獨立 review／QA：review 查邏輯／差異／規格，QA 按原 AC 驗版本／真操作；可用既有獨立 session，統籌處理意見，不啟付費雲端 AI reviewer。初始回歸涵蓋按[流程檢查](#流程檢查與滾動調整)擴充；真源／磁碟／跨程序／UI 沿本機 gate，不為 CI 縮 AC。CI／helper 變更跑兩產品工作；前端依賴／後端驗證清單各觸發所屬，backend 來源亦驗前端契約。

### PR CI 失敗與接手

任務統籌觀察適用 run 至完成或下一具名 owner ACK。離線／中斷留 owner、重查事件／時間、ACK；未接手記缺口，背景命令／未讀回通知不證交接。Git 在原單記 run URL、attempt、job／step、原 error／exit、base／head／實際 test 完整 SHA；統籌核最新 required 綁當前 base／candidate，指定下一角色。

- 程式／測試／helper 缺陷：回開發中，原 branch 修正、保留失敗；自測／review、獨立 QA、文件／索引／freeze 後回待整合，推同 PR 核准候選並重跑適用 CI。不刪測試、skip 適用工作、改 expected 湊綠；驗收語意依範圍決策。
- 有 runner／network 暫態證據：同 base／head 可重試一次、保存兩 run／attempt；再失敗 Blocked=是、保留階段／owner／原 exit／解除條件／重查事件。外部條件變更另記新證據再核重試；無暫態證據或版本變更不套重試。
- cancelled／stale head 不直接算 bug 或通過；最新 required 缺失／未完／不成功不合併。master 變則重核 base／candidate／差異／QA／CI。
- 合併前失敗，核 master 未寫後全局釋放入口重排，WIP 按掛起／停寫規則；合併後按[AGENTS](../AGENTS.md#合併與-git-結案)待整合／停其他整合／原單修正重驗。

上述以事件／owner 接手，不建背景喚醒、定時監看或未授權重跑。

## 失敗分流與有界重驗

| 分類 | 判定 | 處置與重驗 |
| --- | --- | --- |
| 本地產品缺陷 | 確定版本、可重建輸入下原 AC 失敗 | 原單退開發；修正、自測後獨立 QA 重驗受影響 AC。 |
| 測試工具／環境 | helper、依賴、埠、權限、編碼、hook 失敗，產品未被執行到 | 白名單內修工具／環境，或另開工具單；重跑同一案例，不判產品通過或失敗。 |
| 外部取源／授權 | 拒絕、配額、NO-RETRY、缺授權 | Blocked；保留原錯誤，不重取、不換 session／工具繞過；解阻 owner 備合法方案或列使用者決策。 |
| 驗收資料不足 | 樣本未覆蓋 AC 必要案例（窗口、公司行動、標的數） | 該 AC 標未驗，交資料線／[樣本庫](development-baseline/README.md#測試資料庫分層)補樣本；fixture 不冒通過。 |

- 未執行不等於來源不存在；保留原錯誤、exit、版本與 AC。可能已寫 DB 或送出請求的未知副作用先對帳，再分類。
- 每次重跑須列變更（程式、工具、環境、資料版本）；同版本同輸入不重跑。同一失敗連續兩輪修正無效，回任務統籌重新分類或拆單。
- 金融來源一次性配額只約束該來源操作，不概括套到本地可重建測試；原單已明示 STOP／NO-RETRY 的範圍以原文為準，重新分類由全局在原單記錄。

## 讀取、交接與證據成本

- 讀：按階段讀[文件索引](README.md)指定的必要文件；大檔用標題、搜尋、行範圍，不整檔讀。長 Issue 讀本文、最新交接及被引用留言，`gh` 用 `--json`／`--jq` 篩欄位；索引結果分頁。
- 傳：交接引用完整 SHA、檔案路徑、留言 URL，不重貼全文、source、Base64 或分段 manifest。大型證據留可重建腳本、hash 及授權位置的原件。
- 驗：hash／diff 以程式核對，只回摘要；首次必要 review 與版本變更才重驗。
- 角色：空閒角色停寫並結束不需要的 session；恢復讀最新交接，不載入完整歷史。
- 量測：Claude `--output-format json` 提供 input／cache／output token；其他 provider 依其 usage，取不到標未知。字元數只是代理指標，不估造費用；換模型或流程的成本比較須有前後量測，記在原 Issue。

<a id="導入順序與驗收"></a>
<a id="導入項目與驗收"></a>

## 流程檢查與滾動調整

全局追蹤／排序／決策，任務統籌原單收版本化證據，[治理 #1](https://github.com/YiCheng0608/stock-lab/issues/1)連待接手項、決策及原單證據。未任命全局時標待接手／ACK，流程維護角色不能代填 owner 或恢復產品；新任／恢復全局核實 session、接受項、下次事件才接手。

治理 #1 本文是即時摘要：WIP 上限／實占／空位、進行中的單與 owner、整合入口持有者、待使用者決策、停滯計數、現任全局 session／handle。全局每次事件更新本文，收據留在留言；兩者不一致時以收據為準並修正本文。接手者先讀本文，再依連結查收據。

全局例行換手：以下任一條件成立即換手——對話被自動壓縮一次、自任命起關閉 5 張單（任期內關閉的所有單，含流程單；取消／重複不算）、自任命收據時間起連續運作 2 小時、跨日（台灣時間）。全局更新 #1 本文並留交接，之後停止派工與決策，只保留啟動新全局：在管理 checkout 開 Orca 可見 terminal（不建 worktree；標題含「新全局」只作輔助，關閉與送訊息只認 handle），沿舊全局任命收據的 provider（未記則預設 Claude）與 [AGENTS 角色表](../AGENTS.md#六種角色)的模型／effort，依 [provider 表](#角色-provider-與啟動參數)啟動並送交接 prompt，依[派工與接手](#派工與接手)核送達與首個完成的 turn，在 #1 留啟動收據（舊全局 handle、新全局 handle、送達證據）；新全局任命收據出現後才完全停寫。建立失敗時依[派工與接手](#派工與接手)對帳，唯一確認未建出才重建，最多一次；送達失敗時對原 handle 讀回後補送一次（只補送出，如 `--retry-request` 或 Enter，不重貼全文），不新建。仍失敗，或舊全局失效無法自行啟動，依 [AGENTS](../AGENTS.md#疑問阻塞與範圍變更)記阻塞，下一動作固定為使用者入口通知使用者啟動；舊全局失效時由新全局在任命收據補記。等待期間不重新計算換手條件。從啟動到舊 terminal 關閉，舊全局不碰 repo 工作樹與 git 狀態，GitHub 只寫啟動收據與 #1 記錄。交接只放整理過的內容：#1 本文摘要的連結；未結事項（處理中的決策、已送出未回覆的通知、進行中的整合、已知風險），每項附原單連結；新全局的第一個動作。不轉貼歷史收據、對話或整串留言，細節由接手者依連結查。新的全局 session 讀本文接手，核管理 checkout 工作樹 clean（不 clean 則不清理、不覆寫，仍先留任命收據並記 #1 交原 owner），在 #1 留任命收據並更新本文的現任全局，依序：
1. 以 `orca terminal list` 的實際 worktree／handle 核對交接名單與本文 WIP 表的任務統籌 session／handle；不一致以實際讀回為準，修正本文並在收據記差異。
2. 核對舊全局已留交接、停寫且 terminal 閒置後，以 `orca terminal close --terminal <舊全局 handle>` 只關閉該 terminal（handle 取自更新本文前的值、啟動收據或舊任命收據；新舊全局同在管理 checkout，不用 `--tab`／`--worktree --all`），結果記在 #1，使送往舊 handle 的訊息直接失敗。
3. 通知進行中的任務統籌新的 session／handle。

每次原單記 owner／session、觸發、版本／證據、處置、下次事件，治理單連回。勾選不免後續檢查，日期／補單／文件不解除暫停或授權排程。

| 檢查項目 | 負責角色 | 觸發事件 | 必備證據 | 處置 |
| --- | --- | --- | --- | --- |
| CI 涵蓋 | 工程提案、QA 核 AC、統籌收據、全局跨任務決策 | PR／AC／CI 入口變更 | AC、SHA、案例／缺口、run／結果、本機項 | 同 PR 補可重建案例、QA review；沿[runner／本機 QA](#github-ci-與本機-reviewqa)，不縮 AC。 |
| 拆單 | 統籌回報、全局決策 | Ready 不足／阻塞／不可獨立驗／驗收後 | 原 AC、範圍、真正前置／獨立操作 | 當次拆分／補前置／維持，留原 AC 及承接，不等無關結案。 |
| 角色／槽位 | 統籌核階段及寫權、全局排資源 | 啟動／恢復／交接／容量變更 | actual session／模型／reasoning／cwd／branch／HEAD、白名單、停寫／ACK、QA 不同 session | 按[角色](../AGENTS.md#六種角色)分階段、空閒停寫；不足只順排受影響階段。 |
| 交接欄位 | 統籌／文件核、全局調整 | 重複缺漏／採用後 | 交接／ACK、版本責任缺漏／重複例證 | 刪重複，留 owner／AC 修訂／完整 SHA／停寫／ACK，治理連模板差異，不另附件。 |
| 並行資源 | 全局及參與統籌 | 派工／補派／恢復／資源變更 | Ready／前置、階段角色、共用白名單／埠／資料輸出／服務版本、索引 root／scope／版本、整合 owner／隔離 | 治理准入收據；缺口只阻受影響任務／操作，暫限列解除事件，其他獨立照常派。master 一次一張，worktree 不證隔離。 |
| 產物／歷史文件 | 統籌核量、QA 執行、文件核連結、全局排候選 | 落盤前／修改相關歷史 | 數量／大小／絕對路徑／授權／建立清理／殘留、連結失效證據 | 按[暫存規則](../AGENTS.md#驗證資料與暫存)，不足才提工具改善；觸及歷史連結時處理。 |

改善可延後；僅影響既定 AC、安全、啟動送達、並行隔離者阻對應動作。原 AC 失敗原單退修，獨立改善由全局去重／列候選／排序，不自納 V1 或授權派工。


## 模板入口

- [產品功能母單](../.github/ISSUE_TEMPLATE/feature.md)：功能及整體 AC，不自動派工。
- [執行任務](../.github/ISSUE_TEMPLATE/task.md)：子單或獨立小功能，派工前完成全部必要欄位。
- [候選 bug／想法](../.github/ISSUE_TEMPLATE/candidate.md)：先分流；違反當前任務 AC 的問題仍回原單退修。
- [PR](../.github/pull_request_template.md)：指定版本、證據、整合授權及合併後檢查；不自動關單。

模板直接貼原 Issue，不另建附件；填實值、完整 SHA、可定位證據，未驗明列，空白勾選不證通過。

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

新單先留派工／建立授權（session 待建立、接手待確認），再留 Orca 路徑／branch／起始 SHA／可見 terminal／actual runtime 收據。終端就緒才送 UTF-8；背景 API 不證可見送達。接收者核 Issue／版本／白名單／授權／名額，ACK 後才開發／派工程；啟動中待辦且占 WIP。恢復核原 session，不重建或代填。

送達未知保留名額；確定未送達且無可執行 session，或撤權且 session 停寫才釋放。逾時／ACK 遺失不釋放或重派。

角色之間以「原單留言＋Orca 短通知」聯繫：先在原單留收據或請求，再用 `orca terminal send` 對收件者的可見 terminal 送一則短通知，開頭標 `【#Issue 發送角色 → 收件角色】`，附發送者 session ID、terminal handle、留言連結與下一動作。適用於：
- 角色（工程、QA、文件、索引／Git）交回任務統籌；
- 任務統籌向全局請求處置，全局處置後回送任務統籌。

送出後讀回收件 terminal，核訊息已送出並開始新 turn；只有 accepted 依[送達未證規則](#派工與接手)記錄。

派工收據與任務 prompt 附全局 session ID、terminal handle 及上段聯絡格式；任務統籌的 ACK 附自己的 session ID、handle。全局現任 session／handle 以 #1 本文為準，與任命收據不一致時以收據為準；每次聯絡全局前都從 #1 本文讀取，不沿用記憶或舊收據的值，送出失敗先重查 #1，不改送其他 terminal（換手見[流程檢查](#流程檢查與滾動調整)）。通知是事件，不是定時監看；收件者讀回前不算接手；送進 terminal 的訊息不算使用者授權。

未證 ACK 只保留該單名額，其他已准入單可補位。退修依 [AGENTS](../AGENTS.md#狀態與驗收責任)原單交工程 ACK、獨立 QA，拖卡片／自動喚醒不證接手。

建立前核精確 worktree 的 terminal／session 唯讀基線，不完整就不建立。create 逾時／非 JSON／錯誤不證未建立，只在原 worktree 對帳 handle／session／可見／可執行；無法唯一確認列 unknown、候選、限制。不重複 create（全局換手依[流程檢查](#流程檢查與滾動調整)的一次重建例外）、殺其他 session 或據候選取得 ownership。未送記 `not sent`；結果不明或只有 accepted（如訊息停在輸入框未送出）、沒有 actual userMessage／turn 全文核對，記送達未證。兩者依上段算 WIP，not sent 不自動釋放。失敗留原錯誤、對帳、handle／session（含未知）、送出與否、殘留、下一 owner／動作。

本機 mock 在 repo root 執行 `python -B -X utf8 tools/test_coordinator_startup.py --helper C:/Users/YiCheng/.local/bin/codex-session-control.py`。須選核定實際 helper；不可讀即失敗，無外部 helper 的自動探索不跑 suite。隔離外部呼叫，不建真 terminal／服務、不取源／DB／落盤；原單記 helper hash／命令／結果。Repo 只存測試，不部署共用 helper；雲端 CI 不證本機安裝／版本／真啟動，仍核可見派工收據。

```text
事件：派工與建立授權／交接／接手確認；時間：
Issue／AC 修訂：
活動名額：預留／啟動中／已接手／失敗保留或釋放（送達、授權與停寫證據）：
目前核心缺口／新增操作／必要依賴與可用證據：
交付者 → 接收者角色／session：
全局 session ID／terminal handle／聯絡格式：
接收者（任務統籌）session ID／terminal handle（ACK 填）：
下一動作／完成條件：
repo／worktree／branch／base SHA／candidate SHA：
Orca terminal handle／provider／實際 session／模型／reasoning 或 effort 讀回／cwd 核對：
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
資料版本／樣本庫版本／日期／市場標的／用途／授權：
AC-1：通過／退回／未驗；操作或命令；版本／原 exit；證據：
AC-2：通過／退回／未驗；實際與預期；復現：
真實數值／API／可信 UI／磁碟跨程序：適用項與證據，不適用理由：
失敗分類（本地產品／工具環境／外部取源授權／資料不足）與本次變更：
沿用證據與差異分析／未驗與限制：
產物／清理結果／殘留路徑大小與原因：
結論：通過或退回（必要 AC 未驗不能通過）
下一角色／動作／版本／接手確認：
```

### 阻塞與決策

```text
Issue／原階段／Blocked 或 Paused／失敗分類／受影響 AC：
原因／阻擋 Issue／實際證據：
決策者／需決定事項／影響：
解除條件／重新檢查事件或時間：
解阻 owner／下一具名動作（替代路徑、外部等待條件或使用者範圍選項）：
AC 是否變更／核准者與修訂／需重驗項：
```

### 整合與結案

```text
事件：排隊／取得整合權／合併／檢查／釋放整合權
Issue／PR／整合執行者／授權依據（AGENTS 預設授權或使用者收據）／開始時間：
正式 remote／master base SHA／candidate SHA：
最新 master 合入任務 branch／衝突處理者／差異與 QA：
文件 freeze／索引 project、絕對 root／scope、branch、內容版本依據、generation／coverage 限制／刷新者：
核准者（持入口任務統籌；流程改造為全局）／核准 SHA（QA 通過版本）／合併前 base 再核：
合併後 master SHA／必要檢查命令、原 exit、證據：
合併後被測服務版本收據／正式 root 的受影響索引核對：
新增能力／實際解除依賴／可靠性改善／剩餘缺口：
全局停滯計數前後／下一步理由：
Issue 關閉與 Project 狀態同步：
結案清理（預設授權）或例外的授權依據／執行或未執行／殘留：
整合權釋放／失敗時暫停及接管安排：
```
