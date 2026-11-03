<!-- owns: candidate_score_v1、candidate_score_v2、candidate_score_v3、candidate_score_v4、candidate_score_v5、候選 AI 進出點說明 -->
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
- **族群**：群組須 active、T 日成員有效、榜別為產業或題材（新上市觀察與 ETF 分區不算），且 T 日分數列符合 `app.decision._qualified_groups_for_instrument` 的條件（`complete`、合格成員 ≥3、有排名、TAIEX 基準、非 ETF 榜）；不以較早日的分數替代。分項 JSON 記所取群組、榜別、排名與同榜群組數。

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

更早的評分（[#262](https://github.com/YiCheng0608/stock-lab/issues/262)），現行為 [candidate_score_v5](#candidate_score_v5)。與 [candidate_score_v1](#candidate_score_v1) 只差兩處：`name` 為 `candidate_score_v2`，新聞分項的 `llm_prompt_version` 為 `news_v2`（當時的現行新聞提示，[NEWS_SPEC §5](../NEWS_SPEC.md#5-ai-摘要與推論)）；其餘權重、子項、窗口、門檻、名單、理由、保存與 API 規則都照 v1。設定是 `domain.py` 的 `CANDIDATE_SCORE_V2`（快照與「只差兩處」由 `test_candidates.py` 釘住），當時 `CANDIDATE_SCORE` 指向它。新聞提示升版時評分也要升版：測試 `test_score_reads_the_news_prompt_version_the_news_llm_writes` 要求現行評分讀的版本等於 `worker.news_llm.PROMPT_VERSION`，否則新版提示寫的方向不會被計分。v2 現行時 `/api/candidates` 與個股 `candidate` 只讀 v2 的 run；v1 的 run 與列保留不改。現在的讀取規則見 [candidate_score_v5 的交界](#candidate_score_v5)。換版的 T 日窗口內若有只做過 `news_v1` 判讀的新聞，這些新聞記 `unscored`。

## candidate_score_v3

更早的評分（[#392](https://github.com/YiCheng0608/stock-lab/issues/392)），現行為 [candidate_score_v5](#candidate_score_v5)。與 [candidate_score_v2](#candidate_score_v2) 只差策略名稱：`name` 為 `candidate_score_v3`，候選池與技術分項（量比方向、距離公式）的 `breakout_v1`／`pullback_v1` 換成 [`breakout_v2`／`pullback_v2`](breakout_pullback.md#breakout_v2pullback_v2)；其餘照 v2。設定是 `domain.py` 的 `CANDIDATE_SCORE_V3`（快照與「只差策略名稱」由 `test_candidates.py` 釘住）；v2 的 run 與列保留不改。

## candidate_score_v4

前一版評分（[#413](https://github.com/YiCheng0608/stock-lab/issues/413)），現行為 [candidate_score_v5](#candidate_score_v5)。與 [candidate_score_v3](#candidate_score_v3) 只差兩處：`name` 為 `candidate_score_v4`，新聞分項的 `llm_prompt_version` 為 `news_v3`（[NEWS_SPEC §5](../NEWS_SPEC.md#5-ai-摘要與推論) 的現行新聞提示）；其餘權重、子項、窗口、門檻、候選池、名單、理由、保存與 API 規則都照 v3。設定是 `domain.py` 的 `CANDIDATE_SCORE_V4`（快照與「只差兩處」由 `test_candidates.py` 釘住）；v3 的 run 與列保留不改。換版的 T 日窗口內若有只做過 `news_v2` 判讀的新聞，這些新聞記 `unscored`。

## candidate_score_v5

目前的評分版本（`CANDIDATE_SCORE_VERSION`，[#404](https://github.com/YiCheng0608/stock-lab/issues/404)）。與 [candidate_score_v4](#candidate_score_v4) 只差策略名稱：`name` 為 `candidate_score_v5`，候選池與技術分項（量比方向、距離公式）的 `breakout_v2`／`pullback_v2` 換成 [`breakout_v3`／`pullback_v3`](breakout_pullback.md#breakout_v3pullback_v3)；其餘權重、子項、窗口、門檻、新聞提示（`news_v3`）、名單、理由、保存與 API 規則都照 v4。設定是 `domain.py` 的 `CANDIDATE_SCORE_V5`（快照與「只差策略名稱」由 `test_candidates.py` 釘住），`CANDIDATE_SCORE` 指向它；v4 的 run 與列保留不改。

**交界**（[#407](https://github.com/YiCheng0608/stock-lab/pull/407) review M3、[#413](https://github.com/YiCheng0608/stock-lab/issues/413)、[#404](https://github.com/YiCheng0608/stock-lab/issues/404)）：過去日期的候選不重算。讀取端（`/api/candidates` 與個股 `candidate`、行動頁第 1 級、族群成員表）每個日期依版本清單 `CANDIDATE_SCORE_READ_VERSIONS`（v5、v4、v3、v2）取它有的第一個版本的 run（`app.candidate_runs.read_run`）：沒有 v5 run 的日期取 v4 run，依此類推。所以切換前的日期照舊顯示當時的名單，同一天只讀一版，與訊號的交界相同（[策略框架與 registry](README.md#策略框架與-registry)）。`daily` 只寫 v5，候選 AI 說明只寫 v5 run。
