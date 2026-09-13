export function legacyRouteTarget(pathname: string, search = ''): string | null {
  if (pathname === '/groups') return '/themes'
  if (pathname.startsWith('/groups/')) return '/themes/' + encodeURIComponent(pathname.slice('/groups/'.length))
  if (pathname === '/instruments') return '/stocks'
  if (pathname.startsWith('/instruments/')) {
    const symbol = pathname.slice('/instruments/'.length)
    const exchange = new URLSearchParams(search).get('exchange')
    return exchange
      ? '/stocks/' + encodeURIComponent(exchange) + '/' + encodeURIComponent(symbol)
      : '/stocks?q=' + encodeURIComponent(symbol)
  }
  if (pathname === '/signals' || pathname === '/tracking' || pathname === '/portfolio') return '/actions'
  if (pathname === '/data-quality') return '/system/data-quality'
  if (pathname === '/backtest') return '/research/backtest'
  return null
}
