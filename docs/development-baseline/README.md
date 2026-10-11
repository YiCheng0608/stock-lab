# 開發與驗證入口

本文管理可重建入口、副作用與驗收方式；資料、產物配額、保留及清理依 [AGENTS](../../AGENTS.md#驗證資料與暫存)。接手與未清資源記原 GitHub Issue；命令／版本／exit／計數／hash／退修／提交收據留原 Issue／Git，入口見[遷移說明](../TASK_COORDINATION.md)。下列 task／ROOT／freeze 收據只證歷史，不授權現行派工，也不證目前來源通過。

下列單次測試與具名來源的 GET／RAM／落盤上限只約束其授權範圍，不是全專案只能開一張任務的限制；跨任務仍須核共用資源及各自授權，不因另開 worktree 擴大配額。

## 版本與資料

先以 `git status --short`、`git diff`、`git log -1` 核對來源。`.gitattributes` 固定 LF，replay 綁定的 source bytes 不可因換行改變。Git 保存測試與 fixture 建構方式，不保存本機 DB、raw、依賴或生成產物。磁碟驗收用專案外最小隔離檔案，仍須滿足各入口的 snapshot 契約。

測試失敗先依[失敗分流與有界重驗](../GITHUB_WORKFLOW.md#失敗分流與有界重驗)分類；工具／環境失敗修正後重跑同一案例，不判產品結果，也不重取外部資料。

使用 API／preview 前，依[執行資源與服務版本](../GITHUB_WORKFLOW.md#執行資源與服務版本)核實載入版本與資源隔離；commit 不更新舊程序，補版本證據仍須遵守原件生命週期、quota 與 NO-RETRY。

## 測試資料庫分層

| 層 | 用途 | 寫權與共享 | owner |
| --- | --- | --- | --- |
| 日常 DB | 使用者研究與收集（[OPERATIONS](../OPERATIONS.md#1-工作目錄環境與啟停)預設 `.local/data/stock.db`） | 不作測試寫入、不放測試資料 | 使用者 |
| 固定版本唯讀樣本庫 | 核准的小型真實樣本；工程與 QA 讀同一版本 | 只讀開啟（SQLite `mode=ro`＋`PRAGMA query_only=ON`）；更新即產生新版本 | 全局核准、資料線 owner 維護 |
| 可重設隔離測試庫 | 寫入、migration、保存／跨程序測試 | 每次執行獨立路徑，由樣本庫或 fixture 建立；不共享可變狀態，不逐角色複製整份 DB | 該任務工程／QA |

- 三層都用產品 schema（`init-db` 建立），不另設假資料表或另一套查詢路徑。日常 DB 與隔離測試庫以三個 `STOCK_*` 指向該層的絕對路徑並於執行前讀回；樣本庫只以 `select` 回傳的唯讀 URI 開啟（URI 只帶 `mode=ro`，使用端另設 `PRAGMA query_only=ON`）；樣本庫與隔離測試庫放專案外、不入 Git、不複製私人 DB。產品 app 以讀寫方式開啟 `STOCK_DB_PATH`，不得把 app 或寫入測試直接指向樣本庫，須先複製到隔離測試庫。
- 樣本中繼資料隨樣本庫保存：來源用途權利（依 [SOURCE_REGISTRY](../SOURCE_REGISTRY.md#1-registry-與-policy-契約)）、資料日期、取得時間、schema 版本、抽樣規則、樣本版本、檔案 hash。真實樣本與人工邊界案例分開標示；必要原始回應與正規化欄位可追溯；未知發布時間／PIT 標未知，不補造。
- 按最小完整案例取樣：價格顯示少量日、MA60 至少 60 個交易日、公司行動含事件前後、七股驗收覆蓋七股。日常回歸、整合驗收、容量／效能案例分開，樣本庫不隨日常 DB 成長。
- 樣本庫的位置與大小限額在核准時登記，各單引用該登記，變更才重核；隔離測試庫在執行結束重設或清理，失敗回報路徑／大小／原因，不每輪重造 manifest。
- 本地重驗讀樣本庫不觸發外部 GET；人工 fixture 另驗錯誤邊界。沒有適用真實樣本時，該 AC 標未驗。

### 共用入口 `tools.test_db`

[tools/test_db](../../tools/test_db/__init__.py) 實作樣本庫與隔離測試庫（工具程序只用標準函式庫）。契約測試見 [guards](../../backend/tests/test_test_db_guards.py)、[entry](../../backend/tests/test_test_db_entry.py)、[real_sample](../../backend/tests/test_test_db_real_sample.py)，人工 fixture 範例見 [sample_basic.json](../../backend/tests/fixtures/test_db/sample_basic.json)（虛構資料，非市場資料）。從專案根目錄執行：

```powershell
python -B -X utf8 -m tools.test_db --root <專案外絕對路徑> [--max-bytes N] [--deps <依賴路徑>] <命令> [參數]
```

| 命令 | 用途 |
| --- | --- |
| `build-sample --version V --fixture F` | 以產品 `worker.cli init-db` 建 schema、載入人工 fixture，發布為不可變樣本版本；`--kind`（`manual_fixture` 預設或 `real_sample`）、`--meta`（metadata JSON 檔）、`--skip-product-check` |
| `freeze --run-id R --version V` | 把隔離測試庫發布為新樣本版本；選項同上 |
| `list-samples` | 列各版本的 kind、schema、hash、大小；損壞的版本在其項目內列錯誤 |
| `verify --version V` | 檢查檔案集合、版本、hash／大小、Alembic 標記，預設再做產品檢查 |
| `select --version V` | 同 `verify` 但預設不做產品檢查（`--check-product` 開啟），回傳供只讀開啟的 URI；樣本位置不得作寫入目標 |
| `isolate [--version V]` | 建獨立可寫 run（`--run-id` 可指定，不重用）：給版本則複製已驗樣本，省略則 `init-db` 空庫；回傳 run 路徑與三個 `STOCK_*` |
| `reset --run-id R` | 還原 run 到初始狀態：樣本來源先重驗樣本再重複製，空庫重跑 `init-db`；路徑不變，`data/`（含 `raw/`）與 `tmp/` 重建 |
| `cleanup --run-id R` | 移除 run；標記最後才刪，失敗可用同一 run id 重試 |
| `usage` | `--root` 的已用／剩餘位元組與各子目錄用量 |
| `load-fixture --run-id R --fixture F` | 把 fixture 列載入 run |
| `read-table --table T` | 以獨立唯讀連線讀回前 `--limit`（預設 100）列；目標 `--run-id` 或 `--version` 擇一 |
| `exec [--version V] -- 命令…` | 建 run、以隔離 `STOCK_*` 執行命令，結束必清理；`--check-product` 同 `select` |

- 參數：`--root`（或 `STOCK_TESTDB_ROOT`）必填，須為專案外絕對路徑，不得在產品 checkout、`.local/data` 或繼承來的 `STOCK_*` 位置內，建目錄前即拒絕。`--max-bytes` 預設 50,000,000（十進位 50 MB）。`--python` 指定產品子程序的直譯器（預設本程序的），`--deps`（可重複）或 `STOCK_TEST_DEPS`（以路徑分隔字元串接）指定子程序可 import 的既有依賴路徑；`--timeout` 預設 180 秒，只限產品子程序。
- 輸出：每個命令印一個 JSON，exit 0 或 1。成功 `{"ok":true,"result":…}`；失敗 `{"ok":false,"error":{code,reason,path,size_bytes,details}}`，`path` 為絕對路徑，涉及檔案或目錄樹時帶 `size_bytes`。argparse 參數錯誤 exit 2 且不建檔。`exec` 的 exit 為被執行命令的 exit，成功時工具 JSON（含執行前 `STOCK_*` 讀回）寫 stderr，stdout 留給該命令。
- 錯誤碼：守門 `forbidden_target`／`stock_env_invalid`／`reparse_point`／`invalid_argument`；樣本 `version_missing`／`version_mismatch`／`version_exists`／`hash_mismatch`／`schema_mismatch`／`sample_corrupt`／`metadata_invalid`／`fixture_invalid`；抽取 `source_mismatch`；run `run_exists`／`run_not_found`／`not_a_run_dir`／`not_found`；資源 `quota_exceeded`／`cleanup_failed`／`in_use`／`io_error`；產品子程序 `product_failed`／`product_timeout`。
- 版面：`<root>/samples/<version>/{sample.db,metadata.json}`（OS 唯讀屬性；目錄恰此兩檔，否則 `sample_corrupt`）、`<root>/runs/<run-id>/{.testdb-run.json,data/stock.db,data/raw/,tmp/}`、`<root>/tmp/`（schema 檢查暫存）。版本名與 run id 須符合 `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`；已發布版本不可覆蓋（`version_exists`）。需 run id 的命令只接受含 `.testdb-run.json` 且與 run id 相符的目錄，否則 `not_a_run_dir`，不碰無標記目錄。
- metadata：`metadata.json` 欄位為 `metadata_schema`、`sample_version`、`kind`、`source_rights`、`data_dates`、`acquired_at`、`publication_time`、`schema_version`、`sampling_rule`、`sha256`、`size_bytes`、`created_at`、`row_counts`、`provenance`，缺欄即 `metadata_invalid`。`publication_time` 未陳述時為 `unknown`，不推算。
- fixture：UTF-8 JSON `{"tables":[{"table":名稱,"rows":[{欄:值}]}],"data_dates":…}`，`data_dates` 選填（缺則 `unknown`）。載入為單一交易並啟用外鍵：未知表／欄、`sqlite_*`、違反約束或外鍵即 `fixture_invalid` 並整份回滾；`provenance` 記 fixture 檔名與 sha256。
- `real_sample`：須以 `--meta` 自行陳述 `source_rights`、`data_dates`、`acquired_at`、`sampling_rule`，發布前檢查（`build-sample` 在建任何 run 之前，`freeze` 在移入版本之前）；缺漏或未陳述任何內容的值回 `metadata_invalid`，不留版本。字串先 NFKC 正規化、不分大小寫並忽略空白與標點，整個值等於 `unknown`、`not-applicable`／`n/a`／`na`／`not available`、`tbd`／`tba`／`todo`、`none`／`null`／`nil`／`undefined`／`nan`、`無`／`未知`／`不適用`／`待定`／`待補`／`未定`，或只含空白與標點，即視為未陳述；list／dict 為空，或任一層巢狀值未陳述（如 `data_dates` 的 `first`／`last` 任一端的值未陳述）亦同；缺少的 key 不擋，只有 `first`、沒有 `last` 會接受。刻意不擋：只認上列占位詞，不在清單內的近義詞或同形異體字不擋；只比對整個值，以占位詞開頭但帶說明的字串（如 `not-applicable: …`、`None of the rows …`）會接受；數字與布林不判斷；`publication_time` 與 `provenance` 不檢查（未陳述時為 `unknown`）；只在發布時檢查，`verify`／`select` 不重驗 metadata 陳述。工具只擋未陳述，不判斷陳述是否屬實或符合上述來源權利規則。`manual_fixture` 的預設 metadata（如 `not-applicable: …`）不受此閘門影響。
- 隔離：工具程序不 import 產品 `app`（`app.config` import 時即建目錄並綁定路徑）；產品程式（`init-db`、schema 檢查、`exec` 命令）只在子程序執行，環境重建為：丟棄所有繼承的 `STOCK_*`（含 live-source opt-in），只設該 run 的三個 `STOCK_*`，`TEMP`／`TMP`／`TMPDIR` 指向 run 的 `tmp/`。啟動前讀回並檢查三者皆設、為無 `..` 的絕對路徑、全在該 run 目錄內；拒絕（`forbidden_target`／`stock_env_invalid`，不啟動）產品 checkout（含 repo `data/`、`.local`）、`.local/data`、繼承來的 `STOCK_*` 位置與樣本庫內的目標。工具根為連結或 reparse point 即拒絕；根內含連結時 `usage` 與配額記帳 fail-closed（`reparse_point`，指出路徑）。
- schema 檢查邊界：`verify`、`build-sample`、`freeze` 預設做產品檢查，`select`、`isolate`、`exec` 預設不做，需 `--check-product`；檔案集合、版本、hash／大小、Alembic 標記、metadata 一律檢查。產品檢查為產品啟動用的 `check_database_readiness`（必要表／欄、主鍵、唯一鍵、外鍵）加樣本 `schema_version` 等於 Alembic head，不比對完整 DDL（多出的欄位不失敗），也不稽核資料。樣本的 OS 唯讀屬性、hash 與 metadata 可被有權限者一併改寫，防竄改須以 `--expect-sha256`（`verify`／`select`／`isolate`）對核准 hash。
- 配額邊界：`--max-bytes` 約束整個 `--root`（含非工具建立的檔案），只在工具管理的檢查點核算——`isolate`（有樣本時複製前先預估）、`reset`、`freeze`、`build-sample` 的複製、發布與建庫前後。超額回 `quota_exceeded`（`size_bytes` 為預計總量，`details` 含 current／incoming／limit），`isolate`、`freeze`、`build-sample` 不留該次新建的 run 或發布暫存。`load-fixture`、`init-db` 子程序與 `exec` 命令的寫入不受即時約束，事後核算才發現；因此是檢查點限額，不是即時硬上限。並行 `isolate` 的事後核算會看到彼此的複本，可能比序列多回 `quota_exceeded`，仍是單一 JSON。
- 並行與占用：不同 run 互不影響；記帳對他人正在清理而消失的項目視為已不存在，拒絕存取在約 0.2 秒重試後仍在才回 `io_error`（指出該項目）。同 run id 並行 `isolate` 恰一個成功、其餘 `run_exists`；同版本並行 `build-sample` 的敗者可能回 `in_use` 而非 `version_exists`，勝者完好。同一 run 不要同時 `reset` 與 `cleanup`，否則可能留下無標記的 run 目錄（含重建的 DB），`cleanup --run-id` 回 `not_a_run_dir`、無法以 id 清除，且仍計入配額，須人工移除。
- 清理失敗：其他程序持有 run 內檔案時，`cleanup`／`reset` 回 `cleanup_failed`（`path`／`size_bytes`／`reason` 指出首項，`details.failures` 列全部），可清項已清、標記保留，放手後以 run id 重試；`exec` 的 `cleanup_failed` 另帶 `details.command_exit_code`。唯讀屬性檔可清；連結與 reparse point 不進入、不刪除。run 內有無法列舉的目錄（如權限拒絕）時，`cleanup`／`reset`／`exec` 回 `io_error`（`path` 指向該目錄、`size_bytes` 為 null、無 `failures` 清單，`exec` 不帶 `command_exit_code`）而非 `cleanup_failed`，標記保留，排除後同樣可重試。
- 子程序與網路：`product_timeout` 只終止直接子程序，不追殺其子孫；`exec` 的命令不設逾時，子孫仍占用 run 檔案時清理回 `cleanup_failed`。隔離只涉及檔案路徑與 `STOCK_*`：工具不取源、預設不封鎖也不稽核網路，`exec` 只移除繼承的 live-source opt-in，命令是否連網由命令自負；要取得「本地讀用無網路」的證據時用下節的 `netguard`。
- 平台：檔案占用、junction／reparse point、ACL 拒絕與 `exec` 僅在 Windows 驗證，其他平台未驗。

### 真實樣本的抽取與無網路讀用

私人 TPEx 單日 bundle（`body.csv`、`capture-receipt.json`、`storage-receipt.json`，見 [SOURCE_REGISTRY §30.2](../SOURCE_REGISTRY.md#302-三檔原子出版與嚴格重驗)）只能以摘要入樣本庫。抽取與讀用各一個模組（標準函式庫，不 import 產品）：

```powershell
python -B -X utf8 -m tools.test_db.extract --source <bundle 目錄> --out <專案外絕對路徑>
python -B -X utf8 -m tools.test_db.netguard --log <檔案> -- <tools.test_db 的參數>
```

- **`extract`**：三檔只以唯讀開啟，不寫入、搬移，也不在來源目錄建任何檔。`--out` 須是專案外絕對路徑、不在產品 checkout／`.local/data`／繼承的 `STOCK_*` 位置內、與來源互不包含，且不覆寫既有檔。讀任何一列前先核 body SHA-256，以及兩份 receipt 與 [§29.1](../SOURCE_REGISTRY.md#291-1006-價格-policy-tuple-版本表) `.5`、[§30.1](../SOURCE_REGISTRY.md#301-fresh用途與獨立storage版本) 固定的 policy 版本與 digest、selected symbols、資料日、兩份 receipt 之間的 hash 與時間；任一不符回 `source_mismatch`，不輸出任何檔。通過後只輸出 `<name>-fixture.json`（`instruments`、`market_bars`，格式同 fixture）與 `<name>-metadata.json`（`--meta` 用）。兩檔含市場數值，只放 scratch 或樣本庫 `tmp/`，不入 repo、Git 或 GitHub；命令輸出只有 hash、筆數與欄位名。再以 `build-sample --kind real_sample --fixture <fixture> --meta <metadata>` 發布。
- **內建 profile 只有 A1**（`tpex_11370_daily_close_csv`、資料日 2026-10-06、3105／3293／5274／5347／6488／6510／8069 各一列，單日）。欄位對應：`代號`→`instruments.symbol`、`名稱`→`instruments.name`、`開盤／最高／最低／收盤`→`market_bars.open/high/low/close`、`成交股數`→`volume`、`成交金額`→`turnover`（`turnover_status=available`）。`adj_close` 取 `close`（沿用產品 worker 的保存方式，不是還原價）；`created_at`／`collected_at` 取 receipt `captured_at`，不是建檔時間；`raw_payload_id` 為 NULL，原始回應以 body／receipt hash 記在 `provenance` 追溯，不複製；其餘來源欄位不存。`publication_time` 取 receipt，未陳述為 `unknown`。不涵蓋多日歷史、MA60 或公司行動案例。
- **`netguard`**：以 audit hook 在連線、名稱解析與 datagram 送出之前拋 `NetworkBlocked`，每個被武裝的程序在 `--log` 寫一行 `armed`，每次攔截寫一行 `blocked`。產品子程序與 `exec` 的命令經 `guard_site/sitecustomize.py` 一併武裝；更早在 `PYTHONPATH` 的 `sitecustomize` 會使子程序不被武裝，須以 log 的 `armed` 核對。hook 無法卸除，須在獨立程序執行，不放進測試程序。它是證據而非隔離：`tools/test_db` 本身不 import 網路函式庫，也不取源。

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

stdout／stderr 在記憶體捕獲。以子程序 exit、八份無 skip 的 metrics 與 `validation_complete` 核對完整執行；`R1A2_RESULT` 分列 `test_exit`、`cleanup_exit`、確切殘留／大小／原因。八個 file-backed 案例不外推正式 DB、API startup、backup restore、UI 或完整 backend。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L55–L68](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L55-L68)。

### R1-A2 selected invalid／拒收的磁碟驗證入口

`tools/Invoke-StockDaySelectedInvalidValidation.ps1` 直接跑 `backend/tests/test_stock_day_selected_invalid_file_integration.py` 的一個 compound unittest；缺專用環境的 `SkipTest` 不算通過。指定三種 invalid／四類拒收見[資料來源](../DATA_SOURCES.md#r1-a2-selected-invalid拒收磁碟整合有限接受)。

```powershell
$selectedInvalidDependencyRoots = '<既有 backend/.deps>;<既有 backend/.validation-deps>'
$selectedInvalidRoot = 'C:/Users/YiCheng/AppData/Local/Temp/taiwan-stock-r1a2-si-<owner>-<32-hex>'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./tools/Invoke-StockDaySelectedInvalidValidation.ps1 -RunOwner '<owner>' -ValidationRoot $selectedInvalidRoot -DependencyRoots $selectedInvalidDependencyRoots
```

owner 為核定八個 ASCII 英數字元，32-hex 為核定小寫 hex；根須是 `LocalAppData/Temp` 直屬、專案外且不存在，不能沿用已用根。`-PythonPath` 可指定既有 Python，預設 bundled 3.12.14。只對子程序 Bypass；無 `KeepArtifacts`。

內容只准 DB／journal、`capture/capture.zip`／必要 staging／lock、`raw/body.bin`／`receipt.json`／lock。三個 `STOCK_*`、runner 環境、`TEMP`／`TMP` 綁定核定根，禁 bytecode。含暫態檔上限 **4 directories／5 files／2 MiB**；DB **1 MiB**、ZIP／staging **64 KiB**、body／receipt 各 **32 KiB**；DB page 4096 bytes、最多 256 pages。檢查點與退出時核配額。

路徑為 production capture／load／select→adapters 正常去重→`collect(force)`→dispose／new engine→API；其他端點用記憶體 fixture，TPEx 為明示空 batch。程序上限 **60 秒**；只停止自有程序。需一份 `R1A2_SELECTED_INVALID_METRICS`、`tests_run=1`、`skipped=0` 及 `validation_complete`。`R1A2_SELECTED_INVALID_RESULT` 分報 test／cleanup exit 與殘留；`finally` 還原環境，只清核對過的自有路徑，reparse／額外內容拒絕清理。

本入口不涵蓋完整 backend、production startup、UI、live、TPEx、正式 DB 或 migration 八案例。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L70–L86](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L70-L86)。

### R1-A2 legacy 成交量的零落盤驗證入口

從根目錄直接執行 [test_legacy_daily_volume.py](../../backend/tests/test_legacy_daily_volume.py)，不使用一般 pytest 或通用落盤 runner。格式／別名／fixture 範圍見[資料來源](../DATA_SOURCES.md#r1-a2-legacy-日行情成交量精確整數-gate有限接受)。

```powershell
$volumePreviousDeps = $env:STOCK_TEST_DEPS
try {
    $env:STOCK_TEST_DEPS = '<既有 backend/.deps>;<既有 backend/.validation-deps>'
    & 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -X utf8 ./backend/tests/test_legacy_daily_volume.py
    $volumeTestExit = $LASTEXITCODE
} finally {
    $env:STOCK_TEST_DEPS = $volumePreviousDeps
}
```

Standalone stub 提供 93 日常數與未使用的 `memory-unused/raw`，來源 import 前啟用 audit；adapter `_fetch` 使用記憶體 payload／metadata，不讀寫 raw body。新增產物／殘留上限 **0**。核程序 exit、`subcases`、`blocked_io`；blocked I/O 使程序失敗，不能只看方法數。

Parser／adapter fixture 不包括 capture、collect、SQLite、API、live、UI 或 production startup，也不替代下節磁碟驗收。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L88–L105](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L88-L105)。

### R1-A2 legacy 成交量的磁碟整合驗證入口

`tools/Invoke-LegacyDailyVolumeValidation.ps1` 直接跑 `backend/tests/test_legacy_daily_volume_file_integration.py` 的一個 compound unittest，不載一般 conftest。合法／拒收、兩次 force collect、重開與 API 範圍見[資料來源](../DATA_SOURCES.md#r1-a2-legacy-成交量磁碟整合)。

```powershell
$legacyVolumeDependencyRoots = '<既有 backend/.deps>;<既有 backend/.validation-deps>'
$legacyVolumeRoot = 'C:/Users/YiCheng/AppData/Local/Temp/taiwan-stock-r1a2-lv-<owner>-<32-hex>'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./tools/Invoke-LegacyDailyVolumeValidation.ps1 -RunOwner '<owner>' -ValidationRoot $legacyVolumeRoot -DependencyRoots $legacyVolumeDependencyRoots
```

owner／root 規則與上述 selected runner 相同；可指定 `-PythonPath`，使用既有共用依賴，不另建環境。內容只准 DB／journal，以及 `raw/twse/2026/09/05`、`raw/tpex/2026/09/05` 的六份 target body／六份 metadata；檔名為 64 位小寫 SHA 的 `.json`／`.meta.json`，ancillary 資料留記憶體。三個 `STOCK_*`、驗證環境及 `TEMP`／`TMP` 收斂核定根，禁 bytecode／ZIP／附件。

含暫態檔上限 **14 files／11 directories／3 MiB**；DB／journal 各 **1 MiB**、raw JSON **32 KiB**、metadata **8 KiB**。程序上限 **60 秒**；需一份 `R1A2_LEGACY_VOLUME_METRICS`、`tests_run=1`、`skipped=0`、`validation_complete=true`。`R1A2_LEGACY_VOLUME_RESULT` 分列 test／cleanup exit 和殘留；只清自有 exact 根，reparse／額外內容拒絕清理。無 `KeepArtifacts`。

預期 audit-denial probes 沒有實際 I/O，TestClient／asyncio 的本地 socketpair 不算外網。其他未驗範圍由資料来源契約負責。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L107–L121](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L107-L121)。

### M1-P3b 記憶體事件接線的驗收入口

此路徑零額外落盤，不套通用 runner。server exact `STOCK_TWSE_EVENTS_MEMORY_CAPTURE=1` 啟用明示 POST；普通 GET／import 不抓外網，成功原件只留 process cache。契約與真原件／API／具名桌面及窄版範圍見[個股頁 §11](../STOCK_RESEARCH_PAGE.md#11-m1-p3bselected-官方事件總覽接線)。Memory catalogue 不作真行情／DB 證據。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L123–L125](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L123-L125)。

### M2-P1 官方事件關注清單的驗收入口

GET／首次明示 POST 共用 P3b 的來源、啟用值、cache 與鎖。Consumer／API 記憶體邊界和單次真原件／API／具名操作分開接受；精確範圍見[個股頁 §12](../STOCK_RESEARCH_PAGE.md#12-m2-p1官方事件關注清單接個股總覽)。零額外落盤；原件未保存，不能離線重播。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L127–L129](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L127-L129)。

### M2-P2 搜尋與研究往返的驗收入口

沿 M2-P1 零額外落盤入口；GET／POST 可帶 `q`。全原件驗證、搜尋後截斷、matching 外壞列、同股多事件、query 邊界與 M1 返回依[個股頁 §13](../STOCK_RESEARCH_PAGE.md#13-m2-p2官方事件清單搜尋與研究往返)。最小 fixture 不代替來源或持久化驗收。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L131–L133](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L131-L133)。

### UNIT-LOTS-1 台股張數前置的記憶體驗證入口

[`tools/unit-lots-preview.cjs`](../../tools/unit-lots-preview.cjs) 預設 `--check --deps <既有 frontend/node_modules>`；借用共用依賴唯讀，不另建環境。Check 核 src 的 `noEmit:true`、`incremental:false`、`composite:false` 並拒絕writeFile；App與preview bundle採 `write:false`。涵蓋精確張／原股、單位／日期窗口、預設lot輸入、零股相容與unsafe拒用；不外推W1–W7舊suite或完整backend。

最小fixture只存memory，受8MiB上限；Git測試工具是可重建來源，不是附件。`--serve` 只供root另核具名Full App預覽／loopback fixture API，重啟即消失，非正式庫存或本次新來源；保存API／payload未改，不重跑舊storage回歸，memory不能替代未來必要磁碟重開。

具名桌面／390px顯示與可信輸入／提交只按[UI §10.3](../UI_COPY_SPEC.md#103-張零股)及[個股頁 §7.1](../STOCK_RESEARCH_PAGE.md#71-unit-lots-1-日常張數與原股稽核有限接受)範圍接受。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L135–L145](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L135-L145)。

### M1-PRICE-1 單日價量的記憶體驗證入口

後端入口[tools/tpex-price-api.py](../../tools/tpex-price-api.py)為 `python -B -X utf8 ... --check --deps <既有 backend/.deps>`，前端[tools/tpex-price-preview.cjs](../../tools/tpex-price-preview.cjs)為 `node ... --check --deps <既有 frontend/node_modules>`，共用依賴唯讀。Python在import前隔離memory config／SQLite `:memory:` 並拒絕disk寫入；Node核現行26src `noEmit:true`、`incremental:false`、`composite:false`，writeFile拒用、bundle `write:false`，不落buildinfo／bundle。

check fixture為重建selected值與synthetic邊界，非official capture。

`--serve` 與API `--live-source-opt-in` 只供root核定的loopback／actual router驗收；API需 `--policy-version`／`--policy-digest` 沿[來源 §20](../SOURCE_REGISTRY.md#20-m1-price-1tpex-兩股單日價格來源與准入)的外部pins。程式明示啟用須 `STOCK_TPEX_PRICE_MEMORY_CAPTURE=1`、`STOCK_TPEX_PRICE_POLICY_VERSION` 與 `STOCK_TPEX_PRICE_POLICY_DIGEST` 均符合固定pins；check不抓live source，import／ordinary GET零外網。首次合法POST最多1 bounded GET，同程序重複／切股與失敗cache不重取；原件／receipt只process memory，重啟釋放，不能離線重播或作磁碟保存證據。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L147–L157](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L147-L157)。

### M2-FOCUS-LOTS-1 精確張數關注的記憶體驗證入口

後端既有[tools/tpex-price-api.py](../../tools/tpex-price-api.py)增加 `python -B -X utf8 ... --focus-check --deps <既有 backend/.deps>`，只跑[test_price_focus.py](../../backend/tests/test_price_focus.py)必要7項；前端既有[tools/tpex-price-preview.cjs](../../tools/tpex-price-preview.cjs)增加 `node ... --focus-check --deps <既有 frontend/node_modules>`，只跑[priceFocus.test.ts](../../frontend/src/priceFocus.test.ts)55 helper與18 full-App SSR，現行28src noEmit。沿memory config／SQLite `:memory:`、唯讀共用依賴、Python不寫disk／pycache、Node writeFile拒用／bundle write:false／無buildinfo，不另建環境。

Checks驗精確門檻、非法字串／日期、來源拒用、真零與unavailable、固定返回、回應篡改及既有事件返回相容；check不取actual來源，重建selected樣本不代真來源或磁碟保存。

Actual 驗收以 `serve(preloaded_store=已驗Store)` 在取得原件的同一 Python 程序啟 loopback 真 router。入口須先核Store已attempted、request_count=1、無error、raw完整且validated；只patch同程序STORE，不從舊memory、disk、base64 replay或check fixture冒稱actual。Receipt明示 `preloaded_source=true`、來源count1與runner新增0；catalogue／10/02仍synthetic。普通GET／import、兩個stock POST與兩個focus POST均不增外網；首次live-source模式仍受既有external pins、明示opt-in及每程序1GET／redirect0／retry0／3MiB／30秒約束。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L159–L169](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L159-L169)。

### M2-FOCUS-DAY-MOVE-1 單日方向與完整返回的記憶體驗證入口

沿既有[tools/tpex-price-api.py](../../tools/tpex-price-api.py)的 `python -B -X utf8 ... --focus-check --deps <既有 backend/.deps>` 與[tools/tpex-price-preview.cjs](../../tools/tpex-price-preview.cjs)的 `node ... --focus-check --deps <既有 frontend/node_modules>`，只跑必要[test_price_focus.py](../../backend/tests/test_price_focus.py)10項、[priceFocus.test.ts](../../frontend/src/priceFocus.test.ts)110helper／44 full-App SSR與現行28src noEmit。仍採memory config／SQLite `:memory:`、既有依賴唯讀、noEmit／write:false／incremental:false／composite:false與guard拒寫，不另建環境；M1／UNIT／m2-v1仍適用證據沿用，不泛跑full suite或production build。

Checks涵蓋all／up／down／flat、Decimal／前端原字串O/C比較、缺失／invalid方向拒用、精確股門檻、兩股讀值／理由重算、三條件重複與safe返回、legacy omitted direction=all。Fixture只synthetic，不代actual來源。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L171–L179](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L171-L179)。

### M2-FOCUS-TURNOVER-1 精確成交金額與四條件返回的記憶體驗證入口

沿[tools/tpex-price-api.py](../../tools/tpex-price-api.py)的 `python -B -X utf8 ... --focus-check --deps <既有 backend/.deps>` 與[tools/tpex-price-preview.cjs](../../tools/tpex-price-preview.cjs)的 `node ... --focus-check --deps <既有 frontend/node_modules>`，必要Python與Node checks；舊M1／UNIT／m2-v1／v2有效證據沿用，不泛跑full old suite／production build。Memory config／SQLite `:memory:`、既有依賴唯讀、noEmit／write:false／incremental:false／composite:false及guard拒寫不變，不另建環境。

Checks驗canonical int64元／省略0／explicit invalid／duplicates、兩股amount/status/reason/raw完整gate、來源明確0與missing分清、等額／加1元、三理由重算、全部四條件samecutoff safe返回，以及legacy omitted amount／shared q／事件返回相容。Fixture僅synthetic，不代actual來源。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L181–L189](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L181-L189)。

### M2-FOCUS-DAY-RANGE-1 新日期與五條件返回的記憶體驗證入口

沿既有[tools/tpex-price-api.py](../../tools/tpex-price-api.py)的 `python -B -X utf8 ... --check/--focus-check --deps <既有backend/.deps>`、[tools/tpex-price-preview.cjs](../../tools/tpex-price-preview.cjs)的 `node ... --check/--focus-check --deps <既有frontend/node_modules>`。

最小synthetic只memory config／SQLite `:memory:`，既有依賴唯讀、noEmit／write:false／incremental:false／composite:false與guard拒寫，不另建環境。Checks涵蓋百分比原字串／千分scaled int64、精確OHL交叉比較、H=L合法0與missing、四理由／完整reads、safe五條件／尾零／legacy省略，以及兩明確immutable source tuples／store與前端日期隔離、錯pins／body／receipt拒收。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L191–L211](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L191-L211)。

### M2-FOCUS-STOCK-SCOPE-1～5 三至七股範圍的記憶體驗證入口

沿既有tools/tpex-price-api.py／tools/tpex-price-preview.cjs --check／--focus-check及唯讀共用依賴，Python -B／SQLite :memory:、Node write:false／noEmit／incremental:false／composite:false、拒寫guards保持；無新環境、helper或disk fixture。各版來源 policy tuple 見[來源 §29.1](../SOURCE_REGISTRY.md#291-1006-價格-policy-tuple-版本表)，actual API／可信操作契約見[個股頁 §34](../STOCK_RESEARCH_PAGE.md#34-m2-focus-stock-scope-5七股關注與同截止往返)。

Ordinary fixture max7 CSV rows／serialized80KiB／object512KiB；舊64KiB及五／六股cap與斷言保持。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L213–L279](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L213-L279)。

### M1-PRICE-SAVE-1 私人磁碟保存與新程序驗證入口

沿既有`tools/tpex-price-api.py`及`tools/tpex-price-preview.cjs`／唯讀共用依賴，無新環境或helper。Python `-B -X utf8`、SQLite :memory:及AST config stub保留；只有已核定private scope例外寫檔，DB不變。Source／storage dual pins及三檔schema見[來源 §30](../SOURCE_REGISTRY.md#30-m1-price-save-1私人單日保存與跨程序讀回)，actual操作見[個股頁 §35](../STOCK_RESEARCH_PAGE.md#35-m1-price-save-1私人單日保存與跨程序操作)。Windows path保護目前僅Windows。

Product runner producer用`--serve --cutoff 2026-10-06 --live-source-opt-in`及原`.5` source `--policy-version/--policy-digest`、新`--private-store-root/--private-policy-version/--private-policy-digest`；NEW reader以`--saved-source-only`取代live opt-in，同source/storage pins及root，empty Store／capture禁用。Private設定為`STOCK_TPEX_PRICE_PRIVATE_STORE=1`、`STOCK_TPEX_PRICE_PRIVATE_ROOT`、`STOCK_TPEX_PRICE_PRIVATE_POLICY_VERSION/DIGEST`；import／普通startup不fetch／hydrate。Exact pins見來源§30，product/private entry都需原task核範圍，本文不授權重跑。

Testroot `C:/Users/YiCheng/AppData/Local/taiwan-stock-research/price-save-tests-01a11367`；productroot同parent下`price-save-01a11367`。Parent起初不存在；combined≤9files／7dirs／3432448B（含parent），product≤3files／3dirs／3170304B，synthetic≤6files／256KiB、一case一份最小bundle；ordinary fixture≤7rows／serialized80KiB／object512KiB。只清本次created／owned exact scopes，parent限created且empty；不掃Temp、不留整套successful產物。

既有私人三檔的 file count cap 與 NO-RETRY 保護規則見[來源 §30.2](../SOURCE_REGISTRY.md#302-三檔原子出版與嚴格重驗)；不新增磁碟案例，也不以替代工具／路徑繞過。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L281–L299](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L281-L299)。

### M1／R1-A2 成交量精確呈現的零落盤驗證入口

`backend/tests/test_volume_exact_presentation.py` 直接 standalone 執行；Node `tools/volume-exact-preview.cjs` 分別核 units／chart／overview、product fetch／Response.json 及 UI。Python 沿 AST stub／memory SQLite，不載 conftest 或 lifespan；`_capture_evidence` 的 patch 僅支援 synthetic fixture，不重驗檔案 gate。API／股張／圖形近似與兩市場範圍見[個股頁 §14](../STOCK_RESEARCH_PAGE.md#14-m1r1-a2成交量-httpjavascript個股精確呈現)。

沒有磁碟重開、真官方／live、production startup／build 或完整 M1／PIT 證據。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L301–L305](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L301-L305)。

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

Node preview 的 `--check`、`--http-check`、`--serve` 使用共用 `--deps`；自有 **8780** 接 **8779**，bundle `write:false`。Synthetic `2026-10-03` 的兩市場使用者數量不作官方行情／正式持倉證據。

瀏覽器 capture 停止會自動建立 HAR 檔（落盤副作用）。未來使用 capture 先核 stop 落盤副作用和配額；記憶體 bundle 不保證瀏覽器工具零落盤。

本節只證 owned fixture 的有限 startup、股數保存／重開，不證正式 migration／restore、production、官方／live、完整 backend／Vite build、大數金融估值、Plan、完整 M3 或 PIT。

### M3-P3 庫存價值輸入的零落盤驗證入口

Python `test_share_quantity_exact_presentation.py --finance-only`；Node preview `--finance-check`、`--finance-http-check`，serve pair **8777／8778**。沿共同 standalone／audit／write:false；只在 memory fixture 保存 synthetic 持倉，不承襲 P2 disk fixture，不使用會落 HAR 的 capture。

UI 原字串、helper 序列化前、raw HTTP 三層各自驗收，見[UI](../UI_COPY_SPEC.md#m3-p3-庫存成本停損風險輸入可信檢核與拒收保留)。不證污染讀回、Decimal exact、磁碟保存、production、完整估值／風險或 Plan。

### M3-P4 庫存價值可信讀回的零落盤驗證入口

Python `--finance-read-only`；Node `--finance-read-check`、`--finance-read-http-check`；serve 兩端皆帶 `--finance-read-fixture`，pair **8777／8778**。固定 synthetic `2026-10-04` 十四持倉與六十個明示 fixture 日期；mutation 封鎖，不作保存／刪除驗收。

三態、missing-only 停損 fallback、metadata 相容與具名範圍見[UI](../UI_COPY_SPEC.md#m3-p4-既有庫存價值可信讀回與非法停損隔離)。不修污染或 affinity 遺失的意圖，不證磁碟、官方行情、Decimal exact 或完整風險行動。

### M3-P5 可信股數與估值／持倉判定的零落盤驗證入口

Python `--quantity-trust-only`；Node `--quantity-trust-check`、`--quantity-trust-http-check`；serve 皆帶 `--quantity-trust-fixture`，pair **8777／8778**。固定 synthetic `2026-10-04` 十六持倉、兩個 absent metadata，不作官方行情／持倉證據。

股數／held／估值三態、原 gate 優先及 scope 見[UI](../UI_COPY_SPEC.md#m3-p5-可信庫存股數與既有估值持倉判定一致)。不證行情信任、金融估值 exact、磁碟重開、所有風險／Plan 或完整 M3。

### M3-P6a 庫存本地行情與試算的零落盤驗證入口

Python `--quote-read-only`；Node `--quote-read-check`、`--quote-read-http-check`；serve 皆帶 `--quote-read-fixture`，pair **8777／8778**。固定 synthetic `2026-10-04` **20 持倉／18 行情**，兩整表全欄／typeof／note／updated_at 在 HTTP／UI 前後同 hash、read mutation 0。

本地數值隔離及試算只由[UI](../UI_COPY_SPEC.md#m3-p6a-庫存收盤數值隔離與本地試算可檢視)負責。記憶體 patch 不證 M1 正向 file gate、磁碟重開、官方／availability／PIT 或完整交易能力。

<a id="m3-p6b-actions-清單行情讀回的零落盤驗證入口"></a>

### M3-P6b Actions 清單行情讀回的零落盤驗證入口

Python `--action-read-only`；Node `--action-read-check`、`--action-read-http-check`；serve 皆帶 `--action-read-fixture`，pair **8777／8778**。固定 synthetic `2026-10-04` **24 持倉／1,382 行情**、每市場十二 symbols／六十個明示 fixture 日期；巨大值補驗的 L-FUTURE cutoff close／adj_close 為 `1e308`，翌日 5000 仍排除。兩 instances 各核自身 before／after／pre-shutdown 全欄／typeof，不能跨 instance 比 hash。

逐列 raw／unlocated／latest／scope 與具名兩尺寸清單、搜尋／state／分頁及正常導航見[UI](../UI_COPY_SPEC.md#m3-p6b-actions-清單逐列行情讀回污染隔離)。污染卡片完整詳情未由 P6b 點驗，detail SSR 不證 StockPage。未驗完整 ActionsPage、來源／日期真實性、PIT、磁碟／production 或新 Plan。

### M3-P6c 個股詳情行情讀回的零落盤驗證入口

Python `--stock-read-only`，必要局部矩陣為 `--stock-read-case router-matrix`；Node `--stock-read-check --deps <既有依賴目錄>`、`--stock-read-http-check`、`--stock-read-followup`；serve 皆帶 `--stock-read-fixture`，pair **8777／8778**。固定 synthetic `2026-10-04` **十二標的／十二持倉／784 行情**，沒有准入 M1 原件。

Raw 十七欄、nullable／候選窗口／MA／M1 latest 由[個股頁 §15](../STOCK_RESEARCH_PAGE.md#15-m3-p6c個股詳情行情讀回污染隔離)負責。Hidden table `innerText` 空白不證 MA 全空，SSR／工具 ack 不代替操作。

### M3-P6d 個股研究候選讀回的零落盤驗證入口

Python `--signal-read-only`，局部補驗 `--signal-read-case evidence-shape`；Node `--signal-read-check` 只做 noEmit，`--signal-read-http-check` 核 actual getStock／Response.json／StockPage／Panel，`--signal-read-status-check` 核 actual export guard／Panel 的非字串 status 邊界；serve 皆帶 `--signal-read-fixture`，pair **8777／8778**。

投影／JSON／窗口／canonical latest／observation 由[個股頁 §16](../STOCK_RESEARCH_PAGE.md#16-m3-p6d個股詳情研究候選讀回污染隔離)負責。

### M3-P6e 個股獨立特徵／籌碼讀回的零落盤驗證入口

Python `--independent-read-only`；Node `--independent-read-check --deps <既有依賴目錄>`、`--independent-read-http-check --api http://127.0.0.1:8777 --deps <既有依賴目錄>`；serve 皆帶 `--independent-read-fixture`，owned pair **8777／8778**。Serve／compiler 順序啟動，bundle `write:false`。

資料契約與 native／DOM.click 支持範圍見[個股頁 §17](../STOCK_RESEARCH_PAGE.md#17-m3-p6e個股特徵籌碼獨立區塊讀回隔離)。

歷史收據（M3 各批 fixture 計數、acceptance、配額、清理與實測失敗）：[基線 L311–L391](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L311-L391)。

### M1-W2～W7 法人窗口的零落盤驗證入口（歷史）

現行入口為下節 W8；W2～W7 不作現行入口，其入口、case、版本與收據見[基線 L393–L477](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L393-L477)。

### M1-W8 八截止法人窗口的零落盤驗證入口

現行 [`test_institutional_windows.py`](../../backend/tests/test_institutional_windows.py) 的 `--w8-only`為8個worker synthetic memory cases，`--w8-api-only`為5個real-router／MockTransport cases。Python3.12.14／httpx0.28.1；沿 `-B -X utf8`、AST config stub／guarded memory SQLite，不載conftest／正式startup，不建DB／fixture檔；`--serve`預設mock，另用 `--serve --live-source-opt-in`才取W8當次原件，普通GET／import零外網，共用既有環境。

[`institutional-window-preview.cjs`](../../tools/institutional-window-preview.cjs)沿共用唯讀 `--deps <既有 frontend/node_modules>`，explicit Node24.19.0／TS5.9.3／esbuild0.25.12；`--w8-only --typecheck-only` full-src noEmit／SSR。Full App `--w8-only --serve`以esbuild `write:false` memory bundle／fallback字型接actual API，非Vite／production build。不稱mock96 HTTP通過，不重跑old／full／legacy／ZIP／old live／build。舊selectors僅保留歷史class byte，不稱現版可pass，重現須查Git當時版本。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L479–L491](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L479-L491)。

### M1-CHIPS-CUTOFF-1006-1 同截止法人窗口的零落盤驗證入口

沿共用Python3.12.14／httpx0.28.1、`-B -X utf8`、既有唯讀dependencies及guarded SQLite `:memory:`；不載conftest／正式config mkdir／startup，不建DB／raw／fixture檔／pycache／helper或附件。Exact來源／pins及執行上限由[來源 §31](../SOURCE_REGISTRY.md#31-m1-chips-cutoff-1006-1同1006法人窗口與完整有界日曆)管理，具名操作與未驗由[個股頁 §36](../STOCK_RESEARCH_PAGE.md#36-m1-chips-cutoff-1006-1同截止法人窗口與完整日曆)管理；本文不另授權金融重跑。

新[`test_institutional_windows_1006.py`](../../backend/tests/test_institutional_windows_1006.py)的`--worker-only`／`--worker-case <具名case>`及`--api-only`只使用最小synthetic memory，`--serve`預設mock。Root另核`--serve --live-source-opt-in --policy-version <新version> --policy-digest <新digest>`才開NEW empty新／W8 Store，finance seed0，不preload／samecapture replay；API／preview owned pair8799／8800。新啟用變數為`STOCK_TPEX_INSTITUTIONAL_1006_MEMORY_CAPTURE=1`及`STOCK_TPEX_INSTITUTIONAL_1006_POLICY_VERSION/DIGEST`，import／普通startup／GET不fetch。

沿[`institutional-window-preview.cjs`](../../tools/institutional-window-preview.cjs)及共用唯讀`--deps <既有frontend/node_modules>`；explicit Node24.19.0／TypeScript5.9.3／esbuild0.25.12，`--chips-1006-only --typecheck-only`核new SSR／full-src noEmit；`--serve`完整App esbuild `write:false` memory bundle，非production build。原W8 StockOverview受影響SSR另局部核對，不把old selector歷史整套升格為現版pass。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L493–L507](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L493-L507)。

### M1-SAVED-PRICE-FOCUS-1006-1 保存來源關注的零落盤驗證入口

沿既有 `tools/tpex-price-api.py`／`tools/tpex-price-preview.cjs`及唯讀共用dependencies；Python `-B -X utf8`、guarded SQLite `:memory:`，Node `write:false`／full-src noEmit／incremental:false／composite:false。不載正式DB、一般startup mkdir或conftest，不建新環境／helper／backup／fixture檔。來源用途與精確pins由[來源 §32](../SOURCE_REGISTRY.md#32-m1-saved-price-focus-1006-1保存來源的七股關注准入)管理，actual操作見[個股頁 §37](../STOCK_RESEARCH_PAGE.md#37-m1-saved-price-focus-1006-1保存來源關注與同截止往返)；本節不另授權重跑。

NEW product reader用 `--serve --cutoff 2026-10-06 --saved-source-only`、原capture `--policy-version/--policy-digest`、原storage `--private-store-root/--private-policy-version/--private-policy-digest`，另需新 `--saved-focus-policy-version/--saved-focus-policy-digest`。只有原task核定existing private root／finite讀取quota後可啟用；consumer opt-in不允live-source opt-in、preloaded Store、POST、old saved入口繞過或memory／DB hydration。來源§32的10s cooperative／32MiB graph estimate、檔案bounds與兩reader共用96 quota不作OS deadline／RSS保證。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L509–L523](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L509-L523)。

### M1-SAVED-PRICE-CHIPS-INTEGRATION-1006-1 共同入口的零落盤驗證入口

只沿既有 `tools/tpex-price-api.py`／`tools/tpex-price-preview.cjs`、共用dependencies及guarded SQLite `:memory:`；Python3.12.14 `-B -X utf8`、pinned Node24.19.0、TypeScript5.9.3／esbuild0.25.12。Shell node20.19.4另列，不代pinned runtime；不install、建helper／fixture檔、startup mkdir、正式DB或複製環境。來源／quota由[§33](../SOURCE_REGISTRY.md#33-m1-saved-price-chips-integration-1006-1保存行情與法人窗口共同入口)管理，本節不另授權重跑。

API／preview皆需 `--serve --saved-source-only --saved-price-chips-opt-in`；API另需 `--cutoff 2026-10-06 --private-root` 原task literal root，preview `--api-port 8799`／memory bundle。外部五組pins：capture `--policy-version/--policy-digest`、storage `--private-policy-version/--private-policy-digest`、saved consumer `--saved-focus-policy-version/--saved-focus-policy-digest`、chips `--chips-policy-version/--chips-policy-digest`、joint `--joint-policy-version/--joint-policy-digest`。Joint不允 `--live-source-opt-in`；僅此preview compile `VITE_SAVED_PRICE_CHIPS_INTEGRATION='m1-v1'`，write:false／noEmit／incremental:false／composite:false。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L525–L536](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L525-L536)。

### M1-SAVED-PRICE-CHIPS-FOCUS-1006-1 八條件入口的零落盤驗證入口

沿前節共用pinned dependencies、API/preview及guarded SQLite `:memory:`，不install／建helper或fixture檔／startup mkdir／正式DB／另建環境。新 `--saved-price-chips-focus-opt-in` 與 `VITE_SAVED_PRICE_CHIPS_FOCUS='m1-v1'` 獨立；本preview old integration flag OFF。New pair為 `--joint-focus-policy-version m1-saved-price-chips-focus-tpex-2026-10-06.1 --joint-focus-policy-digest sha256:1b48fc6bb23b021f3d289c797b8d077af4576f492cbc08953d0515ef0da89416`；另核原capture/storage/saved-focus/chips/joint五組pins、原task literal private root及finite quota，原flags/公式不改。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L538–L548](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L538-L548)。

### M2-FOCUS-STOCK-SCOPE-6 八股新來源日的零落盤驗證入口

沿既有 `tools/tpex-price-api.py`／`tools/tpex-price-preview.cjs`、共用pinned dependencies、Python `-B -X utf8`／guarded SQLite `:memory:`、Node `write:false/noEmit/incremental:false/composite:false`；未install／建helper／disk fixture／新環境／正式DB。新policy／worker／projection／consumer pins及有限FIRST範圍由[來源 §35](../SOURCE_REGISTRY.md#35-m2-focus-stock-scope-6八股與新來源日准入)管理，exact啟動命令及所有raw exits留ROOT原task，不另授權重跑。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L549–L561](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L549-L561)。

### M1-SAVED-PRICE-CHIPS-FOCUS-CALENDAR-1006-2 全月日曆八條件的零落盤驗證入口

沿共用pinned Python3.12.14 `-B -X utf8`、Node24.19／TypeScript5.9.3／esbuild0.25.12、既有API/preview及guarded SQLite `:memory:`；不install/helper/fixture檔/DB複製/正式DB。新API／preview `--serve --saved-source-only --saved-price-chips-focus-calendar-opt-in`，與old joint/focus flags互斥；API另需 `--cutoff 2026-10-06 --private-root` 原task literal root，preview `--api-port 8799`／memory bundle。新compile `VITE_SAVED_PRICE_CHIPS_FOCUS_CALENDAR='m1-v2'`，old flags OFF。

外部六組pairs仍為capture `--policy-version/--policy-digest`、storage `--private-policy-version/--private-policy-digest`、saved-focus `--saved-focus-policy-version/--saved-focus-policy-digest`、new chips `--chips-policy-version/--chips-policy-digest`、new entry `--joint-policy-version/--joint-policy-digest`、new focus `--joint-focus-policy-version/--joint-focus-policy-digest`；前三不改、新三version／canonical bytes／digest由[來源 §36](../SOURCE_REGISTRY.md#36-m1-saved-price-chips-focus-calendar-1006-2全月日曆與八條件來源准入)單一管理。Exact啟動／check命令與原exit留ROOT task，本節不另授權重跑。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L563–L573](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L563-L573)。

### M1-SAVED-PRICE-CHIPS-FOCUS-STOCK-SCOPE-7-1006-1 七股八條件的零落盤驗證入口

沿共用pinned Python3.12.14 `-B -X utf8`／FastAPI0.141.1／SQLAlchemy2.0.52／httpx0.28.1及Node24.19／TypeScript5.9.3／esbuild0.25.12；guarded SQLite `:memory:`，不install/helper/fixture檔/DB複製/正式DB。New API/preview `--serve --saved-source-only --saved-price-chips-focus-stock-scope-7-opt-in`，與old/calendar flags互斥；API另需 `--cutoff 2026-10-06 --private-store-root` 原task exactroot，preview `--api-port 8799`／memory bundle，compile `VITE_SAVED_PRICE_CHIPS_FOCUS_STOCK_SCOPE_7='m1-v1'`、old flags OFF。

外部capture/storage/saved-focus/chips/joint/joint-focus六組version/digest args沿前節；前三price pins不變，新三canonical version/bytes/SHA由[來源 §37](../SOURCE_REGISTRY.md#37-m1-saved-price-chips-focus-stock-scope-7-1006-1七股共同來源准入)管理。ROOT先核用途與pins才implementation/GET/privateIO；原啟動/check commands／版本／exit及各failed invocation留原task，本節不授權重跑或來源配額。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L576–L588](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L576-L588)。

### M1-CHIPS-STOCK-SCOPE-7-DAILY-NET-TREND-20-1006-1 七股每日淨超的零落盤驗證入口

chips-only 入口為 `tools/tpex-chips-series-api.py`、`tools/tpex-chips-series-preview.cjs`；不使用old saved/joint producer、private root或price fetch。沿pinned Python3.12.14 `-B -X utf8`、FastAPI0.141.1／httpx0.28.1及Node24.19／TypeScript5.9.3／esbuild0.25.12，只讀既有backend/.deps與frontend/node_modules，不install、建helper／fixture檔、DB或整套來源副本。新policy version／外部digest由[來源 §38](../SOURCE_REGISTRY.md#38-m1-chips-stock-scope-7-daily-net-trend-20-1006-1七股每日法人淨超與窗口累計)單一管理。

下列為已驗入口形狀，原exact commands／版本／raw exit留原task；文件不授權再FIRST／重啟或更新配額。API只在 `--serve --chips-series-stock-scope-7-opt-in` 明示啟用；新preview flag與old flags獨立互斥，GET/capture僅as_of，三UI RAW不可當額外API keys。

```powershell
$seriesNode = 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -X utf8 tools/tpex-chips-series-api.py --check
& $seriesNode tools/tpex-chips-series-preview.cjs --check
& $seriesNode tools/tpex-chips-series-preview.cjs --check --check-ui-only
& $seriesNode tools/tpex-chips-series-preview.cjs --check --check-startup-only
# serve 須沿原 task 准入與外部 pins
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -X utf8 tools/tpex-chips-series-api.py --serve --chips-series-stock-scope-7-opt-in --port 8801 --policy-version m1-chips-daily-net-series-stock-scope-7-tpex-2026-10-06.1 --policy-digest sha256:143aabb4cd2d86110d5564793ce77b0fb6c60b3e603f23c1e188875934a48a31
& $seriesNode tools/tpex-chips-series-preview.cjs --serve --chips-series-stock-scope-7-opt-in --api-port 8801 --port 8802 --policy-version m1-chips-daily-net-series-stock-scope-7-tpex-2026-10-06.1 --policy-digest sha256:143aabb4cd2d86110d5564793ce77b0fb6c60b3e603f23c1e188875934a48a31
```

API／preview 預設埠 8799／8800，preview `--api-port` 預設 8799；bundle 於啟動時建立，換 UI 埠不換 API，commit 不更新既有 bundle。

Fixture／數值／零窗口仍synthetic，不代actual來源／操作。政策cap中的retained8748386B為estimate，非RSS／construction peak；headers／deadline的postcheck／cooperative限制由來源§38管理。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L590–L613](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L590-L613)。

## 歷史驗證

完整原文見 `git show 5ae84d2:docs/development-baseline/README.md`，歸檔前全文見 `git show f431b9885cd3332ddd328309d0041a15c55b8610:docs/development-baseline/README.md`；其他歷史入口見[文件索引](../README.md#歷史查閱)。已刪 Temp 附件不作接手依賴；未清、審核拒絕及占用資源仍依[治理 #1](https://github.com/YiCheng0608/stock-lab/issues/1)處理。

### M2-OFFICIAL-EVENT-DATE-RANGE-20261008-1 官方事件區間的零落盤驗證入口

Backend入口為[test_official_events.py](../../backend/tests/test_official_events.py)／[test_official_event_focus.py](../../backend/tests/test_official_event_focus.py)。Node20.19.4／TypeScript5.9.3／esbuild0.25.12，[tpex-price-preview.cjs](../../tools/tpex-price-preview.cjs) `--event-range-check` 為獨立零網路模式。既有price query四條件共享URL相容與事件不滲價量API屬必要檢查，不擴舊price來源驗收。

Checks使用可重建記憶體fixture與既有依賴，不install／建helper、DB、cache、build／raw／附件；noEmit與memory-only consumer保持。範圍包含日期grammar／inclusive／單側／invalid先於source與catalogue、完整feed先驗後range／q、計數／cap／返回、首次失敗跨focus／selected shared seal及retry0。Synthetic邊界不代真原件、原三instrument catalogue只routing。原exact命令／版本／所有raw exit與工具參數、quoting、offscreen／未送達操作收據留task；本段不授權重跑金融來源或producer。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L619–L627](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L619-L627)。

### M2-OFFICIAL-EVENT-KIND-20261008-1/B1 官方事件類型的零落盤驗證入口

Python3.12.14／pytest8.4.2：[test_official_events.py](../../backend/tests/test_official_events.py)及[test_official_event_focus.py](../../backend/tests/test_official_event_focus.py)。原task UTF8 stdin以Python `-B -X utf8`、PYTHONDONTWRITEBYTECODE=1／PYTEST_DISABLE_PLUGIN_AUTOLOAD=1，sys.path先放本根backend／backend/tests及main backend/.deps；AST僅抽install_zero_disk_guard，以os／sys／Path globals編譯並先執行，再import pytest。pytest參數 `--noconftest -q -s -p no:cacheprovider -p no:logging` 加上述兩檔；只memory SQLite，禁止写入／mutation／subprocess／外網，完整inline命令留原task，不建helper或環境。

Node20.19.4／TypeScript5.9.3／esbuild0.25.12，[tpex-price-preview.cjs](../../tools/tpex-price-preview.cjs)独立零網路check：

```powershell
& 'C:/Program Files/nodejs/node.exe' 'tools/tpex-price-preview.cjs' --deps '<既有 frontend/node_modules>' --event-kind-check
```

RAM esbuild／既有Git fixture，不寫DB／cache／build／raw／Temp。

真來源及actual操作見[來源](../SOURCE_REGISTRY.md) §40／[個股頁](../STOCK_RESEARCH_PAGE.md) §45；synthetic4不代ordinary／fullmarket／price／PIT。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L629–L641](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L629-L641)。

## M1-TWSE-ISSUER-EVENT-PROFILE-20261008-1：公司與事件的零落盤驗證入口

scope／provenance／date／Code與Namejoin／duplicate與conflict拒收／pins／single attempt FIRST failure SPENT／unavailable／failure clear用RAM fixtures驗，不代真來源或可信UI。實際1095×33 issuer及58×12event原件／全部映射由[來源](../SOURCE_REGISTRY.md) §41管理；可信desktop1365×900／390×844三股與五條件往返／502清值由[個股頁](../STOCK_RESEARCH_PAGE.md) §46管理。

### 記憶體測試與既有入口

後端[Test module](../../backend/tests/test_twse_issuer_profile.py)要求先安裝[test_official_events.py](../../backend/tests/test_official_events.py)的 `install_zero_disk_guard`，再import pytest／新module；原task以Python `-B -X utf8`／PYTHONDONTWRITEBYTECODE=1／PYTEST_DISABLE_PLUGIN_AUTOLOAD=1、main repo既有backend/.deps及本根import paths、AST抽取guard方式執行。pytest用 `--noconftest -q -s -p no:cacheprovider -p no:logging`，只RAM fixture／SQLite，不import app.main／conftest或寫DB；完整inline命令、版本、原exit與範圍留原task，不另建helper／環境。

前端新mode沿[tpex-price-preview.cjs](../../tools/tpex-price-preview.cjs)的既有RAM編譯／guard入口；必要已接受命令：

```powershell
& 'C:/Program Files/nodejs/node.exe' 'tools/tpex-price-preview.cjs' --deps '<既有 frontend/node_modules>' --issuer-event-check
```

42src noEmit／80targetchecks只synthetic tuple／SSR／response／routing／proxy邊界，非金融／browser／磁碟保存／production build／普通股history證據。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L643–L665](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L643-L665)。

## M1-TWSE-ISSUER-INDUSTRY-TRACE-20261008-1/B1：兩碼追溯的零落盤驗證入口

新[Test module](../../backend/tests/test_twse_issuer_industry.py)覆蓋two-code exact lookup、其他市場／空白／numeric／special／unknown拒用、external pins／宣告hash／date precision／source URLs、duplicate／conflict、同cutoff與完整dualSHA／ordinal、名稱與raw mappings。RAM fixtures是邊界計算證據，不代真公司／官方文件／可信UI；authority分別見[來源 §42](../SOURCE_REGISTRY.md)、[產業 §10](../INDUSTRY_CLASSIFICATION.md)、[個股頁 §47](../STOCK_RESEARCH_PAGE.md)。

沿[test_official_events.py](../../backend/tests/test_official_events.py)既有zero-disk guard，先安裝audit guard再import pytest／新module；用既有backend/.deps／本根路徑、Python `-B -X utf8`／PYTHONDONTWRITEBYTECODE=1／PYTEST_DISABLE_PLUGIN_AUTOLOAD=1及pytest noconftest、no cacheprovider／logging。只RAM fixtures／SQLite，不import app.main／conftest、建DB或寫Temp；實際命令／版本／exit與限制留ROOT原task，不另建helper／環境／附件。

前端沿既有[RAM preview入口](../../tools/tpex-price-preview.cjs)的新bounded mode：

```powershell
& 'C:/Program Files/nodejs/node.exe' 'tools/tpex-price-preview.cjs' --deps '<既有 frontend/node_modules>' --issuer-industry-check
```

45src noEmit＋71target checks是synthetic tuple／validator／SSR／query error與routing／proxy guard證據，不是financial truth／native UI／production build／磁碟保存。Serve只proxy ROOT-owned API，`--issuer-industry` 必須另有exact industry registry／consumer四external pins及已准入issuer／event pins；舊defaults／其他opt-in不自動升格。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L667–L689](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L667-L689)。

## M1-CHIPS-STOCK-SCOPE-7-GROSS-TRADE-20-1006-1/B1：gross零落盤驗證入口

來源與操作邊界見[來源 §43](../SOURCE_REGISTRY.md)／[個股頁 §48](../STOCK_RESEARCH_PAGE.md)。

三命令不附`--deps`／policy-version／digest參數；runner預設共用main依賴，grossflag選獨立硬coded policy version／外部digest（SOURCE43），不提升oldpins：

```powershell
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -X utf8 tools/tpex-chips-series-api.py --check --chips-gross-stock-scope-7-opt-in
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' tools/tpex-chips-series-preview.cjs --check --chips-gross-stock-scope-7-opt-in
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' tools/tpex-chips-series-preview.cjs --check --check-ui-only --chips-gross-stock-scope-7-opt-in
```

Fixtures／syntheticzero與SSR不代金融truth／nativeUI；checks sourceGET／network／disk-private-DB寫入0、各rejectionguard0，未跑productionbuild／fullsuite／磁碟保存。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L691–L707](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L691-L707)。

## M1-CHIPS-STOCK-SCOPE-7-DIRECTION-SEGMENTS-20-1006-20261008-1/B1：方向區段零落盤入口

來源及操作見[來源 §44](../SOURCE_REGISTRY.md)／[個股頁 §49](../STOCK_RESEARCH_PAGE.md)。新opt-in使用獨立ROOT外部pins，不升olddefaults。

本worktree根的三個check入口：

```powershell
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -X utf8 tools/tpex-chips-series-api.py --check --chips-direction-stock-scope-7-opt-in
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' tools/tpex-chips-series-preview.cjs --check --chips-direction-stock-scope-7-opt-in
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' tools/tpex-chips-series-preview.cjs --check --check-ui-only --chips-direction-stock-scope-7-opt-in
```

SSRwarnings、fixture／27signcases邊界與actualUI分報，不代金融truth；未跑productionbuild／fullsuite／磁碟保存。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L708–L724](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L708-L724)。

## M1-CHIPS-STOCK-SCOPE-7-ADJACENT-WINDOWS-5-1006-20261008-1/B1：相鄰窗口零落盤驗證入口

來源／pins與操作見[來源 §45](../SOURCE_REGISTRY.md)／[個股頁 §50](../STOCK_RESEARCH_PAGE.md)。本根opt-in使用獨立ROOT外部canonical9284B及digest，不提升olddefaults；共用main依賴／pinned Node24.19.0，不另建環境。

本worktree根的必要check入口：

```powershell
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -X utf8 tools/tpex-chips-series-api.py --check --chips-adjacent-stock-scope-7-opt-in
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' tools/tpex-chips-series-preview.cjs --check --chips-adjacent-stock-scope-7-opt-in
```

純fixture／overflow／zero／lifecycle及SSR不證financial truth／trusted nativeUI；未跑productionbuild／fullsuite／DB／磁碟保存。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L726–L747](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L726-L747)。

## M1-CHIPS-STOCK-SCOPE-7-DEALER-COMPONENTS-5-1006-20261008-1/B1：三組對帳零落盤驗證入口

新source／canonical9245B與外部digest／774B署名見[來源 §46](../SOURCE_REGISTRY.md)，actual操作見[個股頁 §51](../STOCK_RESEARCH_PAGE.md)。共用main現成backend/.deps及frontend/node_modules，不另建環境；pinned Node24.19.0／TypeScript5.9.3／esbuild0.25.12。

本worktree根的必要check入口（memory-only、不得藉此重新啟動已釋放financial producer）：

```powershell
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -X utf8 tools/tpex-chips-series-api.py --check --chips-dealer-components-stock-scope-7-opt-in
& 'C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' tools/tpex-chips-series-preview.cjs --check --chips-dealer-components-stock-scope-7-opt-in
```

Overflow／zero／missing／components／lifecycle fixture及SSR不代financial truth或trusted nativeUI；未跑productionbuild／fullsuite／DB／磁碟保存。

歷史收據（測試計數、fixture 尺寸、exit、PID、清理與實測失敗）：[基線 L749–L772](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/development-baseline/README.md#L749-L772)。
