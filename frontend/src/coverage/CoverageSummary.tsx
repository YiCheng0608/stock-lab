import type { CoverageReport } from '../types'

type Summary = CoverageReport['summary']

export const coverageReasonLabels: Record<string, string> = {
  listed_under_threshold: '上市／掛牌後有效交易日尚不足',
  missing_bar_dates: '部分有效交易日缺少行情',
  suspended_or_no_trade: '停牌或當日無交易',
  official_no_trade: '官方行情表列出但當日無成交（不算缺資料）',
  missing_taiex: '缺少 加權指數 交易日基準',
  missing_chips: '部分有效交易日缺少籌碼',
  etf_not_general_action_eligible: '此 ETF 類型不套用一般股票進出場判斷',
  // The stock page's coverage only (Issue 511): the day's quote table was stored but has no row for the stock.
  quote_not_listed: '官方行情表當日未列此股',
  coverage_baseline_unknown: '尚無可核實的 加權指數 交易日基準',
}

function countLabel(value: number | null | undefined): string {
  return value == null ? '尚無資料' : `${value} 個標的`
}

// The backfill card's verified sessions (Issue #479): the target excludes the
// window's confirmed closures, and the card says how many it took out.
export function backfillSessionsLabel(verified: number, target: number, closures: number): string {
  return `${verified}／${target} 日${closures > 0 ? `（已扣除 ${closures} 個確定休市日）` : ''}`
}

// The market coverage cards (Issue #454): an official no-trade day (the quote
// table lists the security with every price blank) is counted apart from
// missing data, never as a gap and never as a price.
export function CoverageSummaryMetrics({ summary, snapshot }: { summary: Summary; snapshot: boolean }) {
  return <>
    <div className="metric-grid">
      <div className="metric-card"><span>加權指數 已核實交易日</span><b>{summary.verified_taiex_sessions} 日{snapshot ? '（官方快照）' : ''}</b></div>
      <div className="metric-card"><span>行情未滿 20 日</span><b>{countLabel(summary.incomplete_to_20)}</b></div>
      <div className="metric-card"><span>官方無成交（20 日內）</span><b>{countLabel(summary.no_trade_to_20)}</b></div>
      <div className="metric-card"><span>行情未滿 60 日</span><b>{countLabel(summary.incomplete_to_60)}</b></div>
      <div className="metric-card"><span>籌碼未滿 20 日</span><b>{countLabel(summary.incomplete_chips_to_20)}</b></div>
    </div>
    <div className="small-note">官方無成交：官方每日行情表列出該檔、但開高低收全部空白的交易日。這些日子不算缺資料，也不補價格，不計入「行情未滿」；「行情未滿」是缺資料或上市後交易日還不夠的標的。同一檔可能同時有缺日與官方無成交的日子。</div>
    {Object.keys(summary.coverage_reason_counts).length > 0 && <div className="tag-list">{Object.entries(summary.coverage_reason_counts).map(([reason, count]) => <span className="tag" key={reason}>{coverageReasonLabels[reason] ?? '其他資料缺口'}：{count}</span>)}</div>}
  </>
}
