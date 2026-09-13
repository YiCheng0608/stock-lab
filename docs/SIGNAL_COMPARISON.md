# Signal comparison 離線唯讀契約

更新：2026-09-13。狀態：**已 review（Round32 C032-B 有限 library）**。

本文件說明 `signal-comparison/v1`：呼叫端明示兩個專案外、穩定且為 rollback mode 的 SQLite snapshot，再以 exact legacy key 與 exact signal-artifact selector 取得一份 detached、可穩定序列化的**描述性**報告。它沒有 CLI、API、UI、worker 或預設資料庫接線，不建立、備份、checkpoint、repair 或 migration；`comparable` 永遠是 `false`，也不完成 B2、B7、paired replay 或 PIT。

Signal artifact 本身的 canonical identity、revision、lifecycle、attempt/run 與 writer 契約仍以 [Signal artifact 持久化契約](SIGNAL_ARTIFACTS.md) 為準。

## 1. Public library API

實際公開介面位於 [`backend/app/signal_comparison.py`](../backend/app/signal_comparison.py) 與 [`backend/app/signal_artifact_store.py`](../backend/app/signal_artifact_store.py)：

```python
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
```

`compare_signals` 的兩個 expected SHA-256 都是必填、恰為 64 個十六進位字元；大小寫均可，實際 fingerprint 以小寫回傳。`open_readonly` 是共用 strict artifact reader 的支援入口，hash 在該較低階介面可省略；這不放寬 comparison 的雙 hash 必填規則。

### 1.1 可用範例

以下是 Python library 呼叫，不是 shell command 或專案 CLI。路徑必須換成呼叫端自己建立的專案外 stable checkpoint；不要改成正式 `data/stock.db`、專案 `.local` 或目前正在寫入的 DB。

```python
from hashlib import file_digest
from pathlib import Path

from app.signal_comparison import compare_signals, comparison_json


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return file_digest(source, "sha256").hexdigest()


legacy = Path(r"C:\external-review\legacy-rollback.sqlite")
artifact = Path(r"C:\external-review\signal-artifacts-rollback.sqlite")

report = compare_signals(
    legacy_path=legacy,
    legacy_expected_database_sha256=sha256(legacy),
    legacy_signal_key="exact-opaque-key",
    artifact_path=artifact,
    artifact_expected_database_sha256=sha256(artifact),
    artifact_selector={"lineage_key": "signal-lineage:v1:…", "revision": 2},
)

canonical_text = comparison_json(report)
canonical_utf8 = canonical_text.encode("utf-8")
```

先計算 hash 不會把正在寫入的 DB 變成安全 snapshot；呼叫端仍須先取得停止變動、無 sidecar 且 rollback-header 的兩個獨立檔案。

## 2. Exact selector 與 missing 行為

Legacy 只接受 nonempty `signal_key`，使用 BINARY collation 並再核對 fetched value；key 是 opaque bytes-equivalent text，不解析日期、namespace、subject，也沒有同日／同標的 fallback。前後空白可屬 legacy key 本身，不會由 comparator trim。

`artifact_selector` 只允許：

| Selector | 規則 |
| --- | --- |
| `artifact_key` | nonempty exact text。 |
| `identity_hash` | nonempty exact text。 |
| `lineage_key`＋`revision` | lineage nonempty；revision 必須是 positive、non-bool integer。 |
| 多個 selector | 全部以 `AND` 合併；矛盾但格式合法時是 new side missing，不 fallback。 |

Artifact selector text 不接受前後空白；未知欄、空 mapping、只有 revision、lineage 未帶 revision、bool／零／負數／浮點 revision 都在 SQLite-open 前拒絕。兩側 exact query 的零筆是有效診斷結果：`legacy.state`／`new.state` 為 `missing`，reason 分別是 `legacy_signal_missing`／`new_artifact_missing`；兩側都 missing 仍可產生報告。多筆、schema／data／FK／integrity 不合法則是 hard error，不會降級成 missing 或回傳部分 payload。

