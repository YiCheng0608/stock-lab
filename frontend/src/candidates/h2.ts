import type { H2Item, H2Response } from '../types'
import { formatDate } from './candidates'
import { signedPercent } from './mainstream'

// 接近年高前 20 (the H2 list, #881/#882): the third list beside the today list on the today page. The frozen research
// definition explore_research_v2_X2; the page shows each stock's distance to its one-year high, the close and the
// sparkline, and no price levels, research results or t (decision #1 7044998169). Copy follows UI_COPY_SPEC §10
// 接近年高前 20 (decision #882 7048604437).

// Not in the API (its config_json is not returned): the universe's 20-session mean volume line and the definition's
// period, both of app.h2_list / explore_research X2.
export const H2_MIN_AVERAGE_LOTS = 1000
export const H2_PERIOD_SESSIONS = 60

export const H2_MISSING_TITLE = '尚無接近年高名單'
export const H2_ZERO_TITLE = '當日沒有股票進入母體'

// 「距一年高點 -3.21%」: high_gap_240 × 100, two decimals; not red or green (it is not a change). null → 「—」, no reason:
// the API does not say why (fewer than 240 bars, a missing high).
export function h2GapText(item: Pick<H2Item, 'high_gap_240'>): string {
  return signedPercent(item.high_gap_240).text
}

export const H2_GAP_LEAD = '距一年高點'

// The head's definition line: W and the universe from the API, the volume line and the period from the constants.
export function h2Definition(data: Pick<H2Response, 'window' | 'universe_count'>): string {
  const universe = typeof data.universe_count === 'number' ? `母體 ${data.universe_count.toLocaleString()} 檔，` : ''
  return `收盤最接近一年高點（近 ${data.window} 個交易日最高價，價格還原除權息）的 20 檔；${universe}20 日均量 ${H2_MIN_AVERAGE_LOTS.toLocaleString()} 張以上的上市櫃股票；以入選後 ${H2_PERIOD_SESSIONS} 個交易日為觀察期`
}

export type H2State =
  | { kind: 'list'; items: H2Item[] }
  | { kind: 'zero' | 'missing'; title: string; text: string }

// computed with rows → the list; missing (no list for the day) and zero (an empty universe) as 主流族群前 20 writes them.
export function h2State(data: H2Response): H2State {
  if (data.status === 'computed' && data.items.length > 0) return { kind: 'list', items: data.items }
  if (data.status === 'missing') {
    const day = formatDate(data.trading_date)
    return { kind: 'missing', title: H2_MISSING_TITLE, text: day ? `${day} 尚未產生接近年高名單` : '尚未產生接近年高名單' }
  }
  return { kind: 'zero', title: H2_ZERO_TITLE, text: `沒有上市櫃股票的 20 日均量達 ${H2_MIN_AVERAGE_LOTS.toLocaleString()} 張，當日不產生名單` }
}
