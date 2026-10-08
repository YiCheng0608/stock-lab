'use strict'
// Independent memory preview: no financial transport, disk output or private I/O.
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
const allowed = new Set(['--check', '--check-ui-only', '--check-startup-only', '--serve', '--chips-series-stock-scope-7-opt-in', '--chips-gross-stock-scope-7-opt-in', '--deps', '--api-port', '--port', '--policy-version', '--policy-digest'])
const optionNames = new Set(['--deps', '--api-port', '--port', '--policy-version', '--policy-digest'])
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
assert(!seen.has('--check-startup-only') || check && !seen.has('--check-ui-only'), '--check-startup-only requires --check without --check-ui-only')
const gross = seen.has('--chips-gross-stock-scope-7-opt-in')
assert(!gross || !seen.has('--chips-series-stock-scope-7-opt-in'), 'gross and daily-net profiles cannot be enabled together')
assert(!serve || seen.has('--chips-series-stock-scope-7-opt-in') || gross, 'explicit new frontend flag required')
assert(process.version === 'v24.19.0', 'pinned Node24.19.0 required')
const version = gross ? 'm1-chips-gross-trade-stock-scope-7-tpex-2026-10-06.1' : 'm1-chips-daily-net-series-stock-scope-7-tpex-2026-10-06.1'
const pin = gross ? 'sha256:ea02b5f32ff2bd0c415e14192c6daa276dc2781e8a6c2d4e5b90bcad776d1144' : 'sha256:143aabb4cd2d86110d5564793ce77b0fb6c60b3e603f23c1e188875934a48a31'
assert((options.get('--policy-version') ?? version) === version && (options.get('--policy-digest') ?? pin) === pin, 'independent external pins mismatch')
const port = Number(options.get('--port') ?? 8800), apiPort = Number(options.get('--api-port') ?? 8799)
assert([port, apiPort].every((p) => Number.isInteger(p) && p >= 1024 && p <= 65535) && port !== apiPort, 'finite distinct local ports')
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
function guardedLiteralLookup(original, serving, denied = denyNetwork) {
  return function (hostname, ...rest) {
    if (!serving() || hostname !== '127.0.0.1') return denied()
    return original.call(this, hostname, ...rest)
  }
}
dns.lookup = guardedLiteralLookup(dns.lookup, () => serve)
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
assert(ts.version === '5.9.3' && esbuild.version === '0.25.12', 'pinned TypeScript/esbuild versions')
const sourceRoot = path.join(root, 'frontend/src')
const dependencySource = path.resolve(deps, '../src')
const originalResolve = Module._resolveFilename
Module._resolveFilename = function (request, parent, ...rest) {
  try { return originalResolve.call(this, request, parent, ...rest) }
  catch (error) { if (error.code !== 'MODULE_NOT_FOUND' || request.startsWith('.') || path.isAbsolute(request)) throw error; return requireDeps.resolve(request) }
}
for (const extension of ['.ts', '.tsx']) Module._extensions[extension] = (mod, filename) => {
  const result = ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true }, fileName: filename })
  mod._compile(result.outputText, filename)
}
Module._extensions['.css'] = () => {}
function typecheck() {
  const filename = path.join(root, 'frontend/tsconfig.app.json')
  const config = ts.readConfigFile(filename, ts.sys.readFile)
  assert(!config.error, 'read TypeScript config')
  const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, path.dirname(filename))
  const options = { ...parsed.options, noEmit: true, incremental: false, composite: false }
  const host = ts.createCompilerHost(options)
  host.writeFile = denyWrite
  host.resolveModuleNames = (names, containing) => {
    const relative = path.relative(sourceRoot, path.resolve(containing))
    const own = !relative.startsWith('..') && !path.isAbsolute(relative)
    return names.map((name) => ts.resolveModuleName(name, name.startsWith('.') || !own ? containing : path.join(dependencySource, path.basename(containing)), options, host).resolvedModule)
  }
  const program = ts.createProgram(parsed.fileNames, options, host)
  const diagnostics = [...parsed.errors, ...ts.getPreEmitDiagnostics(program)]
  if (diagnostics.length) {
    console.error(ts.formatDiagnosticsWithColorAndContext(diagnostics.slice(0, 12), { getCanonicalFileName: (f) => f, getCurrentDirectory: () => root, getNewLine: () => '\n' }))
    throw new Error('TypeScript diagnostics ' + diagnostics.length)
  }
  console.log(JSON.stringify({ typecheck: 'current full src noEmit', source_files: parsed.fileNames.length }))
}
const definitions = { 'import.meta.env.VITE_API_BASE': JSON.stringify('/api'), 'import.meta.env.VITE_CHIPS_SERIES_STOCK_SCOPE_7': JSON.stringify(gross ? '' : 'm1-v1'), 'import.meta.env.VITE_CHIPS_GROSS_STOCK_SCOPE_7': JSON.stringify(gross ? 'm1-v1' : ''), 'import.meta.env.VITE_SAVED_PRICE_CHIPS_INTEGRATION': JSON.stringify(''), 'import.meta.env.VITE_SAVED_PRICE_CHIPS_FOCUS': JSON.stringify(''), 'import.meta.env.VITE_SAVED_PRICE_CHIPS_FOCUS_CALENDAR': JSON.stringify(''), 'import.meta.env.VITE_SAVED_PRICE_CHIPS_FOCUS_STOCK_SCOPE_7': JSON.stringify('') }
function stripFontImports(css) {
  return css.replace(/@import\s+url\([^)]*\)\s*;/gi, '')
}
async function startupCheckOnly() {
  const simulated = { forwarded: 0, rejected: 0 }
  const fakeLookup = (...args) => { simulated.forwarded++; return args }
  const denied = () => { simulated.rejected++; throw new Error('simulated lookup rejected before resolver') }
  const permitted = guardedLiteralLookup(fakeLookup, () => true, denied)
  const disabled = guardedLiteralLookup(fakeLookup, () => false, denied)
  const callback = () => {}
  assert.deepEqual(permitted('127.0.0.1', { family: 4 }, callback), ['127.0.0.1', { family: 4 }, callback], 'literal listen lookup forwards options/callback')
  assert.deepEqual(permitted('127.0.0.1', callback), ['127.0.0.1', callback], 'literal callback overload preserved')
  for (const hostname of ['localhost', 'www.tpex.org.tw', '0.0.0.0', '::1', '127.0.0.1.example.org', Buffer.from('127.0.0.1')]) assert.throws(() => permitted(hostname, callback), /simulated lookup rejected/)
  assert.throws(() => disabled('127.0.0.1', callback), /simulated lookup rejected/)
  assert.equal(simulated.forwarded, 2); assert.equal(simulated.rejected, 7)
  for (const name of ['resolve', 'resolve4', 'resolve6', 'reverse']) assert.equal(dns[name], denyNetwork, 'external resolution remains forbidden')
  const suffix = '\nbody { font-family: system-ui; color: #123; }'
  const cases = [
    "@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600&display=swap');",
    '@import url("https://fonts.googleapis.com/css2?family=A:wght@400;500&family=B:wght@400;700");',
    '@import url(https://fonts.googleapis.com/css2?family=A:wght@400;500);',
    "@IMPORT\nurl('https://fonts.googleapis.com/css2?family=A:wght@400;500') ;"
  ]
  for (const fixture of cases) assert.equal(stripFontImports(fixture + suffix), suffix, 'whole URL import removed through closing parenthesis')
  const originalCSS = fs.readFileSync(path.join(sourceRoot, 'styles.css'), 'utf8')
  const cleanCSS = stripFontImports(originalCSS)
  assert(!cleanCSS.includes('fonts.googleapis.com') && !cleanCSS.includes('500&family'), 'actual style URL has no leftover fragments')
  const sourceInputBytes = Buffer.byteLength(originalCSS) + cases.reduce((sum, css) => sum + Buffer.byteLength(css + suffix), 0)
  assert(sourceInputBytes <= 96 * 1024, 'bounded source CSS test inputs')
  const graphEstimate = 128 + [originalCSS, cleanCSS, suffix, ...cases].reduce((sum, text) => sum + 24 + Buffer.byteLength(text) * 2, 0)
  assert(graphEstimate <= 1024 * 1024, 'bounded string graph estimate, not RSS or construction peak')
  const parsed = await esbuild.transform(cleanCSS, { loader: 'css', logLevel: 'silent' })
  assert.equal(parsed.warnings.length, 0, 'CSS parser receives no partial-import warnings')
  console.log(JSON.stringify({ focused_startup_only: true, simulated_lookup_forwarded: simulated.forwarded, simulated_lookup_rejected_before_resolver: simulated.rejected, external_resolution_methods_forbidden: 4, import_cases: cases.length, css_warnings: parsed.warnings.length, source_input_bytes: sourceInputBytes, string_graph_estimate_bytes: graphEstimate, estimate: 'bounded string estimate, not RSS or construction peak', full_app_ssr: false, validators: false, real_dns: 0, sockets: 0, services: 0, versions: { node: process.version, typescript: ts.version, esbuild: esbuild.version }, guards: counts }))
}
async function checkOnly() {
  typecheck()
  const literal = fs.readFileSync(path.join(root, gross ? 'backend/worker/tpex_institutional_gross_scope7.py' : 'backend/worker/tpex_institutional_series_scope7.py'), 'utf8').match(/POLICY_CANONICAL = r'''([\s\S]*?)'''/)[1]
  assert(Buffer.byteLength(literal) === (gross ? 10654 : 9733) && 'sha256:' + crypto.createHash('sha256').update(literal).digest('hex') === pin, 'independent canonical policy check')
  const tests = require(path.join(sourceRoot, gross ? 'chipsGross.test.ts' : 'chipsSeries.test.ts'))
  const fixture = await (gross ? tests.createGrossFixture : tests.createSeriesFixture)(JSON.parse(literal))
  assert(fixture.sourceInputBytes <= 96 * 1024, 'small test source input cap')
  const checked = seen.has('--check-ui-only') ? 0 : await (gross ? tests.runGrossChecks : tests.runSeriesChecks)(fixture.read, assert)
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
  const exports = gross ? "export { GrossChart as SeriesChart, GrossEvidence as SeriesEvidence } from './ChipsGrossPage'" : "export { SeriesChart, SeriesEvidence } from './ChipsSeriesPage'"
  const result = await esbuild.build({ stdin: { contents: "export { default as App } from './App'; " + exports, resolveDir: sourceRoot, loader: 'ts' }, bundle: true, write: false, platform: 'node', format: 'cjs', target: 'es2020', jsx: 'automatic', nodePaths: [deps], external: ['react', 'react/*', 'react-dom', 'react-dom/*', '@tanstack/react-query', 'react-router-dom', 'echarts', 'echarts-for-react'], loader: { '.css': 'empty' }, define: definitions })
  const mod = new Module(path.join(sourceRoot, '__series_ssr_memory__.cjs'))
  mod.filename = path.join(sourceRoot, '__series_ssr_memory__.cjs'); mod.paths = Module._nodeModulePaths(sourceRoot)
  mod._compile(result.outputFiles[0].text, mod.filename)
  const React = requireDeps('react'), { renderToStaticMarkup } = requireDeps('react-dom/server'), { MemoryRouter } = requireDeps('react-router-dom')
  const { App, SeriesChart, SeriesEvidence } = mod.exports
  const previousFetch = global.fetch
  let forbiddenFetch = 0
  global.fetch = () => { forbiddenFetch++; throw new Error('SSR automatic fetch') }
  let chartChecks = 0
  try {
    const route = gross ? '/chips-stock-scope-7-gross-trade' : '/chips-stock-scope-7-daily-net-trend'
    const html = renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: [route + '?as_of=2026-10-06&investor=foreign&horizon=20'] }, React.createElement(App)))
    assert(html.includes('首次取得來源') && html.includes('已驗證股數') && html.includes('未知') && !html.includes('<svg'), 'initial fullApp has identities, no unverified charts')
    if (gross) {
      const unknown = renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: [route + '/9999?as_of=2026-10-06&investor=foreign&horizon=20'] }, React.createElement(App)))
      assert(unknown.includes('此標的不在核定七股範圍') && !unknown.includes('<svg') && !unknown.includes('精確日期買進賣出淨超與累計') && /disabled=""[^>]*>明確讀取已持有來源/.test(unknown), 'unknown selected stock masks data and forbids READ before returning to supported scope')
    }
    for (const stock of seen.has('--check-ui-only') ? [] : fixture.read.stocks) for (const investor of ['foreign', 'trust', 'dealer']) for (const horizon of ['5', '20']) {
      const window = stock.series[investor][horizon]
      for (const cumulative of [false, true]) {
        const chart = renderToStaticMarkup(React.createElement(SeriesChart, { window, cumulative, onPoint: () => {} }))
        assert(chart.includes('tabindex="0"') && chart.includes(window.points[0].date) && chart.includes('series-zero-line'), 'operable dated exact chart point')
        chartChecks++
      }
    }
    const negative = fixture.read.stocks[0].series.foreign['20'].points.find((p) => p.net_shares.startsWith('-'))
    const zero = fixture.read.stocks[0].series.foreign['20'].points.find((p) => p.net_shares === '0')
    const negativeHTML = renderToStaticMarkup(React.createElement(SeriesEvidence, { point: negative, read: fixture.read }))
    assert(negativeHTML.includes(negative.net_lots) && negativeHTML.includes(negative.receipt_sha256) && negativeHTML.includes(negative.body_sha256), 'exact negative lots and original receipts')
    assert(renderToStaticMarkup(React.createElement(SeriesEvidence, { point: zero, read: fixture.read })).includes(gross ? '已驗證當日買進及賣出為零' : '已驗證當日淨超為零'), 'verified synthetic daily zero SSR')
    assert(forbiddenFetch === 0, 'SSR network zero')
  } finally { global.fetch = previousFetch }
  console.log(JSON.stringify({ synthetic_only: true, focused_ui_only: seen.has('--check-ui-only'), versions: { node: process.version, typescript: ts.version, esbuild: esbuild.version }, validator_checks: checked, chart_ssr: chartChecks, initial_full_app_ssr: true, evidence_negative_and_zero_ssr: true, source_input_bytes: fixture.sourceInputBytes, shared_derived_graph_estimate_bytes: retainedEstimate, derived_expanded_serialization_bytes: Buffer.byteLength(JSON.stringify(fixture.read)), estimate: 'deduplicated object/string estimate, not RSS or construction peak', network: 0, guards: counts }))
}
async function serveOnly() {
  const result = await esbuild.build({ entryPoints: [path.join(sourceRoot, 'main.tsx')], bundle: true, write: false, outfile: path.join(sourceRoot, '__series_memory__.js'), platform: 'browser', format: 'iife', target: 'es2020', jsx: 'automatic', nodePaths: [deps], define: definitions, plugins: [{ name: 'system-fonts-memory', setup(build) { build.onLoad({ filter: /\.css$/ }, (args) => ({ contents: stripFontImports(fs.readFileSync(args.path, 'utf8')), loader: 'css' })) } }] })
  const js = result.outputFiles.find((f) => f.path.endsWith('.js')).contents
  const css = result.outputFiles.find((f) => f.path.endsWith('.css'))?.contents ?? Buffer.alloc(0)
  const html = Buffer.from('<!doctype html><html lang="zh-Hant"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + (gross ? '七股法人買進與賣出' : '七股每日法人淨超') + '</title><link rel="stylesheet" href="/series-memory.css"></head><body><div id="root"></div><script src="/series-memory.js"></script></body></html>')
  function reply(res, status, body, type = 'application/json; charset=utf-8') { res.writeHead(status, { 'Content-Type': type, 'Cache-Control': 'no-store', 'Content-Security-Policy': "default-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'self'; img-src 'self' data:" }); res.end(body) }
  const server = http.createServer(async (req, res) => {
    try {
      const url = new URL(req.url, 'http://127.0.0.1:' + port)
      if (req.method === 'GET' && ['/series-memory.js', '/series-memory.css'].includes(url.pathname)) return reply(res, 200, url.pathname.endsWith('.js') ? js : css, url.pathname.endsWith('.js') ? 'text/javascript; charset=utf-8' : 'text/css; charset=utf-8')
      const routePattern = gross ? /^\/chips-stock-scope-7-gross-trade(?:\/[0-9A-Za-z]{1,16})?$/ : /^\/chips-stock-scope-7-daily-net-trend(?:\/(?:3105|3293|5274|5347|6488|6510|8069))?$/
      if (req.method === 'GET' && routePattern.test(url.pathname)) return reply(res, 200, html, 'text/html; charset=utf-8')
      if (req.method === 'GET' && url.pathname === (gross ? '/__gross_preview_receipt' : '/__series_preview_receipt') && !url.search) return reply(res, 200, JSON.stringify({ pid: process.pid, versions: { node: process.version, typescript: ts.version, esbuild: esbuild.version }, policy_digest: pin, js_bytes: js.length, css_bytes: css.length, write: false, guard_counts: counts }))
      const allowedPath = gross ? '/api/chips/gross-stock-scope-7' : '/api/chips/series-stock-scope-7'
      const keys = [...url.searchParams.keys()]
      const date = url.searchParams.get('as_of')
      if (!((url.pathname === allowedPath && req.method === 'GET') || (url.pathname === allowedPath + '/capture' && req.method === 'POST')) || keys.length !== 1 || keys[0] !== 'as_of' || !/^\d{4}-\d{2}-\d{2}$/.test(date ?? '') || new Date(date + 'T00:00:00Z').toISOString().slice(0, 10) !== date) {
        counts.rejected_requests++; return reply(res, 422, JSON.stringify({ reason: 'preview_path_method_query_not_admitted' }))
      }
      const cap = req.method === 'POST' ? 4096 : 0
      if (Number(req.headers['content-length'] ?? 0) > cap) { counts.rejected_requests++; return reply(res, req.method === 'POST' ? 413 : 422, '{"reason":"body_limit"}') }
      const parts = []; let size = 0
      for await (const part of req) { size += part.length; if (size > cap) { counts.rejected_requests++; return reply(res, req.method === 'POST' ? 413 : 422, '{"reason":"body_limit"}') }; parts.push(part) }
      const body = Buffer.concat(parts)
      if (req.method === 'POST') { const parsed = JSON.parse(body.toString('utf8')); if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object' || Object.keys(parsed).length) { counts.rejected_requests++; return reply(res, 422, '{"reason":"empty_object_required"}') } }
      counts[req.method === 'POST' ? 'proxy_post' : 'proxy_get']++
      const upstream = http.request({ hostname: '127.0.0.1', port: apiPort, path: url.pathname + url.search, method: req.method, agent: false, headers: { 'Content-Type': 'application/json', 'Content-Length': body.length } }, (response) => {
        const chunks = []; let bytes = 0
        response.on('data', (chunk) => { bytes += chunk.length; if (bytes > 16777216) { upstream.destroy(new Error('local API response cap')); return }; chunks.push(chunk) })
        response.on('end', () => { if (!res.writableEnded) reply(res, response.statusCode ?? 502, Buffer.concat(chunks)) })
      })
      upstream.setTimeout(195000, () => upstream.destroy(new Error('finite local API timeout')))
      upstream.on('error', () => { if (!res.writableEnded) reply(res, 502, '{"reason":"owned_api_unavailable"}') })
      upstream.end(body)
    } catch { if (!res.writableEnded) reply(res, 422, '{"reason":"invalid_preview_request"}') }
  })
  server.listen(port, '127.0.0.1', () => console.log(JSON.stringify({ serving: true, pid: process.pid, port, api_port: apiPort, js_bytes: js.length, css_bytes: css.length, financial_get: 0, write: false, versions: { node: process.version, typescript: ts.version, esbuild: esbuild.version }, guards: counts })))
  process.once('SIGINT', () => { server.close(() => { esbuild.stop(); console.log(JSON.stringify({ shutdown: true, guards: counts })); process.exitCode = 0 }); server.closeAllConnections() })
}
;(async () => {
  try { if (seen.has('--check-startup-only')) await startupCheckOnly(); else if (check) await checkOnly(); else await serveOnly() }
  catch (error) { console.error(error); process.exitCode = 1 }
  finally { if (check || process.exitCode) { esbuild.stop(); console.log(JSON.stringify({ final_guards: counts })) } }
})()
