import type { Instrument, PriceFocusDayMove, PriceSavedFocusConsumer, PriceSavedFocusData, StockPriceSavedData, StockPriceSavedFocusData } from './types'
import { validStockPriceSavedRead } from './stockPriceSavedRead'
import { PRICE_SYMBOL_NAMES } from './stockPriceMemoryRead'
import { exactDayMove, exactDayRange, exactLotsText, minLotsShares, minRangeMilliPct, minTurnoverValue, rangeMeetsMinimum, sharesMeetMinimum, validFocusDate, validPriceFocusDayMove } from './priceFocus'

export const SAVED_FOCUS_VERSION = 'price-saved-focus/m1-v1'
export const SAVED_FOCUS_POLICY_VERSION = 'm1-saved-price-focus-tpex-11370-2026-10-06.1'
export const SAVED_FOCUS_POLICY_DIGEST = 'sha256:93059779e66d7826818db4a9eb9ea0a6856d631234b0efaa93c98241d6e5de3b'
export const SAVED_FOCUS_SYMBOLS = ['3105', '3293', '5274', '5347', '6488', '6510', '8069']
export const SAVED_CAPTURE_RECEIPT_SHA = '871a6887a3b87bd7c23c20fc3a25ec98d369d0df2ed8eedbe8cb040e5242cd36'
export const SAVED_STORAGE_RECEIPT_SHA = '436465b4d13d604965327fe1be7eff98edf65274b0f16c7871474280feb0197b'
export const SAVED_AT = '2026-10-06T23:32:45.499432+00:00'
const same = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right)
const proofKeys = ['policy_version', 'policy_digest', 'projection_version', 'origin', 'source_requests', 'disk_writes', 'db_mutations',
  'deadline_seconds', 'deadline_semantics', 'retained_graph_estimated_bytes', 'max_retained_graph_bytes']
const reasons = { up: 'close_above_open', down: 'close_below_open', flat: 'close_equal_open' }
const limitations = ['single_day_only', 'publication_first_available_revision_unknown', 'capture_saved_read_times_not_publication',
  'historical_pit_unsupported', 'no_history_calendar_ma20_signal_or_plan', 'no_capture_hydrate_copy_export_publish_delete_or_new_disk_cases']

export function validSavedFocusConsumer(value: unknown): value is PriceSavedFocusConsumer {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const p = value as PriceSavedFocusConsumer
  return same(Object.keys(p).sort(), [...proofKeys].sort()) && p.policy_version === SAVED_FOCUS_POLICY_VERSION
    && p.policy_digest === SAVED_FOCUS_POLICY_DIGEST && p.projection_version === SAVED_FOCUS_VERSION && p.origin === 'private_local'
    && p.source_requests === 0 && p.disk_writes === 0 && p.db_mutations === 0 && p.deadline_seconds === 10
    && p.deadline_semantics === 'cooperative_post_read_and_parse' && p.max_retained_graph_bytes === 33554432
    && Number.isInteger(p.retained_graph_estimated_bytes) && p.retained_graph_estimated_bytes > 0 && p.retained_graph_estimated_bytes <= 33554432
}

export function validAdmittedSavedRead(value: StockPriceSavedData | undefined, instrument: Instrument, asOf: string): value is StockPriceSavedData {
  return asOf === '2026-10-06' && validStockPriceSavedRead(value, instrument, asOf)
    && value.provenance!.body_bytes === 1788599 && value.provenance!.row_count === 12194
    && value.provenance!.receipt_sha256 === SAVED_CAPTURE_RECEIPT_SHA
    && value.storage_provenance!.capture_receipt_bytes === 1461 && value.storage_provenance!.saved_at === SAVED_AT
    && value.storage_provenance!.storage_receipt_sha256 === SAVED_STORAGE_RECEIPT_SHA
    && value.storage_state.action === 'reopened'
}

export function validSavedFocusStock(value: StockPriceSavedData | undefined, instrument: Instrument, asOf: string): value is StockPriceSavedFocusData {
  return validAdmittedSavedRead(value, instrument, asOf) && validSavedFocusConsumer((value as StockPriceSavedFocusData).focus_consumer)
}

export function validSavedFocusParams(params: URLSearchParams): boolean {
  const allowed = ['as_of', 'min_lots', 'day_move', 'min_turnover', 'min_range_pct']
  return !Array.from(params.keys()).some((key) => !allowed.includes(key))
    && ['as_of', 'min_lots'].every((key) => params.getAll(key).length === 1)
    && ['day_move', 'min_turnover', 'min_range_pct'].every((key) => params.getAll(key).length <= 1)
    && validFocusDate(params.get('as_of') ?? '') && minLotsShares(params.get('min_lots')) !== null
    && validPriceFocusDayMove(params.get('day_move') ?? 'all') && minTurnoverValue(params.get('min_turnover') ?? '0') !== null
    && minRangeMilliPct(params.get('min_range_pct') ?? '0') !== null
}

export function savedFocusDetailPath(symbol: string, asOf: string, minLots: string, dayMove: PriceFocusDayMove, minTurnover: string, minRangePct: string): string {
  return `/stocks/TPEx/${symbol}?${new URLSearchParams({ as_of: asOf, from: 'price-saved-focus', source_mode: 'private_saved',
    focus_as_of: asOf, focus_min_lots: minLots, focus_day_move: dayMove, focus_min_turnover: minTurnover, focus_min_range_pct: minRangePct })}`
}

