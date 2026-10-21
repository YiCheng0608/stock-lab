# GitHub 工作手冊

[AGENTS](../AGENTS.md) 管角色與原則，本文管操作細節與模板。

## 欄位與唯一來源

| 資訊 | 位置 |
| --- | --- |
| 程式與文件 | [YiCheng0608/stock-lab](https://github.com/YiCheng0608/stock-lab)，正式 branch `master`；[主線規則](https://github.com/YiCheng0608/stock-lab/rules/24769026)要求 PR、只允許 merge commit、禁止強推，required check 為 CI 的 `required` |
| 產品方向、版本範圍、已完成能力 | [ROADMAP](ROADMAP.md) |
| 前端視覺與互動 | [DESIGN_SYSTEM](DESIGN_SYSTEM.md) |
| 任務目標、範圍、AC、決策、結果 | Issue 本文與留言 |
| 版本任務集合 | [V1 milestone](https://github.com/YiCheng0608/stock-lab/milestone/1) |
| 狀態 | [產品開發看板](https://github.com/users/YiCheng0608/projects/1) Status：待辦／開發中／待整合／完成（「測試中」不使用） |
| 使用者層級決策 | [治理 Issue #1](https://github.com/YiCheng0608/stock-lab/issues/1) 留言 |

Issue 標題前綴：`[任務]` 可直接開工的工作、`[功能]` 多任務的母單、`[候選]` 想法或 bug 尚未排程。母子關係用 GitHub 原生 sub-issue，依賴寫在 Issue 本文。

## 版本範圍與完成判定

ROADMAP 的 V1 基線列出七個 gate（V1-G1～G7）；每個 gate 由一到數張任務 Issue 承接，統籌在建單時於本文寫明對應 gate。V1 完成的判定是 G7 發布驗收通過，不是 Issue 關閉數。

## 資料與功能拆線

資料（排程、collector、DB）與功能（指標、API、UI）可拆成不同任務並行；功能任務先用小 fixture 開發，接真實資料是整合步驟，寫在 AC 裡。

## 分流

開工前依序問，第一個答「是」就停：

1. 改到[高風險路徑](../tools/ci/checks.py)（`HIGH_RISK_PATHS`，清單只在該處維護）嗎？是：完整流程（Issue、AC、worktree），PR 加 `independent-review` label，AC 含正式 DB 唯讀副本實測。
2. 改到 `backend/app/`、`backend/worker/`、`backend/alembic/`、`backend/data/`、`frontend/src/` 的非測試檔嗎？是：Issue、AC、worktree；小的統籌可自做。
3. 其餘（文件、流程檔、`tools/ci/`、純測試改動）：可直接開 PR 不建 Issue，驗證欄寫 CI；規模大仍可建 Issue。

另兩條與大小無關：要拆成多張就開 `[功能]` 母單；碰到共用檔案且有任務進行中，先在 Issue 協調（[任務流程](#任務流程)第 3 步）。第 1、2 類由 CI 的 `pr` 檢查（規則 a、d，見 [Review 與合併](#review-與合併)）擋下沒有 `Closes #<issue>` 或缺 label 的 PR。

## 任務流程

1. **建單**：套 [任務模板](../.github/ISSUE_TEMPLATE/task.md)，填目標、範圍、AC、依賴、對應 gate；套 milestone；看板設待辦。
2. **開工**：統籌以 Orca 從最新 `origin/master` 建 worktree，branch `task/<issue>-<slug>`：

   ```text
   orca worktree create --repo id:<repoId> --name task-<issue>-<slug> --no-parent --setup skip --json
   git -C <path> branch -m <orca-branch> task/<issue>-<slug>
   orca terminal create --worktree id:<repoId>::<path> --title "#<issue> <slug>" --command "claude --model <model> --effort <effort>" --json
   orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json
   orca terminal send --terminal <handle> --text "<任務全文：Issue 連結、AC、白名單、驗證方式>" --enter --json
   ```

   看板設開發中。工程師接手後在 Issue 留一則「開工」留言（session、branch、HEAD）。
   派工後統籌保持一個背景監看（每分鐘查 `gh pr list` 的新 PR 與 repo 層級 `issues/comments?since=` 的新留言），直到所有進行中任務結案；監看到期就重掛，換統籌 session 時由新 session 重掛。工程師的提問與回報只寫在 Issue 留言，不依賴口頭通知。反方向：工程師 session 不會自己查 GitHub，統籌在 Issue／PR 留言給工程師（review 意見、回覆提問、決定）後，必須對該工程師 terminal 送一句短通知並附留言連結，再讀回確認已開始處理；內容以留言為準，terminal 只用來喚醒。
3. **實作**：只改任務需要的檔案；共用檔案（如 `frontend/src/App.tsx`、`backend/app/api.py`）改動前先看是否有其他進行中的任務也在改，有就在 Issue 協調。
4. **本機檢查**：見下節；全部通過才開 PR。
5. **PR**：套 [PR 模板](../.github/pull_request_template.md)（`gh pr create --body-file` 不會自動帶入模板，先複製模板再填），`Closes #<issue>`，附驗證結果與截圖（前端）。看板設待整合。
6. **Review 與合併**：見下節。合併後 master CI 綠 → Issue 自動關閉、看板完成；遠端 branch 由 GitHub 自動刪（repo 設定 `delete_branch_on_merge`）；統籌關工程師 terminal、刪本地 branch、`orca worktree rm --force`（殘留目錄再手動刪）、刪工程師在 worktree 外建立的暫存目錄（PR 本文須寫出路徑）、刷新程式索引；Issue 有「統籌承諾」留言時依承諾的順序與時點清理。同類錯誤第二次發生時，另建一張 `[任務]` 把它編成會失敗的檢查（[#228](https://github.com/YiCheng0608/stock-lab/issues/228) 的 skill），並更新 [AGENTS](../AGENTS.md#規則與強制手段) 對照表。

## 本機檢查

| 範圍 | 命令 |
| --- | --- |
| 後端 | `python -m pytest backend/tests -q`；`ruff check backend tools`；`ruff format --check backend tools`（repo 根目錄執行，設定在 [`ruff.toml`](../ruff.toml)，CI 同命令） |
| 前端 | `pnpm --dir frontend test:ci`；`pnpm --dir frontend build` |
| 文件／repo | `python tools/ci/checks.py repository --base <完整 master SHA>` |

每個 checkout 設一次 `git config blame.ignoreRevsFile .git-blame-ignore-revs`，`git blame` 會略過 [`.git-blame-ignore-revs`](../.git-blame-ignore-revs) 列出的全檔格式化 commit。

Python 用 `C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`（PATH 上的 python 是 Store stub）。後端依賴依 `backend/requirements.txt` 安裝，並以 `backend/validation-requirements.lock.txt` 為 constraints（與 CI 相同）；資料路徑見 [OPERATIONS](OPERATIONS.md)。

## Review 與合併

- PR 必須 CI 全綠（`.github/workflows/ci.yml`）。CI 的 `pr` 檢查（[`tools/ci/checks.py`](../tools/ci/checks.py) `pr` 模式）讀 PR 本文、label 與 commit 訊息；改本文或 label 會自動重跑：
  - a. 改到[分流](#分流)第 1、2 類路徑，本文要有 `Closes #<issue>`。
  - b. 本文「AC 逐條結果」的每一條 AC 後面要有內容；第 1、2 類 PR 必須有這一區。
  - c. 改到 `frontend/src/` 的非測試檔，本文要有圖片或 `pr-assets` 連結。
  - d. 改到 `HIGH_RISK_PATHS`，PR 要有 `independent-review` label。
  - e. commit 訊息不得有 closing keyword（`Fix #N`、`Closes #N`、`Resolves #N` 等）：commit 一進 master 就會關 Issue，早於結案步驟。
- 統籌 review 重點：AC 是否逐條有驗證、文件是否同步、是否遵守 DESIGN_SYSTEM、有沒有寫死色碼／路徑／金鑰、測試是否覆蓋邊界。AC 證據必須是命令與輸出、查詢結果或截圖連結，只寫「通過」不算。
- 改到 [`HIGH_RISK_PATHS`](../tools/ci/checks.py) 的 PR 加一次獨立 review（`/code-review` 或另開 session）並加 `independent-review` label。獨立 review 要寫出「這個變更安全是因為哪一個事實」，以及證明它的方式（命令與輸出、查詢或測試名稱）。
- 合併用 merge commit，不 squash／rebase；衝突由 PR 作者在自己 branch 解決。主線規則要求 PR 分支跟上 master：master 前進後統籌以 `gh api -X PUT repos/YiCheng0608/stock-lab/pulls/<n>/update-branch -f expected_head_sha=<head>` 把 master 併入（merge commit），CI 重跑綠再合併。
- master CI 紅：先修 master（fix-forward PR），修好前不合併其他 PR。

## 統籌 session

同時只有一個統籌，開啟一律由 agent 執行，使用者不手動開：現任統籌觸發換手時自己開；統籌不在時使用者對任一 Claude session 說「開統籌」。開啟者先讀心跳檔 `<資料目錄>/logs/coordinator-heartbeat.json`（資料目錄見 [OPERATIONS §6](OPERATIONS.md#6-排程)）：心跳在 60 分鐘內就不開，改對心跳記的 handle 送一句「請寫心跳檔並依手冊巡檢」；否則在 `master` 管理 checkout 開可見 terminal：

```text
orca terminal create --worktree id:<repoId>::<master 路徑> --title "統籌" --command "claude --model claude-opus-5-5 --effort medium --autocompact 400k" --json
orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json
orca terminal send --terminal <handle> --text "<接手文>" --enter --json
orca terminal rename --terminal <handle> --title "統籌" --json
```

`--autocompact 400k` 把自動壓縮視窗設在 400K，不等到模型上限才壓縮。標題只是給人看的，存活判定一律用心跳檔。接手文固定如下，開啟者原文送出，心跳記的舊 terminal 已不存在時刪掉最後一句；開啟者若不是統籌本人，開完只回報 handle，不再對 repo 寫入：

```text
你是 stock-lab 的統籌。先讀 AGENTS.md、docs/GITHUB_WORKFLOW.md、docs/ROADMAP.md、治理 Issue #1 本文的決策索引與最近 10 則留言、所有 open Issues 與 PR、最近 48 小時內關閉的 Issue 與合併的 PR 的最後一則留言。接著：寫心跳檔；掛 GitHub 背景監看（since 取接手前 1 小時）與定時巡檢（手冊「無人值守運作」）；在 #1 留言「統籌 session 更換：<terminal handle>／<session id>」並更新 #1 本文的現任統籌；回覆所有最後一則是工程師提問且無統籌回覆的 Issue；兌現前任在 Issue 標「統籌承諾」的事；核對前任標「已完成」的事，不只接續；然後依手冊推進。回覆使用者一律繁體中文。舊統籌 terminal 為 <舊 handle>，用 orca terminal wait --for tui-idle 確認它閒置後以 orca terminal close 關掉它。
```

**自動換手機制**（統籌 session 自己執行，不需要人在場）：

1. 偵測：壓縮次數由 repo 的 PreCompact hook（`.claude/settings.json` → `tools/ops/compact_hook.sh`）自動寫進 `<資料目錄>/logs/compactions/<session id>.count`，不靠模型記得。巡檢第一步寫心跳檔（`session_id`、`terminal_handle`、`written_at`），第二步讀自己的計數檔；達 2 次、或自覺對不上 Issue 與文件，就換手。
2. 執行：先寫換手標記 `<資料目錄>/logs/handoff-<session id>.json`（舊 handle、時間），停掉自己的巡檢 cron 與監看，之後不再合併、派工、留言；再照上面四行開新 session 並送接手文（含自己的 handle）。
3. 接回：新 session 15 分鐘內未在 #1 留言，舊統籌刪標記檔、重掛監看與巡檢，在 #1 記「換手失敗：<新 handle>」，下次巡檢再試。
4. 收尾：新統籌在 #1 留言並寫心跳檔後，確認舊 terminal 閒置再關掉它。
5. 換手不通知工程師：工程師的回報與提問一律在 Issue／PR 留言，不送到統籌 terminal；新統籌啟動時讀所有 open Issue 與 PR 並重掛監看，換手前後的留言都由它接續。新統籌之後給工程師的留言仍照[開工](#任務流程)的反方向規則通知 terminal。

## 無人值守運作

使用者不在時統籌照本節持續推進；使用者回來只看 [#1](https://github.com/YiCheng0608/stock-lab/issues/1) 本文與看板。

- **事件與巡檢**：派工後的 GitHub 監看（見[開工](#任務流程)）之外，統籌在自己的 session 掛每 20～30 分鐘一次的巡檢，固定順序：寫心跳檔 → 讀計數檔與換手標記 → 監看是否存活 → open PR 的 CI 與合併 → 進行中 Issue 的提問 → 名額空缺就派工 → 背景工作是否卡住。監看到期重掛時 `since` 取上次監看啟動時間，不取現在。
- **待辦隊列**：下一輪任務先建成 Issue（看板待辦），依 ROADMAP gate 順序排；並行名額（3）一空就從最新 `origin/master` 派下一張。沒有已建 Issue 就先建，不停擺。台北 18:30～21:30 是排程 `daily` 時段：不派新工、不跑全套 pytest、不跑全市場 analyze。
- **需要使用者的事**（來源與付費、刪資料、部署、對外操作、範圍變更、正式資料位置）：在 #1 留言寫清楚問題與統籌建議，標「待使用者」，轉做不受影響的工作；不猜答案、不停工。
- **決策落地**：會影響後續判斷的使用者決定，當下寫進 #1 留言並同步更新 #1 本文的決策索引（只列仍有效的決策、待使用者事項與現任統籌，每條附留言連結）。
- **統籌承諾**：統籌對工程師做出偏離手冊的承諾（例如合併後先不清 worktree）時，在該 Issue 的留言開頭標「統籌承諾」；換手後由新統籌兌現。
- **統籌換手**：觸發條件任一成立就換：同一 session 已自動壓縮兩次以上；統籌自覺回答對不上 Issue 與文件；使用者要求。偵測與執行步驟見[統籌 session](#統籌-session)的自動換手機制。
- **前提與限制**：本機與 Orca 保持開機登入；訂閱額度由統籌、工程師與 LLM 批次共用，額度用盡時全部暫停到重置，不視為失敗；合併把關為 CI＋統籌 review＋高風險項獨立 review。

## 失敗處理

| 類型 | 處置 |
| --- | --- |
| 產品缺陷 | 同 PR 修正並補測試 |
| 測試工具／環境 | 修環境或在 Issue 記錄限制；不刪測試湊綠 |
| 外部來源失敗（限流、改版） | 在 Issue 記來源、時間、錯誤；程式要能重跑且不寫壞資料 |
| AC 做不到 | Issue 說明原因與替代，統籌決定拆分、延後或請使用者決策 |

## 程式索引

每個 worktree 用 codebase-memory 建索引（project 名稱含 worktree 名）；合併後統籌刷新 master 索引並刪任務索引。MCP 斷線用同引擎 CLI `C:/Users/YiCheng/.local/bin/codebase-memory-mcp.cmd cli --json <tool>`。索引只是查找工具，不當驗收證據。

## 排程

V1 的每日排程在本機以 Windows 工作排程器執行 `python -m backend.worker.cli daily` 與新聞任務；設定方式與日誌位置寫在 [OPERATIONS §6](OPERATIONS.md#6-排程)。排程失敗以 Issue 追蹤。
