import { useEffect, useMemo, useState } from 'react'
import ReactEChartsModule from 'echarts-for-react'

import { Card, DateBadge, EmptyState, Skeleton, Table, Tabs, tabPanelId } from '../components/ui'
import type { StockBarsInterval, StockBarsResponse } from '../types'
import {
  INDICATOR_PANELS,
  INTERVALS,
  MA_LINES,
  buildBarsChartOption,
  chartLayout,
  dataZoomPercent,
  defaultZoom,
  formatBarVolume,
  formatPrice,
  indicatorPanelState,
  isDrawableBar,
  maNotes,
  priceDigits,
  readChartTheme,
  sourcesLabel,
  type ChartTheme,
  type ChartZoom,
  type IndicatorPanelId,
  type MaField,
} from './stockBars'

// Vite resolves the ESM default export; under plain Node (scripts/ci-test.cjs, package type module) the CJS build
// arrives as its module object, whose `default` is the component.
const ReactECharts = (ReactEChartsModule as unknown as { default?: typeof ReactEChartsModule }).default ?? ReactEChartsModule

const ALL_MA: ReadonlySet<MaField> = new Set(MA_LINES.map((line) => line.field))

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

function priceBasisLabel(basis: string): string {
  return basis === 'as_of_date_raw_basis'
    ? 'K 線為原始價；均線與指標以各根資料日的原始價為基準換算前期除權息'
    : '價格基準待核實'
}

function indicatorSourceLabel(response: StockBarsResponse): string {
  if (response.interval === 'week') return '週線依日線聚合後即時計算'
  return response.indicators.computed_at ? `日線批次計算於 ${response.indicators.computed_at.replace('T', ' ').slice(0, 16)}` : '日線批次尚未計算'
}

