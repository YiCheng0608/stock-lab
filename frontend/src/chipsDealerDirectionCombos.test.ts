import { canonicalJson } from './chipsGross'
import { COMBOS_CALCULATION, COMBOS_CONSUMER_VERSION, COMBOS_DATASET, COMBOS_KEYS, COMBOS_NAMESPACE, COMBOS_POLICY_VERSION, COMBOS_ROUTE, COMBOS_ROW_NAMES, COMBOS_SCHEMA, COMBOS_SYMBOLS, COMBOS_WINDOW_DATES, comboActionAllowed, comboBound, comboControls, comboInt, comboExpectedPin, comboLots, comboPath, comboPinValid, comboRequestInit, comboReturnPath, comboSHA, comboSegments, comboURL, deriveComboWindow, resolveComboResponse, validComboControls, validComboParams, validateCombos } from './chipsDealerDirectionCombos'
import type { ComboPoint, ComboRead, ComboRow } from './chipsDealerDirectionCombos'
import { installComboPageLifecycle, isComboTrustedAction } from './ChipsDealerDirectionCombosPage'
type Assert = (ok: unknown, label: string) => void

const POLICY_SHA = '7db5e7a7e17f883e7e4e81de297ce2e4ad8c6c4fcde409b7cbeae0eaa56696b1'
const API_ORDER = ['Foreign_Investor', 'Foreign_Dealer_Self', 'Investment_Trust', 'Dealer_self', 'Dealer_Hedging']
// Synthetic per-symbol daily nets (shares / 1250); never source truth. Index 6 is real zeros everywhere.
const SELF = [[4, -3, 0, 2, -1], [5, 7, 0, 3, 4], [0, 0, -6, -6, -6], [1, 1, 1, 1, 1], [-1, -1, -1, -1, -1], [2, -2, 2, -2, 2], [0, 0, 0, 0, 0]]
const HEDGE = [[-1, 2, 0, -2, 1], [-2, -3, -1, -4, 0], [3, 3, 3, 0, -3], [1, 1, 1, 1, 1], [0, 0, 0, 0, 0], [-2, 2, -2, 2, -2], [0, 0, 0, 0, 0]]
const SCALE = 1250

