(() => {
  const r = (el) => { const b = el.getBoundingClientRect(); return { top: Math.round(b.top + scrollY), bottom: Math.round(b.bottom + scrollY), height: Math.round(b.height) } }
  const vis = (el) => el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden'
  const H = window.innerHeight
  const page = document.querySelector('.page')
  const lines = (el) => { const cs = getComputedStyle(el); const lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.5; return Math.round(el.getBoundingClientRect().height / lh) }
  const label = (c) => c.tagName.toLowerCase() + (typeof c.className === 'string' && c.className.trim() ? '.' + c.className.trim().split(/\s+/).join('.') : '')
  const blocks = []
  const walk = (el, depth) => { for (const c of el.children) { if (!vis(c)) continue; blocks.push({ depth, label: label(c), ...r(c), text: (c.innerText || '').split('\n')[0].slice(0, 50) }); if (depth < 2 && /page-title|theme-header|board-controls|board-toolbar|panel-head|section-head|filter-row|market-panel/.test(String(c.className))) walk(c, depth + 1) } }
  if (page) walk(page, 0)
  // Explanatory text outside a closed <details>: paragraphs and notes with their length and line count.
  const notes = [...document.querySelectorAll('.page p, .page .small-note, .page .table-note, .page .eyebrow, .page summary')]
    .filter(vis).filter((el) => !el.closest('details:not([open]) > :not(summary)'))
    .map((el) => ({ label: label(el), ...r(el), chars: (el.innerText || '').replace(/\s/g, '').length, lines: lines(el), text: (el.innerText || '').replace(/\n/g, ' / ').slice(0, 160) }))
  const sel = '.board-row, .data-table-wrap tbody tr, table tbody tr, .stock-card, .member-card, .card-list > *'
  const items = [...new Set([...document.querySelectorAll(sel)])].filter(vis).filter((el) => !el.closest('details:not([open])'))
  const groups = {}
  for (const el of items) {
    const key = el.closest('.member-table-wrap,.stock-table-wrap,.market-index-table,.board-list,.member-cards,.stock-cards,.card-list')?.className.split(/\s+/)[0] || label(el)
    const g = groups[key] = groups[key] || { total: 0, fullyVisible: 0, first: null, firstLines: null }
    g.total += 1
    const b = el.getBoundingClientRect()
    if (b.bottom + scrollY <= H) g.fullyVisible += 1
    if (!g.first) { g.first = r(el); g.firstLines = (el.innerText || '').split('\n').filter(Boolean) }
  }
  const clipped = [...document.querySelectorAll('.page td, .page th, .page .stock-card *, .page .member-card *, .page .board-row *')].filter(vis).filter((el) => el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflow !== 'visible').slice(0, 20).map((el) => ({ label: label(el), text: (el.innerText || '').slice(0, 40), sw: el.scrollWidth, cw: el.clientWidth }))
  const right = Math.max(...[...document.querySelectorAll('.page *')].filter(vis).map((el) => el.getBoundingClientRect().right))
  return { openDetails: document.querySelectorAll('details[open]').length, innerHeight: H, clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth, maxRight: Math.round(right), scrollHeight: document.documentElement.scrollHeight, blocks, notes, groups, clipped }
})()
