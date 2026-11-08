// #564 evidence in headless Edge: first-screen and table close-ups without opening <details>, and the
// keyboard / click selection (Tab to a row's button, Enter; a click on a row cell; reload keeps ?index=).
'use strict'
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const BASE = process.argv[2] || 'http://127.0.0.1:8564'
const OUT = process.argv[3] || 'C:/Users/YiCheng/t564/shots'
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
    if (stable >= 4) return true
    await sleep(250)
  }
  return false
}

async function shot(cdp, name, clip) {
  const r = await cdp.send('Page.captureScreenshot', clip ? { format: 'png', captureBeyondViewport: true, clip: { ...clip, scale: 1 } } : { format: 'png' })
  fs.writeFileSync(path.join(OUT, `${name}.png`), Buffer.from(r.data, 'base64'))
}

async function key(cdp, k, code, vk) {
  await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: k, code, windowsVirtualKeyCode: vk, ...(k === 'Enter' ? { text: String.fromCharCode(13), unmodifiedText: String.fromCharCode(13) } : {}) })
  await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: k, code, windowsVirtualKeyCode: vk })
}

const state = `(() => ({ url: location.pathname + location.search, chart: document.querySelector('#market-chart-title')?.textContent,
  selected: [...document.querySelectorAll('.market-index-row.is-selected')].map((r) => r.dataset.index),
  pressed: [...document.querySelectorAll('.market-index-select[aria-pressed="true"]')].map((b) => b.textContent),
  focus: (document.activeElement?.textContent ?? '').slice(0, 30), scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth }))()`

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
      await cdp.send('Page.navigate', { url: `${BASE}/market` }); await sleep(300); await ready(cdp)
      await shot(cdp, `first-${width}`)
      const box = await cdp.eval(`(() => { const r = document.querySelector('.market-indexes').getBoundingClientRect(); return { x: 0, y: r.top + scrollY, width: ${width}, height: r.height } })()`)
      await shot(cdp, `table-${width}`, box)
      log.push({ width, firstScreen: await cdp.eval(`(() => { const rows = [...document.querySelectorAll('.market-index-row')].map((r) => [r.dataset.index, Math.round(r.getBoundingClientRect().bottom)]); return { rows, viewport: innerHeight, chartTitleTop: Math.round(document.querySelector('#market-chart-title').getBoundingClientRect().top) } })()`) })
      // Keyboard: Tab from the top of the page until the 台指期近月 button has focus, then Enter.
      await cdp.eval(`document.activeElement?.blur(); window.scrollTo(0, 0); true`)
      let tabs = 0
      for (; tabs < 80; tabs++) { await key(cdp, 'Tab', 'Tab', 9); if ((await cdp.eval(`document.activeElement?.textContent`)) === '台指期近月') break }
      const beforeEnter = await cdp.eval(state)
      await key(cdp, 'Enter', 'Enter', 13); await sleep(300); await ready(cdp)
      const afterEnter = await cdp.eval(state)
      // One more Tab reaches the next row's button; Space selects it.
      await key(cdp, 'Tab', 'Tab', 9)
      const nextFocus = await cdp.eval(`document.activeElement?.textContent`)
      await key(cdp, ' ', 'Space', 32); await sleep(300); await ready(cdp)
      const afterSpace = await cdp.eval(state)
      if (width === 1280) await shot(cdp, 'keyboard-focus-1280', await cdp.eval(`(() => { const r = document.querySelector('.market-indexes').getBoundingClientRect(); return { x: 0, y: r.top + scrollY, width: 1280, height: r.height } })()`))
      // A click on a cell (not the button) of the NASDAQ row.
      const cell = await cdp.eval(`(() => { const td = document.querySelector('[data-index="ixic"] .market-index-close'); td.scrollIntoView({ block: 'center' }); const r = td.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 } })()`)
      for (const type of ['mousePressed', 'mouseReleased']) await cdp.send('Input.dispatchMouseEvent', { type, x: cell.x, y: cell.y, button: 'left', clickCount: 1 })
      await sleep(300); await ready(cdp)
      const afterClick = await cdp.eval(state)
      const history = await cdp.eval('history.length')
      await cdp.send('Page.reload'); await sleep(300); await ready(cdp)
      const afterReload = await cdp.eval(state)
      if (width === 390) {
        const box2 = await cdp.eval(`(() => { const r = document.querySelector('.market-indexes').getBoundingClientRect(); return { x: 0, y: r.top + scrollY, width: 390, height: r.height } })()`)
        await shot(cdp, 'table-spx-selected-390', box2)
      }
      log.push({ width, tabs: tabs + 1, beforeEnter, afterEnter, nextFocus, afterSpace, afterClick, history, afterReload })
    }
  } finally {
    await cdp.send('Browser.close').catch(() => {})
    await sleep(1500); try { child.kill() } catch {}
    await sleep(1500); fs.rmSync(profile, { recursive: true, force: true })
  }
  console.log(JSON.stringify(log, null, 1))
}
main().catch((e) => { console.error(e); process.exit(1) })