/** Minimal synthetic FinMind-shaped payload, rebuilt in RAM; never official evidence. */
export async function createCombosFixture(): Promise<{ read: ComboRead; sourceInputBytes: number }> {
  const dates = ['2026-09-29', ...COMBOS_WINDOW_DATES]
  const receipts: ComboRead['receipts'] = [], stocks: ComboRead['stocks'] = []
  let sourceInputBytes = 0
  for (const [ordinal, symbol] of COMBOS_SYMBOLS.entries()) {
    const order = ordinal === 3 ? ['Dealer_Hedging', 'Dealer_self', 'Investment_Trust', 'Foreign_Dealer_Self', 'Foreign_Investor'] : API_ORDER
    const wire: Record<string, unknown>[] = []
    const points: ComboPoint[] = []
    for (const [d, day] of dates.entries()) {
      const rows: ComboRow[] = []
      for (const name of order) {
        const dealer = name === 'Dealer_self' ? SELF[ordinal][d - 1] : name === 'Dealer_Hedging' ? HEDGE[ordinal][d - 1] : 0
        const net = (d === 0 ? 3 : dealer) * SCALE
        const base = name.startsWith('Dealer') && ordinal === 6 ? 0 : 1000 + ordinal * 7 + d
        const buy = base + Math.max(net, 0), sell = base + Math.max(-net, 0)
        wire.push({ buy, date: day, name, sell, stock_id: symbol })
        rows.push({ row_index: wire.length - 1, key_order: ['buy', 'date', 'name', 'sell', 'stock_id'], date: day, stock_id: symbol, name, buy_shares: String(buy), sell_shares: String(sell) })
      }
      if (d > 0) points.push({ date: day, index: d - 1, request_index: ordinal, url: comboURL(symbol), receipt_sha256: '', body_sha256: '', rows, self: null as never, hedge: null as never, combination: 'zero_zero', opposite: false })
    }
    const body = JSON.stringify({ msg: 'success', status: 200, data: wire }), bodySHA = await comboSHA(body), bytes = new TextEncoder().encode(body).length
    sourceInputBytes += bytes
    const time = (second: number) => '2026-10-12T12:00:' + String(second).padStart(2, '0') + '.000000+00:00'
    const original = { source_id: 'finmind_institutional_investors/' + symbol, source_version: COMBOS_POLICY_VERSION, method: 'GET', url: comboURL(symbol), status: 200, request_started_utc: time(ordinal * 2), observed_utc: time(ordinal * 2 + 1), body_bytes: bytes, body_sha256: bodySHA, full_eof: true, content_type: 'application/json', content_encoding: 'identity', namespace: COMBOS_NAMESPACE, policy_sha256: POLICY_SHA }
    const canonical = canonicalJson(original), sha256 = await comboSHA(canonical)
    receipts.push({ request_index: ordinal, symbol, url: comboURL(symbol), canonical, sha256, body_sha256: bodySHA, body_bytes: bytes })
    for (const p of points) { p.receipt_sha256 = sha256; p.body_sha256 = bodySHA }
    const derived = deriveComboWindow(points)
    stocks.push({ symbol, name: { '3105': '穩懋', '3293': '鈊象', '5274': '信驊', '5347': '世界', '6488': '環球晶', '6510': '精測', '8069': '元太' }[symbol] as string, exchange: 'TPEx', security_type: 'stock', currency: 'TWD', unit: 'shares', window: { horizon: 5, ...derived } })
  }
  const read: ComboRead = {
    schema: COMBOS_SCHEMA, calculation_version: COMBOS_CALCULATION, consumer_version: COMBOS_CONSUMER_VERSION, namespace: COMBOS_NAMESPACE,
    as_of: '2026-10-06', generation: 'synthetic-generation-1', state: 'available', available: true, reason: null, failure: null, count: 7,
    window_dates: [...COMBOS_WINDOW_DATES], stocks,
    calendar: { reference: 'SOURCE_REGISTRY 31.2', closed_dates: ['2026-09-25', '2026-09-28'], calendar_gets: 0, window_dates: [...COMBOS_WINDOW_DATES], anchor_only_dates: ['2026-09-29'], meaning: 'fixed verified trading days; no calendar GET, no closure inference' },
    receipts,
    provenance: { namespace: COMBOS_NAMESPACE, policy_sha256: POLICY_SHA, policy_version: COMBOS_POLICY_VERSION, consumer_version: COMBOS_CONSUMER_VERSION, market: 'TW/TPEx', cutoff: '2026-10-06', instrument_type: 'ordinary_stock', source_use: 'synthetic', dataset: COMBOS_DATASET, unit: 'shares', rights: 'FinMind personal noncommercial local RAM; attribution; no raw redistribution or mirror', calendar_reference: 'SOURCE_REGISTRY 31.2', calendar_gets: 0, value_label: 'API value at acquisition time; buy/sell may later grow by equal same-category late bookings (net unaffected); not PIT', anchors_checked: 56, record_only_comparison: { compared_values: 210, expected_zero_set: [], observed_zero_set: [], only_expected: [], only_observed: [], matches: false, gate: false }, publication_time: 'unknown', first_availability: 'unknown', revision_time: 'unknown', unsupported: ['historical_pit'], storage: 'process_RAM' },
    attempted: true, request_count: 7,
  }
  return { read, sourceInputBytes }
}
export async function runComboChecks(read: ComboRead, assert: Assert): Promise<number> {
  let checks = 0
  const check = (ok: unknown, label: string) => { assert(ok, label); checks++ }
  async function rejected(change: (copy: ComboRead) => void | Promise<void>, label: string) { const copy = structuredClone(read); await change(copy); check(await validateCombos(copy, { pin: POLICY_SHA }) === null, label) }
  check(await validateCombos(read, { pin: POLICY_SHA }) !== null, 'ALL7 stocks / 35 point days / 175 original name rows / receipts validate')
  check(await validateCombos(read, { pin: POLICY_SHA }) !== null && await validateCombos(read, { pin: 'a'.repeat(64) }) === null, 'externally supplied policy pin must match the payload and every receipt')
  // R1-3: fail closed. An empty, missing or malformed pin never skips the comparison - nothing is shown.
  for (const bad of ['', 'abc', 'A'.repeat(64), POLICY_SHA.slice(1), POLICY_SHA + '0', ' ' + POLICY_SHA]) check(await validateCombos(read, { pin: bad }) === null && !comboPinValid(bad), 'a missing or malformed external pin fails closed: ' + JSON.stringify(bad))
  check(comboPinValid(POLICY_SHA) && !comboPinValid(123) && !comboPinValid(null) && !comboPinValid(undefined), 'pin shape: 64 lowercase hex only')
  // No explicit pin: the build-time define decides, and an empty define is still fail-closed.
  const defined = comboExpectedPin()
  check((await validateCombos(read) !== null) === (comboPinValid(defined) && defined === POLICY_SHA), 'without an explicit pin only a valid build-time pin can verify; an empty one fails closed')
  const wrongProvenancePin = structuredClone(read); wrongProvenancePin.provenance.policy_sha256 = 'b'.repeat(64)
  check(await validateCombos(wrongProvenancePin, { pin: POLICY_SHA }) === null, 'the provenance pin must equal the supplied pin')
  const neutral = structuredClone(read); neutral.calendar.meaning = 'other descriptive text'; neutral.provenance.record_only_comparison.matches = true; neutral.provenance.rights = 'other rights text'
  check(await validateCombos(structuredClone(read), { pin: POLICY_SHA }) !== null && await validateCombos(neutral, { pin: POLICY_SHA }) !== null, 'a clone and descriptive-text-only changes still validate, so each rejection below is caused by its own mutation')
  const [s0, s1, s2, s6] = [read.stocks[0].window, read.stocks[1].window, read.stocks[2].window, read.stocks[6].window]
  const seg = (sign: string, a: number, b: number, early: boolean) => ({ sign, start_index: a, end_index: b, start_date: COMBOS_WINDOW_DATES[a], end_date: COMBOS_WINDOW_DATES[b], length: b - a + 1, earlier_unknown: early })
  // Independent golden values, worked out by hand from the SELF/HEDGE tables above (not from the product functions).
  check(canonicalJson(s0.points.map((p) => [p.self.net_shares, p.self.net_lots, p.self.sign, p.hedge.net_shares, p.hedge.net_lots, p.hedge.sign, p.combination])) === canonicalJson([['5000', '5', 'positive', '-1250', '-1.25', 'negative', 'positive_negative'], ['-3750', '-3.75', 'negative', '2500', '2.5', 'positive', 'negative_positive'], ['0', '0', 'zero', '0', '0', 'zero', 'zero_zero'], ['2500', '2.5', 'positive', '-2500', '-2.5', 'negative', 'positive_negative'], ['-1250', '-1.25', 'negative', '1250', '1.25', 'positive', 'negative_positive']]), 'golden daily net / lots / sign / combination, stock 0')
  check(canonicalJson([s0.counts, s0.opposite, s0.combination_counts.positive_negative, s0.combination_counts.negative_positive, s0.combination_counts.zero_zero]) === canonicalJson([{ self: { positive: 2, negative: 2, zero: 1 }, hedge: { positive: 2, negative: 2, zero: 1 } }, { count: 4, dates: ['2026-09-30', '2026-10-01', '2026-10-05', '2026-10-06'] }, 2, 2, 1]), 'golden counts / opposite / combination counts, stock 0')
  check(canonicalJson(s0.segments.self) === canonicalJson([seg('positive', 0, 0, true), seg('negative', 1, 1, false), seg('zero', 2, 2, false), seg('positive', 3, 3, false), seg('negative', 4, 4, false)]) && canonicalJson(s0.latest) === canonicalJson({ self: seg('negative', 4, 4, false), hedge: seg('positive', 4, 4, false) }), 'golden segments and latest, stock 0')
  check(canonicalJson(s1.segments) === canonicalJson({ self: [seg('positive', 0, 1, true), seg('zero', 2, 2, false), seg('positive', 3, 4, false)], hedge: [seg('negative', 0, 3, true), seg('zero', 4, 4, false)] }), 'a true zero is its own run and breaks the positive run; first segment is earlier_unknown only')
  check(canonicalJson([s1.combination_counts.positive_negative, s1.combination_counts.zero_negative, s1.combination_counts.positive_zero, s1.opposite]) === canonicalJson([3, 1, 1, { count: 3, dates: ['2026-09-30', '2026-10-01', '2026-10-05'] }]) && s1.latest.hedge.sign === 'zero' && s1.latest.self.length === 2, 'golden combinations for stock 1; latest zero interrupts the run')
  check(canonicalJson(s2.segments) === canonicalJson({ self: [seg('zero', 0, 1, true), seg('negative', 2, 4, false)], hedge: [seg('positive', 0, 2, true), seg('zero', 3, 3, false), seg('negative', 4, 4, false)] }) && canonicalJson(s2.opposite) === canonicalJson({ count: 1, dates: ['2026-10-02'] }) && s2.combination_counts.zero_positive === 2 && s2.combination_counts.negative_zero === 1, 'golden zero-first window and a single opposite day, stock 2')
  check(s6.counts.self.zero === 5 && s6.counts.hedge.zero === 5 && s6.combination_counts.zero_zero === 5 && s6.opposite.count === 0 && s6.segments.self.length === 1 && s6.points[0].hedge.net_shares === '0' && s6.points[0].rows.find((r) => r.name === 'Dealer_Hedging')!.buy_shares === '0', 'verified zero originals: all-zero window has one zero run and no opposite day')
  check(COMBOS_KEYS.length === 9 && read.stocks.every((s) => COMBOS_KEYS.reduce((n, k) => n + s.window.combination_counts[k], 0) === 5), 'nine combinations reconcile to the five-day window for every stock')
  check(canonicalJson(comboSegments(['zero', 'positive', 'zero', 'positive', 'positive'], COMBOS_WINDOW_DATES).map((s) => [s.sign, s.length, s.earlier_unknown])) === canonicalJson([['zero', 1, true], ['positive', 1, false], ['zero', 1, false], ['positive', 2, false]]), 'maximal segments, direct')
  check(read.stocks[3].window.points[0].rows[0].name === 'Dealer_Hedging' && read.stocks[3].window.points[0].rows[0].row_index < read.stocks[3].window.points[0].rows[1].row_index, 'original row order is kept (not sorted by name) and traced by response ordinal')
  for (const bad of ['-0', '+1', '01', '1.0', '', '-1', '9223372036854775808', ' 1']) check(comboInt(bad) === null, 'canonical gross ' + JSON.stringify(bad))
  check(comboInt('0') === 0n && comboInt('9223372036854775807') === 2n ** 63n - 1n && comboInt(5) === null && comboInt(null) === null, 'canonical gross accepts only exact unsigned int64 text')
  check(comboLots(-1n) === '-0.001' && comboLots(1200n) === '1.2' && comboLots(0n) === '0' && comboLots(-2500n) === '-2.5' && comboLots(123456789n) === '123456.789', 'exact lots')
  for (const n of [2n ** 63n, -(2n ** 63n) - 1n]) { let caught = false; try { comboBound(n) } catch { caught = true }; check(caught, 'signed int64 overflow rejected') }
  const controls = comboControls(new URLSearchParams('as_of=2026-10-06&investor=dealer&horizon=5'))
  check(comboPath(controls, '6510').endsWith('/6510?as_of=2026-10-06&investor=dealer&horizon=5') && comboPath(controls) === '/chips-stock-scope-7-dealer-direction-combos?as_of=2026-10-06&investor=dealer&horizon=5', 'RAW3 exact preserved')
  check(!validComboControls({ ...controls, horizon: '20' }) && !validComboControls({ ...controls, investor: 'trust' }) && !validComboControls({ ...controls, as_of: '' }) && !validComboControls({ ...controls, as_of: '2026-10-07' }) && validComboControls(controls), 'dealer / 5 / 2026-10-06 only')
  for (const query of ['as_of=2026-10-06&investor=dealer', 'as_of=2026-10-06&investor=dealer&horizon=5&x=1', 'as_of=2026-10-06&investor=dealer&horizon=5&horizon=5']) check(!validComboParams(new URLSearchParams(query)), 'missing/duplicate/unknown RAW query')
  // R5-1: the way back from a symbol carries the literal location.search, so a non-canonical RAW query returns with READ/FIRST in the same state.
  const keptAsIs = ['', '?', '?as_of=2026-10-06&investor=dealer&horizon=5', '?as_of=2026-10-06&investor=dealer', '?as_of=2026-10-06&investor=dealer&horizon=5&x=1', '?as_of=2026-10-06&investor=dealer&horizon=5&horizon=5',
    '?as_of=2026-10-07&investor=dealer&horizon=5', '?as_of=2026-10-06&investor=foreign&horizon=20', '?horizon=5&investor=dealer&as_of=2026-10-06', '?as_of=2026%2D10%2D06&investor=dealer&horizon=5',
    '?as_of=&investor=&horizon=', '?x=%zz&y=%E4%B8%AD&z=a+b&z=', '?investor=dealer', '?horizon=5&horizon=5&horizon=5']
  for (const search of keptAsIs) check(comboReturnPath(search) === COMBOS_ROUTE + search, 'return link keeps the literal query ' + JSON.stringify(search))
  for (const search of ['', '?', '?as_of=2026-10-06&investor=dealer', '?as_of=2026-10-06&investor=dealer&horizon=5&x=1', '?as_of=2026-10-06&investor=dealer&horizon=5&horizon=5', '?horizon=5&investor=dealer&as_of=2026-10-06',
    '?as_of=2026%2D10%2D06&investor=dealer&horizon=5', '?x=%zz&y=%E4%B8%AD&z=a+b&z=', '?investor=dealer', '?horizon=5&horizon=5&horizon=5']) {
    check(comboPath(comboControls(new URLSearchParams(search.slice(1)))) !== comboReturnPath(search), 'the former normalised return changed ' + JSON.stringify(search))
  }
  check(comboReturnPath('?as_of=2026-10-06&investor=dealer&horizon=5') === comboPath(comboControls(new URLSearchParams('as_of=2026-10-06&investor=dealer&horizon=5'))), 'a canonical triple returns the same address as before')
  check(comboURL('3105') === 'https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=3105&start_date=2026-09-29&end_date=2026-10-06', 'exact policy URL')
  await rejected((v) => { v.schema = 'old' }, 'schema'); await rejected((v) => { v.calculation_version = 'old' }, 'calculation version')
  await rejected((v) => { v.consumer_version = 'old' }, 'consumer version'); await rejected((v) => { v.namespace = 'issue9-dealer-direction-combos-finmind-v1/qa2' }, 'namespace')
  await rejected((v) => { v.generation = '' }, 'generation required'); await rejected((v) => { v.count = 6 }, 'count 7')
  await rejected((v) => { v.available = false }, 'available required'); await rejected((v) => { v.state = 'pending' }, 'state available required')
  await rejected((v) => { v.reason = 'x' }, 'no reason on available'); await rejected((v) => { v.window_dates.reverse() }, 'window dates')
  await rejected((v) => { v.as_of = '2026-10-05' }, 'as_of'); await rejected((v) => { v.stocks.pop() }, 'missing seventh stock')
  await rejected((v) => { v.stocks.reverse() }, 'stock order'); await rejected((v) => { v.stocks[0].name = '穩懋X' }, 'identity name')
  await rejected((v) => { v.stocks[0].window.points[0].date = '2026-09-29' }, 'point date'); await rejected((v) => { v.stocks[0].window.points.pop() }, 'five points')
  await rejected((v) => { v.stocks[0].window.points[0].rows.pop() }, 'missing name row'); await rejected((v) => { v.stocks[0].window.points[0].rows[0].name = 'Dealer' }, 'Dealer name not admitted')
  await rejected((v) => { v.stocks[0].window.points[0].rows[1].name = v.stocks[0].window.points[0].rows[0].name }, 'duplicate name row')
  await rejected((v) => { v.stocks[0].window.points[0].rows[0].name = 'Other' }, 'other name'); await rejected((v) => { v.stocks[0].window.points[0].rows[0].stock_id = '3293' }, 'stock_id')
  await rejected((v) => { v.stocks[0].window.points[0].rows[0].date = '2026-10-01' }, 'row date'); await rejected((v) => { v.stocks[0].window.points[0].rows[0].key_order = ['date', 'buy', 'name', 'sell'] }, 'key order')
  await rejected((v) => { v.stocks[0].window.points[1].rows[0].row_index = v.stocks[0].window.points[0].rows[0].row_index }, 'duplicate original ordinal')
  await rejected((v) => { const [a, b] = v.stocks[0].window.points[0].rows; v.stocks[0].window.points[0].rows[0] = b; v.stocks[0].window.points[0].rows[1] = a }, 'row order must follow original ordinals')
  await rejected((v) => { v.stocks[0].window.points[0].rows[3].buy_shares = '0' + v.stocks[0].window.points[0].rows[3].buy_shares }, 'leading zero')
  await rejected((v) => { v.stocks[0].window.points[0].rows[3].buy_shares = 1 as unknown as string }, 'JSON number rejected')
  await rejected((v) => { v.stocks[0].window.points[0].rows[3].sell_shares = '9223372036854775808' }, 'gross over int64')
  await rejected((v) => { v.stocks[0].window.points[0].rows[3].sell_shares = '-1' }, 'negative gross')
  await rejected((v) => { v.stocks[0].window.points[0].self.net_shares = '5001' }, 'self net'); await rejected((v) => { v.stocks[0].window.points[0].self.net_lots = '5.1' }, 'lots')
  await rejected((v) => { v.stocks[0].window.points[0].hedge.sign = 'positive' }, 'hedge sign'); await rejected((v) => { v.stocks[0].window.points[0].combination = 'positive_positive' }, 'combination')
  await rejected((v) => { v.stocks[0].window.points[0].opposite = false }, 'opposite flag'); await rejected((v) => { v.stocks[0].window.points[0].self.row_index = 0 }, 'amount row ordinal')
  await rejected((v) => { v.stocks[0].window.counts.self.positive = 3 }, 'counts'); await rejected((v) => { v.stocks[1].window.segments.self[1].sign = 'negative' }, 'segments')
  await rejected((v) => { v.stocks[0].window.segments.self[0].earlier_unknown = false }, 'first segment must be earlier_unknown')
  await rejected((v) => { v.stocks[0].window.segments.self[1].earlier_unknown = true }, 'only the first segment is earlier_unknown')
  await rejected((v) => { v.stocks[1].window.latest.hedge = { ...v.stocks[1].window.latest.hedge, sign: 'negative' } }, 'latest')
  await rejected((v) => { v.stocks[0].window.combination_counts.zero_zero = 2 }, 'combination counts')
  await rejected((v) => { v.stocks[0].window.combination_dates.zero_zero = ['2026-10-01'] }, 'combination dates')
  await rejected((v) => { v.stocks[0].window.opposite.count = 3 }, 'opposite count'); await rejected((v) => { v.stocks[0].window.opposite.dates.pop() }, 'opposite dates')
  await rejected((v) => { (v.stocks[0].window as unknown as Record<string, unknown>).extra = 1 }, 'unaudited extra key')
  await rejected((v) => { v.receipts.pop() }, 'seven receipts'); await rejected((v) => { v.receipts[2].canonical = '{}' }, 'canonical receipt')
  await rejected((v) => { v.receipts[2].sha256 = v.receipts[3].sha256 }, 'receipt sha uniqueness / digest')
  await rejected((v) => { v.receipts[2].url = v.receipts[3].url }, 'receipt URL'); await rejected((v) => { v.receipts[2].body_sha256 = 'f'.repeat(64) }, 'receipt body sha')
  await rejected((v) => { v.stocks[0].window.points[0].receipt_sha256 = v.receipts[1].sha256 }, 'point receipt sha')
  await rejected((v) => { v.stocks[0].window.points[0].body_sha256 = v.receipts[1].body_sha256 }, 'point body sha')
  await rejected((v) => { v.stocks[0].window.points[0].url = v.receipts[1].url }, 'point URL')
  await rejected((v) => { v.stocks[0].window.points[0].request_index = 1 }, 'point request index')
  await rejected(async (v) => { const r = JSON.parse(v.receipts[2].canonical); r.url = v.receipts[3].url; v.receipts[2].canonical = canonicalJson(r); v.receipts[2].sha256 = await comboSHA(v.receipts[2].canonical) }, 'resealed receipt URL must still match its request')
  await rejected(async (v) => { const r = JSON.parse(v.receipts[2].canonical); r.extra = 'not-original'; v.receipts[2].canonical = canonicalJson(r); v.receipts[2].sha256 = await comboSHA(v.receipts[2].canonical) }, 'unaugmented receipt')
  await rejected(async (v) => { const r = JSON.parse(v.receipts[2].canonical); r.status = 302; v.receipts[2].canonical = canonicalJson(r); v.receipts[2].sha256 = await comboSHA(v.receipts[2].canonical) }, 'receipt status')
  await rejected(async (v) => { const r = JSON.parse(v.receipts[2].canonical); r.observed_utc = '2026-10-12T11:59:59.000000+00:00'; v.receipts[2].canonical = canonicalJson(r); v.receipts[2].sha256 = await comboSHA(v.receipts[2].canonical) }, 'receipt time order')
  await rejected(async (v) => { const r = JSON.parse(v.receipts[2].canonical); r.policy_sha256 = 'e'.repeat(64); v.receipts[2].canonical = canonicalJson(r); v.receipts[2].sha256 = await comboSHA(v.receipts[2].canonical) }, 'receipt policy sha must equal the provenance policy sha')
  await rejected((v) => { v.provenance.policy_sha256 = 'short' }, 'provenance policy sha'); await rejected((v) => { v.provenance.rights = '' }, 'rights')
  await rejected((v) => { v.provenance.value_label = '' }, 'value label'); await rejected((v) => { v.provenance.anchors_checked = 55 }, 'anchors checked')
  await rejected((v) => { v.provenance.publication_time = '2026-10-06' }, 'publication unknown'); await rejected((v) => { v.calendar.calendar_gets = 1 }, 'calendar GET 0')
  await rejected((v) => { v.calendar.closed_dates = [] }, 'calendar closed dates')
  // R1-4: only end >= start inside a receipt is checked; the seven are ordered by request_index, not by wall clock.
  const steppedBack = structuredClone(read)
  for (const ordinal of [3, 4, 5, 6]) {
    const r = JSON.parse(steppedBack.receipts[ordinal].canonical)
    r.request_started_utc = '2026-10-12T11:' + String(10 + ordinal).padStart(2, '0') + ':00.000000+00:00'; r.observed_utc = '2026-10-12T11:' + String(10 + ordinal).padStart(2, '0') + ':01.000000+00:00'
    steppedBack.receipts[ordinal].canonical = canonicalJson(r); steppedBack.receipts[ordinal].sha256 = await comboSHA(steppedBack.receipts[ordinal].canonical)
    for (const p of steppedBack.stocks[ordinal].window.points) p.receipt_sha256 = steppedBack.receipts[ordinal].sha256
  }
  check(await validateCombos(steppedBack, { pin: POLICY_SHA }) !== null, 'a clock stepped back between receipts does not hide a valid, already spent batch')
  await rejected(async (v) => { const r = JSON.parse(v.receipts[4].canonical); r.observed_utc = '2026-10-12T11:59:59.000000+00:00'; v.receipts[4].canonical = canonicalJson(r); v.receipts[4].sha256 = await comboSHA(v.receipts[4].canonical); for (const p of v.stocks[4].window.points) p.receipt_sha256 = v.receipts[4].sha256 }, 'end before start inside one receipt')
  await rejected(async (v) => { [v.receipts[3], v.receipts[4]] = [v.receipts[4], v.receipts[3]] }, 'receipt order is the backend request_index')
  // R1-1 (client side): every request declares JSON; the POST body is exactly {}.
  const getInit = comboRequestInit(false), postInit = comboRequestInit(true)
  check(getInit.method === 'GET' && postInit.method === 'POST' && postInit.body === '{}' && getInit.body === undefined && getInit.headers['Content-Type'] === 'application/json' && postInit.headers['Content-Type'] === 'application/json' && Object.keys(postInit.headers).length === 1, 'FIRST and READ requests both declare application/json; FIRST posts {}')
  // FIRST / READ / mask semantics.
  const open = { trusted: true, pending: false, valid: true, capture: true, firstLatched: false }
  check(comboActionAllowed(open) && !comboActionAllowed({ ...open, trusted: false }) && !comboActionAllowed({ ...open, pending: true }) && !comboActionAllowed({ ...open, valid: false }) && !comboActionAllowed({ ...open, firstLatched: true }) && comboActionAllowed({ ...open, capture: false, firstLatched: true }), 'trusted, unique, non-concurrent, valid controls; READ may repeat after FIRST')
  for (const missing of ['', 'not-a-pin']) {
    const refused = await resolveComboResponse({ capture: false, status: 200, ok: true, body: read, heldGeneration: null, pin: missing })
    check(refused.read === null && refused.phase === 'error' && refused.text.includes('policy pin'), 'READ without a valid external pin shows nothing')
  }
  const resolved = await resolveComboResponse({ capture: false, status: 200, ok: true, body: read, heldGeneration: null, pin: POLICY_SHA })
  check(resolved.read !== null && resolved.phase === 'available' && resolved.generation === 'synthetic-generation-1' && resolved.lockFirst, 'verified READ is available and locks FIRST')
  const sameGeneration = await resolveComboResponse({ capture: false, status: 200, ok: true, body: read, heldGeneration: 'synthetic-generation-1', pin: POLICY_SHA })
  const otherGeneration = await resolveComboResponse({ capture: false, status: 200, ok: true, body: read, heldGeneration: 'another', pin: POLICY_SHA })
  check(sameGeneration.read !== null && otherGeneration.read === null && otherGeneration.phase === 'error', 'a held READ restores only the same generation')
  const tampered = structuredClone(read); tampered.stocks[0].window.counts.self.positive = 3
  const bad = await resolveComboResponse({ capture: false, status: 200, ok: true, body: tampered, heldGeneration: null, pin: POLICY_SHA })
  check(bad.read === null && bad.phase === 'error', 'a READ that fails verification clears everything')
  const blank = (state: string, reason: string, extra: Record<string, unknown> = {}) => ({ available: false, state, reason, generation: 'synthetic-generation-1', failure: null, stocks: [], ...extra })
  const pendingFirst = await resolveComboResponse({ capture: true, status: 200, ok: true, body: blank('pending', 'pending_independent_admission'), heldGeneration: null, pin: POLICY_SHA })
  check(pendingFirst.read === null && pendingFirst.phase === 'pending' && pendingFirst.lockFirst && pendingFirst.generation === 'synthetic-generation-1' && pendingFirst.text.includes('pending_independent_admission'), 'FIRST returns pending: no values, FIRST locked, generation remembered')
  const pendingRead = await resolveComboResponse({ capture: false, status: 409, ok: false, body: blank('pending', 'pending_independent_admission'), heldGeneration: 'synthetic-generation-1', pin: POLICY_SHA })
  check(pendingRead.read === null && pendingRead.phase === 'pending' && !pendingRead.lockFirst, 'READ before admission is pending and shows nothing')
  const failed = await resolveComboResponse({ capture: true, status: 502, ok: false, body: blank('failed', 'failed', { failure: { primary_code: 'http_status', primary_stage: 'batch' } }), heldGeneration: null, pin: POLICY_SHA })
  check(failed.read === null && failed.phase === 'failed' && failed.text.includes('http_status') && failed.lockFirst, 'a failed FIRST names the first failure code and stays spent')
  const hostile = await resolveComboResponse({ capture: false, status: 409, ok: false, body: blank('failed', 'failed', { failure: { primary_code: '<img src=x>' } }), heldGeneration: null, pin: POLICY_SHA })
  check(hostile.phase === 'failed' && !hostile.text.includes('<'), 'unexpected failure text is never echoed')
  for (const [state, phase] of [['new', 'unacquired'], ['expired', 'expired'], ['released', 'released'], ['acquiring', 'acquiring']] as const) {
    const outcome = await resolveComboResponse({ capture: false, status: 409, ok: false, body: blank(state, state === 'new' ? 'not_acquired' : state), heldGeneration: null, pin: POLICY_SHA })
    check(outcome.read === null && outcome.phase === phase, 'state ' + state + ' shows no values')
  }
  const conflict = await resolveComboResponse({ capture: false, status: 409, ok: false, body: blank('available', 'calculation_conflict'), heldGeneration: null, pin: POLICY_SHA })
  const again = await resolveComboResponse({ capture: true, status: 409, ok: false, body: blank('pending', 'already_attempted'), heldGeneration: null, pin: POLICY_SHA })
  const html = await resolveComboResponse({ capture: false, status: 502, ok: false, body: null, heldGeneration: null, pin: POLICY_SHA })
  const foreignGeneration = await resolveComboResponse({ capture: false, status: 409, ok: false, body: blank('released', 'released', { generation: 'someone-else' }), heldGeneration: 'synthetic-generation-1', pin: POLICY_SHA })
  check(conflict.phase === 'error' && again.read === null && html.phase === 'error' && html.read === null && foreignGeneration.phase === 'error', 'conflict / repeated FIRST / non-JSON / other generation never show values')
  // Lifecycle: pagehide / pageshow persisted / popstate mask synchronously and never fetch by themselves.
  const target = new EventTarget()
  let held: ComboRead | null = read, selected: number | null = 1, masks = 0, automaticFetch = 0
  const detach = installComboPageLifecycle(target, () => { held = null; selected = null; masks++ })
  const dispatch = (name: string, persisted: boolean) => { const event = new Event(name); Object.defineProperty(event, 'persisted', { value: persisted }); target.dispatchEvent(event) }
  const oldFetch = globalThis.fetch
  globalThis.fetch = () => { automaticFetch++; throw new Error('lifecycle automatic fetch') }
  try {
    dispatch('pageshow', false); check(masks === 0 && held === read && selected === 1, 'initial pageshow takes no action')
    dispatch('pagehide', false); check(Number(masks) === 1 && held === null && selected === null, 'pagehide sync clears graph and selection')
    held = read; selected = 2; dispatch('pageshow', true); check(Number(masks) === 2 && held === null && selected === null, 'persisted pageshow masks all')
    held = read; selected = 3; dispatch('popstate', false); check(Number(masks) === 3 && held === null && selected === null, 'native browser history return masks all')
    detach(); held = read; selected = 4; dispatch('pagehide', true); dispatch('popstate', false)
    check(Number(masks) === 3 && held === read && selected === 4, 'unmounted lifecycle detaches handlers')
    check(automaticFetch === 0, 'masking never automatically READs or captures')
    check(!isComboTrustedAction(new Event('click')) && !isComboTrustedAction({ isTrusted: true } as Event), 'synthetic FIRST/READ cannot pass the trusted native Event guard')
  } finally { detach(); globalThis.fetch = oldFetch }
  check(COMBOS_ROW_NAMES.length === 5 && !COMBOS_ROW_NAMES.includes('Dealer'), 'five admitted names, never the merged Dealer')
  return checks
}
