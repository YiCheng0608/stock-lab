import { useEffect, useRef, useState } from 'react'
import type { MouseEvent, ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { Term } from '../components/Term'
import { useSameAsPage } from '../components/pageDate'
import { Badge, Card, DataTable, DateBadge, EmptyState, ScoreBar, Skeleton, cx, type Column } from '../components/ui'
import { AiBadge } from '../news/NewsViews'
import { EVIDENCE_PATH, NO_EVIDENCE_LINK_LABEL, NO_EVIDENCE_TEXT } from '../strategy/evidence'
import { STRATEGY_LINK_LABEL } from '../strategy/strategyName'
import { AddPlanButton } from '../tracking/TrackingViews'
import type { CandidateComponent, CandidateComponentKey, CandidateItem, CandidateSubItem, CandidatesResponse } from '../types'
import {
  CANDIDATE_COMPONENTS,
  CANDIDATE_DISCLAIMER,
  GROUP_EVENT_PENDING,
  NOTE_DISCLAIMER,
  NOTE_TITLE,
  PARTIAL_NOTE,
  TODAY_VISIBLE,
  averageVolumeText,
  formatLots,
  candidateAiEntry,
  candidateChange,
  candidateGroupState,
  candidateGroupText,
  candidateNoteView,
  candidateSourceText,
  candidateStrategyLabel,
  candidateT1Text,
  candidatesState,
  chartToggleLabel,
  nextChartRank,
  OVERNIGHT_US_TITLE,
  candidateOvernightLinks,
  overnightUsView,
  type OvernightUsItem,
  type OvernightUsView,
  rowClickToggles,
  exchangeLabel,
  formatCandidateClose,
  formatCandidateScore,
  formatDate,
  formatEntryZone,
  formatPrice,
  formatRiskReward,
  formatRiskRewardWithBasis,
  formatSubItemValue,
  groupBoardLabel,
  ladderLabel,
  priceLadder,
  sparkline,
  SPARKLINE_HEIGHT,
  SPARKLINE_WIDTH,
  riskRewardBasisNote,
  stockPath,
  subItemLabel,
} from './candidates'
import { EntryConditions, EntryPlanCard } from './EntryPlanCard'
import { entryPlanView } from './entryPlan'

// Daily candidate list (candidate_score_v1, #215): the today list (#276); the stock strategy board (#274) reuses the
// note, reasons and score details.
// Copy follows UI_COPY_SPEC §10; reason dots and level colours follow DESIGN_SYSTEM §7; in-place terms follow §7;
// the today list (one list at every width, #510) follows DESIGN_SYSTEM §5 候選列表.

function errorReason(error: unknown): string {
  return error instanceof Error ? error.message : '請稍後重新整理'
}

function InferenceBadge() {
  return <Badge tone="accent" dot className="badge-compact">推論</Badge>
}

// A 0–1 component score on the bar's 0–100 scale (#654); null stays null so the bar reads 「—」.
const scoreOf = (value: number | null | undefined) => (typeof value === 'number' && Number.isFinite(value) ? value * 100 : null)

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
              <dd title={component?.score == null ? component?.null_explanation ?? undefined : undefined}><ScoreBar label={label} value={scoreOf(component?.score)} /></dd>
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

// Four columns at most inside a card, short headers so 390px fits; the component title is its own row (DESIGN_SYSTEM §5.1).
const SUB_ITEM_COLUMNS: ReadonlyArray<Column<SubItemRow>> = [
  { key: 'sub', header: '子項', wrap: true, cell: ({ name, sub }) => <>{subItemLabel(name)}{sub.null_explanation && <div className="small-note">{sub.null_explanation}</div>}</> },
  { key: 'value', header: '原值', num: true, cell: ({ name, sub }) => formatSubItemValue(name, sub.value) },
  { key: 'percentile', header: <Term id="percentile">百分位</Term>, num: true, cell: ({ sub }) => formatCandidateScore(sub.percentile) },
  { key: 'weight', header: '權重（%）', num: true, cell: ({ sub }) => String(Math.round(sub.weight * 100)) },
]

export function ScoreDetails({ item, open }: { item: CandidateItem; open: boolean }) {
  const sameDate = useSameAsPage(item.data_as_of)
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
          ? <span className="score-group-title">{label}<ScoreBar label={label} value={scoreOf(component?.score)} /><span className="score-group-weight">權重 {Math.round((component?.weight ?? 0) * 100)}%</span>{component?.inference && <InferenceBadge />}</span>
          : null}
      />
      {item.alternatives.length > 0 && (
        <div className="small-note">同檔另一策略：{item.alternatives.map((alt) => `${candidateStrategyLabel(alt.strategy)} 總分 ${formatCandidateScore(alt.total_score)}`).join('、')}（只留總分高者）</div>
      )}
      <div className="small-note"><Term id="candidate_score">權重涵蓋</Term> {Math.round(item.weight_coverage * 100)}%{sameDate ? '' : ` · 資料日期 ${formatDate(item.data_as_of) ?? '待核實'}`}{item.levels.earliest_execution_date ? ` · 規則最早執行日 ${formatDate(item.levels.earliest_execution_date)}` : ''}</div>
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
          {/* One 推論 mark an item (#661): the API text already ends 「（推論）」; the badge only when it does not. */}
          {reason.inference && !reason.text.includes('推論') && <InferenceBadge />}
        </li>
      ))}
    </ul>
  )
}

