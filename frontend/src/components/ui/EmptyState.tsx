import type { ReactNode } from 'react'

import { cx } from './cx'

// Centered muted "無資料" plus one line of reason, no illustration (DESIGN_SYSTEM §5).
export function EmptyState({ title = '無資料', reason, className }: { title?: ReactNode; reason?: ReactNode; className?: string }) {
  return (
    <div className={cx('empty-state', className)} role="status">
      <strong className="empty-state-title">{title}</strong>
      {reason != null && <span className="empty-state-reason">{reason}</span>}
    </div>
  )
}
