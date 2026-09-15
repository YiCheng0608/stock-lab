export type ShareUnit = 'lot' | 'odd_lot'

export const LOT_SIZE = 1000

/** Table cells contain values only; their caller describes units outside the table. */
export function formatTableNumber(value: unknown, digits = 3, signed = false): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return ''
  const number = value.toLocaleString('zh-TW', { maximumFractionDigits: digits })
  return signed && value > 0 ? `+${number}` : number
}

export function formatTableVolume(shares: number | null | undefined, source: string | null | undefined): string {
  if (!isVerifiedShareSource(source) || (typeof shares === 'number' && shares < 0)) return ''
  return formatTableNumber(typeof shares === 'number' ? shares / LOT_SIZE : shares)
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
  if (!Number.isInteger(quantity) || quantity <= 0) {
    throw new Error('數量必須是正整數')
  }
  return unit === 'lot' ? quantity * LOT_SIZE : quantity
}

export function formatShareQuantity(shares: number): string {
  if (!Number.isFinite(shares) || shares < 0 || !Number.isInteger(shares)) return '—'
  const lots = Math.floor(shares / LOT_SIZE)
  const remainder = shares % LOT_SIZE
  if (lots > 0 && remainder > 0) return `${lots.toLocaleString('zh-TW')} 張 ${remainder.toLocaleString('zh-TW')} 股`
  if (lots > 0) return `${lots.toLocaleString('zh-TW')} 張`
  return `${remainder.toLocaleString('zh-TW')} 股（零股）`
}
