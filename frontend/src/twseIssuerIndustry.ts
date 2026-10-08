import type { OfficialEventsData, TwseIndustryCitation, TwseIssuerIndustryData, TwseIssuerProfileData } from './types'
import { issuerSourceDate, issuerSupported, validTwseIssuerProfile } from './twseIssuerProfile'

export const INDUSTRY_VERSION = 'twse-issuer-industry-trace/m1-v1'
export const INDUSTRY_PROFILE = 'twse_two_code_complete_name_local_citation'
export const INDUSTRY_POLICY_DIGEST = 'sha256:e9815a28d0ec22d29cd82c5524b02612debff4fec0110465002f6016afbae9b8'
export const INDUSTRY_REGISTRY_VERSION = 'twse-industry-citation-r1-2026-10-08.1'
export const INDUSTRY_REGISTRY_DIGEST = 'sha256:75b7667f65a9da7397a72a1e9c494a35364f7563faedc4df2cda21f12e61b647'
export const INDUSTRY_EXCERPT_DIGEST = 'sha256:dfba7e99fdb9343d71b34361afc04c0198a3ab1ebc31ff8a175fee588aa0fac8'
export const INDUSTRY_DECLARATION: TwseIndustryCitation['declaration'] = {
  version: 'twse-two-code-citations/b12-notice-fl007104-2025-06-09-v1', exchange: 'TWSE', metadata_observed_date: '2026-10-08',
  evidence_kind: 'parsed_official_document', entries: [{ code_raw: '04', name_zh: '紡織纖維' }, { code_raw: '20', name_zh: '其他' }],
  sources: [
    { source_id: 'twse_b12_appendix3', url: 'https://www.twse.com.tw/staticFiles/product/broker/ff80808166388ea1016676ac941001e0.pdf',
      document_version: 'B.12.00', revision_month: '2018-10', implementation_month: '2020-03', date_precision: 'month',
      locator: { appendix: '3', printed_page: 92, zero_based_page: 100, parsed_page_count: 104 }, supports: 'exact_code_name_pairs' },
    { source_id: 'twse_industry_notice_20230530', url: 'https://eshop.twse.com.tw/zh/news/detail/0000000087e9b84901886b8d96940024',
      announcement_date: '2023-05-30', patch_effective_date: '2023-07-03', date_precision: 'day', supports: 'code16_rename_and_code35_to38_additions_context' },
    { source_id: 'twse_fl007104_section2', url: 'https://twse-regulation.twse.com.tw/TW/law/DAT0201_print.aspx?FLCODE=FL007104',
      rule_id: 'FL007104', section: '2', revision_date: '2025-06-09', date_precision: 'day', supports: 'both_complete_names_present_in_33_name_list' },
  ],
  source_use: { purpose: 'bounded_local_research_complete_name_citation', basis: 'TWSE_terms_section_8', terms_url: 'https://www.twse.com.tw/zh/terms/use.html',
    conditions: ['identify_source', 'preserve_complete_name_integrity'], full_table_redistribution: 'not_admitted', original_document_download: 'not_admitted',
    complete_current_taxonomy: 'not_validated', company_membership_effective_date: 'unknown', historical_pit: 'unsupported' },
}
export const INDUSTRY_CITATION: TwseIndustryCitation = {
  schema_version: 'twse-industry-citation-registry/v1', registry_version: INDUSTRY_REGISTRY_VERSION, content_digest: INDUSTRY_REGISTRY_DIGEST,
  profile: INDUSTRY_PROFILE, declaration: INDUSTRY_DECLARATION, canonical_root_attested_excerpt_sha256: INDUSTRY_EXCERPT_DIGEST,
  evidence_delivery: { kind: 'parsed_official_document', attestation: 'root_reviewed_bounded_citation', original_body_sha256: null, original_receipt_sha256: null },
}
export const INDUSTRY_LIMITATIONS = ['two_complete_code_name_citations_only', 'parsed_documents_not_raw_capture_receipts', 'not_complete_current_taxonomy',
  'company_classification_effective_date_unknown', 'not_ordinary_or_etf_classification', 'no_ranking_or_group_membership', 'not_historical_pit']
const keys = ['version', 'status', 'reasons', 'exchange', 'symbol', 'as_of', 'cutoff_basis', 'metadata_observed_date', 'row', 'provenance', 'policy', 'limitations']
const object = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v)
const exact = (v: Record<string, unknown>, wanted: string[]) => Object.keys(v).length === wanted.length && wanted.every(k => Object.prototype.hasOwnProperty.call(v, k))
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every(x => typeof x === 'string')
export function industryCanonical(v: unknown): string {
  if (Array.isArray(v)) return '[' + v.map(industryCanonical).join(',') + ']'
  if (object(v)) return '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + industryCanonical(v[k])).join(',') + '}'
  return JSON.stringify(v)
}
const same = (a: unknown, b: unknown) => industryCanonical(a) === industryCanonical(b)

