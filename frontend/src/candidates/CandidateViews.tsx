import { useState } from 'react'
import { Link } from 'react-router-dom'

import { Term } from '../components/Term'
import { Badge, Card, DataTable, DateBadge, EmptyState, Skeleton, cx, type Column } from '../components/ui'
import { AiBadge } from '../news/NewsViews'
import type { CandidateComponent, CandidateComponentKey, CandidateItem, CandidateSubItem, CandidatesResponse } from '../types'
import {
  CANDIDATE_COMPONENTS,
  CANDIDATE_DISCLAIMER,
  NOTE_DISCLAIMER,
  NOTE_TITLE,
  PARTIAL_NOTE,
  TODAY_VISIBLE,
  candidateAiEntry,
  candidateChange,
  candidateGroupText,
  candidateNoteView,
  candidateSourceText,
  candidateStrategyLabel,
  candidateT1Text,
  candidatesState,
  exchangeLabel,
  formatCandidateClose,
  formatCandidateScore,
  formatDate,
  formatEntryZone,
  formatPrice,
  formatRiskReward,
  formatSubItemValue,
  stockPath,
  subItemLabel,
} from './candidates'

// Daily candidate list (candidate_score_v1, #215): the today list (#276); the stock strategy board (#274) reuses the
// note, reasons and score details.
// Copy follows UI_COPY_SPEC §10; reason dots and level colours follow DESIGN_SYSTEM §7; in-place terms follow §7;
// the today table and phone cards follow DESIGN_SYSTEM §5 候選列表.

function errorReason(error: unknown): string {
  return error instanceof Error ? error.message : '請稍後重新整理'
}

function InferenceBadge() {
  return <Badge tone="accent" dot className="badge-compact">推論</Badge>
}

function ComponentScores({ item }: { item: CandidateItem }) {
  const missing = CANDIDATE_COMPONENTS.filter(({ key }) => item.components[key]?.score == null)
  return (
    <>
      <dl className="candidate-components">
        {CANDIDATE_COMPONENTS.map(({ key, label }) => {
          const component = item.components[key]
          return (
            <div key={key} data-component={key}>
              <dt>{label}{component?.inference && <> <InferenceBadge /></>}</dt>
              <dd title={component?.score == null ? component?.null_explanation ?? undefined : undefined}>{formatCandidateScore(component?.score)}</dd>
            </div>
          )
        })}
      </dl>
      {missing.length > 0 && (
        <ul className="candidate-null-notes small-note">
          {missing.map(({ key, label }) => <li key={key}>{label}：{item.components[key]?.null_explanation ?? '無資料'}</li>)}
        </ul>
      )}
    </>
  )
}

type SubItemRow = { key: CandidateComponentKey; label: string; component: CandidateComponent | undefined; name: string; sub: CandidateSubItem; first: boolean }

// Four columns at most inside a card; the component title is its own row (DESIGN_SYSTEM §5.1).
const SUB_ITEM_COLUMNS: ReadonlyArray<Column<SubItemRow>> = [
  { key: 'sub', header: '子項', wrap: true, cell: ({ name, sub }) => <>{subItemLabel(name)}{sub.null_explanation && <div className="small-note">{sub.null_explanation}</div>}</> },
  { key: 'value', header: '原值', num: true, cell: ({ name, sub }) => formatSubItemValue(name, sub.value) },
  { key: 'percentile', header: <Term id="percentile">百分位</Term>, num: true, cell: ({ sub }) => formatCandidateScore(sub.percentile) },
  { key: 'weight', header: '子項權重', num: true, cell: ({ sub }) => `${Math.round(sub.weight * 100)}%` },
]

export function ScoreDetails({ item, open }: { item: CandidateItem; open: boolean }) {
  const rows = CANDIDATE_COMPONENTS.flatMap(({ key, label }) => {
    const component = item.components[key]
    return Object.entries(component?.items ?? {}).map(([name, sub], index): SubItemRow => ({ key, label, component, name, sub, first: index === 0 }))
  })
  return (
    <details className="details candidate-details" open={open}>
      <summary>評分細節、資料日期與來源</summary>
      <DataTable
        note="分數與百分位為 0–100，越高越好（「較低為佳」的子項已反向）；「—」表示無資料，不以 0 計。"
        columns={SUB_ITEM_COLUMNS}
        rows={rows}
        rowKey={(row) => row.key + row.name}
        rowProps={(row) => ({ 'data-sub-item': row.name })}
        groupTitle={({ first, label, component }) => first
          ? <>{label}（{formatCandidateScore(component?.score)}，權重 {Math.round((component?.weight ?? 0) * 100)}%）{component?.inference && <> <InferenceBadge /></>}</>
          : null}
      />
      {item.alternatives.length > 0 && (
        <div className="small-note">同檔另一策略：{item.alternatives.map((alt) => `${candidateStrategyLabel(alt.strategy)} 總分 ${formatCandidateScore(alt.total_score)}`).join('、')}（只留總分高者）</div>
      )}
      <div className="small-note"><Term id="candidate_score">權重涵蓋</Term> {Math.round(item.weight_coverage * 100)}% · 資料日期 {formatDate(item.data_as_of) ?? '待核實'}{item.levels.earliest_execution_date ? ` · 規則最早執行日 ${formatDate(item.levels.earliest_execution_date)}` : ''}</div>
      <div className="small-note">來源：{candidateSourceText(item)}</div>
    </details>
  )
}

