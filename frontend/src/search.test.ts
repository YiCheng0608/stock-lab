import * as search from './search'
import type { Suggestion, SuggestTimer } from './search'

const { commitSearchOnEnter } = search
const check = (condition: unknown, message: string) => { if (!condition) throw new Error(message) }

// ---- page search boxes (/stocks, /watch): a query is committed only on Enter ----
const submitted = commitSearchOnEnter('  2330  ', 'Enter')
check(submitted === '2330', 'Enter should commit a trimmed search value')
check(commitSearchOnEnter('2330', 'a') === null, 'typing must not commit a search value')
check(commitSearchOnEnter('', 'Enter') === '', 'Enter should allow clearing to an empty query')

// ---- navbar suggestions (Issue 599): while typing only the light /instruments API is asked, debounced ----
check(typeof search.createSuggestController === 'function', 'search.ts exports the navbar suggestion controller (Issue 599)')

const items: Suggestion[] = [
  { exchange: 'TWSE', symbol: '2330', name: '台積電' },
  { exchange: 'TWSE', symbol: '2303', name: '聯電' },
  { exchange: 'TPEx', symbol: '00723B', name: '群益投資級科技債' },
]

type Harness = ReturnType<typeof harness>
function harness(respond: (path: string) => Promise<Suggestion[]> = () => Promise.resolve(items)) {
  const timers = new Map<number, () => void>()
  let next = 0
  const delays: number[] = []
  const timer: SuggestTimer = {
    set: (callback, ms) => { delays.push(ms); timers.set(++next, callback); return next },
    clear: (handle) => { timers.delete(handle as number) },
  }
  const asked: string[] = []
  const aborted: string[] = []
  const controller = search.createSuggestController({
    timer,
    onChange: () => {},
    fetchSuggestions: (path, signal) => {
      asked.push(path)
      signal.addEventListener('abort', () => aborted.push(path))
      return respond(path)
    },
  })
  const flushTimers = () => { const due = [...timers.values()]; timers.clear(); due.forEach((run) => run()) }
  return { controller, asked, aborted, delays, flushTimers, pendingTimers: () => timers.size }
}
// Microtasks only: the test runner settles a module once (setImmediate) before its PASS line.
const settle = async () => { for (let turn = 0; turn < 10; turn++) await Promise.resolve() }
async function typeAndLoad(h: Harness, value: string) {
  h.controller.input(value)
  h.flushTimers()
  await settle()
}

