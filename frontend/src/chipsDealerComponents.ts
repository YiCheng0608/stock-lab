import { canonicalJson, grossInteger, grossLots } from './chipsGross'
declare global { interface ImportMetaEnv { readonly VITE_CHIPS_DEALER_COMPONENTS_STOCK_SCOPE_7?: string } }

export const DEALER_COMPONENTS_ROUTE = '/chips-stock-scope-7-dealer-components'
export const DEALER_COMPONENTS_API = '/api/chips/dealer-components-stock-scope-7'
export const DEALER_COMPONENTS_PIN = 'sha256:54347a73a5d725e702599eb582e9c75550f2c24c6839afd61c890e37bed99eab'
export const DEALER_COMPONENTS_VERSION = 'm1-chips-dealer-components-stock-scope-7-tpex-2026-10-06.1'
export const DEALER_COMPONENTS_PROFILE = 'free_public_local_chips_only_dealer_components_stock_scope_7'
export const DEALER_COMPONENTS_SCHEMA = 'institutional-dealer-components-read/chips-stock-scope-7-v1'
export const DEALER_COMPONENTS_WORKER_SCHEMA = 'tpex-institutional-dealer-components/chips-stock-scope-7-v1'
export const DEALER_COMPONENTS_CAPTURE_SCHEMA = 'tpex-institutional-dealer-components-capture/chips-stock-scope-7-v1'
export const DEALER_COMPONENTS_CALENDAR_SCHEMA = 'institutional-dealer-components-calendar/chips-stock-scope-7-v1'
export const DEALER_COMPONENTS_CALENDAR_VERSION = 'dataset-11391-month-csv-observed-2026-10-08/chips-dealer-components-stock-scope-7-v1'
export const DEALER_COMPONENTS_CALCULATION = 'dealer-self-hedge-total-buy-sell-net/five-session-step-int64-v1'
export const DEALER_COMPONENTS_ATTRIBUTION = "金融監督管理委員會證券期貨局提供、財團法人中華民國證券櫃檯買賣中心（Taipei Exchange, TPEx）[2026] 櫃買指數歷史資料（dataset11391；dataset-11391-month-csv-observed-2026-10-08/chips-dealer-components-stock-scope-7-v1）及上櫃股票三大法人買賣明細資訊（dataset11856；dataset-11856-dated-csv-observed-2026-10-08/chips-dealer-components-stock-scope-7-v1）。此開放資料依政府資料開放授權條款（Open Government Data License）進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料開放授權條款－第1版：https://data.gov.tw/license。原欄、來源及完整性保留；自行買賣、避險及總額之每日與五日比較為本地衍生結果。"
export const DEALER_COMPONENTS_NAMES: Record<string, string> = {"3105":"穩懋","3293":"鈊象","5274":"信驊","5347":"世界","6488":"環球晶","6510":"精測","8069":"元太"}
export const DEALER_COMPONENTS_SYMBOLS = ['3105', '3293', '5274', '5347', '6488', '6510', '8069']
export const DEALER_COMPONENTS = ['self', 'hedge', 'total'] as const
export const DEALER_METRICS = ['buy', 'sell', 'net'] as const
export type DealerComponent = typeof DEALER_COMPONENTS[number]
export type DealerMetric = typeof DEALER_METRICS[number]
export type DealerControls = { as_of: string; investor: string; horizon: string }
export type DealerAmounts = { buy_shares: string; buy_lots: string; verified_buy_zero: boolean; sell_shares: string; sell_lots: string; verified_sell_zero: boolean; net_shares: string; net_lots: string; verified_net_zero: boolean }
export type DealerTrace = { date: string; row_ordinal: number; source_values: string[]; receipt_sha256: string; body_sha256: string }
export type DealerPoint = DealerTrace & { components: Record<DealerComponent, DealerAmounts>; component_check: boolean }
export type DealerWindow = { horizon: number; points: DealerPoint[]; totals: Record<DealerComponent, DealerAmounts>; component_check: boolean }
export type DealerStock = { symbol: string; name: string; exchange: string; security_type: string; currency: string; window: DealerWindow }
export type DealerPolicy = { scope: { cutoff: string; symbols: string[]; identities: Record<string, string>; components: string[]; investors: string[]; horizons: number[] }; calendar: { from: string; closed_dates: string[]; observation_date: string }; rights: { attribution: string }; sources: { daily: { header: string[]; base_url: string; source_version: string }; index: { header: string[]; base_url: string; requests: string[]; source_version: string } } }
export type DealerRead = { schema: string; worker_schema: string; capture_schema: string; calendar_schema: string; calendar_version: string; calculation_version: string; profile: string; policy_version: string; policy_digest: string; policy: DealerPolicy; as_of: string; generation: string; available: boolean; count: number | null; reason: string | null; stocks: DealerStock[]; receipts: { original: Record<string, unknown>; canonical: string; sha256: string }[]; calendar: { schema: string; version: string; original_dates: string[]; adopted_dates: string[]; daily_dates: string[]; rows: DealerTrace[]; post_cutoff_excluded: string[] } }

