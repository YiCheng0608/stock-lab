## verify-stock-lab 結果（2026-10-22 01:37 台北）

- 程式：`task/227-verify-skill` @ `fe06b9c`
- 副本：資料日 2026-10-21（`market_bars` 最新），alembic `0016_group_score_archive`，複製 5.9 秒
- Doctor：health 200、readiness 通過、proxy 200
- 證據：https://github.com/YiCheng0608/stock-lab/tree/pr-assets/227/20261022-0137

| 導覽 | 結果 | 失敗或無法判定的檢查 |
| --- | --- | --- |
| 今日 `/` | 失敗 | T6：前 3 則新聞（`/api/news/1958`、`/1952`、`/1946`）皆有 AI 判讀（done＋inference），今日卡顯示 `影響尚未判定`、無 `AI 推論`（today-1280.txt 第 30、40、50 行）；`/api/dashboard` 的 `news[]` 不帶 `ai`、`impact_direction` 為 `unknown` |
| 新聞 `/news` | 通過 | — |
| 族群 `/themes` | 通過 | — |
| 個股 `/stocks` | 通過 | — |
| 行動 `/actions` | 通過 | — |

路徑：今日 #1 產業「鋼鐵」→ 族群詳情 → 個股 TWSE 3004 → 行動 TWSE 3004。
耗時：Launch 0:34、Doctor 0:05、Drive 8:25。

### 今日 `/`：失敗

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| T1 | 通過 | 1280／390 ready，httpErrors、consoleErrors 皆空，無橫向捲動（scrollWidth = clientWidth） |
| T2 | 通過 | today-1280.txt 第 7 行 `資料 2026-10-21` = facts `market_latest_trading_date` 2026-10-21 |
| T3 | 通過 | 第 13 行 `資料截至` → 第 14 行 `2026/10/21` → 第 15 行 `TWSE／TPEx 官方資料` = `market.source_label` |
| T4 | 通過 | 第 54 行 `熱門族群` 後第一個 `資料 ` 行為第 58 行 `資料 2026/10/21`；B 2026-10-21 = facts `group_scores_latest_trading_date` |
| T5 | 通過 | `資料 2026/10/21 · 相對加權指數` 10 行 = min(10, 10)；`items[0].display_name`「鋼鐵」為第 60 行整行 |
| T6 | 失敗 | 三則標題皆整行出現（第 25、35、45 行），但 `/api/news/1958`、`/api/news/1952`、`/api/news/1946` 的 `ai` 皆 done＋inference true（方向 negative／negative／positive），今日卡分別在第 30、40、50 行顯示 `影響尚未判定`，三張卡都沒有 `AI 推論`。`dashboard.json` 的 `news[]` 沒有 `ai` 欄位、`impact_direction` 為 `unknown` |
| T7 | 通過 | status `success`、20 則：第 180 行 `明日候選` → 第 181 行 `資料 2026/10/21` → 第 182 行 `20 檔`；`^來源：` 20 行 = items 20；C 2026-10-21 = facts `candidate_run_latest_trading_date` |
| T8 | 通過 | 20 筆 `news_sentiment.inference` 皆 true，對應 20 行 `^來源：` 結尾皆為 `（推論）`；整行 `AI 推論` 20 行 ≥ 20；免責句 20 行 = 20 |
| T9 | 通過 | `查看個股詳情 →` 6 行，`^資料日 YYYY/MM/DD$` 6 行（第 1343～1383 行，皆 `資料日 2026/10/21`） |

截圖：shots/today-1280.png、shots/today-390.png

### 新聞 `/news`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| N1 | 通過 | 6 張截圖（news 1280／390、news-international 1280、news-official 1280、news-detail 1280／390）ready，httpErrors、consoleErrors 皆空，無橫向捲動 |
| N2 | 通過 | 國內前 3 則標題依序為 news-1280.txt 第 19、30、41 行；國際前 3 則依序為 news-international-1280.txt 第 19、30、41 行；官方 API 標題含 `\r\n`（頁面顯示為空白），改比來源標籤與時間：前 3 張卡依序為 `公開資訊觀測站公告`（`source_name` MOPS）＋ `事件日 2026/10/20`（= `event_date` 2026-10-20），第 17／23、29／35、41／47 行 |
| N3 | 通過 | 時間行：國內 20／20、國際 20／20、官方 20／20 |
| N4 | 通過 | 整行 `AI 推論`：國內 20 = API done 20、國際 20 = 20、官方 7 = 7 |
| N5 | 通過 | facts `news_latest_published_at` 2026-10-21 15:59 UTC → 23:59 台北，早於現在 2026-10-22 01:41；國內第一則時間行 `發布於 2026/10/21 23:32`（第 23 行）不晚於今天 |
| N6 | 通過 | news-detail（id 1946）：第 11 行 `來源事實`、第 28 行 `AI 摘要與判讀` → 第 29 行 `AI 推論`；ai done，第 49 行以 `模型 claude-haiku-5-5 · 提示版本 news_v1` 開頭（產生時間顯示 `待核實`，`ai.generated_at` 無時區，依前端規則不顯示） |

截圖：shots/news-1280.png、shots/news-390.png、shots/news-international-1280.png、shots/news-official-1280.png、shots/news-detail-1280.png、shots/news-detail-390.png

