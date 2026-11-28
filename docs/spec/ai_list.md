# AI 名單 ai_list_v1

AI 名單：每個交易日 D 08:21（台北），從候選池挑出今日名單（最多 10 檔、排名次），每檔給判讀方式、理由、進場區、停損、目標與有效期，程式核對後存檔，存了不改。名單與價位是 **AI 推論，未經驗證**，不是下單指示；價位由 AI 給、程式核對。本規格只寫產出與存檔（[#1145](https://github.com/YiCheng0608/stock-lab/issues/1145)）；頁面、Telegram、盤中通知與對答案是母單 [#1144](https://github.com/YiCheng0608/stock-lab/issues/1144) 的後續任務。依據：[#1142](https://github.com/YiCheng0608/stock-lab/issues/1142) 的評估（[1/4](https://github.com/YiCheng0608/stock-lab/issues/1142#issuecomment-7235660250) 名單怎麼產生、[2/4](https://github.com/YiCheng0608/stock-lab/issues/1142#issuecomment-7235671507) 價位與核對、[3/4](https://github.com/YiCheng0608/stock-lab/issues/1142#issuecomment-7235688997) 存法、[4/4](https://github.com/YiCheng0608/stock-lab/issues/1142#issuecomment-7235713717) 架構），#1 決定 [7235996430](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-7235996430)（全部選建議的 A）。

程式：job `backend/worker/ai_list.py`、輸入 `backend/worker/ai_list_input.py`、呼叫與核對 `backend/worker/ai_list_reading.py`、提示詞 `backend/worker/prompts/ai_list_v1.md`；排程與日誌見 [SCHEDULING](../ops/SCHEDULING.md#scheduler-容器的排程serve)，看門狗見 [WATCHDOG](../ops/WATCHDOG.md)。和 [早盤 AI 判讀 premarket_v1](premarket_ai.md) 並存：兩者 08:21 同時起跑、各自的呼叫、鎖、上限與表，`premarket_v1` 照跑、照存、照對答案。

## 輸入

- **快照**：與 `premarket_v1` 同一份（`premarket_input.build`，[輸入快照](premarket_ai.md#輸入快照)）：截止 D 08:15 的隔夜新聞與截止前的 AI 判讀、美股四檔、台指期一般時段與夜盤、加權指數，以及候選池每檔的進池來源、價量、籌碼、產業題材與個股新聞；背景規則名單（名單日的今日名單）上的股票另附規則價位 `strategy_levels`。只從候選池挑（#1 [7187528140](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-7187528140)：不從池外補股）。
- **上一份 AI 名單**：不給（2/4 Q2-1 A）：每天獨立判讀。
- **價位事實** `level_facts`（`ai_list_facts_v1`，每檔一份，`level_facts_version` 記在快照最上層）：只用名單日 T 以前的日 K，D 當天的資料都不用。

| 欄位 | 算法 |
| --- | --- |
| `basis`、`as_of`、`instrument_type`、`close` | `list_date_raw`：T 的未還原價；窗口內有除權息時，較早的日 K 乘上 `pipeline._corporate_action_factor` 的因子換到 T 的基準（該根之後、T 以前的公司行動；沒有官方參考價時用除權息前一根的收盤，同追蹤的算法） |
| `ma5`、`ma10`、`ma20`、`ma60` | 收盤的簡單平均，兩位小數 |
| `high_20`、`low_20`、`high_60`、`low_60` | `{price, date}`：窗口內最高價（沒有時用收盤）、最低價，同值取最近的一根 |
| `atr14` | 14 根真實波幅 max(H−L, \|H−前收\|, \|L−前收\|) 的簡單平均，三位小數 |
| `volume_node_60` | `{low, high, share, window}`：60 根的最低到最高切 20 格，每根的量放在 (H+L+C)/3 那一格，取量最多的那格 |
| `limit_up`、`limit_down` | `app.strategies.levels.price_limits`：T 收盤 ±10%，依 D 的升降單位取整；ETF 是 null |
| `tick` | T 收盤在 D 的升降單位表上的單位（`levels._ladder`，2027-07-05 起上市換表） |
| `corporate_action_in_window`、`corporate_action_on_session` | 窗口內有公司行動；T 之後到 D 有公司行動（D 的漲跌停會和這裡不同） |

根數不夠的欄位是 null；T 沒有日線的股票是 `{"status": "missing"}`，不能挑。

## 輸出

提示詞 `ai_list_v1`，schema `ai_list_reading.OUTPUT_SCHEMA`（以 `--json-schema` 傳給 CLI，程式再驗一次）：

- `market`：`stance`（`bullish`／`bearish`／`neutral`）、`confidence`（`high`／`medium`／`low`）、`method.basis`（1～5 個，依重要性排、不重複：`us`、`tx_night`、`tx_day`、`news`、`taiex`）、`reasons`。
- `sectors`：同 `premarket_v1`。
- `picks`：最多 10 檔，每檔：
  - `symbol`、`rank`（1 起連號，1 是 AI 最看好的）；
  - `method`：`setup`（`breakout` 突破、`pullback_support` 回檔到支撐、`oversold_rebound` 跌深反彈、`theme_momentum` 題材發酵、`news_catalyst` 消息催化、`chip_accumulation` 籌碼集中）、`basis`（1～3 個，陣列順序就是主次：`news`、`chips`、`technical`、`sector`、`market`）、`confidence`；
  - `reasons`：1～3 條 `{text, refs}`，「根據……，推論……」，價位寫成名詞（進場區、停損、目標）；
  - `levels`：`entry`（`type`：`breakout` 站上 `low` 才算、`high` 是不追價上限；`pullback` 回到 `low`～`high` 之間才算；`low`、`high`、`condition`）、`stop`、`target_1`、`target_2`（可為 null），每個價位是 `{price, refs, atr_multiple}`；`exit_conditions` 0～2 條；`valid_sessions` 1～5 個交易日。
- `empty_reason`：空名單時必填，否則 null。大盤偏空可以空名單（1/4 Q1-4 A），提示詞寫「偏空且信心不是 low 時傾向空名單」，程式不強制。
- `data_gaps`：`{text, refs}`。

提示詞的 SHA-256 釘在 `ai_list_reading.PROMPTS`、schema 的釘在測試：改了任一個要換版本。

## 核對

依序；第一個不過的是 `reason`。

| 層 | 檢查 | 不過時 |
| --- | --- | --- |
| 整份 | schema：結構、代碼表外的值、`basis` 重複、`valid_sessions` 超出 1～5、超過 10 檔（`schema`） | 重試 1 次，仍不過 `rejected` |
| 整份 | 代號不在候選池（`not_in_pool`）、重複（`duplicate_pick`）、`rank` 不是 1～n 連號（`rank_not_contiguous`）、空名單沒寫原因（`empty_without_reason`） | `rejected`，不重試 |
| 整份 | `news:<id>` 不在輸入（`unknown_news_ref`）、下單指示用語（`directive_words`，同 [premarket_v1](premarket_ai.md#核對)；查所有理由、進場條件、出場條件、資料缺口與 `empty_reason`） | `rejected`，不重試 |
| 單檔 | 見下面「每檔的價位」 | 單檔不過，整份照 `done` |
| 只記錄 | 理由、進場條件與出場條件裡不是該檔任何輸入數字或價位的價位寫法（`price_mentions`，同 `worker.price_mentions`）、超過 120 字的理由數（`long_reasons`）、輸入沒有的族群 id（`unknown_group_ids`） | 記在 `checks_json`，不判不過 |

呼叫層的失敗（逾時、回應不是 CLI 的 JSON、CLI 錯誤）重試 1 次；`rate_limited`、`not_logged_in`、`cli_not_started` 不重試，記 `failed`；剩下不到 300 秒不再呼叫（`no_time`）；提示詞與版本的雜湊不符就不呼叫（`prompt_hash_mismatch`）。

### 每檔的價位

先取整，再做其他檢查（2/4 Q2-3 A）：依 D 的升降單位，進場區下緣、目標一、目標二往下取，停損、進場區上緣往上取（`levels.tick_floor`／`tick_ceil`），有變動的記在 `rounded`。

| 檢查 | 代碼 |
| --- | --- |
| 有 `level_facts` | `no_level_facts` |
| `refs[0]` 是 `stock:<本檔代號>:<欄位>`，欄位是 `price` 的 `open`／`high`／`low`／`close` 或 `level_facts` 的 `close`、`ma5`、`ma10`、`ma20`、`ma60`、`high_20`、`low_20`、`high_60`、`low_60`、`volume_node_60.low`、`volume_node_60.high`、`limit_up`、`limit_down`，而且有值 | `ref_not_price_field` |
| `atr_multiple` 是 0、±0.5、±1、±1.5、±2、±3 之一 | `atr_multiple_not_allowed` |
| 倍數不是 0 時有 `atr14` | `no_atr` |
| AI 給的價位和「基準＋倍數×`atr14`」相差不超過 max(2 個 tick, 0.5%)（tick 取基準算出的價位那一級） | `ref_mismatch` |
| 取整後的每個價位在 D 的漲跌停之內（ETF 不判） | `outside_limits` |
| 取整後 停損＜進場下緣≤進場上緣＜目標一＜目標二 | `order` |
| RR ≥ 1.0（2/4 Q2-4 A） | `risk_reward_below_min` |

- **RR**：(目標一 − 參考進場) ÷ (參考進場 − 停損)，用取整後的價位；參考進場在突破是進場下緣、拉回是進場區中點（同規則價位的 `risk_reward_basis`）。程式算，兩位小數存；參考進場不高於停損時是 null。
- **單檔不過**（2/4 Q2-5 A）：名次、判讀方式、理由照留，`display_levels_json` 是 null（不顯示價位、不進盤中通知、不能加入追蹤，由後續任務照此讀）。

## 紀錄

只新增，不改、不刪。表與 `premarket_ai_*` 分開（3/4 Q3-1 A：`premarket_score_v1` 對 `premarket_ai_readings` 所有 `done` 的列算分）。

- **`ai_list_readings`**：每次執行一列，欄位同 `premarket_ai_readings`（`session_date`、`list_date`、`role`（`champion`）、`sequence`、`trigger`、`prompt_version`、`prompt_sha256`、`schema_sha256`、`model_alias`、`llm_model`、`pool_phase`、`cutoff_at`、`input_hash`、`input_json`、`status`、`reason`、`error`、`output_json`、`checks_json`、`attempts`、`attempts_json`、`duration_ms`、`usage_json`、`ingestion_run_id`、`started_at`、`finished_at`），另加 `market_method_json`（`done` 時大盤的 `basis`，依序）。`checks_json.picks` 是每檔的價位核對，`picks_passed` 是全過的檔數。
- **`ai_list_picks`**：`done` 的每檔一列：`reading_id`、`rank`、`instrument_id`、`symbol`、`pool_item_id`、`pool_sources_json`、`on_rule_list`（背景規則名單有沒有它）、`setup`、`basis_json`（依序）、`basis_primary`、`confidence`、`levels_json`（AI 原樣）、`levels_check_json`（逐項的基準、預期值、容許值、取整與不過的項目）、`display_levels_json`（全過才有：取整後的進場區、停損、目標、RR、`valid_sessions`、`valid_until`）、`risk_reward`、`valid_sessions`、`valid_until`（D 算第 1 個交易日，依存的交易日曆往後數，沒標休市的平日算交易日）、`exit_conditions_json`、`reasons_json`、`rule_levels_json`（輸入裡該檔的規則價位，沒有是 null）。
- **重跑**：同一天已有 `done` 就不呼叫，記 `skipped reason=already_done`；`failed`／`rejected` 之後再跑才另加下一個 `sequence`。呼叫期間不寫 DB：每次呼叫的提示與回應先寫 raw 檔，呼叫結束、再查一次維護模式後，才在同一個交易裡寫 `ingestion_runs`（`run_type=ai_list`）、`raw_payloads`（`source=ai_list`）、判讀與每檔列。
- **模型與提示版本**：每次呼叫記 `prompt_version`、`prompt_sha256`、`schema_sha256`、`model_alias`（`sonnet`）與 CLI 回報的 `llm_model`。

## 限制

- 價位事實換到 T 的基準；T 之後到 D 有除權息時，D 的漲跌停與價位基準不同，只標 `corporate_action_on_session`，核對照 T 的漲跌停。
- 重放過去的日子（`--date`）時，今日名單、自選、H2 與台指期日盤讀的是現在存的值，同 [premarket_v1 的限制](premarket_ai.md#限制)。
- 名單日之後的走勢、開盤後檢查與對答案不在本規格。
