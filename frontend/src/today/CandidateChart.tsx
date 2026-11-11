import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { getStockBars } from '../api'
import { candidateChartLevels } from '../candidates/candidates'
import { StockBarsChart } from '../stock/StockBarsChart'
import type { CandidateItem, StockBarsInterval } from '../types'

// The chart beside the today list (DESIGN_SYSTEM §5 候選列表): the stock page's K-line card for the picked candidate,
// with its rule levels drawn. It shares the stock page's query key, so opening the stock page afterwards reuses the bars.
export function CandidateChart({ item }: { item: CandidateItem }) {
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
      titleId="candidate-chart-title"
      levels={candidateChartLevels(item.levels)}
    />
  )
}
