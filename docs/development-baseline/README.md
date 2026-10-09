# 開發與驗證入口

協作、資料選擇、產物配額、保留例外與清理失敗依 [AGENTS](../../AGENTS.md#驗證資料與暫存)；現行接手與未清資源記在原 GitHub Issue；[遷移入口](../TASK_COORDINATION.md)只保留設定缺口及歷史。本文負責可重建入口、副作用與驗收方式。新任務的命令、版本、exit、計數、hash、退修及提交收據留原 Issue／Git；下列既有 task／ROOT／freeze 收據是歷史證據，不能當現行派工或授權，歷史 pass 不代表目前來源已驗收。

## 版本與資料

先以 `git status --short`、`git diff`、`git log -1` 核對來源。`.gitattributes` 固定 LF，replay 綁定的 source bytes 不可因換行改變。Git 保存測試與 fixture 建構方式，不保存本機 DB、raw、依賴或生成產物。磁碟驗收用專案外最小隔離檔案，仍須滿足各入口的 snapshot 契約。

使用已啟動 API／preview 時，另依[執行資源與服務版本](../GITHUB_WORKFLOW.md#執行資源與服務版本)核 PID、載入來源／bundle、埠及 proxy upstream；commit 不會更新舊程序。並行任務先分配資源，無法隔離就順序驗證。原件生命週期、quota 與 NO-RETRY 維持，不能為補版本證據擅自重啟或重取來源。

## 後端驗證

從專案根目錄依變更選必要範圍；文件只查差異、連結與一致性。

```powershell
# 預設：啟動與 migration 邊界
& ./tools/Invoke-Validation.ps1

# 需要完整回歸時
& ./tools/Invoke-Validation.ps1 -TestPaths @('backend/tests')
```

入口優先使用目前使用者的 bundled Python，否則使用 PATH，也可傳 `-PythonPath`。Replay 必須維持 CPython 3.12.14 與 source／config pins。依賴可來自既有 `backend/.deps`、`backend/.validation-deps` 或已選環境；重建依 `backend/requirements.txt`，[驗證版本清單](validation-requirements.lock.txt)只作 constraints，不是附 wheel hash 的跨平台 lockfile。

### 現行入口的落盤行為

`Invoke-Validation.ps1` 每次建立專案外唯一目錄，將三個 `STOCK_*`、`TEMP`／`TMP` 和 pytest basetemp 指向該處；`finally` 還原環境並嘗試清理。入口尚無自動數量／大小上限；`-KeepArtifacts` 會跳過清理，依 AGENTS 預設禁用。未先核定產物／殘留配額時，不執行此入口。

下列零落盤入口另有 standalone hook，不能將其保證套到一般 pytest、conftest 或 production lifespan。共同方式為：

- Python 以 `-B -X utf8`、AST config 常數 stub、既有唯讀依賴及 guarded `:memory:` SQLite／actual router 執行，排除真 config 的 mkdir；audit 拒絕磁碟變更、外網與未授權 subprocess。
- Node 使用既有 `--deps`，`write:false` 的記憶體 bundle；preview 只在記憶體 CSS 排除外部字型並以 CSP 阻外網，因此字型驗收限 fallback font。
- 測試、HTTP、SSR 與真正 browser 操作分別驗收；記憶體 bundle 不代替 production Vite build，記憶體保存不代替磁碟關閉／重開。
- Serve／compiler 順序啟動，核對 owned command、PID／parent、port 後才停止；readback 前後核同一 fixture 的全欄與 SQLite `typeof`，不能跨 instance 比 hash。
- 產物／附件／暫存／殘留預設為 0；每次實跑仍由原 task 核定範圍與上限。一般測試 import 不安裝 standalone hook。測試和清理分報，不以工具 ack、wrapper exit 或程序消失推定成功。

### R1-A2 legacy 成交額 migration 的磁碟驗證入口

`tools/Invoke-TurnoverMigrationValidation.ps1` 直接用 unittest 執行 Alembic／fallback 兩路徑各四個案例，共八個子程序，不載入一般 pytest conftest。一般 pytest 缺專用環境時的八個 skip 不算磁碟驗收。Fixture 與 NULL 限度見[資料來源](../DATA_SOURCES.md#r1-a2-legacy-成交額-migration-磁碟驗收有限接受)。

```powershell
$migrationDependencyRoots = 'C:/path/to/shared/backend/.deps;C:/path/to/shared/backend/.validation-deps'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./tools/Invoke-TurnoverMigrationValidation.ps1 -RunOwner '<8 ASCII alphanumeric>' -DependencyRoots $migrationDependencyRoots
```

`-RunOwner` 必填八個 ASCII 英數字元，須使用該 task 核定的 owner；依賴範例改成已核實目錄。`-PythonPath` 可明示既有 Python，預設 bundled。`ExecutionPolicy Bypass` 只作用於子程序，不改全域 policy；無 `KeepArtifacts`。

入口建立 `LocalAppData/Temp/taiwan-stock-r1a2-<RunOwner>-<UUID>`，將三個 `STOCK_*`、`TEMP`／`TMP` 指向根內，禁 bytecode。每案例只准 `data/legacy.db` 與 journal；含 root／data／raw 的上限為 **3 directories／2 files／2 MiB**，單 DB **1 MiB**。每例清理 DB／journal；reparse 或額外內容拒絕清理並分報，清理失敗停止新增案例。

stdout／stderr 在記憶體捕獲。以子程序 exit、八份無 skip 的 metrics 與 `validation_complete` 核對完整執行；`R1A2_RESULT` 分列 `test_exit`、`cleanup_exit`、確切殘留／大小／原因。八個 file-backed 案例已有限接受，不外推正式 DB、API startup、backup restore、UI 或完整 backend；Alembic `path_separator` warning 仍在。

### R1-A2 selected invalid／拒收的磁碟驗證入口

`tools/Invoke-StockDaySelectedInvalidValidation.ps1` 直接跑 `backend/tests/test_stock_day_selected_invalid_file_integration.py` 的一個 compound unittest；缺專用環境的 `SkipTest` 不算通過。指定三種 invalid／四類拒收見[資料來源](../DATA_SOURCES.md#r1-a2-selected-invalid拒收磁碟整合有限接受)。

```powershell
$selectedInvalidDependencyRoots = 'C:/Users/YiCheng/Desktop/taiwan-stock-research/backend/.deps;C:/Users/YiCheng/Desktop/taiwan-stock-research/backend/.validation-deps'
$selectedInvalidRoot = 'C:/Users/YiCheng/AppData/Local/Temp/taiwan-stock-r1a2-si-<owner>-<32-hex>'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./tools/Invoke-StockDaySelectedInvalidValidation.ps1 -RunOwner '<owner>' -ValidationRoot $selectedInvalidRoot -DependencyRoots $selectedInvalidDependencyRoots
```

owner 為核定八個 ASCII 英數字元，32-hex 為核定小寫 hex；根須是 `LocalAppData/Temp` 直屬、專案外且不存在，不能沿用已用根。`-PythonPath` 可指定既有 Python，預設 bundled 3.12.14。只對子程序 Bypass；無 `KeepArtifacts`。

內容只准 DB／journal、`capture/capture.zip`／必要 staging／lock、`raw/body.bin`／`receipt.json`／lock。三個 `STOCK_*`、runner 環境、`TEMP`／`TMP` 綁定核定根，禁 bytecode。含暫態檔上限 **4 directories／5 files／2 MiB**；DB **1 MiB**、ZIP／staging **64 KiB**、body／receipt 各 **32 KiB**；DB page 4096 bytes、最多 256 pages。檢查點與退出時核配額。

路徑為 production capture／load／select→adapters 正常去重→`collect(force)`→dispose／new engine→API；其他端點用記憶體 fixture，TPEx 為明示空 batch。程序上限 **60 秒**；只停止自有程序。需一份 `R1A2_SELECTED_INVALID_METRICS`、`tests_run=1`、`skipped=0` 及 `validation_complete`。`R1A2_SELECTED_INVALID_RESULT` 分報 test／cleanup exit 與殘留；`finally` 還原環境，只清核對過的自有路徑，reparse／額外內容拒絕清理。

指定 subset 已於第三次實測有限接受；早期失敗與最終成功保留原 task，不稱首跑通過。TestClient deprecation warning 仍在；未驗完整 backend、production startup、UI、live、TPEx、正式 DB 或 migration 八案例。

### R1-A2 legacy 成交量的零落盤驗證入口

從根目錄直接執行 [test_legacy_daily_volume.py](../../backend/tests/test_legacy_daily_volume.py)，不使用一般 pytest 或通用落盤 runner。格式／別名／fixture 範圍見[資料來源](../DATA_SOURCES.md#r1-a2-legacy-日行情成交量精確整數-gate有限接受)。

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

Standalone stub 提供 93 日常數與未使用的 `memory-unused/raw`，來源 import 前啟用 audit；adapter `_fetch` 使用記憶體 payload／metadata，不讀寫 raw body。新增產物／殘留上限 **0**。核程序 exit、`subcases`、`blocked_io`；blocked I/O 使程序失敗，不能只看方法數。

Parser／adapter fixture 已有限接受；不包括 capture、collect、SQLite、API、live、UI 或 production startup，也不替代下節磁碟驗收。

### R1-A2 legacy 成交量的磁碟整合驗證入口

`tools/Invoke-LegacyDailyVolumeValidation.ps1` 直接跑 `backend/tests/test_legacy_daily_volume_file_integration.py` 的一個 compound unittest，不載一般 conftest。合法／拒收、兩次 force collect、重開與 API 範圍見[資料來源](../DATA_SOURCES.md#r1-a2-legacy-成交量磁碟整合)。

```powershell
$legacyVolumeDependencyRoots = 'C:/Users/YiCheng/Desktop/taiwan-stock-research/backend/.deps;C:/Users/YiCheng/Desktop/taiwan-stock-research/backend/.validation-deps'
$legacyVolumeRoot = 'C:/Users/YiCheng/AppData/Local/Temp/taiwan-stock-r1a2-lv-<owner>-<32-hex>'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./tools/Invoke-LegacyDailyVolumeValidation.ps1 -RunOwner '<owner>' -ValidationRoot $legacyVolumeRoot -DependencyRoots $legacyVolumeDependencyRoots
```

owner／root 規則與上述 selected runner 相同；可指定 `-PythonPath`，使用既有共用依賴，不另建環境。內容只准 DB／journal，以及 `raw/twse/2026/09/05`、`raw/tpex/2026/09/05` 的六份 target body／六份 metadata；檔名為 64 位小寫 SHA 的 `.json`／`.meta.json`，ancillary 資料留記憶體。三個 `STOCK_*`、驗證環境及 `TEMP`／`TMP` 收斂核定根，禁 bytecode／ZIP／附件。

含暫態檔上限 **14 files／11 directories／3 MiB**；DB／journal 各 **1 MiB**、raw JSON **32 KiB**、metadata **8 KiB**。程序上限 **60 秒**；需一份 `R1A2_LEGACY_VOLUME_METRICS`、`tests_run=1`、`skipped=0`、`validation_complete=true`。`R1A2_LEGACY_VOLUME_RESULT` 分列 test／cleanup exit 和殘留；只清自有 exact 根，reparse／額外內容拒絕清理。無 `KeepArtifacts`。

首次實際磁碟測試已有限接受；載入前 execution-policy 拒絕未執行 runner，不算通過。TestClient deprecation 仍在；預期 audit-denial probes 沒有實際 I/O，TestClient／asyncio 的本地 socketpair 不算外網。其他未驗範圍由資料来源契約負責。

### M1-P3b 記憶體事件接線的驗收入口

此路徑零額外落盤，不套通用 runner。server exact `STOCK_TWSE_EVENTS_MEMORY_CAPTURE=1` 啟用明示 POST；普通 GET／import 不抓外網，成功原件只留 process cache。契約與真原件／API／具名桌面及窄版範圍見[個股頁 §11](../STOCK_RESEARCH_PAGE.md#11-m1-p3bselected-官方事件總覽接線)。必要記憶體回歸、型別／SSR／bundle 已有限接受；完整 backend／production Vite build 未跑，memory catalogue 不作真行情／DB 證據。

### M2-P1 官方事件關注清單的驗收入口

GET／首次明示 POST 共用 P3b 的來源、啟用值、cache 與鎖。Consumer／API 記憶體邊界和單次真原件／API／具名操作分開接受；精確範圍見[個股頁 §12](../STOCK_RESEARCH_PAGE.md#12-m2-p1官方事件關注清單接個股總覽)。零額外落盤；原件未保存，不能離線重播。完整 backend／production Vite build 未跑。

### M2-P2 搜尋與研究往返的驗收入口

沿 M2-P1 零額外落盤入口；GET／POST 可帶 `q`。全原件驗證、搜尋後截斷、matching 外壞列、同股多事件、query 邊界與 M1 返回依[個股頁 §13](../STOCK_RESEARCH_PAGE.md#13-m2-p2官方事件清單搜尋與研究往返)。記憶體回歸及真原件／API／具名往返已有限接受；完整 backend／production Vite build 未跑。最小 fixture 不代替來源或持久化驗收。

### UNIT-LOTS-1 台股張數前置的記憶體驗證入口

[`tools/unit-lots-preview.cjs`](../../tools/unit-lots-preview.cjs) 預設 `--check --deps <既有 frontend/node_modules>`；借用共用依賴唯讀，不另建環境。Node20.19.4／TypeScript5.9.3／esbuild0.25.12的本輪check exit0，核current24個src的 `noEmit:true`、`incremental:false`、`composite:false` 並拒絕writeFile；App與preview bundle採 `write:false`。已核canonical48／overview43／現行W8 SSR104／App與chart18個斷言，涵蓋精確張／原股、單位／日期窗口、預設lot輸入、零股相容與unsafe拒用；不外推W1–W7舊suite或完整backend。

最小fixture只存memory，本輪14,771B，受8MiB上限；Git測試工具22,074B≤32KiB是可重建來源，不是附件。Filesystem／network／未授權subprocess guard均0，額外DB／raw／bundle／buildinfo／HAR／截圖／cache／log／disk artifact=0。`--serve` 只供root另核具名Full App預覽／loopback fixture API，重啟即消失，非正式庫存或本次新來源；保存API／payload未改，不重跑舊storage回歸，memory不能替代未來必要磁碟重開。

具名桌面／390px顯示與可信輸入／提交只按[UI §10.3](../UI_COPY_SPEC.md#103-張零股)及[個股頁 §7.1](../STOCK_RESEARCH_PAGE.md#71-unit-lots-1-日常張數與原股稽核有限接受)範圍接受。初始stock chip的date-only fixture被既有validator拒用，改為ISO instant並補2個projection checks，沒有產品source退修。Orca owner短暫unavailable／runtime connectionclosed的原exit保留；tab show／後snapshot正面恢復，未重啟Orca或root，不把初始fill/select event=false或Chip DOM選擇稱native通過。

清理另報：兩組owned preview server／compiler有SIGINT shutdown receipt，兩PTY rawexit1不改；exact CIM與8794 listener後驗均absent，三個exact owned pages已關閉且tab list=[]。完整PID／handle／命令／原exit留root原task，不保存整套成功資料。沒有新行情原件、來源驗收、backend／正式DB、磁碟保存、Vite production build或完整M1／M3證據；本前置不解除研究條件／價格gate。

M1-PRICE-1接線後的必要UNIT回歸另已exit0：沿同Node20.19.4／TS5.9.3／esbuild0.25.12，current26個src noEmit、canonical48／Overview43／W8 SSR104／App-chart18、fixture14,771B，guards／source_requests／artifacts皆0；19 source前後SHA相同、owned shell／Node／esbuild後驗absent。這是同core batch兼容回歸，原24src前置收據保留，不新增native／DB保存宣稱。

### M1-PRICE-1 單日價量的記憶體驗證入口

後端入口[tools/tpex-price-api.py](../../tools/tpex-price-api.py)為 `python -B -X utf8 ... --check --deps <既有 backend/.deps>`，前端[tools/tpex-price-preview.cjs](../../tools/tpex-price-preview.cjs)為 `node ... --check --deps <既有 frontend/node_modules>`，共用依賴唯讀。Python在import前隔離memory config／SQLite `:memory:` 並拒絕disk寫入；Node核現行26src `noEmit:true`、`incremental:false`、`composite:false`，writeFile拒用、bundle `write:false`，不落buildinfo／bundle。

必要後端18項exit0（[parser10](../../backend/tests/test_tpex_price_capture.py)／[store6](../../backend/tests/test_tpex_price_store.py)／[router2](../../backend/tests/test_tpex_price_api.py)）；前端validator52／SSR26／App-chart18及noEmit exit0。check fixture為重建selected值與synthetic邊界，非official capture。CJS default interop初exit1已修，reverse-cutoff兩方向本批修＋驗；必要checks與具名actual源／API／native分報，版本／命令／原exit留root原task，不泛跑backend full。

`--serve` 與API `--live-source-opt-in` 只供root核定的loopback／actual router驗收；API需 `--policy-version`／`--policy-digest` 沿[來源 §20](../SOURCE_REGISTRY.md#20-m1-price-1tpex-兩股單日價格來源與准入)的外部pins。程式明示啟用須 `STOCK_TPEX_PRICE_MEMORY_CAPTURE=1`、`STOCK_TPEX_PRICE_POLICY_VERSION` 與 `STOCK_TPEX_PRICE_POLICY_DIGEST` 均符合固定pins；check不抓live source，import／ordinary GET零外網。首次合法POST最多1 bounded GET，同程序重複／切股與失敗cache不重取；原件／receipt只process memory，重啟釋放，不能離線重播或作磁碟保存證據。

Root唯一production capture、兩股12金融值／API／chart／audit及真正native桌面／390px操作已有限接受，精確界線見[個股頁 §25](../STOCK_RESEARCH_PAGE.md#25-m1-price-1上櫃兩股單日價量閉環有限接受)。catalogue與10/02是synthetic，只有official10/05價格actual；source／filesystem／未授權subprocess guards0、額外DB／raw file／bundle／HAR／截圖／cache／log／artifact0，DB tables preserved=true不外推正式資料目錄。

清理另已核：core唯一owned page關閉、tab list=[]；owned API與兩組UI／compiler及PS parent exact CIM後均absent，8795／8796無listener。SIGINT shutdown=true、guards0／artifacts0；PTY rawexit1保留，不改為check exit0。UNIT先前三pages／server也已核清0；完整PID／handle／原exit留原task，舊資源拒絕／NO-RETRY維持。本入口不證正式DB、跨程序、MA20、完整M1／PIT或全市場，未新增成功產物附件。

### M2-FOCUS-LOTS-1 精確張數關注的記憶體驗證入口

後端既有[tools/tpex-price-api.py](../../tools/tpex-price-api.py)增加 `python -B -X utf8 ... --focus-check --deps <既有 backend/.deps>`，只跑[test_price_focus.py](../../backend/tests/test_price_focus.py)必要7項；前端既有[tools/tpex-price-preview.cjs](../../tools/tpex-price-preview.cjs)增加 `node ... --focus-check --deps <既有 frontend/node_modules>`，只跑[priceFocus.test.ts](../../frontend/src/priceFocus.test.ts)55 helper與18 full-App SSR，現行28src noEmit。沿memory config／SQLite `:memory:`、唯讀共用依賴、Python不寫disk／pycache、Node writeFile拒用／bundle write:false／無buildinfo，不另建環境。首次checks與wrap退修後必要Node重驗均exit0，屬同一核心批次。

驗證版本Python3.12.14／FastAPI0.141.1／SQLAlchemy2.0.52／httpx0.28.1，Node20.19.4／TS5.9.3／esbuild0.25.12；synthetic fixture17,546B、核定memory≤8MiB。Checks驗精確門檻、非法字串／日期、來源拒用、真零與unavailable、固定返回、回應篡改及既有事件返回相容；check不取actual來源，重建selected樣本不代真來源或磁碟保存。Guards與額外disk artifacts皆0；歷史M1／UNIT通過證據保留，不泛跑backend full或舊suite。

Root本輪actual另作唯一bounded fresh GET，沿[來源 §20.4](../SOURCE_REGISTRY.md#204-m2-focus-lots-1-同來源的本輪觀測與採用)同policy／digest／body pins；取得後在**同一Python程序**以 `serve(preloaded_store=已驗Store)`啟loopback真router。入口須先核Store已attempted、request_count=1、無error、raw完整且validated；只patch同程序STORE，不從舊memory、disk、base64 replay或check fixture冒稱actual。Receipt明示 `preloaded_source=true`、來源count1與runner新增0；catalogue／10/02仍synthetic。普通GET／import、兩個stock POST與兩個focus POST均不增外網；首次live-source模式仍受既有external pins、明示opt-in及每程序1GET／redirect0／retry0／3MiB／30秒約束。

Root獨立原件／actual API與桌面、390寬具名操作已有限接受，數值、原生事件與未驗邊界見[個股頁 §26](../STOCK_RESEARCH_PAGE.md#26-m2-focus-lots-1精確成交張數關注與同截止往返有限接受)。Orca fill只設draft，isTrusted=false；真正click／submit／Enter事件另核。長SHA初溢出與wrap補驗、原非零工具收據留原task，不把ACK當成功。

Owned清理另已核：兩個pages各close exit0／tabs=[]；兩組UI／compiler與root同程序API各有shutdown，final source1／runner0、DB preserved=true、guards四項0／artifacts0，raw／receipt已隨程序結束釋放。Exact五PID與8797／8798 listener後驗count0、結構化查核exit0；Ctrl+C外層PTY rawexit1及初始空listener查詢exit1原樣保留，不改成tests exit0。無raw／DB／Temp／HAR／screenshot／build產物；其他歷史資源及NO-RETRY不動。完整命令、PID／handle、原exit與Git收據留原task，不新增附件。本入口不證正式DB、跨程序、PIT、全市場、MA／trend、研究／Signal／Plan、下一日內方向條件或production build。

### M2-FOCUS-DAY-MOVE-1 單日方向與完整返回的記憶體驗證入口

沿既有[tools/tpex-price-api.py](../../tools/tpex-price-api.py)的 `python -B -X utf8 ... --focus-check --deps <既有 backend/.deps>` 與[tools/tpex-price-preview.cjs](../../tools/tpex-price-preview.cjs)的 `node ... --focus-check --deps <既有 frontend/node_modules>`，只跑本輪必要[test_price_focus.py](../../backend/tests/test_price_focus.py)10項、[priceFocus.test.ts](../../frontend/src/priceFocus.test.ts)110helper／44 full-App SSR與現行28src noEmit，均exit0。仍採memory config／SQLite `:memory:`、既有依賴唯讀、noEmit／write:false／incremental:false／composite:false與guard拒寫，不另建環境；M1／UNIT／m2-v1仍適用證據沿用，不泛跑full suite或production build。

Checks涵蓋all／up／down／flat、Decimal／前端原字串O/C比較、缺失／invalid方向拒用、精確股門檻、兩股讀值／理由重算、三條件重複與safe返回、legacy omitted direction=all。Fixture只synthetic，不代actual來源：Python serialized22,587B、object graph＋snapshot＋CSV合計69,487B，Node27,690B，均最小可重建memory、在核定8MiB內；這些不是RSS或程序峰值。執行版本、命令、原warning／錯誤及exit留原task，不建附件／manifest。

Actual另由root唯一fresh GET後以**同一程序held Store**供真router／UI，沿[來源 §20.5](../SOURCE_REGISTRY.md#205-m2-focus-day-move-1-同來源的新觀測與方向-consumer)；全結構／兩股金融與用途gate先核，不用check fixture、base64或disk replay。根獨立HTTP核12次invalid422、合法方向／精確邊界、focus POST2／stock POST2同cache及default隔離；native／窄版範圍見[個股頁 §27](../STOCK_RESEARCH_PAGE.md#27-m2-focus-day-move-1單日方向關注與完整條件往返有限接受)。Source累計1／runner新增0、ordinaryGET外網0，Python四項／root四項／UI三項guard均0、DB preserved=true；額外DB／raw／Temp／HAR／screenshot／bundle／buildinfo／log／artifact0。

清理另已核：唯一owned browser page close exit0，exact五個API／UI／compiler／parent PID後驗absent、8799／8800 listeners0、worktree新增untracked／ignored0。UI／Python PTY Ctrl+C rawexit1保留，結構化後驗exit0；root附加診斷／stdout解碼原錯及後UTF-8正面結果留原task，不把原工具exit改0。Raw／receipt／memory已隨owned程序結束釋放，沒有磁碟保存／跨程序驗收。舊資源清理與NO-RETRY另由協作紀錄管理；本入口不證全市場、PIT、歷史close／日曆、MA／trend、研究／Signal／Plan或下一成交額條件。

### M2-FOCUS-TURNOVER-1 精確成交金額與四條件返回的記憶體驗證入口

沿[tools/tpex-price-api.py](../../tools/tpex-price-api.py)的 `python -B -X utf8 ... --focus-check --deps <既有 backend/.deps>` 與[tools/tpex-price-preview.cjs](../../tools/tpex-price-preview.cjs)的 `node ... --focus-check --deps <既有 frontend/node_modules>`，必要Python14、Node28src noEmit／177helper／77 full-App SSR均exit0。Node前兩exit1與同批測試修正保留原task，契約未降低；舊M1／UNIT／m2-v1／v2有效證據沿用，不泛跑full old suite／production build。Memory config／SQLite `:memory:`、既有依賴唯讀、noEmit／write:false／incremental:false／composite:false及guard拒寫不變，不另建環境。

Checks驗canonical int64元／省略0／explicit invalid／duplicates、兩股amount/status/reason/raw完整gate、來源明確0與missing分清、等額／加1元、三理由重算、全部四條件samecutoff safe返回，以及legacy omitted amount／shared q／事件返回相容。Fixture僅synthetic：Python serialized22,826B、object graph69,828B；Node combined27,917B、conservative object estimate128,464B，非RSS／程序峰值，均在memory≤8MiB、serialized≤256KiB範圍。真來源兩股amount均positive，來源零案例不當actual；完整命令、版本、warning／原exit留原task。

Root沿[來源 §20.6](../SOURCE_REGISTRY.md#206-m2-focus-turnover-1-同來源的新觀測與成交額-consumer)唯一fresh GET後，在同一程序held Store供真router／UI，source1／runner0、DB preserved=true、API四guard／UI三guard皆0。Actual原件先核metadata／用途／instrument／execution、固定pins及12金融值，不用fixture／base64／disk replay。HTTP 16 invalid422／合法門檻與兩股等額＋1元／POST cache／default隔離，以及具名desktop／390px、四條件返回與拒外域見[個股頁 §28](../STOCK_RESEARCH_PAGE.md#28-m2-focus-turnover-1精確成交金額與四條件往返有限接受)；UI proxy GET26／POST0／rejected0只屬本次擷取範圍。

Owned清理另已核：唯一browser page exact close accepted、tabs0；owned API／Node／esbuild皆停止、8799／8800 listeners0，raw／receipt／memory已釋放，額外DB／raw／Temp／HAR／screenshot／bundle／buildinfo／log／artifact0。SIGINT兩PTY rawexit1保留，shutdown receipt與獨立PID／listener後驗0另報。前輪outside-owner及歷史NO-RETRY由協作紀錄管理；本輪worktree不自刪。未跑磁碟保存／跨程序、full suite／production build；不證全市場、PIT、歷史close／日曆、MA／trend／研究／Signal／Plan或下一振幅條件。

### M2-FOCUS-DAY-RANGE-1 新日期與五條件返回的記憶體驗證入口

沿既有[tools/tpex-price-api.py](../../tools/tpex-price-api.py)的 `python -B -X utf8 ... --check/--focus-check --deps <既有backend/.deps>`、[tools/tpex-price-preview.cjs](../../tools/tpex-price-preview.cjs)的 `node ... --check/--focus-check --deps <既有frontend/node_modules>`。必要backend --check22／focus18、Node M1 validator66／Overview26／App chart28及focus272 helper／121 full-App SSR、現行28src noEmit已exit0；舊適用驗證沿用，不重跑全套或production build。前兩Node失敗TS2345與誤期望19731.700（正確精確張呈現19731.7）及後修正pass分報，不降低契約。

最小synthetic只memory config／SQLite `:memory:`，既有依賴唯讀、noEmit／write:false／incremental:false／composite:false與guard拒寫，不另建環境。Checks涵蓋百分比原字串／千分scaled int64、精確OHL交叉比較、H=L合法0與missing、四理由／完整reads、safe五條件／尾零／legacy省略，以及兩明確immutable source tuples／store與前端日期隔離、錯pins／body／receipt拒收。10/05的4／4.5／5%屬歷史fixture，不當本輪10/06 actual。

Fixture尺寸：Python focus serialized23,096B／object70,355B；Node M1四fixtures合計39,743B／object estimate180,176B，focus combined28,171B／estimate130,736B，均在memory≤8MiB／serialized≤256KiB內；object估計非RSS或程序峰值。各入口guards0／artifact0，命令、版本、原exit與精確PID收據留task，不建附件／manifest／來源副本。

Actual另由root先取得並held10/06新body，程式更新後**同一程序**pure builder准入新tuple，再供preloaded真API／UI；來源、four observations及receipt由[來源 §20.7](../SOURCE_REGISTRY.md#207-m2-focus-day-range-1新日期來源准入與本日振幅-consumer)負責。Actual source Store count1／runner新GET0、DB preserved=true／API與client guards0；不使用fixture／base64／disk replay，不將cached UI首次click說成真fresh GET，也不稱m1-v2較早發出該GET。Root router讀入前importlib.util／runner NameError更正後無重取，原失敗保留。Actual數值／422／日期隔離及有限UI驗收見[個股頁 §29](../STOCK_RESEARCH_PAGE.md#29-m2-focus-day-range-1本日振幅與五條件往返)。

Owned清理分報：第一preview因footer10/05退修停止，Ctrl+C rawexit1／guard0 shutdown、最初absence命令rawexit1、後CIM own PID43224／33028 absent0分報；修正後focus272／121／noEmit28通過。先前三個owned Orca pages的click／keypress／inserttext只有ACK，events空、value／React／URL未改；第三頁fresh-ref聚焦後inserttext6.000仍value0／URL min0，未接受native操作。三頁exact close全部accepted、tabs[]後驗0。當時最後readonly確認走ChromiumInput.insertText，但未證實可用且符合不改runtime／不落盤的不同native路徑；Orca visible／nonminimized而非foreground、guestfocus=false只是觀測，未斷言唯一原因。

獨立Edge154.0.4258.53 headless/CDP驗證先核一個`.range-ui-01a1106d`隔離profile，budget≤32MiB／128files／64dirs；建立後1,911,561B／167files／68dirs超出count上限，因此在產品UI測試前停止，不把profile準備當UI通過。Edge PID50476由owned CDP Browser.close正常exit0，driver51236 rawexit1為budget失敗；該owned family八PID後驗absent。Flush後殘留2,555,430B／232files／94dirs，Exact path `C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-m2-day-range-20261006/.range-ui-01a1106d`.Computed及exact literal PowerShell Remove-Item均於CreateProcess前被automatic review以blocked by policy拒絕，刪除未執行；此exact scope列NO-RETRY，等外部policy／owner，不改工具／路徑繞過。殘留超cap時不新增落盤UI profiles／tests，其餘memory工作續作；有效來源／API驗證不失效。

Root續驗同held body的可信桌面1277／窄版390座標mouse move／down／up及trusted input，接受6.000／真0／精確邊界／missing、四理由及五原條件samecutoff安全往返；詳見[個股頁 §29](../STOCK_RESEARCH_PAGE.md#29-m2-focus-day-range-1本日振幅與五條件往返)。外部Orca1.4.220→1.4.221更新非root執行、不作因果修復主張。最後額外invalid fallback native click僅ACK、無DOM event，未完成；先前有效往返不需重跑。Root錯stock path的expected wait timeout raw1、scoped unknown assertion及V8 URL用法錯誤已修正，收據保留原task，不列產品失敗。

Root判定B1有限核心驗收已接受：core+1／dep+1／reliability0／stall0。沿原root／三child完成文件review與版本封存；不new round／BOOT或追加quote GET，feature freeze／index／commit／merge／next coordinator均pending。

原task曾核定兩owned RAM服務保留同body續驗：Python PID25192／session42499／127.0.0.1:8799，同已准入raw1,788,599B／receipt1408B及Store；Node PID1412／session84779／127.0.0.1:8800與compiler16392。驗收完成後第四owned page `8a6e95c0-6ebf-4cc5-9597-a2771b732da0` exact close=true，worktree tabs[]後驗0，四lifetime owned pages皆closed；未新profile／screenshot／HAR／附件。Preview Ctrl+C rawexit1、structured shutdown=true／guards0／disk_artifacts0，proxy API GET32／POST0不是32次quote GET，esbuild exit3221225786；API structured stopped=true／entry guards0／DB preserved／sourcecount1／runner0，之後exit() rawexit1。Exact25192／1412／16392 absent及8799／8800 listeners none後驗exit0；Python process absence才釋放held原件memory，未落盤／raw export。有效驗收、interruption rawexit1、清理後驗0分報，非所有歷史資源已清。不得新增落盤profile／tests，profile自動審查拒絕的exact scope仍NO-RETRY，外部policy／owner另處理。

Python／Node入口guards0／artifact0只屬各入口；browser profile metadata是額外artifact，不稱本輪全域artifact0。沒有正式DB、行情raw／fixture／HAR／screenshot複本；未驗磁碟保存／跨程序、full suite／production build、全市場／PIT／歷史close／日曆／MA／trend／研究／Signal／Plan。舊turnover及本輪outside-owner由協作紀錄管理，不自刪cwd。

### M2-FOCUS-STOCK-SCOPE-1 三股範圍的記憶體驗證入口

沿既有tools/tpex-price-api.py、tools/tpex-price-preview.cjs的 --check／--focus-check與唯讀shared deps；Python -B、SQLite :memory:、Node write:false／noEmit／incremental:false／composite:false及guard拒寫。新三股fixture可由Git中的測試建構方式重建，只memory，不建立DB／raw／HAR／screenshot／profile／附件或環境副本。來源與actual金融值由[來源 §21](../SOURCE_REGISTRY.md#21-m2-focus-stock-scope-1三股來源准入)管理，API／可信操作由[個股頁 §30](../STOCK_RESEARCH_PAGE.md#30-m2-focus-stock-scope-1三股關注與同截止往返)管理。

本批必要checks接受：backend worker／store／API25、focus20；TS focus helper297／full-App SSR132、memory reader75／Overview SSR35／App chart30、28個src完整noEmit。Overview的六個malformed／unknown scope SSR屬同批必要退修，不另計核心或可靠性。版本為Python3.12.14／FastAPI0.141.1／SQLAlchemy2.0.52／httpx0.28.1、Node20.19.4／TypeScript5.9.3／esbuild0.25.12；命令、原非零／後pass與逐檔hash留原task。未跑full suite／production build或磁碟保存／跨程序驗收，不將已驗範圍升格。

Ordinary fixture最大serialized49,759B／object estimate221,060B，三個新增CSV rows；virtual oversize3,145,729B只在memory驗3MiB拒收。仍在memory≤8MiB／serialized≤256KiB內，object estimate不是RSS。Program sourceGET0／全部guards0／artifact0；不能因此說root本輪quoteGET0，root有兩次獨立觀測。

Actual由第二root程序held原件，程式更新後同程序pure builder准入，再供preloaded API／UI。首個非TTY觀測在stdin EOF後正常結束，memory釋放，不能聲稱兩觀測共同供一個cached Store；第二Store sourcecount1／runner新增GET0。Root REPL初importlib.util AttributeError發生runner import前，顯式import修正後未新增GET或磁碟；這些原錯留task，不重取或修改原exit。

本輪owned清理完成：唯一Orca page `46b2bf07-29d1-4ae5-bfb8-3259a8e94f1b` exact closed／tabs0；API PID60400、preview30672及compiler8280 absent，8801／8802 listeners none後驗raw0，raw memory釋放。Compiler8280是新的esbuild lifetime，不能與先前已結束的Python同PID混作同程序。Node SIGINT structured shutdown保存proxy API GET15／POST0／rejected0、guards0／disk0，terminal rawexit1；API serve finally stopped／DB preserved／Store1／runner0／guards0返回0，後REPL sys.exit(0)的terminal rawexit1保留，與清理後驗0分報。沒有建立isolated Edge profile或disk fixture。

舊day-range exact四session closure／history archive已另驗，worktree／branch及2,555,430B／232files／94dirs profile NO-RETRY仍保留、不重掃／刪除；舊turnover與其他歷史不納入，責任與接手由[協作紀錄](../TASK_COORDINATION.md)管理。當前功能接受不等於全域artifact0或所有歷史資源已清；仍只跑本變更必要驗證。

### M2-FOCUS-STOCK-SCOPE-2 四股範圍的記憶體驗證入口

沿既有tools/tpex-price-api.py／tools/tpex-price-preview.cjs的 --check／--focus-check及共用唯讀依賴；Python -B／SQLite :memory:、Node write:false／noEmit／incremental:false／composite:false與guards拒寫保持。Fixture建構方式在Git，可重建四股selected與synthetic邊界，只memory；不建DB／raw／HAR／screenshot／Edge profile／附件或新環境。金融／版本由[來源 §23](../SOURCE_REGISTRY.md#23-m2-focus-stock-scope-2四股來源准入)管理，actual API／可信操作由[個股頁 §31](../STOCK_RESEARCH_PAGE.md#31-m2-focus-stock-scope-2四股關注與同截止往返)管理。

本變更必要checks已接受：Python worker／store／API27與focus22；Node focus helper327／full-App SSR150、memory validator94／Overview SSR46／App chart32，兩組28src noEmit；全部final exit0、sourceGET0／guards0／disk0／DB preserved。沿共用既有版本與依賴，沒有env install；命令、原失敗及逐檔hash留原task，不跑full suite／production build或磁碟保存／跨程序。Ordinary fixture最大serialized59815B／object estimate264092B（各低於64KiB／512KiB）、最多四CSV rows；separate virtual oversize仍只在memory驗既有拒收，object estimate不是RSS／程序峰值。

Actual由root同一guarded程序在改程式前唯一new quote GET並held raw，改後pure builder准入四股 `.2`、preloaded Store供真router與UI。Source Store1／runner新增GET0、guard0／DB preserved=true；不是UI首次capture click取得新body，也不用fixture／disk／舊程序memory當actual。原件與receipt只memory，所有held raw現已釋放。

Owned唯一page `5028fdbb-3c34-42dd-a406-537ee5559f2a` exact closed／tabs0；API35548／preview51332／compiler54688後驗absent，8801／8802 listeners none。Structured stopped／guards0／DB preserved已核；preview interrupt與interactive API terminal最後raw exit1保留，獨立清理後驗exit0分報，不改原exit或否定有效產品驗收。未建立Edge profile、screenshots／HAR／artifacts／DB copy／KeepArtifacts產物。前輪STOCK-SCOPE四session已outside關閉封存接受，worktree／branch移除仍待新輪涉及索引；DAY-RANGE full containing worktree／NO-RETRY與TURNOVER／cache／Temp／其他歷史排除，不稱所有歷史資源已清。

該四股版source13＋DOC8 freeze21／qualified索引／exact commit與正常ff-only master merge `899fa62260e495075cc756ff31869a57df6b3895` 已接受；後續五股入口見下節。Coreoperation+1／scope dependency+1／reliability0／stall0。M1 parameterless單日JSON observation沒有解除多日close／calendar／strategy／time／execution，也不計implementation batch；保存／跨程序、PIT／全市場、完整M1／M2／M3仍未驗。

### M2-FOCUS-STOCK-SCOPE-3 五股範圍的記憶體驗證入口

沿既有tools/tpex-price-api.py／tools/tpex-price-preview.cjs的 --check／--focus-check及共用唯讀依賴；Python -B／SQLite :memory:、Node write:false／noEmit／incremental:false／composite:false、guards拒寫保持。沒有新環境、helper或disk fixture；建構方式留Git，來源／版本見[來源 §25](../SOURCE_REGISTRY.md#25-m2-focus-stock-scope-3五股來源准入)，actual API／可信操作見[個股頁 §32](../STOCK_RESEARCH_PAGE.md#32-m2-focus-stock-scope-3五股關注與同截止往返)。

必要checks final exit0：Python worker／store／API29與focus24；Node memory validators111／Overview SSR46／App chart32，focus helpers366／full-App SSR167，兩組28src noEmit。Python3.12.14／FastAPI0.141.1／SQLAlchemy2.0.52／httpx0.28.1、Node20.19.4／TypeScript5.9.3／esbuild0.25.12；依賴與warnings如實保留，child sourceGET0／guards0／artifacts0，未跑full suite／production build或磁碟保存／跨程序。

新增3293鈊象的五股tuple，ordinary fixture最多5 CSV rows、serialized cap80KiB／object cap512KiB；actual Python53717B／graph147897B、Node55693B／estimate243488B低於各cap，estimate不是RSS。Explicit舊tuple64KiB／512KiB斷言保留；separate virtual oversize仍只memory驗拒收，不以新cap放寬舊policy。

本輪CSV GET共3次，不能把final Store1／runner1稱全輪一次。OBS1 root名稱Unicode預期錯而exit1／raw釋放；OBS2金融與pure admitpass，但root custom network audit漏Windows loopback socketpair，startup network_denied1／API無listener。原guard失敗保留；structured helper stopped／DB preserved，root stdlib獨立重現並exact stop30296 exit0／absence後驗0，無raw轉移。OBS3 existing guarded API36908／live-source-opt-in／preloaded=false，native firstload在程式修改後觸發唯一NEW workerGET；final DB preserved／guards0／sourcecount1／runnerGET1，cached再讀不增加GET。Source金融觀測與版本由來源§25.2管理，不拿fixture／body replay／preedit同程序替代final actual。

清理另已root獨立接受：唯一lifetime owned page `ad99ff9a-1f83-4c09-98f6-5d8716ff0804` exact closed／tabs0；API36908／preview55908／compiler34308／old observer30296均absent，8871／8801／8802 listeners none，獨立verify exit0、held raw隨process exit釋放。中斷API／preview terminal rawexit1與清理verify0分報；停止前structured diagnostic guards0／disk0／DB preserved／sourcecount1／runner1／preloadedfalse。不改原exit、不否定有效驗收；未建立screenshot／HAR／Edge profile／DB copy／env install／KeepArtifacts或新artifact。

Coreoperation+1／selected scope dependency+1／reliability0／stall0，BOOT／M1 metadata／DOC／index／Git不算implementation batch。歷史前任session封存與NO-RETRY由[協作紀錄](../TASK_COORDINATION.md)管理；本worktree／branch不自刪，不掃Temp／cache／logs。未驗保存／跨程序、PIT／全市場、20／21歷史close／完整calendar／strategy time execution、MA／trend／ATR／研究／Signal／Plan或完整M1／M2／M3。

### M2-FOCUS-STOCK-SCOPE-4 六股範圍的記憶體驗證入口

沿既有tools/tpex-price-api.py／tools/tpex-price-preview.cjs的 --check／--focus-check與共用唯讀依賴；Python -B／SQLite :memory:、Node write:false／noEmit／incremental:false／composite:false、guards拒寫保持。沒有新環境、helper或disk fixture；建構方式留Git，來源版本見[來源 §27](../SOURCE_REGISTRY.md#27-m2-focus-stock-scope-4六股來源准入)，actual API／可信操作見[個股頁 §33](../STOCK_RESEARCH_PAGE.md#33-m2-focus-stock-scope-4六股關注與同截止往返)。

必要checks final rawexit0：Python worker／store／API32與focus26；Node memory validators129／Overview SSR46／App chart32、focus helpers392／full-App SSR184，兩組28src noEmit。Python3.12.14／FastAPI0.141.1／SQLAlchemy2.0.52／httpx0.28.1、Node20.19.4／TypeScript5.9.3／esbuild0.25.12沿既有版本；child financial GET／POST0、guards0／disk0。未跑full suite／production build、磁碟保存／跨程序。

六股tuple ordinary fixture最多6 CSV rows，serialized cap80KiB／object cap512KiB；Python最大64040B serialized／174694B object graph，Node64943B serialized／282220B estimate，estimate不是RSS。舊64KiB／512KiB cap及原斷言保留；virtual oversize仍只memory，不放寬舊policy。

本輪financial CSV GET總3次，不能把final Store1／runner1稱全輪一次。OBS1 optional Content-Length root diagnostic在GET後失敗，raw釋放／未准入；OBS2 root fresh金融接受後釋放；final OBS3 PID38684於source修改後native首次load觸發NEW workerGET1／preloaded=false，沒有OBS2 preload、raw transfer／export或replay。Final sourcecount1／runner1／guards0／disk0／DB preserved；金融值與原件receipt只由來源§27.2管理。

清理另經root獨立接受：唯一lifetime owned page `f4b2101d-4728-447c-8405-ba9d4c431100` exact closed／tabs0；preview15520／compiler26492／API38684 absent，8801／8802／8871 listeners none，held raw全釋放。Normal Ctrl+C API／preview rawexit1與independent cleanup verify exit0分報；stopped receipts guards0／DB preserved，不改原exit或否定有效驗收。無source copies／profiles／screenshots／HAR／env install／KeepArtifacts。

Coreoperation+1／selected ordinary identity-source-date-policy dependency+1／reliability0／stall0，BOOT／M1 metadata／DOC／index／Git非implementation batch。前任exact四session closure／archive與baseline仍需保留的舊worktree見[協作紀錄](../TASK_COORDINATION.md)，不重做歷史清理。未驗保存／跨程序、PIT／全市場、20／21歷史close／complete calendar／strategy time execution、MA／trend／ATR／研究／Signal／Plan或完整M1／M2／M3。

### M2-FOCUS-STOCK-SCOPE-5 七股範圍的記憶體驗證入口

沿既有tools/tpex-price-api.py／tools/tpex-price-preview.cjs --check／--focus-check及唯讀共用依賴，Python -B／SQLite :memory:、Node write:false／noEmit／incremental:false／composite:false、拒寫guards保持；無新環境、helper或disk fixture。來源版本見[§29](../SOURCE_REGISTRY.md#29-m2-focus-stock-scope-5七股來源准入)，actual API／trusted操作見[個股頁 §34](../STOCK_RESEARCH_PAGE.md#34-m2-focus-stock-scope-5七股關注與同截止往返)。

Necessary final rawexit0：Python worker／store／API35與focus28；Node validators147／Overview SSR46／App chart32、focus helpers420／App SSR201，兩組28src noEmit。沿既有Python3.12.14／FastAPI0.141.1／SQLAlchemy2.0.52／httpx0.28.1及Node20.19.4／TypeScript5.9.3／esbuild0.25.12；child financial GET／POST0、guards0／disk0。

Ordinary fixture max7 CSV rows／serialized80KiB／object512KiB：Python74441B／201599B，Node74229B／321312B estimate；不是RSS，舊64KiB及五／六股cap與斷言保持。Original bulk preflight exit1（count3／expected2）在test writes前失敗；首Node focus exit1是SSR3055／3,055預期差異，修正後只重跑受影響focus至exit0，原失敗不抹除。

Root獨立行情OBS1核後釋放；final post-edit OBS2 native firstload NEW worker／Store1／runner1／preloaded=false，本輪financial GET總2，金融body與receipt權威在來源§29.2。Stop前guards0／disk0／DB preserved、preview API GET15／POST1／rejected0；source1／runner1不是全輪只GET1。

Cleanup另經root獨立接受：唯一lifetime page045cdead-1528-460f-adc2-949aa3fc0fa1 closed／tabs0，API8752／preview48316／compiler39468 absent，8801／8802／8871 listeners none；API exit釋放held raw。Normal Ctrl+C API／preview rawexit1與independent cleanup verify exit0分報，無profile／screenshots／HAR／env install／KeepArtifacts／產物。

Coreoperation+1／selected dependency+1／reliability0／stall0；BOOT／M1 metadata／DOC／index／Git非implementation batch。未跑full suite／production build、磁碟保存／跨程序／全市場／PIT／20／21歷史close及完整M1／M2／M3。新保存操作另須source-purpose及actual disk驗收，不以本入口的memory fixture替代。

### M1-PRICE-SAVE-1 私人磁碟保存與新程序驗證入口

沿既有`tools/tpex-price-api.py`及`tools/tpex-price-preview.cjs`／唯讀共用依賴，無新環境或helper。Python `-B -X utf8`、SQLite :memory:及AST config stub保留；只有已核定private scope例外寫檔，DB不變。Source／storage dual pins及三檔schema見[來源 §30](../SOURCE_REGISTRY.md#30-m1-price-save-1私人單日保存與跨程序讀回)，actual操作見[個股頁 §35](../STOCK_RESEARCH_PAGE.md#35-m1-price-save-1私人單日保存與跨程序操作)。Windows path保護目前僅Windows。

Product runner producer用`--serve --cutoff 2026-10-06 --live-source-opt-in`及原`.5` source `--policy-version/--policy-digest`、新`--private-store-root/--private-policy-version/--private-policy-digest`；NEW reader以`--saved-source-only`取代live opt-in，同source/storage pins及root，empty Store／capture禁用。Private設定為`STOCK_TPEX_PRICE_PRIVATE_STORE=1`、`STOCK_TPEX_PRICE_PRIVATE_ROOT`、`STOCK_TPEX_PRICE_PRIVATE_POLICY_VERSION/DIGEST`；import／普通startup不fetch／hydrate。Exact pins見來源§30，product/private entry都需原task核範圍，本文不授權重跑。

Testroot `C:/Users/YiCheng/AppData/Local/taiwan-stock-research/price-save-tests-01a11367`；productroot同parent下`price-save-01a11367`。Parent起初不存在；combined≤9files／7dirs／3432448B（含parent），product≤3files／3dirs／3170304B，synthetic≤6files／256KiB、一case一份最小bundle；ordinary fixture≤7rows／serialized80KiB／object512KiB。只清本次created／owned exact scopes，parent限created且empty；不掃Temp、不留整套successful產物。

Root接受必要rawexit0：backend gate1 compound、bounded disk write/read/faults 10／71／18 checks（獨立PIDs28452／2620／20388）；synthetic CSV821B／7rows，三檔3826B，writes／mutations依phase為6／3、0／0、34／15，unapproved guards0。Synthetic cleanup exit0／testroot absent。初次write fdopen guard integration exit1保留，owned staging清後separate cleanup0，再修Windows fd guard；fixture不代實際金融保存。

Final backend35；frontend30src noEmit、新validator68／saved SSR10、原affected147／46／32均raw0。Node記憶體write:false、noEmit／incremental:false／composite:false；synthetic9834B／object estimate36236B，非RSS；compiler已停。既有Python3.12.14／FastAPI0.141.1／SQLAlchemy2.0.52／httpx0.28.1、Node20.19.4／TypeScript5.9.3／esbuild0.25.12。逐輪exact命令、原exit、版本／hash收據留原task，synthetic命令不在此重複。

Root actual OBS1獨立fresh後memory釋放，OBS2是post-edit producer29780 native NEW worker1／Store1／runner1／preloaded=false；CURRENT financial GET總2，完整body／capture／storage時間及SHA由來源§30.3負責。Producer save／idempotent、停止後NEW reader33208 fullraw＋兩receipt／all126欄42金融、saved API／原生desktop窄版已驗；reader writes0／mutations0／network0／guards0／DB preserved。

**測試／功能通過，產品清理未完成。** EXACT product三檔及empty dirs的native PowerShell刪除被automatic review在CreateProcess前以`blocked by policy`拒絕，刪除未執行。殘留final `C:/Users/YiCheng/AppData/Local/taiwan-stock-research/price-save-01a11367/tpex-11370-2026-10-06-m1-v1/`：`body.csv`1788599B、`capture-receipt.json`1461B、`storage-receipt.json`1584B，共1791644B／3files及common parent／productroot／final 3dirs；root readonly residue hash proof0。Filecount cap3已達，停止新增disk cases；NO-RETRY、不換工具／path／owner／rename／containing tree繞過。Testroot已absent，清理拒絕不否定有效驗收、不要求使用者刪除或重跑。

Actual missing-file native UI未跑；corruption／schema／partial gate是synthetic，actual同token failed reread是在normal停止reader後proxy502→清除舊saved值。Root readonly checker最初zero-based ordinal assertion exit1保留，改ONE-BASED後proof0；6510 ordinal726／header727，沒有新增GET或mutation。

Producer／reader／preview normal Ctrl+C各rawexit1；independent root PID29780／33208／6024／compiler40916 absent及8801／8802無listener proof0分報。唯一lifetime page已closed／tabs0；memory raw隨程序停止釋放，disk raw仍留。無screenshot／HAR／profile／export／env install／KeepArtifacts。未跑full suite／production build／非Windows保護／actual missing-file UI；全市場／PIT／20／21close／完整calendar／strategy time execution仍缺。

### M1／R1-A2 成交量精確呈現的零落盤驗證入口

`backend/tests/test_volume_exact_presentation.py` 直接 standalone 執行；Node `tools/volume-exact-preview.cjs` 分別核 units／chart／overview、product fetch／Response.json 及 UI。Python 沿 AST stub／memory SQLite，不載 conftest 或 lifespan；`_capture_evidence` 的 patch 僅支援 synthetic fixture，不重驗檔案 gate。API／股張／圖形近似與兩市場範圍見[個股頁 §14](../STOCK_RESEARCH_PAGE.md#14-m1r1-a2成交量-httpjavascript個股精確呈現)。

必要記憶體／HTTP／具名操作已有限接受；兩 serve 的原 exit **1** 與 direct test／Node check exit 0 分報，Python serve 沒有最後完整 audit receipt。沒有磁碟重開、真官方／live、production startup／build 或完整 M1／PIT 證據。

### M3-P1 既有庫存股數的零落盤驗證入口

`backend/tests/test_share_quantity_exact_presentation.py` 與 `tools/share-quantity-exact-preview.cjs` 採上述 standalone／memory 方式；原股數／Float safe 範圍及具名操作見[UI 契約](../UI_COPY_SPEC.md#m3-p1-既有庫存股數的有限呈現契約)。當時 router commit／refresh→GET、unsafe 拒收、formatter／SSR／實際操作已有限接受，不能當磁碟 reopen 或大數 Float 保存證據。同名入口的現行 storage 模式見下節。

### M3-P2 可信整數保存與磁碟重開驗證入口

股數與輸入契約見[UI](../UI_COPY_SPEC.md#m3-p2-可信整數保存與磁碟重開契約)，migration／readiness 見[R0 §8.11](../R0_IMPLEMENTATION.md#811-m3-p2持倉精確整數-migrationreadiness有限接受)。

`test_share_quantity_exact_presentation.py` 為記憶體 router／guard；`test_share_quantity_storage.py` 預設不建檔，`--memory-storage` 只跑 storage memory cases。兩者 standalone 使用共用唯讀依賴，不載 conftest。必要記憶體驗證已有限接受；不能將重複 audit probe skip 改報全 pass／0 skip。

Storage runner 的磁碟模式只接受固定根 `C:/Users/YiCheng/AppData/Local/Temp/taiwan-stock-m3-share-storage-01a10250`，須有原 task 授權且 root／ancestors non-reparse；不得換根繞過限制。最多 **2 files**（DB／journal）、**3 directories**（root／data／raw）、總 **2 MiB**、單 DB **1 MiB**；殘留同上限，無 WAL／pycache／附件／KeepArtifacts。

- `--disk`：四個 sequential synthetic normal／fault 案例，驗 migration、關閉／重開、readiness 唯讀 hash 與 API int64 保存；最後嘗試清理，test／cleanup 分列。
- `--prepare`：exclusive 建 owned DB，不覆寫既有檔。
- `--serve`：只用該 DB 在 loopback **8779** 跑 actual `app.main`／readonly readiness，不做 init-db 或 migration。
- `--inspect`：SQLite `mode=ro` 查 storage type、已知列與 closed-file SHA。
- `--cleanup`：清理這次核定的自有根。

Node preview 的 `--check`、`--http-check`、`--serve` 使用共用 `--deps`；自有 **8780** 接 **8779**，bundle `write:false`。Synthetic `2026-10-03` 的兩市場使用者數量不作官方行情／正式持倉證據。四個磁碟案例與具名保存／第二程序重開已有限接受；前兩次 cleanup／marker fixture 失敗留原 task，不稱首跑通過。

**Capture stop 副作用仍未解除：**瀏覽器 capture 停止自動建立 `C:/Users/YiCheng/.agent-browser/tmp/har/har-1791044803009.har`，**1 file／64,885 bytes**，超過當時附件配額 0。exact 單檔刪除在 CreateProcess 前遭 automatic review `blocked by policy`，未執行；不重試或換工具，不掃 shared HAR／parent。隔離 DB 已清，HAR 仍有殘留；待外部變化／使用者處置，見[協作紀錄](../TASK_COORDINATION.md)。未來使用 capture 先核 stop 落盤副作用和配額；記憶體 bundle 不保證瀏覽器工具零落盤。

本節只證 owned fixture 的有限 startup、股數保存／重開，不證正式 migration／restore、production、官方／live、完整 backend／Vite build、大數金融估值、Plan、完整 M3 或 PIT。

### M3-P3 庫存價值輸入的零落盤驗證入口

Python `test_share_quantity_exact_presentation.py --finance-only`；Node preview `--finance-check`、`--finance-http-check`，serve pair **8777／8778**。沿共同 standalone／audit／write:false；只在 memory fixture 保存 synthetic 持倉，不承襲 P2 disk fixture，不使用會落 HAR 的 capture。

UI 原字串、helper 序列化前、raw HTTP 三層各自驗收，見[UI](../UI_COPY_SPEC.md#m3-p3-庫存成本停損風險輸入可信檢核與拒收保留)。必要邊界、actual HTTP／具名保存、拒收與空白清欄已有限接受；兩次刪除沒有 DELETE，該批刪除未驗，NEW rows 只隨 memory shutdown 釋放。不證污染讀回、Decimal exact、磁碟保存、production、完整估值／風險或 Plan。

### M3-P4 庫存價值可信讀回的零落盤驗證入口

Python `--finance-read-only`；Node `--finance-read-check`、`--finance-read-http-check`；serve 兩端皆帶 `--finance-read-fixture`，pair **8777／8778**。固定 synthetic `2026-10-04` 十四持倉與六十個明示 fixture 日期；mutation 封鎖，不作保存／刪除驗收。

三態、missing-only 停損 fallback、metadata 相容與具名範圍見[UI](../UI_COPY_SPEC.md#m3-p4-既有庫存價值可信讀回與非法停損隔離)。必要 direct／HTTP／formatter／SSR／具名操作及同 instance 十四列全欄／typeof／note／updated_at 不變已有限接受。不修污染或 affinity 遺失的意圖，不證磁碟、官方行情、Decimal exact 或完整風險行動。

### M3-P5 可信股數與估值／持倉判定的零落盤驗證入口

Python `--quantity-trust-only`；Node `--quantity-trust-check`、`--quantity-trust-http-check`；serve 皆帶 `--quantity-trust-fixture`，pair **8777／8778**。固定 synthetic `2026-10-04` 十六持倉、兩個 absent metadata，不作官方行情／持倉證據。

股數／held／估值三態、原 gate 優先及 scope 見[UI](../UI_COPY_SPEC.md#m3-p5-可信庫存股數與既有估值持倉判定一致)。必要 direct／HTTP／真正 ActionDetailPanel、Portfolio／首頁與具名操作已有限接受；同 instance 全列／typeof／note／updated_at 不變。第一版 ProductActionCard SSR 不證真正詳情，badge 修正後另驗。SSR warnings 仍有；不證行情信任、金融估值 exact、磁碟重開、所有風險／Plan 或完整 M3。

### M3-P6a 庫存本地行情與試算的零落盤驗證入口

Python `--quote-read-only`；Node `--quote-read-check`、`--quote-read-http-check`；serve 皆帶 `--quote-read-fixture`，pair **8777／8778**。固定 synthetic `2026-10-04` **20 持倉／18 行情**，兩整表全欄／typeof／note／updated_at 在 HTTP／UI 前後同 hash、read mutation 0。

本地數值隔離及試算只由[UI](../UI_COPY_SPEC.md#m3-p6a-庫存收盤數值隔離與本地試算可檢視)負責。修正版 direct／HTTP／Portfolio SSR 和具名兩尺寸展開已有限接受。該批 `/api/actions?limit=20` 因 Date processor 遇 `not-a-date` 有 **2 GET／500**；Portfolio 可用不證完整 ActionsPage。後續 P6b 清單修正不倒改此失敗。記憶體 patch 不證 M1 正向 file gate、磁碟重開、官方／availability／PIT 或完整交易能力。

<a id="m3-p6b-actions-清單行情讀回的零落盤驗證入口"></a>

### M3-P6b Actions 清單行情讀回的零落盤驗證入口

Python `--action-read-only`；Node `--action-read-check`、`--action-read-http-check`；serve 皆帶 `--action-read-fixture`，pair **8777／8778**。固定 synthetic `2026-10-04` **24 持倉／1,382 行情**、每市場十二 symbols／六十個明示 fixture 日期；巨大值補驗的 L-FUTURE cutoff close／adj_close 為 `1e308`，翌日 5000 仍排除。兩 instances 各核自身 before／after／pre-shutdown 全欄／typeof，不能跨 instance 比 hash。

逐列 raw／unlocated／latest／scope 與具名兩尺寸清單、搜尋／state／分頁及正常導航見[UI](../UI_COPY_SPEC.md#m3-p6b-actions-清單逐列行情讀回污染隔離)。必要 direct／actual HTTP／SSR／具名操作已有限接受；污染卡片完整詳情未由 P6b 點驗，detail SSR 不證 StockPage。後續 P6c 有限範圍依其契約，不能倒改 P6b。未驗完整 ActionsPage、來源／日期真實性、PIT、磁碟／production 或新 Plan。

### M3-P6c 個股詳情行情讀回的零落盤驗證入口

Python `--stock-read-only`，必要局部矩陣為 `--stock-read-case router-matrix`；Node `--stock-read-check --deps <既有依賴目錄>`、`--stock-read-http-check`、`--stock-read-followup`；serve 皆帶 `--stock-read-fixture`，pair **8777／8778**。固定 synthetic `2026-10-04` **十二標的／十二持倉／784 行情**，沒有准入 M1 原件。必要 direct／actual getStock／Response.json／完整 App SSR、具名操作與同 instance positions／bars 全欄／typeof 不變已有限接受；不是完整 suite 首跑全通。磁碟 `test_stock_overview.py` 只做 AST／diff 核對，未跑。

Raw 十七欄、nullable／候選窗口／MA／M1 latest 由[個股頁 §15](../STOCK_RESEARCH_PAGE.md#15-m3-p6c個股詳情行情讀回污染隔離)負責。**有效歷史 390px 橫向溢出 assertion exit 1，原因未證；physical canvas 與真正截止表單未驗。**Hidden table `innerText` 空白不證 MA 全空，SSR／工具 ack 不代替操作。

歷史核定上限：direct setup **32**／router GET **96**；單 fixture product GET **96**（Node／統籌各 **48**）、static **32**、review＋shutdown **8**；整輪 product GET **192**、SSR attempts **40**。Bundle 上限 JS **6 MiB**、CSS／HTML 各 **64 KiB**，API response **2 MiB**。這是當批配額，後續由原 task 核定，不能沿用已耗額度或新增 fixture 來重置。新落盤上限 **0**。

短暫 HTTP compiler 未即時觀測 PID／並發，不能宣稱整輪 child cap 已證；後續核舊 preview／child 退出後才續驗。實作未改 `_stable_read`／`_capture_evidence`／shared `bar_dict` 或 source pins；M1 正向 filesystem、磁碟重開、production、官方／availability／PIT 仍待驗。

### M3-P6d 個股研究候選讀回的零落盤驗證入口

Python `--signal-read-only`，局部補驗 `--signal-read-case evidence-shape`；Node `--signal-read-check` 只做 noEmit，`--signal-read-http-check` 核 actual getStock／Response.json／StockPage／Panel，`--signal-read-status-check` 核 actual export guard／Panel 的非字串 status 邊界；serve 皆帶 `--signal-read-fixture`，pair **8777／8778**。

Synthetic `2026-10-04` source 建構十四 instruments（十三研究標的＋一個 TAIEX）；actual 四表 snapshot **780 bars／十三持倉／38 Signals／5 StrategyVersions**，instrument 數只由 source 建構核對。必要 direct／HTTP／App／具名五案、status 單項補驗與同 instance 四表全欄／typeof 不變已有限接受。SQL None 只核 pure projection／RR，不證寫進 NOT NULL evidence 欄。

投影／JSON／窗口／canonical latest／observation 由[個股頁 §16](../STOCK_RESEARCH_PAGE.md#16-m3-p6d個股詳情研究候選讀回污染隔離)負責。十個 HTTP-derived malformed SSR 不替代後來的 status pure case；含 `toString` function／undefined 的 helper 形狀不當 HTTP JSON。B 最終原生 click，其餘四案 DOM.click 後核 actual browser DOM，不稱五案全原生。短暫 helper compiler 未即時觀測，不宣稱 child cap 全程已證。

P6d 指定外部 owned 清理與五 DB 刪前檢查缺口、blocked／NO-RETRY 資源依[協作紀錄](../TASK_COORDINATION.md)，不在此重試。當批 direct／GET／setup／SSR／process 配額與原失敗留 task；新增落盤仍為 0。其他 typed paths、M1 正向 file gate、磁碟／正式 DB／production、官方／PIT，以及 P6c canvas／有效歷史窄版／真正截止表單不因本批通過。

### M3-P6e 個股獨立特徵／籌碼讀回的零落盤驗證入口

Python `--independent-read-only`；Node `--independent-read-check --deps <既有依賴目錄>`、`--independent-read-http-check --api http://127.0.0.1:8777 --deps <既有依賴目錄>`；serve 皆帶 `--independent-read-fixture`，owned pair **8777／8778**。原批次驗收限制為只用單一 fixture，不重啟／reseed／replay B；舊 signal fixture 不作本批已驗證據。Serve／compiler 順序啟動，bundle `write:false`。

版本基準為 **Python 3.12.14／SQLAlchemy 2.0.52／Pydantic 2.13.5／Node 24.19.0／TypeScript 5.9.3**。Synthetic `2026-10-04` fixture 的六表為 **12 features／253 chips／10 Signals／1 version／10 positions／600 bars**，另有十一 instruments。Actual HTTP／App／Panel、六具名操作及同 instance 六表全部欄位／typeof 的 start／before／after／UI 後同 digest、read mutation 0 已有限接受。原首輪一項 held-observation expectation 錯誤只做局部修正／補驗，沒有重跑八個有效 case；pure guard cases 不冒充 actual HTTP。SQL None 只核 pure projection，affinity 數值化的字串／bool 不證恢復原意圖。

資料契約與 native／DOM.click 支持範圍見[個股頁 §17](../STOCK_RESEARCH_PAGE.md#17-m3-p6e個股特徵籌碼獨立區塊讀回隔離)。兩個 QA pages 順序使用、最大同時一個；最後 owned pages／serve／captured children／listeners 已清，新落盤／附件／暫存／殘留 0。Compiler exit code 未觀測，不由 ceased 推 exit 0；console／network 只作具名範圍查閱，不稱全域零 warning。原工具／selector／runtime 失敗留 task。

原件／磁碟重開、正式 DB、source／availability／PIT 等 gate 保留；M1／M3 核心完成條件由 [ROADMAP](../ROADMAP.md) 負責。當批方法／GET／setup／SSR／程序配額留原 task／Git；現有未清資源見協作紀錄，不重置歷史已耗額度，不預設啟動下一個隔離輪。

### M1-W2 法人窗口的零落盤驗證入口

以下保留 W2當時的 case／版本／操作邊界；現行入口與四截止驗收見[W4節](#m1-w4-四截止法人窗口的零落盤驗證入口)。

[`test_institutional_windows.py`](../../backend/tests/test_institutional_windows.py) 預設驗 W1 memory 邊界；`--api-only` 驗5個 W2 case，`--serve` 用 MockTransport。統籌另核 `--serve --live-source-opt-in` 才取真原件，owned API／UI pair **8781／8782**；使用 Python `-B -X utf8`，不載 conftest／正式 app startup、不建 DB 或 fixture 檔。

[`institutional-window-preview.cjs`](../../tools/institutional-window-preview.cjs) 指定共用唯讀 `--deps <既有 frontend/node_modules>`；預設 full-src noEmit／18 SSR／mock product HTTP，`--typecheck-only` 執行 noEmit／SSR、略過 HTTP，`--serve` 用完整 App 記憶體 bundle、`write:false`，字型 fallback。前述驗證及實際兩股／單截止操作已有限接受，契約與未驗項見[個股頁 §18](../STOCK_RESEARCH_PAGE.md#18-m1-w2同截止法人窗口與原件追溯)。舊 P2b ZIP fixture／live capture 未重跑。

驗收 reader exit0；serve 主動 Ctrl+C 中斷 exit1，shutdown `db_preserved=true`／guard0。已核自有 API／Node／esbuild 三 PID、8781／8782 listeners 為0，owned tab 已關；新增測試附件／raw／DB／tmp 殘留0，舊資源及 NO-RETRY 不動。精確命令、版本與收據留原 task。

### M1-W3 三截止法人窗口的零落盤驗證入口

W3當時 [`test_institutional_windows.py`](../../backend/tests/test_institutional_windows.py) 仍保留 legacy預設 suite；當輪已跑 `--w3-only`的7個 worker memory case及 `--w3-api-only`的5個 actual router case。`--serve`使用 MockTransport，只有另核 `--serve --live-source-opt-in`才取當次真原件。沿既有 Python `-B -X utf8`與 owned API／UI pair **8781／8782**，不載 conftest／正式 app startup、不建 DB或 fixture檔；W3記憶體 loader只准當次 pins／三截止scope，不能把此入口直接用於 W4新日期。

W3當時 [`institutional-window-preview.cjs`](../../tools/institutional-window-preview.cjs) 沿共用唯讀 `--deps <既有 frontend/node_modules>`；當輪需 `--w3-only`才選 full-src noEmit／24 SSR／三截止 mock product HTTP，預設仍為舊 suite。可合 `--typecheck-only`略過 HTTP，或合 `--serve`以完整 App、esbuild `write:false`作記憶體 bundle，字型 fallback。worker7、actual router5、SSR24、noEmit及 mock HTTP／BigInt三 cutoff36 net均 exit0；程式驗證的43 GET／22 POST為本地 product HTTP，source外網0／guard0／19表不變，不當成真來源請求。首 worker fixture誤污染 index致 exit1，改為僅污染 daily後7例通過；原失敗留 task，舊 ZIP／live及 full suite未重跑。

統籌另驗新增日期 probe與 production first POST兩個觀測：probe2 GET／287,489 body bytes；actual API3105／9/30首次 production24 GET／3,191,051 body bytes，合計外部26 GET，並非一次26原件 batch或 process峰值。native兩股三 cutoff使用其同一 held24原件，repeat POST／普通 GET不新增來源請求。獨立真值及來源 gate見[來源 §14](../SOURCE_REGISTRY.md#14-m1-w3三截止法人來源與窗口)，native可信事件／setup與未驗項見[個股頁 §19](../STOCK_RESEARCH_PAGE.md#19-m1-w3三截止法人窗口與原件追溯)。

驗收用 catalog與 price seed僅 synthetic-memory；真來源驗收限 TPEx法人／指數原件，不證測試 catalog身分或 seed是真行情／正式 DB。19表不變包含這些 dummy price／catalog原欄，沒有將它們升格為正式資料證據。

驗收 reader exit0，19表全欄／typeof由 before至 shutdown不變。owned API／Node服務均主動 Ctrl+C，原 exit均1；API shutdown為 `db_preserved=true`／guard0，Node未輸出最終 guard計數，不補稱 exit0或有 finalcounter。自有 API／Node／esbuild PID、8781／8782 listeners及唯一 owned page已獨立核缺席，ownedpageclose=true／tabs空。新測試附件／raw／tmp／DB／artifact0；這不代表全 cache或歷史殘留0。

最初 Orca snapshot／eval兩次 connection failure及未 focus時 ack但0 trusted事件的操作保留；後 `--focus`原生成功，未重啟 browser或重新取來源。horizontal原生手勢、physical canvas、Vite／production build與 pending導航 race未驗。詳細命令、UTC、full hashes、首跑失敗／修正與清理收據留原 task；不建立新附件，原 NO-RETRY仍適用。

### M1-W4 四截止法人窗口的零落盤驗證入口

現行 [`test_institutional_windows.py`](../../backend/tests/test_institutional_windows.py) 用 `--w4-only`驗9個 worker memory case，`--w4-api-only`驗5個 actual router case；選 `--w4-api-case first-post`只跑具名 first-post。沿 Python `-B -X utf8`、AST config stub、guarded memory SQLite及既有唯讀依賴，不載 conftest／正式 app startup、不建 DB／fixture檔。 `--serve`預設 MockTransport，另核 `--serve --live-source-opt-in`才取當次26原件；W4 pins／四截止不授權 W5新日期。

現行 [`institutional-window-preview.cjs`](../../tools/institutional-window-preview.cjs) 沿共用唯讀 `--deps <既有 frontend/node_modules>`，需 `--w4-only`才選 full-src noEmit／40 SSR／四截止48 net mock HTTP；可合 `--typecheck-only`或 `--serve`。完整 App用 esbuild `write:false` memory bundle，字型僅 fallback，不代 production build。

本輪 Python3.12.14／httpx0.28.1 worker9首exit0。API首suite exit1：4例通過，1例誤把 `capture_state.action=acquired／cached`的整物件作相等比較；只修斷言後具名 first-post局部1例exit0，另涵蓋9/30、10/1、10/2 first POST。不把原suite exit1改為0或稱整套補跑。Node24.19.0／TypeScript5.9.3／esbuild0.25.12的 noEmit／40 SSR／48 mock HTTP BigInt net exit0。API原跑＋補case＋Node合計60個本地GET／32 POST，source外網0、guards0、同fixture19表全欄／typeof不變、新測試附件0；本地 product HTTP不是source請求。

Mock驗證自有54400／54808／35436／54632 PID及8781／8782 listeners已核缺席；API Ctrl+C原exit1、shutdown `db_preserved=true`／guard0，Node reader exit0，esbuild exit未獨立觀測。此收據限 mock服務；actual-source服務另有以下清理驗收。

統籌另驗新增 probe2 GET／146,823B及 first actual API POST3105／9/29的 production26 GET／3,337,874B，獨立觀測合計28 GET，不是一次28原件batch／memory峰值。native兩股四 cutoff沿同 held26，repeat POST／普通 GET零新增來源請求。每日／全月 OHLC／23日曆、48 net／1800重複 API字串見[來源 §15](../SOURCE_REGISTRY.md#15-m1-w4四截止法人來源與全月日曆核對)，具名可信表單、原列及未驗邊界見[個股頁 §20](../STOCK_RESEARCH_PAGE.md#20-m1-w4四截止法人窗口與原件追溯)。

Actual-source驗收的19表全欄／typeof至 shutdown不變。兩 serve均 Ctrl+C原exit1；API shutdown為DB preserved／guard0，Node無最終guardcounter、esbuild exit未知，不補exit0或finalcounter。自有API53388／shell54604、Node54672／shell53380／esbuild53204及exact UUID browser helper後驗缺席；GetActiveTcpListeners在8781／8782成功回count0，先前connect_ex10035不足以證absence。唯一 owned page一次close／closed=true，post tabs=[]，零新增raw／DB／tmp／pycache／log／artifact；只接受exact scope，不稱全cache0。

Catalog／price seed僅 synthetic-memory，19表不變不證 seed是真行情、正式DB或 catalog身分。原API斷言失敗、checker GET404及原生工具／quote／focus失敗留原 task；不改原exit，不新增驗收附件。Legacy／ZIP／old live／full suite／build未重跑；horizontal原生手勢、physical canvas與pending導航 race未驗，既有 NO-RETRY及零新增落盤限制保持。

### M1-W5 五截止法人窗口的零落盤驗證入口

現行 [`test_institutional_windows.py`](../../backend/tests/test_institutional_windows.py) 用 `--w5-only`驗11個worker synthetic memory cases，`--w5-api-only`驗5個real-router／MockTransport cases；`--w5-api-case`只限具名case。沿核定既有Python3.12.14／httpx0.28.1、`-B -X utf8`、AST config stub／guarded memory SQLite，不載conftest／正式startup，不建DB／fixture檔。`--serve`預設mock；另核 `--serve --live-source-opt-in`才取當次W5原件，不由普通GET／import取得外來源。

現行 [`institutional-window-preview.cjs`](../../tools/institutional-window-preview.cjs) 沿共用唯讀 `--deps <既有 frontend/node_modules>`；`--w5-only`選full-src noEmit／62 SSR／五截止60 net mock HTTP，可合 `--typecheck-only`或 `--serve`。完整App採esbuild `write:false` memory bundle／fallback字型，不代production build；W3／W4 selectors保留，但本輪不稱新globals下其整套已重驗。

Python11 worker首exit0、5 API mock首exit0；API為48 local GET／26 POST，每fixture19表全欄／typeof前後不變、guards0、source外網0。核定Node24.19.0／TS5.9.3／esbuild0.25.12的noEmit／62 SSR／60 mock BigInt首exit0，24 GET／10 POST、guards0。較早Node20.19.4 exit0保留為非核定runtime收據；只補受影響檢查，不將原runtime誤稱核定。兩mock服務Ctrl+C原exit1保留，不補exit0。

統籌actual來源probe4 GET／150,072B、first actual POST3105／9/24新production27 GET／3,485,390B為獨立觀測；合計31 external GET不是一批31原件／process峰值。Root獨立memory reader首exit0，24 local GET／11 POST含initial capture及10 held組；後追加唯讀DOM expected／最後guard核，沒有重取外來源。兩股原生BUTTON重複POST仍held27。43全月index／24日曆、全daily／selected金融欄、60 net及2250重疊API字串集中[來源 §16](../SOURCE_REGISTRY.md#16-m1-w5五截止法人來源與完整有界日曆)；10可信表單、來源外層／新8/28日列及拒用界線集中[個股頁 §21](../STOCK_RESEARCH_PAGE.md#21-m1-w5五截止法人窗口與原件追溯)。

Actual owned page `e73b4c86-93e6-44ee-9cbf-2ee8c8ca65fe`單次close成功、tabs=[]。Node及API各Ctrl+C原exit1；API shutdown19表preserved／guards0，Node無final guardcounter、esbuild exit未獨立觀測，不補通過。自有API55556／shell29188、Node5032／shell11624／esbuild52988及owned children後驗缺席；GetActiveTcpListeners在8781／8782成功回count0，不以connect_ex不足結果證absence。附件／tmp／raw／DB／pycache／log／artifact新增0；正式程式8檔及docs7檔不當附件，不稱全cache0。

原connection／quote／os206／snapshot截斷／ack0 trusted及unsupported日期setup錯誤留原task，不改原exit、不把ack當native證據。PS預設Get-Content中文mojibake僅stdout，後以UTF-8原文／DOM核，不採亂碼為來源；App search_code缺pattern一次isError經更正、無mutation，不把所有toolerrors稱0。詳細命令／raw收據留原task，不新增附件。

Catalog／price seed僅synthetic-memory，19表不變不證seed是真行情或正式DB。缺／壞8/28局部窗口失效只必要synthetic API／SSR，實際missing0；非actual缺日原生。Legacy／ZIP／old live／full suite／Vite／production build未重跑，physical canvas／native horizontal gesture／pending導航race未驗；既有NO-RETRY及零新增落盤限制不變。

### M1-W6 六截止法人窗口的零落盤驗證入口

現行 [`test_institutional_windows.py`](../../backend/tests/test_institutional_windows.py) 的 `--w6-only`為worker synthetic memory、`--w6-api-only`為real-router／MockTransport；具名case沿 `--w6-api-case`。沿既有Python3.12.14／httpx0.28.1、`-B -X utf8`、AST config stub／guarded memory SQLite，不載conftest／正式startup，不建DB／fixture檔。`--serve`預設mock；另核 `--serve --live-source-opt-in`才取W6當次原件，普通GET／import零外網。

[`institutional-window-preview.cjs`](../../tools/institutional-window-preview.cjs) 沿共用唯讀 `--deps <既有 frontend/node_modules>`；`--w6-only`選full-src noEmit／SSR／六cutoff72 net mock HTTP，可合 `--typecheck-only`或 `--serve`。完整App採esbuild `write:false` memory bundle／fallback字型，非Vite／production build。W3／W4／W5 selectors保留，不稱新globals下整套重驗。新增owned shutdown guardcounter／esbuild exit收據接線本身不代已核清理。

必要mock已有限接受：Python3.12.14／httpx0.28.1 worker首11 cases exit1（10 passed／1 fixture誤8/27越界），修8/26後 `--w6-worker-case calendar-scope`局部1 exit0；API首5 cases exit1（4 passed／1期待60而actual72），修72後 `--w6-api-case batch`局部1 exit0。原API56 GET／29 POST、補26 GET／13 POST，guards均0、19 memory表全欄／typeof保留；只補受影響case，不稱11／5全套首跑通過。

Bundled Node24.19.0／TS5.9.3／esbuild0.25.12 full-src noEmit／76 SSR首exit0；mock HTTP76 SSR／72 BigInt net exit0，28 GET／12 POST、held28，三preview asset GET200。首node-e因PS5 quoting SyntaxError exit1／0HTTP，改ASCII stdin後exit0。Mock兩serve Ctrl+C各raw exit1；API shutdown preserved／guards0，Node SIGINT／final guards0已觀測，esbuild自身exit未知。五owned PID及checker／esbuild／children與8781／8782 listeners後驗缺席，新增artifact0。Actual probe4 GET／147446B與first POST3105／9/23新production28 GET／3630280B分開，共32 external GET非單批／峰值。Root獨立raw／policy／25日曆／1100金融原字串、72 net／2700重疊API字串及19表全部欄／typeof保留／guards0見[來源 §17](../SOURCE_REGISTRY.md#17-m1-w6六截止法人來源與完整有界日曆)；12可信日期form／72 DOM net、2160來源金融欄及390×844新原列／拒用已有限接受，見[個股頁 §22](../STOCK_RESEARCH_PAGE.md#22-m1-w6六截止法人窗口與原件追溯)。

Root actual owned page `26adac27-0ecb-4e01-89e0-227ff0d41304` once close成功、tabs=[]；API37524／shell55520、Node25384／shell43920／esbuild43476及children後驗缺席，8781／8782 GetActiveTcpListeners各0。兩actual serve Ctrl+C各raw exit1保留；API shutdown19表preserved／guards0，Node SIGINT／final guards0已觀測，esbuild自身exit仍unknown，不補exit0。

原probe shared httpx ModuleNotFoundError、只讀code純數字AssertionError／detail path KeyError，以及snapshot／tabswitch focus／wait URL glob connectionclosed均原exit1保留；direct PS eval quoting、CSS ack未open、outer-open／trusted檢查及date-reader JSON誤parse（0submit）留原task，修正後不重取來源或新建證據檔。明示來源原件只存process memory；附件／raw／DB／tmp／pycache／log／artifact新增0不等於全cache0。Catalog／price seed僅synthetic-memory，19表保留不證seed是真行情或正式DB；範圍外／PIT、保存／跨程序讀回、legacy／ZIP／old live／full suite／physical canvas／native橫向手勢／Vite／production build／pending導航race未驗，既有NO-RETRY與零落盤限制不變。逐次命令、runtime、原失敗、hash與清理收據留原task／Git，不新增附件。

### M1-W7 七截止法人窗口的零落盤驗證入口

現行 [`test_institutional_windows.py`](../../backend/tests/test_institutional_windows.py) 的 `--w7-only`為8個worker synthetic memory cases，`--w7-api-only`為5個real-router／MockTransport cases。Python3.12.14／httpx0.28.1，`-B -X utf8`、AST config stub／guarded memory SQLite，不載conftest／正式startup、不建DB／fixture檔；`--serve`預設mock，另核 `--serve --live-source-opt-in`才取W7當次原件，普通GET／import零外網。Backend/.venv metadata誤入口首exit1保留，改用master根共用.venv，未建立環境。

[`institutional-window-preview.cjs`](../../tools/institutional-window-preview.cjs) 沿共用唯讀 `--deps <既有 frontend/node_modules>`；`--w7-only`選full-src noEmit／90 SSR／七cutoff84 net mock HTTP，可合 `--typecheck-only`或 `--serve`。完整App採esbuild `write:false` memory bundle／fallback字型，非Vite／production build；舊selectors保留，不稱本輪整套重驗。

Python8 worker／5 API mock首各exit0；5 API local66 GET／33 POST、source外網0、19表全部欄／typeof保留及guards0。Node先由PATH20.19.4跑過，為非pinned收據；後explicit Node24.19.0／TS5.9.3／esbuild0.25.12補核full-src noEmit／90 SSR／mock84 BigInt net exit0，32 GET／14 POST、held29，不稱首次即pinned。只跑本輪必要驗證，未跑項不報通過。

Root PROBE-1取得1body後因ZoneInfo formatter缺tzdata exit1、未完成全驗／byteshash收據；PROBE-2獨立4 GET／146640B，first actual POST3105／9/22另production29 GET／3774364B。合計1＋4＋29=34 external GET為三觀測，首body bytes未知，不稱一批34、總bytes全已知或peak memory。完整43月列／26日曆、23485daily full rows／52 selected／1144金融原字串、84 net／3150 API重疊字串及ALL29 receipt SHA獨算見[來源 §18](../SOURCE_REGISTRY.md#18-m1-w7七截止法人來源與完整有界日曆)；root browser前actual local32 GET／15 POST不含browser總數。14可信form／84 DOM net、2520來源金融欄、兩股390×844新8/26原列及拒用界線見[個股頁 §23](../STOCK_RESEARCH_PAGE.md#23-m1-w7七截止法人窗口與原件追溯)。

Browser首三次錯namespace help exit1；snapshot／tabswitch focus兩次connectionclosed，unquoted @ref splat invalid argument，focus ack／keyup未出trusted事件均不算pass。Audit normcase(None) TypeError在spawn前、0process；goto後漏--focus使draft未變，讀W6 archived成功receipt後核exact own terminal＋same page --focus才通，未恢復舊角色。Monthend ArrowUp9/31空draft assert exit1／0submit，修有效方向只補剩6、未重跑已通8。String.raw backtick SyntaxError為0tools；額外長命令os206 rejected／0process屬長命令限制，非approval review。Extras viewport兩次connectionclosed、誤worktree switch unknown exit1／0mutation，核own terminal switch＋same page focus後補通。無reload／restart／新page或來源重取；原命令／exit／trusted evidence留原task，不新增附件。

本輪唯一owned page `9ec9559e-a34e-4467-8122-c0aaad36605c` once close ok=true／post tabs=[]。API55348／shell49668、Node1856／shell21680／esbuild37568及children fresh後驗absent，8781／8782 listeners0。API Ctrl+C raw exit1，shutdown19表preserved／guards0可觀測。Node兩Ctrl+C使listener關閉、active connection仍等待，final guard無觀測；root fresh PID／parent21680／explicit24 executable／cmdline核後 `ROOT-W7-PREVIEW-STOP-1` Stop-Process exact1856 exit0、PTY raw exit1，不稱Node SIGINT final guard通過。Esbuild已觀測exit code3221225786／signal=null，不再unknown；清理結果與驗證exit分報。

原件僅process memory，無重啟重取／新增raw、helper、DB、pycache、附件或artifact，不稱全profile／cache0。Catalog／price seed僅synthetic；缺／壞8/26按窗口失效只必要synthetic API／SSR，actual missing0。範圍外／PIT、保存／跨程序讀回、legacy／ZIP／old live／full suite／physical canvas／native橫向手勢／Vite／production build／pending導航race未驗；既有NO-RETRY與零新增落盤限制不變。

### M1-W8 八截止法人窗口的零落盤驗證入口

現行 [`test_institutional_windows.py`](../../backend/tests/test_institutional_windows.py) 的 `--w8-only`為8個worker synthetic memory cases，`--w8-api-only`為5個real-router／MockTransport cases。Python3.12.14／httpx0.28.1，各first exit0；API synthetic local75 GET／36 POST／source0。沿 `-B -X utf8`、AST config stub／guarded memory SQLite，不載conftest／正式startup，不建DB／fixture檔；`--serve`預設mock，另用 `--serve --live-source-opt-in`才取W8當次原件，普通GET／import零外網，共用既有環境。

[`institutional-window-preview.cjs`](../../tools/institutional-window-preview.cjs)沿共用唯讀 `--deps <既有 frontend/node_modules>`，explicit Node24.19.0／TS5.9.3／esbuild0.25.12；`--w8-only --typecheck-only` full-src noEmit／104 SSR exit0，guards0／artifact0。Full App `--w8-only --serve`以esbuild `write:false` memory bundle／fallback字型接actual API，非Vite／production build。Node mock HTTP未跑；產品fetch／Response.json的真96 net由root具名16組native覆蓋，不稱mock96 HTTP通過，不重跑old／full／legacy／ZIP／old live／build。W1–W7分節為Git當時版本收據；舊selectors僅保留歷史class byte，W8未重跑，不稱現版可pass，重現須查Git當時版本。

Root source probe4 GET／146055B與first actual POST3105／9/21 production30 GET／3917863B為兩個獨立觀測；全43月列／27日曆、24383 daily full rows／54 selected／1188金融原字串、96 net／3600 API重疊字串及ALL30 body／canonical receipt SHA獨算見[來源 §19](../SOURCE_REGISTRY.md#19-m1-w8八截止法人來源與完整有界日曆)。Root browser前具名local34 GET／33 POST，historical parser錯把`## 18.`混入小節導致assert0／exit1，前30 source／96 API及3600欄已通；修正唯讀2 GET／0 POST／source0核全84歷史及ALL30 hash canonical exit0，不重POST／外源。原JS const reassign TypeError為0tools／0GET；PS讀§18以SimpleMatch產生多行$n array後op_Subtraction exit1／0mutation，改唯讀Python補通。原命令與exit留原task，不抹首錯。

ROOT-W8-NATIVE-3105-1／6488-1：各8unique可信日期spinbutton方向鍵＋FORM submit，全16組explicit390×844，96 DOM net／5及20日起迄／actual missing0通；16outer SUMMARY可信click對held30的2880 DOM金融欄、兩股新8/25 nested原列、repeat held30／source0及拒用見[個股頁 §24](../STOCK_RESEARCH_PAGE.md#24-m1-w8八截止法人窗口與原件追溯)。初snapshot connectionclosed exit1、goto `--focus` unknown exit1／0goto、browser eval PS雙引號strip造成privatefield `#stock` SyntaxError exit1／0product、exec help unknown exit1／0product均未算pass。初focus／key／click ack無trusted／date／outer open不算成功；fresh focus／viewport scroll後可信通。6488 goto／tab focus後actual1277×924使viewport assert1／0forms，explicit重設390×844後才8unique通；不稱1277×924是窄版驗收。本輪建立1個owned page，其後無額外page／reload／restart／來源重取或附件。

ROOT-W8-PREVIEW-CLOSE-1：唯一owned page `f86c37bb-b554-4f85-854a-d874bb062eaf` once close rawexit0、post tabs=[]。Node52108（parent57256／esbuild57136）Ctrl+C一次，SIGINT shutdown finalguard0／disk0正面可觀測，PTY rawexit1；esbuild exit code未觀測，不沿用W7值。API55612（venv launcher54804／shell56612）Ctrl+C一次，shutdown19表全欄／typeof preserved=true、finalguard0正面，PTY rawexit1。Fresh六PID及children／8781和8782 listeners均absent；無Stop-Process、第二signal或重啟重取。清理結果與驗證exit分報。

服務清理後、文件更新前worktree225files（224tracked＋.git111B）／14dirs／4366028B，額外ignored／untracked新增0；原件僅process memory，無raw、helper、DB、pycache、附件或artifact，不稱全profile／cache0。Catalog／price seed synthetic；缺／壞8/25只有必要synthetic API／SSR，actual missing0。範圍外／PIT、保存／跨程序讀回、原生水平手勢／physical canvas／Vite production build／nav race未驗；W7外清literal `\n` SyntaxError為另案永久NO-RETRY，不混product錯誤或報approval拒，既有零新增落盤限制不變。

### M1-CHIPS-CUTOFF-1006-1 同截止法人窗口的零落盤驗證入口

沿共用Python3.12.14／httpx0.28.1、`-B -X utf8`、既有唯讀dependencies及guarded SQLite `:memory:`；不載conftest／正式config mkdir／startup，不建DB／raw／fixture檔／pycache／helper或附件。Exact來源／pins及執行上限由[來源 §31](../SOURCE_REGISTRY.md#31-m1-chips-cutoff-1006-1同1006法人窗口與完整有界日曆)管理，具名操作與未驗由[個股頁 §36](../STOCK_RESEARCH_PAGE.md#36-m1-chips-cutoff-1006-1同截止法人窗口與完整日曆)管理；本文不另授權金融重跑。

新[`test_institutional_windows_1006.py`](../../backend/tests/test_institutional_windows_1006.py)的`--worker-only`／`--worker-case <具名case>`及`--api-only`只使用最小synthetic memory，`--serve`預設mock。Root另核`--serve --live-source-opt-in --policy-version <新version> --policy-digest <新digest>`才開NEW empty新／W8 Store，finance seed0，不preload／samecapture replay；API／preview owned pair8799／8800。新啟用變數為`STOCK_TPEX_INSTITUTIONAL_1006_MEMORY_CAPTURE=1`及`STOCK_TPEX_INSTITUTIONAL_1006_POLICY_VERSION/DIGEST`，import／普通startup／GET不fetch。

沿[`institutional-window-preview.cjs`](../../tools/institutional-window-preview.cjs)及共用唯讀`--deps <既有frontend/node_modules>`；explicit Node24.19.0／TypeScript5.9.3／esbuild0.25.12，`--chips-1006-only --typecheck-only`核new SSR／full-src noEmit；`--serve`完整App esbuild `write:false` memory bundle，非production build。原W8 StockOverview受影響SSR另局部核對，不把old selector歷史整套升格為現版pass。

Program final worker10＋唯一新增bound case1、actual-router synthetic API3、new SSR98／full-src noEmit及受影響W8 StockOverviewSSR104 rawexit均0；19 memory DB表schema／values／每cell typeof保留、guards0／sourceGET0／diskartifact0。Synthetic18396B、retained graph284153～284960B估算非RSS／peak。Frontend中途detached provenance fixture修正前exit1保留，final98／104／typecheck0；原命令、版本與exit留原task，不抹首錯。Root policy／source／API／manual獨立proof各exit0。

ROOT metadata6與financial總46分項見來源§31.4，不稱整輪22或整輪total body bytes完整。OBS2 22及post-source-edit native NEW22各2907099B／18098 daily full rows；獨立reader source0／disk0／guards0、22body與原22canonical receipt hash、40selected1000欄／880金融、144calendar欄及12nets核通，graph9568313B只估算。全部真值與可見操作由兩份主題契約負責，不重存原件或manifest。

ROOT清理proof exit0：API13668／parent34328、preview59284／parent14996、esbuild35088 absent，8799／8800無listener；ONE page `34a24963-6f67-43dc-810d-57439fab7e91` lifetime1正常closed／tabs[]。先正常停API再沿same-token native讀得502及清值，未重啟producer。兩次Normal Ctrl+C各rawexit1，不能改成exit0；服務／reader退出釋放本輪memory raw，diskartifact0。

只跑變更所需驗證，未跑full DB／backend suite／production build／install；child financial GET／POST0，沒有disk cases／KeepArtifacts。舊price private1791644B／3files＋3dirs仍因CreateProcess前auto-review拒絕而NO-RETRY、at-cap不新增disk測試；整個DAY-RANGE worktree／branch兩次拒絕fence及其他歷史資源保持，功能與清理分報。

### M1-SAVED-PRICE-FOCUS-1006-1 保存來源關注的零落盤驗證入口

沿既有 `tools/tpex-price-api.py`／`tools/tpex-price-preview.cjs`及唯讀共用dependencies；Python `-B -X utf8`、guarded SQLite `:memory:`，Node `write:false`／full-src noEmit／incremental:false／composite:false。不載正式DB、一般startup mkdir或conftest，不建新環境／helper／backup／fixture檔。來源用途與精確pins由[來源 §32](../SOURCE_REGISTRY.md#32-m1-saved-price-focus-1006-1保存來源的七股關注准入)管理，actual操作見[個股頁 §37](../STOCK_RESEARCH_PAGE.md#37-m1-saved-price-focus-1006-1保存來源關注與同截止往返)；本節不另授權重跑。

NEW product reader用 `--serve --cutoff 2026-10-06 --saved-source-only`、原capture `--policy-version/--policy-digest`、原storage `--private-store-root/--private-policy-version/--private-policy-digest`，另需新 `--saved-focus-policy-version/--saved-focus-policy-digest`。只有原task核定existing private root／finite讀取quota後可啟用；consumer opt-in不允live-source opt-in、preloaded Store、POST、old saved入口繞過或memory／DB hydration。來源§32的10s cooperative／32MiB graph estimate、檔案bounds與兩reader共用96 quota不作OS deadline／RSS保證。Actual成功snapshot28、logical file reads84＋root獨立9＝93；preview observed api_get30／api_post0不是外部金融GET30。

本B1 current metadata／external financial GET均0、新disk writes0／DBmut0；NEW reader1與為尚未驗detail failure分支另准的NEW reader2都empty Store／finance seed0／memorydisabled／preloaded=false。19 DB表PRAGMA與sqlite_master table/index/trigger definitions、全部values／每cell typeof在兩reader前後相等；guards全部0、無capture_attempt／cache／raw持久化。原三檔full bytes／SHA／mtimeNS前後不變，完整觀測、原canonical receipt及時間由來源§32管理，不重存原件或manifest。

Necessary final rawexit0：backend saved-focus6；frontend55 helper／17 App SSR／5 Overview SSR及33src noEmit。Frontend首次typecheck exit1／23 narrowing diagnostics已修正，final0；不抹首次失敗。最小synthetic memory七列，quota serialized≤80KiB／graph≤512KiB，actual frontend76367B／480088B；fixture不代實際私人讀取。既有Python3.12.14／FastAPI0.141.1／SQLAlchemy2.0.52／httpx0.28.1，Node24.19.0／TypeScript5.9.3／esbuild0.25.12。逐輪exact命令／ID／原exit／版本封存收據留原task，只跑變更所需checks，未跑full suite／production build／install／diskcases。

Owned reader1／reader2及preview normal Ctrl+C各rawexit1，ROOT獨立runtime cleanup proof0分報：兩reader與parents、preview／parent／esbuild皆absent，8799／8800無listener；ONE lifetime page正常closed、fresh tabs=[]，compiler正常exit0／無本輪repo artifacts。Focus502與新detail502由各自正常停止reader後同page／同token驗，不重啟producer，不replay／HAR／screenshot／export。Native96 events全trusted；CLI讀取／quoting等失敗、首次selection失敗與root diagnostic/raw assertion exit1及後續readonly0保持分報，不稱首次皆成功。

**既有私人disk原件仍1791644B／3files，不是global disk0。** 原scope common parent／productroot／bundle共3dirs；runner只計root＋bundle兩層，不把兩種口徑混成殘留消失。原清理auto-review在CreateProcess前以 `blocked by policy` 拒絕，process／deletion0，STRICT NO-RETRY：不換工具／path／owner、逐檔、rename／containing tree繞過。Filecount已at-cap，本輪不新增diskcases／copy／export／publish／delete；actual missing-file UI NOT RUN，synthetic integrity拒用與actual HTTP502分別保留。

整個historic DAY-RANGE worktree／branch與 `.range-ui`2555430B／232files／94dirs strict NO-RETRY retain；不掃Temp／HAR／profile／cache／history。功能通過與owned runtime清理通過不把以上受保護殘留稱已刪。普通20／21close、trend／strategy／time／PIT／execution及完整ROADMAP仍缺；既有通過證據不因換角色重跑。

### M1-SAVED-PRICE-CHIPS-INTEGRATION-1006-1 共同入口的零落盤驗證入口

只沿既有 `tools/tpex-price-api.py`／`tools/tpex-price-preview.cjs`、共用dependencies及guarded SQLite `:memory:`；Python3.12.14 `-B -X utf8`、pinned Node24.19.0、TypeScript5.9.3／esbuild0.25.12。Shell node20.19.4另列，不代pinned runtime；不install、建helper／fixture檔、startup mkdir、正式DB或複製環境。來源／quota由[§33](../SOURCE_REGISTRY.md#33-m1-saved-price-chips-integration-1006-1保存行情與法人窗口共同入口)管理，本節不另授權重跑。

API／preview皆需 `--serve --saved-source-only --saved-price-chips-opt-in`；API另需 `--cutoff 2026-10-06 --private-root` 原task literal root，preview `--api-port 8799`／memory bundle。外部五組pins：capture `--policy-version/--policy-digest`、storage `--private-policy-version/--private-policy-digest`、saved consumer `--saved-focus-policy-version/--saved-focus-policy-digest`、chips `--chips-policy-version/--chips-policy-digest`、joint `--joint-policy-version/--joint-policy-digest`。Joint不允 `--live-source-opt-in`；僅此preview compile `VITE_SAVED_PRICE_CHIPS_INTEGRATION='m1-v1'`，write:false／noEmit／incremental:false／composite:false。

Necessary final各rawexit0：Py6、Node42guard／9recovery／7AppSSR、full33src noEmit。首次Node TS narrowing exit1與首次Python synthetic cutoff fixture exit1修正後0，原exit保留；小型memory fixtures只驗invalid／provenance／same-generation兩成功recovery，不代actual missing-private-file UI。未跑full old SSR／suite／install／production build／diskcases。

Actual SINGLE producer／NEW stores／finance seed0、trusted FIRST22；ROOT independently全22 body／原canonical receipt／times及金融raw0。19 SQLite完整schema／allvalues／cell typeof前後相等，guards0／product newdisk0／DBmut0。Private actual9producer＋3ROOT＝12snapshots／36logicalfiles；首ROOT Unicode assertion raw1計入quota、OBS2 corrected0／OBS3 post-stop0，原三檔bytes／SHA／mtimeNS不變。Exact命令、raw errors／request／版本封存receipt留原task。

API50788／parent55084、preview28516／parent44304 normal Ctrl+C各rawexit1／stoppedtrue，DISTINCT ROOT cleanup `bb71a4` raw0核上述及esbuild37844 absent、8799／8800無listener。Local preview /__price_ui/receipt GET1為只讀memory metadata，無proxy/private I/O；api_get14／api_post3／rejected6非金融GET；held POST200 source0後同token502清兩來源，無APIrestart。ONE page正常closed `443dd850-d6ff-40c1-beae-9a3acd7246b9` raw0，fresh tabs[] `460238f7-04d5-4a2c-919c-a28c17e94432`。Chips graph隨退出釋放，private disk仍1791644B／3files／3dirs at-cap；actualmissing-file UI NOT RUN。Strict NO-RETRY及ENTIRE DAY-RANGE fence見來源§33，功能／清理分報，非global disk0或allrawreleased。


### M1-SAVED-PRICE-CHIPS-FOCUS-1006-1 八條件入口的零落盤驗證入口

沿前節共用pinned dependencies、API/preview及guarded SQLite `:memory:`，不install／建helper或fixture檔／startup mkdir／正式DB／另建環境。新 `--saved-price-chips-focus-opt-in` 與 `VITE_SAVED_PRICE_CHIPS_FOCUS='m1-v1'` 獨立；本preview old integration flag OFF。New pair為 `--joint-focus-policy-version m1-saved-price-chips-focus-tpex-2026-10-06.1 --joint-focus-policy-digest sha256:1b48fc6bb23b021f3d289c797b8d077af4576f492cbc08953d0515ef0da89416`；另核原capture/storage/saved-focus/chips/joint五組pins、原task literal private root及finite quota，原flags/公式不改。

必要checks：Py6 raw0沿用；final pinned Node raw0＝59checks／17guards／7SSR／36src noEmit。首次10個optional windows type diagnostics exit1修正後0；write:false/noEmit/incremental:false/composite:false。Memory fixture serialized41039B／graph279196B、largest287512B為interned payload＋slot估算，非RSSpeak。Full命令／版本／原exit與read-only assertion/quoting修正收據留ROOT原task，本節不另授權重跑。

Actual只FIRST index2／1502B、daily0，Oct10/7超immutable10/6scope而拒用；[§39](../STOCK_RESEARCH_PAGE.md#39-m1-saved-price-chips-focus-1006-1八條件入口與不可用驗收邊界)管理桌面／窄版unavailable。Private4producer＋3ROOT＝7/21（含首次assertion），post-stop原三檔bytes/SHA/mtimeNS不變；19DB schema/values/cell typeof保留、guards0/DBmut0/new productdisk0。Detail新flag attempted失敗guard在previewbuild後修正並驗memory，無previewrestart／後續native，actual detail NOT RUN；oldexpression保持。

API／preview正常stop各raw1，ROOT owned cleanup raw0核processes absent／8799+8800無listener，ONEpageclose raw0／fresh tabs[]；commands/PIDs/lifecycle receipts留ROOT task，功能與清理分報。停API後native只證masked，沒有HTTP502status／positive→clear驗收。Matching／verifiedzero／jointdetail／八RAWback／負門檻actual未驗；actual missing-file NOT RUN，未跑fullsuite/install/productionbuild/diskcases。

來源/caps/no-retry由[§34](../SOURCE_REGISTRY.md#34-m1-saved-price-chips-focus-1006-1保存行情與法人條件關注准入及日曆缺口)管理。Private1791644B／3files／原3dirs ATCAP仍disk保留；ENTIRE DAY-RANGE worktree/branch及.range-ui、TURNOVER/較舊資源排除cleanup，禁替代tool/path/owner／逐檔/rename/containingtree、copy/export/publish/delete/newdiskcases。Core0/dep0/reliability0/stall1；unavailable受驗不解除正向來源依賴。
### M2-FOCUS-STOCK-SCOPE-6 八股新來源日的零落盤驗證入口

沿既有 `tools/tpex-price-api.py`／`tools/tpex-price-preview.cjs`、共用pinned dependencies、Python `-B -X utf8`／guarded SQLite `:memory:`、Node `write:false/noEmit/incremental:false/composite:false`；未install／建helper／disk fixture／新環境／正式DB。新policy／worker／projection／consumer pins及有限FIRST範圍由[來源 §35](../SOURCE_REGISTRY.md#35-m2-focus-stock-scope-6八股與新來源日准入)管理，exact啟動命令及所有raw exits留ROOT原task，不另授權重跑。

必要final證據已接受：Py8＋30guards raw0；pinned Node18＋19＋16SSR＋30guards及full36src noEmit raw0。Early synthetic flat方向預期錯誤SSR raw1修正後0；intermediate compiler SIGTERM不當通過，final PID28028 exit0。Read-only DOM selector raw1及native Ctrl+A append／SAME page Home/Delete修正收據保留，不抹除無效動作。

Memory fixture caps80KiB serialized／512KiB graph：Py max81050B／213428B、Node72387B／307860B；都是estimate，非RSS或construction peak。19 memory tables的schema／index／trigger／全values／每cell typeof preserved；guards0／newdisk0／private0／financeSeed0／preloaded=false。Metadata7 attempts包含兩未知partial，不聲稱總bytes已知；financialGET2／known3586610B／兩份1793305B原件及ORIGINAL receipts見來源§35。

ONE native page、183 ALLtrusted events、actual API九案、desktop／窄版detail＋五RAWback、真零／恢復及same page post-stop HTTP502清值由[個股頁 §40](../STOCK_RESEARCH_PAGE.md#40-m2-focus-stock-scope-6八股四條件與同截止往返)管理。Final preview20 localAPI GET／1POST／14rejected不是finance GET。停止後detail error actual NOT RUN（SSR不代actual）；沒有restart或重抓。

Cleanup分報：API normalstop session13309 rawexit1、preview15835 rawexit1；ROOT2920ca raw0獨立核54084／14816／50816／13292／23404／esbuild43744 absent、8799＋8800無listener。ONE pageclose `8c35344b-edac-4d7a-8078-4c6b09112f3c` raw0，fresh tabs[] receipt `1e80df05-2273-4180-9efd-e79229f5b8b4`；只此owned scope，沒有刪私人或其他worktree。Inherited private／DAY-RANGE／MAIN5／holiday及failed chips NO-RETRY依[協作紀錄](../TASK_COORDINATION.md)保持。

Coreoperation+1／standalone dependency0／reliability+1／stall1→0；未跑old/full suite／production build／install／diskcases／actual post-stop detail error。完整M1／M2／M3、PIT／ordinary20或21close history／strategy／time／execution未完成。DOC／freeze／qualified index／Git尚待ROOT original-task接受。

### M1-SAVED-PRICE-CHIPS-FOCUS-CALENDAR-1006-2 全月日曆八條件的零落盤驗證入口

沿共用pinned Python3.12.14 `-B -X utf8`、Node24.19／TypeScript5.9.3／esbuild0.25.12、既有API/preview及guarded SQLite `:memory:`；不install/helper/fixture檔/DB複製/正式DB。新API／preview `--serve --saved-source-only --saved-price-chips-focus-calendar-opt-in`，與old joint/focus flags互斥；API另需 `--cutoff 2026-10-06 --private-root` 原task literal root，preview `--api-port 8799`／memory bundle。新compile `VITE_SAVED_PRICE_CHIPS_FOCUS_CALENDAR='m1-v2'`，old flags OFF。

外部六組pairs仍為capture `--policy-version/--policy-digest`、storage `--private-policy-version/--private-policy-digest`、saved-focus `--saved-focus-policy-version/--saved-focus-policy-digest`、new chips `--chips-policy-version/--chips-policy-digest`、new entry `--joint-policy-version/--joint-policy-digest`、new focus `--joint-focus-policy-version/--joint-focus-policy-digest`；前三不改、新三version／canonical bytes／digest由[來源 §36](../SOURCE_REGISTRY.md#36-m1-saved-price-chips-focus-calendar-1006-2全月日曆與八條件來源准入)單一管理。Exact啟動／check命令與原exit留ROOT task，本節不另授權重跑。

必要final checks：Python12／47034B serialized／142547B graph raw0，含正常GET route非空body首chunk在DB/source前拒用；pinned Node full38src noEmit／validators41／proxy10／SSR22 raw0，compiler29380正常exit0。Aggregate77473B／453892B≤80KiB／512KiB，為estimate非RSSpeak；write:false/noEmit/incremental:false/composite:false，guard0/artifact0/child actual GET/private0。早期Py404／Node／JSON quoting／alnum validator／command-length206/process0 failures保留原task，修正後必要checks被ROOT獨立接受，不抹原exit；未跑old/fullsuite／install／productionbuild／diskcases。

ONE actualFIRST22／2907155B及兩股12net見來源§36；API/proxy50guards、native positive／真零／samecutoff detail／八RAWback與實際focus/detail502清兩來源見[個股頁 §41](../STOCK_RESEARCH_PAGE.md#41-m1-saved-price-chips-focus-calendar-1006-2八條件正向關注與同截止往返)。Current preview為negative card repair前bundle；POSTFIX NEGATIVE CARD ACTUAL NOT RUN，僅final SSR／API／detail負值受驗；actual missing-file及post-stop recovery亦未跑。

Cleanup分報：API session83980／Python5840、preview80879／Node53608 normal Ctrl+C各rawexit1、不restart；ROOT86760b raw0核5840/33436/53608/13008/esbuild44944 absent、8799+8800無listener。ONE intendedpage正常close、fresh tabs[]；兩misfocus about:blank pages各正常close，不作globaltabs清理聲明。Final proxy22 localGET/1POST/23rejected非financialGET；19DB全schema/index/trigger/values/每cell typeof保留。Actual26producer＋ROOT2＋inherited7＝35snapshots/105logicalfiles，post-stop原三檔bytes/SHA/mtimeNS不變。PrivateATCAP與DAY/TURNOVER/MAIN五cache、較舊資源NO-RETRY排除fence不改；功能與清理分報，非globaldisk0/allrawreleased。Coreoperation+1/standalone dep0/reliability+1/stall0；DOC/freeze/qualified index/Git仍待ROOT接受。


### M1-SAVED-PRICE-CHIPS-FOCUS-STOCK-SCOPE-7-1006-1 七股八條件的零落盤驗證入口

沿共用pinned Python3.12.14 `-B -X utf8`／FastAPI0.141.1／SQLAlchemy2.0.52／httpx0.28.1及Node24.19／TypeScript5.9.3／esbuild0.25.12；guarded SQLite `:memory:`，不install/helper/fixture檔/DB複製/正式DB。New API/preview `--serve --saved-source-only --saved-price-chips-focus-stock-scope-7-opt-in`，與old/calendar flags互斥；API另需 `--cutoff 2026-10-06 --private-store-root` 原task exactroot，preview `--api-port 8799`／memory bundle，compile `VITE_SAVED_PRICE_CHIPS_FOCUS_STOCK_SCOPE_7='m1-v1'`、old flags OFF。

外部capture/storage/saved-focus/chips/joint/joint-focus六組version/digest args沿前節；前三price pins不變，新三canonical version/bytes/SHA由[來源 §37](../SOURCE_REGISTRY.md#37-m1-saved-price-chips-focus-stock-scope-7-1006-1七股共同來源准入)管理。ROOT先核用途與pins才implementation/GET/privateIO；原啟動/check commands／版本／exit及各failed invocation留原task，本節不授權重跑或來源配額。

Final必要checks：Python15＋168 aggregate cases raw0，含全7×2×3 net aggregate signed int64越界guard；Node38src noEmit／68validators／10proxy／21SSR raw0，compiler15500 normalexit0，ROOT獨立接受。Python fixture56276B/graph151199B、Node21898B/graph506788B，各在80KiB/512KiB界線內；不同process估算不當RSSpeak。NoEmit／write:false／incremental:false／composite:false、guard0/artifact0/children actual GET-private0；未跑old/fullsuite/install/productionbuild/diskcases。

Actual FIRST22／2907155B／140rows／42nets見來源§37；12 API ops及58 preFIRST guards、七股desktop/narrow positive／新profile negative cards／fullseven真零／七detail／八RAWback／actual detail和focus502清兩來源見[個股頁 §42](../STOCK_RESEARCH_PAGE.md#42-m1-saved-price-chips-focus-stock-scope-7-1006-1七股八條件與同截止往返)。First API harness KeyError raw1後剩11有限案raw0、不重首request；大raw輸出truncated／local猜POST405→正capture409、failed CLI/offscreen/selectionmiss原收據保持。Actual missingfile/recovery NOT RUN，synthetic不代actual；old calendar negative-card history不改。

Cleanup分報：ONE API34519 Python38660/parent18404，normalCtrlC＋SAMEpoll rawexit1；ONE preview34887 Node43592/parent18576/esbuild39252 normalCtrlC rawexit1。ROOT核五PIDs absent／8799+8800none；ONE intendedpage normalclose/fresh tabs[]，未restart。Finalproxy26GET/1POST/27rejected localNOTfinancialGET；19DB schema/index/trigger/values/everycelltypeof preserved，financeSeed0/preloadedfalse/formalDB0/newdisk0/childIO0。

Private inherited35＋producer26＋ROOT2＝FINAL63bundles/189logicalfiles≤shared64/192，reserve1unused且非future grant；原三檔full SHA/bytes/mtime與receipts不變，producer26 SPENT。ATCAP／preCreateProcess拒絕STRICT NO-RETRY及ENTIRE DAY/TURNOVER/MAIN五literal cache＋holiday CRLF/older資源排除不改，不掃Temp/HAR/GPG/cache/log/history，非globaldisk0/allrawreleased。Coreoperation+1/standalone coredependency0/reliability+1/stall0→0；DOC review/freeze/qualified index/commit/另准master merge待。

### M1-CHIPS-STOCK-SCOPE-7-DAILY-NET-TREND-20-1006-1 七股每日淨超的零落盤驗證入口

本次獨立chips-only入口為 `tools/tpex-chips-series-api.py`、`tools/tpex-chips-series-preview.cjs`；不使用old saved/joint producer、private root或price fetch。沿pinned Python3.12.14 `-B -X utf8`、FastAPI0.141.1／httpx0.28.1及Node24.19／TypeScript5.9.3／esbuild0.25.12，只讀既有backend/.deps與frontend/node_modules，不install、建helper／fixture檔、DB或整套來源副本。新policy version／外部digest由[來源 §38](../SOURCE_REGISTRY.md#38-m1-chips-stock-scope-7-daily-net-trend-20-1006-1七股每日法人淨超與窗口累計)單一管理。

下列為已驗入口形狀，原exact commands／版本／raw exit留原task；文件不授權再FIRST／重啟或更新配額。API只在 `--serve --chips-series-stock-scope-7-opt-in` 明示啟用；新preview flag與old flags獨立互斥，GET/capture僅as_of，三UI RAW不可當額外API keys。

```powershell
$seriesNode = 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -X utf8 tools/tpex-chips-series-api.py --check
& $seriesNode tools/tpex-chips-series-preview.cjs --check
& $seriesNode tools/tpex-chips-series-preview.cjs --check --check-ui-only
& $seriesNode tools/tpex-chips-series-preview.cjs --check --check-startup-only
# 本批受驗serve的有限local ports；必須沿ROOT原task准入與外部pins
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -X utf8 tools/tpex-chips-series-api.py --serve --chips-series-stock-scope-7-opt-in --port 8801 --policy-version m1-chips-daily-net-series-stock-scope-7-tpex-2026-10-06.1 --policy-digest sha256:143aabb4cd2d86110d5564793ce77b0fb6c60b3e603f23c1e188875934a48a31
& $seriesNode tools/tpex-chips-series-preview.cjs --serve --chips-series-stock-scope-7-opt-in --api-port 8801 --port 8802 --policy-version m1-chips-daily-net-series-stock-scope-7-tpex-2026-10-06.1 --policy-digest sha256:143aabb4cd2d86110d5564793ce77b0fb6c60b3e603f23c1e188875934a48a31
```

Necessary checks：Python15、41src noEmit＋25validators＋84SSR、targeted41／UI follow-up與startup-only DNS/CSS guard修正均raw0。ROOT已獨立接受；沒有因換角色重跑。NoEmit／write:false及guard0/newdisk0；fixture／數值／零窗口仍synthetic，不代actual來源／操作，未跑production build／完整old suites／diskcases。必要compiler／Node已核absent。政策cap中的retained8748386B為estimate，非RSS／construction peak；headers／deadline的postcheck／cooperative限制由來源§38管理。

ONE API保持empty新generation；首次preview BEFORELISTEN因literal local DNS／font CSS失敗raw1，financial/private/proxy/disk0。SAME程式角色只修preview一檔，後一次成功；不是one preview attempt total，API未restart，FIRST前source0。Scoped42窗口／525prefix／dated point-row／ALL25calendar、477 trusted events與unsupported／502 actual見[個股頁 §43](../STOCK_RESEARCH_PAGE.md#43-m1-chips-stock-scope-7-daily-net-trend-20-1006-1七股每日淨超與累計操作)。Local receipt cap8193首raw1後修正cachedPOST409，未financial retry；original harness／鍵盤／RT失敗及未跑actual whole-window zero／post-stop recovery保留，不報通過。

退出分報：API normal Ctrl+C rawexit1（source22／guards0），成功preview SAMEhandle normal Ctrl+C rawexit1；final localproxy8GET／3POST／34reject非financial。ROOT核五owned PIDs absent、8801／8802無listener；ONE page normalclose／fresh tabs[]，不重啟服務／browser。Current privateactualIO0／metadataGET0／ordinarypriceGET0／正式DB0／newdisk0；私人三檔與FINAL63/189、remaining1非grant／STRICTNO-RETRY、DAY／MAIN／older資源fences見[協作紀錄](../TASK_COORDINATION.md)，不稱globaldisk0或MAINignored0。

Coreoperation+1／standalone dep0／reliability+1／stall0→0。使用者要求本批DOC／freeze／qualified索引／commit／另准local master merge後暫停；文件截止以上版本工作待ROOT，不回寫hash或重做成功驗證。Current四角色／worktree保留，沒有outside owner接手own4清理；前任四角色normalclose/archive已接受，exact前任worktree/branch removal仍須另滿足qualified indexes／mergedmaster／freshclean／baselineunneeded。

## 歷史驗證

完整原文可由 `git show 5ae84d2:docs/development-baseline/README.md` 取閱；其他歷史入口見[文件索引](../README.md#歷史查閱)。已刪 Temp 附件不作接手依賴；未清、審核拒絕及占用資源仍依協作紀錄處理。

### M2-OFFICIAL-EVENT-DATE-RANGE-20261008-1 官方事件區間的零落盤驗證入口

ROOT已接受本批必要checks與actual操作；文件角色不重跑。Backend入口為[test_official_events.py](../../backend/tests/test_official_events.py)／[test_official_event_focus.py](../../backend/tests/test_official_event_focus.py)，101 passed／38 warnings／raw0；首輪99 passed＋2failed／raw1保留。Node20.19.4／TypeScript5.9.3／esbuild0.25.12，[tpex-price-preview.cjs](../../tools/tpex-price-preview.cjs) `--event-range-check` 為獨立零網路模式，41src noEmit／69checks raw0；初SSR設定raw1保留。既有price query四條件共享URL相容與事件不滲價量API屬必要檢查，不擴舊price來源驗收。

Checks使用可重建記憶體fixture與既有依賴，不install／建helper、DB、cache、build／raw／附件；noEmit與memory-only consumer保持。範圍包含日期grammar／inclusive／單側／invalid先於source與catalogue、完整feed先驗後range／q、計數／cap／返回、首次失敗跨focus／selected shared seal及retry0。Synthetic邊界不代真原件、原三instrument catalogue只routing。原exact命令／版本／所有raw exit與工具參數、quoting、offscreen／未送達操作收據留task；本段不授權重跑金融來源或producer。

Actual ONE金融GET／62列及[來源 §39.1](../SOURCE_REGISTRY.md#391-m2-official-event-date-range-20261008-1實際來源結果)已接受；可信desktop／390px／同截止往返／真零／API停止後502清值見[個股頁 §44](../STOCK_RESEARCH_PAGE.md#44-m2-official-event-date-range-20261008-1官方事件日期區間與研究往返)。Preview共16GET／1POST均loopback，不另算金融GET；RAM原件隨API終了釋放，不replay／restart。

退出分報：API／Node preview normal SIGINT各raw1，不改報exit0；ROOT核owned49216／8484／62180 absent、8797／8798無listener，唯一tab `f9a30d71-ea8a-4190-b875-3cf6c977602f` 正常close、本根tabs=[]。本批filesystem／privateIO／磁碟DB／cache／build／raw／附件產物0；功能驗收與退出分報，非全專案清理。Coreoperation+1／dependency0／reliability+1／stall0→0；DOC review／freeze／索引／commit／merge與下輪交接、關閉封存清理待ROOT，見[協作紀錄](../TASK_COORDINATION.md)。

### M2-OFFICIAL-EVENT-KIND-20261008-1/B1 官方事件類型的零落盤驗證入口

ROOT已接受必要checks，文件角色不重跑。Python3.12.14／pytest8.4.2：[test_official_events.py](../../backend/tests/test_official_events.py)及[test_official_event_focus.py](../../backend/tests/test_official_event_focus.py)，126passed／51warnings／raw0。原task UTF8 stdin以Python `-B -X utf8`、PYTHONDONTWRITEBYTECODE=1／PYTEST_DISABLE_PLUGIN_AUTOLOAD=1，sys.path先放本根backend／backend/tests及main backend/.deps；AST僅抽install_zero_disk_guard，以os／sys／Path globals編譯並先執行，再import pytest。pytest參數 `--noconftest -q -s -p no:cacheprovider -p no:logging` 加上述兩檔；只memory SQLite，禁止写入／mutation／subprocess／外網，完整inline命令留原task，不建helper或環境。

Node20.19.4／TypeScript5.9.3／esbuild0.25.12，[tpex-price-preview.cjs](../../tools/tpex-price-preview.cjs)独立零網路check：

```powershell
& 'C:/Program Files/nodejs/node.exe' 'tools/tpex-price-preview.cjs' --deps 'C:/Users/YiCheng/Desktop/taiwan-stock-research/frontend/node_modules' --event-kind-check
```

41src noEmit＋116checks（helper58／response24／SSR13／API5／proxy16）raw0；RAM esbuild／既有Git fixture，不寫DB／cache／build／raw／Temp。原collection縮排raw1、125passed＋1fixturefail raw1、ROOT AST／quoting及browser ACK未delivery收據均保留，不改exit或擴為通過。

真来源及actual操作見[來源](../SOURCE_REGISTRY.md) §40／[個股頁](../STOCK_RESEARCH_PAGE.md) §45；synthetic4不代ordinary／fullmarket／price／PIT。API／preview normalSIGINT各raw1，preview31GET／1POST／0reject為loopback；ROOT核3PIDs absent、8803／8804無listener、ownedpage close／tabs[]。privateIO／新增test及product檔案0B，indexcache另報；原件RAM釋放不重啟。Coreoperation+1／standalone dep0／reliability0／stall0→0，版本待辦見[協作紀錄](../TASK_COORDINATION.md)。

## M1-TWSE-ISSUER-EVENT-PROFILE-20261008-1：公司與事件的零落盤驗證入口

2026-10-08。ROOT接受Source13／actual及本入口有限證據；DOC不重跑成功checks。原44backend／7warnings raw0、42src noEmit＋80targetchecks raw0沿用；0056不暗示ETF的最小文案修正後，2SSR＋42noEmit raw0。scope／provenance／date／Code與Namejoin／duplicate與conflict拒收／pins／single attempt FIRST failure SPENT／unavailable／failure clear用RAM fixtures驗，不代真來源或可信UI。實際1095×33 issuer及58×12event原件／全部映射由[來源](../SOURCE_REGISTRY.md) §41管理；可信desktop1365×900／390×844三股與五條件往返／502清值由[個股頁](../STOCK_RESEARCH_PAGE.md) §46管理。

### 記憶體測試與既有入口

後端[Test module](../../backend/tests/test_twse_issuer_profile.py)要求先安裝[test_official_events.py](../../backend/tests/test_official_events.py)的 `install_zero_disk_guard`，再import pytest／新module；原task以Python `-B -X utf8`／PYTHONDONTWRITEBYTECODE=1／PYTEST_DISABLE_PLUGIN_AUTOLOAD=1、main repo既有backend/.deps及本根import paths、AST抽取guard方式執行。pytest用 `--noconftest -q -s -p no:cacheprovider -p no:logging`，只RAM fixture／SQLite，不import app.main／conftest或寫DB；完整inline命令、版本、原exit與範圍留原task，不另建helper／環境。

前端新mode沿[tpex-price-preview.cjs](../../tools/tpex-price-preview.cjs)的既有RAM編譯／guard入口；必要已接受命令：

```powershell
& 'C:/Program Files/nodejs/node.exe' 'tools/tpex-price-preview.cjs' --deps 'C:/Users/YiCheng/Desktop/taiwan-stock-research/frontend/node_modules' --issuer-event-check
```

42src noEmit／80targetchecks只synthetic tuple／SSR／response／routing／proxy邊界，非金融／browser／磁碟保存／production build／普通股history證據；修字2SSR＋42noEmit是最小回歸，不因session／DOC換人重跑全部。初始backend／frontend raw1與ROOT引用／TTY／selector／offscreen ACK／rows-vs-items／read-onlyinspection錯誤原exit全保留，後續修正與actual接受分報，不回寫為全通或MCP／來源gate失敗。

### actual 與退出結果

ROOT actual20 TestClient calls含8invalid issuerPOST先422／sourceGET0／DB0、initial1449unavailable、三股positive／cachedPOST、missing-cutoff／07／0056unavailable、1463權10/15真零與恢復08；來源各只freshGET1。可信兩viewport六原欄／rawindustry／事件三型／雙trace、missing／earlier／2614原五條件back及nooverflow受驗。API停止後same-key1449READ POST502清兩區／headline／provenance、crossselected1463GET502 error／fields0是實際失敗拒用，不作positive；所有工具ACK須有狀態效果才計驗收。

API26328 normalSTOP raw0，shutdown實際印server_stoppedtrue／兩sourcegets各1／四audit0，完整原件RAM釋放不restart／replay／clone／hydrate／preload。修字前preview46188／compiler25556 normalSIGINT raw1／shutdown GET35 POST7 rejected0；修字後preview34000／compiler61744 RAM rebuild／normalSIGINT raw1／shutdown GET3 POST1 rejected0，API從未重啟／無新金融GET，兩preview guards／artifacts0。ROOT核5PID absent、8805／8806無listener、唯一ownedpage closed／tabs[]；全部test／product／artifactfiles0B／privateIO0，shared indexcache另報。metadata5／金融2已SPENT，無新quota／diskcase／private／正式DBgrant。

coreoperation+1／standalone coredependency0／reliability0／stall0→0，完整M1／M2／M3未完成；capital／payout numeric未驗、raw industry不代分類，ordinary20／21closes仍缺rights／calendar。版本及outside-cleanup接受見[協作紀錄](../TASK_COORDINATION.md)，DOCreview／freeze19／qualified7／commit／另准merge仍待；不建附件／來源副本／manifest報表。

## M1-TWSE-ISSUER-INDUSTRY-TRACE-20261008-1/B1：兩碼追溯的零落盤驗證入口

2026-10-08。ROOT接受SOURCE12、41backend／7warnings及45src noEmit＋71target checks raw0；本DOC不重跑。新[Test module](../../backend/tests/test_twse_issuer_industry.py)覆蓋two-code exact lookup、其他市場／空白／numeric／special／unknown拒用、external pins／宣告hash／date precision／source URLs、duplicate／conflict、同cutoff與完整dualSHA／ordinal、名稱與raw mappings。RAM fixtures是邊界計算證據，不代真公司／官方文件／可信UI；authority分別見[來源 §42](../SOURCE_REGISTRY.md)、[產業 §10](../INDUSTRY_CLASSIFICATION.md)、[個股頁 §47](../STOCK_RESEARCH_PAGE.md)。

沿[test_official_events.py](../../backend/tests/test_official_events.py)既有zero-disk guard，先安裝audit guard再import pytest／新module；用既有backend/.deps／本根路徑、Python `-B -X utf8`／PYTHONDONTWRITEBYTECODE=1／PYTEST_DISABLE_PLUGIN_AUTOLOAD=1及pytest noconftest、no cacheprovider／logging。只RAM fixtures／SQLite，不import app.main／conftest、建DB或寫Temp；完整本輪實際命令／版本／exit與限制留ROOT原task，不另建helper／環境／附件。

前端沿既有[RAM preview入口](../../tools/tpex-price-preview.cjs)的新bounded mode：

```powershell
& 'C:/Program Files/nodejs/node.exe' 'tools/tpex-price-preview.cjs' --deps 'C:/Users/YiCheng/Desktop/taiwan-stock-research/frontend/node_modules' --issuer-industry-check
```

45src noEmit＋71target checks是synthetic tuple／validator／SSR／query error與routing／proxy guard證據，不是financial truth／native UI／production build／磁碟保存。Serve只proxy ROOT-owned API，`--issuer-industry` 必須另有exact industry registry／consumer四external pins及已准入issuer／event pins；舊defaults／其他opt-in不自動升格。

ROOT兩fresh financial GET各1、NEW empty distinct generation、全1095×33 issuer與58×12event ORIGINAL body／receipt同RAM逐列核及21 direct API已受驗；金融quota2已SPENT，metadata parsed reader不證raw HTTP總數。Gov／Swagger新actual200及Swagger extractor KeyError raw1不重GET由來源§42記錄。Swagger抽取／offscreen ACK未delivery／inspection SyntaxError／DOC首命令CreateProcess os206（process0／write0）原失敗保留，不改exit或當來源／MCP阻擋；後續有效接受分報。

ROOT可信desktop1365×900／narrow390×844三股六原欄＋04／04／20完整名稱／三事件型、三完整trace與雙原件SHA／ordinals、分類effective未知、原五條件back／真零／missing／earlier07→08恢復、真失敗清值／nooverflow已接受。Missing／0056拒用另有narrow390及實際desktop1277核對；native select／navigation會重設emulated viewport到1277，ROOT重新設390並讀回才計窄版，不冒稱原一次尺寸。

原ROOT Orca eval shell quoting SyntaxError raw1、RAM reader regex escaping四Python SyntaxError raw1（filewrites0）、offscreen／非可見tab ACK未delivery、一次NaN scroll raw1保留。UI assertion使用URL未定義ReferenceError但actual DOM正確，修reader後成功、沒有source change；network limit6未被host限制、stdout truncation raw0，沒有HAR／落盤。只以 computer-use 恢復 Orca 視窗及選自有瀏覽器 tab（no screenshot），後續Orca trusted native按實際效果驗，不DOM mutation／新source GET；錯誤不改exit、不記passed。

API52996／session88784正常STOP raw0，實際SHUTDOWN／server_stopped=true／artifact0B，兩完整ORIGINAL RAM隨process終止釋放；preview55124／compiler31816／session47349正常SIGINT raw1，SHUTDOWN GET46／POST7／rejected0／FS、network、subprocess guards0／diskartifact0。三PID absent、8807／8808無listen、唯一ownedpage正常close receipt `a01ac02e-171e-4de1-acfa-54cb2c026833`／tabs[]核raw0；new test／productartifactfiles0B／privateIO0／DBfiles0。服務清理與正常SIGINT raw1分報，不restart／replay／clone／hydrate、不改退出值。

本批coreoperation+1／standalone coredependency0／reliability0／stall0→0、完整M1／M2／M3未完成；未跑production build／full suite／DB／diskcase／privateIO，shared indexcache另報。詳細命令／版本與一次性驗收留原task，不新增來源副本／manifest附件或保留整套成功產物。版本與有限outside cleanup見[協作紀錄](../TASK_COORDINATION.md)，DOC review／freeze／索引／commit／另准merge仍待。

## M1-CHIPS-STOCK-SCOPE-7-GROSS-TRADE-20-1006-1/B1：gross零落盤驗證入口

2026-10-08。ROOT接受source10及具名actual；本DOC不重跑。來源與操作邊界見[來源 §43](../SOURCE_REGISTRY.md)／[個股頁 §48](../STOCK_RESEARCH_PAGE.md)。Actual Python3.12.14／Nodev24.19.0／TS5.9.3／esbuild0.25.12／FastAPI0.141.1／httpx0.28.1／uvicorn0.52.4；SSR useLayoutEffect warnings原樣保留。

三命令在本worktree根實際通過raw0，未附`--deps`／policy-version／digest參數；runner預設共用main依賴，grossflag選獨立硬coded policy version／外部digest（SOURCE43），不提升oldpins：

```powershell
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -X utf8 tools/tpex-chips-series-api.py --check --chips-gross-stock-scope-7-opt-in
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' tools/tpex-chips-series-preview.cjs --check --chips-gross-stock-scope-7-opt-in
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' tools/tpex-chips-series-preview.cjs --check --check-ui-only --chips-gross-stock-scope-7-opt-in
```

依序11backend RAMtests；48src noEmit＋29validator＋84chartSSR；unknown-mask修正後48src noEmit／局部SSR、validator0／chart0沿用前證據。Fixtures／syntheticzero與SSR不代金融truth／nativeUI；checks sourceGET／network／disk-private-DB寫入0、各rejectionguard0，未跑productionbuild／fullsuite／磁碟保存。Actual SAMEgenFIRST22／雙SHA／ALL126totals與1575prefixcomponents、兩viewport ALL7矩陣／每日gross0／502清值由ROOT獨立接受。

API18464正常SIGINT raw1／SHUTDOWNtrue，source_requests22／producer22及disk_writes／mutations／private_reads／databases／subprocesses／network_rejections0。Preview42276／compiler35212正常SIGINT raw1／SHUTDOWNtrue，GET8／POST1／rejected_requests233，不記0或推原因；disk／private／network／subprocessrejection0。18464／42276／35212／7768absent、8809／8810nolisten、ownpage正常close／tabs[]；test／productartifacts0files0B／privateIO0／DB0／priceGET0，ORIGINAL RAM已釋放、不restart／replay／hydrate。

原raw1（missingimport／quote／PATHNode20guard／fixturemutation／JSONDecodeError／hiddenbrowser-board-RT-card assertions）保留；Ctrl+A ACK未選造成draftappend、execstoreundefined suppressedinner outcomeunknown亦留ROOTtask。更正後UTF8stdin／同READ actualCDP502分報，不改exit／重送金融；ignorednetworklimit／stdouttruncation不作取得證據，無helper／附件。Core+1／standalone dep0／reliability0／stall0→0，完整M1／M2／M3未完成；版本封存及outsidecleanup見[協作紀錄](../TASK_COORDINATION.md)。
## M1-CHIPS-STOCK-SCOPE-7-DIRECTION-SEGMENTS-20-1006-20261008-1/B1：方向區段零落盤入口

2026-10-08。ROOT有限接受actual，本DOC不重跑；來源及操作見[來源 §44](../SOURCE_REGISTRY.md)／[個股頁 §49](../STOCK_RESEARCH_PAGE.md)。Python3.12.14／Node24.19.0／TS5.9.3／esbuild0.25.12；新opt-in使用獨立ROOT外部pins，不升olddefaults。

本worktree根的三個check入口：

```powershell
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -X utf8 tools/tpex-chips-series-api.py --check --chips-direction-stock-scope-7-opt-in
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' tools/tpex-chips-series-preview.cjs --check --chips-direction-stock-scope-7-opt-in
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' tools/tpex-chips-series-preview.cjs --check --check-ui-only --chips-direction-stock-scope-7-opt-in
```

15backendRAM／51src noEmit＋37validator＋42groupSSR raw0；後UI局部51src＋42SSR raw0，validator37沿用。SSRwarnings、fixture／27signcases邊界與actualUI分報，不代金融truth；未跑productionbuild／fullsuite／磁碟保存。ROOT受驗FIRST22／完整原件API graph、84trustedconfigs／164native trace／真net零2及502清值沿PAGE49。

API36576／preview15748 normalSIGINT raw1且SHUTDOWNtrue，各guard0／source22；compiler9288隨preview停，auditor52704 /stop釋放22原件後最後raw0。四PIDabsent／8809、8810、8811nolisten／onlyownedpage正常close／freshtabs[]；previewproxy GET8／POST1／rejected_requests211保原數、不推原因。Test／productartifacts0files0B／privateIO0／DB0／ordinarypriceGET0，indexcache另報。

原quote／AXACK-noeffect／PSsyntax／Ctrl+A未選先assert／punctuation／offscreen／queryless POST422wrongassert／tablist--page等raw1保留ROOTtask；/stop已有效不重送，只修harness、不改exit或重送GET。Metadata截斷／receipts及reader403限制見SOURCE44；outsidecleanup與freeze/index/Git待辦見[協作紀錄](../TASK_COORDINATION.md)，不掃其他old／private／Temp／cache。

## M1-CHIPS-STOCK-SCOPE-7-ADJACENT-WINDOWS-5-1006-20261008-1/B1：相鄰窗口零落盤驗證入口

2026-10-08。ROOT接受SOURCE9及具名actual，本DOC不重跑成功驗證。來源／pins與操作見[來源 §45](../SOURCE_REGISTRY.md)／[個股頁 §50](../STOCK_RESEARCH_PAGE.md)。本根opt-in使用獨立ROOT外部canonical9284B及digest，不提升olddefaults；共用main依賴／pinned Node24.19.0，不另建環境。精確runtime版本、每次命令與raw exit留ROOT原task。

本worktree根的必要check入口：

```powershell
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -X utf8 tools/tpex-chips-series-api.py --check --chips-adjacent-stock-scope-7-opt-in
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' tools/tpex-chips-series-preview.cjs --check --chips-adjacent-stock-scope-7-opt-in
```

初backend19 RAM raw0仍適用、不因UI修再跑；frontend修後54src noEmit＋56validator（49原checks＋7RAM lifecycle）＋42SSR raw0，SSRwarnings保留。純fixture／overflow／zero／lifecycle及SSR不證financial truth／trusted nativeUI；未跑productionbuild／fullsuite／DB／磁碟保存。本DOC引用已接受證據，不執行產品check。

ROOT同RAM ORIGINAL／完整math停前共3次對帳，sourceGET仍12；581成功UI checks（含31masked）及未過harness逐項留原task。兩viewport42detailconfigs／210native pairclicks／420雙原列views、primary52 nativecalendaropens（非全批總數）、新前窗latestzero／同三RAWback及samekey502清ALL沿PAGE50。

Native return原live缺口局部修：pagehide flushSync mask＋selected清除／持續pageshow persisted守門；native Page.navigate／browser back→mask→READ兩viewport已核，persisted=true BFCache未觀察、不冒actual BFCache證據。兩source實質UI修後只重編RAM preview，不改API／auditor／既有數值與pins，不新增金融GET。

API20584 normalSIGINT raw1／SHUTDOWNtrue、source12／guards0；舊preview29600／compiler51012正常SIGINT raw1／SHUTDOWNtrue、GET15／POST1／rejected105，final preview37668／compiler34260正常SIGINT raw1／SHUTDOWNtrue、GET13／POST0／rejected26，不推rejected原因或改0。Auditor56144正常release／exitraw0、ORIGINAL12released／guards0；sixownedPIDs20584／29600／51012／37668／34260／56144最終absent、8812–8814 bindcheck無listener、ownedpage正常close／tabs[]已ROOT獨立核。初poststopAPIpid仍在raw1保留，後自然退出、無forcekill、後assert0。

FIRST input ACK無效與focus修正、unsupported Nonecalendar錯assert／correctedblank200、viewport／selector／expectedmask等原raw1保留，不改exit或當成功。CachedPOST含asof409／missing422已核；correctedunsupported及sameheld再驗source仍12。Product／testartifacts0files0B、privateIO0／DB0／ordinarypriceGET0，原件RAM全釋放，不restart／replay／clone／hydrate／preload；shared indexcache另報。文件命令首SyntaxError／CreateProcess長度等原失敗留task，無helper／附件或sourcecopy；不掃old／private／Temp／cache。

Core+1／standalone dep0／reliability+1／stall0→0，完整M1／M2／M3未完成；outsidecleanup已有限完成、版本freeze／索引／commit／另准merge待ROOT，詳[協作紀錄](../TASK_COORDINATION.md)。

## M1-CHIPS-STOCK-SCOPE-7-DEALER-COMPONENTS-5-1006-20261008-1/B1：三組對帳零落盤驗證入口

2026-10-08。ROOT接受SOURCE9及具名actual，本DOC不重跑已接受checks。新source／canonical9245B與外部digest／774B署名見[來源 §46](../SOURCE_REGISTRY.md)，actual操作見[個股頁 §51](../STOCK_RESEARCH_PAGE.md)。共用main現成backend/.deps及frontend/node_modules，不另建環境；pinned Node24.19.0／TypeScript5.9.3／esbuild0.25.12，精確Python runtime／命令／raw exit及逐次收據留原task。

本worktree根的必要check入口（memory-only、不得藉此重新啟動已釋放financial producer）：

```powershell
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -X utf8 tools/tpex-chips-series-api.py --check --chips-dealer-components-stock-scope-7-opt-in
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' tools/tpex-chips-series-preview.cjs --check --chips-dealer-components-stock-scope-7-opt-in
```

Backend15RAM raw0；front57src noEmit＋52validator/lifecycle＋42SSR raw0，warnings保留。Overflow／zero／missing／components／lifecycle fixture及SSR不代financial truth或trusted nativeUI；未跑productionbuild／fullsuite／DB／磁碟保存。本DOC只引用已接受收據，未執行產品checks。Wrongpin Python nativeexit2／tool2、Node nativeexit1／tool1在imports／compiler前拒收；原exit不改0。初TS nullableclosure raw1及patch tail rawfail保留。

首6metadata direct holder在完整ROOT transfer前EOF、raw0退出／RAM釋放，全6SPENT且gate未過，不稱來源失敗；2reader／NEW3完整准入界線見SOURCE46。ROOT AST stdout mojibake9472B／ca6d93…錯pin撤回於source／finance grant前，改ASCII JSON讀回9245B後才核，不沿用錯pin。New metadataholder54396／port56176正常SIGINT raw1、RAMreleasedtrue後PID／port absent、artifact0，不retry或留附件。

ROOT最初ALL7 ORIGINAL bodies及未增補receipt／math／fullAPI全核，停前完整再核一次；不冒3次fullmath或額外GET。金融source仍7SPENT。首次5newsource doubleEOF使原NUL diff raw3；每檔精確刪ONE LF共5B後ROOT以舊hash重組核bytes、tracked diffcheck raw0／new NULdiff raw1且空輸出。僅EOF修正，功能未變、不重驗；原raw3／raw1保留。

可信FIRST visible但productgoto viewport reset1277×924，當時未beforeclickassert1365；原gap保留，後續1365×900及390×844完整矩陣沿PAGE51。PRIMARY70 rawrows／70canonicalopens及52calendar opens不代表全batch click總數。ROOT `new Function`內await SyntaxError、兩offscreen link ACK未navigate、table clip下rawbutton點到DIV、typedscroll right invalid_argument、完整DOMprojection被序列化截成9calendar／錯count、postcutoff實際「截止後排除」而預設「否」錯assert原raw1保留。修ROOT auditor／scroll定位後 `scrollIntoView`只定位，fresh snapshot／native click及isTrusted actualtarget再核；不改source／重GET。

Canonical換列保留open，auditor直接toggle變closed的原assert raw1，改先close再open；PS ErrorActionPreference Stop遇既有Orca crashpad stderr提前raw1，當次改Continue仍核nativeexit／JSONok／targettrust，不把stderr改成功。大DOM eval超max輸出／JSON parse失敗後用compact projection及live DOM逐條比全26欄位。Blank PS CLI丟empty值／primitive JSON parse／Control+A ACK無keydown原raw1，改native End＋Backspace得真空值。全部harness失敗只修auditor，不混產品source或通過checks。

停前samekey5274／dealer／5／10/06兩viewportlive完整原列／54metrics／calendar先核；API normalSIGINT後narrow native READ actual502 fromlive清ALL、desktop同keyrepeat502由masked保持ALL清，RAW3back仍mask；非兩獨立producer。API32860 SHUTDOWNtrue／requests7／guards0 normalSIGINT toolraw1；preview15564／compiler25940 SHUTDOWNtrue、proxyGET23／POST1／rejected44，其餘guards0、normalSIGINT raw1，不推reject原因或改0。Auditor54880 normalSIGINT raw1／RAMreleasedtrue／guards0；停前RAMreaudit61996 raw0，metadataholder54396先前退出。六exactPIDs32860／15564／25940／54880／61996／54396 absent、8812–14無listener ROOTraw0；ownedpage正常close收據 `2298c5f3-9762-450b-9740-71291aff4a5e`／tabs[]已核。

ROOT ORIGINAL及derivedlist RAM全release，不restart／replay／clone／hydrate／preload。Product／testartifacts0files0B、privateIO0／DB0／ordinarypriceGET0；source／indexcache另報，無附件／helper／manifest／Temp，未掃older／private／cache。Core+1／standalone dep0／reliability0／stall0→0；outsidecleanup已接受、freeze／索引／commit／另准merge仍待ROOT，見[協作紀錄](../TASK_COORDINATION.md)。
