import { useRef, useState } from 'react'
import { ordinaryCloseTrendReasonLabel } from './presentation'
import type { OrdinaryCloseTrendClose, OrdinaryCloseTrendData, OrdinaryCloseTrendValue } from './types'

export const ORDINARY_CLOSE_TREND_VERSION = 'ordinary-close-trend/m1-v1'
export const ORDINARY_CLOSE_TREND_CUTOFF = '2026-10-06'
export const ORDINARY_CLOSE_TREND_SYMBOLS = ['3105', '3293', '5274', '5347', '6488', '6510', '8069']
const POLICY_VERSION = 'issue7-ordinary-close-saved-seven-v1'
const POLICY_SHA256 = 'f7659362cd3056413545d48a40a2e89bc97b810dc9c5535a4c8bdca41fcb9968'
const POLICY_BYTES = 5173
/** Verbatim `unsupported` of policy v1 (SHA-256 f7659362...9968): a payload must list exactly these, no more and no fewer. */
export const ORDINARY_CLOSE_TREND_UNSUPPORTED = ['historical_pit', 'publication_time', 'first_availability', 'revision_guarantee', 'adjusted_prices',
  'company_actions', 'suspension_comparability', 'whole_window_historical_membership', 'historical_eligibility', 'actionable_strategy', 'plan',
  'trading', 'historical_simulation', 'raw_body_storage', 'redistribution', 'other_cutoffs']
const MA_DAYS = 20
const RETURN_CLOSES = 21
const PLACES = { ma20: 2, return_20d: 2, close_over_ma20: 4 } as const
const TOP_KEYS = ['version', 'status', 'origin', 'exchange', 'symbol', 'as_of', 'supported_scope', 'price_basis', 'unit', 'windows', 'closes',
  'values', 'provenance', 'unsupported', 'limitations', 'reasons', 'read_state'].sort()
const PROVENANCE_KEYS = ['storage', 'storage_schema', 'consumer_version', 'source_policy', 'cutoff', 'closes_file', 'closes_bytes', 'closes_sha256',
  'receipt_sha256', 'saved_at', 'calendar', 'adapter', 'attribution', 'rights', 'publication_time', 'first_availability', 'revision_time',
  'historical_pit'].sort()

type Fraction = { n: bigint; d: bigint }
type Json = Record<string, unknown>

function gcd(a: bigint, b: bigint): bigint {
  let x = a < 0n ? -a : a, y = b < 0n ? -b : b
  while (y) [x, y] = [y, x % y]
  return x
}
function fraction(n: bigint, d: bigint): Fraction {
  const sign = d < 0n ? -1n : 1n
  const g = gcd(n, d) || 1n
  return { n: (sign * n) / g, d: (sign * d) / g }
}
const add = (a: Fraction, b: Fraction) => fraction(a.n * b.d + b.n * a.d, a.d * b.d)
const subtract = (a: Fraction, b: Fraction) => fraction(a.n * b.d - b.n * a.d, a.d * b.d)
const divide = (a: Fraction, b: Fraction) => fraction(a.n * b.d, a.d * b.n)
const times = (a: Fraction, k: bigint) => fraction(a.n * k, a.d)
const fractionText = (a: Fraction) => `${a.n}/${a.d}`

/** Canonical positive decimal text as stored by the backend (no exponent, no trailing zeros, at most six decimals). */
function parseClose(text: unknown): Fraction | null {
  if (typeof text !== 'string' || !/^(0|[1-9][0-9]{0,12})(\.[0-9]{0,5}[1-9])?$/.test(text)) return null
  const [whole, part = ''] = text.split('.')
  const n = BigInt(whole + part)
  return n > 0n ? fraction(n, 10n ** BigInt(part.length)) : null
}

/** Round half away from zero; a result of zero never carries a sign. Mirrors the backend rule exactly. */
export function roundHalfUp(value: Fraction, places: number): string {
  const negative = value.n < 0n
  const scale = 10n ** BigInt(places)
  const units = ((negative ? -value.n : value.n) * scale * 2n + value.d) / (value.d * 2n)
  const text = places === 0 ? units.toString() : `${units / scale}.${(units % scale).toString().padStart(places, '0')}`
  return negative && units > 0n ? `-${text}` : text
}

