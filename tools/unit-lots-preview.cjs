/** UNIT-LOTS-1: scoped checks and a full-App presentation preview, entirely in memory.
 * Fixtures and provenance are synthetic; no source/DB/save acceptance is implied.
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
assert(args.every((arg, index) => ['--deps', '--check', '--serve', '--port'].includes(arg) || ['--deps', '--port'].includes(args[index - 1])), 'unknown argument')
assert(!(args.includes('--serve') && args.includes('--check')), 'choose check or serve')
const root = path.resolve(__dirname, '..')
const dependencies = path.resolve(option('--deps', ''))
assert(args.includes('--deps') && fs.existsSync(path.join(dependencies, 'typescript/package.json')), '--deps needs existing frontend/node_modules')
const port = Number(option('--port', '8782'))
assert(Number.isInteger(port) && port >= 1024 && port <= 65535, 'invalid own preview port')
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
for (const owner of [http, https]) for (const name of ['request', 'get']) owner[name] = denyNetwork
net.connect = net.createConnection = tls.connect = denyNetwork
net.Socket.prototype.connect = denyNetwork
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
global.__institutionalWindowSSRSelection = 'unit-lots-only'
const cases = require(path.join(sourceRoot, 'components/StockOverview.test.tsx'))
const units = require(path.join(sourceRoot, 'units.ts'))
const fixture = cases.createUnitLotsFixture()
const instrument = { id: 1, exchange: 'TPEx', symbol: '3105', name: '穩懋', instrument_type: 'stock', currency: 'TWD' }
const chipRow = (id, source, foreign, trust, dealer, margin) => ({ id, instrument_id: 1, date: '2026-10-02', trading_date: '2026-10-02',
  foreign_buy: foreign, trust_buy: trust, dealer_buy: dealer, margin_balance: 2000, margin_change: margin,
  short_balance: null, borrowed_sell: null, day_trade_ratio: null, source, data_as_of: '2026-10-02T08:00:00+00:00', collected_at: '2026-10-05T00:00:00+00:00', raw_payload_id: null })
const chips = [chipRow(1, 'tpex_3insti+tpex_margin', 1, -1250, 0, 1250), chipRow(2, 'unknown', 999, -1, null, 1250)]
const position = (id, exact) => ({ id, instrument: { ...instrument, name: `數量樣本 ${exact ?? 'unknown'}` },
  // Large quantities use only their exact field; no lossy numeric projection is needed.
  shares: exact == null || exact.length > 15 ? null : Number(exact), shares_exact: exact, position_quantity_status: exact == null ? 'unknown' : 'known',
  quantity: exact === '1500' ? { total_shares: 1500, total_shares_exact: '1500', quantity_lots: 1, quantity_lots_exact: '1', odd_lot_shares: 500, unit: 'mixed', display: '1 張 500 股' } : null,
  average_cost: 25.55, stop_price: 20, risk_budget: null, note: 'synthetic presentation fixture', updated_at: null, latest_bar: null,
  market_value: null, unrealized_pnl: null,
})
let positions = ['0', '1', '999', '1500', '9007199254740993', '9223372036854775807', null].map((value, index) => position(index + 1, value))
const stock = { instrument, overview: fixture, bars: [{ ...fixture.price.latest, id: 1, instrument_id: 1, adj_close: 25.55, is_suspended: false }],
  features: {}, chips, groups: [], news: [], events: [], corporate_actions: [], fundamentals: [], data_quality: [], signals: [],
  strategy_conditions: {}, decision_summary: null,
}
const paginatedPositions = () => ({ items: positions, total: positions.length, page: 1, page_size: 20, total_pages: 1 })
const snapshotBytes = () => Buffer.byteLength(JSON.stringify({ stock, positions }))
assert(snapshotBytes() <= 8 * 1024 * 1024, 'fixture memory bound')
const runtime = () => ({ node: process.versions.node, typescript: ts.version, esbuild: esbuild.version })
const receipt = () => ({ runtime: runtime(), guard: counts, disk_artifacts: 0, source_requests: 0, fixture_bytes: snapshotBytes(),
  source_evidence: 'synthetic presentation fixtures; existing daily SSR figures only, no new source verification',
  persistence: 'process memory only; no DB or cross-process save test', owned_pid: process.pid, child_pids: ownedChildren.map((child) => child.pid) })

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

async function check() {
  typecheck()
  const unitCases = require(path.join(sourceRoot, 'units.test.ts'))
  const React = requireDependency('react')
  const { renderToStaticMarkup } = requireDependency('react-dom/server')
  const overviewChecks = cases.runUnitLotsSSRTests(renderToStaticMarkup)
  const currentW8Checks = cases.runInstitutionalWindowEighthCutoffSSRTests(renderToStaticMarkup)
  const { QueryClient, QueryClientProvider } = requireDependency('@tanstack/react-query')
  const { MemoryRouter } = requireDependency('react-router-dom')
  const App = await appSSRModule()
  let appChecks = 0
  const verify = (condition, message) => { appChecks++; assert(condition, message) }
  const { validStockChipRead, stockIndependentView } = require(path.join(sourceRoot, 'stockIndependentReads.ts'))
  verify(validStockChipRead(stock), 'synthetic chips satisfy the full App read gate, including instant metadata')
  const independent = stockIndependentView(stock)
  verify(independent.chips.length === 2 && independent.chipStatus === 'known', 'full App projection keeps both named chip samples')
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
  queryClient.setQueryData(['portfolio-subsection'], paginatedPositions())
  const portfolio = renderToStaticMarkup(React.createElement(QueryClientProvider, { client: queryClient },
    React.createElement(MemoryRouter, null, React.createElement(App.PortfolioSubsection))))
  verify(portfolio.includes('<option value="lot" selected="">') && portfolio.includes('aria-label="張數"'), 'portfolio default input is lots')
  for (const expected of ['0 張', '0.001 張', '0.999 張', '1.5 張', '9,007,199,254,740.993 張', '9,223,372,036,854,775.807 張', '庫存數量待核實']) {
    verify(portfolio.includes('持有 ' + expected), 'portfolio primary lots/unknown: ' + expected)
  }
  verify(portfolio.includes('平均成本（報價幣別元／股）') && portfolio.includes('25.55'), 'price per share does not convert')
  verify(portfolio.includes('<summary>核對庫存原股數、本地行情與試算</summary>') && portfolio.includes('來源稽核原股數 9,007,199,254,740,993 股'), 'original position shares stay in existing details')
  verify(!/position-quantity[^]*?原股數[^]*?<\/div><\/div>/.test(portfolio.split('portfolio-quote-review')[0]), 'first primary position has no raw shares')
  const knownChip = renderToStaticMarkup(React.createElement(App.ChipTable, { rows: [independent.chips[0]] }))
  verify(knownChip.includes('>+0.001</td>') && knownChip.includes('>-1.25</td>') && knownChip.includes('>0</td>') && knownChip.includes('>+1,250</td>'), 'chip flow is lots and margin remains original lots')
  verify(knownChip.includes('外資（股）') && knownChip.includes('融資（張）'), 'raw chip fields have their actual unit')
  const unknownChip = renderToStaticMarkup(React.createElement(App.ChipTable, { rows: [independent.chips[1]] }))
  verify(!unknownChip.split('<details')[0].includes('>0.999</td>') && unknownChip.includes('外資（單位待核實）') && unknownChip.includes('融資（單位待核實）'), 'unknown source cannot claim share or lot units')
  const { formatStockTooltip, prepareStockChartData } = require(path.join(sourceRoot, 'stockChart.ts'))
  const tooltip = formatStockTooltip(prepareStockChartData(stock.bars), { dataIndex: 0 })
  verify(tooltip.includes('成交量（張）') && tooltip.includes('9,007,199,254,740.993') && tooltip.includes('收：25.55'), 'existing chart tooltip retains exact lots and price')
  queryClient.clear()
  verify(Object.values(counts).every((count) => count === 0), 'artifact/network/subprocess guards')
  console.log(JSON.stringify({ passed: true, unit_legacy_suites: 'units.test.ts only', canonical_quantity_checks: unitCases.unitLotsCanonicalChecks,
    affected_overview_ssr_checks: overviewChecks, current_w8_window_ssr_checks: currentW8Checks, app_and_chart_checks: appChecks, ...receipt(),
    not_run: ['backend', 'disk persistence', 'external sources', 'Vite production build', 'browser interaction', 'legacy W1-W7 suites'] }))
}

const requests = { get: 0, post: 0, delete: 0, rejected: 0 }
const savedPayloads = []
function json(response, status, value) { response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' }); response.end(JSON.stringify(value)) }
async function readBody(request) {
  const parts = []; let length = 0
  for await (const part of request) { length += part.length; if (length > 4096) throw new Error('body bound'); parts.push(part) }
  return JSON.parse(Buffer.concat(parts).toString('utf8'))
}
async function fixtureAPI(request, response, url) {
  const pathname = url.pathname
  if (request.method === 'GET') {
    requests.get++
    if (pathname === '/__unit_lots/receipt') return json(response, 200, { ...receipt(), requests, saved_payloads: savedPayloads })
    if (pathname === '/api/portfolio') return json(response, 200, paginatedPositions())
    if (pathname === '/api/actions') return json(response, 200, { items: [], meta: { limit: 20, has_more: false, next_cursor: null }, summary: { total: 0, actionable: 0, data_insufficient: 0, held: 0, held_unknown: 1 } })
    if (pathname === '/api/glossary') return json(response, 200, { items: require(path.join(sourceRoot, 'glossary.ts')).GLOSSARY, meta: { version: 'fixture', total: 0 } })
    if (pathname === '/api/stocks/TPEx/3105' || pathname === '/api/stocks/TPEx/UNITUNKNOWN') {
      const sample = structuredClone(stock)
      if (url.searchParams.get('as_of') && url.searchParams.get('as_of') !== '2026-10-02') {
        sample.overview.institutional.as_of = url.searchParams.get('as_of')
        sample.overview.institutional_daily.status = 'unavailable'; sample.overview.institutional_daily.row = null
      }
      if (pathname.endsWith('/UNITUNKNOWN')) {
        sample.instrument.symbol = 'UNITUNKNOWN'; sample.instrument.name = '來源單位未知樣本'
        sample.overview.institutional.unit = 'mixed'; sample.overview.institutional_daily.unit = 'unknown'
      }
      return json(response, 200, sample)
    }
  }
  if (request.method === 'POST' && pathname === '/api/portfolio') {
    requests.post++
    if (savedPayloads.length >= 4 || positions.length >= 11) return json(response, 409, { detail: 'memory-only preview save bound' })
    try {
      const payload = await readBody(request)
      assert(typeof payload.quantity === 'string', 'canonical quantity input is a string')
      const quantity = units.positionQuantityFromText(payload.unit, payload.quantity)
      const shares = payload.unit === 'lot' ? quantity + '000' : quantity
      assert(units.formatCanonicalShareLots(shares, 1, true) !== null, 'share limit')
      assert(typeof payload.symbol === 'string' && payload.symbol.length <= 16, 'symbol bound')
      const item = position(positions.length + 1, shares)
      item.instrument = { ...instrument, symbol: payload.symbol, name: '新增記憶體庫存樣本' }
      item.average_cost = payload.average_cost ?? null; item.stop_price = payload.stop_price ?? null
      positions.push(item); savedPayloads.push(payload)
      assert(snapshotBytes() <= 8 * 1024 * 1024, 'memory bound')
      return json(response, 200, item)
    } catch (error) { return json(response, 400, { detail: error.message }) }
  }
  if (request.method === 'DELETE' && /^\/api\/portfolio\/[0-9]+$/.test(pathname)) {
    requests.delete++; const id = Number(pathname.split('/').pop()); positions = positions.filter((item) => item.id !== id)
    return json(response, 200, { status: 'deleted_in_memory', id })
  }
  requests.rejected++; return json(response, 404, { detail: 'outside named presentation fixture API' })
}

async function serve() {
  const build = await esbuild.build({ entryPoints: [path.join(sourceRoot, 'main.tsx')], bundle: true, write: false,
    absWorkingDir: path.join(root, 'frontend'), nodePaths: [dependencies], outdir: '__memory_only__',
    platform: 'browser', format: 'esm', target: 'es2020', jsx: 'automatic',
    define: { 'import.meta.env.VITE_API_BASE': JSON.stringify('/api'), 'process.env.NODE_ENV': JSON.stringify('development') } })
  const script = build.outputFiles.find((file) => file.path.endsWith('.js')).contents
  const css = build.outputFiles.find((file) => file.path.endsWith('.css')).text.replace(/@import\s+(?:url\([^)]*\)|["'][^"']*["'])\s*;/g, '')
  const html = fs.readFileSync(path.join(root, 'frontend/index.html'), 'utf8').replace('src="/src/main.tsx"', 'src="/app.js"')
    .replace('</head>', '<link rel="stylesheet" href="/app.css"></head>')
    .replace('<div id="root">', '<div style="padding:8px;background:#573e18;color:#fff">數量顯示驗證樣本：記憶體 fixture，非本次真來源或正式庫存；重新啟動即消失。</div><div id="root">')
  const server = http.createServer(async (request, response) => {
    response.setHeader('Cache-Control', 'no-store')
    response.setHeader('Content-Security-Policy', "default-src 'self' data:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; font-src 'self' data:")
    const url = new URL(request.url, `http://127.0.0.1:${port}`)
    try {
      if (url.pathname.startsWith('/api/') || url.pathname === '/__unit_lots/receipt') return await fixtureAPI(request, response, url)
      if (request.method !== 'GET') { response.writeHead(405); response.end(); return }
      if (url.pathname === '/app.js') { response.writeHead(200, { 'Content-Type': 'text/javascript; charset=utf-8' }); response.end(script) }
      else if (url.pathname === '/app.css') { response.writeHead(200, { 'Content-Type': 'text/css; charset=utf-8' }); response.end(css) }
      else { response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }); response.end(html) }
    } catch (error) { json(response, 500, { detail: error.message }) }
  })
  server.listen(port, '127.0.0.1', () => console.log(JSON.stringify({ mode: 'full App + synthetic memory presentation API',
    port, url: `http://127.0.0.1:${port}/stocks/TPEx/3105?as_of=2026-10-02`, portfolio_url: `http://127.0.0.1:${port}/actions`,
    unknown_unit_url: `http://127.0.0.1:${port}/stocks/TPEx/UNITUNKNOWN?as_of=2026-10-02`,
    ...receipt(), font: 'fallback; remote font import omitted in memory' })))
  let stopping = false
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => {
    if (stopping) return
    stopping = true
    server.close(() => {
      console.log(JSON.stringify({ shutdown: true, signal, requests, saved_payloads: savedPayloads, ...receipt() }))
      esbuild.stop()
    })
    server.closeIdleConnections()
  })
}

Promise.resolve().then(() => args.includes('--serve') ? serve() : check())
  .catch((error) => { console.error(error); process.exitCode = 1; esbuild.stop() })
  .finally(() => { if (!args.includes('--serve')) esbuild.stop() })
