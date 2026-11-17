<!-- owns: 開啟命令、接手腳本的步驟、resume 統籌、換手偵測、工程師 session 的狀態、工程師 terminal 與 resume -->
# 統籌手冊參考

[統籌手冊](../COORDINATOR.md)裡接手時用不到的段落（#828）：手冊原處留一行「遇到什麼時讀這裡哪一節」。各節是從手冊逐字搬來的原文，只把相對連結改成從本目錄算。

## 開啟命令

開啟者照[統籌 session](../COORDINATOR.md#統籌-session)讀過心跳檔、確定要開時，在 `master` 管理 checkout 開可見 terminal：

```text
orca terminal create --worktree id:<repoId>::<master 路徑> --title "統籌" --command "claude --model claude-opus-5-5 --effort xhigh --autocompact 400k" --json
orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json
orca terminal send --terminal <handle> --text "<接手文>" --enter --json
orca terminal rename --terminal <handle> --title "統籌" --json
```

`--autocompact 400k` 把自動壓縮視窗設在 400K，不等到模型上限才壓縮。新統籌第一次呼叫的 context 門檻是 55K；repo 的 `.claude/settings.json` 關掉了用不到的 plugin、連接器、工具與 skill，每一項的理由、怎麼量、怎麼對單一 session 開回來見 [LOCAL](LOCAL.md#session-起始-context-的專案設定)。標題只是給人看的，存活判定一律用心跳檔。

## 接手腳本的步驟

[`take_over.sh`](../../tools/ops/take_over.sh) 開始前先核對給的舊 handle 就是心跳記的 terminal（空字串、或心跳記的是別的 terminal，就以 64 停下、什麼都不做），所以不會關到工程師的 terminal；心跳會被第一步覆寫，舊 handle 與接手前有沒有 listener 記在 `<資料目錄>/logs/take-over-<session id>.json`，續跑時讀它核對，全部完成後刪掉。步驟依序是：`patrol.sh --heartbeat-only --take-over` 寫心跳並讀回；`wake_listener_start.sh`，之後 `--status` 要說在跑；以 `comment.sh` 在 #1 留「回報：統籌 session 更換：<handle>／<session id>」，附未兌現的承諾；讀 #1 本文、只換掉「## 現任統籌」底下那一列（其他內容逐位元組不變；標題或那一列不是剛好一個就不改並停下），送出後讀回比對；`close` 先 `orca terminal read` 舊 terminal，印出最後畫面與 `draft`（有字時多印一行提示，見[自動換手機制](../COORDINATOR.md#統籌-session)第 4 點）；接著在背景先起 `orca terminal wait --for tui-idle`，2 秒後（`TAKE_OVER_CLOSE_SETTLE`）才送一句固定短訊「新統籌 <handle> 已接手，要關閉這個 terminal。只回覆收到，不要呼叫工具。」製造一次回合結束。接手前就停在輸入框的 terminal 不會再「變成閒置」，只 wait 會逾時，2026-11-14、11-16 各發生一次（#806）。wait 只認「變成閒置」那一刻，所以要先開始等才送；舊 session 可能先自動壓縮，wait 最多等 600 秒（`TAKE_OVER_CLOSE_WAIT`）。`satisfied:true` 才 `orca terminal close`；讀不到（不存在，訊息附 `--no-old-terminal` 的續跑命令）、送不出去（沒有 `accepted:true`，背景的 wait 一併停掉）、等不到閒置，都以 `close` 失敗停下、不關，`--from close` 續跑會再送一次短訊；接手前就在跑的 listener（舊 terminal 的）要在關掉舊 terminal 後 10 秒內停止回應，再跑一次 `wake_listener_start.sh` 並以 `--status` 確認，逾時就停下（它可能不是舊 terminal 的，或晚點才結束而沒有 listener；查清後以 `--from relisten` 續跑，不再等待），本次接手才啟動的 listener 在新 terminal 裡，保留；印出未兌現的承諾；`closed` 以 GraphQL（search）讀最近 48 小時關閉的 Issue 與 PR，依建立時間排序（`sort:created-asc`，頁與頁之間順序固定；讀的過程中有新關閉的單、張數對不上時印「未查完」），一頁 100 張、照游標往下讀，最多 3 頁（gh 呼叫 1～3 次），各頁合起來核對一次、印一次，核對連到 Issue 的 PR 已合併（還有 open 的算異常；全部關閉未合併也算，`NOT_PLANNED`／`DUPLICATE` 的單除外，單號另列在「其餘正常」那一行）、merge commit 上最新一次 push 的 `CI` run 是 success（沒跑完、沒有結果、紅各自寫明；目標分支不是 master 時註明；check suite 超過一頁而沒讀到 CI 時印未查完）、連到的 PR 的 head branch 與 `task/<n>-*` 已沒有本地 branch 與 git worktree（目錄名是 `task-<n>-*` 的 worktree 也算，detached、prunable 的照樣列出）；沒有 PR 的 Issue（研究單、手動關的、`NOT_PLANNED`）只核對 worktree 與 branch，單號列在「其餘正常」那一行；沒連到 Issue 的 PR（例如 `docs/*`）單獨核對。異常與未查完的逐張一行寫原因，其餘合成一行；gh 或 git 讀不到（第 2 頁起任一頁讀不到時寫明第幾頁，已讀的頁也不當成完整）、超過 300 張（第 3 頁之後還有）、判定程式失敗時印「未查完（原因）」，不當成正常；「未查完」的行都寫實際的 gh 呼叫次數。這一步只印、不擋接手，也可以 `--from closed` 續跑；平時要再核對時跑 `bash tools/ops/take_over.sh --closed-only`（只跑這一步、不要舊 handle、不寫任何檔）；最後以 `memory_check.py` 唯讀檢查記憶目錄（[記憶](../COORDINATOR.md#記憶)），失敗時改好記憶再 `--from memory` 續跑。任一步失敗就停下，後面的步驟都不做，stderr 印出已完成的步驟與 `--from <步驟>` 的續跑命令（從改本文起要帶 `--comment-url` 前一次的 #1 留言），最後一行是 JSON。

## resume 統籌

**resume 統籌**（#710）：接回原統籌 session（重開機、terminal 被關）時帶回開啟時的旗標：`claude --resume <session id> --model claude-opus-5-5 --effort xhigh --autocompact 400k`。resume 不保證沿用開啟時的旗標（effort 會重置為預設）；前任 `59660bf2` 11/13 重啟後沒有再壓縮，context 到 793,547、該 session 67% 的成本花在 400K 以上（#708，推測是沒帶 `--autocompact`）。沒帶時還有統籌手冊[「統籌換手」](../COORDINATOR.md#無人值守運作)的 context 門檻（450K）兜底。

## 換手偵測

壓縮次數只算統籌主對話的壓縮（#811），不靠模型記得。`patrol.sh` 第一步寫心跳檔（`session_id`、`terminal_handle`、`written_at`），第二步以 [`session_cost.py`](../../tools/ops/session_cost.py) `compactions` 數自己主 transcript 裡 `isSidechain` 不是 true 的 `compact_boundary` 列（紀錄檔的找法與下面的 context 相同）；子代理的 transcript（`<session id>/subagents/`）不讀。repo 的 PreCompact hook（`.claude/settings.json` → `tools/ops/compact_hook.sh`）照舊把每次壓縮計入 `<資料目錄>/logs/compactions/<session id>.count`、在同目錄的 `<session id>.log` 記一列時間、`trigger` 與 `agent_id`（主對話記 `agent_id=none`，子代理記 `agent_id=<id> agent_type=<類型>`）；子代理壓縮時 hook 收到的是父 session 的 `session_id`，所以這個計數含子代理，工程師 session 也寫。兩邊不同時表頭另印 hook 的數字，例如「壓縮 1 次（hook 記 2 次，含子代理）」；紀錄檔讀不到或讀不懂時改用 hook 計數並註明「（hook 計數，可能含子代理；紀錄檔未讀到：原因）」，不當成 0 次。`compact_boundary` 在壓縮真正套用時才寫入，比 hook 晚（前任 `0e58cba6` 那次晚約 11 分鐘），這段時間表頭的次數還沒加上。達 2 次時表頭印「已達換手條件」，最後一行再印一次，並以 exit 10 結束（`| tail -1` 或只看結束碼也看得到）。同一步也讀自己最後一次呼叫的 context（#710）：[`session_cost.py`](../../tools/ops/session_cost.py) `context` 從紀錄檔尾往回找最後一筆非 sidechain、非 `<synthetic>`、有 `usage` 的 assistant 列，context＝input＋cache 讀＋cache 寫；紀錄檔依序找 `$CLAUDE_CONFIG_DIR/projects/*/<session id>.jsonl`、`$HOME/.claude/projects/*/<session id>.jsonl`，同一個 id 有多個檔取最後修改的，`--transcript`／`STOCK_TRANSCRIPT` 可直接指定。表頭在「壓縮 N 次」下一行印 `context：<數字>（門檻 <門檻>，<百分比>）（<紀錄檔路徑>）`；超過門檻（預設 450,000，環境變數 `STOCK_CONTEXT_LIMIT` 可改）與壓縮 2 次並列為換手條件，同樣最後一行印出、exit 10。紀錄檔讀不到或讀不懂時只印 `context：未讀到（原因；連續 N 次）`，不擋巡邏、exit code 不變；連續次數記在同目錄的 `<session id>.context-misses`，讀到就刪，連續 3 次以上在最後一行前加印「context 已連續 N 次讀不到」（#710 決定 6877357244）。任一條件成立、或自覺對不上 Issue 與文件，就換手。量接手本身加了多少 context 用 `"$STOCK_PYTHON" -X utf8 tools/ops/session_cost.py takeover <session id（前 8 碼以上）或紀錄檔路徑>…`（#803）。它印三個點的 context：第 1 次呼叫；印出 `"ok":true` 那次 `take_over.sh` 工具結果之後的呼叫（失敗後以 `--from` 續跑時是第 2 次以後；`--closed-only` 與只讀檔的 `sed`、`grep` 不算執行）；其後第一個 `patrol.sh` 工具結果之後的呼叫（`--heartbeat-only` 不算；與那次 `take_over.sh` 同一個命令或同一批結果時，第三點等於第二點）。另印第 1 次呼叫到第三個點之間，工具結果依讀取對象分組（repo 檔逐檔、#1、其他 Issue／PR、兩支腳本的輸出、統籌自己的輸出）的位元組、context 增量與位元組／token。任一點找不到時只印缺哪一個、exit 5。

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

- **工程師 terminal 與 resume**（#595）：工程師的 terminal 是 `dispatch.sh` 回報的 handle，也就是 `orca terminal list --json` 裡 `paneTitle` 是 `#<issue> <slug>` 的那個。同一個 worktree 另有 Orca 自動建的裸 shell terminal，它停在 `$` 不代表 session 退出；`lastOutputAt` 會被畫面重繪推進，`preview` 尾端是輸入框的建議草稿，都不能當成工作中或閒置的證據。resume 前先確認沒有該任務的 claude 程序（`Get-CimInstance Win32_Process -Filter "Name='claude.exe'"` 的命令列帶 `--add-dir …/t<issue>/task` 或 `--resume <id>`）；有就是 session 還在，回到它的 terminal，不另開，否則同一個 session id 會有兩個程序。確定沒有才在 dispatch 回報的 terminal（不在了就新開一個）照[本機檢查](../WORKFLOW.md#本機檢查)的 resume 命令接回。
