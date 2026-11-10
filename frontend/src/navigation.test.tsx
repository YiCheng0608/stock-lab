import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import * as AppModule from './App'
import { MAIN_NAV } from './components/Navbar'
import { Shell } from './components/Shell'
import { listResponse } from './candidates/candidates.fixtures'
import { CandidatesSection } from './candidates/CandidateViews'
import { noPreviousCloseText } from './marketChange'
import { newsItem } from './news/news.fixtures'
import { industryBoard } from './themes/themeBoards.fixtures'
import { TODAY_BOARD_LIMIT } from './themes/themeBoards'
import { HoldingAlert } from './today/TodayViews'
import { overviewBoth, riskActions } from './today/today.fixtures'
import { planLink } from './tracking/tracking'
import type { Dashboard } from './types'

// The 觀察中 purpose line for a first-time reader (UI_COPY_SPEC §5, decision 6648288563).
const WATCH_PURPOSE = '把有興趣的候選加入追蹤，系統每天收盤後依日線模擬它的進場與出場（不是實際成交）；這裡也會提醒你庫存的風險，和快要成立的股票。'

// The frontend ships no Node typings; scripts/ci-test.cjs runs this module under Node, so declare what it uses.
declare const require: (id: string) => unknown
declare const __dirname: string
const fs = require('node:fs') as { readFileSync(file: string, encoding: 'utf8'): string }
const path = require('node:path') as { join(...parts: string[]): string }

// Information architecture (#493, Issue 549; PRODUCT_SPEC §2, DESIGN_SYSTEM §4/§5, UI_COPY_SPEC §5/§10/§11): the seven main
// links, 觀察中 at /watch with /actions redirecting, the 策略說明 page, the 今日可買 home and its table and columns.
const failures: string[] = []
let checks = 0
const count = (html: string, part: string) => html.split(part).length - 1
const check = (condition: boolean, message: string) => { checks++; if (!condition) failures.push(message) }
const text = (html: string) => html.replace(/<[^>]+>/g, ' ').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/\s+/g, ' ')

function render(location: string, element: ReactElement, client = new QueryClient()): string {
  try {
    return renderToStaticMarkup(<QueryClientProvider client={client}><StaticRouter location={location}>{element}</StaticRouter></QueryClientProvider>)
  } catch (error) {
    checks++
    failures.push(`${location}: render failed (${error instanceof Error ? error.message.split('\n')[0] : String(error)})`)
    return ''
  }
}

// ---- main navigation: 今日可買, 大盤 (Issue 549), 觀察中, three data pages, then the explanation ----
const nav = MAIN_NAV.map((item) => `${item.to} ${item.label}`)
const expectedNav = ['/ 今日可買', '/market 大盤', '/watch 觀察中', '/themes 族群', '/stocks 個股', '/news 新聞', '/strategy 策略說明']
check(JSON.stringify(nav) === JSON.stringify(expectedNav), `MAIN_NAV: ${JSON.stringify(nav)}，預期 ${JSON.stringify(expectedNav)}`)

