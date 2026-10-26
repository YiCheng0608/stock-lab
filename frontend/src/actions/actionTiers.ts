import { formatDay } from '../dates'
import { productActionReasonLabel } from '../presentation'
import { nearLine } from '../stock/strategyBoard'
import type { ActionNearness, ActionSummary, ActionTierNumber, ActionTierSummary, ActionView, ActionsResponse } from '../types'
import { formatFixed, formatTableNumber } from '../units'

// Action centre tiers (action_tier_v1, #278): the API orders and counts; this module only words and groups.
// Copy follows UI_COPY_SPEC §5; the list follows DESIGN_SYSTEM §5 行動列表.

export const ACTIONS_PAGE_LIMIT = 20
// First rows of a tier that has rows but none on the first page (tools/verify/page_checks.py ACTION_TIER_PREVIEW).
export const ACTION_TIER_PREVIEW = 5

export const ACTION_VIEWS: ReadonlyArray<{ id: ActionView; label: string }> = [
  { id: 'focus', label: '重點' },
  { id: 'with_observation', label: '含其他觀察' },
  { id: 'all', label: '全部' },
]
export const DEFAULT_ACTION_VIEW: ActionView = 'focus'

export const SEARCH_NOTE = '搜尋不受篩選限制，結果依級別列出。'
export const EMPTY_TEXT = '目前沒有符合篩選的標的。'
export const LEVELS_NOTE = '單位：價格為各標的報價幣別的元。空白表示沒有成立的價位。'
export const RESEARCH_LINK = '策略總表 →'
// Tier 3 shows no level; its levels are on the stock's strategy board (DESIGN_SYSTEM §7 接近成立).
export const NEAR_RESEARCH_LINK = '價位見策略總表 →'
export const CONDITIONS_PENDING_TEXT = '條件明細尚未產生'

export const ACTION_STATE_LABELS: Record<string, string> = {
  conditional_entry: '條件進場',
  wait_breakout: '等待突破',
  wait_pullback: '等待回踩',
  hold_observe: '持有觀察',
  reduce_exit: '庫存風險：減碼／退場條件',
  data_insufficient: '策略判斷資料待補',
  no_condition: '暫無研究條件',
  manual_review: '需人工判讀',
}

const INCOMPLETE_STATES = ['data_insufficient', 'data_incomplete', 'insufficient_data']

export function actionStateLabel(action: ActionSummary): string {
  if (INCOMPLETE_STATES.includes(action.action_state)) return '策略判斷資料待補'
  return action.display_action || ACTION_STATE_LABELS[action.action_state] || '待判定'
}

export function stockResearchPath(exchange: string, symbol: string): string {
  return `/stocks/${encodeURIComponent(exchange)}/${encodeURIComponent(symbol)}?tab=research`
}

export const actionKey = (action: ActionSummary) => `${action.instrument.exchange}:${action.instrument.symbol}`

const count = (value: number) => value.toLocaleString()

export function viewChipLabel(view: ActionView, summary: ActionTierSummary): string {
  const label = ACTION_VIEWS.find((item) => item.id === view)?.label ?? view
  return `${label} ${count(summary.views[view] ?? 0)}`
}

export function etfLabel(summary: ActionTierSummary): string {
  return `含 ETF（${count(summary.etf)}）`
}

// 預設隱藏：… — each hidden row once, ETFs first (summary.hidden); zero parts are left out.
export function hiddenSentence(summary: ActionTierSummary): string | null {
  const parts = [
    ['ETF', summary.hidden.etf],
    ['其他觀察', summary.hidden.observation],
    ['策略判斷資料待補', summary.hidden.data_insufficient],
  ] as const
  const listed = parts.filter(([, value]) => value > 0).map(([label, value]) => `${label} ${count(value)} 檔`)
  if (!listed.length) return null
  const isDefault = summary.view === DEFAULT_ACTION_VIEW && !summary.include_etf
  return `${isDefault ? '預設隱藏' : '目前隱藏'}：${listed.join('、')}；自選標的一律顯示。隱藏不刪資料，切換上方篩選即可看到。`
}

export const shownText = (loaded: number, shown: number) => `顯示 ${count(loaded)}／${count(shown)} 檔`
export const moreText = (remaining: number) => `顯示更多（還有 ${count(remaining)} 檔）`

// Tiers listed in the current filter whose rows are not on the first page: each loads its first rows on its own.
export function previewTiers(data: ActionsResponse): number[] {
  return data.summary.tiers.filter((tier) => tier.shown > 0 && !data.items.some((item) => item.tier === tier.tier)).map((tier) => tier.tier)
}

export type TierSection = { tier: ActionTierNumber; key: string; label: string; shown: number; items: ActionSummary[]; candidateListSize: number | null }

