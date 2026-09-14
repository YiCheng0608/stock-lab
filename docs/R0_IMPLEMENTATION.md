# R0 實作與驗收契約

更新：2026-09-14。本文件定義 [ROADMAP](ROADMAP.md) R0-1～R0-5 的實作與驗收邊界；優先順序與能力狀態仍以 ROADMAP 為唯一權威。任何小批「已 review」只代表本文件明列的有限範圍，不代表 R0、B2、B3、B5 或 B7 整體完成。歷史逐輪 log、hash 與 Temp 路徑可由 Git 基準 `69f62cf7b9e9003c3878952cc33636ed9a063865` 查閱。

## 1. 狀態語意與使用規則

| 標記 | 意義 | 最低證據 |
| --- | --- | --- |
| 提案 | 契約已定義，對應實作／資料變更尚未存在。 | 輸入、輸出、失敗行為、驗收案例。 |
| 已實作 | 程式已存在，尚未完成獨立 review。 | 變更路徑、版本、實跑結果與未跑／失敗項。 |
| 已 review | reviewer 已重現關鍵案例並接受有限範圍。 | 日期、隔離環境、版本、命令結果與限制。 |

實作者只能標「已實作」；reviewer 才能標「已 review」。ROADMAP 狀態由統籌核定、文件角色更新，不能由本文件的批次名稱推論。

目前邊界：B1、B3 純核心、B3-persist、B4a、B5a 的 local foundation／read-time projection，以及 R0-5 的若干 finite migration／startup slices 已 review；B4b、B5b 與 B7仍是提案。B2 已有四個互相分離的 slices，但 SignalArtifact bridge、official source／availability／decision time、legacy-v2 paired output、API／UI/default、PIT 與 B7 未完成，所以 B2 整體未完成。正式 worker 仍使用 legacy ATR；正式資料修復、正式 artifact、預設版本切換與策略有效性均未完成。

## 2. 靜態基線與共同不變條件

歷史 legacy 基線仍是：worker `_calculate_features` 的 `atr14` 為最近最多 14 根 `high-low` 算術平均；`_risk_levels` 使用 `max(atr or entry×2%, entry×1%)` 並產生 1.6R／3R；`TechnicalFeature` 以 instrument＋date 唯一且 `features_json` 可更新；`Signal` 保留 nullable confidence、字串 `data_cutoff` 與 date-only `earliest_execution_date`。C-001 改新 confidence 語意，C-002 新增未接線的 `technical_v2_atr14_wilder`，都沒有覆寫上述 legacy 路徑。

所有 R0 批次共同遵守：

1. 不改寫 `breakout_v1`、`pullback_v1`、`hot_group_v1` 或既有 run 的歷史語意與結果。
2. 公式、時間、價位、成本或輸出語意變更時，使用對應的新 feature／strategy／execution／prediction／signal-output／presentation version；舊、新輸出可並存。
3. 每筆輸出可回查實作版本或檔案 hash、設定、資料 snapshot／as-of、公司行動版本及 run id；沒有 HEAD 時記檔案 hash，不捏造 commit。
4. 缺值、不可證 availability、公司行動不可重建、非有限價格或資料斷層一律 fail-closed，不補 0 或選有利解讀。
5. 正式 DB、正式輸出與舊 run 只讀；migration、重算與比較先在具名隔離 DB 執行。

| 版本軸 | 用途 | 必須升版的變更 |
| --- | --- | --- |
| `feature_version` | ATR、均線、調整與 warm-up | 公式、平滑、期間、缺值或價格基礎。 |
| `strategy_version` | gate、rule evidence、signal lifecycle | feature、門檻、價位規則或狀態轉移。 |
| `execution_version` | T+1、成交、成本、tick、不可比 | 時間、費稅、滑價、撮合或優先序。 |
| `prediction_version` | target、model、calibration、scope | 任一預測定義或模型／資料版本。 |
| `signal_output_semantics_version` | rule-only confidence 與輸出 | gate 不變、只改欄位 nullability／解讀。 |
| `presentation_contract_version` | 使用者可見標籤與 legacy 解讀 | 呈現語意改變；不反寫研究資料。 |

## 3. 小批交付順序

下表把歷史驗收濃縮為「記錄截止／有限接受範圍／仍未完成」；不同 run 的 pass counts 不相加，也不當成目前 checkout 的驗證。

