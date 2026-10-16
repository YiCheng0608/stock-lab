import { renderToStaticMarkup } from 'react-dom/server'
import type { OrdinaryCloseTrendData } from './types'
import {
  ORDINARY_CLOSE_TREND_UNSUPPORTED, OrdinaryCloseTrend, OrdinaryCloseTrendView, formatOrdinaryCloseValue, ordinaryCloseTrendRelevant, ordinaryCloseTrendSupported,
  readOrdinaryCloseTrend, recomputeOrdinaryCloseTrend, roundHalfUp, settleTrendRead, validOrdinaryCloseTrend, visibleTrendState,
} from './OrdinaryCloseTrend'
import type { TrendState } from './OrdinaryCloseTrend'

/**
 * Client-only checks. GOLDEN is the backend payload for a synthetic test bundle (test data, not a real source or the real
 * private root): backend/tests/test_ordinary_close_trend.py produced it with read_ordinary_close_trend, so this file also
 * proves the TypeScript gate accepts exactly what the Python product emits.
 */
const GOLDEN: OrdinaryCloseTrendData = {"as_of":"2026-10-06","closes":[{"close":"13.8643","date":"2026-09-04"},{"close":"14.1577","date":"2026-09-07"},{"close":"13.8578","date":"2026-09-08"},{"close":"14.166","date":"2026-09-09"},{"close":"13.8809","date":"2026-09-10"},{"close":"13.6032","date":"2026-09-11"},{"close":"13.9336","date":"2026-09-14"},{"close":"13.6707","date":"2026-09-15"},{"close":"14.0159","date":"2026-09-16"},{"close":"13.7678","date":"2026-09-17"},{"close":"14.1278","date":"2026-09-18"},{"close":"13.8945","date":"2026-09-21"},{"close":"13.6686","date":"2026-09-22"},{"close":"14.0508","date":"2026-09-23"},{"close":"13.8397","date":"2026-09-24"},{"close":"13.636","date":"2026-09-29"},{"close":"14.0404","date":"2026-09-30"},{"close":"13.8515","date":"2026-10-01"},{"close":"13.67","date":"2026-10-02"},{"close":"14.0966","date":"2026-10-05"},{"close":"13.9299","date":"2026-10-06"}],"exchange":"TPEx","limitations":["date_is_asia_taipei_trading_calendar_date_not_utc","identity_and_unit_anchored_only_at_2026-10-06","publication_time_first_availability_revision_time_unknown","closes_only_no_open_high_low_volume_amount","raw_body_not_stored_hashes_only","personal_noncommercial_local_use_no_redistribution","provider_reported_nominal_closes_not_adjusted_for_company_actions","suspension_comparability_not_established","trend_judgement_formula_not_defined_not_inferred","not_historical_pit_not_a_plan_signal_or_trade"],"origin":"private_local","price_basis":"provider_reported_nominal_close","provenance":{"adapter":{"ohlcv_history_source_sha256":"f1adbf6ca71fff64204bded4c0b586a59357d901658c1dcfffc8df3d5bfe0930","ordinary_close_source_sha256":"242569e216ff39ab88f925a497276ad299c75a0045a595d4d73bd8b0cb5f10c5"},"attribution":"synthetic test attribution","calendar":{"rows":68,"source_version":"finmind-trading-dates-checked-against-formal-aug21-sep20-oct4/issue7-v1","timezone":"Asia/Taipei trading calendar date","window":{"end_date":"2026-10-06","start_date":"2026-07-01"}},"closes_bytes":11483,"closes_file":"closes.json","closes_sha256":"68e806e19c6bc4efa8c2cde7699d7ff142b6fd76947bb4d2b5abb0a2e81d5c57","consumer_version":"ordinary-close-saved-window-v1","cutoff":"2026-10-06","first_availability":"unknown","historical_pit":"unsupported","publication_time":"unknown","receipt_sha256":"b9ed521fd85db664addc0dbd477c6725d6d03beb8450e2accdc99da10146380a","revision_time":"unknown","rights":{"price_source":"synthetic test rights text","trading_date_source":"synthetic test rights text"},"saved_at":"2026-10-06T23:32:40+00:00","source_policy":{"bytes":5173,"sha256":"f7659362cd3056413545d48a40a2e89bc97b810dc9c5535a4c8bdca41fcb9968","version":"issue7-ordinary-close-saved-seven-v1"},"storage":"private_local","storage_schema":"ordinary-close-saved/v1"},"read_state":{"network_requests":0,"read_only":true,"verified":true,"writes":0},"reasons":[],"status":"available","supported_scope":{"cutoff":"2026-10-06","instrument_type":"ordinary_stock","market":"TW/TPEx","symbols":["3105","3293","5274","5347","6488","6510","8069"]},"symbol":"6488","unit":"TWD_per_share","unsupported":["historical_pit","publication_time","first_availability","revision_guarantee","adjusted_prices","company_actions","suspension_comparability","whole_window_historical_membership","historical_eligibility","actionable_strategy","plan","trading","historical_simulation","raw_body_storage","redistribution","other_cutoffs"],"values":{"close_over_ma20":{"display":"1.0027","display_places":4,"display_scale":1,"display_unit":"ratio","exact":"464330/463099","latest_close":"13.9299","latest_date":"2026-10-06","ma20_window_end":"2026-10-06","ma20_window_start":"2026-09-07","reasons":[],"rounding":"half_up_away_from_zero","status":"available"},"latest":{"close":"13.9299","date":"2026-10-06"},"ma20":{"count":20,"display":"13.89","display_places":2,"display_scale":1,"display_unit":"TWD_per_share","exact":"1389297/100000","reasons":[],"rounding":"half_up_away_from_zero","status":"available","window_end":"2026-10-06","window_start":"2026-09-07"},"return_20d":{"base_close":"13.8643","base_date":"2026-09-04","display":"0.47","display_places":2,"display_scale":100,"display_unit":"percent","exact":"656/138643","latest_close":"13.9299","latest_date":"2026-10-06","reasons":[],"rounding":"half_up_away_from_zero","status":"available"},"trend":{"display":null,"exact":null,"reasons":["trend_formula_not_defined"],"status":"formula_not_defined"}},"version":"ordinary-close-trend/m1-v1","windows":{"ma_days":20,"return_closes":21,"return_days":20}}

