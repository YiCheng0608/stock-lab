import type { CursorParams } from '../api'
import { newsSourceLabel, productTimeRoleKnown } from '../presentation'
import type { NewsAi, NewsItem, ProductTime, ProductTimeRole } from '../types'

// News page and stock news timeline (docs/NEWS_SPEC.md §4–§6, docs/UI_COPY_SPEC.md §4).
export const NEWS_PAGE_SIZE = 20
export const STOCK_NEWS_LIMIT = 50
export const NEWS_SUMMARY_PREVIEW_CHARS = 120

// Feed news is split by category (domestic／international); official disclosures are projected as company／taiwan
// categories, so their tab filters on source_kind instead.
export type NewsTab = 'domestic' | 'international' | 'official'

export const NEWS_TABS: ReadonlyArray<{ id: NewsTab; label: string }> = [
  { id: 'domestic', label: '國內' },
  { id: 'international', label: '國際' },
  { id: 'official', label: '官方公告' },
]

export function parseNewsTab(value: string | null | undefined): NewsTab {
  return NEWS_TABS.some((tab) => tab.id === value) ? value as NewsTab : 'domestic'
}

export type NewsFilters = { tab: NewsTab; q: string; symbol: string }

export function newsListParams({ tab, q, symbol }: NewsFilters, cursor?: string, limit = NEWS_PAGE_SIZE): CursorParams {
  const params: CursorParams = tab === 'official' ? { source_kind: 'official_disclosure' } : { category: tab }
  if (q.trim()) params.q = q.trim()
  if (symbol.trim()) params.symbol = symbol.trim()
  if (cursor) params.cursor = cursor
  params.limit = limit
  return params
}

// Search params of /news: the tab is omitted for the default (domestic), empty filters are dropped.
export function newsPageSearch({ tab, q, symbol }: NewsFilters): Record<string, string> {
  const search: Record<string, string> = {}
  if (tab !== 'domestic') search.tab = tab
  if (q.trim()) search.q = q.trim()
  if (symbol.trim()) search.symbol = symbol.trim()
  return search
}

export function newsCategoryLabel(category: string | null | undefined): string {
  return ({ domestic: '國內', international: '國際', company: '個股公告', taiwan: '台灣官方事件' } as Record<string, string>)[category ?? ''] ?? '類別待核實'
}

export function sourceKindLabel(kind: string | null | undefined): string {
  return ({ media: '媒體報導', macro_official: '官方機構', official_disclosure: '官方公告資料' } as Record<string, string>)[kind ?? ''] ?? '來源類型待核實'
}

export function newsSourceName(item: Pick<NewsItem, 'source_kind' | 'source_name'>): string {
  if (item.source_kind === 'official_disclosure') return newsSourceLabel(item.source_name)
  return item.source_name?.trim() || '來源未提供'
}

// Asia/Taipei has no DST: a fixed +08:00 keeps the format deterministic (YYYY/MM/DD HH:mm, UI_COPY §1).
export function formatTaipeiInstant(value: string | null | undefined): string | null {
  if (!value || !/(?:Z|[+-]\d\d:\d\d)$/.test(value)) return null
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return null
  const local = new Date(parsed.getTime() + 8 * 3600 * 1000)
  const pad = (number: number) => String(number).padStart(2, '0')
  return `${local.getUTCFullYear()}/${pad(local.getUTCMonth() + 1)}/${pad(local.getUTCDate())} ${pad(local.getUTCHours())}:${pad(local.getUTCMinutes())}`
}

export function formatCalendarDay(value: string | null | undefined): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value ?? '')
  return match ? `${match[1]}/${match[2]}/${match[3]}` : null
}

function formatRole(role: ProductTimeRole | undefined): string | null {
  if (!role || !productTimeRoleKnown(role)) return null
  return role.precision === 'date' ? formatCalendarDay(role.value) : formatTaipeiInstant(role.utc ?? role.value)
}

const TIME_ROLES: ReadonlyArray<{ role: 'published_at' | 'event_at' | 'event_date'; prefix: string }> = [
  { role: 'published_at', prefix: '發布於' },
  { role: 'event_at', prefix: '事件於' },
  { role: 'event_date', prefix: '事件日' },
]

export type NewsTimeView = { text: string; dateTime: string | null; known: boolean }

// UI_COPY §4 日期: the first known of published_at → event_at → event_date. With product_time present only its roles count
// (NEWS_SPEC §6); a role with a source value but unknown status is 「待核實」, no source value at all is 「未提供」.
export function newsTime(item: Pick<NewsItem, 'product_time' | 'published_at' | 'event_at' | 'event_date' | 'time_consistency'>): NewsTimeView {
  const hasSourceTime = Boolean(item.published_at || item.event_at || item.event_date)
  if (item.time_consistency === 'conflict') return { text: '來源時間待核實', dateTime: null, known: false }
  if (item.product_time) {
    for (const { role, prefix } of TIME_ROLES) {
      const value = item.product_time.roles?.[role]
      const text = formatRole(value)
      if (text) return { text: `${prefix} ${text}`, dateTime: value?.precision === 'date' ? value.value ?? null : value?.utc ?? value?.value ?? null, known: true }
    }
    return { text: hasSourceTime ? '來源時間待核實' : '來源時間未提供', dateTime: null, known: false }
  }
  const legacy: Array<[string, string | null]> = [
    ['發布於', formatTaipeiInstant(item.published_at)],
    ['事件於', formatTaipeiInstant(item.event_at)],
    ['事件日', formatCalendarDay(item.event_date)],
  ]
  const found = legacy.find(([, text]) => text)
  if (found) return { text: `${found[0]} ${found[1]}`, dateTime: null, known: true }
  return { text: hasSourceTime ? '來源時間待核實' : '來源時間未提供', dateTime: null, known: false }
}

