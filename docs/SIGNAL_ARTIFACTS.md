# Signal artifact 持久化契約

更新：2026-09-27。本文件負責 `signal-artifact/v1` local store、Bridge A 已證邊界、Bridge B capture→candidate adapter，以及獨立 `STOCK_DAY_ALL` selected-bar evidence verifier 的有限 review；Bridge B 現可讀 opt-in selected bar metadata capture v2 及 prior volumes 本地列 capture v3。Verifier 只回傳指定本地證據的一致性結果，未接入 bridge／consumer，亦未以實際 body／receipt／research snapshot 做整合驗收。離線 comparison、pure-rule replay 與 worker capture 是分離能力；R0-B2 整體仍未完成，狀態以 [ROADMAP](ROADMAP.md) 為準。

## 1. 範圍與不變條件

- 新 artifact 與 legacy `signals.signal_key` 使用不同 namespace；不得更新 legacy 列或只補 evidence marker 冒充雙版本。
- Store 不註冊 legacy ORM metadata、不是 Alembic revision、沒有預設 DB path，也不寫 legacy signal／evaluation／settlement。
- Rule-only `confidence=null`；semantics 固定為 `signal-confidence/v2`、`not_calibrated`、`is_calibrated=false`、`is_probability=false`。不得把固定值、raw score 或 unknown numeric 稱為機率。
- Store 的 input／implementation refs 只保證 caller-provided shape 自洽，固定標 `caller_provided_only`／`not_officially_verified`；digest 不證來源、內容或 availability truth。Bridge B 的 v2 selected bar 本地 metadata 證據另見 §10，不改此 store gate。
- 尚無 session／PIT gate，`earliest_execution_at=null` 且 reason 固定為 `execution_time_unavailable_without_pit_session_availability`。不得從 date-only、legacy cutoff 或 naive time 推成 instant。

### 1.1 Canonical 最小 shape

- Mapping 的 `contract` 缺失／null 時補 `signal-artifact/v1`；non-null 只能是該值。Nested／flat alias 同時存在時須 canonical 後相等；未知頂層欄拒絕。
- `signal_output_semantics` 固定：`version=signal-confidence/v2`、`kind=rule_only`、兩個 probability flags 均 false。
- `confidence_semantics` 固定：同 version、`kind=not_calibrated`、兩個 flags false、`display_label_zh=未校準；非預測勝率`。Writer 重建 canonical 值，不信任 caller label／flags。
- `ruleset_snapshot` 必須為 nonempty object，其 canonical JSON 可重算 digest。
- `basis_manifest` 至少含 `mode, verification, status, value, reason`；mode／verification 固定 caller-only／未官方驗證。status 是 provided／unknown／unavailable；後兩者 value=null 且 reason nonempty，provided 要有 nonempty value。
- Dependency／input-source manifest 至少含固定 mode／verification 及去重 string arrays `references`、`unknown_reasons`，兩者至少一個非空。
- Implementation reference 至少含固定 mode／verification、nonempty `ref` 與已比對 SHA-256 `digest`，且須等於 version binding 的 implementation digest。

## 2. 三層識別：subject、research core、revision

### 2.1 Subject group

Subject group 由 normalized exchange＋symbol、`market_date`、strategy name/version 及 `signal_output_semantics_version` 組成，只供同日同策略語意分組。同一 subject 可以有多個 research roots；snapshot、as-of、basis 或 dependency 不同時不可自動挑 latest。

### 2.2 Research-core lineage

`lineage_key` 由完整 canonical input core 導出，包含：

- contract、固定 lineage subject 及 subject group；
- input snapshot id＋hash；
- 含 offset 且 canonicalized 的 `decision_at`，以及 nullable、若提供亦須含 offset 的 `as_of_at`；
- price basis、dependency、ruleset settings 與 implementation digests；
- feature artifact keys、caller-only mode 及 nullable legacy reference。

規則 status/outcome/evidence、quality/missing reasons、nullable confidence 及其 semantics 屬 research payload，不在 core。價位只有 caller 放在 `rule_evidence` 才保存，沒有獨立 levels 欄。

同一 core 只能有一個 root，且不可變綁定 canonical research payload seal；同輸入／版本卻得到不同結果必須 collision，不能用新 revision 或 lifecycle child 規避。只有研究輸入變化才建立新 root；settings／implementation 變化還必須先升對應版本。

### 2.3 Revision 與 artifact identity

