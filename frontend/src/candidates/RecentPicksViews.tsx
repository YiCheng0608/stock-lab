import { Link } from 'react-router-dom'

import { cx } from '../components/ui'
import type { StrategyRecentPicks } from '../types'
import { exchangeLabel, stockPath } from './candidates'
import { RECENT_NOT_TODAY, RECENT_VIEWS, type RecentView, recentChipLabel, recentPickRows, recentPickText, recentWindowText } from './recentPicks'

// 「當天」「近 60 日入選過」 (#1021): the chips under the head of 接近年高前 20 and 盈餘殖利率前 20 (my tracking's 篩選膠囊,
// DESIGN_SYSTEM §5), and the second view's rows: the stock, 「入選 k 次 · 首次 MM/DD · 最近 MM/DD」 and 「今日未入選」
// for a stock not in the day's list. No rank, close, chart or price level: the rows say only when it was listed.

export function RecentViewChips({ view, onChange, counts }: { view: RecentView; onChange: (view: RecentView) => void; counts: Record<RecentView, number> }) {
  return (
    <div className="filter-chips recent-view-chips" role="group" aria-label="名單範圍">
      {RECENT_VIEWS.map((item) => (
        <button key={item.id} type="button" className={cx('badge filter-chip', item.id === view && 'filter-chip-selected')} aria-pressed={item.id === view} onClick={() => onChange(item.id)}>
          {recentChipLabel(item.id, item.id === view, counts)}
        </button>
      ))}
    </div>
  )
}

export function RecentPicksList({ kind, picks }: { kind: 'h2' | 'x4'; picks: StrategyRecentPicks }) {
  return (
    <>
      <p className="small-note recent-picks-window">{recentWindowText(picks)}</p>
      <ol className={cx('candidate-list', 'recent-picks-list', `${kind}-recent-list`)}>
        {recentPickRows(picks).map((row) => (
          <li key={row.instrument.exchange + row.instrument.symbol} className="candidate-row recent-pick-row" data-recent-symbol={row.instrument.symbol}>
            <div className="candidate-row-main">
              <div className="candidate-row-body">
                <p className="candidate-row-title">
                  <Link className="symbol-link candidate-row-name" to={stockPath(row)}><strong>{row.instrument.symbol}</strong> {row.instrument.name}</Link>{' '}
                  <span className="candidate-row-meta">{exchangeLabel(row.instrument.exchange)}</span>
                </p>
                <div className="recent-pick-line">
                  <p className="mainstream-return recent-pick-text">{recentPickText(row)}</p>
                  {row.today_rank == null && <span className="badge badge-compact recent-not-today">{RECENT_NOT_TODAY}</span>}
                </div>
              </div>
            </div>
          </li>
        ))}
      </ol>
    </>
  )
}
