import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'

import { completeItem, listResponse } from '../candidates/candidates.fixtures'
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
  candidateCountsByGroup,
  componentExtremes,
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

// ---- Issue 522 the highest and lowest components, and 今日名單 per group (UI_COPY_SPEC §8.5 族群頁) ----
const extremesOf = (components: Parameters<typeof componentExtremes>[0]) => componentExtremes(components).map((entry) => `${entry.label} ${formatComponent(entry.value)}`).join('・')
check(extremesOf(boardItem().components) === '催化劑 100・法人 25', `highest and lowest of five: ${extremesOf(boardItem().components)}`)
check(extremesOf(industryBoard().items[1].components) === '量能 80・法人 40', 'null components are left out, never read as 0')
const flatComponents = { relative_return: 0.5, breadth: 0.5, volume_strength: 0.5, institutional_flow: 0.5, catalyst: 0.5 }
check(extremesOf(flatComponents) === '相對報酬 50・催化劑 50', `a tie: the earlier component is the highest, the later the lowest: ${extremesOf(flatComponents)}`)
const oneComponent = { relative_return: null, breadth: 0.4, volume_strength: null, institutional_flow: null, catalyst: null }
check(extremesOf(oneComponent) === '廣度 40' && componentExtremes({ ...oneComponent, breadth: null }).length === 0, 'one valued component gives one entry; none gives none')
const picksRun = (date: string | null, groups: string[][], status = 'success') => ({ ...listResponse(), status, trading_date: date, items: groups.map((ids) => ({ ...completeItem(), groups: ids.map((group_id) => ({ ...completeItem().groups[0], group_id })) })) })
const counted = candidateCountsByGroup(picksRun('2026-09-08', [['industry-24', 'theme-cowos'], ['industry-24'], ['theme-cowos', 'theme-cowos']]), '2026-09-08')
check(counted?.get('industry-24') === 2 && counted?.get('theme-cowos') === 2 && !counted?.has('industry-28'), 'candidates counted per group, a stock once per group')
check(candidateCountsByGroup(picksRun('2026-09-07', [['industry-24']]), '2026-09-08') === null, 'a candidate list of another day says nothing')
check(candidateCountsByGroup(undefined, '2026-09-08') === null && candidateCountsByGroup(picksRun(null, [], 'not_computed'), '2026-09-08') === null, 'no list, or a list not computed, says nothing')

