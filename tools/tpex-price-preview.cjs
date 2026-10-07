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
const pinOptions = ['--policy-version', '--policy-digest', '--private-policy-version', '--private-policy-digest', '--saved-focus-policy-version', '--saved-focus-policy-digest', '--chips-policy-version', '--chips-policy-digest', '--joint-policy-version', '--joint-policy-digest', '--joint-focus-policy-version', '--joint-focus-policy-digest']
assert(args.every((arg, index) => ['--deps', '--check', '--event-range-check', '--event-range', '--scope-check', '--focus-check', '--saved-focus-check', '--joint-check', '--saved-price-chips-focus-check', '--saved-price-chips-focus-calendar-check', '--saved-price-chips-focus-stock-scope-7-check', '--private-save-check', '--serve', '--stock-scope6-opt-in', '--saved-source-only', '--saved-price-chips-opt-in', '--saved-price-chips-focus-opt-in', '--saved-price-chips-focus-calendar-opt-in', '--saved-price-chips-focus-stock-scope-7-opt-in', '--port', '--api-port', ...pinOptions].includes(arg) || ['--deps', '--port', '--api-port', ...pinOptions].includes(args[index - 1])), 'unknown argument')
const eventRangeCheck = args.includes('--event-range-check'), eventRangeActive = args.includes('--event-range')
assert(!(eventRangeCheck && eventRangeActive), 'choose event check or serve')
assert(!eventRangeActive || args.includes('--serve'), 'event-range is an owned serve mode')
assert(!(eventRangeCheck || eventRangeActive) || !args.some((arg) => arg !== '--event-range-check' && (arg.endsWith('-check') || arg.endsWith('-opt-in') || ['--check', '--saved-source-only', ...pinOptions].includes(arg))), 'event range excludes other consumers')
assert(!eventRangeCheck || !args.includes('--serve'), 'event check has zero network')
assert(!args.includes('--scope-check') || !['--serve', '--check', '--focus-check', '--saved-focus-check', '--joint-check', '--saved-price-chips-focus-check', '--private-save-check'].some((flag) => args.includes(flag)), 'choose one scope check mode')
assert(!(args.includes('--serve') && args.includes('--check')), 'choose check or serve')
assert(!(args.includes('--focus-check') && (args.includes('--serve') || args.includes('--check'))), 'choose one check mode')
assert(!(args.includes('--private-save-check') && (args.includes('--serve') || args.includes('--check') || args.includes('--focus-check'))), 'choose one check mode')
assert(!args.includes('--saved-focus-check') || !['--serve', '--check', '--focus-check', '--private-save-check'].some((flag) => args.includes(flag)), 'choose one check mode')
assert(!args.includes('--saved-source-only') || args.includes('--serve'), 'saved-source-only is an owned serve mode')
const root = path.resolve(__dirname, '..')
const scope7Active = args.includes('--saved-price-chips-focus-stock-scope-7-opt-in')
const scope7Check = args.includes('--saved-price-chips-focus-stock-scope-7-check')
const scope7Mode = scope7Active || scope7Check
const calendarActive = args.includes('--saved-price-chips-focus-calendar-opt-in')
const calendarCheck = args.includes('--saved-price-chips-focus-calendar-check')
const calendarMode = calendarActive || calendarCheck
const focusActive = args.includes('--saved-price-chips-focus-opt-in') || calendarActive || scope7Active
const focusCheck = args.includes('--saved-price-chips-focus-check') || calendarCheck || scope7Check
const focusAPIPath = scope7Mode ? '/api/focus/price-saved-chips-stock-scope-7' : calendarMode ? '/api/focus/price-saved-chips-calendar' : '/api/focus/price-saved-chips'
assert([args.includes('--saved-price-chips-opt-in'), args.includes('--saved-price-chips-focus-opt-in'), calendarActive, scope7Active].filter(Boolean).length <= 1, 'choose one independently bound joint mode')
assert(!focusActive || !args.includes('--saved-price-chips-opt-in'), 'choose one joint consumer')
assert(!focusCheck || !['--serve', '--check', '--joint-check', '--focus-check', '--saved-focus-check', '--private-save-check'].some((flag) => args.includes(flag)), 'choose one check mode')
const jointActive = args.includes('--saved-price-chips-opt-in') || focusActive
const stockScope6Active = args.includes('--stock-scope6-opt-in')
const stockScope6Version = 'm2-stock-scope-tpex-11370-2026-10-07.1'
const stockScope6Digest = 'sha256:bdad10af9090dd15319b3f3e8dca2952f75c4caf6d46b3032e706a5006ccbab2'
assert(!stockScope6Active || args.includes('--serve') && !jointActive && !args.includes('--saved-source-only'), 'new stock scope requires ordinary owned serve')
if (stockScope6Active) {
  assert(option('--policy-version') === stockScope6Version && option('--policy-digest') === stockScope6Digest, 'independent external stock-scope6 pins required')
  assert(!pinOptions.slice(2).some((name) => args.includes(name)), 'new stock scope excludes private/chips pins')
}
assert(!jointActive || args.includes('--serve') && args.includes('--saved-source-only'), 'joint opt-in requires saved-only serve')
assert(jointActive || stockScope6Active || !pinOptions.some((name) => args.includes(name)), 'pins require an admitted opt-in')
let jointPolicy
const jointDigest = scope7Mode ? 'sha256:8e55142cce367fd44d64ea9d6d9e756c1fdd5b091c928669bbe94de1df950de8' : calendarMode ? 'sha256:bfb9abeca3546f2dcedfcacaf5b3dece1709c05b49a839bce3fea5ded1936765' : 'sha256:a5e6ecda19952e4f6dc44ad9660e4cbbcc2e4a0a3670229ab63900cf74678d14'
if (jointActive || args.includes('--joint-check') || focusCheck) {
  const jointPolicyText = fs.readFileSync(path.join(root, scope7Mode ? 'backend/app/saved_price_chips_scope7_entry.py' : calendarMode ? 'backend/app/saved_price_chips_calendar_entry.py' : 'backend/app/saved_price_chips_entry.py'), 'utf8').match(/_POLICY = json.loads\(r'''([\s\S]*?)'''\)/)[1]
  jointPolicy = JSON.parse(jointPolicyText)
  assert(Buffer.byteLength(jointPolicyText) === (scope7Mode ? 13404 : calendarMode ? 12009 : 10702) && 'sha256:' + crypto.createHash('sha256').update(jointPolicyText).digest('hex') === jointDigest, 'canonical joint policy intact')
}
let focusPolicy
const focusDigest = scope7Mode ? 'sha256:2f6d3a91337363e5700d7fdf6c16c63b8a14f45362d4407c8b73b01dabfe860e' : calendarMode ? 'sha256:42c232a3f533683dce727ce1279e767038a6ee0f6295ce85b5aee07e998972bc' : 'sha256:1b48fc6bb23b021f3d289c797b8d077af4576f492cbc08953d0515ef0da89416'
if (focusActive || focusCheck) {
  const source = fs.readFileSync(path.join(root, scope7Mode ? 'backend/app/saved_price_chips_scope7_focus.py' : calendarMode ? 'backend/app/saved_price_chips_calendar_focus.py' : 'backend/app/saved_price_chips_focus.py'), 'utf8')
  const literal = source.match(/^_POLICY = json.loads\(r'''(.+)'''\)$/m)
  assert(literal, 'exact admitted focus policy literal required')
  assert(Buffer.byteLength(literal[1]) === (scope7Mode ? 17021 : calendarMode ? 15487 : 14399) && 'sha256:' + crypto.createHash('sha256').update(literal[1]).digest('hex') === focusDigest, 'ROOT focus policy intact')
  focusPolicy = JSON.parse(literal[1])
}
if (focusActive) {
  assert(option('--joint-focus-policy-version') === focusPolicy.version && option('--joint-focus-policy-digest') === focusDigest, 'independent external new focus pins required')
  const pin = focusPolicy.independent_pins.joint_entry
  assert(option('--joint-policy-version') === pin.policy_version && option('--joint-policy-digest') === `sha256:${pin.sha256}`, 'fifth independent policy pair required')
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

async function appSSRModule(joint = false, focus = false, calendar = false, scope7 = false) {
  // The package's CJS entry returns { default: Component }. Normalize only
  // this Node SSR import; the browser bundle keeps its real ECharts component.
  const originalLoad = Module._load
  Module._load = function (request, parent, ...rest) {
    const value = originalLoad.call(this, request, parent, ...rest)
    return request === 'echarts-for-react' && value && typeof value.default === 'function' ? value.default : value
  }
  const entry = eventRangeCheck ? { stdin: { contents: "export * from './App'; export { default } from './App'; export { getOfficialEventFocus, captureOfficialEventFocus } from './api'", resolveDir: sourceRoot, loader: 'ts', sourcefile: 'event-range-ssr-memory.ts' } } : focus ? { stdin: { contents: "export { default } from './App'; export { SavedPriceChipsFocusResults } from './SavedPriceChipsFocusPage'" + ((calendar || scope7) ? "; export { InstitutionalWindows, PriceSaved } from './components/StockOverview'; export { jointValidationTransition } from './App'" : ''), resolveDir: sourceRoot, loader: 'ts', sourcefile: 'joint-focus-ssr-memory.ts' } } : { entryPoints: [path.join(sourceRoot, 'App.tsx')] }
  const result = await esbuild.build({ ...entry, bundle: true, write: false,
    ...(eventRangeCheck ? { loader: { '.css': 'empty' } } : {}),
    platform: 'node', format: 'cjs', target: 'es2020', jsx: 'automatic', nodePaths: [dependencies],
    external: ['react', 'react/*', 'react-dom', 'react-dom/*', '@tanstack/react-query', 'react-router-dom', 'echarts', 'echarts-for-react'],
    define: { 'import.meta.env.VITE_API_BASE': JSON.stringify('/api'), 'import.meta.env.VITE_CHIPS_SERIES_STOCK_SCOPE_7': JSON.stringify(''), 'import.meta.env.VITE_SAVED_PRICE_CHIPS_INTEGRATION': JSON.stringify(joint ? 'm1-v1' : ''), 'import.meta.env.VITE_SAVED_PRICE_CHIPS_FOCUS': JSON.stringify(focus && !calendar && !scope7 ? 'm1-v1' : ''), 'import.meta.env.VITE_SAVED_PRICE_CHIPS_FOCUS_CALENDAR': JSON.stringify(calendar ? 'm1-v2' : ''), 'import.meta.env.VITE_SAVED_PRICE_CHIPS_FOCUS_STOCK_SCOPE_7': JSON.stringify(scope7 ? 'm1-v1' : '') } })
  const module = new Module(path.join(sourceRoot, '__memory_unit_lots_app__.cjs'))
  module.filename = path.join(sourceRoot, '__memory_unit_lots_app__.cjs')
  module.paths = Module._nodeModulePaths(sourceRoot)
  module._compile(result.outputFiles[0].text, module.filename)
  return module.exports
}


// Check fixtures are synthetic; serving proxies the root-owned actual Python API.
global.__institutionalWindowSSRSelection = 'unit-lots-only'
const cases = eventRangeCheck || eventRangeActive || (focusActive || focusCheck) && !(calendarCheck || scope7Check) ? {} : require(path.join(sourceRoot, 'components/StockOverview.test.tsx'))
const memoryCases = eventRangeCheck || eventRangeActive || (focusActive || focusCheck) && !(calendarCheck || scope7Check) ? {} : require(path.join(sourceRoot, 'stockPriceMemoryRead.test.ts'))
const memoryRead = require(path.join(sourceRoot, 'stockPriceMemoryRead.ts'))
const savedCases = eventRangeCheck || eventRangeActive || focusActive || focusCheck ? {} : require(path.join(sourceRoot, 'stockPriceSavedRead.test.ts'))
const savedFocusCases = eventRangeCheck || eventRangeActive || focusActive || focusCheck ? {} : require(path.join(sourceRoot, 'savedPriceFocus.test.ts'))
const focusCases = eventRangeCheck || eventRangeActive || focusActive || focusCheck ? {} : require(path.join(sourceRoot, 'priceFocus.test.ts'))
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
  if (eventRangeCheck) {
    const checks = await checkEventRange()
    assert(Object.values(counts).every((count) => count === 0), 'event guards zero')
    console.log(JSON.stringify({ passed: true, contract: 'official-event-focus/p3-v1', ...checks,
      known_react_router_ssr_useLayoutEffect_warnings: knownSSRWarnings, ...receipt(),
      not_run: ['external source', 'browser native UI', 'disk persistence', 'production build', 'ordinary-stock price history'] }))
    return
  }
  if (args.includes('--scope-check')) {
    const memoryChecks = memoryCases.runScopeMemoryReadTests(), focusChecks = focusCases.runScopeFocusTests()
    const { QueryClient, QueryClientProvider } = requireDependency('@tanstack/react-query')
    const { MemoryRouter } = requireDependency('react-router-dom')
    const App = await appSSRModule()
    let ssrChecks = 0, maxSerialized = 0, maxGraph = 0
    const verify = (value, message) => { ssrChecks++; assert(value, message) }
    for (const [lots, amount, range, expected] of [['0.000', '0', '0.000', 8], ['896.441', '4984488555', '10.000', 1], ['896.442', '4984488555', '10.000', 0], ['896.441', '4984488556', '10.000', 0], ['896.441', '4984488555', '10.001', 0]]) {
      const move = expected === 8 ? 'all' : 'up'
      const data = focusCases.createPriceFocusFixture(lots, move, amount, range, '2026-10-07')
      maxSerialized = Math.max(maxSerialized, Buffer.byteLength(JSON.stringify(data))); maxGraph = Math.max(maxGraph, estimateGraph(data))
      assert(maxSerialized <= 80 * 1024 && maxGraph <= 512 * 1024, 'eight-stock synthetic fixture caps; estimate is not RSS')
      const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
      client.setQueryData(['price-lot-focus', '2026-10-07', lots, move, amount, range], data)
      const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter,
        { initialEntries: [`/?as_of=2026-10-07&min_lots=${lots}&day_move=${move}&min_turnover=${amount}&min_range_pct=${range}`] }, React.createElement(App.default))))
      verify((html.match(/class="focus-card"/g) || []).length === expected && html.includes('已核 8 股'), 'eight-stock complete scope rendered')
      verify(expected !== 0 || html.includes('零候選'), 'verified zero distinct')
      if (expected === 1) verify(html.includes('6223 旺矽') && html.includes('4984488555') && html.includes('focus_min_range_pct=10.000'), 'eighth exact reason and detail link')
      if (expected === 1) {
        client.getQueryCache().find({ queryKey: ['price-lot-focus', '2026-10-07', lots, move, amount, range] }).setState({ status: 'error', error: new Error('synthetic_current_refetch_failure') })
        const failed = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter,
          { initialEntries: [`/?as_of=2026-10-07&min_lots=${lots}&day_move=${move}&min_turnover=${amount}&min_range_pct=${range}`] }, React.createElement(App.default))))
        verify(!failed.includes('class="focus-card"') && !failed.includes('focus-count') && failed.includes('候選數未知') && failed.includes('讀取已取得原件'), 'current failure masks cached positive candidates and keeps explicit read')
      }
      client.clear()
    }
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
    client.setQueryData(['stock', 'TPEx', '6223', '2026-10-07'], stockFixture('6223', '2026-10-07'))
    const route = '/stocks/TPEx/6223?as_of=2026-10-07&from=price-lots&focus_as_of=2026-10-07&focus_min_lots=896.441&focus_day_move=up&focus_min_turnover=4984488555&focus_min_range_pct=10.000'
    const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter, { initialEntries: [route] }, React.createElement(App.default))))
    verify(html.includes('2026-10-07 官方單日行情') && html.includes('旺矽'), 'new source date and eighth detail')
    verify(html.includes('/?as_of=2026-10-07&amp;min_lots=896.441&amp;day_move=up&amp;min_turnover=4984488555&amp;min_range_pct=10.000#price-lot-focus-title'), 'five raw strings safe return')
    client.getQueryCache().find({ queryKey: ['stock', 'TPEx', '6223', '2026-10-07'] }).setState({ status: 'error', error: new Error('synthetic_current_refetch_failure') })
    const failedDetail = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter, { initialEntries: [route] }, React.createElement(App.default))))
    verify(!failedDetail.includes('overview-price-memory') && !failedDetail.includes('stock-quote-grid') && !failedDetail.includes('stock-price-chart') && !failedDetail.includes('官方單日行情原始列'), 'detail failure masks retained numeric headline/chart/raw')
    client.clear()
    let guardChecks = 0
    const guard = (method, route, body, status) => { assert.equal(scope6RequestError(method, new URL(route, 'http://owned.invalid'), Buffer.from(body))?.[0] ?? 200, status); guardChecks++ }
    const query = 'as_of=2026-10-07&min_lots=896.441&day_move=up&min_turnover=4984488555&min_range_pct=10.000'
    for (const method of ['GET', 'POST']) {
      const base = '/api/focus/price-lots' + (method === 'POST' ? '/capture' : '') + '?' + query, body = method === 'POST' ? '{}' : ''
      guard(method, base, body, 200)
      for (const suffix of ['&x=1', '&min_lots=896.441']) guard(method, base + suffix, body, 422)
      guard(method, base.replace('&min_range_pct=10.000', ''), body, 422)
      guard(method, base.replace('896.441', '9223372036854775.808'), body, 422)
      if (method === 'POST') for (const value of ['', 'null', '[]', '{"x":1}', '\ufffd', ' '.repeat(4097)]) guard(method, base, value, value.length > 4096 ? 413 : 422)
      else guard(method, base, '{}', 422)
    }
    for (const symbol of ['3105', '3293', '5274', '5347', '6223', '6488', '6510', '8069']) guard('POST', `/api/stocks/TPEx/${symbol}/prices/capture?as_of=2026-10-07`, '{}', 200)
    guard('POST', '/api/stocks/TPEx/6223/prices/capture?as_of=2026-10-06', '{}', 422)
    for (const path of ['/api/stocks/TPEx/6223/prices/save', '/api/stocks/TPEx/6223/institutional-windows/capture', '/api/stocks/TPEx/9999/prices/capture']) guard('POST', path + '?as_of=2026-10-07', '{}', 405)
    guard('POST', '/__price_ui/receipt', '{}', 405)
    verify(previewBanner(true).includes('首次載入前沒有行情資料') && !previewBanner(true).includes('合成樣本') && previewBanner(false).includes('既有行情與未支持標的仍為合成樣本'), 'new empty-finance banner and retained old banner')
    assert(Object.values(counts).every((x) => x === 0), 'scope guards')
    console.log(JSON.stringify({ passed: true, memory_checks: memoryChecks, focus_checks: focusChecks, scope_app_ssr_checks: ssrChecks, scope_request_guard_checks: guardChecks, max_fixture_serialized_bytes: maxSerialized, max_held_fixture_graph_estimated_bytes: maxGraph, estimate_not_rss: true, max_selected_rows: 8, ...receipt(), not_run: ['actual source', 'native operation', 'private files', 'disk cases', 'prior full suites'] }))
    return
  }
  if (scope7Check) {
    const tests = require(path.join(sourceRoot, 'savedPriceChipsFocus.test.ts'))
    const validator = require(path.join(sourceRoot, 'institutionalWindows.test.ts'))
    const checks = tests.runScope7FocusTests() + validator.runScope7WindowTests()
    const data = tests.scope7JointFixture()
    let fixtureBytes = tests.scope7FixtureInputBytes(data)
    const results = await appSSRModule(false, true, false, true)
    const { MemoryRouter } = requireDependency('react-router-dom')
    const { QueryClient, QueryClientProvider } = requireDependency('@tanstack/react-query')
    let ssrChecks = 0
    const verify = (condition, message) => { ssrChecks++; assert(condition, message) }
    const focusRoute = '/saved-price-chips-focus-stock-scope-7?' + new URLSearchParams(tests.jointFixtureConditions())
    const page = renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: [focusRoute] }, React.createElement(results.default)))
    for (const text of ['讀取保存來源', '首次取得法人來源', '核對共同來源並篩選', '候選數未知']) verify(page.includes(text), text)
    verify(page.indexOf('讀取保存來源</button>') < page.indexOf('首次取得法人來源</button>') && page.indexOf('首次取得法人來源</button>') < page.indexOf('核對共同來源並篩選</button>'), 'three explicit actions ordered saved read then FIRST then joint read')
    verify(!page.includes('class="focus-card"'), 'new route performs no private read on entry')
    const positive = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(results.SavedPriceChipsFocusResults, { data, scope7: true })))
    verify(['3105', '3293', '5274', '5347', '6488', '6510', '8069'].every(code => positive.includes(code)), 'seven matching cards')
    const conditions = tests.jointFixtureConditions({ min_net_lots: '1000000.000' })
    const zero = tests.scope7JointFixture(conditions, data)
    const html = renderToStaticMarkup(React.createElement(results.SavedPriceChipsFocusResults, { data: zero, scope7: true }))
    verify(html.includes('零候選'), 'full joint verification before available zero')

    let signedSSRFixtureGraph = 0
    for (const [horizon, net] of [['5', '-0.125'], ['20', '-0.35']]) {
      const negativeConditions = tests.jointFixtureConditions({ investor: 'trust', horizon, min_net_lots: net })
      const negative = tests.scope7JointFixture(negativeConditions, data)
      const negativeHTML = renderToStaticMarkup(React.createElement(MemoryRouter, null,
        React.createElement(results.SavedPriceChipsFocusResults, { data: negative, scope7: true })))
      verify(negative.count === 7 && negativeHTML.includes(`${horizon} 交易日淨買賣超 ${net} 張 ≥ ${net} 張`), 'scope7 exact signed negative net rendered for ' + horizon)
      fixtureBytes += Buffer.byteLength(JSON.stringify(negativeConditions))
      signedSSRFixtureGraph = Math.max(signedSSRFixtureGraph, tests.jointFixtureGraphBytes([data, zero, negative]))
    }
    const institutional = data.institutional[0]
    const windowProps = { data: institutional, scope7: true, onCapture: () => {}, expectedExchange: 'TPEx', expectedSymbol: '3105', expectedCutoff: '2026-10-06' }
    const windowHTML = renderToStaticMarkup(React.createElement(results.InstitutionalWindows, windowProps))
    verify(windowHTML.includes('25個已驗月原件交易日（24日採用）') && windowHTML.includes('2026-10-07／5') && windowHTML.includes('20261007'), 'all25 original calendar rows render, including unadopted 10/07')
    verify(windowHTML.includes('此日完整25欄官方原字串') && windowHTML.includes('窗口來源稽核原值'), 'daily and window raw source evidence')
    const failedHTML = renderToStaticMarkup(React.createElement(results.InstitutionalWindows, { ...windowProps, requestFailure: 'window_read_request_failed' }))
    verify(!failedHTML.includes('20261007') && !failedHTML.includes('窗口來源稽核原值') && !failedHTML.includes('此日完整25欄官方原字串') && failedHTML.includes('未能通過核對'), 'current read failure masks held chips nets and both raw families')
    verify(failedHTML.includes('讀取本次法人窗口'), 'current failure retains explicit held verification action without another FIRST')
    const priceRead = data.price.reads[0]
    const priceDetail = { ...priceRead.price_saved, focus_consumer: data.price.consumer_provenance }
    const priceProps = { data: priceDetail, instrument: priceRead.instrument, cutoff: '2026-10-06', canSave: false, readonly: true }
    const knownPrice = renderToStaticMarkup(React.createElement(results.PriceSaved, priceProps))
    verify(knownPrice.includes('保存原件的官方原字串') && knownPrice.includes('19,731.7'), 'held saved original values render only after verification')
    const failedPrice = renderToStaticMarkup(React.createElement(results.PriceSaved, { ...priceProps, failure: 'joint_source_read_failed' }))
    verify(!failedPrice.includes('19,731.7') && !failedPrice.includes('保存原件的官方原字串') && failedPrice.includes('未能通過核對'), 'current joint failure masks saved values and original raw')
    const helper = require(path.join(sourceRoot, 'savedPriceChipsFocus.ts'))
    const expectedMarketRoute = '/saved-price-chips-focus-stock-scope-7?' + new URLSearchParams({ as_of: '2026-10-06', min_lots: '10000.000', day_move: 'all', min_turnover: '0', min_range_pct: '0.000', investor: 'foreign', horizon: '5', min_net_lots: '0.000' })
    let largestSSRFixtureGraph = tests.jointFixtureGraphBytes([data, zero, priceDetail])
    for (const route of ['/', helper.jointDetailPath('3105', tests.jointFixtureConditions(), false, true), helper.jointDetailPath('3105', tests.jointFixtureConditions(), false, true) + '&focus_horizon=5']) {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
      const detail = stockFixture('3105', '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V5)
      detail.overview.institutional = institutional
      largestSSRFixtureGraph = Math.max(largestSSRFixtureGraph, tests.jointFixtureGraphBytes([data, zero, priceDetail, detail]))
      client.setQueryData(['stock', 'TPEx', '3105', '2026-10-06'], detail)
      const output = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter, { initialEntries: [route] }, React.createElement(results.default))))
      verify(route === '/' ? output.includes('href="' + expectedMarketRoute.replaceAll('&', '&amp;') + '"') : new URL(route, 'http://owned.invalid').searchParams.getAll('focus_horizon').length > 1 ? output.includes('未讀取來源') && !output.includes('保存原件的官方原字串') : output.includes(helper.jointReturnPath(new URL(route, 'http://owned.invalid').searchParams, false, true).replaceAll('&', '&amp;')) && !output.includes('保存原件的官方原字串'), 'full App independent route and strict RAW context with no implicit private read: ' + route)
      client.clear()
    }
    const failed = results.jointValidationTransition({ token: 'current', epoch: 0, failure: null, price: true, chips: true }, 'current', 0, 'failure')
    verify(failed.failure && !failed.price && !failed.chips && results.jointValidationTransition(failed, 'current', 0, 'price') === failed, 'current detail failure clears both and rejects stale completion')
    const freshPrice = results.jointValidationTransition(failed, 'current', 1, 'price')
    verify(freshPrice.failure && freshPrice.price && !freshPrice.chips && !results.jointValidationTransition(freshPrice, 'current', 1, 'chips').failure, 'same generation new private read plus held chips verification required to recover')
    const fixtureGraph = Math.max(signedSSRFixtureGraph, largestSSRFixtureGraph, tests.largestScope7FixtureGraphBytes, validator.largestScope7WindowFixtureGraphBytes)
    assert(fixtureBytes <= 81920 && fixtureGraph <= 524288, 'aggregate calendar fixture caps')
    let guardChecks = 0
    const checkGate = (method, route, body, expected) => { assert.equal(focusRequestError(method, new URL(route, 'http://owned.invalid'), Buffer.from(body))?.[0] ?? 200, expected); guardChecks++ }
    checkGate('GET', focusAPIPath + '?' + new URLSearchParams(tests.jointFixtureConditions()), '', 200)
    checkGate('GET', focusAPIPath + '?' + new URLSearchParams(tests.jointFixtureConditions()) + '&investor=foreign', '', 422)
    checkGate('GET', focusAPIPath + '?' + new URLSearchParams(tests.jointFixtureConditions()), '{}', 422)
    checkGate('GET', '/api/focus/price-saved-chips?' + new URLSearchParams(tests.jointFixtureConditions()), '', 405)
    checkGate('POST', '/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-06', '{}', 409)
    completeFocusProxy(focusProxyGeneration, true)
    checkGate('POST', '/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-06', ' {} ', 200)
    checkGate('POST', '/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-06', 'null', 422)
    checkGate('POST', '/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-06&x=1', '{}', 422)
    checkGate('GET', '/api/stocks/TPEx/3105?as_of=2026-10-06&x=1', '', 422)
    checkGate('GET', '/__price_validation/chips/raw?index=22', '', 422)
    assert(Object.values(counts).every(value => value === 0))
    console.log(JSON.stringify({ passed: true, scope7_validator_checks: checks, preview_guard_checks: guardChecks, ssr_checks: ssrChecks,
      fixture_input_serialized_bytes: fixtureBytes, fixture_retained_graph_estimated_bytes: fixtureGraph,
      max_serialized_bytes: 81920, max_graph_estimated_bytes: 524288, actual_source_get: 0, actual_private_reads: 0, old_test_suites_run: 0, ...receipt() }))
    return
  }
  if (calendarCheck) {
    const tests = require(path.join(sourceRoot, 'savedPriceChipsFocus.test.ts'))
    const validator = require(path.join(sourceRoot, 'institutionalWindows.test.ts'))
    const checks = tests.runCalendarFocusTests() + validator.runCalendarWindowTests()
    const data = tests.calendarJointFixture()
    let fixtureBytes = tests.jointFixtureInputBytes(data)
    const results = await appSSRModule(false, true, true)
    const { MemoryRouter } = requireDependency('react-router-dom')
    const { QueryClient, QueryClientProvider } = requireDependency('@tanstack/react-query')
    let ssrChecks = 0
    const verify = (condition, message) => { ssrChecks++; assert(condition, message) }
    const focusRoute = '/saved-price-chips-focus-calendar?' + new URLSearchParams(tests.jointFixtureConditions())
    const page = renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: [focusRoute] }, React.createElement(results.default)))
    for (const text of ['讀取保存來源', '首次取得法人來源', '核對共同來源並篩選', '候選數未知']) verify(page.includes(text), text)
    verify(page.indexOf('讀取保存來源</button>') < page.indexOf('首次取得法人來源</button>') && page.indexOf('首次取得法人來源</button>') < page.indexOf('核對共同來源並篩選</button>'), 'three explicit actions ordered saved read then FIRST then joint read')
    verify(!page.includes('class="focus-card"'), 'new route performs no private read on entry')
    const positive = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(results.SavedPriceChipsFocusResults, { data, calendar: true })))
    verify(positive.includes('3105') && positive.includes('6488'), 'two matching cards')
    const conditions = tests.jointFixtureConditions({ min_net_lots: '1000000.000' })
    const zero = tests.calendarJointFixture(conditions, data)
    const html = renderToStaticMarkup(React.createElement(results.SavedPriceChipsFocusResults, { data: zero, calendar: true }))
    verify(html.includes('零候選'), 'full joint verification before available zero')
    let signedSSRFixtureGraph = 0
    {
      const zeroInstitutional = structuredClone(data.institutional)
      for (const read of zeroInstitutional) {
        for (const { row } of read.windows['20'].daily_evidence) {
          const trust = row.investors.trust
          trust.sell = trust.buy
          trust.net = '0'
          row.source_values[trust.source_fields.sell] = trust.buy
          row.source_values[trust.source_fields.net] = '0'
          row.total_net = String(BigInt(row.investors.foreign.net) + BigInt(row.investors.dealer.net))
          row.source_values['三大法人買賣超股數合計'] = row.total_net
        }
        for (const horizon of ['5', '20']) read.windows[horizon].values.trust = '0'
      }
      const zeroSource = { ...data, institutional: zeroInstitutional }
      fixtureBytes += Buffer.byteLength(JSON.stringify({ daily: zeroInstitutional.map(read => read.windows['20'].daily_evidence.map(({ row }) => row.source_values)) }))
      for (const [horizon, net] of [['5', '-0.125'], ['20', '-0.35']]) {
        const negativeConditions = tests.jointFixtureConditions({ investor: 'trust', horizon, min_net_lots: net })
        const negative = tests.calendarJointFixture(negativeConditions, data)
        const negativeHTML = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(results.SavedPriceChipsFocusResults, { data: negative, calendar: true })))
        verify(negative.count === 2 && negativeHTML.includes(`${horizon} 交易日淨買賣超 ${net} 張 ≥ ${net} 張`), 'calendar exact signed negative net rendered for ' + horizon)
        const zeroConditions = tests.jointFixtureConditions({ investor: 'trust', horizon, min_net_lots: '0.000' })
        const zeroNet = tests.calendarJointFixture(zeroConditions, zeroSource)
        const zeroHTML = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(results.SavedPriceChipsFocusResults, { data: zeroNet, calendar: true })))
        verify(zeroNet.count === 2 && zeroHTML.includes(`${horizon} 交易日淨買賣超 0 張 ≥ 0.000 張`), 'calendar exact zero net rendered for ' + horizon)
        fixtureBytes += Buffer.byteLength(JSON.stringify([negativeConditions, zeroConditions]))
        signedSSRFixtureGraph = Math.max(signedSSRFixtureGraph, tests.jointFixtureGraphBytes([data, zero, zeroSource, negative, zeroNet]))
      }
    }
    const institutional = data.institutional[0]
    const windowProps = { data: institutional, calendar: true, expectedExchange: 'TPEx', expectedSymbol: '3105', expectedCutoff: '2026-10-06' }
    const windowHTML = renderToStaticMarkup(React.createElement(results.InstitutionalWindows, windowProps))
    verify(windowHTML.includes('25個已驗月原件交易日（24日採用）') && windowHTML.includes('2026-10-07／5') && windowHTML.includes('20261007'), 'all25 original calendar rows render, including unadopted 10/07')
    verify(windowHTML.includes('此日完整25欄官方原字串') && windowHTML.includes('窗口來源稽核原值'), 'daily and window raw source evidence')
    const failedHTML = renderToStaticMarkup(React.createElement(results.InstitutionalWindows, { ...windowProps, requestFailure: 'window_read_request_failed' }))
    verify(!failedHTML.includes('20261007') && !failedHTML.includes('窗口來源稽核原值') && !failedHTML.includes('此日完整25欄官方原字串') && failedHTML.includes('未能通過核對'), 'current read failure masks held chips nets and both raw families')
    const priceRead = data.price.reads[0]
    const priceDetail = { ...priceRead.price_saved, focus_consumer: data.price.consumer_provenance }
    const priceProps = { data: priceDetail, instrument: priceRead.instrument, cutoff: '2026-10-06', canSave: false, readonly: true }
    const knownPrice = renderToStaticMarkup(React.createElement(results.PriceSaved, priceProps))
    verify(knownPrice.includes('保存原件的官方原字串') && knownPrice.includes('19,731.7'), 'held saved original values render only after verification')
    const failedPrice = renderToStaticMarkup(React.createElement(results.PriceSaved, { ...priceProps, failure: 'joint_source_read_failed' }))
    verify(!failedPrice.includes('19,731.7') && !failedPrice.includes('保存原件的官方原字串') && failedPrice.includes('未能通過核對'), 'current joint failure masks saved values and original raw')
    const helper = require(path.join(sourceRoot, 'savedPriceChipsFocus.ts'))
    const expectedMarketRoute = '/saved-price-chips-focus-calendar?' + new URLSearchParams({ as_of: '2026-10-06', min_lots: '10000.000', day_move: 'all', min_turnover: '0', min_range_pct: '0.000', investor: 'foreign', horizon: '5', min_net_lots: '0.000' })
    let largestSSRFixtureGraph = tests.jointFixtureGraphBytes([data, zero, priceDetail])
    for (const route of ['/', helper.jointDetailPath('3105', tests.jointFixtureConditions(), true), helper.jointDetailPath('3105', tests.jointFixtureConditions(), true) + '&focus_horizon=5']) {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
      const detail = stockFixture('3105', '2026-10-06', memoryRead.PRICE_SCOPE_POLICY_VERSION_V5)
      detail.overview.institutional = institutional
      largestSSRFixtureGraph = Math.max(largestSSRFixtureGraph, tests.jointFixtureGraphBytes([data, zero, priceDetail, detail]))
      client.setQueryData(['stock', 'TPEx', '3105', '2026-10-06'], detail)
      const output = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter, { initialEntries: [route] }, React.createElement(results.default))))
      verify(route === '/' ? output.includes('href="' + expectedMarketRoute.replaceAll('&', '&amp;') + '"') : new URL(route, 'http://owned.invalid').searchParams.getAll('focus_horizon').length > 1 ? output.includes('未讀取來源') && !output.includes('保存原件的官方原字串') : output.includes(helper.jointReturnPath(new URL(route, 'http://owned.invalid').searchParams, true).replaceAll('&', '&amp;')) && !output.includes('保存原件的官方原字串'), 'full App independent route and strict RAW context with no implicit private read: ' + route)
      client.clear()
    }
    const failed = results.jointValidationTransition({ token: 'current', epoch: 0, failure: null, price: true, chips: true }, 'current', 0, 'failure')
    verify(failed.failure && !failed.price && !failed.chips && results.jointValidationTransition(failed, 'current', 0, 'price') === failed, 'current detail failure clears both and rejects stale completion')
    const freshPrice = results.jointValidationTransition(failed, 'current', 1, 'price')
    verify(freshPrice.failure && freshPrice.price && !freshPrice.chips && !results.jointValidationTransition(freshPrice, 'current', 1, 'chips').failure, 'same generation new private read plus held chips verification required to recover')
    const fixtureGraph = Math.max(signedSSRFixtureGraph, largestSSRFixtureGraph, tests.largestCalendarFixtureGraphBytes, validator.largestCalendarWindowFixtureGraphBytes)
    assert(fixtureBytes <= 81920 && fixtureGraph <= 524288, 'aggregate calendar fixture caps')
    let guardChecks = 0
    const checkGate = (method, route, body, expected) => { assert.equal(focusRequestError(method, new URL(route, 'http://owned.invalid'), Buffer.from(body))?.[0] ?? 200, expected); guardChecks++ }
    checkGate('GET', focusAPIPath + '?' + new URLSearchParams(tests.jointFixtureConditions()), '', 200)
    checkGate('GET', focusAPIPath + '?' + new URLSearchParams(tests.jointFixtureConditions()) + '&investor=foreign', '', 422)
    checkGate('GET', focusAPIPath + '?' + new URLSearchParams(tests.jointFixtureConditions()), '{}', 422)
    checkGate('GET', '/api/focus/price-saved-chips?' + new URLSearchParams(tests.jointFixtureConditions()), '', 405)
    checkGate('POST', '/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-06', '{}', 409)
    completeFocusProxy(focusProxyGeneration, true)
    checkGate('POST', '/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-06', ' {} ', 200)
    checkGate('POST', '/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-06', 'null', 422)
    checkGate('POST', '/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-06&x=1', '{}', 422)
    checkGate('GET', '/api/stocks/TPEx/3105?as_of=2026-10-06&x=1', '', 422)
    checkGate('GET', '/__price_validation/chips/raw?index=22', '', 422)
    assert(Object.values(counts).every(value => value === 0))
    console.log(JSON.stringify({ passed: true, calendar_validator_checks: checks, preview_guard_checks: guardChecks, ssr_checks: ssrChecks,
      fixture_input_serialized_bytes: fixtureBytes, fixture_retained_graph_estimated_bytes: fixtureGraph,
      max_serialized_bytes: 81920, max_graph_estimated_bytes: 524288, actual_source_get: 0, actual_private_reads: 0, old_test_suites_run: 0, ...receipt() }))
    return
  }
  if (focusCheck) {
    const helper = require(path.join(sourceRoot, 'savedPriceChipsFocus.ts'))
    const tests = require(path.join(sourceRoot, 'savedPriceChipsFocus.test.ts'))
    const checks = tests.runJointFocusTests()
    let gateChecks = 0, ssrChecks = 0
    const verify = (method, route, body, status) => {
      assert.equal(focusRequestError(method, new URL(route, 'http://owned.invalid'), Buffer.from(body))?.[0] ?? 200, status); gateChecks++
    }
    const conditions = tests.jointFixtureConditions()
    const query = new URLSearchParams(conditions).toString()
    const focusRoute = '/api/focus/price-saved-chips?' + query
    verify('GET', focusRoute, '', 200)
    verify('GET', focusRoute + '&investor=foreign', '', 422)
    verify('GET', focusRoute + '&x=1', '', 422)
    verify('GET', focusRoute.replace('horizon=5', 'horizon=05'), '', 422)
    verify('GET', focusRoute, '{}', 422)
    verify('GET', focusRoute.replace('2026-10-06', '2026-10-05'), '', 200)
    const captureRoute = '/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-06'
    verify('POST', captureRoute, '{}', 409)
    focusProxyReady = true
    verify('POST', captureRoute, '{}', 200)
    verify('POST', captureRoute, 'null', 422)
    verify('POST', captureRoute, ' '.repeat(4097), 413)
    verify('POST', captureRoute.replace('3105', '5347'), '{}', 405)
    verify('GET', '/api/focus/price-saved?as_of=2026-10-06&min_lots=0', '', 405)
    invalidateFocusProxy()
    const slowTicket = focusProxyGeneration
    assert(focusRequestError('GET', new URL(focusRoute + '&unknown=1', 'http://owned.invalid'), Buffer.alloc(0)))
    invalidateFocusProxy()
    assert(!completeFocusProxy(slowTicket, true) && !focusProxyReady); gateChecks++
    verify('POST', captureRoute, '{}', 409)
    const currentTicket = focusProxyGeneration
    assert(completeFocusProxy(currentTicket, true)); verify('POST', captureRoute, '{}', 200)
    assert(completeFocusProxy(currentTicket, false) && !focusProxyReady && !completeFocusProxy(currentTicket, true)); gateChecks++
    verify('POST', captureRoute, '{}', 409)
    const App = await appSSRModule(false, true)
    const results = App
    const { QueryClient, QueryClientProvider } = requireDependency('@tanstack/react-query')
    const { MemoryRouter } = requireDependency('react-router-dom')
    for (const route of ['/', '/saved-price-chips-focus?' + query, helper.jointDetailPath('3105', conditions) + '&focus_horizon=5']) {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
      const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter, { initialEntries: [route] }, React.createElement(App.default))))
      if (route === '/') {
        const expected = '/saved-price-chips-focus?' + new URLSearchParams({ as_of: '2026-10-06', min_lots: '10000.000', day_move: 'all', min_turnover: '0', min_range_pct: '0.000', investor: 'foreign', horizon: '5', min_net_lots: '0.000' })
        assert(html.includes('href="' + expected.replaceAll('&', '&amp;') + '"') && html.includes('保存行情與法人條件關注：設定八條件'))
      } else assert(route.startsWith('/saved-price-chips-focus') ? html.includes('保存行情與法人條件關注') && html.includes('首次取得法人來源') : html.includes('未讀取來源'))
      ssrChecks++
      client.clear()
    }
    const data = tests.jointFixture()
    for (const item of [data, tests.jointFixture(tests.jointFixtureConditions({ min_net_lots: '1000000' }), data.price, data.institutional)]) {
      const html = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(results.SavedPriceChipsFocusResults, { data: item })))
      assert(item.count ? html.includes('3105') && html.includes('6488') && html.includes('交易日淨買賣超') : html.includes('零候選')); ssrChecks++
    }
    for (const cutoff of ['2026-10-05', '2026-10-07']) {
      const unavailable = { ...data, as_of: cutoff, status: 'unavailable', count: null, items: [], price: null, institutional: [], price_ready: false, chips_ready: false, capture_attempted: false, can_capture: false, reasons: ['joint_focus_cutoff_not_supported'] }
      const html = renderToStaticMarkup(React.createElement(results.SavedPriceChipsFocusResults, { data: unavailable }))
      assert(html.includes(`來源日期 ${cutoff} 不在本次範圍`) && html.includes('候選數未知') && !html.includes('零候選') && !html.includes('請明示重新讀取')); ssrChecks++
    }
    const fixtureBytes = tests.jointFixtureInputBytes(data)
    const fixtureGraph = tests.jointFixtureGraphBytes(data)
    assert(fixtureBytes <= 81920 && fixtureGraph <= 524288, `bounded new joint fixtures: ${fixtureBytes}/${fixtureGraph}`)
    assert(Object.values(counts).every((value) => value === 0), 'zero mutation/network guard counts')
    console.log(JSON.stringify({ passed: true, new_validator_parser_context_recovery_checks: checks, new_guard_checks: gateChecks, new_ssr_checks: ssrChecks,
      fixture_input_serialized_bytes: fixtureBytes, fixture_retained_graph_estimated_bytes: fixtureGraph, max_serialized_bytes: 81920, max_graph_estimated_bytes: 524288,
      largest_shared_fixture_branch_graph_estimated_bytes: tests.largestJointFixtureGraphBytes, fixture_graph_estimate: 'explicitly interned immutable object/string payloads once; every property slot counted; not RSS or peak',
      old_test_suites_run: 0, known_react_router_ssr_useLayoutEffect_warnings: knownSSRWarnings, ...receipt() }))
    return
  }
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

