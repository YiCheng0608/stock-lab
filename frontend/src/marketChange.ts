// Why a stock has no change against the previous session, the same words on every page (UI_COPY_SPEC §8.2, #475).
// The status comes from the API (backend app.market_change.no_close_status): the candidate and theme member
// `market.change_status`, the action summary `price_change_status` and the bars API `latest_change.change_status`.
export function noPreviousCloseText(status: string | null | undefined): string | null {
  // The source published the previous session without this stock's close (#465).
  if (status === 'no_previous_close') return '前一交易日無收盤'
  // The master lists the stock only from this session (#475): a new listing, or the first session after a
  // market transfer, whose master row starts on the transfer day (#493).
  if (status === 'first_trading_day') return '掛牌首日'
  return null
}