## 3. Snapshot 與唯讀保護

兩個輸入在任一 SQLite-open 前都完成 path、expected hash 與 sidecar preflight：

- 必須是存在、absolute、regular、專案外的檔案；URI、`:memory:`、workspace、`formal`、`.local` 路徑拒絕。
- symlink、junction、hardlink、resolved alias 與兩個 path 指向同一檔案時拒絕。
- 任一 `-wal`、`-shm`、`-journal` sidecar 存在時拒絕。
- SQLite header 的 read 或 write version byte 為 `2` 時拒絕；即使 checkpoint 後 sidecar 已消失，WAL-header DB 仍不會被 comparator 開啟。此 library 只接受 rollback-header snapshot，不替 caller checkpoint 或轉換。
- 每側以 URI `mode=ro`、`PRAGMA query_only=ON`、deny-write authorizer 與單一 read `BEGIN` 讀取；DDL、DML、ATTACH、`load_extension`、關閉 query-only 等操作拒絕。
- 讀前後比較 path、SHA-256、size、nanosecond mtime 與 sidecar 狀態。若前後都成功取得 fingerprint 而內容／metadata 不同，才以 `snapshot_changed` fail closed；若 postcheck 新發現 sidecar、檔案缺失／不可讀或 WAL header，會先分別拋 `snapshot_sidecar_present`、`snapshot_unreadable`、`snapshot_wal_header` 等較具體 code。兩側 snapshot 各自獨立，並非 cross-file atomic transaction，也不保證抵抗 active writer、hostile path race 或惡意移除 Python authorizer。

`SignalArtifactStore.open_readonly` 不走 writer constructor、初始化、DDL 或 `BEGIN IMMEDIATE`；它重用既有 exact reader 的 ownership、seal、binding、feature refs、lifecycle、attempt/run 與 ancestor-chain 驗證。這個入口不會讓一般 `SignalArtifactStore(explicit_path)` writer 取得預設路徑。

## 4. Legacy 有限 schema 與資料邊界

Comparator 只支援本次明列的有限 legacy shape，不是任意 historical／custom schema audit：`signals`、`instruments`、`strategy_versions` 必須是 main schema 的 plain tables，所有必要欄位必須是 `table_xinfo.hidden=0` 的 real／non-generated columns；view、virtual table 或 generated 必要欄拒絕。

選到唯一 exact signal 後才驗證：

- `id`、`instrument_id`、`strategy_version_id` 是 positive integer；SQLite 已儲存成 integer 後無法恢復原 caller 是否以 Python bool binding。
- instrument 與 strategy FK 各自恰有一列；missing、NULL 或 duplicate target 都拒絕，canonical `(exchange, symbol)` duplicate 也拒絕。
- exchange／symbol 必須 nonempty、trimmed、uppercase；strategy name／version 必須 nonempty、trimmed。
- signal key、status、entry type、data quality 是 nonempty text；rationale、cutoff、source、created 是 text 或 SQL NULL。
- `signal_date` 與 nullable execution dates 必須 round-trip `YYYY-MM-DD`；不接受 datetime text。nullable prices、confidence、execution price 只能是 finite SQLite integer／real，不作 text／blob coercion。
- `rule_evidence_json` 的 SQL NULL 保留為 unavailable＋`legacy_evidence_unavailable`；空 object 合法，但不表示 evidence 完整。malformed、array/scalar/null JSON、duplicate key、NaN／Infinity 或 exponent overflow 拒絕。只有頂層 `strategy`、`strategy_version` 是 identity assertion；若存在就必須是與 FK 完全相同的 string。其他 key 原樣保留，不能覆寫 canonical confidence classification。

Legacy confidence 的 canonical 分類只有三種，且全部 `is_calibrated=false`、`is_probability=false`：

