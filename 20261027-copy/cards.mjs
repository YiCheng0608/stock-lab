// Element screenshots of action cards at a given width (#279 PR evidence). Usage:
// node --experimental-websocket cards.mjs <debug port> <url> <width> <out dir> <click css>... -- <name=css>...
import fs from 'node:fs'

const [port, url, width, out, ...rest] = process.argv.slice(2)
const split = rest.indexOf('--')
const clicks = rest.slice(0, split)
const targets = rest.slice(split + 1).map((item) => item.split(/=(.*)/s).slice(0, 2))
const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()
const ws = new WebSocket(pages.find((page) => page.type === 'page').webSocketDebuggerUrl)
await new Promise((resolve) => ws.addEventListener('open', resolve))
let id = 0
const pending = new Map()
ws.addEventListener('message', (event) => {
  const message = JSON.parse(event.data)
  if (pending.has(message.id)) { pending.get(message.id)(message); pending.delete(message.id) }
})
const send = (method, params = {}) => new Promise((resolve) => { const n = ++id; pending.set(n, resolve); ws.send(JSON.stringify({ id: n, method, params })) })
const evaluate = async (expression) => (await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })).result?.result?.value
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const idle = async () => {
  for (let quiet = 0, n = 0; quiet < 4 && n < 240; n++) {
    await sleep(500)
    quiet = await evaluate("!document.querySelector('[aria-busy=\"true\"], .skeleton') && document.querySelectorAll('[data-tier]').length > 0") ? quiet + 1 : 0
  }
}
await send('Emulation.setDeviceMetricsOverride', { width: Number(width), height: 900, deviceScaleFactor: 1, mobile: Number(width) < 641 })
await send('Page.enable')
await send('Page.navigate', { url })
await idle()
for (const css of clicks) { await evaluate(`document.querySelector(${JSON.stringify(css)})?.click()`); await sleep(2500); await idle() }
for (const [name, css] of targets) {
  const box = await evaluate(`(() => { const e = document.querySelector(${JSON.stringify(css)}); if (!e) return null; e.scrollIntoView({ block: 'center' }); const r = e.getBoundingClientRect(); return { x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height } })()`)
  if (!box) { console.log(`${name}: not found ${css}`); continue }
  const pad = 12
  const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { x: Math.max(0, box.x - pad), y: Math.max(0, box.y - pad), width: box.w + pad * 2, height: box.h + pad * 2, scale: 1 } })
  fs.writeFileSync(`${out}/${name}.png`, Buffer.from(shot.result.data, 'base64'))
  console.log(`${name}: ${Math.round(box.w)}x${Math.round(box.h)}`)
}
ws.close()
