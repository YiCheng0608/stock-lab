import type { MainstreamItem, MainstreamResponse } from '../types'

// /api/mainstream responses for the frontend tests (#769), the shape of backend/app/mainstream.py mainstream_list and
// _empty as merged in PR 771: computed and zero carry universe_count and ranked_group_count, missing has neither key.

const GROUPS: MainstreamResponse['groups'] = [
  // Out of rank order on purpose: the head lists the names by rank.
  { id: 'theme-ai-server', name: 'AI 伺服器', group_type: 'theme', strength: 0.31, rank: 2, member_count: 12, top_count: 4 },
  { id: 'industry-semiconductor', name: '半導體', group_type: 'official_industry', strength: 0.42, rank: 1, member_count: 30, top_count: 10 },
  { id: 'industry-computer', name: '電腦及週邊設備', group_type: 'official_industry', strength: 0.2, rank: 3, member_count: 25, top_count: 9 },
]

const closes = (start: number, step: number) => ({
  dates: Array.from({ length: 30 }, (_, index) => `2026-10-${String(index + 1).padStart(2, '0')}`),
  closes: Array.from({ length: 30 }, (_, index) => start + step * index),
})

export function mainstreamItem(rank: number, overrides: Partial<MainstreamItem> = {}): MainstreamItem {
  return {
    rank,
    instrument: { id: 1000 + rank, exchange: 'TWSE', symbol: String(3000 + rank), name: `示範${rank}`, instrument_type: 'stock' },
    groups: [{ id: 'industry-semiconductor', name: '半導體', group_type: 'official_industry', rank: 1 }],
    return_w: 0.5 - rank * 0.01,
    excess_w: 0.3 - rank * 0.01,
    market: { trading_date: '2026-11-13', close: 100 + rank, change: 1, change_pct: 0.01, change_status: 'known', source: 'twse_stock_day_all' },
    recent_closes: closes(80, 0.5),
    today_list: null,
    ...overrides,
  }
}

export function mainstreamResponse(overrides: Partial<MainstreamResponse> = {}): MainstreamResponse {
  return {
    status: 'computed',
    trading_date: '2026-11-13',
    version: 'mainstream_v1',
    window: 240,
    group_count: 3,
    computed_at: '2026-11-13T10:30:00+00:00',
    index_return: 0.2133,
    universe_count: 812,
    ranked_group_count: 64,
    groups: GROUPS,
    items: [
      mainstreamItem(1, {
        instrument: { id: 1, exchange: 'TWSE', symbol: '2330', name: '台積電', instrument_type: 'stock' },
        groups: [
          { id: 'industry-semiconductor', name: '半導體', group_type: 'official_industry', rank: 1 },
          { id: 'theme-ai-server', name: 'AI 伺服器', group_type: 'theme', rank: 2 },
        ],
        return_w: 0.45671,
        excess_w: 0.12344,
        market: { trading_date: '2026-11-13', close: 1085, change: 15, change_pct: 0.014, change_status: 'known', source: 'twse_stock_day_all' },
        today_list: { rank: 2, entry_type: 'breakout', score_version: 'candidate_score_v7' },
      }),
      mainstreamItem(2, {
        instrument: { id: 2, exchange: 'TPEx', symbol: '6274', name: '台燿', instrument_type: 'stock' },
        return_w: 0.3,
        excess_w: -0.0123,
        market: { trading_date: '2026-11-13', close: 230.5, change: -2, change_pct: -0.0086, change_status: 'known', source: 'tpex_daily' },
        recent_closes: closes(240, -0.5),
      }),
    ],
    ...overrides,
  }
}

// _empty('missing', day): no run of the day (or none at all when the date is null); no universe/ranked counts.
export function missingMainstream(day: string | null = '2026-11-13'): MainstreamResponse {
  return {
    status: 'missing',
    trading_date: day,
    version: 'mainstream_v1',
    window: 240,
    group_count: 5,
    computed_at: null,
    index_return: null,
    groups: [],
    items: [],
  }
}

export function zeroMainstream(): MainstreamResponse {
  return { ...mainstreamResponse(), status: 'zero', group_count: 5, universe_count: 1234, ranked_group_count: 0, groups: [], items: [] }
}
