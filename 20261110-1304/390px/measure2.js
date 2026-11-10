(() => {
  const r = (n) => Math.round(n * 10) / 10
  const b = (el) => { const x = el.getBoundingClientRect(); return { left: r(x.left), top: r(x.top), right: r(x.right), bottom: r(x.bottom) } }
  return Array.from(document.querySelectorAll('.candidate-row:not([hidden])')).map((row) => {
    const nums = row.querySelector('.candidate-row-nums')
    const scoreCell = nums.lastElementChild
    const dd = scoreCell.querySelector('dd'); const dt = scoreCell.querySelector('dt')
    const btn = row.querySelector('.candidate-ai-toggle')
    const rb = b(row), sb = b(dd), tb = b(btn), lb = b(dt)
    const ox = Math.max(0, Math.min(sb.right, tb.right) - Math.max(sb.left, tb.left))
    const oy = Math.max(0, Math.min(sb.bottom, tb.bottom) - Math.max(sb.top, tb.top))
    const hit = document.elementFromPoint((sb.left + Math.min(sb.right, sb.left + 12)) / 2 + 2, (sb.top + sb.bottom) / 2)
    return { rank: row.dataset.candidateRank, rowRight: rb.right, scoreLabel: dt.innerText, labelRight: lb.right, scoreText: dd.innerText, score: sb, button: tb, overlapPx: [r(ox), r(oy)], topElementAtScore: hit ? hit.className || hit.tagName : null }
  })
})()
