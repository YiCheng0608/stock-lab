import { canonicalJson, grossInteger, grossLots } from './chipsGross'
import { ADJACENT_CALCULATION, ADJACENT_CALENDAR_SCHEMA, ADJACENT_CALENDAR_VERSION, ADJACENT_CAPTURE_SCHEMA, ADJACENT_INVESTORS, ADJACENT_NAMES, ADJACENT_PIN, ADJACENT_PROFILE, ADJACENT_SCHEMA, ADJACENT_SIGNS, ADJACENT_SYMBOLS, ADJACENT_VERSION, ADJACENT_WINDOWS, ADJACENT_WORKER_SCHEMA, adjacentBound, adjacentControls, adjacentDailyURL, adjacentPath, adjacentStats, validAdjacentControls, validAdjacentParams, validateAdjacent } from './chipsAdjacent'
import type { AdjacentPoint, AdjacentPolicy, AdjacentRead, AdjacentSegment, AdjacentSign, AdjacentStats, AdjacentStock, AdjacentWindow } from './chipsAdjacent'
import { installAdjacentPageLifecycle } from './ChipsAdjacentPage'

type Assert = (value: unknown, message: string) => void
const csv = (header: string[], rows: string[][]) => [header, ...rows].map((row) => row.map((s) => '"' + s.replace(/"/g, '""') + '"').join(',')).join('\n') + '\n'
async function hash(text: string): Promise<string> { return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))), (n) => n.toString(16).padStart(2, '0')).join('') }
const patterns = [1, -2, 0, 3, 0, -3, 2, 1, 0, -1]
export async function createAdjacentFixture(policy: AdjacentPolicy): Promise<{ read: AdjacentRead; sourceInputBytes: number }> {
  const adopted: string[] = []
  let instant = new Date(policy.calendar.from + 'T00:00:00Z')
  while (instant.toISOString().slice(0, 10) <= policy.scope.cutoff) {
    const day = instant.toISOString().slice(0, 10)
    if (instant.getUTCDay() > 0 && instant.getUTCDay() < 6 && !policy.calendar.closed_dates.includes(day)) adopted.push(day)
    instant = new Date(instant.valueOf() + 86400000)
  }
  const originalDates = [...adopted, '2026-10-07', '2026-10-08'], dailyDates = adopted.slice(-10)
  const receipts: AdjacentRead['receipts'] = [], calendarRows: AdjacentRead['calendar']['rows'] = [], daily: AdjacentPoint[][] = []
  let sourceInputBytes = new TextEncoder().encode(canonicalJson(policy)).length
  for (let ordinal = 0; ordinal < 12; ordinal++) {
    const requested = ordinal < 2 ? policy.sources.index.requests[ordinal] : dailyDates[ordinal - 2]
    const rows = ordinal < 2 ? originalDates.filter((day) => day.slice(0, 7) === requested.slice(0, 7)).map((day) => [day.replace(/-/g, ''), '100', '102', '99', '101', '1']) : ADJACENT_SYMBOLS.map((symbol, j) => {
      const foreign = BigInt(patterns[(ordinal - 2 + j) % 10] * (j + 1) * 1001), trust = BigInt(patterns[(ordinal - 1 + j) % 10] * 7), dealer = BigInt(patterns[(ordinal + j) % 10] * 13)
      const triple = (n: bigint) => [String(n > 0n ? n : 0n), String(n < 0n ? -n : 0n), String(n)]
      return [String(Number(requested.slice(0, 4)) - 1911) + requested.slice(5, 7) + requested.slice(8), symbol, ADJACENT_NAMES[symbol], ...[foreign, 0n, foreign, trust, dealer, 0n, dealer].flatMap(triple), String(foreign + trust + dealer)]
    })
    const body = csv(ordinal < 2 ? policy.sources.index.header : policy.sources.daily.header, rows), bodySHA = await hash(body), bodyBytes = new TextEncoder().encode(body).length
    sourceInputBytes += bodyBytes
    const stamp = '2026-10-08T00:00:' + String(ordinal).padStart(2, '0') + '+00:00'
    const url = ordinal < 2 ? policy.sources.index.base_url + '&date=' + encodeURIComponent(requested.replace(/-/g, '/')) : adjacentDailyURL(policy, requested)
    const original = { schema: ADJACENT_CAPTURE_SCHEMA, ordinal, source: ordinal < 2 ? 'index' : 'daily', source_version: ordinal < 2 ? policy.sources.index.source_version : policy.sources.daily.source_version, requested_date: requested, url, method: 'GET', request_body_bytes: 0, http_status: 200, content_type: 'application/csv;charset=utf-8', content_encoding: 'identity', body_bytes: bodyBytes, body_sha256: bodySHA, request_started_at: stamp, captured_at: stamp, policy_version: ADJACENT_VERSION, policy_digest: ADJACENT_PIN, profile: ADJACENT_PROFILE, publication_time: 'unknown', first_available_time: 'unknown', revision_time: 'unknown', historical_pit: 'unsupported', request_count: 1 }
    const canonical = canonicalJson(original), receiptSHA = await hash(canonical)
    receipts.push({ original, canonical, sha256: receiptSHA })
    const trace = (row: string[], index: number) => ({ date: ordinal < 2 ? row[0].slice(0, 4) + '-' + row[0].slice(4, 6) + '-' + row[0].slice(6) : requested, row_ordinal: index + 1, source_values: row, receipt_sha256: receiptSHA, body_sha256: bodySHA })
    if (ordinal < 2) calendarRows.push(...rows.map(trace))
    else daily.push(rows.map((row, j) => {
      const sign = (n: string): AdjacentSign => BigInt(n) > 0n ? 'positive' : BigInt(n) < 0n ? 'negative' : 'zero'
      return { ...trace(row, j), net_shares: { foreign: row[5], trust: row[14], dealer: row[23] }, net_lots: { foreign: grossLots(row[5]), trust: grossLots(row[14]), dealer: grossLots(row[23]) }, signs: { foreign: sign(row[5]), trust: sign(row[14]), dealer: sign(row[23]) } }
    }))
  }
  const stats = (points: AdjacentPoint[], investor: typeof ADJACENT_INVESTORS[number]): AdjacentStats => {
    const counts = { positive: 0, negative: 0, zero: 0 }, segments: AdjacentSegment[] = []
    let begin = 0
    while (begin < 5) {
      const sign = points[begin].signs[investor]
      let end = begin
      while (end + 1 < 5 && points[end + 1].signs[investor] === sign) end++
      counts[sign] += end - begin + 1
      segments.push({ sign, start_index: begin, end_index: end, start_date: points[begin].date, end_date: points[end].date, length: end - begin + 1, earlier_unknown: begin === 0 })
      begin = end + 1
    }
    const total = points.reduce((n, p) => n + BigInt(p.net_shares[investor]), 0n)
    return { counts, total_shares: String(total), total_lots: grossLots(String(total)), verified_zero: total === 0n, segments, latest_run: { ...segments.at(-1)! } }
  }
  const stocks: AdjacentStock[] = ADJACENT_SYMBOLS.map((symbol, j) => {
    const points = daily.map((rows) => rows[j]), windows = {} as AdjacentStock['windows']
    for (const [name, selected] of [['previous', points.slice(0, 5)], ['recent', points.slice(5)]] as const) {
      const investors = Object.fromEntries(ADJACENT_INVESTORS.map((investor) => [investor, stats(selected, investor)])) as AdjacentWindow['investors']
      windows[name] = { horizon: 5, points: selected, investors }
    }
    const pairs = windows.previous.points.map((old, index) => {
      const recent = windows.recent.points[index], deltas = Object.fromEntries(ADJACENT_INVESTORS.map((i) => [i, String(BigInt(recent.net_shares[i]) - BigInt(old.net_shares[i]))])) as AdjacentPoint['net_shares']
      return { position: index + 1, previous_date: old.date, recent_date: recent.date, previous_row_ordinal: old.row_ordinal, recent_row_ordinal: recent.row_ordinal, net_delta_shares: deltas, net_delta_lots: Object.fromEntries(ADJACENT_INVESTORS.map((i) => [i, grossLots(deltas[i])])) as AdjacentPoint['net_lots'] }
    })
    const comparisons = Object.fromEntries(ADJACENT_INVESTORS.map((i) => {
      const old = windows.previous.investors[i], recent = windows.recent.investors[i], delta = BigInt(recent.total_shares) - BigInt(old.total_shares)
      return [i, { net_delta_shares: String(delta), net_delta_lots: grossLots(String(delta)), verified_delta_zero: delta === 0n, count_deltas: Object.fromEntries(ADJACENT_SIGNS.map((s) => [s, recent.counts[s] - old.counts[s]])) }]
    })) as AdjacentStock['comparisons']
    return { symbol, name: ADJACENT_NAMES[symbol], exchange: 'TPEx', currency: 'TWD', security_type: 'stock', windows, pairs, comparisons }
  })
  return { sourceInputBytes, read: { schema: ADJACENT_SCHEMA, worker_schema: ADJACENT_WORKER_SCHEMA, capture_schema: ADJACENT_CAPTURE_SCHEMA, calendar_schema: ADJACENT_CALENDAR_SCHEMA, calendar_version: ADJACENT_CALENDAR_VERSION, calculation_version: ADJACENT_CALCULATION, profile: ADJACENT_PROFILE, policy_version: ADJACENT_VERSION, policy_digest: ADJACENT_PIN, policy, as_of: '2026-10-06', generation: 'synthetic-only-not-official-evidence', available: true, count: 7, reason: null, stocks, receipts,
    calendar: { schema: ADJACENT_CALENDAR_SCHEMA, version: ADJACENT_CALENDAR_VERSION, original_dates: originalDates, adopted_dates: adopted, daily_dates: dailyDates, previous_dates: dailyDates.slice(0, 5), recent_dates: dailyDates.slice(5), rows: calendarRows, post_cutoff_excluded: ['2026-10-07', '2026-10-08'] } } }
}
async function reseal(read: AdjacentRead, index: number) {
  const receipt = read.receipts[index], old = receipt.sha256
  receipt.canonical = canonicalJson(receipt.original); receipt.sha256 = await hash(receipt.canonical)
  for (const stock of read.stocks) for (const window of Object.values(stock.windows)) for (const point of window.points) if (point.receipt_sha256 === old) point.receipt_sha256 = receipt.sha256
  for (const row of read.calendar.rows) if (row.receipt_sha256 === old) row.receipt_sha256 = receipt.sha256
}
export async function runAdjacentChecks(read: AdjacentRead, assert: Assert): Promise<number> {
  let checks = 0
  const check = (ok: unknown, label: string) => { assert(ok, label); checks++ }
  async function rejected(change: (copy: AdjacentRead) => void | Promise<void>, label: string) { const copy = structuredClone(read); await change(copy); check(await validateAdjacent(copy) === null, label) }
  const lifecycle = new EventTarget()
  let held: AdjacentRead | null = read, selected: number | null = 2, masks = 0, automaticFetch = 0
  const detach = installAdjacentPageLifecycle(lifecycle, () => { held = null; selected = null; masks++ })
  const dispatch = (name: string, persisted: boolean) => {
    const event = new Event(name)
    Object.defineProperty(event, 'persisted', { value: persisted })
    lifecycle.dispatchEvent(event)
  }
  const previousFetch = globalThis.fetch
  globalThis.fetch = () => { automaticFetch++; throw new Error('lifecycle must not fetch') }
  try {
    dispatch('pageshow', false)
    check(masks === 0 && held === read && selected === 2, 'initial pageshow leaves state and performs no action')
    dispatch('pagehide', false)
    check(Number(masks) === 1 && held === null && selected === null, 'ordinary pagehide synchronously clears full graph and selected pair')
    held = read; selected = 3
    dispatch('pagehide', true)
    check(Number(masks) === 2 && held === null && selected === null, 'persisted pagehide clears before dispatch returns; native commit still requires browser acceptance')
    held = read; selected = 4
    dispatch('pageshow', true)
    check(Number(masks) === 3 && held === null && selected === null, 'persisted pageshow independently clears stale restored state')
    dispatch('pageshow', true)
    check(Number(masks) === 4 && held === null && selected === null, 'repeated restore remains masked without recovering old values')
    detach(); held = read; selected = 5
    dispatch('pagehide', true); dispatch('pageshow', true)
    check(Number(masks) === 4 && held === read && selected === 5, 'unmounted page detaches both lifecycle handlers')
    check(automaticFetch === 0, 'lifecycle has no automatic READ or capture')
  } finally { detach(); globalThis.fetch = previousFetch }
  check(await validateAdjacent(read) !== null, 'ALL70 / two disjoint5 windows / 35 positional pairs / 21 comparisons')
  const golden = read.stocks[0].windows.previous.points.map((p, i) => ({ ...p, net_shares: { ...p.net_shares, foreign: String([2, 3, 0, 0, -1][i]) } }))
  const stats = adjacentStats(golden, 'foreign')
  check(canonicalJson(stats.counts) === canonicalJson({ positive: 2, negative: 1, zero: 2 }) && stats.total_shares === '4', 'independent counts and sum golden')
  check(canonicalJson(stats.segments.map((s) => [s.sign, s.start_index, s.end_index, s.length, s.earlier_unknown])) === canonicalJson([['positive', 0, 1, 2, true], ['zero', 2, 3, 2, false], ['negative', 4, 4, 1, false]]), 'zero interrupts signs, maximal runs and first censor')
  check(stats.latest_run.sign === 'negative' && stats.latest_run.length === 1, 'latest confined to this5 window')
  for (const bad of ['-0', '+1', '01', '1.0', '9223372036854775808']) check(grossInteger(bad) === null, 'canonical int64 ' + bad)
  check(grossLots('-1') === '-0.001' && grossLots('1200') === '1.2', 'exact lots')
  for (const n of [2n ** 63n, -(2n ** 63n) - 1n]) { let caught = false; try { adjacentBound(n) } catch { caught = true }; check(caught, 'derived subtraction overflow') }
  let caught = false
  try { adjacentStats(golden.map((p, i) => ({ ...p, net_shares: { ...p.net_shares, foreign: String([2n ** 63n - 1n, 1n, -(2n ** 63n - 1n), 0n, 0n][i]) } })), 'foreign') } catch { caught = true }
  check(caught, 'window partial sum overflow even when final in range')
  const controls = adjacentControls(new URLSearchParams('as_of=2026-10-06&investor=dealer&horizon=5'))
  check(adjacentPath(controls, '6510').endsWith('/6510?as_of=2026-10-06&investor=dealer&horizon=5'), 'all three RAW controls preserved')
  check(!validAdjacentControls({ ...controls, horizon: '20' }) && !validAdjacentControls({ ...controls, as_of: '' }), 'only adjacent5 valid')
  for (const raw of ['as_of=2026-10-06&investor=trust', 'as_of=2026-10-06&investor=trust&horizon=5&x=1', 'as_of=2026-10-06&investor=trust&horizon=5&horizon=5']) check(!validAdjacentParams(new URLSearchParams(raw)), 'missing duplicate unknown RAW query')
  await rejected((v) => { v.policy.calendar.from = '2026-09-02' }, 'independent canonical root policy')
  await rejected((v) => { v.policy_digest = 'old' }, 'old pin')
  await rejected((v) => { v.worker_schema = 'old' }, 'worker schema')
  await rejected((v) => { v.calendar.version = 'old' }, 'calendar schema version')
  await rejected((v) => { v.stocks.pop() }, 'seventh stock missing')
  await rejected((v) => { v.receipts[2].canonical = '{}' }, 'canonical original digest')
  await rejected(async (v) => { v.receipts[2].original.source_version = 'old'; await reseal(v, 2) }, 'resealed wrong source version')
  await rejected(async (v) => { v.receipts[2].original.url = v.receipts[3].original.url; await reseal(v, 2) }, 'dynamic exact daily URL')
  await rejected(async (v) => { v.receipts[2].original.captured_at = '2026-10-07T00:00:02+00:00'; await reseal(v, 2) }, 'old observation')
  await rejected(async (v) => { for (let i = 0; i < v.receipts.length; i++) { v.receipts[i].original.request_started_at = '2026-10-08T24:00:00+00:00'; v.receipts[i].original.captured_at = '2026-10-08T24:00:00+00:00'; await reseal(v, i) } }, 'UTC24 rollover is rejected without normalizing observation date')
  await rejected(async (v) => { v.receipts[2].original.extra = 'not-original'; await reseal(v, 2) }, 'unaugmented original receipt')
  await rejected((v) => { v.calendar.rows.at(-1)!.source_values[2] = '1' }, 'ALL postcutoff OHLC')
  await rejected((v) => { v.calendar.rows.splice(3, 1); v.calendar.original_dates.splice(3, 1) }, 'full adopted weekday missing')
  await rejected((v) => { v.calendar.rows.push(v.calendar.rows[0]); v.calendar.original_dates.push(v.calendar.original_dates[0]) }, 'full calendar duplicate')
  await rejected((v) => { v.calendar.daily_dates.reverse() }, 'last10 strict order')
  await rejected((v) => { v.calendar.previous_dates[0] = v.calendar.recent_dates[0] }, 'windows disjoint')
  await rejected((v) => { v.stocks[0].windows.previous.points[0].net_shares.foreign = 1 as unknown as string }, 'JSON numeric net')
  await rejected((v) => { v.stocks[6].windows.previous.points[0].source_values[23] = '9223372036854775808' }, 'seventh stock original overflow')
  await rejected((v) => { v.stocks[0].windows.previous.points[0].source_values[21] = '2' }, 'dealer components')
  await rejected((v) => { v.stocks[0].windows.previous.points[0].signs.foreign = 'zero' }, 'sign must match exact original')
  await rejected((v) => { v.stocks[0].windows.previous.investors.foreign.counts.zero++ }, 'counts predicates and sum5')
  await rejected((v) => { v.stocks[0].windows.previous.investors.foreign.total_shares = '0' }, 'total from five originals')
  await rejected((v) => { v.stocks[0].windows.previous.investors.foreign.segments[0].end_index++ }, 'segment gap overlap')
  await rejected((v) => { v.stocks[0].windows.previous.investors.foreign.segments[0].earlier_unknown = false }, 'first segment censored')
  await rejected((v) => { v.stocks[0].windows.recent.investors.foreign.latest_run = v.stocks[0].windows.previous.investors.foreign.latest_run }, 'latest cannot borrow other window')
  await rejected((v) => { v.stocks[0].pairs[0].previous_date = v.stocks[0].pairs[1].previous_date }, 'wrong positional date pair')
  await rejected((v) => { v.stocks[0].pairs[0].recent_row_ordinal++ }, 'pair original ordinal')
  await rejected((v) => { v.stocks[0].pairs[0].net_delta_shares.foreign = '0' }, 'pair recent minus previous')
  await rejected((v) => { v.stocks[0].comparisons.foreign.net_delta_shares = '0' }, 'total delta and pair sum')
  await rejected((v) => { v.stocks[0].comparisons.foreign.count_deltas.zero = 6 }, 'count difference bounded and exact')
  await rejected((v) => { v.available = false; v.count = null }, 'unknown unavailable is not verified zero')
  return checks
}
