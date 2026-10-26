import { CandidateNote, ReasonList, ScoreDetails } from '../candidates/CandidateViews'
import { CANDIDATE_DISCLAIMER, candidateStrategyLabel, formatCandidateScore, formatDate, formatPrice, formatRiskReward } from '../candidates/candidates'
import { Term } from '../components/Term'
import { Badge, DataTable, DateBadge, EmptyState, type Column } from '../components/ui'
import { productActionReasonLabel } from '../presentation'
import type { CandidateItem, StrategyActionableLevels, StrategyBoard as Board, StrategyBoardRow } from '../types'
import {
  BOARD_NOTE,
  BOARD_TITLE,
  LEVELS_MISSING_TEXT,
  OBSERVATION_LABEL,
  STATUS_TONES,
  conditionViews,
  levelsVersionLabel,
  observationLines,
  statusLabel,
  trendUnreachableText,
  unmetText,
} from './strategyBoard'

// Stock strategy board (#274): one row per registered strategy at the top of the 研究條件 tab, replacing the
// candidate panel and the static condition list. Desktop is a table, 640px and below one card per strategy
// (DESIGN_SYSTEM §5 策略總表). Actionable levels come from the signal, observation levels from strategy_levels;
// the two never share a block (DESIGN_SYSTEM §7). The AI note appears only on the candidate row.

function StatusCell({ row }: { row: StrategyBoardRow }) {
  return <>
    <Badge tone={STATUS_TONES[row.status] ?? 'default'} dot className="badge-compact" data-strategy-status={row.status}>{statusLabel(row.status)}</Badge>
    {row.status === 'conditional' && row.earliest_execution_date && <div className="small-note">最早執行日 {formatDate(row.earliest_execution_date)}</div>}
  </>
}

function ActionableLevels({ levels }: { levels: StrategyActionableLevels }) {
  const breakout = levels.entry_type === 'breakout'
  return (
    <dl className="strategy-levels strategy-levels-actionable">
      {breakout
        ? <div><dt>觸發</dt><dd className="level-entry">{formatPrice(levels.trigger_price)}</dd></div>
        : <div><dt><Term id="entry_zone">進場區</Term></dt><dd className="level-entry">{formatPrice(levels.entry_low)}～{formatPrice(levels.entry_high)}</dd></div>}
      <div><dt><Term id="support">停損</Term></dt><dd className="level-stop">{formatPrice(levels.invalid_price)}</dd></div>
      <div><dt><Term id="target">目標</Term></dt><dd className="level-target">{formatPrice(levels.target_1)}{levels.target_2 != null && <>／{formatPrice(levels.target_2)}</>}</dd></div>
      <div><dt><Term id="rr">RR</Term></dt><dd><Badge tone="primary" className="badge-compact">{formatRiskReward(levels.risk_reward)}</Badge></dd></div>
    </dl>
  )
}

function ObservationBlock({ row }: { row: StrategyBoardRow }) {
  const levels = row.levels?.kind === 'observation' ? row.levels : null
  if (!levels) return <div className="strategy-observation strategy-missing" data-strategy-levels="missing">{LEVELS_MISSING_TEXT}</div>
  let body
  if (levels.availability === 'levels') {
    body = <>
      <dl className="strategy-levels">
        {observationLines(levels).map((line) => <div key={line.key}><dt>{line.label}</dt><dd className={line.className}>{line.value}</dd></div>)}
      </dl>
      {levels.reachable_next_session === false && <div className="small-note strategy-unreachable">超出下一交易日漲跌停範圍，下一交易日無法達到。</div>}
      {levels.next_session_date && <div className="small-note">對象：下一交易日 {formatDate(levels.next_session_date)} 收盤；價位為參考，成立當天依實際資料重算。</div>}
    </>
  } else if (levels.availability === 'trend_unreachable') {
    body = <p className="small-note">{trendUnreachableText(row)}</p>
  } else {
    body = <p className="small-note">不產生觀察價位：{levels.missing_labels.join('、') || '原因待核實'}</p>
  }
  return (
    <div className="strategy-observation" data-strategy-levels={levels.availability}>
      <div className="strategy-observation-label">{OBSERVATION_LABEL}</div>
      {body}
    </div>
  )
}

function LevelsCell({ row }: { row: StrategyBoardRow }) {
  if (row.status === 'conditional' && row.levels?.kind === 'actionable') return <ActionableLevels levels={row.levels} />
  if (row.status === 'observation') return <ObservationBlock row={row} />
  return <span className="muted">無價位</span>
}

