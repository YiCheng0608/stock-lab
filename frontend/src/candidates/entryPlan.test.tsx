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
import { ENTRY_LEVELS_MISSING_STOCK_TEXT, ENTRY_LEVELS_MISSING_TEXT, ENTRY_UNKNOWN_TYPE_TEXT, entryPlanView, entryText } from './entryPlan'

// Standalone regression module for a candidate's plain-language entry plan (Issue 491; UI_COPY_SPEC §10.2; decision
// 6647568372, review 6648572346): one sentence per entry type with the signal's own levels (the table's numbers), the
// stop as the only exit, no price from strategy_levels (its next-session levels decide a new signal, not this one's
// failure), where it shows (today row, stock page candidate row), the signal day's judgement under
// 「完整條件」, and the stated reason when a price is missing — never a blank, NaN or a guessed number.
const check = (condition: boolean, message: string) => { if (!condition) throw new Error(message) }
const render = (element: ReactElement) => renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}><StaticRouter location="/">{element}</StaticRouter></QueryClientProvider>)
const text = (markup: string) => markup.replace(/<[^>]+>/g, '')
const count = (markup: string, needle: string) => markup.split(needle).length - 1
const withLevels = (item: CandidateItem, levels: Partial<CandidateLevels>): CandidateItem => ({ ...item, levels: { ...item.levels, ...levels } })

const BREAKOUT = '2026/10/16 收盤已突破 161.50 元。規則進場價 161.50 元（T+1 起），停損 157.82 元，目標 167.39 元'
const PULLBACK = '2026/10/16 已拉回到支撐區。規則進場區 13.05～13.35 元（T+1 起），停損 12.75 元，目標 13.92 元'
// Issue 693: the sentence states the rule's prices; no instruction to buy (the rules have no evidence of an edge).
for (const sentence of [BREAKOUT, PULLBACK]) check(!/可進場|明天起|跌破/.test(sentence), `no instruction in 「${sentence}」`)

// ---- AC-1: the sentence = the signal's levels (and the table columns) ----
const breakout = entryPlanView(completeItem())
check(breakout.kind === 'levels' && breakout.type === 'breakout', 'a breakout candidate reads as 突破型 with levels')
check(entryText(breakout.parts) === BREAKOUT, `breakout sentence, got 「${entryText(breakout.parts)}」`)
const pullback = entryPlanView(partialItem())
check(pullback.kind === 'levels' && pullback.type === 'pullback', 'a pullback candidate reads as 回踩型 with levels')
check(entryText(pullback.parts) === PULLBACK, `pullback sentence, got 「${entryText(pullback.parts)}」`)

// The sentence's numbers are the table's columns (進場區, 停損, 目標一) of the same item.
for (const item of [completeItem(), partialItem()]) {
  const view = entryPlanView(item)
  const of = (className: string) => view.parts.filter((part) => part.className === className).map((part) => part.text)
  check(of('level-entry')[0] === `${formatEntryZone(item.levels)} 元`, `${item.instrument.symbol}: entry is the table's 進場區`)
  check(of('level-stop')[0] === `${formatPrice(item.levels.invalid_price)} 元`, `${item.instrument.symbol}: stop is the table's 停損`)
  check(of('level-target')[0] === `${formatPrice(item.levels.target_1)} 元`, `${item.instrument.symbol}: target is the table's 目標一`)
}

// No price comes from strategy_levels: its next-session trigger and zone decide whether tomorrow raises a new signal,
// not whether this one fails (review 6648572346). The fixture's levels row differs from the signal on purpose.
check(breakoutPlan().trigger_price === 164.5 && pullbackPlan().zone_low === 13.1 && pullbackPlan().zone_high === 13.3, 'fixture: the levels row differs from the signal')
const card = render(<EntryPlanCard item={completeItem()} />)
const pullCard = render(<EntryPlanCard item={partialItem()} />)
for (const [label, markup, numbers] of [['breakout', card, ['164.50', '12,346']], ['pullback', pullCard, ['13.10', '13.30', '601', '1,200']]] as const) {
  for (const number of numbers) check(!text(markup).includes(number), `${label}: no strategy_levels number 「${number}」 on the plan`)
  check(!text(markup).includes('訊號不再成立') && !text(markup).includes('下一交易日') && !text(markup).includes('明天依當天資料'), `${label}: no next-session condition or invalidation line`)
}
// The same sentence with or without a levels row: the plan never depends on it.
check(entryText(entryPlanView({ ...completeItem(), entry_plan: null }).parts) === BREAKOUT, 'no levels row: the same sentence')
check(entryText(entryPlanView({ ...completeItem(), entry_plan: { ...breakoutPlan(), trigger_price: 999 } }).parts) === BREAKOUT, 'another trigger: the same sentence')

