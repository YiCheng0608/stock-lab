import { canonicalJson } from './chipsGross'
declare global { interface ImportMetaEnv { readonly VITE_CHIPS_DEALER_DIRECTION_COMBOS_POLICY_SHA256?: string } }

export const COMBOS_ROUTE = '/chips-stock-scope-7-dealer-direction-combos'
export const COMBOS_API = '/api/chips/dealer-direction-combos-stock-scope-7'
export const COMBOS_SCHEMA = 'dealer-direction-combos-read/finmind-stock-scope-7-v1'
export const COMBOS_CALCULATION = 'dealer-self-hedging-sign-combos-counts-maximal-segments/five-session-int64-v1'
export const COMBOS_CONSUMER_VERSION = 'dealer-self-hedging-direction-combos-five-session-v1'
export const COMBOS_NAMESPACE = 'issue9-dealer-direction-combos-finmind-v1/qa1'
export const COMBOS_POLICY_VERSION = 'issue9-dealer-direction-combos-finmind-v2'
export const COMBOS_PROVIDER = 'FinMind'
export const COMBOS_DATASET = 'TaiwanStockInstitutionalInvestorsBuySell'
export const COMBOS_ENDPOINT = 'https://api.finmindtrade.com/api/v4/data'
export const COMBOS_NAMES: Record<string, string> = { '3105': '穩懋', '3293': '鈊象', '5274': '信驊', '5347': '世界', '6488': '環球晶', '6510': '精測', '8069': '元太' }
export const COMBOS_SYMBOLS = ['3105', '3293', '5274', '5347', '6488', '6510', '8069']
export const COMBOS_WINDOW_DATES = ['2026-09-30', '2026-10-01', '2026-10-02', '2026-10-05', '2026-10-06']
export const COMBOS_CLOSED_DATES = ['2026-09-25', '2026-09-28']
export const COMBOS_ROW_NAMES = ['Dealer_Hedging', 'Dealer_self', 'Foreign_Dealer_Self', 'Foreign_Investor', 'Investment_Trust']
export const COMBOS_ROW_KEYS = ['buy', 'date', 'name', 'sell', 'stock_id']
export const COMBOS_COMPONENTS = ['self', 'hedge'] as const
export const COMBOS_SIGNS = ['positive', 'negative', 'zero'] as const
export const COMBOS_KEYS = ['positive_positive', 'positive_negative', 'positive_zero', 'negative_positive', 'negative_negative', 'negative_zero', 'zero_positive', 'zero_negative', 'zero_zero'] as const
export const COMBOS_OPPOSITE_KEYS = ['positive_negative', 'negative_positive']
export type ComboComponent = typeof COMBOS_COMPONENTS[number]
export type ComboSign = typeof COMBOS_SIGNS[number]
export type ComboKey = typeof COMBOS_KEYS[number]
export type ComboControls = { as_of: string; investor: string; horizon: string }
export type ComboSegment = { sign: ComboSign; start_index: number; end_index: number; start_date: string; end_date: string; length: number; earlier_unknown: boolean }
export type ComboAmounts = { row_index: number; buy_shares: string; sell_shares: string; net_shares: string; net_lots: string; sign: ComboSign }
export type ComboRow = { row_index: number; key_order: string[]; date: string; stock_id: string; name: string; buy_shares: string; sell_shares: string }
export type ComboPoint = { date: string; index: number; request_index: number; url: string; receipt_sha256: string; body_sha256: string; rows: ComboRow[]; self: ComboAmounts; hedge: ComboAmounts; combination: ComboKey; opposite: boolean }
export type ComboCounts = Record<ComboSign, number>
export type ComboWindow = { horizon: number; points: ComboPoint[]; counts: Record<ComboComponent, ComboCounts>; segments: Record<ComboComponent, ComboSegment[]>; latest: Record<ComboComponent, ComboSegment>; combination_counts: Record<ComboKey, number>; combination_dates: Record<ComboKey, string[]>; opposite: { count: number; dates: string[] } }
export type ComboStock = { symbol: string; name: string; exchange: string; security_type: string; currency: string; unit: string; window: ComboWindow }
export type ComboReceipt = { request_index: number; symbol: string; url: string; canonical: string; sha256: string; body_sha256: string; body_bytes: number }
export type ComboProvenance = { namespace: string; policy_sha256: string; policy_version: string; consumer_version: string; cutoff: string; dataset: string; unit: string; rights: string; value_label: string; calendar_reference: string; anchors_checked: number; record_only_comparison: { compared_values: number; expected_zero_set: string[][]; observed_zero_set: string[][]; only_expected: string[][]; only_observed: string[][]; matches: boolean; gate: boolean }; publication_time: string; first_availability: string; revision_time: string; unsupported: string[]; storage: string; [key: string]: unknown }
export type ComboCalendar = { reference: string; closed_dates: string[]; calendar_gets: number; window_dates: string[]; anchor_only_dates: string[]; meaning: string }
export type ComboRead = { schema: string; calculation_version: string; consumer_version: string; namespace: string; as_of: string; generation: string; state: string; available: boolean; reason: string | null; failure: unknown; count: number | null; window_dates: string[]; stocks: ComboStock[]; calendar: ComboCalendar; receipts: ComboReceipt[]; provenance: ComboProvenance; attempted: boolean; request_count: number }
export type ComboPhase = 'unacquired' | 'acquiring' | 'pending' | 'available' | 'failed' | 'expired' | 'released' | 'masked' | 'unsupported' | 'error'

