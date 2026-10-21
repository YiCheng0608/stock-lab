### 行動 `/actions`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| A1 | 通過 | 3 張截圖 ready，無錯誤、無橫向捲動 |
| A2 | 通過 | `我的庫存` actions-1280.txt 第 24 行；庫存 0 筆，`尚未建立庫存。` actions-1280.txt 第 39 行 |
| A3 | 通過 | `第 1 頁 · 本頁 20 筆 · 共 1,858 筆` actions-1280.txt 第 206 行 |
| A4 | 通過 | `查看個股詳情 →` 20 行、`資料日` 20 行（['資料日 2026/10/21']）；data_as_of 2026-10-21 = facts 2026-10-21 |
| A5 | 通過 | 不含 `推論` |
| A6 | 通過 | `3004` action-detail-1280.txt 第 9 行、`研究動作` action-detail-1280.txt 第 27 行；`資料日：` 行 `資料日：2026/10/21 · 價位語意：未驗證規則參考價 · 規則與官方資料詳見資料說明。`，data_cutoff 2026/10/21 |
| A7 | 通過 | 行動詳情頁首 `3004` `豐達科`（action-detail-1280.txt 第 10 行）= stock.json `3004 豐達科` |

截圖：shots/action-detail-1280.png、shots/actions-1280.png、shots/actions-390.png
