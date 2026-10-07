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
const crypto = require('node:crypto')
const args = process.argv.slice(2)
const option = (name, fallback) => args.includes(name) ? args[args.indexOf(name) + 1] : fallback
const pinOptions = ['--policy-version', '--policy-digest', '--private-policy-version', '--private-policy-digest', '--saved-focus-policy-version', '--saved-focus-policy-digest', '--chips-policy-version', '--chips-policy-digest', '--joint-policy-version', '--joint-policy-digest']
assert(args.every((arg, index) => ['--deps', '--check', '--focus-check', '--saved-focus-check', '--joint-check', '--private-save-check', '--serve', '--saved-source-only', '--saved-price-chips-opt-in', '--port', '--api-port', ...pinOptions].includes(arg) || ['--deps', '--port', '--api-port', ...pinOptions].includes(args[index - 1])), 'unknown argument')
assert(!(args.includes('--serve') && args.includes('--check')), 'choose check or serve')
assert(!(args.includes('--focus-check') && (args.includes('--serve') || args.includes('--check'))), 'choose one check mode')
assert(!(args.includes('--private-save-check') && (args.includes('--serve') || args.includes('--check') || args.includes('--focus-check'))), 'choose one check mode')
assert(!args.includes('--saved-focus-check') || !['--serve', '--check', '--focus-check', '--private-save-check'].some((flag) => args.includes(flag)), 'choose one check mode')
assert(!args.includes('--saved-source-only') || args.includes('--serve'), 'saved-source-only is an owned serve mode')
const root = path.resolve(__dirname, '..')
const jointActive = args.includes('--saved-price-chips-opt-in')
assert(!jointActive || args.includes('--serve') && args.includes('--saved-source-only'), 'joint opt-in requires saved-only serve')
assert(jointActive || !pinOptions.some((name) => args.includes(name)), 'joint pins require joint opt-in')
let jointPolicy
const jointDigest = 'sha256:a5e6ecda19952e4f6dc44ad9660e4cbbcc2e4a0a3670229ab63900cf74678d14'
if (jointActive || args.includes('--joint-check')) {
  const jointPolicyText = fs.readFileSync(path.join(root, 'backend/app/saved_price_chips_entry.py'), 'utf8').match(/_POLICY = json.loads\(r'''([\s\S]*?)'''\)/)[1]
  jointPolicy = JSON.parse(jointPolicyText)
  assert(Buffer.byteLength(jointPolicyText) === 10702 && 'sha256:' + crypto.createHash('sha256').update(jointPolicyText).digest('hex') === jointDigest, 'canonical joint policy intact')
}
if (jointActive) {
  assert(option('--joint-policy-version') === jointPolicy.version && option('--joint-policy-digest') === jointDigest, 'independent external joint pins required')
  for (const [name, prefix] of [['price_capture', 'policy'], ['price_storage', 'private-policy'], ['saved_focus', 'saved-focus-policy'], ['institutional', 'chips-policy']]) {
    const pin = jointPolicy.independent_pins[name]
    assert(option(`--${prefix}-version`) === pin.policy_version && option(`--${prefix}-digest`) === `sha256:${pin.sha256}`, `external ${name} pins required`)
  }
}
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

