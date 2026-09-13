import { eventTimeLabels, formatResearchDate, formatResearchDateTime, isTemporaryIndustryGroupName, isTemporaryIndustryTheme, newsTimeLabels, recentByDate, summarizeStockResearch, TEMPORARY_INDUSTRY_GROUP_NOTICE } from './stockResearch'
import type { InstrumentDetail, NewsItem } from './types'

function expect(condition: boolean, message: string): void {
  if (!condition) throw new Error(message)
}

expect(formatResearchDate('2026-09-08') === '2026/09/08', 'date-only evidence keeps date precision')
expect(formatResearchDate('2026-02-30') === '待核實', 'invalid evidence dates stay unknown')
expect(formatResearchDateTime('2026-09-08T01:00:00+00:00').includes('2026/09/08'), 'aware evidence timestamps display in Taiwan time')
expect(formatResearchDateTime('2026-09-08T01:00:00') === '待核實（時間格式未確認）', 'naive timestamps are not promoted to a timezone')
expect(isTemporaryIndustryTheme({ category: '股票族群', name_status: 'official' }), 'official industry themes use the temporary verification guard')
expect(!isTemporaryIndustryTheme({ category: 'ETF', name_status: 'official' }), 'ETF themes stay outside the industry verification guard')
expect(isTemporaryIndustryGroupName('Industry · Shipping'), 'legacy industry membership names use the temporary verification guard')
expect(TEMPORARY_INDUSTRY_GROUP_NOTICE.includes('既有族群關聯待重新核實'), 'temporary industry notice keeps the fixed warning copy')

const rows = [{ date: '2026-09-03' }, { date: '2026-09-01' }, { date: 'bad' }]
expect(recentByDate(rows, 2).map((row) => row.date).join(',') === '2026-09-03,2026-09-01', 'recent evidence is deterministic and date-descending')

const news = {
  id: 'news-1',
  canonical_key: 'news-1',
  dedupe_cluster_id: null,
  category: 'announcement',
  source_kind: 'official',
  source_name: 'TWSE',
  source: { name: 'TWSE', url: null, url_kind: 'none' },
  source_item_id: null,
  title: '公告',
  summary: '摘要',
  language: 'zh-TW',
  published_at: '2026-09-08T01:00:00+00:00',
  event_at: null,
  event_date: '2026-09-08',
  collected_at: null,
  symbols: ['2330'],
  themes: [],
  theme_ids: [],
  impact: { scope: 'instrument', direction: 'neutral', rationale: null, method: 'official', confidence: 'unknown' },
  impact_scope: 'instrument',
  impact_direction: 'neutral',
  confidence: 'unknown',
  status: 'active',
  content_hash: null,
  provenance: { event_id: null, raw_payload_id: null, endpoint: null, data_as_of: null },
} satisfies NewsItem
const labels = newsTimeLabels(news)
expect(labels.event === '2026/09/08' && labels.published.includes('2026/09/08'), 'news keeps event and published times separate')
const protectedNews = { ...news, product_time: { roles: { published_at: { role: 'published_at', status: 'unknown', precision: 'none', value: null } } } } as unknown as NewsItem
const protectedLabels = newsTimeLabels(protectedNews)
expect(protectedLabels.published === '待核實' && protectedLabels.unknownCount > 0, 'unknown product-time roles do not fall back to raw timestamps')
expect(eventTimeLabels({ date: '2026-09-08', type: 'dividend', title: '事件', description: null, source: 'TWSE', data_as_of: null }).eventDate === '2026/09/08', 'event rows keep event date semantics')

const detail = {
  groups: [{ id: 'g1', name: '半導體', valid_from: '2026-01-01', valid_to: null }],
  chips: [],
  events: [{ date: '2026-09-08', type: 'dividend', title: '事件', description: null, source: 'TWSE', data_as_of: null }],
  strategy_conditions: { breakout: { label: '突破條件', requires: ['market_bar'], source: '固定研究規則' } },
  news: [news],
} as Pick<InstrumentDetail, 'groups' | 'chips' | 'events' | 'strategy_conditions'> & { news: NewsItem[] }
const summary = summarizeStockResearch(detail)
expect(summary.groups === 1 && summary.news === 1 && summary.events === 1 && summary.strategies === 1, 'research inventory counts only supplied sections')
