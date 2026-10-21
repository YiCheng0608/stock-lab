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
