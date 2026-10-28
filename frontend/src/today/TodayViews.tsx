import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { formatDay, formatTaipeiDay } from '../dates'
import type { ActionSummary, MarketOverview, MarketOverviewExchange } from '../types'
import { cx } from '../components/ui'
import { formatFixed } from '../units'

// Today page header line, market overview and holding-risk alert (#276).
// Order and layout follow DESIGN_SYSTEM §4/§5; copy and units follow UI_COPY_SPEC §11.

const EXCHANGES = [
  { exchange: 'TWSE', label: '上市', index: '加權指數' },
  { exchange: 'TPEx', label: '上櫃', index: '櫃買指數' },
] as const
type ExchangeSpec = (typeof EXCHANGES)[number]

const SCOPE_LABELS: Record<string, string> = {
  twse_all_securities: '集中市場總計（含 ETF、權證等）',
  tpex_stocks: '上櫃股票',
}
// Shown next to each turnover amount, so the scope is on screen without opening 資料說明 (UI_COPY_SPEC §11).
const SHORT_SCOPE_LABELS: Record<string, string> = {
  twse_all_securities: '集中市場總計',
  tpex_stocks: '上櫃股票',
}

const isFiniteNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const dash = (value: number | null | undefined, digits = 0) => isFiniteNumber(value) ? formatFixed(value, digits) : '—'

function available(overview: MarketOverview | undefined, exchange: string): MarketOverviewExchange | null {
  const row = overview?.exchanges.find((item) => item.exchange === exchange)
  return row?.status === 'available' ? row : null
}

const missingText = (spec: ExchangeSpec) => `${spec.label}大盤資料未取得`

function changeTone(value: number | null | undefined): string | null {
  if (!isFiniteNumber(value) || Number(value.toFixed(2)) === 0) return null
  return value > 0 ? 'tone-up' : 'tone-down'
}

function IndexWidget({ spec, row }: { spec: ExchangeSpec; row: MarketOverviewExchange | null }) {
  const index = row?.index
  const pct = isFiniteNumber(index?.change_pct) ? `${formatFixed(index.change_pct * 100, 2, true)}%` : '—'
  return (
    <div className="market-widget market-index" data-exchange={spec.exchange}>
      <div className="market-widget-head"><span className="market-widget-label">{spec.index}</span><span className="market-widget-unit">點</span></div>
      {index ? <>
        <div className="market-widget-value">{dash(index.close, 2)}</div>
        <div className={cx('market-widget-change', changeTone(index.change))}>{isFiniteNumber(index.change) ? formatFixed(index.change, 2, true) : '—'}（{pct}）</div>
      </> : <div className="market-widget-empty">{missingText(spec)}</div>}
    </div>
  )
}

// Turnover is stored in 元 and shown in 億元 with two decimals, followed by its short scope.
function turnoverText(row: MarketOverviewExchange): ReactNode {
  const { value, scope, scope_label: scopeLabel } = row.turnover ?? { value: null, scope: null, scope_label: null }
  const short = (scope ? SHORT_SCOPE_LABELS[scope] : undefined) ?? scopeLabel
  return <>{isFiniteNumber(value) ? formatFixed(value / 1e8, 2) : '—'}{short && <> <span className="market-row-scope">{short}</span></>}</>
}

function breadthText(row: MarketOverviewExchange): string {
  const breadth = row.breadth
  if (!breadth) return '—'
  const limits = breadth.limit_up == null && breadth.limit_down == null ? '' : `（${dash(breadth.limit_up)}／${dash(breadth.limit_down)}）`
  return `上漲 ${dash(breadth.advancers)} · 下跌 ${dash(breadth.decliners)} · 平盤 ${dash(breadth.unchanged)}${limits}`
}

