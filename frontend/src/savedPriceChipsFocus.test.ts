import type { InstitutionalWindowsData, PriceFocusDayMove, PriceSavedFocusData } from './types'
import { createSavedPriceFocusFixture } from './savedPriceFocus.test'
import { CHIPS1006_DAILY_FIELDS, CHIPS1006_POLICY_DIGEST } from './components/StockOverview'
import { JOINT_KEYS, JOINT_FOCUS_VERSION, JOINT_FOCUS_POLICY, JOINT_FOCUS_DIGEST, JOINT_SYMBOLS, netLotsShares, jointParams, jointDetailPath, jointReturnPath, jointDetailContext, jointDetailEvidenceInvalid, validJointFocus, focusTransition, type JointConditions, type JointFocusData } from './savedPriceChipsFocus'

// Reconstructable synthetic input; pure existing fixture builders run no old tests.
export const jointFixtureConditions = (changes: Partial<JointConditions> = {}): JointConditions => ({ as_of: '2026-10-06', min_lots: '0.000', day_move: 'all', min_turnover: '0', min_range_pct: '0.000', investor: 'foreign', horizon: '5', min_net_lots: '0.000', ...changes })
const dates = ['09-01', '09-02', '09-03', '09-04', '09-07', '09-08', '09-09', '09-10', '09-11', '09-14', '09-15', '09-16', '09-17', '09-18', '09-21', '09-22', '09-23', '09-24', '09-29', '09-30', '10-01', '10-02', '10-05', '10-06'].map((day) => `2026-${day}`)
const policy = 'm1-chips-cutoff-tpex-2026-10-06.1'
const calendarVersion = 'tpex-2026-09-01_2026-10-06-weekdays-11503027221/chips-v1'

// Canonicalize immutable synthetic evidence to shared objects and strings.
// The temporary lookup tables are released when construction returns.
function compactFixture<T>(value: T): T {
  const objects = new Map<string, unknown>(), strings = new Map<string, string>()
  const visit = (input: unknown): unknown => {
    if (typeof input === 'string') { if (!strings.has(input)) strings.set(input, input); return strings.get(input) }
    if (!input || typeof input !== 'object') return input
    const output = Array.isArray(input) ? input.map(visit) : Object.fromEntries(Object.entries(input).map(([key, child]) => [visit(key) as string, visit(child)]))
    const signature = JSON.stringify(output)
    if (objects.has(signature)) return objects.get(signature)
    objects.set(signature, output); return output
  }
  return visit(value) as T
}

// Applies only to the explicitly interned synthetic graph. Each property slot
// is counted, with shared object/string payloads counted once.
export function jointFixtureGraphBytes(value: unknown, seen = new Set<unknown>()): number {
  if (value == null) return 16
  if (typeof value === 'string') { if (seen.has(value)) return 0; seen.add(value); return 64 + value.length * 4 }
  if (typeof value !== 'object') return 16
  if (seen.has(value)) return 0
  seen.add(value)
  return 128 + Object.entries(value).reduce((sum, [key, child]) => sum + 32 + jointFixtureGraphBytes(key, seen) + jointFixtureGraphBytes(child, seen), 0)
}
export let largestJointFixtureGraphBytes = 0

