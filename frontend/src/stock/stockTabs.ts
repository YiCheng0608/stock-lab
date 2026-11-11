// Stock page tabs follow ?tab= (#278), so /actions/:exchange/:symbol can land on the research tab and a tab is a link.
export type StockTab = 'chart' | 'chips' | 'financials' | 'news' | 'research' | 'data'

export const STOCK_TABS: ReadonlyArray<{ id: StockTab; label: string }> = [
  { id: 'chart', label: '走勢' },
  { id: 'chips', label: '籌碼' },
  { id: 'financials', label: '財務' },
  { id: 'news', label: '新聞與公告' },
  { id: 'research', label: '進出場' },
  { id: 'data', label: '資料來源' },
]

export const DEFAULT_STOCK_TAB: StockTab = 'chart'

export function parseStockTab(value: string | null | undefined): StockTab {
  return STOCK_TABS.some((tab) => tab.id === value) ? value as StockTab : DEFAULT_STOCK_TAB
}

// The page's other parameters (as_of) stay; the default tab is not written.
export function stockTabSearch(current: URLSearchParams, tab: StockTab): URLSearchParams {
  const next = new URLSearchParams(current)
  if (tab === DEFAULT_STOCK_TAB) next.delete('tab')
  else next.set('tab', tab)
  return next
}
