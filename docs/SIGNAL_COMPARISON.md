# Signal comparison 離線唯讀契約

更新：2026-09-16。`signal-comparison/v1` 的有限 library 已 review。Caller 明示兩個專案外、stable、rollback-mode SQLite snapshots，再以 exact legacy key 與 exact artifact selector 取得 detached、deterministic 描述報告；`comparable=false` 固定不變。它沒有 CLI、API、UI、worker 或預設 DB 接線，也不建檔、backup、checkpoint、repair 或 migrate。

Artifact identity、revision、lifecycle、attempt/run 與 writer 契約見 [SIGNAL_ARTIFACTS](SIGNAL_ARTIFACTS.md)。

## 1. Public library API

~~~python
compare_signals(
    *,
    legacy_path: str | Path,
    legacy_expected_database_sha256: str,
    legacy_signal_key: str,
    artifact_path: str | Path,
    artifact_expected_database_sha256: str,
    artifact_selector: Mapping[str, Any],
) -> dict[str, Any]

comparison_json(report: Mapping[str, Any]) -> str

SignalArtifactStore.open_readonly(
    database_path: str | Path,
    *,
    expected_database_sha256: str | None = None,
) -> SignalArtifactStore
~~~

`compare_signals` 的兩個 expected SHA-256 必填，格式為 64 hex；大小寫可輸入，report 回 lowercase。較低階 `open_readonly` 可省略 hash，不放寬 comparison 的雙 hash要求。Hash 不能把 active DB 變成 stable snapshot；caller 仍須先取得 inactive、無 sidecar 的 rollback snapshot。

從 repository backend import path 呼叫上列 API，傳入 caller 自行建立的 external snapshots；不得改成正式 `data/stock.db`、`.local` 或 active DB。`comparison_json(report).encode("utf-8")` 可取得 canonical bytes。

## 2. Exact selector 與 missing 行為

Legacy `signal_key` 必須 nonempty，以 BINARY collation 查詢並重核 fetched value。它是 opaque text：不 trim、不解析日期／namespace／subject，也沒有同日或同標的 fallback。

| Artifact selector | 規則 |
| --- | --- |
| `artifact_key` | nonempty exact text |
| `identity_hash` | nonempty exact text |
| `lineage_key`＋`revision` | lineage nonempty；revision 是 positive、non-bool integer |
| 多 selector | 全部以 AND 合併；格式合法但矛盾時為 new missing |

Selector text 不接受前後空白；未知欄、空 mapping、revision 缺 lineage、lineage 缺 revision、bool／零／負／float revision 都在 SQLite-open 前拒絕。

Exact query 零列是合法報告：side state=missing，reason 為 `legacy_signal_missing` 或 `new_artifact_missing`；兩側皆 missing 仍可回 report。多列、schema／FK／data／integrity 異常是 hard error，不降級 missing 或回 partial payload。

## 3. Snapshot 與唯讀保護

兩側在任何 SQLite-open 前完成 path、hash、alias、sidecar 與 header preflight：

- 必須是 existing absolute regular file 且在 workspace／formal／`.local` 外；URI、`:memory:`、symlink／junction／hardlink alias、same-file pair 拒絕。
- 任一 `-wal`、`-shm`、`-journal` 存在時拒絕；SQLite header read/write version byte=2 也拒絕，不替 caller checkpoint 或轉換。
- 每側用 URI `mode=ro`、`query_only=ON`、deny-write authorizer 與單一 read transaction；DDL、DML、ATTACH、load_extension 或關閉 query-only 拒絕。
- 讀前後比對 path、SHA-256、size、mtime_ns 與 sidecars；變化、不可讀或新 sidecar／WAL header fail closed。

兩側 transaction 不是 cross-file atomic snapshot，也不防 active writer、hostile path race 或惡意移除 authorizer。`open_readonly` 不走 writer constructor、DDL 或 `BEGIN IMMEDIATE`，但重用 artifact ownership、seal、binding、refs、lifecycle、attempt/run 與 ancestor validation。

## 4. Legacy 有限 schema 與資料邊界

只支援本版 `signals`、`instruments`、`strategy_versions` plain tables 的必要 real／non-generated columns；view、virtual table、generated required field 拒絕。選到唯一 signal 後：

- ids 必須 positive integer；instrument／strategy FK 各唯一存在，canonical exchange＋symbol 也不得 duplicate。
- exchange／symbol 為 nonempty trimmed uppercase；strategy name／version 為 nonempty trimmed text。
- key、status、entry type、data quality 為 nonempty text；rationale、cutoff、source、created 可 text 或 SQL NULL。
- signal／execution dates 只能是 round-trip `YYYY-MM-DD`，不可為 datetime。
- nullable prices、confidence、execution price 只接受 finite SQLite integer／real，不 coercion text/blob。
- `rule_evidence_json` 的 SQL NULL 保存為 unavailable＋`legacy_evidence_unavailable`；空 object 合法但不表示完整。Malformed、array/scalar/null、duplicate key、NaN／Infinity／overflow exponent 拒絕。頂層 strategy identity 若存在，必須與 FK 完全相同；其他 evidence 不能覆寫 confidence 分類。

Legacy confidence 全部 `is_calibrated=false`、`is_probability=false`：

| Value／identity | kind | 解讀 |
| --- | --- | --- |
| finite 0.75 且兩個 v1 1.0.0 | `legacy_fixed_value` | 舊版固定值，非勝率 |
| SQL NULL | `not_calibrated` | 沒有校準 confidence |
| 其他 finite numeric／identity | `unknown_numeric` | 語意未知，不轉百分比 |

