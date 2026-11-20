import type { ReactElement } from 'react'
import type { CandidateItem, CandidateLiquidity, H2Item, H2Response, MainstreamItem, MainstreamResponse, PreopenNews } from '../types'
import { QueryClient, QueryClientProvider, QueryObserver } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'

import {
  NOTE_DISCLAIMER,
  NOTE_MISSING_TEXT,
  NOTE_PENDING_TEXT,
  NOT_COMPUTED_TEXT,
  averageVolumeText,
  PARTIAL_NOTE,
  candidateGroupState,
  candidateGroupText,
  candidateNoteMeta,
  candidateNoteView,
  candidateSourceText,
  candidateStrategyLabel,
  candidatesPath,
  candidatesState,
  formatCandidateScore,
  formatEntryZone,
  formatLots,
  formatRiskRewardWithBasis,
  riskRewardBasisNote,
  liquidityExclusionText,
  formatSubItemValue,
  marketSourceLabel,
} from './candidates'
import { SOX_GROUP_ID, completeItem, doneNote, listResponse, noPreopenNews, notComputedResponse, overnightUs, partialItem, preopenChecked, preopenNews, preopenNotChecked, zeroResponse } from './candidates.fixtures'
import { PREOPEN_NOT_CHECKED, preopenCheckLine, preopenRowMark } from './candidates'
import { OVERNIGHT_US_CLOSED, OVERNIGHT_US_PENDING, overnightUsView } from './candidates'
import { PageDateContext } from '../components/pageDate'
import { removedCopyIn } from '../removedCopy.fixtures'
import { CandidatesSection, PriceLadder, ScoreDetails, Sparkline, TodayCandidateList } from './CandidateViews'
import { MainstreamList, MainstreamSection, TodayListsSection, mainstreamQueryOptions } from './MainstreamViews'
import { TODAY_LISTS, mainstreamGroupsText, mainstreamReturnText, mainstreamState, signedPercent, todayListKind, todayListMark, todayListPickPath, todayListSearch } from './mainstream'
import { mainstreamItem, mainstreamResponse, missingMainstream, zeroMainstream } from './mainstream.fixtures'
import { H2List, H2Section, h2QueryOptions } from './H2Views'
import { h2Definition, h2GapText, h2State } from './h2'
import { h2Response, missingH2, zeroH2 } from './h2.fixtures'
import { ROW_CLICK_IGNORED, SPARKLINE_HEIGHT, SPARKLINE_WIDTH, TERMINAL_MIN_WIDTH, candidateChartLevels, chartToggleLabel, ladderLabel, nextChartRank, priceLadder, rowClickToggles, sparkline } from './candidates'
// scripts/ci-test.cjs runs this module under Node (the frontend ships no Node typings): the stylesheet check reads a file.
declare const require: (id: string) => unknown
declare const __dirname: string

// Standalone regression module (no browser, no server, no network) for the daily candidate list (#215):
// the detail content under each today row (components, reasons, AI note), partial components, the score details
// the stock page shows, and zero and not-computed runs.
// The today list (one list at every width, Issue 510) is checked in today/today.test.tsx.
const check = (condition: boolean, message: string) => { if (!condition) throw new Error(message) }
// The "加入追蹤" button (#253) reads the query client.
const render = (element: ReactElement) => renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}><StaticRouter location="/">{element}</StaticRouter></QueryClientProvider>)
const count = (markup: string, needle: string) => markup.split(needle).length - 1
const slice = (markup: string, start: string, end: string) => {
  const from = markup.indexOf(start)
  return from < 0 ? '' : markup.slice(from, markup.indexOf(end, from + start.length))
}
// One today row (Issue 510): from its data-candidate-rank to the next row; its detail is the <details> inside it.
const rowOf = (markup: string, rank: number) => {
  const from = markup.indexOf(`data-candidate-rank="${rank}"`)
  if (from < 0) return ''
  const next = markup.indexOf('data-candidate-rank=', from + 1)
  return markup.slice(from, next < 0 ? markup.indexOf('</ol>', from) : next)
}
const detailOf = (row: string) => row.slice(row.indexOf('<details class="candidate-detail"'))

// ---- request parameters ----
check(candidatesPath() === '/candidates', 'no date asks for the latest run')
check(candidatesPath('2026-10-16', 10) === '/candidates?date=2026-10-16&limit=10', 'date and limit are passed through')

// ---- formatting ----
check(formatCandidateScore(0.827566) === '83' && formatCandidateScore(0) === '0' && formatCandidateScore(null) === '—', 'scores on 0–100, null is 「—」 never 0')
check(formatEntryZone(completeItem().levels) === '161.50', 'breakout entry zone collapses to one price')
check(formatEntryZone(partialItem().levels) === '13.05～13.35', 'pullback entry zone shows low～high')
check(formatSubItemValue('margin_change_5d', -0.0592) === '-5.9%' && formatSubItemValue('volume_ratio', 2.8847) === '2.88 倍', 'sub-item units')
check(formatSubItemValue('net_direction', null) === '—', 'null sub-item is 「—」')
// Every strategy version reads the same, without its version suffix (#392, #404).
for (const version of ['v1', 'v2', 'v3']) {
  check(candidateStrategyLabel(`breakout_${version}`) === '突破條件', `breakout_${version} reads 突破條件`)
  check(candidateStrategyLabel(`pullback_${version}`) === '回踩條件', `pullback_${version} reads 回踩條件`)
}
check(marketSourceLabel('tpex_3insti+tpex_margin') === '證券櫃檯買賣中心' && marketSourceLabel(null) === '來源未提供', 'market sources are named')
check(candidateGroupText(completeItem().groups[0]) === 'AI 伺服器（題材，第 2 名／11）', 'ranked group shows board and rank')
check(candidateGroupText(completeItem().groups[1]) === '電腦及週邊（產業，當日未排名）', 'unranked group says so')
// #453: a partial group is ranked on /themes but not used by the score; it is never called unranked.
const pendingGroup = { ...completeItem().groups[0], group_id: 'official-industry-shipping', name: '航運', board: 'industry', qualified: false, rank: null, board_size: null, board_percentile: null, data_quality: 'partial' }
check(candidateGroupText(pendingGroup) === '航運（產業，事件資料待補，未計入族群分）', `partial group says why it did not count: ${candidateGroupText(pendingGroup)}`)
check(candidateGroupState(completeItem().groups[0]) === 'ranked' && candidateGroupState(pendingGroup) === 'pending' && candidateGroupState(completeItem().groups[1]) === 'unranked', 'three group states')
for (const quality of ['insufficient_members', 'insufficient_data', null]) {
  check(candidateGroupText({ ...pendingGroup, data_quality: quality }) === '航運（產業，當日未排名）', `${quality} group is unranked`)
}
{
  const pendingList = listResponse()
  pendingList.items[1] = { ...pendingList.items[1], groups: [pendingGroup] }
  const markup = render(<CandidatesSection data={pendingList} loading={false} error={null} />)
  // The today row keeps the group on one line (Issue 493, 510); the long form is its title.
  const meta = slice(rowOf(markup, 2), 'class="candidate-row-meta"', '</p>')
  check(meta.replace(/<[^>]+>/g, '').includes('航運（產業，事件資料待補）'), 'row: partial group text')
  check(meta.includes('title="航運（產業，事件資料待補，未計入族群分）"'), 'row: the long form is the title')
  check(/<button[^>]*>事件資料待補<\/button>/.test(meta), 'row: 「事件資料待補」 opens its glossary term')
  check(!meta.includes('當日未排名'), 'row: partial group is not called unranked')
}
// #661 (P-a): the source line is a fact; the news component and its reason carry the one 推論 mark.
// Issue 729: the source line names the market and chip sources and the AI news reading, without rule or prompt versions.
check(candidateSourceText(completeItem()) === '行情 臺灣證券交易所 · 籌碼 臺灣證券交易所 · 新聞方向 AI 判讀' && !candidateSourceText(completeItem()).includes('推論'), `news source without versions or 推論, got ${candidateSourceText(completeItem())}`)

