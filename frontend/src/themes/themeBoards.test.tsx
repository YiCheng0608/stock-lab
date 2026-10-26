import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'

import { productTime, unknownRole } from '../news/news.fixtures'
import { readChartTheme } from '../stock/stockBars'
import type { ThemeBoardEmptyReason } from '../types'
import {
  DEFAULT_MEMBER_SORT,
  MEMBER_PAGE_SIZE,
  MEMBER_SORTS,
  THEME_BOARD_LIMIT,
  TODAY_BOARD_LIMIT,
  boardDates,
  boardPagePath,
  buildTrendChartOption,
  evidenceUrl,
  filterBoardItems,
  formatComponent,
  formatTrendTooltip,
  memberQuery,
  memberTableNote,
  memberTableRows,
  parseBoard,
  qualityLabel,
  relativeReturn,
  themeBoardPath,
  themeDefinitionVersion,
  trendHasEnoughPoints,
} from './themeBoards'
import { EMPTY_MESSAGES, boardItem, emptyBoard, industryBoard, membersPage, newsItems, themeBoard, themeDetail, trend } from './themeBoards.fixtures'
import { HotGroupsSection, ThemeDetailView, ThemeNewsList, ThemesBoardView } from './ThemeViews'

// Standalone regression module (no browser, no server, no network) for the group boards (#179): /themes with the
// industry and theme boards, /themes/:id with trend, components, members and news, and the today Top 10 section.
const check = (condition: boolean, message: string) => { if (!condition) throw new Error(message) }
const render = (element: ReactElement) => renderToStaticMarkup(<StaticRouter location="/">{element}</StaticRouter>)
const noop = () => undefined
const count = (markup: string, needle: string) => markup.split(needle).length - 1

// ---- AC-1 request parameters: each tab asks for its own board ----
check(themeBoardPath('industry') === `/themes?board=industry&limit=${THEME_BOARD_LIMIT}` && THEME_BOARD_LIMIT === 100, 'board page asks for the whole industry board')
check(themeBoardPath('theme') === '/themes?board=theme&limit=100', 'theme tab switches only the board parameter')
check(themeBoardPath('theme', TODAY_BOARD_LIMIT) === '/themes?board=theme&limit=5', 'today asks for the Top 5')
check(parseBoard(null) === 'industry' && parseBoard('theme') === 'theme' && parseBoard('etf') === 'industry', 'industry is the default board; unknown values fall back to it')
check(boardPagePath('industry') === '/themes' && boardPagePath('theme') === '/themes?board=theme', 'full-ranking link keeps the current tab')

// ---- AC-1 formatting rules ----
check(formatComponent(0.9) === '90' && formatComponent(0) === '0' && formatComponent(null) === '—', 'components on 0–100, null is 「—」 never 0')
check(JSON.stringify(relativeReturn(0.0123, '%')) === JSON.stringify({ text: '+1.23%', tone: 'up' }), 'positive return: + sign, up (red) tone')
check(JSON.stringify(relativeReturn(-0.0045)) === JSON.stringify({ text: '-0.45', tone: 'down' }), 'negative return: - sign, down (green) tone')
check(relativeReturn(0).tone === 'flat' && relativeReturn(0).text === '0.00' && relativeReturn(null).text === '—', 'zero is flat; missing is 「—」')
check(qualityLabel('complete') === '熱門族群' && qualityLabel('partial') === '技術與籌碼觀察（事件資料待補）', 'quality copy follows UI_COPY §3')
const dates = boardDates(themeBoard().meta)
check(dates.trading === '2026/09/08' && dates.dataAsOf === '2026/09/09', 'official data date is added when it differs')
check(boardDates(industryBoard().meta).dataAsOf === null, 'same-day data date is not repeated')
check(filterBoardItems(industryBoard().items, '電子').map((item) => item.theme_id).join() === 'industry-28', 'search filters the board by name')

