import { Link } from 'react-router-dom'

import { Term } from '../components/Term'
import { Badge, DateBadge } from '../components/ui'
import type { ActionSummary, StrategyBoard } from '../types'
import { STATUS_TONES, statusLabel, unmetText } from './strategyBoard'
import { LevelsCell } from './StrategyBoardPanel'
import { NO_BOARD_TEXT, SUMMARY_COLUMNS, SUMMARY_LINK, closestStrategy, stockVerdict } from './stockSummary'

// The summary card between the stock header and the tabs (#519; DESIGN_SYSTEM §5 個股摘要卡, UI_COPY_SPEC §8.2 摘要卡):
// can it be bought now, which condition is short, where the rule levels are. It reuses the strategy board's own blocks,
// so a level here is the same block as in the research tab, only not folded. No AI content.
export function StockSummaryCard({
  board,
  action,
  researchHref,
  onResearch,
}: {
  board: StrategyBoard | null | undefined
  action: ActionSummary | null | undefined
  researchHref: string
  onResearch?: () => void
}) {
  const verdict = stockVerdict(board, action)
  const row = closestStrategy(board)
  const date = board?.as_of ?? action?.data_cutoff ?? null
  // 完整條件 → ends the label row of the last column (DESIGN_SYSTEM §5 個股摘要卡).
  const link = <Link className="text-link stock-summary-link" to={researchHref} onClick={onResearch}>{SUMMARY_LINK}</Link>
  return (
    <section className="card stock-summary" aria-label="目前判斷摘要">
      <div className="stock-summary-col" data-summary-part="verdict">
        <div className="stock-summary-label"><span>{SUMMARY_COLUMNS.verdict}</span>{date && <DateBadge date={date} />}</div>
        <div className="stock-summary-verdict">
          <Badge tone={verdict.tone} dot className="stock-summary-badge" data-verdict={verdict.label}>{verdict.label}</Badge>
          <span className="stock-summary-reason">{verdict.reason}</span>
        </div>
      </div>
      <div className="stock-summary-col" data-summary-part="closest">
        <div className="stock-summary-label"><span>{SUMMARY_COLUMNS.closest}</span>{!row && link}</div>
        {row
          ? <>
            <div className="stock-summary-strategy">
              <strong><Term id={row.entry_type === 'breakout' ? 'breakout' : 'pullback'}>{row.label}</Term></strong>
              <Badge tone={STATUS_TONES[row.status] ?? 'default'} className="badge-compact" data-strategy-status={row.status}>{statusLabel(row.status)}</Badge>
            </div>
            <div className="stock-summary-unmet">差：{unmetText(row)}</div>
          </>
          : <div className="muted">{NO_BOARD_TEXT}</div>}
      </div>
      {row && <div className="stock-summary-col" data-summary-part="levels">
        <div className="stock-summary-label"><span>{SUMMARY_COLUMNS.levels}</span>{link}</div>
        <LevelsCell row={row} />
      </div>}
    </section>
  )
}
