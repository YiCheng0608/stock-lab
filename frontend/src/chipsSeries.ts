export const SERIES_ROUTE = '/chips-stock-scope-7-daily-net-trend'
export const SERIES_API = '/api/chips/series-stock-scope-7'
export const SERIES_PIN = 'sha256:143aabb4cd2d86110d5564793ce77b0fb6c60b3e603f23c1e188875934a48a31'
export const SERIES_VERSION = 'm1-chips-daily-net-series-stock-scope-7-tpex-2026-10-06.1'
export const SERIES_PROFILE = 'free_public_local_chips_only_daily_net_series_stock_scope_7'
export const SERIES_SCHEMA = 'institutional-daily-net-series-read/chips-stock-scope-7-v1'
export const SERIES_CALCULATION = 'signed-daily-net-running-sum/window-reset-int64-v1'
export const SERIES_NAMES: Record<string, string> = { '3105': '穩懋', '3293': '鈊象', '5274': '信驊', '5347': '世界', '6488': '環球晶', '6510': '精測', '8069': '元太' }
export const SERIES_SYMBOLS = ['3105', '3293', '5274', '5347', '6488', '6510', '8069']
export const SERIES_INVESTORS = ['foreign', 'trust', 'dealer'] as const
export type SeriesInvestor = typeof SERIES_INVESTORS[number]
export type SeriesControls = { as_of: string; investor: string; horizon: string }
export type SeriesPoint = { date: string; row_ordinal: number; source_values: string[]; receipt_sha256: string; body_sha256: string; net_shares: string; net_lots: string; cumulative_shares: string; cumulative_lots: string }
export type SeriesWindow = { horizon: number; points: SeriesPoint[]; total_shares: string; total_lots: string; verified_zero: boolean }
export type SeriesStock = { symbol: string; name: string; exchange: string; currency: string; security_type: string; series: Record<SeriesInvestor, Record<string, SeriesWindow>> }
type SeriesPolicy = { scope: { daily_dates: string[]; symbols: string[]; identities: Record<string, string> }; calendar: { original_dates: string[]; adopted_dates: string[] }; sources: { exact_urls: string[]; daily: { header: string[]; source_version: string }; index: { source_version: string } } }
type CalendarRow = Pick<SeriesPoint, 'date' | 'row_ordinal' | 'source_values' | 'receipt_sha256' | 'body_sha256'>
export type SeriesRead = { schema: string; calculation_version: string; profile: string; policy_version: string; policy_digest: string; policy: SeriesPolicy; as_of: string; generation: string; available: boolean; count: number | null; reason: string | null; stocks: SeriesStock[]; receipts: { original: Record<string, unknown>; canonical: string; sha256: string }[]; calendar: { original_dates: string[]; adopted_dates: string[]; rows: CalendarRow[]; post_cutoff_excluded: string[] } }
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
export function seriesInteger(value: unknown): bigint | null {
  if (typeof value !== 'string' || value.length > 20 || !integerPattern.test(value)) return null
  const n = BigInt(value)
  return n >= MIN && n <= MAX ? n : null
}
export function seriesLots(value: string): string {
  const n = BigInt(value), abs = n < 0n ? -n : n
  const remainder = abs % 1000n
  return (n < 0n ? '-' : '') + String(abs / 1000n) + (remainder ? '.' + String(remainder).padStart(3, '0').replace(/0+$/, '') : '')
}
export function seriesControls(params: URLSearchParams): SeriesControls {
  return { as_of: params.get('as_of') ?? '2026-10-06', investor: params.get('investor') ?? 'foreign', horizon: params.get('horizon') ?? '20' }
}
export function validSeriesControls(c: SeriesControls): boolean {
  return c.as_of === '2026-10-06' && SERIES_INVESTORS.includes(c.investor as SeriesInvestor) && ['5', '20'].includes(c.horizon)
}
export function seriesPath(c: SeriesControls, symbol?: string): string {
  const params = new URLSearchParams(c)
  return SERIES_ROUTE + (symbol ? '/' + symbol : '') + '?' + params.toString()
}
function equals(a: unknown, b: unknown): boolean { return canonicalJson(a) === canonicalJson(b) }
function assert(ok: unknown): asserts ok { if (!ok) throw new Error('series_evidence_invalid') }
function utcMicroseconds(value: unknown): bigint {
  assert(typeof value === 'string')
  const match = /^(2026-10-07T[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.([0-9]{1,6}))?(?:Z|\+00:00)$/.exec(value)
  assert(match && Number.isFinite(Date.parse(match[1] + 'Z')))
  return BigInt(Date.parse(match[1] + 'Z')) * 1000n + BigInt((match[2] ?? '').padEnd(6, '0') || '0')
}
function checkedRaw(point: SeriesPoint, symbol: string, header: string[], day: string): Record<SeriesInvestor, bigint> {
  const row = point.source_values
  assert(Array.isArray(row) && row.length === 25 && header.length === 25 && row.every((x) => typeof x === 'string'))
  assert(row[0] === String(Number(day.slice(0, 4)) - 1911) + day.slice(5, 7) + day.slice(8) && row[1] === symbol && row[2].trim() === SERIES_NAMES[symbol])
  const groups = [3, 6, 9, 12, 15, 18, 21].map((start) => {
    const buy = seriesInteger(row[start]), sell = seriesInteger(row[start + 1]), net = seriesInteger(row[start + 2])
    assert(buy !== null && sell !== null && net !== null && buy >= 0n && sell >= 0n && buy - sell === net)
    return [buy, sell, net]
  })
  assert(groups[2].every((v, i) => v === groups[0][i] + groups[1][i]) && groups[6].every((v, i) => v === groups[4][i] + groups[5][i]))
  assert(seriesInteger(row[24]) === groups[0][2] + groups[3][2] + groups[6][2])
  return { foreign: groups[0][2], trust: groups[3][2], dealer: groups[6][2] }
}
/** Verify the whole seven-stock graph before returning any series or zero. */
export async function validateSeries(value: unknown): Promise<SeriesRead | null> {
  try {
    const v = value as SeriesRead
    assert(v && v.available === true && v.count === 7 && v.reason === null && v.schema === SERIES_SCHEMA && v.profile === SERIES_PROFILE && v.policy_version === SERIES_VERSION && v.policy_digest === SERIES_PIN && v.calculation_version === SERIES_CALCULATION && v.as_of === '2026-10-06' && typeof v.generation === 'string' && v.generation.length > 0)
    const canonicalPolicy = canonicalJson(v.policy)
    assert(new TextEncoder().encode(canonicalPolicy).length === 9733 && 'sha256:' + await sha(canonicalPolicy) === SERIES_PIN)
    assert(equals(v.policy.scope.symbols, SERIES_SYMBOLS) && equals(v.policy.scope.identities, SERIES_NAMES))
    assert(Array.isArray(v.receipts) && v.receipts.length === 22)
    let previousTime = 0n, bodyTotal = 0
    const receipts = new Map<string, Record<string, unknown>>()
    for (let i = 0; i < v.receipts.length; i++) {
      const receipt = v.receipts[i], r = receipt.original
      assert(receipt.canonical === canonicalJson(r) && shaPattern.test(receipt.sha256) && await sha(receipt.canonical) === receipt.sha256)
      assert(r.ordinal === i && r.schema === 'tpex-institutional-series-capture/chips-stock-scope-7-v1' && r.url === v.policy.sources.exact_urls[i] && r.method === 'GET' && r.request_body_bytes === 0 && r.http_status === 200 && r.content_encoding === 'identity' && r.policy_digest === SERIES_PIN && r.policy_version === SERIES_VERSION && r.profile === SERIES_PROFILE && r.request_count === 1)
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
    assert(v.calendar && equals(v.calendar.original_dates, v.policy.calendar.original_dates) && equals(v.calendar.adopted_dates, v.policy.calendar.adopted_dates) && equals(v.calendar.post_cutoff_excluded, ['2026-10-07']))
    assert(v.calendar.rows.length === 25 && equals(v.calendar.rows.map((r) => r.date), v.calendar.original_dates))
    for (const row of v.calendar.rows) {
      const receipt = receipts.get(row.receipt_sha256)
      assert(receipt && receipt.source === 'index' && receipt.requested_date === row.date.slice(0, 7) + '-01' && receipt.body_sha256 === row.body_sha256 && Number.isInteger(row.row_ordinal) && row.row_ordinal > 0 && row.source_values.length === 6 && row.source_values.every((x) => typeof x === 'string') && row.source_values[0] === row.date.replace(/-/g, ''))
    }
    assert(v.stocks.length === 7 && equals(v.stocks.map((s) => s.symbol), SERIES_SYMBOLS))
    for (const stock of v.stocks) {
      assert(stock.name === SERIES_NAMES[stock.symbol] && stock.exchange === 'TPEx' && stock.currency === 'TWD' && stock.security_type === 'stock')
      for (const investor of SERIES_INVESTORS) {
        for (const horizon of ['5', '20']) {
          const window = stock.series[investor][horizon], dates = v.policy.scope.daily_dates.slice(-Number(horizon))
          assert(window.horizon === Number(horizon) && window.points.length === Number(horizon))
          let prefix = 0n, total = 0n
          for (let i = 0; i < window.points.length; i++) {
            const point = window.points[i], receipt = receipts.get(point.receipt_sha256)
            assert(point.date === dates[i] && Number.isInteger(point.row_ordinal) && point.row_ordinal > 0 && receipt && receipt.source === 'daily' && receipt.requested_date === point.date && receipt.body_sha256 === point.body_sha256)
            const nets = checkedRaw(point, stock.symbol, v.policy.sources.daily.header, point.date), net = seriesInteger(point.net_shares)
            assert(net !== null && net === nets[investor])
            prefix += net; total += net
            assert(prefix >= MIN && prefix <= MAX && seriesInteger(point.cumulative_shares) === prefix && point.net_lots === seriesLots(point.net_shares) && point.cumulative_lots === seriesLots(point.cumulative_shares))
          }
          assert(total >= MIN && total <= MAX && seriesInteger(window.total_shares) === total && window.total_lots === seriesLots(window.total_shares) && window.verified_zero === (total === 0n))
          const full = stock.series[investor]['20']
          assert(equals(window.points.map((p) => [p.date, p.net_shares, p.source_values, p.row_ordinal, p.receipt_sha256, p.body_sha256]), full.points.slice(-Number(horizon)).map((p) => [p.date, p.net_shares, p.source_values, p.row_ordinal, p.receipt_sha256, p.body_sha256])))
          assert(equals(window.points.map((p) => [p.date, p.source_values, p.row_ordinal, p.receipt_sha256, p.body_sha256]), stock.series.foreign[horizon].points.map((p) => [p.date, p.source_values, p.row_ordinal, p.receipt_sha256, p.body_sha256])))
        }
      }
    }
    return v
  } catch { return null }
}
export function seriesGeometry(points: SeriesPoint[], cumulative = false): { zero: number; values: { x: number; y: number }[] } {
  // Approximation is confined to SVG geometry; exact values remain strings/BigInt.
  const nums = points.map((p) => Number(cumulative ? p.cumulative_shares : p.net_shares))
  const bound = Math.max(1, ...nums.map(Math.abs))
  return { zero: 80, values: nums.map((n, i) => ({ x: 30 + (points.length === 1 ? 0 : i * 640 / (points.length - 1)), y: 80 - n / bound * 64 })) }
}
