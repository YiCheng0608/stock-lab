// The name of the strategy behind 今日名單 (#577; UI_COPY_SPEC §10 今日名單頁首, §13 策略說明). It is defined once, here:
// the 策略說明 page and the 今日名單 head read these, and copy.test.tsx fails when another source file spells the name out.
// The glossary term (glossary.ts and backend/app/glossary.py, which backend/tests/test_glossary.py compares) is the only
// other place that writes it, because the term is data the API serves.
export const STRATEGY_NAME = '順勢籌碼型'
export const STRATEGY_TERM_ID = 'trend_chips'
// The 今日名單 head link to /strategy: the name first, so the reader sees which strategy made the list.
export const STRATEGY_LINK_LABEL = `${STRATEGY_NAME} · 策略說明 →`
