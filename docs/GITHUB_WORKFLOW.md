# GitHub 工作手冊

[AGENTS](../AGENTS.md) 管角色與原則，本文管操作細節與模板。

## 欄位與唯一來源

| 資訊 | 位置 |
| --- | --- |
| 產品方向、版本範圍、已完成能力 | [ROADMAP](ROADMAP.md) |
| 前端視覺與互動 | [DESIGN_SYSTEM](DESIGN_SYSTEM.md) |
| 任務目標、範圍、AC、決策、結果 | Issue 本文與留言 |
| 版本任務集合 | GitHub milestone（V1） |
| 狀態 | Project 看板 Status：待辦／進行中／Review／完成 |
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
3. **實作**：只改任務需要的檔案；共用檔案（如 `frontend/src/App.tsx`、`backend/app/api.py`）改動前先看是否有其他進行中的任務也在改，有就在 Issue 協調。
4. **本機檢查**：見下節；全部通過才開 PR。
5. **PR**：套 [PR 模板](../.github/pull_request_template.md)，`Closes #<issue>`，附驗證結果與截圖（前端）。看板設 Review。
6. **Review 與合併**：見下節。合併後 master CI 綠 → Issue 自動關閉、看板完成；統籌刪遠端 branch、`orca worktree rm`。

## 本機檢查

| 範圍 | 命令 |
| --- | --- |
| 後端 | `python -m pytest backend/tests -q`；`ruff check backend`；`ruff format --check backend` |
| 前端 | `pnpm --dir frontend test`；`pnpm --dir frontend build`；`pnpm --dir frontend lint`（若有） |
| 文件／repo | `python tools/ci/checks.py repository --base <完整 master SHA>` |

Python 用 `C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`（PATH 上的 python 是 Store stub）。依賴與資料路徑見 [development-baseline](development-baseline/README.md) 與 [OPERATIONS](OPERATIONS.md)。

## Review 與合併

- PR 必須 CI 全綠（`.github/workflows/ci.yml`）。
- 統籌 review 重點：AC 是否逐條有驗證、文件是否同步、是否遵守 DESIGN_SYSTEM、有沒有寫死色碼／路徑／金鑰、測試是否覆蓋邊界。
- 以下情況加一次獨立 review（`/code-review` 或另開 session）：新資料管線、策略或指標公式、DB migration、排程。
- 合併用 merge commit，不 squash／rebase；衝突由 PR 作者在自己 branch 解決。
- master CI 紅：先修 master（fix-forward PR），修好前不合併其他 PR。

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

V1 的每日排程在本機以 Windows 工作排程器執行 `python -m backend.worker.cli daily` 與新聞任務；設定方式與日誌位置寫在 [OPERATIONS §8](OPERATIONS.md#8-排程)。排程失敗以 Issue 追蹤。
