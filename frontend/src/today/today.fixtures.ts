import type { ActionSummary, AiListPick, AiListResponse, MarketOverview, MarketOverviewExchange } from '../types'

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

// GET /api/ai-list (#1146): today's done list with a breakout (corporate action after the list date), a pullback and
// a pick whose levels failed the check; the values of #1142 3/4's sketch.
const aiReason = (text: string, refs: AiListResponse['picks'][number]['reasons'][number]['refs'] = []) => ({ text, refs })
export function aiPick(rank: number, overrides: Partial<AiListPick> = {}): AiListPick {
  return {
    rank, symbol: '1477', exchange: 'TWSE', name: '聚陽', instrument_type: 'stock', on_rule_list: true,
    setup: 'breakout', setup_text: '突破', basis: ['technical', 'chips'], basis_text: '技術面＞籌碼', confidence: 'medium', confidence_text: '把握中',
    method_text: '突破 · 技術面＞籌碼 · 把握中', levels_status: 'pass',
    levels: { entry: { type: 'breakout', low: 233, high: 236.5 }, stop: 226, target_1: 243.5, target_2: 254.5, risk_reward: 1.5, valid_sessions: 3, valid_until: '2026-12-02' },
    levels_text: null, risk_reward: 1.5, valid_sessions: 3, valid_until: '2026-12-02', expired: false, expired_text: null,
    corporate_action_on_session: false, corporate_action_text: null, entry_condition: '若站上 20 日高點',
    exit_conditions: [aiReason('若外資與投信轉為連續賣超')],
    reasons: [aiReason('根據收盤 233 創 20 日與 60 日新高、量比 1.39，推論突破格局成形', [{ ref: 'news:501', kind: 'news', news_id: 501, label: '聚陽接單暢旺' }, { ref: 'stock:1477:chips', kind: 'stock', label: '1477 籌碼' }])],
    level_refs: ['進場下緣 233.00＝20 日高點（11/26）'],
    ...overrides,
  }
}
export function aiListDone(overrides: Partial<AiListResponse> = {}): AiListResponse {
  return {
    status: 'done', title: 'AI 名單', mark: 'AI 推論，未經驗證', today: '2026-11-27', session_date: '2026-11-27', list_date: '2026-11-26', is_today: true,
    prompt_version: 'ai_list_v1', llm_model: 'claude-sonnet-5-5', finished_at: '2026-11-27T00:22:00+00:00', failure: null, missing_text: null,
    market: { stance: 'neutral', stance_text: '中性', confidence: 'low', confidence_text: '把握低', basis: ['tx_night', 'taiex', 'news', 'us'], basis_text: '台指期夜盤＞加權指數＞隔夜消息＞美股', reasons: [aiReason('根據台指期夜盤收 39492、與結算價持平，推論開盤缺乏方向訊號', [{ ref: 'tx:night', kind: 'tx', label: '台指期夜盤' }])] },
    sectors: [{ group_id: 'industry:28', name: 'PCB', direction: 'positive', direction_text: '可能正向', reasons: [] }],
    picks: [
      aiPick(1, { corporate_action_on_session: true, corporate_action_text: '名單日後有除權息，價位以 11/26 收盤為基準，今天的漲跌停與參考價可能不同' }),
      aiPick(2, {
        symbol: '2618', name: '長榮航', setup: 'pullback_support', setup_text: '回檔到支撐', method_text: '回檔到支撐 · 技術面＞籌碼 · 把握中', on_rule_list: false,
        levels: { entry: { type: 'pullback', low: 44.4, high: 46.05 }, stop: 42, target_1: 48.95, target_2: 50.15, risk_reward: 1.2, valid_sessions: 4, valid_until: '2026-12-03' },
        level_refs: [],
      }),
      aiPick(3, { symbol: '9999', name: '範例', levels_status: 'fail', levels: null, levels_text: '價位未通過核對，未顯示', risk_reward: null, entry_condition: null, level_refs: [] }),
    ],
    empty_reason: null, empty_text: null, data_gaps: ['台指期日盤沒有資料'], input_gaps: ['美股 費半 非最新'],
    ...overrides,
  }
}
