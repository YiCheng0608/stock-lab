import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import * as AppModule from '../App'
import { MAIN_NAV } from '../components/Navbar'
import type { Dashboard, StockBarRow, StockBarsResponse } from '../types'
import { overviewBoth, overviewNone, overviewTwseOnly } from '../today/today.fixtures'
import { IndexChartPanel, MarketOverviewPanel, MarketOverviewView } from './MarketViews'
import { MarketPage } from './MarketPage'
import {
  TAIEX,
  TAIEX_BARS_LIMIT,
  TPEX_NO_BARS_TEXT,
  buildIndexChartOption,
  chartMeta,
  indexChartLayout,
  indexSourceText,
  marketOverviewNotes,
  summaryItems,
} from './marketOverview'

// The frontend ships no Node typings; scripts/ci-test.cjs runs this module under Node, so declare what it uses.
declare const require: (id: string) => unknown
declare const __dirname: string
const fs = require('node:fs') as { readFileSync(file: string, encoding: 'utf8'): string }
const path = require('node:path') as { join(...parts: string[]): string }

// 大盤 page (/market, Issue 549; PRODUCT_SPEC §2, DESIGN_SYSTEM §4/§5/§6, UI_COPY_SPEC §11): navigation, the page with
// data, and the states without data (no 櫃買 daily history, no TAIEX bars, no overview). Failures are listed together.
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

const bar = (date: string, close: number | null, extra: Partial<StockBarRow> = {}): StockBarRow =>
  ({ date, open: close, high: close, low: close, close, volume: 0, source: 'twse_index', is_suspended: false, bar_count: null, reasons: {}, ...extra })

function taiexBars(rows: StockBarRow[], extra: Partial<StockBarsResponse> = {}): StockBarsResponse {
  return {
    instrument: { id: 9, exchange: 'TWSE', symbol: 'TAIEX', name: '發行量加權股價指數', instrument_type: 'index' },
    interval: 'day',
    limit: TAIEX_BARS_LIMIT,
    count: rows.length,
    data_as_of: rows.length ? rows[rows.length - 1].date : null,
    sources: rows.length ? ['twse_index'] : [],
    indicators: { formula_version: 'indicators/v1', price_basis: 'as_of_date_raw_basis/v2', parameters: {}, required_bars: {}, fields: [], source: 'technical_indicators', computed_at: null },
    bars: rows,
    ...extra,
  }
}

const days = Array.from({ length: 40 }, (_, i) => bar(`2026-09-${String((i % 28) + 1).padStart(2, '0')}`, 45000 + i * 25.5))
days[days.length - 1] = bar('2026-10-22', 46041.43)
const fullBars = taiexBars(days)

// ---- navigation: 大盤 right after 今日可買, the /market route renders this page ----
const nav = MAIN_NAV.map((item) => `${item.to} ${item.label}`)
check(nav[0] === '/ 今日可買' && nav[1] === '/market 大盤' && nav.length === 7, `MAIN_NAV: 大盤 is second of seven, got ${JSON.stringify(nav)}`)
const routes = (AppModule as Record<string, unknown>).APP_ROUTES as ReadonlyArray<{ path: string; element: ReactElement }> | undefined
check(routes?.find((route) => route.path === '/market')?.element.type === MarketPage, '/market route renders MarketPage')
const App = (AppModule as Record<string, unknown>).default as () => ReactElement
const shell = render('/market', <App />)
check(!shell.includes('找不到此頁') && shell.includes('<h1>大盤</h1>'), `/market is not a 404 and its title is 大盤: ${text(shell).slice(0, 200)}`)
check(/<a[^>]*class="active"[^>]*href="\/market"[^>]*>大盤<\/a>|<a[^>]*href="\/market"[^>]*class="active"[^>]*>大盤<\/a>|aria-current="page"[^>]*href="\/market"|href="\/market"[^>]*aria-current="page"/.test(shell), '/market: the navbar marks 大盤 as the current page')