type Loose = any // eslint-free mutation helper: invalid shapes are the point of these checks
let count = 0
const check = (condition: boolean, message: string) => { count++; if (!condition) throw new Error(message) }
const clone = (): Loose => JSON.parse(JSON.stringify(GOLDEN))
const edited = (change: (value: Loose) => void): Loose => { const value = clone(); change(value); return value }
const valid = (value: unknown, exchange = 'TPEx', symbol = '6488', asOf = '2026-10-06') => validOrdinaryCloseTrend(value, exchange, symbol, asOf)
const unavailable = (reasons: string[]): Loose => edited((x) => {
  x.status = 'unavailable'; x.closes = []; x.values = null; x.provenance = null; x.reasons = reasons
  x.read_state = { verified: false, read_only: true, network_requests: 0, writes: 0 }
})
const noop = () => {}

// 1. The gate accepts exactly the payload the Python product emitted, and only for the requested stock and cutoff.
check(valid(GOLDEN), 'python payload accepted')
check(!valid(GOLDEN, 'TWSE') && !valid(GOLDEN, 'TPEx', '3105') && !valid(GOLDEN, 'TPEx', '9999') && !valid(GOLDEN, 'TPEx', '6488', '2026-10-05')
  && !valid(GOLDEN, 'TPEx', '6488', '') && !valid(null) && !valid('x') && !valid(5) && !valid([]) && !valid(undefined), 'request context and non-objects rejected')

