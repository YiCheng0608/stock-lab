import type { IndexMa60, IndexRow, MarketOverview } from '../types'
import { overviewBoth } from '../today/today.fixtures'

// market_overview.indexes (Issue 564) for the 2026-10-22 overview of today.fixtures: one row per state the table shows —
// latest and above MA60 (TAIEX, the same close and MA60 as taiex_ma60), 非最新 with too few closes (TPEX), a TX roll day,
// 非最新 (SPX), MA60 not computed (IXIC), 美股休市 and equal to MA60 (DJI), and a failed FinMind read (SOX).

const ma60 = (trading_date: string, extra: Partial<IndexMa60>): IndexMa60 => ({ trading_date, required_closes: 60, status: 'available', ...extra })

const usSource = (series: string, copyright: string) => ({ label: 'FinMind', detail: `FinMind USStockPrice ${series}`, copyright })
const SPDJI = 'Copyright © 2016, S&P Dow Jones Indices LLC. All rights reserved.'
const NASDAQ = 'Copyright © 2016, NASDAQ OMX Group, Inc.'

export const indexRows = (): IndexRow[] => [
  {
    key: 'taiex', group: 'tw', exchange: 'TWSE', symbol: 'TAIEX', name: '加權指數', instrument_type: 'index', status: 'available',
    trading_date: '2026-10-22', expected_date: '2026-10-22', freshness: 'latest', close: 46041.43, change: -846.34, change_pct: -0.0181, change_pct_method: 'official',
    ma60: ma60('2026-10-22', { close: 46041.43, ma60: 44012.5, above: true, position: 'above', close_count: 250 }),
    source: { label: '臺灣證券交易所', detail: '臺灣證券交易所 MI_INDEX' },
  },
  {
    key: 'tpex', group: 'tw', exchange: 'TPEx', symbol: 'TPEX', name: '櫃買指數', instrument_type: 'index', status: 'available',
    trading_date: '2026-10-21', expected_date: '2026-10-22', freshness: 'stale', close: 395.42, change: 2.1, change_pct: 0.005339, change_pct_method: 'derived',
    ma60: ma60('2026-10-21', { status: 'insufficient', reason: 'insufficient_closes', close_count: 42 }),
    source: { label: '證券櫃檯買賣中心', detail: '櫃買中心 tpex_mainborad_highlight' },
  },
  {
    key: 'tx', group: 'tw', exchange: 'TAIFEX', symbol: 'TX', name: '台指期近月', instrument_type: 'futures', status: 'available',
    trading_date: '2026-10-22', expected_date: '2026-10-22', freshness: 'latest', close: 46110, change: null, change_pct: null, change_pct_method: 'derived',
    change_status: 'contract_roll', contract_month: '202611', previous_contract_month: '202610', open_interest: 125011,
    ma60: ma60('2026-10-22', { close: 46110, ma60: 46502.4, above: false, position: 'below', close_count: 61 }),
    source: { label: '臺灣期貨交易所', detail: 'taifex_daily_futures' },
  },
  {
    key: 'spx', group: 'us', exchange: 'US', symbol: 'SPX', name: 'S&P 500', instrument_type: 'index', status: 'available',
    trading_date: '2026-10-20', expected_date: '2026-10-21', freshness: 'stale', close: 7353.73, change: -334.89, change_pct: -0.043557, change_pct_method: 'derived',
    ma60: ma60('2026-10-20', { close: 7353.73, ma60: 6900.12, above: true, position: 'above', close_count: 60 }),
    source: usSource('^GSPC', SPDJI),
  },
  {
    key: 'ixic', group: 'us', exchange: 'US', symbol: 'IXIC', name: 'NASDAQ Composite', instrument_type: 'index', status: 'available',
    trading_date: '2026-10-21', expected_date: '2026-10-21', freshness: 'latest', close: 24579.42, change: 264.42, change_pct: 0.010875, change_pct_method: 'derived',
    ma60: ma60('2026-10-21', { status: 'unavailable', reason: 'indicator_not_computed' }),
    source: usSource('^IXIC', NASDAQ),
  },
  {
    key: 'dji', group: 'us', exchange: 'US', symbol: 'DJI', name: 'Dow Jones Industrial Average', instrument_type: 'index', status: 'available',
    trading_date: '2026-10-20', expected_date: '2026-10-21', freshness: 'us_market_closed', close: 51285.73, change: -40.25, change_pct: -0.000784, change_pct_method: 'derived',
    ma60: ma60('2026-10-20', { close: 51285.73, ma60: 51285.73, above: false, position: 'equal', close_count: 300 }),
    source: usSource('^DJI', SPDJI),
  },
  {
    key: 'sox', group: 'us', exchange: 'US', symbol: 'SOX', name: 'PHLX Semiconductor', instrument_type: 'index', status: 'unavailable',
    reason: 'fetch_failed', last_attempt_date: '2026-10-22', expected_date: '2026-10-21', ma60: null,
    source: usSource('^SOX', NASDAQ),
  },
]

export const overviewWithIndexes = (rows: IndexRow[] = indexRows()): MarketOverview => ({ ...overviewBoth(), indexes: rows })