| Legacy value／identity | `kind` | 解讀 |
| --- | --- | --- |
| finite `0.75` 且 `breakout_v1@1.0.0` 或 `pullback_v1@1.0.0` | `legacy_fixed_value` | 舊版固定規則值；不是勝率。 |
| SQL NULL | `not_calibrated` | 沒有校準 confidence。 |
| 其他 finite numeric 或其他 strategy/version | `unknown_numeric` | 來源語意未知；不得轉成百分比。 |

新的 `signal-artifact/v1` rule-only artifact 則要求 `confidence=null` 與 canonical `not_calibrated` semantics；legacy evidence 裡自行宣告 probability 不能覆寫上述分類。

Malformed SQLite/schema SQL 可能直接拋出 `sqlite3.DatabaseError`。這仍是 hard failure，不會產生 partial report。

## 5. Report shape 與解讀限制

Top-level keys 固定為 `contract`、`comparable`、`inputs`、`legacy`、`new`、`dimensions`、`reasons`。`contract="signal-comparison/v1"`、`comparable=false`；inputs echo 兩側 fingerprint 與 selector，legacy 保存所選 snapshot row，new 保存經完整 strict reader 驗證的 `StoredSignalArtifact.to_dict()`。

| Dimension | 可能狀態 | 只能如何解讀 |
| --- | --- | --- |
| `subject` | `equal`／`different`／`unavailable` | 比較 actual exchange、symbol、market date、strategy name/version；相等不證 shared inputs，不同也不重選。 |
| `status` | `observational`／`unavailable` | `lexically_equal` 只比較文字；不證 rule 或 lifecycle 等價。 |
| `linkage` | `match`／`conflict`／`unknown`／`unavailable` | new `legacy_reference` 與**請求的** opaque legacy key byte-for-byte 比較，即使 legacy row missing 也如此；match 只表示 caller declaration 相同。 |
| `confidence`、`prices`、`evidence`、`quality`、`time`、`revision`、`inputs` | `incomparable` | 固定保留原因；不算 delta、不推 probability、不把價位 evidence 當共同 levels schema、不推 decision／generated／execution／availability／PIT。 |

時間角色必須分開：legacy `signal_date`／execution dates 是 calendar date，`data_cutoff`／naive `created_at` 只是 legacy text，都不能提升成 instant。new `decision_at`／`as_of_at` 是 caller-provided、not officially verified 的研究宣告；store 的 `first_generated_at` 與 `created_at` 保留既有首次生成／持久化 metadata 角色。四者都不能單獨證明 source availability、PIT gate 或 execution time。

既有 signal-artifact normalizer 會 canonicalize optional `legacy_reference` text；legacy requested key 則保持 opaque。因此含前後空白的 legacy key 可以 exact 命中，但若 artifact 內 reference 已被 trim，linkage 會正確回 `conflict`。不要把這個結果改寫成自動 trim、fallback 或歷史 linkage 證明。

`comparison_json` 使用 sorted keys、compact separators、`ensure_ascii=False`、`allow_nan=False`。未加入 wall clock；來源不變時 mapping、text 與 `.encode("utf-8")` bytes 可重現。回傳值經 JSON round-trip detached；修改某次 report 的 nested mapping／list 不會改來源或下一次結果。

本版成功報告的 machine reason codes 依 dimension 固定如下；top-level `reasons` 依此順序去重，不應依顯示文字分支：

- missing：`legacy_signal_missing`、`new_artifact_missing`、`selected_side_missing`。
- subject／status：`subject_equality_not_input_equivalence`、`subject_mismatch`、`raw_status_not_rule_or_lifecycle_equivalence`。
- linkage：`caller_linkage_unknown`、`matching_caller_declaration_only`、`legacy_reference_conflict`。
- confidence／prices／evidence／quality：`incomparable_confidence_semantics`、`not_calibrated_not_probability`、`new_levels_contract_absent`、`no_shared_evidence_contract`、`no_shared_quality_contract`。
- time：`legacy_decision_at_not_persisted`、`legacy_generated_at_not_persisted_with_timezone`、`legacy_date_only_execution_not_instant`、`new_decision_asof_caller_provided_not_officially_verified`、`store_generation_creation_metadata_not_availability_pit_execution`。
- revision／inputs：`legacy_revision_unavailable`、`lifecycle_not_trading_state`、`legacy_sealed_inputs_unavailable`、`caller_provided_only`、`not_officially_verified`、`no_paired_replay_or_pit_truth`。

