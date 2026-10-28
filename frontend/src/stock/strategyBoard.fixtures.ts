import type { StrategyBoard, StrategyBoardRow, StrategyCondition } from '../types'

// Strategy board fixtures (#274), shaped like backend/app/strategy_board.py; numbers are illustrative.

const condition = (code: string, kind: string, satisfied: boolean | null, extra: Partial<StrategyCondition> = {}): StrategyCondition => ({
  code, kind, satisfied, actual: null, threshold: null, threshold_high: null, operator: null, reasons: [], next_session: null, ...extra,
})

const common = (complete = true) => [
  condition('eligibility', 'eligibility', true),
  condition('required_inputs', 'data', complete, complete ? {} : { reasons: ['margin_balance_change_ratio_5d_missing_or_non_finite'] }),
]

const confirmations = (satisfied: boolean | null = true) => [
  condition('group_relative_strength', 'confirmation', satisfied, { actual: satisfied == null ? null : 0.0213, threshold: 0, operator: 'gt' }),
  condition('institutional_flow', 'confirmation', satisfied, { actual: satisfied == null ? null : 0.012, threshold: -0.003, operator: 'gte' }),
  condition('margin_financing', 'confirmation', satisfied, { actual: satisfied == null ? null : -0.01, threshold: 0.05, operator: 'lte' }),
]

export function conditionalBreakout(): StrategyBoardRow {
  return {
    strategy: 'breakout_v1', label: '突破條件', version: '1.0.0', entry_type: 'breakout', status: 'conditional',
    signal_id: 11, signal_date: '2026-10-22', earliest_execution_date: '2026-10-23',
    levels: { kind: 'actionable', entry_type: 'breakout', trigger_price: 2400, reference_entry: null, entry_low: null, entry_high: null, invalid_price: 2364, target_1: 2458, target_2: 2508, risk_reward: 1.6 },
    levels_missing: false, unmet: [], missing: [], missing_labels: [],
    conditions: [
      ...common(),
      condition('breakout_price', 'price', true, { actual: 2405, threshold: 2395, operator: 'gt', next_session: { min_close: 2400, gap: -0.002 } }),
      condition('breakout_volume', 'volume', true, { actual: 1.42, threshold: 1.2, operator: 'gte', next_session: { min_volume: 16371500 } }),
      ...confirmations(),
    ],
  }
}

export function observationPullback(): StrategyBoardRow {
  return {
    strategy: 'pullback_v1', label: '回踩條件', version: '1.0.0', entry_type: 'pullback', status: 'observation',
    signal_id: 12, signal_date: '2026-10-22', earliest_execution_date: null,
    levels: {
      kind: 'observation', display_label: '條件未成立・觀察價位', availability: 'levels', next_session_date: '2026-10-23',
      trigger_price: null, zone_low: 2430, zone_high: 2535, min_volume: 16370600, max_volume: 32741200,
      reference_entry: 2430, entry_low: 2420.5, entry_high: 2450.5, invalid_price: 2399.64, target_1: 2478.57, target_2: 2521.07,
      risk_reward: 1.6, reachable_next_session: true, price_basis: 'score_date_raw_basis', missing_inputs: [], missing_labels: [],
    },
    levels_missing: false, unmet: ['pullback_support_zone', 'pullback_volume'], missing: [], missing_labels: [],
    conditions: [
      ...common(),
      condition('pullback_history', 'data', true, { actual: 60, threshold: 60, operator: 'gte', next_session: { bar_count: 61 } }),
      condition('pullback_trend', 'trend', true, { actual: 2350, threshold: 2210, operator: 'gt', next_session: { min_close: 1800 } }),
      condition('pullback_above_ma60', 'trend', true, { actual: 2575, threshold: 2210, operator: 'gte', next_session: { min_close: 2215 } }),
      condition('pullback_support_zone', 'price', false, { actual: 2575, threshold: 2279.5, threshold_high: 2397, operator: 'between', next_session: { min_close: 2430, max_close: 2535, position: 'above', gap: -0.0155 } }),
      condition('pullback_volume', 'volume', false, { actual: 1.55, threshold: 0.6, threshold_high: 1.2, operator: 'between', next_session: { min_volume: 16370600, max_volume: 32741200 } }),
      ...confirmations(),
    ],
  }
}

