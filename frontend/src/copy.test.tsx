import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import * as AppModule from './App'
import { CandidateCard } from './candidates/CandidateViews'
import { completeItem } from './candidates/candidates.fixtures'
import { DateBadge } from './components/ui'
import { GLOSSARY } from './glossary'
import { NewsDetailView, NewsCard } from './news/NewsViews'
import { aiResult, newsItem } from './news/news.fixtures'
import { StockBarsChart } from './stock/StockBarsChart'
import { barsResponse, tradedBar } from './stock/stockBars.fixtures'
import { ThemeBoardPanel, ThemeDetailView } from './themes/ThemeViews'
import { industryBoard, membersPage, themeBoard, themeDetail } from './themes/themeBoards.fixtures'
import type { ActionSummary } from './types'
import { positionQuantityFromText } from './units'

// The frontend ships no Node typings; scripts/ci-test.cjs runs this module under Node, so declare what it uses.
declare const require: (id: string) => unknown
declare const __dirname: string
type DirEntry = { name: string; isDirectory(): boolean }
const fs = require('node:fs') as { readdirSync(dir: string, options: { withFileTypes: true }): DirEntry[]; readFileSync(file: string, encoding: 'utf8'): string }
const path = require('node:path') as { join(...parts: string[]): string; relative(from: string, to: string): string; sep: string }

// In-place terms, dates and copy (#270; UI_COPY_SPEC §1, §4, §7, §8.3). Every check runs and the failures are
// listed together, so one run shows each place that is off.
const failures: string[] = []
let checks = 0
const check = (condition: boolean, message: string) => { checks++; if (!condition) failures.push(message) }
const render = (name: string, element: () => ReactElement): string => {
  try {
    const client = new QueryClient()
    return renderToStaticMarkup(<QueryClientProvider client={client}><StaticRouter location="/">{element()}</StaticRouter></QueryClientProvider>)
  } catch (error) {
    failures.push(`${name}: render failed (${error instanceof Error ? error.message.split('\n')[0] : String(error)})`)
    return ''
  }
}
// Looked up by name so a missing export is one listed failure instead of a build error.
const component = (name: string) =>
  ((AppModule as Record<string, unknown>)[name] ?? (() => { throw new Error(`App does not export ${name}`) })) as (props: Record<string, unknown>) => ReactElement
const text = (markup: string) => markup.replace(/<[^>]+>/g, '')
const noop = () => undefined
const loaded = <T,>(data: T) => ({ data, loading: false, error: null })

// A term button: `<button ... class="term-button" ...>label</button>`, label possibly wrapping other markup.
const termLabels = (markup: string): string[] =>
  (markup.match(/<button[^>]*class="term-button"[^>]*>[\s\S]*?<\/button>/g) ?? []).map((button) => text(button))
const hasTerm = (markup: string, label: string) => termLabels(markup).some((found) => found.includes(label))

// ---- glossary: every in-place term exists with all five fields (UI_COPY_SPEC §7 就地說明) ----
const IN_PLACE_TERMS: Record<string, string> = {
  candidate_score: '候選總分',
  entry_zone: '進場區',
  support: '停損／條件失效價',
  target: '目標價',
  rr: '風險報酬比 RR',
  percentile: '百分位',
  heat_rank: '熱度分數與排名',
  group_components: '五分項',
  event_data_pending: '事件資料待補',
}
for (const [id, name] of Object.entries(IN_PLACE_TERMS)) {
  const term = GLOSSARY.find((item) => item.term_id === id)
  check(term?.name === name, `glossary ${id}: name is 「${name}」, got ${term ? `「${term.name}」` : 'no term'}`)
  check(Boolean(term && term.plain_definition && term.use && term.how_to_read && term.limitations), `glossary ${id}: definition, use, reading and limits are all written`)
}
check(GLOSSARY.every((term) => !/percentile/i.test(term.name)), 'glossary: no term is named in English 「percentile」')

