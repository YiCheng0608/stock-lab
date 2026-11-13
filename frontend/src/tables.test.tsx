import type { ReactElement } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'

import * as AppModule from './App'
import { ScoreDetails } from './candidates/CandidateViews'
import { completeItem } from './candidates/candidates.fixtures'
import * as ui from './components/ui'
import { NavSearch } from './components/NavSearch'
import { StockBarsChart } from './stock/StockBarsChart'
import { barsResponse, tradedBar } from './stock/stockBars.fixtures'
import { ThemeMemberTable } from './themes/ThemeViews'
import type { ActionSummary, InstrumentDetail, RawPayload, StockDirectoryRow } from './types'
import { formatCanonicalShareLots, formatTableChip, formatTableNumber, formatTableVolume } from './units'

// The frontend ships no Node typings; scripts/ci-test.cjs runs this module under Node, so declare what it uses.
declare const require: (id: string) => unknown
declare const __dirname: string
type DirEntry = { name: string; isDirectory(): boolean }
const fs = require('node:fs') as { readdirSync(dir: string, options: { withFileTypes: true }): DirEntry[]; readFileSync(file: string, encoding: 'utf8'): string }
const path = require('node:path') as { join(...parts: string[]): string; relative(from: string, to: string): string; sep: string }

// Table alignment and number formats (#267; DESIGN_SYSTEM §3, §5, §5.1; UI_COPY_SPEC §8.3).
// Every check runs and the failures are listed together, so one run shows each table that is off.
const failures: string[] = []
let checks = 0
const check = (condition: boolean, message: string) => { checks++; if (!condition) failures.push(message) }
// The candidates' "加入追蹤" button (#253) reads the query client.
const render = (name: string, element: () => ReactElement): string => {
  try { return renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}><StaticRouter location="/">{element()}</StaticRouter></QueryClientProvider>) } catch (error) {
    failures.push(`${name}: render failed (${error instanceof Error ? error.message.split('\n')[0] : String(error)})`)
    return ''
  }
}
// Looked up by name so a missing export is one listed failure instead of a build error.
const exported = (module: object, from: string, name: string) =>
  ((module as Record<string, unknown>)[name] ?? (() => { throw new Error(`${from} does not export ${name}`) })) as (props: Record<string, unknown>) => ReactElement
const component = (name: string) => exported(AppModule, 'App', name)
const DataTable = ui.DataTable

// ---- one table: the num class marks the same columns in th and in every body row ----
const classes = (cell: string) => / class="([^"]*)"/.exec(cell)?.[1].split(' ') ?? []
const cells = (row: string, tag: 'th' | 'td') => row.match(new RegExp(`<${tag}(?: [^>]*)?>`, 'g')) ?? []
function tables(markup: string): string[] {
  return markup.match(/<table[\s\S]*?<\/table>/g) ?? []
}
// Numeric headers without a unit, each with the reason (UI_COPY_SPEC §8.4); everything else ends in 「（單位）」.
const UNITLESS_HEADERS: Record<string, string> = {
  排名: 'an ordinal; the cell is #N',
  資料日: 'a date column',
  資料批次: 'a batch identifier, not a quantity',
  RR: 'the cell carries 倍 (UI_COPY_SPEC §10)',
  原值: 'mixed units per sub-item; each cell carries its own unit',
  百分位: '0–100; the scale is in the table note, and a longer header would overflow the 390px card',
  相對報酬: 'same-board percentile 0–100; the scale is in the table note',
  廣度: 'same-board percentile 0–100; the scale is in the table note',
  量能: 'same-board percentile 0–100; the scale is in the table note',
  法人: 'same-board percentile 0–100; the scale is in the table note',
  催化劑: 'same-board percentile 0–100; the scale is in the table note',
}
const hasUnit = (label: string) => /（[^（）]+）$/.test(label) || label in UNITLESS_HEADERS
function checkAligned(name: string, markup: string, numericHeaders: string[]) {
  const found = tables(markup)
  check(found.length > 0, `${name}: no table rendered`)
  for (const table of found) {
    const head = /<thead>([\s\S]*?)<\/thead>/.exec(table)?.[1] ?? ''
    const headers = cells(head, 'th')
    const labels = (head.match(/<th(?: [^>]*)?>[\s\S]*?<\/th>/g) ?? []).map((th) => th.replace(/<[^>]+>/g, ''))
    const numeric = headers.map((th) => classes(th).includes('num'))
    for (const label of numericHeaders) {
      const index = labels.indexOf(label)
      check(index >= 0 && numeric[index], `${name}: header 「${label}」 is not right-aligned (th without num)`)
    }
    // #463 (UI_COPY_SPEC §8.4): every numeric column names its unit in the header, e.g. 「收盤（元）」.
    labels.forEach((label, index) => {
      if (numeric[index]) check(hasUnit(label), `${name}: numeric header 「${label}」 names no unit; write it as 「${label}（單位）」 (UI_COPY_SPEC §8.4)`)
    })
    const rows = (/<tbody>([\s\S]*?)<\/tbody>/.exec(table)?.[1] ?? '').match(/<tr[\s\S]*?<\/tr>/g) ?? []
    for (const row of rows) {
      const data = cells(row, 'td')
      if (data.some((td) => / colSpan="| colspan="/.test(td))) continue // a group title row spans the whole table
      check(data.length === headers.length, `${name}: a body row has ${data.length} cells for ${headers.length} headers`)
      data.forEach((td, index) => {
        check(classes(td).includes('num') === numeric[index], `${name}: column 「${labels[index]}」 th and td disagree on num`)
      })
    }
    check(!/numeric-cell/.test(table), `${name}: numeric-cell is merged into num`)
  }
}
const bodyText = (markup: string) => markup.replace(/<[^>]+>/g, '\u0001').split('\u0001').filter(Boolean)

