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
| 整合排隊／持有者 | 治理 Issue 最新整合收據 | 全局唯一更新，有序候選、最多一位持有者，不建本機鎖表。 |
| WIP／停滯計數 | 同一治理 Issue | 上限／實占／空位／補派處置；暫限列證據、範圍、解除事件，計算及釋放依[AGENTS](../AGENTS.md#建立任務與派工)。停滯按批次驗收順序，母單連收據。 |
| Repo／Project／整合入口 URL | 遷移入口 | 只留穩定入口，不抄即時 roster／狀態。 |

原生關係確定不支援時才用 Issue「母單／子單」及「Blocked by／Blocking」完整連結，全局核雙向一致；不維護兩套權威關係或以 label 複製 Ready／Status。

建議視圖：產品母單、Ready 待辦、進行中、待整合、已暫停、候選。進行中含 Paused=否的阻塞單，已暫停為 Paused=是；卡片／回報顯示 Status／Blocked／Paused。卡片用 Issue、PR 回原單；未設自動化不稱技術強制 WIP。

## 版本範圍與完成判定

正式派工（含試跑）前，全局盤點 V1 流程、能力、編號 AC、必要依賴、後版候選及未決範圍，交使用者核定後去重補單。近期拆至可獨立驗收，遠期保留功能概述，不逐段造單或重開已驗能力。

[治理 #1](https://github.com/YiCheng0608/stock-lab/issues/1)留版本化 AC／coverage，由 milestone 引用「來源章節／完整版本 → 能力／AC → 已整合證據、既有 Issue、缺口或核定後版／不做決策」。來源規格仍是契約，不複製 repo 即時矩陣。盤點缺口 0 只代表每項 AC 有具名單、適用已驗證據或使用者核定排除；不證功能／依賴／發布通過。排除須列原 AC，待核／unknown／缺證據仍算缺口；未逐項完成不稱清單完整。

milestone 是唯一版本集合。跨版母單按 V1 必要 AC 拆子單，不整張納入；逐子核 milestone，不推定繼承。Project 可留後版／候選；取消／重複不算能力，必要 AC 須映射承接單或有效證據。

既定 AC 的必要前置／缺陷由全局列受阻 AC、版本、依賴影響並決定納入 V1；新能力、市場、策略或降 AC 須使用者核定，pending 不接受。後版想法不延長 V1，建單不占 WIP／解除暫停。缺來源且無新路徑時保留階段、記阻塞／解除條件，不用 unknown 代交付。

進度報已驗能力、剩餘 AC、未解除依賴、發布 gate，不重複計母子／PR／維護或按 closed 比例算完成。已整合 master 的全部 V1 必要 AC、執行單、獨立 QA 端到端（含磁碟／跨程序）、required CI、文件齊全且阻擋缺陷 0，才由全局寫發布驗收、關 milestone。後版／跨版母單可 open；部署另授權。

## 待辦涵蓋與補單

以 PRODUCT_SPEC、ROADMAP、V1_SPEC、ROADMAP_EXECUTION、文件索引所指現行契約，對照 open／closed Issues、PR、已整合／未合併成果，依[版本基線](#版本範圍與完成判定)去重補缺。母單標題、程式存在、closed 不證 AC；archive 按能力／版本去重，證據須適用本版標的、來源、操作、程式。逐契約核完才稱遷移完成。

| 時機 | 責任與動作 |
| --- | --- |
| 初次基線 | 核定範圍、去重、coverage 完成才派產品。 |
| 每日開始／恢復全局 | 先核暫停、owner 交接、治理決策，再查需求／Ready／依賴／空位，有缺口才補單；不因日期造單或未授權建定時 worker。 |
| 空位而 Ready 不足；任務進 QA／退修／阻塞／掛起 | 立即查其他 Ready、拆獨立近期子能力／必要前置；保留母 AC，缺可行方案則列缺口、owner、下一步，不硬標 Ready 或等前單結案。 |
| 任務／母單驗收 | 核剩餘 AC、新能力、依賴、未覆蓋契約，必要時補單；原 AC 失敗原單退修。 |
| 規格／ROADMAP／決策變更 | 更新來源對應，去重調單／補單，留 AC 修訂及重驗範圍。 |
| 發現獨立前置／無關 bug／想法 | 立即回原單；任務統籌查 open／closed、未合併成果去重，建關聯前置／候選、附來源／證據／阻擋方向，全局核範圍／優先級／Ready／派工。不得自行加 worker 或把原 AC 失敗拆走。 |

### 平行派工與補位

WIP、ACK、session 分別是已派 Issue、接手確認、角色資源。[AGENTS](../AGENTS.md#建立任務與派工)的上限及補派規則適用；一張 Ready 不另核永久容量 1。等待只約束該單及真正依賴，共用檔案／服務／整合排程只約束相關操作；補單本身不授權開工。

治理收據記「上限／實占／空位 → Ready／必要前置 → 隔離／角色安排 → 派工或阻擋／解除事件」。來源取得／准入任務先核合法可執行方案，真取得／正向下游仍是交付 AC。Project 連現行規則、治理單，舊限制明示歷史。規則未整合時全局交版本化決策／差異給受影響 owner 讀回，不改被測樹或把管理候選當產品 base。

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

chips API／preview 預設 8799／8800，preview `--api-port` 預設 8799，bundle 啟動時建立；換 UI 埠不換 API，commit 不更新既有 bundle。用核定 `--port`／`--api-port` 並讀回，見[API](../tools/tpex-chips-series-api.py)／[preview](../tools/tpex-chips-series-preview.cjs)。不要求逐測試新建環境，隔離入口沿原契約。

## Projects 與關單自動化

導入設定須讀回收據：
- Status 五值，Blocked／Paused 獨立欄位。
- 停用 PR merged／Issue closed → Done、Done → close Issue 的 automation；取消／重複不算成功。
- PR／commit 用 `Refs #<number>`，不用 `Closes`／`Fixes`／`Resolves` 關單，人工不提前關。
- 合併後檢查通過才由任務統籌關 Issue／更新 Status；任一步失敗記已做／待同步，重試前讀回。
- 依授權配置 master review／適用 checks、禁止直推／強推／刪除、整合寫入者；未驗設定記未設，不冒技術保護或不存在的 CI。

配置參考：[PR 與 Issue](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue)、[Projects automation](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-built-in-automations)。

## GitHub CI 與本機 review／QA

[CI](../.github/workflows/ci.yml)於 master PR 建立／更新、master push 執行，GitHub-hosted Ubuntu／唯讀權限。行情、私人資料、正式 DB、部署憑證、付費 Copilot 不使用；安裝／build 限一次性 runner，不上傳產物或建持久 cache。

| 檢查 | 範圍與限制 |
| --- | --- |
| `repository` | 每 PR／master push 驗 diff 空白、變更檔 UTF-8、Python／JSON／YAML 語法、Markdown 相對檔案連結；Python 另驗 Ruff E9／F63／F7／F82。外部 URL／anchor／語意由 review 核，不批量改既有風格。 |
| `backend` | backend／工具／CI／驗證依賴變更：chips API 五個 `--check` profiles，RAM fixture／計算／API 邊界；guard 禁 GET／DB／寫檔。不證完整 suite、真源、磁碟。 |
| `frontend` | frontend／backend／工具／CI 變更：pnpm frozen lock、units／search／routes／presentation／stockChart 五個 standalone 回歸、TypeScript／Vite build。不證可信瀏覽器或全部 guarded 測試。 |
| `required` | 固定彙整，永遠核分類及適用工作；僅不適用可 skipped，失敗／取消／未跑／分類失敗不放行。 |

master ruleset 要求 GitHub Actions `required` 及最新 base；首次實際成功後配置／讀回，不以 YAML 存在冒設定。workflow 無 paths-ignore；文件-only 跑 repository／required，省產品測試。master CI 失敗按 AGENTS 停整合／原單退修。

CI 不替代本機獨立 review／QA：review 查邏輯／差異／規格，QA 按原 AC 驗版本／真操作；可用既有獨立 session，統籌處理意見，不啟付費雲端 AI reviewer。初始回歸涵蓋按[流程檢查](#流程檢查與滾動調整)擴充；真源／磁碟／跨程序／UI 沿本機 gate，不為 CI 縮 AC。CI／helper 變更跑兩產品工作；前端依賴／後端驗證清單各觸發所屬，backend 來源亦驗前端契約。

### PR CI 失敗與接手

任務統籌觀察適用 run 至完成或下一具名 owner ACK。離線／中斷留 owner、重查事件／時間、ACK；未接手記缺口，背景命令／未讀回通知不證交接。Git 在原單記 run URL、attempt、job／step、原 error／exit、base／head／實際 test 完整 SHA；統籌核最新 required 綁當前 base／candidate，指定下一角色。

- 程式／測試／helper 缺陷：回開發中，原 branch 修正、保留失敗；自測／review、獨立 QA、文件／索引／freeze 後回待整合，推同 PR 核准候選並重跑適用 CI。不刪測試、skip 適用工作、改 expected 湊綠；驗收語意依範圍決策。
- 有 runner／network 暫態證據：同 base／head 可重試一次、保存兩 run／attempt；再失敗 Blocked=是、保留階段／owner／原 exit／解除條件／重查事件。外部條件變更另記新證據再核重試；無暫態證據或版本變更不套重試。
- cancelled／stale head 不直接算 bug 或通過；最新 required 缺失／未完／不成功不合併。master 變則重核 base／candidate／差異／QA／CI。
- 合併前失敗，核 master 未寫後全局釋放入口重排，WIP 按掛起／停寫規則；合併後按[AGENTS](../AGENTS.md#合併與-git-結案)待整合／停其他整合／原單修正重驗。

上述以事件／owner 接手，不建背景喚醒、定時監看或未授權重跑。

## 流程檢查與滾動調整

全局追蹤／排序／決策，任務統籌原單收版本化證據，[治理 #1](https://github.com/YiCheng0608/stock-lab/issues/1)連待接手項、決策及原單證據。未任命全局時標待接手／ACK，流程維護角色不能代填 owner 或恢復產品；新任／恢復全局核實 session、接受項、下次事件才接手。

每次原單記 owner／session、觸發、版本／證據、處置、下次事件，治理單連回。勾選不免後續檢查，日期／補單／文件不解除暫停或授權排程。

| 檢查項目 | 負責角色 | 觸發事件 | 必備證據 | 處置 |
| --- | --- | --- | --- | --- |
| CI 涵蓋 | 工程提案、QA 核 AC、統籌收據、全局跨任務決策 | PR／AC／CI 入口變更 | AC、SHA、案例／缺口、run／結果、本機項 | 同 PR 補可重建案例、QA review；沿[runner／本機 QA](#github-ci-與本機-reviewqa)，不縮 AC。 |
| 拆單 | 統籌回報、全局決策 | Ready 不足／阻塞／不可獨立驗／驗收後 | 原 AC、範圍、真正前置／獨立操作 | 當次拆分／補前置／維持，留原 AC 及承接，不等無關結案。 |
| 角色／槽位 | 統籌核階段及寫權、全局排資源 | 啟動／恢復／交接／容量變更 | actual session／模型／reasoning／cwd／branch／HEAD、白名單、停寫／ACK、QA 不同 session | 按[角色](../AGENTS.md#六種角色)分階段、空閒停寫；不足只順排受影響階段。 |
| 交接欄位 | 統籌／文件核、全局調整 | 首完整試跑／重複缺漏／採用後 | 交接／ACK、版本責任缺漏／重複例證 | 刪重複，留 owner／AC 修訂／完整 SHA／停寫／ACK，治理連模板差異，不另附件。 |
| 並行資源 | 全局及參與統籌 | 派工／補派／恢復／資源變更 | Ready／前置、階段角色、共用白名單／埠／資料輸出／服務版本、索引 root／scope／版本、整合 owner／隔離 | 治理准入收據；缺口只阻受影響任務／操作，暫限列解除事件，其他獨立照常派。master 一次一張，worktree 不證隔離。 |
| 產物／歷史文件 | 統籌核量、QA 執行、文件核連結、全局排候選 | 落盤前／修改相關歷史 | 數量／大小／絕對路徑／授權／建立清理／殘留、連結失效證據 | 按[暫存規則](../AGENTS.md#驗證資料與暫存)，不足才提工具改善；觸及歷史連結時處理，既有 [#27](https://github.com/YiCheng0608/stock-lab/issues/27)不納 V1。 |

改善可延後；僅影響既定 AC、安全、啟動送達、並行隔離者阻對應動作。原 AC 失敗原單退修，獨立改善由全局去重／列候選／排序，不自納 V1 或授權派工。

單任務完整試跑驗：派工、Orca 可見工作區／session、工程自測、獨立 QA、文件、freeze、索引／coverage、候選 commit、獲授權 push／PR／CI、串行整合、master 檢查、關單／名額釋放；逐階段核 owner／版本／ACK。維護 PR／CI、mock 不算產品試跑；未發生的啟動失敗、退修、阻塞、CI 異常、owner 中斷可桌上走讀並標非實測，不刻意破壞或啟資源。

單任務試跑、逐次並行准入、實際並行交接／串行整合分別留證；單試跑不阻平行派工。開上限不證驗收、不恢復暫停、略 QA 或擴來源／落盤授權。

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

未證 ACK 只保留該單名額，其他已准入單可補位。退修依 [AGENTS](../AGENTS.md#狀態與驗收責任)原單交工程 ACK、獨立 QA，拖卡片／自動喚醒不證接手。

建立前核精確 worktree 的 terminal／session 唯讀基線，不完整就不建立。create 逾時／非 JSON／錯誤不證未建立，只在原 worktree 對帳 handle／session／可見／可執行；無法唯一確認列 unknown、候選、限制。不重複 create、殺其他 session 或據候選取得 ownership。未送記 `not sent`；結果不明或只有 accepted、沒有 actual userMessage／turn 全文核對，記送達未證。兩者依上段算 WIP，not sent 不自動釋放。失敗留原錯誤、對帳、handle／session（含未知）、送出與否、殘留、下一 owner／動作。

本機 mock 在 repo root 執行 `python -B -X utf8 tools/test_coordinator_startup.py --helper C:/Users/YiCheng/.local/bin/codex-session-control.py`。須選核定實際 helper；不可讀即失敗，無外部 helper 的自動探索不跑 suite。隔離外部呼叫，不建真 terminal／服務、不取源／DB／落盤；原單記 helper hash／命令／結果。Repo 只存測試，不部署共用 helper；雲端 CI 不證本機安裝／版本／真啟動，仍核可見派工收據。

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

<a id="導入順序與驗收"></a>

## 導入項目與驗收

1. **本機改造**：讀 AGENTS／ROADMAP／Git／模型配置，保留既有修改；規則、模板、歷史交接、一致性存本機 branch／commit，不算產品試跑。
2. **GitHub 設定**：核 repo／Project 所屬、可見性、帳號／登入授權，先唯讀盤點。外部寫入／設定獲授權才配欄位／關係／治理／整合入口，讀回 automation／權限；歷史本機路徑／session 資訊未檢查不公開發布。
3. **基線／遷移**：完成[核定範圍](#版本範圍與完成判定)、[去重補單](#待辦涵蓋與補單)、coverage／milestone 才試跑。已 review 須核主線／原證據／缺口，不直換 Done；暫停／NO-RETRY／私人保護保持。
4. **停滯／owner**：核最近兩批、Git／原 task，計數不歸零。GitHub 明示新 owner，舊 session 無接續權、不因遷移刪／關；遷移入口留實際 URL，不更新 repo 即時狀態。
5. **單試跑**：選依賴可用、有真能力增量的近期單，按[完整契約](#流程檢查與滾動調整)驗階段，再核拆單／交接欄位。
6. **並行**：按[空位補派](../AGENTS.md#建立任務與派工)、[資源准入](#流程檢查與滾動調整)留治理證據，實測交接／串行整合；與單試跑分報，不授部署／清理。

既有明示授權沿指定 repo／branch／任務範圍使用；同意流程不授登入／push／PR／merge／部署／刪除。需核准時先備確切對象、版本、檔案、動作。
