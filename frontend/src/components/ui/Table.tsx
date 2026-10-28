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
  // Long text that may wrap; other cells stay on one line (DESIGN_SYSTEM §5.1).
  wrap?: boolean
  // A secondary column hidden at 640px and below, so the key numbers stay on the first screen.
  wideOnly?: boolean
  // Extra class for the body cells only.
  cellClassName?: string
  cell: (row: T, index: number) => ReactNode
}

// The same classes on th and td, so a header and its cells cannot disagree.
function columnClass<T>(column: Column<T>): string | undefined {
  return cx(column.num && 'num', column.wrap && 'cell-wrap', column.wideOnly && 'wide-only') || undefined
}

type DataTableProps<T> = {
  columns: ReadonlyArray<Column<T>>
  rows: readonly T[]
  rowKey: (row: T, index: number) => Key
  rowProps?: (row: T, index: number) => HTMLAttributes<HTMLTableRowElement> & Record<`data-${string}`, string | number | undefined>
  // A title row spanning the table before this row (e.g. a component name above its sub-items), instead of a column.
  groupTitle?: (row: T, index: number) => ReactNode
  // A detail row spanning the table after this row (e.g. a candidate's expanded notes); it follows the row's `hidden`.
  detailRow?: (row: T, index: number) => { content: ReactNode; props?: Record<`data-${string}`, string | number | undefined> } | null
  note?: ReactNode
  wrapClassName?: string
  className?: string
}

// Every table goes through here, so a numeric column's header and cells cannot disagree on alignment.
export function DataTable<T>({ columns, rows, rowKey, rowProps, groupTitle, detailRow, note, wrapClassName, className }: DataTableProps<T>) {
  return (
    <Table note={note} wrapClassName={wrapClassName} className={className}>
      <thead><tr>{columns.map((column) => <th key={column.key} className={columnClass(column)}>{column.header}</th>)}</tr></thead>
      <tbody>{rows.flatMap((row, index) => {
        const key = rowKey(row, index)
        const title = groupTitle?.(row, index)
        const props = rowProps?.(row, index)
        const detail = detailRow?.(row, index)
        const body = (
          <tr key={key} {...props}>
            {columns.map((column) => <td key={column.key} className={cx(columnClass(column), column.cellClassName) || undefined}>{column.cell(row, index)}</td>)}
          </tr>
        )
        return [
          ...(title == null ? [] : [<tr key={`${key}-group`} className="table-group-row"><td colSpan={columns.length}>{title}</td></tr>]),
          body,
          ...(detail == null ? [] : [<tr key={`${key}-detail`} hidden={props?.hidden} className="table-detail-row" {...detail.props}><td colSpan={columns.length}>{detail.content}</td></tr>]),
        ]
      })}</tbody>
    </Table>
  )
}
