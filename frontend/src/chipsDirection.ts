import { canonicalJson, grossInteger, grossLots } from './chipsGross'

export const DIRECTION_ROUTE = '/chips-stock-scope-7-direction-segments'
export const DIRECTION_API = '/api/chips/direction-stock-scope-7'
export const DIRECTION_PIN = 'sha256:eb7a4dd688907855dd91250bfbec96b4dd8b2cb65085dce49e7e12c3a80c5348'
export const DIRECTION_VERSION = 'm1-chips-direction-segments-stock-scope-7-tpex-2026-10-06.1'
export const DIRECTION_PROFILE = 'free_public_local_chips_only_direction_segments_stock_scope_7'
export const DIRECTION_SCHEMA = 'institutional-direction-segments-read/chips-stock-scope-7-v1'
export const DIRECTION_WORKER_SCHEMA = 'tpex-institutional-direction/chips-stock-scope-7-v1'
export const DIRECTION_CAPTURE_SCHEMA = 'tpex-institutional-direction-capture/chips-stock-scope-7-v1'
export const DIRECTION_CALENDAR_SCHEMA = 'institutional-direction-calendar/chips-stock-scope-7-v1'
export const DIRECTION_CALENDAR_VERSION = 'dataset-11391-month-csv-observed-2026-10-08/chips-direction-segments-stock-scope-7-v1'
export const DIRECTION_CALCULATION = 'net-sign-triples-counts-contiguous-segments/window-limited-int64-v1'
export const DIRECTION_NAMES: Record<string, string> = { '3105': '穩懋', '3293': '鈊象', '5274': '信驊', '5347': '世界', '6488': '環球晶', '6510': '精測', '8069': '元太' }
export const DIRECTION_SYMBOLS = ['3105', '3293', '5274', '5347', '6488', '6510', '8069']
export const DIRECTION_INVESTORS = ['foreign', 'trust', 'dealer'] as const
export const DIRECTION_SIGNS = ['positive', 'negative', 'zero'] as const
export const DIRECTION_CATEGORIES = ['all_positive', 'all_negative', 'opposite', 'single_direction_with_zero', 'all_zero'] as const
export type DirectionInvestor = typeof DIRECTION_INVESTORS[number]
export type DirectionSign = typeof DIRECTION_SIGNS[number]
export type DirectionCategory = typeof DIRECTION_CATEGORIES[number]
export type DirectionControls = { as_of: string; investor: string; horizon: string }
export type DirectionTrace = { date: string; row_ordinal: number; source_values: string[]; receipt_sha256: string; body_sha256: string }
export type DirectionPoint = DirectionTrace & { net_shares: Record<DirectionInvestor, string>; net_lots: Record<DirectionInvestor, string>; signs: Record<DirectionInvestor, DirectionSign>; category: DirectionCategory }
export type DirectionSegment = { sign: DirectionSign; start_index: number; end_index: number; start_date: string; end_date: string; length: number; earlier_unknown: boolean }
export type DirectionStats = { counts: Record<DirectionSign, number>; segments: DirectionSegment[]; latest_run: DirectionSegment }
export type DirectionWindow = { horizon: number; points: DirectionPoint[]; direction_counts: Record<DirectionCategory, number>; investors: Record<DirectionInvestor, DirectionStats> }
export type DirectionStock = { symbol: string; name: string; exchange: string; currency: string; security_type: string; windows: Record<string, DirectionWindow> }
export type DirectionPolicy = { worker_schema: string; capture_schema: string; calendar_schema: string; calendar_version: string; scope: { daily_dates: string[]; symbols: string[]; identities: Record<string, string> }; calendar: { adopted_dates: string[]; from: string; closed_dates: string[]; observation_date: string }; rights: { attribution: string }; sources: { exact_urls: string[]; daily: { header: string[]; source_version: string }; index: { source_version: string } } }
export type DirectionRead = { schema: string; worker_schema: string; capture_schema: string; calendar_schema: string; calendar_version: string; calculation_version: string; profile: string; policy_version: string; policy_digest: string; policy: DirectionPolicy; as_of: string; generation: string; available: boolean; count: number | null; reason: string | null; stocks: DirectionStock[]; receipts: { original: Record<string, unknown>; canonical: string; sha256: string }[]; calendar: { schema: string; version: string; original_dates: string[]; adopted_dates: string[]; rows: DirectionTrace[]; post_cutoff_excluded: string[] } }

