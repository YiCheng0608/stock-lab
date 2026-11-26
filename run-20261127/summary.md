# 每月檢討 2026-11（monthly_review 第 2 版，#1062）

- cutoff：2026-11-26（副本裡 2026-11 的最後一個交易日；**月份還沒結束**）
- 副本：最新交易日 2026-11-26，alembic `0038_futures_night_bars`，檔案時間 2026-11-26T22:20:08.049648+00:00
- 上個月：沒有（沒有 `--previous`）
- 子入口：13 個，成功 10、失敗 3（candidate_pool_score、premarket_errors、premarket_score_report）
- 耗時 261 秒，峰值記憶體 0.62 GB
- 重現：`python tools/research/monthly_review.py --db /db/stock.db --month 2026-11 --out /out/run-20261127 --min-free-gb 0`
- 第 2 版改了什麼：#1069：加候選池的 16 個來源（任一期間「輸給基準」進變差、「通過」進變強，只當紀錄）；新增「候選池的對答案」「早盤 AI 判錯清單」兩段，判錯清單不進清單

## 變差

| 項目 | 內容 | 動作 |
| --- | --- | --- |
| `candidate_pool_score` | candidate_pool_score 失敗，未判 | 看該段的失敗原因 |
| `feature_evidence` | 特徵與條件降級：沒有上個月可比（沒有 --previous），不列 | — |

- 已進產品策略用到、不在 `feature_evidence.FEATURES` 的鍵（沒得比）：X4-product `eps_yield_raw`

## 變強

| 項目 | 內容 | 動作 |
| --- | --- | --- |
| `candidate_pool_score` | candidate_pool_score 失敗，未判 | 看該段的失敗原因 |
| `feature_evidence` | 特徵升級：沒有上個月可比（沒有 --previous），不列 | — |

- 「用過」從登記的定義自動查：`explore_ledger.json` 每一筆的工具的 `HYPOTHESES[代號]`、`portfolio_research.HYPOTHESES` 與 `forward_watch.WATCHES` 的定義裡出現特徵鍵（整字）就算；只用中文標籤描述、沒寫鍵名的假設比對不到，可能被誤列成沒用過，統籌看清單時刪掉

## H1

- 對加權指數超額（只列出，至今全部）：日均 0.621%，t 0.47，8 日
- 判定：**樣本不足（累積 8／250 日）**：下面的數字不是判定，滿 250 日才判定一次
- 原始輸出：`H1/`（整個 `--out` 推 `pr-assets/699` 的 `run-<YYYYMMDD>/`）

## X4

- X4 前瞻觀察的前瞻紀錄（forward_watch 第 1 版，#868）
- 對加權指數超額（只列出）：日均 -2.144%，t -0.78，4 日
- 對母體超額：日均 0.017%，t 1.01，累積 4 日
- 判定：**樣本不足（累積 4／60 日）**：數字不是判定，滿 60 日才判定；前瞻觀察的對象：只當紀錄，不判下架，判到「輸給基準」也只記錄；不改成「通過」；放上頁面另由使用者決定
- 第一個有名單的訊號日：2026-11-20
- 原始輸出：`X4/`（`pr-assets/699` 的 `run-<YYYYMMDD>/X4/`）

## H2

- H2 通過驗證的前瞻紀錄（forward_watch 第 1 版，#868）
- 對加權指數超額（只列出）：日均 -2.223%，t -0.80，4 日
- 對母體超額：日均 -0.062%，t -0.92，累積 4 日
- 判定：**樣本不足（累積 4／60 日）**：數字不是判定，滿 60 日才判定；通過驗證、待使用者決定進不進產品的策略：只當紀錄，不判下架；判到「輸給基準」時由統籌在 #1 的進產品提案補一則（是事實，不是下架提案），其餘判定只記錄
- 第一個有名單的訊號日：2026-11-20
- 原始輸出：`H2/`（`pr-assets/699` 的 `run-<YYYYMMDD>/H2/`）

