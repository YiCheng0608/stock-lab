import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import * as AppModule from '../App'
import * as ActionModule from '../actions/ActionViews'
import * as CandidateModule from '../candidates/CandidateViews'
import { NOTE_DISCLAIMER, NOTE_MISSING_TEXT, NOTE_PENDING_TEXT, NOT_COMPUTED_TEXT, candidateChange, candidateSourceText } from '../candidates/candidates'
import { completeItem, listResponse, longList, notComputedResponse, partialItem, zeroResponse } from '../candidates/candidates.fixtures'
import type { ActionSummary, AiListPick } from '../types'
import * as TodayModule from './TodayViews'
import { aiListDone, aiPick, overviewBoth, overviewNone, overviewTwseOnly, riskActions } from './today.fixtures'
import * as AiListModule from './AiListSection'
import { AI_LIST_ERROR, AI_LIST_LOADING, AI_LIST_MARK, AI_LIST_MISSING, AI_LIST_TITLE, aiChartLevels } from './aiList'
import { levelsNote } from '../stock/stockBars'
import { StrategyBoardPanel } from '../stock/StrategyBoardPanel'
import { board, conditionalBreakout, observationPullback } from '../stock/strategyBoard.fixtures'
import { removedCopyIn } from '../removedCopy.fixtures'

// The frontend ships no Node typings; scripts/ci-test.cjs runs this module under Node, so declare what it uses.
declare const require: (id: string) => unknown
declare const __dirname: string
const fs = require('node:fs') as { readFileSync(file: string, encoding: 'utf8'): string }
const path = require('node:path') as { join(...parts: string[]): string }

// Today page redesign and level colours (#276; PRODUCT_SPEC §2, DESIGN_SYSTEM §4/§5/§7, UI_COPY_SPEC §10/§11).
// Every check runs and the failures are listed together, so one run shows each place that is off.
const failures: string[] = []
let checks = 0
const check = (condition: boolean, message: string) => { checks++; if (!condition) failures.push(message) }
type Props = Record<string, unknown>
const component = (module: Record<string, unknown>, name: string) =>
  (module[name] ?? (() => { throw new Error(`does not export ${name}`) })) as (props: Props) => ReactElement | null
const render = (name: string, element: () => ReactElement): string => {
  try {
    const client = new QueryClient()
    return renderToStaticMarkup(<QueryClientProvider client={client}><StaticRouter location="/">{element()}</StaticRouter></QueryClientProvider>)
  } catch (error) {
    checks++
    failures.push(`${name}: render failed (${error instanceof Error ? error.message.split('\n')[0] : String(error)})`)
    return ''
  }
}
const text = (markup: string) => markup.replace(/<[^>]+>/g, '')
const count = (markup: string, needle: string) => markup.split(needle).length - 1
const slice = (markup: string, start: string, end: string) => {
  const from = markup.indexOf(start)
  return from < 0 ? '' : markup.slice(from, markup.indexOf(end, from + start.length))
}
const termIds = (markup: string) => [...markup.matchAll(/data-term="([^"]+)"/g)].map((match) => match[1])

const MarketSummaryLine = component(TodayModule, 'MarketSummaryLine')
const TodayHeader = component(TodayModule, 'TodayHeader')
const HoldingAlert = component(TodayModule, 'HoldingAlert')
const CandidatesSection = component(CandidateModule, 'CandidatesSection')

// ---- market summary (Issue 549, UI_COPY_SPEC §11): one line of 加權 and 櫃買, the date and 看大盤 →; the overview is on /market ----
const summary = render('MarketSummaryLine both', () => <MarketSummaryLine overview={overviewBoth()} />)
const summaryText = text(summary)
const order = ['大盤', '加權 46,041.43 -1.81%', '櫃買 381.69 -3.47%', '資料 2026/10/22', '看大盤 →'].map((part) => summaryText.indexOf(part))
check(order.every((at, i) => at >= 0 && (i === 0 || at > order[i - 1])), `摘要列: 大盤 → 加權 → 櫃買 → date → 看大盤 →, got 「${summaryText}」`)
check(summary.includes('href="/market"'), '摘要列: 看大盤 → links to /market')
check(count(summary, 'tone-down') === 2, '摘要列: falling changes are green')
check(!summary.includes('market-widget') && !text(summary).includes('成交金額') && !text(summary).includes('上漲'), '摘要列: no widgets, turnover or breadth (they are on /market)')
check(/<section class="market-summary" aria-label="大盤摘要">/.test(summary), '摘要列: one framed section')
const summaryTwse = text(render('MarketSummaryLine TWSE only', () => <MarketSummaryLine overview={overviewTwseOnly()} />))
check(summaryTwse.includes('46,041.43') && summaryTwse.includes('櫃買 未取得') && !summaryTwse.includes('381.69'), `摘要列（只有上市）: 櫃買 未取得, got ${summaryTwse}`)
for (const [name, overview] of [['都沒有', overviewNone()], ['欄位不存在', undefined]] as const) {
  const none = text(render(`MarketSummaryLine ${name}`, () => <MarketSummaryLine overview={overview} />))
  check(none.includes('加權 未取得') && none.includes('櫃買 未取得') && !/\d,\d{3}\.\d{2}/.test(none) && none.includes('看大盤 →'), `摘要列（${name}）: both 未取得, still links to /market`)
}
check(text(render('MarketSummaryLine no field', () => <MarketSummaryLine overview={undefined} />)).includes('資料日期未提供'), '摘要列: no overview → 資料日期未提供')

