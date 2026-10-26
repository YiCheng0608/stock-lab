import type { EChartsOption } from 'echarts'

import type { ChangeTone } from '../components/ui/Stat'
import { formatDay, formatTaipeiMinute } from '../dates'
import type { IndicatorField, StockBarRow, StockBarsInterval, StockBarsResponse } from '../types'
import { formatTableVolume, isVerifiedShareSource } from '../units'

// Pure helpers for the stock page K-line, indicator panels and header quote (bars API, docs/V1_SPEC.md 技術指標).

export const STOCK_BARS_LIMIT = 250
// Bars visible when a series first renders; the rest of the 250 stay reachable through dataZoom.
export const DEFAULT_VISIBLE_BARS = 120

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

export function barSources(bar: StockBarRow): string[] {
  if (Array.isArray(bar.sources)) return bar.sources.filter((source): source is string => typeof source === 'string' && source.length > 0)
  return typeof bar.source === 'string' && bar.source ? [bar.source] : []
}

export function sourceName(source: string): string {
  if (source === 'twse') return '臺灣證券交易所'
  if (source === 'tpex') return '證券櫃檯買賣中心'
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
}

export function changeTone(value: number | null | undefined): ChangeTone {
  if (!isFiniteNumber(value) || value === 0) return 'flat'
  return value > 0 ? 'up' : 'down'
}

// Decimal places follow the TWSE/TPEx stock tick ladder (0.01 / 0.05 under 50, 0.1 / 0.5 under 500, whole yuan above).
export function priceDigits(price: number | null | undefined, instrumentType?: string | null): number {
  if (instrumentType?.toLowerCase() === 'etf') return 2
  if (!isFiniteNumber(price) || price < 50) return 2
  return price < 500 ? 1 : 0
}

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
export function stockQuote(bars: readonly StockBarRow[], instrumentType?: string | null): StockQuote {
  let index = bars.length - 1
  while (index >= 0 && !isDrawableBar(bars[index])) index--
  const latest = index >= 0 ? bars[index] : undefined
  if (!latest || !isDrawableBar(latest)) return { close: null, change: null, changePct: null, date: null, sources: [], tone: 'flat', digits: 2 }
  const previous = bars[index - 1]
  const sources = barSources(latest)
  const sameSource = previous ? barSources(previous).join('+') === sources.join('+') : false
  const change = isDrawableBar(previous) && sameSource ? Number((latest.close - previous.close).toFixed(6)) : null
  const changePct = change != null && isDrawableBar(previous) ? change / previous.close : null
  return { close: latest.close, change, changePct, date: latest.date, sources, tone: changeTone(change), digits: priceDigits(latest.close, instrumentType) }
}

// ---- chart --------------------------------------------------------------------------------------

export type ChartTheme = {
  up: string; down: string; flat: string
  primary: string; accent: string
  text: string; muted: string; subtle: string
  grid: string; border: string; cardBg: string
  fontMono: string
  ma5: string; ma10: string; ma20: string; ma60: string; ma120: string
}

