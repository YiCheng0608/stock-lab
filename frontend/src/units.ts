export type ShareUnit = 'lot' | 'odd_lot'

export const LOT_SIZE = 1000

/** A fixed number of decimals, so one column lines up (DESIGN_SYSTEM §3); a value that rounds to zero has no sign. */
export function formatFixed(value: number, digits: number, signed = false): string {
  const rounded = Number(value.toFixed(digits))
  const number = Math.abs(rounded).toLocaleString('zh-TW', { minimumFractionDigits: digits, maximumFractionDigits: digits })
  return rounded < 0 ? `-${number}` : signed && rounded > 0 ? `+${number}` : number
}

/** Table cells contain values only; their caller describes units outside the table. */
export function formatTableNumber(value: unknown, digits: number, signed = false): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return ''
  return formatFixed(value, digits, signed)
}

const MAX_VOLUME_TEXT = '9223372036854775807'

const SHARE_LIMITS = { 1: MAX_VOLUME_TEXT, 5: '46116860184273879035', 20: '184467440737095516140' } as const
type ShareHorizon = keyof typeof SHARE_LIMITS

function canonicalShareText(value: unknown, horizon: ShareHorizon, nonnegative: boolean): string | null {
  const maximum = SHARE_LIMITS[horizon]
  if (!maximum || typeof value !== 'string' || value.length > maximum.length + 1
    || !/^(?:0|-?[1-9][0-9]*)(?![\s\S])/.test(value) || (nonnegative && value.startsWith('-'))) return null
  const magnitude = value.startsWith('-') ? value.slice(1) : value
  return magnitude.length > maximum.length || (magnitude.length === maximum.length && magnitude > maximum) ? null : value
}

/** Decimal digit string plus one, without Number (sums exceed the safe integer range). */
function incrementDigits(digits: string): string {
  let carry = 1
  let result = ''
  for (let index = digits.length - 1; index >= 0; index--) {
    const sum = Number(digits[index]) + carry
    result = String(sum % 10) + result
    carry = sum >= 10 ? 1 : 0
  }
  return carry ? '1' + result : result
}

/**
 * Bounded canonical shares, including signed 5/20-day sums, as whole lots (UI_COPY_SPEC §8.3): rounded half away
 * from zero on the exact string, so an odd-lot flow under 500 shares is an unsigned 0.
 */
export function formatCanonicalShareLots(value: unknown, horizon: ShareHorizon = 1, nonnegative = false): string | null {
  const text = canonicalShareText(value, horizon, nonnegative)
  if (text == null) return null
  const negative = text.startsWith('-')
  const padded = (negative ? text.slice(1) : text).padStart(4, '0')
  const whole = padded.slice(0, -3).replace(/^0+(?=\d)/, '')
  const lots = padded[padded.length - 3] >= '5' ? incrementDigits(whole) : whole
  return (negative && lots !== '0' ? '-' : '') + groupedInteger(lots)
}

/** Exact lots with up to three odd-lot decimals, for holdings only (UI_COPY_SPEC §8.3). */
function formatExactShareLots(text: string): string {
  const padded = text.padStart(4, '0')
  const fraction = padded.slice(-3).replace(/0+$/, '')
  return groupedInteger(padded.slice(0, -3)) + (fraction ? `.${fraction}` : '')
}

/** Original share text belongs in explicitly labelled source-audit details. */
export function formatCanonicalShares(value: unknown, horizon: ShareHorizon = 1, nonnegative = false): string | null {
  const text = canonicalShareText(value, horizon, nonnegative)
  return text == null ? null : groupedInteger(text)
}

function exactVolumeText(shares: unknown, exact: unknown): string | null {
  // Only an absent field permits compatibility with a safe legacy JSON number.
  if (exact === undefined) {
    return typeof shares === 'number' && Number.isSafeInteger(shares) && shares >= 0 ? String(shares) : null
  }
  return canonicalShareText(exact, 1, true)
}

