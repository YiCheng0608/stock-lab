import type { CursorPage, NewsAi, NewsItem, ProductTime, ProductTimeRole } from '../types'

// Shapes follow GET /api/news and /api/news/{id} (backend/app/api.py news_dict); `ai` follows PR 176 (Issue 163)
// news_ai_map: latest done result, inference=true, symbol candidates verified=false, name=null for unknown codes.

function unknownRole(role: string, reason: string): ProductTimeRole {
  return { role, status: 'unknown', precision: 'none', value: null, utc: null, date: null, reason }
}

function knownInstant(role: string, utc: string): ProductTimeRole {
  return { role, status: 'known', precision: 'instant', value: utc, utc, date: null, reason: null }
}

function knownDate(role: string, value: string): ProductTimeRole {
  return { role, status: 'known', precision: 'date', value, utc: null, date: value, reason: null }
}

export function productTime(roles: Record<string, ProductTimeRole> = {}): ProductTime {
  return {
    version: 'product-time/v1',
    scope: 'news_item',
    availability_truth: 'not_asserted',
    timezone_policy: {
      display_timezone: 'Asia/Taipei',
      known_instant: 'UTC_normalized_then_displayed_in_Asia_Taipei',
      date_only: 'calendar_date_without_timezone_conversion',
      naive_or_missing: 'unknown_with_reason',
    },
    roles: {
      published_at: unknownRole('published_at', 'published_at_empty'),
      event_at: unknownRole('event_at', 'news_event_at_not_display_basis'),
      event_date: unknownRole('event_date', 'news_event_date_not_persisted'),
      collected_at: unknownRole('collected_at', 'collected_at_naive_timezone_missing'),
      ...roles,
    },
    response_generated_at: '2026-10-18T02:00:00+00:00',
    legacy: {},
    limitations: [],
  }
}

export const PUBLISHED_UTC = '2026-10-17T16:05:00+00:00' // 2026/10/18 00:05 in Taipei

export function newsItem(overrides: Partial<NewsItem> = {}): NewsItem {
  return {
    id: '174',
    canonical_key: 'news:yahoo_tw:abc',
    dedupe_cluster_id: 'news-title:abc',
    category: 'domestic',
    source_kind: 'media',
    source_name: 'Yahoo奇摩股市',
    source: { name: 'Yahoo奇摩股市', url: 'https://tw.news.yahoo.com/tsmc-tainan-160000675.html', url_kind: 'item' },
    source_item_id: null,
    title: '台積電宣布臺南再蓋新廠\n 南市府：積極協助行政程序',
    summary: '台積電十五日召開法說會，宣布在台南增建一座三奈米廠，預計二〇二八年上半年量產。',
    description: '台積電十五日召開法說會，宣布在台南增建一座三奈米廠，預計二〇二八年上半年量產。',
    summary_preview: '台積電十五日召開法說會，宣布在台南增建一座三奈米廠，預計二〇二八年上半年量產。',
    language: 'zh-Hant',
    published_at: PUBLISHED_UTC,
    event_at: null,
    event_date: null,
    display_time: PUBLISHED_UTC,
    time_basis: 'published',
    time_precision: 'datetime',
    time_consistency: 'verified',
    product_time: productTime({ published_at: knownInstant('published_at', PUBLISHED_UTC), collected_at: knownInstant('collected_at', '2026-10-17T16:56:28+00:00') }),
    collected_at: '2026-10-17T16:56:28+00:00',
    symbols: ['TWSE:2330'],
    instruments: [{ exchange: 'TWSE', symbol: '2330', name: '台積電' }],
    themes: [],
    theme_ids: [],
    impact: { scope: 'instrument', direction: 'unknown', rationale: null, method: 'rule:exact-name-code/v1', confidence: 'unknown' },
    impact_scope: 'instrument',
    impact_direction: 'unknown',
    confidence: 'unknown',
    status: 'active',
    content_hash: 'hash-174',
    provenance: { event_id: null, raw_payload_id: 1432, endpoint: 'https://tw.stock.yahoo.com/rss?category=tw-market', data_as_of: '2026-10-17T16:56:28' },
    detail_url: '/news/174',
    ai: null,
    ...overrides,
  }
}

