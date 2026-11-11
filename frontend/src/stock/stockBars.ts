import type { EChartsOption } from 'echarts'

import type { ChangeTone } from '../components/ui/Stat'
import { formatDay, formatTaipeiMinute } from '../dates'
import { noPreviousCloseText } from '../marketChange'
import type { CandidateMarket, IndicatorField, StockBarRow, StockBarsInterval, StockBarsResponse, StrategyBoardRow } from '../types'
import { formatTableVolume, isVerifiedShareSource } from '../units'

// Pure helpers for the stock page K-line, indicator panels and header quote (bars API, docs/spec/indicators.md).

export const STOCK_BARS_LIMIT = 250
// The bars API's largest `limit` (backend app.stock_bars.MAX_LIMIT): 「全部」 asks for it when 250 bars do not reach back.
export const STOCK_BARS_MAX_LIMIT = 1500
// The bars API price basis this page explains (backend app.indicators.PRICE_BASIS; v2 since Issue 394).
export const PRICE_BASIS = 'as_of_date_raw_basis/v2'

export function stockBarsPath(exchange: string, symbol: string, interval: StockBarsInterval, limit = STOCK_BARS_LIMIT): string {
  const query = new URLSearchParams({ interval, limit: String(limit) })
  return `/stocks/${encodeURIComponent(exchange)}/${encodeURIComponent(symbol)}/bars?${query.toString()}`
}

export const INTERVALS: ReadonlyArray<{ id: StockBarsInterval; label: string }> = [
  { id: 'day', label: '日K' },
  { id: 'week', label: '週K' },
]

export type MaField = 'ma5' | 'ma10' | 'ma20' | 'ma60' | 'ma120'
export const MA_LINES: ReadonlyArray<{ field: MaField; label: string; color: 'ma5' | 'ma10' | 'ma20' | 'ma60' | 'ma120' }> = [
  { field: 'ma5', label: 'MA5', color: 'ma5' },
  { field: 'ma10', label: 'MA10', color: 'ma10' },
  { field: 'ma20', label: 'MA20', color: 'ma20' },
  { field: 'ma60', label: 'MA60', color: 'ma60' },
  { field: 'ma120', label: 'MA120', color: 'ma120' },
]

export type IndicatorPanelId = 'macd' | 'rsi' | 'kd' | 'boll'
export const INDICATOR_PANELS: ReadonlyArray<{ id: IndicatorPanelId; label: string; fields: readonly IndicatorField[] }> = [
  { id: 'macd', label: 'MACD', fields: ['macd_dif', 'macd_signal', 'macd_hist'] },
  { id: 'rsi', label: 'RSI', fields: ['rsi6', 'rsi12'] },
  { id: 'kd', label: 'KD', fields: ['kd_k', 'kd_d'] },
  { id: 'boll', label: '布林', fields: ['boll_mid', 'boll_upper', 'boll_lower'] },
]

const FIELD_LABELS: Record<IndicatorField, string> = {
  ma5: 'MA5', ma10: 'MA10', ma20: 'MA20', ma60: 'MA60', ma120: 'MA120',
  macd_dif: 'DIF', macd_signal: 'DEA', macd_hist: 'MACD 柱',
  rsi6: 'RSI6', rsi12: 'RSI12',
  kd_k: 'K', kd_d: 'D',
  boll_mid: '中軌', boll_upper: '上軌', boll_lower: '下軌',
  vol_ma5: '量 MA5', vol_ma20: '量 MA20',
}

export function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

// A candle is drawn only for a traded day with finite positive, self-consistent OHLC; anything else stays a gap.
export function isDrawableBar(bar: StockBarRow | undefined | null): bar is StockBarRow & { open: number; high: number; low: number; close: number } {
  if (!bar || bar.is_suspended === true) return false
  const { open, high, low, close } = bar
  return isFiniteNumber(open) && isFiniteNumber(high) && isFiniteNumber(low) && isFiniteNumber(close)
    && open > 0 && high > 0 && low > 0 && close > 0
    && high >= Math.max(open, close) && low <= Math.min(open, close)
}

// A traded day the source gave a close without open/high/low (Issue 552/547): no candle, but its close is real.
export function isCloseOnlyBar(bar: StockBarRow | undefined | null): bar is StockBarRow & { close: number } {
  return !!bar && bar.is_suspended !== true && !isDrawableBar(bar) && !!bar.price_reason && isFiniteNumber(bar.close) && bar.close > 0
}

// A series whose source publishes the close only (FRED's US index rows, Issue 547): every bar is close-only, so the
// chart draws a close line instead of candles and says so.
export const isCloseOnlySeries = (bars: readonly StockBarRow[]) => bars.length > 0 && bars.every(isCloseOnlyBar)
export const CLOSE_ONLY_NOTE = '來源只提供收盤價：畫收盤線，不畫 K 棒與成交量；KD 與量均線不計算'

export function barSources(bar: StockBarRow): string[] {
  if (Array.isArray(bar.sources)) return bar.sources.filter((source): source is string => typeof source === 'string' && source.length > 0)
  return typeof bar.source === 'string' && bar.source ? [bar.source] : []
}