// A pullback whose trend cannot pass next session: both numbers, no price.
export function unreachablePullback(): StrategyBoardRow {
  const row = observationPullback()
  return {
    ...row,
    levels: {
      ...(row.levels as Extract<StrategyBoardRow['levels'], { kind: 'observation' }>),
      availability: 'trend_unreachable', zone_low: null, zone_high: null, min_volume: null, max_volume: null,
      reference_entry: null, entry_low: null, entry_high: null, invalid_price: null, target_1: null, target_2: null, risk_reward: null,
      reachable_next_session: null, missing_inputs: ['trend_cannot_pass_within_support_zone'],
      missing_labels: ['下一交易日收盤無法同時讓 20 日均線站上 60 日均線並落在支撐區'],
    },
    unmet: ['pullback_trend'],
    conditions: [
      ...common(),
      condition('pullback_trend', 'trend', false, { actual: 240, threshold: 262, operator: 'gt', next_session: { min_close: 322 } }),
      condition('pullback_support_zone', 'price', false, { actual: 236, threshold: 233, threshold_high: 245, operator: 'between', next_session: { min_close: 241, max_close: 253 } }),
    ],
  }
}

export function observationBreakout(): StrategyBoardRow {
  return {
    ...conditionalBreakout(), status: 'observation', earliest_execution_date: null,
    levels: {
      kind: 'observation', display_label: '條件未成立・觀察價位', availability: 'levels', next_session_date: '2026-10-23',
      trigger_price: 61.3, zone_low: null, zone_high: null, min_volume: 1234500, max_volume: null,
      reference_entry: 61.3, entry_low: null, entry_high: null, invalid_price: 60.07, target_1: 63.27, target_2: 64.99,
      risk_reward: 1.6, reachable_next_session: false, price_basis: 'score_date_raw_basis', missing_inputs: [], missing_labels: [],
    },
    unmet: ['breakout_price', 'breakout_volume'],
    conditions: [
      ...common(),
      condition('breakout_price', 'price', false, { actual: 55.2, threshold: 61.2, operator: 'gt', next_session: { min_close: 61.3, gap: 0.1105 } }),
      condition('breakout_volume', 'volume', false, { actual: 0.8, threshold: 1.2, operator: 'gte', next_session: { min_volume: 1234500 } }),
      ...confirmations(),
    ],
  }
}

export function incompleteRow(): StrategyBoardRow {
  return {
    ...conditionalBreakout(), status: 'data_incomplete', earliest_execution_date: null, levels: null,
    unmet: [], missing: ['margin_balance_change_ratio_5d_missing_or_non_finite'], missing_labels: ['近 5 日融資變化資料待補'],
    conditions: [...common(false), ...confirmations(null)],
  }
}

export function notApplicableRow(): StrategyBoardRow {
  return {
    ...conditionalBreakout(), status: 'not_applicable', earliest_execution_date: null, levels: null,
    unmet: [], missing: ['etf_category_excluded_from_actionable_signals:bond'], missing_labels: ['債券、槓桿或反向 ETF 不適用一般突破／回踩研究條件'],
    conditions: [],
  }
}

// An observation whose levels row was not written (an older date or a failed levels step).
export function missingLevelsRow(): StrategyBoardRow {
  return { ...observationPullback(), levels: null, levels_missing: true, unmet: [], conditions: [] }
}

export function board(strategies: StrategyBoardRow[], candidate: StrategyBoard['candidate'] = null): StrategyBoard {
  return { as_of: '2026-10-22', levels_version: 'strategy_levels_v1', candidate, strategies }
}
