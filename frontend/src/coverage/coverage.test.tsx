import { renderToStaticMarkup } from 'react-dom/server'
import { CoverageSummaryMetrics, coverageReasonLabels } from './CoverageSummary'
import type { CoverageReport } from '../types'

// Standalone regression module (no browser, no server, no network): the market
// coverage cards count official no-trade days apart from missing data (#454).
const check = (condition: boolean, message: string) => { if (!condition) throw new Error(message) }

const summary = (extra: Partial<CoverageReport['summary']> = {}): CoverageReport['summary'] => ({
  session_basis: 'taiex_observed', coverage_status: 'manifest', session_count: 62, date_count: 67, instrument_count: 2357,
  bar_rows: 0, chip_rows: 0, incomplete_to_20: 33, incomplete_to_60: 60, no_trade_to_20: 170, no_trade_to_60: 260,
  incomplete_chips_to_20: 98, incomplete_chips_to_60: 120,
  coverage_reason_counts: { missing_bar_dates: 17, official_no_trade: 260, listed_under_threshold: 10 },
  requested_calendar_sessions: 67, verified_trading_sessions: 62, verified_ohlcv_sessions: 62, verified_taiex_sessions: 62,
  verified_chip_sessions: 62, verified_event_sessions: 0, target_ohlcv_taiex_sessions: 65, target_chip_event_sessions: 20,
  target_met: false, latest_observed: '2026-11-03', data_cutoff: '2026-11-03',
  ...extra,
})

const html = renderToStaticMarkup(<CoverageSummaryMetrics summary={summary()} snapshot={false} />)
check(html.includes('<span>行情缺資料（20 日內）</span><b>33 個標的</b>'), 'missing-data card shows incomplete_to_20')
check(html.includes('<span>官方無成交（20 日內）</span><b>170 個標的</b>'), 'no-trade card shows no_trade_to_20 apart')
check(html.includes('<span>行情缺資料（60 日內）</span><b>60 個標的</b>'), 'missing-data card shows incomplete_to_60')
check(html.includes('不算缺資料'), 'the note says no-trade days are not missing data')
check(html.includes(`${coverageReasonLabels.official_no_trade}：260`), 'the official_no_trade reason has its own label')
check(!html.includes('其他資料缺口'), 'every reason of the fixture is labelled')
check(!html.includes('（官方快照）'), 'no snapshot suffix for a manifest')

// An API without the field (older backend) shows 尚無資料, never 0.
const older = summary({ no_trade_to_20: undefined })
const olderHtml = renderToStaticMarkup(<CoverageSummaryMetrics summary={older} snapshot />)
check(olderHtml.includes('<span>官方無成交（20 日內）</span><b>尚無資料</b>'), 'missing no_trade_to_20 is shown as no data')
check(olderHtml.includes('62 日（官方快照）'), 'snapshot suffix kept')