export type OrdinaryCloseTrendRecomputed = { ma20: Fraction; return_20d: Fraction; close_over_ma20: Fraction }

/** Independent client recomputation from the 21 original close strings; null when any close is not canonical. */
export function recomputeOrdinaryCloseTrend(closes: OrdinaryCloseTrendClose[]): OrdinaryCloseTrendRecomputed | null {
  if (closes.length !== RETURN_CLOSES) return null
  const values = closes.map((row) => parseClose(row.close))
  if (values.some((value) => value === null)) return null
  const rows = values as Fraction[]
  const average = divide(rows.slice(-MA_DAYS).reduce(add, fraction(0n, 1n)), fraction(BigInt(MA_DAYS), 1n))
  const latest = rows[rows.length - 1]
  return { ma20: average, return_20d: subtract(divide(latest, rows[0]), fraction(1n, 1n)), close_over_ma20: divide(latest, average) }
}

const isRecord = (value: unknown): value is Json => typeof value === 'object' && value !== null && !Array.isArray(value)
const sameKeys = (value: Json, keys: string[]) => JSON.stringify(Object.keys(value).sort()) === JSON.stringify(keys)
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every((item) => typeof item === 'string')
/** Set equality with the policy list: nothing missing, nothing extra, no duplicates; order is not part of the contract. */
const exactUnsupported = (value: unknown): boolean => strings(value) && value.length === ORDINARY_CLOSE_TREND_UNSUPPORTED.length
  && new Set(value).size === value.length && value.every((item) => ORDINARY_CLOSE_TREND_UNSUPPORTED.includes(item))
const HEX64 = /^[0-9a-f]{64}$/
const REASON = /^[a-z0-9_]{1,64}$/
const UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?\+00:00$/

function validDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

function validProvenance(value: unknown, asOf: string): boolean {
  if (!isRecord(value) || !sameKeys(value, PROVENANCE_KEYS)) return false
  const policy = value.source_policy, calendar = value.calendar, adapter = value.adapter, rights = value.rights
  return value.storage === 'private_local' && typeof value.storage_schema === 'string' && typeof value.consumer_version === 'string'
    && isRecord(policy) && policy.version === POLICY_VERSION && policy.sha256 === POLICY_SHA256 && policy.bytes === POLICY_BYTES
    && value.cutoff === asOf && value.closes_file === 'closes.json' && Number.isInteger(value.closes_bytes) && (value.closes_bytes as number) > 0
    && typeof value.closes_sha256 === 'string' && HEX64.test(value.closes_sha256) && typeof value.receipt_sha256 === 'string' && HEX64.test(value.receipt_sha256)
    && typeof value.saved_at === 'string' && UTC.test(value.saved_at)
    && isRecord(calendar) && typeof calendar.source_version === 'string' && Number.isInteger(calendar.rows) && isRecord(calendar.window)
    && validDate(calendar.window.start_date) && validDate(calendar.window.end_date) && calendar.window.end_date >= asOf
    && isRecord(adapter) && Object.values(adapter).every((item) => typeof item === 'string' && HEX64.test(item))
    && typeof value.attribution === 'string' && value.attribution !== '' && isRecord(rights) && Object.values(rights).every((item) => typeof item === 'string' && item !== '')
    && value.publication_time === 'unknown' && value.first_availability === 'unknown' && value.revision_time === 'unknown' && value.historical_pit === 'unsupported'
}

function validValue(value: unknown, kind: keyof typeof PLACES, expected: Fraction, unit: string, scale: bigint, trace: Json): boolean {
  if (!isRecord(value) || value.status !== 'available' || !strings(value.reasons) || value.reasons.length !== 0) return false
  if (value.exact !== fractionText(expected) || value.display !== roundHalfUp(times(expected, scale), PLACES[kind])) return false
  if (value.display_unit !== unit || value.display_scale !== Number(scale) || value.display_places !== PLACES[kind] || value.rounding !== 'half_up_away_from_zero') return false
  return Object.entries(trace).every(([name, expectedValue]) => value[name] === expectedValue)
}

