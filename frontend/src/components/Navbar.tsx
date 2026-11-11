import { useEffect, useState } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'

import { NavSearch } from './NavSearch'
import { DateBadge } from './ui'

export { stockSearchPath } from '../search'

// Fixed 64px top bar (DESIGN_SYSTEM §4): logo, seven main links (#493; Issue 549 added 大盤 after 今日名單: the pages that ask for action, the data
// pages, the explanation), stock search with suggestions (NavSearch, Issue 599), data-date badge, hamburger on narrow screens.

export const MAIN_NAV: ReadonlyArray<{ to: string; label: string; end?: boolean }> = [
  { to: '/', label: '今日名單', end: true },
  { to: '/market', label: '大盤' },
  { to: '/watch', label: '我的追蹤' },
  { to: '/themes', label: '族群' },
  { to: '/stocks', label: '個股' },
  { to: '/news', label: '新聞' },
  { to: '/strategy', label: '策略說明' },
]

function Logo() {
  return (
    <span className="logo-mark" aria-hidden="true">
      <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="3 17 9 11 13 15 21 7" />
        <polyline points="15 7 21 7 21 13" />
      </svg>
    </span>
  )
}

function MenuIcon({ open }: { open: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      {open
        ? <><line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" /></>
        : <><line x1="4" y1="7" x2="20" y2="7" /><line x1="4" y1="12" x2="20" y2="12" /><line x1="4" y1="17" x2="20" y2="17" /></>}
    </svg>
  )
}

export function Navbar({ dataDate, dataDateLoading = false, dataDateError = false }: { dataDate: string | null; dataDateLoading?: boolean; dataDateError?: boolean }) {
  const [open, setOpen] = useState(false)
  const location = useLocation()
  useEffect(() => setOpen(false), [location.pathname, location.search])
  return (
    <header className="navbar">
      <div className="navbar-inner">
        <Link to="/" className="navbar-brand"><Logo /><span>台股研究台</span></Link>
        <button type="button" className="btn btn-ghost navbar-toggle" aria-expanded={open} aria-controls="navbar-menu" aria-label={open ? '關閉選單' : '開啟選單'} onClick={() => setOpen((value) => !value)}>
          <MenuIcon open={open} />
        </button>
        <div id="navbar-menu" className={open ? 'navbar-menu navbar-menu-open' : 'navbar-menu'}>
          <nav className="navbar-links" aria-label="主要導覽">
            {MAIN_NAV.map((item) => <NavLink key={item.to} to={item.to} end={item.end}>{item.label}</NavLink>)}
          </nav>
          <div className="navbar-tools">
            <NavSearch />
            {!dataDateLoading && <DateBadge date={dataDate} unavailable={dataDateError && !dataDate} />}
          </div>
        </div>
      </div>
    </header>
  )
}
