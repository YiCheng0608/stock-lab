import { formatPrice } from '../candidates/candidates'
import type { StrategyBoardRow, StrategyBoardStatus, StrategyCondition, StrategyObservationLevels } from '../types'
import { formatCanonicalShareLots, formatFixed } from '../units'

// Pure helpers for the stock strategy board (#274); copy follows UI_COPY_SPEC §10.1, visuals DESIGN_SYSTEM §7.

export const BOARD_TITLE = '策略總表'
export const BOARD_NOTE = '每個研究條件各自判定；「觀察價位」是條件尚未成立時，下一交易日收盤與成交量要達到的參考值，不是建議進出點。'
export const OBSERVATION_LABEL = '條件未成立・觀察價位'
export const LEVELS_MISSING_TEXT = '觀察價位未產生：這個資料日的條件價位尚未計算或計算失敗。'

export const STATUS_LABELS: Record<StrategyBoardStatus, string> = {
  conditional: '成立',
  observation: '觀察',
  data_incomplete: '資料不足',
  not_applicable: '不適用',
}

// Badge variants (DESIGN_SYSTEM §5): success 成立, primary 觀察, warning 資料不足, default (muted) 不適用.
export const STATUS_TONES: Record<StrategyBoardStatus, 'success' | 'primary' | 'warning' | 'default'> = {
  conditional: 'success',
  observation: 'primary',
  data_incomplete: 'warning',
  not_applicable: 'default',
}

export function statusLabel(status: string): string {
  return STATUS_LABELS[status as StrategyBoardStatus] ?? '狀態待核實'
}

// "v1" from the levels version key (strategy_levels_v1).
export function levelsVersionLabel(version: string): string {
  const match = /_v(\d+)$/.exec(version)
  return match ? `價位規則 v${match[1]}` : '價位規則待核實'
}

type ConditionCopy = { label: string; unmet: string }

const CONDITIONS: Record<string, ConditionCopy> = {
  eligibility: { label: '適用標的', unmet: '標的不適用' },
  required_inputs: { label: '必要資料齊備', unmet: '資料待補' },
  breakout_price: { label: '收盤突破前 20 日高點', unmet: '收盤未突破前 20 日高點' },
  breakout_volume: { label: '量比 ≥ 1.20 倍', unmet: '量比未達 1.20 倍' },
  pullback_history: { label: '日線滿 60 日', unmet: '日線未滿 60 日' },
  pullback_trend: { label: '20 日均線在 60 日均線之上', unmet: '20 日均線未站上 60 日均線' },
  pullback_above_ma60: { label: '收盤不低於 60 日均線', unmet: '收盤低於 60 日均線' },
  pullback_support_zone: { label: '收盤在 20 日均線支撐區（0.97～1.02 倍）', unmet: '收盤不在支撐區' },
  pullback_volume: { label: '量比 0.6～1.2 倍', unmet: '量比不在 0.6～1.2 倍' },
  group_relative_strength: { label: '族群 20 日超額報酬 > 0', unmet: '族群未強於大盤' },
  institutional_flow: { label: '法人 5 日淨額 ≥ −0.3% 均量', unmet: '法人籌碼未達要求' },
  margin_financing: { label: '融資 5 日變動 ≤ 5%', unmet: '融資增加超過上限' },
}
const UNKNOWN_CONDITION = '研究條件需要人工核對'

export function conditionLabel(code: string): string {
  return CONDITIONS[code]?.label ?? UNKNOWN_CONDITION
}

export function unmetLabel(code: string): string {
  return CONDITIONS[code]?.unmet ?? UNKNOWN_CONDITION
}

const isNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const percent = (value: unknown, signed = true) => isNumber(value) ? `${formatFixed(value * 100, 2, signed)}%` : '—'
const ratio = (value: unknown) => isNumber(value) ? `${formatFixed(value, 2)} 倍` : '—'
// Whole lots, rounded half away from zero on the exact share count (UI_COPY_SPEC §8.3).
const lotNumber = (value: unknown) => isNumber(value) && Number.isSafeInteger(value) ? formatCanonicalShareLots(String(value), 1, true) ?? '—' : '—'
const lots = (value: unknown) => `${lotNumber(value)} 張`
const lotRange = (low: unknown, high: unknown) => `${lotNumber(low)}～${lotNumber(high)} 張`

// 「差哪個條件」: one line per row.
export function unmetText(row: StrategyBoardRow): string {
  if (row.status === 'conditional') return '全部達成'
  if (row.status === 'data_incomplete' || row.status === 'not_applicable') {
    const labels = row.missing_labels.length ? row.missing_labels.join('、') : '原因待核實'
    return row.status === 'not_applicable' ? labels : `缺：${labels}`
  }
  if (row.levels_missing && row.conditions.length === 0) return '條件明細未產生'
  return row.unmet.length ? row.unmet.map(unmetLabel).join('、') : '條件明細待核實'
}

export type ConditionView = { code: string; state: 'met' | 'unmet' | 'unknown'; stateText: string; label: string; value: string; next: string | null }

const STATE_TEXT = { met: '已達成', unmet: '未達成', unknown: '無資料' } as const

