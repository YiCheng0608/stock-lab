<!-- owns: 統籌 session、接手文、統籌換手、無人值守運作 -->
# 統籌手冊

統籌接手時固定讀 [AGENTS](../AGENTS.md) 與本文（[接手文](#統籌-session)）；其他文件依手上的事再讀：

- 建單、派工、本機檢查、review、合併、結案、留言類型、長期整合分支：[WORKFLOW](WORKFLOW.md)。
- 排下一張任務、判斷範圍與 gate、更新產品方向：[ROADMAP](ROADMAP.md)；已完成能力：[CAPABILITIES](CAPABILITIES.md)。
- review 改到檢查、hook 或 CI 的 PR，規則表要補列，或查某條規則由什麼擋：[GUARDRAILS](GUARDRAILS.md)。
- 發佈與部署：[RELEASE](RELEASE.md)。

## 統籌 session

同時只有一個統籌，開啟一律由 agent 執行，使用者不手動開：現任統籌觸發換手時自己開；統籌不在時使用者對任一 Claude session 說「開統籌」。開啟者先讀心跳檔 `<資料目錄>/logs/coordinator-heartbeat.json`（資料目錄見 [排程](ops/SCHEDULING.md)）：心跳在 60 分鐘內就不開，改對心跳記的 handle 送一句「請跑 bash tools/ops/patrol.sh 處理事件佇列」；否則在 `master` 管理 checkout 開可見 terminal：

```text
orca terminal create --worktree id:<repoId>::<master 路徑> --title "統籌" --command "claude --model claude-opus-5-5 --effort medium --autocompact 400k" --json
orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json
orca terminal send --terminal <handle> --text "<接手文>" --enter --json
orca terminal rename --terminal <handle> --title "統籌" --json
```

`--autocompact 400k` 把自動壓縮視窗設在 400K，不等到模型上限才壓縮。標題只是給人看的，存活判定一律用心跳檔。接手文固定如下，開啟者原文送出，心跳記的舊 terminal 已不存在時刪掉最後一句；開啟者若不是統籌本人，開完只回報 handle，不再對 repo 寫入：

```text
你是 stock-lab 的統籌。先讀 AGENTS.md、docs/COORDINATOR.md、治理 Issue #1 本文的決策索引與最近 10 則留言、所有 open Issues 與 PR、最近 48 小時內關閉的 Issue 與合併的 PR 的最後一則留言。接著：跑 bash tools/ops/wake_listener_start.sh（wake listener 沒在跑就啟動），再跑 bash tools/ops/patrol.sh（寫心跳檔、列出事件佇列），處理未處理的事件，處理完以 --done 標記（docs/COORDINATOR.md「無人值守運作」）；在 #1 留言「統籌 session 更換：<terminal handle>／<session id>」並更新 #1 本文的現任統籌；以 `決定：` 回覆 patrol.sh 列出的每一則未回覆的提問，以及沒有類型的舊格式提問；兌現前任 `統籌承諾：` 留言的事；核對前任標「已完成」的事，不只接續；然後依手冊推進。回覆使用者一律繁體中文。舊統籌 terminal 為 <舊 handle>，用 orca terminal wait --for tui-idle 確認它閒置後以 orca terminal close 關掉它。
```

**自動換手機制**（統籌 session 自己執行，不需要人在場）：

1. 偵測：壓縮次數由 repo 的 PreCompact hook（`.claude/settings.json` → `tools/ops/compact_hook.sh`）自動寫進 `<資料目錄>/logs/compactions/<session id>.count`，每次壓縮的時間另記一列在同目錄的 `<session id>.log`，不靠模型記得；工程師 session 也寫，統籌的是心跳檔記的 session id 那份。`patrol.sh` 第一步寫心跳檔（`session_id`、`terminal_handle`、`written_at`），第二步讀自己的計數檔；達 2 次、或自覺對不上 Issue 與文件，就換手。
2. 執行：先寫換手標記 `<資料目錄>/logs/handoff-<session id>.json`（舊 handle、時間），之後不再合併、派工、留言；再照上面四行開新 session 並送接手文（含自己的 handle）。
3. 接回：新 session 15 分鐘內未在 #1 留言，舊統籌刪標記檔、照常處理事件佇列，在 #1 記「換手失敗：<新 handle>」，下次處理佇列時再試。
4. 收尾：新統籌在 #1 留言並寫心跳檔後，確認舊 terminal 閒置再關掉它，然後再跑一次 `bash tools/ops/wake_listener_start.sh`：舊統籌啟動的 wake listener 跟著它的 terminal 結束，換由新統籌啟動（[統籌事件 monitor](ops/MONITOR.md)）。
5. 換手不通知工程師：工程師的回報與提問一律在 Issue／PR 留言，不送到統籌 terminal；新統籌啟動時讀所有 open Issue 與 PR 並處理事件佇列（換手前後的留言都在佇列裡），之後 monitor 喚醒的是新心跳記的 terminal。新統籌之後給工程師的留言仍照[開工](WORKFLOW.md#任務流程)的反方向規則通知 terminal。

## 無人值守運作

使用者不在時統籌照本節持續推進；使用者回來只看 [#1](https://github.com/YiCheng0608/stock-lab/issues/1) 本文與看板。

- **事件佇列**：GitHub 與排程狀態由常駐的事件 monitor（[`monitor.sh`](../tools/ops/monitor.sh)，排程與管理見 [統籌事件 monitor](ops/MONITOR.md)）輪詢，不用 LLM；統籌 session 只處理 monitor 送來的事件，不自己輪詢 GitHub、不排定時輪詢的工作，也不自己用 gh 查 PR、CI 或新留言；接手時一次性讀取 open Issue 與 PR（[接手文](#統籌-session)）不在此限。monitor 每輪最多 2 次 gh（open PR 的 CI 與 `mergeStateStatus`、repo 層級新留言）、兩輪至少隔 60 秒（5000 次／小時的限流全帳號共用），另讀 task worktree 數（並行名額）與排程日誌（含看門狗記的 gh 被拒）；新事件去重後寫入 `<資料目錄>/logs/events.jsonl`，並對心跳檔記的統籌 terminal 送一句「有 N 個事件，請處理佇列」，同一事件只喚醒一次。monitor 在 scheduler 容器裡時（#338），佇列與心跳仍是這兩個主機路徑（bind mount），喚醒與 task worktree 數經主機的 wake listener 用本機 orca 執行；listener 沒在跑時喚醒失敗、事件留在佇列，10 分鐘後再試。
- **處理佇列**：被喚醒時（或自己開始一輪工作時）先跑 `bash tools/ops/wake_listener_start.sh`（wake listener 已在跑就什麼都不做），再跑 `bash tools/ops/patrol.sh`：[它](../tools/ops/patrol.sh)寫心跳檔、讀自己的計數檔與換手標記，印出 monitor 的心跳與它最後一輪看到的 open PR 與排程日誌最後一列、[未回覆的提問](WORKFLOW.md#留言類型)、未處理的事件，不讀排程日誌（scheduler 容器的日誌在 volume 裡）。PR、CI 與新留言讀佇列，不呼叫 gh；只有未回覆的提問要讀每個 open Issue 與 PR 的最新留言（Issue 是否已關、`決定：` 連到哪則，佇列的留言事件看不出來），用一次 GraphQL 讀完、不逐一呼叫，gh 呼叫最多 `--max-gh` 次（預設 1；0 或到上限時印「未查完」，其他輸出照常）。patrol 只在統籌被喚醒或開始一輪工作時跑一次，不是輪詢。open Issue 或 PR 超過 100 個、單一 Issue 留言超過 100 則時也印「未查完」並寫出沒讀到的範圍。照這個順序處理：open PR 的 CI 與合併 → [未回覆的提問](WORKFLOW.md#留言類型) → 名額空缺就派工 → 背景工作是否卡住；處理完以 `patrol.sh --done <seq>`（到該 seq 為止的未處理事件，含下述不喚醒的事件）或 `--done <事件 id>` 標記。不喚醒的事件另列在「不喚醒的事件」下：統籌用 `comment.sh` 發的留言、PR 離開 open 清單（`pr_gone`）、與同 PR 同 head 的新 CI 結果同一輪出現的 `CLEAN`／`UNSTABLE` merge 狀態；它們照樣記進佇列，但不算未處理、不喚醒，也不計入 60 分鐘「請開統籌」，看過即可，不用處理（#440）。`gh_auth` 事件（GitHub 拒絕容器的 `GH_TOKEN`，看門狗與 monitor 都無法留言）由統籌用本機 gh 在 #1 留言「待使用者」請換 token（[容器內的 claude 與 gh 認證（.env）](ops/SETUP.md#容器內的-claude-與-gh-認證env)），同一台北日只有一個這種事件。心跳檔若屬於另一個 session 且不到 60 分鐘，又沒有它的換手標記，就不覆寫並非 0 結束；確定要接手才加 `--take-over`。
- **統籌留言**：統籌在 Issue／PR（含 #1）留言一律用 `bash tools/ops/comment.sh <Issue 或 PR 編號> --body-file <本文檔>`（[它](../tools/ops/comment.sh)在本文最後加一行不顯示的標記 `<!-- stock-lab:coordinator -->`，印出留言 URL；gh 失敗時非 0 結束、不印 URL），不直接用 `gh issue comment`／`gh pr comment`：所有 session 共用同一個 GitHub 帳號，monitor 只能靠這個標記認出統籌自己的留言、不為它喚醒統籌。本文檔照[留言類型](WORKFLOW.md#留言類型)第一行標類型，寫在 session 的 scratchpad。沒有標記的留言（工程師、使用者、獨立 review）照常喚醒。
- **monitor 的留言**：佇列有事件等了 60 分鐘、這段期間統籌心跳都沒更新時，monitor 在 #1 留言「待使用者：請開統籌」（同一心跳只留一則），不自己開 session（#1 [6245309556](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6245309556)、[6320448594](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6320448594)）。monitor 停擺超過 10 分鐘由看門狗在 #1 留言（[排程看門狗](ops/WATCHDOG.md)）。統籌兌現定時承諾（例如 G7 每日核對）可以排一次性的定時工作，不算輪詢。
- **待辦隊列**：下一輪任務先建成 Issue（看板待辦），依 ROADMAP gate 順序排；並行名額（3）一空就從最新 `origin/master` 派下一張。沒有已建 Issue 就先建，不停擺。台北 18:30～21:30 是排程 `daily` 時段：不派新工、不跑全套 pytest、不跑全市場 analyze，也不做吃記憶體的 `docker build`。
- **需要使用者的事**（來源與付費、刪資料、部署、對外操作、範圍變更、正式資料位置）：在 #1 留言寫清楚問題與統籌建議，標「待使用者」，轉做不受影響的工作；不猜答案、不停工。部署（[`deploy.sh`](RELEASE.md#部署)）與要發佈的 tag 範圍也在這裡：使用者在 #1 明確授權後統籌才執行，授權留言連結寫進 `--operator`；腳本本身不檢查授權。
- **決策落地**：會影響後續判斷的使用者決定，當下寫進 #1 留言並同步更新 #1 本文的決策索引（只列仍有效的決策、待使用者事項與現任統籌，每條附留言連結）。
- **統籌承諾**：統籌對工程師做出偏離手冊的承諾（例如合併後先不清 worktree）時，在該 Issue 留一則 `統籌承諾：` 留言（[留言類型](WORKFLOW.md#留言類型)）；換手後由新統籌兌現。
- **統籌換手**：觸發條件任一成立就換：同一 session 已自動壓縮兩次以上；統籌自覺回答對不上 Issue 與文件；使用者要求。偵測與執行步驟見[統籌 session](#統籌-session)的自動換手機制。
- **前提與限制**：本機與 Orca 保持開機登入（monitor 在容器裡時，喚醒靠統籌 session 啟動的 wake listener，[統籌事件 monitor](ops/MONITOR.md)）；訂閱額度由統籌、工程師與 LLM 批次共用，額度用盡時全部暫停到重置，不視為失敗；合併把關為 CI＋統籌 review＋高風險項獨立 review。