| 批次 | 記錄截止 | 有限接受範圍 | 仍未完成 |
| --- | --- | --- | --- |
| D-001 | 2026-09-11 | 文件契約 | 程式能力。 |
| B1／C-001 | 2026-09-12 | 新 rule-only confidence=null、legacy 0.75 安全解讀、API/UI 非機率標示 | 雙版本 artifact、正式回寫、prediction calibration。 |
| B3／C-002 | 2026-09-12 | `technical_v2_atr14_wilder` 純核心與 fail-closed 案例 | worker、來源 truth、持久化接線、paired replay。 |
| B3-persist／C-004＋C-006 | 2026-09-12 | schema 1 local ATR store、strict caller-provided provenance、legacy＋兩 as-of 唯讀比較 | worker/API、official truth、PIT、B7。 |
| B4a／C-005 | 2026-09-12 | legacy 規則參考價的 read-time API／UI semantics | B4b trade plan、tick/gap/cost/liquidity/PIT。 |
| B5a／C007＋C008 | 2026-09-12 | `time-evidence/v1` local store與 `product-time/v1` read-time projection | store-product linkage、source truth、worker、B5b。 |
| R0-A2／C010＋C011 | 2026-09-12 | synthetic recovery mechanics、News JSON defaults parity 與有限 SQLite atomic regression | 所有 historical schema parity、正式 restore／deployment、non-SQLite。 |
| B6／C-003 | 2026-09-12 | 正式 DB 歷史唯讀狀態、外部 copy／fresh DB upgrade與 preservation | 正式 upgrade；forward-only restore 未實跑。 |
| B2／C012 | 2026-09-12 | `signal-artifact/v1` local immutable store | legacy/new comparison、worker/API/UI/default、PIT、B7。 |
| R0-A3／C027-B | 截至 2026-09-13 | API startup finite readonly readiness | 完整 schema/data audit、正式 migration／restore／deployment。 |
| C028／C029 | 截至 2026-09-13 | instruments／settlements 的 finite canonical legacy SQLite rebuild、rollback、retry | 任意 legacy/custom schema、auto salvage、正式 migration。 |
| R0-A6／C030-B | 截至 2026-09-13 | settlement startup UNIQUE descriptor gate | arbitrary INSERT、CHECK/trigger/dependency audit。 |
| R0-A7／C031-B | 截至 2026-09-13 | instruments startup UNIQUE descriptor gate | complete writability、custom-schema repair。 |
| B2／C032-B | 截至 2026-09-14 | two-snapshot offline exact descriptive comparison | replay、shared-input／PIT truth、產品接線。 |
| B2／C033-B | 截至 2026-09-14 | caller-provided current pure-rule replay | historical inputs、subject/time、Signal reconstruction。 |
| B2／C034-B | 截至 2026-09-14 | opt-in worker actual evaluator input/result capture | SignalArtifact bridge、official time/source、paired output。 |
| B4b／B5b／B7 | 提案 | 契約見後文 | 實作與獨立 review。 |

## 4. R0-1：ATR 定義、公司行動與 warm-up

### 4.1 B3 第一段範圍與目標公式

C-002 的純核心版本是 `technical_v2_atr14_wilder`。所有價格先轉成同一、可追溯且在 `decision_at` 可得的 basis：

```text
TR_t = max(high_t-low_t, abs(high_t-close_{t-1}), abs(low_t-close_{t-1}))
ATR_14(seed) = mean(TR_1 ... TR_14)
ATR_14(t) = (ATR_14(t-1) * 13 + TR_t) / 14
```

seed 出現在第 14 個連續有效 TR；第 15 個才開始 recurrence。計算過程不逐根 rounding。若要 SMA、不同 period 或 precision，必須使用另一 feature version。這個 core 未接 legacy worker、API 或 DB。

### 4.2 序列、有效輸入與 fail-closed 狀態機

- `expected_sessions` 必須嚴格遞增並與 bars 配對；`decision_at` 必須含 offset。市場日期按 Asia/Taipei 判定。
- OHLC 與必要 previous close 必須是 finite positive，且 `low<=open/close<=high`。無效 row 不提供 recurrence或下一根可信前收。
- previous close precedence：連續 state close → calculator-level external previous close → row-level previous close → 只有在真正序列第一根、前三者皆未提供時才用 `high-low`。已選 evidence 無效時不能降級 fallback。
- 缺預期 bar、invalid OHLC、missing selected previous close、row basis conflict或 row availability 在 decision 後，會令該位置 null並清除 recurrence。恢復第一根若有合法 row previous close可開始 TR；否則只建立 close anchor，下一根才開始 TR。
- caller-confirmed suspended session 只有在無 bar／全空 marker 時可跳過，不注入 TR=0、不重啟。suspension 與任一價格並存是 `suspension_price_conflict`，清空 recurrence。復牌延續還要求跨期 basis/action/availability 可重建。
- 輸出須區分 warm-up、missing previous close/session、invalid OHLC、basis conflict、action evidence insufficient、future availability、suspension-price conflict與合法 non-trading assertion。

### 4.3 公司行動與缺資料

`corporate_actions` 是共同 `price_basis` 所需的完整 dependency manifest，不是只列 bar 日以前事件。coverage、source、version、basis與 `available_at<=decision_at` 都是強制 evidence。介面沒有 row／segment 到 action 的精確依賴映射，因此任一必要 action dependency partial／unsupported、缺 source/time、future、basis conflict或 factor 非有限／0 時，整個 artifact 的 TR／ATR 皆為 null；不能只令事件當日失效。

