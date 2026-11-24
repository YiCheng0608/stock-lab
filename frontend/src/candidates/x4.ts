import type { X4Item, X4Response } from '../types'
import { formatDate } from './candidates'
import { signedPercent } from './mainstream'

// 盈餘殖利率前 20 (the X4 list, #1016/#1019): the fourth list beside the today list on the today page. A 前瞻觀察 list
// the user put on the page (decisions #1 7106346106, 7114503228): its head carries the warning badge
// 「前瞻觀察（未通過驗證）」 and nothing else of the research (no research code, numbers or t), and no price levels.
// Copy follows UI_COPY_SPEC §10 盈餘殖利率前 20.

// Not in the API (its config_json is not returned): the universe's 20-session mean volume line and the definition's
// period, both of app.x4_list / explore_research X4.
export const X4_MIN_AVERAGE_LOTS = 1000
export const X4_PERIOD_SESSIONS = 60

export const X4_WATCH_BADGE = '前瞻觀察（未通過驗證）'
export const X4_MISSING_TITLE = '尚無盈餘殖利率名單'
export const X4_ZERO_TITLE = '當日沒有股票進入母體'
export const X4_NONE_PASSED_TITLE = '當日沒有月營收年增與 EPS 年增都為正的股票'

const missingText = '—'

// 「12.34%」: eps_yield_raw × 100, two decimals, no sign and no tone (it is a yield, not a change).
export function x4YieldText(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return missingText
  const rounded = Number((value * 100).toFixed(2))
  return `${(rounded === 0 ? 0 : rounded).toFixed(2)}%`
}

// An EPS in 元, two decimals: 「3.21」, 「-0.50」.
function epsText(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return missingText
  const rounded = Number(value.toFixed(2))
  return (rounded === 0 ? 0 : rounded).toFixed(2)
}

// The row's three parts, joined by 「 · 」 on the page (each its own run, so a narrow row breaks between them):
// 「盈餘殖利率 12.34%」, 「營收年增（10 月）+25.10%」 and 「2026Q3 EPS 3.21（去年同季 2.10）」. A lead carries its own
// gap before the value: a space, or none after the month's full-width bracket.
export type X4LinePart = { lead: string; value: string; note?: string }

export function x4LineParts(item: Pick<X4Item, 'eps_yield_raw' | 'revenue_yoy' | 'revenue_month' | 'quarter_eps'>): X4LinePart[] {
  const month = item.revenue_month ? Number(item.revenue_month.slice(5, 7)) : NaN
  const quarter = item.quarter_eps
  return [
    { lead: '盈餘殖利率 ', value: x4YieldText(item.eps_yield_raw) },
    { lead: Number.isFinite(month) && month >= 1 ? `營收年增（${month} 月）` : '營收年增 ', value: signedPercent(item.revenue_yoy).text },
    quarter
      ? { lead: `${quarter.quarter} EPS `, value: epsText(quarter.eps), note: `（去年同季 ${epsText(quarter.year_before_eps)}）` }
      : { lead: 'EPS ', value: missingText },
  ]
}

export function x4LineText(item: Pick<X4Item, 'eps_yield_raw' | 'revenue_yoy' | 'revenue_month' | 'quarter_eps'>): string {
  return x4LineParts(item).map((part) => `${part.lead}${part.value}${part.note ?? ''}`).join(' · ')
}

// The head's definition line: the universe from the API, the volume line and the period from the constants.
export function x4Definition(data: Pick<X4Response, 'universe_count' | 'list_size'>): string {
  const universe = typeof data.universe_count === 'number' ? `母體 ${data.universe_count.toLocaleString()} 檔，` : ''
  return `月營收年增與單季 EPS 年增都為正的股票中，盈餘殖利率（最新一季 EPS × 4 ÷ 收盤）最高的 ${data.list_size} 檔（通過的不到 ${data.list_size} 檔時只放那幾檔）；${universe}20 日均量 ${X4_MIN_AVERAGE_LOTS.toLocaleString()} 張以上的上市櫃股票；以入選後 ${X4_PERIOD_SESSIONS} 個交易日為觀察期`
}

export type X4State =
  | { kind: 'list'; items: X4Item[] }
  | { kind: 'zero' | 'missing'; title: string; text: string }

// computed with rows → the list; missing (no list for the day); zero in two kinds: an empty universe (H2's sentence)
// and members none of which passes both filters (zero_reason, else by universe_count).
export function x4State(data: X4Response): X4State {
  if (data.status === 'computed' && data.items.length > 0) return { kind: 'list', items: data.items }
  if (data.status === 'missing') {
    const day = formatDate(data.trading_date)
    return { kind: 'missing', title: X4_MISSING_TITLE, text: day ? `${day} 尚未產生盈餘殖利率名單` : '尚未產生盈餘殖利率名單' }
  }
  const nonePassed = data.zero_reason === 'none_passed' || (data.zero_reason == null && typeof data.universe_count === 'number' && data.universe_count > 0)
  if (nonePassed) {
    const universe = typeof data.universe_count === 'number' ? `母體 ${data.universe_count.toLocaleString()} 檔中` : '母體中'
    return { kind: 'zero', title: X4_NONE_PASSED_TITLE, text: `${universe}沒有一檔同時通過兩個條件，當日不產生名單` }
  }
  return { kind: 'zero', title: X4_ZERO_TITLE, text: `沒有上市櫃股票的 20 日均量達 ${X4_MIN_AVERAGE_LOTS.toLocaleString()} 張，當日不產生名單` }
}
