import React from 'react'
import type { ReactElement } from 'react'
import type { TwseIssuerIndustryData } from './types'
import { createTwseIssuerFixture } from './components/StockOverview.test'
import { TwseIssuerIndustry } from './components/TwseIssuerIndustry'
import { validTwseIssuerProfile } from './twseIssuerProfile'
import { INDUSTRY_CITATION, INDUSTRY_LIMITATIONS, INDUSTRY_POLICY_DIGEST, INDUSTRY_PROFILE, INDUSTRY_VERSION,
  validTwseIssuerIndustry, unavailableIndustry } from './twseIssuerIndustry'

/** Reconstructable synthetic boundaries; these bytes and receipts are not live evidence. */
export function createIndustryFixture(symbol = '1449') {
  const fixture = createTwseIssuerFixture(symbol)
  const code = symbol === '2614' ? '20' : '04', name = code === '20' ? '其他' : '紡織纖維'
  fixture.data.row!.industry_code_raw = code
  fixture.data.row!.source_row['產業別'] = code
  const trace: TwseIssuerIndustryData = {
    version: INDUSTRY_VERSION, status: 'available', reasons: [], exchange: 'TWSE', symbol, as_of: '2026-10-08',
    cutoff_basis: 'observed_taipei_date_inclusive', metadata_observed_date: '2026-10-08',
    row: { industry_code_raw: code, name_zh: name, issuer_row_ordinal: fixture.data.row!.row_ordinal,
      event_row_ordinals: fixture.events.rows.map(x => x.row_ordinal), company_classification_effective_date: 'unknown' },
    provenance: { issuer: structuredClone(fixture.data.provenance!), event: structuredClone(fixture.events.provenance!), taxonomy_citation: structuredClone(INDUSTRY_CITATION) },
    policy: { version: INDUSTRY_VERSION, digest: INDUSTRY_POLICY_DIGEST, profile: INDUSTRY_PROFILE }, limitations: [...INDUSTRY_LIMITATIONS],
  }
  fixture.overview.issuer_industry_trace = trace
  return { ...fixture, trace }
}

export function runTwseIssuerIndustryTests(render: (element: ReactElement) => string): number {
  let checks = 0
  const verify = (ok: boolean, message: string) => { checks++; if (!ok) throw new Error(message) }
  for (const symbol of ['1449', '1463', '2614']) {
    const f = createIndustryFixture(symbol), before = JSON.stringify(f.data)
    verify(validTwseIssuerProfile(f.data, 'TWSE', symbol, '2026-10-08', f.events), 'issuer v1 remains valid')
    verify(validTwseIssuerIndustry(f.trace, 'TWSE', symbol, '2026-10-08', f.data, f.events), 'pinned two-code citation trace')
    const props = { data: f.trace, issuer: f.data, events: f.events, exchange: 'TWSE', symbol, cutoff: '2026-10-08' }
    const html = render(React.createElement(TwseIssuerIndustry, props))
    verify(html.includes('<td>' + f.trace.row!.name_zh + '</td>') && html.includes('<td>' + f.trace.row!.industry_code_raw + '</td>'), 'raw code and complete quoted name')
    verify(html.includes('2020年3月') && html.includes('月精度') && html.includes('2023-07-03') && html.includes('2025-06-09') && html.includes('公司分類生效日'), 'separate month, notice, revision and unknown company time')
    verify(html.includes('B.12.00') && html.includes('dfba7e99') && html.includes('不是 PDF') && html.includes('1'.repeat(64)) && html.includes('b'.repeat(64)), 'typed citation versus original financial trace')
    const failed = render(React.createElement(TwseIssuerIndustry, { ...props, requestFailure: 'issuer_read_request_failed' }))
    verify(!failed.includes('<td>' + f.trace.row!.name_zh + '</td>') && !failed.includes('dfba7e99') && !failed.includes('1'.repeat(64)), 'request failure clears all names and provenance')
    const missing = unavailableIndustry(f.trace, 'industry_issuer_unavailable')
    verify(validTwseIssuerIndustry(missing, 'TWSE', symbol, '2026-10-08', f.data, f.events), 'clear unavailable contract')
    verify(JSON.stringify(f.data) === before && f.data.classification === 'unsupported', 'new projection does not mutate issuer v1')
  }
  const f = createIndustryFixture()
  for (const mutate of [
    (x: TwseIssuerIndustryData) => { x.row!.name_zh = 'changed' },
    (x: TwseIssuerIndustryData) => { x.row!.industry_code_raw = '4' },
    (x: TwseIssuerIndustryData) => { x.row!.company_classification_effective_date = '2023-07-03' as 'unknown' },
    (x: TwseIssuerIndustryData) => { x.row!.event_row_ordinals = [1] },
    (x: TwseIssuerIndustryData) => { x.provenance!.issuer.body_sha256 = 'a'.repeat(64) },
    (x: TwseIssuerIndustryData) => { x.provenance!.event.source_version = 'changed' },
    (x: TwseIssuerIndustryData) => { x.provenance!.taxonomy_citation.declaration.sources[0].implementation_month = '2020-03-01' },
    (x: TwseIssuerIndustryData) => { x.provenance!.taxonomy_citation.evidence_delivery.original_body_sha256 = 'fake' as unknown as null },
    (x: TwseIssuerIndustryData) => { x.policy.digest = 'changed' },
    (x: TwseIssuerIndustryData) => { (x as unknown as Record<string, unknown>).extra = true },
  ]) {
    const bad = structuredClone(f.trace); mutate(bad)
    verify(!validTwseIssuerIndustry(bad, 'TWSE', '1449', '2026-10-08', f.data, f.events), 'tampered trace rejected')
  }
  for (const code of ['91', '80', '00', '99', '4', ' 04', '04 ', 'Other', '']) {
    const bad = structuredClone(f), raw = bad.data.row!
    raw.industry_code_raw = code; raw.source_row['產業別'] = code; bad.trace.row!.industry_code_raw = code
    verify(!validTwseIssuerIndustry(bad.trace, 'TWSE', '1449', '2026-10-08', bad.data, bad.events), 'unsupported raw code is not Other fallback')
  }
  verify(!validTwseIssuerIndustry(f.trace, 'TWSE', '1449', '2026-10-07', f.data, f.events), 'earlier cutoff rejects evidence')
  verify(!validTwseIssuerIndustry(f.trace, 'TWSE', '1449', null, f.data, f.events), 'missing cutoff rejects evidence')
  verify(!validTwseIssuerIndustry(f.trace, 'TWSE', '0056', '2026-10-08', f.data, f.events), 'unsupported symbol has no catalogue fallback')
  const conflicted = structuredClone(f.events); conflicted.rows[0].company_name = 'conflict'
  verify(!validTwseIssuerIndustry(f.trace, 'TWSE', '1449', '2026-10-08', f.data, conflicted), 'exact original event name required')
  return checks
}
