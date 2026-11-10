// What 策略說明 (/strategy) says about the current strategy (#577; UI_COPY_SPEC §13). These numbers are copy, not config: the
// rules are read from backend/app/strategies (base.py COMMON_CONFIRMATIONS, breakout_v1.py, pullback_v1.py, which
// breakout_v3 and pullback_v3 inherit) and the score from backend/app/domain.py (CANDIDATE_SCORE_V6). A change to either
// changes this file and UI_COPY_SPEC §13 in the same PR.

// What the strategy is made of: its two rules and its score, by version id.
export const COMPOSITION = { breakout: 'breakout_v3', pullback: 'pullback_v3', score: 'candidate_score_v6' } as const

export type ConfirmationRow = { key: 'group' | 'institutional' | 'margin'; name: string; threshold: string; meaning: string }

// The three confirmations both rules share (base.py COMMON_CONFIRMATIONS).
export const CONFIRMATIONS: ReadonlyArray<ConfirmationRow> = [
  {
    key: 'group', name: '族群',
    threshold: '所屬族群近 20 日報酬高於加權指數',
    meaning: '族群比大盤強，個股才有順風。',
  },
  {
    key: 'institutional', name: '法人',
    threshold: '三大法人 5 日淨買賣超 ≥ 20 日均量的 −0.3%（5 日合計賣超不超過一天均量的 0.3%）',
    meaning: '法人沒有明顯賣超；買超或小額賣超都算通過。',
  },
  {
    key: 'margin', name: '融資',
    threshold: '融資餘額 5 日增幅 ≤ 5%（非融資標的不適用這一條）',
    meaning: '融資增加太快，代表追價過熱。',
  },
]

export type ScoreRow = { key: 'technical' | 'chips' | 'group' | 'news_sentiment'; name: string; weight: number; inference?: boolean; looks: string }

// The four score components and their weights in percent (candidate_score_v6 weights; the sum is 100).
export const SCORE_COMPONENTS: ReadonlyArray<ScoreRow> = [
  {
    key: 'technical', name: '技術', weight: 35,
    looks: '量比（當日成交量 ÷ 前 20 日均量）與價位距離（突破型看距前 20 日高點，回踩型看距 20 日均線），兩項各占一半；在同一天、同一型的入選股之間比較。',
  },
  {
    key: 'chips', name: '籌碼', weight: 30,
    looks: '三大法人 5 日淨買超（占 40%）、20 日淨買超（占 30%），都除以 20 日均量；融資 5 日變動（占 30%，減少較好）。和當日全市場的股票比較。',
  },
  {
    key: 'group', name: '族群', weight: 20,
    looks: '所屬產業、題材族群在各自榜上的名次，越前面越高；兩種都有時取較高的。',
  },
  {
    key: 'news_sentiment', name: '新聞情緒', weight: 15, inference: true,
    looks: '近 3 日關聯新聞的淨方向（偏多 +1、偏空 −1），由 AI 判讀，所以標「推論」。',
  },
]
