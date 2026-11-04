# 研究回測表格：run 2210

- 副本：`C:\Users\YiCheng\t318\db\c1103\stock.db`
- run：`technical-backtest:v1:2025-11-04:2026-11-03:research:breakout_v2,pullback_v2,breakout_v2_ablate_breakout,breakout_v2_ablate_volume,breakout_v2_ablate_group,breakout_v2_ablate_institutional,breakout_v2_ablate_margin,pullback_v2_ablate_trend,pullback_v2_ablate_support,pullback_v2_ablate_volume,pullback_v2_ablate_group,pullback_v2_ablate_institutional,pullback_v2_ablate_margin`（success，2026-11-03 17:27:58.893351～2026-11-04 00:29:20.322555）
- 訊號日：2025-11-04～2026-11-03，241 個交易日
- 基準一：每個訊號日抽與策略同數的 `stock`／`ipo`，200 次，seed 318
- 產生命令：`python tools/research/research_report.py --db C:/Users/YiCheng/t318/db/c1103/stock.db --run-id 2210 --out C:/Users/YiCheng/t318/out/y1`

## 觸發數

| 策略 | 訊號列 | 條件成立（actionable） | 有成交 | data_incomplete |
| --- | ---: | ---: | ---: | ---: |
| `breakout_v2` | 546,143 | 4,241 | 4,077 | 201,923 |
| `pullback_v2` | 546,143 | 3,982 | 3,642 | 205,590 |
| `breakout_v2_ablate_breakout` | 546,143 | 14,256 | 10,741 | 201,900 |
| `breakout_v2_ablate_volume` | 546,143 | 6,349 | 6,114 | 201,920 |
| `breakout_v2_ablate_group` | 546,143 | 6,445 | 6,231 | 201,919 |
| `breakout_v2_ablate_institutional` | 546,143 | 5,151 | 4,931 | 201,921 |
| `breakout_v2_ablate_margin` | 546,143 | 8,244 | 7,953 | 201,921 |
| `pullback_v2_ablate_trend` | 546,143 | 7,184 | 6,463 | 205,582 |
| `pullback_v2_ablate_support` | 546,143 | 13,084 | 9,549 | 205,588 |
| `pullback_v2_ablate_volume` | 546,143 | 10,673 | 9,841 | 205,574 |
| `pullback_v2_ablate_group` | 546,143 | 12,239 | 11,368 | 205,571 |
| `pullback_v2_ablate_institutional` | 546,143 | 6,555 | 6,035 | 205,589 |
| `pullback_v2_ablate_margin` | 546,143 | 4,729 | 4,314 | 205,588 |

## 報酬分佈與基準（可比較的 settlement，扣 30 bps 成本）

