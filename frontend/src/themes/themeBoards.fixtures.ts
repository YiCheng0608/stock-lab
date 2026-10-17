import type {
  NewsItem,
  ThemeBoard,
  ThemeBoardEmptyReason,
  ThemeBoardItem,
  ThemeBoardResponse,
  ThemeDetail,
  ThemeEvidence,
  ThemeMembersResponse,
  ThemeTrendPoint,
} from '../types'

// Small fixtures shaped like the #162 board API (backend/app/api.py _board_item, _board_ranking, theme_detail,
// theme_members): two boards, an empty board per empty_reason, 20-day and 1-day trends, members with evidence.

export function boardItem(overrides: Partial<ThemeBoardItem> = {}): ThemeBoardItem {
  return {
    theme_id: 'industry-24',
    display_name: '半導體業',
    description: '依官方共同產業分類建立的市場族群。',
    board: 'industry',
    rank: 1,
    score: 81.25,
    quality: 'complete',
    components: { relative_return: 0.9, breadth: 0.75, volume_strength: 0.5, institutional_flow: 0.25, catalyst: 1 },
    relative_returns: { '1d': 0.0123, '5d': -0.0045, '20d': 0 },
    eligible_members: 12,
    member_count: 14,
    trading_date: '2026-09-08',
    ...overrides,
  }
}

function meta(board: ThemeBoard, total: number, overrides: Partial<ThemeBoardResponse['meta']> = {}): ThemeBoardResponse['meta'] {
  return {
    board,
    requested_date: null,
    trading_date: '2026-09-08',
    data_as_of: '2026-09-08',
    limit: 100,
    total,
    sort: 'rank asc',
    empty_reason: null,
    empty_message: null,
    ...overrides,
  }
}

export function industryBoard(): ThemeBoardResponse {
  const items = [
    boardItem(),
    boardItem({
      theme_id: 'industry-28',
      display_name: '電子零組件業',
      rank: 2,
      score: 64.4,
      quality: 'partial',
      components: { relative_return: 0.6, breadth: null, volume_strength: 0.8, institutional_flow: 0.4, catalyst: null },
      relative_returns: { '1d': -0.0231, '5d': 0.051, '20d': null },
      eligible_members: 30,
      member_count: 41,
    }),
  ]
  return { items, meta: meta('industry', items.length) }
}

export function themeBoard(): ThemeBoardResponse {
  const items = [
    boardItem({
      theme_id: 'theme-cowos',
      display_name: 'CoWoS 先進封裝',
      description: '台積電 CoWoS 先進封裝產能與設備供應鏈。',
      board: 'theme',
      rank: 1,
      score: 72.5,
      quality: 'partial',
      components: { relative_return: 1, breadth: 0.5, volume_strength: 0.75, institutional_flow: 0, catalyst: null },
      relative_returns: { '1d': 0.0302, '5d': 0.0711, '20d': 0.1204 },
      eligible_members: 8,
      member_count: 9,
    }),
    boardItem({ theme_id: 'theme-ai-server', display_name: 'AI 伺服器', board: 'theme', rank: 2, score: 55, quality: 'partial', components: { relative_return: 0.4, breadth: 0.25, volume_strength: 0.1, institutional_flow: 0.9, catalyst: null } }),
  ]
  // Official data date later than the score date: both are shown.
  return { items, meta: meta('theme', items.length, { trading_date: '2026-09-08', data_as_of: '2026-09-09' }) }
}

export const EMPTY_MESSAGES: Record<ThemeBoardEmptyReason, string> = {
  no_official_run: '尚無成功的官方資料擷取，無法提供族群榜。',
  no_board_scores: '此榜尚未計算；需先以 analyze 或 daily 產生族群分數。',
  no_scores_for_date: '該日沒有此榜的族群分數（非交易日或尚未計算）。',
  no_ranked_groups: '該日沒有達到至少 3 檔有效成員且資料足以計分的族群。',
}

