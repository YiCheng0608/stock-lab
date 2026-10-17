import type { ReactNode, TableHTMLAttributes } from 'react'

import { cx } from './cx'

type TableProps = TableHTMLAttributes<HTMLTableElement> & {
  // Unit / blank-cell explanation shown once above the table (UI_COPY_SPEC §10.4).
  note?: ReactNode
  wrapClassName?: string
}

// DESIGN_SYSTEM §5 table: card container, muted 14px header, 56px rows, hover row, right-aligned mono numbers (`num`).
export function Table({ note, wrapClassName, className, children, ...rest }: TableProps) {
  return (
    <div className={cx('table-wrap', wrapClassName)}>
      {note != null && <p className="table-note">{note}</p>}
      <table className={className} {...rest}>{children}</table>
    </div>
  )
}