// ---- AC-1 board page markup: one list of two-line rows at every width (Issue 522, DESIGN_SYSTEM §5 族群榜) ----
const industryMarkup = render(<ThemesBoardView board="industry" onBoardChange={noop} search="" onSearchChange={noop} data={industryBoard()} loading={false} error={null} />)
check(industryMarkup.includes('id="board-tab-industry" aria-selected="true"') && industryMarkup.includes('id="board-panel-industry"'), 'industry tab selected by default with its panel')
check(industryMarkup.includes('<ol class="board-list">') && count(industryMarkup, '<li class="board-row" data-theme-id=') === 2, 'one list, one row per group')
check(!industryMarkup.includes('<table') && !industryMarkup.includes('board-card'), 'Issue 522: no 12-column table and no phone cards')
const boardRowOf = (markup: string, id: string) => markup.slice(markup.indexOf(`data-theme-id="${id}"`), markup.indexOf('</li>', markup.indexOf(`data-theme-id="${id}"`)))
const mainOf = (row: string) => row.slice(row.indexOf('<div class="board-row-main">'), row.indexOf('<details'))
const detailOf = (row: string) => row.slice(row.indexOf('<details'), row.indexOf('</details>'))
const industryRow = boardRowOf(industryMarkup, 'industry-24')
const industryMain = mainOf(industryRow)
for (const text of ['第 1 名', '#1', '半導體業', '81.25', '催化劑 <b>100</b>', '法人 <b>25</b>']) {
  check(industryMain.includes(text), `industry row shows ${text}: ${industryMain}`)
}
// Issue 654 AC-3: the three relative returns are strength blocks (hue by sign, depth by step), the number kept inside.
// The block whose aria-label starts with `label`; null when there is none (never a slice from the string's end).
const chipOf = (markup: string, label: string) => {
  const at = markup.indexOf(`aria-label="${label}`)
  return at < 0 ? null : /<b class="strength-chip[^"]*" role="img" aria-label="([^"]*)" data-strength="([^"]*)">([^<]*)<\/b>/.exec(markup.slice(Math.max(0, at - 80)))
}
check(chipOf('<p>none</p>', '1 日相對加權指數') === null, 'chipOf: no block is null')
const chipsOf = (markup: string) => [...markup.matchAll(/<b class="strength-chip[^"]*" role="img" aria-label="([^"]*)" data-strength="([^"]*)">([^<]*)<\/b>/g)].map((match) => match.slice(1).join('|'))
const boardChips = ['1 日相對加權指數 +1.23%|up-2|+1.23%', '5 日相對加權指數 -0.45%|down-1|-0.45%', '20 日相對加權指數 0.00%|flat-0|0.00%']
check(JSON.stringify(chipsOf(industryMain)) === JSON.stringify(boardChips), `Issue 654: board row returns are strength blocks: ${JSON.stringify(chipsOf(industryMain))}`)
check(industryMain.includes('1 日 <b class="strength-chip') && !/tone-(?:up|down|flat)/.test(industryMain), 'Issue 654: the window label stays beside the block and no bare up/down text colour is left on the row')
check(chipOf(industryMain, '1 日相對加權指數')?.[2] === 'up-2', 'Issue 654: chip lookup')
check(industryMain.includes('href="/themes/industry-24"'), 'the name links to the detail page')
// Two lines: the title (name, quality, extremes) and the meta (returns, 今日名單); the score and the 五分項 button beside them.
check(/^<div class="board-row-main"><span class="board-rank"[^>]*>#1<\/span><p class="board-row-title">.*<\/p><p class="board-row-meta">.*<\/p><span class="board-row-score">.*<\/span><button[^>]*>五分項 ▸<\/button><\/div>$/.test(industryMain), `Issue 522: a row is a title line and a meta line: ${industryMain}`)
check(!industryMain.includes('熱門族群') && !industryMain.includes('badge-success'), 'Issue 522: a complete group (熱門族群) carries no quality badge')
check(!industryMain.includes('今日名單') && !industryMarkup.includes('board-row-picks'), 'without a candidate list no row says 今日名單')
// AC-2: the five components and the members stay on the page, folded under the row.
const industryFold = detailOf(industryRow)
// Issue 654 AC-2: each component is a 0–100 score bar (fill share = the percentile), its number beside the bar.
for (const [label, value] of [['相對報酬', '90'], ['廣度', '75'], ['量能', '50'], ['法人', '25'], ['催化劑', '100']]) {
  check(industryFold.includes(`<dt>${label}</dt><dd><span class="score-bar" role="img" aria-label="${label} ${value}（0–100）" data-score="${value}">`) && industryFold.includes(`style="width:${value}%"`), `AC-2: the fold shows ${label} ${value} as a bar: ${industryFold}`)
}
check(industryFold.includes('<dt>成員（檔）</dt><dd>12／14</dd>'), 'the fold shows 成員（檔） 12／14 as a number')
const partialFold = detailOf(boardRowOf(industryMarkup, industryBoard().items[1].theme_id))
check(partialFold.includes('aria-label="廣度 無資料" data-score="none"') && partialFold.includes('aria-label="催化劑 無資料" data-score="none"') && !/aria-label="(?:廣度|催化劑) 無資料"[^>]*><span class="score-bar-track" aria-hidden="true"><span class="score-bar-fill"/.test(partialFold), `Issue 654: a missing component draws no fill and reads 「—」: ${partialFold}`)
check(industryFold.startsWith('<details class="board-row-detail" id="board-detail-industry-24">') && industryRow.includes('aria-controls="board-detail-industry-24"') && industryRow.includes('aria-expanded="false"'), 'the fold is closed by default and the button controls it')
check(industryFold.includes('href="/themes/industry-24">族群詳情 →'), 'the fold links to the detail page')
const partialRow = boardRowOf(industryMarkup, 'industry-28')
check(mainOf(partialRow).replace(/<[^>]+>/g, '').includes('技術與籌碼觀察（事件資料待補）'), 'a partial group shows its quality badge on the title line')
check(count(detailOf(partialRow), '>—<') === 2 && count(mainOf(partialRow), '>—<') === 1, `null breadth and catalyst show 「—」 in the fold, the null 20d return on the row: ${partialRow}`)
check(industryMarkup.includes('資料 2026/09/08') && !industryMarkup.includes('官方資料 '), 'board date badge')
check(!industryMarkup.includes('待重新核實') && !industryMarkup.includes('class="data-gap"'), 'industry board shows no temporary verification notice')
// The page explanation and the units moved into the closed 說明 fold beside the board line.
const help = industryMarkup.slice(industryMarkup.indexOf('<details class="details board-help">'), industryMarkup.indexOf('</details>', industryMarkup.indexOf('board-help')))
check(help.includes('<summary>說明</summary>') && !help.includes('open=""'), 'Issue 522: 說明 is a closed fold')
for (const sentence of ['只有五分項完整的族群稱為熱門族群', '1／5／20 日為相對加權指數的報酬（%）', '「—」表示該項無資料。', '名稱後的兩個分項是五分項中最高與最低的一項。', '今日名單 N 檔是當日今日名單中屬於這個族群的檔數，沒有時不顯示。']) {
  check(help.replace(/<[^>]+>/g, '').includes(sentence), `說明 says ${sentence}`)
}
const pageTitle = industryMarkup.slice(industryMarkup.indexOf('<section class="page-title">'), industryMarkup.indexOf('</section>'))
check(!pageTitle.includes('<p>'), 'Issue 522: the title holds no explanation paragraph')
// 今日名單 N 檔 only from a list of the board's own date, and only for a group with candidates.
const withPicks = render(<ThemesBoardView board="industry" onBoardChange={noop} search="" onSearchChange={noop} data={industryBoard()} loading={false} error={null} candidates={picksRun('2026-09-08', [['industry-24'], ['industry-24', 'theme-cowos']])} />)
check(mainOf(boardRowOf(withPicks, 'industry-24')).includes('今日名單 2 檔') && !boardRowOf(withPicks, 'industry-28').includes('今日名單'), 'Issue 522: 今日名單 2 檔 on the group with two candidates, nothing on a group with none')
const stalePicks = render(<ThemesBoardView board="industry" onBoardChange={noop} search="" onSearchChange={noop} data={industryBoard()} loading={false} error={null} candidates={picksRun('2026-09-07', [['industry-24']])} />)
check(!stalePicks.includes('board-row-picks') && !mainOf(boardRowOf(stalePicks, 'industry-24')).includes('今日名單'), 'Issue 522: a candidate list of another day is not counted')

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
check(['相對報酬', '廣度', '量能', '法人', '催化劑'].every((label) => components.includes(label)) && components.includes('aria-label="相對報酬 100（0–100）" data-score="100"') && components.includes('aria-label="催化劑 無資料" data-score="none"'), 'Issue 654: five components as score bars with null as 「—」')
check((components.slice(0, components.indexOf('components-returns')).match(/class="score-bar(?: score-bar-empty)?" role="img"/g) ?? []).length === 5, 'Issue 654: the components card draws one bar per component')
check(JSON.stringify(chipsOf(components.slice(components.indexOf('components-returns')))) === JSON.stringify(['1 日相對加權指數 +3.02%|up-3|+3.02%', '5 日相對加權指數 +7.11%|up-4|+7.11%', '20 日相對加權指數 +12.04%|up-4|+12.04%']), `Issue 654: the card's relative returns are strength blocks: ${JSON.stringify(chipsOf(components))}`)
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
// #463: rank and components come from the board request; while it loads or after it fails the page never says the
// group is off the board (UI_COPY_SPEC §8.5 族群詳情的名次與五分項).
const boardPending = render(<ThemeDetailView detail={themeDetail()} board={waiting} members={loaded(membersPage())} onMemberPageChange={noop} news={loaded({ items: [] })} />)
check(!boardPending.includes('不在本日') && !boardPending.includes('未列入本日榜單'), 'a loading board is not 「不在本日榜」')
check(count(boardPending, 'aria-busy="true"') >= 2 && boardPending.includes('榜單載入中'), `the rank cell and the components card are busy while the board loads: ${count(boardPending, 'aria-busy="true"')}`)
const boardFailed = render(<ThemeDetailView detail={themeDetail()} board={{ data: undefined, loading: false, error: new Error('API 503') }} members={loaded(membersPage())} onMemberPageChange={noop} news={loaded({ items: [] })} />)
check(!boardFailed.includes('不在本日') && !boardFailed.includes('未列入本日榜單') && !boardFailed.includes('aria-busy="true"'), 'a failed board is not 「不在本日榜」 and not busy')
check(boardFailed.includes('榜單暫時無法載入') && boardFailed.includes('榜單暫時無法載入：API 503'), 'a failed board says it could not load, with the reason in the components card')
check(detailMarkup.includes('題材榜共 2 個族群') && !detailMarkup.includes('不在本日') && !detailMarkup.includes('aria-busy="true"'), 'a loaded board on which the group ranks shows the board size')
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
check(MEMBER_SORTS.map((option) => option.label).join() === '成交金額,漲跌幅,5 日相對,20 日相對,代號', 'sort option labels')
check(detailMarkup.includes('aria-label="成員排序"') && detailMarkup.includes('<option value="turnover" selected="">成交金額</option>'), 'the sort select shows turnover by default')
const bySort = render(<ThemeDetailView detail={themeDetail()} board={loaded(themeBoard())} members={loaded(membersPage())} memberSort="change_pct" onMemberSortChange={noop} onMemberPageChange={noop} news={loaded({ items: [] })} />)
check(bySort.includes('<option value="change_pct" selected="">漲跌幅</option>') && !bySort.includes('<option value="turnover" selected="">'), 'another sort is selected when chosen')
check(bySort.includes('第 2／2 頁') && bySort.includes('下一頁'), 'paging stays under a chosen sort')
// Theme board: role only as the 領先成員 badge in the name cell, evidence stays last.
check(headersOf(detailMarkup).join('|') === '代號|名稱|市場|收盤（元）|漲跌幅（%）|成交金額（億元）|5 日相對（%）|20 日相對（%）|證據', `theme member headers: ${headersOf(detailMarkup).join('|')}`)
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
check(noteAt >= 0 && noteAt < detailMarkup.indexOf('member-table-wrap') && noteAt < detailMarkup.indexOf('class="card-list member-cards"'), 'the member note precedes the table and the cards')
const memberNote = strip(detailMarkup.slice(detailMarkup.indexOf('>', noteAt) + 1, detailMarkup.indexOf('</p>', noteAt)))
check(memberNote.startsWith('收盤為各標的報價幣別的元；成交金額是當日成交金額；5／20 日相對是相對加權指數的報酬。'), `member unit note: ${memberNote.slice(0, 80)}`)
for (const sentence of ['漲跌幅空白表示漲跌待核實。', '成交金額空白表示來源未提供。', '5／20 日相對空白表示未列入當日族群計分。', '收盤下方的「資料 YYYY/MM/DD」表示該檔沒有成員資料日的日線，漲跌幅與成交金額留空。', '收盤空白表示該檔尚無日線。']) {
  check(memberNote.includes(sentence), `member note says ${sentence}`)
}
check(!memberNote.includes('成交金額空白表示待核實'), 'an unknown turnover sentence only when a row is unknown')
check(memberTableNote([{ ...membersPage().items[0] }], '2026-09-08') === '收盤為各標的報價幣別的元；成交金額是當日成交金額；5／20 日相對是相對加權指數的報酬。', 'no blank, no blank sentence')
check(memberTableNote([{ ...membersPage().items[0], turnover: null, turnover_status: 'unknown' }], '2026-09-08').endsWith('成交金額空白表示待核實。'), 'unknown turnover reads 待核實')
// #465: the source published the previous session but gave the stock no close (no trade, suspended or newly listed) — the cause is
// known, so the note says it instead of 待核實; an unverified change on the same page keeps its own sentence.
const noPrevious = { ...membersPage().items[0], change: null, change_pct: null, change_status: 'no_previous_close' }
const noPreviousNote = memberTableNote([noPrevious], '2026-09-08')
check(noPreviousNote.endsWith('漲跌幅空白表示前一交易日沒有收盤價，不計算漲跌。') && !noPreviousNote.includes('待核實'), `no previous close reads its cause: ${noPreviousNote}`)
check(memberTableNote([noPrevious, { ...membersPage().items[0], change: null, change_pct: null, change_status: 'unverified' }], '2026-09-08').includes('漲跌幅空白表示漲跌待核實。'), 'an unverified change still reads 待核實')
// #475: a new listing's first day is its own sentence, not 「前一交易日沒有收盤價」 or 待核實.
const firstDayNote = memberTableNote([{ ...noPrevious, change_status: 'first_trading_day' }], '2026-09-08')
check(firstDayNote.endsWith('漲跌幅空白表示該檔為掛牌首日（新上市或轉市），沒有前一交易日收盤。') && !firstDayNote.includes('前一交易日沒有收盤價') && !firstDayNote.includes('待核實'), `first trading day note: ${firstDayNote}`)
// Industry board: no role column, no evidence column.
const industryMembers = render(<ThemeDetailView detail={industryDetail} board={loaded(industryBoard())} members={loaded(membersPage())} onMemberPageChange={noop} news={loaded({ items: [] })} />)
check(headersOf(industryMembers).join('|') === '代號|名稱|市場|收盤（元）|漲跌幅（%）|成交金額（億元）|5 日相對（%）|20 日相對（%）', `industry member headers: ${headersOf(industryMembers).join('|')}`)
check(!cellsOf(rowOf(industryMembers, '2330'))[1].includes('領先成員') && cellsOf(rowOf(industryMembers, '2330'))[1].includes('候選 #3'), 'industries show no role, keep the candidate badge')
// 390: one card per member, title row with close and change, then three cells.
const cards = detailMarkup.slice(detailMarkup.indexOf('class="card-list member-cards"'), detailMarkup.indexOf('pagination-controls', detailMarkup.indexOf('class="card-list member-cards"')))
check(count(cards, 'class="member-card"') === membersPage().items.length, 'one phone card per member')
const leaderCard = cards.slice(cards.indexOf('class="member-card"'), cards.indexOf('class="member-card"', cards.indexOf('class="member-card"') + 1))
check(strip(leaderCard).includes('2330 台積電') && leaderCard.includes('1,085.00') && leaderCard.includes('tone-up">+1.40%<'), `card title row: ${strip(leaderCard)}`)
check(['成交金額（億元）', '5 日相對', '20 日相對'].every((label) => leaderCard.includes(`<dt>${label}</dt>`)) && leaderCard.includes('<dd>325.12</dd>') && leaderCard.includes('tone-up">+1.23%<'), 'card has the three cells, 億元 on the label and % on the returns')
check(leaderCard.includes('主要業務 · 關聯度高'), 'theme cards keep the evidence')
check(strip(cards).includes('資料 2026/09/05'), 'a stale card shows its bar date')

// ---- Issue 522 the board is the full ranking: every group is a row at every width, nothing folds behind 「顯示其餘」 ----
const twelveGroups = { ...industryBoard(), items: Array.from({ length: 12 }, (_, i) => boardItem({ theme_id: `industry-${i + 1}`, rank: i + 1, display_name: `族群${i + 1}` })) }
twelveGroups.meta = { ...twelveGroups.meta, total: 12 }
const longBoard = render(<ThemesBoardView board="industry" onBoardChange={noop} search="" onSearchChange={noop} data={twelveGroups} loading={false} error={null} />)
check(count(longBoard, '<li class="board-row" data-theme-id=') === 12 && !longBoard.includes('顯示其餘'), 'all 12 rows, none folded')
check(longBoard.indexOf('族群11') < longBoard.indexOf('族群12') && longBoard.indexOf('>#11<') < longBoard.indexOf('>#12<'), 'rows keep the rank order')
const twelveMembers = { ...membersPage(), items: Array.from({ length: 12 }, (_, i) => ({ ...membersPage().items[0], symbol: String(2400 + i), name: `成員${i + 1}`, candidate_rank: null, conditional: false })) }
const longMembers = render(<ThemeDetailView detail={themeDetail()} board={loaded(themeBoard())} members={loaded(twelveMembers)} onMemberPageChange={noop} news={loaded({ items: [] })} />)
const memberPhone = longMembers.slice(longMembers.indexOf('class="card-list member-cards"'))
const memberRest = memberPhone.slice(memberPhone.indexOf('<details class="details card-list-rest">'), memberPhone.indexOf('</details>') + 10)
check(count(memberPhone, 'class="member-card"') === 12 && count(memberRest, 'class="member-card"') === 2 && memberRest.includes('<summary>顯示其餘 2 檔</summary>'), 'phone members: 10 cards open, 「顯示其餘 2 檔」 folds the last 2')
check(memberRest.includes('2410 成員11') && memberRest.includes('2411 成員12'), 'the folded members are the last two in API order')

check(themeDefinitionVersion({ ...themeDetail(), theme: { ...themeDetail().theme, definition_version: 'themes_v1:2026.10.18' } }) === 'themes_v1:2026.10.18', 'theme.definition_version wins when present')
check(evidenceUrl({ kind: null, url: 'http://x.test', relation: null, relevance: null, theme_version: null }) === 'http://x.test' && evidenceUrl(null) === null, 'evidence url rule')

// ---- today Top 5 rows (Issue 510; UI_COPY_SPEC §8.5): two lines each, the quality badge only when it is not 熱門族群 ----
const topTen = { ...industryBoard(), items: Array.from({ length: 5 }, (_, index) => boardItem({ theme_id: `industry-${index + 1}`, display_name: `產業 ${index + 1}`, rank: index + 1, quality: index === 1 ? 'partial' : 'complete' })) }
const today = render(<HotGroupsSection board="industry" onBoardChange={noop} data={topTen} loading={false} error={null} />)
check(count(today, 'class="hot-group-row"') === 5 && !today.includes('feature-card'), 'five rows, no feature cards')
check(!today.includes('eyebrow') && !today.includes('各榜前 5 名'), 'Issue 510: the head has no eyebrow')
check(today.includes('href="/themes/industry-1"') && today.includes('href="/themes/industry-5"'), 'rows link to the detail page')
check(today.includes('href="/themes">完整排行 →'), 'full ranking link 「完整排行 →」 for the industry tab')
check(today.includes('資料 2026/09/08') && today.includes('1／5／20 日為相對加權指數的報酬') && count(today, '資料 2026/09/08') === 1, 'Issue 510: the date and 「相對加權指數」 are said once under the head, not per row')
const rowOfGroup = (id: string) => today.slice(today.indexOf(`data-theme-id="${id}"`), today.indexOf('</a>', today.indexOf(`data-theme-id="${id}"`)))
const firstCard = rowOfGroup('industry-1')
for (const text of ['第 1 名', '產業 1', '81.25', '+1.23%', '-0.45%', '0.00%']) check(firstCard.includes(text), `today row shows ${text}: ${firstCard}`)
check(JSON.stringify(chipsOf(firstCard)) === JSON.stringify(boardChips), `Issue 654: today group returns are strength blocks: ${JSON.stringify(chipsOf(firstCard))}`)
// Two lines: the line with rank, name, quality and score; the line with the three returns. Nothing else.
check(/^data-theme-id="industry-1"[^>]*><span class="hot-group-line">.*<\/span><span class="hot-group-returns">.*<\/span>$/.test(firstCard), `Issue 510: a row is the head line and the returns line: ${firstCard}`)
check(!firstCard.includes('badge-success') && !firstCard.includes('熱門族群'), 'Issue 510: a complete group (熱門族群) carries no quality badge')
check(rowOfGroup('industry-2').includes('技術與籌碼觀察（事件資料待補）'), 'Issue 510: a group that is not 熱門族群 shows its quality badge')
const todayTheme = render(<HotGroupsSection board="theme" onBoardChange={noop} data={themeBoard()} loading={false} error={null} />)
check(todayTheme.includes('id="today-board-tab-theme" aria-selected="true"') && todayTheme.includes('href="/themes?board=theme">完整排行 →') && todayTheme.includes('CoWoS 先進封裝'), 'theme tab and its full-ranking link')
const todayEmpty = render(<HotGroupsSection board="industry" onBoardChange={noop} data={emptyBoard('industry', 'no_ranked_groups')} loading={false} error={null} />)
check(todayEmpty.includes(EMPTY_MESSAGES.no_ranked_groups) && !todayEmpty.includes('hot-group-row'), 'today empty board shows empty_message')
