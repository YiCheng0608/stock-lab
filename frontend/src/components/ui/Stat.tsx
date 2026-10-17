import type { ReactNode } from 'react'

import { cx } from './cx'

export type ChangeTone = 'up' | 'down' | 'flat'

// Statistic number: mono, 24px, 600 (DESIGN_SYSTEM §5 stat-value).
export function Stat({ label, value, detail, className }: { label: ReactNode; value: ReactNode; detail?: ReactNode; className?: string }) {
  return (
    <div className={cx('stat', className)}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {detail != null && <div className="stat-detail">{detail}</div>}
    </div>
  )
}

// Small data block: muted label, mono main number, change below in up/down/flat color (DESIGN_SYSTEM §5 market-widget).
export function MarketWidget({ label, value, change, tone = 'flat', className }: { label: ReactNode; value: ReactNode; change?: ReactNode; tone?: ChangeTone; className?: string }) {
  return (
    <div className={cx('market-widget', className)}>
      <div className="market-widget-label">{label}</div>
      <div className="market-widget-value">{value}</div>
      {change != null && <div className={cx('market-widget-change', `tone-${tone}`)}>{change}</div>}
    </div>
  )
}
