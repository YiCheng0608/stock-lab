import type { StrategyRecentPicks, StrategyRecentRow } from '../types'

// recent_picks of /api/strategy-lists/{strategy} for the frontend tests (#1021), the shape of
// backend/app/strategy_lists.py recent_picks. The rows are out of order on purpose: the page sorts them.

const row = (id: number, symbol: string, name: string, count: number, first: string, last: string, todayRank: number | null, exchange = 'TWSE'): StrategyRecentRow => ({
  instrument: { id, exchange, symbol, name, instrument_type: 'stock' },
  count,
  first_date: first,
  last_date: last,
  today_rank: todayRank,
})

export function recentPicks(overrides: Partial<StrategyRecentPicks> = {}): StrategyRecentPicks {
  return {
    sessions: 60,
    days: 60,
    since: '2026-08-25',
    items: [
      // Not in the day's list: listed 5 times, the last on 11/10.
      row(9, '2603', '長榮', 5, '2026-09-01', '2026-11-10', null),
      row(1, '2330', '台積電', 12, '2026-08-25', '2026-11-20', 1),
      // As often as 2603, listed later: before it.
      row(2, '6274', '台燿', 5, '2026-10-01', '2026-11-20', 2, 'TPEx'),
      row(8, '1101', '台泥', 1, '2026-09-15', '2026-09-15', null),
    ],
    ...overrides,
  }
}
