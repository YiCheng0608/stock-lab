# Worker analysis capture 操作與持久化契約

更新：2026-09-14。狀態：**已 review（Round34 C034-B 有限 opt-in worker evaluation capture）**。

本文件是 `backend/worker/analysis_capture.py` 的 public API、CLI、環境、local schema、結果、錯誤與限制權威。這個通路會從 caller 明示的專案外 stable SQLite snapshot 建立一份新的 owned 研究 DB，然後在該副本執行現行 analysis core，把實際 shared evaluator 收到的完整轉換後參數、實際結果、Round33 private replay bundle 與當次 legacy `Signal` snapshot 放進同一 transaction。一般 `analyze`、`run_daily`、backtest、API 與 UI 不會自動啟用 capture。

這是 **worker evaluation capture**，不是 `SignalArtifactStore`、`signal-artifact/v1`、完整 B2／B7、歷史 PIT／availability 證明或正式資料處理入口。

## 1. Public API

```python
from worker.analysis_capture import (
    AnalysisCaptureError,
    create_research_database,
    execute_analysis_attempt,
    read_analysis_attempt,
)
```

```python
create_research_database(
    *,
    source_snapshot_path,
    expected_source_sha256,
    research_database_path,
)

execute_analysis_attempt(*, research_database_path, attempt_id)
read_analysis_attempt(*, research_database_path, attempt_id)
```

- `create_research_database`：驗證 explicit source snapshot 與 expected SHA，exclusive 建立一個先前不存在的 owned research DB。它只驗有限 migration marker、必要分析表／欄位、copy hash 與 local owner/schema readback；**不代表 research DB 已通過完整執行 readiness**。
- `execute_analysis_attempt`：先驗 owner 與 exact attempt。已存在的同 ID 只做 strict readback 並回 `idempotent_reuse=true`；新 ID 才驗三個 STOCK 隔離路徑、lazy import worker/config、執行既有 `check_database_readiness`，再於同一 transaction 執行 analysis、Signal upsert、capture 與 receipt。
- `read_analysis_attempt`：用 fresh read-only snapshot 依 exact attempt ID 驗證並回傳完整 committed receipt/captures；不匯入 worker/config，不需 STOCK 環境，也沒有 latest／date／subject fallback。

`attempt_id` 必須是 1～128 字元，首字元為 ASCII 英數；其餘只允許 ASCII 英數、`_ . : -`。ID 表示一次明確 analysis attempt，不是 official collection run ID；receipt 會另存實際選中的 `source_collection_run_id`。

## 2. Source、target 與環境前置

Source 必須由 caller 先建立成專案外、inactive、stable、rollback-mode 的 SQLite consistent snapshot，且沒有 `-wal`、`-shm`、`-journal` sidecar。不要直接以檔案複製 active WAL DB，也不要把正式 `data/stock.db`、專案 `.local` 或 workspace 內檔案當範例來源。Caller 必須從該 snapshot bytes 自行計算 expected SHA-256；library 不替 caller 尋找或挑選「目前正式庫」。

Research target 必須是 absolute external path，而且主檔及三種 sidecar 都不存在。實作拒絕 workspace／受保護路徑、URI、`:memory:`、symlink／junction／hard-link alias 與未知既有目標；不會認領、清空或覆寫既有檔案。

每個**新** attempt 在 lazy worker/config import 前要求下列三個 process environment variables：

| 變數 | 契約 |
| --- | --- |
| `STOCK_DATA_DIR` | absolute external directory，或所有既存 parent 都是 directory 的可建立位置。 |
| `STOCK_RAW_DIR` | 同上；不得位於 workspace／受保護或 alias 路徑。 |
| `STOCK_DB_PATH` | absolute external、尚不存在的隔離 placeholder DB path；不得等於 source 或 research DB，主檔／sidecar 都不得存在。它不會成為本次 analysis 的連線目標。 |

Library/CLI 不替 caller 改全域環境。設定這三個值只是把 lazy import 可能使用的預設副作用限制在 caller 指定的專案外位置；真正 analysis connection 永遠是 `research_database_path`。

