# #564 指數總表截圖與瀏覽器實測（2026-11-09）

- 資料：正式 DB 唯讀副本（`tools/ops/copy_db.py`，`source_latest_trading_date` 2026-11-06，alembic `0029_market_bar_ohlc_nullable`，quick_check ok，見 `copy_db.json`），放在任務 volume `task-564_stock-data`；服務是本 branch 的 api＋web（compose project `task-564`，埠 8564／8565）。
- 正式 DB 目前只有加權、櫃買日線（台指期與美股尚未收集），所以真資料下另 5 列是「無資料：尚未收集」：`market-real-1280.png`、`market-real-390.png`。
- 其餘狀態（選中台指期／美股、非最新、資料不足、有季線的台指期與 NASDAQ）在**任務 volume 的副本**暫加合成列後拍攝（`seed_states.py`，來源名稱加 `_shot` 後綴；拍完以 `unseed_states.py` 刪除），不是真實行情：台指期 70 根（加權收盤附近）、S&P 500 40 根到 2026-11-04（非最新＋資料不足）、NASDAQ 70 根到 2026-11-05。加權、櫃買兩列與大盤概況都是真資料。合成列的來源名稱不在前端對照表，所以美股圖的 chart-meta 顯示「來源待核實」。
- `cdp_check.cjs`／`cdp_check.json`：headless Edge 實測 1280 與 390：Tab 到「台指期近月」按 Enter → `?index=tx`、圖變「台指期近月日線」；下一個 Tab 到「S&P 500」按 Space → `?index=spx`；點 NASDAQ 列的收盤格 → `?index=ixic`；重新整理後仍選 NASDAQ；`history.length` 不因切換增加（replace）；`scrollWidth` = `clientWidth`（無整頁橫向捲動）。`firstScreen` 是各列底部的 y 座標。