// ---- routes: /watch and /strategy render their pages; /actions keeps its query and plan anchor ----
const App = (AppModule as Record<string, unknown>).default as () => ReactElement
const watch = render('/watch', <App />)
check(watch.includes('<h1>觀察中</h1>'), '/watch 的頁面標題是「觀察中」')
check(text(watch).includes(WATCH_PURPOSE), `/watch 有用途說明: ${text(watch).slice(0, 300)}`)
check(!watch.includes('找不到此頁'), '/watch 不是 404')
const strategy = render('/strategy', <App />)
check(strategy.includes('<h1>策略說明</h1>'), '/strategy 的頁面標題是「策略說明」')
for (const heading of ['今日可買怎麼來', '突破型', '回踩型', '怎麼照著做', '觀察中在做什麼']) {
  check(text(strategy).includes(heading), `/strategy 缺「${heading}」`)
}
// 策略說明 names the strategy, then writes its thresholds and weights (#577; UI_COPY_SPEC §13; the numbers restate
// backend/app/strategies/base.py COMMON_CONFIRMATIONS, breakout_v1.py, pullback_v1.py and domain.py CANDIDATE_SCORE_V6).
const strategyText = text(strategy)
const block = strategy.slice(strategy.indexOf('data-strategy="trend_chips"'), strategy.indexOf('aria-labelledby="strategy-follow-title"'))
const blockText = text(block)
check(strategy.includes('data-strategy="trend_chips"') && count(strategy, 'data-strategy=') === 1, '/strategy 有一個以策略名稱為標題的區塊（data-strategy），沒有切換或第二個策略區塊')
check(strategyText.includes('目前策略：順勢籌碼型'), `/strategy 頁首寫「目前策略：順勢籌碼型」: ${strategyText.slice(0, 200)}`)
check(/<h2 id="strategy-current-title"><button[^>]*data-term="trend_chips"[^>]*>順勢籌碼型<\/button><\/h2>/.test(block), '/strategy 的策略區塊標題是「順勢籌碼型」詞彙按鈕')
// text() puts a space where a tag was (a term button, <code>); the paragraph is compared without spaces.
const flat = (markup: string) => text(markup).replace(/\s+/g, '')
const firstParagraph = flat(/<\/h2><p>([\s\S]*?)<\/p>/.exec(block)?.[1] ?? '')
for (const part of ['順勢籌碼型', '只做多頭趨勢', '所屬族群比大盤強', '三大法人沒有明顯賣超', '融資沒有過熱', '大盤好壞目前不影響判斷', '突破型（breakout_v3）', '回踩型（pullback_v4）', '候選總分（candidate_score_v7）']) {
  check(firstParagraph.includes(part.replace(/\s+/g, '')), `/strategy 策略區塊第一段缺「${part}」: ${firstParagraph}`)
}
check(strategyText.indexOf('順勢籌碼型') < strategyText.indexOf('今日可買怎麼來') && strategy.indexOf('data-strategy="trend_chips"') < strategy.indexOf('aria-labelledby="strategy-follow-title"'), '/strategy 先寫策略名稱與區塊，再寫「怎麼照著做」')
// The three confirmations, each with its threshold, in a table.
const tables = [...block.matchAll(/<table[\s\S]*?<\/table>/g)].map((match) => match[0])
check(tables.length === 2 && tables.every((table) => table.includes('class="action-table"')), `/strategy 策略區塊有兩張表（確認條件、評分權重），got ${tables.length}`)
// Phones show both tables: styles.css hides strategy-table-wrap at 640px (the strategy board shows cards there), so the
// tables sit in the plain table-wrap.
check(count(block, '<div class="table-wrap">') === 2 && !block.includes('strategy-table-wrap'), '/strategy 的兩張表在 640px 以下仍顯示（不放進被隱藏的 strategy-table-wrap）')
const confirmations = text(tables[0] ?? '')
for (const part of ['確認條件', '族群', '所屬族群近 20 日報酬高於加權指數', '法人', '三大法人 5 日淨買賣超 ≥ 20 日均量的 −0.3%', '融資', '融資餘額 5 日增幅 ≤ 5%（非融資標的不適用這一條）']) {
  check(confirmations.includes(part), `/strategy 確認條件表缺「${part}」: ${confirmations}`)
}
check(count(tables[0] ?? '', '<tr>') === 4, '/strategy 確認條件表是表頭加三列')
// The four score weights: 35 + 30 + 20 + 15, one row each, in this order.
const weightRows = [...(tables[1] ?? '').matchAll(/<tr><td[^>]*>([\s\S]*?)<\/td><td[^>]*>([\s\S]*?)<\/td><td[^>]*>([\s\S]*?)<\/td><\/tr>/g)].map((match) => [text(match[1]).trim(), text(match[2]).trim(), text(match[3]).trim()])
check(JSON.stringify(weightRows.map(([name, weight]) => [name, weight])) === JSON.stringify([['技術', '35%'], ['籌碼', '30%'], ['族群', '20%'], ['新聞情緒（推論）', '15%']]),
  `/strategy 評分權重表：技術 35%、籌碼 30%、族群 20%、新聞情緒（推論）15%，got ${JSON.stringify(weightRows.map(([name, weight]) => [name, weight]))}`)
