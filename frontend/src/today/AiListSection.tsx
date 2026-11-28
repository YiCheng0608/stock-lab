import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { getAiList } from '../api'
import { chartToggleLabel, nextChartRank } from '../candidates/candidates'
import { Badge, cx } from '../components/ui'
import type { AiListPick, AiListReason, AiListResponse } from '../types'
import {
  AI_LIST_ENTRY_CONDITION, AI_LIST_ERROR, AI_LIST_EXIT, AI_LIST_GAPS, AI_LIST_INPUT_GAPS, AI_LIST_LEVEL_REFS, AI_LIST_LOADING, AI_LIST_MARK, AI_LIST_MORE,
  AI_LIST_MISSING, AI_LIST_TITLE, aiLevelParts, aiListHead, aiListMarket, aiListMeta, aiListStaleBadge, aiNoLevelsText, aiPickName, aiPickPath,
  aiReasonRefs,
} from './aiList'
import './aiList.css'

// The AI list on the 今日名單 tab (#1146; UI_COPY_SPEC §10 AI 名單, DESIGN_SYSTEM §7): the latest list with its date, a
// warning badge when it is not today's, 「AI 推論，未經驗證」, then each pick's rank, method, levels and reasons. Only
// levels that passed the program's check are shown; the K-line card beside the list (from 1280px) or under the row
// draws them as AI lines (#1142 4/4 row 26).
export function AiListSection({ renderChart, wide = false }: { renderChart?: (pick: AiListPick) => ReactNode; wide?: boolean }) {
  const query = useQuery({ queryKey: ['ai-list', 'latest'], queryFn: () => getAiList() })
  return <AiListView data={query.data} loading={query.isLoading} error={query.error} renderChart={renderChart} wide={wide} />
}

function AiBadge() {
  return <Badge tone="accent" dot className="badge-compact ai-list-mark">{AI_LIST_MARK}</Badge>
}

function ReasonItem({ reason }: { reason: AiListReason }) {
  const { news, others } = aiReasonRefs(reason)
  return (
    <li className="ai-list-reason">
      <span>{reason.text}</span>
      {news.length > 0 && (
        <span className="ai-list-refs">
          {news.map((item) => <Link key={item.id} className="text-link" to={`/news/${item.id}`}>{item.label}</Link>)}
        </span>
      )}
      {others.length > 0 && <span className="ai-list-refs muted">依據 {others.join('、')}</span>}
    </li>
  )
}

function Reasons({ reasons, className }: { reasons: readonly AiListReason[]; className?: string }) {
  if (reasons.length === 0) return null
  return <ul className={cx('ai-list-reasons', className)}>{reasons.map((reason, index) => <ReasonItem key={index} reason={reason} />)}</ul>
}

// The levels (§7 entry/stop/target colours, mono prices, each label with its price unbroken), or the sentence instead.
function Levels({ pick }: { pick: AiListPick }) {
  const none = aiNoLevelsText(pick)
  if (none || !pick.levels) return <p className={cx('ai-list-no-levels', pick.expired && 'ai-list-expired')}>{none}</p>
  return (
    <p className="ai-list-levels">
      {aiLevelParts(pick.levels).map((part, index) => (
        <span key={part.label}>
          {index > 0 && '｜'}
          <span className="ai-list-level">{part.label} <b className={cx('ai-list-price', part.className)}>{part.value}</b></span>
        </span>
      ))}
    </p>
  )
}

type RowChart = { open: boolean; onToggle: () => void; content: ReactNode }

function PickRow({ pick, selected, onSelect, chart }: { pick: AiListPick; selected: boolean; onSelect?: () => void; chart?: RowChart }) {
  const chartId = `ai-list-chart-${pick.rank}`
  return (
    <li className={cx('ai-list-row', selected && 'ai-list-row-selected')} data-ai-rank={pick.rank} data-levels={pick.levels ? 'shown' : 'hidden'}>
      <p className="ai-list-row-title">
        {onSelect
          ? <button type="button" className="candidate-rank candidate-rank-button" aria-label={`第 ${pick.rank} 名，顯示走勢圖`} aria-pressed={selected} onClick={onSelect}>{pick.rank}</button>
          : chart
            ? <button type="button" className="candidate-rank candidate-rank-button" aria-label={chartToggleLabel(pick.rank, chart.open)} aria-expanded={chart.open} aria-controls={chartId} onClick={chart.onToggle}>{pick.rank}</button>
            : <span className="candidate-rank" aria-label={`第 ${pick.rank} 名`}>{pick.rank}</span>}{' '}
        <Link className="symbol-link ai-list-name" to={aiPickPath(pick)}><strong>{pick.symbol}</strong> {pick.name}</Link>{' '}
        <span className="ai-list-method">{pick.method_text}</span>
      </p>
      <Levels pick={pick} />
      {pick.corporate_action_text && <p className="ai-list-corporate">{pick.corporate_action_text}</p>}
      <Reasons reasons={pick.reasons} />
      {/* The conditions and the levels' basis folded (PR #1153 review 3: two picks on the first screen at 1280×800). */}
      {((pick.levels && pick.entry_condition) || pick.exit_conditions.length > 0 || pick.level_refs.length > 0) && (
        <details className="ai-list-more">
          <summary>{AI_LIST_MORE}</summary>
          {pick.levels && pick.entry_condition && <p className="ai-list-condition">{AI_LIST_ENTRY_CONDITION}：{pick.entry_condition}</p>}
          {pick.exit_conditions.length > 0 && <p className="ai-list-condition">{AI_LIST_EXIT}：{pick.exit_conditions.map((item) => item.text).join('；')}</p>}
          {pick.level_refs.length > 0 && (
            <div className="ai-list-level-refs">
              <p className="ai-list-condition">{AI_LIST_LEVEL_REFS}</p>
              <ul>{pick.level_refs.map((line) => <li key={line}>{line}</li>)}</ul>
            </div>
          )}
        </details>
      )}
      {chart && (
        <div className="ai-list-chart" id={chartId} hidden={!chart.open} role={chart.open ? 'region' : undefined} aria-label={chart.open ? `${aiPickName(pick)} 走勢圖` : undefined}>
          {chart.open && chart.content}
        </div>
      )}
    </li>
  )
}

