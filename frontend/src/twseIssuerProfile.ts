import type { OfficialEventsData, TwseIssuerProfileData } from './types'

export const ISSUER_SYMBOLS = ['1449', '1463', '2614'] as const
export const ISSUER_VERSION = 'twse-issuer-event-profile/m1-v1'
export const ISSUER_POLICY_DIGEST = 'sha256:02bf2422129c46490516557bccd188f7d550d2516c4b5e49e9acc2faf5338244'
export const ISSUER_REGISTRY_VERSION = 'twse-issuer-r1-2026-10-08.1'
export const ISSUER_REGISTRY_DIGEST = 'sha256:7488da20a3bdf94aaa548c896d19077628bf93529208226d49b2a02896972f89'
export const ISSUER_ENDPOINT = 'https://openapi.twse.com.tw/v1/opendata/t187ap03_L'
export const ISSUER_FIELDS = ['出表日期', '公司代號', '公司名稱', '公司簡稱', '外國企業註冊地國', '產業別', '住址',
  '營利事業統一編號', '董事長', '總經理', '發言人', '發言人職稱', '代理發言人', '總機電話', '成立日期', '上市日期',
  '普通股每股面額', '實收資本額', '私募股數', '特別股', '編制財務報表類型', '股票過戶機構', '過戶電話', '過戶地址',
  '簽證會計師事務所', '簽證會計師1', '簽證會計師2', '英文簡稱', '英文通訊地址', '傳真機號碼', '電子郵件信箱', '網址', '已發行普通股數或TDR原股發行股數']
const keys = ['version', 'status', 'reasons', 'exchange', 'symbol', 'as_of', 'cutoff_basis', 'observed_date', 'capture_enabled', 'can_capture', 'capture_action',
  'attempted', 'busy', 'cache_present', 'storage', 'durable_capture', 'historical_pit', 'published_time', 'first_availability', 'revision_history', 'classification',
  'feed_status', 'profile_present', 'candidate_count', 'row', 'provenance', 'attribution', 'policy', 'limitations']
const rowKeys = ['exchange', 'symbol', 'full_name', 'short_name', 'report_date_raw', 'report_date', 'report_date_role', 'listing_date_raw', 'listing_date',
  'listing_date_role', 'industry_code_raw', 'row_ordinal', 'source_row', 'event_names', 'body_sha256', 'receipt_sha256']
const provenanceKeys = ['source_id', 'source_version', 'endpoint', 'profile', 'registry_version', 'manifest_digest', 'generation_id', 'request_started_at',
  'captured_at', 'body_sha256', 'body_bytes', 'receipt_sha256', 'storage', 'verification', 'validation_scope']
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value)
const exact = (value: Record<string, unknown>, wanted: string[]) => Object.keys(value).length === wanted.length && wanted.every(key => Object.prototype.hasOwnProperty.call(value, key))
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(item => typeof item === 'string')
const hash = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value)
export const issuerSupported = (exchange: string, symbol: string) => exchange === 'TWSE' && ISSUER_SYMBOLS.some(code => code === symbol)

export function issuerSourceDate(raw: string, report = false): string | null {
  if (!(report ? /^[0-9]{7}$/ : /^(?:[0-9]{7}|[0-9]{8})$/).test(raw)) return null
  const sourceYear = Number(raw.slice(0, -4))
  if (!sourceYear) return null
  const year = sourceYear + (raw.length === 7 ? 1911 : 0)
  const iso = `${String(year).padStart(4, '0')}-${raw.slice(-4, -2)}-${raw.slice(-2)}`
  const instant = Date.parse(iso + 'T00:00:00Z')
  return Number.isFinite(instant) && new Date(instant).toISOString().slice(0, 10) === iso ? iso : null
}