export function syntheticJointChips(): InstitutionalWindowsData[] {
  const months = ['2026-09-01', '2026-10-01'], requested = [...months, ...dates.slice(-20)]
  const receipts = requested.map((day, index) => ({ schema_version: 'tpex-institutional-memory-capture/chips-1006-v1',
    source_id: index < 2 ? 'tpex_government_index_csv' : 'tpex_government_institutional_csv',
    source_version: index < 2 ? 'dataset-11391-month-csv-observed-2026-10-07/chips-v1' : 'dataset-11856-dated-csv-observed-2026-10-07/chips-v1',
    requested_date: day, url: (index < 2 ? 'https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data&date=' : 'https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=') + encodeURIComponent(index < 2 ? day.replaceAll('-', '/') : `115/${day.slice(5).replace('-', '/')}`),
    method: 'GET', body_sha256: index.toString(16).padStart(64, '0'), body_bytes: 512, request_started_at: '2026-10-07T00:00:00+00:00', captured_at: '2026-10-07T00:00:01+00:00',
    policy_version: policy, policy_digest: CHIPS1006_POLICY_DIGEST, profile: 'free_public_local', http_status: 200, content_type: 'application/csv;charset=utf-8', content_encoding: 'identity', storage: 'process_memory',
    published_time: 'unknown', first_available_time: 'unknown', revision_time: 'unknown', historical_pit: 'unsupported', request_count: 1 }))
  const indexFields = ['資料日期', '開市', '最高價', '最低價', '收市', '漲跌']
  const calendar = { schema_version: 'tpex-observed-calendar/chips-1006-v1', version: calendarVersion, status: 'available', from: dates[0], to: dates[23], expected_dates: dates, valid_dates: dates, missing_dates: [],
    evidence: receipts.slice(0, 2).map((receipt, index) => ({ ...receipt, receipt_sha256: 'sha256:' + 'a'.repeat(64), validation_scope: 'all_returned_month_rows', candidate_count: [20, 4][index], adopted_count: [20, 4][index], pre_calendar_row_count: 0 })),
    rows: dates.map((day, index) => ({ date: day, source_values: Object.fromEntries(indexFields.map((field, position) => [field, [day.replaceAll('-', ''), '10', '12', '9', '11', '1'][position]])), body_sha256: receipts[index < 20 ? 0 : 1].body_sha256, row_ordinal: index < 20 ? index + 1 : index - 19 })) }
  const provenance = { worker_version: 'tpex-institutional-window/chips-1006-v1', worker_schema_version: 'tpex-institutional-window-summary/chips-1006-v1', verification: 'local_evidence_consistent', captured_versions: receipts }
  return JOINT_SYMBOLS.map((symbol) => {
    const daily = dates.slice(-20).map((day, index) => {
      const ordinal = index + 1, groups = [[100 + ordinal, 20, 80 + ordinal], [2, 1, 1], [102 + ordinal, 21, 81 + ordinal], [3, 10 + ordinal, -7 - ordinal], [10, 3, 7], [7 + ordinal, 4, 3 + ordinal], [17 + ordinal, 7, 10 + ordinal]]
      const raw = ['115' + day.slice(5).replace('-', ''), symbol, 'Synthetic ' + symbol, ...groups.flat().map(String), String(83 + ordinal)]
      const investors = Object.fromEntries(([['foreign', 0, 3, '外資及陸資（不含外資自營商）'], ['trust', 3, 12, '投信'], ['dealer', 6, 21, '自營商']] as const).map(([key, group, offset, label]) => [key, { label, buy: String(groups[group][0]), sell: String(groups[group][1]), net: String(groups[group][2]), source_fields: { buy: CHIPS1006_DAILY_FIELDS[offset], sell: CHIPS1006_DAILY_FIELDS[offset + 1], net: CHIPS1006_DAILY_FIELDS[offset + 2] } }]))
      return { row: { date: day, source_date: raw[0], symbol, company_name: raw[2], row_ordinal: 1, investors, total_net: raw[24], source_values: Object.fromEntries(CHIPS1006_DAILY_FIELDS.map((field, position) => [field, raw[position]])) }, provenance: { ...receipts[index + 2], receipt_sha256: 'sha256:' + 'b'.repeat(64) } }
    })
    const windows = Object.fromEntries([5, 20].map((horizon) => {
      const selected = daily.slice(-horizon), required = dates.slice(-horizon)
      return [String(horizon), { horizon, status: 'available', from: required[0], to: '2026-10-06', required_dates: required, valid_dates: required, missing_dates: [], invalid_dates: [], daily_evidence: selected,
        values: Object.fromEntries(['foreign', 'trust', 'dealer'].map((key) => [key, String(selected.reduce((sum, evidence) => sum + BigInt((evidence.row.investors[key] as { net: string }).net), 0n))])) }]
    }))
    return { schema_version: 'institutional-windows-read/chips-1006-v1', version: 'institutional-windows/chips-1006-v1', status: 'available', exchange: 'TPEx', symbol, as_of: '2026-10-06',
      supported_scope: { exchange: 'TPEx', symbols: JOINT_SYMBOLS, supported_cutoffs: ['2026-10-06'], calendar_from: '2026-09-01', calendar_to: '2026-10-06', financial_dates: dates.slice(-20), selection: 'explicit_requested_as_of_only' },
      horizons: [5, 20], investors: ['foreign', 'trust', 'dealer'], unit: 'shares', quantity_encoding: 'canonical_integer_string', historical_pit: 'unsupported', published_time: 'unknown', first_available_time: 'unknown', revision_time: 'unknown', storage: 'process_memory', windows, calendar, provenance,
      policy: { version: policy, digest: CHIPS1006_POLICY_DIGEST, profile: 'free_public_local' }, calculation_version: 'independent-net-sum/expected-session-inclusive-v1', reasons: [], failures: [], limitations: [], values: null,
      capture_state: { enabled: true, attempted: true, busy: false, can_capture: true, cache_present: true, action: 'cached', request_count: 22 } } as unknown as InstitutionalWindowsData
  })
}