/** Strict client gate: a response is adopted only when it describes this stock and cutoff and every value recomputes. */
export function validOrdinaryCloseTrend(data: unknown, exchange: string, symbol: string, asOf: string): data is OrdinaryCloseTrendData {
  if (!isRecord(data) || !sameKeys(data, TOP_KEYS)) return false
  const scope = data.supported_scope, windows = data.windows, state = data.read_state
  if (data.version !== ORDINARY_CLOSE_TREND_VERSION || data.origin !== 'private_local' || data.exchange !== exchange || data.symbol !== symbol || data.as_of !== asOf) return false
  if (!ordinaryCloseTrendSupported(exchange, symbol, asOf) || data.price_basis !== 'provider_reported_nominal_close' || data.unit !== 'TWD_per_share') return false
  if (!isRecord(scope) || scope.cutoff !== ORDINARY_CLOSE_TREND_CUTOFF || JSON.stringify(scope.symbols) !== JSON.stringify(ORDINARY_CLOSE_TREND_SYMBOLS)) return false
  if (!isRecord(windows) || windows.ma_days !== MA_DAYS || windows.return_days !== 20 || windows.return_closes !== RETURN_CLOSES) return false
  if (!exactUnsupported(data.unsupported) || !strings(data.limitations) || !strings(data.reasons) || !isRecord(state) || state.read_only !== true || state.network_requests !== 0 || state.writes !== 0) return false
  if (data.status === 'unavailable') {
    return state.verified === false && data.values === null && data.provenance === null && Array.isArray(data.closes) && data.closes.length === 0
      && data.reasons.length > 0 && data.reasons.every((reason) => REASON.test(reason))
  }
  if (data.status !== 'available' || state.verified !== true || data.reasons.length !== 0 || !validProvenance(data.provenance, asOf)) return false
  const closes = data.closes
  if (!Array.isArray(closes) || closes.length !== RETURN_CLOSES) return false
  for (let index = 0; index < closes.length; index++) {
    const row = closes[index]
    if (!isRecord(row) || !sameKeys(row, ['close', 'date']) || !validDate(row.date) || parseClose(row.close) === null) return false
    if (index > 0 && (row.date as string) <= (closes[index - 1] as OrdinaryCloseTrendClose).date) return false
  }
  const rows = closes as OrdinaryCloseTrendClose[]
  const first = rows[0], second = rows[1], last = rows[rows.length - 1]
  if (last.date !== asOf) return false
  const recomputed = recomputeOrdinaryCloseTrend(rows)
  const values = data.values
  if (!recomputed || !isRecord(values) || !sameKeys(values, ['close_over_ma20', 'latest', 'ma20', 'return_20d', 'trend'])) return false
  if (!isRecord(values.latest) || values.latest.date !== last.date || values.latest.close !== last.close) return false
  if (!isRecord(values.trend) || values.trend.status !== 'formula_not_defined' || values.trend.exact !== null || values.trend.display !== null
    || !strings(values.trend.reasons) || values.trend.reasons.join() !== 'trend_formula_not_defined') return false
  return validValue(values.ma20, 'ma20', recomputed.ma20, 'TWD_per_share', 1n, { window_start: second.date, window_end: last.date, count: MA_DAYS })
    && validValue(values.return_20d, 'return_20d', recomputed.return_20d, 'percent', 100n,
      { base_date: first.date, base_close: first.close, latest_date: last.date, latest_close: last.close })
    && validValue(values.close_over_ma20, 'close_over_ma20', recomputed.close_over_ma20, 'ratio', 1n,
      { latest_date: last.date, latest_close: last.close, ma20_window_start: second.date, ma20_window_end: last.date })
}

export const ordinaryCloseTrendRelevant = (exchange: string, symbol: string) => exchange === 'TPEx' && ORDINARY_CLOSE_TREND_SYMBOLS.includes(symbol)
export const ordinaryCloseTrendSupported = (exchange: string, symbol: string, asOf: string) =>
  ordinaryCloseTrendRelevant(exchange, symbol) && asOf === ORDINARY_CLOSE_TREND_CUTOFF

export function formatOrdinaryCloseValue(value: OrdinaryCloseTrendValue): string {
  if (value.status !== 'available' || value.display === null) return '資料不足，不補算'
  if (value.display_unit === 'percent') return `${value.display.startsWith('-') || /^0(\.0+)?$/.test(value.display) ? '' : '+'}${value.display}%`
  if (value.display_unit === 'TWD_per_share') return `${value.display} 元／股`
  return value.display
}

