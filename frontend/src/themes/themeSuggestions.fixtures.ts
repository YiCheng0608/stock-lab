import type { ThemeSuggestion, ThemeSuggestionsResponse } from '../types'

// Shapes follow backend/app/theme_suggestions.py (/api/theme-suggestions).

export function suggestion(overrides: Partial<ThemeSuggestion> = {}): ThemeSuggestion {
  return {
    id: 11,
    theme_key: '無人機',
    display_name: '無人機',
    status: 'pending_verification',
    inference: true,
    news_count: 7,
    first_news_date: '2026-10-11',
    last_news_date: '2026-10-17',
    confidence: 'not_provided',
    matched_group: null,
    prompt_version: 'news_v1',
    aggregation_version: 'theme_suggestions_v1',
    llm_models: ['claude-haiku-5-5'],
    computed_at: '2026-10-18T01:00:00+00:00',
    news: [17, 16, 15, 14, 13].map((day) => ({
      news_id: 100 + day,
      title: `無人機訂單新聞 ${day}`,
      source_name: '鉅亨網',
      news_date: `2026-10-${day}`,
      theme_text: '無人機',
      reason: '國防無人機採購',
    })),
    ...overrides,
  }
}

export function suggestions(overrides: Partial<ThemeSuggestionsResponse['meta']> = {}): ThemeSuggestionsResponse {
  return {
    items: [
      suggestion(),
      suggestion({
        id: 12,
        theme_key: '液冷',
        display_name: '液冷',
        news_count: 1,
        first_news_date: '2026-10-17',
        last_news_date: '2026-10-17',
        news: [{ news_id: 201, title: '伺服器液冷滲透率提升', source_name: 'MoneyDJ', news_date: '2026-10-17', theme_text: '液冷', reason: null }],
      }),
    ],
    meta: {
      total: 3,
      limit: 2,
      include_matched: false,
      matched_total: 4,
      news_per_suggestion: 5,
      aggregation_version: 'theme_suggestions_v1',
      updated_at: '2026-10-18T01:00:00+00:00',
      sort: 'news_count desc, last_news_date desc, theme_key asc',
      ...overrides,
    },
  }
}