// Prices carry their level colour (DESIGN_SYSTEM §7 進出點); never the up/down colours.
check(card.includes('<b class="level-entry">161.50 元</b>') && card.includes('<b class="level-stop">157.82 元</b>') && card.includes('<b class="level-target">167.39 元</b>'), 'entry, stop and target classes')
check(card.includes('data-term="breakout_entry"') && text(card).startsWith('突破型'), 'the line starts with the 突破型 glossary term')
check(pullCard.includes('data-term="pullback_entry"'), 'a pullback line starts with the 回踩型 term')
check(!/tone-up|tone-down/.test(card), 'no up/down colours on the entry plan')

// 「完整條件」 is folded: the signal day's judgement of each condition, with its day in the title.
check(card.includes('<details class="details entry-plan-conditions"><summary>完整條件（2026/10/16 判定）</summary>'), 'full conditions are a folded details block named by the signal day')
check(!card.includes('data-condition="eligibility"'), 'eligibility is not listed')
check(card.includes('data-condition="breakout_price" data-condition-state="met"') && text(card).includes('已達成收盤突破前 20 日高點收盤 162.00／前 20 日高點 160.00'), 'price condition: met, with the day\'s close and high')
check(text(card).includes('量比 ≥ 1.20 倍量比 2.88 倍') && text(card).includes('超額報酬 +3.21%'), 'volume and group conditions: the day\'s values')
check(card.includes('data-condition="margin_financing" data-condition-state="not_applicable"') && text(card).includes('非融資標的，融資條件不適用'), 'a non-margin security\'s margin condition says why it does not apply')
check(!render(<EntryPlanCard item={{ ...completeItem(), entry_plan: null }} />).includes('entry-plan-conditions'), 'no levels row: no 完整條件 block')

// ---- the two places: today row (the line under the name, Issue 510) and the stock page ----
const today = render(<CandidatesSection data={listResponse()} loading={false} error={null} />)
check(count(today, 'data-entry-plan="levels"') === 2, 'today: each of two candidates has one plan, at every width')
check(count(text(today), BREAKOUT) === 1 && count(text(today), PULLBACK) === 1, 'today: both sentences, once each')
const rowOf = (markup: string, rank: number) => {
  const from = markup.indexOf(`data-candidate-rank="${rank}"`)
  if (from < 0) return ''
  const next = markup.indexOf('data-candidate-rank=', from + 1)
  return markup.slice(from, next < 0 ? markup.indexOf('</ol>', from) : next)
}
const row1 = rowOf(today, 1)
const dataRow = row1.slice(0, row1.indexOf('<details class="candidate-detail"'))
check(dataRow.indexOf('candidate-row-title') >= 0 && dataRow.indexOf('data-entry-plan') > dataRow.indexOf('candidate-row-title'), 'today row: the plan is the line under the name (Issue 510)')
const detailRow = row1.slice(row1.indexOf('<details class="candidate-detail"'))
check(!detailRow.includes('data-entry-plan') && detailRow.indexOf('entry-plan-conditions') > detailRow.indexOf('class="candidate-detail-folds"'), 'today row: the folded conditions are in the detail\'s folds, no second sentence')
check(/<button[^>]*data-term="support"[^>]*>停損<\/button>/.test(dataRow) && /<button[^>]*data-term="target"[^>]*>目標<\/button>/.test(dataRow), 'the sentence\'s 停損 and 目標 open their glossary terms')

