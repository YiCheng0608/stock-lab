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
