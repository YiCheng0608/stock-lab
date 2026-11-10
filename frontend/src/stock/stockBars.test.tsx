import { renderToStaticMarkup } from 'react-dom/server'

import { StockBarsChart } from './StockBarsChart'
import { StockCutoffControl, cutoffSubmission } from './StockCutoffControl'
import { StockQuoteLine, tradingHaltLabel } from './StockHeader'
import {
  CHART_THEME_TOKENS,
  INDICATOR_PANELS,
  MA_LINES,
  STOCK_BARS_LIMIT,
  buildBarsChartOption,
  compactCount,
  formatBarVolume,
  volumeKind,
  sourceName,
  sourcesLabel,
  chartLayout,
  BAR_RANGES,
  DEFAULT_BARS_RANGE,
  STOCK_BARS_MAX_LIMIT,
  barsBasis,
  needsMoreBars,
  preferChromeInputPath,
  rangeCutoff,
  viewFromZoomEvent,
  zoomForView,
  fieldsState,
  formatBarsTooltip,
  formatSignedPercent,
  formatSignedPrice,
  formatTaipeiDateTime,
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
import type { StockBarsResponse, TradingHalt } from '../types'

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
check(nullReasonText('synthetic_index', { interval: 'day' }) === '指數只有收盤價，高低點與成交量不計算', 'synthetic index reason text (Issue 394)')
check(nullReasonText('missing_ohlc', { interval: 'day' }) === '來源有一天未提供開高低，高低點不計算' && nullReasonText('missing_volume', { interval: 'day' }) === '來源有一天未提供成交量，不計算', 'index days without open/high/low or volume (Issue 552)')
// Volume units (Issue 552, PR 553 review): stocks in 張, an index in 億股, TX in 口; the close-only TAIEX rows unverified.
check(volumeKind(['twse']) === 'lots' && volumeKind(['twse_index_ohlcv', 'tpex_index_ohlcv']) === 'index_shares' && volumeKind(['taifex_daily_futures']) === 'contracts' && volumeKind(['twse_index']) === 'unverified' && volumeKind(['twse', 'twse_index_ohlcv']) === 'unverified', 'volumeKind by source')
check(formatBarVolume({ ...tradedBar('2026-11-06', 39701.64, 1), volume: 19_339_729_647, source: 'twse_index_ohlcv' }) === '193.40' && formatBarVolume({ ...tradedBar('2026-11-06', 39786, 1), volume: 143277, source: 'taifex_daily_futures' }) === '143,277' && formatBarVolume({ ...tradedBar('2026-11-06', 304, 1), volume: null, source: 'tpex_index_ohlcv' }) === '', 'formatBarVolume: 億股, 口, empty without a volume')
// TX from the website futDataDown history (Issue 590; every production TX row since #563): 臺灣期貨交易所 and 口, alone or mixed with the OpenAPI rows.
check(sourceName('taifex_futdatadown') === '臺灣期貨交易所' && sourceName('taifex_daily_futures') === '臺灣期貨交易所' && sourcesLabel(['taifex_futdatadown', 'taifex_daily_futures']) === '臺灣期貨交易所', 'sourceName: both TX sources are TAIFEX')
check(volumeKind(['taifex_futdatadown']) === 'contracts' && volumeKind(['taifex_futdatadown', 'taifex_daily_futures']) === 'contracts' && volumeKind(['taifex_futdatadown', 'twse']) === 'unverified', 'volumeKind: futDataDown TX in 口, mixed TX sources too')
check(formatBarVolume({ ...tradedBar('2026-11-06', 39786, 1), volume: 143277, source: 'taifex_futdatadown' }) === '143,277' && formatBarVolume({ ...tradedBar('2026-11-06', 39786, 1), volume: 98765, source: null, sources: ['taifex_futdatadown', 'taifex_daily_futures'] }) === '98,765', 'formatBarVolume: futDataDown TX in 口')
// FinMind's US indexes (Issue 568): member shares in 億股 like the Taiwan indexes; SOX has no volume (NULL), so empty.
check(volumeKind(['finmind_us_index']) === 'index_shares' && volumeKind(['fred_close']) === 'unverified' && volumeKind(['finmind_us_index', 'twse']) === 'unverified', 'volumeKind: FinMind US indexes in 億股')
check(formatBarVolume({ ...tradedBar('2026-11-06', 7376.86, 1), volume: 5_701_900_000, source: 'finmind_us_index' }) === '57.02' && formatBarVolume({ ...tradedBar('2026-11-06', 9390.25, 1), volume: null, source: 'finmind_us_index' }) === '', 'formatBarVolume: S&P 500 in 億股, SOX empty')
check(compactCount(9999) === '9,999' && compactCount(52_000) === '5.2萬' && compactCount(1_234_567) === '123.5萬' && compactCount(320_000_000) === '3.2億', 'volume axis labels fit the gutter (萬／億)')
check(priceDigits(39786, 'futures') === 0, 'TX is in whole points')
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
check(maNotes(notComputed, new Set<MaField>(['ma5']))[0] === 'MA5 指標尚未計算：2026/10/16 的指標尚未由批次計算', 'MA note for not_computed')

// ---- suspended day + missing calendar day ----
const suspended = suspendedWithGapDaily()
const dates = suspended.bars.map((bar) => bar.date)
check(dates.length === 40 && !dates.includes('2026-09-07') && dates.includes('2026-09-08'), 'the missing calendar day is not filled in')
const suspendedState = indicatorPanelState(suspended, 'rsi')
check(suspendedState.kind === 'chart' && suspendedState.note === `${dates[39].replaceAll('-', '/')} RSI無資料：停牌，當日不計算`, `latest suspended bar keeps the chart and explains the gap: ${JSON.stringify(suspendedState)}`)
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
check(upMarkup.includes('資料 2026/10/16') && upMarkup.includes('臺灣證券交易所'), 'header shows data date badge and source')
// #475: the bars API says the stock had no close on the previous verified session; the older row (10/14, a gap
// day between) does not stand in, and the header uses the candidate page's words.
const gapBars = [tradedBar('2026-10-14', 98.5, 1), tradedBar('2026-10-16', 100, 2)]
const latestChange = (status: string, day = '2026-10-16') => ({ trading_date: day, close: 100, change: null, change_pct: null, change_status: status, source: 'twse' })
const noPreviousQuote = stockQuote(gapBars, 'stock', latestChange('no_previous_close'))
check(noPreviousQuote.change === null && noPreviousQuote.changePct === null && noPreviousQuote.noChange === '前一交易日無收盤' && noPreviousQuote.close === 100, `no previous close: ${JSON.stringify(noPreviousQuote)}`)
const noPreviousMarkup = renderToStaticMarkup(<StockQuoteLine bars={gapBars} latestChange={latestChange('no_previous_close')} />)
check(noPreviousMarkup.includes('前一交易日無收盤') && noPreviousMarkup.includes('tone-flat') && !noPreviousMarkup.includes('+1.5') && !noPreviousMarkup.includes('漲跌待核實'), `no previous close markup: ${noPreviousMarkup}`)
const firstDayMarkup = renderToStaticMarkup(<StockQuoteLine bars={[tradedBar('2026-10-16', 100, 2)]} latestChange={latestChange('first_trading_day')} />)
check(firstDayMarkup.includes('掛牌首日') && !firstDayMarkup.includes('前一交易日無收盤') && !firstDayMarkup.includes('漲跌待核實'), `first trading day markup: ${firstDayMarkup}`)
// Another day's status, or a status that names no cause, leaves the bars rule alone.
check(stockQuote(gapBars, 'stock', latestChange('no_previous_close', '2026-10-15')).change === 1.5, 'a status for another day does not apply')
check(stockQuote(gapBars, 'stock', latestChange('unverified')).change === 1.5 && stockQuote(gapBars, 'stock', latestChange('known')).noChange === null, 'unverified and known keep the bars rule')

// Issue 582: on a session an official stop of trading covers, the header says why the close is older than the market.
const halt: TradingHalt = { reason: 'capital_reduction', reason_label: '減資換發新股', reason_detail: '退還股款', halt_start: '2026-11-05', resume_date: '2026-11-16', last_trade_date: '2026-11-04', exchange: 'TWSE', source: 'twse_twtauu', endpoint: 'TWTAUU', data_as_of: '2026-11-09', as_of: '2026-11-09' }
check(tradingHaltLabel(halt) === '停止買賣中（減資換發新股，預計 2026/11/16 恢復）', `halt label: ${tradingHaltLabel(halt)}`)
check(tradingHaltLabel(null) === null && tradingHaltLabel(undefined) === null, 'no stop, no label')
const haltMarkup = renderToStaticMarkup(<StockQuoteLine bars={[tradedBar('2026-11-03', 57.3, 1), tradedBar('2026-11-04', 56.7, 2)]} halt={halt} />)
check(haltMarkup.includes('badge-warning stock-header-halt') && haltMarkup.includes('停止買賣中（減資換發新股，預計 2026/11/16 恢復）') && haltMarkup.includes('資料 2026/11/04'), `halt markup: ${haltMarkup}`)
check(!upMarkup.includes('停止買賣中'), 'a stock that trades has no stop badge')

// ---- weekly series ----
const weekly = weeklySeries()
const weeklyMacd = indicatorPanelState(weekly, 'macd')
check(weeklyMacd.kind === 'empty' && weeklyMacd.reason === '週線不足 34 根，現有 3 根', `weekly reason counts weeks: ${JSON.stringify(weeklyMacd)}`)
const weeklyTooltip = formatBarsTooltip(weekly, 2, 'macd', allMa, 0)
check(weeklyTooltip.includes('2026/10/12～2026/10/16（5 個交易日）') && weeklyTooltip.includes('成交量（張） 105,000'), `weekly tooltip: ${weeklyTooltip}`)
check(stockQuote(weekly.bars).sources.join() === 'twse', 'weekly rows read their sources list')

// ---- chart option: K line, volume, five MAs, four indicator panels ----
const layout = chartLayout(320)
check(layout.indicator.height === Math.round(layout.main.height * 0.35), 'indicator panel is 35% of the main chart')
const series = (response: StockBarsResponse, panel: IndicatorPanelId, visible: ReadonlySet<MaField> = allMa) => {
  const option = buildBarsChartOption(response, { panel, panelState: indicatorPanelState(response, panel), visibleMa: visible, theme, layout, zoom: zoomForView(response, { range: DEFAULT_BARS_RANGE }), digits: 2 })
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

// ---- rendered panel states ----
const render = (data: StockBarsResponse, interval: 'day' | 'week' = 'day') => renderToStaticMarkup(<StockBarsChart interval={interval} onIntervalChange={() => undefined} data={data} loading={false} error={null} />)
const insufficientMarkup = render(insufficient)
check(insufficientMarkup.includes('無資料') && insufficientMarkup.includes('日線不足 34 根，現有 20 根'), 'rendered MACD panel shows 無資料 with the reason')
check(insufficientMarkup.includes('資料 2026/09/20') && insufficientMarkup.includes('indicators/v1'), 'chart card shows its data date badge and formula version')
check(insufficientMarkup.includes('日線批次計算於 2026/10/16 18:00（台灣時間）'), 'naive UTC computed_at is shown in Taiwan time')
// The basis label follows the API's current basis; the basis before Issue 394 is not explained as the current one.
check(insufficientMarkup.includes('K 線為原始價；均線與指標以各根資料日的原始價為基準換算前期除權息'), 'current price basis is explained')
const oldBasis = render({ ...insufficient, indicators: { ...insufficient.indicators, price_basis: 'as_of_date_raw_basis' } })
check(oldBasis.includes('價格基準待核實') && !oldBasis.includes('K 線為原始價'), 'an older price basis reads 待核實')
check(formatTaipeiDateTime('2026-10-17T11:39:37.362391') === '2026/10/17 19:39' && formatTaipeiDateTime('2026-10-17T23:30:00+08:00') === '2026/10/17 23:30', 'computed_at time zone handling')
check(formatTaipeiDateTime(null) === null && formatTaipeiDateTime('not a date') === null, 'missing or invalid computed_at')
check(['MACD', 'RSI', 'KD', '布林'].every((label) => insufficientMarkup.includes(`>${label}</button>`)), 'four indicator tabs are rendered')
check(MA_LINES.every((line) => insufficientMarkup.includes(`ma-swatch-${line.color}`)), 'five MA toggles are rendered')
check(render(notComputed).includes('指標尚未計算'), 'rendered not_computed state')
const weeklyMarkup = render(weekly, 'week')
check(weeklyMarkup.includes('aria-selected="true"') && weeklyMarkup.includes('週線不足 34 根，現有 3 根'), 'rendered weekly panel')
const loadingMarkup = renderToStaticMarkup(<StockBarsChart interval="day" onIntervalChange={() => undefined} data={undefined} loading error={null} />)
check(loadingMarkup.includes('aria-busy="true"') && loadingMarkup.includes('skeleton'), 'loading shows a skeleton')
const emptyChart = renderToStaticMarkup(<StockBarsChart interval="day" onIntervalChange={() => undefined} data={barsResponse([])} loading={false} error={null} />)
check(emptyChart.includes('來源未提供日線') && emptyChart.includes('資料日期未提供'), 'no bars → empty state and no-date badge')

// ---- #300 研究截止日期 (DESIGN_SYSTEM §4 手機第一屏): one toggle line on phones, open when a cutoff is applied ----
const latestCutoff = renderToStaticMarkup(<StockCutoffControl asOf="" onApply={() => undefined} />)
check(latestCutoff.includes('class="cutoff-panel"') && latestCutoff.includes('aria-expanded="false"') && latestCutoff.includes('研究截止日期：最新資料 ▸'), `no cutoff: the panel starts folded and names 最新資料: ${latestCutoff.slice(0, 200)}`)
check(latestCutoff.indexOf('cutoff-toggle') < latestCutoff.indexOf('<form id="stock-cutoff-form" class="overview-cutoff-control"') && latestCutoff.includes('套用截止'), 'the toggle precedes the unchanged cutoff form')
const appliedCutoff = renderToStaticMarkup(<StockCutoffControl asOf="2026-10-20" onApply={() => undefined} />)
check(appliedCutoff.includes('class="cutoff-panel open"') && appliedCutoff.includes('aria-expanded="true"') && appliedCutoff.includes('研究截止日期：2026/10/20 ▾') && appliedCutoff.includes('value="2026-10-20"'), 'an applied cutoff starts open and shows its date')
// #463 (UI_COPY_SPEC §8.2 研究截止日期): say what the cutoff does and which day 「最新資料」 is.
const CUTOFF_MEANING = '只用這一天收盤（含）以前的資料判斷研究條件、研究動作與候選，用來回看當時會怎麼判斷'
const latestDated = renderToStaticMarkup(<StockCutoffControl asOf="" effectiveDate="2026-11-03" onApply={() => undefined} />)
check(latestDated.includes('研究截止日期：最新資料（2026/11/03） ▸'), `no cutoff: the toggle names the actual data day: ${latestDated.slice(0, 240)}`)
check(latestDated.includes(CUTOFF_MEANING) && latestDated.includes('空白或按「最新資料」時用 2026/11/03（該股最近一個有資料的交易日）'), 'the form explains the cutoff and the latest data day')
check(latestDated.includes('頁首收盤、K 線與新聞時間線不受影響'), 'the form still says the header, K-line and news are unaffected')
check(latestCutoff.includes(CUTOFF_MEANING) && !latestCutoff.includes('（該股最近一個有資料的交易日）'), 'without a known day the date part is left out')
// #492: the date field starts on the latest data day instead of blank, and cannot go past it; applying it unchanged
// keeps 「最新資料」 (no as_of in the URL), any other day is applied as the cutoff.
const cutoffInput = (markup: string) => /<input id="stock-cutoff"[^>]*>/.exec(markup)?.[0] ?? ''
check(cutoffInput(latestDated).includes('value="2026-11-03"') && cutoffInput(latestDated).includes('max="2026-11-03"'), `no cutoff: the field shows and caps at the latest data day: ${cutoffInput(latestDated)}`)
const latestStamped = renderToStaticMarkup(<StockCutoffControl asOf="" effectiveDate="2026-11-03T13:30:00+08:00" onApply={() => undefined} />)
check(cutoffInput(latestStamped).includes('value="2026-11-03"') && cutoffInput(latestStamped).includes('max="2026-11-03"'), `a timestamped latest day fills the field with its calendar day: ${cutoffInput(latestStamped)}`)
check(cutoffInput(appliedCutoff).includes('value="2026-10-20"'), 'an applied cutoff shows as_of in the field')
const appliedWithLatest = renderToStaticMarkup(<StockCutoffControl asOf="2026-10-20" effectiveDate="2026-11-03" onApply={() => undefined} />)
check(cutoffInput(appliedWithLatest).includes('value="2026-10-20"'), 'as_of wins over the latest data day in the field')
check(cutoffInput(latestCutoff).includes('value=""') && !cutoffInput(latestCutoff).includes('max='), 'without a known day the field stays empty and uncapped')
check(cutoffSubmission('2026-11-03', '2026-11-03') === '', 'applying the unchanged latest day keeps 最新資料 (no as_of)')
check(cutoffSubmission('2026-10-31', '2026-11-03') === '2026-10-31', 'applying a changed day sets it as the cutoff')
check(cutoffSubmission('', '2026-11-03') === '' && cutoffSubmission('2026-10-20', null) === '2026-10-20', 'a cleared field is 最新資料; without a known latest day the value is applied as typed')

// ---- #600 display range: 1M／3M／6M／1Y／全部 set the dataZoom window, kept across 日K／週K, cleared by a manual zoom ----
const isoDay = (time: number) => new Date(time).toISOString().slice(0, 10)
// Weekdays up to 2026-11-10 (a Tuesday), as the API returns the latest `limit` of them.
const weekdays = (count: number, last = '2026-11-10') => {
  const days: string[] = []
  for (let time = Date.parse(`${last}T00:00:00Z`); days.length < count; time -= 86_400_000) {
    const weekday = new Date(time).getUTCDay()
    if (weekday !== 0 && weekday !== 6) days.unshift(isoDay(time))
  }
  return days
}
const dailyOf = (days: readonly string[], limit = 250) => ({ ...barsResponse(days.map((day, index) => tradedBar(day, 100 + (index % 9), index + 1))), limit })
// A year of weekdays and a little more (the real 250 trading days reach back about a year and two weeks).
const fullPage = dailyOf(weekdays(262), 262)
const LAST = fullPage.bars.length - 1
const weeklyOf = (count: number) => {
  // Week rows end on the Friday (the last week ends 2026-11-10, its latest trading day so far).
  const bars = Array.from({ length: count }, (_, index) => {
    const weekStart = isoDay(Date.parse('2026-11-09T00:00:00Z') - (count - 1 - index) * 7 * 86_400_000)
    const weekEnd = index === count - 1 ? '2026-11-10' : isoDay(Date.parse(`${weekStart}T00:00:00Z`) + 4 * 86_400_000)
    return tradedBar(weekEnd, 600 + index, index + 1, { week_start: weekStart, week_end: weekEnd, trading_days: 5 })
  })
  return barsResponse(bars, 'week')
}
const weeklyPage = weeklyOf(110)
const firstOnOrAfter = (response: StockBarsResponse, day: string) => response.bars.findIndex((bar) => bar.date >= day)
const windowOf = (response: StockBarsResponse, view: Parameters<typeof zoomForView>[1]) => zoomForView(response, view) as { startValue: number; endValue: number }

check(BAR_RANGES.map((item) => item.label).join() === '1M,3M,6M,1Y,全部' && DEFAULT_BARS_RANGE === '6m', 'five range buttons, 6M by default')
check(rangeCutoff('2026-11-10', '1m') === '2026-10-10' && rangeCutoff('2026-11-10', '3m') === '2026-08-10' && rangeCutoff('2026-11-10', '6m') === '2026-05-10' && rangeCutoff('2026-11-10', '1y') === '2025-11-10', 'range cutoffs move back whole calendar months')
check(rangeCutoff('2026-03-31', '1m') === '2026-02-28' && rangeCutoff('2024-02-29', '1y') === '2023-02-28', 'a cutoff clamps to the month end')
check(rangeCutoff('2026-11-10', 'all') === null && rangeCutoff(undefined, '1m') === null && rangeCutoff('not a date', '3m') === null, '全部 and an unknown latest day have no cutoff')

// Each range on a full daily page: from the first bar on or after the cutoff to the latest bar.
const expectedStart: Record<string, string> = { '1m': '2026-10-12', '3m': '2026-08-10', '6m': '2026-05-11', '1y': '2025-11-10' }
for (const item of BAR_RANGES) {
  const zoom = windowOf(fullPage, { range: item.id })
  const cutoff = rangeCutoff('2026-11-10', item.id)
  const expected = cutoff == null ? 0 : firstOnOrAfter(fullPage, cutoff)
  check(zoom.startValue === expected && zoom.endValue === LAST, `${item.label}: window ${JSON.stringify(zoom)}, expected start ${expected}`)
  if (cutoff) check(fullPage.bars[zoom.startValue].date === expectedStart[item.id] && (zoom.startValue === 0 || fullPage.bars[zoom.startValue - 1].date < cutoff), `${item.label}: starts at ${fullPage.bars[zoom.startValue].date}`)
}
check(windowOf(fullPage, { range: '1m' }).endValue - windowOf(fullPage, { range: '1m' }).startValue + 1 === 22, '1M on daily bars is about a month of trading days')
const option1m = buildBarsChartOption(fullPage, { panel: 'macd', panelState: indicatorPanelState(fullPage, 'macd'), visibleMa: allMa, theme, layout, zoom: zoomForView(fullPage, { range: '1m' }), digits: 2 })
const optionZoom = option1m.dataZoom as Array<Record<string, unknown>>
check(optionZoom.length === 2 && optionZoom.every((item) => item.startValue === firstOnOrAfter(fullPage, '2026-10-10') && item.endValue === LAST && item.start === undefined), `both dataZoom components take the bar window: ${JSON.stringify(optionZoom.map((item) => [item.startValue, item.endValue]))}`)

// Fewer bars than the range: everything is shown, nothing throws.
const short = dailyOf(weekdays(20))
for (const item of BAR_RANGES.filter((range) => range.id !== '1m')) {
  const zoom = windowOf(short, { range: item.id })
  check(zoom.startValue === 0 && zoom.endValue === 19, `${item.label} on 20 bars shows all of them: ${JSON.stringify(zoom)}`)
}
check(JSON.stringify(zoomForView(barsResponse([]), { range: '1y' })) === '{"startValue":0,"endValue":0}', 'no bars: an empty window, no error')
const someManual = viewFromZoomEvent(fullPage, { start: 10, end: 20 })
check(someManual !== null && JSON.stringify(zoomForView(barsResponse([]), someManual)) === '{"startValue":0,"endValue":0}', 'a manual window on no bars: empty, no error')
check(render(short).includes('最近 20 根日線'), 'a short series renders with the range selected')

// 日K → 週K keeps the range: the same cutoff picks the week that holds it.
for (const item of BAR_RANGES) {
  const zoom = windowOf(weeklyPage, { range: item.id })
  const cutoff = rangeCutoff('2026-11-10', item.id)
  check(zoom.endValue === 109 && zoom.startValue === (cutoff == null ? 0 : firstOnOrAfter(weeklyPage, cutoff)), `weekly ${item.label}: ${JSON.stringify(zoom)}`)
  if (cutoff) {
    const week = weeklyPage.bars[zoom.startValue]
    check((week.week_start ?? '') <= cutoff || week.date >= cutoff, `weekly ${item.label}: the first week (${week.week_start}～${week.date}) holds or follows ${cutoff}`)
  }
}
check(windowOf(weeklyPage, { range: '3m' }).endValue - windowOf(weeklyPage, { range: '3m' }).startValue + 1 === 14, '3M on weekly bars is 14 weeks')

// A manual zoom: no button is selected; on the same bars ECharts' percents stay, on the other interval its dates map.
const manual = viewFromZoomEvent(fullPage, { batch: [{ start: 50, end: 80 }] })
check(manual !== null && manual.range === null, 'a dataZoom event clears the selected range')
if (manual && manual.range === null) {
  check(manual.basis === barsBasis(fullPage) && manual.from === fullPage.bars[Math.ceil(LAST * 0.5)].date && manual.to === fullPage.bars[Math.floor(LAST * 0.8)].date, `manual window dates: ${manual.from}～${manual.to}`)
  check(JSON.stringify(zoomForView(fullPage, manual)) === '{"start":50,"end":80}', 'the same bars keep the dragged percents (no snapping while dragging)')
  const onWeekly = windowOf(weeklyPage, manual)
  const firstWeek = weeklyPage.bars[onWeekly.startValue]
  const lastWeek = weeklyPage.bars[onWeekly.endValue]
  check((firstWeek.week_start ?? '') <= manual.from && firstWeek.date >= manual.from, `the manual start lands in its week: ${firstWeek.week_start}～${firstWeek.date} holds ${manual.from}`)
  check((lastWeek.week_start ?? '') <= manual.to && lastWeek.date >= manual.to, `the manual end lands in its week: ${lastWeek.week_start}～${lastWeek.date} holds ${manual.to}`)
  const weeklyAll = viewFromZoomEvent(weeklyPage, { start: 0, end: 100 })
  check(weeklyAll !== null, 'a weekly zoom event gives a manual view')
  if (weeklyAll) {
    const back = windowOf(fullPage, weeklyAll)
    check(back.startValue === Math.max(0, firstOnOrAfter(fullPage, weeklyPage.bars[0].week_start ?? '')) && back.endValue === LAST, `週K → 日K maps the weekly window back by its first week start: ${JSON.stringify(back)}`)
  }
  check(!needsMoreBars(fullPage, manual), 'a manual zoom asks for nothing')
}
check(viewFromZoomEvent(fullPage, { start: 'x' }) === null && viewFromZoomEvent(fullPage, null) === null, 'an event without percents changes nothing')
const pressed = (markup: string) => [...markup.matchAll(/<button type="button" class="badge filter-chip( filter-chip-selected)?" aria-pressed="(true|false)">([^<]+)<\/button>/g)].map((match) => `${match[3]}:${match[2]}`)
check(pressed(render(fullPage)).join() === '1M:false,3M:false,6M:true,1Y:false,全部:false', `range buttons render with 6M pressed: ${pressed(render(fullPage)).join()}`)
check(pressed(render(weeklyPage, 'week')).join() === '1M:false,3M:false,6M:true,1Y:false,全部:false', 'the weekly chart has the same buttons')

// 全部 (or a range before the first loaded bar) asks for more only when the page is full and under the API maximum.
check(STOCK_BARS_MAX_LIMIT === 1500, 'the longer request uses the bars API maximum (backend app.stock_bars.MAX_LIMIT)')
check(needsMoreBars(fullPage, { range: 'all' }) && !needsMoreBars(fullPage, { range: '1y' }) && !needsMoreBars(fullPage, { range: '6m' }), '全部 asks for more; 1Y fits in a page that reaches back a year')
check(needsMoreBars(dailyOf(weekdays(200), 200), { range: '1y' }), 'a range reaching before a full page asks for more')
check(!needsMoreBars(short, { range: 'all' }) && !needsMoreBars(weeklyPage, { range: 'all' }), 'a page shorter than its limit is the whole history')
check(!needsMoreBars({ ...fullPage, limit: STOCK_BARS_MAX_LIMIT, count: STOCK_BARS_MAX_LIMIT }, { range: 'all' }), 'the API maximum is not asked again')

// Crosshair on touch (#600 headless Edge check): the tooltip stays inside the chart, and a sideways drag reaches the chart.
declare const require: (id: string) => unknown
declare const __dirname: string
const chartCss = (require('node:fs') as { readFileSync(file: string, encoding: 'utf8'): string }).readFileSync((require('node:path') as { join(...parts: string[]): string }).join(__dirname, '..', 'styles.css'), 'utf8')
const tooltip = option1m.tooltip as { confine?: boolean; trigger?: string; axisPointer?: { type?: string } }
check(tooltip.confine === true && tooltip.trigger === 'axis' && tooltip.axisPointer?.type === 'cross', 'the crosshair tooltip is confined to the chart')
check(/\.chart-stage \{[^}]*touch-action: pan-y/.test(chartCss), 'the chart takes sideways drags (touch-action: pan-y)')
// Chromium Edge ("Edg/", which zrender takes for old Edge) gets Chrome's input path; other browsers are left alone.
const edgeTouch = { browser: { newEdge: true }, touchEventsSupported: false, pointerEventsSupported: true }
check(preferChromeInputPath(edgeTouch, true) && edgeTouch.touchEventsSupported && !edgeTouch.pointerEventsSupported, 'Chromium Edge with touch listens to touch events')
const edgeMouse = { browser: { newEdge: true }, touchEventsSupported: false, pointerEventsSupported: true }
check(preferChromeInputPath(edgeMouse, false) && !edgeMouse.touchEventsSupported && !edgeMouse.pointerEventsSupported, 'Chromium Edge without touch listens to mouse events, as Chrome')
const chrome = { browser: { newEdge: false }, touchEventsSupported: true, pointerEventsSupported: false }
check(!preferChromeInputPath(chrome, true) && chrome.touchEventsSupported && !chrome.pointerEventsSupported, 'Chrome is not changed')
const oldIe = { browser: { newEdge: false }, touchEventsSupported: false, pointerEventsSupported: true }
check(!preferChromeInputPath(oldIe, true) && oldIe.pointerEventsSupported, 'IE11 and EdgeHTML keep pointer events')
