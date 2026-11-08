import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import * as AppModule from '../App'
import { MAIN_NAV } from '../components/Navbar'
import type { Dashboard, ForeignIndex, MarketOverview, StockBarRow, StockBarsResponse } from '../types'
import { overviewBoth, overviewNone, overviewTwseOnly } from '../today/today.fixtures'
import { CLOSE_ONLY_NOTE, STOCK_BARS_LIMIT, axisDigits, buildBarsChartOption, chartLayout, isCloseOnlySeries, priceDigits, readChartTheme } from '../stock/stockBars'
import { MarketChartView, MarketOverviewPanel, MarketOverviewView, UsChartFooter, UsIndexPanel } from './MarketViews'
import { MarketPage } from './MarketPage'
import { FRED_ATTRIBUTION, MARKET_CHARTS, TAIEX, TAIFEX_ATTRIBUTION, US_INDEXES, collectedSinceText, foreignLatestDate, futuresLatestText, marketOverviewNotes, summaryItems, usChartSpec } from './marketOverview'

const expectedText = (overview: MarketOverview) => `資料 ${(foreignLatestDate(overview) ?? '').replace(/-/g, '/')}`

// The frontend ships no Node typings; scripts/ci-test.cjs runs this module under Node, so declare what it uses.
declare const require: (id: string) => unknown
declare const __dirname: string
const fs = require('node:fs') as { readFileSync(file: string, encoding: 'utf8'): string }
const path = require('node:path') as { join(...parts: string[]): string }

// 大盤 page (/market, Issue 549/552; PRODUCT_SPEC §2, DESIGN_SYSTEM §4/§5/§6, UI_COPY_SPEC §11): navigation, the page with
// data (the overview and the TAIEX, TPEx and TX daily K charts), and the states without data. Failures are listed together.
const failures: string[] = []
let checks = 0
const check = (condition: boolean, message: string) => { checks++; if (!condition) failures.push(message) }
const text = (html: string) => html.replace(/<[^>]+>/g, ' ').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/\s+/g, ' ')
const count = (html: string, part: string) => html.split(part).length - 1
const slice = (markup: string, start: string, end: string) => {
  const from = markup.indexOf(start)
  return from < 0 ? '' : markup.slice(from, markup.indexOf(end, from + start.length))
}

function render(location: string, element: ReactElement, client = new QueryClient()): string {
  try {
    return renderToStaticMarkup(<QueryClientProvider client={client}><StaticRouter location={location}>{element}</StaticRouter></QueryClientProvider>)
  } catch (error) {
    checks++
    failures.push(`${location}: render failed (${error instanceof Error ? error.message.split('\n')[0] : String(error)})`)
    return ''
  }
}

// Real daily K bars (Issue 552): open below the close, a range around both, volume in shares.
const bar = (date: string, close: number | null, extra: Partial<StockBarRow> = {}): StockBarRow =>
  ({ date, open: close == null ? null : close - 20, high: close == null ? null : close + 35.5, low: close == null ? null : close - 60.25, close, volume: 19_339_729_647, source: 'twse_index_ohlcv', is_suspended: false, bar_count: null, reasons: {}, ...extra })

function taiexBars(rows: StockBarRow[], extra: Partial<StockBarsResponse> = {}): StockBarsResponse {
  return {
    instrument: { id: 9, exchange: 'TWSE', symbol: 'TAIEX', name: '發行量加權股價指數', instrument_type: 'index' },
    interval: 'day',
    limit: STOCK_BARS_LIMIT,
    count: rows.length,
    data_as_of: rows.length ? rows[rows.length - 1].date : null,
    sources: [...new Set(rows.map((row) => row.source ?? ''))].filter(Boolean),
    indicators: { formula_version: 'indicators/v1', price_basis: 'as_of_date_raw_basis/v2', parameters: {}, required_bars: {}, fields: [], source: 'technical_indicators', computed_at: null },
    bars: rows,
    ...extra,
  }
}

