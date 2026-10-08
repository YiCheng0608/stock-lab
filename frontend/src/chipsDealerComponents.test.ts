import { canonicalJson, grossInteger, grossLots } from './chipsGross'
import { DEALER_COMPONENTS, DEALER_COMPONENTS_CALCULATION, DEALER_COMPONENTS_CALENDAR_SCHEMA, DEALER_COMPONENTS_CALENDAR_VERSION, DEALER_COMPONENTS_CAPTURE_SCHEMA, DEALER_COMPONENTS_PIN, DEALER_COMPONENTS_PROFILE, DEALER_COMPONENTS_SCHEMA, DEALER_COMPONENTS_SYMBOLS, DEALER_COMPONENTS_VERSION, DEALER_COMPONENTS_WORKER_SCHEMA, dealerAmounts, dealerBound, dealerControls, dealerDailyURL, dealerDates, dealerPath, dealerSHA, validDealerControls, validDealerParams, validateDealerComponents } from './chipsDealerComponents'
import type { DealerComponent, DealerPoint, DealerPolicy, DealerRead, DealerTrace } from './chipsDealerComponents'
import { installDealerPageLifecycle, isDealerTrustedAction } from './ChipsDealerComponentsPage'
type Assert = (ok: unknown, label: string) => void

/** Minimal synthetic CSVs, rebuilt in RAM; never official evidence. */
export async function createDealerFixture(policy: DealerPolicy): Promise<{ read: DealerRead; sourceInputBytes: number }> {
  const adopted = dealerDates(policy), daily = adopted.slice(-5), original = [...adopted, '2026-10-07', '2026-10-08']
  const receipts: DealerRead['receipts'] = [], calendarRows: DealerTrace[] = [], byDay = new Map<string, Map<string, DealerPoint>>()
  let sourceInputBytes = 0
  for (let ordinal = 0; ordinal < 7; ordinal++) {
    const source = ordinal < 2 ? 'index' : 'daily', requested = ordinal < 2 ? policy.sources.index.requests[ordinal] : daily[ordinal - 2]
    const rows: string[][] = ordinal < 2 ? original.filter((d) => d.startsWith(requested.slice(0, 7))).map((d) => [d.replace(/-/g, ''), '100', '102', '99', '101', '1']) : DEALER_COMPONENTS_SYMBOLS.map((symbol, i) => {
      const ownNet = [4, -3, 0, 2, -1][ordinal - 2], hedgeNet = [-1, 2, 0, -2, 1][ordinal - 2]
      const triple = (n: number, base: number) => [base + Math.max(n, 0), base + Math.max(-n, 0), n]
      const own = triple(ownNet, 10 + i), hedge = triple(hedgeNet, 6 + i), total = own.map((n, j) => n + hedge[j])
      return [String(Number(requested.slice(0, 4)) - 1911) + requested.slice(5, 7) + requested.slice(8), symbol, policy.scope.identities[symbol], ...[[7, 3, 4], [1, 2, -1], [8, 5, 3], [4, 4, 0], own, hedge, total].flat().map(String), String(4 + total[2])]
    })
    const header = policy.sources[source].header, body = [header, ...rows].map((row) => row.join(',')).join('\n') + '\n'
    const bodySHA = await dealerSHA(body), bytes = new TextEncoder().encode(body).length
    sourceInputBytes += bytes
    const url = ordinal < 2 ? policy.sources.index.base_url + '&date=' + encodeURIComponent(requested.replace(/-/g, '/')) : dealerDailyURL(policy, requested)
    const time = (second: number) => '2026-10-08T12:00:' + String(second).padStart(2, '0') + '.000000+00:00'
    const receipt = { schema: DEALER_COMPONENTS_CAPTURE_SCHEMA, ordinal, source, source_version: policy.sources[source].source_version, requested_date: requested, url, method: 'GET', request_body_bytes: 0, http_status: 200, content_type: 'application/csv;charset=utf-8', content_encoding: 'identity', body_bytes: bytes, body_sha256: bodySHA, request_started_at: time(ordinal * 2), captured_at: time(ordinal * 2 + 1), policy_version: DEALER_COMPONENTS_VERSION, policy_digest: DEALER_COMPONENTS_PIN, profile: DEALER_COMPONENTS_PROFILE, publication_time: 'unknown', first_available_time: 'unknown', revision_time: 'unknown', historical_pit: 'unsupported', request_count: 1 }
    const canonical = canonicalJson(receipt), sha256 = await dealerSHA(canonical)
    receipts.push({ original: receipt, canonical, sha256 })
    if (ordinal < 2) {
      for (const [index, row] of rows.entries()) calendarRows.push({ date: row[0].slice(0, 4) + '-' + row[0].slice(4, 6) + '-' + row[0].slice(6), row_ordinal: index + 1, source_values: row, receipt_sha256: sha256, body_sha256: bodySHA })
    } else {
      const map = new Map<string, DealerPoint>()
      for (const [index, row] of rows.entries()) {
        const components = Object.fromEntries(DEALER_COMPONENTS.map((c, i) => [c, dealerAmounts(row.slice(15 + i * 3, 18 + i * 3).map(BigInt))])) as DealerPoint['components']
        map.set(row[1], { date: requested, row_ordinal: index + 1, source_values: row, receipt_sha256: sha256, body_sha256: bodySHA, components, component_check: true })
      }
      byDay.set(requested, map)
    }
  }
  const stocks = DEALER_COMPONENTS_SYMBOLS.map((symbol) => {
    const points = daily.map((day) => byDay.get(day)!.get(symbol)!)
    const totals = Object.fromEntries(DEALER_COMPONENTS.map((name) => {
      const sums = [0n, 0n, 0n]
      for (const p of points) for (const [i, metric] of ['buy', 'sell', 'net'].entries()) sums[i] += BigInt(p.components[name][metric + '_shares' as 'buy_shares'])
      return [name, dealerAmounts(sums)]
    })) as Record<DealerComponent, ReturnType<typeof dealerAmounts>>
    return { symbol, name: policy.scope.identities[symbol], exchange: 'TPEx', security_type: 'stock', currency: 'TWD', window: { horizon: 5, points, totals, component_check: true } }
  })
  return { sourceInputBytes, read: { schema: DEALER_COMPONENTS_SCHEMA, worker_schema: DEALER_COMPONENTS_WORKER_SCHEMA, capture_schema: DEALER_COMPONENTS_CAPTURE_SCHEMA, calendar_schema: DEALER_COMPONENTS_CALENDAR_SCHEMA, calendar_version: DEALER_COMPONENTS_CALENDAR_VERSION, calculation_version: DEALER_COMPONENTS_CALCULATION, profile: DEALER_COMPONENTS_PROFILE, policy_version: DEALER_COMPONENTS_VERSION, policy_digest: DEALER_COMPONENTS_PIN, policy, as_of: '2026-10-06', generation: 'synthetic-dealer-components-only', available: true, count: 7, reason: null, stocks, receipts, calendar: { schema: DEALER_COMPONENTS_CALENDAR_SCHEMA, version: DEALER_COMPONENTS_CALENDAR_VERSION, original_dates: original, adopted_dates: adopted, daily_dates: daily, rows: calendarRows, post_cutoff_excluded: ['2026-10-07', '2026-10-08'] } } }
}
async function reseal(v: DealerRead, ordinal: number) { const r = v.receipts[ordinal]; r.canonical = canonicalJson(r.original); r.sha256 = await dealerSHA(r.canonical) }
export async function runDealerChecks(read: DealerRead, assert: Assert): Promise<number> {
  let checks = 0
  const check = (ok: unknown, label: string) => { assert(ok, label); checks++ }
  async function rejected(change: (copy: DealerRead) => void | Promise<void>, label: string) { const copy = structuredClone(read); await change(copy); check(await validateDealerComponents(copy) === null, label) }
  check(await validateDealerComponents(read) !== null, 'ALL35 / all875 strings / all770 int64 / three daily and window components')
  const t = read.stocks[0].window.totals
  check(canonicalJson([t.self.buy_shares, t.self.sell_shares, t.self.net_shares, t.hedge.buy_shares, t.hedge.sell_shares, t.hedge.net_shares, t.total.buy_shares, t.total.sell_shares, t.total.net_shares]) === canonicalJson(['56', '54', '2', '33', '33', '0', '89', '87', '2']), 'independent golden buy/sell/net totals; hedge net0 does not mean buy/sell0')
  check(t.hedge.verified_net_zero && !t.hedge.verified_buy_zero && read.stocks[0].window.points[2].components.self.verified_net_zero, 'daily and window zero predicates are distinct')
  for (const bad of ['-0', '+1', '01', '1.0', '9223372036854775808']) check(grossInteger(bad) === null, 'canonical int64 ' + bad)
  check(grossLots('-1') === '-0.001' && grossLots('1200') === '1.2', 'exact lots')
  for (const n of [2n ** 63n, -(2n ** 63n) - 1n]) { let caught = false; try { dealerBound(n) } catch { caught = true }; check(caught, 'signed step overflow') }
  let total = 0n, caught = false
  try { for (const n of [2n ** 63n - 1n, 1n, -(2n ** 63n - 1n)]) total = dealerBound(total + n) } catch { caught = true }
  check(caught, 'partial sum overflow even when final in range')
  const controls = dealerControls(new URLSearchParams('as_of=2026-10-06&investor=dealer&horizon=5'))
  check(dealerPath(controls, '6510').endsWith('/6510?as_of=2026-10-06&investor=dealer&horizon=5'), 'RAW3 exact preserved')
  check(!validDealerControls({ ...controls, horizon: '20' }) && !validDealerControls({ ...controls, investor: 'trust' }) && !validDealerControls({ ...controls, as_of: '' }), 'dealer5 only')
  for (const query of ['as_of=2026-10-06&investor=dealer', 'as_of=2026-10-06&investor=dealer&horizon=5&x=1', 'as_of=2026-10-06&investor=dealer&horizon=5&horizon=5']) check(!validDealerParams(new URLSearchParams(query)), 'missing/duplicate/unknown RAW query')
  await rejected((v) => { v.policy.calendar.from = '2026-09-02' }, 'independent canonical policy')
  await rejected((v) => { v.policy_digest = 'old' }, 'old pin')
  await rejected((v) => { v.worker_schema = 'old' }, 'worker schema')
  await rejected((v) => { v.capture_schema = 'old' }, 'capture schema')
  await rejected((v) => { v.calendar.version = 'old' }, 'calendar schema/version')
  await rejected((v) => { v.stocks.pop() }, 'missing seventh stock')
  await rejected((v) => { v.receipts[2].canonical = '{}' }, 'original receipt digest')
  await rejected(async (v) => { v.receipts[2].original.source_version = 'old'; await reseal(v, 2) }, 'resealed source version')
  await rejected(async (v) => { v.receipts[2].original.url = v.receipts[3].original.url; await reseal(v, 2) }, 'dynamic exact daily URL')
  await rejected(async (v) => { v.receipts[2].original.captured_at = '2026-10-07T12:00:00+00:00'; await reseal(v, 2) }, 'old observation')
  await rejected(async (v) => { v.receipts[2].original.captured_at = '2026-10-08T24:00:00+00:00'; await reseal(v, 2) }, 'UTC24 rollover')
  await rejected(async (v) => { v.receipts[2].original.extra = 'not-original'; await reseal(v, 2) }, 'unaugmented receipt')
  await rejected((v) => { v.calendar.rows.at(-1)!.source_values[2] = '1' }, 'ALL postcutoff OHLC')
  await rejected((v) => { v.calendar.rows.splice(3, 1); v.calendar.original_dates.splice(3, 1) }, 'full weekday calendar missing')
  await rejected((v) => { v.calendar.rows.push(v.calendar.rows[0]); v.calendar.original_dates.push(v.calendar.original_dates[0]) }, 'full calendar duplicate')
  await rejected((v) => { v.calendar.daily_dates.reverse() }, 'last5 strict order')
  await rejected((v) => { v.stocks[6].window.points[0].source_values[23] = '9223372036854775808' }, 'seventh stock original overflow')
  await rejected((v) => { v.stocks[0].window.points[0].source_values[3] = '-1' }, 'ALL22 nondealer gross validated')
  await rejected((v) => { v.stocks[0].window.points[0].source_values[21] = '2' }, 'daily self plus hedge equals total')
  await rejected((v) => { v.stocks[0].window.points[0].components.self.buy_shares = 1 as unknown as string }, 'JSON number rejected')
  await rejected((v) => { v.stocks[0].window.points[0].components.self.net_lots = '0' }, 'lots exact')
  await rejected((v) => { v.stocks[0].window.points[0].components.self.verified_net_zero = true }, 'daily zero must match originals')
  await rejected((v) => { v.stocks[1].window.points[0].row_ordinal = v.stocks[0].window.points[0].row_ordinal }, 'duplicate original ordinal')
  await rejected((v) => { v.stocks[0].window.points[0].component_check = false }, 'daily component check')
  await rejected((v) => { v.stocks[0].window.totals.self.buy_shares = '0' }, 'five-row gross total')
  await rejected((v) => { v.stocks[0].window.totals.hedge.verified_net_zero = false }, 'window zero predicate')
  await rejected((v) => { v.stocks[0].window.component_check = false }, 'window component check')
  await rejected((v) => { v.available = false; v.count = null }, 'unavailable never zero')
  const target = new EventTarget()
  let held: DealerRead | null = read, selected: number | null = 1, masks = 0, automaticFetch = 0
  const detach = installDealerPageLifecycle(target, () => { held = null; selected = null; masks++ })
  const dispatch = (name: string, persisted: boolean) => { const event = new Event(name); Object.defineProperty(event, 'persisted', { value: persisted }); target.dispatchEvent(event) }
  const oldFetch = globalThis.fetch
  globalThis.fetch = () => { automaticFetch++; throw new Error('lifecycle automatic fetch') }
  try {
    dispatch('pageshow', false); check(masks === 0 && held === read && selected === 1, 'initial pageshow no action')
    dispatch('pagehide', false); check(Number(masks) === 1 && held === null && selected === null, 'pagehide sync clears graph and selection')
    held = read; selected = 2; dispatch('pageshow', true); check(Number(masks) === 2 && held === null && selected === null, 'persisted pageshow masks all')
    held = read; selected = 3; dispatch('popstate', false); check(Number(masks) === 3 && held === null && selected === null, 'native browser history return masks all')
    detach(); held = read; selected = 4; dispatch('pagehide', true); dispatch('popstate', false)
    check(Number(masks) === 3 && held === read && selected === 4, 'unmounted lifecycle detaches handlers')
    check(automaticFetch === 0, 'masking never automatically READs or captures')
    check(!isDealerTrustedAction(new Event('click')) && !isDealerTrustedAction({ isTrusted: true } as Event), 'synthetic FIRST/READ cannot pass trusted native Event guard')
  } finally { detach(); globalThis.fetch = oldFetch }
  return checks
}