// ECharts draws on canvas and cannot resolve var(); the component reads these tokens at runtime (DESIGN_SYSTEM §6).
export const CHART_THEME_TOKENS: Record<keyof ChartTheme, string> = {
  up: '--color-up', down: '--color-down', flat: '--color-flat',
  primary: '--color-primary', accent: '--color-accent',
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

export type ChartZoom = { start: number; end: number }

export function defaultZoom(count: number): ChartZoom {
  return { start: count > DEFAULT_VISIBLE_BARS ? (1 - DEFAULT_VISIBLE_BARS / count) * 100 : 0, end: 100 }
}

export function dataZoomPercent(event: unknown): ChartZoom | null {
  const payload = event && typeof event === 'object' ? event as Record<string, unknown> : null
  const batch = Array.isArray(payload?.batch) ? payload.batch[0] as Record<string, unknown> | undefined : undefined
  const source = batch ?? payload
  if (!source || !isFiniteNumber(source.start) || !isFiniteNumber(source.end)) return null
  return { start: Math.max(0, Math.min(100, source.start)), end: Math.max(0, Math.min(100, source.end)) }
}

// Volume in lots (張) only when every source is a verified share-count source; otherwise blank (unit unverified).
export function formatBarVolume(bar: StockBarRow): string {
  const sources = barSources(bar)
  const verified = sources.length > 0 && sources.every(isVerifiedShareSource)
  return formatTableVolume(bar.volume, verified ? sources[0] : null)
}

function volumeUnitVerified(response: StockBarsResponse): boolean {
  return response.sources.length > 0 && response.sources.every(isVerifiedShareSource)
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
  if (!isDrawableBar(bar)) {
    lines.push(bar.is_suspended ? '停牌，無 K 線' : '此根行情不完整，不繪製')
  } else {
    lines.push(
      `開 ${escapeHtml(formatPrice(bar.open, digits))}　高 ${escapeHtml(formatPrice(bar.high, digits))}`,
      `低 ${escapeHtml(formatPrice(bar.low, digits))}　收 ${escapeHtml(formatPrice(bar.close, digits))}`,
      `成交量（張） ${escapeHtml(formatBarVolume(bar) || '單位待核實')}`,
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
      data: bars.map((bar) => isDrawableBar(bar) ? bar.close : '-'), lineStyle: { color: theme.flat, width: 1 }, itemStyle: { color: theme.flat },
    },
    lineSeries(bars, 2, { name: '中軌', field: 'boll_mid', color: theme.primary }),
    lineSeries(bars, 2, { name: '上軌', field: 'boll_upper', color: theme.accent }),
    lineSeries(bars, 2, { name: '下軌', field: 'boll_lower', color: theme.accent }),
  ]
}

export type BarsChartOptions = {
  panel: IndicatorPanelId
  panelState: PanelState
  visibleMa: ReadonlySet<MaField>
  theme: ChartTheme
  layout: ChartLayout
  zoom: ChartZoom
  digits: number
}

export function buildBarsChartOption(response: StockBarsResponse, options: BarsChartOptions): EChartsOption {
  const { theme, layout, zoom, digits } = options
  const bars = response.bars
  const dates = bars.map((bar) => formatDay(bar.date) ?? bar.date)
  const axisLabel = { color: theme.muted, fontSize: 12, fontFamily: theme.fontMono }
  const splitLine = { lineStyle: { color: theme.grid } }
  const gridBase = { left: layout.left, right: layout.right }
  const lots = volumeUnitVerified(response)
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
      formatter: (params: unknown) => {
        const entries = Array.isArray(params) ? params : [params]
        const first = entries.find((entry) => entry && typeof entry === 'object' && isFiniteNumber((entry as { dataIndex?: unknown }).dataIndex)) as { dataIndex: number } | undefined
        return first ? formatBarsTooltip(response, first.dataIndex, options.panel, options.visibleMa, digits) : ''
      },
    },
    xAxis,
    yAxis: [
      { type: 'value', gridIndex: 0, scale: true, axisLabel: { ...axisLabel, showMinLabel: false, formatter: (value: number) => formatPrice(value, digits) }, splitLine },
      { type: 'value', gridIndex: 1, scale: false, splitNumber: 2, axisLabel: { ...axisLabel, showMaxLabel: false, formatter: (value: number) => (lots ? value / 1000 : value).toLocaleString('zh-TW', { maximumFractionDigits: 0 }) }, splitLine },
      bounded
        ? { type: 'value', gridIndex: 2, min: 0, max: 100, interval: 50, axisLabel, splitLine }
        : { type: 'value', gridIndex: 2, scale: true, splitNumber: 2, axisLabel: { ...axisLabel, formatter: (value: number) => indicatorNumber(value, options.panel === 'boll' ? digits : 2) }, splitLine },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1, 2], filterMode: 'filter', start: zoom.start, end: zoom.end },
      {
        type: 'slider', xAxisIndex: [0, 1, 2], filterMode: 'filter', start: zoom.start, end: zoom.end,
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
      },
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