const dateOf = (i: number) => new Date(Date.UTC(2026, 8, 1) + i * 86400000).toISOString().slice(0, 10)
const days = Array.from({ length: 40 }, (_, i) => bar(dateOf(i), 45000 + i * 25.5))
days[days.length - 1] = bar('2026-10-22', 46041.43)
const fullBars = taiexBars(days)
const tpexBars: StockBarsResponse = {
  ...taiexBars(days.map((row, i) => ({ ...row, open: 300 + i, high: 302 + i, low: 299 + i, close: 301 + i, volume: 1_069_692_000, source: 'tpex_index_ohlcv' }))),
  instrument: { id: 10, exchange: 'TPEx', symbol: 'TPEX', name: '櫃買指數', instrument_type: 'index' },
}
// TX from the first collect only: 12 sessions, so fewer than the limit (UI_COPY_SPEC §11 「自 … 起收集」).
const txRows = Array.from({ length: 12 }, (_, i) => bar(dateOf(28 + i), 46000 + i * 10, { open: 45990 + i * 10, high: 46100 + i * 10, low: 45900 + i * 10, volume: 143277, source: 'taifex_daily_futures', contract_month: i < 6 ? '202609' : '202610', open_interest: 125000 + i, settlement_price: 45995 + i * 10 }))
const txBars: StockBarsResponse = { ...taiexBars(txRows), instrument: { id: 11, exchange: 'TAIFEX', symbol: 'TX', name: '臺股期貨近月', instrument_type: 'futures' } }

// ---- navigation: 大盤 right after 今日可買, the /market route renders this page ----
const nav = MAIN_NAV.map((item) => `${item.to} ${item.label}`)
check(nav[0] === '/ 今日可買' && nav[1] === '/market 大盤' && nav.length === 7, `MAIN_NAV: 大盤 is second of seven, got ${JSON.stringify(nav)}`)
const routes = (AppModule as Record<string, unknown>).APP_ROUTES as ReadonlyArray<{ path: string; element: ReactElement }> | undefined
check(routes?.find((route) => route.path === '/market')?.element.type === MarketPage, '/market route renders MarketPage')
const App = (AppModule as Record<string, unknown>).default as () => ReactElement
const shell = render('/market', <App />)
check(!shell.includes('找不到此頁') && shell.includes('<h1>大盤</h1>'), `/market is not a 404 and its title is 大盤: ${text(shell).slice(0, 200)}`)
check(/<a[^>]*class="active"[^>]*href="\/market"[^>]*>大盤<\/a>|<a[^>]*href="\/market"[^>]*class="active"[^>]*>大盤<\/a>|aria-current="page"[^>]*href="\/market"|href="\/market"[^>]*aria-current="page"/.test(shell), '/market: the navbar marks 大盤 as the current page')

