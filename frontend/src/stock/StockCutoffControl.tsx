import { useEffect, useState } from 'react'

import { formatDay } from '../dates'

// 研究截止日期 in the stock page header. Above 640px the form is always shown; at 640px and below it folds behind
// a one-line toggle so the header and tabs fit the first screen, and starts open when a cutoff is applied
// (DESIGN_SYSTEM §4 手機第一屏).
export function StockCutoffControl({ asOf, onApply }: { asOf: string; onApply: (asOf: string) => void }) {
  const [draft, setDraft] = useState(asOf)
  const [open, setOpen] = useState(Boolean(asOf))
  useEffect(() => setDraft(asOf), [asOf])
  return (
    <div className={open ? 'cutoff-panel open' : 'cutoff-panel'}>
      <button type="button" className="btn btn-ghost btn-sm cutoff-toggle" aria-expanded={open} aria-controls="stock-cutoff-form" onClick={() => setOpen(!open)}>
        {`研究截止日期：${asOf ? formatDay(asOf) ?? asOf : '最新資料'} ${open ? '▾' : '▸'}`}
      </button>
      <form id="stock-cutoff-form" className="overview-cutoff-control" onSubmit={(event) => { event.preventDefault(); onApply(String(new FormData(event.currentTarget).get('as_of') ?? '')) }}>
        <label htmlFor="stock-cutoff">研究截止日期</label>
        <input id="stock-cutoff" name="as_of" type="date" className="input" value={draft} onInput={(event) => setDraft(event.currentTarget.value)} onChange={(event) => setDraft(event.target.value)} />
        <button type="submit" className="btn btn-secondary btn-sm">套用截止</button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => { onApply(''); setDraft('') }}>最新資料</button>
        <span className="small-note">空白日期會使用最新資料日期；截止日期不影響頁首收盤、K 線與新聞時間線。</span>
      </form>
    </div>
  )
}
