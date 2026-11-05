import { renderToStaticMarkup } from 'react-dom/server'

import type { FundamentalSnapshot } from '../types'
import { StockFundamentalsPanel } from './StockFundamentalsPanel'
import { FUNDAMENTALS_TITLE, NOT_PROVIDED, fundamentalPeriodLabel, fundamentalsEmptyReason, revenueText } from './stockFundamentals'
import { STOCK_TABS, parseStockTab } from './stockTabs'

// Standalone regression module for the stock page 「財務」 tab (Issue 528; UI_COPY_SPEC §8.2 財務分頁, DESIGN_SYSTEM §5
// 個股財務表): the collected quarterly revenue and EPS, ROE 來源未提供 instead of 0, and one reason sentence when there is
// no row. The cutoff itself (no report whose 可得日 is after as_of, #529) is the API's filter, pinned in backend/tests/test_stock_fundamentals.py.
const check = (condition: boolean, message: string) => { if (!condition) throw new Error(message) }
const text = (markup: string) => markup.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
const row = (extra: Partial<FundamentalSnapshot> = {}): FundamentalSnapshot => ({
  period_end: '2026-06-30', fiscal_period: 'Q2', announcement_date: '2026-10-30',
  revenue: 2404483690, eps: 49.33, roe: null, source: 'mops_fundamental', data_as_of: '2026-06-30', ...extra,
})
const label = (source: string) => (source === 'mops_fundamental' ? '公開資訊觀測站 季報' : source)
const panel = (rows: FundamentalSnapshot[], instrumentType = 'stock', asOf: string | null = null) =>
  renderToStaticMarkup(<StockFundamentalsPanel rows={rows} instrumentType={instrumentType} asOf={asOf} sourceLabel={label} />)

// ---- the tab ----
check(STOCK_TABS.map((tab) => tab.label).join('／') === '圖表與指標／法人籌碼／財務／新聞與公告／研究條件／資料說明', `財務 sits after 法人籌碼, got ${STOCK_TABS.map((tab) => tab.label).join('／')}`)
check(parseStockTab('financials') === 'financials', '?tab=financials opens 財務')

// ---- rows: period, 億元, EPS, ROE, 可得日, source ----
const q3 = row({ period_end: '2026-09-30', fiscal_period: 'Q3', announcement_date: '2026-11-05', revenue: 385478, eps: -0.52, data_as_of: '2026-09-30' })
const filled = panel([q3, row()])
const filledText = text(filled)
check(filledText.includes(FUNDAMENTALS_TITLE), 'the card title')
check(filled.includes('資料 2026/09/30'), `the data badge is the newest period end, got ${filledText}`)
check(filledText.includes('2026 年第 3 季 3.85 -0.52 來源未提供 2026/11/05 公開資訊觀測站 季報'), `Q3: NT$ thousands to 億元, signed EPS, ROE 來源未提供, 可得日, source; got ${filledText}`)
check(filledText.includes('2026 年第 2 季 24,044.84 49.33 來源未提供 2026/10/30'), `Q2 after Q3 in API order; got ${filledText}`)
check(filled.indexOf('2026 年第 3 季') < filled.indexOf('2026 年第 2 季'), 'rows keep the API order, newest period first')
check(!/>0(?:\.00)?</.test(filled), 'a missing ROE is never shown as 0')
check(filledText.includes('年初至季底累計 營收（億元）') && filledText.includes('年初至季底累計 EPS（元）') && filled.includes('年初至季底累計</span><br/>營收（億元）') && filledText.includes('ROE（%）') && filledText.includes('可得日') && !filledText.includes('出表日 '), 'the headers say 年初至季底累計 and their units')
check(filledText.includes('來源：公開資訊觀測站 季報'), 'the source line under the table (the source column is wide only)')
check(filled.includes('<summary>說明</summary>') && filledText.includes('年初至季底累計') && filledText.includes('不是單季'), 'the note folds into 說明 and says the sums are year-to-date')
// #529: the note names the three bases of 可得日 and says the research cutoff filters by it.
check(['第一次收到的出表日期', '法定申報期限', '期限未到時是第一次抓到的日期', '研究截止日期以可得日篩選'].every((part) => filledText.includes(part)) && !filledText.includes('每次收集會更新'), `the note explains 可得日; got ${filledText}`)

// A missing revenue or EPS (insurance companies report no 營業收入) reads 來源未提供 too.
const insurer = text(panel([row({ revenue: null, eps: null, roe: 12.345 })]))
check(insurer.includes(`2026 年第 2 季 ${NOT_PROVIDED} ${NOT_PROVIDED} 12.35`), `missing revenue and EPS: 來源未提供; a present ROE keeps two decimals; got ${insurer}`)
check(revenueText(0) === '0.00', 'a reported zero revenue is a value, not 來源未提供')

check(fundamentalPeriodLabel({ period_end: '2026-05-31', fiscal_period: 'M05' }) === '2026 年 5 月', 'a monthly period')
check(fundamentalPeriodLabel({ period_end: '2026-06-30', fiscal_period: 'unknown' }) === '2026/06/30', 'an unknown period shows its end date')

// ---- no row: one reason sentence, no table ----
const etf = panel([], 'etf')
check(text(etf).includes('ETF 沒有公司財報，不適用。') && !etf.includes('<table'), `ETF: not applicable, no table; got ${text(etf)}`)
check(!etf.includes('date-badge') && !etf.includes('<summary>說明</summary>'), 'no data badge and no 說明 without a row')
const cutoff = text(panel([], 'stock', '2026-08-01'))
check(cutoff.includes('研究截止日期 2026/08/01 以前沒有已可得的季報。'), `a cutoff before every report says so; got ${cutoff}`)
check(fundamentalsEmptyReason('etf', '2026-08-01') === 'ETF 沒有公司財報，不適用。', 'an ETF stays not applicable under a cutoff')
check(text(panel([], 'ipo')).includes('新上市公司尚未有已收集的季報：官方季報快照與彙總報表都還沒有這檔。'), 'a new listing without a report')
check(text(panel([], 'stock')).includes('尚未收集到這檔的季報：官方季報快照與彙總報表都沒有這檔。') && !text(panel([], 'stock')).includes('最新一期'), 'a stock without a report')
check(text(panel([], 'stock')).includes('無資料'), 'the empty state title')
