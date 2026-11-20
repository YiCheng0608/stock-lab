<!-- owns: 統籌 session、統籌換手、無人值守運作、記憶維護 -->
# 統籌手冊

統籌接手時固定讀 [AGENTS](../AGENTS.md) 與本文；其他文件依手上的事再讀：

- 建單、派工、本機檢查、review、合併、結案、留言類型、長期整合分支：[WORKFLOW](WORKFLOW.md)。
- 大 PR（計數 1,500 行以上或估計 3 萬 token 以上）的 review 交子代理，統籌不讀整份 diff：[WORKFLOW「Review 與合併」](WORKFLOW.md#review-與合併)。
- 排下一張任務、判斷範圍與 gate、更新產品方向：[ROADMAP](ROADMAP.md)；已完成能力：[CAPABILITIES](CAPABILITIES.md)。
- review 改到檢查、hook 或 CI 的 PR，規則表要補列，或查某條規則由什麼擋：[GUARDRAILS](GUARDRAILS.md)。
- 發佈與部署：[RELEASE](RELEASE.md)。
- 接手與每次巡邏用不到的段落：[統籌手冊參考](ops/COORDINATOR_REFERENCE.md)（本文原處各有一行指過去）。

## 統籌 session

同時只有一個統籌，開啟一律由 agent 執行，使用者不手動開：現任統籌觸發換手時自己開；統籌不在時使用者對任一 Claude session 說「開統籌」。要開統籌時（讀心跳檔、四行命令、原文送出的接手文）讀[參考「開啟命令」](ops/COORDINATOR_REFERENCE.md#開啟命令)。本文的 `<資料目錄>` 換成 [LOCAL](ops/LOCAL.md#正式位置使用者決定)「正式位置」表的「正式資料目錄」，`<資料目錄>/logs` 就是該表的「統籌的資料目錄的 `logs/`」；心跳檔是 `<資料目錄>/logs/coordinator-heartbeat.json`。

`take_over.sh` 中途停下要續跑，或要知道它某一步做什麼（含 `--from`、`--closed-only`）時讀[參考「接手腳本的步驟」](ops/COORDINATOR_REFERENCE.md#接手腳本的步驟)。

**resume 統籌**（#710）：重開機、terminal 被關要接回原統籌 session 時讀[參考「resume 統籌」](ops/COORDINATOR_REFERENCE.md#resume-統籌)。

**自動換手機制**（統籌 session 自己執行，不需要人在場）：

1. 偵測：由 `patrol.sh` 做，達下面「統籌換手」的條件時表頭與最後一行印「已達換手條件」、exit 10。壓縮次數與 context 怎麼數、讀不到時印什麼，以及量接手加了多少 context（`session_cost.py takeover`）時讀[參考「換手偵測」](ops/COORDINATOR_REFERENCE.md#換手偵測)。
2. 執行（含換手空窗）：要換手時讀[參考「執行換手」](ops/COORDINATOR_REFERENCE.md#執行換手)。
3. 接回：新 session 沒接上時，同上。
4. 收尾：由新統籌的 [`take_over.sh`](../tools/ops/take_over.sh) 做。`close` 步驟對舊 terminal 送短訊之前，腳本會印出舊 terminal 的畫面與 `draft`（輸入框裡還沒送出的字，短訊送出後就沒了；有字時多印一行提示），新統籌照印出的內容看最後一個回合與 `draft`：有使用者交代、而舊統籌沒照第 2 點（換手空窗）留到 #1 的事，由新統籌在 #1 補一則 `決定：` 並照常處理；只是問進度就在回覆使用者時一併回答。讀舊 terminal 那一步就失敗、沒有印出畫面時，讀[參考「接手腳本的步驟」](ops/COORDINATOR_REFERENCE.md#接手腳本的步驟)。
5. 換手不通知工程師（細節同第 2 點）。新統籌之後給工程師的留言仍照[開工](WORKFLOW.md#任務流程)的反方向規則通知 terminal。

## 無人值守運作

使用者不在時統籌照本節持續推進；使用者回來只看 [#1](https://github.com/YiCheng0608/stock-lab/issues/1) 本文與看板。

- **事件佇列**：GitHub 與排程狀態由常駐的事件 monitor（[`monitor.sh`](../tools/ops/monitor.sh)，排程與管理見 [統籌事件 monitor](ops/MONITOR.md)）輪詢，不用 LLM；統籌 session 只處理 monitor 送來的事件，不自己輪詢 GitHub、不排定時輪詢的工作，也不自己用 gh 查 PR、CI 或新留言；接手時的 `patrol.sh --overview`，以及對某張單動作前讀那張單的本文與相關留言（[接手文](ops/COORDINATOR_REFERENCE.md#開啟命令)）不在此限。要判斷某個事件為什麼（沒）喚醒、monitor 每輪讀什麼時讀[參考「事件 monitor」](ops/COORDINATOR_REFERENCE.md#事件-monitor)。
- **處理佇列**：被喚醒時（或自己開始一輪工作時）先跑 `bash tools/ops/wake_listener_start.sh`（wake listener 已在跑就什麼都不做），再跑 `bash tools/ops/patrol.sh`：[它](../tools/ops/patrol.sh)印出 monitor 的心跳與它最後一輪看到的 open PR 與排程日誌最後一列、[未回覆的提問](WORKFLOW.md#留言類型)、並行名額（下一點）、未處理的事件與未兌現的承諾（見下面「統籌承諾」；達換手條件時最後一行另印、exit 10）。patrol 只在統籌被喚醒或開始一輪工作時跑一次，不是輪詢。照這個順序處理：open PR 的 CI 與合併 → [未回覆的提問](WORKFLOW.md#留言類型) → #1 漏同步（exit 12）：把列出的決定補進 #1 本文，一次性的決定在它的留言加 `本文：不同步`（見下面「決策落地」）→ 看 patrol 的名額行，名額空缺就派工（下一點）→ 背景工作是否卡住；處理完以 `patrol.sh --done <seq>`（到該 seq 為止的未處理事件，含下述不喚醒的事件）或 `--done <事件 id>` 標記。patrol 印的「未查完」、`--overview` 的兩層、exit 碼、分級、「不喚醒的事件」、`gh_auth` 事件，或 patrol 因心跳屬於別的 session 而非 0 結束時，讀[參考「patrol 的輸出」](ops/COORDINATOR_REFERENCE.md#patrol-的輸出)。
- **並行名額**（#727，決定 [6882324819](https://github.com/YiCheng0608/stock-lab/issues/727#issuecomment-6882324819)）：名額由 patrol 經 [`slots.py`](../tools/ops/slots.py) 計算，統籌照名額行派工，不自己數、不沿用前任的數。名額行怎麼讀、某張單為什麼算或不算、待辦為什麼列成有依賴、什麼時候 exit 11，讀[參考「並行名額的判定」](ops/COORDINATOR_REFERENCE.md#並行名額的判定)。
  - 統籌寫 review（含複核通過）一律以「review：可合併，必修 0 項（head `<sha>`…）」或含這兩段的第一行開頭，否則程式讀不到。
  - **等外部（不算）**：Issue 上一則第一行是 `回報：等外部（head `<sha>`）：<事件>，預計 <YYYY-MM-DD HH:MM>（台北）` 的留言，由工程師（或統籌）在只剩等外部時點時留；什麼時候失效見參考。
- **工程師 session**（#595）：佇列有 `engineer_*` 事件、或要知道 turn hook 怎麼寫狀態檔時讀[參考「工程師 session 的狀態」](ops/COORDINATOR_REFERENCE.md#工程師-session-的狀態)；要找工程師的 terminal 或 resume 時讀[參考「工程師 terminal 與 resume」](ops/COORDINATOR_REFERENCE.md#工程師-terminal-與-resume)。
- **統籌留言**：統籌在 Issue／PR（含 #1）留言一律用 `bash tools/ops/comment.sh <Issue 或 PR 編號> --body-file <本文檔>`（[它](../tools/ops/comment.sh)在本文最後加一行不顯示的標記 `<!-- stock-lab:coordinator -->`，印出留言 URL；gh 失敗時非 0 結束、不印 URL），不直接用 `gh issue comment`／`gh pr comment`：所有 session 共用同一個 GitHub 帳號，monitor 只能靠這個標記認出統籌自己的留言、不為它喚醒統籌。本文檔照[留言類型](WORKFLOW.md#留言類型)第一行標類型，寫在 session 的 scratchpad。沒有標記的留言（工程師、使用者、獨立 review）照分級喚醒。
- **monitor 的留言**：#1 有 monitor 的「待使用者：請開統籌」或看門狗的留言，或要排一次性的定時工作提醒自己兌現承諾時，讀[參考「monitor 與看門狗的留言」](ops/COORDINATOR_REFERENCE.md#monitor-與看門狗的留言)。
- **待辦隊列**：下一輪任務先建成 Issue（看板待辦），依 ROADMAP 與 milestone 的順序排，優先順序就是看板位置（patrol 照它列待辦）；建單時依賴另一張 Issue 的，除了本文「依賴的任務／資料：」一行，也用 GitHub 的 blocked-by 設上（`gh api -X POST repos/YiCheng0608/stock-lab/issues/<n>/dependencies/blocked_by -F issue_id=<被依賴的 Issue 的 id>`），patrol 才讀得到。[並行名額](../AGENTS.md#任務生命週期)（3 個，做完只等合併與只等外部時點的任務不算，由 patrol 計算，見上面「並行名額」）有空額就從最新 `origin/master` 派下一張。沒有已建 Issue 就先建，不停擺。台北 21:30～23:30 是排程 `daily` 時段（21:30 正式一輪、23:00 保險一輪，#466）：不派新工、不跑全套 pytest、不跑全市場 analyze，也不做吃記憶體的 `docker build`。
- **需要使用者的事**（來源與付費、刪正式資料、外部帳戶、部署、對外操作、正式資料位置）：在 #1 留言寫清楚問題與統籌建議，標「待使用者」，轉做不受影響的工作；不猜答案、不停工。範圍取捨不在此列：照統籌建議先做，每項先在 #1 留 `決定：`（[AGENTS「角色」](../AGENTS.md#角色)）。部署（[`deploy.sh`](RELEASE.md#部署)）與要發佈的 tag 範圍也在這裡：使用者在 #1 明確授權後統籌才執行，授權留言連結寫進 `--operator`；腳本本身不檢查授權。
- **決策落地**：會影響後續判斷的使用者決定，當下寫進 #1 留言並同步更新 #1 本文的決策索引（只列仍有效的決策、待使用者事項與現任統籌，每條附留言連結）。一次性的決定（同意某個 PR 合併、確認某天的通知有收到這類用完就沒有後續的決定）不進本文：統籌在那則 `決定：`／`統籌承諾：` 裡另起一行寫 `本文：不同步（<原因>）`。patrol 列 #1 漏同步（exit 12），或要知道哪些留言算已同步（歸檔行、涵蓋、已取代）時讀[參考「決策落地的比對」](ops/COORDINATOR_REFERENCE.md#決策落地的比對)。
- **統籌承諾**：統籌對工程師做出偏離手冊的承諾（例如合併後先不清 worktree），或答應日後在某個時點做某件事（例如隔天的實測、21:30 daily 後的核對）時，同時寫兩處：在該 Issue 留一則 `統籌承諾：` 留言（[留言類型](WORKFLOW.md#留言類型)），再以 `bash tools/ops/commit.sh add --due <時間或 none> --url <那則留言的連結> --text <內容>` 寫進承諾檔 `<資料目錄>/logs/commitments.jsonl`（[`commit.sh`](../tools/ops/commit.sh)；時間寫成 `2026-11-07T09:23+08:00`，沒有固定時點寫 `none`）。兌現後在 Issue 留言並 `commit.sh done <id> --url <留言連結>`。`patrol.sh` 每次列出未兌現的承諾，已到期的標「已到期」；session 內排的一次性定時工作只當提醒，跟著 session 消失，不是唯一記錄。換手後由新統籌兌現（`take_over.sh` 也會列出）。
- **統籌換手**：觸發條件任一成立就換：同一 session 已自動壓縮兩次以上；最後一次呼叫的 context 超過門檻（預設 450K，#710）；統籌自覺回答對不上 Issue 與文件；使用者要求。偵測與執行步驟見[統籌 session](#統籌-session)的自動換手機制。
- **前提與限制**：統籌停在權限或信任的確認框時，只有使用者能選，monitor 不替統籌選。其他前提（開機登入、額度用盡、合併把關），以及 #1 有「待使用者：統籌停在確認框」時，讀[參考「前提與限制」](ops/COORDINATOR_REFERENCE.md#前提與限制)。

## 記憶

Claude Code 的 project memory（`MEMORY.md` 與它列的記憶檔，每個統籌與工程師 session 開場都載入）在 repo 外，worktree 與管理 checkout 共用同一份。實際位置是 `C:/Users/YiCheng/.claude/projects/<slug>/memory/`，`<slug>` 是管理 checkout 的路徑、英數以外的字元換成 `-`（現在是 `C--Users-YiCheng-Desktop-taiwan-stock-research`）。Orca 開的 session 看到的是 `$CLAUDE_CONFIG_DIR/projects/<slug>/memory/`，那是指向實際位置的 symlink。CI 讀不到它，所以由本機檢查維持（#705）。

- **用實際位置改**：統籌改記憶的 Edit／Write 一律寫實際位置，不要寫 session 開場提示給的 `$CLAUDE_CONFIG_DIR` 底下的 symlink 路徑。經 symlink 寫入會跳確認框（「outside working directory via a symlink」），加 `--add-dir` 也一樣；確認框有時停 100 秒以上，統籌就卡在那裡，佇列和喚醒都停住。寫實際位置不跳框，啟動與 resume 命令不必改（實測 [6880462190](https://github.com/YiCheng0608/stock-lab/issues/705#issuecomment-6880462190)）。
- **誰改**：只有統籌與使用者改記憶（含新增）。工程師 session 不寫記憶目錄：多個 session 同時寫同一份 `MEMORY.md` 會互相覆蓋。checkout 在 `task/*` branch 的 session 以 Edit／Write／NotebookEdit 寫記憶目錄時，實際位置或 symlink 路徑都會被 [`agent_guard.cjs`](../tools/ops/agent_guard.cjs) 擋下（Bash 擋不到，見 [GUARDRAILS](GUARDRAILS.md)）。工程師把任務讓哪幾則記憶過期（檔案刪除、流程改變、角色改名、坑已編成檢查）寫在 PR 本文「欄位」區的「會過期的記憶」（[PR 模板](templates/pull-request.md)；沒有就寫「無」，空著時 CI `pr` 規則 f 會紅）。
- **何時改**：結案時，`close_task.sh` 之後（[任務流程](WORKFLOW.md#任務流程)第 6 步）。照 PR 本文「會過期的記憶」改寫或刪掉那幾則：坑已編成檢查的，改成一句「已由 <檢查> 擋」併入相關主題，或直接刪掉（[encode-lesson](../.claude/skills/encode-lesson/SKILL.md) 第 6 步）。同步 `MEMORY.md`，改名或刪除時一併改掉別則的 `[[舊名稱]]`，再跑一次 `memory_check.py` 確認通過。平時讀到與現況不符的記憶，也當下改或刪。
- **檢查**：`memory_check.py` 失敗、要手動跑，或要知道它檢查什麼時，讀[參考「記憶的檢查」](ops/COORDINATOR_REFERENCE.md#記憶的檢查)。
