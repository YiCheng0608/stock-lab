import { formatDay } from '../dates'
import type { FundamentalSnapshot, MonthlyRevenue } from '../types'
import { formatFixed } from '../units'

// The stock page 「財務」 tab (#528; UI_COPY_SPEC §8.2 財務分頁, DESIGN_SYSTEM §5 個股財務表). The rows are the stock API's
// `fundamentals`, already cut at the research cutoff by their 可得日 (announcement_date <= as_of; #529: the first
// 出表日期 of the snapshot feeds t187ap14_L / mopsfin_t187ap14_O, or the statutory filing deadline of a quarter backfilled
// from the t163sb04 summary report), so nothing available after the cutoff reaches here. Both MOPS sources report revenue
// in NT$ thousands and both revenue and EPS as year-to-date sums, so the table says 累計 and converts revenue to 億元.

export const FUNDAMENTALS_TITLE = '季報營收與 EPS'
export const FUNDAMENTALS_EYEBROW = '財務資料'
export const NOT_PROVIDED = '來源未提供'
// The first header line of the revenue and EPS columns (#528 decision: the header says the sums are year-to-date).
export const CUMULATIVE = '年初至季底累計'
export const FUNDAMENTALS_NOTE = '營收與 EPS 都是年初至季底累計（該年 1 月 1 日到該季最後一天，官方綜合損益表口徑），不是單季；營收單位為億元（官方千元 ÷ 100,000）。可得日是官方季報快照第一次收到的出表日期，或回補季度的法定申報期限（遇休市順延；期限未到時是第一次抓到的日期），研究截止日期以可得日篩選，之前尚未可得的季度不顯示。來源沒有的欄位寫「來源未提供」。財務資料不納入策略或評分。'

const THOUSANDS_PER_HUNDRED_MILLION = 100_000

/** 2026 年第 2 季 for Q2, 2026 年 5 月 for M05; any other period shows its end date. */
export function fundamentalPeriodLabel(row: Pick<FundamentalSnapshot, 'period_end' | 'fiscal_period'>): string {
  const year = /^(\d{4})-/.exec(row.period_end)?.[1]
  const quarter = /^Q([1-4])$/.exec(row.fiscal_period)?.[1]
  if (year && quarter) return `${year} 年第 ${quarter} 季`
  const month = /^M(0[1-9]|1[0-2])$/.exec(row.fiscal_period)?.[1]
  if (year && month) return `${year} 年 ${Number(month)} 月`
  return formatDay(row.period_end) ?? row.period_end
}

const finite = (value: number | null | undefined): value is number => typeof value === 'number' && Number.isFinite(value)

/** Revenue in 億元 (the feed's NT$ thousands ÷ 100,000), two decimals. */
export function revenueText(value: number | null | undefined): string {
  return finite(value) ? formatFixed(value / THOUSANDS_PER_HUNDRED_MILLION, 2) : NOT_PROVIDED
}

export function epsText(value: number | null | undefined): string {
  return finite(value) ? formatFixed(value, 2) : NOT_PROVIDED
}

/** ROE in percent; the feed has no ROE today, so every row reads 來源未提供 — never 0. */
export function roeText(value: number | null | undefined): string {
  return finite(value) ? formatFixed(value, 2) : NOT_PROVIDED
}

/** One sentence for why there is no row (#528): ETF has no company report; a cutoff can predate every report. */
export function fundamentalsEmptyReason(instrumentType: string, asOf: string | null | undefined): string {
  if (instrumentType.toLowerCase() === 'etf') return 'ETF 沒有公司財報，不適用。'
  const cutoff = formatDay(asOf)
  if (cutoff) return `研究截止日期 ${cutoff} 以前沒有已可得的季報。`
  if (instrumentType.toLowerCase() === 'ipo') return '新上市公司尚未有已收集的季報：官方季報快照與彙總報表都還沒有這檔。'
  return '尚未收集到這檔的季報：官方季報快照與彙總報表都沒有這檔。'
}

