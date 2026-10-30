<!-- owns: 唯一來源對照、Issue 標題前綴、版本完成判定、資料與功能拆線、分流、任務流程、本機檢查、review 與合併、PR 檢查規則、長期整合分支、統籌 session、無人值守運作、失敗處理、程式索引 -->
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

1. **建單**：套 [任務模板](../.github/ISSUE_TEMPLATE/task.md)，填目標、範圍、AC、依賴、對應 gate；套 milestone；看板設待辦。UI 任務（改五個主導航的頁面）的 AC 固定加一條「更新對應的 [`features/*.md`](../.claude/skills/verify-stock-lab/features/) 或寫明不需更新」。
2. **開工**：統籌把任務全文（Issue 連結、AC、白名單、驗證方式）寫成 UTF-8 檔（不經 PowerShell 管線），放 worktree 外、統籌換手後仍在的目錄（例如 `$HOME/t<issue>/task/task.md`；工程師把 `$HOME/t<issue>/` 列進 PR 本文的 worktree 外暫存目錄，結案時以 `--extra-dir` 刪）。pytest 的 `--basetemp` 要用同一目錄下的另一個子目錄（例如 `$HOME/t<issue>/b1`），因為 pytest 開跑時會清空 basetemp，全綠時也會刪掉它，任務檔不能放在裡面。目錄名不能含 `"`、`$`、反引號、`%`、`!`，dispatch.sh 會拒絕（exit 64）。寫好後跑一行：

   ```text
   bash tools/ops/dispatch.sh <issue> <slug> --task-file <任務全文檔> [--model <model> --effort <effort>] [--base origin/<branch>]
   ```

   [`dispatch.sh`](../tools/ops/dispatch.sh) 先 fetch 再從最新 `origin/master` 建 worktree；子單的 PR 目標是[長期整合分支](#長期整合分支)時加 `--base origin/<該分支>`，fetch 與「新 worktree 的 HEAD 等於最新 base」的核對都改用它。依序等於下列手動命令（模型預設 `claude-opus-5-5`／`high`；`--base-branch` 只在 `--base` 不等於 `origin/master` 時加）：

   ```text
   orca worktree create --repo id:<repoId> --name task-<issue>-<slug> --no-parent --setup skip [--base-branch origin/<branch>] --json
   git -C <path> branch -m <orca-branch> task/<issue>-<slug>
   orca terminal create --worktree id:<repoId>::<path> --title "#<issue> <slug>" --command 'claude --model <model> --effort <effort> --add-dir "<任務檔目錄>"' --json
   orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json
   orca terminal send --terminal <handle> --text "請用 Read 工具讀取任務檔 <path>（UTF-8），依其內容開工；開工留言回貼任務檔裡的 Issue 連結與 AC 數。" --enter --wait-submit 30 --json
   ```

   terminal 只收到這一句，`<path>` 是任務檔的絕對路徑（Windows 寫成 `C:/…`）；任務全文不經 terminal，沒有長度上限，引號、`$`、反引號與換行都不必跳脫（#315）。`--add-dir` 讓 session 不管在哪種權限模式下，讀任務檔都不會跳詢問。wait 回 `satisfied:true` 才送，送出後看 `turn_started` 並讀回 terminal，最後看板設開發中；輸出一行 JSON（worktree、branch、HEAD、terminal、任務檔路徑、是否已送出）。exit 1 是未送出；exit 3 是已送出但未見開始，先 `orca terminal read`，不要重送。工程師接手後在 Issue 留一則「開工」留言（session、branch、HEAD、任務檔路徑、任務檔裡的 Issue 連結與 AC 數）；統籌拿 Issue 連結與 AC 數對照任務檔，對不上就是沒讀到完整檔案，在 Issue 留言後通知工程師重讀。五個主導航的端到端驗證由 CI `verify` job 負責（[verify-stock-lab CI 模式](../.claude/skills/verify-stock-lab/SKILL.md#ci-模式)，依改動範圍只驗受影響的頁），工程師不必在自己的 branch 另跑；UI 任務的截圖仍依規則 c 附在 PR。
   派工後統籌保持一個背景監看（每分鐘查 `gh pr list` 的新 PR 與 repo 層級 `issues/comments?since=` 的新留言），直到所有進行中任務結案；監看到期就重掛，換統籌 session 時由新 session 重掛。工程師的提問與回報只寫在 Issue 留言，不依賴口頭通知。反方向：工程師 session 不會自己查 GitHub，統籌在 Issue／PR 留言給工程師（review 意見、回覆提問、決定）後，必須對該工程師 terminal 送一句短通知並附留言連結，再讀回確認已開始處理；內容以留言為準，terminal 只用來喚醒。
3. **實作**：只改任務需要的檔案；共用檔案（如 `frontend/src/App.tsx`、`backend/app/api.py`）改動前先看是否有其他進行中的任務也在改，有就在 Issue 協調。放 token 的 `.env` 由使用者自己建，agent 只看 `.env.example`（key 與說明寫在那裡）；`.env` 不讀、不搜、不複製、不改，要它的值時請使用者執行。這個 hook 防的是 agent 不小心讀到，防不了刻意繞過（例如先寫一支會讀 `.env` 的腳本再執行），真 token 放進 `.env` 前要知道這點。hook 對 Bash／PowerShell 從寬擋：命令字串提到 `.env` 路徑就擋，連 commit 訊息與 heredoc 裡的字也算，要搜這段文字改用 Grep 工具（pattern 不檢查）、commit 訊息改用 `-F <檔案>`。compose 會把 env file 的值展開進容器的環境變數，所以 hook 也擋會印出它們的 docker 命令（#360）：
   - `docker compose config` 只放行 `-q`／`--quiet`、`--no-interpolate`、`--services` 三種寫法。旗標要直接寫在 `config` 後面，不能是前一個選項的值（`--profile -q` 不算）。另外不能加 `-o`／`--output`、`--environment`、`--variables`，也不能寫帶 `=` 的安全旗標或 `=false` 之類的值（`--quiet=false` 會把它關掉）。
   - `docker inspect`（含 `container`／`image`／`service inspect`）要加 `--format`／`-f`，而且 format 不能取 `Env`、整個 `.Config`、`.` 或 `$`。`network`、`volume inspect` 不擋。
   - `docker run`／`exec`、`docker compose run`／`exec` 的參數裡有 `env`、`printenv` 或 `environ` 時擋下。

   以變數名印出（`sh -c 'echo $TOKEN'`）的寫法擋不到。任務自己 build 的 image 用 `t<issue>` tag，compose project 名稱用 `t<issue>` 開頭，結案時才會被清掉（第 6 步）。工程師與 review session 不跑 `docker image prune`、`docker builder prune`：dangling image 與 build cache 是所有任務共用的，只由 `close_task.sh` 清。
4. **本機檢查**：見下節；全部通過才開 PR。
5. **PR**：套 [PR 模板](../.github/pull_request_template.md)（`gh pr create --body-file` 不會自動帶入模板，先複製模板再填），`Closes #<issue>`，附驗證結果與截圖（前端）。看板設待整合。
6. **Review 與合併**：見下節。合併後 master CI 綠 → Issue 自動關閉、看板完成（PR 進[長期整合分支](#長期整合分支)時 GitHub 不自動關，由 `close_task.sh` 關）；遠端 branch 由 GitHub 自動刪（repo 設定 `delete_branch_on_merge`）；統籌在 `master` 管理 checkout 跑 `bash tools/ops/close_task.sh <issue> [--extra-dir <PR 本文寫的 worktree 外暫存目錄>]...`（同一 Issue 有多個 `task/<issue>-*` worktree 時加 `--slug <slug>`），再刷新程式索引。[`close_task.sh`](../tools/ops/close_task.sh) 先確認 PR 已合併、PR 目標分支（`baseRefName`：master 或[長期整合分支](#長期整合分支)）上它的 merge commit CI 綠（該分支最新一次也不是紅）、本地 branch 已在 `origin/<目標分支>` 裡、worktree 沒有未 commit 的改動、terminal 都閒置，才關 terminal、`orca worktree rm --force`＋`git worktree prune`（殘留目錄一併刪）、刪本地 branch、刪暫存目錄（裡面的 junction／symlink 先拆，不跟隨）、清該任務的 Docker 資源、看板設完成並讀回；任一前提不符就不刪任何東西並非 0 結束。repo 與各 worktree、`$HOME`、磁碟根、`stock-lab-data` 與 `STOCK_DATA_DIR` 不能當 `--extra-dir`；路徑中間經過 junction／symlink 或用了 8.3 短檔名也拒絕，請給實際路徑。Issue 有「統籌承諾」留言時依承諾的順序與時點清理。Docker 資源的清法如下（#360）：
   - **刪除範圍**：tag 是 `t<issue>`／`t<issue>-*` 的 image，repository 以 `t<issue>-`／`task-<issue>-` 開頭的 image（compose 的 `<project>-<service>`），以及名稱以 `t<issue>`／`task-<issue>` 開頭的已停止容器、volume、network。名稱的數字後面要接 `-`、`_`、`.` 或結尾，所以 `t36` 不會刪到 `t360` 的資源。image 一律以 `repository:tag` 刪，不用 id、不加 `-f`，同一個 image 的其他 tag 會留著。
   - **有容器在跑時**：容器名稱屬於這個任務，或用到上述 image／volume／network 時，這個任務的資源一個都不刪，JSON 的 steps 列出 `docker_running:<容器>` 與每個留下的 `docker_kept:<種類>:<名稱>`。
   - **prune**：上述資源清完後，以下條件都成立才跑 `docker image prune -f` 與 `docker builder prune -f`：這個任務是 Docker 子單（PR 進長期整合分支），或剛剛刪了它的資源；沒有任何容器在跑；其他 `task/<n>-*` worktree 都不是 Docker 任務。worktree 有 `t<n>`／`task-<n>` 資源，或 HEAD 含有長期整合分支自己的 commit，就算 Docker 任務；git 讀不出來也算。不成立時記 `docker_prune_skipped:<原因>`，留給最後一個結案的任務。`--no-board` 的試跑不 prune。
   - **不碰的東西**：base image（`python`、`node`、`nginx`、`alpine` 等）與其他專案的 image。
   - **docker 無回應時**：沒有 docker、daemon 沒回應，或任一次呼叫超過 30 秒（`CLOSE_TASK_DOCKER_TIMEOUT`），只記 `docker_skipped:<原因>`，不刪 Docker 資源，結案照常完成。刪不掉的資源記 `docker_failed:<種類>:<名稱>`，不讓結案失敗。
   - **steps**：JSON 的 steps 逐一列出刪掉的資源，格式是 `docker_removed:<種類>:<名稱>`。
   結案時對照本次 review 留言、CI 失敗與使用者糾正，用一次 `gh search issues "<關鍵字>" --repo YiCheng0608/stock-lab --match comments` 查同關鍵字的「第一次」留言（留言格式見 [encode-lesson skill](../.claude/skills/encode-lesson/SKILL.md) 第 1 步），不用 `--paginate` 翻全部留言；有重複就是第二次，另建一張 `[任務]` 把它編成會失敗的檢查（[#228](https://github.com/YiCheng0608/stock-lab/issues/228)），並更新 [AGENTS](../AGENTS.md#規則與強制手段) 對照表。
   每個 gate 收尾、或每合併約 3 個 PR 後，統籌在以最新 `origin/master` 為底的 worktree 跑一次 [verify-stock-lab 真資料模式](../.claude/skills/verify-stock-lab/SKILL.md#真資料模式)（五頁全套，正式 DB 唯讀副本），結果貼在該 gate 的 Issue。verify（CI 或真資料）抓到的 bug，修的同一個 PR 要加一條會先失敗的檢查（測試或 verify 檢查項），不能只修不加。worktree 的 branch 命名 `task/<貼結果的 Issue>-...`（否則 Evidence 不推 `pr-assets`），並在該 worktree 另開 session 執行（skill 拒絕在 `master` 分支跑）。G7 另有五點（使用者 2026-10-26 決定，#288）：
   - **兩條 branch**：排程窗口期間發佈 checkout 跟發佈 branch `release/v1`（[OPERATIONS §6](OPERATIONS.md#6-排程)），master 照常合併 V1.1。`release/v1` 受 ruleset 保護（禁止刪除與強推、只經 PR 以 merge commit 合併、CI `required` 綠）。
   - **V1 改動兩個 PR**：要進 V1 的改動（V1 milestone 的 Issue，含窗口中的修正）從同一條工作 branch 開兩個 PR，一個進 master、一個進 `release/v1`，兩個都要 CI 綠；工作 branch 只合併 `origin/release/v1`（不合併含 V1.1 的 master），進 master 的衝突在 master 那個 PR 解。`release/v1` 不合回 master，也不拿它當 PR 的 head（合併後會被自動刪 branch 設定刪掉）。每次進 `release/v1` 記在 G7 Issue。
   - **真資料 verify** 在窗口的開頭與結尾各跑一次，兩次都用當時 `origin/release/v1` 的程式：worktree 從它建、不加 commit、不留未 commit 的改動（`page_checks.py --g7` 要求 HEAD 等於 `origin/release/v1`，不符合就拒跑）；人工檢查由另一個 session 依寫死的樣本判讀，整份證據再由另一個 session 獨立 review。
   - **每日核對**記發佈 checkout 當時的 branch 與 HEAD（`git -C <發佈 checkout> rev-parse --abbrev-ref HEAD` 與 `--short HEAD`），證明窗口每天跑的是 `release/v1`。
   - **窗口結束**（使用者確認 G7 後）：`git log origin/master..origin/release/v1 --no-merges` 必須為空（V1 改動都已在 master）；在排程閒置時把發佈 checkout 切回 master、依 master 的 lock 檔重裝 venv（下一次 daily 會升 V1.1 的 migration）；`release/v1` 最後一個 commit 打 `v1.0` tag。三項結果記在 G7 Issue。
   master 另有 CI 每晚全套（`schedule`，台北 22:40；也可手動 `workflow_dispatch`）：後端、前端全部跑，`verify` 驗五頁。紅了照 master CI 紅處理（見 [Review 與合併](#review-與合併)）。

## 本機檢查

| 範圍 | 命令 |
| --- | --- |
| 後端 | `python -m pytest backend/tests -q`；`ruff check backend tools`；`ruff format --check backend tools`（repo 根目錄執行，設定在 [`ruff.toml`](../ruff.toml)，CI 同命令） |
| 前端 | `pnpm --dir frontend test:ci`；`pnpm --dir frontend build` |
| 文件／repo | `python tools/ci/checks.py repository --base <完整 master SHA>`（比 base 與工作樹，`--no-commit` 合併時檢的是合併結果） |

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

## 長期整合分支

多張子單要整批進 master 時，子單的 PR 先進一條長期整合分支。目前只有 `feat/docker`（Docker 母單 [#331](https://github.com/YiCheng0608/stock-lab/issues/331)）。

- **建立與保護**：統籌從最新 `origin/master` 切出、推上 GitHub，再建 ruleset。ruleset 內容與 master 的[主線規則](https://github.com/YiCheng0608/stock-lab/rules/24769026)相同，只換目標分支：禁止刪除、禁止強推、只經 PR 以 merge commit 合併、CI `required` 綠才合併。另有兩項也相同：PR 分支要跟上目標分支，review 討論要全部解決。`feat/docker` 從 `5c8deb0` 切出，ruleset 是 [26027657](https://github.com/YiCheng0608/stock-lab/rules/26027657)，可用 `gh api repos/YiCheng0608/stock-lab/rulesets/<id>` 對照兩份的 `rules`。長期整合分支的清單只寫在 [`close_task.sh`](../tools/ops/close_task.sh) 的 `integration_branches`。CI 對它的 PR 與 push 都要跑，所以每個分支也要列在 `.github/workflows/ci.yml` 的 `pull_request`／`push` branches；`tools/ci/test_checks.py` 的 `WorkflowTriggers` 會核對兩邊一致。新增長期整合分支時，同一個 PR 改這兩處。
- **第一次派工之前**：PR 的 CI 讀的是 merge ref 裡的 `ci.yml`。整合分支如果是在 `ci.yml` 列入它之前切出的，從它開的 PR 不會跑 CI，`required` 不會回報，PR 就合不進去；push 也沒有 run，`close_task.sh` 會讀到 `missing`。這種情況要先開一次「master → 整合分支」的同步 PR（做法見下方「跟上 master」），合併後才派子單。`feat/docker` 就是這種情況：它從 `5c8deb0` 切出，早於 #332。
- **派工**：`dispatch.sh … --base origin/feat/docker`（[任務流程](#任務流程)第 2 步）。工程師以 `gh pr create --base feat/docker` 開 PR，跟上目標分支時合併 `origin/feat/docker`。
- **結案**：`close_task.sh` 讀 PR 的 `baseRefName`，查的是目標分支的 CI 與歷史（[任務流程](#任務流程)第 6 步）。目標只接受 master 與 `integration_branches`；進 `release/*` 或其他分支的 PR 會被拒絕，什麼都不刪，要結案就用 `--pr` 指定進 master 的那個 PR。
- **關 Issue**：PR 合併進非預設分支時，GitHub 不會依 `Closes #<issue>` 關 Issue。所以目標不是 master 時，close_task 在全部前提成立後、刪除任何東西之前，執行 `gh issue close <issue>`，並留言 PR 與 merge commit。
  - 關不掉，而且讀回 Issue 仍是開的：停下，不刪任何東西。
  - Issue 已經關了（例如刪除步驟失敗後重跑）：不再呼叫 `gh issue close`，照常清理。
  - 目標是 master 時不呼叫；`--no-board` 的試跑也不關。
- **跟上 master 與收尾**：master 每週至少合併進整合分支一次。因為整合分支只收 PR，做法是從 `origin/feat/docker` 開 branch、合併 `origin/master` 後開 PR。全部子單完成後，整合分支開一個 PR 進 master；Docker 另要等 G7 通過，見 #331。合併後統籌移除它的 ruleset 與分支，並把分支從 `integration_branches` 與 `ci.yml` 移除。

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

- **事件與巡檢**：派工後的 GitHub 監看（見[開工](#任務流程)）之外，統籌在自己的 session 掛每 20～30 分鐘一次的巡檢，固定順序：寫心跳檔 → 讀計數檔與換手標記 → 監看是否存活 → open PR 的 CI 與合併 → 進行中 Issue 的提問 → 名額空缺就派工 → 背景工作是否卡住。每次巡檢先跑 `bash tools/ops/patrol.sh`：[它](../tools/ops/patrol.sh)寫心跳檔、讀自己的計數檔與換手標記，並印出 open PR 的 CI 與 `mergeStateStatus`、`--since`（預設上次心跳）之後的新留言、排程日誌的最後一列；gh 呼叫最多 `--max-gh` 次（預設 2）。心跳檔若屬於另一個 session 且不到 60 分鐘，又沒有它的換手標記，就不覆寫並非 0 結束；確定要接手才加 `--take-over`。其餘各步照上面的順序判斷。監看到期重掛時 `since` 取上次監看啟動時間，不取現在。
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

V1 的每日排程在本機以 Windows 工作排程器執行 `python -m worker.cli job daily` 與 `job news`；設定方式與日誌位置寫在 [OPERATIONS §6](OPERATIONS.md#6-排程)。排程失敗以 Issue 追蹤。
