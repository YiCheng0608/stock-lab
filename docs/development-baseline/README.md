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

### M1-P3b 記憶體事件接線的驗收入口

本輪額外測試落盤配額為 0，不能直接套用上述會建立隔離目錄的入口；也須先辨識 pytest conftest、App 啟動與 import 的 DB／目錄副作用。純計算、selected／receipt 拒收與 API 投影優先以不載入 conftest 的記憶體 fixture 驗證；實際來源與產品操作另外具名核對，不能用 fixture 或記憶體 App bundle 代替 live／production 驗收。限制與既有殘留見[協作紀錄](../TASK_COORDINATION.md)。

server `STOCK_TWSE_EVENTS_MEMORY_CAPTURE=1` 明示啟用 `POST /api/stocks/{exchange}/{symbol}/official-events/capture?as_of=YYYY-MM-DD`，不需 body 參數；普通 GET／import 不抓外網，成功後只有 process 記憶體原件再用，不寫 DB／檔案。程式、原件／API 與具名桌面／窄版操作已有限接受；API／UI 契約與驗收邊界見[個股頁 §11](../STOCK_RESEARCH_PAGE.md#11-m1-p3bselected-官方事件總覽接線)。本輪靶向回歸、前端型別／SSR 與記憶體全 App bundle 通過，未跑完整 backend／production Vite build；驗收用 memory catalogue 不代表真行情或 DB 證據。測試命令、版本、exit、結果與限制留本輪 task，不另存產物或解除已有清理拒絕。

### M2-P1 官方事件關注清單的驗收入口

本批新增 `GET /api/focus/official-events?as_of=YYYY-MM-DD` 與首次明示 `POST /api/focus/official-events/capture?as_of=YYYY-MM-DD`，共用 P3b 的固定來源／啟用值／cache／鎖，程式與具名操作已有限 review。額外落盤配額仍為 0，不能直接載入會建立目錄的 conftest 或把隔離 memory catalogue 當真行情／正式 DB；純記憶體 consumer／API 邊界與一次真原件 58 列／API／桌面／窄版操作已分開接受。操作、未支援範圍及清理結果見[個股頁 §12](../STOCK_RESEARCH_PAGE.md#12-m2-p1官方事件關注清單接個股總覽)；後端必要記憶體回歸、前端型別／SSR／記憶體 bundle 通過，完整 backend／production Vite build 未跑，不因記憶體 bundle 成功稱通過。原件未保存、不能離線重播；命令／版本／exit／hash 與失敗／退修及最終收據只留本輪 task，無新增附件／暫存。

### M2-P2 搜尋與研究往返的驗收入口

沿用 M2-P1 明示取得與零額外落盤入口，GET／POST 可帶 optional `q`；原始最多 100 個 Unicode 字元、全 feed 驗證後搜尋再套上限，純記憶體測試須另驗匹配外壞列、101 股以上與同股名稱／完整事件，不能只對前 100 股或 live 58 股聲稱完整邊界驗收。統籌已有限接受實際原件／API 與搜尋／M1 往返、截止切換及窄版操作，以及 78 個記憶體測試、前端型別／最終 16 組 SSR／全 App 記憶體 bundle 的 exit 0，該輪已 freeze／索引／本地 commit。精確支持範圍及未跑項見[個股頁 §13](../STOCK_RESEARCH_PAGE.md#13-m2-p2官方事件清單搜尋與研究往返)；完整 backend／production Vite build 未跑，不以 fixture、memory catalogue 或記憶體 bundle 代替來源／DB／production 驗收。首輪測試／SSR helper 失敗與修正後成功分留 task；命令、版本、exit、原件 hash 與 QA 清理收據留本輪 task，不另建附件，既有殘留及零落盤限制保留。

## 歷史驗證

歷史測試不代表目前來源已驗收；原始數據依[文件索引](../README.md#歷史查閱)取閱，已刪除的 Temp 附件不作接手依賴。
