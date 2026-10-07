import type { Instrument, StockDetailBar, StockPriceMemoryBar, StockPriceMemoryData } from './types'

export const PRICE_MEMORY_VERSION = 'stock-price-memory/m1-v1'
export const PRICE_POLICY_VERSION = 'm1-price-tpex-11370-2026-10-05.1'
export const PRICE_POLICY_DIGEST = 'sha256:452b9b8cfa3d050b79ea1a85b3e4ed643c40cf3d17882b8cb809ffdb7143deea'
export const PRICE_BODY_SHA = 'bdfcead65b5c36d2bd75d20fe7b790fa56ce39d2547d0772989243550ca36149'
export const PRICE_APPROVED_DATES = ['2026-10-05', '2026-10-06', '2026-10-07'] as const
export const PRICE_SCOPE_POLICY_VERSION = 'm2-stock-scope-tpex-11370-2026-10-06.1'
export const PRICE_SCOPE_POLICY_VERSION_V2 = 'm2-stock-scope-tpex-11370-2026-10-06.2'
export const PRICE_SCOPE_POLICY_VERSION_V3 = 'm2-stock-scope-tpex-11370-2026-10-06.3'
export const PRICE_SCOPE_POLICY_VERSION_V4 = 'm2-stock-scope-tpex-11370-2026-10-06.4'
export const PRICE_SCOPE_POLICY_VERSION_V5 = 'm2-stock-scope-tpex-11370-2026-10-06.5'
export const PRICE_SCOPE_POLICY_VERSION_V6 = 'm2-stock-scope-tpex-11370-2026-10-07.1'
export const PRICE_SYMBOL_NAMES: Record<string, string> = { '3105': '穩懋', '3293': '鈊象', '5274': '信驊', '5347': '世界', '6223': '旺矽', '6488': '環球晶', '6510': '精測', '8069': '元太' }
export function priceSourcePins(cutoff: string | null, policyVersion?: string) {
  if (cutoff === '2026-10-07' && (!policyVersion || policyVersion === PRICE_SCOPE_POLICY_VERSION_V6)) return { policyVersion: PRICE_SCOPE_POLICY_VERSION_V6, policyDigest: 'sha256:bdad10af9090dd15319b3f3e8dca2952f75c4caf6d46b3032e706a5006ccbab2', bodySha: 'eaa1eaf37ff3e2305629dced8b0f6945a063b05841c69d75f826960e6bd819c8', workerVersion: 'tpex-price-capture/m2-stock-scope-v6', memoryVersion: 'stock-price-memory/m2-stock-scope-v6', symbols: ['3105', '3293', '5274', '5347', '6223', '6488', '6510', '8069'] }
  if (cutoff === '2026-10-05' && (!policyVersion || policyVersion === PRICE_POLICY_VERSION)) return { policyVersion: PRICE_POLICY_VERSION, policyDigest: PRICE_POLICY_DIGEST, bodySha: PRICE_BODY_SHA, workerVersion: 'tpex-price-capture/m1-v1', memoryVersion: PRICE_MEMORY_VERSION, symbols: ['3105', '6488'] }
  if (cutoff === '2026-10-06' && policyVersion === 'm1-price-tpex-11370-2026-10-06.1') return { policyVersion, policyDigest: 'sha256:fc7b1451f6ae47145a5b40c3e08cdcad7ac8b9dafc64c7bf89f95c67cfefc288', bodySha: 'aae44dcb35107299a9f2cd47191301fe2cc2d980b6eae152927587df015bfd9a', workerVersion: 'tpex-price-capture/m1-v2', memoryVersion: PRICE_MEMORY_VERSION, symbols: ['3105', '6488'] }
  if (cutoff === '2026-10-06' && policyVersion === PRICE_SCOPE_POLICY_VERSION) return { policyVersion: PRICE_SCOPE_POLICY_VERSION, policyDigest: 'sha256:6e662d5fc91957b586becdf41f351d5abf2c41cec09909de468e62e76cda4a78', bodySha: 'ab34590df051d7ba08f35941811b69ee35f46c890212558b9f089119307b3200', workerVersion: 'tpex-price-capture/m2-stock-scope-v1', memoryVersion: 'stock-price-memory/m2-stock-scope-v1', symbols: ['3105', '5347', '6488'] }
  if (cutoff === '2026-10-06' && policyVersion === PRICE_SCOPE_POLICY_VERSION_V2) return { policyVersion: PRICE_SCOPE_POLICY_VERSION_V2, policyDigest: 'sha256:eb378f12e85462855d8271f1e977e4e84878882dd0944c004840a2ad21ab4434', bodySha: 'ab34590df051d7ba08f35941811b69ee35f46c890212558b9f089119307b3200', workerVersion: 'tpex-price-capture/m2-stock-scope-v2', memoryVersion: 'stock-price-memory/m2-stock-scope-v2', symbols: ['3105', '5274', '5347', '6488'] }
  if (cutoff === '2026-10-06' && policyVersion === PRICE_SCOPE_POLICY_VERSION_V3) return { policyVersion: PRICE_SCOPE_POLICY_VERSION_V3, policyDigest: 'sha256:57fb2dd808d71d43e89aca3fb42ef8dc53d9338093dd92a296858e62c41152ca', bodySha: 'ab34590df051d7ba08f35941811b69ee35f46c890212558b9f089119307b3200', workerVersion: 'tpex-price-capture/m2-stock-scope-v3', memoryVersion: 'stock-price-memory/m2-stock-scope-v3', symbols: ['3105', '3293', '5274', '5347', '6488'] }
  if (cutoff === '2026-10-06' && policyVersion === PRICE_SCOPE_POLICY_VERSION_V4) return { policyVersion: PRICE_SCOPE_POLICY_VERSION_V4, policyDigest: 'sha256:03738997b4d8ec27872c58cfedef75c602aa17251b4a7724d1a375b6b85d8afc', bodySha: 'ab34590df051d7ba08f35941811b69ee35f46c890212558b9f089119307b3200', workerVersion: 'tpex-price-capture/m2-stock-scope-v4', memoryVersion: 'stock-price-memory/m2-stock-scope-v4', symbols: ['3105', '3293', '5274', '5347', '6488', '8069'] }
  if (cutoff === '2026-10-06' && (!policyVersion || policyVersion === PRICE_SCOPE_POLICY_VERSION_V5)) return { policyVersion: PRICE_SCOPE_POLICY_VERSION_V5, policyDigest: 'sha256:5e397d1e560860208e11c8877fe539f38701757f8ba48dc6e7fea8ef8c0c4040', bodySha: 'ab34590df051d7ba08f35941811b69ee35f46c890212558b9f089119307b3200', workerVersion: 'tpex-price-capture/m2-stock-scope-v5', memoryVersion: 'stock-price-memory/m2-stock-scope-v5', symbols: ['3105', '3293', '5274', '5347', '6488', '6510', '8069'] }
  return null
}
export const PRICE_ENDPOINT = 'https://www.tpex.org.tw/web/stock/aftertrading/DAILY_CLOSE_quotes/stk_quote_result.php?l=zh-tw&o=data'
const names = PRICE_SYMBOL_NAMES
const limitations = ['single_day_only', 'historical_pit_unsupported', 'no_history_calendar_ma20_signal_or_plan', 'capture_time_is_not_publication_time']
const maxInt64 = '9223372036854775807'
const maxSafe = '9007199254740991'
export const PRICE_HEADERS = ['資料日期', '代號', '名稱', '收盤', '漲跌', '開盤', '最高', '最低', '均價', '成交股數', '成交金額', '成交筆數', '最後買價', '最後賣價', '發行股數', '次日參考價', '次日漲停價', '次日跌停價']
const uint = (value: unknown): value is string => typeof value === 'string' && /^(?:0|[1-9][0-9]*)(?![\s\S])/.test(value)
  && (value.length < maxInt64.length || (value.length === maxInt64.length && value <= maxInt64))