// ---- candidate card: score, levels, RR and the details header are terms; no English 「percentile」 ----
const candidate = render('CandidateCard', () => <CandidateCard item={completeItem()} detailsOpen />)
for (const label of ['總分', '進場區', '停損', '目標', 'RR', '百分位']) check(hasTerm(candidate, label), `候選卡: 「${label}」 opens its glossary term (found ${termLabels(candidate).join('、') || 'none'})`)
check(!/percentile/i.test(text(candidate)), '候選卡: 「percentile」 is not shown; the details read 「百分位」')
check(text(candidate).includes('分數與百分位為 0–100'), '候選卡: the details note reads 「分數與百分位為 0–100」')

// ---- themes: rank, score, same-board percentile and 「事件資料待補」 explain themselves; never inside a link ----
const boardMarkup = render('ThemeBoardPanel', () => <ThemeBoardPanel board="industry" data={industryBoard()} search="" />)
const tableMarkup = /<table[\s\S]*<\/table>/.exec(boardMarkup)?.[0] ?? ''
const tableHead = /<thead>[\s\S]*?<\/thead>/.exec(tableMarkup)?.[0] ?? ''
check(hasTerm(tableHead, '排名') && hasTerm(tableHead, '分數'), `族群榜: 「排名」「分數」 headers open 熱度分數與排名 (found ${termLabels(tableHead).join('、') || 'none'})`)
check(hasTerm(boardMarkup, '同榜百分位'), '族群榜: the table note explains 「同榜百分位」')
check(hasTerm(tableMarkup, '事件資料待補'), '族群榜: the partial-quality badge in the table explains 「事件資料待補」')
const links = boardMarkup.match(/<a [\s\S]*?<\/a>/g) ?? []
check(links.every((link) => !link.includes('<button')), '族群榜: no term button sits inside a link (the phone cards stay plain)')
const detailMarkup = render('ThemeDetailView', () => <ThemeDetailView detail={themeDetail()} board={loaded(themeBoard())} members={loaded(membersPage())} onMemberPageChange={noop} news={loaded({ items: [] })} />)
for (const label of ['排名', '五分項', '同榜百分位', '事件資料待補']) check(hasTerm(detailMarkup, label), `族群詳情: 「${label}」 opens its glossary term (found ${termLabels(detailMarkup).join('、') || 'none'})`)

// ---- stock research tab: stop／invalidation and target levels are terms ----
const action = {
  instrument: { id: 1, exchange: 'TWSE', symbol: '1742', name: '台蠟', instrument_type: 'stock', etf_category: null },
  action_state: 'conditional_entry', current_price: 21.1, price_as_of: '2026-10-22', data_cutoff: '2026-10-22', data_quality: 'complete',
  trigger_price: 21.5, invalid_price: 20.1, target_1: 23.8, risk_reward: 1.6, reasons: [], conflicts: [], strategies: [],
  level_semantics: { kind: 'rule_reference' },
} as unknown as ActionSummary
const ActionDetailPanel = component('ActionDetailPanel')
const research = render('ActionDetailPanel', () => <ActionDetailPanel {...{ action }} />)
check(termLabels(research).some((label) => /失效|停損/.test(label)), `研究條件: the invalidation／stop level opens 停損／條件失效價 (found ${termLabels(research).join('、') || 'none'})`)
check(termLabels(research).some((label) => label.includes('目標')), '研究條件: the target level opens 目標價')
check(hasTerm(research, '風險報酬比'), '研究條件: 風險報酬比 stays a term')

// ---- news detail: the facts column never reads like a verdict next to the AI direction (UI_COPY_SPEC §4) ----
const newsDetail = render('NewsDetailView', () => <NewsDetailView item={newsItem({ ai: aiResult() })} />)
const factsStart = newsDetail.indexOf('data-testid="news-facts"')
const facts = newsDetail.slice(factsStart, newsDetail.indexOf('data-testid="ai-inference"'))
check(facts.includes('來源未標示影響') && !facts.includes('影響尚未判定'), `新聞詳情: facts read 「來源未標示影響」, got ${text(/news-detail-label">影響<\/span>[\s\S]*?<\/div>/.exec(facts)?.[0] ?? '')}`)
check(render('NewsCard', () => <NewsCard item={newsItem()} />).includes('影響尚未判定'), '新聞卡: without AI the card keeps 「影響尚未判定」')

