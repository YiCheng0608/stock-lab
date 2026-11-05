import { Term } from '../components/Term'
import { cx } from '../components/ui'
import type { CandidateItem } from '../types'
import { ENTRY_PLAN_CONDITIONS_TITLE, ENTRY_TYPES, entryPlanView, type EntryPart } from './entryPlan'

function Parts({ parts }: { parts: readonly EntryPart[] }) {
  return <>{parts.map((part, index) => part.className ? <b key={index} className={part.className}>{part.text}</b> : <span key={index}>{part.text}</span>)}</>
}

// A candidate's entry plan (#491; UI_COPY_SPEC §10.2, DESIGN_SYSTEM §5 進場卡片): the entry type as a glossary term and
// the main sentence with the signal's levels, the small reminder of when the signal no longer holds, and the full
// conditions folded. Self-contained (only the candidate item), so the today list, the stock page's candidate row and
// later pages (#493) all reuse it.
export function EntryPlanCard({ item, className }: { item: Pick<CandidateItem, 'levels' | 'entry_plan' | 'trading_date'>; className?: string }) {
  const view = entryPlanView(item)
  const type = view.type ? ENTRY_TYPES[view.type] : null
  return (
    <section className={cx('entry-plan', className)} aria-label="進場方式" data-entry-plan={view.kind} data-entry-type={view.type ?? 'unknown'}>
      <p className="entry-plan-line">
        <span className="entry-plan-type">{type ? <Term id={type.term}>{type.label}</Term> : '進場方式'}</span>
        <span className={cx('entry-plan-sentence', view.kind === 'reason' && 'entry-plan-reason')}><Parts parts={view.parts} /></span>
      </p>
      {/* One small line under the sentence: the reminder, then the folded full conditions (they take the full width when open). */}
      {(view.holds || view.conditions.length > 0) && <div className="entry-plan-foot">
      {view.holds && <p className="small-note entry-plan-holds" data-entry-holds=""><Parts parts={view.holds} /></p>}
      {view.conditions.length > 0 && (
        <details className="details entry-plan-conditions">
          <summary>{ENTRY_PLAN_CONDITIONS_TITLE}</summary>
          <ul className="entry-plan-condition-list">
            {view.conditions.map((condition) => (
              <li key={condition.code} data-condition={condition.code}>
                <span className="entry-plan-condition-label">{condition.label}</span>
                <span className="small-note">{condition.next}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
      </div>}
    </section>
  )
}
