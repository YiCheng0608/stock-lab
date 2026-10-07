import type { PriceFocusDayMove, PriceSavedFocusConsumer, PriceSavedFocusData, StockPriceSavedFocusData } from './types'
import { createPriceSavedFixture } from './stockPriceSavedRead.test'
import { priceFixtureInstrument } from './stockPriceMemoryRead.test'
import { exactDayMove, exactLotsText, minLotsShares, rangeMeetsMinimum, sharesMeetMinimum } from './priceFocus'
import { SAVED_AT, SAVED_CAPTURE_RECEIPT_SHA, SAVED_FOCUS_POLICY_DIGEST, SAVED_FOCUS_POLICY_VERSION, SAVED_FOCUS_SYMBOLS, SAVED_FOCUS_VERSION,
  SAVED_STORAGE_RECEIPT_SHA, savedFocusDetailPath, savedFocusReturnPath, validSavedFocusConsumer, validSavedFocusParams, validSavedFocusStock, validSavedPriceFocus } from './savedPriceFocus'

/** Reconstructed client-only contracts; no official raw/private-file evidence. */
export function syntheticConsumerProof(): PriceSavedFocusConsumer {
  return { policy_version: SAVED_FOCUS_POLICY_VERSION, policy_digest: SAVED_FOCUS_POLICY_DIGEST, projection_version: SAVED_FOCUS_VERSION,
    origin: 'private_local', source_requests: 0, disk_writes: 0, db_mutations: 0, deadline_seconds: 10,
    deadline_semantics: 'cooperative_post_read_and_parse', retained_graph_estimated_bytes: 4096, max_retained_graph_bytes: 33554432 }
}

export function createSavedFocusStockFixture(symbol = '6510'): StockPriceSavedFocusData {
  const data = createPriceSavedFixture(symbol)
  data.provenance!.receipt_sha256 = SAVED_CAPTURE_RECEIPT_SHA
  data.provenance!.request_started_at = '2026-10-06T23:32:17.666931+00:00'
  data.provenance!.captured_at = '2026-10-06T23:32:21.005311+00:00'
  data.latest!.collected_at = data.provenance!.captured_at
  data.latest!.provenance = data.provenance!
  data.bars = [structuredClone(data.latest!)]
  data.storage_provenance!.capture_receipt_sha256 = SAVED_CAPTURE_RECEIPT_SHA
  data.storage_provenance!.saved_at = SAVED_AT
  data.storage_provenance!.captured_at = data.provenance!.captured_at
  data.storage_provenance!.request_started_at = data.provenance!.request_started_at
  data.storage_provenance!.storage_receipt_sha256 = SAVED_STORAGE_RECEIPT_SHA
  return { ...data, focus_consumer: syntheticConsumerProof() }
}

export function createSavedPriceFocusFixture(minLots = '0', dayMove: PriceFocusDayMove = 'all', minTurnover = '0', minRangePct = '0'): PriceSavedFocusData {
  const reads = SAVED_FOCUS_SYMBOLS.map((symbol) => {
    const { focus_consumer, ...price_saved } = createSavedFocusStockFixture(symbol)
    void focus_consumer
    return { instrument: priceFixtureInstrument(symbol), price_saved }
  })
  const minimum = minLotsShares(minLots)!
  const items = reads.filter(({ price_saved }) => {
    const bar = price_saved.latest!, fields = bar.source_fields
    return sharesMeetMinimum(bar.volume_exact, minimum) && sharesMeetMinimum(bar.turnover_exact!, minTurnover)
      && (dayMove === 'all' || dayMove === exactDayMove(fields['開盤'], fields['收盤']))
      && rangeMeetsMinimum(fields['開盤'], fields['最高'], fields['最低'], minRangePct) === true
  }).map(({ instrument, price_saved }) => {
    const bar = price_saved.latest!, fields = bar.source_fields, move = exactDayMove(fields['開盤'], fields['收盤'])!
    return { exchange: 'TPEx' as const, symbol: instrument.symbol, name: instrument.name, volume_exact: bar.volume_exact,
      volume_lots: exactLotsText(bar.volume_exact), min_lots: minLots, min_shares: minimum, min_turnover: minTurnover,
      turnover_exact: bar.turnover_exact!, day_move: move, open_exact: fields['開盤'], close_exact: fields['收盤'], min_range_pct: minRangePct,
      high_exact: fields['最高'], low_exact: fields['最低'], reasons: ['volume_at_least_min_lots', 'turnover_at_least_min_turnover',
        move === 'up' ? 'close_above_open' : move === 'down' ? 'close_below_open' : 'close_equal_open', 'range_at_least_min_range_pct'] as PriceSavedFocusData['items'][number]['reasons'],
      source_date: '2026-10-06', source_version: price_saved.provenance!.source_version,
      detail_url: savedFocusDetailPath(instrument.symbol, '2026-10-06', minLots, dayMove, minTurnover, minRangePct) }
  })
  return { version: SAVED_FOCUS_VERSION, origin: 'private_local', status: 'available', as_of: '2026-10-06', min_lots: minLots,
    min_shares: minimum, day_move: dayMove, min_turnover: minTurnover, min_range_pct: minRangePct, count: items.length, items, reads,
    supported_scope: { exchange: 'TPEx', asset_type: 'stock', currency: 'TWD', cutoff: '2026-10-06', symbols: [...SAVED_FOCUS_SYMBOLS] },
    consumer_provenance: syntheticConsumerProof(), can_capture: false, reasons: [], historical_pit: 'unsupported', sort: 'code_ascending',
    limitations: ['single_day_only', 'publication_first_available_revision_unknown', 'capture_saved_read_times_not_publication', 'historical_pit_unsupported',
      'no_history_calendar_ma20_signal_or_plan', 'no_capture_hydrate_copy_export_publish_delete_or_new_disk_cases'] }
}