// ---- the page with data: overview first, then the TAIEX, TPEx and TX daily charts ----
const dashboard = { as_of: '2026-10-22', market_overview: overviewBoth() } as unknown as Dashboard
const client = new QueryClient()
client.setQueryData(['dashboard'], dashboard)
// The stock page's query key: /stocks/TWSE/TAIEX and /market share one cache entry.
client.setQueryData(['stock-bars', TAIEX.exchange, TAIEX.symbol, 'day'], fullBars)
client.setQueryData(['stock-bars', 'TPEx', 'TPEX', 'day'], tpexBars)
client.setQueryData(['stock-bars', 'TAIFEX', 'TX', 'day'], txBars)
const page = render('/market', <MarketPage />, client)
const pageText = text(page)
check(JSON.stringify(MARKET_CHARTS.map((spec) => `${spec.exchange}/${spec.symbol}`)) === '["TWSE/TAIEX","TPEx/TPEX","TAIFEX/TX"]', 'the three charts read the bars API of TAIEX, TPEX and TX')
const order = ['id="market-overview-title"', 'id="market-chart-title"', 'id="market-tpex-chart-title"', 'id="market-tx-chart-title"'].map((id) => page.indexOf(id))
check(order.every((at, i) => at > 0 && (i === 0 || at > order[i - 1])), `DESIGN_SYSTEM §4: 大盤概況 → 加權 → 櫃買 → 台指期, got ${order}`)
check(!page.includes('market-no-bars') && !pageText.includes('歷史日 K 尚未收集'), '櫃買 has its K line now, no 無資料 row')
check(!/大盤狀態/.test(pageText), 'no placeholder for 大盤狀態 (Issue 546) yet')
// Issue 547: 美股（前一交易日） after the TX chart; without foreign_indices every index says it has no data.
check(page.indexOf('id="market-us-title"') > page.indexOf('id="market-tx-chart-title"') && page.indexOf('id="market-tx-chart-title"') > 0, 'DESIGN_SYSTEM §4: 美股 comes after 台指期近月日線')
check(count(page, '無資料：尚未收集') === 4, `美股 without foreign_indices: four 無資料：尚未收集, got ${count(page, '無資料：尚未收集')}`)
const overviewPanel = slice(page, 'id="market-overview-title"', 'id="market-chart-title"')
for (const value of ['大盤概況', '資料 2026/10/22', '加權指數', '46,041.43', '-846.34（-1.81%）', '櫃買指數', '381.69', '-13.73（-3.47%）', '上市 9,334.37 集中市場總計', '上櫃 2,255.45 上櫃股票', '上市 上漲 247 · 下跌 756 · 平盤 74（3／5）', '上櫃 上漲 146 · 下跌 659 · 平盤 63（17／11）']) {
  check(text(overviewPanel).includes(value), `大盤概況: shows 「${value}」`)
}
check(count(overviewPanel, 'market-widget-dual') === 2 && !overviewPanel.includes('market-overview-more'), '大盤概況: four widgets, nothing folded on phones (the page is for the market)')
check(/class="market-widget-change[^"]*tone-down"/.test(overviewPanel), '大盤概況: a falling index change is green')
const explanation = text(slice(overviewPanel, '<details class="data-explanation"', '</details>'))
for (const line of ['來源：上市為臺灣證券交易所 MI_INDEX；上櫃為櫃買中心 tpex_mainborad_highlight', '成交金額範圍：上市為集中市場總計（含 ETF、權證等）；上櫃為上櫃股票', '櫃買指數漲跌幅依前一日收市指數計算', '紅色為上漲、綠色為下跌（台股慣例）']) {
  check(explanation.includes(line), `大盤概況 資料說明: 「${line}」, got ${explanation}`)
}
// The chart is the stock page's StockBarsChart (coordinator decision 6715021190): same tabs, indicator panels and
// synthetic-bar rules, so the real daily K bars of Issue 552 need no new view.
const chartPanel = slice(page, 'id="market-chart-title"', 'id="market-tpex-chart-title"')
check(page.includes('<h3 class="card-title" id="market-chart-title">加權指數日線</h3>') && page.includes('aria-labelledby="market-chart-title"'), '加權指數日線: the StockBarsChart card, titled for the index')
check(text(chartPanel).includes('資料 2026/10/22'), `加權指數日線: the last bar's date badge: ${text(chartPanel).slice(0, 160)}`)
check(chartPanel.includes('id="bars-interval-tab-day"') && chartPanel.includes('id="bars-interval-tab-week"') && text(chartPanel).includes('日K') && text(chartPanel).includes('週K'), '加權指數日線: the stock page period switch (日K／週K)')
check(chartPanel.includes('class="ma-toggles"') && chartPanel.includes('id="indicator-tab-macd"'), '加權指數日線: the stock page MA toggles and indicator panels')
check(text(chartPanel).includes('最近 40 根日線；缺日不補、停牌不畫 K 線'), '加權指數日線: the stock page chart meta')
for (const header of ['開（點）', '收（點）', 'MA5（點）']) check(text(chartPanel).includes(header), `資料表: an index is in 點 (「${header}」)`)
check(!text(chartPanel).includes('收（元）') && text(chartPanel).includes('單位：指數與均線為點'), '資料表: no 元 for an index')
check(text(chartPanel).includes('2026/10/22 46,021.43 46,076.93 45,981.18 46,041.43'), '資料表: an index keeps two decimals and its real open, high and low')
check(text(chartPanel).includes('成交量（億股）') && text(chartPanel).includes('193.40') && text(chartPanel).includes('成交量為億股'), '資料表: an index volume is in 億股 (PR 553 review), 19,339,729,647 shares = 193.40')
check(text(chartPanel).includes('來源 臺灣證券交易所'), 'chart meta: the TAIEX report source is named')
const tpexPanel = slice(page, 'id="market-tpex-chart-title"', 'id="market-tx-chart-title"')
check(page.includes('<h3 class="card-title" id="market-tpex-chart-title">櫃買指數日線</h3>') && text(tpexPanel).includes('來源 證券櫃檯買賣中心') && text(tpexPanel).includes('10.70'), `櫃買指數日線: the same card on the TPEx index, volume in 億股: ${text(tpexPanel).slice(0, 200)}`)
const txPanel = page.slice(page.indexOf('id="market-tx-chart-title"'))
check(txPanel.includes('>台指期近月日線</h3>') && text(txPanel).includes('來源 臺灣期貨交易所'), '台指期近月日線: the same card on the TX near month')
check(text(txPanel).includes('成交量（口）') && text(txPanel).includes('143,277') && text(txPanel).includes('開（點）') && text(txPanel).includes('46,110'), '台指期: whole points and volume in 口')
check(text(txPanel).includes('2026/10/10 合約 2026/10 · 未平倉 125,011 口 · 結算價 46,105'), `台指期: the latest contract month, open interest and settlement: ${text(txPanel).slice(-600)}`)
check(text(txPanel).includes('自 2026/09/29 起收集，無更早歷史') && text(txPanel).includes(TAIFEX_ATTRIBUTION), '台指期: when the history starts and the open-data attribution')
check(collectedSinceText(fullBars) === '自 2026/09/01 起收集，無更早歷史' && collectedSinceText({ ...fullBars, count: STOCK_BARS_LIMIT }) === null, 'collectedSinceText: only when the series is shorter than the request')
check(futuresLatestText(fullBars) === null, 'futuresLatestText: nothing for an index')
check(priceDigits(46041.43, 'index') === 2 && priceDigits(46041.43, 'stock') === 0, 'priceDigits: an index has two decimals, a stock above 500 none')
check(axisDigits(24500, 2) === 0 && axisDigits(8000, 2) === 0 && axisDigits(999, 2) === 2, 'price axis: index labels from 1,000 drop the decimals so 「8,000」 fits the phone gutter (Issue 547)')
// The close-only TAIEX rows still read as before (synthetic bars, volume unit unverified).
const closeOnly = taiexBars([bar('2026-10-22', 46041.43, { open: 46041.43, high: 46041.43, low: 46041.43, volume: 0, source: 'twse_index' })])
const closeOnlyMarkup = text(render('/market close-only', <MarketChartView spec={MARKET_CHARTS[0]} interval="day" onIntervalChange={() => {}} data={closeOnly} loading={false} error={null} />))
check(closeOnlyMarkup.includes('2026/10/22 46,041.43 46,041.43 46,041.43 46,041.43') && closeOnlyMarkup.includes('成交量（張）'), `close-only TAIEX rows: 開＝高＝低＝收, no unit change: ${closeOnlyMarkup.slice(-300)}`)

