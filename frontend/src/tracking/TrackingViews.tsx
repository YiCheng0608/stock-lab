import { createContext, useContext, useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useLocation } from 'react-router-dom'

import { Badge, Button, Card, DataTable, DateBadge, EmptyState, Skeleton, type Column } from '../components/ui'
import { candidateStrategyLabel, exchangeLabel, formatDate, formatEntryZone, formatPrice, formatRiskReward } from '../candidates/candidates'
import type { AddPlanResponse, StrategyDecision, TrackingPlan, TrackingPlanDetail, TrackingPlanSession, TrackingPlansResponse } from '../types'
import {
  ADD_LABEL,
  CONFLICT_TEXT,
  EMPTY_CLOSED_TEXT,
  EMPTY_OPEN_TEXT,
  HISTORY_TITLE,
  NO_CONDITION_TEXT,
  PLAN_PAGE_SIZE,
  TRACKED_LABEL,
  TRACKING_TITLE,
  addPlanErrorText,
  cancelPlanErrorText,
  hasTransitionConflict,
  planAnchor,
  planDateLine,
  planExecutionLine,
  planExitLine,
  planLink,
  planProgressLine,
  planResultLine,
  planStatus,
  planVersionText,
  sessionStatusLabel,
  sessionTriggers,
  trackingNote,
} from './tracking'

// User tracking plans (#253): the "加入追蹤" button (today candidates, stock research tab) and the actions page
// sections 追蹤計畫 / 追蹤回看. Copy follows UI_COPY_SPEC §11; status badges and level colours DESIGN_SYSTEM §7.

// The plan API calls, given by App (api.ts) or a test; views do not import api.ts themselves.
export type TrackingClient = {
  plans: (params: { status: 'open' | 'closed'; page: number; page_size: number }) => Promise<TrackingPlansResponse>
  plan: (planId: number) => Promise<TrackingPlanDetail>
  add: (payload: { signal_id: number; daily_candidate_id?: number }) => Promise<AddPlanResponse>
  cancel: (planId: number) => Promise<{ plan: TrackingPlan }>
}

const missingClient = () => Promise.reject(new Error('tracking client is not provided'))
const TrackingClientContext = createContext<TrackingClient>({ plans: missingClient, plan: missingClient, add: missingClient, cancel: missingClient })
export const TrackingClientProvider = TrackingClientContext.Provider

// Every view that shows whether a signal is tracked, refreshed after a plan is added or cancelled.
const TRACKED_QUERIES = [['tracking-plans'], ['tracking-plan'], ['candidates'], ['stock']] as const

function useRefreshTracked() {
  const client = useQueryClient()
  return () => Promise.all(TRACKED_QUERIES.map((queryKey) => client.invalidateQueries({ queryKey: [...queryKey] })))
}

