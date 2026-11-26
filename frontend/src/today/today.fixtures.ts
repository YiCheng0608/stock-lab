import type { ActionSummary, MarketOverview, MarketOverviewExchange, PremarketAiResponse } from '../types'

// dashboard.market_overview shapes (#275) with the 2026-10-22 values checked in the #269 design (§4).

function twse(): MarketOverviewExchange {
  return {
    exchange: 'TWSE',
    status: 'available',
    index: { name: '加權指數', close: 46041.43, change: -846.34, change_pct: -0.0181, change_pct_method: 'official' },
    turnover: { value: 933437473560, scope: 'twse_all_securities', scope_label: '集中市場總計（含 ETF、權證等）' },
    breadth: { advancers: 247, decliners: 756, unchanged: 74, limit_up: 3, limit_down: 5, unmatched: 7, not_comparable: 0, scope: 'twse_stocks' },
    source: { label: '臺灣證券交易所', collected_at: '2026-10-22T10:30:05+00:00', data_as_of: '2026-10-22', raw_payload_id: 6 },
  }
}

function tpex(): MarketOverviewExchange {
  return {
    exchange: 'TPEx',
    status: 'available',
    index: { name: '櫃買指數', close: 381.69, change: -13.73, change_pct: -0.0347, change_pct_method: 'derived' },
    turnover: { value: 225545000000, scope: 'tpex_stocks', scope_label: '上櫃股票' },
    breadth: { advancers: 146, decliners: 659, unchanged: 63, limit_up: 17, limit_down: 11, unmatched: 26, not_comparable: null, scope: 'tpex_stocks' },
    source: { label: '證券櫃檯買賣中心', collected_at: '2026-10-22T10:31:00+00:00', data_as_of: '2026-10-22', raw_payload_id: 7 },
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

// GET /api/premarket-ai (#1042): a done reading with a today-list stock (rule levels) and a pool stock (no price).
export function premarketAiDone(): PremarketAiResponse {
  return {
    status: 'done', session_date: '2026-11-30', list_date: '2026-11-27', prompt_version: 'premarket_v1', llm_model: 'claude-sonnet-5-5',
    cutoff_at: '2026-11-30T00:15:00+00:00', finished_at: '2026-11-30T00:24:00+00:00', reason: null, reason_text: null,
    market: { stance: 'bullish', stance_text: '偏多', confidence: 'medium', confidence_text: '把握中', reasons: [{ text: '根據美股四大指數收高，推論台股開盤偏多', refs: [{ ref: 'us:SPX', kind: 'us', label: '美股 S&P 500' }, { ref: 'tx:night', kind: 'tx', label: '台指期夜盤' }] }] },
    sectors: [{ group_id: 'industry:24', name: '半導體', direction: 'positive', direction_text: '可能正向', reasons: [{ text: '根據隔夜新聞，推論半導體族群可能正向', refs: [{ ref: 'news:777', kind: 'news', news_id: 777, label: '美股收高 費半大漲' }] }] }],
    stocks: [
      {
        symbol: '1101', exchange: 'TWSE', name: '台泥', on_today_list: true, action: 'reprice', action_text: '依開盤價重算',
        reprice_rule: { max_gap_pct: 0.05, max_gap_down_pct: 0.03, min_risk_reward: 1.5 }, reprice_text: '開盤漲幅逾 5.0%、跌幅逾 3.0%或重算後 RR 低於 1.5 倍即暫緩',
        reasons: [{ text: '根據台泥擴產新聞，推論開盤可能跳空', refs: [{ ref: 'news:501', kind: 'news', news_id: 501, label: '台泥擴產' }, { ref: 'stock:1101:chips', kind: 'stock', label: '1101 籌碼' }, { ref: 'weird', kind: 'other', label: null }] }],
        rank: 1,
        levels: { rank: 1, entry_type: 'breakout', entry: 101, entry_zone: { low: 101, high: 101 }, invalid_price: 98, target_1: 103.2, target_2: null, risk_reward: 0.73, earliest_execution_date: '2026-11-30' },
      },
      {
        symbol: '2330', exchange: 'TWSE', name: '台積電', on_today_list: false, action: 'defer', action_text: '暫緩', reprice_rule: null, reprice_text: null,
        reasons: [{ text: '根據台指期夜盤缺資料，推論族群方向不明，暫緩判讀', refs: [{ ref: 'tx:night', kind: 'tx', label: '台指期夜盤' }] }],
      },
    ],
    data_gaps: ['台指期夜盤沒有資料，大盤判讀信心降低'],
    input_gaps: ['台指期夜盤無資料', '2330 台積電 名單日無日線'],
  }
}

export function premarketAiNotDone(status: 'failed' | 'rejected' | 'missing', reasonText: string | null = null): PremarketAiResponse {
  return {
    status, session_date: status === 'missing' ? null : '2026-11-30', list_date: '2026-11-27', prompt_version: 'premarket_v1', llm_model: null,
    reason: reasonText ? 'timeout' : null, reason_text: reasonText, market: null, sectors: [], stocks: [], data_gaps: [], input_gaps: [],
  }
}