| 策略 | T+N | n | 平均 | p10 | p25 | 中位數 | p75 | p90 | 基準一平均（95% 區間） | 策略平均在基準一的百分位 | TAIEX 同期平均 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| `breakout_v2` | T+5 | 3,836 | -0.99% | -5.72% | -3.88% | -1.66% | 1.91% | 4.40% | -0.38%（-0.58%～-0.21%） | 0% | 0.86% |
| `breakout_v2` | T+20 | 3,530 | -0.94% | -5.94% | -4.06% | -1.77% | 2.18% | 4.84% | 1.31%（0.84%～1.78%） | 0% | 4.99% |
| `pullback_v2` | T+5 | 3,253 | -0.59% | -4.20% | -2.33% | -0.83% | 1.02% | 3.43% | -0.39%（-0.60%～-0.19%） | 4% | 0.92% |
| `pullback_v2` | T+20 | 3,007 | -0.34% | -4.38% | -2.52% | -0.99% | 2.03% | 4.30% | 2.27%（1.76%～2.76%） | 0% | 5.65% |
| `breakout_v2_ablate_breakout` | T+5 | 8,624 | -1.11% | -5.63% | -4.02% | -2.04% | 1.67% | 4.71% | -0.22%（-0.35%～-0.10%） | 0% | 1.12% |
| `breakout_v2_ablate_breakout` | T+20 | 9,406 | -1.08% | -5.74% | -4.17% | -2.26% | 2.04% | 5.20% | 1.80%（1.49%～2.09%） | 0% | 5.42% |
| `breakout_v2_ablate_volume` | T+5 | 5,762 | -0.87% | -5.60% | -3.50% | -1.40% | 1.63% | 4.30% | -0.42%（-0.59%～-0.27%） | 0% | 0.84% |
| `breakout_v2_ablate_volume` | T+20 | 5,405 | -0.82% | -5.76% | -3.68% | -1.48% | 1.91% | 4.67% | 1.29%（0.92%～1.67%） | 0% | 4.99% |
| `breakout_v2_ablate_group` | T+5 | 5,898 | -0.90% | -5.20% | -3.22% | -1.41% | 1.38% | 3.63% | -0.45%（-0.62%～-0.30%） | 0% | 0.82% |
| `breakout_v2_ablate_group` | T+20 | 5,509 | -0.85% | -5.31% | -3.38% | -1.48% | 1.62% | 3.94% | 1.30%（0.91%～1.70%） | 0% | 5.29% |
| `breakout_v2_ablate_institutional` | T+5 | 4,603 | -1.04% | -5.75% | -3.96% | -1.76% | 1.87% | 4.44% | -0.34%（-0.54%～-0.15%） | 0% | 0.93% |
| `breakout_v2_ablate_institutional` | T+20 | 4,279 | -0.99% | -5.95% | -4.11% | -1.87% | 2.16% | 4.87% | 1.34%（0.91%～1.87%） | 0% | 5.05% |
| `breakout_v2_ablate_margin` | T+5 | 7,437 | -0.92% | -6.08% | -4.26% | -1.64% | 2.39% | 5.24% | -0.42%（-0.54%～-0.27%） | 0% | 0.81% |
| `breakout_v2_ablate_margin` | T+20 | 6,903 | -0.87% | -6.23% | -4.44% | -1.76% | 2.68% | 5.52% | 1.28%（0.94%～1.66%） | 0% | 5.05% |
| `pullback_v2_ablate_trend` | T+5 | 5,644 | -0.53% | -3.89% | -2.25% | -0.80% | 1.04% | 3.30% | -0.29%（-0.43%～-0.14%） | 0% | 1.17% |
| `pullback_v2_ablate_trend` | T+20 | 5,276 | -0.33% | -4.14% | -2.49% | -0.96% | 1.95% | 4.05% | 2.80%（2.45%～3.21%） | 0% | 6.62% |
| `pullback_v2_ablate_support` | T+5 | 6,992 | -0.06% | -4.02% | -2.12% | -0.48% | 1.51% | 4.46% | -0.64%（-0.77%～-0.49%） | 100% | 0.36% |
| `pullback_v2_ablate_support` | T+20 | 8,003 | 0.68% | -3.97% | -2.05% | -0.09% | 2.65% | 6.33% | 1.36%（1.07%～1.67%） | 0% | 4.47% |
| `pullback_v2_ablate_volume` | T+5 | 8,821 | -0.57% | -4.60% | -2.55% | -0.92% | 1.07% | 4.01% | -0.47%（-0.60%～-0.33%） | 7% | 0.82% |
| `pullback_v2_ablate_volume` | T+20 | 8,180 | -0.36% | -4.91% | -2.83% | -1.12% | 2.05% | 5.10% | 2.23%（1.92%～2.52%） | 0% | 5.68% |
| `pullback_v2_ablate_group` | T+5 | 10,300 | -0.50% | -3.77% | -2.18% | -0.85% | 1.08% | 3.42% | -0.43%（-0.55%～-0.32%） | 11% | 0.76% |
| `pullback_v2_ablate_group` | T+20 | 10,049 | -0.40% | -4.07% | -2.43% | -1.06% | 1.70% | 4.02% | 1.12%（0.88%～1.38%） | 0% | 4.18% |
| `pullback_v2_ablate_institutional` | T+5 | 5,437 | -0.58% | -4.63% | -2.51% | -0.85% | 1.20% | 3.82% | -0.34%（-0.49%～-0.16%） | 0% | 0.93% |
| `pullback_v2_ablate_institutional` | T+20 | 5,075 | -0.34% | -5.06% | -2.80% | -1.05% | 2.12% | 5.02% | 2.14%（1.77%～2.54%） | 0% | 5.45% |
| `pullback_v2_ablate_margin` | T+5 | 3,857 | -0.54% | -4.11% | -2.23% | -0.75% | 1.05% | 3.37% | -0.40%（-0.60%～-0.21%） | 9% | 0.91% |
| `pullback_v2_ablate_margin` | T+20 | 3,601 | -0.31% | -4.31% | -2.44% | -0.93% | 2.01% | 4.25% | 2.29%（1.89%～2.69%） | 0% | 5.65% |

