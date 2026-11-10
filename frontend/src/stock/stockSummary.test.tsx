import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'

import { ActionDetailPanel } from '../App'
import { NO_CONDITION_TEXT } from '../tracking/tracking'
import { StockPlanPanel } from '../tracking/TrackingViews'
import type { ActionSummary, StrategyBoardRow, StrategyDecision } from '../types'
import { StockCutoffControl } from './StockCutoffControl'
import { StockSummaryCard } from './StockSummaryCard'
import { BOARD_NOTE, OBSERVATION_LABEL } from './strategyBoard'
import {
  board,
  conditionalBreakout,
  incompleteRow,
  missingLevelsRow,
  notApplicableRow,
  observationBreakout,
  observationPullback,
  unreachablePullback,
} from './strategyBoard.fixtures'
import { StrategyBoardPanel } from './StrategyBoardPanel'
import { closestStrategy, stockVerdict } from './stockSummary'

// Standalone regression module for the stock page layout of Issue 519 (DESIGN_SYSTEM §4 個股頁頁首與摘要卡, §5 個股摘要卡
// and 策略總表, UI_COPY_SPEC §8.2 摘要卡): the verdict and its reason, the strategy closest to passing with its levels,
// and the research tab folded to its status rows.
const check = (condition: boolean, message: string) => { if (!condition) throw new Error(message) }
const render = (element: ReactElement) => renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}><StaticRouter location="/stocks/TWSE/2884">{element}</StaticRouter></QueryClientProvider>)
const text = (markup: string) => markup.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
const count = (markup: string, needle: string) => markup.split(needle).length - 1
const action = (extra: Partial<ActionSummary> = {}) => ({
  instrument: { id: 1, exchange: 'TWSE', symbol: '2884', name: '玉山金', instrument_type: 'stock', etf_category: null },
  action_state: 'no_condition', display_action: '暫無研究條件', display_instruction: '條件未成立，暫不研究進場。',
  primary_reason: { label: '回踩條件差 1 項：支撐區', scope: 'strategy' }, data_cutoff: '2026-10-22', data_quality: 'complete',
  reasons: [], conflicts: [], strategies: [], blocking_reasons: [], ...extra,
}) as unknown as ActionSummary
const candidateSummary = { rank: 3, total_score: 0.784, score_version: 'candidate_score_v2', strategy: 'pullback_v1' }
const conditionalPullback = (): StrategyBoardRow => ({ ...conditionalBreakout(), strategy: 'pullback_v1', label: '回踩條件', entry_type: 'pullback' })

// ---- the verdict: the first rule that holds (UI_COPY_SPEC §8.2 目前判斷) ----
const buy = stockVerdict(board([observationBreakout(), conditionalPullback()], candidateSummary), action({ action_state: 'conditional_entry' }))
check(buy.label === '條件成立' && buy.tone === 'success' && buy.reason === '每日候選第 3 名 · 總分 78 · 回踩條件', `candidate (Issue 581): 條件成立, not 可買, with its rank, got ${JSON.stringify(buy)}`)
const exit = stockVerdict(board([conditionalBreakout()], candidateSummary), action({ action_state: 'reduce_exit', held: true, display_instruction: '已碰到既定風險條件，重新研究處置。' }))
check(exit.label === '持倉風險' && exit.tone === 'warning' && exit.reason === '已碰到既定風險條件，重新研究處置。', `a holding risk wins over the candidate, got ${JSON.stringify(exit)}`)
const gaps = [{ code: 'listed_under_threshold', label: '上市（櫃）後只有 41 個交易日，未滿 60 個交易日' }, { code: 'official_no_trade', label: '近 60 個交易日有 3 天官方行情無成交' }]
const short = stockVerdict(board([observationBreakout(), incompleteRow()]), action({ action_state: 'data_insufficient', gap_reasons: gaps }))
check(short.label === '資料不足' && short.tone === 'warning' && short.reason === `${gaps[0].label}；${gaps[1].label}`, `data insufficient: the Issue 511 reasons joined by ；, got ${JSON.stringify(short)}`)
const older = stockVerdict(board([incompleteRow()]), action({ action_state: 'data_insufficient', data_gap: '研究資料尚未完整，尚不能計算進場、失效與目標價。' }))
check(older.label === '資料不足' && older.reason.includes('研究資料尚未完整'), `an older response without gap_reasons uses data_gap, got ${JSON.stringify(older)}`)
const etf = stockVerdict(board([notApplicableRow(), { ...notApplicableRow(), strategy: 'pullback_v1' }]), action({ action_state: 'data_insufficient', gap_reasons: [{ code: 'etf_not_general_action_eligible', label: '債券、槓桿或反向 ETF 不適用一般突破／回踩研究條件' }] }))
check(etf.label === '不適用' && etf.tone === 'default' && etf.reason === '債券、槓桿或反向 ETF 不適用一般突破／回踩研究條件', `every row not applicable: 不適用, got ${JSON.stringify(etf)}`)
const passed = stockVerdict(board([conditionalBreakout()]), action({ action_state: 'conditional_entry' }))
check(passed.label === '條件成立' && passed.tone === 'success' && passed.reason === '不在這個資料日的每日候選名單', `conditional, not a candidate, got ${JSON.stringify(passed)}`)
const thinBoard = { ...board([conditionalBreakout()]), liquidity: { average_volume_lots_20d: 32.4, state: 'ok', unit: 'lots' as const, data_as_of: '2026-10-22', minimum_lots: 1000, below_minimum: true, candidate_exclusion: 'low_volume', score_version: 'candidate_score_v6' } }
check(stockVerdict(thinBoard, action({ action_state: 'conditional_entry' })).reason === '20 日均量 32 張，低於 1,000 張門檻，不列候選', 'conditional below the floor: the floor sentence')
const etfAction = action({ action_state: 'conditional_entry', instrument: { id: 2, exchange: 'TWSE', symbol: '0050', name: '元大台灣50', instrument_type: 'etf', etf_category: 'broad_market' } })
check(stockVerdict(board([conditionalBreakout()]), etfAction).reason === 'ETF 不列入候選評分', 'a conditional ETF says ETF is not scored')
const watch = stockVerdict(board([observationBreakout(), observationPullback()]), action())
check(watch.label === '觀察' && watch.tone === 'primary' && watch.reason === '回踩條件差 1 項：支撐區', `observation: the primary reason, got ${JSON.stringify(watch)}`)
const none = stockVerdict(null, null)
check(none.label === '無資料' && none.reason === '尚無行動摘要。', `nothing to judge, got ${JSON.stringify(none)}`)

