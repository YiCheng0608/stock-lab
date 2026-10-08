export const GROSS_ROUTE = '/chips-stock-scope-7-gross-trade'
export const GROSS_API = '/api/chips/gross-stock-scope-7'
export const GROSS_PIN = 'sha256:ea02b5f32ff2bd0c415e14192c6daa276dc2781e8a6c2d4e5b90bcad776d1144'
export const GROSS_VERSION = 'm1-chips-gross-trade-stock-scope-7-tpex-2026-10-06.1'
export const GROSS_PROFILE = 'free_public_local_chips_only_daily_gross_trade_stock_scope_7'
export const GROSS_SCHEMA = 'institutional-daily-gross-read/chips-stock-scope-7-v1'
export const GROSS_CALCULATION = 'gross-buy-sell-net-running-sum/window-reset-int64-v1'
export const GROSS_NAMES: Record<string, string> = { '3105': '穩懋', '3293': '鈊象', '5274': '信驊', '5347': '世界', '6488': '環球晶', '6510': '精測', '8069': '元太' }
export const GROSS_SYMBOLS = ['3105', '3293', '5274', '5347', '6488', '6510', '8069']
export const GROSS_INVESTORS = ['foreign', 'trust', 'dealer'] as const
export type GrossInvestor = typeof GROSS_INVESTORS[number]
export type GrossControls = { as_of: string; investor: string; horizon: string }
export type GrossComponent = 'buy' | 'sell' | 'net'
type PointValues = Record<`${GrossComponent}_shares` | `${GrossComponent}_lots` | `cumulative_${GrossComponent}_shares` | `cumulative_${GrossComponent}_lots`, string>
export type GrossPoint = { date: string; row_ordinal: number; source_values: string[]; receipt_sha256: string; body_sha256: string } & PointValues
export type GrossWindow = { horizon: number; points: GrossPoint[] } & Record<`total_${GrossComponent}_shares` | `total_${GrossComponent}_lots`, string> & Record<`verified_${GrossComponent}_zero`, boolean>
export type GrossStock = { symbol: string; name: string; exchange: string; currency: string; security_type: string; series: Record<GrossInvestor, Record<string, GrossWindow>> }
type GrossPolicy = { scope: { daily_dates: string[]; symbols: string[]; identities: Record<string, string> }; calendar: { adopted_dates: string[]; from: string; closed_dates: string[]; observation_date: string }; rights: { attribution: string }; sources: { exact_urls: string[]; daily: { header: string[]; source_version: string }; index: { source_version: string } } }
type CalendarRow = Pick<GrossPoint, 'date' | 'row_ordinal' | 'source_values' | 'receipt_sha256' | 'body_sha256'>
export type GrossRead = { schema: string; calculation_version: string; profile: string; policy_version: string; policy_digest: string; policy: GrossPolicy; as_of: string; generation: string; available: boolean; count: number | null; reason: string | null; stocks: GrossStock[]; receipts: { original: Record<string, unknown>; canonical: string; sha256: string }[]; calendar: { original_dates: string[]; adopted_dates: string[]; rows: CalendarRow[]; post_cutoff_excluded: string[] } }
const MIN = -(2n ** 63n), MAX = 2n ** 63n - 1n
const shaPattern = /^[0-9a-f]{64}$/
const integerPattern = /^(?:0|-?[1-9][0-9]*)$/
export function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(canonicalJson).join(',') + ']'
  if (value !== null && typeof value === 'object') return '{' + Object.keys(value).sort().map((key) => JSON.stringify(key) + ':' + canonicalJson((value as Record<string, unknown>)[key])).join(',') + '}'
  return JSON.stringify(value)
}
async function sha(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text)
  return Array.from(new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', bytes)), (n) => n.toString(16).padStart(2, '0')).join('')
}
export function grossInteger(value: unknown): bigint | null {
  if (typeof value !== 'string' || value.length > 20 || !integerPattern.test(value)) return null
  const n = BigInt(value)
  return n >= MIN && n <= MAX ? n : null
}
export function grossLots(value: string): string {
  const n = BigInt(value), abs = n < 0n ? -n : n
  const remainder = abs % 1000n
  return (n < 0n ? '-' : '') + String(abs / 1000n) + (remainder ? '.' + String(remainder).padStart(3, '0').replace(/0+$/, '') : '')
}
export function grossControls(params: URLSearchParams): GrossControls {
  return { as_of: params.get('as_of') ?? '2026-10-06', investor: params.get('investor') ?? 'foreign', horizon: params.get('horizon') ?? '20' }
}
export function validGrossControls(c: GrossControls): boolean {
  return c.as_of === '2026-10-06' && GROSS_INVESTORS.includes(c.investor as GrossInvestor) && ['5', '20'].includes(c.horizon)
}
export function grossPath(c: GrossControls, symbol?: string): string {
  const params = new URLSearchParams(c)
  return GROSS_ROUTE + (symbol ? '/' + symbol : '') + '?' + params.toString()
}
function equals(a: unknown, b: unknown): boolean { return canonicalJson(a) === canonicalJson(b) }
function assert(ok: unknown): asserts ok { if (!ok) throw new Error('series_evidence_invalid') }
function utcMicroseconds(value: unknown): bigint {
  assert(typeof value === 'string')
  const match = /^(2026-10-08T[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.([0-9]{1,6}))?(?:Z|\+00:00)$/.exec(value)
  assert(match && Number.isFinite(Date.parse(match[1] + 'Z')))
  return BigInt(Date.parse(match[1] + 'Z')) * 1000n + BigInt((match[2] ?? '').padEnd(6, '0') || '0')
}
function checkedRaw(point: GrossPoint, symbol: string, header: string[], day: string): Record<GrossInvestor, bigint[]> {
  const row = point.source_values
  assert(Array.isArray(row) && row.length === 25 && header.length === 25 && row.every((x) => typeof x === 'string'))
  assert(row[0] === String(Number(day.slice(0, 4)) - 1911) + day.slice(5, 7) + day.slice(8) && row[1] === symbol && row[2].trim() === GROSS_NAMES[symbol])
  const groups = [3, 6, 9, 12, 15, 18, 21].map((start) => {
    const buy = grossInteger(row[start]), sell = grossInteger(row[start + 1]), net = grossInteger(row[start + 2])
    assert(buy !== null && sell !== null && net !== null && buy >= 0n && sell >= 0n && buy - sell === net)
    return [buy, sell, net]
  })
  assert(groups[2].every((v, i) => v === groups[0][i] + groups[1][i]) && groups[6].every((v, i) => v === groups[4][i] + groups[5][i]))
  assert(grossInteger(row[24]) === groups[0][2] + groups[3][2] + groups[6][2])
  return { foreign: groups[0], trust: groups[3], dealer: groups[6] }
}
/** Verify the whole seven-stock graph before returning any series or zero. */
export async function validateGross(value: unknown): Promise<GrossRead | null> {
  try {
    const v = value as GrossRead
    assert(v && v.available === true && v.count === 7 && v.reason === null && v.schema === GROSS_SCHEMA && v.profile === GROSS_PROFILE && v.policy_version === GROSS_VERSION && v.policy_digest === GROSS_PIN && v.calculation_version === GROSS_CALCULATION && v.as_of === '2026-10-06' && typeof v.generation === 'string' && v.generation.length > 0)
    const canonicalPolicy = canonicalJson(v.policy)
    assert(new TextEncoder().encode(canonicalPolicy).length === 10654 && 'sha256:' + await sha(canonicalPolicy) === GROSS_PIN)
    assert(equals(v.policy.scope.symbols, GROSS_SYMBOLS) && equals(v.policy.scope.identities, GROSS_NAMES))
    assert(Array.isArray(v.receipts) && v.receipts.length === 22)
    let previousTime = 0n, bodyTotal = 0
    const receipts = new Map<string, Record<string, unknown>>()
    for (let i = 0; i < v.receipts.length; i++) {
      const receipt = v.receipts[i], r = receipt.original
      assert(receipt.canonical === canonicalJson(r) && shaPattern.test(receipt.sha256) && await sha(receipt.canonical) === receipt.sha256)
      assert(r.ordinal === i && r.schema === 'tpex-institutional-gross-capture/chips-stock-scope-7-v1' && r.url === v.policy.sources.exact_urls[i] && r.method === 'GET' && r.request_body_bytes === 0 && r.http_status === 200 && r.content_encoding === 'identity' && r.policy_digest === GROSS_PIN && r.policy_version === GROSS_VERSION && r.profile === GROSS_PROFILE && r.request_count === 1)
      assert(r.source_version === (i < 2 ? v.policy.sources.index.source_version : v.policy.sources.daily.source_version))
      assert(typeof r.body_sha256 === 'string' && shaPattern.test(r.body_sha256) && typeof r.body_bytes === 'number' && Number.isInteger(r.body_bytes) && r.body_bytes > 0 && r.body_bytes <= (i < 2 ? 1048576 : 2097152))
      bodyTotal += r.body_bytes
      assert(bodyTotal <= 44040192)
      assert(typeof r.content_type === 'string' && /^(?:text|application)\/csv(?:;charset=utf-8)?$/i.test(r.content_type.replace(/ /g, '')))
      assert(typeof r.request_started_at === 'string' && typeof r.captured_at === 'string' && /(?:Z|\+00:00)$/.test(r.request_started_at) && /(?:Z|\+00:00)$/.test(r.captured_at))
      const start = utcMicroseconds(r.request_started_at), end = utcMicroseconds(r.captured_at)
      assert(start >= previousTime && end >= start)
      previousTime = end
      assert(r.publication_time === 'unknown' && r.first_available_time === 'unknown' && r.revision_time === 'unknown' && r.historical_pit === 'unsupported')
      assert(r.source === (i < 2 ? 'index' : 'daily') && r.requested_date === (i < 2 ? ['2026-09-01', '2026-10-01'][i] : v.policy.scope.daily_dates[i - 2]))
      receipts.set(receipt.sha256, r)
    }
    assert(v.calendar && equals(v.calendar.adopted_dates, v.policy.calendar.adopted_dates))
    assert(Array.isArray(v.calendar.rows) && equals(v.calendar.rows.map((r) => r.date), v.calendar.original_dates))
    assert(equals([...new Set(v.calendar.original_dates)].sort(), v.calendar.original_dates))
    assert(equals(v.calendar.original_dates.filter((d) => d <= v.as_of), v.calendar.adopted_dates))
    assert(equals(v.calendar.original_dates.filter((d) => d > v.as_of), v.calendar.post_cutoff_excluded))
    const expectedCalendar: string[] = []
    for (let instant = Date.parse(v.policy.calendar.from + 'T00:00:00Z'); instant <= Date.parse(v.as_of + 'T00:00:00Z'); instant += 86400000) {
      const date = new Date(instant), day = date.toISOString().slice(0, 10)
      if (![0, 6].includes(date.getUTCDay()) && !v.policy.calendar.closed_dates.includes(day)) expectedCalendar.push(day)
    }
    assert(equals(expectedCalendar, v.calendar.adopted_dates) && equals(expectedCalendar.slice(-20), v.policy.scope.daily_dates))
    for (const row of v.calendar.rows) {
      const receipt = receipts.get(row.receipt_sha256)
      assert(receipt && receipt.source === 'index' && receipt.requested_date === row.date.slice(0, 7) + '-01' && receipt.body_sha256 === row.body_sha256 && Number.isInteger(row.row_ordinal) && row.row_ordinal > 0 && row.source_values.length === 6 && row.source_values.every((x) => typeof x === 'string') && row.source_values[0] === row.date.replace(/-/g, ''))
      const date = new Date(row.date + 'T00:00:00Z')
      assert(/^2026-(09|10)-[0-9]{2}$/.test(row.date) && Number.isFinite(date.valueOf()) && date.toISOString().slice(0, 10) === row.date && ![0, 6].includes(date.getUTCDay()) && !v.policy.calendar.closed_dates.includes(row.date) && row.date <= v.policy.calendar.observation_date)
      const decimal = (s: string) => { assert(/^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)$/.test(s)); const n = Number(s); assert(Number.isFinite(n)); return n }
      const [open, high, low, close] = row.source_values.slice(1, 5).map(decimal)
      decimal(row.source_values[5])
      assert(open > 0 && high > 0 && low > 0 && close > 0 && low <= Math.min(open, close) && Math.max(open, close) <= high)
    }
    assert(v.stocks.length === 7 && equals(v.stocks.map((s) => s.symbol), GROSS_SYMBOLS))
    for (const stock of v.stocks) {
      assert(stock.name === GROSS_NAMES[stock.symbol] && stock.exchange === 'TPEx' && stock.currency === 'TWD' && stock.security_type === 'stock')
      for (const investor of GROSS_INVESTORS) {
        for (const horizon of ['5', '20']) {
          const window = stock.series[investor][horizon], dates = v.policy.scope.daily_dates.slice(-Number(horizon))
          assert(window.horizon === Number(horizon) && window.points.length === Number(horizon))
          const prefix = [0n, 0n, 0n], total = [0n, 0n, 0n]
          for (let i = 0; i < window.points.length; i++) {
            const point = window.points[i], receipt = receipts.get(point.receipt_sha256)
            assert(point.date === dates[i] && Number.isInteger(point.row_ordinal) && point.row_ordinal > 0 && receipt && receipt.source === 'daily' && receipt.requested_date === point.date && receipt.body_sha256 === point.body_sha256)
            const values = checkedRaw(point, stock.symbol, v.policy.sources.daily.header, point.date)[investor]
            for (const [j, component] of (['buy', 'sell', 'net'] as const).entries()) {
              const shares = point[`${component}_shares`], cumulative = point[`cumulative_${component}_shares`]
              assert(grossInteger(shares) === values[j])
              prefix[j] += values[j]; total[j] += values[j]
              assert(prefix[j] >= MIN && prefix[j] <= MAX && grossInteger(cumulative) === prefix[j] && point[`${component}_lots`] === grossLots(shares) && point[`cumulative_${component}_lots`] === grossLots(cumulative))
            }
            assert(prefix[0] - prefix[1] === prefix[2])
          }
          for (const [j, component] of (['buy', 'sell', 'net'] as const).entries()) {
            assert(total[j] >= MIN && total[j] <= MAX && grossInteger(window[`total_${component}_shares`]) === total[j] && window[`total_${component}_lots`] === grossLots(window[`total_${component}_shares`]) && window[`verified_${component}_zero`] === (total[j] === 0n))
          }
          assert(total[0] - total[1] === total[2])
          const full = stock.series[investor]['20']
          assert(equals(window.points.map((p) => [p.date, p.buy_shares, p.sell_shares, p.net_shares, p.source_values, p.row_ordinal, p.receipt_sha256, p.body_sha256]), full.points.slice(-Number(horizon)).map((p) => [p.date, p.buy_shares, p.sell_shares, p.net_shares, p.source_values, p.row_ordinal, p.receipt_sha256, p.body_sha256])))
          assert(equals(window.points.map((p) => [p.date, p.source_values, p.row_ordinal, p.receipt_sha256, p.body_sha256]), stock.series.foreign[horizon].points.map((p) => [p.date, p.source_values, p.row_ordinal, p.receipt_sha256, p.body_sha256])))
        }
      }
    }
    return v
  } catch { return null }
}
export function grossGeometry(points: GrossPoint[], cumulative = false, component: 'buy' | 'sell' = 'buy', sharedBound?: number): { zero: number; values: { x: number; y: number }[] } {
  // Approximation is confined to SVG geometry; exact values remain strings/BigInt.
  const nums = points.map((p) => Number(cumulative ? p[`cumulative_${component}_shares`] : p[`${component}_shares`]))
  const bound = sharedBound ?? Math.max(1, ...nums)
  return { zero: 150, values: nums.map((n, i) => ({ x: 30 + (points.length === 1 ? 0 : i * 640 / (points.length - 1)), y: 150 - n / bound * 120 })) }
}
