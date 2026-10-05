import type { Instrument, StockPriceMemoryData } from './types'
import { memoryPriceCaptureReady, memoryPriceChartBars, PRICE_BODY_SHA, PRICE_ENDPOINT, PRICE_HEADERS, PRICE_POLICY_DIGEST, PRICE_POLICY_VERSION, validStockPriceMemoryRead } from './stockPriceMemoryRead'
export const priceFixtureInstrument = (symbol = '3105'): Instrument => ({
  id: symbol === '3105' ? 1 : 2, market: 'TW', exchange: 'TPEx', symbol, name: symbol === '3105' ? '穩懋' : '環球晶',
  instrument_type: 'stock', etf_category: null, is_watchlisted: false, status: 'active',
})

/** Pure client contract fixture: reconstructed six values, synthetic other CSV fields/receipt, no real raw. */
export function createPriceMemoryFixture(symbol = '3105'): StockPriceMemoryData {
  const instrument = priceFixtureInstrument(symbol)
  const values = symbol === '3105' ? [614, 630, 604, 615, '48127911', '29694939981'] : [1220, 1235, 1175, 1180, '18982607', '22887612060']
  const [open, high, low, close, volume, amount] = values as [number, number, number, number, string, string]
  const row = ['1151005', symbol, instrument.name, close.toFixed(2), '0', open.toFixed(2), high.toFixed(2), low.toFixed(2), '0', volume, amount, '0', '0', '0', '0', '0', '0', '0']
  const limitations = ['single_day_only', 'historical_pit_unsupported', 'no_history_calendar_ma20_signal_or_plan', 'capture_time_is_not_publication_time']
  const attribution = { owners: ['金融監督管理委員會證券期貨局', '財團法人中華民國證券櫃檯買賣中心'], dataset_name: '上櫃股票行情', year: 2026,
    release_version: 'data-date-2026-10-05', license: 'OGL-1.0', license_url: 'https://data.gov.tw/license',
    publication_time: 'unknown' as const, first_available_time: 'unknown' as const, revision_time: 'unknown' as const }
  const provenance = { worker_version: 'tpex-price-capture/m1-v1', source_id: 'tpex_11370_daily_close_csv', source_version: 'tpex-11370/2026-10-05',
    endpoint: PRICE_ENDPOINT, method: 'GET' as const, http_status: 200, request_count: 1, request_started_at: '2026-10-05T14:01:32.196378+00:00',
    captured_at: '2026-10-05T14:01:51.813710+00:00', body_sha256: PRICE_BODY_SHA, receipt_sha256: 'c'.repeat(64), body_bytes: 1773012,
    policy_version: PRICE_POLICY_VERSION, policy_digest: PRICE_POLICY_DIGEST, profile: 'free_public_local', storage: 'process_memory' as const,
    historical_pit: 'unsupported' as const, structural_validation: 'all_rows_header_width_date_unique_date_code', financial_validation: 'selected_symbols_only',
    row_count: 12060, selected_symbols: ['3105', '6488'], raw_payload_id: null, ingestion_run_id: null,
    memory_capture_id: 'tpex-11370:2026-10-05:' + PRICE_BODY_SHA, verification: 'pinned_raw_csv_selected_values', attribution, limitations }
  const bar = { id: null, origin: 'process_memory' as const, exchange: 'TPEx' as const, symbol, company_name: instrument.name, currency: 'TWD' as const,
    date: '2026-10-05', open, high, low, close, volume: Number(volume), volume_exact: volume, turnover: Number(amount), turnover_exact: amount,
    turnover_status: 'available' as const, turnover_reason: null, source: 'tpex' as const, source_date: '1151005', row_ordinal: symbol === '3105' ? 206 : 718,
    source_fields: Object.fromEntries(PRICE_HEADERS.map((field, index) => [field, row[index]])), is_suspended: false as const, adj_close: null,
    data_as_of: '2026-10-05', collected_at: provenance.captured_at, provenance }
  return { version: 'stock-price-memory/m1-v1', origin: 'process_memory', status: 'available', exchange: 'TPEx', symbol, as_of: '2026-10-05',
    supported_scope: { exchange: 'TPEx', asset_type: 'stock', currency: 'TWD', symbols: ['3105', '6488'], cutoff: '2026-10-05' },
    unit: 'shares', quantity_encoding: 'canonical_integer_string', price_unit: 'TWD_per_share', latest: bar, bars: [bar], provenance, attribution,
    historical_pit: 'unsupported', published_time: 'unknown', first_available_time: 'unknown', revision_time: 'unknown', reasons: [], limitations,
    capture_state: { enabled: true, attempted: true, busy: false, can_capture: false, cache_present: true, request_count: 1, action: 'cached' } }
}

