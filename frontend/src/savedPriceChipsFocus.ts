import type { InstitutionalWindowsData, PriceFocusDayMove, PriceSavedFocusData } from './types'
import { validSavedPriceFocus } from './savedPriceFocus'
import { validChips1006Identity, validChips1006Read, SCOPE7_SYMBOLS } from './components/StockOverview'
import { validFocusDate, minLotsShares, minTurnoverValue, minRangeMilliPct, validPriceFocusDayMove } from './priceFocus'

export const JOINT_FOCUS_VERSION = 'price-saved-chips-focus/m1-v1'
export const JOINT_FOCUS_POLICY = 'm1-saved-price-chips-focus-tpex-2026-10-06.1'
export const JOINT_FOCUS_DIGEST = 'sha256:1b48fc6bb23b021f3d289c797b8d077af4576f492cbc08953d0515ef0da89416'
export const CALENDAR_FOCUS_VERSION = 'price-saved-chips-focus-calendar/m1-v2'
export const CALENDAR_FOCUS_POLICY = 'm1-saved-price-chips-focus-calendar-tpex-2026-10-06.2'
export const CALENDAR_FOCUS_DIGEST = 'sha256:42c232a3f533683dce727ce1279e767038a6ee0f6295ce85b5aee07e998972bc'
export const SCOPE7_FOCUS_VERSION = 'price-saved-chips-focus-stock-scope-7/m1-v1'
export const SCOPE7_FOCUS_POLICY = 'm1-saved-price-chips-focus-stock-scope-7-tpex-2026-10-06.1'
export const SCOPE7_FOCUS_DIGEST = 'sha256:2f6d3a91337363e5700d7fdf6c16c63b8a14f45362d4407c8b73b01dabfe860e'
export { SCOPE7_SYMBOLS }
export const JOINT_KEYS = ['as_of', 'min_lots', 'day_move', 'min_turnover', 'min_range_pct', 'investor', 'horizon', 'min_net_lots'] as const
export const JOINT_SYMBOLS = ['3105', '6488']
export type JointConditions = Record<typeof JOINT_KEYS[number], string>
export type JointFocusItem = Omit<PriceSavedFocusData['items'][number], 'reasons'> & {
  investor: string; horizon: string; net_shares: string; min_net_lots: string; min_net_shares: string; reasons: string[]
}
export type JointFocusData = JointConditions & {
  version: string; policy_version: string; policy_digest: string; min_net_shares: string
  status: 'available' | 'unavailable'; count: number | null; items: JointFocusItem[]
  price: PriceSavedFocusData | null; institutional: InstitutionalWindowsData[]
  price_ready: boolean; chips_ready: boolean; capture_attempted: boolean; can_capture: boolean
  reasons: string[]; sort: string; supported_symbols: string[]; excluded_price_symbols: string[]; historical_pit: string
}
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

export function netLotsShares(raw: unknown): string | null {
  if (typeof raw !== 'string' || raw.length > 21 || !/^-?(0|[1-9][0-9]*)(\.[0-9]{1,3})?$/.test(raw)) return null
  const [whole, fraction = ''] = raw.replace(/^-/, '').split('.')
  let value = BigInt(whole) * 1000n + BigInt(fraction.padEnd(3, '0'))
  if (raw.startsWith('-')) { if (value === 0n) return null; value = -value }
  return value >= -9223372036854775808n && value <= 9223372036854775807n ? String(value) : null
}

export function validJointConditions(value: JointConditions): boolean {
  return same(Object.keys(value).sort(), [...JOINT_KEYS].sort()) && JOINT_KEYS.every((key) => typeof value[key] === 'string' && value[key].length > 0)
    && validFocusDate(value.as_of) && minLotsShares(value.min_lots) !== null && validPriceFocusDayMove(value.day_move)
    && minTurnoverValue(value.min_turnover) !== null && minRangeMilliPct(value.min_range_pct) !== null
    && ['foreign', 'trust', 'dealer'].includes(value.investor) && ['5', '20'].includes(value.horizon) && netLotsShares(value.min_net_lots) !== null
}

export function jointParams(params: URLSearchParams): JointConditions | null {
  if ([...params].length !== 8 || JOINT_KEYS.some((key) => params.getAll(key).length !== 1)) return null
  const value = Object.fromEntries(params) as JointConditions
  return validJointConditions(value) ? value : null
}

export function jointDetailPath(symbol: string, value: JointConditions, calendar = false, scope7 = false): string {
  return `/stocks/TPEx/${symbol}?${new URLSearchParams({ as_of: value.as_of, from: scope7 ? 'price-saved-chips-focus-stock-scope-7' : calendar ? 'price-saved-chips-focus-calendar' : 'price-saved-chips-focus', source_mode: 'private_saved',
    ...Object.fromEntries(JOINT_KEYS.map((key) => [`focus_${key}`, value[key]])) })}`
}

export function jointReturnPath(params: URLSearchParams, calendar = false, scope7 = false): string | null {
  const allowed = ['as_of', 'from', 'source_mode', ...JOINT_KEYS.map((key) => `focus_${key}`)]
  if ([...params].length !== 11 || allowed.some((key) => params.getAll(key).length !== 1)
    || params.get('from') !== (scope7 ? 'price-saved-chips-focus-stock-scope-7' : calendar ? 'price-saved-chips-focus-calendar' : 'price-saved-chips-focus') || params.get('source_mode') !== 'private_saved') return null
  const values = Object.fromEntries(JOINT_KEYS.map((key) => [key, params.get(`focus_${key}`)!])) as JointConditions
  return params.get('as_of') === values.as_of && values.as_of === '2026-10-06' && validJointConditions(values)
    ? `/saved-price-chips-focus${scope7 ? '-stock-scope-7' : calendar ? '-calendar' : ''}?${new URLSearchParams(values)}` : null
}

