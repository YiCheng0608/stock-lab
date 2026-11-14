// Issue 729 (decision 6881593041; PRODUCT_SPEC §1 顯示原則): copy that left the pages because it explains rather than shows:
// research status, how to read a page, process notes and words for developers. The tests render the pages that held it
// and check that none of these comes back. The full original text is kept in the Issue's AC-1 list.
export const REMOVED_COPY: readonly string[] = [
  // 1-A, 1-B, 1-E1: the research status and its link (Issue 693).
  '現行規則尚無證據',
  '研究結論',
  'strategy-evidence',
  '前瞻驗證',
  // 4-1, 4-2: the head's how-to-read clause and the score disclaimer.
  '才可研究進場',
  '評分只用於排序',
  // 3-1 to 3-3: internal version ids beside the data.
  'indicators/v1',
  '提示版本',
  'LLM 判讀',
  'hot_group_v1',
  // 4-3, 4-4: how the chart is drawn.
  '不是成交價',
  '缺日不補',
  '原始價為基準',
  '區間與日K／週K 跟著上方 K 線卡',
  // 4-5: how to read the strategy board and the score table.
  '每個研究條件各自判定',
  '價位為參考，成立當天依實際資料重算',
  '越高越好',
  '加入後每日依日線規則模擬',
  // 4-6: the disclaimer.
  '此為研究工具與資料摘要',
  // 4-7: the financials method notes.
  '不納入策略或評分',
  '研究截止日期以可得日篩選',
  // 3-9 to 3-14, 4-13: audit values, source codes, progress and notes for developers.
  '來源稽核原值',
  '（twse_t86）',
  '（twse_margin）',
  '尚未提供整合的券商分點',
  '券商分點是交易通道',
  '決策時間',
  '時間以台灣時間顯示',
  '規則與官方資料詳見',
  '策略判斷資料已齊備',
  // 3-15: the footer's flow note and its pointer.
  'T 日收盤訊號',
  '詳細來源見',
]

// Phrases of REMOVED_COPY found in a page's markup.
export function removedCopyIn(markup: string): string[] {
  return REMOVED_COPY.filter((phrase) => markup.includes(phrase))
}
