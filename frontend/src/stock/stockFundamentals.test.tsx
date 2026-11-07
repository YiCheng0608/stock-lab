import { renderToStaticMarkup } from 'react-dom/server'

import type { FundamentalSnapshot, MonthlyRevenue } from '../types'
import { StockFundamentalsPanel } from './StockFundamentalsPanel'
import { CORRECTED, CORRECTION_HEADER, FUNDAMENTALS_TITLE, MONTHLY_NOTE, MONTHLY_TITLE, NOT_PROVIDED, correctionNote, fundamentalPeriodLabel, fundamentalsEmptyReason, isCorrected, monthlyEmptyReason, revenueMonthLabel, revenueText, yoyText } from './stockFundamentals'
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

// ---- 月營收 (Issue 530): the 12 newest months under the quarterly table ----
const month = (extra: Partial<MonthlyRevenue> = {}): MonthlyRevenue => ({
  revenue_month: '2026-09', revenue: 511857399, prior_year_revenue: 330980920, yoy: 54.64861207105231,
  cumulative_revenue: 3898726974, announcement_date: '2026-10-12', announcement_basis: 'statutory_deadline',
  source: 'mops_t21sc03', data_as_of: '2026-09-30', ...extra,
})
const monthlyLabel = (source: string) => (source === 'mops_t21sc03' ? '公開資訊觀測站 營業收入統計表' : source === 'mops_t187ap05' ? '公開資訊觀測站 月營收' : label(source))
const tab = (rows: FundamentalSnapshot[], months: MonthlyRevenue[], instrumentType = 'stock', asOf: string | null = null) =>
  renderToStaticMarkup(<StockFundamentalsPanel rows={rows} monthlyRows={months} instrumentType={instrumentType} asOf={asOf} sourceLabel={monthlyLabel} />)

const august = month({ revenue_month: '2026-08', revenue: 514805337, yoy: -0.0001, announcement_date: '2026-09-10', data_as_of: '2026-08-31', source: 'mops_t187ap05' })
const both = tab([row()], [month(), august])
const bothText = text(both)
check(bothText.includes(MONTHLY_TITLE) && both.indexOf(FUNDAMENTALS_TITLE) < both.indexOf(`>${MONTHLY_TITLE}<`), `the monthly card sits under the quarterly table; got ${bothText}`)
check(bothText.includes('月份 營收（億元） 年增率（%） 可得日 來源'), `monthly headers; got ${bothText}`)
check(bothText.includes('2026 年 9 月 5,118.57 +54.6 2026/10/12 公開資訊觀測站 營業收入統計表'), `one month: 億元, signed one-decimal yoy, 可得日, source; got ${bothText}`)
check(bothText.includes('2026 年 8 月 5,148.05 0.0 2026/09/10 公開資訊觀測站 月營收'), `a yoy that rounds to zero has no sign; got ${bothText}`)
check(both.indexOf('2026 年 9 月') < both.indexOf('2026 年 8 月'), 'months keep the API order, newest first')
check(both.includes('資料 2026/09/30'), 'the monthly badge is the newest month end')
check(bothText.includes('來源：公開資訊觀測站 營業收入統計表、公開資訊觀測站 月營收'), `the monthly source line; got ${bothText}`)
check(['不是累計', '次月 10 日', '研究截止日期以可得日篩選', '月營收不納入策略或評分'].every((part) => MONTHLY_NOTE.includes(part)) && bothText.includes(MONTHLY_NOTE), 'the monthly 說明')
check(yoyText(null) === NOT_PROVIDED && text(tab([], [month({ yoy: null, revenue: null })])).includes(`2026 年 9 月 ${NOT_PROVIDED} ${NOT_PROVIDED}`), 'a blank yoy or revenue reads 來源未提供, never 0')
check(revenueMonthLabel('2026-01') === '2026 年 1 月' && revenueMonthLabel('bad') === 'bad', 'month labels')

