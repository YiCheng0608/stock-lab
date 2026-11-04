<!-- owns: hot_group_v1 -->
# hot_group_v1

基準為 TAIEX 調整收盤價；相對報酬、廣度、量能、法人、催化劑權重依序為 35%、25%、15%、15%、10%。

| 分項 | 公式 |
| --- | --- |
| 相對報酬 | 群組等權超額報酬；1／5／20 日按 20%／30%／50% 加權後取同榜 percentile。 |
| 廣度 | 成員跑贏 TAIEX 的比例；1／5／20 日採相同 20%／30%／50% 權重。 |
| 量能 | `volume_1d / prior_20d_avg` 與 `mean(volume_5d) / prior_20d_avg` 各 50%，取同榜 percentile。 |
| 法人 | 5 日三大法人淨股數／含 T 的 20 日成交量合計（股），群組取成員平均後取同榜 percentile；覆蓋規則見下。 |
| 催化劑 | MOPS／TWSE-TPEx 公告／申報事件；1／5／20 日按 50%／30%／20% 加權，3 件封頂。 |

membership 必須在 score date 有效；每個股票榜或 ETF 類別分區至少 3 檔合格成員。產業與題材各算一榜，「同榜」依群組類型劃分：官方產業（`official_industry`）、[題材表](../INDUSTRY_CLASSIFICATION.md#7-題材表)題材（`theme`）、其他股票群組（目前只有新上市觀察 `daily_hot_group`）各自成榜，ETF 依類別分區；percentile 與排名只在同榜內計算，榜別寫在 `details_json.board`，未達成員門檻的群組仍是同榜 percentile 的比較對象，`theme_candidate` 不計分；[新聞題材建議](theme_suggestions.md)不是群組，不進任何榜。breakout_v1／pullback_v1 的族群確認只取非題材群組，`worker.pipeline._best_group_for_signal` 會排除 `theme`；decision／行動摘要的 qualified 族群（`app.decision._qualified_groups_for_instrument`）與今日候選則含題材。`details_json.member_count` 是 score date 有效、標的 active 且類型合格（股票榜為 stock／ipo，ETF 分區為合格類別 ETF）的成員數；`eligible_members` 是其中 1／5／20 日報酬、TAIEX 基準與量能輸入皆齊全的成員數，3 檔門檻看的是 `eligible_members`。事件 missing policy：

- 事件覆蓋以 MOPS `t05st02` 的日期查詢為準（[規則](../DATA_SOURCES.md#重大訊息日期查詢)）：一個交易日的狀態是 verified（有事件）、empty（已核實空日）、partial（查詢失敗）或 unqueried（沒有日期查詢，含只有快照的日子），由 `worker.mops_events.event_coverage_states` 依日期回傳。當日的查詢以查詢時間為截止，查詢之後的公告由下一個日曆日的清單補進事件，不改變該日的覆蓋狀態；週五與連假前一天的晚間公告在週六或假日的清單裡，由下一次 collect 補查（[補查週末與連假](../DATA_SOURCES.md#重大訊息日期查詢)）。一個窗口的日期要一次傳給 `event_coverage_states`，不要逐日呼叫（每次呼叫都讀全部 run 的 metadata）。
- 官方事件完整覆蓋 1／5／20 日窗口且沒有已核實事件時，催化劑才是有效 0。
- unsupported、partial、錯日、缺日或事件—族群關聯未核實時，催化劑為 null，不能改成 0 或推測方向。
- 只有催化劑可以缺：其餘四個 component 都有值時，可用權重 0.90 達門檻，分數為 `(0.35×相對報酬 + 0.25×廣度 + 0.15×量能 + 0.15×法人流) / 0.90`，品質固定為 partial；不檢查同榜其他群組的事件狀態。其他任一 component 缺時可用權重低於 0.90，判為 `insufficient_data`，不給分（`app.domain.group_score_quality`）。
- 五個 component 全部完整才可稱「完整熱門」。四分項 observation 不得產生候選或 action，也不得虛構事件理由。

**法人覆蓋（1.1.0）**：分母是 `eligible_members`，與其他四分項相同；每個合格成員都要有 5 日法人值，法人分項才有值，群組值為成員值總和除以 `eligible_members`。單檔法人值沿用 20 根非停牌日線、成交量皆 > 0 的條件（`worker.pipeline._flow_and_volume_inputs`）。最後 5 根中的某一天，成員沒有籌碼列，或籌碼列只有融資來源時，處理方式如下：
- 同市場同日有官方法人檔證據時，該日三大法人淨額記 0。證據是至少一列來自官方法人 parser（`twse_t86`／`tpex_3insti`）的籌碼列，`raw_payload_id` 指向該端點（T86／`insti/dailyTrade`）且 raw `data_as_of` 等於該日（`worker.pipeline._official_institutional_file_evidence`）。語意與核對見 [DATA_SOURCES 法人口徑](../DATA_SOURCES.md#法人口徑)。
- 沒有證據（檔案沒收到、日期不符、只有另一市場的檔）時，該成員法人值為 null。來自官方檔的籌碼列有任一欄 null 時也是 null。

`details_json.institutional_flow_coverage` 記 available、eligible、`member_count`、`complete`，以及補 0 的成員數、成員日數與日期；`member_returns[].institutional_flow_absent_from_official_file` 逐日記補 0 的日期與證據 raw id。這條規則只用於 hot_group；breakout_v1／pullback_v1 與 candidate_score_v1 的法人輸入仍把缺列視為缺資料。

**版本**：`StrategyVersion`（`hot_group_v1`、`1.1.0`、`institutional-flow/v2-shares-per-share-volume`）。`1.0.0` 要求全部成員（不是合格成員）都有法人值，也不把官方檔未列記 0；它的 `StrategyVersion` 列不改。分數列在 `details_json.hot_group_version` 記寫入版本，沒有這個欄位的列是 1.0.0 寫的。`group_daily_scores` 每個群組每日只有一列；較新版本要改寫舊版本寫的列（含 `--rescore-days` 重算清除停用群組的名次）之前，會在同一 transaction 內把舊列原樣複製到 `group_daily_score_archive`。封存表記原列 id、寫入版本、`archive_reason`、`archived_at`，每個（群組、日期、版本）只保存一份，API 不讀封存表。

**重算舊分數日**：daily 替當天全部 active 群組打分數。`corporate-actions rebuild`（[現有 worker CLI](../ops/CLI.md#現有-worker-cli)）以更正後的價格與因子重算舊分數日時，群組固定為那天原本就有分數列的群組，percentile 與排名只在這些群組的同榜之間計算，不新增（日期、群組）列；那天之後才有分數的群組不補到那天（#409）。這個集合就是那天的排名母體，不看現在的 `active`：現在已停用的群組也在其中，照樣重算並保留 rank（#412）。頁面與 API 只顯示現在 active 的群組，所以舊日榜單上 active 群組的 rank 可能不從 1 起算、中間跳號（停用群組占了名次但不顯示），這是預期結果，不是排名錯誤。`industry repair`／`instruments repair` 的 `--rescore-days` 重算最近幾個交易日的全部 active 群組，停用群組不重算、清掉那天的 rank（原列先封存）。
