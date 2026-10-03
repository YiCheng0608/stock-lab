/** Parse an optional user value before JSON can silently replace Infinity. */
export function portfolioValueFromText(text: string, label: string): number | null {
  if (text === '') return null
  const decimal = /^(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)$/.exec(text)
  if (!decimal || decimal[0] !== text) {
    throw new Error(`${label}請輸入非負十進小數，留空表示未提供。`)
  }
  const value = Number(text)
  if (!Number.isFinite(value) || (value === 0 && /[1-9]/.test(text))) {
    throw new Error(`${label}數值超出可保存範圍。`)
  }
  return value
}

export function assertPortfolioValue(value: unknown, label: string): void {
  if (value !== null && value !== undefined &&
    (typeof value !== 'number' || !Number.isFinite(value) || value < 0)) {
    throw new Error(`${label}必須是有限非負數值，或留空表示未提供。`)
  }
}

/** An explicit read status must agree with the value; only old APIs omit it. */
export function formatPortfolioValue(value: unknown, metadata: unknown, field: 'average_cost' | 'stop_price' | 'risk_budget'): string {
  const known = typeof value === 'number' && Number.isFinite(value) && value >= 0
  let status: unknown = value === null ? 'missing' : known ? 'known' : 'invalid'
  if (metadata !== undefined) {
    status = metadata !== null && typeof metadata === 'object' && !Array.isArray(metadata)
      ? (metadata as Record<string, unknown>)[field] : 'invalid'
  }
  if (status === 'known' && known) {
    return (value === 0 ? 0 : value).toLocaleString('zh-TW', { maximumFractionDigits: 2 })
  }
  if (status === 'missing' && value === null) return '未提供'
  return '待核實'
}

/** Estimates must agree with their explicit read status; do not rescue it. */
export function formatPositionValuation(value: unknown, metadata: unknown, field: 'market_value' | 'unrealized_pnl'): string {
  const known = typeof value === 'number' && Number.isFinite(value)
  let status: unknown = value === null ? 'missing' : known ? 'known' : 'invalid'
  if (metadata !== undefined) {
    status = metadata !== null && typeof metadata === 'object' && !Array.isArray(metadata)
      ? (metadata as Record<string, unknown>)[field] : 'invalid'
  }
  if (status === 'known' && known) {
    const formatted = Math.abs(value).toLocaleString('zh-TW', { maximumFractionDigits: 2 })
    return field === 'unrealized_pnl' && value > 0 ? `+${formatted}` : value < 0 ? `-${formatted}` : formatted
  }
  if (value === null) {
    if (status === 'missing') return '未提供'
    if (status === 'quantity_unknown') return '股數待核實'
    if (status === 'precision_unsupported') return '估值精度待支援'
  }
  return '待核實'
}
