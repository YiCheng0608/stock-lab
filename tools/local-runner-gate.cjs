'use strict'
// Cross-site / DNS-rebinding gate for loopback-only preview servers; the same rules as tools/local_runner_gate.py and the Issue 9 combos
// preview. A preview never emits CORS headers, so a cross-origin preflight fails by itself; this also refuses the simple requests a
// foreign page can still send, before the handler reads a body, forwards to the local API or changes any state.
//   Host must be exactly 127.0.0.1:<port>; Sec-Fetch-Site (when sent) a single same-origin|none; Origin (when sent) a single
//   http://127.0.0.1:<port>; every POST a single application/json (optional charset=utf-8), judged on the ORIGINAL request headers,
//   so a preview that rewrites the forwarded Content-Type can never launder a form or text/plain request.
// Limit: a browser without Fetch Metadata sends neither Sec-Fetch-Site nor (on a GET) Origin, so its cross-site no-cors GET still
// carries the exact Host and is admitted; the response is opaque and every source-fetching or state-changing call is a POST.
const fs = require('node:fs')
const assert = require('node:assert/strict')

// Node DISCARDS duplicate Host and Content-Type values in req.headers, which would hide a duplicated guard header: read rawHeaders.
function headerValues(rawHeaders, name) {
  const values = []
  for (let i = 0; i + 1 < rawHeaders.length; i += 2) if (rawHeaders[i].toLowerCase() === name) values.push(rawHeaders[i + 1])
  return values
}
const JSON_MEDIA = /^application\/json(?:\s*;\s*charset=utf-8)?$/i

