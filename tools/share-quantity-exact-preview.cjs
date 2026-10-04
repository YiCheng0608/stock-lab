/** Reconstructable M3-P2 memory-output quantity checks and full-App preview.
 * Existing --deps is borrowed read-only. --check needs no running server;
 * --http-check exercises the actual owned SQLite HTTP router after it starts.
 * No bundles, buildinfo, responses, screenshots, cache or test files are saved.
 */
const fs = require('node:fs')
const path = require('node:path')
const http = require('node:http')
const Module = require('node:module')
const assert = require('node:assert/strict')

const args = process.argv.slice(2)
let ssrLayoutWarnings = 0
if (args.includes('--quantity-trust-check') || args.includes('--quantity-trust-http-check')
  || args.includes('--quote-read-check') || args.includes('--quote-read-http-check')
  || args.includes('--action-read-check') || args.includes('--action-read-http-check')
  || args.includes('--stock-read-check') || args.includes('--stock-read-http-check')) {
  const originalError = console.error
  console.error = (message, ...rest) => {
    if (typeof message === 'string' && message.startsWith('Warning: useLayoutEffect does nothing on the server')) {
      ssrLayoutWarnings++
    } else originalError(message, ...rest)
  }
}
const option = (name, fallback) => {
  const index = args.indexOf(name)
  return index < 0 ? fallback : args[index + 1]
}
const root = path.resolve(__dirname, '..')
const dependencies = path.resolve(option('--deps', ''))
if (!args.includes('--deps') || !fs.existsSync(path.join(dependencies, 'typescript/package.json'))) {
  throw new Error('--deps must name an existing read-only frontend/node_modules')
}
const apiOrigin = new URL(option('--api', 'http://127.0.0.1:8779'))
if (apiOrigin.protocol !== 'http:' || apiOrigin.hostname !== '127.0.0.1' || apiOrigin.pathname !== '/' || apiOrigin.search || apiOrigin.hash) {
  throw new Error('--api must be an owned 127.0.0.1 HTTP origin')
}
const requireDependency = Module.createRequire(path.join(dependencies, '../package.json'))
const compilerPackage = path.join(dependencies, '.pnpm/node_modules/esbuild')
const compilerBinary = fs.realpathSync(require.resolve(`@esbuild/${process.platform}-${process.arch}/esbuild.exe`, { paths: [compilerPackage] }))
const childProcess = require('node:child_process')
const originalSpawn = childProcess.spawn
childProcess.spawn = function (command, compilerArgs, options) {
  if (fs.realpathSync(command) !== compilerBinary || !Array.isArray(compilerArgs)
    || !compilerArgs.some((arg) => /^--service=/.test(arg))
    || compilerArgs.some((arg) => !/^--service=/.test(arg) && arg !== '--ping')) {
    throw new Error('memory-only preview denied an unowned subprocess')
  }
  return originalSpawn.call(this, command, compilerArgs, options)
}
for (const name of ['exec', 'execSync', 'execFile', 'execFileSync', 'spawnSync', 'fork']) {
  childProcess[name] = () => { throw new Error('memory-only preview denied an unowned subprocess') }
}
// Deny Node filesystem mutations before loading tools and source modules. The
// esbuild service uses its installed binary, with all build output in memory.
const denied = () => { throw new Error('memory-only preview denied a filesystem mutation') }
for (const name of ['writeFile', 'writeFileSync', 'appendFile', 'appendFileSync', 'mkdir', 'mkdirSync', 'mkdtemp', 'mkdtempSync',
  'rename', 'renameSync', 'unlink', 'unlinkSync', 'rm', 'rmSync', 'rmdir', 'rmdirSync', 'copyFile', 'copyFileSync',
  'truncate', 'truncateSync', 'ftruncate', 'ftruncateSync', 'chmod', 'chmodSync', 'chown', 'chownSync', 'utimes', 'utimesSync',
  'link', 'linkSync', 'symlink', 'symlinkSync', 'createWriteStream', 'write', 'writeSync', 'writev', 'writevSync']) {
  fs[name] = denied
}
for (const name of ['writeFile', 'appendFile', 'mkdir', 'mkdtemp', 'rename', 'unlink', 'rm', 'rmdir', 'copyFile',
  'truncate', 'chmod', 'chown', 'utimes', 'link', 'symlink']) fs.promises[name] = denied
const safeFlags = (flags) => typeof flags === 'string' ? flags === 'r' || flags === 'rs' :
  !(flags & (fs.constants.O_WRONLY | fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_TRUNC | fs.constants.O_APPEND))
for (const name of ['open', 'openSync']) {
  const original = fs[name]
  fs[name] = function (filename, flags, ...rest) {
    if (!safeFlags(flags)) return denied()
    return original.call(fs, filename, flags, ...rest)
  }
}
const originalPromiseOpen = fs.promises.open
fs.promises.open = async (filename, flags, ...rest) => {
  if (!safeFlags(flags)) return denied()
  return originalPromiseOpen.call(fs.promises, filename, flags, ...rest)
}
const originalFetch = global.fetch
global.fetch = (input, options = {}) => {
  const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url)
  if (url.origin !== apiOrigin.origin) throw new Error('memory-only preview denied an unowned network destination')
  return originalFetch(input, { ...options, redirect: 'error' })
}
const ts = requireDependency('typescript')
const esbuild = require(compilerPackage)
const sourceRoot = path.join(root, 'frontend/src')
const dependencySource = path.resolve(dependencies, '../src')

// Source is compiled inside CommonJS modules; dependency resolution borrows
// master node_modules and never creates a junction in this worktree.
const originalResolve = Module._resolveFilename
let resolvingBorrowedDependency = false
Module._resolveFilename = function (request, parent, ...rest) {
  try { return originalResolve.call(this, request, parent, ...rest) } catch (error) {
    if (resolvingBorrowedDependency || error.code !== 'MODULE_NOT_FOUND' || request.startsWith('.') || path.isAbsolute(request)) throw error
    resolvingBorrowedDependency = true
    try { return requireDependency.resolve(request) } finally { resolvingBorrowedDependency = false }
  }
}
for (const extension of ['.ts', '.tsx']) {
  Module._extensions[extension] = (module, filename) => {
    const result = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
      compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
      fileName: filename,
    })
    module._compile(result.outputText, filename)
  }
}

function typecheck() {
  const filename = path.join(root, 'frontend/tsconfig.app.json')
  const config = ts.readConfigFile(filename, ts.sys.readFile)
  if (config.error) throw new Error(ts.flattenDiagnosticMessageText(config.error.messageText, '\n'))
  const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, path.dirname(filename))
  const options = { ...parsed.options, noEmit: true, incremental: false, composite: false }
  const host = ts.createCompilerHost(options)
  host.writeFile = denied
  host.resolveModuleNames = (names, containingFile) => {
    const relative = path.relative(sourceRoot, path.resolve(containingFile))
    const ownSource = !relative.startsWith('..') && !path.isAbsolute(relative)
    return names.map((name) => ts.resolveModuleName(name, name.startsWith('.') || !ownSource
      ? containingFile : path.join(dependencySource, path.basename(containingFile)), options, host).resolvedModule)
  }
  const program = ts.createProgram(parsed.fileNames, options, host)
  const diagnostics = [...parsed.errors, ...ts.getPreEmitDiagnostics(program)]
  if (diagnostics.length) {
    console.error(JSON.stringify({ typescript_diagnostics: diagnostics.length }))
    console.error(ts.formatDiagnosticsWithColorAndContext(diagnostics.slice(0, 15), { getCanonicalFileName: (f) => f, getCurrentDirectory: () => root, getNewLine: () => '\n' }))
    throw new Error('TypeScript validation failed')
  }
  console.log('TypeScript full src check passed; no emit/buildinfo')
}

async function apiModule() {
  const result = await esbuild.build({ entryPoints: [path.join(sourceRoot, 'api.ts')], bundle: true, write: false,
    platform: 'node', format: 'cjs', target: 'es2020', define: { 'import.meta.env.VITE_API_BASE': JSON.stringify(apiOrigin.origin + '/api') } })
  const module = new Module(path.join(sourceRoot, '__memory_api__.cjs'))
  module.filename = path.join(sourceRoot, '__memory_api__.cjs')
  module._compile(result.outputFiles[0].text, module.filename)
  return module.exports
}


async function appModule() {
  const stockMode = args.includes('--stock-read-check') || args.includes('--stock-read-http-check')
  const result = await esbuild.build({ entryPoints: [path.join(sourceRoot, 'App.tsx')], bundle: true, write: false,
    nodePaths: [dependencies], platform: 'node', format: 'cjs', packages: stockMode ? undefined : 'external',
    external: stockMode ? ['react', 'react-dom', 'react-router-dom', '@tanstack/react-query'] : [], target: 'es2020', jsx: 'automatic',
    plugins: [{ name: 'actual-chart-cjs', setup(build) {
      if (!stockMode) return
      build.onResolve({ filter: /^echarts-for-react$/ }, () => ({ path: 'actual-echarts-react-class', namespace: 'actual-chart' }))
      build.onLoad({ filter: /.*/, namespace: 'actual-chart' }, () => ({
        // Keep the installed chart class; bridge its CJS default export for the
        // Node SSR bundle without replacing the chart or changing browser code.
        contents: `module.exports = require(${JSON.stringify(requireDependency.resolve('echarts-for-react'))}).default;`,
        loader: 'js', resolveDir: path.dirname(requireDependency.resolve('echarts-for-react')),
      }))
    } }],
    define: { 'import.meta.env.VITE_API_BASE': JSON.stringify(apiOrigin.origin + '/api') } })
  const module = new Module(path.join(sourceRoot, '__memory_app__.cjs'))
  module.filename = path.join(sourceRoot, '__memory_app__.cjs')
  module._compile(result.outputFiles[0].text, module.filename)
  return module.exports
}

async function browserBuild() {
  return esbuild.build({ entryPoints: [path.join(sourceRoot, 'main.tsx')], bundle: true, write: false,
    absWorkingDir: path.join(root, 'frontend'), nodePaths: [dependencies], outdir: '__memory_only__',
    platform: 'browser', format: 'esm', target: 'es2020', jsx: 'automatic',
    define: { 'import.meta.env.VITE_API_BASE': JSON.stringify('/api'), 'process.env.NODE_ENV': JSON.stringify('development') } })
}

