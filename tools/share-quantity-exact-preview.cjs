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
  const fixtureLabel = args.includes('--finance-read-fixture') ? '隔離合成庫存讀值・2026-10-04・非正式持倉／行情與交易日資料' : '隔離合成使用者股數・2026-10-03・非正式持倉／行情資料'
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
    pid: process.pid, url: `http://127.0.0.1:${port}/actions`, api: apiOrigin.origin, fixture_date: args.includes('--finance-read-fixture') ? '2026-10-04' : '2026-10-03',
    disk_artifacts: 0, font: 'local fallback; external imports omitted in memory; CSP blocks external requests' })))
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => server.close(() => { esbuild.stop(); process.exit(0) }))
}

Promise.resolve().then(() => args.includes('--serve') ? serve() : args.includes('--finance-read-http-check') ? financeReadHttpCheck()
  : args.includes('--finance-read-check') ? financeReadCheck() : args.includes('--finance-http-check') ? financeHttpCheck()
  : args.includes('--http-check') ? httpCheck() : args.includes('--finance-check') ? financeCheck() : check())
  .catch((error) => { esbuild.stop(); console.error(error); process.exitCode = 1 })