## 6. Errors 與 diagnostics

主要 exception family：

- `ReadonlySnapshotError(code)`：hash/path/protection/alias/sidecar/WAL header/unreadable/change/same-pair/write-forbidden；可依 exception class 與 `code` 分支。
- `SignalComparisonError(code)`：selector、legacy schema、ambiguous row、FK、canonical identity、primitive、date、numeric 或 evidence 錯誤；可依 exception class 與 `code` 分支。
- 既有 `SignalArtifactStoreOwnershipError`、`SignalArtifactIntegrityError`、revision/collision 類 store errors：new store ownership 或 selected/ancestor/binding/ref/lifecycle/attempt-run integrity 失敗。
- `sqlite3.DatabaseError`：SQLite 自身無法解析或讀取 malformed database/schema。

實際完整 code 清單以 source 為準。只有 `ReadonlySnapshotError` 與 `SignalComparisonError` 提供本契約的穩定 `code`；既有 store errors 與 `sqlite3.DatabaseError` 應依 exception class 處理，不保證有穩定 `.code`，也不要解析自然語言 message。只有 `legacy_signal_missing`／`new_artifact_missing` 是成功報告內的 missing diagnostics。

本版穩定 `ReadonlySnapshotError.code` 集合：

```text
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
```

本版明列的 `SignalComparisonError.code` 集合：

```text
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
```

## 7. Round32 驗收與未完成項

Frozen source SHA-256：

- `backend/app/signal_artifact_store.py`：`8efd349ada7cc1937e83a7e9f65720795216bb035c604a529d73ae436e480a91`
- `backend/app/signal_comparison.py`：`1f029cb8b5560cfecada8fba5f68d146fe7ce024b7875a34ec6a0e6df691282f`
- `backend/tests/test_signal_comparison.py`：`d23336ce8fb04cdb139430e8618461c97230fbea461cdd39907bb304c87c9437`

統籌 final independent matrix 為 58 cases、68 個 `mode=ro` connections、915 SQL statements、exit 0。作者 final targeted 為 129 passed／1 skipped；作者 full backend 為 2,264 passed／2 skipped／12,414 warnings、pytest 280.69 秒／process 283.578 秒、exit 0，162 個 guards 前後一致；統籌是 review 該 full raw evidence，沒有冒稱自己重跑 full。D034 另有 11／11 focused probes、exit 0。各 run 是不同證據，數字不得相加。

保留的失敗史包含 coordinator Phase A fixture 欄位錯誤、作者初始 corruption setup／readonly alias 失敗，以及 D034 缺 `tzdata` 的錯誤 Python 環境與兩個 probe 預期修正；它們都不是 final product pass，也沒有被 final 成功刪除。D034-B manifest 只封存 5 個 review artifacts 的 SHA／bytes，未包含 mtime 或每個 raw runtime fixture；不得把 5／5 說成所有 probe fixtures 的完整 manifest。

本次只接受有限 offline exact comparison library。以下仍未完成：

1. 以完整保存且可證相同的輸入，實際執行 legacy／new paired replay。
2. B5b 官方 availability／PIT gate、B3-wire 與來源 truth。
3. API list/detail/action、DecisionSummary、UI／worker 接線及版本選擇政策。
4. B7 差異報告、成功／缺資料／gap／公司行動／修訂案例與統籌採用 review。
5. 預設版本切換、策略有效性、winner 或交易建議。
