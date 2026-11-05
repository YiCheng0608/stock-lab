import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import * as AppModule from './App'
import { MAIN_NAV } from './components/Navbar'
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

// Information architecture (#493; PRODUCT_SPEC §2, DESIGN_SYSTEM §4/§5, UI_COPY_SPEC §5/§10/§11): the six main
// links, 觀察中 at /watch with /actions redirecting, the 策略說明 page, the 今日可買 home and its table and columns.
const failures: string[] = []
let checks = 0
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

// ---- main navigation: two pages that ask for action, three data pages, then the explanation ----
const nav = MAIN_NAV.map((item) => `${item.to} ${item.label}`)
const expectedNav = ['/ 今日可買', '/watch 觀察中', '/themes 族群', '/stocks 個股', '/news 新聞', '/strategy 策略說明']
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
check(!render('/actions', <App />).includes('找不到此頁'), '/actions 不是 404')
const redirect = (AppModule as Record<string, unknown>).watchRedirectPath as ((search: string, hash: string) => string) | undefined
check(typeof redirect === 'function' && redirect('?q=2330', '#plan-7') === '/watch?q=2330#plan-7' && redirect('', '') === '/watch',
  `/actions 轉 /watch 並保留查詢與錨點: ${typeof redirect === 'function' ? redirect('?q=2330', '#plan-7') : 'watchRedirectPath 不存在'}`)
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
check(!text(home).includes('明日候選') && !text(home).includes('關注標的'), '首頁不再有「明日候選」與「關注標的」')
const columns = home.slice(home.indexOf('home-columns'))
const panels = columns.match(/class="[^"]*\bhome-panel\b[^"]*"/g) ?? []
check(panels.length === 2, `熱門族群與重點新聞各是一張 home-panel 卡: ${panels.length}`)
const hotHead = home.slice(home.indexOf('id="hot-groups-title"'), home.indexOf('id="hot-groups-title"') + 1500)
check(/^[^]*?role="tablist"/.test(hotHead.slice(0, hotHead.indexOf('</div></div>') + 12)) || hotHead.split('section-head')[0].includes('role="tablist"'),
  '熱門族群的產業／題材 tab 在標題列內')
const newsCount = (columns.match(/class="[^"]*\bnews-card-compact\b/g) ?? []).length
check(newsCount === 5, `重點新聞列 5 則: ${newsCount}`)

// ---- 今日可買 table: 7 columns, the strategy type and levels in one 進場方式 column, the group on one line ----
const list = render('/', <CandidatesSection data={listResponse()} loading={false} error={null} />)
const table = list.slice(list.indexOf('<table'), list.indexOf('</thead>'))
const headers = (table.match(/<th[\s>]/g) ?? []).length
check(headers === 7, `今日可買表格 7 欄: ${headers}`)
for (const header of ['股票', '最近收盤（元）', '進場方式', 'RR', '總分（0–100）', '主要理由']) {
  check(text(table).replace(/\s/g, '').includes(header), `今日可買表格缺欄「${header}」: ${text(table)}`)
}
check(!text(table).includes('所屬族群') && !text(table).includes('名次'), `族群與名次併進股票欄: ${text(table)}`)
const body = list.slice(list.indexOf('<tbody'), list.indexOf('</table>'))
check(text(body).includes('#1 2377 微星') || text(body).includes('#1 2377 微星'.replace(' ', '  ')), `股票欄以名次開頭: ${text(body).slice(0, 200)}`)
check(text(body).includes('上市 · AI 伺服器（題材 #2）'), `股票欄第二行是「市場 · 族群（榜 #名次）」: ${text(body).slice(0, 300)}`)
check(text(body).includes('突破型') && text(body).includes('161.50') && text(body).includes('157.82') && text(body).replace(/\s/g, '').includes('167.39／172.54'),
  `進場方式欄有策略類型與進場、停損、目標一／二: ${text(body).slice(0, 400)}`)

// ---- 掛牌首日 replaces 新上市首日 (a market transfer also starts a new listing row, #475 review) ----
check(noPreviousCloseText('first_trading_day') === '掛牌首日', `first_trading_day: ${noPreviousCloseText('first_trading_day')}`)

// ---- layout rules the static markup cannot show ----
const css = fs.readFileSync(path.join(__dirname, 'styles.css'), 'utf8')
const rule = (selector: string) => { const at = css.indexOf(selector + ' {'); return at < 0 ? '' : css.slice(at, css.indexOf('}', at)) }
check(/align-items:\s*stretch/.test(rule('.home-columns')), `.home-columns 兩欄等高: ${rule('.home-columns')}`)
check(/table-layout:\s*fixed/.test(rule('.candidate-table')), `.candidate-table 固定欄寬: ${rule('.candidate-table')}`)

if (failures.length) throw new Error(`${failures.length} of ${checks} navigation checks failed:\n- ${failures.join('\n- ')}`)
