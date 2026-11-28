<!-- owns: premarket_ai_v1、早盤 AI 判讀的輸入快照、早盤 AI 判讀的核對、早盤 AI 判讀紀錄表、早盤 AI 判讀的顯示、premarket_score_v1、早盤 AI 判讀的對答案、早盤 AI 判錯清單、早盤提示詞改版提案 -->
# premarket_ai_v1

早盤 AI 判讀：每個交易日 D 08:21（台北），用截止 D 08:15 的隔夜新聞、美股、台指期夜盤，以及候選池每檔的價量籌碼、產業題材（今日名單的股票另附規則價位），呼叫一次 `claude -p`（sonnet），產出大盤、族群與每檔「維持／依開盤價重算／暫緩」與理由；核對後存檔，存了不改。判讀是**推論**，不是買賣訊號。自 [#1142](https://github.com/YiCheng0608/stock-lab/issues/1142) 起只記錄、不顯示（今日名單見 [ai_list_v1](ai_list.md)），照舊對答案。依據：#1002 的評估（[AC-2 1/2](https://github.com/YiCheng0608/stock-lab/issues/1002#issuecomment-7118193790)、[AC-2 2/2](https://github.com/YiCheng0608/stock-lab/issues/1002#issuecomment-7118209417)、[AC-3](https://github.com/YiCheng0608/stock-lab/issues/1002#issuecomment-7108600534)）與 #1 決定 [7187492081](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-7187492081)（3a、4A）、[7187528140](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-7187528140)（不從池外補股）。程式：job `backend/worker/premarket_ai.py`、輸入 `backend/worker/premarket_input.py`、呼叫與核對 `backend/worker/premarket_reading.py`、讀取 `backend/app/premarket_ai.py`；排程與日誌見 [SCHEDULING](../ops/SCHEDULING.md#scheduler-容器的排程serve)，看門狗見 [WATCHDOG](../ops/WATCHDOG.md)。08:45 的 Telegram 與今日名單頁怎麼顯示見[顯示](#顯示)（#1042）；對答案見[對答案](#對答案)（#1043）。

## 輸入快照

每天一份 JSON，整份存進 `premarket_ai_readings.input_json`（送給模型的就是它）。截止點 `cutoff_taipei` 是 D 08:15。截止點管的是 job 自己組進快照的資料（新聞、美股、夜盤、價量籌碼與規則價位）；候選池照它存的那一輪讀，例外見[限制](#限制)。

| 欄位 | 內容 | 時點 |
| --- | --- | --- |
| `session_date`／`list_date` | 判讀的交易日 D、名單日（D 的前一個交易日，`notify.previous_session`） | — |
| `pool` | `phase`（見[候選池](#候選池)）、`count`、`today_list_count`、`today_list_run_id`、`cap` | — |
| `taiex` | 名單日加權指數收盤、漲跌（對前一根）、`freshness`、來源與抓取時間 | 資料日 ≤ 名單日 |
| `us_indices` | 四檔美股（`expected_date` 是 D 前一個週間日）：收盤、漲跌、`trading_date`、`freshness`（`latest`／`us_market_closed`／`stale`）、來源與抓取時間 | `collected_at` ≤ 截止點（08:30、09:30 那兩次 us 不算） |
| `tx_futures.day` | 台指期一般時段（名單日近月）：開高低收、月份、結算價、漲跌；換月那天 `change_status=contract_roll`、不給漲跌 | 資料日 ≤ 名單日 |
| `tx_futures.night` | D 的夜盤（[#1040](https://github.com/YiCheng0608/stock-lab/issues/1040)，`futures_night_bars`）：開高低收、對結算價的漲跌與漲跌幅、量、來源與抓取時間；沒有就 `status=missing` | 夜盤 05:00 收；08:15 的 night job 在截止點後幾秒寫入，所以讀「組輸入時已抓到」的那列 |
| `overnight_news_stats` | 隔夜新聞則數、截止前已有 AI 判讀的則數、各範圍與方向的則數 | 同下 |
| `market_news` | AI 判成 market／theme、方向不是 unknown 的最新 60 則：id、時間、來源、標題、AI 摘要、方向、範圍、題材 id | 同下 |
| `groups` | 候選股所屬族群與 `market_news` 題材的 id→名稱；AI 的 `sectors` 只能用這些 id | — |
| `candidates` | 候選池每檔：`symbol`、`exchange`、`name`、`pool_sources`、`on_today_list`、`price`、`chips`、`groups`、`news`；今日名單的股票另有 `strategy_levels` | 見下 |

- **隔夜新聞**：發布時間（`display_time`）在名單日 13:30 之後、截止點（含）之前，`collected_at` 也在截止點之前；`status=active`、時間不衝突、只收有時間的（`time_precision=datetime`）；同一則（canonical key、dedupe cluster 或 content hash）只算一次。每則的 AI 判讀是 `news_v4`（與等價版本）在截止點前寫好的 `done` 結果；截止點之後才判的記 `ai: not_judged_by_cutoff`，不給方向。輸入自己讀這些新聞，不靠候選池的新聞來源（候選池晚上那輪之前收進來、當時還沒判讀的新聞兩輪都不收，#1048 review [7190403114](https://github.com/YiCheng0608/stock-lab/pull/1048#issuecomment-7190403114)）。
- **每檔**：`price` 是名單日的日線與 1／5／20 日報酬、量（張）、對前 20 日均量的倍數、距 240 根最高價的距離，都用未調整的收盤（`basis=raw`），名單日沒有日線時 `status=missing`；`chips` 是最近 5 個交易日的外資、投信、自營淨買（張）與融資增減，沒有就 `status=missing`；`groups` 是名單日有效的官方產業與題材成員；`news` 是規則關聯（`symbols_json`）點到它的隔夜新聞，最多 5 則。
- **規則價位**（3a）：只有今日名單（`app.candidate_runs.read_run` 的名單日那份）的股票有 `strategy_levels`：名次、策略與今日名單頁顯示的價位（`candidate_view._levels`：`entry`、`entry_zone`、`invalid_price`、`target_1`、`target_2`、`risk_reward`、`earliest_execution_date`）。其他股票**沒有這個欄位**，也沒有任何價位欄。只適用於 `premarket_v1`；AI 名單的價位由 AI 給、程式核對，見 [ai_list_v1](ai_list.md)。
- 不給 `extra_universe`、不給我的追蹤：AI 只判池內的股票。
- 同一個代號在上市與上櫃各有一檔時，只收池內先出現的那檔（輸出以代號對回）。

### 候選池

| `pool_phase` | 什麼時候 | 內容 |
| --- | --- | --- |
| `morning` | 名單日的 [candidate_pool_v1](candidate_pool.md) 有晚上那輪，而且組輸入時早上那輪（08:20 preopen 寫）已寫好 | 晚上那輪入選的股票（依 `rank`），再接早上那輪入選的；`pool_sources` 是 `candidate_pool_items.sources_json` 每列的 `source`、`value`、`data_date`；`pool_item_id` 對回 `candidate_pool_items.id`；`pool` 另記 `version`、`evening_run_id`、`morning_run_id`、`cap`（兩輪合計） |
| `evening` | 有晚上那輪，但組輸入時還沒有早上那輪（preopen 等 news 鎖時 08:21 可能還沒寫） | 只有晚上那輪入選的股票；`morning_run_id` 是 null。不等早上那輪、不延後 08:21（#1041 決定 [7188153160](https://github.com/YiCheng0608/stock-lab/issues/1041#issuecomment-7188153160)） |
| `interim` | 名單日沒有晚上那輪（例如 #1020 部署前、daily 失敗），**退回**暫代池（決定 [7192367021](https://github.com/YiCheng0608/stock-lab/issues/1041#issuecomment-7192367021)） | `pool.fallback=no_candidate_pool_evening`；暫代池：依序收今日名單（`today_list#<名次>`）、名單日的規則訊號（`signals` 的 analysis 列，`conditional`／`active`，`rule_signal:<進場型態>:<狀態>`）、名單日的 H2 名單（`h2#<名次>`）、自選（`watchlist`）、隔夜新聞至少 2 則且最多的 12 檔（`overnight_news:<則數>`）；同一檔在多個來源時全部列在 `pool_sources`，取前 60 檔 |

- 「已寫好」看 run 的 `computed_at` 不晚於組輸入的時點，所以重放過去的日子時，之後才補算的池不會混進來。
- 規則價位仍只看今日名單（不看候選池的 `rule_signal` 來源）；今日名單的股票因上限沒進池時，就不在輸入裡。

## 輸出

JSON schema 釘在 `premarket_reading.OUTPUT_SCHEMA`（雜湊 `SCHEMA_SHA256`），提示詞在 `backend/worker/prompts/premarket_v1.md`（雜湊 `PROMPTS`）；兩者改任何一處都要升版。

| 區塊 | 內容 |
| --- | --- |
| `market` | `stance`（`bullish`／`bearish`／`neutral`）、`confidence`（`high`／`medium`／`low`）、`reasons` |
| `sectors` | 受影響的族群：`group_id`（輸入 `groups` 裡的）、`name`、`direction`（`positive`／`negative`／`mixed`）、`reasons` |
| `candidates` | 輸入每檔恰好一個：`symbol`、`action`（`keep` 維持／`reprice` 依開盤價重算／`defer` 暫緩）、`reprice_rule`、`reasons`（1～3 條）；`reprice_rule` 每檔都要有，`keep`／`defer` 是 `null`，`reprice` 是物件（schema 設成選填時，AC-4 實測模型三檔 `reprice` 都沒給，所以改成必填可為 null）：`max_gap_pct`（開盤漲幅超過就暫緩）、`max_gap_down_pct`（開盤跌幅超過就暫緩，正的小數；開盤已低於 `invalid_price` 一律暫緩）、`min_risk_reward`（重算後低於就暫緩） |
| `data_gaps` | 輸入標缺漏的項目與對判讀的影響 |

- 每條理由 `{text, refs}`：`refs` 引用輸入，`news:<id>`、`us:<代號>`、`tx:night`、`tx:day`、`taiex`、`stock:<代號>:<欄位>`。
- 寫法 4A：動作代碼加「根據……，推論……」，價位只用規則價位或程式依開盤價重算的價位；重算的數字由程式在開盤後算（AI 只給暫緩門檻），不是 AI 寫的。只適用於 `premarket_v1`；AI 名單見 [ai_list_v1](ai_list.md)。

## 核對

依序檢查，第一個不過的就是 `reason`，判讀記 `rejected`；每一項的結果都記在 `checks_json`。

| `reason` | 不過的情況 | 重試 |
| --- | --- | --- |
| `additions_present` | 輸出有 `additions`（#1 決定 7187528140） | 不重試 |
| `schema` | 不符 schema：缺欄、多欄、型別或列舉值不對、`reprice` 的 `reprice_rule` 不是物件或其他動作的不是 `null` | 重試 1 次 |
| `coverage` | 少了輸入的股票、多了輸入以外的股票或同一檔出現兩次（`missing`／`extra`／`duplicate`） | 不重試 |
| `reprice_without_levels` | 沒有可用規則價位的股票判 `reprice`：沒有 `strategy_levels`，或今日名單裡 `strategy_levels.status=no_levels` 的 | 不重試 |
| `unknown_news_ref` | 引用的 `news:<id>` 不在輸入裡，或 `news` 開頭的引用格式不是 `news:<數字>`（例如 `news: 123`、`news:1,2`） | 不重試 |
| `directive_words` | 理由或資料缺口有下單指示：「下單」「掛單」，或「買進／買入／賣出／進場／出場」前面緊接「建議、可、宜、應、請、今日、明日、立即、逢低、開盤、分批、考慮、不宜、暫不……」 | 不重試 |

- **不算指令**（#1002 AC-2 2/2 觀察 2）：引述評等（動詞前 8 個字內有「評等、初評、調升、調降、券商、投顧、分析師、目標價……」，或後面接「評等」），以及名詞用法（後面接「區、價、點」，例如「進場區」）。法人「賣出」「連三日買進」這類事實沒有指令前綴，也不算；單字前綴其實是複合詞的尾字時也不算（`COMPOUND_PREFIXES`：率先、首先、搶先、優先、事先、預先、原先、特別、分別、反應、回應、因應、供應……，例如「外資率先買進」「市場反應賣出壓力」）；但複合詞前面又接著指令前綴時照算（「建議優先買進」「應優先賣出」「可以率先買進」）。「今日」「明日」前綴照算：08:21 的「今日」指還沒開盤的那一盤。
- 另外記、但不判 `rejected`：`unknown_group_ids`（`sectors` 用了 `groups` 以外的 id）、`long_reasons`（超過 120 字的理由數）。
- **非名單股的價位**（3a，`prices_without_levels`，[#1058](https://github.com/YiCheng0608/stock-lab/issues/1058)）：另外記、不判 `rejected`、不重試，`done` 照存；顯示時換掉那幾條（見[顯示](#顯示)）。查的是沒有可用規則價位的股票（同 `reprice_without_levels`：沒有 `strategy_levels`，或 `status=no_levels`）每條理由，以及 `data_gaps` 裡提到這些股票代號（前後不是英數字）或名稱的那幾條；`market`、`sectors` 的理由與有規則價位的股票不查。每筆記 `{symbol, where: "reasons[<i>]"|"data_gaps[<i>]", prices}`，沒有時是 `[]`。
  - 判準只有一個函式 `backend/worker/price_mentions.py` 的 `price_mentions`（只用標準函式庫；verify T30 以路徑載入同一個檔）。先拿掉不算價位的片段，再找**價位**：兩位小數的數字（「收盤 85.30」「1,234.50」），或「元」前面的數字（「85 元附近」「85元」「目標價 85 元」）。
  - **不算價位**：百分比（`3.25%`、`3.25 ％`、`0.50 個百分點`、`2.35 百分點`）、倍數（`1.85 倍`、`0.60～1.20 倍`、`量比 1.85`）、數字後接兆／億／百萬／萬／千／仟或張／股（`營收 12.34 億`、`12.34 億元`、`12.34 百萬元`、`3.5 萬張`、`1,234 張`、`1,000 股`；單位字其實是下一個詞的開頭時照算價位：`85.30 萬一跌破`、`85.30 股價`）、點數（`23,456.78 點`）、日期（`2026-11-26`、`2026/11/26`、`2026.11.26`、`114/11/26`、`11/26`、`11 月 26 日`；前後緊接數字或小數點時不是日期：`85.30/86.00` 是兩個價位）、每股數字（數字前 6 個字內有 EPS／每股盈餘／每股純益／每股淨值／股利／配息／配股／除息，中間沒有「價」與標點：`EPS 3.25 元`、`現金股利 2.50 元`、`除息 2.5 元`；`配息後股價 85.30 元` 照算）、股票的「代號＋名稱」（輸入每檔的 `<代號> <名稱>`，`8069 元太` 不是 `8069 元`；T30 用頁面上每檔的代號與名稱），以及引述的新聞標題（整段等於、或「」『』“”裡有非數字的字且是**整份輸出任一條理由引用的** `news:<id>` 在輸入裡的標題的一部分；只有數字的引號 `「85.30」` 照算）。單獨寫的 `11.26` 分不出是日期，照算價位。
  - 判準改了，`checks_json` 跟著變；舊判讀列不重算，照它存的 `checks_json` 顯示。
- **呼叫失敗**記 `failed`：`timeout`、`invalid_json`（不是 CLI 的 JSON）、`cli_error` 重試 1 次；`rate_limited`、`not_logged_in`、`cli_not_started` 不重試（`news_llm.FATAL_REASONS`）；找不到 CLI（`cli_not_found`）、設了 API 金鑰（`api_key_env_refused`）、提示詞與釘住的雜湊不符（`prompt_hash_mismatch`）都不呼叫；剩下的時間不到 CLI 的 300 秒逾時就不再開始新的呼叫（第一次就不夠記 `no_time`，重試不夠記 `checks_json.retry_skipped=no_time`，保留第一次的結果）。

## 紀錄

三張表都只新增，不更新、不刪除；判讀只在當天早上有效，事後不能重做（模型已知道之後的走勢）。

- **`premarket_ai_readings`**（判讀紀錄）：每次 run 一列，`session_date`＋`prompt_version`＋`role`＋`sequence` 唯一。欄位：`list_date`、`role`（`champion`／`shadow`）、`sequence`、`trigger`、`prompt_version`、`prompt_sha256`、`schema_sha256`、`model_alias`（`sonnet`）、`llm_model`（CLI 回報的實際模型，例如 `claude-sonnet-5-5`）、`pool_phase`、`cutoff_at`（UTC）、`input_hash`、`input_json`、`status`（`done`／`failed`／`rejected`）、`reason`、`error`、`output_json`（模型的結構化輸出）、`checks_json`、`attempts`、`attempts_json`（每次呼叫的耗時、token、原因、raw 的 `raw_payload_id`）、`duration_ms`（各次呼叫合計）、`usage_json`（token 合計）、`ingestion_run_id`（`run_type=premarket_ai`）、`started_at`、`finished_at`。每次呼叫的提示與回應另存 raw（`source=premarket_ai`）。
- **`premarket_ai_stocks`**（每檔判讀）：`done` 的判讀每檔一列：`reading_id`、`instrument_id`、`symbol`、`position`、`on_today_list`、`daily_candidate_id`、`pool_item_id`（讀 candidate_pool_v1 時對回 `candidate_pool_items.id`）、`pool_sources_json`、`levels_json`（今日名單的規則價位，其他是 null）、`action`、`reprice_rule_json`、`reasons_json`。
- **`premarket_ai_scores`**（對答案）：`reading_id`、`stock_id`、`scope`（`market`／`stock`／`overall`）、`subject`、`horizon`、`score_version`、`outcome_json`、`computed_at`；口徑與寫法見[對答案](#對答案)。
- **重跑**：當天同一版本、同一角色已有 `done` 的列就不再呼叫（`skipped reason=already_done`），已存的列不變；只有 `failed`／`rejected` 時再判一次，另加下一個 `sequence`，前面的列不變。當天的判讀是 `done` 那列，沒有時是最新的一列（`app.premarket_ai.day_reading`）。
- **shadow**（#1002 AC-3 D）：`premarket_reading.SHADOW_PROMPT_VERSION` 設了新版本時，同一次 run 在 champion 之後用**同一份輸入**再呼叫一次，另存 `role=shadow` 的列（同一個 `input_hash`）；champion 當天稍早已經 `done` 時，shadow 讀 champion 存下的那份輸入，不重組。shadow 只記錄，不送 Telegram。同時最多一個 shadow。

## 顯示

自 [#1146](https://github.com/YiCheng0608/stock-lab/issues/1146) 起不顯示：API 照留（`GET /api/premarket-ai`），頁面與 Telegram 改讀 AI 名單（[ai_list_v1 顯示](ai_list.md#顯示)）。以下是 API 的契約，以及 #1042～#1146 之間頁面與 Telegram 的寫法（紀錄）。

`app.premarket_ai.view`（#1042）：只讀 champion（`role=champion`、目前的 `premarket_reading.PROMPT_VERSION`）當天的判讀（[重跑](#紀錄)：有 `done` 就是它，沒有時是最新一列）；shadow 與其他版本不顯示。判讀和規則名單分開放，標「AI 推論」、模型（`llm_model`）與提示版本；文案見 [UI_COPY_SPEC §10](../UI_COPY_SPEC.md#10-每日候選)。

**`GET /api/premarket-ai`**：`date`（交易日 D）或 `list_date`（名單日；今日名單頁帶頁面上那份名單的 `trading_date`，取那個名單日最新的交易日），都不給時是最新一天。

| 欄位 | 內容 |
| --- | --- |
| `status` | `done`／`failed`／`rejected`；那天沒有 champion 列（還沒跑、還在跑：呼叫期間不寫 DB，或沒跑）是 `missing` |
| `session_date`、`list_date`、`prompt_version`、`llm_model`、`model_alias`、`pool_phase`、`cutoff_at`、`finished_at` | 那一列的值（時間是 UTC、帶時區）；`missing` 只有 `session_date`／`list_date`（有給時）與 `prompt_version` |
| `reason`、`reason_text` | 不是 `done` 時的 `reason` 與給人看的短句（`premarket_ai.REASON_TEXT`，對照表在 UI_COPY_SPEC §10；不認得的寫「其他原因」）；`done` 是 null |
| `market` | `stance`、`stance_text`（偏多／偏空／中性）、`confidence`、`confidence_text`（把握高／中／低）、`reasons`；不是 `done` 是 null |
| `sectors` | 每個族群的 `group_id`、`name`、`direction`、`direction_text`（可能正向／可能負向／正負互見）、`reasons` |
| `stocks` | `premarket_ai_stocks` 每檔：今日名單的股票在前（依 `rank`），其餘依輸入順序。`symbol`、`exchange`、`name`（輸入快照的）、`on_today_list`、`action`、`action_text`（維持／依開盤價重算／暫緩）、`reprice_rule`、`reprice_text`（「開盤漲幅逾 5.0%、跌幅逾 3.0%或重算後 RR 低於 1.5 倍即暫緩」）、`reasons`；**只有今日名單的股票**另有 `rank` 與 `levels`（`levels_json`，輸入時的規則價位，3a），其他股票沒有這兩個鍵 |
| `data_gaps` | AI 寫的資料缺口（推論） |
| `input_gaps` | 輸入快照標缺漏的事實（`premarket_ai.input_gaps`）：加權指數沒有、美股未取得或非最新、台指期日盤／夜盤沒有、截止前沒判讀的隔夜新聞則數、每檔名單日沒有日線、沒有籌碼、規則價位不完整 |

- 每條理由 `{text, refs}`：`refs` 每個是 `{ref, kind, label}`；`news:<id>` 是 `kind=news`、`news_id` 與輸入快照裡那則的標題（頁面連到 `/news/<id>`），`us:<代號>`、`tx:night`、`tx:day`、`taiex`、`stock:<代號>:<欄位>` 是給人看的名稱，其他是 `kind=other`、`label` null（頁面不列）。
- 價位（3a）：頁面只在今日名單的股票寫「規則價位 進場／進場區 …｜停損 …｜目標一 …」（`levels`，事實，不標推論），其他股票不寫任何價位；依開盤價重算的價位由程式在開盤後算，08:45 還沒有。
- 價位被核對記下的理由（`checks_json.prices_without_levels`，見[核對](#核對)）：`view` 把那幾條理由的 `text` 換成「理由含價位，未顯示」（`PRICE_HIDDEN_TEXT`）、`refs` 清空，提到該股的 `data_gaps` 那條也換成同一句；API、Telegram（文字版與卡片）與今日名單頁都讀 `view`，拿不到原文。原文仍在 `output_json`。
- **Telegram**（#1042～#1146，已不送）：`done` 時在隔夜美股之後一段「早盤 AI 判讀（AI 推論）」：模型與提示、大盤與前 2 條理由、族群（前 5 個，各第一條理由）、每檔動作與第一條理由（今日名單的股票在前，最多 20 檔，其餘寫「另 N 檔的 AI 判讀見今日名單頁」），段內不寫價位（今日名單的價位在上面的名單）。文字版超過 4096 字時先從 AI 段最後一檔往前刪，再刪名單的列。`failed`／`rejected` 不送這段，名單標題下一行「今日 AI 判讀失敗：<reason_text>」；`missing` 寫「今日 AI 判讀尚未完成」。讀判讀或組 AI 段時出錯（`view` 或 `notify.ai_view` 丟例外，例如判讀的形狀和這一版不同）寫「今日 AI 判讀無法讀取」，日誌記 `--- premarket_ai unreadable error=<例外型別>`，規則名單與隔夜美股照送。notify 不等判讀、不拿判讀的鎖。
- **今日名單頁**（#1042～#1146，已拿掉）：只在「今日名單」分頁、名單之後、熱門族群之前，讀頁面那份名單的 `list_date`。#1146 起 verify today T30 改檢查 AI 名單。

## 對答案

口徑 `premarket_score_v1`：#1043 決定 [7196577181](https://github.com/YiCheng0608/stock-lab/issues/1043#issuecomment-7196577181)（依據 #1002 [AC-3](https://github.com/YiCheng0608/stock-lab/issues/1002#issuecomment-7108600534) 的 B、D），在看任何結果之前寫死；之後要改就是新的 `score_version`，舊列不動。常數在 `app.premarket_score.RULES`，它與本節全文由 `test_premarket_score` 的快照釘住。計算是 daily 的最後一步 `premarket_score`（`backend/worker/premarket_score.py`，[SCHEDULING](../ops/SCHEDULING.md#日誌與-run-記錄)）與 `worker.cli premarket-score`；純計算在 `backend/app/premarket_score.py`。早盤 AI 判讀不能回測（模型已知道過去的走勢），只能從上線那天起逐日記錄、用之後才發生的走勢對答案。

- **對哪些判讀**：每個交易日 D、每個 `prompt_version`＋`role` 的 `done` 判讀各算一套；`failed`／`rejected` 不算分，月報另列天數。champion 與 shadow、不同提示版本各自成套，不混。
- **交易日**：D 是第 1 個交易日，T+N 是 D 起第 N 個台股交易日（`pipeline.taiwan_bar_dates`：名單日之後有台股日 K 的日子，美股在台股休市日的列不算）。休市日沒有判讀，也不算進 N。名單日之後的第一個有日 K 的日子不是 D 時，先以 `app.coverage.collect_states`（daily 補抓判休市的同一條規則）判 D：確認休市（`non_trading`）才把大盤與整體記 `no_data`（`no_session`）、不算每檔；不是確認休市（例如 collect 失敗、補抓還沒成功）就整筆判讀這次不寫，等 D 的日 K 補上後照常算。
- **報酬**：買進價加 5 bps、賣出價減 5 bps，再扣 30 bps 來回成本（`app.tracking` 的假設）；價格用 `pipeline._tracking_inputs` 的除權息因子換回名單日的基準。

### 大盤

`scope=market`、`subject=market`，`horizon` 是 `d0`（D 開盤→D 收盤）與 `t5`（D 開盤→T+5 收盤）。

- 開盤價用 D 的加權指數日 K 的 `open`（collect 的指數日 K，#552）；D 的列只有收盤（`open` 是空的、`price_reason` 有值或來源仍是 `twse_index`）時記 `no_data`（`no_open`），不拿前收代替。
- 漲跌 `r`：|r| ≤ 0.5%（`d0`）／1.5%（`t5`）是 `flat`，否則 `up`／`down`。`bullish` 對 `up`、`bearish` 對 `down`、`neutral` 對 `flat` 是 `hit=true`，其他是 `false`。
- `outcome_json`：`stance`、`confidence`、`open`、`close`、`close_date`、`return`、`band`、`realized`、`hit`、`status`（`scored`／`no_data`）、`reason`。

### 每檔

`scope=stock`、`subject` 是代號、`stock_id` 是 `premarket_ai_stocks.id`，`horizon` 是 `t5`、`t20`。每檔兩種結果：

1. **`open_hold`**（池內每檔都有）：D 開盤買、T+N 收盤賣。D..T+N 少一根交易日的日 K 記 `incomparable`（`missing_bar`），有停牌（`app.tracking` 的停牌判斷）記 `suspended_in_window`，價格不能用記 `no_price`；這些不算報酬。
2. **`levels`**（只有附規則價位的今日名單股票；`strategy_levels.status=no_levels` 的沒有）：`tracking_v2`（`track_path`＋`settle`，名單日是 level date，D 是 session 1，最多 20 個交易日），不能成交照 `tracking_v2` 的原因碼（`not_filled_by_horizon`、`gap_above_target`、`gap_below_invalid`、停牌），不算報酬。
   - `original`：照 `levels_json` 的規則價位（突破用 `entry_zone.low` 當突破價，拉回用 `entry_zone.low`～`high`）。`keep`、`defer`（假設做了的結果）、`reprice` 都記。
   - `repriced`（只有 `reprice`）：程式依開盤價重算的價位，唯一的算法是 `app.premarket_score.reprice`，顯示重算價位的地方都呼叫它。停損價 `invalid_price` 與目標價 `target_1` 不動，進場改成 D 開盤價 O；`gap = O ÷ 名單日收盤 − 1`、`stop_distance = O − invalid_price`、`risk_reward = (target_1 − O) ÷ (O − invalid_price)`。依序檢查 `O ≤ invalid_price`（`open_at_or_below_invalid`）、`O ≥ target_1`（`open_at_or_above_target`）、`gap > max_gap_pct`（`gap_up_over_max`）、`−gap > max_gap_down_pct`（`gap_down_over_max`）、`risk_reward < min_risk_reward`（`risk_reward_under_min`），任一成立就是 `reprice_deferred`（全部列在 `conditions`），不算重算後的結果；否則是 `repriced`，`repriced_result` 是 D 開盤成交後照 `tracking_v2` 的結果。D 沒有日 K 或名單日沒有收盤時記 `no_data`。
- **有效動作** `effective_action`：`keep`；`reprice` 沒被暫緩是 `reprice`；`defer` 與 `reprice_deferred` 是 `defer`。
- 我的追蹤（#1002 AC-3 B 4）不算：輸入沒有我的追蹤（見[輸入快照](#輸入快照)）。

### 整體

`scope=overall`、`subject=overall`，`horizon` 是 `t5`、`t20`。每組列筆數、可比數、平均、中位數與不能比的原因碼；`tracking_v2` 的組另列成交數。

- **母體**：D 有日 K、沒停牌的 `stock`／`ipo`（上市與上櫃，不含 ETF，不設流動性門檻）的 `open_hold` 等權平均。
- **AI 版本**：有效動作是 `keep`／`reprice` 的股票的 `open_hold` 等權平均；`reprice` 也用 `open_hold`，因為兩者都是 D 開盤進。超額＝平均－母體。
- **規則版本**：今日名單全部（`on_today_list`）的 `open_hold` 等權平均與超額；今日名單 0 檔記 `no_list`，不算 0。
- **AI 判讀的價值**：
  - `value_open_hold`＝AI 版本的平均－有效動作 `defer` 的平均（同一個候選池）。這是換版條件用的那一個（T+5）。
  - `levels.value`＝今日名單內 `keep` 的 `original` 與 `reprice` 的 `repriced_result` 的平均－`defer`／`reprice_deferred` 的 `original` 的平均。只當參考，不進換版條件。
  - 任一邊沒有可比的結果就記 `null`（`empty_side`）。
- `tracking_v2` 有停損與達標，和母體的 `open_hold` 不是同一個口徑，所以 `levels` 只列平均與價值，不算對母體的超額。
- `outcome_json` 另記 `reading_id`、`pool_phase`、`today_list_count`、`population`（`members`、`comparable`、`mean`）、各有效動作的 `open_hold`。

### 寫入與重跑

- 一個 horizon 的最後一個交易日已有日 K（到 daily 的目標日為止）才寫那個 horizon 的列；還沒到就不寫，不寫 pending 列。之後的日子都不讀。
- 寫了不改：同一個 `reading_id`＋`scope`＋`subject`＋`horizon`＋`score_version` 已有就跳過（表上的 unique），所以同一天重跑、或錯過幾天之後的 daily 都只補還沒寫的列。日 K 事後更正也不重算；要重算就是新的 `score_version`。
- 個股在 T+N 之前下市或長期停牌：市場已到 T+N 卻少了那根，就記 `incomparable`（`missing_bar`）照寫，不永遠等。

### 月報與去留

- `worker.cli premarket-score-report --month YYYY-MM` 產 markdown（讀 DB、不寫）：每個 `prompt_version`＋`role` 一節，從上線起累積到該月底的判讀天數（`done`／`failed`／`rejected`）、大盤 `d0`／`t5` 判對率、判讀×實際的 3×3 表與各判讀下的平均漲跌、各有效動作的 `open_hold` 與 `levels` 平均、AI 版本與規則版本對母體的超額、AI 判讀的價值。大盤當日已對答案的交易日未滿 60 天標 `insufficient_sample`。
- 統籌每月第一個交易日（和 #1004 的每月檢討同一天）跑它，以 `回報：` 貼 #1；CLI 不自己貼。
- 60 個交易日滿才給「AI 版本比規則版本好、差或分不出」的結論，由使用者決定去留；中途不改口徑。
- **換版**（#1002 AC-3 D）：shadow 上線後，同一批交易日上，新版本的大盤當日判對率不低於舊版本，**而且** `value_open_hold` 的 T+5 平均高於舊版本，兩項都過才換；同一批交易日未滿 20 天標 `insufficient_sample`。月報有 shadow 時列這兩項。換版由統籌在 #1 提案、使用者決定。

## 判錯清單與改版提案

每月檢討挑出上個月判錯的案例，再讓 AI 讀這些案例提出提示詞的修改（[#1069](https://github.com/YiCheng0608/stock-lab/issues/1069)，#1004 第 3、4 點）。規則由統籌在第一次真跑前決定（[決定 7203530697](https://github.com/YiCheng0608/stock-lab/issues/1069#issuecomment-7203530697)，回覆[提問 7203458168](https://github.com/YiCheng0608/stock-lab/issues/1069#issuecomment-7203458168)），寫死在 `tools/research/premarket_errors.py` 與 `tools/research/prompt_proposal.py` 的常數與函式；要改就加各自的 `VERSION`。只讀[對答案](#對答案)已寫好的 `premarket_score_v1` 列，不重算；不改口徑、不改 `premarket_v1` 與 `OUTPUT_SCHEMA`。清單與提案只負責列出：上線 shadow、換版由統籌在 #1 提案，使用者決定。

### 判錯清單（`premarket_errors.py`）

`python tools/research/premarket_errors.py --db <副本> --month YYYY-MM --out <目錄>`：每月檢討的子入口（[evidence 每月檢討](evidence.md#每月檢討)），寫 `cases.json`（提案命令讀它）與 `cases.md`。只讀，拒絕同 `exit_research`。

- **哪些判讀**：`role=champion`、`prompt_version` 等於跑的時候程式裡的 `premarket_reading.PROMPT_VERSION`、`done` 的判讀。提案改的是現在這一版，舊版的案例不拿來改新版：換版那個月，其他版本的 champion 判讀只列版本與天數（`other_versions`）。shadow 不收（shadow 只用它上線之後的日子比，不拿提出修改時看過的案例）。`failed`／`rejected` 只列天數，取法同月報：當天有 `done` 就算 done，沒有時取最新一列。
- **判錯**（每份判讀的每檔最多一個案例；常數 `ERROR_EXCESS = 0.03`、`STOP_TRIGGER = "invalidated"`、`TARGET_TRIGGER = "target_1_hit"`）：

  | 類 | 判錯 | 判對（對照） |
  | --- | --- | --- |
  | `market` 大盤 | `d0`、`status=scored`、`hit=false`（`t5` 只列，不收） | `hit=true` |
  | `defer` 暫緩卻漲 | 有效動作 `defer`（含 `reprice_deferred`，另標）、T+5 `open_hold` 減同一份判讀 `overall` T+5 的 `population.mean` ≥ +3 個百分點 | ≤ −3 個百分點 |
  | `levels_stop` 維持卻觸停損 | 有規則價位（`app.premarket_score.has_levels`）、有效動作 `keep` 看 T+20 `levels.original`，`reprice` 看 `levels.repriced_result`：`first_trigger` 是 `invalidated` | 先觸 `target_1_hit` |
  | `no_levels_keep` 沒有規則價位的維持卻跌 | 有效動作 `keep`、T+5 對母體超額 ≤ −3 個百分點（沒有規則價位不能判 `reprice`，核對會擋） | ≥ +3 個百分點 |

  - 有規則價位的 `keep`／`reprice` 只看停損那一條，不再套 ±3 個百分點；介於兩個門檻之間的不算對也不算錯。
  - 族群不收：`premarket_score_v1` 沒有對族群對答案。
  - 該月判讀中，`open_hold` 或 `levels` 結果是 `incomparable` 的記「不能比」筆數，分數列還沒寫的記 `pending`，已寫但結果落在之後月份的記 `later_month`；三種都只在判讀所在的月份計數。不能比的不收也不算判對；後兩種到結果出來的那個月才收。
- **歸哪個月**：案例歸**結果出來的那個月**：大盤是 D（`close_date`），個股是那個期間的最後一個交易日（`open_hold.exit_date`）。T+20 的結果約一個月後才寫，照判讀日歸月的話，月底那些判讀到月初跑時大多還沒對答案、下個月也不再收；照結果月歸，每筆剛好收一次，而且月初跑時都已寫好。判讀天數、`failed`／`rejected` 天數與提案門檻的大盤天數，則照 `session_date` 在該月的判讀算；提案門檻的判錯筆數照結果月份，即這個月收進來的判錯（截到 30 筆以前）（[決定 7205021451](https://github.com/YiCheng0608/stock-lab/issues/1069#issuecomment-7205021451)）。
- **筆數與排序**（`MAX_CASES = 30`）：判錯最多 30 筆，大盤全收（依日期），個股依排序鍵的絕對值大的先（同值依日期、代號）；排序鍵是案例那個期間的 `open_hold` 對母體超額（停損類用 T+20，其他用 T+5；不能比時當 0）。另附對照：每一類取和收進來的判錯同樣筆數的判對案例，排序相同（大盤依 `|return|`），讓 AI 不會只看錯的就改（#1004 第 4 點）。
- **每筆案例**：`case_id`（`<session_date>:<market|代號>:<類>`）、`kind`（`error`／`control`）、當時的輸入（那檔在 `input_json.candidates` 的資料；`sessions[<日期>].market_input` 是大盤用到的部分：加權指數、美股、台指期、隔夜新聞統計與大盤理由引用的新聞）、AI 的動作、`reprice_rule`、規則價位與理由，以及結果（`outcome`）。
- **理由引用的種類**（#1004 第 3 點）：`cases.md` 附一張表，不進清單：列是 `refs` 的種類（`news`、`us:<代號>`、`tx:night`、`tx:day`、`taiex`、`stock:<欄位>`），欄是引用的理由數與判對率。判對率的分母是該月 champion `done` 判讀的全部判斷：大盤看 `hit`，每檔看 T+5 對母體超額的正負（`keep`／`reprice` 為正、`defer` 為負算對），和判錯的 ±3 個百分點不是同一個口徑。要不要列成研究候選另議。
- **提案門檻**（`proposal_gate`，`MIN_MARKET_DAYS = 15`、`MIN_ERRORS = 10`）：`SHADOW_PROMPT_VERSION` 有值時是 `shadow_exists`「已有 shadow，不提案」（同時最多一個 shadow）；否則該月 champion 大盤 `d0` 已對答案的交易日 ≥ 15、而且判錯 ≥ 10 筆才是 `ok`，不到是 `insufficient_sample`「樣本不足，不提案」。`cases.json` 另記 `month_stats`（大盤 `d0` 判對率、各有效動作 T+5 `open_hold` 平均），給提案用。

### 改版提案（`prompt_proposal.py`）

`python tools/research/prompt_proposal.py --cases <目錄>/premarket_errors/cases.json --out <新的空目錄> [--attempt 2]`：和每月檢討並列、不是子入口（它要 CLI 登入，每次的結果也不同）。只讀 `cases.json` 與目前的提示詞 `backend/worker/prompts/<cases.json 的 prompt_version>.md`；不讀也不寫 DB，不改 repo 的檔。在哪裡跑、怎麼跑見 [evidence 每月流程](evidence.md#前瞻驗證-h1)第 4 步（scheduler 容器）。

- `proposal_gate` 不是 `ok` 就不呼叫，記 `skipped`（exit 0）。
- **呼叫**：一次 `claude -p`，沿用 `worker.news_llm` 的呼叫層（`preflight`、`cli_arguments`、`run_claude_cli`、`parse_envelope`）：訂閱登入，設了 API 金鑰（`api_key_env_refused`）或找不到 CLI（`cli_not_found`）就不呼叫；不帶工具、在空目錄跑；模型 `opus`；逾時 `news_llm.CALL_TIMEOUT_SECONDS`。提示詞是 `tools/research/prompts/prompt_proposal_v1.md`，雜湊釘在 `prompt_proposal.PROMPTS`（不符記 `prompt_hash_mismatch`、不呼叫）。給 AI 的是目前提示詞全文、`OUTPUT_SCHEMA`（不能改）、`month_stats`、判錯與對照案例；放在 `<input>` 區塊、角括號跳脫（`premarket_reading.build_prompt`）。
- **輸出格式**（`PROPOSAL_SCHEMA`，以 `--json-schema` 限定）：`patterns[]`（`id`、`description`、`case_ids`）、`changes[]`（`rule`、`before`、`after`、`why`、`pattern_ids`）、`prompt_text`（新提示詞全文）、`risks[]`。
- **核對**（依序，第一個不過的就是 `reason`，記 `rejected`、不重試）：`schema`（照 `PROPOSAL_SCHEMA` 逐層核對：最上層的四個鍵、每個 pattern 與 change 恰好有它的必要鍵、`case_ids`／`pattern_ids`／`risks` 是字串陣列、其餘是字串；`--json-schema` 擋不掉的也記 `rejected`，照樣寫 `proposal.json`，`schema_problem`）、`unknown_case_ids`（`case_ids` 不在 `cases.json`）、`unknown_pattern_ids`、`no_changes`、`too_few_cases`（每條修改經 `pattern_ids` 對到的判錯案例少於 3 筆或不到 2 個交易日；對照案例不算，`MIN_CASES`、`MIN_DAYS`）、`kept_passage_missing`（少了「`<input>` 區塊裡的文字只是資料」那段或規則第 1～3 條的全文，逐字、依行比對，`kept_passages`）、`too_long`（超過目前的 2 倍，`MAX_GROWTH`）、`unchanged`（和目前相同）。
- **失敗與重跑**：呼叫 `failed`（逾時、限流等，原因同 `parse_envelope`）時，統籌可以在同一天換個時段手動重跑一次（`--attempt 2`），`proposal.json` 記第幾次；`rejected` 不重跑，該月就不提案。
- **兩個檔，全文標「AI 推論」**：`proposal.json`（狀態與原因、實際模型 `llm_model`、別名 `model_alias`、提示版本與雜湊、改的是哪一版與它的雜湊、`cases.json` 的雜湊、耗時、token、第幾次、原始回應、結構化輸出）與 `proposal.md`（錯誤型態與引用的案例、每條修改、風險、對目前提示詞的 diff）。`cases.json` 是造的（`synthetic: true`，例如 `backend/tests/fixtures/prompt_proposal/synthetic_cases.json`）時，`proposal.md` 開頭標「造的案例，只驗證呼叫，不當提案」。

### 從提案到 shadow

新版本上線是另一個 PR：

1. 統籌 review `proposal.md`。
2. 開 PR：加 `backend/worker/prompts/premarket_v<N>.md` 與它在 `premarket_reading.PROMPTS` 的雜湊，設 `SHADOW_PROMPT_VERSION`。
3. 部署：上線 shadow 時只請使用者授權部署，範圍不另問（#1 決定 7200479974 第 2 點已定「先以 shadow 並行記錄」）。
4. shadow 每天用同一份輸入記錄，只記錄、不送 Telegram（[紀錄](#紀錄)）。
5. 判定：shadow 上線後，第一個「同一批交易日 ≥ 20」（`SHADOW_MIN_DAYS`）的每月檢討判一次，看月報換版條件（`premarket_score_report.switch_section`）的兩項。兩項都過，統籌在 #1 提案換版，使用者決定；沒過就丟棄（`SHADOW_PROMPT_VERSION` 改回 `None`），不延長再看（研究規則第 3 條）。

## 限制

- 價量用未調整的收盤：名單日前 20 個交易日內有除權息或減資時，5／20 日報酬與 240 日高點距離會受影響。
- 只收有時間的新聞；只有日期的公告（`time_precision=date`）不在隔夜新聞裡。
- 美股以截止點前抓到的為準：07:30 那次沒抓到 D 前一個美股交易日時，輸入是較舊的值並標 `stale`，不等 08:30。
- **候選池早上那輪不受 08:15 截止**（#1041 決定 [7194510455](https://github.com/YiCheng0608/stock-lab/issues/1041#issuecomment-7194510455)）：`pool_phase=morning` 讀 08:20 preopen 算好的那一輪，它的成員與 `pool_sources` 的值（例如 `news_count`、`directions`）是到 preopen 檢查時點（08:2x）的資料，含 08:15 之後才收進、才判讀的新聞。不另外過濾也不重算：早上那輪一定在 08:15 之後才算好，嚴格照 08:15 切就永遠用不到它；差的只有幾分鐘，都在 09:00 開盤之前。輸入裡每檔自己的 `news` 與 `market_news` 仍照 08:15 截止。
- **重放過去的日子**（`--dry-run --date`）：只有新聞、新聞的 AI 判讀、美股、夜盤與候選池有用抓取或計算時間限制；今日名單、訊號價位、自選（`is_watchlisted` 是現在的值）、H2 名單、價量籌碼與美股的品質列都讀現在存的值。排程當天 08:21 的判讀不受影響。
- **寫入**：呼叫期間不寫 DB，呼叫結束、再查一次維護標記之後才在同一個交易裡寫 run、raw、判讀與每檔列；被 serve 的保險時間殺掉或中途例外時，DB 什麼都沒寫（不會留下 `running` 的 run），只有已寫到磁碟的 raw 檔。
