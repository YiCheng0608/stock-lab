import type { Instrument, StockDetailBar, StockPriceMemoryData, StockPriceSavedBar, StockPriceSavedData } from './types'
import { PRICE_SCOPE_POLICY_VERSION_V5, priceMemoryInstrumentSupported, priceSourcePins, validPriceMemoryEnvelope, validStockPriceMemoryRead } from './stockPriceMemoryRead'

export const PRICE_SAVED_VERSION = 'stock-price-saved/m1-v1'
export const PRICE_STORAGE_POLICY_VERSION = 'm1-price-save-tpex-11370-2026-10-06.1'
export const PRICE_STORAGE_POLICY_DIGEST = 'sha256:0e0d9f77fdfa97f2fe9864b9f1cfe2e73429899f1e0aea6c006c7630f0d7201e'
const sha = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{64}(?![\s\S])/.test(value)
const same = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right)
const utc = (value: unknown): value is string => typeof value === 'string'
  && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:\+00:00|Z)(?![\s\S])/.test(value)
  && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 19) === value.slice(0, 19)
const storageKeys = ['version', 'storage', 'storage_policy_version', 'storage_policy_digest', 'capture_policy_version', 'capture_policy_digest',
  'source_id', 'source_version', 'endpoint', 'method', 'as_of', 'selected_symbols', 'body_sha256', 'body_bytes', 'capture_receipt_sha256',
  'capture_receipt_bytes', 'captured_at', 'request_started_at', 'saved_at', 'attribution', 'limitations', 'storage_receipt_sha256']
const sourceKeys = ['worker_version', 'source_id', 'source_version', 'endpoint', 'method', 'http_status', 'request_count', 'request_started_at',
  'captured_at', 'body_sha256', 'body_bytes', 'policy_version', 'policy_digest', 'profile', 'storage', 'historical_pit', 'structural_validation',
  'financial_validation', 'row_count', 'selected_symbols', 'attribution', 'limitations', 'receipt_sha256', 'verification', 'raw_payload_id', 'ingestion_run_id', 'capture_id']
const keys = (value: object, expected: string[]) => same(Object.keys(value).sort(), [...expected].sort())

export function privatePriceSupported(instrument: Instrument, cutoff: string | null): boolean {
  return cutoff === '2026-10-06' && priceMemoryInstrumentSupported(instrument)
}

// This view verifies the unchanged original observation contract. It is never returned,
// cached, or used to claim the current server made an HTTP capture or owns memory data.
function originalObservation(value: StockPriceSavedData): StockPriceMemoryData {
  const p = value.provenance
  const source = p ? { ...p, memory_capture_id: p.capture_id, verification: 'pinned_raw_csv_selected_values' } : null
  const bar = value.latest ? { ...value.latest, origin: 'process_memory' as const, provenance: source! } : null
  return { ...value, version: 'stock-price-memory/m2-stock-scope-v5', origin: 'process_memory',
    latest: bar, bars: bar ? [bar] : [], provenance: source,
    capture_state: { enabled: true, attempted: value.status === 'available', busy: false, can_capture: false,
      cache_present: value.status === 'available', request_count: value.status === 'available' ? 1 : 0, action: 'cached' } }
}

export function validPriceSavedEnvelope(value: StockPriceSavedData | undefined, instrument: Instrument, cutoff: string | null): value is StockPriceSavedData {
  if (!value || value.version !== PRICE_SAVED_VERSION || value.origin !== 'private_local'
    || value.exchange !== instrument.exchange || value.symbol !== instrument.symbol || value.as_of !== cutoff
    || !privatePriceSupported(instrument, cutoff) || !Array.isArray(value.reasons) || !value.reasons.every((x) => typeof x === 'string')
    || !Array.isArray(value.bars) || !['available', 'unavailable'].includes(value.status)) return false
  const state = value.storage_state
  if (!state || !keys(state, ['enabled', 'action', 'verified', 'network_requests']) || typeof state.enabled !== 'boolean'
    || typeof state.verified !== 'boolean' || typeof state.action !== 'string' || state.network_requests !== 0) return false
  if (value.status === 'unavailable' && (value.latest !== null || value.bars.length || value.provenance !== null
    || value.storage_provenance !== null || value.attribution !== null || state.verified || !value.reasons.length)) return false
  return validPriceMemoryEnvelope(originalObservation(value), instrument.exchange, instrument.symbol, cutoff)
}

export function validStockPriceSavedRead(value: StockPriceSavedData | undefined, instrument: Instrument, cutoff: string | null): value is StockPriceSavedData & { latest: StockPriceSavedBar } {
  if (!validPriceSavedEnvelope(value, instrument, cutoff) || value.status !== 'available' || !value.latest
    || value.latest.origin !== 'private_local' || value.bars.length !== 1 || !same(value.latest, value.bars[0])
    || !value.storage_state.enabled || !value.storage_state.verified || !['saved', 'already_saved', 'reopened'].includes(value.storage_state.action)
    || !value.provenance || !keys(value.provenance, sourceKeys) || value.provenance.verification !== 'private_raw_csv_selected_values'
    || !same(value.provenance, value.latest.provenance) || !validStockPriceMemoryRead(originalObservation(value), instrument, cutoff)) return false
  const p = value.provenance, s = value.storage_provenance, pins = priceSourcePins(cutoff, PRICE_SCOPE_POLICY_VERSION_V5)!
  return s != null && keys(s, storageKeys) && s.version === 'tpex-price-storage-receipt/m1-v1' && s.storage === 'private_local'
    && s.storage_policy_version === PRICE_STORAGE_POLICY_VERSION && s.storage_policy_digest === PRICE_STORAGE_POLICY_DIGEST
    && s.capture_policy_version === pins.policyVersion && s.capture_policy_digest === pins.policyDigest
    && s.source_id === p.source_id && s.source_version === p.source_version && s.endpoint === p.endpoint && s.method === 'GET'
    && s.as_of === cutoff && same(s.selected_symbols, pins.symbols) && s.body_sha256 === pins.bodySha && s.body_bytes === p.body_bytes
    && s.capture_receipt_sha256 === p.receipt_sha256 && Number.isInteger(s.capture_receipt_bytes) && s.capture_receipt_bytes > 0 && s.capture_receipt_bytes <= 8192
    && s.captured_at === p.captured_at && s.request_started_at === p.request_started_at && utc(s.saved_at)
    && Date.parse(s.saved_at) >= Date.parse(s.captured_at) && same(s.attribution, p.attribution) && same(s.limitations, p.limitations)
    && sha(s.storage_receipt_sha256)
}

export function savedPriceChartBars(value: StockPriceSavedData, instrument: Instrument, cutoff: string | null): StockDetailBar[] {
  if (!validStockPriceSavedRead(value, instrument, cutoff)) return []
  const bar = value.latest
  return [{ date: bar.date, open: bar.open, high: bar.high, low: bar.low, close: bar.close, adj_close: null,
    volume: bar.volume, volume_exact: bar.volume_exact, turnover: bar.turnover, turnover_status: bar.turnover_status,
    turnover_reason: bar.turnover_reason, source: bar.source, is_suspended: false, data_as_of: bar.data_as_of, collected_at: bar.collected_at }]
}