const projected = (value: string): number | null => value.length < maxSafe.length || (value.length === maxSafe.length && value <= maxSafe) ? Number(value) : null
const positive = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value > 0
const utc = (value: unknown): value is string => typeof value === 'string'
  && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:\+00:00|Z)(?![\s\S])/.test(value)
  && Number.isFinite(Date.parse(value))
  && new Date(value).toISOString().slice(0, 19) === value.slice(0, 19)
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every((item) => typeof item === 'string')
const same = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right)
const attributionValid = (value: StockPriceMemoryData['attribution'], cutoff: string | null) => value != null
  && same(value.owners, ['金融監督管理委員會證券期貨局', '財團法人中華民國證券櫃檯買賣中心'])
  && value.dataset_name === '上櫃股票行情' && value.year === 2026 && value.release_version === 'data-date-' + cutoff
  && value.license === 'OGL-1.0' && value.license_url === 'https://data.gov.tw/license'
  && value.publication_time === 'unknown' && value.first_available_time === 'unknown' && value.revision_time === 'unknown'

export function priceMemoryInstrumentSupported(instrument: Instrument): boolean {
  const currency = (instrument as Instrument & { currency?: unknown }).currency
  return instrument.market === 'TW' && instrument.exchange === 'TPEx' && Object.prototype.hasOwnProperty.call(names, instrument.symbol)
    && names[instrument.symbol] === instrument.name && instrument.instrument_type === 'stock' && !instrument.etf_category
    && (currency === undefined || currency === 'TWD')
}

