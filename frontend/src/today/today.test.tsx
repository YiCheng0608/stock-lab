import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import * as AppModule from '../App'
import * as ActionModule from '../actions/ActionViews'
import * as CandidateModule from '../candidates/CandidateViews'
import { CANDIDATE_DISCLAIMER, NOTE_DISCLAIMER, NOTE_MISSING_TEXT, NOTE_PENDING_TEXT, NOT_COMPUTED_TEXT, candidateChange, candidateSourceText } from '../candidates/candidates'
import { completeItem, listResponse, longList, notComputedResponse, partialItem, zeroResponse } from '../candidates/candidates.fixtures'
import type { ActionSummary } from '../types'
import * as TodayModule from './TodayViews'
import { overviewBoth, overviewNone, overviewTwseOnly, riskActions } from './today.fixtures'
import { StrategyBoardPanel } from '../stock/StrategyBoardPanel'
import { board, conditionalBreakout, observationPullback } from '../stock/strategyBoard.fixtures'

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

const MarketOverviewView = component(TodayModule, 'MarketOverviewView')
const TodayHeader = component(TodayModule, 'TodayHeader')
const HoldingAlert = component(TodayModule, 'HoldingAlert')
const CandidatesSection = component(CandidateModule, 'CandidatesSection')

// ---- market overview: four widgets, both / one / no exchange (UI_COPY_SPEC §11) ----
const both = render('MarketOverviewView both', () => <MarketOverviewView overview={overviewBoth()} />)
const wide = slice(both, 'class="market-overview-grid"', '<details')
for (const value of ['加權指數', '46,041.43', '-846.34（-1.81%）', '櫃買指數', '381.69', '-13.73（-3.47%）', '成交金額', '億元', '上市 9,334.37 集中市場總計', '上櫃 2,255.45 上櫃股票',
  '漲跌家數（股票）', '括號為漲停／跌停', '上市 上漲 247 · 下跌 756 · 平盤 74（3／5）', '上櫃 上漲 146 · 下跌 659 · 平盤 63（17／11）']) {
  check(text(wide).includes(value), `大盤概況（兩邊都有）: shows 「${value}」`)
}
check(count(wide, 'market-widget') >= 4 && count(wide, 'market-widget-dual') === 2, '大盤概況: four widgets, turnover and breadth are the dual-row variant')
check(/class="market-widget-change[^"]*tone-down"/.test(wide), '大盤概況: a falling index change is green (tone-down)')
// The turnover scope stays on screen next to each amount (#1 6394637858 point 2); the full wording is in 資料說明.
check(count(slice(wide, 'market-turnover', 'market-breadth'), 'class="market-row-scope"') === 2, '大盤概況: each turnover row carries its short scope')
const otherScope = { ...overviewBoth(), exchanges: overviewBoth().exchanges.map((row) => row.exchange === 'TPEx' ? { ...row, turnover: { value: 1e8, scope: 'tpex_all', scope_label: '上櫃全部證券' } } : row) }
check(text(render('MarketOverviewView other scope', () => <MarketOverviewView overview={otherScope} />)).includes('上櫃 1.00 上櫃全部證券'), '大盤概況: an unknown scope shows the API scope_label')
check(text(slice(both, '<details', '</details>')).includes('成交金額與漲跌家數'), '大盤概況: phones fold turnover and breadth into 「成交金額與漲跌家數」')
const one = text(render('MarketOverviewView TWSE only', () => <MarketOverviewView overview={overviewTwseOnly()} />))
check(one.includes('上櫃大盤資料未取得') && !one.includes('381.69') && !one.includes('2,255.45'), '大盤概況（只有上市）: the TPEx cells read 「上櫃大盤資料未取得」')
check(one.includes('46,041.43') && one.includes('上市 9,334.37'), '大盤概況（只有上市）: TWSE shows as usual')
for (const [name, overview] of [['都沒有', overviewNone()], ['欄位不存在', undefined]] as const) {
  const none = text(render(`MarketOverviewView ${name}`, () => <MarketOverviewView overview={overview} />))
  check(none.includes('上市大盤資料未取得') && none.includes('上櫃大盤資料未取得') && !/\d,\d{3}\.\d{2}/.test(none), `大盤概況（${name}）: both read 未取得 and show no number`)
}

// ---- header line and 資料說明: turnover scope, derived TPEx change, red/green meaning ----
const headerProps = { asOf: '2026-10-22T10:30:00+00:00', sourceLabel: 'TWSE／TPEx 官方資料', modeLabel: '官方單日快照', badge: <span className="pill complete">行情來源完整</span>, scopeText: '官方標的範圍 · 1,950 檔標的' }
const header = render('TodayHeader', () => <TodayHeader {...headerProps} overview={overviewBoth()} />)
check(text(slice(header, 'class="home-dataline-text"', '</span>')).includes('資料截至 2026/10/22 · TWSE／TPEx 官方資料 · 官方單日快照'), 'header: one line 「資料截至 2026/10/22 · 來源 · 模式」')
const explanation = text(slice(header, '<details', '</details>'))
check(explanation.includes('成交金額範圍：上市為集中市場總計（含 ETF、權證等）；上櫃為上櫃股票'), `資料說明: the turnover scope of both exchanges, got ${explanation}`)
check(explanation.includes('櫃買指數漲跌幅依前一日收市指數計算'), '資料說明: the derived TPEx change says how it was computed')
check(explanation.includes('紅色為上漲、綠色為下跌（台股慣例）'), '資料說明: red is up and green is down')
const headerTwse = text(render('TodayHeader TWSE only', () => <TodayHeader {...headerProps} overview={overviewTwseOnly()} />))
check(headerTwse.includes('成交金額範圍：上市為集中市場總計（含 ETF、權證等）') && !headerTwse.includes('上櫃為') && !headerTwse.includes('依前一日收市指數'), '資料說明（只有上市）: only the TWSE scope, no TPEx note')
check(!/hero|glow/.test(header), 'header: no hero or glow (DESIGN_SYSTEM §1)')
check(/<h1 class="sr-only">今日<\/h1>/.test(header), 'header: the page still has an h1 for assistive tech')
// Without a dashboard (load failed) the line has no empty source or mode parts.
const failed = text(slice(render('TodayHeader failed', () => <TodayHeader asOf={null} sourceLabel="" modeLabel="" overview={undefined} />), 'class="home-dataline-text"', '</span>'))
check(failed.endsWith('資料截至 未提供') && !failed.includes('·'), `header: a failed load reads 「資料截至 未提供」, got 「${failed}」`)

