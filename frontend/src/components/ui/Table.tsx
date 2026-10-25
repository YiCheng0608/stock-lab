import type { HTMLAttributes, Key, ReactNode, TableHTMLAttributes } from 'react'

import { cx } from './cx'

type TableProps = TableHTMLAttributes<HTMLTableElement> & {
  // Unit / blank-cell explanation shown once above the table (UI_COPY_SPEC §8.4).
  note?: ReactNode
  wrapClassName?: string
}

// DESIGN_SYSTEM §5 table: card container, muted 14px header, 56px rows, hover row; §5.1 narrow widths.
function Table({ note, wrapClassName, className, children, ...rest }: TableProps) {
  return (
    <div className={cx('table-wrap', wrapClassName)}>
      {note != null && <p className="table-note">{note}</p>}
      <table className={className} {...rest}>{children}</table>
    </div>
  )
}

export type Column<T> = {
  key: string
  header: ReactNode
  // Numeric column: th and td both get `num` (right-aligned, mono, tabular, no wrap).
  num?: boolean
  // Extra class for the body cells only.
  cellClassName?: string
  cell: (row: T, index: number) => ReactNode
}

type DataTableProps<T> = {
  columns: ReadonlyArray<Column<T>>
  rows: readonly T[]
  rowKey: (row: T, index: number) => Key
  rowProps?: (row: T, index: number) => HTMLAttributes<HTMLTableRowElement> & Record<`data-${string}`, string | number | undefined>
  // A title row spanning the table before this row (e.g. a component name above its sub-items), instead of a column.
  groupTitle?: (row: T, index: number) => ReactNode
  note?: ReactNode
  wrapClassName?: string
  className?: string
}

// Every table goes through here, so a numeric column's header and cells cannot disagree on alignment.
export function DataTable<T>({ columns, rows, rowKey, rowProps, groupTitle, note, wrapClassName, className }: DataTableProps<T>) {
  return (
    <Table note={note} wrapClassName={wrapClassName} className={className}>
      <thead><tr>{columns.map((column) => <th key={column.key} className={column.num ? 'num' : undefined}>{column.header}</th>)}</tr></thead>
      <tbody>{rows.flatMap((row, index) => {
        const key = rowKey(row, index)
        const title = groupTitle?.(row, index)
        const body = (
          <tr key={key} {...rowProps?.(row, index)}>
            {columns.map((column) => <td key={column.key} className={cx(column.num && 'num', column.cellClassName) || undefined}>{column.cell(row, index)}</td>)}
          </tr>
        )
        return title == null ? [body] : [<tr key={`${key}-group`} className="table-group-row"><td colSpan={columns.length}>{title}</td></tr>, body]
      })}</tbody>
    </Table>
  )
}
