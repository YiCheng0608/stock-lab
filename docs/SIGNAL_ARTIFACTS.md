# Signal artifact 持久化契約

更新：2026-09-13。狀態：**已 review（Round12 C012 有限本地 foundation；Round32 C032-B 有限離線 comparison library；Round33 C033-B 有限 caller-provided current pure-rule replay library）**。

本文件固定 R0-B2／B2-persist 的獨立 signal artifact foundation。Round12 C012 已實作並 review `signal-confidence/v2` rule-only 結果的純契約、immutable revision 與明確 opt-in 的本地 SQLite store；Round32 C032-B 再加入明確 opt-in、專案外雙 snapshot 的 exact legacy／new 描述性 comparison library；Round33 C033-B 另加入不接 store、只處理 caller-provided current rule arguments 的 capture/replay library。三批都不改 legacy `signals`、evaluation／settlement、worker、API、UI、Alembic 或正式資料庫。ROADMAP 是能力狀態唯一權威；這些有限能力通過不代表 B2 或 R0 已完成。

## 1. 範圍與不變條件

- 新 artifact 與 legacy `signals.signal_key` 使用分離 namespace；不得以更新同一列、擴充 legacy key 或只補 `rule_evidence_json` marker 冒充雙版本並存。
- C012 不寫 legacy signal、原始 `confidence=0.75`、evaluation 或 settlement。新 store 不註冊 legacy `Base.metadata`，不是 Alembic revision，也沒有預設 DB 路徑；正式 DB 不變，`.local` 的外部 task 例外另見第 9 節。
- 本段的新 rule-only `confidence` 必須為 `null`；confidence semantics 固定為 `signal-confidence/v2`、`not_calibrated`、`is_calibrated=false`、`is_probability=false`。不得把 raw score、固定常數或未知 numeric 值改名為機率。
- 本段只保存 caller-provided、結構自洽的 input source 與 implementation references；固定標示 `caller_provided_only`／`not_officially_verified`。digest shape 或 canonical projection 通過不代表官方來源、實際 availability 或內容真實性已驗證。
- 本段不接交易 session／PIT gate，所以 `earliest_execution_at` 一律為 `null` 並帶明確 machine reason。不得從 legacy `earliest_execution_date`、`data_cutoff`、date-only 欄位或 naive `created_at` 推導 instant。

### 1.1 Canonical 最小 shape

「strict」必須落到可驗證的 type、required field 與 enum，不得只接受任意 JSON scalar／object：

- mapping 的 `contract` 若省略或為 `null`，normalizer 會填入 `signal-artifact/v1`；若提供 non-null 值則只能是該版本，未知版本拒絕。caller-facing `SignalArtifact` dataclass 本身沒有 `contract` 欄，轉成 canonical mapping 時同樣補入該固定版本。若同一欄位有 nested／flat alias，兩者同時出現時必須 canonical 後完全相等；矛盾 alias 或未列入契約的頂層欄位一律拒絕，不能靜默忽略。
- `signal_output_semantics` 固定為 `version=signal-confidence/v2`、`kind=rule_only`、`is_calibrated=false`、`is_probability=false`；不得只檢查字首 `signal-`，也不得接受缺 version、任意 probability 宣稱或布林值的 `0`／`null` 替代。
- `confidence_semantics` 固定沿用既有 canonical v2 集合：`version=signal-confidence/v2`、`kind=not_calibrated`、`is_calibrated=false`、`is_probability=false`、`display_label_zh=未校準；非預測勝率`。writer 重建 canonical 值，不信任 caller 自報的 kind、label 或額外欄位。
- `ruleset_snapshot` 是 non-empty object，並由其 canonical JSON 重算 digest；`null`、scalar、array 或空 object 不代表規則設定。
- `basis_manifest` 至少是 `{mode, verification, status, value, reason}` object。`mode=caller_provided_only`、`verification=not_officially_verified` 固定；`status=provided|unknown|unavailable`。unknown／unavailable 必須 `value=null` 且帶 non-empty machine reason；provided 必須有 non-empty value，但仍不得升格成官方 truth。
- dependency／input-source manifest 至少是 `{mode, verification, references, unknown_reasons}` object；前兩欄固定為 caller-only／未官方驗證，後兩欄分別是去重的 string arrays，且至少一方 non-empty。不得接受 `null`、scalar、空 object 或只靠 digest 的無內容宣告。
- implementation reference 至少是 `{mode, verification, ref, digest}` object；mode／verification 同上，ref non-empty，digest 為重算或比對過的 SHA-256。它與 version binding 保存的 implementation digest 必須一致。
- `earliest_execution_reason` 在本 slice 固定為 `execution_time_unavailable_without_pit_session_availability`，不接受任意文字替代 machine contract。

