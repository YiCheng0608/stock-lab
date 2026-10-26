// #276 evidence: first-screen crops and full pages in the collapsed default state, the #269 probe
// (6394571906 §1) adapted to the real page, and element clips for the level-colour before/after shots.
// Usage: node shots276.cjs <repo> <out dir> <jobs.json>
// jobs: [{ name, url, width, height?, mode: 'first'|'full'|'clip', selector?, clicks?: [css], open?: [css], probe?: bool, maxHeight? }]
const fs = require('node:fs')
const path = require('node:path')
const { spawn } = require('node:child_process')

const [repo, out, jobsFile] = process.argv.slice(2)
const { findBrowser, browserArgs } = require(path.join(repo, 'tools', 'ops', 'screenshot.cjs'))
const jobs = JSON.parse(fs.readFileSync(jobsFile, 'utf8'))
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

class Cdp {
  constructor(url) {
    this.id = 1; this.pending = new Map(); this.inflight = new Set()
    this.socket = new WebSocket(url)
    this.opened = new Promise((resolve, reject) => { this.socket.onopen = resolve; this.socket.onerror = () => reject(new Error('socket')) })
    this.socket.onmessage = (event) => {
      const m = JSON.parse(event.data)
      if (m.id && this.pending.has(m.id)) { const p = this.pending.get(m.id); this.pending.delete(m.id); m.error ? p.reject(new Error(m.error.message)) : p.resolve(m.result) }
      else if (m.method === 'Network.requestWillBeSent') this.inflight.add(m.params.requestId)
      else if (m.method === 'Network.loadingFinished' || m.method === 'Network.loadingFailed') this.inflight.delete(m.params.requestId)
    }
  }
  send(method, params = {}) { const id = this.id++; return new Promise((resolve, reject) => { this.pending.set(id, { resolve, reject }); this.socket.send(JSON.stringify({ id, method, params })) }) }
  async evaluate(expression) { const r = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + ' ' + (r.exceptionDetails.exception?.description ?? '')); return r.result.value }
}

async function ready(cdp) {
  let stable = 0
  for (let i = 0; i < 300; i++) {
    const ok = cdp.inflight.size === 0 && await cdp.evaluate("document.readyState === 'complete' && !document.querySelector('.skeleton, [aria-busy=\"true\"]')")
    stable = ok ? stable + 1 : 0
    if (stable >= 4) return true
    await sleep(250)
  }
  return false
}

// The #269 probe on the real page: fully visible candidate rows within the first screen, numeric cells whose text
// wraps inside one line box (text nodes grouped by their nearest non-inline ancestor), and horizontal overflow.
const PROBE = `(() => {
  const W = innerWidth, H = W > 640 ? 800 : 844
  const items = W > 640 ? [...document.querySelectorAll('.candidate-table > tbody > tr[data-candidate-rank]')] : [...document.querySelectorAll('.candidate-cards > .candidate-mini')]
  let rows = 0
  for (const el of items) { const r = el.getBoundingClientRect(); if (r.height > 0 && r.top >= 0 && r.bottom <= H) rows++ }
  const cells = W > 640 ? [...document.querySelectorAll('.candidate-table td.num')] : [...document.querySelectorAll('.candidate-mini-levels dd')]
  const wrapped = []
  let measured = 0
  for (const cell of cells) {
    if (cell.getBoundingClientRect().height === 0) continue
    measured++
    const groups = new Map()
    const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT)
    let node
    while ((node = walker.nextNode())) {
      if (!node.textContent.trim()) continue
      let box = node.parentElement
      while (box !== cell && getComputedStyle(box).display.startsWith('inline')) box = box.parentElement
      const range = document.createRange(); range.selectNodeContents(node)
      const tops = groups.get(box) ?? new Set()
      for (const rect of range.getClientRects()) if (rect.width > 0) tops.add(Math.round(rect.top))
      groups.set(box, tops)
    }
    if ([...groups.values()].some((tops) => tops.size > 1)) wrapped.push(cell.textContent.trim())
  }
  const de = document.documentElement
  return 'PROBE first_screen=' + W + 'x' + H + ' fully_visible_rows=' + rows + ' of ' + items.filter((el) => el.getBoundingClientRect().height > 0).length + ' shown'
    + ' wrapped_num_cells=' + wrapped.length + '/' + measured + (wrapped.length ? ' :: ' + wrapped.slice(0, 8).join(' | ') : '')
    + ' scrollWidth=' + de.scrollWidth + ' clientWidth=' + de.clientWidth + ' overflow=' + (de.scrollWidth > de.clientWidth)
})()`

