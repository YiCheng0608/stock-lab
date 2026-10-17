import type { HTMLAttributes } from 'react'

import { cx } from './cx'

export type BadgeTone = 'default' | 'primary' | 'success' | 'warning' | 'error'

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
export function DateBadge({ date, label = '資料' }: { date: string | null | undefined; label?: string }) {
  return date
    ? <Badge className="date-badge" title={`${label}日期 ${date}`}>{label} {date}</Badge>
    : <Badge className="date-badge" tone="warning">{label}日期待核實</Badge>
}
