import type { ReactElement } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'

import {
  CONFLICT_TEXT,
  EMPTY_CLOSED_TEXT,
  EMPTY_OPEN_TEXT,
  NO_CONDITION_TEXT,
  PLAN_STATUS,
  addPlanErrorText,
  cancelPlanErrorText,
  formatSignedReturn,
  formatTaipeiDate,
  planDateLine,
  planResultLine,
  trackingNote,
} from './tracking'
import { ambiguous, cancelled, conflict, detailResponse, expired, invalidated, listResponse, meta, plan, suspendedClose, targetHit, triggered } from './tracking.fixtures'
import { AddPlanButton, PlanCard, PlanHistory, StockPlanPanel, TrackingSection } from './TrackingViews'
import type { StrategyDecision } from '../types'

// Standalone regression module (no browser, no server, no network) for the user tracking plans (#253):
// plan cards per status, the actions page sections, the history table and the "加入追蹤" buttons.
const check = (condition: boolean, message: string) => { if (!condition) throw new Error(message) }
const count = (markup: string, needle: string) => markup.split(needle).length - 1
const slice = (markup: string, start: string, end: string) => {
  const from = markup.indexOf(start)
  return from < 0 ? '' : markup.slice(from, markup.indexOf(end, from + start.length))
}
function render(element: ReactElement, cache: Array<[readonly unknown[], unknown]> = []) {
  const client = new QueryClient()
  for (const [key, data] of cache) client.setQueryData(key, data)
  return renderToStaticMarkup(<QueryClientProvider client={client}><StaticRouter location="/actions">{element}</StaticRouter></QueryClientProvider>)
}

// ---- formatting ----
check(formatSignedReturn(0.0939) === '+9.39%' && formatSignedReturn(-0.0268) === '-2.68%' && formatSignedReturn(0) === '0.00%', 'signed returns, two decimals')
check(formatSignedReturn(-0.00001) === '0.00%' && formatSignedReturn(null) === '—', 'no negative zero, null is 「—」')
check(formatTaipeiDate('2026-10-16T15:30:00+00:00') === '2026/10/16' && formatTaipeiDate('2026-10-16T16:30:00+00:00') === '2026/10/17', 'created date is the Taipei date')
check(formatTaipeiDate(null) === null && formatTaipeiDate('nope') === null, 'missing or bad instants')
check(planDateLine(plan()) === '計畫資料日 2026/10/16 · 建立 2026/10/16', 'plan date and creation date line')
check(trackingNote(meta()).includes('買賣各 5 bps 滑價、來回 30 bps 成本假設') && trackingNote(undefined).includes('不是實際成交'), 'note names the assumptions')

// ---- status badges (DESIGN_SYSTEM §7) ----
const tones: Record<string, [string, string]> = {
  pending: ['待觸發', 'primary'], triggered: ['已觸發', 'warning'], target_hit: ['達標', 'success'], invalidated: ['失效', 'error'],
  incomparable: ['無法比較', 'warning'], expired: ['到期', 'default'], closed: ['期滿結算', 'default'], cancelled: ['已取消', 'default'],
}
for (const [status, [label, tone]] of Object.entries(tones)) {
  check(PLAN_STATUS[status].label === label && PLAN_STATUS[status].tone === tone, `${status} is ${label} (${tone})`)
}
for (const item of [plan(), triggered(), targetHit(), invalidated(), expired(), suspendedClose(), ambiguous(), cancelled()]) {
  const markup = render(<PlanCard plan={item} />)
  const [label, tone] = tones[item.status]
  const badge = tone === 'default' ? `class="badge badge-compact">${label}</span>` : `class="badge badge-${tone} badge-compact">${label}</span>`
  check(markup.includes(badge), `${item.status} card has the ${label} badge`)
  check(markup.includes(`id="plan-${item.id}"`) && markup.includes(`id="plan-${item.id}-history"`), `${item.status} card has its anchors`)
  check(!markup.includes('勝率'), `${item.status} card never says 勝率`)
}

