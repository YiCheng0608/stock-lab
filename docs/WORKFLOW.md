<!-- owns: 唯一來源對照、Issue 標題前綴、版本完成判定、資料與功能拆線、分流、任務流程、留言類型、本機檢查、review 與合併、PR 檢查規則、CI 後端測試分流、長期整合分支、失敗處理、程式索引 -->
# GitHub 工作手冊

[AGENTS](../AGENTS.md) 管角色與原則，本文管操作細節，模板在 [docs/templates](templates/README.md)；統籌 session 與無人值守運作見 [COORDINATOR](COORDINATOR.md)。

## 欄位與唯一來源

| 資訊 | 位置 |
| --- | --- |
| 程式與文件 | [YiCheng0608/stock-lab](https://github.com/YiCheng0608/stock-lab)，正式 branch `master`；[主線規則](https://github.com/YiCheng0608/stock-lab/rules/24769026)要求 PR、只允許 merge commit、禁止強推，required check 為 CI 的 `required` |
| 產品方向、版本範圍 | [ROADMAP](ROADMAP.md) |
| 已完成能力 | [CAPABILITIES](CAPABILITIES.md) |
| 前端視覺與互動 | [DESIGN_SYSTEM](DESIGN_SYSTEM.md) |
| 任務目標、範圍、AC、決策、結果 | Issue 本文與留言 |
| 版本任務集合 | [GitHub milestones](https://github.com/YiCheng0608/stock-lab/milestones)（V1 已關閉；之後的任務在 V1.1 體驗與策略等 milestone） |
| 狀態 | [產品開發看板](https://github.com/users/YiCheng0608/projects/1) Status：待辦／開發中／待整合／完成（「測試中」不使用） |
| 使用者層級決策 | [治理 Issue #1](https://github.com/YiCheng0608/stock-lab/issues/1) 留言 |
| 發佈與部署 | [RELEASE](RELEASE.md)；部署記錄在正式 compose project 的 volume 的 `/data/logs/deploy.json` |

Issue 標題前綴：`[任務]` 可直接開工的工作、`[功能]` 多任務的母單、`[候選]` 想法或 bug 尚未排程。母子關係用 GitHub 原生 sub-issue，依賴寫在 Issue 本文。

## 版本範圍與完成判定

V1 以 ROADMAP V1 基線的七個 gate（V1-G1～G7）承接，每個 gate 由一到數張任務 Issue 承接；完成的判定是 G7 發布驗收通過，不是 Issue 關閉數，已於 2026-11-02 通過（[V1 已完成](ROADMAP.md#v1-已完成)）。之後的任務在建單時於本文寫明對應的 milestone 與依據（#1 決策留言、ROADMAP 段落或母單）。

## 資料與功能拆線

資料（排程、collector、DB）與功能（指標、API、UI）可拆成不同任務並行；功能任務先用小 fixture 開發，接真實資料是整合步驟，寫在 AC 裡。

## 分流

開工前依序問，第一個答「是」就停：

1. 改到[高風險路徑](../tools/ci/checks.py)（`HIGH_RISK_PATHS`，清單只在該處維護）嗎？是：完整流程（Issue、AC、worktree），PR 加 `independent-review` label，AC 含正式 DB 唯讀副本實測（取法見 [LOCAL](ops/LOCAL.md#取正式-db-的唯讀副本)：正式 DB 在 Docker volume，不是主機檔案）。
2. 改到 `backend/app/`、`backend/worker/`、`backend/alembic/`、`backend/data/`、`frontend/src/` 的非測試檔嗎？是：Issue、AC、worktree；小的統籌可自做。
3. 其餘（文件、流程檔、`tools/ci/`、純測試改動）：可直接開 PR 不建 Issue，驗證欄寫 CI；規模大仍可建 Issue。

另兩條與大小無關：要拆成多張就開 `[功能]` 母單；碰到共用檔案且有任務進行中，先在 Issue 協調（[任務流程](#任務流程)第 3 步）。第 1、2 類由 CI 的 `pr` 檢查（規則 a、d，見 [Review 與合併](#review-與合併)）擋下沒有 `Closes #<issue>` 或缺 label 的 PR。

## 任務流程

1. **建單**：套[任務 Issue 模板](templates/issue-task.md)，填目標、範圍、AC、依賴、對應里程碑與依據；套 milestone；看板設待辦。UI 任務（改 verify 五個頁面組的頁面：今日名單（含大盤）、我的追蹤、族群、個股、新聞；主導航是七項，策略說明不在 verify）的 AC 固定加一條「更新對應的 [`features/*.md`](../.claude/skills/verify-stock-lab/features) 或寫明不需更新」。
2. **開工**：統籌照[任務檔模板](templates/task-file.md)把任務全文（Issue 連結、AC、白名單、驗證方式，以及「提問與回報照[留言類型](#留言類型)寫在 Issue／PR 留言」一點）寫成 UTF-8 檔（不經 PowerShell 管線），放 worktree 外、統籌換手後仍在的目錄（例如 `$HOME/t<issue>/task/task.md`；工程師把 `$HOME/t<issue>/` 列進 PR 本文的 worktree 外暫存目錄，結案時以 `--extra-dir` 刪）。pytest 的 `--basetemp` 要用同一目錄下的另一個子目錄（例如 `$HOME/t<issue>/b1`），因為 pytest 開跑時會清空 basetemp，全綠時也會刪掉它，任務檔不能放在裡面。目錄名不能含 `"`、`$`、反引號、`%`、`!`，dispatch.sh 會拒絕（exit 64）。寫好後跑一行：

   ```text
   bash tools/ops/dispatch.sh <issue> <slug> --task-file <任務全文檔> [--model <model> --effort <effort>] [--base origin/<branch>]
   ```

   [`dispatch.sh`](../tools/ops/dispatch.sh) 先 fetch 再從最新 `origin/master` 建 worktree；子單的 PR 目標是[長期整合分支](#長期整合分支)時加 `--base origin/<該分支>`，fetch 與「新 worktree 的 HEAD 等於最新 base」的核對都改用它。依序等於下列手動命令（模型預設 `claude-opus-5-5`／`medium`；`--base-branch` 只在 `--base` 不等於 `origin/master` 時加）：

   ```text
   orca worktree create --repo id:<repoId> --name task-<issue>-<slug> --no-parent --setup skip [--base-branch origin/<branch>] --json
   git -C <path> branch -m <orca-branch> task/<issue>-<slug>
   orca terminal create --worktree id:<repoId>::<path> --title "#<issue> <slug>" --shell git-bash --command 'COMPOSE_PROJECT_NAME=task-<issue> CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP=1 claude --model <model> --effort <effort> --add-dir "<任務檔目錄>"' --json
   orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json
   orca terminal send --terminal <handle> --text "請用 Read 工具讀取任務檔 <path>（UTF-8），依其內容開工；開工留言回貼任務檔裡的 Issue 連結與 AC 數。" --enter --wait-submit 30 --json
   ```

   terminal 只收到這一句，`<path>` 是任務檔的絕對路徑（Windows 寫成 `C:/…`）；任務全文不經 terminal，沒有長度上限，引號、`$`、反引號與換行都不必跳脫（#315）。`--add-dir` 讓 session 不管在哪種權限模式下，讀任務檔都不會跳詢問。wait 回 `satisfied:true` 才送，送出後看 `turn_started` 並讀回 terminal，最後看板設開發中；輸出一行 JSON（worktree、branch、HEAD、terminal、任務檔路徑、是否已送出）。exit 1 是未送出；exit 3 是已送出但未見開始，先 `orca terminal read`，不要重送。工程師接手後在 Issue 留一則 `回報：開工` 留言（session、branch、HEAD、任務檔路徑、任務檔裡的 Issue 連結與 AC 數）；統籌拿 Issue 連結與 AC 數對照任務檔，對不上就是沒讀到完整檔案，在 Issue 留言後通知工程師重讀。verify 五個頁面組的端到端驗證由 CI `verify` job 負責（[verify-stock-lab CI 模式](../.claude/skills/verify-stock-lab/SKILL.md#ci-模式)，依改動範圍只驗受影響的頁），工程師不必在自己的 branch 另跑；UI 任務的截圖仍依規則 c 附在 PR。
   派工後的新 PR 與新留言由常駐的事件 monitor 發現並喚醒統籌（[無人值守運作](COORDINATOR.md#無人值守運作)），統籌 session 不必自己輪詢。工程師的提問與回報照[留言類型](#留言類型)寫在 Issue／PR 留言，不依賴口頭通知。反方向：工程師 session 不會自己查 GitHub，統籌在 Issue／PR 留言給工程師（`review：`、`決定：`）後，必須對該工程師 terminal 送一句短通知並附留言連結，再讀回確認已開始處理；內容以留言為準，terminal 只用來喚醒。
3. **實作**：只改任務需要的檔案；共用檔案（如 `frontend/src/App.tsx`、`backend/app/api.py`）改動前先看是否有其他進行中的任務也在改，有就在 Issue 協調。放 token 的 `.env` 由使用者自己建，agent 只看 `.env.example`（key 與說明寫在那裡）；`.env` 不讀、不搜、不複製、不改，要它的值時請使用者執行。這個 hook 防的是 agent 不小心讀到，防不了刻意繞過（例如先寫一支會讀 `.env` 的腳本再執行），真 token 放進 `.env` 前要知道這點。hook 對 Bash／PowerShell 從寬擋：命令字串提到 `.env` 路徑就擋，連 commit 訊息與 heredoc 裡的字也算，要搜這段文字改用 Grep 工具（pattern 不檢查）、commit 訊息改用 `-F <檔案>`。compose 會把 env file 的值展開進容器的環境變數，所以 hook 也擋會印出它們的 docker 命令（`docker compose config`、`docker inspect`、`docker run`／`exec` 等；放行與擋下的旗標只寫在 [GUARDRAILS](GUARDRAILS.md) 不讀 `.env` 那一列，#360）。以變數名印出（`sh -c 'echo $TOKEN'`）的寫法擋不到。任務自己 build 的 image 用 `t<issue>` tag，compose project 名稱用 `t<issue>` 或 `task-<issue>` 開頭，結案時才會被清掉（第 6 步）。工程師與 review session 不跑 `docker image prune`、`docker builder prune`、`docker volume prune`、`docker system prune`：dangling image 與 build cache 是所有任務共用的，只由 `close_task.sh` 清。
4. **本機檢查**：見下節；全部通過才開 PR。
5. **PR**：套 [PR 模板](templates/pull-request.md)（`gh pr create --body-file` 不會自動帶入模板，先複製模板再填），`Closes #<issue>`，附驗證結果與截圖（前端）。看板設待整合。
6. **Review 與合併**：見下節。合併後 master CI 綠 → Issue 自動關閉、看板完成（PR 進[長期整合分支](#長期整合分支)時 GitHub 不自動關，由 `close_task.sh` 關）；遠端 branch 由 GitHub 自動刪（repo 設定 `delete_branch_on_merge`）；統籌在 `master` 管理 checkout 跑 `bash tools/ops/close_task.sh <issue> [--extra-dir <PR 本文寫的 worktree 外暫存目錄>]...`（同一 Issue 有多個 `task/<issue>-*` worktree 時加 `--slug <slug>`）；清理後它把管理 checkout 快轉到新 master 並重建、驗證[程式索引](#程式索引)，不另外手動刷新。[`close_task.sh`](../tools/ops/close_task.sh) 先確認 PR 已合併、PR 目標分支（`baseRefName`：master 或[長期整合分支](#長期整合分支)）上它的 merge commit CI 綠（該分支最新一次也不是紅）、本地 branch 已在 `origin/<目標分支>` 裡、worktree 沒有未 commit 的改動、terminal 都閒置，才關 terminal、`orca worktree rm --force`＋`git worktree prune`（殘留目錄一併刪）、刪本地 branch、刪暫存目錄（裡面的 junction／symlink 先拆，不跟隨）、並刪該任務各工程師 session 的 Claude Code scratchpad（#472，規則見 `close_task.sh` 開頭與 GUARDRAILS）、清該任務的 Docker 資源、看板設完成並讀回；任一前提不符就不刪任何東西並非 0 結束。repo 與各 worktree、`$HOME`、磁碟根、`stock-lab-data` 與 `STOCK_DATA_DIR` 不能當 `--extra-dir`；路徑中間經過 junction／symlink 或用了 8.3 短檔名也拒絕，請給實際路徑。Issue 有 `統籌承諾：` 留言時依承諾的順序與時點清理。Docker 資源只刪名稱屬於這個任務（`t<issue>`／`task-<issue>`）的，刪除範圍、有容器在跑時、`prune` 與 docker 無回應時的處理見 [GUARDRAILS](GUARDRAILS.md) 的「結案腳本刪任務的 Docker 資源」列與 [`coordinator_lib.sh`](../tools/ops/coordinator_lib.sh) 的 `docker_cleanup`（#360）。
   結案時對照本次 review 留言、CI 失敗與使用者糾正，用一次 `gh search issues "<關鍵字>" --repo YiCheng0608/stock-lab --match comments` 查同關鍵字的「第一次」留言（留言格式見 [encode-lesson skill](../.claude/skills/encode-lesson/SKILL.md) 第 1 步），不用 `--paginate` 翻全部留言；有重複就是第二次，另建一張 `[任務]` 把它編成會失敗的檢查（[#228](https://github.com/YiCheng0608/stock-lab/issues/228)），並更新 [GUARDRAILS](GUARDRAILS.md) 對照表。
   每個 gate 收尾、或每合併約 3 個 PR 後，統籌在以最新 `origin/master` 為底的 worktree 跑一次 [verify-stock-lab 真資料模式](../.claude/skills/verify-stock-lab/SKILL.md#真資料模式)（五頁全套，正式 DB 唯讀副本），結果貼在該 gate 的 Issue。verify（CI 或真資料）抓到的 bug，修的同一個 PR 要加一條會先失敗的檢查（測試或 verify 檢查項），不能只修不加。worktree 的 branch 命名 `task/<貼結果的 Issue>-...`（否則 Evidence 不推 `pr-assets`），並在該 worktree 另開 session 執行（skill 拒絕在 `master` 分支跑）。發佈與部署（tag、`deploy.sh`）見 [RELEASE](RELEASE.md)；V1 G7 窗口用過的發佈隔離已結束，見 [RELEASE 的 V1 發佈隔離（歷史）](RELEASE.md#v1-發佈隔離歷史)。
   每個 gate 收尾時，統籌另跑一次 DB 深度審查（[#391](https://github.com/YiCheng0608/stock-lab/issues/391)）：先照 [LOCAL](ops/LOCAL.md#取正式-db-的唯讀副本) 的標準命令（`tools/ops/copy_db.py`）取正式 DB 的唯讀副本，在以最新 `origin/master` 為底的 worktree 跑 `python tools/audit/audit.py --db <副本> --out <目錄>`，把 `<目錄>/summary.md` 貼在該 gate 的 Issue。
   - **審什麼**：工具不 import 產品的計算函式，依 [Canonical v1 規格](spec/README.md) 獨立重算全歷史，比對日線、raw、除權息欄位與缺漏、來源與日期欄位、技術指標、訊號的法人與融資比率、候選分數與族群分數。項目清單與各項範圍寫在 [`audit.py`](../tools/audit/audit.py) 開頭。
   - **只讀**：DB 用唯讀連線，raw 依副本的 `payload_path` 經 `app.raw_paths.payload_file` 找檔（舊 Windows 路徑在容器內讀 `STOCK_RAW_DIR` 底下），只以 `rb` 開啟；兩處都沒有時，`--raw-dir` 可改指 raw 副本。主機的 `raw/` 已刪，在主機直接跑讀不到 raw，要在容器內跑或給 `--raw-dir`（[LOCAL](ops/LOCAL.md#讀-raw-的工具)）。拒絕正式 DB（含 hard link）、`--out` 指到正式資料目錄底下（字面與解析連結後都比）、台北 21:30～23:30 與可用記憶體不足（`--min-free-gb`，預設 5）。跑到 21:30 就停在下一項之前，其餘記無法判定，exit 3；23:30 後用 `--only` 補跑剩下的項目。
   - **三態**：失敗是 DB 和重算或 raw 不一致；無法判定是 raw 讀不到、母體重建不出，或列寫入之後它讀到的輸入才被更正而沒有重算（`inputs_changed_after_write`：籌碼比率只看窗口內的籌碼列與日線，價格類只看窗口內的除權息；筆數與例子列在 summary）。失敗的項目由統籌建 Issue 處理，工具不修資料。
   master 另有 CI 每晚全套（`schedule`，台北 22:40；也可手動 `workflow_dispatch`）：後端、前端全部跑，`verify` 驗五頁。紅了照 master CI 紅處理（見 [Review 與合併](#review-與合併)）。

## 留言類型

任務 Issue 與 PR 上，工程師、統籌與獨立 review 的每則對話留言，第一行以下列其中一種開頭（冒號用全形），依「誰要接著動作」分類（#401）：

| 第一行開頭 | 誰寫 | 誰要接著動作 | 必填 |
| --- | --- | --- | --- |
| `提問：` | 工程師 | 統籌必須回覆，工程師在等 | 問題、選項、建議、卡住什麼 |
| `決定：` | 統籌 | 工程師照做 | 回覆哪一則提問（連結）、決定、理由 |
| `回報：` | 工程師 | 不用動作（開工、進度、PR 已開、必修已修、收到） | head、做了什麼、下一步 |
| `review：` | 統籌、獨立 review | 有必修時工程師修 | head、結論（可合併／有必修）、必修清單 |
| `統籌承諾：` | 統籌 | 統籌日後兌現 | 還沒做的事、時點、保留的資源 |

- 提問只寫在 Issue／PR 留言，不寫在 terminal，也不在 terminal 等口頭回覆。背景工作被系統停掉、或任何要等統籌才能繼續的情況也一樣，以 `提問：` 留在 Issue。工程師 session 的回合結束時，[turn hook](COORDINATOR.md#無人值守運作)會檢查這一回合有沒有在 Issue／PR 留言，沒有就擋一次並提醒（#595）。統籌只看 Issue／PR 留言，terminal 的通知只用來喚醒（[任務流程](#任務流程)第 2 步）。
- 統籌的留言經 [`comment.sh`](../tools/ops/comment.sh) 發，本文最後一行會帶不顯示的統籌標記，事件 monitor 不為它喚醒統籌（[統籌留言](COORDINATOR.md#無人值守運作)）。只有統籌用它：工程師與獨立 review 用了，留言就不會喚醒統籌。
- 一則留言只放一種類型；一次問好幾件事就分成好幾則 `提問：`，各自等 `決定：`。
- `決定：` 要附它回覆的提問留言連結（`…#issuecomment-<id>`，只寫 ID 不算）。`決定：` 寫在提問所在的 Issue／PR；PR 可能先關時（改開新 PR、Docker 子單），寫在 Issue：`patrol.sh` 只讀 open Issue 與 open PR，寫在已關的 PR 上的決定讀不到，提問會變回未回覆。
- 第一行前面的空行與空白可以；第一行不要加粗或引用（`**提問：**`、`> 提問：` 都不算類型）。
- [`patrol.sh`](../tools/ops/patrol.sh) 讀 open Issue 與 open PR 的留言，把還沒有 `決定：` 連到它的 `提問：` 逐筆列為「未回覆的提問」（Issue 號、留言連結、經過時間）；判斷只看第一行開頭與連結，寫在 [`coordinator_json.py`](../tools/ops/coordinator_json.py) 的 `unanswered_questions`。只讀對話留言，PR review 與行內留言不算。
- 治理 Issue #1 的留言照[無人值守運作](COORDINATOR.md#無人值守運作)的寫法（「待使用者」與決策紀錄），不套本表，`patrol.sh` 也不讀它：#1 是使用者決策的治理單，工程師不在那裡提問；它的留言又超過一頁，讀了只會每次都印「未查完」。

## 本機檢查

在容器內跑，用 CI 同一套 image 與依賴（[Docker compose](ops/SETUP.md#docker-compose)；需要 Docker Compose 2.24 以上）。Git Bash、worktree 根目錄執行。`-p task-<issue>` 是任務的 compose project，image、容器與 volume 都以它開頭，各 worktree 互不影響；`dispatch.sh` 以 Git Bash（`--shell git-bash`，前綴是 POSIX 寫法）開 terminal，並用 `COMPOSE_PROJECT_NAME=task-<issue> CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP=1 claude …` 啟動，漏了 `-p` 也落在同一個 project。第二個變數關掉 Claude Code 在主機記憶體吃緊時收掉背景 shell 的機制（#595：被收的是主機上的 docker CLI，幾乎不釋放記憶體，容器的記憶體由 WSL VM 的上限管，收掉只讓結果收不回來，通知又叫工程師停下來等人）。這兩個變數只跟著那一次 `claude`：resume 工程師 session 時寫成 `COMPOSE_PROJECT_NAME=task-<issue> CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP=1 claude --resume <ID> --effort <原 level>`；Orca 自己 resume 的 session 沒有它們，只靠命令裡的 `-p`。`--build` 從工作樹（含未 commit 的改動）重建 image，沒改的層走快取。

測試與 `checks.py` 讀 git，而 image 不含 `.git`；worktree 的 `.git` 是指向 Windows 路徑的檔案，容器裡讀不到。所以唯讀掛進共用的 git 目錄，再掛一個指向其中 `worktrees/<worktree 名>` 的 `.git` 檔，容器裡的 git 讀到的就是這個 worktree 的 branch、HEAD 與 index。每個新 shell 先跑（`$T` 是 worktree 外暫存目錄，路徑見 [LOCAL](ops/LOCAL.md#工具)，寫進 PR）：

```bash
# 換值（docs/ops/LOCAL.md）：<worktree 外暫存目錄>＝「工具」表的「worktree 外暫存目錄」，t<issue> 的 <issue> 是 Issue 號
T=<worktree 外暫存目錄>; mkdir -p "$T"
printf 'gitdir: /repo.git/worktrees/%s\n' "$(basename "$(git rev-parse --git-dir)")" > "$T/gitfile"
GIT_RO=(-v "$(git rev-parse --git-common-dir):/repo.git:ro" -v "$T/gitfile:/app/.git:ro")
export MSYS_NO_PATHCONV=1   # 否則 Git Bash 會把 -v 的容器路徑改寫成 Windows 路徑
```

| 範圍 | 命令 |
| --- | --- |
| 後端 | `docker compose -p task-<issue> run --rm --build "${GIT_RO[@]}" api python -B -m pytest -p no:cacheprovider -q <改動相關的測試檔>`；`docker compose -p task-<issue> run --rm --build api ruff check --no-cache backend tools`；`docker compose -p task-<issue> run --rm --build api ruff format --check --no-cache backend tools`（設定在 [`ruff.toml`](../ruff.toml)，ruff 版本與 CI 相同） |
| 前端 | `docker compose -p task-<issue> -f docker-compose.yml -f docker-compose.dev.yml run --rm --build web pnpm run test:ci`；同樣的前綴接 `web pnpm run build`（dev image，`frontend/` bind mount 進容器，`dist/` 寫回工作樹） |
| 文件／repo | `docker compose -p task-<issue> run --rm --build "${GIT_RO[@]}" api python -B tools/ci/checks.py repository --base <PR 目標分支的完整 SHA>`（比 base 與工作樹，`--no-commit` 合併時檢的是合併結果）；`docker compose -p task-<issue> run --rm --build "${GIT_RO[@]}" api python -B -m unittest discover -s tools/ci -p 'test_*.py'` |

- 後端只跑改動相關的測試檔（改到的模組與腳本自己的測試，以及讀它們的測試），不跑全套：全套後端 pytest 由 PR CI 的 `backend` job 跑（每個 PR 都跑，[CI 後端測試分流](#review-與合併)）。PR 本文的驗證寫本機跑了哪些測試檔（#595：本機全套要 52～68 分鐘，是同時最吃資源的工作，又沒有比 CI 多驗到東西）。
- 有真 env file 時，哪些輸出會帶 token、不能貼到 GitHub，見 [Docker compose](ops/SETUP.md#docker-compose) 的 `STOCK_ENV_FILE`。
- 台北 21:30～23:30 不跑全套 pytest 與 `docker build`（[無人值守運作](COORDINATOR.md#無人值守運作)）。
- 結案時（[任務流程](#任務流程)第 6 步）統籌在 `close_task.sh` 之前跑 `docker compose -p task-<issue> -f docker-compose.yml -f docker-compose.dev.yml down --volumes --rmi all`，刪掉這個 project 的容器、網路、volume 與 image；`$T` 以 `--extra-dir` 交給 `close_task.sh`。

每個 checkout 設一次 `git config blame.ignoreRevsFile .git-blame-ignore-revs`，`git blame` 會略過 [`.git-blame-ignore-revs`](../.git-blame-ignore-revs) 列出的全檔格式化 commit。

容器外的工具（`tools/ops/*.sh`、在本機跑的 `tools/verify/*.py`）用的 Python 是[容器外的 Python](ops/LOCAL.md#工具)（PATH 上的 python 是 Store stub）。資料路徑見 [LOCAL](ops/LOCAL.md#正式位置使用者決定)。

## Review 與合併

- PR 必須 CI 全綠（`.github/workflows/ci.yml`）。CI 的 `pr` 檢查（[`tools/ci/checks.py`](../tools/ci/checks.py) `pr` 模式）讀 PR 本文、label 與 commit 訊息；改本文或 label 會自動重跑：
  - a. 改到[分流](#分流)第 1、2 類路徑，本文要有 `Closes #<issue>`。
  - b. 本文「AC 逐條結果」的每一條 AC 後面要有內容；第 1、2 類 PR 必須有這一區。
  - c. 改到 `frontend/src/` 的非測試檔，本文要有圖片或 `pr-assets` 連結。
  - d. 改到 `HIGH_RISK_PATHS`，PR 要有 `independent-review` label。
  - e. commit 訊息不得有 closing keyword（`Fix #N`、`Closes #N`、`Resolves #N` 等）：commit 一進 master 就會關 Issue，早於結案步驟。
- 後端測試在 CI 分兩個 job，不重跑全套（#378）：`backend` 在 runner 上以 pytest-xdist 平行跑 `backend/tests` 全套（#442；本機只跑相關測試檔，#595）；`docker` 在 image 內建置、import `app`／`worker` 全部模組、截圖，並只跑 [`docker_suite.json`](../tools/ci/docker_suite.json) 的 `docker` 列出的測試——結果會隨 image 的執行環境（tini 當 PID 1、非 root、image 內的 node 與 chromium）改變的那些。`suite` job 以 [`suite_split.py`](../tools/ci/suite_split.py) 比對兩個 job 的報告：全套每個測試都要在其中一個 job **實際執行**（不是 skipped），否則 CI 紅並列出 test id；比的是執行而不是收集，因為 `backend` 收集全套，只比收集永遠成立。`docker` 列出的測試在 image 內被 skip 也紅（它們在 runner 上也會通過，不另外檢查就會漏掉 image 退化）。新增只在 runner 上跳過的測試（缺 image 才有的工具、`skipif`）時，把它或它的檔案加進 `docker`；Windows 專屬、CI 哪裡都不會跑的測試寫進同一檔的 `skipped_everywhere` 並附原因，已能執行的項目留在裡面也會紅。本機檢查在容器內只跑相關測試檔（[本機檢查](#本機檢查)）。
- 統籌 review 重點：AC 是否逐條有驗證、文件是否同步、是否遵守 DESIGN_SYSTEM、有沒有寫死色碼／路徑／金鑰、測試是否覆蓋邊界。AC 證據必須是命令與輸出、查詢結果或截圖連結，只寫「通過」不算。
- 改到 [`HIGH_RISK_PATHS`](../tools/ci/checks.py) 的 PR 加一次獨立 review（`/code-review` 或另開 session）並加 `independent-review` label。獨立 review 要寫出「這個變更安全是因為哪一個事實」，以及證明它的方式（命令與輸出、查詢或測試名稱）。另開的 review session 在本機 build 或起 compose 時，image tag 與 compose project 用 `t<pr>-review` 開頭（結案腳本只清 `t<issue>`，PR 的資源不會被它刪），結束前自己 `docker compose -p t<pr>-review down --volumes --rmi all`；與工程師一樣不跑任何 `prune`（[任務流程](#任務流程)第 3 步；PR #349 第一次 review 曾刪掉別人的 image）。派 review session 的任務文要寫進這兩點。
- 合併用 merge commit，不 squash／rebase；衝突由 PR 作者在自己 branch 解決。主線規則要求 PR 分支跟上 master：master 前進後統籌以 `gh api -X PUT repos/YiCheng0608/stock-lab/pulls/<n>/update-branch -f expected_head_sha=<head>` 把 master 併入（merge commit），CI 重跑綠再合併。
- master CI 紅：先修 master（fix-forward PR），修好前不合併其他 PR。

## 長期整合分支

多張子單要整批進 master 時，子單的 PR 先進一條長期整合分支。目前沒有；過去有 `feat/docker`（Docker 母單 [#331](https://github.com/YiCheng0608/stock-lab/issues/331)），2026-11-03 由 PR #420 併入 master，#428 把它移出清單。

- **建立與保護**：統籌從最新 `origin/master` 切出、推上 GitHub，再建 ruleset。ruleset 內容與 master 的[主線規則](https://github.com/YiCheng0608/stock-lab/rules/24769026)相同，只換目標分支：禁止刪除、禁止強推、只經 PR 以 merge commit 合併、CI `required` 綠才合併。另有兩項也相同：PR 分支要跟上目標分支，review 討論要全部解決。可用 `gh api repos/YiCheng0608/stock-lab/rulesets/<id>` 對照兩份的 `rules`（過去的 `feat/docker` 從 `5c8deb0` 切出，ruleset 是 26027657）。長期整合分支的清單只寫在 [`close_task.sh`](../tools/ops/close_task.sh) 的 `integration_branches`。CI 對它的 PR 與 push 都要跑，所以每個分支也要列在 `.github/workflows/ci.yml` 的 `pull_request`／`push` branches；`tools/ci/test_checks.py` 的 `WorkflowTriggers` 會核對兩邊一致。清單可以是空的（`integration_branches=()`）。新增長期整合分支時，同一個 PR 改這兩處。
- **第一次派工之前**：PR 的 CI 讀的是 merge ref 裡的 `ci.yml`。整合分支如果是在 `ci.yml` 列入它之前切出的，從它開的 PR 不會跑 CI，`required` 不會回報，PR 就合不進去；push 也沒有 run，`close_task.sh` 會讀到 `missing`。這種情況要先開一次「master → 整合分支」的同步 PR（做法見下方「跟上 master」），合併後才派子單。`feat/docker` 當時就是這種情況：它從 `5c8deb0` 切出，早於 #332。
- **派工**：`dispatch.sh … --base origin/<整合分支>`（[任務流程](#任務流程)第 2 步）。工程師以 `gh pr create --base <整合分支>` 開 PR，跟上目標分支時合併 `origin/<整合分支>`。
- **結案**：`close_task.sh` 讀 PR 的 `baseRefName`，查的是目標分支的 CI 與歷史（[任務流程](#任務流程)第 6 步）。目標只接受 master 與 `integration_branches`；進 `release/*` 或其他分支的 PR 會被拒絕，什麼都不刪，要結案就用 `--pr` 指定進 master 的那個 PR。
- **關 Issue**：PR 合併進非預設分支時，GitHub 不會依 `Closes #<issue>` 關 Issue。所以目標不是 master 時，close_task 在全部前提成立後、刪除任何東西之前，執行 `gh issue close <issue>`，並留言 PR 與 merge commit。
  - 關不掉，而且讀回 Issue 仍是開的：停下，不刪任何東西。
  - Issue 已經關了（例如刪除步驟失敗後重跑）：不再呼叫 `gh issue close`，照常清理。
  - 目標是 master 時不呼叫；`--no-board` 的試跑也不關。
- **跟上 master 與收尾**：master 每週至少合併進整合分支一次。因為整合分支只收 PR，做法是從 `origin/<整合分支>` 開 branch、合併 `origin/master` 後開 PR。全部子單完成後，整合分支開一個 PR 進 master（`feat/docker` 另等了 G7 通過，見 #331）。合併後開一個 PR 把分支從 `integration_branches` 與 `ci.yml` 移除（`feat/docker` 是 #428）；那個 PR 合併、master CI 綠後，統籌刪掉它的 ruleset 與分支。

## 失敗處理

| 類型 | 處置 |
| --- | --- |
| 產品缺陷 | 同 PR 修正並補測試 |
| 測試工具／環境 | 修環境或在 Issue 記錄限制；不刪測試湊綠 |
| 外部來源失敗（限流、改版） | 在 Issue 記來源、時間、錯誤；程式要能重跑且不寫壞資料 |
| AC 做不到 | Issue 說明原因與替代，統籌決定拆分、延後或請使用者決策 |

## 程式索引

codebase-memory 只有一份索引：master 管理 checkout 的 project `C-Users-YiCheng-Desktop-taiwan-stock-research`（#704）。工程師查程式用這個 project，不對自己的 worktree 跑 `index_repository`；自己改過的檔以 worktree 內的實際檔案為準。MCP 斷線用同引擎 CLI（[LOCAL](ops/LOCAL.md#工具)）`<codebase-memory CLI> cli --json <tool>`。索引只是查找工具，不當驗收證據。

索引由腳本維持，不靠人記得：

- [`close_task.sh`](../tools/ops/close_task.sh)（PR 進 master、不是 `--no-board`）：清理做完後，把管理 checkout 以 `git merge --ff-only origin/master` 更新（checkout 要在 master、已追蹤的檔沒有未 commit 的改動），重建索引，再驗證這次 merge commit 改到的檔。任一步失敗是 exit 3，`error` 以「管理 checkout 更新：」或「索引步驟：」開頭，已做的清理列在 `steps`，看板不動；修好後加 `--pr <n>` 重跑。
- [`dispatch.sh`](../tools/ops/dispatch.sh)：建 worktree 之前，從 `origin/master`（預設）派工時先把管理 checkout 快轉到剛 fetch 的 `origin/master`（條件同上；不符合就 exit 1），再驗證最近 5 次合併改到的檔；過期先重建一次，仍過期就 exit 1，什麼都不建、不送。所以「合併後、`close_task.sh` 之前就派下一張」時，索引也會跟上新 worktree 的起點。`--base` 是長期整合分支時不快轉，索引只對得上 master。
- 兩支腳本整份包在一個 `{ … }` 區塊裡：bash 先讀完整份檔才執行，快轉改到腳本自己時不會讀到新檔的半截（#704 review）。
- 一般重建後仍過期、而且原因全是下表的 `mtime` 時，再強制重建一次（`delete_project`＋`index_repository`，master 約 11 秒，這段時間查不到這個 project），之後還過期就失敗。
- CLI 不存在、逾時（預設 300 秒）、輸出解析不出 JSON、回 `isError`，都算失敗並印出原因，不當成沒過期。CLI 路徑、project 名稱、逾時與「最近幾次合併」在 [`coordinator_lib.sh`](../tools/ops/coordinator_lib.sh) 的 `cbm_*`，可用 `STOCK_CBM_CLI`、`STOCK_CBM_PROJECT`、`STOCK_CBM_TIMEOUT`、`STOCK_CBM_RECENT_MERGES` 覆寫。

判定（`coordinator_json.py` 的 `index_verdict`；引擎的回答來自 `check_index_coverage` 與 `query_graph` 的 `MATCH (f:File) RETURN f.file_path`，`indexed_at` 是引擎回的時間，不是腳本自己寫的戳記）：

| 引擎回什麼 | 判定 |
| --- | --- |
| 檔案已不在 checkout（這次刪掉的） | 不列入（`deleted`） |
| `status` 是 `excluded`（`.gitignore`、`.cbmignore`、忽略的副檔名） | 不列入（`excluded`） |
| 檔案在，`freshness` 卻是 `missing` | 過期（`missing`） |
| 引擎有收這個檔（在 `File` 清單裡），檔案 mtime 晚於 `indexed_at` | 過期（`mtime`）；不晚於就通過 |
| 引擎沒收這個檔，但有收同副檔名（沒副檔名就比檔名，如 `Dockerfile`）的其他檔 | 過期（`not_tracked`：新檔沒進索引） |
| 引擎沒收這個檔，也沒收任何同類型的檔（例如 `.txt`） | 不列入（`unsupported`） |
| 回答沒有 `indexed_at` 或解析不出時間、`File` 清單是空的或列數對不上、少回某個路徑 | 失敗 |

`freshness` 的 `metadata_changed` 不當判定依據：2026-11-14 實測引擎 0.10.8（Windows）對剛建好、沒改過的檔也回 `metadata_changed`（[#704 提問](https://github.com/YiCheng0608/stock-lab/issues/704#issuecomment-6874992164)）；同版引擎在只有 mtime 變、或只改了它不收的檔時，重建不更新 `indexed_at` 與它記錄的 mtime（[#704 回報](https://github.com/YiCheng0608/stock-lab/issues/704#issuecomment-6875050095)），所以才有強制重建。引擎修好、`metadata_changed` 只在檔案真的變了時才回之後，可以改回直接看 `freshness`。
