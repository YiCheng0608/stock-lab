import type { PriceFocusDayMove, PriceLotFocusData } from './types'
import { memoryPriceCaptureReady, priceMemoryInstrumentSupported, validStockPriceMemoryRead } from './stockPriceMemoryRead'

const maximum = '9223372036854775807'
const symbols = ['3105', '6488']
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

export function minTurnoverValue(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > 19 || !/^(?:0|[1-9][0-9]*)(?![\s\S])/.test(value)) return null
  return value.length > maximum.length || (value.length === maximum.length && value > maximum) ? null : value
}

export function exactTurnoverText(value: string): string {
  return value.replace(/\B(?=(?:[0-9]{3})+(?![0-9]))/g, ',')
}

/** q is the existing official-event panel's shared homepage search state. */
export function validPriceFocusParams(params: URLSearchParams): boolean {
  const allowed = ['as_of', 'min_lots', 'day_move', 'min_turnover', 'q']
  return !Array.from(params.keys()).some((key) => !allowed.includes(key))
    && ['as_of', 'min_lots'].every((key) => params.getAll(key).length === 1)
    && ['day_move', 'min_turnover', 'q'].every((key) => params.getAll(key).length <= 1)
    && validFocusDate(params.get('as_of') ?? '') && minLotsShares(params.get('min_lots')) !== null
    && validPriceFocusDayMove(params.get('day_move') ?? 'all') && minTurnoverValue(params.get('min_turnover') ?? '0') !== null
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

export function priceFocusDetailPath(symbol: string, asOf: string, minLots: string, dayMove: PriceFocusDayMove = 'all', minTurnover = '0'): string {
  return `/stocks/TPEx/${symbol}?${new URLSearchParams({ as_of: asOf, from: 'price-lots', focus_as_of: asOf, focus_min_lots: minLots, focus_day_move: dayMove, focus_min_turnover: minTurnover })}`
}

export function priceFocusReturnPath(params: URLSearchParams): string | null {
  if (params.get('from') !== 'price-lots') return null
  const required = ['as_of', 'from', 'focus_as_of', 'focus_min_lots'], optional = ['focus_day_move', 'focus_min_turnover'], allowed = [...required, ...optional]
  if (Array.from(params.keys()).some((key) => !allowed.includes(key)) || required.some((key) => params.getAll(key).length !== 1) || optional.some((key) => params.getAll(key).length > 1)) return null
  const asOf = params.get('focus_as_of') ?? '', minLots = params.get('focus_min_lots') ?? ''
  const dayMove = params.get('focus_day_move') ?? 'all'
  const minTurnover = params.get('focus_min_turnover') ?? '0'
  if (!validFocusDate(asOf) || minLotsShares(minLots) === null || params.get('as_of') !== asOf || !validPriceFocusDayMove(dayMove) || minTurnoverValue(minTurnover) === null) return null
  return `/?${new URLSearchParams({ as_of: asOf, min_lots: minLots, day_move: dayMove, min_turnover: minTurnover })}#price-lot-focus-title`
}

/** Check the two source reads even when no stock meets the threshold. */
export function validPriceLotFocus(value: unknown, asOf: string, minLots: string, dayMove: PriceFocusDayMove = 'all', minTurnover = '0'): value is PriceLotFocusData {
  if (!value || typeof value !== 'object' || !validFocusDate(asOf)) return false
  const data = value as PriceLotFocusData, minimum = minLotsShares(minLots)
  if (minimum === null || minTurnoverValue(minTurnover) === null || !validPriceFocusDayMove(dayMove) || data.version !== 'price-lot-focus/m2-v3' || data.day_move !== dayMove || data.min_turnover !== minTurnover || data.as_of !== asOf || data.min_lots !== minLots || data.min_shares !== minimum
    || !['available', 'unavailable'].includes(data.status) || data.historical_pit !== 'unsupported' || data.sort !== 'code_ascending'
    || typeof data.can_capture !== 'boolean' || !Array.isArray(data.items) || !Array.isArray(data.reads) || !Array.isArray(data.reasons)
    || data.reasons.some((reason) => typeof reason !== 'string')
    || !same(data.supported_scope, { exchange: 'TPEx', symbols, cutoff: '2026-10-05', currency: 'TWD', asset_type: 'stock' })) return false
  if (data.status === 'unavailable') {
    if (data.count !== null || data.items.length !== 0 || data.reasons.length === 0 || ![0, 2].includes(data.reads.length)) return false
    return !data.can_capture || (data.reads.length === 2 && data.reads.every((read, index) => read?.instrument?.symbol === symbols[index]
      && priceMemoryInstrumentSupported(read.instrument) && memoryPriceCaptureReady(read.price_memory ?? undefined, 'TPEx', symbols[index], asOf)))
  }
  if (asOf !== '2026-10-05' || data.can_capture || data.reasons.length || data.reads.length !== 2 || !Number.isInteger(data.count) || data.count !== data.items.length) return false
  for (let index = 0; index < 2; index++) {
    const read = data.reads[index]
    if (!read?.instrument || read.instrument.symbol !== symbols[index] || !validStockPriceMemoryRead(read.price_memory ?? undefined, read.instrument, asOf)
      || exactDayMove(read.price_memory!.latest!.source_fields['開盤'], read.price_memory!.latest!.source_fields['收盤']) === null
      || minTurnoverValue(read.price_memory!.latest!.turnover_exact) === null || read.price_memory!.latest!.turnover_status !== 'available') return false
  }
  if (!same(data.reads[0].price_memory!.provenance, data.reads[1].price_memory!.provenance)) return false
  const expected = data.reads.filter((read) => {
    const bar = read.price_memory!.latest!, move = exactDayMove(bar.source_fields['開盤'], bar.source_fields['收盤'])
    return sharesMeetMinimum(bar.volume_exact, minimum) && sharesMeetMinimum(bar.turnover_exact!, minTurnover) && (dayMove === 'all' || move === dayMove)
  })
  return expected.length === data.items.length && expected.every((read, index) => {
    const item = data.items[index], bar = read.price_memory!.latest!, provenance = read.price_memory!.provenance!
    const actualMove = exactDayMove(bar.source_fields['開盤'], bar.source_fields['收盤'])!
    return item != null && item.exchange === 'TPEx' && item.symbol === read.instrument.symbol && item.name === read.instrument.name
      && item.volume_exact === bar.volume_exact && item.volume_lots === exactLotsText(bar.volume_exact) && item.min_lots === minLots
      && item.min_shares === minimum && item.min_turnover === minTurnover && item.turnover_exact === bar.turnover_exact
      && item.day_move === actualMove && item.open_exact === bar.source_fields['開盤'] && item.close_exact === bar.source_fields['收盤']
      && same(item.reasons, ['volume_at_least_min_lots', 'turnover_at_least_min_turnover', directionReasons[actualMove]]) && item.source_date === asOf
      && item.source_version === provenance.source_version && item.detail_url === priceFocusDetailPath(item.symbol, asOf, minLots, dayMove, minTurnover)
  })
}
