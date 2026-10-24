import type { BadgeTone } from '../components/ui'
import type { TrackingMeta, TrackingPlan, TrackingPlanSession } from '../types'
import { formatDate, formatPrice } from '../candidates/candidates'

// User tracking plans (plan_tracking_v1, #253): labels, formatting and copy for the actions page and the
// "加入追蹤" buttons. Copy follows UI_COPY_SPEC §11; status badges follow DESIGN_SYSTEM §7.

export const TRACKING_TITLE = '追蹤計畫'
export const HISTORY_TITLE = '追蹤回看'
export const EMPTY_OPEN_TEXT = '尚未建立追蹤計畫。可從今日候選或個股研究條件加入。'
export const EMPTY_CLOSED_TEXT = '尚無已結束的計畫。'
export const CONFLICT_TEXT = '行情有更正，狀態待核對'
export const NO_CONDITION_TEXT = '目前沒有成立的研究條件，無法建立追蹤計畫'
export const ADD_LABEL = '加入追蹤'
export const TRACKED_LABEL = '已在追蹤'
export const PLAN_PAGE_SIZE = 20

const DEFAULT_META: TrackingMeta = { tracking_version: 'plan_tracking_v1', window_sessions: 20, slippage_bps: 5, round_trip_cost_bps: 30, simulated: true }

export function trackingNote(meta: TrackingMeta | undefined): string {
  const { slippage_bps: slippage, round_trip_cost_bps: cost } = meta ?? DEFAULT_META
  return `計畫價位來自建立當日的研究條件；成交與結果是依日線規則的模擬（買賣各 ${slippage} bps 滑價、來回 ${cost} bps 成本假設），不是實際成交，也不統計勝率。實際持股請看「我的庫存」。`
}

export const PLAN_STATUS: Record<string, { label: string; tone: BadgeTone }> = {
  pending: { label: '待觸發', tone: 'primary' },
  triggered: { label: '已觸發', tone: 'warning' },
  target_hit: { label: '達標', tone: 'success' },
  invalidated: { label: '失效', tone: 'error' },
  incomparable: { label: '無法比較', tone: 'warning' },
  expired: { label: '到期', tone: 'default' },
  closed: { label: '期滿結算', tone: 'default' },
  cancelled: { label: '已取消', tone: 'default' },
}

export function planStatus(status: string): { label: string; tone: BadgeTone } {
  return PLAN_STATUS[status] ?? { label: '狀態待核實', tone: 'warning' }
}

// The stored status stays shown; a recomputation the plan may not move to only adds this note (V1_SPEC).
export function hasTransitionConflict(plan: Pick<TrackingPlan, 'data_quality'>): boolean {
  return plan.data_quality === 'transition_conflict'
}

const SESSION_STATUS: Record<string, string> = {
  not_triggered: '未觸發',
  active: '已模擬成交',
  target_1_hit: '達標',
  invalidated: '失效',
  ambiguous: '順序不明',
  suspended: '停牌',
}

export function sessionStatusLabel(status: string): string {
  return SESSION_STATUS[status] ?? '狀態待核實'
}

export function sessionTriggers(session: Pick<TrackingPlanSession, 'entry_trigger' | 'target_trigger' | 'invalid_trigger'>): string {
  const hits = [session.entry_trigger && '進場', session.target_trigger && '目標', session.invalid_trigger && '失效'].filter(Boolean)
  return hits.length ? hits.join('、') : '—'
}

export function planSourceLabel(kind: string): string {
  return kind === 'candidate' ? '今日候選' : kind === 'stock' ? '個股研究條件' : '來源待核實'
}

const isFiniteNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)

// Signed percent with two decimals: 0.0123 -> "+1.23%".
export function formatSignedReturn(value: number | null | undefined): string {
  if (!isFiniteNumber(value)) return '—'
  const percent = (value * 100).toFixed(2)
  return (value > 0 ? '+' : '') + (percent === '-0.00' ? '0.00' : percent) + '%'
}

// UTC instant -> Asia/Taipei YYYY/MM/DD (UI_COPY_SPEC §1).
export function formatTaipeiDate(instant: string | null | undefined): string | null {
  if (!instant) return null
  const time = new Date(instant)
  if (Number.isNaN(time.getTime())) return null
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(time)
  const part = (type: string) => parts.find((item) => item.type === type)?.value
  return `${part('year')}/${part('month')}/${part('day')}`
}

