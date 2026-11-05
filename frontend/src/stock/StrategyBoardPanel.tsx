import { CandidateNote, ReasonList, ScoreDetails } from '../candidates/CandidateViews'
import { EntryPlanCard } from '../candidates/EntryPlanCard'
import {
  CANDIDATE_DISCLAIMER,
  averageVolumeText,
  candidateStrategyLabel,
  formatCandidateScore,
  formatDate,
  formatLots,
  formatPrice,
  formatRiskReward,
  liquidityExclusionText,
} from '../candidates/candidates'
import { Term } from '../components/Term'
import { Badge, DataTable, DateBadge, EmptyState, type Column } from '../components/ui'
import { productActionReasonLabel } from '../presentation'
import type { CandidateItem, GapReason, StrategyActionableLevels, StrategyBoard as Board, StrategyBoardRow } from '../types'
import {
  BOARD_NOTE,
  BOARD_TITLE,
  CANDIDATE_MORE_LABEL,
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

function StatusCell({ row, floorNote }: { row: StrategyBoardRow; floorNote: string | null }) {
  return <>
    <Badge tone={STATUS_TONES[row.status] ?? 'default'} dot className="badge-compact" data-strategy-status={row.status}>{statusLabel(row.status)}</Badge>
    {row.status === 'conditional' && row.earliest_execution_date && <div className="small-note">最早執行日 {formatDate(row.earliest_execution_date)}</div>}
    {row.status === 'conditional' && floorNote && <div className="small-note strategy-floor-note" data-liquidity-exclusion>{floorNote}</div>}
  </>
}

export function ActionableLevels({ levels }: { levels: StrategyActionableLevels }) {
  const breakout = levels.entry_type === 'breakout'
  return (
    <dl className="strategy-levels strategy-levels-actionable">
      {breakout
        ? <div><dt>觸發（元）</dt><dd className="level-entry">{formatPrice(levels.trigger_price)}</dd></div>
        : <div><dt><Term id="entry_zone">進場區</Term>（元）</dt><dd className="level-entry">{formatPrice(levels.entry_low)}～{formatPrice(levels.entry_high)}</dd></div>}
      <div><dt><Term id="support">停損</Term>（元）</dt><dd className="level-stop">{formatPrice(levels.invalid_price)}</dd></div>
      <div><dt><Term id="target">{levels.target_2 != null ? '目標一／目標二' : '目標一'}</Term>（元）</dt><dd className="level-target">{formatPrice(levels.target_1)}{levels.target_2 != null && <>／{formatPrice(levels.target_2)}</>}</dd></div>
      <div><dt><Term id="rr">RR</Term></dt><dd><Badge tone="primary" className="badge-compact">{formatRiskReward(levels.risk_reward)}</Badge></dd></div>
    </dl>
  )
}

export function ObservationBlock({ row, folded = false }: { row: StrategyBoardRow; folded?: boolean }) {
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
  // #519: the research tab folds the block behind its own label; the summary card keeps it open.
  if (folded) {
    return (
      <details className="strategy-observation" data-strategy-levels={levels.availability}>
        <summary className="strategy-observation-label">{OBSERVATION_LABEL}</summary>
        {body}
      </details>
    )
  }
  return (
    <div className="strategy-observation" data-strategy-levels={levels.availability}>
      <div className="strategy-observation-label">{OBSERVATION_LABEL}</div>
      {body}
    </div>
  )
}

export const NO_LEVELS_TEXT = '無價位'

export function LevelsCell({ row, folded = false }: { row: StrategyBoardRow; folded?: boolean }) {
  if (row.status === 'conditional' && row.levels?.kind === 'actionable') return <ActionableLevels levels={row.levels} />
  if (row.status === 'observation') return <ObservationBlock row={row} folded={folded} />
  return <span className="muted">{NO_LEVELS_TEXT}</span>
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

function columns(floorNote: string | null, gapReasons: GapReason[] | undefined): ReadonlyArray<Column<StrategyBoardRow>> {
  return [
    { key: 'strategy', header: '策略', cell: (row) => <strong><Term id={row.entry_type === 'breakout' ? 'breakout' : 'pullback'}>{row.label}</Term></strong> },
    { key: 'status', header: '狀態', cell: (row) => <StatusCell row={row} floorNote={floorNote} /> },
    { key: 'unmet', header: '差哪個條件', wrap: true, cellClassName: 'strategy-unmet', cell: (row) => unmetText(row, gapReasons) },
    { key: 'levels', header: '價位', wrap: true, cellClassName: 'strategy-levels-cell', cell: (row) => <LevelsCell row={row} folded /> },
  ]
}

function StrategyCard({ row, floorNote, gapReasons }: { row: StrategyBoardRow; floorNote: string | null; gapReasons: GapReason[] | undefined }) {
  return (
    <article className="card strategy-card" data-strategy-card={row.strategy}>
      <div className="strategy-card-head"><strong><Term id={row.entry_type === 'breakout' ? 'breakout' : 'pullback'}>{row.label}</Term></strong><StatusCell row={row} floorNote={floorNote} /></div>
      <p className="strategy-unmet">{unmetText(row, gapReasons)}</p>
      <LevelsCell row={row} folded />
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
      {/* #491: how to enter, before the reasons. */}
      {candidate && <EntryPlanCard item={candidate} onStockPage />}
      {/* #519: the reasons and the AI note fold behind one line; the score details stay their own fold. */}
      {candidate && <details className="details strategy-candidate-more">
        <summary>{CANDIDATE_MORE_LABEL}</summary>
        <ReasonList reasons={candidate.reasons} />
        <CandidateNote item={candidate} />
      </details>}
      {candidate && <ScoreDetails item={candidate} open={false} />}
    </div>
  )
}

// gapReasons: the stock summary's causes (UI_COPY_SPEC §6.1), for 差哪個條件 of an incomplete row (§10.1).
export function StrategyBoardPanel({ board, candidate, gapReasons }: { board: Board | null | undefined; candidate: CandidateItem | null | undefined; gapReasons?: GapReason[] }) {
  if (!board) return null
  // 「…低於 1,000 張門檻，不列候選」 next to every 成立 when the day's run left the stock out (#490).
  const floorNote = liquidityExclusionText(board.liquidity ? { ...board.liquidity, exclusion: board.liquidity.candidate_exclusion } : null)
  return (
    <section className="panel strategy-board" aria-labelledby="strategy-board-title">
      <div className="panel-head">
        <h2 id="strategy-board-title">{BOARD_TITLE}</h2>
        <div className="board-dates">{board.as_of && <DateBadge date={board.as_of} />}<Badge>{levelsVersionLabel(board.levels_version)}</Badge></div>
      </div>
      {/* #519: the 20-session lots and the 說明 fold share one line; opened, the note takes the next. */}
      <div className="board-meta">
        {board.liquidity && (
          <p className="small-note strategy-liquidity" data-liquidity={board.liquidity.state ?? undefined}>
            {averageVolumeText(board.liquidity.average_volume_lots_20d)} · 資料日期 {formatDate(board.liquidity.data_as_of)}
            {board.liquidity.minimum_lots != null && `（候選門檻 ${formatLots(board.liquidity.minimum_lots)}）`}
          </p>
        )}
        <details className="details board-help"><summary>說明</summary><p className="small-note">{BOARD_NOTE}</p></details>
      </div>
      {!board.as_of && <EmptyState reason="此股尚無策略判定資料。" />}
      <CandidateRow board={board} candidate={candidate} />
      <DataTable
        wrapClassName="strategy-table-wrap"
        className="strategy-table"
        columns={columns(floorNote, gapReasons)}
        rows={board.strategies}
        rowKey={(row) => row.strategy}
        rowProps={(row) => ({ 'data-strategy-row': row.strategy })}
        detailRow={(row) => ({ props: { 'data-strategy-detail': row.strategy }, content: <ConditionDetails row={row} /> })}
      />
      <div className="strategy-cards">{board.strategies.map((row) => <StrategyCard key={row.strategy} row={row} floorNote={floorNote} gapReasons={gapReasons} />)}</div>
    </section>
  )
}
