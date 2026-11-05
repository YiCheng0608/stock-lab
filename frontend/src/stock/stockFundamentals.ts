import { formatDay } from '../dates'
import type { FundamentalSnapshot } from '../types'
import { formatFixed } from '../units'

// The stock page 「財務」 tab (#528; UI_COPY_SPEC §8.2 財務分頁, DESIGN_SYSTEM §5 個股財務表). The rows are the stock API's
// `fundamentals`, already cut at the research cutoff by their 出表日 (announcement_date <= as_of), so nothing published
// after the cutoff reaches here. The MOPS feed (t187ap14_L / mopsfin_t187ap14_O) reports revenue in NT$ thousands and both
// revenue and EPS as year-to-date sums, so the table says 累計 and converts revenue to 億元.

export const FUNDAMENTALS_TITLE = '季報營收與 EPS'
export const FUNDAMENTALS_EYEBROW = '財務資料'
export const NOT_PROVIDED = '來源未提供'
// The first header line of the revenue and EPS columns (#528 decision: the header says the sums are year-to-date).
export const CUMULATIVE = '年初至季底累計'
export const FUNDAMENTALS_NOTE = '營收與 EPS 都是年初至季底累計（該年 1 月 1 日到該季最後一天，官方綜合損益表口徑），不是單季；營收單位為億元（官方千元 ÷ 100,000）。出表日是官方開放資料的出表日期，每次收集會更新為最近一次出表的日期，可能晚於公司實際公告日；研究截止日期以前尚未出表的季度不顯示。官方開放資料沒有的欄位寫「來源未提供」。財務資料不納入策略或評分。'

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
  if (cutoff) return `研究截止日期 ${cutoff} 以前沒有已出表的季報。`
  if (instrumentType.toLowerCase() === 'ipo') return '新上市公司尚未有已收集的季報：系統目前只收官方最新一期的季報快照。'
  return '尚未收集到這檔的季報：系統目前只收官方最新一期的季報快照，該期尚未出表或不在官方清單時沒有資料。'
}

/** The latest period's data date for the card's badge. */
export function fundamentalsDataDate(rows: readonly FundamentalSnapshot[]): string | null {
  return rows.reduce<string | null>((latest, row) => {
    const day = row.data_as_of ?? row.period_end
    return latest == null || day > latest ? day : latest
  }, null)
}