export function planDateLine(plan: Pick<TrackingPlan, 'plan_date' | 'created_at'>): string {
  return `計畫資料日 ${formatDate(plan.plan_date) ?? '待核實'} · 建立 ${formatTaipeiDate(plan.created_at) ?? '待核實'}`
}

export function planProgressLine(plan: Pick<TrackingPlan, 'sessions_observed' | 'window_sessions'>): string {
  return `第 ${plan.sessions_observed}／${plan.window_sessions} 個交易日`
}

export function planExecutionLine(plan: Pick<TrackingPlan, 'execution_date' | 'execution_price'>): string {
  return plan.execution_date ? `模擬成交 ${formatDate(plan.execution_date)} ${formatPrice(plan.execution_price)}` : '尚未模擬成交'
}

export function planExitLine(plan: Pick<TrackingPlan, 'outcome_date' | 'outcome_price'>): string | null {
  return plan.outcome_date && isFiniteNumber(plan.outcome_price) ? `模擬出場 ${formatDate(plan.outcome_date)} ${formatPrice(plan.outcome_price)}` : null
}

function incomparableText(plan: Pick<TrackingPlan, 'status' | 'status_reason' | 'incomparable_reason' | 'execution_date'>): string {
  if (plan.status === 'cancelled') return '已取消'
  if (plan.status === 'expired' || !plan.execution_date) return '視窗內未模擬成交'
  if (plan.status_reason === 'same_session_stop_and_target') return '同一交易日失效價與目標一都觸及，先後順序不明'
  if (plan.status_reason === 'insufficient_sessions') return '40 個交易日內該股不足 20 根日線'
  if (plan.incomparable_reason?.includes('suspended')) return '期間有停牌或不可比較的日線'
  return '原因待核實'
}

// Ended plans only: the simulated return, or why it cannot be compared. Never a win rate.
export function planResultLine(plan: TrackingPlan): string | null {
  if (plan.open) return null
  if (plan.result_comparable === true && isFiniteNumber(plan.result_return)) return `模擬報酬 ${formatSignedReturn(plan.result_return)}`
  return `模擬報酬：無法比較（${incomparableText(plan)}）`
}

export function planVersionText(plan: Pick<TrackingPlan, 'versions' | 'source_kind'>): string {
  const { versions } = plan
  return [
    `來源 ${planSourceLabel(plan.source_kind)}`,
    `策略版本 ${versions.strategy_version_id ?? '未記錄'}`,
    `公式 ${versions.formula_version ?? '未記錄'}`,
    versions.score_version ? `評分 ${versions.score_version}` : null,
    `追蹤規則 ${versions.tracking_version}`,
  ].filter(Boolean).join(' · ')
}

export function planAnchor(planId: number): string {
  return `plan-${planId}`
}

export function planLink(planId: number): string {
  return `/actions#${planAnchor(planId)}`
}

// "加入追蹤" refusals (API detail codes, V1_SPEC 使用者追蹤計畫) in everyday words.
const ADD_ERRORS: Record<string, string> = {
  stale_signal: '這個研究條件的資料日已過，請用最新資料日的條件建立',
  signal_not_conditional: '這個研究條件目前不成立，無法建立追蹤計畫',
  invalid_levels: '研究條件的價位不完整或不合理，無法建立追蹤計畫',
  candidate_signal_mismatch: '候選與研究條件不一致，請重新整理頁面',
  candidate_not_found: '找不到這筆候選，請重新整理頁面',
  signal_not_found: '找不到這個研究條件，請重新整理頁面',
}

const CANCEL_ERRORS: Record<string, string> = {
  plan_already_closed: '計畫已結束，無法取消',
  plan_not_found: '找不到這個計畫，請重新整理頁面',
  plan_changed: '計畫狀態剛更新，請重新整理後再試',
}

function errorCode(error: unknown): string | null {
  return error && typeof error === 'object' && 'code' in error && typeof error.code === 'string' ? error.code : null
}

export function addPlanErrorText(error: unknown): string {
  return ADD_ERRORS[errorCode(error) ?? ''] ?? '加入失敗，請稍後再試'
}

export function cancelPlanErrorText(error: unknown): string {
  return CANCEL_ERRORS[errorCode(error) ?? ''] ?? '取消失敗，請稍後再試'
}
