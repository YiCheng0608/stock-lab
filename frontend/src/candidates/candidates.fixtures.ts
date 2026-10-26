import type { CandidateComponent, CandidateItem, CandidateLlmNote, CandidatesResponse, CandidateSubItem } from '../types'

// Shapes copied from GET /api/candidates on a read-only copy of the production DB (2026-10-16 run, #215),
// trimmed to two rows: a complete row and a partial row whose group and news components are null.

const sub = (value: number | null, percentile: number | null, weight: number, better: string, nullReason: string | null = null, nullExplanation: string | null = null): CandidateSubItem => ({
  value, percentile, weight, better, null_reason: nullReason, null_explanation: nullExplanation,
})

const NO_GROUP = '當日沒有已排名且資料完整的所屬產業或題材'
const NO_NEWS = '近 3 日沒有成功的新聞收集，新聞分項無資料'

function technical(score: number): CandidateComponent {
  return {
    label: '技術', score, weight: 0.35, inference: false, item_coverage: 1, null_reason: null, null_explanation: null,
    items: {
      volume_ratio: sub(2.8847035888649, 0.5957446808510638, 0.5, 'higher'),
      distance: sub(0.0031055900621117516, 0.8936170212765957, 0.5, 'lower'),
      risk_reward: sub(1.600543478260863, 0.5319148936170213, 0, 'higher'),
    },
  }
}

function chips(score: number): CandidateComponent {
  return {
    label: '籌碼', score, weight: 0.3, inference: false, item_coverage: 1, null_reason: null, null_explanation: null,
    items: {
      institutional_flow_5d: sub(2.5860654584767193, 0.9708237986270023, 0.4, 'higher'),
      institutional_flow_20d: sub(4.5892246199002455, 0.9713589274832419, 0.3, 'higher'),
      margin_change_5d: sub(-0.059222967165205434, 0.8150921658986175, 0.3, 'lower'),
    },
  }
}

const groupNull: CandidateComponent = {
  label: '族群', score: null, weight: 0.2, inference: false, item_coverage: 0, null_reason: 'no_qualified_group', null_explanation: NO_GROUP,
  items: { board_percentile: sub(null, null, 1, 'higher', 'no_qualified_group', NO_GROUP) }, source: null,
}

const newsNull: CandidateComponent = {
  label: '新聞情緒', score: null, weight: 0.15, inference: true, item_coverage: 0, null_reason: 'news_collection_missing', null_explanation: NO_NEWS,
  items: { net_direction: sub(null, null, 1, 'higher', 'news_collection_missing', NO_NEWS) },
}

const sources = {
  signal: 'analysis:breakout_v1',
  market_bar: 'twse',
  chips: 'twse_t86+twse_margin',
  groups: 'hot_group_v1',
  news: 'news_items+news_llm_results:news_v1',
}

