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

// A relative return in percent as the shown text and its sign. A value that rounds to 0.00% is flat.
export function strengthOf(percent: number | null | undefined): { text: string; tone: StrengthTone } {
  if (!isFiniteNumber(percent)) return { text: '—', tone: 'none' }
  const magnitude = Math.abs(percent).toFixed(2)
  if (magnitude === '0.00') return { text: '0.00%', tone: 'flat' }
  return percent > 0 ? { text: `+${magnitude}%`, tone: 'up' } : { text: `-${magnitude}%`, tone: 'down' }
}

// A relative return as plain coloured text (DESIGN_SYSTEM §5 漲跌文字; #654 drew it as a block, #675 took the
// block away): --color-up red when up, --color-down green when down, neutral when flat or without data. No
// background. The class name stays `strength-chip`: tools/ops/screenshot.cjs measures `.strength-chip` and its
// ::before, so verify can tell no background is drawn. `percent` is already in percent.
export function StrengthChip({ label, percent, className }: { label: string; percent: number | null | undefined; className?: string }) {
  const { text, tone } = strengthOf(percent)
  return (
    <b className={cx('strength-chip', `strength-${tone}`, className)} role="img" aria-label={tone === 'none' ? `${label} 無資料` : `${label} ${text}`} data-strength={tone}>
      {text}
    </b>
  )
}
