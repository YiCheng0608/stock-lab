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