export function AddPlanButton({ signalId, candidateId, openPlanId }: { signalId: number; candidateId?: number; openPlanId?: number | null }) {
  const client = useContext(TrackingClientContext)
  const refresh = useRefreshTracked()
  const [busy, setBusy] = useState(false)
  const [added, setAdded] = useState<number | null>(null)
  const [error, setError] = useState('')
  const planId = openPlanId ?? added
  if (planId != null) {
    return <div className="plan-add"><Link className="text-link" to={planLink(planId)}>{TRACKED_LABEL}</Link></div>
  }
  const add = async () => {
    setBusy(true)
    setError('')
    try {
      const result = await client.add({ signal_id: signalId, ...(candidateId != null ? { daily_candidate_id: candidateId } : {}) })
      setAdded(result.plan.id)
      await refresh()
    } catch (failure) {
      setError(addPlanErrorText(failure))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="plan-add">
      <Button size="sm" disabled={busy} onClick={add}>{busy ? '加入中…' : ADD_LABEL}</Button>
      {error && <div className="small-note plan-error" role="status">{error}</div>}
    </div>
  )
}

// Stock research tab: one row per conditional strategy of the decision summary.
export function StockPlanPanel({ strategies }: { strategies: StrategyDecision[] | undefined }) {
  const conditional = (strategies ?? []).filter((row) => row.status === 'conditional')
  return (
    <Card className="stock-plan-panel" eyebrow="追蹤計畫 · 模擬" title="把研究條件加入追蹤">
      {conditional.length
        ? (
          <ul className="plan-strategy-list">
            {conditional.map((row) => (
              <li key={row.signal_id}>
                <div><strong>{candidateStrategyLabel(row.strategy)}成立</strong><div className="small-note">條件資料日 {formatDate(row.signal_date) ?? '待核實'}</div></div>
                <AddPlanButton signalId={row.signal_id} openPlanId={row.open_plan_id} />
              </li>
            ))}
          </ul>
        )
        : <p className="small-note">{NO_CONDITION_TEXT}</p>}
      <p className="small-note">加入後每日依日線規則模擬成交與出場，結果在行動頁「{TRACKING_TITLE}」與「{HISTORY_TITLE}」；不是實際成交。</p>
    </Card>
  )
}

function CancelPlan({ plan }: { plan: TrackingPlan }) {
  const client = useContext(TrackingClientContext)
  const refresh = useRefreshTracked()
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const cancel = async () => {
    setBusy(true)
    setError('')
    try {
      await client.cancel(plan.id)
      await refresh()
    } catch (failure) {
      setError(cancelPlanErrorText(failure))
      setConfirming(false)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="plan-cancel">
      {confirming
        ? <><Button variant="ghost" size="sm" disabled={busy} onClick={cancel}>{busy ? '取消中…' : '確定取消'}</Button><Button variant="ghost" size="sm" disabled={busy} onClick={() => setConfirming(false)}>保留</Button><span className="small-note">取消後不再更新，計畫與明細會保留。</span></>
        : <Button variant="ghost" size="sm" onClick={() => setConfirming(true)}>取消追蹤</Button>}
      {error && <div className="small-note plan-error" role="status">{error}</div>}
    </div>
  )
}

// A table in a card has at most 4 columns on a phone (DESIGN_SYSTEM §5.1): date, status, close and triggers.
const SESSION_COLUMNS: ReadonlyArray<Column<TrackingPlanSession>> = [
  { key: 'date', header: '日期', cell: (session) => formatDate(session.session_date) },
  { key: 'no', header: '第幾日', wideOnly: true, cell: (session) => `第 ${session.session_no} 日` },
  { key: 'status', header: '狀態', cell: (session) => sessionStatusLabel(session.status) },
  { key: 'open', header: '開', num: true, wideOnly: true, cell: (session) => formatPrice(session.ohlc.open) },
  { key: 'high', header: '高', num: true, wideOnly: true, cell: (session) => formatPrice(session.ohlc.high) },
  { key: 'low', header: '低', num: true, wideOnly: true, cell: (session) => formatPrice(session.ohlc.low) },
  { key: 'close', header: '收', num: true, cell: (session) => formatPrice(session.ohlc.close) },
  { key: 'triggers', header: '觸發', cell: (session) => sessionTriggers(session) },
]

// The sessions are fetched when the details first open (verify's screenshot opens every <details>).
export function PlanHistory({ plan, initiallyOpen = false }: { plan: TrackingPlan; initiallyOpen?: boolean }) {
  const client = useContext(TrackingClientContext)
  const [open, setOpen] = useState(initiallyOpen)
  const detail = useQuery({ queryKey: ['tracking-plan', plan.id, plan.updated_at], queryFn: () => client.plan(plan.id), enabled: open })
  return (
    <details className="details plan-history" id={`${planAnchor(plan.id)}-history`} open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>版本、來源與逐日明細</summary>
      <p className="small-note">{planVersionText(plan)}</p>
      {!open
        ? null
        : detail.isLoading
          ? <Skeleton lines={2} label="逐日明細載入中…" />
          : detail.error
            ? <EmptyState title="明細暫時無法載入" reason="請稍後重新整理" />
            : detail.data && (detail.data.sessions.length
              ? (
                <DataTable
                  note="價格為當日原始日線（報價幣別元），觸發依計畫價位換算到當日價格基準判定；成交為模擬。"
                  columns={SESSION_COLUMNS}
                  rows={detail.data.sessions}
                  rowKey={(session) => session.session_date}
                  rowProps={(session) => ({ 'data-session-no': session.session_no })}
                />
              )
              : <p className="small-note">尚無追蹤的交易日。</p>)}
    </details>
  )
}

export function PlanCard({ plan }: { plan: TrackingPlan }) {
  const status = planStatus(plan.status)
  const { levels } = plan
  const exit = planExitLine(plan)
  const result = planResultLine(plan)
  return (
    <Card
      as="article"
      id={planAnchor(plan.id)}
      className="plan-card"
      data-plan-status={plan.status}
      eyebrow={`${exchangeLabel(plan.instrument.exchange)} · ${candidateStrategyLabel(plan.strategy)}`}
      title={<Link className="symbol-link" to={'/stocks/' + encodeURIComponent(plan.instrument.exchange) + '/' + encodeURIComponent(plan.instrument.symbol)}><strong>{plan.instrument.symbol}</strong> {plan.instrument.name}</Link>}
      aside={<div className="plan-badges"><Badge tone={status.tone} className="badge-compact">{status.label}</Badge><DateBadge date={formatDate(plan.last_session_date ?? plan.plan_date)} /></div>}
    >
      {hasTransitionConflict(plan) && <div className="warning-box plan-conflict">{CONFLICT_TEXT}</div>}
      <dl className="candidate-levels">
        <div><dt>進場區</dt><dd className="level-entry">{formatEntryZone(levels)}</dd></div>
        <div><dt>失效價</dt><dd className="level-stop">{formatPrice(levels.invalid_price)}</dd></div>
        <div><dt>目標</dt><dd className="level-target">{formatPrice(levels.target_1)}</dd></div>
        <div><dt>RR</dt><dd><Badge tone="primary" className="badge-compact">{formatRiskReward(levels.risk_reward)}</Badge></dd></div>
      </dl>
      <div className="plan-lines">
        <div className="small-note">{planDateLine(plan)}</div>
        <div className="small-note">{planProgressLine(plan)}</div>
        <div className="small-note">{planExecutionLine(plan)}</div>
        {exit && <div className="small-note">{exit}</div>}
        {result && <div className="plan-result">{result}</div>}
      </div>
      {plan.open && <CancelPlan plan={plan} />}
      <PlanHistory plan={plan} />
    </Card>
  )
}

function PlanPager({ data, page, onPage }: { data: TrackingPlansResponse; page: number; onPage: (page: number) => void }) {
  const { total_pages: pages, has_previous: previous, has_next: next } = data.pagination
  if (pages <= 1) return null
  return (
    <div className="pagination-controls">
      <span>第 {page}／{pages} 頁 · 共 {data.pagination.total.toLocaleString()} 筆</span>
      <div>
        <Button size="sm" disabled={!previous} onClick={() => onPage(page - 1)}>上一頁</Button>
        <Button size="sm" disabled={!next} onClick={() => onPage(page + 1)}>下一頁</Button>
      </div>
    </div>
  )
}

function PlanList({ scope, eyebrow, title, empty }: { scope: 'open' | 'closed'; eyebrow: string; title: string; empty: string }) {
  const client = useContext(TrackingClientContext)
  const [page, setPage] = useState(1)
  const query = useQuery({ queryKey: ['tracking-plans', scope, page], queryFn: () => client.plans({ status: scope, page, page_size: PLAN_PAGE_SIZE }) })
  const titleId = `tracking-${scope}-title`
  return (
    <section className="tracking-section" aria-labelledby={titleId} data-plan-scope={scope}>
      <div className="section-head">
        <div><div className="eyebrow">{eyebrow}</div><h2 id={titleId}>{title}</h2></div>
        {query.data && <span className="small-note">{query.data.pagination.total} 筆</span>}
      </div>
      {scope === 'open' && <p className="small-note">{trackingNote(query.data?.meta)}</p>}
      {query.isLoading
        ? <Skeleton lines={3} label={`${title}載入中…`} />
        : query.error
          ? <Card><EmptyState title="資料暫時無法載入" reason="請稍後重新整理" /></Card>
          : query.data && (query.data.items.length
            ? <><div className="plan-grid">{query.data.items.map((plan) => <PlanCard key={plan.id} plan={plan} />)}</div><PlanPager data={query.data} page={page} onPage={setPage} /></>
            : <div className="empty panel">{empty}</div>)}
    </section>
  )
}

// Actions page: after 我的庫存 (real positions), before the action cards; the three never mix.
export function TrackingSection() {
  const location = useLocation()
  useEffect(() => {
    if (!location.hash.startsWith('#plan-')) return
    const timer = window.setInterval(() => {
      const target = document.getElementById(location.hash.slice(1))
      if (target) { target.scrollIntoView({ block: 'start' }); window.clearInterval(timer) }
    }, 200)
    const stop = window.setTimeout(() => window.clearInterval(timer), 5000)
    return () => { window.clearInterval(timer); window.clearTimeout(stop) }
  }, [location.hash])
  return (
    <>
      <PlanList scope="open" eyebrow="模擬追蹤 · 進行中" title={TRACKING_TITLE} empty={EMPTY_OPEN_TEXT} />
      <PlanList scope="closed" eyebrow="模擬追蹤 · 已結束" title={HISTORY_TITLE} empty={EMPTY_CLOSED_TEXT} />
    </>
  )
}
