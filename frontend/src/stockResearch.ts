import type { EventRow, InstrumentDetail, NewsItem } from './types'
import { formatProductTimeRole } from './presentation'

// Temporary UI guard for the currently known official-industry membership
// migration issue. Remove this flag after the repaired source data is verified.
export const TEMPORARY_INDUSTRY_GROUP_GUARD = true
export const TEMPORARY_INDUSTRY_GROUP_NOTICE = '既有族群關聯待重新核實；排行與相關研究條件僅供查閱。'

export function isTemporaryIndustryTheme(theme: { category?: string | null; name_status?: string | null }): boolean {
  if (!TEMPORARY_INDUSTRY_GROUP_GUARD) return false
  const category = theme.category?.trim().toLowerCase() ?? ''
  return category === '股票族群' || category === 'industry' || category.startsWith('industry ·') || category.startsWith('產業')
}

export function isTemporaryIndustryGroupName(name: string | null | undefined): boolean {
  if (!TEMPORARY_INDUSTRY_GROUP_GUARD) return false
  const value = name?.trim() ?? ''
  return /^industry\s*·/i.test(value) || /^產業(?:分類|代碼)/.test(value)
}

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/
const AWARE_INSTANT = /(?:Z|[+-]\d\d:\d\d)$/

function validDateOnly(value: string): boolean {
  if (!DATE_ONLY.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

export function formatResearchDate(value: string | null | undefined): string {
  if (!value) return '待核實'
  if (validDateOnly(value)) return value.replace(/-/g, '/')
  return '待核實'
}

export function formatResearchDateTime(value: string | null | undefined): string {
  if (!value) return '待核實'
  if (validDateOnly(value)) return formatResearchDate(value)
  if (!AWARE_INSTANT.test(value)) return '待核實（時間格式未確認）'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '待核實'
  return new Intl.DateTimeFormat('zh-TW', {
    timeZone: 'Asia/Taipei',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(parsed)
}

export function recentByDate<T extends { date: string }>(rows: readonly T[], limit: number): T[] {
  return [...rows]
    .sort((left, right) => {
      const leftValid = validDateOnly(left.date)
      const rightValid = validDateOnly(right.date)
      if (leftValid !== rightValid) return leftValid ? -1 : 1
      return right.date.localeCompare(left.date)
    })
    .slice(0, Math.max(0, limit))
}

export type NewsTimeLabels = {
  event: string
  published: string
  collected: string
  dataAsOf: string
  unknownCount: number
}

function formatNewsTime(item: NewsItem, roleName: string, fallbackValue: string | null | undefined): string {
  return item.product_time ? formatProductTimeRole(item.product_time, roleName) : formatResearchDateTime(fallbackValue)
}

export function newsTimeLabels(item: NewsItem): NewsTimeLabels {
  const eventValue = item.event_at ?? item.event_date
  const eventRole = item.event_at != null ? 'event_at' : 'event_date'
  const event = formatNewsTime(item, eventRole, eventValue)
  const published = formatNewsTime(item, 'published_at', item.published_at)
  const collected = formatNewsTime(item, 'collected_at', item.collected_at)
  const dataAsOf = formatNewsTime(item, 'data_as_of', item.provenance.data_as_of)
  return {
    event,
    published,
    collected,
    dataAsOf,
    unknownCount: [eventValue, item.published_at, item.collected_at, item.provenance.data_as_of]
      .filter((value, index) => value != null && [event, published, collected, dataAsOf][index].startsWith('待核實'))
      .length,
  }
}

export type ResearchInventory = {
  groups: number
  chips: number
  news: number
  events: number
  strategies: number
  unknownTimes: number
}

export function summarizeStockResearch(data: Pick<InstrumentDetail, 'groups' | 'chips' | 'events' | 'strategy_conditions'> & { news: NewsItem[] }): ResearchInventory {
  const newsUnknownTimes = data.news.reduce((count, item) => count + newsTimeLabels(item).unknownCount, 0)
  const eventUnknownTimes = data.events.filter((item) => !validDateOnly(item.date) || (item.data_as_of != null && formatResearchDateTime(item.data_as_of).startsWith('待核實'))).length
  return {
    groups: data.groups.length,
    chips: data.chips.length,
    news: data.news.length,
    events: data.events.length,
    strategies: Object.keys(data.strategy_conditions).length,
    unknownTimes: newsUnknownTimes + eventUnknownTimes,
  }
}

export function eventTimeLabels(item: EventRow): { eventDate: string; dataAsOf: string } {
  return { eventDate: formatResearchDate(item.date), dataAsOf: formatResearchDateTime(item.data_as_of) }
}
