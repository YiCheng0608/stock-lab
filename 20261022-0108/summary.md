## verify-stock-lab 結果（2026-10-22 01:08 台北）

- 程式：`task/227-verify-skill` @ `9651574`
- 副本：資料日 2026-10-21（`market_bars` 最新），alembic `0016_group_score_archive`，複製 22.9 秒
- Doctor：health 200、readiness 通過、proxy 200、facts 通過（`portfolio_positions` 0，證據全部可推送）
- 證據：https://github.com/YiCheng0608/stock-lab/tree/pr-assets/227/20261022-0108

| 導覽 | 結果 | 失敗或無法判定的檢查 |
| --- | --- | --- |
| 今日 `/` | 失敗 | T6：今日市場前 3 則新聞（`/api/news/1958`、`1952`、`1946`）API 皆 `ai.status` done、`inference` true、有 `impact_direction`，今日卡卻顯示 `影響尚未判定`、無 `AI 推論`（today-1280.txt 第 30、40、50 行）；同一則 1946 在新聞頁顯示 `可能正向`＋`AI 推論` |
| 新聞 `/news` | 通過 | — |
| 族群 `/themes` | 通過 | — |
| 個股 `/stocks` | 通過 | — |
| 行動 `/actions` | 通過 | — |

路徑：今日 #1 產業「鋼鐵」→ 族群詳情 → 個股 TWSE 3004 豐達科 → 行動 TWSE 3004。
耗時：Launch 0:50、Doctor 0:05、Drive 8:58。

### 今日 `/`：失敗

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| T1 | 通過 | 1280／390 ready，無 httpErrors／consoleErrors，無橫向捲動（shots/today.jsonl） |
| T2 | 通過 | `資料 2026-10-21` 整行出現（today-1280.txt 第 7 行）= facts `market_latest_trading_date` 2026-10-21 |
| T3 | 通過 | `資料截至` 下一行 `2026/10/21`，再下一行 `TWSE／TPEx 官方資料` = `market.source_label`（第 13～15 行） |
| T4 | 通過 | `熱門族群` 後第一個資料行 `資料 2026/10/21`（第 58 行）= today-board `meta.trading_date` = facts `group_scores_latest_trading_date` 2026-10-21 |
| T5 | 通過 | `資料 2026/10/21 · 相對加權指數` 10 行 = min(10, 10)；`鋼鐵` 整行出現（第 60 行） |
| T6 | 失敗 | 3 則標題皆出現（比對時把全形空白正規化為半形），但 `/api/news/1958`、`/api/news/1952`（ai done、inference true、impact_direction negative）與 `/api/news/1946`（done、true、positive）在今日卡都顯示 `影響尚未判定`、無整行 `AI 推論`（第 30、40、50 行） |
| T7 | 通過 | `明日候選` 下一行 `資料 2026/10/21`、再下一行 `20 檔`；`來源：` 20 行 = items 20；trading_date 2026-10-21 = facts `candidate_run_latest_trading_date` |
| T8 | 通過 | 20 個 `news_sentiment.inference` true 的候選來源行皆以 `（推論）` 結尾；整行 `AI 推論` 20 行 ≥ 20；免責句 20 行 = 20 |
| T9 | 通過 | `查看個股詳情 →` 6 行 = `資料日 YYYY/MM/DD` 6 行（皆 `資料日 2026/10/21`） |

截圖：shots/today-1280.png、shots/today-390.png

### 新聞 `/news`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| N1 | 通過 | 6 張截圖（news 1280／390、news-international 1280、news-official 1280、news-detail 1280／390）ready，無錯誤，無橫向捲動（shots/news.jsonl） |
| N2 | 通過 | 國內、國際、官方各 20 則；前 3 則標題依序整行出現（國內第 18／29／40 行、國際第 18／29／40 行、官方第 18／30／42 行；比對時全形空白正規化） |
| N3 | 通過 | 國內 20／20、國際 20／20、官方 20／20 張卡有時間行 |
| N4 | 通過 | 國內 `AI 推論` 20 行 = API done 且 inference 20 則；國際 20 = 20；官方 7 = 7 |
| N5 | 通過 | facts `news_latest_published_at` 2026-10-21 15:59（不晚於台北 2026-10-22 01:12）；國內第一則 `發布於 2026/10/21 23:32` 不晚於今天 |
| N6 | 通過 | `/news/1946`：`來源事實`、`AI 摘要與判讀` 整行出現，下一行 `AI 推論`；有 `模型 claude-haiku-5-5 · 提示版本 news_v1 · …` 行（390 寬同樣兩欄都在） |

另見（不影響判定）：詳情頁的模型行顯示 `產生時間 待核實`，API `ai.generated_at` 為 `2026-10-21T16:01:32.746332`（無時區）。

截圖：shots/news-1280.png、shots/news-390.png、shots/news-international-1280.png、shots/news-official-1280.png、shots/news-detail-1280.png、shots/news-detail-390.png

