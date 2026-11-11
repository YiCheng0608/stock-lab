<!-- owns: candidate_score_v1、candidate_score_v2、candidate_score_v3、candidate_score_v4、candidate_score_v5、candidate_score_v6、candidate_score_v7、候選 AI 進出點說明 -->
# candidate_score

## candidate_score_v1

評分只用於排序，不代表勝率或預期報酬，不改變策略判定。設定在 `backend/app/domain.py` 的 `CANDIDATE_SCORE_V1`（快照由 `backend/tests/test_candidates.py` 釘住）；權重、子項、窗口、門檻、名單長度或理由規則任一改變都必須升版，舊版的 `candidate_runs`／`daily_candidates` 保留不改。實作在 `backend/worker/candidates.py`，由 `daily` 的 candidates 步驟或 `worker.cli candidates` 執行（[現有 worker CLI](../ops/CLI.md#現有-worker-cli)）。

**候選池**：T 日 `analysis` namespace 的 `breakout_v1`／`pullback_v1` 訊號，同時符合：analyze 在 T 日判定可行動（`rule_evidence_json.actionable = true`，即當日 `conditional`；evaluate 之後把狀態推進成 `active`、`target_1_hit`、`invalidated` 等不影響入池，重算舊日期時池子相同；沒有此旗標的舊列改看狀態是否為 `conditional`、`active`、`target_1_hit`、`target_2_hit`、`invalidated`、`incomparable` 之一）、策略列為現行公式（`active`）、標的為 active 的 `stock`／`ipo`（ETF、指數一律排除）、entry type 與策略相符且通過 `validate_signal_levels`（含 RR ≥ 1.5，見[價位、ETF 與生命週期](README.md#價位etf-與生命週期)）、T 日有非停牌日線。排除原因與計數寫入 `candidate_runs.exclusions_json`。

**分項**（0～1，1 為較佳端）：percentile 一律為同日 mid-rank `(less + (equal−1)/2)/(n−1)`，只有 1 個值時 0.5（與 `hot_group_v1` 同函式），「較低為佳」的子項先取負再算。分項是有值子項的加權平均，子項全缺才為 null；缺資料不補 0。

| 分項 | 權重 | 子項（權重） | 原值 | percentile 母體 |
| --- | --- | --- | --- | --- |
| technical | 0.35 | 量比（0.5） | `volume[T]/mean(volume[T-20:T-1])`；breakout 越高越好、pullback 越低越好（量縮回檔） | 同日同策略的候選池 |
| | | 距離（0.5） | breakout `close[T]/max(high[T-20:T-1])−1`；pullback `abs(close[T]/MA20[T]−1)`；越小越好 | 同上 |
| | | RR（0） | `(target_1−entry)/(entry−invalid)`；只顯示不計分：`risk_levels` 以固定 1.6R 設目標，RR 只差四捨五入，沒有鑑別力 | — |
| chips | 0.30 | 法人 5 日（0.4） | 三大法人 5 日淨股數／20 日均量（與策略同公式） | 同日 active stock／ipo 全市場有值者 |
| | | 法人 20 日（0.3） | 三大法人 20 日淨股數／20 日均量；20 個有效交易日都要有籌碼列 | 同上 |
| | | 融資 5 日（0.3） | 5 日融資餘額變動比（與策略同）；越低越好 | 同上 |
| news_sentiment（推論） | 0.15 | 淨方向（1） | 見下 | 同日 active stock／ipo 全市場 |
| group | 0.20 | 榜內 percentile（1） | 所屬合格群組 `1−(rank−1)/(同榜有排名群組數−1)` 的最大值，同榜只有 1 群組時 0.5；不再做跨股 percentile | — |

- **籌碼**取 T（含）以前最後 20 根非停牌日線，最後一根必須是 T；任一籌碼欄缺、日線不足或量非正時該子項為 null。
- **新聞**：窗口為 T−2～T 三個台北日曆日；`datetime` 精度的時間以 UTC＋8 換日，`date` 精度直接用日期。只算 `status=active`、`time_consistency=verified`、`symbols_json` 規則命中（裸代號或 `交易所:代號`）的新聞；方向取設定中 `llm_prompt_version`（v1 為 `news_v1`，[v2](#candidate_score_v2)、[v3](#candidate_score_v3) 為 `news_v2`，[v4](#candidate_score_v4)、[v5](#candidate_score_v5) 為 `news_v3`）且 `llm_status=done` 的 `ai_impact_direction`：positive +1、negative −1、mixed 0，unknown 與未判讀不計分（計入 `unscored`）。原值為加總；窗口內有任一 `run_type=news` 的 success／partial 收集 run（`run_date` 為台北日期，`worker.cli news` 預設取台北今日）時，沒有關聯新聞是有效 0，否則全市場此分項為 null（`news_collection_missing`）。多數股票原值為 0，mid-rank 會落在中段；`instruments_with_news` 記有新聞的股票數。只用計算當下 DB 已有的資料，同日不重算。
- **族群**：群組須 active、T 日成員有效、榜別為產業或題材（新上市觀察與 ETF 分區不算），且 T 日分數列符合 `app.decision._qualified_groups_for_instrument` 的條件（`complete`、合格成員 ≥3、有排名、TAIEX 基準、非 ETF 榜）；不以較早日的分數替代。分項 JSON 記所取群組、榜別、排名與同榜群組數。`groups_json` 每個群組另記 `qualified` 與當日分數列的 `data_quality`：只缺催化劑的 partial 群組（[hot_group_v1](hot_group.md) 事件覆蓋未核實）在族群榜上有名次，但不合格、不計分，畫面依 `data_quality` 寫「事件資料待補」而不是「當日未排名」（[UI_COPY_SPEC 每日候選](../UI_COPY_SPEC.md)）。

**總分與名單**：總分 = `Σ wᵢ·sᵢ / Σ wᵢ`，只對非 null 分項（重新正規化），`weight_coverage = Σ wᵢ（非 null）` 一併保存；technical 必須有值且 `weight_coverage ≥ 0.65`，否則排除（`insufficient_score_coverage`）；門檻只看權重合計，不另外要求 chips 有值（可行動訊號本身已要求籌碼輸入）。同一標的兩策略都入池時只留總分高者（同分取 breakout），另一筆記在分項 JSON 的 `alternatives`。排序鍵：總分 desc → technical desc → chips desc → `exchange` asc → `symbol` asc。取前 20；少於 10 檔照實際數量；零檔是合法結果，原因 `no_actionable_signals`（T 日沒有可行動訊號）或 `all_excluded`（可行動訊號全被排除）。T 日沒有任何訊號時回 `no_data`（`no_signals_for_date`）且不寫列，待 analyze 補上後再算。

**理由**：規則式理由碼（文案見 [UI_COPY_SPEC §10](../UI_COPY_SPEC.md#10-每日候選)），每檔最多 4 條：先取每個分項的第一條，依分項加權貢獻 `wᵢ·sᵢ` 由高到低，再以同順序補滿；新聞理由標 `inference=true`。

**保存與冪等**：`candidate_runs` 以（交易日、評分版本）唯一，記評估訊號數、池內數、候選數、零檔原因、排除計數、設定快照與摘要（計算當下的訊號狀態分佈、可行動訊號數、籌碼母體數、新聞覆蓋、群組榜數、耗時）；`daily_candidates` 以（交易日、標的、評分版本）唯一，記 `signal_id`、策略、總分、`weight_coverage`、排名、分項 JSON、理由 JSON、族群 JSON 與資料日期。同日同版本已有 run 時不新增、不改寫。

**時點一致性**：只保證 `daily` 當日計算的時點一致。重算舊日期時（`worker.cli candidates --date <舊日>`，或在沒有 run 的日期跑 `daily --force`），入池與評分輸入都以 T 為資料日期，但標的與群組的 active 狀態、LLM 判讀，以及 T 之後才收錄的 T 日新聞，可能用到 T 之後才有的資訊。

**API**：`GET /api/candidates?date=&limit=`（`limit` 1～20，預設 20；不帶 `date` 取最新一次 run）回傳 run 摘要、`zero_reason`／`zero_reason_text`、方法說明（權重、各分項 `inference`、null 說明）與每列的排名、標的、策略、進場區／停損／目標／RR、總分、`weight_coverage`、`partial_components`、四分項（子項值、percentile、`null_reason`／`null_explanation`）、理由、族群、資料日期與來源；該日未計算時 `status=not_computed`。`GET /api/stocks/{exchange}/{symbol}` 的 `candidate` 為該股在 cutoff 當日或之前最新一次 run 中的列，沒有則為 null。兩者的每列另有 `llm_note`（[候選 AI 進出點說明](#候選-ai-進出點說明)），既有欄位不變。

### 候選 AI 進出點說明

每檔候選附一段 LLM 推論的說明：為何入選、進場區／停損／目標的解讀、需留意的風險。說明只讀已保存的資料，不影響分數、排序、入選或任何策略判定，也不是勝率或操作建議。實作在 `backend/worker/candidate_notes.py`，提示 `backend/worker/prompts/candidate_notes_v1.md`（提示版本 `candidate_notes_v1`，`app.domain.CANDIDATE_NOTE_PROMPT_VERSION`；文字雜湊由測試釘住，改提示必須升版），模型 `sonnet`，呼叫方式同新聞 LLM（[NEWS_SPEC §5](../NEWS_SPEC.md#5-ai-摘要與推論)）。

- **輸入**（每檔；該檔輸入物件以 `sort_keys` JSON 序列化後的 SHA-256 存為 `llm_input_hash`）：`daily_candidates` 的名次、代號名稱、策略、資料日期、總分與 `weight_coverage`（0–100）、四分項分數與 null 說明、規則理由文字與 `inference`、族群（名稱、榜別、當日排名／同榜數）；訊號的進場區、停損、目標 1／2、RR、規則最早執行日；分項 JSON 記錄的關聯新聞最多 5 則（新的在前：台北日期、標題、`llm_status=done` 時的 AI 摘要與方向，否則來源摘要前 200 字）。不送行情序列或其他候選。
- **輸出**：每檔 `selection`（≤120 字）、`levels`（≤160 字）、`risks`（≤120 字），繁中；`id` 須與輸入一一對應，缺欄、多欄、空字串、超長或 id 不符時整批失敗。某檔的輸入無法組出時只有該檔記 `pending`（`input_error`），同批其他檔照送。提示要求只引用輸入中的價位、不寫買賣建議與勝率。
- **保存**：`candidate_llm_notes` 每檔候選（`daily_candidate_id`）× 提示版本一列（unique），記 `candidate_run_id`、交易日、`llm_status`（`done`／`pending`）、`llm_model`（CLI 回報的實際模型；`pending` 列為空）、`prompt_version`、`llm_input_hash`、`llm_run_at`（產生時間，UTC）、`llm_error`、三段說明與 ingestion run、raw 參照。失敗只寫狀態與原因，不改既有說明文字；已 `done` 的列不會被之後失敗的批次（含並行的另一次執行）改回 `pending`。
- **冪等**：同一候選同提示版本已 `done` 就不再送、不改寫（之後關聯新聞的判讀補齊也不重算）；`pending` 由同日的下一次執行重送（daily 只處理自己的目標日，前一日的 `pending` 要手動 `candidate-notes --date` 補）。新提示版本另寫新列，舊列保留。
- **執行**：`daily` 最後一步 `candidate_notes`（candidates 成功後），失敗不影響 daily；手動 `python -m worker.cli candidate-notes`（[現有 worker CLI](../ops/CLI.md#現有-worker-cli)）。
- **API**：`llm_note` 為 null（未嘗試）或 `{status, inference: true, selection, levels, risks, model, prompt_version, generated_at（帶 +00:00）, input_hash}`；優先取現行提示版本的 `done`，其次其他版本最新的 `done`，都沒有時為 `pending` 且三段文字為 null。文案見 [UI_COPY_SPEC §10](../UI_COPY_SPEC.md#10-每日候選)。

## candidate_score_v2

更早的評分（[#262](https://github.com/YiCheng0608/stock-lab/issues/262)），現行為 [candidate_score_v7](#candidate_score_v7)。與 [candidate_score_v1](#candidate_score_v1) 只差兩處：`name` 為 `candidate_score_v2`，新聞分項的 `llm_prompt_version` 為 `news_v2`（當時的現行新聞提示，[NEWS_SPEC §5](../NEWS_SPEC.md#5-ai-摘要與推論)）；其餘權重、子項、窗口、門檻、名單、理由、保存與 API 規則都照 v1。設定是 `domain.py` 的 `CANDIDATE_SCORE_V2`（快照與「只差兩處」由 `test_candidates.py` 釘住），當時 `CANDIDATE_SCORE` 指向它。新聞提示升版時評分也要升版：測試 `test_score_reads_the_news_prompt_version_the_news_llm_writes` 要求現行評分讀的版本等於 `worker.news_llm.PROMPT_VERSION`，否則新版提示寫的方向不會被計分。v2 現行時 `/api/candidates` 與個股 `candidate` 只讀 v2 的 run；v1 的 run 與列保留不改。現在的讀取規則見 [candidate_score_v7 的交界](#candidate_score_v7)。換版的 T 日窗口內若有只做過 `news_v1` 判讀的新聞，這些新聞記 `unscored`。

## candidate_score_v3

更早的評分（[#392](https://github.com/YiCheng0608/stock-lab/issues/392)），現行為 [candidate_score_v7](#candidate_score_v7)。與 [candidate_score_v2](#candidate_score_v2) 只差策略名稱：`name` 為 `candidate_score_v3`，候選池與技術分項（量比方向、距離公式）的 `breakout_v1`／`pullback_v1` 換成 [`breakout_v2`／`pullback_v2`](breakout_pullback.md#breakout_v2pullback_v2)；其餘照 v2。設定是 `domain.py` 的 `CANDIDATE_SCORE_V3`（快照與「只差策略名稱」由 `test_candidates.py` 釘住）；v2 的 run 與列保留不改。

## candidate_score_v4

更早的評分（[#413](https://github.com/YiCheng0608/stock-lab/issues/413)），現行為 [candidate_score_v7](#candidate_score_v7)。與 [candidate_score_v3](#candidate_score_v3) 只差兩處：`name` 為 `candidate_score_v4`，新聞分項的 `llm_prompt_version` 為 `news_v3`（[NEWS_SPEC §5](../NEWS_SPEC.md#5-ai-摘要與推論) 的現行新聞提示）；其餘權重、子項、窗口、門檻、候選池、名單、理由、保存與 API 規則都照 v3。設定是 `domain.py` 的 `CANDIDATE_SCORE_V4`（快照與「只差兩處」由 `test_candidates.py` 釘住）；v3 的 run 與列保留不改。換版的 T 日窗口內若有只做過 `news_v2` 判讀的新聞，這些新聞記 `unscored`。

## candidate_score_v5

前一版評分（[#404](https://github.com/YiCheng0608/stock-lab/issues/404)），現行為 [candidate_score_v7](#candidate_score_v7)。與 [candidate_score_v4](#candidate_score_v4) 只差策略名稱：`name` 為 `candidate_score_v5`，候選池與技術分項（量比方向、距離公式）的 `breakout_v2`／`pullback_v2` 換成 [`breakout_v3`／`pullback_v3`](breakout_pullback.md#breakout_v3pullback_v3)；其餘權重、子項、窗口、門檻、新聞提示（`news_v3`）、名單、理由、保存與 API 規則都照 v4。設定是 `domain.py` 的 `CANDIDATE_SCORE_V5`（快照與「只差策略名稱」由 `test_candidates.py` 釘住）；v4 的 run 與列保留不改。

## candidate_score_v6

前一版評分（[#490](https://github.com/YiCheng0608/stock-lab/issues/490)），現行為 [candidate_score_v7](#candidate_score_v7)。與 [candidate_score_v5](#candidate_score_v5) 只差兩處：`name` 為 `candidate_score_v6`，候選池多一道**流動性門檻**（設定 `pool.liquidity`）；策略（`breakout_v3`／`pullback_v3`）、權重、子項、窗口、新聞提示（`news_v3`）、名單、理由與保存規則都照 v5。設定是 `domain.py` 的 `CANDIDATE_SCORE_V6`（快照與「只差兩處」由 `test_candidates.py` 釘住），當時 `CANDIDATE_SCORE` 指向它；v5 的 run 與列保留不改。門檻只放在評分版本裡，訊號、條件價位、追蹤與回測都不受影響；調整門檻要升評分版，不升策略版。

**流動性門檻**（實作 `app.liquidity`，在 `worker.candidates._liquid_pool` 套用）：入池的其他條件都通過後，T 日（含）的 20 日平均成交量須 **≥ 1,000 張**（1 張 = 1,000 股，`market_bars.volume` 為股），剛好 1,000 張會進。只看張數不看成交值：高價股成交值再高，張數少一樣排除。門檻在評分之前套用，所以技術分項的同策略池 percentile 只排達門檻的訊號。

- **窗口**：從 T 往回走已驗證的 TAIEX 交易日（`app.coverage.verified_taiex_sessions`，與行動摘要的覆蓋率同一個呼叫，最多回看 120 個交易日），取 20 個計入的交易日；T 本身必須是已驗證交易日。
- **停牌日不計入**：日線標 `is_suspended` 的交易日跳過，窗口再往前多取一日。
- **無成交日算 0 張**：當天沒有日線、但有官方無成交日列（`no_trade_days`，[#454](https://github.com/YiCheng0608/stock-lab/issues/454)）時，計入並以 0 張計。有日線而 `volume = 0` 也照 0 計。
- **缺資料不當 0**：窗口內某交易日既沒有日線也沒有無成交日列，或 `volume` 不是有限的非負數，均量為 null（`missing_bars`）；上市不足 20 個計入日（`insufficient_sessions`）、T 不是已驗證交易日（`session_baseline_missing`）也一樣。均量為 null 時排除，原因 `liquidity_data_missing`，與低於門檻的 `low_volume` 分開計數。
- **計數與記錄**：`exclusions_json` 的 `low_volume`／`liquidity_data_missing` 與其他排除一樣每個訊號算一次（同一檔兩個策略都入池時算兩次）。`summary_json.liquidity` 記門檻、資料日期、檢查的標的數，以及兩種原因各自的股票清單（每檔一列：代號、均量張數或 null、狀態、缺資料的交易日、被排除的策略）。入選的列在 `components_json.liquidity` 記均量（張，小數三位、無條件捨去，所以未達門檻的值不會存成 1000.0；畫面再捨去成整數張）、門檻、狀態、窗口起訖、計入日數與跳過的停牌日、無成交日、缺資料日；它不是分項，不計分、不進理由。
- **零檔**：全部可行動訊號都被門檻排除時零檔原因是 `all_excluded`。

**API**：`/api/candidates` 與個股 `candidate` 的每列多 `liquidity`（`average_volume_lots_20d`、`minimum_lots`、`state`、`below_minimum`、`data_as_of`、窗口起訖、`unit=lots`；v5 以前的 run 為 null）。個股 API 的 `strategy_board.liquidity` 為策略總表當日的 20 日均量（當日 run 因門檻排除該股時取 run 記的值，否則以同一規則計算），`minimum_lots` 取當日 run 的設定（沒有門檻的版本為 null），`candidate_exclusion` 為 `low_volume`／`liquidity_data_missing`／null。`/api/actions` 的每列多 `liquidity`：當日 run 因門檻排除、又不在候選名單的股票為 `{average_volume_lots_20d, minimum_lots, state, below_minimum, exclusion, data_as_of, score_version, unit}`，其餘為 null。文案見 [UI_COPY_SPEC §10](../UI_COPY_SPEC.md#10-每日候選)。

**稽核**：`tools/audit` 的候選重算以 TAIEX 指數日線的日期為交易日，獨立重算 20 日均量，重建的池子先套同一門檻，入選列的 `liquidity.average_volume_lots_20d` 要與重算值相符。


## candidate_score_v7

目前的評分版本（`CANDIDATE_SCORE_VERSION`，[#580](https://github.com/YiCheng0608/stock-lab/issues/580)）。與 [candidate_score_v6](#candidate_score_v6) 只差策略名稱：`name` 為 `candidate_score_v7`，候選池與技術分項（量比方向、距離公式）的 `pullback_v3` 換成 [`pullback_v4`](breakout_pullback.md#pullback_v4)（RR 以進場區中點計算），`breakout_v3` 不變；流動性門檻、權重、子項、窗口、新聞提示（`news_v3`）、名單、理由與保存規則都照 v6。設定是 `domain.py` 的 `CANDIDATE_SCORE_V7`（快照與「只差策略名稱」由 `test_candidates.py` 釘住），`CANDIDATE_SCORE` 指向它；v6 的 run 與列保留不改。

- **入池的 RR**：入池仍要求通過 `validate_signal_levels`（RR ≥ 1.5）與 analyze 判定可行動。v4 的 RR 以進場區中點計算，不足 1.5 的回踩訊號在 analyze 就記 `invalid_levels`、不是可行動訊號，所以不入池（不算可行動訊號，只出現在 run 摘要的訊號狀態分佈 `invalid_levels`，不計入 `exclusions_json`）。今日名單的回踩型因此可能變少（使用者接受，[#1 6744852194](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6744852194)）。
- **RR 子項**：權重仍是 0（只顯示、不計分）。v4 起回踩型的 RR 會隨收盤在進場區的位置變動，不再固定約 1.6；要不要計分另議，改權重要再升版。
- **API**：`/api/candidates` 與個股 `candidate` 的 `levels` 多 `risk_reward_basis`（`entry_zone_midpoint`／`signal_close`／`entry_price`，依訊號的策略版本；畫面據此標明 RR 的計算基準，[UI_COPY_SPEC §10](../UI_COPY_SPEC.md#10-每日候選)），其餘欄位不變。

**交界**（[#407](https://github.com/YiCheng0608/stock-lab/pull/407) review M3、[#413](https://github.com/YiCheng0608/stock-lab/issues/413)、[#404](https://github.com/YiCheng0608/stock-lab/issues/404)、[#490](https://github.com/YiCheng0608/stock-lab/issues/490)、[#580](https://github.com/YiCheng0608/stock-lab/issues/580)）：過去日期的候選不重算。讀取端（`/api/candidates` 與個股 `candidate`、行動頁第 1 級、族群成員表）每個日期依版本清單 `CANDIDATE_SCORE_READ_VERSIONS`（v7、v6、v5、v4、v3、v2）取它有的第一個版本的 run（`app.candidate_runs.read_run`）：沒有 v7 run 的日期取 v6 run，依此類推。所以切換前的日期照舊顯示當時的名單，同一天只讀一版，與訊號的交界相同（[策略框架與 registry](README.md#策略框架與-registry)）。`daily` 只寫 v7，候選 AI 說明只寫 v7 run。