const stockCandidate = { ...completeItem(), trading_date: '2026-10-22' }
const summary = { rank: 1, total_score: 0.83, score_version: 'candidate_score_v5', strategy: 'breakout_v3', llm_note: null }
const stock = render(<StrategyBoardPanel board={board([conditionalBreakout(), observationPullback()], summary)} candidate={stockCandidate} />)
check(count(stock, 'data-entry-plan="levels"') === 1 && text(stock).includes(BREAKOUT.replace('2026/10/16', '2026/10/22')), 'stock page: the candidate row has the plan')
check(stock.indexOf('data-entry-plan') < stock.indexOf('class="candidate-reasons"'), 'stock page: the plan comes before the reasons')
check(stock.indexOf('data-entry-plan') < stock.indexOf('data-strategy-row='), 'stock page: the plan sits in the candidate row above the strategy table')
// On the stock page the missing-levels sentence does not point to the stock page (review suggestion).
const stockMissing = render(<StrategyBoardPanel board={board([conditionalBreakout()], summary)} candidate={withLevels(stockCandidate, { invalid_price: null })} />)
check(text(stockMissing).includes(ENTRY_LEVELS_MISSING_STOCK_TEXT) && !text(stockMissing).includes('請看個股頁的策略總表'), 'stock page: the reason without the pointer to itself')

// ---- AC-2: a missing price shows its reason, never a blank or NaN ----
const reasonOf = (item: CandidateItem) => {
  const markup = render(<EntryPlanCard item={item} />)
  check(!/NaN|undefined|null|Infinity|—/.test(text(markup)), `no blank value in 「${text(markup)}」`)
  const view = entryPlanView(item)
  check(view.kind === 'reason', `a candidate without full signal levels is a reason, got ${view.kind}`)
  check(markup.includes('entry-plan-reason'), 'the reason is marked as such')
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
check(reasonOf({ ...completeItem(), entry_plan: undefined, trading_date: '' }) === ENTRY_LEVELS_MISSING_TEXT, 'a response from before Issue 491 without a date: the reason')
const unknown = entryPlanView(withLevels({ ...completeItem(), entry_plan: { ...breakoutPlan(), entry_type: 'other' } }, { entry_type: 'other' }))
check(unknown.kind === 'reason' && entryText(unknown.parts) === ENTRY_UNKNOWN_TYPE_TEXT && unknown.type === null, 'an unknown entry type has no sentence and no type term')

// ---- today row (decision 6647903049): levels in the sentence -> no level cells; a reason -> the three cells ----
const rowMain = (markup: string, rank: number) => { const row = rowOf(markup, rank); return row.slice(0, row.indexOf('<details class="candidate-detail"')) }
const levelCells = (row: string) => row.indexOf('candidate-row-levels') < 0 ? '' : row.slice(row.indexOf('candidate-row-levels'), row.indexOf('</dl>', row.indexOf('candidate-row-levels')))
for (const rank of [1, 2]) check(levelCells(rowMain(today, rank)) === '', `today row #${rank}: the sentence has the levels, no level cell repeats them`)
const missingLevels = { ...listResponse(), items: [withLevels(completeItem(), { invalid_price: null }), partialItem()] }
const fallback = render(<CandidatesSection data={missingLevels} loading={false} error={null} />)
const fallbackCells = levelCells(rowMain(fallback, 1))
check(text(rowMain(fallback, 1)).includes(ENTRY_LEVELS_MISSING_TEXT), 'today row #1: the sentence states the reason')
check(count(fallbackCells, '<dt>') === 3 && fallbackCells.includes('data-term="entry_zone"') && fallbackCells.includes('data-term="support"') && fallbackCells.includes('data-term="target"'), 'today row #1: without levels in the sentence the three level cells come back')
check(text(fallbackCells).includes('停損（元）—'), 'today row #1: the missing stop reads 「—」')
check(levelCells(rowMain(fallback, 2)) === '', 'today row #2 still has levels in its sentence: no cells')
// The detail keeps the four level cells either way (Issue 510).
check(count(fallback, 'class="candidate-detail-levels"') === 2, 'today detail: the level cells stay for every candidate')