async function run() {
  // Debounce: three key presses, one request after the delay, for the last value, to /instruments only.
  const typing = harness()
  for (const value of ['2', '23', '233']) typing.controller.input(value)
  check(typing.asked.length === 0, `no request before the debounce delay, got ${typing.asked.join(', ')}`)
  check(typing.pendingTimers() === 1, 'each key press replaces the pending request')
  check(typing.delays.every((ms) => ms >= 200 && ms <= 300), `debounce is 200–300 ms, got ${typing.delays.join(', ')}`)
  typing.flushTimers()
  await settle()
  check(typing.asked.length === 1, `one request for three key presses, got ${typing.asked.length}`)
  check(typing.asked[0] === '/instruments?q=233&securities_only=true&page_size=8', `suggestion request path: ${typing.asked[0]}`)
  check(typing.asked.every((path) => !path.startsWith('/stocks')), 'typing never asks /api/stocks')
  let state = typing.controller.state()
  check(state.open && state.status === 'ready' && state.items.length === 3 && state.active === -1, `suggestions shown, none highlighted: ${JSON.stringify(state)}`)

  // Clearing the box asks nothing and hides the list.
  typing.controller.input('   ')
  typing.flushTimers()
  await settle()
  check(typing.asked.length === 1 && !typing.controller.state().open, 'a blank box asks nothing and shows no list')

  // Keyboard: down highlights the first, up wraps to the last, Enter opens that stock page.
  const keys = harness()
  await typeAndLoad(keys, '23')
  check(keys.controller.key('ArrowDown').kind === 'none' && keys.controller.state().active === 0, 'ArrowDown highlights the first suggestion')
  keys.controller.key('ArrowDown')
  check(keys.controller.state().active === 1, 'ArrowDown moves to the next suggestion')
  keys.controller.key('ArrowUp')
  keys.controller.key('ArrowUp')
  check(keys.controller.state().active === 2, `ArrowUp from the first wraps to the last, got ${keys.controller.state().active}`)
  const picked = keys.controller.key('Enter')
  check(picked.kind === 'navigate' && picked.path === '/stocks/TPEx/00723B', `Enter on a highlighted suggestion opens its stock page, got ${JSON.stringify(picked)}`)
  check(!keys.controller.state().open, 'choosing closes the list')

  // Mouse: a click chooses that option.
  const mouse = harness()
  await typeAndLoad(mouse, '台積')
  mouse.controller.highlight(1)
  check(mouse.controller.state().active === 1, 'hover highlights the option')
  const clicked = mouse.controller.choose(0)
  check(clicked.kind === 'navigate' && clicked.path === '/stocks/TWSE/2330', `clicking a suggestion opens its stock page, got ${JSON.stringify(clicked)}`)

  // Esc closes the list without leaving the box; focusing again reopens it.
  const escape = harness()
  await typeAndLoad(escape, '23')
  escape.controller.key('ArrowDown')
  escape.controller.key('Escape')
  state = escape.controller.state()
  check(!state.open && state.active === -1 && state.query === '23', `Esc closes the list and keeps the text: ${JSON.stringify(state)}`)
  check(escape.controller.key('Enter').kind === 'submit', 'Enter after Esc submits the search instead of a hidden option')
  escape.controller.focus()
  check(escape.controller.state().open, 'focusing the box again shows the suggestions')

  // Enter with nothing highlighted submits the form (→ /stocks?q=), also before the suggestions arrive.
  const plain = harness()
  await typeAndLoad(plain, '23')
  check(plain.controller.key('Enter').kind === 'submit', 'Enter without a highlighted suggestion submits the form')
  check(search.stockSearchPath(' 23 ') === '/stocks?q=23', 'the submitted form opens /stocks?q=')
  const early = harness()
  early.controller.input('2330')
  check(early.controller.key('Enter').kind === 'submit', 'Enter before the debounce fires submits the form')
  early.flushTimers()
  await settle()
  check(early.asked.length === 0 && !early.controller.state().open, 'a submitted search cancels the pending suggestion request')

  // A failed request does not block Enter and shows the failure state.
  const failing = harness(() => Promise.reject(new Error('API 500')))
  await typeAndLoad(failing, '23')
  state = failing.controller.state()
  check(state.status === 'error' && state.items.length === 0 && state.open, `a failed request shows the failure line: ${JSON.stringify(state)}`)
  check(failing.controller.key('ArrowDown').kind === 'none' && failing.controller.state().active === -1, 'nothing to highlight after a failure')
  check(failing.controller.key('Enter').kind === 'submit', 'Enter still submits after a failed request')

  // No match: ready with no items.
  const none = harness(() => Promise.resolve([]))
  await typeAndLoad(none, 'zzzz')
  state = none.controller.state()
  check(state.status === 'ready' && state.items.length === 0 && state.open, 'no match is a ready, empty list')

  // A slow answer for an older value never replaces a newer one; the older request is aborted.
  const resolvers: Record<string, (value: Suggestion[]) => void> = {}
  const slow = harness((path) => new Promise((resolve) => { resolvers[path] = resolve }))
  slow.controller.input('2')
  slow.flushTimers()
  slow.controller.input('23')
  slow.flushTimers()
  const [first, second] = slow.asked
  check(slow.aborted.includes(first), 'a newer value aborts the older request')
  resolvers[second]([items[1]])
  await settle()
  resolvers[first](items)
  await settle()
  state = slow.controller.state()
  check(state.items.length === 1 && state.items[0].symbol === '2303', `the older answer is ignored: ${JSON.stringify(state.items)}`)

  // At most eight suggestions.
  const many = harness(() => Promise.resolve(Array.from({ length: 12 }, (_, index) => ({ exchange: 'TWSE', symbol: String(1000 + index), name: `股${index}` }))))
  await typeAndLoad(many, '1')
  check(many.controller.state().items.length === 8, `at most 8 suggestions, got ${many.controller.state().items.length}`)
}

// A failed check rejects; scripts/ci-test.cjs reports the unhandled rejection against this file.
void run()
