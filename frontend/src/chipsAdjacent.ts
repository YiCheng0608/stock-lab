import { canonicalJson, grossInteger, grossLots } from './chipsGross'

declare global {
  interface ImportMetaEnv {
    readonly VITE_CHIPS_ADJACENT_STOCK_SCOPE_7?: string
  }
}

export const ADJACENT_ROUTE = '/chips-stock-scope-7-adjacent-windows'
export const ADJACENT_API = '/api/chips/adjacent-stock-scope-7'
export const ADJACENT_PIN = 'sha256:092f86d7fd2797b88f12f92e0474beb120139143ba5c3f3e27edb0c52f5c235e'
export const ADJACENT_VERSION = 'm1-chips-adjacent-windows-stock-scope-7-tpex-2026-10-06.1'
export const ADJACENT_PROFILE = 'free_public_local_chips_only_adjacent_windows_stock_scope_7'
export const ADJACENT_SCHEMA = 'institutional-adjacent-windows-read/chips-stock-scope-7-v1'
export const ADJACENT_WORKER_SCHEMA = 'tpex-institutional-adjacent/chips-stock-scope-7-v1'
export const ADJACENT_CAPTURE_SCHEMA = 'tpex-institutional-adjacent-capture/chips-stock-scope-7-v1'
export const ADJACENT_CALENDAR_SCHEMA = 'institutional-adjacent-calendar/chips-stock-scope-7-v1'
export const ADJACENT_CALENDAR_VERSION = 'dataset-11391-month-csv-observed-2026-10-08/chips-adjacent-windows-stock-scope-7-v1'
export const ADJACENT_CALCULATION = 'adjacent-five-session-counts-net-pairs-deltas/window-limited-int64-v1'
export const ADJACENT_NAMES: Record<string, string> = { '3105': '穩懋', '3293': '鈊象', '5274': '信驊', '5347': '世界', '6488': '環球晶', '6510': '精測', '8069': '元太' }
export const ADJACENT_SYMBOLS = ['3105', '3293', '5274', '5347', '6488', '6510', '8069']
export const ADJACENT_INVESTORS = ['foreign', 'trust', 'dealer'] as const
export const ADJACENT_SIGNS = ['positive', 'negative', 'zero'] as const
export const ADJACENT_WINDOWS = ['previous', 'recent'] as const
export type AdjacentInvestor = typeof ADJACENT_INVESTORS[number]
export type AdjacentSign = typeof ADJACENT_SIGNS[number]
export type AdjacentWindowName = typeof ADJACENT_WINDOWS[number]
export type AdjacentControls = { as_of: string; investor: string; horizon: string }
export type AdjacentTrace = { date: string; row_ordinal: number; source_values: string[]; receipt_sha256: string; body_sha256: string }
export type AdjacentPoint = AdjacentTrace & { net_shares: Record<AdjacentInvestor, string>; net_lots: Record<AdjacentInvestor, string>; signs: Record<AdjacentInvestor, AdjacentSign> }
export type AdjacentSegment = { sign: AdjacentSign; start_index: number; end_index: number; start_date: string; end_date: string; length: number; earlier_unknown: boolean }
export type AdjacentStats = { counts: Record<AdjacentSign, number>; total_shares: string; total_lots: string; verified_zero: boolean; segments: AdjacentSegment[]; latest_run: AdjacentSegment }
export type AdjacentWindow = { horizon: number; points: AdjacentPoint[]; investors: Record<AdjacentInvestor, AdjacentStats> }
export type AdjacentComparison = { net_delta_shares: string; net_delta_lots: string; verified_delta_zero: boolean; count_deltas: Record<AdjacentSign, number> }
export type AdjacentPair = { position: number; previous_date: string; recent_date: string; previous_row_ordinal: number; recent_row_ordinal: number; net_delta_shares: Record<AdjacentInvestor, string>; net_delta_lots: Record<AdjacentInvestor, string> }
export type AdjacentStock = { symbol: string; name: string; exchange: string; currency: string; security_type: string; windows: Record<AdjacentWindowName, AdjacentWindow>; comparisons: Record<AdjacentInvestor, AdjacentComparison>; pairs: AdjacentPair[] }
export type AdjacentPolicy = { scope: { cutoff: string; symbols: string[]; identities: Record<string, string> }; calendar: { from: string; closed_dates: string[]; observation_date: string }; rights: { attribution: string }; sources: { daily: { header: string[]; base_url: string; source_version: string }; index: { header: string[]; base_url: string; requests: string[]; source_version: string } } }
export type AdjacentRead = { schema: string; worker_schema: string; capture_schema: string; calendar_schema: string; calendar_version: string; calculation_version: string; profile: string; policy_version: string; policy_digest: string; policy: AdjacentPolicy; as_of: string; generation: string; available: boolean; count: number | null; reason: string | null; stocks: AdjacentStock[]; receipts: { original: Record<string, unknown>; canonical: string; sha256: string }[]; calendar: { schema: string; version: string; original_dates: string[]; adopted_dates: string[]; daily_dates: string[]; previous_dates: string[]; recent_dates: string[]; rows: AdjacentTrace[]; post_cutoff_excluded: string[] } }