export function savedFocusReturnPath(params: URLSearchParams): string | null {
  const required = ['as_of', 'from', 'source_mode', 'focus_as_of', 'focus_min_lots', 'focus_day_move', 'focus_min_turnover', 'focus_min_range_pct']
  if (params.get('from') !== 'price-saved-focus' || params.get('source_mode') !== 'private_saved'
    || Array.from(params.keys()).some((key) => !required.includes(key)) || required.some((key) => params.getAll(key).length !== 1)) return null
  const next = new URLSearchParams({ as_of: params.get('focus_as_of')!, min_lots: params.get('focus_min_lots')!, day_move: params.get('focus_day_move')!,
    min_turnover: params.get('focus_min_turnover')!, min_range_pct: params.get('focus_min_range_pct')! })
  return params.get('as_of') === next.get('as_of') && validSavedFocusParams(next) ? `/focus/price-saved?${next}` : null
}

export function validSavedPriceFocus(value: unknown, asOf: string, minLots: string, dayMove: PriceFocusDayMove, minTurnover: string, minRangePct: string): value is PriceSavedFocusData {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const data = value as PriceSavedFocusData, minimum = minLotsShares(minLots)
  if (data.version !== SAVED_FOCUS_VERSION || data.origin !== 'private_local' || data.as_of !== asOf || data.min_lots !== minLots
    || minimum === null || data.min_shares !== minimum || data.day_move !== dayMove || !validPriceFocusDayMove(dayMove)
    || minTurnoverValue(minTurnover) === null || minRangeMilliPct(minRangePct) === null || !validFocusDate(asOf)
    || data.min_turnover !== minTurnover || data.min_range_pct !== minRangePct || data.can_capture !== false
    || !same(data.supported_scope, { exchange: 'TPEx', asset_type: 'stock', currency: 'TWD', cutoff: '2026-10-06', symbols: SAVED_FOCUS_SYMBOLS })
    || data.sort !== 'code_ascending' || data.historical_pit !== 'unsupported' || !same(data.limitations, limitations)
    || !Array.isArray(data.items) || !Array.isArray(data.reads) || !Array.isArray(data.reasons) || data.reasons.some((r) => typeof r !== 'string')) return false
  if (data.status === 'unavailable') return data.count === null && data.items.length === 0 && data.reads.length === 0 && data.consumer_provenance === null && data.reasons.length > 0
  if (data.status !== 'available' || asOf !== '2026-10-06' || !validSavedFocusConsumer(data.consumer_provenance) || data.reasons.length
    || data.reads.length !== 7 || !Number.isInteger(data.count) || data.count !== data.items.length) return false
  for (let index = 0; index < 7; index++) {
    const read = data.reads[index]
    if (!read?.instrument || read.instrument.symbol !== SAVED_FOCUS_SYMBOLS[index] || read.instrument.name !== PRICE_SYMBOL_NAMES[read.instrument.symbol]
      || !validAdmittedSavedRead(read.price_saved, read.instrument, asOf)) return false
    const bar = read.price_saved.latest!
    if (exactDayMove(bar.source_fields['開盤'], bar.source_fields['收盤']) === null
      || exactDayRange(bar.source_fields['開盤'], bar.source_fields['最高'], bar.source_fields['最低']) === null
      || minTurnoverValue(bar.turnover_exact) === null || bar.turnover_status !== 'available' || bar.turnover_reason !== null) return false
  }
  if (data.reads.slice(1).some((read) => !same(read.price_saved.provenance, data.reads[0].price_saved.provenance)
    || !same(read.price_saved.storage_provenance, data.reads[0].price_saved.storage_provenance))) return false
  const expected = data.reads.filter((read) => {
    const bar = read.price_saved.latest!, move = exactDayMove(bar.source_fields['開盤'], bar.source_fields['收盤'])
    return sharesMeetMinimum(bar.volume_exact, minimum) && sharesMeetMinimum(bar.turnover_exact!, minTurnover) && (dayMove === 'all' || move === dayMove)
      && rangeMeetsMinimum(bar.source_fields['開盤'], bar.source_fields['最高'], bar.source_fields['最低'], minRangePct) === true
  })
  return expected.length === data.items.length && expected.every((read, index) => {
    const item = data.items[index], bar = read.price_saved.latest!, fields = bar.source_fields, move = exactDayMove(fields['開盤'], fields['收盤'])!
    return item?.exchange === 'TPEx' && item.symbol === read.instrument.symbol && item.name === read.instrument.name
      && item.volume_exact === bar.volume_exact && item.volume_lots === exactLotsText(bar.volume_exact) && item.min_lots === minLots && item.min_shares === minimum
      && item.min_turnover === minTurnover && item.turnover_exact === bar.turnover_exact && item.day_move === move
      && item.open_exact === fields['開盤'] && item.close_exact === fields['收盤'] && item.high_exact === fields['最高'] && item.low_exact === fields['最低']
      && item.min_range_pct === minRangePct && same(item.reasons, ['volume_at_least_min_lots', 'turnover_at_least_min_turnover', reasons[move], 'range_at_least_min_range_pct'])
      && item.source_date === asOf && item.source_version === read.price_saved.provenance!.source_version
      && item.detail_url === savedFocusDetailPath(item.symbol, asOf, minLots, dayMove, minTurnover, minRangePct)
  })
}