// ---- the page with data: overview first, then the TAIEX daily chart, then the 櫃買 no-history row ----
const dashboard = { as_of: '2026-10-22', market_overview: overviewBoth() } as unknown as Dashboard
const client = new QueryClient()
client.setQueryData(['dashboard'], dashboard)
client.setQueryData(['stock-bars', TAIEX.exchange, TAIEX.symbol, 'day', TAIEX_BARS_LIMIT], fullBars)
const page = render('/market', <MarketPage />, client)
const pageText = text(page)
check(page.indexOf('id="market-overview-title"') > 0 && page.indexOf('id="market-overview-title"') < page.indexOf('id="market-chart-title"'), 'DESIGN_SYSTEM §4: 大盤概況 before 加權指數日線')
check(page.indexOf('id="market-chart-title"') < page.indexOf('class="market-no-bars"'), '櫃買指數日線 row is the last thing of the chart block')
check(!/美股|大盤狀態/.test(pageText), 'no placeholder for 美股 (Issue 547) or 大盤狀態 (Issue 546) yet')
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
const chartPanel = slice(page, 'id="market-chart-title"', 'class="market-no-bars"')
check(text(chartPanel).includes('加權指數日線') && text(chartPanel).includes('資料 2026/10/22'), `加權指數日線: title and the last bar's date badge: ${text(chartPanel).slice(0, 120)}`)
check(chartPanel.includes('role="tablist"') && text(chartPanel).includes('日線') && text(chartPanel).includes('週線') && chartPanel.includes('aria-selected="true"'), '加權指數日線: the stock page period switch (日線／週線)')
for (const line of ['來源 臺灣證券交易所', '最近 40 根日線；缺日不補', '指數只有收盤價，只畫收盤線，不畫 K 線與成交量']) check(text(chartPanel).includes(line), `加權指數日線 meta: 「${line}」`)
check(text(chartPanel).includes('查看圖表資料表（最近 30 根）') && count(chartPanel, '<tr') === 31, `資料表: a header and the latest 30 rows, got ${count(chartPanel, '<tr')}`)
check(text(chartPanel).includes('2026/10/22 46,041.43'), '資料表: newest first, close in 點 with two decimals')
check(!chartPanel.includes('MACD') && !chartPanel.includes('indicator-tabs') && !chartPanel.includes('成交量（張）'), 'an index draws a close line, no indicator panel or volume (DESIGN_SYSTEM §6)')
check(text(slice(page, 'class="market-no-bars"', '</p>')).includes('櫃買指數日線') && pageText.includes(TPEX_NO_BARS_TEXT), `無資料（櫃買日線）: 「${TPEX_NO_BARS_TEXT}」`)

// ---- no data: no TAIEX bars, a failed bars request, a loading request, no overview ----
const emptyBars = render('/market', <IndexChartPanel interval="day" onIntervalChange={() => {}} data={taiexBars([])} loading={false} error={null} />)
check(text(emptyBars).includes('無資料') && text(emptyBars).includes('來源未提供日線') && text(emptyBars).includes('資料日期未提供') && !emptyBars.includes('chart-data-table'), `沒有日線: 無資料＋來源未提供日線, no table: ${text(emptyBars)}`)
check(text(emptyBars).includes(TPEX_NO_BARS_TEXT), '沒有日線: the 櫃買 row still says why it has none')
const failedBars = render('/market', <IndexChartPanel interval="week" onIntervalChange={() => {}} data={undefined} loading={false} error={new Error('HTTP 502')} />)
check(text(failedBars).includes('資料暫時無法載入') && text(failedBars).includes('HTTP 502'), `載入失敗: 資料暫時無法載入: ${text(failedBars)}`)
const loadingBars = render('/market', <IndexChartPanel interval="day" onIntervalChange={() => {}} data={undefined} loading error={null} />)
check(loadingBars.includes('aria-busy="true"') && !loadingBars.includes('date-badge'), 'loading: a skeleton, no date badge yet')
const suspendedOnly = render('/market', <IndexChartPanel interval="day" onIntervalChange={() => {}} data={taiexBars([bar('2026-10-22', null), bar('2026-10-21', 0)])} loading={false} error={null} />)
check(text(suspendedOnly).includes('來源未提供日線'), 'bars without a drawable close: 無資料, not an empty chart')
for (const [name, overview] of [['只有上市', overviewTwseOnly()], ['都沒有', overviewNone()], ['欄位不存在', undefined]] as const) {
  const markup = text(render(`/market ${name}`, <MarketOverviewPanel overview={overview} />))
  check(markup.includes('上櫃大盤資料未取得'), `大盤概況（${name}）: 上櫃大盤資料未取得`)
  check(name === '只有上市' ? markup.includes('46,041.43') && !markup.includes('381.69') && !markup.includes('上櫃為') : markup.includes('上市大盤資料未取得') && !/\d,\d{3}\.\d{2}/.test(markup), `大盤概況（${name}）: the shown exchange as usual, no number for the missing one`)
}
const otherScope = { ...overviewBoth(), exchanges: overviewBoth().exchanges.map((row) => row.exchange === 'TPEx' ? { ...row, turnover: { value: 1e8, scope: 'tpex_all', scope_label: '上櫃全部證券' } } : row) }
check(text(render('MarketOverviewView other scope', <MarketOverviewView overview={otherScope} />)).includes('上櫃 1.00 上櫃全部證券'), '大盤概況: an unknown scope shows the API scope_label')
check(JSON.stringify(marketOverviewNotes(overviewNone())) === JSON.stringify(['紅色為上漲、綠色為下跌（台股慣例）']), `資料說明 without data: only the red/green line, got ${JSON.stringify(marketOverviewNotes(overviewNone()))}`)