## 出場方式與不可比較的原因

| 策略 | T+N | 出場狀態（可比較） | 不可比較 |
| --- | --- | --- | --- |
| `breakout_v2` | T+5 | active 379、invalidated 1,785、target_1_hit 1,672、target_1_hit_below_zero 290 | filled_after_horizon 109、not_executed 164、suspended_or_ambiguous 92、too_few_sessions 40 |
| `breakout_v2` | T+20 | active 12、invalidated 1,789、target_1_hit 1,729、target_1_hit_below_zero 264 | not_executed 164、suspended_or_ambiguous 83、too_few_sessions 464 |
| `pullback_v2` | T+5 | active 963、invalidated 1,575、target_1_hit 715、target_1_hit_below_zero 33 | filled_after_horizon 201、not_executed 340、suspended_or_ambiguous 14、too_few_sessions 174 |
| `pullback_v2` | T+20 | active 95、invalidated 1,795、target_1_hit 1,117、target_1_hit_below_zero 35 | not_executed 340、suspended_or_ambiguous 12、too_few_sessions 623 |
| `breakout_v2_ablate_breakout` | T+5 | active 1,052、invalidated 4,553、target_1_hit 3,019、target_1_hit_below_zero 379 | filled_after_horizon 1,739、not_executed 3,515、suspended_or_ambiguous 265、too_few_sessions 113 |
| `breakout_v2_ablate_breakout` | T+20 | active 125、invalidated 5,557、target_1_hit 3,724、target_1_hit_below_zero 391 | not_executed 3,515、suspended_or_ambiguous 227、too_few_sessions 1,108 |
| `breakout_v2_ablate_volume` | T+5 | active 601、invalidated 2,575、target_1_hit 2,586、target_1_hit_below_zero 437 | filled_after_horizon 166、not_executed 235、suspended_or_ambiguous 129、too_few_sessions 57 |
| `breakout_v2_ablate_volume` | T+20 | active 25、invalidated 2,646、target_1_hit 2,734、target_1_hit_below_zero 408 | not_executed 235、suspended_or_ambiguous 120、too_few_sessions 589 |
| `breakout_v2_ablate_group` | T+5 | active 576、invalidated 2,726、target_1_hit 2,596、target_1_hit_below_zero 444 | filled_after_horizon 160、not_executed 214、suspended_or_ambiguous 133、too_few_sessions 40 |
| `breakout_v2_ablate_group` | T+20 | active 17、invalidated 2,765、target_1_hit 2,727、target_1_hit_below_zero 412 | not_executed 214、suspended_or_ambiguous 124、too_few_sessions 598 |
| `breakout_v2_ablate_institutional` | T+5 | active 441、invalidated 2,173、target_1_hit 1,989、target_1_hit_below_zero 348 | filled_after_horizon 135、not_executed 220、suspended_or_ambiguous 146、too_few_sessions 47 |
| `breakout_v2_ablate_institutional` | T+20 | active 15、invalidated 2,196、target_1_hit 2,068、target_1_hit_below_zero 319 | not_executed 220、suspended_or_ambiguous 133、too_few_sessions 519 |
| `breakout_v2_ablate_margin` | T+5 | active 584、invalidated 3,300、target_1_hit 3,553、target_1_hit_below_zero 713 | filled_after_horizon 171、not_executed 291、suspended_or_ambiguous 261、too_few_sessions 84 |
| `breakout_v2_ablate_margin` | T+20 | active 17、invalidated 3,305、target_1_hit 3,581、target_1_hit_below_zero 651 | not_executed 291、suspended_or_ambiguous 226、too_few_sessions 824 |
| `pullback_v2_ablate_trend` | T+5 | active 1,719、invalidated 2,550、target_1_hit 1,375、target_1_hit_below_zero 97 | filled_after_horizon 381、not_executed 721、suspended_or_ambiguous 24、too_few_sessions 414 |
| `pullback_v2_ablate_trend` | T+20 | active 186、invalidated 2,997、target_1_hit 2,093、target_1_hit_below_zero 120 | not_executed 721、suspended_or_ambiguous 22、too_few_sessions 1,165 |
| `pullback_v2_ablate_support` | T+5 | active 1,482、invalidated 4,481、target_1_hit 1,029、target_1_hit_below_zero 55 | filled_after_horizon 2,236、not_executed 3,535、suspended_or_ambiguous 28、too_few_sessions 293 |
| `pullback_v2_ablate_support` | T+20 | active 149、invalidated 6,190、target_1_hit 1,664、target_1_hit_below_zero 68 | not_executed 3,535、suspended_or_ambiguous 25、too_few_sessions 1,521 |
| `pullback_v2_ablate_volume` | T+5 | active 2,635、invalidated 4,265、target_1_hit 1,921、target_1_hit_below_zero 80 | filled_after_horizon 524、not_executed 832、suspended_or_ambiguous 39、too_few_sessions 457 |
| `pullback_v2_ablate_volume` | T+20 | active 255、invalidated 4,982、target_1_hit 2,943、target_1_hit_below_zero 92 | not_executed 832、suspended_or_ambiguous 34、too_few_sessions 1,627 |
| `pullback_v2_ablate_group` | T+5 | active 2,715、invalidated 5,061、target_1_hit 2,524、target_1_hit_below_zero 116 | filled_after_horizon 831、not_executed 871、suspended_or_ambiguous 56、too_few_sessions 181 |
| `pullback_v2_ablate_group` | T+20 | active 233、invalidated 6,206、target_1_hit 3,610、target_1_hit_below_zero 145 | not_executed 871、suspended_or_ambiguous 49、too_few_sessions 1,270 |
| `pullback_v2_ablate_institutional` | T+5 | active 1,674、invalidated 2,517、target_1_hit 1,246、target_1_hit_below_zero 58 | filled_after_horizon 328、not_executed 520、suspended_or_ambiguous 16、too_few_sessions 254 |
| `pullback_v2_ablate_institutional` | T+20 | active 179、invalidated 2,965、target_1_hit 1,931、target_1_hit_below_zero 61 | not_executed 520、suspended_or_ambiguous 13、too_few_sessions 947 |
| `pullback_v2_ablate_margin` | T+5 | active 1,134、invalidated 1,853、target_1_hit 870、target_1_hit_below_zero 43 | filled_after_horizon 242、not_executed 415、suspended_or_ambiguous 15、too_few_sessions 200 |
| `pullback_v2_ablate_margin` | T+20 | active 112、invalidated 2,145、target_1_hit 1,344、target_1_hit_below_zero 46 | not_executed 415、suspended_or_ambiguous 13、too_few_sessions 700 |