## 2. 三層識別：subject、research core、revision

識別分成三層，避免把不同研究輸入誤串成 revision，也避免用任意 revision number 繞過 collision。

### 2.1 Subject group

subject group 只供同日、同策略語意的查詢分組，至少包含：

- canonical instrument identity：normalized exchange＋symbol；
- `market_date`；
- strategy name＋strategy version；
- `signal_output_semantics_version`。

同一 subject group 可以有多個 research root。例如 input snapshot、as-of、basis 或 dependency 不同時，必須各自成為新 root，不能自動選其中一筆作 latest。

### 2.2 Research-core lineage

實作以完整 canonical **研究輸入 core** 導出 `lineage_key`，排除研究結果、revision 與使用紀錄。core 實際納入：

- contract 與固定 lineage subject；
- subject group 全部欄位；
- input snapshot id＋hash；
- 必填、含 offset 且 canonicalized 的 exact `decision_at`，以及 nullable `as_of_at`；`as_of_at` 有值時也必須含 offset 並 canonicalize；
- price basis 與 dependency digest；
- rule settings digest 與 implementation digest；
- 所用 feature artifact keys；
- caller-provided source／implementation mode，以及 nullable legacy reference。

規則 status／outcome、rule state/evidence、quality／missing reasons、nullable confidence 與 confidence semantics 屬 canonical research payload，不放入 research core。C012 沒有獨立 `levels` 欄；caller 若提供規則價位，只會作為 `rule_evidence` 內容被 canonical 保存。同一 research core 只能建立一個 lineage root，並不可變綁定一份 canonical research payload seal；相同輸入與版本卻算出不同結果時必須 collision，不能因結果不同自動得到新 lineage，也不能改 revision 或 append lifecycle revision 繞過。

只有 snapshot、as-of、basis、dependency、feature keys 等研究輸入不同時才建立新 research core 與新 root。settings 或 implementation 改變時，除了 core 不同，還必須先依第 3 節升級對應版本；不可只換 digest 而沿用原版本。

### 2.3 Revision 與 artifact identity

實際 canonical payload 以 positive integer `revision`、nullable `supersedes_artifact_key` 與 `lifecycle_state` 表達 revision；沒有另存 `revision_id` 或 `revision_kind` 欄。`revision=1` 且 `active` 可推導為 root，後續唯一允許的 `withdrawn` child 可由 revision、state 與 supersedes 關係推導。`lineage_key` 由 research core 穩定導出；`identity_hash` 則由同一 research core **再加 revision** 導出，不能誤稱為不含 revision 的純 input hash。`artifact_key` 再由該完整 revision identity 穩定計算；caller 若提供 `artifact_key`，normalizer／store 會核對而不是允許覆寫 canonical identity。

相同完整 identity 與相同 canonical payload 是 idempotent replay；相同 artifact identity 對應不同 payload 是 collision。不得改 revision number 將同一筆研究內容的矛盾 payload 偽裝成合法 research revision。

## 3. Strategy／semantics version binding

版本 binding key 固定為 strategy name＋strategy version＋`signal_output_semantics_version`，binding value 固定為 canonical rule settings digest＋implementation digest，並保存可重算的 canonical config／implementation reference。