// Complete row: every component has a value, a news reason is inference, and the stock ranks on a theme board.
export function completeItem(): CandidateItem {
  return {
    rank: 1,
    trading_date: '2026-10-16',
    score_version: 'candidate_score_v1',
    instrument: { id: 314, exchange: 'TWSE', symbol: '2377', name: '微星', instrument_type: 'stock' },
    strategy: 'breakout_v1',
    signal_id: 5987,
    signal_status: 'conditional',
    levels: {
      entry_type: 'breakout', entry: 161.5, entry_zone: { low: 161.5, high: 161.5 },
      invalid_price: 157.82, target_1: 167.39, target_2: 172.54, risk_reward: 1.6005, earliest_execution_date: '2026-10-19',
    },
    total_score: 0.827566,
    weight_coverage: 1,
    partial_components: false,
    components: {
      technical: technical(0.7446808510638298),
      chips: chips(0.9242648474653588),
      news_sentiment: {
        label: '新聞情緒', score: 0.81, weight: 0.15, inference: true, item_coverage: 1, null_reason: null, null_explanation: null,
        items: { net_direction: sub(2, 0.81, 1, 'higher') },
      },
      group: {
        label: '族群', score: 0.9, weight: 0.2, inference: false, item_coverage: 1, null_reason: null, null_explanation: null,
        items: { board_percentile: sub(0.9, 0.9, 1, 'higher') },
        source: { group_id: 'theme-ai-server', name: 'AI 伺服器', board: 'theme', rank: 2, board_size: 11 },
      },
    },
    alternatives: [{ strategy: 'pullback_v1', signal_id: 5990, total_score: 0.61 }],
    reasons: [
      { code: 'institutional_net_buy_5d', component: 'chips', text: '三大法人 5 日淨買超，約 20 日均量的 2.59 倍', params: { ratio: '2.59' }, inference: false },
      { code: 'breakout_20d_high', component: 'technical', text: '突破 20 日高點，量比 2.9', params: { volume_ratio: '2.9' }, inference: false },
      { code: 'hot_group_rank', component: 'group', text: '所屬題材「AI 伺服器」熱度第 2', params: { board: '題材', name: 'AI 伺服器', rank: '2' }, inference: false },
      { code: 'news_positive_3d', component: 'news_sentiment', text: '近 3 日 2 則偏多新聞（推論）', params: { count: '2' }, inference: true },
    ],
    groups: [
      { group_id: 'theme-ai-server', name: 'AI 伺服器', board: 'theme', qualified: true, rank: 2, board_size: 11, board_percentile: 0.9, score: 71.2, data_quality: 'complete', score_date: '2026-10-16' },
      { group_id: 'official-industry-d60be8febbae1cd6', name: '電腦及週邊', board: 'industry', qualified: false, rank: null, board_size: null, board_percentile: null, score: null, data_quality: 'insufficient_data', score_date: '2026-10-16' },
    ],
    data_as_of: '2026-10-16',
    llm_note: doneNote(),
    sources,
    market: { trading_date: '2026-10-16', close: 162, change: 3.5, change_pct: 0.022082, change_status: 'known', source: 'twse' },
  }
}

// A done candidate LLM note (#220); the partial row below has none (responses from before #220 omit the field).
export function doneNote(): CandidateLlmNote {
  return {
    status: 'done',
    inference: true,
    selection: '三大法人 5 日淨買超約 20 日均量 2.59 倍、籌碼分項 92 分居前，並突破 20 日高點，所屬題材 AI 伺服器熱度第 2。',
    levels: '規則的進場區為 161.50，條件失效的停損 157.82；第一目標 167.39、第二目標 172.54，RR 1.60。',
    risks: '新聞情緒分項來自 AI 方向判讀，屬推論；所屬產業「電腦及週邊」當日未排名。',
    model: 'claude-sonnet-5-5',
    prompt_version: 'candidate_notes_v1',
    generated_at: '2026-10-16T11:05:00+00:00',
    input_hash: 'a'.repeat(64),
  }
}

// Partial row as produced on 2026-10-16: group and news null, weight_coverage 0.65.
export function partialItem(): CandidateItem {
  return {
    rank: 2,
    trading_date: '2026-10-16',
    score_version: 'candidate_score_v1',
    instrument: { id: 1520, exchange: 'TPEx', symbol: '6026', name: '福邦證', instrument_type: 'stock' },
    strategy: 'pullback_v1',
    signal_id: 6001,
    signal_status: 'conditional',
    levels: {
      entry_type: 'pullback', entry: 13.2, entry_zone: { low: 13.05, high: 13.35 },
      invalid_price: 12.75, target_1: 13.92, target_2: null, risk_reward: 1.6, earliest_execution_date: null,
    },
    total_score: 0.825,
    weight_coverage: 0.65,
    partial_components: true,
    components: { technical: technical(0.8571428571428572), chips: chips(0.7884297082096952), news_sentiment: newsNull, group: groupNull },
    alternatives: [],
    reasons: [
      { code: 'pullback_ma20_support', component: 'technical', text: '回測 20 日均線，距均線 1.2%，量比 0.8', params: {}, inference: false },
      { code: 'foreign_trust_net_buy_5d', component: 'chips', text: '外資＋投信 5 日淨買超', params: {}, inference: false },
    ],
    groups: [
      { group_id: 'official-industry-finance', name: '金融', board: 'industry', qualified: false, rank: null, board_size: null, board_percentile: null, score: null, data_quality: 'insufficient_data', score_date: '2026-10-16' },
    ],
    data_as_of: '2026-10-16',
    sources: { ...sources, signal: 'analysis:pullback_v1', market_bar: 'tpex', chips: 'tpex_3insti+tpex_margin' },
    // The previous session's bar came from another source, so the change is not shown.
    market: { trading_date: '2026-10-16', close: 13.2, change: null, change_pct: null, change_status: 'unverified', source: 'tpex' },
  }
}

