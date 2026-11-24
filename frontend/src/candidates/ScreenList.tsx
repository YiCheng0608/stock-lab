import { useEffect, useRef, useState } from 'react'
import type { MouseEvent, ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { cx } from '../components/ui'
import type { CandidateMarket, CandidateRecentCloses, MainstreamTodayList } from '../types'
import {
  candidateChange,
  chartToggleLabel,
  exchangeLabel,
  formatCandidateClose,
  nextChartRank,
  rowClickToggles,
  stockPath,
} from './candidates'
import { Sparkline } from './CandidateViews'
import { todayListMark } from './mainstream'

// The rows of the today page's lists without price levels (主流族群前 20 #769, 接近年高前 20 #882, 盈餘殖利率前 20 #1019; DESIGN_SYSTEM §5
// 候選列表): each the rank, the stock and its market, a list's own line with 「今日名單 #n」, the sparkline and the close
// with its change on the right; the K-line card beside the list from 1280px, under the row below that. No entry
// sentence, price ladder, RR, total score or AI button. The rows carry .mainstream-row, whose layout both lists share
// (styles/mainstream.css), and their own class for what differs.

export type ScreenItem = {
  rank: number
  instrument: { id: number; exchange: string; symbol: string; name: string; instrument_type: string }
  market: CandidateMarket
  recent_closes: CandidateRecentCloses
  today_list: MainstreamTodayList | null
}

export type ScreenKind = 'mainstream' | 'h2' | 'x4'

type RowChart = { open: boolean; onToggle: () => void; content: ReactNode }

type RowParts = { meta: string | null; line: ReactNode }

function ScreenRow({ kind, item, parts, listDate, todayDate, selected, onSelect, chart }: { kind: ScreenKind; item: ScreenItem; parts: RowParts; listDate: string | null; todayDate: string | null; selected: boolean; onSelect?: () => void; chart?: RowChart }) {
  const { instrument } = item
  const change = candidateChange(item.market)
  const mark = todayListMark(item, listDate, todayDate)
  const chartId = `${kind}-chart-${item.rank}`
  const meta = parts.meta ? `${exchangeLabel(instrument.exchange)} · ${parts.meta}` : exchangeLabel(instrument.exchange)
  const onRowClick = chart
    ? (event: MouseEvent<HTMLDivElement>) => {
      const selection = typeof window === 'undefined' ? '' : window.getSelection()?.toString() ?? ''
      if (rowClickToggles(event.target instanceof Element ? event.target : null, selection)) chart.onToggle()
    }
    : undefined
  return (
    <li className={cx('candidate-row', 'mainstream-row', kind !== 'mainstream' && `${kind}-row`, selected && 'candidate-row-selected', chart && 'candidate-row-chartable', chart?.open && 'candidate-row-charted')} {...{ [`data-${kind}-rank`]: item.rank }}>
      <div className="candidate-row-main" onClick={onRowClick}>
        <div className="candidate-row-body">
          {/* One line of inline runs, like the today list's title: 「#1 2330 台積電 上市 · 半導體、AI 伺服器」. */}
          <p className="candidate-row-title">
            {onSelect
              ? <button type="button" className="candidate-rank candidate-rank-button" aria-label={`第 ${item.rank} 名，顯示走勢圖`} aria-pressed={selected} onClick={onSelect}>#{item.rank}</button>
              : chart
                ? <button type="button" className="candidate-rank candidate-rank-button candidate-chart-toggle" aria-label={chartToggleLabel(item.rank, chart.open)} aria-expanded={chart.open} aria-controls={chartId} onClick={chart.onToggle}>#{item.rank}</button>
                : <span className="candidate-rank" aria-label={`第 ${item.rank} 名`}>#{item.rank}</span>}{' '}
            <Link className="symbol-link candidate-row-name" to={stockPath(item)}><strong>{instrument.symbol}</strong> {instrument.name}</Link>{' '}
            <span className="candidate-row-meta" title={parts.meta ?? undefined}>{meta}</span>
          </p>
          <div className="mainstream-row-line">
            {parts.line}
            {mark?.link && <Link className="badge badge-compact mainstream-today-mark" to={mark.link} data-today-rank={item.today_list?.rank}>{mark.text}</Link>}
            {mark && !mark.link && <span className="badge badge-compact mainstream-today-mark mainstream-today-mark-other" data-today-rank={item.today_list?.rank}>{mark.text}</span>}
          </div>
          <div className="candidate-row-figures mainstream-row-figures"><Sparkline item={item} /></div>
        </div>
        <dl className="candidate-row-nums">
          <div className="candidate-row-close">
            <dt>收盤（元）</dt>
            <dd><div>{formatCandidateClose(item.market)}</div><div className={cx('candidate-change', change.tone && `tone-${change.tone}`)}>{change.text}</div></dd>
          </div>
        </dl>
      </div>
      {chart && (
        <div className="candidate-chart" id={chartId} hidden={!chart.open} role={chart.open ? 'region' : undefined}
          aria-label={chart.open ? `${instrument.symbol} ${instrument.name} 走勢圖` : undefined}>
          {chart.open && chart.content}
        </div>
      )}
    </li>
  )
}

// The rows, and from 1280px the picked stock's K-line card on the right (盤後終端, the today list's layout): the first
// until another rank is pressed. Below that a row opens its own card, none at first (#665: no chart mounts, no /bars).
// listDate / todayDate: the list's date and the today list's the page shows; 「今日名單 #n」 links only on the same date.
export function ScreenList<T extends ScreenItem>({ kind, items, parts, listDate = null, todayDate = null, renderChart, wide = false, initialChartRank = null }: { kind: ScreenKind; items: T[]; parts: (item: T) => RowParts; listDate?: string | null; todayDate?: string | null; renderChart?: (item: T) => ReactNode; wide?: boolean; initialChartRank?: number | null }) {
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
  const selected = items.find((item) => item.rank === picked) ?? items[0]
  const list = (
    <ol className={cx('candidate-list', `${kind}-list`)}>
      {items.map((item) => (
        <ScreenRow key={item.instrument.exchange + item.instrument.symbol} kind={kind} item={item} parts={parts(item)} listDate={listDate} todayDate={todayDate}
          selected={terminal && item === selected} onSelect={terminal ? () => setPicked(item.rank) : undefined}
          chart={renderChart && !wide ? { open: chartRank === item.rank, onToggle: () => setChartRank((current) => nextChartRank(current, item.rank)), content: chartRank === item.rank ? renderChart(item) : null } : undefined} />
      ))}
    </ol>
  )
  if (!terminal || !selected) return list
  return (
    <div className="candidates-terminal">
      <div className="candidates-terminal-list">{list}</div>
      <aside className="candidates-terminal-chart" aria-label={`${selected.instrument.symbol} ${selected.instrument.name} 走勢圖`} data-chart-rank={selected.rank}>{renderChart(selected)}</aside>
    </div>
  )
}

// A failed load's reason (the today list writes the same): the API's message, else a hint to reload.
export function errorReason(error: unknown): string {
  return error instanceof Error ? error.message : '請稍後重新整理'
}