async function portfolioRenderer() {
  const { PortfolioSubsection } = await appModule()
  const React = requireDependency('react')
  const { renderToStaticMarkup } = requireDependency('react-dom/server')
  const { MemoryRouter } = requireDependency('react-router-dom')
  const { QueryClient, QueryClientProvider } = requireDependency('@tanstack/react-query')
  return (items) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    client.setQueryData(['portfolio-subsection'], { items, meta: { page: 1, page_size: 20, total: items.length } })
    try {
      return renderToStaticMarkup(React.createElement(MemoryRouter, null,
        React.createElement(QueryClientProvider, { client }, React.createElement(PortfolioSubsection))))
    } finally { client.clear() }
  }
}

async function quantityTrustRenderer() {
  const app = await appModule()
  const React = requireDependency('react')
  const { renderToStaticMarkup } = requireDependency('react-dom/server')
  const { MemoryRouter } = requireDependency('react-router-dom')
  const { QueryClient, QueryClientProvider } = requireDependency('@tanstack/react-query')
  return (component, props = {}, entries = []) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    for (const [key, data] of entries) client.setQueryData(key, data)
    try {
      return renderToStaticMarkup(React.createElement(MemoryRouter, null,
        React.createElement(QueryClientProvider, { client }, React.createElement(app[component], props))))
    } finally { client.clear() }
  }
}

async function stockPageRenderer() {
  const app = await appModule()
  const React = requireDependency('react')
  const { renderToStaticMarkup } = requireDependency('react-dom/server')
  const { MemoryRouter } = requireDependency('react-router-dom')
  const { QueryClient, QueryClientProvider } = requireDependency('@tanstack/react-query')
  return (data, route = '/stocks/TWSE/A-NORMAL?as_of=2026-10-04') => {
    const url = new URL(route, apiOrigin)
    const asOf = url.searchParams.get('as_of') || ''
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    client.setQueryData(['stock', data.instrument.exchange, data.instrument.symbol, asOf], data)
    try {
      return renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: [route] },
        React.createElement(QueryClientProvider, { client }, React.createElement(app.default))))
    } finally { client.clear() }
  }
}

function syntheticStock() {
  const metadata = Object.fromEntries(['adj_close', 'turnover', 'turnover_status', 'turnover_reason', 'data_as_of', 'collected_at', 'raw_payload_id'].map((key) => [key, 'missing']))
  const core = { status: 'known', invalid_fields: [], missing_fields: [], metadata_fields: metadata }
  return { instrument: { id: 1, exchange: 'TWSE', symbol: 'A-NORMAL', name: 'Synthetic stock read', instrument_type: 'stock' },
    bars: [{ id: 1, date: '2026-10-04', open: 10, high: 11, low: 9, close: 10.5, adj_close: null, volume: 1000, volume_exact: '1000',
      turnover: null, turnover_status: 'unknown', turnover_reason: null, source: 'fixture-stock-detail', data_as_of: null, collected_at: null,
      is_suspended: false, market_read: core }],
    market_read: { ...core, candidate_count: 1, window_limit: 120, unlocated_count: 0, unlocated_market_bar_id: null, verification: 'stored_value_syntax_only' },
    features: {}, groups: [], chips: [], corporate_actions: [], fundamentals: [], events: [], data_quality: [], signals: [], news: [],
    decision_summary: null, strategy_conditions: {} }
}

async function stockReadCheck() {
  typecheck()
  if (args.includes('--type-only')) {
    console.log(JSON.stringify({ passed: true, node: process.version, typescript: ts.version, validation: 'noEmit only', disk_artifacts: 0 }))
    esbuild.stop(); return
  }
  require(path.join(sourceRoot, 'stockChart.test.ts'))
  const render = await stockPageRenderer()
  let cases = 0
  const checks = [
    ['metadata-only', (p) => { p.market_read.metadata_fields.data_as_of = 'invalid'; p.bars[0].market_read.metadata_fields.collected_at = 'invalid' }, false],
    ['invalid', (p) => { p.market_read.status = 'invalid'; p.market_read.invalid_fields = ['close'] }, true],
    ['missing', (p) => { p.market_read.status = 'missing'; p.market_read.candidate_count = 0; p.market_read.missing_fields = ['market_bar']; p.bars = [] }, true],
    ['null', (p) => { p.market_read = null }, true],
    ['partial', (p) => { p.market_read = { status: 'known' } }, true],
    ['known-invalid', (p) => { p.market_read.invalid_fields = ['source'] }, true],
    ['known-missing', (p) => { p.market_read.missing_fields = ['volume'] }, true],
    ['no-count', (p) => { delete p.market_read.candidate_count }, true],
    ['no-metadata-keys', (p) => { p.market_read.metadata_fields = {} }, true],
    ['no-verifier', (p) => { delete p.market_read.verification }, true],
    ['zero-candidates', (p) => { p.market_read.candidate_count = 0 }, true],
    ['bar-invalid', (p) => { p.bars[0].market_read = { ...p.bars[0].market_read, invalid_fields: ['source'] } }, true],
    ['invalid-date', (p) => { p.bars[0].date = '2026-02-30' }, true],
    ['decision-conflict', (p) => { p.decision_summary = { current_price: 900, price_change: 50, price_change_pct: 3 } }, true],
    ['legacy-infinity', (p) => { delete p.market_read; delete p.bars[0].market_read; p.bars[0].close = Infinity; p.decision_summary = { current_price: Infinity, price_change: Infinity, price_change_pct: Infinity } }, true],
    ['percent-overflow', (p) => { delete p.market_read; delete p.bars[0].market_read; p.decision_summary = { current_price: 10.5, price_change: 1, price_change_pct: 1e308 } }, false],
    ['core-source-null', (p) => { p.bars[0].source = null }, true],
    ['core-nonpositive', (p) => { p.bars[0].close = 0 }, true],
    ['unicode-source', (p) => { p.bars[0].source = '😀'.repeat(120) }, false],
    ['change-conflict', (p) => { p.bars.unshift({ ...p.bars[0], id: 2, date: '2026-10-03', close: 10 }); p.decision_summary = { current_price: 10.5, price_change: 99, price_change_pct: 0.05 } }, false],
    ['percent-conflict', (p) => { p.bars.unshift({ ...p.bars[0], id: 2, date: '2026-10-03', close: 10 }); p.decision_summary = { current_price: 10.5, price_change: 0.5, price_change_pct: 99 } }, false],
    ['previous-invalid', (p) => { p.bars.unshift({ ...p.bars[0], id: 2, date: '2026-10-03', close: 10, source: null }); p.decision_summary = { current_price: 10.5, price_change: 0.5, price_change_pct: 0.05 } }, false],
  ]
  for (const [name, mutate, unverified] of checks) {
    const data = syntheticStock(); mutate(data)
    const before = structuredClone(data)
    const html = render(data)
    assert.ok(html.includes('個股詳情分頁') && html.includes('研究條件'), name + ': actual StockPage')
    assert.ok(!/Infinity|NaN/.test(html), name + ': non-finite display')
    assert.ok(html.includes('最近收盤（報價幣別元）</span><strong>' + (unverified ? '待核實' : '10.5') + '</strong>'), name + ': headline')
    if (name === 'decision-conflict') assert.ok(html.includes('漲跌（元／%）</span><strong class="">待核實</strong>'))
    if (['change-conflict', 'previous-invalid'].includes(name)) assert.ok(html.includes('漲跌（元／%）</span><strong class="">待核實</strong>'), name + ': delta isolation')
    if (name === 'percent-conflict') assert.ok(!html.includes('9,900%') && html.includes('>+0.5</strong>'), name + ': percentage isolation')
    assert.deepEqual(data, before, name + ': mutated input')
    cases++
  }
  const bundle = await browserBuild()
  assert.ok(bundle.outputFiles.some((file) => file.path.endsWith('.js')))
  console.log(JSON.stringify({ passed: true, node: process.version, stock_page_full_app_ssr: cases,
    typescript: ts.version, known_ssr_use_layout_effect_warnings: ssrLayoutWarnings,
    memory_build: { write: false, js_bytes: bundle.outputFiles.filter((file) => file.path.endsWith('.js')).reduce((sum, file) => sum + file.contents.byteLength, 0),
      css_bytes: bundle.outputFiles.filter((file) => file.path.endsWith('.css')).reduce((sum, file) => sum + file.contents.byteLength, 0) },
    source: 'synthetic read classifications only; not admitted M1 price evidence', disk_artifacts: 0,
    excluded: 'real browser operations, production DB, M1 filesystem positive, save/reopen' }))
  esbuild.stop()
}

async function stockReadHttpCheck() {
  const api = await apiModule()
  const render = await stockPageRenderer()
  let routes = 0, ssr = 0
  const guardedFetch = global.fetch
  global.fetch = async (url, options = {}) => {
    if (options.method && options.method !== 'GET') throw new Error('stock read HTTP check is GET only')
    if (++routes > 48) throw new Error('stock read HTTP route cap exceeded')
    const response = await guardedFetch(url, options)
    const copy = response.clone()
    if ((await copy.arrayBuffer()).byteLength > 2 * 1024 * 1024) throw new Error('stock response cap exceeded')
    return response
  }
  const snapshot = async () => (await fetch(apiOrigin.origin + '/__review__/stock-read-snapshot')).json()
  try {
    const before = await snapshot()
    const followup = args.includes('--stock-read-followup')
    const symbols = followup ? ['I-MISSING', 'J-HISTORY', 'K-FUTURE', 'L-WINDOW'] : ['A-NORMAL', 'B-CLOSE', 'C-DATE', 'D-METADATA', 'E-SOURCE', 'F-SUSPEND', 'G-VOLUME', 'H-OHLC', 'I-MISSING', 'J-HISTORY', 'K-FUTURE', 'L-WINDOW']
    for (const symbol of symbols) {
      const data = await api.getStock('TWSE', symbol, '2026-10-04')
      assert.equal(data.instrument.symbol, symbol)
      assert.equal(data.overview.price.latest, null)
      const { prepareStockChartData } = require(path.join(sourceRoot, 'stockChart.ts'))
      const prepared = prepareStockChartData(data.bars, { unlocatedDateRows: data.market_read.unlocated_count })
      if (symbol === 'D-METADATA') assert.equal(prepared.bars.length, 60)
      if (symbol === 'L-WINDOW') {
        assert.equal(prepared.totalRows, 120)
        assert.equal(prepared.invalidDateRows, 1)
        assert.ok(prepared.ma20.every((value) => value === null))
      }
      for (const entry of ['stocks', ...(!followup && ['B-CLOSE', 'C-DATE'].includes(symbol) ? ['actions'] : [])]) {
        const html = render(data, `/${entry}/TWSE/${symbol}?as_of=2026-10-04`)
        assert.ok(html.includes('最近收盤（報價幣別元）</span><strong>待核實</strong>'))
        assert.ok(html.includes('尚無來源與數值已核對的價格。'))
        if (data.market_read.status === 'invalid') assert.ok(html.includes('行情讀值無效，先核對原記錄。'))
        if (data.market_read.status === 'missing') assert.ok(html.includes('尚無行情記錄。'))
        if (data.market_read.status === 'known') assert.ok(!html.includes('行情讀值無效，先核對原記錄。'), 'M1 admission failure is not invalid stored syntax')
        assert.ok(!/Infinity|NaN/.test(html))
        ssr++
      }
    }
    for (const symbol of ['C-DATE', 'L-WINDOW']) {
      const data = await api.getStock('TWSE', symbol)
      assert.equal(data.overview.as_of, null)
      assert.equal(data.decision_summary, null)
    }
    const after = await snapshot()
    assert.deepEqual(after, before, 'whole SQL tables/typeof/note/updated_at changed')
    assert.equal(after.read_mutations, 0)
    console.log(JSON.stringify({ passed: true, node: process.version, actual_http_routes: routes, product_gets: routes - 2, review_digest_gets: 2,
      typescript: ts.version, known_ssr_use_layout_effect_warnings: ssrLayoutWarnings,
      stock_page_full_app_ssr: ssr, whole_sql_sha256: before.whole_sql_sha256, read_mutations: 0,
      scope: followup ? 'remaining four stock cases; two default-cutoff GETs; no replay of accepted cases' : 'twelve stock cases; two action aliases; two default-cutoff GETs',
      disk_artifacts: 0, excluded: 'M1 positive filesystem, browser interaction, production DB, save/reopen' }))
  } finally { global.fetch = guardedFetch; esbuild.stop() }
}

