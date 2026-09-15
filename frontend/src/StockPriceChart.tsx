import { useEffect, useMemo, useState } from 'react'
import ReactECharts from 'echarts-for-react'

import type { Bar } from './types'
import { buildStockChartOption, dataZoomEventWindow, normalizeStockChartWindow, prepareStockChartData, windowForRange, type StockChartRange, type StockChartWindow } from './stockChart'
import { formatTableNumber, formatTableVolume, isVerifiedShareSource } from './units'

const RANGES: Array<{ value: StockChartRange; label: string }> = [
  { value: 30, label: '近 30 日' },
  { value: 60, label: '近 60 日' },
  { value: 120, label: '近 120 日' },
  { value: 'all', label: '全部有效日線' },
]
const EMPTY_GAP_DATES: readonly string[] = []

function sourceLabel(sources: string[]): string {
  if (sources.length === 0) return '來源未提供'
  return sources.map((source) => source === 'twse' ? '臺灣證券交易所' : source === 'tpex' ? '證券櫃檯買賣中心' : '來源待核實').join('、')
}

export function StockPriceChart({ bars, knownGapDates = EMPTY_GAP_DATES }: { bars: readonly Bar[]; knownGapDates?: readonly string[] }) {
  const stableGapDates = knownGapDates.length === 0 ? EMPTY_GAP_DATES : knownGapDates
  const gapDateKey = stableGapDates.join('\u0000')
  const prepared = useMemo(() => prepareStockChartData(bars, { knownGapDates: stableGapDates }), [bars, gapDateKey])
  const [preset, setPreset] = useState<StockChartRange | null>('all')
  const [window, setWindow] = useState<StockChartWindow>(() => windowForRange(0, 'all'))

  useEffect(() => {
    setPreset('all')
    setWindow(windowForRange(prepared.points.length, 'all'))
  }, [prepared])

  const currentWindow = normalizeStockChartWindow(prepared.points.length, window)
  const option = useMemo(() => buildStockChartOption(prepared, currentWindow), [prepared, currentWindow])
  const visibleStart = prepared.points[currentWindow.start]
  const visibleEnd = prepared.points[currentWindow.end]
  const visibleSlotCount = prepared.points.length > 0 ? currentWindow.end - currentWindow.start + 1 : 0
  const visibleDrawableCount = prepared.points.slice(currentWindow.start, currentWindow.end + 1).filter((point) => point.bar != null).length
  const volumeUnitConfirmed = prepared.sourceNames.length > 0 && prepared.sourceNames.every((source) => isVerifiedShareSource(source))

  const chooseRange = (value: StockChartRange) => {
    setPreset(value)
    setWindow(windowForRange(prepared.points.length, value))
  }
  const resetZoom = () => {
    setPreset('all')
    setWindow({ start: 0, end: Math.max(0, prepared.points.length - 1) })
  }
  const handleDataZoom = (event: unknown) => {
    const next = dataZoomEventWindow(event, prepared.points.length)
    if (next) {
      setPreset(null)
      setWindow(next)
    }
  }

  return (
    <section className="panel stock-chart-panel" aria-labelledby="stock-price-chart-title">
      <div className="section-head stock-chart-head">
        <div>
          <div className="eyebrow">市場基礎層 · 日線</div>
          <h2 id="stock-price-chart-title">價格與成交量</h2>
        </div>
        <div className="chart-range-controls" role="group" aria-label="日線顯示區間">
          {RANGES.map((item) => (
            <button
              type="button"
              key={String(item.value)}
              className={'secondary-button' + (preset === item.value ? ' selected' : '')}
              aria-pressed={preset === item.value}
              onClick={() => chooseRange(item.value)}
              disabled={prepared.bars.length === 0}
            >
              {item.label}
            </button>
          ))}
          <button type="button" className="secondary-button" onClick={resetZoom} disabled={prepared.bars.length === 0} aria-label="重設日線顯示區間">重設</button>
        </div>
      </div>
      <div className="chart-meta stock-chart-meta">
        <span>視窗：{visibleStart?.date ?? '待核實'}～{visibleEnd?.date ?? '待核實'} · 可畫 K {visibleDrawableCount.toLocaleString()}／{visibleSlotCount.toLocaleString()}</span>
        <span>來源：{sourceLabel(prepared.sourceNames)} · 日線非即時</span>
        <details className="technical-details chart-status-details"><summary>資料狀態</summary><div>來源回應：{prepared.totalRows.toLocaleString()} 筆；可繪製日線：{prepared.bars.length.toLocaleString()} 筆。</div><div>價格為來源原值；還原方式未提供。</div></details>
      </div>
      {prepared.bars.length > 0 ? (
        <>
          <ReactECharts
            option={option}
            notMerge
            lazyUpdate
            autoResize
            opts={{ renderer: 'canvas' }}
            style={{ width: '100%', height: '440px' }}
            className="stock-price-chart"
            role="img"
            aria-label="日K與成交量互動圖表；詳細數值請查看下方圖表資料表"
            onEvents={{ datazoom: handleDataZoom }}
          />
          <div className="chart-legend" aria-label="圖表說明">
            <span><i className="legend-swatch legend-up" />紅：收盤高於或等於開盤</span>
            <span><i className="legend-swatch legend-down" />綠：收盤低於開盤</span>
            <span><i className="legend-line legend-ma20" />MA20</span>
            <span><i className="legend-line legend-ma60" />MA60</span>
            <span>{volumeUnitConfirmed ? '成交量單位：張（原始股數 ÷ 1000）' : '成交量單位：來源未核實，原值保留'}</span>
            <span>MA20／MA60：{prepared.maReason}</span>
          </div>
          <details className="technical-details chart-data-table">
            <summary>查看圖表資料表（開高低收與成交量）</summary>
            <div className="table-wrap compact-table"><p className="small-note">單位：股價及均線為各標的報價幣別的元，指數為點；成交量為張。空白表示未提供資料、均線樣本不足、數值無效或成交量單位待核實。</p>
              <table>
                <thead><tr><th>日期</th><th>開</th><th>高</th><th>低</th><th>收</th><th>成交量</th><th>MA20</th><th>MA60</th></tr></thead>
                <tbody>{prepared.points.slice(currentWindow.start, currentWindow.end + 1).reverse().map((point) => <tr key={point.date}>
                  <td>{point.date}</td>
                  {point.bar ? <><td>{point.bar.open.toLocaleString('zh-TW')}</td><td>{point.bar.high.toLocaleString('zh-TW')}</td><td>{point.bar.low.toLocaleString('zh-TW')}</td><td>{point.bar.close.toLocaleString('zh-TW')}</td><td className="numeric-cell">{formatTableVolume(point.bar.volume, point.bar.source)}</td></> : <td colSpan={5} aria-label="此日期行情資料不完整" />}
                  <td className="numeric-cell">{formatTableNumber(point.ma20, 2)}</td><td className="numeric-cell">{formatTableNumber(point.ma60, 2)}</td>
                </tr>)}</tbody>
              </table>
            </div>
          </details>
          {(prepared.invalidRows > 0 || prepared.duplicateDates.length > 0) && (
            <div className="chart-warning" role="status">
              已略過無法安全繪製的資料：無效／格式錯誤 {prepared.invalidRows} 筆、重複日期資料 {prepared.duplicateRows} 筆；重複日期 {prepared.duplicateDates.length ? prepared.duplicateDates.join('、') : '無'}。缺少的日線保持空缺。
            </div>
          )}
        </>
      ) : (
        <div className="empty chart-empty">
          {prepared.totalRows === 0
            ? '來源未提供可繪製的日線資料。'
            : `來源回應 ${prepared.totalRows} 筆，但可繪製日線 0 筆；無效／格式錯誤 ${prepared.invalidRows} 筆、重複日期資料 ${prepared.duplicateRows} 筆，缺少的日線保持空缺。`}
        </div>
      )}
    </section>
  )
}
