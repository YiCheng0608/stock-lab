<!-- owns: theme_heat_v1 -->
# theme_heat_v1

題材熱度：每個交易日 T，把[題材表](../INDUSTRY_CLASSIFICATION.md#7-題材表)的題材（`group_type="theme"`）依六個分項排名，讓系統認得出正在變熱的題材。熱度只用來決定 AI 先看哪些題材與股票，**不是買賣訊號**（[NEWS_SPEC](../NEWS_SPEC.md#1-目標與來源政策)「新聞篇數或情緒不能直接作買賣訊號」）：今日名單、`candidate_score`、`hot_group_v1` 與主流族群都不讀它。公式依據是 [#1003 AC-2 第 3 節](https://github.com/YiCheng0608/stock-lab/issues/1003#issuecomment-7107953147)的草案；程式在 `backend/app/theme_heat.py`，權重、窗口與設定快照由 `backend/tests/test_theme_heat.py` 對本文釘住，改任何一項要升版另寫新列。

## 分項

| 分項 | 鍵 | 原值 | 權重 |
| --- | --- | --- | --- |
| 5 日超額 | `excess_5d` | 成員 5 日報酬的等權平均 − 加權指數 5 日報酬 | 0.20 |
| 20 日超額 | `excess_20d` | 同上，20 日 | 0.20 |
| 成交金額放大 | `turnover_ratio` | 成員近 5 日平均成交金額的合計 ÷ 再往前 20 日平均成交金額的合計 | 0.20 |
| 法人 | `institutional_ratio` | 成員三大法人近 5 日淨買超金額的合計 ÷ 成員近 5 日成交金額的合計 | 0.12 |
| 廣度 | `breadth` | 20 日報酬跑贏加權指數 20 日報酬的成員比例 | 0.08 |
| 新聞 | `news` | 近 3 個交易日的題材新聞則數日均 ÷ 前 20 個交易日的日均（平滑後） | 0.20 |

- **熱度**＝有值分項的同榜百分位依權重加權平均：Σ（權重 × 百分位）÷ Σ（有值分項的權重），0～1，API 與頁面乘 100。缺的分項不補 0，其餘權重重新正規化；沒有新聞分項時五個量價分項的權重就是 0.25、0.25、0.25、0.15、0.10（草案「沒有新聞時」那一欄）。
- **百分位**：每個分項在當天同一榜內取百分位，用 `hot_group_v1` 同一個函式（`worker.pipeline._percentile`：同值取中間名次，榜上只有一個值時 0.5）。新聞原值為 0（則數未達門檻）時百分位固定為 0，不取同值的中間名次（同 hot_group 的催化劑）。
- **排名**：熱度大者先，同分依題材 id；沒有熱度的題材不排名。`quality` 是 `complete`（六分項都有值）、`partial`（至少一個缺）或 `insufficient_data`（不在榜上）。

## 榜與成員

- **榜**：T 當天的 active 題材，成員是 `role="member"`、T 落在 `valid_from`～`valid_to` 內、`instrument_type` 為 `stock`／`ipo` 的標的。題材與成員都不回溯：2026-11-24 才加入的題材在那天之前沒有成員、不在榜上；回算舊日期時每一天都用那天有效的成員。官方產業不在這一榜。
- **上榜門檻**：至少 3 個成員有 20 日報酬（`eligible_members`），不到 3 個的題材那天沒有熱度（各分項的百分位只在上榜的題材之間計算）。
- **交易日**：加權指數（`TAIEX`）有日線的日子；窗口一律數這些交易日。T 不是交易日時不計算。

## 計算細節

- **報酬**：成員在 T 與 T 往前 n 個交易日的收盤，都換到公司行動調整後的同一基準（`worker.pipeline._action_factor_by_bar`，族群分數與主流族群用的同一個因子；DB 的 `adj_close` 是原始收盤，不能直接用）。任一天沒有日線或收盤不是正數時，這個成員這個窗口沒有報酬。加權指數用原始收盤。
- **成交金額**：日線的 `turnover`；`turnover` 為 0 或空時用收盤 × 成交量。近 5 日是 T 往前 5 個交易日（含 T），前 20 日是再往前的 20 個交易日；每個成員把窗口內有值的日子加總後除以窗口天數（停牌、沒有日線的日子沒有成交，算 0），再加總成員。前 20 日合計為 0、或 T 之前不到 24 個交易日時沒有值。
- **法人**：成員每天的淨買超金額＝（外資＋投信＋自營商的淨買超股數）× 當天收盤；外資欄是空的那天沒有值，投信、自營商的空欄算 0。近 5 個交易日每天都有值的成員才計入分子；這種成員不到成員數的一半（向下取整）時沒有值。分母是全部成員近 5 日成交金額的合計。
- **新聞**：
  - 讀 `news_items` 中 `status="active"`、`source_kind="media"` 的新聞（不含 MOPS 等官方事件投影）。新聞日期是 `published_at`（沒有時用 `collected_at`）換成台北時間的日期，算進當天或之後的第一個交易日；所以近 3 個交易日的窗口是（S[T−3]，S[T]］的日曆日，前 20 個交易日是（S[T−23]，S[T−3]］。
  - 一則新聞算進一個題材的條件（每則每個題材只算一次）：標題加摘要含題材表該題材的任一個 `keywords`（NFKC、不分大小寫；`keywords` 只存在題材表檔案），**或** 這則新聞已完成的 AI 判讀（`news_llm_results`，現行提示版本與其等價版本）列出的標的是該題材在 T 有效的成員。
  - 原值＝（近 3 日則數 ÷ 3）÷（（前 20 日則數 ＋ 1）÷ 20）；近 3 日不到 3 則時原值為 0。
  - **缺資料**：T 當天沒有新聞收集 run（`ingestion_runs.run_type="news"`、`status` 為 `success` 或 `partial`、`run_date` 是 T）時，那天所有題材的新聞分項都是 null（`news_status="no_news_run"`），其餘權重重新正規化，不當成 0 則。最早一次新聞收集 run 晚於前 20 日窗口的第一個日曆日時也是 null（`history_short`），因為窗口裡還沒開始收新聞的日子不是 0 則。新聞只從 2026-10-16 起收，所以在那之前的日子都沒有新聞分項。
  - AI 判讀的正負方向只顯示在新聞頁，不計分。重算時讀當下已收的新聞與判讀，可能比當天 daily 算的多；`theme_heat_runs.news_through_id` 記算的時候讀到的最大新聞 id。
- **其他缺值**：同一原則。成交金額放大、法人沒有值時是 null，該題材其餘分項的權重重新正規化；5 日超額沒有成員有 5 日報酬時是 null。

## 存放與讀取

- `theme_heat_runs`：每個交易日、每個版本一列：`status`（`computed`，或沒有任何題材上榜的 `zero`）、`theme_count`、`ranked_count`、`news_status`（`available`／`no_news_run`／`history_short`）、`news_through_id`、`config_json`（權重與窗口的快照）、`computed_at`。
- `theme_heat_scores`：每個題材一列：`rank`、`heat`、`quality`、`member_count`、`eligible_members`、`available_weight`（有值分項的權重合計）、`components_json`（六分項各自的 `raw` 與 `percentile`，缺的是 null）、`details_json`（近 5 日都有法人值的成員數 `flow_members`、新聞兩個窗口的則數 `news_recent`／`news_prior`）。
- 同一天重算時整份換掉。daily 的 `theme_heat` 步驟與回算入口見[排程](../ops/SCHEDULING.md#題材熱度)與 [CLI](../ops/CLI.md#現有-worker-cli)。
- `GET /api/theme-heat?date=`：`date` 當天或之前最新的一份（不給時是最新一份）。`meta` 有 `trading_date`、`computed_at`、`news_status`、`weights`、`not_a_signal`，`items` 依名次排（沒有熱度的在後），每個題材有 `heat`、`rank`、`quality`、成員數、`components`（六分項的同榜百分位）、`raw` 與 `news_items`（兩個窗口的則數）。只列現在 active 的題材。

## 限制

- 成員名單本身有後見之明（[題材表](../INDUSTRY_CLASSIFICATION.md#7-題材表)「初版與回溯限制」）；初版 12 個題材的成員從 2026-01-01 起有效，所以 2026-01-01 前的回算沒有任何題材上榜。
- 題材表的 `keywords` 是為證據核對定的，有些詞很寬（「測試」「晶圓」「藥」），新聞則數會含不相關的新聞；新聞分項看的是近 3 日相對前 20 日的變化，比例會抵掉一部分。
- 熱度是相對排名：跌勢裡會選到防禦型題材（#1003 試算 2026-11-20 第 1 名是金控），這是預期中的結果。
- 和 #1003 試算的差別只有價格基準：試算用 `adj_close`（原始收盤），除權息、減資前後的報酬沒有調整；本版用調整後的基準，和 `hot_group_v1`、`mainstream_v1` 同一個因子（[#1017 決定](https://github.com/YiCheng0608/stock-lab/issues/1017#issuecomment-7118215004)）。在正式 DB 副本（2026-11-24 取得）上以試算的 21 個題材對照 2024-11-01～2026-11-23 共 107 週：改用原始收盤時同分並列後 107 週名次全同；用調整後價格時 61 週相同，前 5 名組合 101 週相同，名次最多移 7 名，移 3 名以上的 21 筆集中在 2025-04、2025-07～08、2026-07～09 的除權息、減資前後。
