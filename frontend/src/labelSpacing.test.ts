// Label above value (DESIGN_SYSTEM §5 標籤與值, #463): every value sits a spacing token below its label, written as the
// value's margin-top; never 0 and never a literal px. Covers each <dl class> the components render, the Stat and
// market-widget values, and fails when a new <dl> ships without its rule.

// The frontend ships no Node typings; scripts/ci-test.cjs runs this module under Node, so declare what it uses.
declare const require: (id: string) => unknown
declare const __dirname: string
type DirEntry = { name: string; isDirectory(): boolean }
const fs = require('node:fs') as { readdirSync(dir: string, options: { withFileTypes: true }): DirEntry[]; readFileSync(file: string, encoding: 'utf8'): string }
const path = require('node:path') as { join(...parts: string[]): string; relative(from: string, to: string): string; sep: string }

const failures: string[] = []
let checks = 0
const check = (condition: boolean, message: string) => { checks++; if (!condition) failures.push(message) }

const srcRoot = __dirname
const css = fs.readFileSync(path.join(srcRoot, 'styles.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
const tokens = fs.readFileSync(path.join(srcRoot, 'styles', 'tokens.css'), 'utf8')
check(/--space-label:\s*var\(--space-1\);/.test(tokens), 'tokens.css defines --space-label as var(--space-1) (DESIGN_SYSTEM §2)')

// Every rule (also inside @media) as [selector list, body].
const rules = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((match) => ({ selectors: match[1].split(',').map((s) => s.trim()), body: match[2] }))
// The top margin a rule sets, or null when it sets none: margin-top, or the first value of the margin shorthand.
function topMargin(body: string): string | null {
  let top: string | null = null
  for (const [, property, value] of body.matchAll(/(margin(?:-top)?)\s*:\s*([^;]+)/g)) {
    top = property === 'margin-top' ? value.trim() : (value.trim().match(/var\([^)]*\)|\S+/)?.[0] ?? null)
  }
  return top
}
const isSpaceToken = (value: string) => /^var\(--space-(label|\d+)\)$/.test(value)

// The value selectors: `.<dl class> dd` for each <dl> in the components, plus the two widget values.
function sources(dir: string, found: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) sources(full, found)
    else if (/\.tsx$/.test(entry.name) && !/\.test\.tsx$/.test(entry.name)) found.push(full)
  }
  return found
}
const dlClasses = new Set<string>()
for (const file of sources(srcRoot)) {
  for (const [, classes] of fs.readFileSync(file, 'utf8').matchAll(/<dl className="([^"]+)"/g)) dlClasses.add(classes.split(' ')[0])
}
check(dlClasses.size >= 8, `found the label/value lists, got ${[...dlClasses].join('、')}`)
const valueSelectors = [...[...dlClasses].map((name) => `.${name} dd`), '.stat-value', '.market-widget-value']

for (const selector of valueSelectors) {
  const own = rules.filter((rule) => rule.selectors.includes(selector))
  const tops = own.map((rule) => topMargin(rule.body)).filter((top): top is string => top !== null)
  check(tops.length > 0, `${selector}: no margin-top; the value needs a spacing token below its label (DESIGN_SYSTEM §5 標籤與值)`)
  for (const top of tops) check(isSpaceToken(top), `${selector}: margin-top is 「${top}」; use var(--space-label) or another --space-* token, never 0 or px`)
}
// Any other rule that reaches these values (a descendant or a media override) may not take the space away.
for (const rule of rules) {
  for (const selector of rule.selectors) {
    if (valueSelectors.includes(selector) || !valueSelectors.some((value) => selector.endsWith(' ' + value))) continue
    const top = topMargin(rule.body)
    if (top !== null) check(isSpaceToken(top), `${selector}: margin-top is 「${top}」; use a --space-* token (DESIGN_SYSTEM §5 標籤與值)`)
  }
}

if (failures.length) {
  console.error(`label spacing checks failed:\n- ${failures.join('\n- ')}`)
  throw new Error(`${failures.length} of ${checks} label spacing checks failed (listed above)`)
}
console.log('label spacing', checks, 'checks passed')
