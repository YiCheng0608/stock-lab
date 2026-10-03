/** Reconstructable memory-only M3-P1 quantity checks and full-App preview.
 * Existing --deps is borrowed read-only. --check needs no running server;
 * --http-check exercises the actual owned memory router after --serve starts.
 * No bundles, buildinfo, responses, screenshots, cache or test files are saved.
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
const apiOrigin = new URL(option('--api', 'http://127.0.0.1:8777'))
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


async function appModule() {
  const result = await esbuild.build({ entryPoints: [path.join(sourceRoot, 'App.tsx')], bundle: true, write: false,
    nodePaths: [dependencies], platform: 'node', format: 'cjs', packages: 'external', target: 'es2020', jsx: 'automatic',
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
    assert.ok(html.includes('1 至 9,007,199,254,740,991 股'))
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
    ]) {
      const saved = await api.upsertPortfolio({ symbol: 'NEW', exchange, ...fields })
      routes++
      assert.equal(saved.shares_exact, exact)
      const read = await api.getPortfolio({ q: 'NEW' })
      routes++
      assert.equal(read.items.find((item) => item.id === saved.id).shares_exact, exact)
    }
    const before = await api.getPortfolio({ q: 'NEW' })
    routes++
    const original = before.items.find((item) => item.instrument.exchange === exchange)
    for (const fields of [{ shares: 9007199254740992 }, { unit: 'lot', quantity: 9007199254741 },
      { unit: 'odd_lot', quantity: '9007199254740993' }, { shares: null }, { shares: true }, { shares: 1.5 }]) {
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
      pure_int64_orm_claim: false, rejected_legacy: ['ODDFLOAT', 'MAXFLOAT'] }))
  }
  console.log(JSON.stringify({ passed: true, actual_http_routes: routes, parser: 'product fetch + Response.json',
    source: 'synthetic user quantities, memory ORM commit/refresh/GET', disk_save_reopen: 'not_tested', disk_artifacts: 0 }))
  esbuild.stop()
}

async function serve() {
  const port = Number(option('--port', '8778'))
  if (port !== 8778 || apiOrigin.origin !== 'http://127.0.0.1:8777') throw new Error('only owned ports 8777/8778 are authorized')
  const build = await browserBuild()
  const script = build.outputFiles.find((file) => file.path.endsWith('.js')).contents
  const css = build.outputFiles.find((file) => file.path.endsWith('.css')).text
    .replace(/@import\s+(?:url\([^)]*\)|["'][^"']*["'])\s*;/g, '')
  const html = fs.readFileSync(path.join(root, 'frontend/index.html'), 'utf8')
    .replace('<div id="root"></div>', '<p style="padding:8px 16px;color:#f5b85b">記憶體合成使用者股數・2026-10-03・非正式持倉／磁碟保存驗收</p><div id="root"></div>')
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
  server.listen(port, '127.0.0.1', () => console.log(JSON.stringify({ mode: 'memory full App + owned actual portfolio router',
    pid: process.pid, url: 'http://127.0.0.1:8778/actions', api: apiOrigin.origin, fixture_date: '2026-10-03',
    disk_artifacts: 0, font: 'local fallback; external imports omitted in memory; CSP blocks external requests' })))
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => server.close(() => { esbuild.stop(); process.exit(0) }))
}

Promise.resolve().then(() => args.includes('--serve') ? serve() : args.includes('--http-check') ? httpCheck() : check())
  .catch((error) => { esbuild.stop(); console.error(error); process.exitCode = 1 })

