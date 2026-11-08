import { useState, type ReactNode } from 'react'

import { DateBadge, cx } from '../components/ui'
import type { ForeignIndex, MarketOverview, MarketOverviewExchange, StockBarsInterval, StockBarsResponse, TaiexMa60 } from '../types'
import { formatFixed } from '../units'
import { isFiniteNumber } from '../stock/stockBars'
import { StockBarsChart } from '../stock/StockBarsChart'
import {
  EXCHANGES,
  FRED_ATTRIBUTION,
  MA60_LABEL,
  SHORT_SCOPE_LABELS,
  TAIFEX_ATTRIBUTION,
  TX_ROLL_NOTE,
  US_INDEXES,
  US_SECTION_TITLE,
  available,
  changeTone,
  collectedSinceText,
  dash,
  foreignAvailable,
  foreignDateText,
  foreignIndex,
  foreignLatestDate,
  foreignMissingText,
  foreignNotes,
  futuresLatestText,
  ma60MissingText,
  ma60PositionParts,
  ma60SegmentsText,
  marketOverviewNotes,
  missingText,
  signedPercent,
  usChartSpec,
  type ExchangeSpec,
  type MarketChartSpec,
  type UsIndexSpec,
} from './marketOverview'

// The market page blocks (/market, Issue 549/552/547): 大盤概況, the three daily K charts and 美股（前一交易日）, in the
// order DESIGN_SYSTEM §4 fixes.
// Copy and units follow UI_COPY_SPEC §11.

function IndexWidget({ spec, row }: { spec: ExchangeSpec; row: MarketOverviewExchange | null }) {
  const index = row?.index
  return (
    <div className="market-widget market-index" data-exchange={spec.exchange}>
      <div className="market-widget-head"><span className="market-widget-label">{spec.index}</span><span className="market-widget-unit">點</span></div>
      {index ? <>
        <div className="market-widget-value">{dash(index.close, 2)}</div>
        <div className={cx('market-widget-change', changeTone(index.change))}>{isFiniteNumber(index.change) ? formatFixed(index.change, 2, true) : '—'}（{signedPercent(index.change_pct)}）</div>
      </> : <div className="market-widget-empty">{missingText(spec)}</div>}
    </div>
  )
}

// Turnover is stored in 元 and shown in 億元 with two decimals, followed by its short scope.
function turnoverText(row: MarketOverviewExchange): ReactNode {
  const { value, scope, scope_label: scopeLabel } = row.turnover ?? { value: null, scope: null, scope_label: null }
  const short = (scope ? SHORT_SCOPE_LABELS[scope] : undefined) ?? scopeLabel
  return <>{isFiniteNumber(value) ? formatFixed(value / 1e8, 2) : '—'}{short && <> <span className="market-row-scope">{short}</span></>}</>
}

function breadthText(row: MarketOverviewExchange): string {
  const breadth = row.breadth
  if (!breadth) return '—'
  const limits = breadth.limit_up == null && breadth.limit_down == null ? '' : `（${dash(breadth.limit_up)}／${dash(breadth.limit_down)}）`
  return `上漲 ${dash(breadth.advancers)} · 下跌 ${dash(breadth.decliners)} · 平盤 ${dash(breadth.unchanged)}${limits}`
}

function DualWidget({ className, label, unit, overview, value }: { className: string; label: string; unit: string; overview: MarketOverview | undefined; value: (row: MarketOverviewExchange) => ReactNode }) {
  return (
    <div className={cx('market-widget market-widget-dual', className)}>
      <div className="market-widget-head"><span className="market-widget-label">{label}</span><span className="market-widget-unit">{unit}</span></div>
      {EXCHANGES.map((spec) => {
        const row = available(overview, spec.exchange)
        return row
          ? <div key={spec.exchange} className="market-row" data-exchange={spec.exchange}><span className="market-row-label">{spec.label}</span> {value(row)}</div>
          : <div key={spec.exchange} className="market-row market-row-empty" data-exchange={spec.exchange}>{missingText(spec)}</div>
      })}
    </div>
  )
}

// One bar of four widgets: the two indexes, turnover and breadth (DESIGN_SYSTEM §5 market-widget, dual-row variant).
export function MarketOverviewView({ overview }: { overview: MarketOverview | undefined }) {
  return (
    <div className="market-overview-grid">
      {EXCHANGES.map((spec) => <IndexWidget key={spec.exchange} spec={spec} row={available(overview, spec.exchange)} />)}
      <DualWidget className="market-turnover" label="成交金額" unit="億元" overview={overview} value={turnoverText} />
      <DualWidget className="market-breadth" label="漲跌家數（股票）" unit="括號為漲停／跌停" overview={overview} value={breadthText} />
    </div>
  )
}

// 加權指數與季線 (Issue 561): one neutral strip under the four widgets — the close, its date, the position against MA60 and
// the latest runs above it; without a position only the reason. No up/down colors: background, not a signal.
export function TaiexMa60View({ item }: { item: TaiexMa60 | undefined }) {
  const missing = ma60MissingText(item)
  const parts = item ? ma60PositionParts(item) : null
  const segments = item ? ma60SegmentsText(item) : null
  return (
    <div className="market-ma60" data-status={item?.status ?? 'missing'}>
      <div className="market-widget-head"><span className="market-widget-label">{MA60_LABEL}</span><span className="market-widget-unit">點</span></div>
      {parts
        ? <div className="market-ma60-line">{parts.lead}<strong className="market-ma60-position">{parts.position}</strong>{parts.ma60}</div>
        : <div className="market-widget-empty market-ma60-empty">{missing}</div>}
      {segments && <div className="market-ma60-segments">{segments}</div>}
    </div>
  )
}