// ---- detail content under each today row (the table's levels and total are checked in today/today.test.tsx) ----
const list = render(<CandidatesSection data={listResponse()} loading={false} error={null} />)
// The head names the strategy behind the list and links to /strategy (#577; UI_COPY_SPEC §10).
const STRATEGY_LINK = /<a class="text-link candidates-strategy-link" href="\/strategy">([^<]*)<\/a>/
check(STRATEGY_LINK.exec(slice(list, 'class="candidates-head"', '<ol'))?.[1] === '順勢籌碼型 · 策略說明 →', `今日名單頁首的連結寫「順勢籌碼型 · 策略說明 →」並連到 /strategy, got ${STRATEGY_LINK.exec(list)?.[1]}`)
const first = detailOf(rowOf(list, 1))
check(count(list, '<details class="candidate-detail"') === 2, 'one detail per candidate')
check(!first.includes(PARTIAL_NOTE) && !first.includes('candidate-null-notes'), 'complete row has no partial note')
for (const [component, score] of [['technical', '74'], ['chips', '92'], ['news_sentiment', '81'], ['group', '90']]) {
  check(slice(first, `data-component="${component}"`, '</div>').includes(`>${score}<`), `component ${component} shows ${score}`)
}
// Issue 654 AC-2: each of the four components is a 0–100 score bar, its number beside it.
for (const [component, label, score] of [['technical', '技術', '74'], ['chips', '籌碼', '92'], ['news_sentiment', '新聞情緒', '81'], ['group', '族群', '90']]) {
  const cell = slice(first, `data-component="${component}"`, '</div>')
  check(cell.includes(`<span class="score-bar" role="img" aria-label="${label} ${score}（0–100）" data-score="${score}">`) && cell.includes('class="score-bar-fill" style="width:'), `Issue 654: component ${component} is a bar at ${score}: ${cell}`)
}
check(slice(first, 'data-component="news_sentiment"', '</div>').includes('badge-accent') && !slice(first, 'data-component="chips"', '</div>').includes('badge-accent'), 'only news sentiment is marked 推論')
check(count(first, 'data-reason=') === 4, 'all four API reasons are shown')
check(first.indexOf('institutional_net_buy_5d') < first.indexOf('breakout_20d_high'), 'reasons keep the API order')
for (const [code, dot] of [['breakout_20d_high', 'technical'], ['institutional_net_buy_5d', 'chips'], ['news_positive_3d', 'news_sentiment'], ['hot_group_rank', 'group']]) {
  check(slice(first, `data-reason="${code}"`, '</li>').includes(`reason-dot-${dot}`), `${code} has the ${dot} dot`)
}
// #661 AC-2: one 推論 mark an inferred item. The API reason text already ends 「（推論）」, so no badge after it.
const inferredReason = slice(first, 'data-reason="news_positive_3d"', '</li>')
check(count(inferredReason, '推論') === 1 && !inferredReason.includes('badge-accent'), `inference reason: its own 「（推論）」 and no second badge: ${inferredReason}`)
const unmarked = render(<CandidatesSection data={{ ...listResponse(), items: [{ ...completeItem(), reasons: [{ code: 'news_positive_3d', component: 'news_sentiment', text: '近 3 日 2 則偏多新聞', params: {}, inference: true }] }] }} loading={false} error={null} />)
check(count(slice(unmarked, 'data-reason="news_positive_3d"', '</li>'), '推論') === 1 && slice(unmarked, 'data-reason="news_positive_3d"', '</li>').includes('badge-accent'), 'an inferred reason whose text does not say 推論 gets the one badge')
check(!slice(first, 'data-reason="breakout_20d_high"', '</li>').includes('推論'), 'fact reasons carry no 推論')
check(count(slice(first, 'data-component="news_sentiment"', '</div>'), '推論') === 1, 'news sentiment component: one 推論 badge')
for (const component of ['technical', 'chips', 'group']) check(!slice(first, `data-component="${component}"`, '</div>').includes('推論'), `fact component ${component}: no 推論`)
// The AI note block: one 「AI 推論」 badge in its head, no badge inside the parts (their text is the model's own).
const firstNote = slice(first, 'class="ai-inference candidate-note"', '</section>')
check(count(firstNote, 'AI 推論') === 1 && count(firstNote, 'badge-accent') === 1 && !slice(firstNote, '<dl class="candidate-note-parts">', '</dl>').includes('badge'), `AI 進出點說明: one AI 推論 badge, none inside: ${firstNote}`)
// Sources are facts (P-a): no 推論 in the 資料日期與來源 fold.
check(!slice(first, '<details class="details candidate-detail-sources">', '</details>').includes('推論'), '資料日期與來源: no 推論')
check(first.includes('資料日期 2026/10/16') && first.includes('臺灣證券交易所'), 'data date and sources in the detail (no page date known)')
// #661 AC-3 (D-b): with the navbar's page date the same day, the detail writes no date; another day still writes it.
const plain = (markup: string) => markup.replace(/<[^>]+>/g, "")
const onPage = (day: string, data = listResponse()) => detailOf(rowOf(render(<PageDateContext.Provider value={day}><CandidatesSection data={data} loading={false} error={null} /></PageDateContext.Provider>), 1))
const sameDayDetail = onPage('2026-10-16')
check(!sameDayDetail.includes('資料日期') || !/資料日期 \d/.test(plain(sameDayDetail)), `page date 2026/10/16: no 「資料日期 2026/10/16」 in the detail: ${plain(sameDayDetail).match(/資料日期[^<]{0,20}/g)}`)
check(sameDayDetail.includes('臺灣證券交易所'), 'page date: the sources stay')
check(/資料日期 2026\/10\/16/.test(plain(onPage('2026-10-19'))), 'another page date: the detail still writes 資料日期 2026/10/16')
const olderLiquidity = listResponse()
olderLiquidity.items[0] = { ...olderLiquidity.items[0], liquidity: { state: 'eligible', average_volume_lots_20d: 1682, minimum_lots: 1000, ...olderLiquidity.items[0].liquidity, data_as_of: '2026-10-15' } as CandidateLiquidity }
const liquidityLine = slice(onPage('2026-10-16', olderLiquidity), 'candidate-liquidity', '</div>')
check(liquidityLine.includes('資料日期 2026/10/15'), `a liquidity of another day than the page keeps its date: ${liquidityLine}`)

// ---- partial components ----
const second = detailOf(rowOf(list, 2))
check(second.includes(PARTIAL_NOTE), 'partial row explains the renormalised score')
check(slice(second, 'data-component="group"', '</div>').includes('>—<') && slice(second, 'data-component="news_sentiment"', '</div>').includes('>—<'), 'null components show 「—」')
check(!slice(second, 'data-component="group"', '</div>').includes('>0<'), 'null component is never 0')
for (const [component, label] of [['group', '族群'], ['news_sentiment', '新聞情緒']]) {
  const cell = slice(second, `data-component="${component}"`, '</div>')
  check(cell.includes(`aria-label="${label} 無資料" data-score="none"`) && !cell.includes('score-bar-fill'), `Issue 654: a null ${component} draws no fill: ${cell}`)
}
check(second.includes('族群：當日沒有已排名且資料完整的所屬產業或題材') && second.includes('新聞情緒：近 3 日沒有成功的新聞收集，新聞分項無資料'), 'null_explanation shown next to the scores')
const row2 = rowOf(list, 2)
check(row2.includes('13.05～13.35') && row2.includes('上櫃') && row2.includes('回踩型'), 'pullback zone, TPEx label and the entry type (Issue 493)')
check(!row2.includes('level-target-2'), 'missing target 2 is not rendered')
check(count(second, 'data-reason=') === 2, 'fewer reasons are not padded')

// ---- LLM note (#220): inference block apart from the rule values ----
const note = slice(first, 'class="ai-inference candidate-note"', '</section>')
check(note.includes('data-note-state="done"') && note.includes('AI 進出點說明') && note.includes('AI 推論'), 'done note has its title and the AI 推論 badge')
for (const [part, label, text] of [
  ['selection', '為何入選', '三大法人 5 日淨買超約 20 日均量 2.59 倍'],
  ['levels', '進場區、停損與目標', '條件失效的停損 157.82'],
  ['risks', '需留意的風險', '屬推論'],
] as const) {
  check(slice(note, `data-note-part="${part}"`, '</div>').includes(label) && slice(note, `data-note-part="${part}"`, '</div>').includes(text), `note part ${part}`)
}
check(note.includes(NOTE_DISCLAIMER), 'note says it is inference, not advice')
check(note.includes('<p class="small-note ai-meta">產生於 2026/10/16 19:05</p>') && !note.includes('claude-sonnet') && !note.includes('candidate_notes_v1'), 'the note shows its Taipei time, without model or prompt version (Issue 729)')
// Issue 510: the note opens the detail; the rule levels, the components and reasons, the date and sources come after it.
check(first.indexOf('candidate-note') > 0 && first.indexOf('candidate-note') < first.indexOf('candidate-detail-levels') && first.indexOf('candidate-detail-levels') < first.indexOf('candidate-reasons') && first.indexOf('candidate-reasons') < first.indexOf('來源：'), 'note first, then the levels, the reasons, the date and sources')
check(!note.includes('candidate-detail-levels') && !note.includes('level-stop'), 'rule levels stay outside the AI block')
const missing = slice(second, 'class="ai-inference candidate-note"', '</section>')
check(missing.includes('data-note-state="empty"') && missing.includes(NOTE_MISSING_TEXT) && !missing.includes('data-note-part') && !missing.includes('ai-meta'), 'a row without a note shows the fixed copy')
const pending = candidateNoteView({ ...doneNote(), status: 'pending', model: null, selection: null, levels: null, risks: null })
check(pending.kind === 'empty' && pending.text === NOTE_PENDING_TEXT, 'a pending note shows the fixed copy')
check(pending.meta === '嘗試於 2026/10/16 19:05', 'a pending note shows its attempt time only')
check(candidateNoteView({ ...doneNote(), risks: '' }).kind === 'empty', 'a done note missing a part is not shown half-filled')
check(candidateNoteView(null).kind === 'empty' && candidateNoteView(undefined).kind === 'empty', 'null and missing notes use the fixed copy')
check(candidateNoteMeta({ ...doneNote(), model: null, generated_at: '2026-10-16T11:05:00' }) === null, 'a time without offset shows no meta line')

// ---- zero candidates and not computed ----
for (const reason of ['no_actionable_signals', 'all_excluded'] as const) {
  const data = zeroResponse(reason)
  const markup = render(<CandidatesSection data={data} loading={false} error={null} />)
  check(markup.includes(data.zero_reason_text ?? '?') && markup.includes('當日零候選'), `zero run ${reason} shows zero_reason_text`)
  check(!markup.includes('data-candidate-rank') && markup.includes('資料 2026/10/16') && !markup.includes('0 檔'), `zero run ${reason} keeps the date badge only`)
  check(candidatesState({ ...data, zero_reason_text: null }).kind === 'zero' && (candidatesState({ ...data, zero_reason_text: null }) as { text: string }).text === data.zero_reason_text, `zero ${reason} falls back to the §10 copy`)
}
const notComputed = render(<CandidatesSection data={notComputedResponse()} loading={false} error={null} />)
check(STRATEGY_LINK.exec(notComputed)?.[1] === '順勢籌碼型 · 策略說明 →', `尚無候選清單時頁首仍標出策略名稱, got ${STRATEGY_LINK.exec(notComputed)?.[1]}`)
check(notComputed.includes(NOT_COMPUTED_TEXT) && notComputed.includes('尚無候選清單') && !notComputed.includes('date-badge'), 'not_computed copy without a date badge')
// Issue 729: the head holds the title, date, count, the day the conditions held and the strategy link; no disclaimer,
// how-to-read clause or research status in any state.
for (const [label, markup] of [['list', list], ['zero', render(<CandidatesSection data={zeroResponse('no_actionable_signals')} loading={false} error={null} />)], ['not computed', notComputed]] as const) {
  const head = slice(markup, 'class="candidates-head"', '</div>')
  check(!removedCopyIn(markup).length, `${label}: removed copy is back: ${removedCopyIn(markup).join('、')}`)
  check(!head.includes('candidate-disclaimer') && !head.includes('candidate-evidence'), `${label}: no disclaimer or evidence line in the head`)
}
check(slice(list, 'class="candidates-head"', '</div>').includes('<p class="small-note candidate-notes"><span class="candidate-t1">2026/10/16 收盤後條件成立</span></p>'), 'list: the head says the day the conditions held, nothing more')
check(!slice(notComputed, 'class="candidates-head"', '</div>').includes('candidate-notes'), 'not computed: no empty notes paragraph')

// ---- loading and error ----
check(render(<CandidatesSection data={undefined} loading error={null} />).includes('今日名單載入中…'), 'loading skeleton')
check(render(<CandidatesSection data={undefined} loading={false} error={new Error('API 500: boom')} />).includes('API 500: boom'), 'error reason shown')

