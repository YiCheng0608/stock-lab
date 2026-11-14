<!-- owns: 任務檔模板 -->
<!-- 用法見 [模板清單](README.md)。統籌複製到 worktree 外的 `$HOME/t<issue>/task/task.md`（UTF-8，不經 PowerShell 管線），把 <…> 換成實際內容、刪掉這兩行註解，再跑 dispatch.sh。不適用的項目寫「無」，不要整區刪掉。 -->
# 任務 #<issue>：<標題>

- Issue：https://github.com/YiCheng0608/stock-lab/issues/<issue> （AC 共 <N> 條：AC-1～AC-<N>，以 Issue 本文為準）
- branch：`task/<issue>-<slug>`（dispatch.sh 已從最新 `origin/master` 建好；子單寫 `--base` 的分支）
- 模型：`<model>`／`<effort>`。你是工程師，照 AGENTS.md 與 docs/WORKFLOW.md「任務流程」做。
- 依據：<使用者決定或 #1 留言連結；沒有寫「無」>

## 先讀

1. Issue #<issue> 本文（現況、範圍、<N> 條 AC）與相關留言。
2. <要讀的規格與文件，例如 docs/DESIGN_SYSTEM.md、docs/DATA_SOURCES.md 某節>
3. <要讀的程式：檔案與函式>
4. <相關的已合併任務：Issue／PR 編號與它做了什麼>

## 要做的事

- <逐條寫要改的行為；與 Issue 範圍一致，不加新範圍>
- 查程式：codebase-memory 用 master 索引（project `C-Users-YiCheng-Desktop-taiwan-stock-research`，從 `origin/master` 派工時 dispatch.sh 已把它更新到你的起點並驗證；`--base` 子單的索引只對得上 master）；不要對自己的 worktree 跑 `index_repository`；自己改過的檔以 worktree 內的實際檔案為準（docs/WORKFLOW.md「程式索引」）。
- 文件：<同 PR 要更新的文件>
- UI 任務：更新 `.claude/skills/verify-stock-lab/features/` 對應的檔，或寫明不需更新。

## 白名單（可改的檔）

<檔案或目錄清單>。要改其他檔先在 Issue 留 `提問：`。改到 `HIGH_RISK_PATHS`（`tools/ci/checks.py`）時 PR 加 `independent-review` label。

## 驗證

- 每條 AC 的驗法：<單元測試（記憶體 DB、小 fixture，舊程式紅新程式綠）、正式 DB 唯讀副本實測、截圖等>
- 本機檢查：容器（compose project `task-<issue>`）跑改動相關的後端測試檔（<檔名>）、`ruff check`、`ruff format --check`，以及前端 test 與 build；全套後端 pytest 由 PR CI 跑，本機不跑（docs/WORKFLOW.md「本機檢查」）。改檔後 `compose run` 加 `--build`。
- 正式 DB 唯讀副本（需要時）：docs/ops/LOCAL.md「取正式 DB 的唯讀副本」，放進 `task-<issue>_` 開頭的 Docker volume，新 volume 先 chown 1000。
- 台北 21:30～23:30 是 daily 時段：不做吃記憶體的 `docker build`。
- 部署後才能驗的 AC：PR 標「待部署」，由統籌做。

## 回報

- 開工後在 Issue 留一則 `回報：開工`：session、branch、HEAD、任務檔路徑，以及本檔的 Issue 連結與 AC 數（<N>）。
- 之後的提問與回報照 docs/WORKFLOW.md「留言類型」寫在 Issue／PR 留言（第一行是 `提問：`／`回報：`），不送到統籌 terminal。
- 背景工作被系統停掉、或任何要等統籌才能繼續的情況，以 `提問：` 留在 Issue，不在 terminal 等。
- PR 本文照抄 `docs/templates/pull-request.md`，要有 `Closes #<issue>`；worktree 外暫存目錄寫 `C:/Users/YiCheng/t<issue>`。
- pytest 的 `--basetemp` 用 `C:/Users/YiCheng/t<issue>/b1` 這類路徑，不要放在 `task/` 底下。