check(weightRows.reduce((sum, [, weight]) => sum + Number.parseInt(weight, 10), 0) === 100 && weightRows.every(([, , looks]) => looks.length > 10), '/strategy 權重合計 100%，每個分項都寫了看什麼')
check(text(tables[1] ?? '').includes('權重') && text(tables[1] ?? '').includes('看什麼'), '/strategy 評分權重表表頭是「分項、權重、看什麼」')
// Kept: the liquidity floor, the 20-name cap and the two rules' own numbers.
for (const part of ['20 日平均成交量至少 1,000 張', '最多列 20 檔', '當天成交量至少是前 20 日均量的 1.2 倍', '約 −3%～+2%', '前 20 日均量的 0.6～1.2 倍', '有資料的分項權重合計要達 65%']) {
  check(blockText.includes(part), `/strategy 策略區塊缺「${part}」`)
}
// Every term on the page opens a glossary entry; the page has no switch, "other strategies" or "coming soon" block.
const strategyTerms = [...strategy.matchAll(/data-term="([^"]+)"/g)].map((match) => match[1])
for (const id of ['trend_chips', 'candidate_score', 'percentile', 'breakout', 'pullback', 't_plus_1', 'entry_zone', 'support', 'target', 'rr']) check(strategyTerms.includes(id), `/strategy 的詞彙按鈕 ${id} 要開得了詞條（found ${strategyTerms.join('、')}）`)
check(!/即將推出|敬請期待|其他策略|切換策略|稍後推出/.test(strategyText), '/strategy 不放切換、「其他策略」或「即將推出」')
check(!render('/actions', <App />).includes('找不到此頁'), '/actions 不是 404')
const redirect = (AppModule as Record<string, unknown>).watchRedirectPath as ((search: string, hash: string) => string) | undefined
check(typeof redirect === 'function' && redirect('?q=2330', '#plan-7') === '/watch?q=2330#plan-7' && redirect('', '') === '/watch',
  `/actions 轉 /watch 並保留查詢與錨點: ${typeof redirect === 'function' ? redirect('?q=2330', '#plan-7') : 'watchRedirectPath 不存在'}`)
// The /actions route is a redirect, not the page rendered in place (a static render cannot follow <Navigate>, so read
// the route table and the target the redirect computes from the location it is given).
const routes = (AppModule as Record<string, unknown>).APP_ROUTES as ReadonlyArray<{ path: string; element: ReactElement }> | undefined
const WatchRedirect = (AppModule as Record<string, unknown>).WatchRedirect as (() => ReactElement) | undefined
const legacy = routes?.find((route) => route.path === '/actions')
check(Boolean(legacy && WatchRedirect && legacy.element.type === WatchRedirect), `/actions 的 Route 是 WatchRedirect: ${legacy ? String((legacy.element.type as { name?: string }).name) : 'APP_ROUTES 沒有 /actions'}`)
check(routes?.find((route) => route.path === '/watch')?.element.type === AppModule.ActionsPage, '/watch 的 Route 是觀察中頁 (ActionsPage)')
let landed: unknown = null
function LandingProbe() {
  // Calls the redirect in this component's render, so its hooks read the StaticRouter location below.
  const element = WatchRedirect ? WatchRedirect() : null
  landed = element ? (element.props as { to?: unknown }).to : null
  return null
}
render('/actions?q=2330#plan-7', <LandingProbe />)
check(landed === '/watch?q=2330#plan-7', `/actions?q=2330#plan-7 轉到: ${String(landed)}，預期 /watch?q=2330#plan-7`)
check(planLink(7) === '/watch#plan-7', `已在追蹤的連結: ${planLink(7)}`)
const alert = render('/', <HoldingAlert actions={riskActions()} />)
check(alert.includes('href="/watch"') && text(alert).includes('查看觀察中 →'), `持倉風險提示列連到 /watch: ${text(alert)}`)