// LLM note (#220): DESIGN_SYSTEM §7 inference block, apart from the rule values; never part of the score.
export function CandidateNote({ item }: { item: CandidateItem }) {
  const view = candidateNoteView(item.llm_note)
  return (
    <section className="ai-inference candidate-note" aria-label={NOTE_TITLE} data-note-state={view.kind}>
      <div className="ai-inference-head"><h3>{NOTE_TITLE}</h3><AiBadge /></div>
      {view.kind === 'done'
        ? (
          <dl className="candidate-note-parts">
            {view.parts.map((part) => <div key={part.key} data-note-part={part.key}><dt>{part.label}</dt><dd>{part.text}</dd></div>)}
          </dl>
        )
        : <p className="candidate-note-empty">{view.text}</p>}
      <p className="small-note">{NOTE_DISCLAIMER}</p>
      {view.meta && <p className="small-note ai-meta">{view.meta}</p>}
    </section>
  )
}

const REASON_COMPONENTS: ReadonlySet<string> = new Set<CandidateComponentKey>(['technical', 'chips', 'news_sentiment', 'group'])

export function ReasonList({ reasons }: { reasons: CandidateItem['reasons'] }) {
  if (reasons.length === 0) return null
  return (
    <ul className="candidate-reasons">
      {reasons.map((reason) => (
        <li key={reason.code} data-reason={reason.code}>
          <i className={'reason-dot reason-dot-' + (REASON_COMPONENTS.has(reason.component) ? reason.component : 'other')} aria-hidden="true" />
          <span>{reason.text}</span>
          {reason.inference && <InferenceBadge />}
        </li>
      ))}
    </ul>
  )
}

// The stock-page card may break before 「／」; the today table and phone card keep a target on one line (DESIGN_SYSTEM §5).
function Targets({ levels, breakable = true }: { levels: CandidateItem['levels']; breakable?: boolean }) {
  return <>{formatPrice(levels.target_1)}{levels.target_2 != null && <span className="level-target-2">{breakable && <wbr />}／{formatPrice(levels.target_2)}</span>}</>
}

export function CandidateCard({ item, linkToStock = true, detailsOpen = false }: { item: CandidateItem; linkToStock?: boolean; detailsOpen?: boolean }) {
  const { instrument, levels } = item
  const name = <><strong>{instrument.symbol}</strong> {instrument.name}</>
  return (
    <article className="card candidate-card" data-candidate-rank={item.rank}>
      <div className="candidate-head">
        <span className="candidate-rank" aria-label={`第 ${item.rank} 名`}>#{item.rank}</span>
        <div className="candidate-name">
          {linkToStock ? <Link className="symbol-link" to={stockPath(item)}>{name}</Link> : <span>{name}</span>}
          <div className="small-note">{exchangeLabel(instrument.exchange)} · {candidateStrategyLabel(item.strategy)}</div>
        </div>
        <div className="candidate-total"><span><Term id="candidate_score">總分</Term></span><b>{formatCandidateScore(item.total_score)}</b></div>
      </div>
      {item.partial_components && <div className="candidate-partial small-note">{PARTIAL_NOTE}</div>}
      <dl className="candidate-levels">
        <div><dt><Term id="entry_zone">進場區</Term></dt><dd className="level-entry">{formatEntryZone(levels)}</dd></div>
        <div><dt><Term id="support">停損</Term></dt><dd className="level-stop">{formatPrice(levels.invalid_price)}</dd></div>
        <div><dt><Term id="target">目標</Term></dt><dd className="level-target"><Targets levels={levels} /></dd></div>
        <div><dt><Term id="rr">RR</Term></dt><dd><Badge tone="primary" className="badge-compact">{formatRiskReward(levels.risk_reward)}</Badge></dd></div>
      </dl>
      <ComponentScores item={item} />
      <ReasonList reasons={item.reasons} />
      <div className="small-note candidate-groups">族群：{item.groups.length ? item.groups.map(candidateGroupText).join('、') : '無所屬產業或題材'}</div>
      <CandidateNote item={item} />
      <ScoreDetails item={item} open={detailsOpen} />
    </article>
  )
}