export type TrendReadResult = { kind: 'loaded'; data: OrdinaryCloseTrendData } | { kind: 'failed'; reason: string }
export type OrdinaryCloseTrendFetcher = (exchange: string, symbol: string, asOf: string) => Promise<unknown>

export async function readOrdinaryCloseTrend(fetcher: OrdinaryCloseTrendFetcher, exchange: string, symbol: string, asOf: string): Promise<TrendReadResult> {
  let raw: unknown
  try { raw = await fetcher(exchange, symbol, asOf) } catch { return { kind: 'failed', reason: 'ordinary_close_request_failed' } }
  return validOrdinaryCloseTrend(raw, exchange, symbol, asOf) ? { kind: 'loaded', data: raw } : { kind: 'failed', reason: 'ordinary_close_contract_invalid' }
}

export type TrendState =
  | { token: string; phase: 'idle' }
  | { token: string; phase: 'busy' }
  | { token: string; phase: 'loaded'; data: OrdinaryCloseTrendData }
  | { token: string; phase: 'failed'; reason: string }

/** Values belong to one stock/date context: any other context shows the idle state, never the earlier values. */
export const visibleTrendState = (state: TrendState, token: string): TrendState => (state.token === token ? state : { token, phase: 'idle' })

/** A response for an earlier context is dropped; it can never fill the current one. */
export function settleTrendRead(state: TrendState, token: string, current: string, result: TrendReadResult): TrendState {
  if (token !== current) return state
  return result.kind === 'loaded' ? { token, phase: 'loaded', data: result.data } : { token, phase: 'failed', reason: result.reason }
}

function Reasons({ codes }: { codes: string[] }) {
  return <div className="data-gap" role="status">{codes.map((code) => <div key={code}>{ordinaryCloseTrendReasonLabel(code)}（<code>{code}</code>）</div>)}</div>
}

function Loaded({ data }: { data: OrdinaryCloseTrendData }) {
  const values = data.values!, provenance = data.provenance!, closes = data.closes
  const first = closes[0], last = closes[closes.length - 1]
  return <>
    <div className="table-wrap">
      <table>
        <caption>{data.symbol} 截止 {data.as_of} 的名目收盤衍生值（單位見各列）</caption>
        <thead><tr><th>項目</th><th>數值</th><th>計算依據</th></tr></thead>
        <tbody>
          <tr><th scope="row">最近收盤（元／股）</th><td className="numeric-cell">{last.close}</td><td>{last.date} 收盤原字串</td></tr>
          <tr><th scope="row">MA20（元／股）</th><td className="numeric-cell">{formatOrdinaryCloseValue(values.ma20)}</td><td>{values.ma20.window_start}～{values.ma20.window_end} 共 20 個交易日收盤的簡單平均</td></tr>
          <tr><th scope="row">20 日報酬（%）</th><td className="numeric-cell">{formatOrdinaryCloseValue(values.return_20d)}</td><td>{last.date} 收盤 ÷ {first.date} 收盤 − 1（共 21 個收盤）</td></tr>
          <tr><th scope="row">收盤／MA20（比值）</th><td className="numeric-cell">{formatOrdinaryCloseValue(values.close_over_ma20)}</td><td>{last.date} 收盤 ÷ 同日 MA20</td></tr>
          <tr><th scope="row">趨勢</th><td colSpan={2}>趨勢判定規格未定義，不推論</td></tr>
        </tbody>
      </table>
    </div>
    <p className="small-note">顯示值以四捨五入（0.5 進位）取小數：MA20 與報酬各 2 位、比值 4 位；計算前不逐筆四捨五入，精確分數見明細。收盤為名目收盤，未還原，未納入公司行動與停牌可比性。</p>
    <details className="technical-details">
      <summary>逐日收盤、精確值與來源版本</summary>
      <div className="table-wrap">
        <table>
          <caption>單位：元／股，名目收盤原字串；日期為臺北交易日曆日</caption>
          <thead><tr><th>交易日</th><th>收盤</th><th>用途</th></tr></thead>
          <tbody>{closes.map((row, index) => <tr key={row.date}><td>{row.date}</td><td className="numeric-cell">{row.close}</td><td>{index === 0 ? '20 日報酬基準' : index === closes.length - 1 ? 'MA20 窗口末日（最近收盤）' : 'MA20 窗口'}</td></tr>)}</tbody>
        </table>
      </div>
      <div>精確值（分數）：MA20 {values.ma20.exact}；20 日報酬 {values.return_20d.exact}；收盤／MA20 {values.close_over_ma20.exact}</div>
      <div>來源政策：{provenance.source_policy.version} · {provenance.source_policy.bytes} bytes</div>
      <div className="hash-cell">政策 SHA-256：{provenance.source_policy.sha256}</div>
      <div className="hash-cell">收盤檔 SHA-256：{provenance.closes_sha256}（{provenance.closes_file}，{provenance.closes_bytes} bytes）</div>
      <div className="hash-cell">收據 SHA-256：{provenance.receipt_sha256}</div>
      <div>保存時間（UTC）：{provenance.saved_at}</div>
      <div>交易日曆：{provenance.calendar.source_version} · {provenance.calendar.rows} 日 · {provenance.calendar.window.start_date}～{provenance.calendar.window.end_date}</div>
      <div>發布時間、首次可得時間與修訂時間皆 {provenance.publication_time}；歷史時點（PIT）{provenance.historical_pit}</div>
      <div>署名：{provenance.attribution}</div>
      <div>不支援：{data.unsupported.join('、')}</div>
    </details>
  </>
}

