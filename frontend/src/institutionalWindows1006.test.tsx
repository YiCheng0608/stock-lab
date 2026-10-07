import type { InstitutionalWindowsData } from './types'
import type { ReactElement } from 'react'
import { CHIPS1006_DAILY_FIELDS, CHIPS1006_POLICY_DIGEST, InstitutionalWindows, validChips1006Read } from './components/StockOverview'

const dates = ['09-01', '09-02', '09-03', '09-04', '09-07', '09-08', '09-09', '09-10', '09-11', '09-14', '09-15', '09-16', '09-17', '09-18', '09-21', '09-22', '09-23', '09-24', '09-29', '09-30', '10-01', '10-02', '10-05', '10-06'].map((day) => `2026-${day}`)
const policy = 'm1-chips-cutoff-tpex-2026-10-06.1'
const dailySource = 'tpex_government_institutional_csv'
const indexSource = 'tpex_government_index_csv'
const indexFields = ['資料日期', '開市', '最高價', '最低價', '收市', '漲跌']

export function createChips1006Fixture(symbol = '3105'): InstitutionalWindowsData {
  const receipt = (day: string, daily: boolean) => ({
    schema_version: 'tpex-institutional-memory-capture/chips-1006-v1', source_id: daily ? dailySource : indexSource,
    source_version: daily ? 'dataset-11856-dated-csv-observed-2026-10-07/chips-v1' : 'dataset-11391-month-csv-observed-2026-10-07/chips-v1',
    requested_date: day, url: daily ? 'https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=' + encodeURIComponent(`115/${day.slice(5).replace('-', '/')}`)
      : 'https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data&date=' + encodeURIComponent(day.replaceAll('-', '/')),
    method: 'GET', body_sha256: (daily ? 'a' : day.slice(5, 7) === '09' ? 'b' : 'c').repeat(64), receipt_sha256: 'sha256:' + 'd'.repeat(64),
    body_bytes: 900, request_started_at: '2026-10-07T00:00:00+00:00', captured_at: '2026-10-07T00:00:01+00:00',
    policy_version: policy, policy_digest: CHIPS1006_POLICY_DIGEST, profile: 'free_public_local', historical_pit: 'unsupported',
    http_status: 200, content_type: 'application/csv;charset=utf-8', content_encoding: 'identity',
    storage: 'process_memory', published_time: 'unknown', first_available_time: 'unknown', revision_time: 'unknown', request_count: 1,
  })
  const months = ['2026-09-01', '2026-10-01']
  const daily = dates.slice(-20).map((day, index) => {
    const ordinal = index + 1
    const foreign = [100 + ordinal, 20, 80 + ordinal], foreignDealer = [2, 1, 1]
    const trust = [3, 10 + ordinal, -7 - ordinal], own = [10, 3, 7], hedge = [7 + ordinal, 4, 3 + ordinal]
    const dealer = own.map((value, part) => value + hedge[part]), totalForeign = foreign.map((value, part) => value + foreignDealer[part])
    const total = foreign[2] + trust[2] + dealer[2]
    const fields = ['115' + day.slice(5).replace('-', ''), symbol, 'Synthetic ' + symbol,
      ...[foreign, foreignDealer, totalForeign, trust, own, hedge, dealer].flat().map(String), String(total)]
    const investors = Object.fromEntries(([['foreign', 3, foreign, '外資及陸資（不含外資自營商）'], ['trust', 12, trust, '投信'], ['dealer', 21, dealer, '自營商']] as const).map(([key, offset, group, label]) => [key,
      { label, buy: String(group[0]), sell: String(group[1]), net: String(group[2]), source_fields: { buy: CHIPS1006_DAILY_FIELDS[offset], sell: CHIPS1006_DAILY_FIELDS[offset + 1], net: CHIPS1006_DAILY_FIELDS[offset + 2] } }])) as Record<'foreign' | 'trust' | 'dealer', { label: string; buy: string; sell: string; net: string; source_fields: { buy: string; sell: string; net: string } }>
    return { row: { symbol, company_name: 'Synthetic ' + symbol, date: day, source_date: fields[0], row_ordinal: symbol === '3105' ? 1 : 2,
      investors, total_net: String(total), source_values: Object.fromEntries(CHIPS1006_DAILY_FIELDS.map((field, part) => [field, fields[part]])) }, provenance: receipt(day, true) }
  })
  const data: InstitutionalWindowsData = {
    schema_version: 'institutional-windows-read/chips-1006-v1', version: 'institutional-windows/chips-1006-v1', exchange: 'TPEx', symbol,
    as_of: '2026-10-06', status: 'available', horizons: [5, 20], investors: ['foreign', 'trust', 'dealer'], values: null, reasons: [],
    unit: 'shares', quantity_encoding: 'canonical_integer_string', historical_pit: 'unsupported', published_time: 'unknown', first_available_time: 'unknown', revision_time: 'unknown',
    supported_scope: { exchange: 'TPEx', symbols: ['3105', '6488'], supported_cutoffs: ['2026-10-06'], calendar_from: '2026-09-01', calendar_to: '2026-10-06', financial_dates: dates.slice(-20), selection: 'explicit_requested_as_of_only' },
    policy: { version: policy, digest: CHIPS1006_POLICY_DIGEST, profile: 'free_public_local' }, calculation_version: 'independent-net-sum/expected-session-inclusive-v1',
    provenance: { worker_version: 'tpex-institutional-window/chips-1006-v1', worker_schema_version: 'tpex-institutional-window-summary/chips-1006-v1', verification: 'local_evidence_consistent', captured_versions: [...months.map((day) => receipt(day, false)), ...daily.map((item) => item.provenance)] },
    calendar: { schema_version: 'tpex-observed-calendar/chips-1006-v1', version: 'tpex-2026-09-01_2026-10-06-weekdays-11503027221/chips-v1', status: 'available', from: '2026-09-01', to: '2026-10-06', expected_dates: dates, valid_dates: dates, missing_dates: [],
      evidence: months.map((day, index) => ({ ...receipt(day, false), candidate_count: [20, 4][index], adopted_count: [20, 4][index], pre_calendar_row_count: 0, validation_scope: 'all_returned_month_rows' })),
      rows: dates.map((day, index) => ({ date: day, row_ordinal: index < 20 ? index + 1 : index - 19, body_sha256: receipt(months[index < 20 ? 0 : 1], false).body_sha256,
        source_values: Object.fromEntries(indexFields.map((field, part) => [field, [day.replaceAll('-', ''), '10', '12', '9', '11', '1'][part]])) })) },
    windows: {}, capture_state: { enabled: true, attempted: true, busy: false, can_capture: true, cache_present: true, action: 'cached', request_count: 22 },
  }
  for (const horizon of [5, 20]) {
    const evidence = daily.slice(-horizon)
    data.windows![String(horizon)] = { horizon, status: 'available', values: Object.fromEntries(['foreign', 'trust', 'dealer'].map((key) => [key,
      String(evidence.reduce((sum, item) => sum + BigInt(item.row.investors[key as 'foreign' | 'trust' | 'dealer'].net), 0n))])) as Record<'foreign' | 'trust' | 'dealer', string>,
      required_dates: dates.slice(-horizon), valid_dates: dates.slice(-horizon), missing_dates: [], invalid_dates: [], from: dates.at(-horizon), to: '2026-10-06', reasons: [], daily_evidence: evidence }
  }
  return data
}

