import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { ApiError, getDashboard, getStockBars } from '../api'
import { EmptyState, Skeleton } from '../components/ui'
import type { Dashboard, StockBarsInterval } from '../types'
import { MarketChartView, MarketOverviewPanel } from './MarketViews'
import { MARKET_CHARTS, type MarketChartSpec } from './marketOverview'

const notFound = (error: unknown) => error instanceof ApiError && error.status === 404

// One chart with its own period switch; the stock page's query key, so /stocks/TWSE/TAIEX and /market share a cache.
// A series whose instrument is not collected yet (404: TPEX before its first report, TX before its first collect) is a
// chart without daily bars, not a load failure.
function MarketChart({ spec }: { spec: MarketChartSpec }) {
  const [interval, setBarsInterval] = useState<StockBarsInterval>('day')
  const bars = useQuery({
    queryKey: ['stock-bars', spec.exchange, spec.symbol, interval],
    queryFn: () => getStockBars(spec.exchange, spec.symbol, interval),
    retry: (count, error) => !notFound(error) && count < 3,
  })
  const missing = notFound(bars.error)
  return <MarketChartView spec={spec} interval={interval} onIntervalChange={setBarsInterval} data={bars.data} loading={bars.isLoading} error={missing ? null : bars.error} />
}

// 大盤 (/market, Issue 549/552; PRODUCT_SPEC §2, DESIGN_SYSTEM §4): every market-level block in a fixed order —
// 大盤概況 → 加權指數日線 → 櫃買指數日線 → 台指期近月日線 → 美股（前一交易日, Issue 547）→ 大盤狀態 (Issue 546).
// Blocks without a source yet are not rendered (no placeholders or made-up data). The overview shares the dashboard
// query with the today page.
export function MarketPage() {
  const dashboard = useQuery<Dashboard>({ queryKey: ['dashboard'], queryFn: getDashboard })
  return (
    <div className="page market-page">
      <section className="page-title news-page-title">
        <h1>大盤</h1>
        <p>上市、上櫃的收盤概況，加權、櫃買指數與台指期的日 K。</p>
      </section>
      {dashboard.isLoading
        ? <Skeleton height={140} label="大盤概況載入中…" />
        : dashboard.error
          ? <section className="panel market-panel"><EmptyState title="資料暫時無法載入" reason={dashboard.error instanceof Error ? dashboard.error.message : '請稍後重新整理'} /></section>
          : <MarketOverviewPanel overview={dashboard.data?.market_overview} />}
      {MARKET_CHARTS.map((spec) => <MarketChart key={spec.key} spec={spec} />)}
    </div>
  )
}
