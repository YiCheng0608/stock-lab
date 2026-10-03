/** Reconstructable memory-only TS validation and full-App preview.
 * Borrow an existing master frontend/node_modules with --deps; never installs,
 * emits dist/cache/buildinfo, or saves HTTP responses, screenshots or bundles.
 * Start test_volume_exact_presentation.py --serve first: --check uses the actual
 * API getStock/getInstrument fetch -> Response.json -> chart/overview rendering.
 */
const fs = require('node:fs')
const path = require('node:path')
const http = require('node:http')
const Module = require('node:module')
const assert = require('node:assert/strict')

const args = process.argv.slice(2)
const option = (name, fallback) => {
  const index = args.indexOf(name)
  return index < 0 ? fallback : args[index + 1]
}
const root = path.resolve(__dirname, '..')
const dependencies = path.resolve(option('--deps', ''))
if (!args.includes('--deps') || !fs.existsSync(path.join(dependencies, 'typescript/package.json'))) {
  throw new Error('--deps must name an existing read-only frontend/node_modules')
}
const apiOrigin = new URL(option('--api', 'http://127.0.0.1:8765'))
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
Module._resolveFilename = function (request, parent, ...rest) {
  try { return originalResolve.call(this, request, parent, ...rest) } catch (error) {
    if (error.code !== 'MODULE_NOT_FOUND' || request.startsWith('.') || path.isAbsolute(request)) throw error
    return requireDependency.resolve(request)
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

async function check() {
  typecheck()
  for (const filename of ['units.test.ts', 'stockChart.test.ts', 'components/StockOverview.test.tsx']) require(path.join(sourceRoot, filename))
  const { formatTableVolume, formatTableVolumeShares } = require(path.join(sourceRoot, 'units.ts'))
  const { prepareStockChartData, formatStockTooltip } = require(path.join(sourceRoot, 'stockChart.ts'))
  const { StockOverview } = require(path.join(sourceRoot, 'components/StockOverview.tsx'))
  const { StockPriceChart } = require(path.join(sourceRoot, 'StockPriceChart.tsx'))
  const React = requireDependency('react')
  const { renderToStaticMarkup } = requireDependency('react-dom/server')
  const api = await apiModule()
  const cases = [
    ['ZERO0', '0', '0'], ['ONE1', '1', '0.001'], ['N999', '999', '0.999'],
    ['LOT1', '1000', '1'], ['LOT01', '1001', '1.001'],
    ['SAFE', '9007199254740991', '9,007,199,254,740.991'],
    ['ODD', '9007199254740993', '9,007,199,254,740.993'],
    ['MAX', '9223372036854775807', '9,223,372,036,854,775.807'],
  ]
  let routes = 0
  for (const exchange of ['TWSE', 'TPEx']) {
    for (const [symbol, exact, lots] of cases) {
      // These exported product functions call actual fetch/Response.json.
      const stock = await api.getStock(exchange, symbol, '2026-10-01')
      const instrument = await api.getInstrument(symbol, exchange)
      const overviewResponse = await fetch(`${apiOrigin.origin}/api/stocks/${exchange}/${symbol}/overview?as_of=2026-10-01`)
      assert.equal(overviewResponse.status, 200)
      const overview = await overviewResponse.json()
      routes += 3
      for (const payload of [stock, instrument]) {
        const bar = payload.bars[0]
        assert.equal(bar.volume_exact, exact)
        assert.equal(bar.volume, Number(exact))
        assert.equal(formatTableVolume(bar.volume, bar.source, bar.volume_exact), lots)
        assert.equal(formatTableVolumeShares(bar.volume, bar.source, bar.volume_exact), exact.replace(/\B(?=(\d{3})+(?!\d))/g, ','))
        const data = prepareStockChartData(payload.bars)
        assert.ok(formatStockTooltip(data, { dataIndex: 0 }).includes(`成交量（張）：${lots}`))
        const chart = renderToStaticMarkup(React.createElement(StockPriceChart, { bars: payload.bars }))
        assert.ok(chart.includes(`<td class="numeric-cell">${lots}</td>`))
        assert.ok(chart.includes('成交量柱形與座標刻度為近似值'))
      }
      const price = stock.overview.price
      assert.deepEqual(overview.price, price)
      if (exchange === 'TWSE') {
        assert.equal(price.latest.volume_exact, exact)
        const html = renderToStaticMarkup(React.createElement(StockOverview, { data: stock.overview, onNews: () => {} }))
        assert.ok(html.includes(`<strong>${lots}</strong>`))
        assert.ok(html.includes(`<td>${exact.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}</td>`))
      } else {
        assert.equal(price.latest, null)
        assert.ok(price.reasons.includes('price_source_not_admitted'))
      }
      console.log(JSON.stringify({ exchange, symbol, date: '2026-10-01', volume_exact: exact, parsed_number: stock.bars[0].volume,
        exact_lots: lots, legacy_number_safe: Number.isSafeInteger(stock.bars[0].volume), overview: price.status }))
    }
  }
  console.log(JSON.stringify({ passed: true, actual_http_routes: routes, response_parser: 'product fetch + Response.json',
    source: 'synthetic memory fixtures', disk_artifacts: 0, production_vite_build: 'not_run', disk_evidence_gate: 'not_tested' }))
}

async function serve() {
  const port = Number(option('--port', '8766'))
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('invalid owned preview port')
  const build = await esbuild.build({ entryPoints: [path.join(sourceRoot, 'main.tsx')], bundle: true, write: false,
    absWorkingDir: path.join(root, 'frontend'), nodePaths: [dependencies], outdir: '__memory_only__',
    platform: 'browser', format: 'esm', target: 'es2020', jsx: 'automatic',
    define: { 'import.meta.env.VITE_API_BASE': JSON.stringify('/api'), 'process.env.NODE_ENV': JSON.stringify('development') } })
  const script = build.outputFiles.find((file) => file.path.endsWith('.js')).contents
  // Existing production CSS requests a remote font. Preview uses the local
  // fallback and removes only @import statements from its in-memory response.
  const css = build.outputFiles.find((file) => file.path.endsWith('.css')).text.replace(/@import\s+(?:url\([^)]*\)|["'][^"']*["'])\s*;/g, '')
  const html = fs.readFileSync(path.join(root, 'frontend/index.html'), 'utf8')
    .replace('<div id="root"></div>', '<p style="padding:8px 16px;color:#f5b85b">記憶體合成資料・2026-10-01・成交量精確呈現驗證</p><div id="root"></div>')
    .replace('src="/src/main.tsx"', 'src="/app.js"').replace('</head>', '<link rel="stylesheet" href="/app.css"></head>')
  const server = http.createServer(async (request, response) => {
    response.setHeader('Cache-Control', 'no-store')
    response.setHeader('Content-Security-Policy', "default-src 'self' data:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; font-src 'self' data:")
    if (request.method !== 'GET') { response.writeHead(405); response.end('read-only preview'); return }
    try {
      if (request.url.startsWith('/api/')) {
        const upstream = await fetch(apiOrigin.origin + request.url)
        response.writeHead(upstream.status, { 'Content-Type': upstream.headers.get('content-type') || 'application/json' })
        response.end(Buffer.from(await upstream.arrayBuffer()))
      } else if (request.url === '/app.js') {
        response.writeHead(200, { 'Content-Type': 'text/javascript; charset=utf-8' }); response.end(script)
      } else if (request.url === '/app.css') {
        response.writeHead(200, { 'Content-Type': 'text/css; charset=utf-8' }); response.end(css)
      } else {
        response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }); response.end(html)
      }
    } catch (error) { response.writeHead(502); response.end(String(error)) }
  })
  server.listen(port, '127.0.0.1', () => console.log(JSON.stringify({ mode: 'memory full App + actual router proxy',
    url: `http://127.0.0.1:${port}/stocks/TWSE/MAX`, api: apiOrigin.origin, date: '2026-10-01', disk_artifacts: 0,
    font: 'local fallback; external CSS imports omitted in memory; CSP blocks external requests' })))
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => server.close(() => process.exit(0)))
}

Promise.resolve().then(() => args.includes('--serve') ? serve() : check()).catch((error) => { console.error(error); process.exitCode = 1 })
