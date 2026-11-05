import { Card, DataTable, DateBadge, EmptyState, type Column } from '../components/ui'
import { formatDay } from '../dates'
import type { FundamentalSnapshot, MonthlyRevenue } from '../types'
import {
  CUMULATIVE,
  FUNDAMENTALS_EYEBROW,
  FUNDAMENTALS_NOTE,
  FUNDAMENTALS_TITLE,
  MONTHLY_NOTE,
  MONTHLY_TITLE,
  NOT_PROVIDED,
  epsText,
  fundamentalPeriodLabel,
  fundamentalsDataDate,
  fundamentalsEmptyReason,
  monthlyDataDate,
  monthlyEmptyReason,
  revenueMonthLabel,
  revenueText,
  roeText,
  yoyText,
} from './stockFundamentals'

// The stock page 「財務」 tab (#528; DESIGN_SYSTEM §5 個股財務表, UI_COPY_SPEC §8.2 財務分頁): the collected quarterly
// reports as the API returns them (newest period first), with their 可得日 (#529) and source on every row, and under
// them the 12 newest months of revenue (#530).
export function StockFundamentalsPanel({
  rows,
  monthlyRows = [],
  instrumentType,
  asOf,
  sourceLabel,
}: {
  rows: readonly FundamentalSnapshot[]
  monthlyRows?: readonly MonthlyRevenue[]
  instrumentType: string
  asOf: string | null | undefined
  sourceLabel: (source: string) => string
}) {
  const date = fundamentalsDataDate(rows)
  const columns: ReadonlyArray<Column<FundamentalSnapshot>> = [
    { key: 'period', header: '期別', cell: (row) => fundamentalPeriodLabel(row) },
    // Two header lines keep 年初至季底累計 in the header and the EPS column on a 390px first screen (DESIGN_SYSTEM §5.1).
    { key: 'revenue', header: <><span className="th-qualifier">{CUMULATIVE}</span><br />營收（億元）</>, num: true, cell: (row) => revenueText(row.revenue) },
    { key: 'eps', header: <><span className="th-qualifier">{CUMULATIVE}</span><br />EPS（元）</>, num: true, cell: (row) => epsText(row.eps) },
    { key: 'roe', header: 'ROE（%）', num: true, cell: (row) => roeText(row.roe) },
    { key: 'announced', header: '可得日', cell: (row) => formatDay(row.announcement_date) ?? NOT_PROVIDED },
    { key: 'source', header: '來源', wideOnly: true, cell: (row) => sourceLabel(row.source) },
  ]
  const sources = [...new Set(rows.map((row) => sourceLabel(row.source)))]
  return <>
    <Card className="stock-fundamentals" eyebrow={FUNDAMENTALS_EYEBROW} title={FUNDAMENTALS_TITLE} aside={rows.length ? <DateBadge date={date} /> : undefined}>
      {rows.length
        ? <>
          <details className="details stock-fundamentals-note"><summary>說明</summary><p className="small-note">{FUNDAMENTALS_NOTE}</p></details>
          <DataTable wrapClassName="compact-table" columns={columns} rows={rows} rowKey={(row) => `${row.period_end}-${row.fiscal_period}`} />
          <p className="small-note stock-fundamentals-source">來源：{sources.join('、')}</p>
        </>
        : <EmptyState reason={fundamentalsEmptyReason(instrumentType, asOf)} />}
    </Card>
    <MonthlyRevenueCard rows={monthlyRows} instrumentType={instrumentType} asOf={asOf} sourceLabel={sourceLabel} />
  </>
}

function MonthlyRevenueCard({
  rows,
  instrumentType,
  asOf,
  sourceLabel,
}: {
  rows: readonly MonthlyRevenue[]
  instrumentType: string
  asOf: string | null | undefined
  sourceLabel: (source: string) => string
}) {
  const columns: ReadonlyArray<Column<MonthlyRevenue>> = [
    { key: 'month', header: '月份', cell: (row) => revenueMonthLabel(row.revenue_month) },
    { key: 'revenue', header: '營收（億元）', num: true, cell: (row) => revenueText(row.revenue) },
    { key: 'yoy', header: '年增率（%）', num: true, cell: (row) => yoyText(row.yoy) },
    { key: 'announced', header: '可得日', cell: (row) => formatDay(row.announcement_date) ?? NOT_PROVIDED },
    { key: 'source', header: '來源', wideOnly: true, cell: (row) => sourceLabel(row.source) },
  ]
  const sources = [...new Set(rows.map((row) => sourceLabel(row.source)))]
  return (
    <Card className="stock-fundamentals stock-monthly-revenue" eyebrow={FUNDAMENTALS_EYEBROW} title={MONTHLY_TITLE} aside={rows.length ? <DateBadge date={monthlyDataDate(rows)} /> : undefined}>
      {rows.length
        ? <>
          <details className="details stock-fundamentals-note"><summary>說明</summary><p className="small-note">{MONTHLY_NOTE}</p></details>
          <DataTable wrapClassName="compact-table" columns={columns} rows={rows} rowKey={(row) => row.revenue_month} />
          <p className="small-note stock-fundamentals-source">來源：{sources.join('、')}</p>
        </>
        : <EmptyState reason={monthlyEmptyReason(instrumentType, asOf)} />}
    </Card>
  )
}
