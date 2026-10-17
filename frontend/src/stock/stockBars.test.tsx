import { renderToStaticMarkup } from 'react-dom/server'

import { StockBarsChart } from './StockBarsChart'
import { StockQuoteLine } from './StockHeader'
import {
  CHART_THEME_TOKENS,
  INDICATOR_PANELS,
  MA_LINES,
  STOCK_BARS_LIMIT,
  buildBarsChartOption,
  chartLayout,
  defaultZoom,
  fieldsState,
  formatBarsTooltip,
  formatSignedPercent,
  formatSignedPrice,
  indicatorPanelState,
  maNotes,
  nullReasonText,
  priceDigits,
  readChartTheme,
  stockBarsPath,
  stockQuote,
  type IndicatorPanelId,
  type MaField,
} from './stockBars'
import { barsResponse, insufficientDaily, notComputedDaily, suspendedWithGapDaily, tradedBar, weeklySeries } from './stockBars.fixtures'
import type { StockBarsResponse } from '../types'

// Standalone regression module (no browser, no server, no network) for the stock page K-line, indicator
// panels and header quote, on bars-API fixtures (PR #155 shape).
const check = (condition: boolean, message: string) => { if (!condition) throw new Error(message) }

// Theme values stand in for the CSS variables the component reads at runtime; each is its own token name.
const theme = readChartTheme((token) => `token(${token})`)
check(theme.up === 'token(--color-up)' && theme.ma120 === 'token(--chart-ma120)', 'chart theme reads tokens by name')
check(Object.keys(CHART_THEME_TOKENS).length === Object.keys(theme).length, 'every theme key maps to a token')

// ---- request parameters: limit 250 by default, interval switches day → week ----
check(STOCK_BARS_LIMIT === 250, 'stock page asks for 250 bars by default')
check(stockBarsPath('TWSE', '2330', 'day') === '/stocks/TWSE/2330/bars?interval=day&limit=250', 'daily request path')
check(stockBarsPath('TPEx', '6488', 'week') === '/stocks/TPEx/6488/bars?interval=week&limit=250', 'weekly toggle switches only the interval parameter')
check(stockBarsPath('TWSE', 'A&B', 'day', 10) === '/stocks/TWSE/A%26B/bars?interval=day&limit=10', 'symbol is path-encoded and limit is passed through')

// ---- insufficient data: 「日線不足 34 根，現有 20 根」 from reasons + required_bars / bar_count ----
const insufficient = insufficientDaily()
const macd = indicatorPanelState(insufficient, 'macd')
check(macd.kind === 'empty' && macd.title === '無資料' && macd.reason === '日線不足 34 根，現有 20 根', `MACD panel reason composed from the largest required count: ${JSON.stringify(macd)}`)
for (const panel of ['rsi', 'kd', 'boll'] as const) check(indicatorPanelState(insufficient, panel).kind === 'chart', `${panel} has values on the latest bar`)
check(nullReasonText('insufficient_bars', { interval: 'day', required: 60, barCount: 12 }) === '日線不足 60 根，現有 12 根', 'reason text with counts')
check(nullReasonText('insufficient_bars', { interval: 'week', required: 20, barCount: null }) === '週線不足 20 根', 'reason text without bar_count')
check(nullReasonText('no_price_change', { interval: 'day' }) === '期間內收盤沒有漲跌，無法計算', 'no_price_change reason')
check(nullReasonText('something_new', { interval: 'day' }) === '原因待核實', 'unknown codes are not shown raw')
const allMa = new Set<MaField>(MA_LINES.map((line) => line.field))
check(maNotes(insufficient, allMa).join('|') === 'MA60 無資料：日線不足 60 根，現有 20 根|MA120 無資料：日線不足 120 根，現有 20 根', 'MA notes list only lines without a value')
check(maNotes(insufficient, new Set<MaField>(['ma5', 'ma20'])).length === 0, 'hidden MA lines have no note')

// ---- not_computed: 「指標尚未計算」 ----
const notComputed = notComputedDaily()
for (const panel of INDICATOR_PANELS) {
  const state = indicatorPanelState(notComputed, panel.id)
  check(state.kind === 'not_computed' && state.title === '指標尚未計算', `${panel.id}: not_computed state`)
}
check(fieldsState(notComputed.bars[1], ['ma5'], notComputed).kind === 'not_computed', 'not_computed field state')
check(maNotes(notComputed, new Set<MaField>(['ma5']))[0] === 'MA5 指標尚未計算：2026-10-16 的指標尚未由批次計算', 'MA note for not_computed')