// wide: from 1280px the picked stock's K-line card is beside the list (the first until another rank is pressed);
// below that a rank opens the card under its row, none at first (no chart mounts, no /bars is fetched).
export function AiPickList({ picks, renderChart, wide = false, initialChartRank = null }: { picks: AiListPick[]; renderChart?: (pick: AiListPick) => ReactNode; wide?: boolean; initialChartRank?: number | null }) {
  const [picked, setPicked] = useState<number | null>(null)
  const [chartRank, setChartRank] = useState<number | null>(initialChartRank)
  const lastWide = useRef(wide)
  useEffect(() => {
    if (lastWide.current === wide) return
    lastWide.current = wide
    setPicked(null)
    setChartRank(null)
  }, [wide])
  const terminal = !!renderChart && wide
  const selected = picks.find((pick) => pick.rank === picked) ?? picks[0]
  const list = (
    <ol className="ai-list-picks">
      {picks.map((pick) => (
        <PickRow key={pick.symbol} pick={pick} selected={terminal && pick === selected} onSelect={terminal ? () => setPicked(pick.rank) : undefined}
          chart={renderChart && !wide ? { open: chartRank === pick.rank, onToggle: () => setChartRank((current) => nextChartRank(current, pick.rank)), content: chartRank === pick.rank ? renderChart(pick) : null } : undefined} />
      ))}
    </ol>
  )
  if (!terminal || !selected) return list
  return (
    <div className="ai-list-terminal">
      <div className="ai-list-terminal-list">{list}</div>
      <aside className="ai-list-terminal-chart" aria-label={`${aiPickName(selected)} 走勢圖`} data-ai-chart-rank={selected.rank}>{renderChart(selected)}</aside>
    </div>
  )
}

export function AiListView({ data, loading = false, error = null, renderChart, wide = false, initialChartRank = null }: { data: AiListResponse | undefined; loading?: boolean; error?: unknown; renderChart?: (pick: AiListPick) => ReactNode; wide?: boolean; initialChartRank?: number | null }) {
  const done = data?.status === 'done'
  const stale = data ? aiListStaleBadge(data) : null
  const market = data ? aiListMarket(data) : null
  const head = data && done ? aiListHead(data) : null
  return (
    <section className="ai-inference ai-list" aria-labelledby="ai-list-title" data-ai-list-state={data?.status ?? (loading ? 'loading' : 'error')}>
      <div className="ai-list-head">
        <h2 id="ai-list-title">{AI_LIST_TITLE}</h2>
        {head && <span className="ai-list-date">{head}</span>}
        {stale && <Badge tone="warning" className="badge-compact ai-list-stale">{stale}</Badge>}
        <AiBadge />
      </div>
      {data?.failure && <p className="ai-list-failure" role="status">{data.failure.text}</p>}
      {!data
        ? <p className="ai-list-empty">{loading ? AI_LIST_LOADING : error ? AI_LIST_ERROR : AI_LIST_LOADING}</p>
        : !done
          ? (!data.failure && <p className="ai-list-empty">{data.missing_text ?? AI_LIST_MISSING}</p>)
          : (
            <>
              <p className="small-note ai-list-meta">{aiListMeta(data)}</p>
              {/* The market's reasons folded under its one-line summary (PR #1153 review 3: the first screen). */}
              {market && (
                <details className="ai-list-block ai-list-market" data-part="market">
                  <summary>{market}</summary>
                  <Reasons reasons={data.market?.reasons ?? []} />
                </details>
              )}
              {data.sectors.length > 0 && (
                <p className="ai-list-sectors" data-part="sectors">族群：{data.sectors.map((sector) => `${sector.name} ${sector.direction_text}`).join('、')}</p>
              )}
              {data.picks.length === 0
                ? <p className="ai-list-empty">{data.empty_text}</p>
                : <AiPickList picks={data.picks} renderChart={renderChart} wide={wide} initialChartRank={initialChartRank} />}
              {data.data_gaps.length > 0 && <p className="small-note ai-list-gaps">{AI_LIST_GAPS}：{data.data_gaps.join('；')}</p>}
              {data.input_gaps.length > 0 && <p className="small-note ai-list-gaps">{AI_LIST_INPUT_GAPS}：{data.input_gaps.join('；')}</p>}
            </>
          )}
    </section>
  )
}
