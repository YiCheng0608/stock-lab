# 專案協作規則

本文管理權責與驗收；[GitHub 工作手冊](docs/GITHUB_WORKFLOW.md)管理操作、欄位與模板。自 2026-10-09 起改用 GitHub 任務流程；舊 task、BOOT、roster、quota 及清理紀錄只供追溯，不授權新工作。

## 工具與執行範圍

- **GitHub Issues／Projects** 是任務管理唯一來源：Issue 保存目標、AC、關係、決策與收據；Project 保存狀態、優先級與排序。Repo 不另建即時任務表。
- **Repo** 保存 [ROADMAP](docs/ROADMAP.md)、規格、程式、可重建測試及長期驗收邊界。一次性命令、exit、退修與交接留原 Issue，連到確切 commit／檔案；機密、私人資料及整套產物不上 GitHub。
- **Orca** 管 session、terminal、worktree。有 Orca 用 CLI，否則用 Git，不要求安裝。只有已派工執行單建產品 branch／worktree；母單、候選及未開工阻塞單不預建。全局沿用管理 checkout。
- 查來源先用 codebase-memory 核 root、版本及 coverage；不適用或有缺口時讀原檔。索引依[手冊](docs/GITHUB_WORKFLOW.md#任務識別與程式索引)，不因新 Issue 或連線失敗重建。
- App MCP 失敗用同引擎 `C:/Users/YiCheng/.local/bin/codebase-memory-mcp.cmd cli --json <tool>`，固定 runtime `C:/Users/YiCheng/cbm-runtime`、cache `C:/Users/YiCheng/cbm-cache`。分報連線、索引、coverage；不改 ACL、終止其他 session 或另建 cache。
- 一般開發限免費公開資料與本地測試；正式 DB、採購、外部帳戶、排程、部署、自動交易仍需對應授權。保留未提交工作與歷史；角色分工不代表憑證隔離。
- 跨 session 優先用結構化參數。PowerShell 5 中文 stdin 在該 scope 設 UTF-8，Python 及寫檔用 UTF-8 並讀回；不改全域 execution policy。

## 六種角色

全局管理多張任務；每單由任務統籌協調工程、QA、文件、索引／Git，按階段啟動，空閒停寫，不要求六個常駐 session。容量不足只排程受影響階段，無依賴任務照常進行。

全局與使用者入口須為不同的獨立 actual session。入口只溝通、傳決策及交接；全局在管理 checkout 的 Orca 可見 terminal 執行，任命收據在治理 Issue 核 runtime、版本、terminal、ACK。新 owner 確認前停止新產品派工，既有工作沿原授權及停寫界線。

| 角色 | 預設模型／Reasoning | 責任與寫入範圍 |
| --- | --- | --- |
| 全局統籌 | `gpt-6.1-sol`／`ultra` | 盤點、去重拆單、排序派工、跨任務決策、整合排程、母單驗收關閉；不代 QA 簽通過。 |
| 任務統籌 | `gpt-6.1-sol`／`ultra` | 指定 Issue 的範圍、review、狀態、交接、整合申請及關閉；不自行接下一單。 |
| 工程師 | `gpt-6.1-sol`／`xhigh` | 白名單內實作、自測、修缺陷及衝突；不降 AC 或自簽 QA。 |
| QA | `gpt-6.1-sol`／`xhigh` | 獨立 session 驗指定版本，逐 AC 通過／退回／未驗；不改被驗產品程式。 |
| 文件 | `gpt-6.1-sol`／`xhigh` | 依實作及 QA／review 更新規格、說明、能力與限制；不改程式或建狀態表。 |
| 索引／Git | `gpt-6-luna`／`medium` | 指定版本索引、coverage、白名單提交及獲授權的 push／PR／整合；不改來源或處理語意衝突。 |

新建／恢復角色須在 Issue 核實際 session ID、模型、reasoning、cwd、branch、HEAD、白名單；prompt、模型表及 UI 名稱不作證據。換模型由全局記原因與配置，不改全域設定或暗中重啟。

QA 與該版本實作者須不同 session，取得原 AC、規格、自測及原始失敗，獨立決定案例與結論。文件、索引可按需重用已確認 session，不跨任務冒領身分。

<a id="啟動驗收與交接"></a>

## 建立任務與派工

正式派工（含試跑）前先盤點核定版本的能力／AC，補齊必要 Issues 與適用證據。ROADMAP 管承諾、milestone 管必要任務集合、Project 管狀態；見[版本範圍](docs/GITHUB_WORKFLOW.md#版本範圍與完成判定)。

1. 全局依[補單規則](docs/GITHUB_WORKFLOW.md#待辦涵蓋與補單)查契約、open／closed Issues、PR、未合併成果並去重。近期拆至可獨立驗收，遠期保留功能概述；每日開始／恢復、Ready 不足、驗收、需求變更時補查。建單不等於派工。
2. 母單代表功能，子單代表可派工工作；小功能可獨立成單。母子與依賴分開，依賴可跨母單但不得循環；純管理母單不建工作區。
3. 每單必填目標／新增操作、範圍與不做事項、編號 AC、真實資料及版本邊界、依賴、優先級、角色。開工前補具名 owner、白名單、測試／資料授權、必要文件與適用的已驗依賴證據。
4. 先選優先母單的可開工子單；跨母單前置由全局調序。M1 → M2 → M3 是優先順序，不要求逐母單清空。Ready 須範圍清楚、真正前置已驗且版本／用途適用、授權及執行條件滿足；Done 不證依賴可用。資料取得／來源准入任務先核合法可執行方案，真實取得、正向讀用及原 AC 留執行後驗，不要求先完成本單才開工。
5. **WIP 上限 5，實占 0～5，無固定容量 1。** 預留、啟動、開發、測試、待整合及已開工阻塞均占額；角色數、候選、容器母單不計。派工／補派／恢復先核[並行資源](docs/GITHUB_WORKFLOW.md#流程檢查與滾動調整)，治理 Issue 記上限／實占／空位／處置。具體資源不足或隔離缺口才暫限受影響任務／階段，列限制數、原因／證據、替代安排、解除事件；僅一張 Ready 不降上限。有空位及 Ready 即補派，不足即查拆工／必要前置並列缺口及下一步，不等無關前單或湊名額。名額依[掛起](#狀態與驗收責任)或[啟動失敗](docs/GITHUB_WORKFLOW.md#派工與接手)釋放。單任務試跑不阻擋平行派工；master 整合一次一張。
6. 全局在 Issue 記派工、預定統籌、工作區授權並預留名額；用 Orca 從最新已驗正式 master 建 `task/<issue>-<slug>`。依[接手規則](docs/GITHUB_WORKFLOW.md#派工與接手)核可見 terminal、runtime、版本、全文送達、ACK；確認前保持待辦且不派工程師，逾時不重派。
7. 全局劃分共用檔案白名單，核服務埠、資料路徑、索引綁定及[隔離／順序驗證](docs/GITHUB_WORKFLOW.md#執行資源與服務版本)。交付者停寫、保留成果，指定接收角色、動作、AC 修訂與版本；讀回 ACK 後才轉寫入權。恢復先核 GitHub 現行 owner／交接。

ACK 是各任務的版本／範圍讀回及接手，不是配額或共同開工門檻。單張待 ACK、啟動失敗、QA、退修、阻塞只影響該單及真實依賴；其他已准入任務照常派工。全局負責[流程檢查](docs/GITHUB_WORKFLOW.md#流程檢查與滾動調整)，任務統籌在原單收證據。

## 狀態與驗收責任

執行狀態只有 **待辦 → 開發中 → 測試中 → 待整合 → 完成**；Blocked／Paused 另記，保留原階段，回報三欄。配置見[手冊](docs/GITHUB_WORKFLOW.md#欄位與唯一來源)。

Paused 保留工作區，不代表完成／取消。全局核所有角色停寫、版本／收據保存、Ready=否、Paused=是、退出整合占用後才釋放 WIP。原單列原因、解除條件、決策者、重查事件／時間；恢復須全局重核依賴／版本並明示重排，日期、換 session 或新任務不自動恢復。

| 轉移 | 負責者 | 必備證據與下一動作 |
| --- | --- | --- |
| 待辦 → 開發中 | 全局派工、任務統籌確認 | Ready、owner、白名單、授權、ACK 齊全，工程實作／自測。 |
| 開發中 → 測試中 | 任務統籌 | 自測／review 齊全、工程停寫；索引／Git 提交候選，記完整 SHA、AC 修訂、clean；QA 在同 worktree 獨立驗。 |
| 測試中 → 開發中 | 任務統籌依 QA 退回 | 原單列失敗 AC、實際／預期、復現、版本；工程修正，獨立 QA 重驗受影響項。 |
| 測試中 → 待整合 | 任務統籌 | QA 逐項通過、文件／證據齊全；final freeze、索引 coverage、最終候選與 QA 一致，申請整合。 |
| 待整合 → 完成 | 任務統籌 | 正式 master 包含核准版本，合併後檢查通過；最終 SHA／PR／證據回原單，再關 Issue／更新 Project。 |

候選 checkpoint 鎖 QA 版本，不證最終索引完成。QA 期間所有角色不得改被測樹，要寫先交接，並核[服務載入版本](docs/GITHUB_WORKFLOW.md#執行資源與服務版本)。QA 後純文件可核差異、適用範圍、最終 SHA 沿用程式證據；程式／設定／驗收語意改動須重驗受影響項。

一般退修在原 Issue／branch／worktree、原白名單與授權交回工程師並核 ACK，修正、自測／review 後交獨立 QA；不新增 WIP 或逐輪等使用者指令。卡片退回不證 agent 已接手。來源用途、配額耗盡、暫停恢復、擴範圍、外部操作仍依原 gate。

母單須必要子單完成、整體 AC 在已整合版本通過才由全局關閉；需額外實作另派子單。容器只聚合進度。取消／重複用 GitHub 未完成理由及決策結案，不標完成或計核心增量。

## 疑問、阻塞與範圍變更

- 疑問留原單由任務統籌處理；產品取捨／跨任務交全局。需使用者決策時列選項、影響、等待條件。
- 原 AC 失敗留原單退修；獨立前置、無關 bug／想法依[補單規則](docs/GITHUB_WORKFLOW.md#待辦涵蓋與補單)分流，不自擴範圍或派 worker。
- 阻塞列原因、決策者、解除條件、原階段、下一動作、重查事件／時間；必要 gate 未滿足就等待，不降真實性、安全、磁碟或執行條件。
- 保留 AC 修訂。改範圍由全局核定並記原因、使用者影響、依賴、重驗項；QA 按差異重核，不刪失敗或縮條件冒通過。
- 既定 AC 的必要前置／缺陷由全局記影響後納入；新功能、市場、策略、縮承諾須使用者決定。候選預設不納 V1，未答不視同意；見[版本範圍](docs/GITHUB_WORKFLOW.md#版本範圍與完成判定)。
- 暫停／撤權即停對應工作，改文件／喚醒不代表恢復。GitHub 不可用時停新派工、正式狀態轉移與整合，可續已授權且版本明確的本地工作；恢復先補原單、核 owner，不建 repo 看板替代。

## 合併與 Git 結案

1. 正式 master 全走全局指定的**單一整合入口**。GitHub 記入口、正式 remote／branch、持有者、Issue、base／candidate 完整 SHA、授權、開始時間；Git 只操作獲准項，人工同樣遵守。未配權限／branch protection 不稱技術鎖。
2. 輪到任務，由 Git 在該 worktree 把最新正式 master 合入 branch，工程師處理衝突；跨任務共同確認。不在 master 修、不全選一方、不混他人修改。
3. branch／master 改動須分析差異：需修正退開發、需 QA 轉測試，通過才回待整合。驗整合行為及受影響 AC、補文件、freeze／相關索引／coverage／提交；base 或 candidate 變即舊核准失效，重核必要證據，不盲重跑全套。
4. push、PR、merge 各需明示授權，PR 回原單並附 QA／文件／索引／授權。禁提前自動關單，見[automation](docs/GITHUB_WORKFLOW.md#projects-與關單自動化)；送 PR 後按[CI 接手規則](docs/GITHUB_WORKFLOW.md#pr-ci-失敗與接手)處置至完成或下一 owner ACK，失敗同單／branch／PR 退修。
5. 合併前再核 base 未變、候選／工作樹一致、檢查及授權有效。預設 merge commit 保留已驗歷史；squash／rebase 須另核版本映射。只經核准 PR 整合，不直接 push master 或本地 ff-only 繞過。
6. 合併後在明確 master SHA 跑必要檢查。失敗保持待整合、記「合併後檢查失敗」、停其他整合；須修程式依第 3 項退修，原單交修正 PR 或獲授權 revert，QA 重驗後解除，不先 Done 另開單。
7. 原單回報合併版本、提交範圍、QA／檢查、索引限制、剩餘差異、清理，再關單／釋放入口。中斷由全局核舊 owner 停寫後接管，不憑逾時搶占。

已派工本地 checkpoint／最終提交只 stage freeze 白名單，不混無關修改、秘密或忽略產物。GitHub 登入、Issue／Project 寫入、push、PR、merge、部署、清理各記授權對象／範圍；既有明示授權沿用，角色名不授權。

## 驗證資料與暫存

- 真資料、計算、API、UI 須具名操作驗收，記版本、日期、市場／標的／用途、未支援範圍。fixture／SSR／mock 不證真來源或可信 UI，索引不證功能。
- 唯讀用已授權資料或固定小樣本；計算／解析／邊界用 RAM 或最小 fixture。先查入口、import、設定副作用；真資料不取代邊界案例。
- 保存、備份、跨程序／重開讀回、雜湊及磁碟契約須最小隔離檔案，不用 RAM 替代、不例行複製整份 DB 或逐角色建環境；見[開發入口](docs/development-baseline/README.md)。
- 落盤前原單核數量、大小、建立／清理及授權。禁 `-KeepArtifacts`、整套成功產物保留；未解問題只留必要復現，列目的、位置、範圍、期限／清理條件。模板不代表逐輪附件。
- 只清本次自有、已核絕對路徑的授權產物；不掃 Temp、改名轉存或處理其他 session 資源。成功／失敗均嘗試清理，中斷／占用／拒絕不稱已刪。
- 測試、清理分報，保留原 exit、未跑項、失敗路徑／大小／原因。清理失敗不否定驗收或要求重跑；殘留達上限只停新增落盤案例。
- Done 不刪 worktree／branch／session。清理另核授權、範圍、已合併版本、未保存成果、owner 停寫、執行者位於目標外；保留歷史，未清／失敗明列，不借新任務取得刪除權。
- 只驗變更所需範圍，沿用適用證據。文件只查差異、連結、模板、一致性，不跑 backend 或建 DB；未跑不列通過。

## 文件與交接

- final freeze／索引前補規格、說明、能力、驗收邊界、缺口；owner／狀態／下一角色只更新 GitHub，不 prepend repo 文件。
- 規則在負責文件詳述，其他處摘要連結，見[文件索引](docs/README.md)。公式／代碼表／術語未變只核對，不造日期 diff。
- 原 Issue 交接含能力／證據／缺口、下一角色／動作、版本、停滯計數、freeze／索引／commit／PR／merge、ACK。舊指令不授新權；不可重建證據連正式位置，不造逐輪副本／manifest。

## 核心選題與進度判定

全局依 ROADMAP 的 M1 → M2 → M3 排序。核心須必要資料／計算、API、UI 及具名操作驗收；保存須磁碟／跨程序讀回。依賴須實際取得、驗證並解除操作阻擋；審查、規劃、fixture、unknown 不算解除，可靠性另報。

版本進度／milestone 依[完成判定](docs/GITHUB_WORKFLOW.md#版本範圍與完成判定)回報已驗能力、剩餘 AC、依賴、發布 gate，不按 Issue／PR 數量算完成率。

每批記新增能力、實際解除依賴、可靠性、驗收證據、剩餘缺口、下一步理由。前兩者皆無則連續無核心增量 +1；有任一真驗收才歸零，小修、測試、commit、換 session／branch／任務不重置。

連續兩批未推進核心，下批派工前重看拆工／選題。產品母單與批次 Issue 記計數、原因；跨母單繼承，並行按驗收接受順序計。未知先核最近兩批，不預設零。未採用來源不全域阻塞；無新取得路徑時選其他可交付能力，不空轉審查。流程改造不算產品批次。

## 導入例外與完成界線

使用者授權的流程改造可在現有 checkout 建本機流程 branch、改規則／模板／文件並本地提交，不套已撤換產品輪次 gate、不啟動產品或清舊資源。GitHub 未設定的缺口只記[遷移入口](docs/TASK_COORDINATION.md)，不建平行任務系統或假 Issue URL。

[導入文件、GitHub 配置、單任務試跑、每次並行准入及實測](docs/GITHUB_WORKFLOW.md#導入項目與驗收)分別驗收；上限開放不證通過。
