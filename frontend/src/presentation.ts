import type { ProductTime, ProductTimeRole } from './types'

const INCOMPLETE_ACTION_STATES = new Set(['data_insufficient', 'data_incomplete', 'insufficient_data'])

const REASON_LABELS: Record<string, string> = {
  passed: '此研究條件已符合',
  rejected: '此研究條件尚未成立',
  data_incomplete: '此研究條件資料待補',
  observation: '條件尚未成立，持續觀察',
  conditional: '符合條件後可研究進場',
  active: '研究追蹤中',
  target_1_hit: '已達到第一目標',
  target_2_hit: '已達到第二目標',
  invalidated: '研究條件已失效',
  expired: '研究條件已到期',
  incomparable: '目前資料無法比較',
  settled: '研究追蹤已結束',
  invalid_levels: '研究價位無法驗證',
  prior_20_highs_missing_or_invalid: '前 20 個交易日高點資料待補',
  prior_20_volumes_missing_or_invalid: '前 20 個交易日成交量資料待補',
  close_missing_or_non_finite: '最近收盤資料待補',
  volume_missing_or_non_finite: '當日成交量資料待補',
  ma20_missing_or_non_finite: '20 日均線資料待補',
  ma60_missing_or_non_finite: '60 日均線資料待補',
  close_not_above_prior_20_day_high: '收盤尚未站上前 20 日高點',
  volume_ratio_below_1_20: '成交量未達前 20 日均量的 1.2 倍',
  ma20_not_above_ma60: 'MA20 尚未高於 MA60',
  close_below_ma60: '收盤仍低於 MA60',
  close_outside_ma20_support_zone: '收盤不在 MA20 支撐區',
  pullback_volume_ratio_outside_range: '回踩量比不在規則範圍',
  group_relative_strength_not_positive: '族群相對 TAIEX 的 20 日超額報酬未轉正',
  group_excess_return_20d_missing_or_non_finite: '缺少族群相對 TAIEX 的 20 日超額報酬',
  institutional_flow_to_turnover_ratio_5d_missing_or_non_finite: '缺少 5 日法人流向與 20 日日均成交額',
  institutional_flow_5d_missing_or_incomplete: '5 日法人籌碼資料尚未齊備',
  margin_balance_change_ratio_5d_missing_or_non_finite: '缺少 5 日融資餘額變化率',
  margin_change_5d_missing_or_incomplete: '5 日融資變化資料尚未齊備',
  effective_group_score_missing_or_under_minimum_members: '族群資料未達有效成員門檻',
  close_or_volume_must_be_positive: '收盤或成交量資料無法用於計算',
  bar_count_missing_or_invalid: '歷史交易日數資料待核實',
  history_under_60_bars: '近 60 個交易日行情不足',
  price_and_volume_inputs_must_be_positive: '價格、均線或成交量資料無法用於計算',
  institutional_flow_materially_adverse: '法人籌碼未達規則要求',
  margin_financing_increase_abnormal: '融資變化超過規則上限',
  unsupported_instrument_type: '此商品類型暫不適用一般研究規則',
  unsupported_or_missing_etf_category: 'ETF 分類尚待核實',
  etf_category_excluded_from_actionable_signals: '此 ETF 類型暫不適用一般研究訊號',
  etf_category_is_only_valid_for_etf: 'ETF 分類資料待核實',
  ipo_history_under_20_bars: '新上市標的歷史未滿 20 個交易日',
  ipo_observation_only_under_60_bars: '新上市標的歷史未滿 60 個交易日，僅作觀察',
  unsupported_entry_type: '研究進場類型無法驗證',
  entry_price_must_be_finite_and_positive: '研究進場價無法驗證',
  invalid_price_must_be_finite_and_positive: '研究失效價無法驗證',
  invalid_price_must_be_below_entry: '研究失效價與進場價關係無法驗證',
  target_1_must_be_finite_and_positive: '第一目標價無法驗證',
  target_1_must_exceed_entry: '第一目標價與進場價關係無法驗證',
  target_2_must_be_finite_and_positive_when_present: '第二目標價無法驗證',
  target_2_must_exceed_target_1: '第二目標價與第一目標價關係無法驗證',
  minimum_first_target_risk_reward_must_be_finite_and_positive: '風險報酬門檻設定待核實',
  target_1_risk_reward_below_minimum: '第一目標的風險報酬未達規則門檻',
  unsupported_current_status: '研究追蹤狀態無法驗證',
  unsupported_next_status: '研究追蹤狀態無法驗證',
  illegal_signal_status_transition: '研究追蹤狀態無法驗證',
  signal_day_suspended: '訊號日標的處於停牌狀態',
  data_as_of: '尚無可核實的資料日期',
  market_bar: '缺少日行情',
  bars_20d: '缺少 20 日有效行情',
  bars_60d: '缺少 60 日有效行情',
  benchmark: '缺少 TAIEX 基準',
  theme_membership: '缺少有效族群成員關聯',
  qualified_theme: '尚無達到門檻的熱門族群',
  institutional_flow_5d: '缺少 5 日法人籌碼',
  foreign_buy: '缺少外陸資淨買賣超',
  trust_buy: '缺少投信淨買賣超',
  dealer_buy: '缺少自營商淨買賣超',
  margin_balance: '缺少融資餘額',
  margin_change: '缺少融資變化',
  signal_data_quality: '策略訊號資料尚未齊備',
  risk_reward: '風險報酬比未達最低要求',
  invalid_price: '缺少有效失效／停損價',
  target_1: '缺少有效第一目標價',
  rule_not_met: '固定研究條件尚未成立',
  required_inputs_complete: '必要研究資料已齊備',
  required_inputs_complete_: '必要研究資料已齊備',
}

