// Measure the news filter bar: one JSON line per URL and width with the bar's children rects (#270 evidence).
// usage: node --experimental-websocket measure.cjs <url> [<url>...]
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const PROFILE = 'C:/v270/edge-measure'
const PORT = 9327
const WIDTHS = [1280, 1024, 860, 390]
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function main(urls) {
  fs.mkdirSync(PROFILE, { recursive: true })
  const child = spawn(EDGE, ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`, '--no-first-run', 'about:blank'], { stdio: 'ignore' })
  let pages = null
  for (let i = 0; i < 60 && !pages; i++) {
    try { pages = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json() } catch { await sleep(500) }
  }
  const page = pages.find((p) => p.type === 'page')
  const ws = new WebSocket(page.webSocketDebuggerUrl)
  await new Promise((resolve) => ws.addEventListener('open', resolve))
  let id = 0
  const waiting = new Map()
  ws.addEventListener('message', (event) => {
    const msg = JSON.parse(event.data)
    if (msg.id && waiting.has(msg.id)) { waiting.get(msg.id)(msg); waiting.delete(msg.id) }
  })
  const send = (method, params = {}) => new Promise((resolve) => { const n = ++id; waiting.set(n, resolve); ws.send(JSON.stringify({ id: n, method, params })) })
  const evaluate = async (expression) => (await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })).result?.result?.value
  for (const url of urls) {
    for (const width of WIDTHS) {
      await send('Emulation.setDeviceMetricsOverride', { width, height: 900, deviceScaleFactor: 1, mobile: width < 640 })
      await send('Page.navigate', { url })
      for (let i = 0; i < 60; i++) {
        await sleep(500)
        if (await evaluate("document.fonts.status === 'loaded' && !!document.querySelector('.news-card') && !document.querySelector('.skeleton')")) break
      }
      const rects = await evaluate(`(() => {
        const r = (el) => { const b = el.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.top), Math.round(b.right), Math.round(b.bottom)] }
        const form = document.querySelector('.news-filters')
        return { tabs: r(document.querySelector('.news-controls .tabs')), form: r(form), children: [...form.children].map((el) => [el.getAttribute('aria-label') || el.textContent.trim(), ...r(el)]), cards: r(document.querySelector('.news-cards')) }
      })()`)
      const tops = new Set(rects.children.map((c) => c[2]))
      console.log(JSON.stringify({ url, width, oneRow: tops.size === 1, ...rects }))
    }
  }
  ws.close()
  child.kill()
}

main(process.argv.slice(2)).catch((error) => { console.error(error); process.exit(1) })
