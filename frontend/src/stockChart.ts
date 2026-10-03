import type { EChartsOption } from 'echarts'

import type { Bar } from './types'
import { formatTableNumber, formatTableVolume, isVerifiedShareSource } from './units'

export type StockChartBar = {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  volumeExact?: string | null
  source: string
  dataAsOf: string | null
  isSuspended: boolean
}

export type StockChartPoint = {
  date: string
  bar: StockChartBar | null
  ma20: number | null
  ma60: number | null
}

export type PreparedStockChart = {
  bars: StockChartBar[]
  points: StockChartPoint[]
  ma20: Array<number | null>
  ma60: Array<number | null>
  totalRows: number
  invalidDateRows: number
  invalidRows: number
  duplicateDates: string[]
  duplicateRows: number
  sourceNames: string[]
  maStatus: 'available' | 'insufficient' | 'basis_unknown' | 'data_gap'
  maReason: string
}

export type StockChartRange = 30 | 60 | 120 | 'all'
export type StockChartWindow = { start: number; end: number }
export type StockChartPreparationOptions = { knownGapDates?: readonly string[] }

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function isValidDate(value: unknown): value is string {
  if (typeof value !== 'string' || !DATE_PATTERN.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

function normalizeSource(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) return 'unknown'
  return value.trim()
}

function isValidBar(value: unknown): value is Bar & {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
} {
  if (!value || typeof value !== 'object') return false
  const row = value as Partial<Bar>
  return isValidDate(row.date)
    && isFiniteNumber(row.open)
    && isFiniteNumber(row.high)
    && isFiniteNumber(row.low)
    && isFiniteNumber(row.close)
    && isFiniteNumber(row.volume)
    && row.high >= Math.max(row.open, row.close)
    && row.low <= Math.min(row.open, row.close)
    && row.high >= row.low
}

export function movingAverage(values: Array<number | null>, period: number): Array<number | null> {
  if (!Number.isInteger(period) || period < 1) return values.map(() => null)
  return values.map((_, index) => {
    if (index < period - 1) return null
    const window = values.slice(index - period + 1, index + 1)
    const numericValues = window.filter(isFiniteNumber)
    if (numericValues.length !== period) return null
    return numericValues.reduce((sum, value) => sum + value, 0) / period
  })
}

export function prepareStockChartData(input: readonly Bar[] | null | undefined, options: StockChartPreparationOptions = {}): PreparedStockChart {
  const rawRows = Array.isArray(input) ? input as readonly unknown[] : []
  const dateRows = rawRows.filter((row): row is { date: string } => Boolean(row && typeof row === 'object' && isValidDate((row as Partial<Bar>).date)))
  const invalidDateRows = rawRows.length - dateRows.length
  const dateCounts = new Map<string, number>()
  dateRows.forEach((row) => dateCounts.set(row.date, (dateCounts.get(row.date) ?? 0) + 1))
  const duplicateDates = [...dateCounts.entries()]
    .filter(([, count]) => count > 1)
    .map(([date]) => date)
    .sort()
  const duplicateSet = new Set(duplicateDates)
  const duplicateRows = duplicateDates.reduce((count, date) => count + (dateCounts.get(date) ?? 0), 0)
  const invalidRows = rawRows.length - duplicateRows - rawRows.filter((row): row is Bar => isValidBar(row) && !duplicateSet.has(row.date)).length
  const slotsByDate = new Map<string, unknown | null>()
  dateRows.forEach((row) => {
    slotsByDate.set(row.date, duplicateSet.has(row.date) ? null : row)
  })
  for (const value of options.knownGapDates ?? []) {
    if (isValidDate(value) && !slotsByDate.has(value)) slotsByDate.set(value, null)
  }
  const pointsWithoutMovingAverages = [...slotsByDate.keys()].sort().map((date) => {
    const row = slotsByDate.get(date)
    if (!row || !isValidBar(row)) return { date, bar: null as StockChartBar | null }
    return {
      date,
      bar: {
        date: row.date,
        open: row.open,
        high: row.high,
        low: row.low,
        close: row.close,
        volume: row.volume,
        volumeExact: row.volume_exact,
        source: normalizeSource(row.source),
        dataAsOf: typeof row.data_as_of === 'string' ? row.data_as_of : null,
        isSuspended: row.is_suspended === true,
      },
    }
  })
  const bars = pointsWithoutMovingAverages.flatMap((point) => point.bar ? [point.bar] : [])
  const sourceNames = [...new Set(rawRows.map((row) => row && typeof row === 'object' ? normalizeSource((row as Partial<Bar>).source) : 'unknown'))].sort()
  const sameKnownSource = sourceNames.length === 1 && sourceNames[0] !== 'unknown'
  const closes = pointsWithoutMovingAverages.map((point) => point.bar?.close ?? null)
  const ma20 = sameKnownSource && invalidDateRows === 0 ? movingAverage(closes, 20) : closes.map(() => null)
  const ma60 = sameKnownSource && invalidDateRows === 0 ? movingAverage(closes, 60) : closes.map(() => null)
  const hasDataGap = pointsWithoutMovingAverages.some((point) => point.bar == null)
  const maStatus = !sameKnownSource
    ? 'basis_unknown'
    : invalidDateRows > 0 || hasDataGap
      ? 'data_gap'
      : !ma20.some((value) => value != null)
      ? 'insufficient'
      : 'available'
  const maReason = maStatus === 'basis_unknown'
    ? '來源或價格基準未足以確認一致，暫不繪製均線。'
    : maStatus === 'data_gap'
      ? '資料含缺口、重複日期或無效日期；均線不跨越缺口，缺口後須重新累積完整 20／60 筆。'
    : maStatus === 'insufficient'
      ? '有效同一來源且連續的日線不足 20 筆，MA20／MA60 暫不繪製。'
      : !ma60.some((value) => value != null)
        ? 'MA20 依 20 筆有效收盤價計算；MA60 需滿 60 筆後才顯示。'
      : '均線僅依本頁有效收盤價計算，不等同後端策略特徵。'
  const points = pointsWithoutMovingAverages.map((point, index) => ({ ...point, ma20: ma20[index], ma60: ma60[index] }))
  return { bars, points, ma20, ma60, totalRows: rawRows.length, invalidDateRows, invalidRows, duplicateDates, duplicateRows, sourceNames, maStatus, maReason }
}

export function rangeStartIndex(length: number, range: StockChartRange): number {
  if (length <= 0 || range === 'all') return 0
  return Math.max(0, length - range)
}

export function windowForRange(length: number, range: StockChartRange): StockChartWindow {
  const safeLength = Math.max(0, Math.floor(length))
  return { start: rangeStartIndex(safeLength, range), end: Math.max(0, safeLength - 1) }
}

export function normalizeStockChartWindow(length: number, window: StockChartWindow): StockChartWindow {
  const safeLength = Math.max(0, Math.floor(length))
  if (safeLength === 0) return { start: 0, end: 0 }
  const maxIndex = safeLength - 1
  const start = Math.min(maxIndex, Math.max(0, Math.floor(Number.isFinite(window.start) ? window.start : 0)))
  const end = Math.min(maxIndex, Math.max(start, Math.floor(Number.isFinite(window.end) ? window.end : maxIndex)))
  return { start, end }
}

function numericValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function dataZoomEventWindow(event: unknown, length: number): StockChartWindow | null {
  const payload = event && typeof event === 'object' ? event as Record<string, unknown> : null
  const batch = payload?.batch
  const source = Array.isArray(batch) && batch[0] && typeof batch[0] === 'object'
    ? batch[0] as Record<string, unknown>
    : payload
  if (!source) return null
  const startValue = numericValue(source.startValue)
  const endValue = numericValue(source.endValue)
  if (startValue != null && endValue != null) return normalizeStockChartWindow(length, { start: startValue, end: endValue })
  const start = numericValue(source.start)
  const end = numericValue(source.end)
  if (start == null || end == null) return null
  const maxIndex = Math.max(0, Math.floor(length) - 1)
  return normalizeStockChartWindow(length, {
    start: maxIndex * start / 100,
    end: maxIndex * end / 100,
  })
}

function chartNumber(value: number | null | undefined, digits = 2): string {
  return isFiniteNumber(value)
    ? value.toLocaleString('zh-TW', { maximumFractionDigits: digits })
    : '待核實'
}

function chartVolumeNumber(value: number | null | undefined, unitConfirmed: boolean): string {
  return unitConfirmed ? formatTableNumber(typeof value === 'number' ? value / 1000 : value) : formatTableNumber(value)
}

function escapeTooltipText(value: unknown): string {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

export function formatStockTooltip(data: PreparedStockChart, params: unknown): string {
  const entries = Array.isArray(params) ? params : [params]
  const first = entries.find((entry): entry is { dataIndex: number } => Boolean(entry && typeof entry === 'object' && typeof (entry as { dataIndex?: unknown }).dataIndex === 'number' && (entry as { dataIndex: number }).dataIndex >= 0))
  const index = first?.dataIndex ?? -1
  const point = data.points[index]
  if (!point) return '資料待核實'
  if (!point.bar) return `<strong>${escapeTooltipText(point.date)}</strong><br/>此日期沒有可繪製的完整行情資料`
  const status = point.bar.isSuspended ? ' · 停牌／無交易標記' : ''
  const volumeLabel = isVerifiedShareSource(point.bar.source) ? '成交量（張）' : '成交量（單位待核實）'
  const lines = [
    `<strong>${escapeTooltipText(point.date)}${status}</strong>`,
    '價格及均線：報價幣別元；指數：點',
    `開：${escapeTooltipText(chartNumber(point.bar.open))}`,
    `高：${escapeTooltipText(chartNumber(point.bar.high))}`,
    `低：${escapeTooltipText(chartNumber(point.bar.low))}`,
    `收：${escapeTooltipText(chartNumber(point.bar.close))}`,
    `${volumeLabel}：${escapeTooltipText(formatTableVolume(point.bar.volume, point.bar.source, point.bar.volumeExact) || '未提供或數值、單位待核實')}`,
  ]
  if (point.ma20 != null) lines.push(`MA20：${escapeTooltipText(chartNumber(point.ma20))}`)
  if (point.ma60 != null) lines.push(`MA60：${escapeTooltipText(chartNumber(point.ma60))}`)
  // ECharts renders formatter strings as tooltip HTML. Dynamic text is escaped;
  // only these fixed line-break tags are emitted by this formatter.
  return lines.join('<br/>')
}

export function buildStockChartOption(data: PreparedStockChart, range: StockChartRange | StockChartWindow = 'all'): EChartsOption {
  const selectedWindow = typeof range === 'object' ? normalizeStockChartWindow(data.points.length, range) : windowForRange(data.points.length, range)
  const volumeUnitConfirmed = data.sourceNames.length > 0 && data.sourceNames.every((source) => isVerifiedShareSource(source))
  const { start: startValue, end: endValue } = selectedWindow
  const dates = data.points.map((point) => point.date)
  const candles = data.points.map((point) => point.bar ? [point.bar.open, point.bar.close, point.bar.low, point.bar.high] : [null, null, null, null])
  const volumes = data.points.map((point) => ({
    value: point.bar && point.bar.volume >= 0 ? point.bar.volume : null,
    itemStyle: point.bar ? { color: point.bar.close >= point.bar.open ? '#e899a0' : '#70c8a5', opacity: point.bar.isSuspended ? 0.45 : 0.82 } : { opacity: 0 },
  }))
  return {
    animation: false,
    grid: [
      { left: 12, right: 16, top: 28, height: '56%', containLabel: true },
      { left: 12, right: 16, top: '72%', height: '17%', containLabel: true },
    ],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: (params) => formatStockTooltip(data, params),
    },
    xAxis: [
      {
        type: 'category',
        gridIndex: 0,
        data: dates,
        boundaryGap: true,
        axisLine: { lineStyle: { color: '#405060' } },
        axisLabel: { color: '#87909d', hideOverlap: true },
      },
      { type: 'category', gridIndex: 1, data: dates, boundaryGap: true, axisLabel: { show: false } },
    ],
    yAxis: [
      {
        type: 'value',
        gridIndex: 0,
        scale: true,
        axisLabel: { color: '#87909d', formatter: (value: number) => chartNumber(value) },
        splitLine: { lineStyle: { color: '#2a3540' } },
      },
      {
        type: 'value',
        gridIndex: 1,
        axisLabel: { color: '#87909d', formatter: (value: number) => chartVolumeNumber(value, volumeUnitConfirmed) },
        splitLine: { lineStyle: { color: '#202a34' } },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], filterMode: 'none', startValue, endValue },
      { type: 'slider', xAxisIndex: [0, 1], filterMode: 'none', startValue, endValue, left: 12, right: 16, height: 18, bottom: 5, borderColor: '#405060', fillerColor: 'rgba(245,184,91,.16)', textStyle: { color: '#87909d' } },
    ],
    series: [
      {
        name: '日K',
        type: 'candlestick',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: candles,
        itemStyle: { color: '#e899a0', color0: '#70c8a5', borderColor: '#e899a0', borderColor0: '#70c8a5' },
      },
      {
        name: 'MA20',
        type: 'line',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: data.ma20,
        showSymbol: false,
        connectNulls: false,
        lineStyle: { color: '#f5b85b', width: 1.5 },
      },
      {
        name: 'MA60',
        type: 'line',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: data.ma60,
        showSymbol: false,
        connectNulls: false,
        lineStyle: { color: '#8fa8d4', width: 1.5 },
      },
      { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volumes, barMaxWidth: 12 },
    ],
  }
}
