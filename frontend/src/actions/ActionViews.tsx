import { Link } from 'react-router-dom'

import { formatCandidateScore } from '../candidates/candidates'
import { Term } from '../components/Term'
import { Badge, CardList, DataTable, Skeleton, cx, type Column } from '../components/ui'
import type { ActionSummary, ActionTierSummary, ActionView } from '../types'
import {
  ACTION_VIEWS,
  CONDITIONS_PENDING_TEXT,
  EMPTY_TEXT,
  LEVELS_NOTE,
  NEAR_RESEARCH_LINK,
  RESEARCH_LINK,
  SEARCH_NOTE,
  actionClose,
  actionDataDay,
  actionKey,
  actionLevels,
  actionNote,
  actionStateLabel,
  conditionalNote,
  conditionsPending,
  etfLabel,
  hiddenSentence,
  moreText,
  nearCopy,
  shownText,
  stockResearchPath,
  viewChipLabel,
  type TierSection,
} from './actionTiers'

// Action centre (#278): filter chips, the hidden-rows line and one section per tier (UI_COPY_SPEC §5);
// desktop tables and phone cards follow DESIGN_SYSTEM §5 行動列表, level colours §7.

function marketLabel(exchange: string): string {
  return exchange === 'TWSE' ? '上市' : exchange === 'TPEx' ? '上櫃' : '市場待核實'
}

function typeLabel(type: string): string {
  return ({ stock: '股票', equity: '股票', etf: 'ETF', ipo: '新上市', index: '指數' } as Record<string, string>)[type.toLowerCase()] ?? '其他標的'
}

const researchPath = (action: ActionSummary) => stockResearchPath(action.instrument.exchange, action.instrument.symbol)

export function ActionFilters({ summary, view, includeEtf, searching, onViewChange, onIncludeEtfChange }: {
  summary: ActionTierSummary
  view: ActionView
  includeEtf: boolean
  searching: boolean
  onViewChange: (view: ActionView) => void
  onIncludeEtfChange: (value: boolean) => void
}) {
  const hidden = searching ? SEARCH_NOTE : hiddenSentence(summary)
  return (
    <div className="action-filters">
      <div className="filter-row">
        <div className="filter-chips" role="group" aria-label="篩選">
          {ACTION_VIEWS.map((item) => (
            <button key={item.id} type="button" className={cx('badge filter-chip', item.id === view && 'filter-chip-selected')} aria-pressed={item.id === view} onClick={() => onViewChange(item.id)}>
              {viewChipLabel(item.id, summary)}
            </button>
          ))}
        </div>
        <label className="check-label"><input type="checkbox" checked={includeEtf} onChange={(event) => onIncludeEtfChange(event.target.checked)} /> {etfLabel(summary)}</label>
      </div>
      {hidden && <p className="small-note action-hidden-note">{hidden}</p>}
    </div>
  )
}

function StockCell({ action }: { action: ActionSummary }) {
  const { instrument } = action
  return <>
    <Link className="symbol-link" to={researchPath(action)}><strong>{instrument.symbol}</strong> {instrument.name}</Link>
    <div className="small-note">{marketLabel(instrument.exchange)} · {typeLabel(instrument.instrument_type)}</div>
  </>
}

// The row's tier context: tier 3 words its nearest strategy, tier 2 says why it is not a candidate (UI_COPY_SPEC §6).
type RowContext = { tier: number; candidateListSize: number | null }

// The phone card puts tier 2's line with the other text (DESIGN_SYSTEM §5.1 ④), not under the badge.
function StatusCell({ action, context, withNote = true }: { action: ActionSummary; context: RowContext; withNote?: boolean }) {
  const near = context.tier === 3 ? nearCopy(action.nearness) : null
  if (near) return <Badge tone="primary" className="badge-compact">{near.title}</Badge>
  return <>
    <Badge tone={action.action_state === 'conditional_entry' ? 'primary' : action.action_state === 'reduce_exit' ? 'warning' : 'default'} className="badge-compact">{actionStateLabel(action)}</Badge>
    {action.position_quantity_status === 'unknown' && <div><span className="pill ambiguous badge-compact">庫存數量待核實</span></div>}
    {withNote && context.tier === 2 && <div className="small-note action-tier-note">{conditionalNote(action, context.candidateListSize)}</div>}
  </>
}

