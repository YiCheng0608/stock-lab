### 今日 `/`：失敗

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| T1 | 通過 | 1280／390 ready，無 console／HTTP 錯誤，無橫向捲動 |
| T2 | 通過 | `資料 2026-10-21`（today-1280.txt 第 7 行）；facts market_latest_trading_date 2026-10-21 |
| T3 | 通過 | `資料截至` 第 13 行，下一行 `2026/10/21`（預期 `2026/10/21`），再下一行 `TWSE／TPEx 官方資料`（source_label `TWSE／TPEx 官方資料`） |
| T4 | 通過 | `熱門族群` 第 54 行後第一個資料行 `資料 2026/10/21`（第 58 行）；B 2026-10-21，facts group_scores 2026-10-21 |
| T5 | 通過 | 卡片日期行 10 = min(10, 10)；#1 `鋼鐵` 第 60 行 |
| T6 | 失敗 | #1958「Polymarket trade…」`/api/news/1958` ai done／inference true（negative），卡片（第 25～34 行）顯示 `影響尚未判定`、無 `AI 推論`；#1952「How Ukraine’s dr…」`/api/news/1952` ai done／inference true（negative），卡片（第 35～44 行）顯示 `影響尚未判定`、無 `AI 推論`；#1946「台股反彈594點！分析師拋「4萬…」`/api/news/1946` ai done／inference true（positive），卡片（第 45～53 行）顯示 `影響尚未判定`、無 `AI 推論` |
| T7 | 通過 | `明日候選` 第 180 行下接 `資料 2026/10/21`、`20 檔`；`^來源：` 20 行 = items 20；C 2026-10-21 = facts 2026-10-21 |
| T8 | 通過 | news_sentiment.inference true 20 檔，來源行結尾（推論）缺 0；整行 `AI 推論` 20 ≥ 20；免責句 20 = 20 |
| T9 | 通過 | `查看個股詳情 →` 6 行，`資料日 YYYY/MM/DD` 6 行 |

截圖：shots/today-1280.png、shots/today-390.png