// ---- the shared table: one column definition sets th and td together ----
type SharedRow = { id: string; name: string; value: number }
const SharedTable = (DataTable ?? exported(ui, 'components/ui', 'DataTable')) as typeof ui.DataTable<SharedRow>
const shared = render('DataTable', () => <SharedTable
  note="單位：張"
  rows={[{ id: 'a', name: '甲', value: 1 }, { id: 'b', name: '乙', value: 2 }]}
  rowKey={(row) => row.id}
  columns={[{ key: 'name', header: '名稱', cell: (row) => row.name }, { key: 'value', header: '數值（張）', num: true, cell: (row) => String(row.value) }]}
/>)
checkAligned('DataTable', shared, ['數值（張）'])
check(shared.includes('<p class="table-note">單位：張</p>'), 'DataTable keeps the unit note above the table')

// ---- no table is written by hand outside the shared component ----
// scripts/ci-test.cjs compiles this file to CJS, so __dirname is src.
const srcRoot = __dirname
function sources(dir: string, found: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) sources(full, found)
    else if (/\.tsx$/.test(entry.name) && !/\.test\.tsx$/.test(entry.name)) found.push(full)
  }
  return found
}
for (const file of sources(srcRoot)) {
  const name = path.relative(srcRoot, file).split(path.sep).join('/')
  if (name === 'components/ui/Table.tsx') continue
  const text = fs.readFileSync(file, 'utf8')
  check(!/<(table|th|td)[\s>]/.test(text), `${name}: writes <table>/<th>/<td> by hand; use DataTable so th and td share num`)
  check(!text.includes('numeric-cell'), `${name}: uses numeric-cell; DataTable column num replaces it`)
}

// ---- whole lots: round half away from zero, thousands separators, odd lots show 0 ----
for (const [shares, lots] of [
  ['0', '0'], ['1', '0'], ['-1', '0'], ['499', '0'], ['-499', '0'], ['500', '1'], ['-500', '-1'], ['999', '1'],
  ['1500', '2'], ['-7500', '-8'], ['53500', '54'], ['57797', '58'], ['29796590', '29,797'], ['-12694626', '-12,695'],
  ['9223372036854775807', '9,223,372,036,854,776'], ['-9223372036854775807', '-9,223,372,036,854,776'],
]) check(formatCanonicalShareLots(shares) === lots, `lots: ${shares} shares should be ${lots}, got ${formatCanonicalShareLots(shares)}`)
check(formatCanonicalShareLots('46116860184273879035', 5) === '46,116,860,184,273,879', '5-day sum rounds on the exact string')
check(formatCanonicalShareLots('184467440737095516140', 20) === '184,467,440,737,095,516', '20-day sum rounds on the exact string')
check(formatCanonicalShareLots('999999999999999999500', 20) === null, 'over-limit sums are still rejected')
check(formatTableChip(57797, 'twse_t86') === '+58' && formatTableChip(-7500, 'twse_t86') === '-8', 'institutional flow shows signed whole lots')
check(formatTableChip(493, 'twse_t86') === '0' && formatTableChip(-266, 'tpex_3insti') === '0', 'an odd-lot flow is 0 without a sign')
check(formatTableChip(-196, 'twse_margin', true) === '-196' && formatTableChip(5, 'twse_margin', true) === '+5', 'margin is already lots, no decimals')
check(formatTableVolume(29796590, 'twse', '29796590') === '29,797' && formatTableVolume(1250, 'twse') === '1', 'volume is whole lots')