// ---- suspended day + missing calendar day ----
const suspended = suspendedWithGapDaily()
const dates = suspended.bars.map((bar) => bar.date)
check(dates.length === 40 && !dates.includes('2026-09-07') && dates.includes('2026-09-08'), 'the missing calendar day is not filled in')
const suspendedState = indicatorPanelState(suspended, 'rsi')
check(suspendedState.kind === 'chart' && suspendedState.note === `${dates[39]} RSI無資料：停牌，當日不計算`, `latest suspended bar keeps the chart and explains the gap: ${JSON.stringify(suspendedState)}`)
const suspendedQuote = stockQuote(suspended.bars)
check(suspendedQuote.date === dates[38] && suspendedQuote.close === suspended.bars[38].close, 'latest close skips the suspended last row')
check(suspendedQuote.change != null && Math.abs(suspendedQuote.change - 0.5) < 1e-9, 'change uses the adjacent traded row before it')
const haltThenTrade = stockQuote([...suspended.bars.slice(29, 30), suspended.bars[30], suspended.bars[31]])
check(haltThenTrade.date === dates[31] && haltThenTrade.change === null && haltThenTrade.tone === 'flat', 'no adjacent trusted previous close → 漲跌待核實')

// ---- quote color and sign ----
const up = stockQuote([tradedBar('2026-10-15', 98.5, 1), tradedBar('2026-10-16', 100, 2)])
check(up.tone === 'up' && formatSignedPrice(up.change, up.digits) === '+1.5' && formatSignedPercent(up.changePct) === '+1.52%', `up: ${JSON.stringify(up)}`)
const down = stockQuote([tradedBar('2026-10-15', 600, 1), tradedBar('2026-10-16', 590, 2)])
check(down.tone === 'down' && formatSignedPrice(down.change, down.digits) === '-10' && formatSignedPercent(down.changePct) === '-1.67%', `down: ${JSON.stringify(down)}`)
const flat = stockQuote([tradedBar('2026-10-15', 25.35, 1), tradedBar('2026-10-16', 25.35, 2)])
check(flat.tone === 'flat' && formatSignedPrice(flat.change, flat.digits) === '0.00' && formatSignedPercent(flat.changePct) === '0.00%', `flat: ${JSON.stringify(flat)}`)
check(priceDigits(25, 'stock') === 2 && priceDigits(120, 'stock') === 1 && priceDigits(1085, 'stock') === 0 && priceDigits(150, 'etf') === 2, 'price decimals follow the tick ladder')
const upMarkup = renderToStaticMarkup(<StockQuoteLine bars={[tradedBar('2026-10-15', 98.5, 1), tradedBar('2026-10-16', 100, 2)]} />)
check(upMarkup.includes('tone-up') && upMarkup.includes('+1.5（+1.52%）') && upMarkup.includes('100.0'), `up markup: ${upMarkup}`)
const downMarkup = renderToStaticMarkup(<StockQuoteLine bars={[tradedBar('2026-10-15', 600, 1), tradedBar('2026-10-16', 590, 2)]} />)
check(downMarkup.includes('tone-down') && downMarkup.includes('-10（-1.67%）') && !downMarkup.includes('tone-up'), `down markup: ${downMarkup}`)
const emptyMarkup = renderToStaticMarkup(<StockQuoteLine bars={[]} />)
check(emptyMarkup.includes('待核實') && emptyMarkup.includes('漲跌待核實') && emptyMarkup.includes('tone-flat') && !emptyMarkup.includes('>0<'), 'no bars → 待核實, never 0')
check(upMarkup.includes('資料 2026-10-16') && upMarkup.includes('臺灣證券交易所'), 'header shows data date badge and source')

// ---- weekly series ----
const weekly = weeklySeries()
const weeklyMacd = indicatorPanelState(weekly, 'macd')
check(weeklyMacd.kind === 'empty' && weeklyMacd.reason === '週線不足 34 根，現有 3 根', `weekly reason counts weeks: ${JSON.stringify(weeklyMacd)}`)
const weeklyTooltip = formatBarsTooltip(weekly, 2, 'macd', allMa, 0)
check(weeklyTooltip.includes('2026-10-12～2026-10-16（5 個交易日）') && weeklyTooltip.includes('成交量（張） 105,000'), `weekly tooltip: ${weeklyTooltip}`)
check(stockQuote(weekly.bars).sources.join() === 'twse', 'weekly rows read their sources list')

