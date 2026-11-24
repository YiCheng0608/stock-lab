<!-- owns: 排程、日誌與 run 記錄、重跑與回補、排程限制 -->
# 排程

每日排程由排程器定時執行一條命令：`python -m worker.cli job daily` 與 `python -m worker.cli job news`（news 之後接著 `worker.cli news-llm`）（[ROADMAP V1-G1](../ROADMAP.md#v1-範圍基線2026-10-17-核定)）。job（[`backend/worker/job.py`](../../backend/worker/job.py)）自己負責單一執行個體（檔案鎖）、起跑前檢查、單次上限、日誌與保留，不依賴排程器的設定，換排程器只要定時執行同一條命令。job 只在 Linux（[後端 image](SETUP.md#工作目錄環境與啟停)）執行（#333），所以這份程式的排程器是 scheduler 容器的 `worker.cli serve`（[scheduler 容器的排程（serve）](#scheduler-容器的排程serve)）。自動下單不在第一版範圍。

| 排程器 | 跑的程式 | 資料與 job 日誌 | 本節的操作 |
| --- | --- | --- | --- |
| scheduler 容器（`serve`，#336） | 正式 compose project 的 image，由 [`deploy.sh`](../RELEASE.md#部署) 部署（#340） | volume `stock-data` 的 `/data`（`stock.db`、`raw/`、`logs/`、`locks/`） | [scheduler 容器的排程（serve）](#scheduler-容器的排程serve)；daily、news 與看門狗的判定、日誌與 run 記錄同[排程看門狗](WATCHDOG.md)、[daily／news 工作的註冊與管理](platform/windows.md#dailynews-工作的註冊與管理)與本文[日誌與 run 記錄](#日誌與-run-記錄)～[限制](#限制) |
| Windows 工作排程器（Docker 切換後停用、不再當回退） | 見 [Windows 工作排程器](platform/windows.md) | 見 [Windows 工作排程器](platform/windows.md) | [Windows 工作排程器](platform/windows.md)（daily／news、看門狗與 monitor 的工作，切換與回退） |

位置（使用者 2026-10-17 決定）：正式資料目錄（[LOCAL](LOCAL.md#正式位置使用者決定)；`stock.db`、`raw/`、`logs/`），以 `STOCK_DATA_DIR` 指向；切換（#342）時 `stock.db`、`raw/` 與 `logs/` 複製進 volume `stock-data`（`raw_payloads.payload_path` 不改寫，容器內經 [`app.raw_paths.payload_file`](../../backend/app/raw_paths.py) 讀），之後主機的這個目錄只剩統籌的檔案；回退用的原檔 `stock.db` 與 `raw/` 已於 2026-11-05 刪除（使用者決定，[LOCAL](LOCAL.md#正式位置使用者決定)），正式資料現在只在 volume 裡。排程只從發佈 checkout（[LOCAL](LOCAL.md#正式位置使用者決定)；repo 的獨立 clone）執行：它是正式 compose project 的目錄，停在 `tools/ops/deploy.sh` 部署的 tag，排程起跑不 `git pull`（升版見 [RELEASE](../RELEASE.md)）；不從 `master` 管理 checkout。統籌心跳檔、換手標記與壓縮計數檔都在主機資料目錄的 `logs/` 下（[統籌手冊](../COORDINATOR.md#統籌-session)），事件 monitor 的事件佇列與它自己的心跳、日誌也是：scheduler 容器以 `STOCK_COORDINATION_DIR` 把這個目錄 bind mount 到 `/coordination`（[統籌事件 monitor](MONITOR.md)）。

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
- **run 記錄**：`schedule_runs` 每次 daily 執行一列（目標日、觸發來源、開始／結束、狀態、錯誤、collect 筆數、摘要），摘要 `summary_json` 每列都有 `runtime`：跑的 image 與 commit（`image`、`head`，見 [daily／news 工作的註冊與管理](platform/windows.md#dailynews-工作的註冊與管理) 執行的版本與 [scheduler 容器的排程（serve）](#scheduler-容器的排程serve)），這是一列唯一的版本欄位（#340 拿掉 #314 的 `git_tag`／`HEAD`）；`schedule_run_steps` 每步一列（catchup／collect／trading_calendar／analyze／evaluate／candidates／indicators／mainstream／h2_list／theme_heat／period_backfill／x4_list／plan_tracking／strategy_levels／action_tiers／candidate_notes／theme_discovery 的開始／結束、狀態、錯誤、處理筆數，collect 另連 `ingestion_runs.id`；`already_complete` 的列若重抓了三大法人檔，只有一列 institutional_refetch 步驟，連到 `run_type=institutional_refetch` 的 ingestion run；catchup 的 `details_json` 列出檢查與補抓的日期及各日結果）。查詢：`python -m worker.cli schedule-runs --date YYYY-MM-DD`。news 的結果在 `run_type=news` 的 ingestion run，news-llm 的在 `run_type=news_llm`（`metadata_json` 記每批則數、耗時、模型與 token 用量，API 查詢要加 `include_metadata=true`）。

| run 狀態 | 意義 |
| --- | --- |
| `success` | collect、analyze、evaluate、candidates、indicators、plan_tracking 都成功（或該步驟回 `no_data`；沒有任何追蹤計畫時 plan_tracking 是 `success`、0 筆）；trading_calendar、mainstream、h2_list、x4_list、strategy_levels、action_tiers、candidate_notes、theme_discovery 與 period_backfill 的狀態不列入，`success` 的定義不因新增這些步驟而改變（G7 起的判定照舊）。catchup 沒補齊不改變 run 狀態，記在該步驟與 `summary_json.steps.catchup`，由看門狗留言。 |
| `partial` | collect 有缺（例如籌碼尚未公布）；後續步驟記 `skipped`，錯誤欄列 collect 警告。 |
| `non_trading_day` | 官方來源明確回報該週間日無交易，且已確認（當日目標要兩次觸發都回 no-data）。 |
| `non_trading_unconfirmed` | 當日目標第一次回 no-data，等下一次觸發確認；不算完成，exit code 0。 |
| `failed` | 某步驟失敗或拋例外；錯誤欄記步驟與訊息，依賴它的步驟記 `skipped`（evaluate 與 candidates 依賴 analyze；trading_calendar、indicators、mainstream、h2_list、x4_list、plan_tracking 與 theme_discovery 只依賴 collect；strategy_levels 與 action_tiers 依賴 analyze；candidate_notes 依賴 candidates）。run 列記錄執行的主機與 PID；由 job 持鎖啟動的 run 列另記鎖的路徑（`summary_json.runtime.job_lock`），下一次拿到同一把鎖的 daily 不看主機與 PID，立即把它記 `failed`（`abandoned: process <PID> on <主機> no longer holds <鎖>`）：重建的容器 hostname 不同，PID 也可能被新程序重用（#336）。其餘的列：同主機的新執行發現該 PID 已不存在（例如被系統終止）時，立即把舊列改記 `failed`（abandoned）並照常執行；其他情況要超過 2.5 小時（與 job 預設的單次上限相同）仍為 `running` 才記 abandoned，在那之前同日的新執行記 `skipped`（`already_running`）。 |
| `skipped` | 同目標日已有 `success`／`non_trading_day`（`already_complete`）、另一次執行仍在進行（`already_running`：run 列仍在 running，或 job 拿不到鎖，後者 `related_run_id` 指向當時 running 的列、沒有則為空；DB 不在 head 時不寫列，見 [daily／news 工作的註冊與管理](platform/windows.md#dailynews-工作的註冊與管理)），或起跑前檢查未通過（`low_memory`／`git_busy`；#314 前的列另有 `git_pull_failed`）；不碰資料，唯一的例外是 `already_complete` 時重抓三大法人檔：結果記在 `summary_json.institutional_refetch`（`status`、`run_id`、`idempotent_reuse`、`requests`、`revised_rows`、`unchanged_rows`、`value_fills`，失敗時有 `error`），run 的 `records` 是更正的列數。重抓失敗也維持 `skipped`、exit code 0，當日是否完成仍看先前那列 `success`。 |

trading_calendar 步驟呼叫 `worker.trading_calendar.run_trading_calendar(目標日)`，在 collect 成功後、analyze 之前執行，抓目標日的年度與下一年度的[官方休市表](../DATA_SOURCES.md#交易日曆)（2 個請求），供 analyze 推算訊號的[規則最早執行日](../spec/README.md#價位etf-與生命週期)。寫入列數記在步驟列的 `records`，`details_json.years` 記各年度結果。它的任何狀態（`failed`、`partial`、例外）都只記在該步驟列（原因寫在 `error`，例如 `holiday schedule 2027 unavailable: …`）與 `summary_json.steps`，**不改變 run 狀態與 exit code**；analyze 照跑並使用表內已有的日曆，日曆答不出來時訊號的日期留空，analyze 步驟的 `details_json.execution_calendar` 記 `status`（`available`／`unavailable`）、`reason`、`missing_year`、`next_session` 與 `signals_without_date`，看門狗以 `invariant_execution_calendar` 留言（[排程看門狗](WATCHDOG.md)）。休市日 collect 為 skipped 時它也記 `skipped`。手動更新：`python -m worker.cli trading-calendar`（[現有 worker CLI](CLI.md#現有-worker-cli)）。

indicators 步驟呼叫 `worker.indicator_batch.run_indicator_batch(目標日)`；只要 collect 成功就執行（analyze 失敗也跑），失敗時 run 記 `failed`、錯誤欄記 indicators 訊息。

mainstream 步驟呼叫 `worker.mainstream.run_mainstream(目標日)`（[#768](https://github.com/YiCheng0608/stock-lab/issues/768)），排在 candidates 與 indicators 之後，寫[主流族群前 20](#主流族群前-20)。只讀日線、公司行動與族群成員，所以只要 collect 成功就跑：analyze 或 candidates 失敗也照算，`today_list` 那天就全是 null。步驟列的 `records` 是寫入的檔數。它不阻擋 daily，任何狀態（`failed`、例外）都只記在該步驟列與 `summary_json.steps`，另在 stderr 寫一行 `warning: mainstream_v1 <日期> failed: <原因>`（進 daily 日誌），**不改變 run 狀態與 exit code**，今日名單也不受影響。

h2_list 步驟呼叫 `worker.h2_list.run_h2_list(目標日)`（[#881](https://github.com/YiCheng0608/stock-lab/issues/881)），排在 mainstream 之後，寫 [H2 名單](#h2-名單)。只讀日線與公司行動，所以只要 collect 成功就跑：analyze 或 candidates 失敗也照算，`today_list` 那天就全是 null。步驟列的 `records` 是寫入的檔數。它不阻擋 daily，任何狀態（`failed`、例外）都只記在該步驟列與 `summary_json.steps`，另在 stderr 寫一行 `warning: explore_research_v2_X2 <日期> failed: <原因>`（進 daily 日誌），**不改變 run 狀態與 exit code**，今日名單與主流族群前 20 也不受影響。

theme_discovery 步驟呼叫 `worker.theme_discovery.run_theme_discovery(目標日)`（[#1018](https://github.com/YiCheng0608/stock-lab/issues/1018)），排在最後、candidate_notes 之後（它的 `claude -p` 不拖到候選說明）：算當天的[量價共振分群](#新題材發現)並存檔，再把符合條件的群交 `claude -p` 命名、提成員與證據，證據過核對才寫成待核實的候選題材。只讀日線，所以只要 collect 成功就跑。步驟列的 `records` 是當天的群數；AI 那一步失敗（CLI 不在、未登入、逾時）時步驟是 `partial`，分群照樣存。它不阻擋 daily，任何狀態都只記在該步驟列與 `summary_json.steps`，例外時 stderr 寫一行 `warning: theme_discovery <日期> failed: <原因>`，**不改變 run 狀態與 exit code**，今日名單不受影響。

x4_list 步驟呼叫 `worker.x4_list.run_x4_list(目標日)`（[#1016](https://github.com/YiCheng0608/stock-lab/issues/1016)），排在 h2_list 與 period_backfill 之後（period_backfill 在窗口內補寫的月營收、季報，法定期限前的可得日就是抓取當天，研究工具之後算同一天會讀到，所以 x4_list 要在它之後算），寫 [X4 名單](#x4-名單)。只讀日線、月營收與季報 EPS，所以只要 collect 成功就跑：analyze 或 candidates 失敗也照算，`today_list` 那天就全是 null。步驟列的 `records` 是寫入的檔數。它不阻擋 daily，任何狀態（`failed`、例外）都只記在該步驟列與 `summary_json.steps`，另在 stderr 寫一行 `warning: explore_research_v2_X4 <日期> failed: <原因>`（進 daily 日誌），**不改變 run 狀態與 exit code**，今日名單、主流族群前 20 與 H2 名單也不受影響。

candidates 步驟呼叫 `worker.candidates.run_candidates(目標日)`，只讀當日訊號、籌碼、族群榜與新聞，不改行情、訊號與追蹤；失敗時 run 記 `failed`（exit code 1，看門狗與排程異常處理照 `failed` 處置）、錯誤欄記 candidates 訊息，indicators 照跑。行情與訊號已寫入，只需重跑候選：`python -m worker.cli candidates --date YYYY-MM-DD`（不需 `daily --force`；接著會補該日的 AI 說明，`--skip-notes` 跳過，[CLI](CLI.md)）。

plan_tracking 步驟呼叫 `worker.plan_tracking.run_plan_tracking(目標日)`，在 indicators 之後、candidate_notes 之前執行（candidate_notes 可能跑很久），只讀日線、公司行動、停牌事件與計畫自己的價位快照，更新[使用者追蹤計畫](../spec/tracking.md#使用者追蹤計畫)；collect 成功就執行（analyze 失敗也跑），失敗時 run 記 `failed`、錯誤欄記 plan_tracking 訊息，其他步驟的結果不變。只需重算計畫：`python -m worker.cli track-plans --date YYYY-MM-DD`。`schedule_run_steps` 以 run 與步驟名稱找列，`sequence` 只用來排序（trading_calendar 為 2、analyze 為 3，mainstream 為 7（#768），h2_list 為 8（#881），theme_heat 為 9（#1017），period_backfill 為 10、x4_list 為 11，plan_tracking 為 12、strategy_levels 為 13、action_tiers 為 14、candidate_notes 為 15、theme_discovery 為 16（#1018；#1017 以前 period_backfill～candidate_notes 是 9～14（#1016），#1016 以前 plan_tracking～candidate_notes 是 9～12、period_backfill 是 13，#881 以前依序是 8～12；#476 以前 candidate_notes 為 10）；之前的 run 維持寫入當時的號碼）。

strategy_levels 步驟呼叫 `worker.strategy_levels.run_strategy_levels(目標日)`，在 plan_tracking 之後、candidate_notes 之前執行，analyze 成功（含 `no_data`）才跑，否則記 `skipped`（`analyze_not_successful`）；為當日 analysis 訊號寫[條件價位](../spec/strategy_levels.md)，只讀已存資料、不改訊號、候選與追蹤，處理的訊號數記在步驟列的 `records`，`details_json` 有寫入列數與 `availability` 分佈。它的任何狀態（`failed`、`partial`、例外）都只記在該步驟列與 `summary_json.steps`，**不改變 run 狀態與 exit code**，不觸發 daily 失敗的看門狗；失敗由看門狗的資料不變量 `invariant_strategy_levels`（[排程](#)）回報，個股頁策略總表對沒有條件價位列的觀察訊號顯示「觀察價位未產生」（#274）。daily 已 success 後不會重跑，補算或重算以 `python -m worker.cli strategy-levels --date YYYY-MM-DD`（[現有 worker CLI](CLI.md#現有-worker-cli)）。

action_tiers 步驟呼叫 `worker.action_tiers.run_action_tiers(目標日)`，在 strategy_levels 之後、candidate_notes 之前執行，analyze 成功（含 `no_data`）才跑，否則記 `skipped`（`analyze_not_successful`）。它把首頁與行動頁 action tier 的日資料部分寫進 `action_tier_snapshots`（[action tier 預算與新聞投影](#action-tier-預算與新聞投影)），步驟列的 `records` 是寫入的標的數。任何狀態（`failed`、例外）都只記在該步驟列與 `summary_json.steps`，**不改變 run 狀態與 exit code**：頁面在沒有當日預算時改為即時計算，結果相同，只是比較慢。重算以 `python -m worker.cli action-tiers --date YYYY-MM-DD`。


candidate_notes 步驟呼叫 `worker.candidate_notes.run_candidate_notes_batch(目標日)`，在 candidates 成功（含 `no_data`）後最後執行，為當日候選寫 [AI 進出點說明](../spec/candidate_score.md#候選-ai-進出點說明)；最多 4 次 `claude -p`，各 300 秒逾時（實測一次約 7 秒）。它的任何狀態（`success`／`partial`／`failed`／`skipped`／`no_data`，含找不到 claude、未登入、額度用盡、逾時與例外）都只記在該步驟列與 `summary_json.steps`，**不改變 run 狀態與 exit code**；candidates 不成功時記 `skipped`（`candidates_not_successful`）。最新候選日的候選清單產生超過 30 分鐘仍沒有一檔完成的說明時，看門狗以 `invariant_candidate_notes` 留言（daily 或 candidate_notes run 執行中不判定，[WATCHDOG](WATCHDOG.md)；#517）。daily 已 success 後 23:00 那次不會重跑，`pending` 或未說明的候選以 `python -m worker.cli candidate-notes --date YYYY-MM-DD` 補（只送未完成者）；手動 `worker.cli candidates` 重產候選後預設接著跑這一步（[CLI](CLI.md)）；結果查 `/api/ingestion-runs?q=candidate_notes&include_metadata=true` 或步驟列。

period_backfill 步驟呼叫 [`worker.period_backfill.run_period_backfill(目標日)`](../../backend/worker/period_backfill.py)（[#536](https://github.com/YiCheng0608/stock-lab/issues/536)），在 h2_list 之後、x4_list 之前執行（x4_list 讀它補寫的月營收與季報，#1016；排在 candidate_notes 之後時那幾天的 X4 名單會少讀當天可得的列），collect 成功就跑（不依賴 analyze）；後面的步驟因此最多晚約 300 秒，daily 的總時間不變。它在法定期限前後的窗口裡，跑 `fundamentals backfill` 與 `revenue backfill` 的同一套程式（[季度財報回補](../DATA_SOURCES.md#季度財報回補)、[月營收](../DATA_SOURCES.md#月營收)），補最近一期與前一期。日快照只有一期、換期後就不再更新，換期後才上市的新股、晚申報與更正都收不到（#536 AC-1 的量測）：

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
  - 版本常數：`ACTION_TIER_STORE_VERSION`、`action_tier_v1`、`STRATEGY_LEVELS_VERSION`、candidate score 版本、registry 與分級門檻。
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

## 主流族群前 20

daily 在今日名單之後，另算一份「主流族群前 20」（`mainstream_v1`，[#768](https://github.com/YiCheng0608/stock-lab/issues/768)；定義與參數見 [`app.mainstream`](../../backend/app/mainstream.py) 的模組說明，AC-1 的決定是 [6892019991](https://github.com/YiCheng0608/stock-lab/issues/768#issuecomment-6892019991)）。它不附點位，也不改今日名單、`candidate_score_v7` 與 `hot_group_v1`。

- **選法**：
  - 族群取 active 的 `official_industry` 與 `theme`，母體沿用研究的共同口徑。
  - 族群強弱＝族群內有值成員 240 日報酬的前 ⌈n/3⌉ 檔（至少 3 檔）平均，減加權指數 240 日報酬；有值成員不到 5 檔的族群不排名。
  - 依序取 5 個族群；成員有 80% 以上已在前面選上的族群裡時跳過（去重）。
  - 5 個族群的成員聯集照 240 日報酬取前 20，不設族群上限。
- **存放**：`mainstream_runs`（每個交易日、每個版本一列，`status` 是 `computed` 或 `zero`）與 `mainstream_items`（每檔一列）。同一天重算時整份換掉；算失敗時不寫入，前一份留著。
- **誰寫**：daily 的 mainstream 步驟（`worker.mainstream.run_mainstream`）。
- **讀取**：`GET /api/mainstream?date=`，沒給日期時取最新一份。
  - 那天沒有算時 `status` 是 `missing`。
  - 每檔的 `today_list` 在讀取時才查當天的今日名單（名次與 `entry_type`），不寫進表。
  - `recent_closes` 和 `/api/candidates` 同形。
- **重算**：目前沒有 CLI。在 api 或 scheduler 容器裡跑 `python -c 'import datetime, worker.mainstream as m; print(m.run_mainstream(datetime.date(2026, 11, 13)))'`（日期換成要重算的那天）。
- **實測**（2026-11-15，正式 DB 副本，2026-11-13）：計算 1.8 秒，母體 579 檔、可排名族群 30 個；`/api/mainstream` 讀取 0.07 秒。

## H2 名單

daily 在主流族群前 20 之後，另算一份「H2 名單」（`explore_research_v2_X2`，[#881](https://github.com/YiCheng0608/stock-lab/issues/881)）。它是研究工具 `explore_research` 第 2 版的 X2：通過探索段與驗證段，使用者決定進產品、先只顯示名單（[#1 7044998169](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-7044998169)）。定義凍結，產品程式 [`app.h2_list`](../../backend/app/h2_list.py) 照研究程式逐項重寫，模組說明列出每一項；AC-1 的決定是 [7045371555](https://github.com/YiCheng0608/stock-lab/issues/881#issuecomment-7045371555)。產品不 import `tools/research`，兩邊是否相同由 `backend/tests/test_h2_list.py` 的金樣鎖住：同一份 fixture 的每個交易日，名單要和研究工具逐筆相同。它不附點位，也不改今日名單與主流族群前 20。

- **選法**：當天母體依 `high_gap_240`（還原收盤 ÷ 最近 240 根日線的還原最高價 − 1）大者先，取 20 檔。
  - 同分依 `sha256("<日期>:<instrument_id>")` 排。
  - 缺值（不到 240 根、窗口內有最高價缺值）排在有值的後面，但不剔除。有值的不到 20 檔時，缺值的會補進名單，`high_gap_240` 存 null。
- **母體和 `mainstream_v1` 不同**，兩者沒有共用函式：
  - 停牌：H2 照研究，`is_suspended` 為真**或**「零量且開高低收相同」都算，T 那根停牌就不在母體。mainstream 只看 `is_suspended`。
  - 均量：兩者都是最近 20 根日線（含 T）平均 ≥ 1,000 張。H2 不足 20 根就不在母體，不另要求 241 根。
  - 種類：這點兩者相同，都只取 `stock`／`ipo`（依 `instrument_type`，不看 `status`）。
  - 日線：只算交易日（當天有 `stock` 日線的日子）上的日線，「最近 240 根」是這種日線的根數，停牌沒日線的日子不算。
  - 還原：每筆公司行動各自算因子（`worker.pipeline._corporate_action_factor`），只取 T 以前（含）的；沒有參考價的，用該日前最近一根 > 0 的收盤補。不用 mainstream 的 `_action_factor_by_bar`。
  - 研究工具的 `bar_exclusions.json` 不搬進產品：三段 code_reuse 只在 DB 存有舊公司日線時才生效。正式 DB 的 stock 日線從 2024-09-30 起，那三檔沒有舊公司日線（#881 AC-4 查過）；上櫃 2007 那段也早於正式 DB。只有在研究 DB 這類更早的歷史上重算舊日期，才可能和研究工具不同。
- **存放**：通用的策略名單表（[#1014](https://github.com/YiCheng0608/stock-lab/issues/1014)，`app.strategy_lists`；migration 0035 把 0034 的 `h2_runs`／`h2_items` 搬進來並刪掉舊表，降級時反向搬回），H2 的 `strategy` 是 `h2`。之後的策略名單（X4 等）寫同一組表，每個策略只給「算一天」與「欄位轉成 API」兩個函式，登記在 `strategy_lists.strategies()`。
  - `strategy_list_runs`：每個交易日、策略、版本一列（唯一鍵 `trading_date`＋`strategy`＋`version`）。`definitions_sha256` 記定義的雜湊（H2 是研究定義 `600dc942…ebec63`），`status` 是 `computed` 或 `zero`，`universe_count` 是母體檔數，`item_count` 是名單檔數，`config_json` 是參數，`computed_at` 是 UTC 寫入時間。
  - `strategy_list_items`：每檔一列（`run_id`、`trading_date`、`instrument_id`、`strategy`、`version`、`rank`、`close` 是 T 的原始收盤；唯一鍵 `trading_date`＋`instrument_id`＋`strategy`＋`version`）。策略自己的值放 `values_json`，H2 是 `{"high_gap_240": <值或 null>}`。
  - 同一天重算時整份換掉；算失敗時不寫入，前一份留著。T 不是交易日（沒有 `stock` 日線）時算失敗。
  - 降級到 0034 只搬回 `h2` 的列；別的策略的名單 0034 沒有地方放，跟著新表刪掉。
- **誰寫**：daily 的 h2_list 步驟（`worker.h2_list.run_h2_list`），只算 daily 的目標日。catchup 只跑 collect，它補抓的日子沒有 H2 名單，`/api/h2?date=` 對那些日子回 `missing`；主流族群前 20 也一樣。要補時照下面的「重算」逐日跑。
- **讀取**：`GET /api/h2?date=`，沒給日期時取最新一份；`GET /api/strategy-lists/h2?date=` 回一樣的內容（#1014，不認得的策略回 404），另加 `recent_picks`（下面「近 60 日入選」，#1021）。前端從 #1021 起讀 `/api/strategy-lists/h2`；`/api/h2` 的回應不變。
  - 回傳 `status`、`trading_date`、`version`、`definitions_sha256`、`window`、`computed_at`、`universe_count` 與 `items`。
  - 每檔有 `rank`、`instrument`（`id`、`exchange`、`symbol`、`name`、`instrument_type`）、`high_gap_240`（缺值為 null）、`close`（T 的原始收盤）、`market`、`recent_closes`，以及 `today_list`。
  - `today_list` 在讀取時才查當天的今日名單（名次、`entry_type`、`score_version`），不在今日名單是 null，不寫進表。
  - `market`（T 的收盤與漲跌）與 `recent_closes`（近 30 個交易日的原始收盤，畫走勢線）也在讀取時才算，不寫進表，寫法同 `/api/mainstream`（`market_change.adjacent_change`、`candidate_view.recent_closes`；[#882](https://github.com/YiCheng0608/stock-lab/issues/882)）。
  - 那天沒有算時 `status` 是 `missing`、`items` 是空的；母體是空的那天是 `zero`。
  - 不附進場區、停損與目標。
- **近 60 日入選**（[#1021](https://github.com/YiCheng0608/stock-lab/issues/1021)，`app.strategy_lists.recent_picks`；每個策略都有，X4 也是）：研究測的是每天買一份、每份抱 60 個交易日，帳上是近 60 個交易日名單的聯集，所以 `/api/strategy-lists/{strategy}` 另回 `recent_picks`，在讀取時算、不寫進表。
  - 窗口：到這份名單的日期（含）為止最近 60 個交易日（有 `stock` 日線的日子，同上面「日線」的口徑），只讀同策略、同版本存下的名單。
  - `recent_picks`：`sessions`（60）、`days`（窗口內有存名單的天數，回補前會少於 60）、`since`（其中最早一天）與 `items`。每檔 `instrument`、`count`（入選天數）、`first_date`、`last_date`（窗口內第一次與最後一次）、`today_rank`（這份名單的名次，不在是 null）；依 `count` 多者先、`last_date` 晚者先、代號排。這份名單的每檔另有 `recent_picks`（`count`、`first_date`、`last_date`）。那天沒有名單（`missing`）時是 null。
  - 只陳述哪天入選、入選幾次，不算權重或部位。
- **重算**：在 api 或 scheduler 容器裡跑 `python -c 'import datetime, worker.h2_list as h; print(h.run_h2_list(datetime.date(2026, 11, 20)))'`（日期換成要重算的那天）。一次只算一天：catchup 補抓的日子、migration 0034 降級後再升回時，舊日期都要逐日跑（0035 的升降級會搬列，不必重算）。
- **回補**（#1021）：`python -m worker.cli strategy-lists backfill [--strategy h2|x4|all] [--sessions 60] [--until YYYY-MM-DD] [--force]`（[CLI](CLI.md#現有-worker-cli)）把最近 60 個交易日的名單由舊到新逐日寫進表（每天一個 commit，同 daily 的那一步）。已有名單的日子不重算（daily 存下的名單不被改寫），重跑只補還沒有的日子；`--force` 才整段重算。某天算不出來就記在 `failed`、接著算下一天，`status` 是 `failed`（exit 1）。起跑時持有[維護模式](#維護模式)，台北 21:15～23:30 拒絕起跑（exit 75）；正式 DB 也避開偶數整點。
- **實測**（2026-11-21，正式 DB 副本，2026-11-20）：計算 8.2～9.6 秒，母體 586 檔（有值 584）；`/api/h2` 讀取 0.01 秒。2026-11-13 在研究 DB 上，研究工具與本模組的 20 檔逐檔相同。

## X4 名單

daily 在 H2 名單之後，另算一份「X4 名單」（頁面分頁名「盈餘殖利率前 20」，`explore_research_v2_X4`，[#1016](https://github.com/YiCheng0608/stock-lab/issues/1016)）。它是研究工具 `explore_research` 第 2 版的 `HYPOTHESES["X4"]`，驗證段是前瞻觀察（[策略證據「前瞻監測與下架」](../spec/evidence.md#前瞻監測與下架)），使用者決定放上頁面（[#1 7106346106](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-7106346106)、[7114503228](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-7114503228)）。定義凍結，產品程式 [`app.x4_list`](../../backend/app/x4_list.py) 照研究程式逐項重寫，模組說明列出每一項；產品不 import `tools/research`，兩邊是否相同由 `backend/tests/test_x4_list.py` 的金樣鎖住：同一份 fixture 的每個交易日，名單要和研究工具逐筆相同。它不附點位，也不改今日名單、主流族群前 20 與 H2 名單。

- **選法**：先篩後排。當天母體只取 `revenue_yoy` > 0 且 `eps_growth_yield` > 0 的，依 `eps_yield_raw`（最新一季單季 EPS × 4 ÷ T 的未還原收盤）大者先，取 20 檔。
  - 同分依 `sha256("<日期>:<instrument_id>")` 排。
  - 兩個條件任一缺值就不通過。通過的不到 20 檔時，名單就只有那幾檔，不像 H2 補缺值。
- **母體**：和 H2 相同（`stock`／`ipo`、T 有日線且不停牌、最近 20 根交易日日線平均 ≥ 1,000 張；停牌與交易日的口徑見 [H2 名單](#h2-名單)）。
- **輸入**：
  - `revenue_yoy`：`announcement_date` ≤ T 的月營收中最新的月份（營收有值的列），該月營收 ÷ 去年同月 − 1；最新月份距 T 超過 80 個日曆日、或去年同月是空值或 ≤ 0 時缺值。
  - 單季 EPS：`announcement_date` ≤ T、EPS 有值的季報；EPS 是年度累計，單季是和前一季相減（Q1 就是累計數），前一季不在時缺值。最新一季是期末最晚的一季，距 T 超過 200 天、或沒有單季值時沒有最新一季；去年同季是一年前同一季的單季值。
  - `eps_growth_yield`：（最新一季單季 EPS − 去年同季）÷ T 的收盤，只用正負。研究工具除的是還原收盤；公司行動的因子都 > 0，所以正負和除以未還原收盤相同，產品用未還原收盤（金樣有一筆除息確認）。
- **存放**：通用的策略名單表（`app.strategy_lists`，同 [H2 名單](#h2-名單)的「存放」），`strategy` 是 `x4`，`definitions_sha256` 是 `600dc942…ebec63`（和 H2 同一版研究定義）。`values_json` 是 `eps_yield_raw`、`revenue_yoy`、`revenue_month`（該月 1 日）、`quarter_end`（最新一季的期末）、`quarter_eps`、`quarter_eps_year_before`。`universe_count` 是母體檔數，`item_count` 是名單檔數；同一天重算時整份換掉，算失敗時不寫入，T 不是交易日時算失敗。
- **誰寫**：daily 的 x4_list 步驟（`worker.x4_list.run_x4_list`），只算 daily 的目標日；catchup 補抓的日子沒有 X4 名單，要補時照下面的「重算」逐日跑。
- **讀取**：`GET /api/strategy-lists/x4?date=`，沒給日期時取最新一份。
  - 回傳 `status`、`zero_reason`、`trading_date`、`version`、`definitions_sha256`、`list_size`（20）、`computed_at`、`universe_count`、`item_count` 與 `items`。
  - 每檔有 `rank`、`instrument`（`id`、`exchange`、`symbol`、`name`、`instrument_type`）、`eps_yield_raw`、`revenue_yoy`、`revenue_month`（`YYYY-MM`）、`quarter_eps`（`quarter` 如 `2026Q3`、`period_end`、`eps` 是單季 EPS、`year_before_eps` 是去年同季）、`close`（T 的原始收盤）、`market`、`recent_closes` 與 `today_list`；後三個在讀取時才算，寫法同 [H2 名單](#h2-名單)的「讀取」。
  - 那天沒有算時 `status` 是 `missing`、`items` 是空的。名單是空的那天是 `zero`，`zero_reason` 分兩種：`universe_empty`（母體是空的，`universe_count` 0）與 `none_passed`（母體有股票，但沒有一檔通過兩個條件）；其他狀態的 `zero_reason` 是 null。
  - 不附進場區、停損與目標。
- **近 60 日入選與回補**：同 [H2 名單](#h2-名單)的「近 60 日入選」與「回補」（`--strategy x4`）。
- **重算**：在 api 或 scheduler 容器裡跑 `python -c 'import datetime, worker.x4_list as x; print(x.run_x4_list(datetime.date(2026, 11, 20)))'`（日期換成要重算的那天）。一次只算一天；近 60 日回補用上面的 `strategy-lists backfill`，已存的日子不重寫。重算舊日期讀的是現在的 DB：之後重編的 EPS、更正過的月營收（#543）、之後才補寫但可得日較早的列都會讀到，所以結果可能和當天 daily 存下的不同；研究工具在同一份 DB 上算也一樣，金樣不受影響。
- **限制**：同一檔、同一期末、同一 `announcement_date` 有兩列季報（`fiscal_period` 不同）且 EPS 不同時，產品與研究工具都只照 `announcement_date`、`period_end` 排序取後者，兩邊可能取到不同列。2026-11-24 的正式 DB 副本上是 0 組。
- **實測**（2026-11-24，正式 DB 副本，最新交易日 2026-11-23）：算一天 2.7～3.6 秒、峰值 0.08 GB；2026-11-23 母體 588 檔、通過兩個條件 346 檔、名單 20 檔。
  - 2026-11-20 的名單和同一份副本 `forward_watch.py --watch X4` 的 `picks.csv` 逐筆相同（`picks.csv` 只有這一天：訊號日的下一個交易日要在資料裡）。
  - 2026-11-20 與 2026-11-23 的名單和研究工具本身（`explore_research.load_context`＋`_rank`）逐筆相同，`eps_yield_raw`、`revenue_yoy` 差 0。

## 題材熱度

daily 在 H2 名單之後、X4 名單之前算當天的題材熱度（`theme_heat_v1`，[#1017](https://github.com/YiCheng0608/stock-lab/issues/1017)）。公式、缺資料與存放見[規格](../spec/theme_heat.md)；熱度不是買賣訊號，今日名單與其他名單都不讀它。

- **誰寫**：daily 的 theme_heat 步驟（`worker.theme_heat.run_theme_heat`），只算 daily 的目標日，只讀已存的日線、籌碼、新聞與題材成員。失敗是不阻擋的步驟（`NON_BLOCKING_STEPS`）：stderr 一行 `warning:`，step 列記 `failed`，run 狀態與結束碼不變，那天不寫入、之前算的留著。T 不是交易日（沒有 TAIEX 日線）時算失敗。
- **存放**：`theme_heat_runs` 與 `theme_heat_scores`（[欄位](../spec/theme_heat.md#存放與讀取)）。同一天重算時整份換掉。
- **讀取**：`GET /api/theme-heat?date=`；族群頁的「熱度」分頁讀它。
- **重算與回算**：`python -m worker.cli theme-heat --date <日>` 算一天；`--since <起日> [--until <迄日>]` 逐個交易日重算，每天用那天有效的成員（不回溯），`--weekly` 再印每週最後一個交易日的排名（[CLI](CLI.md#現有-worker-cli)）。catchup 補抓的日子、migration 0036 降級後再升回時用它補。新聞分項以最早一次新聞收集 run（2026-10-18）為準，前 20 日窗口整段在它之後才有值；23:00 的法人重抓會改寫 T 的籌碼，當晚存的熱度可能和之後重算不同（[限制](../spec/theme_heat.md#限制)）；初版題材的成員從 2026-01-01 起有效，之前的日子沒有題材上榜（`status=zero`）。

## 新題材發現

daily 的 theme_discovery 步驟找題材表以外、正在一起動的一群股票（[#1018](https://github.com/YiCheng0608/stock-lab/issues/1018)，方法照評估 [#1003 AC-2 第 2 節](https://github.com/YiCheng0608/stock-lab/issues/1003#issuecomment-7107953147)）。程式在 [`app.theme_clusters`](../../backend/app/theme_clusters.py)（分群）與 [`worker.theme_discovery`](../../backend/worker/theme_discovery.py)（提案），候選題材的寫法與核對見 [INDUSTRY_CLASSIFICATION §7](../INDUSTRY_CLASSIFICATION.md#73-候選題材)。

- **分群**（`theme_cluster_v1`）：TAIEX 最近 41 個交易日為窗口，`stock`／`ipo` 每天都要有正的 `adj_close`。篩選：20 日均量 ≥ 1,000 張、20 日報酬減 TAIEX ≥ 10%、近 5 日成交金額（`turnover`，沒有時收盤 × 量）平均 ÷ 前 20 日平均 ≥ 1.3。入選的股票以近 40 日每日超額報酬的相關係數做平均連結法分群，平均相關 ≥ 0.45 才合併，至少 3 檔才算一群；門檻是 `ClusterConfig`，每次寫進 `config_json`。
- **存檔**：`theme_cluster_runs` 每個交易日與版本一列（入選數、群數、門檻），`theme_cluster_members` 每檔一列（群號、群大小、群內平均相關、這檔與群內其他成員的平均相關、20 日超額、成交金額比、20 日均量）。同一天重跑整份換掉，結果相同。
- **送 AI 的群**：至少 3 檔，而且沒有一個現有題材（active 的 `theme`）或已寫過的候選題材佔群內超過一半。每群一次 `claude -p`（`sonnet`，提示 `theme_discovery_v1`，用使用者的訂閱登入、不帶工具），每個台北日最多 3 次（`DAILY_CALL_LIMIT`，跨 run 合計）；超過的群記 `daily_call_limit` 不送。每群最多送 20 檔，每檔附 MOPS 公司基本資料的「主要經營業務」（程式抓，間隔 3 秒）與近 7 天點名它的新聞標題。
- **記錄**：`run_type=theme_discovery` 的 ingestion run，`metadata_json` 記 `prompt_version`、`prompt_sha256`、`model`、`calls`、每群的結果（`written`、`not_theme`、`rejected` 與原因、`failed`）、核對沒過的成員與錯誤、token 用量；提示與回應存 raw。每晚的呼叫次數看 `calls`。
- **耗時上限**：每次 `claude -p` 最多 300 秒（`news_llm.CALL_TIMEOUT_SECONDS`），每群抓 MOPS 最多約 60 秒（20 頁、間隔 3 秒，每頁逾時 30 秒時更久），所以一晚最壞約 3 × (300 + 60) 秒 ≈ 18 分鐘，加上每頁逾時的最壞情況約 48 分鐘；分群本身在正式副本上 4～5 秒。它排在 candidate_notes 之後，不拖到今日名單與候選說明。daily 被上限停掉時，留在 `running` 的 theme_discovery run 會在下一次送 AI 前、超過 2.5 小時時記成 `failed`（abandoned），已用的呼叫照算。
- **限制**：AI 判成「不是題材」（例如防禦股輪動）或被拒的群不會被記住：那群隔天還在時會再送一次，吃掉當晚的呼叫，排在第 4 群以後的群可能一直送不到。只有寫成候選題材的群，之後才因已知佔比超過一半而不再送。
- **重放**：`python -m worker.cli theme-discovery --date YYYY-MM-DD --no-ai` 只重算並存那天的分群，不呼叫 AI（[CLI](CLI.md#現有-worker-cli)）。不加 `--no-ai` 時照 daily 的規則送 AI，候選題材的成員從那天生效，所以不要拿它補過去的日期。

## 重跑與回補

- **手動重跑**：見 [daily／news 工作的註冊與管理](platform/windows.md#dailynews-工作的註冊與管理)「不經排程執行一次」，或直接 `python -m worker.cli daily --date YYYY-MM-DD`。已完成的日期加 `-Force`／`--force` 才會再跑各步驟。
- **漏日補抓**：每次 daily 在 collect 目標日前跑 catchup：從目標日前一天往回取最近 5 個不是確定休市的週間日（確定休市＝該日的 daily run 記過 `non_trading_day`，或 collect 的 no-data 是在該台北日結束後才取得；只有當天一次 no-data、23:00 沒再確認的 `non_trading_unconfirmed` 日仍列入補抓，避免誤報的休市永遠補不回），最多回看 15 個週間日（「確定休市」與回補目標同一條規則，見[回補目標與確定休市日](../DATA_SOURCES.md#回補目標與確定休市日)）；其中沒有 collect success（含 TAIEX）的日期，由舊到新以回補的單日路徑（`pipeline.collect(日期, adapter=OfficialMarketDataAdapter(snapshot_feeds=False))`，只抓日期範圍的官方資料，不抓當日快照）補抓；歷史路徑不查 MOPS 快照，只查該日的 MOPS 日期清單（[重大訊息日期查詢](../DATA_SOURCES.md#重大訊息日期查詢)）；清單核實了該日就以它為覆蓋，否則重抓已有 snapshot collect 的日期時沿用該 request 已存的 `event_coverage` 與 `mops_events`／`mops_fundamentals` 資料品質列，不退成歷史預設。補過的日期之後不再抓；補抓失敗的日期下一次 daily 再試，超出 5 個交易日窗口就不再自動補，看門狗會在失敗當晚留言，改用下面的手動回補。catchup 只補 collect，不補跑過去日期的 analyze／evaluate／candidates；指標由當日 indicators 步驟依[指標規則](CLI.md#現有-worker-cli)處理，補到的日線影響最後一列以外時跑 `indicators --rebuild`。
- **主檔外的行情列**：官方行情表裡的普通股代號（4 位數、非 0 或 91 開頭）與 ETF 代號（`00` 開頭、4～6 碼，最後可帶一個大寫字母；#393），即使不在當天的官方清單，也照樣寫入 DB 中同交易所、同代號的既有標的（例如已下市或已轉市的舊標的）。DB 沒有該標的時不建立，記一列 `data_quality`（`entity_type=unmatched_bar`，`entity_key=交易所:代號`，`as_of_date` 為 collect 目標日，checks 列交易日、來源與 raw id）與 run metadata 的 `unmatched_bars`，並加一則 notice；collect 狀態不變。這類代號的歷史可用 `instruments repair --include-delisted` 補回（[現有 worker CLI](CLI.md#現有-worker-cli)）。
- **標的晚建立時補寫日線**（#388）：新上市股票的清單常比首日行情晚一天，首日先被記成 `unmatched_bar`。之後每次 collect 在寫完當日行情與狀態同步後，檢查還沒補完的 `unmatched_bar` 列；代號已有標的時，依該列記的 raw id（新的先）讀已存的行情 raw，核對 SHA-256 並以 collect 相同的解析寫入該日日線。值、來源、資料日期與 `raw_payload_id` 都取自那份 raw，不重新抓取；已存的日線不改。該列 checks 加 `backfill`（寫入的日期與 raw id、已有日線的日期、讀不到的日期與原因），全部日期都有日線時狀態改為 `complete`；raw 找不到、內容與 SHA-256 不符、解析出錯時不補值，狀態維持 `missing`（部分補到為 `partial`）、`missing_fields` 為 `raw_payload`，下次 collect 再試；這類列每次 collect 都會重讀它記的 raw。代號仍沒有標的的列不動。補寫過日線的日期（含先前已補完、狀態 `complete` 的列）沒有籌碼列時，同一次也從當日已存的官方法人與融資 raw（TWSE T86、MI_MARGN；TPEx 三大法人、融資餘額）補該標的的籌碼列（#415）。每份 capture 核對 SHA-256 與回報日期後以 collect 相同的解析讀取；每組由當日最新一份「有個股列或讀不出來」的 capture 決定（#387 以較晚的為準），沒有個股列的（如 18:30 還沒公布的 MI_MARGN）與回報日期不是當日的跳過。決定的那份有該代號就取它的值，沒有就是該組沒有這檔；那份讀不出來（檔案不在、與 SHA-256 不符、解析出錯），或該組沒有一份有個股列的 capture 時，該組無法判定，舊的 capture 不拿來替代。兩組都判定了才寫：有值的組寫入，法人與融資各自記 source、raw、資料日與收集時間（#395）；兩組都沒有這檔就不寫。已存的籌碼列不改。結果記在該列 `backfill.chips`（`written` 附兩組 raw id、`no_row`、`existing`），記過的日期之後不再讀 raw；有一組無法判定時整個日期不寫也不記，回傳列在 `chips_pending`（附該組與讀不出來的 raw id、原因），下次再試。回傳另有 `chips_written`、`chips_checked`。run metadata 與回傳記 `unmatched_backfill`（`status` 為 `success` 或 `failed`），有補寫時加一則 notice。補寫本身出錯時只撤回補寫的寫入：collect 狀態與當日行情不受影響，`unmatched_backfill` 記 `failed` 與錯誤並加一則 notice，列維持未補。補寫日期之後的技術指標由 daily 的 indicators 步驟重寫：該標的最後一列的 `bar_count` 變了，整檔重算。不跑 daily 時用 `instruments backfill-unmatched --apply` 再跑 `indicators`（[現有 worker CLI](CLI.md#現有-worker-cli)）。
- **新上市期間遇到上市日被改**（[#846](https://github.com/YiCheng0608/stock-lab/issues/846)、[#848](https://github.com/YiCheng0608/stock-lab/issues/848)）：新上市觀察的成員期間從觀測日開到「上市日＋60 天」。官方名單之後給的上市日變了（2026-11-17～11-19 TPEx 6874 的 `DateOfListing` 是 `20221214` → `20261005` → `20221214`），已開的期間結束日就和新算出的對不上（`worker.pipeline._nonindustry_observations`）：
  - 只有上市日和這次 collect 寫入前 `instruments.listing_date` 的值不同時，才當成官方改了上市日。上市日沒變、期間結束日卻對不上（舊版寫壞或手改的列），照樣讓 collect 失敗；寫入前沒有上市日（`NULL`）而有開著的期間時也一樣。
  - 上市日只由當日的 snapshot collect 採用：歷史路徑（上面的漏日補抓、手動回補，`snapshot_feeds=False`）帶的是今天的名單，已有上市日的標的不改，只補空值（`worker.pipeline.get_or_create_instrument`）。所以 daily 先補抓前幾天、再 collect 當日時，當日的 collect 仍看得出上市日改了。
  - 新上市日算出來觀測日不在窗口內：已開的期間收在觀測日前一天，之前的成員日不改寫，`action` 是 `closed_listing_date_revised`。
  - 還在窗口內：不切段，同一段期間的結束日改成新的「上市日＋60 天」，開始日不動，`action` 是 `expiry_listing_date_revised`。兩個上市日每天交替時，期間始終只有一段，只有結束日跟著最新的官方值。
  - run metadata 的新上市 receipt 記 `listing_date_revision`：前一次採用的上市日（`previous_listing_date`）、原期間的起訖，以及收到哪天（`closed_valid_to`）或新的結束日（`revised_valid_to`）。
  - 期間收掉之後，今天的上市日又落在窗口內、算出的結束日跟收掉那段不同：不重開、不改舊期間，collect 不失敗。
    - 這包含三種情況，程式不分：官方來回改（6874 再改回 `20261005` 這種）、上市日沒變但收掉的期間被手改或寫壞、真的重新上市（代號重用、新的上市日）。三種都只記錄，不重開；要不要人工重開，看記下的上市日到 Issue 決定。
    - receipt 的 `status` 是 `unresolved_closed_history_conflict`，`closed_history` 記收掉那段的起訖與這次 collect 寫入前的上市日（`previous_listing_date`），新上市結果是 `partial`。
    - collect 加一則非核心 warning（不讓 collect 變 `partial`）：`newlisting membership not reopened: TPEx 6874: listing date 2026-10-05 (before this collect 2022-12-14) ends 2026-12-04, period closed on 2026-11-18`。
    - 寫一列 data_quality：`entity_type` `newlisting_membership`、`entity_key` `TPEx:6874`、`as_of_date` 是觀測日（capture 的台北日期，不是 score_date）、`status` `conflict`、`missing_fields` `["group_membership"]`、`checks` 是該筆 receipt。官方一直給這個值就每天照樣記。
    - 去哪裡看：warning 在 collect run 的 `metadata_json.noncore_warnings` 與 daily 的 `schedule_runs.summary_json.noncore_warnings`（`python -m worker.cli schedule-runs --date YYYY-MM-DD`）；data_quality 列用 `GET /api/data-quality?entity_type=newlisting_membership` 查。看門狗與 `tools/ops/data_check.py` 不讀這兩樣，不會自動留言。
  - 同一次 collect 有兩筆紀錄對到同一個標的：算出來群組和結束日都一樣，第二筆的 `action` 記 `duplicate_record`、不再寫一段；不一樣就讓 collect 失敗（`conflicting newlisting records for one instrument`）。
  - 照樣讓 collect 失敗的：期間在觀測日當天才開（同一天改了兩次）、群組或來源交易所對不上、期間重疊、倒置或在未來、ETF 的上市日被改。新上市與 ETF 成員期間的錯誤訊息最後都帶交易所與代號（例如 `: TPEx 6874`），從 daily log 的 collect `error` 就看得出是哪一檔，再到 Issue 決定怎麼處理。
- **冪等**：collect 對同一 request 已有 `success` 時直接重用、不發請求。重新擷取時：
  - **日線與融資**：既有列只補空欄，不覆寫已存的非空值，不一致的值保留原值，件數記在該 collect run metadata 的 `value_conflicts`、前 50 筆在 `value_conflict_samples`。只補空欄時該列的 `raw_payload_id`、source、data_as_of、collected_at 不變（仍指向原值的 capture），補了哪些欄位與新 capture 的 raw id 記在 `value_fill_groups`（依表、交易所、日期、欄位、raw id 分組列代號，同一 request 的多次執行累加）。
  - **籌碼列的兩組來源**（[#395](https://github.com/YiCheng0608/stock-lab/issues/395)）：法人與融資各自記來源、raw、資料日與收集時間（[DATA_SOURCES 籌碼來源](../DATA_SOURCES.md#籌碼來源)），上一條的「該列 provenance」對籌碼列是指那一組的。列還沒有某一組時（例如 #466 以前 18:30 的 collect 只有法人檔，21:30 才有融資），那一組改指向帶來它的 capture，不算補空欄，不記 `value_fill_groups`；那一組已有來源時補其中的空欄才算補空欄，`value_fill_groups` 記的是那一組 capture 的 raw id（融資記融資檔，不是法人檔）。
  - **三大法人**（籌碼列的 `foreign_buy`、`trust_buy`、`dealer_buy`）：交易所 18:30 公布後會更正，例如 2313 在 2026-10-19 的投信 18:30 是 −162,968 股、21:30 更正為 1,133,032 股（[#387](https://github.com/YiCheng0608/stock-lab/issues/387)）。新 capture 與既存列同一交易日、同一份官方法人檔（上市 T86、上櫃 `insti/dailyTrade` 或當日 OpenAPI `tpex_3insti_daily_trading`，即兩者的法人組來源相同），且擷取時間（`raw_payloads.collected_at`）嚴格晚於該列法人組目前指向的 capture 時，不同的值改成新值，該列的法人組改指向新 capture，融資組不變；值相同時不改列。舊值記在 collect run metadata 的 `value_revision_rows`：每列一筆，含交易所、代號、交易日、各欄舊值與新值、舊與新的 raw id；同一 request 的多次執行累加、不截斷。本次執行更正的列數在 `value_revisions`。擷取時間相同或較早的 capture 照日線與融資的規則處理，例如重跑舊日期時讀到較早的 capture、或 capture 順序顛倒。法人組沒有 raw 指向時，以它的收集時間當擷取時間。
  - **23:00 重抓三大法人檔**（[#396](https://github.com/YiCheng0608/stock-lab/issues/396)）：目標日已有 daily `success` 時，下一次 daily（排程是 23:00，#466 以前是 21:30）不重跑 collect，只呼叫 `worker.institutional_refetch.refetch_institutional(目標日)`：上市 T86、上櫃 `insti/dailyTrade` 各請求一次（daily 每個交易日多 2 個請求），raw 存在 `run_type=institutional_refetch`、`request_key=institutional_refetch:<日期>` 的 ingestion run 下，再以上一點的規則套用到既有的籌碼列（不新增列，融資欄與融資組來源不動）。run 的 `records` 與 metadata 的 `revised_rows` 是更正的列數，`unchanged_rows` 是值相同未改的列數，`value_revision_rows` 列每列舊值與新值，`exchanges` 記各交易所的結果與 raw id。兩份都成功是 `success`，同一日期之後的 daily 直接重用、不再請求；一份失敗是 `partial`、兩份失敗是 `failed`，成功的那份照樣寫入，下一次 daily 兩份都再抓一次。重抓的 capture 之後也會被 `chips revise` 依擷取時間重放。只更正籌碼列，不重算當日的訊號、族群與候選，下一個交易日的 daily 讀到更正後的值。
  - **force**：`collect(force=True)` 覆寫所有欄位（含較早的 capture），覆寫時指向新 capture；籌碼列只移動值有改變的那一組。
  - **#387 以前的初值**：以 [`chips revise`](CLI.md#現有-worker-cli) 依已存的 raw 套用三大法人規則更正。
  - **0021 以前的籌碼列**：以 [`chips provenance`](CLI.md#現有-worker-cli) 依已存的 raw 與 `value_fill_groups` 補寫兩組來源。
- **回補**：`python -m worker.cli backfill --start-date <起> --end-date <迄> --scope market`。中斷後以相同起訖重跑即從各段 manifest 續做；輸出列出每段 run id、`partial_dates`／`failed_dates`（缺日，不補值）與 `skipped_non_trading_dates`（官方無交易）。每段 run 的狀態：有 `failed` 或 `partial` 日是 `partial`；有 `failed` 日而且沒有任何完成或 `partial` 的日子是 `failed`；其餘（只有完成日與休市日）是 `success`。休市日（`skipped_non_trading_dates`）是官方明確回「沒有資料」的日子（例如 `MI_INDEX` 的「沒有符合條件的資料」），不是查交易日曆，請求失敗不會記成休市；它不讓段變 `partial`，也不讓全部失敗的段變成 `partial`。run 的狀態、`coverage_manifest_summary.status` 與 CLI 輸出的每段 `status` 相同（[#772](https://github.com/YiCheng0608/stock-lab/issues/772) 以前休市日會讓 run 變 `partial`，summary 也沒有 `failed`）。已 `success` 且達到目標的段，以相同起訖重跑會直接回傳、不發請求，各日的 collect run 已 `success` 時也一樣；要重抓加 `--force`。每段的 `target_met` 看「已驗證交易日 ≥ `min(65, 平日數 − 確定休市日)`」（[回補目標與確定休市日](../DATA_SOURCES.md#回補目標與確定休市日)）；規則改版前寫下的 run，以相同起訖重跑一次就會更新：已完成與已確認休市的日期都會重用、不發請求（#479）。回補或更正舊日線後跑 `python -m worker.cli indicators --rebuild` 重算指標。
- **限流**：`fetch_json` 對同一官方主機保持最小間隔（`sources.OFFICIAL_HOST_MIN_INTERVAL_SECONDS`：`www.twse.com.tw` 2.5 秒、MOPS 與期交所網站 3 秒，其餘官方主機 1 秒），另有 429／5xx／暫時性 307 的有界重試。手動的回補命令對每個 host 至少 3 秒（[CLI](CLI.md#現有-worker-cli)「回補命令的請求間隔」，#692）；daily 與 catchup 照上面的間隔。
- **不要並行回補**：回補與 daily 都長時間寫 DB，analyze 也依 collect run 決定分析日；回補、回測期間停用 daily：scheduler 容器不必停：`backfill`、`backtest` 起跑時自己開[維護模式](#維護模式)（daily 與 news 不跑，看門狗與 monitor 照常），結束時自己關，作業死掉由 serve 在心跳逾時後解除（工作排程器的做法見 [daily／news 工作的註冊與管理](platform/windows.md#dailynews-工作的註冊與管理)）。

### evaluate 的增量規則與全量重算

daily 的 evaluate 步驟（`pipeline.evaluate`）照 [Tracking 口徑](../spec/tracking.md#tracking-與-technical-backtest-口徑)第 7 點選出還在追蹤的 `analysis-*` 訊號。其中「已結算」的訊號保留原列，不重算，狀態也不動；其他訊號照舊重算（[#841](https://github.com/YiCheng0608/stock-lab/issues/841)）。

- **已結算**：下面四條全部成立（`pipeline._settled_signal_ids`），任何一條不成立就重算。
  - **R1 視窗已滿**：已有 20 筆 evaluation。
  - **R2 沒有除權息**：訊號日到最後一筆 evaluation 之間沒有 `corporate_actions` 列。有就重算，不比較因子。
  - **R3 沒有相關停牌公告**：沒有開始日在最後一筆 evaluation 以前、結束日在訊號日以後的 suspension 事件。結束日缺漏或無法解析的事件也算相關。
  - **R4 重算結果相同**：用現在的輸入在記憶體裡重算，結果要和存的逐欄相同，什麼都不寫。
    - 輸入：訊號日之後的前 20 根日線、這些日子的籌碼、族群、前 20 日成交量，以及訊號現在的價位與狀態。
    - 比對對象：20 列 evaluation、T+5／T+20 settlement（含 `tracking_rules`），以及訊號的狀態、資料品質、成交日與成交價。
    - 重算和真正追蹤用同一段程式（`_tracking_outcome`、`_apply_signal_outcome`）。R2、R3 成立時價格因子是 1、沒有停牌缺口，所以不用再讀除權息與事件。
    - 看得到的變動：日線被更正、補插或刪掉，籌碼晚到，族群改變，前 20 日量被更正，規則版本改變。重跑舊日期的 analyze 改寫了訊號的價位、狀態或資料品質，也看得到。追蹤程式改了但沒升規則版本，同樣看得到。
- **跳過的是哪些訊號**：視窗還沒滿的訊號每天多一根日線，一定要重算。這些是絕大多數：2026-11-18 的副本有 75,918 個被選中的訊號，其中 133 個已結算。已結算的訊號是成交後停在 `target_1_hit`、`invalidated`、`incomparable` 或 `active`、永遠不離開清單的那一群，只有它們會隨累積的訊號數一直變多。
- **驗證也要時間**：已結算的訊號每晚都重新驗證一次，這段時間也會跟著它們的數量成長。回傳的 `settled_check_seconds` 記這段時間，部署後看它長不長。
- **孤兒 evaluation**：日線被刪掉或改日期後，舊日期的 evaluation 不會刪（重算只寫現在的 20 根）。這種訊號的 evaluation 超過 20 筆，R1 永遠不成立，所以每晚照樣重算。結果仍然正確，只是省不到時間。
- **每個訊號一次的讀取**：重算的訊號以前每一根日線各查一次族群分數、籌碼、停牌事件與既有的 evaluation，現在每個訊號各查一次。族群確認在同一次 evaluate 內按（標的、訊號日）共用：這個步驟不寫族群資料。結果與逐根查詢相同。
- **全量重算**：`python -m worker.cli evaluate --force`（`evaluate(force=True)`）不看 R1～R4，所有被選中的訊號都重算。`backtest-*` 訊號與 v1 完整視窗的保留規則（[#444](https://github.com/YiCheng0608/stock-lab/issues/444)）不受影響。R4 讀不到的情況要跑一次全量重算：
  - 回補或手動更正了上面列的輸入以外的資料。
  - 改了 R4 不經過的讀取程式，例如 `_tracking_inputs` 的除權息因子、停牌缺口或日線選取。
- **回傳**：
  - `signals_checked`：被選中的訊號數。
  - `signals_skipped`：其中已結算、沒重算的數量。
  - `settled_check_seconds`：已結算判斷花的秒數（`--force` 時是 0）。
  - `force`：這次有沒有全量重算。
  - `evaluations_written`／`settlements_written`：只算重算的訊號，是重算的列數。值沒變的列 SQLAlchemy 不會發 UPDATE，所以實際寫入的列比這少。

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

- **作業自己持有**：`backfill`、`backtest`、`events backfill`、`fundamentals backfill`、`revenue backfill`、`instruments repair --apply`、`strategy-lists backfill`（#1021） 起跑時自己開維護模式，正常結束、例外或 SIGTERM（`docker stop`）都在 `finally` 關掉（[`MaintenanceHold`](../../backend/worker/job.py)）。直接照平常跑，不必先停 scheduler，例如 `docker compose -p <P> exec scheduler python -m worker.cli backtest --start-date … --end-date …`；`exec scheduler` 或 `compose run api` 都一樣，標記檔在同一個 volume。起跑時 stderr 會提示：**預估會跨過 21:30 時，請改在 23:30 後開始**（21:30 的 daily 會被跳過，要等解除才補跑）。
- **標記檔**：`/data/locks/maintenance`（JSON）。作業持有時記 owner（命令、容器 hostname、PID、token）、開始時間與心跳時間，作業期間每 60 秒更新心跳。取得、心跳、解除、逾時與手動 `on`／`off` 都在 `/data/locks/maintenance.lock` 的 flock 下進行：兩個作業同時起跑只有一個取得，心跳也不會讓 serve 剛解除的標記檔復活。
- **拒絕起跑**（exit 75，stderr 寫出原因）：有開啟前就在跑的 daily／news／us job 或開盤前檢查（`running_jobs`，preopen 自 #755 起列入；等它結束再跑），維護模式由另一個仍有心跳的作業持有（一次只跑一個回補或回測），或維護模式是手動開的（部署中：`deploy.sh` 會在作業還在跑時把它關掉，所以等部署完成再跑）。其餘情況自動開，不拒絕。
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
- **serve 不寫 DB 的範圍**：維護模式中 serve 啟動的程序都不寫 `stock.db`：daily、news、us 不啟動 worker；preopen 開始時與寫入前各查一次維護標記，有就記 `skipped reason=maintenance`、不寫（#755）；看門狗以唯讀連線查 DB（`mode=ro`、`query_only`）；monitor 只讀日誌、寫佇列目錄；notify 與 intraday（#801）只讀 DB；serve 自己的補跑判定也是唯讀。api 照常服務，使用者的寫入（例如追蹤計畫）不受影響，與停 scheduler 相同。scheduler 跑的是 #468 以前的 image（v1.2.3 以前）時沒有維護模式，仍要 `stop scheduler`。
- 不讓回補與 daily 並行。

## 限制

- 三大法人的更正只在之後還有 capture 時才會寫入（[重跑與回補的冪等](#重跑與回補)）：21:30 的 collect 已 `success` 時由 23:00 重抓一次當日法人檔（#466），23:00 之後的更正收不到；23:00 那次沒跑（serve 停了、`low_memory`）時也收不到，過後要收進更正就對該日期手動跑一次 `daily --date`（第一次會重抓）。21:30 失敗、23:00 重跑才成功的日子沒有重抓：23:00 的 collect 本身已是當晚最晚的法人檔。重抓不看時間：21:30 `success` 之後、23:00 之前手動跑 daily，會用掉當天唯一一次重抓，23:00 就直接重用、不再請求，那段時間之後的更正收不到。23:00 更正的值不會改寫當日已算好的訊號、族群與候選。
- universe 取自今日的官方清單。回補期間已下市或轉市的股票與 ETF，DB 已有標的時照樣寫入歷史；沒有標的時只記 `unmatched_bar`，需要 `instruments repair --include-delisted` 才會建標的並補歷史（[重跑與回補](#重跑與回補)）。
- 標的狀態只依官方清單與已存行情表判定，沒有接終止上市、停牌公告。仍在清單內、但 60 個交易日沒有行情列的推定為 `dormant`；未滿 60 個交易日的維持 `active`，日線停在最後交易日（[DATA_SOURCES 標的狀態同步](../DATA_SOURCES.md#標的狀態同步)、[#212](https://github.com/YiCheng0608/stock-lab/issues/212)）。
- 歷史回補不保存當日產業觀測與 MOPS／除權息快照；這些只由 daily 記錄當天。
- 休市判定依官方 no-data 回應；來源暫時失敗的日期記為缺日，不推定休市。
- 全市場 analyze＋evaluate 單次約 4～6 分鐘、峰值約 0.2 GB，連同 candidates／indicators 約 6 分鐘、0.3 GB（2026-10-18，正式 DB 副本：2,409 檔、2024-09-30～2026-10-16 共 496 個交易日；[#184](https://github.com/YiCheng0608/stock-lab/issues/184)）。analyze 每 200 檔 commit 一次 features、group scores 寫完再 commit，每次持有寫入鎖約 2 秒內，與 news 同時執行不會等到 30 秒 busy timeout；analyze 中途失敗時已 commit 的 features／group scores 都是由日線重算的值，重跑會寫出相同結果。group scores 先於 signals commit，所以 analyze 進行中（約 1～2 分鐘）或中途失敗時，API 可能看到新日期族群分數與舊日期訊號並存，重跑 analyze 即一致。
- daily 的 evaluate 每 2,000 個訊號 commit 一次（[Tracking 口徑](../spec/tracking.md#tracking-與-technical-backtest-口徑)第 7 點，[#640](https://github.com/YiCheng0608/stock-lab/issues/640)），每批持有的物件數固定；隨追蹤中的訊號數成長的只有開頭取的 id 清單（6 萬多個整數）與耗時。2026-11-11 正式 DB 副本要重算 63,395 個訊號（大多是 `observation`，每個交易日約 3,900 個，視窗滿 20 根才結束，所以約是最近 20 個交易日的量）：2g 上限下 994 秒、cgroup anon 峰值 289 MB；1g 上限下 953 秒、anon 峰值 280 MB、`memory.peak` 350 MB（evaluation 與 settlement 全部重寫的情況）。#640 以前整個 evaluate 是一個 transaction，訊號與寫出的 evaluation／settlement 都留在 session 直到結束：同一副本在 4g 上限下 18 分鐘被 OOM 結束，正式 scheduler 11/10、11/11 在 2g 上限被結束。
- [#841](https://github.com/YiCheng0608/stock-lab/issues/841) 改成每個訊號只讀一次輸入、已結算的訊號跳過（[evaluate 的增量規則與全量重算](#evaluate-的增量規則與全量重算)）。2026-11-18 正式 DB 副本，75,918 個被選中的訊號，2g 上限，每次各用一份獨立副本跑同一天：
  - #841 以前（master 8e5d593a）：1,650 秒，行程 RSS 峰值 324 MiB，`memory.peak` 964 MiB。
  - 增量（a3741761，舊版規則）：308 秒，跳過 133 個，RSS 峰值 324 MiB，`memory.peak` 1,395 MiB。
  - `--force`（a3741761）：297 秒，RSS 峰值 323 MiB，`memory.peak` 1,493 MiB。
  - 增量（28343815，R1～R4）：369 秒，跳過 133 個，其中已結算判斷 1.8 秒（0.5%），RSS 峰值 321 MiB，`memory.peak` 1,475 MiB。比 a3741761 多約 60 秒，不在已結算判斷；兩者在不同時段量，原因沒有再拆。
  - 每一份的 `signal_evaluations`、`signal_settlements`、`signals` 逐列相同。`memory.peak` 含 page cache，行程本身的峰值都約 321～324 MiB。
  - 增量與 `--force` 的耗時差不多：同一天跳過的只有 0.2%，變快主要來自讀取合併。增量規則讓成交後停在清單裡的訊號不再每晚重算，這一群會一直累積。

## scheduler 容器的排程（serve）

`python -m worker.cli serve`（[`backend/worker/serve.py`](../../backend/worker/serve.py)，#336）是 scheduler 容器的常駐命令，在[後端 image](SETUP.md#工作目錄環境與啟停) 內取代工作排程器：APScheduler 依台北時間啟動與 [daily／news 工作的註冊與管理](platform/windows.md#dailynews-工作的註冊與管理) 註冊相同的命令，每次一個子程序。compose 設定見 [Docker compose](SETUP.md#docker-compose)（#335），`claude`／`gh` 的認證見 [容器內的 claude 與 gh 認證（.env）](SETUP.md#容器內的-claude-與-gh-認證env)（#337）；正式切換（#342）已完成，工作排程器停用、不再當回退（[Windows 工作排程器](platform/windows.md)）。

| 工作 | 觸發（預設） | 命令 |
| --- | --- | --- |
| daily | 週一至週五台北 21:30、23:00（`--daily-times`，#466） | `worker.cli job daily --trigger scheduler --data-dir <data> --log-dir <data>/logs --min-free-memory-gb 2 [--claude-cli <claude>] --time-limit-minutes 80`（`--daily-time-limit-minutes`） |
| news | 每 2 小時整點（`--news-interval-hours`，1～24 的整數，超出就 exit 2；每台北日從 0 點重新起算，所以不能整除 24 的值如 5 在午夜前的間隔較短，24 是每日 0 點一次，#368） | 同上換成 `job news`、`--min-free-memory-gb 1`；`--skip-news-llm`（沒給時看 env file 的 `STOCK_SKIP_NEWS_LLM`）交給 job |
| us（美股四檔，#568、#681） | 週二至週六台北 07:30、08:30、09:30（`--us-times`） | 同 daily 換成 `job us`、`--min-free-memory-gb 2`（`--us-min-free-memory-gb`，預設同 daily）；`--us-time-limit-minutes` 有給才帶，否則用 job 的 20 分。job 跑 `worker.cli index-bars us-collect --trigger scheduler`（[CLI](CLI.md#現有-worker-cli)、[美股指數](../DATA_SOURCES.md#美股指數)） |
| preopen（開盤前檢查，#755） | 週一至週五台北 08:20 | `worker.cli preopen --trigger scheduler --log-dir <data>/logs`（[`backend/worker/preopen.py`](../../backend/worker/preopen.py)）；不經 job：自己的鎖 `<data>/locks/preopen.lock`、日誌 `<data>/logs/preopen-YYYYMMDD.log`，上限 15 分鐘（等 news 最多 10 分鐘加檢查本身），第二道防線再加 5 分鐘 |
| notify（每日 Telegram 通知，#728） | 週一至週五台北 08:45 | `worker.cli notify --send --trigger scheduler --log-dir <data>/logs`（[`backend/worker/notify.py`](../../backend/worker/notify.py)）；不經 job：自己的鎖 `<data>/locks/notify.lock`、日誌 `<data>/logs/notify-YYYYMMDD.log`，上限 5 分鐘，第二道防線再加 5 分鐘 |
| intraday（盤中即時通知，#801） | 週一至週五台北 08:59，13:30 那輪之後自己結束（13:31 前） | `worker.cli intraday --send --trigger scheduler --log-dir <data>/logs`（[`backend/worker/intraday.py`](../../backend/worker/intraday.py)、富果 adapter [`backend/worker/fugle.py`](../../backend/worker/fugle.py)）；不經 job：自己的鎖 `<data>/locks/intraday.lock`、日誌 `<data>/logs/intraday-YYYYMMDD.log`、當天事件 `<data>/logs/intraday-YYYYMMDD.jsonl`，上限 280 分鐘，第二道防線再加 5 分鐘；失敗處理見下面的 intraday 一節 |
| 看門狗 | 每小時 :15、:45（`--watchdog-minutes`） | `bash tools/ops/watchdog.sh --data-dir <data> --python <serve 的 python>`，`--watchdog-dry-run` 時加 `--dry-run`；monitor 開著時加 `--monitor-dir <monitor 目錄>` |
| 事件 monitor | 每分鐘，只在 `--monitor`（預設 `STOCK_MONITOR`，沒設為 `off`）是 `on`／`record-only` 時（#338） | `bash tools/ops/monitor.sh --once --data-dir <data> --queue-dir <--monitor-dir，預設 /coordination> --python <serve 的 python> --orca <--monitor-orca> --waker <--monitor-waker>`，`record-only` 時加 `--record-only`；見 [統籌事件 monitor](MONITOR.md) |

- **daily 的 21:30 與 23:00**（#466）：
  - **21:30** 是當日的 daily 本體（catchup、collect 到 candidate_notes）。#466 以前第一次是 18:30，但融資檔那時還沒公布，10/19～11/04 的交易日 18:30 都是 `partial`（跑 1～2 分鐘就停），正式資料一直是 21:30 那次產出的。
  - **23:00 在 21:30 `success` 之後**：記 `skipped`（`already_complete`），只做一次[法人重抓](#重跑與回補)（上市 T86、上櫃 `insti/dailyTrade` 各 1 個請求），收進交易所較晚的更正；不跑 catchup、collect 與之後的步驟，不查 MOPS。
  - **23:00 在 21:30 沒有 `success` 時**（`partial`、`failed`、`non_trading_unconfirmed`、`skipped`，或 21:30 沒跑）：同一日期完整重跑一次 daily，規則與 21:30 相同。MOPS 的查詢次數：21:30 的 collect 已 `success`（失敗在之後的步驟）時重用那次 collect，不再查；collect 沒有 `success` 時重查目標日的[日期清單](../DATA_SOURCES.md#重大訊息日期查詢) 1 次（覆蓋以 23:00 的查詢時間為截止，#464），再補查 `gap_dates` 仍未回答的週末與連假：21:30 已回答（`verified`／`empty`）的不再查，只有 21:30 查失敗（`partial`）或沒查到的才再查，通常是 0 次。catchup 照常補過去 5 個交易日裡還沒 collect `success` 的日期（各自查該日的 MOPS 清單），與 21:30 相同。
  - **單次上限 80 分鐘**（#466 決定 [6638008818](https://github.com/YiCheng0608/stock-lab/issues/466#issuecomment-6638008818)）：serve 傳給 job 的 `--time-limit-minutes`（`--daily-time-limit-minutes`）。21:30 那次卡住時 22:50 被 job 結束（job 自己沒結束時，第二道防線在 22:55 結束它），23:00 拿到鎖、把它記 abandoned 並重跑；否則 23:00 會因鎖被占記 `already_running`，當天不會重試。10/19～11/04 最長的一次 daily 是 19.7 分鐘，80 分約有 4 倍餘裕。手動 `job daily` 仍是 job 預設的 2.5 小時。
  - 看門狗從 23:10 起判定當日 daily，00:30 起再判定前一個交易日一次（[排程看門狗](WATCHDOG.md)）：21:30 失敗而 23:00 還會重試時不提早留言，23:00 的重試卡到午夜後也會報。
- **us 的 07:30、08:30 與 09:30**（#568 決定 [6729065016](https://github.com/YiCheng0608/stock-lab/issues/568#issuecomment-6729065016)；#681 決定 [6869771833](https://github.com/YiCheng0608/stock-lab/issues/681#issuecomment-6869771833)）：
  - 美股收盤是台北 04:00（夏令）或 05:00（冬令），所以週二到週六各抓前一個美股交易日。週日、週一沒有新的美股交易日，不排。
  - **為什麼不是 06:30**（#681 AC-1，[提問 6869756981](https://github.com/YiCheng0608/stock-lab/issues/681#issuecomment-6869756981)）：#568 起 06:30、09:30 兩次，11/10、11/12、11/13、11/14 四個早上 06:30 都還沒有前一晚（D 前一個平日）的收盤，09:30 都有（美東冬令，收盤後 1.5 小時還沒有、4.5 小時內有）。FinMind 文件沒寫更新時間，所以排三次，前兩次在 09:00 開盤前。
  - **07:30、08:30** 開盤前抓前一晚；**09:30** 是保險。每一次在四檔都已存到前一個平日時記 `already_complete`、不發請求，所以一天最多 12 個請求。夏令收盤早一小時，同一組時間只會更早拿到，不用分季切換；`test_worker_serve.py` 用 `America/New_York` 的夏冬令各算一次收盤，鎖住每個時間都在收盤 2 小時後、前兩次在 09:00 前。
  - 三個時間都在 :30，避開每個偶數整點的 news。每個 job 各用自己的檔案鎖（`daily.lock`、`news.lock`、`us.lock`），不共用；靠排程時間錯開。SQLite 是 WAL，連線有 busy_timeout，us 的寫入又小，偶爾重疊也只是等待（#568 review 第 3 點）。
  - 第一次拿到的 D−1 收盤就是定值，之後的重讀只會修訂成交量（#681 AC-1：例如 SPX 11/12 的量在隔天由 31.8 億股改成 46.9 億股，收盤不變），修訂照 `value_revision_rows` 記錄。
  - 前一個平日是美股休市日時，三次都拿不到那一天，畫面標「美股尚未更新」；下一個交易日的列進來時，那天才記成休市，畫面直接變最新，不會出現「美股休市」（[美股指數](../DATA_SOURCES.md#美股指數)，#568 review 第 4 點）。
  - 錯過的日子由下一次自動補上：請求從已存最後一列往前 10 天起，不必另外回補。
  - 記憶體門檻同 daily（2 GB）。被 `low_memory`、`git_busy` 或 `already_running` 擋下時，job 照 daily 的做法讓 worker 記一筆 `skipped` 的 `us_index_collect` run，不發請求；維護模式時只記日誌、不寫 DB。
- **preopen 的 08:20**（#755 決定 [6888598143](https://github.com/YiCheng0608/stock-lab/issues/755#issuecomment-6888598143)）：
  - **內容**：前一個交易日（同 notify：往前第一個週間日，跳過 `trading_calendar_days` 標 `closed` 的日子）那一份今日名單（`app.candidate_runs.read_run`，同 `/api/candidates?date=<該日>`）的每一檔，列出名單產生之後才收到的新聞與檢查當下已判讀好的 AI 方向（[`app.preopen_news`](../../backend/app/preopen_news.py)），寫進 `preopen_news_checks`，每檔一列（0 則也寫）。不另外呼叫 AI，不改分數、排序與門檻。
  - **時間窗**：`news_items.collected_at` 晚於名單的 `candidate_runs.computed_at`（daily 的 candidates 步驟讀完新聞、算完分數後立即寫入，是 daily 讀新聞截止點的近似），而且不晚於檢查時點；發布時間（`display_time`）在名單日台北 00:00 之後、檢查時點以前。只有日期的新聞（`time_precision=date`）看 `event_date`，在名單日到檢查日之間。`status` 不是 `active` 與 `time_consistency=conflict` 的不算（同個股頁）。不用「21:30 以後發布」切的原因：news 是偶數整點跑，daily 讀新聞時 20:00 那輪之後發布的新聞還沒收進來；正式 DB 11/05～11/13 的 `computed_at` 是台北 21:50～22:04，每晚有 10～62 則名單日發布、`computed_at` 之後才收進來的新聞（#755 AC-1 [提問 6888582326](https://github.com/YiCheng0608/stock-lab/issues/755#issuecomment-6888582326)）。
  - **近似的缺口**（#755 review [6889365957](https://github.com/YiCheng0608/stock-lab/pull/758#issuecomment-6889365957)）：news 在抓 feed 之前就決定 `collected_at`（`news_batch` 每個來源一個時間），抓完才 commit。某輪 news 和 daily 的 candidates 步驟重疊時（例如 22:00 那輪剛好在 daily 讀新聞期間），`collected_at` 早於 `computed_at`、commit 卻晚於 daily 的讀取，這些新聞 daily 沒看到，開盤前檢查也不算。只會少算，不影響分數；要精確得在 daily 讀新聞時記下水位（例如 `max(news_items.id)`），另案評估。
  - **同一則轉載只算一次**：同一檔股票的新聞裡，`canonical_key`、`dedupe_cluster_id` 或 `content_hash` 與較早一則相同的不再算（同 `/api/news` 的去重）。
  - **對應**：個股頁新聞列表的規則關聯，`news_items.symbols_json` 有代號或 `交易所:代號`（`api._news_symbol_filter`）。AI 的代號候選不算。
  - **為什麼是 08:20**：08:00 那輪 news（含 news-llm）在 11/05、11/06、11/09、11/10、11/12、11/13 是 25～243 秒，最晚 08:04 結束（AC-1 的量測）；08:20 也避開看門狗的 :15、us 的 08:30 與 notify 的 08:45（`test_worker_serve.py` 檢查不重疊）。
  - **等 news**：開始時 `news.lock` 被占（news 那輪還沒結束）就等它，每 10 秒以 `job.lock_held` 探測一次，最多 10 分鐘；超過就照跑，結果記 `news_running=yes`。探測只拿一瞬間就放掉，不在持有 `news.lock` 時做事，不會擋到下一輪 news。
  - **一天一次**：排程那次發現名單日已有同一份名單（`candidate_run_id` 相同）的列，就記 `skipped reason=already_checked`，所以一天的結果是第一次檢查的結果；名單被重算過（`candidate_run_id` 不同）時覆寫。手動 `--force` 整天刪掉重寫。覆寫時日誌記 `--- overwrite checked_at=<被覆寫的檢查時點> run_id=<…>`。方向存檢查當下的值，之後 AI 補判了也不改。
  - **跳過**：週末或行事曆標 `closed` 記 `skipped reason=non_trading_day`；那天沒有名單記 `no_list`；維護模式記 `maintenance`（會寫 DB，不照 notify 在維護模式中照跑；開始時與寫入前各查一次，等 news 期間開了維護也不寫，記 `maintenance after_wait=yes`）；拿不到鎖記 `already_running`。`--trigger scheduler` 只在台北 08:20～13:30 檢查，其他時刻記 `too_late at=<HH:MM>`（同 notify：主機 08:20 睡著、晚上才醒時不補）。
  - **日誌**：`logs/preopen-YYYYMMDD.log`（執行的台北日），每次追加 `===== <時間> start job=preopen …`、`--- news_lock waited=<秒>s running=<yes|no>`、有新聞的每檔一列 `--- candidate rank=<名次> <交易所:代號> news=<則數> positive=… negative=… mixed=… unknown=… unscored=… ids=<新聞 id>`、`--- result status=<checked|skipped|failed> …`（`checked` 帶 `list_date`、`run_id`、`window_start`、`checked_at`、`candidates`、`with_news`、`news`、`unscored`）與 `===== <時間> end exit=<碼> seconds=<秒>`。保留 90 天。
  - **頁面**：`/api/candidates` 的 `preopen_check` 與每個 item 的 `preopen_news`（[UI_COPY_SPEC §10](../UI_COPY_SPEC.md#10-每日候選)）；只有 `candidate_run_id` 等於頁面那份名單時才是 `checked`，否則 `not_checked`。
  - **失敗怎麼被發現**：看門狗從 09:00 起判定（09:15 那一輪，#760），`preopen_missing`（當天沒有日誌，或 `start` 列比 `end` 列多，兩種留言文字不同）、`preopen_failed`（當天最後一個非 skipped 的結果是 `failed`）與 `preopen_missed`（當天只有 skipped、其中有 `too_late`：排程在 08:20～13:30 之外才跑），每台北日各最多一則，在 #1 留言；其他 skipped 理由不算異常（[排程看門狗](WATCHDOG.md)）。不送 Telegram。
  - **手動**：`worker.cli preopen --dry-run [--date YYYY-MM-DD]` 印出這次會存的結果，不等 news、不寫 DB、不寫日誌；`worker.cli preopen --trigger manual [--force]` 照排程的流程跑一次。
- **notify 的 08:45**（#728 決定 [6881879639](https://github.com/YiCheng0608/stock-lab/issues/728#issuecomment-6881879639)；設定步驟見 [每日 Telegram 通知](SETUP.md#每日-telegram-通知)）：
  - **內容**：先送圖片卡片（#754，使用者選定）：`backend/worker/notify_card.py` 把下面同一份內容照 DESIGN_SYSTEM 盤後終端深色版面畫成一張 PNG（每區一張表：代號名稱、進場、停損、目標；隔夜美股紅漲綠跌），用 image 內的 Chromium（`SCREENSHOT_BROWSER`）在系統暫存目錄畫、畫完即刪、30 秒逾時就殺掉，以 `sendPhoto`（multipart）送出，圖下一行說明「今日名單 <日期>・突破 N、回踩 M」（`parse_mode=HTML`）。畫圖失敗（沒有瀏覽器、非 0 結束、逾時、PNG 是空的）、`sendPhoto` 回不重試的 4xx、或重試後仍失敗，改送下面的文字版。圖與文字版出自同一次讀取，名單、價位與美股的文字逐項相同。文字版是卡片式版面（#742）：`parse_mode=HTML`，標題、分區標題與每檔的代號名稱用粗體（`<b>`），資料裡的文字（股名、原因、來源）先 `html.escape`。前一個交易日（往前第一個週間日，跳過 `trading_calendar_days` 標 `closed` 的日子）那一份今日名單，取自 `app.candidate_view.candidate_list`（同 `/api/candidates?date=<該日>`），最多 20 檔，依 `entry_type` 分「🚀 突破」「↩️ 回踩」兩區（其他型態放最後的「其他」，空的一區不印），區內照 rank；每檔一行代號名稱、一行「進場 X｜停損 Y｜目標 Z」（照今日名單頁的規則進場價或規則進場區，回踩寫「X～Y」；價位不完整的照樣留在該區）；那天沒有名單就寫「無資料（<日期>的名單沒有產生；daily：<當日 schedule_runs 最後一筆狀態>）」，不拿更早的名單頂替。隔夜美股取 `foreign_indices(今天)`（同 `overnight_us`，#681），照今日名單頁的「美股休市」「非最新」「美股尚未更新」判斷，每檔前面標 🔴 漲／🟢 跌／⚪ 平盤（台股慣例），附收盤日與來源名稱（「來源 FinMind」）；缺的一檔寫「無資料（未取得）」、不加符號。名單超過 20 檔、或超過 Telegram 的 4096 字（連標籤與跳脫後的字一起算，emoji 算兩字）從名單尾端（rank 最後）截短時，最後一行寫「另 N 檔見今日名單頁」（N＝名單檔數 − 列出的檔數）。開盤前檢查（#759）：讀同一次 `candidate_list` 的 `preopen_check` 與每檔的 `preopen_news`（`app.preopen_news.list_view` 判定，只有 `candidate_run_id` 等於這份名單的檢查才是 `checked`）。`checked` 時有隔夜新聞的檔標「隔夜新聞 N（可能負向 k）」（同今日名單頁的列標記；沒有可能負向就不寫括號，0 則不標）：圖片卡片在該列名稱與價位下多一行（可能負向的字用下跌色 `--color-down`，該列高 40→54 CSS px），文字版接在代號名稱那一行後面；不是 `checked`（08:45 時 preopen 還沒跑完、失敗，或名單在檢查後重算）就在名單標題下寫一行「開盤前檢查：尚未完成」，不拿前一天的結果代替。沒有名單或 0 檔不寫。notify 不等 preopen、不取 `preopen.lock`。20 檔、每檔都有標記時卡片高 1498～1578 CSS px（一區或兩區），PNG 2996～3156 px，超過 Telegram 保留的最長邊 2560，會縮成約 923×2560～876×2560（#759 AC-2）。不加研究狀態或說明文字（[#1 6881297699](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6881297699)）。
  - **判斷與送出**：
    - `--trigger scheduler` 只在台北 08:45～13:30 送，其他時刻記 `skipped reason=too_late at=<HH:MM>`、exit 0。這是 job 自己的規則，不靠 APScheduler：主機 08:45 睡著、晚上才醒時，APScheduler 會補跑錯過的觸發，job 就在這裡擋下，不在收盤後送早上的名單（#728 review [6882303076](https://github.com/YiCheng0608/stock-lab/pull/735#issuecomment-6882303076) 第 1 點）。手動（`--trigger manual`）任何時刻都送。這一項排在交易日判斷之後：休市日照舊記 `non_trading_day`，所以 `too_late` 只出現在錯過的交易日，看門狗以 `notify_missed` 回報（review [6882535482](https://github.com/YiCheng0608/stock-lab/pull/735#issuecomment-6882535482)）。
    - 今天是週末或行事曆標 `closed` 時記 `skipped reason=non_trading_day`；行事曆缺年份或 unknown 時照週間日送。
    - `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID` 有一個是空的記 `not_configured`，exit 0，不算失敗。
    - chat id 不是正整數（群組、頻道）記 `failed reason=chat_not_private`、不送。
    - 送出用 Bot API `sendPhoto`（每次逾時 30 秒）、退回時 `sendMessage`（每次逾時 20 秒），兩者各最多兩次，重試規則相同。
      - **重試**：網路錯誤（連不上、連線中斷、`IncompleteRead`）、逾時與 5xx 等 30 秒重試；429 照回應的 `retry_after` 等，超過 60 秒就不等、直接記失敗。
      - **不重試**：其他 4xx（400／401／403 等：token 或 chat id 錯了，再送也一樣；400 `can't parse entities` 是 Telegram 解析不了 HTML，記 `parse_error`），以及 200 但回應不是 ok 的。
      - **可能重複送**：逾時或連線在送出之後才中斷時，Telegram 可能已經收下，重試會讓使用者收到兩則。照片與文字版各自如此，而照片重試後仍判失敗就改送文字版，所以最壞是 2 張圖加 2 則文字。照片回 200 但內容不是 ok 時不重試、直接改送文字版，最多 1 張圖加 1 則文字。統籌的取捨是重複比漏送好，所以仍重試。
    - 送出記 `sent mode=photo attempts=<次數> message_id=<id> photo=<寬>x<高>`（Telegram 保留的最大尺寸），退回文字版送出記 `sent mode=text reason=<render_failed:<原因>|photo_failed:<每次的原因>> …`。兩種都失敗才記 `failed reason=<文字版每次的原因，逗號分隔，例如 http_500,network:TimeoutError> attempts=<次數> photo=<圖的原因> detail=…`，exit 1。

  - **日誌與不重送**：每次在 `logs/notify-YYYYMMDD.log`（目標台北日）追加 `===== <時間> start job=notify …`、文字版全文（`--- message` 到 `--- message end`）、圖片說明（`--- caption`）與圖的尺寸（`--- card`）、`--- result status=<sent|not_configured|failed|skipped> …` 與 `===== <時間> end exit=<碼> seconds=<秒>`。拿到鎖後先讀當天日誌，已有 `status=sent` 就記 `skipped reason=already_sent`，所以重啟 scheduler 或手動再跑都不會重送；拿不到鎖記 `skipped reason=already_running`。token 在寫出前遮成 `<token>`，不出現在日誌、錯誤與輸出。保留 90 天。不加新表。
  - **鎖與其他工作**：`notify.lock` 與 daily／news／us／preopen 的鎖分開，08:45 也不和它們的時間重疊（`test_worker_serve.py` 檢查），互不卡住。只讀 DB、最多送 4 個請求（照片兩次、文字兩次），再起一個 Chromium 畫圖（約 0.5～0.8 秒）。#754 在 scheduler 的 image 量到的整個 notify 峰值約 312 MiB（只畫圖約 247 MiB），scheduler 上限 2g，08:45 又不和 daily 重疊，所以不檢查記憶體與 git，維護模式中照送。最壞耗時（畫圖逾時 30 秒、照片兩次各 30 秒、文字兩次各 20 秒、兩次 429 各等 60 秒）約 250 秒，在 5 分鐘上限內。
  - **失敗怎麼被發現**：看門狗從 09:10 起判定（09:15 那一輪），`notify_missing`（當天沒有日誌，或 `start` 列比 `end` 列多，兩種留言文字不同）、`notify_failed`（當天最後一個非 skipped 的結果是 `failed`）與 `notify_missed`（當天只有 `too_late`：排程在 08:45～13:30 之外才跑，收盤後不補送），每台北日各最多一則，在 #1 留「待使用者」（[排程看門狗](WATCHDOG.md)）。
  - **手動**：`worker.cli notify --dry-run [--date YYYY-MM-DD]` 只印出那天會送的圖片說明（`caption=`）與文字版全文（第一行 `configured=yes|no`，不印值），不送、不寫日誌；加 `--image-out <路徑>` 另把圖片卡片畫到該路徑（畫不出來時印 `image=failed reason=…`、exit 1）；`worker.cli notify --send --trigger manual` 照排程的流程送一次（鎖、不重送、日誌相同）。
- **intraday 的 08:59～13:31**（#801；#756 決定：來源 [6909643332](https://github.com/YiCheng0608/stock-lab/issues/756#issuecomment-6909643332)、規則 [6906115438](https://github.com/YiCheng0608/stock-lab/issues/756#issuecomment-6906115438)／[6906115855](https://github.com/YiCheng0608/stock-lab/issues/756#issuecomment-6906115855)、架構 [6906133359](https://github.com/YiCheng0608/stock-lab/issues/756#issuecomment-6906133359)）：
  - **內容**：今日名單與我的追蹤的股票觸及頁面上的規則進場、停損或目標價時，幾分鐘內傳一則 Telegram 到 notify 同一個私人 chat（沿用 `worker.notify.send`，`parse_mode=HTML`，股名先 `html.escape`）。訊息只陳述規則價位，不寫「買進」「賣出」「出場」（`test_intraday.py` 掃全部模板）。
  - **對象**：08:59 以唯讀連線（`mode=ro`）讀一次。今日名單是前一個交易日那份名單（`app.candidate_runs.read_run`，同頁面最多 20 檔、依 rank）裡 `earliest_execution_date` 等於今天的訊號；我的追蹤是 `pending`、`triggered`、沒取消、09:00 以前建立的計畫（盤中才新增的當天不納入）。追蹤計畫的訊號就在今日名單裡、而且計畫存的價位和訊號完全相同時是同一檔，只發一則，訊息最後一行寫「來源：今日名單、我的追蹤」；價位不同（計畫建立後訊號被重寫）時分成兩個，各用自己的價位、各自發（#802 review 6910820856 第 2 點）。
  - **價位**：訊號自己的（`signals`），同頁面（`app.candidate_view._levels`）：突破 `breakout_price`、回踩 `pullback_low`～`pullback_high`、停損 `invalid_price`、目標一 `target_1`、目標二 `target_2`；追蹤計畫用計畫自己存的。不用 `strategy_levels`。價位不完整（同 notify 的「價位不完整」規則）的不看。
  - **輪詢**：09:00～13:30 每分鐘一輪（整天 271 輪），每檔一個富果請求（[盤中報價](../DATA_SOURCES.md#盤中報價)），10 個執行緒同時送、10 秒逾時。每分鐘最多 50 檔（免費上限 60 次／分，留 10 次）：超過時依今日名單 rank、再追蹤計畫建立時間取前 50 檔，日誌記 `--- capped kept=50 skipped=<代號>`，當天第一次發一則通知。
  - **落後時不補輪**（#802 review 6910820856 第 1 點）：一輪拖過下一分鐘（`notify.send` 一則最多約 70 秒、富果大量逾時）或主機睡過頭時，下一輪排在還沒過的下一個整分，錯過的分鐘記 `--- skipped_rounds from=<HH:MM> to=<HH:MM> minutes=<N>`、不補問，也不算成 poll；所以同一檔一分鐘最多一個請求，看門狗的 80% 也看得到落後。
  - **規則**（`worker.intraday.judge`，純函式）：用最高最低判斷觸及，這一輪的 `highPrice`／`lowPrice` 和上一輪比，新的最高（最低）越過價位才算；每檔的第一輪用開盤以來的最高最低。試撮（`isTrial`）不判斷；報價的 `date` 不是今天（例如颱風臨時停市、行事曆沒標，富果回前一個交易日的報價）也不判斷，每檔記一次 `--- stale_quote symbol=<代號> date=<日期>`。突破是最高 ≥ 進場價、回踩是 [最低, 最高] 與進場區有交集。停損與達標只在進場之後才算；`triggered` 的計畫從頭就算。觸發進場的那一輪開盤已在目標一以上（`gap_above_target`）或停損以下（`gap_below_invalid`）時不算進場，發一則說明，當天這檔不再通知。沒進場就跌破停損發「跌破停損 X，進場條件不再成立」，當天不再通知。進場與停損在同一輪：開盤（或上一輪成交價）已在進場價之上、或回踩已在進場區內或之上時，進場在先、照兩則發；否則發「同一分鐘內觸及規則進場價與停損，先後不明」並結束這檔。進場後停損與目標一在同一輪是 `incomparable`，寫「同一分鐘內觸及停損與目標一，先後不明」。目標一之後只看目標二。同一檔、同一訊號（或計畫）、同一事件一天一次。
  - **訊息**：例「1802 台玻 觸及規則進場價 81.70（10:12 前後；10:12:05 成交 81.80）」：「HH:MM 前後」是這一輪的時間（上一輪和這一輪之間觸及），括號附 `lastTrade` 的價與時間，沒有就寫「成交價取不到」。漲停（跌停）鎖住（`isLimitUpPrice` 且 `isLimitUpBid`；跌停是 `isLimitDownPrice` 且 `isLimitDownAsk`）另起一行「漲停鎖住（委買 200.00，委賣取不到）」，取不到的一邊照實寫，不推算。
  - **失敗處理**（富果）：單次逾時、連線失敗或 5xx 時這一分鐘這檔跳過、不重試。整輪沒有一檔回 200 算一次失敗，連續 5 次改成每 5 分鐘一輪，發「盤中報價暫停（來源回應失敗），HH:MM 起；改為每 5 分鐘讀一次」；之後有一輪回 200 就恢復每分鐘並發「盤中報價恢復，HH:MM 起」。這兩則當天各一次，第二次中斷只改間隔、不再發。429、401、403 當天停止讀取，發「盤中報價今天停止讀取（富果回應 <碼>：<原因>），HH:MM 起」，結果記 `stopped`。404 與回應缺 `highPrice`／`lowPrice`／`lastTrade`（格式不對）只讓那一檔當天停止，日誌記 `--- dropped symbol=<代號> reason=<http_404|malformed:<欄位>>`。開盤後還沒有第一筆成交的檔（沒有 `lastTrade`、最高最低、開盤價與成交量）不算格式不對，下一分鐘再問。Telegram 送失敗記 `--- send_failed`，該事件不重送。
  - **日誌**：`logs/intraday-YYYYMMDD.log`，每次執行追加 `===== <時間> start job=intraday …`、`--- targets`（各來源檔數）與每檔一列 `--- target`、每輪一列 `--- poll at=<HH:MM:SS> symbols=<檔數> ok=<成功數> codes=<碼:次數,…> ms_median=… ms_max=… lag_median=… lag_max=…`（`lag` 是收到時間 − `lastUpdated` 的秒數）、每個事件一列 `--- event key=<signal:<id>|plan:<id>|ops> symbol=… event=… status=<sent|failed>`、`--- result status=<finished|stopped|not_configured|skipped|failed> …` 與 `===== <時間> end exit=<碼> seconds=<秒>`。當天的事件另存 `logs/intraday-YYYYMMDD.jsonl`（每則一行：時間、key、代號、事件、送出狀態、全文；另外每輪一列 `levels`，記這一輪判斷過、還在看的各檔的最高、最低、成交價與判斷用的價位，沒有 key 與事件，不算事件也不算結果，#808），重啟時先讀它，已發過的不再發（暫停、恢復、停止、略過這幾則通知也算在內）。兩者保留 90 天。富果的 key 與 Telegram token 遮成 `<key>`／`<token>`，不寫進日誌、jsonl 與輸出。富果的報價（成交價與時間、開盤、委買委賣、每輪的最高最低）只在 jsonl，日誌與終端沒有（#833，[DATA_SOURCES 源頭遮罩](../DATA_SOURCES.md#盤中報價)）。不寫 DB、不加表與 migration。
  - **跳過**：週末或行事曆標 `closed` 記 `skipped reason=non_trading_day` 就結束；沒有 `FUGLE_API_KEY`（或 Telegram 的 token／chat id）記 `not_configured missing=<變數>` 就結束，不算失敗；沒有對象記 `no_targets`；拿不到鎖記 `already_running`；`--trigger scheduler` 在 13:30 以後才起跑記 `too_late at=<HH:MM>`。維護模式中照跑（不寫 DB）。
  - **重啟**：serve 在週一至週五 08:59～13:30 之間啟動，而當天的 `logs/intraday-YYYYMMDD.log` 沒有 `finished`、`stopped`、`non_trading_day` 或 `no_targets` 的結果時，立即補跑一次，記 `serve catchup job=intraday reason=not_running`（維護模式中照補）。補跑的那次從下一個整分起輪詢，讀 jsonl 接續：已發的事件不再發，各檔第一輪拿 jsonl 裡含有這檔的最後一列 `levels`（某輪逾時沒判斷到這檔，就是它更早的那列）的最高最低當「上一輪」，所以重啟前已到過的價位（例如回踩型進場前就碰過的目標一）不會再算一次「觸及」。讀不到這檔的 `levels`（例如重啟前它還沒判斷過），或記下的價位和現在不同（盤中改過計畫的價位），這檔照舊用開盤以來的最高最低。jsonl 已存在時，日誌記一列 `--- levels_restored restored=<還原檔數> missing=<key,…|->`，兩個數只算會輪詢（沒被每分鐘上限略過）、當天還沒結束的檔；jsonl 不存在時（重啟前一輪都沒判斷完、也沒發過通知）不記，行為和第一次執行相同（#808）。`not_configured` 也會補：使用者盤中才放好 key、重建 scheduler 時當天就接上。
  - **資源**：每分鐘最多 50 個 GET，回應每個約 2 KB；只讀 DB 一次。最大 RSS 實測 74.1 MB（#801 AC-4：import 整個 `worker.cli`、50 檔跑完整天 271 輪；只 import 完是 72.2 MB）。鎖 `intraday.lock` 與其他工作分開，08:59 也不和其他工作的時間重疊（`test_worker_serve.py` 檢查）。
  - **失敗怎麼被發現**：看門狗在交易日 13:45 那輪（13:45 起）判定：沒有 `logs/intraday-YYYYMMDD.log`、或成功輪詢（`--- poll` 列 `ok` 大於 0）少於整天 271 輪的 80%（217 輪以上才算夠，216 輪以下留言）時，在 #1 留言 `intraday_result_<日期>`，每台北日一則（[排程看門狗](WATCHDOG.md)）。休市日（行事曆標 `closed`，或日誌是 `non_trading_day`）、`not_configured` 與 `no_targets` 不判。
  - **手動**：`worker.cli intraday --dry-run [--minutes N] [--raw-file <路徑>]` 照常讀富果、判斷，不送 Telegram、不寫日誌與 jsonl、不取鎖，日誌列與訊息印到 stdout，訊息裡富果的值遮成 `<價>`／`<時間>`；加 `--raw-file` 時，原始的訊息與每輪 `levels` 以 jsonl 追加到那個本機檔（空值、路徑在 git checkout 裡、intraday 自己的日誌或 jsonl、logs 目錄底下都拒絕，#833）（AC-6 實測用；不要和排程的那次同時跑，兩邊會共用 key 的每分鐘 60 次）；`worker.cli intraday --send --trigger manual` 照排程的流程跑。
- **分工**：鎖、起跑前檢查、單次上限、日誌與 exit code 都由 job 負責，與 [daily／news 工作的註冊與管理](platform/windows.md#dailynews-工作的註冊與管理)、[日誌與 run 記錄](#日誌與-run-記錄)相同；serve 自己不加鎖，重疊的觸發照樣啟動 job，由 job 記 `already_running`（同一工作同時最多 3 個，再多的由 APScheduler 擋下並在 stderr 記警告）。不帶 `--git-pull`：程式由 image 決定（部署見 [RELEASE](../RELEASE.md#部署)）。
- **第二道防線**：daily、news 超過 job 上限 5 分鐘（#466 review 前是 10 分鐘，排程 daily 的 21:30 那次因此在 22:55、早於 23:00），或看門狗、事件 monitor 的一輪跑超過 10 分鐘，serve 結束它的程序群組並記 `serve killed`，同工作排程器的上限。
- **錯過的時段**：機器睡眠時錯過的觸發在醒來後補跑一次（APScheduler `coalesce`、不限 misfire 時間，同 StartWhenAvailable）；serve 啟動前的時段不補，只有 daily 例外：serve 啟動時是週一至週五、已過第一個 daily 時間（預設 21:30），而當日 `schedule_runs` 沒有 `success`／`non_trading_day`（讀不到 run 表也算），就立即補跑一次，記 `serve catchup job=daily reason=<not_complete|unreadable:…>`；沒有 `stock.db`（空 volume）不補（#342 決定第 5 點）。部署或切換在晚上重建容器時，當天的 daily 不會因此漏掉；21:30 失敗後、23:00 前重建時也立即補跑，不等 23:00。休市日補跑的 daily 與 21:30 的觸發相同：第一次 no-data 記 `non_trading_unconfirmed`，下一次（23:00）再確認。21:30 已 `success` 時不補跑，所以 23:00 之後才重建的容器不補當晚的法人重抓。維護模式中啟動時不補跑，關閉維護模式時才補（[維護模式](#維護模式)）。us 照同樣規則補跑（#568）：週二至週六、已過第一個 us 時間（預設 07:30，#681），而當日沒有 `success`／`already_complete` 的 `us_index_collect` run（讀不到 run 表也算），就立即補跑一次，記 `serve catchup job=us reason=…`。已經存到前一個平日時，worker 自己記 `already_complete`、不發請求，所以重建容器多跑一次也不會多發請求。notify 也補（#728）：週一至週五 08:45～13:30 之間啟動，而當天的 `logs/notify-YYYYMMDD.log` 沒有 `sent` 或 `non_trading_day` 的結果，就立即補送一次，記 `serve catchup job=notify reason=not_sent`。`failed` 與 `not_configured` 也會再送：使用者 08:45 之後才設好 token、重建 scheduler 時，13:30 前當天就補送。13:30 收盤後不補（job 自己也擋，見上面的 `too_late`），沒有 `stock.db` 不補，維護模式中照補。preopen 也補（#755）：週一至週五 08:20～13:30 之間啟動，而當天的 `logs/preopen-YYYYMMDD.log` 沒有 `checked`、`already_checked`、`non_trading_day` 或 `no_list` 的結果，就立即補跑一次，記 `serve catchup job=preopen reason=not_checked`；它會寫 DB，所以維護模式中不補，關閉維護模式時才補（同 daily 與 us）。intraday 也補（#801）：週一至週五 08:59～13:30 之間啟動，而當天的 `logs/intraday-YYYYMMDD.log` 沒有結束當天的結果，就立即補跑一次，記 `serve catchup job=intraday reason=not_running`，維護模式中照補（見上面 intraday 一節）。
- **維護模式**（#468）：標記檔在時 daily、news 與 preopen 只記 skipped，看門狗、monitor、notify 與 intraday 照常；serve 每分鐘讀一次標記檔，解除作業持有、心跳超過 10 分鐘的標記檔（`maintenance_expired`），解除後補跑當日缺的 daily、us、preopen、notify 與 intraday（notify 與 intraday 在維護模式中本來就照跑，解除時仍照同一套判定補，正在跑的那次拿不到鎖、記 `already_running`）；執行期間持有 `<data>/locks/serve.lock`（`maintenance status` 的 `serve_running`）。見[維護模式](#維護模式)。
- **停止**：子程序隨 serve 結束（PR_SET_PDEATHSIG）。`docker stop`（SIGTERM，`tini` 轉給 serve）時 serve 收到訊號當下就記 `stopping`（由專責執行緒經 wakeup fd 接手，不等下一個排程時間，#503）、結束執行中的 job 後退出；`docker kill` 時整個容器一起結束。兩者都不留下 job 或鎖，被殺的 daily 的 run 列由下一次拿到鎖的 daily 立即記 abandoned（[日誌與 run 記錄](#日誌與-run-記錄)的 `failed`）。
- **輸出**：serve 的列 `<台北時間> serve <事件> key=value`（`ready` 列出各工作下次執行時間；`start`、`end exit=<碼> seconds=<秒>`，被結束時 `exit=killed`；`killed`、`stopping`、`stop_kill`、`stopped`），與 job、看門狗的 stdout 一起寫到 stdout，由 `docker logs` 查；各工作的日誌照舊在 `<data>/logs/`。
- **時間注入**：`--now YYYY-MM-DDTHH:MM[:SS]`（沒有時區時為台北時間）讓排程的時鐘從該時間起算，照真實速度走；daily 與 us 另帶 `--date <該台北日>`，preopen、notify 與 intraday 另帶 `--now <注入的時間>`（preopen 檢查 08:20～13:30、檢查時點也照注入的時間記；notify 檢查 08:45～13:30；intraday 的每一輪照注入的時鐘走），看門狗以 `WATCHDOG_NOW`、事件 monitor 以 `MONITOR_NOW` 判定。日誌檔名與時間戳記仍是真實時間。只用在 DB 副本上的驗證。
- **run 記錄的 image 與 HEAD**：`schedule_runs` 每列的 `summary_json.runtime` 記 `image`（`STOCK_IMAGE_TAG`）、`head`（`STOCK_GIT_HEAD`，沒有時 `git rev-parse HEAD`，都沒有為 null）與 job 持有的鎖 `job_lock`。build context 不含 `.git`，所以 build 時帶入；正式 project 由 [`deploy.sh`](../RELEASE.md#部署) 以 `STOCK_RELEASE_TAG=<tag> STOCK_GIT_HEAD=<該 commit> docker compose build` 帶入（[Docker compose](SETUP.md#docker-compose)，#340），單獨 build 時：`docker build -f backend/Dockerfile -t stock-lab-backend:<tag> --build-arg STOCK_IMAGE_TAG=stock-lab-backend:<tag> --build-arg STOCK_GIT_HEAD="$(git rev-parse HEAD)" .`。
- 其他選項：`--data-dir`、`--log-dir`、`--claude-cli`、`--daily-min-free-memory-gb`、`--news-min-free-memory-gb`、`--daily-time-limit-minutes`、`--news-time-limit-minutes`、`--us-min-free-memory-gb`、`--us-time-limit-minutes`（交給 job）；`--monitor-dir`、`--monitor-orca`、`--monitor-waker`（交給 monitor，後兩者預設 `http_orca.sh`、`http_wake.sh`，經主機的 wake listener，[統籌事件 monitor](MONITOR.md)）。只在 Linux 執行，其他系統 exit 69。

工作排程器的工作為什麼要維持停用、為什麼不能回退見 [Windows 工作排程器](platform/windows.md)。
