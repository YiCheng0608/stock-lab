import type { StrategyRecentPicks, StrategyRecentRow } from '../types'

// 「近 60 日入選過」 (#1021; UI_COPY_SPEC §10 接近年高前 20, 盈餘殖利率前 20): the 接近年高前 20 and 盈餘殖利率前 20 tabs
// switch between the day's list (當天) and every stock in the stored lists of the last 60 sessions (the research holds
// each day's 20 for 60 sessions, so its book is their union; decision #1 7114503228 D4 ③). It says which days a stock
// was listed and how often, nothing of a position, a weight or an order.

export type RecentView = 'today' | 'recent'

export const RECENT_VIEWS: { id: RecentView; label: string }[] = [
  { id: 'today', label: '當天' },
  { id: 'recent', label: '近 60 日入選過' },
]

export const RECENT_NOT_TODAY = '今日未入選'

// ?view=recent keeps 近 60 日入選過 across a reload; nothing (or another value) is 當天. A tab switch drops it
// (mainstream.ts todayListSearch).
export const VIEW_PARAM = 'view'
export const RECENT_VIEW_VALUE = 'recent'

export function recentView(search: URLSearchParams): RecentView {
  return search.get(VIEW_PARAM) === RECENT_VIEW_VALUE ? 'recent' : 'today'
}

export function recentViewSearch(search: URLSearchParams, view: RecentView): URLSearchParams {
  const next = new URLSearchParams(search)
  if (view === 'recent') next.set(VIEW_PARAM, RECENT_VIEW_VALUE)
  else next.delete(VIEW_PARAM)
  return next
}

// Only the pressed chip writes its count (DESIGN_SYSTEM §5 篩選膠囊): 「當天 20 檔」, 「近 60 日入選過 57 檔」.
export function recentChipLabel(view: RecentView, selected: boolean, counts: Record<RecentView, number>): string {
  const label = RECENT_VIEWS.find((item) => item.id === view)?.label ?? view
  return selected ? `${label} ${counts[view].toLocaleString()} 檔` : label
}

// 「11/20」 of an ISO date; the window is at most 60 sessions, so the year is left out.
export function monthDay(value: string | null | undefined): string {
  const match = value ? /^\d{4}-(\d{2})-(\d{2})/.exec(value) : null
  return match ? `${match[1]}/${match[2]}` : '—'
}

// 「近 60 個交易日」, or with fewer stored lists than sessions 「近 {n} 個交易日（名單從 {MM/DD} 起）」: the days the
// counts are over, not a 60 the lists do not have.
export function recentWindowText(picks: Pick<StrategyRecentPicks, 'sessions' | 'days' | 'since'>): string {
  if (picks.days >= picks.sessions) return `近 ${picks.sessions} 個交易日`
  return `近 ${picks.days} 個交易日（名單從 ${monthDay(picks.since)} 起）`
}

// 「入選 3 次 · 首次 10/01 · 最近 11/20」.
export function recentPickText(row: Pick<StrategyRecentRow, 'count' | 'first_date' | 'last_date'>): string {
  return `入選 ${row.count} 次 · 首次 ${monthDay(row.first_date)} · 最近 ${monthDay(row.last_date)}`
}

// The most often listed first, then the latest listed, then the symbol (the API's order, kept here too).
export function recentPickRows(picks: Pick<StrategyRecentPicks, 'items'>): StrategyRecentRow[] {
  return [...picks.items].sort((a, b) =>
    b.count - a.count
    || b.last_date.localeCompare(a.last_date)
    || a.instrument.symbol.localeCompare(b.instrument.symbol)
    || a.instrument.exchange.localeCompare(b.instrument.exchange))
}