// ---- today list (#276): desktop table with a detail row per candidate, phone cards ----

const groupText = (item: CandidateItem) => item.groups.length ? candidateGroupText(item.groups[0]) : '無所屬產業或題材'

function FirstReason({ item }: { item: CandidateItem }) {
  const reason = item.reasons[0]
  return reason ? <>{reason.text}{reason.inference && <> <InferenceBadge /></>}</> : <>—</>
}

function CloseValue({ item }: { item: CandidateItem }) {
  const change = candidateChange(item.market)
  return <><div>{formatCandidateClose(item.market)}</div><div className={cx('candidate-change', change.tone && `tone-${change.tone}`)}>{change.text}</div></>
}

// The expanded content, the same on the desktop detail row and the phone card: every reason and component, the AI
// note, data date and sources; the score-detail table stays on the stock page.
function CandidateDetail({ item }: { item: CandidateItem }) {
  return (
    <div className="candidate-detail-grid">
      <div className="candidate-detail-facts">
        {item.partial_components && <div className="candidate-partial small-note">{PARTIAL_NOTE}</div>}
        <ComponentScores item={item} />
        <ReasonList reasons={item.reasons} />
      </div>
      <CandidateNote item={item} />
      <div className="candidate-detail-source">
        <div className="small-note">資料日期 {formatDate(item.data_as_of) ?? '待核實'}</div>
        <div className="small-note">來源：{candidateSourceText(item)}</div>
        <Link className="text-link" to={stockPath(item)}>評分細節 → 個股頁</Link>
      </div>
    </div>
  )
}