export function StockBarsChart({
  interval,
  onIntervalChange,
  data,
  loading,
  error,
  instrumentType,
}: {
  interval: StockBarsInterval
  onIntervalChange: (interval: StockBarsInterval) => void
  data: StockBarsResponse | undefined
  loading: boolean
  error: unknown
  instrumentType?: string | null
}) {
  const narrow = useNarrow()
  const [panel, setPanel] = useState<IndicatorPanelId>('macd')
  const [visibleMa, setVisibleMa] = useState<ReadonlySet<MaField>>(ALL_MA)
  const count = data?.bars.length ?? 0
  const [zoom, setZoom] = useState<ChartZoom>(() => defaultZoom(count))
  useEffect(() => setZoom(defaultZoom(count)), [data, count])
  const theme = useMemo(documentTheme, [])
  const layout = useMemo(() => chartLayout(narrow ? 220 : 320), [narrow])
  const latestClose = data ? [...data.bars].reverse().find(isDrawableBar)?.close : undefined
  const digits = priceDigits(latestClose, instrumentType)
  const panelState = data ? indicatorPanelState(data, panel) : null
  const option = useMemo(
    () => data && panelState ? buildBarsChartOption(data, { panel, panelState, visibleMa, theme, layout, zoom, digits }) : null,
    [data, panel, panelState?.kind, visibleMa, theme, layout, zoom, digits],
  )
  const toggleMa = (field: MaField) => setVisibleMa((current) => {
    const next = new Set(current)
    if (next.has(field)) next.delete(field)
    else next.add(field)
    return next
  })
  const notes = data ? maNotes(data, visibleMa) : []
  const unit = interval === 'week' ? '週線' : '日線'

  return (
    <Card
      className="stock-chart-card"
      eyebrow={data ? `技術指標 ${data.indicators.formula_version}` : '技術指標'}
      title="K 線與技術指標"
      titleId="stock-chart-title"
      aria-labelledby="stock-chart-title"
      aside={<DateBadge date={data?.data_as_of ?? null} />}
    >
      <div className="chart-toolbar">
        <Tabs items={INTERVALS} value={interval} onChange={onIntervalChange} label="K 線週期" idPrefix="bars-interval" className="tabs-compact" />
        <div className="ma-toggles" role="group" aria-label="均線顯示">
          {MA_LINES.map((line) => (
            <label className="ma-toggle" key={line.field}>
              <input type="checkbox" checked={visibleMa.has(line.field)} onChange={() => toggleMa(line.field)} />
              <i className={`ma-swatch ma-swatch-${line.color}`} aria-hidden="true" />
              {line.label}
            </label>
          ))}
        </div>
      </div>
      <div id={tabPanelId('bars-interval', interval)} role="tabpanel" aria-labelledby={`bars-interval-tab-${interval}`}>
        {loading ? (
          <Skeleton height={layout.height} label={`${unit}載入中…`} className="chart-skeleton" />
        ) : error ? (
          <EmptyState title="資料暫時無法載入" reason={error instanceof Error ? error.message : '請稍後重新整理'} />
        ) : !data || !option || data.bars.length === 0 ? (
          <EmptyState reason={`來源未提供${unit}`} />
        ) : (
          <>
            <div className="chart-stage" id={tabPanelId('indicator', panel)} role="tabpanel" aria-labelledby={`indicator-tab-${panel}`} style={{ height: layout.height }}>
              <ReactECharts
                option={option}
                notMerge
                lazyUpdate
                autoResize
                opts={{ renderer: 'canvas' }}
                style={{ width: '100%', height: layout.height }}
                role="img"
                aria-label={`${unit} K 線、成交量與 ${INDICATOR_PANELS.find((item) => item.id === panel)?.label} 指標圖；數值見下方資料表`}
                onEvents={{ datazoom: (event: unknown) => { const next = dataZoomPercent(event); if (next) setZoom(next) } }}
              />
              <div className="indicator-tabs" style={{ top: layout.tabsTop, left: layout.left, right: layout.right }}>
                <Tabs items={INDICATOR_PANELS} value={panel} onChange={setPanel} label="指標面板" idPrefix="indicator" className="tabs-compact" />
              </div>
              {panelState && panelState.kind !== 'chart' && (
                <div className="indicator-empty" style={{ top: layout.indicator.top, height: layout.indicator.height, left: layout.left, right: layout.right }}>
                  <EmptyState title={panelState.title} reason={panelState.reason} />
                </div>
              )}
            </div>
            {panelState?.kind === 'chart' && panelState.note && <p className="chart-note">{panelState.note}</p>}
            {notes.length > 0 && <ul className="chart-note-list">{notes.map((note) => <li key={note}>{note}</li>)}</ul>}
            <div className="chart-meta">
              <span>來源 {sourcesLabel(data.sources)}</span>
              <span>{priceBasisLabel(data.indicators.price_basis)}</span>
              <span>{indicatorSourceLabel(data)}</span>
              <span>最近 {data.count} 根{unit}；缺日不補、停牌不畫 K 線</span>
            </div>
            <details className="details chart-data-table">
              <summary>查看圖表資料表（最近 30 根）</summary>
              <Table note="單位：價格與均線為各標的報價幣別的元；成交量為張。空白表示來源未提供、停牌或指標無資料。">
                <thead><tr><th>日期</th><th className="num">開</th><th className="num">高</th><th className="num">低</th><th className="num">收</th><th className="num">成交量</th>{MA_LINES.map((line) => <th className="num" key={line.field}>{line.label}</th>)}</tr></thead>
                <tbody>{data.bars.slice(-30).reverse().map((bar) => {
                  const drawable = isDrawableBar(bar)
                  return <tr key={bar.date}>
                    <td>{bar.date}{bar.is_suspended ? '（停牌）' : ''}</td>
                    <td className="num">{drawable ? formatPrice(bar.open, digits) : ''}</td>
                    <td className="num">{drawable ? formatPrice(bar.high, digits) : ''}</td>
                    <td className="num">{drawable ? formatPrice(bar.low, digits) : ''}</td>
                    <td className="num">{drawable ? formatPrice(bar.close, digits) : ''}</td>
                    <td className="num">{drawable ? formatBarVolume(bar) : ''}</td>
                    {MA_LINES.map((line) => <td className="num" key={line.field}>{typeof bar[line.field] === 'number' ? formatPrice(bar[line.field], digits) : ''}</td>)}
                  </tr>
                })}</tbody>
              </Table>
            </details>
          </>
        )}
      </div>
    </Card>
  )
}
