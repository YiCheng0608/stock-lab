import type { HTMLAttributes } from 'react'

import { formatDay } from '../../dates'
import { cx } from './cx'

export type BadgeTone = 'default' | 'primary' | 'success' | 'warning' | 'error' | 'accent'

type BadgeProps = HTMLAttributes<HTMLSpanElement> & {
  tone?: BadgeTone
  // 8px leading dot; pulse marks an active state (DESIGN_SYSTEM §5 badge).
  dot?: boolean
  pulse?: boolean
}

export function Badge({ tone = 'default', dot = false, pulse = false, className, children, ...rest }: BadgeProps) {
  return (
    <span className={cx('badge', tone !== 'default' && `badge-${tone}`, className)} {...rest}>
      {dot && <i className={cx('badge-dot', pulse && 'badge-dot-pulse')} aria-hidden="true" />}
      {children}
    </span>
  )
}

// Data-date badge for the top right of a data card (DESIGN_SYSTEM §6, §7).
// An API date (YYYY-MM-DD) reads YYYY/MM/DD (UI_COPY_SPEC §1); an already formatted date is kept.
// No date is 「未提供」 and a failed request 「暫時無法載入」, never 待核實 (UI_COPY_SPEC §1, #465).
export function DateBadge({ date, label = '資料', unavailable = false }: { date: string | null | undefined; label?: string; unavailable?: boolean }) {
  const day = formatDay(date) ?? date
  if (day) return <Badge className="date-badge" title={`${label}日期 ${day}`}>{label} {day}</Badge>
  return <Badge className="date-badge" tone="warning">{label}日期{unavailable ? '暫時無法載入' : '未提供'}</Badge>
}