## 3. PowerShell 可執行範例

以下範例只接受 caller 透過 `WORKER_CAPTURE_SOURCE` 明示的**外部一致快照**，並建立新的外部 Temp research DB。它不建立、複製或開啟正式 DB。

在 repository root 執行：

```powershell
$RepoRoot = (Get-Location).Path
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot 'backend\worker\analysis_capture.py') -PathType Leaf)) {
    throw 'Run this example from the taiwan-stock-research repository root.'
}
$PythonPath = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Bundled CPython 3.12.14 not found: $PythonPath"
}
if (-not $env:WORKER_CAPTURE_SOURCE) {
    throw 'Set WORKER_CAPTURE_SOURCE to a caller-created external consistent SQLite snapshot.'
}
$SourceSnapshot = (Resolve-Path -LiteralPath $env:WORKER_CAPTURE_SOURCE).Path
$RepoPrefix = $RepoRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if ($SourceSnapshot.StartsWith($RepoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Source snapshot must be outside the repository.'
}

$CaptureRoot = Join-Path ([IO.Path]::GetTempPath()) ('worker-analysis-capture-' + [guid]::NewGuid().ToString('N'))
$DataDir = Join-Path $CaptureRoot 'runtime-data'
$RawDir = Join-Path $CaptureRoot 'runtime-raw'
$UnusedDbDir = Join-Path $CaptureRoot 'unused-config-db'
$ResearchDb = Join-Path $CaptureRoot 'research.db'
New-Item -ItemType Directory -Path $DataDir, $RawDir, $UnusedDbDir -ErrorAction Stop | Out-Null

$env:STOCK_DATA_DIR = $DataDir
$env:STOCK_RAW_DIR = $RawDir
$env:STOCK_DB_PATH = Join-Path $UnusedDbDir 'unused.db'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = @(
    (Join-Path $RepoRoot 'backend'),
    (Join-Path $RepoRoot 'backend\.deps'),
    (Join-Path $RepoRoot 'backend\.validation-deps')
) -join [IO.Path]::PathSeparator

$ExpectedSourceSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $SourceSnapshot).Hash.ToLowerInvariant()
$AttemptId = 'manual-analysis-001'

& $PythonPath -Xutf8 -m worker.analysis_capture create `
    --source-snapshot-path $SourceSnapshot `
    --expected-source-sha256 $ExpectedSourceSha `
    --research-database-path $ResearchDb
if ($LASTEXITCODE -ne 0) { throw 'capture create failed; do not reuse an outcome-unknown target' }

& $PythonPath -Xutf8 -m worker.analysis_capture run `
    --research-database-path $ResearchDb `
    --attempt-id $AttemptId
if ($LASTEXITCODE -ne 0) { throw 'capture run failed; inspect the JSON error/outcome' }

& $PythonPath -Xutf8 -m worker.analysis_capture read `
    --research-database-path $ResearchDb `
    --attempt-id $AttemptId