feature evidence 至少保存 price basis、完整 manifest/digest、factor source/version、`corporate_actions_applied_through`、raw refs 與 availability。無法重建時，下游 signal 為 `data_incomplete` 或 tracking 為 `incomparable`，不得使用 raw gap／1.0 fallback。新 ATR 必須進可與 legacy 同日並存的新 artifact/version，不能更新 `features_json.atr14`。

### 4.4 獨立手算驗收矩陣

| ID | 核心期望 |
| --- | --- |
| TR-01/02/03 | 無 gap 得 5；100→110/108 向上 gap 得 10；100→95/90 向下 gap 得 10。 |
| ATR-01/02 | TR=1..16 時 seed=`15/2`、S15=`225/28`、S16=`3373/392`，不得得到 rolling SMA 8.5／9.5。 |
| GAP-01 | 一般截窗首根無前收時 TR/ATR=null，只能建立 anchor。 |
| PREV-01 | 首根 row previous close 100、high 110、low 108 得 TR=10；若該 evidence無效，不得退回 high-low。 |
| GAP-02/03 | 缺日後無 row previous close 時第 14 個恢復 TR 在 S36；有合法 row previous close 則在 S35；兩例 ATR=3。 |
| HALT-01/02 | 合法停牌不注入 TR=0且復牌可依前 close續算；停牌＋價格衝突則 null並清空 recurrence。 |
| ACT-01/02 | 同 basis 除權例以 adjusted previous close 90 得 TR=2；future action dependency 令全 artifact null。 |
| BAD-01/BASIS-01/PIT-01 | 無效 OHLC、row basis conflict、必要 row evidence future 均依 §4.2 fail-closed；若是共同 action evidence 則全 artifact invalid。 |

### 4.5 純核心輸出與 review 邊界

入口為 `calculate_atr14(...) -> ATRArtifact`，aliases 為 `calculate_atr`／`compute_atr14`；主要型別是 `OHLCBar`、`CorporateActionEvidence`、`ATRObservation`。artifact 固定帶 feature version、algorithm、period、snapshot ref、price basis、aware UTC decision time、observations、action dependencies與全域 coverage，serialized output 標 `provenance_validation=caller_supplied_only`。純核心只驗 caller-provided metadata 的結構與一致性，不證來源官方、正式 persistence 或 B7 replay。

### 4.6 C-002 final review 證據與未完成邊界

2026-09-12 的有限 review 接受 Wilder 數值、gap／previous-close precedence、artifact-wide action failure、suspension conflict、aware decision time及不逐根 rounding；也確認 legacy worker未切換。未完成：官方 source truth、versioned persistence接線、worker/API、完整 replay／B7與瀏覽器驗收。這個歷史 review 不等於目前 full suite已重跑。

### 4.7 B3 持久化最小契約

artifact 必須與 mutable legacy `technical_features` 分離，至少保存 stable key、instrument、market date、feature/version、value/null＋reason、aware decision time、首次 immutable generated time、snapshot/hash、ordered refs、algorithm/config/implementation、basis、calendar/halt/previous-close及完整 action manifest。identity 要區分 instrument/date/version/snapshot/decision/basis/dependency/config/implementation；相同 identity＋相同 canonical payload為 idempotent replay並保留首次 generated time，payload不同為 collision。attempt與run relation另存，不進 canonical payload。

reader 使用 exact selectors，沒有 implicit latest／`<=as_of`。若 artifact與legacy位於不同 SQLite，不能宣稱跨庫 FK；須依自足 instrument identity與 provenance稽核。

#### 4.7.1 C-004 獨立 store 第一段契約（已 review：有限儲存段落）

`ArtifactStore(explicit_path)` 是 opt-in schema 1 SQLite store，沒有預設 path、不加入 legacy Base／Alembic／startup。既存 empty、foreign或 unknown-version DB在 mutation前拒絕。canonical instrument 是 normalized exchange＋symbol；nullable legacy reference不是 FK。parent、observations、dependencies、attempt relation單次 transaction保存；immutable triggers阻擋 UPDATE／DELETE／REPLACE。ordinary store只驗 caller-supplied最低結構與 digest，不證 official truth。

### 4.8 C-004 final review 證據與未完成邊界

2026-09-12 的有限 review 接受 schema/version ownership、aware UTC canonicalization、single-artifact atomic save、immutable rows、retry/collision、two-connection同 identity、exact reader與 legacy DB隔離。C-004 當時缺 strict provenance及 legacy＋兩 as-of比較，後由 C-006補齊；worker/API、來源truth、PIT與B7仍未完成。

### 4.9 C-006 provenance／compatibility final review 與完成邊界

C-006 使 C-004＋C-006 的有限 B3-persist 可標已 review；store schema仍為1。strict profile固定 name=`atr-provenance`、version=2、id=`atr-provenance/v2`、mode=`caller_provided_only`，instrument validation仍為 `caller_supplied_only`。