// ---- AC-1 board page markup ----
const industryMarkup = render(<ThemesBoardView board="industry" onBoardChange={noop} search="" onSearchChange={noop} data={industryBoard()} loading={false} error={null} />)
check(industryMarkup.includes('id="board-tab-industry" aria-selected="true"') && industryMarkup.includes('id="board-panel-industry"'), 'industry tab selected by default with its panel')
const industryRow = industryMarkup.slice(industryMarkup.indexOf('data-theme-id="industry-24"'), industryMarkup.indexOf('</tr>', industryMarkup.indexOf('data-theme-id="industry-24"')))
for (const text of ['>1<', '半導體業', '熱門族群', '81.25', '>90<', '>75<', '>50<', '>25<', '>100<', 'tone-up">+1.23<', 'tone-down">-0.45<', 'tone-flat">0.00<', '12／14']) {
  check(industryRow.includes(text), `industry row shows ${text}: ${industryRow}`)
}
check(industryRow.includes('href="/themes/industry-24"'), 'row links to the detail page')
const partialRow = industryMarkup.slice(industryMarkup.indexOf('data-theme-id="industry-28"'), industryMarkup.indexOf('</tr>', industryMarkup.indexOf('data-theme-id="industry-28"')))
check(partialRow.replace(/<[^>]+>/g, '').includes('技術與籌碼觀察（事件資料待補）') && !partialRow.includes('熱門族群'), 'partial row is not called a hot group')
check(count(partialRow, '>—<') === 3, `null breadth, catalyst and 20d return show 「—」: ${partialRow}`)
check(industryMarkup.includes('資料 2026/09/08') && !industryMarkup.includes('官方資料 '), 'board date badge')
check(!industryMarkup.includes('待重新核實') && !industryMarkup.includes('class="data-gap"'), 'industry board shows no temporary verification notice')
check(industryMarkup.includes('class="board-cards"') && count(industryMarkup, 'class="board-card"') === 2, 'phone cards render every row')

const themeMarkup = render(<ThemesBoardView board="theme" onBoardChange={noop} search="" onSearchChange={noop} data={themeBoard()} loading={false} error={null} />)
check(themeMarkup.includes('id="board-tab-theme" aria-selected="true"') && themeMarkup.includes('id="board-tab-industry" aria-selected="false"') && themeMarkup.includes('id="board-panel-theme"'), 'theme tab selected')
check(themeMarkup.includes('CoWoS 先進封裝') && !themeMarkup.includes('半導體業'), 'theme board shows only theme rows')
check(themeMarkup.includes('資料 2026/09/08') && themeMarkup.includes('官方資料 2026/09/09'), 'score date and differing data date badges')
const searched = render(<ThemesBoardView board="industry" onBoardChange={noop} search="不存在" onSearchChange={noop} data={industryBoard()} loading={false} error={null} />)
check(searched.includes('沒有符合的族群') && !searched.includes('data-theme-id'), 'a search with no match says so')

// ---- AC-1 empty boards show the API message verbatim ----
for (const reason of Object.keys(EMPTY_MESSAGES) as ThemeBoardEmptyReason[]) {
  const markup = render(<ThemesBoardView board="theme" onBoardChange={noop} search="" onSearchChange={noop} data={emptyBoard('theme', reason)} loading={false} error={null} />)
  check(markup.includes(EMPTY_MESSAGES[reason]) && !markup.includes('<table'), `empty board ${reason} shows empty_message`)
}

// ---- AC-2 trend chart ----
const twenty = trend(20)
check(trendHasEnoughPoints(twenty) && !trendHasEnoughPoints(trend(1)) && !trendHasEnoughPoints([{ ...twenty[0] }, { ...twenty[1], score: null }]), 'at least 2 scored points draw a chart')
const theme = readChartTheme((token) => `token(${token})`)
const option = buildTrendChartOption(twenty, theme)
const xData = (option.xAxis as { data: string[] }).data
const series = option.series[0]
check(xData.length === 20 && xData[0] === '08/12' && xData[19] === '08/31', `x axis carries the 20 dates in order: ${xData.join()}`)
check((series.data as number[]).join() === twenty.map((point) => point.score).join(), 'series carries the scores')
check(series.lineStyle.color === 'token(--color-primary)' && series.lineStyle.width === 2 && series.areaStyle.opacity === 0.25, 'single line: primary 2px with a 25% fill')
check(option.yAxis.min === 0 && option.yAxis.max === 100, 'score axis is 0–100')
const withGap = buildTrendChartOption([...twenty.slice(0, 2), { ...twenty[2], score: null }], theme)
check((withGap.series[0].data as Array<number | string>)[2] === '-', 'a missing score is a gap, not 0')
const tooltip = formatTrendTooltip({ trading_date: '2026-09-08', score: 72.5, rank: 3, quality: 'partial', eligible_members: 8 })
check(tooltip.includes('2026/09/08') && tooltip.includes('排名 #3') && tooltip.includes('技術與籌碼觀察') && tooltip.includes('有效成員 8 檔'), `tooltip: ${tooltip}`)

