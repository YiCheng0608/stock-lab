<!-- owns: 統籌 session、接手文、統籌換手、無人值守運作 -->
# 統籌手冊

統籌接手時固定讀 [AGENTS](../AGENTS.md) 與本文（[接手文](#統籌-session)）；其他文件依手上的事再讀：

- 建單、派工、本機檢查、review、合併、結案、留言類型、長期整合分支：[WORKFLOW](WORKFLOW.md)。
- 排下一張任務、判斷範圍與 gate、更新產品方向：[ROADMAP](ROADMAP.md)；已完成能力：[CAPABILITIES](CAPABILITIES.md)。
- review 改到檢查、hook 或 CI 的 PR，規則表要補列，或查某條規則由什麼擋：[GUARDRAILS](GUARDRAILS.md)。
- 發佈與部署：[RELEASE](RELEASE.md)。

## 統籌 session

同時只有一個統籌，開啟一律由 agent 執行，使用者不手動開：現任統籌觸發換手時自己開；統籌不在時使用者對任一 Claude session 說「開統籌」。開啟者先讀心跳檔 `<資料目錄>/logs/coordinator-heartbeat.json`（`<資料目錄>` 換成 [LOCAL](ops/LOCAL.md#正式位置使用者決定)「正式位置」表的「正式資料目錄」，`<資料目錄>/logs` 就是該表的「統籌的資料目錄的 `logs/`」；本文其他處的 `<資料目錄>` 同）：心跳在 60 分鐘內就不開，改對心跳記的 handle 送一句「請跑 bash tools/ops/patrol.sh 處理事件佇列」；否則在 `master` 管理 checkout 開可見 terminal：

```text
orca terminal create --worktree id:<repoId>::<master 路徑> --title "統籌" --command "claude --model claude-opus-5-5 --effort xhigh --autocompact 400k" --json
orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json
orca terminal send --terminal <handle> --text "<接手文>" --enter --json
orca terminal rename --terminal <handle> --title "統籌" --json
```

`--autocompact 400k` 把自動壓縮視窗設在 400K，不等到模型上限才壓縮。新統籌第一次呼叫的 context 門檻是 55K；repo 的 `.claude/settings.json` 關掉了用不到的 plugin、連接器、工具與 skill，每一項的理由、怎麼量、怎麼對單一 session 開回來見 [LOCAL](ops/LOCAL.md#session-起始-context-的專案設定)。標題只是給人看的，存活判定一律用心跳檔。接手文固定如下，開啟者原文送出，`<舊 handle>` 換成心跳記的舊統籌 terminal，它已不存在時換成 `--no-old-terminal`；開啟者若不是統籌本人，開完只回報 handle，不再對 repo 寫入：

```text
你是 stock-lab 的統籌。先讀 AGENTS.md、docs/COORDINATOR.md、治理 Issue #1 本文的決策索引與最近 10 則留言、所有 open Issues 與 PR、最近 48 小時內關閉的 Issue 與合併的 PR 的最後一則留言。接著跑 bash tools/ops/take_over.sh <舊 handle>：它寫心跳、啟動 wake listener、在 #1 留「統籌 session 更換」並改 #1 本文的現任統籌、等舊統籌 terminal 閒置後關掉它、列出未兌現的承諾；中途失敗會停下並印出已做的步驟與續跑命令，修好原因後照它續跑，不手動補做。再跑 bash tools/ops/patrol.sh 處理未處理的事件，處理完以 --done 標記（docs/COORDINATOR.md「無人值守運作」）；以 `決定：` 回覆 patrol.sh 列出的每一則未回覆的提問，以及沒有類型的舊格式提問；兌現 take_over.sh 與 patrol.sh 列出的承諾，以及前任 `統籌承諾：` 留言裡承諾檔沒有的事（補寫進承諾檔）；核對前任標「已完成」的事，不只接續；然後依手冊推進。回覆使用者一律繁體中文。
```

[`take_over.sh`](../tools/ops/take_over.sh) 開始前先核對給的舊 handle 就是心跳記的 terminal（空字串、或心跳記的是別的 terminal，就以 64 停下、什麼都不做），所以不會關到工程師的 terminal；心跳會被第一步覆寫，舊 handle 與接手前有沒有 listener 記在 `<資料目錄>/logs/take-over-<session id>.json`，續跑時讀它核對，全部完成後刪掉。步驟依序是：`patrol.sh --heartbeat-only --take-over` 寫心跳並讀回；`wake_listener_start.sh`，之後 `--status` 要說在跑；以 `comment.sh` 在 #1 留「回報：統籌 session 更換：<handle>／<session id>」，附未兌現的承諾；讀 #1 本文、只換掉「## 現任統籌」底下那一列（其他內容逐位元組不變；標題或那一列不是剛好一個就不改並停下），送出後讀回比對；對舊 terminal `orca terminal wait --for tui-idle`，`satisfied:true` 才 `orca terminal close`；接手前就在跑的 listener（舊 terminal 的）要在關掉舊 terminal 後 10 秒內停止回應，再跑一次 `wake_listener_start.sh` 並以 `--status` 確認，逾時就停下（它可能不是舊 terminal 的，或晚點才結束而沒有 listener；查清後以 `--from relisten` 續跑，不再等待），本次接手才啟動的 listener 在新 terminal 裡，保留；最後印出未兌現的承諾。任一步失敗就停下，後面的步驟都不做，stderr 印出已完成的步驟與 `--from <步驟>` 的續跑命令（從改本文起要帶 `--comment-url` 前一次的 #1 留言），最後一行是 JSON。

**resume 統籌**（#710）：接回原統籌 session（重開機、terminal 被關）時帶回開啟時的旗標：`claude --resume <session id> --model claude-opus-5-5 --effort xhigh --autocompact 400k`。resume 不保證沿用開啟時的旗標（effort 會重置為預設）；前任 `59660bf2` 11/13 重啟後沒有再壓縮，context 到 793,547、該 session 67% 的成本花在 400K 以上（#708，推測是沒帶 `--autocompact`）。沒帶時還有自動換手機制第 1 點的 context 門檻（450K）兜底。

**自動換手機制**（統籌 session 自己執行，不需要人在場）：

1. 偵測：壓縮次數由 repo 的 PreCompact hook（`.claude/settings.json` → `tools/ops/compact_hook.sh`）自動寫進 `<資料目錄>/logs/compactions/<session id>.count`，每次壓縮的時間另記一列在同目錄的 `<session id>.log`，不靠模型記得；工程師 session 也寫，統籌的是心跳檔記的 session id 那份。`patrol.sh` 第一步寫心跳檔（`session_id`、`terminal_handle`、`written_at`），第二步讀自己的計數檔；達 2 次時表頭印「已達換手條件」，最後一行再印一次，並以 exit 10 結束（`| tail -1` 或只看結束碼也看得到）。同一步也讀自己最後一次呼叫的 context（#710）：[`session_cost.py`](../tools/ops/session_cost.py) `context` 從紀錄檔尾往回找最後一筆非 sidechain、非 `<synthetic>`、有 `usage` 的 assistant 列，context＝input＋cache 讀＋cache 寫；紀錄檔依序找 `$CLAUDE_CONFIG_DIR/projects/*/<session id>.jsonl`、`$HOME/.claude/projects/*/<session id>.jsonl`，同一個 id 有多個檔取最後修改的，`--transcript`／`STOCK_TRANSCRIPT` 可直接指定。表頭在「壓縮 N 次」下一行印 `context：<數字>（門檻 <門檻>，<百分比>）（<紀錄檔路徑>）`；超過門檻（預設 450,000，環境變數 `STOCK_CONTEXT_LIMIT` 可改）與壓縮 2 次並列為換手條件，同樣最後一行印出、exit 10。紀錄檔讀不到或讀不懂時只印 `context：未讀到（原因；連續 N 次）`，不擋巡邏、exit code 不變；連續次數記在同目錄的 `<session id>.context-misses`，讀到就刪，連續 3 次以上在最後一行前加印「context 已連續 N 次讀不到」（#710 決定 6877357244）。任一條件成立、或自覺對不上 Issue 與文件，就換手。
2. 執行：先寫換手標記 `<資料目錄>/logs/handoff-<session id>.json`（舊 handle、時間），之後不再合併、派工、留言；手上的定時承諾都要已在承諾檔（`commit.sh list` 核對，缺的先補）；再照上面四行開新 session 並送接手文（`<舊 handle>` 換成自己的 handle）。
3. 接回：新 session 15 分鐘內未在 #1 留言，舊統籌刪標記檔、照常處理事件佇列，在 #1 記「換手失敗：<新 handle>」，下次處理佇列時再試。
4. 收尾：由新統籌的 [`take_over.sh`](../tools/ops/take_over.sh) 做（步驟見上面接手文之後的說明）。
5. 換手不通知工程師：工程師的回報與提問一律在 Issue／PR 留言，不送到統籌 terminal；新統籌啟動時讀所有 open Issue 與 PR 並處理事件佇列（換手前後的留言都在佇列裡），之後 monitor 喚醒的是新心跳記的 terminal。新統籌之後給工程師的留言仍照[開工](WORKFLOW.md#任務流程)的反方向規則通知 terminal。

## 無人值守運作

使用者不在時統籌照本節持續推進；使用者回來只看 [#1](https://github.com/YiCheng0608/stock-lab/issues/1) 本文與看板。

- **事件佇列**：GitHub 與排程狀態由常駐的事件 monitor（[`monitor.sh`](../tools/ops/monitor.sh)，排程與管理見 [統籌事件 monitor](ops/MONITOR.md)）輪詢，不用 LLM；統籌 session 只處理 monitor 送來的事件，不自己輪詢 GitHub、不排定時輪詢的工作，也不自己用 gh 查 PR、CI 或新留言；接手時一次性讀取 open Issue 與 PR（[接手文](#統籌-session)）不在此限。monitor 每輪最多 2 次 gh（open PR 的 CI 與 `mergeStateStatus`、repo 層級新留言）、兩輪至少隔 60 秒（5000 次／小時的限流全帳號共用），另讀 task worktree 數（並行名額）與排程日誌（含看門狗記的 gh 被拒）；新事件去重後寫入 `<資料目錄>/logs/events.jsonl`，並對心跳檔記的統籌 terminal 送一句「有 N 個事件，請處理佇列」，同一事件只喚醒一次。monitor 在 scheduler 容器裡時（#338），佇列與心跳仍是這兩個主機路徑（bind mount），喚醒與 task worktree 數經主機的 wake listener 用本機 orca 執行；listener 沒在跑時喚醒失敗、事件留在佇列，10 分鐘後再試。
- **處理佇列**：被喚醒時（或自己開始一輪工作時）先跑 `bash tools/ops/wake_listener_start.sh`（wake listener 已在跑就什麼都不做），再跑 `bash tools/ops/patrol.sh`：[它](../tools/ops/patrol.sh)寫心跳檔、讀自己的計數檔與換手標記，印出 monitor 的心跳與它最後一輪看到的 open PR 與排程日誌最後一列、[未回覆的提問](WORKFLOW.md#留言類型)、未處理的事件與未兌現的承諾（見下面「統籌承諾」；達換手條件時最後一行另印、exit 10），不讀排程日誌（scheduler 容器的日誌在 volume 裡）。PR、CI 與新留言讀佇列，不呼叫 gh；只有未回覆的提問要讀每個 open Issue 與 PR 的最新留言（Issue 是否已關、`決定：` 連到哪則，佇列的留言事件看不出來），用一次 GraphQL 讀完、不逐一呼叫，gh 呼叫最多 `--max-gh` 次（預設 1；0 或到上限時印「未查完」，其他輸出照常）。patrol 只在統籌被喚醒或開始一輪工作時跑一次，不是輪詢。open Issue 或 PR 超過 100 個、單一 Issue 留言超過 100 則時也印「未查完」並寫出沒讀到的範圍。照這個順序處理：open PR 的 CI 與合併 → [未回覆的提問](WORKFLOW.md#留言類型) → 名額空缺就派工 → 背景工作是否卡住；處理完以 `patrol.sh --done <seq>`（到該 seq 為止的未處理事件，含下述不喚醒的事件）或 `--done <事件 id>` 標記。不喚醒的事件另列在「不喚醒的事件」下：統籌用 `comment.sh` 發的留言、PR 離開 open 清單（`pr_gone`）、與同 PR 同 head 的新 CI 結果同一輪出現的 `CLEAN`／`UNSTABLE` merge 狀態；它們照樣記進佇列，但不算未處理、不喚醒，也不計入 60 分鐘「請開統籌」，看過即可，不用處理（#440）。`gh_auth` 事件（GitHub 拒絕容器的 `GH_TOKEN`，看門狗與 monitor 都無法留言）由統籌用本機 gh 在 #1 留言「待使用者」請換 token（[容器內的 claude 與 gh 認證（.env）](ops/SETUP.md#容器內的-claude-與-gh-認證env)），同一台北日只有一個這種事件。心跳檔若屬於另一個 session 且不到 60 分鐘，又沒有它的換手標記，就不覆寫並非 0 結束；確定要接手才加 `--take-over`。
- **工程師 session 的狀態**（#595；hook 行為只寫在這裡）：工程師 session（branch `task/<issue>-*`）由 repo 的 turn hook（`.claude/settings.json` 的 Stop、StopFailure、UserPromptSubmit、SessionEnd → [`turn_hook.cjs`](../tools/ops/turn_hook.cjs)）把狀態寫進 `<資料目錄>/logs/sessions/<session id>.json`：`working`（新回合開始，task-notification 也算）、`stopped`（回合結束；這一回合有沒有留言、最後一則訊息前 500 字）、`failed`（回合因 API 錯誤中斷，帶錯誤類型與細節）、`ended`（session 結束與原因）。
  - **擋一次**：回合結束時，hook 讀 transcript 裡這一回合（最後一則輸入之後；`isMeta` 的列如 Stop hook feedback 不算新回合）的工具呼叫。成功的 `gh issue comment`、`gh pr comment`、`gh pr create`、`gh pr review`、`comment.sh`，或 POST 到 `…/comments` 的 `gh api` 才算留言，而且最後一則留言要在回合結束前 10 分鐘內：開工留言之後做了兩小時、最後在 terminal 問統籌，不算有留言。沒有留言就擋一次，提醒工程師在等統籌就先以 `提問：` 留在 Issue。擋下後 session 繼續工作，狀態記 `working`；下一次停止（`stop_hook_active`）放行並記 `stopped`。hook 自己出錯（讀不到 transcript、資料目錄不在）時不擋，錯誤記到 `<資料目錄>/logs/turn-hook.log`。`master` 與其他 branch 的 session（統籌）不受影響；在 task worktree 另開的 review session 以 `STOCK_TURN_HOOK=off claude …` 啟動就不動作。
  - **事件**：monitor 讀這些檔（判定與去重見[統籌事件 monitor](ops/MONITOR.md)），統籌這樣處理：
    - `engineer_waiting`：回合結束超過 30 分鐘、沒有留言（或 hook 判定不了）、之後沒有新回合。讀 patrol 印的最後一則訊息與該 Issue：在問統籌就照[留言類型](WORKFLOW.md#留言類型)以 `決定：` 回覆並通知工程師 terminal，同時請工程師以後把提問留在 Issue；只是做完或在等外部時點，看過即可，以 `--done` 標記。
    - `engineer_failed`：回合因 API 錯誤中斷（限流、額度、認證等），立即記。額度用盡就等重置後對工程師 terminal 送一句「請繼續」；其他錯誤讀 terminal 判斷。
    - `engineer_ended`：session 結束而該任務的 worktree 還在。任務還沒完成就照下一點 resume；已完成只等合併或結案就不用動作。
  - **已知限制**：
    - 留言判定是比對命令字串：`echo` 或 heredoc 裡出現 `gh issue comment` 也會被當成有留言；`gh -R … issue comment`、`gh.exe`、GraphQL mutation 沒算到，只會多擋一次。
    - claude 程序被強制結束時 SessionEnd hook 不會跑，只剩最後一個回合的狀態；使用者中斷回合（Esc）時 Stop 不跑，狀態停在 `working`：兩種都偵測不到。
    - transcript 超過約 512 MB 時 hook 讀不進來，當成判定不了（不擋，monitor 照沒留言處理）。
    - 有背景工作在跑時結束回合而沒留言，30 分鐘後一樣記 `engineer_waiting`，事件文字寫背景工作數。
- **工程師 terminal 與 resume**（#595）：工程師的 terminal 是 `dispatch.sh` 回報的 handle，也就是 `orca terminal list --json` 裡 `paneTitle` 是 `#<issue> <slug>` 的那個。同一個 worktree 另有 Orca 自動建的裸 shell terminal，它停在 `$` 不代表 session 退出；`lastOutputAt` 會被畫面重繪推進，`preview` 尾端是輸入框的建議草稿，都不能當成工作中或閒置的證據。resume 前先確認沒有該任務的 claude 程序（`Get-CimInstance Win32_Process -Filter "Name='claude.exe'"` 的命令列帶 `--add-dir …/t<issue>/task` 或 `--resume <id>`）；有就是 session 還在，回到它的 terminal，不另開，否則同一個 session id 會有兩個程序。確定沒有才在 dispatch 回報的 terminal（不在了就新開一個）照[本機檢查](WORKFLOW.md#本機檢查)的 resume 命令接回。
- **統籌留言**：統籌在 Issue／PR（含 #1）留言一律用 `bash tools/ops/comment.sh <Issue 或 PR 編號> --body-file <本文檔>`（[它](../tools/ops/comment.sh)在本文最後加一行不顯示的標記 `<!-- stock-lab:coordinator -->`，印出留言 URL；gh 失敗時非 0 結束、不印 URL），不直接用 `gh issue comment`／`gh pr comment`：所有 session 共用同一個 GitHub 帳號，monitor 只能靠這個標記認出統籌自己的留言、不為它喚醒統籌。本文檔照[留言類型](WORKFLOW.md#留言類型)第一行標類型，寫在 session 的 scratchpad。沒有標記的留言（工程師、使用者、獨立 review）照常喚醒。
- **monitor 的留言**：佇列有事件等了 60 分鐘、這段期間統籌心跳都沒更新時，monitor 在 #1 留言「待使用者：請開統籌」（同一心跳只留一則），不自己開 session（#1 [6245309556](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6245309556)、[6320448594](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6320448594)）。monitor 停擺超過 10 分鐘由看門狗在 #1 留言（[排程看門狗](ops/WATCHDOG.md)）。統籌兌現定時承諾（例如 G7 每日核對）可以排一次性的定時工作提醒自己，不算輪詢；承諾本身照下面「統籌承諾」寫進承諾檔。
- **待辦隊列**：下一輪任務先建成 Issue（看板待辦），依 ROADMAP 與 milestone 的順序排；[並行名額](../AGENTS.md#任務生命週期)（3 個，做完只等合併與只等外部時點的任務不算）有空額就從最新 `origin/master` 派下一張。沒有已建 Issue 就先建，不停擺。台北 21:30～23:30 是排程 `daily` 時段（21:30 正式一輪、23:00 保險一輪，#466）：不派新工、不跑全套 pytest、不跑全市場 analyze，也不做吃記憶體的 `docker build`。
- **需要使用者的事**（來源與付費、刪資料、部署、對外操作、範圍變更、正式資料位置）：在 #1 留言寫清楚問題與統籌建議，標「待使用者」，轉做不受影響的工作；不猜答案、不停工。部署（[`deploy.sh`](RELEASE.md#部署)）與要發佈的 tag 範圍也在這裡：使用者在 #1 明確授權後統籌才執行，授權留言連結寫進 `--operator`；腳本本身不檢查授權。
- **決策落地**：會影響後續判斷的使用者決定，當下寫進 #1 留言並同步更新 #1 本文的決策索引（只列仍有效的決策、待使用者事項與現任統籌，每條附留言連結）。
- **統籌承諾**：統籌對工程師做出偏離手冊的承諾（例如合併後先不清 worktree），或答應日後在某個時點做某件事（例如隔天的實測、21:30 daily 後的核對）時，同時寫兩處：在該 Issue 留一則 `統籌承諾：` 留言（[留言類型](WORKFLOW.md#留言類型)），再以 `bash tools/ops/commit.sh add --due <時間或 none> --url <那則留言的連結> --text <內容>` 寫進承諾檔 `<資料目錄>/logs/commitments.jsonl`（[`commit.sh`](../tools/ops/commit.sh)；時間寫成 `2026-11-07T09:23+08:00`，沒有固定時點寫 `none`）。兌現後在 Issue 留言並 `commit.sh done <id> --url <留言連結>`。`patrol.sh` 每次列出未兌現的承諾，已到期的標「已到期」；session 內排的一次性定時工作只當提醒，跟著 session 消失，不是唯一記錄。換手後由新統籌兌現（`take_over.sh` 也會列出）。
- **統籌換手**：觸發條件任一成立就換：同一 session 已自動壓縮兩次以上；最後一次呼叫的 context 超過門檻（預設 450K，#710）；統籌自覺回答對不上 Issue 與文件；使用者要求。偵測與執行步驟見[統籌 session](#統籌-session)的自動換手機制。
- **前提與限制**：本機與 Orca 保持開機登入（monitor 在容器裡時，喚醒靠統籌 session 啟動的 wake listener，[統籌事件 monitor](ops/MONITOR.md)）；訂閱額度由統籌、工程師與 LLM 批次共用，額度用盡時全部暫停到重置，不視為失敗；合併把關為 CI＋統籌 review＋高風險項獨立 review。