export function OrdinaryCloseTrendView({ exchange, symbol, asOf, state, onRead }: {
  exchange: string; symbol: string; asOf: string; state: TrendState; onRead: () => void
}) {
  if (!ordinaryCloseTrendRelevant(exchange, symbol)) return null
  const supported = ordinaryCloseTrendSupported(exchange, symbol, asOf)
  const busy = state.phase === 'busy'
  return <section className="panel ordinary-close-trend" aria-label="已保存收盤與 MA20">
    <div className="section-head"><div><div className="eyebrow">已保存名目收盤</div><h2>收盤、MA20 與 20 日報酬</h2></div></div>
    <p className="small-note">只讀本機已保存的 {RETURN_CLOSES} 日收盤（{ORDINARY_CLOSE_TREND_CUTOFF} 截止），不連網、不寫檔；按下按鈕才讀取。</p>
    {!supported && <div className="data-gap" role="status">目前研究截止為 {asOf || '最新資料（未指定日期）'}，與本區塊支援的 {ORDINARY_CLOSE_TREND_CUTOFF} 不符，不讀取，也不以較早或較晚日期代替。請在「研究截止日期」套用 {ORDINARY_CLOSE_TREND_CUTOFF}。</div>}
    {supported && <button type="button" className="secondary-button" onClick={onRead} disabled={busy} aria-busy={busy}>{busy ? '讀取中…' : '讀取已保存收盤與 MA20'}</button>}
    {supported && state.phase === 'idle' && <p className="small-note">尚未讀取。切換股票或截止日期後須重新按下按鈕。</p>}
    {state.phase === 'failed' && <Reasons codes={[state.reason]} />}
    {state.phase === 'loaded' && state.data.status === 'unavailable' && <Reasons codes={state.data.reasons} />}
    {state.phase === 'loaded' && state.data.status === 'available' && <Loaded data={state.data} />}
  </section>
}

export function OrdinaryCloseTrend({ exchange, symbol, asOf, fetcher }: { exchange: string; symbol: string; asOf: string; fetcher: OrdinaryCloseTrendFetcher }) {
  const key = `${exchange}:${symbol}:${asOf}`
  const route = useRef({ key, generation: 0 })
  if (route.current.key !== key) route.current = { key, generation: route.current.generation + 1 }
  const token = `${route.current.generation}:${key}`
  const current = useRef(token)
  current.current = token
  const pending = useRef(new Set<string>())
  const [state, setState] = useState<TrendState>({ token, phase: 'idle' })
  const read = async () => {
    if (!ordinaryCloseTrendSupported(exchange, symbol, asOf) || pending.current.has(token)) return
    pending.current.add(token)
    setState({ token, phase: 'busy' })
    try {
      const result = await readOrdinaryCloseTrend(fetcher, exchange, symbol, asOf)
      setState((prior) => settleTrendRead(prior, token, current.current, result))
    } finally {
      pending.current.delete(token)
    }
  }
  return <OrdinaryCloseTrendView exchange={exchange} symbol={symbol} asOf={asOf} state={visibleTrendState(state, token)} onRead={read} />
}