function assert(ok: unknown, label = 'combos_evidence_invalid'): asserts ok { if (!ok) throw new Error(label) }
const equals = (a: unknown, b: unknown) => canonicalJson(a) === canonicalJson(b)
const shaPattern = /^[0-9a-f]{64}$/
const intPattern = /^(?:0|[1-9][0-9]*)$/
const MAX_I64 = 2n ** 63n - 1n
const MIN_I64 = -(2n ** 63n)
const keysOf = (value: object) => Object.keys(value).sort()
const isObject = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value)
const isInt = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0

export async function comboSHA(text: string): Promise<string> {
  return Array.from(new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))), (n) => n.toString(16).padStart(2, '0')).join('')
}
/** Canonical gross (buy/sell) text: unsigned decimal, no sign, no leading zeros, at most signed-int64 max. */
export function comboInt(value: unknown): bigint | null {
  if (typeof value !== 'string' || value.length > 19 || !intPattern.test(value)) return null
  const n = BigInt(value)
  return n <= MAX_I64 ? n : null
}
export function comboBound(n: bigint): bigint { assert(n >= MIN_I64 && n <= MAX_I64, 'combos_int64_overflow'); return n }
export function comboLots(n: bigint): string {
  comboBound(n)
  const abs = n < 0n ? -n : n, rest = abs % 1000n
  return (n < 0n ? '-' : '') + String(abs / 1000n) + (rest ? '.' + String(rest).padStart(3, '0').replace(/0+$/, '') : '')
}
export function comboSign(n: bigint): ComboSign { comboBound(n); return n > 0n ? 'positive' : n < 0n ? 'negative' : 'zero' }
export function comboSegments(signs: ComboSign[], dates: string[]): ComboSegment[] {
  assert(signs.length === dates.length && signs.length > 0)
  const out: ComboSegment[] = []
  for (const [i, sign] of signs.entries()) {
    const last = out[out.length - 1]
    if (last && last.sign === sign) { last.end_index = i; last.end_date = dates[i]; last.length++ }
    else out.push({ sign, start_index: i, end_index: i, start_date: dates[i], end_date: dates[i], length: 1, earlier_unknown: i === 0 })
  }
  assert(out.reduce((n, s) => n + s.length, 0) === signs.length)
  return out
}
export function comboControls(p: URLSearchParams): ComboControls { return { as_of: p.get('as_of') ?? '2026-10-06', investor: p.get('investor') ?? 'dealer', horizon: p.get('horizon') ?? '5' } }
export function validComboParams(p: URLSearchParams): boolean { const keys = [...p.keys()]; return !keys.length || keys.length === 3 && ['as_of', 'investor', 'horizon'].every((key) => p.getAll(key).length === 1) }
export function validComboControls(c: ComboControls): boolean { return c.as_of === '2026-10-06' && c.investor === 'dealer' && c.horizon === '5' }
export function comboPath(c: ComboControls, symbol?: string): string { return COMBOS_ROUTE + (symbol ? '/' + symbol : '') + '?' + new URLSearchParams(c).toString() }
export function comboURL(symbol: string): string { return COMBOS_ENDPOINT + '?dataset=' + COMBOS_DATASET + '&data_id=' + symbol + '&start_date=2026-09-29&end_date=2026-10-06' }
/** The opt-in flag. A guarded read so an application built without this define (the other chips previews) still renders. */
export function comboFlag(): string {
  try { const value = import.meta.env.VITE_CHIPS_DEALER_DIRECTION_COMBOS_STOCK_SCOPE_7; return typeof value === 'string' ? value : '' } catch { return '' }
}
/** The externally published policy pin, injected by the preview build; empty when none was supplied. */
export function comboExpectedPin(): string {
  try { const value = import.meta.env.VITE_CHIPS_DEALER_DIRECTION_COMBOS_POLICY_SHA256; return typeof value === 'string' ? value : '' } catch { return '' }
}
/** Every FIRST/READ request declares JSON; the local service refuses a POST that does not (a simple cross-site POST cannot spend the quota). */
export function comboRequestInit(capture: boolean): { method: string; headers: Record<string, string>; body?: string } {
  return capture ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' } : { method: 'GET', headers: { 'Content-Type': 'application/json' } }
}
/** The externally published pin is mandatory: an empty or malformed pin means nothing can be verified, so nothing is shown. */
export function comboPinValid(pin: unknown): pin is string { return typeof pin === 'string' && shaPattern.test(pin) }
/** The FIRST action is native, trusted, unique, not concurrent and only for the one admitted RAW control set. */
export function comboActionAllowed(input: { trusted: boolean; pending: boolean; valid: boolean; capture: boolean; firstLatched: boolean }): boolean {
  return input.trusted && !input.pending && input.valid && !(input.capture && input.firstLatched)
}