// 目標一／目標二 on one line (DESIGN_SYSTEM §5; UI_COPY_SPEC §8.4).
function Targets({ levels }: { levels: CandidateItem['levels'] }) {
  return <>{formatPrice(levels.target_1)}{levels.target_2 != null && <span className="level-target-2">／{formatPrice(levels.target_2)}</span>}</>
}

// ---- today list (#510; DESIGN_SYSTEM §5 候選列表): one list at every width, two lines a candidate, detail below ----

// 「20 日均量 1,682 張（資料日期 2026/10/16，候選門檻 1,000 張）」 (#490): the lots the liquidity floor read; nothing on
// runs scored before candidate_score_v6. The today list shows it in the detail's 「資料日期與來源」 (#510).
// The date only when it is not the page date (#661); 待核實 always shows.
export function LiquidityNote({ item }: { item: Pick<CandidateItem, 'liquidity'> }) {
  const liquidity = item.liquidity
  const sameDate = useSameAsPage(liquidity?.data_as_of)
  if (!liquidity) return null
  const date = sameDate ? '' : `資料日期 ${formatDate(liquidity.data_as_of) ?? '待核實'}，`
  return (
    <div className="small-note candidate-liquidity" data-liquidity={liquidity.state ?? undefined}>
      {`${averageVolumeText(liquidity.average_volume_lots_20d)}（${date}候選門檻 ${formatLots(liquidity.minimum_lots)}）`}
    </div>
  )
}

// 「資料日期 YYYY/MM/DD」 for a detail line, or nothing when it is the page date (#661, DESIGN_SYSTEM §7).
function DataDateLine({ date }: { date: string | null | undefined }) {
  if (useSameAsPage(date)) return null
  return <div className="small-note candidate-data-date">資料日期 {formatDate(date) ?? '待核實'}</div>
}

function CloseValue({ item }: { item: CandidateItem }) {
  const change = candidateChange(item.market)
  return <><div>{formatCandidateClose(item.market)}</div><div className={cx('candidate-change', change.tone && `tone-${change.tone}`)}>{change.text}</div></>
}

// The row's RR and, under it, what its entry is (#580; UI_COPY_SPEC §10): 「以進場區中點計算」 for pullback_v4.
function RiskRewardValue({ levels }: { levels: CandidateItem['levels'] }) {
  const note = riskRewardBasisNote(levels.risk_reward_basis)
  return <><div>{formatRiskReward(levels.risk_reward)}</div>{note && <div className="small-note candidate-rr-basis">{note}</div>}</>
}

