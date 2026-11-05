import { productActionReasonLabel } from '../presentation'
import { signalDayConditionViews, type ConditionView } from '../stock/strategyBoard'
import type { CandidateItem } from '../types'
import { formatDate, formatPrice } from './candidates'

// A candidate's entry plan in plain words (#491; UI_COPY_SPEC §10.2; decisions 6647568372, review 6648572346).
// The sentence reads only the signal's own levels: the same numbers as the table columns and the ones tracking and
// the backtest simulate (from T+1 a touch of the level fills; stop and target are the signal's risk_levels). The only
// exit is the stop. The next-session levels of strategy_levels say whether tomorrow raises a new signal, not whether
// this one fails, so no price here comes from them. The folded 「完整條件」 lists the signal day's judgement of each
// condition. A missing number is a stated reason, never a blank or NaN. Pure, so the today list, the stock page and
// later pages (#493) render the same plan.

export type EntryType = 'breakout' | 'pullback'

export const ENTRY_TYPES: Record<EntryType, { label: string; term: string }> = {
  breakout: { label: '突破型', term: 'breakout_entry' },
  pullback: { label: '回踩型', term: 'pullback_entry' },
}

export const ENTRY_LEVELS_MISSING_TEXT = '成立價位不完整，暫不顯示進場價位；請看個股頁的策略總表。'
// On the stock page the board is right below, so the pointer to it is left out.
export const ENTRY_LEVELS_MISSING_STOCK_TEXT = '成立價位不完整，暫不顯示進場價位。'
export const ENTRY_UNKNOWN_TYPE_TEXT = '進場方式待核實：這個策略沒有對應的白話說明。'

export function entryConditionsTitle(tradingDate: string | null | undefined): string {
  const day = formatDate(tradingDate)
  return day ? `完整條件（${day} 判定）` : '完整條件'
}

// One run of a sentence; a price carries its DESIGN_SYSTEM §7 level class (entry, stop, target).
export type EntryPart = { text: string; className?: 'level-entry' | 'level-stop' | 'level-target' }

export type EntryPlanView = {
  // levels: the sentence has every price; reason: it says why there is none.
  kind: 'levels' | 'reason'
  type: EntryType | null
  parts: EntryPart[]
  // The signal day's judgement of each condition (eligibility and required inputs left out).
  conditions: ConditionView[]
}

type PlanItem = Pick<CandidateItem, 'levels' | 'entry_plan' | 'trading_date'>

const isPrice = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value > 0
const price = (value: number, className?: EntryPart['className']): EntryPart => ({ text: `${formatPrice(value)} 元`, className })
const range = (low: number, high: number, className?: EntryPart['className']): EntryPart => ({ text: `${formatPrice(low)}～${formatPrice(high)} 元`, className })

export function entryType(item: Pick<CandidateItem, 'levels'>): EntryType | null {
  const kind = item.levels?.entry_type
  return kind === 'breakout' || kind === 'pullback' ? kind : null
}

export function entryText(parts: readonly EntryPart[]): string {
  return parts.map((part) => part.text).join('')
}

// The signal's levels; a breakout's stop < entry < target (risk_levels), a pullback's stop < target.
function mainParts(type: EntryType, item: PlanItem): EntryPart[] | null {
  const { levels } = item
  const day = formatDate(item.trading_date)
  const stop = levels?.invalid_price
  const target = levels?.target_1
  if (!day || !isPrice(stop) || !isPrice(target)) return null
  const tail: EntryPart[] = [{ text: '；跌破 ' }, price(stop, 'level-stop'), { text: '停損，目標 ' }, price(target, 'level-target')]
  if (type === 'breakout') {
    const entry = levels.entry ?? levels.entry_zone?.low
    if (!isPrice(entry) || !(stop < entry && entry < target)) return null
    return [{ text: `${day} 收盤已突破 ` }, price(entry), { text: '。明天起在 ' }, price(entry, 'level-entry'), { text: '附近可進場' }, ...tail]
  }
  const { low, high } = levels.entry_zone ?? { low: null, high: null }
  if (!isPrice(low) || !isPrice(high) || low > high || !(stop < target)) return null
  return [{ text: `${day} 已拉回到支撐區。明天起在 ` }, range(low, high, 'level-entry'), { text: '之間可進場' }, ...tail]
}

export function entryPlanView(item: PlanItem, options: { onStockPage?: boolean } = {}): EntryPlanView {
  const type = entryType(item)
  const conditions = signalDayConditionViews(item.entry_plan?.conditions ?? [], productActionReasonLabel)
  if (!type) return { kind: 'reason', type, parts: [{ text: ENTRY_UNKNOWN_TYPE_TEXT }], conditions: [] }
  const parts = mainParts(type, item)
  if (!parts) return { kind: 'reason', type, parts: [{ text: options.onStockPage ? ENTRY_LEVELS_MISSING_STOCK_TEXT : ENTRY_LEVELS_MISSING_TEXT }], conditions }
  return { kind: 'levels', type, parts, conditions }
}