## H2-product

- H2 已進產品的前瞻紀錄（forward_watch 第 1 版，#868）
- 對加權指數超額（只列出）：日均 -2.248%，t -0.57，3 日
- 對母體超額：日均 -0.024%，t -0.47，累積 3 日
- 判定：**樣本不足（累積 3／60 日）**：數字不是判定，滿 60 日才判定；已進產品的策略：滿 60 日起每月判一次，判到「輸給基準」由統籌在 #1 提案下架；其餘判定只列出
- 第一個有名單的訊號日：2026-11-23
- 原始輸出：`H2-product/`（`pr-assets/699` 的 `run-<YYYYMMDD>/H2-product/`）

## F2

- F2 前瞻觀察的前瞻紀錄（forward_watch 第 1 版，#868）
- 對加權指數超額（只列出）：日均 -2.231%，t -0.56，3 日
- 對母體超額：日均 -0.007%，t -0.11，累積 3 日
- 判定：**樣本不足（累積 3／60 日）**：數字不是判定，滿 60 日才判定；前瞻觀察的對象：只當紀錄，不判下架，判到「輸給基準」也只記錄；不改成「通過」；放上頁面另由使用者決定
- 第一個有名單的訊號日：沒有名單
- 原始輸出：`F2/`（`pr-assets/699` 的 `run-<YYYYMMDD>/F2/`）

## P2

- P2 前瞻觀察的前瞻紀錄（forward_watch 第 1 版，#868）
- 對加權指數超額（只列出）：日均 —，t —，0 日
- 對母體超額：日均 —，t —，累積 0 日
- 判定：**樣本不足（起日後還沒有事件日）**：累積 0／60 日，下一個事件日 2027-03-31（法定期限；當天或之後的第一個週一～週五交易日），數字不是判定，滿 60 日才判定；前瞻觀察的對象：只當紀錄，不判下架，判到「輸給基準」也只記錄；不改成「通過」；放上頁面另由使用者決定
- 第一個有名單的訊號日：沒有名單
- 原始輸出：`P2/`（`pr-assets/699` 的 `run-<YYYYMMDD>/P2/`）

## A1

- A1 前瞻觀察的前瞻紀錄（forward_watch 第 1 版，#868）
- 對加權指數超額（只列出）：日均 —，t —，0 日
- 對母體超額：日均 —，t —，累積 0 日
- 判定：**樣本不足（起日後還沒有事件日）**：累積 0／60 日，下一個事件日 2027-03-31（法定期限；當天或之後的第一個週一～週五交易日），數字不是判定，滿 60 日才判定；前瞻觀察的對象：只當紀錄，不判下架，判到「輸給基準」也只記錄；不改成「通過」；放上頁面另由使用者決定
- 第一個有名單的訊號日：沒有名單
- 原始輸出：`A1/`（`pr-assets/699` 的 `run-<YYYYMMDD>/A1/`）

## X4-product

- X4 已進產品的前瞻紀錄（forward_watch 第 1 版，#868）
- 對加權指數超額（只列出）：日均 1.200%，t 0.34，2 日
- 對母體超額：日均 0.024%，t 1.75，累積 2 日
- 判定：**樣本不足（累積 2／60 日）**：數字不是判定，滿 60 日才判定；已進產品的策略：滿 60 日起每月判一次，判到「輸給基準」由統籌在 #1 提案下架；其餘判定只列出
- 第一個有名單的訊號日：2026-11-24
- 原始輸出：`X4-product/`（`pr-assets/699` 的 `run-<YYYYMMDD>/X4-product/`）

## 候選成績單

- 候選：2026-10-19～2026-11-26，332 檔次；判定：全部候選的每日超額，`forward_judge`，滿 60 日才判

