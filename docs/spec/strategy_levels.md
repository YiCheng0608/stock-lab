<!-- owns: strategy_levels_v1 -->
# strategy_levels_v1

條件價位：以 T 日收盤後已知的資料，反推下一個交易日（T+1）的收盤與成交量要落在哪裡，T+1 的 analyze 才會判該策略的價格與量能條件成立。T+1 的前 20 日窗口是 T−19～T，所以門檻是已知數，不是預測；族群、法人、融資無法反推，只列 T 日實際值與門檻。版本 `levels_version = "strategy_levels_v1"`（`app.domain.STRATEGY_LEVELS_VERSION`），公式、升降單位表（`app.strategies.levels.TICK_LADDERS`）與漲跌幅由 `backend/tests/test_strategy_levels.py` 釘住；改任何一項要升版另寫新列，舊列保留。觀察價位**不是**成立的價位：`signals` 不改，決策摘要、候選評分與使用者追蹤計畫都不讀這張表（行動頁列表只讀 `conditions_json` 與價格差距，不顯示觀察價位），追蹤計畫仍只收 conditional 訊號。候選的進場方式（`/api/candidates` 與個股 API `candidate` 的 `entry_plan`，`app.entry_plan`，[#491](https://github.com/YiCheng0608/stock-lab/issues/491)）原樣帶出候選訊號的這一列與展開的條件清單；畫面只用條件清單裡資料日的判定（「完整條件」，[UI_COPY_SPEC §10.2](../UI_COPY_SPEC.md#102-進場方式)），進場句的價位都讀訊號。這一列的觸發價與區間是下一交易日能否再出新訊號的門檻，不是已成立訊號的失效條件（失效只看停損）。

**價格基準**：價格用 T 日價格基準的還原序列（與 `technical_features`、`rule_evidence_json.inputs` 相同）。T 之後到下一交易日（含）的公司行動若已存入 `corporate_actions`，全部價格乘上該段的換算因子，改用下一交易日的基準（`price_basis = next_session_raw_basis`；現金股利沒有參考價時以 T 收盤代替，同 analyze）；沒有存入時維持 `score_date_raw_basis`，T+1 除權息時門檻會偏差。下一交易日同[規則最早執行日](README.md#價位etf-與生命週期)（官方休市表推算，連假後第一天的除權息也會換算）；休市表答不出來時取 T 之後第一個週間日。`next_session_date` 記用哪一天。量用原始股數。

**升降單位**：股票與 IPO：未滿 10 元 0.01、10～50 元 0.05、50～100 元 0.1、100～500 元 0.5、500～1,000 元 1、1,000 元以上 5；ETF：未滿 50 元 0.01、50 元以上 0.05。價格先四捨五入到小數 6 位再取整（與 `prior_20_highs` 相同）；嚴格大於取「下一個合法價位」，下界往上取、上界往下取。最小量無條件進位、最大量無條件捨去，到整數股（張數顯示由前端依 UI_COPY_SPEC 換算）。

**breakout_v1**：H＝T−19～T 的最高價（下一交易日基準）。`trigger_price`＝H 之上的下一個合法價位；`min_volume`＝⌈1.2 × T−19～T 均量⌉。參考價位：`reference_entry`＝trigger，停損與目標＝`risk_levels(trigger, ATR14[T])`（[價位](README.md#價位etf-與生命週期)的 1.6R／3R，ATR 也乘換算因子），`risk_reward` 為 (target_1 − entry)／(entry − invalid)。

**pullback_v1**：S19、S59＝最後 19、59 根收盤之和（T−18～T、T−58～T）。下一交易日收盤 c 使 MA20＝(S19+c)/20、MA60＝(S59+c)/60，條件都是 c 的一次式：

| 條件 | 下一交易日 |
| --- | --- |
| 歷史 | T 日已有 ≥ 59 根（T+1 才滿 60 根） |
| MA20 > MA60 | c > (S59 − 3·S19)/2 |
| 收盤 ≥ MA60 | c ≥ S59/59 |
| 支撐區 0.97～1.02×MA20 | 0.97·S19/19.03 ≤ c ≤ 1.02·S19/18.98 |
| 量能 0.6～1.2 倍 | ⌈0.6 × 均量⌉ ≤ volume ≤ ⌊1.2 × 均量⌋ |

收盤區間 `zone_low`＝L（前三個下界取整後的最大值）、`zone_high`＝U（支撐區上界取整）。L > U 時記 `trend_unreachable`，不給任何價位與量，`conditions_json` 的趨勢條件與支撐區條件仍列出兩個數字。否則參考 `reference_entry`＝T 收盤夾在 [L, U] 內最近的點（收盤在區間內／上方／下方分別記 `position` inside／above／below），停損與目標＝`risk_levels(entry, ATR14[T])`，參考進場區 `entry_low`／`entry_high`＝MA20' ± max(0.5·ATR14, 0.5%·entry)，MA20'＝(S19+entry)/20（同成立價位的算法）。

**pullback_v4**（[#580](https://github.com/YiCheng0608/stock-lab/issues/580)）：收盤區間、量、可達性、參考進場區與停損目標都同上（停損與目標仍是 `risk_levels(夾進 [L, U] 的收盤, ATR14[T])`），只把參考 `reference_entry` 換成參考進場區中點 `round((entry_low + entry_high) / 2, 2)`，`risk_reward` 以這個中點重算；中點不在停損與目標一之間時 `risk_reward` 為 null。和成立價位同一條規則（[pullback_v4](breakout_pullback.md#pullback_v4)）。`levels_version` 不升：v3 的列不動，只有 v4 的新列套用。

**可達性** `reachable_next_session`：股票與 IPO 以 T 收盤（下一交易日基準）±10% 依升降單位取整為漲跌停；breakout 為 trigger ≤ 漲停，pullback 為 L ≤ 漲停且 U ≥ 跌停。ETF 的漲跌幅因商品而異（例：00967B 官方 LimitUp 9999.95），一律 null。

**availability**：

| 值 | 條件 | 價位 |
| --- | --- | --- |
| `levels` | 下列情況以外 | 有 |
| `trend_unreachable` | pullback 的 L > U | 無；`missing_inputs_json` 為 `trend_cannot_pass_within_support_zone` |
| `suspended` | T 日停牌 | 無；`signal_day_suspended` |
| `not_applicable` | 排除的 ETF 類別（`etf_category_excluded_from_actionable_signals:<類別>`） | 無 |
| `data_incomplete` | 以下一交易日的根數（T 的根數＋1）判定 eligibility 不通過（例：IPO 未滿 60 根 `ipo_observation_only_under_60_bars`），或缺下一交易日要的輸入：前 20 根最高價／成交量、59 根收盤、T 收盤，以及 T 日的族群、法人、融資值；`missing_inputs_json` 用 evaluator 的原因碼 | 無 |

T 日沒有日線的標的沒有 signal，也就沒有列。

**`conditions_json`**：每個策略一份條件清單，前兩條共通：`eligibility`（T 日 eligibility 與停牌，`reasons` 列原因）、`required_inputs`（T 日判定是否 `data_incomplete`，`reasons` 列缺項）；接著是策略自己的條件（breakout：`breakout_price`、`breakout_volume`；pullback：`pullback_history`、`pullback_trend`、`pullback_above_ma60`、`pullback_support_zone`、`pullback_volume`）與三個確認條件（`group_relative_strength`、`institutional_flow`、`margin_financing`）。每條有 `kind`（eligibility／data／price／volume／trend／confirmation）、`satisfied`（T 日 analyze 存的判定，`data_incomplete` 時為 null）、`actual`、`threshold`、`threshold_high`、`operator`、`reasons`、`next_session`（可反推的條件才有：`min_close`、`max_close`、`min_volume`、`max_volume`，價格條件另有 `gap`＝目標價／T 收盤 − 1，支撐區另有 `position`）。存進表時每條只留 `code` 與跟該策略預設值不同的欄位（#274）：預設值是 `app.strategies.levels.condition_defaults`（沒有任何輸入時的條件清單，含 `kind`、`operator`、設定的固定門檻與空值），讀取一律經 `expand_conditions` 補回完整欄位，舊的完整格式照樣讀得回來；預設值依 `levels_version` 由測試釘住（`PINNED_CONDITION_DEFAULTS`，現行版本不在表內或預設值不同就失敗），改了就要升 `levels_version`。條件價位步驟與策略總表只處理策略名稱、版本與法人流向公式版本（`formula_version`）都等於現行的訊號（`strategies.current_strategy`），其他版本的列不以現行預設值展開。個股頁策略總表（`GET /api/stocks/{exchange}/{symbol}` 的 `strategy_board`）回傳展開後的清單。

**表** `strategy_levels`（migration `0019_strategy_levels`）：每個 signal 與 `levels_version` 一列（unique），欄位為 `availability`、`next_session_date`、`trigger_price`、`zone_low`、`zone_high`、`min_volume`、`max_volume`、`reference_entry`、`entry_low`、`entry_high`、`invalid_price`、`target_1`、`target_2`、`risk_reward`、`reachable_next_session`、`conditions_json`、`missing_inputs_json`、`price_basis`、`computed_at`；策略、標的、日期與 `strategy_version_id` 經 signal 取得。conditional 的訊號也有列（下一交易日再次成立的門檻），成立價位仍以 `signals` 為準。只處理 `analysis` 訊號，且策略版本須等於 registry 的現行版本，其他版本略過並計入 `signals_skipped`。每日保存全部列（約 4,600 列／日；條件清單精簡後 2026-10-21～10-22 副本約 3.6 MB／日，精簡前約 8 MB／日）。

**冪等與回補**：daily 的 `strategy_levels` 步驟（[日誌與 run 記錄](../ops/SCHEDULING.md#日誌與-run-記錄)）與 `worker.cli strategy-levels --date`（[現有 worker CLI](../ops/CLI.md#現有-worker-cli)）是同一個函式；同日重跑值相同就不改寫（`computed_at` 不動），值不同才更新。資料可由 `market_bars`、`corporate_actions`、`technical_features` 與 `signals` 完整重建。