// ---- simulated result lines ----
check(planResultLine(plan()) === null && planResultLine(triggered()) === null, 'open plans have no result')
check(planResultLine(targetHit()) === '模擬報酬 +9.39%' && planResultLine(invalidated()) === '模擬報酬 -2.68%', 'comparable results')
check(planResultLine(expired()) === '模擬報酬：無法比較（視窗內未模擬成交）', 'expired: no fill')
check(planResultLine(suspendedClose()) === '模擬報酬：無法比較（期間有停牌或不可比較的日線）', 'suspension makes it incomparable')
check(planResultLine(ambiguous()) === '模擬報酬：無法比較（同一交易日失效價與目標一都觸及，先後順序不明）', 'same-session stop and target')
check(planResultLine(cancelled()) === '模擬報酬：無法比較（已取消）', 'cancelled')
check(planResultLine(plan({ status: 'incomparable', status_reason: 'insufficient_sessions', open: false, result_comparable: false, execution_date: '2026-10-19' })) === '模擬報酬：無法比較（40 個交易日內該股不足 20 根日線）', 'too few bars')

// ---- one card ----
const pending = render(<PlanCard plan={plan()} />)
for (const text of ['2377', '微星', '上市 · 突破條件', '資料 2026/10/16', '計畫資料日 2026/10/16 · 建立 2026/10/16', '第 0／20 個交易日', '尚未模擬成交', '>取消追蹤</button>', 'href="/stocks/TWSE/2377"']) {
  check(pending.includes(text), `pending card shows ${text}`)
}
check(pending.includes('class="level-entry">161.50') && pending.includes('class="level-stop">157.82') && pending.includes('class="level-target">167.39'), 'level colours as the candidate card')
check(!pending.includes('模擬報酬') && !pending.includes(CONFLICT_TEXT), 'pending card has no result and no conflict note')
const filled = render(<PlanCard plan={triggered()} />)
check(filled.includes('模擬成交 2026/10/20 161.58') && filled.includes('第 3／20 個交易日') && filled.includes('資料 2026/10/21'), 'triggered card: fill, progress and last tracked date')
const hit = render(<PlanCard plan={targetHit()} />)
check(hit.includes('上櫃 · 回踩條件') && hit.includes('13.05～13.35') && hit.includes('模擬出場 2026/10/07 14.49') && hit.includes('模擬報酬 +9.39%'), 'ended card: zone, exit and return')
check(!hit.includes('取消追蹤'), 'an ended plan cannot be cancelled')
check(hit.includes('來源 個股研究條件 · 策略版本 3 · 公式 institutional-flow/v1-shares-per-twd-turnover · 追蹤規則 plan_tracking_v1'), 'versions and source in the details')
check(pending.includes('來源 今日候選') && pending.includes('評分 candidate_score_v1'), 'candidate plans name the score version')
const corrected = render(<PlanCard plan={conflict()} />)
check(corrected.includes(CONFLICT_TEXT) && corrected.includes('>已觸發</span>'), 'transition conflict keeps the stored status and adds the note')
check(!render(<PlanCard plan={cancelled()} />).includes('取消追蹤'), 'a cancelled plan has no cancel button')

// ---- history table ----
const detail = detailResponse()
const history = render(<PlanHistory plan={detail.plan} initiallyOpen />, [[['tracking-plan', detail.plan.id, detail.plan.updated_at], detail]])
check(history.includes('<details class="details plan-history" id="plan-3-history" open="">'), 'history opens')
check(count(history, 'data-session-no=') === 4, 'one row per session')
const row1 = slice(history, 'data-session-no="1"', '</tr>')
for (const text of ['2026/10/02', '第 1 日', '已模擬成交', '>13.20<', '>13.40<', '>13.10<', '>13.30<', '進場']) check(row1.includes(text), `first row shows ${text}`)
check(slice(history, 'data-session-no="4"', '</tr>').includes('達標') && slice(history, 'data-session-no="4"', '</tr>').includes('目標'), 'target row')
check(slice(history, 'data-session-no="2"', '</tr>').includes('>—<'), 'no trigger is 「—」')
check(history.includes('class="num">13.30') && history.includes('<th class="num">收</th>'), 'numbers are right-aligned mono cells')
check(!render(<PlanHistory plan={detail.plan} />).includes('data-session-no'), 'closed history fetches nothing')