if ($LASTEXITCODE -ne 0) { throw 'capture readback failed' }
```

Module 在受支援環境成功載入、參數也成功解析並進入 handler 後，每個子命令 stdout 只有一個 JSON object。成功 `create` 回 owner；成功 `run`／`read` 回 verified attempt。Handler 捕捉的 runtime 失敗會以 CLI exit 1 在 stdout 回：

```json
{"error":"<code-or-exception-class>","outcome":null,"detail":null}
```

缺 required argument、未知 subcommand等 argparse usage error 發生在上述 handler 前，會以 exit 2 把 usage/error 寫到 stderr，不保證 stdout JSON。

不要把範例中的 Temp research DB 當永久 artifact store。若要長期保存，caller 仍須自行管理專案外位置、備份、權限與生命週期；這個模組沒有 export 或 cleanup API。

## 4. 每個 subject/day 實際保存什麼

Analysis date 沿用既有 worker：選 `updated_at,id` 最新的 official collection run，要求 `status=success` 且 `data_as_of` 可解析，再以該 market date 計算 features/groups/signals。`observed_market_date` 只表示此次 workflow 選中的日曆日；它不是 `decision_at`、`first_available_at` 或 PIT 證據。

每個有該日 bar、由 `_upsert_signal` 寫入兩個 strategy Signal 的 subject，會保存四列 evaluator call，順序固定為：

```text
selected breakout occurrence: breakout_v1, pullback_v1
selected pullback occurrence: breakout_v1, pullback_v1
```

Breakout 保存 exact 7 kwargs：`close`、`prior_highs`、`volume`、`prior_volumes`、`group_excess_return_20d`、`institutional_flow_to_turnover_ratio_5d`、`margin_balance_change_ratio_5d`。Pullback 不含 `prior_highs`，改含 `bar_count`、`ma20`、`ma60`，所以是 exact 9 kwargs。保存的是 shared evaluator 呼叫前的轉換後值：包含 `_safe_float` 的 `close`／`volume`，以及 worker 的 `int(raw_bar_count)` 結果；history 保留原完整順序、prefix、null、空或短 list，不從 mutable `rule_evidence_json.inputs` 事後還原。

每列 call payload exact fields：

```text
attempt_id, database_id, ordinal, evaluator,
selected_strategy {id, name, version, config},
namespace, subject {instrument_id, market, exchange, symbol},
observed_market_date, signal_snapshot, arguments,
captured_at, actual_result, bundle
```

- `actual_result` 是 shared callable 實際回傳的 `passed/state/ordered reasons`。
- `bundle` 是 Round33 `rule-replay-bundle/v1` 用同一份 detached arguments 在 fresh private module 再算的 pinned result。Collector 要求兩者以 canonical JSON identity 完全相同；`false` 不等於 `0`，`1.0` 不等於 `1`。
- `selected_strategy.config`、實際 `StrategyVersion.config_json`、`canonical_config_snapshot` 與該 evaluator 的 pinned config 必須相符。
- `signal_snapshot` 是 `db.flush()`／`refresh()` 後該次 legacy Signal 所有實際欄位的 detached snapshot，並與 subject/date/strategy/key/evidence 交叉核對。它仍可能包含 legacy confidence／time／price semantics，不能稱為新 signal artifact、校準機率或完整歷史 Signal reconstruction。

一個有 bar 的 subject 產生 2 個 Signal snapshots、4 個 call rows；receipt 的 `signal_count` 是 Signal snapshot/strategy occurrence 數，所以：

```text
signal_count = analysis.signals_upserted * 2
call rows     = signal_count * 2 = analysis.signals_upserted * 4
```

沒有該日 bar 的 active instrument 不增加上述預期數量。

## 5. Local schema、transaction 與 ownership

Capture schema 只存在 owned research DB，不加入 ORM metadata 或 Alembic：

| Table | 基數與內容 |
| --- | --- |
| `worker_capture_owner` | 恰一列 `id=1`；sealed `kind`、random `database_id`、aware `created_at`、source path/SHA/size/mtime/sidecars fingerprint。 |
| `worker_capture_attempts` | `attempt_id` primary key；sealed receipt，含 owner/source binding、analysis result、collection run、ordered call digests 與 counts。 |
| `worker_capture_calls` | `(attempt_id, ordinal)` primary key及 deferred FK；每列是 sealed exact call payload。 |

三表各有 UPDATE、DELETE、same-identity INSERT/replace 阻擋 trigger；strict reader 另要求 exact schema object set，包括兩個 SQLite primary-key autoindex。多出任意名稱但附著於 capture table 的 trigger/index，或少一個預期 object，都會 `capture_schema_mismatch`。這能偵測 trusted-local accidental corruption；能修改 schema、payload 與 digest 的 hostile administrator 不在保證內，SHA-256 seal 也不是 authentication。

新 attempt 使用一個 explicit SQLAlchemy Session 與 `BEGIN IMMEDIATE`。Features、groups、legacy Signal upsert、calls 與 receipt 一起 commit；evaluator、private replay、config binding、capture、flush、count 或 receipt 任一 pre-commit failure 會嘗試整筆 rollback。成功只有在 commit 後用 fresh connection strict readback 通過時才回 `committed_verified`。

同一 `attempt_id` 再呼叫 `execute_analysis_attempt` 不重算現在的 collection/date/Signal，也不需要三個 STOCK env；它只回原 durable receipt/captures並設 `idempotent_reuse=true`。不同 ID 是新的 analysis，會再次依當時 research DB 的 mutable legacy state 執行並追加 capture；它不是相同輸入的 replay 保證。

## 6. Strict JSON、R33 binding 與 reader

Owner、receipt 與**每個完整 call payload**都必須落在 Round33 canonical native-JSON domain；每個 canonical payload上限 1 MiB。Rule bundle 另沿用 container depth 16、每個 history 10,000 elements、finite float 與整數 ±(2^53−1) 限制。非原生 dict/list/string/number/bool/null、nonfinite、過深或超限資料在 write/read 失敗，不會清洗、截短或補零後稱 exact。

Round34 沿用 Round33 固定 binding：CPython 3.12.14、binary64、完整 `backend/app/domain.py` bytes SHA-256 與兩個完整 config digests。詳情、bundle shape 與 replay error family見 [Rule replay 契約](RULE_REPLAY.md)。Source/config/runtime pin 不相符時，新 attempt 失敗；capture 不會默默改用 shared mutable config 冒充 pinned replay。

Strict reader驗 owner/schema、sealed canonical text與digest、exact attempt、完整 row/count/ordinal、subject/date/strategy/Signal/evidence/internal pair關係，並真的執行 `rule_replay_json` 與 `replay_rule_inputs`。它不從目前 mutable `signals` row 反證舊 snapshot，也不提供 partial success 或 fallback latest。

## 7. 結果與失敗語意

| 結果／outcome | 意義 |
| --- | --- |
| `committed_verified` | commit 後 fresh strict readback 成功。 |
| `committed_verified_after_error` | commit 呼叫拋錯，但 fresh strict readback證明 exact attempt 已 committed；另有 `commit_error` 類名。 |
| `not_committed` | analysis 回 `no_data`／`skipped` 等非 success；沒有成功 attempt receipt。 |
| `rollback_confirmed` | pre-commit error 後 Session rollback 成功；外層 error 為 `analysis_failed`。 |
| `not_committed_verified` | commit 呼叫拋錯且 fresh exact read確認 attempt 不存在。 |
| `commit_outcome_unknown` | commit/rollback/readback 無法可靠判定；不得宣稱成功或 rollback。 |
| `creation_outcome_unknown` | exclusive target 已出現後 create 失敗；檔案可能 partial，也可能已完整 owned。模組不自動刪除、認領、覆寫或以同 path retry；caller 需另行核實／診斷並自行管理該檔。 |

`AnalysisCaptureError` 提供 `.code`、nullable `.outcome`、nullable `.detail`。Public caller 應依 code/outcome 處理，不解析 message。主要 code 分組如下：

- path/create：`absolute_external_path_required`、`protected_path`、`path_alias`、`expected_source_sha256_required`、`target_exists`、`source_migration_not_ready`、`source_analysis_schema_missing`、`source_already_owned`、`copied_source_hash_mismatch`、`creation_readback_mismatch`、`creation_failed`；source snapshot 前置也可能直接拋 `ReadonlySnapshotError` 的 path/hash/sidecar/WAL/change code。
- owner/read：`capture_schema_mismatch`、`ownership_missing`、`ownership_invalid`、`source_fingerprint_invalid`、`invalid_sealed_payload`、`invalid_capture_timestamp`、`invalid_market_date`、`attempt_not_found`、`attempt_manifest_mismatch`、`attempt_count_mismatch`、`attempt_metadata_invalid`、`capture_relation_mismatch`、`capture_keys_mismatch`、`capture_occurrence_invalid`、`capture_replay_mismatch`、`capture_signal_link_mismatch`、`capture_snapshot_shape_invalid`、`capture_snapshot_type_invalid`、`capture_signal_evidence_mismatch`、`capture_strategy_link_mismatch`、`capture_result_mismatch`、`capture_pair_mismatch`、`capture_occurrence_mismatch`、`capture_integrity_error`。
- new-run preflight：`invalid_attempt_id`、`isolated_stock_environment_required`、`stock_directory_required`、`stock_database_parent_invalid`、`stock_database_must_be_unused`；完整 readiness failure沿用 `check_database_readiness` 的錯誤。
- execution/transaction：`worker_private_result_mismatch`、`duplicate_or_missing_occurrence`、`worker_strategy_binding_mismatch`、`worker_capture_count_mismatch`、`analysis_failed`、`commit_readback_failed`。

Create 失敗若尚未建立 target，原始 source/path exception 保留；一旦 caller 指定的原本不存在 target 出現，外層固定改為 `creation_failed`＋`creation_outcome_unknown`，原原因放在 `detail`。若要重試應換一個全新 path；未知結果檔先由 caller 核實／診斷，再依自己的 artifact 管理政策處置，不能直接假設它是空目標。

## 8. Round34 final review 證據與限制

Frozen source SHA-256：

- `backend/worker/pipeline.py`：`D6311842C2F7F73B8925439BC706B09BEAA191BD4CDD867C613AFD0212F55BB4`
- `backend/worker/analysis_capture.py`：`3EF5F5C71FB5F9F51CE6043C7C7E1E1EDF2300924C588A7D61719FF178D7C980`
- `backend/tests/test_worker_analysis_capture.py`：`111C880A0D79A0384FA6B80CD779362F0393560A46E384A9F2CA293576160409`

作者 final exact-source targeted 為 52 passed、8,929 warnings、12.88 秒、exit 0。作者 full backend 為 2,436 passed、2 skipped、17,549 warnings、exit 0，但 `analysis_capture.py`／tests 當時是較早 guard SHA；因此只能作 default pipeline 與較早 guard 的完整回歸，**不能稱 final capture guard SHA 的 full-suite 結果**。統籌 final public／fault／六組 negative／CLI 四組腳本均 exit 0；這些是獨立 probe groups，不與 pytest case 數相加。D036 另以 final source 跑 owner/schema/env/same-ID/type tamper 具名 probe，exit 0。

失敗史保留：作者最初把 owner `mtime_ns` 存為超出 JSON safe integer的 numeric，後改十進位字串；Windows subprocess large JSON harness 需固定 UTF-8；舊 final `9B114967...` 以 Python equality 把 `false`／`0` 視為相等，產品負例實際失敗後才改成 canonical JSON identity並補 bool/int/float tests。這些不是第一次即成功的 run。

正式 DB 當輪被其他 process 占用，無法取得 byte hash；因此不宣稱正式 DB unchanged 已驗。所有功能驗證使用專案外、真 migration-ready synthetic source與 owned copies。這個通路仍有下列限制：

- 不建立或寫入 `SignalArtifactStore`，不保存可證官方 truth／`first_available_at`／`decision_at`，也不執行 legacy-v2 same-snapshot paired replay；B2、B5b、B7仍未完成。
- 不接 default analyze、daily/backfill、backtest、API、UI 或 DecisionSummary，不切換預設策略／輸出版本。
- `captured_at` 是此次 capture 的 aware observation time；`observed_market_date` 來自現行 collection selection。兩者都不是歷史 availability/PIT 證據。
- 上游 group score `details_json.member_returns` 只保存 `symbol`，現行 signal lookup 也只以 symbol取第一筆。雙 exchange 同 symbol fixture只證 capture subject identity分離，**不證 `group_excess_return_20d` provenance 已 exchange-aware**。這是後續 canonical group-member identity 調查候選，不在 Round34 修正。
- Trusted-local、inactive snapshot與非敵對 filesystem/runtime 是假設；active-writer race、hostile rewrite、實體 crash/disk-full及長期保管不在本批驗收。

整體 B2／B7 邊界見 [Signal artifact 持久化契約](SIGNAL_ARTIFACTS.md)、[R0 實作契約](R0_IMPLEMENTATION.md)、[ROADMAP](ROADMAP.md)與[執行清單](ROADMAP_EXECUTION.md)。