// ---- fixed decimals within a column ----
check(formatTableNumber(21.1, 2) === '21.10' && formatTableNumber(1234.5, 2) === '1,234.50' && formatTableNumber(3, 0) === '3', 'table numbers keep their fixed decimals')
check(formatTableNumber(-0.001, 2) === '0.00', 'a value that rounds to zero has no minus sign')

// ---- each table of the #266 review ----
const t86 = (day: string, at: string) => ({ source: 'twse_t86', data_as_of: day, collected_at: at })
const margin = (day: string, at: string) => ({ source: 'twse_margin', data_as_of: day, collected_at: at })
const chipRows = [
  { date: '2026-10-20', foreign_buy: 57797, trust_buy: 0, dealer_buy: -7500, margin_balance: null, margin_change: -196, short_balance: null, borrowed_sell: null, day_trade_ratio: null, source: 'twse_t86+twse_margin', data_as_of: '2026-10-20', collected_at: null, institutional: t86('2026-10-20', '2026-10-20T10:30:15Z'), margin: margin('2026-10-20', '2026-10-20T13:30:18Z') },
  { date: '2026-10-21', foreign_buy: 493, trust_buy: null, dealer_buy: 1000, margin_balance: null, margin_change: 3, short_balance: null, borrowed_sell: null, day_trade_ratio: null, source: 'twse_t86+twse_margin', data_as_of: '2026-10-21', collected_at: null, institutional: t86('2026-10-21', '2026-10-21T10:30:14Z'), margin: margin('2026-10-21', '2026-10-21T13:30:17Z') },
] as unknown as InstrumentDetail['chips']
const ChipTable = component('ChipTable')
const chips = render('ChipTable', () => <ChipTable {...{ rows: chipRows }} />)
checkAligned('個股籌碼', chips, ['外資買賣超（張）', '投信（張）', '自營商（張）', '融資增減（張）'])
check(bodyText(chips).includes('+58') && bodyText(chips).includes('-8') && !chips.includes('57.797'), '個股籌碼: institutional flow is whole lots')
check(chips.includes('57,797'), '個股籌碼: the original share count stays in the source details')
// #395: each value group names its own file, data date and collection time.
const plainText = (markup: string) => markup.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, '\n')
const chipText = plainText(chips)
check(chipText.includes('法人：臺灣證券交易所 三大法人（twse_t86） · 資料截至：2026/10/20 · 收集：2026/10/20 18:30'), '個股籌碼: the institutional line has its own source and time')
check(chipText.includes('融資：臺灣證券交易所 融資融券（twse_margin） · 資料截至：2026/10/20 · 收集：2026/10/20 21:30'), '個股籌碼: the margin line has its own source and time')
// A row without a margin file shows no margin value and says so; one without an institutional file likewise.
// The row-level source still names both files, so a column reading it instead of its group would show the value.
const onlyInstitutional = [{ ...chipRows[0], margin: null }, { ...chipRows[1], institutional: null }] as unknown as InstrumentDetail['chips']
const partial = render('ChipTable (one group)', () => <ChipTable {...{ rows: onlyInstitutional }} />)
const partialText = plainText(partial)
check(partialText.includes('融資：無資料') && partialText.includes('法人：無資料'), '個股籌碼: a missing group is labelled 無資料')
check(!bodyText(partial).includes('-196') && bodyText(partial).includes('+58') && bodyText(partial).includes('+3') && !bodyText(partial).includes('+1'), '個股籌碼: a value shows only under its own group source')

