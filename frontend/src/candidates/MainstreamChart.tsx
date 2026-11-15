import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { getStockBars } from '../api'
import { StockBarsChart } from '../stock/StockBarsChart'
import type { MainstreamItem, StockBarsInterval } from '../types'

// The chart beside 主流族群前 20 (#769; DESIGN_SYSTEM §5 候選列表): the same stock-page K-line card as the today list's
// (today/CandidateChart), with no rule level lines: the list has no price levels. It shares the stock page's query key.
export function MainstreamChart({ item }: { item: Pick<MainstreamItem, 'instrument'> }) {
  const [interval, setInterval] = useState<StockBarsInterval>('day')
  const { exchange, symbol, name } = item.instrument
  const bars = useQuery({ queryKey: ['stock-bars', exchange, symbol, interval], queryFn: () => getStockBars(exchange, symbol, interval) })
  return (
    <StockBarsChart
      interval={interval}
      onIntervalChange={setInterval}
      data={bars.data}
      loading={bars.isLoading}
      error={bars.error}
      instrumentType={item.instrument.instrument_type}
      title={`${symbol} ${name}`}
      titleId="mainstream-chart-title"
    />
  )
}
