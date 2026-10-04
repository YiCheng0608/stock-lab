/** Memory-only W8 typecheck, product HTTP/SSR and full-App preview.
 * Existing master node_modules are borrowed read-only via --deps. No files,
 * bundles, buildinfo, HTTP captures, screenshots or new dependencies are made.
 * Start the guarded Python --serve on 8781 first; --live-source-opt-in belongs
 * exclusively to coordinator acceptance. This tool never opts into live data.
 */
const fs = require('node:fs')
const path = require('node:path')
const http = require('node:http')
const Module = require('node:module')
const assert = require('node:assert/strict')
const childProcess = require('node:child_process')
const args = process.argv.slice(2)
const option = (name, fallback) => args.includes(name) ? args[args.indexOf(name) + 1] : fallback
const root = path.resolve(__dirname, '..')
const dependencies = path.resolve(option('--deps', ''))
if (!args.includes('--deps') || !fs.existsSync(path.join(dependencies, 'typescript/package.json'))) throw new Error('--deps requires existing frontend/node_modules')
const apiOrigin = 'http://127.0.0.1:8781'
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
  ownedChildren.push(child.pid)
  console.log(JSON.stringify({ esbuild_pid: child.pid, parent_pid: process.pid, binary: compilerBinary }))
  child.once('exit', (code, signal) => console.log(JSON.stringify({ esbuild_exit: true, pid: child.pid, code, signal })))
  return child
}
for (const name of ['exec', 'execSync', 'execFile', 'execFileSync', 'spawnSync', 'fork']) childProcess[name] = () => {
  counts.unapproved_subprocess++; throw new Error('unapproved subprocess')
}
const denied = () => { counts.filesystem_mutations++; throw new Error('filesystem mutation denied') }
for (const name of ['writeFile', 'writeFileSync', 'appendFile', 'appendFileSync', 'mkdir', 'mkdirSync', 'mkdtemp', 'mkdtempSync',
  'rename', 'renameSync', 'unlink', 'unlinkSync', 'rm', 'rmSync', 'rmdir', 'rmdirSync', 'copyFile', 'copyFileSync',
  'truncate', 'truncateSync', 'ftruncate', 'ftruncateSync', 'chmod', 'chmodSync', 'chown', 'chownSync', 'utimes', 'utimesSync',
  'link', 'linkSync', 'symlink', 'symlinkSync', 'createWriteStream', 'write', 'writeSync', 'writev', 'writevSync']) fs[name] = denied
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
fs.promises.open = (filename, flags, ...rest) => safeFlags(flags) ? originalPromiseOpen.call(fs.promises, filename, flags, ...rest) : denied()
const allowedPost = (url) => /^\/api\/stocks\/TPEx\/(3105|6488)\/institutional-windows\/capture$/.test(url.pathname)
const originalFetch = global.fetch
global.fetch = (input, options = {}) => {
  const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url)
  const method = (options.method ?? 'GET').toUpperCase()
  if (url.origin !== apiOrigin || (method !== 'GET' && !(method === 'POST' && allowedPost(url)))) {
    counts.unapproved_network++; throw new Error('network destination or operation outside preview scope')
  }
  return originalFetch(input, { ...options, redirect: 'error' })
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
  console.log('TypeScript full src passed; no emit/buildinfo')
}

async function apiModule() {
  const result = await esbuild.build({ entryPoints: [path.join(sourceRoot, 'api.ts')], bundle: true, write: false,
    platform: 'node', format: 'cjs', target: 'es2020', define: { 'import.meta.env.VITE_API_BASE': JSON.stringify(apiOrigin + '/api') } })
  const module = new Module(path.join(sourceRoot, '__memory_api__.cjs'))
  module.filename = path.join(sourceRoot, '__memory_api__.cjs')
  module._compile(result.outputFiles[0].text, module.filename)
  return module.exports
}