export function validTwseIssuerIndustry(value: unknown, exchange: string, symbol: string, cutoff: string | null,
  issuer?: TwseIssuerProfileData, events?: OfficialEventsData): value is TwseIssuerIndustryData {
  if (!object(value) || !exact(value, keys) || value.version !== INDUSTRY_VERSION || value.exchange !== exchange || value.symbol !== symbol
    || value.as_of !== cutoff || value.cutoff_basis !== 'observed_taipei_date_inclusive' || !strings(value.reasons)
    || !same(value.limitations, INDUSTRY_LIMITATIONS) || !same(value.policy, { version: INDUSTRY_VERSION, digest: INDUSTRY_POLICY_DIGEST, profile: INDUSTRY_PROFILE })
    || value.metadata_observed_date !== null && value.metadata_observed_date !== INDUSTRY_DECLARATION.metadata_observed_date) return false
  if (value.status === 'unavailable') return value.row === null && value.provenance === null && value.reasons.length > 0
  if (value.status !== 'available' || value.reasons.length || !issuerSupported(exchange, symbol) || !cutoff
    || value.metadata_observed_date !== INDUSTRY_DECLARATION.metadata_observed_date || value.metadata_observed_date > cutoff
    || !validTwseIssuerProfile(issuer, exchange, symbol, cutoff, events) || issuer.status !== 'available' || !issuer.row || !issuer.provenance
    || !events || events.status !== 'available' || events.version !== 'official-events/p3b-v1' || events.as_of !== cutoff || !events.provenance
    || !object(value.row) || !exact(value.row, ['industry_code_raw', 'name_zh', 'issuer_row_ordinal', 'event_row_ordinals', 'company_classification_effective_date'])
    || !object(value.provenance) || !exact(value.provenance, ['issuer', 'event', 'taxonomy_citation'])) return false
  const row = value.row, provenance = value.provenance, event = events.provenance
  const quote = INDUSTRY_DECLARATION.entries.find(entry => entry.code_raw === issuer.row!.industry_code_raw)
  if (!quote || row.industry_code_raw !== issuer.row.industry_code_raw || row.name_zh !== quote.name_zh || row.issuer_row_ordinal !== issuer.row.row_ordinal
    || row.company_classification_effective_date !== 'unknown' || !same(row.event_row_ordinals, events.rows.map(x => x.row_ordinal))
    || !same(provenance.issuer, issuer.provenance) || !same(provenance.event, event) || !same(provenance.taxonomy_citation, INDUSTRY_CITATION)
    || event.source_id !== 'twse_twt48u_all' || event.source_version !== 'twse-twt48u-all-d011-2026-09-12'
    || event.endpoint !== 'https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL' || event.registry_version !== 'r1-a1-c009-2026-09-12.1'
    || event.manifest_digest !== 'sha256:eb6c290d7716300c4117bb2cdc61a66cbf8d62e344870928933b44b77461f87b'
    || event.storage !== 'memory_only' || event.verification !== 'local_evidence_consistent'
    || !['body_sha256', 'receipt_sha256'].every(k => typeof event[k as keyof typeof event] === 'string' && /^[0-9a-f]{64}$/.test(String(event[k as keyof typeof event])))
    || !/(?:Z|\+00:00)$/.test(event.captured_at) || !/(?:Z|\+00:00)$/.test(event.request_started_at)
    || new Set(events.rows.map(x => x.row_ordinal)).size !== events.rows.length
    || events.rows.some(x => x.exchange !== exchange || x.symbol !== symbol || !Number.isSafeInteger(x.row_ordinal) || x.row_ordinal < 1
      || x.event_date !== issuerSourceDate(x.source_date, true) || x.event_date_role !== 'effective_date' || x.event_date_precision !== 'date'
      || x.published_at !== null || x.first_available_at !== null || x.revision_available_at !== null || x.availability !== 'unknown'
      || !({ '息': ['ex_dividend', '除息'], '權': ['ex_right', '除權'], '權息': ['ex_right_and_dividend', '除權息'] }[x.source_classification])
      || ({ '息': ['ex_dividend', '除息'], '權': ['ex_right', '除權'], '權息': ['ex_right_and_dividend', '除權息'] }[x.source_classification])?.join('|') !== [x.kind, x.label].join('|'))) return false
  const start = Date.parse(event.request_started_at), end = Date.parse(event.captured_at)
  return Number.isFinite(start) && Number.isFinite(end) && start <= end
    && new Date(end + 8 * 3600000).toISOString().slice(0, 10) === events.observed_date && events.observed_date !== null && events.observed_date <= cutoff
}

export function unavailableIndustry(data: TwseIssuerIndustryData, reason: string): TwseIssuerIndustryData {
  return { ...data, status: 'unavailable', row: null, provenance: null, reasons: [reason] }
}
