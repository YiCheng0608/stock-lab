import { Link } from 'react-router-dom'

import { formatCandidateScore } from '../candidates/candidates'
import { Term } from '../components/Term'
import { Badge, DataTable, cx, type Column } from '../components/ui'
import type { ActionSummary, ActionTierSummary, ActionView } from '../types'
import {
  ACTION_VIEWS,
  EMPTY_TEXT,
  LEVELS_NOTE,
  RESEARCH_LINK,
  SEARCH_NOTE,
  actionClose,
  actionDataDay,
  actionKey,
  actionLevels,
  actionNote,
  actionStateLabel,
  etfLabel,
  hiddenSentence,
  moreText,
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

function StatusCell({ action }: { action: ActionSummary }) {
  return <>
    <Badge tone={action.action_state === 'conditional_entry' ? 'primary' : action.action_state === 'reduce_exit' ? 'warning' : 'default'} className="badge-compact">{actionStateLabel(action)}</Badge>
    {action.position_quantity_status === 'unknown' && <div><span className="pill ambiguous badge-compact">庫存數量待核實</span></div>}
  </>
}

function CloseCell({ action }: { action: ActionSummary }) {
  const close = actionClose(action)
  if (close.close === null) return <div className="small-note action-no-close">價格資料尚未完整，暫不顯示最近收盤</div>
  return <><div>{close.close}</div><div className={cx('action-change', close.tone)}>{close.change}</div></>
}

const rankLabel = (action: ActionSummary) => action.candidate ? `#${action.candidate.rank}` : ''

function tierColumns(tier: number): ReadonlyArray<Column<ActionSummary>> {
  const stock: Column<ActionSummary> = { key: 'stock', header: '股票', cell: (action) => <StockCell action={action} /> }
  const status: Column<ActionSummary> = { key: 'status', header: '狀態', cell: (action) => <StatusCell action={action} /> }
  const close: Column<ActionSummary> = { key: 'close', header: '最近收盤', num: true, cell: (action) => <CloseCell action={action} /> }
  const levels: Array<Column<ActionSummary>> = [
    { key: 'entry', header: <Term id="entry_zone">進場區</Term>, num: true, cellClassName: 'level-entry', cell: (action) => actionLevels(action)?.entry ?? '' },
    { key: 'stop', header: <Term id="support">停損</Term>, num: true, cellClassName: 'level-stop', cell: (action) => actionLevels(action)?.stop ?? '' },
    { key: 'target', header: <Term id="target">目標</Term>, num: true, cellClassName: 'level-target', cell: (action) => actionLevels(action)?.target ?? '' },
  ]
  const day: Column<ActionSummary> = { key: 'day', header: '資料日', num: true, cell: actionDataDay }
  const link: Column<ActionSummary> = { key: 'link', header: <span className="sr-only">策略總表</span>, cell: (action) => <Link className="text-link" to={researchPath(action)}>{RESEARCH_LINK}</Link> }
  if (tier === 1) {
    return [
      { key: 'rank', header: '名次', cell: (action) => <span className="candidate-rank" aria-label={`第 ${action.candidate?.rank ?? ''} 名`}>{rankLabel(action)}</span> },
      stock, status, close, ...levels,
      { key: 'total', header: <Term id="candidate_score">總分</Term>, num: true, cell: (action) => action.candidate ? formatCandidateScore(action.candidate.total_score) : '' },
      day, link,
    ]
  }
  if (tier >= 4) return [stock, status, close, { key: 'note', header: '說明', wrap: true, cellClassName: 'action-note-cell', cell: (action) => actionNote(action) ?? '' }, day, link]
  return [stock, status, close, ...levels, day, link]
}

function ActionCard({ action, tier }: { action: ActionSummary; tier: number }) {
  const close = actionClose(action)
  const levels = tier <= 3 ? actionLevels(action) : null
  const note = tier >= 4 ? actionNote(action) : null
  return (
    <article className="card action-card-mini" data-action-card={actionKey(action)}>
      <div className="action-card-head">
        <Link className="symbol-link" to={researchPath(action)}><strong>{action.instrument.symbol}</strong> {action.instrument.name}</Link>
        <StatusCell action={action} />
      </div>
      <div className="small-note">{action.candidate ? `#${action.candidate.rank} · ` : ''}{marketLabel(action.instrument.exchange)} · {typeLabel(action.instrument.instrument_type)}</div>
      {close.close === null
        ? <div className="small-note">價格資料尚未完整，暫不顯示最近收盤</div>
        : <div className="action-card-close"><span className="small-note">最近收盤</span> <b>{close.close}</b> <span className={cx('action-change', close.tone)}>{close.change}</span></div>}
      {levels && (
        // Only the levels the row has; a blank level is left out, not shown as 0 or a dash (UI_COPY_SPEC §5).
        <dl className="candidate-mini-levels">
          {levels.entry && <div><dt>進場區</dt><dd className="level-entry">{levels.entry}</dd></div>}
          {levels.stop && <div><dt>停損</dt><dd className="level-stop">{levels.stop}</dd></div>}
          {levels.target && <div><dt>目標</dt><dd className="level-target">{levels.target}</dd></div>}
        </dl>
      )}
      {note && <p className="small-note">{note}</p>}
      <div className="action-card-foot"><span className="small-note">資料日 {actionDataDay(action)}</span><Link className="text-link" to={researchPath(action)}>{RESEARCH_LINK}</Link></div>
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
  return (
    <section className="action-tier" data-tier={section.tier} aria-labelledby={titleId}>
      <div className="section-head">
        <div><div className="eyebrow">第 {section.tier} 級</div><h2 id={titleId}>{section.label}</h2></div>
        <span className="small-note">{shownText(section.items.length, section.shown)}</span>
      </div>
      {section.items.length > 0 && <>
        <DataTable
          wrapClassName="action-table-wrap"
          className="action-table"
          note={section.tier <= 3 ? LEVELS_NOTE : undefined}
          columns={tierColumns(section.tier)}
          rows={section.items}
          rowKey={actionKey}
          rowProps={(action) => ({ 'data-action-row': actionKey(action) })}
        />
        <div className="action-cards">{section.items.map((action) => <ActionCard key={actionKey(action)} action={action} tier={section.tier} />)}</div>
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