// Tier 3's 差哪個條件: one 「差：」 line per unmet condition, then the met short names; never a level.
function NearLines({ action }: { action: ActionSummary }) {
  const near = nearCopy(action.nearness)
  if (!near) return null
  return <div className="action-near" data-near-lines="">
    {near.lines.map((line) => <div key={line} className="action-near-line">{line}</div>)}
    {near.met && <div className="small-note">{near.met}</div>}
  </div>
}

function NoteLines({ action, tier }: { action: ActionSummary; tier: number }) {
  const note = actionNote(action)
  return <>
    {note && <div>{note}</div>}
    {conditionsPending(action, tier) && <div className="small-note">{CONDITIONS_PENDING_TEXT}</div>}
  </>
}

function CloseCell({ action }: { action: ActionSummary }) {
  const close = actionClose(action)
  if (close.close === null) return <div className="small-note action-no-close">價格資料尚未完整，暫不顯示最近收盤</div>
  return <><div>{close.close}</div><div className={cx('action-change', close.tone)}>{close.change}</div></>
}

const rankLabel = (action: ActionSummary) => action.candidate ? `#${action.candidate.rank}` : ''

function tierColumns(context: RowContext): ReadonlyArray<Column<ActionSummary>> {
  const { tier } = context
  const stock: Column<ActionSummary> = { key: 'stock', header: '股票', cell: (action) => <StockCell action={action} /> }
  const status: Column<ActionSummary> = { key: 'status', header: '狀態', cell: (action) => <StatusCell action={action} context={context} /> }
  const close: Column<ActionSummary> = { key: 'close', header: '最近收盤', num: true, cell: (action) => <CloseCell action={action} /> }
  const levels: Array<Column<ActionSummary>> = [
    { key: 'entry', header: <Term id="entry_zone">進場區</Term>, num: true, cellClassName: 'level-entry', cell: (action) => actionLevels(action)?.entry ?? '' },
    { key: 'stop', header: <Term id="support">停損</Term>, num: true, cellClassName: 'level-stop', cell: (action) => actionLevels(action)?.stop ?? '' },
    { key: 'target', header: <Term id="target">目標</Term>, num: true, cellClassName: 'level-target', cell: (action) => actionLevels(action)?.target ?? '' },
  ]
  const day: Column<ActionSummary> = { key: 'day', header: '資料日', num: true, cell: actionDataDay }
  const link: Column<ActionSummary> = { key: 'link', header: <span className="sr-only">策略總表</span>, cell: (action) => <Link className="text-link" to={researchPath(action)}>{tier === 3 ? NEAR_RESEARCH_LINK : RESEARCH_LINK}</Link> }
  if (tier === 1) {
    return [
      { key: 'rank', header: '名次', cell: (action) => <span className="candidate-rank" aria-label={`第 ${action.candidate?.rank ?? ''} 名`}>{rankLabel(action)}</span> },
      stock, status, close, ...levels,
      { key: 'total', header: <Term id="candidate_score">總分</Term>, num: true, cell: (action) => action.candidate ? formatCandidateScore(action.candidate.total_score) : '' },
      day, link,
    ]
  }
  if (tier === 3) return [stock, status, close, { key: 'near', header: '差哪個條件', wrap: true, cellClassName: 'action-note-cell', cell: (action) => <NearLines action={action} /> }, day, link]
  if (tier >= 4) return [stock, status, close, { key: 'note', header: '說明', wrap: true, cellClassName: 'action-note-cell', cell: (action) => <NoteLines action={action} tier={tier} /> }, day, link]
  return [stock, status, close, ...levels, day, link]
}

