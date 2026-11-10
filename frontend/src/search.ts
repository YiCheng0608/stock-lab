/**
 * Search request contract.
 *
 * - The page search boxes (/stocks, /watch) commit a query only on Enter: `commitSearchOnEnter`.
 * - The navbar box (Issue 599) asks only the light suggestion API while typing, debounced:
 *   `suggestionPath` is `/instruments?…` (about 2 KB per query), never `/stocks?…` (which scores
 *   every row). `/stocks?q=` is opened only when the form is submitted without a chosen suggestion.
 *
 * Kept free of React and the DOM so the regression modules can drive it under Node.
 */
export function commitSearchOnEnter(draft: string, key: string): string | null {
  return key === 'Enter' ? draft.trim() : null
}

// Navbar form submit without a chosen suggestion: the full stock directory search.
export function stockSearchPath(value: string): string | null {
  const query = value.trim()
  return query ? '/stocks?q=' + encodeURIComponent(query) : null
}

export const SUGGEST_DEBOUNCE_MS = 250
export const SUGGEST_LIMIT = 8

export type Suggestion = { exchange: string; symbol: string; name: string }

// API path (relative to /api) the navbar asks while typing; null when there is nothing to ask.
export function suggestionPath(value: string): string | null {
  const query = value.trim()
  if (!query) return null
  return `/instruments?q=${encodeURIComponent(query)}&securities_only=true&page_size=${SUGGEST_LIMIT}`
}

export function stockPagePath(item: Suggestion): string {
  return `/stocks/${encodeURIComponent(item.exchange)}/${encodeURIComponent(item.symbol)}`
}

export type SuggestStatus = 'idle' | 'loading' | 'ready' | 'error'

export type SuggestState = {
  query: string
  status: SuggestStatus
  items: Suggestion[]
  // Index of the highlighted option, -1 for none.
  active: number
  open: boolean
}

export const INITIAL_SUGGEST_STATE: SuggestState = { query: '', status: 'idle', items: [], active: -1, open: false }

// What a key press in the box asks the component to do: go to a stock page, let the form submit
// (Enter with no highlighted option goes to /stocks?q= as before), or nothing beyond the new state.
export type SuggestCommand = { kind: 'navigate'; path: string } | { kind: 'submit' } | { kind: 'none' }

export type SuggestTimer = {
  set: (callback: () => void, ms: number) => unknown
  clear: (handle: unknown) => void
}

export type SuggestController = {
  input: (value: string) => void
  key: (key: string) => SuggestCommand
  choose: (index: number) => SuggestCommand
  highlight: (index: number) => void
  close: () => void
  focus: () => void
  dispose: () => void
  state: () => SuggestState
}

const defaultTimer: SuggestTimer = {
  set: (callback, ms) => setTimeout(callback, ms),
  clear: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
}

export function createSuggestController({
  fetchSuggestions,
  onChange,
  timer = defaultTimer,
  delayMs = SUGGEST_DEBOUNCE_MS,
}: {
  fetchSuggestions: (path: string, signal: AbortSignal) => Promise<Suggestion[]>
  onChange: (state: SuggestState) => void
  timer?: SuggestTimer
  delayMs?: number
}): SuggestController {
  let state = INITIAL_SUGGEST_STATE
  let pending: unknown = null
  let inflight: AbortController | null = null
  let sequence = 0
  const set = (next: Partial<SuggestState>) => {
    state = { ...state, ...next }
    onChange(state)
  }
  const cancel = () => {
    if (pending !== null) timer.clear(pending)
    pending = null
    inflight?.abort()
    inflight = null
  }
  const ask = (query: string, path: string) => {
    const ticket = ++sequence
    const controller = new AbortController()
    inflight = controller
    fetchSuggestions(path, controller.signal).then(
      (items) => {
        if (ticket !== sequence || state.query !== query) return
        set({ status: 'ready', items: items.slice(0, SUGGEST_LIMIT), active: -1 })
      },
      () => {
        if (ticket !== sequence || state.query !== query) return
        // A failed request only hides the list; Enter still submits to /stocks?q=.
        set({ status: 'error', items: [], active: -1 })
      },
    )
  }
  const choose = (index: number): SuggestCommand => {
    const item = state.open ? state.items[index] : undefined
    if (!item) return { kind: 'none' }
    cancel()
    set({ open: false, active: -1 })
    return { kind: 'navigate', path: stockPagePath(item) }
  }
  return {
    input(value) {
      cancel()
      sequence++
      const path = suggestionPath(value)
      if (!path) {
        set({ query: value, status: 'idle', items: [], active: -1, open: false })
        return
      }
      set({ query: value, status: 'loading', active: -1, open: true })
      const query = value
      pending = timer.set(() => {
        pending = null
        ask(query, path)
      }, delayMs)
    },
    key(key) {
      const count = state.status === 'ready' ? state.items.length : 0
      if (key === 'ArrowDown' || key === 'ArrowUp') {
        if (!count) return { kind: 'none' }
        const step = key === 'ArrowDown' ? 1 : -1
        const from = state.open ? state.active : -1
        const active = from === -1 ? (step === 1 ? 0 : count - 1) : (from + step + count) % count
        set({ open: true, active })
        return { kind: 'none' }
      }
      if (key === 'Escape') {
        if (state.open) set({ open: false, active: -1 })
        return { kind: 'none' }
      }
      if (key === 'Enter') {
        if (state.open && state.active >= 0 && state.active < count) return choose(state.active)
        cancel()
        sequence++
        if (state.open) set({ open: false, active: -1 })
        return { kind: 'submit' }
      }
      return { kind: 'none' }
    },
    choose,
    highlight(index) {
      if (state.open && index >= 0 && index < state.items.length && index !== state.active) set({ active: index })
    },
    close() {
      if (state.open) set({ open: false, active: -1 })
    },
    focus() {
      if (!state.open && suggestionPath(state.query) && state.status !== 'idle') set({ open: true })
    },
    dispose: cancel,
    state: () => state,
  }
}