function utcMicroseconds(value: unknown): bigint {
  assert(typeof value === 'string')
  const m = /^(\d{4}-\d{2}-\d{2}T(\d{2}):(\d{2}):(\d{2}))(?:\.(\d{1,6}))?\+00:00$/.exec(value)
  assert(m && Number(m[2]) < 24 && Number(m[3]) < 60 && Number(m[4]) < 60 && Number.isFinite(Date.parse(m[1] + 'Z')))
  return BigInt(Date.parse(m[1] + 'Z')) * 1000n + BigInt((m[5] ?? '').padEnd(6, '0') || '0')
}
function amounts(row: ComboRow): ComboAmounts {
  const buy = comboInt(row.buy_shares), sell = comboInt(row.sell_shares)
  assert(buy !== null && sell !== null)
  const net = comboBound(buy - sell)
  return { row_index: row.row_index, buy_shares: String(buy), sell_shares: String(sell), net_shares: String(net), net_lots: comboLots(net), sign: comboSign(net) }
}
/** Recompute everything derived for one symbol from its five original-row days. */
export function deriveComboWindow(points: ComboPoint[]): Omit<ComboWindow, 'horizon' | 'points'> & { points: ComboPoint[] } {
  const dates = points.map((p) => p.date), derived: ComboPoint[] = []
  const signs: Record<ComboComponent, ComboSign[]> = { self: [], hedge: [] }
  for (const [index, p] of points.entries()) {
    const byName = new Map(p.rows.map((r) => [r.name, r]))
    const own = amounts(byName.get('Dealer_self')!), hedge = amounts(byName.get('Dealer_Hedging')!)
    signs.self.push(own.sign); signs.hedge.push(hedge.sign)
    const combination = (own.sign + '_' + hedge.sign) as ComboKey
    derived.push({ ...p, index, self: own, hedge, combination, opposite: COMBOS_OPPOSITE_KEYS.includes(combination) })
  }
  const counts = Object.fromEntries(COMBOS_COMPONENTS.map((c) => [c, Object.fromEntries(COMBOS_SIGNS.map((s) => [s, signs[c].filter((x) => x === s).length]))])) as Record<ComboComponent, ComboCounts>
  const combination_dates = Object.fromEntries(COMBOS_KEYS.map((k) => [k, derived.filter((p) => p.combination === k).map((p) => p.date)])) as Record<ComboKey, string[]>
  const combination_counts = Object.fromEntries(COMBOS_KEYS.map((k) => [k, combination_dates[k].length])) as Record<ComboKey, number>
  const opposite = derived.filter((p) => p.opposite).map((p) => p.date)
  const segments = { self: comboSegments(signs.self, dates), hedge: comboSegments(signs.hedge, dates) }
  const latest = { self: { ...segments.self[segments.self.length - 1] }, hedge: { ...segments.hedge[segments.hedge.length - 1] } }
  return { points: derived, counts, segments, latest, combination_counts, combination_dates, opposite: { count: opposite.length, dates: opposite } }
}

