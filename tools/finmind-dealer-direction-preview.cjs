'use strict'
// Independent memory preview for the Issue 9 dealer self/hedging direction-combos page.
// Never opens a financial transport itself: --check is offline (no listener, no socket, no resolver) and --serve
// only serves the bundle and proxies the two admitted calls to this process' own local API port.
// The external policy pin is supplied as parameters; nothing about it is hard-coded here.
const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const childProcess = require('node:child_process')
const net = require('node:net')
const http = require('node:http')
const dns = require('node:dns')
const crypto = require('node:crypto')
const assert = require('node:assert/strict')
const root = path.resolve(__dirname, '..')
const args = process.argv.slice(2)
const allowed = new Set(['--check', '--check-ui-only', '--serve', '--chips-dealer-direction-combos-opt-in', '--policy-sha256', '--policy-bytes', '--policy-file', '--deps', '--api-port', '--port'])
const optionNames = new Set(['--policy-sha256', '--policy-bytes', '--policy-file', '--deps', '--api-port', '--port'])
const seen = new Set(), options = new Map()
for (let i = 0; i < args.length; i++) {
  const name = args[i]
  assert(allowed.has(name) && !seen.has(name), 'unknown/duplicate runner option')
  seen.add(name)
  if (optionNames.has(name)) { assert(args[i + 1] && !args[i + 1].startsWith('--'), 'runner option value missing'); options.set(name, args[++i]) }
}
const serve = seen.has('--serve'), check = seen.has('--check')
assert(serve !== check, 'choose exactly --check or --serve')
assert(!seen.has('--check-ui-only') || check, '--check-ui-only requires --check')
assert(seen.has('--chips-dealer-direction-combos-opt-in'), 'explicit new frontend flag required')
const policySha = options.get('--policy-sha256'), policyBytes = Number(options.get('--policy-bytes'))
assert(/^[0-9a-f]{64}$/.test(policySha ?? '') && Number.isSafeInteger(policyBytes) && policyBytes > 0, 'external policy pin parameters required: --policy-sha256 and --policy-bytes')
const port = Number(options.get('--port') ?? 8800), apiPort = Number(options.get('--api-port') ?? 8799)
assert([port, apiPort].every((p) => Number.isInteger(p) && p >= 1024 && p <= 65535) && port !== apiPort, 'finite distinct local ports')
// R1-1: cross-site / DNS-rebinding guard. Pure over Node's flat rawHeaders because Node DISCARDS duplicate Host and Content-Type
// values in req.headers, which would hide a duplicated guard header. No CORS header is ever emitted, so a cross-origin preflight fails.
const ownHost = '127.0.0.1:' + port, ownOrigin = 'http://' + ownHost, apiHost = '127.0.0.1:' + apiPort
function headerValues(rawHeaders, name) {
  const values = []
  for (let i = 0; i + 1 < rawHeaders.length; i += 2) if (rawHeaders[i].toLowerCase() === name) values.push(rawHeaders[i + 1])
  return values
}
function admitRequest(method, rawHeaders) {
  const host = headerValues(rawHeaders, 'host')
  if (host.length !== 1 || host[0] !== ownHost) return { status: 403, reason: 'host_not_admitted' }
  const site = headerValues(rawHeaders, 'sec-fetch-site')
  if (site.length && (site.length !== 1 || !['same-origin', 'none'].includes(site[0].toLowerCase()))) return { status: 403, reason: 'cross_site_rejected' }
  const origin = headerValues(rawHeaders, 'origin')
  if (origin.length && (origin.length !== 1 || origin[0] !== ownOrigin)) return { status: 403, reason: 'origin_not_admitted' }
  if (method === 'POST') {
    const type = headerValues(rawHeaders, 'content-type')
    if (type.length !== 1 || !/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(type[0].trim())) return { status: 415, reason: 'content_type_json_required' }
  }
  return null
}
function checkGate() {
  const good = ['Host', ownHost], n = { positive: 0, negative: 0 }
  const expectRule = (method, headers, expected, label) => {
    const got = admitRequest(method, headers)
    assert.deepEqual(got && got.reason, expected, label)
    n[expected ? 'negative' : 'positive']++
  }
  expectRule('GET', good, null, 'exact Host admitted')
  expectRule('GET', [...good, 'Origin', ownOrigin, 'Sec-Fetch-Site', 'same-origin'], null, 'own origin and same-origin admitted')
  expectRule('GET', [...good, 'Sec-Fetch-Site', 'none'], null, 'none admitted (address-bar navigation)')
  expectRule('POST', [...good, 'Content-Type', 'application/json'], null, 'JSON POST admitted')
  expectRule('POST', [...good, 'Content-Type', 'Application/JSON; charset=UTF-8', 'Origin', ownOrigin], null, 'JSON POST with charset admitted')
  for (const host of ['localhost:' + port, '127.0.0.1', '127.0.0.1:' + apiPort, '127.0.0.1:' + port + '.evil.example', 'evil.example', '[::1]:' + port, '127.0.0.1:0' + port, '']) expectRule('GET', ['Host', host], 'host_not_admitted', 'bad Host ' + host)
  expectRule('GET', [], 'host_not_admitted', 'missing Host')
  expectRule('GET', [...good, 'Host', 'evil.example'], 'host_not_admitted', 'duplicated Host')
  for (const value of ['cross-site', 'same-site', 'Cross-Site', '', 'unknown']) expectRule('GET', [...good, 'Sec-Fetch-Site', value], 'cross_site_rejected', 'Sec-Fetch-Site ' + value)
  expectRule('GET', [...good, 'Sec-Fetch-Site', 'same-origin', 'Sec-Fetch-Site', 'cross-site'], 'cross_site_rejected', 'duplicated Sec-Fetch-Site')
  for (const value of ['http://evil.example', 'null', 'http://localhost:' + port, 'http://127.0.0.1:' + apiPort, 'https://' + ownHost, ownOrigin + '/', '']) expectRule('GET', [...good, 'Origin', value], 'origin_not_admitted', 'Origin ' + value)
  expectRule('GET', [...good, 'Origin', ownOrigin, 'Origin', 'http://evil.example'], 'origin_not_admitted', 'duplicated Origin')
  for (const type of ['text/plain', 'text/plain;charset=UTF-8', 'application/x-www-form-urlencoded', 'multipart/form-data; boundary=x', 'application/json5', 'application/jsonx', 'application/json; charset=latin-1', 'application/json; boundary=x', '']) expectRule('POST', [...good, 'Content-Type', type], 'content_type_json_required', 'POST Content-Type ' + type)
  expectRule('POST', good, 'content_type_json_required', 'POST without Content-Type')
  expectRule('POST', [...good, 'Content-Type', 'application/json', 'Content-Type', 'text/plain'], 'content_type_json_required', 'duplicated Content-Type')
  expectRule('POST', [...good, 'Content-Type', 'text/plain', 'Origin', 'http://evil.example', 'Sec-Fetch-Site', 'cross-site'], 'cross_site_rejected', 'a foreign simple POST is refused before the body or the quota is considered')
  assert.equal(apiHost, '127.0.0.1:' + apiPort, 'forwarded Host is fixed')
  return n
}
const deps = path.resolve(options.get('--deps') ?? 'C:/Users/YiCheng/Desktop/taiwan-stock-research/frontend/node_modules')
const requireDeps = Module.createRequire(path.join(deps, '../package.json'))
const esbuildPackage = path.join(deps, '.pnpm/node_modules/esbuild')
const compiler = fs.realpathSync(require.resolve('@esbuild/' + process.platform + '-' + process.arch + '/esbuild.exe', { paths: [esbuildPackage] }))
const counts = { disk_writes: 0, private_reads: 0, network_rejections: 0, subprocess_rejections: 0, proxy_get: 0, proxy_post: 0, rejected_requests: 0 }
const children = []
const originalSpawn = childProcess.spawn
childProcess.spawn = function (command, childArgs, opts) {
  if (fs.realpathSync(command) !== compiler || children.length || !Array.isArray(childArgs) || !childArgs.some((s) => /^--service=/.test(s)) || childArgs.some((s) => !/^--service=/.test(s) && s !== '--ping')) {
    counts.subprocess_rejections++; throw new Error('subprocess outside one borrowed esbuild')
  }
  const child = originalSpawn.call(this, command, childArgs, opts)
  children.push(child)
  console.log(JSON.stringify({ esbuild_pid: child.pid, parent_pid: process.pid, compiler }))
  child.once('exit', (code, signal) => console.log(JSON.stringify({ esbuild_exit: true, code, signal })))
  return child
}
for (const name of ['spawnSync', 'exec', 'execSync', 'execFile', 'execFileSync', 'fork']) childProcess[name] = () => { counts.subprocess_rejections++; throw new Error('subprocess rejected') }
function denyWrite() { counts.disk_writes++; throw new Error('filesystem mutation rejected') }
for (const name of ['writeFile', 'writeFileSync', 'appendFile', 'appendFileSync', 'mkdir', 'mkdirSync', 'mkdtemp', 'mkdtempSync', 'rename', 'renameSync', 'unlink', 'unlinkSync', 'rm', 'rmSync', 'rmdir', 'rmdirSync', 'copyFile', 'copyFileSync', 'cp', 'cpSync', 'truncate', 'truncateSync', 'ftruncate', 'ftruncateSync', 'chmod', 'chmodSync', 'chown', 'chownSync', 'utimes', 'utimesSync', 'link', 'linkSync', 'symlink', 'symlinkSync', 'createWriteStream', 'write', 'writeSync', 'writev', 'writevSync']) fs[name] = denyWrite
for (const name of ['writeFile', 'appendFile', 'mkdir', 'mkdtemp', 'rename', 'unlink', 'rm', 'rmdir', 'copyFile', 'cp', 'truncate', 'chmod', 'chown', 'utimes', 'link', 'symlink']) fs.promises[name] = denyWrite
function readGate(filename) {
  if (typeof filename === 'number') return
  const normalized = path.resolve(String(filename)).replace(/\\/g, '/').toLowerCase()
  if (normalized.includes('/appdata/local/taiwan-stock-research/')) { counts.private_reads++; throw new Error('private read forbidden') }
}
for (const name of ['readFile', 'readFileSync', 'createReadStream']) {
  const original = fs[name]
  fs[name] = function (filename, ...rest) { readGate(filename); return original.call(this, filename, ...rest) }
}
for (const name of ['open', 'openSync']) {
  const original = fs[name]
  fs[name] = function (filename, flags, ...rest) {
    readGate(filename)
    if (flags !== 'r' && flags !== 'rs' && !(typeof flags === 'number' && !(flags & (fs.constants.O_WRONLY | fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_TRUNC | fs.constants.O_APPEND)))) return denyWrite()
    return original.call(this, filename, flags, ...rest)
  }
}
const promiseOpen = fs.promises.open.bind(fs.promises), promiseRead = fs.promises.readFile.bind(fs.promises)
fs.promises.open = async (filename, flags = 'r', ...rest) => { readGate(filename); if (flags !== 'r') return denyWrite(); return promiseOpen(filename, flags, ...rest) }
fs.promises.readFile = async (filename, ...rest) => { readGate(filename); return promiseRead(filename, ...rest) }
function denyNetwork() { counts.network_rejections++; throw new Error('network outside own local API/preview rejected') }
const originalLookup = dns.lookup
dns.lookup = function (hostname, ...rest) { if (!serve || hostname !== '127.0.0.1') return denyNetwork(); return originalLookup.call(this, hostname, ...rest) }
for (const name of ['resolve', 'resolve4', 'resolve6', 'reverse']) dns[name] = denyNetwork
const originalConnect = net.Socket.prototype.connect
net.Socket.prototype.connect = function (...connectArgs) {
  const first = connectArgs[0]
  const opt = Array.isArray(first) ? first[0] : first
  const host = opt && typeof opt === 'object' ? opt.host : connectArgs[1]
  const targetPort = opt && typeof opt === 'object' ? Number(opt.port) : Number(opt)
  if (!serve || host !== '127.0.0.1' || targetPort !== apiPort) return denyNetwork()
  return originalConnect.apply(this, connectArgs)
}
const originalListen = net.Server.prototype.listen
net.Server.prototype.listen = function (listenPort, host, ...rest) {
  if (!serve || listenPort !== port || host !== '127.0.0.1') return denyNetwork()
  return originalListen.call(this, listenPort, host, ...rest)
}
const ts = requireDeps('typescript')
const esbuild = require(esbuildPackage)
const sourceRoot = path.join(root, 'frontend/src')
const dependencySource = path.resolve(deps, '../src')
const originalResolve = Module._resolveFilename
Module._resolveFilename = function (request, parent, ...rest) {
  try { return originalResolve.call(this, request, parent, ...rest) }
  catch (error) { if (error.code !== 'MODULE_NOT_FOUND' || request.startsWith('.') || path.isAbsolute(request)) throw error; return requireDeps.resolve(request) }
}
Module._extensions['.css'] = () => {}
function typecheck() {
  const filename = path.join(root, 'frontend/tsconfig.app.json')
  const config = ts.readConfigFile(filename, ts.sys.readFile)
  assert(!config.error, 'read TypeScript config')
  const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, path.dirname(filename))
  const compilerOptions = { ...parsed.options, noEmit: true, incremental: false, composite: false }
  const host = ts.createCompilerHost(compilerOptions)
  host.writeFile = denyWrite
  host.resolveModuleNames = (names, containing) => {
    const relative = path.relative(sourceRoot, path.resolve(containing))
    const own = !relative.startsWith('..') && !path.isAbsolute(relative)
    return names.map((name) => ts.resolveModuleName(name, name.startsWith('.') || !own ? containing : path.join(dependencySource, path.basename(containing)), compilerOptions, host).resolvedModule)
  }
  const program = ts.createProgram(parsed.fileNames, compilerOptions, host)
  const diagnostics = [...parsed.errors, ...ts.getPreEmitDiagnostics(program)]
  if (diagnostics.length) {
    console.error(ts.formatDiagnosticsWithColorAndContext(diagnostics.slice(0, 12), { getCanonicalFileName: (f) => f, getCurrentDirectory: () => root, getNewLine: () => '\n' }))
    throw new Error('TypeScript diagnostics ' + diagnostics.length)
  }
  console.log(JSON.stringify({ typecheck: 'current full src noEmit', source_files: parsed.fileNames.length }))
}
function definitions(extra = {}) {
  const base = {
    'import.meta.env.VITE_API_BASE': JSON.stringify('/api'),
    'import.meta.env.VITE_CHIPS_DEALER_DIRECTION_COMBOS_STOCK_SCOPE_7': JSON.stringify('m1-v1'),
    'import.meta.env.VITE_CHIPS_DEALER_DIRECTION_COMBOS_POLICY_SHA256': JSON.stringify(policySha),
    'import.meta.env.VITE_CHIPS_DEALER_COMPONENTS_STOCK_SCOPE_7': JSON.stringify(''),
    'import.meta.env.VITE_CHIPS_ADJACENT_STOCK_SCOPE_7': JSON.stringify(''),
    'import.meta.env.VITE_CHIPS_DIRECTION_STOCK_SCOPE_7': JSON.stringify(''),
    'import.meta.env.VITE_CHIPS_SERIES_STOCK_SCOPE_7': JSON.stringify(''),
    'import.meta.env.VITE_CHIPS_GROSS_STOCK_SCOPE_7': JSON.stringify(''),
    'import.meta.env.VITE_SAVED_PRICE_CHIPS_INTEGRATION': JSON.stringify(''),
    'import.meta.env.VITE_SAVED_PRICE_CHIPS_FOCUS': JSON.stringify(''),
    'import.meta.env.VITE_SAVED_PRICE_CHIPS_FOCUS_CALENDAR': JSON.stringify(''),
    'import.meta.env.VITE_SAVED_PRICE_CHIPS_FOCUS_STOCK_SCOPE_7': JSON.stringify(''),
  }
  return { ...base, ...extra }
}
// A web font @import would be an external fetch; remove it (the parenthesised URL up to its closing parenthesis).
function stripFontImports(css) {
  return css.replace(/@import\s+url\([^)]*\)\s*;/gi, '')
}
function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']'
  if (value !== null && typeof value === 'object') return '{' + Object.keys(value).sort().map((key) => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}'
  return JSON.stringify(value).replace(/[\u007f-\uffff]/g, (c) => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'))
}
function checkPolicyFile() {
  if (!seen.has('--policy-file')) return { policy_file: false }
  const raw = fs.readFileSync(path.resolve(options.get('--policy-file')))
  assert(raw.length === policyBytes && crypto.createHash('sha256').update(raw).digest('hex') === policySha, 'independent canonical policy pin check')
  const text = raw.toString('utf8'), parsed = JSON.parse(text)
  assert(canonical(parsed) === text && parsed.version === 'issue9-dealer-direction-combos-finmind-v2' && parsed.lease === 'held until process exit' && parsed.issue === 9, 'policy file is canonical and is the issue 9 policy')
  return { policy_file: true, policy_file_bytes: raw.length }
}
async function buildSSR(extra) {
  const entry = [
    "export * from './chipsDealerDirectionCombos.test'",
    "export { default as App } from './App'",
    "export { ComboSummary, ComboDaily, ComboSegments, ComboCombinations, ComboEvidence, ComboCalendar } from './ChipsDealerDirectionCombosPage'",
  ].join('\n')
  const result = await esbuild.build({ stdin: { contents: entry, resolveDir: sourceRoot, loader: 'ts' }, bundle: true, write: false, platform: 'node', format: 'cjs', target: 'es2020', jsx: 'automatic', nodePaths: [deps], external: ['react', 'react/*', 'react-dom', 'react-dom/*', '@tanstack/react-query', 'react-router-dom', 'echarts', 'echarts-for-react'], loader: { '.css': 'empty' }, define: definitions(extra) })
  const mod = new Module(path.join(sourceRoot, '__combos_ssr_memory__.cjs'))
  mod.filename = path.join(sourceRoot, '__combos_ssr_memory__.cjs'); mod.paths = Module._nodeModulePaths(sourceRoot)
  mod._compile(result.outputFiles[0].text, mod.filename)
  return mod.exports
}
async function checkOnly() {
  typecheck()
  const gate = checkGate()
  const policy = checkPolicyFile()
  const clean = stripFontImports(fs.readFileSync(path.join(sourceRoot, 'styles.css'), 'utf8'))
  assert(!/@import/i.test(clean), 'actual style has no remaining import')
  const parsedCSS = await esbuild.transform(clean, { loader: 'css', logLevel: 'silent' })
  assert.equal(parsedCSS.warnings.length, 0, 'CSS parser receives no partial-import warnings')
  const { App, createCombosFixture, runComboChecks, ComboSummary, ComboDaily, ComboSegments, ComboCombinations, ComboEvidence, ComboCalendar } = await buildSSR()
  const fixture = await createCombosFixture()
  assert(fixture.sourceInputBytes <= 96 * 1024, 'small test source input cap')
  const checked = seen.has('--check-ui-only') ? 0 : await runComboChecks(fixture.read, (ok, label) => assert(ok, label))
  const visited = new Set()
  function estimate(value) {
    if (value === null || value === undefined) return 0
    if (typeof value === 'string') { if (visited.has(value)) return 0; visited.add(value); return 24 + Buffer.byteLength(value) * 2 }
    if (typeof value !== 'object') return 16
    if (visited.has(value)) return 0
    visited.add(value)
    return 64 + Object.entries(value).reduce((sum, [k, v]) => sum + 16 + estimate(k) + estimate(v), 0)
  }
  const retainedEstimate = estimate(fixture.read)
  assert(retainedEstimate <= 1024 * 1024, 'shared derived graph estimate cap')
  const React = requireDeps('react'), { renderToStaticMarkup } = requireDeps('react-dom/server'), { MemoryRouter } = requireDeps('react-router-dom')
  const previousFetch = global.fetch
  let forbiddenFetch = 0, groups = 0
  global.fetch = () => { forbiddenFetch++; throw new Error('SSR automatic fetch') }
  const count = (html, attribute) => (html.match(new RegExp(attribute + '=', 'g')) ?? []).length
  try {
    const route = '/chips-stock-scope-7-dealer-direction-combos', query = '?as_of=2026-10-06&investor=dealer&horizon=5'
    const render = (entry) => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: [entry] }, React.createElement(App)))
    const html = render(route + query)
    assert(html.includes('首次取得來源') && html.includes('已驗證股數') && html.includes('未知') && html.includes('FinMind') && html.includes('TaiwanStockInstitutionalInvestorsBuySell'), 'initial full App has identities and provenance, no values')
    assert(!html.includes('data-combos-summary') && !html.includes('data-combos-row-date') && !html.includes('<svg'), 'initial App masks the whole graph')
    assert(/data-combos-phase="unacquired"/.test(html) && /disabled=""[^>]*>完整七股來源驗證後開啟/.test(html), 'initial phase is unacquired; per-stock open is disabled until verified')
    const unknown = render(route + '/9999' + query)
    assert(unknown.includes('此標的不在核定七股範圍') && !unknown.includes('data-combos-summary') && /disabled=""[^>]*>明確讀取已持有來源/.test(unknown), 'unknown selected stock masks data and forbids READ')
    for (const bad of ['as_of=&investor=dealer&horizon=5', 'as_of=2026-10-07&investor=dealer&horizon=5', 'as_of=2026-10-06&investor=foreign&horizon=5', 'as_of=2026-10-06&investor=dealer&horizon=20', 'as_of=2026-10-06&investor=dealer&horizon=5&horizon=5']) {
      const masked = render(route + '/3105?' + bad)
      assert(!masked.includes('data-combos-summary') && /disabled=""[^>]*>明確讀取已持有來源/.test(masked), 'invalid RAW controls mask all and disable READ')
    }
    for (const stock of fixture.read.stocks) {
      const summary = renderToStaticMarkup(React.createElement(ComboSummary, { stock }))
      assert(count(summary, 'data-combos-count') === 6 && count(summary, 'data-combos-latest') === 2 && summary.includes('自行買賣') && summary.includes('避險') && summary.includes('相反方向日數') && summary.includes('首段之前延續未知'), 'ALL7 self and hedge counts and latest always parallel')
      const daily = renderToStaticMarkup(React.createElement(ComboDaily, { stock, onPoint: () => {} }))
      assert(count(daily, 'data-combos-daily-date') === 10 && count(daily, 'data-combos-point-button') === 5 && count(daily, 'data-combos-daily-combination') === 5, 'ALL7 five dates, ten daily net cells, five trace buttons')
      const segments = renderToStaticMarkup(React.createElement(ComboSegments, { stock, onPoint: () => {} }))
      const total = stock.window.segments.self.length + stock.window.segments.hedge.length
      assert((segments.match(/data-combos-segment="/g) ?? []).length === total && count(segments, 'data-combos-segment-date') === 10, 'every maximal segment and its dates are operable')
      const combos = renderToStaticMarkup(React.createElement(ComboCombinations, { stock, onPoint: () => {} }))
      assert((combos.match(/data-combos-combo="/g) ?? []).length === 9 && count(combos, 'data-combos-combo-date') === 5 && count(combos, 'data-combos-opposite-date') === stock.window.opposite.count, 'nine combination rows, five dated buttons, opposite dates operable')
      for (let index = 0; index < 5; index++) {
        const evidence = renderToStaticMarkup(React.createElement(ComboEvidence, { stock, index, read: fixture.read }))
        const point = stock.window.points[index]
        assert(count(evidence, 'data-combos-raw-row') === 5 && count(evidence, 'data-combos-key-order') === 5 && evidence.includes(point.receipt_sha256) && evidence.includes(point.body_sha256) && evidence.includes(point.url.replace(/&/g, '&amp;')) && evidence.includes('SOURCE_REGISTRY 31.2') && evidence.includes('canonical receipt'), 'five original name rows, key order, dual SHA, URL, calendar reference')
        groups++
      }
      groups++
    }
    const zeroEvidence = renderToStaticMarkup(React.createElement(ComboEvidence, { stock: fixture.read.stocks[6], index: 0, read: fixture.read }))
    const zeroDaily = renderToStaticMarkup(React.createElement(ComboDaily, { stock: fixture.read.stocks[6], onPoint: () => {} }))
    assert(zeroEvidence.includes('已驗證原值為零') && zeroDaily.includes('已驗證淨額為零'), 'verified synthetic zero labels')
    assert(renderToStaticMarkup(React.createElement(ComboCalendar, { read: fixture.read })).includes('SOURCE_REGISTRY 31.2'), 'fixed calendar reference')
    const exclusive = await buildSSR({ 'import.meta.env.VITE_CHIPS_DEALER_COMPONENTS_STOCK_SCOPE_7': JSON.stringify('m1-v1') })
    assert.throws(() => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: [route + query] }, React.createElement(exclusive.App))), /cannot be enabled together/)
    assert(forbiddenFetch === 0, 'SSR network zero')
  } finally { global.fetch = previousFetch }
  console.log(JSON.stringify({ synthetic_only: true, focused_ui_only: seen.has('--check-ui-only'), versions: { node: process.version, typescript: ts.version, esbuild: esbuild.version }, validator_checks: checked, combos_group_ssr: groups, stocks_ssr: 7, flag_exclusion_checked: true, browser_gate_checks: gate, policy_sha256: policySha, policy_bytes: policyBytes, ...policy, native_viewport_verification: false, source_input_bytes: fixture.sourceInputBytes, shared_derived_graph_estimate_bytes: retainedEstimate, estimate: 'deduplicated object/string estimate, not RSS or construction peak', network: 0, guards: counts }))
}
async function serveOnly() {
  const policy = checkPolicyFile()
  const result = await esbuild.build({ entryPoints: [path.join(sourceRoot, 'main.tsx')], bundle: true, write: false, outfile: path.join(sourceRoot, '__combos_memory__.js'), platform: 'browser', format: 'iife', target: 'es2020', jsx: 'automatic', nodePaths: [deps], define: definitions(), plugins: [{ name: 'system-fonts-memory', setup(build) { build.onLoad({ filter: /\.css$/ }, (loadArgs) => ({ contents: stripFontImports(fs.readFileSync(loadArgs.path, 'utf8')), loader: 'css' })) } }] })
  const js = result.outputFiles.find((f) => f.path.endsWith('.js')).contents
  const css = result.outputFiles.find((f) => f.path.endsWith('.css'))?.contents ?? Buffer.alloc(0)
  const html = Buffer.from('<!doctype html><html lang="zh-Hant"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>七股自營商自行買賣與避險方向組合</title><link rel="stylesheet" href="/combos-memory.css"></head><body><div id="root"></div><script src="/combos-memory.js"></script></body></html>')
  function reply(res, status, body, type = 'application/json; charset=utf-8') { res.writeHead(status, { 'Content-Type': type, 'Cache-Control': 'no-store', 'Content-Security-Policy': "default-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'self'; img-src 'self' data:" }); res.end(body) }
  const apiPath = '/api/chips/dealer-direction-combos-stock-scope-7'
  const server = http.createServer(async (req, res) => {
    try {
      const refused = admitRequest(req.method, req.rawHeaders)
      if (refused) { counts.rejected_requests++; return reply(res, refused.status, JSON.stringify({ reason: refused.reason })) }
      const url = new URL(req.url, 'http://127.0.0.1:' + port)
      if (req.method === 'GET' && ['/combos-memory.js', '/combos-memory.css'].includes(url.pathname)) return reply(res, 200, url.pathname.endsWith('.js') ? js : css, url.pathname.endsWith('.js') ? 'text/javascript; charset=utf-8' : 'text/css; charset=utf-8')
      if (req.method === 'GET' && /^\/chips-stock-scope-7-dealer-direction-combos(?:\/[0-9A-Za-z]{1,16})?$/.test(url.pathname)) return reply(res, 200, html, 'text/html; charset=utf-8')
      if (req.method === 'GET' && url.pathname === '/__combos_preview_receipt' && !url.search) return reply(res, 200, JSON.stringify({ pid: process.pid, compiler_pids: children.map((child) => child.pid), versions: { node: process.version, typescript: ts.version, esbuild: esbuild.version }, policy_sha256: policySha, policy_bytes: policyBytes, ...policy, js_bytes: js.length, css_bytes: css.length, write: false, guard_counts: counts }))
      // Only the two product calls pass; the root-local diagnostic and admission endpoints are reached directly on the API port, never here.
      const keys = [...url.searchParams.keys()]
      const day = url.searchParams.get('as_of')
      if (!((url.pathname === apiPath && req.method === 'GET') || (url.pathname === apiPath + '/capture' && req.method === 'POST')) || keys.length !== 1 || keys[0] !== 'as_of' || !/^\d{4}-\d{2}-\d{2}$/.test(day ?? '') || new Date(day + 'T00:00:00Z').toISOString().slice(0, 10) !== day) {
        counts.rejected_requests++; return reply(res, 422, JSON.stringify({ reason: 'preview_path_method_query_not_admitted' }))
      }
      const cap = req.method === 'POST' ? 4096 : 0
      if (Number(req.headers['content-length'] ?? 0) > cap) { counts.rejected_requests++; return reply(res, req.method === 'POST' ? 413 : 422, '{"reason":"body_limit"}') }
      const parts = []; let size = 0
      for await (const part of req) { size += part.length; if (size > cap) { counts.rejected_requests++; return reply(res, req.method === 'POST' ? 413 : 422, '{"reason":"body_limit"}') }; parts.push(part) }
      const body = Buffer.concat(parts)
      if (req.method === 'POST') { const parsed = JSON.parse(body.toString('utf8')); if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object' || Object.keys(parsed).length) { counts.rejected_requests++; return reply(res, 422, '{"reason":"empty_object_required"}') } }
      counts[req.method === 'POST' ? 'proxy_post' : 'proxy_get']++
      const upstream = http.request({ hostname: '127.0.0.1', port: apiPort, path: url.pathname + url.search, method: req.method, agent: false, headers: { Host: apiHost, 'Content-Type': 'application/json', 'Content-Length': body.length } }, (response) => {
        const chunks = []; let bytes = 0
        response.on('data', (chunk) => { bytes += chunk.length; if (bytes > 16777216) { upstream.destroy(new Error('local API response cap')); return }; chunks.push(chunk) })
        response.on('end', () => { if (!res.writableEnded) reply(res, response.statusCode ?? 502, Buffer.concat(chunks)) })
      })
      upstream.setTimeout(195000, () => upstream.destroy(new Error('finite local API timeout')))
      upstream.on('error', () => { if (!res.writableEnded) reply(res, 502, '{"reason":"owned_api_unavailable"}') })
      upstream.end(body)
    } catch { if (!res.writableEnded) reply(res, 422, '{"reason":"invalid_preview_request"}') }
  })
  server.listen(port, '127.0.0.1', () => console.log(JSON.stringify({ serving: true, pid: process.pid, port, api_port: apiPort, js_bytes: js.length, css_bytes: css.length, policy_sha256: policySha, policy_bytes: policyBytes, ...policy, financial_get: 0, write: false, versions: { node: process.version, typescript: ts.version, esbuild: esbuild.version }, guards: counts })))
  process.once('SIGINT', () => { server.close(() => { esbuild.stop(); console.log(JSON.stringify({ shutdown: true, pid: process.pid, compiler_pids: children.map((child) => child.pid), guards: counts })); process.exitCode = 0 }); server.closeAllConnections() })
}
;(async () => {
  try { if (check) await checkOnly(); else await serveOnly() }
  catch (error) { console.error(error); process.exitCode = 1 }
  finally { if (check || process.exitCode) { esbuild.stop(); console.log(JSON.stringify({ pid: process.pid, compiler_pids: children.map((child) => child.pid), final_guards: counts })) } }
})()