export function aiResult(overrides: Partial<NewsAi> = {}): NewsAi {
  return {
    inference: true,
    status: 'done',
    summary: '台積電宣布臺南增建3奈米廠，預計2028年上半年量產，南市府積極協助。',
    symbol_candidates: [
      { exchange: 'TWSE', symbol: '2330', name: '台積電', reason: '新廠擴產', confidence: 'high', verified: false },
      { exchange: 'TWSE', symbol: '6751', name: null, reason: '供應鏈', confidence: 'low', verified: false },
    ],
    theme_candidates: [{ theme: '半導體', reason: '晶圓代工產能' }],
    impact_direction: 'positive',
    impact_scope: 'instrument',
    impact_rationale: '新廠預計2028年上半年量產，被視為產能與技術布局的正面訊號。',
    unsupported: false,
    model: 'claude-haiku-5-5',
    prompt_version: 'news_v1',
    input_hash: 'sha256-input',
    generated_at: '2026-10-17T15:04:00+00:00',
    ...overrides,
  }
}

// International macro item without AI and a dataset-only link.
export function internationalItem(): NewsItem {
  return newsItem({
    id: '289',
    category: 'international',
    source_kind: 'macro_official',
    source_name: 'Federal Reserve',
    source: { name: 'Federal Reserve', url: null, url_kind: 'none' },
    title: 'Federal Reserve Board announces termination of enforcement action',
    summary: null,
    description: null,
    summary_preview: null,
    language: 'en',
    symbols: [],
    instruments: [],
    impact_scope: 'market',
  })
}

// Official MOPS projection: date-only event_date, feed link, bare symbol code.
export function officialItem(): NewsItem {
  return newsItem({
    id: '116',
    category: 'company',
    source_kind: 'official_disclosure',
    source_name: 'MOPS',
    source: { name: 'MOPS', url: 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O', url_kind: 'feed' },
    title: '公告本公司董事會通過變更營業地址',
    summary: '1.事實發生日:115/09/08 2.公司名稱:光耀科技股份有限公司',
    description: '1.事實發生日:115/09/08 2.公司名稱:光耀科技股份有限公司 3.與公司關係:本公司',
    summary_preview: '1.事實發生日:115/09/08 2.公司名稱:光耀科技股份有限公司',
    published_at: null,
    event_date: '2026-09-08',
    display_time: '2026-09-08T00:00:00',
    time_basis: 'event_date',
    time_precision: 'date',
    product_time: productTime({ event_date: knownDate('event_date', '2026-09-08') }),
    symbols: ['3666'],
    instruments: [],
    confidence: 'high',
    impact: { scope: 'instrument', direction: 'unknown', rationale: null, method: 'official_disclosure', confidence: 'high' },
    provenance: { event_id: 88, raw_payload_id: 12, endpoint: 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O', data_as_of: '2026-09-08' },
  })
}

// Feed news stored as UTC-naive: product_time keeps published_at unknown (Issue 186 pending).
export function naiveTimeItem(): NewsItem {
  return newsItem({
    id: '175',
    published_at: '2026-10-17T16:00:00',
    display_time: '2026-10-17T16:00:00',
    product_time: productTime({ published_at: unknownRole('published_at', 'published_at_naive_timezone_missing') }),
  })
}

export function newsPage(items: NewsItem[], meta: Partial<CursorPage<NewsItem>['meta']> = {}): CursorPage<NewsItem> {
  return {
    items,
    meta: { limit: 20, next_cursor: null, has_more: false, sort: 'display_time_desc,time_basis_desc,time_precision_desc,canonical_key_desc,id_desc', data_as_of: '2026-09-08', ...meta },
  }
}
