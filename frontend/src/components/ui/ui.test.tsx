import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'

import { Navbar, stockSearchPath } from '../Navbar'
import { SuggestPopup, suggestAnnouncement } from '../NavSearch'
import { Badge, Button, Card, DataTable, DateBadge, EmptyState, MarketWidget, Skeleton, Stat, Tabs } from '.'

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
check(['今日名單', '我的追蹤', '族群', '個股', '新聞', '策略說明'].every((label) => navbar.includes(`>${label}</a>`)), 'Navbar has the six main links (Issue 493)')
check(navbar.includes('class="active" href="/stocks"') || navbar.includes('href="/stocks" class="active"') || /<a[^>]*aria-current="page"[^>]*href="\/stocks"/.test(navbar), `Navbar marks the current section: ${navbar}`)
check(navbar.includes('role="search"') && navbar.includes('資料 2026/10/16') && navbar.includes('aria-expanded="false"'), 'Navbar search, data date and menu toggle')
check(!html(<StaticRouter location="/"><Navbar dataDate={null} dataDateLoading /></StaticRouter>).includes('date-badge'), 'Navbar hides the badge while loading')
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
