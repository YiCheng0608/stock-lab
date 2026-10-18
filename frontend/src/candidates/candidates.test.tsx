import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'

import {
  CANDIDATE_DISCLAIMER,
  NOTE_DISCLAIMER,
  NOTE_MISSING_TEXT,
  NOTE_PENDING_TEXT,
  NOT_COMPUTED_TEXT,
  PARTIAL_NOTE,
  candidateGroupText,
  candidateNoteMeta,
  candidateNoteView,
  candidateSourceText,
  candidatesPath,
  candidatesState,
  formatCandidateScore,
  formatEntryZone,
  formatSubItemValue,
  marketSourceLabel,
} from './candidates'
import { completeItem, doneNote, listResponse, notComputedResponse, partialItem, zeroResponse } from './candidates.fixtures'
import { CandidateCard, CandidatesSection, StockCandidatePanel } from './CandidateViews'

// Standalone regression module (no browser, no server, no network) for the daily candidate list (#215):
// the today section, partial components, zero and not-computed runs, and the stock page panel.
const check = (condition: boolean, message: string) => { if (!condition) throw new Error(message) }
const render = (element: ReactElement) => renderToStaticMarkup(<StaticRouter location="/">{element}</StaticRouter>)
const count = (markup: string, needle: string) => markup.split(needle).length - 1
const slice = (markup: string, start: string, end: string) => {
  const from = markup.indexOf(start)
  return from < 0 ? '' : markup.slice(from, markup.indexOf(end, from + start.length))
}

// ---- request parameters ----
check(candidatesPath() === '/candidates', 'no date asks for the latest run')
check(candidatesPath('2026-10-16', 10) === '/candidates?date=2026-10-16&limit=10', 'date and limit are passed through')

// ---- formatting ----
check(formatCandidateScore(0.827566) === '83' && formatCandidateScore(0) === '0' && formatCandidateScore(null) === '—', 'scores on 0–100, null is 「—」 never 0')
check(formatEntryZone(completeItem().levels) === '161.50', 'breakout entry zone collapses to one price')
check(formatEntryZone(partialItem().levels) === '13.05～13.35', 'pullback entry zone shows low～high')
check(formatSubItemValue('margin_change_5d', -0.0592) === '-5.9%' && formatSubItemValue('volume_ratio', 2.8847) === '2.88 倍', 'sub-item units')
check(formatSubItemValue('net_direction', null) === '—', 'null sub-item is 「—」')
check(marketSourceLabel('tpex_3insti+tpex_margin') === '證券櫃檯買賣中心' && marketSourceLabel(null) === '來源未提供', 'market sources are named')
check(candidateGroupText(completeItem().groups[0]) === 'AI 伺服器（題材，第 2 名／11）', 'ranked group shows board and rank')
check(candidateGroupText(completeItem().groups[1]) === '電腦及週邊（產業，當日未排名）', 'unranked group says so')
check(candidateSourceText(completeItem()).includes('新聞方向 LLM 判讀 news_v1（推論）'), 'news source names the prompt version and is inference')

// ---- normal list ----
const list = render(<CandidatesSection data={listResponse()} loading={false} error={null} />)
check(list.includes('明日候選') && list.includes(CANDIDATE_DISCLAIMER), 'section title and the fixed disclaimer')
check(list.includes('資料 2026/10/16') && list.includes('2 檔'), 'run date badge and candidate count')
check(count(list, 'class="card candidate-card"') === 2, 'one card per candidate')
const first = slice(list, 'data-candidate-rank="1"', '</article>')
for (const text of ['#1', '2377', '微星', '上市', '突破條件', '>83<', '161.50', '157.82', '167.39', '172.54', '1.60', 'href="/stocks/TWSE/2377"']) {
  check(first.includes(text), `complete row shows ${text}`)
}
check(first.includes('class="level-stop">157.82') && first.includes('class="level-target">167.39'), 'stop and target carry their colours')
check(!first.includes(PARTIAL_NOTE) && !first.includes('candidate-null-notes'), 'complete row has no partial note')
for (const [component, score] of [['technical', '74'], ['chips', '92'], ['news_sentiment', '81'], ['group', '90']]) {
  check(slice(first, `data-component="${component}"`, '</div>').includes(`>${score}<`), `component ${component} shows ${score}`)
}
check(slice(first, 'data-component="news_sentiment"', '</div>').includes('badge-accent') && !slice(first, 'data-component="chips"', '</div>').includes('badge-accent'), 'only news sentiment is marked 推論')
check(count(first, 'data-reason=') === 4, 'all four API reasons are shown')
check(first.indexOf('institutional_net_buy_5d') < first.indexOf('breakout_20d_high'), 'reasons keep the API order')
for (const [code, dot] of [['breakout_20d_high', 'technical'], ['institutional_net_buy_5d', 'chips'], ['news_positive_3d', 'news_sentiment'], ['hot_group_rank', 'group']]) {
  check(slice(first, `data-reason="${code}"`, '</li>').includes(`reason-dot-${dot}`), `${code} has the ${dot} dot`)
}
check(slice(first, 'data-reason="news_positive_3d"', '</li>').includes('badge-accent'), 'inference reason carries the 推論 badge on its row')
check(!slice(first, 'data-reason="breakout_20d_high"', '</li>').includes('badge-accent'), 'fact reasons carry no 推論 badge')
check(first.includes('族群：AI 伺服器（題材，第 2 名／11）、電腦及週邊（產業，當日未排名）'), 'groups listed')
check(first.includes('<details class="details candidate-details">'), 'score details collapsed on the today list')
check(first.includes('同檔另一策略：回踩條件 總分 61') && first.includes('規則最早執行日 2026/10/19'), 'alternatives and earliest execution date in details')
check(first.includes('資料日期 2026/10/16') && first.includes('臺灣證券交易所'), 'data date and sources in details')

