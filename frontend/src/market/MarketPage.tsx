import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'

import { ApiError, getDashboard, getStockBars } from '../api'
import { EmptyState, Skeleton } from '../components/ui'
import type { Dashboard, MarketOverview, StockBarsInterval } from '../types'
import { IndexTablePanel, MarketChartView, MarketOverviewPanel } from './MarketViews'
import { MARKET_PAGE_LEAD, indexRow, indexSearch, selectedIndex, type IndexSpec } from './marketOverview'

const notFound = (error: unknown) => error instanceof ApiError && error.status === 404

// The shared chart of the selected row, on the stock page's query key, so /stocks/TWSE/TAIEX and /market share a cache.
// A series whose instrument is not collected yet (404: TPEX before its first report, TX before its first collect, a US
// index before its first FRED read) is a chart without daily bars, not a load failure.
function MarketChart({ spec, overview, interval, onIntervalChange }: { spec: IndexSpec; overview: MarketOverview | undefined; interval: StockBarsInterval; onIntervalChange: (interval: StockBarsInterval) => void }) {
  const bars = useQuery({
    queryKey: ['stock-bars', spec.exchange, spec.symbol, interval],
    queryFn: () => getStockBars(spec.exchange, spec.symbol, interval),
    retry: (count, error) => !notFound(error) && count < 3,
  })
  const missing = notFound(bars.error)
  return <MarketChartView spec={spec} row={indexRow(overview, spec.key)} interval={interval} onIntervalChange={onIntervalChange} data={bars.data} loading={bars.isLoading} error={missing ? null : bars.error} />
}

// 大盤 (/market, Issue 549/561/564; PRODUCT_SPEC §2, DESIGN_SYSTEM §4): 大盤概況（with 加權指數與季線）→ 指數總表 → the
// shared daily K chart of the selected row (?index=, 加權指數 by default) → 大盤狀態 (Issue 546). Blocks without a source
// yet are not rendered (no placeholders or made-up data). The overview shares the dashboard query with the today page.
export function MarketPage() {
  const dashboard = useQuery<Dashboard>({ queryKey: ['dashboard'], queryFn: getDashboard })
  const [searchParams, setSearchParams] = useSearchParams()
  const [interval, setBarsInterval] = useState<StockBarsInterval>('day')
  const spec = selectedIndex(searchParams)
  // replace: switching rows is not a page of its own in the history, and a reload keeps the selection.
  const select = (key: string) => setSearchParams(indexSearch(searchParams, key), { replace: true })
  const overview = dashboard.data?.market_overview
  return (
    <div className="page market-page">
      <section className="page-title news-page-title">
        <h1>大盤</h1>
        <p>{MARKET_PAGE_LEAD}</p>
      </section>
      {dashboard.isLoading
        ? <Skeleton height={140} label="大盤概況載入中…" />
        : dashboard.error
          ? <section className="panel market-panel"><EmptyState title="資料暫時無法載入" reason={dashboard.error instanceof Error ? dashboard.error.message : '請稍後重新整理'} /></section>
          : <>
            <MarketOverviewPanel overview={overview} />
            <IndexTablePanel overview={overview} selected={spec.key} onSelect={select} />
          </>}
      <MarketChart spec={spec} overview={overview} interval={interval} onIntervalChange={setBarsInterval} />
    </div>
  )
}