export function validPriceMemoryEnvelope(value: StockPriceMemoryData | undefined, exchange: string, symbol: string, cutoff: string | null): value is StockPriceMemoryData {
  if (!value) return false
  const pins = priceSourcePins(cutoff, value.provenance?.policy_version ?? (cutoff === '2026-10-06' && value.version === PRICE_MEMORY_VERSION ? 'm1-price-tpex-11370-2026-10-06.1' : cutoff === '2026-10-06' && value.version === 'stock-price-memory/m2-stock-scope-v1' ? PRICE_SCOPE_POLICY_VERSION : cutoff === '2026-10-06' && value.version === 'stock-price-memory/m2-stock-scope-v2' ? PRICE_SCOPE_POLICY_VERSION_V2 : cutoff === '2026-10-06' && value.version === 'stock-price-memory/m2-stock-scope-v3' ? PRICE_SCOPE_POLICY_VERSION_V3 : cutoff === '2026-10-06' && value.version === 'stock-price-memory/m2-stock-scope-v4' ? PRICE_SCOPE_POLICY_VERSION_V4 : undefined))
  if (value.version !== (pins?.memoryVersion ?? PRICE_MEMORY_VERSION) || value.origin !== 'process_memory' || value.exchange !== exchange || value.symbol !== symbol
    || value.as_of !== cutoff || !['available', 'unavailable'].includes(value.status)
    || value.unit !== 'shares' || value.quantity_encoding !== 'canonical_integer_string' || value.price_unit !== 'TWD_per_share'
    || value.historical_pit !== 'unsupported' || value.published_time !== 'unknown' || value.first_available_time !== 'unknown' || value.revision_time !== 'unknown'
    || !strings(value.reasons) || !strings(value.limitations) || !Array.isArray(value.bars)) return false
  const scope = value.supported_scope
  const state = value.capture_state
  return scope != null && scope.exchange === 'TPEx' && scope.asset_type === 'stock' && scope.currency === 'TWD'
    && scope.cutoff === (pins ? cutoff : '2026-10-05') && same(scope.symbols, pins?.symbols ?? ['3105', '6488'])
    && state != null && [state.enabled, state.attempted, state.busy, state.can_capture, state.cache_present].every((item) => typeof item === 'boolean')
    && Number.isInteger(state.request_count) && state.request_count >= 0 && state.request_count <= 1 && typeof state.action === 'string'
    && (value.status !== 'unavailable' || (value.latest === null && value.bars.length === 0 && value.provenance === null && value.attribution === null))
}

export function memoryPriceCaptureReady(value: StockPriceMemoryData | undefined, exchange: string, symbol: string, cutoff: string | null): boolean {
  return validPriceMemoryEnvelope(value, exchange, symbol, cutoff) && exchange === 'TPEx' && Object.prototype.hasOwnProperty.call(names, symbol) && priceSourcePins(cutoff) !== null
    && value.supported_scope.symbols.includes(symbol)
    && value.status === 'unavailable' && value.reasons.length === 1 && value.reasons[0] === 'price_memory_capture_missing'
    && value.capture_state.enabled && value.capture_state.can_capture && !value.capture_state.attempted
    && !value.capture_state.busy && !value.capture_state.cache_present && value.capture_state.request_count === 0
}

