<!-- owns: premarket_ai_v1、早盤 AI 判讀的輸入快照、早盤 AI 判讀的核對、早盤 AI 判讀紀錄表 -->
# premarket_ai_v1

早盤 AI 判讀：每個交易日 D 08:21（台北），用截止 D 08:15 的隔夜新聞、美股、台指期夜盤，以及候選池每檔的價量籌碼、產業題材（今日名單的股票另附規則價位），呼叫一次 `claude -p`（sonnet），產出大盤、族群與每檔「維持／依開盤價重算／暫緩」與理由；核對後存檔，存了不改。判讀是**推論**，不是買賣訊號，也不改今日名單、分數或規則價位。依據：#1002 的評估（[AC-2 1/2](https://github.com/YiCheng0608/stock-lab/issues/1002#issuecomment-7118193790)、[AC-2 2/2](https://github.com/YiCheng0608/stock-lab/issues/1002#issuecomment-7118209417)、[AC-3](https://github.com/YiCheng0608/stock-lab/issues/1002#issuecomment-7108600534)）與 #1 決定 [7187492081](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-7187492081)（3a、4A）、[7187528140](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-7187528140)（不從池外補股）。程式：job `backend/worker/premarket_ai.py`、輸入 `backend/worker/premarket_input.py`、呼叫與核對 `backend/worker/premarket_reading.py`、讀取 `backend/app/premarket_ai.py`；排程與日誌見 [SCHEDULING](../ops/SCHEDULING.md#scheduler-容器的排程serve)，看門狗見 [WATCHDOG](../ops/WATCHDOG.md)。08:45 的 Telegram 與今日名單頁怎麼顯示是 #1042，對答案的計算是 #1043。

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
- **規則價位**（3a）：只有今日名單（`app.candidate_runs.read_run` 的名單日那份）的股票有 `strategy_levels`：名次、策略與今日名單頁顯示的價位（`candidate_view._levels`：`entry`、`entry_zone`、`invalid_price`、`target_1`、`target_2`、`risk_reward`、`earliest_execution_date`）。其他股票**沒有這個欄位**，也沒有任何價位欄。
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
- 寫法 4A：動作代碼加「根據……，推論……」，價位只用規則價位或程式依開盤價重算的價位；重算的數字由程式在開盤後算（AI 只給暫緩門檻），不是 AI 寫的。

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
- **呼叫失敗**記 `failed`：`timeout`、`invalid_json`（不是 CLI 的 JSON）、`cli_error` 重試 1 次；`rate_limited`、`not_logged_in`、`cli_not_started` 不重試（`news_llm.FATAL_REASONS`）；找不到 CLI（`cli_not_found`）、設了 API 金鑰（`api_key_env_refused`）、提示詞與釘住的雜湊不符（`prompt_hash_mismatch`）都不呼叫；剩下的時間不到 CLI 的 300 秒逾時就不再開始新的呼叫（第一次就不夠記 `no_time`，重試不夠記 `checks_json.retry_skipped=no_time`，保留第一次的結果）。

## 紀錄

三張表都只新增，不更新、不刪除；判讀只在當天早上有效，事後不能重做（模型已知道之後的走勢）。

- **`premarket_ai_readings`**（判讀紀錄）：每次 run 一列，`session_date`＋`prompt_version`＋`role`＋`sequence` 唯一。欄位：`list_date`、`role`（`champion`／`shadow`）、`sequence`、`trigger`、`prompt_version`、`prompt_sha256`、`schema_sha256`、`model_alias`（`sonnet`）、`llm_model`（CLI 回報的實際模型，例如 `claude-sonnet-5-5`）、`pool_phase`、`cutoff_at`（UTC）、`input_hash`、`input_json`、`status`（`done`／`failed`／`rejected`）、`reason`、`error`、`output_json`（模型的結構化輸出）、`checks_json`、`attempts`、`attempts_json`（每次呼叫的耗時、token、原因、raw 的 `raw_payload_id`）、`duration_ms`（各次呼叫合計）、`usage_json`（token 合計）、`ingestion_run_id`（`run_type=premarket_ai`）、`started_at`、`finished_at`。每次呼叫的提示與回應另存 raw（`source=premarket_ai`）。
- **`premarket_ai_stocks`**（每檔判讀）：`done` 的判讀每檔一列：`reading_id`、`instrument_id`、`symbol`、`position`、`on_today_list`、`daily_candidate_id`、`pool_item_id`（讀 candidate_pool_v1 時對回 `candidate_pool_items.id`）、`pool_sources_json`、`levels_json`（今日名單的規則價位，其他是 null）、`action`、`reprice_rule_json`、`reasons_json`。
- **`premarket_ai_scores`**（對答案）：`reading_id`、`stock_id`、`scope`（`market`／`stock`／`overall`）、`subject`、`horizon`、`score_version`、`outcome_json`、`computed_at`；口徑與計算是 #1043，本單只建表。
- **重跑**：當天同一版本、同一角色已有 `done` 的列就不再呼叫（`skipped reason=already_done`），已存的列不變；只有 `failed`／`rejected` 時再判一次，另加下一個 `sequence`，前面的列不變。當天的判讀是 `done` 那列，沒有時是最新的一列（`app.premarket_ai.day_reading`）。
- **shadow**（#1002 AC-3 D）：`premarket_reading.SHADOW_PROMPT_VERSION` 設了新版本時，同一次 run 在 champion 之後用**同一份輸入**再呼叫一次，另存 `role=shadow` 的列（同一個 `input_hash`）；champion 當天稍早已經 `done` 時，shadow 讀 champion 存下的那份輸入，不重組。shadow 只記錄，不送 Telegram。同時最多一個 shadow。

## 限制

- 價量用未調整的收盤：名單日前 20 個交易日內有除權息或減資時，5／20 日報酬與 240 日高點距離會受影響。
- 只收有時間的新聞；只有日期的公告（`time_precision=date`）不在隔夜新聞裡。
- 美股以截止點前抓到的為準：07:30 那次沒抓到 D 前一個美股交易日時，輸入是較舊的值並標 `stale`，不等 08:30。
- **候選池早上那輪不受 08:15 截止**（#1041 決定 [7194510455](https://github.com/YiCheng0608/stock-lab/issues/1041#issuecomment-7194510455)）：`pool_phase=morning` 讀 08:20 preopen 算好的那一輪，它的成員與 `pool_sources` 的值（例如 `news_count`、`directions`）是到 preopen 檢查時點（08:2x）的資料，含 08:15 之後才收進、才判讀的新聞。不另外過濾也不重算：早上那輪一定在 08:15 之後才算好，嚴格照 08:15 切就永遠用不到它；差的只有幾分鐘，都在 09:00 開盤之前。輸入裡每檔自己的 `news` 與 `market_news` 仍照 08:15 截止。
- **重放過去的日子**（`--dry-run --date`）：只有新聞、新聞的 AI 判讀、美股、夜盤與候選池有用抓取或計算時間限制；今日名單、訊號價位、自選（`is_watchlisted` 是現在的值）、H2 名單、價量籌碼與美股的品質列都讀現在存的值。排程當天 08:21 的判讀不受影響。
- **寫入**：呼叫期間不寫 DB，呼叫結束、再查一次維護標記之後才在同一個交易裡寫 run、raw、判讀與每檔列；被 serve 的保險時間殺掉或中途例外時，DB 什麼都沒寫（不會留下 `running` 的 run），只有已寫到磁碟的 raw 檔。
