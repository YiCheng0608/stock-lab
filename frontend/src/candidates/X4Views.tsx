import { Fragment, type ReactNode } from 'react'

import { getX4 } from '../api'
import { Badge, Card, DateBadge, EmptyState, Skeleton } from '../components/ui'
import type { X4Item, X4Response } from '../types'
import { formatDate } from './candidates'
import { X4_TITLE, type TodayListKind } from './mainstream'
import { ScreenList, errorReason } from './ScreenList'
import { X4_WATCH_BADGE, x4Definition, x4LineParts, x4State } from './x4'

// 盈餘殖利率前 20 (the X4 list, #1019; UI_COPY_SPEC §10 盈餘殖利率前 20): the today page's fourth list, laid out as
// 接近年高前 20 (ScreenList). The head ends in the warning badge 「前瞻觀察（未通過驗證）」, on this list's head only
// (not on its tab); the second line is the yield, the revenue growth and the quarter's EPS, then 「今日名單 #n」.

// /api/strategy-lists/x4 only once the fourth list is open (as /api/h2, decision 6893166683).
export function x4QueryOptions(kind: TodayListKind, fetch: () => Promise<X4Response> = () => getX4()) {
  return { queryKey: ['x4', 'latest'] as const, queryFn: fetch, enabled: kind === 'x4' }
}

// 「盈餘殖利率 12.34% · 營收年增（10 月）+25.10% · 2026Q3 EPS 3.21（去年同季 2.10）」 in the list's number type, no tone:
// none of them is a price change. Each part is one unbroken run ending in its 「 ·」, so a narrow row wraps after a
// separator, never before one.
function FiguresLine({ item }: { item: X4Item }) {
  return (
    <p className="mainstream-return x4-figures">
      {x4LineParts(item).map((part, index, parts) => (
        <Fragment key={index}>
          {index > 0 && ' '}
          <span className="x4-figure">{part.lead}<span className="mainstream-return-value x4-figure-value">{part.value}</span>{part.note && <span className="mainstream-return-excess">{part.note}</span>}{index < parts.length - 1 && ' ·'}</span>
        </Fragment>
      ))}
    </p>
  )
}

export function X4List({ items, listDate = null, todayDate = null, renderChart, wide = false, initialChartRank = null }: { items: X4Item[]; listDate?: string | null; todayDate?: string | null; renderChart?: (item: X4Item) => ReactNode; wide?: boolean; initialChartRank?: number | null }) {
  return (
    <ScreenList kind="x4" items={items} listDate={listDate} todayDate={todayDate} renderChart={renderChart} wide={wide} initialChartRank={initialChartRank}
      parts={(item) => ({ meta: null, line: <FiguresLine item={item} /> })} />
  )
}

// todayDate: the date of the today list the page shows (the latest); 「今日名單 #n」 links to it only on the same date.
export function X4Section({ data, loading, error, renderChart, wide = false, todayDate = null }: { data: X4Response | undefined; loading: boolean; error: unknown; renderChart?: (item: X4Item) => ReactNode; wide?: boolean; todayDate?: string | null }) {
  const state = data ? x4State(data) : null
  return (
    <section className="candidates-section x4-section" aria-labelledby="x4-title">
      <div className="candidates-head">
        <h2 id="x4-title">{X4_TITLE}</h2>
        <span className="board-dates">
          {data?.trading_date && <DateBadge date={formatDate(data.trading_date)} />}
          {state?.kind === 'list' && <Badge>{state.items.length} 檔</Badge>}
          <Badge tone="warning" className="x4-watch-badge">{X4_WATCH_BADGE}</Badge>
        </span>
      </div>
      {data && state?.kind === 'list' && <p className="small-note mainstream-definition x4-definition">{x4Definition(data)}</p>}
      {loading
        ? <Skeleton lines={4} label={`${X4_TITLE} 載入中…`} />
        : error
          ? <Card><EmptyState title="資料暫時無法載入" reason={errorReason(error)} /></Card>
          : !state || !data
            ? null
            : state.kind === 'list'
              ? <X4List items={state.items} listDate={data.trading_date} todayDate={todayDate} renderChart={renderChart} wide={wide} />
              : <Card><EmptyState title={state.title} reason={state.text} /></Card>}
    </section>
  )
}