strict provenance 的固定頂層為 `contract`、`feature`、`instrument`、`source`、`algorithm`、`basis`、`calendar`、`sessions`、`halts`、`previous_close`、`company_actions`。writer／reader必須驗完整 snapshot＋ordered rows、instrument mapping、method/config/implementation、共同 basis、calendar/sessions/halts、每個實際 selected previous close，以及 action manifest/digest/coverage/source/aware availability。必要結構缺失在寫入前拒絕；`unknown`／`unavailable` 必須有 machine reason，且受影響 result只能為 null。`not_applicable`／`not_used` 要與計算路徑一致。manifest、basis與config digest由 canonical structure重算；外部 snapshot／implementation hash沒有原 bytes時只驗 algorithm與shape，不冒稱核真。

普通 schema 1 writer／reader保持舊 minimal行為；strict-like marker不能升格舊 artifact。`save_atr_artifact_strict`在 commit前重新讀驗，失敗令 parent/children/dependencies/attempts 全 rollback；`get_strict_by_key`／`read_strict`／`get_strict_atr`每次重驗。舊 key、seal、payload、generated time與rows不回填、不重算、不重分類。

`ArtifactComparisonReader`要求明確 legacy SQLite與artifact store paths。兩側均以 `mode=ro`／`query_only`讀 stable file；缺檔、live WAL/SHM/journal、ownership/schema mismatch或讀取中 fingerprint變化拒絕。legacy selector明示 instrument/date/row/snapshot/version；artifact以 key，或完整 version＋snapshot id/hash＋exact aware decision time選取。禁止 latest、最大時間或 first-row fallback。

report列 legacy、Wilder v2 A/B各自 value/null、reason、version、snapshot、basis、decision與exact ref，並對三個 pair分別給 comparability/reasons/delta。只有完整 signature相容且兩值非 null才有delta；legacy缺 persisted algorithm/as-of/basis provenance，所以 legacy-vs-new 固定 incomparable，但不阻塞相容的A-vs-B。comparison不寫DB，也不是B7。

## 5. R0-2：legacy confidence 與未校準預測邊界

### 5.1 欄位語意

| 概念 | 欄位 | 契約 |
| --- | --- | --- |
| data sufficiency | `data_quality`＋reasons | complete／partial／missing；不是 probability。 |
| rule state | `status`／`rule_state` | observation／conditional／data_incomplete；不是 probability。 |
| relation evidence | `relation_confidence` | high／medium／low／unknown；只描述關聯。 |
| calibrated prediction | `prediction.probability` | 只有 target、horizon、model、calibration與scope完整時才可0–1。 |

legacy strategy allowlist＋version `1.0.0`＋實值0.75才可輸出 `legacy_fixed_value`／`signal-confidence/v1-fixed`；其他 non-null是 `unknown_numeric`。兩者均 `is_calibrated=false`、`is_probability=false`，不顯示百分比、不進 ranking/gate/performance。新 rule-only signal寫 `confidence=null`與 `signal-confidence/v2`／`not_calibrated`；同 key舊非null值保留。uncalibrated model可保存 raw score，但 probability維持null。

### 5.2 C-001 實際相容行為與驗證

C-001 已在 domain、writer、API與frontend建立上述三種 canonical semantics；不信任 evidence自報 probability marker。它沒有 migration、沒有改策略 gate／價位／execution，也沒有批次洗掉歷史0.75。2026-09-12 有限 review接受 backend行為及新增前端語意；當時完整前端仍有一個與本改動無關的既存 presentation assertion failure，不能標整套通過。該過時期待後由C-002只改test修正，不回寫C-001當時的驗收結果。

### 5.3 B2：完整雙版本 artifact 與 replay

B2 要求 legacy與new使用不同 version key／namespace／artifact，不得在同一 legacy row補 metadata後繼續upsert。只有輸出語意改變可升 `signal_output_semantics_version`；gate／價位／execution改變則必須升 strategy／execution version。

完整驗收仍要求同 instrument＋date可同時查舊、新artifact或用完整舊輸入重放；legacy row/hash與0.75不變；new confidence=null；輸入相同時，除列明的output-semantics差異外，rule status、levels、quality一致。還須覆蓋 writer/replay、API list/detail/action、DecisionSummary、frontend與明確default policy。

C032只比較caller-selected snapshots，C033只重放caller-provided current pure rule，C034只捕捉actual legacy evaluator輸入／結果。三者都沒有證明 shared historical inputs、source/time/PIT或legacy-v2 paired output。

### 5.4 B2 持久化最小契約

實作細節以 [Signal artifact 持久化契約](SIGNAL_ARTIFACTS.md) 為準；comparison、pure replay、worker capture分別見 [SIGNAL_COMPARISON](SIGNAL_COMPARISON.md)、[RULE_REPLAY](RULE_REPLAY.md)、[WORKER_ANALYSIS_CAPTURE](WORKER_ANALYSIS_CAPTURE.md)。

