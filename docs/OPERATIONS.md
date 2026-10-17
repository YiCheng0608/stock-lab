# 操作手冊

現行測試入口、依賴與環境重建以 [開發入口](development-baseline/README.md) 為準；能力狀態與後續順序見 [ROADMAP](ROADMAP.md)。本文件只保留可操作入口、安全邊界與診斷順序。

## 1. 工作目錄、環境與啟停

後端命令從專案根目錄執行。範例預設使用 workspace 內 `.local` 開發資料；做測試、migration 或可丟棄研究時，先把三個 `STOCK_*` 改成明確的隔離路徑，可用共用入口 `python -B -X utf8 -m tools.test_db` 建立並讀回；日常 DB、唯讀樣本庫與隔離測試庫的分工，以及該入口的命令、隔離保證與能力邊界見[測試資料庫分層](development-baseline/README.md#測試資料庫分層)。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt

$env:STOCK_DATA_DIR = (Join-Path $PWD '.local/data')
$env:STOCK_DB_PATH = (Join-Path $env:STOCK_DATA_DIR 'stock.db')
$env:STOCK_RAW_DIR = (Join-Path $env:STOCK_DATA_DIR 'raw')
$env:PYTHONPATH = (Join-Path $PWD 'backend')
```

明確初始化／升級指定 DB 後再啟動 API：

```powershell
python -m worker.cli init-db
python -m uvicorn app.main:app --reload --port 8000
```

`init-db` 會改 schema。執行前必須解析三個路徑、確認目標與授權，並為既有 DB 建 consistent backup。API startup 只跑 `check_database_readiness()`，不會自動建庫、migration、repair 或 stamp；缺檔、空檔、不可讀或不相容時拒絕啟動。以 `Ctrl+C` 停止自己啟動的前景服務；不要停止或重啟其他 task／使用者管理的 process。source 更新也不會改變已載入舊 lifespan 的 running process。

`app.config` import 執行設定的 data／raw 目錄建立；API 的資料變更 handlers 及 collect／daily／backfill／analyze／evaluate／backtest 是寫入入口。要做只讀查驗，應直接使用 SQLite `mode=ro`＋`PRAGMA query_only=ON`，不能用一般 app startup 代替。

前端開發服務：

```powershell
Push-Location frontend
pnpm install --frozen-lockfile
pnpm run dev
Pop-Location
```

預設 API base 是 `http://127.0.0.1:8000/api`；需要不同位址時，在啟動前設定 `VITE_API_BASE`，該位址須符合[§1.1](#11-產品-api-的跨站請求防護)的 Host 規則，否則寫入會被拒。

### 1.1 產品 API 的跨站請求防護

`app.main:app` 對每個 POST、PUT、PATCH、DELETE，先經 [`BrowserGate`](../backend/app/browser_gate.py)（純 ASGI，常開，不依任何 env 或設定；取源端點是否啟用仍由各自的 env 決定）才進 router 與 handler。拒絕的請求不讀 body、不開 DB、不取源，也不碰額度與私人檔案；GET、HEAD、OPTIONS 不檢查。需要這層是因為 CORS 只決定瀏覽器讀不讀得到回應，不阻止表單或 `text/plain` 的 simple request 送達本機埠。

四項依序檢查，第一個不符即回應：

| 順序 | 檢查 | 放行條件 | 拒絕 |
| --- | --- | --- | --- |
| 1 | Host | 恰一個值，為 `127.0.0.1:<port>` 或 `localhost:<port>`；`<port>` 是 API 實際監聽的埠（ASGI `scope["server"]`）。須小寫、須帶 port | 403 `host_not_admitted` |
| 2 | Sec-Fetch-Site（有送時） | 恰一個值；`same-origin`、`none` 放行；`same-site`、`cross-site` 僅在 Origin 已被接受時放行；其他值不放行 | 403 `cross_site_rejected` |
| 3 | Origin（有送時） | 恰一個值，且在允許清單內，或等於自身 `http://<Host>` | 403 `origin_not_admitted` |
| 4 | Content-Type（只查 POST、PUT、PATCH） | 恰一個值，為 `application/json`，可接 `; charset=utf-8`，不分大小寫 | 415 `content_type_json_required` |

DELETE 不查 Content-Type（前端的 DELETE 不帶 body）。沒有 Origin 與 Sec-Fetch-Site 的請求（curl、腳本）視為非瀏覽器呼叫，只受 Host 與 Content-Type 規則約束。

允許清單是 `config.DEFAULT_CORS_ORIGINS`（`http://localhost:5173`、`http://127.0.0.1:5173`），與 `configure_cors` 交給 `CORSMiddleware` 的是同一個物件，沒有 env 或設定可覆寫。

拒絕回應是 JSON `{"reason":"<reason>"}` 加 `Cache-Control: no-store`。防護在 `CORSMiddleware` 內側：preflight 由 CORS 直接回應、不經檢查（Host 不符的 preflight 也得到 CORS 回應，但其後的實際請求仍被 Host 規則拒絕）；允許清單內的 origin 被拒時，回應仍帶 `Access-Control-Allow-Origin`，前端讀得到狀態碼與 reason；其他 origin 被拒時回應只有 `Access-Control-Allow-Credentials: true`、沒有 `Access-Control-Allow-Origin`，頁面讀不到回應。

**使用方式**：

- 前端：Vite 在 `http://localhost:5173` 或 `http://127.0.0.1:5173`、API base 為預設值時不需調整。
- curl 與腳本：URL 用小寫的 `http://127.0.0.1:<port>` 或 `http://localhost:<port>`；POST、PUT、PATCH 須明確加 JSON Content-Type（curl 的 `-d` 預設送 `application/x-www-form-urlencoded`，會得 415）。

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/<路徑>" -H "Content-Type: application/json" --data-binary "@body.json"
curl.exe -X DELETE "http://127.0.0.1:8000/api/portfolio/<id>"
```

**限制**（寫入會被拒的情況）：

- Host 不是 `127.0.0.1` 或 `localhost`：`--host 0.0.0.0` 後以 LAN IP 或機器名稱連線、IPv6 `[::1]`、Host 被反向代理或埠轉發改寫的請求。`LocalHost` 等大小寫變體，以及 Host 的 port 與實際監聽埠不同或省略（例如 `--port 80`，瀏覽器不送 port）也被拒。
- Unix socket 沒有 `scope["server"]` 的 port，一律被拒。
- `VITE_API_BASE` 的 host 不是 `127.0.0.1` 或 `localhost`，或 port 不是 API 實際監聽埠。
- 前端 origin 不在允許清單，例如 Vite 在 5173 被占用而改用其他埠。
- 不是身分驗證：同機其他程式送出符合上述規則的請求一樣放行。
- 可重建的驗證是以手造標頭執行的 RAM 測試 [`test_app_main_browser_gate.py`](../backend/tests/test_app_main_browser_gate.py)；未用真瀏覽器的外站頁面或真 uvicorn 實測。

**殘留**（GET 不檢查）：

- `GET /api/dashboard`、`GET /api/news`、`GET /api/news/{id}` 會呼叫 `sync_news_from_events`，有變更列時 commit，把本機既有的官方 Events 冪等投影成 NewsItem；內容全來自本機既有資料，不由請求決定，外站 no-cors GET 也讀不到回應。

## 2. 資料庫、migration 與 readiness

程式 Alembic head 是 `0010_technical_indicators`（只新增 `technical_indicators` 表），revision chain 為 0001→0010，另有相容 fallback markers；這不證明任何 DB 已升級。0009 的遷移與分類契約見 [V1_SPEC](V1_SPEC.md#已知實作偏差與版本修正要求) 已知偏差第 6 條。實際 DB 歷史、revision 與 preservation 證據見 [R0 §8](R0_IMPLEMENTATION.md#8-r0-5migration-head-與實際-db-revision)，新持倉欄的有限 migration／readiness 與九枚 markers 規則見 [§8.11](R0_IMPLEMENTATION.md#811-m3-p2持倉精確整數-migrationreadiness有限接受)。

readiness 只在唯讀 transaction 檢查有限 descriptor：revision marker 必須是唯一 current head 或受控的完整 fallback 形狀；mapped objects、必要欄名、ordered PK／FK／UNIQUE 與 News JSON defaults 必須符合契約；`signal_settlements` 與 `instruments` 的精確 identity gate 分見 [R0 §8.9](R0_IMPLEMENTATION.md#89-round30-c030api-startup-signal_settlements-unique-metadata-gate有限-review) 及 [§8.10](R0_IMPLEMENTATION.md#810-round31-c031api-startup-instruments-unique-metadata-gate有限-review)。它不執行 `quick_check`、`integrity_check`、資料 FK scan 或完整 type／CHECK／trigger／custom-schema audit，也不涵蓋 live WAL／SHM、concurrent writer、non-SQLite 與 attached schema；通過不保證任意寫入成功。

R1-A2 legacy 成交額 migration 的可重建 fixture 八案例已有限接受，只支持關閉後讀回、既存狀態保留及指定 trigger 失敗回復；不證任何正式 DB 已升級、API readiness 或 backup restore。fixture／路徑限度見[資料來源](DATA_SOURCES.md#r1-a2-legacy-成交額-migration-磁碟驗收有限接受)，專用驗證命令與隔離／清理行為見[開發入口](development-baseline/README.md#r1-a2-legacy-成交額-migration-的磁碟驗證入口)。正式升級與復原仍依下列順序另行授權。

### 2.1 安全升級與復原順序

1. 唯讀解析實際 DB 絕對路徑，記錄 revision、schema、size、mtime、hash。
2. 使用 SQLite backup API 或等價一致性機制建立專案外具名副本；有 WAL 或尚未確認 writer／sidecar 狀態時，不裸複製主檔。
3. 在副本記錄完整 before evidence，確認 Alembic 可 import 且版本正確，再執行 `init-db`／upgrade。
4. 驗 revision、schema diff、共同欄位內容、row counts、PK／FK／UNIQUE、`integrity_check`、`foreign_key_check` 與第二次執行冪等。
5. 另外驗 recovery：forward-only migration 的做法是丟棄故障副本，從 consistent backup 還原到新的隔離路徑；未實跑就標未執行。
6. 最後再次唯讀確認來源 DB 未變。正式升級、restore 與 deployment 需要各自具名授權及驗收。

Migration helpers 只接受有限 canonical SQLite legacy shapes，並在 destructive DDL 前拒絕未知 schema、constraints、indexes、triggers、views、FK、scratch／TEMP shadow 或 marker 矛盾。遇到拒絕時保留 DB 與錯誤，回到 consistent backup 的新副本診斷；不要手動刪 scratch、補 marker、關 FK 或反覆執行嘗試 salvage。可保存形狀見 [R0 §8.7](R0_IMPLEMENTATION.md#87-round28-c028canonical-legacy-instruments-identity-rebuild-rollbackfail-closed有限-review) 與 [§8.8](R0_IMPLEMENTATION.md#88-round29-c029canonical-legacy-signal_settlements-identity-rebuild-rollbackfail-closed有限-review)。

## 3. 現有 worker CLI

| 指令 | 行為與限制 |
| --- | --- |
| `python -m worker.cli init-db` | 建立／升級指定 DB；先確認路徑、backup 與授權。 |
| `python -m worker.cli collect --date YYYY-MM-DD --months-back 0` | 官方來源收集；`months-back` 只接受 0、1、2、3。 |
| `python -m worker.cli daily --date YYYY-MM-DD --months-back 0` | collect 成功才 analyze；analyze 之後跑指標批次（不論 analyze 結果）；analyze 成功才 evaluate。 |
| `python -m worker.cli backfill --start-date YYYY-MM-DD --end-date YYYY-MM-DD --scope market` | 有界官方回補、重試與稽核；不是 backtest。 |
| `python -m worker.cli analyze` | 要求最新官方 collect run success 與有效 as-of；沒有 `--date`，也不是任意局部分析器。 |
| `python -m worker.cli evaluate` | 更新 execution／tracking 與 T+5／T+20 settlement；會寫 DB。 |
| `python -m worker.cli backtest --start-date YYYY-MM-DD --end-date YYYY-MM-DD` | 回放既有資料並保存 audit；不下載歷史資料。 |
| `python -m worker.cli indicators [--date YYYY-MM-DD] [--rebuild]` | 以保存日線算 [技術指標](V1_SPEC.md#技術指標) 寫入 `technical_indicators`；不發網路、不改日線。預設（每日）對每檔寫上次已算日之後到 `--date`（預設 DB 最新日線日）的列，通常就是最新一日；若最後一筆已算值與重算不符（日線回補／更正或除權息晚到）就整檔重寫。`--rebuild` 重寫全部歷史，回補日線或升版後用。不會跑 `init-db`，表不存在時回 `technical_indicators_table_missing_run_init_db`。 |

`backfill --scope` 支援 `market`、`portfolio`、`watchlist`、`events`、`candidates`、`priority`、`all`；名稱存在不代表資料來源或管理 UI 完整。起日不得晚於迄日，輸入差不超過 `OFFICIAL_MAX_BACKFILL_DAYS=93`；目標有效交易日不足時，候選查詢可早於輸入起日，但不得超過迄日前 93 日界線。批次最多 5 個交易日，adapter 逐日呼叫；重試規則是立即 3 次、後續 2 次。`--force` 會重新擷取已完成日期，並非一般重試預設。

`candidates`／`priority` 的 group-score 納入範圍已有限 review：typed 依 DB-local ID＋pair 精確收斂，legacy symbol 為避免漏抓可納入所有 active exchange；這不是 decision selection。`/api/coverage` 同名 scope 重用此 resolver。完整規則與 public source-day 展示分見 [產業分類 §9.5](INDUSTRY_CLASSIFICATION.md#95-backfillcoverage-的候選納入契約) 與 [§9.6](INDUSTRY_CLASSIFICATION.md#96-public-candidate-的-source-day-身分展示契約)。

Backfill run 建立時把 `metadata.target_instruments` 固定為 snapshot；既有 run 的 resume／`--force` 不重新 resolve，修正只作用於新建或實際重新 resolve 的範圍。

範例日期只作隔離研究，不表示資料已完整：

```powershell
python -m worker.cli collect --date 2026-09-08 --months-back 0
python -m worker.cli backfill --start-date 2026-06-10 --end-date 2026-09-08 --scope market
python -m worker.cli analyze
python -m worker.cli evaluate
python -m worker.cli backtest --start-date 2026-06-10 --end-date 2026-09-08
```

先檢查 run status、有效 sessions、缺欄／缺日與 raw evidence。collect 為 partial／failed 時，`daily` 不執行後續；不得人工改 status 繞過 gate。

## 4. Source registry 與 capture

`worker.source_registry` 的 import／validate／inspect 不發 HTTP、不開 DB，也不接 legacy collector。所有命令都必須使用外部已 review pins；不能從待驗 manifest 自己讀 version／digest 後宣稱已 pinned。

```powershell
$env:PYTHONPATH = (Join-Path $PWD 'backend')
$registryPath = (Join-Path $PWD 'backend/worker/source_registry.json')
$expectedRegistryVersion = 'r1-a1-c009-2026-09-12.1'
$expectedRegistryDigest = 'sha256:eb6c290d7716300c4117bb2cdc61a66cbf8d62e344870928933b44b77461f87b'

python -m worker.source_registry validate `
  --manifest $registryPath `
  --expected-registry-version $expectedRegistryVersion `
  --expected-digest $expectedRegistryDigest

foreach ($purpose in 'local_fetch','raw_store','summarize','historical_pit') {
  python -m worker.source_registry inspect `
    --manifest $registryPath `
    --profile free_public_local `
    --purpose $purpose `
    --expected-registry-version $expectedRegistryVersion `
    --expected-digest $expectedRegistryDigest
}
```

`allow` 只代表該 profile／purpose 的 eligibility；`restricted`／`unsupported` 與 reasons 必須保留。完整矩陣見 [SOURCE_REGISTRY](SOURCE_REGISTRY.md)。

`source_runtime capture` 是 standalone raw capture，不是 `collect`／`daily`／`backfill`，也不碰 DB。只有驗證目標需要實際 capture 時才落盤；`source_registry validate`／`inspect` 只輸出結果，不建立 capture 產物。先選用已授權、已存在的專案外 research output parent，明確決定這次唯一 output directory；不得把範例改回每次自動建立的隨機 Temp。output directory 必須不存在或為空，且不能位於 workspace 或正式／`.local` data 路徑。

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$captureParent = (Resolve-Path -LiteralPath $env:STOCK_RESEARCH_OUTPUT_PARENT).Path
$captureOutputDir = Join-Path $captureParent 'twse-stock-day-all-capture'

python -m worker.source_runtime capture `
  --manifest $registryPath `
  --profile free_public_local `
  --source twse_stock_day_all `
  --expected-registry-version $expectedRegistryVersion `
  --expected-digest $expectedRegistryDigest `
  --output-dir $captureOutputDir
```

