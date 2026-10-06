/** M1-PRICE-1: scoped checks and a full-App actual API preview, entirely in memory.
 * Check fixtures/provenance are synthetic. Serve proxies the root-owned API;
 * actual acquisition/admission provenance comes from that API's receipt.
 * Borrow existing --deps read-only. --check is the default; --serve belongs to root.
 */
const fs = require('node:fs')
const path = require('node:path')
const http = require('node:http')
const https = require('node:https')
const net = require('node:net')
const tls = require('node:tls')
const Module = require('node:module')
const assert = require('node:assert/strict')
const childProcess = require('node:child_process')
const args = process.argv.slice(2)
const option = (name, fallback) => args.includes(name) ? args[args.indexOf(name) + 1] : fallback
assert(args.every((arg, index) => ['--deps', '--check', '--focus-check', '--serve', '--port', '--api-port'].includes(arg) || ['--deps', '--port', '--api-port'].includes(args[index - 1])), 'unknown argument')
assert(!(args.includes('--serve') && args.includes('--check')), 'choose check or serve')
assert(!(args.includes('--focus-check') && (args.includes('--serve') || args.includes('--check'))), 'choose one check mode')
const root = path.resolve(__dirname, '..')
const dependencies = path.resolve(option('--deps', ''))
assert(args.includes('--deps') && fs.existsSync(path.join(dependencies, 'typescript/package.json')), '--deps needs existing frontend/node_modules')
const port = Number(option('--port', '8796'))
assert(Number.isInteger(port) && port >= 1024 && port <= 65535, 'invalid own preview port')
const apiPort = Number(option('--api-port', '8795'))
assert(Number.isInteger(apiPort) && apiPort >= 1024 && apiPort <= 65535 && apiPort !== port, 'invalid owned API port')
const counts = { filesystem_mutations: 0, unapproved_network: 0, unapproved_subprocess: 0 }
const ownedChildren = []
const requireDependency = Module.createRequire(path.join(dependencies, '../package.json'))
const compilerPackage = path.join(dependencies, '.pnpm/node_modules/esbuild')
const compilerBinary = fs.realpathSync(require.resolve(`@esbuild/${process.platform}-${process.arch}/esbuild.exe`, { paths: [compilerPackage] }))
const originalSpawn = childProcess.spawn
childProcess.spawn = function (command, compilerArgs, options) {
  if (fs.realpathSync(command) !== compilerBinary || !Array.isArray(compilerArgs) || !compilerArgs.some((arg) => /^--service=/.test(arg))
    || compilerArgs.some((arg) => !/^--service=/.test(arg) && arg !== '--ping') || ownedChildren.length) {
    counts.unapproved_subprocess++; throw new Error('unapproved subprocess')
  }
  const child = originalSpawn.call(this, command, compilerArgs, options)
  ownedChildren.push(child)
  console.log(JSON.stringify({ esbuild_pid: child.pid, parent_pid: process.pid, binary: compilerBinary }))
  child.once('exit', (code, signal) => console.log(JSON.stringify({ esbuild_exit: true, pid: child.pid, code, signal })))
  return child
}
for (const name of ['exec', 'execSync', 'execFile', 'execFileSync', 'spawnSync', 'fork']) childProcess[name] = () => {
  counts.unapproved_subprocess++; throw new Error('unapproved subprocess')
}
const denied = () => { counts.filesystem_mutations++; throw new Error('filesystem mutation denied') }
for (const name of ['writeFile', 'writeFileSync', 'appendFile', 'appendFileSync', 'mkdir', 'mkdirSync', 'mkdtemp', 'mkdtempSync',
  'rename', 'renameSync', 'unlink', 'unlinkSync', 'rm', 'rmSync', 'rmdir', 'rmdirSync', 'copyFile', 'copyFileSync', 'cp', 'cpSync',
  'truncate', 'truncateSync', 'ftruncate', 'ftruncateSync', 'chmod', 'chmodSync', 'chown', 'chownSync', 'utimes', 'utimesSync',
  'link', 'linkSync', 'symlink', 'symlinkSync', 'createWriteStream', 'write', 'writeSync', 'writev', 'writevSync']) fs[name] = denied
for (const name of ['writeFile', 'appendFile', 'mkdir', 'mkdtemp', 'rename', 'unlink', 'rm', 'rmdir', 'copyFile', 'cp',
  'truncate', 'chmod', 'chown', 'utimes', 'link', 'symlink']) fs.promises[name] = denied