// ---- header line and 資料說明: red/green meaning; no method note (the turnover scope moved to /market) ----
const headerProps = { asOf: '2026-10-22T10:30:00+00:00', sourceLabel: 'TWSE／TPEx 官方資料', modeLabel: '官方單日快照', badge: <span className="pill complete">行情來源完整</span>, scopeText: '官方標的範圍 · 1,950 檔標的' }
const header = render('TodayHeader', () => <TodayHeader {...headerProps} />)
check(text(slice(header, 'class="home-dataline-text"', '</span>')).includes('資料截至 2026/10/22 · TWSE／TPEx 官方資料 · 官方單日快照'), 'header: one line 「資料截至 2026/10/22 · 來源 · 模式」')
const explanation = text(slice(header, '<details', '</details>'))
check(!explanation.includes('成交金額範圍'), `資料說明: the turnover scope is on /market now, got ${explanation}`)
// No method note for a derived TPEx change (Issue 747, #732 N-5); the header no longer reads the overview, and verify
// T23 checks the fixture page, whose TPEx change is derived.
check(!removedCopyIn(header).length && !explanation.includes('櫃買指數漲跌幅'), `資料說明: no method note for the derived TPEx change (Issue 747), got ${explanation}`)
check(explanation.includes('紅色為上漲、綠色為下跌（台股慣例）'), '資料說明: red is up and green is down')
check(!/hero|glow/.test(header), 'header: no hero or glow (DESIGN_SYSTEM §1)')
check(/<h1 class="sr-only">今日<\/h1>/.test(header), 'header: the page still has an h1 for assistive tech')
// Without a dashboard (load failed) the line has no empty source or mode parts.
const failed = text(slice(render('TodayHeader failed', () => <TodayHeader asOf={null} sourceLabel="" modeLabel="" />), 'class="home-dataline-text"', '</span>'))
check(failed.endsWith('資料截至 未提供') && !failed.includes('·'), `header: a failed load reads 「資料截至 未提供」, got 「${failed}」`)

// ---- holding-risk alert row: only verified holding risks, linked to the action centre ----
const alert = render('HoldingAlert', () => <HoldingAlert actions={riskActions()} />)
check(text(alert).includes('持倉風險 4 檔：2330 台積電：減碼／退場條件；1101 台泥：持倉風險資料不足；2882 國泰金：庫存數量待核實 等 4 檔'), `持倉提示列: count, first three holdings and reasons, got ${text(alert)}`)
check(alert.includes('href="/watch"') && text(alert).includes('查看我的追蹤 →'), '持倉提示列: links to /watch (Issue 493)')
check(!text(alert).includes('長榮') && !text(alert).includes('鴻海'), '持倉提示列: not-held rows are no holding risk')
const noRisk = render('HoldingAlert none', () => <HoldingAlert actions={riskActions().filter((item: ActionSummary) => !item.held)} />)
check(noRisk === '', `持倉提示列: nothing when no holding is at risk, got ${text(noRisk)}`)

