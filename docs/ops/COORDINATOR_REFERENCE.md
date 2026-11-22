<!-- owns: 開啟命令、接手文、接手腳本的步驟、resume 統籌、換手偵測、執行換手、事件 monitor、patrol 的輸出、並行名額的判定、monitor 與看門狗的留言、決策落地的比對、前提與限制、工程師 session 的狀態、工程師 terminal 與 resume、記憶的檢查 -->
# 統籌手冊參考

[統籌手冊](../COORDINATOR.md)裡接手與每次巡邏用不到的段落（#828、#850、#857）：手冊原處留一行「遇到什麼時讀這裡哪一節」。各節是從手冊逐字搬來的原文，只把相對連結改成從本目錄算；原文裡的「下面「…」」指的是手冊的段落。接手文也在這裡（「開啟命令」）：新統籌的第一則提示就是它，接手時不再從手冊讀第二次。各節彼此獨立：照手冊那一行指的節讀，不必整份讀。

## 開啟命令

開啟一律由 agent 執行（[統籌 session](../COORDINATOR.md#統籌-session)）。開啟者先讀心跳檔 `<資料目錄>/logs/coordinator-heartbeat.json`（`<資料目錄>` 換成 [LOCAL](LOCAL.md#正式位置使用者決定)「正式位置」表的「正式資料目錄」，`<資料目錄>/logs` 就是該表的「統籌的資料目錄的 `logs/`」；本文其他處的 `<資料目錄>` 同）：心跳在 60 分鐘內就不開，改對心跳記的 handle 送一句「請跑 bash tools/ops/patrol.sh 處理事件佇列」；否則在 `master` 管理 checkout 開可見 terminal：

```text
orca terminal create --worktree id:<repoId>::<master 路徑> --title "統籌" --command "claude --model claude-opus-5-5 --effort xhigh --autocompact 400k" --json
orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json
orca terminal send --terminal <handle> --text "<接手文>" --enter --json
orca terminal rename --terminal <handle> --title "統籌" --json
```

`--autocompact 400k` 把自動壓縮視窗設在 400K，不等到模型上限才壓縮。新統籌第一次呼叫的 context 門檻是 55K；repo 的 `.claude/settings.json` 關掉了用不到的 plugin、連接器、工具與 skill，每一項的理由、怎麼量、怎麼對單一 session 開回來見 [LOCAL](LOCAL.md#session-起始-context-的專案設定)。標題只是給人看的，存活判定一律用心跳檔。

接手文固定如下，開啟者原文送出，`<舊 handle>` 換成心跳記的舊統籌 terminal，它已不存在時換成 `--no-old-terminal`；開啟者若不是統籌本人，開完只回報 handle，不再對 repo 寫入：

```text
你是 stock-lab 的統籌。先讀 AGENTS.md、docs/COORDINATOR.md、治理 Issue #1 本文的決策索引。接著跑 bash tools/ops/take_over.sh <舊 handle>：它寫心跳、啟動 wake listener、在 #1 留「統籌 session 更換」並改 #1 本文的現任統籌、等舊統籌 terminal 閒置後關掉它、列出未兌現的承諾、核對最近 48 小時內關閉的 Issue 與合併的 PR、檢查記憶目錄；中途失敗會停下並印出已做的步驟與續跑命令，修好原因後照它續跑，不手動補做。關閉單只讀「關閉單核對」列為異常或未查完的那幾張的最後一則留言並處理，其餘不讀。再跑 bash tools/ops/patrol.sh --overview：它除了事件佇列、未回覆的提問、名額與承諾，還印出現況頁的索引（每張 open Issue 與 PR 的標題、未勾 AC 數、名額、最後一則留言；未回覆的提問、不在承諾檔的統籌承諾印全文；有效的等外部宣告、統籌要做的事逐條；以及 #1 最近 10 則留言），不另外整串讀 open Issue 與 PR。現況頁是索引，不是依據：對某張單留言、決定、review、合併、派工、勾 AC 或兌現承諾之前，先跑 bash tools/ops/patrol.sh --overview <單號> 看那張單的完整段落（每則留言一行、未勾 AC 的文字、內文更正標記），再讀那張單的本文、那張單上每一則 `決定：`、`統籌承諾：`、`review：` 的全文（限定條件常只寫在內文、不在第一行），以及與這次動作有關的 `提問：` 和工程師最近一則同階段的 `回報：`（按留言 id 讀單則：gh api repos/YiCheng0608/stock-lab/issues/comments/<id> --jq .body）；`決定：` 第一行是「照 A／照建議／Qn」這類要對照才看得懂的，連它回覆的提問一起讀；第一行寫「更正 <id>」或現況頁標「內文更正或取代」的，連被更正的那則一起讀，以更正後的為準。動作會改變某張單的範圍或 AC 歸屬（含把接續單的事提前、把本單的事移走）時，照該單 `統籌承諾：`／`決定：` 原本的安排做；要改，先另留 `決定：` 寫明改什麼與理由。標「未查完」的單照印出的範圍補讀；留言超過 30 則的單不整串展開。處理未處理的事件，處理完以 --done 標記（docs/COORDINATOR.md「無人值守運作」）；以 `決定：` 回覆現況頁列為未回覆的每一則提問，以及沒有類型的舊格式提問；兌現 take_over.sh 與 patrol.sh 列出的承諾，以及現況頁列為「不在承諾檔的統籌承諾」的事（補寫進承諾檔）；核對前任標「已完成」的事（現況頁「最近 24 小時兌現的承諾」附兌現留言），不只接續；然後依手冊推進。回覆使用者一律繁體中文。
```

## 接手腳本的步驟

[`take_over.sh`](../../tools/ops/take_over.sh) 開始前先核對給的舊 handle 就是心跳記的 terminal（空字串、或心跳記的是別的 terminal，就以 64 停下、什麼都不做），所以不會關到工程師的 terminal；心跳會被第一步覆寫，舊 handle 與接手前有沒有 listener 記在 `<資料目錄>/logs/take-over-<session id>.json`，續跑時讀它核對，全部完成後刪掉。步驟依序是：`patrol.sh --heartbeat-only --take-over` 寫心跳並讀回；`wake_listener_start.sh`，之後 `--status` 要說在跑；以 `comment.sh` 在 #1 留「回報：統籌 session 更換：<handle>／<session id>」，附未兌現的承諾；讀 #1 本文、只換掉「## 現任統籌」底下那一列（其他內容逐位元組不變；標題或那一列不是剛好一個就不改並停下），送出後讀回比對；`close` 先 `orca terminal read` 舊 terminal，印出最後畫面與 `draft`（有字時多印一行提示，見[自動換手機制](../COORDINATOR.md#統籌-session)第 4 點）；接著在背景先起 `orca terminal wait --for tui-idle`，2 秒後（`TAKE_OVER_CLOSE_SETTLE`）才送一句固定短訊「新統籌 <handle> 已接手，要關閉這個 terminal。只回覆收到，不要呼叫工具。」製造一次回合結束。接手前就停在輸入框的 terminal 不會再「變成閒置」，只 wait 會逾時，2026-11-14、11-16 各發生一次（#806）。wait 只認「變成閒置」那一刻，所以要先開始等才送；舊 session 可能先自動壓縮，wait 最多等 600 秒（`TAKE_OVER_CLOSE_WAIT`）。`satisfied:true` 才 `orca terminal close`；讀不到（不存在，訊息附 `--no-old-terminal` 的續跑命令）、送不出去（沒有 `accepted:true`，背景的 wait 一併停掉）、等不到閒置，都以 `close` 失敗停下、不關，`--from close` 續跑會再送一次短訊；接手前就在跑的 listener（舊 terminal 的）要在關掉舊 terminal 後 10 秒內停止回應，再跑一次 `wake_listener_start.sh` 並以 `--status` 確認，逾時就停下（它可能不是舊 terminal 的，或晚點才結束而沒有 listener；查清後以 `--from relisten` 續跑，不再等待），本次接手才啟動的 listener 在新 terminal 裡，保留；印出未兌現的承諾；`closed` 以 GraphQL（search）讀最近 48 小時關閉的 Issue 與 PR，依建立時間排序（`sort:created-asc`，頁與頁之間順序固定；讀的過程中有新關閉的單、張數對不上時印「未查完」），一頁 100 張、照游標往下讀，最多 3 頁（gh 呼叫 1～3 次），各頁合起來核對一次、印一次，核對連到 Issue 的 PR 已合併（還有 open 的算異常；全部關閉未合併也算，`NOT_PLANNED`／`DUPLICATE` 的單除外，單號另列在「其餘正常」那一行）、merge commit 上最新一次 push 的 `CI` run 是 success（沒跑完、沒有結果、紅各自寫明；目標分支不是 master 時註明；check suite 超過一頁而沒讀到 CI 時印未查完）、連到的 PR 的 head branch 與 `task/<n>-*` 已沒有本地 branch 與 git worktree（目錄名是 `task-<n>-*` 的 worktree 也算，detached、prunable 的照樣列出）；沒有 PR 的 Issue（研究單、手動關的、`NOT_PLANNED`）只核對 worktree 與 branch，單號列在「其餘正常」那一行；沒連到 Issue 的 PR（例如 `docs/*`）單獨核對。異常與未查完的逐張一行寫原因，其餘合成一行；gh 或 git 讀不到（第 2 頁起任一頁讀不到時寫明第幾頁，已讀的頁也不當成完整）、超過 300 張（第 3 頁之後還有）、判定程式失敗時印「未查完（原因）」，不當成正常；「未查完」的行都寫實際的 gh 呼叫次數。這一步只印、不擋接手，也可以 `--from closed` 續跑；平時要再核對時跑 `bash tools/ops/take_over.sh --closed-only`（只跑這一步、不要舊 handle、不寫任何檔）；最後以 `memory_check.py` 唯讀檢查記憶目錄（[記憶的檢查](#記憶的檢查)），失敗時改好記憶再 `--from memory` 續跑。任一步失敗就停下，後面的步驟都不做，stderr 印出已完成的步驟與 `--from <步驟>` 的續跑命令（從改本文起要帶 `--comment-url` 前一次的 #1 留言），最後一行是 JSON。

統籌手冊自動換手機制第 4 點（收尾）的失敗情況：讀舊 terminal 那一步就失敗時沒有印出畫面：舊 terminal 多半已不存在，查 `orca terminal list --json` 確認後以 `--no-old-terminal --from close --comment-url <#1 留言>` 續跑。

## resume 統籌

**resume 統籌**（#710）：接回原統籌 session（重開機、terminal 被關）時帶回開啟時的旗標：`claude --resume <session id> --model claude-opus-5-5 --effort xhigh --autocompact 400k`。resume 不保證沿用開啟時的旗標（effort 會重置為預設）；前任 `59660bf2` 11/13 重啟後沒有再壓縮，context 到 793,547、該 session 67% 的成本花在 400K 以上（#708，推測是沒帶 `--autocompact`）。沒帶時還有統籌手冊[「統籌換手」](../COORDINATOR.md#無人值守運作)的 context 門檻（320K）兜底。

## 換手偵測

壓縮次數只算統籌主對話的壓縮（#811），不靠模型記得。`patrol.sh` 第一步寫心跳檔（`session_id`、`terminal_handle`、`written_at`），第二步以 [`session_cost.py`](../../tools/ops/session_cost.py) `compactions` 數自己主 transcript 裡 `isSidechain` 不是 true 的 `compact_boundary` 列（紀錄檔的找法與下面的 context 相同）；子代理的 transcript（`<session id>/subagents/`）不讀。repo 的 PreCompact hook（`.claude/settings.json` → `tools/ops/compact_hook.sh`）照舊把每次壓縮計入 `<資料目錄>/logs/compactions/<session id>.count`、在同目錄的 `<session id>.log` 記一列時間、`trigger` 與 `agent_id`（主對話記 `agent_id=none`，子代理記 `agent_id=<id> agent_type=<類型>`）；子代理壓縮時 hook 收到的是父 session 的 `session_id`，所以這個計數含子代理，工程師 session 也寫。兩邊不同時表頭另印 hook 的數字，例如「壓縮 1 次（hook 記 2 次，含子代理）」；紀錄檔讀不到或讀不懂時改用 hook 計數並註明「（hook 計數，可能含子代理；紀錄檔未讀到：原因）」，不當成 0 次。`compact_boundary` 在壓縮真正套用時才寫入，比 hook 晚（前任 `0e58cba6` 那次晚約 11 分鐘），這段時間表頭的次數還沒加上。達 2 次時表頭印「已達換手條件」，最後一行再印一次，並以 exit 10 結束（`| tail -1` 或只看結束碼也看得到）。同一步也讀自己最後一次呼叫的 context（#710）：[`session_cost.py`](../../tools/ops/session_cost.py) `context` 從紀錄檔尾往回找最後一筆非 sidechain、非 `<synthetic>`、有 `usage` 的 assistant 列，context＝input＋cache 讀＋cache 寫；紀錄檔依序找 `$CLAUDE_CONFIG_DIR/projects/*/<session id>.jsonl`、`$HOME/.claude/projects/*/<session id>.jsonl`，同一個 id 有多個檔取最後修改的，`--transcript`／`STOCK_TRANSCRIPT` 可直接指定。表頭在「壓縮 N 次」下一行印 `context：<數字>（門檻 <門檻>，<百分比>）（<紀錄檔路徑>）`；超過門檻（預設 320,000，環境變數 `STOCK_CONTEXT_LIMIT` 可改）與壓縮 2 次並列為換手條件，同樣最後一行印出、exit 10。門檻要低於自動壓縮點（#958）：統籌以 `--autocompact 400k` 開啟，扣掉自動壓縮的緩衝約 33K，約 367K 就壓縮；320,000 是 400K 的 80%，留約 47K 給一輪巡邏與交接，讓 patrol 在壓縮前先報換手（原本是 450K，高於上限，從未觸發）。`--autocompact` 改了，門檻照同一算法重算。紀錄檔讀不到或讀不懂時只印 `context：未讀到（原因；連續 N 次）`，不擋巡邏、exit code 不變；連續次數記在同目錄的 `<session id>.context-misses`，讀到就刪，連續 3 次以上在最後一行前加印「context 已連續 N 次讀不到」（#710 決定 6877357244）。任一條件成立、或自覺對不上 Issue 與文件，就換手。量接手本身加了多少 context 用 `"$STOCK_PYTHON" -X utf8 tools/ops/session_cost.py takeover <session id（前 8 碼以上）或紀錄檔路徑>…`（#803）。它印三個點的 context：第 1 次呼叫；印出 `"ok":true` 那次 `take_over.sh` 工具結果之後的呼叫（失敗後以 `--from` 續跑時是第 2 次以後；`--closed-only` 與只讀檔的 `sed`、`grep` 不算執行）；其後第一個 `patrol.sh` 工具結果之後的呼叫（`--heartbeat-only` 不算；與那次 `take_over.sh` 同一個命令或同一批結果時，第三點等於第二點）。另印第 1 次呼叫到第三個點之間，工具結果依讀取對象分組（repo 檔逐檔、#1、其他 Issue／PR、兩支腳本的輸出、統籌自己的輸出）的位元組、context 增量與位元組／token。任一點找不到時只印缺哪一個、exit 5。

## 工程師 session 的狀態

- **工程師 session 的狀態**（#595；hook 行為只寫在這裡）：工程師 session（branch `task/<issue>-*`）由 repo 的 turn hook（`.claude/settings.json` 的 Stop、StopFailure、UserPromptSubmit、SessionEnd → [`turn_hook.cjs`](../../tools/ops/turn_hook.cjs)）把狀態寫進 `<資料目錄>/logs/sessions/<session id>.json`：`working`（新回合開始，task-notification 也算）、`stopped`（回合結束；這一回合有沒有留言、最後一則訊息前 500 字）、`failed`（回合因 API 錯誤中斷，帶錯誤類型與細節）、`ended`（session 結束與原因）。
  - **擋一次**：回合結束時，hook 讀 transcript 裡這一回合（最後一則輸入之後；`isMeta` 的列如 Stop hook feedback 不算新回合）的工具呼叫。成功的 `gh issue comment`、`gh pr comment`、`gh pr create`、`gh pr review`、`comment.sh`，或 POST 到 `…/comments` 的 `gh api` 才算留言，而且最後一則留言要在回合結束前 10 分鐘內：開工留言之後做了兩小時、最後在 terminal 問統籌，不算有留言。沒有留言就擋一次，提醒工程師在等統籌就先以 `提問：` 留在 Issue。擋下後 session 繼續工作，狀態記 `working`；下一次停止（`stop_hook_active`）放行並記 `stopped`。hook 自己出錯（讀不到 transcript、資料目錄不在）時不擋，錯誤記到 `<資料目錄>/logs/turn-hook.log`。`master` 與其他 branch 的 session（統籌）不受影響；在 task worktree 另開的 review session 以 `STOCK_TURN_HOOK=off claude …` 啟動就不動作。
  - **事件**：monitor 讀這些檔（判定與去重見[統籌事件 monitor](MONITOR.md)），統籌這樣處理：
    - `engineer_waiting`：回合結束超過 30 分鐘、沒有留言（或 hook 判定不了）、之後沒有新回合。讀 patrol 印的最後一則訊息與該 Issue：在問統籌就照[留言類型](../WORKFLOW.md#留言類型)以 `決定：` 回覆並通知工程師 terminal，同時請工程師以後把提問留在 Issue；只是做完或在等外部時點，看過即可，以 `--done` 標記。
    - `engineer_failed`：回合因 API 錯誤中斷（限流、額度、認證等），立即記。額度用盡就等重置後對工程師 terminal 送一句「請繼續」；其他錯誤讀 terminal 判斷。
    - `engineer_ended`：session 結束而該任務的 worktree 還在。任務還沒完成就照下一點 resume；已完成只等合併或結案就不用動作。
  - **已知限制**：
    - 留言判定是比對命令字串：`echo` 或 heredoc 裡出現 `gh issue comment` 也會被當成有留言；`gh -R … issue comment`、`gh.exe`、GraphQL mutation 沒算到，只會多擋一次。
    - claude 程序被強制結束時 SessionEnd hook 不會跑，只剩最後一個回合的狀態；使用者中斷回合（Esc）時 Stop 不跑，狀態停在 `working`：兩種都偵測不到。
    - transcript 超過約 512 MB 時 hook 讀不進來，當成判定不了（不擋，monitor 照沒留言處理）。
    - 有背景工作在跑時結束回合而沒留言，30 分鐘後一樣記 `engineer_waiting`，事件文字寫背景工作數。

## 工程師 terminal 與 resume

- **工程師 terminal 與 resume**（#595）：工程師的 terminal 是 `dispatch.sh` 回報的 handle，也就是 `orca terminal list --json` 裡該 worktree 有 `agentIdentity` 的那個（`paneTitle` 不一定有；monitor 讀確認框也認 `agentIdentity`，#873）。同一個 worktree 另有 Orca 自動建的裸 shell terminal，它停在 `$` 不代表 session 退出；`lastOutputAt` 會被畫面重繪推進，`preview` 尾端是輸入框的建議草稿，都不能當成工作中或閒置的證據。resume 前先確認沒有該任務的 claude 程序（Windows 是 `Get-CimInstance Win32_Process -Filter "Name='claude.exe'"`，macOS 是 `ps -axo pid,lstart,command | grep '[c]laude'`；看命令列帶 `additionalDirectories` 的 `…/t<issue>/task`（#835 起；之前是 `--add-dir …/t<issue>/task`）或 `--resume <id>`）；有就是 session 還在，回到它的 terminal，不另開，否則同一個 session id 會有兩個程序。確定沒有才在 dispatch 回報的 terminal（不在了就新開一個）照[本機檢查](../WORKFLOW.md#本機檢查)的 resume 命令接回。

## 執行換手

統籌手冊[自動換手機制](../COORDINATOR.md#統籌-session)的第 2、3、5 點：

2. 執行：先寫換手標記 `<資料目錄>/logs/handoff-<session id>.json`（舊 handle、時間），之後不再合併、派工、留言（例外只有下面的換手空窗）；手上的定時承諾都要已在承諾檔（`commit.sh list` 核對，缺的先補）；再照[參考「開啟命令」](#開啟命令)開新 session 並送接手文（`<舊 handle>` 換成自己的 handle）。
   - **換手空窗**（#1 [6911025182](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6911025182)）：寫了標記到舊 terminal 被關之前，使用者在舊 terminal 講話時，舊統籌先回覆新統籌的 handle，請使用者改到新 terminal 講。講的是決定或交代（不只是問進度）時，仍以 `comment.sh` 在 #1 留一則第一行是「決定：換手空窗：…」的留言（#1 本文由新統籌同步，舊統籌不改），再對新統籌 terminal 送一句附留言連結的短訊：統籌標記的留言不會喚醒新統籌，它也可能已經讀過 #1 最近 10 則。
3. 接回：新 session 15 分鐘內未在 #1 留言，舊統籌刪標記檔、照常處理事件佇列，在 #1 記「換手失敗：<新 handle>」，下次處理佇列時再試。

第 4 點（收尾）留在手冊。

5. 換手不通知工程師：工程師的回報與提問一律在 Issue／PR 留言，不送到統籌 terminal；新統籌啟動時讀 `patrol.sh --overview` 的現況頁（動作前再讀該單原文，見接手文）並處理事件佇列（換手前後的留言都在佇列裡），之後 monitor 喚醒的是新心跳記的 terminal。新統籌之後給工程師的留言仍照[開工](../WORKFLOW.md#任務流程)的反方向規則通知 terminal。

## 事件 monitor

統籌手冊[無人值守運作](../COORDINATOR.md#無人值守運作)「事件佇列」的後半：

monitor 每輪最多 2 次 gh（open PR 的 CI 與 `mergeStateStatus`、repo 層級新留言）、兩輪至少隔 60 秒（5000 次／小時的限流全帳號共用），另讀 task worktree 數（名額事件只是提示，名額只由 patrol 判定）與排程日誌（含看門狗記的 gh 被拒）；新事件去重後寫入 `<資料目錄>/logs/events.jsonl`，並依事件的分級對心跳檔記的統籌 terminal 送一句「有 N 個事件，請處理佇列」，同一事件只喚醒一次：急件（`提問：`、CI 紅、`DIRTY` 等）立即喚醒，terminal 不閒置時每輪重試；CI 綠、`BEHIND` 等立即喚醒；`回報：`、新 PR、名額等搭下一次喚醒，最晚等 15 分鐘（#711，分級表見[統籌事件 monitor](MONITOR.md)）。monitor 在 scheduler 容器裡時（#338），佇列與心跳仍是這兩個主機路徑（bind mount），喚醒與 task worktree 數經主機的 wake listener 用本機 orca 執行；listener 沒在跑時喚醒失敗、事件留在佇列，10 分鐘後再試。

## patrol 的輸出

統籌手冊[無人值守運作](../COORDINATOR.md#無人值守運作)「處理佇列」裡 `patrol.sh` 的讀法與輸出細節：

patrol 寫心跳檔、讀自己的計數檔與換手標記，不讀排程日誌（scheduler 容器的日誌在 volume 裡）。PR、CI 與新留言讀佇列，不呼叫 gh；只有未回覆的提問與並行名額要讀每個 open Issue 與 PR 的最新留言（Issue 是否已關、`決定：` 連到哪則，佇列的留言事件看不出來）與 PR 的 commit、看板待辦，用同一次 GraphQL 讀完、不逐一呼叫，gh 呼叫最多 `--max-gh` 次（預設 1，`--overview` 時是 2；0 或到上限時印「未查完」，其他輸出照常）。`--overview`（[`overview.py`](../../tools/ops/overview.py)，#804）在最後幾行之前另印現況頁，用同一次查詢的回應（每張單多讀標題、本文與 milestone），內容見檔頭。分兩層（決定 [6914347432](https://github.com/YiCheng0608/stock-lab/issues/804#issuecomment-6914347432)）：只寫 `--overview` 印索引，接手時讀這一層；`--overview <單號>…` 印那幾張單的完整段落，對某張單動作前讀；有單的留言超過 100 則時才多一次呼叫，以別名一次補齊這些單最舊的 totalCount−100 則（最多 100 則，以留言網址去重），補到的只給現況頁用，提問與名額照主查詢判定；補不到（超過 200 則、到上限或 gh 失敗）時那張單印「未查完」與缺的範圍（決定 [6913246451](https://github.com/YiCheng0608/stock-lab/issues/804#issuecomment-6913246451)）。同一次查詢另外只對 #1 多讀本文，對照下面「決策落地」：表頭印「#1 漏同步：N 則」（GitHub 沒讀到時印「未查完」，不當成 0 則），#1 本文超過 14 KB（`STOCK_GOVERNANCE_BODY_LIMIT` 位元組可改）時另印「#1 本文 N 位元組（K KB），超過上限 M」，這行只是提示；有漏同步的留言時，在最後一行前逐則列出時間、id、第一行，最後一行寫「#1 漏同步 N 則」並以 exit 12 結束（#807）。exit 碼的優先序是換手 10 → 名額空缺 11 → 漏同步 12，同時成立時用前面的碼，但各段照印；有本 session 的換手標記時只印出、exit 0。open Issue 或 PR 超過 100 個、單一 Issue 留言超過 100 則時也印「未查完」並寫出沒讀到的範圍。

未處理事件每行前面標分級（`急件`、`立即`、`搭下一次`），表頭寫搭下一次的有幾個、還沒被喚醒涵蓋的最晚何時喚醒（UTC）。不喚醒的事件另列在「不喚醒的事件」下：統籌用 `comment.sh` 發的留言（含 `deploy.sh` 的 #1 留言）、PR 離開 open 清單（`pr_gone`）、與同 PR 同 head 的新 CI 結果同一輪出現的 `CLEAN`／`UNSTABLE` merge 狀態、monitor 自己在 #1 的「請開統籌」、`回報：開工`／`回報：收到…`、任務 PR 已離開 open 的工程師 session（#711）；它們照樣記進佇列，但不算未處理、不喚醒，也不計入 60 分鐘「請開統籌」，看過即可，不用處理（#440）。`gh_auth` 事件（GitHub 拒絕容器的 `GH_TOKEN`，看門狗與 monitor 都無法留言）由統籌用本機 gh 在 #1 留言「待使用者」請換 token（[容器內的 claude 與 gh 認證（.env）](SETUP.md#容器內的-claude-與-gh-認證env)），同一台北日只有一個這種事件。心跳檔若屬於另一個 session 且不到 60 分鐘，又沒有它的換手標記，就不覆寫並非 0 結束；確定要接手才加 `--take-over`。

## 並行名額的判定

統籌手冊[無人值守運作](../COORDINATOR.md#無人值守運作)「並行名額」的判定（統籌寫 review 的第一行與「等外部」宣告的寫法留在手冊）：

表頭印「名額：已用 N／3（算：…；不算：…）」，下面每張一行寫判定與依據的留言連結。

- **任務**：本機 `git worktree list` 裡 branch 是 `task/<n>-*` 的 worktree；同一 Issue 有多個 worktree 算一張。
- **只等合併（不算）**：PR open，PR 上最新一則帶統籌標記的 `review：` 第一行有「可合併，必修 0 項」與 `` head `<sha>` ``，之後 PR 只有 update-branch 的 merge commit（2 個 parent、committer 是 GitHub），PR head 最新一個 `required` check 不是紅（不用 rollup 的總狀態：同 head 被新 run 取消的舊 run 會讓它變 FAILURE），本機 worktree 沒有未 commit 的改動、HEAD 在 PR 的 commit 裡。PR 已合併、還沒結案的也不算（已合併，等結案）。
- **等外部（不算）**：宣告的寫法留在手冊。本機 HEAD 不是宣告的 sha、工作樹有改動、之後有 `提問：` 或沒有統籌標記的其他 `回報：`、或已過預計時點，就失效、算進名額。
- **其餘都算**：開發中（沒有 PR）、review 中、有必修、CI 紅；讀不到的（git status 失敗、留言或 commit 超過一頁）算進名額並印「判定不了（原因）」。GitHub 沒讀到（gh 失敗、`--max-gh 0`）時每張都是判定不了，名額行標「未查完」，不判定空額。
- **待辦與依賴**：有空額時列看板「待辦」（project 1 的看板位置順序，milestone 只印出；只列 open 的 `[任務]`、還沒有 task worktree 的）前幾張。GitHub blocked-by 有 open 的單，或本文「依賴的任務／資料：」那一行在等 open 的 Issue 或 PR（同一句裡（以「。」「；」「;」切）出現在「後」之前、和「後」之間有「合併」「完成」「結案」「驗收」其一的 `#n`，例如「#725（登記）合併後派」；只是參考的「#721（規格改版）」與「#729 拿掉…標示後的版本」不算），就印「有依賴，等 #…」、不算可派。
- **會失敗**：有空額而待辦有可派的單時，最後一行印「名額空缺 M 個，請派工：#n」、exit 11。換手條件同時成立時它印在換手那行之前、exit 10；有本 session 的換手標記時只印出、exit 0；台北 21:30～23:30 daily 時段也只印出，exit 0，但同時有 #1 漏同步時是 exit 12（#807）。

## monitor 與看門狗的留言

- **monitor 的留言**：佇列有事件等了 60 分鐘、這段期間統籌心跳都沒更新時，monitor 在 #1 留言「待使用者：請開統籌」（同一心跳只留一則），不自己開 session（#1 [6245309556](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6245309556)、[6320448594](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6320448594)）。monitor 停擺超過 10 分鐘由看門狗在 #1 留言（[排程看門狗](WATCHDOG.md)）。統籌兌現定時承諾（例如 G7 每日核對）可以排一次性的定時工作提醒自己，不算輪詢；承諾本身照下面「統籌承諾」寫進承諾檔。

## 決策落地的比對

統籌手冊[無人值守運作](../COORDINATOR.md#無人值守運作)「決策落地」的漏同步檢查：

漏同步由 `patrol.sh` 檢查（#807）：#1 最近 100 則留言裡，第一行是 `決定：`（含 `決定（補充…）`）、`統籌承諾：`，或沒有統籌標記的留言，id 不在本文、也不早於本文的歸檔留言，又沒有被涵蓋，就列出來、exit 12。本文寫留言連結（`issuecomment-<id>`）或只寫 id（6 位數以上，例如 `[6911025182]`）都算有寫。歸檔留言寫在本文唯一一行以 `歸檔：` 開頭的行，那一行只放一個 #1 留言連結，例如 `歸檔：[<id>](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-<id>)（2026-11-16 整理前的本文全文）`；id 小於等於它的留言都算已歸檔。`歸檔：` 開頭的行超過一行，或那一行沒有連結、有多個 #1 連結時，印「未查完」，不列任何一則。id 在本文、早於歸檔留言，或帶這個標記的統籌留言，內文提到的留言 id（例如「回覆 [id]」回覆的使用者「同意」）也算涵蓋；只往下算一層。不列的有：monitor、看門狗、`deploy.sh` 的自動留言（內文有「`tools/ops/<腳本>` 自動留言」），以及沒有統籌標記的 `部署：`、`回報：統籌 session 更換`、`回報：開工`、`回報：收到`。已被取代的決定：取代它的留言已同步進本文、內文又寫了舊決定的 id 時，就算涵蓋；也可以在本文寫上它的 id 並註明「已取代」。本文超過 14 KB 時表頭會提示，請整理成只列仍有效的決策。

## 前提與限制

統籌手冊[無人值守運作](../COORDINATOR.md#無人值守運作)「前提與限制」（「確認框只有使用者能選」那一句留在手冊）：

本機與 Orca 保持開機登入（monitor 在容器裡時，喚醒靠統籌 session 啟動的 wake listener，[統籌事件 monitor](MONITOR.md)）；訂閱額度由統籌、工程師與 LLM 批次共用，額度用盡時全部暫停到重置，不視為失敗；合併把關為 CI＋統籌 review＋高風險項獨立 review。

monitor 的喚醒會記 `prompt_blocked`，持續 10 分鐘、至少 2 次後在 #1 留言「待使用者：統籌停在確認框」，同一次停住只留一則，這段期間不留「請開統籌」（#720，[統籌事件 monitor](MONITOR.md)）。這只在佇列有事件要喚醒時才偵測得到；沒有事件等著時停住不會被發現，也不會誤事。

工程師 terminal 停在權限或信任確認框滿 10 分鐘，monitor 發一個「立即」事件 `engineer_prompt_blocked`（Issue、terminal handle、從幾點起、確認框裡命令的第一行；#873，[GUARDRAILS](../GUARDRAILS.md) 對照表、[統籌事件 monitor](MONITOR.md)），patrol 的名額列也標「工程師停在確認框」。monitor 不替工程師選。統籌讀那個 terminal 的畫面判斷：要擋的命令，統籌可以選 No，再在 Issue 留 `決定：` 說怎麼繼續；需要核准的，統籌不代選 Yes，在 #1 留「待使用者」，請使用者到那個 terminal 自己選（[WORKFLOW 任務流程](../WORKFLOW.md#任務流程)：確認框只有使用者能選）。寫記憶目錄的命令已由 `agent_guard.cjs` 直接拒絕，不會再跳框。

## 記憶的檢查

統籌手冊[記憶](../COORDINATOR.md#記憶)的「檢查」：

[`memory_check.py`](../../tools/ops/memory_check.py) 唯讀，會失敗、不是報告。它檢查五項：`MEMORY.md` 不超過 7,000 位元組、每列不超過 240 位元組（每個 session 開場都載入整份索引，#851；細節寫進記憶檔，索引只留提示）；`MEMORY.md` 每列連到一個存在的檔；目錄裡沒有不在索引的檔；`[[連結]]` 都指得到存在的記憶；反引號裡看起來是 repo 路徑的字串在管理 checkout 的 `origin/master` 上存在。判定規則見檔頭；已刪或改名的路徑要留作歷史時寫成 `<路徑>@<commit>`。失敗時每項印一列「<檔>: <檢查>: <原因>」；找不到記憶目錄時以 2 結束，不會靜默通過。兩支腳本會跑它：
- `take_over.sh` 的最後一步 `memory`：失敗時改好記憶，再以 `--from memory` 續跑。
- `close_task.sh` 在清理與索引之後、設看板之前：失敗時以 3 結束，看板不動；改好記憶後以 `close_task.sh <issue> --pr <n>` 續跑。
- 手動跑：在管理 checkout 執行 `python -X utf8 tools/ops/memory_check.py`。目錄可用 `--memory-dir` 或 `STOCK_MEMORY_DIR` 指定，預設依 `CLAUDE_CONFIG_DIR`（沒有時 `~/.claude`）推出。