- 同一 binding 可跨 instrument、market date、snapshot 與 as-of 使用；這些研究維度不得塞入 binding key，藉此讓同名版本實際對應不同設定或程式。
- 同一 binding 若收到不同 settings 或 implementation，必須以 version binding collision（`SignalArtifactCollisionError`）拒絕並全 transaction rollback；不得另記未實作的 machine reason code。
- 變更規則 gate、價位或執行行為時必須升級對應 strategy／execution version；只變更輸出 nullability／解讀時才使用新的 output-semantics version。
- binding 只保證 caller-provided version 與 digest 自洽，不證明 repository commit、官方輸入或部署版本真實。repository 無 HEAD 時不得捏造 commit SHA。

## 4. Canonical payload、generated time 與使用紀錄

canonical research payload 保存 research core 所產生的不可變研究結果與 provenance projection，至少包含規則 status／outcome、rule state/evidence、quality／missing reasons、nullable confidence 與 canonical confidence semantics；規則價位只有在 caller 放入 `rule_evidence` 時才保存，沒有獨立 `levels` 欄。store 另算 `research_payload_hash`；root 建立後，`lineage_key`、research core 與此 hash 的綁定不可變。payload 排除：

- `generated_at`；
- retry 的 `attempted_at`、`attempt_id`；
- `run_id` 與 run 使用關係；
- store 的 `stored_at` 或 response 組裝時間。

首次建立時的 `generated_at` 是 immutable 封存 metadata，必須是合法 aware instant；root 首次值不得早於 `decision_at`，lifecycle child 首次值不得早於該 child 的 `lifecycle_at`。它不參與 research core、含 revision identity 或 canonical payload hash。相同 artifact retry 即使傳入不同候選 `generated_at`，也回傳原首次值；retry candidate 只驗 aware timestamp shape，不替代已存值，也不得拿較晚候選值重新判定既有 lineage 的時間順序、誤判 collision 或改寫舊值。

attempt 與 run relation 另表追加，基數固定為 artifact 1:N attempts、run 1:N attempts，而每個 attempt 最多綁一個 nullable run；schema 以 `UNIQUE(attempt_id)` 或等價 constraint 落實 0:1 run 基數。同 artifact＋同 run 可以有多個不同 attempt，以保留實際重試／重用；相同 attempt＋相同 artifact/run/payload 才是 relation 冪等重放。同一 attempt 改綁其他 run、artifact 或 payload 必須衝突。relation identity 由 attempt＋run＋artifact 導出，strict reader 必須重算 relation key，並核對 payload hash、attempt FK／identity、0:1 基數及 relation time；不得以 `(run_id, artifact_key)` unique 誤把同 run 的第二次合法 attempt 當 collision，也不得讓 run id 與已存 relation key 分離。attempt 驗證、relation 寫入與 artifact commit 在同一 transaction，任何失敗不得留下 orphan row。

Python contract object 是 detached transfer snapshot，不等同於 SQLite row 本身。若 nested mapping／list 未遞迴 freeze，文件與型別不得宣稱它是 deep immutable：writer 必須在 transaction 前取得 canonical deep snapshot，reader 每次回傳新的 detached value；修改 caller input 或某次 read 結果都不能改 DB、cache 或下一次 exact read。直接 dataclass 建構與 mapping 建構在省略可重算 digest 時必須得到相同 canonical payload；若實作要宣稱 Python object 本身 immutable，則須遞迴 freeze nested values 並另有測試。

## 5. Lifecycle revision

不可變 rule result 與 lifecycle state 必須分開。本段的最小 lifecycle 只允許：

```text
root: active -> lifecycle revision: withdrawn
```