// ---- AC-2 detail page ----
const loaded = <T,>(data: T) => ({ data, loading: false, error: null })
const detailMarkup = render(<ThemeDetailView detail={themeDetail()} board={loaded(themeBoard())} members={loaded(membersPage())} onMemberPageChange={noop} news={loaded({ items: newsItems(3) })} />)
check(detailMarkup.includes('<h1>CoWoS 先進封裝</h1>') && detailMarkup.includes('>題材<') && detailMarkup.includes('#1') && detailMarkup.includes('72.50'), 'header: name, board badge, rank and score from the board')
check(detailMarkup.includes('題材表版本 themes_v1:2026.10.17'), 'theme table version comes from member evidence')
check(detailMarkup.includes('熱度走勢') && !detailMarkup.includes('走勢資料不足') && detailMarkup.includes('查看走勢資料表'), '20-day trend draws the chart')
const components = detailMarkup.slice(detailMarkup.indexOf('五分項'))
check(['相對報酬', '廣度', '量能', '法人', '催化劑'].every((label) => components.includes(label)) && components.includes('<b>100</b>') && components.includes('<b>—</b>'), 'five components with null as 「—」')
check(detailMarkup.includes('台積電') && detailMarkup.includes('1,085') && detailMarkup.includes('萬潤'), 'member table reads the paginated page')
check(detailMarkup.includes('<th>證據</th>') && detailMarkup.includes('主要業務 · 關聯度高') && detailMarkup.includes('產品線 · 關聯度低'), 'theme members carry an evidence column')
check(detailMarkup.includes('href="https://example.test/cowos" target="_blank" rel="noopener noreferrer"'), 'evidence link opens a new tab')
check(!detailMarkup.includes('javascript:') && detailMarkup.includes('來源連結未提供'), 'non-http evidence is not linked')
check(detailMarkup.includes('第 2／2 頁') && detailMarkup.includes('共 34 檔'), 'member pagination')
check(!detailMarkup.includes('弘塑'), 'inline members are not shown once a page arrived')
check(count(detailMarkup, 'href="/news/') === 3 && detailMarkup.includes('公開資訊觀測站公告'), 'related news list')
// #203 AC-1: related news time reads product_time like the news page — Taipei time for a known instant, the event day for date-only.
const timeCell = (markup: string, title: string) => {
  const row = markup.slice(markup.lastIndexOf('<li', markup.indexOf(title)), markup.indexOf('</li>', markup.indexOf(title)))
  return row.slice(row.indexOf('news-list-time'), row.indexOf('</span>', row.indexOf('news-list-time')))
}
const relatedItems = newsItems(3)
check(timeCell(detailMarkup, 'CoWoS 擴產公告 1').includes('事件日 2026/09/08') && !timeCell(detailMarkup, 'CoWoS 擴產公告 1').includes('00:00'), 'date-only official event shows the event day without hours')
check(relatedItems[1].product_time?.roles.published_at.utc === '2026-10-17T13:30:00+00:00' && timeCell(detailMarkup, 'CoWoS 擴產公告 2').includes('發布於 2026/10/17 21:30'), 'published_at 13:30 UTC shows 21:30 Taipei')
check(timeCell(detailMarkup, 'CoWoS 擴產公告 3').includes('發布於 2026/10/18 00:05') && timeCell(detailMarkup, 'CoWoS 擴產公告 3').includes('dateTime="2026-10-17T16:05:00+00:00"'), 'a UTC evening instant is already the next day in Taipei')
check(!detailMarkup.includes('發布日'), 'no UTC-date 「發布日」 wording is left')
const naiveRelated = render(<ThemeNewsList items={[{ ...relatedItems[1], published_at: '2026-10-17T13:30:00', product_time: productTime({ published_at: unknownRole('published_at', 'published_at_naive_timezone_missing') }) }]} />)
check(naiveRelated.includes('來源時間待核實') && !naiveRelated.includes('2026/10/17'), 'a naive source time stays 待核實 and is never cut to a date')
const noTimeRelated = render(<ThemeNewsList items={[{ ...relatedItems[1], published_at: null, product_time: productTime() }]} />)
check(noTimeRelated.includes('來源時間未提供'), 'no source time at all')
// #186 AC-5: the related news list names the real source; a media item is never shown as 「官方公告資料」.
const relatedNews = detailMarkup.slice(detailMarkup.indexOf('theme-news-list'))
const mediaRow = relatedNews.slice(relatedNews.indexOf('CoWoS 擴產公告 3'))
check(count(relatedNews, '公開資訊觀測站公告') === 2, 'official rows keep the official source label')
check(mediaRow.includes('<span class="small-note">中央社</span>'), `media row shows its own source name: ${mediaRow}`)
check(!relatedNews.includes('官方公告資料'), 'no related news row falls back to 「官方公告資料」')
const mediaOnly = render(<ThemeNewsList items={[{ ...newsItems(3)[2], source_name: '  ' }]} />)
check(mediaOnly.includes('來源未提供') && !mediaOnly.includes('官方公告資料'), 'a media row without a name says 來源未提供')