function validateReceipt(receipt: ComboReceipt, ordinal: number, pin: string): Promise<void> {
  return (async () => {
    assert(isObject(receipt) && equals(keysOf(receipt), ['body_bytes', 'body_sha256', 'canonical', 'request_index', 'sha256', 'symbol', 'url']))
    const symbol = COMBOS_SYMBOLS[ordinal]
    assert(receipt.request_index === ordinal && receipt.symbol === symbol && receipt.url === comboURL(symbol))
    assert(typeof receipt.canonical === 'string' && shaPattern.test(receipt.sha256) && shaPattern.test(receipt.body_sha256) && await comboSHA(receipt.canonical) === receipt.sha256)
    const original = JSON.parse(receipt.canonical) as Record<string, unknown>
    assert(isObject(original) && canonicalJson(original) === receipt.canonical)
    assert(equals(keysOf(original), ['body_bytes', 'body_sha256', 'content_encoding', 'content_type', 'full_eof', 'method', 'namespace', 'observed_utc', 'policy_sha256', 'request_started_utc', 'source_id', 'source_version', 'status', 'url']))
    assert(original.source_id === 'finmind_institutional_investors/' + symbol && original.source_version === COMBOS_POLICY_VERSION && original.method === 'GET' && original.status === 200)
    assert(original.url === receipt.url && original.body_sha256 === receipt.body_sha256 && original.body_bytes === receipt.body_bytes && original.full_eof === true && original.content_encoding === 'identity' && original.namespace === COMBOS_NAMESPACE)
    assert(isInt(receipt.body_bytes) && receipt.body_bytes > 0 && receipt.body_bytes <= 1048576)
    assert(typeof original.content_type === 'string' && /^application\/json(?:\s*;\s*charset="?utf-8"?)?$/i.test(original.content_type))
    assert(typeof original.policy_sha256 === 'string' && shaPattern.test(original.policy_sha256) && original.policy_sha256 === pin)
    // Only end >= start inside one receipt. The order of the seven is the backend's request_index (checked above); wall clocks
    // across receipts are not compared, so a clock stepped back after the quota was spent cannot hide a valid batch.
    assert(utcMicroseconds(original.observed_utc) >= utcMicroseconds(original.request_started_utc))
  })()
}
function validateRows(point: ComboPoint, symbol: string, day: string, seen: Set<number>) {
  assert(Array.isArray(point.rows) && point.rows.length === 5)
  const names = new Set<string>()
  let previous = -1
  for (const row of point.rows) {
    assert(isObject(row) && equals(keysOf(row), ['buy_shares', 'date', 'key_order', 'name', 'row_index', 'sell_shares', 'stock_id']))
    assert(typeof row.name === 'string' && COMBOS_ROW_NAMES.includes(row.name) && !names.has(row.name))
    names.add(row.name)
    assert(row.date === day && row.stock_id === symbol && isInt(row.row_index) && row.row_index > previous && !seen.has(row.row_index))
    previous = row.row_index; seen.add(row.row_index)
    assert(Array.isArray(row.key_order) && row.key_order.length === 5 && equals([...row.key_order].sort(), COMBOS_ROW_KEYS))
    assert(comboInt(row.buy_shares) !== null && comboInt(row.sell_shares) !== null)
  }
  assert(names.size === 5)
}
function validateAmounts(value: ComboAmounts, row: ComboRow) {
  assert(isObject(value) && equals(keysOf(value), ['buy_shares', 'net_lots', 'net_shares', 'row_index', 'sell_shares', 'sign']) && value.row_index === row.row_index)
}
/** Verify the whole READ against its own original rows before anything is shown; null means unavailable. */
export async function validateCombos(value: unknown, options: { pin?: string } = {}): Promise<ComboRead | null> {
  try {
    const v = value as ComboRead, pin = options.pin ?? comboExpectedPin()
    assert(comboPinValid(pin), 'combos_policy_pin_required')
    assert(isObject(v) && v.available === true && v.state === 'available' && v.reason === null && v.failure === null && v.count === 7 && v.as_of === '2026-10-06')
    assert(typeof v.generation === 'string' && v.generation.length > 0 && v.attempted === true && isInt(v.request_count) && v.request_count === 7)
    assert(v.schema === COMBOS_SCHEMA && v.calculation_version === COMBOS_CALCULATION && v.consumer_version === COMBOS_CONSUMER_VERSION && v.namespace === COMBOS_NAMESPACE)
    assert(equals(v.window_dates, COMBOS_WINDOW_DATES))
    const p = v.provenance
    assert(isObject(p) && p.namespace === COMBOS_NAMESPACE && p.policy_version === COMBOS_POLICY_VERSION && p.consumer_version === COMBOS_CONSUMER_VERSION && p.cutoff === '2026-10-06' && p.dataset === COMBOS_DATASET && p.unit === 'shares')
    assert(typeof p.policy_sha256 === 'string' && shaPattern.test(p.policy_sha256) && p.policy_sha256 === pin)
    assert(typeof p.rights === 'string' && p.rights.length > 0 && typeof p.value_label === 'string' && p.value_label.length > 0)
    assert(p.publication_time === 'unknown' && p.first_availability === 'unknown' && p.revision_time === 'unknown' && p.storage === 'process_RAM' && p.calendar_reference === 'SOURCE_REGISTRY 31.2')
    assert(p.anchors_checked === 56 && isObject(p.record_only_comparison) && p.record_only_comparison.gate === false && typeof p.record_only_comparison.matches === 'boolean' && Array.isArray(p.unsupported))
    const c = v.calendar
    assert(isObject(c) && equals(keysOf(c), ['anchor_only_dates', 'calendar_gets', 'closed_dates', 'meaning', 'reference', 'window_dates']) && c.reference === 'SOURCE_REGISTRY 31.2' && c.calendar_gets === 0)
    assert(equals(c.closed_dates, COMBOS_CLOSED_DATES) && equals(c.window_dates, COMBOS_WINDOW_DATES) && equals(c.anchor_only_dates, ['2026-09-29']) && typeof c.meaning === 'string')
    assert(Array.isArray(v.receipts) && v.receipts.length === 7)
    let bodyTotal = 0
    const shas = new Set<string>()
    for (const [ordinal, receipt] of v.receipts.entries()) {
      await validateReceipt(receipt, ordinal, pin)
      assert(!shas.has(receipt.sha256)); shas.add(receipt.sha256)
      bodyTotal += receipt.body_bytes; assert(bodyTotal <= 8388608)
    }
    assert(Array.isArray(v.stocks) && v.stocks.length === 7 && equals(v.stocks.map((s) => s.symbol), COMBOS_SYMBOLS))
    for (const [ordinal, stock] of v.stocks.entries()) {
      assert(isObject(stock) && equals(keysOf(stock), ['currency', 'exchange', 'name', 'security_type', 'symbol', 'unit', 'window']))
      assert(stock.name === COMBOS_NAMES[stock.symbol] && stock.exchange === 'TPEx' && stock.security_type === 'stock' && stock.currency === 'TWD' && stock.unit === 'shares')
      const w = stock.window
      assert(isObject(w) && equals(keysOf(w), ['combination_counts', 'combination_dates', 'counts', 'horizon', 'latest', 'opposite', 'points', 'segments']) && w.horizon === 5 && Array.isArray(w.points) && w.points.length === 5)
      const receipt = v.receipts[ordinal], seen = new Set<number>()
      for (const [index, point] of w.points.entries()) {
        assert(isObject(point) && equals(keysOf(point), ['body_sha256', 'combination', 'date', 'hedge', 'index', 'opposite', 'receipt_sha256', 'request_index', 'rows', 'self', 'url']))
        assert(point.date === COMBOS_WINDOW_DATES[index] && point.index === index && point.request_index === ordinal)
        assert(point.receipt_sha256 === receipt.sha256 && point.body_sha256 === receipt.body_sha256 && point.url === receipt.url)
        validateRows(point, stock.symbol, point.date, seen)
        const byName = new Map(point.rows.map((r) => [r.name, r]))
        validateAmounts(point.self, byName.get('Dealer_self')!); validateAmounts(point.hedge, byName.get('Dealer_Hedging')!)
      }
      const derived = deriveComboWindow(w.points)
      assert(equals(w.points, derived.points) && equals(w.counts, derived.counts) && equals(w.segments, derived.segments) && equals(w.latest, derived.latest))
      assert(equals(w.combination_counts, derived.combination_counts) && equals(w.combination_dates, derived.combination_dates) && equals(w.opposite, derived.opposite))
      assert(COMBOS_COMPONENTS.every((name) => COMBOS_SIGNS.reduce((n, s) => n + w.counts[name][s], 0) === 5) && COMBOS_KEYS.reduce((n, k) => n + w.combination_counts[k], 0) === 5)
    }
    return v
  } catch { return null }
}

