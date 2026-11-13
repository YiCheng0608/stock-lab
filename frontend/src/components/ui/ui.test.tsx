import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'

import { Navbar, stockSearchPath } from '../Navbar'
import { PageDateContext, sameDay } from '../pageDate'
import { SuggestPopup, suggestAnnouncement } from '../NavSearch'
import { Badge, Button, Card, DataTable, DateBadge, EmptyState, MarketWidget, ScoreBar, Skeleton, Stat, StrengthChip, Tabs, strengthOf } from '.'

// Standalone regression module (no browser, no server): one minimal render check per ui component
// (DESIGN_SYSTEM §5) and the navbar (§4).
const check = (condition: boolean, message: string) => { if (!condition) throw new Error(message) }
const html = renderToStaticMarkup

// Card: card class, optional eyebrow / title / aside header.
const card = html(<Card eyebrow="籌碼資料" title="法人與融資" aside={<DateBadge date="2026-10-16" />}><p>內容</p></Card>)
check(card.startsWith('<section class="card"') && card.includes('card-eyebrow') && card.includes('<h3 class="card-title">法人與融資</h3>') && card.includes('card-aside'), `Card: ${card}`)
check(!html(<Card>x</Card>).includes('card-head'), 'Card without header renders no header row')

// Badge: tone variants, dot, data-date badge.
check(html(<Badge>上市</Badge>) === '<span class="badge">上市</span>', 'Badge default')
check(html(<Badge tone="warning" dot pulse>更新中</Badge>).includes('class="badge badge-warning"') && html(<Badge tone="warning" dot pulse>更新中</Badge>).includes('badge-dot badge-dot-pulse'), 'Badge tone + pulsing dot')
check(html(<DateBadge date="2026-10-16" />).includes('資料 2026/10/16'), 'DateBadge shows the API date as YYYY/MM/DD')
check(html(<DateBadge date={null} />).includes('badge-warning') && html(<DateBadge date={null} />).includes('資料日期未提供') && !html(<DateBadge date={null} />).includes('待核實'), 'DateBadge without a date says none was provided instead of inventing one (Issue 465: not 待核實)')
check(html(<DateBadge date={null} unavailable />).includes('資料日期暫時無法載入'), 'DateBadge whose request failed says so')
// #661 (DESIGN_SYSTEM §7): the navbar states the page date once; a card badge of that day is left out, another day,
// a missing date or an unknown page date still shows (decision 6835320079 conditions 1 and 2).
const onPage = (day: string | null, node: ReactElement) => html(<PageDateContext.Provider value={day}>{node}</PageDateContext.Provider>)
check(onPage('2026-10-16', <DateBadge date="2026-10-16" />) === '', 'DateBadge of the page date renders nothing')
check(onPage('2026-10-16', <DateBadge date="2026/10/16" />) === '', 'DateBadge of the page date, already formatted, renders nothing')
check(onPage('2026-10-16', <DateBadge date="2026-10-13" />).includes('資料 2026/10/13'), 'DateBadge of another day than the page still shows')
check(onPage(null, <DateBadge date="2026-10-16" />).includes('資料 2026/10/16'), 'DateBadge with no known page date (loading, failed, none) shows as before')
check(onPage('2026-10-16', <DateBadge date={null} />).includes('資料日期未提供') && onPage('2026-10-16', <DateBadge date={null} unavailable />).includes('資料日期暫時無法載入'), 'a missing or failed date still says so on a page with a date')
check(onPage('2026-10-16', <DateBadge date="2026-10-16" always />).includes('資料 2026/10/16'), 'the navbar badge (always) shows the page date')
check(!sameDay('2026-10-16', null) && !sameDay(null, '2026-10-16') && !sameDay('待核實', '2026-10-16') && sameDay('2026-10-16T09:00:00', '2026-10-16'), 'sameDay: only two known days that match')