const oneDay = render(<ThemeDetailView detail={themeDetail({ trendDays: 1 })} board={loaded(themeBoard())} members={loaded(membersPage())} onMemberPageChange={noop} news={loaded({ items: [] })} />)
check(oneDay.includes('走勢資料不足') && !oneDay.includes('查看走勢資料表'), '1-day trend shows the empty state')
check(oneDay.includes('此族群尚無已核實關聯的新聞'), 'zero news shows the empty state')

const waiting = { data: undefined, loading: true, error: null }
const inline = render(<ThemeDetailView detail={themeDetail()} board={loaded(themeBoard())} members={waiting} onMemberPageChange={noop} news={loaded({ items: [] })} />)
check(inline.includes('/stocks/TWSE/2330') && inline.includes('弘塑'), 'inline members stand in until the page arrives')
const truncated = render(<ThemeDetailView detail={themeDetail({ truncated: true })} board={loaded(themeBoard())} members={waiting} onMemberPageChange={noop} news={loaded({ items: [] })} />)
check(!truncated.includes('弘塑') && !truncated.includes('/stocks/TWSE/2330') && truncated.includes('成員載入中'), 'members_truncated=true never renders the inline list')
check(memberTableRows(themeDetail({ truncated: true }), undefined) === null && memberTableRows(themeDetail(), undefined)?.length === 2, 'member source rule')
check(MEMBER_PAGE_SIZE === 30, 'member page size')

