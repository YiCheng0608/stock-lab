// #568 screenshots in headless Edge: the market page with the four US indexes from FinMind
// (S&P 500 and SOX selected), at 1280 and 390; also reads the page text for the source labels.
'use strict'
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const BASE = process.argv[2] || 'http://127.0.0.1:8569'
const OUT = process.argv[3] || 'C:/Users/YiCheng/t568/shots/out'
const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

class Cdp {
  constructor(url) {
    this.id = 1; this.pending = new Map()
    this.ws = new WebSocket(url)
    this.opened = new Promise((res, rej) => { this.ws.onopen = res; this.ws.onerror = () => rej(new Error('ws')) })
    this.ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.id && this.pending.has(m.id)) { const p = this.pending.get(m.id); this.pending.delete(m.id); m.error ? p.rej(new Error(m.error.message)) : p.res(m.result) } }
  }
  send(method, params = {}) { const id = this.id++; return new Promise((res, rej) => { this.pending.set(id, { res, rej }); this.ws.send(JSON.stringify({ id, method, params })) }) }
  async eval(expr) { const r = await this.send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error(r.exceptionDetails.text); return r.result.value }
}

async function ready(cdp) {
  for (let i = 0, stable = 0; i < 240; i++) {
    const ok = await cdp.eval(`document.readyState === 'complete' && !document.querySelector('.skeleton, [aria-busy="true"]') && !!document.querySelector('.market-index-row')`)
    stable = ok ? stable + 1 : 0
    if (stable >= 6) return true
    await sleep(250)
  }
  return false
}

async function shot(cdp, name, full) {
  let params = { format: 'png' }
  if (full) {
    const size = await cdp.eval(`({ width: document.documentElement.clientWidth, height: document.documentElement.scrollHeight })`)
    params = { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: 0, width: size.width, height: size.height, scale: 1 } }
  }
  const r = await cdp.send('Page.captureScreenshot', params)
  fs.writeFileSync(path.join(OUT, `${name}.png`), Buffer.from(r.data, 'base64'))
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true })
  const profile = fs.mkdtempSync(path.join(OUT, '.p-'))
  const child = spawn(EDGE, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--no-first-run', '--disable-gpu', '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' })
  let port
  for (let i = 0; i < 300 && !port; i++) { try { port = fs.readFileSync(path.join(profile, 'DevToolsActivePort'), 'utf8').split('\n')[0] } catch {} await sleep(100) }
  const page = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === 'page')
  const cdp = new Cdp(page.webSocketDebuggerUrl); await cdp.opened
  await cdp.send('Page.enable'); await cdp.send('Runtime.enable')
  const log = []
  try {
    for (const [width, height, mobile] of [[1280, 800, false], [390, 844, true]]) {
      await cdp.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile })
      for (const index of ['spx', 'sox']) {
        await cdp.send('Page.navigate', { url: `${BASE}/market?index=${index}` }); await sleep(300)
        const ok = await ready(cdp)
        // Open the data notes and the chart's data table so their text is in the shot.
        await cdp.eval(`[...document.querySelectorAll('details')].forEach((d) => { d.open = true }); true`)
        await sleep(800)
        await shot(cdp, `market-${index}-${width}`, true)
        const text = await cdp.eval(`document.body.innerText`)
        log.push({
          width, index, ready: ok,
          scrollWidth: await cdp.eval(`document.documentElement.scrollWidth`),
          clientWidth: await cdp.eval(`document.documentElement.clientWidth`),
          finmindLines: text.split('\n').filter((line) => line.includes('FinMind')),
          fredLines: text.split('\n').filter((line) => line.includes('FRED')),
          closeOnlyNote: text.includes('來源只提供收盤價'),
          chartMeta: text.split('\n').filter((line) => line.includes('來源 ')).slice(0, 3),
        })
      }
    }
  } finally {
    fs.writeFileSync(path.join(OUT, 'shots.json'), JSON.stringify(log, null, 2))
    cdp.ws.close(); child.kill()
    await sleep(500)
    fs.rmSync(profile, { recursive: true, force: true })
  }
}

main().catch((e) => { console.error(e); process.exit(1) })
