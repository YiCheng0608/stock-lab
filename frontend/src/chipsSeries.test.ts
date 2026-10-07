import { canonicalJson, SERIES_CALCULATION, SERIES_NAMES, SERIES_PIN, SERIES_PROFILE, SERIES_SCHEMA, SERIES_SYMBOLS, SERIES_VERSION, seriesControls, seriesGeometry, seriesInteger, seriesLots, seriesPath, validateSeries } from './chipsSeries'
import type { SeriesRead, SeriesPoint, SeriesStock } from './chipsSeries'

type Assert = (value: unknown, message: string) => void
async function hash(text: string): Promise<string> {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))), (v) => v.toString(16).padStart(2, '0')).join('')
}
const csv = (header: string[], rows: string[][]) => [header, ...rows].map((r) => r.map((s) => '"' + s.replace(/"/g, '""') + '"').join(',')).join('\n') + '\n'
export async function createSeriesFixture(policy: SeriesRead['policy']): Promise<{ read: SeriesRead; sourceInputBytes: number }> {
  const receipts: SeriesRead['receipts'] = []
  const calendarRows: SeriesRead['calendar']['rows'] = []
  const dailyRows: { point: Omit<SeriesPoint, 'net_shares' | 'net_lots' | 'cumulative_shares' | 'cumulative_lots'>; nets: bigint[] }[][] = []
  let sourceInputBytes = new TextEncoder().encode(canonicalJson(policy)).length
  for (let ordinal = 0; ordinal < 22; ordinal++) {
    const requested = ordinal < 2 ? ['2026-09-01', '2026-10-01'][ordinal] : policy.scope.daily_dates[ordinal - 2]
    let rows: string[][]
    const netsByStock: bigint[][] = []
    if (ordinal < 2) {
      rows = policy.calendar.original_dates.filter((d) => d.slice(0, 7) === requested.slice(0, 7)).map((d) => [d.replace(/-/g, ''), '100', '102', '99', '101', '1'])
    } else {
      rows = SERIES_SYMBOLS.map((symbol, j) => {
        const net = BigInt((ordinal % 5 - 2) * (j + 1))
        const nets = [net * 100n + (ordinal === 2 ? 1n : 0n), net * 10n, net]
        netsByStock.push(nets)
        const triple = (n: bigint) => [String(n > 0n ? n : 0n), String(n < 0n ? -n : 0n), String(n)]
        return [String(Number(requested.slice(0, 4)) - 1911) + requested.slice(5, 7) + requested.slice(8), symbol, SERIES_NAMES[symbol], ...[nets[0], 0n, nets[0], nets[1], nets[2], 0n, nets[2]].flatMap(triple), String(nets.reduce((a, b) => a + b, 0n))]
      })
    }
    const body = csv(ordinal < 2 ? ['資料日期', '開市', '最高價', '最低價', '收市', '漲跌'] : policy.sources.daily.header, rows)
    const bodyBytes = new TextEncoder().encode(body).length
    sourceInputBytes += bodyBytes
    const bodySHA = await hash(body)
    const stamp = '2026-10-07T00:00:' + String(ordinal).padStart(2, '0') + '+00:00'
    const original = { schema: 'tpex-institutional-series-capture/chips-stock-scope-7-v1', ordinal, source: ordinal < 2 ? 'index' : 'daily', source_version: ordinal < 2 ? policy.sources.index.source_version : policy.sources.daily.source_version, requested_date: requested, url: policy.sources.exact_urls[ordinal], method: 'GET', request_body_bytes: 0, http_status: 200, content_type: 'application/csv;charset=utf-8', content_encoding: 'identity', body_bytes: bodyBytes, body_sha256: bodySHA, request_started_at: stamp, captured_at: stamp, policy_version: SERIES_VERSION, policy_digest: SERIES_PIN, profile: SERIES_PROFILE, publication_time: 'unknown', first_available_time: 'unknown', revision_time: 'unknown', historical_pit: 'unsupported', request_count: 1 }
    const canonical = canonicalJson(original), receiptSHA = await hash(canonical)
    receipts.push({ original, canonical, sha256: receiptSHA })
    const trace = (row: string[], i: number) => ({ date: ordinal < 2 ? row[0].slice(0, 4) + '-' + row[0].slice(4, 6) + '-' + row[0].slice(6) : requested, row_ordinal: i + 1, source_values: row, body_sha256: bodySHA, receipt_sha256: receiptSHA })
    if (ordinal < 2) calendarRows.push(...rows.map(trace))
    else dailyRows.push(rows.map((row, i) => ({ point: trace(row, i), nets: netsByStock[i] })))
  }
  const stocks: SeriesStock[] = SERIES_SYMBOLS.map((symbol, j) => {
    const series = {} as SeriesStock['series']
    for (const [i, investor] of (['foreign', 'trust', 'dealer'] as const).entries()) {
      const windows: SeriesStock['series']['foreign'] = {}
      for (const horizon of [5, 20]) {
        let prefix = 0n
        const points = dailyRows.slice(-horizon).map((rows) => {
          const row = rows[j], net = row.nets[i]
          prefix += net
          return { ...row.point, net_shares: String(net), net_lots: seriesLots(String(net)), cumulative_shares: String(prefix), cumulative_lots: seriesLots(String(prefix)) }
        })
        windows[String(horizon)] = { horizon, points, total_shares: String(prefix), total_lots: seriesLots(String(prefix)), verified_zero: prefix === 0n }
      }
      series[investor] = windows
    }
    return { symbol, name: SERIES_NAMES[symbol], exchange: 'TPEx', currency: 'TWD', security_type: 'stock', series }
  })
  return { sourceInputBytes, read: { schema: SERIES_SCHEMA, calculation_version: SERIES_CALCULATION, profile: SERIES_PROFILE, policy_version: SERIES_VERSION, policy_digest: SERIES_PIN, policy, as_of: '2026-10-06', generation: 'synthetic-only-no-official-evidence', available: true, count: 7, reason: null, stocks, receipts, calendar: { original_dates: policy.calendar.original_dates, adopted_dates: policy.calendar.adopted_dates, rows: calendarRows, post_cutoff_excluded: ['2026-10-07'] } } }
}
async function reseal(read: SeriesRead, index: number) {
  const receipt = read.receipts[index], old = receipt.sha256
  receipt.canonical = canonicalJson(receipt.original); receipt.sha256 = await hash(receipt.canonical)
  for (const stock of read.stocks) for (const windows of Object.values(stock.series)) for (const window of Object.values(windows)) for (const point of window.points) if (point.receipt_sha256 === old) point.receipt_sha256 = receipt.sha256
  for (const row of read.calendar.rows) if (row.receipt_sha256 === old) row.receipt_sha256 = receipt.sha256
}
export async function runSeriesChecks(read: SeriesRead, assert: Assert): Promise<number> {
  let checks = 0
  async function rejected(change: (copy: SeriesRead) => void | Promise<void>, label: string) {
    const copy = structuredClone(read)
    await change(copy)
    assert(await validateSeries(copy) === null, label); checks++
  }
  assert(await validateSeries(read) !== null, 'complete all42 synthetic graph validates'); checks++
  assert(seriesInteger('-9223372036854775808') === -(2n ** 63n) && seriesInteger('9223372036854775807') === 2n ** 63n - 1n, 'signed int64 endpoints'); checks++
  for (const n of ['-0', '+1', '01', '1.0', '9223372036854775808']) { assert(seriesInteger(n) === null, 'canonical integer rejects ' + n); checks++ }
  assert(seriesLots('-1') === '-0.001' && seriesLots('1200') === '1.2', 'exact signed lots'); checks++
  const c = seriesControls(new URLSearchParams('as_of=2026-10-06&investor=dealer&horizon=5'))
  assert(seriesPath(c, '6510').endsWith('/6510?as_of=2026-10-06&investor=dealer&horizon=5') && seriesPath(c).includes('investor=dealer&horizon=5'), 'raw control detail/back URLs'); checks++
  await rejected((v) => { v.policy.scope.daily_dates[0] = '2026-09-08' }, 'canonical policy tamper')
  await rejected((v) => { v.stocks.pop() }, 'missing stock')
  await rejected((v) => { v.receipts[2].canonical = '{}' }, 'original receipt tamper')
  await rejected(async (v) => { v.receipts[2].original.source_version = 'old'; await reseal(v, 2) }, 'source version mismatch after internally valid receipt reseal')
  await rejected(async (v) => { v.receipts[2].original.body_bytes = 1.5; await reseal(v, 2) }, 'fractional body bytes')
  await rejected(async (v) => { v.receipts[2].original.body_bytes = 2097153; await reseal(v, 2) }, 'body and aggregate source quota gate')
  await rejected((v) => { for (const h of ['5', '20']) v.stocks[0].series.trust[h].points.forEach((p) => { p.row_ordinal = 99 }) }, 'cross-investor original ordinal mismatch')
  await rejected((v) => { for (const h of ['5', '20']) v.stocks[0].series.trust[h].points.forEach((p) => { p.source_values = [...p.source_values]; p.source_values[2] += ' ' }) }, 'cross-investor original25 mismatch despite same trimmed name')
  await rejected((v) => { v.calendar.rows[0].receipt_sha256 = v.receipts[1].sha256; v.calendar.rows[0].body_sha256 = String(v.receipts[1].original.body_sha256) }, 'index receipt month mismatch')
  await rejected(async (v) => { v.receipts[2].original.captured_at = '2026-10-08T00:00:02+00:00'; await reseal(v, 2) }, 'observation date change')
  await rejected((v) => { v.stocks[0].series.foreign['5'].points[0].cumulative_shares = '1' }, 'window-reset prefix mismatch')
  await rejected((v) => { v.stocks[0].series.foreign['20'].total_shares = '9223372036854775808' }, 'aggregate overflow')
  await rejected((v) => { v.stocks[0].series.foreign['20'].points[0].net_shares = '9223372036854775808' }, 'daily overflow')
  await rejected((v) => {
    const stock = v.stocks[0], values = [2n ** 63n - 1n, 1n, -1n, ...Array<bigint>(17).fill(0n)]
    const rows = stock.series.foreign['20'].points.map((p, i) => {
      const n = values[i], buy = n > 0n ? n : 0n, sell = n < 0n ? -n : 0n
      const raw = [...p.source_values.slice(0, 3), ...Array<string>(22).fill('0')]
      for (const start of [3, 9]) { raw[start] = String(buy); raw[start + 1] = String(sell); raw[start + 2] = String(n) }
      raw[24] = String(n)
      return { ...p, source_values: raw }
    })
    for (const investor of ['foreign', 'trust', 'dealer'] as const) for (const horizon of ['5', '20']) {
      const window = stock.series[investor][horizon]
      let prefix = 0n
      window.points = rows.slice(-Number(horizon)).map((p, i) => {
        const n = investor === 'foreign' ? values[20 - Number(horizon) + i] : 0n
        prefix += n
        return { ...p, net_shares: String(n), net_lots: seriesLots(String(n)), cumulative_shares: String(prefix), cumulative_lots: seriesLots(String(prefix)) }
      })
      window.total_shares = String(prefix); window.total_lots = seriesLots(String(prefix)); window.verified_zero = prefix === 0n
    }
  }, 'running prefix exceeds int64 while final aggregate remains MAX')
  await rejected((v) => { v.available = false; v.count = null }, 'unavailable cannot expose zero')
  const points = read.stocks[0].series.foreign['20'].points
  const g = seriesGeometry(points)
  assert(points.some((p) => p.net_shares === '0') && g.values.some((p) => p.y < g.zero) && g.values.some((p) => p.y > g.zero), 'negative positive and zero chart geometry'); checks++
  return checks
}