// ---- stock page: the strategy board's candidate row reuses the score details (stock/strategyBoard.test.tsx) ----
const details = render(<ScoreDetails item={partialItem()} open={false} />)
check(details.includes('<details class="details candidate-details">') && details.includes('評分細節、資料日期與來源'), 'score details stay collapsed on the board')
check(!details.includes('href="/stocks/'), 'score details do not link to the stock page')
check(details.replace(/<[^>]+>/g, '').includes('權重涵蓋 65%'), 'weight coverage in details')
check(render(<ScoreDetails item={partialItem()} open />).includes('<details class="details candidate-details" open="">'), 'score details open when asked')
const completeDetails = render(<ScoreDetails item={completeItem()} open={false} />)
check(completeDetails.includes('同檔另一策略：回踩條件 總分 61') && completeDetails.includes('規則最早執行日 2026/10/19'), 'alternatives and earliest execution date in details')
check(completeDetails.includes('資料日期 2026/10/16') && completeDetails.includes('臺灣證券交易所'), 'data date and sources in details')
// Issue 654 AC-2: the table's component titles carry the score bar and the weight (the sub-item 百分位 column stays a number).
const groupTitles = [...completeDetails.matchAll(/<span class="score-group-title">(.*?)<span class="score-group-weight">權重 (\d+)%<\/span>/g)].map((match) => /data-score="([^"]*)"/.exec(match[1])?.[1])
check(JSON.stringify(groupTitles) === JSON.stringify(['74', '92', '81', '90']), `Issue 654: every component title in the score details is a bar: ${JSON.stringify(groupTitles)}`)
check(!/（\d+，權重/.test(completeDetails), 'Issue 654: the old 「技術（74，權重 35%）」 text title is gone')
const partialDetails = render(<ScoreDetails item={partialItem()} open />)
check(partialDetails.includes('aria-label="族群 無資料" data-score="none"'), `Issue 654: a null component title draws an empty bar: ${partialDetails}`)

// ---- 加入追蹤 (#253): one button or link per candidate ----
check(count(list, '>加入追蹤</button>') === 2 && !list.includes('已在追蹤'), 'every untracked candidate has the add button once, in its detail')
// The today list (Issue 510) puts it in each candidate's detail, beside the AI note.
const todayItems = listResponse().items.map((item, index) => index === 0 ? { ...item, candidate_id: 11, open_plan_id: 7 } : item)
const today = render(<CandidatesSection data={{ ...listResponse(), items: todayItems }} loading={false} error={null} />)
const details2 = todayItems.map((item) => detailOf(rowOf(today, item.rank)))
check(details2.every((detail, index) => slice(detail, 'class="candidate-detail-actions"', '</div>').includes(index === 0 ? '>已在追蹤</a>' : '>加入追蹤</button>')), 'every detail has the plan button or link')
check(details2[0].includes('href="/watch#plan-7">已在追蹤</a>') && !details2[0].includes('加入追蹤'), 'a tracked candidate links to its plan')

// ---- liquidity floor (candidate_score_v6, #490; UI_COPY_SPEC §10) ----
check(formatLots(1681.55) === '1,681 張' && formatLots(999.6) === '999 張' && formatLots(0) === '0 張' && formatLots(null) === '—', 'lots: whole lots rounded down with separators, null is 「—」')
check(liquidityExclusionText({ exclusion: 'low_volume', average_volume_lots_20d: 999.6, minimum_lots: 1000 }) === '20 日均量 999 張，低於 1,000 張門檻，不列候選', 'just under the floor never reads as the floor (PR 496 review)')
check(averageVolumeText(29803.2) === '20 日均量 29,803 張' && averageVolumeText(null) === '20 日均量資料不足', 'average volume copy')
const lowVolume = { exclusion: 'low_volume', average_volume_lots_20d: 32.4, minimum_lots: 1000 }
check(liquidityExclusionText(lowVolume) === '20 日均量 32 張，低於 1,000 張門檻，不列候選', `low volume note, got ${liquidityExclusionText(lowVolume)}`)
check(liquidityExclusionText({ ...lowVolume, exclusion: 'liquidity_data_missing', average_volume_lots_20d: null }) === '20 日均量資料不足，無法確認是否達 1,000 張門檻，不列候選', 'missing data note')
check(liquidityExclusionText(null) === null && liquidityExclusionText({ ...lowVolume, exclusion: null }) === null, 'no note without an exclusion')
const liquidItem = { ...completeItem(), liquidity: { average_volume_lots_20d: 1682.3, minimum_lots: 1000, state: 'ok', below_minimum: false, data_as_of: '2026-10-16', window_start: '2026-09-18', window_end: '2026-10-16', unit: 'lots' as const } }
const liquidList = render(<CandidatesSection data={{ ...listResponse(), items: [liquidItem] }} loading={false} error={null} />)
// Issue 510: the average volume moved off the row into the detail's 資料日期與來源, with its date and the floor.
check(count(liquidList, '20 日均量 1,682 張') === 1 && slice(liquidList, 'candidate-detail-sources', '</details>').includes('20 日均量 1,682 張（資料日期 2026/10/16，候選門檻 1,000 張）'), `the detail shows the lots with the date and the floor, the row none, got ${count(liquidList, '20 日均量 1,682 張')}`)
check(!render(<CandidatesSection data={listResponse()} loading={false} error={null} />).includes('candidate-liquidity'), 'a run before candidate_score_v6 shows no average volume')

// ---- RR basis (#580; UI_COPY_SPEC §10): the today row names what the RR's entry is, the detail names its price ----
check(riskRewardBasisNote('entry_zone_midpoint') === '以進場區中點計算' && riskRewardBasisNote('entry_price') === '以進場價計算' && riskRewardBasisNote('signal_close') === '以資料日收盤計算', 'the three basis notes')
check(riskRewardBasisNote(null) === null && riskRewardBasisNote(undefined) === null && riskRewardBasisNote('other') === null, 'an unknown or missing basis has no note')
check(formatRiskRewardWithBasis(1.6234, 'entry_zone_midpoint', 27.27) === '1.62 倍（以進場區中點 27.27 元計算）', 'the RR with its basis and entry price')
check(formatRiskRewardWithBasis(1.6, null, 27.27) === '1.60 倍' && formatRiskRewardWithBasis(1.6, 'entry_price', null) === '1.60 倍' && formatRiskRewardWithBasis(null, 'entry_price', 10) === '—', 'no basis, no price or no RR: the RR alone')
const midpointItem = {
  ...completeItem(), strategy: 'pullback_v4',
  levels: {
    entry_type: 'pullback', entry: 27.27, entry_zone: { low: 26.85, high: 27.69 }, invalid_price: 26.5, target_1: 28.52, target_2: 29.4,
    risk_reward: 1.6234, risk_reward_basis: 'entry_zone_midpoint' as const, earliest_execution_date: null,
  },
}
const midpointList = render(<CandidatesSection data={{ ...listResponse(), items: [midpointItem] }} loading={false} error={null} />)
const midpointRow = slice(rowOf(midpointList, 1), 'candidate-row-nums', '</dl>')
check(midpointRow.includes('1.62 倍') && midpointRow.includes('class="small-note candidate-rr-basis">以進場區中點計算</div>'), `the row's RR names its basis, got ${midpointRow}`)
check(detailOf(rowOf(midpointList, 1)).includes('1.62 倍（以進場區中點 27.27 元計算）'), 'the detail names the midpoint price')
const breakoutList = render(<CandidatesSection data={{ ...listResponse(), items: [{ ...completeItem(), levels: { ...completeItem().levels, risk_reward_basis: 'entry_price' as const } }] }} loading={false} error={null} />)
check(breakoutList.includes('>以進場價計算</div>') && breakoutList.includes('1.60 倍（以進場價 161.50 元計算）'), 'a breakout reads at its entry price')
check(!render(<CandidatesSection data={listResponse()} loading={false} error={null} />).includes('candidate-rr-basis'), 'a response without the basis shows no note')

// ---- 盤後終端: the price ladder and the chart beside the list (DESIGN_SYSTEM §5 候選列表) ----
const breakoutItem = completeItem()
check(JSON.stringify(candidateChartLevels(breakoutItem.levels)) === JSON.stringify({ entry: 161.5, stop: 157.82, target: 167.39 }), 'the chart draws the entry, the stop and the first target')
const zoneLevels = { ...breakoutItem.levels, entry_type: 'pullback', entry: null, entry_zone: { low: 160, high: 162 } }
check(candidateChartLevels(zoneLevels)?.entry === 161, 'without an entry the zone midpoint is the entry')
check(candidateChartLevels({ ...breakoutItem.levels, invalid_price: null }) === null, 'a missing stop draws nothing')
check(candidateChartLevels({ ...breakoutItem.levels, invalid_price: 170 }) === null, 'a stop above the entry draws nothing')
const ladder = priceLadder(breakoutItem.levels, 161.5)
const entryAt = ((161.5 - 157.82) / (167.39 - 157.82)) * 100
check(ladder !== null && Math.abs(ladder.entry - entryAt) < 1e-9 && Math.abs(ladder.close - entryAt) < 1e-9 && ladder.outside === null, `a close at the entry sits on the entry tick: ${JSON.stringify(ladder)}`)
check(priceLadder(breakoutItem.levels, 150)?.close === 0 && priceLadder(breakoutItem.levels, 150)?.outside === 'below_stop', 'a close under the stop is clamped to the left end and says so')
check(priceLadder(breakoutItem.levels, 180)?.close === 100 && priceLadder(breakoutItem.levels, 180)?.outside === 'above_target', 'a close over the target is clamped to the right end and says so')
check(priceLadder(breakoutItem.levels, null) === null && priceLadder({ ...breakoutItem.levels, target_1: null }, 161.5) === null, 'no close or no full set of levels: no ladder')
check(ladderLabel(priceLadder(breakoutItem.levels, 159)!) === '收盤在停損與進場之間' && ladderLabel(priceLadder(breakoutItem.levels, 165)!) === '收盤在進場與目標之間', 'the ladder label says which side of the entry the close is')
check(ladderLabel(priceLadder(breakoutItem.levels, 150)!) === '收盤已低於停損' && ladderLabel(priceLadder(breakoutItem.levels, 180)!) === '收盤已高於目標', 'and when it ran past an end')
const ladderMarkup = renderToStaticMarkup(<PriceLadder item={breakoutItem} />)
check(ladderMarkup.includes('role="img"') && ladderMarkup.includes('price-ladder-entry') && ladderMarkup.includes('price-ladder-close'), 'the ladder is an image with an entry tick and a close dot')
check(ladderMarkup.replace(/<[^>]+>/g, '') === '', 'the ladder adds no page text (the row already states the prices)')
check(renderToStaticMarkup(<PriceLadder item={{ ...breakoutItem, levels: { ...breakoutItem.levels, target_1: null } }} />) === '', 'no ladder without a full set of levels')

