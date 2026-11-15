import { useEffect, useRef, useState } from 'react'
import type { MouseEvent, ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'

import { getMainstream } from '../api'
import { Badge, Card, DateBadge, EmptyState, Skeleton, Tabs, cx, tabId, tabPanelId } from '../components/ui'
import type { CandidateItem, CandidatesResponse, MainstreamItem, MainstreamResponse } from '../types'
import '../styles/mainstream.css'
import {
  candidateChange,
  chartToggleLabel,
  exchangeLabel,
  formatCandidateClose,
  formatDate,
  nextChartRank,
  rowClickToggles,
  stockPath,
} from './candidates'
import { CandidatesSection, Sparkline } from './CandidateViews'
import {
  MAINSTREAM_TITLE,
  PICK_PARAM,
  TODAY_LISTS,
  mainstreamDefinition,
  mainstreamGroupsText,
  mainstreamReturnParts,
  mainstreamState,
  todayListKind,
  todayListMark,
  todayListSearch,
  type TodayListKind,
  type TodayListMarkView,
} from './mainstream'

// The today page's two lists (#769; DESIGN_SYSTEM §5 候選列表, UI_COPY_SPEC §10 主流族群前 20): a two-tab switch
// 「今日名單｜主流族群前 20」 above the list, the same at every width. The address carries ?list=mainstream, so a reload
// stays on it; without it the page shows 今日名單, whose rows, order and lines do not change (page_checks T5–T8, T13).

const LISTS_ID = 'today-list'

// The page imports the chart from here too, so App.tsx needs one import line (decision 6893166683).
export { MainstreamChart } from './MainstreamChart'

function errorReason(error: unknown): string {
  return error instanceof Error ? error.message : '請稍後重新整理'
}

export type TodayListsProps = {
  today: { data: CandidatesResponse | undefined; loading: boolean; error: unknown }
  renderChart?: (item: CandidateItem) => ReactNode
  renderMainstreamChart?: (item: MainstreamItem) => ReactNode
  wide?: boolean
}

// /api/mainstream only once the second list is open (decision 6893166683): the today list's page requests nothing more.
export function mainstreamQueryOptions(kind: TodayListKind, fetch: () => Promise<MainstreamResponse> = () => getMainstream()) {
  return { queryKey: ['mainstream', 'latest'] as const, queryFn: fetch, enabled: kind === 'mainstream' }
}

export function TodayListsSection({ today, renderChart, renderMainstreamChart, wide = false }: TodayListsProps) {
  const [search, setSearch] = useSearchParams()
  const kind = todayListKind(search)
  const mainstream = useQuery(mainstreamQueryOptions(kind))
  const change = (next: TodayListKind) => setSearch(todayListSearch(search, next))
  return (
    <div className="today-lists">
      <Tabs items={TODAY_LISTS} value={kind} onChange={change} label="名單" idPrefix={LISTS_ID} className="tabs-compact today-list-tabs" />
      <div id={tabPanelId(LISTS_ID, kind)} role="tabpanel" aria-labelledby={tabId(LISTS_ID, kind)}>
        {kind === 'today'
          ? <CandidatesSection data={today.data} loading={today.loading} error={today.error} renderChart={renderChart} wide={wide} pick={search.get(PICK_PARAM)} />
          : <MainstreamSection data={mainstream.data} loading={mainstream.isLoading} error={mainstream.error} renderChart={renderMainstreamChart} wide={wide} todayDate={today.data?.trading_date ?? null} />}
      </div>
    </div>
  )
}

// 「近 240 日 +45.67%（較加權 +12.34%）」: the value red up and green down, the excess in the muted text.
function ReturnLine({ item, days }: { item: MainstreamItem; days: number }) {
  const { lead, value, excess } = mainstreamReturnParts(item, days)
  return (
    <p className="mainstream-return">
      {lead} <span className={cx('mainstream-return-value', value.tone && `tone-${value.tone}`)}>{value.text}</span>
      <span className="mainstream-return-excess">（較加權 {excess.text}）</span>
    </p>
  )
}

type RowChart = { open: boolean; onToggle: () => void; content: ReactNode }

// One stock (#769): who (rank, name, market · groups) on the first line, its W-session strength and 「今日名單 #n」 on the
// second, the sparkline under it, the close and change on the right. No entry sentence, price ladder, RR or total
// score: the list has no price levels. Below 1280px the rank button opens the row's K-line card, as on the today list.
function MainstreamRow({ item, days, mark, selected, onSelect, chart }: { item: MainstreamItem; days: number; mark: TodayListMarkView | null; selected: boolean; onSelect?: () => void; chart?: RowChart }) {
  const { instrument } = item
  const change = candidateChange(item.market)
  const groups = mainstreamGroupsText(item)
  const chartId = `mainstream-chart-${item.rank}`
  const onRowClick = chart
    ? (event: MouseEvent<HTMLDivElement>) => {
      const selection = typeof window === 'undefined' ? '' : window.getSelection()?.toString() ?? ''
      if (rowClickToggles(event.target instanceof Element ? event.target : null, selection)) chart.onToggle()
    }
    : undefined
  return (
    <li className={cx('candidate-row', 'mainstream-row', selected && 'candidate-row-selected', chart && 'candidate-row-chartable', chart?.open && 'candidate-row-charted')} data-mainstream-rank={item.rank}>
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
            <span className="candidate-row-meta" title={groups}>{exchangeLabel(instrument.exchange)} · {groups}</span>
          </p>
          <div className="mainstream-row-line">
            <ReturnLine item={item} days={days} />
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
export function MainstreamList({ items, days, listDate = null, todayDate = null, renderChart, wide = false, initialChartRank = null }: { items: MainstreamItem[]; days: number; listDate?: string | null; todayDate?: string | null; renderChart?: (item: MainstreamItem) => ReactNode; wide?: boolean; initialChartRank?: number | null }) {
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
    <ol className="candidate-list mainstream-list">
      {items.map((item) => (
        <MainstreamRow key={item.instrument.exchange + item.instrument.symbol} item={item} days={days} mark={todayListMark(item, listDate, todayDate)}
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

// todayDate: the date of the today list the page shows (the latest); 「今日名單 #n」 links to it only on the same date.
export function MainstreamSection({ data, loading, error, renderChart, wide = false, todayDate = null }: { data: MainstreamResponse | undefined; loading: boolean; error: unknown; renderChart?: (item: MainstreamItem) => ReactNode; wide?: boolean; todayDate?: string | null }) {
  const state = data ? mainstreamState(data) : null
  return (
    <section className="candidates-section mainstream-section" aria-labelledby="mainstream-title">
      {/* One head line like the today list's: title, the data date and the count; the definition on the next line. */}
      <div className="candidates-head">
        <h2 id="mainstream-title">{MAINSTREAM_TITLE}</h2>
        {data?.trading_date && (
          <span className="board-dates"><DateBadge date={formatDate(data.trading_date)} />{state?.kind === 'list' && <Badge>{state.items.length} 檔</Badge>}</span>
        )}
      </div>
      {data && state?.kind === 'list' && <p className="small-note mainstream-definition">{mainstreamDefinition(data)}</p>}
      {loading
        ? <Skeleton lines={4} label="主流族群前 20 載入中…" />
        : error
          ? <Card><EmptyState title="資料暫時無法載入" reason={errorReason(error)} /></Card>
          : !state || !data
            ? null
            : state.kind === 'list'
              ? <MainstreamList items={state.items} days={data.window} listDate={data.trading_date} todayDate={todayDate} renderChart={renderChart} wide={wide} />
              : <Card><EmptyState title={state.title} reason={state.text} /></Card>}
    </section>
  )
}