## 價位距離（actionable 訊號）

| 策略 | 失效價距進場（中位數） | 目標一 R（中位數） | 目標二 R（中位數） |
| --- | ---: | ---: | ---: |
| `pullback_v2_ablate_group` | 1.87% | 1.60 | 3.00 |
| `pullback_v2_ablate_support` | 2.90% | 1.60 | 3.00 |
| `breakout_v2_ablate_group` | 2.28% | 1.60 | 3.00 |
| `breakout_v2_ablate_institutional` | 2.85% | 1.60 | 3.00 |
| `breakout_v2_ablate_volume` | 2.55% | 1.60 | 3.00 |
| `breakout_v2` | 2.81% | 1.60 | 3.00 |
| `breakout_v2_ablate_breakout` | 2.88% | 1.60 | 3.00 |
| `breakout_v2_ablate_margin` | 3.30% | 1.60 | 3.00 |
| `pullback_v2_ablate_volume` | 2.17% | 1.60 | 3.00 |
| `pullback_v2_ablate_institutional` | 2.14% | 1.60 | 3.00 |
| `pullback_v2` | 2.01% | 1.60 | 3.00 |
| `pullback_v2_ablate_trend` | 1.95% | 1.60 | 3.00 |
| `pullback_v2_ablate_margin` | 1.96% | 1.60 | 3.00 |