// ---- the sparkline (Issue 653; DESIGN_SYSTEM §5 候選列表): 30 sessions' closes, red up and green down, a labelled image ----
const closes = (values: Array<number | null>) => ({ dates: values.map((_, index) => `2026-10-${String(index + 1).padStart(2, '0')}`), closes: values })
const rising = sparkline(closes([100, 104, 102, 110]))
check(rising?.tone === 'up' && rising.label === '近 4 個交易日收盤走勢：2026/10/01–2026/10/04 +10.00%', `a span that rose is up and its label states the span and change: ${JSON.stringify(rising)}`)
const falling = sparkline(closes([50, 48, 49, 45]))
check(falling?.tone === 'down' && falling.label.endsWith(' -10.00%'), `a span that fell is down: ${JSON.stringify(falling)}`)
check(sparkline(closes([20, 21, 20]))?.tone === 'flat' && sparkline(closes([20, 21, 20]))!.label.endsWith(' 0.00%'), 'an unchanged span is flat')
check(rising?.path === 'M1 23L32.33 14.2L63.67 18.6L95 1', `the line spans the box, the high at the top and the low at the bottom: ${rising?.path}`)
const gapped = sparkline(closes([null, 100, null, 101, 102]))
check(gapped !== null && (gapped.path.match(/M/g) ?? []).length === 2 && gapped.label.includes('2026/10/02–2026/10/05'), `a session without a close leaves a gap, and the span runs from the first close to the last: ${JSON.stringify(gapped)}`)
check(sparkline(closes([null, 100, null])) === null && sparkline(closes([])) === null && sparkline(undefined) === null, 'fewer than 2 closes: no line')
check(sparkline({ dates: ['2026-10-01'], closes: [1, 2] }) === null, 'dates and closes of different lengths: no line')
const flatLine = sparkline(closes([30, 30]))
check(flatLine?.path === `M1 ${SPARKLINE_HEIGHT / 2}L95 ${SPARKLINE_HEIGHT / 2}`, `an unchanged price is a level line in the middle: ${flatLine?.path}`)
const sparkMarkup = renderToStaticMarkup(<Sparkline item={{ recent_closes: closes([100, 104, 102, 110]) }} />)
check(sparkMarkup.startsWith('<svg class="sparkline sparkline-up" role="img" aria-label="近 4 個交易日收盤走勢：2026/10/01–2026/10/04 +10.00%"'), `the sparkline is an image whose class carries the tone: ${sparkMarkup}`)
check(sparkMarkup.includes(`viewBox="0 0 ${SPARKLINE_WIDTH} ${SPARKLINE_HEIGHT}"`) && sparkMarkup.replace(/<[^>]+>/g, '') === '' && !/<(text|line|g)b/.test(sparkMarkup), 'no axis or text: one path in the box')
check(renderToStaticMarkup(<Sparkline item={{ recent_closes: closes([50, 45]) }} />).includes('class="sparkline sparkline-down"'), 'a span that fell carries the down class')
check(renderToStaticMarkup(<Sparkline item={{ recent_closes: closes([50]) }} />) === '' && renderToStaticMarkup(<Sparkline item={{}} />) === '', 'no sparkline with one close or none (responses from before Issue 653)')

const plainList = render(<CandidatesSection data={listResponse()} loading={false} error={null} />)
check(!plainList.includes('candidates-terminal') && !plainList.includes('candidate-rank-button'), 'without a chart the list is the list alone and the rank is not a button')
const charted = render(<CandidatesSection data={listResponse()} loading={false} error={null} wide renderChart={(item) => <div data-test-chart={item.instrument.symbol} />} />)
check(charted.includes('class="candidates-terminal"') && charted.includes('data-chart-rank="1"') && charted.includes('data-test-chart="2377"'), 'with a chart the first candidate is the one shown')
check((charted.match(/candidate-rank-button/g) ?? []).length === 2 && (charted.match(/aria-pressed="true"/g) ?? []).length === 1, 'every rank is a button and only the shown one is pressed')
check(charted.includes('aria-label="第 1 名，顯示走勢圖"') && charted.includes('>#1</button>'), 'the rank button keeps its text and says what it does')
check(charted.indexOf('candidates-terminal-list') < charted.indexOf('candidates-terminal-chart'), 'the list comes before the chart in the document')
const text = (markup: string) => markup.replace(/<[^>]+>/g, '')
check(text(charted) === text(plainList), 'the chart slot and the ladder change no page text of the list')

