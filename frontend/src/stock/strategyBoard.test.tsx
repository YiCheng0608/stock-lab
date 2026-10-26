import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'

import { CANDIDATE_DISCLAIMER } from '../candidates/candidates'
import { completeItem, doneNote } from '../candidates/candidates.fixtures'
import type { StrategyBoardRow } from '../types'
import {
  LEVELS_MISSING_TEXT,
  OBSERVATION_LABEL,
  conditionViews,
  levelsVersionLabel,
  statusLabel,
  trendUnreachableText,
  unmetText,
} from './strategyBoard'
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

// Standalone regression module for the stock strategy board (#274): the four statuses, actionable and observation
// levels kept apart, the AI note only on the candidate row, and whole-lot volumes (UI_COPY_SPEC §8.3).
const check = (condition: boolean, message: string) => { if (!condition) throw new Error(message) }
const render = (element: ReactElement) => renderToStaticMarkup(<StaticRouter location="/">{element}</StaticRouter>)
const count = (markup: string, needle: string) => markup.split(needle).length - 1
// One strategy's desktop row, or its phone card.
const tableRow = (markup: string, key: string) => {
  const from = markup.indexOf(`data-strategy-row="${key}"`)
  return from < 0 ? '' : markup.slice(from, markup.indexOf('</tr>', from))
}
const card = (markup: string, key: string) => {
  const from = markup.indexOf(`data-strategy-card="${key}"`)
  return from < 0 ? '' : markup.slice(from, markup.indexOf('</article>', from))
}
const noReason = (code: string) => code
const plainMarkup = () => render(<StrategyBoardPanel board={board([observationBreakout(), unreachablePullback()])} candidate={null} />)

// ---- copy helpers ----
check(statusLabel('conditional') === '成立' && statusLabel('observation') === '觀察' && statusLabel('data_incomplete') === '資料不足' && statusLabel('not_applicable') === '不適用', 'four status labels')
check(statusLabel('active') === '狀態待核實', 'an unknown status is not passed through')
check(levelsVersionLabel('strategy_levels_v1') === '價位規則 v1', 'levels version label')
check(unmetText(conditionalBreakout()) === '全部達成', 'conditional: every condition met')
check(unmetText(observationPullback()) === '收盤不在支撐區、量比不在 0.60～1.20 倍', `observation lists the unmet conditions, got ${unmetText(observationPullback())}`)
check(unmetText(incompleteRow()) === '缺：近 5 日融資變化資料待補', 'incomplete lists what is missing')
check(unmetText(notApplicableRow()) === '債券、槓桿或反向 ETF 不適用一般突破／回踩研究條件', 'not applicable says why')
check(unmetText(missingLevelsRow()) === '條件明細未產生', 'a missing levels row is not filled')
check(trendUnreachableText(unreachablePullback()).includes('收盤需高於 322.00') && trendUnreachableText(unreachablePullback()).includes('支撐區上緣只有 253.00'), 'trend_unreachable shows both numbers')
// Rule bounds come from the API's threshold and operator, not from copy (review L3).
const labels = Object.fromEntries(conditionViews(observationPullback(), noReason).map((view) => [view.code, view.label]))
check(labels.pullback_volume === '量比 0.60～1.20 倍' && labels.pullback_history === '日線滿 60 日', `pullback bounds from thresholds, got ${labels.pullback_volume} / ${labels.pullback_history}`)
check(labels.group_relative_strength === '族群 20 日超額報酬 > 0.00%' && labels.institutional_flow === '法人 5 日淨額 ÷ 20 日均量 ≥ -0.30%' && labels.margin_financing === '融資 5 日變動 ≤ 5.00%', `confirmation bounds from thresholds, got ${labels.institutional_flow}`)
const raised = observationBreakout()
raised.conditions = raised.conditions.map((item) => item.code === 'breakout_volume' ? { ...item, threshold: 1.25 } : item)
check(conditionViews(raised, noReason).find((view) => view.code === 'breakout_volume')?.label === '量比 ≥ 1.25 倍', 'a new threshold shows as the API sends it')
check(unmetText(raised) === '收盤未突破前 20 日高點、量比未達 1.25 倍', `unmet copy follows the threshold, got ${unmetText(raised)}`)
const unbounded = observationBreakout()
unbounded.conditions = unbounded.conditions.map((item) => item.code === 'breakout_volume' ? { ...item, threshold: null } : item)
check(conditionViews(unbounded, noReason).find((view) => view.code === 'breakout_volume')?.label === '量比 達規則門檻', 'no threshold: no invented number')
// Volume bounds never look looser than the rule's shares (review L2): a minimum rounds up, a maximum down.
const edge = observationBreakout()
edge.levels = { ...(edge.levels as Extract<StrategyBoardRow['levels'], { kind: 'observation' }>), min_volume: 15110400 }
check(render(<StrategyBoardPanel board={board([edge])} candidate={null} />).includes('15,111 張'), '15,110,400 shares is at least 15,111 lots')
const range = observationPullback()
range.levels = { ...(range.levels as Extract<StrategyBoardRow['levels'], { kind: 'observation' }>), min_volume: 15110000, max_volume: 15110900 }
check(render(<StrategyBoardPanel board={board([range])} candidate={null} />).includes('15,110～15,110 張'), 'an exact minimum stays and a maximum rounds down')
const views = conditionViews(observationPullback(), noReason)
const volume = views.find((view) => view.code === 'pullback_volume')
check(volume?.state === 'unmet' && volume.stateText === '未達成' && volume.next === '下一交易日成交量 16,371～32,741 張', `volume range in whole lots, got ${volume?.next}`)
check(views.find((view) => view.code === 'pullback_trend')?.next === null, 'a met condition has no next-session line')
const zone = views.find((view) => view.code === 'pullback_support_zone')
check(zone?.next === '下一交易日收盤 2,430.00～2,535.00（距最近收盤 -1.55%）', `support zone next session, got ${zone?.next}`)
const incompleteViews = conditionViews(incompleteRow(), (code) => code === 'margin_balance_change_ratio_5d_missing_or_non_finite' ? '近 5 日融資變化資料待補' : code)
check(incompleteViews.find((view) => view.code === 'required_inputs')?.value === '近 5 日融資變化資料待補', 'reasons are translated')
check(incompleteViews.find((view) => view.code === 'margin_financing')?.stateText === '無資料', 'null satisfied is 無資料')