const safeFlags = (flags) => typeof flags === 'string' ? flags === 'r' || flags === 'rs' :
  !(flags & (fs.constants.O_WRONLY | fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_TRUNC | fs.constants.O_APPEND))
for (const name of ['open', 'openSync']) {
  const original = fs[name]
  fs[name] = function (filename, flags, ...rest) { return safeFlags(flags) ? original.call(fs, filename, flags, ...rest) : denied() }
}
const originalPromiseOpen = fs.promises.open
fs.promises.open = async (filename, flags, ...rest) => {
  if (!safeFlags(flags)) return denied()
  const handle = await originalPromiseOpen.call(fs.promises, filename, flags, ...rest)
  for (const name of ['write', 'writev', 'writeFile', 'appendFile', 'truncate', 'chmod', 'chown', 'utimes', 'createWriteStream']) handle[name] = denied
  return handle
}
const denyNetwork = () => { counts.unapproved_network++; throw new Error('outbound network denied') }
global.fetch = denyNetwork
const originalHttpRequest = http.request
const approvedRequest = (options, callback) => {
  if (!args.includes('--serve') || options.hostname !== '127.0.0.1' || options.port !== apiPort
    || !['GET', 'POST'].includes(options.method) || !(options.path.startsWith('/api/') || options.path.startsWith('/__price_validation/'))) return denyNetwork()
  return originalHttpRequest.call(http, options, callback)
}
http.request = approvedRequest
http.get = denyNetwork
https.request = https.get = tls.connect = denyNetwork
const originalSocketConnect = net.Socket.prototype.connect
net.Socket.prototype.connect = function (...connectArgs) {
  let options = connectArgs[0]
  if (Array.isArray(options)) options = options[0]
  if (!args.includes('--serve') || !options || typeof options !== 'object'
    || (options.host || options.hostname) !== '127.0.0.1' || Number(options.port) !== apiPort) return denyNetwork()
  return originalSocketConnect.apply(this, connectArgs)
}
const originalListen = net.Server.prototype.listen
net.Server.prototype.listen = function (listenPort, host, ...rest) {
  if (!args.includes('--serve') || listenPort !== port || host !== '127.0.0.1') return denyNetwork()
  return originalListen.call(this, listenPort, host, ...rest)
}
const ts = requireDependency('typescript')
const esbuild = require(compilerPackage)
const sourceRoot = path.join(root, 'frontend/src')
const dependencySource = path.resolve(dependencies, '../src')
const originalResolve = Module._resolveFilename
Module._resolveFilename = function (request, parent, ...rest) {
  try { return originalResolve.call(this, request, parent, ...rest) } catch (error) {
    if (error.code !== 'MODULE_NOT_FOUND' || request.startsWith('.') || path.isAbsolute(request)) throw error
    return requireDependency.resolve(request)
  }
}
for (const extension of ['.ts', '.tsx']) Module._extensions[extension] = (module, filename) => {
  const result = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true }, fileName: filename,
  })
  module._compile(result.outputText, filename)
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
    console.error(ts.formatDiagnosticsWithColorAndContext(diagnostics.slice(0, 15), { getCanonicalFileName: (f) => f, getCurrentDirectory: () => root, getNewLine: () => '\n' }))
    throw new Error(`TypeScript diagnostics: ${diagnostics.length}`)
  }
  console.log(JSON.stringify({ typecheck: 'current full src noEmit', source_files: parsed.fileNames.length, incremental: false, composite: false }))
}

async function appSSRModule() {
  // The package's CJS entry returns { default: Component }. Normalize only
  // this Node SSR import; the browser bundle keeps its real ECharts component.
  const originalLoad = Module._load
  Module._load = function (request, parent, ...rest) {
    const value = originalLoad.call(this, request, parent, ...rest)
    return request === 'echarts-for-react' && value && typeof value.default === 'function' ? value.default : value
  }
  const result = await esbuild.build({ entryPoints: [path.join(sourceRoot, 'App.tsx')], bundle: true, write: false,
    platform: 'node', format: 'cjs', target: 'es2020', jsx: 'automatic', nodePaths: [dependencies],
    external: ['react', 'react/*', 'react-dom', 'react-dom/*', '@tanstack/react-query', 'react-router-dom', 'echarts', 'echarts-for-react'],
    define: { 'import.meta.env.VITE_API_BASE': JSON.stringify('/api') } })
  const module = new Module(path.join(sourceRoot, '__memory_unit_lots_app__.cjs'))
  module.filename = path.join(sourceRoot, '__memory_unit_lots_app__.cjs')
  module.paths = Module._nodeModulePaths(sourceRoot)
  module._compile(result.outputFiles[0].text, module.filename)
  return module.exports
}


