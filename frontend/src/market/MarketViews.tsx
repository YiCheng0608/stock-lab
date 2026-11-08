import type { ReactNode } from 'react'

import { DateBadge, cx } from '../components/ui'
import type { MarketOverview, MarketOverviewExchange, StockBarsInterval, StockBarsResponse } from '../types'
import { formatFixed } from '../units'
import { isFiniteNumber } from '../stock/stockBars'
import { StockBarsChart } from '../stock/StockBarsChart'
import {
  EXCHANGES,
  SHORT_SCOPE_LABELS,
  TAIEX_CHART_TITLE,
  TPEX_NO_BARS_TEXT,
  available,
  changeTone,
  dash,
  marketOverviewNotes,
  missingText,
  signedPercent,
  type ExchangeSpec,
} from './marketOverview'

// The market page blocks (/market, Issue 549): 大盤概況 and 加權指數日線, in the order DESIGN_SYSTEM §4 fixes.
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

// 加權指數日線 is the stock page's StockBarsChart (same period switch, indicators and synthetic-bar rules) so the real
// daily K bars of Issue 552 need no new view; 櫃買 has no daily history yet and says so in one line under it.
export function IndexChartSection({ interval, onIntervalChange, data, loading, error }: {
  interval: StockBarsInterval
  onIntervalChange: (interval: StockBarsInterval) => void
  data: StockBarsResponse | undefined
  loading: boolean
  error: unknown
}) {
  return (
    <div className="market-chart">
      <StockBarsChart interval={interval} onIntervalChange={onIntervalChange} data={data} loading={loading} error={error}
        instrumentType="index" title={TAIEX_CHART_TITLE} titleId="market-chart-title" />
      <p className="market-no-bars" data-exchange="TPEx"><b>櫃買指數日線</b> <span>{TPEX_NO_BARS_TEXT}</span></p>
    </div>
  )
}