const barRows = [
  { date: '2026-10-21', open: 21, high: 21.5, low: 20.95, close: 21.1, adj_close: 21.1, volume: 1500, volume_exact: '1500', turnover: 1, turnover_status: 'available', turnover_reason: null, source: 'twse', data_as_of: '2026-10-21', collected_at: null, is_suspended: false },
  { date: '2026-10-20', open: 20.5, high: 21, low: 20.5, close: 20.5, adj_close: 20.5, volume: 499, volume_exact: '499', turnover: 1, turnover_status: 'available', turnover_reason: null, source: 'twse', data_as_of: '2026-10-20', collected_at: null, is_suspended: false },
] as unknown as InstrumentDetail['bars']
const BarTable = component('BarTable')
const bars = render('BarTable', () => <BarTable {...{ rows: barRows, instrumentType: 'stock' }} />)
checkAligned('原始行情', bars, ['收盤（元）', '最高（元）', '最低（元）', '成交量（張）', '成交股數（股）'])
check(bodyText(bars).includes('21.10') && bodyText(bars).includes('20.50') && bodyText(bars).includes('2'), '原始行情: prices keep two decimals under 50, volume is whole lots')

const directoryRows = [
  { exchange: 'TWSE', symbol: '1742', name: '台蠟', instrument_type: 'stock', is_watchlisted: false, status: 'active', latest_price: 21.1, price_as_of: '2026-10-22' },
  { exchange: 'TWSE', symbol: '2330', name: '台積電', instrument_type: 'stock', is_watchlisted: false, status: 'active', latest_price: 2510, price_as_of: '2026-10-22' },
] as unknown as StockDirectoryRow[]
const StockTable = component('StockTable')
const directory = render('StockTable', () => <StockTable {...{ rows: directoryRows, dataAsOf: '2026-10-22' }} />)
checkAligned('個股清單', directory, ['最近收盤（元）'])
check(bodyText(directory).includes('21.10') && bodyText(directory).includes('2,510.00'), '個股清單: a column across stocks keeps two decimals')
// #300 phone cards (DESIGN_SYSTEM §5 個股清單, §5.1): name and close, then (#666) the action with 市場 · 類型 in small type at
// its right; no table to scroll.
const count = (markup: string, needle: string) => markup.split(needle).length - 1
const plain = (markup: string) => markup.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, '\n').split('\n').map((line) => line.trim()).filter(Boolean)
const directoryCards = directory.slice(directory.indexOf('class="card-list stock-cards"'))
const stockCards = directoryCards.split('<div class="stock-card">').slice(1)
check(stockCards.length === 2 && !/<table/.test(directoryCards), `個股清單手機卡: one card per row and no table, got ${stockCards.length}`)
check(plain(stockCards[0]).join('|') === '1742 台蠟|21.10|尚無研究動作|上市 · 股票', `個股清單手機卡: field order, got ${plain(stockCards[0]).join('|')}`)
check(plain(stockCards[1]).slice(0, 2).join('|') === '2330 台積電|2,510.00', `個股清單手機卡: two decimals with thousands, got ${plain(stockCards[1]).join('|')}`)
check(/<div class="stock-card-price">[^<]*<\/div>/.test(stockCards[0]), '個股清單手機卡: the close is one text run')
// #666: two lines; the second is the action, then 市場 · 類型 (the same text as before, in small type).
check(/<div class="stock-card-foot"><div class="stock-card-action">尚無研究動作<\/div><div class="stock-card-meta">上市 · 股票<\/div><\/div>/.test(stockCards[0]), `個股清單手機卡: action then 市場 · 類型 on one line, got ${stockCards[0]}`)
// #666: the unit note left the table and the cards for the title's 說明 fold.
check(!directory.includes('class="table-note"') && !plain(directory).some((line) => line.startsWith('單位：')), '個股清單: no unit note over the table or the cards (it is in 說明)')
const staleDirectory = render('StockTable stale', () => <StockTable {...{ rows: [{ ...directoryRows[0], price_as_of: '2026-10-20' }], dataAsOf: '2026-10-22' }} />)
const staleCard = staleDirectory.slice(staleDirectory.indexOf('<div class="stock-card">'))
check(plain(staleCard).slice(0, 3).join('|') === '1742 台蠟|21.10|（2026/10/20）', `個股清單手機卡: an older close carries its date under it, got ${plain(staleCard).join('|')}`)
const manyRows = Array.from({ length: 12 }, (_, i) => ({ ...directoryRows[0], symbol: String(1100 + i), name: `標的${i + 1}` })) as StockDirectoryRow[]
const manyDirectory = render('StockTable 12', () => <StockTable {...{ rows: manyRows, dataAsOf: '2026-10-22' }} />)
const manyCards = manyDirectory.slice(manyDirectory.indexOf('class="card-list stock-cards"'))
const foldedCards = manyCards.slice(manyCards.indexOf('<details class="details card-list-rest">'))
check(count(manyCards, '<div class="stock-card">') === 12 && count(foldedCards, '<div class="stock-card">') === 2 && foldedCards.includes('<summary>顯示其餘 2 檔</summary>') && count(manyDirectory, '<tr') === 13, '個股清單: the table keeps 12 rows, the phone shows 10 cards and folds 2')
// Issue 602: one research-action column (data_quality only repeated it); short of data, the first missing item under it.
const directoryHeaders = (/<thead>([\s\S]*?)<\/thead>/.exec(directory)?.[1] ?? '').replace(/<[^>]+>/g, '|').split('|').filter(Boolean)
check(directoryHeaders.join('|') === '代號|名稱|交易所|類型|最近收盤（元）|目前研究動作', `個股清單: one action column, got ${directoryHeaders.join('|')}`)
const gapRows = [
  { ...directoryRows[0], action_state: 'data_insufficient', action_label_zh: '資料不足', data_quality: 'partial', missing_data_priority: [{ field: 'bars_20d', priority: 'market_base', priority_label: '市場基礎層', reason: '' }] },
  // An action that is not 資料不足 keeps its own label even when data_quality is partial (a holding's manual review).
  { ...directoryRows[1], action_state: 'manual_review', action_label_zh: '需人工判讀', data_quality: 'partial', missing_data_priority: [{ field: 'bars_20d', priority: 'market_base', priority_label: '市場基礎層', reason: '' }] },
  { ...directoryRows[1], symbol: '2002', name: '中鋼', action_state: 'no_condition', action_label_zh: '暫無條件', data_quality: 'complete', missing_data_priority: [] },
] as unknown as StockDirectoryRow[]
const gapDirectory = render('StockTable gaps', () => <StockTable {...{ rows: gapRows, dataAsOf: '2026-10-22' }} />)
const gapTableRows = (/<tbody>([\s\S]*?)<\/tbody>/.exec(gapDirectory)?.[1] ?? '').split('<tr').slice(1).map((row) => plain('<tr' + row).join('|'))
check(gapTableRows[0]?.endsWith('|暫不行動|缺少 20 日有效行情'), `個股清單: 資料不足 shows the first missing item under the label, got ${gapTableRows[0]}`)
check(gapTableRows[1]?.endsWith('|需人工判讀') && !gapTableRows[1].includes('缺少') && !gapTableRows[1].includes('不足'), `個股清單: a partial row with another action shows only its label, got ${gapTableRows[1]}`)
check(gapTableRows[2]?.endsWith('|暫無條件'), `個股清單: a complete row shows its label alone, got ${gapTableRows[2]}`)
check(!gapDirectory.includes('class="pill"'), '個股清單: no separate 策略判斷資料 pill on the table or the cards')
const gapCards = gapDirectory.slice(gapDirectory.indexOf('class="card-list stock-cards"')).split('<div class="stock-card">').slice(1)
check(plain(gapCards[0] ?? '').slice(-3).join('|') === '暫不行動|缺少 20 日有效行情|上市 · 股票' && plain(gapCards[1] ?? '').slice(-2)[0] === '需人工判讀', `個股清單手機卡: the same action cell, got ${plain(gapCards[0] ?? '').join('|')} / ${plain(gapCards[1] ?? '').join('|')}`)
const stockDirectoryGap = AppModule.stockDirectoryGap
check(stockDirectoryGap({ action_state: 'data_insufficient', missing_data_priority: [] }) === null && stockDirectoryGap({ action_state: 'data_insufficient' }) === null, '個股清單: no missing item, no note')
// #666: the old eyebrow, lead and unit note are one 說明 fold on the title line, closed, with the same sentences.
const StockDirectoryHelp = component('StockDirectoryHelp')
const directoryHelp = render('StockDirectoryHelp', () => <StockDirectoryHelp />)
check(directoryHelp.startsWith('<details class="details page-help"><summary>說明</summary>'), `個股清單說明: a closed 說明 fold, got ${directoryHelp.slice(0, 80)}`)
check(plain(directoryHelp).join('|') === '說明|市場標的目錄：股票、ETF 與新上市標的分開標示；行動與缺資料優先級只來自已驗證官方快照。|單位：價格為各標的報價幣別的元，指數為點。空白表示未提供資料或數值待核實；最近收盤早於最新交易日時，下方括號標出它的日期。', `個股清單說明: the same sentences as before, got ${plain(directoryHelp).join('|')}`)
const stockDirectoryCountText = (AppModule as unknown as { stockDirectoryCountText?: (meta: Record<string, unknown>) => string }).stockDirectoryCountText
check(stockDirectoryCountText?.({ total: 1234 }) === '共 1,234 筆' && stockDirectoryCountText?.({}) === '共 0 筆', '個股清單: the filter row ends with 「共 N 筆」')