// Check fixtures are synthetic; serving proxies the root-owned actual Python API.
global.__institutionalWindowSSRSelection = 'unit-lots-only'
const cases = require(path.join(sourceRoot, 'components/StockOverview.test.tsx'))
const memoryCases = require(path.join(sourceRoot, 'stockPriceMemoryRead.test.ts'))
const memoryRead = require(path.join(sourceRoot, 'stockPriceMemoryRead.ts'))
const focusCases = require(path.join(sourceRoot, 'priceFocus.test.ts'))
const React = requireDependency('react')
const { renderToStaticMarkup } = requireDependency('react-dom/server')
const runtime = () => ({ node: process.versions.node, typescript: ts.version, esbuild: esbuild.version })
const receipt = () => ({ runtime: runtime(), guard: counts, disk_artifacts: 0, owned_pid: process.pid,
  child_pids: ownedChildren.map((child) => child.pid), fixture_kind: args.includes('--serve')
    ? 'full App proxy of root-owned API; acquisition/admission provenance supplied by API receipt'
    : 'synthetic client contract only; no actual source acquisition' })
const estimateGraph = (value, seen = new Set()) => {
  if (value === null || value === undefined) return 16
  if (typeof value === 'string') return 64 + value.length * 4
  if (typeof value !== 'object') return 16
  if (seen.has(value)) return 0
  seen.add(value)
  return 128 + Object.entries(value).reduce((total, [key, child]) => total + 32 + estimateGraph(key, seen) + estimateGraph(child, seen), 0)
}
function stockFixture(symbol = '3105', cutoff = '2026-10-05') {
  const overview = cases.createUnitLotsFixture()
  overview.as_of = cutoff
  overview.price_memory = memoryCases.createPriceMemoryFixture(symbol, cutoff)
  overview.price = { ...overview.price, status: 'unavailable', latest: null, bars: [], reasons: ['price_raw_evidence_missing'] }
  overview.institutional = { status: 'unavailable', horizons: [5, 20], investors: ['foreign', 'trust', 'dealer'], values: null, reasons: ['window_cutoff_not_supported'] }
  overview.institutional_daily = undefined
  const data = { instrument: memoryCases.priceFixtureInstrument(symbol), overview,
    bars: [{ date: '2026-10-02', open: 10, high: 11, low: 9, close: 10, adj_close: 10, volume: 1000, source: 'synthetic', is_suspended: false }],
    features: {}, chips: [], groups: [], news: [], events: [], corporate_actions: [], fundamentals: [], data_quality: [], signals: [], strategy_conditions: {}, decision_summary: null }
  assert(Buffer.byteLength(JSON.stringify(data)) <= 8 * 1024 * 1024, 'small memory fixture bound')
  return data
}