export function jointDetailContext(exchange: string, symbol: string, params: URLSearchParams, calendar = false, scope7 = false): boolean {
  return exchange === 'TPEx' && (scope7 ? SCOPE7_SYMBOLS : JOINT_SYMBOLS).includes(symbol) && jointReturnPath(params, calendar, scope7) !== null
}

export function jointDetailEvidenceInvalid(data: InstitutionalWindowsData, exchange: string, symbol: string, cutoff: string, calendar = false, scope7 = false): boolean {
  const evidence = data.calendar?.status === 'available' || Object.values(data.windows ?? {}).some((window) => window?.values != null || (window?.daily_evidence?.length ?? 0) > 0)
  return !validChips1006Identity(data, exchange, symbol, cutoff, calendar, scope7)
    || Boolean(data.capture_state?.attempted || evidence) && (data.status !== 'available' || !validChips1006Read(data, exchange, symbol, cutoff, calendar, scope7))
}

export function validJointFocus(value: unknown, conditions: JointConditions, calendar = false, scope7 = false): value is JointFocusData {
  const symbols = scope7 ? SCOPE7_SYMBOLS : JOINT_SYMBOLS
  try {
    if (!value || typeof value !== 'object' || Array.isArray(value) || !validJointConditions(conditions)) return false
    const data = value as JointFocusData
    if (data.version !== (scope7 ? SCOPE7_FOCUS_VERSION : calendar ? CALENDAR_FOCUS_VERSION : JOINT_FOCUS_VERSION) || data.policy_version !== (scope7 ? SCOPE7_FOCUS_POLICY : calendar ? CALENDAR_FOCUS_POLICY : JOINT_FOCUS_POLICY) || data.policy_digest !== (scope7 ? SCOPE7_FOCUS_DIGEST : calendar ? CALENDAR_FOCUS_DIGEST : JOINT_FOCUS_DIGEST)
      || JOINT_KEYS.some((key) => data[key] !== conditions[key]) || data.min_net_shares !== netLotsShares(conditions.min_net_lots)
      || data.sort !== 'code_ascending' || data.historical_pit !== 'unsupported' || !same(data.supported_symbols, symbols)
      || !same(data.excluded_price_symbols, scope7 ? [] : ['3293', '5274', '5347', '6510', '8069'])
      || !Array.isArray(data.items) || !Array.isArray(data.institutional) || !Array.isArray(data.reasons)
      || !data.reasons.every((reason) => typeof reason === 'string') || !['price_ready', 'chips_ready', 'capture_attempted', 'can_capture'].every((key) => typeof data[key as keyof JointFocusData] === 'boolean')) return false
    if (data.status === 'unavailable') return data.count === null && data.items.length === 0 && data.price === null && data.institutional.length === 0
      && !data.chips_ready && data.reasons.length > 0 && (!data.price_ready || data.as_of === '2026-10-06')
      && data.can_capture === (data.price_ready && !data.capture_attempted)
    if (data.status !== 'available' || data.as_of !== '2026-10-06' || !data.price_ready || !data.chips_ready || !data.capture_attempted || data.can_capture
      || data.reasons.length || !data.price || !validSavedPriceFocus(data.price, data.as_of, data.min_lots, data.day_move as PriceFocusDayMove, data.min_turnover, data.min_range_pct)
      || data.price.status !== 'available' || data.institutional.length !== symbols.length) return false
    for (let index = 0; index < symbols.length; index++) {
      const read = data.institutional[index]
      if (read.status !== 'available' || !validChips1006Read(read, 'TPEx', symbols[index], data.as_of, calendar, scope7)
        || read.provenance?.captured_versions.length !== 22
        || !['5', '20'].every((horizon) => read.windows?.[horizon]?.status === 'available' && read.windows[horizon]?.missing_dates.length === 0)) return false
    }
    if (data.institutional.some((read) => !same(data.institutional[0].calendar, read.calendar) || !same(data.institutional[0].provenance, read.provenance))) return false
    const expected = data.price.items.filter((item) => symbols.includes(item.symbol)).filter((item) => {
      const read = data.institutional[symbols.indexOf(item.symbol)]
      const net = read.windows![data.horizon].values![data.investor as 'foreign' | 'trust' | 'dealer']
      return BigInt(net) >= BigInt(data.min_net_shares)
    })
    return Number.isInteger(data.count) && data.count === data.items.length && expected.length === data.items.length && expected.every((item, index) => {
      const net = data.institutional[symbols.indexOf(item.symbol)].windows![data.horizon].values![data.investor as 'foreign' | 'trust' | 'dealer']
      return same(data.items[index], { ...item, investor: data.investor, horizon: data.horizon, net_shares: net, min_net_lots: data.min_net_lots,
        min_net_shares: data.min_net_shares, reasons: [...item.reasons, 'selected_net_at_least_min_net_lots'], detail_url: jointDetailPath(item.symbol, conditions, calendar, scope7) })
    })
  } catch { return false }
}

export type FocusGeneration = { token: string; epoch: number; failure: string | null; price: boolean; chips: boolean }
export function focusTransition(state: FocusGeneration, token: string, epoch: number, source: 'price' | 'chips' | 'joint' | 'failure'): FocusGeneration {
  if (state.token !== token || source !== 'failure' && state.epoch !== epoch) return state
  if (source === 'failure') return { token, epoch: state.epoch + 1, failure: 'joint_source_validation_failed', price: false, chips: false }
  const next = { ...state, price: state.price || source === 'price' || source === 'joint', chips: state.chips || source === 'chips' || source === 'joint' }
  return { ...next, failure: next.price && next.chips ? null : next.failure }
}
