import type { StockPriceSavedData } from './types'
import { createPriceMemoryFixture, priceFixtureInstrument } from './stockPriceMemoryRead.test'
import { PRICE_SCOPE_POLICY_VERSION_V5, validStockPriceMemoryRead } from './stockPriceMemoryRead'
import { PRICE_SAVED_VERSION, PRICE_STORAGE_POLICY_VERSION, PRICE_STORAGE_POLICY_DIGEST, savedPriceChartBars, validStockPriceSavedRead } from './stockPriceSavedRead'

/** Client-only reconstructed contract, not raw/source/disk evidence. */
export function createPriceSavedFixture(symbol = '6510'): StockPriceSavedData {
  const observation = createPriceMemoryFixture(symbol, '2026-10-06', PRICE_SCOPE_POLICY_VERSION_V5)
  const { memory_capture_id, ...original } = observation.provenance!
  const source = { ...original, capture_id: memory_capture_id, verification: 'private_raw_csv_selected_values' as const }
  const bar = { ...observation.latest!, origin: 'private_local' as const, provenance: source }
  const { capture_state, ...base } = observation
  void capture_state
  return { ...base, version: PRICE_SAVED_VERSION, origin: 'private_local', latest: bar, bars: [bar], provenance: source,
    storage_provenance: { version: 'tpex-price-storage-receipt/m1-v1', storage: 'private_local',
      storage_policy_version: PRICE_STORAGE_POLICY_VERSION, storage_policy_digest: PRICE_STORAGE_POLICY_DIGEST,
      capture_policy_version: source.policy_version, capture_policy_digest: source.policy_digest, source_id: source.source_id,
      source_version: source.source_version, endpoint: source.endpoint, method: 'GET', as_of: '2026-10-06', selected_symbols: source.selected_symbols,
      body_sha256: source.body_sha256, body_bytes: source.body_bytes, capture_receipt_sha256: source.receipt_sha256,
      capture_receipt_bytes: 1461, captured_at: source.captured_at, request_started_at: source.request_started_at,
      saved_at: '2026-10-07T00:00:00+00:00', attribution: source.attribution, limitations: source.limitations, storage_receipt_sha256: 'd'.repeat(64) },
    storage_state: { enabled: true, verified: true, action: 'reopened', network_requests: 0 } }
}

export function runStockPriceSavedReadTests(): number {
  let count = 0
  const check = (condition: boolean, message: string) => { count++; if (!condition) throw new Error(message) }
  for (const symbol of ['3105', '3293', '5274', '5347', '6488', '6510', '8069']) {
    const data = createPriceSavedFixture(symbol), instrument = priceFixtureInstrument(symbol)
    check(validStockPriceSavedRead(data, instrument, '2026-10-06'), 'strict saved seven-stock contract')
    check(savedPriceChartBars(data, instrument, '2026-10-06').length === 1, 'one saved bar')
    check(!validStockPriceSavedRead(data, instrument, '2026-10-05') && !validStockPriceSavedRead(data, instrument, null), 'explicit saved cutoff')
  }
  const source = createPriceSavedFixture()
  const changes: Array<(value: StockPriceSavedData) => void> = [
    (x) => { x.origin = 'process_memory' as never }, (x) => { x.version = 'stock-price-memory/m2-stock-scope-v5' },
    (x) => { x.storage_state.network_requests = 1 as never }, (x) => { x.storage_state.verified = false },
    (x) => { x.storage_state.action = 'cached' }, (x) => { x.provenance!.storage = 'private_local' as never },
    (x) => { x.provenance!.policy_version = 'm2-stock-scope-tpex-11370-2026-10-06.4' },
    (x) => { x.provenance!.receipt_sha256 = 'e'.repeat(64) }, (x) => { x.storage_provenance!.version = 'wrong' },
    (x) => { x.storage_provenance!.storage_policy_digest = 'sha256:' + '0'.repeat(64) },
    (x) => { x.storage_provenance!.capture_policy_digest = 'bad' }, (x) => { x.storage_provenance!.body_sha256 = '0'.repeat(64) },
    (x) => { x.storage_provenance!.capture_receipt_bytes = 8193 }, (x) => { x.storage_provenance!.capture_receipt_bytes = true as never },
    (x) => { x.storage_provenance!.storage_receipt_sha256 = 'bad' }, (x) => { x.storage_provenance!.saved_at = '2026-10-04T00:00:00Z' },
    (x) => { x.storage_provenance!.selected_symbols = ['6510'] }, (x) => { x.storage_provenance!.captured_at = 'wrong' },
    (x) => { x.latest!.source_fields['收盤'] = '1' }, (x) => { x.latest!.volume_exact = '1' },
    (x) => { x.bars = [] }, (x) => { (x.storage_provenance as unknown as Record<string, unknown>).path = 'C:/private' },
  ]
  for (const change of changes) {
    const value = structuredClone(source); change(value)
    check(!validStockPriceSavedRead(value, priceFixtureInstrument('6510'), '2026-10-06'), 'corruption rejected without values')
    check(savedPriceChartBars(value, priceFixtureInstrument('6510'), '2026-10-06').length === 0, 'invalid saved chart empty')
  }
  check(!validStockPriceSavedRead(source, { ...priceFixtureInstrument('6510'), name: 'wrong' }, '2026-10-06'), 'identity guard')
  for (const symbol of ['3105', '6488']) check(validStockPriceMemoryRead(createPriceMemoryFixture(symbol), priceFixtureInstrument(symbol), '2026-10-05'), 'historical memory tuple remains valid')
  return count
}