// Button: variants, size, default type=button.
check(html(<Button variant="primary">送出</Button>) === '<button type="button" class="btn btn-primary">送出</button>', 'Button primary')
check(html(<Button>取消</Button>).includes('btn btn-secondary'), 'Button defaults to secondary')
check(html(<Button variant="ghost" size="sm" type="submit">更多</Button>).includes('type="submit" class="btn btn-ghost btn-sm"'), 'Button ghost small submit')

// DataTable: card container, note above, one column definition puts num on th and td.
const table = html(<DataTable note="單位：張" rows={[1]} rowKey={(row) => row} columns={[{ key: 'v', header: '數值', num: true, cell: (row) => row }]} />)
check(table.startsWith('<div class="table-wrap"><p class="table-note">單位：張</p><table>') && table.includes('<th class="num">數值</th>') && table.includes('<td class="num">1</td>'), `DataTable: ${table}`)

// Tabs: tablist, selected tab, aria wiring.
const tabs = html(<Tabs items={[{ id: 'macd', label: 'MACD' }, { id: 'rsi', label: 'RSI' }]} value="rsi" onChange={() => undefined} label="指標面板" idPrefix="indicator" />)
check(tabs.includes('role="tablist"') && tabs.includes('aria-label="指標面板"'), 'Tabs tablist')
check(tabs.includes('id="indicator-tab-rsi" aria-selected="true" aria-controls="indicator-panel-rsi" tabindex="0" class="tab tab-active"'), `Tabs selected tab: ${tabs}`)
check(tabs.includes('id="indicator-tab-macd" aria-selected="false" aria-controls="indicator-panel-macd" tabindex="-1" class="tab"'), 'Tabs unselected tab')

// Stat / MarketWidget: mono value class, change tone.
check(html(<Stat label="候選" value="12" detail="今日" />).includes('<div class="stat-value">12</div>'), 'Stat value')
const widget = html(<MarketWidget label="加權指數" value="23,456" change="+1.20%" tone="up" />)
check(widget.includes('market-widget-value') && widget.includes('class="market-widget-change tone-up">+1.20%'), `MarketWidget: ${widget}`)

// EmptyState: 無資料 + reason.
const empty = html(<EmptyState reason="日線不足 60 根" />)
check(empty.includes('role="status"') && empty.includes('無資料') && empty.includes('日線不足 60 根'), 'EmptyState default title and reason')
check(html(<EmptyState title="指標尚未計算" />).includes('指標尚未計算') && !html(<EmptyState title="指標尚未計算" />).includes('empty-state-reason'), 'EmptyState custom title, no reason line')

// Skeleton: busy card with bars, no spinner.
const skeleton = html(<Skeleton lines={3} />)
check(skeleton.includes('aria-busy="true"') && skeleton.split('skeleton-bar').length - 1 === 3 && skeleton.includes('資料載入中…'), `Skeleton: ${skeleton}`)

