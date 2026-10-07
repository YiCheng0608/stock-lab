import type { Instrument, StockPriceMemoryData } from './types'
import { memoryPriceCaptureReady, memoryPriceChartBars, priceSourcePins, PRICE_ENDPOINT, PRICE_HEADERS, PRICE_SCOPE_POLICY_VERSION, PRICE_SCOPE_POLICY_VERSION_V2, PRICE_SCOPE_POLICY_VERSION_V3, PRICE_SCOPE_POLICY_VERSION_V4, PRICE_SCOPE_POLICY_VERSION_V5, PRICE_SYMBOL_NAMES, validStockPriceMemoryRead } from './stockPriceMemoryRead'
export const priceFixtureInstrument = (symbol = '3105'): Instrument => ({
  id: ({ '3105': 1, '3293': 5, '5274': 4, '5347': 3, '6223': 8, '6488': 2, '6510': 7, '8069': 6 } as Record<string, number>)[symbol], market: 'TW', exchange: 'TPEx', symbol, name: PRICE_SYMBOL_NAMES[symbol],
  instrument_type: 'stock', etf_category: null, is_watchlisted: false, status: 'active',
})

/** Pure client contract fixture: reconstructed tuple-scoped selected values, synthetic other CSV fields/receipt, no real raw. */
export function createPriceMemoryFixture(symbol = '3105', cutoff = '2026-10-05', policyVersion?: string): StockPriceMemoryData {
  const instrument = priceFixtureInstrument(symbol)
  // New-day prices and unselected quantities are synthetic, not ROOT's observed finance.
  const values: Record<string, [number, number, number, number, string, string]> = cutoff === '2026-10-07'
    ? Object.fromEntries(priceSourcePins(cutoff)!.symbols.map((s) => [s, s === '6223' ? [100, 110, 100, 110, '896441', '4984488555'] : [100, 101, 99, 100, '100', '10000']]))
    : cutoff === '2026-10-06'
    ? { '3105': [615, 623, 588, 592, '19731700', '11863581093'], '3293': [794, 794, 772, 780, '1495462', '1164617657'], '5274': [19520, 19895, 18855, 18985, '188693', '3627465565'], '5347': [184.5, 195, 184.5, 191, '34637793', '6615109776'], '6488': [1175, 1260, 1145, 1205, '13913614', '16835605385'], '6510': [3125, 3140, 3050, 3055, '560518', '1729347985'], '8069': [147, 151.5, 145, 149, '10796741', '1607943663'] }
    : { '3105': [614, 630, 604, 615, '48127911', '29694939981'], '6488': [1220, 1235, 1175, 1180, '18982607', '22887612060'] }
  const pins = priceSourcePins(cutoff, policyVersion ?? (cutoff === '2026-10-06' ? 'm1-price-tpex-11370-2026-10-06.1' : undefined))!
  if (!pins || !pins.symbols.includes(symbol) || !values[symbol]) throw new Error('fixture tuple/symbol not supported')
  const [open, high, low, close, volume, amount] = values[symbol]
  const row = [cutoff === '2026-10-07' ? '1151007' : cutoff === '2026-10-05' ? '1151005' : '1151006', symbol, instrument.name, close.toFixed(2), '0', open.toFixed(2), high.toFixed(2), low.toFixed(2), '0', volume, amount, '0', '0', '0', '0', '0', '0', '0']
  const limitations = ['single_day_only', 'historical_pit_unsupported', 'no_history_calendar_ma20_signal_or_plan', 'capture_time_is_not_publication_time']
  const attribution = { owners: ['金融監督管理委員會證券期貨局', '財團法人中華民國證券櫃檯買賣中心'], dataset_name: '上櫃股票行情', year: 2026,
    release_version: 'data-date-' + cutoff, license: 'OGL-1.0', license_url: 'https://data.gov.tw/license',
    publication_time: 'unknown' as const, first_available_time: 'unknown' as const, revision_time: 'unknown' as const }
  const provenance = { worker_version: pins.workerVersion, source_id: 'tpex_11370_daily_close_csv', source_version: 'tpex-11370/' + cutoff,
    endpoint: PRICE_ENDPOINT, method: 'GET' as const, http_status: 200, request_count: 1, request_started_at: cutoff === '2026-10-05' ? '2026-10-05T14:01:32.196378+00:00' : '2026-10-06T09:21:17.268510+00:00',
    captured_at: cutoff === '2026-10-05' ? '2026-10-05T14:01:51.813710+00:00' : '2026-10-06T09:21:22.201440+00:00', body_sha256: pins.bodySha, receipt_sha256: 'c'.repeat(64), body_bytes: cutoff === '2026-10-05' ? 1773012 : 1788599,
    policy_version: pins.policyVersion, policy_digest: pins.policyDigest, profile: 'free_public_local', storage: 'process_memory' as const,
    historical_pit: 'unsupported' as const, structural_validation: 'all_rows_header_width_date_unique_date_code', financial_validation: 'selected_symbols_only',
    row_count: cutoff === '2026-10-05' ? 12060 : 12194, selected_symbols: pins.symbols, raw_payload_id: null, ingestion_run_id: null,
    memory_capture_id: 'tpex-11370:' + cutoff + ':' + pins.bodySha, verification: 'pinned_raw_csv_selected_values', attribution, limitations }
  const bar = { id: null, origin: 'process_memory' as const, exchange: 'TPEx' as const, symbol, company_name: instrument.name, currency: 'TWD' as const,
    date: cutoff, open, high, low, close, volume: Number(volume), volume_exact: volume, turnover: Number(amount), turnover_exact: amount,
    turnover_status: 'available' as const, turnover_reason: null, source: 'tpex' as const, source_date: row[0], row_ordinal: ({ '3105': 205, '3293': 255, '5274': 513, '5347': 532, '6488': 717, '6510': 726, '8069': 12098 } as Record<string, number>)[symbol],
    source_fields: Object.fromEntries(PRICE_HEADERS.map((field, index) => [field, row[index]])), is_suspended: false as const, adj_close: null,
    data_as_of: cutoff, collected_at: provenance.captured_at, provenance }
  if (cutoff === '2026-10-07') {
    provenance.request_started_at = '2026-10-07T08:00:00.000000Z'; provenance.captured_at = '2026-10-07T08:00:01.000000Z'
    provenance.body_bytes = 2048; provenance.row_count = 8
    bar.row_ordinal = pins.symbols.indexOf(symbol) + 1; bar.collected_at = provenance.captured_at
  }
  return { version: pins.memoryVersion, origin: 'process_memory', status: 'available', exchange: 'TPEx', symbol, as_of: cutoff,
    supported_scope: { exchange: 'TPEx', asset_type: 'stock', currency: 'TWD', symbols: pins.symbols, cutoff },
    unit: 'shares', quantity_encoding: 'canonical_integer_string', price_unit: 'TWD_per_share', latest: bar, bars: [bar], provenance, attribution,
    historical_pit: 'unsupported', published_time: 'unknown', first_available_time: 'unknown', revision_time: 'unknown', reasons: [], limitations,
    capture_state: { enabled: true, attempted: true, busy: false, can_capture: false, cache_present: true, request_count: 1, action: 'cached' } }
}

