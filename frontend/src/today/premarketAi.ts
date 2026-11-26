import { todayListKind } from '../candidates/mainstream'
import { formatDay, formatTaipeiMinute } from '../dates'
import type { PremarketAiReason, PremarketAiResponse, PremarketAiStock } from '../types'
import { formatFixed } from '../units'

// The today page's pre-market AI reading (#1042, UI_COPY_SPEC §10 早盤 AI 判讀): the words and the price rule (3a).
export const PREMARKET_AI_TITLE = '早盤 AI 判讀'
export const PREMARKET_AI_LISTED = '今日名單的股票'
export const PREMARKET_AI_OTHERS = '候選池其他股票'
export const PREMARKET_AI_FAILED = '早盤 AI 判讀失敗：'
export const PREMARKET_AI_MISSING = '尚無早盤 AI 判讀（每個交易日 08:21 判讀）'
export const PREMARKET_AI_LOADING = '早盤 AI 判讀載入中…'
export const PREMARKET_AI_ERROR = '早盤 AI 判讀暫時無法載入'
export const PREMARKET_AI_GAPS = '資料缺口'
export const PREMARKET_AI_INPUT_GAPS = '判讀輸入的資料缺口'

// Only under the 今日名單 tab and with a list date: the reading is of that list.
export function premarketAiShown(search: URLSearchParams, listDate: string | null | undefined): boolean {
  return Boolean(listDate) && todayListKind(search) === 'today'
}

export type PremarketAiState =
  | { kind: 'done' }
  | { kind: 'empty'; text: string }

export function premarketAiState(data: PremarketAiResponse): PremarketAiState {
  if (data.status === 'done') return { kind: 'done' }
  if (data.status === 'failed' || data.status === 'rejected') return { kind: 'empty', text: `${PREMARKET_AI_FAILED}${data.reason_text ?? '其他原因'}` }
  return { kind: 'empty', text: PREMARKET_AI_MISSING }
}

// 「2026/11/30 開盤前 · 模型 claude-sonnet-5-5 · 提示 premarket_v1 · 判讀於 2026/11/30 08:24」: 「提示」, as the 08:45
// message has it (「提示版本」 is #729's removed copy, removedCopy.fixtures.ts).
export function premarketAiMeta(data: PremarketAiResponse): string {
  const day = formatDay(data.session_date)
  const at = formatTaipeiMinute(data.finished_at ?? null)
  return [
    day ? `${day} 開盤前` : null,
    `模型 ${data.llm_model ?? '未記錄'}`,
    `提示 ${data.prompt_version}`,
    at ? `判讀於 ${at}` : null,
  ].filter(Boolean).join(' · ')
}

export function premarketAiGroups(stocks: readonly PremarketAiStock[]): { title: string; listed: boolean; stocks: PremarketAiStock[] }[] {
  return [
    { title: PREMARKET_AI_LISTED, listed: true, stocks: stocks.filter((stock) => stock.on_today_list) },
    { title: PREMARKET_AI_OTHERS, listed: false, stocks: stocks.filter((stock) => !stock.on_today_list) },
  ].filter((group) => group.stocks.length > 0)
}

const price = (value: number | null | undefined): string | null => typeof value === 'number' && Number.isFinite(value) && value > 0 ? formatFixed(value, 2) : null

export const PREMARKET_AI_LEVELS = '規則價位'
export const PREMARKET_AI_LEVELS_INCOMPLETE = '規則價位不完整'

// One labelled price in the §7 entry/stop/target colour (.level-entry, .level-stop, .level-target).
export type PremarketAiLevel = { label: string; value: string; className: 'level-entry' | 'level-stop' | 'level-target' }

// 3a: prices only on a today-list stock, and only the rule's: 進場 (進場區 for a pullback), 停損, 目標一. Any other stock
// has none (null), whatever the response holds; a today-list stock without all three is 'incomplete'.
export function premarketAiLevelParts(stock: PremarketAiStock): PremarketAiLevel[] | 'incomplete' | null {
  if (!stock.on_today_list) return null
  const levels = stock.levels
  if (!levels) return 'incomplete'
  const stop = price(levels.invalid_price)
  const target = price(levels.target_1)
  const low = price(levels.entry_zone?.low)
  const high = price(levels.entry_zone?.high)
  const single = price(levels.entry ?? levels.entry_zone?.low)
  const entry: PremarketAiLevel | null = levels.entry_type === 'pullback'
    ? (low && high ? { label: '進場區', value: `${low}～${high}`, className: 'level-entry' } : null)
    : (single ? { label: '進場', value: single, className: 'level-entry' } : null)
  if (!entry || !stop || !target) return 'incomplete'
  return [entry, { label: '停損', value: stop, className: 'level-stop' }, { label: '目標一', value: target, className: 'level-target' }]
}

// The same as one line: 「規則價位 進場 101.00｜停損 98.00｜目標一 103.20」 (the page's text; verify T30 mirrors it).
export function premarketAiLevels(stock: PremarketAiStock): string | null {
  const parts = premarketAiLevelParts(stock)
  if (parts === null) return null
  if (parts === 'incomplete') return PREMARKET_AI_LEVELS_INCOMPLETE
  return `${PREMARKET_AI_LEVELS} ${parts.map((part) => `${part.label} ${part.value}`).join('｜')}`
}

// One line with the name, 「1101 台泥 · 依開盤價重算（…）」: a name on a line of its own reads as a K-line card's title.
export const PREMARKET_AI_JOIN = ' · '

export function premarketAiAction(stock: PremarketAiStock): string {
  return stock.reprice_text ? `${stock.action_text}（${stock.reprice_text}）` : stock.action_text
}

// A reason's cited inputs: the news (each links to its news page) and the labels of the others, once each.
export function premarketAiRefs(reason: PremarketAiReason): { news: { id: number; label: string }[]; others: string[] } {
  const news: { id: number; label: string }[] = []
  const others: string[] = []
  for (const ref of reason.refs) {
    if (ref.kind === 'news' && typeof ref.news_id === 'number') {
      if (!news.some((item) => item.id === ref.news_id)) news.push({ id: ref.news_id, label: ref.label ?? `新聞 ${ref.news_id}` })
    } else if (ref.label && !others.includes(ref.label)) {
      others.push(ref.label)
    }
  }
  return { news, others }
}

// 「1101 台泥」, no 「#n」: the list's rows above own that (verify page_checks.CANDIDATE_ROW), and the order says the rank.
export function premarketAiStockName(stock: PremarketAiStock): string {
  return [stock.symbol, stock.name].filter(Boolean).join(' ')
}