export function jointFixture(values = jointFixtureConditions(), price?: PriceSavedFocusData, institutional?: InstitutionalWindowsData[]): JointFocusData {
  const shared = price !== undefined && institutional !== undefined
  price ??= createSavedPriceFocusFixture(values.min_lots, values.day_move as PriceFocusDayMove, values.min_turnover, values.min_range_pct)
  institutional ??= syntheticJointChips()
  const minimum = netLotsShares(values.min_net_lots)!
  const items = price.items.filter((item) => JOINT_SYMBOLS.includes(item.symbol)).filter((item) => BigInt(institutional[JOINT_SYMBOLS.indexOf(item.symbol)].windows![values.horizon].values![values.investor as 'foreign' | 'trust' | 'dealer']) >= BigInt(minimum)).map((item) => ({ ...item, investor: values.investor, horizon: values.horizon,
    net_shares: institutional[JOINT_SYMBOLS.indexOf(item.symbol)].windows![values.horizon].values![values.investor as 'foreign' | 'trust' | 'dealer'], min_net_lots: values.min_net_lots, min_net_shares: minimum, reasons: [...item.reasons, 'selected_net_at_least_min_net_lots'], detail_url: jointDetailPath(item.symbol, values) }))
  const data: JointFocusData = { ...values, version: JOINT_FOCUS_VERSION, policy_version: JOINT_FOCUS_POLICY, policy_digest: JOINT_FOCUS_DIGEST, min_net_shares: minimum, status: 'available', count: items.length, items, price, institutional,
    price_ready: true, chips_ready: true, capture_attempted: true, can_capture: false, reasons: [], sort: 'code_ascending', supported_symbols: JOINT_SYMBOLS, excluded_price_symbols: ['3293', '5274', '5347', '6510', '8069'], historical_pit: 'unsupported' }
  return shared ? data : compactFixture(data)
}

