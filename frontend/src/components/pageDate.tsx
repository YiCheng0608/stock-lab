import { createContext, useContext, type ReactNode } from 'react'

import { formatDay } from '../dates'

// The page's one data date (#661, DESIGN_SYSTEM §7): the navbar badge states it once at every width; a card or line
// whose date is the same day says nothing, one with another day still states its own. Null while the date is
// loading, failed or missing, and then every date is shown as before.
export const PageDateContext = createContext<string | null>(null)

export function usePageDate(): string | null {
  return useContext(PageDateContext)
}

/** True only when both are days and the same day; an unknown page date or value is never 「the same」. */
export function sameDay(value: string | null | undefined, pageDate: string | null | undefined): boolean {
  const day = formatDay(value) ?? (value && /^\d{4}\/\d{2}\/\d{2}$/.test(value) ? value : null)
  const page = formatDay(pageDate) ?? (pageDate && /^\d{4}\/\d{2}\/\d{2}$/.test(pageDate) ? pageDate : null)
  return day != null && day === page
}

/** Whether a date the page would print equals the page date (so it is left out). */
export function useSameAsPage(value: string | null | undefined): boolean {
  return sameDay(value, usePageDate())
}

/** Its children only when `date` is not the page date: a date phrase inside a line (#661). */
export function UnlessPageDate({ date, children }: { date: string | null | undefined; children: ReactNode }) {
  return useSameAsPage(date) ? null : <>{children}</>
}
