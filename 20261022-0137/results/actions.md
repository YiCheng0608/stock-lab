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
