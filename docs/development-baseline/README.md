# 開發與驗證入口

協作、資料選擇、產物配額、保留例外與清理失敗依 [AGENTS](../../AGENTS.md#驗證資料與暫存)；現行接手與未清資源見[協作紀錄](../TASK_COORDINATION.md)。本文負責可重建入口、副作用與驗收方式。逐輪命令、版本、exit、計數、hash、退修及提交收據留原 task／Git；歷史 pass 不代表目前來源已驗收。

## 版本與資料

先以 `git status --short`、`git diff`、`git log -1` 核對來源。`.gitattributes` 固定 LF，replay 綁定的 source bytes 不可因換行改變。Git 保存測試與 fixture 建構方式，不保存本機 DB、raw、依賴或生成產物。磁碟驗收用專案外最小隔離檔案，仍須滿足各入口的 snapshot 契約。

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

## 歷史驗證

完整原文可由 `git show 5ae84d2:docs/development-baseline/README.md` 取閱；其他歷史入口見[文件索引](../README.md#歷史查閱)。已刪 Temp 附件不作接手依賴；未清、審核拒絕及占用資源仍依協作紀錄處理。