export function emptyBoard(board: ThemeBoard, reason: ThemeBoardEmptyReason): ThemeBoardResponse {
  return { items: [], meta: meta(board, 0, { trading_date: reason === 'no_official_run' || reason === 'no_board_scores' ? null : '2026-09-08', empty_reason: reason, empty_message: EMPTY_MESSAGES[reason] }) }
}

function addDays(date: string, days: number): string {
  const value = new Date(`${date}T00:00:00Z`)
  value.setUTCDate(value.getUTCDate() + days)
  return value.toISOString().slice(0, 10)
}

export function trend(count: number): ThemeTrendPoint[] {
  return Array.from({ length: count }, (_, index) => ({
    trading_date: addDays('2026-08-12', index),
    score: 40 + index,
    rank: 20 - index,
    quality: index % 2 === 0 ? 'partial' : 'complete',
    eligible_members: 8,
  }))
}

export function evidence(overrides: Partial<ThemeEvidence> = {}): ThemeEvidence {
  return {
    kind: 'theme_table',
    url: 'https://example.test/cowos',
    relation: 'core_business',
    relevance: 'high',
    theme_version: 'themes_v1:2026.10.17',
    ...overrides,
  }
}

export function themeDetail(options: { trendDays?: number; truncated?: boolean } = {}): ThemeDetail {
  const { trendDays = 20, truncated = false } = options
  return {
    theme: {
      theme_id: 'theme-cowos',
      display_name: 'CoWoS 先進封裝',
      description: '台積電 CoWoS 先進封裝產能與設備供應鏈。',
      category: '題材',
      name_status: 'verified',
      qualified: false,
      score: 72.5,
      rank: null,
      trading_date: '2026-09-08',
      data_quality: 'partial',
      eligible_members: 8,
      metrics: { relative_return_1d: 0.0302, relative_return_5d: 0.0711, relative_return_20d: 0.1204, breadth: 0.5, volume_strength: 1.4, institutional_flow: 0.01 },
    },
    board: 'theme',
    data_as_of: '2026-09-08',
    trend: trend(trendDays),
    members_total: truncated ? 150 : 2,
    members_truncated: truncated,
    members_endpoint: '/api/themes/theme-cowos/members',
    members_as_of: '2026-09-08',
    members: [
      { exchange: 'TWSE', symbol: '2330', name: '台積電', instrument_type: 'stock', role: 'member', valid_from: '2026-01-01', valid_to: null, theme_evidence: evidence() },
      { exchange: 'TPEx', symbol: '3131', name: '弘塑', instrument_type: 'stock', role: 'member', valid_from: '2026-01-01', valid_to: null, theme_evidence: evidence({ relation: 'supply_chain', relevance: 'medium', url: 'https://example.test/gpm' }) },
    ],
  }
}

export function membersPage(): ThemeMembersResponse {
  const detail = themeDetail()
  return {
    theme: detail.theme,
    items: [
      {
        exchange: 'TWSE', symbol: '2330', name: '台積電', instrument_type: 'stock', is_watchlisted: false, status: 'active', role: 'member',
        theme_evidence: evidence(),
        latest_bar: { date: '2026-09-08', close: 1085 } as ThemeMembersResponse['items'][number]['latest_bar'],
      },
      {
        exchange: 'TPEx', symbol: '6187', name: '萬潤', instrument_type: 'stock', is_watchlisted: false, status: 'active', role: 'member',
        theme_evidence: evidence({ relation: 'product_line', relevance: 'low', url: 'javascript:alert(1)' }),
        latest_bar: null,
      },
    ],
    meta: { page: 2, page_size: 30, total: 32, total_pages: 2, has_previous: true, has_next: false },
  }
}

export function newsItems(count: number): NewsItem[] {
  return Array.from({ length: count }, (_, index) => ({
    id: String(100 + index),
    title: `CoWoS 擴產公告 ${index + 1}`,
    source_name: 'mops',
    event_date: index === 0 ? '2026-09-08' : null,
    event_at: null,
    published_at: '2026-09-07T08:00:00',
  }) as unknown as NewsItem)
}
