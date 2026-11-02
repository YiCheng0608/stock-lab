import type { TrackingMeta, TrackingPlan, TrackingPlanDetail, TrackingPlansResponse } from '../types'

// Shapes of GET /api/tracking and /api/tracking/plans/{id} (#253), one plan per status.

export const meta = (): TrackingMeta => ({ tracking_version: 'plan_tracking_v1', window_sessions: 20, slippage_bps: 5, round_trip_cost_bps: 30, simulated: true })

export function plan(overrides: Partial<TrackingPlan> = {}): TrackingPlan {
  return {
    id: 1,
    instrument: { id: 11, exchange: 'TWSE', symbol: '2377', name: '微星' },
    source_kind: 'candidate',
    signal_id: 101,
    daily_candidate_id: 201,
    strategy: 'breakout_v1',
    versions: { strategy_version_id: 3, formula_version: 'institutional-flow/v1-shares-per-twd-turnover', score_version: 'candidate_score_v1', tracking_version: 'plan_tracking_v1' },
    plan_date: '2026-10-16',
    levels: {
      entry_type: 'breakout', entry: 161.5, entry_zone: { low: 161.5, high: 161.5 }, invalid_price: 157.82,
      target_1: 167.39, target_2: 172.54, risk_reward: 1.6, earliest_execution_date: '2026-10-19',
    },
    window_sessions: 20,
    status: 'pending',
    status_reason: 'awaiting_entry',
    open: true,
    sessions_observed: 0,
    last_session_date: null,
    execution_date: null,
    execution_price: null,
    outcome_date: null,
    outcome_price: null,
    result_return: null,
    result_comparable: null,
    incomparable_reason: null,
    data_quality: 'complete',
    simulated: true,
    // 2026/10/16 23:30 in Taipei is 15:30 UTC: the Taipei date is shown.
    created_at: '2026-10-16T15:30:00+00:00',
    updated_at: '2026-10-16T15:30:00+00:00',
    cancelled_at: null,
    ...overrides,
  }
}

export const triggered = () => plan({
  id: 2, status: 'triggered', status_reason: 'entry_filled', sessions_observed: 3, last_session_date: '2026-10-21',
  execution_date: '2026-10-20', execution_price: 161.58,
})

export const targetHit = () => plan({
  id: 3, source_kind: 'stock', daily_candidate_id: null, versions: { ...plan().versions, score_version: null },
  instrument: { id: 12, exchange: 'TPEx', symbol: '6488', name: '環球晶' }, strategy: 'pullback_v1',
  levels: { entry_type: 'pullback', entry: 13.2, entry_zone: { low: 13.05, high: 13.35 }, invalid_price: 12.6, target_1: 14.5, target_2: null, risk_reward: 2.17, earliest_execution_date: '2026-10-02' },
  plan_date: '2026-10-01', status: 'target_hit', status_reason: 'target_1_touched', open: false, sessions_observed: 4, last_session_date: '2026-10-07',
  execution_date: '2026-10-02', execution_price: 13.21, outcome_date: '2026-10-07', outcome_price: 14.49, result_return: 0.0939, result_comparable: true,
})

export const invalidated = () => plan({
  id: 4, status: 'invalidated', status_reason: 'invalid_price_touched', open: false, sessions_observed: 2, last_session_date: '2026-10-20',
  execution_date: '2026-10-19', execution_price: 161.58, outcome_date: '2026-10-20', outcome_price: 157.74, result_return: -0.0268, result_comparable: true,
})

export const expired = () => plan({
  id: 5, status: 'expired', status_reason: 'window_ended_without_entry', open: false, sessions_observed: 20, last_session_date: '2026-10-14', plan_date: '2026-09-15',
})

export const suspendedClose = () => plan({
  id: 6, status: 'closed', status_reason: 'window_ended_after_entry', open: false, sessions_observed: 20, last_session_date: '2026-10-14', plan_date: '2026-09-15',
  execution_date: '2026-09-16', execution_price: 161.58, outcome_date: '2026-10-14', outcome_price: 162, result_return: null, result_comparable: false,
  incomparable_reason: 'suspended or otherwise non-comparable session in horizon', data_quality: 'incomplete',
})

export const ambiguous = () => plan({
  id: 7, status: 'incomparable', status_reason: 'same_session_stop_and_target', open: false, sessions_observed: 2, last_session_date: '2026-10-20',
  execution_date: '2026-10-19', execution_price: 161.58, outcome_date: '2026-10-20', result_comparable: false,
  incomparable_reason: 'same-session stop and target both touched; order is unknowable', data_quality: 'incomplete',
})

export const cancelled = () => plan({
  id: 8, status: 'cancelled', status_reason: 'cancelled_while_pending', open: false, sessions_observed: 1, last_session_date: '2026-10-19',
  cancelled_at: '2026-10-19T10:00:00+00:00',
})

export const conflict = () => plan({
  id: 9, status: 'triggered', status_reason: 'transition_conflict:triggered->pending', data_quality: 'transition_conflict',
  sessions_observed: 1, last_session_date: '2026-10-19', execution_date: '2026-10-19', execution_price: 161.58,
})

export function listResponse(items: TrackingPlan[], total = items.length): TrackingPlansResponse {
  return {
    items,
    pagination: { page: 1, page_size: 20, total, total_pages: Math.ceil(total / 20), has_previous: false, has_next: total > 20 },
    summary: { open: items.filter((item) => item.open).length, closed: items.filter((item) => !item.open).length },
    meta: meta(),
  }
}

export function detailResponse(): TrackingPlanDetail {
  const bar = (open: number, high: number, low: number, close: number) => ({ open, high, low, close, adj_close: close })
  const session = (no: number, day: string, status: string, ohlc: ReturnType<typeof bar>, triggers: Partial<Record<'entry_trigger' | 'target_trigger' | 'invalid_trigger', boolean>> = {}) => ({
    session_date: day, session_no: no, status, reason: null, ohlc, adjusted_ohlc: {}, entry_trigger: false, target_trigger: false, invalid_trigger: false,
    suspended: status === 'suspended', comparable: status !== 'suspended', execution_price: status === 'active' && triggers.entry_trigger ? 13.21 : null,
    source: 'tpex_daily_quotes', data_time: null, ...triggers,
  })
  return {
    plan: targetHit(),
    sessions: [
      session(1, '2026-10-02', 'active', bar(13.2, 13.4, 13.1, 13.3), { entry_trigger: true }),
      session(2, '2026-10-03', 'active', bar(13.3, 13.9, 13.2, 13.8)),
      session(3, '2026-10-06', 'active', bar(13.8, 14.1, 13.6, 14.0)),
      session(4, '2026-10-07', 'target_1_hit', bar(13.9, 14.6, 13.8, 14.4), { target_trigger: true }),
    ],
    meta: meta(),
  }
}