// ---- no data: no bars, a failed bars request, a loading request, no overview ----
for (const spec of MARKET_CHARTS) {
  const emptyBars = render(`/market ${spec.key}`, <MarketChartView spec={spec} interval="day" onIntervalChange={() => {}} data={taiexBars([])} loading={false} error={null} />)
  check(text(emptyBars).includes(spec.title) && text(emptyBars).includes('無資料') && text(emptyBars).includes('來源未提供日線') && text(emptyBars).includes('資料日期未提供') && !emptyBars.includes('chart-data-table'), `沒有日線（${spec.key}）: 無資料＋來源未提供日線, no table: ${text(emptyBars)}`)
  check(text(emptyBars).includes(TAIFEX_ATTRIBUTION) === (spec.key === 'tx'), `沒有日線（${spec.key}）: the TX attribution stays, only on TX`)
}
const failedBars = render('/market', <MarketChartView spec={MARKET_CHARTS[1]} interval="week" onIntervalChange={() => {}} data={undefined} loading={false} error={new Error('HTTP 502')} />)
check(text(failedBars).includes('資料暫時無法載入') && text(failedBars).includes('HTTP 502'), `載入失敗: 資料暫時無法載入: ${text(failedBars)}`)
const loadingBars = render('/market', <MarketChartView spec={MARKET_CHARTS[2]} interval="day" onIntervalChange={() => {}} data={undefined} loading error={null} />)
check(loadingBars.includes('aria-busy="true"'), 'loading: a skeleton')
for (const [name, overview] of [['只有上市', overviewTwseOnly()], ['都沒有', overviewNone()], ['欄位不存在', undefined]] as const) {
  const markup = text(render(`/market ${name}`, <MarketOverviewPanel overview={overview} />))
  check(markup.includes('上櫃大盤資料未取得'), `大盤概況（${name}）: 上櫃大盤資料未取得`)
  check(name === '只有上市' ? markup.includes('46,041.43') && !markup.includes('381.69') && !markup.includes('上櫃為') : markup.includes('上市大盤資料未取得') && !/\d,\d{3}\.\d{2}/.test(markup), `大盤概況（${name}）: the shown exchange as usual, no number for the missing one`)
}
const otherScope = { ...overviewBoth(), exchanges: overviewBoth().exchanges.map((row) => row.exchange === 'TPEx' ? { ...row, turnover: { value: 1e8, scope: 'tpex_all', scope_label: '上櫃全部證券' } } : row) }
check(text(render('MarketOverviewView other scope', <MarketOverviewView overview={otherScope} />)).includes('上櫃 1.00 上櫃全部證券'), '大盤概況: an unknown scope shows the API scope_label')
check(JSON.stringify(marketOverviewNotes(overviewNone())) === JSON.stringify(['紅色為上漲、綠色為下跌（台股慣例）']), `資料說明 without data: only the red/green line, got ${JSON.stringify(marketOverviewNotes(overviewNone()))}`)

