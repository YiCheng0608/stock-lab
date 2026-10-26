// Run the frontend standalone regression modules in memory, without a server, browser or DOM.
// Every frontend/src/**/*.test.ts(x) must appear exactly once below: in SUITES (run) or in EXCLUDED (named reason).
// An unlisted file, a stale entry, an exported run* function no entry drives, or a runner that checks nothing fails
// the run, so a new test file or runner cannot be skipped silently.
const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const assert = require('node:assert/strict')
const { AsyncLocalStorage } = require('node:async_hooks')
const root = path.resolve(__dirname, '..')
const srcRoot = path.join(root, 'src')
const viteRequire = Module.createRequire(require.resolve('vite/package.json'))
const esbuild = viteRequire('esbuild')
// Same instance the bundled components import (react stays external), so hooks and renderer agree.
const { renderToStaticMarkup } = require('react-dom/server')

// One entry per test file (path relative to src). Top-level assertions run while the module loads.
//   runners: exported run* functions called with renderToStaticMarkup; each returns its check count.
const SUITES = [
  { file: 'units.test.ts' },
  { file: 'search.test.ts' },
  { file: 'presentation.test.ts' },
  { file: 'noHardcodedColors.test.ts' },
  { file: 'stock/stockBars.test.tsx' },
  { file: 'components/StrategyVersionCard.test.tsx' },
  { file: 'components/ui/ui.test.tsx' },
  { file: 'themes/themeBoards.test.tsx' },
  { file: 'themes/themeSuggestions.test.tsx' },
  { file: 'news/news.test.tsx' },
  { file: 'candidates/candidates.test.tsx' },
  { file: 'tables.test.tsx' },
]

// Test files that cannot run here: path relative to src -> why (needs a browser/DOM or a guarded environment) and
// where it runs instead. Empty: every current test file runs in memory under Node.
const EXCLUDED = {}

function discover(dir, found = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) { if (entry.name !== 'node_modules') discover(full, found) }
    else if (/\.test\.tsx?$/.test(entry.name)) found.push(path.relative(srcRoot, full).split(path.sep).join('/'))
  }
  return found.sort()
}

function loadModule(filename) {
  const result = esbuild.buildSync({
    entryPoints: [filename], bundle: true, platform: 'node', format: 'cjs', write: false, logLevel: 'error',
    jsx: 'automatic', packages: 'external', loader: { '.css': 'empty' }, // page styles do not affect the assertions
    define: { 'import.meta.env': '{}' }, // api.ts reads the Vite env at load; App tables render without a server
  })
  const testModule = new Module(filename, module)
  testModule.filename = filename
  testModule.paths = Module._nodeModulePaths(path.dirname(filename))
  testModule._compile(result.outputFiles[0].text, filename)
  return testModule.exports
}

const failed = []
const fail = (file, error) => {
  failed.push(file)
  console.error(`FAIL ${file}: ${error && error.stack ? error.stack.split('\n').slice(0, 6).join('\n') : error}`)
}
const summarize = () => console.error(`Failed ${failed.length}: ${[...new Set(failed)].join(', ')}`)

// A module may start async checks at load. A rejection nobody handles can surface at any
// time, even after the last PASS line (a timer in a test), so it is reported when it happens and always fails the run.
// The suite whose load started the async chain owns it; without an owner it is reported as unowned.
const owner = new AsyncLocalStorage()
let concluded = false
process.on('unhandledRejection', (reason) => {
  fail(owner.getStore() ?? '(unhandled rejection outside any suite)', reason)
  process.exitCode = 1
  if (concluded) summarize() // the Passed line is already out; end with the failure, not the success
})
const settle = () => new Promise((resolve) => setImmediate(resolve))

async function runSuite(suite) {
  const exported = loadModule(path.join(srcRoot, suite.file))
  await settle() // microtask-only async checks finish here, before the PASS line
  if (failed.includes(suite.file)) return null
  const driven = suite.runners ?? []
  const absent = driven.filter((name) => typeof exported[name] !== 'function')
  assert(!absent.length, `listed runner not exported: ${absent.join(', ')}`)
  const undriven = Object.keys(exported).filter((name) => /^run[A-Z]/.test(name) && typeof exported[name] === 'function' && !driven.includes(name))
  assert(!undriven.length, `exported runner not driven by SUITES: ${undriven.join(', ')}`)
  const counts = []
  for (const name of suite.runners ?? []) counts.push([name, await exported[name](renderToStaticMarkup)])
  for (const [name, count] of counts) assert(Number.isInteger(count) && count > 0, `${name} reported ${count} checks`)
  return counts
}

async function main() {
  // The tests are compiled with jsx 'automatic': tsconfig.app.json "react-jsx" (checked by tsc) and @vitejs/plugin-react.
  assert(/"jsx"\s*:\s*"react-jsx"/.test(fs.readFileSync(path.join(root, 'tsconfig.app.json'), 'utf8')),
    'tsconfig.app.json jsx is no longer "react-jsx"; update the esbuild jsx option in scripts/ci-test.cjs')
  const found = discover(srcRoot)
  const listed = [...SUITES.map((suite) => suite.file), ...Object.keys(EXCLUDED)]
  for (const file of found) if (!listed.includes(file)) fail(file, 'test file is in neither SUITES nor EXCLUDED of scripts/ci-test.cjs')
  for (const file of new Set(listed)) {
    if (!found.includes(file)) fail(file, 'listed in scripts/ci-test.cjs but no such test file under src')
    else if (listed.indexOf(file) !== listed.lastIndexOf(file)) fail(file, 'listed more than once in scripts/ci-test.cjs')
  }
  for (const [file, reason] of Object.entries(EXCLUDED)) {
    if (typeof reason === 'string' && reason.trim()) console.log(`SKIP ${file}: ${reason}`)
    else fail(file, 'EXCLUDED entry needs a reason')
  }
  let passed = 0
  for (const suite of SUITES) {
    if (!found.includes(suite.file) || failed.includes(suite.file)) continue
    try {
      const counts = await owner.run(suite.file, () => runSuite(suite))
      if (!counts) continue // its unhandled rejection is already reported
      passed++
      console.log(`PASS ${suite.file}${counts.length ? ` (${counts.map(([name, count]) => `${name} ${count}`).join(', ')})` : ''}`)
    } catch (error) { fail(suite.file, error) }
  }
  concluded = true
  if (failed.length) {
    summarize()
    process.exitCode = 1
    return
  }
  console.log(`Passed ${passed} test modules, ${Object.keys(EXCLUDED).length} excluded; this is not browser or full product QA.`)
}

main().catch((error) => { console.error(error); process.exitCode = 1 })