// Navbar: five main links, search, data-date badge, hamburger toggle.
const navbar = html(<StaticRouter location="/stocks/TWSE/2330"><Navbar dataDate="2026-10-16" /></StaticRouter>)
check(['今日名單', '大盤', '我的追蹤', '族群', '個股', '策略說明'].every((label) => navbar.includes(`>${label}</a>`)) && !navbar.includes('>新聞</a>'), 'Navbar has the six main links and no 新聞 (Issue 493, Issue 631)')
check(navbar.includes('class="active" href="/stocks"') || navbar.includes('href="/stocks" class="active"') || /<a[^>]*aria-current="page"[^>]*href="\/stocks"/.test(navbar), `Navbar marks the current section: ${navbar}`)
check(navbar.includes('role="search"') && navbar.includes('資料 2026/10/16') && navbar.includes('aria-expanded="false"'), 'Navbar search, data date and menu toggle')
check(!html(<StaticRouter location="/"><Navbar dataDate={null} dataDateLoading /></StaticRouter>).includes('date-badge'), 'Navbar hides the badge while loading')
// #661 (decision 6835320079 condition 1): the page date sits on the bar outside the collapsible menu, so a phone sees it
// without opening the menu; it is the one badge even when a page date is known (always).
const menu = navbar.slice(navbar.indexOf('id="navbar-menu"'), navbar.indexOf('<span class="navbar-date">'))
check(navbar.includes('<span class="navbar-date"><span class="badge date-badge"') && !menu.includes('date-badge'), `Navbar: the date badge is outside the menu: ${navbar.slice(navbar.indexOf('navbar-date') - 40, navbar.indexOf('navbar-date') + 120)}`)
check(html(<PageDateContext.Provider value="2026-10-16"><StaticRouter location="/"><Navbar dataDate="2026-10-16" /></StaticRouter></PageDateContext.Provider>).includes('資料 2026/10/16'), 'Navbar keeps its badge on a page of that date')
// #465: a failed /api/dashboard (500/504 on the production copy under load) read 資料日期待核實.
const navbarError = html(<StaticRouter location="/actions"><Navbar dataDate={null} dataDateError /></StaticRouter>)
check(navbarError.includes('資料日期暫時無法載入') && !navbarError.includes('待核實'), `Navbar says the date could not load: ${navbarError}`)
// Issue 599: the navbar box is a combobox whose suggestions list code, name and market.
check(/<input[^>]*role="combobox"[^>]*aria-autocomplete="list"[^>]*aria-expanded="false"/.test(navbar) && !navbar.includes('aria-controls="nav-suggest-') && navbar.includes('aria-label="搜尋個股代號或名稱"') && navbar.includes('placeholder="代號或名稱"'), `Navbar search is a combobox: ${navbar}`)
const suggestState = { query: '23', status: 'ready' as const, active: 1, open: true, items: [{ exchange: 'TWSE', symbol: '2330', name: '台積電' }, { exchange: 'TPEx', symbol: '00723B', name: '群益投資級科技債' }] }
const popup = html(<SuggestPopup state={suggestState} listId="s" />)
check(popup.includes('<ul class="nav-suggest-list" id="s" role="listbox" aria-label="符合的股票">'), `SuggestPopup listbox: ${popup}`)
check(popup.split('role="option"').length - 1 === 2 && popup.includes('id="s-option-1" role="option" aria-selected="true"') && popup.includes('id="s-option-0" role="option" aria-selected="false"'), `SuggestPopup options and highlighted one: ${popup}`)
check(['2330', '台積電', '上市', '00723B', '群益投資級科技債', '上櫃'].every((value) => popup.includes(`>${value}</span>`)), `SuggestPopup shows code, name and market: ${popup}`)
const noMatch = html(<SuggestPopup state={{ ...suggestState, items: [] }} listId="s" />)
check(!noMatch.includes('role="status"') && noMatch.includes('沒有符合「23」的股票，按 Enter 到個股清單搜尋。') && !noMatch.includes('role="listbox"'), `SuggestPopup no match: ${noMatch}`)
const failed = html(<SuggestPopup state={{ ...suggestState, status: 'error', items: [] }} listId="s" />)
check(failed.includes('建議暫時無法載入，按 Enter 到個股清單搜尋。'), `SuggestPopup failure: ${failed}`)
// The live region stays in the navbar form and only its text changes (Issue 599 review).
check(/<p class="sr-only" role="status"><\/p><\/form>/.test(navbar), `Navbar keeps an empty live region: ${navbar}`)
check(suggestAnnouncement(suggestState) === '2 檔符合，按上下鍵選取。' && suggestAnnouncement({ ...suggestState, items: [] }) === '沒有符合「23」的股票，按 Enter 到個股清單搜尋。' && suggestAnnouncement({ ...suggestState, status: 'error', items: [] }) === '建議暫時無法載入，按 Enter 到個股清單搜尋。' && suggestAnnouncement({ ...suggestState, status: 'loading' }) === '', 'live region text: count, no match, failure, nothing while loading')
check(html(<SuggestPopup state={{ ...suggestState, status: 'loading' }} listId="s" />) === '' && html(<SuggestPopup state={{ ...suggestState, open: false }} listId="s" />) === '', 'SuggestPopup shows nothing while loading or closed')
check(stockSearchPath(' 2330 ') === '/stocks?q=2330' && stockSearchPath('台積 電') === '/stocks?q=%E5%8F%B0%E7%A9%8D%20%E9%9B%BB' && stockSearchPath('  ') === null, 'Navbar search path')