- root 的 lifecycle state 固定 `active`；lifecycle child 只能為 `withdrawn`，而且 withdrawn 是終態。
- withdrawn revision 必須沿用完全相同的 research core／`lineage_key` 與 `research_payload_hash`，並明示 predecessor artifact key、machine-readable reason 與含 offset 的 lifecycle time。
- lifecycle time canonicalize 後不得早於 `decision_at` 或 root 已持久化的首次 `generated_at`；child 自己的首次 `generated_at` 則不得早於 lifecycle event。pure validator 看不到 parent 的 stored time，跨 artifact 順序必須由 store 在同一 transaction 查 parent 後驗證，不能拿 retry candidate 代替 root 首次值。
- 本段不建立 observation、conditional、triggered、filled、target-hit、invalidated、settled 等交易／追蹤狀態；既有 domain transition 不自動成為本 store 的允許集合。
- lineage 僅允許線性 append：每個 research core 最多一個 root，每個 parent 最多一個 child；缺 parent、跨 research core／payload seal／subject／strategy／semantics parent、branch、cycle、由 withdrawn 再追加都拒絕。
- 兩個 connection 同時對同 parent append 時，SQLite constraint 與 transaction 必須保證最多一個 child 成功；另一個回傳明確 conflict 或 bounded retryable busy，不得形成 branch。

## 6. Store ownership、transaction 與不可變性

`SignalArtifactStore(explicit_path)` 只接受呼叫端明示、專案外的專用 SQLite 路徑。實作至少遵守：

- 拒絕正式 `data/stock.db`、專案 `.local`、整個 resolved workspace 內路徑、其符號連結／hard link／junction alias、既存空 DB、foreign DB 與未知 store version；path protection 先於 file create/open，既存檔再以 read-only ownership preflight 先於任何 write-capable connection 或 DDL。拒絕後 DB 與既有 `-wal`／`-shm`／`-journal` sidecars 的 bytes（平台可讀時）、size、mtime、schema 與內容不變；不能只因使用 `mode=ro` 或普通 `BEGIN` 就推定沒有 side effect。
- store schema version 與 Alembic revision 分離；不修改程式 head、fallback markers、API lifespan 或 `worker.cli init-db`。
- `PRAGMA foreign_keys=ON`，parent／revision／binding／attempt-run 關係由 constraint 保護；artifact、binding、relation rows 以 UPDATE／DELETE／`INSERT OR REPLACE` triggers 保持 append-only。no-replace predicate 必須**同時**涵蓋既有 `rowid` 與各表全部實際 primary／unique identity，不能修一邊卻移除另一邊，也不能假設 `recursive_triggers=ON`；否則明示舊 rowid 但改全部 declared keys，或未明示 rowid 的 `INSERT OR REPLACE ... SELECT *`，仍可能替換舊列。這不冒充對可修改 schema 或停用 trigger 的惡意管理者防護。
- write 使用 `BEGIN IMMEDIATE`，並在 COMMIT 前由保存列重算 artifact／lineage key、含 revision identity、payload seal、binding、feature／lifecycle、attempt／run 與 parent 關係。create 與 idempotent replay 共用相同的 pre-commit hook／寫後驗證 gate；replay 不得在記錄 attempt 後直接 COMMIT 跳過。validation、collision、version binding、child、attempt、relation 或 commit precheck 任一失敗都回滾整筆 transaction。
- database locked 轉成 bounded retryable error；呼叫端重試同一 save operation，不得在 store 內改 identity 或偷偷 fallback。

最小概念表可分為 version bindings、research-core lineage／artifact revisions、attempts 與 run relations；實際表名不是契約，但每類 row 的 ownership、唯一性、FK、seal 與 rollback 行為都必須能獨立驗證。

## 7. Exact reader 與 selector

reader 只提供明確 selector。C012 實際的 `get_exact` 支援 exact `artifact_key`、exact `identity_hash`，或 exact `lineage_key`＋`revision`；多個 selector 同時提供時會合併成同一精確查詢。

