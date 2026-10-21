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