export function runSavedPriceFocusTests(): number {
  let count = 0
  const check = (condition: unknown, message: string) => { count++; if (!condition) throw new Error(message) }
  for (const [lots, move, amount, range, expected] of [['0.000', 'all', '0', '0.000', '3105,3293,5274,5347,6488,6510,8069'],
    ['560.518', 'down', '1729347985', '2.880', '3105,6510'], ['560.519', 'down', '1729347985', '2.880', '3105'],
    ['560.518', 'down', '1729347986', '2.880', '3105'], ['560.518', 'down', '1729347985', '2.881', '3105'], ['0', 'all', '0', '10', '']]) {
    const data = createSavedPriceFocusFixture(lots, move as PriceFocusDayMove, amount, range)
    check(validSavedPriceFocus(data, '2026-10-06', lots, move as PriceFocusDayMove, amount, range), 'strict independent saved focus')
    check(data.items.map((item) => item.symbol).join() === expected, 'exact inclusive neighbouring thresholds')
    check(data.reads.length === 7, 'all seven checked even for true zero')
  }
  for (const symbol of SAVED_FOCUS_SYMBOLS) check(validSavedFocusStock(createSavedFocusStockFixture(symbol), priceFixtureInstrument(symbol), '2026-10-06'), 'same-stock consumer receipt')
  const source = createSavedPriceFocusFixture()
  const mutations: Array<(data: PriceSavedFocusData) => void> = [
    (d) => { d.version = 'price-lot-focus/m2-v9' }, (d) => { d.origin = 'process_memory' as never },
    (d) => { d.consumer_provenance!.policy_digest = 'wrong' }, (d) => { d.consumer_provenance!.source_requests = 1 as never },
    (d) => { d.consumer_provenance!.retained_graph_estimated_bytes = 33554433 }, (d) => { d.reads.pop() },
    (d) => { d.reads.reverse() }, (d) => { d.items.reverse() }, (d) => { d.items.pop() }, (d) => { d.count = 0 },
    (d) => { d.items[0].detail_url = '/stocks/TPEx/3105?as_of=2026-10-05' },
    (d) => { d.reads[6].price_saved.storage_provenance!.saved_at = '2026-10-07T00:00:00+00:00' },
    (d) => { d.reads[6].price_saved.storage_provenance!.storage_receipt_sha256 = 'e'.repeat(64) },
    (d) => { d.reads[6].price_saved.provenance!.receipt_sha256 = 'e'.repeat(64) },
    (d) => { d.reads[6].price_saved.latest!.turnover_exact = null },
    (d) => { d.reads[6].price_saved.latest!.source_fields['成交股數'] = '0' },
  ]
  for (const mutate of mutations) {
    const data = structuredClone(source); mutate(data)
    check(!validSavedPriceFocus(data, '2026-10-06', '0', 'all', '0', '0'), 'wrong/partial source never adopted')
  }
  const unavailable = { ...source, status: 'unavailable' as const, count: null, reads: [], items: [], consumer_provenance: null, reasons: ['price_saved_capture_missing'] }
  check(validSavedPriceFocus(unavailable, '2026-10-06', '0', 'all', '0', '0'), 'unavailable is unknown count')
  check(!validSavedPriceFocus({ ...unavailable, count: 0 }, '2026-10-06', '0', 'all', '0', '0'), 'unknown never zero')
  const detail = savedFocusDetailPath('6510', '2026-10-06', '560.518', 'down', '1729347985', '2.880')
  const params = new URLSearchParams(detail.split('?')[1]), back = savedFocusReturnPath(params)
  check(back === '/focus/price-saved?as_of=2026-10-06&min_lots=560.518&day_move=down&min_turnover=1729347985&min_range_pct=2.880', 'five exact strings and source mode return')
  for (const [key, value] of [['source_mode', 'memory'], ['from', 'price-lots'], ['as_of', '2026-10-05'], ['focus_min_lots', '01'], ['focus_min_range_pct', '2.8800']]) {
    const bad = new URLSearchParams(params); bad.set(key, value)
    check(savedFocusReturnPath(bad) === null, 'bad context rejected')
  }
  const duplicate = new URLSearchParams(params); duplicate.append('focus_min_lots', '0')
  check(savedFocusReturnPath(duplicate) === null, 'duplicate detail context rejected')
  const query = new URLSearchParams('as_of=2026-10-06&min_lots=0&day_move=all&min_turnover=0&min_range_pct=0')
  check(validSavedFocusParams(query), 'valid saved filter params')
  for (const addition of ['&as_of=2026-10-06', '&unknown=1', '&min_lots=0']) check(!validSavedFocusParams(new URLSearchParams(query + addition)), 'duplicate/unknown filter params rejected')
  check(!validSavedFocusConsumer({ ...syntheticConsumerProof(), path: 'C:/private' }), 'consumer proof exact schema')
  return count
}
