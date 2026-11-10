import { isValidElement, type ReactElement, type ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import * as AppModule from '../App'
import { MAIN_NAV } from '../components/Navbar'
import type { Dashboard, IndexRow, MarketOverview, StockBarRow, StockBarsResponse, TaiexMa60 } from '../types'
import { overviewBoth, overviewNone, overviewTwseOnly } from '../today/today.fixtures'
import { CLOSE_ONLY_NOTE, STOCK_BARS_LIMIT, axisDigits, buildBarsChartOption, chartLayout, isCloseOnlySeries, priceDigits, readChartTheme } from '../stock/stockBars'
import { IndexTablePanel, IndexTableView, MarketChartView, MarketOverviewPanel, MarketOverviewView, UsChartFooter } from './MarketViews'
import { MarketPage } from './MarketPage'
import { indexRows, overviewWithIndexes } from './market.fixtures'
import {
  US_ATTRIBUTION, INDEX_MA60_NOTE, INDEX_SPECS, MA60_BACKGROUND_NOTE, MA60_NOTE, TAIEX, TAIFEX_ATTRIBUTION, US_SECTION_TITLE,
  chartTitle, collectedSinceText, futuresLatestText, indexMa60Cell, indexSearch, indexTableNotes, marketOverviewNotes, selectedIndex,
  summaryItems, usGroupTitle,
} from './marketOverview'

// The frontend ships no Node typings; scripts/ci-test.cjs runs this module under Node, so declare what it uses.
declare const require: (id: string) => unknown
declare const __dirname: string
const fs = require('node:fs') as { readFileSync(file: string, encoding: 'utf8'): string }
const path = require('node:path') as { join(...parts: string[]): string }

// 大盤 page (/market, Issue 549/552/547/561/564; PRODUCT_SPEC §2, DESIGN_SYSTEM §4/§5/§6, UI_COPY_SPEC §11): navigation, the
// page with data (the overview, the index table and the shared daily K chart), selecting a row, and the states without
// data. Failures are listed together.
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

// The host elements of a tree without hooks, function components called in place: the static markup drops event
// handlers, so a row's onClick is read and called from here (the tests run without a DOM).
type Host = { type: string; props: Record<string, unknown> }
function hosts(node: ReactNode, found: Host[] = []): Host[] {
  if (Array.isArray(node)) { node.forEach((child) => hosts(child, found)); return found }
  if (!isValidElement(node)) return found
  const props = node.props as Record<string, unknown>
  if (typeof node.type === 'function') return hosts((node.type as (props: unknown) => ReactNode)(props), found)
  if (typeof node.type === 'string') found.push({ type: node.type, props })
  hosts(props.children as ReactNode, found)
  return found
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
// TX from the first collects only: 12 sessions, so fewer than the limit (UI_COPY_SPEC §11 「自 … 起收集」); futDataDown
// rows before the OpenAPI ones (Issue 590), as in the production DB.
const txRows = Array.from({ length: 12 }, (_, i) => bar(dateOf(28 + i), 46000 + i * 10, { open: 45990 + i * 10, high: 46100 + i * 10, low: 45900 + i * 10, volume: 143277, source: i < 6 ? 'taifex_futdatadown' : 'taifex_daily_futures', contract_month: i < 6 ? '202609' : '202610', open_interest: 125000 + i, settlement_price: 45995 + i * 10 }))
const txBars: StockBarsResponse = { ...taiexBars(txRows), instrument: { id: 11, exchange: 'TAIFEX', symbol: 'TX', name: '臺股期貨近月', instrument_type: 'futures' } }
// A FRED series: closes only (Issue 547).
const fredRows = days.map((row) => ({ ...row, open: null, high: null, low: null, volume: null, source: 'fred_close', price_reason: 'source_missing_ohlc' }))
const fredBars: StockBarsResponse = { ...taiexBars(fredRows), instrument: { id: 14, exchange: 'US', symbol: 'SPX', name: 'S&P 500', instrument_type: 'index' } }
// A FinMind series (Issue 568): open, high, low and close; SOX has no volume (NULL).
const finmindRows = days.map((row) => ({ ...row, volume: null, source: 'finmind_us_index', price_reason: null }))
const finmindBars: StockBarsResponse = { ...taiexBars(finmindRows), instrument: { id: 17, exchange: 'US', symbol: 'SOX', name: '費城半導體指數', instrument_type: 'index' } }

const spec = (key: string) => INDEX_SPECS.find((item) => item.key === key) ?? TAIEX
const chart = (key: string, data: StockBarsResponse | undefined, extra: { loading?: boolean; error?: unknown; row?: IndexRow | null; interval?: 'day' | 'week' } = {}) =>
  <MarketChartView spec={spec(key)} row={extra.row ?? null} interval={extra.interval ?? 'day'} onIntervalChange={() => {}} data={data} loading={extra.loading ?? false} error={extra.error ?? null} />

// ---- navigation: 大盤 right after 今日可買, the /market route renders this page ----
const nav = MAIN_NAV.map((item) => `${item.to} ${item.label}`)
check(nav[0] === '/ 今日可買' && nav[1] === '/market 大盤' && nav.length === 7, `MAIN_NAV: 大盤 is second of seven, got ${JSON.stringify(nav)}`)
const routes = (AppModule as Record<string, unknown>).APP_ROUTES as ReadonlyArray<{ path: string; element: ReactElement }> | undefined
check(routes?.find((route) => route.path === '/market')?.element.type === MarketPage, '/market route renders MarketPage')
const App = (AppModule as Record<string, unknown>).default as () => ReactElement
const shell = render('/market', <App />)
check(!shell.includes('找不到此頁') && shell.includes('<h1>大盤</h1>'), `/market is not a 404 and its title is 大盤: ${text(shell).slice(0, 200)}`)
check(/<a[^>]*class="active"[^>]*href="\/market"[^>]*>大盤<\/a>|<a[^>]*href="\/market"[^>]*class="active"[^>]*>大盤<\/a>|aria-current="page"[^>]*href="\/market"|href="\/market"[^>]*aria-current="page"/.test(shell), '/market: the navbar marks 大盤 as the current page')

// ---- the page with data: 大盤概況 → 指數總表 → the shared chart (加權指數 by default) ----
const dashboard = { as_of: '2026-10-22', market_overview: overviewWithIndexes() } as unknown as Dashboard
const client = new QueryClient()
client.setQueryData(['dashboard'], dashboard)
// The stock page's query key: /stocks/TWSE/TAIEX and /market share one cache entry.
client.setQueryData(['stock-bars', 'TWSE', 'TAIEX', 'day'], fullBars)
client.setQueryData(['stock-bars', 'TPEx', 'TPEX', 'day'], tpexBars)
client.setQueryData(['stock-bars', 'TAIFEX', 'TX', 'day'], txBars)
client.setQueryData(['stock-bars', 'US', 'SOX', 'day'], fredBars)
const page = render('/market', <MarketPage />, client)
const pageText = text(page)
check(JSON.stringify(INDEX_SPECS.map((item) => `${item.exchange}/${item.symbol}`)) === '["TWSE/TAIEX","TPEx/TPEX","TAIFEX/TX","US/SPX","US/IXIC","US/DJI","US/SOX"]', 'the seven rows read the bars API of TAIEX, TPEX, TX and the four US indexes')
const order = ['id="market-overview-title"', 'id="market-indexes-title"', 'id="market-chart-title"'].map((id) => page.indexOf(id))
check(order.every((at, i) => at > 0 && (i === 0 || at > order[i - 1])), `DESIGN_SYSTEM §4: 大盤概況 → 指數總表 → K 線, got ${order}`)
check(count(page, 'class="card-title"') === 1 && page.includes('>加權指數日線</h3>'), 'one shared chart, 加權指數 by default (Issue 564 replaces the three charts)')
check(!page.includes('market-us-title') && !page.includes('market-us-chart') && !page.includes('id="market-tpex-chart-title"'), 'no separate US panel or folded US charts, no second chart card')
check(!/大盤狀態/.test(pageText), 'no placeholder for 大盤狀態 (Issue 546) yet')
check(pageText.includes('上市、上櫃的收盤概況，以及加權、櫃買、台指期與美股共 7 檔指數的總表；點一列看它的日 K。'), 'the page lead names the table')
const overviewPanel = slice(page, 'id="market-overview-title"', 'id="market-indexes-title"')
for (const value of ['大盤概況', '資料 2026/10/22', '加權指數', '46,041.43', '-846.34（-1.81%）', '櫃買指數', '381.69', '-13.73（-3.47%）', '上市 9,334.37 集中市場總計', '上櫃 2,255.45 上櫃股票', '上市 上漲 247 · 下跌 756 · 平盤 74（3／5）', '上櫃 上漲 146 · 下跌 659 · 平盤 63（17／11）']) {
  check(text(overviewPanel).includes(value), `大盤概況: shows 「${value}」`)
}
check(count(overviewPanel, 'market-widget-dual') === 2 && !overviewPanel.includes('market-overview-more'), '大盤概況: four widgets, nothing folded on phones (the page is for the market)')
check(/class="market-widget-change[^"]*tone-down"/.test(overviewPanel), '大盤概況: a falling index change is green')
const explanation = text(slice(overviewPanel, '<details class="data-explanation"', '</details>'))
for (const line of ['來源：上市為臺灣證券交易所 MI_INDEX；上櫃為櫃買中心 tpex_mainborad_highlight', '成交金額範圍：上市為集中市場總計（含 ETF、權證等）；上櫃為上櫃股票', '櫃買指數漲跌幅依前一日收市指數計算', '紅色為上漲、綠色為下跌（台股慣例）']) {
  check(explanation.includes(line), `大盤概況 資料說明: 「${line}」, got ${explanation}`)
}

// ---- 指數總表 (AC-1): seven rows in two groups, each state of the fixture ----
const table = slice(page, 'id="market-indexes-title"', 'id="market-chart-title"')
const tableText = text(table)
check(count(table, 'class="market-index-row') === 7 && count(table, 'class="table-group-row"') === 2, `指數總表: seven rows in two groups, got ${count(table, 'class="market-index-row')} / ${count(table, 'class="table-group-row"')}`)
for (const header of ['指數', '收盤（點）', '漲跌', '漲跌幅', '資料日', '相對季線（MA60）', '來源']) check(table.includes(`>${header}</th>`), `指數總表: the 「${header}」 column`)
check(/<th class="num">收盤（點）<\/th><th class="num">漲跌<\/th><th class="num">漲跌幅<\/th>/.test(table), '指數總表: close and change columns are numeric (right, mono)')
const rowOf = (key: string) => slice(table, `data-index="${key}"`, '</tr>')
const rowText = (key: string) => text(rowOf(key)).trim()
const expectRow = (key: string, parts: string[]) => { for (const part of parts) check(rowText(key).includes(part), `${key} row: 「${part}」, got ${rowText(key)}`) }
expectRow('taiex', ['加權指數', '46,041.43', '-846.34', '-1.81%', '2026/10/22', '之上', '季線 44,012.50', '臺灣證券交易所'])
check(!rowText('taiex').includes('非最新'), 'taiex: the latest data has no 非最新')
expectRow('tpex', ['櫃買指數', '395.42', '+2.10', '+0.53%', '2026/10/21 非最新', '資料不足（42／60 日）', '證券櫃檯買賣中心'])
expectRow('tx', ['台指期近月', '合約 2026/11', '46,110', '換月', '2026/10/22', '之下', '季線 46,502', '臺灣期貨交易所'])
check(!/46,110\.\d/.test(rowText('tx')) && !/46,502\.\d/.test(rowText('tx')), 'tx: whole points for the close and MA60 (DESIGN_SYSTEM §3)')
check(count(rowOf('tx'), '換月') === 2 && !/tone-(up|down)/.test(rowOf('tx')), 'tx on a roll day: 換月 in both change cells (the reason, not a blank; decision 6725073156), no up/down color')
check(tableText.includes('台指期近月 2026/10/22 換月（2026/10 → 2026/11），與前一筆是不同合約，不計漲跌'), `tx roll note under the table: ${tableText.slice(-400)}`)
expectRow('spx', ['S&P 500', '7,353.73', '-334.89', '-4.36%', '2026/10/20 非最新', '之上', '季線 6,900.12', 'FinMind'])
expectRow('ixic', ['NASDAQ 綜合指數', '24,579.42', '+264.42', '+1.09%', '2026/10/21', '無資料：季線尚未計算'])
check(!rowText('ixic').includes('非最新') && !rowText('ixic').includes('美股休市'), 'ixic: the expected US session, no flag')
expectRow('dji', ['道瓊工業指數', '51,285.73', '2026/10/20 2026/10/21 美股休市', '持平', '季線 51,285.73'])
check(!rowText('dji').includes('非最新'), 'dji: 美股休市 is not 非最新')
expectRow('sox', ['費城半導體指數', '無資料：最近一次擷取失敗（2026/10/22）', 'FinMind'])
check(!/\d,\d{3}\.\d{2}/.test(rowText('sox')) && count(rowOf('sox'), '>—<') >= 4, `sox without data: no number, — in the value cells: ${rowText('sox')}`)
check(count(table, 'market-index-stale') === 2, `非最新 in the warning color on TPEX and SPX, got ${count(table, 'market-index-stale')}`)
check(/data-index="taiex"(?:(?!<\/tr>)[\s\S])*tone-down/.test(table) && /data-index="ixic"(?:(?!<\/tr>)[\s\S])*tone-up/.test(table) && /data-index="tpex"(?:(?!<\/tr>)[\s\S])*tone-up/.test(table), '漲跌: 台股 colors on the change only, a fall green and a rise red')
check(!/market-index-ma60[^>]*>(?:(?!<\/td>)[\s\S])*tone-(up|down)/.test(table), '相對季線: no up/down colors (background, not a signal)')
const groupTitles = [...table.matchAll(/class="table-group-row"><td colSpan="7">([^<]*)<\/td>/gi)].map((match) => match[1])
check(groupTitles.join() === '台股,美股', `groups: 台股 and 美股 (one US row is 非最新, so not ${US_SECTION_TITLE}), got ${groupTitles.join()}`)
check(tableText.includes('來源：加權指數 臺灣證券交易所；櫃買指數 證券櫃檯買賣中心；台指期近月 臺灣期貨交易所；美股 FinMind'), 'the 來源 note under the table (the column is hidden on phones)')
check(page.indexOf('data-index="taiex"') < page.indexOf('data-index="tpex"') && page.indexOf('data-index="tx"') < page.indexOf('data-index="spx"') && page.indexOf('data-index="dji"') < page.indexOf('data-index="sox"'), 'rows in table order')
const tableNotes = text(slice(table, '<details class="data-explanation"', '</details>'))
for (const line of [TAIFEX_ATTRIBUTION, US_ATTRIBUTION, 'Copyright © 2016, S&P Dow Jones Indices LLC. All rights reserved.', 'Copyright © 2016, NASDAQ OMX Group, Inc.', '台股資料日的前一個平日', '台指期換月日不計漲跌', INDEX_MA60_NOTE, MA60_BACKGROUND_NOTE, '紅色為上漲、綠色為下跌（台股慣例）']) {
  check(tableNotes.includes(line), `指數總表 資料說明: 「${line}」, got ${tableNotes}`)
}
check(count(tableNotes, 'S&P Dow Jones Indices LLC') === 1, '資料說明: a copyright notice shared by two series is listed once')

// ---- selection (AC-2): the selected row, the URL, a click and Enter ----
check(/data-index="taiex"[^>]*aria-current="true"/.test(page) || /aria-current="true"[^>]*data-index="taiex"/.test(page), 'default: 加權指數 is the selected row')
check(count(table, 'is-selected') === 1 && count(table, 'aria-pressed="true"') === 1 && count(table, 'aria-pressed="false"') === 6, 'one selected row, its name button pressed')
for (const [location, key, title] of [['/market?index=tpex', 'tpex', '櫃買指數日線'], ['/market?index=tx', 'tx', '台指期近月日線'], ['/market?index=sox', 'sox', '費城半導體指數日線'], ['/market?index=nope', 'taiex', '加權指數日線'], ['/market?tab=x&index=tx', 'tx', '台指期近月日線']] as const) {
  const markup = render(location, <MarketPage />, client)
  const selectedRow = slice(markup, 'is-selected', '</tr>')
  check(markup.includes(`>${title}</h3>`) && count(markup, 'class="card-title"') === 1, `${location}: the chart is 「${title}」`)
  check(count(markup, 'is-selected') === 1 && markup.indexOf(`data-index="${key}"`) >= 0 && markup.lastIndexOf('<tr', markup.indexOf('is-selected')) === markup.lastIndexOf('<tr', markup.indexOf(`data-index="${key}"`)) && selectedRow.includes('aria-pressed="true"'), `${location}: the ${key} row is selected after a reload`)
}
const soxPage = render('/market?index=sox', <MarketPage />, client)
check(text(soxPage).includes(CLOSE_ONLY_NOTE) && text(soxPage).includes(US_ATTRIBUTION) && text(soxPage).includes('Copyright © 2016, NASDAQ OMX Group, Inc.'), 'a US row: the close line note, the FRED attribution and its copyright under the chart')
const txPage = render('/market?index=tx', <MarketPage />, client)
check(text(txPage).includes('2026/10/10 合約 2026/10 · 未平倉 125,011 口 · 結算價 46,105') && text(txPage).includes(TAIFEX_ATTRIBUTION), 'the TX row: contract month, open interest and the attribution under the chart (Issue 552)')
check(selectedIndex(new URLSearchParams('index=dji')).key === 'dji' && selectedIndex(new URLSearchParams('')).key === 'taiex' && selectedIndex(new URLSearchParams('index=TAIEX')).key === 'taiex', 'selectedIndex: ?index=<key>, 加權指數 otherwise')
check(indexSearch(new URLSearchParams('tab=x'), 'tx').toString() === 'tab=x&index=tx' && indexSearch(new URLSearchParams('index=tx&tab=x'), 'taiex').toString() === 'tab=x', 'indexSearch: sets ?index= and keeps other parameters; the default drops it')
// A click anywhere on a row calls onSelect with its key; the name is a native button whose click (Enter or Space on the
// focused button) bubbles to the row, so Tab reaches every row and Enter switches it.
const picked: string[] = []
const tree = hosts(IndexTableView({ overview: overviewWithIndexes(), selected: 'dji', onSelect: (key) => picked.push(key) }))
const rows = tree.filter((node) => node.type === 'tr' && typeof node.props['data-index'] === 'string')
check(rows.map((row) => row.props['data-index']).join() === 'taiex,tpex,tx,spx,ixic,dji,sox', `rows: ${rows.map((row) => row.props['data-index']).join()}`)
for (const row of rows) (row.props.onClick as (() => void) | undefined)?.()
check(picked.join() === 'taiex,tpex,tx,spx,ixic,dji,sox', `a click on each row selects it, got ${picked.join()}`)
const buttons = tree.filter((node) => node.type === 'button')
check(buttons.length === 7 && buttons.every((button) => button.props.type === 'button' && button.props.onClick === undefined && button.props.tabIndex === undefined && button.props.disabled === undefined), 'each row has one native button (focusable by Tab, Enter clicks it), no handler of its own to stop the click reaching the row')
check(buttons.map((button) => button.props['aria-pressed']).join() === 'false,false,false,false,false,true,false' && buttons.every((button) => button.props['aria-controls'] === 'market-index-chart'), 'aria-pressed on the selected row, every button controls the chart')
check(rows.find((row) => row.props['data-index'] === 'dji')?.props.className === 'market-index-row is-selected', 'the selected row has its class')
check(page.includes('id="market-index-chart"'), 'the chart has the id the buttons control')

// ---- AC-3: the MA60 shown is the row's indicators/v1 ma60; TAIEX is the 季線 strip's (#561) ----
const taiexRow = indexRows()[0]
const strip = { ...(dashboard.market_overview as MarketOverview), taiex_ma60: { trading_date: '2026-10-22', required_closes: 60, status: 'available', close: 46041.43, ma60: 44012.5, above: true, position: 'above', close_count: 250, segments: [], segment_window: { start: '2025-10-28', end: '2026-10-22', sessions: 250, max_segments: 3 } } as TaiexMa60 }
const withStrip = render('/market strip', <><MarketOverviewPanel overview={strip} /><IndexTablePanel overview={strip} selected="taiex" onSelect={() => {}} /></>)
check(text(slice(withStrip, 'class="market-ma60"', '</section>')).includes('在季線之上 （季線 44,012.50）') && text(slice(withStrip, 'data-index="taiex"', '</tr>')).includes('之上 季線 44,012.50'), 'TAIEX: the table and the 季線 strip show the same position and MA60')
const cell = indexMa60Cell(taiexRow, 2)
check(cell.kind === 'position' && cell.ma60 === '季線 44,012.50' && cell.position === '之上', `indexMa60Cell: the stored ma60 as is, got ${JSON.stringify(cell)}`)
check(JSON.stringify(indexMa60Cell({ ...taiexRow, ma60: { ...taiexRow.ma60!, ma60: 44012.004 } }, 2)) === JSON.stringify({ kind: 'position', position: '之上', ma60: '季線 44,012.00' }), 'indexMa60Cell: two decimals of the stored value, no recomputation')
for (const [reason, expected] of [['not_collected', '無資料：日線未收集'], ['row_date_mismatch', '無資料：日線最新為 2026/10/21'], ['ma60_unavailable', '無資料']] as const) {
  const item = indexMa60Cell({ ...taiexRow, ma60: { trading_date: '2026-10-22', required_closes: 60, status: 'unavailable', reason, latest_trading_date: '2026-10-21' } }, 2)
  check(item.kind === 'text' && item.text === expected, `indexMa60Cell(${reason}): 「${expected}」, got ${JSON.stringify(item)}`)
}

// ---- the US group title (decision 6725073156): 前一交易日 only when the US data is the session before ----
const us = (freshness: string, trading_date: string) => indexRows().map((row) => row.group === 'us' && row.status === 'available' ? { ...row, freshness, trading_date } : row)
check(usGroupTitle(overviewWithIndexes(us('latest', '2026-10-21'))) === '美股（前一交易日）', 'every US row the session before: 美股（前一交易日）')
check(usGroupTitle(overviewWithIndexes()) === '美股', 'one US row 非最新: just 美股')
check(usGroupTitle(overviewWithIndexes(us('latest', '2026-10-22'))) === '美股', 'a US row dated the Taiwan data date: just 美股')
check(usGroupTitle(overviewWithIndexes(indexRows().map((row) => row.group === 'us' ? { ...row, status: 'unavailable', reason: 'not_collected', ma60: null } : row))) === '美股', 'no US data: just 美股')
check(usGroupTitle(overviewWithIndexes(indexRows().map((row) => row.key === 'spx' ? { ...row, freshness: 'us_market_closed' } : row))) === '美股（前一交易日）', '美股休市 and latest rows: 前一交易日')
check(text(page).includes('美股') && !text(table).includes('美股（前一交易日）'), 'the page fixture has a 非最新 US row: the group says 美股 only')

// ---- the shared chart: the stock page's StockBarsChart (coordinator decision 6715021190) ----
const chartPanel = page.slice(page.indexOf('id="market-chart-title"'))
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
const tpexChart = text(render('/market tpex', chart('tpex', tpexBars)))
check(tpexChart.includes('櫃買指數日線') && tpexChart.includes('來源 證券櫃檯買賣中心') && tpexChart.includes('10.70'), `櫃買指數日線: the same card on the TPEx index, volume in 億股: ${tpexChart.slice(0, 200)}`)
const txChart = text(render('/market tx', chart('tx', txBars)))
check(txChart.includes('台指期近月日線') && txChart.includes('來源 臺灣期貨交易所'), '台指期近月日線: the same card on the TX near month')
check(txChart.includes('成交量（口）') && txChart.includes('143,277') && txChart.includes('開（點）') && txChart.includes('46,110'), '台指期: whole points and volume in 口')
check(txChart.includes('2026/10/10 合約 2026/10 · 未平倉 125,011 口 · 結算價 46,105'), `台指期: the latest contract month, open interest and settlement: ${txChart.slice(-600)}`)
check(txChart.includes('自 2026/09/29 起收集，無更早歷史') && txChart.includes(TAIFEX_ATTRIBUTION), '台指期: when the history starts and the open-data attribution')
check(collectedSinceText(fullBars) === '自 2026/09/01 起收集，無更早歷史' && collectedSinceText({ ...fullBars, count: STOCK_BARS_LIMIT }) === null, 'collectedSinceText: only when the series is shorter than the request')
check(futuresLatestText(fullBars) === null, 'futuresLatestText: nothing for an index')
check(priceDigits(46041.43, 'index') === 2 && priceDigits(46041.43, 'stock') === 0, 'priceDigits: an index has two decimals, a stock above 500 none')
check(axisDigits(24500, 2) === 0 && axisDigits(8000, 2) === 0 && axisDigits(999, 2) === 2, 'price axis: index labels from 1,000 drop the decimals so 「8,000」 fits the phone gutter (Issue 547)')
check(INDEX_SPECS.map(chartTitle).join() === '加權指數日線,櫃買指數日線,台指期近月日線,S&P 500日線,NASDAQ 綜合指數日線,道瓊工業指數日線,費城半導體指數日線', 'chart titles: 「{名稱}日線」')
// The close-only TAIEX rows still read as before (synthetic bars, volume unit unverified).
const closeOnly = taiexBars([bar('2026-10-22', 46041.43, { open: 46041.43, high: 46041.43, low: 46041.43, volume: 0, source: 'twse_index' })])
const closeOnlyMarkup = text(render('/market close-only', chart('taiex', closeOnly)))
check(closeOnlyMarkup.includes('2026/10/22 46,041.43 46,041.43 46,041.43 46,041.43') && closeOnlyMarkup.includes('成交量（張）'), `close-only TAIEX rows: 開＝高＝低＝收, no unit change: ${closeOnlyMarkup.slice(-300)}`)
// A FRED series: closes only, so a close line and the note; the table keeps each close (Issue 552 null rules).
const fredChart = text(render('/market us chart', chart('spx', fredBars, { row: indexRows()[3] })))
check(fredChart.includes('S&P 500日線') && fredChart.includes(CLOSE_ONLY_NOTE), `FRED chart: titled, with the close-only note: ${fredChart.slice(0, 300)}`)
check(fredChart.includes('2026/10/22 46,041.43') && !fredChart.includes('2026/10/22 46,021.43'), 'FRED chart table: the close, no open/high/low')
check(fredChart.includes('來源 FRED（聖路易聯邦準備銀行）') && fredChart.includes(US_ATTRIBUTION) && fredChart.includes('S&P Dow Jones Indices LLC'), 'FRED chart: FRED named, the attribution and copyright under it')
check(text(render('UsChartFooter', <UsChartFooter row={null} />)).trim() === US_ATTRIBUTION, 'US footer without a row: the attribution alone')
// A FinMind series: candles like a Taiwan index, no close-only note, FinMind named (Issue 568).
const finmindChart = text(render('/market us finmind chart', chart('sox', finmindBars, { row: indexRows()[6] })))
check(!finmindChart.includes(CLOSE_ONLY_NOTE) && !isCloseOnlySeries(finmindRows), `FinMind chart: candles, no close-only note: ${finmindChart.slice(0, 300)}`)
check(finmindChart.includes('來源 FinMind') && finmindChart.includes(US_ATTRIBUTION) && finmindChart.includes('Copyright © 2016, NASDAQ OMX Group, Inc.'),`FinMind chart: FinMind named, the attribution and copyright under it: ${finmindChart.slice(-400)}`)
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
const mixedChart = text(render('/market mixed', chart('taiex', taiexBars(mixedRows))))
check(!mixedChart.includes(CLOSE_ONLY_NOTE) && mixedChart.includes('來源 臺灣證券交易所'), 'a Taiwan index with one close-only day: no close-only note')

// ---- no data: no bars, a failed bars request, a loading request, no overview, no indexes ----
for (const item of INDEX_SPECS) {
  const emptyBars = render(`/market ${item.key}`, chart(item.key, taiexBars([])))
  check(text(emptyBars).includes(chartTitle(item)) && text(emptyBars).includes('無資料') && text(emptyBars).includes('來源未提供日線') && text(emptyBars).includes('資料日期未提供') && !emptyBars.includes('chart-data-table'), `沒有日線（${item.key}）: 無資料＋來源未提供日線, no table: ${text(emptyBars)}`)
  check(text(emptyBars).includes(TAIFEX_ATTRIBUTION) === (item.key === 'tx') && text(emptyBars).includes(US_ATTRIBUTION) === (item.group === 'us'), `沒有日線（${item.key}）: the TX / FRED attribution stays, only on its own chart`)
}
const failedBars = render('/market', chart('tpex', undefined, { interval: 'week', error: new Error('HTTP 502') }))
check(text(failedBars).includes('資料暫時無法載入') && text(failedBars).includes('HTTP 502'), `載入失敗: 資料暫時無法載入: ${text(failedBars)}`)
const loadingBars = render('/market', chart('tx', undefined, { loading: true }))
check(loadingBars.includes('aria-busy="true"'), 'loading: a skeleton')
for (const [name, overview] of [['只有上市', overviewTwseOnly()], ['都沒有', overviewNone()], ['欄位不存在', undefined]] as const) {
  const markup = text(render(`/market ${name}`, <MarketOverviewPanel overview={overview} />))
  check(markup.includes('上櫃大盤資料未取得'), `大盤概況（${name}）: 上櫃大盤資料未取得`)
  check(name === '只有上市' ? markup.includes('46,041.43') && !markup.includes('381.69') && !markup.includes('上櫃為') : markup.includes('上市大盤資料未取得') && !/\d,\d{3}\.\d{2}/.test(markup), `大盤概況（${name}）: the shown exchange as usual, no number for the missing one`)
}
// An API without market_overview.indexes (or before the first collect): seven rows that say they have no data.
const noIndexes = render('/market no indexes', <IndexTablePanel overview={overviewBoth()} selected="taiex" onSelect={() => {}} />)
check(count(noIndexes, 'class="market-index-row') === 7 && count(noIndexes, '無資料：尚未收集') === 7 && !/\d,\d{3}\.\d{2}/.test(text(noIndexes)), `no indexes: seven rows of 無資料：尚未收集, got ${count(noIndexes, '無資料：尚未收集')}`)
const noSession = render('/market no session', <IndexTablePanel overview={overviewWithIndexes(indexRows().map((row) => row.group === 'tw' ? { key: row.key, group: 'tw', exchange: row.exchange, symbol: row.symbol, name: row.name, instrument_type: row.instrument_type, status: 'unavailable', reason: 'no_verified_session', ma60: null, source: row.source } : row))} selected="taiex" onSelect={() => {}} />)
check(count(noSession, '無資料：尚無已驗證的資料日') === 3, 'Taiwan rows without a verified session say so')
const otherScope = { ...overviewBoth(), exchanges: overviewBoth().exchanges.map((row) => row.exchange === 'TPEx' ? { ...row, turnover: { value: 1e8, scope: 'tpex_all', scope_label: '上櫃全部證券' } } : row) }
check(text(render('MarketOverviewView other scope', <MarketOverviewView overview={otherScope} />)).includes('上櫃 1.00 上櫃全部證券'), '大盤概況: an unknown scope shows the API scope_label')
check(JSON.stringify(marketOverviewNotes(overviewNone())) === JSON.stringify(['紅色為上漲、綠色為下跌（台股慣例）']), `資料說明 without data: only the red/green line, got ${JSON.stringify(marketOverviewNotes(overviewNone()))}`)
check(!indexTableNotes(overviewBoth()).some((line) => line.startsWith('Copyright')), '資料說明 without US data: no copyright notice')

// ---- 加權指數與季線, Issue 561: above, below or equal, too few closes, and no data ----
const ma60 = (extra: Partial<TaiexMa60>): TaiexMa60 => ({
  trading_date: '2026-10-22', required_closes: 60, status: 'available', close: 46041.43, ma60: 44012.5, above: true, position: 'above', close_count: 250,
  segments: [
    { start: '2026-09-01', end: '2026-10-22', sessions: 37, ongoing: true, starts_before_window: false },
    { start: '2026-06-02', end: '2026-07-15', sessions: 31, ongoing: false, starts_before_window: false },
    { start: '2025-10-28', end: '2025-10-28', sessions: 1, ongoing: false, starts_before_window: true },
  ],
  segment_window: { start: '2025-10-28', end: '2026-10-22', sessions: 250, max_segments: 3 },
  source: { label: '臺灣證券交易所', bar_source: 'twse_index_ohlcv', formula_version: 'indicators/v1', computed_at: '2026-10-22T10:40:00+00:00', data_as_of: '2026-10-22' },
  ...extra,
})
const ma60Panel = (item: TaiexMa60 | undefined) => {
  const markup = render(`/market ma60 ${item?.status}`, <MarketOverviewPanel overview={{ ...overviewBoth(), taiex_ma60: item }} />)
  return { markup, strip: markup.slice(markup.indexOf('class="market-ma60"')), notes: marketOverviewNotes({ ...overviewBoth(), taiex_ma60: item }) }
}
const above = ma60Panel(ma60({}))
check(text(above.strip).includes('加權指數與季線（MA60） 點'), `季線: the strip's label and unit: ${text(above.strip).slice(0, 120)}`)
check(text(above.strip).includes('加權指數 46,041.43（2026/10/22） 在季線之上 （季線 44,012.50）'), `季線（之上）: close, date, position and MA60: ${text(above.strip).slice(0, 200)}`)
check(text(above.strip).includes('近 250 個交易日在季線之上：2026/09/01–2026/10/22（37 日，持續中）；2026/06/02–2026/07/15（31 日）；2025/10/28（或更早）（1 日）'), `季線: the newest runs first, an open start said: ${text(above.strip)}`)
check(above.markup.indexOf('class="market-ma60"') > above.markup.indexOf('market-overview-grid'), '季線: under the four widgets, in the 大盤概況 panel')
check(!/tone-(up|down)/.test(above.strip.slice(0, above.strip.indexOf('</section>'))), '季線: no up/down colors (background, not a signal)')
check(above.notes.includes(MA60_NOTE) && above.notes.includes(MA60_BACKGROUND_NOTE), `季線 資料說明: the definition and that it is background only: ${JSON.stringify(above.notes)}`)
const below = ma60Panel(ma60({ close: 43000, ma60: 44012.5, above: false, position: 'below', segments: [{ start: '2026-09-01', end: '2026-10-21', sessions: 36, ongoing: false, starts_before_window: false }] }))
check(text(below.strip).includes('加權指數 43,000.00（2026/10/22） 在季線之下 （季線 44,012.50）') && !text(below.strip).includes('在季線之上 （'), `季線（之下）: ${text(below.strip).slice(0, 200)}`)
check(text(below.strip).includes('2026/09/01–2026/10/21（36 日）') && !text(below.strip).includes('持續中'), '季線（之下）: the last run has ended')
const equal = ma60Panel(ma60({ close: 44012.5, above: false, position: 'equal', segments: [] }))
check(text(equal.strip).includes('與季線持平 （季線 44,012.50）') && text(equal.strip).includes('近 250 個交易日沒有在季線之上的日子'), `季線（持平）: not above, no runs: ${text(equal.strip).slice(0, 200)}`)
const short = ma60Panel({ trading_date: '2026-10-22', required_closes: 60, status: 'insufficient', reason: 'insufficient_closes', close_count: 59 })
check(text(short.strip).includes('季線資料不足：加權指數到 2026/10/22 只有 59 個交易日收盤，季線需要 60 個'), `季線（資料不足）: the reason: ${text(short.strip).slice(0, 200)}`)
check(!/季線之[上下]|持平/.test(text(short.markup)), `季線（資料不足）: no position anywhere on the panel: ${text(short.markup)}`)
check(short.notes.includes(MA60_NOTE), '季線（資料不足）: 資料說明 explains the 60 closes')
for (const [item, reason] of [
  [{ trading_date: null, required_closes: 60, status: 'unavailable', reason: 'no_verified_session' }, '季線無資料：尚無已驗證的資料日'],
  [{ trading_date: '2026-10-22', required_closes: 60, status: 'unavailable', reason: 'not_collected' }, '季線無資料：加權指數日線未收集'],
  [{ trading_date: '2026-10-22', required_closes: 60, status: 'unavailable', reason: 'row_date_mismatch', latest_trading_date: '2026-10-21' }, '季線無資料：加權指數日線最新為 2026/10/21，不是資料日'],
  [{ trading_date: '2026-10-22', required_closes: 60, status: 'unavailable', reason: 'indicator_not_computed' }, '季線無資料：季線尚未計算'],
  [{ trading_date: '2026-10-22', required_closes: 60, status: 'unavailable', reason: 'ma60_unavailable', null_reason: 'invalid_bar' }, '季線無資料：當日收盤無法計算季線'],
  [undefined, '季線無資料：尚未提供'],
] as const) {
  const panel = ma60Panel(item as TaiexMa60 | undefined)
  check(text(panel.strip).includes(reason) && !/季線之[上下]|持平/.test(text(panel.markup)), `季線（${item?.reason ?? '欄位不存在'}）: 「${reason}」, no position: ${text(panel.strip).slice(0, 160)}`)
  check(!panel.notes.includes(MA60_NOTE), `季線（${item?.reason ?? '欄位不存在'}）: no MA60 definition in 資料說明`)
}

// ---- pure helpers ----
const items = summaryItems(overviewTwseOnly())
check(items[0].close === '46,041.43' && items[0].pct === '-1.81%' && items[0].tone === 'tone-down' && items[1].close === null, `summary items: ${JSON.stringify(items)}`)
const small = summaryItems({ ...overviewBoth(), exchanges: overviewBoth().exchanges.map((row) => row.exchange === 'TWSE' ? { ...row, index: { ...row.index!, change_pct: -0.0049 } } : row) })
check(small[0].pct === '-0.49%' && small[0].tone === 'tone-down', `a small fall (-0.49%) is still green, got ${small[0].tone}`)

// ---- layout rules the static markup cannot show ----
const css = fs.readFileSync(path.join(__dirname, '..', 'styles.css'), 'utf8')
check(!css.includes('market-overview-more') && !css.includes('market-us-'), 'Issue 549/564: no folded overview and no US panel styles left')
check(/\.market-summary-item \{[^}]*white-space:\s*nowrap/.test(css), 'summary: an index item never breaks inside')
check(/\.market-index-row\.is-selected \{[^}]*var\(--color-primary-soft\)/.test(css) && /\.market-index-row\.is-selected td:first-child \{[^}]*inset 3px 0 0 var\(--color-primary\)/.test(css), '指數總表: the selected row has the selection background and a primary bar')
const phone = css.slice(css.indexOf('/* 指數總表 on phones'))
check(/\.market-index-table tr \{[^}]*display: grid;[^}]*grid-template-columns: minmax\(0, 1fr\) auto auto auto/.test(phone) && /\.market-index-table \.market-index-date \{[^}]*grid-row: 2/.test(phone) && /\.market-index-table \.market-index-ma60 \{[^}]*grid-row: 2/.test(phone), '指數總表 on phones: each row two lines (name and numbers, then date and MA60), no horizontal scroll')

if (failures.length) throw new Error(`${failures.length} of ${checks} market checks failed:\n- ${failures.join('\n- ')}`)