// One section per tier with rows in the current filter: the first page's rows of that tier, then the tier pages
// loaded by 顯示更多 (which start from the tier's top, so repeated rows are dropped).
export function tierSections(data: ActionsResponse, tierPages: Partial<Record<number, ActionsResponse[]>> = {}): TierSection[] {
  return data.summary.tiers.flatMap((tier) => {
    if (tier.shown <= 0) return []
    const items = new Map<string, ActionSummary>()
    for (const item of data.items) if (item.tier === tier.tier) items.set(actionKey(item), item)
    for (const page of tierPages[tier.tier] ?? []) for (const item of page.items) if (!items.has(actionKey(item))) items.set(actionKey(item), item)
    return [{ tier: tier.tier, key: tier.key, label: tier.label, shown: tier.shown, items: [...items.values()], candidateListSize: data.summary.candidate_list_size ?? null }]
  })
}

export type ActionClose = { close: string | null; change: string | null; tone: 'positive' | 'negative' | '' }

// The same validity rules as the today cards: a missing or invalid market read shows no close (UI_COPY_SPEC §5).
// A column across stocks keeps two decimals and the change is a percent, as in the candidate list (DESIGN_SYSTEM §3).
export function actionClose(action: ActionSummary): ActionClose {
  const read = action.market_read
  const explicitRead = read !== undefined
  const price = typeof action.current_price === 'number' && Number.isFinite(action.current_price) && action.current_price > 0 ? action.current_price : null
  const validRead = !explicitRead || (read != null && !Array.isArray(read) && read.status === 'known' && Array.isArray(read.invalid_fields) && read.invalid_fields.length === 0)
  if (!validRead || price === null) return { close: null, change: null, tone: '' }
  const pct = action.price_change_pct
  if (typeof action.price_change !== 'number' || !Number.isFinite(action.price_change) || typeof pct !== 'number' || !Number.isFinite(pct * 100)) {
    return { close: formatFixed(price, 2), change: '漲跌待核實', tone: '' }
  }
  // The tone follows the shown percent, so +0.00% is not coloured.
  const shown = Number((pct * 100).toFixed(2))
  return { close: formatFixed(price, 2), change: `${formatFixed(pct * 100, 2, true)}%`, tone: shown > 0 ? 'positive' : shown < 0 ? 'negative' : '' }
}

export type ActionLevels = { entry: string; stop: string; target: string }

// Rule levels of a passed condition, and a holding's stop (the user's stop or the rule's invalid price); two decimals.
export function actionLevels(action: ActionSummary): ActionLevels | null {
  const price = (value: number | null | undefined) => formatTableNumber(value, 2)
  if (action.action_state === 'conditional_entry') {
    const zone = action.entry_low != null || action.entry_high != null
    const entry = action.trigger_kind === 'pullback' || (zone && action.trigger_price == null)
      ? (zone ? `${price(action.entry_low)}～${price(action.entry_high)}` : '')
      : price(action.trigger_price)
    return { entry, stop: price(action.invalid_price), target: price(action.target_1) }
  }
  if (['hold_observe', 'reduce_exit'].includes(action.action_state) && action.stop_price != null) {
    return { entry: '', stop: price(action.stop_price), target: '' }
  }
  return null
}

// The 說明 column of tiers 4 and 5: the summary's main reason, or what data is missing.
export function actionNote(action: ActionSummary): string | null {
  if (INCOMPLETE_STATES.includes(action.action_state)) return productActionReasonLabel(action.data_gap ?? '研究資料尚未完整，尚不能計算進場、失效與目標價。')
  return action.primary_reason?.label ?? null
}

// Tier 4 without a strategy_levels row: its conditions are not known yet (UI_COPY_SPEC §6).
export const conditionsPending = (action: ActionSummary, tier: number) => tier === 4 && action.nearness == null && !INCOMPLETE_STATES.includes(action.action_state)

// Tier 2: why a passed condition is not in today's candidates (UI_COPY_SPEC §6).
export function conditionalNote(action: ActionSummary, candidateListSize: number | null): string {
  if (action.instrument.instrument_type === 'etf') return '條件成立，ETF 不列入候選評分'
  return candidateListSize ? `條件成立，未進今日候選前 ${candidateListSize}` : '條件成立，未進今日候選'
}

export type NearCopy = { title: string; lines: string[]; met: string | null }

// Tier 3: the badge, one 「差：」 line per unmet condition and the met short names; no level (DESIGN_SYSTEM §7).
export function nearCopy(nearness: ActionNearness | null | undefined): NearCopy | null {
  if (!nearness?.near) return null
  return {
    title: `接近${nearness.label}`,
    lines: nearness.unmet.map(nearLine),
    met: nearness.met_short_labels.length ? `${nearness.met_short_labels.join('、')}已達成` : null,
  }
}

export const actionDataDay = (action: ActionSummary) => formatDay(action.data_cutoff ?? action.price_as_of) ?? '待核實'
