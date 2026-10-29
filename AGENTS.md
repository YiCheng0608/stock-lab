<!-- owns: 協作角色、任務生命週期、並行上限、工程原則、文件原則、規則與強制手段、上下文壓縮保留、流程變更 -->
# 專案協作規則

本文管角色與原則；操作、欄位與模板見[GitHub 工作手冊](docs/GITHUB_WORKFLOW.md)；產品方向與版本範圍見[ROADMAP](docs/ROADMAP.md)；前端視覺見[設計規範](docs/DESIGN_SYSTEM.md)。

## 目標

用最少的角色與步驟把 ROADMAP 的 V1 做出來：每個任務一個 Issue、一個 worktree、一個 PR，CI 通過並經 review 後合併。流程服務產品，不反過來。

## 工具

- **GitHub Issues** 是任務來源：目標、範圍、驗收條件（AC）、決策與結果都記在 Issue。Project 看板只顯示狀態，不另建表。
- **Repo** 保存程式、文件、可重建測試。一次性命令、實測紀錄、待辦留 Issue。
- **Orca** 管 worktree 與 terminal；每個任務在自己的 worktree 工作，不在管理 checkout（`master`）改檔。排程只從獨立的發佈 checkout 執行，正式資料目錄在 repo 外（[OPERATIONS §6](docs/OPERATIONS.md#6-排程)）；agent 不得在任何 checkout 跑 `git clean -x`，不得刪資料目錄。
- **codebase-memory** 先查索引再讀原檔；MCP 斷線改用同引擎 CLI，不重建整份索引。
- 回覆使用者一律繁體中文、台灣用語；程式、指令、路徑維持原樣。

## 角色

| 角色 | 預設模型／effort | 做什麼 |
| --- | --- | --- |
| 統籌 | `claude-opus-5-5`／`medium`，`--autocompact 400k` | 同時只有一個，一律由 agent 依[工作手冊](docs/GITHUB_WORKFLOW.md#統籌-session)以 Orca 開啟：現任統籌自行換手；沒有統籌時使用者對任一 Claude session 說「開統籌」，由它開。拆任務、建 Issue、派工、review、合併、更新 ROADMAP 與文件、回報進度；使用者不在時依[無人值守運作](docs/GITHUB_WORKFLOW.md#無人值守運作)持續推進。 |
| 工程師 | `claude-opus-5-5`／`high`（簡單任務可用 `claude-sonnet-5-5`／`xhigh`） | 每個任務一個 session，在自己的 worktree 實作、自測、寫文件、開 PR、處理 review 與 CI。 |

- 不設常駐 QA、文件、索引／Git 角色。需要獨立驗證時由統籌在 PR 上跑 `/code-review` 或另開一個 review session，見[工作手冊](docs/GITHUB_WORKFLOW.md#review-與合併)。
- 統籌可以自己當工程師做小任務；大任務或可並行的任務派給工程師 session。
- 使用者只決定產品取捨：範圍、來源與付費、刪除資料、部署、對外操作。其餘由統籌自行推進，不逐步請示。

## 任務生命週期

1. **建 Issue**：目標、範圍與不做事項、3～5 條可驗收的 AC、依賴、對應 ROADMAP 里程碑；套 V1 milestone。要不要建 Issue 依工作手冊的[分流](docs/GITHUB_WORKFLOW.md#分流)。
2. **開 worktree**：以 Orca 從最新 `origin/master` 建 `task/<issue>-<slug>`，啟動工程師 session 並送任務全文。
3. **實作與自測**：工程師在 worktree 完成程式、測試與文件；跑後端 `pytest`、`ruff`、前端測試與 build（見[工作手冊](docs/GITHUB_WORKFLOW.md#本機檢查)）。
4. **PR**：描述做了什麼、怎麼驗、未做什麼；`Closes #<issue>`。CI 必須綠。
5. **Review 與合併**：統籌 review（必要時獨立 review），以 merge commit 合併；不 squash／rebase、不直接 push master。
6. **結案**：合併後 master CI 綠即關 Issue、移除 worktree；遠端 branch 由 GitHub 自動刪。master CI 紅就先修，不開新功能。

並行以不互改同一組檔案為原則，建議同時進行的任務不超過 3 個；「做完、只等合併」的任務（PR CI 綠、review 完、工程師不再改）不算在內（使用者 2026-10-26 決定）。衝突由後合併者在自己的 branch 解決，不全選一方。

## 工程原則

- **資料**：只用免費公開來源；每筆保存來源與資料日期；缺資料留空並標無資料，不補零、不混來源。DB、raw、金鑰、私人資料不進 Git。
- **顯示**：有資料就顯示並標來源與日期；LLM 產出與來源事實分欄並標「推論」。詳見 [ROADMAP 顯示原則](docs/ROADMAP.md#v1-範圍基線2026-10-17-核定)。
- **LLM**：只做新聞摘要、關聯、方向判讀與進出點說明；以本機 Claude Code 無介面模式（`claude -p`）用使用者的訂閱帳號呼叫，不接 API 金鑰、不計費；每次呼叫記模型與提示版本。
- **測試**：單元與計算用小 fixture 或記憶體 DB；需要磁碟時用隔離暫存檔並在測試後清理；真實資料驗收記日期與範圍。
- **不做**：自動下單、盤中即時、付費來源、未驗證勝率。部署、正式 DB、外部帳戶需使用者同意。
- **AC 不自行降低**：做不到就在 Issue 說明並請統籌決定拆分或延後。

## 前端

所有前端工作遵守 [DESIGN_SYSTEM](docs/DESIGN_SYSTEM.md)：token、字體、元件、圖表與狀態的視覺規則都以該文件為準，不在元件內寫死色碼；PR 附桌面與手機截圖。要偏離先在 Issue 說明並經統籌同意，同意後先改 DESIGN_SYSTEM 再實作。

## 文件

- ROADMAP 寫方向、版本範圍與已完成能力；規格文件（PRODUCT_SPEC、V1_SPEC、NEWS_SPEC 等）只寫確定的契約；過程與待辦留 Issue。
- 功能完成的同一個 PR 更新受影響文件；內容失效時同批刪除指向它的連結。
- 同一規則只寫一次，其他處放連結。

## 規則與強制手段

會擋下違規的檢查列在這裡；強制手段寫「無」的規則只靠文件與 review。新增檢查時同一個 PR 補一列。hook 有問題時 revert `.claude/settings.json` 即可停用。

| 規則 | 強制手段 | 檔案／設定 |
| --- | --- | --- |
| 改產品或高風險路徑的 PR 要對應 Issue（`Closes #<issue>`） | CI `pr` 規則 a | `tools/ci/checks.py`（`needs_issue`）、`.github/workflows/ci.yml`（`pr` job） |
| 「AC 逐條結果」每條要有內容 | CI `pr` 規則 b | `tools/ci/checks.py`（`ac_results`） |
| AC 證據是命令與輸出、查詢結果或截圖連結，只寫「通過」不算 | 無（統籌 review；規則 b 只查有沒有內容） | `docs/GITHUB_WORKFLOW.md` |
| 前端變更附截圖 | CI `pr` 規則 c | `tools/ci/checks.py`（`frontend_source`） |
| 高風險路徑要獨立 review | CI `pr` 規則 d（`independent-review` label） | `tools/ci/checks.py`（`HIGH_RISK_PATHS`） |
| 獨立 review 寫出變更安全所依據的事實與證明方式 | 無 | `docs/GITHUB_WORKFLOW.md` |
| commit 訊息不得有 closing keyword | CI `pr` 規則 e | `tools/ci/checks.py`（`CLOSING_KEYWORD`） |
| 改 PR 本文或 label 後重新檢查 | CI `pull_request.types` 含 `edited`、`labeled`、`unlabeled` | `.github/workflows/ci.yml` |
| PR 套模板 | 部分：規則 a、b 檢查 `Closes` 與 AC 區，其餘欄位無 | `.github/pull_request_template.md` |
| 不在 master 管理 checkout 改檔 | Claude Code PreToolUse hook（Edit、Write） | `tools/ops/agent_guard.cjs`、`.claude/settings.json` |
| 不跑 `git clean -x`／`-X` | PreToolUse hook（Bash、PowerShell） | `tools/ops/agent_guard.cjs`、`.claude/settings.json` |
| 不用裸 `git stash`、`git stash pop`、`git stash clear` | PreToolUse hook（Bash、PowerShell） | `tools/ops/agent_guard.cjs`、`.claude/settings.json` |
| 不強推（含 `--force-with-lease`） | PreToolUse hook（Bash、PowerShell）；master 另有主線規則 | `tools/ops/agent_guard.cjs`、[主線規則](https://github.com/YiCheng0608/stock-lab/rules/24769026) |
| 不刪資料目錄 | PreToolUse hook：遞迴刪除且命令含 `stock-lab-data`／`STOCK_DATA_DIR` | `tools/ops/agent_guard.cjs`、`.claude/settings.json` |
| agent 不讀、不搜、不複製、不改 `.env`（檔名 `.env` 或不以 `.example` 結尾的 `.env.*`，任何目錄）；`.env.example` 放行（#353） | PreToolUse hook（Read、Edit、Write、NotebookEdit、Grep、Glob、Bash、PowerShell、Monitor、Artifact、ArtifactData、DesignSync、codebase-memory）：路徑或命令提到 `.env`、連結或 8.3 短檔名指到 `.env`（每個工具都解析）、glob 會展開到 `.env`、遞迴讀取（含 `git grep --no-index`／`--untracked`、`find -exec`、`fd -x`）的目錄底下有 `.env`（Grep 略過 git ignore 的；走不完就擋）、會印出 env file 值的 docker 命令（`compose config` 只放行 `config` 後面直接寫的 `-q`／`--quiet`、`--no-interpolate`、`--services`，不是前一個選項的值，且不帶 `-o`／`--output`、`--environment`、`--variables`、帶 `=` 的安全旗標或 `=false` 類的值；`inspect` 要 `--format` 且不取 `Env`、整個 `.Config`、`.` 或 `$`；`run`／`exec` 的參數有 `env`、`printenv`、`environ`；#360）、`powershell -EncodedCommand`；hook 出錯或輸入格式不對也擋（exit 2）。hook 逾時 Claude Code 會放行（#353 實測），所以 settings 明寫 `timeout: 60`，hook 對超過 5 MB、或 heredoc 以外超過 10 萬字元的命令直接擋，最壞約 1 秒內結束；node 測試 `.env rules`（docker 命令見 `docker commands that print …`，#360）。只防不小心讀到，防不了刻意繞過（例如先寫腳本再執行）；codebase-memory 只檢查輸入，回傳內容不含 `.env` 靠索引器不收 git ignore 的檔 | `tools/ops/agent_guard.cjs`（`envFileDenial`、`grepDenial`、`envSegmentDenial`、`dockerDenial`）、`.claude/settings.json`、`tools/ops/agent_guard.test.cjs`、`docs/GITHUB_WORKFLOW.md`（任務流程第 3 步） |
| 經 PR、只用 merge commit、CI `required` 綠才合併 | 主線規則 | [主線規則](https://github.com/YiCheng0608/stock-lab/rules/24769026) |
| 合併後刪遠端 branch | GitHub repo 設定 `delete_branch_on_merge=true` | repo 設定（`gh api repos/YiCheng0608/stock-lab --jq .delete_branch_on_merge`） |
| 依分流決定是否建 Issue | 部分：第 1、2 類由 CI `pr` 規則 a、d | `docs/GITHUB_WORKFLOW.md`（分流） |
| Python lint 與格式（#225） | CI `repository` job 的 `lint` step | `tools/ci/checks.py`（`LINT_COMMANDS`）、`ruff.toml` |
| Alembic head 只有一個來源（#225） | 後端測試 `test_operations_doc_names_the_code_head` | `backend/app/migration_revisions.py`、`backend/tests/test_database_readiness.py` |
| `git blame` 略過全檔格式化 commit（#225） | 無（每個 checkout 手動設 `blame.ignoreRevsFile`） | `.git-blame-ignore-revs` |
| worktree 外暫存目錄路徑寫進 PR | 無（PR 模板欄位） | `.github/pull_request_template.md` |
| 統籌接手時核對前任標「已完成」的事 | 無 | `docs/GITHUB_WORKFLOW.md`（統籌 session） |
| 同類錯誤第二次發生就編成檢查 | 無（流程用 encode-lesson skill，#228） | `docs/GITHUB_WORKFLOW.md`（任務流程第 6 步）、`.claude/skills/encode-lesson/SKILL.md` |
| 五個主導航在假資料庫上通過 features 標「CI」的檢查（#243） | CI `verify` job（`required` 依賴它；已知產品缺陷列在 `KNOWN_FAILURES` 並附 Issue 與失敗訊息片段，訊息不符照常失敗，#251） | `tools/verify/page_checks.py`、`.github/workflows/ci.yml`（`verify` job） |
| `KNOWN_FAILURES` 每列綁 stock-lab Issue 連結、失敗訊息片段與 `expires`，`expires` 最晚是加入該列的 commit 日起 30 天；過了 `expires` 該列不算，再命中照常失敗（#311） | 後端測試 `test_known_failures_expire_within_30_days_of_the_commit_that_added_them`（加入日取 `git log -1 --format=%cs -S`）、`test_known_problems_flag_a_missing_or_late_expires`、`test_page_checks_exits_1_on_an_expired_known_failure`；CI `verify` job | `tools/verify/page_checks.py`（`Known`、`known_problems`、`judge`）、`backend/tests/test_verify_checks.py`、`.claude/skills/verify-stock-lab/features/README.md`（已知失敗） |
| verify 結果三態：上游沒通過的檢查記「無法判定（上游 X）」、不計失敗；假資料庫上無法判定也讓 CI 失敗（#251） | 後端測試 `test_verify_tristate.py`（10/24 真資料情境）；CI `verify` job | `tools/verify/page_checks.py`（`OWNERS`、`AFTER`、`judge`、`blocking`） |
| 空狀態與 DB／其他 API 交叉核對，另一處有資料就判失敗；個股選股依序備援（#251） | 後端測試 `test_verify_tristate.py`；CI `verify` job | `tools/verify/page_checks.py`（`empty_board`、T7、T9、A4、`Run.stock`） |
| master 每晚與手動觸發跑 CI 全套，`verify` 驗五頁（#251） | CI `schedule`、`workflow_dispatch`；後端測試 `test_nightly_and_manual_runs_verify_every_page` | `.github/workflows/ci.yml`、`tools/verify/verify_plan.py`（`FULL_EVENTS`） |
| features 標「人工」的檢查有寫死的抽樣規則（#251） | `page_checks.py` exit 2；後端測試 `test_every_manual_check_has_a_sampler` | `tools/verify/page_checks.py`（`MANUAL`、`registry_problems`） |
| G7 真資料 verify 用發佈 branch `release/v1` 上已 commit 的程式，5 日窗口頭尾各跑一次；人工檢查由另一個 session 判讀（#251、#260） | 部分：`page_checks.py --g7` 在有未 commit 改動或 HEAD 不等於 `origin/release/v1`（`G7_REF`）時 exit 2（#288）；時點與獨立判讀無 | `tools/verify/page_checks.py`（`g7_problems`、`G7_REF`）、`docs/GITHUB_WORKFLOW.md`（任務流程第 6 步）、`.claude/skills/verify-stock-lab/SKILL.md` |
| 發佈 branch `release/*` 不能刪、不能強推，只經 PR（merge commit）且 CI `required` 綠才合併；CI 對 `release/**` 的 PR 與 push 都跑（#288） | GitHub ruleset（`release/*`）；CI `pull_request`／`push` 的 branches | repo ruleset、`.github/workflows/ci.yml` |
| features 標「CI」的檢查都有實作、有實作的都標「CI」（#243） | CI `verify` job（`page_checks.py` 不一致就 exit 2）；後端測試 `test_every_ci_check_in_features_is_implemented` | `tools/verify/page_checks.py`（`registry_problems`）、`backend/tests/test_verify_checks.py` |
| `checks.py repository` 檢查工作樹，含未 commit 的合併結果（#228） | CI `repository` job 的 unittest `RepositoryWorkingTree` | `tools/ci/checks.py`（`repository_checks`、`changed_paths`）、`tools/ci/test_checks.py` |
| 每份 Markdown（不只改到的）的相對連結與指向 master 的絕對連結要找得到檔案，錨點要有標題或 HTML id 產生；`docs/**/*.md` 與 `AGENTS.md` 第一行是 `<!-- owns: … -->`，概念在全部文件間不重複（#319） | CI `repository` job 的 `repository` step；unittest `AnchorTests`、`OwnsTests`、`RepositoryWorkingTree` | `tools/ci/checks.py`（`markdown_errors`、`heading_slug`、`owns_errors`、`documentation_errors`）、`tools/ci/test_checks.py` |
| CI `verify` job 只驗改動影響的頁，依 features「驗證範圍」選頁；不驗時 job 仍 success（#245） | CI `verify` job 的 Plan step；後端測試 `test_verify_plan.py`（各類改動的頁面範圍、前端檔清單涵蓋 import 它的檔） | `tools/verify/verify_plan.py`、`.claude/skills/verify-stock-lab/features/README.md`（驗證範圍）、`.github/workflows/ci.yml`（`verify` job） |
| `backend/app/api.py` 每個 route 對到某頁或寫明排除與理由（#245） | 後端測試 `test_every_api_route_is_on_a_page_or_excluded`、`test_api_routes_match_the_router` | `tools/verify/verify_plan.py`（`route_problems`）、`backend/tests/test_verify_plan.py` |
| verify 抓到的 bug，修的同一個 PR 要加一條會失敗的檢查（#245） | 無（統籌 review） | `docs/GITHUB_WORKFLOW.md`（任務流程第 6 步） |
| 排程 job 不用 WMI 讀記憶體：系統忙時 WMI 取消呼叫，job 連日誌都沒寫就停（#246）；#313 起記憶體由 Python job 讀（Windows `GlobalMemoryStatusEx`、Linux `/proc/meminfo`） | 後端測試：`test_the_job_source_has_no_wmi_call`、`test_the_wrapper_source_has_no_wmi_call`（CI 也跑）；Windows 本機另有 harness 讓 WMI 一律失敗後經轉呼叫腳本跑 job（`test_the_wrapper_reads_free_memory_without_wmi`，CI 跳過） | `backend/worker/job.py`（`free_memory_mb`）、`tools/Invoke-WorkerJob.ps1`、`backend/tests/test_worker_job.py`（`WMI_CALL`）、`backend/tests/test_worker_job_scripts.py`（`NO_WMI_MODULE`、`WMI_COMMAND`） |
| 排程 job 同種一次一個，拿不到鎖記 `already_running`；被強制終止（`taskkill /F`、`kill -9`）時 worker 一起結束、鎖不殘留；到單次上限結束 worker；看門狗用同一把檔案鎖（#313，取代 #224） | 後端測試 `test_worker_job.py`（`test_a_second_daily_job_records_already_running`、`test_a_killed_job_takes_its_worker_along_and_leaves_no_lock`、`test_daily_is_killed_at_the_time_limit`；Windows 分支本機跑）、`test_watchdog.py`（`test_a_killed_watchdog_leaves_no_lock_behind`） | `backend/worker/job.py`（`FileLock`、`_ProcessTree`）、`tools/ops/watchdog.sh` |
| 表格一律經共用 `DataTable`，數字欄 th 與 td 同帶 `num`；同欄固定位數；成交量與法人買賣超為整數張（#267） | 前端測試 `tables.test.tsx`（掃 `src` 不得手寫 `<table>`／`<th>`／`<td>`、逐表核對 th／td 對齊與數字格式） | `frontend/src/components/ui/Table.tsx`、`frontend/src/units.ts`、`frontend/src/tables.test.tsx` |
| 日期一律 `YYYY/MM/DD`、日期時間 24 小時 `HH:mm`；只有 `dates.ts` 用 `Intl.DateTimeFormat`（#270） | 前端測試 `copy.test.tsx`（掃 `src` 的 `Intl.DateTimeFormat`、渲染 badge／K 線／計算時間） | `frontend/src/dates.ts`、`frontend/src/copy.test.tsx` |
| 候選卡、族群頁、研究條件的就地術語有詞條，前端副本與 API 詞彙一致（#270） | 前端測試 `copy.test.tsx`；後端測試 `test_glossary.py` | `frontend/src/glossary.ts`、`backend/app/glossary.py`、`frontend/src/components/Term.tsx` |
| 官方行情的普通股列不悄悄丟掉：主檔外的列寫入既有標的或記 `unmatched_bar`（#212） | 後端測試 `test_collect_has_no_silent_skip_of_a_quote_row`、`test_collect_writes_quotes_of_a_stored_instrument_missing_from_the_lists`、`test_tpex_quotes_keep_ordinary_shares_outside_the_lists` | `backend/worker/pipeline.py`（`collect`）、`backend/worker/sources.py`（`is_common_stock_code`）、`backend/tests/test_instrument_lifecycle.py` |
| 標的狀態同步被 5% 防呆略過時由統籌處理（#212） | 看門狗資料不變量 `invariant_status_sync`；後端測試 `test_a_skipped_status_sync_is_commented_until_a_later_sync_applies` | `tools/ops/watchdog_helper.py`、`tools/ops/watchdog.sh`、`docs/OPERATIONS.md`（§6.1） |
| verify 假資料庫的下市／轉市列與 worker 寫出的一致（#212） | 後端測試 `test_the_verify_fixture_lifecycle_rows_are_what_the_worker_writes` | `tools/verify/fixture_data.py`（`LIFECYCLE`）、`backend/tests/test_instrument_lifecycle.py` |
| 結案腳本在 PR 未合併或 master CI 非綠時零刪除；`--extra-dir` 不得是 repo 與各 worktree、`$HOME`、磁碟根、`stock-lab-data`、`STOCK_DATA_DIR`，字面與解析連結後的實際路徑都比、兩者不同（經過 junction／symlink、8.3 短檔名）就拒絕，刪除前再查一次；junction 先拆；orca／gh／git 讀取失敗也拒絕（#282、#283 review） | 後端測試 `test_coordinator_scripts.py`（假 orca／gh／git，路徑一律 `tmp_path` 替身） | `tools/ops/close_task.sh`、`tools/ops/coordinator_lib.sh`（`guard_dir`）、`backend/tests/test_coordinator_scripts.py` |
| 結案腳本刪本地 branch 時，`branch -D` 失敗但 `show-ref` 讀回已不存在（`orca worktree rm` 先刪了）記 `branch_already_gone` 並繼續；branch 仍在才 exit 3、不刪 `--extra-dir`、不設看板（#290） | 後端測試 `test_close_task_takes_a_branch_orca_already_deleted_as_done`、`test_close_task_stops_when_the_branch_cannot_be_deleted` | `tools/ops/close_task.sh`（`branch_gone`）、`backend/tests/test_coordinator_scripts.py` |
| 長期整合分支 `feat/docker` 不能刪、不能強推，只經 PR（merge commit）且 CI `required` 綠才合併；長期整合分支清單只在 `close_task.sh` 的 `integration_branches`，CI 對清單裡每個分支的 PR 與 push 都跑（#332） | GitHub ruleset 26027657（`feat/docker`，規則同主線規則 24769026）；CI `pull_request`／`push` 的 branches；unittest `test_ci_runs_on_every_long_lived_branch`（`ci.yml` 兩份清單等於 master、`release/**` 加 `integration_branches`） | repo ruleset、`.github/workflows/ci.yml`、`tools/ops/close_task.sh`（`integration_branches`）、`tools/ci/test_checks.py`（`WorkflowTriggers`）、`docs/GITHUB_WORKFLOW.md`（長期整合分支） |
| `dispatch.sh --base origin/<branch>` 先 fetch 該分支，新 worktree 的 HEAD 不等於它的最新 commit 就不開 terminal；不帶 `--base` 時與 `origin/master` 的流程相同；`--base` 不是 `origin/<branch>` 就 exit 64（#332） | 後端測試 `test_dispatch_from_another_base_starts_the_worktree_at_its_tip`、`test_dispatch_without_base_fetches_and_checks_origin_master`、`test_dispatch_opens_no_terminal_when_the_worktree_is_not_at_the_base`、`test_dispatch_refuses_a_base_that_is_not_origin_branch` | `tools/ops/dispatch.sh`、`backend/tests/test_coordinator_scripts.py` |
| 結案腳本以 PR 的 `baseRefName` 為目標分支：查該分支上 merge commit 的 CI 與該分支最新一次 CI、本地 branch 要在 `origin/<目標分支>` 裡；目標只能是 master 或 `integration_branches`（`release/*` 等其他分支拒絕）；未合併、CI 非綠、讀不到目標分支時零刪除。目標不是 master 時，全部前提成立後、刪除前 `gh issue close`（GitHub 只在預設分支處理 `Closes`）；目標是 master 或前提不成立時不關；Issue 已關（重跑）就不再關、照常清理；關不掉且讀回仍開就零刪除（#332） | 後端測試 `test_close_task_checks_ci_on_the_branch_the_pr_merged_into`、`test_close_task_checks_master_ci_for_a_pr_into_master`、`test_close_task_deletes_nothing_when_a_pr_into_feat_docker_is_not_done`、`test_close_task_deletes_nothing_when_the_branch_is_not_in_feat_docker`、`test_close_task_deletes_nothing_without_a_readable_target_branch`、`test_close_task_leaves_the_issue_open_when_a_later_check_fails`、`test_close_task_deletes_nothing_when_the_issue_cannot_be_closed`、`test_close_task_no_board_leaves_the_issue_open`、`test_close_task_refuses_a_pr_into_a_branch_that_is_not_long_lived`、`test_close_task_rerun_goes_on_when_the_issue_is_already_closed`、`test_close_task_takes_a_failed_close_of_an_issue_now_closed_as_closed` | `tools/ops/close_task.sh`（`base_branch`、`integration_branches`、`issue_state`）、`backend/tests/test_coordinator_scripts.py` |
| 結案腳本刪任務的 Docker 資源：只刪 tag 是 `t<issue>`／`t<issue>-*`、repository 以 `t<issue>-`／`task-<issue>-` 開頭的 image，與名稱以 `t<issue>`／`task-<issue>` 開頭（數字後接 `-`、`_`、`.` 或結尾）的已停止容器、volume、network；image 以 `repository:tag` 刪、不加 `-f`；有容器在跑且屬於或用到這些資源就全部不刪；`image prune`／`builder prune` 只在任務是 Docker 子單或有資源、沒有容器在跑、其他 worktree 都不是 Docker 任務（有 `t<n>` 資源或含整合分支自己的 commit，讀不出來也算）時跑，`--no-board` 不跑；每次 docker 呼叫有逾時，沒有 docker 或 daemon 無回應只記 `docker_skipped`、不讓結案失敗；結案前的檢查與 Docker 以外的刪除不變（#360） | 後端測試 `test_close_task_removes_the_docker_resources_named_for_the_task`、`test_close_task_keeps_the_docker_resources_while_one_runs`、`test_close_task_leaves_the_prune_to_the_last_docker_task`、`test_close_task_prunes_when_no_other_worktree_is_a_docker_subtask`、`test_close_task_prunes_only_for_a_docker_task`、`test_close_task_skips_docker_when_it_does_not_answer`、`test_close_task_reports_a_docker_resource_it_could_not_delete`（假 docker；拒絕結案的測試另驗沒有任何 docker 呼叫） | `tools/ops/coordinator_lib.sh`（`docker_cleanup`、`owned_name`、`docker_task_issues`）、`tools/ops/close_task.sh`、`backend/tests/test_coordinator_scripts.py`、`docs/GITHUB_WORKFLOW.md`（任務流程第 6 步） |
| 後端 pytest 全綠時刪掉該次的 basetemp（含 `--basetemp`），測試建的假 repo 不留在 worktree 外暫存目錄，刪除重試不經連結 chmod；`--extra-dir` 的 `.git` 防呆不放寬，拒絕時寫出找到的 `.git` 路徑（#290） | 後端測試 `test_a_green_pytest_run_leaves_no_repository_in_its_basetemp`、`test_a_killed_pytest_run_leaves_only_the_repository_of_the_test_it_was_in`、`test_basetemp_cleanup_does_not_chmod_a_link` | `backend/tests/conftest.py`（`pytest_sessionfinish`、`_retry_writable`）、`tools/ops/coordinator_json.py`（`_git_inside`）、`backend/tests/test_coordinator_scripts.py` |
| 後端 pytest 沒全綠時也不留假 repo：每個測試結束（失敗也算）刪掉它 tmp_path 裡的 `.git`，session 沒全綠或被中斷時再掃整個 basetemp；其他檔案留著除錯；不進 junction／symlink，`.git` 本身是連結就只拆連結（#304） | 後端測試 `test_a_failed_run_then_a_green_run_on_another_basetemp_leave_no_repository`、`test_a_killed_pytest_run_leaves_only_the_repository_of_the_test_it_was_in`、`test_a_failed_session_keeps_its_basetemp_without_a_repository`、`test_dropping_repositories_does_not_follow_a_link` | `backend/tests/conftest.py`（`isolate_runtime_paths`、`pytest_sessionfinish`、`_drop_repositories`、`_delete`）、`backend/tests/test_coordinator_scripts.py` |
| 訊號的規則最早執行日只由官方休市表推算，不讀之後的日線；休市表只有一套分類規則；最新訊號日有訊號缺這個日期時由統籌處理（#294） | 後端測試 `test_trading_calendar.py`（有／沒有後續日線結果相同、缺年度留空並計入 `signals_without_date`、backfill 剛好排除 2025～2026 的 45 個休市日、不排除交易日提示與 `unknown`）；看門狗資料不變量 `invariant_execution_calendar` | `backend/app/trading_calendar.py`、`backend/worker/pipeline.py`（`_next_execution_date`）、`tools/ops/watchdog_helper.py`、`tools/ops/watchdog.sh` |
| 個股策略總表的成立價位只讀 `signals`、觀察價位只讀 `strategy_levels`，兩者不混；沒有條件價位列時回空不補值；觀察價位在「條件未成立・觀察價位」標籤之下；AI 說明只在候選列；量的門檻下限進位、上限捨去；條件門檻文案取自 API 的 `threshold`（#274） | 後端測試 `test_strategy_board.py`；前端測試 `stock/strategyBoard.test.tsx`；CI `verify` job（stocks S10） | `backend/app/strategy_board.py`、`frontend/src/stock/StrategyBoardPanel.tsx`、`tools/verify/page_checks.py`（`s10`） |
| `strategy_levels` 步驟失敗不改 run 狀態，由看門狗留言（#274，#293 review L2） | 看門狗資料不變量 `invariant_strategy_levels`；後端測試 `test_a_failed_strategy_levels_step_is_commented` | `tools/ops/watchdog_helper.py`（`_strategy_levels`）、`tools/ops/watchdog.sh` |
| `conditions_json` 只存跟策略預設值不同的欄位，預設值改了就要升 `levels_version`（#274，#293 review L3） | 後端測試 `test_the_condition_defaults_are_pinned_to_the_levels_version`（以 `STRATEGY_LEVELS_VERSION` 為 key）、`test_stored_conditions_omit_the_defaults_and_read_back_whole`、`test_a_signal_of_another_formula_version_is_skipped`、`test_a_row_of_another_formula_version_is_not_read` | `backend/app/strategies/levels.py`（`condition_defaults`、`compact_conditions`、`expand_conditions`）、`backend/app/strategies/__init__.py`（`current_strategy`） |
| 行動頁第 3 級「接近成立」只讀 `strategy_levels` 的條件與價格差距，門檻與排序屬 `action_tier_v1`；列表不帶任何價位；條件碼只列在策略 registry 與前端 `strategyBoard.ts`；`no_condition` 的主要原因只讀訊號判定，有無 `strategy_levels` 結果相同（#279） | 後端測試 `test_action_tiers.py`（`test_the_nearness_rule`、`test_the_tier_rules_are_pinned_to_the_version`、`test_the_near_tier_through_the_api_carries_no_level`）、`test_condition_copy_source.py`、`test_product.py`（`test_the_decision_summary_does_not_read_strategy_levels`）；前端測試 `copy.test.tsx`；CI `verify` job（actions A11～A13） | `backend/app/decision.py`（`strategy_nearness`、`ACTION_NEAR_PRICE_GAP`、`_fewest_unmet`）、`backend/app/strategies/base.py`（`short_label`）、`frontend/src/stock/strategyBoard.ts`（`CONDITIONS`）、`tools/verify/page_checks.py`（`a11`～`a13`）、`tools/ci/checks.py`（`BACKEND_READ_FILES`） |
| 研究回測不帶覆寫時與現行 backtest 完全相同；每組 ablation 只移除一個條件（資料要求不變）；研究 run 逐日 commit、分批追蹤，中途失敗後重跑與一次跑完相同；研究腳本拒跑正式 DB（含 hard link）、台北 18:30～21:30 與可用記憶體不足，重播中進入該時段就在 commit 後停下（#318） | 後端測試 `test_strategy_ablation.py`（`test_an_evaluator_without_config_is_the_evaluator_with_the_canonical_config`、`test_an_ablation_drops_only_its_condition_reasons`、`test_a_research_backtest_matches_the_default_one_and_removes_one_condition_per_ablation`、`test_a_failed_research_run_rerun_matches_one_uninterrupted_run`、`test_a_research_run_commits_each_score_date`、`test_a_research_run_stops_at_the_daily_window_and_a_rerun_completes_it`）、`test_backtest_research.py`（`test_a_hard_link_to_the_production_file_is_refused`）；`backtest_research.py` exit 2 | `backend/app/strategies/ablation.py`、`backend/worker/pipeline.py`（`backtest`、`_ensure_strategies`、`_track_research_signals`、`_summarize_research_backtest`、`_pause_if`）、`tools/research/backtest_research.py`（`production_problem`、`window_check`） |
| 新聞頁、個股頁、今日頁的新聞 `ai` 只取目前提示版本（`worker.news_llm.PROMPT_VERSION`）的 `done` 結果，舊版本的結果即使較新也不顯示（#308） | 後端測試 `test_only_the_current_prompt_version_result_reaches_any_page`（`/news`、`/news/<id>`、`/dashboard`、`/stocks/<exchange>/<symbol>`） | `backend/app/api.py`（`news_ai_map`）、`backend/tests/test_news_llm.py` |
| 派工只在 `orca terminal wait --for tui-idle` 回 `satisfied:true` 後送任務；巡檢的 gh 呼叫不超過上限，不覆寫別的統籌一小時內的心跳（#282） | 後端測試 `test_coordinator_scripts.py` | `tools/ops/dispatch.sh`、`tools/ops/patrol.sh` |
| 後端不用已棄用的 `datetime.utcnow()`，現在時間（naive UTC，欄位 default 也是）一律用 `app.clock.utcnow()`，寫入 DB 的值與字串格式跟 `datetime.utcnow()` 相同（#374） | 後端測試 `test_nothing_calls_datetime_utcnow`（AST 掃 `backend/app`、`backend/worker`、`backend/tests`）、`test_a_default_stores_the_text_a_naive_utc_value_stores` | `backend/app/clock.py`、`backend/tests/test_clock.py` |

## 上下文壓縮時保留

任何 session 被壓縮時，摘要必須保留：手上任務的 Issue／PR 編號與目前步驟；使用者最近的決策與其 #1 留言 id；等待中的事件（CI、回報、回補）與對應 terminal／worktree；已承諾未做完的事；使用者給過的參考資料（連結、檔案）與它們代表什麼；自己的 session id 與 terminal handle；背景監看與巡檢 cron 是否仍在；心跳檔與壓縮計數檔的位置。不保留已結案任務的細節，那些在 GitHub。

## 流程變更

改本文或工作手冊由統籌開 PR，使用者同意後合併；不占任務名額。
