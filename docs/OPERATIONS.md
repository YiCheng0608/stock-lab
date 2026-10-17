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

`init-db` 會改 schema，執行前先解析三個路徑並為既有 DB 備份（[§2.1](#21-安全升級與復原順序)）。API startup 只跑 `check_database_readiness()`，不會自動建庫、migration、repair 或 stamp；缺檔、空檔、不可讀或不符契約時拒絕啟動。已啟動的 process 不會因 source 更新而改變 lifespan。

`app.config` import 執行設定的 data／raw 目錄建立；API 的資料變更 handlers 及 collect／daily／backfill／analyze／evaluate／backtest／news／news-llm 是寫入入口。要做只讀查驗，應直接使用 SQLite `mode=ro`＋`PRAGMA query_only=ON`，不能用一般 app startup 代替。`GET /api/dashboard`、`GET /api/news`、`GET /api/news/{id}` 會呼叫 `sync_news_from_events`，把本機既有官方 Events 冪等投影成 NewsItem 並 commit。前端開發服務與 `VITE_API_BASE` 見[前端 README](../frontend/README.md#啟動)。

### 1.1 產品 API 的跨站請求防護

`app.main:app` 對每個 POST、PUT、PATCH、DELETE，先經 [`BrowserGate`](../backend/app/browser_gate.py)（純 ASGI，常開，不依 env 或設定）才進 router；GET、HEAD、OPTIONS 不檢查。拒絕的請求不讀 body、不開 DB。CORS 只決定瀏覽器讀不讀得到回應，不阻止表單或 `text/plain` 的 simple request 送達本機埠，所以需要這層。四項依序檢查，第一個不符即回應：

| 順序 | 檢查 | 放行條件 | 拒絕 |
| --- | --- | --- | --- |
| 1 | Host | 恰一個值，為小寫 `127.0.0.1:<port>` 或 `localhost:<port>`，`<port>` 是 API 實際監聽埠 | 403 `host_not_admitted` |
| 2 | Sec-Fetch-Site（有送時） | `same-origin`、`none` 放行；`same-site`、`cross-site` 僅在 Origin 已被接受時放行 | 403 `cross_site_rejected` |
| 3 | Origin（有送時） | 在允許清單 `config.DEFAULT_CORS_ORIGINS`（`http://localhost:5173`、`http://127.0.0.1:5173`）內，或等於自身 `http://<Host>` | 403 `origin_not_admitted` |
| 4 | Content-Type（只查 POST、PUT、PATCH） | `application/json`，可接 `; charset=utf-8` | 415 `content_type_json_required` |

拒絕回應是 JSON `{"reason":"<reason>"}` 加 `Cache-Control: no-store`；防護在 `CORSMiddleware` 內側，允許清單內的 origin 被拒時前端仍讀得到狀態碼與 reason。沒有 Origin 與 Sec-Fetch-Site 的請求（curl、腳本）只受 Host 與 Content-Type 規則約束（POST 須帶 `-H "Content-Type: application/json"`）。

寫入會被拒的情況：以 LAN IP、機器名稱、IPv6 `[::1]` 或經代理改寫的 Host 連線；Host 大小寫變體或 port 不符／省略；Unix socket；`VITE_API_BASE` 不符 Host 規則；Vite 改用 5173 以外的埠。這不是身分驗證，同機其他程式送出符合規則的請求一樣放行。

## 2. 資料庫、migration 與 readiness

程式 Alembic head 是 `0012_news_llm`，revision chain 為 0001→0012（`app/migration_revisions.py`；0010 新增 `technical_indicators`，0011 新增排程 run 記錄表，見 [§6.3](#63-日誌與-run-記錄)，0012 新增新聞 LLM 判讀表 `news_llm_results`，見 [NEWS_SPEC §5](NEWS_SPEC.md#5-ai-摘要與推論)）；無法載入 Alembic 時，`init-db` 以內建步驟升級並把 revision 寫入 `schema_migrations`（`migrations.upgrade_database`）。程式 head 不代表任何 DB 已升級。策略版本的遷移規則見 [V1_SPEC](V1_SPEC.md#策略版本識別)。連線一律用 WAL 與 30 秒 busy timeout（`app.db`），排程的 daily 與 news 寫同一個 DB 時互相等待而不報 `database is locked`。

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
| `python -m worker.cli daily --date YYYY-MM-DD --months-back 0 [--trigger manual\|scheduler\|simulation] [--force]` | collect 成功才 analyze；analyze 成功才 evaluate。collect 成功後跑指標批次（目標日傳給批次；analyze 失敗也跑）；collect 失敗時後續步驟記 `skipped`。每次執行寫一列 `schedule_runs`，任一步驟失敗則該 run 為 `failed`；exit code 與狀態見 [§6.3](#63-日誌與-run-記錄)。 |
| `python -m worker.cli schedule-runs [--date YYYY-MM-DD] [--limit N]` | 列出 daily run 記錄與各步驟；唯讀。 |
| `python -m worker.cli backfill --start-date YYYY-MM-DD --end-date YYYY-MM-DD --scope market` | 有界官方回補、重試與稽核；不是 backtest。超過 93 日的範圍依序切成多段。 |
| `python -m worker.cli analyze` | 要求最新官方 collect run success 與有效 as-of；沒有 `--date`，也不是任意局部分析器。 |
| `python -m worker.cli evaluate` | 更新 execution／tracking 與 T+5／T+20 settlement；會寫 DB。 |
| `python -m worker.cli backtest --start-date YYYY-MM-DD --end-date YYYY-MM-DD` | 回放既有資料並保存 audit；不下載歷史資料。 |
| `python -m worker.cli indicators [--date YYYY-MM-DD] [--rebuild]` | 以保存日線算 [技術指標](V1_SPEC.md#技術指標) 寫入 `technical_indicators`；不發網路、不改日線。預設（每日）對每檔寫上次已算日之後到 `--date`（預設 DB 最新日線日）的列，通常就是最新一日；最後一筆已算值與重算不符時整檔重寫，但只偵測得到影響最後一列的變動。補登除權息事件、回補或更正舊日線、升版後要跑 `--rebuild` 重寫全部歷史。不會跑 `init-db`，表不存在時回 `technical_indicators_table_missing_run_init_db`。 |
| `python -m worker.cli news [--date YYYY-MM-DD]` | 抓 [新聞來源](DATA_SOURCES.md#新聞來源) 的 RSS，寫 raw 與 `news_items`（去重與關聯規則見 [NEWS_SPEC §3](NEWS_SPEC.md#3-去重新資訊與事件影響)）。每個來源一筆 `run_type=news` 的 ingestion run，status 為 `success`／`partial`／`failed`，失敗的 feed 記在 `error` 與 `metadata_json.feeds`，其他來源照常寫入。可重跑，既有新聞不改寫。`--date` 只標記 run 日期（預設台北今日），不篩選來源內容。不會跑 `init-db`，表不存在時回 `news_items_table_missing_run_init_db`。 |
| `python -m worker.cli news-llm [--date YYYY-MM-DD] [--limit N] [--dry-run]` | 以本機 Claude Code 無介面模式（`claude -p --model haiku`，使用者的訂閱登入，不用 API 金鑰）判讀新聞，結果寫 `news_llm_results`（選取、旗標與欄位規則見 [NEWS_SPEC §5](NEWS_SPEC.md#5-ai-摘要與推論)）。挑 3 天內未判讀的新聞，新的在前，最多 `--limit` 則（預設 50），每 25 則一次呼叫；`--date` 只挑該台北日收錄（`collected_at`）的新聞。同一台北日所有 run 合計最多 20 次呼叫，每批呼叫後立即計入，超過的批次跳過並記在 `error`。超時、非 JSON、不符 schema 時該批各則標 `pending`，其他批照跑，下次重試；未登入、額度限制或 CLI 無法啟動時停止本次執行，其餘批次跳過。環境有 `ANTHROPIC_API_KEY`／`ANTHROPIC_AUTH_TOKEN`、`STOCK_CLAUDE_CLI` 格式錯誤或找不到可執行檔時，記一筆 `failed` run 後結束，不呼叫也不寫判讀列。每次執行一筆 `run_type=news_llm` 的 ingestion run，`metadata_json` 記每批則數、耗時、模型與 token 用量；每批的 prompt 與 CLI 回應存 raw（`news_llm`）。`--dry-run` 只列出批次，不呼叫、不寫 DB。CLI 預設為 PATH 上的 `claude`，可用 `STOCK_CLAUDE_CLI` 指定路徑或 JSON 字串陣列；只支援原生 `claude` 可執行檔，npm 的 `.cmd` shim 在超時時無法終止底下的 node 程序。結束碼同 daily：`success`／`skipped`／`dry_run` 為 0，`partial` 為 2，`failed` 為 1（找不到 claude、未登入、額度限制、全部批次失敗，原因在 JSON 的 `reason`、run 的 `error`）。排程由 `\stock-lab\news` 在 `news` 之後呼叫，見 [§6](#6-排程)。不會跑 `init-db`，表不存在時回 `news_llm_results_table_missing_run_init_db`。 |

`backfill --scope` 支援 `market`、`portfolio`、`watchlist`、`events`、`candidates`、`priority`、`all`；名稱存在不代表資料來源或管理 UI 完整。起日不得晚於迄日；CLI 把較長範圍由舊到新切成每段不超過 `OFFICIAL_MAX_BACKFILL_DAYS=93` 日的連續段，每段各有 request key、manifest 與重試（API 的單次回補仍限 93 日）。CLI 回補不抓只代表「今天」的快照來源（STOCK_DAY_ALL、OpenAPI 指數、除權息、MOPS 清單、TPEx 停復牌），universe 每次執行只抓一次，也不記錄當日產業觀測；目標有效交易日不足時，候選查詢可早於輸入起日，但不得超過迄日前 93 日界線。批次最多 5 個交易日，adapter 逐日呼叫；重試規則是立即 3 次、後續 2 次。`--force` 會重新擷取已完成日期，並非一般重試預設。

`candidates`／`priority` 依群組分數的候選身分決定納入標的，`/api/coverage` 同名 scope 重用同一 resolver（規則見[產業分類 §6](INDUSTRY_CLASSIFICATION.md#6-群組成員與候選身分)）；run 建立時把 `metadata.target_instruments` 固定為 snapshot，resume 與 `--force` 不重新解析。

先檢查 run status、有效 sessions、缺欄／缺日與 raw evidence。collect 為 partial／failed 時，`daily` 不執行後續；不得人工改 status 繞過 gate。

## 4. 資料品質與研究結果

- 逐用途檢查交易所、標的、日期與欄位；行情 success 不代表 chips、events、actions 完整。無資料、錯日與 incomparable 的判定見 [V1_SPEC 共通原則](V1_SPEC.md#共通原則)。
- entry、breakout、pullback、invalid、targets 是規則參考價，不是持倉成本、委託或成交；`cost_included=false` 只表示價位公式未扣成本。
- `data_cutoff`、`signal_date`、`earliest_execution_date`、naive `created_at` 都不能證明 `decision_at`。unknown time／basis 必須連同 reason 保留。
- `/api/ingestion-runs`、`/api/backfill-runs`、`/api/data-quality`、`/api/backtest/summary` 提供稽核摘要，`/api/coverage` 提供 coverage。前端入口為 `/research/backtest`、`/research/coverage`、`/system/data-quality`。
- 產業分類 run 與 ordinary、ETF、新上市 receipt 分開讀，其中一個 success 不代表全分類已核實（[產業分類](INDUSTRY_CLASSIFICATION.md)）。

## 5. 測試與驗證

命令見[工作手冊](GITHUB_WORKFLOW.md#本機檢查)，測試資料與落盤原則見 [AGENTS](../AGENTS.md#工程原則)；後端測試與瀏覽器驗證使用隔離 DB，不指向正式或 `.local` DB。

## 6. 排程

每日排程以 Windows 工作排程器執行 `worker.cli daily` 與 `worker.cli news`（news 之後接著 `worker.cli news-llm`）（[ROADMAP V1-G1](ROADMAP.md#v1-範圍基線2026-10-17-核定)）；註冊、查詢、停用與移除見 [§6.2](#62-dailynews-工作的註冊與管理)，日誌與 run 記錄見 [§6.3](#63-日誌與-run-記錄)。自動下單不在第一版範圍。

位置（使用者 2026-10-17 決定）：正式資料目錄 `C:/Users/YiCheng/stock-lab-data/`（`stock.db`、`raw/`、`logs/`），以 `STOCK_DATA_DIR` 指向；排程只從發佈 checkout `C:/Users/YiCheng/stock-lab-release/`（repo 的獨立 clone，停在 `origin/master`，排程起跑前 `git pull --ff-only`）及其 `.venv` 執行，不從 `master` 管理 checkout。統籌心跳檔、換手標記與壓縮計數檔都在資料目錄的 `logs/` 下（[工作手冊](GITHUB_WORKFLOW.md#統籌-session)）。

新聞任務與 `daily` 分開排程，不掛在 `daily` 之後：

- **頻率**：每 2 小時執行一次 `python -m worker.cli news`，環境變數（`STOCK_*`、`PYTHONPATH`）與 `daily` 相同。feed 只保留最近 10～65 則，間隔拉長會漏稿（見[新聞來源限制](DATA_SOURCES.md#新聞來源)）。
- **rate limit**：每次 9 個請求、間隔 2 秒，一天約 108 個請求；不重試，限流或失敗的 feed 等下一輪。
- **冪等**：重跑或兩輪重疊抓到同一則時，不新增列、不改寫既有列。
- **錯誤**：每個來源的結果寫入 `run_type=news` 的 ingestion run，可用 `/api/ingestion-runs?q=news` 查；CLI 也把同一份結果以 JSON 印到 stdout，排程把 stdout／stderr 導到日誌檔保存（[§6.3](#63-日誌與-run-記錄)）。
- **LLM 判讀**：`\stock-lab\news` 每輪在 `worker.cli news` 結束後，於同一次執行接著跑 `python -m worker.cli news-llm`（環境變數相同、不帶 `--date`），把新收的新聞做 AI 摘要與判讀。每輪最多 50 則（2 次呼叫），同一台北日所有 run 合計最多 20 次呼叫，超過的批次等下一個台北日（[§3](#3-現有-worker-cli)）。
  - news 失敗時仍會跑（news-llm 只讀已入庫的新聞）；news-llm 失敗不改變 news 的結果，也不改變工作的結束碼。失敗只留在日誌的 news-llm 段落與 `run_type=news_llm` 的 ingestion run（`status=failed`、`error` 寫原因），可用 `/api/ingestion-runs?q=news_llm` 查；日誌格式見 [§6.3](#63-日誌與-run-記錄)。
  - 執行機器須已登入 Claude Code 且環境沒有 `ANTHROPIC_API_KEY`／`ANTHROPIC_AUTH_TOKEN`（有就拒絕執行）。排程環境的 PATH 與互動 shell 不同，所以註冊時以 `-ClaudeCli` 寫入原生 `claude.exe` 的完整路徑（[§6.2](#62-dailynews-工作的註冊與管理)）。找不到 claude、未登入或額度用盡時，當輪記 `failed`（或該批 `pending`）並停止，下一輪重試。
  - 看門狗在最近 3 批判讀都是 `pending` 時留言（[§6.1](#61-統籌看門狗)）；找不到 claude、API 金鑰這類設定錯誤是沒有批次的 `failed` run，不計入該判定，要看日誌的 `news_llm_exit`。
  - **停用／恢復**：只停 news-llm 用 `-NoNewsLlm` 重新註冊 news（[§6.2](#62-dailynews-工作的註冊與管理)）；整個 news 停用用 `Disable-ScheduledTask`。額度吃緊時先停 news-llm，news 照常收稿。

### 6.1 統籌看門狗

`tools/ops/ensure_coordinator.sh`（Git Bash）每 15 分鐘由工作 `\stock-lab\watchdog` 執行：讀心跳檔判定統籌是否在線，停擺就送喚醒文、不在就開新統籌，判定規則見[工作手冊](GITHUB_WORKFLOW.md#統籌-session)；另以檔案與唯讀 DB 檢查排程異常並在 [#1](https://github.com/YiCheng0608/stock-lab/issues/1) 留言「待使用者」，每個異常每台北日最多一則：

- `daily`：週一至週五台北 21:30 後，當日 `logs/daily-YYYYMMDD.log` 不存在或沒有 `end` 列。
- `news`：最新的 `logs/news-*.log` 已超過 6 小時（連續 3 次）沒有更新。
- `news_llm`：`stock.db` 最近 3 批判讀都是 `pending`（沒有批次的 `failed` run 不算，見 [§6](#6-排程)）。

`daily`／`news` 還沒有任何日誌時不判定（排程尚未註冊）。執行環境：Git Bash、PATH 上有 `orca` 與已登入的 `gh`；Python 只用來解析 JSON 與唯讀查 DB，預設發佈 checkout 的 `.venv`。以下命令在發佈 checkout 執行：

| 動作 | 命令 |
| --- | --- |
| 預覽 | `powershell -ExecutionPolicy Bypass -File tools/ops/Register-Watchdog.ps1 -WhatIf` |
| 註冊或更新 | `powershell -ExecutionPolicy Bypass -File tools/ops/Register-Watchdog.ps1`（`-DataDir`、`-PythonPath` 預設 `STOCK_DATA_DIR`、`.venv`；`-DryRun` 註冊只判定不動作的版本，用來以 `Start-ScheduledTask -TaskPath \stock-lab\ -TaskName watchdog` 驗證排程環境） |
| 查詢 | `schtasks /query /tn "\stock-lab\watchdog" /v /fo list` |
| 停用／啟用 | `Disable-ScheduledTask -TaskPath \stock-lab\ -TaskName watchdog`／`Enable-ScheduledTask ...` |
| 移除 | `powershell -ExecutionPolicy Bypass -File tools/ops/Register-Watchdog.ps1 -Unregister` |
| 手動判定 | `bash tools/ops/ensure_coordinator.sh --dry-run`（只輸出將做的動作與接手文） |

工作以目前使用者、Interactive logon、隱藏執行，登入時才跑；同時只跑一個，10 分鐘逾時。日誌 `<資料目錄>/logs/ensure_coordinator.log`，每列為 UTC 時間、事件、`key=value` 與說明；喚醒文（每 60 分鐘最多一次）、開統籌（每 120 分鐘最多一次）與異常留言（每日一則）的頻率限制都以此日誌判斷。執行中持有 `logs/ensure_coordinator.lock/`，殘留超過 30 分鐘自動移除。

### 6.2 daily／news 工作的註冊與管理

三個位置（使用者 2026-10-17 決定，見本節開頭）：

| 位置 | 路徑 | 說明 |
| --- | --- | --- |
| 資料目錄 | `C:/Users/YiCheng/stock-lab-data/` | 正式 `stock.db`、`raw/`、`logs/`。排程以 `-DataDir` 傳入並設成子行程的 `STOCK_DATA_DIR`（預設依序為 `STOCK_DATA_DIR`、`%USERPROFILE%\stock-lab-data`），不由 cwd 推導。 |
| 發佈 checkout | `C:/Users/YiCheng/stock-lab-release/` | repo 的獨立 clone，停在 `origin/master`；排程**只**從這裡執行，不從 `master` 管理 checkout 或任務 worktree。每次執行先 `git pull --ff-only`。 |
| Python | `C:/Users/YiCheng/stock-lab-release/.venv` | 依 `backend/validation-requirements.lock.txt` 安裝；依賴變更的 PR 合併後由統籌在此 venv 重裝。預設依序為 `-PythonPath`（別名 `-Python`）、`STOCK_PYTHON`、發佈 checkout 的 `.venv`。 |

首次建立：`git clone` 到發佈 checkout，建 `.venv` 並安裝依賴；以 SQLite backup API 把已初始化的 DB 複製成資料目錄的 `stock.db`（有 WAL 時不裸複製主檔），再於發佈 checkout 註冊工作。daily 開頭只在 DB 的 Alembic revision 不是程式 head 時才跑 `init_db`（含整庫 migration 完整性檢查，多年 DB 上要數分鐘）；已在 head 時直接開始。

以下命令在發佈 checkout 執行（`<py>` 為發佈 checkout 的 `.venv\Scripts\python.exe`，`<data>` 為資料目錄）：

| 動作 | 命令 |
| --- | --- |
| 預覽（不改系統） | `powershell -ExecutionPolicy Bypass -File tools/Register-WorkerSchedule.ps1 -Job daily -Python <py> -DataDir <data> -WhatIf`（news 把 `-Job` 換成 `news`；輸出的 `Command:` 列就是工作排程器會執行的完整命令） |
| 註冊或更新 | 同上去掉 `-WhatIf`；同名覆寫 |
| 查詢 | `schtasks /query /tn "\stock-lab\daily" /v /fo list`；`Get-ScheduledTaskInfo -TaskPath \stock-lab\ -TaskName daily`（上次執行時間與結果、下次執行時間） |
| 手動觸發 | `Start-ScheduledTask -TaskPath \stock-lab\ -TaskName daily`（與排程完全相同的環境） |
| 停用／啟用 | `Disable-ScheduledTask -TaskPath \stock-lab\ -TaskName daily`／`Enable-ScheduledTask ...` |
| 移除 | `powershell -ExecutionPolicy Bypass -File tools/Register-WorkerSchedule.ps1 -Job daily -Unregister` |
| 不經排程執行一次 | `powershell -ExecutionPolicy Bypass -File tools/Invoke-WorkerJob.ps1 -Job daily -Python <py> -DataDir <data> -Trigger manual [-Date YYYY-MM-DD] [-Force]`；news 另可加 `-ClaudeCli <claude.exe>`、`-SkipNewsLlm`，`-Date` 只給 news（news-llm 的 `--date` 是篩選，不帶） |
| news 的 news-llm | 註冊 news 時指定 `-ClaudeCli <原生 claude.exe>`；未給時依序取 `STOCK_CLAUDE_CLI`、PATH 上第一個 `claude.exe`，都沒有或是 `.cmd` shim 就拒絕註冊。停用：同一條註冊命令改加 `-NoNewsLlm`（工作內為 `-SkipNewsLlm`）；恢復：去掉 `-NoNewsLlm` 再註冊一次。 |

| 工作 | 觸發 | 動作 |
| --- | --- | --- |
| `\stock-lab\daily` | 週一至週五台北 18:30，21:30 再跑一次（`-TaipeiTimes` 可改） | `tools/Invoke-WorkerJob.ps1 -Job daily -GitPull -MinFreeMemoryGB 6`（註冊參數 `-DailyMinFreeMemoryGB`），單次上限 2.5 小時 |
| `\stock-lab\news` | 每天每 2 小時（`-IntervalHours`），從下一個整點區間開始 | `tools/Invoke-WorkerJob.ps1 -Job news -GitPull -MinFreeMemoryGB 1 -ClaudeCli <claude.exe>`（註冊參數 `-NewsMinFreeMemoryGB`；`-NoNewsLlm` 時改為 `-SkipNewsLlm`）：先 `news`、再 `news-llm`，單次上限 90 分鐘 |

兩個工作都以目前使用者、互動式登入、一般權限、隱藏視窗執行，不存密碼，使用者登入時才跑；錯過的時段在登入後補跑（StartWhenAvailable）；前一次未結束不另起新執行個體。主機不在台灣時區時腳本自動換算本機時間。

休市日不寫進觸發：週間無交易日時官方來源回 no-data，run 記為 `non_trading_day`。三大法人與融資公布時間晚於收盤且不固定，18:30 若因缺這些資料而 collect 為 `partial`，analyze 不會執行，由 21:30 補齊；當日已完成後的 21:30 只記一列 `skipped`（`already_complete`）。

**起跑前檢查**（`Invoke-WorkerJob.ps1`）：可用實體記憶體低於 `-MinFreeMemoryGB`（直接執行時預設 8；註冊時 daily 6、news 1）記 `low_memory`；發佈 checkout 有 `index.lock` 或 `MERGE_HEAD` 記 `git_busy`；`git pull --ff-only` 失敗記 `git_pull_failed`。三者都不執行 worker，等下一次觸發；daily 另在 `schedule_runs` 留一列 `skipped` 與原因，news 只寫日誌。全市場 analyze 單次峰值約 5～5.5 GB（2026-10-17 本機實測），daily 的門檻不宜低於此值。

### 6.3 日誌與 run 記錄

- **日誌**：`<data>/logs/daily-YYYYMMDD.log`、`<data>/logs/news-YYYYMMDD.log`（台北日期），排程失敗時先看這裡。每次執行追加開始列（含可用記憶體）、`git pull` 輸出、跳過原因、CLI 的 JSON 結果（stdout）、stderr 與結束列 `===== <時間> end exit=<code> seconds=<秒>`（[§6.1](#61-統籌看門狗) 的看門狗以此判定 daily 是否完成）。保留 90 天（`-LogRetentionDays`），只清同名前綴的檔案。包裝腳本本身出錯時記 `wrapper error`，工作排程器「上次執行結果」為非 0。
  - **news 日誌的分段**：`--- news stdout`／`--- news stderr`／`--- news end exit=<碼> seconds=<秒>`，接著 `--- news-llm start claude_cli=<路徑>`、`--- news-llm stdout`／`stderr`、`--- news-llm end exit=<碼> seconds=<秒>`；結束列為 `===== <時間> end exit=<news 的碼> seconds=<秒> news_llm_exit=<碼>`，`news_llm_exit` 另有 `disabled`（`-SkipNewsLlm`）、`not_run`（起跑前檢查未通過）、`wrapper_error`（包裝腳本啟動 news-llm 失敗）。daily 日誌格式不變。
- **exit code**：daily 0＝`success`／`skipped`／`non_trading_day`，2＝`partial`，1＝`failed`；工作排程器的「上次執行結果」即此值。news 工作的碼是 `worker.cli news` 的碼；`worker.cli news-llm` 的碼（0＝`success`／`skipped`，2＝`partial`，1＝`failed`）只記在日誌的 `news-llm end` 與 `news_llm_exit`，不影響工作的碼。
- **run 記錄**：`schedule_runs` 每次 daily 執行一列（目標日、觸發來源、開始／結束、狀態、錯誤、collect 筆數、摘要），`schedule_run_steps` 每步一列（collect／analyze／evaluate／indicators 的開始／結束、狀態、錯誤、處理筆數，collect 另連 `ingestion_runs.id`）。查詢：`python -m worker.cli schedule-runs --date YYYY-MM-DD`。news 的結果在 `run_type=news` 的 ingestion run，news-llm 的在 `run_type=news_llm`（`metadata_json` 記每批則數、耗時、模型與 token 用量）。

| run 狀態 | 意義 |
| --- | --- |
| `success` | collect、analyze、evaluate、indicators 都成功（或該步驟回 `no_data`）。 |
| `partial` | collect 有缺（例如籌碼尚未公布）；後續步驟記 `skipped`，錯誤欄列 collect 警告。 |
| `non_trading_day` | 官方來源明確回報該週間日無交易。 |
| `failed` | 某步驟失敗或拋例外；錯誤欄記步驟與訊息，依賴它的步驟記 `skipped`（evaluate 依賴 analyze；indicators 只依賴 collect）。run 列記錄執行的主機與 PID；同主機的新執行發現該 PID 已不存在（例如被系統終止）時，立即把舊列改記 `failed`（abandoned）並照常執行；其他情況要超過 2.5 小時（與排程單次上限相同，小於 18:30 與 21:30 的間隔）仍為 `running` 才記 abandoned，在那之前同日的新執行記 `skipped`（`already_running`）。 |
| `skipped` | 同目標日已有 `success`／`non_trading_day`（`already_complete`）、另一次執行仍在進行（`already_running`），或起跑前檢查未通過（`low_memory`／`git_busy`／`git_pull_failed`）；不碰資料。 |

indicators 步驟呼叫 `worker.indicator_batch.run_indicator_batch(目標日)`；只要 collect 成功就執行（analyze 失敗也跑），失敗時 run 記 `failed`、錯誤欄記 indicators 訊息。

### 6.4 重跑與回補

- **手動重跑**：見 [§6.2](#62-dailynews-工作的註冊與管理)「不經排程執行一次」，或直接 `python -m worker.cli daily --date YYYY-MM-DD`。已完成的日期加 `-Force`／`--force` 才會再跑各步驟。
- **冪等**：collect 對同一 request 已有 `success` 時直接重用、不發請求；重新擷取時，既有日線與籌碼只補空欄，不覆寫已存的非空值，不一致的值保留原值並記在該 collect run metadata 的 `value_conflicts`。只有 `collect(force=True)` 會覆寫。
- **回補**：`python -m worker.cli backfill --start-date <起> --end-date <迄> --scope market`。中斷後以相同起訖重跑即從各段 manifest 續做；輸出列出每段 run id、`partial_dates`／`failed_dates`（缺日，不補值）與 `skipped_non_trading_dates`（官方無交易）。回補或更正舊日線後跑 `python -m worker.cli indicators --rebuild` 重算指標。
- **限流**：`fetch_json` 對同一官方主機保持最小間隔（`www.twse.com.tw` 2.5 秒，其餘官方主機 1 秒），另有 429／5xx／暫時性 307 的有界重試。
- **不要並行回補**：回補與 daily 都長時間寫 DB，analyze 也依 collect run 決定分析日；回補期間停用 daily 工作（`Disable-ScheduledTask`），完成後再啟用。

### 6.5 限制

- universe 取自今日的官方清單：回補期間已下市的股票沒有歷史列。
- 歷史回補不保存當日產業觀測與 MOPS／除權息快照；這些只由 daily 記錄當天。
- 休市判定依官方 no-data 回應；來源暫時失敗的日期記為缺日，不推定休市。
- 全市場 analyze 單次約 27～30 分鐘、峰值約 5～5.5 GB（2026-10-17，2 年資料）。