新 signal artifact至少保存 instrument/date/strategy/output semantics/status/null confidence、feature keys、snapshot/hash、config、rule evidence、quality/reasons、dependency digest、aware decision time、首次 generated time與nullable earliest execution time；attempt/run relation另存。identity區分上述版本、snapshot、decision/as-of、basis/dependency/config/implementation。相同 identity同payload冪等；不同payload或version binding衝突 fail-closed。revision/supersedes immutable，legacy reference只作nullable link。

### 5.5 Round12 C012 final review 證據與未完成邊界

C012 的 `signal-artifact/v1` local store已有限 review：contract omission/null會補v1，未知non-null拒絕；lineage由research core導出，identity另含positive revision；root active、唯一next revision withdrawn＋supersedes；atomic save、version binding、attempt/run relation、exact／filtered reader與ownership/integrity fail-closed成立。價位只有caller放入 `rule_evidence`才保存。

未完成：SignalArtifact與worker/source/time bridge、legacy-v2 paired replay、API list/detail/action、DecisionSummary、frontend/default、official availability/PIT與B7。當輪保護結果是40／41 unchanged；唯一 `.local` DB差異來自另一個已授權preview task，不是C012成果，不能改稱全部不變。

### 5.6 Round32 C032-B offline exact comparison（有限 review）

`compare_signals`要求兩個 caller-provided external rollback-mode SQLite files、各自expected SHA-256、opaque exact legacy key與conjunctive exact artifact selector。兩側在open前檢查path/hash/sidecars/WAL header，read-only factory使用 `mode=ro`、`query_only`、deny-write authorizer、read transaction與前後fingerprint；不checkpoint、不用writer constructor。

report固定 `signal-comparison/v1`、`comparable=false`。subject/status/linkage只作lexical observation；confidence、prices、evidence、quality、time、revision與inputs保持incomparable。zero row是structured missing；duplicate、schema/ownership/integrity或cross-identity mismatch hard fail。本批不接CLI/API/UI/worker/default，也不做replay、PIT或truth驗證。

### 5.7 Round33 C033-B caller-provided current pure-rule replay（有限 review）

public API為 `capture_rule_inputs`、`rule_replay_json`、`replay_rule_inputs`，只支援 `breakout_v1@1.0.0`／`pullback_v1@1.0.0`。bundle保存完整 admitted arguments、ordered histories、explicit null、config、recorded `RuleEvaluation`，以 `arguments_digest`綁 evaluator＋arguments、`bundle_digest`綁 implementation/config/arguments/result claim。

binding固定完整 `domain.py` bytes、兩個config digests、CPython 3.12.14與binary64；每次 bounded-read/hash、compile/exec fresh private module並做identity-guarded cleanup。native JSON限制為raw/canonical各1MiB、depth16、history10000、integer±(2^53−1)、finite float，duplicate key/cycle/surrogate/nonfinite拒絕。report只比較 passed/state/ordered reasons，subject/time/historical/availability/PIT/signal reconstructed均false。本批不改 evaluator、schema、store、worker、API/UI/default或DB。

### 5.8 Round34 C034-B opt-in worker evaluation capture（有限 review）

`backend/worker/analysis_capture.py`與 `_analyze_session(db, capture=None)`可由caller明確opt-in，以external stable rollback-mode source snapshot＋expected hash建立owned research DB；同一transaction保存actual evaluator kwargs/result、subject/date/strategy、legacy Signal snapshot、R33 private bundle與sealed receipt。同ID只strict readback，new ID才建立新attempt與驗external paths/readiness。

default `analyze()`不捕捉。`observed_market_date`／`captured_at`不證decision、availability或PIT；legacy Signal不是SignalArtifact／prediction；上游group-member detail與lookup仍只按symbol，雙exchange同symbol測試不證group-excess provenance已exchange-aware。未完成範圍以 [WORKER_ANALYSIS_CAPTURE](WORKER_ANALYSIS_CAPTURE.md) 為準。

## 6. R0-3：規則參考價與新交易計畫

### 6.1 legacy 價位的強制標示

B4a只做read-time API／presentation semantics，不改worker、schema、legacy values或v1 rules。只有 `breakout_v1@1.0.0`、`pullback_v1@1.0.0` 可標 `level_semantics.kind=rule_reference`／`version=signal-level-semantics/v1`／formula `legacy-risk-levels/v1`；unknown strategy/version或缺relation則kind unknown＋machine reason，不能信任evidence自報marker。

legacy basis未持久化，所以 `price_basis.value=null`；historical `decision_at`與`generated_at`也為null＋reason。`response_generated_at`只代表API組裝時間。`cost_included=false`只表示level formula未扣成本，不否定execution/backtest另有成本假設。

| legacy欄位 | 正確標籤／角色 |
| --- | --- |
| `breakout_price` | 規則觸發價／`rule_trigger` |
| `pullback_low/high` | 規則回踩觀察區／`rule_observation_zone` |
| `reference_entry` | 規則計算參考價／`rule_calculation_reference` |
| `invalid_price` | 規則失效參考價／`rule_invalidation_reference` |
| `target_1/2` | 規則參考目標一／二／`rule_reference_target` |