async function check() {
  let knownSSRWarnings = 0
  const originalError = console.error
  console.error = (...values) => {
    if (typeof values[0] === 'string' && values[0].startsWith('Warning: useLayoutEffect does nothing on the server')) { knownSSRWarnings++; return }
    originalError(...values)
  }
  typecheck()
  if (args.includes('--focus-check')) {
    const helperChecks = focusCases.runPriceFocusTests()
    const { QueryClient, QueryClientProvider } = requireDependency('@tanstack/react-query')
    const { MemoryRouter } = requireDependency('react-router-dom')
    const App = await appSSRModule()
    let appChecks = 0
    const verify = (value, message) => { appChecks++; assert(value, message) }
    for (const [minimum, dayMove, minTurnover] of [['20000', 'all', '0'], ['10000', 'all', '0'], ['50000', 'all', '0'],
      ['10000.000', 'up', '0'], ['10000.000', 'down', '0'], ['10000.000', 'flat', '0'],
      ['10000.000', 'all', '25000000000'], ['10000.000', 'all', '20000000000'], ['10000.000', 'down', '25000000000']]) {
      const data = focusCases.createPriceFocusFixture(minimum, dayMove, minTurnover)
      const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
      client.setQueryData(['price-lot-focus', '2026-10-05', minimum, dayMove, minTurnover, '0'], data)
      const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter,
        { initialEntries: [`/?as_of=2026-10-05&min_lots=${minimum}&day_move=${dayMove}${minTurnover === '0' ? '' : '&min_turnover=' + minTurnover}`] }, React.createElement(App.default))))
      verify(html.includes('成交張數關注') && html.includes('來源日期 2026-10-05'), 'full Today App renders selected source date')
      verify((html.match(/class="focus-card"/g) || []).length === data.count, 'exact expected candidate count')
      verify(data.count !== 0 || (html.includes('零候選') && !html.includes('候選數未知')), 'true zero separate from missing source')
      for (const item of data.items) {
        verify(html.includes(item.symbol === '3105' ? '48,127.911' : '18,982.607') && html.includes(`focus_min_lots=${minimum}&amp;focus_day_move=${dayMove}&amp;focus_min_turnover=${minTurnover}`), 'exact lots and complete fixed-state stock link')
        verify(html.includes(`開盤 ${item.open_exact} 元／股`) && html.includes(`收盤 ${item.close_exact} 元／股`) && html.includes(item.day_move === 'up' ? '收高於開：' : '收低於開：'), 'each stock has exact volume and actual direction reasons including all')
        verify(html.includes(item.symbol === '3105' ? '29,694,939,981' : '22,887,612,060') && html.includes('成交金額'), 'third reason displays exact TWD original amount')
      }
      if (minimum === '10000') verify(html.indexOf('3105 穩懋') < html.indexOf('6488 環球晶') && html.includes('18,982.607'), 'two stocks sorted by code')
      client.clear()
    }
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
    client.setQueryData(['price-lot-focus', '2026-10-05', '50000', 'all', '0', '0'], focusCases.createUnloadedFocusFixture())
    const missing = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter,
      { initialEntries: ['/?as_of=2026-10-05&min_lots=50000'] }, React.createElement(App.default))))
    verify(missing.includes('候選數未知') && !missing.includes('這是此範圍的零候選'), 'unloaded panel never claims available zero')
    client.clear()
    for (const [symbol, dayMove, amount] of [['3105', 'up', '25000000000'], ['6488', 'down', '20000000000'], ['3105', 'all', '0']]) {
      const stock = stockFixture(symbol), queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
      queryClient.setQueryData(['stock', 'TPEx', symbol, '2026-10-05'], stock)
      const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client: queryClient }, React.createElement(MemoryRouter,
        { initialEntries: [`/stocks/TPEx/${symbol}?as_of=2026-10-05&from=price-lots&focus_as_of=2026-10-05&focus_min_lots=10000.000&focus_day_move=${dayMove}${amount === '0' ? '' : '&focus_min_turnover=' + amount}`] }, React.createElement(App.default))))
      verify(html.includes('回到成交張數關注（原條件）') && html.includes(`/?as_of=2026-10-05&amp;min_lots=10000.000&amp;day_move=${dayMove}&amp;min_turnover=${amount}&amp;min_range_pct=0#price-lot-focus-title`), 'full App retains exact original conditions and legacy zero amount')
      verify(html.includes(symbol === '3105' ? '48,127.911' : '18,982.607') && html.includes(symbol === '3105' ? '>615<' : '>1,180<'), 'shared M1 lots and per-share close unchanged')
      queryClient.clear()
    }
    for (const suffix of ['&day_move=unknown', '&day_move=up&day_move=down', '&as_of=2026-10-02', '&min_lots=0',
      '&min_turnover=', '&min_turnover=-1', '&min_turnover=01', '&min_turnover=1.0', '&min_turnover=1&min_turnover=2', '&min_range_pct=', '&min_range_pct=-1', '&min_range_pct=01', '&min_range_pct=1.0001', '&min_range_pct=1&min_range_pct=2', '&next=https://foreign.example']) {
      const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
      const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client: queryClient }, React.createElement(MemoryRouter,
        { initialEntries: ['/?as_of=2026-10-05&min_lots=10000' + suffix] }, React.createElement(App.default))))
      verify(html.includes('尚未查詢候選') && !html.includes('class="focus-card"'), 'invalid/duplicate conditions never render accepted candidates')
      queryClient.clear()
    }
    for (const suffix of ['&focus_day_move=unknown', '&focus_day_move=up&focus_day_move=down', '&next=https://foreign.example',
      '&focus_min_turnover=', '&focus_min_turnover=-1', '&focus_min_turnover=1&focus_min_turnover=2', '&focus_min_range_pct=', '&focus_min_range_pct=-1', '&focus_min_range_pct=1&focus_min_range_pct=2', '&q=3105']) {
      const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
      queryClient.setQueryData(['stock', 'TPEx', '3105', '2026-10-05'], stockFixture())
      const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client: queryClient }, React.createElement(MemoryRouter,
        { initialEntries: ['/stocks/TPEx/3105?as_of=2026-10-05&from=price-lots&focus_as_of=2026-10-05&focus_min_lots=10000.000' + suffix] }, React.createElement(App.default))))
      verify(!html.includes('回到成交張數關注（原條件）') && !html.includes('href="https://foreign.example'), 'unsafe return state falls back to local stock directory')
      queryClient.clear()
    }
    verify(App.officialEventFocusReturnPath(new URLSearchParams('from=official-events&focus_as_of=2026-10-05&focus_q=3105')) === '/?as_of=2026-10-05&q=3105#official-event-focus-title', 'existing event return preserved')
    const staleClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
    staleClient.setQueryData(['price-lot-focus', '2026-10-05', '10000', 'all', '0', '0'], focusCases.createPriceFocusFixture('10000'))
    const stale = renderToStaticMarkup(React.createElement(QueryClientProvider, { client: staleClient }, React.createElement(MemoryRouter,
      { initialEntries: ['/?as_of=2026-10-05&min_lots=10000&day_move=all&min_turnover=25000000000&q=3105'] }, React.createElement(App.default))))
    verify(!stale.includes('class="focus-card"') && stale.includes('value="25000000000"'), 'amount belongs to query key; shared q remains valid')
    staleClient.clear()
    for (const [minimum, move, expected] of [['0', 'all', '3105,6488'], ['4', 'all', '3105,6488'], ['6.000', 'all', '6488'], ['10', 'all', ''], ['6', 'down', ''], ['6', 'up', '6488']]) {
      const data = focusCases.createPriceFocusFixture('10000.000', move, '0', minimum, '2026-10-06')
      const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
      queryClient.setQueryData(['price-lot-focus', '2026-10-06', '10000.000', move, '0', minimum], data)
      const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client: queryClient }, React.createElement(MemoryRouter,
        { initialEntries: [`/?as_of=2026-10-06&min_lots=10000.000&day_move=${move}&min_turnover=0&min_range_pct=${minimum}`] }, React.createElement(App.default))))
      verify(data.items.map((item) => item.symbol).join() === expected && (html.match(/class="focus-card"/g) || []).length === data.count, 'new date independent exact range candidate set ' + minimum + '/' + move)
      verify(html.includes('最小本日振幅（%）') && html.includes('100×(最高−最低)/開盤') && html.includes('來源日期 2026-10-06'), 'range control and formula with selected admitted date')
      verify(data.count !== 0 || (html.includes('零候選') && !html.includes('候選數未知')), 'new range true zero from two admitted reads')
      for (const item of data.items) {
        verify(html.includes(`最高 ${item.high_exact} − 最低 ${item.low_exact}`) && html.includes(`/開盤 ${item.open_exact}`) && html.includes(`門檻 ${minimum}%`), 'fourth reason keeps exact O/H/L and raw threshold')
        verify(html.includes(item.symbol === '3105' ? '約 5.691%' : '約 9.787%') && html.includes(`focus_min_range_pct=${minimum}`), 'display rounded percent and same-cutoff five-condition detail URL')
      }
      queryClient.clear()
    }
    const backClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
    backClient.setQueryData(['stock', 'TPEx', '6488', '2026-10-06'], stockFixture('6488', '2026-10-06'))
    const back = renderToStaticMarkup(React.createElement(QueryClientProvider, { client: backClient }, React.createElement(MemoryRouter,
      { initialEntries: ['/stocks/TPEx/6488?as_of=2026-10-06&from=price-lots&focus_as_of=2026-10-06&focus_min_lots=10000.000&focus_day_move=up&focus_min_turnover=0&focus_min_range_pct=6.000'] }, React.createElement(App.default))))
    verify(back.includes('/?as_of=2026-10-06&amp;min_lots=10000.000&amp;day_move=up&amp;min_turnover=0&amp;min_range_pct=6.000#price-lot-focus-title') && back.includes('13,913.614') && back.includes('>1,205<'), 'new M1 detail and safe return preserve all five conditions and tail zeros')
    backClient.clear()
    for (const query of ['min_range_pct=6', 'min_range_pct=-1', 'min_range_pct=01', 'min_range_pct=1&min_range_pct=2']) {
      const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
      queryClient.setQueryData(['price-lot-focus', '2026-10-06', '10000', 'all', '0', '0'], focusCases.createPriceFocusFixture('10000', 'all', '0', '0', '2026-10-06'))
      const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client: queryClient }, React.createElement(MemoryRouter,
        { initialEntries: ['/?as_of=2026-10-06&min_lots=10000&day_move=all&min_turnover=0&' + query] }, React.createElement(App.default))))
      verify(!html.includes('class="focus-card"'), 'range condition owns cache key and invalid inputs cannot display stale cards')
      queryClient.clear()
    }
    assert(Object.values(counts).every((count) => count === 0), 'guard counts zero')
    const fixtureBytes = { focus: Buffer.byteLength(JSON.stringify(focusCases.createPriceFocusFixture('10000'))), stock: Buffer.byteLength(JSON.stringify(stockFixture())) }
    fixtureBytes.combined = fixtureBytes.focus + fixtureBytes.stock
    assert(fixtureBytes.combined <= 256 * 1024 && fixtureBytes.combined <= 8 * 1024 * 1024, 'bounded synthetic fixture serialization')
    const fixtureObjectEstimate = estimateGraph([focusCases.createPriceFocusFixture('10000'), stockFixture()])
    assert(fixtureObjectEstimate <= 8 * 1024 * 1024, 'conservative fixture object graph estimate, not process RSS')
    console.log(JSON.stringify({ passed: true, focus_helper_checks: helperChecks, focus_app_ssr_checks: appChecks, fixture_bytes: fixtureBytes,
      fixture_object_estimated_bytes: fixtureObjectEstimate,
      known_react_router_ssr_useLayoutEffect_warnings: knownSSRWarnings, ...receipt(), not_run: ['actual source', 'native browser operation', 'disk persistence', 'production build', 'full prior suite'] }))
    return
  }
  const validatorChecks = memoryCases.runStockPriceMemoryReadTests()
  const overviewChecks = cases.runPriceMemoryOverviewSSRTests(renderToStaticMarkup)
  const { QueryClient, QueryClientProvider } = requireDependency('@tanstack/react-query')
  const { MemoryRouter } = requireDependency('react-router-dom')
  const App = await appSSRModule()
  let appChecks = 0
  const verify = (value, message) => { appChecks++; assert(value, message) }
  const { formatStockTooltip, prepareStockChartData } = require(path.join(sourceRoot, 'stockChart.ts'))
  for (const symbol of ['3105', '6488']) {
    const stock = stockFixture(symbol, '2026-10-06')
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
    client.setQueryData(['stock', 'TPEx', symbol, '2026-10-06'], stock)
    const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter,
      { initialEntries: [`/stocks/TPEx/${symbol}?as_of=2026-10-06`] }, React.createElement(App.default))))
    verify(html.includes(symbol === '3105' ? '19,731.7' : '13,913.614') && html.includes(symbol === '3105' ? '>592<' : '>1,205<'), 'new immutable tuple produces same-date M1 exact lots and per-share close')
    verify(html.includes('10/6 官方單日行情') && html.includes('/stocks/TPEx/3105?as_of=2026-10-06') && html.includes('/stocks/TPEx/6488?as_of=2026-10-06'), 'new M1 labels and navigation follow explicit admitted cutoff')
    verify(html.includes('data-date-2026-10-06') && html.includes(memoryRead.priceSourcePins('2026-10-06').bodySha), 'new original-row source card uses exact date/version/body pin')
    const bars = memoryRead.memoryPriceChartBars(stock.overview.price_memory, stock.instrument, '2026-10-06'), chart = prepareStockChartData(bars)
    verify(bars.length === 1 && bars[0].date === '2026-10-06' && bars[0].id === undefined && chart.ma20.every((value) => value === null), 'new date is one unsaved bar without synthetic ID or history')
    const tooltip = formatStockTooltip(chart, { dataIndex: 0 })
    verify(tooltip.includes(symbol === '3105' ? '19,731.7' : '13,913.614') && tooltip.includes(symbol === '3105' ? '收：592' : '收：1,205'), 'new M1 tooltip exact shares-to-lots and close')
    client.clear()
  }
  for (const symbol of ['3105', '6488']) {
    const stock = stockFixture(symbol)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
    client.setQueryData(['stock', 'TPEx', symbol, '2026-10-05'], stock)
    const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client },
      React.createElement(MemoryRouter, { initialEntries: [`/stocks/TPEx/${symbol}?as_of=2026-10-05`] }, React.createElement(App.default))))
    verify(html.includes(symbol === '3105' ? '48,127.911' : '18,982.607'), 'full App headline exact lots')
    verify(html.includes(symbol === '3105' ? '>615<' : '>1,180<'), 'full App headline new single-day close')
    verify(html.includes('10/5 官方單日行情') && !html.includes('最近收盤與漲跌待核實'), 'new market branch independent of missing DB evidence')
    verify(html.includes('/stocks/TPEx/3105?as_of=2026-10-05') && html.includes('/stocks/TPEx/6488?as_of=2026-10-05'), 'same-cutoff navigation')
    const bars = memoryRead.memoryPriceChartBars(stock.overview.price_memory, stock.instrument, '2026-10-05')
    const chart = prepareStockChartData(bars)
    const tooltip = formatStockTooltip(chart, { dataIndex: 0 })
    verify(bars.length === 1 && bars[0].id === undefined && bars[0].date === '2026-10-05', 'chart same-date adapter and no fake ID')
    verify(tooltip.includes(symbol === '3105' ? '48,127.911' : '18,982.607') && tooltip.includes(symbol === '3105' ? '收：615' : '收：1,180'), 'chart exact lots and raw per-share price')
    verify(chart.ma20.every((value) => value === null), 'single day gives no MA20')
    client.clear()
    const conflictClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
    conflictClient.setQueryData(['stock', 'TPEx', symbol, '2026-10-02'], stock)
    const conflict = renderToStaticMarkup(React.createElement(QueryClientProvider, { client: conflictClient },
      React.createElement(MemoryRouter, { initialEntries: [`/stocks/TPEx/${symbol}?as_of=2026-10-02`] }, React.createElement(App.default))))
    verify(!conflict.includes(symbol === '3105' ? '48,127.911' : '18,982.607'), 'full App rejects URL/response cutoff conflict')
    conflictClient.clear()
    const reversedClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
    const reversed = structuredClone(stock)
    reversed.overview.as_of = '2026-10-02'
    reversedClient.setQueryData(['stock', 'TPEx', symbol, '2026-10-05'], reversed)
    const reversedHTML = renderToStaticMarkup(React.createElement(QueryClientProvider, { client: reversedClient },
      React.createElement(MemoryRouter, { initialEntries: [`/stocks/TPEx/${symbol}?as_of=2026-10-05`] }, React.createElement(App.default))))
    verify(!reversedHTML.includes(symbol === '3105' ? '48,127.911' : '18,982.607'), 'full App rejects reverse URL/overview cutoff conflict')
    reversedClient.clear()
  }
  assert(Object.values(counts).every((count) => count === 0), 'guard counts zero')
  const m1Fixtures = [stockFixture('3105'), stockFixture('6488'), stockFixture('3105', '2026-10-06'), stockFixture('6488', '2026-10-06')]
  const fixtureBytes = Buffer.byteLength(JSON.stringify(m1Fixtures)), fixtureObjectEstimate = estimateGraph(m1Fixtures)
  assert(fixtureBytes <= 256 * 1024 && fixtureObjectEstimate <= 8 * 1024 * 1024, 'bounded old/new M1 fixture graphs; estimate is not RSS')
  console.log(JSON.stringify({ passed: true, validator_checks: validatorChecks, affected_overview_ssr_checks: overviewChecks,
    full_app_chart_checks: appChecks, known_react_router_ssr_useLayoutEffect_warnings: knownSSRWarnings, fixture_bytes: fixtureBytes, fixture_object_estimated_bytes: fixtureObjectEstimate,
    ...receipt(), not_run: ['backend rerun', 'external source', 'browser native UI', 'disk persistence', 'full build', 'historical price/MA20'] }))
}