- 不提供 implicit latest、最大時間、`<= as_of`、第一筆或單純同日 fallback。
- exact key 零筆可回 `null`／not-found；缺少必要 selector、候選多筆、cross-identity、version/binding mismatch 或 stored seal 不一致必須 fail-closed。
- `list_artifacts` 只在 caller 明示 `lineage_key`，或至少一個實際支援的 subject filter（strategy name、market date、exchange、symbol）時列出 candidates；可再搭配 strategy version／revision。它不替 caller 選預設；完全無 lineage／subject filter 時拒絕，不得默認傾倒全 DB。`history` 則要求 exact `lineage_key`。
- child exact read 必須重驗整條 ancestor chain 的 stored payload／seal、research core／revision identity、parent payload seal、binding、feature refs、lifecycle 與 attempt/run 關係；任一 parent 或 relation 缺漏／矛盾時，child 也 fail-closed。
- 就 Round12 C012 本段而言，沒有 legacy reader、legacy/new comparison、API list/detail/action projection 或前端選擇政策。Round32 已以分離 library 補上有限 exact legacy reader／comparison；其 actual API、missing／hard-error 與不可比邊界見 [Signal comparison 離線唯讀契約](SIGNAL_COMPARISON.md)。API／UI／worker 選擇政策與完整 replay 仍是 B2 後續工作。

## 8. 驗收矩陣

| 面向 | 必須通過 | 必須拒絕／保持不變 |
| --- | --- | --- |
| 建立與重開 | fresh 專用 DB 建 root；關閉重開後 exact read 的 artifact／lineage key、revision identity、payload seal、generated time 一致。 | existing empty／foreign／unknown version、正式或 `.local` 路徑與 alias 不得被初始化。 |
| 信心與時間 | rule-only confidence 為 null 且 semantics canonical；earliest execution 為 null＋固定 machine reason。 | 0.75、raw score、legacy date／naive time 不得被提升成 probability 或 execution instant。 |
| Retry | 相同 identity/payload 重跑回既有 artifact 與首次 generated time；同 artifact＋run 可追加多個不同 attempt，相同 attempt＋artifact/run/payload 冪等；reader 重算 relation key。 | retry candidate generated time 不得改 payload/hash；同 attempt 改綁 run/artifact/payload 或 relation key/run id 分離時拒絕；replay precommit hook 失敗須連新 attempt/relation 全 rollback。 |
| Collision／rollback | same identity same payload idempotent。 | same identity different payload、invalid attempt/time/precommit seal 失敗後 artifact/core/binding/attempt/relation 各表皆不增不改。 |
| Version binding | 同 strategy＋semantics＋settings＋implementation 跨 instrument/date/snapshot/as-of 成功。 | 同 binding 換 settings/config 或 implementation 必須以 `SignalArtifactCollisionError` 拒絕並 rollback；不得用研究維度擴大 binding key 規避。 |
| Research root | 同 subject 下不同 snapshot/as-of/basis/dependency/feature keys 各自建立可精確區分的 root。 | 同 research core 的不同 research result 必須 collision；不可用新 revision 或 lifecycle revision 改 research payload。 |
| Lifecycle | `active -> withdrawn`，reason 與 aware time 合法；reopen 後 lineage/seal 一致。 | backward、withdrawn 後追加、缺 parent、跨 lineage、branch、cycle、過早或 naive lifecycle time 拒絕。 |
| Concurrency | 雙 connection 同 identity 只建立一筆；同 parent 競爭最多一個 child。 | 不得產生重複 root、branch 或 orphan attempt/relation。 |
| Reader | exact key／完整 selector 得到唯一版本；明示 lineage 或至少一個實際支援的 subject filter 時可列舉 candidates；child read 重驗 ancestor 及 relation seals。 | ambiguity、mismatch、無 lineage／subject filter 的全庫 list/history、latest／`<=asof`／first fallback 拒絕；parent payload/seal/refs/lifecycle/attempt-run 任一損壞時 child 不得讀出。 |
| 相容性 | C012 不寫 legacy signal／evaluation／settlement；正式 DB 不變；完整 backend 與本段 targeted tests 通過。 | 保護結果不得寫成 41／41；`.local` 外部 task 例外按第 9 節歸因。不接 worker/API/UI、不因本地 fixture 宣稱 official truth 或 B2 完成。 |