// ---- actions page sections ----
const opened = listResponse([triggered(), plan()])
const closed = listResponse([targetHit(), invalidated(), expired(), cancelled()])
const section = render(<TrackingSection />, [[['tracking-plans', 'open', 1], opened], [['tracking-plans', 'closed', 1], closed]])
check(section.indexOf('>追蹤計畫</h2>') >= 0 && section.indexOf('>追蹤計畫</h2>') < section.indexOf('>追蹤回看</h2>'), '追蹤計畫 before 追蹤回看')
check(section.includes(trackingNote(meta())), 'the simulation note')
const openPart = slice(section, 'data-plan-scope="open"', 'data-plan-scope="closed"')
const closedPart = section.slice(section.indexOf('data-plan-scope="closed"'))
check(count(openPart, 'class="card plan-card"') === 2 && count(closedPart, 'class="card plan-card"') === 4, 'cards split by scope')
check(openPart.includes('>2 筆<') && closedPart.includes('>4 筆<'), 'counts per section')
check(!openPart.includes('模擬報酬') && count(closedPart, '模擬報酬') === 4, 'results only in the look-back')
check(openPart.indexOf('id="plan-2"') < openPart.indexOf('id="plan-1"'), 'API order is kept')
check(!section.includes('pagination-controls'), 'one page needs no pager')
const paged = render(<TrackingSection />, [[['tracking-plans', 'open', 1], listResponse([plan()], 25)], [['tracking-plans', 'closed', 1], listResponse([])]])
check(paged.includes('第 1／2 頁 · 共 25 筆'), 'more than one page shows the pager')
const empty = render(<TrackingSection />, [[['tracking-plans', 'open', 1], listResponse([])], [['tracking-plans', 'closed', 1], listResponse([])]])
check(empty.includes(EMPTY_OPEN_TEXT) && empty.includes(EMPTY_CLOSED_TEXT), 'two empty states')
check(render(<TrackingSection />).includes('追蹤計畫載入中…'), 'loading skeleton')

// ---- 加入追蹤 ----
check(render(<AddPlanButton signalId={1} />).includes('>加入追蹤</button>'), 'untracked signal: secondary button')
check(render(<AddPlanButton signalId={1} />).includes('class="btn btn-secondary btn-sm"'), 'the add button is secondary, not primary')
check(render(<AddPlanButton signalId={1} openPlanId={5} />).includes('href="/actions#plan-5">已在追蹤</a>'), 'tracked signal: link to its plan')
const strategy = (status: string, signalId: number, openPlanId: number | null = null) => ({ strategy: 'breakout_v1', signal_id: signalId, signal_date: '2026-10-16', status, open_plan_id: openPlanId }) as unknown as StrategyDecision
const stockPanel = render(<StockPlanPanel strategies={[strategy('conditional', 1), strategy('observation', 2), strategy('conditional', 3, 9)]} />)
check(count(stockPanel, '突破條件成立') === 2 && stockPanel.includes('條件資料日 2026/10/16'), 'one row per conditional strategy')
check(stockPanel.includes('>加入追蹤</button>') && stockPanel.includes('href="/actions#plan-9">已在追蹤</a>'), 'add or tracked per row')
check(!stockPanel.includes(NO_CONDITION_TEXT), 'conditional rows hide the no-condition line')
check(render(<StockPlanPanel strategies={[strategy('observation', 2)]} />).includes(NO_CONDITION_TEXT) && render(<StockPlanPanel strategies={undefined} />).includes(NO_CONDITION_TEXT), 'no conditional strategy: no button, one line')

// ---- refusal copy ----
const apiError = (code: string) => Object.assign(new Error(`API 409: {"detail":"${code}"}`), { status: 409, code })
check(addPlanErrorText(apiError('stale_signal')) === '這個研究條件的資料日已過，請用最新資料日的條件建立', 'stale signal copy')
check(addPlanErrorText(apiError('signal_not_conditional')).includes('目前不成立') && addPlanErrorText(new Error('network')) === '加入失敗，請稍後再試', 'other refusals')
check(cancelPlanErrorText(apiError('plan_already_closed')) === '計畫已結束，無法取消' && cancelPlanErrorText(null) === '取消失敗，請稍後再試', 'cancel refusals')