// ---- candidates (Issue 510; DESIGN_SYSTEM §5 候選列表): one list at every width, two lines a candidate, top 10 plus the rest ----
const long = render('CandidatesSection long', () => <CandidatesSection data={longList()} loading={false} error={null} />)
const list = slice(long, '<ol class="candidate-list"', '</ol>')
// One row: from its data-candidate-rank to the next row (a row holds nested <li> of reasons and conditions).
const rowOf = (markup: string, rank: number) => {
  const from = markup.indexOf(`data-candidate-rank="${rank}"`)
  if (from < 0) return ''
  const next = markup.indexOf('data-candidate-rank=', from + 1)
  return markup.slice(from, next < 0 ? markup.indexOf('</ol>', from) : next)
}
const mainOf = (row: string) => slice(row, 'class="candidate-row-main"', '<details class="candidate-detail"')
const detailOf = (row: string) => row.slice(row.indexOf('<details class="candidate-detail"'))
check(list.length > 0 && !long.includes('<table') && !long.includes('candidate-mini') && !long.includes('candidate-cards'), 'Issue 510: one list, no table and no phone cards')
check(count(list, '<li class="candidate-row') === 12, `list: one row per candidate, got ${count(list, '<li class="candidate-row')}`)
check(count(list, 'hidden=""') === 2 && rowOf(list, 11).includes('hidden=""') && !rowOf(list, 10).includes('hidden=""'), 'list: the first 10 rows show, the last 2 are folded')
check(text(slice(long, 'class="candidate-more"', '</details>')).includes('顯示其餘 2 檔'), 'list: 「顯示其餘 2 檔」 folds the rest')
check(text(long).includes('2026/10/16 收盤後條件成立') && !text(long).includes('才可研究進場') && !text(long).includes('評分只用於排序'), 'list: the day the conditions held, without the T+1 clause or the disclaimer (Issue 729)')
check(!removedCopyIn(long).length, `list: removed copy is back: ${removedCopyIn(long).join('、')}`)
// The head is one line (Issue 510): no eyebrow; title, date badge, count, the notes and 策略說明 in one flex row.
const head = slice(long, 'class="candidates-head"', '<ol')
check(!head.includes('eyebrow') && head.includes('id="candidates-title">今日名單</h2>') && head.includes('href="/strategy"'), 'Issue 510: the head has no eyebrow, the title and 策略說明 are in it')
check(head.indexOf('今日名單</h2>') < head.indexOf('資料 2026/10/16') && head.indexOf('資料 2026/10/16') < head.indexOf('12 檔') && head.indexOf('12 檔') < head.indexOf('收盤後條件成立'), 'Issue 510: title → date → count → notes in the head')
// AC-2: each row shows the name, the entry sentence (with its stop and target) and the levels' classes; the reason and
// the average volume moved into the detail.
const main1 = mainOf(rowOf(list, 1))
check(/^#1 2377 微星 上市 · AI 伺服器（題材 #2）$/.test(text(slice(main1, '<p class="candidate-row-title"', '</p>') + '</p>').trim()), `row #1: one title line 「#1 2377 微星 上市 · 族群」, got 「${text(slice(main1, '<p class="candidate-row-title"', '</p>'))}」`)
for (const value of ['突破型', '161.50 元', '157.82 元', '167.39 元', '162.00', '+2.21%', '1.60 倍', '83', 'AI 推論 ▸']) check(text(main1).includes(value), `row #1: shows 「${value}」`)
check(main1.includes('href="/stocks/TWSE/2377"'), 'row #1: the name links to the stock page')
check(/class="level-stop">157\.82 元/.test(main1) && /class="level-target">167\.39 元/.test(main1), 'row #1: stop and target carry the level classes')
check(!text(main1).includes('三大法人 5 日淨買超') && !main1.includes('candidate-reasons'), 'Issue 510: no reason on the row (it is in the detail)')
check(!main1.includes('entry-plan-conditions'), 'row #1: the folded conditions are in the detail, not the row')
check(!/candidate-row-levels/.test(main1), 'row #1: the sentence has the levels, so no level cells repeat it (decision 6647903049)')
// #463: the row's numbers name 元 and the total its 0–100 scale; RR and 總分 open their terms.
const nums1 = slice(main1, '<dl class="candidate-row-nums"', '</dl>')
for (const label of ['收盤（元）', 'RR', '總分（0–100）']) check(text(nums1).includes(label), `row nums: 「${label}」, got ${text(nums1)}`)
for (const id of ['rr', 'candidate_score']) check(termIds(nums1).includes(id), `row nums: ${id} opens its glossary term`)
for (const id of ['support', 'target']) check(termIds(main1).includes(id), `row #1: the sentence's ${id} opens its glossary term`)
const main2 = mainOf(rowOf(list, 2))
check(text(main2).includes('13.20') && text(main2).includes('漲跌待核實') && text(main2).includes('13.05～13.35') && text(main2).includes('上櫃') && text(main2).includes('回踩型'), 'row #2: pullback zone, TPEx, and an unverified change reads 漲跌待核實')
check(text(mainOf(rowOf(list, 4))).includes('-1.50%'), 'row #4: a falling close shows a signed change')
// #465: no close on the previous session the source published (no trade, suspended or newly listed) says so, not 待核實.
const noPreviousClose = candidateChange({ trading_date: '2026-10-16', close: 13.2, change: null, change_pct: null, change_status: 'no_previous_close', source: 'tpex' })
check(noPreviousClose.text === '前一交易日無收盤' && noPreviousClose.tone === null, `no previous close: ${noPreviousClose.text}`)
// #475: a new listing's first day says so instead.
const firstTradingDay = candidateChange({ trading_date: '2026-10-16', close: 13.2, change: null, change_pct: null, change_status: 'first_trading_day', source: 'tpex' })
check(firstTradingDay.text === '掛牌首日' && firstTradingDay.tone === null, `first trading day: ${firstTradingDay.text}`)
check(text(mainOf(rowOf(list, 5))).includes('待核實'), 'row #5: no bar on the day reads 待核實')
// AI entry: a note (done or pending) is 「AI 推論 ▸」, none is 「AI 說明 ▸」; one entry per row (page_checks T8).
check(text(mainOf(rowOf(list, 2))).includes('AI 說明 ▸') && !text(mainOf(rowOf(list, 2))).includes('AI 推論 ▸'), 'AI entry: no note → 「AI 說明 ▸」')
check(text(mainOf(rowOf(list, 3))).includes('AI 推論 ▸'), 'AI entry: pending note → 「AI 推論 ▸」')
check(count(text(list), 'AI 推論 ▸') + count(text(list), 'AI 說明 ▸') === 12, 'one AI entry per candidate')
check(/<button[^>]*aria-expanded="false"[^>]*aria-controls="candidate-detail-1"/.test(main1), 'the AI entry is a button that controls the row\'s detail')
// AC-2: the detail opens with the AI note, its 為何入選 first; the levels and 加入追蹤 beside it; the facts folded under.
const detail1 = detailOf(rowOf(list, 1))
const body1 = slice(detail1, 'class="candidate-detail-body"', 'class="candidate-detail-side"')
check(/^class="candidate-detail-body"><section class="ai-inference candidate-note"/.test(body1), `Issue 510: the detail's first block is the AI note, got ${body1.slice(0, 120)}`)
check(body1.indexOf('data-note-part="selection"') > 0 && body1.indexOf('data-note-part="selection"') < body1.indexOf('data-note-part="levels"') && body1.indexOf('data-note-part="levels"') < body1.indexOf('data-note-part="risks"'), 'Issue 510: the note reads 為何入選 → 進場區、停損與目標 → 需留意的風險')
check(detail1.includes('data-note-state="done"') && detail1.includes(NOTE_DISCLAIMER), 'detail #1: the done AI note with its disclaimer')
const side1 = slice(detail1, 'class="candidate-detail-side"', 'class="candidate-detail-folds"')
check(!side1.includes('ai-inference') && /class="level-entry">161\.50</.test(side1) && /class="level-stop">157\.82</.test(side1) && /class="level-target">167\.39</.test(side1) && text(side1).includes('1.60 倍'), 'Issue 510: the rule levels and RR sit beside the note, outside the AI block')
for (const label of ['進場區（元）', '停損（元）', '目標一／二（元）', 'RR']) check(text(side1).includes(label), `detail levels: 「${label}」, got ${text(side1)}`)
check(text(side1).includes('加入追蹤') && side1.includes('href="/stocks/TWSE/2377"') && text(side1).includes('評分細節 → 個股頁'), 'detail #1: 加入追蹤 and the stock-page link beside the note')
const folds1 = detail1.slice(detail1.indexOf('class="candidate-detail-folds"'))
for (const summary of ['完整條件（2026/10/16 判定）', '分項分數與理由', '資料日期與來源']) check(folds1.includes(`<summary>${summary}</summary>`), `Issue 510: 「${summary}」 is folded under the note`)
check(!/<details[^>]*open/.test(folds1), 'the three folds are closed by default')
check(count(folds1, 'data-reason=') === 4 && folds1.includes('data-component="technical"'), 'detail #1: every reason and the four components in 分項分數與理由')
check(text(folds1).includes('資料日期 2026/10/16') && text(folds1).includes('來源：' + candidateSourceText(completeItem())), 'detail #1: data date and 來源 line in 資料日期與來源')
check(!detail1.includes('data-sub-item='), 'detail #1: the score-detail table stays on the stock page')
check(text(detailOf(rowOf(list, 2))).includes(NOTE_MISSING_TEXT), 'detail #2: no note → fixed copy')
check(text(detailOf(rowOf(list, 3))).includes(NOTE_PENDING_TEXT), 'detail #3: pending note → fixed copy')
check(count(list, '來源：') === 12 && count(list, NOTE_DISCLAIMER) === 12 && count(list, '>加入追蹤</button>') === 12, 'list: one 來源 line, one AI disclaimer and one 加入追蹤 per candidate (page_checks T7, T8, T13)')
const short = render('CandidatesSection two', () => <CandidatesSection data={listResponse()} loading={false} error={null} />)
check(!short.includes('candidate-more') && count(short, '<li class="candidate-row') === 2, 'list of 2: no fold')
check(text(short).includes('資料 2026/10/16') && text(short).includes('2 檔'), 'list: run date badge and count')
// Zero candidates and not computed keep their copy.
for (const reason of ['no_actionable_signals', 'all_excluded'] as const) {
  const data = zeroResponse(reason)
  const markup = render(`CandidatesSection zero ${reason}`, () => <CandidatesSection data={data} loading={false} error={null} />)
  check(text(markup).includes(data.zero_reason_text ?? '?') && text(markup).includes('當日零候選') && !markup.includes('candidate-list'), `zero ${reason}: copy, no list`)
}
const notComputed = render('CandidatesSection not computed', () => <CandidatesSection data={notComputedResponse()} loading={false} error={null} />)
check(text(notComputed).includes(NOT_COMPUTED_TEXT) && text(notComputed).includes('尚無候選清單') && !notComputed.includes('date-badge') && !text(notComputed).includes('T+1'), 'not_computed: copy without a date badge or T+1 sentence')

// ---- Issue 510 layout rules the static markup cannot show (DESIGN_SYSTEM §5 候選列表, 熱門族群) ----
const styles = fs.readFileSync(path.join(__dirname, '..', 'styles.css'), 'utf8')
const ruleOf = (selector: string) => { const at = styles.indexOf('\n' + selector + ' {'); return at < 0 ? '' : styles.slice(at, styles.indexOf('}', at)) }
check(/white-space:\s*nowrap/.test(ruleOf('.candidate-row-title')) && /text-overflow:\s*ellipsis/.test(ruleOf('.candidate-row-title')), 'Issue 510: the title line never wraps; market · group is cut with an ellipsis')
check(/white-space:\s*nowrap/.test(ruleOf('.hot-group-returns')), 'Issue 510: line two of a group never wraps')
// Issue 675 (DESIGN_SYSTEM §5 漲跌文字): the 1／5／20 日 returns are plain text, red up and green down; no rule draws a
// background or a ::before block on them (Issue 654 drew one per step).
const strengthRules = styles.split('\n').filter((line) => /^\.strength-/.test(line))
check(strengthRules.length > 0 && strengthRules.every((line) => !/::before|background|opacity|strength-l\d/.test(line)), `Issue 675: no background on the group returns: ${strengthRules.join(' ')}`)
check(/color:\s*var\(--color-up\)/.test(ruleOf('.strength-chip.strength-up')) && /color:\s*var\(--color-down\)/.test(ruleOf('.strength-chip.strength-down')), 'Issue 675: up returns are --color-up text, down returns --color-down')
check(/color:\s*var\(--color-text\)/.test(ruleOf('.strength-chip')) && /color:\s*var\(--color-text-muted\)/.test(ruleOf('.strength-chip.strength-none')) && ruleOf('.strength-chip.strength-flat') === '', 'Issue 675: 0.00% stays the body text colour, no data muted')
check(/white-space:\s*nowrap/.test(ruleOf('.hot-group-line h3')), 'Issue 510: a group name is one line')
check(!/var\(--text-|--space-row|--space-block/.test(styles.replace(/var\(--text-(xs|sm|md|base|lg|xl|2xl)\)|var\(--space-(row|block)\)/g, '')), 'Issue 510: only the defined type and spacing tokens are used')
// Issue 608: on phones the AI entry left the numbers' line (it covered the total at 390) for the title line's right,
// the numbers take the whole width, and the RR's basis may wrap inside its column. page_checks T17 measures it.
const phoneAt = styles.indexOf('@media (max-width: 640px)')
const phoneRuleOf = (selector: string) => { const at = styles.indexOf('\n  ' + selector + ' {', phoneAt); return phoneAt < 0 || at < 0 ? '' : styles.slice(at, styles.indexOf('}', at)) }
check(/display:\s*contents/.test(phoneRuleOf('.candidate-row-body')) && /grid-row:\s*1/.test(phoneRuleOf('.candidate-row-title')), 'Issue 608: the row body\'s children sit in the row grid, the title on line one')
check(/grid-column:\s*2/.test(phoneRuleOf('.candidate-ai-toggle')) && /grid-row:\s*1/.test(phoneRuleOf('.candidate-ai-toggle')), 'Issue 608: the AI entry is at the right of the title line on phones')
check(/grid-column:\s*1 \/ -1/.test(phoneRuleOf('.candidate-row-body > :not(.candidate-row-title), .candidate-row-nums')), 'Issue 608: the sentence and the numbers take the whole row')
check(/min-width:\s*0/.test(phoneRuleOf('.candidate-row-nums > .candidate-row-rr')) && /white-space:\s*normal/.test(phoneRuleOf('.candidate-row-nums .candidate-rr-basis')), 'Issue 608: the RR column may narrow and its basis wrap')
check(nums1.includes('<div class="candidate-row-rr"><dt>'), 'Issue 608: the RR cell carries the class the phone rule narrows')
// Issue 668: beside the chart (from 1280px) the list column is too narrow for the note beside the levels, so the detail
// stacks there as below 860px; from 861 to 1279px it stays side by side. page_checks T21 measures the note's width.
const wideAt = styles.indexOf('@media (min-width: 1280px)')
const wideRuleOf = (selector: string) => { const at = styles.indexOf('\n  ' + selector + ' {', wideAt); const end = styles.indexOf('\n}', wideAt); return wideAt < 0 || at < 0 || at > end ? '' : styles.slice(at, styles.indexOf('}', at)) }
const stacked = wideRuleOf('.candidates-terminal .candidate-detail-body')
check(/grid-template-areas:\s*"note" "side" "folds"/.test(stacked) && /grid-template-columns:\s*minmax\(0, 1fr\);/.test(stacked), `Issue 668: from 1280px the detail in the list column stacks, got 「${stacked.trim()}」`)
check(/grid-template-areas:\s*"note side"/.test(ruleOf('.candidate-detail-body')), 'Issue 668: below 1280px (above 860px) the note and the levels stay side by side')
const tokenCss = fs.readFileSync(path.join(__dirname, '..', 'styles', 'tokens.css'), 'utf8')
for (const token of ['--text-xs', '--text-sm', '--text-md', '--text-base', '--text-lg', '--text-xl', '--text-2xl', '--space-row', '--space-block']) check(tokenCss.includes(token + ':'), `tokens.css defines ${token} (DESIGN_SYSTEM §2)`)

// ---- level colours site-wide: stop warning, target primary; red and green only for up and down ----
const css = fs.readFileSync(path.join(__dirname, '..', 'styles.css'), 'utf8')
const rule = (selector: string) => new RegExp(`(^|\\n)\\${selector}\\s*\\{([^}]*)\\}`).exec(css)?.[2] ?? ''
check(/color:\s*var\(--color-warning\)/.test(rule('.level-stop')), `.level-stop uses --color-warning, got 「${rule('.level-stop').trim()}」`)
check(/color:\s*var\(--color-primary\)/.test(rule('.level-target')), `.level-target uses --color-primary, got 「${rule('.level-target').trim()}」`)
check(!/--color-(error|success)/.test(rule('.level-stop') + rule('.level-target')), 'levels: no --color-error／--color-success')
// The sparkline (Issue 653): red for a span that rose, green for one that fell (台股紅漲綠跌), muted when unchanged.
check(/stroke:\s*var\(--color-up\)/.test(rule('.sparkline-up path')) && /stroke:\s*var\(--color-down\)/.test(rule('.sparkline-down path')), `sparkline: up uses --color-up and down --color-down, got 「${rule('.sparkline-up path').trim()}」「${rule('.sparkline-down path').trim()}」`)
check(/stroke:\s*var\(--color-text-muted\)/.test(rule('.sparkline path')) && /fill:\s*none/.test(rule('.sparkline path')), 'sparkline: an unchanged span is muted and the line has no fill')
const boardPanel = render('StrategyBoardPanel', () => <StrategyBoardPanel board={board([conditionalBreakout(), observationPullback()])} candidate={null} />)
check(boardPanel.includes('class="level-stop">2,364.00') && boardPanel.includes('class="level-target">2,458.00／2,508.00'), '個股頁策略總表: stop and target carry the level classes')
check(boardPanel.includes('class="level-stop">2,399.64') && boardPanel.includes('class="level-target">2,478.57／2,521.07'), '個股頁觀察價位: reference stop and target carry the level classes')
const conditional = {
  instrument: { id: 1, exchange: 'TWSE', symbol: '1742', name: '台蠟', instrument_type: 'stock', etf_category: null },
  action_state: 'conditional_entry', primary_strategy: 'breakout_v1', current_price: 21.1, price_as_of: '2026-10-22', data_cutoff: '2026-10-22', data_quality: 'complete',
  trigger_price: 21.5, invalid_price: 20.1, target_1: 23.8, risk_reward: 1.6, reasons: [], conflicts: [], strategies: [], missing_data_priority: [], alternative_strategies: [],
  level_semantics: { version: 'signal-level-semantics/v1', kind: 'rule_reference' },
} as unknown as ActionSummary
// The action list shows the levels now (#278; #297 review L5 removed the unused ProductActionCard).
const tierSection = (tier: number, item: ActionSummary) => ({ tier: tier as 0 | 1 | 2, key: 'k', label: 'L', shown: 1, items: [{ ...item, tier }] as ActionSummary[] })
const actionCard = render('ActionTierSectionView', () => { const View = component(ActionModule as Record<string, unknown>, 'ActionTierSectionView'); return <View section={tierSection(2, conditional)} canLoadMore onMore={() => {}} /> })
check(/<td class="num level-stop">20\.10<\/td>/.test(actionCard) && /<td class="num level-target">23\.80<\/td>/.test(actionCard), `行動頁列表: stop and target carry the level classes`)
check(/<td class="num level-entry">21\.50<\/td>/.test(actionCard), '行動頁列表: the trigger is the entry level')
check(/<dd class="level-stop">20\.10<\/dd>/.test(actionCard) && /<dd class="level-target">23\.80<\/dd>/.test(actionCard), '行動頁手機卡: stop and target carry the level classes')
const actionDetail = render('ActionDetailPanel', () => { const Panel = component(AppModule as Record<string, unknown>, 'ActionDetailPanel'); return <Panel action={conditional} /> })
check(/<b class="level-stop">20\.10<\/b>/.test(actionDetail) && /<b class="level-target">23\.80<\/b>/.test(actionDetail), '行動詳情: stop and target carry the level classes')
const held = { ...conditional, action_state: 'reduce_exit', held: true, stop_price: 19.5, stop_price_semantics: { kind: 'user_position_risk_input' } } as unknown as ActionSummary
const heldCard = render('ActionTierSectionView held', () => { const View = component(ActionModule as Record<string, unknown>, 'ActionTierSectionView'); return <View section={tierSection(0, held)} canLoadMore onMore={() => {}} /> })
check(/<td class="num level-stop">19\.50<\/td>/.test(heldCard), '行動頁列表: a holding stop is a stop level too')

// ---- AI 名單 (#1146, UI_COPY_SPEC §10 AI 名單, DESIGN_SYSTEM §7): the list's date and 「AI 推論，未經驗證」, the badge on a list of
// another day, the failure line, no level of a pick that failed its check, the warning of a corporate action ----
const AiListView = component(AiListModule as Record<string, unknown>, 'AiListView')
const ai = render('AiListView done', () => <AiListView data={aiListDone()} />)
const aiText = text(ai)
check(ai.startsWith('<section class="ai-inference ai-list"') && count(ai, AI_LIST_MARK) === 2 && count(ai, 'badge-accent') === 1, `AI 名單: one §7 block, one badge 「AI 推論，未經驗證」 and the meta line, got ${ai.slice(0, 300)}`)
check(aiText.includes('AI 名單 · 2026/11/27 開盤前產出（08:22）') && aiText.includes('模型 claude-sonnet-5-5 · 提示 ai_list_v1 · AI 推論，未經驗證'), `AI 名單 (AC-1): the list's date, the model and the prompt version, got ${aiText}`)
check(!ai.includes('ai-list-stale') && !ai.includes('ai-list-failure'), 'AI 名單: today\'s list has no date badge and no failure line')
check(aiText.includes('大盤 中性（把握低） · 依據：台指期夜盤＞加權指數＞隔夜消息＞美股') && aiText.includes('族群：PCB 可能正向'), `AI 名單: market with its basis, the sectors, got ${aiText}`)
const firstPick = slice(ai, 'data-ai-rank="1"', '</li><li')
check(text(firstPick).includes('1477 聚陽 突破 · 技術面＞籌碼 · 把握中') && firstPick.includes('href="/stocks/TWSE/1477"'), `AI 名單: rank, name (to the stock page) and method in words, got ${text(firstPick)}`)
check(text(firstPick).includes('進場 站上 233.00（不追價 236.50）｜停損 226.00｜目標一 243.50／二 254.50｜RR 1.50 倍｜有效至 12/02'), `AI 名單: the AI levels in one line, got ${text(firstPick)}`)
check(firstPick.includes('class="ai-list-price level-entry"') && firstPick.includes('class="ai-list-price level-stop"') && firstPick.includes('class="ai-list-price level-target"'), 'AI 名單: entry/stop/target carry the §7 level classes')
check(firstPick.includes('<p class="ai-list-corporate">名單日後有除權息，價位以 11/26 收盤為基準，今天的漲跌停與參考價可能不同</p>'), `AI 名單 (decision 7238366814): the corporate-action warning beside the levels, got ${firstPick}`)
check(firstPick.includes('href="/news/501"') && text(firstPick).includes('依據 1477 籌碼') && text(firstPick).includes('進場條件：若站上 20 日高點') && text(firstPick).includes('出場條件：若外資與投信轉為連續賣超') && text(firstPick).includes('價位依據進場下緣 233.00＝20 日高點（11/26）'), `AI 名單: reasons, cited news, conditions and the levels' basis, got ${text(firstPick)}`)
check(text(slice(ai, 'data-ai-rank="2"', '</li><li')).includes('進場區 44.40～46.05｜停損 42.00'), 'AI 名單: a pullback writes 進場區')
const failedPick = slice(ai, 'data-ai-rank="3"', '</ol>')
check(failedPick.includes('data-levels="hidden"') && text(failedPick).includes('價位未通過核對，未顯示') && !failedPick.includes('ai-list-price') && !text(failedPick).includes('停損') && !text(failedPick).includes('進場條件'), `AI 名單 (AC-2): a failed check shows no price, got ${text(failedPick)}`)
const aiCss = fs.readFileSync(path.join(__dirname, 'aiList.css'), 'utf8')
check(/\.ai-list-level\s*\{[^}]*white-space:\s*nowrap/.test(aiCss) && /\.ai-list-price\s*\{[^}]*font-family:\s*var\(--font-mono\)[^}]*tabular-nums/.test(aiCss), 'AI 名單: a price is mono, tabular and stays with its label')
check(/\.ai-list-expired, \.ai-list-corporate\s*\{\s*color:\s*var\(--color-warning\)/.test(aiCss), 'AI 名單: the expired and corporate-action lines use the warning token')
// A list of another day (AC-1), and the list before a failed day (AC-2, 1/4 Q1-5 A).
const stale = render('AiListView stale', () => <AiListView data={aiListDone({ is_today: false, today: '2026-11-28' })} />)
check(stale.includes('badge-warning') && text(slice(stale, 'ai-list-stale', '</span>')).includes('11/27 的名單'), `AI 名單 (AC-1): a warning badge 「11/27 的名單」 on a list of another day, got ${stale.slice(0, 400)}`)
const fallback = render('AiListView failed day', () => <AiListView data={aiListDone({ is_today: false, today: '2026-11-30', failure: { session_date: '2026-11-30', status: 'failed', reason: 'timeout', reason_text: '呼叫逾時', text: '今天的 AI 名單沒有產出：呼叫逾時' } })} />)
check(text(fallback).includes('今天的 AI 名單沒有產出：呼叫逾時') && text(fallback).includes('11/27 的名單') && text(fallback).includes('1477 聚陽'), `AI 名單 (AC-2): the failure line over the list before, with its date badge, got ${text(fallback).slice(0, 300)}`)
const expired = render('AiListView expired', () => <AiListView data={aiListDone({ picks: [aiPick(1, { levels: null, expired: true, expired_text: '價位已過有效期（3 個交易日，至 12/02）' })] })} />)
check(expired.includes('<p class="ai-list-no-levels ai-list-expired">價位已過有效期（3 個交易日，至 12/02）</p>') && !/站上 \d/.test(text(expired)), 'AI 名單: a pick past its validity says so without levels')
const empty = text(render('AiListView empty', () => <AiListView data={aiListDone({ picks: [], empty_reason: '大盤偏空', empty_text: '今天 AI 沒有列股票：大盤偏空' })} />))
check(empty.includes('今天 AI 沒有列股票：大盤偏空'), `AI 名單: an empty list says why, got ${empty}`)
const none = text(render('AiListView none', () => <AiListView data={{ ...aiListDone(), status: 'missing', session_date: null, picks: [], market: null, sectors: [], missing_text: AI_LIST_MISSING }} />))
check(none === `${AI_LIST_TITLE}${AI_LIST_MARK}${AI_LIST_MISSING}`, `AI 名單: no list at all is one line, got ${none}`)
check(text(render('AiListView loading', () => <AiListView data={undefined} loading />)).includes(AI_LIST_LOADING), 'AI 名單: loading')
check(text(render('AiListView error', () => <AiListView data={undefined} error={new Error('x')} />)).includes(AI_LIST_ERROR), 'AI 名單: a failed load')
// The chart (#1142 4/4 row 26): beside the list from 1280px with the AI lines; none for a pick without levels.
const wideAi = render('AiListView wide', () => <AiListView data={aiListDone()} wide renderChart={(pick: AiListPick) => <div data-test-chart={pick.symbol} />} />)
check(wideAi.includes('class="ai-list-terminal"') && wideAi.includes('data-ai-chart-rank="1"') && wideAi.includes('data-test-chart="1477"'), 'AI 名單: the first pick\'s chart beside the list from 1280px')
const narrowAi = render('AiListView narrow', () => <AiListView data={aiListDone()} initialChartRank={2} renderChart={(pick: AiListPick) => <div data-test-chart={pick.symbol} />} />)
check(!narrowAi.includes('ai-list-terminal') && count(narrowAi, 'data-test-chart=') === 1 && narrowAi.includes('data-test-chart="2618"'), 'AI 名單: below 1280px only the opened row\'s card')
const lines = aiChartLevels(aiListDone().picks[0])
check(lines?.entry === 233 && lines.stop === 226 && lines.target === 243.5 && lines.source === 'ai', `AI 名單: a breakout's line is its low, marked AI, got ${JSON.stringify(lines)}`)
check(Math.abs((aiChartLevels(aiListDone().picks[1])?.entry ?? 0) - 45.225) < 1e-9 && aiChartLevels(aiListDone().picks[2]) === null, 'AI 名單: a pullback\'s line is its middle; no lines without levels')
check(levelsNote(lines!) === 'AI 價位線（AI 推論，未經驗證）：AI 進場 233.00 元（虛線）、AI 停損 226.00 元、AI 目標 243.50 元', `AI 名單: the chart note marks the lines AI, got ${levelsNote(lines!)}`)
check(levelsNote({ entry: 101, stop: 98, target: 103.2 }).startsWith('規則價位線：進場 101.00 元'), 'the stock page keeps the rule lines')
// AC-3 (#1042): no order wording in the block (the job's check, backend premarket_reading.directive_words, in short).
const ORDER = /下單|掛單|(?:建議|可以|宜|應該|應|請|今日|今天|明日|明天|立即|馬上|逢低|逢高|開盤|分批|考慮|不宜|暫不)\s*(?:買進|買入|賣出|進場|出場)/
check(!ORDER.test(aiText) && !ORDER.test(text(fallback)), `AI 名單: no order wording, got ${aiText}`)
check(ORDER.test('建議買進') && ORDER.test('下單'), 'the order pattern catches an order')

if (failures.length) throw new Error(`${failures.length} of ${checks} today checks failed:\n- ${failures.join('\n- ')}`)
