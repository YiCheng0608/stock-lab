import { cx } from './cx'

const isFiniteNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)

// A 0–100 score or percentile as a horizontal bar (DESIGN_SYSTEM §5 分數橫條, #654): the fill is the value's share of
// the track, the number stays beside it in mono. No data draws no fill and reads 「—」, never 0.
export function ScoreBar({ label, value, className }: { label: string; value: number | null | undefined; className?: string }) {
  const known = isFiniteNumber(value)
  const text = known ? String(Math.round(value)) : '—'
  const width = known ? Math.min(100, Math.max(0, value)) : 0
  return (
    <span className={cx('score-bar', !known && 'score-bar-empty', className)} role="img" aria-label={known ? `${label} ${text}（0–100）` : `${label} 無資料`} data-score={known ? text : 'none'}>
      <span className="score-bar-track" aria-hidden="true">{known && <span className="score-bar-fill" style={{ width: `${width}%` }} />}</span>
      <span className="score-bar-value" aria-hidden="true">{text}</span>
    </span>
  )
}

export type StrengthTone = 'up' | 'down' | 'flat' | 'none'

// Steps of |percent| (DESIGN_SYSTEM §5 強弱色塊): below 1 is level 1, 1 to below 3 level 2, 3 to below 6 level 3,
// 6 and above level 4. A value that rounds to 0.00% is flat (level 0).
export const STRENGTH_STEPS: readonly number[] = [1, 3, 6]

export function strengthOf(percent: number | null | undefined): { text: string; tone: StrengthTone; level: number } {
  if (!isFiniteNumber(percent)) return { text: '—', tone: 'none', level: 0 }
  const magnitude = Math.abs(percent).toFixed(2)
  if (magnitude === '0.00') return { text: '0.00%', tone: 'flat', level: 0 }
  const level = 1 + STRENGTH_STEPS.filter((step) => Number(magnitude) >= step).length
  return percent > 0 ? { text: `+${magnitude}%`, tone: 'up', level } : { text: `-${magnitude}%`, tone: 'down', level }
}

// A relative return as a coloured block with its number inside (DESIGN_SYSTEM §5 強弱色塊, #654): the hue is the sign
// (--color-up red, --color-down green), the depth the step of the magnitude. `percent` is already in percent.
export function StrengthChip({ label, percent, className }: { label: string; percent: number | null | undefined; className?: string }) {
  const { text, tone, level } = strengthOf(percent)
  return (
    <b className={cx('strength-chip', `strength-${tone}`, level > 0 && `strength-l${level}`, className)} role="img" aria-label={tone === 'none' ? `${label} 無資料` : `${label} ${text}`} data-strength={`${tone}-${level}`}>
      {text}
    </b>
  )
}
