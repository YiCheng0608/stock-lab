import type { ReactElement } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'

import { board, conditionalBreakout, observationPullback } from '../stock/strategyBoard.fixtures'
import { StrategyBoardPanel } from '../stock/StrategyBoardPanel'
import type { CandidateItem, CandidateLevels } from '../types'
import { formatEntryZone, formatPrice } from './candidates'
import { breakoutPlan, completeItem, listResponse, partialItem, pullbackPlan } from './candidates.fixtures'
import { CandidatesSection } from './CandidateViews'
import { EntryPlanCard } from './EntryPlanCard'
import { ENTRY_LEVELS_MISSING_TEXT, ENTRY_UNKNOWN_TYPE_TEXT, entryPlanView, entryText } from './entryPlan'

// Standalone regression module for a candidate's plain-language entry plan (Issue 491; UI_COPY_SPEC §10.2; decision
// 6647568372): the main sentence per entry type with the signal's own levels (the table's numbers), the small
// reminder with the strategy_levels prices, where it shows (today table and phone card, stock page candidate row),
// and the stated reason when a price is missing — never a blank, NaN or a guessed number.
const check = (condition: boolean, message: string) => { if (!condition) throw new Error(message) }
const render = (element: ReactElement) => renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}><StaticRouter location="/">{element}</StaticRouter></QueryClientProvider>)
const text = (markup: string) => markup.replace(/<[^>]+>/g, '')
const count = (markup: string, needle: string) => markup.split(needle).length - 1
const withLevels = (item: CandidateItem, levels: Partial<CandidateLevels>): CandidateItem => ({ ...item, levels: { ...item.levels, ...levels } })

const BREAKOUT = '2026/10/16 收盤已突破 161.50 元。明天起在 161.50 元附近可進場；跌破 157.82 元停損，目標 167.39 元'
const BREAKOUT_HOLDS = '明天收盤若跌回 164.50 元以下，訊號不再成立。'
const PULLBACK = '2026/10/16 已拉回到支撐區。明天起在 13.05～13.35 元之間可進場；跌破 12.75 元停損，目標 13.92 元'
const PULLBACK_HOLDS = '明天收盤若收在 13.10～13.30 元以外，訊號不再成立。'

// ---- AC-1: main sentence = the signal's levels (and the table columns); reminder = strategy_levels ----
const breakout = entryPlanView(completeItem())
check(breakout.kind === 'levels' && breakout.type === 'breakout', 'a breakout candidate reads as 突破型 with levels')
check(entryText(breakout.parts) === BREAKOUT, `breakout sentence, got 「${entryText(breakout.parts)}」`)
check(entryText(breakout.holds) === BREAKOUT_HOLDS, `breakout reminder, got 「${entryText(breakout.holds)}」`)
const pullback = entryPlanView(partialItem())
check(pullback.kind === 'levels' && pullback.type === 'pullback', 'a pullback candidate reads as 回踩型 with levels')
check(entryText(pullback.parts) === PULLBACK, `pullback sentence, got 「${entryText(pullback.parts)}」`)
check(entryText(pullback.holds) === PULLBACK_HOLDS, `pullback reminder, got 「${entryText(pullback.holds)}」`)

// The main sentence's numbers are the table's columns (進場區, 停損, 目標一) of the same item.
for (const item of [completeItem(), partialItem()]) {
  const view = entryPlanView(item)
  const of = (className: string) => view.parts.filter((part) => part.className === className).map((part) => part.text)
  check(of('level-entry')[0] === `${formatEntryZone(item.levels)} 元`, `${item.instrument.symbol}: entry is the table's 進場區`)
  check(of('level-stop')[0] === `${formatPrice(item.levels.invalid_price)} 元`, `${item.instrument.symbol}: stop is the table's 停損`)
  check(of('level-target')[0] === `${formatPrice(item.levels.target_1)} 元`, `${item.instrument.symbol}: target is the table's 目標一`)
}
// The reminder's numbers are strategy_levels', not the signal's.
check(breakoutPlan().trigger_price === 164.5 && completeItem().levels.entry === 161.5, 'fixture: trigger and signal entry differ')
check(pullbackPlan().zone_low === 13.1 && partialItem().levels.entry_zone.low === 13.05, 'fixture: zone and entry zone differ')

// Prices carry their level colour (DESIGN_SYSTEM §7 進出點); never the up/down colours.
const card = render(<EntryPlanCard item={completeItem()} />)
check(card.includes('<b class="level-entry">161.50 元</b>') && card.includes('<b class="level-stop">157.82 元</b>') && card.includes('<b class="level-target">167.39 元</b>'), 'entry, stop and target classes')
check(card.includes('data-term="breakout_entry"') && text(card).startsWith('突破型'), 'the line starts with the 突破型 glossary term')
check(render(<EntryPlanCard item={partialItem()} />).includes('data-term="pullback_entry"'), 'a pullback line starts with the 回踩型 term')
check(card.includes('<p class="small-note entry-plan-holds" data-entry-holds="">'), 'the reminder is small text')
check(!/tone-up|tone-down/.test(card), 'no up/down colours on the entry plan')

// The full conditions are folded under 「完整條件」: what each condition needs tomorrow.
check(card.includes('<details class="details entry-plan-conditions"><summary>完整條件</summary>'), 'full conditions are a folded details block')
check(!card.includes('data-condition="eligibility"'), 'eligibility is not a condition for tomorrow')
check(card.includes('下一交易日收盤 ≥ 164.50（距最近收盤 +1.54%）') && card.includes('下一交易日成交量 ≥ 12,346 張'), 'price and volume conditions say tomorrow\'s bound (minimum volume rounds up)')
check(text(card).includes('明天依當天資料重新判定（最近 超額報酬 +3.21%）'), 'a confirmation condition is judged again on tomorrow\'s data')
check(text(card).includes('非融資標的，融資條件不適用'), 'a non-margin security\'s margin condition says why it does not apply')