// 2. Every contract field is re-checked: any single drift rejects the whole response.
const drifts: Array<[string, (value: Loose) => void]> = [
  ['version', (x) => { x.version = 'ordinary-close-trend/m1-v0' }], ['origin', (x) => { x.origin = 'process_memory' }],
  ['exchange', (x) => { x.exchange = 'TWSE' }], ['symbol', (x) => { x.symbol = '3105' }], ['as_of', (x) => { x.as_of = '2026-10-05' }],
  ['extra top key', (x) => { x.forecast = 1 }], ['missing top key', (x) => { delete x.limitations }],
  ['price basis', (x) => { x.price_basis = 'adjusted_close' }], ['unit', (x) => { x.unit = 'TWD' }],
  ['scope cutoff', (x) => { x.supported_scope.cutoff = '2026-10-05' }], ['scope symbols', (x) => { x.supported_scope.symbols.pop() }],
  ['ma days', (x) => { x.windows.ma_days = 19 }], ['return closes', (x) => { x.windows.return_closes = 20 }],
  ['unsupported lacks other_cutoffs', (x) => { x.unsupported = x.unsupported.filter((item: string) => item !== 'other_cutoffs') }],
  ['unsupported lacks adjusted_prices', (x) => { x.unsupported = x.unsupported.filter((item: string) => item !== 'adjusted_prices') }],
  ['unsupported lacks publication_time', (x) => { x.unsupported = x.unsupported.filter((item: string) => item !== 'publication_time') }],
  ['unsupported has one extra', (x) => { x.unsupported.push('forecast') }],
  ['unsupported extra replaces nothing', (x) => { x.unsupported = [...x.unsupported, 'adjusted_prices'] }],
  ['unsupported duplicate in place of one', (x) => { x.unsupported[15] = x.unsupported[0] }],
  ['unsupported swapped for a different item', (x) => { x.unsupported[15] = 'forecast' }],
  ['unsupported empty', (x) => { x.unsupported = [] }], ['unsupported not a list', (x) => { x.unsupported = 'historical_pit' }],
  ['unsupported non-string item', (x) => { x.unsupported[3] = 4 }],
  ['reasons on available', (x) => { x.reasons = ['ordinary_close_saved_missing'] }], ['status', (x) => { x.status = 'partial' }],
  ['read_state network', (x) => { x.read_state.network_requests = 1 }], ['read_state writes', (x) => { x.read_state.writes = 1 }],
  ['read_state unverified', (x) => { x.read_state.verified = false }], ['read_state not read only', (x) => { x.read_state.read_only = false }],
  ['closes 20 rows', (x) => { x.closes.pop() }], ['closes 22 rows', (x) => { x.closes.push({ date: '2026-10-07', close: '14' }) }],
  ['last date is not the cutoff', (x) => { x.closes[20].date = '2026-10-07' }], ['dates not ascending', (x) => { x.closes[3].date = x.closes[2].date }],
  ['impossible date', (x) => { x.closes[3].date = '2026-09-31' }], ['close value changed', (x) => { x.closes[3].close = '14.167' }],
  ['close trailing zero', (x) => { x.closes[3].close = '14.1660' }], ['close exponent', (x) => { x.closes[3].close = '1.4166e1' }],
  ['close zero', (x) => { x.closes[3].close = '0' }], ['close negative', (x) => { x.closes[3].close = '-14.166' }],
  ['close number', (x) => { x.closes[3].close = 14.166 }], ['close extra key', (x) => { x.closes[3].volume = '1' }],
  ['latest close', (x) => { x.values.latest.close = '13.93' }], ['latest date', (x) => { x.values.latest.date = '2026-10-05' }],
  ['ma20 display', (x) => { x.values.ma20.display = '13.90' }], ['ma20 exact', (x) => { x.values.ma20.exact = '1389298/100000' }],
  ['ma20 unreduced exact', (x) => { x.values.ma20.exact = '2778594/200000' }], ['ma20 window start', (x) => { x.values.ma20.window_start = '2026-09-04' }],
  ['ma20 unit', (x) => { x.values.ma20.display_unit = 'ratio' }], ['ma20 places', (x) => { x.values.ma20.display_places = 3 }],
  ['ma20 rounding mode', (x) => { x.values.ma20.rounding = 'half_even' }], ['ma20 count', (x) => { x.values.ma20.count = 21 }],
  ['ma20 insufficient while 21 closes', (x) => { Object.assign(x.values.ma20, { status: 'data_insufficient', exact: null, display: null }) }],
  ['return display', (x) => { x.values.return_20d.display = '0.48' }], ['return exact', (x) => { x.values.return_20d.exact = '657/138643' }],
  ['return scale', (x) => { x.values.return_20d.display_scale = 1 }], ['return base date', (x) => { x.values.return_20d.base_date = '2026-09-07' }],
  ['return base close', (x) => { x.values.return_20d.base_close = '14.1577' }],
  ['ratio display', (x) => { x.values.close_over_ma20.display = '1.0028' }], ['ratio exact', (x) => { x.values.close_over_ma20.exact = '1/1' }],
  ['ratio window end', (x) => { x.values.close_over_ma20.ma20_window_end = '2026-10-05' }],
  ['trend inferred', (x) => { x.values.trend = { status: 'rising', exact: null, display: '上升', reasons: [] } }],
  ['trend status only', (x) => { x.values.trend.status = 'rising' }], ['trend display', (x) => { x.values.trend.display = '上升' }], ['trend reasons', (x) => { x.values.trend.reasons = [] }],
  ['values missing', (x) => { x.values = null }], ['values extra key', (x) => { x.values.signal = 'buy' }],
  ['provenance missing', (x) => { x.provenance = null }], ['provenance extra key', (x) => { x.provenance.signed = true }],
  ['provenance missing key', (x) => { delete x.provenance.rights }],
  ['closes sha not hex', (x) => { x.provenance.closes_sha256 = 'g'.repeat(64) }], ['closes sha short', (x) => { x.provenance.closes_sha256 = 'a'.repeat(63) }],
  ['receipt sha upper case', (x) => { x.provenance.receipt_sha256 = x.provenance.receipt_sha256.toUpperCase() }],
  ['policy sha', (x) => { x.provenance.source_policy.sha256 = 'a'.repeat(64) }], ['policy bytes', (x) => { x.provenance.source_policy.bytes = 5172 }],
  ['policy version', (x) => { x.provenance.source_policy.version = 'issue7-ordinary-close-saved-seven-v2' }],
  ['provenance cutoff', (x) => { x.provenance.cutoff = '2026-10-05' }], ['saved_at not UTC', (x) => { x.provenance.saved_at = '2026-10-06T23:32:40Z' }],
  ['saved_at offset', (x) => { x.provenance.saved_at = '2026-10-07T07:32:40+08:00' }], ['pit', (x) => { x.provenance.historical_pit = 'supported' }],
  ['publication time', (x) => { x.provenance.publication_time = '2026-10-06' }], ['storage', (x) => { x.provenance.storage = 'process_memory' }],
  ['calendar end before cutoff', (x) => { x.provenance.calendar.window.end_date = '2026-10-05' }],
  ['adapter hash', (x) => { x.provenance.adapter.ordinary_close_source_sha256 = 'zz' }], ['attribution empty', (x) => { x.provenance.attribution = '' }],
]
for (const [label, change] of drifts) check(!valid(edited(change)), `drift rejected: ${label}`)