function DualWidget({ className, label, unit, overview, value }: { className: string; label: string; unit: string; overview: MarketOverview | undefined; value: (row: MarketOverviewExchange) => ReactNode }) {
  return (
    <div className={cx('market-widget market-widget-dual', className)}>
      <div className="market-widget-head"><span className="market-widget-label">{label}</span><span className="market-widget-unit">{unit}</span></div>
      {EXCHANGES.map((spec) => {
        const row = available(overview, spec.exchange)
        return row
          ? <div key={spec.exchange} className="market-row" data-exchange={spec.exchange}><span className="market-row-label">{spec.label}</span> {value(row)}</div>
          : <div key={spec.exchange} className="market-row market-row-empty" data-exchange={spec.exchange}>{missingText(spec)}</div>
      })}
    </div>
  )
}

function TurnoverAndBreadth({ overview }: { overview: MarketOverview | undefined }) {
  return <>
    <DualWidget className="market-turnover" label="成交金額" unit="億元" overview={overview} value={turnoverText} />
    <DualWidget className="market-breadth" label="漲跌家數（股票）" unit="括號為漲停／跌停" overview={overview} value={breadthText} />
  </>
}

// One row of four widgets; phones keep the two indexes and fold turnover and breadth into a <details>.
export function MarketOverviewView({ overview }: { overview: MarketOverview | undefined }) {
  return (
    <section className="market-overview" aria-label="大盤概況">
      <div className="market-overview-grid">
        {EXCHANGES.map((spec) => <IndexWidget key={spec.exchange} spec={spec} row={available(overview, spec.exchange)} />)}
        <TurnoverAndBreadth overview={overview} />
      </div>
      <details className="details market-overview-more">
        <summary>成交金額與漲跌家數</summary>
        <div className="market-overview-more-grid"><TurnoverAndBreadth overview={overview} /></div>
      </details>
    </section>
  )
}

// 資料說明 lines about the overview: the turnover scope of each exchange shown, how a derived change is computed.
export function marketOverviewNotes(overview: MarketOverview | undefined): string[] {
  const scopes = EXCHANGES.flatMap((spec) => {
    const turnover = available(overview, spec.exchange)?.turnover
    const label = turnover?.scope_label ?? (turnover?.scope ? SCOPE_LABELS[turnover.scope] : undefined)
    return label ? [`${spec.label}為${label}`] : []
  })
  const derived = available(overview, 'TPEx')?.index?.change_pct_method === 'derived'
  return [
    ...(scopes.length ? [`成交金額範圍：${scopes.join('；')}`] : []),
    ...(derived ? ['櫃買指數漲跌幅依前一日收市指數計算'] : []),
  ]
}

export const UP_DOWN_NOTE = '紅色為上漲、綠色為下跌（台股慣例）'

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
  return (
    <section className="home-header" aria-label="資料狀態">
      {/* No visible page title (DESIGN_SYSTEM §3); assistive tech still gets one. */}
      <h1 className="sr-only">今日</h1>
      <div className="home-dataline">
        {/* A failed load has no source or mode: the line is only 「資料截至 未提供」. */}
        <span className="home-dataline-text">{loading ? '資料截至 載入中…' : [`資料截至 ${day ?? '未提供'}`, sourceLabel, modeLabel].filter(Boolean).join(' · ')}</span>
        {badge}
      </div>
      <details className="data-explanation">
        <summary>資料說明</summary>
        {scopeText && <div>{scopeText}</div>}
        {marketOverviewNotes(overview).map((line) => <div key={line}>{line}</div>)}
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
  if (['data_insufficient', 'data_incomplete', 'insufficient_data'].includes(action.action_state)) return '持倉風險資料待補'
  if (action.position_quantity_status === 'unknown') return QUANTITY_UNKNOWN
  return null
}

const ALERT_LISTED = 3

// Shown above the candidates only when a holding is at risk; the action centre has the detail (PRODUCT_SPEC §2).
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
      <Link className="text-link" to="/actions">查看行動中心 →</Link>
    </div>
  )
}
