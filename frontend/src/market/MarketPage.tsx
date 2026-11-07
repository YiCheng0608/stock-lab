import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { getDashboard, getStockBars } from '../api'
import { EmptyState, Skeleton } from '../components/ui'
import type { Dashboard, StockBarsInterval } from '../types'
import { IndexChartPanel, MarketOverviewPanel } from './MarketViews'
import { TAIEX, TAIEX_BARS_LIMIT } from './marketOverview'

// 大盤 (/market, Issue 549; PRODUCT_SPEC §2, DESIGN_SYSTEM §4): every market-level block in a fixed order —
// 大盤概況 → 加權指數日線 → 美股（前一交易日, Issue 547）→ 大盤狀態 (Issue 546). Blocks without a source yet are not
// rendered (no placeholders or made-up data). The overview shares the dashboard query with the today page.
export function MarketPage() {
  const dashboard = useQuery<Dashboard>({ queryKey: ['dashboard'], queryFn: getDashboard })
  const [interval, setBarsInterval] = useState<StockBarsInterval>('day')
  const bars = useQuery({
    queryKey: ['stock-bars', TAIEX.exchange, TAIEX.symbol, interval, TAIEX_BARS_LIMIT],
    queryFn: () => getStockBars(TAIEX.exchange, TAIEX.symbol, interval, TAIEX_BARS_LIMIT),
  })
  return (
    <div className="page market-page">
      <section className="page-title news-page-title">
        <h1>大盤</h1>
        <p>上市、上櫃的收盤概況與加權指數走勢。</p>
      </section>
      {dashboard.isLoading
        ? <Skeleton height={140} label="大盤概況載入中…" />
        : dashboard.error
          ? <section className="panel market-panel"><EmptyState title="資料暫時無法載入" reason={dashboard.error instanceof Error ? dashboard.error.message : '請稍後重新整理'} /></section>
          : <MarketOverviewPanel overview={dashboard.data?.market_overview} />}
      <IndexChartPanel interval={interval} onIntervalChange={setBarsInterval} data={bars.data} loading={bars.isLoading} error={bars.error} />
    </div>
  )
}
