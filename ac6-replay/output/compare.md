# AC-6 比對結果

## signals

| 日期 | 基準列數 | 重播列數 | 逐列相符 | 欄位不同 | 只在基準 | 只在重播 |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-10-19 | 4628 | 4628 | 4 | 4624 | 0 | 0 |
| 2026-10-20 | 4632 | 4634 | 6 | 4626 | 0 | 2 |
| 2026-10-21 | 4638 | 4638 | 50 | 4588 | 0 | 0 |
| 2026-10-22 | 4622 | 4622 | 4620 | 2 | 0 | 0 |

| 不同的欄位 | 列數（四日合計） | 各日 | 最大數值差 | 例 |
| --- | --- | --- | --- | --- |
| `rule_evidence_json.execution.earliest` | 13838 | 4624/4626/4588/0 |  | ('analysis-TPEx-00411A-2026-10-19-breakout_v1-1.0.0',): `None` → `2026-10-20` |
| `earliest_execution_date` | 13838 | 4624/4626/4588/0 |  | ('analysis-TPEx-00411A-2026-10-19-breakout_v1-1.0.0',): `None` → `2026-10-20` |
| `rule_evidence_json.inputs.bar_count_60d` | 4 | 0/0/2/2 | 1 | ('analysis-TWSE-6467-2026-10-21-breakout_v1-1.0.0',): `1` → `2` |
| `rule_evidence_json.inputs.prior_20_volumes` | 4 | 0/0/2/2 |  | ('analysis-TWSE-6467-2026-10-21-breakout_v1-1.0.0',): `[]` → `[3100797]` |
| `rule_evidence_json.inputs.prior_20_highs` | 4 | 0/0/2/2 |  | ('analysis-TWSE-6467-2026-10-21-breakout_v1-1.0.0',): `[]` → `[219.5]` |
| `rule_evidence_json.group_member_return_lookup.group_id` | 2 | 2/0/0/0 |  | ('analysis-TPEx-7806-2026-10-19-breakout_v1-1.0.0',): `official-industry-206d1b19286222a7` → `official-new-listings-dc1567ade14ff3b0` |
| `rationale` | 2 | 2/0/0/0 |  | ('analysis-TPEx-7806-2026-10-19-breakout_v1-1.0.0',): `breakout=data_incomplete:prior_20_highs_missing_or_invalid,prior_20_volumes_missing_or_invalid,group_excess_return_20d_missing_or_non_finite,institutional_flow_to_turnover_ratio_5d_missing_or_non_finite,margin_balance_change_ratio_5d_missing_or_non_finite; pullback=data_incomplete:history_under_60_bars; group=official-industry-206d1b19286222a7; missing=ipo_history_under_20_bars,prior_20_highs_missing_or_invalid,prior_20_volumes_missing_or_invalid,group_excess_return_20d_missing_or_non_finite,institutional_flow_to_turnover_ratio_5d_missing_or_non_finite,margin_balance_change_ratio_5d_missing_or_non_finite` → `breakout=data_incomplete:prior_20_highs_missing_or_invalid,prior_20_volumes_missing_or_invalid,group_excess_return_20d_missing_or_non_finite,institutional_flow_to_turnover_ratio_5d_missing_or_non_finite,margin_balance_change_ratio_5d_missing_or_non_finite; pullback=data_incomplete:history_under_60_bars; group=official-new-listings-dc1567ade14ff3b0; missing=ipo_history_under_20_bars,prior_20_highs_missing_or_invalid,prior_20_volumes_missing_or_invalid,group_excess_return_20d_missing_or_non_finite,institutional_flow_to_turnover_ratio_5d_missing_or_non_finite,margin_balance_change_ratio_5d_missing_or_non_finite` |

## technical_features

| 日期 | 基準列數 | 重播列數 | 逐列相符 | 欄位不同 | 只在基準 | 只在重播 |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-10-19 | 2315 | 2315 | 2315 | 0 | 0 | 0 |
| 2026-10-20 | 2317 | 2318 | 2317 | 0 | 0 | 1 |
| 2026-10-21 | 2320 | 2320 | 2319 | 1 | 0 | 0 |
| 2026-10-22 | 2312 | 2312 | 2311 | 1 | 0 | 0 |

| 不同的欄位 | 列數（四日合計） | 各日 | 最大數值差 | 例 |
| --- | --- | --- | --- | --- |
| `features_json.high_20d` | 2 | 0/0/1/1 | 18 | ('TWSE:6467', '2026-10-21'): `201.5` → `219.5` |
| `features_json.bar_count` | 2 | 0/0/1/1 | 1 | ('TWSE:6467', '2026-10-21'): `1` → `2` |
| `features_json.bar_count_60d` | 2 | 0/0/1/1 | 1 | ('TWSE:6467', '2026-10-21'): `1` → `2` |
| `features_json.low_20d` | 2 | 0/0/1/1 | 19 | ('TWSE:6467', '2026-10-21'): `187.0` → `168.0` |
| `features_json.atr14` | 2 | 0/0/1/1 | 18.5 | ('TWSE:6467', '2026-10-21'): `14.5` → `33.0` |
| `features_json.return_1d` | 1 | 0/0/1/0 |  | ('TWSE:6467', '2026-10-21'): `None` → `-0.065` |

## group_daily_scores

| 日期 | 基準列數 | 重播列數 | 逐列相符 | 欄位不同 | 只在基準 | 只在重播 |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-10-19 | 41 | 53 | 10 | 31 | 0 | 12 |
| 2026-10-20 | 53 | 53 | 28 | 25 | 0 | 0 |
| 2026-10-21 | 53 | 53 | 36 | 17 | 0 | 0 |
| 2026-10-22 | 53 | 53 | 53 | 0 | 0 | 0 |

| 不同的欄位 | 列數（四日合計） | 各日 | 最大數值差 | 例 |
| --- | --- | --- | --- | --- |
| `rank` | 50 | 24/16/10/0 | 6 | ('official-industry-0435ae1f54a7615d', '2026-10-19'): `19` → `22` |
| `score` | 31 | 16/11/4/0 | 8.34 | ('official-industry-17661791d0d765c5', '2026-10-19'): `37.47` → `40.8` |
| `catalyst` | 31 | 16/11/4/0 | 0.833 | ('official-industry-17661791d0d765c5', '2026-10-19'): `0.6666666666666666` → `1.0` |
| `details_json.raw_values.catalyst` | 31 | 16/11/4/0 | 0.833 | ('official-industry-17661791d0d765c5', '2026-10-19'): `0.6666666666666666` → `1.0` |
| `details_json.normalized_values.catalyst` | 31 | 16/11/4/0 | 0.833 | ('official-industry-17661791d0d765c5', '2026-10-19'): `0.6666666666666666` → `1.0` |
| `details_json.member_count` | 21 | 7/7/7/0 | 19 | ('official-etf-8b17ba811dd3d9f0', '2026-10-19'): `52` → `41` |
| `details_json.institutional_flow_coverage.member_count` | 21 | 7/7/7/0 | 19 | ('official-etf-8b17ba811dd3d9f0', '2026-10-19'): `52` → `41` |
| `data_quality` | 11 | 7/3/1/0 |  | ('official-industry-35423f5368e5eefd', '2026-10-19'): `partial` → `complete` |