// ---- a candidate with a conditional breakout and an observation pullback ----
const candidate = { ...completeItem(), trading_date: '2026-10-22', llm_note: doneNote() }
const summary = { rank: 3, total_score: 0.784, score_version: 'candidate_score_v2', strategy: 'breakout_v1', llm_note: doneNote() }
const both = render(<StrategyBoardPanel board={board([conditionalBreakout(), observationPullback()], summary)} candidate={candidate} />)
check(both.includes('策略總表') && both.includes('資料 2026/10/22') && both.includes('價位規則 v1'), 'title, data date and levels version')
check(both.includes('data-strategy-candidate="3"') && both.includes('第 3 名'), 'candidate row with rank')
check(both.includes(`<span class="small-note strategy-candidate-disclaimer">${CANDIDATE_DISCLAIMER}</span>`), 'the ranking disclaimer sits beside the score')
check(/第 3 名 · .*總分.* 78 · 突破條件/.test(both), 'candidate row: rank, score and strategy')
check(count(both, 'class="ai-inference candidate-note"') === 1 && both.includes('AI 推論'), 'the AI note appears once, on the candidate row')
check(both.indexOf('data-strategy-candidate') < both.indexOf('data-strategy-row="breakout_v1"'), 'the candidate row is above the strategy rows')
const actionable = tableRow(both, 'breakout_v1')
check(actionable.includes('data-strategy-status="conditional"') && actionable.includes('成立') && actionable.includes('最早執行日 2026/10/23'), 'conditional row with T+1')
check(actionable.includes('class="level-entry">2,400.00') && actionable.includes('class="level-stop">2,364.00') && actionable.includes('class="level-target">2,458.00／2,508.00'), 'actionable levels carry the level classes')
check(!actionable.includes(OBSERVATION_LABEL) && !actionable.includes('strategy-observation'), 'actionable levels are not in an observation block')
const observation = tableRow(both, 'pullback_v1')
check(observation.includes('data-strategy-status="observation"') && observation.includes('觀察'), 'observation status')
check(observation.includes(`<div class="strategy-observation-label">${OBSERVATION_LABEL}</div>`), 'observation levels sit under the observation label')
const box = observation.slice(observation.indexOf('class="strategy-observation"'))
for (const text of ['2,430.00～2,535.00', '16,371～32,741 張', '參考停損', '2,399.64', '參考目標', '2,478.57／2,521.07', '下一交易日 2026/10/23']) {
  check(box.includes(text), `observation box shows ${text}`)
}
check(!observation.includes('ai-inference'), 'no AI note on a strategy row')
// Only the ranking disclaimer may name a win rate, to say the score is not one.
for (const markup of [both.split(CANDIDATE_DISCLAIMER).join(''), plainMarkup()]) check(!markup.includes('勝率') && !markup.includes('機率'), 'no win rate or probability')
// Phone: one card per strategy with the same content.
check(count(both, 'class="card strategy-card"') === 2, 'one phone card per strategy')
check(card(both, 'pullback_v1').includes(OBSERVATION_LABEL) && card(both, 'breakout_v1').includes('class="level-stop">2,364.00'), 'cards keep the two kinds of levels apart')
check(count(both, 'strategy-conditions') === 4, 'condition details under each row and each card')

