## verify 檢查結果（2026-11-12 18:04 台北）

- 程式：`task/649-watch-page-slim` @ `2885bae1`（未 commit：.claude/skills/verify-stock-lab/features/actions.md、docs/DESIGN_SYSTEM.md、docs/PRODUCT_SPEC.md、docs/UI_COPY_SPEC.md、frontend/src/App.tsx、frontend/src/actions/ActionViews.tsx、frontend/src/actions/actionTiers.ts、frontend/src/actions/actions.test.tsx、frontend/src/navigation.test.tsx、frontend/src/stock/gapWording.test.tsx、frontend/src/styles.css、frontend/src/tracking/TrackingViews.tsx、frontend/src/tracking/tracking.test.tsx、tools/verify/page_checks.py）
- API `http://127.0.0.1:28649`、前端 `http://127.0.0.1:28650`、DB `stock.db`（假資料庫）
- 個股 E／S：TWSE 9101，今日榜 #1 族群「半導體」的第一個成員
- 截圖並行 4（預設）
- 19 項：通過 19、失敗 0、無法判定 0、已知失敗 0；耗時 14 秒

### 我的追蹤 `/watch`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| API | 通過 | 25 項 = fixture_data.EXPECTED |
| A1 | 通過 | 4 張截圖 ready，無錯誤，無橫向捲動 |
| A2 | 通過 | 1 筆庫存各有 `記錄來源` |
| A3 | 通過 | 持倉風險 `顯示 1／1 檔`；今日候選 `顯示 3／3 檔`；接近成立 `顯示 2／2 檔` |
| A4 | 通過 | 6 列各有資料日 ≤ 2026/10/16；data_as_of = facts |
| A5 | 通過 | 6 列，沒有 `AI 推論` 與 `（推論）` |
| A6 | 通過 | TWSE 9101：`資料日：2026/10/16` = data_cutoff |
| A7 | 通過 | 頁首 `9101`／`示範晶圓` = stock.json |
| A8 | 通過 | 今日候選 3 列 = candidates.json 去掉持倉，依名次 [1, 2, 3] |
| A9 | 通過 | 預設清單沒有 ETF（持倉／自選 ETF 0 列）；隱藏 ETF 1 檔 |
| A10 | 通過 | `預設隱藏：ETF 1 檔`；「說明」有隱藏說明 |
| A11 | 通過 | 接近成立 2 列 = actions.json 第 3 級，連結 `價位見策略總表 →` |
| A12 | 通過 | 2 列各有 `差：`，共 4 行 |
| A13 | 通過 | 2 列除了最近收盤沒有價格（收盤 116.22、50.45） |
| A14 | 通過 | 進行中 2＋已結束 4 張卡，計畫資料日與建立日 = API |
| A15 | 通過 | 6 張卡的狀態、更正標示與模擬報酬 = API；沒有 `勝率` |
| A16 | 通過 | 我的庫存 < 追蹤計畫 < 行動列表 < 追蹤回看；庫存與模擬的行各在自己的區塊 |
| A17 | 通過 | 39 列明細 = 各卡 sessions_observed；計畫 3 的 11 列 = tracking-plan.json |
| A18 | 通過 | `/watch` 是 `我的追蹤`；`/actions?from=legacy#plan-0` 轉到 `/watch?from=legacy#plan-0` |
