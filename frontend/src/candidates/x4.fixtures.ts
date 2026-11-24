import type { X4Item, X4Response } from '../types'

// /api/strategy-lists/x4 responses for the frontend tests (#1019), the shape of backend/app/x4_list.py present and
// _empty: computed and zero carry universe_count and item_count, missing has them null; zero carries zero_reason.

const closes = (start: number, step: number) => ({
  dates: Array.from({ length: 30 }, (_, index) => `2026-10-${String(index + 1).padStart(2, '0')}`),
  closes: Array.from({ length: 30 }, (_, index) => start + step * index),
})

const VERSION = 'explore_research_v2_X4'
const SHA = '0f4c1d7e2a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5'

export function x4Item(rank: number, overrides: Partial<X4Item> = {}): X4Item {
  return {
    rank,
    instrument: { id: 3000 + rank, exchange: 'TWSE', symbol: String(5000 + rank), name: `殖利率${rank}`, instrument_type: 'stock' },
    eps_yield_raw: 0.2 - 0.01 * rank,
    revenue_yoy: 0.1,
    revenue_month: '2026-10',
    quarter_eps: { quarter: '2026Q3', period_end: '2026-09-30', eps: 1.5, year_before_eps: 1.2 },
    close: 30 + rank,
    market: { trading_date: '2026-11-20', close: 30 + rank, change: 0.5, change_pct: 0.01, change_status: 'known', source: 'twse_stock_day_all' },
    recent_closes: closes(25, 0.2),
    today_list: null,
    ...overrides,
  }
}

export function x4Response(overrides: Partial<X4Response> = {}): X4Response {
  return {
    status: 'computed',
    zero_reason: null,
    trading_date: '2026-11-20',
    version: VERSION,
    definitions_sha256: SHA,
    list_size: 20,
    computed_at: '2026-11-20T13:45:00+00:00',
    universe_count: 586,
    item_count: 3,
    items: [
      x4Item(1, {
        instrument: { id: 1, exchange: 'TWSE', symbol: '2330', name: '台積電', instrument_type: 'stock' },
        eps_yield_raw: 0.123449,
        revenue_yoy: 0.251,
        revenue_month: '2026-10',
        quarter_eps: { quarter: '2026Q3', period_end: '2026-09-30', eps: 3.21, year_before_eps: 2.1 },
        close: 1045,
        market: { trading_date: '2026-11-20', close: 1045, change: 12.7, change_pct: 0.0123, change_status: 'known', source: 'twse_stock_day_all' },
        today_list: { rank: 3, entry_type: 'breakout', score_version: 'candidate_score_v7' },
      }),
      // A loss a year before and a month before October: 「（去年同季 -0.50）」, 「（9 月）」.
      x4Item(2, {
        instrument: { id: 2, exchange: 'TPEx', symbol: '6274', name: '台燿', instrument_type: 'stock' },
        eps_yield_raw: 0.0805,
        revenue_yoy: 0.0312,
        revenue_month: '2026-09',
        quarter_eps: { quarter: '2026Q3', period_end: '2026-09-30', eps: 4.64, year_before_eps: -0.5 },
        close: 230.5,
        market: { trading_date: '2026-11-20', close: 230.5, change: -2, change_pct: -0.0086, change_status: 'known', source: 'tpex_daily' },
        recent_closes: closes(240, -0.5),
      }),
      x4Item(3),
    ],
    ...overrides,
  }
}

// _empty(day): no run of the day (or none at all when the date is null).
export function missingX4(day: string | null = '2026-11-20'): X4Response {
  return {
    status: 'missing',
    zero_reason: null,
    trading_date: day,
    version: VERSION,
    definitions_sha256: SHA,
    list_size: 20,
    computed_at: null,
    universe_count: null,
    item_count: null,
    items: [],
  }
}

// zero: an empty universe, or members none of which passes both filters.
export function zeroX4(reason: 'universe_empty' | 'none_passed' = 'universe_empty'): X4Response {
  return { ...x4Response(), status: 'zero', zero_reason: reason, universe_count: reason === 'universe_empty' ? 0 : 586, item_count: 0, items: [] }
}