export function runJointFocusTests(): number {
  let checks = 0
  const check = (condition: unknown, message: string) => { checks++; if (!condition) throw new Error(message) }
  for (const [raw, expected] of [['0', '0'], ['0.000', '0'], ['-0.001', '-1'], ['1.010', '1010'], ['-9223372036854775.808', '-9223372036854775808'], ['9223372036854775.807', '9223372036854775807']]) check(netLotsShares(raw) === expected, raw)
  for (const raw of ['-0', '-0.0', '-0.00', '-0.000', '+1', '01', '1,000', '1e2', ' 1', '1 ', '1.0000', '9223372036854775.808', '-9223372036854775.809']) check(netLotsShares(raw) === null, raw)
  const data = jointFixture(), values = jointFixtureConditions()
  largestJointFixtureGraphBytes = jointFixtureGraphBytes(data)
  check(validJointFocus(data, values), 'complete synthetic joint evidence')
  for (const investor of ['foreign', 'trust', 'dealer']) for (const horizon of ['5', '20']) {
    const shares = data.institutional[0].windows![horizon].values![investor as 'foreign' | 'trust' | 'dealer']
    const lots = `${BigInt(shares) < 0n ? '-' : ''}${(BigInt(shares) < 0n ? -BigInt(shares) : BigInt(shares)) / 1000n}.${String((BigInt(shares) < 0n ? -BigInt(shares) : BigInt(shares)) % 1000n).padStart(3, '0')}`
    const exact = jointFixtureConditions({ investor, horizon, min_net_lots: lots }), fixture = jointFixture(exact, data.price!, data.institutional)
    largestJointFixtureGraphBytes = Math.max(largestJointFixtureGraphBytes, jointFixtureGraphBytes([data, fixture]))
    check(largestJointFixtureGraphBytes <= 524288, 'shared boundary graph bound')
    check(fixture.count === 2 && validJointFocus(fixture, exact), 'signed inclusive boundary')
  }
  const emptyValues = jointFixtureConditions({ min_net_lots: '1000000' }), empty = jointFixture(emptyValues, data.price!, data.institutional)
  check(empty.count === 0 && validJointFocus(empty, emptyValues), 'verified zero')
  const reject = (bad: JointFocusData) => { check(!validJointFocus(bad, values), 'corruption clears joint result'); largestJointFixtureGraphBytes = Math.max(largestJointFixtureGraphBytes, jointFixtureGraphBytes([data, empty, bad])); check(largestJointFixtureGraphBytes <= 524288, 'shared corruption graph bound') }
  const second = data.institutional[1], first = data.institutional[0]
  reject({ ...data, institutional: [first, { ...second, windows: { ...second.windows, '20': { ...second.windows!['20'], status: 'unavailable' } } }] })
  reject({ ...data, institutional: [{ ...first, windows: { ...first.windows, '5': { ...first.windows!['5'], values: { ...first.windows!['5'].values!, foreign: '1' } } } }, second] })
  reject({ ...data, policy_digest: 'sha256:' + '0'.repeat(64) })
  reject({ ...data, items: [...data.items].reverse() })
  reject({ ...data, price: { ...data.price!, reads: data.price!.reads.slice(0, -1) } })
  const initial: InstitutionalWindowsData = { ...first, status: 'unavailable', values: null, windows: {}, calendar: null, policy: null, calculation_version: null, provenance: null,
    reasons: ['chips_memory_capture_missing'], capture_state: { ...first.capture_state!, attempted: false, busy: false, cache_present: false, request_count: 0, action: 'not_attempted' } }
  const failed: InstitutionalWindowsData = { ...initial, reasons: ['chips_index_date_outside_scope'], capture_state: { ...initial.capture_state!, attempted: true, cache_present: true, request_count: 2, action: 'cached' } }
  const failedCalendar: InstitutionalWindowsData = { ...failed, calendar: { version: calendarVersion, status: 'unavailable', reasons: failed.reasons, valid_dates: dates.slice(0, 20) } }
  check(!jointDetailEvidenceInvalid(first, 'TPEx', '3105', values.as_of), 'complete held detail remains valid')
  check(!jointDetailEvidenceInvalid(initial, 'TPEx', '3105', values.as_of), 'untouched missing detail permits explicit pre-capture price read')
  check(jointDetailEvidenceInvalid(failed, 'TPEx', '3105', values.as_of), 'attempted failure masks without positive evidence')
  check(jointDetailEvidenceInvalid(failedCalendar, 'TPEx', '3105', values.as_of), 'failed calendar masks both before positive evidence')
  check(jointDetailEvidenceInvalid({ ...failedCalendar, status: 'available' }, 'TPEx', '3105', values.as_of), 'available claim with failed calendar remains masked')
  const failedState = focusTransition({ token: 'detail', epoch: 0, failure: null, price: true, chips: true }, 'detail', 0, 'failure')
  check(failedState.failure && !failedState.price && !failedState.chips, 'attempted detail failure clears both numeric sources')
  check(focusTransition(failedState, 'detail', 0, 'joint') === failedState, 'delayed pre-failure success cannot restore detail numbers')
  largestJointFixtureGraphBytes = Math.max(largestJointFixtureGraphBytes, jointFixtureGraphBytes([data, empty, initial, failed, failedCalendar]))
  check(largestJointFixtureGraphBytes <= 524288, 'shared detail failure graph bound')
  const route = jointDetailPath('3105', values), params = new URL(route, 'http://owned.invalid').searchParams
  check(jointReturnPath(params) === `/saved-price-chips-focus?${new URLSearchParams(values)}`, 'all eight RAW back')
  check(jointDetailContext('TPEx', '3105', params) && !jointDetailContext('TPEx', '5347', params), 'two identity detail')
  check(jointReturnPath(new URLSearchParams(params + '&focus_horizon=5')) === null && jointReturnPath(new URLSearchParams(params + '&unknown=1')) === null, 'detail duplicates/unknown')
  check(jointParams(new URLSearchParams(values)) !== null && jointParams(new URLSearchParams(new URLSearchParams(values) + '&investor=foreign')) === null, 'eight query fields once')
  let state = { token: 'current', epoch: 0, failure: null as string | null, price: true, chips: true }
  state = focusTransition(state, 'current', 0, 'failure')
  check(state.failure && !state.price && !state.chips && state.epoch === 1, 'same token failure masks both')
  check(focusTransition(state, 'current', 0, 'joint') === state && focusTransition(state, 'old', 1, 'joint') === state, 'stale success cannot unmask')
  state = focusTransition(state, 'current', 1, 'price'); check(state.failure && state.price && !state.chips, 'one source cannot unmask')
  state = focusTransition(state, 'current', 1, 'chips'); check(!state.failure && state.price && state.chips, 'two current successes recover')
  return checks
}

