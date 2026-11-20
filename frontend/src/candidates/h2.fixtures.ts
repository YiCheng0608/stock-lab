import type { H2Item, H2Response } from '../types'

// /api/h2 responses for the frontend tests (#882), the shape of backend/app/h2_list.py h2_list and _empty: computed and
// zero carry universe_count, missing has it null; items carry market and recent_closes (#882's read fields).

const closes = (start: number, step: number) => ({
  dates: Array.from({ length: 30 }, (_, index) => `2026-10-${String(index + 1).padStart(2, '0')}`),
  closes: Array.from({ length: 30 }, (_, index) => start + step * index),
})

export function h2Item(rank: number, overrides: Partial<H2Item> = {}): H2Item {
  return {
    rank,
    instrument: { id: 2000 + rank, exchange: 'TWSE', symbol: String(4000 + rank), name: `年高${rank}`, instrument_type: 'stock' },
    high_gap_240: -0.01 * rank,
    close: 50 + rank,
    market: { trading_date: '2026-11-20', close: 50 + rank, change: 0.5, change_pct: 0.01, change_status: 'known', source: 'twse_stock_day_all' },
    recent_closes: closes(40, 0.3),
    today_list: null,
    ...overrides,
  }
}

export function h2Response(overrides: Partial<H2Response> = {}): H2Response {
  return {
    status: 'computed',
    trading_date: '2026-11-20',
    version: 'explore_research_v2_X2',
    definitions_sha256: '600dc942361847eb9591425b4eb97ce4178b477695ff34fc234e45a665ebec63',
    window: 240,
    computed_at: '2026-11-20T13:40:00+00:00',
    universe_count: 586,
    items: [
      // At its one-year high: 0.00%.
      h2Item(1, {
        instrument: { id: 1, exchange: 'TWSE', symbol: '2330', name: '台積電', instrument_type: 'stock' },
        high_gap_240: 0,
        close: 1085,
        market: { trading_date: '2026-11-20', close: 1085, change: 15, change_pct: 0.014, change_status: 'known', source: 'twse_stock_day_all' },
        today_list: { rank: 2, entry_type: 'breakout', score_version: 'candidate_score_v7' },
      }),
      h2Item(2, {
        instrument: { id: 2, exchange: 'TPEx', symbol: '6274', name: '台燿', instrument_type: 'stock' },
        high_gap_240: -0.032144,
        close: 230.5,
        market: { trading_date: '2026-11-20', close: 230.5, change: -2, change_pct: -0.0086, change_status: 'known', source: 'tpex_daily' },
        recent_closes: closes(240, -0.5),
      }),
      // Fewer than 240 bars: no value, filled after the valued ones.
      h2Item(3, { high_gap_240: null }),
    ],
    ...overrides,
  }
}

// _empty('missing', day): no run of the day (or none at all when the date is null).
export function missingH2(day: string | null = '2026-11-20'): H2Response {
  return {
    status: 'missing',
    trading_date: day,
    version: 'explore_research_v2_X2',
    definitions_sha256: '600dc942361847eb9591425b4eb97ce4178b477695ff34fc234e45a665ebec63',
    window: 240,
    computed_at: null,
    universe_count: null,
    items: [],
  }
}

export function zeroH2(): H2Response {
  return { ...h2Response(), status: 'zero', universe_count: 0, items: [] }
}
