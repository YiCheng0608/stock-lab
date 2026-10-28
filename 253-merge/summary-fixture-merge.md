## verify 檢查結果（2026-10-28 23:27 台北）

- 程式：`task/253-plan-tracking-ui` @ `a3b20ac`（未 commit：.claude/skills/verify-stock-lab/db_facts.py、.claude/skills/verify-stock-lab/features/README.md、.claude/skills/verify-stock-lab/features/actions.md、.claude/skills/verify-stock-lab/features/stocks.md、.claude/skills/verify-stock-lab/features/themes.md、.claude/skills/verify-stock-lab/features/today.md、.github/workflows/ci.yml、AGENTS.md、backend/alembic/versions/0018_market_summaries.py、backend/alembic/versions/0019_strategy_levels.py、backend/alembic/versions/0020_trading_calendar.py、backend/app/api.py、backend/app/candidate_view.py、backend/app/decision.py、backend/app/domain.py、backend/app/glossary.py、backend/app/level_semantics.py、backend/app/market_change.py、backend/app/market_overview.py、backend/app/migration_revisions.py、backend/app/migrations.py、backend/app/models.py、backend/app/presentation.py、backend/app/strategies/__init__.py、backend/app/strategies/ablation.py、backend/app/strategies/base.py、backend/app/strategies/breakout_v1.py、backend/app/strategies/levels.py、backend/app/strategies/pullback_v1.py、backend/app/strategy_board.py、backend/app/theme_member_view.py、backend/app/trading_calendar.py、backend/tests/conftest.py、backend/tests/fixtures/market_summary/tpex_highlight_20261022.json、backend/tests/fixtures/market_summary/twse_mi_index_20261022.json、backend/tests/fixtures/trading_calendar/2025.json、backend/tests/fixtures/trading_calendar/2026.json、backend/tests/fixtures/trading_calendar/2027.json、backend/tests/fixtures/worker_job/wrapper_daily.txt、backend/tests/fixtures/worker_job/wrapper_news.txt、backend/tests/job_daily_child.py、backend/tests/test_action_tiers.py、backend/tests/test_backtest_research.py、backend/tests/test_candidates.py、backend/tests/test_condition_copy_source.py、backend/tests/test_coordinator_scripts.py、backend/tests/test_daily_schedule.py、backend/tests/test_database_readiness.py、backend/tests/test_domain.py、backend/tests/test_glossary.py、backend/tests/test_group_candidate_identity.py、backend/tests/test_hot_group_flow_coverage.py、backend/tests/test_instrument_identity_migration.py、backend/tests/test_market_summaries.py、backend/tests/test_news_llm.py、backend/tests/test_pipeline_integration.py、backend/tests/test_product.py、backend/tests/test_sources.py、backend/tests/test_strategy_ablation.py、backend/tests/test_strategy_board.py、backend/tests/test_strategy_formula_migration.py、backend/tests/test_strategy_levels.py、backend/tests/test_strategy_registry.py、backend/tests/test_theme_members.py、backend/tests/test_trading_calendar.py、backend/tests/test_verify_checks.py、backend/tests/test_verify_plan.py、backend/tests/test_verify_tools.py、backend/tests/test_verify_tracking.py、backend/tests/test_verify_tristate.py、backend/tests/test_watchdog.py、backend/tests/test_worker_job.py、backend/tests/test_worker_job_scripts.py、backend/worker/candidate_notes.py、backend/worker/candidates.py、backend/worker/cli.py、backend/worker/job.py、backend/worker/market_summary.py、backend/worker/news_llm.py、backend/worker/pipeline.py、backend/worker/schedule_runs.py、backend/worker/sources.py、backend/worker/strategy_levels.py、backend/worker/trading_calendar.py、docs/DATA_SOURCES.md、docs/DESIGN_SYSTEM.md、docs/GITHUB_WORKFLOW.md、docs/INDUSTRY_CLASSIFICATION.md、docs/NEWS_SPEC.md、docs/OPERATIONS.md、docs/PRODUCT_SPEC.md、docs/ROADMAP.md、docs/UI_COPY_SPEC.md、docs/V1_SPEC.md、frontend/scripts/ci-test.cjs、frontend/src/App.tsx、frontend/src/actions/ActionViews.tsx、frontend/src/actions/actionTiers.ts、frontend/src/actions/actions.test.tsx、frontend/src/api.ts、frontend/src/candidates/CandidateViews.tsx、frontend/src/candidates/candidates.fixtures.ts、frontend/src/candidates/candidates.test.tsx、frontend/src/candidates/candidates.ts、frontend/src/components/Term.tsx、frontend/src/components/ui/Badge.tsx、frontend/src/components/ui/CardList.tsx、frontend/src/components/ui/Table.tsx、frontend/src/components/ui/index.ts、frontend/src/components/ui/ui.test.tsx、frontend/src/copy.test.tsx、frontend/src/dates.ts、frontend/src/glossary.ts、frontend/src/news/NewsViews.tsx、frontend/src/news/news.test.tsx、frontend/src/news/newsView.ts、frontend/src/presentation.ts、frontend/src/stock/StockBarsChart.tsx、frontend/src/stock/StockCutoffControl.tsx、frontend/src/stock/StrategyBoardPanel.tsx、frontend/src/stock/stockBars.test.tsx、frontend/src/stock/stockBars.ts、frontend/src/stock/stockTabs.ts、frontend/src/stock/strategyBoard.fixtures.ts、frontend/src/stock/strategyBoard.test.tsx、frontend/src/stock/strategyBoard.ts、frontend/src/styles.css、frontend/src/tables.test.tsx、frontend/src/themes/ThemeViews.tsx、frontend/src/themes/themeBoards.fixtures.ts、frontend/src/themes/themeBoards.test.tsx、frontend/src/themes/themeBoards.ts、frontend/src/today/TodayViews.tsx、frontend/src/today/today.fixtures.ts、frontend/src/today/today.test.tsx、frontend/src/tracking/TrackingViews.tsx、frontend/src/tracking/tracking.test.tsx、frontend/src/tracking/tracking.ts、frontend/src/types.ts、frontend/src/units.test.ts、frontend/src/units.ts、tools/Invoke-WorkerJob.ps1、tools/Register-WorkerSchedule.ps1、tools/ci/checks.py、tools/ci/test_checks.py、tools/ops/close_task.sh、tools/ops/coordinator_json.py、tools/ops/dispatch.sh、tools/ops/watchdog.sh、tools/ops/watchdog_helper.py、tools/research/backtest_research.py、tools/verify/fixture_data.py、tools/verify/page_checks.py）
- API `http://127.0.0.1:53207`、前端 `http://127.0.0.1:53208`、DB `stock.db`（假資料庫）
- 個股 E／S：TWSE 9101，今日榜 #1 族群「半導體」的第一個成員
- 67 項：通過 67、失敗 0、無法判定 0、已知失敗 0；耗時 64 秒

