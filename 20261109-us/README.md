# #568 美股四檔改用 FinMind：大盤頁截圖（2026-11-09）

- 資料：任務 volume `task-568_stock-data` 的空 DB（`init_db`），用 `seed_from_ac1.py` 跑 `us_index_bars.collect_us_indexes`。fetch 回傳 AC-1 存下的四份 FinMind 回應（2026-11-09 07:57 台北），沒有發任何請求。四檔各 799 列，2023-09-01～2026-11-06。台股三列沒有資料，所以顯示「無資料」。
- 服務：本 branch 的 api＋web（compose project `task-568`，埠 8568／8569），head `b164119`。
- `shots.cjs`：headless Edge，1280×800 與 390×844，`/market?index=spx`、`?index=sox`，展開 `<details>` 後拍整頁；`shots.json` 是頁面文字的檢查：
  - 含 FinMind 的行，含 FRED 的行（0 行）。
  - 「只有收盤」的說明（沒有）。
  - `scrollWidth`／`clientWidth`（相等，沒有整頁橫向捲動）。
- 看點：
  - 美股列的來源欄是「FinMind」，資料說明是「資料來源：FinMind（個人非商業使用）」。
  - S&P 500 畫 K 棒與量柱；資料表的「成交量（億股）」11/06 是 57.02。
  - 費半沒有量：沒有量柱，量欄留空。
