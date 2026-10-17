# 開發與驗證入口

本文管理可重建入口、副作用與驗收方式；資料、產物配額、保留及清理依 [AGENTS](../../AGENTS.md#工程原則)。接手與未清資源記原 GitHub Issue；命令／版本／exit／計數／hash／退修／提交收據留原 Issue／Git，入口見[遷移說明](../TASK_COORDINATION.md)。下列 task／ROOT／freeze 收據只證歷史，不授權現行派工，也不證目前來源通過。

下列單次測試與具名來源的 GET／RAM／落盤上限只約束其授權範圍，不是全專案只能開一張任務的限制；跨任務仍須核共用資源及各自授權，不因另開 worktree 擴大配額。

## 版本與資料

先以 `git status --short`、`git diff`、`git log -1` 核對來源。`.gitattributes` 固定 LF，replay 綁定的 source bytes 不可因換行改變。Git 保存測試與 fixture 建構方式，不保存本機 DB、raw、依賴或生成產物。磁碟驗收用專案外最小隔離檔案，仍須滿足各入口的 snapshot 契約。

本文的 `python`／`node` 指實際安裝的直譯器。Python 須為 3.12.x，Windows 下若 PATH 的 `python` 是 Store stub，請改用實際安裝路徑。`--check`／preview 入口以 pinned Node 24.19.0（TypeScript 5.9.3／esbuild 0.25.12）驗收，CI frontend／backend job 的 Node 版本以 [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) 的 setup-node 為準；舊 20.19.4 只是歷史驗收當時版本。各入口的 `--deps` 指既有唯讀依賴（本機 `backend/.deps`／`frontend/node_modules`），省略時 runner 取 repo 內 `backend/.deps`／`frontend/node_modules`（任務 worktree 通常沒有）、找不到即明確失敗，或直接要求 `--deps`，因此一律明示。

測試失敗先依[失敗處理](../GITHUB_WORKFLOW.md#失敗處理)分類；工具／環境失敗修正後重跑同一案例，不判產品結果，也不重取外部資料。

使用 API／preview 前，先核實載入版本與資源隔離；commit 不更新舊程序，補版本證據仍須遵守原件生命週期、quota 與 NO-RETRY。

## 測試資料庫分層

| 層 | 用途 | 寫權與共享 | owner |
| --- | --- | --- | --- |
| 日常 DB | 使用者研究與收集（[OPERATIONS](../OPERATIONS.md#1-工作目錄環境與啟停)預設 `.local/data/stock.db`） | 不作測試寫入、不放測試資料 | 使用者 |
| 固定版本唯讀樣本庫 | 核准的小型真實樣本；工程與 QA 讀同一版本 | 只讀開啟（SQLite `mode=ro`＋`PRAGMA query_only=ON`）；更新即產生新版本 | 全局核准、資料線 owner 維護 |
| 可重設隔離測試庫 | 寫入、migration、保存／跨程序測試 | 每次執行獨立路徑，由樣本庫或 fixture 建立；不共享可變狀態，不逐角色複製整份 DB | 該任務工程／QA |

- 三層都用產品 schema（`init-db` 建立），不另設假資料表或另一套查詢路徑。日常 DB 與隔離測試庫以三個 `STOCK_*` 指向該層的絕對路徑並於執行前讀回；樣本庫只以 `select` 回傳的唯讀 URI 開啟（URI 只帶 `mode=ro`，使用端另設 `PRAGMA query_only=ON`）；樣本庫與隔離測試庫放專案外、不入 Git、不複製私人 DB。產品 app 以讀寫方式開啟 `STOCK_DB_PATH`，不得把 app 或寫入測試直接指向樣本庫，須先複製到隔離測試庫。
- 樣本中繼資料隨樣本庫保存：來源用途權利（依 [SOURCE_REGISTRY](../SOURCE_REGISTRY.md#1-registry-與-policy-契約)）、資料日期、取得時間、schema 版本、抽樣規則、樣本版本、檔案 hash。真實樣本與人工邊界案例分開標示；必要原始回應與正規化欄位可追溯；未知發布時間／PIT 標未知，不補造。
- 按最小完整案例取樣：價格顯示少量日、MA60 至少 60 個交易日、公司行動含事件前後。日常回歸、整合驗收、容量／效能案例分開，樣本庫不隨日常 DB 成長。
- 樣本庫的位置與大小限額在核准時登記，各單引用該登記，變更才重核；隔離測試庫在執行結束重設或清理，失敗回報路徑／大小／原因，不每輪重造 manifest。
- 本地重驗讀樣本庫不觸發外部 GET；人工 fixture 另驗錯誤邊界。沒有適用真實樣本時，該 AC 標未驗。

### 共用入口 `tools.test_db`

[tools/test_db](../../tools/test_db/__init__.py) 實作樣本庫與隔離測試庫（工具程序只用標準函式庫）。契約測試見 [guards](../../backend/tests/test_test_db_guards.py)、[entry](../../backend/tests/test_test_db_entry.py)，人工 fixture 範例見 [sample_basic.json](../../backend/tests/fixtures/test_db/sample_basic.json)（虛構資料，非市場資料）。從專案根目錄執行：

```powershell
python -B -X utf8 -m tools.test_db --root <專案外絕對路徑> [--max-bytes N] [--deps <依賴路徑>] <命令> [參數]
```

| 命令 | 用途 |
| --- | --- |
| `build-sample --version V --fixture F` | 以產品 `worker.cli init-db` 建 schema、載入人工 fixture，發布為不可變樣本版本；`--kind`（`manual_fixture` 預設或 `real_sample`）、`--meta`（metadata JSON 檔，內容須是 JSON 物件，否則 `metadata_invalid`）、`--skip-product-check` |
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

- 參數：`--root`（或 `STOCK_TESTDB_ROOT`）必填，須為專案外絕對路徑，不得在產品 checkout、`.local/data` 或繼承來的 `STOCK_*` 位置內，建目錄前即拒絕。在 Windows 上 root 另有長度限制：以解析後的真實路徑、UTF-16 單位（`MAX_PATH` 的算法）計，至多 136 字元；工具自建的最長路徑比 root 多 123 字元（`runs/<run id，最長 64>/tmp/<子程序暫存，保留 48>`，其餘後綴較短，常數見 `tools/test_db/entry.py` 的 `ROOT_PATH_SUFFIXES`），須落在 259（`MAX_PATH` 260 含結尾 NUL）內，超過即在建任何目錄前回 `path_too_long`（`details` 帶 `root_length`、`reserved_length`、`limit`、`max_root_length`）。`subst` 與 junction 不能縮短（仍以解析後的路徑計）；保留量只涵蓋工具自建的路徑與子程序暫存的合理保留，`exec` 的命令在 run 內自建的路徑（如 `data/raw/` 下的檔名）不在內。`--max-bytes` 預設 50,000,000（十進位 50 MB）。`--python` 指定產品子程序的直譯器（預設本程序的），`--deps`（可重複）或 `STOCK_TEST_DEPS`（以路徑分隔字元串接）指定子程序可 import 的既有依賴路徑；`--timeout` 預設 180 秒，只限產品子程序。
- 輸出：每個命令印一個 JSON，exit 0 或 1。成功 `{"ok":true,"result":…}`；失敗 `{"ok":false,"error":{code,reason,path,size_bytes,details}}`，`path` 為絕對路徑，涉及檔案或目錄樹時帶 `size_bytes`。argparse 參數錯誤 exit 2 且不建檔。`exec` 的 exit 為被執行命令的 exit，成功時工具 JSON（含執行前 `STOCK_*` 讀回）寫 stderr，stdout 留給該命令。
- 錯誤碼：守門 `forbidden_target`／`stock_env_invalid`／`reparse_point`／`invalid_argument`／`path_too_long`；樣本 `version_missing`／`version_mismatch`／`version_exists`／`hash_mismatch`／`schema_mismatch`／`sample_corrupt`／`metadata_invalid`／`fixture_invalid`；run `run_exists`／`run_not_found`／`not_a_run_dir`／`not_found`；資源 `quota_exceeded`／`cleanup_failed`／`in_use`／`io_error`；產品子程序 `product_failed`／`product_timeout`。
- 版面：`<root>/samples/<version>/{sample.db,metadata.json}`（OS 唯讀屬性；目錄恰此兩檔，否則 `sample_corrupt`）、`<root>/runs/<run-id>/{.testdb-run.json,data/stock.db,data/raw/,tmp/}`、`<root>/tmp/`（schema 檢查暫存）。版本名與 run id 須符合 `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`；已發布版本不可覆蓋（`version_exists`）。需 run id 的命令只接受含 `.testdb-run.json` 且與 run id 相符的目錄，否則 `not_a_run_dir`，不碰無標記目錄。
- metadata：`metadata.json` 欄位為 `metadata_schema`、`sample_version`、`kind`、`source_rights`、`data_dates`、`acquired_at`、`publication_time`、`schema_version`、`sampling_rule`、`sha256`、`size_bytes`、`created_at`、`row_counts`、`provenance`，缺欄即 `metadata_invalid`。`publication_time` 未陳述時為 `unknown`，不推算。
- fixture：UTF-8 JSON `{"tables":[{"table":名稱,"rows":[{欄:值}]}],"data_dates":…}`，`data_dates` 選填（缺則 `unknown`）。載入為單一交易並啟用外鍵：未知表／欄、`sqlite_*`、違反約束或外鍵即 `fixture_invalid` 並整份回滾；`provenance` 記 fixture 檔名與 sha256。
- `real_sample`：須以 `--meta` 自行陳述 `source_rights`、`data_dates`、`acquired_at`、`sampling_rule`，發布前檢查（`build-sample` 在建任何 run 之前，`freeze` 在建立 `samples/` 之前，見「配額邊界」條的發布拒絕順序）；缺漏或未陳述任何內容的值回 `metadata_invalid`，不留版本。`--meta` 檔的內容不是 JSON 物件（含 `null`、`0`、`""`、`[]`、`false`）或讀不了，同樣回 `metadata_invalid`（`path` 指該檔）；未給 `--meta` 才是沒有 metadata。字串先 NFKC 正規化、不分大小寫並忽略空白與標點，整個值等於 `unknown`、`not-applicable`／`n/a`／`na`／`not available`、`tbd`／`tba`／`todo`、`none`／`null`／`nil`／`undefined`／`nan`、`無`／`未知`／`不適用`／`待定`／`待補`／`未定`，或只含空白與標點，即視為未陳述；list／dict 為空，或任一層巢狀值未陳述（如 `data_dates` 的 `first`／`last` 任一端的值未陳述）亦同；缺少的 key 不擋，只有 `first`、沒有 `last` 會接受。刻意不擋：只認上列占位詞，不在清單內的近義詞或同形異體字不擋；只比對整個值，以占位詞開頭但帶說明的字串（如 `not-applicable: …`、`None of the rows …`）會接受；數字與布林不判斷；`publication_time` 與 `provenance` 不檢查（未陳述時為 `unknown`）；只在發布時檢查，`verify`／`select` 不重驗 metadata 陳述。工具只擋未陳述，不判斷陳述是否屬實或符合上述來源權利規則。`manual_fixture` 的預設 metadata（如 `not-applicable: …`）不受此閘門影響。
- 隔離：工具程序不 import 產品 `app`（`app.config` import 時即建目錄並綁定路徑）；產品程式（`init-db`、schema 檢查、`exec` 命令）只在子程序執行，環境重建為：丟棄所有繼承的 `STOCK_*`（含 live-source opt-in），只設該 run 的三個 `STOCK_*`，`TEMP`／`TMP`／`TMPDIR` 指向 run 的 `tmp/`。啟動前讀回並檢查三者皆設、為無 `..` 的絕對路徑、全在該 run 目錄內；拒絕（`forbidden_target`／`stock_env_invalid`，不啟動）產品 checkout（含 repo `data/`、`.local`）、`.local/data`、繼承來的 `STOCK_*` 位置與樣本庫內的目標。工具根為連結或 reparse point 即拒絕；根內含連結時 `usage` 與配額記帳 fail-closed（`reparse_point`，指出路徑）。
- schema 檢查邊界：`verify`、`build-sample`、`freeze` 預設做產品檢查，`select`、`isolate`、`exec` 預設不做，需 `--check-product`；檔案集合、版本、hash／大小、Alembic 標記、metadata 一律檢查。產品檢查為產品啟動用的 `check_database_readiness`（必要表／欄、主鍵、唯一鍵、外鍵）加樣本 `schema_version` 等於 Alembic head，不比對完整 DDL（多出的欄位不失敗），也不稽核資料。樣本的 OS 唯讀屬性、hash 與 metadata 可被有權限者一併改寫，防竄改須以 `--expect-sha256`（`verify`／`select`／`isolate`）對核准 hash。
- 配額邊界：`--max-bytes` 約束整個 `--root`（含非工具建立的檔案），只在工具管理的檢查點核算——`isolate`（有樣本時複製前先預估）、`reset`、`freeze`、`build-sample` 的複製、發布與建庫前後。超額回 `quota_exceeded`（`size_bytes` 為預計總量，`details` 含 current／incoming／limit），`isolate`、`freeze`、`build-sample` 不留該次新建的 run 或發布暫存；`freeze` 的預估在建立 `samples/` 之前（順序見本條末的發布拒絕順序）。`load-fixture`、`init-db` 子程序與 `exec` 命令的寫入不受即時約束，事後核算才發現；因此是檢查點限額，不是即時硬上限。並行 `isolate` 的事後核算會看到彼此的複本，可能比序列多回 `quota_exceeded`，仍是單一 JSON。發布拒絕順序：CLI 先讀 `--meta` 檔（不是 JSON 物件或讀不了即 `metadata_invalid`）。`freeze` 依序判斷，先成立者先回報：① 版本名不合 `invalid_argument`；② `kind` 不合 `invalid_argument`；③ 版本已存在 `version_exists`；④ run 不合（run id 不合 `invalid_argument`、不存在 `run_not_found`、無標記 `not_a_run_dir`、連結 `reparse_point`）；⑤ run 無資料庫 `not_found`；⑥ 有 `stock.db-*` 殘留 `sample_corrupt`；⑦ Alembic 標記不是恰一個 `schema_mismatch`；⑧ metadata 不合（`real_sample` 未陳述、`meta` 不是物件）`metadata_invalid`；⑨ 配額預估（資料庫大小加 64 KiB）`quota_exceeded`。①～⑨ 都不建任何目錄；全數通過才建立 `samples/` 與 `.partial-*`，其後依序為複製與雜湊（`io_error`／`in_use`／`hash_mismatch`）、樣本檢查含產品檢查（`sample_corrupt`／`metadata_invalid`／`version_mismatch`／`hash_mismatch`／`schema_mismatch`／`product_failed`／`product_timeout`）、發布前第二次配額核算（`quota_exceeded`）、移入版本（`io_error`／`in_use`）。因此 metadata 不合與配額不足同時成立時回 `metadata_invalid`。其後的任何拒絕都移除 `.partial-*`，並移除本次呼叫新建且仍為空的 `samples/` 與 `<root>/tmp/`（既有的、或已有他人項目的不動）。`build-sample` 在建 run 之前先做 ①②③ 與 ⑧ 的同類檢查（另有 fixture 檔讀不了的 `fixture_invalid`），再建 run、載入 fixture，最後走上述 `freeze`；失敗時移除它建的 run（移除失敗另回 `cleanup_failed`），但 run 所在的 `runs/` 目錄不在此保證內，可能留空。
- 並行與占用：不同 run 互不影響；記帳對他人正在清理而消失的項目視為已不存在，拒絕存取在約 0.2 秒重試後仍在才回 `io_error`（指出該項目）。同 run id 並行 `isolate` 恰一個成功、其餘 `run_exists`；同版本並行 `build-sample` 的敗者可能回 `in_use` 而非 `version_exists`，勝者完好。同一 run 不要同時 `reset` 與 `cleanup`，否則可能留下無標記的 run 目錄（含重建的 DB），`cleanup --run-id` 回 `not_a_run_dir`、無法以 id 清除，且仍計入配額，須人工移除。
- 清理失敗：其他程序持有 run 內檔案時，`cleanup`／`reset` 回 `cleanup_failed`（`path`／`size_bytes`／`reason` 指出首項，`details.failures` 列全部），可清項已清、標記保留，放手後以 run id 重試；`exec` 的 `cleanup_failed` 另帶 `details.command_exit_code`。唯讀屬性檔可清；連結與 reparse point 不進入、不刪除。run 內有無法列舉的目錄（如權限拒絕）時，`cleanup`／`reset`／`exec` 回 `io_error`（`path` 指向該目錄、`size_bytes` 為 null、無 `failures` 清單，`exec` 不帶 `command_exit_code`）而非 `cleanup_failed`，標記保留，排除後同樣可重試。
- 子程序與網路：`product_timeout` 只終止直接子程序，不追殺其子孫；`exec` 的命令不設逾時，子孫仍占用 run 檔案時清理回 `cleanup_failed`。隔離只涉及檔案路徑與 `STOCK_*`：工具不取源、預設不封鎖也不稽核網路，`exec` 只移除繼承的 live-source opt-in，命令是否連網由命令自負。
- 平台：檔案占用、junction／reparse point、ACL 拒絕與 `exec` 僅在 Windows 驗證，其他平台未驗。`path_too_long` 預檢只在 Windows 生效，其他平台不限 root 長度，未驗。

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

### 不由 pytest 收集的 standalone-only 測試檔

[`backend/tests/conftest.py`](../../backend/tests/conftest.py) 的 `STANDALONE_ONLY` 列出 2 個以 standalone 為契約執行方式的檔案，由 `pytest_pycollect_makemodule` 排除：整目錄收集或逐檔明列都不 import、不收集（只明列這些檔時 pytest 以 exit 5 結束），pytest 標頭印出清單。略過不是通過也不是 skip，不證該檔已驗，須用下表的指令執行；名單以 conftest 為準，增減時同步本表。

PR CI 的 `standalone` job（[ci.yml](../../.github/workflows/ci.yml)）執行下表 2 檔，指令同下表；`test_share_quantity_storage.py` 以 `PYTHONPATH=backend` 前綴。不進 CI 的模式與理由逐項註解於 ci.yml，CI 要求見[工作手冊](../GITHUB_WORKFLOW.md#review-與合併)。

| 檔 | 執行方式（專案根目錄） |
| --- | --- |
| [`test_share_quantity_storage.py`](../../backend/tests/test_share_quantity_storage.py) | 見[M3-P2](#m3-p2-可信整數保存與磁碟重開驗證入口) |
| [`test_conditional_plan_store.py`](../../backend/tests/test_conditional_plan_store.py) | `python -B -X utf8 backend/tests/test_conditional_plan_store.py`，僅標準函式庫，不需 `--deps` |

### R1-A2 legacy 成交額 migration 的磁碟驗證入口

`tools/Invoke-TurnoverMigrationValidation.ps1` 直接用 unittest 執行 Alembic／fallback 兩路徑各四個案例，共八個子程序，不載入一般 pytest conftest。一般 pytest 缺專用環境時的八個 skip 不算磁碟驗收。Fixture 與 NULL 限度見[資料來源](../DATA_SOURCES.md#r1-a2-legacy-成交額-migration-磁碟驗收有限接受)。

```powershell
$migrationDependencyRoots = 'C:/path/to/shared/backend/.deps;C:/path/to/shared/backend/.validation-deps'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./tools/Invoke-TurnoverMigrationValidation.ps1 -RunOwner '<8 ASCII alphanumeric>' -DependencyRoots $migrationDependencyRoots
```

`-RunOwner` 必填八個 ASCII 英數字元，須使用該 task 核定的 owner；依賴範例改成已核實目錄。`-PythonPath` 可明示既有 Python，預設 bundled。`ExecutionPolicy Bypass` 只作用於子程序，不改全域 policy；無 `KeepArtifacts`。

入口建立 `LocalAppData/Temp/taiwan-stock-r1a2-<RunOwner>-<UUID>`，將三個 `STOCK_*`、`TEMP`／`TMP` 指向根內，禁 bytecode。每案例只准 `data/legacy.db` 與 journal；含 root／data／raw 的上限為 **3 directories／2 files／2 MiB**，單 DB **1 MiB**。每例清理 DB／journal；reparse 或額外內容拒絕清理並分報，清理失敗停止新增案例。

stdout／stderr 在記憶體捕獲。以子程序 exit、八份無 skip 的 metrics 與 `validation_complete` 核對完整執行；`R1A2_RESULT` 分列 `test_exit`、`cleanup_exit`、確切殘留／大小／原因。八個 file-backed 案例不外推正式 DB、API startup、backup restore、UI 或完整 backend。

### R1-A2 selected invalid／拒收的磁碟驗證入口

`tools/Invoke-StockDaySelectedInvalidValidation.ps1` 直接跑 `backend/tests/test_stock_day_selected_invalid_file_integration.py` 的一個 compound unittest；缺專用環境的 `SkipTest` 不算通過。指定三種 invalid／四類拒收見[資料來源](../DATA_SOURCES.md#r1-a2-selected-invalid拒收磁碟整合有限接受)。

```powershell
$selectedInvalidDependencyRoots = '<既有 backend/.deps>;<既有 backend/.validation-deps>'
$selectedInvalidRoot = '<LocalAppData>/Temp/taiwan-stock-r1a2-si-<owner>-<32-hex>'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./tools/Invoke-StockDaySelectedInvalidValidation.ps1 -RunOwner '<owner>' -ValidationRoot $selectedInvalidRoot -DependencyRoots $selectedInvalidDependencyRoots
```

owner 為核定八個 ASCII 英數字元，32-hex 為核定小寫 hex；根須是 `LocalAppData/Temp` 直屬、專案外且不存在，不能沿用已用根。`-PythonPath` 可指定既有 Python，預設 bundled 3.12.14。只對子程序 Bypass；無 `KeepArtifacts`。

內容只准 DB／journal、`capture/capture.zip`／必要 staging／lock、`raw/body.bin`／`receipt.json`／lock。三個 `STOCK_*`、runner 環境、`TEMP`／`TMP` 綁定核定根，禁 bytecode。含暫態檔上限 **4 directories／5 files／2 MiB**；DB **1 MiB**、ZIP／staging **64 KiB**、body／receipt 各 **32 KiB**；DB page 4096 bytes、最多 256 pages。檢查點與退出時核配額。

路徑為 production capture／load／select→adapters 正常去重→`collect(force)`→dispose／new engine→API；其他端點用記憶體 fixture，TPEx 為明示空 batch。程序上限 **60 秒**；只停止自有程序。需一份 `R1A2_SELECTED_INVALID_METRICS`、`tests_run=1`、`skipped=0` 及 `validation_complete`。`R1A2_SELECTED_INVALID_RESULT` 分報 test／cleanup exit 與殘留；`finally` 還原環境，只清核對過的自有路徑，reparse／額外內容拒絕清理。

本入口不涵蓋完整 backend、production startup、UI、live、TPEx、正式 DB 或 migration 八案例。

### R1-A2 legacy 成交量的零落盤驗證入口

從根目錄直接執行 [test_legacy_daily_volume.py](../../backend/tests/test_legacy_daily_volume.py)，不使用一般 pytest 或通用落盤 runner。格式／別名／fixture 範圍見[資料來源](../DATA_SOURCES.md#r1-a2-legacy-日行情成交量精確整數-gate有限接受)。

```powershell
$volumePreviousDeps = $env:STOCK_TEST_DEPS
try {
    $env:STOCK_TEST_DEPS = '<既有 backend/.deps>;<既有 backend/.validation-deps>'
    & python -B -X utf8 ./backend/tests/test_legacy_daily_volume.py
    $volumeTestExit = $LASTEXITCODE
} finally {
    $env:STOCK_TEST_DEPS = $volumePreviousDeps
}
```

Standalone stub 提供 93 日常數與未使用的 `memory-unused/raw`，來源 import 前啟用 audit；adapter `_fetch` 使用記憶體 payload／metadata，不讀寫 raw body。新增產物／殘留上限 **0**。核程序 exit、`subcases`、`blocked_io`；blocked I/O 使程序失敗，不能只看方法數。

Parser／adapter fixture 不包括 capture、collect、SQLite、API、live、UI 或 production startup，也不替代下節磁碟驗收。

### R1-A2 legacy 成交量的磁碟整合驗證入口

`tools/Invoke-LegacyDailyVolumeValidation.ps1` 直接跑 `backend/tests/test_legacy_daily_volume_file_integration.py` 的一個 compound unittest，不載一般 conftest。合法／拒收、兩次 force collect、重開與 API 範圍見[資料來源](../DATA_SOURCES.md#r1-a2-legacy-成交量磁碟整合)。

```powershell
$legacyVolumeDependencyRoots = '<既有 backend/.deps>;<既有 backend/.validation-deps>'
$legacyVolumeRoot = '<LocalAppData>/Temp/taiwan-stock-r1a2-lv-<owner>-<32-hex>'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./tools/Invoke-LegacyDailyVolumeValidation.ps1 -RunOwner '<owner>' -ValidationRoot $legacyVolumeRoot -DependencyRoots $legacyVolumeDependencyRoots
```

owner／root 規則與上述 selected runner 相同；可指定 `-PythonPath`，使用既有共用依賴，不另建環境。內容只准 DB／journal，以及 `raw/twse/2026/09/05`、`raw/tpex/2026/09/05` 的六份 target body／六份 metadata；檔名為 64 位小寫 SHA 的 `.json`／`.meta.json`，ancillary 資料留記憶體。三個 `STOCK_*`、驗證環境及 `TEMP`／`TMP` 收斂核定根，禁 bytecode／ZIP／附件。

含暫態檔上限 **14 files／11 directories／3 MiB**；DB／journal 各 **1 MiB**、raw JSON **32 KiB**、metadata **8 KiB**。程序上限 **60 秒**；需一份 `R1A2_LEGACY_VOLUME_METRICS`、`tests_run=1`、`skipped=0`、`validation_complete=true`。`R1A2_LEGACY_VOLUME_RESULT` 分列 test／cleanup exit 和殘留；只清自有 exact 根，reparse／額外內容拒絕清理。無 `KeepArtifacts`。

預期 audit-denial probes 沒有實際 I/O，TestClient／asyncio 的本地 socketpair 不算外網。其他未驗範圍由資料來源契約負責。

### M1-P3b 記憶體事件接線的驗收入口

server 以 `STOCK_TWSE_EVENTS_MEMORY_CAPTURE=1` 啟用明示 POST，普通 GET／import 不抓外網；契約見[個股頁 §11](../STOCK_RESEARCH_PAGE.md#11-m1-p3bselected-官方事件總覽接線)。歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/development-baseline/README.md` M1-P3b 記憶體事件接線的驗收入口。

### M2-P1 官方事件關注清單的驗收入口

沿 P3b 入口；精確範圍見[個股頁 §12](../STOCK_RESEARCH_PAGE.md#12-m2-p1官方事件關注清單接個股總覽)。歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/development-baseline/README.md` M2-P1 官方事件關注清單的驗收入口。

### M2-P2 搜尋與研究往返的驗收入口

沿 M2-P1 入口；精確範圍見[個股頁 §13](../STOCK_RESEARCH_PAGE.md#13-m2-p2官方事件清單搜尋與研究往返)。歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/development-baseline/README.md` M2-P2 搜尋與研究往返的驗收入口。

### M1／R1-A2 成交量精確呈現的零落盤驗證入口

`python -B -X utf8 backend/tests/test_volume_exact_presentation.py` standalone 執行，Node `tools/volume-exact-preview.cjs` 核 units／chart／overview 與 UI；範圍見[個股頁 §14](../STOCK_RESEARCH_PAGE.md#14-m1r1-a2成交量-httpjavascript個股精確呈現)。歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/development-baseline/README.md` M1／R1-A2 成交量精確呈現的零落盤驗證入口。

### M3-P1 既有庫存股數的零落盤驗證入口

`python -B -X utf8 backend/tests/test_share_quantity_exact_presentation.py` 為記憶體 standalone 入口；`--serve` 只接受自有埠 8777，不在跨站防護範圍（見[#102 一節](#102-本機-runner-的跨站請求防護)）。契約見[UI](../UI_COPY_SPEC.md#m3-p1-既有庫存股數的有限呈現契約)，現行 storage 模式見下節。歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/development-baseline/README.md` M3-P1 既有庫存股數的零落盤驗證入口。

### M3-P2 可信整數保存與磁碟重開驗證入口

股數與輸入契約見[UI](../UI_COPY_SPEC.md#m3-p2-可信整數保存與磁碟重開契約)，migration／readiness 見[R0 §8.11](../R0_IMPLEMENTATION.md#811-m3-p2持倉精確整數-migrationreadiness有限接受)。

`python -B -X utf8 backend/tests/test_share_quantity_storage.py` 預設不建檔，`--memory-storage` 只跑 storage memory cases；standalone 使用共用唯讀依賴，不載 conftest。它 import `app` 時不自行加入 `backend/`，依賴環境沒有 `backend` 時須讓它在 `sys.path`（POSIX shell 前綴 `PYTHONPATH=backend`，CI 即如此；PowerShell 先設 `$env:PYTHONPATH='backend'`），否則 `ModuleNotFoundError: No module named 'app'`。重複 audit probe 的 skip 不得改報全 pass／0 skip。

磁碟模式只接受 `OWNED_ROOT`（`%LOCALAPPDATA%/Temp/taiwan-stock-m3-share-storage-01a10250`）這個原 task 授權的固定根。它在磁碟模式啟動時由 `derive_owned_root()` 從 `%LOCALAPPDATA%` 衍生，import 時不讀環境；`LOCALAPPDATA` 無法衍生（未設、空、相對、含 `..` 或 NUL，Windows 上非磁碟機代號起頭）就拒絕，不 fallback 到 `TEMP`／`APPDATA` 等其他變數或路徑。root／ancestors non-reparse，不得換根繞過限制。最多 **2 files**（DB／journal）、**3 directories**（root／data／raw）、總 **2 MiB**、單 DB **1 MiB**；殘留同上限，無 WAL／pycache／附件／KeepArtifacts。

- `--disk`：四個 sequential synthetic normal／fault 案例，驗 migration、關閉／重開、readiness 唯讀 hash 與 API int64 保存；最後嘗試清理，test／cleanup 分列。
- `--prepare`：exclusive 建 owned DB，不覆寫既有檔。
- `--serve`：只用該 DB 在 loopback 跑 actual `app.main`／readonly readiness，不做 init-db 或 migration；先過跨站防護，見[#102 一節](#102-本機-runner-的跨站請求防護)。
- `--inspect`：SQLite `mode=ro` 查 storage type、已知列與 closed-file SHA。
- `--cleanup`：清理這次核定的自有根。

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/development-baseline/README.md` M3-P2 可信整數保存與磁碟重開驗證入口。

### M3-P3 庫存價值輸入的零落盤驗證入口

Python `test_share_quantity_exact_presentation.py --finance-only`。契約見[UI](../UI_COPY_SPEC.md#m3-p3-庫存成本停損風險輸入可信檢核與拒收保留)。歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/development-baseline/README.md` M3-P3 庫存價值輸入的零落盤驗證入口。

### M3-P4 庫存價值可信讀回的零落盤驗證入口

Python `--finance-read-only`；serve 帶 `--finance-read-fixture`。契約見[UI](../UI_COPY_SPEC.md#m3-p4-既有庫存價值可信讀回與非法停損隔離)。歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/development-baseline/README.md` M3-P4 庫存價值可信讀回的零落盤驗證入口。

### M3-P5 可信股數與估值／持倉判定的零落盤驗證入口

Python `--quantity-trust-only`；serve 帶 `--quantity-trust-fixture`。契約見[UI](../UI_COPY_SPEC.md#m3-p5-可信庫存股數與既有估值持倉判定一致)。歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/development-baseline/README.md` M3-P5 可信股數與估值／持倉判定的零落盤驗證入口。

### M3-P6a 庫存本地行情與試算的零落盤驗證入口

Python `--quote-read-only`；serve 帶 `--quote-read-fixture`。契約見[UI](../UI_COPY_SPEC.md#m3-p6a-庫存收盤數值隔離與本地試算可檢視)。歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/development-baseline/README.md` M3-P6a 庫存本地行情與試算的零落盤驗證入口。

<a id="m3-p6b-actions-清單行情讀回的零落盤驗證入口"></a>

### M3-P6b Actions 清單行情讀回的零落盤驗證入口

Python `--action-read-only`；serve 帶 `--action-read-fixture`。契約見[UI](../UI_COPY_SPEC.md#m3-p6b-actions-清單逐列行情讀回污染隔離)。歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/development-baseline/README.md` M3-P6b Actions 清單行情讀回的零落盤驗證入口。

### M3-P6c 個股詳情行情讀回的零落盤驗證入口

Python `--stock-read-only`，局部矩陣 `--stock-read-case router-matrix`；serve 帶 `--stock-read-fixture`。契約見[個股頁 §15](../STOCK_RESEARCH_PAGE.md#15-m3-p6c個股詳情行情讀回污染隔離)。歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/development-baseline/README.md` M3-P6c 個股詳情行情讀回的零落盤驗證入口。

### M3-P6d 個股研究候選讀回的零落盤驗證入口

Python `--signal-read-only`，局部補驗 `--signal-read-case evidence-shape`；serve 帶 `--signal-read-fixture`。契約見[個股頁 §16](../STOCK_RESEARCH_PAGE.md#16-m3-p6d個股詳情研究候選讀回污染隔離)。歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/development-baseline/README.md` M3-P6d 個股研究候選讀回的零落盤驗證入口。

### M3-P6e 個股獨立特徵／籌碼讀回的零落盤驗證入口

Python `--independent-read-only`；serve 帶 `--independent-read-fixture`。契約見[個股頁 §17](../STOCK_RESEARCH_PAGE.md#17-m3-p6e個股特徵籌碼獨立區塊讀回隔離)。歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/development-baseline/README.md` M3-P6e 個股獨立特徵／籌碼讀回的零落盤驗證入口。

### #102 本機 runner 的跨站請求防護

本機 API runner 只綁 `127.0.0.1`，但不需 preflight 的 simple request（`text/plain` 或表單 POST、no-cors GET）仍能從跨站頁面送到埠上，足以觸發寫入。套用防護的 runner 因此在 app 之前先過跨站防護：拒絕的請求不讀 body，也不碰 DB 或檔案。

**規則**（[`tools/local_runner_gate.py`](../../tools/local_runner_gate.py)，純 ASGI；依序檢查，先成立者先回報）：

1. `Host` 須恰為一個 `127.0.0.1:<該服務自己的埠>`，否則 403 `host_not_admitted`（重複的 Host 亦拒）。
2. `Sec-Fetch-Site` 有送就須恰為一個 `same-origin` 或 `none`（不分大小寫），否則 403 `cross_site_rejected`。
3. `Origin` 有送就須恰為一個 `http://127.0.0.1:<埠>`，否則 403 `origin_not_admitted`。
4. 每個 POST 的 `Content-Type` 須恰為一個 `application/json`（可帶 `charset=utf-8`），否則 415 `content_type_json_required`。

**套用範圍**：[`test_share_quantity_storage.py`](../../backend/tests/test_share_quantity_storage.py)（固定埠 8779）的 `--serve`：`uvicorn` 收到的是 `local_runner_gate.wrap(main.app, port=8779)` 的結果，防護套用到每個路徑與 method，含 `POST /api/portfolio` 與未登記路徑。

**行為**：

- 拒絕回 JSON `{"reason":"<reason>"}` 與 `Cache-Control: no-store`；一律關閉 WebSocket。
- 只認 `127.0.0.1`：用 `http://localhost:<埠>/` 或 `[::1]` 開 API 會得到 403 `host_not_admitted`，一律用 `http://127.0.0.1:<埠>/`。
- `main.app` 掛有 `CORSMiddleware`，允許 Vite 的 `http://localhost:5173`、`http://127.0.0.1:5173`。防護包在它外面：這兩個 origin 的 preflight 與 POST 都先被站別或 `Origin` 規則拒絕，所以 5173 的頁面不能直連 8779。

**限制**：

- 沒有 Fetch Metadata 的舊瀏覽器不送 `Sec-Fetch-Site`，跨站 no-cors GET 也不帶 `Origin`，仍帶正確 Host 而被放行，回應是 opaque。寫入的 POST 被 Content-Type 規則擋下（DELETE、PUT 見下條）。
- 不加防護的服務：`volume-exact-preview.cjs`（只有 GET，上游是記憶體 fixture）；`test_share_quantity_exact_presentation.py --serve`（8777）與 `test_volume_exact_presentation.py --serve` 的埠可被外站直接呼叫，但只影響記憶體 fixture，不取源、不落盤。其中 8777 有 `POST /__review__/shutdown`，外站可以直接把它關掉。
- 產品 API `uvicorn app.main:app` 不用本節的 helper，由 [`backend/app/browser_gate.py`](../../backend/app/browser_gate.py) 對 POST、PUT、PATCH、DELETE 常開防護，GET 不檢查；規則、允許清單、限制與殘留見 [OPERATIONS §1.1](../OPERATIONS.md#11-產品-api-的跨站請求防護)。
- DELETE、PUT 不加 Content-Type 規則：跨站送這兩種 method 需要 preflight，而 preflight 同樣先過防護，`Origin` 不符即 403，不會得到 CORS 許可；它們仍受 Host、`Sec-Fetch-Site`、`Origin` 規則。
- 防的是瀏覽器跨站與 DNS rebinding，不是身分驗證：同機其他程式送出正確 Host 與標頭的請求一樣放行。
- 規則依 Fetch Metadata 與 `Origin` 的規格行為制定；可重建的驗證只用手造標頭，未用真瀏覽器的外站頁面實測。
- 拒絕次數記在結束收據的 `browser_gate_refusals`（依 reason 分列）。Windows 以 Ctrl+Break 停止時，結束收據不一定印出，不能單靠它證明拒絕發生。

**驗證**：防護案例在 `test_share_quantity_storage.py --memory-storage` 內執行（記憶體、不連網、不開服務埠、不建檔案或 DB），以 helper 的拒絕／放行表逐一核對，不另設旗標。

## 歷史驗證

已刪 Temp 附件不作接手依賴；未清、審核拒絕及占用資源仍依[治理 #1](https://github.com/YiCheng0608/stock-lab/issues/1)處理。

### M2-OFFICIAL-EVENT-DATE-RANGE-20261008-1 官方事件區間的零落盤驗證入口

Backend 入口為 [test_official_events.py](../../backend/tests/test_official_events.py)／[test_official_event_focus.py](../../backend/tests/test_official_event_focus.py)（執行方式見下節 EVENT-KIND）；前端沒有獨立 check。歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/development-baseline/README.md` M2-OFFICIAL-EVENT-DATE-RANGE-20261008-1 官方事件區間的零落盤驗證入口。

### M2-OFFICIAL-EVENT-KIND-20261008-1/B1 官方事件類型的零落盤驗證入口

[test_official_events.py](../../backend/tests/test_official_events.py) 及 [test_official_event_focus.py](../../backend/tests/test_official_event_focus.py) 以 `python -B -X utf8`、`PYTHONDONTWRITEBYTECODE=1`／`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 執行：sys.path 先放 `backend`／`backend/tests` 及既有 `backend/.deps`，先執行 `test_official_events.py` 的 `install_zero_disk_guard`，再 import pytest 並以 `--noconftest -q -s -p no:cacheprovider -p no:logging` 跑兩檔；只 memory SQLite，禁止寫入／mutation／subprocess／外網；前端沒有獨立 check。

真來源及 actual 操作見[來源](../SOURCE_REGISTRY.md) §40／[個股頁](../STOCK_RESEARCH_PAGE.md) §45。歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/development-baseline/README.md` M2-OFFICIAL-EVENT-KIND-20261008-1/B1 官方事件類型的零落盤驗證入口。

### M1-TWSE-ISSUER-EVENT-PROFILE-20261008-1：公司與事件的零落盤驗證入口

來源與映射由[來源](../SOURCE_REGISTRY.md) §41 管理，可信操作由[個股頁](../STOCK_RESEARCH_PAGE.md) §46 管理。歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/development-baseline/README.md` M1-TWSE-ISSUER-EVENT-PROFILE-20261008-1。

#### 記憶體測試與既有入口

後端 [test_twse_issuer_profile.py](../../backend/tests/test_twse_issuer_profile.py) 沿 EVENT-KIND 的執行方式（先安裝 `install_zero_disk_guard`，再 import pytest 以 `--noconftest` 跑）。前端由 [StockOverview.test.tsx](../../frontend/src/components/StockOverview.test.tsx) 的 issuer fixture 案例涵蓋，以 `pnpm --dir frontend test:ci`（`frontend/scripts/ci-test.cjs`）執行。

### M1-TWSE-ISSUER-INDUSTRY-TRACE-20261008-1/B1：兩碼追溯的零落盤驗證入口

後端 [test_twse_issuer_industry.py](../../backend/tests/test_twse_issuer_industry.py) 沿 EVENT-KIND 的執行方式；authority 見[來源 §42](../SOURCE_REGISTRY.md)、[產業 §10](../INDUSTRY_CLASSIFICATION.md)、[個股頁 §47](../STOCK_RESEARCH_PAGE.md)。前端 [twseIssuerIndustry.test.ts](../../frontend/src/twseIssuerIndustry.test.ts) 以 `pnpm --dir frontend test:ci`（`frontend/scripts/ci-test.cjs`）執行。歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/development-baseline/README.md` M1-TWSE-ISSUER-INDUSTRY-TRACE-20261008-1/B1。
