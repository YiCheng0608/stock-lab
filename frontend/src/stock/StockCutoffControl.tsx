import { useEffect, useState } from 'react'

import { formatDay } from '../dates'

/** The YYYY-MM-DD calendar day a date input can hold, from an ISO date or the date part of a timestamp. */
function inputDay(value: string | null | undefined): string | null {
  return value ? /^\d{4}-\d{2}-\d{2}/.exec(value)?.[0] ?? null : null
}

/** What 「套用截止」 applies: the unchanged latest data day (or a cleared field) stays 「最新資料」, so the URL gets no
 *  as_of; any other day is the cutoff (#492). */
export function cutoffSubmission(value: string, latestDay: string | null): string {
  return value && value !== latestDay ? value : ''
}

// 研究截止日期 in the stock page header. Above 640px the form is always shown; at 640px and below it folds behind
// a one-line toggle so the header and tabs fit the first screen, and starts open when a cutoff is applied
// (DESIGN_SYSTEM §4 手機第一屏). `effectiveDate` is the cutoff the API actually used, so 「最新資料」 names its day,
// the date field starts on it and cannot go past it, and the form says what a cutoff does (UI_COPY_SPEC §8.2
// 研究截止日期, #463, #492).
export function StockCutoffControl({ asOf, effectiveDate = null, onApply }: { asOf: string; effectiveDate?: string | null; onApply: (asOf: string) => void }) {
  const latestInput = inputDay(effectiveDate)
  const [draft, setDraft] = useState(asOf || latestInput || '')
  const latestDay = effectiveDate ? formatDay(effectiveDate) ?? null : null
  const current = asOf ? formatDay(asOf) ?? asOf : latestDay ? `最新資料（${latestDay}）` : '最新資料'
  const [open, setOpen] = useState(Boolean(asOf))
  useEffect(() => setDraft(asOf || latestInput || ''), [asOf, latestInput])
  return (
    <div className={open ? 'cutoff-panel open' : 'cutoff-panel'}>
      <button type="button" className="btn btn-ghost btn-sm cutoff-toggle" aria-expanded={open} aria-controls="stock-cutoff-form" onClick={() => setOpen(!open)}>
        {`研究截止日期：${current} ${open ? '▾' : '▸'}`}
      </button>
      <form id="stock-cutoff-form" className="overview-cutoff-control" onSubmit={(event) => { event.preventDefault(); onApply(cutoffSubmission(String(new FormData(event.currentTarget).get('as_of') ?? ''), latestInput)) }}>
        <label htmlFor="stock-cutoff">研究截止日期</label>
        <input id="stock-cutoff" name="as_of" type="date" className="input" value={draft} max={latestInput ?? undefined} onInput={(event) => setDraft(event.currentTarget.value)} onChange={(event) => setDraft(event.target.value)} />
        <button type="submit" className="btn btn-secondary btn-sm">套用截止</button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => { onApply(''); setDraft(latestInput ?? '') }}>最新資料</button>
        {/* #519: the sentence folds behind 說明 so the form is one row (UI_COPY_SPEC §8.2 研究截止日期). */}
        <details className="cutoff-help"><summary>說明</summary><p className="small-note">只用這一天收盤（含）以前的資料判斷研究條件、研究動作與候選，用來回看當時會怎麼判斷；空白或按「最新資料」時用{asOf ? '最新資料日' : latestDay ? ` ${latestDay}（該股最近一個有資料的交易日）` : '最新資料日'}。頁首收盤、K 線與新聞時間線不受影響。</p></details>
      </form>
    </div>
  )
}
