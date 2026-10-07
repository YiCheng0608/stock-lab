import type { PriceFocusDayMove, PriceLotFocusData } from './types'
import { memoryPriceCaptureReady, PRICE_SCOPE_POLICY_VERSION, PRICE_SCOPE_POLICY_VERSION_V2, PRICE_SCOPE_POLICY_VERSION_V3, PRICE_SCOPE_POLICY_VERSION_V4, priceMemoryInstrumentSupported, priceSourcePins, validStockPriceMemoryRead } from './stockPriceMemoryRead'

const maximum = '9223372036854775807'
const same = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right)
export const priceFocusDayMoveLabels = { all: '全部', up: '收高於開', down: '收低於開', flat: '平收' } as const
const directionReasons = { up: 'close_above_open', down: 'close_below_open', flat: 'close_equal_open' } as const

export function validPriceFocusDayMove(value: unknown): value is PriceFocusDayMove {
  return typeof value === 'string' && ['all', 'up', 'down', 'flat'].includes(value)
}

/** Compare source decimal strings without projecting prices to a JS number. */
export function exactDayMove(opening: unknown, closing: unknown): Exclude<PriceFocusDayMove, 'all'> | null {
  const parts = (value: unknown): [string, string] | null => {
    if (typeof value !== 'string' || value.length > 64 || !/^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?![\s\S])/.test(value)) return null
    const [whole, fraction = ''] = value.split('.')
    if (whole === '0' && !/[1-9]/.test(fraction)) return null
    return [whole, fraction.replace(/0+$/, '')]
  }
  const open = parts(opening), close = parts(closing)
  if (!open || !close) return null
  if (open[0].length !== close[0].length) return close[0].length > open[0].length ? 'up' : 'down'
  if (open[0] !== close[0]) return close[0] > open[0] ? 'up' : 'down'
  const length = Math.max(open[1].length, close[1].length), left = open[1].padEnd(length, '0'), right = close[1].padEnd(length, '0')
  return right > left ? 'up' : right < left ? 'down' : 'flat'
}

export function minLotsShares(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > 20 || !/^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,3})?(?![\s\S])/.test(value)) return null
  const [whole, fraction = ''] = value.split('.')
  const shares = (whole + fraction.padEnd(3, '0')).replace(/^0+/, '') || '0'
  return shares.length > maximum.length || (shares.length === maximum.length && shares > maximum) ? null : shares
}

export const minRangeMilliPct = minLotsShares

/** Align the original O/H/L decimals before any subtraction or division. */
export function exactDayRange(opening: unknown, high: unknown, low: unknown): { opening: bigint; high: bigint; low: bigint } | null {
  const values = [opening, high, low]
  if (values.some((value) => typeof value !== 'string' || value.length > 64 || !/^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?![\s\S])/.test(value))) return null
  const parts = (values as string[]).map((value) => value.split('.'))
  const scale = Math.max(...parts.map(([, fraction = '']) => fraction.length))
  const [openInt, highInt, lowInt] = parts.map(([whole, fraction = '']) => BigInt(whole + fraction.padEnd(scale, '0')))
  return highInt >= openInt && openInt >= lowInt && lowInt > 0n ? { opening: openInt, high: highInt, low: lowInt } : null
}

export function rangeMeetsMinimum(opening: unknown, high: unknown, low: unknown, minimum: string): boolean | null {
  const prices = exactDayRange(opening, high, low), scaled = minRangeMilliPct(minimum)
  return !prices || scaled === null ? null : 100000n * (prices.high - prices.low) >= BigInt(scaled) * prices.opening
}

/** Display only: round the exact rational percent half-up to three decimals. */
export function approximateRangePct(opening: string, high: string, low: string): string | null {
  const prices = exactDayRange(opening, high, low)
  if (!prices) return null
  const numerator = 100000n * (prices.high - prices.low)
  const rounded = (2n * numerator + prices.opening) / (2n * prices.opening)
  const text = rounded.toString().padStart(4, '0')
  return `${text.slice(0, -3)}.${text.slice(-3)}`
}

export function minTurnoverValue(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > 19 || !/^(?:0|[1-9][0-9]*)(?![\s\S])/.test(value)) return null
  return value.length > maximum.length || (value.length === maximum.length && value > maximum) ? null : value
}

export function exactTurnoverText(value: string): string {
  return value.replace(/\B(?=(?:[0-9]{3})+(?![0-9]))/g, ',')
}

