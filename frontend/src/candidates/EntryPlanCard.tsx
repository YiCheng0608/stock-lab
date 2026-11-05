import { Term } from '../components/Term'
import { Badge, cx } from '../components/ui'
import type { CandidateItem } from '../types'
import { ENTRY_TYPES, entryConditionsTitle, entryPlanView, type EntryPart } from './entryPlan'

type PlanItem = Pick<CandidateItem, 'levels' | 'entry_plan' | 'trading_date'>

function Parts({ parts }: { parts: readonly EntryPart[] }) {
  return <>{parts.map((part, index) => part.className ? <b key={index} className={part.className}>{part.text}</b> : part.term ? <Term key={index} id={part.term}>{part.text}</Term> : <span key={index}>{part.text}</span>)}</>
}

// The signal day's judgement of every condition, folded (#491). The today table shows it in the row's AI detail
// (#493), so the 進場方式 cell stays two lines; the phone card and the stock page keep it under the sentence.
export function EntryConditions({ item, onStockPage = false }: { item: PlanItem; onStockPage?: boolean }) {
  const { conditions } = entryPlanView(item, { onStockPage })
  if (conditions.length === 0) return null
  return (
    <details className="details entry-plan-conditions">
      <summary>{entryConditionsTitle(item.trading_date)}</summary>
      <ul className="entry-plan-condition-list">
        {conditions.map((condition) => (
          <li key={condition.code} data-condition={condition.code} data-condition-state={condition.state}>
            <Badge tone={condition.state === 'met' ? 'success' : condition.state === 'unmet' ? 'warning' : 'default'} className="badge-compact">{condition.stateText}</Badge>
            <span className="entry-plan-condition-label">{condition.label}</span>
            {condition.value && <span className="small-note">{condition.value}</span>}
          </li>
        ))}
      </ul>
    </details>
  )
}

// A candidate's entry plan (#491; UI_COPY_SPEC §10.2, DESIGN_SYSTEM §5 進場卡片): the entry type as a glossary term and
// one sentence with the signal's levels, and the signal day's judgement of every condition folded under it.
// Self-contained (only the candidate item), so the today list (the 進場方式 column and the phone card, #493), the stock
// page's candidate row and later pages all reuse it; onStockPage drops the pointer to the stock page from the
// missing-levels sentence; conditions={false} leaves the folded conditions to EntryConditions elsewhere.
export function EntryPlanCard({ item, className, onStockPage = false, conditions = true }: { item: PlanItem; className?: string; onStockPage?: boolean; conditions?: boolean }) {
  const view = entryPlanView(item, { onStockPage })
  const type = view.type ? ENTRY_TYPES[view.type] : null
  return (
    <section className={cx('entry-plan', className)} aria-label="進場方式" data-entry-plan={view.kind} data-entry-type={view.type ?? 'unknown'}>
      <p className="entry-plan-line">
        <span className="entry-plan-type">{type ? <Term id={type.term}>{type.label}</Term> : '進場方式'}</span>
        <span className={cx('entry-plan-sentence', view.kind === 'reason' && 'entry-plan-reason')}><Parts parts={view.parts} /></span>
      </p>
      {conditions && <EntryConditions item={item} onStockPage={onStockPage} />}
    </section>
  )
}