New `signal-artifact/v1` rule-only 要求 confidence=null＋canonical not-calibrated semantics。Malformed SQLite/schema 可直接拋 `sqlite3.DatabaseError`，仍屬 hard failure。

## 5. Report shape 與解讀限制

Top-level exact keys 為 `contract`、`comparable`、`inputs`、`legacy`、`new`、`dimensions`、`reasons`；contract=`signal-comparison/v1`，comparable=false。Inputs echo fingerprints／selectors；legacy 保存 selected snapshot row；new 保存 strict reader 驗證的 artifact。

| Dimension | 狀態 | 僅可解讀 |
| --- | --- | --- |
| subject | equal／different／unavailable | 比較 exchange、symbol、market date、strategy name/version；相等不證 inputs 相同。 |
| status | observational／unavailable | lexical equality 只比較文字，不證 rule／lifecycle 等價。 |
| linkage | match／conflict／unknown／unavailable | new legacy_reference 與**requested** opaque key byte-for-byte 比較；match 只是 caller declaration。 |
| confidence、prices、evidence、quality、time、revision、inputs | incomparable | 不算 delta、不推機率／共同 levels／availability／PIT／execution。 |

Legacy date／cutoff／naive created、new caller-provided decision/as-of、store first-generated／created 均不能單獨證明 availability 或 execution time。Artifact normalizer 會 trim optional legacy_reference，requested legacy key 不 trim，因此含空白 key 可能 exact 命中但 linkage=conflict。

`comparison_json` 採 sorted keys、compact separators、`ensure_ascii=False`、`allow_nan=False`，不加入 wall clock。Report 經 JSON round-trip detached。

成功 report 的 machine reasons：

- missing：`legacy_signal_missing`、`new_artifact_missing`、`selected_side_missing`。
- subject/status：`subject_equality_not_input_equivalence`、`subject_mismatch`、`raw_status_not_rule_or_lifecycle_equivalence`。
- linkage：`caller_linkage_unknown`、`matching_caller_declaration_only`、`legacy_reference_conflict`。
- confidence/prices/evidence/quality：`incomparable_confidence_semantics`、`not_calibrated_not_probability`、`new_levels_contract_absent`、`no_shared_evidence_contract`、`no_shared_quality_contract`。
- time：`legacy_decision_at_not_persisted`、`legacy_generated_at_not_persisted_with_timezone`、`legacy_date_only_execution_not_instant`、`new_decision_asof_caller_provided_not_officially_verified`、`store_generation_creation_metadata_not_availability_pit_execution`。
- revision/inputs：`legacy_revision_unavailable`、`lifecycle_not_trading_state`、`legacy_sealed_inputs_unavailable`、`caller_provided_only`、`not_officially_verified`、`no_paired_replay_or_pit_truth`。

## 6. Errors 與 diagnostics

- `ReadonlySnapshotError(code)`：snapshot path、hash、alias、sidecar、header、change 或 write protection。
- `SignalComparisonError(code)`：selector、legacy schema／row／FK／identity／primitive／date／numeric／evidence。
- Existing artifact store errors：new ownership 或 selected/ancestor/binding/ref/lifecycle/relation integrity；依 exception class 處理，不保證 stable code。
- `sqlite3.DatabaseError`：SQLite 無法讀 malformed DB/schema。

只有兩個 missing reason 是成功 diagnostics；其餘錯誤不產生 report。穩定 codes：

~~~text
ReadonlySnapshotError:
invalid_expected_database_sha256
invalid_snapshot_path
absolute_file_path_required
protected_snapshot_path
snapshot_path_alias
snapshot_regular_file_required
snapshot_sidecar_present
snapshot_wal_header
snapshot_unreadable
snapshot_changed
snapshot_hash_mismatch
same_snapshot_pair
readonly_store_write_forbidden

SignalComparisonError:
invalid_artifact_selector
exact_artifact_selector_required
exact_revision_required
invalid_selector_artifact_key
invalid_selector_identity_hash
invalid_selector_lineage_key
invalid_selector_revision
invalid_legacy_schema
legacy_signal_ambiguous
legacy_exact_key_mismatch
legacy_fk_missing_or_ambiguous
legacy_instrument_identity_ambiguous
noncanonical_legacy_instrument
noncanonical_legacy_strategy
invalid_legacy_evidence
legacy_identity_evidence_conflict
invalid_legacy_signal_key
invalid_legacy_id
invalid_legacy_instrument_id
invalid_legacy_strategy_version_id
invalid_legacy_exchange
invalid_legacy_symbol
invalid_legacy_strategy_name
invalid_legacy_strategy_version
invalid_legacy_status
invalid_legacy_entry_type
invalid_legacy_data_quality
invalid_legacy_rationale
invalid_legacy_data_cutoff
invalid_legacy_source_report
invalid_legacy_created_at
invalid_legacy_signal_date
invalid_legacy_earliest_execution_date
invalid_legacy_execution_date
invalid_legacy_reference_entry
invalid_legacy_pullback_low
invalid_legacy_pullback_high
invalid_legacy_breakout_price
invalid_legacy_invalid_price
invalid_legacy_target_1
invalid_legacy_target_2
invalid_legacy_confidence
invalid_legacy_execution_price
~~~

## 7. Round32 驗收與未完成項

Selectors、read-only protections、legacy validation、deterministic report、corruption 與 diagnostics 已有限 review。仍未完成：同一已證輸入上的 legacy/new paired replay、availability／PIT、產品選版、B7 採用 review、預設切換與策略有效性；`comparable=false` 不得因 subject／status 相等改寫。
