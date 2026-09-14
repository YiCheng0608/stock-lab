# Worker analysis capture 契約

更新：2026-09-14。狀態：已 review；本文件定義 `backend/worker/analysis_capture.py` 的 public API、CLI、環境、local schema、結果與限制。

這條 opt-in 通路把 caller 明示的專案外 stable SQLite snapshot 複製成新的 owned research DB，並在該副本執行現行 analysis core。它會把 shared evaluator 實際收到的參數與結果、private replay bundle、當次 legacy `Signal` snapshot 放在同一 transaction。一般 `analyze`、`run_daily`、backtest、API 與 UI 不會自動啟用。

它不是 `SignalArtifactStore`、`signal-artifact/v1`、完整 B2／B7、歷史 PIT／availability 證明或正式資料處理入口。

## 1. Public API 與 CLI

~~~python
from worker.analysis_capture import (
    AnalysisCaptureError,
    create_research_database,
    execute_analysis_attempt,
    read_analysis_attempt,
)

create_research_database(
    *, source_snapshot_path, expected_source_sha256, research_database_path
)
execute_analysis_attempt(*, research_database_path, attempt_id)
read_analysis_attempt(*, research_database_path, attempt_id)
~~~

- `create_research_database` 驗證 explicit source snapshot 與 expected SHA，exclusive 建立先前不存在的 owned research DB。它只驗 migration marker、必要分析表／欄位、copy hash 與 owner/schema readback，不代表完整 analysis readiness。
- `execute_analysis_attempt` 先驗 owner 與 exact attempt。既存 ID 只做 strict readback，回 `idempotent_reuse=true`；新 ID 才驗隔離環境、lazy import worker/config、執行 `check_database_readiness`，並在同一 transaction 執行 analysis、Signal upsert、capture 與 receipt。
- `read_analysis_attempt` 用 fresh read-only snapshot 依 exact ID 回傳完整 committed receipt/captures；不匯入 worker/config、不需要 STOCK 環境，也沒有 latest／date／subject fallback。

`attempt_id` 長 1～128 字元，首字元為 ASCII 英數，其餘只允許 ASCII 英數、`_ . : -`。它代表明確 analysis attempt；receipt 另存實際 `source_collection_run_id`。

CLI 子命令為：

~~~text
python -m worker.analysis_capture create --source-snapshot-path PATH --expected-source-sha256 HEX --research-database-path PATH
python -m worker.analysis_capture run --research-database-path PATH --attempt-id ID
python -m worker.analysis_capture read --research-database-path PATH --attempt-id ID
~~~

成功載入、解析並進入 handler 後，stdout 只有一個 JSON object。成功 `create` 回 owner，成功 `run`／`read` 回 verified attempt。Handler 內 runtime failure 以 exit 1 回 `{"error":"<code-or-exception-class>","outcome":null,"detail":null}`；argparse 在 handler 前的 usage error 以 exit 2 寫 stderr，不保證 stdout JSON。模組沒有 export 或 cleanup API。

## 2. Source、target 與環境

Source 必須是 caller 預先建立的專案外、inactive、stable、rollback-mode SQLite consistent snapshot，且沒有 `-wal`、`-shm`、`-journal` sidecar。Caller 依 snapshot bytes 計算 expected SHA-256；library 不尋找或選擇目前正式庫。