function ConditionDetails({ row }: { row: StrategyBoardRow }) {
  const views = conditionViews(row, productActionReasonLabel)
  return (
    <details className="details strategy-conditions">
      <summary>{row.label}條件明細</summary>
      {views.length
        ? <ul className="strategy-condition-list">{views.map((view) => (
          <li key={view.code} data-condition={view.code} data-condition-state={view.state}>
            <Badge tone={view.state === 'met' ? 'success' : view.state === 'unmet' ? 'warning' : 'default'} className="badge-compact">{view.stateText}</Badge>
            <span className="strategy-condition-label">{view.label}</span>
            {view.value && <span className="small-note">{view.value}</span>}
            {view.next && <span className="small-note strategy-condition-next">{view.next}</span>}
          </li>
        ))}</ul>
        : <p className="small-note">{row.levels_missing ? '這個資料日的條件明細尚未產生。' : '沒有可列出的條件明細。'}</p>}
    </details>
  )
}

const COLUMNS: ReadonlyArray<Column<StrategyBoardRow>> = [
  { key: 'strategy', header: '策略', cell: (row) => <strong><Term id={row.entry_type === 'breakout' ? 'breakout' : 'pullback'}>{row.label}</Term></strong> },
  { key: 'status', header: '狀態', cell: (row) => <StatusCell row={row} /> },
  { key: 'unmet', header: '差哪個條件', wrap: true, cellClassName: 'strategy-unmet', cell: unmetText },
  { key: 'levels', header: '價位', wrap: true, cellClassName: 'strategy-levels-cell', cell: (row) => <LevelsCell row={row} /> },
]

function StrategyCard({ row }: { row: StrategyBoardRow }) {
  return (
    <article className="card strategy-card" data-strategy-card={row.strategy}>
      <div className="strategy-card-head"><strong><Term id={row.entry_type === 'breakout' ? 'breakout' : 'pullback'}>{row.label}</Term></strong><StatusCell row={row} /></div>
      <p className="strategy-unmet">{unmetText(row)}</p>
      <LevelsCell row={row} />
      <ConditionDetails row={row} />
    </article>
  )
}

function CandidateRow({ board, candidate }: { board: Board; candidate: CandidateItem | null | undefined }) {
  const summary = board.candidate
  if (!summary) return null
  return (
    <div className="strategy-candidate" data-strategy-candidate={summary.rank}>
      <div className="strategy-candidate-head">
        <Badge tone="primary" className="badge-compact">每日候選</Badge>
        <strong>第 {summary.rank} 名 · <Term id="candidate_score">總分</Term> {formatCandidateScore(summary.total_score)} · {candidateStrategyLabel(summary.strategy)}</strong>
        <span className="small-note strategy-candidate-disclaimer">{CANDIDATE_DISCLAIMER}</span>
      </div>
      {candidate && <ReasonList reasons={candidate.reasons} />}
      {candidate && <CandidateNote item={candidate} />}
      {candidate && <ScoreDetails item={candidate} open={false} />}
    </div>
  )
}

export function StrategyBoardPanel({ board, candidate }: { board: Board | null | undefined; candidate: CandidateItem | null | undefined }) {
  if (!board) return null
  return (
    <section className="panel strategy-board" aria-labelledby="strategy-board-title">
      <div className="section-head">
        <div><div className="eyebrow">研究條件 · 每個策略一列</div><h2 id="strategy-board-title">{BOARD_TITLE}</h2></div>
        <div className="board-dates">{board.as_of && <DateBadge date={board.as_of} />}<Badge>{levelsVersionLabel(board.levels_version)}</Badge></div>
      </div>
      <p className="small-note">{BOARD_NOTE}</p>
      {!board.as_of && <EmptyState reason="此股尚無策略判定資料。" />}
      <CandidateRow board={board} candidate={candidate} />
      <DataTable
        wrapClassName="strategy-table-wrap"
        className="strategy-table"
        columns={COLUMNS}
        rows={board.strategies}
        rowKey={(row) => row.strategy}
        rowProps={(row) => ({ 'data-strategy-row': row.strategy })}
        detailRow={(row) => ({ props: { 'data-strategy-detail': row.strategy }, content: <ConditionDetails row={row} /> })}
      />
      <div className="strategy-cards">{board.strategies.map((row) => <StrategyCard key={row.strategy} row={row} />)}</div>
    </section>
  )
}
