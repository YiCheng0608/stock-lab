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

`app.config` import 執行設定的 data／raw 目錄建立；API 的資料變更 handlers 及 collect／daily／backfill／analyze／evaluate／backtest／news 是寫入入口。要做只讀查驗，應直接使用 SQLite `mode=ro`＋`PRAGMA query_only=ON`，不能用一般 app startup 代替。`GET /api/dashboard`、`GET /api/news`、`GET /api/news/{id}` 會呼叫 `sync_news_from_events`，把本機既有官方 Events 冪等投影成 NewsItem 並 commit。前端開發服務與 `VITE_API_BASE` 見[前端 README](../frontend/README.md#啟動)。

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

程式 Alembic head 是 `0010_technical_indicators`，revision chain 為 0001→0010（`app/migration_revisions.py`）；無法載入 Alembic 時，`init-db` 以內建步驟升級並把 revision 寫入 `schema_migrations`（`migrations.upgrade_database`）。程式 head 不代表任何 DB 已升級。策略版本的遷移規則見 [V1_SPEC](V1_SPEC.md#策略版本識別)。

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
| `python -m worker.cli daily --date YYYY-MM-DD --months-back 0` | collect 成功才 analyze；analyze 成功才 evaluate。collect 成功後最後跑指標批次（`--date` 傳給批次；analyze 失敗也跑），批次失敗只在結果的 `indicators` 記 `failed` 與錯誤，不影響前面步驟；collect 失敗時記 `skipped`。 |
| `python -m worker.cli backfill --start-date YYYY-MM-DD --end-date YYYY-MM-DD --scope market` | 有界官方回補、重試與稽核；不是 backtest。 |
| `python -m worker.cli analyze` | 要求最新官方 collect run success 與有效 as-of；沒有 `--date`，也不是任意局部分析器。 |
| `python -m worker.cli evaluate` | 更新 execution／tracking 與 T+5／T+20 settlement；會寫 DB。 |
| `python -m worker.cli backtest --start-date YYYY-MM-DD --end-date YYYY-MM-DD` | 回放既有資料並保存 audit；不下載歷史資料。 |
| `python -m worker.cli indicators [--date YYYY-MM-DD] [--rebuild]` | 以保存日線算 [技術指標](V1_SPEC.md#技術指標) 寫入 `technical_indicators`；不發網路、不改日線。預設（每日）對每檔寫上次已算日之後到 `--date`（預設 DB 最新日線日）的列，通常就是最新一日；最後一筆已算值與重算不符時整檔重寫，但只偵測得到影響最後一列的變動。補登除權息事件、回補或更正舊日線、升版後要跑 `--rebuild` 重寫全部歷史。不會跑 `init-db`，表不存在時回 `technical_indicators_table_missing_run_init_db`。 |
| `python -m worker.cli news [--date YYYY-MM-DD]` | 抓 [新聞來源](DATA_SOURCES.md#新聞來源) 的 RSS，寫 raw 與 `news_items`（去重與關聯規則見 [NEWS_SPEC §3](NEWS_SPEC.md#3-去重新資訊與事件影響)）。每個來源一筆 `run_type=news` 的 ingestion run，status 為 `success`／`partial`／`failed`，失敗的 feed 記在 `error` 與 `metadata_json.feeds`，其他來源照常寫入。可重跑，既有新聞不改寫。`--date` 只標記 run 日期（預設台北今日），不篩選來源內容。不會跑 `init-db`，表不存在時回 `news_items_table_missing_run_init_db`。 |

`backfill --scope` 支援 `market`、`portfolio`、`watchlist`、`events`、`candidates`、`priority`、`all`；名稱存在不代表資料來源或管理 UI 完整。起日不得晚於迄日，輸入差不超過 `OFFICIAL_MAX_BACKFILL_DAYS=93`；目標有效交易日不足時，候選查詢可早於輸入起日，但不得超過迄日前 93 日界線。批次最多 5 個交易日，adapter 逐日呼叫；重試規則是立即 3 次、後續 2 次。`--force` 會重新擷取已完成日期，並非一般重試預設。

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

每日排程以 Windows 工作排程器執行 worker 與新聞任務（[ROADMAP V1-G1](ROADMAP.md#v1-範圍基線2026-10-17-核定)）；排程註冊方式與日誌位置尚未提供，未排程前依 [§3](#3-現有-worker-cli) 手動執行。

新聞任務與 `daily` 分開排程，不掛在 `daily` 之後：

- **頻率**：每 2 小時執行一次 `python -m worker.cli news`，環境變數（`STOCK_*`、`PYTHONPATH`）與 `daily` 相同。feed 只保留最近 10～65 則，間隔拉長會漏稿（見[新聞來源限制](DATA_SOURCES.md#新聞來源)）。
- **rate limit**：每次 9 個請求、間隔 2 秒，一天約 108 個請求；不重試，限流或失敗的 feed 等下一輪。
- **冪等**：重跑或兩輪重疊抓到同一則時，不新增列、不改寫既有列。
- **錯誤**：每個來源的結果寫入 `run_type=news` 的 ingestion run，可用 `/api/ingestion-runs?q=news` 查；CLI 也把同一份結果以 JSON 印到 stdout，排程把 stdout／stderr 導到日誌檔保存。
