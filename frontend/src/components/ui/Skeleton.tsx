import { cx } from './cx'

// Card skeleton with elevated-color bars that fade in and out; no spinner (DESIGN_SYSTEM §5 載入).
export function Skeleton({ lines = 3, height, label = '資料載入中…', className }: { lines?: number; height?: number; label?: string; className?: string }) {
  const count = Math.max(1, Math.floor(lines))
  return (
    <div className={cx('card', 'skeleton', className)} role="status" aria-busy="true">
      <span className="visually-hidden">{label}</span>
      {height != null
        ? <span className="skeleton-bar skeleton-block" style={{ height }} aria-hidden="true" />
        : Array.from({ length: count }, (_, index) => <span className="skeleton-bar" key={index} aria-hidden="true" />)}
    </div>
  )
}
