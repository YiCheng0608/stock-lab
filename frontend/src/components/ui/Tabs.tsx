import type { KeyboardEvent } from 'react'

import { cx } from './cx'

export type TabItem<T extends string> = { id: T; label: string }

type TabsProps<T extends string> = {
  items: ReadonlyArray<TabItem<T>>
  value: T
  onChange: (id: T) => void
  label: string
  // Tab i controls the panel `${idPrefix}-panel-${id}`; the panel should carry aria-labelledby `${idPrefix}-tab-${id}`.
  idPrefix: string
  className?: string
}

export function tabId(idPrefix: string, id: string): string {
  return `${idPrefix}-tab-${id}`
}

export function tabPanelId(idPrefix: string, id: string): string {
  return `${idPrefix}-panel-${id}`
}

// Text tabs; the selected one is main text color with a 2px primary underline (DESIGN_SYSTEM §5).
export function Tabs<T extends string>({ items, value, onChange, label, idPrefix, className }: TabsProps<T>) {
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    if (!step) return
    event.preventDefault()
    const next = items[(index + step + items.length) % items.length]
    onChange(next.id)
    const element = typeof document === 'undefined' ? null : document.getElementById(tabId(idPrefix, next.id))
    element?.focus()
  }
  return (
    <div className={cx('tabs', className)} role="tablist" aria-label={label}>
      {items.map((item, index) => {
        const selected = item.id === value
        return (
          <button
            type="button"
            role="tab"
            key={item.id}
            id={tabId(idPrefix, item.id)}
            aria-selected={selected}
            aria-controls={tabPanelId(idPrefix, item.id)}
            tabIndex={selected ? 0 : -1}
            className={cx('tab', selected && 'tab-active')}
            onClick={() => onChange(item.id)}
            onKeyDown={(event) => onKeyDown(event, index)}
          >
            {item.label}
          </button>
        )
      })}
    </div>
  )
}
