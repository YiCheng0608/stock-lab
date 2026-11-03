<!-- owns: technical backtest 口徑、使用者追蹤計畫 -->
# Tracking 與使用者追蹤計畫

## Tracking 與 technical backtest 口徑

1. T+1 起依觸發條件成交；買賣各採不利 5 bps 滑價，淨報酬扣預設 30 bps round-trip 成本，並寫入 evidence。成本與滑價是固定假設，不區分商品與情境，不是真實通用費率。
2. 每筆訊號最多追蹤 20 個交易日；T+5、T+20 各寫一筆 settlement。公司行動需可追溯調整因子；停牌、缺可判定價格或同日 stop／target 皆觸及且順序未知時標 incomparable。
3. replay 固定 canonical version，保存日期範圍、cutoff、設定快照與執行數；相同成功 request key 可重用既有 run。研究用的策略覆寫（`backtest(registry=...)`，逐一移除條件的 ablation 見 `app.strategies.ablation`）只在正式 DB 的副本或隔離 DB 執行：覆寫的策略以自己的名稱與 kind 寫 `strategy_versions`，request key 加 `:research:<策略名稱>`，不重用 canonical run，也不進 `REGISTRY`。研究 run 每個交易日的訊號寫完就 commit，追蹤每批 2,000 個訊號 commit 一次，摘要以 SQL 彙總；中途失敗時已 commit 的訊號、evaluation 與 settlement 留在同一個 namespace，run 記 `failed`，重跑（或成功後加 `--force`）會覆寫成與一次跑完相同的結果；研究腳本在 daily 時段前以同一機制停下（`should_stop`，`BacktestPaused`）。不帶覆寫的 replay 仍是單一 transaction，失敗時全部 rollback（[#318](https://github.com/YiCheng0608/stock-lab/issues/318)）。
4. audit 保存 observation、data_incomplete 等所有規則列；technical summary 只納入 actionable evidence，按策略／標的類型／T+5、T+20 分組。
5. 三個月或更短一律標 `insufficient_sample`；更長也不等於參數最佳化、walk-forward、獨立 OOS 或策略有效。勝率不能單獨決定採用。
6. 逐日成交與出場規則只寫在 `app.tracking.track_path`（T+N 結果為 `settle`），系統訊號追蹤（`worker.pipeline._evaluate_signal_tracking`）與[使用者追蹤計畫](#使用者追蹤計畫)共用。

## 使用者追蹤計畫

`plan_tracking_v1`：使用者把一筆成立的研究條件存成計畫，系統每日以日線規則模擬成交與出場。計畫不是實際成交，也不寫入或讀取持倉（`portfolio_positions`）；不統計勝率或達標率。

**建立**（`app.tracking_plans.create_plan`）：來源是今日候選（`source_kind=candidate`，另記 `daily_candidate_id` 與 `score_version`）或個股頁研究條件（`stock`）的訊號，須同時符合：

1. 訊號 `status=conditional`，且價位通過 `validate_signal_levels`（pullback 另須有回踩區上下緣），否則 `signal_not_conditional`／`invalid_levels`。
2. 訊號日等於該股 `market_bars` 的最新日，否則 `stale_signal`：追蹤從訊號日的下一個交易日起算，用較早的訊號建計畫等於回看已知的走勢。某日 collect 已寫入日線、analyze 還沒寫入該日訊號時（同一次 daily 的兩步之間，或 analyze 失敗待重跑；例如 18:30 collect 成功、21:30 重跑 analyze 之前），該股只有前一日的訊號，一律 `stale_signal`；analyze 成功後才能以新一日的訊號建立。休市日最新日線與最新訊號同一天，可以建立。
3. 指定候選時，候選列的 `signal_id` 必須是這筆訊號（`candidate_signal_mismatch`）。

同一訊號同時最多一個未取消的計畫（部分唯一索引 `uq_tracking_plan_open_signal`），重複加入回傳原計畫；取消後可再建一個新計畫。建立時快照策略名稱、`strategy_version_id`、`formula_version`、`score_version`、`tracking_version`、計畫資料日（`plan_date`＝訊號日）、最早執行日與全部價位，之後訊號被 analyze 改寫也不影響計畫。

**每日更新**（daily 的 `plan_tracking` 步驟，`worker.plan_tracking`）：每個未結束的計畫從 `plan_date` 起以[Tracking 口徑](#tracking-與-technical-backtest-口徑)重算。視窗與訊號追蹤相同，是該股在 `plan_date` 之後的前 20 根日線（`window_sessions`），不是全市場的前 20 個交易日；該股缺日線時視窗往後延。最多等到全市場在 `plan_date` 之後的第 40 個交易日（`MARKET_SESSION_LIMIT`）：到那時該股仍不足 20 根日線就結束為 `incomparable`。重算讀的日線截止於 min(目標日, 全市場第 40 個交易日)，所以同一份資料不論哪天執行、漏跑幾天，結果都相同。每根日線寫一列 `tracking_plan_sessions`（狀態、觸發、原始與還原 OHLC、是否停牌、模擬成交價、來源）。

| 狀態 | 進入條件 | 模擬結果 |
| --- | --- | --- |
| `pending` 待觸發 | 建立時；還沒成交且視窗未滿 | 無 |
| `triggered` 已觸發 | 突破價或回踩區首次觸及，模擬成交 | 無（未出場） |
| `target_hit` 達標 | 成交後首次觸及目標一 | 以目標一扣賣出滑價出場 |
| `invalidated` 失效 | 成交後首次觸及失效價（策略失效價，不是使用者停損） | 以失效價扣賣出滑價出場 |
| `expired` 到期 | 視窗的 20 根日線內沒有成交 | 無 |
| `closed` 期滿結算 | 已成交，視窗的 20 根日線內未達標也未失效 | 以第 20 根日線的收盤結算 |
| `incomparable` 無法比較 | 同一交易日失效價與目標一都觸及（順序不明）；或全市場在 `plan_date` 之後已有 40 個交易日、該股仍不足 20 根日線（長期停牌、下市、缺日線；`status_reason=insufficient_sessions`） | 無 |
| `cancelled` 已取消 | 使用者取消未結束的計畫 | 保留取消前的成交與明細 |

允許的轉換只有 `pending` → `triggered`／`target_hit`／`invalidated`／`incomparable`／`expired`／`closed`／`cancelled`，與 `triggered` → `target_hit`／`invalidated`／`incomparable`／`closed`／`cancelled`（`app.domain.PLAN_STATUS_TRANSITIONS`）；同一根日線成交又出場、或成交與期滿出現在同一次執行（第 20 根日線才成交，或漏跑幾天）時直接跳到結果。其餘狀態都是終態，之後不再重算。

- **模擬報酬**（`result_return`）：達標、失效、期滿結算才有，＝出場價÷成交價（兩者都換回計畫資料日的價格基準）− 1 − 30 bps；從第 1 根日線到出場（期滿結算為第 20 根）之間有停牌或其他不可比較的日線時（含成交前的停牌日），`result_comparable=false`、報酬為 null 並寫原因，狀態不變。
- **停牌**：停牌日（`is_suspended`、零量一字線、或官方停牌區間內缺日線）記一列 `suspended`，不推論觸發，狀態不變。
- **冪等**：同一目標日重跑寫出相同的列，值沒變就不改寫、`updated_at` 不動。重算出不允許的轉換（例如行情更正後原本的成交不成立）時保留原狀態與明細，`data_quality` 記 `transition_conflict`、`status_reason` 記 `transition_conflict:<原>-><新>`，不倒退。這種計畫仍是 `pending`／`triggered`，之後每次執行都照常重算：行情恢復到允許的轉換時就照新結果更新，`data_quality` 也改回；在那之前一直標 `transition_conflict`。`GET /tracking` 照常回傳這筆計畫與原狀態，並帶 `data_quality` 與 `status_reason`；行動頁在該張卡標示「行情有更正，狀態待核對」，不顯示重算出的新狀態。
- **取消**（`app.tracking_plans.cancel_plan`）：只能取消 `pending`／`triggered` 的計畫，記 `cancelled_at` 與 `status_reason=cancelled_while_<原狀態>`；已結束的計畫回 `plan_already_closed`。計畫與明細都不刪。
- **取消與每日更新同時寫入**：API 與 `plan_tracking` 從不同連線寫同一個計畫，兩邊的寫入都只在計畫仍是讀到時的狀態且未取消時才生效（`app.tracking_plans.claim_plan`，UPDATE 以 `status`、`cancelled_at IS NULL` 為條件）。每日更新讀完計畫後使用者才取消時，取消保留，這次更新不寫該計畫的狀態與明細；取消讀到的狀態已被每日更新改掉時，依新的狀態重新判斷（已結束就回 `plan_already_closed`，`triggered` 就記 `cancelled_while_triggered`）。SQLite 上條件 UPDATE 同時取得寫入鎖，另一方等到這筆交易結束（`busy_timeout`）才寫。

**API**（`/api` 之下，[`app.tracking_plan_view`](../../backend/app/tracking_plan_view.py)）：

| route | 說明 |
| --- | --- |
| `GET /tracking?status=open\|closed\|all&page&page_size` | 計畫清單（預設 `all`，`page_size` 1～100、預設 50）：進行中在前（依 `plan_date` 新到舊），已結束與已取消的依 `outcome_date`、否則 `last_session_date`、否則 `plan_date` 新到舊；同日依 `id` 新到舊。每筆含標的、來源、版本、價位（與候選相同的 `levels` 形狀，含 RR）、狀態、`open`、模擬成交與結果、`data_quality`、`created_at`（UTC，帶時區）；`summary` 為進行中與已結束的筆數，`meta` 為 `tracking_version`、視窗、滑價與成本假設、`simulated: true` |
| `POST /tracking` body `{signal_id, daily_candidate_id?}` | 建立，回 `{created, plan}`；同一訊號已有未取消的計畫時回原計畫與 `created: false`。拒絕時 `detail` 為規則碼：404 `signal_not_found`／`candidate_not_found`，422 `signal_not_conditional`／`invalid_levels`／`candidate_signal_mismatch`，409 `stale_signal` |
| `GET /tracking/plans/{plan_id}` | 單一計畫與逐日 `sessions`（日期、第幾日、狀態、原始與還原 OHLC、觸發、停牌、可比較、模擬成交價、來源）；404 `plan_not_found` |
| `POST /tracking/plans/{plan_id}/cancel` | 取消（冪等），回 `{plan}`；404 `plan_not_found`、409 `plan_already_closed`。409 `plan_changed`：條件寫入連續失敗、依重讀的狀態重判（每個進行中狀態最多一次）後仍沒寫進去，例如這次取消期間 daily 又改了計畫兩次，或舊資料留下 `cancelled_at` 有值、狀態卻仍是 `pending`／`triggered` 的列；計畫不改，重新整理後再取消 |

系統訊號的單筆追蹤留在 `GET /tracking/{signal_key}`。`/api/candidates` 的每筆候選另帶 `candidate_id`（`daily_candidates.id`）與 `open_plan_id`（該訊號未取消的計畫，沒有為 null），個股 API 的 `decision_summary.strategies[]` 也帶 `open_plan_id`。畫面文案見 [UI_COPY_SPEC §12](../UI_COPY_SPEC.md#12-追蹤計畫)。