export function validTwseIssuerProfile(value: unknown, exchange: string, symbol: string, cutoff: string | null,
  events?: OfficialEventsData): value is TwseIssuerProfileData {
  if (!object(value) || !exact(value, keys) || value.version !== ISSUER_VERSION || value.exchange !== exchange || value.symbol !== symbol || value.as_of !== cutoff
    || value.cutoff_basis !== 'observed_taipei_date_inclusive' || value.storage !== 'memory_only' || value.durable_capture !== false
    || value.historical_pit !== 'unsupported' || value.classification !== 'unsupported' || value.published_time !== 'unknown'
    || value.first_availability !== 'unknown' || value.revision_history !== 'unknown' || !strings(value.reasons) || !strings(value.limitations)
    || !['not_attempted', 'acquired', 'cached', 'failed'].includes(String(value.capture_action)) || !['available', 'unavailable'].includes(String(value.feed_status))
    || !['capture_enabled', 'can_capture', 'attempted', 'busy', 'cache_present'].every(key => typeof value[key] === 'boolean')
    || value.observed_date !== null && (typeof value.observed_date !== 'string' || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value.observed_date))
    || value.profile_present !== null && typeof value.profile_present !== 'boolean'
    || value.candidate_count !== null && (!Number.isSafeInteger(value.candidate_count) || Number(value.candidate_count) < 1 || Number(value.candidate_count) > 2000)
    || !object(value.policy) || !exact(value.policy, ['version', 'digest', 'profile']) || value.policy.version !== ISSUER_VERSION
    || value.policy.digest !== ISSUER_POLICY_DIGEST || value.policy.profile !== 'twse_issuer_free_public_local') return false
  if (value.status === 'unavailable') return value.row === null && value.provenance === null && value.attribution === null && value.reasons.length > 0
  if (value.status !== 'available' || !issuerSupported(exchange, symbol) || !cutoff || !value.capture_enabled || !value.attempted || !value.cache_present
    || value.feed_status !== 'available' || value.profile_present !== true || value.reasons.length || !Number.isSafeInteger(value.candidate_count)
    || !object(value.row) || !exact(value.row, rowKeys) || !object(value.provenance) || !exact(value.provenance, provenanceKeys)) return false
  const row = value.row, provenance = value.provenance, raw = row.source_row
  if (row.exchange !== exchange || row.symbol !== symbol || !object(raw) || !exact(raw, ISSUER_FIELDS) || !Object.values(raw).every(item => typeof item === 'string')
    || row.full_name !== raw['公司名稱'] || row.short_name !== raw['公司簡稱'] || raw['公司代號'] !== symbol
    || typeof row.full_name !== 'string' || !row.full_name.trim() || typeof row.short_name !== 'string' || !row.short_name.trim()
    || row.industry_code_raw !== raw['產業別'] || typeof row.industry_code_raw !== 'string' || !row.industry_code_raw.trim()
    || row.report_date_raw !== raw['出表日期'] || typeof row.report_date_raw !== 'string' || typeof row.report_date !== 'string' || row.report_date !== issuerSourceDate(row.report_date_raw, true)
    || row.listing_date_raw !== raw['上市日期'] || typeof row.listing_date_raw !== 'string' || typeof row.listing_date !== 'string' || row.listing_date !== issuerSourceDate(row.listing_date_raw)
    || row.report_date_role !== 'issuer_report_date' || row.listing_date_role !== 'listing_date' || !Number.isSafeInteger(row.row_ordinal)
    || Number(row.row_ordinal) < 1 || Number(row.row_ordinal) > Number(value.candidate_count) || !strings(row.event_names) || !row.event_names.length
    || row.event_names.some(name => name !== row.full_name && name !== row.short_name)) return false
  if (!events || events.status !== 'available' || events.as_of !== cutoff || !Array.isArray(events.rows)
    || events.rows.some(event => !object(event) || typeof event.company_name !== 'string')) return false
  const names = events.rows.filter(event => event.exchange === exchange && event.symbol === symbol).map(event => event.company_name)
  if (!names.length || JSON.stringify(names) !== JSON.stringify(row.event_names)) return false
  if (provenance.source_id !== 'twse_t187ap03_l' || provenance.source_version !== 'twse-t187ap03-l-d18419-2026-10-08'
    || provenance.endpoint !== ISSUER_ENDPOINT || provenance.profile !== 'twse_issuer_free_public_local' || provenance.registry_version !== ISSUER_REGISTRY_VERSION
    || provenance.manifest_digest !== ISSUER_REGISTRY_DIGEST || provenance.storage !== 'memory_only' || provenance.verification !== 'local_evidence_consistent'
    || provenance.validation_scope !== 'all_33_string_fields_unique_company_codes' || typeof provenance.generation_id !== 'string'
    || !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(provenance.generation_id) || !hash(provenance.body_sha256) || !hash(provenance.receipt_sha256)
    || row.body_sha256 !== provenance.body_sha256 || row.receipt_sha256 !== provenance.receipt_sha256
    || !Number.isSafeInteger(provenance.body_bytes) || Number(provenance.body_bytes) < 1 || Number(provenance.body_bytes) > 5242880
    || typeof provenance.captured_at !== 'string' || typeof provenance.request_started_at !== 'string'
    || !/(?:Z|\+00:00)$/.test(provenance.captured_at) || !/(?:Z|\+00:00)$/.test(provenance.request_started_at)) return false
  const captured = Date.parse(provenance.captured_at), started = Date.parse(provenance.request_started_at)
  if (!Number.isFinite(captured) || !Number.isFinite(started) || started > captured) return false
  const observed = new Date(captured + 8 * 3600000).toISOString().slice(0, 10)
  const attribution = value.attribution
  return observed === value.observed_date && observed <= cutoff && object(attribution) && object(attribution.owner)
    && attribution.owner.name === 'Taiwan Stock Exchange (TWSE)' && attribution.owner.type === 'official_exchange'
    && attribution.dataset_id === 'data-gov-18419' && attribution.source_id === provenance.source_id && attribution.source_url === ISSUER_ENDPOINT
    && object(attribution.terms) && attribution.terms.status === 'known' && attribution.terms.value === 'OGL 1.0'
    && Array.isArray(attribution.evidence) && attribution.evidence.length === 4 && object(attribution.purpose_evidence)
}

export function unavailableIssuer(value: TwseIssuerProfileData, reason: string): TwseIssuerProfileData {
  return { ...value, status: 'unavailable', row: null, provenance: null, attribution: null, candidate_count: null, profile_present: null,
    feed_status: 'unavailable', observed_date: null, cache_present: false, can_capture: false, capture_action: 'failed', reasons: [reason] }
}