| 期間 | 候選 | 未到期 | 可比較 | 日數 | 每日超額日均 | t | 判定 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| T+5 | 332 | 10 | 321 | 21 | 1.969% | 1.01 | 樣本不足 |
| T+20 | 332 | 192 | 136 | 7 | 9.971% | — | 樣本不足 |

- 原始輸出：`candidate_scorecard/`

## 特徵證據

- feature_evidence 第 2 版，2024-09-30～2026-11-26

| 類 | 鍵 | T+5 | T+20 |
| --- | --- | --- | --- |
| 條件 | `breakout_price` | 沒有證據 | 沒有證據 |
| 條件 | `breakout_volume` | 沒有證據 | 沒有證據 |
| 條件 | `breakout_rule` | 沒有證據 | 沒有證據 |
| 條件 | `pullback_setup` | 沒有證據 | 沒有證據 |
| 條件 | `institutional_ok` | 沒有證據 | 沒有證據 |
| 條件 | `margin_ok` | 沒有證據 | 沒有證據 |
| 條件 | `breakout_confirmed` | 沒有證據 | 沒有證據 |
| 條件 | `pullback_confirmed` | 沒有證據 | 沒有證據 |
| 特徵 | `momentum_20` | 沒有證據 | 沒有證據 |
| 特徵 | `momentum_60` | 沒有證據 | 沒有證據 |
| 特徵 | `momentum_120` | 沒有證據 | 沒有證據 |
| 特徵 | `high_gap_60` | 沒有證據 | 沒有證據 |
| 特徵 | `high_gap_240` | 沒有證據 | 沒有證據 |
| 特徵 | `volume_ratio` | 沒有證據 | 沒有證據 |
| 特徵 | `institutional_flow_5` | 沒有證據 | 沒有證據 |
| 特徵 | `institutional_flow_20` | 沒有證據 | 沒有證據 |
| 特徵 | `foreign_flow_5` | 沒有證據 | 沒有證據 |
| 特徵 | `trust_flow_5` | 方向一致但不顯著 | 沒有證據 |
| 特徵 | `trust_buy_days_5` | 有證據 | 沒有證據 |
| 特徵 | `margin_change_5` | 沒有證據 | 沒有證據 |
| 特徵 | `short_change_5` | 沒有證據 | 沒有證據 |
| 特徵 | `borrowed_sell_surge` | 無法判定 | 無法判定 |
| 特徵 | `day_trade_ratio` | 無法判定 | 無法判定 |
| 特徵 | `revenue_yoy` | 沒有證據 | 沒有證據 |
| 特徵 | `revenue_yoy_change` | 沒有證據 | 沒有證據 |
| 特徵 | `revenue_high_12` | 方向一致但不顯著 | 沒有證據 |
| 特徵 | `eps_yield` | 有證據 | 沒有證據 |
| 特徵 | `eps_growth_yield` | 沒有證據 | 沒有證據 |

### 判定有變（和上個月比）

沒有上個月可比（沒有 --previous），不列

- 原始輸出：`feature_evidence/`

## 候選池的對答案

- **失敗**：副本沒有 `candidate_pool_items` 表（alembic `0038_futures_night_bars`）：建它的 migration 還沒部署到正式 DB
- 命令：`python tools/research/candidate_pool_score.py --db /db/stock.db --out /out/run-20261127/candidate_pool_score --end 2026-11-26 --min-free-gb 0`

## 早盤 AI 判錯清單

- **失敗**：副本沒有 `premarket_ai_readings` 表（alembic `0038_futures_night_bars`）：建它的 migration 還沒部署到正式 DB
- 命令：`python tools/research/premarket_errors.py --db /db/stock.db --month 2026-11 --out /out/run-20261127/premarket_errors --min-free-gb 0`

## 早盤 AI 判讀月報

- **失敗**：副本沒有 `premarket_ai_readings` 表（alembic `0038_futures_night_bars`）：建它的 migration 還沒部署到正式 DB
- 命令：`premarket_score_report.render(2026-11)`