// ---- not a candidate: no candidate row, no AI note ----
const plain = render(<StrategyBoardPanel board={board([observationBreakout(), unreachablePullback()])} candidate={null} />)
check(!plain.includes('data-strategy-candidate') && !plain.includes('ai-inference') && !plain.includes('AI 推論'), 'a non-candidate has no AI note')
const breakoutObservation = tableRow(plain, 'breakout_v1')
check(breakoutObservation.includes('收盤 ≥') && breakoutObservation.includes('61.30') && breakoutObservation.includes('成交量 ≥') && breakoutObservation.includes('1,235 張'), 'breakout observation: trigger and minimum lots')
check(breakoutObservation.includes('超出下一交易日漲跌停範圍'), 'an unreachable trigger is said so')
const unreachable = tableRow(plain, 'pullback_v1')
check(unreachable.includes('data-strategy-levels="trend_unreachable"') && unreachable.includes(OBSERVATION_LABEL) && unreachable.includes('收盤需高於 322.00'), 'trend_unreachable: explanation, no price')
check(!unreachable.includes('level-stop') && !unreachable.includes('level-target'), 'trend_unreachable shows no stop or target')

// ---- data incomplete, not applicable, missing levels ----
const gaps = render(<StrategyBoardPanel board={board([incompleteRow(), notApplicableRow(), missingLevelsRow()].map((row, index): StrategyBoardRow => ({ ...row, strategy: `s${index}` })))} candidate={null} />)
const incomplete = tableRow(gaps, 's0')
check(incomplete.includes('data-strategy-status="data_incomplete"') && incomplete.includes('資料不足') && incomplete.includes('badge-warning'), 'data incomplete: warning badge')
check(incomplete.includes('缺：近 5 日融資變化資料待補') && incomplete.includes('無價位') && !incomplete.includes('level-'), 'data incomplete: missing items and no levels')
const notApplicable = tableRow(gaps, 's1')
check(notApplicable.includes('data-strategy-status="not_applicable"') && notApplicable.includes('不適用') && !notApplicable.includes('badge-warning') && notApplicable.includes('無價位'), 'not applicable: muted badge, no levels')
const missing = tableRow(gaps, 's2')
check(missing.includes('data-strategy-levels="missing"') && missing.includes(LEVELS_MISSING_TEXT) && !missing.includes('level-'), 'missing levels row says so and fills nothing')

// ---- no board, no signals ----
check(render(<StrategyBoardPanel board={null} candidate={null} />) === '', 'no board renders nothing')
check(render(<StrategyBoardPanel board={{ ...board([]), as_of: null }} candidate={null} />).includes('此股尚無策略判定資料。'), 'a stock without signals says so')