function candidateColumns(open: ReadonlySet<number>, toggle: (rank: number) => void): ReadonlyArray<Column<CandidateItem>> {
  return [
    { key: 'rank', header: '名次', cell: (item) => <span className="candidate-rank" aria-label={`第 ${item.rank} 名`}>#{item.rank}</span> },
    {
      key: 'stock', header: '股票', cell: (item) => <>
        <Link className="symbol-link" to={stockPath(item)}><strong>{item.instrument.symbol}</strong> {item.instrument.name}</Link>
        <div className="small-note">{exchangeLabel(item.instrument.exchange)} · {candidateStrategyLabel(item.strategy)}</div>
      </>,
    },
    { key: 'group', header: <>所屬族群（<Term id="heat_rank">名次</Term>）</>, wrap: true, cellClassName: 'candidate-group-cell', cell: groupText },
    { key: 'close', header: '最近收盤', num: true, cell: (item) => <CloseValue item={item} /> },
    { key: 'entry', header: <Term id="entry_zone">進場區</Term>, num: true, cellClassName: 'level-entry', cell: (item) => formatEntryZone(item.levels) },
    { key: 'stop', header: <Term id="support">停損</Term>, num: true, cellClassName: 'level-stop', cell: (item) => formatPrice(item.levels.invalid_price) },
    { key: 'target', header: <Term id="target">目標</Term>, num: true, cellClassName: 'level-target', cell: (item) => <Targets levels={item.levels} breakable={false} /> },
    { key: 'rr', header: <Term id="rr">RR</Term>, num: true, cell: (item) => <Badge tone="primary" className="badge-compact">{formatRiskReward(item.levels.risk_reward)}</Badge> },
    { key: 'total', header: <Term id="candidate_score">總分</Term>, num: true, cell: (item) => formatCandidateScore(item.total_score) },
    { key: 'reason', header: '主要理由', wrap: true, cellClassName: 'candidate-reason-cell', cell: (item) => <FirstReason item={item} /> },
    {
      key: 'ai', header: <span className="sr-only">AI 說明</span>, cell: (item) => (
        <button type="button" className="badge badge-accent badge-compact candidate-ai-toggle" aria-expanded={open.has(item.rank)} aria-controls={`candidate-detail-${item.rank}`} onClick={() => toggle(item.rank)}>
          {candidateAiEntry(item.llm_note)}
        </button>
      ),
    },
  ]
}

function CandidateMiniCard({ item, hidden }: { item: CandidateItem; hidden: boolean }) {
  const { instrument, levels } = item
  return (
    <article className="card candidate-mini" data-candidate-card={item.rank} hidden={hidden}>
      <div className="candidate-mini-head">
        <span className="candidate-rank" aria-label={`第 ${item.rank} 名`}>#{item.rank}</span>
        <Link className="symbol-link" to={stockPath(item)}><strong>{instrument.symbol}</strong> {instrument.name}</Link>
        <span className="candidate-mini-total"><Term id="candidate_score">總分</Term> <b>{formatCandidateScore(item.total_score)}</b></span>
      </div>
      <div className="small-note">{exchangeLabel(instrument.exchange)} · {candidateStrategyLabel(item.strategy)} · {groupText(item)}</div>
      <dl className="candidate-mini-levels">
        <div><dt>收盤</dt><dd><CloseValue item={item} /></dd></div>
        <div><dt><Term id="entry_zone">進場區</Term></dt><dd className="level-entry">{formatEntryZone(levels)}</dd></div>
        <div><dt><Term id="support">停損</Term></dt><dd className="level-stop">{formatPrice(levels.invalid_price)}</dd></div>
        <div><dt><Term id="target">目標</Term></dt><dd className="level-target"><Targets levels={levels} breakable={false} /></dd></div>
      </dl>
      <p className="candidate-mini-reason"><FirstReason item={item} /></p>
      <details className="details candidate-mini-ai"><summary>AI 說明</summary><CandidateDetail item={item} /></details>
    </article>
  )
}

function TodayCandidateList({ items }: { items: CandidateItem[] }) {
  const [open, setOpen] = useState<ReadonlySet<number>>(() => new Set())
  const [showAll, setShowAll] = useState(false)
  const setRank = (rank: number, value: boolean) => setOpen((current) => {
    if (current.has(rank) === value) return current
    const next = new Set(current)
    if (value) next.add(rank)
    else next.delete(rank)
    return next
  })
  const folded = (index: number) => !showAll && index >= TODAY_VISIBLE
  const rest = Math.max(0, items.length - TODAY_VISIBLE)
  return (
    <>
      <DataTable
        wrapClassName="candidate-table-wrap"
        className="candidate-table"
        columns={candidateColumns(open, (rank) => setRank(rank, !open.has(rank)))}
        rows={items}
        rowKey={(item) => item.instrument.exchange + item.instrument.symbol}
        rowProps={(item, index) => ({ hidden: folded(index), 'data-candidate-rank': item.rank })}
        // Every detail stays in the DOM inside <details>, so the screenshot tool can open them all (DESIGN_SYSTEM §5).
        detailRow={(item) => ({
          props: { 'data-candidate-detail': item.rank },
          content: (
            <details className="candidate-detail" id={`candidate-detail-${item.rank}`} open={open.has(item.rank)} onToggle={(event) => setRank(item.rank, event.currentTarget.open)}>
              <summary>{item.instrument.symbol} {item.instrument.name}</summary>
              <CandidateDetail item={item} />
            </details>
          ),
        })}
      />
      <div className="candidate-cards">
        {items.map((item, index) => <CandidateMiniCard key={item.instrument.exchange + item.instrument.symbol} item={item} hidden={folded(index)} />)}
      </div>
      {rest > 0 && (
        <details className="candidate-more" open={showAll} onToggle={(event) => setShowAll(event.currentTarget.open)}>
          <summary>{showAll ? `收合其餘 ${rest} 檔` : `顯示其餘 ${rest} 檔`}</summary>
        </details>
      )}
    </>
  )
}

export function CandidatesSection({ data, loading, error }: { data: CandidatesResponse | undefined; loading: boolean; error: unknown }) {
  const state = data ? candidatesState(data) : null
  const t1 = state?.kind === 'list' ? candidateT1Text(data?.trading_date) : null
  return (
    <section className="candidates-section" aria-labelledby="candidates-title">
      <div className="section-head">
        <div><div className="eyebrow">每日候選 · 依評分排序</div><h2 id="candidates-title">明日候選</h2></div>
        {data && data.status !== 'not_computed' && (
          <div className="board-dates"><DateBadge date={formatDate(data.trading_date)} />{state?.kind === 'list' && <Badge>{data.candidate_count} 檔</Badge>}</div>
        )}
      </div>
      {t1 && <p className="small-note candidate-t1">{t1}</p>}
      <p className="small-note candidate-disclaimer">{CANDIDATE_DISCLAIMER}</p>
      {loading
        ? <Skeleton lines={4} label="明日候選載入中…" />
        : error
          ? <Card><EmptyState title="資料暫時無法載入" reason={errorReason(error)} /></Card>
          : !state
            ? null
            : state.kind === 'list'
              ? <TodayCandidateList items={state.items} />
              : <Card><EmptyState title={state.kind === 'zero' ? '當日零候選' : '尚無候選清單'} reason={state.text} /></Card>}
    </section>
  )
}
