// Run the frontend standalone regression modules in memory, without a server, browser or DOM.
// Every frontend/src/**/*.test.ts(x) must appear exactly once below: in SUITES (run) or in EXCLUDED (named reason).
// An unlisted file, a stale entry, an exported run* function no entry drives, or a runner that checks nothing fails
// the run, so a new test file or runner cannot be skipped silently.
const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const assert = require('node:assert/strict')
const root = path.resolve(__dirname, '..')
const srcRoot = path.join(root, 'src')
const workerRoot = path.resolve(root, '..', 'backend', 'worker')
const viteRequire = Module.createRequire(require.resolve('vite/package.json'))
const esbuild = viteRequire('esbuild')
// Same instance the bundled components import (react stays external), so hooks and renderer agree.
const { renderToStaticMarkup } = require('react-dom/server')

// One entry per test file (path relative to src). Top-level assertions run while the module loads.
//   runners: exported run* functions called with renderToStaticMarkup; each returns its check count.
//   chips:   async fixture builder + checker pair; the builder takes the policy literal embedded in a backend
//            worker module (tools/tpex-chips-series-preview.cjs reads it the same way). The owner digest pin that
//            the preview checks via --policy-digest is not repeated here.
const chips = (file, create, run, policy) => ({ file, chips: { create, run, policy } })
const SUITES = [
  { file: 'units.test.ts' },
  { file: 'search.test.ts' },
  { file: 'routes.test.ts' },
  { file: 'presentation.test.ts' },
  { file: 'stockChart.test.ts' },
  { file: 'OrdinaryCloseTrend.test.tsx' },
  { file: 'stockResearch.test.ts' },
  { file: 'components/StrategyVersionCard.test.tsx' },
  {
    file: 'components/StockOverview.test.tsx',
    runners: [
      'runPriceSavedOverviewSSRTests', 'runSavedFocusOverviewSSRTests', 'runPriceMemoryOverviewSSRTests',
      'runOfficialEventsSSRTests', 'runInstitutionalWindowSSRTests', 'runInstitutionalWindowCutoffSSRTests',
      'runInstitutionalWindowEarlierCutoffSSRTests', 'runInstitutionalWindowFifthCutoffSSRTests',
      'runInstitutionalWindowSixthCutoffSSRTests', 'runInstitutionalWindowSeventhCutoffSSRTests',
      'runInstitutionalWindowEighthCutoffSSRTests', 'runTwseIssuerProfileSSRTests', 'runUnitLotsSSRTests',
    ],
  },
  { file: 'institutionalWindows.test.ts', runners: ['runCalendarWindowTests', 'runScope7WindowTests'] },
  { file: 'institutionalWindows1006.test.tsx', runners: ['runChips1006SSRTests'] },
  { file: 'priceFocus.test.ts', runners: ['runScopeFocusTests', 'runPriceFocusTests'] },
  { file: 'savedPriceChipsFocus.test.ts', runners: ['runJointFocusTests', 'runCalendarFocusTests', 'runScope7FocusTests'] },
  { file: 'savedPriceFocus.test.ts', runners: ['runSavedPriceFocusTests'] },
  { file: 'stockPriceMemoryRead.test.ts', runners: ['runScopeMemoryReadTests', 'runStockPriceMemoryReadTests'] },
  { file: 'stockPriceSavedRead.test.ts', runners: ['runStockPriceSavedReadTests'] },
  { file: 'twseIssuerIndustry.test.ts', runners: ['runTwseIssuerIndustryTests'] },
  chips('chipsAdjacent.test.ts', 'createAdjacentFixture', 'runAdjacentChecks', 'tpex_institutional_adjacent_scope7.py'),
  chips('chipsDealerComponents.test.ts', 'createDealerFixture', 'runDealerChecks', 'tpex_institutional_dealer_components_scope7.py'),
  chips('chipsDealerDirectionCombos.test.ts', 'createCombosFixture', 'runComboChecks'),
  chips('chipsDirection.test.ts', 'createDirectionFixture', 'runDirectionChecks', 'tpex_institutional_direction_scope7.py'),
  chips('chipsGross.test.ts', 'createGrossFixture', 'runGrossChecks', 'tpex_institutional_gross_scope7.py'),
  chips('chipsSeries.test.ts', 'createSeriesFixture', 'runSeriesChecks', 'tpex_institutional_series_scope7.py'),
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
  })
  const testModule = new Module(filename, module)
  testModule.filename = filename
  testModule.paths = Module._nodeModulePaths(path.dirname(filename))
  testModule._compile(result.outputFiles[0].text, filename)
  return testModule.exports
}