// The rule levels as labelled cells: in the detail beside the AI note, and on the row when the sentence states a reason
// instead of the prices (decision 6647903049). Facts, so outside the AI block (DESIGN_SYSTEM §7).
function LevelCells({ item, className, rr = false }: { item: CandidateItem; className: string; rr?: boolean }) {
  const { levels } = item
  return (
    <dl className={className}>
      <div><dt><Term id="entry_zone">進場區</Term>（元）</dt><dd className="level-entry">{formatEntryZone(levels)}</dd></div>
      <div><dt><Term id="support">停損</Term>（元）</dt><dd className="level-stop">{formatPrice(levels.invalid_price)}</dd></div>
      <div><dt><Term id="target">{levels.target_2 != null ? '目標一／二' : '目標一'}</Term>（元）</dt><dd className="level-target"><Targets levels={levels} /></dd></div>
      {rr && <div><dt><Term id="rr">RR</Term></dt><dd className="candidate-rr">{formatRiskRewardWithBasis(levels.risk_reward, levels.risk_reward_basis, levels.entry)}</dd></div>}
    </dl>
  )
}

// The expanded detail (#510): the AI note first, its 為何入選 the lead; the rule levels, 加入追蹤 and the stock-page link
// beside it; the conditions, every component and reason, and the data date and sources folded underneath.
function CandidateDetail({ item }: { item: CandidateItem }) {
  return (
    <div className="candidate-detail-body">
      <CandidateNote item={item} />
      <div className="candidate-detail-side">
        <LevelCells item={item} className="candidate-detail-levels" rr />
        <div className="candidate-detail-actions">
          <AddPlanButton signalId={item.signal_id} candidateId={item.candidate_id} openPlanId={item.open_plan_id} />
          <Link className="text-link" to={stockPath(item)}>評分細節 → 個股頁</Link>
        </div>
      </div>
      <div className="candidate-detail-folds">
        <EntryConditions item={item} />
        <details className="details candidate-detail-scores">
          <summary>分項分數與理由</summary>
          {item.partial_components && <div className="candidate-partial small-note">{PARTIAL_NOTE}</div>}
          <ComponentScores item={item} />
          <ReasonList reasons={item.reasons} />
        </details>
        <details className="details candidate-detail-sources">
          <summary>資料日期與來源</summary>
          <LiquidityNote item={item} />
          <DataDateLine date={item.data_as_of} />
          <div className="small-note">來源：{candidateSourceText(item)}</div>
        </details>
      </div>
    </div>
  )
}

// The group on one line (#493): name and board rank; the long form with 「事件資料待補」 is in the row's title.
function groupShortText(item: CandidateItem): ReactNode {
  const group = item.groups[0]
  if (!group) return '無所屬族群'
  const board = groupBoardLabel(group.board)
  const state = candidateGroupState(group)
  if (state === 'ranked') return `${group.name}（${board} #${group.rank}）`
  if (state === 'pending') return <>{group.name}（{board}，<Term id="event_data_pending">{GROUP_EVENT_PENDING}</Term>）</>
  return `${group.name}（${board}，未排名）`
}

// The price ladder (DESIGN_SYSTEM §5 候選列表): the stop at the left end, the first target at the right, a tick at the
// entry and a dot at the close. A drawing of numbers the row already states, so it carries a label and no text.
export function PriceLadder({ item }: { item: CandidateItem }) {
  const view = priceLadder(item.levels, item.market?.close)
  if (!view) return null
  return (
    <div className="price-ladder" role="img" aria-label={ladderLabel(view)} data-ladder-outside={view.outside ?? undefined}>
      <i className="price-ladder-risk" style={{ width: `${view.entry}%` }} />
      <i className="price-ladder-reward" style={{ left: `${view.entry}%`, width: `${100 - view.entry}%` }} />
      <i className="price-ladder-entry" style={{ left: `${view.entry}%` }} />
      <i className="price-ladder-close" style={{ left: `${view.close}%` }} />
    </div>
  )
}

// The last 30 sessions' closes as one line (#653; DESIGN_SYSTEM §5 候選列表): red when the span rose, green when it fell,
// a gap where a session has no close. Like the ladder it carries a label (the span and its change) and no text.
export function Sparkline({ item }: { item: Pick<CandidateItem, 'recent_closes'> }) {
  const view = sparkline(item.recent_closes)
  if (!view) return null
  return (
    <svg className={cx('sparkline', `sparkline-${view.tone}`)} role="img" aria-label={view.label} data-sparkline-tone={view.tone}
      width={SPARKLINE_WIDTH} height={SPARKLINE_HEIGHT} viewBox={`0 0 ${SPARKLINE_WIDTH} ${SPARKLINE_HEIGHT}`} preserveAspectRatio="none">
      <path d={view.path} />
    </svg>
  )
}