const FAILED_CODE = /^[a-z0-9_]{1,64}$/
/** Everything that is not a verified available payload: a label for the user, never any value. */
export function comboUnavailable(value: unknown, status: number, capture: boolean): { phase: ComboPhase; text: string } {
  const body = isObject(value) ? value : null
  const state = body && typeof body.state === 'string' ? body.state : ''
  const reason = body && typeof body.reason === 'string' ? body.reason : ''
  const failure = body && isObject(body.failure) && typeof body.failure.primary_code === 'string' && FAILED_CODE.test(body.failure.primary_code) ? body.failure.primary_code : ''
  if (body && body.available === false) {
    if (reason === 'cutoff_not_supported') return { phase: 'unsupported', text: '不支援的截止日。全部每日、方向、組合、區段與原列追溯不可用。' }
    if (reason === 'already_attempted') return { phase: state === 'failed' ? 'failed' : 'pending', text: '本進程已嘗試過首次取得，不會再取得。請明確讀取已持有來源；全部值仍不顯示。' }
    if (state === 'new') return { phase: 'unacquired', text: '尚未取得來源。自行買賣與避險的每日方向、組合、區段與原列均未驗證。' }
    if (state === 'acquiring') return { phase: 'acquiring', text: '來源正在取得，全部值暫不顯示。' }
    if (state === 'pending') return { phase: 'pending', text: capture ? '原件已取得，等待獨立驗證准入（pending_independent_admission）。准入前不顯示任何值；准入後請明確讀取已持有來源。' : '原件已取得但尚未通過獨立驗證准入（pending_independent_admission）。准入前不顯示任何值。' }
    if (state === 'failed') return { phase: 'failed', text: '來源取得或驗證失敗' + (failure ? '（' + failure + '）' : '') + '。全部值已清空；額度已用盡，不重試。' }
    if (state === 'expired') return { phase: 'expired', text: '持有的來源已到期，全部值不可用；重新取得需新額度與新 seal。' }
    if (state === 'released') return { phase: 'released', text: '持有的來源已釋放，全部值不可用；重新取得需新額度與新 seal。' }
    if (state === 'available' && reason === 'calculation_conflict') return { phase: 'error', text: '已取得來源但計算衝突（calculation_conflict），七股整批不顯示。' }
  }
  return { phase: 'error', text: '資料不可用（HTTP ' + status + '）：回應不是已驗證的完整來源。全部值已清空，請明確重新讀取。' }
}
export type ComboOutcome = { read: ComboRead | null; phase: ComboPhase; text: string; generation: string | null; lockFirst: boolean }
/** Pure interpretation of one FIRST/READ response so the page keeps no state of its own about validity. */
export async function resolveComboResponse(input: { capture: boolean; status: number; ok: boolean; body: unknown; heldGeneration: string | null; pin?: string }): Promise<ComboOutcome> {
  const { capture, status, ok, body, heldGeneration } = input
  const bodyGeneration = isObject(body) && typeof body.generation === 'string' && body.generation ? body.generation : null
  if (ok && isObject(body) && body.available === true) {
    if (!comboPinValid(input.pin ?? comboExpectedPin())) return { read: null, phase: 'error', text: '未提供有效的外部 policy pin，無法驗證來源（fail-closed）；七股整批不顯示。', generation: heldGeneration, lockFirst: capture }
    const checked = await validateCombos(body, { pin: input.pin })
    if (!checked) return { read: null, phase: 'error', text: '完整原列、日期、名稱、對帳或方向計算未通過驗證，七股整批不顯示。', generation: heldGeneration, lockFirst: capture }
    if (heldGeneration && checked.generation !== heldGeneration) return { read: null, phase: 'error', text: '讀取的世代與已持有來源不同，全部值不顯示。', generation: heldGeneration, lockFirst: capture }
    return { read: checked, phase: 'available', text: '七股五日原列、自行買賣與避險淨額、九種組合、區段與追溯已驗證；FinMind 值為「API 當下值」（非 PIT）。', generation: checked.generation, lockFirst: true }
  }
  const u = comboUnavailable(body, status, capture)
  const sameGeneration = bodyGeneration && heldGeneration && bodyGeneration !== heldGeneration
  return { read: null, phase: sameGeneration ? 'error' : u.phase, text: sameGeneration ? '回應的世代與已持有來源不同，全部值不顯示。' : u.text, generation: heldGeneration ?? bodyGeneration, lockFirst: capture && status !== 0 }
}
