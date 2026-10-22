#!/usr/bin/env node
// Headless Edge (or Chrome) screenshots over the DevTools protocol (Issue #227).
// For each width: load the page, wait until no skeleton / aria-busy element is left,
// open every <details>, then save <name>-<width>.png (full page) and <name>-<width>.txt
// (document.body.innerText). Prints one JSON line per width with scrollWidth, clientWidth,
// console errors and failed /api/ responses. Exit 1 when a width never became ready.
'use strict'

const { spawn, spawnSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const USAGE = `usage: node tools/ops/screenshot.cjs --url <page> --out <dir> [options]

  --url <page>         page to capture, e.g. http://127.0.0.1:4227/themes
  --out <dir>          output directory (created when missing)
  --name <name>        file prefix; default from the URL path ("/" -> "today")
  --widths <list>      comma separated viewport widths; default 1280,390
  --wait-for <css>     also wait until this selector exists
  --click <css>        after the page is ready, click this element and wait again;
                       repeatable, in order (e.g. --click '#stock-tab-research')
  --timeout-ms <n>     per-width ready timeout; default 60000
  --browser <path>     browser executable; default $SCREENSHOT_BROWSER, then Edge, then Chrome
  -h, --help           show this help

Writes <out>/<name>-<width>.png and <out>/<name>-<width>.txt and prints one JSON line per
width: {"url","width","ready","png","txt","scrollWidth","clientWidth","overflow",
"consoleErrors","httpErrors","missingClicks"}. Exit 0 when every width became ready, 1 otherwise, 2 on usage.`

// Phone widths use mobile emulation; heights are the viewport before the full-page capture.
const MOBILE_MAX_WIDTH = 600
const VIEWPORT_HEIGHT = { desktop: 900, mobile: 844 }
const MAX_CAPTURE_HEIGHT = 20000
// A cold browser start on a shared CI runner can take well over 30 s.
const BROWSER_START_MS = 90000
const POLL_MS = 250
// The page is ready after this many consecutive polls with no loading marker.
const STABLE_POLLS = 3
const LOADING_SELECTOR = '.skeleton, [aria-busy="true"]'
// The app ships no favicon; its 404 is not a page failure.
const IGNORED_HTTP = /\/favicon\.ico(\?|$)/

function parseArgs(argv) {
  const options = { widths: [1280, 390], timeoutMs: 60000, clicks: [] }
  const names = {
    '--url': 'url', '--out': 'out', '--name': 'name', '--widths': 'widths',
    '--wait-for': 'waitFor', '--timeout-ms': 'timeoutMs', '--browser': 'browser', '--click': 'clicks',
  }
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    if (arg === '-h' || arg === '--help') return { help: true }
    const key = names[arg]
    if (!key) throw new Error(`unknown argument: ${arg}`)
    const value = argv[i + 1]
    if (value === undefined || value.startsWith('--')) throw new Error(`${arg} needs a value`)
    i += 1
    if (key === 'widths') {
      options.widths = value.split(',').map((item) => Number(item.trim()))
      if (!options.widths.length || options.widths.some((w) => !Number.isInteger(w) || w < 200 || w > 4000)) {
        throw new Error('--widths must be integers between 200 and 4000')
      }
    } else if (key === 'clicks') {
      options.clicks.push(value)
    } else if (key === 'timeoutMs') {
      options.timeoutMs = Number(value)
      if (!Number.isInteger(options.timeoutMs) || options.timeoutMs <= 0) throw new Error('--timeout-ms must be a positive integer')
    } else {
      options[key] = value
    }
  }
  if (!options.url) throw new Error('--url is required')
  if (!options.out) throw new Error('--out is required')
  if (!/^https?:\/\//.test(options.url)) throw new Error('--url must start with http:// or https://')
  if (options.name !== undefined && !/^[A-Za-z0-9._-]+$/.test(options.name)) throw new Error('--name may only use letters, digits, ".", "_" and "-"')
  options.name = options.name ?? defaultName(options.url)
  return options
}

// "/" -> "today", "/themes?board=theme" -> "themes-board-theme", "/stocks/TWSE/2330" -> "stocks-TWSE-2330".
function defaultName(url) {
  const parsed = new URL(url)
  const parts = [parsed.pathname, parsed.search].join('-').split(/[^A-Za-z0-9]+/).filter(Boolean)
  return parts.length ? parts.join('-') : 'today'
}

function findBrowser(env = process.env, platform = process.platform, exists = fs.existsSync) {
  if (env.SCREENSHOT_BROWSER) return env.SCREENSHOT_BROWSER
  const candidates = platform === 'win32'
    ? [
        path.join(env['ProgramFiles(x86)'] ?? 'C:\\Program Files (x86)', 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
        path.join(env.ProgramFiles ?? 'C:\\Program Files', 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
        path.join(env.ProgramFiles ?? 'C:\\Program Files', 'Google', 'Chrome', 'Application', 'chrome.exe'),
      ]
    : platform === 'darwin'
      ? ['/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome']
      : ['/usr/bin/microsoft-edge', '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser']
  return candidates.find((candidate) => exists(candidate)) ?? null
}

function browserArgs(profileDir, platform = process.platform) {
  const args = [
    '--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profileDir}`,
    '--no-first-run', '--no-default-browser-check', '--disable-gpu', '--hide-scrollbars',
    '--disable-extensions', '--mute-audio',
  ]
  // Ubuntu 24.04 restricts unprivileged user namespaces, which the Chrome sandbox needs;
  // CI containers also give /dev/shm too little room for the renderer.
  if (platform === 'linux') args.push('--no-sandbox', '--disable-dev-shm-usage')
  return [...args, 'about:blank']
}

function viewport(width) {
  const mobile = width <= MOBILE_MAX_WIDTH
  return { width, height: mobile ? VIEWPORT_HEIGHT.mobile : VIEWPORT_HEIGHT.desktop, deviceScaleFactor: 1, mobile }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

// The browser writes DevToolsActivePort once it listens; stop early when it fails first.
async function waitForPortFile(file, child, stderr, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const text = fs.readFileSync(file, 'utf8')
      if (text.includes('\n')) return text
    } catch {
      // not written yet
    }
    // Exit 0 is not a failure: msedge.exe on Windows can hand off to another process and exit.
    if ((child.exitCode !== null && child.exitCode !== 0) || child.signalCode !== null) {
      throw new Error(`browser exited (${child.exitCode ?? child.signalCode}) before listening; stderr: ${stderr.tail() || '(empty)'}`)
    }
    await sleep(100)
  }
  throw new Error(`browser did not write ${file} within ${timeoutMs} ms; stderr: ${stderr.tail() || '(empty)'}`)
}

// Keeps the last few KB of the browser's stderr for error messages.
function stderrTail(stream, limit = 4000) {
  let text = ''
  stream.setEncoding('utf8')
  stream.on('data', (chunk) => { text = (text + chunk).slice(-limit) })
  return { tail: () => text.trim().split('\n').slice(-15).join(' | ') }
}

class Cdp {
  constructor(url) {
    this.nextId = 1
    this.pending = new Map()
    this.listeners = []
    this.socket = new WebSocket(url)
    this.opened = new Promise((resolve, reject) => {
      this.socket.addEventListener('open', resolve, { once: true })
      this.socket.addEventListener('error', () => reject(new Error('DevTools socket failed')), { once: true })
    })
    this.socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data)
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id)
        this.pending.delete(message.id)
        if (message.error) reject(new Error(`${message.error.message} (${message.error.code})`))
        else resolve(message.result)
      } else if (message.method) {
        this.listeners.forEach((listener) => listener(message))
      }
    })
  }

  send(method, params = {}) {
    const id = this.nextId
    this.nextId += 1
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
      this.socket.send(JSON.stringify({ id, method, params }))
    })
  }

  async evaluate(expression) {
    const result = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    if (result.exceptionDetails) throw new Error(`page script failed: ${result.exceptionDetails.text}`)
    return result.result.value
  }

  close() {
    this.socket.close()
  }
}