Canonical payload 以 positive `revision`、nullable `supersedes_artifact_key` 與 `lifecycle_state` 表達 revision。`lineage_key` 不含 revision；`identity_hash` 是 core＋revision；`artifact_key` 再由完整 revision identity 導出。Caller 提供 key 時只能核對，不能覆寫。

相同 identity＋payload 為 idempotent replay；相同 identity＋不同 payload 是 collision。不得改 revision 將矛盾 research result 包成合法修訂。

## 3. Strategy／semantics version binding

Binding key 是 strategy name＋version＋output-semantics version；value 是 canonical settings digest＋implementation digest，並保存可重算 config／implementation ref。

- 同一 binding 可跨 instrument、date、snapshot、as-of 使用；這些研究維度不能塞進 binding key。
- 同 binding 的 settings 或 implementation 不同時，以 `SignalArtifactCollisionError` 拒絕並 rollback。
- 規則 gate、價位或執行行為變更須升 strategy／execution version；只有輸出 nullability／解讀改變才升 semantics version。
- Binding 只證 caller version／digest 自洽，不證 repository commit、部署或官方輸入；沒有 HEAD 時不得造 commit SHA。

## 4. Canonical payload、generated time 與使用紀錄

Research payload 保存不可變規則結果與 provenance projection，至少含 status/outcome、rule state/evidence、quality/missing reasons、nullable confidence 與 canonical semantics。`research_payload_hash` 與 root/core 的綁定不可變。Payload 排除 generated、attempt、run 與 stored timestamps。

首次 `generated_at` 是 immutable aware metadata：root 不得早於 decision_at；child 不得早於 lifecycle_at。它不進 core、revision identity 或 payload hash。Idempotent retry 保留首次值；候選 time 只驗 shape，不能改舊值或重新判 lineage 順序。

Artifact 1:N attempts；run 1:N attempts；每 attempt 最多綁一個 nullable run。同 artifact＋run 可有多次不同 attempt；只有同 attempt＋artifact/run/payload 才冪等。同 attempt 改綁任何關係須 collision。Relation key、payload hash、FK、identity、0:1 run 與 time 都由 reader 重驗。Attempt validation、relation insert 與 artifact commit 同 transaction，失敗不得留 orphan。

Mapping／dataclass 需先取 canonical deep snapshot；reader 每次回 detached value。修改 caller input 或某次 read 不得改 DB 或下一次結果。除非 nested values 已遞迴 freeze，不得宣稱 Python object 本身 deep immutable。

## 5. Lifecycle revision

~~~text
root: active -> lifecycle revision: withdrawn
~~~

- Root 固定 active；唯一 child state 是 terminal withdrawn。
- Child 沿用相同 core、lineage key 與 payload hash，並保存 predecessor、machine reason、含 offset lifecycle time。
- Lifecycle time 不得早於 decision_at 或 root 首次 generated_at；child generated_at 不得早於 lifecycle event。Store 必須在 transaction 內讀 parent 判斷。
- 不建立 observation、conditional、triggered、filled、target-hit、invalidated、settled 等交易狀態。
- Lineage 只允許線性 append：每 core 一 root、每 parent 最多一 child；缺 parent、跨 core／payload／subject／strategy／semantics、branch、cycle 或 withdrawn 後追加都拒絕。
- 兩 connection 同時 append 時最多一個成功，另一個回 conflict 或 bounded retryable busy。

## 6. Store ownership、transaction 與不可變性

`SignalArtifactStore(explicit_path)` 只接受 caller 明示、專案外的專用 SQLite：

- 拒絕正式／`.local` DB、workspace 路徑及 symlink／hardlink／junction aliases，也拒絕既存空 DB、foreign DB 與 unknown version。Existing DB 先 read-only ownership preflight，再開 write connection；拒絕後主檔與 sidecars 不變。
- Store schema 與 Alembic 分離，不改 app head、fallback marker、lifespan 或 `worker.cli init-db`。
- `PRAGMA foreign_keys=ON`。Artifact、binding、relation rows 以 triggers 禁 UPDATE／DELETE／REPLACE；no-replace 同時覆蓋 rowid 與所有 primary／unique identity，不依賴 recursive triggers。這不防可改 schema 的管理者。
- Write 用 `BEGIN IMMEDIATE`；commit 前從 stored rows 重算 artifact／lineage／revision identity、payload seal、binding、feature／lifecycle、attempt／run 與 parent 關係。Create 和 replay 共用相同 precommit gate；任一 validation／collision／busy 以外錯誤均 rollback。
- `database locked` 轉 bounded retryable error；caller 重試同一 save，不改 identity 或 fallback。