export function runScopeMemoryReadTests(): number {
  let checks = 0
  const check = (value: boolean, message: string) => { checks++; if (!value) throw new Error(message) }
  const day = '2026-10-07', data = createPriceMemoryFixture('6223', day), instrument = priceFixtureInstrument('6223')
  check(validStockPriceMemoryRead(data, instrument, day), 'new-day eighth contract')
  check(!validStockPriceMemoryRead(data, instrument, '2026-10-06') && priceSourcePins(day, PRICE_SCOPE_POLICY_VERSION_V5) === null, 'crossed dates and policies')
  for (const [key, value] of [['name', 'wrong'], ['market', 'US'], ['instrument_type', 'etf'], ['currency', 'USD']] as const)
    check(!validStockPriceMemoryRead(data, { ...instrument, [key]: value }, day), 'eighth identity ' + key)
  for (const [key, value] of [['資料日期', '1151006'], ['成交股數', '0896441'], ['成交金額', '9223372036854775808'], ['最高', '99.00']] as const) {
    const prior = data.latest!.source_fields[key]; data.latest!.source_fields[key] = value
    check(!validStockPriceMemoryRead(data, instrument, day), 'invalid eighth original ' + key); data.latest!.source_fields[key] = prior
  }
  const oldPins = [PRICE_SCOPE_POLICY_VERSION, PRICE_SCOPE_POLICY_VERSION_V2, PRICE_SCOPE_POLICY_VERSION_V3, PRICE_SCOPE_POLICY_VERSION_V4, PRICE_SCOPE_POLICY_VERSION_V5]
  for (const policy of oldPins) check(!priceSourcePins('2026-10-06', policy)!.symbols.includes('6223'), 'old scopes exclude eighth')
  check(priceSourcePins('2026-10-06')!.policyVersion === PRICE_SCOPE_POLICY_VERSION_V5 && priceSourcePins('2026-10-05')!.policyVersion === 'm1-price-tpex-11370-2026-10-05.1', 'old defaults unchanged')
  data.status = 'unavailable'; data.latest = null; data.bars = []; data.provenance = null; data.attribution = null
  data.reasons = ['price_memory_capture_missing']; data.capture_state = { enabled: true, attempted: false, busy: false, can_capture: true, cache_present: false, request_count: 0, action: 'not_attempted' }
  check(memoryPriceCaptureReady(data, 'TPEx', '6223', day), 'new empty Store ready')
  data.capture_state.attempted = true; data.capture_state.can_capture = false
  check(!memoryPriceCaptureReady(data, 'TPEx', '6223', day), 'failed attempt cannot acquire again')
  return checks
}

