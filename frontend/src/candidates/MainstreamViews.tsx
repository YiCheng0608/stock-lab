import { useEffect, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'

import { getMainstream } from '../api'
import { Badge, Card, DateBadge, EmptyState, Skeleton, Tabs, cx, tabId, tabPanelId } from '../components/ui'
import type { CandidateItem, CandidatesResponse, MainstreamItem, MainstreamResponse } from '../types'
import '../styles/mainstream.css'
import { formatDate } from './candidates'
import { CandidatesSection } from './CandidateViews'
import { H2Section, h2QueryOptions } from './H2Views'
import { X4Section, x4QueryOptions } from './X4Views'
import {
  MAINSTREAM_TITLE,
  PICK_PARAM,
  TODAY_LISTS,
  mainstreamDefinition,
  mainstreamGroupsText,
  mainstreamReturnParts,
  mainstreamState,
  todayListKind,
  todayListSearch,
  type TodayListKind,
} from './mainstream'
import { ScreenList, errorReason, type ScreenItem } from './ScreenList'

// The today page's lists (#769, #882, #1019; DESIGN_SYSTEM §5 候選列表, UI_COPY_SPEC §10 主流族群前 20, 接近年高前 20 and
// 盈餘殖利率前 20): a four-tab switch 「今日名單｜主流族群前 20｜接近年高前 20｜盈餘殖利率前 20」 above the list, the same
// at every width. The address carries ?list=mainstream, ?list=h2 or ?list=x4, so a reload stays on it; without it the page shows 今日名單, whose rows, order
// and lines do not change (page_checks T5–T8, T13).

const LISTS_ID = 'today-list'

// The page imports the chart from here too, so App.tsx needs one import line (decision 6893166683).
export { MainstreamChart } from './MainstreamChart'

export type TodayListsProps = {
  today: { data: CandidatesResponse | undefined; loading: boolean; error: unknown }
  renderChart?: (item: CandidateItem) => ReactNode
  // The K-line card of 主流族群前 20, 接近年高前 20 and 盈餘殖利率前 20 (no rule level lines): it reads the stock only.
  renderMainstreamChart?: (item: ScreenItem) => ReactNode
  wide?: boolean
}

// /api/mainstream only once the second list is open (decision 6893166683): the today list's page requests nothing more.
export function mainstreamQueryOptions(kind: TodayListKind, fetch: () => Promise<MainstreamResponse> = () => getMainstream()) {
  return { queryKey: ['mainstream', 'latest'] as const, queryFn: fetch, enabled: kind === 'mainstream' }
}

// The tabs scroll sideways when they do not fit (390px, #1019): the selected one, also when opened from the address
// (?list=x4), is scrolled into the strip so it is never cut at the edge. Only the strip scrolls, not the page.
export function revealTab(tab: Element | null) {
  const strip = tab?.parentElement
  if (!tab || !strip || strip.scrollWidth <= strip.clientWidth) return
  const box = tab.getBoundingClientRect()
  const view = strip.getBoundingClientRect()
  if (box.right > view.right) strip.scrollLeft += box.right - view.right
  else if (box.left < view.left) strip.scrollLeft -= view.left - box.left
}

type StripLike = { scrollLeft: number; scrollWidth: number; clientWidth: number }

// Which sides of the strip have tabs scrolled out: they fade there (styles/mainstream.css), so the strip reads as
// scrollable without a scrollbar.
export function tabEdges(strip: StripLike): { left: boolean; right: boolean } {
  return { left: strip.scrollLeft > 0, right: strip.scrollLeft + strip.clientWidth < strip.scrollWidth - 1 }
}

function markEdges(strip: HTMLElement) {
  const edges = tabEdges(strip)
  strip.classList.toggle('tabs-more-left', edges.left)
  strip.classList.toggle('tabs-more-right', edges.right)
}

export function TodayListsSection({ today, renderChart, renderMainstreamChart, wide = false }: TodayListsProps) {
  const [search, setSearch] = useSearchParams()
  const kind = todayListKind(search)
  const mainstream = useQuery(mainstreamQueryOptions(kind))
  const h2 = useQuery(h2QueryOptions(kind))
  const x4 = useQuery(x4QueryOptions(kind))
  const change = (next: TodayListKind) => setSearch(todayListSearch(search, next))
  const todayDate = today.data?.trading_date ?? null
  useEffect(() => {
    const tab = document.getElementById(tabId(LISTS_ID, kind))
    revealTab(tab)
    const strip = tab?.parentElement
    if (!strip) return
    const update = () => markEdges(strip)
    update()
    strip.addEventListener('scroll', update, { passive: true })
    window.addEventListener('resize', update)
    return () => { strip.removeEventListener('scroll', update); window.removeEventListener('resize', update) }
  }, [kind])
  return (
    <div className="today-lists">
      <Tabs items={TODAY_LISTS} value={kind} onChange={change} label="名單" idPrefix={LISTS_ID} className="tabs-compact today-list-tabs" />
      <div id={tabPanelId(LISTS_ID, kind)} role="tabpanel" aria-labelledby={tabId(LISTS_ID, kind)}>
        {kind === 'today'
          ? <CandidatesSection data={today.data} loading={today.loading} error={today.error} renderChart={renderChart} wide={wide} pick={search.get(PICK_PARAM)} />
          : kind === 'mainstream'
            ? <MainstreamSection data={mainstream.data} loading={mainstream.isLoading} error={mainstream.error} renderChart={renderMainstreamChart} wide={wide} todayDate={todayDate} />
            : kind === 'h2'
              ? <H2Section data={h2.data} loading={h2.isLoading} error={h2.error} renderChart={renderMainstreamChart} wide={wide} todayDate={todayDate} />
              : <X4Section data={x4.data} loading={x4.isLoading} error={x4.error} renderChart={renderMainstreamChart} wide={wide} todayDate={todayDate} />}
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

// One stock (#769): who (rank, name, market · groups) on the first line, its W-session strength and 「今日名單 #n」 on the
// second, the sparkline under it, the close and change on the right (ScreenList). Below 1280px the rank button opens
// the row's K-line card, as on the today list.
export function MainstreamList({ items, days, listDate = null, todayDate = null, renderChart, wide = false, initialChartRank = null }: { items: MainstreamItem[]; days: number; listDate?: string | null; todayDate?: string | null; renderChart?: (item: MainstreamItem) => ReactNode; wide?: boolean; initialChartRank?: number | null }) {
  return (
    <ScreenList kind="mainstream" items={items} listDate={listDate} todayDate={todayDate} renderChart={renderChart} wide={wide} initialChartRank={initialChartRank}
      parts={(item) => ({ meta: mainstreamGroupsText(item), line: <ReturnLine item={item} days={days} /> })} />
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