export function runChips1006SSRTests(render: (element: ReactElement) => string): number {
  let count = 0
  const check = (value: boolean, message: string) => { count++; if (!value) throw new Error(message) }
  for (const symbol of ['3105', '6488']) {
    const good = createChips1006Fixture(symbol)
    check(validChips1006Read(good, 'TPEx', symbol, '2026-10-06'), 'known synthetic contract')
    const html = render(<InstitutionalWindows data={good} expectedSymbol={symbol} expectedCutoff="2026-10-06" onCapture={() => {}} />)
    check(html.includes('完整25欄官方原字串') && html.includes('24個已觀測交易日') && html.includes('9月20列'), 'complete original field/calendar presentation')
    check(html.includes('>0.49<') && html.includes('>1,810<') && html.includes('2026-09-07'), 'independent synthetic 5/20 sums, lots and original shares')
    const partial = structuredClone(good), window = partial.windows!['20']
    window.status = 'unavailable'; window.values = null; window.valid_dates = window.valid_dates.slice(1); window.missing_dates = ['2026-09-07']; window.daily_evidence = window.daily_evidence!.slice(1)
    partial.status = 'unavailable'; partial.provenance!.captured_versions.splice(2, 1)
    check(validChips1006Read(partial), 'missing early date retains verified five')
    check(render(<InstitutionalWindows data={partial} />).includes('>0.49<'), 'five displayed when twenty unavailable')
    const poisonedPartial = structuredClone(partial); poisonedPartial.windows!['20'].daily_evidence![0].row.source_values!['投信買進股數'] = '999'
    check(!validChips1006Read(poisonedPartial), 'partial evidence also verified')
    const failed = render(<InstitutionalWindows data={good} onCapture={() => {}} requestFailure="window_capture_request_failed" />)
    check(failed.includes('讀取本次法人窗口') && !failed.includes('完整25欄') && !failed.includes('>0.49<') && !failed.includes('24個已觀測交易日'), 'failed reread clears numbers and verified raw, keeps restoration')
    const corruptions: Array<(data: InstitutionalWindowsData) => void> = [
      (data) => { data.version = 'institutional-windows/w8-v1' }, (data) => { data.schema_version = 'old' },
      (data) => { data.policy!.digest = 'sha256:' + 'e'.repeat(64) }, (data) => { data.symbol = '9999' },
      (data) => { data.as_of = '2026-10-02' }, (data) => { data.provenance!.worker_version = 'old' },
      (data) => { data.windows!['5'].values!.foreign = '777' },
      (data) => { data.windows!['20'].daily_evidence![0].row.investors.foreign.net = '777' },
      (data) => { data.windows!['20'].daily_evidence![0].row.source_values!['投信買進股數'] = '01' },
      (data) => { const row = data.windows!['20'].daily_evidence![0].row; delete row.source_values!['名稱']; row.source_values!.fake = row.company_name },
      (data) => { data.calendar!.rows![0].source_values['最高價'] = '8' },
      (data) => { data.calendar!.rows![0].body_sha256 = 'e'.repeat(64) },
      (data) => { data.calendar!.rows![0].source_values['資料日期'] = '1150901' },
      (data) => { data.calendar!.rows!.push(data.calendar!.rows![0]) },
      (data) => { data.windows!['5'].daily_evidence![0].provenance.source_version = 'old' },
      (data) => { data.windows!['5'].daily_evidence![0].provenance.body_sha256 = 'invalid' },
      (data) => { data.calendar!.rows![0].source_values['開市'] = '0x10' },
      (data) => { data.provenance!.captured_versions[0].body_bytes += 1 },
      (data) => { const item = data.windows!['5'].daily_evidence![0]; item.provenance = { ...item.provenance, body_bytes: item.provenance.body_bytes + 1 } },
      (data) => { data.calendar!.evidence![0].captured_at = '2026-10-07T00:00:02+00:00' },
    ]
    for (const [index, change] of corruptions.entries()) {
      const bad = structuredClone(good); change(bad)
      check(!validChips1006Read(bad), `poisoned numerical/source contract ${index} rejected`)
      const rejected = render(<InstitutionalWindows data={bad} />)
      check(!rejected.includes('完整25欄') && !rejected.includes('>0.49<'), 'rejected projection hides numbers and raw')
    }
    check(!validChips1006Read(good, 'TPEx', symbol === '3105' ? '6488' : '3105', '2026-10-06'), 'cross-stock response rejected')
    check(!validChips1006Read(good, 'TPEx', symbol, ''), 'default request cannot promote explicit new scope')
  }
  return count
}