function syntheticAction(symbol, held, quantityStatus, actionState = 'data_insufficient') {
  return { instrument: { id: 1, exchange: 'TWSE', symbol, name: 'Synthetic quantity', instrument_type: 'stock' },
    held, position_quantity_status: quantityStatus, action_state: actionState, as_of: '2026-10-04',
    data_quality: actionState === 'data_insufficient' ? 'partial' : 'complete', current_price: 10.5,
    data_cutoff: '2026-10-04', price_as_of: '2026-10-04', priority: 1, watchlisted: true, event_ids: [1],
    display_instruction: actionState === 'manual_review' ? '庫存股數待核實，先核對原記錄。' : '目前無法產生研究動作。 研究資料尚未完整。',
    primary_levels: {}, missing_data_priority: [], strategies: [], alternative_strategies: [],
    reasons: [], conflicts: [], evidence_refs: [], blocking_reasons: [], theme_ids: [] }
}

function syntheticDashboard(actions) {
  return { as_of: '2026-10-04', mode: 'official_partial', market: { source: 'fixture', instruments: 2, bars: 2, groups: 0 },
    data_quality: { latest_run: 'success' }, news: [], themes: [], groups: [], signals: [], actions, candidates: actions,
    empty_states: {}, action_counts: { total: actions.length, held: 0, held_unknown: actions.length, scope: 'compact_first_page' } }
}

function actionReadCardAssertions(render, action) {
  const before = structuredClone(action)
  const html = render('CompactActionCard', { action })
  assert.ok(html.includes('/actions/' + action.instrument.exchange + '/' + action.instrument.symbol))
  if (action.market_read.status === 'invalid') {
    assert.ok(html.includes('行情讀值無效，先核對原記錄。'))
    assert.ok(html.includes('策略判斷資料待補'))
    assert.ok(html.includes('待核實'))
    assert.ok(html.includes('漲跌待核實'))
    assert.equal(action.current_price, null)
    assert.deepEqual(action.primary_levels, {})
  } else if (action.market_read.status === 'missing') {
    assert.ok(html.includes('尚無行情記錄。'))
  } else {
    assert.ok(!html.includes('行情讀值無效'))
    assert.ok(!html.includes('尚無行情記錄。'))
  }
  assert.deepEqual(action, before)
  return html
}

async function actionReadCheck() {
  typecheck()
  const render = await quantityTrustRenderer()
  let cases = 0
  for (const exchange of ['TWSE', 'TPEx']) {
    for (const status of ['known', 'missing', 'invalid']) {
      const action = { ...syntheticAction('READ-' + status, true, 'known', status === 'known' ? 'hold_observe' : 'data_insufficient'),
        instrument: { ...syntheticAction('READ-' + status).instrument, exchange },
        current_price: status === 'known' ? 10.5 : null,
        market_read: { status, invalid_fields: status === 'invalid' ? ['close'] : [] } }
      actionReadCardAssertions(render, action); cases++
      const detail = render('ActionDetailPanel', { action })
      if (status !== 'known') assert.ok(!detail.includes('class="level-grid'))
    }
  }
  let conflictingCases = 0
  for (const marketRead of [null, {}, { status: 'known' }, { status: 'partial', invalid_fields: [] },
    { status: 'known', invalid_fields: ['close'] }, { status: 'invalid', invalid_fields: [] },
    { status: 'missing', invalid_fields: [] }, { status: 'known', invalid_fields: 'empty' }]) {
    const action = { ...syntheticAction('CONFLICT', true, 'known', 'hold_observe'),
      market_read: marketRead, current_price: 10.5, price_change: 1, price_change_pct: 0.1 }
    const html = render('CompactActionCard', { action })
    assert.ok(html.includes('<strong>待核實</strong>'))
    assert.ok(html.includes('漲跌待核實'))
    assert.ok(!html.includes('10.50'))
    conflictingCases++
  }
  for (const currentPrice of ['10.5', 0, -1, Infinity, null]) {
    const html = render('CompactActionCard', { action: { ...syntheticAction('BADPRICE', true, 'known'),
      current_price: currentPrice, market_read: { status: 'known', invalid_fields: [] }, price_change: 1, price_change_pct: 0.1 } })
    assert.ok(html.includes('<strong>待核實</strong>'))
    assert.ok(html.includes('漲跌待核實'))
    conflictingCases++
  }
  const legacy = render('CompactActionCard', { action: { ...syntheticAction('LEGACY', true, 'known'), price_change: 1, price_change_pct: 0.1 } })
  assert.match(legacy, /<strong>10\.5(?:0)?<\/strong>/)
  assert.ok(!legacy.includes('行情讀值無效'))
  let largeFiniteCases = 0
  const largePrice = (1e308).toLocaleString('zh-TW', { maximumFractionDigits: 2 })
  assert.ok(largePrice.length > 400)
  for (const sign of [1, -1]) {
    const action = { ...syntheticAction('LARGE-FINITE', true, 'known', 'hold_observe'),
      current_price: 1e308, market_read: { status: 'known', invalid_fields: [] },
      price_change: sign * 1e308, price_change_pct: sign * 1e306 }
    const html = actionReadCardAssertions(render, action)
    assert.ok(html.includes('<strong>' + largePrice + '</strong>'))
    assert.ok(html.includes((sign > 0 ? '+' : '-') + largePrice))
    assert.ok(html.includes('（' + (sign > 0 ? '+' : '-') + '1e+308）'))
    assert.ok(!html.includes('漲跌待核實'))
    assert.ok(!html.includes('Infinity'))
    assert.ok(html.includes('style="min-width:0;flex-wrap:wrap"'))
    assert.ok(html.includes('style="min-width:0;flex:1 1 140px;overflow-wrap:anywhere"'))
    assert.ok(html.includes('style="min-width:0;max-width:100%;overflow-wrap:anywhere"'))
    largeFiniteCases++
  }
  const overflowPercent = render('CompactActionCard', { action: {
    ...syntheticAction('LARGE-PERCENT', true, 'known', 'hold_observe'), current_price: 1e308,
    market_read: { status: 'known', invalid_fields: [] }, price_change: 1e308, price_change_pct: 1e308 } })
  assert.ok(overflowPercent.includes('<strong>' + largePrice + '</strong>'))
  assert.ok(overflowPercent.includes('漲跌待核實'))
  assert.ok(!overflowPercent.includes('Infinity'))
  const bundle = await browserBuild()
  assert.ok(bundle.outputFiles.some((file) => file.path.endsWith('.js')))
  console.log(JSON.stringify({ passed: true, node: process.version, typescript: ts.version,
    action_read_card_ssr: cases, action_detail_panel_ssr: cases,
    contradictory_or_partial_metadata_ssr: conflictingCases, legacy_without_metadata_ssr: 1,
    large_finite_price_change_percent_ssr: largeFiniteCases, percentage_display_overflow_ssr: 1,
    known_ssr_use_layout_effect_warnings: ssrLayoutWarnings,
    memory_bundle_js_bytes: bundle.outputFiles.find((file) => file.path.endsWith('.js')).contents.length,
    memory_bundle_css_bytes: bundle.outputFiles.find((file) => file.path.endsWith('.css')).contents.length,
    source: 'component boundary fixtures; actual HTTP checked separately', disk_artifacts: 0 }))
  esbuild.stop()
}