### 人工檢查樣本（依 features 規則抽樣，判讀見 SKILL 真資料模式第 3 步）

| 檢查 | 樣本 |
| --- | --- |
| T10 | 3 筆，`manual/T10.json` |
| N7 | 1 筆，`manual/N7.json` |
| N8 | 1 筆，`manual/N8.json` |

### 今日 `/`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| API | 通過 | 26 項 = fixture_data.EXPECTED |
| T1 | 通過 | 2 張截圖 ready，無錯誤，無橫向捲動 |
| T2 | 通過 | `資料 2026/10/16` = facts 2026-10-16 |
| T3 | 通過 | `資料截至 2026/10/16 · TWSE／TPEx 官方資料 · 官方單日快照` |
| T4 | 通過 | `資料 2026/10/16`；B = facts 2026-10-16 |
| T5 | 通過 | 2 張卡 `資料 2026/10/16 · 相對加權指數`；#1 `半導體` |
| T6 | 通過 | 前 3 則標題都在；有 AI 判讀的卡片方向與 AI 相同並標 `AI 推論`：1 `可能正向`、5 `可能負向` |
| T7 | 通過 | `資料 2026/10/16`、`3 檔`；名次列 3、來源行 3 = items；C = facts |
| T8 | 通過 | 3 檔新聞情緒推論的來源行以 `（推論）` 結尾；`AI 推論` 5 行；免責句 3 行；入口 `AI 推論 ▸` 3、`AI 說明 ▸` 0 |
| T9 | 通過 | 6 張卡各有 `資料日` |
| T11 | 通過 | 2026-10-16：TWSE 24,012.35、TPEx 251.20；範圍 `上市為集中市場總計（含 ETF、權證等）；上櫃為上櫃股票` |
| T12 | 通過 | `明日候選`（today-1280.txt 第 33 行）→ `熱門族群`（today-1280.txt 第 160 行）、`重點新聞`（today-1280.txt 第 190 行） |
| T13 | 通過 | 3 張卡：`加入追蹤` 2、`已在追蹤` 1 = open_plan_id 非 null |

