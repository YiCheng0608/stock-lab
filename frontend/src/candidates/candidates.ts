import { noPreviousCloseText } from '../marketChange'
import { formatTaipeiInstant } from '../news/newsView'
import type { CandidateComponentKey, CandidateGroup, CandidateItem, CandidateLevels, CandidateLlmNote, CandidateMarket, CandidatesResponse, RiskRewardBasis } from '../types'

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
  all_excluded: '成立的訊號都因 ETF、價位不合法、成交量低於門檻或評分資料不足被排除',
}

// ---- liquidity floor (candidate_score_v6, #490; UI_COPY_SPEC §10) ----

// Lots (張) as a whole number with thousands separators, rounded down so an average below the floor never reads as
// the floor (999.6 is 「999 張」, PR 496 review); null is 「—」, never 0.
export function formatLots(value: number | null | undefined): string {
  return isFiniteNumber(value) ? `${Math.floor(value).toLocaleString('zh-TW')} 張` : '—'
}

// 「20 日均量 1,682 張」, or 「20 日均量資料不足」 without an average.
export function averageVolumeText(lots: number | null | undefined): string {
  return isFiniteNumber(lots) ? `20 日均量 ${formatLots(lots)}` : '20 日均量資料不足'
}

// The note next to 成立 when the day's run left the stock out for the floor; null when it did not.
export function liquidityExclusionText(
  exclusion: { exclusion: string | null; average_volume_lots_20d: number | null; minimum_lots: number | null } | null | undefined,
): string | null {
  if (!exclusion || !exclusion.exclusion) return null
  const floor = formatLots(exclusion.minimum_lots)
  if (exclusion.exclusion === 'low_volume') return `${averageVolumeText(exclusion.average_volume_lots_20d)}，低於 ${floor}門檻，不列候選`
  if (exclusion.exclusion === 'liquidity_data_missing') return `20 日均量資料不足，無法確認是否達 ${floor}門檻，不列候選`
  return null
}

// Every version reads the same (#392, #404, #580): the UI never shows a version suffix.
const STRATEGY_LABELS: Record<string, string> = {
  breakout_v1: '突破條件',
  pullback_v1: '回踩條件',
  breakout_v2: '突破條件',
  pullback_v2: '回踩條件',
  breakout_v3: '突破條件',
  pullback_v3: '回踩條件',
  pullback_v4: '回踩條件',
}

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

// Today list (#276): latest close of the run date and its change; an unverified change is not shown.
export const TODAY_VISIBLE = 10

export function formatCandidateClose(market: CandidateMarket | undefined): string {
  return market && isFiniteNumber(market.close) ? formatPrice(market.close) : '待核實'
}

export function candidateChange(market: CandidateMarket | undefined): { text: string; tone: 'up' | 'down' | 'flat' | null } {
  // #465, #475: no close on the previous session, and why (UI_COPY_SPEC §8.2).
  const noClose = noPreviousCloseText(market?.change_status)
  if (noClose) return { text: noClose, tone: null }
  if (!market || market.change_status !== 'known' || !isFiniteNumber(market.change_pct)) return { text: '漲跌待核實', tone: null }
  const percent = market.change_pct * 100
  const rounded = Number(percent.toFixed(2))
  return { text: `${rounded > 0 ? '+' : ''}${percent.toFixed(2)}%`, tone: rounded > 0 ? 'up' : rounded < 0 ? 'down' : 'flat' }
}

// The latest run's earliest execution date is always null (it needs the next bar), so the sentence names no date.
export function candidateT1Text(tradingDate: string | null | undefined): string | null {
  const day = formatDate(tradingDate)
  return day ? `${day} 收盤後條件成立，最早下一個交易日（T+1）才可研究進場。` : null
}

// A note (done or pending) is inference to open; without one the entry only explains that none exists yet.
export function candidateAiEntry(note: CandidateLlmNote | null | undefined): string {
  return note ? 'AI 推論 ▸' : 'AI 說明 ▸'
}

// RR reads as a multiple (UI_COPY_SPEC §10): 「1.60 倍」.
export function formatRiskReward(value: number | null | undefined): string {
  return isFiniteNumber(value) ? `${value.toFixed(2)} 倍` : '—'
}

// What the RR's entry is (#580; UI_COPY_SPEC §10): the short note under the today list's RR, and the entry it names.
const RISK_REWARD_BASIS: Record<RiskRewardBasis, { note: string; entry: string }> = {
  entry_zone_midpoint: { note: '以進場區中點計算', entry: '進場區中點' },
  entry_price: { note: '以進場價計算', entry: '進場價' },
  signal_close: { note: '以資料日收盤計算', entry: '資料日收盤' },
}

function basisOf(basis: string | null | undefined) {
  return basis && Object.hasOwn(RISK_REWARD_BASIS, basis) ? RISK_REWARD_BASIS[basis as RiskRewardBasis] : null
}