// ---- the two places: today table (the line under each row) and phone card (first line under the name), stock page ----
const today = render(<CandidatesSection data={listResponse()} loading={false} error={null} />)
check(count(today, 'data-entry-plan="levels"') === 4, 'today: each of two candidates has a plan in the table and in its phone card')
check(count(text(today), BREAKOUT) === 2 && count(text(today), PULLBACK) === 2, 'today: both sentences in the table and the cards')
const detailRow = today.slice(today.indexOf('data-candidate-detail="1"'))
check(detailRow.indexOf('data-entry-plan') < detailRow.indexOf('class="candidate-detail"'), 'today table: the plan is the line under the row, above the folded AI detail')
const phone = today.slice(today.indexOf('data-candidate-card="1"'))
check(phone.indexOf('candidate-mini-head') < phone.indexOf('data-entry-plan') && phone.indexOf('data-entry-plan') < phone.indexOf('candidate-mini-levels'), 'phone card: the plan is the first line under the name')

const stockCandidate = { ...completeItem(), trading_date: '2026-10-22' }
const summary = { rank: 1, total_score: 0.83, score_version: 'candidate_score_v5', strategy: 'breakout_v3', llm_note: null }
const stock = render(<StrategyBoardPanel board={board([conditionalBreakout(), observationPullback()], summary)} candidate={stockCandidate} />)
check(count(stock, 'data-entry-plan="levels"') === 1 && text(stock).includes(BREAKOUT.replace('2026/10/16', '2026/10/22')), 'stock page: the candidate row has the plan')
check(stock.indexOf('data-entry-plan') < stock.indexOf('class="candidate-reasons"'), 'stock page: the plan comes before the reasons')
check(stock.indexOf('data-entry-plan') < stock.indexOf('data-strategy-row='), 'stock page: the plan sits in the candidate row above the strategy table')

// ---- AC-2: a missing price shows its reason, never a blank or NaN ----
const noBlank = (item: CandidateItem) => {
  const markup = text(render(<EntryPlanCard item={item} />))
  check(!/NaN|undefined|null|Infinity|—/.test(markup), `no blank value in 「${markup}」`)
  return entryPlanView(item)
}
const reasonOf = (item: CandidateItem) => {
  const view = noBlank(item)
  check(view.kind === 'reason' && view.holds === null, `a candidate without full signal levels is a reason, got ${view.kind}`)
  check(render(<EntryPlanCard item={item} />).includes('entry-plan-reason'), 'the reason is marked as such')
  return entryText(view.parts)
}
check(reasonOf(withLevels(completeItem(), { entry: null, entry_zone: { low: null, high: null } })) === ENTRY_LEVELS_MISSING_TEXT, 'no breakout entry: the reason')
check(reasonOf(withLevels(completeItem(), { entry: Number.NaN })) === ENTRY_LEVELS_MISSING_TEXT, 'a NaN entry is not shown')
check(reasonOf(withLevels(completeItem(), { invalid_price: null })) === ENTRY_LEVELS_MISSING_TEXT, 'no stop: the reason')
check(reasonOf(withLevels(completeItem(), { target_1: null })) === ENTRY_LEVELS_MISSING_TEXT, 'no target: the reason')
check(reasonOf(withLevels(completeItem(), { invalid_price: 170 })) === ENTRY_LEVELS_MISSING_TEXT, 'a stop above the entry is not shown')
check(reasonOf(withLevels(partialItem(), { entry_zone: { low: 13.5, high: 13.35 } })) === ENTRY_LEVELS_MISSING_TEXT, 'an inverted zone is not shown')
check(reasonOf(withLevels(partialItem(), { entry_zone: { low: 13.05, high: null } })) === ENTRY_LEVELS_MISSING_TEXT, 'a zone without its high is not shown')
check(reasonOf({ ...completeItem(), trading_date: '' }) === ENTRY_LEVELS_MISSING_TEXT, 'no data date: the reason')
const unknown = entryPlanView(withLevels({ ...completeItem(), entry_plan: { ...breakoutPlan(), entry_type: 'other' } }, { entry_type: 'other' }))
check(unknown.kind === 'reason' && entryText(unknown.parts) === ENTRY_UNKNOWN_TYPE_TEXT && unknown.type === null, 'an unknown entry type has no sentence and no type term')

// The reminder needs a complete strategy_levels row; otherwise it is left out, never guessed.
for (const [label, item] of [
  ['no row', { ...completeItem(), entry_plan: null }],
  ['a response from before Issue 491', { ...completeItem(), entry_plan: undefined }],
  ['trend_unreachable', { ...partialItem(), entry_plan: { ...pullbackPlan(), availability: 'trend_unreachable', zone_low: null, zone_high: null } }],
  ['suspended', { ...completeItem(), entry_plan: { ...breakoutPlan(), availability: 'suspended', trigger_price: null } }],
  ['a NaN trigger', { ...completeItem(), entry_plan: { ...breakoutPlan(), trigger_price: Number.NaN } }],
  ['an inverted zone', { ...partialItem(), entry_plan: { ...pullbackPlan(), zone_low: 13.4, zone_high: 13.3 } }],
] as const) {
  const view = noBlank(item as CandidateItem)
  check(view.kind === 'levels' && view.holds === null, `${label}: the main sentence stays and the reminder is omitted`)
  check(!render(<EntryPlanCard item={item as CandidateItem} />).includes('data-entry-holds'), `${label}: no reminder line`)
}
check(entryPlanView({ ...completeItem(), entry_plan: null }).conditions.length === 0, 'no row: no 完整條件 block')