// ---- partial components ----
const second = slice(list, 'data-candidate-rank="2"', '</article>')
check(second.includes(PARTIAL_NOTE), 'partial row explains the renormalised score')
check(slice(second, 'data-component="group"', '</div>').includes('>—<') && slice(second, 'data-component="news_sentiment"', '</div>').includes('>—<'), 'null components show 「—」')
check(!slice(second, 'data-component="group"', '</div>').includes('>0<'), 'null component is never 0')
check(second.includes('族群：當日沒有已排名且資料完整的所屬產業或題材') && second.includes('新聞情緒：近 3 日沒有成功的新聞收集，新聞分項無資料'), 'null_explanation shown next to the scores')
check(second.includes('13.05～13.35') && second.includes('上櫃') && second.includes('回踩條件'), 'pullback zone and TPEx label')
check(!second.includes('level-target-2'), 'missing target 2 is not rendered')
check(second.includes('權重涵蓋 65%'), 'weight coverage in details')
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
check(note.includes('模型 claude-sonnet-5-5 · 提示版本 candidate_notes_v1 · 產生於 2026/10/16 19:05'), 'model, prompt version and Taipei time')
check(first.indexOf('candidate-groups') < first.indexOf('candidate-note') && first.indexOf('candidate-note') < first.indexOf('candidate-details'), 'note sits after the rule reasons and groups, before the score details')
check(!slice(first, 'class="candidate-levels"', '</dl>').includes('ai-inference'), 'rule levels stay outside the AI block')
const missing = slice(second, 'class="ai-inference candidate-note"', '</section>')
check(missing.includes('data-note-state="empty"') && missing.includes(NOTE_MISSING_TEXT) && !missing.includes('data-note-part') && !missing.includes('ai-meta'), 'a row without a note shows the fixed copy')
const pending = candidateNoteView({ ...doneNote(), status: 'pending', selection: null, levels: null, risks: null })
check(pending.kind === 'empty' && pending.text === NOTE_PENDING_TEXT && pending.meta?.includes('提示版本 candidate_notes_v1') === true, 'a pending note shows the retry copy and its version')
check(candidateNoteView({ ...doneNote(), risks: '' }).kind === 'empty', 'a done note missing a part is not shown half-filled')
check(candidateNoteView(null).kind === 'empty' && candidateNoteView(undefined).kind === 'empty', 'null and missing notes use the fixed copy')
check(candidateNoteMeta({ ...doneNote(), model: null, generated_at: '2026-10-16T11:05:00' }) === '模型 未記錄 · 提示版本 candidate_notes_v1', 'unknown model and a time without offset')
check(render(<StockCandidatePanel candidate={completeItem()} />).includes('data-note-state="done"'), 'stock panel shows the note too')

// ---- zero candidates and not computed ----
for (const reason of ['no_actionable_signals', 'all_excluded'] as const) {
  const data = zeroResponse(reason)
  const markup = render(<CandidatesSection data={data} loading={false} error={null} />)
  check(markup.includes(data.zero_reason_text ?? '?') && markup.includes('當日零候選'), `zero run ${reason} shows zero_reason_text`)
  check(!markup.includes('candidate-card') && markup.includes('資料 2026/10/16') && !markup.includes('0 檔'), `zero run ${reason} keeps the date badge only`)
  check(candidatesState({ ...data, zero_reason_text: null }).kind === 'zero' && (candidatesState({ ...data, zero_reason_text: null }) as { text: string }).text === data.zero_reason_text, `zero ${reason} falls back to the §10 copy`)
}
const notComputed = render(<CandidatesSection data={notComputedResponse()} loading={false} error={null} />)
check(notComputed.includes(NOT_COMPUTED_TEXT) && notComputed.includes('尚無候選清單') && !notComputed.includes('date-badge'), 'not_computed copy without a date badge')
check(notComputed.includes(CANDIDATE_DISCLAIMER), 'disclaimer stays on top for every state')

// ---- loading and error ----
check(render(<CandidatesSection data={undefined} loading error={null} />).includes('明日候選載入中…'), 'loading skeleton')
check(render(<CandidatesSection data={undefined} loading={false} error={new Error('API 500: boom')} />).includes('API 500: boom'), 'error reason shown')

// ---- stock page ----
check(render(<StockCandidatePanel candidate={null} />) === '' && render(<StockCandidatePanel candidate={undefined} />) === '', 'no candidate renders nothing on the stock page')
const panel = render(<StockCandidatePanel candidate={partialItem()} />)
check(panel.includes('每日候選 · 第 2 名') && panel.includes('明日候選') && panel.includes(CANDIDATE_DISCLAIMER), 'stock panel heading with rank and disclaimer')
check(panel.includes('<details class="details candidate-details" open="">'), 'stock panel opens the score details')
check(!panel.includes('href="/stocks/'), 'stock panel does not link to itself')
check(panel.includes(PARTIAL_NOTE) && panel.includes('資料 2026/10/16'), 'stock panel keeps partial note and date')

// The card alone stays usable without a router link.
check(render(<CandidateCard item={completeItem()} linkToStock={false} />).includes('<span><strong>2377</strong> 微星</span>'), 'card renders the name without a link')