## 9. Round12 C012 final review 證據與限制

final source SHA-256：`backend/app/signal_artifact.py`=`F8B6B56853E08FF263498E96E12A402AEBB1500F5CC5847C9DDFAECEEF14A2D9`、`backend/app/signal_artifact_store.py`=`DD3CF18C64A5B848F43110B32FA51CDA7517304E0D785DEA6B1876D2F635E620`、`backend/tests/test_signal_artifact.py`=`A821EDD0F0FF50204F6F38DA889A0DEF2F18C683A03905BA4AE1CDC4ADBC77E7`、`backend/tests/test_signal_artifact_store.py`=`C8EF20AB672AC7CF4896A1F902E627FB38C950B43D958C051FD57CD70E2BE319`。

統籌使用 bundled Python 3.12.14、true Alembic `PYTHONPATH` 與專案外 Temp 資料環境完成完整 backend：285 passed、4625 warnings、16.95 秒、exit 0；另有獨立矩陣 45／45。程式作者 final targeted 為 26 passed／1.56 秒、完整 backend 為 285 passed／4625 warnings／17.29 秒。文件角色以相同隔離原則重跑兩個 C012 test 檔，為 26 passed／1.57 秒、exit 0；另以專案外 `crossreview.py` 完成 contract rejection、mapping/dataclass canonical 等價、detached nested mutation、foreign WAL／DELETE journal ownership、attempt/run 基數、ancestor damage 與 run relation tamper 的獨立查驗。統籌證據位於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r12-coordinator-review/`；文件 cross-review 位於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r12-d014-review/crossreview.json`（SHA-256 `DF1AA2DEFE166A52187EC1888A6398251022E6F13F7DDD79FC76039C3C73B828`）。

保護目標結果必須精確描述為 **40／41 unchanged**。正式 `data/stock.db` 保持不變（296,054,784 bytes，hash 記錄為 `74A34389…32D6`），本輪沒有正式 migration。唯一例外是 `.local/data/stock.db`：另一個服務 task `執行前後端專案`（task `01a0913c-797b-7863-a5a6-5f47f469bc9b`）依使用者另行要求在 09:27 啟動 lifespan `init_db`，使其由 baseline 425,984 bytes／`306D9D81…E39A9` 變成 438,272 bytes／SHA-256 `87453D7B29954B6D506F8020B8987F321AA6749CE9BC24FBEF695DD3874B8D02`，mtime `2026-09-12T01:27:28.7179604Z`，revision 狀態進至 0006。統籌其後以 `mode=ro`／`query_only` 查驗，兩個 News JSON defaults 皆為 `[]` 且讀前後 hash 穩定。這是可歸因的外部 scope 變更，不是 C012 寫入、部署或 migration 驗收；因此不得聲稱 41／41 全不變，也不得外推 `.local` 所有歷史列均由 C012 preservation test 證明。

## 9.1 Round32 C032-B：有限 offline exact comparison

Round32 新增 `backend/app/signal_comparison.py::compare_signals`／`comparison_json`，並只在既有 store 增加支援的 `SignalArtifactStore.open_readonly`。呼叫端必須提供兩個專案外 absolute rollback-mode SQLite snapshot、各自 expected SHA-256、opaque exact legacy `signal_key` 與 exact artifact selector；多個 new selector 以 AND 合併，沒有 latest／subject fallback。兩側 zero row 是 structured missing；schema、primitive、FK、evidence、ownership 或 selected／ancestor／relation integrity 異常則 hard fail，malformed SQLite 可能直接拋 `sqlite3.DatabaseError`。

