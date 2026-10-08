import { canonicalJson, grossInteger, grossLots } from './chipsGross'
import { DIRECTION_CALCULATION, DIRECTION_CALENDAR_SCHEMA, DIRECTION_CALENDAR_VERSION, DIRECTION_CAPTURE_SCHEMA, DIRECTION_CATEGORIES, DIRECTION_NAMES, DIRECTION_PIN, DIRECTION_PROFILE, DIRECTION_SCHEMA, DIRECTION_SYMBOLS, DIRECTION_VERSION, DIRECTION_WORKER_SCHEMA, directionCategory, directionControls, directionPath, directionStats, validateDirection } from './chipsDirection'
import type { DirectionCategory, DirectionPoint, DirectionPolicy, DirectionRead, DirectionSegment, DirectionStock, DirectionWindow } from './chipsDirection'

type Assert = (value: unknown, message: string) => void
const csv = (header: string[], rows: string[][]) => [header, ...rows].map((r) => r.map((s) => '"' + s.replace(/"/g, '""') + '"').join(',')).join('\n') + '\n'
async function hash(text: string): Promise<string> { return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))), (n) => n.toString(16).padStart(2, '0')).join('') }
const patterns: [number[], DirectionCategory][] = [[[1, 1, 1], 'all_positive'], [[-1, -1, -1], 'all_negative'], [[1, -1, 0], 'opposite'], [[1, 0, 0], 'single_direction_with_zero'], [[0, 0, 0], 'all_zero'], [[1, 1, 1], 'all_positive'], [[1, 1, 1], 'all_positive'], [[-1, 0, 1], 'opposite'], [[0, -1, -1], 'single_direction_with_zero'], [[0, 0, 0], 'all_zero']]
export async function createDirectionFixture(policy: DirectionPolicy): Promise<{ read: DirectionRead; sourceInputBytes: number }> {
  const receipts: DirectionRead['receipts'] = [], calendarRows: DirectionRead['calendar']['rows'] = [], daily: DirectionPoint[][] = []
  const originalDates = [...policy.calendar.adopted_dates, '2026-10-07', '2026-10-08']
  let sourceInputBytes = new TextEncoder().encode(canonicalJson(policy)).length
  for (let ordinal = 0; ordinal < 22; ordinal++) {
    const requested = ordinal < 2 ? ['2026-09-01', '2026-10-01'][ordinal] : policy.scope.daily_dates[ordinal - 2]
    const rows = ordinal < 2 ? originalDates.filter((d) => d.slice(0, 7) === requested.slice(0, 7)).map((d) => [d.replace(/-/g, ''), '100', '102', '99', '101', '1']) : DIRECTION_SYMBOLS.map((symbol, j) => {
      const [signs] = patterns[(ordinal - 2 + j) % patterns.length]
      const [foreign, trust, dealer] = signs.map((n) => BigInt(n * (j + 1) * 1001))
      const triple = (n: bigint) => [String(n > 0n ? n : 0n), String(n < 0n ? -n : 0n), String(n)]
      return [String(Number(requested.slice(0, 4)) - 1911) + requested.slice(5, 7) + requested.slice(8), symbol, DIRECTION_NAMES[symbol],
        ...[foreign, 0n, foreign, trust, dealer, 0n, dealer].flatMap(triple), String(foreign + trust + dealer)]
    })
    const body = csv(ordinal < 2 ? ['資料日期', '開市', '最高價', '最低價', '收市', '漲跌'] : policy.sources.daily.header, rows)
    const bodySHA = await hash(body), bodyBytes = new TextEncoder().encode(body).length
    sourceInputBytes += bodyBytes
    const stamp = '2026-10-08T00:00:' + String(ordinal).padStart(2, '0') + '+00:00'
    const original = { schema: DIRECTION_CAPTURE_SCHEMA, ordinal, source: ordinal < 2 ? 'index' : 'daily', source_version: ordinal < 2 ? policy.sources.index.source_version : policy.sources.daily.source_version, requested_date: requested, url: policy.sources.exact_urls[ordinal], method: 'GET', request_body_bytes: 0, http_status: 200, content_type: 'application/csv;charset=utf-8', content_encoding: 'identity', body_bytes: bodyBytes, body_sha256: bodySHA, request_started_at: stamp, captured_at: stamp, policy_version: DIRECTION_VERSION, policy_digest: DIRECTION_PIN, profile: DIRECTION_PROFILE, publication_time: 'unknown', first_available_time: 'unknown', revision_time: 'unknown', historical_pit: 'unsupported', request_count: 1 }
    const canonical = canonicalJson(original), receiptSHA = await hash(canonical)
    receipts.push({ original, canonical, sha256: receiptSHA })
    const trace = (row: string[], index: number) => ({ date: ordinal < 2 ? row[0].slice(0, 4) + '-' + row[0].slice(4, 6) + '-' + row[0].slice(6) : requested, row_ordinal: index + 1, source_values: row, receipt_sha256: receiptSHA, body_sha256: bodySHA })
    if (ordinal < 2) calendarRows.push(...rows.map(trace))
    else daily.push(rows.map((row, j) => {
      const [signs, category] = patterns[(ordinal - 2 + j) % patterns.length]
      const net_shares = { foreign: row[5], trust: row[14], dealer: row[23] }
      return { ...trace(row, j), net_shares, net_lots: { foreign: grossLots(row[5]), trust: grossLots(row[14]), dealer: grossLots(row[23]) },
        signs: { foreign: signs[0] > 0 ? 'positive' : signs[0] < 0 ? 'negative' : 'zero', trust: signs[1] > 0 ? 'positive' : signs[1] < 0 ? 'negative' : 'zero', dealer: signs[2] > 0 ? 'positive' : signs[2] < 0 ? 'negative' : 'zero' }, category }
    }))
  }
  const stocks: DirectionStock[] = DIRECTION_SYMBOLS.map((symbol, j) => {
    const windows: Record<string, DirectionWindow> = {}
    for (const horizon of [5, 20]) {
      const points = daily.slice(-horizon).map((rows) => rows[j]), investors = {} as DirectionWindow['investors']
      for (const investor of ['foreign', 'trust', 'dealer'] as const) {
        const counts = { positive: 0, negative: 0, zero: 0 }, segments: DirectionSegment[] = []
        let begin = 0
        while (begin < points.length) {
          const current = points[begin].signs[investor]
          let end = begin
          while (end + 1 < points.length && points[end + 1].signs[investor] === current) end++
          counts[current] += end - begin + 1
          segments.push({ sign: current, start_index: begin, end_index: end, start_date: points[begin].date, end_date: points[end].date, length: end - begin + 1, earlier_unknown: begin === 0 })
          begin = end + 1
        }
        investors[investor] = { counts, segments, latest_run: { ...segments[segments.length - 1] } }
      }
      const direction_counts = Object.fromEntries(DIRECTION_CATEGORIES.map((c) => [c, points.filter((p) => p.category === c).length])) as DirectionWindow['direction_counts']
      windows[String(horizon)] = { horizon, points, direction_counts, investors }
    }
    return { symbol, name: DIRECTION_NAMES[symbol], exchange: 'TPEx', currency: 'TWD', security_type: 'stock', windows }
  })
  return { sourceInputBytes, read: { schema: DIRECTION_SCHEMA, worker_schema: DIRECTION_WORKER_SCHEMA, capture_schema: DIRECTION_CAPTURE_SCHEMA, calendar_schema: DIRECTION_CALENDAR_SCHEMA, calendar_version: DIRECTION_CALENDAR_VERSION, calculation_version: DIRECTION_CALCULATION, profile: DIRECTION_PROFILE, policy_version: DIRECTION_VERSION, policy_digest: DIRECTION_PIN, policy, as_of: '2026-10-06', generation: 'synthetic-only-not-official-evidence', available: true, count: 7, reason: null, stocks, receipts,
    calendar: { schema: DIRECTION_CALENDAR_SCHEMA, version: DIRECTION_CALENDAR_VERSION, original_dates: originalDates, adopted_dates: policy.calendar.adopted_dates, rows: calendarRows, post_cutoff_excluded: ['2026-10-07', '2026-10-08'] } } }
}
async function reseal(read: DirectionRead, index: number) {
  const receipt = read.receipts[index], old = receipt.sha256
  receipt.canonical = canonicalJson(receipt.original); receipt.sha256 = await hash(receipt.canonical)
  for (const stock of read.stocks) for (const window of Object.values(stock.windows)) for (const point of window.points) if (point.receipt_sha256 === old) point.receipt_sha256 = receipt.sha256
  for (const row of read.calendar.rows) if (row.receipt_sha256 === old) row.receipt_sha256 = receipt.sha256
}
export async function runDirectionChecks(read: DirectionRead, assert: Assert): Promise<number> {
  let checks = 0
  const check = (ok: unknown, label: string) => { assert(ok, label); checks++ }
  async function rejected(change: (copy: DirectionRead) => void | Promise<void>, label: string) { const copy = structuredClone(read); await change(copy); check(await validateDirection(copy) === null, label) }
  check(await validateDirection(read) !== null, 'whole140 triples / 42 groups synthetic graph')
  const categories: Record<string, DirectionCategory> = {}
  for (const [category, triples] of Object.entries({ all_positive: ['+++'], all_negative: ['---'], all_zero: ['000'], single_direction_with_zero: ['00+', '0+0', '+00', '0++', '+0+', '++0', '00-', '0-0', '-00', '0--', '-0-', '--0'], opposite: ['++-', '+-+', '-++', '--+', '-+-', '+--', '+-0', '+0-', '-+0', '-0+', '0+-', '0-+'] })) for (const triple of triples) categories[triple] = category as DirectionCategory
  check(Object.keys(categories).length === 27 && Object.entries(categories).every(([triple, category]) => directionCategory([...triple].map((c) => c === '+' ? 1n : c === '-' ? -1n : 0n)) === category), 'all27 mutually exclusive triple categories')
  const golden = read.stocks[0].windows['5'].points.map((p, i) => ({ ...p, net_shares: { ...p.net_shares, foreign: String([2, 3, 0, 0, -1][i]) } }))
  const goldenStats = directionStats(golden, 'foreign')
  check(canonicalJson(goldenStats.counts) === canonicalJson({ positive: 2, negative: 1, zero: 2 }) && canonicalJson(goldenStats.segments.map((s) => [s.sign, s.start_index, s.end_index, s.length, s.earlier_unknown])) === canonicalJson([['positive', 0, 1, 2, true], ['zero', 2, 3, 2, false], ['negative', 4, 4, 1, false]]), 'zero breaks signed runs, maximal coverage and first censor')
  check(goldenStats.latest_run.sign === 'negative' && goldenStats.latest_run.length === 1, 'latest only final segment')
  for (const bad of ['-0', '+1', '01', '1.0', '9223372036854775808']) check(grossInteger(bad) === null, 'canonical int64 ' + bad)
  check(grossLots('-1') === '-0.001' && grossLots('1200') === '1.2', 'exact signed lots')
  const controls = directionControls(new URLSearchParams('as_of=2026-10-06&investor=dealer&horizon=5'))
  check(directionPath(controls, '6510').endsWith('/6510?as_of=2026-10-06&investor=dealer&horizon=5'), 'three RAW controls')
  await rejected((v) => { v.policy.scope.daily_dates[0] = '2026-09-08' }, 'independent canonical root pin')
  await rejected((v) => { v.policy_digest = 'sha256:ea02b5f32ff2bd0c415e14192c6daa276dc2781e8a6c2d4e5b90bcad776d1144' }, 'old profile pin')
  await rejected((v) => { v.worker_schema = 'old' }, 'worker schema')
  await rejected((v) => { v.calendar.version = 'old' }, 'calendar version')
  await rejected((v) => { v.stocks.pop() }, 'seventh stock missing')
  await rejected((v) => { v.receipts[2].canonical = '{}' }, 'original receipt digest')
  await rejected(async (v) => { v.receipts[2].original.source_version = 'old'; await reseal(v, 2) }, 'resealed wrong source version')
  await rejected(async (v) => { v.receipts[2].original.captured_at = '2026-10-07T00:00:02+00:00'; await reseal(v, 2) }, 'old observation time')
  await rejected((v) => { v.calendar.rows.at(-1)!.source_values[2] = '1' }, 'postcutoff OHLC checked')
  await rejected((v) => { v.calendar.rows.splice(3, 1); v.calendar.original_dates.splice(3, 1) }, 'missing adopted weekday')
  await rejected((v) => { v.calendar.rows.push(v.calendar.rows[0]); v.calendar.original_dates.push(v.calendar.original_dates[0]) }, 'duplicate full calendar')
  await rejected((v) => { v.stocks[0].windows['20'].points[0].net_shares.foreign = 1 as unknown as string }, 'JSON numeric net')
  await rejected((v) => { v.stocks[6].windows['20'].points[0].source_values[23] = '9223372036854775808' }, 'seventh stock original int64')
  await rejected((v) => { v.stocks[0].windows['20'].points[0].source_values[21] = '2' }, 'original dealer components')
  await rejected((v) => { v.stocks[0].windows['20'].points[0].signs.foreign = 'zero' }, 'derived sign')
  await rejected((v) => { v.stocks[0].windows['20'].points[0].category = 'all_zero' }, 'derived triple category')
  await rejected((v) => { v.stocks[0].windows['20'].direction_counts.all_zero++ }, 'category count predicates')
  await rejected((v) => { v.stocks[0].windows['20'].investors.foreign.counts.zero++ }, 'counts sum and predicates')
  await rejected((v) => { v.stocks[0].windows['20'].investors.foreign.segments[0].end_index++ }, 'segment gap overlap')
  await rejected((v) => { v.stocks[0].windows['20'].investors.foreign.segments[0].length++ }, 'segment length')
  await rejected((v) => { v.stocks[0].windows['20'].investors.foreign.segments[0].earlier_unknown = false }, 'first segment earlier unknown')
  await rejected((v) => { v.stocks[0].windows['20'].investors.foreign.segments[1].sign = v.stocks[0].windows['20'].investors.foreign.segments[0].sign }, 'maximal adjacent equal sign')
  await rejected((v) => { v.stocks[0].windows['5'].investors.foreign.latest_run = v.stocks[0].windows['20'].investors.foreign.segments[0] }, 'latest cannot borrow longer window')
  await rejected((v) => { v.stocks[0].windows['20'].investors.foreign.latest_run.sign = 'positive' }, 'latest zero interrupts positive run')
  await rejected((v) => { v.stocks[0].windows['5'].points[0] = { ...v.stocks[0].windows['5'].points[0], row_ordinal: 99 } }, 'cross-window original ordinal')
  await rejected((v) => { v.available = false; v.count = null }, 'unavailable is never verified zero')
  return checks
}
