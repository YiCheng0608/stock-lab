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
| 狀態 | [產品開發看板](https://github.com/users/YiCheng0608/projects/1) Status：待辦／進行中／Review／完成 |
| 使用者層級決策 | [治理 Issue #1](https://github.com/YiCheng0608/stock-lab/issues/1) 留言 |

Issue 標題前綴：`[任務]` 可直接開工的工作、`[功能]` 多任務的母單、`[候選]` 想法或 bug 尚未排程。母子關係用 GitHub 原生 sub-issue，依賴寫在 Issue 本文。

## 版本範圍與完成判定

ROADMAP 的 V1 基線列出七個 gate（V1-G1～G7）；每個 gate 由一到數張任務 Issue 承接，統籌在建單時於本文寫明對應 gate。V1 完成的判定是 G7 發布驗收通過，不是 Issue 關閉數。

## 資料與功能拆線

資料（排程、collector、DB）與功能（指標、API、UI）可拆成不同任務並行；功能任務先用小 fixture 開發，接真實資料是整合步驟，寫在 AC 裡。

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

   看板設進行中。工程師接手後在 Issue 留一則「開工」留言（session、branch、HEAD）。
   派工後統籌保持一個背景監看（每分鐘查 `gh pr list` 的新 PR 與 repo 層級 `issues/comments?since=` 的新留言），直到所有進行中任務結案；監看到期就重掛，換統籌 session 時由新 session 重掛。工程師的提問與回報只寫在 Issue 留言，不依賴口頭通知。
3. **實作**：只改任務需要的檔案；共用檔案（如 `frontend/src/App.tsx`、`backend/app/api.py`）改動前先看是否有其他進行中的任務也在改，有就在 Issue 協調。
4. **本機檢查**：見下節；全部通過才開 PR。
5. **PR**：套 [PR 模板](../.github/pull_request_template.md)，`Closes #<issue>`，附驗證結果與截圖（前端）。看板設 Review。
6. **Review 與合併**：見下節。合併後 master CI 綠 → Issue 自動關閉、看板完成；統籌關工程師 terminal、刪遠端與本地 branch、`orca worktree rm --force`（殘留目錄再手動刪）、刪工程師在 worktree 外建立的暫存目錄（PR 本文須寫出路徑）、刷新程式索引。

## 本機檢查

| 範圍 | 命令 |
| --- | --- |
| 後端 | `python -m pytest backend/tests -q`；`ruff check backend`；`ruff format --check backend` |
| 前端 | `pnpm --dir frontend test:ci`；`pnpm --dir frontend build` |
| 文件／repo | `python tools/ci/checks.py repository --base <完整 master SHA>` |

Python 用 `C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`（PATH 上的 python 是 Store stub）。後端依賴依 `backend/requirements.txt` 安裝，並以 `backend/validation-requirements.lock.txt` 為 constraints（與 CI 相同）；資料路徑見 [OPERATIONS](OPERATIONS.md)。

## Review 與合併

- PR 必須 CI 全綠（`.github/workflows/ci.yml`）。
- 統籌 review 重點：AC 是否逐條有驗證、文件是否同步、是否遵守 DESIGN_SYSTEM、有沒有寫死色碼／路徑／金鑰、測試是否覆蓋邊界。
- 以下情況加一次獨立 review（`/code-review` 或另開 session）：新資料管線、策略或指標公式、DB migration、排程。
- 合併用 merge commit，不 squash／rebase；衝突由 PR 作者在自己 branch 解決。主線規則要求 PR 分支跟上 master：master 前進後統籌以 `gh api -X PUT repos/YiCheng0608/stock-lab/pulls/<n>/update-branch -f expected_head_sha=<head>` 把 master 併入（merge commit），CI 重跑綠再合併。
- master CI 紅：先修 master（fix-forward PR），修好前不合併其他 PR。

## 統籌 session

同時只有一個統籌，開啟一律由 agent 執行，使用者不手動開：現任統籌觸發換手時自己開；沒有統籌時使用者對任一 Claude session 說「開統籌」，該 session 執行同一組指令。都在 `master` 管理 checkout 開可見 terminal：

```text
orca terminal create --worktree id:<repoId>::<master 路徑> --title "統籌" --command "claude --model claude-opus-5-5 --effort medium --autocompact 400k" --json
orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json
orca terminal send --terminal <handle> --text "<接手文>" --enter --json
```

`--autocompact 400k` 把自動壓縮視窗設在 400K，不等到模型上限才壓縮。接手文固定如下，開啟者原文送出：

```text
你是 stock-lab 的統籌。先讀 AGENTS.md、docs/GITHUB_WORKFLOW.md、docs/ROADMAP.md、治理 Issue #1 的最新決策、所有 open Issues 與 PR。接著：掛 GitHub 背景監看與定時巡檢（手冊「無人值守運作」）；在 #1 留言「統籌 session 更換：<terminal handle>／<session id>」；然後依手冊推進進行中與待辦任務。回覆使用者一律繁體中文。
```

## 無人值守運作

使用者不在時統籌照本節持續推進；使用者回來只看 [#1](https://github.com/YiCheng0608/stock-lab/issues/1) 與看板。

- **事件與巡檢**：派工後的 GitHub 監看（見[開工](#任務流程)）之外，統籌在自己的 session 掛每 20～30 分鐘一次的巡檢：監看是否存活、open PR 的 CI 與合併、進行中 Issue 的提問、名額空缺就派工、背景工作是否卡住。兩者到期或 session 更換時重掛。
- **待辦隊列**：下一輪任務先建成 Issue（看板待辦），依 ROADMAP gate 順序排；並行名額（3）一空就從最新 `origin/master` 派下一張。沒有已建 Issue 就先建，不停擺。
- **需要使用者的事**（來源與付費、刪資料、部署、對外操作、範圍變更）：在 #1 留言寫清楚問題與統籌建議，標「待使用者」，轉做不受影響的工作；不猜答案、不停工。
- **決策落地**：會影響後續判斷的使用者決定，當下寫進 #1 或對應文件，不留在對話。
- **統籌換手**：觸發條件任一成立就換：同一 session 已自動壓縮兩次以上；統籌自覺回答對不上 Issue 與文件；使用者要求。做法與[開啟統籌 session](#統籌-session)相同，由現任統籌執行；新 session 在 #1 留言後，舊 session 停止對 repo 的所有操作。不寫交接文件、不設任期。
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
