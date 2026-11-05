import { formatPrice } from '../candidates/candidates'
import { productActionReasonLabel } from '../presentation'
import type { ActionNearnessItem, GapReason, StrategyBoardRow, StrategyBoardStatus, StrategyCondition, StrategyObservationLevels } from '../types'
import { LOT_SIZE, formatFixed } from '../units'

// Pure helpers for the stock strategy board (#274); copy follows UI_COPY_SPEC §10.1, visuals DESIGN_SYSTEM §7.
// CONDITIONS is the frontend's one condition table: the action list's 「差：…」 lines read it too (#277-B).

export const BOARD_TITLE = '策略總表'
export const BOARD_NOTE = '每個研究條件各自判定；「觀察價位」是條件尚未成立時，下一交易日收盤與成交量要達到的參考值，不是建議進出點。'
export const OBSERVATION_LABEL = '條件未成立・觀察價位'
// #519: the candidate row's fold for the reasons and the AI note (UI_COPY_SPEC §10 個股頁候選列).
export const CANDIDATE_MORE_LABEL = '理由與 AI 進出點說明'
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

const isNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const percent = (value: unknown, signed = true) => isNumber(value) ? `${formatFixed(value * 100, 2, signed)}%` : '—'
const ratio = (value: unknown) => isNumber(value) ? `${formatFixed(value, 2)} 倍` : '—'
// Whole lots for a volume bound: a minimum rounds up and a maximum down, so the shown bound is never looser than the
// rule's share count (#274 review L2); flows and holdings round as UI_COPY_SPEC §8.3.
const lotBound = (value: unknown, round: 'up' | 'down') => isNumber(value) && Number.isSafeInteger(value) && value >= 0
  ? (round === 'up' ? Math.ceil(value / LOT_SIZE) : Math.floor(value / LOT_SIZE)).toLocaleString('zh-TW')
  : '—'
export const minLots = (value: unknown) => `${lotBound(value, 'up')} 張`
export const lotRange = (low: unknown, high: unknown) => `${lotBound(low, 'up')}～${lotBound(high, 'down')} 張`

const OPERATORS: Record<string, string> = { gt: '>', gte: '≥', lt: '<', lte: '≤' }

// A condition's rule bound from the API's own threshold and operator (#274 review L3): no rule number is written here,
// so a new strategy version's thresholds show as they are. null when the condition carries none.
type Bounded = Pick<StrategyCondition, 'threshold' | 'threshold_high' | 'operator'>
function bound(item: Bounded | undefined, format: (value: number) => string, unit: string): string | null {
  if (!item || !isNumber(item.threshold)) return null
  if (item.operator === 'between') return isNumber(item.threshold_high) ? `${format(item.threshold)}～${format(item.threshold_high)}${unit}` : null
  const symbol = OPERATORS[item.operator ?? '']
  return symbol ? `${symbol} ${format(item.threshold)}${unit}` : null
}
const two = (value: number) => formatFixed(value, 2)
const share = (value: number) => formatFixed(value * 100, 2)

// near: the action list's 「差：」 line of a near card (UI_COPY_SPEC §10.1), only for the conditions that can be near.
type ConditionCopy = {
  label: (item?: StrategyCondition) => string
  unmet: (item?: StrategyCondition) => string
  near?: (item: ActionNearnessItem) => string
}
const fixed = (label: string, unmet: string): ConditionCopy => ({ label: () => label, unmet: () => unmet })
// A near card's price gap: the next session's distance, unsigned (the sentence says the side).
const gapText = (gap: unknown) => isNumber(gap) ? `${formatFixed(Math.abs(gap) * 100, 2)}%` : '差距待核實'
const nearVolume = (item: ActionNearnessItem) => `量能 ${bound(item, two, ' 倍') ?? '達規則門檻'}（今日 ${ratio(item.actual)}）`