const STRATEGY_LABELS: Record<string, string> = {
  breakout: '突破條件',
  pullback: '回踩條件',
}

const PRODUCT_TIME_ROLE_LABELS: Record<string, string> = {
  market_date: '資料日期',
  event_date: '事件日期',
  event_at: '事件時間',
  published_at: '發布時間',
  first_available_at: '首次可得時間',
  collected_at: '收錄時間',
  revision_available_at: '修訂可得時間',
  decision_at: '決策時間',
  generated_at: '歷史生成時間',
  earliest_execution_at: '規則最早執行時間',
  earliest_execution_date: '規則最早執行日',
}

export function productTimeRoleLabel(role: string): string {
  return PRODUCT_TIME_ROLE_LABELS[role] ?? '時間'
}

export function productTimeRoleKnown(role?: ProductTimeRole | { status?: string; precision?: string; value?: string | null } | null): boolean {
  return role?.status === 'known' && Boolean(role.value) && ['date', 'instant'].includes(role.precision ?? '')
}

function formatCalendarDate(value: string | null | undefined): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value ?? '')
  if (!match) return '待核實'
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  const parsed = new Date(Date.UTC(year, month - 1, day))
  if (parsed.getUTCFullYear() !== year || parsed.getUTCMonth() !== month - 1 || parsed.getUTCDate() !== day) return '待核實'
  return `${match[1]}/${match[2]}/${match[3]}`
}

function validInstantValue(value: string): string | undefined {
  const match = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?(Z|([+-])(\d{2}):(\d{2}))$/.exec(value)
  if (!match) return undefined
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  const hour = Number(match[4])
  const minute = Number(match[5])
  const second = Number(match[6] ?? '0')
  const offsetHour = Number(match[10] ?? '0')
  const offsetMinute = Number(match[11] ?? '0')
  const calendar = new Date(0)
  calendar.setUTCFullYear(year, month - 1, day)
  calendar.setUTCHours(0, 0, 0, 0)
  if (
    calendar.getUTCFullYear() !== year
    || calendar.getUTCMonth() !== month - 1
    || calendar.getUTCDate() !== day
    || hour > 23
    || minute > 59
    || second > 59
    || offsetHour > 23
    || offsetMinute > 59
  ) return undefined
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? undefined : value
}