// 2b. `unsupported` must equal the policy v1 list as a set: verbatim 16 items, one missing or one extra rejects the whole response.
const POLICY_UNSUPPORTED = ['historical_pit', 'publication_time', 'first_availability', 'revision_guarantee', 'adjusted_prices', 'company_actions',
  'suspension_comparability', 'whole_window_historical_membership', 'historical_eligibility', 'actionable_strategy', 'plan', 'trading',
  'historical_simulation', 'raw_body_storage', 'redistribution', 'other_cutoffs']
check(POLICY_UNSUPPORTED.length === 16 && new Set(POLICY_UNSUPPORTED).size === 16, 'policy list has 16 distinct items')
check(JSON.stringify(ORDINARY_CLOSE_TREND_UNSUPPORTED) === JSON.stringify(POLICY_UNSUPPORTED), 'client list is the verbatim policy list')
check(JSON.stringify(GOLDEN.unsupported) === JSON.stringify(POLICY_UNSUPPORTED), 'python payload carries the verbatim policy list')
for (const missing of POLICY_UNSUPPORTED) {
  check(!valid(edited((x) => { x.unsupported = POLICY_UNSUPPORTED.filter((item) => item !== missing) })), `one missing is rejected: ${missing}`)
}
for (const extra of ['forecast', 'adjusted_prices', 'Other_cutoffs', '']) check(!valid(edited((x) => { x.unsupported = [...POLICY_UNSUPPORTED, extra] })), `one extra is rejected: "${extra}"`)
check(valid(edited((x) => { x.unsupported = [...POLICY_UNSUPPORTED].reverse() })), 'order is not part of the contract (set equality)')
check(!valid(edited((x) => { Object.assign(x, unavailable(['ordinary_close_saved_missing'])); x.unsupported.pop() })), 'unavailable payload also needs the full list (one missing)')
check(!valid(edited((x) => { Object.assign(x, unavailable(['ordinary_close_saved_missing'])); x.unsupported.push('forecast') })), 'unavailable payload also needs the exact list (one extra)')
check(valid(unavailable(['ordinary_close_saved_missing'])), 'unavailable payload with the exact list is accepted')

