import type { CandidateComponentKey, CandidateGroup, CandidateItem, CandidateLevels, CandidatesResponse } from '../types'

// Pure helpers for the daily candidate list (candidate_score_v1, #215); copy follows UI_COPY_SPEC §10.

export const CANDIDATE_LIMIT = 20

export function candidatesPath(date?: string, limit?: number): string {
  const params = new URLSearchParams()
  if (date) params.set('date', date)
  if (limit != null) params.set('limit', String(limit))
  const query = params.toString()
  return '/candidates' + (query ? '?' + query : '')
}

// Display order of the four components; news sentiment is LLM inference.
export const CANDIDATE_COMPONENTS: ReadonlyArray<{ key: CandidateComponentKey; label: string }> = [
  { key: 'technical', label: '技術' },
  { key: 'chips', label: '籌碼' },
  { key: 'news_sentiment', label: '新聞情緒' },
  { key: 'group', label: '族群' },
]

export const CANDIDATE_DISCLAIMER = '評分只用於排序，不代表勝率或預期報酬'
export const PARTIAL_NOTE = '部分分項無資料，以有資料的分項計分'
export const NOT_COMPUTED_TEXT = '此交易日尚未產生候選清單'
export const ZERO_REASON_TEXT: Record<string, string> = {
  no_actionable_signals: '當日沒有成立（條件成立）的策略訊號',
  all_excluded: '成立的訊號都因 ETF、價位不合法或評分資料不足被排除',
}

const STRATEGY_LABELS: Record<string, string> = { breakout_v1: '突破條件', pullback_v1: '回踩條件' }

export function candidateStrategyLabel(strategy: string): string {
  return STRATEGY_LABELS[strategy] ?? '策略條件'
}

const isFiniteNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)

// Scores are 0–1 and shown as 0–100 integers; null is 「—」, never 0.
export function formatCandidateScore(value: number | null | undefined): string {
  return isFiniteNumber(value) ? String(Math.round(value * 100)) : '—'
}

export function formatPrice(value: number | null | undefined): string {
  return isFiniteNumber(value) ? value.toLocaleString('zh-TW', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'
}

export function formatEntryZone(levels: CandidateLevels): string {
  const { low, high } = levels.entry_zone
  if (!isFiniteNumber(low) && !isFiniteNumber(high)) return formatPrice(levels.entry)
  if (low === high || !isFiniteNumber(high)) return formatPrice(low)
  if (!isFiniteNumber(low)) return formatPrice(high)
  return `${formatPrice(low)}～${formatPrice(high)}`
}

export function formatRiskReward(value: number | null | undefined): string {
  return isFiniteNumber(value) ? value.toFixed(2) : '—'
}

export function formatDate(value: string | null | undefined): string | null {
  const match = value ? /^(\d{4})-(\d{2})-(\d{2})/.exec(value) : null
  return match ? `${match[1]}/${match[2]}/${match[3]}` : null
}

// Sub-item names and value formats, matching the V1_SPEC candidate_score_v1 component table.
type SubItemSpec = { label: string; format: (value: number) => string }
const ratio = (digits: number) => (value: number) => `${value.toFixed(digits)} 倍`
const percent = (value: number) => `${(value * 100).toFixed(1)}%`
const signedPercent = (value: number) => `${value > 0 ? '+' : ''}${(value * 100).toFixed(1)}%`

const SUB_ITEMS: Record<string, SubItemSpec> = {
  volume_ratio: { label: '量比（當日量／前 20 日均量）', format: ratio(2) },
  distance: { label: '距離（突破距 20 日高點、回踩距 20 日均線）', format: percent },
  risk_reward: { label: 'RR（只顯示，不計分）', format: ratio(2) },
  institutional_flow_5d: { label: '三大法人 5 日淨買超（÷20 日均量）', format: ratio(2) },
  institutional_flow_20d: { label: '三大法人 20 日淨買超（÷20 日均量）', format: ratio(2) },
  margin_change_5d: { label: '融資 5 日變動', format: signedPercent },
  net_direction: { label: '近 3 日新聞淨方向（偏多＋1、偏空−1）', format: (value) => `${value > 0 ? '+' : ''}${value.toFixed(0)}` },
  board_percentile: { label: '所屬族群榜內位置', format: (value) => formatCandidateScore(value) },
}

export function subItemLabel(key: string): string {
  return SUB_ITEMS[key]?.label ?? key
}

export function formatSubItemValue(key: string, value: number | null | undefined): string {
  if (!isFiniteNumber(value)) return '—'
  return SUB_ITEMS[key]?.format(value) ?? value.toFixed(2)
}

const BOARD_LABELS: Record<string, string> = { industry: '產業', theme: '題材' }

export function groupBoardLabel(board: string): string {
  return BOARD_LABELS[board] ?? '其他'
}

// One line per group: name, board and rank on its board, or why it was not ranked that day.
export function candidateGroupText(group: CandidateGroup): string {
  const board = groupBoardLabel(group.board)
  if (group.qualified && isFiniteNumber(group.rank)) {
    return `${group.name}（${board}，第 ${group.rank} 名${isFiniteNumber(group.board_size) ? `／${group.board_size}` : ''}）`
  }
  return `${group.name}（${board}，當日未排名）`
}

const SOURCE_NAMES: Record<string, string> = {
  twse: '臺灣證券交易所',
  tpex: '證券櫃檯買賣中心',
}

// Market source keys come from the stored bars and chips (twse, tpex, twse_t86+twse_margin, …).
export function marketSourceLabel(source: string | null | undefined): string {
  if (!source) return '來源未提供'
  const exchange = source.split(/[_+]/)[0].toLowerCase()
  return SOURCE_NAMES[exchange] ?? source
}

export function exchangeLabel(exchange: string): string {
  return exchange === 'TWSE' ? '上市' : exchange === 'TPEx' ? '上櫃' : '市場待核實'
}

// Signal and group sources are rule versions; the news source ends with the LLM prompt version (推論).
export function candidateSourceText(item: CandidateItem): string {
  const promptVersion = item.sources.news.split(':').pop()
  const parts = [
    `訊號 ${item.sources.signal.replace(/^analysis:/, '')}`,
    `行情 ${marketSourceLabel(item.sources.market_bar)}`,
    `籌碼 ${marketSourceLabel(item.sources.chips)}`,
    `族群 ${item.sources.groups}`,
    `新聞方向 LLM 判讀 ${promptVersion || '版本未提供'}（推論）`,
  ]
  return parts.join(' · ')
}

export type CandidatesState =
  | { kind: 'list'; items: CandidateItem[] }
  | { kind: 'not_computed'; text: string }
  | { kind: 'zero'; text: string }

// not_computed and zero-candidate runs are legal results with their own copy; the API text wins when present.
export function candidatesState(data: CandidatesResponse): CandidatesState {
  if (data.status === 'not_computed') return { kind: 'not_computed', text: NOT_COMPUTED_TEXT }
  if (data.items.length === 0) {
    const text = data.zero_reason_text ?? (data.zero_reason ? ZERO_REASON_TEXT[data.zero_reason] : null) ?? '當日沒有候選'
    return { kind: 'zero', text }
  }
  return { kind: 'list', items: data.items }
}

export function stockPath(item: Pick<CandidateItem, 'instrument'>): string {
  return '/stocks/' + encodeURIComponent(item.instrument.exchange) + '/' + encodeURIComponent(item.instrument.symbol)
}