v1 replay公式保持：`risk=max(atr if truthy else entry×0.02, entry×0.01)`；`invalid=max(0.01,entry-risk)`；targets為 entry＋1.6R／3R，最後round 2位。breakout entry為 `max(close, prior 20 highs max)`。pullback `reference_entry=round(close,2)`、`support=ma20 if truthy else close`、`zone_width=max((atr if truthy else close×0.01)×0.5,close×0.005)`、區間下緣有0.01 floor。

`PortfolioPosition.average_cost`／user stop、規則levels、tracking `execution_price`與cost assumptions必須分開；沒有execution origin時不能稱券商真實成交。full/compact signal、actions、stock、tracking與DecisionSummary使用同一 helper；top-level沒有唯一selected strategy/version時整組semantics fail-closed。

2026-09-12 有限 review接受跨API/UI入口標籤、known/unknown identity、數值不變、position stop origin分離與無migration/worker改動。它不驗tick、gap、cost sufficiency、liquidity、PIT或新trade-plan lifecycle。

### 6.2 新交易計畫的隔離邊界

B4b必須使用新trade-plan／execution version，至少保存trigger/confirm、entry range、追價上限、invalid條件、targets、time/event expiry、tick rounding、cost/slippage、liquidity gate與earliest execution。驗收包括：rounding後仍 `invalid<entry<target1<target2`；T+1 gap超限為 `rejected_gap`；成本空間不足、低流動、停牌或同日stop/target順序未知時拒絕或incomparable；legacy replay不變且新舊差異逐欄說明。

## 7. R0-4：時間欄位角色與 point-in-time gate

所有instant使用含offset ISO 8601；date不能假裝timestamp。market/event date、published、first available、collected、revision available、decision、generated、earliest execution是不同角色；legacy `data_cutoff`只供稽核，不能證明T日13:30所有輸入已可得。

### 7.1 Round07 C007／B5a final review（有限本地 foundation）

`time-evidence/v1`要求 subject/source/snapshot/revision identity、七個roles（published、first_available、collected、revision_available、decision、generated、earliest_execution）及至少一個 market_date/event_date/instant/event_at anchor。每個role明示status/precision/value/source/evidence/ref；unknown/unavailable有reason。known instant須含offset並canonicalize UTC，known date保持date，不補午夜。

`TimeEvidenceStore(explicit_path)`是opt-in schema1 store，拒絕正式／`.local`、既存empty/foreign DB。每lineage只一root；revision append＋same-lineage supersedes，舊row immutable。相同identity/payload冪等，不同snapshot/payload collision。exact readers/history無latest fallback；`export_json` atomic no-clobber並拒絕既存、active store或protected target。`legacy_safe`只安全投影合法signal_date，不升格 data_cutoff/created_at/earliest_execution_date。

2026-09-12 有限 review只接受caller-provided local contract/store/export；不接News/API/worker/UI，不證official availability或B5b PIT。產品read-time缺口後由C008補，但store linkage仍未完成。

### 7.2 Round08 C008／B5a 產品 read-time projection（有限 review）

`product-time/v1`是News/signal/action/stock/dashboard/tracking的pure read-time projection；不讀C007 store、不寫DB、不採信任意JSON marker。頂層固定包含 `version`、`scope`、`availability_truth=not_asserted`、`timezone_policy`、`roles`、`response_generated_at`、`legacy`、`limitations`；每role明示role/status/precision/value/UTC/date/source/evidence/ref/reason/timezone policy。含offset instant才可known並轉UTC／Asia-Taipei顯示；date-only保持date；missing/naive/conflict/untrusted basis保持unknown＋reason。

legacy signal_date/data_cutoff/earliest_execution_date/naive created_at保留但不升格decision、availability、generated或execution instant。response time獨立；News collected不等於first available；action ingestion-run finished不等於data collected；已有product contract而role unknown時，frontend不得fallback舊日期。

2026-09-12 有限 review接受API/UI相容projection、跨入口一致性與legacy欄位不變；不接C007 store或worker、不保存新time、不證source truth，也未執行B5b。

point-in-time gate仍未完成：每個必要版本須 `available_at<=decision_at`，live run另須 `collected_at<=decision_at`；revision只有 `revision_available_at<=decision_at`可用。unknown availability預設排除或依預先版本化保守延遲，不得只看market_date。`earliest_execution_at`不得早於decision與所有availability，且須落下一合法交易時段。驗收必須覆蓋盤後資料、T+2 revision、backfill-only collected time、offset/date-only及legacy相容輸出。

## 8. R0-5：migration head 與實際 DB revision

分開三件事：程式head=`0006_news_json_defaults`；文件head應一致；實際DB只能對指定path唯讀查 `alembic_version`與fallback markers。`schema_migrations`只證fallback marker，不等於Alembic current。