function create(port) {
  assert(Number.isInteger(port) && port >= 1024 && port <= 65535, 'finite local port required')
  const ownHost = '127.0.0.1:' + port, ownOrigin = 'http://' + ownHost
  function refusal(method, rawHeaders) {
    const host = headerValues(rawHeaders, 'host')
    if (host.length !== 1 || host[0] !== ownHost) return { status: 403, reason: 'host_not_admitted' }
    const site = headerValues(rawHeaders, 'sec-fetch-site')
    if (site.length && (site.length !== 1 || !['same-origin', 'none'].includes(site[0].toLowerCase()))) return { status: 403, reason: 'cross_site_rejected' }
    const origin = headerValues(rawHeaders, 'origin')
    if (origin.length && (origin.length !== 1 || origin[0] !== ownOrigin)) return { status: 403, reason: 'origin_not_admitted' }
    if (method === 'POST') {
      const type = headerValues(rawHeaders, 'content-type')
      if (type.length !== 1 || !JSON_MEDIA.test(type[0].trim())) return { status: 415, reason: 'content_type_json_required' }
    }
    return null
  }
  // The preview's one way to create its server: refuse first, then hand the untouched request to the handler.
  function createServer(http, options, handler) {
    return http.createServer((request, response) => {
      const refused = refusal(request.method, request.rawHeaders)
      if (refused) {
        if (options.onRefuse) options.onRefuse(refused)
        response.writeHead(refused.status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' })
        response.end(JSON.stringify({ reason: refused.reason }))
        return undefined
      }
      return handler(request, response)
    })
  }
  return { ownHost, ownOrigin, refusal, createServer }
}

function flat(pairs) { return pairs.flat() }
function refusalVariants(method, port) {
  const host = '127.0.0.1:' + port, origin = 'http://' + host
  const base = [['Host', host], ...(method === 'POST' ? [['Content-Type', 'application/json']] : [])]
  const replaced = (name, value) => [...base.filter(([k]) => k.toLowerCase() !== name.toLowerCase()), ...(value === null ? [] : [[name, value]])]
  const cases = []
  for (const bad of ['localhost:' + port, '127.0.0.1', '127.0.0.1:' + (port + 1), '127.0.0.1:' + port + '.evil.example', 'evil.example', 'evil.example:' + port, '[::1]:' + port, '127.0.0.1:0' + port, '127.0.0.2:' + port, '']) cases.push(['Host ' + JSON.stringify(bad), replaced('Host', bad), 403, 'host_not_admitted'])
  cases.push(['missing Host', replaced('Host', null), 403, 'host_not_admitted'], ['duplicated Host', [...base, ['Host', 'evil.example']], 403, 'host_not_admitted'])
  for (const value of ['cross-site', 'same-site', 'Cross-Site', '', 'same-origin, cross-site', 'unknown']) cases.push(['Sec-Fetch-Site ' + JSON.stringify(value), [...base, ['Sec-Fetch-Site', value]], 403, 'cross_site_rejected'])
  cases.push(['duplicated Sec-Fetch-Site', [...base, ['Sec-Fetch-Site', 'same-origin'], ['Sec-Fetch-Site', 'cross-site']], 403, 'cross_site_rejected'])
  for (const value of ['http://evil.example', 'null', 'http://localhost:' + port, 'http://127.0.0.1:' + (port + 1), 'https://' + host, origin + '/', origin + '.evil.example', '', 'http://evil.example, ' + origin]) cases.push(['Origin ' + JSON.stringify(value), [...base, ['Origin', value]], 403, 'origin_not_admitted'])
  cases.push(['duplicated Origin', [...base, ['Origin', origin], ['Origin', 'http://evil.example']], 403, 'origin_not_admitted'])
  if (method === 'POST') {
    for (const value of ['text/plain', 'text/plain;charset=UTF-8', 'application/x-www-form-urlencoded', 'multipart/form-data; boundary=x', 'application/json5', 'application/jsonx', 'text/json', 'application/json; charset=latin-1', 'application/json; boundary=x', '']) cases.push(['Content-Type ' + JSON.stringify(value), replaced('Content-Type', value), 415, 'content_type_json_required'])
    cases.push(['missing Content-Type', replaced('Content-Type', null), 415, 'content_type_json_required'], ['duplicated Content-Type', [...base, ['Content-Type', 'text/plain']], 415, 'content_type_json_required'])
    cases.push(['foreign no-cors text POST', [...replaced('Content-Type', 'text/plain'), ['Origin', 'http://evil.example'], ['Sec-Fetch-Site', 'cross-site']], 403, 'cross_site_rejected'])
  }
  return cases.map(([label, pairs, status, reason]) => ({ label, rawHeaders: flat(pairs), status, reason }))
}
function admittedVariants(method, port) {
  const host = '127.0.0.1:' + port, origin = 'http://' + host
  const base = [['Host', host], ...(method === 'POST' ? [['Content-Type', 'application/json']] : [])]
  const cases = [['exact Host', base], ['same-origin page', [...base, ['Origin', origin], ['Sec-Fetch-Site', 'same-origin']]], ['address bar', [...base, ['Sec-Fetch-Site', 'none']]], ['SAME-ORIGIN spelling', [...base, ['Sec-Fetch-Site', 'SAME-ORIGIN']]]]
  if (method === 'POST') cases.push(['JSON with charset', [['Host', host], ['Content-Type', 'Application/JSON; charset=UTF-8'], ['Origin', origin]]])
  return cases.map(([label, pairs]) => ({ label, rawHeaders: flat(pairs) }))
}

// RAM-only conformance for one preview (no dependency, socket, listener or file write): the rule table through a fake http module on
// every endpoint the preview serves, plus proof that the preview file creates its server only through the gate.
function selfCheck({ file, port, endpoints }) {
  const gate = create(port), source = fs.readFileSync(file, 'utf8')
  assert(!/\bhttp\.createServer\(/.test(source) && /\bgate\.createServer\(http,/.test(source), 'the preview creates its server only through gate.createServer')
  const result = { port, endpoints: endpoints.length, refused: 0, admitted: 0, handler_calls_on_refusal: 0, onRefuse_calls: 0 }
  let handled = 0, listener
  const fakeHttp = { createServer: (fn) => { listener = fn; return {} } }
  gate.createServer(fakeHttp, { onRefuse: () => { result.onRefuse_calls++ } }, (request, response) => { handled++; response.writeHead(200, {}); response.end('{}') })
  const run = (method, rawHeaders) => {
    const out = { status: null, body: null }
    listener({ method, rawHeaders, url: '/' }, { writeHead: (status) => { out.status = status }, end: (body) => { out.body = body } })
    return out
  }
  for (const [method, target] of endpoints) {
    assert(target.startsWith('/'), 'endpoint path')
    for (const variant of refusalVariants(method, port)) {
      const before = handled, out = run(method, variant.rawHeaders)
      assert.equal(out.status, variant.status, method + ' ' + target + ' ' + variant.label)
      assert.deepEqual(JSON.parse(out.body), { reason: variant.reason }, method + ' ' + target + ' ' + variant.label)
      assert.equal(handled, before, 'handler never runs for ' + variant.label)
      result.refused++
    }
    for (const variant of admittedVariants(method, port)) {
      const before = handled, out = run(method, variant.rawHeaders)
      assert.equal(out.status, 200, method + ' ' + target + ' admitted ' + variant.label)
      assert.equal(handled, before + 1, 'handler runs once for ' + variant.label)
      result.admitted++
    }
  }
  assert.equal(result.onRefuse_calls, result.refused, 'every refusal is counted')
  // Rules with explicit expectations, independent of the generated table.
  const own = '127.0.0.1:' + port
  const expect = (method, raw, expected, label) => assert.deepEqual(gate.refusal(method, raw) && gate.refusal(method, raw).reason, expected, label)
  expect('GET', ['Host', own], null, 'exact Host admitted')
  expect('DELETE', ['Host', own], null, 'DELETE has no Content-Type rule (the UI sends none)')
  expect('POST', ['Host', own, 'Content-Type', 'application/json'], null, 'JSON POST admitted')
  expect('GET', [], 'host_not_admitted', 'missing Host')
  expect('POST', ['Host', own], 'content_type_json_required', 'POST without Content-Type')
  expect('POST', ['Host', own, 'Content-Type', 'text/plain', 'Origin', 'http://evil.example', 'Sec-Fetch-Site', 'cross-site'], 'cross_site_rejected', 'foreign simple POST refused on site first')
  result.explicit_rules = 6
  return result
}

// `--gate-check` entry for a preview file: parses --port from argv, prints the receipt, exits before any dependency loads.
function gateCheck({ file, defaultPort, endpoints }) {
  const index = process.argv.indexOf('--port'), port = index < 0 ? defaultPort : Number(process.argv[index + 1])
  try {
    console.log(JSON.stringify({ gate_check: true, file: require('node:path').basename(file), ...selfCheck({ file, port, endpoints }), network: 0, disk_artifacts: 0 }))
  } catch (error) {
    console.error(error)
    process.exit(1)
  }
  process.exit(0)
}

module.exports = { create, refusalVariants, admittedVariants, selfCheck, gateCheck, headerValues }
