#!/usr/bin/env node
// Issue #300 evidence: page height and first screen as a visitor sees them (no <details> opened),
// plus the search-bar geometry of the news page. Headless Edge over CDP, same start-up as
// tools/ops/screenshot.cjs (whose findBrowser/browserArgs/viewport it reuses).
//
// usage: node measure.cjs <web origin> <out dir> <name>=<path>[@<click css>] ...
// Prints one JSON line per page and width: scrollHeight, scrollWidth, clientWidth, overflow and,
// on /news pages, the rects of the filter form's controls. Writes <name>-<width>-first.png
// (viewport) and <name>-<width>-full.png (full page, details as rendered).
'use strict'
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')
const { findBrowser, browserArgs, viewport } = require('C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/task-300-mobile-layout/tools/ops/screenshot.cjs')

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const WIDTHS = (process.env.WIDTHS || '1280,390').split(',').map(Number)

async function main() {
  const [web, out, ...pages] = process.argv.slice(2)
  fs.mkdirSync(out, { recursive: true })
  const profile = fs.mkdtempSync(path.join(path.resolve(out), '.browser-'))
  const child = spawn(findBrowser(), browserArgs(profile), { stdio: 'ignore' })
  let port
  for (let i = 0; i < 600 && !port; i += 1) {
    try { port = fs.readFileSync(path.join(profile, 'DevToolsActivePort'), 'utf8').split('\n')[0].trim() } catch { await sleep(100) }
  }
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()
  const ws = new WebSocket(targets.find((t) => t.type === 'page').webSocketDebuggerUrl)
  await new Promise((r) => ws.addEventListener('open', r, { once: true }))
  let next = 1
  const pending = new Map()
  const inflight = new Set()
  ws.addEventListener('message', (e) => {
    const m = JSON.parse(e.data)
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id) }
    if (m.method === 'Network.requestWillBeSent') inflight.add(m.params.requestId)
    if (m.method === 'Network.loadingFinished' || m.method === 'Network.loadingFailed') inflight.delete(m.params.requestId)
  })
  const send = (method, params = {}) => new Promise((r) => { const id = next++; pending.set(id, r); ws.send(JSON.stringify({ id, method, params })) })
  const evaluate = async (expression) => (await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })).result.value
  const ready = async () => {
    let stable = 0
    for (let i = 0; i < 240 && stable < 3; i += 1) {
      const ok = inflight.size === 0 && await evaluate("document.readyState === 'complete' && !document.querySelector('.skeleton, [aria-busy=\"true\"]')")
      stable = ok ? stable + 1 : 0
      await sleep(250)
    }
    return stable >= 3
  }
  await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable')
  for (const spec of pages) {
    const [name, rest] = spec.split(/=(.*)/s)
    const [route, click] = rest.split('@')
    for (const width of WIDTHS) {
      const vp = viewport(width)
      await send('Emulation.setDeviceMetricsOverride', vp)
      const nav = await send('Page.navigate', { url: web + route }); if (process.env.DEBUG) console.error(web + route, JSON.stringify(nav))
      await sleep(250)
      let ok = await ready()
      if (click) { await evaluate(`document.querySelector(${JSON.stringify(click)})?.click()`); await sleep(250); ok = (await ready()) && ok }
      await evaluate('window.scrollTo(0, 0)')
      const m = await evaluate(`(() => {
        const d = document.documentElement
        const rect = (el) => { const r = el.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)] }
        const form = document.querySelector('form.news-filters')
        return {
          scrollHeight: d.scrollHeight, scrollWidth: d.scrollWidth, clientWidth: d.clientWidth,
          filters: form ? { form: rect(form), controls: [...form.children].map((el) => [el.getAttribute('aria-label') || el.textContent.trim(), ...rect(el)]) } : undefined,
        }
      })()`)
      const first = await send('Page.captureScreenshot', { format: 'png' })
      fs.writeFileSync(path.join(out, `${name}-${width}-first.png`), Buffer.from(first.data, 'base64'))
      const full = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: 0, width, height: Math.min(m.scrollHeight, 20000), scale: 1 } })
      fs.writeFileSync(path.join(out, `${name}-${width}-full.png`), Buffer.from(full.data, 'base64'))
      console.log(JSON.stringify({ name, width, ready: ok, overflow: m.scrollWidth > m.clientWidth, ...m }))
    }
  }
  await send('Browser.close').catch(() => {})
  await sleep(1500)
  if (child.exitCode === null) child.kill()
  await sleep(1500)
  fs.rmSync(profile, { recursive: true, force: true })
}
main().catch((e) => { console.error(e); process.exit(1) })
