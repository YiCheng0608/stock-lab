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
  if (status === 'local_estimate' && known && (field !== 'market_value' || value >= 0)) return '行情待核實'
  if (value === null) {
    if (status === 'missing') return '未提供'
    if (status === 'quantity_unknown') return '股數待核實'
    if (status === 'precision_unsupported') return '估值精度待支援'
  }
  return '待核實'
}

function recordObject(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

/** Only the explicitly scoped inspection view can show an unverified trial. */
export function formatLocalPositionValuation(value: unknown, metadata: unknown, field: 'market_value' | 'unrealized_pnl'): string {
  if (recordObject(metadata)?.[field] === 'local_estimate' && typeof value === 'number' && Number.isFinite(value)
    && (field !== 'market_value' || value >= 0)) {
    const formatted = Math.abs(value).toLocaleString('zh-TW', { maximumFractionDigits: 2 })
    return field === 'unrealized_pnl' && value > 0 ? `+${formatted}` : value < 0 ? `-${formatted}` : formatted
  }
  // Explicit unknown/invalid states are never rescued by a numeric value.
  if (value === null) return formatPositionValuation(value, metadata, field)
  return '待核實'
}

export function formatPortfolioClose(metadata: unknown, inspection = false): string {
  const quote = recordObject(metadata)
  if (!quote || quote.source_verification !== 'unverified' || quote.date_verification !== 'unverified') return '行情待核實'
  if (quote.close_status === 'known' && typeof quote.close === 'number' && Number.isFinite(quote.close) && quote.close > 0) {
    return inspection ? quote.close.toLocaleString('zh-TW', { maximumFractionDigits: 2 }) : '行情待核實'
  }
  if (quote.close === null && quote.close_status === 'missing') return '未提供行情'
  if (quote.close === null && quote.close_status === 'invalid') return '行情數值待核實'
  return '行情待核實'
}

function recordedDate(text: string): boolean {
  if (!/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(text)) return false
  const [year, month, day] = text.split('-').map(Number)
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
  return year >= 1 && month >= 1 && month <= 12 && day >= 1 && day <= days[month - 1]
}

function recordedText(value: string, field: 'date' | 'source' | 'data_as_of' | 'collected_at'): boolean {
  if (/[\x00-\x1f\x7f]/.test(value) || Array.from(value).some((char) => {
    const point = char.codePointAt(0)!
    return point >= 0xd800 && point <= 0xdfff
  })) return false
  if (field === 'source') return Array.from(value).length <= 120 && !/^[\s\u0085]*$/.test(value)
  if (field === 'date') return recordedDate(value)
  if (value.length > 64 || !recordedDate(value.slice(0, 10))) return false
  const time = /^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ]([0-9]{2}):([0-9]{2}):([0-9]{2})(?:[.,][0-9]+)?(?:Z|[+-]([0-9]{2}):([0-9]{2})(?::([0-9]{2})(?:[.,][0-9]+)?)?)?$/.exec(value)
  return Boolean(time && Number(time[1]) < 24 && Number(time[2]) < 60 && Number(time[3]) < 60
    && (time[4] === undefined || (Number(time[4]) < 24 && Number(time[5]) < 60 && (time[6] === undefined || Number(time[6]) < 60))))
}

/** Known here describes recorded text only; it is never source/date evidence. */
export function formatQuoteRecord(metadata: unknown, field: 'date' | 'source' | 'data_as_of' | 'collected_at'): string {
  const quote = recordObject(metadata)
  if (!quote || quote.source_verification !== 'unverified' || quote.date_verification !== 'unverified') return '記錄待核實'
  const value = recordObject(quote.recorded)?.[field]
  const status = recordObject(quote.record_status)?.[field]
  if (status === 'known' && typeof value === 'string' && recordedText(value, field)) return value
  if (status === 'missing' && value === null) return '記錄未提供'
  return '記錄待核實'
}
