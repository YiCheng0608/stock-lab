import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { formatDay, formatTaipeiDay } from '../dates'
import type { ActionSummary, MarketOverview } from '../types'
import { DateBadge, cx } from '../components/ui'
import { useSameAsPage } from '../components/pageDate'
import { DERIVED_NOTE, MARKET_PATH, UP_DOWN_NOTE, isDerived, summaryItems } from '../market/marketOverview'

// Today page header line, the one-line market summary and the holding-risk alert (#276; Issue 549 moved the
// overview to /market). Order and layout follow DESIGN_SYSTEM §4/§5; copy and units follow UI_COPY_SPEC §11.

// One line in place of the old four-widget bar: 加權 and 櫃買 close and change, the data date, and 看大盤 →.
export function MarketSummaryLine({ overview }: { overview: MarketOverview | undefined }) {
  return (
    <section className="market-summary" aria-label="大盤摘要">
      <span className="market-summary-label">大盤</span>
      {summaryItems(overview).map(({ spec, close, pct, tone }) => close == null
        ? <span key={spec.exchange} className="market-summary-item market-summary-empty" data-exchange={spec.exchange}>{spec.short} 未取得</span>
        : <span key={spec.exchange} className="market-summary-item" data-exchange={spec.exchange}>
          <span className="market-summary-name">{spec.short}</span> <b>{close}</b> <span className={cx('market-summary-change', tone)}>{pct}</span>
        </span>)}
      <DateBadge date={overview?.trading_date ?? null} />
      <Link className="text-link market-summary-link" to={MARKET_PATH}>看大盤 →</Link>
    </section>
  )
}

// 資料說明 lines about the summary: how a derived TPEx change is computed (the turnover scopes are on /market).
export function marketSummaryNotes(overview: MarketOverview | undefined): string[] {
  return isDerived(overview) ? [DERIVED_NOTE] : []
}

// One line instead of the old hero: data date · source · snapshot mode, then the quality badge and 資料說明.
export function TodayHeader({ loading = false, asOf, sourceLabel, modeLabel, badge, scopeText, overview }: {
  loading?: boolean
  asOf: string | null | undefined
  sourceLabel: string
  modeLabel: string
  badge?: ReactNode
  scopeText?: string
  overview: MarketOverview | undefined
}) {
  // A plain trading date is a calendar day; an instant is read in Taipei time (as the navbar badge).
  const day = !asOf ? null : /^\d{4}-\d{2}-\d{2}$/.test(asOf) ? formatDay(asOf) : formatTaipeiDay(asOf) ?? formatDay(asOf)
  // The navbar already states that day (#661): the line keeps only the source and mode; another day still reads here.
  const sameDate = useSameAsPage(day)
  return (
    <section className="home-header" aria-label="資料狀態">
      {/* No visible page title (DESIGN_SYSTEM §3); assistive tech still gets one. */}
      <h1 className="sr-only">今日</h1>
      <div className="home-dataline">
        {/* A failed load has no source or mode: the line is only 「資料截至 未提供」. */}
        <span className="home-dataline-text">{loading ? '資料截至 載入中…' : [sameDate ? '' : `資料截至 ${day ?? '未提供'}`, sourceLabel, modeLabel].filter(Boolean).join(' · ')}</span>
        {badge}
      </div>
      <details className="data-explanation">
        <summary>資料說明</summary>
        {scopeText && <div>{scopeText}</div>}
        {marketSummaryNotes(overview).map((line) => <div key={line}>{line}</div>)}
        <div>{UP_DOWN_NOTE}</div>
      </details>
    </section>
  )
}

const QUANTITY_UNKNOWN = '庫存數量待核實'

// A verified holding risk: a held row (or one whose quantity is unknown) that reduce_exit, lacks strategy data, or has an unverified quantity.
function holdingRisk(action: ActionSummary): string | null {
  const held = action.held === true || action.position_quantity_status === 'unknown'
  if (!held) return null
  if (action.action_state === 'reduce_exit') return '減碼／退場條件'
  if (['data_insufficient', 'data_incomplete', 'insufficient_data'].includes(action.action_state)) return '持倉風險資料不足'
  if (action.position_quantity_status === 'unknown') return QUANTITY_UNKNOWN
  return null
}

const ALERT_LISTED = 3

// Shown above the candidates only when a holding is at risk; 我的追蹤 (/watch) has the detail (PRODUCT_SPEC §2).
export function HoldingAlert({ actions }: { actions: readonly ActionSummary[] }) {
  const risks = actions.flatMap((action) => {
    const reason = holdingRisk(action)
    return reason ? [`${action.instrument.symbol} ${action.instrument.name}：${reason}`] : []
  })
  if (risks.length === 0) return null
  const listed = risks.slice(0, ALERT_LISTED).join('；') + (risks.length > ALERT_LISTED ? ` 等 ${risks.length} 檔` : '')
  return (
    <div className="alert-row alert-warning" role="status">
      <span>持倉風險 {risks.length} 檔：{listed}</span>
      <Link className="text-link" to="/watch">查看我的追蹤 →</Link>
    </div>
  )
}
