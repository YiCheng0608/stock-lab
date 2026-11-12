import { useEffect, useMemo, useRef, useState, type ReactNode, type TouchEvent } from 'react'
import { env as echartsEnv } from 'echarts'
import ReactEChartsModule from 'echarts-for-react'

import { getStockBars } from '../api'
import { Card, DataTable, DateBadge, EmptyState, Skeleton, Tabs, cx, tabPanelId, type Column } from '../components/ui'
import { formatDay } from '../dates'
import type { StockBarRow, StockBarsInterval, StockBarsResponse } from '../types'
import {
  BAR_RANGES,
  CLOSE_ONLY_NOTE,
  DEFAULT_BARS_RANGE,
  INDICATOR_PANELS,
  INTERVALS,
  MA_LINES,
  PRICE_BASIS,
  STOCK_BARS_MAX_LIMIT,
  buildBarsChartOption,
  levelsNote,
  type ChartLevels,
  chartLayout,
  longerBarsKey,
  longerStatus,
  needsMoreBars,
  retryLonger,
  settleLonger,
  shouldFetchLonger,
  swipeAxis,
  preferChromeInputPath,
  viewFromZoomEvent,
  zoomForView,
  formatBarVolume,
  formatPrice,
  formatTaipeiDateTime,
  indicatorPanelState,
  isCloseOnlySeries,
  isDrawableBar,
  maNotes,
  priceDigits,
  readChartTheme,
  sourcesLabel,
  VOLUME_UNITS,
  volumeKind,
  type ChartTheme,
  type BarsView,
  type LongerBars,
  type IndicatorPanelId,
  type MaField,
} from './stockBars'

// Vite resolves the ESM default export; under plain Node (scripts/ci-test.cjs, package type module) the CJS build
// arrives as its module object, whose `default` is the component.
const ReactECharts = (ReactEChartsModule as unknown as { default?: typeof ReactEChartsModule }).default ?? ReactEChartsModule

// Before any chart exists: Chromium Edge on a touch screen gets Chrome's input path (see preferChromeInputPath).
if (typeof window !== 'undefined') preferChromeInputPath(echartsEnv, 'ontouchstart' in window)

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
  return basis === PRICE_BASIS
    ? 'K 線為原始價；均線與指標以各根資料日的原始價為基準換算前期除權息'
    : '價格基準待核實'
}

function indicatorSourceLabel(response: StockBarsResponse): string {
  if (response.interval === 'week') return '週線依日線聚合後即時計算'
  const computedAt = formatTaipeiDateTime(response.indicators.computed_at)
  return computedAt ? `日線批次計算於 ${computedAt}（台灣時間）` : '日線批次尚未計算'
}

// Prices and moving averages share the latest close's tick decimals (DESIGN_SYSTEM §3); an index or futures contract is
// in 點 (Issue 549/552). A day the source gave a close without open/high/low (Issue 552) keeps its close in the table.
function barColumns(digits: number, unit: string, volumeUnit: string): ReadonlyArray<Column<StockBarRow>> {
  const price = (field: 'open' | 'high' | 'low' | 'close') => (bar: StockBarRow) => isDrawableBar(bar) ? formatPrice(bar[field], digits) : ''
  const close = (bar: StockBarRow) => isDrawableBar(bar) || (bar.price_reason && !bar.is_suspended) ? formatPrice(bar.close, digits) : ''
  return [
    { key: 'date', header: '日期', cell: (bar) => `${formatDay(bar.date) ?? bar.date}${bar.is_suspended ? '（停牌）' : ''}` },
    { key: 'open', header: `開（${unit}）`, num: true, cell: price('open') },
    { key: 'high', header: `高（${unit}）`, num: true, cell: price('high') },
    { key: 'low', header: `低（${unit}）`, num: true, cell: price('low') },
    { key: 'close', header: `收（${unit}）`, num: true, cell: close },
    { key: 'volume', header: `成交量（${volumeUnit}）`, num: true, cell: (bar) => isDrawableBar(bar) || bar.price_reason ? formatBarVolume(bar) : '' },
    ...MA_LINES.map((line): Column<StockBarRow> => ({ key: line.field, header: `${line.label}（${unit}）`, num: true, cell: (bar) => typeof bar[line.field] === 'number' ? formatPrice(bar[line.field], digits) : '' })),
  ]
}