`STOCK_RESEARCH_OUTPUT_PARENT` 只是操作端指向既有、已授權 parent 的變數，runtime 不會自行讀取。執行前依 [開發入口](development-baseline/README.md) 確認目的、產物上限與清理條件；預期只有一個 `capture.zip`，body 上限 5 MiB，另加小型 receipt／ZIP overhead。只清理本次擁有且已核對的路徑。

`--source` 只接受 `twse_stock_day_all`、`twse_holiday_schedule`、`twse_twt48u_all`、`tpex_spendi_history`、`tpex_3insti_daily_trading`；後者仍須 [SOURCE_REGISTRY §8](SOURCE_REGISTRY.md#8-m1-p2atpex-日法人來源與-selected-摘要) 的 explicit 單來源 manifest 與 pins，不沿用原 snapshot 四來源的 registry version。另有 memory-only 模式（`source-memory-capture/v1` receipt，不落盤），目前只對 `twse_twt48u_all` 開放，由 library caller 使用，CLI 範例不涵蓋。preflight failure 是 zero request、stdout failure receipt、exit 2；成功 bundle 內含 `body.bin` 與 `receipt.json`。request、validation、timeout、publication 與 capture-time 邊界見 [SOURCE_REGISTRY §4](SOURCE_REGISTRY.md#4-standalone-source-capture)。

`STOCK_DAY_ALL` 與 holiday bundle consumer 都是 caller 明確 opt-in 的 Python library，沒有 CLI。三個 `STOCK_*` 必須在 import `worker.sources`／`worker.pipeline` 前設為隔離路徑；同 request key 已有 `status=success` 的 run、`records>0`、metadata 的 `taiex_records>0` 且 `force=False` 時直接 reuse；需要驗本次 consumer 接線時用 `force=True` 重新處理該 request。兩者的輸入範圍、fail-closed 與非 PIT 邊界見 [SOURCE_REGISTRY §5.1](SOURCE_REGISTRY.md#51-stock_day_all-selected-security-bars) 及 [§5.2](SOURCE_REGISTRY.md#52-holidayschedule-positive-exclusion)。

TPEx suspension／action 與 TWSE action 修正只有有限 normalization／read-time 行為，沒有 retroactive repair；`force=True` 不會刪舊錯 Event，也不保證修復所有舊 bar 或重算既存 evaluation。精確來源契約見 [SOURCE_REGISTRY §6](SOURCE_REGISTRY.md#6-tpextwse-有限資料品質契約)，不得把 refetch 當成 cleanup／replay。

## 5. 獨立 artifact 與時間投影

下列能力是明確 opt-in 的 local Python API，沒有 CLI、預設 DB 路徑或 legacy migration；caller 必須提供專案外專用 SQLite 路徑，不能使用 `STOCK_DB_PATH`、正式 `data/stock.db`、`.local` 或其他 workspace 路徑。

| 能力 | 現行入口 | 邊界 |
| --- | --- | --- |
| signal artifact | `SignalArtifactStore(path)`、`save_artifact`、exact／filtered readers | `signal-artifact/v1`；immutable local research store；不接 API/UI/worker/default。詳見 [SIGNAL_ARTIFACTS](SIGNAL_ARTIFACTS.md)。 |

reader 使用前先取得 stable SQLite backup/checkpoint。缺檔、live WAL／SHM／journal、ownership/schema 不符或讀取中 fingerprint 改變均應拒絕；跨 DB identity 不可假裝由 FK 保證。`generated_at`、attempt、run relation、idempotent replay、collision 與 null/reason 的精確契約以各專文為準。

`product-time/v1` 是既有 API/UI 的 read-time projection，不寫 DB，也不會把 unknown 升格為來源 truth。known instant 必須含 offset；date-only 不補午夜；legacy `data_cutoff`、naive `created_at` 與 date fields 不能推導 decision／availability。詳見 [R0 §7.2](R0_IMPLEMENTATION.md#72-round08-c008b5a-產品-read-time-projection有限-review)。

## 6. 資料品質與研究結果

- 逐用途檢查交易所、標的、日期與欄位；行情 success 不代表 chips、events、actions 完整。
- 只有官方明確 no-data 無列日可略過；錯日、缺日、未知日期、解析失敗保留缺漏。
- 時間、停牌、公司行動或同日 stop／target 順序無法證明時，fail-closed 或標 incomparable，不假設有利成交。
- 買賣各 5 bps 與 30 bps round-trip 是現行執行假設，不是真實通用費率。
- legacy entry、breakout、pullback、invalid、targets 是規則參考價，不是持倉成本、委託或成交；`cost_included=false` 只表示 level 公式未扣成本。
- `data_cutoff`、`signal_date`、`earliest_execution_date`、naive `created_at` 都不能證明 `decision_at`。unknown time／basis 必須連同 reason 保留。
- `/api/ingestion-runs`、`/api/backfill-runs`、`/api/data-quality`、`/api/backtest/summary` 提供稽核摘要，`/api/coverage` 提供 coverage。前端入口為 `/research/backtest`、`/research/coverage`；舊 `/backtest` 是相容 redirect。
- 短回測依 v1 為 `insufficient_sample`；較長範圍仍需樣本外與執行驗證。

產業分類 run、ordinary receipt、ETF／newlisting 子 scope 必須分開讀。current mapping、觀測日 D、listing date L、60 日窗口、transition／rollback 與前端 guard 以 [產業分類契約](INDUSTRY_CLASSIFICATION.md) 為準；正式資料未修復前，不能把其中一個 success 擴寫成全分類 verified。

## 7. 程式與前端驗證

歷史 pass counts 不代表目前 checkout。依實際變更選擇測試，記錄命令、exit、pass／fail／skip 與限制；文件修改只檢查 diff、連結與內容一致性。測試資料與落盤原則見 [開發入口](development-baseline/README.md) 及 [AGENTS](../AGENTS.md#工程原則)；後端測試不得指向正式 DB。

```powershell
Push-Location frontend
pnpm run build
Pop-Location

& ./tools/Invoke-Validation.ps1 -TestPaths @('backend/tests')
```

個股頁驗收見 [STOCK_RESEARCH_PAGE](STOCK_RESEARCH_PAGE.md)，全站 UX 見 [UX_REVIEW](UX_REVIEW.md)。瀏覽器使用隔離 API；沿用其他任務服務須確認安全、owner 同意及版本適用，並核對實際載入的版本與連線。不得啟動會寫正式／`.local` DB 的舊 lifespan 或干擾其他服務。fixture、screenshot、typecheck、build 與真 API 的證據不能互相取代。

## 8. 排程

每日排程以 Windows 工作排程器執行 worker 與新聞任務（[ROADMAP V1-G1](ROADMAP.md#v1-範圍基線2026-10-17-核定)）；排程須定義來源延遲、rate limit、冪等、錯誤可見性與日誌位置；自動下單不在第一版範圍。現行任務／AC 查原 GitHub Issue 及規格；文件、fixture、外部 startup 或 readiness 不證任務完成。