export function jointFixtureInputBytes(data: JointFocusData): number {
  return new TextEncoder().encode(JSON.stringify({ conditions: jointFixtureConditions(),
    price_rows: data.price!.reads.map((read) => read.price_saved.latest!.source_fields),
    calendar: data.institutional[0].calendar!.rows!.map((row) => row.source_values), daily: data.institutional.map((read) => read.windows!['20'].daily_evidence!.map((evidence) => evidence.row.source_values)) })).byteLength
}

export function calendarJointFixture(values = jointFixtureConditions(), shared?: JointFocusData): JointFocusData {
  const original = shared ? jointFixture(values, shared.price!, shared.institutional) : jointFixture(values)
  if (shared) return { ...original, version: 'price-saved-chips-focus-calendar/m1-v2',
    policy_version: 'm1-saved-price-chips-focus-calendar-tpex-2026-10-06.2',
    policy_digest: 'sha256:42c232a3f533683dce727ce1279e767038a6ee0f6295ce85b5aee07e998972bc',
    items: original.items.map((item) => ({ ...item, detail_url: jointDetailPath(item.symbol, values, true) })) }
  const replacements: Array<[string, string]> = [
    ['chips-1006-v1', 'chips-1006-calendar-v2'],
    ['m1-chips-cutoff-tpex-2026-10-06.1', 'm1-chips-cutoff-calendar-tpex-2026-10-06.2'],
    [CHIPS1006_POLICY_DIGEST, 'sha256:1acf97b7dd0f13b9b49ed3293497e52ca52ea077256b8d99d9bc21ed5761d403'],
    [calendarVersion, 'tpex-2026-09-01_2026-10-06-full-month-observed-2026-10-07-11503027221/chips-calendar-v2'],
    ['/chips-v1', '/chips-calendar-v2'],
    ['free_public_local', 'free_public_local_full_month_cutoff'],
  ]
  let text = JSON.stringify(original.institutional)
  for (const [from, to] of replacements) text = text.split(from).join(to)
  const institutional = JSON.parse(text) as InstitutionalWindowsData[]
  for (const read of institutional) {
    read.capture_state!.can_capture = false
    const calendar = read.calendar!
    calendar.observation_date = '2026-10-07'
    calendar.original_expected_dates = [...dates, '2026-10-07']
    calendar.original_valid_dates = [...dates, '2026-10-07']
    calendar.post_cutoff_dates = ['2026-10-07']
    const last = calendar.rows![23]
    calendar.original_rows = [...calendar.rows!, { ...last, date: '2026-10-07', row_ordinal: 5,
      source_values: { ...last.source_values, '資料日期': '20261007' } }]
    calendar.evidence = calendar.evidence!.map((receipt, index) => ({ ...receipt,
      candidate_count: [20, 5][index], post_cutoff_row_count: [0, 1][index],
      validation_scope: 'all_returned_month_rows_including_valid_post_cutoff_rows' }))
  }
  return compactFixture({ ...original, version: 'price-saved-chips-focus-calendar/m1-v2',
    policy_version: 'm1-saved-price-chips-focus-calendar-tpex-2026-10-06.2',
    policy_digest: 'sha256:42c232a3f533683dce727ce1279e767038a6ee0f6295ce85b5aee07e998972bc',
    institutional, items: original.items.map((item) => ({ ...item, detail_url: jointDetailPath(item.symbol, values, true) })) })
}

