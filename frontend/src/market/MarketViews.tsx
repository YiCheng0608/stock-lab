import type { ReactNode } from 'react'

import { DateBadge, cx } from '../components/ui'
import type { MarketOverview, MarketOverviewExchange, StockBarsInterval, StockBarsResponse } from '../types'
import { formatFixed } from '../units'
import { isFiniteNumber } from '../stock/stockBars'
import { StockBarsChart } from '../stock/StockBarsChart'
import {
  EXCHANGES,
  SHORT_SCOPE_LABELS,
  TAIFEX_ATTRIBUTION,
  TX_ROLL_NOTE,
  available,
  changeTone,
  collectedSinceText,
  dash,
  futuresLatestText,
  marketOverviewNotes,
  missingText,
  signedPercent,
  type ExchangeSpec,
  type MarketChartSpec,
} from './marketOverview'

// The market page blocks (/market, Issue 549/552): 大盤概況 and the three daily K charts, in the order DESIGN_SYSTEM §4
// fixes.
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
export function MarketChartView({ spec, interval, onIntervalChange, data, loading, error }: {
  spec: MarketChartSpec
  interval: StockBarsInterval
  onIntervalChange: (interval: StockBarsInterval) => void
  data: StockBarsResponse | undefined
  loading: boolean
  error: unknown
}) {
  return (
    <div className="market-chart" data-chart={spec.key}>
      <StockBarsChart interval={interval} onIntervalChange={onIntervalChange} data={data} loading={loading} error={error}
        instrumentType={spec.instrumentType} title={spec.title} titleId={spec.titleId}
        footer={spec.instrumentType === 'futures' ? <FuturesFooter data={data} /> : undefined} />
    </div>
  )
}
