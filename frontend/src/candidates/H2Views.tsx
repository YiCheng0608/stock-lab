import type { ReactNode } from 'react'

import { getH2 } from '../api'
import { Badge, Card, DateBadge, EmptyState, Skeleton } from '../components/ui'
import type { H2Item, H2Response } from '../types'
import { formatDate } from './candidates'
import { H2_GAP_LEAD, h2Definition, h2GapText, h2State } from './h2'
import { H2_TITLE, type TodayListKind } from './mainstream'
import { RecentPicksList, RecentViewChips } from './RecentPicksViews'
import type { RecentView } from './recentPicks'
import { ScreenList, errorReason } from './ScreenList'

// 接近年高前 20 (the H2 list, #882; UI_COPY_SPEC §10 接近年高前 20): the today page's third list, laid out as
// 主流族群前 20 (ScreenList). The first line has no group part; the second is 「距一年高點」 and 「今日名單 #n」.

// /api/h2 only once the third list is open (as /api/mainstream, decision 6893166683).
export function h2QueryOptions(kind: TodayListKind, fetch: () => Promise<H2Response> = () => getH2()) {
  return { queryKey: ['h2', 'latest'] as const, queryFn: fetch, enabled: kind === 'h2' }
}

// 「距一年高點 -3.21%」 in the list's number type, no tone: it is a distance, not a change.
function GapLine({ item }: { item: H2Item }) {
  return <p className="mainstream-return h2-gap">{H2_GAP_LEAD} <span className="mainstream-return-value h2-gap-value">{h2GapText(item)}</span></p>
}

export function H2List({ items, listDate = null, todayDate = null, renderChart, wide = false, initialChartRank = null }: { items: H2Item[]; listDate?: string | null; todayDate?: string | null; renderChart?: (item: H2Item) => ReactNode; wide?: boolean; initialChartRank?: number | null }) {
  return (
    <ScreenList kind="h2" items={items} listDate={listDate} todayDate={todayDate} renderChart={renderChart} wide={wide} initialChartRank={initialChartRank}
      parts={(item) => ({ meta: null, line: <GapLine item={item} /> })} />
  )
}

// todayDate: the date of the today list the page shows (the latest); 「今日名單 #n」 links to it only on the same date.
// view: 「當天」 or 「近 60 日入選過」 (#1021, the page's ?view=recent); the chips show once the API has a stored list in
// the window.
export function H2Section({ data, loading, error, renderChart, wide = false, todayDate = null, view = 'today', onViewChange }: { data: H2Response | undefined; loading: boolean; error: unknown; renderChart?: (item: H2Item) => ReactNode; wide?: boolean; todayDate?: string | null; view?: RecentView; onViewChange?: (view: RecentView) => void }) {
  const state = data ? h2State(data) : null
  const recent = data?.status !== 'missing' && data?.recent_picks && data.recent_picks.days > 0 ? data.recent_picks : null
  const shown = recent ? view : 'today'
  return (
    <section className="candidates-section h2-section" aria-labelledby="h2-title">
      <div className="candidates-head">
        <h2 id="h2-title">{H2_TITLE}</h2>
        {data?.trading_date && (
          <span className="board-dates"><DateBadge date={formatDate(data.trading_date)} />{state?.kind === 'list' && <Badge>{state.items.length} 檔</Badge>}</span>
        )}
      </div>
      {data && state?.kind === 'list' && <p className="small-note mainstream-definition h2-definition">{h2Definition(data)}</p>}
      {recent && !loading && !error && <RecentViewChips view={shown} onChange={onViewChange ?? (() => undefined)} counts={{ today: state?.kind === 'list' ? state.items.length : 0, recent: recent.items.length }} />}
      {loading
        ? <Skeleton lines={4} label={`${H2_TITLE} 載入中…`} />
        : error
          ? <Card><EmptyState title="資料暫時無法載入" reason={errorReason(error)} /></Card>
          : !state || !data
            ? null
            : shown === 'recent' && recent
              ? <RecentPicksList kind="h2" picks={recent} />
              : state.kind === 'list'
                ? <H2List items={state.items} listDate={data.trading_date} todayDate={todayDate} renderChart={renderChart} wide={wide} />
                : <Card><EmptyState title={state.title} reason={state.text} /></Card>}
    </section>
  )
}