async function appSSRModule(joint = false) {
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
    define: { 'import.meta.env.VITE_API_BASE': JSON.stringify('/api'), 'import.meta.env.VITE_SAVED_PRICE_CHIPS_INTEGRATION': JSON.stringify(joint ? 'm1-v1' : '') } })
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
const savedCases = require(path.join(sourceRoot, 'stockPriceSavedRead.test.ts'))
const savedFocusCases = require(path.join(sourceRoot, 'savedPriceFocus.test.ts'))
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
function stockFixture(symbol = '3105', cutoff = '2026-10-05', policyVersion) {
  const overview = cases.createUnitLotsFixture()
  overview.as_of = cutoff
  overview.price_memory = memoryCases.createPriceMemoryFixture(symbol, cutoff, policyVersion)
  overview.price = { ...overview.price, status: 'unavailable', latest: null, bars: [], reasons: ['price_raw_evidence_missing'] }
  overview.institutional = { status: 'unavailable', horizons: [5, 20], investors: ['foreign', 'trust', 'dealer'], values: null, reasons: ['window_cutoff_not_supported'] }
  overview.institutional_daily = undefined
  const data = { instrument: memoryCases.priceFixtureInstrument(symbol), overview,
    bars: [{ date: '2026-10-02', open: 10, high: 11, low: 9, close: 10, adj_close: 10, volume: 1000, source: 'synthetic', is_suspended: false }],
    features: {}, chips: [], groups: [], news: [], events: [], corporate_actions: [], fundamentals: [], data_quality: [], signals: [], strategy_conditions: {}, decision_summary: null }
  const serializedCap = [memoryRead.PRICE_SCOPE_POLICY_VERSION_V3, memoryRead.PRICE_SCOPE_POLICY_VERSION_V4, memoryRead.PRICE_SCOPE_POLICY_VERSION_V5].includes(policyVersion) ? 80 * 1024 : 64 * 1024
  assert(Buffer.byteLength(JSON.stringify(data)) <= serializedCap && estimateGraph(data) <= 512 * 1024, 'tuple-scoped bounded ordinary memory fixture; estimate is not RSS')
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
  if (args.includes('--joint-check')) {
    let gateChecks = 0, stateChecks = 0, appChecks = 0
    const verifyGate = (method, route, body, expected) => {
      const error = jointRequestError(method, new URL(route, 'http://owned.invalid'), Buffer.from(body))
      assert.equal(error?.[0] ?? 200, expected); gateChecks++
    }
    const capture = '/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-06'
    for (const body of ['{}', ' \r\n{ }\t']) verifyGate('POST', capture, body, 200)
    for (const body of ['', 'null', '[]', '1', '{"x":1}', '{bad']) verifyGate('POST', capture, body, 422)
    verifyGate('POST', capture, ' '.repeat(4097), 413)
    for (const suffix of ['&x=1', '&as_of=2026-10-06']) verifyGate('POST', capture + suffix, '{}', 422)
    verifyGate('POST', capture.replace('3105', '6510'), '{}', 405)
    for (const path of ['/api/stocks/TPEx/3105/prices/capture', '/api/stocks/TPEx/3105/prices/save', '/api/focus/price-lots/capture']) verifyGate('POST', path, '{}', 405)
    for (const suffix of ['', '/overview', '/prices/saved-focus']) {
      verifyGate('GET', '/api/stocks/TPEx/3105' + suffix + '?as_of=2026-10-06', '', 200)
      verifyGate('GET', '/api/stocks/TPEx/3105' + suffix + '?as_of=2026-10-06&x=1', '', 422)
      verifyGate('GET', '/api/stocks/TPEx/3105' + suffix + '?as_of=2026-10-05', '', 422)
    }
    verifyGate('GET', '/api/focus/price-saved?as_of=2026-10-05&min_lots=0', '', 200)
    verifyGate('GET', '/api/focus/price-saved?as_of=2026-10-06&min_lots=-1', '', 422)
    verifyGate('GET', '/api/stocks/TPEx/3105/prices/saved?as_of=2026-10-06', '', 405)
    verifyGate('GET', '/api/stocks/TPEx/3105?as_of=2026-10-06', '{}', 422)
    for (const index of ['0', '9', '10', '21']) verifyGate('GET', '/__price_validation/chips/raw?index=' + index, '', 200)
    for (const index of ['', '00', '01', '-1', '22', '1.0']) verifyGate('GET', '/__price_validation/chips/raw?index=' + index, '', 422)
    verifyGate('GET', '/__price_validation/chips/raw?index=0&index=0', '', 422)
    verifyGate('GET', '/__price_validation/receipt?include_raw=true&x=1', '', 422)
    const { Readable } = require('node:stream')
    for (const [method, text, status] of [['POST', ' '.repeat(4097), 413], ['GET', '{}', 422]]) {
      const request = Readable.from([Buffer.from(text)])
      request.method = method
      await assert.rejects(boundedJointBody(request), (error) => error.status === status); gateChecks++
    }
    const App = await appSSRModule(true)
    let state = { token: 'current', epoch: 0, failure: null, price: true, chips: true }
    state = App.jointValidationTransition(state, 'current', 0, 'failure', 'source_failed')
    assert(state.failure && !state.price && !state.chips && state.epoch === 1); stateChecks++
    assert.equal(App.jointValidationTransition(state, 'previous', 1, 'price'), state); stateChecks++
    assert.equal(App.jointValidationTransition(state, 'current', 0, 'price'), state); stateChecks++
    state = App.jointValidationTransition(state, 'current', 1, 'chips')
    assert(state.failure && state.chips && !state.price); stateChecks++
    state = App.jointValidationTransition(state, 'current', 1, 'price')
    assert.equal(state.failure, null); stateChecks++
    const helper = require(path.join(sourceRoot, 'savedPriceFocus.ts'))
    const good = helper.savedFocusDetailPath('3105', '2026-10-06', '10000.000', 'all', '0', '0.000')
    const query = new URL(good, 'http://owned.invalid').searchParams
    assert(App.jointSavedContext('TPEx', '3105', query)); stateChecks++
    for (const variant of [new URLSearchParams(query + '&x=1'), new URLSearchParams(query + '&as_of=2026-10-06'), new URLSearchParams(query.toString().replace('2026-10-06', '2026-10-05'))]) {
      assert(!App.jointSavedContext('TPEx', '3105', variant)); stateChecks++
    }
    const { QueryClient, QueryClientProvider } = requireDependency('@tanstack/react-query')
    const { MemoryRouter } = requireDependency('react-router-dom')
    let maxBytes = 0, maxGraph = 0
    for (const [route, valid] of [[good, true], [good + '&x=1', false], [good + '&as_of=2026-10-06', false]]) {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
      const data = stockFixture('3105', '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V5)
      maxBytes = Math.max(maxBytes, Buffer.byteLength(JSON.stringify(data))); maxGraph = Math.max(maxGraph, estimateGraph(data))
      client.setQueryData(['stock', 'TPEx', '3105', '2026-10-06'], data)
      const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter, { initialEntries: [route] }, React.createElement(App.default))))
      assert(valid ? html.includes('回到已保存行情關注（原條件）') : html.includes('未讀取來源')); appChecks++
      assert(!html.includes('查看官方價格原列、來源版本與 SHA') && !html.includes('既有價格與實際視窗')); appChecks++
      client.clear()
    }
    const baseline = await appSSRModule(false)
    const baselineClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
    baselineClient.setQueryData(['stock', 'TPEx', '3105', '2026-10-06'], stockFixture('3105', '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V5))
    const baselineHTML = renderToStaticMarkup(React.createElement(QueryClientProvider, { client: baselineClient }, React.createElement(MemoryRouter,
      { initialEntries: [good + '&x=1'] }, React.createElement(baseline.default))))
    assert(baselineHTML.includes('目前只採已保存行情') && !baselineHTML.includes('未讀取來源')); appChecks++
    baselineClient.clear()
    assert(maxBytes <= 81920 && maxGraph <= 524288 && Object.values(counts).every((count) => count === 0))
    console.log(JSON.stringify({ passed: true, joint_gate_checks: gateChecks, joint_recovery_checks: stateChecks, joint_app_ssr_checks: appChecks,
      fixture_bytes: maxBytes, fixture_object_estimated_bytes: maxGraph, source_requests: 0, ...receipt(),
      not_run: ['actual source/private bundle', 'native UI', 'disk cases', 'full historical SSR suite', 'production build'] }))
    return
  }
  if (args.includes('--saved-focus-check')) {
    const helperChecks = savedFocusCases.runSavedPriceFocusTests()
    const { QueryClient, QueryClientProvider } = requireDependency('@tanstack/react-query')
    const { MemoryRouter } = requireDependency('react-router-dom')
    const App = await appSSRModule()
    let appChecks = 0
    const verify = (value, message) => { appChecks++; assert(value, message) }
    for (const [lots, move, amount, range, expected] of [['0.000', 'all', '0', '0.000', '3105,3293,5274,5347,6488,6510,8069'],
      ['560.518', 'down', '1729347985', '2.880', '3105,6510'], ['560.519', 'down', '1729347985', '2.880', '3105'],
      ['560.518', 'down', '1729347986', '2.880', '3105'], ['560.518', 'down', '1729347985', '2.881', '3105'], ['0', 'all', '0', '10', '']]) {
      const data = savedFocusCases.createSavedPriceFocusFixture(lots, move, amount, range)
      assert(Buffer.byteLength(JSON.stringify(data)) <= 80 * 1024 && estimateGraph(data) <= 512 * 1024, 'bounded synthetic saved focus')
      const html = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(App.SavedPriceFocusResults, { data })))
      verify(data.items.map((item) => item.symbol).join() === expected && (html.match(/class="focus-card"/g) || []).length === data.count, 'saved-focus exact cards')
      verify(html.includes('已核 7 股') && (expected || html.includes('零候選')), 'full snapshot true zero')
      if (expected.includes('6510')) verify(html.includes('560.518') && html.includes('1,729,347,985') && html.includes('3125.00') && html.includes('3055.00'), 'seventh exact saved reasons')
    }
    const componentChecks = cases.runSavedFocusOverviewSSRTests(renderToStaticMarkup)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
    const initial = '/focus/price-saved?as_of=2026-10-06&min_lots=560.518&day_move=down&min_turnover=1729347985&min_range_pct=2.880'
    const waiting = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter, { initialEntries: [initial] }, React.createElement(App.default))))
    verify(waiting.includes('讀取已保存行情') && waiting.includes('候選數未知') && !waiting.includes('class="focus-card"'), 'no private auto-read on route mount')
    client.setQueryData(['stock', 'TPEx', '6510', '2026-10-06'], stockFixture('6510', '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V5))
    const detail = require(path.join(sourceRoot, 'savedPriceFocus.ts')).savedFocusDetailPath('6510', '2026-10-06', '560.518', 'down', '1729347985', '2.880')
    const detailHTML = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter, { initialEntries: [detail] }, React.createElement(App.default))))
    verify(detailHTML.includes('回到已保存行情關注（原條件）') && detailHTML.includes('目前只採已保存行情') && detailHTML.includes('讀取已保存行情'), 'source mode and exact return')
    verify(!detailHTML.includes('查看官方價格原列、來源版本與 SHA') && !detailHTML.includes('既有價格與實際視窗') && !detailHTML.includes('>3,055<'), 'old memory and DB values excluded before explicit saved read')
    client.clear()
    const fixture = savedFocusCases.createSavedPriceFocusFixture()
    assert(Object.values(counts).every((x) => x === 0), 'saved focus frontend guards')
    console.log(JSON.stringify({ passed: true, saved_focus_helper_checks: helperChecks, saved_focus_app_ssr_checks: appChecks,
      affected_overview_ssr_checks: componentChecks, fixture_bytes: Buffer.byteLength(JSON.stringify(fixture)), fixture_object_estimated_bytes: estimateGraph(fixture),
      max_selected_rows: 7, source_requests: 0, ...receipt(), not_run: ['actual private bundle', 'native browser operation', 'disk cases', 'production build', 'full prior suite'] }))
    return
  }
  if (args.includes('--focus-check')) {
    const helperChecks = focusCases.runPriceFocusTests()
    const { QueryClient, QueryClientProvider } = requireDependency('@tanstack/react-query')
    const { MemoryRouter } = requireDependency('react-router-dom')
    const App = await appSSRModule()
    let appChecks = 0
    const verify = (value, message) => { appChecks++; assert(value, message) }
    for (const [lots, move, amount, range, expected] of [['0.000', 'all', '0', '0.000', '3105,3293,5274,5347,6488,6510,8069'], ['560.518', 'down', '1729347985', '2.880', '3105,6510'], ['560.519', 'down', '1729347985', '2.880', '3105'], ['560.518', 'down', '1729347986', '2.880', '3105'], ['560.518', 'down', '1729347985', '2.881', '3105'], ['0', 'all', '0', '10', '']]) {
      const data = focusCases.createPriceFocusFixture(lots, move, amount, range, '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V5)
      assert(data.reads.length === 7 && Buffer.byteLength(JSON.stringify(data)) <= 80 * 1024 && estimateGraph(data) <= 512 * 1024, 'seven-stock ordinary fixture budget')
      const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
      client.setQueryData(['price-lot-focus', '2026-10-06', lots, move, amount, range], data)
      const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter,
        { initialEntries: [`/?as_of=2026-10-06&min_lots=${lots}&day_move=${move}&min_turnover=${amount}&min_range_pct=${range}`] }, React.createElement(App.default))))
      verify(data.items.map((item) => item.symbol).join() === expected && (html.match(/class="focus-card"/g) || []).length === data.count, 'seven-stock exact focus rendered')
      verify(html.includes('已核 7 股') && (expected !== '' || html.includes('零候選')), 'seven-stock scope and true zero')
      if (expected.includes('6510')) verify(html.includes('6510 精測') && html.includes('560.518') && html.includes('1,729,347,985') && html.includes('收低於開：'), 'seventh exact selected reasons')
      if (data.items.length === 7) verify(html.indexOf('6488 環球晶</strong>') < html.indexOf('6510 精測</strong>') && html.indexOf('6510 精測</strong>') < html.indexOf('8069 元太</strong>'), 'seventh between 6488 and 8069 in admitted code order')
      client.clear()
    }
    const seventhClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
    seventhClient.setQueryData(['stock', 'TPEx', '6510', '2026-10-06'], stockFixture('6510', '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V5))
    const seventhHTML = renderToStaticMarkup(React.createElement(QueryClientProvider, { client: seventhClient }, React.createElement(MemoryRouter,
      { initialEntries: ['/stocks/TPEx/6510?as_of=2026-10-06&from=price-lots&focus_as_of=2026-10-06&focus_min_lots=560.518&focus_day_move=down&focus_min_turnover=1729347985&focus_min_range_pct=2.880'] }, React.createElement(App.default))))
    verify(seventhHTML.includes('560.518') && seventhHTML.includes('>3,055<') && seventhHTML.includes('金融數值僅核 3105、3293、5274、5347、6488、6510、8069') && seventhHTML.includes('資料列序 726'), 'seventh same-cutoff detail and reconstructed raw summary')
    verify(seventhHTML.includes('/?as_of=2026-10-06&amp;min_lots=560.518&amp;day_move=down&amp;min_turnover=1729347985&amp;min_range_pct=2.880#price-lot-focus-title'), 'seventh safe exact five-string return')
    seventhClient.clear()
    for (const [lots, move, amount, range, expected] of [['0.000', 'all', '0', '0.000', '3105,3293,5274,5347,6488,8069'], ['10796.741', 'up', '1607943663', '4.421', '5347,6488,8069'], ['10796.742', 'up', '1607943663', '4.421', '5347,6488'], ['10796.741', 'up', '1607943664', '4.421', '5347,6488'], ['10796.741', 'up', '1607943663', '4.422', '5347,6488'], ['0', 'all', '0', '10', '']]) {
      const data = focusCases.createPriceFocusFixture(lots, move, amount, range, '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V4)
      assert(data.reads.length === 6 && Buffer.byteLength(JSON.stringify(data)) <= 80 * 1024 && estimateGraph(data) <= 512 * 1024, 'six-stock ordinary fixture budget')
      const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
      client.setQueryData(['price-lot-focus', '2026-10-06', lots, move, amount, range], data)
      const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter,
        { initialEntries: [`/?as_of=2026-10-06&min_lots=${lots}&day_move=${move}&min_turnover=${amount}&min_range_pct=${range}`] }, React.createElement(App.default))))
      verify(data.items.map((item) => item.symbol).join() === expected && (html.match(/class="focus-card"/g) || []).length === data.count, 'six-stock exact focus rendered')
      verify(html.includes('已核 6 股') && (expected !== '' || html.includes('零候選')), 'six-stock scope and true zero')
      if (expected.includes('8069')) verify(html.includes('8069 元太') && html.includes('10,796.741') && html.includes('1,607,943,663') && html.includes('收高於開：'), 'sixth exact selected reasons')
      if (data.items.length === 6) verify(html.indexOf('6488 環球晶</strong>') < html.indexOf('8069 元太</strong>'), 'sixth last in admitted code order')
      client.clear()
    }
    const sixthClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
    sixthClient.setQueryData(['stock', 'TPEx', '8069', '2026-10-06'], stockFixture('8069', '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V4))
    const sixthHTML = renderToStaticMarkup(React.createElement(QueryClientProvider, { client: sixthClient }, React.createElement(MemoryRouter,
      { initialEntries: ['/stocks/TPEx/8069?as_of=2026-10-06&from=price-lots&focus_as_of=2026-10-06&focus_min_lots=10796.741&focus_day_move=up&focus_min_turnover=1607943663&focus_min_range_pct=4.421'] }, React.createElement(App.default))))
    verify(sixthHTML.includes('10,796.741') && sixthHTML.includes('>149<') && sixthHTML.includes('金融數值僅核 3105、3293、5274、5347、6488、8069') && sixthHTML.includes('資料列序 12098'), 'sixth same-cutoff detail and reconstructed raw summary')
    verify(sixthHTML.includes('/?as_of=2026-10-06&amp;min_lots=10796.741&amp;day_move=up&amp;min_turnover=1607943663&amp;min_range_pct=4.421#price-lot-focus-title'), 'sixth safe exact five-string return')
    sixthClient.clear()
    for (const [lots, move, amount, range, expected] of [['0.000', 'all', '0', '0.000', '3105,3293,5274,5347,6488'], ['1495.462', 'down', '1164617657', '2.770', '3105,3293'], ['1495.463', 'down', '1164617657', '2.770', '3105'], ['1495.462', 'down', '1164617658', '2.770', '3105'], ['1495.462', 'down', '1164617657', '2.771', '3105'], ['35000', 'all', '0', '0', '']]) {
      const data = focusCases.createPriceFocusFixture(lots, move, amount, range, '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V3)
      assert(data.reads.length === 5 && Buffer.byteLength(JSON.stringify(data)) <= 80 * 1024 && estimateGraph(data) <= 512 * 1024, 'five-stock ordinary fixture budget')
      const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
      client.setQueryData(['price-lot-focus', '2026-10-06', lots, move, amount, range], data)
      const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter,
        { initialEntries: [`/?as_of=2026-10-06&min_lots=${lots}&day_move=${move}&min_turnover=${amount}&min_range_pct=${range}`] }, React.createElement(App.default))))
      verify(data.items.map((item) => item.symbol).join() === expected && (html.match(/class="focus-card"/g) || []).length === data.count, 'five-stock exact focus rendered')
      verify(html.includes('已核 5 股') && (expected !== '' || html.includes('零候選')), 'five-stock scope and true zero')
      if (expected.includes('3293')) verify(html.includes('3293 鈊象') && html.includes('1,495.462') && html.includes('1,164,617,657') && html.includes('收低於開：'), 'fifth exact selected reasons')
      if (data.items.length === 5) verify(html.indexOf('3105 穩懋</strong>') < html.indexOf('3293 鈊象</strong>') && html.indexOf('3293 鈊象</strong>') < html.indexOf('5274 信驊</strong>'), 'fifth code order between 3105 and 5274')
      client.clear()
    }
    const fifthClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
    fifthClient.setQueryData(['stock', 'TPEx', '3293', '2026-10-06'], stockFixture('3293', '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V3))
    const fifthHTML = renderToStaticMarkup(React.createElement(QueryClientProvider, { client: fifthClient }, React.createElement(MemoryRouter,
      { initialEntries: ['/stocks/TPEx/3293?as_of=2026-10-06&from=price-lots&focus_as_of=2026-10-06&focus_min_lots=1495.462&focus_day_move=down&focus_min_turnover=1164617657&focus_min_range_pct=2.770'] }, React.createElement(App.default))))
    verify(fifthHTML.includes('1,495.462') && fifthHTML.includes('>780<') && fifthHTML.includes('金融數值僅核 3105、3293、5274、5347、6488') && fifthHTML.includes('資料列序 255'), 'fifth same-cutoff detail and raw summary')
    verify(fifthHTML.includes('/?as_of=2026-10-06&amp;min_lots=1495.462&amp;day_move=down&amp;min_turnover=1164617657&amp;min_range_pct=2.770#price-lot-focus-title'), 'fifth safe exact five-string return')
    fifthClient.clear()
    for (const [lots, move, amount, range, expected] of [['0.000', 'all', '0', '0.000', '3105,5274,5347,6488'], ['188.693', 'down', '0', '0', '3105,5274'], ['188.694', 'down', '0', '0', '3105'], ['0.000', 'down', '3627465565', '5.327', '3105,5274'], ['0.000', 'down', '3627465566', '5.328', '3105'], ['35000', 'all', '0', '0', '']]) {
      const data = focusCases.createPriceFocusFixture(lots, move, amount, range, '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V2)
      assert(Buffer.byteLength(JSON.stringify(data)) <= 64 * 1024 && estimateGraph(data) <= 512 * 1024, 'four-stock focus fixture budget')
      const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
      client.setQueryData(['price-lot-focus', '2026-10-06', lots, move, amount, range], data)
      const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter,
        { initialEntries: [`/?as_of=2026-10-06&min_lots=${lots}&day_move=${move}&min_turnover=${amount}&min_range_pct=${range}`] }, React.createElement(App.default))))
      verify(data.items.map((item) => item.symbol).join() === expected && (html.match(/class="focus-card"/g) || []).length === data.count, 'four-stock exact focus rendered')
      verify(html.includes('已核 4 股') && (expected !== '' || html.includes('零候選')), 'four-stock scope and true zero')
      if (expected.includes('5274')) verify(html.includes('5274 信驊') && html.includes('188.693') && html.includes('3,627,465,565') && html.includes('收低於開：'), 'fourth exact reasons and financial fields')
      if (expected.split(',').length === 4) verify(html.indexOf('3105 穩懋</strong>') < html.indexOf('5274 信驊</strong>') && html.indexOf('5274 信驊</strong>') < html.indexOf('5347 世界</strong>') && html.indexOf('5347 世界</strong>') < html.indexOf('6488 環球晶</strong>'), 'four admitted ordinary stocks code order')
      client.clear()
    }
    const fourthClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
    fourthClient.setQueryData(['stock', 'TPEx', '5274', '2026-10-06'], stockFixture('5274', '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V2))
    const fourthHTML = renderToStaticMarkup(React.createElement(QueryClientProvider, { client: fourthClient }, React.createElement(MemoryRouter,
      { initialEntries: ['/stocks/TPEx/5274?as_of=2026-10-06&from=price-lots&focus_as_of=2026-10-06&focus_min_lots=0.000&focus_day_move=down&focus_min_turnover=3627465565&focus_min_range_pct=5.327'] }, React.createElement(App.default))))
    verify(fourthHTML.includes('188.693') && fourthHTML.includes('>18,985<') && fourthHTML.includes('金融數值僅核 3105、5274、5347、6488'), 'fourth full App same-cutoff quote and raw scope')
    verify(fourthHTML.includes('/?as_of=2026-10-06&amp;min_lots=0.000&amp;day_move=down&amp;min_turnover=3627465565&amp;min_range_pct=5.327#price-lot-focus-title'), 'fourth safe five original strings return')
    fourthClient.clear()
    for (const [lots, move, amount, range, expected] of [['0', 'all', '0', '0', '3105,5347,6488'], ['20000.000', 'up', '0', '5.691', '5347'], ['20000.000', 'up', '0', '5.692', '']]) {
      const data = focusCases.createPriceFocusFixture(lots, move, amount, range, '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION)
      const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
      client.setQueryData(['price-lot-focus', '2026-10-06', lots, move, amount, range], data)
      const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter,
        { initialEntries: [`/?as_of=2026-10-06&min_lots=${lots}&day_move=${move}&min_turnover=${amount}&min_range_pct=${range}`] }, React.createElement(App.default))))
      verify(data.items.map((item) => item.symbol).join() === expected && (html.match(/class="focus-card"/g) || []).length === data.count, 'three-stock focus native contract rendered')
      verify(html.includes('已核 3 股') && (expected !== '' || html.includes('零候選')), 'complete three-stock true zero remains distinct')
      if (expected.includes('5347')) verify(html.includes('5347 世界') && html.includes('34,637.793') && html.includes('6,615,109,776'), 'third exact lots and TWD original amount displayed')
      if (expected.includes(',')) verify(html.indexOf('3105 穩懋</strong>') < html.indexOf('5347 世界</strong>') && html.indexOf('5347 世界</strong>') < html.indexOf('6488 環球晶</strong>'), 'three admitted stocks code order')
      client.clear()
    }
    const thirdClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
    thirdClient.setQueryData(['stock', 'TPEx', '5347', '2026-10-06'], stockFixture('5347', '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION))
    const thirdHTML = renderToStaticMarkup(React.createElement(QueryClientProvider, { client: thirdClient }, React.createElement(MemoryRouter,
      { initialEntries: ['/stocks/TPEx/5347?as_of=2026-10-06&from=price-lots&focus_as_of=2026-10-06&focus_min_lots=20000.000&focus_day_move=up&focus_min_turnover=0&focus_min_range_pct=5.691'] }, React.createElement(App.default))))
    verify(thirdHTML.includes('5347 世界') && thirdHTML.includes('34,637.793') && thirdHTML.includes('>191<'), 'third full stock page same-cutoff per-share quote')
    verify(thirdHTML.includes('/?as_of=2026-10-06&amp;min_lots=20000.000&amp;day_move=up&amp;min_turnover=0&amp;min_range_pct=5.691#price-lot-focus-title'), 'third safe all-five return URL')
    thirdClient.clear()
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
    const fixtureBytes = { focus: Buffer.byteLength(JSON.stringify(focusCases.createPriceFocusFixture('0', 'all', '0', '0', '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V2))), stock: Buffer.byteLength(JSON.stringify(stockFixture('5274', '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V2))) }
    fixtureBytes.combined = fixtureBytes.focus + fixtureBytes.stock
    assert(fixtureBytes.combined <= 64 * 1024, 'bounded synthetic fixture serialization')
    const fixtureObjectEstimate = estimateGraph([focusCases.createPriceFocusFixture('0', 'all', '0', '0', '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V2), stockFixture('5274', '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V2)])
    assert(fixtureObjectEstimate <= 512 * 1024, 'conservative fixture object graph estimate, not process RSS')
    const fifthFixtures = [focusCases.createPriceFocusFixture('0', 'all', '0', '0', '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V3), stockFixture('3293', '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V3)]
    const fifthFixtureBytes = Buffer.byteLength(JSON.stringify(fifthFixtures)), fifthObjectEstimate = estimateGraph(fifthFixtures)
    assert(fifthFixtures[0].reads.length === 5 && fifthFixtureBytes <= 80 * 1024 && fifthObjectEstimate <= 512 * 1024, 'new five-stock combined bounded fixtures; old bounds retained')
    const sixthFixtures = [focusCases.createPriceFocusFixture('0', 'all', '0', '0', '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V4), stockFixture('8069', '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V4)]
    const sixthFixtureBytes = Buffer.byteLength(JSON.stringify(sixthFixtures)), sixthObjectEstimate = estimateGraph(sixthFixtures)
    assert(sixthFixtures[0].reads.length === 6 && sixthFixtureBytes <= 80 * 1024 && sixthObjectEstimate <= 512 * 1024, 'six-stock combined bounded fixtures; old bounds retained')
    const seventhFixtures = [focusCases.createPriceFocusFixture('0', 'all', '0', '0', '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V5), stockFixture('6510', '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V5)]
    const seventhFixtureBytes = Buffer.byteLength(JSON.stringify(seventhFixtures)), seventhObjectEstimate = estimateGraph(seventhFixtures)
    assert(seventhFixtures[0].reads.length === 7 && seventhFixtureBytes <= 80 * 1024 && seventhObjectEstimate <= 512 * 1024, 'seven-stock combined bounded fixtures; old bounds retained')
    console.log(JSON.stringify({ passed: true, focus_helper_checks: helperChecks, focus_app_ssr_checks: appChecks, fixture_bytes: fixtureBytes,
      fixture_object_estimated_bytes: fixtureObjectEstimate, fifth_fixture_bytes: fifthFixtureBytes, fifth_object_estimated_bytes: fifthObjectEstimate,
      sixth_fixture_bytes: sixthFixtureBytes, sixth_object_estimated_bytes: sixthObjectEstimate, seventh_fixture_bytes: seventhFixtureBytes, seventh_object_estimated_bytes: seventhObjectEstimate, max_selected_rows: 7,
      known_react_router_ssr_useLayoutEffect_warnings: knownSSRWarnings, ...receipt(), not_run: ['actual source', 'native browser operation', 'disk persistence', 'production build', 'full prior suite'] }))
    return
  }
  if (args.includes('--private-save-check')) {
    const savedValidatorChecks = savedCases.runStockPriceSavedReadTests()
    const savedSSRChecks = cases.runPriceSavedOverviewSSRTests(renderToStaticMarkup)
    const fixtures = savedCases.createPriceSavedFixture()
    const bytes = Buffer.byteLength(JSON.stringify(fixtures)), estimate = estimateGraph(fixtures)
    assert(bytes <= 80 * 1024 && estimate <= 512 * 1024, 'bounded saved synthetic frontend fixture')
    assert(Object.values(counts).every((x) => x === 0), 'private frontend guards')
    console.log(JSON.stringify({ passed: true, saved_validator_checks: savedValidatorChecks, saved_ssr_checks: savedSSRChecks,
      fixture_bytes: bytes, fixture_object_estimated_bytes: estimate, source_requests: 0, ...receipt() }))
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
  const fourthStock = stockFixture('5274', '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V2)
  const fourthClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
  fourthClient.setQueryData(['stock', 'TPEx', '5274', '2026-10-06'], fourthStock)
  const fourthHTML = renderToStaticMarkup(React.createElement(QueryClientProvider, { client: fourthClient }, React.createElement(MemoryRouter,
    { initialEntries: ['/stocks/TPEx/5274?as_of=2026-10-06'] }, React.createElement(App.default))))
  verify(fourthHTML.includes('188.693') && fourthHTML.includes('>18,985<') && fourthHTML.includes('金融數值僅核 3105、5274、5347、6488'), 'fourth full App ordinary quote and finite scope')
  const fourthChart = prepareStockChartData(memoryRead.memoryPriceChartBars(fourthStock.overview.price_memory, fourthStock.instrument, '2026-10-06'))
  verify(fourthChart.ma20.every((value) => value === null) && formatStockTooltip(fourthChart, { dataIndex: 0 }).includes('188.693'), 'fourth exact chart lots without invented history')
  fourthClient.clear()
  const thirdStock = stockFixture('5347', '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION)
  const thirdClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
  thirdClient.setQueryData(['stock', 'TPEx', '5347', '2026-10-06'], thirdStock)
  const thirdHTML = renderToStaticMarkup(React.createElement(QueryClientProvider, { client: thirdClient }, React.createElement(MemoryRouter,
    { initialEntries: ['/stocks/TPEx/5347?as_of=2026-10-06'] }, React.createElement(App.default))))
  verify(thirdHTML.includes('34,637.793') && thirdHTML.includes('>191<') && thirdHTML.includes('金融數值僅核 3105、5347、6488'), 'third full App ordinary quote and scope')
  const thirdBars = memoryRead.memoryPriceChartBars(thirdStock.overview.price_memory, thirdStock.instrument, '2026-10-06')
  const thirdChart = prepareStockChartData(thirdBars)
  verify(thirdChart.ma20.every((value) => value === null) && formatStockTooltip(thirdChart, { dataIndex: 0 }).includes('34,637.793'), 'third chart exact lots without invented history')
  thirdClient.clear()
  for (const symbol of ['3105', '6488']) {
    const stock = stockFixture(symbol, '2026-10-06')
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
    client.setQueryData(['stock', 'TPEx', symbol, '2026-10-06'], stock)
    const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter,
      { initialEntries: [`/stocks/TPEx/${symbol}?as_of=2026-10-06`] }, React.createElement(App.default))))
    verify(html.includes(symbol === '3105' ? '19,731.7' : '13,913.614') && html.includes(symbol === '3105' ? '>592<' : '>1,205<'), 'new immutable tuple produces same-date M1 exact lots and per-share close')
    verify(html.includes('10/6 官方單日行情') && html.includes('/stocks/TPEx/3105?as_of=2026-10-06') && html.includes('/stocks/TPEx/6488?as_of=2026-10-06'), 'new M1 labels and navigation follow explicit admitted cutoff')
    verify(html.includes('data-date-2026-10-06') && html.includes(memoryRead.priceSourcePins('2026-10-06', stock.overview.price_memory.provenance.policy_version).bodySha), 'legacy original-row source card uses exact date/version/body pin')
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
  const m1Fixtures = [stockFixture('3105'), stockFixture('6488'), stockFixture('3105', '2026-10-06'), stockFixture('6488', '2026-10-06'), thirdStock, fourthStock]
  const fixtureBytes = Buffer.byteLength(JSON.stringify(m1Fixtures)), fixtureObjectEstimate = estimateGraph(m1Fixtures)
  assert(fixtureBytes <= 64 * 1024 && fixtureObjectEstimate <= 512 * 1024, 'bounded old/new M1 fixture graphs; estimate is not RSS')
  console.log(JSON.stringify({ passed: true, validator_checks: validatorChecks, affected_overview_ssr_checks: overviewChecks,
    full_app_chart_checks: appChecks, known_react_router_ssr_useLayoutEffect_warnings: knownSSRWarnings, fixture_bytes: fixtureBytes, fixture_object_estimated_bytes: fixtureObjectEstimate,
    ...receipt(), not_run: ['backend rerun', 'external source', 'browser native UI', 'disk persistence', 'full build', 'historical price/MA20'] }))
}

const requests = { api_get: 0, api_post: 0, rejected: 0 }
const json = (response, status, value) => { response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' }); response.end(JSON.stringify(value)) }
function jointStaticError(method, pathname) {
  if (pathname.endsWith('/prices/saved')) return [405, 'use_the_admitted_saved_focus_reader']
  if (method === 'POST' && !/^\/api\/stocks\/TPEx\/(3105|6488)\/institutional-windows\/capture$/.test(pathname)) return [405, 'joint_post_outside_scope']
  if (!['GET', 'POST'].includes(method)) return [405, 'joint_method_outside_scope']
  return null
}
function jointRequestError(method, url, body) {
  const staticError = jointStaticError(method, url.pathname)
  if (staticError) return staticError
  const pairs = [...url.searchParams]
  const params = (allowed, required = []) => {
    if (pairs.some(([key]) => !allowed.includes(key)) || allowed.some((key) => url.searchParams.getAll(key).length > 1)
      || required.some((key) => url.searchParams.getAll(key).length !== 1)) throw new Error('joint conditions')
    return Object.fromEntries(pairs)
  }
  try {
    if (url.pathname.endsWith('/prices/saved')) return [405, 'use_the_admitted_saved_focus_reader']
    if (method === 'POST') {
      if (!/^\/api\/stocks\/TPEx\/(3105|6488)\/institutional-windows\/capture$/.test(url.pathname)) return [405, 'joint_post_outside_scope']
      if (params(['as_of'], ['as_of']).as_of !== '2026-10-06') return [422, 'joint_cutoff_not_supported']
      if (body.length > 4096) return [413, 'joint_request_body_bound']
      if (!body.length) return [422, 'joint_empty_json_object_required']
      const value = JSON.parse(body.toString('utf8'))
      if (!value || Array.isArray(value) || typeof value !== 'object' || Object.keys(value).length) return [422, 'joint_empty_json_object_required']
      return null
    }
    if (method !== 'GET') return [405, 'joint_method_outside_scope']
    if (body.length) return [422, 'joint_get_body_forbidden']
    if (url.pathname === '/api/focus/price-saved') {
      const p = params(['as_of', 'min_lots', 'day_move', 'min_turnover', 'min_range_pct'], ['as_of', 'min_lots'])
      const helper = require(path.join(sourceRoot, 'priceFocus.ts'))
      if (!helper.validFocusDate(p.as_of) || helper.minLotsShares(p.min_lots) === null || !helper.validPriceFocusDayMove(p.day_move ?? 'all')
        || helper.minTurnoverValue(p.min_turnover ?? '0') === null || helper.minRangeMilliPct(p.min_range_pct ?? '0') === null) throw new Error('joint focus conditions')
    } else {
      const stock = url.pathname.match(/^\/api\/stocks\/([^/]+)\/([^/]+)(\/(overview|prices\/saved-focus))?$/)
      if (stock) {
        if (stock[1] !== 'TPEx' || !jointPolicy.scope.saved_symbols.includes(stock[2])) return [405, 'joint_stock_outside_scope']
        if (params(['as_of'], ['as_of']).as_of !== '2026-10-06') return [422, 'joint_cutoff_not_supported']
      } else if (url.pathname.includes('/prices/saved-focus') || url.pathname.includes('/prices/saved')) return [405, 'joint_sensitive_path_outside_scope']
      else if (url.pathname === '/__price_validation/receipt') {
        if (!['false', 'true'].includes(params(['include_raw']).include_raw ?? 'false')) throw new Error('joint diagnostic')
      } else if (url.pathname === '/__price_validation/chips/raw') {
        if (!/^(0|[1-9]|1[0-9]|2[01])$/.test(params(['index'], ['index']).index)) throw new Error('joint raw index')
      }
    }
    return null
  } catch { return [422, 'joint_request_conditions_invalid'] }
}
async function boundedJointBody(request) {
  const limit = request.method === 'POST' ? 4096 : 0
  let size = 0
  const chunks = []
  // Keep the response socket alive on an early refusal so the caller receives
  // the admitted 413/422 status rather than a connection reset.
  for await (const chunk of request.iterator({ destroyOnReturn: false })) {
    size += chunk.length
    if (size > limit) { request.resume(); throw { status: limit ? 413 : 422, detail: limit ? 'joint_request_body_bound' : 'joint_get_body_forbidden' } }
    chunks.push(chunk)
  }
  return Buffer.concat(chunks)
}
async function proxy(request, response) {
  const url = new URL(request.url, `http://127.0.0.1:${port}`)
  let body
  if (jointActive) {
    const refusedBeforeBody = jointStaticError(request.method, url.pathname)
    if (refusedBeforeBody) { requests.rejected++; return json(response, refusedBeforeBody[0], { detail: refusedBeforeBody[1] }) }
    try { body = await boundedJointBody(request) } catch (error) { requests.rejected++; return json(response, error.status ?? 422, { detail: error.detail ?? 'joint body invalid' }) }
    const refused = jointRequestError(request.method, url, body)
    if (refused) { requests.rejected++; return json(response, refused[0], { detail: refused[1] }) }
  }
  const allowed = jointActive || request.method === 'GET' || (!args.includes('--saved-source-only') && request.method === 'POST' && (/^\/api\/stocks\/TPEx\/(?:3105|3293|5274|5347|6488|6510|8069)\/prices\/(?:capture|save)$/.test(url.pathname) || url.pathname === '/api/focus/price-lots/capture'))
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
  if (jointActive) upstream.end(body)
  else {
    let length = 0
    request.on('data', (part) => { length += part.length; if (length > 4096) { request.destroy(); upstream.destroy() } })
    request.pipe(upstream)
  }
}
async function serve() {
  const build = await esbuild.build({ entryPoints: [path.join(sourceRoot, 'main.tsx')], bundle: true, write: false,
    absWorkingDir: path.join(root, 'frontend'), nodePaths: [dependencies], outdir: '__memory_only__', platform: 'browser', format: 'esm',
    target: 'es2020', jsx: 'automatic', define: { 'import.meta.env.VITE_API_BASE': JSON.stringify('/api'), 'import.meta.env.VITE_SAVED_PRICE_CHIPS_INTEGRATION': JSON.stringify(jointActive ? 'm1-v1' : ''), 'process.env.NODE_ENV': JSON.stringify('development') } })
  const script = build.outputFiles.find((file) => file.path.endsWith('.js')).contents
  const css = build.outputFiles.find((file) => file.path.endsWith('.css')).text.replace(/@import\s+(?:url\([^)]*\)|["'][^"']*["'])\s*;/g, '')
  const html = fs.readFileSync(path.join(root, 'frontend/index.html'), 'utf8').replace('src="/src/main.tsx"', 'src="/app.js"')
    .replace('</head>', '<link rel="stylesheet" href="/app.css"></head>')
    .replace('<div id="root">', '<div style="padding:8px;background:#573e18;color:#fff">受控驗收：所選普通股身分由統籌核對後建構記憶體操作目錄；既有行情與未支持標的仍為合成樣本。官方單日行情須經本次擷取或私有保存原件讀回核對後才採用；來源狀態可在個股詳情核對。</div><div id="root">')
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