## 7. Exact reader 與 selector

`get_exact` 支援 exact artifact key、exact identity hash，或 exact lineage key＋revision；多 selector 以 AND 合併。零筆可回 null；缺 selector、多筆、cross-identity、binding mismatch 或 seal 損壞 fail closed。

`list_artifacts` 必須明示 lineage，或至少一個受支援 subject filter（strategy、market date、exchange、symbol）；可加 strategy version／revision。完全無 filter 的全庫 list 拒絕。`history` 要 exact lineage。不存在 implicit latest、`<= as_of`、first 或同日 fallback。

Child read 會重驗全部 ancestors 的 core／revision identity、payload／seal、binding、feature refs、lifecycle 及 attempt/run relation；任何 ancestor 或 relation 損壞都拒絕。Legacy comparison 由 [SIGNAL_COMPARISON](SIGNAL_COMPARISON.md) 提供；worker capture 由 [WORKER_ANALYSIS_CAPTURE](WORKER_ANALYSIS_CAPTURE.md) 提供，兩者都未自動連入本 store。Bridge B 只交 candidate，由 caller 另行保存。

## 8. 驗收矩陣

| 面向 | 核心驗收 |
| --- | --- |
| 建立／重開 | Fresh external DB 建 root；reopen exact keys、seal、revision、generated time 相同；拒絕 protected／foreign／unknown stores。 |
| 信心／時間 | confidence null＋canonical semantics；earliest execution null＋固定 reason；拒絕 0.75、naive／date-only 升格。 |
| Retry／collision | Idempotent retry 保留首次 generated time；attempt/run 基數正確；same identity different payload、relation tamper 或 precommit failure 全 rollback。 |
| Binding／root | Binding 可跨研究 subject 使用但不可換 config／implementation；不同研究輸入建新 root，同 core 不同 result collision。 |
| Lifecycle／concurrency | 只允許 active→withdrawn 線性鏈；拒絕 branch、cycle、錯 parent／time；競爭只一個 child 成功。 |
| Reader | Exact／filtered read 唯一；拒絕 latest fallback、無 filter list、ambiguous／damaged ancestor 或 relation。 |
| 相容性 | 不寫 legacy／正式 DB，不自動接 worker／API／UI；fixture 不證 official truth。 |

## 9. Round12 C012 final review 證據與限制

Local foundation 的 canonical shape、ownership、WAL／journal guard、transaction、collision、lifecycle、concurrency、reader 與 nested detachment 已有限 review。這不構成 runtime binding，也不擴張下列相鄰能力。

<a id="91-round32-c032-b有限-offline-exact-comparison"></a>
<a id="92-round33-c033-b有限-caller-provided-current-pure-rule-replay"></a>
<a id="93-round34-c034-b有限-opt-in-worker-evaluation-capture"></a>

| 分離能力 | 與 artifact 的邊界 |
| --- | --- |
| [Offline comparison](SIGNAL_COMPARISON.md) | 對兩個 caller-provided stable snapshots 作 exact、唯讀描述；`comparable=false`，不證 shared input、PIT、execution、winner 或 replay。 |
| [Pure-rule replay](RULE_REPLAY.md) | 保存兩個 v1 evaluator 的 exact caller arguments 與固定 binding；沒有 subject／market／decision time，也不進本 store。Arguments digest 不是 research-core、snapshot hash 或 authentication。 |
| [Worker capture](WORKER_ANALYSIS_CAPTURE.md) | 保存 actual evaluator kwargs／result、private replay bundle 與 legacy Signal snapshot；local capture rows 不是 artifact core／revision／relation，captured／observed time 不證 decision 或 availability。 |

<a id="10-bridge-a-可證映射與下一候選"></a>

## 10. Bridge A 可證映射與 Bridge B 有限成果