### 8.1 B6 review 驗收矩陣

| Gate | 必須證明 |
| --- | --- |
| revision graph | 唯一程式head、完整chain、runtime/dependency version與exit。 |
| DB定位／唯讀 | resolved absolute path，`mode=ro`＋`query_only`，前後size/mtime/hash不變。 |
| actual revision | Alembic row與fallback markers分列，不互相推論。 |
| consistent backup | SQLite backup API或等價一致性副本，專案外path，integrity/FK通過。 |
| copy upgrade | before/after revision、schema diff、rows與共同欄位fingerprints、second-run idempotency。 |
| fresh DB | 另一empty DB到head及必要schema；不取代legacy preservation。 |
| startup／restore | isolation API smoke；forward-only時以discard copy＋restore backup，未實跑明列。 |
| final guard | 正式DB再次唯讀fingerprint；任何非預期差異先停止。 |

### 8.2 C-003 final review 證據與限制

2026-09-12 的C003/B6只改migration tests。當時正式DB唯讀確認沒有 `alembic_version`、有五枚fallback markers且未upgrade；外部consistent copy與fresh DB以真Alembic到當時head 0005，copy的20個既有tables／622,399 rows與共同欄位內容保留，API smoke通過。production migrations未改，forward-only restore未實跑。dynamic 0001依current `Base.metadata`建表，未凍結歷史schema，後續migration仍須同時測pre-head copy與fresh DB。

### 8.3 Round10 C010 migration／restore regression assets（有限 review；R0-A2 未結清）

C010新增固定六表synthetic 0004 slice的自動upgrade/recovery回歸：真Alembic到0005，驗schema/rows/PK/FK/UNIQUE/index/integrity；SQLite backup→故障copy→偵測→restore到新path；second upgrade冪等。它不是完整historical/production schema或正式restore。

該輪發現dynamic fresh metadata的 `news_items.symbols_json`／`theme_ids_json` 缺SQL `[]` server defaults，與0004→0005不同；因此R0-A2未結清。這兩欄後由C011有限修正，但不反向改寫C010歷史，也不代表所有schema parity完成。

### 8.4 Round11 C011：JSON server-default parity 與 atomic migration 回歸（有限 review）

C011新增 `0006_news_json_defaults`與fallback第六marker，使ORM fresh、old005→0006、explicit 0004→0005→0006兩欄均有SQL `[]` default；raw omission可得空array。SQLite repair可保存受測extra index、owned trigger、string default與self-FK；遇inbound FK、view、external trigger、AUTOINCREMENT、generated column、unknown non-null default等shape時在mutation前fail-closed。非SQLite未驗。

Alembic runner建立explicit transaction；active external Connection在mutation前拒絕。failure matrix只對fresh／old005涵蓋Alembic engine、external Connection、fallback、FK0/1與marker前後fault；explicit0004只有success path，不能擴寫成全fault cross-product。success idempotency比較schema/research rows/version set；fallback operational `applied_at`可更新。2026-09-12有限review不含正式DB upgrade/restore/deployment，完整historical parity仍未完成。

### 8.5 2026-09-13 外部 preview startup 後的正式 DB 現況（非 R26 migration 驗收）

另一個使用者preview task的舊lifespan log顯示對正式DB執行base→0001→…→0006。後續只讀確認 current=`0006_news_json_defaults`、21 tables；current file 296,366,080 bytes、SHA-256 `3a21772050b3053557c0798876cc0aa1efe024fcbdce5ab44e35e6abf12da018`。這項外部變化不是R26或本文件接受的正式migration／repair／restore；也不證完整preservation、資料truth或PIT。

### 8.6 Round27 API startup readiness（有限 review）

API lifespan改用 `check_database_readiness`。DB須是regular nonempty file，使用 `mode=ro`、`query_only`、single read transaction與1秒busy timeout。revision只接受唯一current Alembic head＋可選完整known fallback prefix，或無Alembic且恰有六markers；malformed/stale/unknown/multiple/gap/duplicate拒絕。

finite schema gate只核19個mapped real tables、欄名、ordered PK、required unique、FK definitions、News JSON defaults及唯一特許partial unique `ingestion_runs(request_key) WHERE request_key IS NOT NULL`。不驗完整type/nullability/collation/FK actions/CHECK/custom schema/SQL text，不掃rows、integrity或page corruption。config import仍可建directories；request handlers與worker仍可寫。R27未重啟既有service，也不涵蓋live WAL/concurrency或正式deployment。

### 8.7 Round28 C028：canonical legacy instruments identity rebuild rollback／fail-closed（有限 review）

C028把 legacy `UNIQUE(market,symbol)`→current `UNIQUE(exchange,symbol)`收斂為有限SQLite grammar。legacy欄位、PK、constraints、indexes必須符合allowlist；missing exchange/industry先走既有additive path。成功保留有限columns、storage types、values、id及已知default形狀。只允許九個具名application child的simple `instrument_id→instruments.id` inbound FK，且NO ACTION/MATCH NONE/non-deferrable。