async function check() {
  typecheck()
  const { renderToStaticMarkup } = requireDependency('react-dom/server')
  const React = requireDependency('react')
  const w3 = args.includes('--w3-only')
  const w4 = args.includes('--w4-only')
  const w5 = args.includes('--w5-only')
  const w6 = args.includes('--w6-only')
  const w7 = args.includes('--w7-only')
  const w8 = args.includes('--w8-only')
  if (w3 || w4 || w5 || w6 || w7 || w8) globalThis.__institutionalWindowSSRSelection = w8 ? 'w8-only' : w7 ? 'w7-only' : w6 ? 'w6-only' : w5 ? 'w5-only' : w4 ? 'w4-only' : 'w3-only'
  const cases = require(path.join(sourceRoot, 'components/StockOverview.test.tsx'))
  const { StockOverview } = require(path.join(sourceRoot, 'components/StockOverview.tsx'))
  const ssrCases = w8 ? cases.runInstitutionalWindowEighthCutoffSSRTests(renderToStaticMarkup) : w7 ? cases.runInstitutionalWindowSeventhCutoffSSRTests(renderToStaticMarkup) : w6 ? cases.runInstitutionalWindowSixthCutoffSSRTests(renderToStaticMarkup) : w5 ? cases.runInstitutionalWindowFifthCutoffSSRTests(renderToStaticMarkup) : w4 ? cases.runInstitutionalWindowEarlierCutoffSSRTests(renderToStaticMarkup) : w3 ? cases.runInstitutionalWindowCutoffSSRTests(renderToStaticMarkup) : cases.runInstitutionalWindowSSRTests(renderToStaticMarkup)
  console.log(JSON.stringify({ new_institutional_window_ssr_cases: ssrCases,
    runtime: { node: process.versions.node, typescript: ts.version, esbuild: esbuild.version }, guard: counts, disk_artifacts: 0 }))
  if (args.includes('--typecheck-only')) return
  const api = await apiModule()
  const cutoffs = w8 ? ['2026-09-21', '2026-09-22', '2026-09-23', '2026-09-24', '2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02'] : w7 ? ['2026-09-22', '2026-09-23', '2026-09-24', '2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02'] : w6 ? ['2026-09-23', '2026-09-24', '2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02'] : w5 ? ['2026-09-24', '2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02'] : w4 ? ['2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02'] : w3 ? ['2026-09-30', '2026-10-01', '2026-10-02'] : ['2026-10-02']
  const expectedRequests = w8 ? 30 : w7 ? 29 : w6 ? 28 : w5 ? 27 : w4 ? 26 : 24
  const before = await api.getStock('TPEx', '3105', cutoffs[0])
  assert.equal(before.overview.institutional.capture_state.attempted, false)
  const first = await api.captureInstitutionalWindows('TPEx', '3105', cutoffs[0])
  assert.equal(first.capture_state.request_count, expectedRequests)
  assert.equal(first.capture_state.action, 'acquired')
  let netChecks = 0
  for (const [cutoffIndex, cutoff] of cutoffs.entries()) for (const symbol of ['3105', '6488']) {
    const repeated = (w4 || w5 || w6 || w7 || w8) && cutoffIndex === 0 && symbol === '3105'
      ? (await api.getStock('TPEx', symbol, cutoff)).overview.institutional
      : await api.captureInstitutionalWindows('TPEx', symbol, cutoff)
    const stock = await api.getStock('TPEx', symbol, cutoff)
    const overview = await (await fetch(`${apiOrigin}/api/stocks/TPEx/${symbol}/overview?as_of=${cutoff}`)).json()
    assert.deepEqual(stock.overview.institutional, repeated)
    assert.deepEqual(overview.institutional, repeated)
    assert.deepEqual(repeated.provenance, first.provenance)
    assert.equal(overview.as_of, cutoff)
    assert.equal(repeated.as_of, cutoff)
    for (const horizon of [5, 20]) {
      const item = repeated.windows[String(horizon)]
      assert.equal(item.to, cutoff)
      assert.equal(item.required_dates.length, horizon)
      assert.ok(item.daily_evidence.every(({ row, provenance }) => row.date <= cutoff && provenance.requested_date === row.date))
      const ordinalEnd = 20 + cutoffIndex
      const ordinalSum = horizon * (2 * ordinalEnd - horizon + 1) / 2
      const base = symbol === '3105' ? [900, -30, -35] : [-500, 30, -5]
      for (const [index, investor] of ['foreign', 'trust', 'dealer'].entries()) {
        const buy = symbol === '3105' ? [1000, 10, 30] : [100, 50, 10]
        const sell = symbol === '3105' ? [100, 40, 65] : [600, 20, 15]
        const expected = w7 || w8 ? String((buy[index] - sell[index]) * horizon + ordinalSum * ([100, 0, 3][index] - [0, 1, 0][index]))
          : String(base[index] * horizon + (w3 || w4 || w5 || w6 ? ordinalSum * [100, -1, 3][index] : 0))
        assert.equal(item.values[investor], expected)
        assert.equal(BigInt(item.values[investor]).toString(), expected)
        netChecks++
      }
    }
    const html = renderToStaticMarkup(React.createElement(StockOverview, { data: overview, onNews: () => {}, onCaptureWindows: () => {} }))
    const displayed = repeated.windows['5'].values.foreign.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
    assert.ok(html.includes(displayed))
    assert.ok(html.includes('讀取本次法人窗口'))
    assert.ok(!html.includes('窗口仍不可用'))
  }
  const refused = await api.getStock('TPEx', '3105', '2026-10-03')
  assert.deepEqual(refused.overview.institutional.windows, {})
  const receipt = await (await fetch(`${apiOrigin}/__window_validation/receipt`)).json()
  assert.equal(receipt.request_count, expectedRequests)
  assert.equal(receipt.db_preserved, true)
  if (w7 || w8) assert.equal(receipt.db_tables, 19)
  assert.ok(Object.values(receipt.guard).every((value) => value === 0))
  console.log(JSON.stringify({ passed: true, new_ssr_cases: ssrCases, response_parser: 'product fetch + Response.json',
    institutional_source: 'synthetic mock only', net_checks: netChecks, supported_cutoffs: cutoffs,
    loopback_requests: { get: cutoffs.length * 4 + 3 + (w4 || w5 || w6 || w7 || w8 ? 1 : 0), post: cutoffs.length * 2 + (w4 || w5 || w6 || w7 || w8 ? 0 : 1) }, request_count: receipt.request_count, db_preserved: receipt.db_preserved,
    guard: counts, disk_artifacts: 0, production_vite_build: 'not_run' }))
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
  const server = http.createServer(async (request, response) => {
    response.setHeader('Cache-Control', 'no-store')
    response.setHeader('Content-Security-Policy', "default-src 'self' data:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; font-src 'self' data:")
    const url = new URL(request.url, apiOrigin)
    const method = request.method
    if (method !== 'GET' && !(method === 'POST' && allowedPost(url))) { response.writeHead(405); response.end('preview operation outside scope'); return }
    try {
      if (url.pathname.startsWith('/api/')) {
        const upstream = await fetch(url, { method, ...(method === 'POST' ? { headers: { 'Content-Type': 'application/json' }, body: '{}' } : {}) })
        response.writeHead(upstream.status, { 'Content-Type': upstream.headers.get('content-type') || 'application/json' })
        response.end(Buffer.from(await upstream.arrayBuffer()))
      } else if (url.pathname === '/app.js') {
        response.writeHead(200, { 'Content-Type': 'text/javascript; charset=utf-8' }); response.end(script)
      } else if (url.pathname === '/app.css') {
        response.writeHead(200, { 'Content-Type': 'text/css; charset=utf-8' }); response.end(css)
      } else {
        response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }); response.end(html)
      }
    } catch { response.writeHead(502); response.end('preview upstream unavailable') }
  })
  server.listen(8782, '127.0.0.1', () => console.log(JSON.stringify({ mode: 'memory full App + limited actual router proxy',
    pid: process.pid, parent_pid: process.ppid, child_pids: ownedChildren, port: 8782,
    url: 'http://127.0.0.1:8782/stocks/TPEx/3105?as_of=2026-10-02', api: apiOrigin,
    font: 'local fallback; remote font import omitted in memory', guard: counts, disk_artifacts: 0 })))
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => server.close(() => {
    console.log(JSON.stringify({ shutdown: true, signal, pid: process.pid, child_pids: ownedChildren, guard: counts, disk_artifacts: 0 }))
    esbuild.stop()
    process.exit(0)
  }))
}

Promise.resolve().then(() => args.includes('--serve') ? serve() : check())
  .catch((error) => { console.error(error); process.exitCode = 1 })
  .finally(() => { if (!args.includes('--serve')) esbuild.stop() })
