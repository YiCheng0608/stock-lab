import type { ReactNode } from 'react'

import { Badge, DateBadge, Skeleton } from '../components/ui'
import { formatDay } from '../dates'
import { exchangeLabel } from '../presentation'
import type { CandidateMarket, StockBarRow, TradingHalt } from '../types'
import { formatPrice, formatSignedPercent, formatSignedPrice, sourcesLabel, stockQuote } from './stockBars'

// An official stop of trading on the page's day (Issue 582, UI_COPY_SPEC §8.2): why the close is older than the market.
export function tradingHaltLabel(halt: TradingHalt | null | undefined): string | null {
  if (!halt) return null
  const resume = formatDay(halt.resume_date)
  const reason = halt.reason_label || '官方公告'
  return resume ? `停止買賣中（${reason}，預計 ${resume} 恢復）` : `停止買賣中（${reason}）`
}

export { exchangeLabel }

// Page header: symbol, name, market, latest close (mono large), change in up/down color with explicit sign,
// data-date badge and source. Without a trusted value the price or change reads 「待核實」 (UI_COPY_SPEC §10.2).
export function StockHeader({
  symbol,
  name,
  exchange,
  typeLabel,
  dailyBars,
  latestChange,
  loading = false,
  instrumentType,
  halt,
  children,
}: {
  symbol: string
  name: string
  exchange: string
  typeLabel: string
  dailyBars: readonly StockBarRow[] | undefined
  latestChange?: CandidateMarket | null
  loading?: boolean
  instrumentType?: string | null
  halt?: TradingHalt | null
  children?: ReactNode
}) {
  return (
    <section className="card stock-header" aria-label={`${symbol} ${name}`}>
      <div className="stock-header-id">
        <span className="stock-header-symbol">{symbol}</span>
        <h1 className="stock-header-name">{name}</h1>
        <Badge>{exchangeLabel(exchange)}</Badge>
        <Badge>{typeLabel}</Badge>
      </div>
      {loading ? <Skeleton lines={2} className="stock-header-skeleton" label="最近收盤載入中…" /> : <StockQuoteLine bars={dailyBars ?? []} instrumentType={instrumentType} latestChange={latestChange} halt={halt} />}
      {children}
    </section>
  )
}

export function StockQuoteLine({ bars, instrumentType, latestChange, halt }: { bars: readonly StockBarRow[]; instrumentType?: string | null; latestChange?: CandidateMarket | null; halt?: TradingHalt | null }) {
  const quote = stockQuote(bars, instrumentType, latestChange)
  const haltLabel = tradingHaltLabel(halt)
  const change = quote.change == null
    ? quote.noChange ?? '漲跌待核實'
    : `${formatSignedPrice(quote.change, quote.digits)}（${formatSignedPercent(quote.changePct)}）`
  return (
    <div className="stock-header-quote">
      <div className="stock-header-price">
        <span className="stock-header-label">最近收盤（報價幣別元）</span>
        <strong className="stock-header-close">{formatPrice(quote.close, quote.digits)}</strong>
        <span className={`stock-header-change tone-${quote.tone}`} data-tone={quote.tone}>{change}</span>
      </div>
      <div className="stock-header-meta">
        <DateBadge date={quote.date} />
        <span>來源 {quote.date ? sourcesLabel(quote.sources) : '尚無已核對的價格來源'}</span>
        {haltLabel && <Badge tone="warning" className="stock-header-halt">{haltLabel}</Badge>}
      </div>
    </div>
  )
}
