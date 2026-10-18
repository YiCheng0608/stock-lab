import { formatTaipeiInstant } from '../news/newsView'
import type { ThemeSuggestion } from '../types'
import { formatDate } from './themeBoards'

// News theme suggestions awaiting review (#216); copy follows UI_COPY_SPEC §8.6.
// They are LLM inference aggregated from news: never scored, ranked or treated as a verified theme.

export const THEME_SUGGESTION_LIMIT = 20

export function themeSuggestionsPath(limit?: number): string {
  return '/theme-suggestions' + (limit != null ? `?limit=${limit}` : '')
}

export const SUGGESTION_NOTE = '由 AI 從近期新聞判讀出的題材名稱彙整，尚未經人工核實；不列入族群排行、不計分，也不作為交易理由。'
export const SUGGESTION_EMPTY_TEXT = '目前沒有新聞題材建議'
export const SUGGESTION_EMPTY_REASON = '新聞 AI 判讀尚未提出與既有族群不同名的題材'

const CONFIDENCE_LABELS: Record<string, string> = { high: '模型把握高', medium: '模型把握中', low: '模型把握低' }

export function suggestionConfidenceLabel(confidence: string | null | undefined): string {
  return CONFIDENCE_LABELS[confidence ?? ''] ?? '模型未提供把握'
}

export function suggestionDates(item: Pick<ThemeSuggestion, 'first_news_date' | 'last_news_date'>): string {
  const first = formatDate(item.first_news_date)
  const last = formatDate(item.last_news_date)
  if (!first || !last) return '新聞日期待核實'
  return first === last ? `新聞日 ${last}` : `首次 ${first} · 最近 ${last}`
}

export function suggestionVersionLine(item: Pick<ThemeSuggestion, 'llm_models' | 'prompt_version' | 'aggregation_version'>): string {
  const models = item.llm_models.length ? item.llm_models.join('、') : '未記錄'
  return `模型 ${models} · 提示版本 ${item.prompt_version} · 彙整規則 ${item.aggregation_version}`
}

export function suggestionUpdatedText(updatedAt: string | null | undefined): string | null {
  const text = formatTaipeiInstant(updatedAt)
  return text ? `最近更新 ${text}` : null
}

// News beyond the newest few listed inline.
export function hiddenNewsCount(item: Pick<ThemeSuggestion, 'news_count' | 'news'>): number {
  return Math.max(0, item.news_count - item.news.length)
}
