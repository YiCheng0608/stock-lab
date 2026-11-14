import { noPreviousCloseText } from '../marketChange'
import { formatTaipeiInstant } from '../news/newsView'
import type { CandidateComponentKey, CandidateGroup, CandidateItem, CandidateLevels, CandidateLlmNote, CandidateMarket, CandidateRecentCloses, CandidatesResponse, ForeignIndex, OvernightUs, RiskRewardBasis } from '../types'

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

export { exchangeLabel } from '../presentation'

// Signal and group sources are rule versions; the news source is the LLM prompt version. It is a source, a fact, so
// it carries no 推論 mark: the news component and its reason say 推論 (#661, DESIGN_SYSTEM §7).
export function candidateSourceText(item: CandidateItem): string {
  const promptVersion = item.sources.news.split(':').pop()
  const parts = [
    `訊號 ${item.sources.signal.replace(/^analysis:/, '')}`,
    `行情 ${marketSourceLabel(item.sources.market_bar)}`,
    `籌碼 ${marketSourceLabel(item.sources.chips)}`,
    `族群 ${item.sources.groups}`,
    `新聞方向 LLM 判讀 ${promptVersion || '版本未提供'}`,
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

// ---- terminal layout (DESIGN_SYSTEM §5 候選列表：價位尺與走勢圖) ----

// The three rule prices the chart draws for a candidate: its entry (the zone midpoint when the API gives none), the
// stop and the first target; null unless all three are there and in order.
export function candidateChartLevels(levels: CandidateLevels): { entry: number; stop: number; target: number } | null {
  const { low, high } = levels.entry_zone ?? { low: null, high: null }
  const zone = isFiniteNumber(low) && isFiniteNumber(high) ? (low + high) / 2 : null
  const entry = levels.entry ?? zone
  const stop = levels.invalid_price
  const target = levels.target_1
  if (!isFiniteNumber(entry) || !isFiniteNumber(stop) || !isFiniteNumber(target)) return null
  return stop > 0 && stop < entry && entry < target ? { entry, stop, target } : null
}

// Where the entry and the close sit between the stop (0) and the first target (100) on the price ladder. The close is
// clamped to the ladder; `outside` says which end it ran past. null without a full set of levels or a close.
export type LadderView = { entry: number; close: number; outside: 'below_stop' | 'above_target' | null }
export function priceLadder(levels: CandidateLevels, close: number | null | undefined): LadderView | null {
  const chart = candidateChartLevels(levels)
  if (!chart || !isFiniteNumber(close)) return null
  const span = chart.target - chart.stop
  const at = (value: number) => ((value - chart.stop) / span) * 100
  const position = at(close)
  return {
    entry: at(chart.entry),
    close: Math.min(100, Math.max(0, position)),
    outside: position < 0 ? 'below_stop' : position > 100 ? 'above_target' : null,
  }
}

export function ladderLabel(view: LadderView): string {
  if (view.outside === 'below_stop') return '收盤已低於停損'
  if (view.outside === 'above_target') return '收盤已高於目標'
  return view.close < view.entry ? '收盤在停損與進場之間' : '收盤在進場與目標之間'
}

// ---- sparkline (#653; DESIGN_SYSTEM §5 候選列表) ----

// The SVG box the row's sparkline is drawn in (CSS pixels; the stroke keeps 1.5px at any size).
export const SPARKLINE_WIDTH = 96
export const SPARKLINE_HEIGHT = 24

// The row's line of the last 30 sessions' closes: one path in the box above, a gap where a session has no close (no
// value is filled in), red when the last close is above the first and green when below (台股紅漲綠跌), and the label
// that states the span and its change. null with fewer than 2 closes.
export type SparklineView = { path: string; tone: 'up' | 'down' | 'flat'; label: string }
export function sparkline(recent: CandidateRecentCloses | null | undefined, width = SPARKLINE_WIDTH, height = SPARKLINE_HEIGHT): SparklineView | null {
  if (!recent || recent.dates.length !== recent.closes.length) return null
  const known = recent.closes.flatMap((close, index) => (isFiniteNumber(close) && close > 0 ? [{ close, index }] : []))
  if (known.length < 2) return null
  const values = known.map(({ close }) => close)
  const low = Math.min(...values)
  const span = Math.max(...values) - low
  // Half the stroke width inside each edge so the line is never cut by the box.
  const pad = 1
  const step = (width - 2 * pad) / Math.max(1, recent.closes.length - 1)
  const x = (index: number) => pad + index * step
  const y = (close: number) => (span > 0 ? pad + (1 - (close - low) / span) * (height - 2 * pad) : height / 2)
  const round = (value: number) => Number(value.toFixed(2))
  let path = ''
  let previous = -2
  for (const { close, index } of known) {
    path += `${index === previous + 1 ? 'L' : 'M'}${round(x(index))} ${round(y(close))}`
    previous = index
  }
  const first = known[0]
  const last = known[known.length - 1]
  const percent = ((last.close - first.close) / first.close) * 100
  const rounded = Number(percent.toFixed(2))
  const tone = rounded > 0 ? 'up' : rounded < 0 ? 'down' : 'flat'
  const from = formatDate(recent.dates[first.index])
  const to = formatDate(recent.dates[last.index])
  return { path, tone, label: `近 ${recent.dates.length} 個交易日收盤走勢：${from}–${to} ${rounded > 0 ? '+' : ''}${percent.toFixed(2)}%` }
}

// ---- the today list below 1280px (#665; DESIGN_SYSTEM §5 候選列表): a row's K-line card opens under it ----

// The width from which the chart sits beside the list; below it a row opens its own card (styles.css uses the same).
export const TERMINAL_MIN_WIDTH = 1280
// One card at a time: pressing the open row closes it, pressing another row moves the card there.
export function nextChartRank(current: number | null, rank: number): number | null {
  return current === rank ? null : rank
}
// A click in a row opens or closes its card unless it lands on something that acts by itself (the name link, a term,
// the AI button) or ends a text selection (decision 6841170465: copying a price must not open the chart).
export const ROW_CLICK_IGNORED = 'a, button, summary, input, select, textarea, label, [role="button"]'
export function rowClickToggles(target: { closest(selector: string): unknown } | null, selection: string): boolean {
  return !!target && !target.closest(ROW_CLICK_IGNORED) && selection === ''
}
// The rank button's label below 1280px (UI_COPY_SPEC §10); its text stays 「#n」.
export function chartToggleLabel(rank: number, open: boolean): string {
  return `第 ${rank} 名，${open ? '收起' : '展開'} K 線圖`
}

// ---- 隔夜美股 (Issue 681; UI_COPY_SPEC §10): the four US indexes on one line under the list's head ----

export const OVERNIGHT_US_TITLE = '隔夜美股'
export const OVERNIGHT_US_PENDING = '美股尚未更新'
export const OVERNIGHT_US_CLOSED = '美股休市'
// Short names, in the API's order (S&P 500, NASDAQ Composite, Dow Jones Industrial Average, PHLX Semiconductor).
export const OVERNIGHT_US_LABELS: Record<string, string> = { SPX: 'S&P 500', IXIC: 'NASDAQ', DJI: '道瓊', SOX: '費半' }

export type OvernightUsItem = {
  symbol: string
  label: string
  // 「+0.53%」, 「—」 without a change, 「未取得」 without a close.
  text: string
  tone: 'up' | 'down' | 'flat' | null
  // The item's own date when the four are not of one day.
  date: string | null
  stale: boolean
  // Of the expected night (latest, or the last session before a US holiday); a row says 非最新 otherwise.
  current: boolean
}

export type OvernightUsView = {
  // 美股尚未更新: none has the expected night; 美股休市: the expected night was a US holiday.
  lead: string | null
  // The one data date of the shown closes.
  date: string | null
  items: OvernightUsItem[]
}

const FRESH = new Set(['latest', 'us_market_closed'])

export function overnightUsItem(index: ForeignIndex): Omit<OvernightUsItem, 'date' | 'stale' | 'current'> {
  const label = OVERNIGHT_US_LABELS[index.symbol] ?? index.name
  if (index.status !== 'available' || !isFiniteNumber(index.close)) return { symbol: index.symbol, label, text: '未取得', tone: null }
  if (!isFiniteNumber(index.change_pct)) return { symbol: index.symbol, label, text: '—', tone: null }
  const percent = index.change_pct * 100
  const rounded = Number(percent.toFixed(2))
  return { symbol: index.symbol, label, text: `${rounded > 0 ? '+' : ''}${percent.toFixed(2)}%`, tone: rounded > 0 ? 'up' : rounded < 0 ? 'down' : 'flat' }
}

// null without overnight_us (a response from before Issue 681). Nothing collected at all: the lead only.
export function overnightUsView(us: OvernightUs | null | undefined): OvernightUsView | null {
  if (!us) return null
  const available = us.indexes.filter((index) => index.status === 'available' && isFiniteNumber(index.close))
  const fresh = available.filter((index) => FRESH.has(index.freshness ?? ''))
  const lead = fresh.length === 0
    ? OVERNIGHT_US_PENDING
    : fresh.every((index) => index.freshness === 'us_market_closed') ? OVERNIGHT_US_CLOSED : null
  if (available.length === 0) return { lead, date: null, items: [] }
  const days = [...new Set(available.map((index) => index.trading_date))]
  const common = days.length === 1 ? formatDate(days[0]) : null
  return {
    lead,
    date: common,
    items: us.indexes.map((index) => ({
      ...overnightUsItem(index),
      date: common || index.status !== 'available' ? null : formatDate(index.trading_date),
      // With the lead 美股尚未更新 the whole line is not current; it says so once.
      stale: lead !== OVERNIGHT_US_PENDING && index.status === 'available' && index.freshness === 'stale',
      current: index.status === 'available' && FRESH.has(index.freshness ?? ''),
    })),
  }
}

// The US indexes a candidate row shows (overnight_us_links, e.g. SOX for the semiconductor groups): those with a close.
export function candidateOvernightLinks(item: Pick<CandidateItem, 'overnight_us_links'>, view: OvernightUsView | null): OvernightUsItem[] {
  if (!view) return []
  const links = item.overnight_us_links ?? []
  return view.items.filter((entry) => links.includes(entry.symbol) && entry.text !== '未取得')
}