// 3. Unavailable responses carry reasons only: no values, closes or provenance may ride along.
check(valid(unavailable(['ordinary_close_saved_missing'])) && valid(unavailable(['ordinary_close_cutoff_not_supported', 'ordinary_close_root_unset'])), 'unavailable accepted')
check(!valid(unavailable([])) && !valid(unavailable(['Bad Reason'])) && !valid(unavailable(['x'.repeat(65)])) && !valid(unavailable([5 as unknown as string])), 'unavailable needs coded reasons')
for (const [label, change] of [
  ['values', (x: Loose) => { x.values = GOLDEN.values }], ['closes', (x: Loose) => { x.closes = GOLDEN.closes }],
  ['provenance', (x: Loose) => { x.provenance = GOLDEN.provenance }], ['verified', (x: Loose) => { x.read_state.verified = true }],
] as Array<[string, (x: Loose) => void]>) check(!valid(edited((x) => { Object.assign(x, unavailable(['ordinary_close_saved_missing'])); change(x) })), `unavailable with ${label} rejected`)

// 4. Arithmetic: hand-computed values, ties, and the client recomputation.
const rows = (texts: string[]) => texts.map((close, index) => ({ date: `2026-09-${String(index + 1).padStart(2, '0')}`, close }))
const hand = recomputeOrdinaryCloseTrend(rows(['100', ...Array(10).fill('101'), ...Array(10).fill('102')]))
check(!!hand && hand.ma20.n === 203n && hand.ma20.d === 2n && hand.return_20d.n === 1n && hand.return_20d.d === 50n && hand.close_over_ma20.n === 204n && hand.close_over_ma20.d === 203n, 'hand-computed MA20, return and ratio')
const tie = recomputeOrdinaryCloseTrend(rows(['100', ...Array(19).fill('100'), '102.5']))
check(!!tie && tie.ma20.n === 801n && tie.ma20.d === 8n && roundHalfUp(tie.ma20, 2) === '100.13', 'MA20 tie rounds up from the exact value')
const up = recomputeOrdinaryCloseTrend(rows(['800', ...Array(19).fill('800'), '801'])), down = recomputeOrdinaryCloseTrend(rows(['800', ...Array(19).fill('800'), '799']))
check(roundHalfUp({ n: up!.return_20d.n * 100n, d: up!.return_20d.d }, 2) === '0.13' && roundHalfUp({ n: down!.return_20d.n * 100n, d: down!.return_20d.d }, 2) === '-0.13', 'return ties round away from zero')
check(recomputeOrdinaryCloseTrend(rows(Array(20).fill('100'))) === null && recomputeOrdinaryCloseTrend(rows([...Array(20).fill('100'), '1e2'])) === null
  && recomputeOrdinaryCloseTrend(rows([...Array(20).fill('100'), '100.50'])) === null && recomputeOrdinaryCloseTrend(rows([...Array(20).fill('100'), '0'])) === null, 'short or non-canonical windows are never recomputed')
const cases: Array<[bigint, bigint, number, string]> = [[1n, 8n, 2, '0.13'], [-1n, 8n, 2, '-0.13'], [5n, 2n, 0, '3'], [-5n, 2n, 0, '-3'], [-1n, 1000n, 2, '0.00'],
  [1n, 3n, 4, '0.3333'], [2n, 3n, 4, '0.6667'], [203n, 2n, 2, '101.50'], [0n, 1n, 2, '0.00'], [99995n, 1000n, 2, '100.00'], [-99995n, 1000n, 2, '-100.00']]