### 族群 `/themes`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| G1 | 通過 | 5 張截圖（themes 1280／390、themes-theme 1280、theme-detail 1280／390）ready，httpErrors、consoleErrors 皆空，無橫向捲動 |
| G2 | 通過 | themes-1280.txt 第 15 行 `產業榜 · 共 34 個族群` → 第 16 行 `資料 2026/10/21`；themes-theme-1280.txt 第 15 行 `題材榜 · 共 12 個族群` → 第 16 行 `資料 2026/10/21`；B 2026-10-21 = facts `group_scores_latest_trading_date`（data_as_of 與 trading_date 相同，無 `官方資料` 行） |
| G3 | 通過 | 兩榜第 20 行表頭以 `排名\t族群` 開頭；產業榜首「鋼鐵」第 22 行、末「電子通路」第 121 行；題材榜首「金控」第 22 行、末「CoWoS 先進封裝」第 55 行；themes-390.txt 第 11 行 `#1` → 第 12 行「鋼鐵」 |
| G4 | 通過 | 建議 20 則：整行 `待核實` 20 行、`AI 推論` 20 行；第 125 行 `433 個建議 · 最近更新 2026/10/21 21:36` |
| G5 | 通過 | theme-detail-1280.txt 第 25 行 `熱度走勢` → `資料 2026/10/21`、第 53 行 `五分項` → `資料 2026/10/21`；第 71 行 `成員資料截至 2026/10/21`（M = members `data_as_of` 2026-10-21） |
| G6 | 通過 | 第 76 行表頭 `代號\t名稱\t市場\t角色\t收盤\t資料日期`；第 77 行 `3004\t豐達科\t上市\t成員\t123\t2026/10/21`；第 107 行 `第 1／2 頁 · 共 48 檔`（48 檔、每頁 30） |
| G7 | 通過 | 今日 `#1`「鋼鐵」（today-1280.txt 第 60 行）= 產業榜 `items[0].display_name`「鋼鐵」= 詳情 `theme.display_name`「鋼鐵」（theme-detail-1280.txt 第 12 行） |

截圖：shots/themes-1280.png、shots/themes-390.png、shots/themes-theme-1280.png、shots/theme-detail-1280.png、shots/theme-detail-390.png

### 個股 `/stocks`：通過（TWSE 3004 豐達科）

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| S1 | 通過 | 7 張截圖（stocks 1280／390、stock 1280／390、stock-research、stock-news、stock-data 1280）ready，missingClicks、httpErrors、consoleErrors 皆空，無橫向捲動 |
| S2 | 通過 | stocks-1280.txt 第 22 行表頭 `代號\t名稱\t交易所\t類型\t最近收盤\t目前研究動作\t策略判斷資料`；第 23 行以 `items[0]` 代號 `00411A` 開頭；第 53 行 `第 1／81 頁 · 共 2,410 筆` |
| S3 | 通過 | stock-1280.txt 第 9 行 `3004`；第一個 `資料 ` 行為導覽列第 7 行 `資料 2026-10-21`，第二個為第 16 行 `資料 2026-10-21`，下一行 `來源 臺灣證券交易所`；I 2026-10-21 = bars `data_as_of` |
| S4 | 通過 | 第 28 行 `K 線與技術指標` → 第 29 行 `資料 2026-10-21`；第 41 行 `來源 臺灣證券交易所`、第 43 行 `日線批次計算於 2026-10-21 21:35（台灣時間）` |
| S5 | 通過 | stock-research-1280.txt 第 27 行 `研究動作`；第 33 行 `資料日期：2026/10/21 · …`、第 35 行 `資料日：2026/10/21 · 價位語意：未驗證規則參考價 · …`；`candidate` 為 null，不查明日候選 |
| S6 | 通過 | stock-news-1280.txt 第 28 行 `3004 相關新聞`；`stock-news.json` 0 則（相符 0 則），第 31 行 `尚無與此股已核實關聯的新聞或公告。` |
| S7 | 通過 | stock-data-1280.txt 第 78 行 `K 線資料日期` → `2026-10-21`；第 68 行 `行情來源` → `臺灣證券交易所`；第 46 行 `行情來源完整 · 資料日 2026/10/21` |
| S8 | 通過 | I 2026-10-21 = facts-stock `instrument.latest_trading_date` 2026-10-21；`instrument.source` = `twse` |

截圖：shots/stocks-1280.png、shots/stocks-390.png、shots/stock-1280.png、shots/stock-390.png、shots/stock-research-1280.png、shots/stock-news-1280.png、shots/stock-data-1280.png

### 行動 `/actions`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| A1 | 通過 | 3 張截圖（actions 1280／390、action-detail 1280）ready，missingClicks、httpErrors、consoleErrors 皆空，無橫向捲動 |
| A2 | 通過 | actions-1280.txt 第 24 行 `我的庫存`；`portfolio.json` items 空，第 39 行 `尚未建立庫存。` |
| A3 | 通過 | 第 206 行 `第 1 頁 · 本頁 20 筆 · 共 1,858 筆` |
| A4 | 通過 | `查看個股詳情 →` 20 行 = `^資料日 YYYY/MM/DD$` 20 行，皆 `資料日 2026/10/21`，不晚於 `meta.data_as_of` 2026-10-21；data_as_of = facts `market_latest_trading_date` 2026-10-21 |
| A5 | 通過 | actions-1280.txt 不含 `推論` |
| A6 | 通過 | action-detail-1280.txt 第 9 行 `3004`、第 27 行 `研究動作`；第 35 行 `資料日：2026/10/21 · 價位語意：…` = `decision_summary.data_cutoff` 2026-10-21 |
| A7 | 通過 | action-detail 頁首第 9～10 行 `3004`、`豐達科` = `stock.json` `instrument.symbol` 3004、`name` 豐達科 |

截圖：shots/actions-1280.png、shots/actions-390.png、shots/action-detail-1280.png