const industryDetail = { ...themeDetail(), board: 'industry', theme: { ...themeDetail().theme, theme_id: 'industry-99', display_name: '玻璃陶瓷' }, members: [] }
const offBoard = render(<ThemeDetailView detail={industryDetail} board={loaded(industryBoard())} members={loaded({ ...membersPage(), items: [] })} onMemberPageChange={noop} news={loaded({ items: [] })} />)
check(offBoard.includes('未列入本日榜單') && offBoard.includes('不在本日產業榜') && !offBoard.includes('<th>證據</th>'), 'a group off the board: no rank, no evidence column for industries')
check(!offBoard.includes('待重新核實') && !offBoard.includes('class="data-gap"') && !offBoard.includes('題材表版本'), 'industry detail shows no temporary verification notice and no theme table version')
// ---- #280 member table: columns, sort, stale day, blanks and phone cards (UI_COPY_SPEC §8.5) ----
const strip = (markup: string) => markup.replace(/<[^>]+>/g, '')
const tableOf = (markup: string) => markup.slice(markup.indexOf('member-table-wrap'), markup.indexOf('</table>', markup.indexOf('member-table-wrap')))
const headersOf = (markup: string) => [...tableOf(markup).matchAll(/<th[^>]*>([\s\S]*?)<\/th>/g)].map((match) => strip(match[1]))
const rowOf = (markup: string, symbol: string) => {
  const table = tableOf(markup)
  const at = table.indexOf(`/${symbol}"`)
  return table.slice(table.lastIndexOf('<tr', at), table.indexOf('</tr>', at))
}
const cellsOf = (row: string) => [...row.matchAll(/<td[^>]*>([\s\S]*?)<\/td>/g)].map((match) => strip(match[1]))
// Default sort and the request: turnover first, page and sort travel together, the options name every sort.
check(DEFAULT_MEMBER_SORT === 'turnover', 'the member table sorts by turnover by default')
check(JSON.stringify(memberQuery(2, 'return_5d')) === JSON.stringify({ page: 2, page_size: MEMBER_PAGE_SIZE, sort: 'return_5d' }), 'a member page asks for its sort')
check(MEMBER_SORTS.map((option) => option.id).join() === 'turnover,change_pct,return_5d,return_20d,symbol', 'sort options')
check(MEMBER_SORTS.map((option) => option.label).join() === '成交值,漲跌幅,5 日相對,20 日相對,代號', 'sort option labels')
check(detailMarkup.includes('aria-label="成員排序"') && detailMarkup.includes('<option value="turnover" selected="">成交值</option>'), 'the sort select shows turnover by default')
const bySort = render(<ThemeDetailView detail={themeDetail()} board={loaded(themeBoard())} members={loaded(membersPage())} memberSort="change_pct" onMemberSortChange={noop} onMemberPageChange={noop} news={loaded({ items: [] })} />)
check(bySort.includes('<option value="change_pct" selected="">漲跌幅</option>') && !bySort.includes('<option value="turnover" selected="">'), 'another sort is selected when chosen')
check(bySort.includes('第 2／2 頁') && bySort.includes('下一頁'), 'paging stays under a chosen sort')
// Theme board: role only as the 領先成員 badge in the name cell, evidence stays last.
check(headersOf(detailMarkup).join('|') === '代號|名稱|市場|收盤|漲跌幅|成交值|5 日相對|20 日相對|證據', `theme member headers: ${headersOf(detailMarkup).join('|')}`)
const leader = rowOf(detailMarkup, '2330')
const leaderCells = cellsOf(leader)
check(leaderCells[1].includes('台積電') && leaderCells[1].includes('候選 #3') && leaderCells[1].includes('領先成員'), `leader name cell carries its badges: ${leaderCells[1]}`)
check(leaderCells.slice(3, 8).join('|') === '1,085.00|+1.40|325.12|+1.23|-0.45', `leader numbers: ${leaderCells.join('|')}`)
check(leader.includes('tone-up">+1.40<') && leader.includes('tone-down">-0.45<'), 'change and returns are red up, green down')
check(leaderCells[8].includes('主要業務 · 關聯度高'), 'evidence column unchanged')
check(cellsOf(rowOf(detailMarkup, '3711'))[1].includes('條件成立') && !cellsOf(rowOf(detailMarkup, '3711'))[1].includes('候選'), 'a conditional member that is not a candidate reads 條件成立')
check(!cellsOf(rowOf(detailMarkup, '6187'))[1].includes('條件成立') && !cellsOf(rowOf(detailMarkup, '6187'))[1].includes('領先成員'), 'no badge without a status')
const unverified = cellsOf(rowOf(detailMarkup, '3711'))
check(unverified.slice(3, 8).join('|') === '151.50|||-0.20|0.00', `unverified change and unavailable turnover are blank: ${unverified.join('|')}`)
// A member whose latest bar is older than members_as_of: its date under the close, change and turnover blank.
const stale = cellsOf(rowOf(detailMarkup, '6187'))
check(stale[3] === '210.50資料 2026/09/05' && stale.slice(4, 8).join('|') === '|||', `stale member: ${stale.join('|')}`)
check(!leader.includes('資料 2026/09/08'), 'a same-day member has no date mark')
check(!cellsOf(rowOf(detailMarkup, '6640'))[3], 'a member without any bar has a blank close')
// Units and blank reasons outside the table (shown above both the table and the phone cards), only for what this page shows.
const noteAt = detailMarkup.indexOf('class="table-note member-note"')
check(noteAt >= 0 && noteAt < detailMarkup.indexOf('member-table-wrap') && noteAt < detailMarkup.indexOf('class="member-cards"'), 'the member note precedes the table and the cards')
const memberNote = strip(detailMarkup.slice(detailMarkup.indexOf('>', noteAt) + 1, detailMarkup.indexOf('</p>', noteAt)))
check(memberNote.startsWith('單位：收盤為各標的報價幣別的元，成交值為億元；漲跌幅與 5／20 日相對加權指數的報酬為 %。'), `member unit note: ${memberNote.slice(0, 80)}`)
for (const sentence of ['漲跌幅空白表示漲跌待核實。', '成交值空白表示成交金額未取得。', '5／20 日相對空白表示未列入當日族群計分。', '收盤下方的「資料 YYYY/MM/DD」表示該檔沒有成員資料日的日線，漲跌幅與成交值留空。', '收盤空白表示該檔尚無日線。']) {
  check(memberNote.includes(sentence), `member note says ${sentence}`)
}
check(!memberNote.includes('成交金額待核實'), 'an unknown turnover sentence only when a row is unknown')
check(memberTableNote([{ ...membersPage().items[0] }], '2026-09-08') === '單位：收盤為各標的報價幣別的元，成交值為億元；漲跌幅與 5／20 日相對加權指數的報酬為 %。', 'no blank, no blank sentence')
check(memberTableNote([{ ...membersPage().items[0], turnover: null, turnover_status: 'unknown' }], '2026-09-08').endsWith('成交值空白表示成交金額待核實。'), 'unknown turnover reads 待核實')
// Industry board: no role column, no evidence column.
const industryMembers = render(<ThemeDetailView detail={industryDetail} board={loaded(industryBoard())} members={loaded(membersPage())} onMemberPageChange={noop} news={loaded({ items: [] })} />)
check(headersOf(industryMembers).join('|') === '代號|名稱|市場|收盤|漲跌幅|成交值|5 日相對|20 日相對', `industry member headers: ${headersOf(industryMembers).join('|')}`)
check(!cellsOf(rowOf(industryMembers, '2330'))[1].includes('領先成員') && cellsOf(rowOf(industryMembers, '2330'))[1].includes('候選 #3'), 'industries show no role, keep the candidate badge')
// 390: one card per member, title row with close and change, then three cells.
const cards = detailMarkup.slice(detailMarkup.indexOf('class="member-cards"'), detailMarkup.indexOf('pagination-controls', detailMarkup.indexOf('class="member-cards"')))
check(count(cards, 'class="member-card"') === membersPage().items.length, 'one phone card per member')
const leaderCard = cards.slice(cards.indexOf('class="member-card"'), cards.indexOf('class="member-card"', cards.indexOf('class="member-card"') + 1))
check(strip(leaderCard).includes('2330 台積電') && leaderCard.includes('1,085.00') && leaderCard.includes('tone-up">+1.40%<'), `card title row: ${strip(leaderCard)}`)
check(['成交值', '5 日相對', '20 日相對'].every((label) => leaderCard.includes(`<dt>${label}</dt>`)) && leaderCard.includes('<dd>325.12</dd>'), 'card has the three cells')
check(leaderCard.includes('主要業務 · 關聯度高'), 'theme cards keep the evidence')
check(strip(cards).includes('資料 2026/09/05'), 'a stale card shows its bar date')