// Issue 602: sorting is the API's sort parameter, and changing it (or any filter) starts again from page 1.
const { changeStockDirectory, stockDirectoryParams, STOCK_SORTS, DEFAULT_STOCK_SORT } = AppModule
const onPage3 = { search: '台', page: 3, type: 'stock', watchlist: true, sort: DEFAULT_STOCK_SORT }
const sorted = changeStockDirectory(onPage3, { sort: 'close_desc' })
check(sorted.page === 1 && sorted.sort === 'close_desc' && sorted.search === '台' && sorted.type === 'stock' && sorted.watchlist, `個股清單排序: a new sort keeps the filters and goes to page 1, got ${JSON.stringify(sorted)}`)
check(JSON.stringify(stockDirectoryParams(sorted)) === JSON.stringify({ q: '台', page: 1, page_size: 30, instrument_type: 'stock', watchlist_only: true, sort: 'close_desc' }), `個股清單排序: the request carries sort, got ${JSON.stringify(stockDirectoryParams(sorted))}`)
check(stockDirectoryParams({ ...onPage3, search: '', type: '', watchlist: false }).sort === undefined, '個股清單排序: the default order sends no sort (same first-page request as before)')
check(changeStockDirectory(onPage3, { type: 'etf' }).page === 1 && changeStockDirectory(onPage3, { search: '2330' }).page === 1, '個股清單: a filter or search change goes to page 1')
check(STOCK_SORTS.map((option) => option.id).join(',') === 'type,symbol,name,close_desc,close_asc' && DEFAULT_STOCK_SORT === 'type', `個股清單排序: the API's sort values, got ${STOCK_SORTS.map((option) => option.id).join(',')}`)
const sortSelect = render('StockSortSelect', () => <AppModule.StockSortSelect value="close_asc" onChange={() => undefined} />)
check(plain(sortSelect).join('|') === '排序|類型（股票在前）|代號|名稱|最近收盤高到低|最近收盤低到高' && /<option value="close_asc" selected="">/.test(sortSelect) && sortSelect.includes('aria-label="個股排序"'), `個股清單排序: the select lists every sort and shows the current one, got ${sortSelect}`)
// Issue 602: the API refuses a q over 100 characters; the navbar box cannot hold more.
const navSearch = render('NavSearch', () => <NavSearch />)
check(navSearch.includes('maxLength="100"') || navSearch.includes('maxlength="100"'), `導覽列搜尋: input is capped at the API's q length, got ${navSearch}`)