export function runStockPriceMemoryReadTests(): number {
  let count = 0
  const check = (value: boolean, message: string) => { count++; if (!value) throw new Error(message) }
  check(priceSourcePins('2026-10-06', PRICE_SCOPE_POLICY_VERSION_V4)!.policyVersion === PRICE_SCOPE_POLICY_VERSION_V4 && priceSourcePins('2026-10-06', PRICE_SCOPE_POLICY_VERSION_V4)!.symbols.join() === '3105,3293,5274,5347,6488,8069', 'explicit six-stock pins retained')
  check(priceSourcePins('2026-10-06', PRICE_SCOPE_POLICY_VERSION_V3)!.symbols.join() === '3105,3293,5274,5347,6488', 'explicit five-stock pins retained')
  check(priceSourcePins('2026-10-06')!.policyVersion === PRICE_SCOPE_POLICY_VERSION_V5 && priceSourcePins('2026-10-06')!.symbols.join() === '3105,3293,5274,5347,6488,6510,8069', 'seven-stock default pins')
  const seventh = createPriceMemoryFixture('6510', '2026-10-06', PRICE_SCOPE_POLICY_VERSION_V5), seventhInstrument = priceFixtureInstrument('6510')
  check(validStockPriceMemoryRead(seventh, seventhInstrument, '2026-10-06') && seventh.latest!.volume_exact === '560518' && seventh.latest!.turnover_exact === '1729347985', 'seventh independent exact values and new tuple')
  check(memoryPriceChartBars(seventh, seventhInstrument, '2026-10-06')[0].close === 3055 && seventh.latest!.row_ordinal === 726, 'seventh chart unit and reconstructed source ordinal')
  for (const mutate of [
    (x: StockPriceMemoryData) => { x.version = 'stock-price-memory/m2-stock-scope-v4' },
    (x: StockPriceMemoryData) => { x.provenance!.policy_version = PRICE_SCOPE_POLICY_VERSION_V4 },
    (x: StockPriceMemoryData) => { x.supported_scope.symbols = ['3105', '3293', '5274', '5347', '6488', '8069'] },
    (x: StockPriceMemoryData) => { x.provenance!.selected_symbols = ['3105', '3293', '5274', '5347', '6488', '6510', '6510'] },
    (x: StockPriceMemoryData) => { x.latest!.source_fields['名稱'] = 'wrong' },
    (x: StockPriceMemoryData) => { x.latest!.source_fields['成交股數'] = '0560518' },
    (x: StockPriceMemoryData) => { x.latest!.source_fields['最低'] = '3141.00' },
  ]) { const bad = structuredClone(seventh); mutate(bad); check(!validStockPriceMemoryRead(bad, seventhInstrument, '2026-10-06'), 'seventh crossed tuple, duplicate scope or bad financial field rejected') }
  for (const [key, value] of [['name', 'wrong'], ['exchange', 'TWSE'], ['instrument_type', 'etf'], ['etf_category', 'mixed'], ['currency', 'unknown']] as const)
    check(!validStockPriceMemoryRead(seventh, { ...seventhInstrument, [key]: value }, '2026-10-06'), 'seventh identity guarded ' + key)
  check(!validStockPriceMemoryRead(seventh, seventhInstrument, '2026-10-05'), 'seventh never leaks into old date')
  const unloadedSeven = structuredClone(seventh)
  unloadedSeven.status = 'unavailable'; unloadedSeven.latest = null; unloadedSeven.bars = []; unloadedSeven.provenance = null; unloadedSeven.attribution = null
  unloadedSeven.reasons = ['price_memory_capture_missing']; unloadedSeven.capture_state = { enabled: true, attempted: false, busy: false, can_capture: true, cache_present: false, request_count: 0, action: 'not_attempted' }
  check(memoryPriceCaptureReady(unloadedSeven, 'TPEx', '6510', '2026-10-06'), 'unloaded seven-stock projection ready')
  check(!priceSourcePins('2026-10-06', PRICE_SCOPE_POLICY_VERSION_V4)!.symbols.includes('6510'), 'seventh absent from explicit prior six policy')
  const sixth = createPriceMemoryFixture('8069', '2026-10-06', PRICE_SCOPE_POLICY_VERSION_V4), sixthInstrument = priceFixtureInstrument('8069')
  check(validStockPriceMemoryRead(sixth, sixthInstrument, '2026-10-06') && sixth.latest!.volume_exact === '10796741' && sixth.latest!.turnover_exact === '1607943663', 'sixth independent exact values and new tuple')
  check(memoryPriceChartBars(sixth, sixthInstrument, '2026-10-06')[0].close === 149 && sixth.latest!.row_ordinal === 12098, 'sixth chart unit and reconstructed source ordinal')
  for (const mutate of [
    (x: StockPriceMemoryData) => { x.version = 'stock-price-memory/m2-stock-scope-v3' },
    (x: StockPriceMemoryData) => { x.provenance!.policy_version = PRICE_SCOPE_POLICY_VERSION_V3 },
    (x: StockPriceMemoryData) => { x.supported_scope.symbols = ['3105', '3293', '5274', '5347', '6488'] },
    (x: StockPriceMemoryData) => { x.provenance!.selected_symbols = ['3105', '3293', '5274', '5347', '6488', '6488'] },
    (x: StockPriceMemoryData) => { x.latest!.source_fields['名稱'] = 'wrong' },
    (x: StockPriceMemoryData) => { x.latest!.source_fields['成交股數'] = '010796741' },
    (x: StockPriceMemoryData) => { x.latest!.source_fields['最低'] = '152.00' },
  ]) { const bad = structuredClone(sixth); mutate(bad); check(!validStockPriceMemoryRead(bad, sixthInstrument, '2026-10-06'), 'sixth crossed tuple, duplicate scope or bad financial field rejected') }
  for (const [key, value] of [['name', 'wrong'], ['exchange', 'TWSE'], ['instrument_type', 'etf'], ['etf_category', 'mixed'], ['currency', 'unknown']] as const)
    check(!validStockPriceMemoryRead(sixth, { ...sixthInstrument, [key]: value }, '2026-10-06'), 'sixth identity guarded ' + key)
  check(!validStockPriceMemoryRead(sixth, sixthInstrument, '2026-10-05'), 'sixth never leaks into old date')
  const unloadedSix = structuredClone(sixth)
  unloadedSix.status = 'unavailable'; unloadedSix.latest = null; unloadedSix.bars = []; unloadedSix.provenance = null; unloadedSix.attribution = null
  unloadedSix.reasons = ['price_memory_capture_missing']; unloadedSix.capture_state = { enabled: true, attempted: false, busy: false, can_capture: true, cache_present: false, request_count: 0, action: 'not_attempted' }
  check(memoryPriceCaptureReady(unloadedSix, 'TPEx', '8069', '2026-10-06'), 'unloaded six-stock projection ready')
  check(!priceSourcePins('2026-10-06', PRICE_SCOPE_POLICY_VERSION_V3)!.symbols.includes('8069'), 'sixth absent from explicit prior five policy')
  check(priceSourcePins('2026-10-06', PRICE_SCOPE_POLICY_VERSION_V2)!.symbols.join() === '3105,5274,5347,6488', 'four-stock explicit immutable pins')
  const fifth = createPriceMemoryFixture('3293', '2026-10-06', PRICE_SCOPE_POLICY_VERSION_V3), fifthInstrument = priceFixtureInstrument('3293')
  check(validStockPriceMemoryRead(fifth, fifthInstrument, '2026-10-06') && fifth.latest!.volume_exact === '1495462' && fifth.latest!.turnover_exact === '1164617657', 'fifth exact selected financial values')
  check(memoryPriceChartBars(fifth, fifthInstrument, '2026-10-06')[0].close === 780, 'fifth single-day chart preserves per-share price')
  for (const policy of [PRICE_SCOPE_POLICY_VERSION_V2, PRICE_SCOPE_POLICY_VERSION, 'm1-price-tpex-11370-2026-10-06.1']) check(!priceSourcePins('2026-10-06', policy)!.symbols.includes('3293'), 'all old immutable scopes exclude fifth')
  for (const mutate of [
    (x: StockPriceMemoryData) => { x.provenance!.policy_version = PRICE_SCOPE_POLICY_VERSION_V2 },
    (x: StockPriceMemoryData) => { x.supported_scope.symbols = ['3105', '5274', '5347', '6488'] },
    (x: StockPriceMemoryData) => { x.provenance!.selected_symbols = ['3105', '5274', '5347', '6488'] },
    (x: StockPriceMemoryData) => { x.latest!.source_fields['名稱'] = '鈐象' },
    (x: StockPriceMemoryData) => { x.latest!.source_fields['成交股數'] = '01495462' },
    (x: StockPriceMemoryData) => { x.latest!.source_fields['最高'] = '0' },
  ]) {
    const altered = structuredClone(fifth); mutate(altered); altered.latest!.provenance = altered.provenance!; altered.bars = [altered.latest!]
    check(!validStockPriceMemoryRead(altered, fifthInstrument, '2026-10-06'), 'fifth crossed tuple or invalid selected field rejected')
  }
  for (const [key, value] of [['name', '鈐象'], ['instrument_type', 'etf'], ['etf_category', 'domestic'], ['exchange', 'TWSE']] as const) check(!validStockPriceMemoryRead(fifth, { ...fifthInstrument, [key]: value }, '2026-10-06'), 'fifth identity guard ' + key)
  const unloadedFifth = structuredClone(fifth)
  unloadedFifth.status = 'unavailable'; unloadedFifth.latest = null; unloadedFifth.bars = []; unloadedFifth.provenance = null; unloadedFifth.attribution = null
  unloadedFifth.reasons = ['price_memory_capture_missing']; unloadedFifth.capture_state = { enabled: true, attempted: false, busy: false, can_capture: true, cache_present: false, request_count: 0, action: 'not_attempted' }
  check(memoryPriceCaptureReady(unloadedFifth, 'TPEx', '3293', '2026-10-06'), 'fifth unloaded explicit scope ready')
  const fourth = createPriceMemoryFixture('5274', '2026-10-06', PRICE_SCOPE_POLICY_VERSION_V2), fourthInstrument = priceFixtureInstrument('5274')
  check(validStockPriceMemoryRead(fourth, fourthInstrument, '2026-10-06') && fourth.latest!.volume_exact === '188693' && fourth.latest!.turnover_exact === '3627465565', 'new fourth stock exact source fields and accepted tuple')
  check(memoryPriceChartBars(fourth, fourthInstrument, '2026-10-06')[0].close === 18985, 'fourth chart keeps TWD per share')
  for (const mutate of [
    (x: StockPriceMemoryData) => { x.provenance!.policy_version = PRICE_SCOPE_POLICY_VERSION },
    (x: StockPriceMemoryData) => { x.supported_scope.symbols = ['3105', '5347', '6488'] },
    (x: StockPriceMemoryData) => { x.provenance!.selected_symbols = ['3105', '5347', '6488'] },
    (x: StockPriceMemoryData) => { x.latest!.source_fields['名稱'] = 'wrong' },
    (x: StockPriceMemoryData) => { x.latest!.source_fields['成交股數'] = '01' },
    (x: StockPriceMemoryData) => { x.latest!.source_fields['最高'] = '0' },
  ]) {
    const altered = structuredClone(fourth); mutate(altered); altered.latest!.provenance = altered.provenance!; altered.bars = [altered.latest!]
    check(!validStockPriceMemoryRead(altered, fourthInstrument, '2026-10-06'), 'fourth crossed scope or financial field rejected')
  }
  for (const [key, value] of [['name', 'wrong'], ['instrument_type', 'etf'], ['etf_category', 'domestic'], ['exchange', 'TWSE']] as const) check(!validStockPriceMemoryRead(fourth, { ...fourthInstrument, [key]: value }, '2026-10-06'), 'fourth identity and ETF guard ' + key)
  for (const policy of [PRICE_SCOPE_POLICY_VERSION, 'm1-price-tpex-11370-2026-10-06.1']) check(!priceSourcePins('2026-10-06', policy)!.symbols.includes('5274'), 'old immutable scope excludes fourth')
  const third = createPriceMemoryFixture('5347', '2026-10-06', PRICE_SCOPE_POLICY_VERSION)
  const thirdInstrument = priceFixtureInstrument('5347')
  for (const loaded of [fourth, third]) {
    const unloaded = structuredClone(loaded)
    unloaded.status = 'unavailable'; unloaded.latest = null; unloaded.bars = []; unloaded.provenance = null; unloaded.attribution = null
    unloaded.reasons = ['price_memory_capture_missing']
    unloaded.capture_state = { enabled: true, attempted: false, busy: false, can_capture: true, cache_present: false, request_count: 0, action: 'not_attempted' }
    check(memoryPriceCaptureReady(unloaded, 'TPEx', unloaded.symbol, '2026-10-06'), 'unloaded preserved three/new four projection selects its own tuple')
    unloaded.supported_scope.symbols = ['3105', '9999', '6488']
    check(!memoryPriceCaptureReady(unloaded, 'TPEx', unloaded.symbol, '2026-10-06'), 'unloaded crossed or unknown scope cannot acquire')
  }
  check(validStockPriceMemoryRead(third, thirdInstrument, '2026-10-06'), 'new three-stock tuple accepts exact third identity and values')
  check(third.latest!.volume_exact === '34637793' && memoryPriceChartBars(third, thirdInstrument, '2026-10-06')[0].close === 191, 'third exact shares and per-share chart')
  for (const mutate of [
    (x: StockPriceMemoryData) => { x.provenance!.policy_version = 'unknown' },
    (x: StockPriceMemoryData) => { x.provenance!.policy_digest = 'sha256:' + '0'.repeat(64) },
    (x: StockPriceMemoryData) => { x.provenance!.selected_symbols = ['3105', '6488'] },
    (x: StockPriceMemoryData) => { x.supported_scope.symbols = ['3105', '6488'] },
    (x: StockPriceMemoryData) => { x.latest!.source_fields['名稱'] = 'unknown' },
    (x: StockPriceMemoryData) => { x.latest!.source_fields['成交股數'] = '01' },
    (x: StockPriceMemoryData) => { x.latest!.source_fields['最高'] = '0' },
  ]) {
    const altered = structuredClone(third); mutate(altered); altered.latest!.provenance = altered.provenance!; altered.bars = [altered.latest!]
    check(!validStockPriceMemoryRead(altered, thirdInstrument, '2026-10-06'), 'third polluted tuple/financial field rejected')
  }
  for (const symbol of ['3105', '6488']) {
    const fresh = createPriceMemoryFixture(symbol, '2026-10-06'), instrument = priceFixtureInstrument(symbol)
    check(validStockPriceMemoryRead(fresh, instrument, '2026-10-06'), 'new immutable tuple and twelve selected values ' + symbol)
    check(memoryPriceChartBars(fresh, instrument, '2026-10-06')[0].close === (symbol === '3105' ? 592 : 1205), 'new M1 chart keeps per-share close')
    check(!validStockPriceMemoryRead(fresh, instrument, '2026-10-05'), 'new body cannot claim old date')
    for (const key of ['worker_version', 'policy_version', 'policy_digest', 'body_sha256'] as const) {
      const altered = structuredClone(fresh), old = createPriceMemoryFixture(symbol)
      altered.provenance![key] = old.provenance![key]; altered.latest!.provenance = altered.provenance!; altered.bars = [altered.latest!]
      check(!validStockPriceMemoryRead(altered, instrument, '2026-10-06'), 'crossed old:new tuple rejected ' + key)
    }
  }
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