for (const [n, d, places, expected] of cases) check(roundHalfUp({ n, d }, places) === expected, `roundHalfUp ${n}/${d} @${places}`)
const shown = GOLDEN.values!
check(formatOrdinaryCloseValue(shown.ma20) === '13.89 元／股' && formatOrdinaryCloseValue(shown.return_20d) === '+0.47%'
  && formatOrdinaryCloseValue(shown.close_over_ma20) === '1.0027', 'value formatting')
check(formatOrdinaryCloseValue({ ...shown.return_20d, display: '-0.13' }) === '-0.13%' && formatOrdinaryCloseValue({ ...shown.return_20d, display: '0.00' }) === '0.00%'
  && formatOrdinaryCloseValue({ ...shown.ma20, status: 'data_insufficient', display: null, exact: null }) === '資料不足，不補算', 'sign, zero and insufficient formatting')
check(ordinaryCloseTrendRelevant('TPEx', '6488') && !ordinaryCloseTrendRelevant('TWSE', '6488') && !ordinaryCloseTrendRelevant('TPEx', '9999')
  && ordinaryCloseTrendSupported('TPEx', '6488', '2026-10-06') && !ordinaryCloseTrendSupported('TPEx', '6488', '') && !ordinaryCloseTrendSupported('TPEx', '6488', '2026-10-05'), 'scope gates')

// 5. Context isolation: values never survive a stock/date switch, and late responses cannot fill another context.
const loaded: TrendState = { token: '0:TPEx:6488:2026-10-06', phase: 'loaded', data: GOLDEN }
check(visibleTrendState(loaded, '0:TPEx:6488:2026-10-06') === loaded, 'same context keeps the value')
const switched = visibleTrendState(loaded, '1:TPEx:3105:2026-10-06')
check(switched.phase === 'idle' && switched.token === '1:TPEx:3105:2026-10-06' && !('data' in switched), 'other stock shows idle without values')
check(visibleTrendState(loaded, '2:TPEx:6488:2026-10-06').phase === 'idle', 'returning to the same stock after a switch needs a new explicit read')
const busy: TrendState = { token: 'B', phase: 'busy' }
check(settleTrendRead(busy, 'A', 'B', { kind: 'loaded', data: GOLDEN }) === busy, 'late response for an earlier context is dropped')
const settled = settleTrendRead(busy, 'B', 'B', { kind: 'loaded', data: GOLDEN })
check(settled.phase === 'loaded' && settled.token === 'B', 'current response is adopted')
const failed = settleTrendRead(loaded, loaded.token, loaded.token, { kind: 'failed', reason: 'ordinary_close_request_failed' })
check(failed.phase === 'failed' && !('data' in failed), 'a failure replaces the earlier values with the reason')

// 6. Rendering (SSR is layout evidence only; the native browser operation belongs to QA).
const view = (state: TrendState, asOf = '2026-10-06', exchange = 'TPEx', symbol = '6488') =>
  renderToStaticMarkup(<OrdinaryCloseTrendView exchange={exchange} symbol={symbol} asOf={asOf} state={state} onRead={noop} />)
const idleHtml = view({ token: 't', phase: 'idle' })
check(idleHtml.includes('讀取已保存收盤與 MA20') && idleHtml.includes('尚未讀取') && !idleHtml.includes('<table') && !idleHtml.includes('趨勢判定規格未定義'), 'idle shows the explicit read only')
const busyHtml = view({ token: 't', phase: 'busy' })
check(busyHtml.includes('讀取中…') && /<button[^>]*disabled/.test(busyHtml), 'busy disables the button')
for (const asOf of ['', '2026-10-05', '2026-10-07']) {
  const html = view({ token: 't', phase: 'idle' }, asOf)
  check(html.includes('不符') && html.includes('不讀取') && !html.includes('<button'), `cutoff ${asOf || '(none)'} is explained and not readable`)
}
check(view({ token: 't', phase: 'idle' }, '2026-10-06', 'TWSE', '2330') === '' && view({ token: 't', phase: 'idle' }, '2026-10-06', 'TPEx', '9999') === '', 'other stocks do not render the block')
const loadedHtml = view({ token: 't', phase: 'loaded', data: GOLDEN })
for (const text of ['13.9299', '13.89 元／股', '+0.47%', '1.0027', '趨勢判定規格未定義，不推論', '名目收盤，未還原', '1389297/100000', '656/138643', '464330/463099',
  GOLDEN.provenance!.closes_sha256, GOLDEN.provenance!.receipt_sha256, GOLDEN.provenance!.source_policy.sha256, '2026-10-06T23:32:40+00:00', 'issue7-ordinary-close-saved-seven-v1',
  '不支援：historical_pit', '2026-09-07～2026-10-06', '2026-10-06 收盤 ÷ 2026-09-04 收盤 − 1']) check(loadedHtml.includes(text), `loaded view shows ${text}`)