// Index and futures daily bars (Issue 552): the TAIEX close-only rows, the monthly index reports and TAIFEX open data.
export const INDEX_BAR_SOURCES: ReadonlySet<string> = new Set(['twse_index_ohlcv', 'tpex_index_ohlcv'])
// TX near-month bars (Issue 590): the OpenAPI daily collect and the website futDataDown history (#563, gap fill #586).
export const FUTURES_BAR_SOURCES: ReadonlySet<string> = new Set(['taifex_daily_futures', 'taifex_futdatadown'])
// The US index bars: FinMind since Issue 568; FRED's close-only rows (Issue 547), Federal Reserve Bank of St. Louis.
export const FINMIND_US_INDEX_SOURCE = 'finmind_us_index'
export const FRED_BAR_SOURCE = 'fred_close'
// Sources whose volume is an index's member shares (億股): the Taiwan index reports and FinMind's US indexes
// (Issue 568 decision 6729561612; a vendor's sum over the members, not comparable across indexes).
export const INDEX_SHARE_SOURCES: ReadonlySet<string> = new Set([...INDEX_BAR_SOURCES, FINMIND_US_INDEX_SOURCE])

export function sourceName(source: string): string {
  if (source === 'twse' || source === 'twse_index' || source === 'twse_index_ohlcv') return '臺灣證券交易所'
  if (source === 'tpex' || source === 'tpex_index_ohlcv') return '證券櫃檯買賣中心'
  if (FUTURES_BAR_SOURCES.has(source)) return '臺灣期貨交易所'
  if (source === FINMIND_US_INDEX_SOURCE) return 'FinMind'
  if (source === FRED_BAR_SOURCE) return 'FRED（聖路易聯邦準備銀行）'
  return '來源待核實'
}

export function sourcesLabel(sources: readonly string[]): string {
  const names = [...new Set(sources.map(sourceName))]
  return names.length ? names.join('、') : '來源未提供'
}

// `indicators.computed_at` is UTC with its offset (a naive value is read as UTC too); show Taiwan time.
export function formatTaipeiDateTime(value: string | null | undefined): string | null {
  return formatTaipeiMinute(value)
}

// ---- null reasons -------------------------------------------------------------------------------

function intervalUnit(interval: StockBarsInterval): string {
  return interval === 'week' ? '週線' : '日線'
}

export function nullReasonText(code: string | undefined, context: { interval: StockBarsInterval; required?: number | null; barCount?: number | null }): string {
  const unit = intervalUnit(context.interval)
  switch (code) {
    case 'insufficient_bars':
      if (!isFiniteNumber(context.required)) return `${unit}根數不足`
      return isFiniteNumber(context.barCount)
        ? `${unit}不足 ${context.required} 根，現有 ${context.barCount} 根`
        : `${unit}不足 ${context.required} 根`
    case 'suspended': return '停牌，當日不計算'
    case 'invalid_bar': return '當日行情無效，不計算'
    case 'no_price_change': return '期間內收盤沒有漲跌，無法計算'
    case 'synthetic_index': return '指數只有收盤價，高低點與成交量不計算'
    case 'missing_ohlc': return '來源有一天未提供開高低，高低點不計算'
    case 'missing_volume': return '來源有一天未提供成交量，不計算'
    case 'not_computed': return '指標尚未計算'
    default: return '原因待核實'
  }
}

export type FieldsState =
  | { kind: 'value' }
  | { kind: 'not_computed'; reason: string }
  | { kind: 'missing'; reason: string }

// State of a group of fields on one bar: any finite value counts as shown; otherwise the reasons explain why.
export function fieldsState(bar: StockBarRow | undefined, fields: readonly IndicatorField[], response: Pick<StockBarsResponse, 'interval' | 'indicators'>): FieldsState {
  if (!bar) return { kind: 'missing', reason: '來源未提供行情' }
  if (fields.some((field) => isFiniteNumber(bar[field]))) return { kind: 'value' }
  const codes = fields.map((field) => bar.reasons?.[field])
  if (codes.every((code) => code === 'not_computed')) return { kind: 'not_computed', reason: `${formatDay(bar.date) ?? bar.date} 的指標尚未由批次計算` }
  const insufficient = fields.filter((_, index) => codes[index] === 'insufficient_bars')
  if (insufficient.length) {
    const required = insufficient.map((field) => response.indicators.required_bars[field]).filter(isFiniteNumber)
    return { kind: 'missing', reason: nullReasonText('insufficient_bars', { interval: response.interval, required: required.length ? Math.max(...required) : null, barCount: bar.bar_count }) }
  }
  return { kind: 'missing', reason: nullReasonText(codes.find((code) => code !== 'not_computed'), { interval: response.interval }) }
}

export type PanelState =
  | { kind: 'chart'; note: string | null }
  | { kind: 'empty' | 'not_computed'; title: string; reason: string }

// The panel follows the latest bar: values there draw the panel; a series that has no value anywhere shows
// 「無資料」 with the reason, or 「指標尚未計算」 when the batch has not written it yet.
export function indicatorPanelState(response: StockBarsResponse, panelId: IndicatorPanelId): PanelState {
  const panel = INDICATOR_PANELS.find((item) => item.id === panelId) ?? INDICATOR_PANELS[0]
  const latest = response.bars[response.bars.length - 1]
  if (!latest) return { kind: 'empty', title: '無資料', reason: '來源未提供行情' }
  const state = fieldsState(latest, panel.fields, response)
  if (state.kind === 'value') return { kind: 'chart', note: null }
  const hasAny = response.bars.some((bar) => panel.fields.some((field) => isFiniteNumber(bar[field])))
  if (hasAny) return { kind: 'chart', note: `${formatDay(latest.date) ?? latest.date} ${panel.label}無資料：${state.reason}` }
  if (state.kind === 'not_computed') return { kind: 'not_computed', title: '指標尚未計算', reason: state.reason }
  return { kind: 'empty', title: '無資料', reason: state.reason }
}