## 沒有條件成立訊號的交易日（AC-5）

### `breakout_v2`：0／241 天

- 每日條件成立數：中位數 15、p10 7、p90 32
- 月份：{}
- 只移除一個條件就有訊號的天數：{}
- 這些天的訊號狀態：{}
- 未通過原因（訊號列數，前 12）：
- 全期 546,143 列的狀態：{"observation": 339970, "data_incomplete": 201923, "invalidated": 2072, "target_1_hit": 1890, "incomparable": 93, "expired": 113, "active": 22, "invalid_levels": 9, "conditional": 51}
- 全期未通過原因（訊號列數，前 12）：`close_not_above_prior_20_day_high` 347,789、`volume_ratio_below_1_20` 273,542、`group_relative_strength_not_positive` 248,497、`institutional_flow_materially_adverse` 173,800、`group_excess_return_20d_missing_or_non_finite` 119,129、`missing:effective_group_score_missing_or_under_minimum_members` 116,876、`margin_financing_increase_abnormal` 68,653、`institutional_flow_to_turnover_ratio_5d_missing_or_non_finite` 48,841、`margin_balance_change_ratio_5d_missing_or_non_finite` 37,303、`missing:etf_category_excluded_from_actionable_signals:bond` 25,166、`missing:etf_category_excluded_from_actionable_signals:inverse` 9,652、`prior_20_highs_missing_or_invalid` 2,724

### `pullback_v2`：29／241 天

- 每日條件成立數：中位數 9、p10 0、p90 46
- 月份：{"2026-01": 7, "2026-02": 1, "2026-03": 1, "2026-04": 8, "2026-05": 10, "2026-06": 1, "2026-08": 1}
- 只移除一個條件就有訊號的天數：{"support": 29, "volume": 25, "group": 29, "institutional": 14, "trend": 2, "margin": 4}
- 這些天的訊號狀態：{"observation": 39141, "data_incomplete": 26577}
- 未通過原因（訊號列數，前 12）：`group_relative_strength_not_positive` 33,876、`pullback_volume_ratio_outside_range` 24,285、`close_outside_ma20_support_zone` 23,648、`ma20_not_above_ma60` 19,444、`institutional_flow_materially_adverse` 18,598、`close_below_ma60` 17,922、`missing:effective_group_score_missing_or_under_minimum_members` 16,559、`group_excess_return_20d_missing_or_non_finite` 16,359、`margin_financing_increase_abnormal` 9,819、`institutional_flow_to_turnover_ratio_5d_missing_or_non_finite` 5,006、`margin_balance_change_ratio_5d_missing_or_non_finite` 4,428、`missing:etf_category_excluded_from_actionable_signals:bond` 3,029
- 全期 546,143 列的狀態：{"observation": 336560, "data_incomplete": 205590, "target_1_hit": 1214, "invalidated": 2263, "expired": 233, "active": 151, "invalid_levels": 11, "incomparable": 14, "conditional": 107}
- 全期未通過原因（訊號列數，前 12）：`group_relative_strength_not_positive` 245,827、`pullback_volume_ratio_outside_range` 218,707、`close_outside_ma20_support_zone` 184,455、`close_below_ma60` 181,145、`ma20_not_above_ma60` 177,328、`institutional_flow_materially_adverse` 172,216、`missing:effective_group_score_missing_or_under_minimum_members` 116,876、`group_excess_return_20d_missing_or_non_finite` 115,485、`margin_financing_increase_abnormal` 67,858、`institutional_flow_to_turnover_ratio_5d_missing_or_non_finite` 45,725、`margin_balance_change_ratio_5d_missing_or_non_finite` 36,812、`missing:etf_category_excluded_from_actionable_signals:bond` 25,166

- 兩個策略都沒有：0 天 