function groupedInteger(value: string): string {
  return value.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

/** Whole lots from canonical share text; no Number division. */
export function formatTableVolume(shares: number | null | undefined, source: string | null | undefined, exact?: string | null): string {
  if (!isVerifiedShareSource(source)) return ''
  const text = exactVolumeText(shares, exact)
  if (text == null) return ''
  return formatCanonicalShareLots(text, 1, true) ?? ''
}

/** Exact source share count for the overview's original-value table. */
export function formatTableVolumeShares(shares: number | null | undefined, source: string | null | undefined, exact?: string | null): string {
  if (!isVerifiedShareSource(source)) return ''
  const text = exactVolumeText(shares, exact)
  return text == null ? '' : groupedInteger(text)
}

export function formatTableChip(value: number | null | undefined, source: string | null | undefined, margin = false): string {
  if (!(margin ? isVerifiedMarginSource(source) : isVerifiedChipFlowSource(source))) return ''
  // Margin sources already count lots.
  if (margin) return formatTableNumber(value, 0, true)
  if (typeof value !== 'number' || !Number.isSafeInteger(value)) return ''
  const lots = formatCanonicalShareLots(String(value))
  return lots == null ? '' : (value > 0 && lots !== '0' ? '+' : '') + lots
}

/** Format a share-count value as whole lots, keeping the sign of a nonzero lot count. */
export function formatShareLots(shares: number | null | undefined): string {
  if (typeof shares !== 'number' || !Number.isSafeInteger(shares)) return '待核實'
  return `${formatCanonicalShareLots(String(shares))} 張`
}

export function formatSignedShareLots(shares: number | null | undefined): string {
  if (typeof shares !== 'number' || !Number.isSafeInteger(shares)) return '待核實'
  const formatted = formatShareLots(Math.abs(shares))
  if (formatted === '0 張') return formatted
  return shares > 0 ? `+${formatted}` : shares < 0 ? `-${formatted}` : formatted
}

export function formatVolumeLots(shares: number | null | undefined): string {
  if (typeof shares !== 'number' || !Number.isSafeInteger(shares) || shares < 0) return '待核實'
  return formatShareLots(shares)
}

export function isVerifiedShareSource(source: string | null | undefined): boolean {
  return source === 'twse' || source === 'tpex'
}

function sourceParts(source: string | null | undefined): string[] {
  return typeof source === 'string' && source.length > 0 ? source.split('+') : []
}

export function isVerifiedChipFlowSource(source: string | null | undefined): boolean {
  const parts = sourceParts(source)
  if (parts.length === 0) return false
  const twse = parts.includes('twse_t86') && parts.every((part) => part === 'twse_t86' || part === 'twse_margin')
  const tpex = parts.includes('tpex_3insti') && parts.every((part) => part === 'tpex_3insti' || part === 'tpex_margin')
  return twse || tpex
}

export function isVerifiedMarginSource(source: string | null | undefined): boolean {
  const parts = sourceParts(source)
  if (parts.length === 0) return false
  const twse = parts.includes('twse_margin') && parts.every((part) => part === 'twse_t86' || part === 'twse_margin')
  const tpex = parts.includes('tpex_margin') && parts.every((part) => part === 'tpex_3insti' || part === 'tpex_margin')
  return twse || tpex
}

/** Convert only exchange-verified share sources; preserve raw values otherwise. */
export function formatSourceAwareShareLots(shares: number | null | undefined, source: string | null | undefined): string {
  if (typeof shares !== 'number' || !Number.isSafeInteger(shares) || shares < 0) return '待核實'
  return isVerifiedShareSource(source)
    ? formatVolumeLots(shares)
    : `${shares.toLocaleString('zh-TW', { maximumFractionDigits: 3 })}（單位待提供）`
}

export function sharesFromUnit(unit: ShareUnit, quantity: number): number {
  if ((unit !== 'lot' && unit !== 'odd_lot') || !Number.isSafeInteger(quantity) || quantity <= 0
    || quantity > (unit === 'lot' ? Math.floor(Number.MAX_SAFE_INTEGER / LOT_SIZE) : Number.MAX_SAFE_INTEGER)) {
    throw new Error('數量必須是正整數')
  }
  return unit === 'lot' ? quantity * LOT_SIZE : quantity
}

/** Normalize digits without Number; POST retains a canonical int64 string. */
export function positionQuantityFromText(unit: ShareUnit, raw: string): string {
  if ((unit !== 'lot' && unit !== 'odd_lot') || !/^[0-9]+(?![\s\S])/.test(raw)) {
    throw new Error('數量須輸入正整數十進位數字。')
  }
  const text = raw.replace(/^0+/, '')
  const maximum = unit === 'lot' ? '9223372036854775' : '9223372036854775807'
  if (!text || text.length > maximum.length || (text.length === maximum.length && text > maximum)) {
    throw new Error('總股數須為 1 至 9,223,372,036,854,775,807 股。')
  }
  return text
}

export function formatShareQuantity(shares: number | null | undefined, exact?: string | null): string {
  const text = exactVolumeText(shares, exact)
  return text == null ? '庫存數量待核實' : `${formatExactShareLots(text)} 張`
}

export function formatPositionShares(shares: number | null | undefined, exact?: string | null): string {
  const text = exactVolumeText(shares, exact)
  return text == null ? '股數待核實' : `${groupedInteger(text)} 股`
}