const CONDITIONS: Record<string, ConditionCopy> = {
  eligibility: fixed('適用標的', '標的不適用'),
  required_inputs: fixed('必要資料齊備', '資料不足'),
  breakout_price: { ...fixed('收盤突破前 20 日高點', '收盤未突破前 20 日高點'), near: (item) => `收盤站上前 20 日高點（還差 ${gapText(item.gap)}）` },
  breakout_volume: {
    label: (item) => `量比 ${bound(item, two, ' 倍') ?? '達規則門檻'}`,
    unmet: (item) => isNumber(item?.threshold) ? `量比未達 ${two(item.threshold)} 倍` : '量比未達規則門檻',
    near: nearVolume,
  },
  pullback_history: {
    label: (item) => isNumber(item?.threshold) ? `日線滿 ${item.threshold} 日` : '日線達規則日數',
    unmet: (item) => isNumber(item?.threshold) ? `日線未滿 ${item.threshold} 日` : '日線未達規則日數',
  },
  pullback_trend: fixed('20 日均線在 60 日均線之上', '20 日均線未站上 60 日均線'),
  pullback_above_ma60: fixed('收盤不低於 60 日均線', '收盤低於 60 日均線'),
  pullback_support_zone: {
    ...fixed('收盤在 20 日均線支撐區', '收盤不在支撐區'),
    // inside: T's close was outside T's zone but is inside the next session's (the zone moves with MA20).
    near: (item) => {
      const side = item.position === 'above' ? `高於上緣 ${gapText(item.gap)}` : item.position === 'below' ? `低於下緣 ${gapText(item.gap)}` : item.position === 'inside' ? '最近收盤已在下一交易日的區間內' : null
      return `收盤回到 20 日均線支撐區${side ? `（${side}）` : ''}`
    },
  },
  pullback_volume: {
    label: (item) => `量比 ${bound(item, two, ' 倍') ?? '在規則區間'}`,
    unmet: (item) => { const range = bound(item, two, ' 倍'); return range ? `量比不在 ${range}` : '量比不在規則區間' },
    near: nearVolume,
  },
  group_relative_strength: { label: (item) => `族群 20 日超額報酬 ${bound(item, share, '%') ?? '達規則門檻'}`, unmet: () => '族群未強於大盤' },
  institutional_flow: { label: (item) => `法人 5 日淨額 ÷ 20 日均量 ${bound(item, share, '%') ?? '達規則門檻'}`, unmet: () => '法人籌碼未達要求' },
  margin_financing: { label: (item) => `融資 5 日變動 ${bound(item, share, '%') ?? '在規則上限內'}`, unmet: () => '融資增加超過上限' },
}
const UNKNOWN_CONDITION = '研究條件需要人工核對'
// The registry's condition codes as this table words them (backend/tests/test_condition_copy_source.py checks the set).
export const CONDITION_CODES: readonly string[] = Object.keys(CONDITIONS)

export function conditionLabel(item: StrategyCondition): string {
  return CONDITIONS[item.code]?.label(item) ?? UNKNOWN_CONDITION
}

export function unmetLabel(code: string, item?: StrategyCondition): string {
  return CONDITIONS[code]?.unmet(item) ?? UNKNOWN_CONDITION
}

// 「差：…」 of one unmet condition of a near action card; a condition without a near sentence uses its unmet phrase.
export function nearLine(item: ActionNearnessItem): string {
  const copy = CONDITIONS[item.code]
  return `差：${copy?.near ? copy.near(item) : copy ? copy.unmet() : UNKNOWN_CONDITION}`
}

// The topic of a signal's data reason (backend/app/gap_reasons.py) and the summary's cause codes that explain it.
const GAP_TOPICS: ReadonlyArray<{ reasons: ReadonlySet<string>; causes: ReadonlySet<string> }> = [
  {
    reasons: new Set(['institutional_flow_to_turnover_ratio_5d_missing_or_non_finite', 'institutional_flow_5d_missing_or_incomplete']),
    causes: new Set(['institutional_not_listed', 'institutional_not_collected']),
  },
  {
    reasons: new Set(['margin_balance_change_ratio_5d_missing_or_non_finite', 'margin_change_5d_missing_or_incomplete']),
    causes: new Set(['margin_not_listed', 'margin_not_collected', 'margin_zero_base']),
  },
  {
    reasons: new Set(['history_under_60_bars', 'ipo_history_under_20_bars', 'ipo_observation_only_under_60_bars', 'bar_count_missing_or_invalid',
      'prior_20_highs_missing_or_invalid', 'prior_20_volumes_missing_or_invalid', 'close_missing_or_non_finite', 'volume_missing_or_non_finite',
      'ma20_missing_or_non_finite', 'ma60_missing_or_non_finite']),
    causes: new Set(['coverage_baseline_unknown', 'listed_under_threshold', 'suspended_or_no_trade', 'official_no_trade', 'bar_invalid', 'quote_not_listed', 'missing_bar_dates']),
  },
  { reasons: new Set(['group_excess_return_20d_missing_or_non_finite']), causes: new Set(['group_return_unavailable']) },
]
// A stock listed fewer than 20 sessions ago has no group return or chip ratios either: its listing explains them.
const SHORT_LISTING_REASONS = new Set(['group_excess_return_20d_missing_or_non_finite', 'institutional_flow_to_turnover_ratio_5d_missing_or_non_finite',
  'margin_balance_change_ratio_5d_missing_or_non_finite', 'margin_change_5d_missing_or_incomplete'])

// An incomplete row's sentences (UI_COPY_SPEC §10.1, Issue 524): each missing input in the summary's own words for its
// topic (an official table without the stock, a short listing, a gap still to backfill), else the input's label.
function incompleteSentences(row: StrategyBoardRow, gapReasons: ReadonlyArray<GapReason> | undefined): string[] {
  const causes = gapReasons ?? []
  const lines = row.missing.flatMap((code, index) => {
    const base = code.split(':', 1)[0]
    const topic = GAP_TOPICS.find((item) => item.reasons.has(base))
    let found = topic ? causes.filter((cause) => topic.causes.has(cause.code)) : []
    if (!found.length && SHORT_LISTING_REASONS.has(base)) found = causes.filter((cause) => cause.code === 'listed_under_threshold')
    if (found.length) return found.map((cause) => cause.label)
    const label = row.missing_labels.length === row.missing.length ? row.missing_labels[index] : productActionReasonLabel(code)
    return label ? [label] : []
  })
  const unique = [...new Set(lines.filter(Boolean))]
  return unique.length ? unique : row.missing_labels
}

