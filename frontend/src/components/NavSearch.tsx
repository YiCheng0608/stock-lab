import { useEffect, useId, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { getInstrumentSuggestions } from '../api'
import { createSuggestController, INITIAL_SUGGEST_STATE, stockSearchPath } from '../search'
import type { SuggestController, SuggestState } from '../search'
import { exchangeLabel } from '../presentation'

// Navbar stock search (DESIGN_SYSTEM §5 導覽列搜尋建議, UI_COPY_SPEC §15; Issue 599): a combobox whose debounced
// suggestions come from /api/instruments only. Picking one opens the stock page; Enter without one opens /stocks?q=.

export const SUGGEST_COPY = {
  label: '搜尋個股代號或名稱',
  placeholder: '代號或名稱',
  listLabel: '符合的股票',
  empty: (query: string) => `沒有符合「${query.trim()}」的股票，按 Enter 到個股清單搜尋。`,
  error: '建議暫時無法載入，按 Enter 到個股清單搜尋。',
  count: (count: number) => `${count} 檔符合，按上下鍵選取。`,
}

export const suggestOptionId = (listId: string, index: number) => `${listId}-option-${index}`

// Whether the popup shows anything: results (or the no-match line) or the failure line; nothing while loading.
export function suggestExpanded(state: SuggestState): boolean {
  return state.open && (state.status === 'ready' || state.status === 'error')
}

// The visible line under the box when there is no list: no match or the request failed.
export function suggestNote(state: SuggestState): string | null {
  if (!suggestExpanded(state)) return null
  if (state.status === 'error') return SUGGEST_COPY.error
  return state.items.length ? null : SUGGEST_COPY.empty(state.query)
}

// What the always-present live region reads (Issue 599 review): only its text changes, so screen readers announce it.
export function suggestAnnouncement(state: SuggestState): string {
  if (!suggestExpanded(state)) return ''
  return suggestNote(state) ?? SUGGEST_COPY.count(state.items.length)
}

export function SuggestPopup({ state, listId, onChoose, onHighlight }: {
  state: SuggestState
  listId: string
  onChoose?: (index: number) => void
  onHighlight?: (index: number) => void
}) {
  if (!suggestExpanded(state)) return null
  const note = suggestNote(state)
  return (
    <div className="nav-suggest">
      {note
        ? <p className="nav-suggest-note" aria-hidden="true">{note}</p>
        : (
          <ul className="nav-suggest-list" id={listId} role="listbox" aria-label={SUGGEST_COPY.listLabel}>
            {state.items.map((item, index) => (
              <li
                key={`${item.exchange}:${item.symbol}`}
                id={suggestOptionId(listId, index)}
                role="option"
                aria-selected={index === state.active}
                className={index === state.active ? 'nav-suggest-option nav-suggest-option-active' : 'nav-suggest-option'}
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => onHighlight?.(index)}
                onClick={() => onChoose?.(index)}
              >
                <span className="nav-suggest-symbol">{item.symbol}</span>
                <span className="nav-suggest-name">{item.name}</span>
                <span className="nav-suggest-market">{exchangeLabel(item.exchange)}</span>
              </li>
            ))}
          </ul>
        )}
    </div>
  )
}

export function NavSearch() {
  const navigate = useNavigate()
  const listId = `nav-suggest-${useId().replace(/:/g, '')}`
  const [state, setState] = useState<SuggestState>(INITIAL_SUGGEST_STATE)
  const controller = useRef<SuggestController | null>(null)
  if (!controller.current) {
    controller.current = createSuggestController({ fetchSuggestions: getInstrumentSuggestions, onChange: setState })
  }
  const composing = useRef(false)
  useEffect(() => () => controller.current?.dispose(), [])
  // Phones: the open menu is capped at the visible height, which shrinks with the soft keyboard (styles.css ≤860px).
  useEffect(() => {
    const viewport = typeof window === 'undefined' ? undefined : window.visualViewport
    if (!viewport) return undefined
    const root = document.documentElement
    const update = () => root.style.setProperty('--visual-viewport-height', `${Math.round(viewport.height)}px`)
    update()
    viewport.addEventListener('resize', update)
    return () => {
      viewport.removeEventListener('resize', update)
      root.style.removeProperty('--visual-viewport-height')
    }
  }, [])
  // Keep the highlighted option visible when the list scrolls with the menu.
  useEffect(() => {
    if (state.active < 0 || typeof document === 'undefined') return
    document.getElementById(suggestOptionId(listId, state.active))?.scrollIntoView({ block: 'nearest' })
  }, [listId, state.active])
  const go = (path: string) => {
    controller.current?.input('')
    navigate(path)
  }
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const path = stockSearchPath(state.query)
    if (path) navigate(path)
  }
  const keyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    // IME candidate selection, not a search key; Safari confirms with Enter after isComposing is false (keyCode 229).
    if (event.nativeEvent.isComposing || event.keyCode === 229 || composing.current) return
    const wasOpen = suggestExpanded(state)
    const command = controller.current?.key(event.key)
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') event.preventDefault()
    if (event.key === 'Escape' && wasOpen) event.preventDefault()
    if (command?.kind === 'navigate') {
      event.preventDefault()
      go(command.path)
    }
  }
  const choose = (index: number) => {
    const command = controller.current?.choose(index)
    if (command?.kind === 'navigate') go(command.path)
  }
  const expanded = suggestExpanded(state) && state.items.length > 0
  return (
    <form className="navbar-search" role="search" onSubmit={submit}>
      <input
        className="input"
        value={state.query}
        onChange={(event) => (composing.current ? controller.current?.compose(event.target.value) : controller.current?.input(event.target.value))}
        onCompositionStart={() => { composing.current = true }}
        onCompositionEnd={(event) => {
          composing.current = false
          controller.current?.input(event.currentTarget.value)
        }}
        onKeyDown={keyDown}
        onBlur={() => controller.current?.close()}
        onFocus={() => controller.current?.focus()}
        placeholder={SUGGEST_COPY.placeholder}
        aria-label={SUGGEST_COPY.label}
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={expanded}
        aria-controls={expanded ? listId : undefined}
        aria-activedescendant={expanded && state.active >= 0 ? suggestOptionId(listId, state.active) : undefined}
        autoComplete="off"
        spellCheck={false}
      />
      <SuggestPopup state={state} listId={listId} onChoose={choose} onHighlight={(index) => controller.current?.highlight(index)} />
      <p className="sr-only" role="status">{suggestAnnouncement(state)}</p>
    </form>
  )
}