async function actionReadHttpCheck() {
  const api = await apiModule()
  const render = await quantityTrustRenderer()
  const guardedFetch = global.fetch
  let routes = 0, mutations = 0, cards = 0
  global.fetch = (url, options = {}) => {
    routes++
    if (options.method && options.method !== 'GET') mutations++
    return guardedFetch(url, options)
  }
  const snapshot = async () => {
    const response = await fetch(apiOrigin.origin + '/__review__/action-read-snapshot')
    assert.equal(response.status, 200)
    return response.json()
  }
  try {
    const before = await snapshot()
    assert.equal(before.position_count, 24)
    assert.equal(before.read_mutations, 0)
    const items = []
    let cursor
    do {
      const page = await api.getActions({ limit: 5, cursor })
      assert.equal(page.summary.total, 24)
      assert.equal(page.summary.held, 22)
      assert.equal(page.summary.held_unknown, 2)
      assert.equal(page.summary.scope, 'page_for_actionable_and_data_insufficient_counts')
      assert.equal(page.summary.data_insufficient, page.items.filter((row) => row.action_state === 'data_insufficient').length)
      items.push(...page.items); cursor = page.meta.next_cursor || undefined
    } while (cursor)
    assert.equal(items.length, 24)
    assert.equal(new Set(items.map((row) => row.instrument.id)).size, 24)
    for (const action of items) {
      const { decision_summary: detail } = await api.getAction(action.instrument.exchange, action.instrument.symbol)
      for (const key of ['action_state', 'market_read', 'current_price', 'price_as_of', 'price_change', 'held']) {
        assert.deepEqual(detail[key], action[key])
      }
      actionReadCardAssertions(render, action); cards++
      if (action.market_read.status === 'invalid') {
        assert.ok(detail.evidence_refs.some((ref) => ref.startsWith('market_bar:')))
        assert.equal(action.action_state, 'data_insufficient')
        assert.equal(action.price_as_of, null)
        assert.equal(action.price_change, null)
      }
      if (['A-NORMAL', 'D-METADATA', 'G-ADJUST', 'L-FUTURE'].includes(action.instrument.symbol)) {
        assert.equal(action.current_price, action.instrument.symbol === 'L-FUTURE' ? 1e308 : 10.5)
        assert.equal(action.action_state, 'hold_observe')
      }
      if (action.instrument.symbol === 'L-FUTURE') {
        assert.deepEqual(action.market_read, { status: 'known', invalid_fields: [] })
        assert.equal(action.price_as_of, '2026-10-04')
        assert.ok(Number.isFinite(action.price_change) && Number.isFinite(action.price_change_pct))
      }
    }
    for (const [params, total, unknown] of [
      [{ q: 'A-NORMAL', limit: 20 }, 2, 0], [{ state: 'data_insufficient', limit: 20 }, 12, 0],
      [{ state: 'manual_review', limit: 20 }, 4, 2], [{ held_only: true, limit: 30 }, 22, 0],
      [{ watchlist_only: true, limit: 20 }, 2, 0],
    ]) {
      const result = await api.getActions(params)
      assert.equal(result.summary.total, total)
      assert.equal(result.summary.held_unknown, unknown)
      if (params.state) assert.equal(result.summary.scope, 'filtered_results')
    }
    const actions = await api.getActions({ limit: 20 })
    const portfolio = await api.getPortfolio({ page: 1, page_size: 20 })
    const html = render('ActionsPage', {}, [
      [['actions', { search: '', cursor: undefined, state: '' }], actions], [['portfolio-subsection'], portfolio],
    ])
    assert.ok(html.includes('行情讀值無效，先核對原記錄。'))
    assert.ok(html.includes('股數待核實'))
    await api.getDashboard()
    await api.getStocks({ page: 1, page_size: 30 })
    const after = await snapshot()
    assert.deepEqual(after, before, 'GET changed whole tables/all columns/all typeof/note/updated_at')
    assert.equal(mutations, 0)
    console.log(JSON.stringify({ passed: true, node: process.version, actual_http_routes: routes,
      actual_action_card_ssr: cards, actual_actions_page_ssr: 1, http_mutations: mutations,
      whole_sql_sha256: before.whole_sql_sha256, includes: before.includes,
      known_ssr_use_layout_effect_warnings: ssrLayoutWarnings, fixture_date: '2026-10-04',
      source: 'synthetic complete run/strategies; sixty explicit fixture dates; not official sessions',
      excluded: 'polluted StockPage/M1 filesystem gates, production DB, save/reopen', disk_artifacts: 0 }))
  } finally { global.fetch = guardedFetch; esbuild.stop() }
}

function localQuote(close = 10.5, closeStatus = 'known') {
  return { close, close_status: closeStatus,
    recorded: { date: '2026-10-04', source: 'fixture-portfolio-quote-read', data_as_of: null, collected_at: '2026-10-04 00:00:00.000000' },
    record_status: { date: 'known', source: 'known', data_as_of: 'missing', collected_at: 'known' },
    source_verification: 'unverified', date_verification: 'unverified' }
}

function quoteCardAssertions(html, row, values) {
  assert.ok(html.includes('<summary>核對本地行情與試算</summary>'))
  assert.ok(html.includes('本地記錄；來源／日期待核實'))
  assert.ok(html.includes('本地試算，行情來源／日期尚未核實'))
  assert.ok(!/<details[^>]*\bopen(?:\s|=|>)/.test(html))
  assert.ok(html.includes('overflow-wrap:anywhere'))
  const visible = html.replace(/<details class="portfolio-quote-review"[^>]*>[\s\S]*?<\/details>/g, '')
  for (const field of ['market_value', 'unrealized_pnl']) {
    const daily = values.formatPositionValuation(row[field], row.valuation_status, field)
    assert.ok(visible.includes((field === 'market_value' ? '市值' : '未實現損益') + '（報價幣別元） ' + daily))
    if (row.valuation_status?.[field] === 'local_estimate') assert.equal(daily, '行情待核實')
  }
  assert.ok(visible.includes('收盤狀態 ' + values.formatPortfolioClose(row.portfolio_quote)))
  assert.ok(!visible.includes('本地收盤讀值'))
  assert.ok(html.includes('本地收盤讀值（報價幣別元／股） ' + values.formatPortfolioClose(row.portfolio_quote, true)))
}

async function quoteReadCheck() {
  typecheck()
  const values = require(path.join(sourceRoot, 'portfolioValues.ts'))
  const render = await portfolioRenderer()
  const closeCases = [
    [localQuote(12.5), '行情待核實', '12.5'], [localQuote(null, 'missing'), '未提供行情', '未提供行情'],
    [localQuote(null, 'invalid'), '行情數值待核實', '行情數值待核實'],
    ...[0, -1, '12.5', true, Infinity, NaN, null].map((v) => [localQuote(v), '行情待核實', '行情待核實']),
    [localQuote(12.5, 'invalid'), '行情待核實', '行情待核實'],
    [null, '行情待核實', '行情待核實'], [[], '行情待核實', '行情待核實'], [undefined, '行情待核實', '行情待核實'],
    [{ ...localQuote(), source_verification: 'verified' }, '行情待核實', '行情待核實'],
  ]
  let cases = 0
  for (const [metadata, daily, inspection] of closeCases) {
    assert.equal(values.formatPortfolioClose(metadata), daily)
    assert.equal(values.formatPortfolioClose(metadata, true), inspection)
    cases += 2
  }
  for (const field of ['market_value', 'unrealized_pnl']) {
    const positive = field === 'unrealized_pnl' ? '+12.5' : '12.5'
    for (const [value, metadata, daily, inspection] of [
      [12.5, { [field]: 'local_estimate' }, '行情待核實', positive],
      [0, { [field]: 'local_estimate' }, '行情待核實', '0'],
      [null, { [field]: 'local_estimate' }, '待核實', '待核實'],
      ['12.5', { [field]: 'local_estimate' }, '待核實', '待核實'],
      [Infinity, { [field]: 'local_estimate' }, '待核實', '待核實'],
      [12.5, { [field]: 'invalid' }, '待核實', '待核實'],
      [12.5, null, '待核實', '待核實'], [12.5, [], '待核實', '待核實'],
      [12.5, { [field]: 'known' }, positive, '待核實'],
      [12.5, undefined, positive, '待核實'],
      [null, { [field]: 'quantity_unknown' }, '股數待核實', '股數待核實'],
      [null, { [field]: 'precision_unsupported' }, '估值精度待支援', '估值精度待支援'],
      [null, { [field]: 'missing' }, '未提供', '未提供'],
    ]) {
      assert.equal(values.formatPositionValuation(value, metadata, field), daily)
      assert.equal(values.formatLocalPositionValuation(value, metadata, field), inspection)
      cases += 2
    }
  }
  assert.equal(values.formatPositionValuation(-1, { market_value: 'local_estimate' }, 'market_value'), '待核實')
  assert.equal(values.formatLocalPositionValuation(-1, { unrealized_pnl: 'local_estimate' }, 'unrealized_pnl'), '-1')
  assert.equal(values.formatPositionValuation(-1, undefined, 'market_value'), '-1')
  for (const [field, value, status, expected] of [
    ['date', '2026-10-04', 'known', '2026-10-04'], ['date', '2026-02-30', 'known', '記錄待核實'],
    ['date', '0000-01-01', 'known', '記錄待核實'], ['date', 20261004, 'known', '記錄待核實'],
    ['date', null, 'missing', '記錄未提供'], ['date', '2026-10-04', 'invalid', '記錄待核實'],
    ['source', 'twse', 'known', 'twse'], ['source', 'not-an-admitted-source', 'known', 'not-an-admitted-source'],
    ['source', 'twse\x7f', 'known', '記錄待核實'], ['source', 's'.repeat(121), 'known', '記錄待核實'],
    ['source', '\u{1f600}'.repeat(120), 'known', '\u{1f600}'.repeat(120)],
    ['source', '\u{1f600}'.repeat(121), 'known', '記錄待核實'], ['source', '\ud800', 'known', '記錄待核實'],
    ['source', '\ufeff', 'known', '記錄待核實'], ['source', '\u0085', 'known', '記錄待核實'],
    ['data_as_of', '2026-10-04T00:00:00+00:00', 'known', '2026-10-04T00:00:00+00:00'],
    ['collected_at', '2026-10-04 00:00:00.000000', 'known', '2026-10-04 00:00:00.000000'],
    ['collected_at', '2026-02-30 00:00:00', 'known', '記錄待核實'],
    ['data_as_of', '2026-10-04T00:00:00.' + '0'.repeat(46), 'known', '記錄待核實'],
    ['data_as_of', '2026-10-04 25:00:00', 'known', '記錄待核實'],
    ['data_as_of', '2026-10-04T00:00:00+01:99', 'known', '記錄待核實'],
    ['data_as_of', '2026-10-04T00:00:00+0100', 'known', '記錄待核實'],
  ]) {
    const quote = localQuote()
    quote.recorded[field] = value; quote.record_status[field] = status
    assert.equal(values.formatQuoteRecord(quote, field), expected); cases++
  }
  for (const metadata of [null, [], undefined, { ...localQuote(), recorded: [], record_status: null }]) {
    assert.equal(values.formatQuoteRecord(metadata, 'date'), '記錄待核實'); cases++
  }
  const rows = [
    { ...syntheticPosition(1000, '1000'), portfolio_quote: localQuote(), market_value: 10500, unrealized_pnl: 500,
      valuation_status: { market_value: 'local_estimate', unrealized_pnl: 'local_estimate' } },
    ...['missing', 'invalid', 'quantity_unknown', 'precision_unsupported'].map((status) => ({
      ...syntheticPosition(1000, '1000'), portfolio_quote: localQuote(null, status === 'missing' ? 'missing' : 'invalid'),
      valuation_status: { market_value: status, unrealized_pnl: status } })),
    { ...syntheticPosition(0, '0'), portfolio_quote: localQuote(), market_value: 0, unrealized_pnl: 0,
      valuation_status: { market_value: 'local_estimate', unrealized_pnl: 'local_estimate' } },
  ]
  const before = structuredClone(rows)
  for (const row of rows) quoteCardAssertions(render([row]), row, values)
  assert.deepEqual(rows, before)
  // Necessary P4 read semantics remain independent of this inspection panel.
  assert.equal(values.formatPortfolioValue(0, { stop_price: 'known' }, 'stop_price'), '0')
  assert.equal(values.formatPortfolioValue(null, { stop_price: 'invalid' }, 'stop_price'), '待核實')
  const bundle = await browserBuild()
  console.log(JSON.stringify({ passed: true, node: process.version, typescript: ts.version, quote_format_cases: cases + 3,
    actual_portfolio_subsection_ssr_cases: rows.length, row_mutations: 0, p4_status_regression_cases: 2,
    known_ssr_use_layout_effect_warnings: ssrLayoutWarnings, source_date_evidence: 'unverified',
    full_main_memory_bundle: bundle.outputFiles.map((f) => ({ extension: path.extname(f.path), bytes: f.contents.length })),
    disk_artifacts: 0, production_vite_build: 'not_run' }))
  esbuild.stop()
}