/** Event search/range are shared homepage state, never price API conditions. */
export function validPriceFocusParams(params: URLSearchParams): boolean {
  const allowed = ['as_of', 'min_lots', 'day_move', 'min_turnover', 'min_range_pct', 'q', 'from', 'to']
  return !Array.from(params.keys()).some((key) => !allowed.includes(key))
    && ['as_of', 'min_lots'].every((key) => params.getAll(key).length === 1)
    && ['day_move', 'min_turnover', 'min_range_pct', 'q', 'from', 'to'].every((key) => params.getAll(key).length <= 1)
    && validFocusDate(params.get('as_of') ?? '') && minLotsShares(params.get('min_lots')) !== null
    && validPriceFocusDayMove(params.get('day_move') ?? 'all') && minTurnoverValue(params.get('min_turnover') ?? '0') !== null
    && minRangeMilliPct(params.get('min_range_pct') ?? '0') !== null
    && (!params.has('from') || validFocusDate(params.get('from')!)) && (!params.has('to') || validFocusDate(params.get('to')!))
    && (!params.has('from') || !params.has('to') || params.get('from')! <= params.get('to')!)
}

export function validFocusDate(value: string): boolean {
  if (!/^[0-9]{4}-[0-9]{2}-[0-9]{2}(?![\s\S])/.test(value) || value.startsWith('0000-')) return false
  const time = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(time.getTime()) && time.toISOString().slice(0, 10) === value
}

export function sharesMeetMinimum(shares: string, minimum: string): boolean {
  return shares.length > minimum.length || (shares.length === minimum.length && shares >= minimum)
}

export function exactLotsText(shares: string): string {
  const padded = shares.padStart(4, '0'), fraction = padded.slice(-3).replace(/0+$/, '')
  return padded.slice(0, -3) + (fraction ? `.${fraction}` : '')
}

export function priceFocusDetailPath(symbol: string, asOf: string, minLots: string, dayMove: PriceFocusDayMove = 'all', minTurnover = '0', minRangePct = '0'): string {
  return `/stocks/TPEx/${symbol}?${new URLSearchParams({ as_of: asOf, from: 'price-lots', focus_as_of: asOf, focus_min_lots: minLots, focus_day_move: dayMove, focus_min_turnover: minTurnover, focus_min_range_pct: minRangePct })}`
}

export function priceFocusReturnPath(params: URLSearchParams): string | null {
  if (params.get('from') !== 'price-lots') return null
  const required = ['as_of', 'from', 'focus_as_of', 'focus_min_lots'], optional = ['focus_day_move', 'focus_min_turnover', 'focus_min_range_pct'], allowed = [...required, ...optional]
  if (Array.from(params.keys()).some((key) => !allowed.includes(key)) || required.some((key) => params.getAll(key).length !== 1) || optional.some((key) => params.getAll(key).length > 1)) return null
  const asOf = params.get('focus_as_of') ?? '', minLots = params.get('focus_min_lots') ?? ''
  const dayMove = params.get('focus_day_move') ?? 'all'
  const minTurnover = params.get('focus_min_turnover') ?? '0'
  const minRangePct = params.get('focus_min_range_pct') ?? '0'
  if (!validFocusDate(asOf) || minLotsShares(minLots) === null || params.get('as_of') !== asOf || !validPriceFocusDayMove(dayMove) || minTurnoverValue(minTurnover) === null || minRangeMilliPct(minRangePct) === null) return null
  return `/?${new URLSearchParams({ as_of: asOf, min_lots: minLots, day_move: dayMove, min_turnover: minTurnover, min_range_pct: minRangePct })}#price-lot-focus-title`
}

