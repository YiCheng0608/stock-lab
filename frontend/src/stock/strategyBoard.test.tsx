import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'

import { CANDIDATE_DISCLAIMER } from '../candidates/candidates'
import { completeItem, doneNote } from '../candidates/candidates.fixtures'
import { GLOSSARY } from '../glossary'
import type { StrategyActionableLevels, StrategyBoardRow } from '../types'
import {
  LEVELS_MISSING_TEXT,
  OBSERVATION_LABEL,
  conditionViews,
  levelsVersionLabel,
  riskRewardShortfallText,
  statusLabel,
  trendUnreachableText,
  unmetText,
} from './strategyBoard'
import {
  board,
  conditionalBreakout,
  incompleteRow,
  missingLevelsRow,
  nonMarginBreakout,
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
check(unmetText(incompleteRow()) === '無法判斷：近 5 日融資變化資料不足', 'incomplete lists what is missing')
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
const incompleteViews = conditionViews(incompleteRow(), (code) => code === 'margin_balance_change_ratio_5d_missing_or_non_finite' ? '近 5 日融資變化資料不足' : code)
check(incompleteViews.find((view) => view.code === 'required_inputs')?.value === '近 5 日融資變化資料不足', 'reasons are translated')
check(incompleteViews.find((view) => view.code === 'margin_financing')?.stateText === '無資料', 'null satisfied is 無資料')

// ---- a non-margin security's margin condition (#392): 不適用, with its reason, never 「—」 or a next-session line ----
const nonMargin = conditionViews(nonMarginBreakout(), (code) => code === 'margin_financing_not_applicable' ? '非融資標的，融資條件不適用' : code)
const marginView = nonMargin.find((view) => view.code === 'margin_financing')
check(marginView?.state === 'not_applicable' && marginView.stateText === '不適用', `not applicable margin badge, got ${marginView?.stateText}`)
check(marginView?.value === '非融資標的，融資條件不適用' && marginView.next === null, `not applicable margin value, got ${marginView?.value}`)
check(!unmetText(nonMarginBreakout()).includes('融資'), 'a not applicable condition is not unmet')
const nonMarginMarkup = render(<StrategyBoardPanel board={board([nonMarginBreakout(), observationPullback()])} candidate={null} />)
const nonMarginRow = nonMarginMarkup.slice(nonMarginMarkup.indexOf('data-condition="margin_financing"'))
check(nonMarginRow.startsWith('data-condition="margin_financing" data-condition-state="not_applicable"') && nonMarginRow.slice(0, 400).includes('不適用'), 'the panel shows 不適用')
const nonMarginText = nonMarginMarkup.replace(/<[^>]*>/g, ' ')
check(!/breakout_v|pullback_v|\bv2\b|2\.0\.0/.test(nonMarginText), 'no strategy code or version on the page text')

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
// #463: two targets are named one by one; RR carries 倍 (UI_COPY_SPEC §10.1).
const actionableText = actionable.replace(/<[^>]+>/g, '')
check(actionableText.includes('目標一／目標二') && !/目標(?!一|二)/.test(actionableText.replace('目標一／目標二', '')), `actionable: 「目標一／目標二」 over the two targets: ${actionableText}`)
check(/>[0-9.]+ 倍</.test(actionable), 'actionable: RR reads 倍')
const observation = tableRow(both, 'pullback_v1')
check(observation.includes('data-strategy-status="observation"') && observation.includes('觀察'), 'observation status')
check(observation.includes(`<summary class="strategy-observation-label">${OBSERVATION_LABEL}</summary>`), 'observation levels sit under the observation label, folded behind it (Issue 519)')
const box = observation.slice(observation.indexOf('class="strategy-observation"'))
for (const text of ['2,430.00～2,535.00', '16,371～32,741 張', '參考停損', '2,399.64', '參考目標一／目標二', '2,478.57／2,521.07', '下一交易日 2026/10/23']) {
  check(box.includes(text), `observation box shows ${text}`)
}
check(!observation.includes('ai-inference'), 'no AI note on a strategy row')
// Only the ranking disclaimer and the 總分 hover hint (UI_COPY_SPEC §7) may name a win rate, to say the score is not one.
const scoreHint = `title="${GLOSSARY.find((term) => term.term_id === 'candidate_score')?.plain_definition}"`
for (const markup of [both.split(CANDIDATE_DISCLAIMER).join('').split(scoreHint).join(''), plainMarkup()]) check(!markup.includes('勝率') && !markup.includes('機率'), 'no win rate or probability')
// Phone: one card per strategy with the same content.
check(count(both, 'class="card strategy-card"') === 2, 'one phone card per strategy')
check(card(both, 'pullback_v1').includes(OBSERVATION_LABEL) && card(both, 'breakout_v1').includes('class="level-stop">2,364.00'), 'cards keep the two kinds of levels apart')
check(count(both, 'strategy-conditions') === 4, 'condition details under each row and each card')

// ---- not a candidate: no candidate row, no AI note ----
const plain = render(<StrategyBoardPanel board={board([observationBreakout(), unreachablePullback()])} candidate={null} />)
check(!plain.includes('data-strategy-candidate') && !plain.includes('ai-inference') && !plain.includes('AI 推論'), 'a non-candidate has no AI note')
const breakoutObservation = tableRow(plain, 'breakout_v1')
check(breakoutObservation.includes('收盤（元） ≥') && breakoutObservation.includes('61.30') && breakoutObservation.includes('成交量 ≥') && breakoutObservation.includes('1,235 張'), 'breakout observation: trigger and minimum lots')
check(breakoutObservation.includes('超出下一交易日漲跌停範圍'), 'an unreachable trigger is said so')
const unreachable = tableRow(plain, 'pullback_v1')
check(unreachable.includes('data-strategy-levels="trend_unreachable"') && unreachable.includes(OBSERVATION_LABEL) && unreachable.includes('收盤需高於 322.00'), 'trend_unreachable: explanation, no price')
check(!unreachable.includes('level-stop') && !unreachable.includes('level-target'), 'trend_unreachable shows no stop or target')

// ---- data incomplete, not applicable, missing levels ----
const gaps = render(<StrategyBoardPanel board={board([incompleteRow(), notApplicableRow(), missingLevelsRow()].map((row, index): StrategyBoardRow => ({ ...row, strategy: `s${index}` })))} candidate={null} />)
const incomplete = tableRow(gaps, 's0')
check(incomplete.includes('data-strategy-status="data_incomplete"') && incomplete.includes('資料不足') && incomplete.includes('badge-warning'), 'data incomplete: warning badge')
check(incomplete.includes('無法判斷：近 5 日融資變化資料不足') && incomplete.includes('無價位') && !incomplete.includes('level-'), 'data incomplete: missing items and no levels')
const notApplicable = tableRow(gaps, 's1')
check(notApplicable.includes('data-strategy-status="not_applicable"') && notApplicable.includes('不適用') && !notApplicable.includes('badge-warning') && notApplicable.includes('無價位'), 'not applicable: muted badge, no levels')
const missing = tableRow(gaps, 's2')
check(missing.includes('data-strategy-levels="missing"') && missing.includes(LEVELS_MISSING_TEXT) && !missing.includes('level-'), 'missing levels row says so and fills nothing')

// ---- no board, no signals ----
check(render(<StrategyBoardPanel board={null} candidate={null} />) === '', 'no board renders nothing')
check(render(<StrategyBoardPanel board={{ ...board([]), as_of: null }} candidate={null} />).includes('此股尚無策略判定資料。'), 'a stock without signals says so')

// ---- liquidity floor (#490): 20-session lots on the board, the floor note next to every 成立 ----
const thinBoard = {
  ...board([conditionalBreakout(), observationPullback()]),
  liquidity: { average_volume_lots_20d: 32.4, state: 'ok', unit: 'lots' as const, data_as_of: '2026-10-22', minimum_lots: 1000, below_minimum: true, candidate_exclusion: 'low_volume', score_version: 'candidate_score_v6' },
}
const thin = render(<StrategyBoardPanel board={thinBoard} candidate={null} />)
check(thin.includes('20 日均量 32 張 · 資料日期 2026/10/22（候選門檻 1,000 張）'), 'the board shows the 20-session lots, date and floor')
const floorNote = '20 日均量 32 張，低於 1,000 張門檻，不列候選'
check(tableRow(thin, 'breakout_v1').includes(floorNote) && card(thin, 'breakout_v1').includes(floorNote), 'the 成立 row and card carry the floor note')
check(!tableRow(thin, 'pullback_v1').includes(floorNote), 'an observation row has no floor note')
const liquid = render(<StrategyBoardPanel board={{ ...thinBoard, liquidity: { ...thinBoard.liquidity, average_volume_lots_20d: 1682, below_minimum: false, candidate_exclusion: null } }} candidate={null} />)
check(liquid.includes('20 日均量 1,682 張') && !liquid.includes('不列候選'), 'a liquid stock shows its lots and no note')
const before = render(<StrategyBoardPanel board={{ ...thinBoard, liquidity: { ...thinBoard.liquidity, minimum_lots: null, candidate_exclusion: null } }} candidate={null} />)
check(before.includes('20 日均量 32 張') && !before.includes('候選門檻') && !before.includes('不列候選'), 'a day scored without the floor shows no floor')

// ---- RR basis and the RR shortfall (#580; UI_COPY_SPEC §10.1) ----
const based = conditionalBreakout()
based.levels = { ...(based.levels as StrategyActionableLevels), risk_reward_basis: 'entry_price' }
const basedMarkup = render(<StrategyBoardPanel board={board([based])} candidate={null} />)
check(tableRow(basedMarkup, 'breakout_v1').includes('1.60 倍') && tableRow(basedMarkup, 'breakout_v1').includes('（以進場價 2,400.00 元計算）'), 'the 成立 RR names its basis and price')
check(!render(<StrategyBoardPanel board={board([conditionalBreakout()])} candidate={null} />).includes('strategy-rr-basis'), 'no basis, no note')
const shortfall: StrategyBoardRow = {
  ...observationPullback(), strategy: 'pullback_v4', unmet: [],
  risk_reward_shortfall: { risk_reward: 0.6718, minimum: 1.5, risk_reward_basis: 'entry_zone_midpoint', entry: 27.27, errors: ['target_1_risk_reward_below_minimum'] },
}
const shortfallText = '條件全部達成，但以進場區中點計算的 RR 0.67 倍未達 1.5 倍'
check(unmetText(shortfall) === shortfallText, `the shortfall sentence, got ${unmetText(shortfall)}`)
check(riskRewardShortfallText({ ...shortfall, risk_reward_shortfall: { ...shortfall.risk_reward_shortfall!, risk_reward: null, errors: ['target_1_must_exceed_entry'] } }) === '條件全部達成，但進場區中點不在停損與目標一之間，RR 未達 1.5 倍', 'no RR to state')
check(riskRewardShortfallText({ ...shortfall, risk_reward_shortfall: { ...shortfall.risk_reward_shortfall!, risk_reward_basis: null } }) === '條件全部達成，但 RR 0.67 倍未達 1.5 倍', 'an unknown basis drops its words')
check(riskRewardShortfallText(observationPullback()) === null, 'an ordinary observation has no shortfall')
const shortfallMarkup = render(<StrategyBoardPanel board={board([conditionalBreakout(), shortfall])} candidate={null} />)
check(tableRow(shortfallMarkup, 'pullback_v4').includes(shortfallText) && card(shortfallMarkup, 'pullback_v4').includes(shortfallText), 'the row and the card state the RR')
check(tableRow(shortfallMarkup, 'pullback_v4').includes('觀察'), 'the shortfall row reads as an observation')