export let largestCalendarFixtureGraphBytes = 0

export function runCalendarFocusTests(): number {
  let checks = 0
  const check = (condition: unknown, message: string) => { checks++; if (!condition) throw new Error(message) }
  const values = jointFixtureConditions({ min_net_lots: '-0.001', min_lots: '0.000', min_range_pct: '0.000' })
  const data = calendarJointFixture(values)
  check(validJointFocus(data, values, true), 'calendar complete positive')
  check(!validJointFocus(data, values), 'old validator rejects independent calendar policy')
  const zeroValues = jointFixtureConditions({ min_net_lots: '1000000.000' })
  const zero = calendarJointFixture(zeroValues, data)
  check(zero.count === 0 && validJointFocus(zero, zeroValues, true), 'calendar verified zero')
  const params = new URL(jointDetailPath('3105', values, true), 'http://owned.invalid').searchParams
  check(jointReturnPath(params, true) === '/saved-price-chips-focus-calendar?' + new URLSearchParams(values), 'all eight original RAW values preserved')
  check(jointReturnPath(params) === null, 'old detail route cannot adopt calendar context')
  check(jointReturnPath(new URLSearchParams(params + '&focus_horizon=5'), true) === null, 'duplicate detail rejects')
  check(jointReturnPath(new URLSearchParams(params + '&unknown=1'), true) === null, 'unknown detail rejects')
  check(jointReturnPath(new URLSearchParams(params.toString().replace('as_of=2026-10-06', 'as_of=2026-10-07')), true) === null, 'detail cutoff mismatch rejects')
  check(jointDetailContext('TPEx', '3105', params, true) && !jointDetailContext('TPEx', '6510', params, true), 'calendar institutional universe')
  check(!jointDetailEvidenceInvalid(data.institutional[0], 'TPEx', '3105', values.as_of, true), 'calendar joint detail valid')
  const partial = { ...data, price: { ...data.price!, reads: data.price!.reads.slice(0, 6) } }
  check(!validJointFocus(partial, values, true), 'all seven saved prices precede counts')
  const missing = { ...zero, institutional: [zero.institutional[0], { ...zero.institutional[1], windows: {} }] }
  check(!validJointFocus(missing, zeroValues, true), 'price zero cannot bypass both full windows')
  largestCalendarFixtureGraphBytes = jointFixtureGraphBytes([data, zero, partial, missing])
  check(largestCalendarFixtureGraphBytes <= 524288, 'aggregate shared calendar boundary graph cap')
  let state = focusTransition({ token: 'now', epoch: 0, failure: null, price: true, chips: true }, 'now', 0, 'failure')
  check(state.failure && !state.price && !state.chips, 'current failure clears both')
  check(focusTransition(state, 'now', 0, 'joint') === state, 'old success cannot unmask')
  state = focusTransition(state, 'now', 1, 'price')
  check(state.failure && state.price && !state.chips, 'new private snapshot alone cannot recover')
  state = focusTransition(state, 'now', 1, 'chips')
  check(!state.failure && state.price && state.chips, 'new snapshot plus held full verification recovers')
  return checks
}