async function checkEventRange() {
  const App = await appSSRModule()
  const { QueryClient, QueryClientProvider } = requireDependency('@tanstack/react-query')
  const { MemoryRouter } = requireDependency('react-router-dom')
  const price = require(path.join(sourceRoot, 'priceFocus.ts'))
  let helperChecks = 0, responseChecks = 0, ssrChecks = 0, proxyChecks = 0, apiChecks = 0
  const verify = (kind, value, message) => {
    if (kind === 'helper') helperChecks++
    else if (kind === 'response') responseChecks++
    else if (kind === 'ssr') ssrChecks++
    else if (kind === 'proxy') proxyChecks++
    else apiChecks++
    assert(value, message)
  }
  const query = new URLSearchParams({ as_of: '2026-10-08', q: '', from: '2026-10-22', to: '2026-10-22' })
  const conditions = App.officialEventConditions(query)
  for (const [value, expected] of [['2026-10-22', true], ['2024-02-29', true], ['2026-02-29', false], ['2026-2-01', false], ['', false], ['0000-01-01', false], ['２０２６-10-22', false], ['2026-10-22T00:00:00Z', false]]) verify('helper', App.validOfficialEventDate(value) === expected, 'canonical ASCII calendar dates')
  for (const tail of ['&from=2026-10-22', '&to=2026-10-22', '&as_of=2026-10-08', '&q=x', '&next=https://outside.invalid']) verify('helper', App.officialEventConditions(new URLSearchParams(query + tail)) === null, 'duplicates and unknown conditions refused')
  verify('helper', App.officialEventConditions(new URLSearchParams('as_of=2026-10-08&from=&to=2026-10-22')) === null, 'explicit empty date refused')
  verify('helper', App.officialEventConditions(new URLSearchParams('as_of=2026-10-08&from=2026-10-23&to=2026-10-22')) === null, 'reversed range refused')
  const shared = new URLSearchParams(query)
  for (const [key, value] of Object.entries({ min_lots: '0.000', day_move: 'all', min_turnover: '0', min_range_pct: '0.000' })) shared.set(key, value)
  verify('helper', App.officialEventConditions(shared) !== null && price.validPriceFocusParams(shared), 'existing price and event queries coexist')
  const submitted = App.officialEventSubmissionParams(shared, '2026-10-08', '　元大~!()*股份　', '2026-10-01', '2026-12-31')
  verify('helper', submitted.get('q') === '元大~!()*股份' && submitted.get('min_lots') === '0.000' && shared.get('q') === '', 'submission strips q and preserves current price keys without mutating drafts')
  const noSearch = App.officialEventSubmissionParams(submitted, '2026-10-08', '', submitted.get('from'), submitted.get('to'))
  verify('helper', !noSearch.has('q') && noSearch.get('from') === '2026-10-01' && noSearch.get('to') === '2026-12-31', 'clear search preserves range')
  const noDates = App.officialEventSubmissionParams(submitted, '2026-10-08', submitted.get('q'), '', '')
  verify('helper', !noDates.has('from') && !noDates.has('to') && noDates.get('q') === submitted.get('q') && noDates.get('min_lots') === '0.000', 'clear range preserves cutoff search and price')
  verify('helper', App.officialEventSubmissionParams(shared, '2026-10-08', 'a'.repeat(101), '', '') === null, 'query length before normalization')
  const duplicatePrice = new URLSearchParams(shared); duplicatePrice.append('min_lots', '0.000')
  verify('helper', App.officialEventConditions(duplicatePrice) === null && !price.validPriceFocusParams(duplicatePrice), 'shared price multiplicity remains enforced')
  const invalidPriceRange = new URLSearchParams(shared); invalidPriceRange.set('from', '2026-10-23')
  verify('helper', !price.validPriceFocusParams(invalidPriceRange), 'shared event dates fail before price request')

  const fixture = (search = '') => {
    const detail = new URLSearchParams({ as_of: conditions.asOf, from: 'official-events', focus_q: search, focus_as_of: conditions.asOf, focus_from: conditions.from, focus_to: conditions.to })
    return { version: 'official-event-focus/p3-v1', status: 'available', reasons: [], as_of: conditions.asOf,
      observed_date: '2026-10-08', cutoff_basis: 'observed_taipei_date_inclusive', capture_enabled: true, can_capture: true, cache_present: true, capture_action: 'cached',
      storage: 'memory_only', durable_capture: false, historical_pit: 'unsupported', source_url_kind: 'feed', published_time: 'unknown', first_availability: 'unknown', revision_history: 'unknown',
      coverage: 'observed_feed_only', research_conditions: 'unknown', effective_from: conditions.from, effective_to: conditions.to,
      candidate_count: 4, selected_count: 4, validation_scope: 'all_observed_identity_dates_classification', total: 3, range_event_count: 1, range_matched: 1, matched: 1, displayed: 1, truncated: false, limit: 100, order: 'symbol_lexicographic', search_query: search,
      provenance: { source_id: 'twse_twt48u_all', source_version: 'twse-twt48u-all-d011-2026-09-12', endpoint: 'https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL', registry_version: 'r1-a1-c009-2026-09-12.1', manifest_digest: 'sha256:eb6c290d7716300c4117bb2cdc61a66cbf8d62e344870928933b44b77461f87b', body_sha256: 'a'.repeat(64), receipt_sha256: 'b'.repeat(64), captured_at: '2026-10-08T01:00:01+00:00', request_started_at: '2026-10-08T01:00:00+00:00', storage: 'memory_only', verification: 'local_evidence_consistent' },
      attribution: { owner: { name: '臺灣證券交易所', type: 'official_exchange' }, dataset_id: 'data-gov-89748', source_id: 'twse_twt48u_all', source_url: 'https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL', terms: { status: 'known', value: 'Open Government Data License v1.0', reason: 'synthetic contract fixture' }, evidence: [{ url: 'https://data.gov.tw/license', checked_at: '2026-09-12', claim: 'synthetic fixture' }], purpose_evidence: {} }, limitations: ['not_complete_history', 'not_a_ranking'],
      items: [{ exchange: 'TWSE', symbol: '0056', company_name: '元大~!()*股份', stock_page_available: true, detail_url: '/stocks/TWSE/0056?' + detail, research_conditions: 'unknown', events: [{ exchange: 'TWSE', symbol: '0056', company_name: '元大~!()*股份', event_date: '2026-10-22', source_date: '1151022', source_classification: '息', event_date_role: 'effective_date', event_date_precision: 'date', kind: 'ex_dividend', label: '除息', row_ordinal: 1, published_at: null, first_available_at: null, revision_available_at: null, availability: 'unknown' }] }] }
  }
  const value = fixture()
  verify('response', App.validOfficialEventFocus(value, conditions), 'fresh whole-feed response fits effective boundary')
  const special = fixture('元大~!()*股份')
  // Python urlencode leaves ~ unescaped and escapes !()*; both encode one value.
  special.items[0].detail_url = special.items[0].detail_url.replace(/%7E/gi, '~')
  verify('response', App.validOfficialEventFocus(special, { ...conditions, q: special.search_query }), 'Python URL encoding and Unicode accepted by exact semantic validation')
  const detailParams = new URL(special.items[0].detail_url, 'https://local.invalid').searchParams
  detailParams.set('as_of', '2026-10-07')
  const back = App.officialEventFocusReturnPath(detailParams)
  const backQuery = new URL(back, 'https://local.invalid').searchParams
  verify('helper', backQuery.get('as_of') === '2026-10-08' && backQuery.get('q') === special.search_query && backQuery.get('from') === conditions.from && backQuery.get('to') === conditions.to, 'detail cutoff change returns original four conditions')
  for (const tail of ['&focus_from=2026-10-22', '&focus_to=2026-10-22', '&from=official-events', '&focus_q=x', '&focus_as_of=2026-10-08', '&return=//outside.invalid', '&next=//outside.invalid']) verify('helper', App.officialEventFocusReturnPath(new URLSearchParams(detailParams + tail)) === null, 'return cannot accept duplicates or arbitrary destination')
  const legacy = new URLSearchParams({ as_of: '2026-10-08', from: 'official-events', focus_as_of: '2026-10-08', focus_q: '0056' })
  verify('helper', App.officialEventFocusReturnPath(legacy) === '/?as_of=2026-10-08&q=0056#official-event-focus-title', 'legacy no-range links remain valid')
  for (const mutate of [v => v.effective_from = '2026-10-01', v => v.total = null, v => v.range_event_count = 0, v => v.matched = 101, v => v.items[0].events[0].event_date = '2026-10-23', v => v.items[0].events[0].source_classification = 'unknown', v => v.items[0].detail_url += '&next=//outside.invalid', v => v.items[0].detail_url += '&focus_to=2026-10-22', v => v.items[0].detail_url = 'https://outside.invalid' + v.items[0].detail_url, v => v.items[0].detail_url += '#outside', v => v.provenance.body_sha256 = 'bad', v => v.provenance.captured_at = '2026-10-09T01:00:00Z']) {
    const invalid = structuredClone(value); mutate(invalid)
    verify('response', !App.validOfficialEventFocus(invalid, conditions), 'invalid response masked')
  }
  const zero = structuredClone(value)
  Object.assign(zero, { items: [], range_event_count: 0, range_matched: 0, matched: 0, displayed: 0 })
  verify('response', App.validOfficialEventFocus(zero, conditions), 'valid zero retains source counts and provenance')
  const empty = structuredClone(zero); Object.assign(empty, { total: 0, candidate_count: 0, selected_count: 0 })
  const failed = structuredClone(zero)
  Object.assign(failed, { status: 'unavailable', total: 0, candidate_count: 0, selected_count: 0, provenance: null, attribution: null, observed_date: null, cache_present: false, can_capture: false, capture_action: 'failed', reasons: ['event_evidence_invalid'] })
  verify('response', App.validOfficialEventFocus(failed, conditions), 'sealed failure has clear cards counts and provenance')
  const render = (data, params = query, failure = false, seedConditions = conditions, stock = false) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } })
    const key = ['official-event-focus', seedConditions.asOf, seedConditions.q, seedConditions.from, seedConditions.to]
    client.setQueryData(key, data)
    if (failure) client.getQueryCache().find({ queryKey: key }).setState({ status: 'error', error: new Error('synthetic refetch failure') })
    let entry = '/?' + params, component = App.OfficialEventFocusPanel
    if (stock) {
      const identity = { exchange: 'TWSE', symbol: '0056', name: 'Synthetic route identity', instrument_type: 'unknown', currency: 'unknown' }
      client.setQueryData(['stock', 'TWSE', '0056', params.get('as_of')], { instrument: identity, bars: [], features: {}, chips: [], groups: [], news: [], events: [], corporate_actions: [], fundamentals: [], data_quality: [], signals: [], strategy_conditions: {}, decision_summary: null })
      entry = '/stocks/TWSE/0056?' + params; component = App.default
    }
    try { return renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter, { initialEntries: [entry] }, React.createElement(component)))) }
    finally { client.clear() }
  }
  const html = render(value)
  verify('ssr', html.includes('class="focus-card"') && html.includes('生效日起日') && html.includes('生效日迄日') && html.includes('focus_from=2026-10-22'), 'current panel date controls and range drilldown rendered')
  verify('ssr', render(zero).includes('沒有符合日期與搜尋條件') && render(empty).includes('本次官方原件為零筆'), 'zero range and empty original have distinct copy')
  for (const [data, error] of [[failed, false], [value, true], [{ ...value, effective_to: '2026-10-23' }, false]]) {
    const hidden = render(data, query, error)
    verify('ssr', !hidden.includes('class="focus-card"') && !hidden.includes('class="focus-count"'), 'failure never renders stale cards or counts')
  }
  const changed = new URLSearchParams(query); changed.set('from', '2026-10-21')
  verify('ssr', !render(value, changed).includes('class="focus-card"'), 'full four-condition cache key excludes prior range')
  verify('ssr', render(value, shared).includes('class="focus-card"'), 'event panel still works on existing price homepage')
  verify('ssr', render(value, detailParams, false, conditions, true).includes('official-event-focus-title'), 'actual stock route return preserves original event conditions after cutoff change')

  const fetched = [], originalFetch = global.fetch
  global.fetch = async (url, options) => { fetched.push({ url, options }); return { ok: true, json: async () => value } }
  try {
    await App.getOfficialEventFocus(conditions.asOf, '元大~!()*股份', conditions.from, conditions.to)
    await App.captureOfficialEventFocus(conditions.asOf, '元大~!()*股份', conditions.from, conditions.to)
  } finally { global.fetch = originalFetch }
  for (const [index, request] of fetched.entries()) {
    const url = new URL(request.url, 'https://local.invalid')
    verify('api', url.pathname === '/api/focus/official-events' + (index ? '/capture' : '') && [...url.searchParams.keys()].sort().join(',') === 'as_of,from,q,to' && url.searchParams.get('q') === '元大~!()*股份' && url.searchParams.get('from') === conditions.from && url.searchParams.get('to') === conditions.to, 'GET and POST carry only full event conditions')
    if (index) verify('api', request.options.method === 'POST' && request.options.body === '{}', 'explicit capture uses empty JSON only')
  }
  for (const [method, route, tail, body, status] of [
    ['POST', '/api/focus/official-events/capture', query.toString(), '{}', null],
    ['POST', '/api/stocks/TWSE/0056/official-events/capture', 'as_of=2026-10-08', '{}', null],
    ['GET', '/api/focus/official-events', query.toString(), '', null],
    ['GET', '/api/focus/official-events', query + '&from=2026-10-22', '', 422],
    ['POST', '/api/focus/official-events/capture', 'as_of=2026-10-07', '{}', 422],
    ['POST', '/api/focus/official-events/capture', query.toString(), '{"extra":1}', 422],
    ['POST', '/api/focus/price-lots/capture', '', '{}', 405],
    ['POST', '/api/stocks/TWSE/0056/prices/save', '', '{}', 405],
    ['GET', '/api/stocks/TWSE/0056/prices/saved', '', '', 405],
    ['GET', '/api/focus/official-events', query.toString(), 'x', 422],
  ]) {
    const error = eventRangeRequestError(method, new URL(route + '?' + tail, 'https://local.invalid'), Buffer.from(body))
    verify('proxy', (error?.[0] ?? null) === status, 'event proxy exact route query and body boundary')
  }
  verify('proxy', eventRangeRequestError('POST', new URL('/api/focus/official-events/capture?' + query, 'https://local.invalid'), Buffer.alloc(4097))[0] === 413, 'request body quota enforced')
  return { helper_checks: helperChecks, response_checks: responseChecks, ssr_checks: ssrChecks, api_checks: apiChecks, proxy_checks: proxyChecks, fixture_bytes: Buffer.byteLength(JSON.stringify(value)) }
}

