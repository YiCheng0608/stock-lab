import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'

import { readChartTheme } from '../stock/stockBars'
import type { ThemeBoardEmptyReason } from '../types'
import {
  MEMBER_PAGE_SIZE,
  THEME_BOARD_LIMIT,
  TODAY_BOARD_LIMIT,
  boardDates,
  boardPagePath,
  buildTrendChartOption,
  evidenceUrl,
  filterBoardItems,
  formatComponent,
  formatTrendTooltip,
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
check(themeBoardPath('theme', TODAY_BOARD_LIMIT) === '/themes?board=theme&limit=10', 'today asks for the Top 10')
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
check(partialRow.includes('技術與籌碼觀察（事件資料待補）') && !partialRow.includes('熱門族群'), 'partial row is not called a hot group')
check(count(partialRow, '>—<') === 3, `null breadth, catalyst and 20d return show 「—」: ${partialRow}`)
check(industryMarkup.includes('資料 2026/09/08') && !industryMarkup.includes('官方資料 '), 'board date badge')
check(industryMarkup.includes('既有族群關聯待重新核實'), 'industry board keeps the temporary verification notice')
check(industryMarkup.includes('class="board-cards"') && count(industryMarkup, 'class="board-card"') === 2, 'phone cards render every row')

const themeMarkup = render(<ThemesBoardView board="theme" onBoardChange={noop} search="" onSearchChange={noop} data={themeBoard()} loading={false} error={null} />)
check(themeMarkup.includes('id="board-tab-theme" aria-selected="true"') && themeMarkup.includes('id="board-tab-industry" aria-selected="false"') && themeMarkup.includes('id="board-panel-theme"'), 'theme tab selected')
check(themeMarkup.includes('CoWoS 先進封裝') && !themeMarkup.includes('半導體業'), 'theme board shows only theme rows')
check(themeMarkup.includes('資料 2026/09/08') && themeMarkup.includes('官方資料 2026/09/09'), 'score date and differing data date badges')
check(!themeMarkup.includes('既有族群關聯待重新核實'), 'theme board has no industry notice')
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
check(detailMarkup.includes('第 2／2 頁') && detailMarkup.includes('共 32 檔'), 'member pagination')
check(!detailMarkup.includes('弘塑'), 'inline members are not shown once a page arrived')
check(count(detailMarkup, 'href="/news/') === 3 && detailMarkup.includes('事件日 2026/09/08') && detailMarkup.includes('發布日 2026/09/07') && detailMarkup.includes('公開資訊觀測站公告'), 'related news list')
// #186 AC-5: the related news list names the real source; a media item is never shown as 「官方公告資料」.
const relatedNews = detailMarkup.slice(detailMarkup.indexOf('theme-news-list'))
const mediaRow = relatedNews.slice(relatedNews.indexOf('CoWoS 擴產公告 3'))
check(count(relatedNews, '公開資訊觀測站公告') === 2, 'official rows keep the official source label')
check(mediaRow.includes('<span class="small-note">中央社</span>'), `media row shows its own source name: ${mediaRow}`)
check(!relatedNews.includes('官方公告資料'), 'no related news row falls back to 「官方公告資料」')
const mediaOnly = render(<ThemeNewsList items={[{ ...newsItems(3)[2], source_name: '  ' }]} />)
check(mediaOnly.includes('來源未提供') && !mediaOnly.includes('官方公告資料'), 'a media row without a name says 來源未提供')
check(!detailMarkup.includes('既有族群關聯待重新核實'), 'theme detail has no industry notice')

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
check(offBoard.includes('既有族群關聯待重新核實') && !offBoard.includes('題材表版本'), 'industry detail keeps the notice and has no theme table version')
check(themeDefinitionVersion({ ...themeDetail(), theme: { ...themeDetail().theme, definition_version: 'themes_v1:2026.10.18' } }) === 'themes_v1:2026.10.18', 'theme.definition_version wins when present')
check(evidenceUrl({ kind: null, url: 'http://x.test', relation: null, relevance: null, theme_version: null }) === 'http://x.test' && evidenceUrl(null) === null, 'evidence url rule')

// ---- AC-3 today Top 10 ----
const topTen = { ...industryBoard(), items: Array.from({ length: 10 }, (_, index) => boardItem({ theme_id: `industry-${index + 1}`, display_name: `產業 ${index + 1}`, rank: index + 1 })) }
const today = render(<HotGroupsSection board="industry" onBoardChange={noop} data={topTen} loading={false} error={null} />)
check(count(today, 'class="feature-card hot-group-card"') === 10, 'ten cards')
check(today.includes('href="/themes/industry-1"') && today.includes('href="/themes/industry-10"'), 'cards link to the detail page')
check(today.includes('href="/themes">查看完整排行'), 'full ranking link for the industry tab')
const firstCard = today.slice(today.indexOf('data-theme-id="industry-1"'), today.indexOf('data-theme-id="industry-2"'))
for (const text of ['第 1 名', '產業 1', '熱門族群', '81.25', '+1.23%', '-0.45%', '0.00%', '資料 2026/09/08']) check(firstCard.includes(text), `today card shows ${text}: ${firstCard}`)
const todayTheme = render(<HotGroupsSection board="theme" onBoardChange={noop} data={themeBoard()} loading={false} error={null} />)
check(todayTheme.includes('id="today-board-tab-theme" aria-selected="true"') && todayTheme.includes('href="/themes?board=theme">查看完整排行') && todayTheme.includes('CoWoS 先進封裝'), 'theme tab and its full-ranking link')
const todayEmpty = render(<HotGroupsSection board="industry" onBoardChange={noop} data={emptyBoard('industry', 'no_ranked_groups')} loading={false} error={null} />)
check(todayEmpty.includes(EMPTY_MESSAGES.no_ranked_groups) && !todayEmpty.includes('hot-group-card'), 'today empty board shows empty_message')