async function quoteReadHttpCheck() {
  const api = await apiModule()
  const values = require(path.join(sourceRoot, 'portfolioValues.ts'))
  const render = await portfolioRenderer()
  const snapshot = async () => {
    const response = await fetch(apiOrigin.origin + '/__review__/quote-read-snapshot')
    assert.equal(response.status, 200)
    const data = await response.json()
    assert.equal(data.storage, 'memory_only'); assert.equal(data.position_count, 20)
    assert.ok(data.includes.includes('all typeof()'))
    return data
  }
  const before = await snapshot()
  const data = await api.getPortfolio({ page: 1, page_size: 100 })
  assert.equal(data.items.length, 20)
  for (const row of data.items) {
    const symbol = row.instrument.symbol
    assert.equal(row.portfolio_quote.source_verification, 'unverified')
    assert.equal(row.portfolio_quote.date_verification, 'unverified')
    const expected = { BADPRICE: 'invalid', MISSINGBAR: 'missing', BADQ: 'quantity_unknown',
      HUGEQ: 'precision_unsupported', OVERFLOW: 'invalid' }[symbol] || 'local_estimate'
    assert.deepEqual(row.valuation_status, { market_value: expected, unrealized_pnl: expected })
    if (expected === 'local_estimate') {
      assert.equal(row.market_value, symbol === 'ZEROQ' ? 0 : 10500)
      assert.equal(row.unrealized_pnl, symbol === 'ZEROQ' ? 0 : 500)
    } else { assert.equal(row.market_value, null); assert.equal(row.unrealized_pnl, null) }
    if (symbol === 'DIRTYDATE') assert.equal(row.portfolio_quote.record_status.date, 'invalid')
    if (symbol === 'METABAD') {
      for (const field of ['source', 'data_as_of', 'collected_at']) assert.equal(row.portfolio_quote.record_status[field], 'invalid')
    }
    const clone = structuredClone(row)
    quoteCardAssertions(render([row]), row, values)
    assert.deepEqual(row, clone)
  }
  assert.deepEqual(await snapshot(), before)
  console.log(JSON.stringify({ passed: true, node: process.version, typescript: ts.version,
    actual_http_routes: 3, actual_portfolio_rows: 20, actual_portfolio_subsection_ssr_cases: 20,
    parser: 'actual getPortfolio fetch + Response.json', whole_sql_sha256: before.whole_sql_sha256,
    read_mutations: 0, owned_http_mutations: 0, source_date_evidence: 'unverified',
    known_ssr_use_layout_effect_warnings: ssrLayoutWarnings, disk_artifacts: 0, disk_save_reopen: 'not_tested' }))
  esbuild.stop()
}

async function quantityTrustCheck() {
  typecheck()
  const { formatPositionValuation, formatPortfolioValue } = require(path.join(sourceRoot, 'portfolioValues.ts'))
  const cases = [
    [null, undefined, '未提供'], [0, undefined, '0'], [12.5, undefined, '12.5'], [-12.5, undefined, '-12.5'],
    [Infinity, undefined, '待核實'], [NaN, undefined, '待核實'], ['12.5', undefined, '待核實'],
    [null, 'missing', '未提供'], [0, 'known', '0'], [12.5, 'known', '12.5'], [-12.5, 'known', '-12.5'],
    [null, 'quantity_unknown', '股數待核實'], [null, 'precision_unsupported', '估值精度待支援'],
    [null, 'invalid', '待核實'], [12.5, 'invalid', '待核實'], [12.5, 'quantity_unknown', '待核實'],
    [12.5, 'precision_unsupported', '待核實'], [null, 'known', '待核實'], [0, 'missing', '待核實'],
    [Infinity, 'known', '待核實'], [null, 'unsupported', '待核實'], [12.5, {}, '待核實'],
    [12.5, null, '待核實'], [12.5, [], '待核實'], [false, 'known', '待核實'],
  ]
  const renderPortfolio = await portfolioRenderer()
  let ssrCases = 0
  for (const field of ['market_value', 'unrealized_pnl']) {
    for (const [value, status, expected] of cases) {
      const metadata = typeof status === 'string' ? { [field]: status } : status
      const display = field === 'unrealized_pnl' && value > 0 && expected === '12.5' ? '+12.5' : expected
      assert.equal(formatPositionValuation(value, metadata, field), display)
      const item = { ...syntheticPosition(null, null), [field]: value }
      if (metadata !== undefined) item.valuation_status = metadata
      const before = structuredClone(item)
      const html = renderPortfolio([item])
      assert.ok(html.includes((field === 'market_value' ? '市值' : '未實現損益') + '（報價幣別元） ' + display))
      assert.deepEqual(item, before)
      ssrCases++
    }
  }
  // Keep the P4 field-status boundary without re-running its whole suite.
  assert.equal(formatPortfolioValue(0, { stop_price: 'known' }, 'stop_price'), '0')
  assert.equal(formatPortfolioValue(null, { stop_price: 'invalid' }, 'stop_price'), '待核實')
  const maximum = { ...syntheticPosition(null, '9223372036854775807'), position_quantity_status: 'known',
    valuation_status: { market_value: 'precision_unsupported', unrealized_pnl: 'precision_unsupported' } }
  const maximumHtml = renderPortfolio([maximum])
  assert.ok(maximumHtml.includes('原股數 9,223,372,036,854,775,807 股'))
  assert.ok(maximumHtml.includes('估值精度待支援'))
  const render = await quantityTrustRenderer()
  const unknown = syntheticAction('BADINT', null, 'unknown')
  const zero = syntheticAction('ZERO', false, 'known', 'no_condition')
  const absent = syntheticAction('ABSENT', false, 'absent', 'no_condition')
  const completeUnknown = syntheticAction('COMPLETE', null, 'unknown', 'manual_review')
  const before = structuredClone([unknown, zero, absent, completeUnknown])
  for (const action of [unknown, completeUnknown]) {
    assert.ok(render('CompactActionCard', { action }).includes('股數待核實'))
    const html = render('ActionDetailPanel', { action })
    assert.ok(html.includes('class="pill ambiguous">股數待核實</span>'))
    assert.ok(html.includes('<strong>' + action.display_instruction + '</strong>'))
    if (action.action_state === 'data_insufficient') assert.ok(html.includes('<h2>策略判斷資料待補</h2>'))
    assert.ok(!html.includes('class="level-grid'))
  }
  const actionResult = { items: [unknown, zero, absent, completeUnknown], meta: { limit: 20, total: 4, has_more: false },
    summary: { held: 0, held_unknown: 2, scope: 'page_for_actionable_and_data_insufficient_counts' } }
  const actionHtml = render('ActionsPage', {}, [
    [['actions', { search: '', cursor: undefined, state: '' }], actionResult],
    [['portfolio-subsection'], { items: [] }],
  ])
  assert.ok(actionHtml.includes('本次篩選股數待核實 2 筆'))
  assert.equal((actionHtml.match(/href="\/actions\/TWSE\/BADINT"/g) || []).length, 1)
  assert.ok(actionHtml.includes('股數待核實'))
  const homeHtml = render('TodayPage', {}, [[['dashboard'], syntheticDashboard([unknown])]])
  assert.equal((homeHtml.match(/href="\/actions\/TWSE\/BADINT"/g) || []).length, 1)
  assert.ok(homeHtml.includes('股數待核實'))
  assert.deepEqual([unknown, zero, absent, completeUnknown], before)
  const bundle = await browserBuild()
  console.log(JSON.stringify({ passed: true, typescript: ts.version, node: process.version,
    valuation_format_cases: cases.length * 2, portfolio_ssr_cases: ssrCases + 1,
    compact_action_ssr_cases: 2, actual_stock_action_detail_ssr_cases: 2,
    actual_stock_detail_profiles: ['incomplete_unknown', 'complete_unknown'], actual_actions_page_ssr: 1, actual_home_page_ssr: 1,
    row_mutations: 0, p4_status_regression_cases: 2,
    known_ssr_use_layout_effect_warnings: ssrLayoutWarnings,
    full_main_memory_bundle: bundle.outputFiles.map((file) => ({ extension: path.extname(file.path), bytes: file.contents.length })),
    disk_artifacts: 0, production_vite_build: 'not_run' }))
  esbuild.stop()
}