// No month: one reason sentence each, the quarterly card unchanged.
const etfTab = text(tab([], [], 'etf'))
check(etfTab.includes('ETF 沒有公司財報，不適用。') && etfTab.includes('ETF 不申報月營收，不適用。'), `ETF: both cards say not applicable; got ${etfTab}`)
check(monthlyEmptyReason('stock', '2026-08-01') === '研究截止日期 2026/08/01 以前沒有已可得的月營收。', 'a cutoff before every month')
check(monthlyEmptyReason('etf', '2026-08-01') === 'ETF 不申報月營收，不適用。', 'an ETF stays not applicable under a cutoff')
check(monthlyEmptyReason('ipo', null).startsWith('新上市公司尚未有已收集的月營收') && monthlyEmptyReason('stock', null).startsWith('尚未收集到這檔的月營收'), 'new listing and stock without a month')
check((tab([row()], []).match(/<table/g) ?? []).length === 1 && (both.match(/<table/g) ?? []).length === 2, 'no monthly table without a month')
check(text(panel([row()])).includes('尚未收集到這檔的月營收'), 'a caller without monthly rows shows the monthly empty state')

// ---- 已更正 (Issue 543): the MOPS page replaced the snapshot's values ----
check(!bothText.includes(CORRECTION_HEADER) && !bothText.includes(CORRECTED) && !both.includes('stock-revenue-correction'), `no 更正 column or note without a corrected month; got ${bothText}`)
const corrected = month({
  revenue: 64332, prior_year_revenue: 50000, yoy: 28.66, cumulative_revenue: 500000, corrected: true,
  superseded_snapshot: { revenue: 60251, prior_year_revenue: 50000, yoy: 20.502, cumulative_revenue: 495919, source: 'mops_t187ap05', release_date: '2026-10-17' },
})
const fixed = tab([], [corrected, august])
const fixedText = text(fixed)
check(fixedText.includes('月份 營收（億元） 年增率（%） 可得日 更正 來源'), `the 更正 column sits between 可得日 and 來源; got ${fixedText}`)
check(fixedText.includes('2026 年 9 月 0.64 +28.7 2026/10/12 已更正 公開資訊觀測站 營業收入統計表'), `the corrected month shows the MOPS values and 已更正 after 可得日; got ${fixedText}`)
check(fixedText.includes('2026 年 8 月 5,148.05 0.0 2026/09/10 公開資訊觀測站 月營收') && (fixedText.match(/已更正/g) ?? []).length === 2, `other months leave the 更正 cell empty; got ${fixedText}`)
// The 更正 cell is not wideOnly: a 390px screen scrolls to it (the 來源 cell is the one hidden).
check(/<td[^>]*>已更正<\/td>/.test(fixed) && !/<td[^>]*wide[^>]*>已更正/.test(fixed), `the 更正 cell shows at every width; got ${fixed}`)
const fixedNote = '2026 年 9 月已更正：原快照營收 0.60 億元、年增率 +20.5%（公開資訊觀測站 月營收，出表日期 2026/10/17），現以公開資訊觀測站 營業收入統計表為準。'
check(correctionNote(corrected, monthlyLabel) === fixedNote && fixedText.includes(`來源：公開資訊觀測站 營業收入統計表、公開資訊觀測站 月營收 ${fixedNote}`), `one note after the source line gives the snapshot values; got ${fixedText}`)
const blankOld = month({ corrected: true, superseded_snapshot: { revenue: null, prior_year_revenue: null, yoy: null, cumulative_revenue: null, source: 'mops_t187ap05', release_date: null } })
check(correctionNote(blankOld, monthlyLabel) === `2026 年 9 月已更正：原快照營收 ${NOT_PROVIDED}、年增率 ${NOT_PROVIDED}（公開資訊觀測站 月營收），現以公開資訊觀測站 營業收入統計表為準。`, 'a blank snapshot value reads 來源未提供 and an unknown 出表日期 is left out')
check(!isCorrected(month({ corrected: true })) && correctionNote(month({ corrected: false, superseded_snapshot: corrected.superseded_snapshot }), monthlyLabel) === null, 'only corrected=true with a snapshot value is 已更正')
