<!-- owns: 排程看門狗 -->
# 排程看門狗

`tools/ops/watchdog.sh`（bash）在 scheduler 容器由 serve 每小時 :15、:45 執行（[scheduler 容器的排程（serve）](SCHEDULING.md#scheduler-容器的排程serve)），只檢查排程與資料不變量：以檔案與唯讀 DB 判定異常並在 [#1](https://github.com/YiCheng0608/stock-lab/issues/1) 留言「待使用者」，每個異常每台北日最多一則。不判定統籌是否在線、不開或喚醒統籌（統籌開啟見[統籌手冊](../COORDINATOR.md#統籌-session)，喚醒由 [統籌事件 monitor](MONITOR.md) 的事件 monitor 負責）。

- 判定時點（#466）：daily 每個交易日跑 21:30 與 23:00 兩次（[scheduler 容器的排程（serve）](SCHEDULING.md#scheduler-容器的排程serve)），23:00 是 21:30 失敗或沒跑時的重試。以下三項 daily 檢查都從台北 23:10 起判定（23:00 那次已寫入日誌與 run 列），當晚只有 23:15、23:45 兩輪：21:30 失敗而 23:00 還會重試時不提早留言；23:15 時 23:00 的重試仍在跑，就留到 23:45 判定。
- `daily`：週一至週五台北 23:10 後，當日 `logs/daily-YYYYMMDD.log` 不存在或沒有 `end` 列。21:30 那次在排程上限 80 分鐘內結束並寫 `end` 列；23:00 遇上仍在跑的 run 時，自己記 `already_running` 也寫 `end` 列。只有 23:00 的重試（或 serve 重啟時的補跑）是當天唯一一次、23:15 仍在跑時，這一項會在 23:15 留言。
- `daily` 結果：週一至週五台北 23:10 後唯讀查當日目標的 `schedule_runs`：當天有 `success`／`non_trading_day` 就算完成（之後的 `skipped` 不影響，例如 23:00 被 `low_memory` 擋下）；否則取最後一筆（略過只指向別列的 `already_complete`／`already_running`），是 `partial`、`failed`、`non_trading_unconfirmed` 或 `skipped:<原因>`（例如 `low_memory`）就留言；仍在 `running` 的等下一輪，超過 2.5 小時視為 `failed`；當日 success 但 catchup 沒補齊（`catchup_incomplete`）也留言；有日誌卻沒有任何 run 列（worker 沒能啟動）也留言，但日誌裡有 `skipped reason=maintenance` 的不算：那天的 daily 因[維護模式](SCHEDULING.md#維護模式)跳過，不寫 run 列，只記 `daily_maintenance`：解除後 serve 還會補跑。下一條的前一個交易日例外：到 00:30 還是只有維護的跳過、沒有 run 列，表示維護跨過午夜、serve 不會再補，就留言（`daily_result_<日期>`，寫出手動補跑的命令）。
- `daily` 前一個交易日（#466 review）：每天 00:30 後，對今天以前最近的一個週間日再判定一次 daily 結果，規則同上，但仍是 `running` 而超過 85 分鐘（serve 的排程上限 80 分加第二道防線 5 分）的視為 `failed`。用來抓 23:00 的重試（或 21:30～23:00 重啟後的補跑）卡住、00:20 才被 job 結束、當晚兩輪看門狗都還看到 `running` 的情況。當晚已就該日留言（key `daily_result`）或之前已補報過（key `daily_result_<日期>`，例如週六替週五報過，週一不再報）時不再留言。
- 當日資料核對（`data_check`，#390）：daily 結果是 `success` 的交易日，23:10 後（23:00 的法人重抓之後）以 `tools/ops/data_check.py` 唯讀（`mode=ro`、`query_only`）核對當日寫進 DB 的資料，每個交易日只核對到有結論為止，不修資料。
  - 用 collector 自己的 parser 與 [重跑與回補的冪等](SCHEDULING.md#重跑與回補)的寫入規則重讀當日 raw（`raw_payloads.payload_path` 指的檔）。日線（OHLC、成交股數與金額、暫停）與融資比對該列指向的 capture，或當日任一 capture（補空欄）；三大法人比對當日最新一份法人 capture（#387）。逐列逐欄，不抽樣。
  - 除權息：當日的列比對寫入它的 TWT48U／tpex_exright_daily 列（套 #386 防呆）。另向官方要當日的 TWT49U（權類另要 TWT49UDetail）與 exDailyQ，總預算 120 秒：TWT48U 寫的列核對因子，其他列核對欄位，並列出 DB 有、官方結果表沒有的事件（明細讀不到的權類事件除外）。預算用完或讀不到時記 `action_official_unavailable`，前面的比對照常列出。
  - 也列出：
    - raw 有、DB 沒有的日線、籌碼列與除權息事件（含先前 TWT48U 已公告當日的）。
    - 近 5 個交易日標的已建立、仍未補寫的 `unmatched_bar`（#388）。
    - 上市、上櫃普通股（`stock`／`ipo`）列數比前 5 個交易日的中位數少 3% 以上（`列數 × 100 ≤ 中位數 × 97`）。
    - 當日法人重抓（#396，排程上是 23:00 那次）是 `failed`／`partial`。daily 在 21:00 前成功（手動跑）、之後沒有重抓也列出：此時法人只跟 21:00 前的檔比過。21:30 起跑成功、23:00 沒有重抓（例如被 `low_memory` 擋下）不列：21:30 的 collect 已拿到較晚的法人檔。
  - 同一事件在一次核對裡只列一筆，來源寫在說明欄：TWT48U 與官方表各自缺的同一事件、同一代號同一天的 `unmatched_bar` 與 `bar_missing`。跨日不合併：還沒補寫的 `unmatched_bar` 在之後 5 個交易日的核對裡都會再列一次。
  - 一天什麼時候算核對完：
    - 沒有不一致，或不一致已經在 #1 留言（key `data_check_<日期>`）時，記 `data_check_done`。`gh` 留言失敗不算，下一輪重新核對、重新留言；`--dry-run` 不算。
    - 法人重抓仍在跑時記 `data_check_pending`；核對失敗、超過 4 分鐘或輸出無法判讀時記 `data_check_failed`。這幾種情況都是下一輪再試。
    - 到當晚最後一輪（23:45）仍沒有結論時，以 key `data_check_incomplete_<日期>` 留一則「沒有核對完」，寫出原因，之後不再自動核對這一天。
    - 當晚沒跑到（關機、過了午夜）的交易日，之後 4 天內的看門狗會補核一次，沒有結論就直接留「沒有核對完」。
    - 每輪最多核對 2 天，先核舊的。DB 缺核對用的表時不判定。
  - 處置：統籌依留言決定開 Issue 修寫入端，再依 [重跑與回補](SCHEDULING.md#重跑與回補) 或該 Issue 的修正命令修資料。全部明細：`python tools/ops/watchdog_helper.py data-check <stock.db> <日期> --all`（`--offline` 不向官方要結果表）。
  - 抓不到的：parser 今天仍以同樣方式讀錯的欄位（全歷史審查見 #391）；daily 沒有成功的交易日不核對。
- `maintenance_long`（#468）：[維護模式](SCHEDULING.md#維護模式)的標記檔 `<data>/locks/maintenance` 在時，每輪記 `maintenance_on`（開始時間與時數）；開超過 12 小時（`MAINTENANCE_MAX_HOURS`）就留言請關掉，每台北日一則。開始時間取標記檔記的時間，讀不懂（或找不到 Python）時取檔案的修改時間。維護模式期間 daily、news 照樣寫日誌（skipped），所以 `daily` 的日誌檢查與下一條 `news` 不會因此留言。
- `maintenance_expired`（#468 AC-5）：`logs/maintenance.log` 24 小時內有 `expired` 紀錄，也就是 serve 解除了一個心跳停了 10 分鐘以上的作業（回補或回測被 SIGKILL 或 OOM 結束，`finally` 沒有執行）的維護模式。留言寫出命令、PID、原因與停了幾分鐘；daily 與 news 已恢復，作業沒有跑完，要查它的輸出並決定是否重跑（回補以相同參數重跑會從 manifest 續做）。每台北日一則。
- `news`：最新的 `logs/news-*.log` 已超過 6 小時（連續 3 次）沒有更新。
- `us`（美股四檔，[#568](https://github.com/YiCheng0608/stock-lab/issues/568)；排程是週二至週六 07:30、08:30、09:30（#681），見 [scheduler 容器的排程（serve）](SCHEDULING.md#scheduler-容器的排程serve)）：
  - `us_no_log`：最新的 `logs/us-*.log` 超過 4 天沒有更新。週六到下週二最長隔 3 天，再多留 1 天。
  - `us_failed`：所有 `us-*.log` 裡最後 2 個 `end` 列的 exit 都不是 0（`partial` 是 2、`failed` 是 1）。job 被擋下（`skipped`）與 `already_complete` 都是 0，不算失敗。
  - 每台北日各最多一則；還沒有任何 `us-*.log` 時不判定。
  - 處置：查該日誌與 `/api/ingestion-runs?q=us_index_collect&include_metadata=true` 的 `series.<代號>.error`。FinMind 回 402（超過每小時上限）時等下一個時段；修好後用 `docker compose -p <P> exec scheduler python -m worker.cli job us --trigger manual --min-free-memory-gb 2` 補跑。
- `monitor_stale`：事件 monitor 的 `logs/monitor-heartbeat.json`（`--monitor-dir` 給了就讀那個目錄的，scheduler 容器是 `/coordination`，#338）超過 10 分鐘沒有更新，或讀不出輪詢時間（[統籌事件 monitor](MONITOR.md)；monitor 每分鐘寫一次）；檔案不存在（monitor 尚未註冊）時不判定。心跳仍在更新、但記錄 gh 已連續 10 輪失敗（例如登入過期，佇列收不到 PR 與留言）時另以 `monitor_gh_failed` 留言，附第一次失敗的時間與最後的錯誤，請查 `gh auth status` 與 `gh api rate_limit`（帳號共用的 5000 次／小時可能已用完）。
- `news_llm`：`stock.db` 最近 3 批判讀都是 `pending`；或 24 小時內最近 3 筆 `run_type=news_llm` 都是 `failed`（`running` 超過 90 分鐘也算）；或 news 日誌（今昨兩天的檔）24 小時內最後 3 個 `news_llm_exit=` 都是 `1`／`wrapper_error`（涵蓋表不存在等不寫 run 的失敗）。後兩者合為一則 `news_llm_failed` 留言；限 24 小時是為了 news 停擺後不再每天就舊失敗留言，停擺本身由上一條 `news` 判定。
- `llm_auth`：24 小時內 news_llm 或 candidate_notes 最近一次 run 有 `claude -p` 認證失敗（`not_logged_in`）的批次，判定與處置見 [容器內的 claude 與 gh 認證（.env）](SETUP.md#容器內的-claude-與-gh-認證env)。
- `gh_auth`：每次執行先讀一次 repo，GitHub 拒絕 gh 的認證（401 或沒有 token）時記 `gh_auth_failed`、當次異常不留言，gh 恢復後補留一則，見 [容器內的 claude 與 gh 認證（.env）](SETUP.md#容器內的-claude-與-gh-認證env)。
- 資料不變量（每輪、不分時段，唯讀查 `stock.db`；各條數字印在 stdout，`--dry-run` 可看）：
  - `invariant_future_date`：`market_bars` 最新 `trading_date` 晚於台北今日。
  - `invariant_bar_provenance`：最新 `trading_date` 的 `market_bars` 有 `source` 為 `unknown`／空，或 `data_as_of` 為空。
  - `invariant_llm_provenance`：`news_llm_results` 中 `llm_status=done` 的列沒有 `llm_model`，或 `prompt_version` 為空。
  - `invariant_execution_calendar`：最新一個 analysis 訊號日有訊號沒有規則最早執行日（`earliest_execution_date` 為空）；原因是官方休市表缺該年度（例如年底時明年還沒公告），或 trading_calendar 步驟失敗而表內沒有該年度。只看改用休市表之後寫入的訊號（evidence 有 `execution.calendar`）：DB 還沒有 `trading_calendar_days`（0020 以前）時印 `skip reason=no_trading_calendar`；升到 0020 後、第一次新的 analyze 之前，最新訊號日還是舊訊號（不回填，永遠為空）時印 `skip reason=signals_before_calendar`，不留言。處置：看該日 analyze 步驟 `details_json.execution_calendar`（`reason`、`missing_year`）與 trading_calendar 步驟，官方公告後跑 `python -m worker.cli trading-calendar`，之後的訊號就有日期；已存的訊號不回填（[價位、ETF 與生命週期](../spec/README.md#價位etf-與生命週期)）。
  - `invariant_strategy_levels`：最近一次已結束的 daily run 的 `strategy_levels` 步驟不是 `success`／`no_data`／`skipped`（#274）。這一步失敗不改 run 狀態（[日誌與 run 記錄](SCHEDULING.md#日誌與-run-記錄)），只有這條會讓人知道個股頁策略總表的觀察價位沒更新；`skipped`（analyze 沒成功）由 daily 本身的異常回報，不重複留言。DB 沒有 `schedule_run_steps` 或還沒有任何含這一步的 run（0019 以前、或發佈 branch 沒有這一步）時印 `skip`。處置：看該 run 的步驟列 `error`，修好後跑 `python -m worker.cli strategy-levels --date <目標日>`。這條判的是步驟列，不是資料：手動補算不會改那一列，所以留言（每台北日一則）會持續到下一個交易日的 daily 該步驟成功、成為最近一次的步驟列才停（例：週五失敗、週五晚上補算，週六、週日仍各留一則），補算後的留言可略過。
  - `invariant_candidate_notes`：最新候選日的現行評分版本清單（`candidate_runs` 中 `score_version` 等於 `watchdog_helper.CANDIDATE_SCORE_VERSION` 的最新 `trading_date`；這個常數由後端測試釘成與 `app.domain.CANDIDATE_SCORE_VERSION` 相同，也就是 `candidate-notes` 會寫說明的版本）有候選、但 `candidate_llm_notes` 沒有一列 `done`（任何提示版本都算），而且清單產生超過 30 分鐘（#517）。只看最新候選日：較早日期的清單缺說明不判定，也不留言。其他評分版本的清單（例如部署新版本前 daily 算的舊版）不判定，因為 `candidate-notes` 不會替它們寫說明。原因可能是手動重產候選時加了 `--skip-notes`、候選由其他指令重算，或 `claude -p` 失敗（額度、每日呼叫上限）。有 `job=daily` 的 `schedule_runs` 或 `run_type=candidate_notes` 的 ingestion run 仍是 `running`（2.5 小時內）時印 `skip reason=daily_running`／`notes_running`，未滿 30 分鐘印 `skip reason=recent`，最新一筆 candidate_notes run 在 24 小時內且有批次登入被拒（`not_logged_in`）時印 `skip reason=notes_auth`（同一原因由上面的 `llm_auth` 留言，不重複；超過 24 小時 `llm_auth` 不再報，這條改為照常判定），DB 沒有候選或說明的表時印 `skip`。處置：查 `/api/ingestion-runs?q=candidate_notes&include_metadata=true`，再跑 `python -m worker.cli candidate-notes --date <候選日>`；說明補上一檔後就不再留言。
  - `invariant_period_backfill_<窗口>`（#539）：最近 3 次（`PERIOD_BACKFILL_FAILURES`）有 period_backfill 結果的 daily run，`summary_json.period_backfill.status` 都不是 `success`／`skipped`（[period_backfill](SCHEDULING.md#日誌與-run-記錄)：MOPS 季報與月營收在法定期限前後的窗口回補，失敗不改 run 狀態，只有這條會讓人知道）。數的是 run 不是交易日，3 次通常是 3 個交易日：一天的 MOPS 中斷不留言，月營收窗口（次月 1～20 日）還留有時間修好並手動補。但 21:30 的 run 失敗、23:00 重跑時兩次都會跑這一步，同一天算 2 次，所以 3 次可能只跨 2 個交易日。沒有這一項的 run（collect 沒成功、#536 以前）略過，不算失敗也不中斷連續；`success` 或 `skipped` 中斷連續。最近一次是 `skipped`（`reason=outside_window`）時印 `skip reason=outside_window`，窗口外不判定。`<窗口>` 是最近一次補的最新季與最新月（例如 `2026Q3_2026-10`），**每個窗口只留一則**，不是每台北日一則：日誌已有該 key 的 `anomaly_commented` 就記 `anomaly_already_commented`；最新月或最新季換了（例如 12 月窗口開始）算新的窗口。月份進出窗口也會換 key：季報窗口（Q3 是 10/31～12/13）跨過兩個月營收窗口，同一季一路失敗時，key 有 `2026Q3`（10/31 與 11/21～11/30）、`2026Q3_2026-10`（11/1～11/20）、`2026Q3_2026-11`（12/1～12/13）三種，最多留 3 則。DB 沒有 `schedule_runs` 或還沒有任何 period_backfill 結果時印 `skip`。處置：`python -m worker.cli schedule-runs --date <目標日>` 看 `summary_json.period_backfill` 的 `error`，修好後對該期手動跑 `fundamentals backfill --quarters 2`／`revenue backfill --months 2`（[CLI](CLI.md#現有-worker-cli)）。
  - `invariant_status_sync`：某交易所最近一次[標的狀態同步](../DATA_SOURCES.md#標的狀態同步)（`data_quality` 的 `instrument_status_sync`）是 `skipped`，也就是官方清單缺席（absent）與 60 個交易日沒有行情列（dormant）的現行標的合計超過該交易所的 5%（至少 5 檔），整批沒有改；留言與 warning 分別寫出兩者的檔數。collect 仍是 `success`，warning 記在 run 的 `noncore_warnings` 與 `instrument_status_sync`。
  - `invariant_deploy_image`（不讀 DB，有 Python 就每輪檢查）：看門狗所在 image 的 `STOCK_IMAGE_TAG`／`STOCK_GIT_HEAD`（scheduler 容器的，[scheduler 容器的排程（serve）](SCHEDULING.md#scheduler-容器的排程serve)）不等於部署記錄 `logs/deploy.json` 的 `image`／`HEAD`，或記錄讀不懂（#340，取代 #314 核對發佈 checkout HEAD 的 `invariant_deploy_head`；不讀任何 checkout 的 git）。原因是容器在 [`deploy.sh`](../RELEASE.md#部署) 之外被重建（例如不帶 `STOCK_RELEASE_TAG` 的 `docker compose up -d --build`，image 變成 `<project>-backend:latest`），或 `deploy.sh` 在寫記錄之後失敗（exit 3）；處置是依 [RELEASE](../RELEASE.md) 以 `deploy.sh` 重新部署該跑的 tag。還沒有部署記錄（從未以 `deploy.sh` 部署）時印 `skip reason=no_deploy_record`；`deploy.sh` 寫記錄時持有看門狗的鎖，不會讀到一半的部署。
  - 處置：看門狗不修資料，違反持續存在就每台北日留言一則（`invariant_period_backfill_<窗口>` 是每個窗口一則）。前兩條查該日 daily 日誌與 `/api/ingestion-runs`，修好寫入端後依 [重跑與回補](SCHEDULING.md#重跑與回補) 重跑或回補該日；第三條查 news 日誌的 news-llm 段落。`invariant_status_sync` 由統籌處理，步驟如下：
    1. 看該日 collect run 的 `instrument_status_sync.exchanges.<交易所>` 的 `absent_symbols` 與 `dormant_symbols`。
    2. 清單是暫時不完整時（例如官方 payload 截斷），下一次 daily 同步成功後自動恢復，不需處理。
    3. 核對官方公告確認真的有大量下市或轉市時，執行 `instruments repair --apply --max-status-share <比例>`（它起跑時自己持有[維護模式](SCHEDULING.md#維護模式)，結束時關掉）；比例、依據與輸出記在該 Issue。修正資料前先備份 `stock.db`（[安全升級與復原順序](SETUP.md#安全升級與復原順序)）。`market_bars` 不存在或沒有資料時前兩條印 `skip`，`news_llm_results` 不存在時第三條印 `skip`，都不留言。

`daily`／`news` 還沒有任何日誌時不判定（排程尚未註冊）。執行環境：bash、PATH 上有 `gh`（有 `GH_TOKEN` 或已登入，[容器內的 claude 與 gh 認證（.env）](SETUP.md#容器內的-claude-與-gh-認證env)）；Python 只用來唯讀查 DB（找不到時跳過 daily 結果、`news_llm` 與資料不變量的 DB 檢查，日誌檢查照做），依序取 `--python`、`STOCK_PYTHON`、checkout 的 `.venv/bin/python`、`python3`、`python`。serve 以 `--data-dir /data --python <serve 的 python>` 呼叫它，monitor 開著時另加 `--monitor-dir /coordination`。

scheduler 容器的命令（在發佈 checkout 執行；`<P>` 是正式 compose project，預設 `stock-lab`；`STOCK_DATA_DIR=/data` 由 compose 給）：

| 動作 | 命令 |
| --- | --- |
| 手動判定（只輸出將留的言與資料不變量的數字，不留言） | `docker compose -p <P> exec scheduler bash tools/ops/watchdog.sh --dry-run` |
| 手動核對某交易日 | `docker compose -p <P> exec scheduler python tools/ops/watchdog_helper.py data-check /data/stock.db <YYYY-MM-DD> [--offline] [--all]`（唯讀，不記日誌、不留言） |
| 日誌 | `docker compose -p <P> exec scheduler tail -n 50 /data/logs/watchdog.log`；serve 的輸出是 `docker compose -p <P> logs scheduler` |
| 停用／啟用 | 看門狗由 serve 排程：`docker compose -p <P> stop scheduler`／`start scheduler`（daily、news、monitor 一起停）；回補、回測起跑時自己開[維護模式](SCHEDULING.md#維護模式)，看門狗照常跑，不必停 |

工作排程器（切換前）的註冊與管理命令見 [Windows 工作排程器的看門狗](platform/windows.md#看門狗stock-labwatchdog)。

看門狗一輪超過 10 分鐘時，serve 結束它（[scheduler 容器的排程（serve）](SCHEDULING.md#scheduler-容器的排程serve)）。日誌 `<資料目錄>/logs/watchdog.log`，每列為 UTC 時間、事件、`key=value` 與說明，沒有異常時記 `schedules_ok`；異常留言（每日一則）的頻率限制以此日誌判斷。同一時間只跑一個：Python 以 job 的同一套檔案鎖（`python -m worker.job lock`）持有 `<資料目錄>/locks/watchdog.lock` 並把腳本當子程序再跑一次，鎖由作業系統在 Python 結束時釋放（被強制終止也一樣，子程序一起結束），下一輪不必等；另一輪仍在跑時記 `locked` 並略過。找不到 Python 時不取鎖：serve 的兩輪相隔 30 分鐘、一輪超過 10 分鐘就被結束，所以不會重疊。持鎖的那一輪另清掉被強制終止的看門狗留在 `logs/` 的 `.watchdog.XXXXXX` 工作目錄（記 `stale_work_removed`；`--dry-run` 只記 `stale_work_planned`）；「持鎖」看的是上層程序確實是持有 `watchdog.lock` 的 `worker.job lock`（讀 `/proc`，#448），不看環境變數：手動帶 `WATCHDOG_LOCK_HELD=1` 不取鎖、記 `lock_unverified`、也不清理。舊版的 `logs/watchdog.lock/` 目錄不再使用；DB 檢查因缺 Python 或讀 DB 失敗而沒跑時記 `python_missing`／`daily_check_failed`／`news_llm_check_failed`／`llm_auth_check_failed`／`invariants_check_failed`／`data_check_failed`，不記 `schedules_ok`；gh 被拒時記 `gh_auth_failed`、沒能留的異常記 `anomaly_not_commented`，讀 repo 因其他原因失敗記 `gh_probe_failed`（照常嘗試留言）。舊版（含開統籌）的日誌 `logs/ensure_coordinator.log` 不再寫入。