async function quantityTrustHttpCheck() {
  const api = await apiModule()
  const renderPortfolio = await portfolioRenderer()
  const render = await quantityTrustRenderer()
  const guardedFetch = global.fetch
  let routes = 0
  let mutations = 0
  global.fetch = (url, options = {}) => {
    routes++
    if (options.method && options.method !== 'GET') mutations++
    return guardedFetch(url, options)
  }
  const snapshot = async () => {
    const response = await fetch(apiOrigin.origin + '/__review__/quantity-trust-snapshot')
    assert.equal(response.status, 200)
    return response.json()
  }
  try {
    const before = await snapshot()
    assert.equal(before.row_count, 16)
    const portfolio = await api.getPortfolio({ page: 1, page_size: 20 })
    assert.equal(portfolio.items.length, 16)
    assert.equal(portfolio.pagination.total, 16)
    let decisions = 0
    let stockDetailSsr = 0
    const stockDetailProfiles = { complete_unknown: 0, incomplete_unknown: 0 }
    for (const exchange of ['TWSE', 'TPEx']) {
      for (const [symbol, total, held, state, valuation] of [
        ['INTPOS', '1000', true, 'hold_observe', 'local_estimate'], ['INTZERO', '0', false, 'conditional_entry', 'local_estimate'],
        ['LEGZERO', '0', false, 'conditional_entry', 'local_estimate'], ['BADINT', null, null, 'manual_review', 'quantity_unknown'],
        ['UNSAFE', null, null, 'manual_review', 'quantity_unknown'],
        ['ODD', '9007199254740993', true, 'hold_observe', 'precision_unsupported'],
        ['MAX', '9223372036854775807', true, 'hold_observe', 'precision_unsupported'],
        ['GATEFAIL', null, null, 'data_insufficient', 'quantity_unknown'],
      ]) {
        const row = portfolio.items.find((item) => item.instrument.exchange === exchange && item.instrument.symbol === symbol)
        assert.ok(row)
        assert.equal(row.shares_exact, total)
        assert.equal(row.shares, total === '1000' ? 1000 : total === '0' ? 0 : null)
        assert.equal(row.position_quantity_status, total === null ? 'unknown' : 'known')
        assert.deepEqual(row.valuation_status, { market_value: valuation, unrealized_pnl: valuation })
        if (valuation === 'local_estimate') assert.equal(row.market_value, total === '0' ? 0 : 10500)
        else { assert.equal(row.market_value, null); assert.equal(row.unrealized_pnl, null) }
        const rowBefore = structuredClone(row)
        const html = renderPortfolio([row])
        if (total !== null) assert.ok(html.includes('原股數 ' + total.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + ' 股'))
        if (valuation === 'precision_unsupported') assert.ok(html.includes('估值精度待支援'))
        if (valuation === 'quantity_unknown') assert.ok(html.includes('股數待核實'))
        assert.deepEqual(row, rowBefore)
        const { decision_summary: action } = await api.getAction(exchange, symbol)
        decisions++
        assert.equal(action.held, held)
        assert.equal(action.position_quantity_status, row.position_quantity_status)
        assert.equal(action.action_state, state)
        if (held === null) {
          assert.ok(action.context_badges.includes('股數待核實'))
          assert.deepEqual(action.primary_levels, {})
          if (state === 'manual_review') assert.equal(action.display_instruction, '庫存股數待核實，先核對原記錄。')
          else { assert.equal(action.priority, 1); assert.ok(action.blocking_reasons.length > 0) }
        }
        const stock = await api.getStock(exchange, symbol)
        for (const key of ['held', 'position_quantity_status', 'action_state', 'display_instruction']) {
          assert.equal(stock.decision_summary[key], action[key])
        }
        if (held === null) {
          // StockPage renders this panel, rather than ProductActionCard.
          const detailHtml = render('ActionDetailPanel', { action: stock.decision_summary })
          assert.ok(detailHtml.includes('class="pill ambiguous">股數待核實</span>'))
          assert.ok(detailHtml.includes('<strong>' + stock.decision_summary.display_instruction + '</strong>'))
          assert.ok(!detailHtml.includes('class="level-grid'))
          const incomplete = state === 'data_insufficient'
          if (incomplete) assert.ok(detailHtml.includes('<h2>策略判斷資料待補</h2>'))
          stockDetailSsr++
          stockDetailProfiles[incomplete ? 'incomplete_unknown' : 'complete_unknown']++
        }
      }
      const { decision_summary: absent } = await api.getAction(exchange, 'ABSENT')
      assert.equal(absent.held, false)
      assert.equal(absent.position_quantity_status, 'absent')
    }
    for (const [params, total, held, unknown] of [
      [{ limit: 4 }, 18, 6, 6], [{ held_only: true, limit: 100 }, 6, 6, 0],
      [{ state: 'manual_review', limit: 100 }, 4, 0, 4], [{ state: 'data_insufficient', limit: 100 }, 2, 0, 2],
      [{ state: 'data_insufficient', held_only: true, limit: 100 }, 0, 0, 0],
      [{ q: 'INTZERO', limit: 100 }, 2, 0, 0],
    ]) {
      const result = await api.getActions(params)
      assert.equal(result.meta.total, total)
      assert.equal(result.summary.held, held)
      assert.equal(result.summary.held_unknown, unknown)
    }
    const actions = await api.getActions({ limit: 20 })
    const actionHtml = render('ActionsPage', {}, [
      [['actions', { search: '', cursor: undefined, state: '' }], actions], [['portfolio-subsection'], portfolio],
    ])
    assert.ok(actionHtml.includes('本次篩選股數待核實 6 筆'))
    const dashboard = await api.getDashboard()
    assert.equal(dashboard.action_counts.scope, 'compact_first_page')
    assert.equal(dashboard.action_counts.held, 6)
    assert.equal(dashboard.action_counts.held_unknown, 2)
    const homeHtml = render('TodayPage', {}, [[['dashboard'], dashboard]])
    assert.ok(homeHtml.includes('股數待核實'))
    const after = await snapshot()
    assert.deepEqual(after, before, 'read HTTP changed all SQL columns/note/updated_at/two quantity typeof()')
    assert.equal(mutations, 0)
    console.log(JSON.stringify({ passed: true, actual_http_routes: routes, portfolio_rows: 16, decisions,
      actual_stock_action_detail_ssr: stockDetailSsr, actual_stock_detail_profiles: stockDetailProfiles,
      actual_actions_page_ssr: 1, actual_home_page_ssr: 1,
      known_ssr_use_layout_effect_warnings: ssrLayoutWarnings,
      whole_sql_rows_sha256: before.whole_row_sha256, includes: before.includes, http_mutations: mutations,
      fixture_date: '2026-10-04', source: 'synthetic user quantities; sixty explicit synthetic dates, not official sessions',
      parser: 'actual product fetch + Response.json; actual components SSR', disk_artifacts: 0, disk_save_reopen: 'not_run' }))
  } finally { global.fetch = guardedFetch; esbuild.stop() }
}

function syntheticPosition(shares, exact) {
  return { id: 1, instrument: { id: 1, exchange: 'TWSE', symbol: 'SYNTHETIC', name: 'Synthetic quantity' },
    shares, shares_exact: exact, quantity: null, average_cost: 10, latest_bar: null,
    market_value: null, unrealized_pnl: null, stop_price: null, risk_budget: null, note: null, updated_at: null }
}

async function check() {
  typecheck()
  require(path.join(sourceRoot, 'units.test.ts'))
  const render = await portfolioRenderer()
  const cases = [
    ['0', '0 股（零股）', '0 股'], ['1', '1 股（零股）', '1 股'],
    ['999', '999 股（零股）', '999 股'], ['1000', '1 張', '1,000 股'],
    ['1001', '1 張 1 股', '1,001 股'],
    ['9007199254740991', '9,007,199,254,740 張 991 股', '9,007,199,254,740,991 股'],
    ['9007199254740993', '9,007,199,254,740 張 993 股', '9,007,199,254,740,993 股'],
    ['9223372036854775807', '9,223,372,036,854,775 張 807 股', '9,223,372,036,854,775,807 股'],
  ]
  for (const [exact, mixed, original] of cases) {
    const html = render([syntheticPosition(Number(exact), exact)])
    assert.ok(html.includes('持有 ' + mixed), 'actual portfolio component lost mixed quantity: ' + exact)
    assert.ok(html.includes('原股數 ' + original), 'actual portfolio component lost original quantity: ' + exact)
    assert.ok(html.includes('type="text" inputMode="numeric"'))
    assert.ok(html.includes('1 至 9,223,372,036,854,775,807 股'))
  }
  for (const exact of [null, '1\n', '9223372036854775808', '01']) {
    const html = render([syntheticPosition(1000, exact)])
    assert.ok(html.includes('持有 股數待核實'))
    assert.ok(html.includes('原股數 股數待核實'))
    assert.ok(!html.includes('持有 1 張'))
  }
  const old = syntheticPosition(9007199254740991, undefined)
  delete old.shares_exact
  assert.ok(render([old]).includes('持有 9,007,199,254,740 張 991 股'))
  assert.ok(render([syntheticPosition(Number('9007199254740993'), undefined)]).includes('持有 股數待核實'))
  const bundle = await browserBuild()
  console.log(JSON.stringify({ passed: true, typescript: ts.version, node: process.version, portfolio_ssr_cases: 14,
    full_main_memory_bundle: bundle.outputFiles.map((file) => ({ extension: path.extname(file.path), bytes: file.contents.length })),
    source: 'synthetic canonical fields; int64 formatter cases are not legacy Float restoration',
    disk_artifacts: 0, disk_save_reopen: 'not_run', production_vite_build: 'not_run' }))
  esbuild.stop()
}