export const isIndexInstrument = (instrumentType?: string | null) => instrumentType?.toLowerCase() === 'index'
export const isFuturesInstrument = (instrumentType?: string | null) => instrumentType?.toLowerCase() === 'futures'

function tableNote(instrumentType: string | null | undefined, volumeUnit: string): string {
  const blank = '空白表示來源未提供、停牌或指標無資料。'
  if (isIndexInstrument(instrumentType)) return `單位：指數與均線為點；成交量為${volumeUnit}。${blank}`
  if (isFuturesInstrument(instrumentType)) return `單位：價格與均線為點；成交量為${volumeUnit}。${blank}`
  return `單位：價格與均線為各標的報價幣別的元；成交量為${volumeUnit}。${blank}`
}

// 全部 (or a range reaching before the loaded page) asks the bars API once more with its maximum limit (Issue 600):
// the page's own query stays at 250, so the header, cache and the other tab read what they read before.
// The state transitions are the pure longer* helpers in stockBars.ts (tested there).
function useLongerBars(loaded: StockBarsResponse | undefined, view: BarsView) {
  const [longer, setLonger] = useState<LongerBars | null>(null)
  const key = loaded ? longerBarsKey(loaded) : ''
  const wanted = !!loaded && needsMoreBars(loaded, view)
  useEffect(() => {
    if (!loaded || !shouldFetchLonger(longer, key, wanted)) return
    setLonger({ key })
    const { exchange, symbol } = loaded.instrument
    // No cancel on cleanup: settleLonger drops a reply whose series is no longer pending.
    getStockBars(exchange, symbol, loaded.interval, STOCK_BARS_MAX_LIMIT).then(
      (response) => setLonger((current) => settleLonger(current, key, { data: response })),
      (error: unknown) => setLonger((current) => settleLonger(current, key, { error })),
    )
  }, [key, wanted, loaded, longer])
  return { ...longerStatus(longer, key, wanted), retry: () => setLonger(retryLonger) }
}