// 「以進場區中點計算」; null for an unknown or missing basis (responses from before #580), which shows no note.
export function riskRewardBasisNote(basis: string | null | undefined): string | null {
  return basisOf(basis)?.note ?? null
}

// The entry the RR is read from: 「進場區中點」; null for an unknown or missing basis.
export function riskRewardBasisEntry(basis: string | null | undefined): string | null {
  return basisOf(basis)?.entry ?? null
}

// What follows an RR: 「（以進場區中點 27.27 元計算）」; null without an RR, a known basis or the entry price.
export function riskRewardBasisSuffix(value: number | null | undefined, basis: string | null | undefined, entry: number | null | undefined): string | null {
  const known = basisOf(basis)
  if (!isFiniteNumber(value) || !known || !isFiniteNumber(entry)) return null
  return `（以${known.entry} ${formatPrice(entry)} 元計算）`
}

// The RR with its basis and entry price: 「1.62 倍（以進場區中點 27.27 元計算）」; without a known basis or entry, the RR only.
export function formatRiskRewardWithBasis(value: number | null | undefined, basis: string | null | undefined, entry: number | null | undefined): string {
  return `${formatRiskReward(value)}${riskRewardBasisSuffix(value, basis, entry) ?? ''}`
}

export function formatDate(value: string | null | undefined): string | null {
  const match = value ? /^(\d{4})-(\d{2})-(\d{2})/.exec(value) : null
  return match ? `${match[1]}/${match[2]}/${match[3]}` : null
}

// Sub-item names and value formats, matching the docs/spec/candidate_score.md candidate_score_v1 component table.
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

// The glossary term of a partial group (event_data_pending), the same words as the /themes quality badge.
export const GROUP_EVENT_PENDING = '事件資料待補'

// ranked: used by the candidate score; pending: scored on four components only (partial, #453); unranked: anything else.
export function candidateGroupState(group: CandidateGroup): 'ranked' | 'pending' | 'unranked' {
  if (group.qualified && isFiniteNumber(group.rank)) return 'ranked'
  if (group.data_quality === 'partial') return 'pending'
  return 'unranked'
}

// One line per group: name, board and rank on its board, or why it did not count that day (UI_COPY_SPEC 每日候選).
export function candidateGroupText(group: CandidateGroup): string {
  const board = groupBoardLabel(group.board)
  const state = candidateGroupState(group)
  if (state === 'ranked') {
    return `${group.name}（${board}，第 ${group.rank} 名${isFiniteNumber(group.board_size) ? `／${group.board_size}` : ''}）`
  }
  if (state === 'pending') return `${group.name}（${board}，${GROUP_EVENT_PENDING}，未計入族群分）`
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

// LLM note (#220): inference shown apart from the rule values above it.
export const NOTE_TITLE = 'AI 進出點說明'
export const NOTE_DISCLAIMER = '由 AI 依上方規則數值、理由與關聯新聞撰寫的推論，不是買賣建議；價位以規則數值為準。'
export const NOTE_MISSING_TEXT = '此檔尚未產生 AI 說明'
export const NOTE_PENDING_TEXT = 'AI 說明這次未能產生'
export const NOTE_PARTS: ReadonlyArray<{ key: 'selection' | 'levels' | 'risks'; label: string }> = [
  { key: 'selection', label: '為何入選' },
  { key: 'levels', label: '進場區、停損與目標' },
  { key: 'risks', label: '需留意的風險' },
]

export type CandidateNoteView =
  | { kind: 'done'; parts: Array<{ key: string; label: string; text: string }>; meta: string }
  | { kind: 'empty'; text: string; meta: string | null }

// A pending note was only attempted: no model, and its time is the attempt.
export function candidateNoteMeta(note: CandidateLlmNote): string {
  const time = formatTaipeiInstant(note.generated_at)
  const done = note.status === 'done'
  return [
    ...(done ? [`模型 ${note.model || '未記錄'}`] : []),
    `提示版本 ${note.prompt_version}`,
    ...(time ? [`${done ? '產生於' : '嘗試於'} ${time}`] : []),
  ].join(' · ')
}

// A done note with every part shows its text; anything else is one fixed sentence.
export function candidateNoteView(note: CandidateLlmNote | null | undefined): CandidateNoteView {
  if (!note) return { kind: 'empty', text: NOTE_MISSING_TEXT, meta: null }
  const parts = NOTE_PARTS.map(({ key, label }) => ({ key, label, text: note[key] ?? '' }))
  if (note.status !== 'done' || parts.some((part) => !part.text)) {
    return { kind: 'empty', text: note.status === 'pending' ? NOTE_PENDING_TEXT : NOTE_MISSING_TEXT, meta: candidateNoteMeta(note) }
  }
  return { kind: 'done', parts, meta: candidateNoteMeta(note) }
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