// ---- the strategy closest to passing ----
check(closestStrategy(board([observationBreakout(), conditionalPullback()], candidateSummary))?.strategy === 'pullback_v1', 'the candidate strategy first')
check(closestStrategy(board([observationPullback(), conditionalBreakout()]))?.strategy === 'breakout_v1', 'then the first conditional row')
check(closestStrategy(board([observationBreakout(), unreachablePullback()]))?.strategy === 'pullback_v1', 'then the observation with the fewest unmet conditions')
check(closestStrategy(board([missingLevelsRow(), observationBreakout()]))?.strategy === 'breakout_v1', 'an observation without condition details goes last')
check(closestStrategy(board([observationBreakout(), { ...observationPullback() }]))?.strategy === 'breakout_v1', 'a tie keeps the declared order')
check(closestStrategy(board([incompleteRow(), notApplicableRow()]))?.status === 'data_incomplete', 'otherwise the first row')
check(closestStrategy(board([])) === null && closestStrategy(null) === null, 'no rows, no strategy')

// ---- the summary card ----
const card = render(<StockSummaryCard board={board([observationBreakout(), conditionalPullback()], candidateSummary)} action={action({ action_state: 'conditional_entry' })} researchHref="?tab=research" />)
for (const label of ['目前判斷', '最接近成立', '規則價位']) check(card.includes(`>${label}<`), `summary card: the ${label} column`)
check(card.indexOf('目前判斷') < card.indexOf('最接近成立') && card.indexOf('最接近成立') < card.indexOf('規則價位'), 'summary card: the three columns in order')
check(card.includes('資料 2026/10/22') && text(card).includes('條件成立 每日候選第 3 名 · 總分 78 · 回踩條件'), `summary card: date, verdict and reason: ${text(card).slice(0, 200)}`)
check(text(card).includes('回踩條件') && text(card).includes('成立') && text(card).includes('差：全部達成'), 'summary card: the closest strategy, its status and 差：全部達成')
check(card.includes('class="level-entry">2,400.00') && card.includes('class="level-stop">2,364.00') && card.includes('class="level-target">2,458.00／2,508.00'), 'summary card: the actionable levels with the level classes')
check(card.includes('href="/stocks/TWSE/2884?tab=research"') && card.includes('完整條件 →'), 'summary card: 完整條件 → opens the research tab')
check(!card.includes('ai-inference') && !card.includes('AI 推論') && !card.includes('<details'), 'summary card: no AI content and nothing folded')
const observed = render(<StockSummaryCard board={board([observationBreakout(), observationPullback()])} action={action()} researchHref="?tab=research" />)
check(observed.includes(OBSERVATION_LABEL) && text(observed).includes('差：收盤未突破前 20 日高點、量比未達 1.20 倍') && observed.includes('61.30'), `summary card: the observation levels stay open under their label: ${text(observed).slice(0, 300)}`)
const shortCard = render(<StockSummaryCard board={board([incompleteRow(), notApplicableRow()])} action={action({ action_state: 'data_insufficient', gap_reasons: gaps })} researchHref="?tab=research" />)
check(shortCard.includes('badge-warning') && text(shortCard).includes(`資料不足 ${gaps[0].label}；${gaps[1].label}`) && text(shortCard).includes('無價位'), 'summary card: data insufficient, its reasons and no levels')
const emptyCard = render(<StockSummaryCard board={board([])} action={null} researchHref="?tab=research" />)
check(text(emptyCard).includes('此股尚無策略判定資料。') && !emptyCard.includes('規則價位'), 'summary card: without strategy rows the two columns are one line')

