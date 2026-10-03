export type ShareUnit = 'lot' | 'odd_lot'

export const LOT_SIZE = 1000

/** Table cells contain values only; their caller describes units outside the table. */
export function formatTableNumber(value: unknown, digits = 3, signed = false): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return ''
  const number = value.toLocaleString('zh-TW', { maximumFractionDigits: digits })
  return signed && value > 0 ? `+${number}` : number
}

const MAX_VOLUME_TEXT = '9223372036854775807'

function exactVolumeText(shares: unknown, exact: unknown): string | null {
  // Only an absent field permits compatibility with a safe legacy JSON number.
  if (exact === undefined) {
    return typeof shares === 'number' && Number.isSafeInteger(shares) && shares >= 0 ? String(shares) : null
  }
  if (typeof exact !== 'string' || !/^(?:0|[1-9][0-9]*)$/.test(exact)
    || exact.length > MAX_VOLUME_TEXT.length
    || (exact.length === MAX_VOLUME_TEXT.length && exact > MAX_VOLUME_TEXT)) return null
  return exact
}

function groupedInteger(value: string): string {
  return value.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

/** Exact lots from canonical share text; no Number division or decimal rounding. */
export function formatTableVolume(shares: number | null | undefined, source: string | null | undefined, exact?: string | null): string {
  if (!isVerifiedShareSource(source)) return ''
  const text = exactVolumeText(shares, exact)
  if (text == null) return ''
  const padded = text.padStart(4, '0')
  const lots = padded.slice(0, -3)
  const fraction = padded.slice(-3).replace(/0+$/, '')
  return groupedInteger(lots) + (fraction ? `.${fraction}` : '')
}

/** Exact source share count for the overview's original-value table. */
export function formatTableVolumeShares(shares: number | null | undefined, source: string | null | undefined, exact?: string | null): string {
  if (!isVerifiedShareSource(source)) return ''
  const text = exactVolumeText(shares, exact)
  return text == null ? '' : groupedInteger(text)
}

export function formatTableChip(value: number | null | undefined, source: string | null | undefined, margin = false): string {
  if (!(margin ? isVerifiedMarginSource(source) : isVerifiedChipFlowSource(source))) return ''
  const normalized = typeof value === 'number' && !margin && isVerifiedChipFlowSource(source) ? value / LOT_SIZE : value
  return formatTableNumber(normalized, 3, true)
}

/** Format a share-count value as lots without discarding fractions or sign. */
export function formatShareLots(shares: number | null | undefined): string {
  if (typeof shares !== 'number' || !Number.isFinite(shares)) return '待核實'
  return `${(shares / LOT_SIZE).toLocaleString('zh-TW', { maximumFractionDigits: 3 })} 張`
}

export function formatSignedShareLots(shares: number | null | undefined): string {
  if (typeof shares !== 'number' || !Number.isFinite(shares)) return '待核實'
  const formatted = formatShareLots(Math.abs(shares))
  return shares > 0 ? `+${formatted}` : shares < 0 ? `-${formatted}` : formatted
}

export function formatVolumeLots(shares: number | null | undefined): string {
  if (typeof shares !== 'number' || !Number.isFinite(shares) || shares < 0) return '待核實'
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
  if (typeof shares !== 'number' || !Number.isFinite(shares) || shares < 0) return '待核實'
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
  if (text == null) return '股數待核實'
  const padded = text.padStart(4, '0')
  const lots = padded.slice(0, -3)
  const remainder = padded.slice(-3).replace(/^0+/, '') || '0'
  if (lots !== '0' && remainder !== '0') return `${groupedInteger(lots)} 張 ${remainder} 股`
  if (lots !== '0') return `${groupedInteger(lots)} 張`
  return `${remainder} 股（零股）`
}

export function formatPositionShares(shares: number | null | undefined, exact?: string | null): string {
  const text = exactVolumeText(shares, exact)
  return text == null ? '股數待核實' : `${groupedInteger(text)} 股`
}