// ---- holding-risk alert row: only verified holding risks, linked to the action centre ----
const alert = render('HoldingAlert', () => <HoldingAlert actions={riskActions()} />)
check(text(alert).includes('持倉風險 4 檔：2330 台積電：減碼／退場條件；1101 台泥：持倉風險資料待補；2882 國泰金：庫存數量待核實 等 4 檔'), `持倉提示列: count, first three holdings and reasons, got ${text(alert)}`)
check(alert.includes('href="/watch"') && text(alert).includes('查看觀察中 →'), '持倉提示列: links to /watch (Issue 493)')
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
check(text(long).includes('2026/10/16 收盤後條件成立，最早下一個交易日（T+1）才可研究進場。') && text(long).includes(CANDIDATE_DISCLAIMER), 'list: the T+1 sentence and the disclaimer')
// The head is one line (Issue 510): no eyebrow; title, date badge, count, the notes and 策略說明 in one flex row.
const head = slice(long, 'class="candidates-head"', '<ol')
check(!head.includes('eyebrow') && head.includes('id="candidates-title">今日可買</h2>') && head.includes('href="/strategy"'), 'Issue 510: the head has no eyebrow, the title and 策略說明 are in it')
check(head.indexOf('今日可買</h2>') < head.indexOf('資料 2026/10/16') && head.indexOf('資料 2026/10/16') < head.indexOf('12 檔') && head.indexOf('12 檔') < head.indexOf('收盤後條件成立'), 'Issue 510: title → date → count → notes in the head')
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

// ---- Issue 510 layout rules the static markup cannot show (DESIGN_SYSTEM §5 候選列表, 熱門族群與重點新聞) ----
const styles = fs.readFileSync(path.join(__dirname, '..', 'styles.css'), 'utf8')
const ruleOf = (selector: string) => { const at = styles.indexOf('\n' + selector + ' {'); return at < 0 ? '' : styles.slice(at, styles.indexOf('}', at)) }
check(/white-space:\s*nowrap/.test(ruleOf('.candidate-row-title')) && /text-overflow:\s*ellipsis/.test(ruleOf('.candidate-row-title')), 'Issue 510: the title line never wraps; market · group is cut with an ellipsis')
check(/white-space:\s*nowrap/.test(ruleOf('.home-news-title')) && /text-overflow:\s*ellipsis/.test(ruleOf('.home-news-title')), 'Issue 510: a news title is one line')
check(/white-space:\s*nowrap/.test(ruleOf('.home-news-meta, .home-news-impact')) && /white-space:\s*nowrap/.test(ruleOf('.hot-group-returns')), 'Issue 510: line two of news and groups never wraps')
check(/white-space:\s*nowrap/.test(ruleOf('.hot-group-line h3')), 'Issue 510: a group name is one line')
check(!/var\(--text-|--space-row|--space-block/.test(styles.replace(/var\(--text-(xs|sm|md|base|lg|xl|2xl)\)|var\(--space-(row|block)\)/g, '')), 'Issue 510: only the defined type and spacing tokens are used')
const tokenCss = fs.readFileSync(path.join(__dirname, '..', 'styles', 'tokens.css'), 'utf8')
for (const token of ['--text-xs', '--text-sm', '--text-md', '--text-base', '--text-lg', '--text-xl', '--text-2xl', '--space-row', '--space-block']) check(tokenCss.includes(token + ':'), `tokens.css defines ${token} (DESIGN_SYSTEM §2)`)

// ---- level colours site-wide: stop warning, target primary; red and green only for up and down ----
const css = fs.readFileSync(path.join(__dirname, '..', 'styles.css'), 'utf8')
const rule = (selector: string) => new RegExp(`(^|\\n)\\${selector}\\s*\\{([^}]*)\\}`).exec(css)?.[2] ?? ''
check(/color:\s*var\(--color-warning\)/.test(rule('.level-stop')), `.level-stop uses --color-warning, got 「${rule('.level-stop').trim()}」`)
check(/color:\s*var\(--color-primary\)/.test(rule('.level-target')), `.level-target uses --color-primary, got 「${rule('.level-target').trim()}」`)
check(!/--color-(error|success)/.test(rule('.level-stop') + rule('.level-target')), 'levels: no --color-error／--color-success')
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

if (failures.length) throw new Error(`${failures.length} of ${checks} today checks failed:\n- ${failures.join('\n- ')}`)
