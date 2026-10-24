# Canonical v1 規格

本文只保存 `breakout_v1`、`pullback_v1`、`hot_group_v1`、[`candidate_score_v1`](#candidate_score_v1)、[技術指標](#技術指標) `indicators/v1`、價位、eligibility、生命週期與回測的 canonical 基準；實作狀態與排程見 [ROADMAP](ROADMAP.md)。修改公式、時間、成本或機率語意時必須升版並保留舊 run、輸入、設定與結果。`StrategyVersion` 以（`name`、`version`、`formula_version`）識別；config 的 `formula_version` 子版本另建一列，`version` 不變，原列與指向它的訊號不改（規則見[策略版本識別](#策略版本識別)）。設定來源是 `backend/app/domain.py`；worker 保存可序列化設定、rule evidence、data cutoff 與 raw provenance。此規格用於重現和稽核，不證明策略已採用或有效。

## 共通原則

- T 是訊號收盤日；最早成交為 T+1，不用 T 收盤冒充成交。
- 價格與必要量值須為有限正數。NaN、Infinity、交易日不足、必要資料缺失、停牌或不可重建路徑一律 `data_incomplete` 或 `incomparable`，不補 0。
- v1 以日期 T 作 cutoff；T 日 13:30 的 cutoff 字串不證明法人等盤後輸入當時已可得。`trading_date`／`event_date` 是資料日期，`collected_at` 是本系統取得時間，回補日不能反推成歷史可得日。新的 PIT 版本須另存 availability、revision 與 decision time。
- failed／partial collect run 不分析或追蹤（gate 見 [OPERATIONS §3](OPERATIONS.md#3-現有-worker-cli)）。明確官方 no-data 且無列的非交易日可略過；錯日、缺報告日期或無法證實的空 payload 必須 fail closed。
- `observation` 表示該策略輸入完整、規則已判定但條件未成立；缺 entry／target／RR 是正常狀態；呈現方式見 [PRODUCT_SPEC §6](PRODUCT_SPEC.md#action-merge)。

## breakout_v1

| 條件 | 定義 |
| --- | --- |
| 突破 | `close[T] > max(high[T-20:T-1])`；前 20 個交易日不含 T。 |
| 量能 | `volume[T] / mean(volume[T-20:T-1]) >= 1.20`。 |
| 族群 | 群組等權 20 日報酬 − TAIEX 20 日報酬 `> 0`。 |
| 法人 | `sum(foreign + trust + dealer, 5d) / average_daily_volume_20d >= -0.003`；分子為 5 日淨股數，分母為含 T 的 20 日均量（股），比率無單位，語意為 5 日淨賣超達 20 日均量的 0.3%。公式識別 `institutional-flow/v2-shares-per-share-volume`。 |
| 融資 | 5 日融資餘額變動比 `<= 0.05`。 |

任何一項不足即 `data_incomplete`，不產生 actionable signal。這只判定單一策略列；同標的同 as-of 的另一條完整策略不得被連帶降級，聚合見 [PRODUCT_SPEC](PRODUCT_SPEC.md#action-merge)。

## pullback_v1

- 至少 60 根日線，`MA20 > MA60`，且 `close[T] >= MA60[T]`。
- 支撐區：`0.97 <= close[T] / MA20[T] <= 1.02`；量能：`0.60 <= volume[T] / mean(volume[T-20:T-1]) <= 1.20`。
- 族群、法人與融資確認沿用 breakout 的 20／5／20／5 日定義；任一不足即 fail closed。

## 價位、ETF 與生命週期

- 合法 entry type 只有 breakout 與 pullback；entry、invalid、targets 必須為有限正數。
- `invalid_price < entry < target_1`；第一目標 RR 必須 `>= 1.5`；存在的 `target_2 > target_1`。
- IPO 少於 20 根不觀察，20–59 根只可 observation，至少 60 根才可 actionable。
- ETF 全部收集、分類並進 ETF 分榜。broad_market、dividend、sector、thematic、commodity 可套一般策略；bond、leveraged、inverse 回傳 `etf_category_excluded_from_actionable_signals:<category>`，仍可收集與排行。

    observation -> conditional -> active -> target_1_hit -> target_2_hit -> settled
                      |              +-> invalidated / expired / incomparable -> settled
                      +-> data_incomplete / invalid_levels / expired

## hot_group_v1

基準為 TAIEX 調整收盤價；相對報酬、廣度、量能、法人、催化劑權重依序為 35%、25%、15%、15%、10%。

| 分項 | 公式 |
| --- | --- |
| 相對報酬 | 群組等權超額報酬；1／5／20 日按 20%／30%／50% 加權後取同榜 percentile。 |
| 廣度 | 成員跑贏 TAIEX 的比例；1／5／20 日採相同 20%／30%／50% 權重。 |
| 量能 | `volume_1d / prior_20d_avg` 與 `mean(volume_5d) / prior_20d_avg` 各 50%，取同榜 percentile。 |
| 法人 | 5 日三大法人淨股數／含 T 的 20 日成交量合計（股），群組取成員平均後取同榜 percentile；覆蓋規則見下。 |
| 催化劑 | MOPS／TWSE-TPEx 公告／申報事件；1／5／20 日按 50%／30%／20% 加權，3 件封頂。 |

membership 必須在 score date 有效；每個股票榜或 ETF 類別分區至少 3 檔合格成員。產業與題材各算一榜，「同榜」依群組類型劃分：官方產業（`official_industry`）、[題材表](INDUSTRY_CLASSIFICATION.md#7-題材表)題材（`theme`）、其他股票群組（目前只有新上市觀察 `daily_hot_group`）各自成榜，ETF 依類別分區；percentile 與排名只在同榜內計算，榜別寫在 `details_json.board`，未達成員門檻的群組仍是同榜 percentile 的比較對象，`theme_candidate` 不計分；[新聞題材建議](#新聞題材建議)不是群組，不進任何榜。breakout_v1／pullback_v1 的族群確認只取非題材群組，`worker.pipeline._best_group_for_signal` 會排除 `theme`；decision／行動摘要的 qualified 族群（`app.decision._qualified_groups_for_instrument`）與今日候選則含題材。`details_json.member_count` 是 score date 有效、標的 active 且類型合格（股票榜為 stock／ipo，ETF 分區為合格類別 ETF）的成員數；`eligible_members` 是其中 1／5／20 日報酬、TAIEX 基準與量能輸入皆齊全的成員數，3 檔門檻看的是 `eligible_members`。事件 missing policy：

- 官方事件完整覆蓋 1／5／20 日窗口且沒有已核實事件時，催化劑才是有效 0。
- unsupported、partial、錯日、缺日或事件—族群關聯未核實時，催化劑為 null，不能改成 0 或推測方向。
- 只有催化劑可以缺：其餘四個 component 都有值時，可用權重 0.90 達門檻，分數為 `(0.35×相對報酬 + 0.25×廣度 + 0.15×量能 + 0.15×法人流) / 0.90`，品質固定為 partial；不檢查同榜其他群組的事件狀態。其他任一 component 缺時可用權重低於 0.90，判為 `insufficient_data`，不給分（`app.domain.group_score_quality`）。
- 五個 component 全部完整才可稱「完整熱門」。四分項 observation 不得產生候選或 action，也不得虛構事件理由。

**法人覆蓋（1.1.0）**：分母是 `eligible_members`，與其他四分項相同；每個合格成員都要有 5 日法人值，法人分項才有值，群組值為成員值總和除以 `eligible_members`。單檔法人值沿用 20 根非停牌日線、成交量皆 > 0 的條件（`worker.pipeline._flow_and_volume_inputs`）。最後 5 根中的某一天，成員沒有籌碼列，或籌碼列只有融資來源時，處理方式如下：
- 同市場同日有官方法人檔證據時，該日三大法人淨額記 0。證據是至少一列來自官方法人 parser（`twse_t86`／`tpex_3insti`）的籌碼列，`raw_payload_id` 指向該端點（T86／`insti/dailyTrade`）且 raw `data_as_of` 等於該日（`worker.pipeline._official_institutional_file_evidence`）。語意與核對見 [DATA_SOURCES 法人口徑](DATA_SOURCES.md#法人口徑)。
- 沒有證據（檔案沒收到、日期不符、只有另一市場的檔）時，該成員法人值為 null。來自官方檔的籌碼列有任一欄 null 時也是 null。

`details_json.institutional_flow_coverage` 記 available、eligible、`member_count`、`complete`，以及補 0 的成員數、成員日數與日期；`member_returns[].institutional_flow_absent_from_official_file` 逐日記補 0 的日期與證據 raw id。這條規則只用於 hot_group；breakout_v1／pullback_v1 與 candidate_score_v1 的法人輸入仍把缺列視為缺資料。

**版本**：`StrategyVersion`（`hot_group_v1`、`1.1.0`、`institutional-flow/v2-shares-per-share-volume`）。`1.0.0` 要求全部成員（不是合格成員）都有法人值，也不把官方檔未列記 0；它的 `StrategyVersion` 列不改。分數列在 `details_json.hot_group_version` 記寫入版本，沒有這個欄位的列是 1.0.0 寫的。`group_daily_scores` 每個群組每日只有一列；較新版本要改寫舊版本寫的列（含 rescore 清除停用群組的名次）之前，會在同一 transaction 內把舊列原樣複製到 `group_daily_score_archive`。封存表記原列 id、寫入版本、`archive_reason`、`archived_at`，每個（群組、日期、版本）只保存一份，API 不讀封存表。

## candidate_score_v1

評分只用於排序，不代表勝率或預期報酬，不改變策略判定。設定在 `backend/app/domain.py` 的 `CANDIDATE_SCORE_V1`（快照由 `backend/tests/test_candidates.py` 釘住）；權重、子項、窗口、門檻、名單長度或理由規則任一改變都必須升版，舊版的 `candidate_runs`／`daily_candidates` 保留不改。實作在 `backend/worker/candidates.py`，由 `daily` 的 candidates 步驟或 `worker.cli candidates` 執行（[OPERATIONS §3](OPERATIONS.md#3-現有-worker-cli)）。

**候選池**：T 日 `analysis` namespace 的 `breakout_v1`／`pullback_v1` 訊號，同時符合：analyze 在 T 日判定可行動（`rule_evidence_json.actionable = true`，即當日 `conditional`；evaluate 之後把狀態推進成 `active`、`target_1_hit`、`invalidated` 等不影響入池，重算舊日期時池子相同；沒有此旗標的舊列改看狀態是否為 `conditional`、`active`、`target_1_hit`、`target_2_hit`、`invalidated`、`incomparable` 之一）、策略列為現行公式（`active`）、標的為 active 的 `stock`／`ipo`（ETF、指數一律排除）、entry type 與策略相符且通過 `validate_signal_levels`（含 RR ≥ 1.5，見[價位、ETF 與生命週期](#價位etf-與生命週期)）、T 日有非停牌日線。排除原因與計數寫入 `candidate_runs.exclusions_json`。

**分項**（0～1，1 為較佳端）：percentile 一律為同日 mid-rank `(less + (equal−1)/2)/(n−1)`，只有 1 個值時 0.5（與 `hot_group_v1` 同函式），「較低為佳」的子項先取負再算。分項是有值子項的加權平均，子項全缺才為 null；缺資料不補 0。

| 分項 | 權重 | 子項（權重） | 原值 | percentile 母體 |
| --- | --- | --- | --- | --- |
| technical | 0.35 | 量比（0.5） | `volume[T]/mean(volume[T-20:T-1])`；breakout 越高越好、pullback 越低越好（量縮回檔） | 同日同策略的候選池 |
| | | 距離（0.5） | breakout `close[T]/max(high[T-20:T-1])−1`；pullback `abs(close[T]/MA20[T]−1)`；越小越好 | 同上 |
| | | RR（0） | `(target_1−entry)/(entry−invalid)`；只顯示不計分：`_risk_levels` 以固定 1.6R 設目標，RR 只差四捨五入，沒有鑑別力 | — |
| chips | 0.30 | 法人 5 日（0.4） | 三大法人 5 日淨股數／20 日均量（與策略同公式） | 同日 active stock／ipo 全市場有值者 |
| | | 法人 20 日（0.3） | 三大法人 20 日淨股數／20 日均量；20 個有效交易日都要有籌碼列 | 同上 |
| | | 融資 5 日（0.3） | 5 日融資餘額變動比（與策略同）；越低越好 | 同上 |
| news_sentiment（推論） | 0.15 | 淨方向（1） | 見下 | 同日 active stock／ipo 全市場 |
| group | 0.20 | 榜內 percentile（1） | 所屬合格群組 `1−(rank−1)/(同榜有排名群組數−1)` 的最大值，同榜只有 1 群組時 0.5；不再做跨股 percentile | — |

- **籌碼**取 T（含）以前最後 20 根非停牌日線，最後一根必須是 T；任一籌碼欄缺、日線不足或量非正時該子項為 null。
- **新聞**：窗口為 T−2～T 三個台北日曆日；`datetime` 精度的時間以 UTC＋8 換日，`date` 精度直接用日期。只算 `status=active`、`time_consistency=verified`、`symbols_json` 規則命中（裸代號或 `交易所:代號`）的新聞；方向取設定中 `llm_prompt_version`（目前 `news_v1`）且 `llm_status=done` 的 `ai_impact_direction`：positive +1、negative −1、mixed 0，unknown 與未判讀不計分（計入 `unscored`）。原值為加總；窗口內有任一 `run_type=news` 的 success／partial 收集 run（`run_date` 為台北日期，`worker.cli news` 預設取台北今日）時，沒有關聯新聞是有效 0，否則全市場此分項為 null（`news_collection_missing`）。多數股票原值為 0，mid-rank 會落在中段；`instruments_with_news` 記有新聞的股票數。只用計算當下 DB 已有的資料，同日不重算。
- **族群**：群組須 active、T 日成員有效、榜別為產業或題材（新上市觀察與 ETF 分區不算），且 T 日分數列符合 `app.decision._qualified_groups_for_instrument` 的條件（`complete`、合格成員 ≥3、有排名、TAIEX 基準、非 ETF 榜）；不以較早日的分數替代。分項 JSON 記所取群組、榜別、排名與同榜群組數。

**總分與名單**：總分 = `Σ wᵢ·sᵢ / Σ wᵢ`，只對非 null 分項（重新正規化），`weight_coverage = Σ wᵢ（非 null）` 一併保存；technical 必須有值且 `weight_coverage ≥ 0.65`，否則排除（`insufficient_score_coverage`）；門檻只看權重合計，不另外要求 chips 有值（可行動訊號本身已要求籌碼輸入）。同一標的兩策略都入池時只留總分高者（同分取 breakout），另一筆記在分項 JSON 的 `alternatives`。排序鍵：總分 desc → technical desc → chips desc → `exchange` asc → `symbol` asc。取前 20；少於 10 檔照實際數量；零檔是合法結果，原因 `no_actionable_signals`（T 日沒有可行動訊號）或 `all_excluded`（可行動訊號全被排除）。T 日沒有任何訊號時回 `no_data`（`no_signals_for_date`）且不寫列，待 analyze 補上後再算。

**理由**：規則式理由碼（文案見 [UI_COPY_SPEC §10](UI_COPY_SPEC.md#10-每日候選)），每檔最多 4 條：先取每個分項的第一條，依分項加權貢獻 `wᵢ·sᵢ` 由高到低，再以同順序補滿；新聞理由標 `inference=true`。

**保存與冪等**：`candidate_runs` 以（交易日、評分版本）唯一，記評估訊號數、池內數、候選數、零檔原因、排除計數、設定快照與摘要（計算當下的訊號狀態分佈、可行動訊號數、籌碼母體數、新聞覆蓋、群組榜數、耗時）；`daily_candidates` 以（交易日、標的、評分版本）唯一，記 `signal_id`、策略、總分、`weight_coverage`、排名、分項 JSON、理由 JSON、族群 JSON 與資料日期。同日同版本已有 run 時不新增、不改寫。

**時點一致性**：只保證 `daily` 當日計算的時點一致。重算舊日期時（`worker.cli candidates --date <舊日>`，或在沒有 run 的日期跑 `daily --force`），入池與評分輸入都以 T 為資料日期，但標的與群組的 active 狀態、LLM 判讀，以及 T 之後才收錄的 T 日新聞，可能用到 T 之後才有的資訊。

**API**：`GET /api/candidates?date=&limit=`（`limit` 1～20，預設 20；不帶 `date` 取最新一次 run）回傳 run 摘要、`zero_reason`／`zero_reason_text`、方法說明（權重、各分項 `inference`、null 說明）與每列的排名、標的、策略、進場區／停損／目標／RR、總分、`weight_coverage`、`partial_components`、四分項（子項值、percentile、`null_reason`／`null_explanation`）、理由、族群、資料日期與來源；該日未計算時 `status=not_computed`。`GET /api/stocks/{exchange}/{symbol}` 的 `candidate` 為該股在 cutoff 當日或之前最新一次 run 中的列，沒有則為 null。兩者的每列另有 `llm_note`（[候選 AI 進出點說明](#候選-ai-進出點說明)），既有欄位不變。

### 候選 AI 進出點說明

每檔候選附一段 LLM 推論的說明：為何入選、進場區／停損／目標的解讀、需留意的風險。說明只讀已保存的資料，不影響分數、排序、入選或任何策略判定，也不是勝率或操作建議。實作在 `backend/worker/candidate_notes.py`，提示 `backend/worker/prompts/candidate_notes_v1.md`（提示版本 `candidate_notes_v1`，`app.domain.CANDIDATE_NOTE_PROMPT_VERSION`；文字雜湊由測試釘住，改提示必須升版），模型 `sonnet`，呼叫方式同新聞 LLM（[NEWS_SPEC §5](NEWS_SPEC.md#5-ai-摘要與推論)）。

- **輸入**（每檔；該檔輸入物件以 `sort_keys` JSON 序列化後的 SHA-256 存為 `llm_input_hash`）：`daily_candidates` 的名次、代號名稱、策略、資料日期、總分與 `weight_coverage`（0–100）、四分項分數與 null 說明、規則理由文字與 `inference`、族群（名稱、榜別、當日排名／同榜數）；訊號的進場區、停損、目標 1／2、RR、規則最早執行日；分項 JSON 記錄的關聯新聞最多 5 則（新的在前：台北日期、標題、`llm_status=done` 時的 AI 摘要與方向，否則來源摘要前 200 字）。不送行情序列或其他候選。
- **輸出**：每檔 `selection`（≤120 字）、`levels`（≤160 字）、`risks`（≤120 字），繁中；`id` 須與輸入一一對應，缺欄、多欄、空字串、超長或 id 不符時整批失敗。某檔的輸入無法組出時只有該檔記 `pending`（`input_error`），同批其他檔照送。提示要求只引用輸入中的價位、不寫買賣建議與勝率。
- **保存**：`candidate_llm_notes` 每檔候選（`daily_candidate_id`）× 提示版本一列（unique），記 `candidate_run_id`、交易日、`llm_status`（`done`／`pending`）、`llm_model`（CLI 回報的實際模型；`pending` 列為空）、`prompt_version`、`llm_input_hash`、`llm_run_at`（產生時間，UTC）、`llm_error`、三段說明與 ingestion run、raw 參照。失敗只寫狀態與原因，不改既有說明文字；已 `done` 的列不會被之後失敗的批次（含並行的另一次執行）改回 `pending`。
- **冪等**：同一候選同提示版本已 `done` 就不再送、不改寫（之後關聯新聞的判讀補齊也不重算）；`pending` 由同日的下一次執行重送（daily 只處理自己的目標日，前一日的 `pending` 要手動 `candidate-notes --date` 補）。新提示版本另寫新列，舊列保留。
- **執行**：`daily` 最後一步 `candidate_notes`（candidates 成功後），失敗不影響 daily；手動 `python -m worker.cli candidate-notes`（[OPERATIONS §3](OPERATIONS.md#3-現有-worker-cli)）。
- **API**：`llm_note` 為 null（未嘗試）或 `{status, inference: true, selection, levels, risks, model, prompt_version, generated_at（帶 +00:00）, input_hash}`；優先取現行提示版本的 `done`，其次其他版本最新的 `done`，都沒有時為 `pending` 且三段文字為 null。文案見 [UI_COPY_SPEC §10](UI_COPY_SPEC.md#10-每日候選)。

## 新聞題材建議

新聞 AI 判讀（[NEWS_SPEC §5](NEWS_SPEC.md#5-ai-摘要與推論)）的 `theme_candidates` 彙整成待核實的題材建議。建議是 LLM 推論：不計分、不排名、不寫 `theme_groups`／`group_memberships`／題材表，也不作為候選或行動的理由；人工核實與納入流程見[題材表](INDUSTRY_CLASSIFICATION.md#7-題材表)。實作在 `backend/worker/theme_suggestions.py`，彙整規則版本 `theme_suggestions_v1`（`app.theme_suggestions.AGGREGATION_VERSION`），規則改變要升版。

- **來源**：`news_llm_results` 中 `llm_status=done` 且 `ai_unsupported` 不為 true 的列，對應的 `news_items.status=active`；`pending`、`skipped_stale` 與資訊不足（unsupported）的判讀不取。
- **合併**：同一提示版本內，以題材名的 NFKC 正規化、去除所有空白、casefold 後的字串為鍵（`theme_key`），例如「AI 伺服器」「AI伺服器」「ＡＩ 伺服器」同一鍵；不做同義詞或模糊比對。不同提示版本各自成列，不跨版本合併。同一則新聞重複提同一鍵只算一次，保留第一個寫法與理由。
- **欄位**（`theme_suggestions`，每個提示版本 × 鍵一列）：`display_name` 取該鍵出現最多的原始寫法（同票取新聞日最早者）；`news_count` 為不重複新聞則數；`first_news_date`／`last_news_date` 為新聞台北日期（`published_at`，缺則 `collected_at`）；`llm_models_json` 為參與判讀的模型去重清單；`prompt_version`、`aggregation_version`；`matched_group_id`：鍵與 active 的題材表題材或官方產業的 `display_name_zh`／`name` 鍵完全相同時記該群組（題材優先），代表不是新題材；`status` 固定 `pending_verification`；`computed_at` 為內容最後變動時間（UTC）。`theme_suggestion_news` 每個建議 × 新聞一列，記 `news_llm_result_id`、模型的題材寫法 `theme_text`、理由 `reason` 與新聞日期。
- **模型把握**：`news_v1` 的題材候選沒有把握欄位，建議不帶把握值，API 回 `confidence=not_provided`；不挪用個股候選的把握。
- **冪等**：每次由全部來源列重算，只寫有差異的列；內容不變不改 `computed_at`。來源不再出現的鍵與連結刪除（例如判讀改為 unsupported 或新聞失效）。
- **執行**：`daily` 最後一步 `theme_suggestions`（collect 成功即跑，不依賴 analyze），或 `python -m worker.cli theme-suggestions`（[OPERATIONS §3](OPERATIONS.md#3-現有-worker-cli)）。
- **API**：`GET /api/theme-suggestions?limit=&include_matched=`（`limit` 1～50，預設 20）依 `news_count` 由多到少、`last_news_date` 由新到舊排序；預設只列 `matched_group_id` 為空者，`include_matched=true` 才含與既有族群同名者（附 `matched_group`）。每項有 `status`、`inference=true`、則數、首末日期、`confidence`、版本欄位與最近 5 則關聯新聞（標題、來源、日期、題材寫法、理由）；`meta` 有 `total`、`matched_total` 與 `updated_at`。`GET /api/theme-suggestions/{id}` 回傳單一建議與全部關聯新聞。文案見 [UI_COPY_SPEC §8.6](UI_COPY_SPEC.md#86-新聞題材建議)。

## 技術指標

版本 `indicators/v1`；公式與參數集中在 `backend/app/indicators.py`（`INDICATOR_VERSION`、`PARAMETERS`、`REQUIRED_BARS`），批次在 `backend/worker/indicator_batch.py`。改公式、參數或不足規則必須升版；`technical_indicators` 以（標的、日期、`formula_version`）為唯一鍵，新版本另寫列，不覆寫既有版本結果。

**輸入與價格基準**：輸入是 DB 保存的日線 `market_bars`。停牌列（`is_suspended`）與無效列（OHLC 非有限正數、`low` 高於開收或 `high` 低於開收、成交量缺漏或為負）不進任何窗口、不補值；該日每欄為 null，原因 `suspended`／`invalid_bar`。窗口以該股「可用日線根數」計，不比對交易所日曆；缺日不補，前後兩根直接相鄰。價格基準 `as_of_date_raw_basis`：T 日的值以 T 日原始價為基準，T 以前的價格依 DB 已收錄的除權息、分割事件（`worker.pipeline._action_factor_by_bar`）換算到 T 日基準，所以 T 日的均線與 T 日原始 K 線同一尺度；之後才發生的事件不影響 T。未收錄的事件等同不還原。成交量不還原。

**公式**（`C`、`H`、`L`、`V` 為上述基準的收、高、低與量）

| 欄位 | 定義 | 需要根數 |
| --- | --- | --- |
| `ma5`／`ma10`／`ma20`／`ma60`／`ma120` | 近 n 根 `C` 的簡單平均 | n |
| `macd_dif` | `EMA12(C) − EMA26(C)`；EMA 的 α = 2/(n+1)，以前 n 根簡單平均起算 | 26 |
| `macd_signal` | `EMA9(DIF)`，以前 9 個 DIF 的簡單平均起算 | 34 |
| `macd_hist` | `DIF − signal`（不乘 2） | 34 |
| `rsi6`／`rsi12` | Wilder：首個平均漲跌為前 n 個變動的簡單平均，之後 `(前值 × (n−1) + 本期) / n`；`RSI = 100 × 平均漲 / (平均漲 + 平均跌)` | n+1 |
| `kd_k`／`kd_d` | `RSV = 100 × (C − L9) / (H9 − L9)`（L9、H9 為近 9 根最低低、最高高）；`K = K' + (RSV − K')/3`、`D = D' + (K − D')/3`，首根前 `K' = D' = 50`；`H9 = L9` 時 RSV 取 50 | 9 |
| `boll_mid`／`boll_upper`／`boll_lower` | 中軌 = MA20；上下軌 = 中軌 ± 2 × 近 20 根 `C` 的母體標準差 | 20 |
| `vol_ma5`／`vol_ma20` | 近 n 根 `V` 的簡單平均 | n |

EMA 與 Wilder 平滑依賴全部可用歷史，起算點是該股在 DB 的第一根可用日線；DB 往前回補後要重算（見 [OPERATIONS §3](OPERATIONS.md#3-現有-worker-cli)）。

`technical_features` 不保存前 20 根陣列；`breakout_v1`／`pullback_v1` 與 `hot_group_v1` 需要的前 20 根高點與量由 `market_bars` 即時切取（`worker.pipeline._prior_20_window`）。

**資料不足**：可用根數少於上表時該欄為 null，原因 `insufficient_bars`，並保存 `bar_count`（含 T 的可用根數），API 另附 `required_bars` 讓畫面說明「需 N 根、現有 M 根」。RSI 在該股自第一根可用日線起完全沒有漲跌時為 null，原因 `no_price_change`（Wilder 平滑下只要曾有漲跌，平均值就不會回到 0）。批次尚未寫入的日期，API 回 `not_computed`。

**週線**：由日線聚合，依 ISO 週（週一起算；補班交易日併入當週）分組，只用可用日線：開＝首日開、高＝最高高、低＝最低低、收＝末日收、量＝加總，`date` 為該週最後一個交易日並附 `week_start`、`trading_days`。週指標以週線序列套用同一公式與參數重算（MA5 即 5 週），價格基準為該週最後一日；整週停牌則無該週。週線指標於 API 請求時計算，不入庫。

**API**：`GET /api/stocks/{exchange}/{symbol}/bars?interval=day|week&limit=N`（`limit` 1～1500，預設 250，取最近 N 根）。每根回 OHLCV、來源、`bar_count`、上表各欄與 `reasons`（只列 null 欄位的原因）；頂層附 `data_as_of`、行情 `sources` 與 `indicators`（版本、價格基準、參數、`required_bars`、欄位清單、指標來源與日線批次計算時間）。日線指標讀 `technical_indicators`，週線即時計算。

## Tracking 與 technical backtest 口徑

1. T+1 起依觸發條件成交；買賣各採不利 5 bps 滑價，淨報酬扣預設 30 bps round-trip 成本，並寫入 evidence。成本與滑價是固定假設，不區分商品與情境，不是真實通用費率。
2. 每筆訊號最多追蹤 20 個交易日；T+5、T+20 各寫一筆 settlement。公司行動需可追溯調整因子；停牌、缺可判定價格或同日 stop／target 皆觸及且順序未知時標 incomparable。
3. replay 固定 canonical version，保存日期範圍、cutoff、設定快照與執行數；相同成功 request key 可重用既有 run。
4. audit 保存 observation、data_incomplete 等所有規則列；technical summary 只納入 actionable evidence，按策略／標的類型／T+5、T+20 分組。
5. 三個月或更短一律標 `insufficient_sample`；更長也不等於參數最佳化、walk-forward、獨立 OOS 或策略有效。勝率不能單獨決定採用。
6. 逐日成交與出場規則只寫在 `app.tracking.track_path`（T+N 結果為 `settle`），系統訊號追蹤（`worker.pipeline._evaluate_signal_tracking`）與[使用者追蹤計畫](#使用者追蹤計畫)共用。

## 使用者追蹤計畫

`plan_tracking_v1`：使用者把一筆成立的研究條件存成計畫，系統每日以日線規則模擬成交與出場。計畫不是實際成交，也不寫入或讀取持倉（`portfolio_positions`）；不統計勝率或達標率。

**建立**（`app.tracking_plans.create_plan`）：來源是今日候選（`source_kind=candidate`，另記 `daily_candidate_id` 與 `score_version`）或個股頁研究條件（`stock`）的訊號，須同時符合：

1. 訊號 `status=conditional`，且價位通過 `validate_signal_levels`（pullback 另須有回踩區上下緣），否則 `signal_not_conditional`／`invalid_levels`。
2. 訊號日等於該股 `market_bars` 的最新日，否則 `stale_signal`：追蹤從訊號日的下一個交易日起算，用較早的訊號建計畫等於回看已知的走勢。某日 collect 已寫入日線、analyze 還沒寫入該日訊號時（同一次 daily 的兩步之間，或 analyze 失敗待重跑；例如 18:30 collect 成功、21:30 重跑 analyze 之前），該股只有前一日的訊號，一律 `stale_signal`；analyze 成功後才能以新一日的訊號建立。休市日最新日線與最新訊號同一天，可以建立。
3. 指定候選時，候選列的 `signal_id` 必須是這筆訊號（`candidate_signal_mismatch`）。

同一訊號同時最多一個未取消的計畫（部分唯一索引 `uq_tracking_plan_open_signal`），重複加入回傳原計畫；取消後可再建一個新計畫。建立時快照策略名稱、`strategy_version_id`、`formula_version`、`score_version`、`tracking_version`、計畫資料日（`plan_date`＝訊號日）、最早執行日與全部價位，之後訊號被 analyze 改寫也不影響計畫。

**每日更新**（daily 的 `plan_tracking` 步驟，`worker.plan_tracking`）：每個未結束的計畫從 `plan_date` 起以[Tracking 口徑](#tracking-與-technical-backtest-口徑)重算，最多 20 個交易日（`window_sessions`），不讀目標日之後的日線；每個交易日寫一列 `tracking_plan_sessions`（狀態、觸發、原始與還原 OHLC、是否停牌、模擬成交價、來源）。

| 狀態 | 進入條件 | 模擬結果 |
| --- | --- | --- |
| `pending` 待觸發 | 建立時；還沒成交且視窗未滿 | 無 |
| `triggered` 已觸發 | 突破價或回踩區首次觸及，模擬成交 | 無（未出場） |
| `target_hit` 達標 | 成交後首次觸及目標一 | 以目標一扣賣出滑價出場 |
| `invalidated` 失效 | 成交後首次觸及失效價（策略失效價，不是使用者停損） | 以失效價扣賣出滑價出場 |
| `expired` 到期 | 20 個交易日內沒有成交 | 無 |
| `closed` 期滿結算 | 已成交，20 個交易日內未達標也未失效 | 以第 20 個交易日收盤結算 |
| `incomparable` 無法比較 | 同一交易日失效價與目標一都觸及（順序不明）；或市場已過 20 個交易日但該股不足 20 根日線（長期停牌、下市） | 無 |
| `cancelled` 已取消 | 使用者取消未結束的計畫 | 保留取消前的成交與明細 |

允許的轉換只有 `pending` → `triggered`／`target_hit`／`invalidated`／`incomparable`／`expired`／`closed`／`cancelled`，與 `triggered` → `target_hit`／`invalidated`／`incomparable`／`closed`／`cancelled`（`app.domain.PLAN_STATUS_TRANSITIONS`）；同一交易日成交又出場、或漏跑幾天後一次看到成交與期滿時直接跳到結果。其餘狀態都是終態，之後不再重算。

- **模擬報酬**（`result_return`）：達標、失效、期滿結算才有，＝出場價÷成交價（兩者都換回計畫資料日的價格基準）− 1 − 30 bps；成交到出場之間有停牌或其他不可比較的交易日時 `result_comparable=false`、報酬為 null 並寫原因，狀態不變。
- **停牌**：停牌日（`is_suspended`、零量一字線、或官方停牌區間內缺日線）記一列 `suspended`，不推論觸發，狀態不變。
- **冪等**：同一目標日重跑寫出相同的列，值沒變就不改寫、`updated_at` 不動。重算出不允許的轉換（例如行情更正後原本的成交不成立）時保留原狀態與明細，`data_quality` 記 `transition_conflict`、`status_reason` 記 `transition_conflict:<原>-><新>`，不倒退。
- **取消**（`app.tracking_plans.cancel_plan`）：只能取消 `pending`／`triggered` 的計畫，記 `cancelled_at` 與 `status_reason=cancelled_while_<原狀態>`；已結束的計畫回 `plan_already_closed`。計畫與明細都不刪。

## 策略版本識別

- 唯一鍵為（`name`、`version`、`formula_version`）。`init-db` 依快照把既存列標為已知公式（與固定 SHA-256 清單內 canonical 快照相同者為 `institutional-flow/v1-shares-per-twd-turnover`），其餘標 `unclassified/<reason>`；非現行公式的列設 `active=false`，id、`version`、`config_json`、快照與指向它的訊號不改。
- `_ensure_strategies` 只取（名稱、版本、目前公式）的列或新建，取到的列與 canonical 不符時以 `strategy_snapshot_mismatch` 拒用；`signal_key` 不含公式，同鍵訊號屬於其他公式時以 `signal_formula_conflict` 拒絕覆寫，`analyze` 不提交該次結果，`daily` 不進入 evaluate。
- `GET /api/strategies` 每列含 `id`（整數主鍵）與庫內原值 `formula_version`（含 `unclassified/<reason>`）。

## 現行限制

1. worker 的 `atr14` 是最多 14 根 high-low 的平均，不含前收盤的 True Range，不是 Wilder ATR。
2. conditional 訊號的 `confidence=0.75` 是沒有校準證據的固定值，不得稱 75% 勝率；rule-only 的數值為 null。
3. `_risk_levels` 以固定風險倍數產生 1.6R／3R，合法 RR 只證明算術關係，不代表可成交、壓力位或預測。
4. 法人比率（`worker.pipeline._validated_flow_and_volume_inputs`）以 T（含）以前最後 20 根非停牌 bar 計算、最後 5 根須有籌碼列，不核對交易所日曆，也不要求最後一根就是 T。
