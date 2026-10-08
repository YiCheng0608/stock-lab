import { canonicalJson, GROSS_CALCULATION, GROSS_NAMES, GROSS_PIN, GROSS_PROFILE, GROSS_SCHEMA, GROSS_SYMBOLS, GROSS_VERSION, grossControls, grossGeometry, grossInteger, grossLots, grossPath, validateGross } from './chipsGross'
import type { GrossRead, GrossPoint, GrossStock } from './chipsGross'

type Assert = (value: unknown, message: string) => void
async function hash(text: string): Promise<string> {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))), (v) => v.toString(16).padStart(2, '0')).join('')
}
const csv = (header: string[], rows: string[][]) => [header, ...rows].map((r) => r.map((s) => '"' + s.replace(/"/g, '""') + '"').join(',')).join('\n') + '\n'
export async function createGrossFixture(policy: GrossRead['policy']): Promise<{ read: GrossRead; sourceInputBytes: number }> {
  const receipts: GrossRead['receipts'] = [], calendarRows: GrossRead['calendar']['rows'] = []
  const dailyRows: { point: Pick<GrossPoint, 'date' | 'row_ordinal' | 'source_values' | 'receipt_sha256' | 'body_sha256'>; values: bigint[][] }[][] = []
  const originalDates = [...policy.calendar.adopted_dates, '2026-10-07', '2026-10-08']
  let sourceInputBytes = new TextEncoder().encode(canonicalJson(policy)).length
  for (let ordinal = 0; ordinal < 22; ordinal++) {
    const requested = ordinal < 2 ? ['2026-09-01', '2026-10-01'][ordinal] : policy.scope.daily_dates[ordinal - 2]
    const valuesByStock: bigint[][][] = []
    const triple = (n: bigint) => [n > 0n ? n : 0n, n < 0n ? -n : 0n, n]
    const rows = ordinal < 2 ? originalDates.filter((d) => d.slice(0, 7) === requested.slice(0, 7)).map((d) => [d.replace(/-/g, ''), '100', '102', '99', '101', '1']) : GROSS_SYMBOLS.map((symbol, j) => {
      const n = BigInt((ordinal % 5 - 2) * (j + 1)), nets = [n * 100n + (ordinal === 2 ? 1n : 0n), n * 10n, n]
      valuesByStock.push(nets.map(triple))
      return [String(Number(requested.slice(0, 4)) - 1911) + requested.slice(5, 7) + requested.slice(8), symbol, GROSS_NAMES[symbol], ...[nets[0], 0n, nets[0], nets[1], nets[2], 0n, nets[2]].flatMap((net) => triple(net).map(String)), String(nets.reduce((a, b) => a + b, 0n))]
    })
    const body = csv(ordinal < 2 ? ['資料日期', '開市', '最高價', '最低價', '收市', '漲跌'] : policy.sources.daily.header, rows)
    const bodyBytes = new TextEncoder().encode(body).length, bodySHA = await hash(body)
    sourceInputBytes += bodyBytes
    const stamp = '2026-10-08T00:00:' + String(ordinal).padStart(2, '0') + '+00:00'
    const original = { schema: 'tpex-institutional-gross-capture/chips-stock-scope-7-v1', ordinal, source: ordinal < 2 ? 'index' : 'daily', source_version: ordinal < 2 ? policy.sources.index.source_version : policy.sources.daily.source_version, requested_date: requested, url: policy.sources.exact_urls[ordinal], method: 'GET', request_body_bytes: 0, http_status: 200, content_type: 'application/csv;charset=utf-8', content_encoding: 'identity', body_bytes: bodyBytes, body_sha256: bodySHA, request_started_at: stamp, captured_at: stamp, policy_version: GROSS_VERSION, policy_digest: GROSS_PIN, profile: GROSS_PROFILE, publication_time: 'unknown', first_available_time: 'unknown', revision_time: 'unknown', historical_pit: 'unsupported', request_count: 1 }
    const canonical = canonicalJson(original), receiptSHA = await hash(canonical)
    receipts.push({ original, canonical, sha256: receiptSHA })
    const trace = (row: string[], i: number) => ({ date: ordinal < 2 ? row[0].slice(0, 4) + '-' + row[0].slice(4, 6) + '-' + row[0].slice(6) : requested, row_ordinal: i + 1, source_values: row, body_sha256: bodySHA, receipt_sha256: receiptSHA })
    if (ordinal < 2) calendarRows.push(...rows.map(trace))
    else dailyRows.push(rows.map((row, i) => ({ point: trace(row, i), values: valuesByStock[i] })))
  }
  const stocks: GrossStock[] = GROSS_SYMBOLS.map((symbol, j) => {
    const series = {} as GrossStock['series']
    for (const [i, investor] of (['foreign', 'trust', 'dealer'] as const).entries()) {
      const windows: GrossStock['series']['foreign'] = {}
      for (const horizon of [5, 20]) {
        const prefixes = [0n, 0n, 0n]
        const points = dailyRows.slice(-horizon).map((rows) => {
          const row = rows[j], values = row.values[i], point = { ...row.point } as GrossPoint
          for (const [k, component] of (['buy', 'sell', 'net'] as const).entries()) {
            prefixes[k] += values[k]
            point[`${component}_shares`] = String(values[k]); point[`${component}_lots`] = grossLots(String(values[k]))
            point[`cumulative_${component}_shares`] = String(prefixes[k]); point[`cumulative_${component}_lots`] = grossLots(String(prefixes[k]))
          }
          return point
        })
        const window = { horizon, points } as GrossStock['series']['foreign'][string]
        for (const [k, component] of (['buy', 'sell', 'net'] as const).entries()) {
          window[`total_${component}_shares`] = String(prefixes[k]); window[`total_${component}_lots`] = grossLots(String(prefixes[k])); window[`verified_${component}_zero`] = prefixes[k] === 0n
        }
        windows[String(horizon)] = window
      }
      series[investor] = windows
    }
    return { symbol, name: GROSS_NAMES[symbol], exchange: 'TPEx', currency: 'TWD', security_type: 'stock', series }
  })
  return { sourceInputBytes, read: { schema: GROSS_SCHEMA, calculation_version: GROSS_CALCULATION, profile: GROSS_PROFILE, policy_version: GROSS_VERSION, policy_digest: GROSS_PIN, policy, as_of: '2026-10-06', generation: 'synthetic-only-no-official-evidence', available: true, count: 7, reason: null, stocks, receipts, calendar: { original_dates: originalDates, adopted_dates: policy.calendar.adopted_dates, rows: calendarRows, post_cutoff_excluded: ['2026-10-07', '2026-10-08'] } } }
}
async function reseal(read: GrossRead, index: number) {
  const receipt = read.receipts[index], old = receipt.sha256
  receipt.canonical = canonicalJson(receipt.original); receipt.sha256 = await hash(receipt.canonical)
  for (const stock of read.stocks) for (const windows of Object.values(stock.series)) for (const window of Object.values(windows)) for (const point of window.points) if (point.receipt_sha256 === old) point.receipt_sha256 = receipt.sha256
  for (const row of read.calendar.rows) if (row.receipt_sha256 === old) row.receipt_sha256 = receipt.sha256
}
export async function runGrossChecks(read: GrossRead, assert: Assert): Promise<number> {
  let checks = 0
  async function rejected(change: (copy: GrossRead) => void | Promise<void>, label: string) {
    const copy = structuredClone(read); await change(copy)
    assert(await validateGross(copy) === null, label); checks++
  }
  assert(await validateGross(read) !== null, 'whole84gross42net synthetic graph'); checks++
  for (const bad of ['-0', '+1', '01', '1.0', '9223372036854775808']) { assert(grossInteger(bad) === null, 'canonical integer ' + bad); checks++ }
  assert(grossLots('-1') === '-0.001' && grossLots('1200') === '1.2', 'exact signed lots'); checks++
  const controls = grossControls(new URLSearchParams('as_of=2026-10-06&investor=dealer&horizon=5'))
  assert(grossPath(controls, '6510').endsWith('/6510?as_of=2026-10-06&investor=dealer&horizon=5'), 'three RAW controls roundtrip'); checks++
  await rejected((v) => { v.policy.scope.daily_dates[0] = '2026-09-08' }, 'independent policy pin')
  await rejected((v) => { v.policy_digest = 'sha256:143aabb4cd2d86110d5564793ce77b0fb6c60b3e603f23c1e188875934a48a31' }, 'old profile pin isolation')
  await rejected((v) => { v.stocks.pop() }, 'missing seventh stock masks whole profile')
  await rejected((v) => { v.receipts[2].canonical = '{}' }, 'original receipt digest')
  await rejected(async (v) => { v.receipts[2].original.source_version = 'old'; await reseal(v, 2) }, 'internally resealed wrong source version')
  await rejected(async (v) => { v.receipts[2].original.captured_at = '2026-10-07T00:00:02+00:00'; await reseal(v, 2) }, 'old observation date')
  await rejected((v) => { v.calendar.rows[0].source_values[1] = 'NaN' }, 'all index finite values')
  await rejected((v) => { v.calendar.rows.at(-1)!.source_values[2] = '1' }, 'postcutoff OHLC validated before selection')
  await rejected((v) => { v.calendar.rows.splice(3, 1); v.calendar.original_dates.splice(3, 1) }, 'missing weekday does not shrink window')
  await rejected((v) => { v.calendar.rows.push(v.calendar.rows[0]); v.calendar.original_dates.push(v.calendar.original_dates[0]) }, 'duplicate calendar')
  await rejected((v) => { v.stocks[0].series.foreign['20'].points[0].buy_shares = '-1' }, 'negative gross')
  await rejected((v) => { v.stocks[0].series.foreign['20'].points[0].buy_shares = 9007199254740992 as unknown as string }, 'unsafe JSON number')
  await rejected((v) => { v.stocks[6].series.dealer['20'].points[0].sell_shares = '9223372036854775808' }, 'seventh stock int64 overflow')
  await rejected((v) => { v.stocks[0].series.foreign['5'].points[0].cumulative_buy_shares = v.stocks[0].series.foreign['20'].points[15].cumulative_buy_shares }, 'five-day reset cannot use twenty-day prefix')
  await rejected((v) => { v.stocks[0].series.foreign['20'].total_buy_shares = '9223372036854775808' }, 'gross aggregate overflow')
  await rejected((v) => { v.stocks[0].series.foreign['20'].points[1].cumulative_sell_shares = '9223372036854775808' }, 'gross prefix overflow')
  await rejected((v) => { v.stocks[0].series.foreign['20'].total_net_shares = '2' }, 'buy minus sell equals net total')
  await rejected((v) => { v.stocks[0].series.trust['20'].points[0].row_ordinal = 99 }, 'cross-investor raw ordinal')
  await rejected((v) => { v.stocks[0].series.dealer['5'].points[0].source_values = [...v.stocks[0].series.dealer['5'].points[0].source_values]; v.stocks[0].series.dealer['5'].points[0].source_values[2] += ' ' }, 'all25 rawstrings consistent across windows')
  await rejected((v) => { v.available = false; v.count = null }, 'unavailable never zero')
  const points = read.stocks[0].series.foreign['20'].points
  assert(points.some((p) => p.buy_shares === '0') && points.some((p) => p.sell_shares === '0') && grossGeometry(points).values.every((p) => p.y <= 150), 'synthetic gross zeros geometry'); checks++
  return checks
}