const READY_PROBE = (waitFor) => `(() => {
  if (document.readyState !== 'complete') return false
  if (document.querySelector(${JSON.stringify(LOADING_SELECTOR)})) return false
  ${waitFor ? `if (!document.querySelector(${JSON.stringify(waitFor)})) return false` : ''}
  return true
})()`

// Ready: no loading marker, no request in flight (the navbar date badge has no skeleton).
async function waitReady(cdp, watch, waitFor, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  let stable = 0
  while (Date.now() < deadline) {
    stable = watch.inflight.size === 0 && (await cdp.evaluate(READY_PROBE(waitFor))) ? stable + 1 : 0
    if (stable >= STABLE_POLLS) return true
    await sleep(POLL_MS)
  }
  return false
}

async function captureWidth(cdp, options, width, watch) {
  watch.consoleErrors.length = 0
  watch.httpErrors.length = 0
  watch.inflight.clear()
  await cdp.send('Emulation.setDeviceMetricsOverride', viewport(width))
  await cdp.send('Page.navigate', { url: options.url })
  await sleep(POLL_MS)
  let ready = await waitReady(cdp, watch, options.waitFor, options.timeoutMs)
  const missingClicks = []
  for (const selector of options.clicks) {
    const clicked = await cdp.evaluate(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return false; el.click(); return true })()`)
    if (!clicked) missingClicks.push(selector)
    await sleep(POLL_MS)
    ready = (await waitReady(cdp, watch, options.waitFor, options.timeoutMs)) && ready
  }
  if (missingClicks.length) ready = false
  await cdp.evaluate("document.querySelectorAll('details').forEach((d) => { d.open = true }); true")
  // Opening <details> can mount more content; give it one more settle.
  if (ready) ready = await waitReady(cdp, watch, options.waitFor, Math.min(options.timeoutMs, 10000))
  const metrics = await cdp.evaluate(`({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    scrollHeight: document.documentElement.scrollHeight,
    text: document.body ? document.body.innerText : '',
  })`)
  const shot = await cdp.send('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: true,
    clip: { x: 0, y: 0, width: Math.max(width, metrics.scrollWidth), height: Math.min(metrics.scrollHeight, MAX_CAPTURE_HEIGHT), scale: 1 },
  })
  const png = path.join(options.out, `${options.name}-${width}.png`)
  const txt = path.join(options.out, `${options.name}-${width}.txt`)
  fs.writeFileSync(png, Buffer.from(shot.data, 'base64'))
  fs.writeFileSync(txt, metrics.text, 'utf8')
  return {
    url: options.url,
    width,
    ready,
    png: png.split(path.sep).join('/'),
    txt: txt.split(path.sep).join('/'),
    scrollWidth: metrics.scrollWidth,
    clientWidth: metrics.clientWidth,
    overflow: metrics.scrollWidth > metrics.clientWidth,
    consoleErrors: watch.consoleErrors.slice(0, 10),
    httpErrors: watch.httpErrors.slice(0, 10),
    missingClicks,
  }
}

// Browser helper processes can hold profile files for a few seconds after the browser exits.
async function removeProfile(profileDir) {
  for (let attempt = 1; ; attempt += 1) {
    try {
      fs.rmSync(profileDir, { recursive: true, force: true })
      return
    } catch (error) {
      if (attempt >= 20) {
        console.error(`screenshot: warning: could not remove ${profileDir}: ${error.message}`)
        return
      }
      await sleep(500)
    }
  }
}

async function run(options) {
  const browser = options.browser ?? findBrowser()
  if (!browser) throw new Error('no Edge or Chrome found; pass --browser or set SCREENSHOT_BROWSER')
  fs.mkdirSync(options.out, { recursive: true })
  const profileDir = fs.mkdtempSync(path.join(path.resolve(options.out), '.browser-'))
  const child = spawn(browser, browserArgs(profileDir), { stdio: ['ignore', 'ignore', 'pipe'] })
  const stderr = stderrTail(child.stderr)
  const exited = new Promise((resolve) => child.once('exit', resolve))
  let cdp
  let allReady = true
  try {
    const active = await waitForPortFile(path.join(profileDir, 'DevToolsActivePort'), child, stderr, BROWSER_START_MS)
    const port = active.split('\n')[0].trim()
    const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()
    const page = targets.find((target) => target.type === 'page')
    if (!page) throw new Error('browser has no page target')
    cdp = new Cdp(page.webSocketDebuggerUrl)
    await cdp.opened
    const watch = { consoleErrors: [], httpErrors: [], inflight: new Set() }
    cdp.listeners.push((message) => {
      const { method, params } = message
      if (method === 'Network.requestWillBeSent') {
        watch.inflight.add(params.requestId)
      } else if (method === 'Network.loadingFinished' || method === 'Network.loadingFailed') {
        watch.inflight.delete(params.requestId)
      }
      if (method === 'Runtime.consoleAPICalled' && params.type === 'error') {
        watch.consoleErrors.push(params.args.map((arg) => arg.value ?? arg.description ?? '').join(' ').slice(0, 300))
      } else if (method === 'Runtime.exceptionThrown') {
        watch.consoleErrors.push((params.exceptionDetails.exception?.description ?? params.exceptionDetails.text).slice(0, 300))
      } else if (method === 'Network.responseReceived' && params.response.status >= 400 && !IGNORED_HTTP.test(params.response.url)) {
        watch.httpErrors.push(`${params.response.status} ${params.response.url}`)
      }
    })
    await Promise.all([cdp.send('Page.enable'), cdp.send('Runtime.enable'), cdp.send('Network.enable')])
    for (const width of options.widths) {
      const result = await captureWidth(cdp, options, width, watch)
      allReady = allReady && result.ready
      console.log(JSON.stringify(result))
    }
  } finally {
    if (cdp) {
      await cdp.send('Browser.close').catch(() => {})
      cdp.close()
    }
    await Promise.race([exited, sleep(5000)])
    if (child.exitCode === null) child.kill()
    await Promise.race([exited, sleep(5000)])
    await removeProfile(profileDir)
  }
  return allReady ? 0 : 1
}

function main(argv) {
  let options
  try {
    options = parseArgs(argv)
  } catch (error) {
    console.error(`screenshot: ${error.message}\n\n${USAGE}`)
    return Promise.resolve(2)
  }
  if (options.help) {
    console.log(USAGE)
    return Promise.resolve(0)
  }
  return run(options).catch((error) => {
    console.error(`screenshot: ${error.message}`)
    return 1
  })
}

if (require.main === module) {
  // Node 20 keeps the WebSocket global behind a flag; Node 22 has it by default.
  if (typeof WebSocket === 'undefined') {
    const result = spawnSync(process.execPath, ['--experimental-websocket', __filename, ...process.argv.slice(2)], { stdio: 'inherit' })
    process.exit(result.status ?? 1)
  }
  main(process.argv.slice(2)).then((code) => { process.exitCode = code })
}

module.exports = { parseArgs, defaultName, findBrowser, browserArgs, viewport, USAGE }