// ---- dates: YYYY/MM/DD and 24-hour YYYY/MM/DD HH:mm everywhere (UI_COPY_SPEC §1) ----
const badge = render('DateBadge', () => <DateBadge date="2026-10-22" />)
check(text(badge).includes('資料 2026/10/22'), `DateBadge: an API date reads 資料 2026/10/22, got ${text(badge)}`)
const chart = render('StockBarsChart', () => <StockBarsChart data={barsResponse([tradedBar('2026-10-21', 21.1, 70), tradedBar('2026-10-22', 21.15, 71)])} interval="day" onIntervalChange={noop} loading={false} error={null} />)
check(!/\d{4}-\d{2}-\d{2}/.test(text(chart)), `K 線: no YYYY-MM-DD on the chart card, got ${(text(chart).match(/\d{4}-\d{2}-\d{2}[^\d]{0,8}/g) ?? []).join('、')}`)
check(text(chart).includes('2026/10/22') && text(chart).includes('2026/10/16 18:00'), 'K 線: bar dates and the batch time read 2026/10/22 and 2026/10/16 18:00')
const IndicatorMetaRows = component('IndicatorMetaRows')
const meta = text(render('IndicatorMetaRows', () => <IndicatorMetaRows {...{ bars: barsResponse([tradedBar('2026-10-22', 21.15, 71)]) }} />))
check(meta.includes('2026/10/16 18:00') && !/\d{4}-\d{2}-\d{2}|上午|下午/.test(meta), `資料說明: computed time and K 線資料日期 are 24-hour slashed dates, got ${meta}`)
const BackfillRunTable = component('BackfillRunTable')
const backfill = text(render('BackfillRunTable', () => <BackfillRunTable {...{ runs: [{ id: 1, updated_at: '2026-10-22T10:00:00+00:00', metadata: {}, status: 'success', records: 9, error: null }] }} />))
check(backfill.includes('2026/10/22 18:00') && !/上午|下午/.test(backfill), `回補紀錄: update time is 2026/10/22 18:00, got ${backfill}`)
// One date module formats every date, so no page reaches for Intl with its locale-dependent 上午／下午.
const srcRoot = path.join(__dirname, '.')
function sources(dir: string, found: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) { if (entry.name !== 'node_modules') sources(full, found) }
    else if (/\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) found.push(full)
  }
  return found
}
const intlUsers = sources(srcRoot)
  .filter((file) => fs.readFileSync(file, 'utf8').includes('Intl.DateTimeFormat'))
  .map((file) => path.relative(srcRoot, file).split(path.sep).join('/'))
check(intlUsers.length === 1 && intlUsers[0] === 'dates.ts', `dates: only dates.ts uses Intl.DateTimeFormat, found ${intlUsers.join('、') || 'none'}`)

// ---- portfolio form: the int64 share limit stays in code, not on screen (UI_COPY_SPEC §8.3) ----
const PortfolioSubsection = component('PortfolioSubsection')
const portfolio = text(render('PortfolioSubsection', () => <PortfolioSubsection />))
check(portfolio.includes('每張為 1,000 股，可輸入整數張或零股股數。'), '我的庫存: the form hint reads 「每張為 1,000 股，可輸入整數張或零股股數。」')
check(!portfolio.includes('9,223,372,036,854,775,807') && !portfolio.includes('9223372036854775807'), '我的庫存: the int64 limit is not shown')
let overLimit = ''
try { positionQuantityFromText('odd_lot', '9223372036854775808') } catch (error) { overLimit = error instanceof Error ? error.message : String(error) }
check(overLimit === '數量超過可保存的上限，請確認張數或股數。', `我的庫存: over the limit says so without the number, got 「${overLimit}」`)
let atLimit = ''
try { atLimit = positionQuantityFromText('odd_lot', '9223372036854775807') } catch { atLimit = 'rejected' }
check(atLimit === '9223372036854775807', '我的庫存: the limit itself is still accepted')

// The runner keeps only the first lines of an error, so the full list goes to stderr first.
if (failures.length) {
  console.error(`copy checks failed:\n- ${failures.join('\n- ')}`)
  throw new Error(`${failures.length} of ${checks} copy checks failed (listed above)`)
}
console.log('copy', checks, 'checks passed')