// 「差哪個條件」: one line per row. gapReasons are the stock summary's causes (decision_summary.gap_reasons).
export function unmetText(row: StrategyBoardRow, gapReasons?: ReadonlyArray<GapReason>): string {
  if (row.status === 'conditional') return '全部達成'
  if (row.status === 'not_applicable') return row.missing_labels.length ? row.missing_labels.join('、') : '原因待核實'
  if (row.status === 'data_incomplete') {
    const lines = incompleteSentences(row, gapReasons)
    return `無法判斷：${lines.length ? lines.join('；') : '原因待核實'}`
  }
  if (row.levels_missing && row.conditions.length === 0) return '條件明細未產生'
  return row.unmet.length ? row.unmet.map((code) => unmetLabel(code, row.conditions.find((item) => item.code === code))).join('、') : '條件明細待核實'
}

export type ConditionView = { code: string; state: 'met' | 'unmet' | 'unknown' | 'not_applicable'; stateText: string; label: string; value: string; next: string | null }

const STATE_TEXT = { met: '已達成', unmet: '未達成', unknown: '無資料', not_applicable: '不適用' } as const
// A condition the rule does not judge for this security (#392: a non-margin security's margin condition).
export const NOT_APPLICABLE_REASONS: readonly string[] = ['margin_financing_not_applicable']

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
      return `下一交易日成交量 ≥ ${minLots(next.min_volume)}`
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

// Also the candidate entry plan's 「完整條件」 (#491): the signal day's judgement only, no next-session line there.
export function conditionViews(row: Pick<StrategyBoardRow, 'conditions'>, reasonLabel: (code: string) => string): ConditionView[] {
  return row.conditions.map((item) => {
    const notApplicable = item.satisfied == null && item.reasons.some((reason) => NOT_APPLICABLE_REASONS.includes(reason))
    const state = notApplicable ? 'not_applicable' : item.satisfied === true ? 'met' : item.satisfied === false ? 'unmet' : 'unknown'
    const reasons = item.reasons.length ? item.reasons.map(reasonLabel).join('、') : ''
    // Not applicable: the reason says why, not an empty 「—」 value.
    const value = notApplicable ? reasons : conditionValue(item) || reasons
    return { code: item.code, state, stateText: STATE_TEXT[state], label: conditionLabel(item), value, next: state === 'met' || notApplicable ? null : nextSession(item) }
  })
}

// A candidate entry plan's 「完整條件」 (#491): the signal day's judgement, without the eligibility and required-inputs rows.
const ENTRY_SKIPPED_CONDITIONS: readonly string[] = ['eligibility', 'required_inputs']
export function signalDayConditionViews(conditions: readonly StrategyCondition[], reasonLabel: (code: string) => string): ConditionView[] {
  return conditionViews({ conditions: conditions.filter((item) => !ENTRY_SKIPPED_CONDITIONS.includes(item.code)) }, reasonLabel)
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

// The observation box lines (UI_COPY_SPEC §10.1); prices two decimals, volume bounds whole lots (minimum up, maximum down).
export function observationLines(levels: StrategyObservationLevels): LevelLine[] {
  const lines: LevelLine[] = []
  if (isNumber(levels.trigger_price)) lines.push({ key: 'trigger', label: '收盤（元） ≥', value: formatPrice(levels.trigger_price), className: 'level-entry' })
  if (isNumber(levels.zone_low) && isNumber(levels.zone_high)) lines.push({ key: 'zone', label: '收盤（元）', value: `${formatPrice(levels.zone_low)}～${formatPrice(levels.zone_high)}`, className: 'level-entry' })
  if (isNumber(levels.min_volume) && isNumber(levels.max_volume)) lines.push({ key: 'volume', label: '成交量', value: lotRange(levels.min_volume, levels.max_volume) })
  else if (isNumber(levels.min_volume)) lines.push({ key: 'volume', label: '成交量 ≥', value: minLots(levels.min_volume) })
  if (isNumber(levels.invalid_price)) lines.push({ key: 'stop', label: '參考停損（元）', value: formatPrice(levels.invalid_price), className: 'level-stop' })
  if (isNumber(levels.target_1)) lines.push({ key: 'target', label: isNumber(levels.target_2) ? '參考目標一／目標二（元）' : '參考目標一（元）', value: formatPrice(levels.target_1) + (isNumber(levels.target_2) ? `／${formatPrice(levels.target_2)}` : ''), className: 'level-target' })
  return lines
}