// ---- the research tab folds to status rows ----
const panel = render(<StrategyBoardPanel board={board([conditionalBreakout(), observationPullback()], { ...candidateSummary, strategy: 'breakout_v1' })} candidate={null} />)
check(/<details class="details board-help"><summary>說明<\/summary><p class="small-note">/.test(panel) && panel.includes(BOARD_NOTE), 'strategy board: the fixed note sits in a 說明 details')
check(!panel.includes('class="eyebrow"'), 'strategy board: no eyebrow')
check(count(panel, `<details class="strategy-observation" data-strategy-levels="levels"><summary class="strategy-observation-label">${OBSERVATION_LABEL}</summary>`) === 2, 'strategy board: each observation block folds behind its label (table row and phone card)')
const missingPanel = render(<StrategyBoardPanel board={board([missingLevelsRow()])} candidate={null} />)
check(missingPanel.includes('data-strategy-levels="missing"') && !missingPanel.includes('<details class="strategy-observation"'), 'strategy board: the missing-levels warning stays open')

// ---- the cutoff form keeps its sentence behind 說明 ----
const cutoff = renderToStaticMarkup(<StockCutoffControl asOf="" effectiveDate="2026-11-03" onApply={() => undefined} />)
check(/<details class="cutoff-help"><summary>說明<\/summary><p class="small-note">只用這一天收盤/.test(cutoff), `cutoff: the meaning sentence is in a 說明 details: ${cutoff.slice(cutoff.indexOf('最新資料</button>'), cutoff.indexOf('最新資料</button>') + 160)}`)

// ---- the tracking rows inside the research-action panel ----
const strategy = (status: string, signalId: number) => ({ strategy: 'breakout_v1', signal_id: signalId, signal_date: '2026-10-16', status, open_plan_id: null }) as unknown as StrategyDecision
const embedded = render(<StockPlanPanel strategies={[strategy('conditional', 1)]} embedded />)
check(embedded.startsWith('<div class="stock-plan-inline"') && !embedded.includes('class="card') && embedded.includes('突破條件成立') && embedded.includes('>加入追蹤</button>'), `tracking rows: no card of their own inside the research-action panel: ${embedded.slice(0, 120)}`)
check(render(<StockPlanPanel strategies={[]} embedded />).includes(NO_CONDITION_TEXT), 'tracking rows: one line without a conditional strategy')

// ---- the research-action panel: the gap causes inside it, each sentence once ----
const gapSentence = '60 日基準還缺 3 個有效交易日，尚不能計算進場、失效與目標價。'
const shortAction = action({ action_state: 'data_insufficient', display_instruction: `目前無法產生研究動作。${gapSentence}`, data_gap: gapSentence, primary_reason: { label: gaps[0].label, scope: 'data' }, gap_reasons: gaps, data_quality: 'partial' })
const actionPanel = render(<ActionDetailPanel action={shortAction} gap={{ reasons: gaps, missingFields: ['bars_60d'] }}><StockPlanPanel strategies={[]} embedded /></ActionDetailPanel>)
check(actionPanel.includes('<h2 id="stock-action-title">研究動作</h2>') && actionPanel.includes('資料不足，無法判斷'), 'research action: the panel title and the action name')
check(text(actionPanel).includes(`目前不能判斷的原因：${gaps[0].label}；${gaps[1].label}。`), 'research action: the gap causes sit inside the panel')
check(count(text(actionPanel), gapSentence) === 1, `research action: the data-gap sentence the instruction carries is not repeated: ${text(actionPanel).slice(0, 400)}`)
check(count(text(actionPanel), gaps[0].label) === 1, 'research action: the primary reason that is a gap cause is not repeated')
check(actionPanel.indexOf('查看風險提醒、時間與價位') < actionPanel.indexOf('class="stock-plan-inline"') && actionPanel.includes(NO_CONDITION_TEXT), 'research action: the tracking rows close the panel')
const ownGap = render(<ActionDetailPanel action={action({ action_state: 'data_insufficient', display_instruction: '目前無法產生研究動作。', data_gap: gapSentence })} />)
check(text(ownGap).includes(gapSentence), 'research action: a data-gap sentence the instruction lacks is still shown')
const watchPanel = render(<ActionDetailPanel action={action()} />)
check(text(watchPanel).includes('暫無研究條件 條件未成立，暫不研究進場。 回踩條件差 1 項：支撐區'), `research action: the name, instruction and primary reason on one line: ${text(watchPanel).slice(0, 200)}`)
