<!-- owns: v1 共通原則、價位／ETF／生命週期、策略版本識別、策略 registry、v1 現行限制 -->
# Canonical v1 規格

本文只保存 `breakout_v1`、`pullback_v1`、[`breakout_v2`／`pullback_v2`](breakout_pullback.md#breakout_v2pullback_v2)、[`breakout_v3`／`pullback_v3`](breakout_pullback.md#breakout_v3pullback_v3)、`hot_group_v1`、[條件價位 `strategy_levels_v1`](strategy_levels.md)、[`candidate_score_v1`](candidate_score.md#candidate_score_v1)／[`candidate_score_v2`](candidate_score.md#candidate_score_v2)／[`candidate_score_v3`](candidate_score.md#candidate_score_v3)／[`candidate_score_v4`](candidate_score.md#candidate_score_v4)／[`candidate_score_v5`](candidate_score.md#candidate_score_v5)／[`candidate_score_v6`](candidate_score.md#candidate_score_v6)、[技術指標](indicators.md) `indicators/v1`、價位、eligibility、生命週期與回測的 canonical 基準；實作狀態與排程見 [ROADMAP](../ROADMAP.md)。修改公式、時間、成本或機率語意時必須升版並保留舊 run、輸入、設定與結果。`StrategyVersion` 以（`name`、`version`、`formula_version`）識別；config 的 `formula_version` 子版本另建一列，`version` 不變，原列與指向它的訊號不改（規則見[策略版本識別](#策略版本識別)）。策略設定來源是 `backend/app/strategies/`（[策略框架與 registry](#策略框架與-registry)），`hot_group_v1` 與 `candidate_score` 的設定在 `backend/app/domain.py`；worker 保存可序列化設定、rule evidence、data cutoff 與 raw provenance。此規格用於重現和稽核，不證明策略已採用或有效。

## 共通原則

- T 是訊號收盤日；最早成交為 T+1，不用 T 收盤冒充成交。
- 價格與必要量值須為有限正數。NaN、Infinity、交易日不足、必要資料缺失、停牌或不可重建路徑一律 `data_incomplete` 或 `incomparable`，不補 0。
- v1 以日期 T 作 cutoff；T 日 13:30 的 cutoff 字串不證明法人等盤後輸入當時已可得。`trading_date`／`event_date` 是資料日期，`collected_at` 是本系統取得時間，回補日不能反推成歷史可得日。新的 PIT 版本須另存 availability、revision 與 decision time。
- 有證據的無資料與缺資料分開記：[官方無成交日](../DATA_SOURCES.md#官方無成交日)（行情表有列、價格全空白）在資料覆蓋度算「官方無成交」，不算缺口，也不是價格；表上沒有該列、或無法證實的空白仍是缺資料。策略與指標對無成交日的處理不因此改變。
- failed／partial collect run 不分析或追蹤（gate 見 [現有 worker CLI](../ops/CLI.md#現有-worker-cli)）。明確官方 no-data 且無列的非交易日可略過；錯日、缺報告日期或無法證實的空 payload 必須 fail closed。
- `observation` 表示該策略輸入完整、規則已判定但條件未成立；缺 entry／target／RR 是正常狀態；呈現方式見 [PRODUCT_SPEC §6](../PRODUCT_SPEC.md#action-merge)。

## 價位、ETF 與生命週期

- 合法 entry type 只有 breakout 與 pullback；entry、invalid、targets 必須為有限正數。
- `invalid_price < entry < target_1`；第一目標 RR 必須 `>= 1.5`；存在的 `target_2 > target_1`。
- IPO 少於 20 根不觀察，20–59 根只可 observation，至少 60 根才可 actionable。
- ETF 全部收集、分類並進 ETF 分榜。broad_market、dividend、sector、thematic、commodity 可套一般策略；bond、leveraged、inverse 回傳 `etf_category_excluded_from_actionable_signals:<category>`，仍可收集與排行。
- **規則最早執行日**（`signals.earliest_execution_date`、`rule_evidence_json.execution.earliest`，[#294](https://github.com/YiCheng0608/stock-lab/issues/294)）：依 T 當晚已存的[官方休市表](../DATA_SOURCES.md#交易日曆)推算 T 之後第一個交易日（週間日、且休市表沒有列為休市；上市與上櫃共用）。只讀休市表、不讀 T 之後的日線，所以當晚與之後重算的結果相同；個股隔天停牌不影響這個日期。`execution.calendar` 記來源 `twse_holiday_schedule`、讀到的休市表 raw（`raw_payload_ids`）與留空原因 `missing_reason`。
  - 休市表缺所需年度（`calendar_year_missing`，例如年底時明年尚未公告）或碰到無法分類的列（`calendar_row_unknown`）時留空，不猜、不退回週間日；analyze 步驟記 `execution_calendar`，看門狗留言（[排程看門狗](../ops/WATCHDOG.md)）。
  - 颱風等臨時休市不在休市表裡，T 當晚無法得知，所以不納入，事後也不改寫。例如 2026-10-22 的訊號得到 10/23，而 10/23 實際上臨時休市。
  - 成交判定（訊號追蹤與[使用者追蹤計畫](tracking.md#使用者追蹤計畫)）讀實際日線（T 之後第一根），不讀這個欄位；追蹤計畫只快照它。改用休市表以前寫入的訊號這欄為空，沒有回填。

    observation -> conditional -> active -> target_1_hit -> target_2_hit -> settled
                      |              +-> invalidated / expired / incomparable -> settled
                      +-> data_incomplete / invalid_levels / expired

## 策略版本識別

- 唯一鍵為（`name`、`version`、`formula_version`）。`init-db` 依快照把既存列標為已知公式（與固定 SHA-256 清單內 canonical 快照相同者為 `institutional-flow/v1-shares-per-twd-turnover`），其餘標 `unclassified/<reason>`；非現行公式的列設 `active=false`，id、`version`、`config_json`、快照與指向它的訊號不改。
- `_ensure_strategies` 只取（名稱、版本、目前公式）的列或新建，取到的列與 canonical 不符時以 `strategy_snapshot_mismatch` 拒用；`signal_key` 不含公式，同鍵訊號屬於其他公式時以 `signal_formula_conflict` 拒絕覆寫，`analyze` 不提交該次結果，`daily` 不進入 evaluate。
- `GET /api/strategies` 每列含 `id`（整數主鍵）與庫內原值 `formula_version`（含 `unclassified/<reason>`）。

### 策略框架與 registry

- `backend/app/strategies/` 的 `REGISTRY` 是策略清單唯一的宣告處，宣告順序為 `breakout_v3`、`pullback_v3`。`backend/app`、`backend/worker` 其他非測試程式不寫策略名稱，一律讀 registry；例外只有歷史資料與版本化快照，列在 `backend/tests/test_strategy_registry.py` 的白名單並寫理由，該測試掃描原始碼，出現白名單外的策略名稱就失敗。
- `StrategyInputs`：analyze 每檔每日建一次、所有策略共用。欄位為 `bar_count`、`close`、`volume`、`ma20`、`ma60`、`atr14`、`prior_highs`／`prior_volumes`（T 之前最多 20 根，與 `rule_evidence_json.inputs` 相同）、`group_excess_return_20d`、`institutional_flow_ratio_5d`、`margin_change_ratio_5d`，以及 `margin_financing`（v2 起的融資標的判定）與 `margin_zero_base`（v3 起的零基期）。
- `Strategy`：`config` 是 canonical 設定（`name`、`version`、`kind` 取自它，快照存成 `StrategyVersion`）；`rule` 是純函式判定，`arguments(inputs)` 給它的參數；`actionable_levels(inputs)` 是判定成立時寫入 `signals` 的價位；`entry_type` 決定價位欄（`app.domain.ENTRY_LEVEL_FIELDS`，只能是既有的 breakout／pullback）；`label_zh`、`research_label_zh`、`requires_zh` 是顯示文案；`level_formula_version` 是價位公式識別；`candidate_distance`、`candidate_reason` 供候選評分的技術分項與理由使用。`observation_levels(next_inputs)` 與 `conditions(inputs, evaluation, levels)` 給[條件價位](strategy_levels.md)：前者以 `NextSessionInputs`（T 日收盤後已知、換算到下一交易日基準的序列）解出下一交易日的收盤與量，後者列出 T 日的條件清單；未實作的策略記 `not_applicable`（`observation_levels_not_defined`）。
- analyze 對每檔每日：建一次輸入，依宣告順序判定每個策略，再為每個策略各寫一列 `signals`；每列的 `rationale` 與 `rule_evidence_json` 以 `kind` 為鍵記錄全部策略的判定。決策摘要取宣告順序中第一個 conditional 策略；只有 observation 時優先 pullback entry type。
- 新增策略：在 `app/strategies/` 新增模組（canonical 設定用新的 `name`／`version`、`rule`、`arguments`、`actionable_levels`、`entry_type` 與文案），登錄到 `REGISTRY`，補單元測試與本文件的策略章節。`kind` 必須和其他已登錄策略不同（例如和 `breakout_v1` 同時登錄的 `breakout_v2` 不能沿用 `breakout`），也不得是證據與 rationale 的固定鍵（`app.strategies.RESERVED_KINDS`：`strategy`、`strategy_version`、`group_member_return_lookup`、`confidence_semantics`、`actionable`、`inputs`、`risk_validation`、`execution`、`group`、`missing`），否則會無聲蓋掉同鍵的內容。`test_strategy_registry.py` 以 `registry_problems` 檢查，並核對保留鍵就是 analyze 實際寫出的固定鍵。登錄後 analyze 就為每檔寫出它的 signal 列，`_ensure_strategies` 新建它的 `StrategyVersion`，個股頁條件清單出現它；不需改 decision、API 或候選程式。
- **取代舊策略**（[#392](https://github.com/YiCheng0608/stock-lab/issues/392)、[#404](https://github.com/YiCheng0608/stock-lab/issues/404)）：新策略的 `config.supersedes` 指向它取代的策略，舊策略移到 `SUPERSEDED`，不再由 analyze 寫入，`kind` 與 `entry_type` 不變。同一 `kind` 的版本以 `supersedes` 連成一條鏈（`breakout_v1` → `breakout_v2` → `breakout_v3`），終點是 `REGISTRY` 的策略。頁面讀訊號時把舊版的訊號當成鏈終點的策略讀（`registry_key`）。某標的某日只讀它有的最新一版：鏈上更新的版本在同一天有 analysis 訊號，就不讀舊版（`NEWER_VERSIONS`、`app.signal_versions.readable_signal`）。所以每段日期顯示當時的版本，同一天不會兩版都出現，例如 #392 切換當天 v1 與 v2 並存，只讀 v2；個股策略總表用同一條規則。`signals(instrument_id, signal_date)` 有複合 index `ix_signals_instrument_date`（0022），這個檢查只查同一標的同一天。條件價位步驟也一樣：同一標的同一天只算最新一版的列（`newest_versions`），略過舊版的列，因為切換當天先寫的舊版列帶的是舊輸入。舊版訊號用它自己的條件與預設值展開（`current_strategy` 也認 `SUPERSEDED`）。
- 候選池不跟著 registry：每個 `candidate_score` 版本在 `pool.strategies` 列出入池策略，並以策略名稱為鍵定義量比方向與距離公式。新策略要進候選池，必須另升一個 `candidate_score` 版本（新設定快照，舊版的 runs 保留），不改現行版本。

## 現行限制

1. worker 的 `atr14` 是最多 14 根 high-low 的平均，不含前收盤的 True Range，不是 Wilder ATR。
2. conditional 訊號的 `confidence=0.75` 是沒有校準證據的固定值，不得稱 75% 勝率；rule-only 的數值為 null。
3. `risk_levels`（`backend/app/strategies/base.py`）以固定風險倍數產生 1.6R／3R，合法 RR 只證明算術關係，不代表可成交、壓力位或預測。
4. 法人比率（`worker.pipeline._validated_flow_and_volume_inputs`）以 T（含）以前最後 20 根非停牌 bar 計算、最後 5 根須有籌碼列，不核對交易所日曆，也不要求最後一根就是 T。