Target 必須是 caller 指定且已授權的具名專案外 research output；它必須是 absolute external path，主檔與三種 sidecar 都不存在。實作拒絕 workspace／受保護路徑、URI、`:memory:`、symlink／junction／hard-link alias 與未知既有目標，不會認領、清空或覆寫既有檔案。真正磁碟 capture 所需的 source snapshot、new research DB 與 unused config DB path 都由 caller 管理；落盤必要性、產物／殘留 budget、保留與清理依 [AGENTS](../AGENTS.md#驗證資料與暫存)，本文件不另設示範 Temp 流程。

Owner 保存的 source fingerprint 對應建立 owned DB 前的原 snapshot bytes。後續 attempt 會在 research DB 寫入 analysis／legacy Signal／capture rows，所以 owner SHA 不是目前 research DB、selected call 或 exact evaluator inputs 的 hash；任何後續 bridge 都須另驗 stable current research snapshot 與 expected SHA。候選映射與 fail-closed 邊界由 [Signal artifact §10](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與下一候選) 統一負責。

每個新 attempt 在 lazy import 前需要三個 process environment variables：

| 變數 | 契約 |
| --- | --- |
| `STOCK_DATA_DIR` | Absolute external directory，或所有既存 parent 皆為 directory 的可建立位置。 |
| `STOCK_RAW_DIR` | 同上；不得位於 workspace、受保護或 alias 路徑。 |
| `STOCK_DB_PATH` | Absolute external、尚不存在的隔離 placeholder DB；不得等於 source/research DB，主檔與 sidecar 均不得存在。它不是本次 analysis connection。 |

Library/CLI 不修改全域環境；真正 analysis connection 永遠是 `research_database_path`。

## 3. Capture 內容

Analysis date 沿用 worker：選 `updated_at,id` 最新的 official collection run，要求 `status=success` 且 `data_as_of` 可解析，再以該 market date 計算 features/groups/signals。`observed_market_date` 只是這次 workflow 選中的日曆日，不是 `decision_at`、`first_available_at` 或 PIT 證據。

每個有該日 bar、由 `_upsert_signal` 寫入 breakout 與 pullback Signal 的 subject，按以下順序保存四列 evaluator call：

~~~text
selected breakout occurrence: breakout_v1, pullback_v1
selected pullback occurrence: breakout_v1, pullback_v1
~~~

Breakout exact 7 kwargs：`close`、`prior_highs`、`volume`、`prior_volumes`、`group_excess_return_20d`、`institutional_flow_to_turnover_ratio_5d`、`margin_balance_change_ratio_5d`。Pullback 不含 `prior_highs`，加入 `bar_count`、`ma20`、`ma60`，為 exact 9 kwargs。保存的是 evaluator 呼叫前的轉換後值，含 `_safe_float(close/volume)` 與 `int(raw_bar_count)`；history 保留原順序、prefix、null、空或短 list，不從 mutable `rule_evidence_json.inputs` 回推。

每列 payload exact fields：

~~~text
attempt_id, database_id, ordinal, evaluator,
selected_strategy {id, name, version, config},
namespace, subject {instrument_id, market, exchange, symbol},
observed_market_date, signal_snapshot, arguments,
captured_at, actual_result, bundle
~~~

- `actual_result` 是 shared callable 實際回傳的 `passed/state/ordered reasons`。
- `bundle` 是 `rule-replay-bundle/v1` 以同一份 detached arguments 在 fresh private module 重算的 pinned result。兩者必須 canonical JSON identity 完全相同；`false != 0`、`1.0 != 1`。
- `selected_strategy.config`、`StrategyVersion.config_json`、`canonical_config_snapshot` 與 evaluator pinned config 必須相符。
- `signal_snapshot` 是 `db.flush()`／`refresh()` 後 legacy Signal 的完整 detached snapshot，並與 subject/date/strategy/key/evidence 交叉核對。其 confidence/time/price 仍是 legacy semantics，不可稱新 artifact、校準機率或完整歷史 reconstruction。

有 bar 的 subject 產生 2 個 Signal snapshots、4 個 call rows：

~~~text
signal_count = analysis.signals_upserted * 2
call rows     = signal_count * 2 = analysis.signals_upserted * 4
~~~

沒有該日 bar 的 active instrument 不增加數量。

## 4. Local schema、transaction 與 ownership

Capture schema 只存在 owned research DB，不加入 ORM metadata 或 Alembic：

| Table | 契約 |
| --- | --- |
| `worker_capture_owner` | 恰一列 `id=1`；sealed kind、random `database_id`、aware `created_at`、source path/SHA/size/mtime/sidecars fingerprint。 |
| `worker_capture_attempts` | `attempt_id` primary key；sealed owner/source binding、analysis result、collection run、ordered call digests 與 counts。 |
| `worker_capture_calls` | `(attempt_id, ordinal)` primary key及 deferred FK；每列一個 sealed exact call payload。 |

三表各有阻擋 UPDATE、DELETE、same-identity INSERT/replace 的 trigger。Strict reader 要求 exact schema object set，包含兩個 SQLite primary-key autoindex；capture table 上多出或少掉任一 trigger/index 都是 `capture_schema_mismatch`。這只偵測 trusted-local accidental corruption；SHA-256 seal 不是 hostile administrator 下的 authentication。

新 attempt 使用一個 explicit SQLAlchemy Session 與 `BEGIN IMMEDIATE`。Features、groups、legacy Signal upsert、calls 與 receipt 一起 commit；pre-commit failure 會嘗試整筆 rollback。只有 commit 後 fresh strict readback 通過才回 `committed_verified`。

同一 ID 再執行只回原 durable data；不同 ID 會依當時 mutable legacy state 再分析並追加 capture，不保證相同輸入 replay。

## 5. Strict JSON、replay binding 與 reader

Owner、receipt 與每個完整 call payload 都須在 canonical native-JSON domain；每個 canonical payload上限 1 MiB。Bundle 另限 container depth 16、每個 history 10,000 elements、finite float、整數 ±(2^53−1)。不合法、過深或過大資料直接失敗，不清洗、截短或補零。

固定 binding 為 CPython 3.12.14、binary64、完整 `backend/app/domain.py` bytes SHA-256 與兩份完整 config digest；bundle shape 與 replay errors 見 [Rule replay 契約](RULE_REPLAY.md)。Pin 不符時新 attempt 失敗，不改用 shared mutable config。

Strict reader驗 owner/schema、canonical text/digest、exact attempt、row/count/ordinal、subject/date/strategy/Signal/evidence 與 pair關係，並執行 `rule_replay_json` 和 `replay_rule_inputs`。它不以目前 mutable `signals` row 反證舊 snapshot，也沒有 partial success 或 fallback latest。

## 6. Outcome 與錯誤

| Outcome | 意義 |
| --- | --- |
| `committed_verified` | Commit 後 fresh strict readback 成功。 |
| `committed_verified_after_error` | Commit 呼叫拋錯，但 readback 證明 exact attempt 已 committed；另回 `commit_error` 類名。 |
| `not_committed` | Analysis 回 `no_data`／`skipped` 等非 success；沒有成功 receipt。 |
| `rollback_confirmed` | Pre-commit error 後 rollback 成功；外層 error 為 `analysis_failed`。 |
| `not_committed_verified` | Commit 拋錯，fresh exact read 確認 attempt 不存在。 |
| `commit_outcome_unknown` | Commit/rollback/readback 無法判定；不得宣稱成功或 rollback。 |
| `creation_outcome_unknown` | Exclusive target 出現後 create 失敗；檔案可能 partial 或完整 owned。不可用同 path retry，須由 caller 核實並管理。 |

`AnalysisCaptureError` 提供 `.code`、nullable `.outcome`、nullable `.detail`；caller 應依 code/outcome 處理，不解析 message。

- Path/create：`absolute_external_path_required`、`protected_path`、`path_alias`、`expected_source_sha256_required`、`target_exists`、`source_migration_not_ready`、`source_analysis_schema_missing`、`source_already_owned`、`copied_source_hash_mismatch`、`creation_readback_mismatch`、`creation_failed`；snapshot 前置亦可能拋 `ReadonlySnapshotError` 的 path/hash/sidecar/WAL/change code。
- Owner/read：`capture_schema_mismatch`、`ownership_missing`、`ownership_invalid`、`source_fingerprint_invalid`、`invalid_sealed_payload`、`invalid_capture_timestamp`、`invalid_market_date`、`attempt_not_found`、`attempt_manifest_mismatch`、`attempt_count_mismatch`、`attempt_metadata_invalid`、`capture_relation_mismatch`、`capture_keys_mismatch`、`capture_occurrence_invalid`、`capture_replay_mismatch`、`capture_signal_link_mismatch`、`capture_snapshot_shape_invalid`、`capture_snapshot_type_invalid`、`capture_signal_evidence_mismatch`、`capture_strategy_link_mismatch`、`capture_result_mismatch`、`capture_pair_mismatch`、`capture_occurrence_mismatch`、`capture_integrity_error`。
- New-run preflight：`invalid_attempt_id`、`isolated_stock_environment_required`、`stock_directory_required`、`stock_database_parent_invalid`、`stock_database_must_be_unused`，以及 `check_database_readiness` errors。
- Execution/transaction：`worker_private_result_mismatch`、`duplicate_or_missing_occurrence`、`worker_strategy_binding_mismatch`、`worker_capture_count_mismatch`、`analysis_failed`、`commit_readback_failed`。

Create 在 target 尚未出現時保留原 exception；target 一旦出現，外層固定為 `creation_failed` + `creation_outcome_unknown`，原原因在 `detail`。重試必須換全新 path。

## 7. Review pin 與未完成範圍

Review 使用專案外、migration-ready synthetic source 與 owned copies；正式 DB 當時被其他 process 占用，未驗 byte hash。`pipeline.py`、`analysis_capture.py` 與其 test 當時的 frozen SHA、完整逐輪命令與失敗史可由 `git show 69f62cf7b9e9003c3878952cc33636ed9a063865:docs/WORKER_ANALYSIS_CAPTURE.md` 取閱；這些 SHA 是歷史 review receipt，真正 replay runtime pins 以 [RULE_REPLAY](RULE_REPLAY.md) 為準。

仍未完成／不在保證內：

- 不建立 `SignalArtifactStore`，不保存官方 truth、`first_available_at`、`decision_at`，也不做 legacy-v2 same-snapshot paired replay；B2、B5b、B7 未完成。
- Bridge A 只完成 source／graph 缺口 review；explicit capture→candidate adapter 仍是提案，capture／receipt digest 或新研究 decision time 都不能補成 historical availability／PIT。
- 未接 default analyze、daily/backfill、backtest、API、UI 或 DecisionSummary，未切換預設策略／輸出版本。
- `captured_at` 是 observation time；`observed_market_date` 是 collection-selected date，兩者都不是 availability/PIT。
- R35 已有限 review 新 producer／worker 的 member-return identity 與保守 legacy lookup，規則見[產業分類契約 §8](INDUSTRY_CLASSIFICATION.md#8-群組衍生成員報酬的身分契約有限-review)。R36 的 candidate typed producer／decision lookup 也已有限 review，規則見[產業分類 §9](INDUSTRY_CLASSIFICATION.md#9-群組候選的身分契約)；這沒有另行驗收本 capture runtime，也不替舊輸入補造 identity，API／UI／backfill 與歷史批次回算仍不在保證內。
- Trusted-local、inactive snapshot、非敵對 filesystem/runtime 是前提；active-writer race、hostile rewrite、實體 crash/disk-full與長期保管不在有限 review。

整體邊界見 [Signal artifact 持久化契約](SIGNAL_ARTIFACTS.md)、[R0 實作契約](R0_IMPLEMENTATION.md)、[ROADMAP](ROADMAP.md)與[執行清單](ROADMAP_EXECUTION.md)。