function readPolicy(workerFile) {
  const match = fs.readFileSync(path.join(workerRoot, workerFile), 'utf8').match(/POLICY_CANONICAL = r'''([\s\S]*?)'''/)
  assert(match, `POLICY_CANONICAL literal not found in backend/worker/${workerFile}`)
  return JSON.parse(match[1])
}

// A module may start async checks at load (OrdinaryCloseTrend.test.tsx); they settle within one event-loop turn
// (no I/O), and their rejections are attributed to the suite being loaded instead of crashing the process.
const stray = []
process.on('unhandledRejection', (reason) => stray.push(reason))
const settle = () => new Promise((resolve) => setImmediate(resolve))

async function runSuite(suite) {
  const exported = loadModule(path.join(srcRoot, suite.file))
  await settle()
  if (stray.length) throw stray.shift()
  const driven = [...(suite.runners ?? []), ...(suite.chips ? [suite.chips.run] : [])]
  const absent = driven.filter((name) => typeof exported[name] !== 'function')
  assert(!absent.length, `listed runner not exported: ${absent.join(', ')}`)
  const undriven = Object.keys(exported).filter((name) => /^run[A-Z]/.test(name) && typeof exported[name] === 'function' && !driven.includes(name))
  assert(!undriven.length, `exported runner not driven by SUITES: ${undriven.join(', ')}`)
  const counts = []
  for (const name of suite.runners ?? []) counts.push([name, await exported[name](renderToStaticMarkup)])
  if (suite.chips) {
    const { create, run, policy } = suite.chips
    const fixture = await exported[create](policy && readPolicy(policy))
    counts.push([run, await exported[run](fixture.read, (ok, label) => assert(ok, label))])
  }
  for (const [name, count] of counts) assert(Number.isInteger(count) && count > 0, `${name} reported ${count} checks`)
  return counts
}

async function main() {
  // The tests are compiled with jsx 'automatic': tsconfig.app.json "react-jsx" (checked by tsc) and @vitejs/plugin-react.
  assert(/"jsx"\s*:\s*"react-jsx"/.test(fs.readFileSync(path.join(root, 'tsconfig.app.json'), 'utf8')),
    'tsconfig.app.json jsx is no longer "react-jsx"; update the esbuild jsx option in scripts/ci-test.cjs')
  const failed = []
  const fail = (file, error) => {
    failed.push(file)
    console.error(`FAIL ${file}: ${error && error.stack ? error.stack.split('\n').slice(0, 6).join('\n') : error}`)
  }
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
      const counts = await runSuite(suite)
      passed++
      console.log(`PASS ${suite.file}${counts.length ? ` (${counts.map(([name, count]) => `${name} ${count}`).join(', ')})` : ''}`)
    } catch (error) { fail(suite.file, error) }
  }
  await settle()
  for (const reason of stray.splice(0)) fail('(unhandled rejection after the suites ran)', reason)
  if (failed.length) {
    console.error(`Failed ${failed.length}: ${[...new Set(failed)].join(', ')}`)
    process.exitCode = 1
    return
  }
  console.log(`Passed ${passed} test modules, ${Object.keys(EXCLUDED).length} excluded; this is not browser or full product QA.`)
}

main().catch((error) => { console.error(error); process.exitCode = 1 })
