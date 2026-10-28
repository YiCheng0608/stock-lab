<!-- owns: 工作目錄與環境、服務啟停、API 跨站請求防護、資料庫 migration 與 readiness、Alembic head、worker CLI、資料品質與研究結果、worker 測試與驗證、排程、排程看門狗、排程註冊與管理、日誌與 run 記錄、重跑與回補、排程限制 -->
# 操作手冊

本文件只保留可操作入口、安全邊界與診斷順序；本機檢查命令見[工作手冊](GITHUB_WORKFLOW.md#本機檢查)，能力狀態見 [ROADMAP](ROADMAP.md)。

## 1. 工作目錄、環境與啟停

後端命令從專案根目錄執行。範例預設使用 workspace 內 `.local` 開發資料；做測試、migration 或可丟棄研究時，先把三個 `STOCK_*` 改成明確的隔離路徑，不指向正式 `data/stock.db`。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt

$env:STOCK_DATA_DIR = (Join-Path $PWD '.local/data')
$env:STOCK_DB_PATH = (Join-Path $env:STOCK_DATA_DIR 'stock.db')
$env:STOCK_RAW_DIR = (Join-Path $env:STOCK_DATA_DIR 'raw')
$env:PYTHONPATH = (Join-Path $PWD 'backend')

python -m worker.cli init-db   # 明確初始化／升級指定 DB 後再啟動 API
python -m uvicorn app.main:app --reload --port 8000
```

**後端 image**（#333，母單 #331）：[`backend/Dockerfile`](../backend/Dockerfile) 是 api 與 scheduler 共用的 image，從 repo 根目錄 `docker build -f backend/Dockerfile -t stock-lab-backend .`。內含 Python 依賴（`backend/requirements.txt`＋lock）、`tzdata`（`TZ=Asia/Taipei`）、git、`gh`、Node 22、Claude Code CLI（`~/.claude.json` 已標記 onboarding 完成）與 Chromium＋CJK 字型（`tools/ops/screenshot.cjs` 用，`SCREENSHOT_BROWSER=/usr/bin/chromium`）；以非 root 使用者 `app` 執行，PID 1 是 `tini`（回收被殺 job 留下的孤兒程序，否則 zombie 的 PID 看起來仍在、run 列不會立即記 abandoned），`STOCK_DATA_DIR=/data`，`PYTHONPATH=/app/backend`。image 本身不帶啟動命令，api 與 scheduler 的命令由 compose 給。build context 排除的檔案見根目錄 `.dockerignore`（含 `.git`）；測試讀 git 歷史，所以容器內跑測試時把 checkout 的 `.git` 唯讀掛進去：`docker run --rm -v "$PWD/.git:/app/.git:ro" stock-lab-backend pytest backend/tests -q`（CI `docker` job 同命令）。執行層（`worker.job` 的 `job` 與 `lock`）只在 Linux 執行，其他系統以 exit 69 拒絕。

`init-db` 會改 schema，執行前先解析三個路徑並為既有 DB 備份（[§2.1](#21-安全升級與復原順序)）。API startup 只跑 `check_database_readiness()`，不會自動建庫、migration、repair 或 stamp；缺檔、空檔、不可讀或不符契約時拒絕啟動。已啟動的 process 不會因 source 更新而改變 lifespan。

`app.config` import 執行設定的 data／raw 目錄建立；API 的資料變更 handlers 及 collect／daily／backfill／analyze／evaluate／backtest／news／news-llm 是寫入入口。要做只讀查驗，應直接使用 SQLite `mode=ro`＋`PRAGMA query_only=ON`，不能用一般 app startup 代替。`GET /api/dashboard`、`GET /api/news`、`GET /api/news/{id}` 會呼叫 `sync_news_from_events`，把本機既有官方 Events 冪等投影成 NewsItem 並 commit。前端開發服務與 `VITE_API_BASE` 見[前端 README](../frontend/README.md#啟動)。

### 1.1 產品 API 的跨站請求防護

`app.main:app` 對每個 POST、PUT、PATCH、DELETE，先經 [`BrowserGate`](../backend/app/browser_gate.py)（純 ASGI，常開，沒有關閉或繞過的設定）才進 router；GET、HEAD、OPTIONS 不檢查。拒絕的請求不讀 body、不開 DB。CORS 只決定瀏覽器讀不讀得到回應，不阻止表單或 `text/plain` 的 simple request 送達本機埠，所以需要這層。四項依序檢查，第一個不符即回應：

| 順序 | 檢查 | 放行條件 | 拒絕 |
| --- | --- | --- | --- |
| 1 | Host | 恰一個值，為小寫 `127.0.0.1:<port>` 或 `localhost:<port>`，`<port>` 是 API 實際監聽埠；或完全等於 `STOCK_API_PUBLIC_HOSTS` 列的一個值。API 都要在 TCP 埠上監聽 | 403 `host_not_admitted` |
| 2 | Sec-Fetch-Site（有送時） | `same-origin`、`none` 放行；`same-site`、`cross-site` 僅在 Origin 已被接受時放行 | 403 `cross_site_rejected` |
| 3 | Origin（有送時） | 在允許清單內，或等於自身 `http://<Host>`。允許清單是 `config.DEFAULT_CORS_ORIGINS`（`http://localhost:5173`、`http://127.0.0.1:5173`）加上 `STOCK_API_ALLOWED_ORIGINS` 列的值 | 403 `origin_not_admitted` |
| 4 | Content-Type（只查 POST、PUT、PATCH） | `application/json`，可接 `; charset=utf-8` | 415 `content_type_json_required` |

拒絕回應是 JSON `{"reason":"<reason>"}` 加 `Cache-Control: no-store`；防護在 `CORSMiddleware` 內側，允許清單內的 origin 被拒時前端仍讀得到狀態碼與 reason。沒有 Origin 與 Sec-Fetch-Site 的請求（curl、腳本）只受 Host 與 Content-Type 規則約束（POST 須帶 `-H "Content-Type: application/json"`）。

允許清單另可由兩個環境變數加值（[`app.config`](../backend/app/config.py) 的 `public_hosts`、`allowed_origins`；範例見 [`.env.example`](../.env.example)）。沒設、或值是空白時，行為與沒有這兩個變數時完全相同：

| 變數 | 加到哪一項 | 每個值的格式 | 用途 |
| --- | --- | --- | --- |
| `STOCK_API_PUBLIC_HOSTS` | Host | `localhost:<port>` 或 `127.0.0.1:<port>` | 瀏覽器看到的 API 埠不是監聽埠：nginx 反代 `/api` 並轉送瀏覽器的 Host（`proxy_set_header Host $http_host`），或容器埠對映到另一個主機埠 |
| `STOCK_API_ALLOWED_ORIGINS` | Origin 允許清單與 CORS（`configure_cors`，同一份清單） | `http://localhost:<port>` 或 `http://127.0.0.1:<port>` | 前端開發服務不在 5173（例如 dev 換 `WEB_PORT`） |

多個值以逗號分隔，前後空白會去掉。`<port>` 是 1～65535、不補前導 0，而且一定要寫：瀏覽器連 80 埠時送出的 Host 不帶 port，列不進清單，寫入會被拒，所以反代或前端對外的埠（`WEB_PORT`）不能用 80。主機名只收小寫的 `localhost` 與 `127.0.0.1`。萬用字元、空項目、`https` 或其他 scheme，以及帶 path、query、fragment、userinfo 的值都不接受。值不符時，`app.main` 匯入就丟 `ValueError`，訊息寫出變數名與那個值，API 不會啟動。worker 不讀這兩個變數。Host 與 Origin 各自比對：列在 `STOCK_API_ALLOWED_ORIGINS` 的埠不會因此成為可接受的 Host，反之亦然。由同一個反代送出的頁面，Origin 等於自身 `http://<Host>`，不必再列進 `STOCK_API_ALLOWED_ORIGINS`。

寫入會被拒的情況：以 LAN IP、機器名稱、IPv6 `[::1]` 或經代理改寫的 Host 連線（例如反代沒轉送 Host，API 看到 `api:8000`）；Host 大小寫變體，或 port 不符、省略且不在 `STOCK_API_PUBLIC_HOSTS`；Unix socket；`VITE_API_BASE` 不符 Host 規則；前端開發服務改用 5173 以外的埠，而該 origin 不在 `STOCK_API_ALLOWED_ORIGINS`。這不是身分驗證，同機其他程式送出符合規則的請求一樣放行。

## 2. 資料庫、migration 與 readiness

程式 Alembic head 是 `0020_trading_calendar`，revision chain 為 0001→0020（`app/migration_revisions.py`；0010 新增 `technical_indicators`，0011 新增排程 run 記錄表，見 [§6.3](#63-日誌與-run-記錄)，0012 新增新聞 LLM 判讀表 `news_llm_results`，見 [NEWS_SPEC §5](NEWS_SPEC.md#5-ai-摘要與推論)，0013 新增每日候選表 `candidate_runs`／`daily_candidates`，見 [V1_SPEC](V1_SPEC.md#candidate_score_v1)，0014 新增新聞題材建議表 `theme_suggestions`／`theme_suggestion_news`，見 [V1_SPEC](V1_SPEC.md#新聞題材建議)，0015 新增候選 AI 說明表 `candidate_llm_notes`，見 [V1_SPEC](V1_SPEC.md#候選-ai-進出點說明)，0016 新增族群分數封存表 `group_daily_score_archive`，見 [V1_SPEC](V1_SPEC.md#hot_group_v1)，0017 新增使用者追蹤計畫表 `tracking_plans`／`tracking_plan_sessions`，見 [V1_SPEC](V1_SPEC.md#使用者追蹤計畫)，0018 新增大盤概況表 `market_summaries`，見 [V1_SPEC](V1_SPEC.md#大盤概況)，0019 新增條件價位表 `strategy_levels`，見 [V1_SPEC](V1_SPEC.md#strategy_levels_v1)，0020 新增官方休市表 `trading_calendar_days`，見 [DATA_SOURCES](DATA_SOURCES.md#交易日曆)）；無法載入 Alembic 時，`init-db` 以內建步驟升級並把 revision 寫入 `schema_migrations`（`migrations.upgrade_database`）。程式 head 不代表任何 DB 已升級。策略版本的遷移規則見 [V1_SPEC](V1_SPEC.md#策略版本識別)。連線一律用 WAL 與 30 秒 busy timeout（`app.db`）：排程的 daily 與 news 寫同一個 DB 時，短交易互相等待；daily 的寫入交易長過 30 秒時，news 遇 `database is locked` 會整個寫入單位（開 run、一個 feed、結束 run）rollback 後重做，間隔 60 秒、最多再 3 次（`news_batch.LOCK_RETRIES`），仍失敗才把該 feed 或該來源記 `failed`（[§3](#3-現有-worker-cli)）。

readiness 只在唯讀 transaction 檢查有限 descriptor：`alembic_version` 必須恰為 current head，`schema_migrations` 必須是不重複的已知 revision 前綴（沒有 `alembic_version` 時須為完整清單）；mapped objects、必要欄名、ordered PK／FK／UNIQUE、News JSON defaults，以及 `signal_settlements` 與 `instruments` 的 identity 必須符合契約。它不執行 `quick_check`、`integrity_check`、資料 FK scan 或完整 type／CHECK／trigger／custom-schema audit，也不涵蓋 live WAL／SHM、concurrent writer、non-SQLite 與 attached schema；通過不保證任意寫入成功。

### 2.1 安全升級與復原順序

1. **備份**：解析實際 DB 絕對路徑，用 SQLite backup API 在專案外建副本；有 WAL 或未確認 writer 時不裸複製主檔。
2. **init-db**：對目標 DB 執行 `python -m worker.cli init-db`。遷移步驟只接受已知的 SQLite schema，在破壞性 DDL 前拒絕未知的 schema、constraint、index、trigger、view 或 marker 矛盾。
3. **驗證**：確認 revision 為 current head，並跑 `PRAGMA integrity_check` 與 `PRAGMA foreign_key_check`。
4. **失敗**：migration 只能前進，失敗時保留 DB 與錯誤，從備份還原到新路徑再診斷；不手動刪暫存表、補 marker、關 FK 或反覆重試。

## 3. 現有 worker CLI

| 指令 | 行為與限制 |
| --- | --- |
| `python -m worker.cli init-db` | 建立／升級指定 DB；先確認路徑、backup 與授權。 |
| `python -m worker.cli collect --date YYYY-MM-DD --months-back 0` | 官方來源收集；`months-back` 只接受 0、1、2、3。 |
| `python -m worker.cli themes sync [--file PATH]` | 驗證[題材表](INDUSTRY_CLASSIFICATION.md#7-題材表)（預設 `backend/data/themes/themes_v1.json`）並寫入 `theme_groups`／`group_memberships`；不發網路，重跑冪等。任何錯誤都整批不寫入、印出位置並 exit 1。題材榜在下一次 analyze／daily 計分。 |
| `python -m worker.cli theme-suggestions` | 由 `news_llm_results` 的題材候選重算[新聞題材建議](V1_SPEC.md#新聞題材建議)，寫 `theme_suggestions`／`theme_suggestion_news`；不呼叫 LLM、不發網路、不寫族群或題材表，重跑冪等（內容不變不改寫）。回傳來源判讀數、建議數、新題材數、與既有族群同名數及新增／更新／刪除數。不會跑 `init-db`，表不存在時回 `theme_suggestions_table_missing_run_init_db` 並 exit 1。正式 DB 唯讀副本（2026-10-18：163 則判讀、93 個建議）重算約 0.1 秒。 |
| `python -m worker.cli industry repair [--apply] [--rescore-days N]` | 依已保存的公司基本資料 raw，把錯配的一般產業 membership 搬到 canonical 群組（規則見 [INDUSTRY_CLASSIFICATION §5.1](INDUSTRY_CLASSIFICATION.md#51-既有錯配-membership-修復)）；不發網路。預設 dry-run 只印預計變更；`--apply` 寫入並記一筆 `run_type=industry_repair` 的 ingestion run，重跑回 `no_change`。`--rescore-days N` 需搭配 `--apply`，寫入後重算最近 N 個 TAIEX 交易日的族群分數（同 analyze 的 `hot_group_v1`），並清掉這些日期停用群組留下的 rank；舊版本寫的分數列在改寫前先封存到 `group_daily_score_archive`（[V1_SPEC hot_group_v1](V1_SPEC.md#hot_group_v1)）；不重算訊號與 `daily_candidates`。寫入與重算在同一個 transaction，正式 DB 執行前要先停用 `daily` 與 `news` 排程（[§6](#6-排程)），完成後再恢復。證據不一致時整批不寫入並 exit 1。 |
| `python -m worker.cli instruments repair [--apply] [--include-delisted] [--max-status-share X] [--rescore-days N]` | 補回 #212 以前 collector 丟掉的資料，只讀已存的 raw，不發網路。依序做三件事：(1) 用已存最新一次的官方清單與行情表（TWSE `t187ap03_L`、`t187ap47_L`、`company/newlisting`，TPEx `mopsfin_t187ap03_O`、`etfFilter`）做[標的狀態同步](DATA_SOURCES.md#標的狀態同步)；(2) 加 `--include-delisted` 時，為已存行情有、DB 沒有、清單也不再列的普通股代號建標的：另一交易所列著就標 `transferred`，否則標 `delisted`；行情停止不到 5 個交易日的不建，只列在 `unmatched`；(3) 以已存的 `dailyQuotes`／`MI_INDEX`／`STOCK_DAY_ALL` 補缺的日線，並對補到日線的標的以 `T86`／`MI_MARGN`／`insti/dailyTrade`／`margin/balance` 補缺的籌碼。只補 DB 沒有的列、不改既有值；raw 與 SHA-256 不符時整批不寫並 exit 1。預設 dry-run 只印預計變更；`--apply` 在同一個 transaction 寫入並記一筆 `run_type=instrument_repair` 的 ingestion run，重跑回 `no_change`。`--rescore-days N` 同 `industry repair`。`--max-status-share` 預設 0.05，見 [§6.1](#61-排程看門狗) 的處置。正式 DB 執行前先停用 `daily` 與 `news` 排程，完成後恢復，之後跑 `indicators --rebuild`。正式 DB 唯讀副本（2026-10-24，最新交易日 2026-10-22）實測：dry-run 約 10 分鐘；`--apply --rescore-days 1` 約 11 分鐘，改 62 檔狀態（27 `delisted`、2 `transferred`、33 `dormant`）、建 15 檔標的、寫入 4,362 根日線與 4,166 筆籌碼；重跑約 5 分鐘，回 `no_change`。 |
| `python -m worker.cli daily --date YYYY-MM-DD --months-back 0 [--trigger manual\|scheduler\|simulation] [--force] [--catchup-sessions N]` | 順序 catchup → collect → trading_calendar → analyze → evaluate → candidates → indicators → theme_suggestions → plan_tracking → strategy_levels → candidate_notes。catchup 先補抓目標日前最近 N 個（預設 5）缺 collect 的官方交易日（[§6.4](#64-重跑與回補)），結果不擋目標日；`--catchup-sessions 0` 不補。collect 成功後先跑 trading_calendar（更新[官方休市表](DATA_SOURCES.md#交易日曆)，結果不影響 run 狀態，analyze 不依賴它，[§6.3](#63-日誌與-run-記錄)），再 analyze；analyze 成功才 evaluate、candidates 與 strategy_levels（evaluate 失敗不擋 candidates；strategy_levels 是條件價位，結果不影響 run 狀態，[§6.3](#63-日誌與-run-記錄)）。collect 成功後跑指標批次（目標日傳給批次；analyze 失敗也跑）、新聞題材建議彙整與追蹤計畫更新（兩者都不依賴 analyze）；candidates 成功才跑 candidate_notes（LLM 說明，結果不影響 run 狀態，[§6.3](#63-日誌與-run-記錄)）；collect 失敗時後續步驟記 `skipped`。每次執行寫一列 `schedule_runs`，trading_calendar、strategy_levels 與 candidate_notes 以外任一步驟失敗則該 run 為 `failed`；當日目標第一次兩市都回 no-data 記 `non_trading_unconfirmed`，下一次觸發再確認（[§6.2](#62-dailynews-工作的註冊與管理)）；exit code 與狀態見 [§6.3](#63-日誌與-run-記錄)。 |
| `python -m worker.cli job daily\|news [--data-dir DIR] [--log-dir DIR] [--trigger …] [--date YYYY-MM-DD] [--force] [--git-pull] [--claude-cli PATH] [--skip-news-llm] [--min-free-memory-gb N] [--time-limit-minutes N] [--log-retention-days N]` | 排程執行的入口（#313）：取該 job 的檔案鎖、起跑前檢查，再以子程序跑 `daily`，或 `news` 後接 `news-llm`，套單次上限並寫 `<data>/logs/<job>-YYYYMMDD.log`；exit code 是 daily／news 的碼。行為、日誌與鎖見 [§6.2](#62-dailynews-工作的註冊與管理)、[§6.3](#63-日誌與-run-記錄)。`daily --skip-reason` 只給 job 用。 |
| `python -m worker.cli serve [--data-dir DIR] [--claude-cli PATH] [--watchdog-dry-run] [--now YYYY-MM-DDTHH:MM] …` | scheduler 容器的常駐排程（#336）：依台北時間定時執行 `job daily`、`job news` 與看門狗，取代工作排程器；選項、輸出與時間注入見 [§6.6](#66-scheduler-容器的排程serve)。只在 Linux 執行。 |
| `python -m worker.cli schedule-runs [--date YYYY-MM-DD] [--limit N]` | 列出 daily run 記錄與各步驟；唯讀。 |
| `python -m worker.cli candidates [--date YYYY-MM-DD]` | 以目前的評分版本 [`candidate_score_v2`](V1_SPEC.md#candidate_score_v2) 對該日（預設 DB 最新訊號日）的訊號評分排序，寫 `candidate_runs`／`daily_candidates`；不發網路、不改訊號。同日同版本已有 run 時回 `already_complete`，不新增、不改寫。該日沒有 analyze 訊號回 `no_data`（`no_signals_for_date`）且不寫列；`success`／`no_data` 以外或例外時 exit 1。全市場約 4 秒（2026-10-16 唯讀副本實測）。 |
| `python -m worker.cli track-plans [--date YYYY-MM-DD]` | 更新未結束的[使用者追蹤計畫](V1_SPEC.md#使用者追蹤計畫)到該日（預設 DB 最新日線日）：寫 `tracking_plans` 的狀態與模擬結果、`tracking_plan_sessions` 的逐日明細；不發網路、不改行情與訊號。與 daily 的 plan_tracking 步驟同一個函式，同日重跑冪等（值沒變不改寫）。沒有計畫時回 `success`、0 筆；DB 沒有日線回 `no_data`；其他狀態或例外 exit 1。回傳檢查的計畫數、寫入的明細列數、各轉換的筆數與 `transition_conflicts`。 |
| `python -m worker.cli market-summary --from YYYY-MM-DD --to YYYY-MM-DD [--force]` | 以已存的上市 `MI_INDEX` raw（`raw_payloads` 中 `type=ALLBUT0999` 的日期報表，每天取最新一份，比對 SHA-256）重建[大盤概況](DATA_SOURCES.md#大盤概況)的上市列；**不發網路請求**，上櫃沒有歷史不回補。每個週間日回 `inserted`／`unchanged`／`filled`／`conflict`／`overwritten`（寫入規則同 collect）、`no_raw`（沒有已存報表）、`no_data`（休市回應）、`unreadable`（檔案不在或雜湊不符）或 `rejected`（日期不符或沒有大盤表）；有 `unreadable`／`rejected` 時回 `partial` 並 exit 1。`--force` 在值不同時改寫並改指向該份 raw。 |
| `python -m worker.cli strategy-levels [--date YYYY-MM-DD]` | 為該日（預設 DB 最新 analysis 訊號日）每個 analysis 訊號寫[條件價位](V1_SPEC.md#strategy_levels_v1)到 `strategy_levels`（每訊號、每 `levels_version` 一列）；不發網路，只讀已存的日線、公司行動、特徵與訊號證據，不改 `signals`。與 daily 的 strategy_levels 步驟同一個函式，同日重跑冪等（值沒變不改寫、`computed_at` 不動）。策略版本不是 registry 現行版本的訊號略過（`signals_skipped`）。該日沒有 analysis 訊號回 `no_data`（`no_signals_for_date`）；`success`／`no_data` 以外或例外 exit 1。回傳處理的訊號數（`records`）、寫入與未改的列數，以及各策略的 `availability` 分佈。正式 DB 唯讀副本（2026-10-22，4,622 個訊號）首次寫入約 9 秒（含程序啟動）、重跑約 8 秒寫入 0 列。不會跑 `init-db`，表不存在時拋錯並 exit 1，先跑 `init-db`。 |
| `python -m worker.cli trading-calendar [--year YYYY ...]` | 抓 TWSE [官方休市表](DATA_SOURCES.md#交易日曆)（每個年度一個 GET，預設今年與明年）存入 `trading_calendar_days`；與 daily 的 trading_calendar 步驟同一個函式。回應與該端點最近一次已存的 raw SHA-256 相同時不另存 raw；內容不同才整年改寫，`years.<年>` 記 `inserted`／`updated`（附 `added`／`changed`／`removed`）／`unchanged`／`unpublished`（官方尚未公告，`total=0`）／`kept`（已有列的年度回應變空，保留舊列並警告）／`failed`（取得失敗或驗證不過，不寫入）。每次執行一筆 `run_type=trading_calendar` 的 ingestion run；`success`／`no_data` 以外（`partial`、`failed`）或例外 exit 1。發佈 DB 升到 0020 後先跑一次載入當年與明年。不會跑 `init-db`，表不存在時拋錯並 exit 1。 |
| `python -m worker.cli candidate-notes [--date YYYY-MM-DD] [--limit N] [--dry-run]` | 以本機 Claude Code 無介面模式（`claude -p --model sonnet`，訂閱登入、不用 API 金鑰，呼叫與環境同 news-llm）為該日（預設最新一次）目前評分版本的候選寫 [AI 進出點說明](V1_SPEC.md#候選-ai-進出點說明)到 `candidate_llm_notes`；不改候選列、分數與排序。每 5 檔一次呼叫（20 檔＝4 次），同一台北日所有 run 合計最多 8 次呼叫；同日同提示版本已 `done` 的不再送，`pending` 的重送；`--limit N` 只送名次在前的 N 檔尚未完成者。超時（300 秒）、非 JSON、不符 schema 時該批標 `pending`、其他批照跑；某檔輸入組不出來時只有該檔標 `pending`；只有實際啟動 CLI 的次數計入每日上限；寫入 DB 失敗（例如 `database is locked`）時本次 run 記 `failed`（`run_error`）並保留已呼叫次數；未登入、額度限制或 CLI 無法啟動時停止本次執行；有 API 金鑰環境變數、找不到 claude，或在 Windows 上解析到的 CLI 不是原生 `.exe`（例如 npm 的 `claude.cmd`，逾時時殺不掉底下的 node，會讓 daily 卡到單次上限）時，記一筆 `failed` run（`cli_not_found`）、不呼叫也不寫說明列。每次執行一筆 `run_type=candidate_notes` 的 ingestion run（每批檔數、耗時、模型、token），prompt 與回應存 raw（`candidate_notes`）；開始時把超過 2.5 小時仍 `running` 的 candidate_notes run 改記 `failed`（`abandoned`）。沒有候選 run 或零候選回 `no_data`、不呼叫。結束碼同 news-llm：`success`／`skipped`／`no_data`／`dry_run` 為 0，`partial` 為 2，`failed` 為 1。不會跑 `init-db`，表不存在時回 `candidate_llm_notes_table_missing_run_init_db`。正式 DB 唯讀副本（2026-10-16 的 20 檔候選，取前 3 檔）一次呼叫約 7 秒。 |
| `python -m worker.cli backfill --start-date YYYY-MM-DD --end-date YYYY-MM-DD --scope market` | 有界官方回補、重試與稽核；不是 backtest。超過 93 日的範圍依序切成多段。 |
| `python -m worker.cli analyze` | 要求最新官方 collect run success 與有效 as-of；沒有 `--date`，也不是任意局部分析器。 |
| `python -m worker.cli evaluate` | 更新 execution／tracking 與 T+5／T+20 settlement；會寫 DB。 |
| `python -m worker.cli backtest --start-date YYYY-MM-DD --end-date YYYY-MM-DD` | 回放既有資料並保存 audit；不下載歷史資料。 |
| `python -m worker.cli indicators [--date YYYY-MM-DD] [--rebuild]` | 以保存日線算 [技術指標](V1_SPEC.md#技術指標) 寫入 `technical_indicators`；不發網路、不改日線。預設（每日）對每檔寫上次已算日之後到 `--date`（預設 DB 最新日線日）的列，通常就是最新一日；最後一筆已算值與重算不符時整檔重寫，但只偵測得到影響最後一列的變動。補登除權息事件、回補或更正舊日線、升版後要跑 `--rebuild` 重寫全部歷史。不會跑 `init-db`，表不存在時回 `technical_indicators_table_missing_run_init_db`。 |
| `python -m worker.cli news [--date YYYY-MM-DD]` | 抓 [新聞來源](DATA_SOURCES.md#新聞來源) 的 RSS，寫 raw 與 `news_items`（去重與關聯規則見 [NEWS_SPEC §3](NEWS_SPEC.md#3-去重新資訊與事件影響)）。每個來源一筆 `run_type=news` 的 ingestion run，status 為 `success`／`partial`／`failed`，失敗的 feed 記在 `error` 與 `metadata_json.feeds`，其他來源照常寫入。可重跑，既有新聞不改寫。寫入遇 `database is locked` 依 [§2](#2-資料庫migration-與-readiness) 重試，仍失敗才記該 feed／來源 `failed`；連 run 都寫不進去時只出現在 CLI 的 JSON 與日誌。`--date` 只標記 run 日期（預設台北今日），不篩選來源內容。不會跑 `init-db`，表不存在時回 `news_items_table_missing_run_init_db`。 |
| `python -m worker.cli news-llm [--date YYYY-MM-DD] [--limit N] [--dry-run]` | 以本機 Claude Code 無介面模式（`claude -p --model sonnet`，使用者的訂閱登入，不用 API 金鑰；#262 起由 `haiku` 改為 `sonnet`）判讀新聞，結果寫 `news_llm_results`（選取、旗標與欄位規則見 [NEWS_SPEC §5](NEWS_SPEC.md#5-ai-摘要與推論)）。挑 3 天內未判讀的新聞，新的在前，最多 `--limit` 則（預設 50），每 25 則一次呼叫；`--date` 只挑該台北日收錄（`collected_at`）的新聞。同一台北日所有 run 合計最多 20 次呼叫，每批呼叫後立即計入，超過的批次跳過並記在 `error`。超時、非 JSON、不符 schema 時該批各則標 `pending`，其他批照跑，下次重試；摘要寫了原文沒有的數字（[摘要核對](NEWS_SPEC.md#5-ai-摘要與推論)）的那則標 `rejected`、不再送，結果 JSON 的 `rejected` 是則數；未登入、額度限制或 CLI 無法啟動時停止本次執行，其餘批次跳過。環境有 `ANTHROPIC_API_KEY`／`ANTHROPIC_AUTH_TOKEN`、`STOCK_CLAUDE_CLI` 格式錯誤或找不到可執行檔時，記一筆 `failed` run 後結束，不呼叫也不寫判讀列。每次執行一筆 `run_type=news_llm` 的 ingestion run，`metadata_json` 記每批則數、耗時、模型與 token 用量；開始時先把超過 90 分鐘（news 工作的單次上限）仍為 `running` 的 news_llm run 改記 `failed`（`abandoned`，例如被排程逾時終止），id 列在結果的 `abandoned_runs`；每批的 prompt 與 CLI 回應存 raw（`news_llm`）。`--dry-run` 只列出批次，不呼叫、不寫 DB。CLI 預設為 PATH 上的 `claude`，可用 `STOCK_CLAUDE_CLI` 指定路徑或 JSON 字串陣列；只支援原生 `claude` 可執行檔，npm 的 `.cmd` shim 在超時時無法終止底下的 node 程序。結束碼同 daily：`success`／`skipped`／`dry_run` 為 0，`partial` 為 2，`failed` 為 1（找不到 claude、未登入、額度限制、全部批次失敗，原因在 JSON 的 `reason`、run 的 `error`）。排程由 `\stock-lab\news` 在 `news` 之後呼叫，見 [§6](#6-排程)。不會跑 `init-db`，表不存在時回 `news_llm_results_table_missing_run_init_db`。 |

`backfill --scope` 支援 `market`、`portfolio`、`watchlist`、`events`、`candidates`、`priority`、`all`；名稱存在不代表資料來源或管理 UI 完整。起日不得晚於迄日；CLI 把較長範圍由舊到新切成每段不超過 `OFFICIAL_MAX_BACKFILL_DAYS=93` 日的連續段，每段各有 request key、manifest 與重試（API 的單次回補仍限 93 日）。CLI 回補不抓只代表「今天」的快照來源（STOCK_DAY_ALL、OpenAPI 指數、除權息、MOPS 清單、TPEx 停復牌），universe 每次執行只抓一次，也不記錄當日產業觀測；目標有效交易日不足時，候選查詢可早於輸入起日，但不得超過迄日前 93 日界線。批次最多 5 個交易日，adapter 逐日呼叫；重試規則是立即 3 次、後續 2 次。`--force` 會重新擷取已完成日期，並非一般重試預設。

`candidates`／`priority` 依群組分數的候選身分決定納入標的，`/api/coverage` 同名 scope 重用同一 resolver（規則見[產業分類 §6](INDUSTRY_CLASSIFICATION.md#6-群組成員與候選身分)）；run 建立時把 `metadata.target_instruments` 固定為 snapshot，resume 與 `--force` 不重新解析。

先檢查 run status、有效 sessions、缺欄／缺日與 raw evidence。collect 為 partial／failed 時，`daily` 不執行後續；不得人工改 status 繞過 gate。

collect 只因**核心**來源的 warning 變 `partial`：日行情、`MI_INDEX`、TAIEX、休市日曆、法人、融資，以及任何未列名的 warning。**非核心**來源（MOPS 重大訊息與基本面、TPEx 停復牌公告與歷史，見 [DATA_SOURCES](DATA_SOURCES.md#核心與非核心來源)）取得失敗時記在 `noncore_warnings`，collect 仍為 `success`、analyze 照跑；`warnings` 保留全部，`core_warnings` 是造成 partial 的那些。daily run 的 `summary_json.noncore_warnings` 列出當次非核心 warning，partial 的錯誤欄只列核心 warning。

## 4. 資料品質與研究結果

- 逐用途檢查交易所、標的、日期與欄位；行情 success 不代表 chips、events、actions 完整。無資料、錯日與 incomparable 的判定見 [V1_SPEC 共通原則](V1_SPEC.md#共通原則)。
- entry、breakout、pullback、invalid、targets 是規則參考價，不是持倉成本、委託或成交；`cost_included=false` 只表示價位公式未扣成本。
- `data_cutoff`、`signal_date`、`earliest_execution_date`、naive `created_at` 都不能證明 `decision_at`。unknown time／basis 必須連同 reason 保留。
- `/api/ingestion-runs`、`/api/backfill-runs`、`/api/data-quality`、`/api/backtest/summary` 提供稽核摘要，`/api/coverage` 提供 coverage。前端入口為 `/research/backtest`、`/research/coverage`、`/system/data-quality`。
- 產業分類 run 與 ordinary、ETF、新上市 receipt 分開讀，其中一個 success 不代表全分類已核實（[產業分類](INDUSTRY_CLASSIFICATION.md)）。

## 5. 測試與驗證

命令見[工作手冊](GITHUB_WORKFLOW.md#本機檢查)，測試資料與落盤原則見 [AGENTS](../AGENTS.md#工程原則)。

- 後端測試用隔離 DB（`backend/tests/conftest.py` 自動指派）。
- 瀏覽器與端到端驗證用隔離 DB 或 `tools/ops/copy_db.py` 產生的唯讀副本（放 worktree `.local/verify/`），不指向正式或其他 `.local` DB。五個主導航的端到端驗證照 skill [verify-stock-lab](../.claude/skills/verify-stock-lab/SKILL.md) 執行（副本啟 API 與 `vite preview`、截圖、證據推 `pr-assets/<issue>`）。

| 命令 | 用途 |
| --- | --- |
| `python tools/ops/copy_db.py --src <stock.db> --dest <目錄> [--force]` | 以 `mode=ro` 連線經 SQLite backup API 複製一份快照（含 WAL 內容；唯讀連線無法也不需要 checkpoint），寫成 `<目錄>/stock.db`；目的地不得在來源目錄內，已有 `stock.db` 時要加 `--force` 才覆蓋；印出副本路徑與來源最新 `trading_date` |
| `node tools/ops/screenshot.cjs --url <頁> --out <目錄>` | headless Edge（或 Chrome）截 1280 與 390 全頁圖並存頁面文字；等骨架消失與請求結束、展開 `details`，可 `--click` 切分頁；印出 `scrollWidth` 與錯誤 |
| `bash tools/ops/push_pr_assets.sh --issue <n> --dir <目錄>` | 不動 checkout，把目錄推到 `pr-assets/<n>`（第一次 orphan commit，之後疊加不強推），印出可貼 PR 的連結 |
| `python tools/verify/fixture_db.py --dest <空目錄>` | 產生 verify 用的固定假資料庫 `<目錄>/stock.db`：走 `init-db` 的 migration 到 head，寫入 `tools/verify/fixture_data.py` 的虛構資料（五個主導航都有內容，每頁預期寫在 `EXPECTED`）；印出 `alembic_version`、各表列數與內容雜湊，兩次產生結果相同。schema 同步與 API 預期由 `backend/tests/test_verify_fixture.py` 檢查 |
| `python tools/verify/page_checks.py --api <API> --web <preview> --db <stock.db> --out <目錄> [--fixture] [--g7]` | 跑 `features/*.md` 標「CI」的全部檢查：抓 API、以 `screenshot.cjs` 截圖（4 個瀏覽器並行）、比對頁面文字與 API／`db_facts.py`；結果是通過／失敗／無法判定三態，並依規則抽好「人工」檢查的樣本（`manual/`）。`--fixture` 另比對 `EXPECTED`、對無資料的 9204 跑個股檢查，且無法判定也算失敗；`--g7` 在程式不是 origin/master 上已 commit 的版本時拒跑。輸出 `summary.md`、`status.md`、`results.json`、`api/`、`shots/`、`manual/`，有失敗 exit 1（[已知失敗](../.claude/skills/verify-stock-lab/features/README.md#已知失敗)除外），features 不一致或 `--g7` 不符 exit 2。preview 用 `tools/verify/vite.preview.mjs`（`VERIFY_DIST`、`VERIFY_WEB_PORT`、`VERIFY_API_URL`）。CI `verify` job 以假資料庫跑 `verify_plan.py` 選出的頁（每晚與手動觸發是五頁全套），結果與截圖上傳成 artifact `verify-<attempt>` |
| `python tools/research/backtest_research.py --db <副本 stock.db> --start YYYY-MM-DD --end YYYY-MM-DD [--ablate all\|<策略>:<條件> ...] [--no-canonical] [--min-free-gb 10] [--force]` | 研究回測（[#318](https://github.com/YiCheng0608/stock-lab/issues/318)）：canonical 策略加上 `--ablate` 列出的 ablation（`app.strategies.ablation`，例如 `breakout_v1:group`）在同一次重播中評估，每檔每日的輸入只建一次。會寫入 `--db`（signals、settlements、`run_type=backtest` 的 run），所以只對 `copy_db.py` 的副本跑。`--db` 在 `stock-lab-data` 或 `STOCK_DATA_DIR` 內、與正式 `stock.db` 是同一個檔案（含 hard link，以 `os.path.samefile` 比對）、台北 18:30～21:30、或可用實體記憶體低於 `--min-free-gb` 時，不載入程式直接 exit 2。重播中每個交易日與每批追蹤 commit 後再查一次時段，進入 18:30 就停下，run 記 `failed`（`BacktestPaused`），exit 3 並在 `rerun` 印出接續的命令（同樣參數、不帶 `--force`）。重跑從頭重播，已 commit 的列覆寫成相同結果，所以起跑時間加預估耗時（12 個月約 5.4 小時）最好不跨進 18:30。印出 run、registry、migration 與重播秒數、峰值 working set、WAL 最大值（每 5 秒取樣），以及各策略的訊號、狀態與 settlement 數 |
| `python tools/verify/freeze_candidates.py [--check]` | 以現行 `worker.candidates` 重算假資料的每日候選並寫回 `tools/verify/fixture_candidates.json`；`--check` 只比對（後端測試會跑），改訊號、族群或候選評分後要重跑 |

## 6. 排程

每日排程由排程器定時執行一條命令：`python -m worker.cli job daily` 與 `python -m worker.cli job news`（news 之後接著 `worker.cli news-llm`）（[ROADMAP V1-G1](ROADMAP.md#v1-範圍基線2026-10-17-核定)）。job（[`backend/worker/job.py`](../backend/worker/job.py)）自己負責單一執行個體（檔案鎖）、起跑前檢查、單次上限、日誌與保留，不依賴排程器的設定，換排程器只要定時執行同一條命令。job 只在 Linux（[後端 image](#1-工作目錄環境與啟停)）執行（#333）；本機目前仍是 Windows 工作排程器，在 Docker 切換（#331 子任務 10）前保留，註冊、查詢、停用與移除見 [§6.2](#62-dailynews-工作的註冊與管理)，日誌與 run 記錄見 [§6.3](#63-日誌與-run-記錄)；接手它的 scheduler 容器（`worker.cli serve`）與切換前提見 [§6.6](#66-scheduler-容器的排程serve)。自動下單不在第一版範圍。

位置（使用者 2026-10-17 決定）：正式資料目錄 `C:/Users/YiCheng/stock-lab-data/`（`stock.db`、`raw/`、`logs/`），以 `STOCK_DATA_DIR` 指向；排程只從發佈 checkout `C:/Users/YiCheng/stock-lab-release/`（repo 的獨立 clone，跟著發佈 branch，排程起跑前 `git pull --ff-only`）及其 `.venv` 執行，不從 `master` 管理 checkout。統籌心跳檔、換手標記與壓縮計數檔都在資料目錄的 `logs/` 下（[工作手冊](GITHUB_WORKFLOW.md#統籌-session)）。

新聞任務與 `daily` 分開排程，不掛在 `daily` 之後：

- **頻率**：每 2 小時執行一次 `python -m worker.cli news`，環境變數（`STOCK_*`、`PYTHONPATH`）與 `daily` 相同。feed 只保留最近 10～65 則，間隔拉長會漏稿（見[新聞來源限制](DATA_SOURCES.md#新聞來源)）。
- **rate limit**：每次 9 個請求、間隔 2 秒，一天約 108 個請求；不重試，限流或失敗的 feed 等下一輪。
- **冪等**：重跑或兩輪重疊抓到同一則時，不新增列、不改寫既有列。
- **錯誤**：每個來源的結果寫入 `run_type=news` 的 ingestion run，可用 `/api/ingestion-runs?q=news` 查；CLI 也把同一份結果以 JSON 印到 stdout，排程把 stdout／stderr 導到日誌檔保存（[§6.3](#63-日誌與-run-記錄)）。
- **LLM 判讀**：`\stock-lab\news` 每輪在 `worker.cli news` 結束後，於同一次執行接著跑 `python -m worker.cli news-llm`（環境變數相同、不帶 `--date`），把新收的新聞做 AI 摘要與判讀。每輪最多 50 則（2 次 `sonnet` 呼叫，25 則一批實測約 32 秒），同一台北日所有 run 合計最多 20 次呼叫，超過的批次等下一個台北日（[§3](#3-現有-worker-cli)）。
  - news 失敗時仍會跑（news-llm 只讀已入庫的新聞）；news-llm 失敗不改變 news 的結果，也不改變工作的結束碼。失敗只留在日誌的 news-llm 段落與 `run_type=news_llm` 的 ingestion run（`status=failed`、`error` 寫原因），可用 `/api/ingestion-runs?q=news_llm` 查；日誌格式見 [§6.3](#63-日誌與-run-記錄)。
  - 執行機器須已登入 Claude Code 且環境沒有 `ANTHROPIC_API_KEY`／`ANTHROPIC_AUTH_TOKEN`（有就拒絕執行）。排程環境的 PATH 與互動 shell 不同，所以註冊時以 `-ClaudeCli` 寫入原生 `claude.exe` 的完整路徑（[§6.2](#62-dailynews-工作的註冊與管理)）。執行期不檢查副檔名：後端 image 的 `claude` 是 npm 套件安裝的原生檔（ELF，`@anthropic-ai/claude-code/bin/claude.exe`），不是 shim；#333 移除了 Windows 只收原生 `.exe` 的檢查。找不到 claude、未登入或額度用盡時，當輪記 `failed`（或該批 `pending`）並停止，下一輪重試。
  - 看門狗在最近 3 批判讀都是 `pending`，或最近 3 筆 news_llm run 都是 `failed`（找不到 claude、API 金鑰這類沒有批次的設定錯誤，以及被逾時終止的 run），或 news 日誌最後 3 次 `news_llm_exit` 都是 `1`／`wrapper_error` 時留言（[§6.1](#61-排程看門狗)）。
  - **停用／恢復**：只停 news-llm 用 `-NoNewsLlm` 重新註冊 news（[§6.2](#62-dailynews-工作的註冊與管理)）；整個 news 停用用 `Disable-ScheduledTask`。額度吃緊時先停 news-llm，news 照常收稿。

### 6.1 排程看門狗

`tools/ops/watchdog.sh`（Git Bash）每 15 分鐘由工作 `\stock-lab\watchdog` 執行，只檢查排程與資料不變量：以檔案與唯讀 DB 判定異常並在 [#1](https://github.com/YiCheng0608/stock-lab/issues/1) 留言「待使用者」，每個異常每台北日最多一則。不判定統籌是否在線、不開或喚醒統籌（統籌開啟見[工作手冊](GITHUB_WORKFLOW.md#統籌-session)）。

- `daily`：週一至週五台北 21:30 後，當日 `logs/daily-YYYYMMDD.log` 不存在或沒有 `end` 列。
- `daily` 結果：週一至週五台北 22:00 後（21:30 那次已寫入 run 列）唯讀查當日目標的 `schedule_runs`：當天有 `success`／`non_trading_day` 就算完成（之後的 `skipped` 不影響）；否則取最後一筆（略過只指向別列的 `already_complete`／`already_running`），是 `partial`、`failed`、`non_trading_unconfirmed` 或 `skipped:<原因>`（例如 `low_memory`）就留言；仍在 `running` 的等下一輪，超過 2.5 小時視為 `failed`；當日 success 但 catchup 沒補齊（`catchup_incomplete`）也留言；有日誌卻沒有任何 run 列（worker 沒能啟動）也留言。
- `news`：最新的 `logs/news-*.log` 已超過 6 小時（連續 3 次）沒有更新。
- `news_llm`：`stock.db` 最近 3 批判讀都是 `pending`；或 24 小時內最近 3 筆 `run_type=news_llm` 都是 `failed`（`running` 超過 90 分鐘也算）；或 news 日誌（今昨兩天的檔）24 小時內最後 3 個 `news_llm_exit=` 都是 `1`／`wrapper_error`（涵蓋表不存在等不寫 run 的失敗）。後兩者合為一則 `news_llm_failed` 留言；限 24 小時是為了 news 停擺後不再每天就舊失敗留言，停擺本身由上一條 `news` 判定。
- 資料不變量（每輪、不分時段，唯讀查 `stock.db`；各條數字印在 stdout，`--dry-run` 可看）：
  - `invariant_future_date`：`market_bars` 最新 `trading_date` 晚於台北今日。
  - `invariant_bar_provenance`：最新 `trading_date` 的 `market_bars` 有 `source` 為 `unknown`／空，或 `data_as_of` 為空。
  - `invariant_llm_provenance`：`news_llm_results` 中 `llm_status=done` 的列沒有 `llm_model`，或 `prompt_version` 為空。
  - `invariant_execution_calendar`：最新一個 analysis 訊號日有訊號沒有規則最早執行日（`earliest_execution_date` 為空）；原因是官方休市表缺該年度（例如年底時明年還沒公告），或 trading_calendar 步驟失敗而表內沒有該年度。只看改用休市表之後寫入的訊號（evidence 有 `execution.calendar`）：DB 還沒有 `trading_calendar_days`（0020 以前）時印 `skip reason=no_trading_calendar`；升到 0020 後、第一次新的 analyze 之前，最新訊號日還是舊訊號（不回填，永遠為空）時印 `skip reason=signals_before_calendar`，不留言。處置：看該日 analyze 步驟 `details_json.execution_calendar`（`reason`、`missing_year`）與 trading_calendar 步驟，官方公告後跑 `python -m worker.cli trading-calendar`，之後的訊號就有日期；已存的訊號不回填（[V1_SPEC](V1_SPEC.md#價位etf-與生命週期)）。
  - `invariant_strategy_levels`：最近一次已結束的 daily run 的 `strategy_levels` 步驟不是 `success`／`no_data`／`skipped`（#274）。這一步失敗不改 run 狀態（[§6.3](#63-日誌與-run-記錄)），只有這條會讓人知道個股頁策略總表的觀察價位沒更新；`skipped`（analyze 沒成功）由 daily 本身的異常回報，不重複留言。DB 沒有 `schedule_run_steps` 或還沒有任何含這一步的 run（0019 以前、或發佈 branch 沒有這一步）時印 `skip`。處置：看該 run 的步驟列 `error`，修好後跑 `python -m worker.cli strategy-levels --date <目標日>`。這條判的是步驟列，不是資料：手動補算不會改那一列，所以留言（每台北日一則）會持續到下一個交易日的 daily 該步驟成功、成為最近一次的步驟列才停（例：週五失敗、週五晚上補算，週六、週日仍各留一則），補算後的留言可略過。
  - `invariant_status_sync`：某交易所最近一次[標的狀態同步](DATA_SOURCES.md#標的狀態同步)（`data_quality` 的 `instrument_status_sync`）是 `skipped`，也就是官方清單缺席（absent）與 60 個交易日沒有行情列（dormant）的現行標的合計超過該交易所的 5%（至少 5 檔），整批沒有改；留言與 warning 分別寫出兩者的檔數。collect 仍是 `success`，warning 記在 run 的 `noncore_warnings` 與 `instrument_status_sync`。
  - 處置：看門狗不修資料，違反持續存在就每台北日留言一則。前兩條查該日 daily 日誌與 `/api/ingestion-runs`，修好寫入端後依 [§6.4](#64-重跑與回補) 重跑或回補該日；第三條查 news 日誌的 news-llm 段落。`invariant_status_sync` 由統籌處理，步驟如下：
    1. 看該日 collect run 的 `instrument_status_sync.exchanges.<交易所>` 的 `absent_symbols` 與 `dormant_symbols`。
    2. 清單是暫時不完整時（例如官方 payload 截斷），下一次 daily 同步成功後自動恢復，不需處理。
    3. 核對官方公告確認真的有大量下市或轉市時，停用排程，執行 `instruments repair --apply --max-status-share <比例>`，再恢復排程；比例、依據與輸出記在該 Issue。修正資料前先備份 `stock.db`（[§2.1](#21-安全升級與復原順序)）。`market_bars` 不存在或沒有資料時前兩條印 `skip`，`news_llm_results` 不存在時第三條印 `skip`，都不留言。

`daily`／`news` 還沒有任何日誌時不判定（排程尚未註冊）。執行環境：Git Bash、PATH 上有已登入的 `gh`；Python 只用來唯讀查 DB（找不到時跳過 daily 結果、`news_llm` 與資料不變量的 DB 檢查，日誌檢查照做），預設發佈 checkout 的 `.venv`。以下命令在發佈 checkout 執行：

| 動作 | 命令 |
| --- | --- |
| 預覽 | `powershell -ExecutionPolicy Bypass -File tools/ops/Register-Watchdog.ps1 -WhatIf` |
| 註冊或更新 | `powershell -ExecutionPolicy Bypass -File tools/ops/Register-Watchdog.ps1`（`-DataDir`、`-PythonPath` 預設 `STOCK_DATA_DIR`、`.venv`；`-DryRun` 註冊只判定不留言的版本，用來以 `Start-ScheduledTask -TaskPath \stock-lab\ -TaskName watchdog` 驗證排程環境） |
| 查詢 | `schtasks /query /tn "\stock-lab\watchdog" /v /fo list` |
| 停用／啟用 | `Disable-ScheduledTask -TaskPath \stock-lab\ -TaskName watchdog`／`Enable-ScheduledTask ...` |
| 移除 | `powershell -ExecutionPolicy Bypass -File tools/ops/Register-Watchdog.ps1 -Unregister` |
| 手動判定 | `bash tools/ops/watchdog.sh --dry-run`（只輸出將留的言與資料不變量的數字） |

工作以目前使用者、Interactive logon、隱藏執行，登入時才跑；同時只跑一個，10 分鐘逾時。日誌 `<資料目錄>/logs/watchdog.log`，每列為 UTC 時間、事件、`key=value` 與說明，沒有異常時記 `schedules_ok`；異常留言（每日一則）的頻率限制以此日誌判斷。同一時間只跑一個：Python 以 job 的同一套檔案鎖（`python -m worker.job lock`）持有 `<資料目錄>/locks/watchdog.lock` 並把腳本當子程序再跑一次，鎖由作業系統在 Python 結束時釋放（被強制終止也一樣，子程序一起結束），下一輪不必等；另一輪仍在跑時記 `locked` 並略過。找不到 Python 時不取鎖（排程的「前一次未結束不另起」仍擋重疊）。舊版的 `logs/watchdog.lock/` 目錄不再使用；DB 檢查因缺 Python 或讀 DB 失敗而沒跑時記 `python_missing`／`daily_check_failed`／`news_llm_check_failed`／`invariants_check_failed`，不記 `schedules_ok`。腳本路徑寫在工作參數裡，腳本改名或搬移後要在發佈 checkout 重跑「註冊或更新」。舊版（含開統籌）的日誌 `logs/ensure_coordinator.log` 不再寫入。

### 6.2 daily／news 工作的註冊與管理

三個位置（使用者 2026-10-17 決定，見本節開頭）：

| 位置 | 路徑 | 說明 |
| --- | --- | --- |
| 資料目錄 | `C:/Users/YiCheng/stock-lab-data/` | 正式 `stock.db`、`raw/`、`logs/`，與 job 的鎖 `locks/`。排程以 `--data-dir`（註冊參數 `-DataDir`）傳入並設成 worker 子程序的 `STOCK_DATA_DIR`（預設依序為 `STOCK_DATA_DIR`、`%USERPROFILE%\stock-lab-data`），不由 cwd 推導。 |
| 發佈 checkout | `C:/Users/YiCheng/stock-lab-release/` | repo 的獨立 clone，跟著發佈 branch：平常是 `master`；版本驗收窗口（V1 G7）期間是 `release/v1`，master 合併的新版本改動不會進排程；V1 的改動以 PR 進 `release/v1`（受 ruleset 保護，[工作手冊](GITHUB_WORKFLOW.md#任務流程)第 6 步，使用者 2026-10-26 決定）。排程**只**從這裡執行，不從 `master` 管理 checkout 或任務 worktree。每次執行先 `git pull --ff-only`（拉目前 branch 的 upstream）。切換：`git fetch origin` 後 `git checkout -b release/v1 --track origin/release/v1`，回到平常用 `git checkout master`；兩者都在排程沒在跑時做，`git status -sb` 核對。 |
| Python | `C:/Users/YiCheng/stock-lab-release/.venv` | 依發佈 branch 的 `backend/validation-requirements.lock.txt` 安裝；發佈 branch 收到依賴變更（或切換發佈 branch）後由統籌在排程閒置時重裝。窗口期間 master 上的依賴變更不裝進這個 venv。預設依序為 `-PythonPath`（別名 `-Python`）、`STOCK_PYTHON`、發佈 checkout 的 `.venv`。 |

首次建立：`git clone` 到發佈 checkout，建 `.venv` 並安裝依賴；以 SQLite backup API 把已初始化的 DB 複製成資料目錄的 `stock.db`（有 WAL 時不裸複製主檔），再於發佈 checkout 註冊工作。daily 開頭只在 DB 的 Alembic revision 不是程式 head 時才跑 `init_db`（含整庫 migration 完整性檢查，多年 DB 上要數分鐘）；已在 head 時直接開始。

以下命令在發佈 checkout 執行（`<py>` 為發佈 checkout 的 `.venv\Scripts\python.exe`，`<data>` 為資料目錄）：

| 動作 | 命令 |
| --- | --- |
| 預覽（不改系統） | `powershell -ExecutionPolicy Bypass -File tools/Register-WorkerSchedule.ps1 -Job daily -Python <py> -DataDir <data> -WhatIf`（news 把 `-Job` 換成 `news`；輸出的 `Command:` 列就是工作排程器會執行的完整命令，`WorkDir:` 是它的工作目錄 `backend`） |
| 註冊或更新 | 同上去掉 `-WhatIf`；同名覆寫 |
| 查詢 | `schtasks /query /tn "\stock-lab\daily" /v /fo list`；`Get-ScheduledTaskInfo -TaskPath \stock-lab\ -TaskName daily`（上次執行時間與結果、下次執行時間） |
| 手動觸發 | `Start-ScheduledTask -TaskPath \stock-lab\ -TaskName daily`（與排程完全相同的環境） |
| 停用／啟用 | `Disable-ScheduledTask -TaskPath \stock-lab\ -TaskName daily`／`Enable-ScheduledTask ...` |
| 移除 | `powershell -ExecutionPolicy Bypass -File tools/Register-WorkerSchedule.ps1 -Job daily -Unregister` |
| 不經排程執行一次 | 在 `backend` 目錄 `<py> -m worker.cli job daily --data-dir <data> --trigger manual [--date YYYY-MM-DD] [--force] [--claude-cli <claude.exe>]`（`--min-free-memory-gb` 預設 8）；news 另可加 `--claude-cli <claude.exe>`、`--skip-news-llm`，`--date` 只給 news（news-llm 的 `--date` 是篩選，不帶）。`tools/Invoke-WorkerJob.ps1` 只把舊參數（`-Job`、`-GitPull`、`-MinFreeMemoryGB`…）轉成這條命令，留給 #313 前註冊、還沒重新註冊的工作 |
| news 的 news-llm | 註冊 news 時指定 `-ClaudeCli <原生 claude.exe>`；未給時依序取 `STOCK_CLAUDE_CLI`、PATH 上第一個 `claude.exe`，都沒有或是 `.cmd` shim 就拒絕註冊。停用：同一條註冊命令改加 `-NoNewsLlm`（工作內為 `--skip-news-llm`）；恢復：去掉 `-NoNewsLlm` 再註冊一次。 |
| daily 的 candidate_notes | 註冊 daily 時加 `-ClaudeCli <原生 claude.exe>`（只認明確參數，不查 `STOCK_CLAUDE_CLI` 或 PATH；不存在或不是 `.exe` 就拒絕註冊），工作內以 `--claude-cli` 交給 job、再以 `STOCK_CLAUDE_CLI` 傳給 worker。未加時照常註冊，`Claude:` 列顯示 `(not set; …)`，該步驟依序用工作環境的 `STOCK_CLAUDE_CLI`、PATH 上的 `claude`，都找不到或找到的不是 `.exe` 就記 `cli_not_found`、不呼叫，daily 結果不受影響。 |

| 工作 | 觸發 | 動作 |
| --- | --- | --- |
| `\stock-lab\daily` | 週一至週五台北 18:30，21:30 再跑一次（`-TaipeiTimes` 可改） | `<py 同目錄的 pythonw.exe> -m worker.cli job daily --trigger scheduler --data-dir <data> --log-dir <data>/logs --min-free-memory-gb 2 --git-pull [--claude-cli <claude.exe>]`（註冊參數 `-DailyMinFreeMemoryGB`、`-ClaudeCli`），單次上限 2.5 小時 |
| `\stock-lab\news` | 每天每 2 小時（`-IntervalHours`），從下一個整點區間開始 | 同上換成 `job news`、`--min-free-memory-gb 1`、`--claude-cli <claude.exe>`（註冊參數 `-NewsMinFreeMemoryGB`；`-NoNewsLlm` 時改為 `--skip-news-llm`）：先 `news`、再 `news-llm`，兩者合計單次上限 90 分鐘 |

兩個工作都以目前使用者、互動式登入、一般權限執行，不存密碼，使用者登入時才跑；錯過的時段在登入後補跑（StartWhenAvailable）。工作執行 `pythonw.exe`（沒有主控台視窗；venv 沒有時用 `python.exe`），job 再以 `python.exe` 無視窗啟動 worker。單一執行個體與單次上限由 job 保證（[§6.3](#63-日誌與-run-記錄)）；工作排程器另設「前一次未結束不另起」與比 job 上限多 10 分鐘的上限，當第二道防線。主機不在台灣時區時腳本自動換算本機時間。

休市日不寫進觸發：週間無交易日時官方來源回 no-data。當日目標第一次兩市都回 no-data（通常是 18:30）記 `non_trading_unconfirmed`，不算完成；21:30 再問一次仍是 no-data 才記 `non_trading_day`，這次有行情就照常跑完。目標日早於今日（手動補跑過去日期）時一次 no-data 即記 `non_trading_day`。三大法人與融資公布時間晚於收盤且不固定，18:30 若因缺這些資料而 collect 為 `partial`，analyze 不會執行，由 21:30 補齊；當日已完成後的 21:30 只記一列 `skipped`（`already_complete`）。

**單一執行個體與起跑前檢查**（job）：同一資料目錄的同種 job 以 `<data>/locks/<job>.lock` 的檔案鎖（`fcntl`）一次只跑一個，鎖由作業系統在 job 結束時釋放，被強制終止也不殘留；拿不到鎖記 `already_running`（daily 只在 DB 已是程式 head 時於 `schedule_runs` 留列；不是 head 時持鎖的 daily 可能正在 migrate，migration 在同一個交易裡先讀數分鐘再寫，期間別的連線寫入一列就會讓它失敗，所以只記日誌與 JSON 結果的 `error`）。拿到鎖後：可用實體記憶體（`/proc/meminfo` 的 `MemAvailable`，不用 WMI，#246）低於 `--min-free-memory-gb`（直接執行時預設 8；註冊時 daily 2、news 1）記 `low_memory`；這個 checkout 有 `index.lock` 或 `MERGE_HEAD` 記 `git_busy`；`--git-pull` 時 `git pull --ff-only` 失敗記 `git_pull_failed`（#314 改為讀 tag 前暫留）。這些都不執行 worker，等下一次觸發；daily 另在 `schedule_runs` 留一列 `skipped` 與原因，news 只寫日誌。全市場 analyze＋evaluate＋candidates＋indicators 峰值約 0.3 GB（[§6.5](#65-限制)），daily 門檻 2 GB 保留 collect 與其他程式的餘裕；2026-10-18 前註冊的工作仍是 6，要在發佈 checkout 重跑「註冊或更新」才生效。

### 6.3 日誌與 run 記錄

- **日誌**：`<data>/logs/daily-YYYYMMDD.log`、`<data>/logs/news-YYYYMMDD.log`（台北日期），排程失敗時先看這裡。每次執行追加開始列（含可用記憶體）、`git pull` 輸出、跳過原因（`===== skipped reason=<原因> (…)`，`already_running` 時括號內是鎖檔）、CLI 的 JSON 結果（stdout）、stderr 與結束列 `===== <時間> end exit=<code> seconds=<秒>`（[§6.1](#61-排程看門狗) 的看門狗以此判定 daily 是否完成）。保留 90 天（`--log-retention-days`），只清同名前綴的檔案。job 本身出錯時記 `wrapper error`，工作排程器「上次執行結果」為非 0；job 被強制終止時日誌只有開始列、沒有結束列。
  - **單次上限**：daily 2.5 小時；news 90 分鐘，news 與 news-llm 合計（`--time-limit-minutes` 可改）。到時 job 結束 worker 與它啟動的程序（程序群組），記 `--- timeout: killed at the <分> minute limit of the <job> job (exit=1)`（news 段落前加 `news ` 或 `news-llm `），該步驟的碼記 1；news 用完時間時 news-llm 不啟動，記 `--- news-llm timeout: not started …`。job 被強制終止時 worker 也一起結束（以 PR_SET_PDEATHSIG，只保證 worker 本身），所以 run 列的 PID 已不存在，下一次執行立即把它記 abandoned（見下表 `failed`）。
  - **news 日誌的分段**：`--- news stdout`／`--- news stderr`／`--- news end exit=<碼> seconds=<秒>`，接著 `--- news-llm start claude_cli=<路徑>`、`--- news-llm stdout`／`stderr`、`--- news-llm end exit=<碼> seconds=<秒>`；結束列為 `===== <時間> end exit=<news 的碼> seconds=<秒> news_llm_exit=<碼>`，`news_llm_exit` 另有 `disabled`（`--skip-news-llm`）、`not_run`（起跑前檢查未通過或另一個 news job 持有鎖）、`timeout`（news 用完單次上限，news-llm 未啟動）、`wrapper_error`（job 啟動 news-llm 失敗）。daily 日誌格式與 #313 前的包裝腳本相同。
- **exit code**：daily 0＝`success`／`skipped`／`non_trading_day`／`non_trading_unconfirmed`，2＝`partial`，1＝`failed`；工作排程器的「上次執行結果」即此值。news 工作的碼是 `worker.cli news` 的碼；`worker.cli news-llm` 的碼（0＝`success`／`skipped`，2＝`partial`，1＝`failed`）只記在日誌的 `news-llm end` 與 `news_llm_exit`，不影響工作的碼。
- **run 記錄**：`schedule_runs` 每次 daily 執行一列（目標日、觸發來源、開始／結束、狀態、錯誤、collect 筆數、摘要），`schedule_run_steps` 每步一列（catchup／collect／trading_calendar／analyze／evaluate／candidates／indicators／theme_suggestions／plan_tracking／strategy_levels／candidate_notes 的開始／結束、狀態、錯誤、處理筆數，collect 另連 `ingestion_runs.id`；catchup 的 `details_json` 列出檢查與補抓的日期及各日結果）。查詢：`python -m worker.cli schedule-runs --date YYYY-MM-DD`。news 的結果在 `run_type=news` 的 ingestion run，news-llm 的在 `run_type=news_llm`（`metadata_json` 記每批則數、耗時、模型與 token 用量）。

| run 狀態 | 意義 |
| --- | --- |
| `success` | collect、analyze、evaluate、candidates、indicators、theme_suggestions、plan_tracking 都成功（或該步驟回 `no_data`；沒有任何追蹤計畫時 plan_tracking 是 `success`、0 筆）；trading_calendar、strategy_levels 與 candidate_notes 的狀態不列入，`success` 的定義不因新增 trading_calendar、strategy_levels 步驟而改變（G7 起的判定照舊）。catchup 沒補齊不改變 run 狀態，記在該步驟與 `summary_json.steps.catchup`，由看門狗留言。 |
| `partial` | collect 有缺（例如籌碼尚未公布）；後續步驟記 `skipped`，錯誤欄列 collect 警告。 |
| `non_trading_day` | 官方來源明確回報該週間日無交易，且已確認（當日目標要兩次觸發都回 no-data）。 |
| `non_trading_unconfirmed` | 當日目標第一次回 no-data，等下一次觸發確認；不算完成，exit code 0。 |
| `failed` | 某步驟失敗或拋例外；錯誤欄記步驟與訊息，依賴它的步驟記 `skipped`（evaluate 與 candidates 依賴 analyze；trading_calendar、indicators、theme_suggestions 與 plan_tracking 只依賴 collect；strategy_levels 依賴 analyze；candidate_notes 依賴 candidates）。run 列記錄執行的主機與 PID；由 job 持鎖啟動的 run 列另記鎖的路徑（`summary_json.runtime.job_lock`），下一次拿到同一把鎖的 daily 不看主機與 PID，立即把它記 `failed`（`abandoned: process <PID> on <主機> no longer holds <鎖>`）：重建的容器 hostname 不同，PID 也可能被新程序重用（#336）。其餘的列：同主機的新執行發現該 PID 已不存在（例如被系統終止）時，立即把舊列改記 `failed`（abandoned）並照常執行；其他情況要超過 2.5 小時（與排程單次上限相同，小於 18:30 與 21:30 的間隔）仍為 `running` 才記 abandoned，在那之前同日的新執行記 `skipped`（`already_running`）。 |
| `skipped` | 同目標日已有 `success`／`non_trading_day`（`already_complete`）、另一次執行仍在進行（`already_running`：run 列仍在 running，或 job 拿不到鎖，後者 `related_run_id` 指向當時 running 的列、沒有則為空；DB 不在 head 時不寫列，見 [§6.2](#62-dailynews-工作的註冊與管理)），或起跑前檢查未通過（`low_memory`／`git_busy`／`git_pull_failed`）；不碰資料。 |

trading_calendar 步驟呼叫 `worker.trading_calendar.run_trading_calendar(目標日)`，在 collect 成功後、analyze 之前執行，抓目標日的年度與下一年度的[官方休市表](DATA_SOURCES.md#交易日曆)（2 個請求），供 analyze 推算訊號的[規則最早執行日](V1_SPEC.md#價位etf-與生命週期)。寫入列數記在步驟列的 `records`，`details_json.years` 記各年度結果。它的任何狀態（`failed`、`partial`、例外）都只記在該步驟列（原因寫在 `error`，例如 `holiday schedule 2027 unavailable: …`）與 `summary_json.steps`，**不改變 run 狀態與 exit code**；analyze 照跑並使用表內已有的日曆，日曆答不出來時訊號的日期留空，analyze 步驟的 `details_json.execution_calendar` 記 `status`（`available`／`unavailable`）、`reason`、`missing_year`、`next_session` 與 `signals_without_date`，看門狗以 `invariant_execution_calendar` 留言（[§6.1](#61-排程看門狗)）。休市日 collect 為 skipped 時它也記 `skipped`。手動更新：`python -m worker.cli trading-calendar`（[§3](#3-現有-worker-cli)）。

indicators 步驟呼叫 `worker.indicator_batch.run_indicator_batch(目標日)`；只要 collect 成功就執行（analyze 失敗也跑），失敗時 run 記 `failed`、錯誤欄記 indicators 訊息。

candidates 步驟呼叫 `worker.candidates.run_candidates(目標日)`，只讀當日訊號、籌碼、族群榜與新聞，不改行情、訊號與追蹤；失敗時 run 記 `failed`（exit code 1，看門狗與排程異常處理照 `failed` 處置）、錯誤欄記 candidates 訊息，indicators 照跑。行情與訊號已寫入，只需重跑候選：`python -m worker.cli candidates --date YYYY-MM-DD`（不需 `daily --force`）。

theme_suggestions 步驟呼叫 `worker.theme_suggestions.run_theme_suggestions`，只讀 `news_llm_results`／`news_items` 與 active 族群名稱，重算[新聞題材建議](V1_SPEC.md#新聞題材建議)；collect 成功就執行（analyze 失敗也跑），失敗時 run 記 `failed`、錯誤欄記 theme_suggestions 訊息，其他步驟的結果不變。只需重算建議：`python -m worker.cli theme-suggestions`。休市日 daily 不跑後續步驟，該日新聞的建議在下一個交易日彙整（每次都由全部判讀重算，不會漏）。

plan_tracking 步驟呼叫 `worker.plan_tracking.run_plan_tracking(目標日)`，在 theme_suggestions 之後、candidate_notes 之前執行（candidate_notes 可能跑很久），只讀日線、公司行動、停牌事件與計畫自己的價位快照，更新[使用者追蹤計畫](V1_SPEC.md#使用者追蹤計畫)；collect 成功就執行（analyze 失敗也跑），失敗時 run 記 `failed`、錯誤欄記 plan_tracking 訊息，其他步驟的結果不變。只需重算計畫：`python -m worker.cli track-plans --date YYYY-MM-DD`。`schedule_run_steps` 以 run 與步驟名稱找列，`sequence` 只用來排序（trading_calendar 為 2、analyze 為 3，plan_tracking 為 8、strategy_levels 為 9、candidate_notes 為 10；之前的 run 維持寫入當時的號碼）。

strategy_levels 步驟呼叫 `worker.strategy_levels.run_strategy_levels(目標日)`，在 plan_tracking 之後、candidate_notes 之前執行，analyze 成功（含 `no_data`）才跑，否則記 `skipped`（`analyze_not_successful`）；為當日 analysis 訊號寫[條件價位](V1_SPEC.md#strategy_levels_v1)，只讀已存資料、不改訊號、候選與追蹤，處理的訊號數記在步驟列的 `records`，`details_json` 有寫入列數與 `availability` 分佈。它的任何狀態（`failed`、`partial`、例外）都只記在該步驟列與 `summary_json.steps`，**不改變 run 狀態與 exit code**，不觸發 daily 失敗的看門狗；失敗由看門狗的資料不變量 `invariant_strategy_levels`（[§6](#6-排程)）回報，個股頁策略總表對沒有條件價位列的觀察訊號顯示「觀察價位未產生」（#274）。daily 已 success 後不會重跑，補算或重算以 `python -m worker.cli strategy-levels --date YYYY-MM-DD`（[§3](#3-現有-worker-cli)）。

candidate_notes 步驟呼叫 `worker.candidate_notes.run_candidate_notes_batch(目標日)`，在 candidates 成功（含 `no_data`）後最後執行，為當日候選寫 [AI 進出點說明](V1_SPEC.md#候選-ai-進出點說明)；最多 4 次 `claude -p`，各 300 秒逾時（實測一次約 7 秒）。它的任何狀態（`success`／`partial`／`failed`／`skipped`／`no_data`，含找不到 claude、未登入、額度用盡、逾時與例外）都只記在該步驟列與 `summary_json.steps`，**不改變 run 狀態與 exit code**，也不觸發看門狗；candidates 不成功時記 `skipped`（`candidates_not_successful`）。daily 已 success 後 21:30 那次不會重跑，`pending` 或未說明的候選以 `python -m worker.cli candidate-notes --date YYYY-MM-DD` 補（只送未完成者）；結果查 `/api/ingestion-runs?q=candidate_notes` 或步驟列。

### 6.4 重跑與回補

- **手動重跑**：見 [§6.2](#62-dailynews-工作的註冊與管理)「不經排程執行一次」，或直接 `python -m worker.cli daily --date YYYY-MM-DD`。已完成的日期加 `-Force`／`--force` 才會再跑各步驟。
- **漏日補抓**：每次 daily 在 collect 目標日前跑 catchup：從目標日前一天往回取最近 5 個不是確定休市的週間日（確定休市＝該日的 daily run 記過 `non_trading_day`，或 collect 的 no-data 是在該台北日結束後才取得；只有當天一次 no-data、21:30 沒再確認的 `non_trading_unconfirmed` 日仍列入補抓，避免誤報的休市永遠補不回），最多回看 15 個週間日；其中沒有 collect success（含 TAIEX）的日期，由舊到新以回補的單日路徑（`pipeline.collect(日期, adapter=OfficialMarketDataAdapter(snapshot_feeds=False))`，只抓日期範圍的官方資料，不抓當日快照）補抓；歷史路徑不查 MOPS，所以重抓已有 snapshot collect 的日期時沿用該 request 已存的 `event_coverage` 與 `mops_events`／`mops_fundamentals` 資料品質列，不退成歷史預設。補過的日期之後不再抓；補抓失敗的日期下一次 daily 再試，超出 5 個交易日窗口就不再自動補，看門狗會在失敗當晚留言，改用下面的手動回補。catchup 只補 collect，不補跑過去日期的 analyze／evaluate／candidates；指標由當日 indicators 步驟依[指標規則](#3-現有-worker-cli)處理，補到的日線影響最後一列以外時跑 `indicators --rebuild`。
- **主檔外的行情列**：官方行情表裡的普通股代號（4 位數、非 0 或 91 開頭），即使不在當天的官方清單，也照樣寫入 DB 中同交易所、同代號的既有標的（例如已下市或已轉市的舊標的）。DB 沒有該標的時不建立，記一列 `data_quality`（`entity_type=unmatched_bar`，`entity_key=交易所:代號`，`as_of_date` 為 collect 目標日，checks 列交易日、來源與 raw id）與 run metadata 的 `unmatched_bars`，並加一則 notice；collect 狀態不變。這類代號的歷史可用 `instruments repair --include-delisted` 補回（[§3](#3-現有-worker-cli)）。
- **冪等**：collect 對同一 request 已有 `success` 時直接重用、不發請求；重新擷取時，既有日線與籌碼只補空欄，不覆寫已存的非空值，不一致的值保留原值並記在該 collect run metadata 的 `value_conflicts`。只補空欄時該列的 `raw_payload_id`、source、data_as_of、collected_at 不變（仍指向原值的 capture），補了哪些欄位與新 capture 的 raw id 記在 `value_fill_groups`（依表、交易所、日期、欄位、raw id 分組列代號，同一 request 的多次執行累加）。只有 `collect(force=True)` 會覆寫，覆寫時指向新 capture。
- **回補**：`python -m worker.cli backfill --start-date <起> --end-date <迄> --scope market`。中斷後以相同起訖重跑即從各段 manifest 續做；輸出列出每段 run id、`partial_dates`／`failed_dates`（缺日，不補值）與 `skipped_non_trading_dates`（官方無交易）。回補或更正舊日線後跑 `python -m worker.cli indicators --rebuild` 重算指標。
- **限流**：`fetch_json` 對同一官方主機保持最小間隔（`www.twse.com.tw` 2.5 秒，其餘官方主機 1 秒），另有 429／5xx／暫時性 307 的有界重試。
- **不要並行回補**：回補與 daily 都長時間寫 DB，analyze 也依 collect run 決定分析日；回補期間停用 daily 工作（`Disable-ScheduledTask`），完成後再啟用。

### 6.5 限制

- universe 取自今日的官方清單。回補期間已下市或轉市的股票，DB 已有標的時照樣寫入歷史；沒有標的時只記 `unmatched_bar`，需要 `instruments repair --include-delisted` 才會建標的並補歷史（[§6.4](#64-重跑與回補)）。
- 標的狀態只依官方清單與已存行情表判定，沒有接終止上市、停牌公告。仍在清單內、但 60 個交易日沒有行情列的推定為 `dormant`；未滿 60 個交易日的維持 `active`，日線停在最後交易日（[DATA_SOURCES 標的狀態同步](DATA_SOURCES.md#標的狀態同步)、[#212](https://github.com/YiCheng0608/stock-lab/issues/212)）。
- 歷史回補不保存當日產業觀測與 MOPS／除權息快照；這些只由 daily 記錄當天。
- 休市判定依官方 no-data 回應；來源暫時失敗的日期記為缺日，不推定休市。
- 全市場 analyze＋evaluate 單次約 4～6 分鐘、峰值約 0.2 GB，連同 candidates／indicators 約 6 分鐘、0.3 GB（2026-10-18，正式 DB 副本：2,409 檔、2024-09-30～2026-10-16 共 496 個交易日；[#184](https://github.com/YiCheng0608/stock-lab/issues/184)）。analyze 每 200 檔 commit 一次 features、group scores 寫完再 commit，每次持有寫入鎖約 2 秒內，與 news 同時執行不會等到 30 秒 busy timeout；analyze 中途失敗時已 commit 的 features／group scores 都是由日線重算的值，重跑會寫出相同結果。group scores 先於 signals commit，所以 analyze 進行中（約 1～2 分鐘）或中途失敗時，API 可能看到新日期族群分數與舊日期訊號並存，重跑 analyze 即一致。

### 6.6 scheduler 容器的排程（serve）

`python -m worker.cli serve`（[`backend/worker/serve.py`](../backend/worker/serve.py)，#336）是 scheduler 容器的常駐命令，在[後端 image](#1-工作目錄環境與啟停) 內取代工作排程器：APScheduler 依台北時間啟動與 [§6.2](#62-dailynews-工作的註冊與管理) 註冊相同的命令，每次一個子程序。compose 設定（#335）、`claude`／`gh` 的認證（#337）與正式切換（#342）不在這裡。

| 工作 | 觸發（預設） | 命令 |
| --- | --- | --- |
| daily | 週一至週五台北 18:30、21:30（`--daily-times`） | `worker.cli job daily --trigger scheduler --data-dir <data> --log-dir <data>/logs --min-free-memory-gb 2 [--claude-cli <claude>]` |
| news | 每 2 小時整點（`--news-interval-hours`） | 同上換成 `job news`、`--min-free-memory-gb 1`；`--skip-news-llm` 交給 job |
| 看門狗 | 每小時 :15、:45（`--watchdog-minutes`；工作排程器是每 15 分鐘） | `bash tools/ops/watchdog.sh --data-dir <data> --python <serve 的 python>`，`--watchdog-dry-run` 時加 `--dry-run` |

- **分工**：鎖、起跑前檢查、單次上限、日誌與 exit code 都由 job 負責，與 §6.2、§6.3 相同；serve 自己不加鎖，重疊的觸發照樣啟動 job，由 job 記 `already_running`（同一工作同時最多 3 個，再多的由 APScheduler 擋下並在 stderr 記警告）。不帶 `--git-pull`：程式由 image 決定（部署見 #340）。
- **第二道防線**：daily、news 超過 job 上限 10 分鐘，或看門狗跑超過 10 分鐘，serve 結束它的程序群組並記 `serve killed`，同工作排程器的上限。
- **錯過的時段**：機器睡眠時錯過的觸發在醒來後補跑一次（APScheduler `coalesce`、不限 misfire 時間，同 StartWhenAvailable）；serve 啟動前的時段不補。
- **停止**：子程序隨 serve 結束（PR_SET_PDEATHSIG）。`docker stop`（SIGTERM，`tini` 轉給 serve）時 serve 記 `stopping`、結束執行中的 job 後退出；`docker kill` 時整個容器一起結束。兩者都不留下 job 或鎖，被殺的 daily 的 run 列由下一次拿到鎖的 daily 立即記 abandoned（§6.3 的 `failed`）。
- **輸出**：serve 的列 `<台北時間> serve <事件> key=value`（`ready` 列出各工作下次執行時間；`start`、`end exit=<碼> seconds=<秒>`，被結束時 `exit=killed`；`killed`、`stopping`、`stop_kill`、`stopped`），與 job、看門狗的 stdout 一起寫到 stdout，由 `docker logs` 查；各工作的日誌照舊在 `<data>/logs/`。
- **時間注入**：`--now YYYY-MM-DDTHH:MM[:SS]`（沒有時區時為台北時間）讓排程的時鐘從該時間起算，照真實速度走；daily 另帶 `--date <該台北日>`，看門狗以 `WATCHDOG_NOW` 判定。日誌檔名與時間戳記仍是真實時間。只用在 DB 副本上的驗證。
- **run 記錄的 image 與 HEAD**：`schedule_runs` 每列的 `summary_json.runtime` 記 `image`（`STOCK_IMAGE_TAG`）、`head`（`STOCK_GIT_HEAD`，沒有時 `git rev-parse HEAD`，都沒有為 null）與 job 持有的鎖 `job_lock`。build context 不含 `.git`，所以 build 時帶入：`docker build -f backend/Dockerfile -t stock-lab-backend:<tag> --build-arg STOCK_IMAGE_TAG=stock-lab-backend:<tag> --build-arg STOCK_GIT_HEAD="$(git rev-parse HEAD)" .`。
- 其他選項：`--data-dir`、`--log-dir`、`--claude-cli`、`--daily-min-free-memory-gb`、`--news-min-free-memory-gb`、`--daily-time-limit-minutes`、`--news-time-limit-minutes`（交給 job）。只在 Linux 執行，其他系統 exit 69。

**切換前提**（#342，PR #346 review S1）：#333 起 job 只在 Linux 執行，工作排程器跑到含 #333 的 commit 時 daily、news、看門狗都以 69 結束，不寫日誌也不留言，排程會無聲停擺。所以工作排程器停用、scheduler 容器接手之前，發佈 checkout 不能拉到任何含 #333 的 commit（維持在 `release/v1` 或固定 tag）；切換步驟由 #342 處理。