// ---- below 1280px a row opens its own K-line card (Issue 665; DESIGN_SYSTEM §5 候選列表, decision 6841170465) ----
// No DOM here: renderChart is what mounts CandidateChart (its /bars query and ECharts), so a call count of 0 means no
// card, no /bars fetch and no chart initialised. A click is the pure transition plus a render in the next state.
check(TERMINAL_MIN_WIDTH === 1280, 'the chart sits beside the list from 1280px, the width styles.css uses')
const chartCalls: string[] = []
const spyChart = (item: CandidateItem) => { chartCalls.push(item.instrument.symbol); return <div className="stock-chart-card" data-test-chart={item.instrument.symbol} /> }
const narrow = render(<CandidatesSection data={listResponse()} loading={false} error={null} renderChart={spyChart} />)
check(chartCalls.length === 0, `below 1280px the first render mounts no chart (no /bars, no ECharts): ${chartCalls.join(',')}`)
check(!narrow.includes('candidates-terminal') && !narrow.includes('stock-chart-card') && !narrow.includes('data-test-chart'), 'below 1280px there is no chart beside the list, hidden or not')
check(!narrow.includes('aria-pressed'), 'below 1280px no rank claims to be the shown chart')
const toggles = narrow.match(/<button type="button" class="candidate-rank candidate-rank-button candidate-chart-toggle"[^>]*>#\d+<\/button>/g) ?? []
check(toggles.length === 2 && toggles.every((button) => button.includes('aria-expanded="false"')), `every rank is a closed disclosure button (Enter and Space are a button's own): ${toggles.join(' ')}`)
check(toggles[0]!.includes('aria-controls="candidate-chart-1"') && toggles[0]!.includes(`aria-label="${chartToggleLabel(1, false)}"`) && chartToggleLabel(1, false) === '第 1 名，展開 K 線圖' && chartToggleLabel(1, true) === '第 1 名，收起 K 線圖', `the rank names the card it controls and says what it does: ${toggles[0]}`)
check(narrow.includes('<div class="candidate-chart" id="candidate-chart-1" hidden="">') && narrow.includes('<div class="candidate-chart" id="candidate-chart-2" hidden="">'), 'each closed row keeps an empty, hidden slot, so aria-controls always names an element')
check(text(narrow) === text(plainList), 'the closed slots and the rank buttons change no page text (page_checks T5–T8, T13)')
const rowMarkup = (markup: string, rank: number) => markup.slice(markup.indexOf(`data-candidate-rank="${rank}"`), rank === 1 ? markup.indexOf('data-candidate-rank="2"') : undefined)
const row1 = rowMarkup(narrow, 1)
check(row1.indexOf('candidate-chart-toggle') < row1.indexOf('candidate-row-name') && row1.indexOf('candidate-row-name') < row1.indexOf('candidate-ai-toggle'), 'focus order: the rank, then the name link, then 「AI 推論」')
check(row1.indexOf('candidate-ai-toggle') < row1.indexOf('id="candidate-chart-1"') && row1.indexOf('id="candidate-chart-1"') < row1.indexOf('id="candidate-detail-1"'), 'the card slot sits between the row and its AI detail')
check(!/<details[^>]*>(?:(?!<\/details>)[\s\S])*candidate-chart-toggle/.test(narrow) && !/<details[^>]*class="candidate-chart/.test(narrow), 'the card is not inside a <details>, so the screenshot tool opening every <details> mounts no chart')

chartCalls.length = 0
const opened = render(<TodayCandidateList items={listResponse().items} renderChart={spyChart} initialChartRank={1} />)
check(chartCalls.join(',') === '2377', `an open row mounts its own card once, and only that row's (one /bars): ${chartCalls.join(',')}`)
const openRow = rowMarkup(opened, 1)
check(openRow.includes('aria-expanded="true"') && openRow.includes(`aria-label="${chartToggleLabel(1, true)}"`) && opened.includes('candidate-row-charted" data-candidate-rank="1"'), 'the open row\'s rank is expanded and says it closes the card')
check(openRow.includes('<div class="candidate-chart" id="candidate-chart-1" role="region" aria-label="2377 微星 走勢圖"><div class="stock-chart-card" data-test-chart="2377"></div></div>'), `the open card is a labelled region under the row: ${openRow.slice(openRow.indexOf('id="candidate-chart-1"') - 30, openRow.indexOf('id="candidate-detail-1"'))}`)
check(openRow.includes('aria-controls="candidate-detail-1" aria-expanded') === false && openRow.includes('class="badge badge-accent badge-compact candidate-ai-toggle" aria-expanded="false"') && !/<details class="candidate-detail"[^>]*open/.test(opened), 'opening the card leaves the AI detail closed')
check(rowMarkup(opened, 2).includes('aria-expanded="false"') && rowMarkup(opened, 2).includes('id="candidate-chart-2" hidden=""'), 'the other row stays closed')
check(nextChartRank(null, 1) === 1 && nextChartRank(1, 1) === null && nextChartRank(1, 2) === 2, 'pressing a closed row opens it, the open row closes it, another row moves the card there (one at a time)')
chartCalls.length = 0
render(<TodayCandidateList items={listResponse().items} renderChart={spyChart} initialChartRank={nextChartRank(1, 2)} />)
check(chartCalls.join(',') === partialItem().instrument.symbol, `after moving to another row only that row's card is mounted (the first one unmounts): ${chartCalls.join(',')}`)
chartCalls.length = 0
render(<TodayCandidateList items={listResponse().items} renderChart={spyChart} initialChartRank={nextChartRank(1, 1)} />)
check(chartCalls.length === 0, 'a closed card is unmounted, not hidden')
chartCalls.length = 0
const both = render(<TodayCandidateList items={listResponse().items} renderChart={spyChart} initialChartRank={1} wide />)
check(chartCalls.join(',') === '2377' && both.includes('class="candidates-terminal"') && !both.includes('candidate-chart-toggle') && !both.includes('id="candidate-chart-1"'), 'from 1280px the list is unchanged: one chart beside it, the rank picks it, no card under a row')

// A tap on the row's free space toggles; a link, a button (rank, term, AI), a summary, or a text selection does not.
const target = (ignored: boolean) => ({ closest: (selector: string) => (selector === ROW_CLICK_IGNORED && ignored ? {} : null) })
check(rowClickToggles(target(false), '') && !rowClickToggles(target(true), '') && !rowClickToggles(target(false), '389.23') && !rowClickToggles(null, ''), 'row taps: free space toggles; controls, a selection or no target do not')
check(['a', 'button', 'summary', '[role="button"]'].every((part) => ROW_CLICK_IGNORED.includes(part)), `ignored targets cover links, buttons (rank, terms, AI) and summaries: ${ROW_CLICK_IGNORED}`)
check(/<div class="candidate-row-figures"><svg class="sparkline sparkline-up"[^>]*><path d="[^"]+"><\/path><\/svg><div class="price-ladder"/.test(plainList), 'a row draws the sparkline, then the ladder, on one line under the sentence (Issue 653)')
check((plainList.match(/class="sparkline /g) ?? []).length === 1, 'only the row with closes has a sparkline')

// ---- Issue 681: the 隔夜美股 line under the head, and 費半 on the semiconductor rows ----
const lineOf = (markup: string) => plain(slice(markup, '<p class="overnight-us"', '</p>'))
const withUs = (us = overnightUs(), links: string[][] = [['SOX'], []]) => ({
  ...listResponse(),
  overnight_us: us,
  items: listResponse().items.map((item, index) => ({ ...item, overnight_us_links: links[index] ?? [] })),
})
const usPage = render(<CandidatesSection data={withUs()} loading={false} error={null} />)
const usLine = lineOf(usPage)
check(usLine.endsWith('隔夜美股 資料 2026/11/13 S&amp;P 500 +0.54% · NASDAQ -0.50% · 道瓊 0.00% · 費半 +2.04%'), `the line: title, the one date, the four changes in order: ${usLine}`)
check(usPage.indexOf('class="candidates-head"') < usPage.indexOf('class="overnight-us"') && usPage.indexOf('class="overnight-us"') < usPage.indexOf('class="candidate-list"'), 'the line sits under the head, above the list')
check(!/<p class="overnight-us"[^>]*>(?:(?!<\/p>)[\s\S])*<div/.test(usPage), 'inline runs only: one line of page text (page_checks T22)')
const usMarkup = slice(usPage, '<p class="overnight-us"', '</p>')
check(/data-us-index="SPX">S&amp;P 500 <span class="overnight-us-change tone-up">\+0\.54%/.test(usMarkup) && /data-us-index="IXIC">NASDAQ <span class="overnight-us-change tone-down">-0\.50%/.test(usMarkup) && /data-us-index="DJI">道瓊 <span class="overnight-us-change tone-flat">0\.00%/.test(usMarkup), 'red up, green down, flat at 0.00%')
// The SOX row: the change on the title line right after the name; the other row shows none.
const soxRow = rowOf(usPage, 1)
const soxTitle = plain(slice(soxRow, '<p class="candidate-row-title">', '</p>'))
check(soxTitle.includes('2377 微星 費半 +2.04% 上市 · ') && !soxTitle.includes('非最新') && soxTitle.indexOf('費半') < soxTitle.indexOf('上市'), `the SOX row: 「費半 +2.04%」 right after the name, before the market and group (the ellipsis cuts those): ${soxTitle}`)
check(!rowOf(usPage, 2).includes('candidate-row-us') && !rowOf(usPage, 2).includes('費半'), 'a row without a link shows no US index')
check(SOX_GROUP_ID === 'official-industry-1858340d045a575f', 'the fixture links the official 半導體 industry')
// Not yet updated: every index of an earlier night is stale; the lead says so once and the rows mark theirs 非最新.
const staleIndexes = overnightUs().indexes.map((index) => ({ ...index, trading_date: '2026-11-12', freshness: 'stale' }))
const stalePage = render(<CandidatesSection data={withUs(overnightUs(staleIndexes))} loading={false} error={null} />)
check(lineOf(stalePage).endsWith(`隔夜美股 ${OVERNIGHT_US_PENDING} 資料 2026/11/12 S&amp;P 500 +0.54% · NASDAQ -0.50% · 道瓊 0.00% · 費半 +2.04%`), `not yet updated: 「美股尚未更新」 then the older closes: ${lineOf(stalePage)}`)
check(plain(slice(rowOf(stalePage, 1), '<p class="candidate-row-title">', '</p>')).includes('2377 微星 費半 +2.04% 非最新 上市'), 'a row\'s stale 費半 says 非最新')
// Nothing collected: the lead alone, no row mark.
const none = overnightUs().indexes.map((index) => ({ exchange: 'US', symbol: index.symbol, name: index.name, series_id: index.series_id, status: 'unavailable', reason: 'not_collected', expected_date: '2026-11-13' }))
const nonePage = render(<CandidatesSection data={withUs(overnightUs(none))} loading={false} error={null} />)
check(lineOf(nonePage).endsWith(`隔夜美股 ${OVERNIGHT_US_PENDING}`) && !rowOf(nonePage, 1).includes('費半'), `nothing collected: 「隔夜美股 美股尚未更新」 only: ${lineOf(nonePage)}`)
// One index missing, another a day old among fresh ones: 未取得, and its own 非最新.
const mixed = overnightUs().indexes.map((index) => index.symbol === 'DJI' ? { ...index, status: 'unavailable', reason: 'fetch_failed', close: null } : index.symbol === 'IXIC' ? { ...index, freshness: 'stale' } : index)
check(lineOf(render(<CandidatesSection data={withUs(overnightUs(mixed))} loading={false} error={null} />)).endsWith('資料 2026/11/13 S&amp;P 500 +0.54% · NASDAQ -0.50% 非最新 · 道瓊 未取得 · 費半 +2.04%'), 'one index failed, one stale')
// A US holiday: the session before it is shown, 美股休市 leads.
const closed = overnightUs().indexes.map((index) => ({ ...index, freshness: 'us_market_closed', trading_date: '2026-11-25' }))
check(overnightUsView(overnightUs(closed))?.lead === OVERNIGHT_US_CLOSED && lineOf(render(<CandidatesSection data={withUs(overnightUs(closed))} loading={false} error={null} />)).endsWith(`隔夜美股 ${OVERNIGHT_US_CLOSED} 資料 2026/11/25 S&amp;P 500 +0.54% · NASDAQ -0.50% · 道瓊 0.00% · 費半 +2.04%`), 'a US holiday: 美股休市 and the session before it')
// Different dates: each index carries its own.
const split = overnightUs().indexes.map((index) => index.symbol === 'SOX' ? { ...index, trading_date: '2026-11-12', freshness: 'stale' } : index)
check(lineOf(render(<CandidatesSection data={withUs(overnightUs(split))} loading={false} error={null} />)).endsWith('隔夜美股 S&amp;P 500 +0.54%（2026/11/13） · NASDAQ -0.50%（2026/11/13） · 道瓊 0.00%（2026/11/13） · 費半 +2.04%（2026/11/12） 非最新'), 'different dates: no common date, each its own')
// Every state of the list has the line; loading, a failure, or a response from before Issue 681 has none.
check(lineOf(render(<CandidatesSection data={{ ...notComputedResponse(), overnight_us: overnightUs() }} loading={false} error={null} />)).startsWith('隔夜美股 資料 2026/11/13'), 'a day without a list still has the line')
check(!render(<CandidatesSection data={listResponse()} loading={false} error={null} />).includes('overnight-us') && !render(<CandidatesSection data={withUs()} loading error={null} />).includes('overnight-us'), 'no line without overnight_us or while loading')

// ---- Issue 755: 開盤前檢查, the overnight news of the list (three states: news, none, not checked) ----
const preopenLineOf = (markup: string) => plain(slice(markup, '<p class="preopen-line"', '</p>'))
const titleOf = (markup: string, rank: number) => plain(slice(rowOf(markup, rank), '<p class="candidate-row-title">', '</p>'))
const panelOf = (markup: string) => plain(slice(markup, '<section class="preopen-news"', '</section>'))
const withPreopen = (check = preopenChecked(), news: Array<PreopenNews | null> = [preopenNews(), noPreopenNews()]) => ({
  ...listResponse(),
  preopen_check: check,
  items: listResponse().items.map((item, index) => ({ ...item, preopen_news: news[index] ?? null })),
})
// With news: the line, the row's mark, the detail's list.
const newsPage = render(<CandidatesSection data={withPreopen()} loading={false} error={null} />)
check(preopenLineOf(newsPage) === '開盤前檢查 2026/11/16 08:20 · 隔夜新聞 1 檔', `the line states the check's time and the stocks with news: ${preopenLineOf(newsPage)}`)
check(newsPage.indexOf('class="preopen-line"') < newsPage.indexOf('class="candidate-list"'), 'the line sits above the list')
const markOf = (markup: string, rank: number) => plain(slice(rowOf(markup, rank), '<p class="candidate-row-preopen"', '</p>'))
check(markOf(newsPage, 1) === '隔夜新聞 3（可能負向 1）', `the row's mark, only 可能負向 in the brackets: ${markOf(newsPage, 1)}`)
// Review 6889365957: on the title line the ellipsis cut the mark off on a phone; it is a line of its own between the
// title and the entry sentence.
const newsRow = rowOf(newsPage, 1)
check(!titleOf(newsPage, 1).includes('隔夜新聞') && newsRow.indexOf('class="candidate-row-title"') < newsRow.indexOf('class="candidate-row-preopen"') && newsRow.indexOf('class="candidate-row-preopen"') < newsRow.indexOf('candidate-entry'), 'the mark is not on the title line: under it, above the entry sentence')
check(rowOf(newsPage, 1).includes('<span class="tone-down">可能負向 1</span>'), 'the negative count in the falling colour')
check(!rowOf(newsPage, 2).includes('candidate-row-preopen'), 'a row without overnight news has no mark')
const newsPanel = panelOf(detailOf(rowOf(newsPage, 1)))
check(newsPanel.startsWith('隔夜新聞（開盤前檢查 2026/11/16 08:20）名單產生之後才收到的新聞'), `the detail's heading and the definition (decision 6888598143): ${newsPanel}`)
check(newsPanel.includes('2026/11/15 22:40 微星下修全年出貨目標 鉅亨 可能負向（AI 推論）'), `a line: time, title, source, the AI direction marked （AI 推論）: ${newsPanel}`)
check(newsPanel.includes('2026/11/16 07:10 微星 AI 伺服器接單 中央社 可能正向（AI 推論）'), 'the positive one')
check(newsPanel.includes('2026/11/16 微星董事會決議 公開資訊觀測站 尚未判讀'), `a date-only item and one not judged yet: ${newsPanel}`)
check(rowOf(newsPage, 1).includes('href="https://news.cnyes.com/news/id/30701"'), 'the title links to the source')
check(panelOf(detailOf(rowOf(newsPage, 2))).startsWith('隔夜新聞 無（開盤前檢查 2026/11/16 08:20）'), 'a checked row without news says 無 with the check time')
// From 1280px: the chosen row's news under its chart, not in the details.
const wideNews = render(<TodayCandidateList items={withPreopen().items} wide renderChart={() => <div className="fake-chart" />} preopen={preopenChecked()} />)
const aside = slice(wideNews, '<aside', '</aside>')
check(aside.indexOf('fake-chart') >= 0 && aside.indexOf('fake-chart') < aside.indexOf('class="preopen-news"') && panelOf(aside).includes('微星下修全年出貨目標'), 'beside the list: the chosen candidate\'s news under its chart')
check(count(wideNews, 'class="preopen-news"') === 1, 'from 1280px the details have no panel of their own')
// None at all: the line says 0, no mark, every detail 無.
const nonePreopen = render(<CandidatesSection data={withPreopen(preopenChecked(0), [noPreopenNews(), noPreopenNews()])} loading={false} error={null} />)
check(preopenLineOf(nonePreopen) === '開盤前檢查 2026/11/16 08:20 · 隔夜新聞 0 檔' && !nonePreopen.includes('candidate-row-preopen'), `checked, no news: ${preopenLineOf(nonePreopen)}`)
check(panelOf(detailOf(rowOf(nonePreopen, 1))).startsWith('隔夜新聞 無（開盤前檢查 2026/11/16 08:20）'), 'checked, no news: the detail says 無')
// Not checked yet (before 08:20, or the list recomputed after the check): no older result stands in.
const pendingPreopen = render(<CandidatesSection data={withPreopen(preopenNotChecked(), [null, null])} loading={false} error={null} />)
check(preopenLineOf(pendingPreopen) === `開盤前檢查 ${PREOPEN_NOT_CHECKED}（每個交易日 08:20）`, `not checked: ${preopenLineOf(pendingPreopen)}`)
check(!pendingPreopen.includes('candidate-row-preopen') && panelOf(detailOf(rowOf(pendingPreopen, 1))).startsWith('隔夜新聞 尚未檢查名單產生之後才收到的新聞'), 'not checked: no mark, the detail says 尚未檢查')
// No line without a list, nor on a response from before Issue 755.
check(!render(<CandidatesSection data={{ ...zeroResponse('all_excluded'), preopen_check: preopenNotChecked() }} loading={false} error={null} />).includes('preopen-line'), 'a zero list has no line')
check(!plainList.includes('preopen'), 'a response without preopen_check shows nothing of it')
check(preopenRowMark({ ...preopenNews(), negative: 0 })?.negative === null && preopenRowMark(noPreopenNews()) === null && preopenRowMark(null) === null, 'no brackets without a negative one; no mark without news')
check(preopenCheckLine(undefined) === null, 'no line without preopen_check')

// ---- 主流族群前 20 (#769; UI_COPY_SPEC §10, DESIGN_SYSTEM §5 候選列表): the switch, the second list's rows and states ----
{
  const renderAt = (location: string, element: ReactElement, client = new QueryClient()) =>
    renderToStaticMarkup(<QueryClientProvider client={client}><StaticRouter location={location}>{element}</StaticRouter></QueryClientProvider>)
  const withMainstream = (data: MainstreamResponse) => {
    const client = new QueryClient()
    client.setQueryData(['mainstream', 'latest'], data)
    return client
  }
  const plain = (markup: string) => markup.replace(/<[^>]+>/g, '').replace(/&amp;/g, '&')
  const inner = (markup: string, start: string, end: string) => plain(slice(markup, start, end).replace(/^[^>]*>/, ''))
  const today = { data: listResponse(), loading: false, error: null }
  const tabOf = (markup: string, label: string) => markup.match(new RegExp(`<button[^>]*role="tab"[^>]*>${label}</button>`))?.[0] ?? ''

  // The switch and the address: ?list=mainstream opens the second list (a reload stays on it); anything else is 今日名單.
  check(todayListKind(new URLSearchParams('')) === 'today' && todayListKind(new URLSearchParams('list=mainstream')) === 'mainstream' && todayListKind(new URLSearchParams('list=other')) === 'today', 'only ?list=mainstream opens the second list')
  check(todayListSearch(new URLSearchParams('list=mainstream&pick=2330&x=1'), 'today').toString() === 'x=1' && todayListSearch(new URLSearchParams('x=1'), 'mainstream').toString() === 'x=1&list=mainstream', 'the tabs write the list to the address and drop a pick')
  check(JSON.stringify(TODAY_LISTS.map((list) => list.label)) === JSON.stringify(['今日名單', '主流族群前 20', '接近年高前 20']), 'three tabs, 今日名單 first (Issue 882)')
  const atToday = renderAt('/', <TodayListsSection today={today} />)
  check(tabOf(atToday, '今日名單').includes('aria-selected="true"') && tabOf(atToday, '主流族群前 20').includes('aria-selected="false"'), 'without ?list the page is on 今日名單')
  check(atToday.includes('id="candidates-title"') && !atToday.includes('mainstream-title') && atToday.indexOf('role="tablist"') < atToday.indexOf('id="candidates-title"'), 'the switch above the today list; the second list not rendered')
  check(atToday.includes('id="today-list-panel-today"') && atToday.includes('aria-labelledby="today-list-tab-today"'), 'the panel is labelled by its tab')
  // The today list itself does not change: the same page text as before the switch, after the two tab labels.
  check(plain(atToday) === '今日名單主流族群前 20接近年高前 20' + plain(render(<CandidatesSection data={listResponse()} loading={false} error={null} />)), 'the today list keeps its page text (page_checks T5–T8, T13)')
  const atMainstream = renderAt('/?list=mainstream', <TodayListsSection today={today} />, withMainstream(mainstreamResponse()))
  check(tabOf(atMainstream, '主流族群前 20').includes('aria-selected="true"') && tabOf(atMainstream, '今日名單').includes('aria-selected="false"'), '?list=mainstream selects the second tab')
  check(atMainstream.includes('id="mainstream-title"') && !atMainstream.includes('candidates-title') && atMainstream.includes('id="today-list-panel-mainstream"'), '?list=mainstream shows the second list instead of the today list')
  check(renderAt('/?list=mainstream', <TodayListsSection today={today} />).includes('主流族群前 20 載入中…'), 'the second list loads on its own')
  // /api/mainstream only on ?list=mainstream (decision 6893166683): a query observer with the page's options, the way
  // useQuery subscribes in the browser, calls the request only for the second list.
  const requests: string[] = []
  for (const kind of ['today', 'mainstream'] as const) {
    const observer = new QueryObserver(new QueryClient(), mainstreamQueryOptions(kind, () => { requests.push(kind); return Promise.resolve(mainstreamResponse()) }))
    observer.subscribe(() => undefined)()
  }
  check(JSON.stringify(requests) === JSON.stringify(['mainstream']), `the today list requests no /api/mainstream: ${requests.join(',')}`)
  // And the page wires them (review 6893655832 suggestion 2): the query the section builds is disabled on 今日名單.
  const enabledAt = (location: string) => {
    const client = new QueryClient()
    renderAt(location, <TodayListsSection today={today} />, client)
    return (client.getQueryCache().find({ queryKey: ['mainstream', 'latest'] })?.options as { enabled?: unknown } | undefined)?.enabled
  }
  check(enabledAt('/') === false && enabledAt('/?list=mainstream') === true, `the section's /api/mainstream query: ${enabledAt('/')} at /, ${enabledAt('/?list=mainstream')} at ?list=mainstream`)

  // computed: the head, the definition (W, G and the group names by rank, from the API) and the rows.
  const computed = render(<MainstreamSection data={mainstreamResponse()} loading={false} error={null} todayDate="2026-11-13" />)
  check(computed.includes('<h2 id="mainstream-title">主流族群前 20</h2>') && plain(computed).includes('2026/11/13') && plain(computed).includes('2 檔'), `the head: title, data date and count: ${plain(computed).slice(0, 60)}`)
  const definition = inner(computed, 'mainstream-definition', '</p>')
  check(definition === '近 240 個交易日相對加權指數最強的 3 個族群：半導體、AI 伺服器、電腦及週邊設備；族群內個股依 240 日漲幅取前 20', `the definition: ${definition}`)
  const fewer = plain(render(<MainstreamSection data={mainstreamResponse({ window: 120, group_count: 5 })} loading={false} error={null} />))
  check(fewer.includes('近 120 個交易日相對加權指數最強的 3 個族群（上限 5 個）') && fewer.includes('依 120 日漲幅') && fewer.includes('近 120 日 +45.67%'), `W and G come from the API, not 240/5: ${fewer.slice(0, 120)}`)
  const mRow = (markup: string, rank: number) => slice(markup, `data-mainstream-rank="${rank}"`, '</li>')
  const first = mRow(computed, 1)
  const second = mRow(computed, 2)
  const title = inner(first, '<p class="candidate-row-title"', '</p>')
  check(title === '#1 2330 台積電 上市 · 半導體、AI 伺服器', `the first line: rank, name, market and every chosen group by 頓號: ${title}`)
  const strength = inner(first, '<p class="mainstream-return"', '</p>')
  check(strength === '近 240 日 +45.67%（較加權 +12.34%）', `the strength line: ${strength}`)
  check(first.includes('mainstream-return-value tone-up') && plain(second).includes('（較加權 -1.23%）'), 'the return red up; a negative excess keeps its sign')
  check(plain(first).includes('收盤（元）1,085.00+1.40%') && first.includes('candidate-change tone-up') && second.includes('candidate-change tone-down') && plain(second).includes('230.50-0.86%'), `close and change, red up and green down: ${plain(second)}`)
  check(first.includes('class="sparkline sparkline-up"') && second.includes('class="sparkline sparkline-down"'), 'the today list\'s sparkline on recent_closes')
  check(signedPercent(-0.00004).text === '0.00%' && signedPercent(-0.00004).tone === 'flat' && signedPercent(null).text === '—', 'a flat or missing percent')

  // 「今日名單 #n」: only on a stock also on the day's today list; it opens the today list on that stock.
  check(todayListPickPath(mainstreamResponse().items[0]!) === '/?pick=2330', 'the mark links to the today list with the stock picked')
  check(first.includes('<a class="badge badge-compact mainstream-today-mark" data-today-rank="2" href="/?pick=2330">今日名單 #2</a>'), `the mark on a today-list stock: ${slice(first, 'mainstream-today-mark', '</a>')}`)
  check(!second.includes('mainstream-today-mark') && !plain(second).includes('今日名單'), 'no mark on a stock off the today list')
  // The two lists of different dates (review 6893655832): today_list is of the mainstream list's date, the page's today
  // list is the latest, so the mark is plain text with its date and never opens another day's row.
  const otherDay = mRow(render(<MainstreamSection data={mainstreamResponse()} loading={false} error={null} todayDate="2026-11-16" />), 1)
  check(!otherDay.includes('<a class="badge badge-compact mainstream-today-mark') && otherDay.includes('<span class="badge badge-compact mainstream-today-mark mainstream-today-mark-other" data-today-rank="2">2026/11/13 今日名單 #2</span>') && !otherDay.includes('pick='), `another day's today list: the mark is not a link: ${slice(otherDay, 'mainstream-today-mark', '</span>')}`)
  check(!mRow(render(<MainstreamSection data={mainstreamResponse()} loading={false} error={null} />), 1).includes('href="/?pick='), 'no link while the today list\'s date is unknown')
  check(todayListMark(mainstreamResponse().items[0]!, '2026-11-13', '2026-11-13T09:30:00+00:00')?.link === '/?pick=2330' && todayListMark(mainstreamResponse().items[1]!, '2026-11-13', '2026-11-13') === null, 'the same date links; no today_list, no mark')
  // The page passes the today list's date: the switch links only when the two responses are of the same day.
  const sameDayPage = renderAt('/?list=mainstream', <TodayListsSection today={{ ...today, data: { ...listResponse(), trading_date: '2026-11-13' } }} />, withMainstream(mainstreamResponse()))
  check(sameDayPage.includes('href="/?pick=2330">今日名單 #2</a>') && !atMainstream.includes('href="/?pick=') && plain(atMainstream).includes('2026/11/13 今日名單 #2'), 'the switch links the mark only when both lists are of the same date')
  // Where the click lands: the today list with the pick, its chart beside the list or its own card below 1280px.
  const long = { ...listResponse(), candidate_count: 12, items: Array.from({ length: 12 }, (_, index) => ({ ...completeItem(), rank: index + 1, instrument: { ...completeItem().instrument, id: 9000 + index, symbol: String(5001 + index) } })) }
  const picked: string[] = []
  const pickChart = (item: CandidateItem) => { picked.push(item.instrument.symbol); return <div data-test-chart={item.instrument.symbol} /> }
  const longToday = { ...today, data: long }
  const widePick = renderAt('/?pick=5003', <TodayListsSection today={longToday} renderChart={pickChart} wide />)
  check(widePick.includes('data-chart-rank="3"') && widePick.includes('data-test-chart="5003"') && (widePick.match(/aria-pressed="true"/g) ?? []).length === 1 && rowOf(widePick, 3).includes('aria-pressed="true"'), 'from 1280px the picked stock is the chart beside the list')
  picked.length = 0
  const narrowPick = renderAt('/?pick=5011', <TodayListsSection today={longToday} renderChart={pickChart} />)
  check(picked.join(',') === '5011' && rowOf(narrowPick, 11).includes('aria-expanded="true"') && narrowPick.includes('<details class="candidate-more" open=""'), `below 1280px the picked row's card is open, and past the first 10 the rest is shown: ${picked.join(',')}`)
  check(renderAt('/?pick=9999', <TodayListsSection today={longToday} renderChart={pickChart} wide />).includes('data-chart-rank="1"'), 'a pick not on the list leaves the default first row')

  // No price levels anywhere on the second list (decision 6891614350): no entry sentence, ladder, RR, total or 「可買」.
  const LEVEL_CLASSES = ['price-ladder', 'candidate-entry', 'entry-plan', 'candidate-row-levels', 'candidate-row-rr', 'candidate-rr', 'level-entry', 'level-stop', 'level-target', 'candidate-ai-toggle', 'candidate-detail', 'score-bar']
  const LEVEL_WORDS = ['進場', '停損', '目標', 'RR', '總分', '可買', '買進', '加入追蹤', '評分']
  for (const [label, markup] of [['computed', computed], ['switch', atMainstream]] as const) {
    const section = slice(markup, 'mainstream-title', '</section>')
    const classes = LEVEL_CLASSES.filter((name) => markup.includes(name))
    const words = LEVEL_WORDS.filter((word) => plain(section).includes(word))
    check(section !== '' && classes.length === 0 && words.length === 0, `${label}: no price-level element or word: ${classes.join(',')} ${words.join(',')}`)
  }

  // The chart: beside the list from 1280px (the first row's), a row's own card below, none mounted at first.
  const mCharts: string[] = []
  const mSpy = (item: MainstreamItem) => { mCharts.push(item.instrument.symbol); return <div data-test-chart={item.instrument.symbol} /> }
  const mWide = render(<MainstreamSection data={mainstreamResponse()} loading={false} error={null} renderChart={mSpy} wide todayDate="2026-11-13" />)
  check(mWide.includes('class="candidates-terminal"') && mWide.includes('data-chart-rank="1"') && mCharts.join(',') === '2330' && mRow(mWide, 1).includes('aria-pressed="true"'), `from 1280px the first stock's chart is beside the list: ${mCharts.join(',')}`)
  mCharts.length = 0
  const mNarrow = render(<MainstreamSection data={mainstreamResponse()} loading={false} error={null} renderChart={mSpy} todayDate="2026-11-13" />)
  check(mCharts.length === 0 && !mNarrow.includes('candidates-terminal') && mNarrow.includes('<div class="candidate-chart" id="mainstream-chart-1" hidden="">') && mRow(mNarrow, 1).includes('aria-expanded="false"'), 'below 1280px no chart mounts until a row opens its card')
  check(render(<MainstreamList items={mainstreamResponse().items} days={240} renderChart={mSpy} initialChartRank={2} />).includes('data-test-chart="6274"') && mCharts.join(',') === '6274', 'an open row mounts its own card')
  check(plain(mWide) === plain(computed) && plain(mNarrow) === plain(computed), 'the chart slot changes no page text')

  // missing and zero, written as the today list writes its empty states; missing has no universe_count or ranked_group_count.
  const missing = missingMainstream()
  check(!('universe_count' in missing) && !('ranked_group_count' in missing), 'the missing fixture is the API\'s _empty shape')
  const missingText = plain(render(<MainstreamSection data={missing} loading={false} error={null} />))
  check(mainstreamState(missing).kind === 'missing' && missingText.endsWith('尚無主流族群名單2026/11/13 尚未產生主流族群名單') && !missingText.includes(' 檔') && !missingText.includes('最強'), `missing: no definition, rows or count: ${missingText}`)
  check(plain(render(<MainstreamSection data={missingMainstream(null)} loading={false} error={null} />)) === '主流族群前 20尚無主流族群名單尚未產生主流族群名單', 'missing with no list at all: no date')
  const zeroText = plain(render(<MainstreamSection data={zeroMainstream()} loading={false} error={null} />))
  check(mainstreamState(zeroMainstream()).kind === 'zero' && zeroText.includes('2026/11/13') && zeroText.endsWith('當日沒有主流族群沒有族群有足夠的成員進入母體（母體 1,234 檔），當日不產生名單'), `zero: ${zeroText}`)
  const { universe_count: _universe, ...zeroWithout } = zeroMainstream()
  check(!JSON.stringify(mainstreamState(zeroWithout)).includes('undefined'), 'zero without universe_count still reads')
  check(mainstreamState({ ...mainstreamResponse(), items: [] }).kind === 'zero', 'computed with no rows reads as zero, not an empty list')
  check(plain(render(<MainstreamSection data={undefined} loading={false} error={new Error('API 500: boom')} />)).includes('API 500: boom'), 'a failed load gives its reason')
  check(mainstreamReturnText(mainstreamItem(1), 60) === '近 60 日 +49.00%（較加權 +29.00%）' && mainstreamGroupsText({ groups: [] }) === '無所屬主流族群', 'the text helpers')

  // The two layout fixes measured in the browser (PR 775, review 6893655832 suggestion 3), locked on the stylesheet: no
  // DOM here, and page_checks T26 measures only the close column. The groups wrap (no ellipsis cuts them) with a hanging
  // indent; below 640px the title spans the row and the sparkline and the close share the last line.
  const css = (require('node:fs') as { readFileSync(file: string, encoding: 'utf8'): string }).readFileSync(`${__dirname}/../styles/mainstream.css`, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
  const rule = (block: string, selector: string) => {
    const at = block.indexOf(`${selector} {`)
    return at < 0 ? '' : block.slice(at, block.indexOf('}', at))
  }
  const phone = css.slice(css.indexOf('@media (max-width: 640px)'))
  const wrapTitle = rule(css, '.candidate-row.mainstream-row .candidate-row-title')
  check(/white-space: normal/.test(wrapTitle) && /overflow: visible/.test(wrapTitle) && /text-overflow: clip/.test(wrapTitle) && /text-indent: -52px/.test(wrapTitle), `the title wraps instead of an ellipsis, hanging under the name: ${wrapTitle}`)
  check(/grid-column: 1 \/ -1/.test(rule(phone, '.candidate-row.mainstream-row .candidate-row-title')) && /text-indent: -42px/.test(rule(phone, '.candidate-row.mainstream-row .candidate-row-title')), 'below 640px the title spans the row')
  check(/grid-column: 1;/.test(rule(phone, '.candidate-row.mainstream-row .mainstream-row-figures')) && /grid-column: 2;/.test(rule(phone, '.candidate-row.mainstream-row .candidate-row-nums')), 'below 640px the sparkline and the close share one line')
}

// ---- 接近年高前 20 (#882; UI_COPY_SPEC §10, decision 7048604437): the third tab, its rows and states ----
{
  const renderAt = (location: string, element: ReactElement, client = new QueryClient()) =>
    renderToStaticMarkup(<QueryClientProvider client={client}><StaticRouter location={location}>{element}</StaticRouter></QueryClientProvider>)
  const withH2 = (data: H2Response) => {
    const client = new QueryClient()
    client.setQueryData(['h2', 'latest'], data)
    return client
  }
  const plain = (markup: string) => markup.replace(/<[^>]+>/g, '').replace(/&amp;/g, '&')
  const inner = (markup: string, start: string, end: string) => plain(slice(markup, start, end).replace(/^[^>]*>/, ''))
  const today = { data: listResponse(), loading: false, error: null }
  const tabOf = (markup: string, label: string) => markup.match(new RegExp(`<button[^>]*role="tab"[^>]*>${label}</button>`))?.[0] ?? ''

  // The switch and the address: ?list=h2 opens the third list (a reload stays on it); an unknown value is 今日名單.
  check(todayListKind(new URLSearchParams('list=h2')) === 'h2' && todayListKind(new URLSearchParams('list=H2')) === 'today' && todayListKind(new URLSearchParams('list=')) === 'today', 'only ?list=h2 opens the third list')
  check(todayListSearch(new URLSearchParams('list=mainstream&pick=2330&x=1'), 'h2').toString() === 'list=h2&x=1' && todayListSearch(new URLSearchParams('list=h2'), 'today').toString() === '' && todayListSearch(new URLSearchParams('list=h2'), 'mainstream').toString() === 'list=mainstream', 'the tabs write ?list=h2, and switch from it to the other two')
  const atH2 = renderAt('/?list=h2', <TodayListsSection today={today} />, withH2(h2Response()))
  check(tabOf(atH2, '接近年高前 20').includes('aria-selected="true"') && tabOf(atH2, '今日名單').includes('aria-selected="false"') && tabOf(atH2, '主流族群前 20').includes('aria-selected="false"'), '?list=h2 selects the third tab')
  check(atH2.includes('id="h2-title"') && !atH2.includes('candidates-title') && !atH2.includes('mainstream-title') && atH2.includes('id="today-list-panel-h2"') && atH2.includes('aria-labelledby="today-list-tab-h2"'), '?list=h2 shows the third list in its own panel')
  check(renderAt('/?list=h2', <TodayListsSection today={today} />).includes('接近年高前 20 載入中…'), 'the third list loads on its own')
  const atToday = renderAt('/', <TodayListsSection today={today} />)
  check(tabOf(atToday, '接近年高前 20').includes('aria-selected="false"') && !atToday.includes('h2-title'), 'without ?list the third list is not rendered')
  // /api/h2 only on ?list=h2: the page's options, subscribed as useQuery does, call the request only for the third list.
  const requests: string[] = []
  for (const kind of ['today', 'mainstream', 'h2'] as const) {
    const observer = new QueryObserver(new QueryClient(), h2QueryOptions(kind, () => { requests.push(kind); return Promise.resolve(h2Response()) }))
    observer.subscribe(() => undefined)()
  }
  check(JSON.stringify(requests) === JSON.stringify(['h2']), `only the third list requests /api/h2: ${requests.join(',')}`)
  const enabledAt = (location: string, key: string) => {
    const client = new QueryClient()
    renderAt(location, <TodayListsSection today={today} />, client)
    return (client.getQueryCache().find({ queryKey: [key, 'latest'] })?.options as { enabled?: unknown } | undefined)?.enabled
  }
  check(enabledAt('/', 'h2') === false && enabledAt('/?list=mainstream', 'h2') === false && enabledAt('/?list=h2', 'h2') === true && enabledAt('/?list=h2', 'mainstream') === false, 'the section queries /api/h2 only on ?list=h2, and /api/mainstream not there')

  // computed: the head, the definition (W and the universe from the API) and the rows.
  const computed = render(<H2Section data={h2Response()} loading={false} error={null} todayDate="2026-11-20" />)
  check(computed.includes('<h2 id="h2-title">接近年高前 20</h2>') && plain(computed).includes('2026/11/20') && plain(computed).includes('3 檔'), `the head: title, data date and count: ${plain(computed).slice(0, 60)}`)
  const definition = inner(computed, 'h2-definition', '</p>')
  check(definition === '收盤最接近一年高點（近 240 個交易日最高價，價格還原除權息）的 20 檔；母體 586 檔，20 日均量 1,000 張以上的上市櫃股票；以入選後 60 個交易日為觀察期', `the definition: ${definition}`)
  check(h2Definition({ window: 120, universe_count: 1234 }).includes('近 120 個交易日最高價') && h2Definition({ window: 120, universe_count: 1234 }).includes('母體 1,234 檔'), 'W and the universe come from the API')
  const hRow = (markup: string, rank: number) => slice(markup, `data-h2-rank="${rank}"`, '</li>')
  const first = hRow(computed, 1)
  const second = hRow(computed, 2)
  const third = hRow(computed, 3)
  check(inner(first, '<p class="candidate-row-title"', '</p>') === '#1 2330 台積電 上市' && inner(second, '<p class="candidate-row-title"', '</p>') === '#2 6274 台燿 上櫃', `the first line: rank, name and market, no group part: ${inner(first, '<p class="candidate-row-title"', '</p>')}`)
  check(first.includes('href="/stocks/TWSE/2330"'), 'the stock links to its page')
  const gap = (row: string) => inner(row, '<p class="mainstream-return h2-gap"', '</p>')
  check(gap(first) === '距一年高點 0.00%' && gap(second) === '距一年高點 -3.21%' && gap(third) === '距一年高點 —', `the distance line, two decimals, null as —: ${gap(first)} | ${gap(second)} | ${gap(third)}`)
  check(!/mainstream-return-value[^"]*tone-/.test(computed), 'the distance is not red or green')
  check(plain(first).includes('收盤（元）1,085.00+1.40%') && first.includes('candidate-change tone-up') && second.includes('candidate-change tone-down') && plain(second).includes('230.50-0.86%'), `close and change from market: ${plain(second)}`)
  check(first.includes('class="sparkline sparkline-up"') && second.includes('class="sparkline sparkline-down"'), 'the sparkline on recent_closes')
  check(h2GapText({ high_gap_240: -0.00004 }) === '0.00%' && h2GapText({ high_gap_240: -0.12345 }) === '-12.35%', 'the distance helper rounds to two decimals')

  // 「今日名單 #n」: a link on the same date, plain text with the list's date otherwise; none off the today list.
  check(first.includes('<a class="badge badge-compact mainstream-today-mark" data-today-rank="2" href="/?pick=2330">今日名單 #2</a>'), `the mark on a today-list stock: ${slice(first, 'mainstream-today-mark', '</a>')}`)
  check(!second.includes('mainstream-today-mark') && !plain(second).includes('今日名單'), 'no mark on a stock off the today list')
  const otherDay = hRow(render(<H2Section data={h2Response()} loading={false} error={null} todayDate="2026-11-23" />), 1)
  check(otherDay.includes('<span class="badge badge-compact mainstream-today-mark mainstream-today-mark-other" data-today-rank="2">2026/11/20 今日名單 #2</span>') && !otherDay.includes('pick='), "another day's today list: the mark is not a link")
  check(!atH2.includes('href="/?pick=') && plain(atH2).includes('2026/11/20 今日名單 #2'), "the page passes the today list's date: no link across dates")
  const sameDayPage = renderAt('/?list=h2', <TodayListsSection today={{ ...today, data: { ...listResponse(), trading_date: '2026-11-20' } }} />, withH2(h2Response()))
  check(sameDayPage.includes('href="/?pick=2330">今日名單 #2</a>'), 'the same date links the mark to the today list')

  // No price levels, research status or t anywhere on the third list (decision #1 7044998169, 6881314294).
  const LEVEL_CLASSES = ['price-ladder', 'candidate-entry', 'entry-plan', 'candidate-row-levels', 'candidate-row-rr', 'candidate-rr', 'level-entry', 'level-stop', 'level-target', 'candidate-ai-toggle', 'candidate-detail', 'score-bar']
  const LEVEL_WORDS = ['進場', '停損', '目標', 'RR', '總分', '可買', '買進', '持有', '加入追蹤', '評分', 'H2', 'X2', '研究', '回測', '驗證', 't 值', '勝率', '報酬']
  for (const [label, markup] of [['computed', computed], ['switch', atH2]] as const) {
    const section = slice(markup, 'h2-title', '</section>')
    const classes = LEVEL_CLASSES.filter((name) => markup.includes(name))
    const words = LEVEL_WORDS.filter((word) => plain(section).includes(word))
    check(section !== '' && classes.length === 0 && words.length === 0, `${label}: no price-level element or research word: ${classes.join(',')} ${words.join(',')}`)
  }

  // The chart: beside the list from 1280px, a row's own card below, none mounted at first.
  const hCharts: string[] = []
  const hSpy = (item: H2Item) => { hCharts.push(item.instrument.symbol); return <div data-test-chart={item.instrument.symbol} /> }
  const hWide = render(<H2Section data={h2Response()} loading={false} error={null} renderChart={hSpy} wide todayDate="2026-11-20" />)
  check(hWide.includes('class="candidates-terminal"') && hWide.includes('data-chart-rank="1"') && hCharts.join(',') === '2330' && hRow(hWide, 1).includes('aria-pressed="true"'), `from 1280px the first stock's chart is beside the list: ${hCharts.join(',')}`)
  hCharts.length = 0
  const hNarrow = render(<H2Section data={h2Response()} loading={false} error={null} renderChart={hSpy} todayDate="2026-11-20" />)
  check(hCharts.length === 0 && !hNarrow.includes('candidates-terminal') && hNarrow.includes('<div class="candidate-chart" id="h2-chart-1" hidden="">') && hRow(hNarrow, 1).includes('aria-expanded="false"'), 'below 1280px no chart mounts until a row opens its card')
  check(render(<H2List items={h2Response().items} renderChart={hSpy} initialChartRank={2} />).includes('data-test-chart="6274"') && hCharts.join(',') === '6274', 'an open row mounts its own card')
  check(plain(hWide) === plain(computed) && plain(hNarrow) === plain(computed), 'the chart slot changes no page text')
  const pageChart = renderAt('/?list=h2', <TodayListsSection today={today} renderMainstreamChart={(item) => <div data-test-chart={item.instrument.symbol} />} wide />, withH2(h2Response()))
  check(pageChart.includes('data-test-chart="2330"'), 'the page passes its K-line card to the third list too')

  // missing, zero, loading and a failed load.
  const missingText = plain(render(<H2Section data={missingH2()} loading={false} error={null} />))
  check(h2State(missingH2()).kind === 'missing' && missingText === '接近年高前 20資料 2026/11/20尚無接近年高名單2026/11/20 尚未產生接近年高名單', `missing: no definition, rows or count: ${missingText}`)
  check(plain(render(<H2Section data={missingH2(null)} loading={false} error={null} />)) === '接近年高前 20尚無接近年高名單尚未產生接近年高名單', 'missing with no list at all: no date')
  const zeroText = plain(render(<H2Section data={zeroH2()} loading={false} error={null} />))
  check(h2State(zeroH2()).kind === 'zero' && zeroText === '接近年高前 20資料 2026/11/20當日沒有股票進入母體沒有上市櫃股票的 20 日均量達 1,000 張，當日不產生名單', `zero: ${zeroText}`)
  check(h2State({ ...h2Response(), items: [] }).kind === 'zero', 'computed with no rows reads as zero, not an empty list')
  check(plain(render(<H2Section data={undefined} loading error={null} />)).includes('接近年高前 20 載入中…'), 'loading')
  const failed = plain(render(<H2Section data={undefined} loading={false} error={new Error('API 500: boom')} />))
  check(failed.includes('資料暫時無法載入') && failed.includes('API 500: boom'), `a failed load gives its reason: ${failed}`)
}