// Audit-layer time (詳情的系統收錄時間、AI 產生時間): only aware values are shown.
export function productTimeText(time: ProductTime | undefined, role: string): string {
  return formatRole(time?.roles?.[role]) ?? '待核實'
}

export function normalizeText(value: string | null | undefined): string | null {
  const cleaned = value?.replace(/\s+/g, ' ').trim()
  return cleaned || null
}

export function summaryPreview(item: Pick<NewsItem, 'summary_preview' | 'summary' | 'description'>, maxLength = NEWS_SUMMARY_PREVIEW_CHARS): string | null {
  const text = normalizeText(item.summary_preview ?? item.summary ?? item.description)
  if (!text) return null
  const chars = Array.from(text)
  return chars.length <= maxLength ? text : chars.slice(0, maxLength - 1).join('').trimEnd() + '…'
}

export const NO_SUMMARY_TEXT = '來源未提供摘要'

export type DirectionTone = 'up' | 'down' | 'flat'
export type DirectionView = { label: string; tone: DirectionTone | null }

// Direction is text plus a colored dot; unknown carries no red／green (NEWS_SPEC §6, Taiwan colors: up red, down green).
export function directionView(direction: string | null | undefined): DirectionView {
  if (direction === 'positive') return { label: '可能正向', tone: 'up' }
  if (direction === 'negative') return { label: '可能負向', tone: 'down' }
  if (direction === 'mixed') return { label: '正負互見', tone: 'flat' }
  return { label: '影響尚未判定', tone: null }
}

export function impactScopeLabel(scope: string | null | undefined): string {
  return ({ instrument: '個股', theme: '族群', market: '整體市場' } as Record<string, string>)[scope ?? ''] ?? '範圍待核實'
}

export function candidateConfidenceLabel(confidence: string | null | undefined): string {
  return ({ high: '模型把握高', medium: '模型把握中', low: '模型把握低' } as Record<string, string>)[confidence ?? ''] ?? '模型把握未提供'
}

// The AI block is shown only for a done inference result; unsupported items keep their direction unknown.
export function usableAi(item: Pick<NewsItem, 'ai'>): NewsAi | null {
  const ai = item.ai
  return ai && ai.inference === true && ai.status === 'done' ? ai : null
}

export function aiDirection(ai: NewsAi): DirectionView {
  return directionView(ai.unsupported ? 'unknown' : ai.impact_direction)
}

export type SourceLinkView = { href: string | null; label: string; note: string | null }

function safeUrl(url: string | null | undefined): string | null {
  return url && /^https?:\/\//i.test(url) ? url : null
}

// UI_COPY §4 來源連結: item → original, feed → dataset (may not locate this item), none → plain text, no dead button.
export function sourceLink(item: Pick<NewsItem, 'source' | 'source_kind'>): SourceLinkView {
  const href = safeUrl(item.source?.url)
  const kind = item.source?.url_kind
  if (href && kind === 'item') return { href, label: item.source_kind === 'official_disclosure' ? '查看原始公告' : '查看原文', note: null }
  if (href && kind === 'feed') return { href, label: '查看官方公告資料集', note: '資料集連結未必定位到本則公告' }
  return { href: null, label: '來源連結未提供', note: null }
}

export function userFacingNewsThemes(item: Pick<NewsItem, 'themes'>): NewsItem['themes'] {
  return (item.themes ?? []).filter((theme) => {
    const name = theme.display_name.trim()
    if (!name || name === '族群待確認') return false
    // The API only emits verified active memberships; keep a guard for a legacy English group label.
    return !/^(industry|etf|new listings)\b/i.test(name)
  })
}

export type RelatedInstrument = { key: string; label: string; href: string | null }

// Verified relations only: rule／source matched instruments (exchange + symbol), or the bare code of an official projection.
export function verifiedInstruments(item: Pick<NewsItem, 'instruments' | 'symbols'>): RelatedInstrument[] {
  const instruments = item.instruments ?? []
  if (instruments.length) {
    return instruments.map((instrument) => ({
      key: `${instrument.exchange}:${instrument.symbol}`,
      label: `${instrument.symbol} ${instrument.name}`.trim(),
      href: `/stocks/${encodeURIComponent(instrument.exchange)}/${encodeURIComponent(instrument.symbol)}`,
    }))
  }
  return (item.symbols ?? []).map((symbol) => ({ key: symbol, label: symbol.includes(':') ? symbol.split(':')[1] : symbol, href: null }))
}

// /api/news?symbol= matches substrings of symbols_json; the stock timeline keeps exact matches for this exchange + symbol.
export function matchesInstrument(item: Pick<NewsItem, 'instruments' | 'symbols'>, exchange: string, symbol: string): boolean {
  if ((item.instruments ?? []).some((instrument) => instrument.exchange === exchange && instrument.symbol === symbol)) return true
  return (item.symbols ?? []).some((value) => value === `${exchange}:${symbol}` || value === symbol)
}

export function stockNewsParams(symbol: string): CursorParams {
  return { symbol, limit: STOCK_NEWS_LIMIT }
}