const members = render('ThemeMemberTable', () => <ThemeMemberTable rows={[
  { exchange: 'TWSE', symbol: '1742', name: '台蠟', role: 'member', latest_bar: { date: '2026-10-22', close: 21.1 }, change: 0.1, change_pct: 0.0047619, change_status: 'known', turnover: 1.2e8, turnover_status: 'available', excess_return_5d: 0.01, excess_return_20d: -0.1 },
  { exchange: 'TWSE', symbol: '2330', name: '台積電', role: 'leader', latest_bar: { date: '2026-10-22', close: 2510 }, change: -10, change_pct: -0.0039683, change_status: 'known', turnover: 4.5e10, turnover_status: 'available', excess_return_5d: 0.002, excess_return_20d: 0.03 },
] as never} withEvidence={false} membersAsOf="2026-10-22" />)
checkAligned('族群成員', members, ['收盤（元）', '漲跌幅（%）', '成交金額（億元）', '5 日相對（%）', '20 日相對（%）'])
check(bodyText(members).includes('21.10') && bodyText(members).includes('2,510.00'), '族群成員: closes keep two decimals')
check(['+0.48', '-0.40', '1.20', '450.00', '+1.00', '-10.00', '+0.20', '+3.00'].every((value) => bodyText(members).includes(value)), `族群成員: percent and 億元 keep two decimals, got ${bodyText(members).join('|')}`)

