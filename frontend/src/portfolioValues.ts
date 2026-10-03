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