// The row's two drawings on one line under the sentence: the sparkline, then the price ladder (DESIGN_SYSTEM §5).
function RowFigures({ item }: { item: CandidateItem }) {
  if (!sparkline(item.recent_closes) && !priceLadder(item.levels, item.market?.close)) return null
  return <div className="candidate-row-figures"><Sparkline item={item} /><PriceLadder item={item} /></div>
}

// One US index's change: 「費半 +1.23%」, red up and green down (Taiwan's convention), its own date when the four
// differ, 「非最新」 when not of the expected night (Issue 681).
function OvernightChange({ entry, stale }: { entry: OvernightUsItem; stale: boolean }) {
  return (
    <span className="overnight-us-item" data-us-index={entry.symbol}>
      {entry.label} <span className={cx('overnight-us-change', entry.tone && `tone-${entry.tone}`)}>{entry.text}</span>
      {entry.date && `（${entry.date}）`}{stale && ' 非最新'}
    </span>
  )
}

// The 隔夜美股 line under the list's head (Issue 681; UI_COPY_SPEC §10, DESIGN_SYSTEM §5 候選列表): one line of inline
// runs, so it reads as one line of page text (page_checks T22): 「隔夜美股 資料 2026/11/13 S&P 500 +0.53% · NASDAQ …」.
export function OvernightUsLine({ view }: { view: OvernightUsView | null }) {
  if (!view) return null
  return (
    <p className="overnight-us" aria-label={OVERNIGHT_US_TITLE}>
      <span className="overnight-us-title">{OVERNIGHT_US_TITLE}</span>
      {view.lead && <> <span className="overnight-us-lead">{view.lead}</span></>}
      {view.date && <> <span className="overnight-us-date">資料 {view.date}</span></>}
      {view.items.map((entry, index) => (
        <span key={entry.symbol}>{index === 0 ? ' ' : ' · '}<OvernightChange entry={entry} stale={entry.stale} /></span>
      ))}
    </p>
  )
}

// Below 1280px a row opens its own K-line card (#665): the card's content and whether it is open.
type RowChart = { open: boolean; onToggle: () => void; content: ReactNode }

