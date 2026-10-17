import type { IndicatorField, StockBarRow, StockBarsInterval, StockBarsResponse } from '../types'

// Small bars-API fixtures shaped like PR #155 (docs/V1_SPEC.md 技術指標): insufficient history, a suspended
// day plus a missing calendar day, a weekly series and a batch that has not run yet.

export const REQUIRED_BARS: Record<IndicatorField, number> = {
  ma5: 5, ma10: 10, ma20: 20, ma60: 60, ma120: 120,
  macd_dif: 26, macd_signal: 34, macd_hist: 34,
  rsi6: 7, rsi12: 13,
  kd_k: 9, kd_d: 9,
  boll_mid: 20, boll_upper: 20, boll_lower: 20,
  vol_ma5: 5, vol_ma20: 20,
}
const FIELDS = Object.keys(REQUIRED_BARS) as IndicatorField[]

function addDays(date: string, days: number): string {
  const value = new Date(`${date}T00:00:00Z`)
  value.setUTCDate(value.getUTCDate() + days)
  return value.toISOString().slice(0, 10)
}

// Deterministic indicator value for a field once enough bars exist (the numbers only need to be finite).
function fieldValue(field: IndicatorField, close: number, index: number): number {
  if (field.startsWith('rsi') || field.startsWith('kd')) return 40 + (index % 30)
  if (field === 'macd_hist') return index % 2 === 0 ? 0.4 : -0.3
  if (field.startsWith('macd')) return 0.5 + index / 100
  if (field === 'boll_upper') return close + 3
  if (field === 'boll_lower') return close - 3
  if (field.startsWith('vol_ma')) return 21000
  return close - 0.5
}

export function tradedBar(date: string, close: number, barCount: number, extra: Partial<StockBarRow> = {}): StockBarRow {
  const bar: StockBarRow = {
    date, open: close - 0.5, high: close + 1, low: close - 1, close, volume: 21_000_000,
    source: 'twse', is_suspended: false, bar_count: barCount, reasons: {},
  }
  for (const field of FIELDS) {
    if (barCount >= REQUIRED_BARS[field]) bar[field] = fieldValue(field, close, barCount)
    else { bar[field] = null; bar.reasons[field] = 'insufficient_bars' }
  }
  return { ...bar, ...extra }
}

export function suspendedBar(date: string, barCount: number): StockBarRow {
  const bar: StockBarRow = { date, open: null, high: null, low: null, close: null, volume: 0, source: 'twse', is_suspended: true, bar_count: barCount, reasons: {} }
  for (const field of FIELDS) { bar[field] = null; bar.reasons[field] = 'suspended' }
  return bar
}

export function notComputedBar(date: string, close: number): StockBarRow {
  const bar = tradedBar(date, close, 0)
  bar.bar_count = null
  for (const field of FIELDS) { bar[field] = null; bar.reasons[field] = 'not_computed' }
  return bar
}

export function barsResponse(bars: StockBarRow[], interval: StockBarsInterval = 'day', sources = ['twse']): StockBarsResponse {
  return {
    instrument: { id: 1, exchange: 'TWSE', symbol: '2330', name: '台積電', instrument_type: 'stock' },
    interval,
    limit: 250,
    count: bars.length,
    data_as_of: bars.length ? bars[bars.length - 1].date : null,
    sources,
    indicators: {
      formula_version: 'indicators/v1',
      price_basis: 'as_of_date_raw_basis',
      parameters: {},
      required_bars: REQUIRED_BARS,
      fields: FIELDS,
      source: interval === 'week' ? 'indicator_batch:weekly_on_request' : 'indicator_batch:technical_indicators',
      computed_at: interval === 'week' ? null : '2026-10-16T10:00:00',
    },
    bars,
  }
}

// 20 trading days: MA5/10/20, RSI, KD and Bollinger have values on the last bar; MACD (26/34) does not.
export function insufficientDaily(): StockBarsResponse {
  return barsResponse(Array.from({ length: 20 }, (_, index) => tradedBar(addDays('2026-09-01', index), 100 + index, index + 1)))
}

// 40 rows, 2026-08-03 onward: row 30 is suspended, the calendar day after row 34 has no row at all, and the
// last row is suspended too. bar_count counts only usable bars, so it stops growing on suspended rows.
export function suspendedWithGapDaily(): StockBarsResponse {
  const bars: StockBarRow[] = []
  let date = '2026-08-03'
  let usable = 0
  for (let index = 0; index < 40; index++) {
    if (index === 30 || index === 39) bars.push(suspendedBar(date, usable))
    else bars.push(tradedBar(date, 50 + index / 2, ++usable))
    date = addDays(date, index === 34 ? 2 : 1)
  }
  return barsResponse(bars)
}

// Weekly series: each row is one ISO week with week_start / week_end / trading_days and a `sources` list.
export function weeklySeries(count = 3): StockBarsResponse {
  const bars = Array.from({ length: count }, (_, index) => {
    const weekStart = addDays('2026-09-28', index * 7)
    const weekEnd = addDays(weekStart, 4)
    const bar = tradedBar(weekEnd, 600 + index * 10, index + 1, { week_start: weekStart, week_end: weekEnd, trading_days: 5, volume: 105_000_000 })
    delete bar.source
    delete bar.is_suspended
    bar.sources = ['twse']
    return bar
  })
  return barsResponse(bars, 'week')
}

export function notComputedDaily(): StockBarsResponse {
  return barsResponse([notComputedBar('2026-10-15', 80), notComputedBar('2026-10-16', 81)])
}