// ScoreBar (Issue 654, DESIGN_SYSTEM §5 分數橫條): fill share = value, the number beside it, no data draws no fill and reads 「—」.
const bar = html(<ScoreBar label="技術" value={74.6} />)
check(bar.includes('role="img"') && bar.includes('aria-label="技術 75（0–100）"') && bar.includes('data-score="75"'), `ScoreBar label and value: ${bar}`)
check(bar.includes('class="score-bar-fill" style="width:74.6%"') && bar.includes('<span class="score-bar-value" aria-hidden="true">75</span>'), `ScoreBar fill share and number: ${bar}`)
check(html(<ScoreBar label="x" value={0} />).includes('style="width:0%"') && html(<ScoreBar label="x" value={0} />).includes('>0</span>'), 'ScoreBar 0 is a known zero: empty fill, number 0')
check(html(<ScoreBar label="x" value={130} />).includes('width:100%') && html(<ScoreBar label="x" value={-5} />).includes('width:0%'), 'ScoreBar clamps the fill to the track')
for (const missing of [null, undefined, Number.NaN]) {
  const empty = html(<ScoreBar label="族群" value={missing} />)
  check(!empty.includes('score-bar-fill') && empty.includes('score-bar-empty') && empty.includes('>—</span>') && !empty.includes('>0<') && empty.includes('aria-label="族群 無資料"') && empty.includes('data-score="none"'), `ScoreBar without data: no fill, 「—」, never 0: ${empty}`)
}

// StrengthChip (Issue 675, DESIGN_SYSTEM §5 漲跌文字): plain text in the sign's colour, no block and no steps; the
// number and the aria-label with the window kept (Issue 654 drew a tinted block per step).
const signs: Array<[number | null, string, string]> = [
  [0.4, '+0.40%', 'up'], [0.999, '+1.00%', 'up'], [12.3, '+12.30%', 'up'],
  [-0.45, '-0.45%', 'down'], [-8, '-8.00%', 'down'],
  [0.001, '0.00%', 'flat'], [-0.004, '0.00%', 'flat'], [null, '—', 'none'], [Number.NaN, '—', 'none'],
]
for (const [percent, text, tone] of signs) {
  const view = strengthOf(percent)
  check(JSON.stringify(view) === JSON.stringify({ text, tone }), `strengthOf(${percent}) = ${JSON.stringify(view)}, want ${text} ${tone}`)
}
const upChip = html(<StrengthChip label="5 日相對加權指數" percent={3.5} />)
check(upChip === '<b class="strength-chip strength-up" role="img" aria-label="5 日相對加權指數 +3.50%" data-strength="up">+3.50%</b>', `StrengthChip up: ${upChip}`)
const downChip = html(<StrengthChip label="1 日相對加權指數" percent={-0.45} />)
check(downChip === '<b class="strength-chip strength-down" role="img" aria-label="1 日相對加權指數 -0.45%" data-strength="down">-0.45%</b>', `StrengthChip down: ${downChip}`)
const flatChip = html(<StrengthChip label="1 日相對加權指數" percent={0} />)
check(flatChip === '<b class="strength-chip strength-flat" role="img" aria-label="1 日相對加權指數 0.00%" data-strength="flat">0.00%</b>', `StrengthChip flat: ${flatChip}`)
const noneChip = html(<StrengthChip label="20 日相對加權指數" percent={null} />)
check(noneChip === '<b class="strength-chip strength-none" role="img" aria-label="20 日相對加權指數 無資料" data-strength="none">—</b>', `StrengthChip without data: ${noneChip}`)