/** Check every admitted source read even when no stock meets the threshold. */
export function validPriceLotFocus(value: unknown, asOf: string, minLots: string, dayMove: PriceFocusDayMove = 'all', minTurnover = '0', minRangePct = '0'): value is PriceLotFocusData {
  if (!value || typeof value !== 'object' || !validFocusDate(asOf)) return false
  const data = value as PriceLotFocusData, minimum = minLotsShares(minLots)
  const symbols = data.supported_scope?.symbols
  const eightScope = asOf === '2026-10-07' && same(symbols, ['3105', '3293', '5274', '5347', '6223', '6488', '6510', '8069'])
  const sevenScope = same(symbols, ['3105', '3293', '5274', '5347', '6488', '6510', '8069'])
  const sixScope = same(symbols, ['3105', '3293', '5274', '5347', '6488', '8069'])
  const fiveScope = same(symbols, ['3105', '3293', '5274', '5347', '6488'])
  const fourScope = same(symbols, ['3105', '5274', '5347', '6488'])
  const threeScope = same(symbols, ['3105', '5347', '6488'])
  const pins = priceSourcePins(asOf, asOf === '2026-10-06' ? sevenScope ? undefined : sixScope ? PRICE_SCOPE_POLICY_VERSION_V4 : fiveScope ? PRICE_SCOPE_POLICY_VERSION_V3 : fourScope ? PRICE_SCOPE_POLICY_VERSION_V2 : threeScope ? PRICE_SCOPE_POLICY_VERSION : 'm1-price-tpex-11370-2026-10-06.1' : undefined)
  const expectedSymbols = pins?.symbols ?? ['3105', '6488']
  if (!same(symbols, expectedSymbols) || minimum === null || minTurnoverValue(minTurnover) === null || minRangeMilliPct(minRangePct) === null || !validPriceFocusDayMove(dayMove)
    || !(eightScope ? data.version === 'price-lot-focus/m2-v10' : sevenScope ? data.version === 'price-lot-focus/m2-v9' : sixScope ? data.version === 'price-lot-focus/m2-v8' : fiveScope ? data.version === 'price-lot-focus/m2-v7' : fourScope ? data.version === 'price-lot-focus/m2-v6' : data.version === 'price-lot-focus/m2-v5' || (!threeScope && data.version === 'price-lot-focus/m2-v4')) || data.day_move !== dayMove || data.min_turnover !== minTurnover || data.min_range_pct !== minRangePct || data.as_of !== asOf || data.min_lots !== minLots || data.min_shares !== minimum
    || !['available', 'unavailable'].includes(data.status) || data.historical_pit !== 'unsupported' || data.sort !== 'code_ascending'
    || typeof data.can_capture !== 'boolean' || !Array.isArray(data.items) || !Array.isArray(data.reads) || !Array.isArray(data.reasons)
    || data.reasons.some((reason) => typeof reason !== 'string')
    || !same(data.supported_scope, { exchange: 'TPEx', symbols: expectedSymbols, cutoff: pins ? asOf : '2026-10-05', currency: 'TWD', asset_type: 'stock' })) return false
  if (data.status === 'unavailable') {
    if (data.count !== null || data.items.length !== 0 || data.reasons.length === 0 || ![0, expectedSymbols.length].includes(data.reads.length)) return false
    return !data.can_capture || (data.reads.length === expectedSymbols.length && data.reads.every((read, index) => read?.instrument?.symbol === expectedSymbols[index]
      && priceMemoryInstrumentSupported(read.instrument) && memoryPriceCaptureReady(read.price_memory ?? undefined, 'TPEx', expectedSymbols[index], asOf)
      && same(read.price_memory?.supported_scope.symbols, expectedSymbols)))
  }
  if (!pins || data.can_capture || data.reasons.length || data.reads.length !== expectedSymbols.length || !Number.isInteger(data.count) || data.count !== data.items.length) return false
  for (let index = 0; index < expectedSymbols.length; index++) {
    const read = data.reads[index]
    if (!read?.instrument || read.instrument.symbol !== expectedSymbols[index] || !validStockPriceMemoryRead(read.price_memory ?? undefined, read.instrument, asOf)
      || read.price_memory!.provenance!.policy_version !== pins.policyVersion
      || exactDayMove(read.price_memory!.latest!.source_fields['開盤'], read.price_memory!.latest!.source_fields['收盤']) === null
      || exactDayRange(read.price_memory!.latest!.source_fields['開盤'], read.price_memory!.latest!.source_fields['最高'], read.price_memory!.latest!.source_fields['最低']) === null
      || minTurnoverValue(read.price_memory!.latest!.turnover_exact) === null || read.price_memory!.latest!.turnover_status !== 'available') return false
  }
  if (data.reads.slice(1).some((read) => !same(data.reads[0].price_memory!.provenance, read.price_memory!.provenance))) return false
  const expected = data.reads.filter((read) => {
    const bar = read.price_memory!.latest!, move = exactDayMove(bar.source_fields['開盤'], bar.source_fields['收盤'])
    return sharesMeetMinimum(bar.volume_exact, minimum) && sharesMeetMinimum(bar.turnover_exact!, minTurnover) && (dayMove === 'all' || move === dayMove)
      && rangeMeetsMinimum(bar.source_fields['開盤'], bar.source_fields['最高'], bar.source_fields['最低'], minRangePct) === true
  })
  return expected.length === data.items.length && expected.every((read, index) => {
    const item = data.items[index], bar = read.price_memory!.latest!, provenance = read.price_memory!.provenance!
    const actualMove = exactDayMove(bar.source_fields['開盤'], bar.source_fields['收盤'])!
    return item != null && item.exchange === 'TPEx' && item.symbol === read.instrument.symbol && item.name === read.instrument.name
      && item.volume_exact === bar.volume_exact && item.volume_lots === exactLotsText(bar.volume_exact) && item.min_lots === minLots
      && item.min_shares === minimum && item.min_turnover === minTurnover && item.turnover_exact === bar.turnover_exact
      && item.day_move === actualMove && item.open_exact === bar.source_fields['開盤'] && item.close_exact === bar.source_fields['收盤']
      && item.min_range_pct === minRangePct && item.high_exact === bar.source_fields['最高'] && item.low_exact === bar.source_fields['最低']
      && same(item.reasons, ['volume_at_least_min_lots', 'turnover_at_least_min_turnover', directionReasons[actualMove], 'range_at_least_min_range_pct']) && item.source_date === asOf
      && item.source_version === provenance.source_version && item.detail_url === priceFocusDetailPath(item.symbol, asOf, minLots, dayMove, minTurnover, minRangePct)
  })
}
