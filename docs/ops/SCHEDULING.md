<!-- owns: 排程、日誌與 run 記錄、重跑與回補、排程限制 -->
# 排程

每日排程由排程器定時執行一條命令：`python -m worker.cli job daily` 與 `python -m worker.cli job news`（news 之後接著 `worker.cli news-llm`）（[ROADMAP V1-G1](../ROADMAP.md#v1-範圍基線2026-10-17-核定)）。job（[`backend/worker/job.py`](../../backend/worker/job.py)）自己負責單一執行個體（檔案鎖）、起跑前檢查、單次上限、日誌與保留，不依賴排程器的設定，換排程器只要定時執行同一條命令。job 只在 Linux（[後端 image](SETUP.md#工作目錄環境與啟停)）執行（#333），所以這份程式的排程器是 scheduler 容器的 `worker.cli serve`（[scheduler 容器的排程（serve）](#scheduler-容器的排程serve)）。自動下單不在第一版範圍。

| 排程器 | 跑的程式 | 資料與 job 日誌 | 本節的操作 |
| --- | --- | --- | --- |
| scheduler 容器（`serve`，#336） | 正式 compose project 的 image，由 [`deploy.sh`](../RELEASE.md#部署) 部署（#340） | volume `stock-data` 的 `/data`（`stock.db`、`raw/`、`logs/`、`locks/`） | [scheduler 容器的排程（serve）](#scheduler-容器的排程serve)；daily、news 與看門狗的判定、日誌與 run 記錄同[排程看門狗](WATCHDOG.md)、[daily／news 工作的註冊與管理](platform/windows.md#dailynews-工作的註冊與管理)與本文[日誌與 run 記錄](#日誌與-run-記錄)～[限制](#限制) |
| Windows 工作排程器（Docker 切換後停用、只供回退） | 見 [Windows 工作排程器](platform/windows.md) | 見 [Windows 工作排程器](platform/windows.md) | [Windows 工作排程器](platform/windows.md)（daily／news、看門狗與 monitor 的工作，切換與回退） |

位置（使用者 2026-10-17 決定）：正式資料目錄（[LOCAL](LOCAL.md#正式位置使用者決定)；`stock.db`、`raw/`、`logs/`），以 `STOCK_DATA_DIR` 指向；切換（#342）時 `stock.db`、`raw/` 與 `logs/` 複製進 volume `stock-data`（`raw_payloads.payload_path` 不改寫，見 [Docker 切換與回退（cutover.sh）](platform/windows.md#docker-切換與回退cutoversh)），之後主機的這個目錄只剩統籌的檔案；回退用的原檔 `stock.db` 與 `raw/` 已於 2026-11-05 刪除（使用者決定，[LOCAL](LOCAL.md#正式位置使用者決定)），正式資料現在只在 volume 裡。排程只從發佈 checkout（[LOCAL](LOCAL.md#正式位置使用者決定)；repo 的獨立 clone）執行：它是正式 compose project 的目錄，停在 `tools/ops/deploy.sh` 部署的 tag，排程起跑不 `git pull`（升版見 [RELEASE](../RELEASE.md)）；不從 `master` 管理 checkout。統籌心跳檔、換手標記與壓縮計數檔都在主機資料目錄的 `logs/` 下（[統籌手冊](../COORDINATOR.md#統籌-session)），事件 monitor 的事件佇列與它自己的心跳、日誌也是：scheduler 容器以 `STOCK_COORDINATION_DIR` 把這個目錄 bind mount 到 `/coordination`（[統籌事件 monitor](MONITOR.md)）。

新聞任務與 `daily` 分開排程，不掛在 `daily` 之後：

- **頻率**：每 2 小時執行一次 `python -m worker.cli news`，環境變數（`STOCK_*`、`PYTHONPATH`）與 `daily` 相同。feed 只保留最近 10～65 則，間隔拉長會漏稿（見[新聞來源限制](../DATA_SOURCES.md#新聞來源)）。
- **rate limit**：每次 9 個請求、間隔 2 秒，一天約 108 個請求；不重試，限流或失敗的 feed 等下一輪。
- **冪等**：重跑或兩輪重疊抓到同一則時，不新增列、不改寫既有列。
- **錯誤**：每個來源的結果寫入 `run_type=news` 的 ingestion run，可用 `/api/ingestion-runs?q=news` 查（失敗 feed 的明細在 metadata，要加 `include_metadata=true`，[CLI](CLI.md#資料品質與研究結果)）；CLI 也把同一份結果以 JSON 印到 stdout，排程把 stdout／stderr 導到日誌檔保存（[日誌與 run 記錄](#日誌與-run-記錄)）。
- **LLM 判讀**：news job 每輪在 `worker.cli news` 結束後，於同一次執行接著跑 `python -m worker.cli news-llm`（環境變數相同、不帶 `--date`），把新收的新聞做 AI 摘要與判讀。每輪最多 100 則（4 次 `sonnet` 呼叫，25 則一批實測約 30～160 秒），前一半給最近 2 小時收錄的新聞，其餘給 3 天窗口內較舊的；同一台北日所有 run 合計最多 48 次呼叫，超過的批次等下一個台北日（#450，選取與額度見 [NEWS_SPEC §5](../NEWS_SPEC.md#5-ai-摘要與推論)、[現有 worker CLI](CLI.md#現有-worker-cli)）。
  - news 失敗時仍會跑（news-llm 只讀已入庫的新聞）；news-llm 失敗不改變 news 的結果，也不改變工作的結束碼。失敗只留在日誌的 news-llm 段落與 `run_type=news_llm` 的 ingestion run（`status=failed`、`error` 寫原因），可用 `/api/ingestion-runs?q=news_llm` 查；日誌格式見 [日誌與 run 記錄](#日誌與-run-記錄)。
  - 執行機器須已登入 Claude Code 且環境沒有 `ANTHROPIC_API_KEY`／`ANTHROPIC_AUTH_TOKEN`（有就拒絕執行）。scheduler 容器的 `claude` 在 image 的 PATH 上，compose 的 serve 命令不帶 `--claude-cli`（工作排程器的寫法見 [daily／news 工作的註冊與管理](platform/windows.md#dailynews-工作的註冊與管理)）。執行期不檢查副檔名：後端 image 的 `claude` 是 npm 套件安裝的原生檔（ELF，`@anthropic-ai/claude-code/bin/claude.exe`），不是 shim；#333 移除了 Windows 只收原生 `.exe` 的檢查。找不到 claude、未登入（含 token 過期或被撤銷，[容器內的 claude 與 gh 認證（.env）](SETUP.md#容器內的-claude-與-gh-認證env)）或額度用盡時，當輪記 `failed`（或該批 `pending`）並停止，下一輪重試。
  - 看門狗在最近 3 批判讀都是 `pending`，或最近 3 筆 news_llm run 都是 `failed`（找不到 claude、API 金鑰這類沒有批次的設定錯誤，以及被逾時終止的 run），或 news 日誌最後 3 次 `news_llm_exit` 都是 `1`／`wrapper_error` 時留言（[排程看門狗](WATCHDOG.md)）。
  - **停用／恢復**：額度吃緊時先停 news-llm，news 照常收稿。scheduler 容器：在發佈 checkout 的 env file 加 `STOCK_SKIP_NEWS_LLM=1`（`1`／`true`／`yes`／`on` 停，空值／`0`／`false`／`no`／`off` 照跑，其他值 serve 以 exit 2 拒絕啟動；[`.env.example`](../../.env.example)），再 `docker compose -p <正式 project> up -d --force-recreate scheduler` 讓 serve 重讀（它是 serve `--skip-news-llm` 的預設，[scheduler 容器的排程（serve）](#scheduler-容器的排程serve)，#342）；恢復是清空這一行再重建一次；只停 daily 與 news、看門狗與 monitor 照跑用[維護模式](#維護模式)；停整個排程是 `docker compose -p <正式 project> stop scheduler`（daily、news、看門狗與 monitor 一起停），恢復是 `start scheduler`。工作排程器的停用見 [daily／news 工作的註冊與管理](platform/windows.md#dailynews-工作的註冊與管理)。

## 日誌與 run 記錄

- **日誌**：`<data>/logs/daily-YYYYMMDD.log`、`<data>/logs/news-YYYYMMDD.log`（台北日期），排程失敗時先看這裡。每次執行追加開始列（含可用記憶體）、版本列 `--- version image=<STOCK_IMAGE_TAG> head=<STOCK_GIT_HEAD>`（沒有時 `unknown`，#340；#340 以前是 `--- checkout HEAD=<SHA> tag=<tag>`）、跳過原因（`===== skipped reason=<原因> (…)`，`already_running` 時括號內是鎖檔）、CLI 的 JSON 結果（stdout）、stderr 與結束列 `===== <時間> end exit=<code> seconds=<秒>`（[排程看門狗](WATCHDOG.md) 的看門狗以此判定 daily 是否完成）。保留 90 天（`--log-retention-days`），只清同名前綴的檔案。job 本身出錯時記 `wrapper error`，serve 的 `end` 列（`docker logs`）與工作排程器「上次執行結果」為非 0；job 被強制終止時日誌只有開始列、沒有結束列。
  - **單次上限**：daily 2.5 小時（serve 的排程觸發傳 80 分鐘，見 [daily 的 21:30 與 23:00](#scheduler-容器的排程serve)）；news 90 分鐘，news 與 news-llm 合計（`--time-limit-minutes` 可改）。到時 job 結束 worker 與它啟動的程序（程序群組），記 `--- timeout: killed at the <分> minute limit of the <job> job (exit=1)`（news 段落前加 `news ` 或 `news-llm `），該步驟的碼記 1；news 用完時間時 news-llm 不啟動，記 `--- news-llm timeout: not started …`。job 被強制終止時 worker 也一起結束（以 PR_SET_PDEATHSIG，只保證 worker 本身），所以 run 列的 PID 已不存在，下一次執行立即把它記 abandoned（見下表 `failed`）。
  - **news 日誌的分段**：`--- news stdout`／`--- news stderr`／`--- news end exit=<碼> seconds=<秒>`，接著 `--- news-llm start claude_cli=<路徑>`、`--- news-llm stdout`／`stderr`、`--- news-llm end exit=<碼> seconds=<秒>`；結束列為 `===== <時間> end exit=<news 的碼> seconds=<秒> news_llm_exit=<碼>`，`news_llm_exit` 另有 `disabled`（`--skip-news-llm`）、`not_run`（起跑前檢查未通過或另一個 news job 持有鎖）、`timeout`（news 用完單次上限，news-llm 未啟動）、`wrapper_error`（job 啟動 news-llm 失敗）。daily 日誌格式與 #313 前的包裝腳本相同，只多了版本列。
- **exit code**：daily 0＝`success`／`skipped`／`non_trading_day`／`non_trading_unconfirmed`，2＝`partial`，1＝`failed`；serve 的 `end exit=<碼>` 列與工作排程器的「上次執行結果」即此值。news 工作的碼是 `worker.cli news` 的碼；`worker.cli news-llm` 的碼（0＝`success`／`skipped`，2＝`partial`，1＝`failed`）只記在日誌的 `news-llm end` 與 `news_llm_exit`，不影響工作的碼。
- **run 記錄**：`schedule_runs` 每次 daily 執行一列（目標日、觸發來源、開始／結束、狀態、錯誤、collect 筆數、摘要），摘要 `summary_json` 每列都有 `runtime`：跑的 image 與 commit（`image`、`head`，見 [daily／news 工作的註冊與管理](platform/windows.md#dailynews-工作的註冊與管理) 執行的版本與 [scheduler 容器的排程（serve）](#scheduler-容器的排程serve)），這是一列唯一的版本欄位（#340 拿掉 #314 的 `git_tag`／`HEAD`）；`schedule_run_steps` 每步一列（catchup／collect／trading_calendar／analyze／evaluate／candidates／indicators／plan_tracking／strategy_levels／action_tiers／candidate_notes／period_backfill 的開始／結束、狀態、錯誤、處理筆數，collect 另連 `ingestion_runs.id`；`already_complete` 的列若重抓了三大法人檔，只有一列 institutional_refetch 步驟，連到 `run_type=institutional_refetch` 的 ingestion run；catchup 的 `details_json` 列出檢查與補抓的日期及各日結果）。查詢：`python -m worker.cli schedule-runs --date YYYY-MM-DD`。news 的結果在 `run_type=news` 的 ingestion run，news-llm 的在 `run_type=news_llm`（`metadata_json` 記每批則數、耗時、模型與 token 用量，API 查詢要加 `include_metadata=true`）。

| run 狀態 | 意義 |
| --- | --- |
| `success` | collect、analyze、evaluate、candidates、indicators、plan_tracking 都成功（或該步驟回 `no_data`；沒有任何追蹤計畫時 plan_tracking 是 `success`、0 筆）；trading_calendar、strategy_levels、action_tiers、candidate_notes 與 period_backfill 的狀態不列入，`success` 的定義不因新增這些步驟而改變（G7 起的判定照舊）。catchup 沒補齊不改變 run 狀態，記在該步驟與 `summary_json.steps.catchup`，由看門狗留言。 |
| `partial` | collect 有缺（例如籌碼尚未公布）；後續步驟記 `skipped`，錯誤欄列 collect 警告。 |
| `non_trading_day` | 官方來源明確回報該週間日無交易，且已確認（當日目標要兩次觸發都回 no-data）。 |
| `non_trading_unconfirmed` | 當日目標第一次回 no-data，等下一次觸發確認；不算完成，exit code 0。 |
| `failed` | 某步驟失敗或拋例外；錯誤欄記步驟與訊息，依賴它的步驟記 `skipped`（evaluate 與 candidates 依賴 analyze；trading_calendar、indicators 與 plan_tracking 只依賴 collect；strategy_levels 與 action_tiers 依賴 analyze；candidate_notes 依賴 candidates）。run 列記錄執行的主機與 PID；由 job 持鎖啟動的 run 列另記鎖的路徑（`summary_json.runtime.job_lock`），下一次拿到同一把鎖的 daily 不看主機與 PID，立即把它記 `failed`（`abandoned: process <PID> on <主機> no longer holds <鎖>`）：重建的容器 hostname 不同，PID 也可能被新程序重用（#336）。其餘的列：同主機的新執行發現該 PID 已不存在（例如被系統終止）時，立即把舊列改記 `failed`（abandoned）並照常執行；其他情況要超過 2.5 小時（與 job 預設的單次上限相同）仍為 `running` 才記 abandoned，在那之前同日的新執行記 `skipped`（`already_running`）。 |
| `skipped` | 同目標日已有 `success`／`non_trading_day`（`already_complete`）、另一次執行仍在進行（`already_running`：run 列仍在 running，或 job 拿不到鎖，後者 `related_run_id` 指向當時 running 的列、沒有則為空；DB 不在 head 時不寫列，見 [daily／news 工作的註冊與管理](platform/windows.md#dailynews-工作的註冊與管理)），或起跑前檢查未通過（`low_memory`／`git_busy`；#314 前的列另有 `git_pull_failed`）；不碰資料，唯一的例外是 `already_complete` 時重抓三大法人檔：結果記在 `summary_json.institutional_refetch`（`status`、`run_id`、`idempotent_reuse`、`requests`、`revised_rows`、`unchanged_rows`、`value_fills`，失敗時有 `error`），run 的 `records` 是更正的列數。重抓失敗也維持 `skipped`、exit code 0，當日是否完成仍看先前那列 `success`。 |

trading_calendar 步驟呼叫 `worker.trading_calendar.run_trading_calendar(目標日)`，在 collect 成功後、analyze 之前執行，抓目標日的年度與下一年度的[官方休市表](../DATA_SOURCES.md#交易日曆)（2 個請求），供 analyze 推算訊號的[規則最早執行日](../spec/README.md#價位etf-與生命週期)。寫入列數記在步驟列的 `records`，`details_json.years` 記各年度結果。它的任何狀態（`failed`、`partial`、例外）都只記在該步驟列（原因寫在 `error`，例如 `holiday schedule 2027 unavailable: …`）與 `summary_json.steps`，**不改變 run 狀態與 exit code**；analyze 照跑並使用表內已有的日曆，日曆答不出來時訊號的日期留空，analyze 步驟的 `details_json.execution_calendar` 記 `status`（`available`／`unavailable`）、`reason`、`missing_year`、`next_session` 與 `signals_without_date`，看門狗以 `invariant_execution_calendar` 留言（[排程看門狗](WATCHDOG.md)）。休市日 collect 為 skipped 時它也記 `skipped`。手動更新：`python -m worker.cli trading-calendar`（[現有 worker CLI](CLI.md#現有-worker-cli)）。

indicators 步驟呼叫 `worker.indicator_batch.run_indicator_batch(目標日)`；只要 collect 成功就執行（analyze 失敗也跑），失敗時 run 記 `failed`、錯誤欄記 indicators 訊息。

candidates 步驟呼叫 `worker.candidates.run_candidates(目標日)`，只讀當日訊號、籌碼、族群榜與新聞，不改行情、訊號與追蹤；失敗時 run 記 `failed`（exit code 1，看門狗與排程異常處理照 `failed` 處置）、錯誤欄記 candidates 訊息，indicators 照跑。行情與訊號已寫入，只需重跑候選：`python -m worker.cli candidates --date YYYY-MM-DD`（不需 `daily --force`；接著會補該日的 AI 說明，`--skip-notes` 跳過，[CLI](CLI.md)）。

plan_tracking 步驟呼叫 `worker.plan_tracking.run_plan_tracking(目標日)`，在 indicators 之後、candidate_notes 之前執行（candidate_notes 可能跑很久），只讀日線、公司行動、停牌事件與計畫自己的價位快照，更新[使用者追蹤計畫](../spec/tracking.md#使用者追蹤計畫)；collect 成功就執行（analyze 失敗也跑），失敗時 run 記 `failed`、錯誤欄記 plan_tracking 訊息，其他步驟的結果不變。只需重算計畫：`python -m worker.cli track-plans --date YYYY-MM-DD`。`schedule_run_steps` 以 run 與步驟名稱找列，`sequence` 只用來排序（trading_calendar 為 2、analyze 為 3，plan_tracking 為 8、strategy_levels 為 9、action_tiers 為 10、candidate_notes 為 11（#476 以前 candidate_notes 為 10）、period_backfill 為 12；之前的 run 維持寫入當時的號碼）。

strategy_levels 步驟呼叫 `worker.strategy_levels.run_strategy_levels(目標日)`，在 plan_tracking 之後、candidate_notes 之前執行，analyze 成功（含 `no_data`）才跑，否則記 `skipped`（`analyze_not_successful`）；為當日 analysis 訊號寫[條件價位](../spec/strategy_levels.md)，只讀已存資料、不改訊號、候選與追蹤，處理的訊號數記在步驟列的 `records`，`details_json` 有寫入列數與 `availability` 分佈。它的任何狀態（`failed`、`partial`、例外）都只記在該步驟列與 `summary_json.steps`，**不改變 run 狀態與 exit code**，不觸發 daily 失敗的看門狗；失敗由看門狗的資料不變量 `invariant_strategy_levels`（[排程](#)）回報，個股頁策略總表對沒有條件價位列的觀察訊號顯示「觀察價位未產生」（#274）。daily 已 success 後不會重跑，補算或重算以 `python -m worker.cli strategy-levels --date YYYY-MM-DD`（[現有 worker CLI](CLI.md#現有-worker-cli)）。

action_tiers 步驟呼叫 `worker.action_tiers.run_action_tiers(目標日)`，在 strategy_levels 之後、candidate_notes 之前執行，analyze 成功（含 `no_data`）才跑，否則記 `skipped`（`analyze_not_successful`）。它把首頁與行動頁 action tier 的日資料部分寫進 `action_tier_snapshots`（[action tier 預算與新聞投影](#action-tier-預算與新聞投影)），步驟列的 `records` 是寫入的標的數。任何狀態（`failed`、例外）都只記在該步驟列與 `summary_json.steps`，**不改變 run 狀態與 exit code**：頁面在沒有當日預算時改為即時計算，結果相同，只是比較慢。重算以 `python -m worker.cli action-tiers --date YYYY-MM-DD`。


candidate_notes 步驟呼叫 `worker.candidate_notes.run_candidate_notes_batch(目標日)`，在 candidates 成功（含 `no_data`）後最後執行，為當日候選寫 [AI 進出點說明](../spec/candidate_score.md#候選-ai-進出點說明)；最多 4 次 `claude -p`，各 300 秒逾時（實測一次約 7 秒）。它的任何狀態（`success`／`partial`／`failed`／`skipped`／`no_data`，含找不到 claude、未登入、額度用盡、逾時與例外）都只記在該步驟列與 `summary_json.steps`，**不改變 run 狀態與 exit code**；candidates 不成功時記 `skipped`（`candidates_not_successful`）。最新候選日的候選清單產生超過 30 分鐘仍沒有一檔完成的說明時，看門狗以 `invariant_candidate_notes` 留言（daily 或 candidate_notes run 執行中不判定，[WATCHDOG](WATCHDOG.md)；#517）。daily 已 success 後 23:00 那次不會重跑，`pending` 或未說明的候選以 `python -m worker.cli candidate-notes --date YYYY-MM-DD` 補（只送未完成者）；手動 `worker.cli candidates` 重產候選後預設接著跑這一步（[CLI](CLI.md)）；結果查 `/api/ingestion-runs?q=candidate_notes&include_metadata=true` 或步驟列。

period_backfill 步驟呼叫 [`worker.period_backfill.run_period_backfill(目標日)`](../../backend/worker/period_backfill.py)（[#536](https://github.com/YiCheng0608/stock-lab/issues/536)），在 candidate_notes 之後最後執行，collect 成功就跑（不依賴 analyze）。它在法定期限前後的窗口裡，跑 `fundamentals backfill` 與 `revenue backfill` 的同一套程式（[季度財報回補](../DATA_SOURCES.md#季度財報回補)、[月營收](../DATA_SOURCES.md#月營收)），補最近一期與前一期。日快照只有一期、換期後就不再更新，換期後才上市的新股、晚申報與更正都收不到（#536 AC-1 的量測）：

- **窗口**：以步驟執行當天的台北日期判斷，不看目標日。窗口外 `skipped`（`reason=outside_window`），不發任何請求。
  - 季報：從該季最早的申報期限前 14 天，到最晚的期限後 14 天。Q1 是 5/1～6/13，Q2 是 7/31～9/14，Q3 是 10/31～12/13，Q4（年報 3/31）是 3/17～4/14。窗口內補該季與前一季，例如 11/6 補 2026Q2、2026Q3。
  - 月營收：從次月 1 日到期限（次月 10 日）後 10 天，即次月 1～20 日。窗口內補上個月與上上個月，例如 11/6 補 9 月、10 月。
- **上限**：每次最多 12 頁，季報 2 季 × 2 市場，月營收 2 個月 × 2 市場 × 2 頁；重試算在內最多 44 次 HTTP（季報每頁 3 次、月營收每頁 4 次）。同 host 間隔 3 秒。時間是硬上限（[#539](https://github.com/YiCheng0608/stock-lab/issues/539)，[`worker.bounded_http`](../../backend/worker/bounded_http.py)）：
  - 每次 HTTP 從連線到讀完整個回應合計最多 30 秒（`ATTEMPT_SECONDS`），超過就當傳輸錯誤重試。httpx 的 `timeout` 是每次連線、每次讀取各自計時，來源一點一點吐資料時一次請求可以拖很久（2026-11-06 實測一頁 `t21sc03` 超過 5 分鐘沒有回完），所以不能只靠它。手動 CLI 不受這條限制，照舊每次讀取 60 秒。
  - 逾時的那次 HTTP 先關掉才重試（PR #541 review）：連上時記下它的 TCP socket，逾時就 shutdown，再最多等 1 秒（`CLOSE_SECONDS`）讓它結束。否則重試會在舊連線還在讀時，對同一個 host 再開一條，而同 host 間隔只看請求開始的時間、擋不到，MOPS 對太頻繁的查詢會回阻擋頁。1 秒內沒結束（卡在 DNS 或 TCP 連線、還沒有 socket 可關）時記失敗、不重試（`AttemptStuck`）。
  - 步驟開始 300 秒（`TIME_BUDGET_SECONDS`）就停：之後不再發請求（間隔的 3 秒也算在內），進行中的那次 HTTP 只等到第 299 秒（留 1 秒關連線），重試的等待會超過第 300 秒就不等、直接記失敗。該部分記 `aborted`（`time budget <剩餘秒數> s used up before <鍵>`），狀態 `partial`。
  - 所以這一步的 HTTP 在開始後 300 秒內結束。整步最多是 300 秒，加上寫入最後一頁與收尾的 DB 寫入（月營收部分建 run、載 instruments、commit；幾秒），以及第 300 秒前開始的一次同 host 間隔（最多 3 秒）。測試以本機每 0.05 秒吐 1 byte 的假來源核對（`test_period_backfill_time_limit.py`）。
- **月初**：月營收窗口從次月 1 日開始，那時還沒有公司申報最新月份。MOPS 對沒有資料的月份回 200 加「查無資料」，不是 404（2026-11-06 實測尚未結束的 115/11：`https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_115_11_0.html`，200，918 bytes）。這一頁在該月期限（遇休市順延）以前記 `empty`（`no_data: true`），不算失敗；過了期限仍是「查無資料」才算失敗。手動 CLI 也一樣。
- **實測**（2026-11-06，正式 DB 副本，alembic `0028_monthly_revenues`）：窗口內 12 頁，68.1 秒與 75.7 秒；第二次 `records 0`。daily 21:30 起跑，10-19～11-05 的 success run 耗時 5.1～23.1 分鐘，加上這一步最多的 5 分鐘多仍早於 serve 的 80 分鐘上限（22:50）與 23:00 那一輪。
- **記錄**：季報與月營收各寫一筆 `run_type=fundamental_backfill`／`revenue_backfill` 的 ingestion run，`metadata_json.trigger` 是 `daily`（手動 CLI 是 `manual`）。步驟列的 `records` 是兩者 `changed` 的和，`details_json` 有兩者的完整結果。run 的 `summary_json.period_backfill` 記 `status`、`reason`、`today`、`quarters`、`months`、`requests`、`records`、`seconds`、`error`，以及 `fundamentals`／`revenue` 各自的 `status`、`run_id`、`requests`、`changed`、`aborted`。
- **失敗**：任何狀態（`partial`、`failed`、例外）都只記在步驟列、`summary_json.steps`、`summary_json.period_backfill`，**不改變 run 狀態與 exit code**。不是 `success`／`skipped` 時，`summary_json.noncore_warnings` 加一則 `MOPS period backfill <狀態>: <原因>`。季報與月營收分開跑：一邊例外，另一邊照跑。連續 3 次 daily run 都不是 `success`／`skipped` 時（數的是 run 不是交易日：21:30 的 run 失敗、23:00 重跑時兩次都會跑這一步，同一天算 2 次，所以 3 次可能只跨 2 個交易日），看門狗在 #1 留言，同一窗口一則（[`invariant_period_backfill`](WATCHDOG.md)）。窗口每天都會再跑一次，所以失敗的那天隔天就補；要立即補，對該期手動跑 `fundamentals backfill --quarters 2`／`revenue backfill --months 2`（[CLI](CLI.md#現有-worker-cli)）。
- **只在 daily 跑**：23:00 那一輪在 21:30 已 `success` 時只重抓法人檔，不再跑這一步；collect 不是 `success`（`partial`、休市）時，這一步記 `skipped`，等下一次 daily。

## action tier 預算與新聞投影

首頁（`/api/dashboard`）、行動頁（`/api/actions`）與新聞（`/api/news`、`/api/news/{id}`）不在 GET 時重算整批的日資料（[#476](https://github.com/YiCheng0608/stock-lab/issues/476)）。

**action tier**（`app.action_tier_store`，表 `action_tier_snapshots`，每個交易日、每個存放版本一列）：

- **存什麼**：只存日資料的部分，也就是每檔標的在套用持股之前的級別，以及候選名次、族群名次、接近度。持股（第 0 級）、自選與名稱在每次請求時即時讀取，所以改持股或自選不必重算。
- **誰寫**：daily 的 action_tiers 步驟，或 `worker.cli action-tiers --date`。
- **依據指紋**：寫入時一併存下，讀取時重算一次（副本上約 70 ms），內容是：
  - 版本常數：`ACTION_TIER_STORE_VERSION`、`action_tier_v1`、`strategy_levels_v1`、candidate score 版本、registry 與分級門檻。
  - 當日訊號：筆數、最大 id，以及各狀態的 id 總和。
  - 當日 strategy_levels：筆數、最大 id、最大 `computed_at`。
  - 當日 candidate run 與它的候選列。
  - 族群分數：筆數、最大 id、rank 總和，以及近 14 天的 `details_json` 長度。
  - 近 7 天事件：筆數與最大 id。
  - bars 的最大 id。
  - `group_memberships`、`theme_groups`、`instruments`（投影讀的欄位）的 hash。
- **何時回退即時計算**：沒有當日的列（`missing`），或指紋不同（`stale`）。指紋不同的例子：daily 重跑、手動 analyze、candidates、strategy-levels、族群或成員變動、版本升級。回應以 `action_tier_source`（dashboard）、`summary.tier_source`（actions）標示 `source`（`precomputed`／`live`）、`reason` 與 `computed_at`。
- **重算**：手動重跑上述步驟之後，跑 `action-tiers --date <該日>` 補回預算；不跑也不會錯，只是頁面在下一次 daily 之前都走即時計算。
- **指紋看不到的變動**：bar 被刪除、TAIEX 的 raw provenance 被原地改寫。目前的程式沒有刪 bar 的路徑。以後若新增，或真的遇到這兩種情況，跑一次 `action-tiers`。
- **規則變更**：改了 `daily_action_tiers` 讀的內容、而指紋不會跟著變時（例如新增一個輸入表），要升 `ACTION_TIER_STORE_VERSION`。

**新聞投影**（`app.news`，表 `news_projection_state`）：

- **worker 寫入後投影**：凡是寫 Event 或族群成員的路徑，都在 commit 前呼叫 `project_news`（完整投影並記下指紋）：
  - collect：當日快照與歷史 batch，含 catchup、回補、MOPS 日期清單的 gap 日。
  - `events backfill`：每個日期 commit 前投影該日的事件，結束時做一次完整投影。回補期間每 commit 一個日期，之後的第一個新聞或首頁 GET 會對不上指紋，完整投影一次（約 3 秒）並寫下新指紋，再之後的 GET 就不投影；改版前是每次 GET 都投影。
  - `themes`。
  - `industry repair --apply`、`instruments repair --apply`（狀態同步會結束族群成員的期間）。
- **GET 只做檢查**：三支 GET 重算指紋（副本上約 60 ms）並和上次存下的比對，不同時才完整投影並寫入，否則什麼都不寫。DB 裡沒有任何官方事件、也沒有已投影的新聞時也不寫。指紋包含：
  - `NEWS_PROJECTION_VERSION`。
  - Event：筆數、最大 id、最大 `collected_at` 與 `updated_at`，以及標題、內容、details、來源、endpoint、raw id、標的、日期、類型的總和。
  - 已投影 NewsItem 的筆數與最大 id。
  - 上述三表的 hash。
- **`events.updated_at`**：ORM 每次寫入有變動的 Event 時更新（`onupdate`）。Core、`bulk_*` 或原生 SQL 改 Event 時不會自動更新，那種寫法要自己設這個欄位；內容總和是第二道防線。目前寫 Event 的只有 `pipeline._upsert_event`，走 ORM。
- **規則變更**：改了投影規則，讓同一筆 Event 投影出不同結果時，要升 `NEWS_PROJECTION_VERSION`。部署後跑一次 `python -m worker.cli news-project`，讓第一個開頁的人不必等投影（[RELEASE](../RELEASE.md#含-migration-的版本)）。

## 重跑與回補

- **手動重跑**：見 [daily／news 工作的註冊與管理](platform/windows.md#dailynews-工作的註冊與管理)「不經排程執行一次」，或直接 `python -m worker.cli daily --date YYYY-MM-DD`。已完成的日期加 `-Force`／`--force` 才會再跑各步驟。
- **漏日補抓**：每次 daily 在 collect 目標日前跑 catchup：從目標日前一天往回取最近 5 個不是確定休市的週間日（確定休市＝該日的 daily run 記過 `non_trading_day`，或 collect 的 no-data 是在該台北日結束後才取得；只有當天一次 no-data、23:00 沒再確認的 `non_trading_unconfirmed` 日仍列入補抓，避免誤報的休市永遠補不回），最多回看 15 個週間日（「確定休市」與回補目標同一條規則，見[回補目標與確定休市日](../DATA_SOURCES.md#回補目標與確定休市日)）；其中沒有 collect success（含 TAIEX）的日期，由舊到新以回補的單日路徑（`pipeline.collect(日期, adapter=OfficialMarketDataAdapter(snapshot_feeds=False))`，只抓日期範圍的官方資料，不抓當日快照）補抓；歷史路徑不查 MOPS 快照，只查該日的 MOPS 日期清單（[重大訊息日期查詢](../DATA_SOURCES.md#重大訊息日期查詢)）；清單核實了該日就以它為覆蓋，否則重抓已有 snapshot collect 的日期時沿用該 request 已存的 `event_coverage` 與 `mops_events`／`mops_fundamentals` 資料品質列，不退成歷史預設。補過的日期之後不再抓；補抓失敗的日期下一次 daily 再試，超出 5 個交易日窗口就不再自動補，看門狗會在失敗當晚留言，改用下面的手動回補。catchup 只補 collect，不補跑過去日期的 analyze／evaluate／candidates；指標由當日 indicators 步驟依[指標規則](CLI.md#現有-worker-cli)處理，補到的日線影響最後一列以外時跑 `indicators --rebuild`。
- **主檔外的行情列**：官方行情表裡的普通股代號（4 位數、非 0 或 91 開頭）與 ETF 代號（`00` 開頭、4～6 碼，最後可帶一個大寫字母；#393），即使不在當天的官方清單，也照樣寫入 DB 中同交易所、同代號的既有標的（例如已下市或已轉市的舊標的）。DB 沒有該標的時不建立，記一列 `data_quality`（`entity_type=unmatched_bar`，`entity_key=交易所:代號`，`as_of_date` 為 collect 目標日，checks 列交易日、來源與 raw id）與 run metadata 的 `unmatched_bars`，並加一則 notice；collect 狀態不變。這類代號的歷史可用 `instruments repair --include-delisted` 補回（[現有 worker CLI](CLI.md#現有-worker-cli)）。
- **標的晚建立時補寫日線**（#388）：新上市股票的清單常比首日行情晚一天，首日先被記成 `unmatched_bar`。之後每次 collect 在寫完當日行情與狀態同步後，檢查還沒補完的 `unmatched_bar` 列；代號已有標的時，依該列記的 raw id（新的先）讀已存的行情 raw，核對 SHA-256 並以 collect 相同的解析寫入該日日線。值、來源、資料日期與 `raw_payload_id` 都取自那份 raw，不重新抓取；已存的日線不改。該列 checks 加 `backfill`（寫入的日期與 raw id、已有日線的日期、讀不到的日期與原因），全部日期都有日線時狀態改為 `complete`；raw 找不到、內容與 SHA-256 不符、解析出錯時不補值，狀態維持 `missing`（部分補到為 `partial`）、`missing_fields` 為 `raw_payload`，下次 collect 再試；這類列每次 collect 都會重讀它記的 raw。代號仍沒有標的的列不動。補寫過日線的日期（含先前已補完、狀態 `complete` 的列）沒有籌碼列時，同一次也從當日已存的官方法人與融資 raw（TWSE T86、MI_MARGN；TPEx 三大法人、融資餘額）補該標的的籌碼列（#415）。每份 capture 核對 SHA-256 與回報日期後以 collect 相同的解析讀取；每組由當日最新一份「有個股列或讀不出來」的 capture 決定（#387 以較晚的為準），沒有個股列的（如 18:30 還沒公布的 MI_MARGN）與回報日期不是當日的跳過。決定的那份有該代號就取它的值，沒有就是該組沒有這檔；那份讀不出來（檔案不在、與 SHA-256 不符、解析出錯），或該組沒有一份有個股列的 capture 時，該組無法判定，舊的 capture 不拿來替代。兩組都判定了才寫：有值的組寫入，法人與融資各自記 source、raw、資料日與收集時間（#395）；兩組都沒有這檔就不寫。已存的籌碼列不改。結果記在該列 `backfill.chips`（`written` 附兩組 raw id、`no_row`、`existing`），記過的日期之後不再讀 raw；有一組無法判定時整個日期不寫也不記，回傳列在 `chips_pending`（附該組與讀不出來的 raw id、原因），下次再試。回傳另有 `chips_written`、`chips_checked`。run metadata 與回傳記 `unmatched_backfill`（`status` 為 `success` 或 `failed`），有補寫時加一則 notice。補寫本身出錯時只撤回補寫的寫入：collect 狀態與當日行情不受影響，`unmatched_backfill` 記 `failed` 與錯誤並加一則 notice，列維持未補。補寫日期之後的技術指標由 daily 的 indicators 步驟重寫：該標的最後一列的 `bar_count` 變了，整檔重算。不跑 daily 時用 `instruments backfill-unmatched --apply` 再跑 `indicators`（[現有 worker CLI](CLI.md#現有-worker-cli)）。
- **冪等**：collect 對同一 request 已有 `success` 時直接重用、不發請求。重新擷取時：
  - **日線與融資**：既有列只補空欄，不覆寫已存的非空值，不一致的值保留原值，件數記在該 collect run metadata 的 `value_conflicts`、前 50 筆在 `value_conflict_samples`。只補空欄時該列的 `raw_payload_id`、source、data_as_of、collected_at 不變（仍指向原值的 capture），補了哪些欄位與新 capture 的 raw id 記在 `value_fill_groups`（依表、交易所、日期、欄位、raw id 分組列代號，同一 request 的多次執行累加）。
  - **籌碼列的兩組來源**（[#395](https://github.com/YiCheng0608/stock-lab/issues/395)）：法人與融資各自記來源、raw、資料日與收集時間（[DATA_SOURCES 籌碼來源](../DATA_SOURCES.md#籌碼來源)），上一條的「該列 provenance」對籌碼列是指那一組的。列還沒有某一組時（例如 #466 以前 18:30 的 collect 只有法人檔，21:30 才有融資），那一組改指向帶來它的 capture，不算補空欄，不記 `value_fill_groups`；那一組已有來源時補其中的空欄才算補空欄，`value_fill_groups` 記的是那一組 capture 的 raw id（融資記融資檔，不是法人檔）。
  - **三大法人**（籌碼列的 `foreign_buy`、`trust_buy`、`dealer_buy`）：交易所 18:30 公布後會更正，例如 2313 在 2026-10-19 的投信 18:30 是 −162,968 股、21:30 更正為 1,133,032 股（[#387](https://github.com/YiCheng0608/stock-lab/issues/387)）。新 capture 與既存列同一交易日、同一份官方法人檔（上市 T86、上櫃 `insti/dailyTrade` 或當日 OpenAPI `tpex_3insti_daily_trading`，即兩者的法人組來源相同），且擷取時間（`raw_payloads.collected_at`）嚴格晚於該列法人組目前指向的 capture 時，不同的值改成新值，該列的法人組改指向新 capture，融資組不變；值相同時不改列。舊值記在 collect run metadata 的 `value_revision_rows`：每列一筆，含交易所、代號、交易日、各欄舊值與新值、舊與新的 raw id；同一 request 的多次執行累加、不截斷。本次執行更正的列數在 `value_revisions`。擷取時間相同或較早的 capture 照日線與融資的規則處理，例如重跑舊日期時讀到較早的 capture、或 capture 順序顛倒。法人組沒有 raw 指向時，以它的收集時間當擷取時間。
  - **23:00 重抓三大法人檔**（[#396](https://github.com/YiCheng0608/stock-lab/issues/396)）：目標日已有 daily `success` 時，下一次 daily（排程是 23:00，#466 以前是 21:30）不重跑 collect，只呼叫 `worker.institutional_refetch.refetch_institutional(目標日)`：上市 T86、上櫃 `insti/dailyTrade` 各請求一次（daily 每個交易日多 2 個請求），raw 存在 `run_type=institutional_refetch`、`request_key=institutional_refetch:<日期>` 的 ingestion run 下，再以上一點的規則套用到既有的籌碼列（不新增列，融資欄與融資組來源不動）。run 的 `records` 與 metadata 的 `revised_rows` 是更正的列數，`unchanged_rows` 是值相同未改的列數，`value_revision_rows` 列每列舊值與新值，`exchanges` 記各交易所的結果與 raw id。兩份都成功是 `success`，同一日期之後的 daily 直接重用、不再請求；一份失敗是 `partial`、兩份失敗是 `failed`，成功的那份照樣寫入，下一次 daily 兩份都再抓一次。重抓的 capture 之後也會被 `chips revise` 依擷取時間重放。只更正籌碼列，不重算當日的訊號、族群與候選，下一個交易日的 daily 讀到更正後的值。
  - **force**：`collect(force=True)` 覆寫所有欄位（含較早的 capture），覆寫時指向新 capture；籌碼列只移動值有改變的那一組。
  - **#387 以前的初值**：以 [`chips revise`](CLI.md#現有-worker-cli) 依已存的 raw 套用三大法人規則更正。
  - **0021 以前的籌碼列**：以 [`chips provenance`](CLI.md#現有-worker-cli) 依已存的 raw 與 `value_fill_groups` 補寫兩組來源。
- **回補**：`python -m worker.cli backfill --start-date <起> --end-date <迄> --scope market`。中斷後以相同起訖重跑即從各段 manifest 續做；輸出列出每段 run id、`partial_dates`／`failed_dates`（缺日，不補值）與 `skipped_non_trading_dates`（官方無交易）。每段的 `target_met` 看「已驗證交易日 ≥ `min(65, 平日數 − 確定休市日)`」（[回補目標與確定休市日](../DATA_SOURCES.md#回補目標與確定休市日)）；規則改版前寫下的 run，以相同起訖重跑一次就會更新：已完成與已確認休市的日期都會重用、不發請求（#479）。回補或更正舊日線後跑 `python -m worker.cli indicators --rebuild` 重算指標。
- **限流**：`fetch_json` 對同一官方主機保持最小間隔（`www.twse.com.tw` 2.5 秒，其餘官方主機 1 秒），另有 429／5xx／暫時性 307 的有界重試。
- **不要並行回補**：回補與 daily 都長時間寫 DB，analyze 也依 collect run 決定分析日；回補、回測期間停用 daily：scheduler 容器不必停：`backfill`、`backtest` 起跑時自己開[維護模式](#維護模式)（daily 與 news 不跑，看門狗與 monitor 照常），結束時自己關，作業死掉由 serve 在心跳逾時後解除（工作排程器的做法見 [daily／news 工作的註冊與管理](platform/windows.md#dailynews-工作的註冊與管理)）。

### 技術回測

`python -m worker.cli backtest --start-date <起> --end-date <迄>` 在正式環境的跑法：`docker compose -p <P> exec scheduler python -m worker.cli backtest …`，起跑時自己持有[維護模式](#維護模式)，不必停 scheduler。

- **記憶體**：每個交易日與每 2,000 個訊號的追蹤批次各 commit 一次（[Tracking 口徑](../spec/tracking.md#tracking-與-technical-backtest-口徑)第 3 點，#484），所以記憶體不隨區間成長。
  - **峰值**：在 2g 的 scheduler 容器、2026-11-04 正式 DB 副本上量 cgroup anon 峰值：
    - 1 個月 235 MB。
    - 3 個月 244 MB（281,674 個訊號）。
    - 12 個月 290 MB（241 個交易日、1,092,604 個訊號，[#484 AC-3](https://github.com/YiCheng0608/stock-lab/issues/484#issuecomment-6666172768)）。290 MB 是換交易日時的短暫尖峰，平常在 145～190 MB。
  - **WAL**：最大約 60 MB。
  - **#484 以前**：整段是一個 transaction，追蹤時一次載入全部回測訊號（約 14 KB／訊號）。1 個月就到 2,002 MB；3 個月在載入時 OOM；12 個月的 run 2286 也被 OOM 結束。
- **耗時**：
  - **固定成本**：`init_db` 約 2～4 分鐘（2.99 GB 的 DB），features 約 1.5 分鐘。
  - **重播**：每個交易日約 55～60 秒，隨交易日數線性成長。
    - **族群分數**：約 17 秒（#509 實測 17.0～17.3 秒）。#509 以前約 60 秒。
    - **訊號**：約 36～43 秒。
  - **追蹤**：1 個月約 30 秒，3 個月約 2 分鐘，12 個月約 9 分鐘。
  - **合計（推算）**：1 個月約 25 分鐘，3 個月約 1 小時 5 分，12 個月約 4 小時。這些是以族群分數 17 秒推算的，沒有實測。
  - **#509 以前的實測**：1 個月 40 分鐘，3 個月 1 小時 55 分，12 個月 6 小時 59 分。12 個月那次後段和主機上其他負載重疊，每日一度慢到 150～200 秒。
- **何時跑**：預估會跨過 21:30 就改在 23:30 後起跑。原因是 21:30 的 daily 會被維護模式跳過，要等回測結束才補跑。
- **中途失敗**：OOM、`docker stop`、例外都算。已 commit 的訊號與結算會留下，run 記 `failed`；以相同起訖重跑，會覆寫成一次跑完的結果（前提是資料沒有更正，見 [Tracking 口徑](../spec/tracking.md#tracking-與-technical-backtest-口徑)第 3 點）。
  - 行程被殺時 `finally` 不會執行，run 會停在 `running`。下一次 canonical backtest 開始時，會把它記成 `failed`（`abandoned:`），並列在輸出的 `abandoned_runs`。daily 開工時（任何步驟之前）也會收：在維護標記的鎖內確認沒有標記（沒有回測持有維護模式，也沒有手動維護），就把正規 `running` 回測記成 `failed`（`abandoned: … daily started with no maintenance hold …`），結果記在 daily 輸出的 `abandoned_backtests`（`checked` 附 `runs`、有標記時 `skipped`、出錯時 `failed`，出錯不讓 daily 失敗，下一次 daily 再試）；研究 run（`:research:`）任何情況都不收（[#581](https://github.com/YiCheng0608/stock-lab/issues/581)）。
- **量記憶體**：
  - 每 5 秒讀一次容器 cgroup `memory.stat` 的 `anon`，取最大值；同時記行程的 `VmRSS`。
  - `memory.peak` 與 `docker stats` 的 MEM USAGE 含 page cache，讀這份 DB 時就會頂到 2g，不能用來判斷會不會 OOM。

## 維護模式

回補、回測、`init-db` 這類長時間寫 DB 的作業期間，以維護模式取代停 scheduler（#468）：daily 與 news 不執行，看門狗與[事件 monitor](MONITOR.md) 照常跑，統籌照樣收得到 Issue／PR 留言與 CI 的事件。#468 以前停 scheduler 會連 monitor 一起停：2026-11-04 技術回測前停了 scheduler，回測結束就 `start` 的那一步放在統籌 session 的背景指令裡，換手時跟著消失；回測又在 04:52 被 OOM 結束，scheduler 一直停到 05:15 部署時才起來，約 7.5 小時沒有 monitor、看門狗與 news（[#468 決定](https://github.com/YiCheng0608/stock-lab/issues/468#issuecomment-6646001167)）。所以恢復不靠任何 session：作業自己開關，作業死掉由 serve 解除。

- **作業自己持有**：`backfill`、`backtest`、`events backfill`、`fundamentals backfill`、`revenue backfill`、`instruments repair --apply` 起跑時自己開維護模式，正常結束、例外或 SIGTERM（`docker stop`）都在 `finally` 關掉（[`MaintenanceHold`](../../backend/worker/job.py)）。直接照平常跑，不必先停 scheduler，例如 `docker compose -p <P> exec scheduler python -m worker.cli backtest --start-date … --end-date …`；`exec scheduler` 或 `compose run api` 都一樣，標記檔在同一個 volume。起跑時 stderr 會提示：**預估會跨過 21:30 時，請改在 23:30 後開始**（21:30 的 daily 會被跳過，要等解除才補跑）。
- **標記檔**：`/data/locks/maintenance`（JSON）。作業持有時記 owner（命令、容器 hostname、PID、token）、開始時間與心跳時間，作業期間每 60 秒更新心跳。取得、心跳、解除、逾時與手動 `on`／`off` 都在 `/data/locks/maintenance.lock` 的 flock 下進行：兩個作業同時起跑只有一個取得，心跳也不會讓 serve 剛解除的標記檔復活。
- **拒絕起跑**（exit 75，stderr 寫出原因）：有開啟前就在跑的 daily／news job（等它結束再跑），維護模式由另一個仍有心跳的作業持有（一次只跑一個回補或回測），或維護模式是手動開的（部署中：`deploy.sh` 會在作業還在跑時把它關掉，所以等部署完成再跑）。其餘情況自動開，不拒絕。
- **心跳逾時**：作業被 SIGKILL 或 OOM 結束時 `finally` 不會執行。serve 每分鐘檢查一次，心跳超過 10 分鐘沒更新就視為 owner 已死：刪掉標記檔、恢復 daily 與 news，在 `docker logs` 記 `serve maintenance_expired`，在 `maintenance.log` 記一筆 `expired`，看門狗據此在 #1 留言 `maintenance_expired`（[排程看門狗](WATCHDOG.md)）。作業沒有跑完，回補以相同參數重跑即從 manifest 續做。下一個回補或回測遇到心跳已停的標記檔會直接接手（記 `took_over_from`）。反過來，作業還活著卻失去維護模式時（主機睡眠或 VM 暫停後 serve 先醒、判定逾時；或心跳寫不進去），心跳執行緒會在一個週期內發現，記 `lost`，以 SIGUSR1 讓主執行緒丟出 `MaintenanceLost`，作業以 exit 70 結束，不和接著開跑的 daily 並行寫 DB。
- **daily、news 與 us**（us 是 #568）：job 取鎖後先看標記檔（[`job.py`](../../backend/worker/job.py)），有就只在日誌記 `===== skipped reason=maintenance (since=<開始時間>, reason=<原因>, marker=<標記檔>)` 與 `end exit=0`（news 的 `news_llm_exit=not_run`），不啟動 worker，所以不寫 DB：daily 其他跳過原因會寫的 `skipped` run 列（含 `already_running`）也不寫。排程觸發與手動的 `job daily|news|us` 一樣跳過；維護期間要手動跑就直接 `worker.cli daily`。標記檔讀不懂時也算開著。
- **解除後補跑**：serve 偵測到維護模式解除（作業結束、手動 off 或心跳逾時）時，是週一至週五、已過 21:30，而當日 daily 沒有完成，就立即補跑一次（與[錯過的時段](#scheduler-容器的排程serve)的啟動補跑相同）。例：21:30 在維護中被跳過、22:10 解除，就在 22:10 補跑；補跑成功後 23:00 那次只記 `already_complete`（做法人重抓），不重跑。在維護模式中啟動的 serve（例如部署換了容器）不在啟動時補跑（記 `catchup_deferred`），等解除時補。**跨午夜**：21:30 與 23:00 都在維護中、午夜後才解除時，補跑只看「今天」，前一天不會補跑；下一個交易日 daily 的 catchup 會補抓那天的 collect，但不補 analyze、candidates 等，看門狗在 00:30 後就那天留言（`daily_result_<日期>`），要那天的訊號與候選就手動跑 `python -m worker.cli daily --date <那天>`。
- **看門狗與 monitor**：照常執行。看門狗每輪記 `maintenance_on`，開超過 12 小時在 #1 留言（`maintenance_long`，每台北日一則）；只因維護模式跳過、沒有 run 列的那天 daily 不算異常。
- **手動開關**：只用在 [RELEASE 含 migration 的版本](../RELEASE.md#含-migration-的版本)的 `init-db`→`deploy.sh` 這一段，因為維護模式要從 `init-db` 前一路開到新容器起來，沒有單一作業能持有它。手動開的沒有心跳、不會逾時解除；`deploy.sh` 換完容器、核對都通過後自己關掉它，記在部署記錄的 `maintenance`。部署失敗時留著，忘了關由看門狗 12 小時的警報提醒。命令（`<P>` 是正式 compose project；`STOCK_DATA_DIR=/data` 由 compose 給，另可加 `--data-dir`）：

  | 動作 | 命令 |
  | --- | --- |
  | 開 | `docker compose -p <P> exec scheduler python -m worker.cli maintenance on --reason "<做什麼，tag 或 Issue>"` |
  | 查 | `docker compose -p <P> exec scheduler python -m worker.cli maintenance status`（owner、心跳、`running_jobs`、`serve_running`） |
  | 關 | `docker compose -p <P> exec scheduler python -m worker.cli maintenance off --reason "<結果>"`（`--only-manual` 只關手動開的，`deploy.sh` 用） |

  `on` 在已開時不改開始時間，只記一列 `on_again`；`running_jobs` 是 `[]` 才開始作業。
- **紀錄**：`/data/logs/maintenance.log` 每次變更一列 JSON：`held`／`released`（作業，`released` 有結果 `success`、`exit <碼>`、例外、`lost: …` 或 `refused: …`）、`lost`（作業失去持有權）、`expired`、`on`／`on_again`／`off`／`off_again`（手動）。
- **serve 不寫 DB 的範圍**：維護模式中 serve 啟動的程序都不寫 `stock.db`：daily、news、us 不啟動 worker；看門狗以唯讀連線查 DB（`mode=ro`、`query_only`）；monitor 只讀日誌、寫佇列目錄；serve 自己的補跑判定也是唯讀。api 照常服務，使用者的寫入（例如追蹤計畫）不受影響，與停 scheduler 相同。scheduler 跑的是 #468 以前的 image（v1.2.3 以前）時沒有維護模式，仍要 `stop scheduler`。
- 不讓回補與 daily 並行。

## 限制

- 三大法人的更正只在之後還有 capture 時才會寫入（[重跑與回補的冪等](#重跑與回補)）：21:30 的 collect 已 `success` 時由 23:00 重抓一次當日法人檔（#466），23:00 之後的更正收不到；23:00 那次沒跑（serve 停了、`low_memory`）時也收不到，過後要收進更正就對該日期手動跑一次 `daily --date`（第一次會重抓）。21:30 失敗、23:00 重跑才成功的日子沒有重抓：23:00 的 collect 本身已是當晚最晚的法人檔。重抓不看時間：21:30 `success` 之後、23:00 之前手動跑 daily，會用掉當天唯一一次重抓，23:00 就直接重用、不再請求，那段時間之後的更正收不到。23:00 更正的值不會改寫當日已算好的訊號、族群與候選。
- universe 取自今日的官方清單。回補期間已下市或轉市的股票與 ETF，DB 已有標的時照樣寫入歷史；沒有標的時只記 `unmatched_bar`，需要 `instruments repair --include-delisted` 才會建標的並補歷史（[重跑與回補](#重跑與回補)）。
- 標的狀態只依官方清單與已存行情表判定，沒有接終止上市、停牌公告。仍在清單內、但 60 個交易日沒有行情列的推定為 `dormant`；未滿 60 個交易日的維持 `active`，日線停在最後交易日（[DATA_SOURCES 標的狀態同步](../DATA_SOURCES.md#標的狀態同步)、[#212](https://github.com/YiCheng0608/stock-lab/issues/212)）。
- 歷史回補不保存當日產業觀測與 MOPS／除權息快照；這些只由 daily 記錄當天。
- 休市判定依官方 no-data 回應；來源暫時失敗的日期記為缺日，不推定休市。
- 全市場 analyze＋evaluate 單次約 4～6 分鐘、峰值約 0.2 GB，連同 candidates／indicators 約 6 分鐘、0.3 GB（2026-10-18，正式 DB 副本：2,409 檔、2024-09-30～2026-10-16 共 496 個交易日；[#184](https://github.com/YiCheng0608/stock-lab/issues/184)）。analyze 每 200 檔 commit 一次 features、group scores 寫完再 commit，每次持有寫入鎖約 2 秒內，與 news 同時執行不會等到 30 秒 busy timeout；analyze 中途失敗時已 commit 的 features／group scores 都是由日線重算的值，重跑會寫出相同結果。group scores 先於 signals commit，所以 analyze 進行中（約 1～2 分鐘）或中途失敗時，API 可能看到新日期族群分數與舊日期訊號並存，重跑 analyze 即一致。
- daily 的 evaluate 每 2,000 個訊號 commit 一次（[Tracking 口徑](../spec/tracking.md#tracking-與-technical-backtest-口徑)第 7 點，[#640](https://github.com/YiCheng0608/stock-lab/issues/640)），每批持有的物件數固定；隨追蹤中的訊號數成長的只有開頭取的 id 清單（6 萬多個整數）與耗時。2026-11-11 正式 DB 副本要重算 63,395 個訊號（大多是 `observation`，每個交易日約 3,900 個，視窗滿 20 根才結束，所以約是最近 20 個交易日的量）：2g 上限下 994 秒、cgroup anon 峰值 289 MB；1g 上限下 953 秒、anon 峰值 280 MB、`memory.peak` 350 MB（evaluation 與 settlement 全部重寫的情況）。#640 以前整個 evaluate 是一個 transaction，訊號與寫出的 evaluation／settlement 都留在 session 直到結束：同一副本在 4g 上限下 18 分鐘被 OOM 結束，正式 scheduler 11/10、11/11 在 2g 上限被結束。

## scheduler 容器的排程（serve）

`python -m worker.cli serve`（[`backend/worker/serve.py`](../../backend/worker/serve.py)，#336）是 scheduler 容器的常駐命令，在[後端 image](SETUP.md#工作目錄環境與啟停) 內取代工作排程器：APScheduler 依台北時間啟動與 [daily／news 工作的註冊與管理](platform/windows.md#dailynews-工作的註冊與管理) 註冊相同的命令，每次一個子程序。compose 設定見 [Docker compose](SETUP.md#docker-compose)（#335），`claude`／`gh` 的認證見 [容器內的 claude 與 gh 認證（.env）](SETUP.md#容器內的-claude-與-gh-認證env)（#337）；正式切換與回退見 [Docker 切換與回退（cutover.sh）](platform/windows.md#docker-切換與回退cutoversh)。

| 工作 | 觸發（預設） | 命令 |
| --- | --- | --- |
| daily | 週一至週五台北 21:30、23:00（`--daily-times`，#466） | `worker.cli job daily --trigger scheduler --data-dir <data> --log-dir <data>/logs --min-free-memory-gb 2 [--claude-cli <claude>] --time-limit-minutes 80`（`--daily-time-limit-minutes`） |
| news | 每 2 小時整點（`--news-interval-hours`，1～24 的整數，超出就 exit 2；每台北日從 0 點重新起算，所以不能整除 24 的值如 5 在午夜前的間隔較短，24 是每日 0 點一次，#368） | 同上換成 `job news`、`--min-free-memory-gb 1`；`--skip-news-llm`（沒給時看 env file 的 `STOCK_SKIP_NEWS_LLM`）交給 job |
| us（美股四檔，#568） | 週二至週六台北 06:30、09:30（`--us-times`） | 同 daily 換成 `job us`、`--min-free-memory-gb 2`（`--us-min-free-memory-gb`，預設同 daily）；`--us-time-limit-minutes` 有給才帶，否則用 job 的 20 分。job 跑 `worker.cli index-bars us-collect --trigger scheduler`（[CLI](CLI.md#現有-worker-cli)、[美股指數](../DATA_SOURCES.md#美股指數)） |
| 看門狗 | 每小時 :15、:45（`--watchdog-minutes`） | `bash tools/ops/watchdog.sh --data-dir <data> --python <serve 的 python>`，`--watchdog-dry-run` 時加 `--dry-run`；monitor 開著時加 `--monitor-dir <monitor 目錄>` |
| 事件 monitor | 每分鐘，只在 `--monitor`（預設 `STOCK_MONITOR`，沒設為 `off`）是 `on`／`record-only` 時（#338） | `bash tools/ops/monitor.sh --once --data-dir <data> --queue-dir <--monitor-dir，預設 /coordination> --python <serve 的 python> --orca <--monitor-orca> --waker <--monitor-waker>`，`record-only` 時加 `--record-only`；見 [統籌事件 monitor](MONITOR.md) |

- **daily 的 21:30 與 23:00**（#466）：
  - **21:30** 是當日的 daily 本體（catchup、collect 到 candidate_notes）。#466 以前第一次是 18:30，但融資檔那時還沒公布，10/19～11/04 的交易日 18:30 都是 `partial`（跑 1～2 分鐘就停），正式資料一直是 21:30 那次產出的。
  - **23:00 在 21:30 `success` 之後**：記 `skipped`（`already_complete`），只做一次[法人重抓](#重跑與回補)（上市 T86、上櫃 `insti/dailyTrade` 各 1 個請求），收進交易所較晚的更正；不跑 catchup、collect 與之後的步驟，不查 MOPS。
  - **23:00 在 21:30 沒有 `success` 時**（`partial`、`failed`、`non_trading_unconfirmed`、`skipped`，或 21:30 沒跑）：同一日期完整重跑一次 daily，規則與 21:30 相同。MOPS 的查詢次數：21:30 的 collect 已 `success`（失敗在之後的步驟）時重用那次 collect，不再查；collect 沒有 `success` 時重查目標日的[日期清單](../DATA_SOURCES.md#重大訊息日期查詢) 1 次（覆蓋以 23:00 的查詢時間為截止，#464），再補查 `gap_dates` 仍未回答的週末與連假：21:30 已回答（`verified`／`empty`）的不再查，只有 21:30 查失敗（`partial`）或沒查到的才再查，通常是 0 次。catchup 照常補過去 5 個交易日裡還沒 collect `success` 的日期（各自查該日的 MOPS 清單），與 21:30 相同。
  - **單次上限 80 分鐘**（#466 決定 [6638008818](https://github.com/YiCheng0608/stock-lab/issues/466#issuecomment-6638008818)）：serve 傳給 job 的 `--time-limit-minutes`（`--daily-time-limit-minutes`）。21:30 那次卡住時 22:50 被 job 結束（job 自己沒結束時，第二道防線在 22:55 結束它），23:00 拿到鎖、把它記 abandoned 並重跑；否則 23:00 會因鎖被占記 `already_running`，當天不會重試。10/19～11/04 最長的一次 daily 是 19.7 分鐘，80 分約有 4 倍餘裕。手動 `job daily` 仍是 job 預設的 2.5 小時。
  - 看門狗從 23:10 起判定當日 daily，00:30 起再判定前一個交易日一次（[排程看門狗](WATCHDOG.md)）：21:30 失敗而 23:00 還會重試時不提早留言，23:00 的重試卡到午夜後也會報。
- **us 的 06:30 與 09:30**（#568 決定 [6729065016](https://github.com/YiCheng0608/stock-lab/issues/568#issuecomment-6729065016)）：
  - 美股收盤是台北 04:00（夏令）或 05:00（冬令），所以週二到週六各抓前一個美股交易日。週日、週一沒有新的美股交易日，不排。
  - **06:30** 是本體：四檔各 1 個 FinMind 請求，抓到台北當日的前一天。
  - **09:30** 是保險：四檔都已存到前一個平日時記 `already_complete`、不發請求；06:30 沒拿到（FinMind 還沒更新、請求失敗或沒跑）才再請求一次。
  - 兩個時間都在 :30，避開每個偶數整點的 news。每個 job 各用自己的檔案鎖（`daily.lock`、`news.lock`、`us.lock`），不共用；靠排程時間錯開。SQLite 是 WAL，連線有 busy_timeout，us 的寫入又小，偶爾重疊也只是等待（#568 review 第 3 點）。
  - 前一個平日是美股休市日時，兩次都拿不到那一天，畫面標「非最新」；下一個交易日的列進來時，那天才記成休市，畫面直接變「最新」，不會出現「美股休市」（[美股指數](../DATA_SOURCES.md#美股指數)，#568 review 第 4 點）。
  - 錯過的日子由下一次自動補上：請求從已存最後一列往前 10 天起，不必另外回補。
  - 記憶體門檻同 daily（2 GB）。被 `low_memory`、`git_busy` 或 `already_running` 擋下時，job 照 daily 的做法讓 worker 記一筆 `skipped` 的 `us_index_collect` run，不發請求；維護模式時只記日誌、不寫 DB。
- **分工**：鎖、起跑前檢查、單次上限、日誌與 exit code 都由 job 負責，與 [daily／news 工作的註冊與管理](platform/windows.md#dailynews-工作的註冊與管理)、[日誌與 run 記錄](#日誌與-run-記錄)相同；serve 自己不加鎖，重疊的觸發照樣啟動 job，由 job 記 `already_running`（同一工作同時最多 3 個，再多的由 APScheduler 擋下並在 stderr 記警告）。不帶 `--git-pull`：程式由 image 決定（部署見 [RELEASE](../RELEASE.md#部署)）。
- **第二道防線**：daily、news 超過 job 上限 5 分鐘（#466 review 前是 10 分鐘，排程 daily 的 21:30 那次因此在 22:55、早於 23:00），或看門狗、事件 monitor 的一輪跑超過 10 分鐘，serve 結束它的程序群組並記 `serve killed`，同工作排程器的上限。
- **錯過的時段**：機器睡眠時錯過的觸發在醒來後補跑一次（APScheduler `coalesce`、不限 misfire 時間，同 StartWhenAvailable）；serve 啟動前的時段不補，只有 daily 例外：serve 啟動時是週一至週五、已過第一個 daily 時間（預設 21:30），而當日 `schedule_runs` 沒有 `success`／`non_trading_day`（讀不到 run 表也算），就立即補跑一次，記 `serve catchup job=daily reason=<not_complete|unreadable:…>`；沒有 `stock.db`（空 volume）不補（#342 決定第 5 點）。部署或切換在晚上重建容器時，當天的 daily 不會因此漏掉；21:30 失敗後、23:00 前重建時也立即補跑，不等 23:00。休市日補跑的 daily 與 21:30 的觸發相同：第一次 no-data 記 `non_trading_unconfirmed`，下一次（23:00）再確認。21:30 已 `success` 時不補跑，所以 23:00 之後才重建的容器不補當晚的法人重抓。維護模式中啟動時不補跑，關閉維護模式時才補（[維護模式](#維護模式)）。us 照同樣規則補跑（#568）：週二至週六、已過第一個 us 時間（預設 06:30），而當日沒有 `success`／`already_complete` 的 `us_index_collect` run（讀不到 run 表也算），就立即補跑一次，記 `serve catchup job=us reason=…`。已經存到前一個平日時，worker 自己記 `already_complete`、不發請求，所以重建容器多跑一次也不會多發請求。
- **維護模式**（#468）：標記檔在時 daily、news 只記 skipped，看門狗與 monitor 照常；serve 每分鐘讀一次標記檔，解除作業持有、心跳超過 10 分鐘的標記檔（`maintenance_expired`），解除後補跑當日 daily 與 us；執行期間持有 `<data>/locks/serve.lock`（`maintenance status` 的 `serve_running`）。見[維護模式](#維護模式)。
- **停止**：子程序隨 serve 結束（PR_SET_PDEATHSIG）。`docker stop`（SIGTERM，`tini` 轉給 serve）時 serve 收到訊號當下就記 `stopping`（由專責執行緒經 wakeup fd 接手，不等下一個排程時間，#503）、結束執行中的 job 後退出；`docker kill` 時整個容器一起結束。兩者都不留下 job 或鎖，被殺的 daily 的 run 列由下一次拿到鎖的 daily 立即記 abandoned（[日誌與 run 記錄](#日誌與-run-記錄)的 `failed`）。
- **輸出**：serve 的列 `<台北時間> serve <事件> key=value`（`ready` 列出各工作下次執行時間；`start`、`end exit=<碼> seconds=<秒>`，被結束時 `exit=killed`；`killed`、`stopping`、`stop_kill`、`stopped`），與 job、看門狗的 stdout 一起寫到 stdout，由 `docker logs` 查；各工作的日誌照舊在 `<data>/logs/`。
- **時間注入**：`--now YYYY-MM-DDTHH:MM[:SS]`（沒有時區時為台北時間）讓排程的時鐘從該時間起算，照真實速度走；daily 與 us 另帶 `--date <該台北日>`，看門狗以 `WATCHDOG_NOW`、事件 monitor 以 `MONITOR_NOW` 判定。日誌檔名與時間戳記仍是真實時間。只用在 DB 副本上的驗證。
- **run 記錄的 image 與 HEAD**：`schedule_runs` 每列的 `summary_json.runtime` 記 `image`（`STOCK_IMAGE_TAG`）、`head`（`STOCK_GIT_HEAD`，沒有時 `git rev-parse HEAD`，都沒有為 null）與 job 持有的鎖 `job_lock`。build context 不含 `.git`，所以 build 時帶入；正式 project 由 [`deploy.sh`](../RELEASE.md#部署) 以 `STOCK_RELEASE_TAG=<tag> STOCK_GIT_HEAD=<該 commit> docker compose build` 帶入（[Docker compose](SETUP.md#docker-compose)，#340），單獨 build 時：`docker build -f backend/Dockerfile -t stock-lab-backend:<tag> --build-arg STOCK_IMAGE_TAG=stock-lab-backend:<tag> --build-arg STOCK_GIT_HEAD="$(git rev-parse HEAD)" .`。
- 其他選項：`--data-dir`、`--log-dir`、`--claude-cli`、`--daily-min-free-memory-gb`、`--news-min-free-memory-gb`、`--daily-time-limit-minutes`、`--news-time-limit-minutes`、`--us-min-free-memory-gb`、`--us-time-limit-minutes`（交給 job）；`--monitor-dir`、`--monitor-orca`、`--monitor-waker`（交給 monitor，後兩者預設 `http_orca.sh`、`http_wake.sh`，經主機的 wake listener，[統籌事件 monitor](MONITOR.md)）。只在 Linux 執行，其他系統 exit 69。

工作排程器的工作為什麼要維持停用（切換前提）、切換與回退見 [Docker 切換與回退（cutover.sh）](platform/windows.md#docker-切換與回退cutoversh)。