Bridge A 的有限 source／graph review 確認：`read_analysis_attempt` 依 exact attempt fail-closed 驗 owner、schema、seal、count、ordinal、pair、Signal／strategy linkage 與 private replay；單一 selected call 可證 evaluator 實際收到的 arguments／result、subject、觀測 market date、selected strategy config／version、legacy Signal snapshot 及 receipt 所記 collection run。v1 只有 capture 內部一致性；opt-in v2 新增 selected bar close／volume 的本地列與 raw metadata 關係；v3 再新增實際 prior volumes 最多 20 筆歷史列的本地 metadata 關係。兩者均沒有驗 raw bytes、來源版本或 availability；owner SHA 也只屬建立 owned DB 前的 source snapshot bytes。Producer／reader 精確規則見 [Worker capture §3.2](WORKER_ANALYSIS_CAPTURE.md#prior-volumes-capture-v3)。

Bridge B 已有限 review 的 opt-in API 位於 `backend/worker/signal_artifact_bridge.py`，只回 detached canonical mapping，不開 `SignalArtifactStore`、不寫 research DB 或 artifact store：

~~~python
build_signal_artifact_candidate(
    *, research_snapshot_path, expected_snapshot_sha256,
    attempt_id, ordinal, decision_at,
)
~~~

| 明示輸入／輸出 | 已接受的候選映射 | 不可擴張的邊界 |
| --- | --- | --- |
| Stable current research snapshot path＋必填 expected SHA、exact attempt＋ordinal | `readonly_snapshot` 驗目前 owned research DB 的 path、bytes、sidecar 與 stable read；同一受保護 snapshot／connection 先以 capture strict reader 驗完整 attempt，再選非負 exact ordinal。只接受 `evaluator == selected_strategy.name` 的 call。 | 不接受 fallback latest、部分 attempt 或未選中的 evaluator。Current research SHA 不等於 owner original-source SHA。 |
| Selected v1 call | `input_snapshot.id` 為 `worker-capture-input/v1:{database_id}/{attempt_id}/{ordinal}`；`hash` 為 `worker-capture-input-manifest/v1` canonical input-only manifest 的 SHA-256。Manifest 含 subject、market date、strategy id/name/version、evaluator、arguments、selected config、pinned evaluator binding 與明示 upstream refs（原 source container SHA、collection run、legacy Signal id/key）。 | Hash 不含 current research container SHA、status/result、captured/receipt time；原 source SHA 只作 upstream container ref，不能代替逐輸入來源或 availability。 |
| Opt-in v2 selected call | Receipt `kind=worker-analysis-capture/v2` 時，bridge、manifest、snapshot ID 分別使用 `worker-capture-candidate/v2`、`worker-capture-input-manifest/v2`、`worker-capture-input/v2:{database_id}/{attempt_id}/{ordinal}`。沿用 v1 manifest 欄位，另加 `selected_bar_input`：bar 的 id／instrument／date／close／volume／source／raw FK，以及 raw 的 id／source／endpoint／宣告 SHA／ingestion run id、status／reason。 | 只封存 selected bar close／volume 的本地 metadata 關係；其餘歷史／衍生輸入仍缺。Hash 排除 bar／raw 的 `data_as_of`、`collected_at`、raw path、current container SHA 及 capture／receipt time；不證 raw bytes 或可得時間。 |
| Opt-in v3 selected call | Receipt `kind=worker-analysis-capture/v3` 時，bridge、manifest、snapshot ID 使用 `worker-capture-candidate/v3`、`worker-capture-input-manifest/v3`、`worker-capture-input/v3:{database_id}/{attempt_id}/{ordinal}`。Manifest 沿用 v2 的 `selected_bar_input`，另加 `prior_volumes_input`：subject／target date、window／`int(volume)`、feature 身分、count／projected values，及有序各列 ordinal、bar id／date／volume／source／raw FK、nullable raw metadata／status／reason。 | 只證本次選中 call 的本地列身份及投影；0／1／19 筆短窗口及零量如實保存，不補歷史資料。Input hash 排除觀測 path／time 與 current container SHA；raw bytes／source version、availability、historical decision 與其餘衍生輸入仍 unknown。 |
| Caller 明示 aware `decision_at` | 代表這次新研究採用時間，不早於 selected call 與 receipt 的 `captured_at`；`generated_at=decision_at`。 | 只證這次時間先後；observed date、legacy cutoff／created time、captured time 均不能回推歷史 decision 或證 PIT。 |
| Selected legacy Signal＋actual evaluator result | `status` 保存 observed legacy snapshot status，`rule_state` 保存 actual result；ruleset 使用 selected config，implementation 固定驗 `domain-rules/v1` pin。`confidence`、`as_of_at`、`earliest_execution_at` 為 null，earliest reason 維持固定值；basis unknown、feature refs 空。 | 不重算 v2 status／levels。Pinned evaluator digest 不涵蓋 adapter、pipeline 或 legacy status／levels，dependency／missing reasons 保留這些缺口。 |
| Capture／receipt 原文 | `rule_evidence.capture_bridge` 保存 exact `call_json`／`receipt_json` opaque string、已驗 call digest、明標 derived 的 receipt seal、manifest JSON／digest，以及 current snapshot path／SHA 和 original source container SHA。v2／v3 另保存完整 `input_provenance_json`／digest 及 `raw_bytes_verification=bytes_unverified`。 | 不把 opaque 原文改成 nested decoded payload；canonicalizer 對 `*_at` 的轉換會破壞原 bytes／seal，legacy naive `created_at` 也不能當 aware time。raw path／time 只在完整 provenance 證據中，不進 input-only hash。 |
| Candidate mapping 與保存 | Adapter 只回 candidate；caller 可另行明示 `attempt_id`／`run_id` 呼叫既有 `SignalArtifactStore.save_artifact`。 | 不自動保存或接 default worker、API、DecisionSummary、前端、comparison consumer；不切預設版本。 |

三種 hash 要分開讀：`expected_snapshot_sha256` 驗本次 current research snapshot，且其 path／SHA 只進 evidence；owner original-source SHA 是建立 owned DB 前的來源容器 fingerprint，僅為 manifest 的 upstream ref；`input_snapshot.hash` 才是 selected call 的 input-only manifest digest。API 沒有 caller 提供的 `input_manifest_digest` 參數；adapter 內部重算 digest，並在回傳前檢查 canonical projection 未改變；v2／v3 亦核對完整 provenance JSON 的 digest。v3 manifest 的 prior rows 依原順序納入身份；改動 bar／raw 關係或 projected values 會改 input hash，觀測欄位則不參與。通用 store 不會在 caller 事後修改 candidate 時再執行 bridge 專屬的 manifest 檢驗。Current snapshot path／SHA 與 opaque call／receipt 都進 research payload；同一 research core 即使 input-only hash 相同，provenance 或結果若變動仍可能因不可變 payload 而 store collision，hash 相同不代表整份 artifact payload 相同。

必須在 current hash／stable snapshot 不符、完整 attempt 任一列損壞、ordinal 不存在、evaluator／selected strategy 不同、subject 需 trim／case 變形、status 需 trim、config／`domain-rules/v1` pin 不符、candidate manifest projection 不符，或 decision 缺失、naive、早於 capture 時 fail closed。v2 reader 以 receipt kind 驗 selected bar 與 arguments／subject／date、raw FK／source／宣告 digest 形狀及 pair；v3 另驗 prior volumes 的 subject／date／count／order／值／嚴格型別／raw 關係和 pair。Unknown kind 或跨版混用拒絕。Capture reader 的 CPython／binary64／`backend/app/domain.py` bytes 與 config pins 仍依 [Worker capture §5](WORKER_ANALYSIS_CAPTURE.md#5-strict-jsonreplay-binding-與-reader)；bridge 不放寬。v2 `data_quality.local_input_row_linkage=close_volume_metadata_captured`，v3 為 `close_volume_prior_volumes_metadata_captured`；`raw_payload_metadata` 是 selected bar 的 `linked_metadata` 或 `unknown`，prior rows 若缺 raw FK 則由 missing reasons 標示。`source_verification=not_officially_verified`、`raw_bytes_verification=bytes_unverified`、availability／historical inputs 為 unknown；basis unknown，`as_of_at`／`earliest_execution_at` 為 null。Missing reasons 標出其餘 raw inputs／source versions、selected bar 與 prior volumes raw bytes／source version、availability、歷史 decision time、price basis 和非 evaluator implementation；缺 raw FK 再標 raw metadata unavailable。Prior highs、MA、groups／chips 等衍生來源尚未連接；digest、receipt 或新 decision time 都不能把 unknown source／availability 升格為已驗證。既有 v3 接線只有有限 DB 與獨立純記憶體診斷，詳見[協作紀錄](TASK_COORDINATION.md)；其餘 pytest 案例待跑，未驗正式來源、歷史輸入、PIT 或磁碟峰值。

### 獨立 `STOCK_DAY_ALL` selected-bar evidence verifier：本地一致性邊界

一般抓取若先解析 HTTP 回應，再將資料重編碼並計算 SHA，只能證重編碼後的內容，不能證原始 HTTP body bytes。既有 opt-in [`STOCK_DAY_ALL` capture](SOURCE_REGISTRY.md#51-stock_day_all-selected-security-bars) 在 `source_runtime.py` 以 `iter_raw()` 取得 identity HTTP entity bytes（移除傳輸 framing 後、不作 content decoding 或 JSON 重編碼），將長度與 SHA-256 記入 receipt，並與 registry 的 source／endpoint／method／`source_version`／manifest pins 關聯。`stock_day_capture.py` 的 loader 核對 ZIP `body.bin`／`receipt.json`、receipt pins、body 長度與 SHA-256，以及全列唯一 symbol／同一交易日期；`StockDayCapture.select` 用 `Decimal` 路徑解析 selected symbol 的價格與整數量。但 loader 最後呼叫 `_publish` 寫出 `body.bin`／`receipt.json`（`stock_day_capture.py:175–207,277–278`），不能直接當零落盤的 verifier。這些既有局部能力先前只有靜態程式 review，本輪也未以實際 body／receipt 與 research snapshot 對照或執行 pytest。

既有 capture→bridge 流程的逐輸入綁定仍缺：`pipeline.py:2122–2126` 的暫存 raw id key 僅為 `(source, SHA)`、不含 endpoint；`_raw_id_for_digest`（2026–2032）只按 SHA 回傳第一筆，因此跨來源或同來源跨 endpoint 的同 digest 會有歧義。`RawPayload` 有 source／endpoint／path／宣告 SHA 與 run id、`MarketBar` 有 nullable raw FK；analysis capture 的 selected bar provenance 封存本地 row、FK、path、宣告 SHA 等 metadata，bridge 的 input manifest 投影不含 path／receipt／來源或 registry version，且仍標 `raw_bytes_verification=bytes_unverified`。它們沒有精確封存 `STOCK_DAY_ALL` body／receipt／registry version 的逐輸入關係，也未從封存 bytes 重解析並比對 selected bar；本輪獨立 verifier 不會回填這些欄位。相同 SHA、raw FK 或本地 `source_version` 不能單獨證明 bytes 來源；registry `source_version` 只是本次本地規格 pin，不證上游修訂版本或官方真實性。

本輪新增的 `backend/worker/stock_day_evidence.py` 不呼叫會落盤的 capture loader，也不改既有 capture／bridge／store。獨立入口只接受 caller 指定的 current research snapshot、exact attempt／ordinal、registry manifest 與外部 pins：

~~~python
verify_selected_bar_evidence(
    *, research_snapshot_path, expected_snapshot_sha256, attempt_id, ordinal,
    manifest_path, expected_registry_version, expected_manifest_digest,
    expected_profile, expected_receipt_sha256,
) -> dict
~~~

`expected_snapshot_sha256` 與 `expected_receipt_sha256` 均須為 SHA-256 hex；registry digest 須為 `sha256:` 加 64 個小寫 hex。入口用 `readonly_snapshot` 核對 current DB SHA／stable read，於同一 connection 以既有 strict reader 驗完整 attempt，再取 exact ordinal；只接受 receipt kind v2／v3 與 selected evaluator。v3 的完整 prior volumes 結構仍由既有 reader 檢查，但本 verifier 的比較與結果只涵蓋 selected bar。

Selected bar provenance 的 raw FK 必須指向 strict reader 已封存的同一 raw metadata；raw source 為 `twse`、endpoint 為 `STOCK_DAY_ALL` 固定 URL、subject exchange 為 `TWSE`。`payload_path` 須精確指向專案外的 `body.bin`，`receipt.json` 固定取同目錄；manifest path 由 caller 明示。檔案檢查要求絕對路徑、regular file、可取得原始 identity、無 symlink／junction 或多連結 alias，且拒絕不存在、不安全路徑與超過 body／receipt／manifest 大小上限的檔案。讀取前核對原始 path／handle identity，限量雙讀，解析後再讀三檔並比較；這是有限的本地穩定性檢查，不保證抵禦任意惡意競態。程式沒有顯式寫入 candidate、DB、cache 或 sidecar；實際檔案／sidecar 的零寫入整合尚未驗收。

Receipt 原始 bytes 須符合 caller 外部提供的 digest；這只 pin 本次供驗 bytes，不能倒推 capture 當時原件。Manifest 由外部 registry version 與 canonical digest 雙 pin，還要符合 `local_fetch`／`raw_store` policy。Verifier 比對 registry 與 receipt 的 source／endpoint／GET method／`source_version`、profile、body 長度／SHA、policy／attribution／condition receipts、2xx HTTP 狀態及 timestamp 順序。全列 body 解析須符合唯一 symbol、同一交易日期；selected row 再驗 OHLC 合法性、數值 TradeValue 與精確整數 volume，close／volume 同時對上 sealed bar 與 actual evaluator arguments。成功才回 detached `schema_version=stock-day-selected-bar-evidence/v1`、`verdict=local_evidence_consistent`、`scope=selected_bar_only`，連同指定 attempt／ordinal、snapshot／body／receipt hashes、registry pins、raw id、symbol／date／close／volume；不回 prior volumes 或改寫 `raw_bytes_verification`。

拒絕以 `StockDayEvidenceError.code` 表示；下列是本入口／helper 已具名的主要分組，不能將拒絕改成 evidence pass：

| 邊界 | 具體拒絕碼 |
| --- | --- |
| Snapshot／選取 | `expected_snapshot_sha256_required`、`invalid_attempt_id`、`invalid_ordinal`、`snapshot_invalid`、`capture_invalid`、`ordinal_not_found`、`unsupported_capture_kind`、`evaluator_not_selected_strategy`。 |
| Raw 關係／來源 | `raw_fk_missing`、`selected_bar_provenance_invalid`、`source_identity_mismatch`、`raw_digest_missing`、`body_hash_mismatch`。 |
| 檔案／穩定讀 | `body`／`receipt`／`manifest` 前綴的 `*_path_invalid`、`*_path_alias`、`*_alias_check_unsupported`、`*_not_regular`、`*_size_limit`、`*_changed`、`*_unreadable`；body／receipt 還有 `*_path_protected`，另有 `file_identity_unavailable`、`evidence_changed`、`manifest_invalid`。 |
| 外部 pin／receipt | `expected_receipt_sha256_required`、`receipt_hash_mismatch`、`registry_pins_required`、`registry_pin_mismatch`、`registry_source_mismatch`、`registry_policy_rejected`、`receipt_invalid`、`receipt_pin_mismatch`、`receipt_http_status_invalid`、`receipt_attribution_mismatch`、`receipt_conditions_mismatch`、`receipt_timestamp_invalid`。 |
| Body／selected row | `evidence_size_limit`、`body_invalid`、`market_date_mismatch`、`selected_symbol_missing`、`selected_row_invalid`、`selected_bar_value_mismatch`、`evaluator_projection_mismatch`。 |

本輪驗收僅有統籌接受的程式靜態 review 與使用者在統籌 task 回報的 12 項直接執行 unittest；案例以純記憶體 payload／helper 和 mock 檔案控制邏輯為主，詳見[協作紀錄](TASK_COORDINATION.md)。尚無真實檔案、SQLite、公開入口端到端、sidecar／實際零寫入或競態整合證據。大整數 volume 只在 helper 案例成立，不能外推既有 sealed reader 的 canonical integer 範圍。`local_evidence_consistent` 也不證官方真實性、上游修訂版本、availability、歷史 decision／PIT；既有 `bytes_unverified` 不變，缺 FK 仍按 v2／v3 契約維持 unknown，prior volumes 不升格。下一步尋找已授權可唯讀的現存 research snapshot／body／receipt／registry pins tuple 做獨立 verifier 整合；缺 specimen 或 pins 時保持待驗，不建附件或 fixture。Consumer、paired replay 與預設切換另依其 gate。

## 11. 完成邊界

R0-B2／B2-persist 仍需：

1. Bridge B adapter、selected bar 與 prior volumes 本地 metadata 接線只已有限 review；相關回歸尚待補，見[協作紀錄](TASK_COORDINATION.md)。獨立 `STOCK_DAY_ALL` selected-bar verifier 已有上述有限成果，但真實檔案／snapshot 整合、歷史原件／來源版本、其餘衍生輸入及 availability／historical decision time 仍待證，再依共同依賴驗同一 snapshot 隔離 legacy／v2 paired replay；prior volumes 未升格。
2. API list/detail/action、DecisionSummary 與明確版本選擇。
3. 前端 non-probability 與 legacy/new 並列，且不得隱式切預設。
4. B3-wire、B5b availability／PIT gate 與 B7 paired replay review。

Schema、digest、receipt、fixture 或單元測試不能取代上述條件；B7 review 前不得自動切換預設版本。
