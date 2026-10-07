import type { InstitutionalWindowsData } from './types'
import { validChips1006Identity, validChips1006Read } from './components/StockOverview'

// An explicit independent v2 selection; the original validators default to v1.
export const validCalendarWindowIdentity = (data: InstitutionalWindowsData, exchange?: string, symbol?: string, cutoff?: string) =>
  validChips1006Identity(data, exchange, symbol, cutoff, true)
export const validCalendarWindowRead = (data: InstitutionalWindowsData, exchange?: string, symbol?: string, cutoff?: string) =>
  validChips1006Read(data, exchange, symbol, cutoff, true)