// One candidate (#510): who (rank, name, market · group) and how to enter (the #491 sentence) on two lines, the close,
// RR and total on the right, then the AI entry. The detail is a <details> under the row the button opens, so every
// detail stays in the DOM and the screenshot tool can open them all (DESIGN_SYSTEM §5 候選列表). Below 1280px the
// row's K-line card sits between the row and the detail; it is not a <details>, so opening every <details> mounts no
// chart, and a closed row renders an empty slot only (#665).
function CandidateRow({ item, hidden, open, onOpen, selected, onSelect, chart, links = [] }: { item: CandidateItem; hidden: boolean; open: boolean; onOpen: (open: boolean) => void; selected: boolean; onSelect?: () => void; chart?: RowChart; links?: OvernightUsItem[] }) {
  const { instrument } = item
  const levelsInSentence = entryPlanView(item).kind === 'levels'
  const detailId = `candidate-detail-${item.rank}`
  const chartId = `candidate-chart-${item.rank}`
  // A tap on the row's free space opens or closes the card too; the keyboard uses the rank button (decision 6841170465).
  const onRowClick = chart
    ? (event: MouseEvent<HTMLDivElement>) => {
      const selection = typeof window === 'undefined' ? '' : window.getSelection()?.toString() ?? ''
      if (rowClickToggles(event.target instanceof Element ? event.target : null, selection)) chart.onToggle()
    }
    : undefined
  return (
    <li className={cx('candidate-row', open && 'candidate-row-open', selected && 'candidate-row-selected', chart && 'candidate-row-chartable', chart?.open && 'candidate-row-charted')} data-candidate-rank={item.rank} hidden={hidden}>
      <div className="candidate-row-main" onClick={onRowClick}>
        <div className="candidate-row-body">
          {/* One line of inline runs: 「#1 2377 微星 上市 · 族群」 reads as one line of page text too (page_checks T7). */}
          <p className="candidate-row-title">
            {/* With a chart beside the list the rank is the button that picks the row's chart; below 1280px it opens the
                row's own card. Its text stays 「#1」 either way. */}
            {onSelect
              ? <button type="button" className="candidate-rank candidate-rank-button" aria-label={`第 ${item.rank} 名，顯示走勢圖`} aria-pressed={selected} onClick={onSelect}>#{item.rank}</button>
              : chart
                ? <button type="button" className="candidate-rank candidate-rank-button candidate-chart-toggle" aria-label={chartToggleLabel(item.rank, chart.open)} aria-expanded={chart.open} aria-controls={chartId} onClick={chart.onToggle}>#{item.rank}</button>
                : <span className="candidate-rank" aria-label={`第 ${item.rank} 名`}>#{item.rank}</span>}{' '}
            <Link className="symbol-link candidate-row-name" to={stockPath(item)}><strong>{instrument.symbol}</strong> {instrument.name}</Link>{' '}
            {/* Issue 681: the semiconductor groups' 費半 change right after the name, so the line's ellipsis cuts the
                market and group, not it (the title is one line at every width). */}
            {links.map((entry) => <span key={entry.symbol} className="candidate-row-us"><OvernightChange entry={{ ...entry, date: null }} stale={!entry.current} />{' '}</span>)}
            <span className="candidate-row-meta" title={item.groups[0] ? candidateGroupText(item.groups[0]) : undefined}>{exchangeLabel(instrument.exchange)} · {groupShortText(item)}</span>
          </p>
          <EntryPlanCard item={item} className="candidate-entry" conditions={false} />
          {!levelsInSentence && <LevelCells item={item} className="candidate-row-levels" />}
          <RowFigures item={item} />
        </div>
        <dl className="candidate-row-nums">
          <div className="candidate-row-close"><dt>收盤（元）</dt><dd><CloseValue item={item} /></dd></div>
          <div className="candidate-row-rr"><dt><Term id="rr">RR</Term></dt><dd><RiskRewardValue levels={item.levels} /></dd></div>
          <div><dt><Term id="candidate_score">總分</Term>（0–100）</dt><dd>{formatCandidateScore(item.total_score)}</dd></div>
        </dl>
        <button type="button" className="badge badge-accent badge-compact candidate-ai-toggle" aria-expanded={open} aria-controls={detailId} onClick={() => onOpen(!open)}>
          {candidateAiEntry(item.llm_note)}
        </button>
      </div>
      {chart && (
        <div className="candidate-chart" id={chartId} hidden={!chart.open} role={chart.open ? 'region' : undefined}
          aria-label={chart.open ? `${instrument.symbol} ${instrument.name} 走勢圖` : undefined}>
          {chart.open && chart.content}
        </div>
      )}
      <details className="candidate-detail" id={detailId} open={open} onToggle={(event) => onOpen(event.currentTarget.open)}>
        <summary>{instrument.symbol} {instrument.name}</summary>
        <CandidateDetail item={item} />
      </details>
    </li>
  )
}

// wide: the viewport is at least TERMINAL_MIN_WIDTH (the page measures it); initialChartRank: the row whose card is open
// at first below that width (none on the page; the tests render an open row with it, as they cannot click).
export function TodayCandidateList({ items, renderChart, wide = false, initialChartRank = null, overnight = null }: { items: CandidateItem[]; renderChart?: (item: CandidateItem) => ReactNode; wide?: boolean; initialChartRank?: number | null; overnight?: OvernightUsView | null }) {
  const [open, setOpen] = useState<ReadonlySet<number>>(() => new Set())
  const [showAll, setShowAll] = useState(false)
  const setRank = (rank: number, value: boolean) => setOpen((current) => {
    if (current.has(rank) === value) return current
    const next = new Set(current)
    if (value) next.add(rank)
    else next.delete(rank)
    return next
  })
  const rest = Math.max(0, items.length - TODAY_VISIBLE)
  // The chart beside the list shows one candidate: the first until another row's rank is pressed.
  const [picked, setPicked] = useState<number | null>(null)
  // Below 1280px: the one row whose card is open (#665), none at first, so no chart mounts and no /bars is fetched.
  const [chartRank, setChartRank] = useState<number | null>(initialChartRank)
  // Crossing 1280px starts each layout from its default: the first row beside the list, no card below (decision 6841170465).
  const lastWide = useRef(wide)
  useEffect(() => {
    if (lastWide.current === wide) return
    lastWide.current = wide
    setPicked(null)
    setChartRank(null)
  }, [wide])
  const terminal = !!renderChart && wide
  const selected = items.find((item) => item.rank === picked) ?? items[0]
  const list = (
    <>
      <ol className="candidate-list">
        {items.map((item, index) => (
          <CandidateRow key={item.instrument.exchange + item.instrument.symbol} item={item} hidden={!showAll && index >= TODAY_VISIBLE} open={open.has(item.rank)} onOpen={(value) => setRank(item.rank, value)}
            selected={terminal && item === selected} onSelect={terminal ? () => setPicked(item.rank) : undefined} links={candidateOvernightLinks(item, overnight)}
            chart={renderChart && !wide ? { open: chartRank === item.rank, onToggle: () => setChartRank((current) => nextChartRank(current, item.rank)), content: chartRank === item.rank ? renderChart(item) : null } : undefined} />
        ))}
      </ol>
      {rest > 0 && (
        <details className="candidate-more" open={showAll} onToggle={(event) => setShowAll(event.currentTarget.open)}>
          <summary>{showAll ? `收合其餘 ${rest} 檔` : `顯示其餘 ${rest} 檔`}</summary>
        </details>
      )}
    </>
  )
  if (!terminal || !selected) return list
  // 盤後終端 (DESIGN_SYSTEM §5 候選列表): the list on the left, the picked candidate's chart on the right from 1280px up;
  // below that the aside is not rendered at all (#665), so no chart mounts in a zero-width box.
  return (
    <div className="candidates-terminal">
      <div className="candidates-terminal-list">{list}</div>
      <aside className="candidates-terminal-chart" aria-label={`${selected.instrument.symbol} ${selected.instrument.name} 走勢圖`} data-chart-rank={selected.rank}>{renderChart(selected)}</aside>
    </div>
  )
}

export function CandidatesSection({ data, loading, error, renderChart, wide = false }: { data: CandidatesResponse | undefined; loading: boolean; error: unknown; renderChart?: (item: CandidateItem) => ReactNode; wide?: boolean }) {
  const state = data ? candidatesState(data) : null
  const t1 = state?.kind === 'list' ? candidateT1Text(data?.trading_date) : null
  const overnight = overnightUsView(data?.overnight_us)
  return (
    <section className="candidates-section" aria-labelledby="candidates-title">
      {/* One head line (#510): title, date and count, the T+1 sentence and the disclaimer, then the strategy name and 策略說明 (#577);
          the 現行規則尚無證據 line (Issue 693) under it. */}
      <div className="candidates-head">
        <h2 id="candidates-title">今日名單</h2>
        {data && data.status !== 'not_computed' && (
          <span className="board-dates"><DateBadge date={formatDate(data.trading_date)} />{state?.kind === 'list' && <Badge>{data.candidate_count} 檔</Badge>}</span>
        )}
        <p className="small-note candidate-notes">{t1 && <span className="candidate-t1">{t1}</span>}<span className="candidate-disclaimer">{CANDIDATE_DISCLAIMER}。</span></p>
        <Link className="text-link candidates-strategy-link" to="/strategy">{STRATEGY_LINK_LABEL}</Link>
        {/* Issue 693: its own line under the head in every state (list, zero, not computed), the warning colour. */}
        <p className="small-note candidate-evidence">{NO_EVIDENCE_TEXT} <Link className="text-link" to={EVIDENCE_PATH}>{NO_EVIDENCE_LINK_LABEL}</Link></p>
      </div>
      {/* Issue 681: under the head in every state (list, zero, not computed), not while loading or failed. */}
      {!loading && !error && <OvernightUsLine view={overnight} />}
      {loading
        ? <Skeleton lines={4} label="今日名單載入中…" />
        : error
          ? <Card><EmptyState title="資料暫時無法載入" reason={errorReason(error)} /></Card>
          : !state
            ? null
            : state.kind === 'list'
              ? <TodayCandidateList items={state.items} renderChart={renderChart} wide={wide} overnight={overnight} />
              : <Card><EmptyState title={state.kind === 'zero' ? '當日零候選' : '尚無候選清單'} reason={state.text} /></Card>}
    </section>
  )
}