function assert(ok: unknown): asserts ok { if (!ok) throw new Error('dealer_components_evidence_invalid') }
const equals = (a: unknown, b: unknown) => canonicalJson(a) === canonicalJson(b)
const shaPattern = /^[0-9a-f]{64}$/
export async function dealerSHA(text: string): Promise<string> { return Array.from(new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))), (n) => n.toString(16).padStart(2, '0')).join('') }
export function dealerBound(n: bigint): bigint { assert(n >= -(2n ** 63n) && n <= 2n ** 63n - 1n); return n }
export function dealerAmounts(values: bigint[]): DealerAmounts {
  assert(values.length === 3 && values[0] >= 0n && values[1] >= 0n && dealerBound(values[0] - values[1]) === values[2])
  const result: Record<string, string | boolean> = {}
  for (const [i, metric] of DEALER_METRICS.entries()) { const n = dealerBound(values[i]); result[metric + '_shares'] = String(n); result[metric + '_lots'] = grossLots(String(n)); result['verified_' + metric + '_zero'] = n === 0n }
  return result as DealerAmounts
}
export function dealerControls(p: URLSearchParams): DealerControls { return { as_of: p.get('as_of') ?? '2026-10-06', investor: p.get('investor') ?? 'dealer', horizon: p.get('horizon') ?? '5' } }
export function validDealerParams(p: URLSearchParams): boolean { const keys = [...p.keys()]; return !keys.length || keys.length === 3 && ['as_of', 'investor', 'horizon'].every((key) => p.getAll(key).length === 1) }
export function validDealerControls(c: DealerControls): boolean { return c.as_of === '2026-10-06' && c.investor === 'dealer' && c.horizon === '5' }
export function dealerPath(c: DealerControls, symbol?: string): string { return DEALER_COMPONENTS_ROUTE + (symbol ? '/' + symbol : '') + '?' + new URLSearchParams(c).toString() }
export function dealerDailyURL(p: DealerPolicy, day: string): string { return p.sources.daily.base_url + '&d=' + encodeURIComponent(String(Number(day.slice(0, 4)) - 1911) + '/' + day.slice(5, 7) + '/' + day.slice(8)) }
export function dealerDates(p: DealerPolicy): string[] {
  const result = []
  for (let time = Date.parse(p.calendar.from + 'T00:00:00Z'); time <= Date.parse(p.scope.cutoff + 'T00:00:00Z'); time += 86400000) {
    const d = new Date(time), day = d.toISOString().slice(0, 10)
    if (![0, 6].includes(d.getUTCDay()) && !p.calendar.closed_dates.includes(day)) result.push(day)
  }
  return result
}
function utcMicroseconds(value: unknown): bigint {
  assert(typeof value === 'string')
  const m = /^(2026-10-08T([0-9]{2}):([0-9]{2}):([0-9]{2}))(?:\.([0-9]{1,6}))?(?:Z|\+00:00)$/.exec(value)
  assert(m && Number(m[2]) < 24 && Number(m[3]) < 60 && Number(m[4]) < 60 && Number.isFinite(Date.parse(m[1] + 'Z')))
  return BigInt(Date.parse(m[1] + 'Z')) * 1000n + BigInt((m[5] ?? '').padEnd(6, '0') || '0')
}
function rawComponents(point: DealerPoint, symbol: string, day: string): Record<DealerComponent, bigint[]> {
  const row = point.source_values
  assert(Array.isArray(row) && row.length === 25 && row.every((x) => typeof x === 'string'))
  assert(row[0] === String(Number(day.slice(0, 4)) - 1911) + day.slice(5, 7) + day.slice(8) && row[1] === symbol && row[2].trim() === DEALER_COMPONENTS_NAMES[symbol])
  const groups = [3, 6, 9, 12, 15, 18, 21].map((start) => {
    const buy = grossInteger(row[start]), sell = grossInteger(row[start + 1]), net = grossInteger(row[start + 2])
    assert(buy !== null && sell !== null && net !== null && buy >= 0n && sell >= 0n && dealerBound(buy - sell) === net)
    return [buy, sell, net]
  })
  assert(groups[2].every((n, i) => n === dealerBound(groups[0][i] + groups[1][i])) && groups[6].every((n, i) => n === dealerBound(groups[4][i] + groups[5][i])))
  assert(grossInteger(row[24]) === dealerBound(dealerBound(groups[0][2] + groups[3][2]) + groups[6][2]))
  return { self: groups[4], hedge: groups[5], total: groups[6] }
}
/** ALL35 original rows and ALL3 components are verified before displaying any value. */
export async function validateDealerComponents(value: unknown): Promise<DealerRead | null> {
  try {
    const v = value as DealerRead
    assert(v && v.available === true && v.count === 7 && v.reason === null && typeof v.generation === 'string' && v.generation.length > 0 && v.as_of === '2026-10-06')
    assert(v.schema === DEALER_COMPONENTS_SCHEMA && v.worker_schema === DEALER_COMPONENTS_WORKER_SCHEMA && v.capture_schema === DEALER_COMPONENTS_CAPTURE_SCHEMA && v.calendar_schema === DEALER_COMPONENTS_CALENDAR_SCHEMA && v.calendar_version === DEALER_COMPONENTS_CALENDAR_VERSION && v.calculation_version === DEALER_COMPONENTS_CALCULATION && v.profile === DEALER_COMPONENTS_PROFILE && v.policy_version === DEALER_COMPONENTS_VERSION && v.policy_digest === DEALER_COMPONENTS_PIN)
    const text = canonicalJson(v.policy)
    assert(new TextEncoder().encode(text).length === 9245 && 'sha256:' + await dealerSHA(text) === DEALER_COMPONENTS_PIN && v.policy.rights.attribution === DEALER_COMPONENTS_ATTRIBUTION)
    assert(equals(v.policy.scope.symbols, DEALER_COMPONENTS_SYMBOLS) && equals(v.policy.scope.identities, DEALER_COMPONENTS_NAMES) && equals(v.policy.scope.components, DEALER_COMPONENTS) && equals(v.policy.scope.investors, ['dealer']) && equals(v.policy.scope.horizons, [5]))
    const adopted = dealerDates(v.policy), daily = adopted.slice(-5)
    assert(daily.length === 5 && v.receipts.length === 7)
    const keys = ['schema', 'ordinal', 'source', 'source_version', 'requested_date', 'url', 'method', 'request_body_bytes', 'http_status', 'content_type', 'content_encoding', 'body_bytes', 'body_sha256', 'request_started_at', 'captured_at', 'policy_version', 'policy_digest', 'profile', 'publication_time', 'first_available_time', 'revision_time', 'historical_pit', 'request_count'].sort()
    const receipts = new Map<string, Record<string, unknown>>()
    let previousTime = 0n, bodyTotal = 0
    for (const [ordinal, receipt] of v.receipts.entries()) {
      const r = receipt.original, source = ordinal < 2 ? 'index' : 'daily'
      const requested = ordinal < 2 ? v.policy.sources.index.requests[ordinal] : daily[ordinal - 2]
      const url = ordinal < 2 ? v.policy.sources.index.base_url + '&date=' + encodeURIComponent(requested.replace(/-/g, '/')) : dealerDailyURL(v.policy, requested)
      assert(equals(Object.keys(r).sort(), keys) && receipt.canonical === canonicalJson(r) && shaPattern.test(receipt.sha256) && await dealerSHA(receipt.canonical) === receipt.sha256 && !receipts.has(receipt.sha256))
      assert(r.schema === DEALER_COMPONENTS_CAPTURE_SCHEMA && r.ordinal === ordinal && r.source === source && r.source_version === v.policy.sources[source].source_version && r.requested_date === requested && r.url === url && r.method === 'GET' && r.request_body_bytes === 0 && r.http_status === 200 && r.content_encoding === 'identity' && r.policy_version === DEALER_COMPONENTS_VERSION && r.policy_digest === DEALER_COMPONENTS_PIN && r.profile === DEALER_COMPONENTS_PROFILE && r.request_count === 1)
      assert(typeof r.body_sha256 === 'string' && shaPattern.test(r.body_sha256) && typeof r.body_bytes === 'number' && Number.isSafeInteger(r.body_bytes) && r.body_bytes > 0 && r.body_bytes <= (ordinal < 2 ? 1048576 : 2097152))
      bodyTotal += r.body_bytes; assert(bodyTotal <= 12582912)
      assert(typeof r.content_type === 'string' && /^(?:text|application)\/csv(?:;charset=utf-8)?$/i.test(r.content_type.replace(/ /g, '')))
      const start = utcMicroseconds(r.request_started_at), end = utcMicroseconds(r.captured_at)
      assert(start >= previousTime && end >= start); previousTime = end
      assert(r.publication_time === 'unknown' && r.first_available_time === 'unknown' && r.revision_time === 'unknown' && r.historical_pit === 'unsupported')
      receipts.set(receipt.sha256, r)
    }
    const calendar = v.calendar
    assert(calendar.schema === DEALER_COMPONENTS_CALENDAR_SCHEMA && calendar.version === DEALER_COMPONENTS_CALENDAR_VERSION)
    assert(equals(calendar.rows.map((r) => r.date), calendar.original_dates) && equals([...new Set(calendar.original_dates)].sort(), calendar.original_dates))
    assert(equals(calendar.adopted_dates, adopted) && equals(calendar.daily_dates, daily) && equals(calendar.original_dates.filter((d) => d <= v.as_of), adopted) && equals(calendar.original_dates.filter((d) => d > v.as_of), calendar.post_cutoff_excluded))
    for (const row of calendar.rows) {
      const r = receipts.get(row.receipt_sha256), d = new Date(row.date + 'T00:00:00Z')
      assert(r && r.source === 'index' && r.requested_date === row.date.slice(0, 7) + '-01' && r.body_sha256 === row.body_sha256 && Number.isSafeInteger(row.row_ordinal) && row.row_ordinal > 0)
      assert(/^2026-(09|10)-[0-9]{2}$/.test(row.date) && Number.isFinite(d.valueOf()) && d.toISOString().slice(0, 10) === row.date && ![0, 6].includes(d.getUTCDay()) && !v.policy.calendar.closed_dates.includes(row.date) && row.date <= v.policy.calendar.observation_date)
      assert(row.source_values.length === 6 && row.source_values.every((s) => typeof s === 'string') && row.source_values[0] === row.date.replace(/-/g, ''))
      const decimal = (s: string) => { assert(s.length > 0 && s.length <= 64 && s === s.trim() && /^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/.test(s)); const n = Number(s); assert(Number.isFinite(n)); return n }
      const [open, high, low, close] = row.source_values.slice(1, 5).map(decimal); decimal(row.source_values[5])
      assert(open > 0 && high > 0 && low > 0 && close > 0 && low <= Math.min(open, close) && Math.max(open, close) <= high)
    }
    for (const month of v.policy.sources.index.requests) assert(equals(calendar.rows.filter((r) => r.date.startsWith(month.slice(0, 7))).map((r) => r.row_ordinal).sort((a, b) => a - b), calendar.rows.filter((r) => r.date.startsWith(month.slice(0, 7))).map((_, i) => i + 1)))
    assert(v.stocks.length === 7 && equals(v.stocks.map((s) => s.symbol), DEALER_COMPONENTS_SYMBOLS))
    const ordinals = new Set<string>()
    for (const stock of v.stocks) {
      assert(stock.name === DEALER_COMPONENTS_NAMES[stock.symbol] && stock.exchange === 'TPEx' && stock.security_type === 'stock' && stock.currency === 'TWD')
      const window = stock.window, sums: Record<DealerComponent, bigint[]> = { self: [0n, 0n, 0n], hedge: [0n, 0n, 0n], total: [0n, 0n, 0n] }
      assert(window.horizon === 5 && window.points.length === 5 && window.component_check === true && equals(Object.keys(window.totals).sort(), [...DEALER_COMPONENTS].sort()))
      for (const [index, point] of window.points.entries()) {
        const r = receipts.get(point.receipt_sha256), key = point.receipt_sha256 + '/' + point.row_ordinal
        assert(point.date === daily[index] && Number.isSafeInteger(point.row_ordinal) && point.row_ordinal > 0 && !ordinals.has(key) && r && r.source === 'daily' && r.requested_date === point.date && r.body_sha256 === point.body_sha256)
        ordinals.add(key)
        const values = rawComponents(point, stock.symbol, point.date)
        assert(point.component_check === true && equals(Object.keys(point.components).sort(), [...DEALER_COMPONENTS].sort()))
        for (const name of DEALER_COMPONENTS) {
          assert(equals(point.components[name], dealerAmounts(values[name])))
          for (let i = 0; i < 3; i++) sums[name][i] = dealerBound(sums[name][i] + values[name][i])
        }
      }
      assert(sums.total.every((n, i) => n === dealerBound(sums.self[i] + sums.hedge[i])))
      for (const name of DEALER_COMPONENTS) assert(equals(window.totals[name], dealerAmounts(sums[name])))
    }
    return v
  } catch { return null }
}
