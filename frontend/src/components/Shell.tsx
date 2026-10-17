import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { getDashboard } from '../api'
import type { Dashboard } from '../types'
import { Navbar } from './Navbar'

export function Shell({ children }: { children: ReactNode }) {
  const dashboard = useQuery<Dashboard>({ queryKey: ['dashboard'], queryFn: getDashboard })
  return (
    <div className="app-shell">
      <Navbar dataDate={dashboard.data?.as_of?.slice(0, 10) ?? null} dataDateLoading={dashboard.isLoading} />
      <main className="container">{children}</main>
      <footer className="container site-footer">
        <span>T 日收盤訊號 · 最早 T+1 執行 · T+5／T+20 追蹤</span>
        <span>僅使用官方資料 · 詳細來源見各頁資料說明</span>
        <nav className="secondary-nav" aria-label="次要工具">
          <Link to="/research/backtest">技術回測</Link>
          <Link to="/research/coverage">資料覆蓋度</Link>
          <Link to="/research/strategies">策略版本</Link>
          <Link to="/system/data-quality">資料品質</Link>
          <Link to="/glossary">用語表</Link>
        </nav>
      </footer>
    </div>
  )
}