async function financeCheck() {
  typecheck()
  const { portfolioValueFromText } = require(path.join(sourceRoot, 'portfolioValues.ts'))
  const accepted = [['', null], ['0', 0], ['00.00', 0], ['12', 12], ['12.5', 12.5],
    ['.5', 0.5], ['12.', 12], ['0012.50', 12.5], ['1' + '0'.repeat(308), 1e308],
    ['0.' + '0'.repeat(323) + '5', Number.MIN_VALUE], ['0.' + '0'.repeat(400), 0]]
  for (const [text, value] of accepted) assert.equal(portfolioValueFromText(text, '平均成本'), value, text)
  const rejected = [' ', '\t', '\n', '1\n', '1\r', ' 1', '1 ', '+1', '-1', '-0', '1e2', '1E2',
    'NaN', 'Infinity', '0x10', '1,000', '$1', '１', '١', '.', '1.2.3', '1' + '0'.repeat(309),
    '0.' + '0'.repeat(324) + '1', '0.\u00a01', '\u200b1']
  for (const text of rejected) assert.throws(() => portfolioValueFromText(text, '停損價'), Error, text)

  const api = await apiModule()
  const guardedFetch = global.fetch
  const bodies = []
  let invalidCalls = 0
  try {
    global.fetch = async (url, options) => {
      assert.equal(new URL(url).origin, apiOrigin.origin)
      bodies.push(JSON.parse(options.body))
      return new Response('{"id":1}', { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    for (const field of ['average_cost', 'stop_price', 'risk_budget']) {
      for (const value of [undefined, null, 0, 12, 12.5, 1e100]) {
        const payload = { symbol: 'NEW', shares: 1, [field]: value }
        const before = structuredClone(payload)
        const count = bodies.length
        await api.upsertPortfolio(payload)
        assert.deepEqual(payload, before, 'helper mutated accepted payload')
        assert.equal(bodies.length, count + 1)
        assert.deepEqual(bodies.at(-1), value === undefined ? { symbol: 'NEW', shares: 1 } : payload)
      }
      for (const value of [true, false, '0', '12.5', 'Infinity', NaN, Infinity, -Infinity, -1, [], {}, { value: Infinity }]) {
        const payload = { symbol: 'NEW', shares: 1, average_cost: 10, stop_price: 9, risk_budget: 100, [field]: value }
        const before = structuredClone(payload)
        const count = bodies.length
        await assert.rejects(async () => api.upsertPortfolio(payload), Error)
        invalidCalls++
        assert.deepEqual(payload, before, 'helper mutated rejected payload')
        assert.equal(bodies.length, count, 'invalid helper value reached fetch')
      }
    }
  } finally { global.fetch = guardedFetch }
  const render = await portfolioRenderer()
  for (const value of [null, 0]) {
    const html = render([{ ...syntheticPosition(1001, '1001'), average_cost: value, stop_price: value }])
    assert.ok(html.includes('aria-label="平均成本／每股" type="text" inputMode="decimal"'))
    assert.ok(html.includes('aria-label="停損價" type="text" inputMode="decimal"'))
    assert.ok(!html.includes('aria-label="風險額度"'))
    assert.ok(html.includes('平均成本（報價幣別元／股） ' + (value === null ? '未提供' : '0')))
  }
  const bundle = await browserBuild()
  console.log(JSON.stringify({ passed: true, typescript: ts.version, node: process.version,
    portfolio_value_parser_accepted: accepted.length, portfolio_value_parser_rejected: rejected.length,
    actual_helper_accepted_fetches: bodies.length, actual_helper_invalid_cases: invalidCalls,
    actual_helper_invalid_fetches: 0, actual_helper_payload_mutations: 0, portfolio_form_ssr_cases: 2,
    full_main_memory_bundle: bundle.outputFiles.map((file) => ({ extension: path.extname(file.path), bytes: file.contents.length })),
    disk_artifacts: 0, disk_save_reopen: 'not_run', production_vite_build: 'not_run' }))
  esbuild.stop()
}

async function financeReadCheck() {
  typecheck()
  const { formatPortfolioValue } = require(path.join(sourceRoot, 'portfolioValues.ts'))
  const status = (value) => ({ average_cost: value, stop_price: value, risk_budget: value })
  const cases = [
    [null, undefined, '未提供'], [0, undefined, '0'], [12.5, undefined, '12.5'],
    [-1, undefined, '待核實'], [Infinity, undefined, '待核實'], [NaN, undefined, '待核實'],
    ['malformed-value', undefined, '待核實'], [false, undefined, '待核實'], [undefined, undefined, '待核實'],
    [0, status('known'), '0'], [12.5, status('known'), '12.5'], [null, status('missing'), '未提供'],
    [null, status('invalid'), '待核實'], [12.5, status('invalid'), '待核實'],
    [null, status('known'), '待核實'], [0, status('missing'), '待核實'],
    [-1, status('known'), '待核實'], [Infinity, status('known'), '待核實'],
    [null, status('unsupported'), '待核實'], [12.5, {}, '待核實'],
    [null, null, '待核實'], [0, [], '待核實'], [12.5, 'known', '待核實'],
  ]
  for (const field of ['average_cost', 'stop_price', 'risk_budget']) {
    for (const [value, metadata, expected] of cases) {
      assert.equal(formatPortfolioValue(value, metadata, field), expected)
    }
  }
  const render = await portfolioRenderer()
  for (const [value, metadata, expected] of cases) {
    const item = { ...syntheticPosition(1000, '1000'), average_cost: value, stop_price: value }
    if (metadata !== undefined) item.portfolio_value_status = metadata
    const before = structuredClone(item)
    const html = render([item])
    assert.ok(html.includes('平均成本（報價幣別元／股） ' + expected))
    assert.ok(html.includes('停損價（報價幣別元／股） ' + expected))
    assert.ok(!html.includes('malformed-value'))
    assert.ok(!html.includes('aria-label="風險額度"'))
    assert.deepEqual(item, before, 'read presentation mutated its row')
  }
  const bundle = await browserBuild()
  console.log(JSON.stringify({ passed: true, typescript: ts.version, node: process.version,
    read_format_cases: cases.length * 3, portfolio_ssr_cases: cases.length, row_mutations: 0,
    explicit_metadata: 'unsupported or inconsistent status is never rescued',
    old_api: 'only absent metadata permits finite nonnegative number/null fallback',
    full_main_memory_bundle: bundle.outputFiles.map((file) => ({ extension: path.extname(file.path), bytes: file.contents.length })),
    disk_artifacts: 0, production_vite_build: 'not_run' }))
  esbuild.stop()
}

async function financeReadHttpCheck() {
  const api = await apiModule()
  const render = await portfolioRenderer()
  const guardedFetch = global.fetch
  let routes = 0
  let mutations = 0
  global.fetch = (url, options = {}) => {
    routes++
    if (options.method && options.method !== 'GET') mutations++
    return guardedFetch(url, options)
  }
  const snapshot = async () => {
    const response = await fetch(apiOrigin.origin + '/__review__/value-read-snapshot')
    assert.equal(response.status, 200)
    return response.json()
  }
  try {
    const before = await snapshot()
    assert.equal(before.row_count, 14)
    const result = await api.getPortfolio({ page: 1, page_size: 20 })
    assert.equal(result.items.length, 14)
    assert.equal(result.pagination.total, 14)
    let rows = 0
    let decisions = 0
    for (const exchange of ['TWSE', 'TPEx']) {
      for (const [symbol, expected, display] of [
        ['MISSING', 'missing', '未提供'], ['ZERO', 'known', '0'], ['NORMAL', 'known', '12.5'],
        ['NEGATIVE', 'invalid', '待核實'], ['INFINITY', 'invalid', '待核實'],
        ['TEXT', 'invalid', '待核實'], ['BLOB', 'invalid', '待核實'],
      ]) {
        const item = result.items.find((row) => row.instrument.exchange === exchange && row.instrument.symbol === symbol)
        assert.ok(item)
        for (const field of ['average_cost', 'stop_price', 'risk_budget']) {
          assert.equal(item.portfolio_value_status[field], expected)
          assert.equal(item[field], expected === 'known' ? (symbol === 'ZERO' ? 0 : 12.5) : null)
        }
        if (expected !== 'known') assert.equal(item.unrealized_pnl, null)
        if (symbol === 'ZERO') assert.equal(item.unrealized_pnl, item.market_value)
        const html = render([item])
        assert.ok(html.includes('平均成本（報價幣別元／股） ' + display))
        assert.ok(html.includes('停損價（報價幣別元／股） ' + display))
        rows++
        const { decision_summary: summary } = await api.getAction(exchange, symbol)
        assert.equal(summary.data_quality, 'complete')
        assert.deepEqual(summary.blocking_reasons, [])
        const expectedState = expected === 'invalid' ? 'manual_review' : symbol === 'NORMAL' ? 'reduce_exit' : 'hold_observe'
        assert.equal(summary.action_state, expectedState)
        assert.equal(summary.stop_price, expected === 'invalid' ? null : symbol === 'MISSING' ? 8 : symbol === 'ZERO' ? 0 : 12.5)
        if (expected === 'invalid') {
          assert.equal(summary.stop_price_semantics.kind, 'unknown')
          assert.equal(summary.stop_price_semantics.origin, 'portfolio_position.stop_price')
          assert.equal(summary.stop_price_semantics.reason, 'invalid_position_stop')
          assert.equal(summary.display_instruction, '庫存停損待核實，先核對原記錄。')
        } else assert.equal(summary.stop_price_semantics.kind, symbol === 'MISSING' ? 'rule_reference' : 'user_position_risk_input')
        decisions++
      }
    }
    const after = await snapshot()
    assert.deepEqual(after, before, 'read HTTP changed full SQL rows/updated_at/typeof')
    assert.equal(mutations, 0)
    console.log(JSON.stringify({ passed: true, actual_http_routes: routes, portfolio_rows: rows, complete_decisions: decisions,
      parser: 'actual getPortfolio/getAction fetch + Response.json; actual PortfolioSubsection SSR',
      whole_sql_rows_sha256: before.whole_row_sha256, includes: before.includes, http_mutations: mutations,
      source: 'fourteen synthetic user-value rows; sixty explicit synthetic fixture dates, not official sessions',
      disk_artifacts: 0, disk_save_reopen: 'not_run' }))
  } finally { global.fetch = guardedFetch; esbuild.stop() }
}

async function financeHttpCheck() {
  const api = await apiModule()
  const guardedFetch = global.fetch
  let routes = 0
  let posts = 0
  let rejectedHelperCases = 0
  let helperInvalidPosts = 0
  global.fetch = (url, options = {}) => {
    routes++
    if (options.method === 'POST') posts++
    return guardedFetch(url, options)
  }
  try {
    for (const exchange of ['TWSE', 'TPEx']) {
      for (const fields of [{ average_cost: 10, stop_price: 20, risk_budget: 100 },
        { average_cost: 0, stop_price: 0, risk_budget: 0 },
        { average_cost: null, stop_price: null, risk_budget: null }, {}]) {
        const payload = { symbol: 'NEW', exchange, shares: '9007199254740993', ...fields }
        const before = structuredClone(payload)
        const saved = await api.upsertPortfolio(payload)
        assert.deepEqual(payload, before)
        for (const field of ['average_cost', 'stop_price', 'risk_budget']) assert.equal(saved[field], fields[field] ?? null)
        assert.equal(saved.shares_exact, '9007199254740993')
        const read = await api.getPortfolio({ q: 'NEW' })
        assert.deepEqual(read.items.find((item) => item.id === saved.id), saved)
      }
      const saved = await api.upsertPortfolio({ symbol: 'NEW', exchange, shares: '9007199254740993',
        average_cost: 10, stop_price: 9, risk_budget: 100, note: 'whole JSON must remain' })
      const baseline = await api.getPortfolio({ page: 1, page_size: 100 })
      for (const field of ['average_cost', 'stop_price', 'risk_budget']) {
        for (const value of [Infinity, NaN, true, '12.5', { value: 1 }, -1]) {
          const payload = { symbol: 'NEW', exchange, shares: '9223372036854775807', note: 'must not replace', [field]: value }
          const before = structuredClone(payload)
          const count = posts
          await assert.rejects(async () => api.upsertPortfolio(payload), Error)
          rejectedHelperCases++
          helperInvalidPosts += posts - count
          assert.equal(posts, count, 'invalid helper value reached HTTP')
          assert.deepEqual(payload, before)
          assert.deepEqual(await api.getPortfolio({ page: 1, page_size: 100 }), baseline)
        }
        for (const token of ['Infinity', 'NaN', '1e999', '[Infinity]', '{"value":NaN}']) {
          const body = '{"symbol":"NEW","exchange":"' + exchange + '","shares":1,"' + field + '":' + token + '}'
          const response = await fetch(apiOrigin.origin + '/api/portfolio', { method: 'POST',
            headers: { 'Content-Type': 'application/json' }, body })
          assert.equal(response.status, 422)
          const error = await response.json()
          assert.ok(error.detail.some((item) => item.loc.at(-1) === field))
          assert.deepEqual(await api.getPortfolio({ page: 1, page_size: 100 }), baseline)
        }
      }
      await api.deletePortfolio(saved.id)
    }
    console.log(JSON.stringify({ passed: true, actual_http_routes: routes, actual_posts: posts,
      actual_helper_rejected_cases: rejectedHelperCases, actual_helper_invalid_posts: helperInvalidPosts,
      actual_helper_payload_mutations: 0, raw_nonfinite_rejection: 'JSON-safe 422; whole portfolio JSON unchanged',
      parser: 'product fetch + Response.json', source: 'synthetic user values; Float-compatible input only',
      disk_artifacts: 0, disk_save_reopen: 'not_run' }))
  } finally { global.fetch = guardedFetch; esbuild.stop() }
}

async function httpCheck() {
  const api = await apiModule()
  const render = await portfolioRenderer()
  let routes = 0
  const initial = await api.getPortfolio({ page: 1, page_size: 100 })
  routes++
  for (const exchange of ['TWSE', 'TPEx']) {
    const safe = initial.items.find((item) => item.instrument.exchange === exchange && item.instrument.symbol === 'SAFE')
    assert.equal(safe.shares_exact, '9007199254740991')
    assert.equal(safe.quantity.display, '9,007,199,254,740 張 991 股')
    assert.ok(render([safe]).includes('原股數 9,007,199,254,740,991 股'))
    for (const symbol of ['ODDFLOAT', 'MAXFLOAT']) {
      const unsafe = initial.items.find((item) => item.instrument.exchange === exchange && item.instrument.symbol === symbol)
      assert.equal(unsafe.shares_exact, null)
      assert.equal(unsafe.quantity, null)
      assert.ok(render([unsafe]).includes('持有 股數待核實'))
    }
    for (const [fields, exact] of [
      [{ shares: 1001 }, '1001'], [{ unit: 'lot', quantity: 2 }, '2000'],
      [{ quantity_lots: 3 }, '3000'], [{ odd_lot_shares: 999 }, '999'],
      [{ unit: 'odd_lot', quantity: 9007199254740991 }, '9007199254740991'],
      [{ shares: '9007199254740993' }, '9007199254740993'],
      [{ unit: 'odd_lot', quantity: '9223372036854775807' }, '9223372036854775807'],
      [{ quantity_lots: '9223372036854775' }, '9223372036854775000'],
      [{ odd_lot_shares: '9223372036854775807' }, '9223372036854775807'],
    ]) {
      const saved = await api.upsertPortfolio({ symbol: 'NEW', exchange, ...fields })
      routes++
      assert.equal(saved.shares_exact, exact)
      assert.equal(typeof saved.shares_exact, 'string')
      assert.equal(saved.quantity.odd_lot_shares, Number(exact.slice(-3)))
      assert.ok(render([saved]).includes('原股數 ' + exact.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + ' 股'))
      const read = await api.getPortfolio({ q: 'NEW' })
      routes++
      assert.equal(read.items.find((item) => item.id === saved.id).shares_exact, exact)
    }
    const before = await api.getPortfolio({ q: 'NEW' })
    routes++
    const original = before.items.find((item) => item.instrument.exchange === exchange)
    for (const fields of [{ shares: 9007199254740992 }, { unit: 'lot', quantity: 9007199254741 },
      { unit: 'odd_lot', quantity: '9223372036854775808' }, { shares: '01' },
      { quantity_lots: '9223372036854776' }, { shares: null }, { shares: true }, { shares: 1.5 }]) {
      const rejected = await fetch(apiOrigin.origin + '/api/portfolio', { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: 'NEW', exchange, ...fields }) })
      routes++
      assert.equal(rejected.status, 422)
      const unchanged = await api.getPortfolio({ q: 'NEW' })
      routes++
      assert.deepEqual(unchanged.items.find((item) => item.id === original.id), original)
    }
    await api.deletePortfolio(original.id)
    routes++
    const remaining = await api.getPortfolio({ q: 'NEW' })
    routes++
    assert.ok(!remaining.items.some((item) => item.id === original.id))
    console.log(JSON.stringify({ exchange, safe_stored_float_exact: safe.shares_exact,
      exact_string_transport: true, rejected_legacy: ['ODDFLOAT', 'MAXFLOAT'] }))
  }
  console.log(JSON.stringify({ passed: true, actual_http_routes: routes, parser: 'product fetch + Response.json',
    source: 'synthetic user quantities through actual owned SQLite HTTP router', disk_save_reopen: 'separate disk runner required', preview_disk_artifacts: 0 }))
  esbuild.stop()
}

async function serve() {
  const pairs = new Map([['http://127.0.0.1:8777', 8778], ['http://127.0.0.1:8779', 8780]])
  const port = Number(option('--port', String(pairs.get(apiOrigin.origin) ?? 8780)))
  if (port !== pairs.get(apiOrigin.origin)) throw new Error('only owned pairs 8777/8778 or 8779/8780 are authorized')
  const build = await browserBuild()
  const script = build.outputFiles.find((file) => file.path.endsWith('.js')).contents
  const css = build.outputFiles.find((file) => file.path.endsWith('.css')).text
    .replace(/@import\s+(?:url\([^)]*\)|["'][^"']*["'])\s*;/g, '')
  const fixtureLabel = args.includes('--stock-read-fixture') ? '隔離合成個股行情讀回・2026-10-04・非正式行情與M1原件驗證' : args.includes('--action-read-fixture') ? '隔離合成行動行情讀回・2026-10-04・非正式持倉／行情與交易日資料' : args.includes('--quote-read-fixture') ? '隔離合成庫存本地行情・2026-10-04・非正式持倉／行情與交易日資料' : args.includes('--quantity-trust-fixture') ? '隔離合成庫存股數・2026-10-04・非正式持倉／行情與交易日資料' : args.includes('--finance-read-fixture') ? '隔離合成庫存讀值・2026-10-04・非正式持倉／行情與交易日資料' : '隔離合成使用者股數・2026-10-03・非正式持倉／行情資料'
  const html = fs.readFileSync(path.join(root, 'frontend/index.html'), 'utf8')
    .replace('<div id="root"></div>', '<p style="padding:8px 16px;color:#f5b85b">' + fixtureLabel + '</p><div id="root"></div>')
    .replace('src="/src/main.tsx"', 'src="/app.js"').replace('</head>', '<link rel="stylesheet" href="/app.css"></head>')
  const server = http.createServer(async (request, response) => {
    response.setHeader('Cache-Control', 'no-store')
    response.setHeader('Content-Security-Policy', "default-src 'self' data:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; font-src 'self' data:")
    if (request.url === '/__review__/shutdown' && request.method === 'POST') {
      response.writeHead(200, { 'Content-Type': 'application/json' })
      response.end(JSON.stringify({ owned_memory_preview: 'stopping' }))
      server.close(() => { esbuild.stop(); process.exit(0) })
      return
    }
    try {
      if (request.url.startsWith('/api/')) {
        if (args.includes('--stock-read-fixture') && !['GET', 'OPTIONS'].includes(request.method)) {
          response.writeHead(405); response.end('stock read preview permits GET/OPTIONS only'); return
        }
        const url = new URL(request.url, apiOrigin)
        if (url.origin !== apiOrigin.origin) throw new Error('invalid upstream destination')
        const chunks = []
        let size = 0
        for await (const chunk of request) {
          size += chunk.length
          if (size > 65536) throw new Error('preview request body limit exceeded')
          chunks.push(chunk)
        }
        const upstream = await fetch(url.href, { method: request.method,
          headers: { 'Content-Type': 'application/json' },
          body: request.method === 'GET' || request.method === 'HEAD' ? undefined : Buffer.concat(chunks) })
        response.writeHead(upstream.status, { 'Content-Type': upstream.headers.get('content-type') || 'application/json' })
        response.end(Buffer.from(await upstream.arrayBuffer()))
      } else if (request.method !== 'GET') {
        response.writeHead(405); response.end('owned preview only')
      } else if (request.url === '/app.js') {
        response.writeHead(200, { 'Content-Type': 'text/javascript; charset=utf-8' }); response.end(script)
      } else if (request.url === '/app.css') {
        response.writeHead(200, { 'Content-Type': 'text/css; charset=utf-8' }); response.end(css)
      } else {
        response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }); response.end(html)
      }
    } catch (error) { response.writeHead(502); response.end(String(error)) }
  })
  server.listen(port, '127.0.0.1', () => console.log(JSON.stringify({ mode: 'memory full App + owned SQLite portfolio router',
    pid: process.pid, url: `http://127.0.0.1:${port}/${args.includes('--stock-read-fixture') ? 'stocks/TWSE/A-NORMAL' : 'actions'}`, api: apiOrigin.origin, fixture_date: args.includes('--finance-read-fixture') || args.includes('--quantity-trust-fixture') || args.includes('--quote-read-fixture') || args.includes('--action-read-fixture') || args.includes('--stock-read-fixture') ? '2026-10-04' : '2026-10-03',
    disk_artifacts: 0, memory_build: { write: false, js_bytes: script.byteLength, css_bytes: Buffer.byteLength(css, 'utf8'), html_bytes: Buffer.byteLength(html, 'utf8') },
    node: process.version, typescript: ts.version, font: 'local fallback; external imports omitted in memory; CSP blocks external requests' })))
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => server.close(() => { esbuild.stop(); process.exit(0) }))
}

Promise.resolve().then(() => args.includes('--serve') ? serve() : args.includes('--stock-read-check') ? stockReadCheck()
  : args.includes('--stock-read-http-check') ? stockReadHttpCheck() : args.includes('--action-read-http-check') ? actionReadHttpCheck()
  : args.includes('--action-read-check') ? actionReadCheck() : args.includes('--finance-read-http-check') ? financeReadHttpCheck()
  : args.includes('--quote-read-http-check') ? quoteReadHttpCheck() : args.includes('--quote-read-check') ? quoteReadCheck()
  : args.includes('--quantity-trust-http-check') ? quantityTrustHttpCheck() : args.includes('--quantity-trust-check') ? quantityTrustCheck()
  : args.includes('--finance-read-check') ? financeReadCheck() : args.includes('--finance-http-check') ? financeHttpCheck()
  : args.includes('--http-check') ? httpCheck() : args.includes('--finance-check') ? financeCheck() : check())
  .catch((error) => { esbuild.stop(); console.error(error); process.exitCode = 1 })
