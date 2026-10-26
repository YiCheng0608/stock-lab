## verify 檢查結果（2026-10-26 17:55 台北）

- 程式：`task/274-strategy-board` @ `f1f3301`（未 commit：.claude/skills/verify-stock-lab/features/actions.md、.claude/skills/verify-stock-lab/features/stocks.md、backend/app/api.py、backend/app/presentation.py、backend/app/strategies/levels.py、backend/app/strategy_board.py、backend/tests/test_strategy_board.py、backend/tests/test_strategy_levels.py、backend/tests/test_verify_plan.py、backend/tests/test_watchdog.py、backend/worker/strategy_levels.py、frontend/scripts/ci-test.cjs、frontend/src/App.tsx、frontend/src/candidates/CandidateViews.tsx、frontend/src/candidates/candidates.test.tsx、frontend/src/stock/StrategyBoardPanel.tsx、frontend/src/stock/strategyBoard.fixtures.ts、frontend/src/stock/strategyBoard.test.tsx、frontend/src/stock/strategyBoard.ts、frontend/src/styles.css、frontend/src/today/today.test.tsx、frontend/src/types.ts、tools/ops/watchdog.sh、tools/ops/watchdog_helper.py、tools/verify/fixture_data.py、tools/verify/page_checks.py）
- API `http://127.0.0.1:18275`、前端 `http://127.0.0.1:4275`、DB `stock.db`（假資料庫）
- 個股 E／S：TWSE 9101，今日榜 #1 族群「半導體」的第一個成員
- 20 項：通過 20、失敗 0、無法判定 0、已知失敗 0；耗時 30 秒

### 個股 `/stocks`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| API | 通過 | 21 項 = fixture_data.EXPECTED |
| S1（TWSE 9101） | 通過 | 8 張截圖 ready，無錯誤，無橫向捲動 |
| S1（TPEx 9204） | 通過 | 6 張截圖 ready，無錯誤，無橫向捲動 |
| S2 | 通過 | 表頭、第一列、`第 1／1 頁 · 共 8 筆` |
| S3（TWSE 9101） | 通過 | 頁首 `資料 2026/10/16`、`來源 臺灣證券交易所`；bars data_as_of 2026-10-16 |
| S3（TPEx 9204） | 通過 | 頁首 `資料 2026/10/16`、`來源 證券櫃檯買賣中心`；bars data_as_of 2026-10-16 |
| S4（TWSE 9101） | 通過 | K 線卡 `資料 2026/10/16`、來源與批次時間 |
| S4（TPEx 9204） | 通過 | K 線卡 `資料 2026/10/16`、來源與批次時間 |
| S5（TWSE 9101） | 通過 | `資料日期：2026/10/16`、`資料日：2026/10/16 · 價位語意：`；候選 #1：`每日候選`、`AI 推論`、`（推論）` |
| S5（TPEx 9204） | 通過 | `資料日期：2026/10/16`、`資料日：2026/10/16 · 價位語意：` |
| S10（TWSE 9101） | 通過 | `策略總表` 資料 2026-10-16；突破條件 成立、回踩條件 觀察；觀察價位 1 列；候選第 1 名 |
| S10（TPEx 9204） | 通過 | `策略總表` 資料 2026-10-16；突破條件 資料不足、回踩條件 資料不足；觀察價位 0 列；非候選 |
| S6（TWSE 9101） | 通過 | 1 則相符新聞，時間行 1 |
| S6（TPEx 9204） | 通過 | 0 則相符新聞，顯示 `尚無與此股已核實關聯的新聞或公告。` |
| S7（TWSE 9101） | 通過 | K 線資料日期 2026/10/16、行情來源 `臺灣證券交易所`、`…資料日 2026/10/16` |
| S7（TPEx 9204） | 通過 | K 線資料日期 2026/10/16、行情來源 `證券櫃檯買賣中心`、`…資料日 2026/10/16` |
| S8（TWSE 9101） | 通過 | facts I 2026-10-16 = API；source `twse` |
| S8（TPEx 9204） | 通過 | facts I 2026-10-16 = API；source `tpex` |
| S9（TWSE 9101） | 通過 | 最新一列 2026/10/16；來源行 25 = min(30, 25) |
| S9（TPEx 9204） | 通過 | chips 空，顯示 `尚無可核實的籌碼資料。` |
