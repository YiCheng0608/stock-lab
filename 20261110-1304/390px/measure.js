(() => {
  const r = (n) => Math.round(n * 10) / 10
  const box = (el) => { const b = el.getBoundingClientRect(); return { left: r(b.left), right: r(b.right), width: r(b.width), height: r(b.height) } }
  const clipAncestor = (el) => {
    for (let p = el.parentElement; p; p = p.parentElement) {
      const s = getComputedStyle(p)
      if (s.overflowX !== 'visible' || s.overflow !== 'visible') return p
    }
    return null
  }
  const desc = (el) => el ? `${el.tagName.toLowerCase()}${el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : ''}` : null
  const one = (el, containerSel) => {
    const container = el.closest(containerSel)
    const clip = clipAncestor(el)
    const cb = container ? box(container) : null
    const eb = box(el)
    const clipBox = clip ? box(clip) : null
    return {
      el: desc(el),
      text: (el.innerText || '').replace(/\s+/g, ' ').slice(0, 80),
      rect: eb,
      container: desc(container),
      containerRect: cb,
      rightOverContainer: cb ? r(eb.right - cb.right) : null,
      scrollWidth: el.scrollWidth,
      clientWidth: el.clientWidth,
      clipAncestor: desc(clip),
      clipRect: clipBox,
      rightOverClip: clipBox ? r(eb.right - clipBox.right) : null,
      whiteSpace: getComputedStyle(el).whiteSpace,
    }
  }
  const pick = (sel, containerSel, limit = 20) => Array.from(document.querySelectorAll(sel)).filter((el) => el.offsetParent !== null || el.getClientRects().length).slice(0, limit).map((el) => one(el, containerSel))
  return {
    viewport: { innerWidth, docScrollWidth: document.documentElement.scrollWidth, docClientWidth: document.documentElement.clientWidth, bodyScrollWidth: document.body.scrollWidth, horizontalScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth },
    candidateNums: pick('.candidate-row-nums', '.candidate-row'),
    candidateNumCells: pick('.candidate-row-nums > div', '.candidate-row'),
    candidateRrBasis: pick('.candidate-rr-basis', '.candidate-row'),
    summaryLevels: pick('.stock-summary [data-summary-part="levels"] .strategy-levels', '.stock-summary'),
    summaryRrBasis: pick('.stock-summary .strategy-rr-basis', '.stock-summary'),
    summaryRrDd: Array.from(document.querySelectorAll('.stock-summary .strategy-rr-basis')).map((el) => one(el.parentElement, '.stock-summary')),
  }
})()
