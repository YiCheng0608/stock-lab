import type { ReactNode } from 'react'

import { Badge, DateBadge, Skeleton } from '../components/ui'
import type { StockBarRow } from '../types'
import { formatPrice, formatSignedPercent, formatSignedPrice, sourcesLabel, stockQuote } from './stockBars'

export function exchangeLabel(exchange: string | null | undefined): string {
  if (exchange === 'TWSE') return '上市'
  if (exchange === 'TPEx') return '上櫃'
  return '市場待核實'
}

// Page header: symbol, name, market, latest close (mono large), change in up/down color with explicit sign,
// data-date badge and source. Without a trusted value the price or change reads 「待核實」 (UI_COPY_SPEC §10.2).
export function StockHeader({
  symbol,
  name,
  exchange,
  typeLabel,
  dailyBars,
  loading = false,
  instrumentType,
  children,
}: {
  symbol: string
  name: string
  exchange: string
  typeLabel: string
  dailyBars: readonly StockBarRow[] | undefined
  loading?: boolean
  instrumentType?: string | null
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
      {loading ? <Skeleton lines={2} className="stock-header-skeleton" label="最近收盤載入中…" /> : <StockQuoteLine bars={dailyBars ?? []} instrumentType={instrumentType} />}
      {children}
    </section>
  )
}

export function StockQuoteLine({ bars, instrumentType }: { bars: readonly StockBarRow[]; instrumentType?: string | null }) {
  const quote = stockQuote(bars, instrumentType)
  const change = quote.change == null
    ? '漲跌待核實'
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
      </div>
    </div>
  )
}