// ---- chart option: K line, volume, five MAs, four indicator panels ----
const layout = chartLayout(320)
check(layout.indicator.height === Math.round(layout.main.height * 0.35), 'indicator panel is 35% of the main chart')
const series = (response: StockBarsResponse, panel: IndicatorPanelId, visible: ReadonlySet<MaField> = allMa) => {
  const option = buildBarsChartOption(response, { panel, panelState: indicatorPanelState(response, panel), visibleMa: visible, theme, layout, zoom: defaultZoom(response.bars.length), digits: 2 })
  return { option, list: option.series as Array<{ name: string; type: string; xAxisIndex: number; data: unknown[]; lineStyle?: { color: string }; itemStyle?: Record<string, unknown> }> }
}
const longDaily = barsResponse(Array.from({ length: 130 }, (_, index) => tradedBar(`2026-${String(1 + Math.floor(index / 28)).padStart(2, '0')}-${String(1 + (index % 28)).padStart(2, '0')}`, 100 + (index % 7), index + 1)))
const expectedIndicators: Record<IndicatorPanelId, string[]> = { macd: ['MACD 柱', 'DIF', 'DEA'], rsi: ['RSI6', 'RSI12'], kd: ['K', 'D'], boll: ['收盤', '中軌', '上軌', '下軌'] }
for (const panel of INDICATOR_PANELS) {
  const { option, list } = series(longDaily, panel.id)
  const names = list.map((item) => item.name)
  check(names.slice(0, 7).join() === '日K,MA5,MA10,MA20,MA60,MA120,成交量', `${panel.id}: K line, five MAs and volume`)
  check(names.slice(7).join() === expectedIndicators[panel.id].join(), `${panel.id}: indicator series ${names.slice(7).join()}`)
  check(list.slice(7).every((item) => item.xAxisIndex === 2), `${panel.id}: indicator series sit on the third grid`)
  const zoom = option.dataZoom as Array<{ xAxisIndex: number[] }>
  check(zoom.every((item) => item.xAxisIndex.join() === '0,1,2'), `${panel.id}: dataZoom drives all three grids`)
  check(JSON.stringify(option.axisPointer).includes('"xAxisIndex":"all"'), `${panel.id}: crosshair links every x axis`)
}
const { list: daily } = series(longDaily, 'rsi')
check(daily[0].itemStyle?.color === theme.up && daily[0].itemStyle?.color0 === theme.down, 'candles use up/down tokens')
check(MA_LINES.every((line, index) => daily[index + 1].lineStyle?.color === theme[line.color]), 'MA lines use their fixed tokens')
const rsiRefs = JSON.stringify((daily[7] as unknown as { markLine: unknown }).markLine)
check(rsiRefs.includes('"yAxis":30') && rsiRefs.includes('"yAxis":70') && rsiRefs.includes(theme.subtle) && rsiRefs.includes('dashed'), 'RSI reference lines 30/70 dashed subtle')
const kdRefs = JSON.stringify((series(longDaily, 'kd').list[7] as unknown as { markLine: unknown }).markLine)
check(kdRefs.includes('"yAxis":20') && kdRefs.includes('"yAxis":80'), 'KD reference lines 20/80')
const volume = daily[6].data as Array<{ itemStyle: { opacity: number } } | '-'>
check(volume.every((item) => item !== '-' && item.itemStyle.opacity === 0.4), 'volume bars are 60% transparent')
const hidden = series(longDaily, 'macd', new Set<MaField>(['ma20'])).list.map((item) => item.name)
check(hidden.slice(0, 3).join() === '日K,MA20,成交量', 'unchecked MAs are not drawn')
check(series(insufficient, 'macd').list.every((item) => item.xAxisIndex !== 2), 'an empty panel draws no indicator series')
const gapCandles = series(suspended, 'rsi').list[0].data as unknown[]
check(JSON.stringify(gapCandles[30]) === '["-","-","-","-"]' && JSON.stringify(gapCandles[39]) === '["-","-","-","-"]', 'suspended days draw no candle')
check(series(weekly, 'kd').list[0].name === '週K', 'weekly series is labelled 週K')
const zoomDefault = defaultZoom(250)
check(Math.abs(zoomDefault.start - 52) < 1e-9 && zoomDefault.end === 100, 'first view shows the latest 120 of 250 bars')

// ---- rendered panel states ----
const render = (data: StockBarsResponse, interval: 'day' | 'week' = 'day') => renderToStaticMarkup(<StockBarsChart interval={interval} onIntervalChange={() => undefined} data={data} loading={false} error={null} />)
const insufficientMarkup = render(insufficient)
check(insufficientMarkup.includes('無資料') && insufficientMarkup.includes('日線不足 34 根，現有 20 根'), 'rendered MACD panel shows 無資料 with the reason')
check(insufficientMarkup.includes('資料 2026-09-20') && insufficientMarkup.includes('indicators/v1'), 'chart card shows its data date badge and formula version')
check(['MACD', 'RSI', 'KD', '布林'].every((label) => insufficientMarkup.includes(`>${label}</button>`)), 'four indicator tabs are rendered')
check(MA_LINES.every((line) => insufficientMarkup.includes(`ma-swatch-${line.color}`)), 'five MA toggles are rendered')
check(render(notComputed).includes('指標尚未計算'), 'rendered not_computed state')
const weeklyMarkup = render(weekly, 'week')
check(weeklyMarkup.includes('aria-selected="true"') && weeklyMarkup.includes('週線不足 34 根，現有 3 根'), 'rendered weekly panel')
const loadingMarkup = renderToStaticMarkup(<StockBarsChart interval="day" onIntervalChange={() => undefined} data={undefined} loading error={null} />)
check(loadingMarkup.includes('aria-busy="true"') && loadingMarkup.includes('skeleton'), 'loading shows a skeleton')
const emptyChart = renderToStaticMarkup(<StockBarsChart interval="day" onIntervalChange={() => undefined} data={barsResponse([])} loading={false} error={null} />)
check(emptyChart.includes('來源未提供日線') && emptyChart.includes('資料日期待核實'), 'no bars → empty state and pending date badge')

