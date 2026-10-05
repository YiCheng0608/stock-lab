import type { PriceLotFocusData } from './types'
import { memoryPriceCaptureReady, priceMemoryInstrumentSupported, validStockPriceMemoryRead } from './stockPriceMemoryRead'

const maximum = '9223372036854775807'
const symbols = ['3105', '6488']
const same = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right)

export function minLotsShares(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > 20 || !/^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,3})?(?![\s\S])/.test(value)) return null
  const [whole, fraction = ''] = value.split('.')
  const shares = (whole + fraction.padEnd(3, '0')).replace(/^0+/, '') || '0'
  return shares.length > maximum.length || (shares.length === maximum.length && shares > maximum) ? null : shares
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

export function priceFocusDetailPath(symbol: string, asOf: string, minLots: string): string {
  return `/stocks/TPEx/${symbol}?${new URLSearchParams({ as_of: asOf, from: 'price-lots', focus_as_of: asOf, focus_min_lots: minLots })}`
}

export function priceFocusReturnPath(params: URLSearchParams): string | null {
  if (params.get('from') !== 'price-lots') return null
  const allowed = ['as_of', 'from', 'focus_as_of', 'focus_min_lots']
  if (Array.from(params.keys()).some((key) => !allowed.includes(key)) || allowed.some((key) => params.getAll(key).length !== 1)) return null
  const asOf = params.get('focus_as_of') ?? '', minLots = params.get('focus_min_lots') ?? ''
  if (!validFocusDate(asOf) || minLotsShares(minLots) === null || !validFocusDate(params.get('as_of') ?? '')) return null
  return `/?${new URLSearchParams({ as_of: asOf, min_lots: minLots })}#price-lot-focus-title`
}

/** Check the two source reads even when no stock meets the threshold. */
export function validPriceLotFocus(value: unknown, asOf: string, minLots: string): value is PriceLotFocusData {
  if (!value || typeof value !== 'object' || !validFocusDate(asOf)) return false
  const data = value as PriceLotFocusData, minimum = minLotsShares(minLots)
  if (minimum === null || data.version !== 'price-lot-focus/m2-v1' || data.as_of !== asOf || data.min_lots !== minLots || data.min_shares !== minimum
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
    if (!read?.instrument || read.instrument.symbol !== symbols[index] || !validStockPriceMemoryRead(read.price_memory ?? undefined, read.instrument, asOf)) return false
  }
  if (!same(data.reads[0].price_memory!.provenance, data.reads[1].price_memory!.provenance)) return false
  const expected = data.reads.filter((read) => sharesMeetMinimum(read.price_memory!.latest!.volume_exact, minimum))
  return expected.length === data.items.length && expected.every((read, index) => {
    const item = data.items[index], bar = read.price_memory!.latest!, provenance = read.price_memory!.provenance!
    return item != null && item.exchange === 'TPEx' && item.symbol === read.instrument.symbol && item.name === read.instrument.name
      && item.volume_exact === bar.volume_exact && item.volume_lots === exactLotsText(bar.volume_exact) && item.min_lots === minLots
      && item.min_shares === minimum && item.reason === 'volume_at_least_min_lots' && item.source_date === asOf
      && item.source_version === provenance.source_version && item.detail_url === priceFocusDetailPath(item.symbol, asOf, minLots)
  })
}