// ---- pure helpers ----
check(indexSourceText(['twse_index']) === '來源 臺灣證券交易所' && indexSourceText(['twse_index_fixture']) === '來源待核實' && indexSourceText([]) === '來源未提供', 'source text: only twse_index is the exchange')
check(chartMeta(taiexBars(days, { interval: 'week', count: 12 }))[1] === '最近 12 根週線；缺日不補；週線依日線聚合', `week meta: ${chartMeta(taiexBars(days, { interval: 'week', count: 12 }))[1]}`)
const theme = { up: 'u', down: 'd', flat: 'f', primary: 'token(--color-primary)', accent: 'a', text: 't', muted: 'm', subtle: 's', grid: 'g', border: 'b', cardBg: 'c', fontMono: 'mono', ma5: '', ma10: '', ma20: '', ma60: '', ma120: '' }
const option = buildIndexChartOption(taiexBars([bar('2026-10-21', 46887.77), bar('2026-10-22', null, { is_suspended: true })]), theme, indexChartLayout(320), { start: 0, end: 100 })
const series = option.series[0]
check(series.type === 'line' && series.lineStyle.color === 'token(--color-primary)' && series.lineStyle.width === 2 && series.areaStyle.opacity === 0.25, 'DESIGN_SYSTEM §6 single line: primary 2px with a 25% fill')
check(JSON.stringify(series.data) === JSON.stringify([46887.77, '-']), `a day without a close is a gap, not 0: ${JSON.stringify(series.data)}`)
check(option.yAxis.scale === true && !('min' in option.yAxis), 'the y axis is not pinned at 0')
check(JSON.stringify(option.xAxis.data) === JSON.stringify(['2026/10/21', '2026/10/22']), `x axis dates: ${JSON.stringify(option.xAxis.data)}`)
const items = summaryItems(overviewTwseOnly())
check(items[0].close === '46,041.43' && items[0].pct === '-1.81%' && items[0].tone === 'tone-down' && items[1].close === null, `summary items: ${JSON.stringify(items)}`)
const small = summaryItems({ ...overviewBoth(), exchanges: overviewBoth().exchanges.map((row) => row.exchange === 'TWSE' ? { ...row, index: { ...row.index!, change_pct: -0.0049 } } : row) })
check(small[0].pct === '-0.49%' && small[0].tone === 'tone-down', `a small fall (-0.49%) is still green, got ${small[0].tone}`)

// ---- layout rules the static markup cannot show ----
const css = fs.readFileSync(path.join(__dirname, '..', 'styles.css'), 'utf8')
check(!css.includes('market-overview-more'), 'Issue 549: no folded overview left (the market page shows all four widgets)')
check(/\.market-summary-item \{[^}]*white-space:\s*nowrap/.test(css), 'summary: an index item never breaks inside')

if (failures.length) throw new Error(`${failures.length} of ${checks} market checks failed:\n- ${failures.join('\n- ')}`)
