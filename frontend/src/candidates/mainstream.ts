import type { MainstreamItem, MainstreamResponse } from '../types'
import { formatDate } from './candidates'

// 主流族群前 20 (mainstream_v1, #768/#769): the second list beside the today list on the today page. A screen, not a
// strategy: each row has its groups, its W-session strength, the close and the sparkline, and no price levels (no entry
// sentence, price ladder, RR or total score; decision #1 6891614350). Copy follows UI_COPY_SPEC §10 主流族群前 20.

// The page's three lists (#882 adds 接近年高前 20, the H2 list; h2.ts).
export type TodayListKind = 'today' | 'mainstream' | 'h2'

export const LIST_PARAM = 'list'
export const MAINSTREAM_LIST = 'mainstream'
export const H2_LIST = 'h2'
// The today list row the page opens on (「今日名單 #n」 on a mainstream row links to it): the stock's symbol.
export const PICK_PARAM = 'pick'

export const TODAY_LIST_TITLE = '今日名單'
export const MAINSTREAM_TITLE = '主流族群前 20'
export const H2_TITLE = '接近年高前 20'
export const TODAY_LISTS: ReadonlyArray<{ id: TodayListKind; label: string }> = [
  { id: 'today', label: TODAY_LIST_TITLE },
  { id: 'mainstream', label: MAINSTREAM_TITLE },
  { id: 'h2', label: H2_TITLE },
]

// The list the page shows: 今日名單 unless the address says ?list=mainstream or ?list=h2 (a reload stays on it); an
// unknown value shows 今日名單 (#882 decision 7048604437).
export function todayListKind(search: URLSearchParams): TodayListKind {
  const value = search.get(LIST_PARAM)
  return value === MAINSTREAM_LIST ? 'mainstream' : value === H2_LIST ? 'h2' : 'today'
}

// The address of another list: ?list=mainstream or ?list=h2, or nothing for the today list (its default). A pick is dropped,
// so switching back by the tab starts the today list from its default row.
export function todayListSearch(search: URLSearchParams, kind: TodayListKind): URLSearchParams {
  const next = new URLSearchParams(search)
  next.delete(PICK_PARAM)
  if (kind === 'mainstream') next.set(LIST_PARAM, MAINSTREAM_LIST)
  else if (kind === 'h2') next.set(LIST_PARAM, H2_LIST)
  else next.delete(LIST_PARAM)
  return next
}

// 「今日名單 #n」 opens the today list on that stock: the page, the today list and the stock's row.
export function todayListPickPath(item: Pick<MainstreamItem, 'instrument'>): string {
  return `/?${PICK_PARAM}=${encodeURIComponent(item.instrument.symbol)}`
}

// The API reads today_list on the mainstream list's own date, while the page's today list is the latest. They differ
// while the daily has written the today list but not yet this one, or when this step failed and the previous list
// stays (review 6893655832). The mark links to the today list only when both are of the same date; otherwise it is
// plain text with the mainstream list's date, 「2026/11/13 今日名單 #9」, so it never opens another day's row.
export type TodayListMarkView = { text: string; link: string | null }

export function todayListMark(
  item: Pick<MainstreamItem, 'today_list' | 'instrument'>,
  mainstreamDate: string | null | undefined,
  todayDate: string | null | undefined,
): TodayListMarkView | null {
  if (!item.today_list) return null
  const text = `${TODAY_LIST_TITLE} #${item.today_list.rank}`
  if (mainstreamDate && todayDate && mainstreamDate.slice(0, 10) === todayDate.slice(0, 10)) return { text, link: todayListPickPath(item) }
  const day = formatDate(mainstreamDate)
  return { text: day ? `${day} ${text}` : text, link: null }
}

// A ratio as a signed percent, two decimals: 「+12.34%」, 「-0.50%」, 「0.00%」 (flat is not coloured).
export function signedPercent(ratio: number | null | undefined): { text: string; tone: 'up' | 'down' | 'flat' | null } {
  if (typeof ratio !== 'number' || !Number.isFinite(ratio)) return { text: '—', tone: null }
  const percent = ratio * 100
  const rounded = Number(percent.toFixed(2))
  const text = `${rounded > 0 ? '+' : ''}${(rounded === 0 ? 0 : percent).toFixed(2)}%`
  return { text, tone: rounded > 0 ? 'up' : rounded < 0 ? 'down' : 'flat' }
}

// The row's strength: 「近 240 日 +45.67%」 and 「（較加權 +12.34%）」, W from the API.
export function mainstreamReturnParts(item: Pick<MainstreamItem, 'return_w' | 'excess_w'>, window: number) {
  return { lead: `近 ${window} 日`, value: signedPercent(item.return_w), excess: signedPercent(item.excess_w) }
}

export function mainstreamReturnText(item: Pick<MainstreamItem, 'return_w' | 'excess_w'>, window: number): string {
  const parts = mainstreamReturnParts(item, window)
  return `${parts.lead} ${parts.value.text}（較加權 ${parts.excess.text}）`
}

// The chosen groups the stock is in, in their rank order, joined by 「、」.
export function mainstreamGroupsText(item: Pick<MainstreamItem, 'groups'>): string {
  return item.groups.length ? item.groups.map((group) => group.name).join('、') : '無所屬主流族群'
}

// The head's one-line definition: W, G and the group names from the API (the names in their rank order).
export function mainstreamDefinition(data: Pick<MainstreamResponse, 'window' | 'group_count' | 'groups'>): string {
  const groups = [...data.groups].sort((a, b) => a.rank - b.rank)
  const count = groups.length < data.group_count ? `${groups.length} 個族群（上限 ${data.group_count} 個）` : `${data.group_count} 個族群`
  return `近 ${data.window} 個交易日相對加權指數最強的 ${count}：${groups.map((group) => group.name).join('、')}；族群內個股依 ${data.window} 日漲幅取前 20`
}

export const MAINSTREAM_MISSING_TITLE = '尚無主流族群名單'
export const MAINSTREAM_ZERO_TITLE = '當日沒有主流族群'

export type MainstreamState =
  | { kind: 'list'; items: MainstreamItem[] }
  | { kind: 'zero' | 'missing'; title: string; text: string }

// computed with rows → the list; zero and missing as the today list writes its empty states (UI_COPY_SPEC §10).
// universe_count is only on computed and zero responses (#768 review 6892856132).
export function mainstreamState(data: MainstreamResponse): MainstreamState {
  if (data.status === 'computed' && data.items.length > 0) return { kind: 'list', items: data.items }
  if (data.status === 'missing') {
    const day = formatDate(data.trading_date)
    return { kind: 'missing', title: MAINSTREAM_MISSING_TITLE, text: day ? `${day} 尚未產生主流族群名單` : '尚未產生主流族群名單' }
  }
  const universe = typeof data.universe_count === 'number' ? `（母體 ${data.universe_count.toLocaleString()} 檔）` : ''
  return { kind: 'zero', title: MAINSTREAM_ZERO_TITLE, text: `沒有族群有足夠的成員進入母體${universe}，當日不產生名單` }
}