async function main() {
  fs.mkdirSync(out, { recursive: true })
  const profile = fs.mkdtempSync(path.join(path.resolve(out), '.browser-'))
  const child = spawn(findBrowser(), browserArgs(profile), { stdio: ['ignore', 'ignore', 'ignore'] })
  let port
  for (let i = 0; i < 300 && !port; i++) { try { port = fs.readFileSync(path.join(profile, 'DevToolsActivePort'), 'utf8').split('\n')[0].trim() } catch { await sleep(200) } }
  const page = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === 'page')
  const cdp = new Cdp(page.webSocketDebuggerUrl)
  await cdp.opened
  await Promise.all([cdp.send('Page.enable'), cdp.send('Runtime.enable'), cdp.send('Network.enable')])
  const log = []
  try {
    for (const job of jobs) {
      const height = job.height ?? (job.width <= 640 ? 844 : 800)
      await cdp.send('Emulation.setDeviceMetricsOverride', { width: job.width, height, deviceScaleFactor: 1, mobile: job.width <= 640 })
      await cdp.send('Page.navigate', { url: job.url })
      await sleep(300)
      let ok = await ready(cdp)
      for (const selector of job.clicks ?? []) { await cdp.evaluate(`document.querySelector(${JSON.stringify(selector)})?.click()`); await sleep(300); ok = (await ready(cdp)) && ok }
      for (const selector of job.open ?? []) { await cdp.evaluate(`document.querySelectorAll(${JSON.stringify(selector)}).forEach((d) => { d.open = true })`); await sleep(300); ok = (await ready(cdp)) && ok }
      await cdp.evaluate('window.scrollTo(0, 0)')
      const line = { name: job.name, url: job.url, width: job.width, ready: ok }
      if (job.probe) line.probe = await cdp.evaluate(PROBE)
      let clip
      if (job.mode === 'first') clip = { x: 0, y: 0, width: job.width, height, scale: 1 }
      else if (job.mode === 'full') {
        const h = await cdp.evaluate('document.documentElement.scrollHeight')
        clip = { x: 0, y: 0, width: job.width, height: Math.min(h, 16000), scale: 1 }
      } else {
        const rect = await cdp.evaluate(`(() => { const el = document.querySelector(${JSON.stringify(job.selector)}); if (!el) return null; const r = el.getBoundingClientRect(); return { x: r.left + scrollX, y: r.top + scrollY, width: r.width, height: r.height } })()`)
        if (!rect) { line.error = 'no element ' + job.selector; log.push(line); console.log(JSON.stringify(line)); continue }
        clip = { x: Math.max(0, rect.x - 8), y: Math.max(0, rect.y - 8), width: rect.width + 16, height: Math.min(rect.height + 16, job.maxHeight ?? 4000), scale: 1 }
      }
      const shot = await cdp.send('Page.captureScreenshot', { format: 'png', clip, captureBeyondViewport: true })
      fs.writeFileSync(path.join(out, job.name + '.png'), Buffer.from(shot.data, 'base64'))
      line.png = job.name + '.png'
      log.push(line)
      console.log(JSON.stringify(line))
    }
  } finally {
    await cdp.send('Browser.close').catch(() => {})
    await sleep(1500)
    if (child.exitCode === null) child.kill()
    for (let i = 0; i < 20; i++) { try { fs.rmSync(profile, { recursive: true, force: true }); break } catch { await sleep(500) } }
  }
  fs.writeFileSync(path.join(out, 'shots.jsonl'), log.map((line) => JSON.stringify(line)).join('\n') + '\n', { flag: 'a' })
}

main().catch((error) => { console.error(error); process.exitCode = 1 })