export function runStockPriceMemoryReadTests(): number {
  let count = 0
  const check = (value: boolean, message: string) => { count++; if (!value) throw new Error(message) }
  for (const symbol of ['3105', '6488']) {
    const data = createPriceMemoryFixture(symbol), instrument = priceFixtureInstrument(symbol)
    check(validStockPriceMemoryRead(data, instrument, '2026-10-05'), 'selected contract accepts ' + symbol)
    const chart = memoryPriceChartBars(data, instrument, '2026-10-05')
    check(chart.length === 1 && chart[0].date === '2026-10-05' && chart[0].id === undefined && chart[0].volume_exact === data.latest!.volume_exact, 'single bar and no invented ID')
    check(!validStockPriceMemoryRead(data, instrument, '2026-10-02'), 'explicit cutoff conflict rejected')
    check(!validStockPriceMemoryRead({ ...data, as_of: '2026-10-02' }, instrument, '2026-10-05'), 'reversed memory envelope cutoff conflict rejected')
    for (const [key, value] of [['market', 'US'], ['name', 'unknown'], ['instrument_type', 'etf'], ['etf_category', 'domestic'], ['exchange', 'TWSE']] as const) {
      check(!validStockPriceMemoryRead(data, { ...instrument, [key]: value }, '2026-10-05'), 'catalogue identity pollution: ' + key)
    }
    for (const mutate of [
      (x: StockPriceMemoryData) => { x.unit = 'unknown' as 'shares' },
      (x: StockPriceMemoryData) => { x.provenance!.policy_digest = 'wrong' },
      (x: StockPriceMemoryData) => { x.provenance!.body_sha256 = '0'.repeat(64) },
      (x: StockPriceMemoryData) => { x.provenance!.endpoint += '&d=1151002' },
      (x: StockPriceMemoryData) => { x.provenance!.raw_payload_id = 1 as unknown as null },
      (x: StockPriceMemoryData) => { x.provenance!.captured_at = '2026-02-30T14:01:51+00:00' },
      (x: StockPriceMemoryData) => { x.provenance!.captured_at = '2026-10-05T14:02:03+00:00' },
      (x: StockPriceMemoryData) => { x.provenance!.limitations = [] },
      (x: StockPriceMemoryData) => { x.limitations = [] },
      (x: StockPriceMemoryData) => { x.latest!.source_fields['成交股數'] = '01' },
      (x: StockPriceMemoryData) => { x.latest!.volume_exact = '1\n' },
      (x: StockPriceMemoryData) => { x.latest!.high = 1 },
      (x: StockPriceMemoryData) => { x.capture_state.request_count = 2 },
    ]) {
      const altered = structuredClone(data); mutate(altered)
      // Keep duplicate projection equal so mutations test the field gate, not object duplication.
      altered.bars = [structuredClone(altered.latest!)]
      altered.latest!.provenance = altered.provenance!
      altered.bars[0].provenance = altered.provenance!
      check(!validStockPriceMemoryRead(altered, instrument, '2026-10-05'), 'polluted memory contract rejects')
    }
    const large = structuredClone(data)
    large.latest!.volume_exact = '9223372036854775807'; large.latest!.volume = null; large.latest!.source_fields['成交股數'] = large.latest!.volume_exact
    large.bars = [large.latest!]
    check(validStockPriceMemoryRead(large, instrument, '2026-10-05'), 'exact int64 is admitted without unsafe number projection')
    const missing = structuredClone(data); missing.latest!.turnover_exact = null; missing.latest!.turnover = null
    missing.latest!.source_fields['成交金額'] = ''; missing.latest!.turnover_status = 'unavailable'; missing.latest!.turnover_reason = 'missing'; missing.bars = [missing.latest!]
    check(validStockPriceMemoryRead(missing, instrument, '2026-10-05'), 'missing amount not replaced with zero')
    const ready = structuredClone(data); ready.status = 'unavailable'; ready.latest = null; ready.bars = []; ready.provenance = null; ready.attribution = null
    ready.reasons = ['price_memory_capture_missing']; ready.capture_state = { enabled: true, attempted: false, busy: false, can_capture: true, cache_present: false, request_count: 0, action: 'not_attempted' }
    check(memoryPriceCaptureReady(ready, 'TPEx', symbol, '2026-10-05'), 'explicit admitted scope ready')
    ready.symbol = 'constructor'
    check(!memoryPriceCaptureReady(ready, 'TPEx', 'constructor', '2026-10-05'), 'prototype name not selected')
  }
  return count
}