function ActionCard({ action, context }: { action: ActionSummary; context: RowContext }) {
  const { tier } = context
  const close = actionClose(action)
  // Tier 3 never shows a level (DESIGN_SYSTEM §7 接近成立).
  const levels = tier <= 2 ? actionLevels(action) : null
  return (
    // DESIGN_SYSTEM §5.1: ① name and badge, the close on the right → ② market · type → ③ levels → ④ text → ⑤ day and link.
    <article className="card action-card-mini" data-action-card={actionKey(action)}>
      <div className="action-card-head">
        <div className="action-card-title">
          <Link className="symbol-link" to={researchPath(action)}><strong>{action.instrument.symbol}</strong> {action.instrument.name}</Link>
          <StatusCell action={action} context={context} withNote={false} />
        </div>
        {close.close !== null && <div className="action-card-price">{close.close}<span className={cx('action-change', close.tone)}>{close.change}</span></div>}
      </div>
      <div className="small-note">{action.candidate ? `#${action.candidate.rank} · ` : ''}{marketLabel(action.instrument.exchange)} · {typeLabel(action.instrument.instrument_type)}</div>
      {close.close === null && <div className="small-note">價格資料尚未完整，暫不顯示最近收盤</div>}
      {levels && (
        // Only the levels the row has; a blank level is left out, not shown as 0 or a dash (UI_COPY_SPEC §5).
        <dl className="candidate-mini-levels">
          {levels.entry && <div><dt>進場區</dt><dd className="level-entry">{levels.entry}</dd></div>}
          {levels.stop && <div><dt>停損</dt><dd className="level-stop">{levels.stop}</dd></div>}
          {levels.target && <div><dt>目標</dt><dd className="level-target">{levels.target}</dd></div>}
        </dl>
      )}
      {tier === 2 && <div className="small-note">{conditionalNote(action, context.candidateListSize)}</div>}
      {tier === 3 && <NearLines action={action} />}
      {tier >= 4 && <div className="small-note action-card-note"><NoteLines action={action} tier={tier} /></div>}
      <div className="action-card-foot"><span className="small-note">資料日 {actionDataDay(action)}</span><Link className="text-link" to={researchPath(action)}>{tier === 3 ? NEAR_RESEARCH_LINK : RESEARCH_LINK}</Link></div>
    </article>
  )
}

export function ActionTierSectionView({ section, loading, canLoadMore, onMore }: {
  section: TierSection
  loading?: boolean
  canLoadMore: boolean
  onMore: () => void
}) {
  const remaining = Math.max(0, section.shown - section.items.length)
  const titleId = `action-tier-${section.tier}`
  const context: RowContext = { tier: section.tier, candidateListSize: section.candidateListSize }
  return (
    <section className="action-tier" data-tier={section.tier} aria-labelledby={titleId}>
      <div className="section-head">
        <div><div className="eyebrow">第 {section.tier} 級</div><h2 id={titleId}>{section.label}</h2></div>
        <span className="small-note">{shownText(section.items.length, section.shown)}</span>
      </div>
      {/* A tier's first rows still loading: a skeleton, not an empty section (the screenshot tools wait for it). */}
      {loading && section.items.length === 0 && <Skeleton lines={2} label={`${section.label}載入中…`} />}
      {section.items.length > 0 && <>
        <DataTable
          wrapClassName="action-table-wrap"
          className="action-table"
          note={section.tier <= 2 ? LEVELS_NOTE : undefined}
          columns={tierColumns(context)}
          rows={section.items}
          rowKey={actionKey}
          rowProps={(action) => ({ 'data-action-row': actionKey(action) })}
        />
        {/* The tier pages with 顯示更多 (UI_COPY_SPEC §5), not the ten-card fold (DESIGN_SYSTEM §5.1). */}
        <CardList className="action-cards" items={section.items} itemKey={actionKey} preview={null} renderCard={(action) => <ActionCard action={action} context={context} />} />
      </>}
      {remaining > 0 && canLoadMore && (
        <button type="button" className="btn btn-secondary btn-sm action-more" disabled={loading} onClick={onMore}>{loading ? '載入中…' : moreText(remaining)}</button>
      )}
    </section>
  )
}

export function ActionTierList({ sections, loadingTiers, canLoadMore, onMore }: {
  sections: TierSection[]
  loadingTiers: ReadonlySet<number>
  canLoadMore: (tier: number) => boolean
  onMore: (tier: number) => void
}) {
  if (!sections.length) return <div className="empty panel">{EMPTY_TEXT}</div>
  return <>{sections.map((section) => <ActionTierSectionView key={section.tier} section={section} loading={loadingTiers.has(section.tier)} canLoadMore={canLoadMore(section.tier)} onMore={() => onMore(section.tier)} />)}</>
}
