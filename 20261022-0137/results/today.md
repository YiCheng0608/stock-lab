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
