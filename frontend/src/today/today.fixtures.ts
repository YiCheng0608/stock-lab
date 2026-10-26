import type { ActionSummary, MarketOverview, MarketOverviewExchange } from '../types'

// dashboard.market_overview shapes (#275) with the 2026-10-22 values checked in the #269 design (§4).

function twse(): MarketOverviewExchange {
  return {
    exchange: 'TWSE',
    status: 'available',
    index: { name: '加權指數', close: 46041.43, change: -846.34, change_pct: -0.0181, change_pct_method: 'official' },
    turnover: { value: 933437473560, scope: 'twse_all_securities', scope_label: '集中市場總計（含 ETF、權證等）' },
    breadth: { advancers: 247, decliners: 756, unchanged: 74, limit_up: 3, limit_down: 5, unmatched: 7, not_comparable: 0, scope: 'twse_stocks' },
    source: { label: '臺灣證券交易所 MI_INDEX', collected_at: '2026-10-22T10:30:05+00:00', data_as_of: '2026-10-22', raw_payload_id: 6 },
  }
}

function tpex(): MarketOverviewExchange {
  return {
    exchange: 'TPEx',
    status: 'available',
    index: { name: '櫃買指數', close: 381.69, change: -13.73, change_pct: -0.0347, change_pct_method: 'derived' },
    turnover: { value: 225545000000, scope: 'tpex_stocks', scope_label: '上櫃股票' },
    breadth: { advancers: 146, decliners: 659, unchanged: 63, limit_up: 17, limit_down: 11, unmatched: 26, not_comparable: null, scope: 'tpex_stocks' },
    source: { label: '櫃買中心 tpex_mainborad_highlight', collected_at: '2026-10-22T10:31:00+00:00', data_as_of: '2026-10-22', raw_payload_id: 7 },
  }
}

const unavailable = (exchange: string, reason: string): MarketOverviewExchange => ({ exchange, status: 'unavailable', reason, latest_trading_date: null })

export const overviewBoth = (): MarketOverview => ({ trading_date: '2026-10-22', exchanges: [twse(), tpex()] })

// TPEx highlight had not been collected for the day; TWSE shows as usual.
export const overviewTwseOnly = (): MarketOverview => ({ trading_date: '2026-10-22', exchanges: [twse(), unavailable('TPEx', 'not_collected')] })

export const overviewNone = (): MarketOverview => ({
  trading_date: '2026-10-22',
  exchanges: [unavailable('TWSE', 'row_date_mismatch'), unavailable('TPEx', 'not_collected')],
})

// Compact action summaries as in dashboard.actions; only the fields the alert row reads matter.
export function action(symbol: string, name: string, state: string, extra: Partial<ActionSummary> = {}): ActionSummary {
  return {
    instrument: { id: Number(symbol), exchange: 'TWSE', symbol, name, instrument_type: 'stock', etf_category: null },
    action_state: state,
    held: false,
    position_quantity_status: 'known',
    as_of: '2026-10-22',
    reasons: [],
    conflicts: [],
    strategies: [],
    missing_data_priority: [],
    alternative_strategies: [],
    ...extra,
  } as unknown as ActionSummary
}

export const riskActions = (): ActionSummary[] => [
  action('2330', '台積電', 'reduce_exit', { held: true }),
  action('2317', '鴻海', 'conditional_entry'),
  action('1101', '台泥', 'data_insufficient', { held: true }),
  // Not held: a reduce_exit state without a position is not a holding risk.
  action('2603', '長榮', 'reduce_exit'),
  action('2882', '國泰金', 'hold_observe', { held: true, position_quantity_status: 'unknown' }),
  action('2412', '中華電', 'reduce_exit', { held: true }),
]