const equals = (a: unknown, b: unknown) => canonicalJson(a) === canonicalJson(b)
function assert(ok: unknown): asserts ok { if (!ok) throw new Error('adjacent_evidence_invalid') }
const MIN = -(2n ** 63n), MAX = 2n ** 63n - 1n
const shaPattern = /^[0-9a-f]{64}$/
export function adjacentBound(n: bigint): bigint { assert(n >= MIN && n <= MAX); return n }
export function adjacentSign(n: bigint): AdjacentSign { adjacentBound(n); return n > 0n ? 'positive' : n < 0n ? 'negative' : 'zero' }
async function sha(text: string): Promise<string> { return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))), (n) => n.toString(16).padStart(2, '0')).join('') }
function utcMicroseconds(value: unknown): bigint {
  assert(typeof value === 'string')
  const match = /^(2026-10-08T[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.([0-9]{1,6}))?(?:Z|\+00:00)$/.exec(value)
  assert(match && Number.isFinite(Date.parse(match[1] + 'Z')))
  const milliseconds = Date.parse(match[1] + 'Z')
  assert(new Date(milliseconds).toISOString().slice(0, 19) === match[1])
  return BigInt(milliseconds) * 1000n + BigInt((match[2] ?? '').padEnd(6, '0') || '0')
}
export function adjacentControls(params: URLSearchParams): AdjacentControls { return { as_of: params.get('as_of') ?? '2026-10-06', investor: params.get('investor') ?? 'foreign', horizon: params.get('horizon') ?? '5' } }
export function validAdjacentParams(params: URLSearchParams): boolean { const keys = [...params.keys()]; return !keys.length || keys.length === 3 && ['as_of', 'investor', 'horizon'].every((key) => params.getAll(key).length === 1) }
export function validAdjacentControls(c: AdjacentControls): boolean { return c.as_of === '2026-10-06' && ADJACENT_INVESTORS.includes(c.investor as AdjacentInvestor) && c.horizon === '5' }
export function adjacentPath(c: AdjacentControls, symbol?: string): string { return ADJACENT_ROUTE + (symbol ? '/' + symbol : '') + '?' + new URLSearchParams(c).toString() }
export function adjacentDailyURL(policy: AdjacentPolicy, day: string): string { return policy.sources.daily.base_url + '&d=' + encodeURIComponent(String(Number(day.slice(0, 4)) - 1911) + '/' + day.slice(5, 7) + '/' + day.slice(8)) }
export function adjacentDates(policy: AdjacentPolicy): string[] {
  const result = []
  for (let time = Date.parse(policy.calendar.from + 'T00:00:00Z'); time <= Date.parse(policy.scope.cutoff + 'T00:00:00Z'); time += 86400000) {
    const date = new Date(time), day = date.toISOString().slice(0, 10)
    if (![0, 6].includes(date.getUTCDay()) && !policy.calendar.closed_dates.includes(day)) result.push(day)
  }
  return result
}
export function adjacentStats(points: AdjacentPoint[], investor: AdjacentInvestor): AdjacentStats {
  assert(points.length === 5)
  const counts = { positive: 0, negative: 0, zero: 0 }, segments: AdjacentSegment[] = []
  let total = 0n
  for (const [index, point] of points.entries()) {
    const n = grossInteger(point.net_shares[investor]); assert(n !== null)
    total = adjacentBound(total + n)
    const sign = adjacentSign(n); counts[sign]++
    const last = segments.at(-1)
    if (last?.sign === sign) { last.end_index = index; last.end_date = point.date; last.length++ }
    else segments.push({ sign, start_index: index, end_index: index, start_date: point.date, end_date: point.date, length: 1, earlier_unknown: index === 0 })
  }
  return { counts, total_shares: String(total), total_lots: grossLots(String(total)), verified_zero: total === 0n, segments, latest_run: { ...segments[segments.length - 1] } }
}
function rawNets(point: AdjacentPoint, symbol: string, day: string): Record<AdjacentInvestor, bigint> {
  const row = point.source_values
  assert(Array.isArray(row) && row.length === 25 && row.every((x) => typeof x === 'string'))
  assert(row[0] === String(Number(day.slice(0, 4)) - 1911) + day.slice(5, 7) + day.slice(8) && row[1] === symbol && row[2].trim() === ADJACENT_NAMES[symbol])
  const groups = [3, 6, 9, 12, 15, 18, 21].map((start) => {
    const buy = grossInteger(row[start]), sell = grossInteger(row[start + 1]), net = grossInteger(row[start + 2])
    assert(buy !== null && sell !== null && net !== null && buy >= 0n && sell >= 0n && adjacentBound(buy - sell) === net)
    return [buy, sell, net]
  })
  assert(groups[2].every((n, i) => n === adjacentBound(groups[0][i] + groups[1][i])) && groups[6].every((n, i) => n === adjacentBound(groups[4][i] + groups[5][i])))
  assert(grossInteger(row[24]) === adjacentBound(adjacentBound(groups[0][2] + groups[3][2]) + groups[6][2]))
  return { foreign: groups[0][2], trust: groups[3][2], dealer: groups[6][2] }
}
/** Verify ALL70 original rows, both windows and every positional pair before showing any zero. */
export async function validateAdjacent(value: unknown): Promise<AdjacentRead | null> {
  try {
    const v = value as AdjacentRead
    assert(v && v.available === true && v.count === 7 && v.reason === null && v.schema === ADJACENT_SCHEMA && v.worker_schema === ADJACENT_WORKER_SCHEMA && v.capture_schema === ADJACENT_CAPTURE_SCHEMA && v.calendar_schema === ADJACENT_CALENDAR_SCHEMA && v.calendar_version === ADJACENT_CALENDAR_VERSION && v.profile === ADJACENT_PROFILE && v.policy_version === ADJACENT_VERSION && v.policy_digest === ADJACENT_PIN && v.calculation_version === ADJACENT_CALCULATION && v.as_of === '2026-10-06' && typeof v.generation === 'string' && v.generation.length > 0)
    const policy = canonicalJson(v.policy)
    assert(new TextEncoder().encode(policy).length === 9284 && 'sha256:' + await sha(policy) === ADJACENT_PIN)
    assert(equals(v.policy.scope.symbols, ADJACENT_SYMBOLS) && equals(v.policy.scope.identities, ADJACENT_NAMES))
    const adopted = adjacentDates(v.policy), dailyDates = adopted.slice(-10)
    assert(dailyDates.length === 10 && v.receipts.length === 12)
    let previousTime = 0n, bodyTotal = 0
    const receipts = new Map<string, Record<string, unknown>>()
    const receiptKeys = ['schema', 'ordinal', 'source', 'source_version', 'requested_date', 'url', 'method', 'request_body_bytes', 'http_status', 'content_type', 'content_encoding', 'body_bytes', 'body_sha256', 'request_started_at', 'captured_at', 'policy_version', 'policy_digest', 'profile', 'publication_time', 'first_available_time', 'revision_time', 'historical_pit', 'request_count'].sort()
    for (const [ordinal, receipt] of v.receipts.entries()) {
      const r = receipt.original, requested = ordinal < 2 ? v.policy.sources.index.requests[ordinal] : dailyDates[ordinal - 2]
      const url = ordinal < 2 ? v.policy.sources.index.base_url + '&date=' + encodeURIComponent(requested.replace(/-/g, '/')) : adjacentDailyURL(v.policy, requested)
      assert(equals(Object.keys(r).sort(), receiptKeys) && receipt.canonical === canonicalJson(r) && shaPattern.test(receipt.sha256) && await sha(receipt.canonical) === receipt.sha256 && !receipts.has(receipt.sha256))
      assert(r.ordinal === ordinal && r.schema === ADJACENT_CAPTURE_SCHEMA && r.url === url && r.method === 'GET' && r.request_body_bytes === 0 && r.http_status === 200 && r.content_encoding === 'identity' && r.policy_digest === ADJACENT_PIN && r.policy_version === ADJACENT_VERSION && r.profile === ADJACENT_PROFILE && r.request_count === 1)
      assert(r.source === (ordinal < 2 ? 'index' : 'daily') && r.requested_date === requested && r.source_version === (ordinal < 2 ? v.policy.sources.index.source_version : v.policy.sources.daily.source_version))
      assert(typeof r.body_sha256 === 'string' && shaPattern.test(r.body_sha256) && typeof r.body_bytes === 'number' && Number.isInteger(r.body_bytes) && r.body_bytes > 0 && r.body_bytes <= (ordinal < 2 ? 1048576 : 2097152))
      bodyTotal += r.body_bytes; assert(bodyTotal <= 23068672)
      assert(typeof r.content_type === 'string' && /^(?:text|application)\/csv(?:;charset=utf-8)?$/i.test(r.content_type.replace(/ /g, '')))
      const start = utcMicroseconds(r.request_started_at), end = utcMicroseconds(r.captured_at)
      assert(start >= previousTime && end >= start); previousTime = end
      assert(r.publication_time === 'unknown' && r.first_available_time === 'unknown' && r.revision_time === 'unknown' && r.historical_pit === 'unsupported')
      receipts.set(receipt.sha256, r)
    }
    const calendar = v.calendar
    assert(calendar.schema === ADJACENT_CALENDAR_SCHEMA && calendar.version === ADJACENT_CALENDAR_VERSION)
    assert(equals(calendar.rows.map((row) => row.date), calendar.original_dates) && equals([...new Set(calendar.original_dates)].sort(), calendar.original_dates))
    assert(equals(calendar.adopted_dates, adopted) && equals(calendar.daily_dates, dailyDates) && equals(calendar.previous_dates, dailyDates.slice(0, 5)) && equals(calendar.recent_dates, dailyDates.slice(5)))
    assert(equals(calendar.original_dates.filter((day) => day <= v.as_of), adopted) && equals(calendar.original_dates.filter((day) => day > v.as_of), calendar.post_cutoff_excluded))
    for (const row of calendar.rows) {
      const receipt = receipts.get(row.receipt_sha256), d = new Date(row.date + 'T00:00:00Z')
      assert(receipt && receipt.source === 'index' && receipt.requested_date === row.date.slice(0, 7) + '-01' && receipt.body_sha256 === row.body_sha256 && Number.isInteger(row.row_ordinal) && row.row_ordinal > 0)
      assert(/^2026-(09|10)-[0-9]{2}$/.test(row.date) && Number.isFinite(d.valueOf()) && d.toISOString().slice(0, 10) === row.date && ![0, 6].includes(d.getUTCDay()) && !v.policy.calendar.closed_dates.includes(row.date) && row.date <= v.policy.calendar.observation_date)
      assert(row.source_values.length === 6 && row.source_values.every((s) => typeof s === 'string') && row.source_values[0] === row.date.replace(/-/g, ''))
      const decimal = (s: string) => { assert(s.length > 0 && s.length <= 64 && s === s.trim() && /^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/.test(s)); const n = Number(s); assert(Number.isFinite(n)); return n }
      const [open, high, low, close] = row.source_values.slice(1, 5).map(decimal); decimal(row.source_values[5])
      assert(open > 0 && high > 0 && low > 0 && close > 0 && low <= Math.min(open, close) && Math.max(open, close) <= high)
    }
    // Original row ordinals must agree with their full, ordered monthly calendar.
    for (const month of v.policy.sources.index.requests) assert(equals(calendar.rows.filter((r) => r.date.startsWith(month.slice(0, 7))).map((r) => r.row_ordinal).sort((a, b) => a - b), calendar.rows.filter((r) => r.date.startsWith(month.slice(0, 7))).map((_, i) => i + 1)))
    assert(v.stocks.length === 7 && equals(v.stocks.map((s) => s.symbol), ADJACENT_SYMBOLS))
    const selectedOrdinals = new Set<string>()
    for (const stock of v.stocks) {
      assert(stock.name === ADJACENT_NAMES[stock.symbol] && stock.exchange === 'TPEx' && stock.security_type === 'stock' && stock.currency === 'TWD' && equals(Object.keys(stock.windows).sort(), [...ADJACENT_WINDOWS].sort()) && equals(Object.keys(stock.comparisons).sort(), [...ADJACENT_INVESTORS].sort()))
      for (const name of ADJACENT_WINDOWS) {
        const window = stock.windows[name], dates = name === 'previous' ? dailyDates.slice(0, 5) : dailyDates.slice(5)
        assert(window.horizon === 5 && window.points.length === 5 && equals(Object.keys(window.investors).sort(), [...ADJACENT_INVESTORS].sort()))
        for (const [index, point] of window.points.entries()) {
          const receipt = receipts.get(point.receipt_sha256)
          assert(point.date === dates[index] && Number.isInteger(point.row_ordinal) && point.row_ordinal > 0 && receipt && receipt.source === 'daily' && receipt.requested_date === point.date && receipt.body_sha256 === point.body_sha256)
          const originalKey = point.receipt_sha256 + '/' + point.row_ordinal
          assert(!selectedOrdinals.has(originalKey)); selectedOrdinals.add(originalKey)
          const values = rawNets(point, stock.symbol, point.date)
          assert([point.net_shares, point.net_lots, point.signs].every((record) => equals(Object.keys(record).sort(), [...ADJACENT_INVESTORS].sort())))
          for (const investor of ADJACENT_INVESTORS) assert(grossInteger(point.net_shares[investor]) === values[investor] && point.net_lots[investor] === grossLots(point.net_shares[investor]) && point.signs[investor] === adjacentSign(values[investor]))
        }
        for (const investor of ADJACENT_INVESTORS) assert(equals(window.investors[investor], adjacentStats(window.points, investor)))
      }
      assert(stock.pairs.length === 5)
      for (const [index, pair] of stock.pairs.entries()) {
        const old = stock.windows.previous.points[index], recent = stock.windows.recent.points[index]
        assert(pair.position === index + 1 && pair.previous_date === old.date && pair.recent_date === recent.date && old.date < recent.date && pair.previous_row_ordinal === old.row_ordinal && pair.recent_row_ordinal === recent.row_ordinal)
        assert([pair.net_delta_shares, pair.net_delta_lots].every((record) => equals(Object.keys(record).sort(), [...ADJACENT_INVESTORS].sort())))
        for (const investor of ADJACENT_INVESTORS) {
          const oldNet = grossInteger(old.net_shares[investor]), newNet = grossInteger(recent.net_shares[investor]); assert(oldNet !== null && newNet !== null)
          const delta = adjacentBound(newNet - oldNet)
          assert(pair.net_delta_shares[investor] === String(delta) && pair.net_delta_lots[investor] === grossLots(String(delta)))
        }
      }
      for (const investor of ADJACENT_INVESTORS) {
        const old = stock.windows.previous.investors[investor], recent = stock.windows.recent.investors[investor], actual = stock.comparisons[investor]
        const a = grossInteger(old.total_shares), b = grossInteger(recent.total_shares); assert(a !== null && b !== null)
        const delta = adjacentBound(b - a)
        let pairSum = 0n
        for (const pair of stock.pairs) { const n = grossInteger(pair.net_delta_shares[investor]); assert(n !== null); pairSum = adjacentBound(pairSum + n) }
        assert(pairSum === delta)
        assert(equals(actual, { net_delta_shares: String(delta), net_delta_lots: grossLots(String(delta)), verified_delta_zero: delta === 0n, count_deltas: Object.fromEntries(ADJACENT_SIGNS.map((s) => [s, recent.counts[s] - old.counts[s]])) }))
      }
    }
    return v
  } catch { return null }
}
