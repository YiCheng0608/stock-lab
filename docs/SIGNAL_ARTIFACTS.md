# Signal artifact 持久化契約

更新：2026-09-16。本文件只負責 `signal-artifact/v1` local store、Bridge A 已證邊界與 B adapter 提案。離線 comparison、pure-rule replay 與 worker capture 是分離能力；R0-B2 整體仍未完成，狀態以 [ROADMAP](ROADMAP.md) 為準。

## 1. 範圍與不變條件

- 新 artifact 與 legacy `signals.signal_key` 使用不同 namespace；不得更新 legacy 列或只補 evidence marker 冒充雙版本。
- Store 不註冊 legacy ORM metadata、不是 Alembic revision、沒有預設 DB path，也不寫 legacy signal／evaluation／settlement。
- Rule-only `confidence=null`；semantics 固定為 `signal-confidence/v2`、`not_calibrated`、`is_calibrated=false`、`is_probability=false`。不得把固定值、raw score 或 unknown numeric 稱為機率。
- Input／implementation refs 只保證 caller-provided shape 自洽，固定標 `caller_provided_only`／`not_officially_verified`；digest 不證來源、內容或 availability truth。
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

Child read 會重驗全部 ancestors 的 core／revision identity、payload／seal、binding、feature refs、lifecycle 及 attempt/run relation；任何 ancestor 或 relation 損壞都拒絕。Legacy comparison 由 [SIGNAL_COMPARISON](SIGNAL_COMPARISON.md) 提供；worker capture 由 [WORKER_ANALYSIS_CAPTURE](WORKER_ANALYSIS_CAPTURE.md) 提供，兩者都未連入本 store。

## 8. 驗收矩陣

| 面向 | 核心驗收 |
| --- | --- |
| 建立／重開 | Fresh external DB 建 root；reopen exact keys、seal、revision、generated time 相同；拒絕 protected／foreign／unknown stores。 |
| 信心／時間 | confidence null＋canonical semantics；earliest execution null＋固定 reason；拒絕 0.75、naive／date-only 升格。 |
| Retry／collision | Idempotent retry 保留首次 generated time；attempt/run 基數正確；same identity different payload、relation tamper 或 precommit failure 全 rollback。 |
| Binding／root | Binding 可跨研究 subject 使用但不可換 config／implementation；不同研究輸入建新 root，同 core 不同 result collision。 |
| Lifecycle／concurrency | 只允許 active→withdrawn 線性鏈；拒絕 branch、cycle、錯 parent／time；競爭只一個 child 成功。 |
| Reader | Exact／filtered read 唯一；拒絕 latest fallback、無 filter list、ambiguous／damaged ancestor 或 relation。 |
| 相容性 | 不寫 legacy／正式 DB，不接 worker／API／UI；fixture 不證 official truth。 |

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

## 10. Bridge A 可證映射與下一候選

Bridge A 的有限 source／graph review 確認：`read_analysis_attempt` 依 exact attempt fail-closed 驗 owner、schema、seal、count、ordinal、pair、Signal／strategy linkage 與 private replay；單一 selected call 可證 evaluator 實際收到的 arguments／result、subject、觀測 market date、selected strategy config／version、legacy Signal snapshot及 receipt 所記 collection run。這只證 capture 內部一致；沒有逐輸入 raw row／source version／availability，owner SHA 也只屬建立 owned DB 前的 source snapshot bytes。有限查核未見 worker、API、DecisionSummary 或前端產品接線；offline comparison 仍是分離 consumer。

下一個 B 候選是窄、無自動保存的 adapter；它仍是提案，最終 I/O、time、binding 與必要磁碟驗收範圍由後續統籌核定：

| 明示輸入／輸出 | 候選映射 | 不可擴張的邊界 |
| --- | --- | --- |
| Stable current research snapshot path＋expected SHA、exact attempt＋ordinal | 在同一穩定 snapshot strict 驗完整 attempt，再選 exact ordinal；evaluator 必須等於 `selected_strategy.name`。 | Current research SHA 與 owner original-source SHA 分開；後者不可冒充當次 input hash。 |
| Selected call | `input_snapshot.id` 綁 database id／attempt／ordinal；hash 只封 canonical input-only manifest：mapping schema、subject/date/strategy/evaluator、arguments、config／pinned evaluator binding 及明示 upstream refs。 | Manifest 排除 captured/receipt time、status/result；owner DB hash只能作 upstream container reference。 |
| Caller 明示 aware `decision_at` | 代表這次新研究採用時間，且不得早於 selected call 與 receipt 的 `captured_at`。 | 只證時間先後；不得由 observed date、legacy `data_cutoff`／`created_at` 或 captured time 回推歷史 decision，也不證 availability／PIT。 |
| Selected legacy Signal＋actual evaluator result | `status` 只保存 observed legacy snapshot status；`rule_state` 分開保存 actual result。Ruleset 用 selected config；confidence、`as_of_at`、`earliest_execution_at` 為 null，earliest reason 仍用固定值；basis unknown、feature refs 空。 | 不是 v2 status／levels 重算或 legacy-v2 paired replay。Pinned `domain-rules/v1` 只綁 evaluator；adapter、pipeline、legacy status／levels 未被該 digest 覆蓋，必須列 dependency unknown／missing，不得稱完整 worker implementation 可重算。 |
| Capture／receipt 原文 | 在 `rule_evidence` 保存 exact canonical JSON opaque string；call 沿用已驗 digest，receipt 只能把重算值明標 derived seal。 | 不直接 nested decoded payload：artifact canonicalizer 會遞迴轉換 `*_at`，且 legacy naive `created_at` 會被拒絕或破壞原 bytes／seal。 |
| Candidate mapping | Adapter 只回 candidate；caller 才能另外呼叫既有 `SignalArtifactStore.save_artifact` 並明示 attempt/run。 | 不自動寫 store、不接 default worker／consumer、不切版本。 |

候選必須在 current hash／stable snapshot 不符、attempt 任一列損壞、ordinal 不存在、evaluator／selected strategy 不同、subject 需 trim／case 變形、ruleset／implementation pin 不符、input manifest digest 不符，或 decision 缺失、naive、早於 capture 時 fail closed。Unknown source／availability 必須保留 reason，不能因 digest、receipt 或新 decision time 升格為已驗證。

## 11. 完成邊界

R0-B2／B2-persist 仍需：

1. 實作並 review 上述 explicit capture→candidate adapter，再把 inputs 接到可證 source／availability／historical decision time，並在同一 snapshot 執行隔離 legacy／v2 paired replay。
2. API list/detail/action、DecisionSummary 與明確版本選擇。
3. 前端 non-probability 與 legacy/new 並列，且不得隱式切預設。
4. B3-wire、B5b availability／PIT gate 與 B7 paired replay review。

Schema、digest、receipt、fixture 或單元測試不能取代上述條件；B7 review 前不得自動切換預設版本。