// One line per moving average that has no value on the latest bar, e.g. 「MA120 無資料：日線不足 120 根，現有 80 根」.
export function maNotes(response: StockBarsResponse, visible: ReadonlySet<MaField>): string[] {
  const latest = response.bars[response.bars.length - 1]
  if (!latest) return []
  const notes: string[] = []
  for (const line of MA_LINES) {
    if (!visible.has(line.field)) continue
    const state = fieldsState(latest, [line.field], response)
    if (state.kind !== 'value') notes.push(`${line.label} ${state.kind === 'not_computed' ? '指標尚未計算' : '無資料'}：${state.reason}`)
  }
  return notes
}

// ---- header quote -------------------------------------------------------------------------------

export type StockQuote = {
  close: number | null
  change: number | null
  changePct: number | null
  date: string | null
  sources: string[]
  tone: ChangeTone
  digits: number
  // Why there is no change, in the candidate page's words (#475); null when there is one or the reason is unknown.
  noChange: string | null
}

export function changeTone(value: number | null | undefined): ChangeTone {
  if (!isFiniteNumber(value) || value === 0) return 'flat'
  return value > 0 ? 'up' : 'down'
}

// Decimal places follow the TWSE/TPEx stock tick ladder (0.01 / 0.05 under 50, 0.1 / 0.5 under 500, whole yuan above);
// ETFs and indexes (published in points with two decimals, Issue 549) keep 2.
export function priceDigits(price: number | null | undefined, instrumentType?: string | null): number {
  const type = instrumentType?.toLowerCase()
  // TX trades in whole index points (Issue 552).
  if (type === 'futures') return 0
  if (type === 'etf' || type === 'index') return 2
  if (!isFiniteNumber(price) || price < 50) return 2
  return price < 500 ? 1 : 0
}

// Price axis labels from 1,000 up drop the decimals: 「8,000.00」 (the US indexes, Issue 547) is cut by the 64px gutter on
// phones. Stocks of 500 and up already show no decimals, so this changes index and ETF axes only.
export const axisDigits = (value: number, digits: number) => Math.abs(value) >= 1000 ? 0 : digits