兩個 path/hash/sidecar/WAL-header preflight 都在任一 SQLite-open 前完成；讀取使用 `mode=ro`、`query_only`、deny-write authorizer 與各自 read transaction，並做前後 fingerprint。這只偵測 observed change：不是 active-writer／hostile-race 保護，也不是 cross-file atomic snapshot。URI、`:memory:`、workspace、`formal`、`.local`、symlink／junction／hardlink alias、same-file pair、sidecars 與 read/write header byte 2 都拒絕；library 不替 caller 建檔、backup、checkpoint、repair 或 migration。

report 固定 `signal-comparison/v1` 且 `comparable=false`。subject equal/different 與 raw status lexical equality都只描述選中資料；confidence、prices、evidence、quality、time、revision、inputs 保持 incomparable。new `legacy_reference` 與**requested** legacy key byte-for-byte 比較，即使 legacy row missing 也不改；既有 artifact normalizer 會 trim optional reference，所以帶空白的 opaque legacy key可能 exact 命中但 linkage 為 conflict。這不證 shared input、歷史 linkage、概率、價位 delta、availability、PIT、execution、winner、default 或 replay。

完整使用方式、result shape、error family、frozen hashes、Round32 evidence 與限制集中於 [Signal comparison 離線唯讀契約](SIGNAL_COMPARISON.md)。C012 第 9 節的 40／41 與 `.local` 外部 task 例外仍是 Round12 歷史證據，不由 Round32 回寫。

## 9.2 Round33 C033-B：有限 caller-provided current pure-rule replay

Round33 新增 `capture_rule_inputs`、`rule_replay_json` 與 `replay_rule_inputs`，只支援 `breakout_v1@1.0.0`／`pullback_v1@1.0.0` 的 exact complete arguments。Bundle 以 canonical JSON 保存 ordered histories、explicit null、完整 selected config、`RuleEvaluation` 的 `passed/state/ordered reasons`、`arguments_digest`、完整 source/config/runtime binding 與覆蓋其餘欄位的 `bundle_digest`；strict native JSON、1 MiB、16 container levels、10,000 history elements、finite number 與 ±(2^53−1) integer limits均 fail closed。

每次 operation 都核對完整 `domain.py` bytes SHA-256、兩個完整 config digests、CPython 3.12.14／binary64，並把同一批已驗 bytes 放進 fresh private module；不讀 shared `app.domain`、cached pyc、DB、worker 或 network。`rule_replay_json` 不呼叫 evaluator，但會 compile／exec source 核對 binding。Replay report 的 `exact_match` 只比較 recorded/replayed `passed`、`state`、ordered `reasons`；subject、market time、historical inputs、availability、PIT 與 full signal reconstruction 六項宣稱均明確為 false。

這個 bundle 目前沒有 instrument／market date／decision time，也不進 `SignalArtifactStore`。`arguments_digest` 是 evaluator＋arguments 的 content identity，不是本文件第 2 節的 research-core、input snapshot hash、artifact identity 或 authentication；current-rule replay 通過也不能證明 C012 artifact 曾用相同輸入產生。完整 API、schema、error families、source hashes與驗收證據見 [Rule replay 契約](RULE_REPLAY.md)。

## 10. 完成邊界

即使上述 foundation、有限 offline comparison 與 caller-provided current pure-rule replay 經 review，R0-B2／B2-persist 整體仍未完成。後續至少還需要：

1. 把可證 subject/time/source/availability 的完整保存輸入連到 artifact／worker，並以同一 snapshot 實際執行隔離的 legacy／v2 paired replay；Round32 只讀既存兩側，Round33 只 replay caller 提供的 current pure-rule arguments，兩者都不能證明 artifact 輸入相同或完成 paired replay；
2. API list/detail/action 與 DecisionSummary 的明確版本選取；
3. 前端非機率呈現、legacy/new 並列及無隱式預設切換；
4. B3-wire、B5b 官方 availability／PIT gate 與 B7 paired replay review。

foundation 的 schema、caller fixture、HTTP 可讀或單元測試不能縮小這些既有 ROADMAP 條件；預設版本在 B7 review 前不得自動切換。
