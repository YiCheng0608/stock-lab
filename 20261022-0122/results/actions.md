### 行動 `/actions`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| A1 | 通過 | 3 張截圖 ready，missingClicks 空，無 console／HTTP 錯誤，無橫向捲動 |
| A2 | 通過 | `我的庫存` 第 24 行；portfolio items 0，`尚未建立庫存。` 第 39 行 |
| A3 | 通過 | `第 1 頁 · 本頁 20 筆 · 共 1,858 筆` 第 206 行 |
| A4 | 通過 | 20 張卡、20 行 `資料日 YYYY/MM/DD`（2026/10/21），晚於 2026/10/21 的 0 行；data_as_of 2026-10-21 = facts 2026-10-21 |
| A5 | 通過 | actions-1280.txt 無 `推論` |
| A6 | 通過 | 整行 `3004` 第 9 行、`研究動作` 第 27 行（下接 `暫無研究條件`）；`資料日：2026/10/21`（第 35 行）= data_cutoff 2026/10/21 |
| A7 | 通過 | action-detail 頁首 `3004`／`豐達科`（第 9～10 行）= stock.json `3004`／`豐達科` |

截圖：shots/actions-1280.png、shots/actions-390.png、shots/action-detail-1280.png