const requests = { api_get: 0, api_post: 0, rejected: 0 }
const json = (response, status, value) => { response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' }); response.end(JSON.stringify(value)) }
function eventRangeStaticError(method, pathname) {
  const focus = pathname === '/api/focus/official-events', capture = pathname === '/api/focus/official-events/capture'
  const selectedCapture = /^\/api\/stocks\/TWSE\/[0-9A-Z]{4,6}\/official-events\/capture$/.test(pathname)
  const detail = /^\/api\/stocks\/TWSE\/[0-9A-Z]{4,6}(?:\/overview)?$/.test(pathname)
  if (method === 'POST' && (capture || selectedCapture) || method === 'GET' && (focus || detail || pathname === '/api/dashboard')) return null
  return [405, 'event_range_operation_outside_scope']
}
function eventRangeRequestError(method, url, body) {
  const refused = eventRangeStaticError(method, url.pathname)
  if (refused) return refused
  if (body.length > 4096) return [413, 'event_range_request_body_bound']
  if (method === 'GET' && body.length) return [422, 'event_range_get_body_forbidden']
  try {
    if (method === 'POST') {
      const value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(body))
      if (!value || Array.isArray(value) || typeof value !== 'object' || Object.keys(value).length) throw new Error('empty object required')
    }
    const pairs = [...url.searchParams], keys = pairs.map(([key]) => key), values = Object.fromEntries(pairs)
    if (new Set(keys).size !== keys.length) throw new Error('duplicate query')
    const focus = url.pathname.startsWith('/api/focus/official-events')
    const allowed = focus ? ['as_of', 'q', 'from', 'to'] : url.pathname === '/api/dashboard' ? [] : ['as_of']
    if (keys.some((key) => !allowed.includes(key)) || (focus || method === 'POST') && !keys.includes('as_of')) throw new Error('query keys')
    const validDate = value => /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value) && !value.startsWith('0000-') && Number.isFinite(Date.parse(value + 'T00:00:00Z')) && new Date(value + 'T00:00:00Z').toISOString().slice(0, 10) === value
    if (['as_of', 'from', 'to'].some(key => keys.includes(key) && !validDate(values[key])) || keys.includes('from') && keys.includes('to') && values.from > values.to || Array.from(values.q ?? '').length > 100) throw new Error('date or search conditions')
    if (method === 'POST' && values.as_of !== '2026-10-08') throw new Error('fresh observation cutoff')
    return null
  } catch { return [422, 'event_range_request_conditions_invalid'] }
}
function scope6StaticError(method, pathname) {
  if (!['GET', 'POST'].includes(method) || method === 'POST' && pathname !== '/api/focus/price-lots/capture' && !/^\/api\/stocks\/TPEx\/(3105|3293|5274|5347|6223|6488|6510|8069)\/prices\/capture$/.test(pathname)) return [405, 'scope6_operation_outside_scope']
  if (['/prices/save', '/prices/saved', '/focus/price-saved'].some((value) => pathname.includes(value))) return [405, 'scope6_private_reader_outside_scope']
  return null
}
function scope6RequestError(method, url, body) {
  const refused = scope6StaticError(method, url.pathname)
  if (refused) return refused
  if (method === 'GET' && body.length) return [422, 'scope6_get_body_forbidden']
  if (body.length > 4096) return [413, 'scope6_request_body_bound']
  try {
    if (method === 'POST') {
      if (!body.length) throw new Error('empty object required')
      const value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(body))
      if (!value || Array.isArray(value) || typeof value !== 'object' || Object.keys(value).length) throw new Error('empty object required')
    }
    const pairs = [...url.searchParams], keys = pairs.map(([key]) => key), values = Object.fromEntries(pairs)
    if (new Set(keys).size !== keys.length) throw new Error('duplicates')
    const isFocus = ['/api/focus/price-lots', '/api/focus/price-lots/capture'].includes(url.pathname)
    const isStock = url.pathname.startsWith('/api/stocks/')
    if (isFocus) {
      const allowed = ['as_of', 'min_lots', 'day_move', 'min_turnover', 'min_range_pct']
      const required = values.as_of === '2026-10-07' ? allowed : ['as_of', 'min_lots']
      const helper = require(path.join(sourceRoot, 'priceFocus.ts'))
      if (keys.some((key) => !allowed.includes(key)) || required.some((key) => !keys.includes(key)) || helper.minLotsShares(values.min_lots) === null
        || !helper.validPriceFocusDayMove(values.day_move ?? 'all') || helper.minTurnoverValue(values.min_turnover ?? '0') === null || helper.minRangeMilliPct(values.min_range_pct ?? '0') === null) throw new Error('focus conditions')
    } else if (isStock) {
      if (keys.some((key) => key !== 'as_of') || method === 'POST' && !keys.includes('as_of')) throw new Error('stock conditions')
    } else return null
    if (values.as_of !== undefined && !['2026-10-05', '2026-10-06', '2026-10-07'].includes(values.as_of) || method === 'POST' && values.as_of !== '2026-10-07') throw new Error('cutoff')
    return null
  } catch { return [422, 'scope6_request_conditions_invalid'] }
}
function jointStaticError(method, pathname) {
  if (pathname.endsWith('/prices/saved')) return [405, 'use_the_admitted_saved_focus_reader']
  if (method === 'POST' && !(scope7Mode ? /^\/api\/stocks\/TPEx\/(3105|3293|5274|5347|6488|6510|8069)\/institutional-windows\/capture$/ : /^\/api\/stocks\/TPEx\/(3105|6488)\/institutional-windows\/capture$/).test(pathname)) return [405, 'joint_post_outside_scope']
  if (!['GET', 'POST'].includes(method)) return [405, 'joint_method_outside_scope']
  return null
}
let focusProxyReady = false
let focusProxyGeneration = 0
function invalidateFocusProxy() { focusProxyGeneration++; focusProxyReady = false }
function completeFocusProxy(ticket, ready) {
  if (ticket !== focusProxyGeneration) return false
  if (ready) focusProxyReady = true
  else invalidateFocusProxy()
  return true
}
function focusRequestError(method, url, body) {
  if (url.pathname === focusAPIPath) {
    if (method !== 'GET') return [405, 'joint_focus_method_outside_scope']
    if (body.length) return [422, 'joint_focus_get_body_forbidden']
    const helper = require(path.join(sourceRoot, 'savedPriceChipsFocus.ts'))
    return helper.jointParams(url.searchParams) ? null : [422, 'joint_focus_conditions_invalid']
  }
  if (url.pathname.startsWith('/api/focus/price-saved-chips') && url.pathname !== focusAPIPath) return [405, 'joint_focus_other_consumer_outside_scope']
  if (url.pathname === '/api/focus/price-saved') return [405, 'use_the_new_joint_focus_consumer']
  const refused = jointRequestError(method, url, body)
  if (refused) return refused
  if (method === 'POST' && !focusProxyReady) return [409, 'joint_focus_explicit_price_validation_required']
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
      if (!(scope7Mode ? /^\/api\/stocks\/TPEx\/(3105|3293|5274|5347|6488|6510|8069)\/institutional-windows\/capture$/ : /^\/api\/stocks\/TPEx\/(3105|6488)\/institutional-windows\/capture$/).test(url.pathname)) return [405, 'joint_post_outside_scope']
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
  if (eventRangeActive) {
    const refusedBeforeBody = eventRangeStaticError(request.method, url.pathname)
    if (refusedBeforeBody) { requests.rejected++; return json(response, refusedBeforeBody[0], { detail: refusedBeforeBody[1] }) }
    try { body = await boundedJointBody(request) } catch (error) { requests.rejected++; return json(response, error.status ?? 422, { detail: 'event_range_request_body_invalid' }) }
    const refused = eventRangeRequestError(request.method, url, body)
    if (refused) { requests.rejected++; return json(response, refused[0], { detail: refused[1] }) }
  } else if (stockScope6Active) {
    const refusedBeforeBody = scope6StaticError(request.method, url.pathname)
    if (refusedBeforeBody) { requests.rejected++; return json(response, refusedBeforeBody[0], { detail: refusedBeforeBody[1] }) }
    try { body = await boundedJointBody(request) } catch (error) { requests.rejected++; return json(response, error.status ?? 422, { detail: error.detail ?? 'scope6 body invalid' }) }
    const refused = scope6RequestError(request.method, url, body)
    if (refused) { requests.rejected++; return json(response, refused[0], { detail: refused[1] }) }
  } else if (jointActive) {
    const refusedBeforeBody = jointStaticError(request.method, url.pathname)
    if (refusedBeforeBody) { if (focusActive) invalidateFocusProxy(); requests.rejected++; return json(response, refusedBeforeBody[0], { detail: refusedBeforeBody[1] }) }
    try { body = await boundedJointBody(request) } catch (error) { if (focusActive) invalidateFocusProxy(); requests.rejected++; return json(response, error.status ?? 422, { detail: error.detail ?? 'joint body invalid' }) }
    const refused = (focusActive ? focusRequestError : jointRequestError)(request.method, url, body)
    if (refused) { if (focusActive) invalidateFocusProxy(); requests.rejected++; return json(response, refused[0], { detail: refused[1] }) }
  }
  const allowed = eventRangeActive || stockScope6Active || jointActive || request.method === 'GET' || (!args.includes('--saved-source-only') && request.method === 'POST' && (/^\/api\/stocks\/TPEx\/(?:3105|3293|5274|5347|6488|6510|8069)\/prices\/(?:capture|save)$/.test(url.pathname) || url.pathname === '/api/focus/price-lots/capture'))
  if (!allowed) { requests.rejected++; return json(response, 405, { detail: 'outside preview operation' }) }
  requests[request.method === 'POST' ? 'api_post' : 'api_get']++
  if (focusActive && url.pathname === focusAPIPath) invalidateFocusProxy()
  const focusTicket = focusProxyGeneration
  const upstream = approvedRequest({ hostname: '127.0.0.1', port: apiPort, path: request.url, method: request.method,
    headers: { 'Content-Type': 'application/json' }, agent: false }, (incoming) => {
    if (focusActive && url.pathname === focusAPIPath) {
      const chunks = []; let total = 0
      incoming.on('data', (part) => { total += part.length; if (total > 8 * 1024 * 1024) { incoming.destroy(); response.destroy() } else chunks.push(part) })
      incoming.on('end', () => {
        const raw = Buffer.concat(chunks)
        try {
          const helper = require(path.join(sourceRoot, 'savedPriceChipsFocus.ts')), conditions = helper.jointParams(url.searchParams), data = JSON.parse(raw.toString('utf8'))
          completeFocusProxy(focusTicket, incoming.statusCode === 200 && conditions !== null && helper.validJointFocus(data, conditions, calendarMode, scope7Mode) && data.price_ready)
        } catch { if (focusTicket === focusProxyGeneration) invalidateFocusProxy() }
        response.writeHead(incoming.statusCode, { 'Content-Type': incoming.headers['content-type'] || 'application/json; charset=utf-8' }); response.end(raw)
      })
      return
    }
    if (focusActive && incoming.statusCode >= 400) completeFocusProxy(focusTicket, false)
    incoming.on('error', () => { if (focusActive) completeFocusProxy(focusTicket, false) })
    response.writeHead(incoming.statusCode, { 'Content-Type': incoming.headers['content-type'] || 'application/json; charset=utf-8' })
    let total = 0
    const sourceChunks = focusActive && /\/prices\/saved|\/institutional-windows(?:\/capture)?$/.test(url.pathname) ? [] : null
    incoming.on('data', (part) => { total += part.length; if (total > 8 * 1024 * 1024) { if (focusActive) completeFocusProxy(focusTicket, false); incoming.destroy(); response.destroy() } else sourceChunks?.push(part) })
    incoming.on('end', () => {
      if (sourceChunks) {
        try { if (JSON.parse(Buffer.concat(sourceChunks).toString('utf8')).status !== 'available') completeFocusProxy(focusTicket, false) }
        catch { completeFocusProxy(focusTicket, false) }
      }
    })
    incoming.pipe(response)
  })
  upstream.on('error', (error) => { if (focusActive && focusTicket === focusProxyGeneration) invalidateFocusProxy(); json(response, 502, { detail: error.message }) })
  if (eventRangeActive || jointActive || stockScope6Active) upstream.end(body)
  else {
    let length = 0
    request.on('data', (part) => { length += part.length; if (length > 4096) { request.destroy(); upstream.destroy() } })
    request.pipe(upstream)
  }
}
function previewBanner(newScope = stockScope6Active) {
  if (eventRangeActive) return '<div style="padding:8px;background:#573e18;color:#fff">官方事件日期範圍驗收：個股目錄僅為合成路由身分，本次官方事件由 ROOT 的新公開原件提供。目錄不證明普通股、價格、市場完整性或歷史可得性；原件僅留本程序記憶體。</div><div id="root">'
  return newScope
    ? '<div style="padding:8px;background:#573e18;color:#fff">受控驗收：八股操作目錄身分已核對。首次載入前沒有行情資料；只有本次明示取得且通過核對的官方單日行情可採用。來源日期與狀態可在個股詳情核對。</div><div id="root">'
    : '<div style="padding:8px;background:#573e18;color:#fff">受控驗收：所選普通股身分由統籌核對後建構記憶體操作目錄；既有行情與未支持標的仍為合成樣本。官方單日行情須經本次擷取或私有保存原件讀回核對後才採用；來源狀態可在個股詳情核對。</div><div id="root">'
}
async function serve() {
  const build = await esbuild.build({ entryPoints: [path.join(sourceRoot, 'main.tsx')], bundle: true, write: false,
    absWorkingDir: path.join(root, 'frontend'), nodePaths: [dependencies], outdir: '__memory_only__', platform: 'browser', format: 'esm',
    target: 'es2020', jsx: 'automatic', define: { 'import.meta.env.VITE_API_BASE': JSON.stringify('/api'), 'import.meta.env.VITE_CHIPS_SERIES_STOCK_SCOPE_7': JSON.stringify(''), 'import.meta.env.VITE_SAVED_PRICE_CHIPS_INTEGRATION': JSON.stringify(jointActive && !focusActive ? 'm1-v1' : ''), 'import.meta.env.VITE_SAVED_PRICE_CHIPS_FOCUS': JSON.stringify(focusActive && !calendarActive && !scope7Active ? 'm1-v1' : ''), 'import.meta.env.VITE_SAVED_PRICE_CHIPS_FOCUS_CALENDAR': JSON.stringify(calendarActive ? 'm1-v2' : ''), 'import.meta.env.VITE_SAVED_PRICE_CHIPS_FOCUS_STOCK_SCOPE_7': JSON.stringify(scope7Active ? 'm1-v1' : ''), 'process.env.NODE_ENV': JSON.stringify('development') } })
  const script = build.outputFiles.find((file) => file.path.endsWith('.js')).contents
  const css = build.outputFiles.find((file) => file.path.endsWith('.css')).text.replace(/@import\s+(?:url\([^)]*\)|["'][^"']*["'])\s*;/g, '')
  const html = fs.readFileSync(path.join(root, 'frontend/index.html'), 'utf8').replace('src="/src/main.tsx"', 'src="/app.js"')
    .replace('</head>', '<link rel="stylesheet" href="/app.css"></head>')
    .replace('<div id="root">', previewBanner())
  const server = http.createServer(async (request, response) => {
    response.setHeader('Cache-Control', 'no-store')
    response.setHeader('Content-Security-Policy', "default-src 'self' data:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; font-src 'self' data:")
    const url = new URL(request.url, `http://127.0.0.1:${port}`)
    try {
      if (stockScope6Active) {
        const refused = scope6StaticError(request.method, url.pathname)
        if (refused) { requests.rejected++; return json(response, refused[0], { detail: refused[1] }) }
      }
      if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/__price_validation/')) return await proxy(request, response)
      if (url.pathname === '/__price_ui/receipt') return json(response, 200, { requests, ...receipt() })
      if (request.method !== 'GET') return json(response, 405, { detail: 'read-only UI' })
      if (url.pathname === '/app.js') { response.writeHead(200, { 'Content-Type': 'text/javascript; charset=utf-8' }); response.end(script) }
      else if (url.pathname === '/app.css') { response.writeHead(200, { 'Content-Type': 'text/css; charset=utf-8' }); response.end(css) }
      else { response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }); response.end(html) }
    } catch (error) { json(response, 500, { detail: error.message }) }
  })
  server.listen(port, '127.0.0.1', () => console.log(JSON.stringify({ mode: 'full App + root-owned actual API proxy', port, api_port: apiPort,
    url: eventRangeActive ? `http://127.0.0.1:${port}/?as_of=2026-10-08&from=2026-10-01&to=2026-12-31` : stockScope6Active ? `http://127.0.0.1:${port}/?as_of=2026-10-07&min_lots=0.000&day_move=all&min_turnover=0&min_range_pct=0.000` : `http://127.0.0.1:${port}/stocks/TPEx/3105?as_of=2026-10-02`, official_event_range: eventRangeActive ? { contract: 'official-event-focus/p3-v1', capture_as_of: '2026-10-08', catalogue: 'synthetic routing identity only' } : null, stock_scope6: stockScope6Active ? { version: stockScope6Version, digest: stockScope6Digest } : null, ...receipt() })))
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