const details = render('ScoreDetails', () => <ScoreDetails item={completeItem()} open />)
checkAligned('個股頁候選評分細節', details, ['原值', '百分位', '權重（%）'])
const detailHeaders = (/<thead>([\s\S]*?)<\/thead>/.exec(details)?.[1] ?? '').match(/<th[\s>]/g) ?? []
check(detailHeaders.length <= 4, `個股頁候選評分細節: ${detailHeaders.length} columns in a card; the group title belongs on its own row (§5.1)`)
// Today list (#276): the levels, close, RR and total are numeric in th and every row.
// The today list is not a table since Issue 510 (one list at every width, DESIGN_SYSTEM §5 候選列表); its numbers are checked in today/today.test.tsx.

const chart = render('StockBarsChart', () => <StockBarsChart data={barsResponse([tradedBar('2026-10-21', 21.1, 70), tradedBar('2026-10-22', 21.15, 71)])} interval="day" onIntervalChange={() => undefined} loading={false} error={null} />)
checkAligned('K 線資料', chart, ['開（元）', '高（元）', '低（元）', '收（元）', '成交量（張）'])

const runs = [{ id: 1, updated_at: '2026-10-22T10:00:00+00:00', source: 'twse', run_date: '2026-10-22', status: 'success', records: 1234, data_as_of: '2026-10-22', error: null }]
const IngestionRunTable = component('IngestionRunTable')
checkAligned('系統頁擷取狀態', render('IngestionRunTable', () => <IngestionRunTable {...{ rows: runs }} />), ['資料量（筆）'])
const rawRows = [{ id: 1, collected_at: '2026-10-22', ingestion_run_id: 12, source: 'twse', data_as_of: '2026-10-22', endpoint: 'STOCK_DAY_ALL', sha256: 'abc' }] as unknown as RawPayload[]
const RawTable = component('RawTable')
checkAligned('系統頁原始來源', render('RawTable', () => <RawTable {...{ rows: rawRows }} />), ['資料批次'])
const BacktestTable = component('BacktestTable')
checkAligned('技術回測', render('BacktestTable', () => <BacktestTable {...{ groups: [{ strategy: 'breakout_v1', version: '1.0.0', instrument_type: 'stock', horizon: 5, sample: 12, comparable: 10, incomparable: 2, assessment: 'complete' }] }} />), ['期限（交易日）', '樣本（筆）', '可比（筆）', '不可比（筆）'])
const BackfillRunTable = component('BackfillRunTable')
checkAligned('回補紀錄', render('BackfillRunTable', () => <BackfillRunTable {...{ runs: [{ id: 1, updated_at: '2026-10-22T10:00:00+00:00', metadata: { start_date: '2026-10-01', end_date: '2026-10-22' }, status: 'success', records: 99, error: null }] }} />), ['資料量（筆）'])

// The runner keeps only the first lines of an error, so the full list goes to stderr first.
if (failures.length) {
  console.error(`table checks failed:\n- ${failures.join('\n- ')}`)
  throw new Error(`${failures.length} of ${checks} table checks failed (listed above)`)
}
console.log('tables', checks, 'checks passed')
