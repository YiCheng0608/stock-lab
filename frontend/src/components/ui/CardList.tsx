import { Fragment, type Key, type ReactNode } from 'react'

import { cx } from './cx'

// DESIGN_SYSTEM §5.1 phone cards: a list of more than this many cards shows the first ones and folds the rest.
export const CARD_LIST_PREVIEW = 10

type CardListProps<T> = {
  items: readonly T[]
  itemKey: (item: T) => Key
  renderCard: (item: T) => ReactNode
  // Summary of the folded rest, e.g. 「顯示其餘 N 檔」.
  restLabel?: (count: number) => string
  className?: string
  // Shown above the cards (e.g. the unit note the hidden desktop table carries).
  note?: ReactNode
  // Cards shown before the fold; null for a list with its own paging (the action tiers' 顯示更多).
  preview?: number | null
}

// The phone rendering of a desktop DataTable: one card per row, the first CARD_LIST_PREVIEW open, the rest in <details>.
export function CardList<T>({ items, itemKey, renderCard, restLabel = (count) => `顯示其餘 ${count} 檔`, className, note, preview = CARD_LIST_PREVIEW }: CardListProps<T>) {
  const limit = preview ?? items.length
  const shown = items.slice(0, limit)
  const rest = items.slice(limit)
  return (
    <div className={cx('card-list', className)}>
      {note}
      {shown.map((item) => <Fragment key={itemKey(item)}>{renderCard(item)}</Fragment>)}
      {rest.length > 0 && (
        <details className="details card-list-rest">
          <summary>{restLabel(rest.length)}</summary>
          <div className="card-list-rest-items">{rest.map((item) => <Fragment key={itemKey(item)}>{renderCard(item)}</Fragment>)}</div>
        </details>
      )}
    </div>
  )
}