for (const row of GOLDEN.closes) check(loadedHtml.includes(`<td>${row.date}</td><td class="numeric-cell">${row.close}</td>`), `daily row ${row.date}`)
check(!/NaN|undefined|null|\[object/.test(loadedHtml), 'no placeholder leakage')
const unavailableHtml = view({ token: 't', phase: 'loaded', data: unavailable(['ordinary_close_saved_missing']) })
check(unavailableHtml.includes('找不到已保存的收盤資料') && unavailableHtml.includes('ordinary_close_saved_missing') && !unavailableHtml.includes('<table') && !unavailableHtml.includes('MA20（元／股）'), 'unavailable shows the reason and no values')
const failedHtml = view({ token: 't', phase: 'failed', reason: 'ordinary_close_contract_invalid' })
check(failedHtml.includes('回應未通過前端核對') && failedHtml.includes('ordinary_close_contract_invalid') && !failedHtml.includes('<table'), 'contract failure shows the reason and no values')
check(view({ token: 't', phase: 'failed', reason: 'ordinary_close_request_failed' }).includes('讀取請求失敗，已清除先前數值'), 'request failure reason')
let reads = 0
const counting = async () => { reads++; return GOLDEN }
const mounted = renderToStaticMarkup(<OrdinaryCloseTrend exchange="TPEx" symbol="6488" asOf="2026-10-06" fetcher={counting} />)
check(mounted.includes('讀取已保存收盤與 MA20') && !mounted.includes('<table') && reads === 0, 'mounting never reads')
check(renderToStaticMarkup(<OrdinaryCloseTrend exchange="TWSE" symbol="2330" asOf="2026-10-06" fetcher={counting} />) === '' && reads === 0, 'unrelated stock mounts nothing')

// 7. The explicit read: arguments, validation and failure mapping.
async function main(): Promise<void> {
  const calls: string[] = []
  const reading = (answer: () => unknown) => async (exchange: string, symbol: string, asOf: string) => { calls.push(`${exchange}:${symbol}:${asOf}`); return answer() }
  const ok = await readOrdinaryCloseTrend(reading(() => GOLDEN), 'TPEx', '6488', '2026-10-06')
  check(ok.kind === 'loaded' && calls.join() === 'TPEx:6488:2026-10-06', 'read passes the exact stock and cutoff and adopts a valid response')
  const gone = await readOrdinaryCloseTrend(reading(() => unavailable(['ordinary_close_saved_missing'])), 'TPEx', '6488', '2026-10-06')
  check(gone.kind === 'loaded' && gone.data.status === 'unavailable', 'a valid unavailable response is shown as unavailable')
  const thrown = await readOrdinaryCloseTrend(async () => { throw new Error('API 500') }, 'TPEx', '6488', '2026-10-06')
  check(thrown.kind === 'failed' && thrown.reason === 'ordinary_close_request_failed', 'request errors become a reason')
  for (const [label, answer] of [['tampered', () => edited((x) => { x.values.ma20.display = '99.99' })], ['wrong stock', () => edited((x) => { x.symbol = '3105' })],
    ['null', () => null], ['text', () => 'ok'], ['list', () => []]] as Array<[string, () => unknown]>) {
    const result = await readOrdinaryCloseTrend(reading(answer), 'TPEx', '6488', '2026-10-06')
    check(result.kind === 'failed' && result.reason === 'ordinary_close_contract_invalid', `${label} response rejected`)
  }
}

// A failed async check rejects, which ends the Node process with a non-zero exit code.
void main().then(() => console.log(`OrdinaryCloseTrend ${count} checks passed`))