check(themeDefinitionVersion({ ...themeDetail(), theme: { ...themeDetail().theme, definition_version: 'themes_v1:2026.10.18' } }) === 'themes_v1:2026.10.18', 'theme.definition_version wins when present')
check(evidenceUrl({ kind: null, url: 'http://x.test', relation: null, relevance: null, theme_version: null }) === 'http://x.test' && evidenceUrl(null) === null, 'evidence url rule')

// ---- today Top 5 compact rows (#276; UI_COPY_SPEC §8.5) ----
const topTen = { ...industryBoard(), items: Array.from({ length: 5 }, (_, index) => boardItem({ theme_id: `industry-${index + 1}`, display_name: `產業 ${index + 1}`, rank: index + 1 })) }
const today = render(<HotGroupsSection board="industry" onBoardChange={noop} data={topTen} loading={false} error={null} />)
check(count(today, 'class="hot-group-row"') === 5 && !today.includes('feature-card'), 'five compact rows, no feature cards')
check(today.includes('各榜前 5 名'), 'eyebrow says Top 5')
check(today.includes('href="/themes/industry-1"') && today.includes('href="/themes/industry-5"'), 'rows link to the detail page')
check(today.includes('href="/themes">查看完整排行'), 'full ranking link for the industry tab')
const firstCard = today.slice(today.indexOf('data-theme-id="industry-1"'), today.indexOf('data-theme-id="industry-2"'))
for (const text of ['第 1 名', '產業 1', '熱門族群', '81.25', '+1.23%', '-0.45%', '0.00%', '資料 2026/09/08']) check(firstCard.includes(text), `today card shows ${text}: ${firstCard}`)
const todayTheme = render(<HotGroupsSection board="theme" onBoardChange={noop} data={themeBoard()} loading={false} error={null} />)
check(todayTheme.includes('id="today-board-tab-theme" aria-selected="true"') && todayTheme.includes('href="/themes?board=theme">查看完整排行') && todayTheme.includes('CoWoS 先進封裝'), 'theme tab and its full-ranking link')
const todayEmpty = render(<HotGroupsSection board="industry" onBoardChange={noop} data={emptyBoard('industry', 'no_ranked_groups')} loading={false} error={null} />)
check(todayEmpty.includes(EMPTY_MESSAGES.no_ranked_groups) && !todayEmpty.includes('hot-group-row'), 'today empty board shows empty_message')