### 族群 `/themes`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| G1 | 通過 | 5 張截圖（themes 1280／390、themes-theme 1280、theme-detail 1280／390）ready，無錯誤，無橫向捲動（shots/themes.jsonl） |
| G2 | 通過 | `產業榜 · 共 34 個族群` 下一行 `資料 2026/10/21`（themes-1280.txt 第 15～16 行）；`題材榜 · 共 12 個族群` 下一行 `資料 2026/10/21`（themes-theme-1280.txt 第 15～16 行）；兩榜 `trading_date` = `data_as_of` = facts 2026-10-21 |
| G3 | 通過 | 兩榜皆有 `排名\t族群…` 表頭；產業 `鋼鐵`／`電子通路`、題材 items[0]／`CoWoS 先進封裝` 皆整行出現；390 寬 `#1` 下一行 `鋼鐵` |
| G4 | 通過 | 12 則建議；整行 `待核實` 20 行、`AI 推論` 20 行，皆 ≥ 12；`433 個建議 · 最近更新 2026/10/21 21:36` 存在（meta.total 433） |
| G5 | 通過 | `熱度走勢`、`五分項` 下一行皆 `資料 2026/10/21`（theme-detail-1280.txt 第 25～26、53～54 行）；`成員資料截至 2026/10/21`（第 71 行，M = 2026-10-21） |
| G6 | 通過 | 成員表頭整行存在；第一個成員 `3004	豐達科	上市	成員	123	2026/10/21`（第 77 行）；`第 1／2 頁 · 共 48 檔`（第 107 行） |
| G7 | 通過 | 今日 #1 `鋼鐵` = 產業榜 items[0] `鋼鐵` = 詳情 `theme.display_name` `鋼鐵`（theme_id `official-industry-b597d5609a60578d`） |

截圖：shots/themes-1280.png、shots/themes-390.png、shots/themes-theme-1280.png、shots/theme-detail-1280.png、shots/theme-detail-390.png

### 個股 `/stocks`：通過（TWSE 3004 豐達科）

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| S1 | 通過 | 7 張截圖（stocks 1280／390、stock 1280／390、stock-research／stock-news／stock-data 1280）ready，`missingClicks` 空，無錯誤，無橫向捲動（shots/stocks.jsonl） |
| S2 | 通過 | 表頭整行存在（stocks-1280.txt 第 22 行）；`00411A` 開頭列存在（items[0]）；`第 1／81 頁 · 共 2,410 筆`（第 53 行）= meta total_pages 81、total 2410 |
| S3 | 通過 | 整行 `3004`；第一個 `資料 2026-10-21` 在導覽列，第二個 `資料 2026-10-21`（stock-1280.txt 第 16 行），下一行 `來源 臺灣證券交易所`；bars `data_as_of` 2026-10-21 |
| S4 | 通過 | `K 線與技術指標` 下一行 `資料 2026-10-21`；有 `來源 臺灣證券交易所` 與 `日線批次計算於 2026-10-21 21:35（台灣時間）` |
| S5 | 通過 | stock-research-1280.txt 有 `研究動作`（第 27 行）、`資料日期：2026/10/21 · …`（第 33 行）、`資料日：2026/10/21 · 價位語意：…`（第 35 行）；`candidate` 為 null，不查候選推論 |
| S6 | 通過 | `3004 相關新聞`（第 28 行）；`/news?symbol=3004` 0 則相符，顯示 `尚無與此股已核實關聯的新聞或公告。`（第 31 行） |
| S7 | 通過 | `K 線資料日期` 下一行 `2026-10-21`；`行情來源` 下一行 `臺灣證券交易所`；`行情來源完整 · 資料日 2026/10/21` 以 `資料日 2026/10/21` 結尾（stock-data-1280.txt 第 46、68～69、78～79 行） |
| S8 | 通過 | I 2026-10-21 = facts-stock `instrument.latest_trading_date` 2026-10-21；`instrument.source` `twse` |

截圖：shots/stocks-1280.png、shots/stocks-390.png、shots/stock-1280.png、shots/stock-390.png、shots/stock-research-1280.png、shots/stock-news-1280.png、shots/stock-data-1280.png

### 行動 `/actions`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| A1 | 通過 | 3 張截圖（actions 1280／390、action-detail 1280）ready，`missingClicks` 空，無錯誤，無橫向捲動（shots/actions.jsonl） |
| A2 | 通過 | `我的庫存` 整行存在；`portfolio.json` items 0，`尚未建立庫存。` 整行存在 |
| A3 | 通過 | `第 1 頁 · 本頁 20 筆 · 共 1,858 筆` 整行存在 = items 20、meta.total 1858 |
| A4 | 通過 | `查看個股詳情 →` 20 行 = `資料日 YYYY/MM/DD` 20 行，皆 `資料日 2026/10/21`；meta.data_as_of 2026-10-21 = facts `market_latest_trading_date` |
| A5 | 通過 | actions-1280.txt 無任何含 `推論` 的行 |
| A6 | 通過 | TWSE 3004：整行 `3004` 與 `研究動作`；`資料日：2026/10/21 · 價位語意：…` = `decision_summary.data_cutoff` 2026-10-21 |
| A7 | 通過 | action-detail 頁首 `3004`／`豐達科` = stock.json `instrument.symbol`／`name` |

截圖：shots/actions-1280.png、shots/actions-390.png、shots/action-detail-1280.png

