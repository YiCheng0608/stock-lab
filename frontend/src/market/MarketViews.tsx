import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import ReactEChartsModule from 'echarts-for-react'

import { DataTable, DateBadge, EmptyState, Skeleton, Tabs, cx, tabPanelId, type Column } from '../components/ui'
import { formatDay } from '../dates'
import type { MarketOverview, MarketOverviewExchange, StockBarRow, StockBarsInterval, StockBarsResponse } from '../types'
import { formatFixed } from '../units'
import { dataZoomPercent, defaultZoom, isFiniteNumber, readChartTheme, type ChartTheme, type ChartZoom } from '../stock/stockBars'
import {
  EXCHANGES,
  MARKET_INTERVALS,
  SHORT_SCOPE_LABELS,
  TABLE_ROWS,
  TPEX_NO_BARS_TEXT,
  available,
  buildIndexChartOption,
  changeTone,
  chartMeta,
  closeOf,
  dash,
  indexChartLayout,
  marketOverviewNotes,
  missingText,
  signedPercent,
  type ExchangeSpec,
} from './marketOverview'

// The market page blocks (/market, Issue 549): 大盤概況 and 加權指數日線, in the order DESIGN_SYSTEM §4 fixes.
// Copy and units follow UI_COPY_SPEC §11.

// Vite resolves the ESM default export; under plain Node (scripts/ci-test.cjs) the CJS build arrives as its module object.
const ReactECharts = (ReactEChartsModule as unknown as { default?: typeof ReactEChartsModule }).default ?? ReactEChartsModule

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

function documentTheme(): ChartTheme {
  const style = typeof document === 'undefined' ? null : getComputedStyle(document.documentElement)
  return readChartTheme((token) => style?.getPropertyValue(token) ?? '')
}

function useNarrow(query = '(max-width: 640px)'): boolean {
  const [narrow, setNarrow] = useState(() => typeof window !== 'undefined' && window.matchMedia(query).matches)
  useEffect(() => {
    const media = window.matchMedia(query)
    const onChange = () => setNarrow(media.matches)
    onChange()
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [query])
  return narrow
}

const TABLE_COLUMNS: ReadonlyArray<Column<StockBarRow>> = [
  { key: 'date', header: '日期', cell: (bar) => formatDay(bar.date) ?? bar.date },
  { key: 'close', header: '收盤（點）', num: true, cell: (bar) => { const close = closeOf(bar); return close == null ? '' : formatFixed(close, 2) } },
]

// 加權指數日線 with the stock page's period switch; 櫃買 has no daily history and says so in the last row.
export function IndexChartPanel({ interval, onIntervalChange, data, loading, error }: {
  interval: StockBarsInterval
  onIntervalChange: (interval: StockBarsInterval) => void
  data: StockBarsResponse | undefined
  loading: boolean
  error: unknown
}) {
  const narrow = useNarrow()
  const theme = useMemo(documentTheme, [])
  const layout = useMemo(() => indexChartLayout(narrow ? 220 : 320), [narrow])
  const count = data?.bars.length ?? 0
  const [zoom, setZoom] = useState<ChartZoom>(() => defaultZoom(count))
  useEffect(() => setZoom(defaultZoom(count)), [data, count])
  const drawable = Boolean(data?.bars.some((bar) => closeOf(bar) != null))
  const option = useMemo(() => data && drawable ? buildIndexChartOption(data, theme, layout, zoom) : null, [data, drawable, theme, layout, zoom])
  const unit = interval === 'week' ? '週線' : '日線'
  return (
    <section className="panel market-panel market-chart-panel" aria-labelledby="market-chart-title">
      <div className="panel-head">
        <h2 id="market-chart-title">加權指數日線</h2>
        {!loading && <DateBadge date={data?.data_as_of ?? null} />}
      </div>
      <div className="chart-toolbar">
        <Tabs items={MARKET_INTERVALS} value={interval} onChange={onIntervalChange} label="加權指數週期" idPrefix="market-interval" className="tabs-compact" />
      </div>
      <div id={tabPanelId('market-interval', interval)} role="tabpanel" aria-labelledby={`market-interval-tab-${interval}`}>
        {loading ? (
          <Skeleton height={layout.height} label={`${unit}載入中…`} className="chart-skeleton" />
        ) : error ? (
          <EmptyState title="資料暫時無法載入" reason={error instanceof Error ? error.message : '請稍後重新整理'} />
        ) : !data || !option ? (
          <EmptyState reason={`來源未提供${unit}`} />
        ) : (
          <>
            <div className="chart-stage" style={{ height: layout.height }}>
              <ReactECharts
                option={option}
                notMerge
                lazyUpdate
                autoResize
                opts={{ renderer: 'canvas' }}
                style={{ width: '100%', height: layout.height }}
                role="img"
                aria-label={`加權指數${unit}收盤走勢圖；數值見下方資料表`}
                onEvents={{ datazoom: (event: unknown) => { const next = dataZoomPercent(event); if (next) setZoom(next) } }}
              />
            </div>
            <div className="chart-meta">{chartMeta(data).map((line) => <span key={line}>{line}</span>)}</div>
            <details className="details chart-data-table">
              <summary>查看圖表資料表（最近 {TABLE_ROWS} 根）</summary>
              <DataTable note="單位：點。空白表示來源未提供收盤。" columns={TABLE_COLUMNS} rows={data.bars.slice(-TABLE_ROWS).reverse()} rowKey={(bar) => bar.date} />
            </details>
          </>
        )}
      </div>
      <p className="market-no-bars" data-exchange="TPEx"><b>櫃買指數日線</b> <span>{TPEX_NO_BARS_TEXT}</span></p>
    </section>
  )
}