### 新聞 `/news`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| API | 通過 | 9 項 = fixture_data.EXPECTED |
| N1 | 通過 | 6 張截圖 ready，無錯誤，無橫向捲動 |
| N2 | 通過 | domestic 前 3 則、international 前 2 則、official 前 1 則依序出現 |
| N3 | 通過 | 時間行 domestic 3／3、international 2／2、official 1／1 |
| N4 | 通過 | `AI 推論`／AI 判讀 domestic 2／2、international 2／2、official 0／0 |
| N5 | 通過 | 最新新聞 2026-10-16 09:30（台北）≤ 現在；國內第一則 `發布於 2026/10/16 09:30` |
| N6 | 通過 | id 1：來源事實／AI 摘要與判讀分欄，`模型 claude-sonnet-5-5 · 提示版本 news_v2 · 產生時間 2026/10/16 11:01` |

### 族群 `/themes`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| API | 通過 | 15 項 = fixture_data.EXPECTED |
| G1 | 通過 | 5 張截圖 ready，無錯誤，無橫向捲動 |
| G2 | 通過 | `產業榜 · 共 2 個族群` → `資料 2026/10/16`、`題材榜 · 共 2 個族群` → `資料 2026/10/16`；= facts 2026-10-16 |
| G3 | 通過 | 1280 表頭與 `半導體`…`電腦及週邊`；390 `#1` → `半導體` |
| G4 | 通過 | 2 個建議：`待核實` 2、`AI 推論` 2 行，`2 個建議` |
| G5 | 通過 | 熱度走勢、五分項皆 `資料 2026/10/16`；`成員資料截至 2026/10/16` |
| G6 | 通過 | 表頭、第一個成員 9101 示範晶圓、`共 3 檔` |
| G7 | 通過 | 今日 #1 = 產業榜 #1 = 詳情 = `半導體` |
| G8 | 通過 | 成員依成交值：9101、9102、9201 |

### 個股 `/stocks`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| API | 通過 | 22 項 = fixture_data.EXPECTED |
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

### 行動 `/actions`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| API | 通過 | 25 項 = fixture_data.EXPECTED |
| A1 | 通過 | 3 張截圖 ready，無錯誤，無橫向捲動 |
| A2 | 通過 | 1 筆庫存各有 `記錄來源` |
| A3 | 通過 | 持倉風險 `顯示 1／1 檔`；今日候選 `顯示 3／3 檔`；接近成立 `顯示 2／2 檔` |
| A4 | 通過 | 6 列各有資料日 ≤ 2026/10/16；data_as_of = facts |
| A5 | 通過 | 6 列，沒有 `AI 推論` 與 `（推論）` |
| A6 | 通過 | TWSE 9101：`資料日：2026/10/16` = data_cutoff |
| A7 | 通過 | 頁首 `9101`／`示範晶圓` = stock.json |
| A8 | 通過 | 今日候選 3 列 = candidates.json 去掉持倉，依名次 [1, 2, 3] |
| A9 | 通過 | 預設清單沒有 ETF（持倉／自選 ETF 0 列）；隱藏 ETF 1 檔 |
| A10 | 通過 | `預設隱藏：ETF 1 檔；自選標的一律顯示。隱藏不刪資料，切換上方篩選即可看到。` |
| A11 | 通過 | 接近成立 2 列 = actions.json 第 3 級，連結 `價位見策略總表 →` |
| A12 | 通過 | 2 列各有 `差：`，共 4 行 |
| A13 | 通過 | 2 列除了最近收盤沒有價格（收盤 116.22、50.45） |
| A14 | 通過 | 進行中 2＋已結束 4 張卡，計畫資料日與建立日 = API |
| A15 | 通過 | 6 張卡的狀態、更正標示與模擬報酬 = API；沒有 `勝率` |
| A16 | 通過 | 我的庫存 < 追蹤計畫 < 追蹤回看 < 行動列表；庫存與模擬的行各在自己的區塊 |
| A17 | 通過 | 39 列明細 = 各卡 sessions_observed；計畫 3 的 11 列 = tracking-plan.json |
