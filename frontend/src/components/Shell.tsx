import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { getDataDate } from '../api'
import type { DataDate } from '../types'
import { Navbar } from './Navbar'

export function Shell({ children }: { children: ReactNode }) {
  // The data date alone (Issue 601): every page shows it, so it must not cost the whole dashboard.
  const dataDate = useQuery<DataDate>({ queryKey: ['data-date'], queryFn: getDataDate })
  return (
    <div className="app-shell">
      <Navbar dataDate={dataDate.data?.as_of?.slice(0, 10) ?? null} dataDateLoading={dataDate.isLoading} dataDateError={dataDate.isError} />
      <main className="container">{children}</main>
      <footer className="container site-footer">
        <span>T 日收盤訊號 · 最早 T+1 執行 · T+5／T+20 追蹤</span>
        <span>僅使用官方資料 · 詳細來源見個股頁「資料來源」分頁、今日名單與大盤頁的「資料說明」</span>
        {/* One entry (Issue 631): news, the research pages and the glossary are listed on /system. */}
        <nav className="secondary-nav" aria-label="次要工具">
          <Link to="/system">系統</Link>
        </nav>
      </footer>
    </div>
  )
}