// ---- 美股（前一交易日）, Issue 547: four FRED closes, their freshness and their close-only daily K ----
const fred = (symbol: string, name: string, series_id: string, extra: Partial<ForeignIndex>): ForeignIndex => ({
  exchange: 'US', symbol, name, series_id, status: 'available', expected_date: '2026-11-06', trading_date: '2026-11-06', freshness: 'latest',
  close: 6820.5, change: -40.25, change_pct: -0.005867, change_pct_method: 'derived', previous_trading_date: '2026-11-05',
  source: { label: `FRED ${series_id}`, copyright: 'Copyright © 2016, S&P Dow Jones Indices LLC. All rights reserved.', collected_at: '2026-11-09T13:40:00+00:00', data_as_of: '2026-11-06', raw_payload_id: 7 },
  ...extra,
})
const usOverview = {
  ...overviewBoth(),
  foreign_indices: [
    fred('SPX', 'S&P 500', 'SP500', { trading_date: '2026-11-05', freshness: 'stale', close: 7353.73, change: -334.89, change_pct: -0.043557 }),
    fred('IXIC', 'NASDAQ 綜合指數', 'NASDAQCOM', { close: 24579.42, change: 264.42, change_pct: 0.010875, source: { label: 'FRED NASDAQCOM', copyright: 'Copyright © 2016, NASDAQ OMX Group, Inc.', collected_at: null } }),
    fred('DJI', '道瓊工業指數', 'DJIA', { trading_date: '2026-11-05', freshness: 'us_market_closed', close: 51285.73 }),
    { exchange: 'US', symbol: 'SOX', name: '費城半導體指數', series_id: 'NASDAQSOX', status: 'unavailable', reason: 'fetch_failed', expected_date: '2026-11-06', last_attempt_date: '2026-11-09' },
  ],
}
const usCharts: string[] = []
const usPanel = render('/market us', <UsIndexPanel overview={usOverview} chart={(spec) => { usCharts.push(spec.symbol); return null }} />)
const usText = text(usPanel)
for (const value of ['美股（前一交易日）', 'S&P 500', '7,353.73', '-334.89（-4.36%）', '資料 2026/11/05 非最新', 'NASDAQ 綜合指數', '24,579.42', '+264.42（+1.09%）', '資料 2026/11/06', '道瓊工業指數', '資料 2026/11/05 2026/11/06 美股休市', '費城半導體指數', '無資料：最近一次擷取失敗（2026/11/09）']) {
  check(usText.includes(value), `美股: shows 「${value}」: ${usText.slice(0, 400)}`)
}
check(!usText.includes('資料 2026/11/06 非最新'), '美股: the latest close has no 非最新')
check(count(usPanel, 'market-us-index') === 4 && count(usPanel, 'market-us-stale') === 1, '美股: four widgets, one marked 非最新')
check(/data-symbol="SPX"[^>]*>(?:(?!data-symbol)[\s\S])*tone-down/.test(usPanel) && /data-symbol="IXIC"[^>]*>(?:(?!data-symbol)[\s\S])*tone-up/.test(usPanel), '美股: 台股 colors, a fall green and a rise red')
check(usText.includes('資料 2026/11/06') && usPanel.includes('market-us-title'), '美股: the section badge is the newest data date')
const usExplanation = text(slice(usPanel, '<details class="data-explanation"', '</details>'))
for (const line of [FRED_ATTRIBUTION, 'Copyright © 2016, S&P Dow Jones Indices LLC. All rights reserved.', 'Copyright © 2016, NASDAQ OMX Group, Inc.', '台股資料日的前一個平日']) {
  check(usExplanation.includes(line), `美股 資料說明: 「${line}」, got ${usExplanation}`)
}
check(count(usPanel, 'class="details market-us-chart"') === 4 && usCharts.length === 0, '美股: four closed rows of daily K, no chart (or bars request) until one is opened')
check(US_INDEXES.map((spec) => usChartSpec(spec).symbol).join() === 'SPX,IXIC,DJI,SOX' && usChartSpec(US_INDEXES[0]).exchange === 'US', 'the US charts read /api/stocks/US/<symbol>/bars')
// A FRED series: closes only, so a close line and the note; the table keeps each close (Issue 552 null rules).
const fredRows = days.map((row) => ({ ...row, open: null, high: null, low: null, volume: null, source: 'fred_close', price_reason: 'source_missing_ohlc' }))
const fredBars: StockBarsResponse = { ...taiexBars(fredRows), instrument: { id: 14, exchange: 'US', symbol: 'SPX', name: 'S&P 500', instrument_type: 'index' } }
const fredChart = text(render('/market us chart', <MarketChartView spec={usChartSpec(US_INDEXES[0])} interval="day" onIntervalChange={() => {}} data={fredBars} loading={false} error={null} footer={<UsChartFooter item={usOverview.foreign_indices[0]} />} />))
check(fredChart.includes('S&P 500日線') && fredChart.includes(CLOSE_ONLY_NOTE), `FRED chart: titled, with the close-only note: ${fredChart.slice(0, 300)}`)
check(fredChart.includes('2026/10/22 46,041.43') && !fredChart.includes('2026/10/22 46,021.43'), 'FRED chart table: the close, no open/high/low')
check(fredChart.includes('來源 FRED（聖路易聯邦準備銀行）') && fredChart.includes(FRED_ATTRIBUTION) && fredChart.includes('S&P Dow Jones Indices LLC'), 'FRED chart: FRED named, the attribution and copyright under it')
const theme = readChartTheme(() => 'black')
const layout = chartLayout(320)
const fredOption = buildBarsChartOption(fredBars, { panel: 'macd', panelState: { kind: 'chart' } as never, visibleMa: new Set(), theme, layout, zoom: { start: 0, end: 100 }, digits: 2 })
const closeLine = (fredOption.series as Array<{ name?: string; xAxisIndex?: number; data?: unknown[] }>).find((series) => series.name === '收盤' && series.xAxisIndex === 0)
check(closeLine?.data?.length === fredRows.length && closeLine.data[fredRows.length - 1] === 46041.43, 'FRED chart: one close line on the price pane')
const taiexOption = buildBarsChartOption(fullBars, { panel: 'macd', panelState: { kind: 'chart' } as never, visibleMa: new Set(), theme, layout, zoom: { start: 0, end: 100 }, digits: 2 })
check(!(taiexOption.series as Array<{ name?: string; xAxisIndex?: number }>).some((series) => series.name === '收盤' && series.xAxisIndex === 0), 'a series with candles has no extra close line')
check(isCloseOnlySeries(fredRows) && !isCloseOnlySeries(days) && !isCloseOnlySeries([]), 'isCloseOnlySeries: every bar close-only')
// DESIGN_SYSTEM §6: only a whole close-only series gets the line. A Taiwan index with one day lacking open/high/low
// (Issue 552) keeps its candles, no close line and no note, as before.
const mixedRows = days.map((row, i) => i === 10 ? { ...row, open: null, high: null, low: null, price_reason: 'source_missing_ohlc' } : row)
const mixedOption = buildBarsChartOption(taiexBars(mixedRows), { panel: 'macd', panelState: { kind: 'chart' } as never, visibleMa: new Set(), theme, layout, zoom: { start: 0, end: 100 }, digits: 2 })
check(!(mixedOption.series as Array<{ name?: string; xAxisIndex?: number }>).some((series) => series.name === '收盤' && series.xAxisIndex === 0), 'a Taiwan index with one close-only day: no close line')
const mixedChart = text(render('/market mixed', <MarketChartView spec={MARKET_CHARTS[0]} interval="day" onIntervalChange={() => {}} data={taiexBars(mixedRows)} loading={false} error={null} />))
check(!mixedChart.includes(CLOSE_ONLY_NOTE) && mixedChart.includes('來源 臺灣證券交易所'), 'a Taiwan index with one close-only day: no close-only note')
check(expectedText(usOverview) === '資料 2026/11/06', 'the section badge reads the newest data date')