recognized current ordered target identity走no-rebuild，但不是完整schema validation。mixed/neither/partial/expression/reversed identity、duplicate target、noncanonical column/default/PK、extra legacy object/CHECK、self/outbound/unknown inbound FK、generated/hidden/table option、FK violation、scratch/TEMP shadow或marker宣稱0002–0006卻仍legacy/absent，都在destructive DDL前拒絕。本批不auto-salvage。

Alembic runner以single explicit transaction包revision chain、marker與pre/post health；fallback以named savepoint提供相同成功邊界。active external Connection拒絕；一般success/failure/no-op恢復FK0/1。只接受finite preservation、fault rollback與same-DB retry；任意custom/historical schema、non-SQLite、crash/disk/concurrency與正式migration未驗。

### 8.8 Round29 C029：canonical legacy `signal_settlements` identity rebuild rollback／fail-closed（有限 review）

C029只接受unmarked exact known 9-column或14-column additive legacy、simple ordinary BINARY `UNIQUE(signal_id)`及sole canonical FK到 `signals.id`。legacy inbound一律拒絕；known nonunique indexes可缺或只接受兩種shape。成功target為ordered `UNIQUE(signal_id,horizon)`；missing／NULL horizon刻意normalize為integer20，missing execution fields=NULL、quality=`complete`，其餘typed payload/id保留。

recognized current要求14 known columns、id PK、essential NOT NULL/defaults、ordered pair identity、canonical FK與基本row checks，走finite no-rebuild。unsupported extra legacy schema、FK、mixed/neither/partial/expression/reversed/duplicate identity、noninteger horizon、scratch/TEMP或known marker配absent/legacy/invalid table都在DDL前拒絕。helper不commit/rollback/switch FK/write marker；runner transaction擁有全部成功邊界。未完成範圍同§8.7，另不保證arbitrary current CHECK/trigger/object或row audit。

### 8.9 Round30 C030：API startup `signal_settlements` UNIQUE metadata gate（有限 review）

readiness要求至少一個full/non-partial、ordinary real columns、ASC/BINARY ordered `UNIQUE(signal_id,horizon)`。所有key parts觸及兩欄的UNIQUE都必須同形；signal-only、horizon-only、reversed、superset/mixed、target partial/DESC/non-BINARY及任意UNIQUE expression拒絕。duplicate canonical pair與unrelated named-column UNIQUE可存在。

gate只讀 `index_list/index_xinfo` key parts，不解析unrelated partial predicate或generated dependency，也不audit CHECK/trigger/actual INSERT；readiness pass不保證任意write。有限review只接受readonly metadata policy，沒有migration、repair、row scan、service reload或正式deployment。

### 8.10 Round31 C031：API startup `instruments` UNIQUE metadata gate（有限 review）

canonical identity是ordered `(exchange,symbol)`；`market`不是identity，但三欄都是writer mapped target，所以都必須 `table_xinfo.hidden=0`。至少一個full/non-partial、ASC/BINARY canonical UNIQUE；每個key parts觸及 `{market,exchange,symbol}` 的UNIQUE都必須同形。single、legacy、reversed、superset/mixed、partial、target DESC/non-BINARY與任意UNIQUE expression拒絕。

key-unrelated named UNIQUE可含partial/DESC/non-BINARY/generated extra；gate不解析其predicate/dependency，因此仍可能阻擋某些write。CHECK、trigger、nonunique index與其他column descriptors不audit。這個startup policy可比R28 current no-rebuild更窄；`init-db`不會自動修所有被startup拒絕的custom shape。正式migration/restore/deployment、non-SQLite、attached/arbitrary schema、concurrency、data truth/PIT仍未完成。

## 9. B7：新舊版本隔離驗證與 review gate

每個產生研究結果的R0修正最後都要用同一read-only input snapshot做paired replay：legacy走原version，新計算走新version，輸出到不同DB/namespace/version key，不能互相upsert。

差異報告至少列：snapshot/hash、date range、universe、action/source versions；全部feature/strategy/execution/prediction/output/presentation versions；ATR value/warm-up/missing與gap/action逐筆差異；rule states/reasons與confidence分布；levels/trade-plan/gap reject/incomparable；availability exclusions與earliest execution；migration revision、commands、exit/pass/fail/skip；unexpected differences、limits與default-switch建議。

reviewer至少重現success、missing、gap、corporate action、legacy confidence、after-hours availability與revision案例。B7通過後只能「提議」更新ROADMAP或default；決定仍由統籌另行處理。

## 10. 非目標與停止條件

- 本契約不選股、不評估績效、不設定個人風險預算，也不授權自動交易。
- 不因R0擴大收集期、採購來源、執行正式migration或回填正式資料。
- 若需要原地覆寫舊列、無法隔離正式DB、無法辨識version，或公司行動／time source不可重建，立即停止該批並記blocker；不得繞過版本與PIT邊界。
