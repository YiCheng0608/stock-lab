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
| verify 結果三態：上游沒通過的檢查記「無法判定（上游 X）」、不計失敗；假資料庫上無法判定也讓 CI 失敗（#251） | 後端測試 `test_verify_tristate.py`（10/24 真資料情境）；CI `verify` job | `tools/verify/page_checks.py`（`OWNERS`、`AFTER`、`judge`、`blocking`） |
| 空狀態與 DB／其他 API 交叉核對，另一處有資料就判失敗；個股選股依序備援（#251） | 後端測試 `test_verify_tristate.py`；CI `verify` job | `tools/verify/page_checks.py`（`empty_board`、T7、T9、A4、`Run.stock`） |
| master 每晚與手動觸發跑 CI 全套，`verify` 驗五頁（#251） | CI `schedule`、`workflow_dispatch`；後端測試 `test_nightly_and_manual_runs_verify_every_page` | `.github/workflows/ci.yml`、`tools/verify/verify_plan.py`（`FULL_EVENTS`） |
| features 標「人工」的檢查有寫死的抽樣規則（#251） | `page_checks.py` exit 2；後端測試 `test_every_manual_check_has_a_sampler` | `tools/verify/page_checks.py`（`MANUAL`、`registry_problems`） |
| G7 真資料 verify 用發佈 branch `release/v1` 上已 commit 的程式，5 日窗口頭尾各跑一次；人工檢查由另一個 session 判讀（#251、#260） | 部分：`page_checks.py --g7` 在有未 commit 改動或 HEAD 不等於 `origin/release/v1`（`G7_REF`）時 exit 2（#288）；時點與獨立判讀無 | `tools/verify/page_checks.py`（`g7_problems`、`G7_REF`）、`docs/GITHUB_WORKFLOW.md`（任務流程第 6 步）、`.claude/skills/verify-stock-lab/SKILL.md` |
| 發佈 branch `release/*` 不能刪、不能強推，只經 PR（merge commit）且 CI `required` 綠才合併；CI 對 `release/**` 的 PR 與 push 都跑（#288） | GitHub ruleset（`release/*`）；CI `pull_request`／`push` 的 branches | repo ruleset、`.github/workflows/ci.yml` |
| features 標「CI」的檢查都有實作、有實作的都標「CI」（#243） | CI `verify` job（`page_checks.py` 不一致就 exit 2）；後端測試 `test_every_ci_check_in_features_is_implemented` | `tools/verify/page_checks.py`（`registry_problems`）、`backend/tests/test_verify_checks.py` |
| `checks.py repository` 檢查工作樹，含未 commit 的合併結果（#228） | CI `repository` job 的 unittest `RepositoryWorkingTree` | `tools/ci/checks.py`（`repository_checks`、`changed_paths`）、`tools/ci/test_checks.py` |
| CI `verify` job 只驗改動影響的頁，依 features「驗證範圍」選頁；不驗時 job 仍 success（#245） | CI `verify` job 的 Plan step；後端測試 `test_verify_plan.py`（各類改動的頁面範圍、前端檔清單涵蓋 import 它的檔） | `tools/verify/verify_plan.py`、`.claude/skills/verify-stock-lab/features/README.md`（驗證範圍）、`.github/workflows/ci.yml`（`verify` job） |
| `backend/app/api.py` 每個 route 對到某頁或寫明排除與理由（#245） | 後端測試 `test_every_api_route_is_on_a_page_or_excluded`、`test_api_routes_match_the_router` | `tools/verify/verify_plan.py`（`route_problems`）、`backend/tests/test_verify_plan.py` |
| verify 抓到的 bug，修的同一個 PR 要加一條會失敗的檢查（#245） | 無（統籌 review） | `docs/GITHUB_WORKFLOW.md`（任務流程第 6 步） |
| 排程 wrapper 不用 WMI 讀記憶體：系統忙時 WMI 取消呼叫，job 連日誌都沒寫就停（#246） | 後端測試：`test_the_wrapper_source_has_no_wmi_call`（CI 也跑）；Windows 本機另有 harness 讓 WMI 一律失敗後跑 wrapper（`test_the_wrapper_reads_free_memory_without_wmi`，CI 跳過） | `tools/Invoke-WorkerJob.ps1`、`backend/tests/test_worker_job_scripts.py`（`NO_WMI_MODULE`、`WMI_COMMAND`） |
| 表格一律經共用 `DataTable`，數字欄 th 與 td 同帶 `num`；同欄固定位數；成交量與法人買賣超為整數張（#267） | 前端測試 `tables.test.tsx`（掃 `src` 不得手寫 `<table>`／`<th>`／`<td>`、逐表核對 th／td 對齊與數字格式） | `frontend/src/components/ui/Table.tsx`、`frontend/src/units.ts`、`frontend/src/tables.test.tsx` |
| 日期一律 `YYYY/MM/DD`、日期時間 24 小時 `HH:mm`；只有 `dates.ts` 用 `Intl.DateTimeFormat`（#270） | 前端測試 `copy.test.tsx`（掃 `src` 的 `Intl.DateTimeFormat`、渲染 badge／K 線／計算時間） | `frontend/src/dates.ts`、`frontend/src/copy.test.tsx` |
| 候選卡、族群頁、研究條件的就地術語有詞條，前端副本與 API 詞彙一致（#270） | 前端測試 `copy.test.tsx`；後端測試 `test_glossary.py` | `frontend/src/glossary.ts`、`backend/app/glossary.py`、`frontend/src/components/Term.tsx` |
| 官方行情的普通股列不悄悄丟掉：主檔外的列寫入既有標的或記 `unmatched_bar`（#212） | 後端測試 `test_collect_has_no_silent_skip_of_a_quote_row`、`test_collect_writes_quotes_of_a_stored_instrument_missing_from_the_lists`、`test_tpex_quotes_keep_ordinary_shares_outside_the_lists` | `backend/worker/pipeline.py`（`collect`）、`backend/worker/sources.py`（`is_common_stock_code`）、`backend/tests/test_instrument_lifecycle.py` |
| 標的狀態同步被 5% 防呆略過時由統籌處理（#212） | 看門狗資料不變量 `invariant_status_sync`；後端測試 `test_a_skipped_status_sync_is_commented_until_a_later_sync_applies` | `tools/ops/watchdog_helper.py`、`tools/ops/watchdog.sh`、`docs/OPERATIONS.md`（§6.1） |
| verify 假資料庫的下市／轉市列與 worker 寫出的一致（#212） | 後端測試 `test_the_verify_fixture_lifecycle_rows_are_what_the_worker_writes` | `tools/verify/fixture_data.py`（`LIFECYCLE`）、`backend/tests/test_instrument_lifecycle.py` |
| 結案腳本在 PR 未合併或 master CI 非綠時零刪除；`--extra-dir` 不得是 repo 與各 worktree、`$HOME`、磁碟根、`stock-lab-data`、`STOCK_DATA_DIR`，字面與解析連結後的實際路徑都比、兩者不同（經過 junction／symlink、8.3 短檔名）就拒絕，刪除前再查一次；junction 先拆；orca／gh／git 讀取失敗也拒絕（#282、#283 review） | 後端測試 `test_coordinator_scripts.py`（假 orca／gh／git，路徑一律 `tmp_path` 替身） | `tools/ops/close_task.sh`、`tools/ops/coordinator_lib.sh`（`guard_dir`）、`backend/tests/test_coordinator_scripts.py` |
| 結案腳本刪本地 branch 時，`branch -D` 失敗但 `show-ref` 讀回已不存在（`orca worktree rm` 先刪了）記 `branch_already_gone` 並繼續；branch 仍在才 exit 3、不刪 `--extra-dir`、不設看板（#290） | 後端測試 `test_close_task_takes_a_branch_orca_already_deleted_as_done`、`test_close_task_stops_when_the_branch_cannot_be_deleted` | `tools/ops/close_task.sh`（`branch_gone`）、`backend/tests/test_coordinator_scripts.py` |
| 後端 pytest 全綠時刪掉該次的 basetemp（含 `--basetemp`），測試建的假 repo 不留在 worktree 外暫存目錄，刪除重試不經連結 chmod；`--extra-dir` 的 `.git` 防呆不放寬，拒絕時寫出找到的 `.git` 路徑（#290） | 後端測試 `test_a_green_pytest_run_leaves_no_repository_in_its_basetemp`、`test_a_failed_pytest_run_keeps_its_basetemp_and_guard_dir_refuses_it`、`test_basetemp_cleanup_does_not_chmod_a_link` | `backend/tests/conftest.py`（`pytest_sessionfinish`、`_retry_writable`）、`tools/ops/coordinator_json.py`（`_git_inside`）、`backend/tests/test_coordinator_scripts.py` |
| 訊號的規則最早執行日只由官方休市表推算，不讀之後的日線；休市表只有一套分類規則；最新訊號日有訊號缺這個日期時由統籌處理（#294） | 後端測試 `test_trading_calendar.py`（有／沒有後續日線結果相同、缺年度留空並計入 `signals_without_date`、backfill 剛好排除 2025～2026 的 45 個休市日、不排除交易日提示與 `unknown`）；看門狗資料不變量 `invariant_execution_calendar` | `backend/app/trading_calendar.py`、`backend/worker/pipeline.py`（`_next_execution_date`）、`tools/ops/watchdog_helper.py`、`tools/ops/watchdog.sh` |
| 個股策略總表的成立價位只讀 `signals`、觀察價位只讀 `strategy_levels`，兩者不混；沒有條件價位列時回空不補值；觀察價位在「條件未成立・觀察價位」標籤之下；AI 說明只在候選列（#274） | 後端測試 `test_strategy_board.py`；前端測試 `stock/strategyBoard.test.tsx`；CI `verify` job（stocks S10） | `backend/app/strategy_board.py`、`frontend/src/stock/StrategyBoardPanel.tsx`、`tools/verify/page_checks.py`（`s10`） |
| `strategy_levels` 步驟失敗不改 run 狀態，由看門狗留言（#274，#293 review L2） | 看門狗資料不變量 `invariant_strategy_levels`；後端測試 `test_a_failed_strategy_levels_step_is_commented` | `tools/ops/watchdog_helper.py`（`_strategy_levels`）、`tools/ops/watchdog.sh` |
| `conditions_json` 只存跟策略預設值不同的欄位，預設值改了就要升 `levels_version`（#274，#293 review L3） | 後端測試 `test_the_condition_defaults_are_pinned`、`test_stored_conditions_omit_the_defaults_and_read_back_whole` | `backend/app/strategies/levels.py`（`condition_defaults`、`compact_conditions`、`expand_conditions`） |
| 派工只在 `orca terminal wait --for tui-idle` 回 `satisfied:true` 後送任務；巡檢的 gh 呼叫不超過上限，不覆寫別的統籌一小時內的心跳（#282） | 後端測試 `test_coordinator_scripts.py` | `tools/ops/dispatch.sh`、`tools/ops/patrol.sh` |

## 上下文壓縮時保留

任何 session 被壓縮時，摘要必須保留：手上任務的 Issue／PR 編號與目前步驟；使用者最近的決策與其 #1 留言 id；等待中的事件（CI、回報、回補）與對應 terminal／worktree；已承諾未做完的事；使用者給過的參考資料（連結、檔案）與它們代表什麼；自己的 session id 與 terminal handle；背景監看與巡檢 cron 是否仍在；心跳檔與壓縮計數檔的位置。不保留已結案任務的細節，那些在 GitHub。

## 流程變更

改本文或工作手冊由統籌開 PR，使用者同意後合併；不占任務名額。