export function validStockPriceMemoryRead(value: StockPriceMemoryData | undefined, instrument: Instrument, cutoff: string | null): value is StockPriceMemoryData & { latest: StockPriceMemoryBar } {
  const pins = priceSourcePins(cutoff, value?.provenance?.policy_version)
  if (!validPriceMemoryEnvelope(value, instrument.exchange, instrument.symbol, cutoff) || value.status !== 'available'
    || !priceMemoryInstrumentSupported(instrument) || !pins || !pins.symbols.includes(instrument.symbol)
    || value.reasons.length || value.bars.length !== 1 || !value.latest || !same(value.latest, value.bars[0])
    || !value.capture_state.enabled || !value.capture_state.attempted || value.capture_state.busy
    || value.capture_state.can_capture || !value.capture_state.cache_present || value.capture_state.request_count !== 1
    || !attributionValid(value.attribution, cutoff) || !same(value.limitations, limitations)) return false
  const bar = value.latest
  const p = value.provenance
  if (!p || !same(p, bar.provenance) || p.worker_version !== pins.workerVersion
    || p.source_id !== 'tpex_11370_daily_close_csv' || p.source_version !== 'tpex-11370/' + cutoff
    || p.endpoint !== PRICE_ENDPOINT || p.method !== 'GET' || p.http_status !== 200 || p.request_count !== 1
    || p.body_sha256 !== pins.bodySha || !/^[0-9a-f]{64}(?![\s\S])/.test(p.receipt_sha256)
    || p.policy_version !== pins.policyVersion || p.policy_digest !== pins.policyDigest || p.profile !== 'free_public_local'
    || p.storage !== 'process_memory' || p.raw_payload_id !== null || p.ingestion_run_id !== null
    || p.memory_capture_id !== 'tpex-11370:' + cutoff + ':' + pins.bodySha || p.verification !== 'pinned_raw_csv_selected_values'
    || p.structural_validation !== 'all_rows_header_width_date_unique_date_code' || p.financial_validation !== 'selected_symbols_only'
    || !same(p.selected_symbols, pins.symbols) || p.historical_pit !== 'unsupported'
    || !Number.isInteger(p.row_count) || p.row_count < pins.symbols.length || !Number.isInteger(p.body_bytes) || p.body_bytes < 1 || p.body_bytes > 3145728
    || !utc(p.request_started_at) || !utc(p.captured_at) || Date.parse(p.captured_at) < Date.parse(p.request_started_at)
    || Date.parse(p.captured_at) - Date.parse(p.request_started_at) > 30000 || !attributionValid(p.attribution, cutoff)
    || !same(p.attribution, value.attribution) || !same(p.limitations, limitations)) return false
  const fields = bar.source_fields
  const rocDate = cutoff === '2026-10-07' ? '1151007' : cutoff === '2026-10-05' ? '1151005' : '1151006'
  if (bar.id !== null || bar.origin !== 'process_memory' || bar.exchange !== 'TPEx' || bar.symbol !== instrument.symbol
    || bar.company_name !== instrument.name || bar.currency !== 'TWD' || bar.source !== 'tpex' || bar.date !== cutoff
    || bar.data_as_of !== cutoff || bar.source_date !== rocDate || bar.is_suspended !== false || bar.adj_close !== null
    || bar.collected_at !== p.captured_at || !Number.isInteger(bar.row_ordinal) || bar.row_ordinal < 1 || bar.row_ordinal > p.row_count
    || !fields || Object.keys(fields).length !== 18 || PRICE_HEADERS.some((field) => typeof fields[field] !== 'string')
    || fields['資料日期'] !== rocDate || fields['代號'] !== bar.symbol || fields['名稱'] !== bar.company_name
    || !uint(bar.volume_exact) || fields['成交股數'] !== bar.volume_exact || bar.volume !== projected(bar.volume_exact)) return false
  const priceFields = [['open', '開盤'], ['high', '最高'], ['low', '最低'], ['close', '收盤']] as const
  if (priceFields.some(([key, source]) => !positive(bar[key]) || fields[source].length > 64
    || !/^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?![\s\S])/.test(fields[source]) || Number(fields[source]) !== bar[key])
    || bar.low > Math.min(bar.open, bar.close) || Math.max(bar.open, bar.close) > bar.high) return false
  return bar.turnover_exact === null
    ? fields['成交金額'] === '' && bar.turnover === null && bar.turnover_status === 'unavailable' && bar.turnover_reason === 'missing'
    : uint(bar.turnover_exact) && fields['成交金額'] === bar.turnover_exact && bar.turnover === projected(bar.turnover_exact)
      && bar.turnover_status === 'available' && bar.turnover_reason === null
}

export function memoryPriceChartBars(value: StockPriceMemoryData, instrument: Instrument, cutoff: string | null): StockDetailBar[] {
  if (!validStockPriceMemoryRead(value, instrument, cutoff)) return []
  const bar = value.latest
  // The chart's existing syntax gate remains intact. No persisted ID is invented.
  return [{ date: bar.date, open: bar.open, high: bar.high, low: bar.low, close: bar.close, adj_close: null,
    volume: bar.volume, volume_exact: bar.volume_exact, turnover: bar.turnover, turnover_status: bar.turnover_status,
    turnover_reason: bar.turnover_reason, source: bar.source, is_suspended: false, data_as_of: bar.data_as_of, collected_at: bar.collected_at }]
}