// ---- 今日可買 home: the list first, no 關注標的, hot groups and news as two equal cards ----
const dashboard = {
  as_of: '2026-10-16', mode: 'official', scan_scope: 'official',
  market: { instruments: 1900, bars: 1900, groups: 40, source: 'twse', source_label: 'TWSE／TPEx 官方資料' },
  data_quality: { latest_run: 'success', latest_run_source: 'twse', latest_run_date: '2026-10-16', latest_run_records: 1900, data_as_of: '2026-10-16', error: null, updated_at: null },
  groups: [], signals: [], signal_status_counts: {},
  news: [newsItem({ id: '1' }), newsItem({ id: '2' }), newsItem({ id: '3' }), newsItem({ id: '4' }), newsItem({ id: '5' }), newsItem({ id: '6' })],
  candidates: [], actions: [], holding_actions: [], market_overview: overviewBoth(),
} as unknown as Dashboard
const homeClient = new QueryClient()
homeClient.setQueryData(['dashboard'], dashboard)
homeClient.setQueryData(['theme-board', 'industry', TODAY_BOARD_LIMIT], industryBoard())
homeClient.setQueryData(['candidates', 'latest'], listResponse())
const TodayPage = AppModule.TodayPage as () => ReactElement
const home = render('/', <TodayPage />, homeClient)
check(home.includes('id="candidates-title">今日可買</h2>'), '首頁名單標題是「今日可買」')
// Issue 549: one market line linking to /market sits above the list; the four-widget overview moved there.
check(home.includes('class="market-summary"') && home.includes('href="/market"') && !home.includes('market-overview-grid'), '首頁大盤只留一行摘要，連到 /market')
check(home.indexOf('class="market-summary"') < home.indexOf('id="candidates-title"'), '大盤摘要在今日可買名單之前')
check(!text(home).includes('明日候選') && !text(home).includes('關注標的'), '首頁不再有「明日候選」與「關注標的」')
const columns = home.slice(home.indexOf('home-columns'))
const panels = columns.match(/class="[^"]*\bhome-panel\b[^"]*"/g) ?? []
check(panels.length === 2, `熱門族群與重點新聞各是一張 home-panel 卡: ${panels.length}`)
// Issue 510: each card head is one line (no eyebrow): title, the board tabs and 完整排行 →, or 全部新聞 →.
const hotHead = home.slice(home.indexOf('<div class="panel-head"><h2 id="hot-groups-title"'), home.indexOf('class="hot-groups-dates"'))
check(hotHead.includes('role="tablist"') && hotHead.includes('>完整排行 →</a>') && !hotHead.includes('eyebrow'), `熱門族群標題列：標題、產業／題材 tab、「完整排行 →」，不放眉標: ${text(hotHead)}`)
const newsHead = home.slice(home.indexOf('<div class="panel-head"><h2 id="home-news-title"'), home.indexOf('class="home-news-list"'))
check(newsHead.includes('href="/news">全部新聞 →</a>') && !newsHead.includes('eyebrow'), `重點新聞標題列：標題與「全部新聞 →」: ${text(newsHead)}`)
const newsCount = count(columns, 'class="home-news-row"')
check(newsCount === 5, `重點新聞列 5 則（dashboard 有 6 則）: ${newsCount}`)
// Issue 510 AC-3: a news row is two lines: the title, then source · time and the direction; no tags, category or summary.
const newsRow = columns.slice(columns.indexOf('class="home-news-row"'), columns.indexOf('</article>', columns.indexOf('class="home-news-row"')))
check(/<h3 class="home-news-title"><a [^>]*title="[^"]+"/.test(newsRow) && newsRow.includes('class="home-news-meta"') && newsRow.includes('class="home-news-impact"'), `新聞列：標題（全文在 title）、來源與時間、方向: ${newsRow.slice(0, 300)}`)
check(!newsRow.includes('news-chips') && !newsRow.includes('news-card-summary') && !newsRow.includes('news-card-meta') && !newsRow.includes('news-ai-candidates'), '新聞列不放已核實標的 tag、摘要、分類與 AI 候選行（在 /news）')
check((newsRow.match(/<(h3|div) class="home-news-/g) ?? []).length === 3, '新聞列只有標題、來源時間、方向三塊（排成兩行）')

// ---- 今日可買 (Issue 510): one list at every width, the group on one line, the #491 sentence under the name ----
const list = render('/', <CandidatesSection data={listResponse()} loading={false} error={null} />)
check(!list.includes('<table') && list.includes('<ol class="candidate-list"'), `今日可買是同一份清單，不是表格: ${list.slice(0, 200)}`)
const firstRow = list.slice(list.indexOf('data-candidate-rank="1"'), list.indexOf('data-candidate-rank="2"'))
const titleLine = firstRow.slice(firstRow.indexOf('<p class="candidate-row-title"'), firstRow.indexOf('</p>'))
check(text(titleLine).trim() === '#1 2377 微星 上市 · AI 伺服器（題材 #2）', `標題列是「#名次 代號 名稱 市場 · 族群（榜 #名次）」一行: ${text(titleLine)}`)
const plan = firstRow.slice(firstRow.indexOf('aria-label="進場方式"'), firstRow.indexOf('</section>', firstRow.indexOf('aria-label="進場方式"')))
check(plan.includes('data-entry-plan="levels"') && text(plan).includes('突破型') && text(plan).includes('161.50 元') && text(plan).includes('157.82 元') && text(plan).includes('167.39 元'),
  `名稱下一行是進場句: ${text(plan).slice(0, 300)}`)
check(!plan.includes('entry-plan-conditions') && firstRow.indexOf('entry-plan-conditions') > firstRow.indexOf('candidate-detail-folds'), '進場句不帶完整條件（在明細的收合列）')
check(count(list, 'aria-label="進場方式"') === listResponse().items.length, `每檔只有一份進場句: ${count(list, 'aria-label="進場方式"')}`)

// ---- first_trading_day reads 掛牌首日: a market transfer also starts a new listing row (#475 review) ----
check(noPreviousCloseText('first_trading_day') === '掛牌首日', `first_trading_day: ${noPreviousCloseText('first_trading_day')}`)

// ---- the navbar date on every page comes from /api/data-date, not the whole dashboard (Issue 601) ----
{
  // Server rendering registers the shell's queries without running them; run each queryFn against a fetch that
  // only records the URL (get() calls fetch before its first await) and never settles.
  const shellClient = new QueryClient()
  render('/strategy', <Shell><p>page</p></Shell>, shellClient)
  const requested: string[] = []
  const realFetch = globalThis.fetch
  globalThis.fetch = ((input: RequestInfo | URL) => { requested.push(String(input)); return new Promise<Response>(() => undefined) }) as typeof fetch
  try {
    for (const query of shellClient.getQueryCache().getAll()) {
      const queryFn = query.options.queryFn
      if (typeof queryFn === 'function') void (queryFn as (context: unknown) => Promise<unknown>)({ queryKey: query.queryKey, signal: new AbortController().signal, meta: undefined, client: shellClient })
    }
  } finally {
    globalThis.fetch = realFetch
  }
  check(requested.some((url) => url.endsWith('/data-date')), `Shell 的導覽列日期打 /data-date: ${JSON.stringify(requested)}`)
  check(!requested.some((url) => url.includes('/dashboard')), `Shell 不請求 /dashboard: ${JSON.stringify(requested)}`)
  const dated = new QueryClient()
  dated.setQueryData(['data-date'], { as_of: '2026-11-09' })
  check(text(render('/strategy', <Shell><p>page</p></Shell>, dated)).includes('2026/11/09'), '導覽列顯示 /data-date 的 as_of')
}

// ---- layout rules the static markup cannot show ----
const css = fs.readFileSync(path.join(__dirname, 'styles.css'), 'utf8')
const rule = (selector: string) => { const at = css.indexOf(selector + ' {'); return at < 0 ? '' : css.slice(at, css.indexOf('}', at)) }
check(/align-items:\s*stretch/.test(rule('.home-columns')), `.home-columns 兩欄等高: ${rule('.home-columns')}`)
check(!css.includes('.candidate-table') && !css.includes('.candidate-cards'), 'Issue 510: no table or card styles left for the today list')
check(/white-space:\s*nowrap/.test(rule('.entry-plan-sentence b')), '進場句的價位不拆行（長句在價位之間換行，不切字）')

if (failures.length) throw new Error(`${failures.length} of ${checks} navigation checks failed:\n- ${failures.join('\n- ')}`)