export function MarketOverviewPanel({ overview }: { overview: MarketOverview | undefined }) {
  return (
    <section className="panel market-panel market-overview" aria-labelledby="market-overview-title">
      <div className="panel-head">
        <h2 id="market-overview-title">大盤概況</h2>
        <DateBadge date={overview?.trading_date ?? null} />
        <details className="data-explanation">
          <summary>資料說明</summary>
          {marketOverviewNotes(overview).map((line) => <div key={line}>{line}</div>)}
        </details>
      </div>
      <MarketOverviewView overview={overview} />
      <TaiexMa60View item={overview?.taiex_ma60} />
    </section>
  )
}

// The TX chart's lines under the K line: the latest contract month, open interest and settlement price, when the
// history starts, the roll rule and the open-data attribution (Issue 552; UI_COPY_SPEC §11).
function FuturesFooter({ data }: { data: StockBarsResponse | undefined }) {
  const latest = futuresLatestText(data)
  const since = collectedSinceText(data)
  return (
    <div className="market-chart-footer" data-exchange="TAIFEX">
      {latest && <p className="market-chart-contract">{latest}</p>}
      <p>{since ? `${since}；` : ''}{TX_ROLL_NOTE}</p>
      <p>{TAIFEX_ATTRIBUTION}</p>
    </div>
  )
}

// Each chart is the stock page's StockBarsChart (same period switch, indicators and empty states), titled for the
// series (DESIGN_SYSTEM §4 大盤頁, Issue 549/552).
export function MarketChartView({ spec, interval, onIntervalChange, data, loading, error, footer }: {
  spec: MarketChartSpec
  interval: StockBarsInterval
  onIntervalChange: (interval: StockBarsInterval) => void
  data: StockBarsResponse | undefined
  loading: boolean
  error: unknown
  // Lines under the chart other than the TX ones (the US indexes' FRED attribution, Issue 547).
  footer?: ReactNode
}) {
  return (
    <div className="market-chart" data-chart={spec.key}>
      <StockBarsChart interval={interval} onIntervalChange={onIntervalChange} data={data} loading={loading} error={error}
        instrumentType={spec.instrumentType} title={spec.title} titleId={spec.titleId}
        footer={spec.instrumentType === 'futures' ? <FuturesFooter data={data} /> : footer} />
    </div>
  )
}

// ---- 美股（前一交易日）, Issue 547 --------------------------------------------------------------------

// One index: close (點, two decimals), change and percent in the 台股 colors, then its data date with 非最新 / 美股休市.
function UsIndexWidget({ spec, item }: { spec: UsIndexSpec; item: ForeignIndex | null }) {
  return (
    <div className="market-widget market-index market-us-index" data-symbol={spec.symbol}>
      <div className="market-widget-head"><span className="market-widget-label">{spec.name}</span><span className="market-widget-unit">點</span></div>
      {foreignAvailable(item) ? <>
        <div className="market-widget-value">{dash(item.close, 2)}</div>
        <div className={cx('market-widget-change', changeTone(item.change))}>{isFiniteNumber(item.change) ? formatFixed(item.change, 2, true) : '—'}（{signedPercent(item.change_pct)}）</div>
        <UsIndexDate item={item} />
      </> : <div className="market-widget-empty">{foreignMissingText(item)}</div>}
    </div>
  )
}

function UsIndexDate({ item }: { item: ForeignIndex & { trading_date: string } }) {
  const { date, flag } = foreignDateText(item)
  return <div className="market-us-date">{date}{flag && <> <span className={cx('market-us-flag', item.freshness === 'stale' && 'market-us-stale')}>{flag}</span></>}</div>
}

// The FRED attribution and the series' copyright notice (FRED terms: keep the notices intact).
export function UsChartFooter({ item }: { item: ForeignIndex | null }) {
  return (
    <div className="market-chart-footer" data-exchange="US">
      <p>{FRED_ATTRIBUTION}</p>
      {item?.source?.copyright && <p>{item.source.copyright}</p>}
    </div>
  )
}

// A chart is mounted only once its row is opened, so the page does not load four more bar series up front.
function UsChartDetails({ spec, item, chart }: { spec: UsIndexSpec; item: ForeignIndex | null; chart: (spec: MarketChartSpec, footer: ReactNode) => ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <details className="details market-us-chart" data-symbol={spec.symbol} onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}>
      <summary>{spec.name} 日 K 與指標</summary>
      {open && chart(usChartSpec(spec), <UsChartFooter item={item} />)}
    </details>
  )
}

export function UsIndexPanel({ overview, chart }: { overview: MarketOverview | undefined; chart: (spec: MarketChartSpec, footer: ReactNode) => ReactNode }) {
  return (
    <section className="panel market-panel market-overview market-us" aria-labelledby="market-us-title">
      <div className="panel-head">
        <h2 id="market-us-title">{US_SECTION_TITLE}</h2>
        <DateBadge date={foreignLatestDate(overview)} />
        <details className="data-explanation">
          <summary>資料說明</summary>
          {foreignNotes(overview).map((line) => <div key={line}>{line}</div>)}
        </details>
      </div>
      <div className="market-overview-grid market-us-grid">
        {US_INDEXES.map((spec) => <UsIndexWidget key={spec.symbol} spec={spec} item={foreignIndex(overview, spec.symbol)} />)}
      </div>
      <div className="market-us-charts">
        {US_INDEXES.map((spec) => <UsChartDetails key={spec.symbol} spec={spec} item={foreignIndex(overview, spec.symbol)} chart={chart} />)}
      </div>
    </section>
  )
}