// ---- 月營收 (#530; UI_COPY_SPEC §8.2 財務分頁). The rows are the stock API's `monthly_revenues`: the 12 newest months
// whose 可得日 is on or before the research cutoff, newest first. Revenue is one month (not year-to-date) in NT$
// thousands; 年增率 is the source's 去年同月增減(%), never recomputed here.

export const MONTHLY_TITLE = '月營收'
export const MONTHLY_NOTE = '營收是單月（該月 1 日到月底），不是累計；單位為億元（官方千元 ÷ 100,000）。年增率是與去年同月相比的增減（%），用來源的數字顯示到小數一位。可得日是官方月營收快照第一次收到的出表日期，或回補月份的法定申報期限次月 10 日（遇休市順延；期限未到時是第一次抓到的日期），研究截止日期以可得日篩選，之前尚未可得的月份不顯示。來源沒有的欄位寫「來源未提供」。月營收不納入策略或評分。'

/** 2026 年 9 月 for 2026-09. */
export function revenueMonthLabel(month: string): string {
  const match = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(month)
  return match ? `${match[1]} 年 ${Number(match[2])} 月` : month
}

/** Year-on-year change in percent, one decimal, signed. */
export function yoyText(value: number | null | undefined): string {
  return finite(value) ? formatFixed(value, 1, true) : NOT_PROVIDED
}

// 已更正 (#543): a company corrected the month after the snapshot was published; the MOPS page's values replaced the
// snapshot's. The 更正 column appears only when a listed month is corrected, after 可得日 (verify S13 reads the first four
// cells), and one note per corrected month under the source line gives the snapshot's values.
export const CORRECTION_HEADER = '更正'
export const CORRECTED = '已更正'

export function isCorrected(row: MonthlyRevenue): boolean {
  return row.corrected === true && row.superseded_snapshot != null
}

/** 「2026 年 9 月已更正：原快照營收 50.00 億元、年增率 +51.1%（…，出表日期 2026/10/17），現以…為準。」 */
export function correctionNote(row: MonthlyRevenue, sourceLabel: (source: string) => string): string | null {
  const old = row.superseded_snapshot
  if (!isCorrected(row) || !old) return null
  const revenue = finite(old.revenue) ? `${revenueText(old.revenue)} 億元` : NOT_PROVIDED
  const yoy = finite(old.yoy) ? `${yoyText(old.yoy)}%` : NOT_PROVIDED
  const released = formatDay(old.release_date)
  const origin = released ? `${sourceLabel(old.source)}，出表日期 ${released}` : sourceLabel(old.source)
  return `${revenueMonthLabel(row.revenue_month)}已更正：原快照營收 ${revenue}、年增率 ${yoy}（${origin}），現以${sourceLabel(row.source)}為準。`
}

/** One sentence for why there is no month: ETF files no monthly revenue; a cutoff can predate every month. */
export function monthlyEmptyReason(instrumentType: string, asOf: string | null | undefined): string {
  if (instrumentType.toLowerCase() === 'etf') return 'ETF 不申報月營收，不適用。'
  const cutoff = formatDay(asOf)
  if (cutoff) return `研究截止日期 ${cutoff} 以前沒有已可得的月營收。`
  if (instrumentType.toLowerCase() === 'ipo') return '新上市公司尚未有已收集的月營收：官方月營收快照與營業收入統計表都還沒有這檔。'
  return '尚未收集到這檔的月營收：官方月營收快照與營業收入統計表都沒有這檔。'
}

/** The newest month's data date (its last day) for the card's badge. */
export function monthlyDataDate(rows: readonly MonthlyRevenue[]): string | null {
  return rows.reduce<string | null>((latest, row) => {
    const day = row.data_as_of ?? row.revenue_month
    return latest == null || day > latest ? day : latest
  }, null)
}

/** The latest period's data date for the card's badge. */
export function fundamentalsDataDate(rows: readonly FundamentalSnapshot[]): string | null {
  return rows.reduce<string | null>((latest, row) => {
    const day = row.data_as_of ?? row.period_end
    return latest == null || day > latest ? day : latest
  }, null)
}
