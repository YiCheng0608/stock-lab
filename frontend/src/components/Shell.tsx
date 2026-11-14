import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { getDataDate } from '../api'
import type { DataDate } from '../types'
import { Navbar } from './Navbar'
import { PageDateContext } from './pageDate'

export function Shell({ children }: { children: ReactNode }) {
  // The data date alone (Issue 601): every page shows it, so it must not cost the whole dashboard.
  const dataDate = useQuery<DataDate>({ queryKey: ['data-date'], queryFn: getDataDate })
  const day = dataDate.data?.as_of?.slice(0, 10) ?? null
  // The page date the cards compare with (#661): only a loaded date; loading, failed or none leaves every date shown.
  const pageDate = !dataDate.isLoading && !dataDate.isError ? day : null
  return (
    <div className="app-shell">
      <Navbar dataDate={day} dataDateLoading={dataDate.isLoading} dataDateError={dataDate.isError} />
      <main className="container"><PageDateContext.Provider value={pageDate}>{children}</PageDateContext.Provider></main>
      <footer className="container site-footer">
        {/* Issue 729: data labels only; how to read the pages stays in the Issues. */}
        <span>僅使用官方資料</span>
        {/* One entry (Issue 631): news, the research pages and the glossary are listed on /system. */}
        <nav className="secondary-nav" aria-label="次要工具">
          <Link to="/system">系統</Link>
        </nav>
      </footer>
    </div>
  )
}