const equals = (a: unknown, b: unknown) => canonicalJson(a) === canonicalJson(b)
function assert(ok: unknown): asserts ok { if (!ok) throw new Error('direction_evidence_invalid') }
const shaPattern = /^[0-9a-f]{64}$/
async function sha(text: string): Promise<string> {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))), (n) => n.toString(16).padStart(2, '0')).join('')
}
function utcMicroseconds(value: unknown): bigint {
  assert(typeof value === 'string')
  const match = /^(2026-10-08T[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.([0-9]{1,6}))?(?:Z|\+00:00)$/.exec(value)
  assert(match && Number.isFinite(Date.parse(match[1] + 'Z')))
  return BigInt(Date.parse(match[1] + 'Z')) * 1000n + BigInt((match[2] ?? '').padEnd(6, '0') || '0')
}
export function directionControls(params: URLSearchParams): DirectionControls {
  return { as_of: params.get('as_of') ?? '2026-10-06', investor: params.get('investor') ?? 'foreign', horizon: params.get('horizon') ?? '20' }
}
export function validDirectionControls(c: DirectionControls): boolean {
  return c.as_of === '2026-10-06' && DIRECTION_INVESTORS.includes(c.investor as DirectionInvestor) && ['5', '20'].includes(c.horizon)
}
export function directionPath(c: DirectionControls, symbol?: string): string {
  return DIRECTION_ROUTE + (symbol ? '/' + symbol : '') + '?' + new URLSearchParams(c).toString()
}
export function directionSign(n: bigint): DirectionSign { return n > 0n ? 'positive' : n < 0n ? 'negative' : 'zero' }
export function directionCategory(nets: bigint[]): DirectionCategory {
  assert(nets.length === 3)
  const signs = nets.map(directionSign)
  if (signs.every((s) => s === 'positive')) return 'all_positive'
  if (signs.every((s) => s === 'negative')) return 'all_negative'
  if (signs.includes('positive') && signs.includes('negative')) return 'opposite'
  return signs.every((s) => s === 'zero') ? 'all_zero' : 'single_direction_with_zero'
}
export function directionStats(points: DirectionPoint[], investor: DirectionInvestor): DirectionStats {
  const counts = { positive: 0, negative: 0, zero: 0 }, segments: DirectionSegment[] = []
  for (const [i, point] of points.entries()) {
    const net = grossInteger(point.net_shares[investor])
    assert(net !== null)
    const sign = directionSign(net)
    counts[sign]++
    const last = segments.at(-1)
    if (last?.sign === sign) { last.end_index = i; last.end_date = point.date; last.length++ }
    else segments.push({ sign, start_index: i, end_index: i, start_date: point.date, end_date: point.date, length: 1, earlier_unknown: i === 0 })
  }
  assert(segments.length > 0)
  return { counts, segments, latest_run: { ...segments[segments.length - 1] } }
}
function rawNets(point: DirectionPoint, symbol: string, day: string): Record<DirectionInvestor, bigint> {
  const row = point.source_values
  assert(Array.isArray(row) && row.length === 25 && row.every((x) => typeof x === 'string'))
  assert(row[0] === String(Number(day.slice(0, 4)) - 1911) + day.slice(5, 7) + day.slice(8) && row[1] === symbol && row[2].trim() === DIRECTION_NAMES[symbol])
  const groups = [3, 6, 9, 12, 15, 18, 21].map((start) => {
    const buy = grossInteger(row[start]), sell = grossInteger(row[start + 1]), net = grossInteger(row[start + 2])
    assert(buy !== null && sell !== null && net !== null && buy >= 0n && sell >= 0n && buy - sell === net)
    return [buy, sell, net]
  })
  assert(groups[2].every((n, i) => n === groups[0][i] + groups[1][i]) && groups[6].every((n, i) => n === groups[4][i] + groups[5][i]))
  assert(grossInteger(row[24]) === groups[0][2] + groups[3][2] + groups[6][2])
  return { foreign: groups[0][2], trust: groups[3][2], dealer: groups[6][2] }
}
/** Validate every original-derived triple and all 42 groups before exposing any count or zero. */
export async function validateDirection(value: unknown): Promise<DirectionRead | null> {
  try {
    const v = value as DirectionRead
    assert(v && v.available === true && v.count === 7 && v.reason === null && v.schema === DIRECTION_SCHEMA && v.worker_schema === DIRECTION_WORKER_SCHEMA && v.capture_schema === DIRECTION_CAPTURE_SCHEMA && v.calendar_schema === DIRECTION_CALENDAR_SCHEMA && v.calendar_version === DIRECTION_CALENDAR_VERSION && v.profile === DIRECTION_PROFILE && v.policy_version === DIRECTION_VERSION && v.policy_digest === DIRECTION_PIN && v.calculation_version === DIRECTION_CALCULATION && v.as_of === '2026-10-06' && typeof v.generation === 'string' && v.generation.length > 0)
    const rawPolicy = canonicalJson(v.policy)
    assert(new TextEncoder().encode(rawPolicy).length === 12382 && 'sha256:' + await sha(rawPolicy) === DIRECTION_PIN)
    assert(equals(v.policy.scope.symbols, DIRECTION_SYMBOLS) && equals(v.policy.scope.identities, DIRECTION_NAMES))
    assert(Array.isArray(v.receipts) && v.receipts.length === 22)
    let previous = 0n, bodyTotal = 0
    const receipts = new Map<string, Record<string, unknown>>()
    for (const [i, receipt] of v.receipts.entries()) {
      const r = receipt.original
      assert(receipt.canonical === canonicalJson(r) && shaPattern.test(receipt.sha256) && await sha(receipt.canonical) === receipt.sha256)
      assert(r.ordinal === i && r.schema === DIRECTION_CAPTURE_SCHEMA && r.url === v.policy.sources.exact_urls[i] && r.method === 'GET' && r.request_body_bytes === 0 && r.http_status === 200 && r.content_encoding === 'identity' && r.policy_digest === DIRECTION_PIN && r.policy_version === DIRECTION_VERSION && r.profile === DIRECTION_PROFILE && r.request_count === 1)
      assert(r.source_version === (i < 2 ? v.policy.sources.index.source_version : v.policy.sources.daily.source_version))
      assert(typeof r.body_sha256 === 'string' && shaPattern.test(r.body_sha256) && typeof r.body_bytes === 'number' && Number.isInteger(r.body_bytes) && r.body_bytes > 0 && r.body_bytes <= (i < 2 ? 1048576 : 2097152))
      bodyTotal += r.body_bytes; assert(bodyTotal <= 44040192)
      assert(typeof r.content_type === 'string' && /^(?:text|application)\/csv(?:;charset=utf-8)?$/i.test(r.content_type.replace(/ /g, '')))
      const start = utcMicroseconds(r.request_started_at), end = utcMicroseconds(r.captured_at)
      assert(start >= previous && end >= start); previous = end
      assert(r.publication_time === 'unknown' && r.first_available_time === 'unknown' && r.revision_time === 'unknown' && r.historical_pit === 'unsupported')
      assert(r.source === (i < 2 ? 'index' : 'daily') && r.requested_date === (i < 2 ? ['2026-09-01', '2026-10-01'][i] : v.policy.scope.daily_dates[i - 2]))
      receipts.set(receipt.sha256, r)
    }
    assert(v.calendar.schema === DIRECTION_CALENDAR_SCHEMA && v.calendar.version === DIRECTION_CALENDAR_VERSION)
    assert(Array.isArray(v.calendar.rows) && equals(v.calendar.rows.map((r) => r.date), v.calendar.original_dates))
    assert(equals([...new Set(v.calendar.original_dates)].sort(), v.calendar.original_dates))
    assert(equals(v.calendar.adopted_dates, v.policy.calendar.adopted_dates))
    assert(equals(v.calendar.original_dates.filter((d) => d <= v.as_of), v.calendar.adopted_dates) && equals(v.calendar.original_dates.filter((d) => d > v.as_of), v.calendar.post_cutoff_excluded))
    const expectedDates: string[] = []
    for (let instant = Date.parse(v.policy.calendar.from + 'T00:00:00Z'); instant <= Date.parse(v.as_of + 'T00:00:00Z'); instant += 86400000) {
      const day = new Date(instant).toISOString().slice(0, 10)
      if (![0, 6].includes(new Date(instant).getUTCDay()) && !v.policy.calendar.closed_dates.includes(day)) expectedDates.push(day)
    }
    assert(equals(expectedDates, v.calendar.adopted_dates) && equals(expectedDates.slice(-20), v.policy.scope.daily_dates))
    for (const row of v.calendar.rows) {
      const receipt = receipts.get(row.receipt_sha256)
      assert(receipt && receipt.source === 'index' && receipt.requested_date === row.date.slice(0, 7) + '-01' && receipt.body_sha256 === row.body_sha256 && Number.isInteger(row.row_ordinal) && row.row_ordinal > 0 && row.source_values.length === 6 && row.source_values.every((x) => typeof x === 'string') && row.source_values[0] === row.date.replace(/-/g, ''))
      const date = new Date(row.date + 'T00:00:00Z')
      assert(/^2026-(09|10)-[0-9]{2}$/.test(row.date) && Number.isFinite(date.valueOf()) && date.toISOString().slice(0, 10) === row.date && ![0, 6].includes(date.getUTCDay()) && !v.policy.calendar.closed_dates.includes(row.date) && row.date <= v.policy.calendar.observation_date)
      const decimal = (s: string) => { assert(/^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/.test(s)); const n = Number(s); assert(Number.isFinite(n)); return n }
      const [open, high, low, close] = row.source_values.slice(1, 5).map(decimal); decimal(row.source_values[5])
      assert(open > 0 && high > 0 && low > 0 && close > 0 && low <= Math.min(open, close) && Math.max(open, close) <= high)
    }
    assert(v.stocks.length === 7 && equals(v.stocks.map((s) => s.symbol), DIRECTION_SYMBOLS))
    for (const stock of v.stocks) {
      assert(stock.name === DIRECTION_NAMES[stock.symbol] && stock.exchange === 'TPEx' && stock.security_type === 'stock' && stock.currency === 'TWD')
      for (const horizon of ['5', '20']) {
        const window = stock.windows[horizon], dates = v.policy.scope.daily_dates.slice(-Number(horizon))
        assert(window.horizon === Number(horizon) && window.points.length === Number(horizon))
        const categoryCounts = Object.fromEntries(DIRECTION_CATEGORIES.map((c) => [c, 0])) as Record<DirectionCategory, number>
        for (const [i, point] of window.points.entries()) {
          const receipt = receipts.get(point.receipt_sha256)
          assert(point.date === dates[i] && Number.isInteger(point.row_ordinal) && point.row_ordinal > 0 && receipt && receipt.source === 'daily' && receipt.requested_date === point.date && receipt.body_sha256 === point.body_sha256)
          const values = rawNets(point, stock.symbol, point.date)
          assert(equals(Object.keys(point.net_shares).sort(), [...DIRECTION_INVESTORS].sort()) && equals(Object.keys(point.net_lots).sort(), [...DIRECTION_INVESTORS].sort()) && equals(Object.keys(point.signs).sort(), [...DIRECTION_INVESTORS].sort()))
          for (const investor of DIRECTION_INVESTORS) assert(grossInteger(point.net_shares[investor]) === values[investor] && point.net_lots[investor] === grossLots(point.net_shares[investor]) && point.signs[investor] === directionSign(values[investor]))
          assert(point.category === directionCategory(DIRECTION_INVESTORS.map((i) => values[i])))
          categoryCounts[point.category]++
        }
        assert(equals(window.direction_counts, categoryCounts))
        for (const investor of DIRECTION_INVESTORS) assert(equals(window.investors[investor], directionStats(window.points, investor)))
        assert(equals(window.points, stock.windows['20'].points.slice(-Number(horizon))))
      }
    }
    return v
  } catch { return null }
}