function conditionValue(item: StrategyCondition): string {
  const { actual, threshold, threshold_high: high } = item
  switch (item.code) {
    case 'eligibility':
    case 'required_inputs':
      return ''
    case 'breakout_price':
      return `收盤 ${formatPrice(actual)}／前 20 日高點 ${formatPrice(threshold)}`
    case 'breakout_volume':
    case 'pullback_volume':
      return `量比 ${ratio(actual)}`
    case 'pullback_history':
      return isNumber(actual) ? `現有 ${actual} 日` : '—'
    case 'pullback_trend':
      return `20 日均線 ${formatPrice(actual)}／60 日均線 ${formatPrice(threshold)}`
    case 'pullback_above_ma60':
      return `收盤 ${formatPrice(actual)}／60 日均線 ${formatPrice(threshold)}`
    case 'pullback_support_zone':
      return `收盤 ${formatPrice(actual)}／支撐區 ${formatPrice(threshold)}～${formatPrice(high)}`
    case 'group_relative_strength':
      return `超額報酬 ${percent(actual)}`
    case 'institutional_flow':
      return `淨額 ÷ 20 日均量 ${percent(actual)}`
    case 'margin_financing':
      return `5 日變動 ${percent(actual)}`
    default:
      return ''
  }
}

function nextSession(item: StrategyCondition): string | null {
  const next = item.next_session
  if (!next) return null
  const gap = isNumber(next.gap) && next.gap !== 0 ? `（距最近收盤 ${percent(next.gap)}）` : ''
  switch (item.code) {
    case 'breakout_price':
      return `下一交易日收盤 ≥ ${formatPrice(next.min_close as number)}${gap}`
    case 'breakout_volume':
      return `下一交易日成交量 ≥ ${lots(next.min_volume)}`
    case 'pullback_trend':
      return `下一交易日收盤 > ${formatPrice(next.min_close as number)}`
    case 'pullback_above_ma60':
      return `下一交易日收盤 ≥ ${formatPrice(next.min_close as number)}`
    case 'pullback_support_zone':
      return `下一交易日收盤 ${formatPrice(next.min_close as number)}～${formatPrice(next.max_close as number)}${gap}`
    case 'pullback_volume':
      return `下一交易日成交量 ${lotRange(next.min_volume, next.max_volume)}`
    default:
      return null
  }
}

export function conditionViews(row: StrategyBoardRow, reasonLabel: (code: string) => string): ConditionView[] {
  return row.conditions.map((item) => {
    const state = item.satisfied === true ? 'met' : item.satisfied === false ? 'unmet' : 'unknown'
    const reasons = item.reasons.length ? item.reasons.map(reasonLabel).join('、') : ''
    const value = conditionValue(item) || reasons
    return { code: item.code, state, stateText: STATE_TEXT[state], label: conditionLabel(item.code), value, next: state === 'met' ? null : nextSession(item) }
  })
}

// Pullback whose trend cannot pass next session: both numbers, no price (#268 design §2).
export function trendUnreachableText(row: StrategyBoardRow): string {
  const find = (code: string) => row.conditions.find((item) => item.code === code)?.next_session
  const trend = find('pullback_trend')?.min_close
  const zone = find('pullback_support_zone')?.max_close
  if (!isNumber(trend) || !isNumber(zone)) return '下一交易日趨勢條件無法成立，不產生觀察價位。'
  return `下一交易日趨勢條件無法成立：收盤需高於 ${formatPrice(trend)} 才能讓 20 日均線站上 60 日均線，但支撐區上緣只有 ${formatPrice(zone)}，不產生觀察價位。`
}

export type LevelLine = { key: string; label: string; value: string; className?: string }

// The observation box lines (UI_COPY_SPEC §10.1); prices two decimals, volume whole lots (§8.3).
export function observationLines(levels: StrategyObservationLevels): LevelLine[] {
  const lines: LevelLine[] = []
  if (isNumber(levels.trigger_price)) lines.push({ key: 'trigger', label: '收盤 ≥', value: formatPrice(levels.trigger_price), className: 'level-entry' })
  if (isNumber(levels.zone_low) && isNumber(levels.zone_high)) lines.push({ key: 'zone', label: '收盤', value: `${formatPrice(levels.zone_low)}～${formatPrice(levels.zone_high)}`, className: 'level-entry' })
  if (isNumber(levels.min_volume) && isNumber(levels.max_volume)) lines.push({ key: 'volume', label: '成交量', value: lotRange(levels.min_volume, levels.max_volume) })
  else if (isNumber(levels.min_volume)) lines.push({ key: 'volume', label: '成交量 ≥', value: lots(levels.min_volume) })
  if (isNumber(levels.invalid_price)) lines.push({ key: 'stop', label: '參考停損', value: formatPrice(levels.invalid_price), className: 'level-stop' })
  if (isNumber(levels.target_1)) lines.push({ key: 'target', label: '參考目標', value: formatPrice(levels.target_1) + (isNumber(levels.target_2) ? `／${formatPrice(levels.target_2)}` : ''), className: 'level-target' })
  return lines
}