export function StockBarsChart({
  interval,
  onIntervalChange,
  data: loaded,
  loading,
  error,
  instrumentType,
  title = 'K 線與技術指標',
  titleId = 'stock-chart-title',
  footer,
  levels = null,
}: {
  interval: StockBarsInterval
  onIntervalChange: (interval: StockBarsInterval) => void
  data: StockBarsResponse | undefined
  loading: boolean
  error: unknown
  instrumentType?: string | null
  // The market page (Issue 549) names its index; the stock page keeps the default.
  title?: string
  titleId?: string
  // Lines under the chart (the market page's TX contract and attribution, Issue 552), shown in every state.
  footer?: ReactNode
  // The rule levels of the strategy that holds on the data day (the stock page); the market page passes none.
  levels?: ChartLevels | null
}) {
  const narrow = useNarrow()
  const [panel, setPanel] = useState<IndicatorPanelId>('macd')
  const [visibleMa, setVisibleMa] = useState<ReadonlySet<MaField>>(ALL_MA)
  // The range stays when 日K／週K or the market page's series changes (the card stays mounted while it loads).
  const [view, setView] = useState<BarsView>({ range: DEFAULT_BARS_RANGE })
  const longer = useLongerBars(loaded, view)
  // The longer series 全部 fetched, once it is here; otherwise the series the page loaded.
  const data = longer.data ?? loaded
  // A redraw re-applies the view (notMerge) after a vertical swipe left the chart a few px panned.
  const [redraw, setRedraw] = useState(0)
  const zoom = useMemo(() => data ? zoomForView(data, view) : null, [data, view, redraw])
  const swipe = useRef<{ x: number; y: number; axis: 'vertical' | 'horizontal' | null; ignored: boolean } | null>(null)
  const onTouchStart = (event: TouchEvent) => {
    const touch = event.touches[0]
    // Two fingers are a pinch: never a page scroll.
    swipe.current = touch ? { x: touch.clientX, y: touch.clientY, axis: event.touches.length > 1 ? 'horizontal' : null, ignored: false } : null
  }
  const onTouchMove = (event: TouchEvent) => {
    const touch = event.touches[0]
    const current = swipe.current
    if (!touch || !current) return
    if (event.touches.length > 1) current.axis = 'horizontal'
    else if (current.axis === null) current.axis = swipeAxis(touch.clientX - current.x, touch.clientY - current.y)
  }
  const onTouchEnd = () => {
    if (swipe.current?.ignored) setRedraw((count) => count + 1)
    swipe.current = null
  }
  const onDataZoom = (event: unknown) => {
    if (!data) return
    if (swipe.current?.axis === 'vertical') { swipe.current.ignored = true; return }
    const next = viewFromZoomEvent(data, event, zoom ?? undefined)
    if (next) setView(next)
  }
  const theme = useMemo(documentTheme, [])
  const layout = useMemo(() => chartLayout(narrow ? 220 : 320), [narrow])
  const latestClose = data ? [...data.bars].reverse().find(isDrawableBar)?.close : undefined
  const digits = priceDigits(latestClose, instrumentType)
  const panelState = data ? indicatorPanelState(data, panel) : null
  const option = useMemo(
    () => data && panelState && zoom ? buildBarsChartOption(data, { panel, panelState, visibleMa, theme, layout, zoom, digits, levels }) : null,
    [data, panel, panelState?.kind, visibleMa, theme, layout, zoom, digits, levels?.entry, levels?.stop, levels?.target],
  )
  const toggleMa = (field: MaField) => setVisibleMa((current) => {
    const next = new Set(current)
    if (next.has(field)) next.delete(field)
    else next.add(field)
    return next
  })
  const notes = data ? maNotes(data, visibleMa) : []
  const unit = interval === 'week' ? '週線' : '日線'
  const volumeUnit = VOLUME_UNITS[volumeKind(data?.sources ?? [])]

  return (
    <Card
      className="stock-chart-card"
      eyebrow={data ? `技術指標 ${data.indicators.formula_version}` : '技術指標'}
      title={title}
      titleId={titleId}
      aria-labelledby={titleId}
      aside={<DateBadge date={data?.data_as_of ?? null} />}
    >
      <div className="chart-toolbar">
        <div className="chart-toolbar-start">
          <Tabs items={INTERVALS} value={interval} onChange={onIntervalChange} label="K 線週期" idPrefix="bars-interval" className="tabs-compact" />
          <div className="filter-chips bars-range" role="group" aria-label="顯示區間">
            {BAR_RANGES.map((item) => (
              <button key={item.id} type="button" className={cx('badge filter-chip', item.id === view.range && 'filter-chip-selected')} aria-pressed={item.id === view.range} onClick={() => { longer.retry(); setView({ range: item.id }) }}>
                {item.label}
              </button>
            ))}
          </div>
        </div>
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
            <div className="chart-stage" id={tabPanelId('indicator', panel)} role="tabpanel" aria-labelledby={`indicator-tab-${panel}`} style={{ height: layout.height }}
              onTouchStartCapture={onTouchStart} onTouchMoveCapture={onTouchMove} onTouchEndCapture={onTouchEnd} onTouchCancelCapture={onTouchEnd}>
              <ReactECharts
                option={option}
                notMerge
                lazyUpdate
                autoResize
                opts={{ renderer: 'canvas' }}
                style={{ width: '100%', height: layout.height }}
                role="img"
                aria-label={`${unit} K 線、成交量與 ${INDICATOR_PANELS.find((item) => item.id === panel)?.label} 指標圖${levels ? '，含規則價位線' : ''}；數值見下方資料表`}
                onEvents={{ datazoom: onDataZoom }}
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
            {levels && <p className="chart-note chart-levels-note" data-chart-levels>{levelsNote(levels)}</p>}
            {longer.loading && <p className="chart-note" role="status">正在載入更早的{unit}…</p>}
            {longer.failed && <p className="chart-note" role="status">更早的{unit}暫時無法載入，目前顯示最近 {data.count} 根</p>}
            {isCloseOnlySeries(data.bars) && <p className="chart-note">{CLOSE_ONLY_NOTE}</p>}
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
              <DataTable
                note={tableNote(instrumentType, volumeUnit)}
                columns={barColumns(digits, isIndexInstrument(instrumentType) || isFuturesInstrument(instrumentType) ? '點' : '元', volumeUnit)}
                rows={data.bars.slice(-30).reverse()}
                rowKey={(bar) => bar.date}
              />
            </details>
          </>
        )}
      </div>
      {footer}
    </Card>
  )
}