const requests = { api_get: 0, api_post: 0, rejected: 0 }
const json = (response, status, value) => { response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' }); response.end(JSON.stringify(value)) }
async function proxy(request, response) {
  const url = new URL(request.url, `http://127.0.0.1:${port}`)
  const allowed = request.method === 'GET' || (request.method === 'POST' && (/^\/api\/stocks\/TPEx\/(?:3105|6488)\/prices\/capture$/.test(url.pathname) || url.pathname === '/api/focus/price-lots/capture'))
  if (!allowed) { requests.rejected++; return json(response, 405, { detail: 'outside preview operation' }) }
  requests[request.method === 'POST' ? 'api_post' : 'api_get']++
  const upstream = approvedRequest({ hostname: '127.0.0.1', port: apiPort, path: request.url, method: request.method,
    headers: { 'Content-Type': 'application/json' }, agent: false }, (incoming) => {
    response.writeHead(incoming.statusCode, { 'Content-Type': incoming.headers['content-type'] || 'application/json; charset=utf-8' })
    let total = 0
    incoming.on('data', (part) => { total += part.length; if (total > 8 * 1024 * 1024) { incoming.destroy(); response.destroy() } })
    incoming.pipe(response)
  })
  upstream.on('error', (error) => json(response, 502, { detail: error.message }))
  let length = 0
  request.on('data', (part) => { length += part.length; if (length > 4096) { request.destroy(); upstream.destroy() } })
  request.pipe(upstream)
}
async function serve() {
  const build = await esbuild.build({ entryPoints: [path.join(sourceRoot, 'main.tsx')], bundle: true, write: false,
    absWorkingDir: path.join(root, 'frontend'), nodePaths: [dependencies], outdir: '__memory_only__', platform: 'browser', format: 'esm',
    target: 'es2020', jsx: 'automatic', define: { 'import.meta.env.VITE_API_BASE': JSON.stringify('/api'), 'process.env.NODE_ENV': JSON.stringify('development') } })
  const script = build.outputFiles.find((file) => file.path.endsWith('.js')).contents
  const css = build.outputFiles.find((file) => file.path.endsWith('.css')).text.replace(/@import\s+(?:url\([^)]*\)|["'][^"']*["'])\s*;/g, '')
  const html = fs.readFileSync(path.join(root, 'frontend/index.html'), 'utf8').replace('src="/src/main.tsx"', 'src="/app.js"')
    .replace('</head>', '<link rel="stylesheet" href="/app.css"></head>')
    .replace('<div id="root">', '<div style="padding:8px;background:#573e18;color:#fff">受控驗收：目錄及既有資料為合成樣本；官方行情由明示載入取得，來源可在個股詳情核對。</div><div id="root">')
  const server = http.createServer(async (request, response) => {
    response.setHeader('Cache-Control', 'no-store')
    response.setHeader('Content-Security-Policy', "default-src 'self' data:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; font-src 'self' data:")
    const url = new URL(request.url, `http://127.0.0.1:${port}`)
    try {
      if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/__price_validation/')) return await proxy(request, response)
      if (url.pathname === '/__price_ui/receipt') return json(response, 200, { requests, ...receipt() })
      if (request.method !== 'GET') return json(response, 405, { detail: 'read-only UI' })
      if (url.pathname === '/app.js') { response.writeHead(200, { 'Content-Type': 'text/javascript; charset=utf-8' }); response.end(script) }
      else if (url.pathname === '/app.css') { response.writeHead(200, { 'Content-Type': 'text/css; charset=utf-8' }); response.end(css) }
      else { response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }); response.end(html) }
    } catch (error) { json(response, 500, { detail: error.message }) }
  })
  server.listen(port, '127.0.0.1', () => console.log(JSON.stringify({ mode: 'full App + root-owned actual API proxy', port, api_port: apiPort,
    url: `http://127.0.0.1:${port}/stocks/TPEx/3105?as_of=2026-10-02`, ...receipt() })))
  let stopping = false
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => {
    if (stopping) return
    stopping = true
    server.close(() => { console.log(JSON.stringify({ shutdown: true, signal, requests, ...receipt() })); esbuild.stop() })
    server.closeIdleConnections()
  })
}
async function stopCheckCompiler() {
  const waits = ownedChildren.map((child) => new Promise((resolve) => {
    if (child.exitCode !== null || child.signalCode !== null) return resolve({ pid: child.pid, code: child.exitCode, signal: child.signalCode, exited: true })
    child.ref()
    const timeout = setTimeout(() => { child.unref(); resolve({ pid: child.pid, exited: false, reason: 'normal stop exit not observed within 5 seconds' }) }, 5000)
    child.once('exit', (code, signal) => { clearTimeout(timeout); resolve({ pid: child.pid, code, signal, exited: true }) })
  }))
  esbuild.stop()
  console.log(JSON.stringify({ compiler_cleanup: await Promise.all(waits) }))
}
Promise.resolve().then(() => args.includes('--serve') ? serve() : check())
  .catch((error) => { console.error(error); console.log(JSON.stringify({ passed: false, ...receipt() })); process.exitCode = 1; if (args.includes('--serve')) esbuild.stop() })
  .finally(async () => { if (!args.includes('--serve')) await stopCheckCompiler() })
