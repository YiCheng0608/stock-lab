# 開發與驗證入口

協作、資料選擇、保留例外及清理失敗的唯一規則見 [AGENTS](../../AGENTS.md#驗證資料與暫存)；接手狀態見[協作紀錄](../TASK_COORDINATION.md)。

## 版本與資料

使用 `git status --short`、`git diff`、`git log -1` 核對來源。`.gitattributes` 固定 LF，避免改變 replay 綁定的 source bytes。Git 保存測試程式與 fixture 建構方式，不備份本機 DB、raw、依賴或生成產物。

資料與落盤選擇依 [AGENTS](../../AGENTS.md#驗證資料與暫存)；磁碟驗收使用專案外最小隔離檔案，並遵守該測試的 snapshot 契約。

## 後端驗證

依變更選必要範圍；純文件只核對差異、連結與內容。以下從專案根目錄執行，完整 backend 不是每次修改或每角色必跑：

```powershell
# 預設：啟動與 migration 邊界
& ./tools/Invoke-Validation.ps1

# 需要完整回歸時
& ./tools/Invoke-Validation.ps1 -TestPaths @('backend/tests')
```

入口優先使用目前使用者的 bundled Python，否則使用 PATH，也可傳 `-PythonPath`。完整 replay 需要 CPython 3.12.14，不得放寬 runtime/source binding。依賴來自 `backend/.deps`、`backend/.validation-deps` 或所選環境；重建依 `backend/requirements.txt`，[驗證版本清單](validation-requirements.lock.txt)可作 constraints，並非附 wheel hash 的跨平台 lockfile。

### 現行入口的落盤行為

每次呼叫仍會建立專案外唯一目錄，將三個 `STOCK_*`、`TEMP`／`TMP` 及 pytest basetemp 指向該處。`finally` 還原環境並嘗試清理；`-KeepArtifacts` 跳過清理，依 AGENTS 預設不得使用。入口尚無自動數量／大小限制，也尚未全部改成記憶體測試。

測試與清理結果、殘留預算及例外處理依 AGENTS，原始結果留 task。

### R1-A2 legacy 成交額 migration 的磁碟驗證入口

專用入口直接以 unittest 分別執行兩條路徑各四案例，共八個子程序，不載入一般 pytest conftest。一般 pytest 未提供專用環境時會略過這八個案例，不能將八個 skip 當成磁碟驗收通過。精確 fixture、Alembic／fallback marker 及 synthetic nullable NULL 限度由[資料來源](../DATA_SOURCES.md#r1-a2-legacy-成交額-migration-磁碟驗收有限接受)負責。

```powershell
$migrationDependencyRoots = 'C:/path/to/shared/backend/.deps;C:/path/to/shared/backend/.validation-deps'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./tools/Invoke-TurnoverMigrationValidation.ps1 -RunOwner '01a10109' -DependencyRoots $migrationDependencyRoots
```

先將依賴範例改成已核實的既有目錄；`-DependencyRoots` 接受分號分隔字串，可共用唯讀依賴，不另建環境。上例只對該 PowerShell 子程序使用 `ExecutionPolicy Bypass`，不修改全域 policy。`-RunOwner` 必填八個 ASCII 英數字元；範例是本輪 owner，後續執行須改成該 task 核定的 owner。`-PythonPath` 可另指定已存在的 Python，預設使用 bundled Python。入口不提供 `KeepArtifacts`。

每次只建立 `LocalAppData/Temp/taiwan-stock-r1a2-<RunOwner>-<UUID>` 唯一根，將三個 `STOCK_*` 與 `TEMP`／`TMP` 指向根內 `data`／`raw`；import 的目錄副作用包含在配額中，停用 Python bytecode 落盤。八案例順序執行，每案例一個 `data/legacy.db`，自有檔案只准 DB 與其 journal；根、data、raw 合計上限 **3 directories／2 files／2 MiB**，單個 DB 上限 **1 MiB**。每案例後清理 DB／journal，`finally` 還原環境並清理本次根；只清理核對過的絕對路徑及自有檔案／目錄，遇到 reparse point 或額外檔案／目錄拒絕清理並分報，清理失敗即停止新增案例。

stdout／stderr 均在記憶體捕獲，stderr 的進度或 Alembic log 不作非零 exit；以程序 exit、八份各一個且無 skip 的 metrics 及 `validation_complete` 核對執行是否完整。`R1A2_RESULT` 分列 `test_exit`、`cleanup_exit` 與殘留路徑／大小／原因，測試失敗不得由清理成功覆蓋；命令、版本與逐 run 數值留 task。本輪專用入口首跑八案例全過、無 skip，程序／測試與清理 exit 0，統籌亦核對唯一隔離根已不存在、無新增殘留；舊殘留未清理。

這是可重建 fixture 的有限磁碟驗收，不代表 API startup、正式 DB、restore／deployment、UI 或完整 backend 通過。既有 Alembic `path_separator` deprecation warning 保留，本批未改設定；來源、pins、正式資料及其餘待驗範圍不變。

### R1-A2 selected invalid／拒收的磁碟驗證入口

專用 `tools/Invoke-StockDaySelectedInvalidValidation.ps1` 直接執行 `backend/tests/test_stock_day_selected_invalid_file_integration.py` 的一個組合 unittest，不載入一般 pytest conftest；第三次實測已有限接受。普通 pytest 未提供專用環境時，該 module 的 `SkipTest` 不代表磁碟驗收通過。精確三種 invalid／四類拒收與來源限度由[資料來源](../DATA_SOURCES.md#r1-a2-selected-invalid拒收磁碟整合有限接受)負責。

```powershell
$selectedInvalidDependencyRoots = 'C:/Users/YiCheng/Desktop/taiwan-stock-research/backend/.deps;C:/Users/YiCheng/Desktop/taiwan-stock-research/backend/.validation-deps'
$selectedInvalidRoot = 'C:/Users/YiCheng/AppData/Local/Temp/taiwan-stock-r1a2-si-01a10137-<task-approved-32-hex>'
$selectedInvalidPython = 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./tools/Invoke-StockDaySelectedInvalidValidation.ps1 -RunOwner '01a10137' -ValidationRoot $selectedInvalidRoot -PythonPath $selectedInvalidPython -DependencyRoots $selectedInvalidDependencyRoots
```

這是本輪 runner 的實際參數形式；依賴為已核實的主線唯讀共用目錄，Python 預設使用 bundled 3.12.14，也可用 `-PythonPath` 明示既有路徑。執行前將 placeholder 換成原 task 事先核定的 32 位小寫 hex；本輪完整已用命令及 exact 根留原 task。後續必須由該 task 重新核定 owner、新的唯一絕對根與額度，不能直接沿用上例已用 owner／root。`-RunOwner` 必填八個 ASCII 英數字元，`-ValidationRoot` 須為 `LocalAppData/Temp` 的直屬目錄、符合 `taiwan-stock-r1a2-si-<owner>-<32-hex>` 且位於專案外；已存在的根拒用。`ExecutionPolicy Bypass` 只作用於上述子程序，不改全域 policy，入口不提供 `KeepArtifacts`。

本輪只核定一個磁碟根；環境與 import 目錄副作用均收斂於該根，將三個 `STOCK_*`、專用 runner 環境及 `TEMP`／`TMP` 設為核定範圍，並停用 bytecode 落盤。自有內容只含 `data/selected-invalid.db`／journal、`capture/capture.zip`／必要 staging／lock，以及 `raw/body.bin`／`receipt.json`／lock；不另建環境、複製正式 DB、抓外網或產生附件。含根及暫態檔的總量上限 **4 directories／5 files／2 MiB**，單個 DB **1 MiB**、ZIP／capture staging **64 KiB**、body 與 receipt 各 **32 KiB**；測試檢查點及程序退出時核對配額，DB 另限制 4096-byte page／最多 256 pages。不可改根或保留成功產物來繞過配額。

核定路徑為 production capture／load／select→`TwseAdapter.fetch`→`OfficialMarketDataAdapter` 正常去重→`collect(force)`，再 dispose／新 engine 讀回同一檔並核對 API。非目標端點使用記憶體 fixture，TPEx 只給明示空 `OfficialBatch` 邊界，未驗 TPEx；測試不改產品來源或 consumer。stdout／stderr 在記憶體捕獲，程序上限 60 秒，只停止本次自有測試程序；需一份 `R1A2_SELECTED_INVALID_METRICS`、`tests_run=1`／`skipped=0` 及 `validation_complete` 才支持完整執行。`R1A2_SELECTED_INVALID_RESULT` 分報程序／測試 exit、cleanup exit 及確切殘留路徑／大小／原因。

`finally` 還原環境，成功或失敗均嘗試清理已核對的本 task 自有絕對路徑；reparse point 或額外檔案／目錄會拒絕清理並分報。清理成功不能把失敗測試改報通過，清理失敗亦不否定有效測試證據；仍達殘留上限時暫緩新增落盤，依 AGENTS 繼續其他工作。

本輪第三次實測 **1 compound unittest／0 skip** 通過，程序／測試與清理 exit 0，`residuals=[]`；統籌獨立核對本輪核定根不存在、無新增測試殘留。觀測峰值 **5 files／4 directories／517,248 bytes**，DB **458,752 bytes**，均在本輪核定額度內。先前載入前 policy 失敗未跑測試、未落盤，兩次實測失敗均清理成功；原失敗／修正與成功收據留 task，不能稱首跑通過。保留 Starlette／TestClient httpx deprecation warning；未跑完整 backend、production API startup／lifespan、UI、live、TPEx、正式 DB 或 legacy migration 八案例，不外推通過。命令／版本與原始收據只留原 task。

### R1-A2 legacy 成交量的零落盤驗證入口

從專案根目錄直接執行 [test_legacy_daily_volume.py](../../backend/tests/test_legacy_daily_volume.py) 的 unittest，不載入一般 pytest conftest 或真實 `app.config`，也不使用會建隔離磁碟根的 `Invoke-Validation.ps1`。精確數值格式、別名與 fixture 支持範圍只由[資料來源](../DATA_SOURCES.md#r1-a2-legacy-日行情成交量精確整數-gate有限接受)負責。

```powershell
$volumePreviousDeps = $env:STOCK_TEST_DEPS
try {
    $env:STOCK_TEST_DEPS = 'C:/Users/YiCheng/Desktop/taiwan-stock-research/backend/.deps;C:/Users/YiCheng/Desktop/taiwan-stock-research/backend/.validation-deps'
    & 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -X utf8 ./backend/tests/test_legacy_daily_volume.py
    $volumeTestExit = $LASTEXITCODE
} finally {
    $env:STOCK_TEST_DEPS = $volumePreviousDeps
}
```

依賴是已存在且已核實的主線唯讀目錄，不另建環境；本次實際 Python **3.12.14**、httpx **0.28.1**。`-B` 與測試內 `sys.dont_write_bytecode` 禁用 pycache；standalone 入口用臨時 `app.config` module stub 提供 93 日常數及不會使用的 `memory-unused/raw`，再 import 真實 `worker.sources`。一般測試 import 不會套用此 standalone stub；若改走 pytest，須先另核其 conftest／設定副作用，不能引用本入口當零落盤證據。

本入口新增產物／殘留配額均為 **0**。audit guard 在來源 import 前啟用，拒絕檔案寫入、建刪目錄、其他檔案變更、subprocess 與網路操作，必要 source／依賴檔案只讀；adapter `_fetch` 則替換為記憶體 payload／metadata，fixture path 不建立或讀取 raw body。程序 exit 與最後 `subcases`／`blocked_io` 一併核對，遭阻擋 I/O 會使程序失敗，不能只看 unittest 的方法數。

首次 direct run **10 methods／219 subcases／0 skip**、exit 0、`blocked_io=0` 已由統籌有限接受；統籌獨立數值與 write／network audit 核對亦通過，`memory-unused`、`data` 與 app／worker／tests pycache 未新增。無新增測試產物，無需測試清理；舊殘留不動。這未執行 capture、collect、SQLite、API、live、UI 或 production startup，不作磁碟保存／重開或完整 backend 驗收。版本、完整命令與原始 stdout／stderr 留 task，不另建附件。

### R1-A2 legacy 成交量的磁碟整合驗證入口

專用 `tools/Invoke-LegacyDailyVolumeValidation.ps1` 直接執行 `backend/tests/test_legacy_daily_volume_file_integration.py` 的一個組合 unittest，不載入一般 pytest conftest；首次實際磁碟測試 **1 compound unittest／0 skip** 已由統籌有限接受。六個合法／24 個拒收標的、兩次 force collect、磁碟重開及 60 個 HTTP 回應的精確支持邊界只由[資料來源](../DATA_SOURCES.md#r1-a2-legacy-成交量磁碟整合)負責。

```powershell
$legacyVolumeDependencyRoots = 'C:/Users/YiCheng/Desktop/taiwan-stock-research/backend/.deps;C:/Users/YiCheng/Desktop/taiwan-stock-research/backend/.validation-deps'
$legacyVolumeRoot = 'C:/Users/YiCheng/AppData/Local/Temp/taiwan-stock-r1a2-lv-<task-approved-8-char-owner>-<task-approved-32-hex>'
$legacyVolumePython = 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./tools/Invoke-LegacyDailyVolumeValidation.ps1 -RunOwner '<task-approved-8-char-owner>' -ValidationRoot $legacyVolumeRoot -PythonPath $legacyVolumePython -DependencyRoots $legacyVolumeDependencyRoots
```

這是參數模板，執行前須將 placeholders 換成該 task 核定的八個 ASCII 英數 owner 與 32 位小寫 hex；根須是 `LocalAppData/Temp` 的直屬目錄、位於專案外且建立前不存在，已用根拒用。exact UUID／命令留 task，不另存逐輪附件；後續執行需另由該 task 核定 owner、唯一根與落盤範圍。借用已核實的主線唯讀共用依賴，不另建環境；實際 Python **3.12.14**、SQLite **3.53.1**，其他版本留原 metrics。`ExecutionPolicy Bypass` 只作用於上述子程序，不改全域 policy；本輪首次直接 `& .ps1` 曾在載入前被 policy 拒絕，runner／test 未啟動且無 metrics／磁碟根，外層 exit 0 不支持通過，其後首次實際磁碟測試才通過。

本輪只核定一個根，內容限 `data/legacy-volume.db`／journal，以及 `raw/twse/2026/09/05`、`raw/tpex/2026/09/05` 下六份 target body／六份 metadata；raw 檔名須符合 64 位小寫 SHA-256 hex 的 `.json`／`.meta.json`，ancillary payload／metadata 留記憶體。三個 `STOCK_*`、專用驗證環境及 `TEMP`／`TMP` 綁定核定根，停用 bytecode 落盤，不建立 capture ZIP、來源副本、正式 DB 或額外附件。含根與暫態檔的上限為 **14 files／11 directories／3 MiB**；DB 與 journal 各 **1 MiB**，每個 raw JSON **32 KiB**、metadata **8 KiB**；測試檢查點及程序退出時核配額。入口不提供 `KeepArtifacts`。

stdout／stderr 在記憶體捕獲，程序上限 60 秒，只停止本次自有測試程序；需一份 `R1A2_LEGACY_VOLUME_METRICS`、`tests_run=1`／`skipped=0` 及 `validation_complete=true` 才支持完整執行。`R1A2_LEGACY_VOLUME_RESULT` 分報 test／cleanup exit、確切殘留路徑／大小／原因；`finally` 還原環境，成功或失敗均只嘗試清理本 task 擁有、已核對的 exact 絕對根與已知非 reparse 內容，額外檔案／目錄或 reparse 拒絕清理並分報。清理成功不把失敗測試改成通過，清理失敗不否定有效測試證據；達殘留上限只暫緩新增落盤。

首次實際磁碟測試的程序／test／cleanup exit 均為 **0**、`validation_complete=true`、`residuals=[]`；統籌獨立核對核定根不存在，無本輪新增測試殘留。觀測總峰值 **14 files／11 directories／605,668 bytes**，DB 峰值 **585,728 bytes**、journal 峰值 **78,488 bytes**，均在核定上限內。audit guard 的五個預期拒絕 probe 不執行實際 I/O，unexpected denial 為 0；八個 stdlib 本地 socketpair 事件屬 TestClient／asyncio 內部喚醒，不是外網抓取。保留 Starlette TestClient deprecation warning，未新增依賴。其他未跑項見資料來源；舊 219 subcases、selected invalid 與 migration 的有效證據未重跑，舊殘留不動。版本、原始 stdout／stderr 與收據只留 task，不為回寫 hash 再改文件。

### M1-P3b 記憶體事件接線的驗收入口

本輪額外測試落盤配額為 0，不能直接套用上述會建立隔離目錄的入口；也須先辨識 pytest conftest、App 啟動與 import 的 DB／目錄副作用。純計算、selected／receipt 拒收與 API 投影優先以不載入 conftest 的記憶體 fixture 驗證；實際來源與產品操作另外具名核對，不能用 fixture 或記憶體 App bundle 代替 live／production 驗收。限制與既有殘留見[協作紀錄](../TASK_COORDINATION.md)。

server `STOCK_TWSE_EVENTS_MEMORY_CAPTURE=1` 明示啟用 `POST /api/stocks/{exchange}/{symbol}/official-events/capture?as_of=YYYY-MM-DD`，不需 body 參數；普通 GET／import 不抓外網，成功後只有 process 記憶體原件再用，不寫 DB／檔案。程式、原件／API 與具名桌面／窄版操作已有限接受；API／UI 契約與驗收邊界見[個股頁 §11](../STOCK_RESEARCH_PAGE.md#11-m1-p3bselected-官方事件總覽接線)。本輪靶向回歸、前端型別／SSR 與記憶體全 App bundle 通過，未跑完整 backend／production Vite build；驗收用 memory catalogue 不代表真行情或 DB 證據。測試命令、版本、exit、結果與限制留本輪 task，不另存產物或解除已有清理拒絕。

### M2-P1 官方事件關注清單的驗收入口

本批新增 `GET /api/focus/official-events?as_of=YYYY-MM-DD` 與首次明示 `POST /api/focus/official-events/capture?as_of=YYYY-MM-DD`，共用 P3b 的固定來源／啟用值／cache／鎖，程式與具名操作已有限 review。額外落盤配額仍為 0，不能直接載入會建立目錄的 conftest 或把隔離 memory catalogue 當真行情／正式 DB；純記憶體 consumer／API 邊界與一次真原件 58 列／API／桌面／窄版操作已分開接受。操作、未支援範圍及清理結果見[個股頁 §12](../STOCK_RESEARCH_PAGE.md#12-m2-p1官方事件關注清單接個股總覽)；後端必要記憶體回歸、前端型別／SSR／記憶體 bundle 通過，完整 backend／production Vite build 未跑，不因記憶體 bundle 成功稱通過。原件未保存、不能離線重播；命令／版本／exit／hash 與失敗／退修及最終收據只留本輪 task，無新增附件／暫存。

### M2-P2 搜尋與研究往返的驗收入口

沿用 M2-P1 明示取得與零額外落盤入口，GET／POST 可帶 optional `q`；原始最多 100 個 Unicode 字元、全 feed 驗證後搜尋再套上限，純記憶體測試須另驗匹配外壞列、101 股以上與同股名稱／完整事件，不能只對前 100 股或 live 58 股聲稱完整邊界驗收。統籌已有限接受實際原件／API 與搜尋／M1 往返、截止切換及窄版操作，以及 78 個記憶體測試、前端型別／最終 16 組 SSR／全 App 記憶體 bundle 的 exit 0，該輪已 freeze／索引／本地 commit。精確支持範圍及未跑項見[個股頁 §13](../STOCK_RESEARCH_PAGE.md#13-m2-p2官方事件清單搜尋與研究往返)；完整 backend／production Vite build 未跑，不以 fixture、memory catalogue 或記憶體 bundle 代替來源／DB／production 驗收。首輪測試／SSR helper 失敗與修正後成功分留 task；命令、版本、exit、原件 hash 與 QA 清理收據留本輪 task，不另建附件，既有殘留及零落盤限制保留。

### M1／R1-A2 成交量精確呈現的零落盤驗證入口

後端及 Node 必要記憶體驗證、完整字串邊界複驗、TWSE／TPEx 具名操作與新增產物／殘留為 0 已有限接受。專用 `backend/tests/test_volume_exact_presentation.py`、前端必要 units／chart／overview 記憶體測試與 `tools/volume-exact-preview.cjs` 分別核對純 helper、實際 router API／JSON parse 及具名 UI 操作；精確相容、股／張、兩市場固定 synthetic fixture、操作方式與來源 gate 只由[個股頁 §14](../STOCK_RESEARCH_PAGE.md#14-m1r1-a2成交量-httpjavascript個股精確呈現)詳述。命令、版本、exit 與原始收據留 task，不另存附件。

上述專用後端檔以 standalone unittest、`-B -X utf8` 直接執行，不載入一般 pytest conftest、`app.main` 或 production lifespan。僅 standalone 入口從實際 `app.config` 原文的 AST 常數建立設定 stub，略過 mkdir，DB 使用 `:memory:`；一般 suite import 不安裝這套 hook，不能把本入口當作一般 pytest 的零落盤證據。測試沿用實際 router 與記憶體 SQLite，不操作正式 DB；僅 `_capture_evidence` 的 memory patch 服務 fixture，不重驗既有檔案 gate 或替代真來源證據，TPEx 總覽的 unavailable 不放寬。audit／入口須拒絕磁碟變更、外網及未授權 subprocess，依賴只讀已核實的主線目錄，不安裝或另建環境。

Node preview／檢查只作記憶體 bundle，`write:false`、無輸出檔；preview 限本機 loopback，實際 fixture API 回應經 `Response.json()` 後的精確字串及具名操作另核。外部字型 import 只在 preview 的記憶體 CSS 略過並由 CSP 阻外網，本輪呈現驗收限 fallback font；不修改正式字型契約。新增測試／preview 產物與殘留配額均為 **0**，不使用會落盤的通用 runner 或 `KeepArtifacts`。全 App 記憶體 bundle 不當 production Vite build；完整 backend、production startup、正式 DB、磁碟重開、真官方／live 與完整 M1／PIT 不由此入口追認。自有 QA tab、兩個 server 程序與 listener 已核實關閉／不存在，測試產物／殘留為 0；direct tests／Node check 的 exit 0 與兩個 serve 的 exit 1 分報，不稱正常 exit 0 或完整 serve audit。版本、完整命令及原始收據留 task，不另建附件，舊殘留維持原狀。

### M3-P1 既有庫存股數的零落盤驗證入口

本節保留 M3-P1 當時「既有可信庫存股數→精確張／零股／原股呈現與失精輸入拒收」的有限驗收；同名入口在 M3-P2 的現行模式與必要磁碟驗收見下一節，歷史計數不冒充目前來源重跑。股數 gate、精確字串、unsafe／fallback 及輸入單位上限只由 [UI 文案 §10.3](../UI_COPY_SPEC.md#m3-p1-既有庫存股數的有限呈現契約)負責；本節只列原入口、副作用與驗收邊界。專用 `backend/tests/test_share_quantity_exact_presentation.py`、前端必要記憶體驗證與 `tools/share-quantity-exact-preview.cjs` 的命令、版本、exit 及原始收據留 task，不另存附件。

後端入口採 standalone unittest、`-B -X utf8` 及 AST config 常數 stub，排除真 config 的 mkdir，不載入一般 pytest conftest、`app.main`／production lifespan，也不執行 init-db 或 migration。主線既有依賴只讀，不安裝或另建環境；audit 拒絕磁碟變更、外網與未授權 subprocess。實際 router 與記憶體 SQLite 核對 POST commit／refresh→GET、unsafe 舊 Float、失精輸入 HTTP 422 及既有資料保留；純 helper 的實際 int／int64 邊界與 Float 保存支持範圍分報，記憶體保存／讀回不代表磁碟 reopen。

Synthetic fixture 日期為 `2026-10-03`，只代表 TWSE／TPEx 身分下的使用者庫存數量，不當官方行情、live 或正式 DB coverage。preview 使用自有 Python `8777`／Node `8778` loopback 記憶體 server；Node bundle 使用 `write:false`、無輸出檔。必要後端複驗 **5 direct tests／0 skip／145 actual router HTTP requests**、exit 0，audit 的五次預期阻擋與 `unexpected_denials=[]` 已接受。初跑 exit 1 是非有限輸入已被 StrictInt 拒收後，error JSON 含 NaN 導致序列化失敗；before validator 將非有限原值轉成仍會拒收的 invalid 字串，修後必要複驗才 exit 0，不稱 NaN 原先被接受或首跑通過。

Node **20.19.4**／TypeScript **5.9.3** 的全 src `noEmit` 型別檢查、units、**14 組 Portfolio subsection SSR**、whole main 記憶體 bundle（JS **4,176,020 bytes**／CSS **27,903 bytes**）與 **51 個 loopback product fetch／JSON HTTP 請求**均 exit 0；SSR 的 React Router `useLayoutEffect` warning 分報。Python 來源後續未改，不因換階段重跑已接受證據。具名桌面／390px 庫存操作已由統籌接受，精確支持範圍見主契約；只在 preview 記憶體 CSS 排除外部字型並以 CSP 阻外網，本次限 fallback font，正式字型不改。

新增測試／preview 產物及殘留實際為 **0 files／0 directories／0 bytes**；未使用通用落盤 runner 或 `KeepArtifacts`。QA 已還原 `1365×900` 並關 tab；核實自有 commandline 後兩 server 的 `POST /__review__/shutdown` 各回 `stopping`、命令 exit 0，Node／Python serve 最終 exit 均 0，Python serve audit `unexpected_denials=[]`。統籌獨立核對兩個 exact PID、`8777`／`8778` listeners 均不存在，新增 artifacts／data／pycache／buildinfo／dist 為空或不存在；測試 exit 0 與清理 exit 0 分報，不混入前輪 serve exit 1。

正常估值／決策／計畫行為不作該批驗收；正式 DB、磁碟重開、真官方／live、production startup、完整 backend／production Vite build、新計畫與完整 M3 均未由 M3-P1 驗證。可信整數保存與磁碟重開由下方 M3-P2 有限補齊，不能以本節記憶體入口替代；freeze／索引／commit／merge 狀態見[協作紀錄](../TASK_COORDINATION.md)，不另建附件。

### M3-P2 可信整數保存與磁碟重開驗證入口

本批核心契約與必要有限驗證已接受；股數／字串／數字相容與拒收規則只由 [UI 文案](../UI_COPY_SPEC.md#m3-p2-可信整數保存與磁碟重開契約)負責，migration／readiness 的具體 descriptor、marker 與 rollback 邊界見 [R0 §8.11](../R0_IMPLEMENTATION.md#811-m3-p2持倉精確整數-migrationreadiness有限接受)。本節只管可重建入口、寫入副作用與有限驗收，完整命令、實際版本、exit、失敗修正與 SHA 收據留原 task。

`backend/tests/test_share_quantity_exact_presentation.py` 與新增 `backend/tests/test_share_quantity_storage.py` 均採 standalone `-B -X utf8`、AST config 常數 stub 及共用既有依賴，不載入一般 pytest conftest、不安裝或複製環境。前者是純記憶體 router／股數 guard，後者預設也不建檔；`--memory-storage` 只跑 9 個 storage memory tests。Audit 拒絕磁碟變更、外網與未授權 subprocess；5 direct tests／0 skip／193 actual router requests 與修正後 9 個 storage memory cases 已接受。初次合併 memory suite 的 13 tests 是 12 pass／1 重複 audit probe skip，由 direct suite 的 0 skip 覆蓋，不能寫成 13 全 pass／0 skip。未重跑完整 backend 或既有舊磁碟矩陣。

同一 storage runner 的磁碟模式只接受核定 `--root C:/Users/YiCheng/AppData/Local/Temp/taiwan-stock-m3-share-storage-01a10250`，明授後才執行。根與 ancestor 必須 non-reparse；最多 **2 files**（`data/quantity.db`、`data/quantity.db-journal`）、**3 directories**（root、`data`、`raw`）、總 **2 MiB**、單 DB **1 MiB**，殘留同上限。不用 WAL、pycache、一般附件或 `KeepArtifacts`，不改根避開限制。`--disk` 是四個 sequential synthetic normal／fault 案例的 compound unittest；每次驗 migration、關閉／重開、readiness 唯讀雜湊與 API int64 保存，最後對自有 exact 根嘗試清理，test／cleanup exit 分列。成功結果為 1 unittest／0 skip、四案例通過，observed peak **1 file／3 directories／425,984 bytes**、`unexpected_denials=[]`；首次連線未關閉的 cleanup 失敗與第二次 marker fixture 錯誤保留原 task，不把第三次成功倒寫成首跑通過。

`--prepare` 建立唯一 owned synthetic DB，拒絕覆寫已占用 DB；`--serve` 僅以該 DB 啟動 actual `app.main` 的 loopback 8779，由 actual lifespan 做 readonly readiness，不執行正式 DB／init-db／migration。這兩模式保留同一檔供具名保存／關閉／第二程序重開，`--inspect` 以 SQLite `mode=ro` 查 storage type、已知列與 closed-file SHA，`--cleanup` 結束這次磁碟驗收。所有模式都受 exact path／audit／inventory gate 約束；標記有值不代表任意實際 DB 已升級。Fixture 日期 `2026-10-03`，兩市場只作 synthetic 使用者股數與路由身分，不當官方行情、live 或正式持倉。

前端 `tools/share-quantity-exact-preview.cjs` 沿共用唯讀 `--deps`，`--check` 做 full src 型別、units、14 組 Portfolio SSR 與 whole main `write:false` 記憶體 bundle；`--http-check` 使用 actual fetch／Response.json 驗 75 個 product HTTP，`--serve` 使用自有 Node 8780 接已核定的 8779。Node 20.19.4／TypeScript 5.9.3 的必要驗證 exit 0；已知 warnings 分報，這不是 production Vite build。preview CSS 只在記憶體排除外部字型，CSP 阻外網，本次限 fallback font，不改正式字型。實際 desktop／390px 保存、第二程序重開、拒收完整列保留及刪除只支持 UI 主契約的具名案例；QA 還原／tab 關閉、兩 API 程序與 Node／esbuild child 的關閉、test／cleanup 與殘留分報於協作紀錄。

**本輪 capture stop 的額外副作用**：即使 preview bundle 為 `write:false`，瀏覽器擷取停止仍自動寫出 `C:/Users/YiCheng/.agent-browser/tmp/har/har-1791044803009.har`，**1 file／64,885 bytes**，超過原附件配額 0。統籌已核檔與 parents 為 non-reparse；exact 單檔 `Remove-Item` 在 CreateProcess 前遭 automatic review 拒絕（`blocked by policy`），未執行，不重試或換工具，不掃 shared HAR 目錄或刪 parent。本輪隔離 DB 已由統籌獨立核不存在；上述 HAR 殘留仍在，兩者分報，不能再稱本輪全部新增產物／殘留為 0；後續不新增測試落盤，也不把該被拒 HAR 列為下一輪可常規重試的清理。未來使用同擷取入口須先核停止時的落盤副作用與配額；本次例外不授權保留其他附件或複製整套成果。有效產品證據仍可有限接受，HAR 待外部變化／使用者處置，實際限制見[協作紀錄](../TASK_COORDINATION.md)。

本批只證 owned fixture 的有限 actual main startup、數量保存與磁碟重開；正式 DB／migration／restore、production deployment、真官方／live、完整 backend／production Vite build、大數金融估值、新 Plan、完整 M3、歷史／availability／PIT 與原來源 gate 均保持未完成。

### M3-P3 庫存價值輸入的零落盤驗證入口

本批七個程式檔、必要記憶體／前端／actual HTTP 及具名庫存操作已由統籌有限接受。三欄 API、兩欄 UI 原字串、actual `upsertPortfolio` helper 的序列化前檢核、零／null／省略及拒收保留規則只由 [UI 文案 §10.3](../UI_COPY_SPEC.md#m3-p3-庫存成本停損風險輸入可信檢核與拒收保留)負責；本節管可重建入口、副作用與有限驗收。命令、版本、原始 exit、SHA 與清理收據留 task，不另建附件。

`backend/tests/test_share_quantity_exact_presentation.py --finance-only` 採 standalone `-B -X utf8`、AST config 常數 stub、既有主線唯讀依賴與記憶體 SQLite／actual router，不載入一般 pytest conftest、真 config 的 mkdir、`app.main`／production lifespan，不執行 migration 或正式 DB。Python **3.12.14**／Pydantic **2.13.5** 的 finance-only 為 **4 tests／0 skip／331 router requests**、exit 0，拒收核完整 DB／JSON 不變，NEW／UNKNOWN 不新增；六次預期 audit denial、`unexpected_denials=[]`。必要既有股數回歸另為 **5 tests／0 skip／193 requests**、exit 0，不冒充本批磁碟重開或完整 backend 驗收。

`tools/share-quantity-exact-preview.cjs --finance-check` 沿共用唯讀 `--deps`，Node **20.19.4**／TypeScript **5.9.3** 的 full src `noEmit`、原字串 parser **11 good／25 bad**、actual helper 的 fake fetch **18 good／36 bad**、非法 fetch **0**／payload mutation **0**、**2 組 actual form SSR** 與 whole main `write:false` 記憶體 bundle 均 exit 0；JS **4,176,717 bytes**／CSS **27,903 bytes**。SSR 既有 `useLayoutEffect` warnings 分報，不能稱 console 空或 production Vite build 通過。這些都是可重建 fixture／邊界，fake fetch 不能代替下一段 actual HTTP。

本輪明授 memory server 為 Python 該入口 `--serve` 的 **8777**、Node preview `--serve` 的 **8778**，只在 owned memory fixture 保存 synthetic 使用者庫存；不承襲 M3-P2 disk fixture，不重跑其磁碟矩陣。Preview bundle 仍為 `write:false`，CSS 僅記憶體排除外部字型、CSP 阻外網；本次使用 scoped memory fetch recorder，沒有啟動會在 stop 自動落 HAR 的 capture。`--finance-http-check` 首次 exit 0，**118 actual HTTP requests／40 POST**、**36 helper 拒收／invalid POST 0／payload mutation 0**；raw 非有限輸入由 server 回 422，完整 JSON 保留。UI 原字串、helper 的序列化前輸入及 raw HTTP 各自驗收，不以 helper 拒收代替 server gate。

Actual TWSE 桌面 **1298×924** 的非零保存、TPEx **390×844** 的零／空白清欄，以及 UI 自拒收和真 router 422／draft 保留已由統籌接受；具名數值、viewport、未生效刪除與原始操作失敗只由主契約／[協作紀錄](../TASK_COORDINATION.md)保留，不複製完整 log。原 12 列完整 JSON 保持，兩 NEW 僅 memory、shutdown 後釋放，不稱已刪除或磁碟保存。

測試與清理分報：本輪必要測試 exit 0，QA 實際還原 **1365×900** 並關原 tab；Python／Node owned shutdown 各 exit 0、兩個 serve exec final exit 0，Python `unexpected_denials=[]`，統籌獨立核 exact PIDs／children／listeners 空。新增測試磁碟產物／殘留為 **0 files／0 directories／0 bytes**；前輪 HAR **64,885 bytes**、既有 review-blocked／occupied 或未知資源未動、不重試，不能稱全部歷史殘留為零，詳見[協作紀錄](../TASK_COORDINATION.md)。文件角色未重跑上述測試或造附件。

本批只補輸入 gate，不修三欄 legacy 污染或驗全部讀回、風險行動／估值；既有 market_value／unrealized_pnl 非有限輸出保護保留。Float 不宣稱十進位 exact；正式 DB／磁碟保存與重開、production deployment／Vite build、完整 backend、risk sizing、新 Plan、完整 M3、來源／tick／歷史／availability／PIT 均未驗。下一可信讀取／未知保留候選及其有界 discovery 條件由 [ROADMAP](../ROADMAP.md#接下來的順序近期產品里程碑)負責，尚未核定修法，不把 memory 取代未來必要磁碟驗收。

## 歷史驗證

歷史測試不代表目前來源已驗收；原始數據依[文件索引](../README.md#歷史查閱)取閱，已刪除的 Temp 附件不作接手依賴。