export function formatPrice(value: number | null | undefined, digits: number): string {
  if (!isFiniteNumber(value)) return '待核實'
  return value.toLocaleString('zh-TW', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function formatSignedPrice(value: number | null | undefined, digits: number): string {
  if (!isFiniteNumber(value)) return '待核實'
  const text = formatPrice(Math.abs(value), digits)
  return value > 0 ? `+${text}` : value < 0 ? `-${text}` : text
}

export function formatSignedPercent(ratio: number | null | undefined): string {
  if (!isFiniteNumber(ratio) || !Number.isFinite(ratio * 100)) return '待核實'
  const text = Math.abs(ratio * 100).toFixed(2)
  return ratio > 0 ? `+${text}%` : ratio < 0 ? `-${text}%` : `${text}%`
}

// Latest traded close, and its change against the directly preceding row only when that row is also a traded
// day from the same source (UI_COPY_SPEC §10.1: no adjacent trusted previous close → 漲跌待核實).
// When the bars API's latest_change for the same day says the stock has no close on the previous verified session
// (no_previous_close, first_trading_day), no older row stands in and the header shows the candidate page's words (#475).
export function stockQuote(bars: readonly StockBarRow[], instrumentType?: string | null, latestChange?: CandidateMarket | null): StockQuote {
  let index = bars.length - 1
  while (index >= 0 && !isDrawableBar(bars[index])) index--
  const latest = index >= 0 ? bars[index] : undefined
  if (!latest || !isDrawableBar(latest)) return { close: null, change: null, changePct: null, date: null, sources: [], tone: 'flat', digits: 2, noChange: null }
  const previous = bars[index - 1]
  const sources = barSources(latest)
  const digits = priceDigits(latest.close, instrumentType)
  const noChange = latestChange?.trading_date === latest.date ? noPreviousCloseText(latestChange.change_status) : null
  if (noChange) return { close: latest.close, change: null, changePct: null, date: latest.date, sources, tone: 'flat', digits, noChange }
  const sameSource = previous ? barSources(previous).join('+') === sources.join('+') : false
  const change = isDrawableBar(previous) && sameSource ? Number((latest.close - previous.close).toFixed(6)) : null
  const changePct = change != null && isDrawableBar(previous) ? change / previous.close : null
  return { close: latest.close, change, changePct, date: latest.date, sources, tone: changeTone(change), digits, noChange: null }
}

// ---- chart --------------------------------------------------------------------------------------

export type ChartTheme = {
  up: string; down: string; flat: string
  primary: string; accent: string; warning: string
  text: string; muted: string; subtle: string
  grid: string; border: string; cardBg: string
  fontMono: string
  ma5: string; ma10: string; ma20: string; ma60: string; ma120: string
}

// zrender 5.6 (under ECharts) reads Chromium Edge's "Edg/" as the old EdgeHTML Edge: it then listens to pointer events
// only and drops every touch pointermove, so on a touch screen the crosshair does not follow the finger and a drag does
// not pan (Issue 600, headless Edge with touch). This puts Chromium Edge on Chrome's path (touch events when the screen
// has touch, mouse events otherwise). It changes the shared detection object before any chart is created.
export type InputDetection = { browser: { newEdge: boolean }; touchEventsSupported: boolean; pointerEventsSupported: boolean }
export function preferChromeInputPath(detected: InputDetection, hasTouch: boolean): boolean {
  if (!detected.browser.newEdge || !detected.pointerEventsSupported) return false
  detected.touchEventsSupported = hasTouch
  detected.pointerEventsSupported = false
  return true
}

// ECharts draws on canvas and cannot resolve var(); the component reads these tokens at runtime (DESIGN_SYSTEM §6).
export const CHART_THEME_TOKENS: Record<keyof ChartTheme, string> = {
  up: '--color-up', down: '--color-down', flat: '--color-flat',
  primary: '--color-primary', accent: '--color-accent', warning: '--color-warning',
  text: '--color-text', muted: '--color-text-muted', subtle: '--color-text-subtle',
  grid: '--chart-grid', border: '--color-border', cardBg: '--color-bg-card',
  fontMono: '--font-mono',
  ma5: '--chart-ma5', ma10: '--chart-ma10', ma20: '--chart-ma20', ma60: '--chart-ma60', ma120: '--chart-ma120',
}

export function readChartTheme(read: (token: string) => string): ChartTheme {
  const entries = Object.entries(CHART_THEME_TOKENS).map(([key, token]) => [key, read(token).trim()])
  return Object.fromEntries(entries) as ChartTheme
}

export type ChartLayout = {
  main: { top: number; height: number }
  volume: { top: number; height: number }
  // Gap above the indicator grid that holds the indicator tabs.
  tabsTop: number
  indicator: { top: number; height: number }
  sliderTop: number
  height: number
  left: number
  right: number
}

// The indicator panel is 35% of the main K-line grid (DESIGN_SYSTEM §6).
export function chartLayout(mainHeight: number): ChartLayout {
  const main = { top: 16, height: mainHeight }
  const volume = { top: main.top + main.height + 20, height: Math.round(mainHeight * 0.24) }
  const tabsTop = volume.top + volume.height + 6
  const indicator = { top: tabsTop + 40, height: Math.round(mainHeight * 0.35) }
  const sliderTop = indicator.top + indicator.height + 30
  return { main, volume, tabsTop, indicator, sliderTop, height: sliderTop + 28, left: 64, right: 16 }
}

// The dataZoom window: a range button sets bar indexes (startValue/endValue), a manual zoom keeps ECharts' own percents
// so dragging the slider is not snapped back to whole bars.
export type ChartZoom = { startValue: number; endValue: number } | { start: number; end: number }

// ---- display range (Issue 600) ------------------------------------------------------------------

export type BarsRange = '1m' | '3m' | '6m' | '1y' | 'all'
export const BAR_RANGES: ReadonlyArray<{ id: BarsRange; label: string; months: number | null }> = [
  { id: '1m', label: '1M', months: 1 },
  { id: '3m', label: '3M', months: 3 },
  { id: '6m', label: '6M', months: 6 },
  { id: '1y', label: '1Y', months: 12 },
  { id: 'all', label: '全部', months: null },
]
export const DEFAULT_BARS_RANGE: BarsRange = '6m'

// A range button (kept across 日K／週K and across series) or a manual zoom: its percents on the bars it was made on
// (`basis`), and the dates they cover, which carry the window over to another interval or series.
export type BarsView =
  | { range: BarsRange }
  | { range: null; start: number; end: number; from: string; to: string; basis: string }

export function barsBasis(response: Pick<StockBarsResponse, 'interval' | 'bars'>): string {
  const bars = response.bars
  return `${response.interval}:${bars.length}:${bars[0]?.date ?? ''}:${bars[bars.length - 1]?.date ?? ''}`
}

// The first day a range shows: the latest bar's date moved back whole calendar months (month end clamps, 03/31 − 1M =
// 02/28); null for 全部 or a date that does not parse.
export function rangeCutoff(latest: string | undefined, range: BarsRange): string | null {
  const months = BAR_RANGES.find((item) => item.id === range)?.months ?? null
  const match = latest ? /^(\d{4})-(\d{2})-(\d{2})/.exec(latest) : null
  if (months == null || !match) return null
  const [year, month, day] = [Number(match[1]), Number(match[2]) - 1, Number(match[3])]
  const target = new Date(Date.UTC(year, month - months, 1))
  const lastDay = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate()
  target.setUTCDate(Math.min(day, lastDay))
  return target.toISOString().slice(0, 10)
}

const barStart = (bar: StockBarRow) => bar.week_start ?? bar.date

// Bar indexes of a view on these bars. A range starts at the first bar on or after its cutoff and ends at the latest
// bar; when the bars do not reach back that far it shows them all. A manual zoom on the same bars keeps its percents;
// on other bars (the other interval, another series) it maps its dates, and falls back to the default range when the
// other bars have none of those dates (加權「全部」 dragged to 2023, then S&P 500 with its 250 bars from 2025).
export function zoomForView(response: Pick<StockBarsResponse, 'interval' | 'bars'>, view: BarsView): ChartZoom {
  const bars = response.bars
  const last = Math.max(0, bars.length - 1)
  if (view.range === null) {
    if (view.basis === barsBasis(response)) return { start: view.start, end: view.end }
    const first = bars.findIndex((bar) => bar.date >= view.from)
    if (first < 0 || barStart(bars[first]) > view.to) return zoomForView(response, { range: DEFAULT_BARS_RANGE })
    let end = last
    while (end > first && barStart(bars[end]) > view.to) end--
    return { startValue: first, endValue: end }
  }
  const cutoff = rangeCutoff(bars[last]?.date, view.range)
  const first = cutoff == null ? 0 : bars.findIndex((bar) => bar.date >= cutoff)
  return { startValue: Math.max(0, first), endValue: last }
}

// The first and last bar index a window shows (ECharts maps percents onto the category extent [0, count − 1]).
export function zoomBars(count: number, zoom: ChartZoom): [number, number] {
  const span = Math.max(0, count - 1)
  if ('startValue' in zoom) return [zoom.startValue, zoom.endValue]
  const first = Math.min(span, Math.ceil(zoom.start / 100 * span - 1e-6))
  return [first, Math.max(first, Math.floor(zoom.end / 100 * span + 1e-6))]
}

// The view a dataZoom event leaves (a drag, wheel or pinch): no range is selected any more. An event that leaves the
// same bars in view (`current`) changes nothing: ECharts also reports a vertical swipe over the chart, whose sideways
// wobble moves the window by less than a bar, and that must not clear the range (#600 review).
export function viewFromZoomEvent(response: Pick<StockBarsResponse, 'interval' | 'bars'>, event: unknown, current?: ChartZoom): BarsView | null {
  const payload = event && typeof event === 'object' ? event as Record<string, unknown> : null
  const batch = Array.isArray(payload?.batch) ? payload.batch[0] as Record<string, unknown> | undefined : undefined
  const source = batch ?? payload
  const bars = response.bars
  if (!source || !bars.length || !isFiniteNumber(source.start) || !isFiniteNumber(source.end)) return null
  const start = Math.max(0, Math.min(100, source.start))
  const end = Math.max(start, Math.min(100, source.end))
  const [first, lastIndex] = zoomBars(bars.length, { start, end })
  if (current) {
    const [shownFirst, shownLast] = zoomBars(bars.length, current)
    if (shownFirst === first && shownLast === lastIndex) return null
  }
  return { range: null, start, end, from: barStart(bars[first]), to: bars[lastIndex].date, basis: barsBasis(response) }
}

// Direction lock for a touch on the chart (#600 review): once the finger has moved SWIPE_LOCK_PX, a mostly vertical
// gesture is a page scroll, and the dataZoom events it causes (a few px of sideways wobble pan the chart) are ignored.
export const SWIPE_LOCK_PX = 8
export function swipeAxis(dx: number, dy: number): 'vertical' | 'horizontal' | null {
  if (Math.hypot(dx, dy) < SWIPE_LOCK_PX) return null
  return Math.abs(dy) > Math.abs(dx) ? 'vertical' : 'horizontal'
}

// Whether a range reaches before the loaded bars while the API may hold older ones (the response is a full page under
// the API maximum): 全部 always, a range only when its cutoff is earlier than the first loaded bar.
export function needsMoreBars(response: Pick<StockBarsResponse, 'bars' | 'count' | 'limit'>, view: BarsView): boolean {
  if (view.range === null || response.limit >= STOCK_BARS_MAX_LIMIT || response.count < response.limit) return false
  const bars = response.bars
  if (!bars.length) return false
  const cutoff = rangeCutoff(bars[bars.length - 1].date, view.range)
  return cutoff == null || bars[0].date > cutoff
}


// ---- the longer request of 全部 (Issue 600) -----------------------------------------------------
// State of the one `limit=1500` request per series: pending (key only), loaded (data) or failed (error).

export type LongerBars = { key: string; data?: StockBarsResponse; error?: unknown }

export function longerBarsKey(response: Pick<StockBarsResponse, 'instrument' | 'interval' | 'data_as_of'>): string {
  return `${response.instrument.exchange}/${response.instrument.symbol}/${response.interval}/${response.data_as_of ?? ''}`
}

// Send it when wanted and this series has no request yet (pending, loaded or failed all block a second one).
export const shouldFetchLonger = (state: LongerBars | null, key: string, wanted: boolean) => wanted && state?.key !== key

// A reply lands only on its own series while that request is still pending; anything else is dropped.
export function settleLonger(state: LongerBars | null, key: string, result: { data: StockBarsResponse } | { error: unknown }): LongerBars | null {
  if (!state || state.key !== key || state.data || state.error !== undefined) return state
  return 'data' in result ? { key, data: result.data } : { key, error: result.error ?? new Error('load failed') }
}

// Pressing a range button after a failure clears it, so the request is sent again (#600 review).
export const retryLonger = (state: LongerBars | null): LongerBars | null => state && state.error !== undefined ? null : state

export function longerStatus(state: LongerBars | null, key: string, wanted: boolean): { data?: StockBarsResponse; loading: boolean; failed: boolean } {
  const current = state && state.key === key ? state : null
  return {
    data: current?.data,
    loading: wanted && !!current && !current.data && current.error === undefined,
    failed: wanted && current?.error !== undefined,
  }
}
// How a volume is shown (Issue 552): stocks in lots (張); an index's whole-market shares in 億股; TX in contracts (口).
// A source whose unit is not verified (the close-only TAIEX rows, volume 0) shows nothing.
export type VolumeKind = 'lots' | 'index_shares' | 'contracts' | 'unverified'
export const VOLUME_UNITS: Record<VolumeKind, string> = { lots: '張', index_shares: '億股', contracts: '口', unverified: '張' }

export function volumeKind(sources: readonly string[]): VolumeKind {
  if (!sources.length) return 'unverified'
  if (sources.every(isVerifiedShareSource)) return 'lots'
  if (sources.every((source) => INDEX_SHARE_SOURCES.has(source))) return 'index_shares'
  if (sources.every((source) => FUTURES_BAR_SOURCES.has(source))) return 'contracts'
  return 'unverified'
}

export function formatBarVolume(bar: StockBarRow): string {
  const sources = barSources(bar)
  const kind = volumeKind(sources)
  if (kind === 'lots') return formatTableVolume(bar.volume, sources[0])
  if (!isFiniteNumber(bar.volume) || bar.volume < 0) return ''
  if (kind === 'index_shares') return (bar.volume / 1e8).toLocaleString('zh-TW', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  if (kind === 'contracts') return bar.volume.toLocaleString('zh-TW', { maximumFractionDigits: 0 })
  return ''
}

// Volume axis labels stay inside the 64px gutter on phones (PR 553 review): 萬／億 above 10,000.
export function compactCount(value: number): string {
  const abs = Math.abs(value)
  const short = (number: number) => number.toLocaleString('zh-TW', { maximumFractionDigits: 1 })
  if (abs >= 1e8) return `${short(value / 1e8)}億`
  if (abs >= 1e4) return `${short(value / 1e4)}萬`
  return value.toLocaleString('zh-TW', { maximumFractionDigits: 0 })
}

function volumeAxisLabel(kind: VolumeKind, value: number): string {
  if (kind === 'lots') return compactCount(value / 1000)
  if (kind === 'index_shares') return (value / 1e8).toLocaleString('zh-TW', { maximumFractionDigits: 0 })
  return compactCount(value)
}

function escapeHtml(value: unknown): string {
  return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')
}

function indicatorNumber(value: number | null | undefined, digits = 2): string {
  return isFiniteNumber(value) ? value.toLocaleString('zh-TW', { minimumFractionDigits: digits, maximumFractionDigits: digits }) : '—'
}

export function formatBarsTooltip(response: StockBarsResponse, index: number, panelId: IndicatorPanelId, visibleMa: ReadonlySet<MaField>, digits: number): string {
  const bar = response.bars[index]
  if (!bar) return ''
  const heading = response.interval === 'week' && bar.week_start
    ? `${formatDay(bar.week_start) ?? bar.week_start}～${formatDay(bar.week_end ?? bar.date) ?? bar.week_end ?? bar.date}（${bar.trading_days ?? '—'} 個交易日）`
    : formatDay(bar.date) ?? bar.date
  const lines = [`<strong>${escapeHtml(heading)}</strong>`]
  if (isCloseOnlyBar(bar)) {
    lines.push(`收 ${escapeHtml(formatPrice(bar.close, digits))}（來源未提供開高低）`)
  } else if (!isDrawableBar(bar)) {
    lines.push(bar.is_suspended ? '停牌，無 K 線' : '此根行情不完整，不繪製')
  } else {
    lines.push(
      `開 ${escapeHtml(formatPrice(bar.open, digits))}　高 ${escapeHtml(formatPrice(bar.high, digits))}`,
      `低 ${escapeHtml(formatPrice(bar.low, digits))}　收 ${escapeHtml(formatPrice(bar.close, digits))}`,
      `成交量（${VOLUME_UNITS[volumeKind(barSources(bar))]}） ${escapeHtml(formatBarVolume(bar) || (isFiniteNumber(bar.volume) ? '單位待核實' : '來源未提供'))}`,
    )
  }
  for (const line of MA_LINES) {
    if (visibleMa.has(line.field)) lines.push(`${line.label} ${escapeHtml(indicatorNumber(bar[line.field], digits))}`)
  }
  const panel = INDICATOR_PANELS.find((item) => item.id === panelId) ?? INDICATOR_PANELS[0]
  lines.push(panel.fields.map((field) => `${FIELD_LABELS[field]} ${escapeHtml(indicatorNumber(bar[field]))}`).join('　'))
  // Only these fixed tags are emitted; every dynamic value above is escaped.
  return lines.join('<br/>')
}

function seriesValues(bars: readonly StockBarRow[], field: IndicatorField): Array<number | '-'> {
  return bars.map((bar) => isFiniteNumber(bar[field]) ? bar[field] as number : '-')
}

type LineSpec = { name: string; field: IndicatorField; color: string; width?: number; dashed?: boolean }

function lineSeries(bars: readonly StockBarRow[], axis: number, spec: LineSpec, extra: Record<string, unknown> = {}) {
  return {
    name: spec.name,
    type: 'line' as const,
    xAxisIndex: axis,
    yAxisIndex: axis,
    data: seriesValues(bars, spec.field),
    showSymbol: false,
    connectNulls: false,
    lineStyle: { color: spec.color, width: spec.width ?? 1.5, type: spec.dashed ? 'dashed' as const : 'solid' as const },
    itemStyle: { color: spec.color },
    emphasis: { disabled: true },
    ...extra,
  }
}

function referenceLines(values: readonly number[], theme: ChartTheme) {
  return {
    silent: true,
    symbol: 'none',
    label: { show: false },
    lineStyle: { color: theme.subtle, type: 'dashed' as const, width: 1 },
    data: values.map((value) => ({ yAxis: value })),
  }
}

function indicatorSeries(bars: readonly StockBarRow[], panelId: IndicatorPanelId, theme: ChartTheme): unknown[] {
  if (panelId === 'macd') {
    return [
      {
        name: 'MACD 柱', type: 'bar', xAxisIndex: 2, yAxisIndex: 2, barMaxWidth: 6,
        data: bars.map((bar) => isFiniteNumber(bar.macd_hist) ? { value: bar.macd_hist, itemStyle: { color: bar.macd_hist >= 0 ? theme.up : theme.down } } : '-'),
      },
      lineSeries(bars, 2, { name: 'DIF', field: 'macd_dif', color: theme.primary }),
      lineSeries(bars, 2, { name: 'DEA', field: 'macd_signal', color: theme.accent }),
    ]
  }
  if (panelId === 'rsi') {
    return [
      lineSeries(bars, 2, { name: 'RSI6', field: 'rsi6', color: theme.primary }, { markLine: referenceLines([30, 70], theme) }),
      lineSeries(bars, 2, { name: 'RSI12', field: 'rsi12', color: theme.accent }),
    ]
  }
  if (panelId === 'kd') {
    return [
      lineSeries(bars, 2, { name: 'K', field: 'kd_k', color: theme.primary }, { markLine: referenceLines([20, 80], theme) }),
      lineSeries(bars, 2, { name: 'D', field: 'kd_d', color: theme.accent }),
    ]
  }
  return [
    {
      name: '收盤', type: 'line', xAxisIndex: 2, yAxisIndex: 2, showSymbol: false, connectNulls: false, emphasis: { disabled: true },
      data: bars.map((bar) => isDrawableBar(bar) || isCloseOnlyBar(bar) ? bar.close : '-'), lineStyle: { color: theme.flat, width: 1 }, itemStyle: { color: theme.flat },
    },
    lineSeries(bars, 2, { name: '中軌', field: 'boll_mid', color: theme.primary }),
    lineSeries(bars, 2, { name: '上軌', field: 'boll_upper', color: theme.accent }),
    lineSeries(bars, 2, { name: '下軌', field: 'boll_lower', color: theme.accent }),
  ]
}

// The rule levels of the strategy that holds on the data day, drawn on the price pane (DESIGN_SYSTEM §6 規則價位線):
// where to enter, where the condition fails, where the first target is. Prices are the signal's own, on the chart's raw basis.
export type ChartLevels = { entry: number; stop: number; target: number }
export const CHART_LEVEL_LABELS = { entry: '進場', stop: '停損', target: '目標' } as const

// Only a conditional row with a complete, ordered set of levels draws lines: an observation's 觀察價位 are not levels to
// act on (PRODUCT_SPEC §2), and a line from half a set would read as a level that is not there.
export function chartLevels(row: StrategyBoardRow | null | undefined): ChartLevels | null {
  if (!row || row.status !== 'conditional' || row.levels?.kind !== 'actionable') return null
  const levels = row.levels
  const zone = isFiniteNumber(levels.entry_low) && isFiniteNumber(levels.entry_high) ? (levels.entry_low + levels.entry_high) / 2 : null
  const entry = levels.entry_type === 'breakout' ? levels.trigger_price : levels.reference_entry ?? zone
  const stop = levels.invalid_price
  const target = levels.target_1
  if (!isFiniteNumber(entry) || !isFiniteNumber(stop) || !isFiniteNumber(target)) return null
  return stop > 0 && stop < entry && entry < target ? { entry, stop, target } : null
}

// The line under the chart: the three prices again as text, for a reader who cannot see the canvas.
export function levelsNote(levels: ChartLevels, digits: number): string {
  const price = (value: number) => formatPrice(value, digits)
  return `規則價位線：${CHART_LEVEL_LABELS.entry} ${price(levels.entry)} 元（虛線）、${CHART_LEVEL_LABELS.stop} ${price(levels.stop)} 元、${CHART_LEVEL_LABELS.target} ${price(levels.target)} 元；條件成立當日的價位，不是成交價。`
}

function levelMarks(levels: ChartLevels, theme: ChartTheme, digits: number) {
  const line = (key: keyof ChartLevels, color: string, type: 'solid' | 'dashed') => ({
    name: CHART_LEVEL_LABELS[key],
    yAxis: levels[key],
    lineStyle: { color, type, width: 1.5 },
    label: { formatter: `${CHART_LEVEL_LABELS[key]} ${formatPrice(levels[key], digits)}`, color, position: 'insideStartTop' as const, fontFamily: theme.fontMono, fontSize: 12, fontWeight: 600 },
  })
  const band = (name: string, from: number, to: number, color: string) => [{ name, yAxis: from, itemStyle: { color, opacity: 0.1 } }, { yAxis: to }]
  return {
    markLine: {
      silent: true, symbol: 'none', animation: false,
      data: [line('target', theme.primary, 'solid'), line('entry', theme.text, 'dashed'), line('stop', theme.warning, 'solid')],
    },
    markArea: {
      silent: true, animation: false, label: { show: false },
      data: [band('目標區間', levels.entry, levels.target, theme.primary), band('風險區間', levels.stop, levels.entry, theme.warning)],
    },
  }
}

export type BarsChartOptions = {
  panel: IndicatorPanelId
  panelState: PanelState
  visibleMa: ReadonlySet<MaField>
  theme: ChartTheme
  layout: ChartLayout
  zoom: ChartZoom
  digits: number
  levels?: ChartLevels | null
}

export function buildBarsChartOption(response: StockBarsResponse, options: BarsChartOptions): EChartsOption {
  const { theme, layout, zoom, digits } = options
  const bars = response.bars
  const dates = bars.map((bar) => formatDay(bar.date) ?? bar.date)
  const axisLabel = { color: theme.muted, fontSize: 12, fontFamily: theme.fontMono }
  const splitLine = { lineStyle: { color: theme.grid } }
  const gridBase = { left: layout.left, right: layout.right }
  const kind = volumeKind(response.sources)
  const xAxis = [0, 1, 2].map((gridIndex) => ({
    type: 'category' as const,
    gridIndex,
    data: dates,
    boundaryGap: true,
    axisLine: { lineStyle: { color: theme.grid } },
    axisTick: { show: false },
    axisLabel: gridIndex === 2 ? { ...axisLabel, hideOverlap: true } : { show: false },
    splitLine: { show: false },
  }))
  const bounded = options.panel === 'rsi' || options.panel === 'kd'
  const levels = options.levels ?? null
  // The price axis reaches the stop and the target, so a line outside the visible bars is still on the pane.
  const priceRange = levels
    ? { min: (extent: { min: number }) => Math.min(extent.min, levels.stop), max: (extent: { max: number }) => Math.max(extent.max, levels.target) }
    : {}
  return {
    animation: false,
    backgroundColor: 'transparent',
    textStyle: { fontFamily: theme.fontMono },
    axisPointer: { link: [{ xAxisIndex: 'all' }], lineStyle: { color: theme.subtle } },
    grid: [
      { ...gridBase, top: layout.main.top, height: layout.main.height },
      { ...gridBase, top: layout.volume.top, height: layout.volume.height },
      { ...gridBase, top: layout.indicator.top, height: layout.indicator.height },
    ],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', lineStyle: { color: theme.subtle }, crossStyle: { color: theme.subtle }, label: { backgroundColor: theme.cardBg, color: theme.text, fontFamily: theme.fontMono } },
      backgroundColor: theme.cardBg,
      borderColor: theme.border,
      borderWidth: 1,
      textStyle: { color: theme.text, fontFamily: theme.fontMono, fontSize: 12 },
      extraCssText: 'border-radius: 8px;',
      // Inside the chart: on a phone the box beside the finger otherwise runs off the screen edge (Issue 600).
      confine: true,
      formatter: (params: unknown) => {
        const entries = Array.isArray(params) ? params : [params]
        const first = entries.find((entry) => entry && typeof entry === 'object' && isFiniteNumber((entry as { dataIndex?: unknown }).dataIndex)) as { dataIndex: number } | undefined
        return first ? formatBarsTooltip(response, first.dataIndex, options.panel, options.visibleMa, digits) : ''
      },
    },
    xAxis,
    yAxis: [
      // Axis labels of 1,000 and up (an index in points, Issue 549/547) drop the decimals so they fit the 64px gutter;
      // the tooltip and the data table keep them.
      { type: 'value', gridIndex: 0, scale: true, ...priceRange, axisLabel: { ...axisLabel, showMinLabel: false, formatter: (value: number) => formatPrice(value, axisDigits(value, digits)) }, splitLine },
      { type: 'value', gridIndex: 1, scale: false, splitNumber: 2, axisLabel: { ...axisLabel, showMaxLabel: false, formatter: (value: number) => volumeAxisLabel(kind, value) }, splitLine },
      bounded
        ? { type: 'value', gridIndex: 2, min: 0, max: 100, interval: 50, axisLabel, splitLine }
        // MACD of an index runs into the thousands: no decimals from 1,000 up, so「-2,000」fits the 64px gutter.
        : { type: 'value', gridIndex: 2, scale: true, splitNumber: 2, axisLabel: { ...axisLabel, formatter: (value: number) => indicatorNumber(value, Math.abs(value) >= 1000 ? 0 : options.panel === 'boll' ? digits : 2) }, splitLine },
    ],
    dataZoom: [
      // preventDefaultMouseMove off: a vertical swipe over the chart scrolls the page on phones (touch-action pan-y, #600).
      { type: 'inside', xAxisIndex: [0, 1, 2], filterMode: 'filter', preventDefaultMouseMove: false, ...zoom },
      {
        type: 'slider', xAxisIndex: [0, 1, 2], filterMode: 'filter', ...zoom,
        top: layout.sliderTop, height: 18, left: layout.left, right: layout.right,
        borderColor: theme.border, fillerColor: theme.grid, backgroundColor: 'transparent',
        dataBackground: { lineStyle: { color: theme.subtle }, areaStyle: { color: theme.grid } },
        handleStyle: { color: theme.muted, borderColor: theme.border },
        textStyle: { color: theme.muted, fontFamily: theme.fontMono, fontSize: 12 },
      },
    ],
    series: [
      {
        name: response.interval === 'week' ? '週K' : '日K',
        type: 'candlestick',
        xAxisIndex: 0,
        barMaxWidth: 14,
        yAxisIndex: 0,
        data: bars.map((bar) => isDrawableBar(bar) ? [bar.open, bar.close, bar.low, bar.high] : ['-', '-', '-', '-']),
        itemStyle: { color: theme.up, color0: theme.down, borderColor: theme.up, borderColor0: theme.down },
        ...(levels ? levelMarks(levels, theme, digits) : {}),
      },
      // A close-only series (Issue 547) has no candle to draw: its closes are one neutral line on the price pane.
      ...(isCloseOnlySeries(bars) ? [{
        name: '收盤', type: 'line' as const, xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, connectNulls: false, emphasis: { disabled: true },
        data: bars.map((bar) => bar.close), lineStyle: { color: theme.text, width: 1.5 }, itemStyle: { color: theme.text },
      }] : []),
      ...MA_LINES.filter((line) => options.visibleMa.has(line.field)).map((line) => lineSeries(bars, 0, { name: line.label, field: line.field, color: theme[line.color], width: 1.2 })),
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        barMaxWidth: 10,
        // Same up/down color as the candle at 60% transparency (DESIGN_SYSTEM §6).
        data: bars.map((bar) => isDrawableBar(bar) && isFiniteNumber(bar.volume) && bar.volume >= 0
          ? { value: bar.volume, itemStyle: { color: bar.close >= bar.open ? theme.up : theme.down, opacity: 0.4 } }
          : '-'),
      },
      ...(options.panelState.kind === 'chart' ? indicatorSeries(bars, options.panel, theme) : []),
    ] as EChartsOption['series'],
  }
}
