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
  // Issue 732 (the other pages; decisions 6881593041 and 6883315647). 3-4, 3-5, N-7: the news AI rows' versions and
  // check rule; 3-6: the raw ids; 4-12: the news list lead.
  '核對規則',
  '候選標的不作為交易理由',
  '原始資料識別碼',
  '事件識別碼',
  '國內、國際財經新聞與官方公告',
  // 3-7, N-3: the plan's versions; 3-8, N-1, N-2: the portfolio audit notes and formulas; 4-9: the 我的追蹤 notes.
  'plan_tracking_v',
  'institutional-flow/',
  '版本、來源與逐日明細',
  '來源稽核原股數',
  '核對庫存原股數',
  '可展開每筆庫存核對',
  '記錄日期不表示交易日',
  '記錄資料時間',
  '可交易用途尚未核對',
  '持倉風險列在',
  '有持倉風險時列在',
  '股數 × 本地收盤',
  '平均成本 × 股數',
  '把有興趣的候選加入追蹤',
  '自選標的一律顯示',
  '計畫價位來自建立當日',
  '價格為當日原始日線',
  // 4-10: how the theme board is scored.
  '各自成榜',
  '名稱後的兩個分項',
  '檔是當日今日名單中',
  // 4-11: the stock directory lead.
  '市場標的目錄',
  '缺資料優先級只來自',
  // 3-16: the 系統 lead.
  '每天選股用不到',
  // 4-8, N-5, N-6: the market page lead, the row hint, the MA60 method and the change and roll methods.
  '三檔指數的總表',
  '點一列',
  '季線位置只是背景資訊',
  '個交易日收盤的平均',
  '換月日不計漲跌',
  '換月不做價差調整',
  '每月第三個週三',
  // N-8, N-9: the theme table version and the news rule version.
  '題材表版本',
  '規則核實 · v',
  '· 規則版本',
]

// Phrases of REMOVED_COPY found in a page's markup.
export function removedCopyIn(markup: string): string[] {
  return REMOVED_COPY.filter((phrase) => markup.includes(phrase))
}