// A note that was attempted and failed: no text, no model.
export function pendingNote(): CandidateLlmNote {
  return { ...doneNote(), status: 'pending', selection: null, levels: null, risks: null, model: null }
}

// Twelve rows for the today list (top 10 plus 「顯示其餘 2 檔」): #1 has a done note, #2 none, #3 a pending note,
// #4 a falling close, #5 no bar on the day; the rest copy #1 under other symbols.
export function longList(): CandidatesResponse {
  const items = Array.from({ length: 12 }, (_, index): CandidateItem => {
    const base = index === 1 ? partialItem() : completeItem()
    const rank = index + 1
    const symbol = index <= 1 ? base.instrument.symbol : String(2400 + rank)
    return { ...base, rank, instrument: { ...base.instrument, id: 9000 + rank, symbol } }
  })
  items[2] = { ...items[2], llm_note: pendingNote() }
  items[3] = { ...items[3], market: { trading_date: '2026-10-16', close: 98.5, change: -1.5, change_pct: -0.015, change_status: 'known', source: 'twse' } }
  items[4] = { ...items[4], market: { trading_date: '2026-10-16', close: null, change: null, change_pct: null, change_status: 'missing', source: null } }
  return { ...run(items), candidate_count: items.length }
}

const methodology: CandidatesResponse['methodology'] = {
  score_version: 'candidate_score_v1',
  purpose: '評分只用於排序，不代表勝率或預期報酬，不改變策略判定',
  weights: { technical: 0.35, chips: 0.3, group: 0.2, news_sentiment: 0.15 },
  minimum_weight_coverage: 0.65,
  components: {
    technical: { label: '技術', weight: 0.35, inference: false },
    chips: { label: '籌碼', weight: 0.3, inference: false },
    group: { label: '族群', weight: 0.2, inference: false },
    news_sentiment: { label: '新聞情緒', weight: 0.15, inference: true },
  },
  null_explanations: { no_qualified_group: NO_GROUP, news_collection_missing: NO_NEWS },
}

function run(items: CandidateItem[], zero: Pick<CandidatesResponse, 'zero_reason' | 'zero_reason_text'> = { zero_reason: null, zero_reason_text: null }): CandidatesResponse {
  return {
    status: 'success',
    trading_date: '2026-10-16',
    score_version: 'candidate_score_v1',
    computed_at: '2026-10-18T07:57:24.662291',
    evaluated_signals: 4622,
    pool_count: items.length ? 84 : 0,
    candidate_count: items.length,
    ...zero,
    exclusions: {},
    data_as_of: '2026-10-16',
    news_coverage: null,
    methodology,
    items,
  }
}

export const listResponse = (): CandidatesResponse => run([completeItem(), partialItem()])

export const zeroResponse = (reason: 'no_actionable_signals' | 'all_excluded'): CandidatesResponse => run([], {
  zero_reason: reason,
  zero_reason_text: reason === 'no_actionable_signals' ? '當日沒有成立（條件成立）的策略訊號' : '成立的訊號都因 ETF、價位不合法或評分資料不足被排除',
})

export const notComputedResponse = (): CandidatesResponse => ({
  status: 'not_computed',
  trading_date: null,
  score_version: 'candidate_score_v1',
  candidate_count: 0,
  zero_reason: null,
  zero_reason_text: null,
  methodology: { ...methodology, weights: null, minimum_weight_coverage: null },
  items: [],
})