function formatKnownInstant(value: string): string {
  const validValue = validInstantValue(value)
  if (!validValue) return '待核實'
  const parsed = new Date(validValue)
  if (Number.isNaN(parsed.getTime())) return '待核實'
  return new Intl.DateTimeFormat('zh-TW', {
    timeZone: 'Asia/Taipei',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(parsed)
}

export function formatProductTimeRole(time: ProductTime | undefined, roleName: string, fallbackDate: string | null = null): string {
  const role = time?.roles?.[roleName]
  if (!time && fallbackDate) return formatCalendarDate(fallbackDate)
  if (!productTimeRoleKnown(role)) return '待核實'
  if (role?.precision === 'date') return formatCalendarDate(role.value)
  return formatKnownInstant(role?.utc ?? role?.value ?? '')
}

export function productTimeRoleDateTime(time: ProductTime | undefined, roleName: string): string | undefined {
  const role = time?.roles?.[roleName]
  if (!productTimeRoleKnown(role) || role?.precision !== 'instant') return undefined
  return validInstantValue(role.utc ?? role.value ?? '')
}

export function signalConfidenceLabel(semantics?: { display_label_zh?: string } | null): string {
  const label = semantics?.display_label_zh?.trim()
  return label || '未校準；非預測勝率'
}

export function levelFieldLabel(
  field: string,
  semantics?: { version?: string; kind?: string; fields?: Record<string, { label_zh?: string }> } | null,
): string {
  if (semantics?.version !== 'signal-level-semantics/v1' || semantics.kind !== 'rule_reference') return '價位（語意未確認）'
  const label = semantics?.fields?.[field]?.label_zh?.trim()
  return label || '價位（語意未確認）'
}

export function levelSemanticsLabel(semantics?: { version?: string; kind?: string } | null): string {
  return semantics?.version === 'signal-level-semantics/v1' && semantics.kind === 'rule_reference' ? '規則參考價' : '未驗證規則參考價'
}

export function levelObservationZoneLabel(semantics?: { version?: string; kind?: string } | null): string {
  return semantics?.version === 'signal-level-semantics/v1' && semantics.kind === 'rule_reference' ? '規則回踩觀察區' : '回踩觀察區（語意未確認）'
}

export function stopPriceFieldLabel(semantics?: { kind?: string; origin?: string | null } | null): string {
  if (semantics?.kind === 'user_position_risk_input' && semantics.origin === 'portfolio_position.stop_price') return '持倉設定風險價'
  if (semantics?.kind === 'rule_reference' && semantics.origin === 'signal.invalid_price') return '規則失效參考價'
  return '風險價位（語意待核實）'
}

function reasonCodeLabel(code: string): string {
  const normalized = code.trim().replace(/[^A-Za-z0-9_]/g, '')
  if (!normalized) return ''
  if (REASON_LABELS[normalized]) return REASON_LABELS[normalized]
  if (normalized.endsWith('_missing_or_non_finite')) {
    const base = normalized.slice(0, -'_missing_or_non_finite'.length)
    if (REASON_LABELS[base]) return REASON_LABELS[base] + '（資料缺漏或無效）'
  }
  if (normalized.includes('required') && normalized.includes('complete')) return '必要研究資料已齊備'
  if (normalized.includes('missing') || normalized.includes('incomplete')) return '必要研究資料尚未齊備'
  if (normalized === 'rejected' || normalized === 'observation') return '固定研究條件尚未成立'
  return ''
}

function strategyStateLabel(value: string): string {
  return ({ passed: '已成立', conditional: '條件成立', observation: '未成立、持續觀察', rejected: '未成立', data_incomplete: '資料待補' }[value] ?? '狀態待核實')
}

function translateStructuredReason(value: string): string | null {
  const equal = value.indexOf('=')
  if (equal <= 0) return null
  const key = value.slice(0, equal).trim().toLowerCase()
  const rest = value.slice(equal + 1).trim()
  if (key === 'group') {
    return rest.toLowerCase() === 'missing' ? '族群條件待補' : '族群條件已核對'
  }
  if (key === 'missing') {
    const labels = rest.split(',').map(reasonCodeLabel).filter(Boolean)
    return labels.length ? '待補資料：' + labels.join('、') : '必要研究資料尚未齊備'
  }
  if (key === 'breakout' || key === 'pullback') {
    const [state, ...reasonParts] = rest.split(':')
    const labels = reasonParts.join(':').split(',').map(reasonCodeLabel).filter(Boolean)
    const strategy = STRATEGY_LABELS[key]
    return `${strategy}：${strategyStateLabel(state)}${labels.length ? '（' + labels.join('、') + '）' : ''}`
  }
  return null
}

export function stockDirectoryActionLabel(actionState?: string, actionLabel?: string): string {
  const state = actionState?.trim().toLowerCase() ?? ''
  const label = actionLabel?.trim() ?? ''
  if (INCOMPLETE_ACTION_STATES.has(state) || label === '資料不足') return '暫不行動'
  return label || '尚無研究動作'
}

export function stockDirectoryQualityLabel(dataQuality?: string): string {
  return dataQuality?.trim().toLowerCase() === 'complete' ? '可用' : '待補'
}

export function productActionReasonLabel(reason: string): string {
  const value = reason.trim()
  if (!value) return '固定研究條件尚未成立'
  if (value === '目前資料不足，不能把此標的包裝成可執行條件') return '策略判斷資料尚未齊備，暫時不能形成可執行條件'
  if (value === 'required inputs complete') return '必要研究資料已齊備'
  const structured = translateStructuredReason(value)
  if (structured) return structured
  if (value.includes(';')) {
    const parts = value.split(';').map((part) => productActionReasonLabel(part)).filter(Boolean)
    return parts.join('；')
  }
  const mapped = reasonCodeLabel(value)
  if (mapped) return mapped
  const colon = value.indexOf(':')
  if (colon > 0) {
    const base = reasonCodeLabel(value.slice(0, colon))
    if (base) return base
  }
  if (value.includes('資料不足')) return value.replace(/資料不足/g, '資料尚未齊備')
  if (/^[\x00-\x7F]*$/.test(value) && /[A-Za-z]/.test(value)) return '研究條件需要人工核對'
  return value
}

export function productResearchDescription(status?: string, missingFields: string[] = []): string {
  const visibleMissing = missingFields.filter(Boolean).slice(0, 4)
  if (visibleMissing.length > 0) return '策略判斷缺少：' + visibleMissing.join('、')
  return status?.trim().toLowerCase() === 'complete'
    ? '策略判斷資料已齊備；是否有條件成立仍以行動摘要為準。'
    : '策略判斷資料仍待補；目前沒有可列出的欄位。'
}

export type ProductQualityKind = 'market' | 'research' | 'theme' | 'generic'

export function productQualityLabel(dataQuality?: string, kind: ProductQualityKind = 'generic'): string {
  const status = dataQuality?.trim().toLowerCase() ?? 'unknown'

  if (kind === 'market') {
    if (['complete', 'success', 'official', 'official_snapshot'].includes(status)) return '行情來源完整'
    if (status === 'unknown') return '行情來源待核實'
    return '行情來源待補'
  }

  if (kind === 'research') {
    return status === 'complete' ? '策略判斷資料完整' : '策略判斷資料待補'
  }

  if (kind === 'theme') {
    if (status === 'complete') return '族群資料完整'
    if (status === 'insufficient_members') return '族群成員不足'
    if (status === 'unknown') return '族群資料待核實'
    return '族群資料待補'
  }

  if (status === 'official_snapshot') return '官方快照'
  if (status === 'complete') return '資料品質完整'
  if (status === 'unknown') return '資料品質待核實'
  return '資料品質待補'
}