// ---- pure helpers ----
const items = summaryItems(overviewTwseOnly())
check(items[0].close === '46,041.43' && items[0].pct === '-1.81%' && items[0].tone === 'tone-down' && items[1].close === null, `summary items: ${JSON.stringify(items)}`)
const small = summaryItems({ ...overviewBoth(), exchanges: overviewBoth().exchanges.map((row) => row.exchange === 'TWSE' ? { ...row, index: { ...row.index!, change_pct: -0.0049 } } : row) })
check(small[0].pct === '-0.49%' && small[0].tone === 'tone-down', `a small fall (-0.49%) is still green, got ${small[0].tone}`)

// ---- layout rules the static markup cannot show ----
const css = fs.readFileSync(path.join(__dirname, '..', 'styles.css'), 'utf8')
check(!css.includes('market-overview-more'), 'Issue 549: no folded overview left (the market page shows all four widgets)')
check(/\.market-summary-item \{[^}]*white-space:\s*nowrap/.test(css), 'summary: an index item never breaks inside')
check(/\.market-us-grid \{[^}]*repeat\(4, minmax\(0, 1fr\)\)/.test(css) && /\.market-overview-grid, \.market-us-grid \{[^}]*repeat\(2,/.test(css), '美股: four equal widgets, two per row below 1200px')

if (failures.length) throw new Error(`${failures.length} of ${checks} market checks failed:\n- ${failures.join('\n- ')}`)
