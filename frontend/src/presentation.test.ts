import { backtestTrackingLabel, groupDisplayName, staleCloseDateLabel, stockGroupLabel, researchRequirementLabel, stockDirectoryActionLabel, formatProductTimeRole, PRODUCT_TIME_NOTE, levelFieldLabel, levelObservationZoneLabel, levelSemanticsLabel, productTimeRoleDateTime, productTimeRoleKnown, productTimeRoleLabel, stopPriceFieldLabel } from './presentation'

function expect(condition: boolean, message: string): void {
  if (!condition) throw new Error(message)
}

const known = {
  version: 'signal-level-semantics/v1',
  kind: 'rule_reference',
  fields: {
    trigger_price: { label_zh: '規則觸發價' },
    entry_low: { label_zh: '規則回踩觀察區下緣' },
  },
}
const spoofedUnknown = {
  version: 'signal-level-semantics/v1',
  kind: 'unknown',
  fields: { target_1: { label_zh: 'AI 目標價' } },
}
const unrecognizedVersion = {
  version: 'signal-level-semantics/v0',
  kind: 'rule_reference',
  fields: { trigger_price: { label_zh: '觸發價' } },
}

expect(levelFieldLabel('trigger_price', known) === '規則觸發價', 'known trigger label')
expect(levelFieldLabel('target_1', spoofedUnknown) === '價位（語意未確認）', 'unknown labels must not trust payload')
expect(levelFieldLabel('trigger_price', unrecognizedVersion) === '價位（語意未確認）', 'unrecognized version fallback')
expect(levelObservationZoneLabel(known) === '規則回踩觀察區', 'pullback range label')
expect(levelSemanticsLabel(spoofedUnknown) === '未驗證規則參考價', 'unknown semantics fallback')
expect(stopPriceFieldLabel({ kind: 'user_position_risk_input', origin: 'portfolio_position.stop_price' }) === '持倉設定風險價', 'position stop origin')
expect(stopPriceFieldLabel({ kind: 'rule_reference', origin: 'signal.invalid_price' }) === '規則失效參考價', 'rule stop origin')
expect(stopPriceFieldLabel({ kind: 'unknown', origin: 'signal.invalid_price' }) === '風險價位（語意待核實）', 'unknown stop origin')
expect(productTimeRoleLabel('market_date') === '資料日期', 'market date label')
expect(productTimeRoleLabel('decision_at') === '決策時間', 'decision time label')
expect(productTimeRoleKnown({ status: 'known', precision: 'date', value: '2026-09-08' }), 'known product date')
expect(!productTimeRoleKnown({ status: 'known', precision: 'invalid', value: '2026-09-08' }), 'invalid precision fallback')
expect(!productTimeRoleKnown({ status: 'unknown', precision: 'date', value: '2026-09-08' }), 'unknown product date')
expect(!productTimeRoleKnown({ status: 'known', precision: 'date', value: null }), 'missing product time')
expect(formatProductTimeRole(undefined, 'market_date', '2026-09-08') === '2026/09/08', 'legacy date fallback')
expect(formatProductTimeRole(undefined, 'market_date', '2026-02-30') === '待核實', 'invalid legacy date')
expect(formatProductTimeRole({ roles: { market_date: { role: 'market_date', status: 'known', precision: 'date', value: '2026-09-08' } } } as never, 'market_date') === '2026/09/08', 'product date formatting')
// #465 (PR 473 review): the backend sends every unknown role as value=null, utc=null (product_time._unknown), so
// only the reason tells them apart. *_not_persisted (the system never stored it) and a missing role read 未記錄;
// every other unknown is a value that failed its check and reads 待核實. Neither uses the legacy fallback.
const unknownRole = (role: string, reason?: string) => ({ roles: { [role]: { role, status: 'unknown', precision: 'none', value: null, utc: null, ...(reason ? { reason } : {}) } } }) as never
expect(formatProductTimeRole(unknownRole('decision_at', 'legacy_decision_at_not_persisted'), 'decision_at') === '未記錄', 'a decision time the system never stored is 未記錄')
expect(formatProductTimeRole(unknownRole('published_at', 'news_published_at_not_persisted'), 'published_at', '2026-09-08') === '未記錄', 'a *_not_persisted role is 未記錄 and must not use fallback')
expect(formatProductTimeRole(unknownRole('published_at', 'time_consistency_conflict'), 'published_at') === '待核實', 'a time conflict is 待核實, not 未記錄')
expect(formatProductTimeRole(unknownRole('published_at', 'published_at_naive_timezone_missing'), 'published_at') === '待核實', 'a value without a time zone is 待核實, not 未記錄')
expect(formatProductTimeRole(unknownRole('event_date', 'event_date_invalid'), 'event_date') === '待核實', 'an invalid value is 待核實')
expect(formatProductTimeRole(unknownRole('published_at'), 'published_at', '2026-09-08') === '待核實', 'an unknown role without a reason is 待核實 and must not use fallback')
expect(formatProductTimeRole({ roles: { decision_at: { role: 'decision_at', status: 'unknown', precision: 'instant', value: '2026-09-08T09:00:00' } } } as never, 'decision_at') === '待核實', 'an unconfirmed value stays 待核實')
expect(formatProductTimeRole({ roles: {} } as never, 'decision_at') === '未記錄', 'a role the response lacks is 未記錄')
expect(PRODUCT_TIME_NOTE === '時間以台灣時間顯示；系統沒有記錄的時間寫「未記錄」，有值但尚未確認的寫「待核實」。', 'the time note tells 未記錄 from 待核實')
expect(formatProductTimeRole({ roles: { published_at: { role: 'published_at', status: 'known', precision: 'instant', value: '2026-09-08T00:00:00' } } } as never, 'published_at') === '待核實', 'naive instant')
expect(productTimeRoleDateTime({ roles: { published_at: { role: 'published_at', status: 'known', precision: 'instant', value: '2026-09-08T00:00:00+00:00' } } } as never, 'published_at') === '2026-09-08T00:00:00+00:00', 'aware instant metadata')
expect(formatProductTimeRole({ roles: { published_at: { role: 'published_at', status: 'known', precision: 'instant', value: '2026-09-08Z' } } } as never, 'published_at') === '待核實', 'date-only Z is not an instant')
expect(productTimeRoleDateTime({ roles: { published_at: { role: 'published_at', status: 'known', precision: 'instant', value: '2026-09-08Z' } } } as never, 'published_at') === undefined, 'invalid instant metadata is not emitted as dateTime')

expect(groupDisplayName('ETF · broad_market') === 'ETF · 大盤型', 'ETF group category is translated')
expect(groupDisplayName('ETF · bond') === 'ETF · 債券型', 'bond ETF category is distinct')
expect(groupDisplayName('ETF · unknown_new') === 'ETF · 分類待核實', 'unknown ETF enum is not leaked')
expect(groupDisplayName('Industry 24') === '產業名稱待核實', 'unverified industry code is not promoted')
expect(researchRequirementLabel('prior_20_highs') === '前 20 個交易日高點', 'requirement codes are translated')
expect(researchRequirementLabel('unknown_new') === '條件名稱待核實', 'unknown requirements are not fabricated')
expect(stockDirectoryActionLabel('new_state', 'new_state') === '研究動作待核實', 'unknown action label is not leaked')

expect(stockDirectoryActionLabel('wait_pullback') === '等待回踩條件', 'known state survives an absent translated label')
expect(researchRequirementLabel('族群相對 TAIEX 的20日超額報酬') === '族群相對 加權指數 的20日超額報酬', 'mixed Chinese requirement translates benchmark name')

expect(stockGroupLabel({ name: 'Industry · Financial', display_name: '金融', verified: true }) === '金融', 'verified industry row shows the official display name')
expect(stockGroupLabel({ name: null, display_name: null, verified: false }) === '族群關聯待核實', 'unverified row stays fail-closed')
expect(stockGroupLabel({ name: 'Industry · Shipping', display_name: '航運', verified: false }) === '族群關聯待核實', 'unverified row never shows a leaked name')
expect(stockGroupLabel({ name: 'ETF · broad_market', display_name: 'ETF 分類：broad_market', verified: true }) === 'ETF · 大盤型', 'ETF rows keep the translated category')
expect(stockGroupLabel({ name: 'New listings', display_name: '新上市標的', verified: true }) === '新上市族群', 'new-listing row keeps its product label')
expect(stockGroupLabel({ name: 'Industry · X', display_name: ' ', verified: true }) === '族群名稱待核實', 'blank display name is not shown as empty')

// Issue #212: an old close in the stock directory carries its own date.
expect(staleCloseDateLabel('2026-10-14', '2026-10-22') === '（2026/10/14）', 'older close shows its date')
expect(staleCloseDateLabel('2026-10-22T00:00:00', '2026-10-22') === null, 'current close has no extra date')
expect(staleCloseDateLabel('2026-10-14', null) === '（2026/10/14）', 'unknown latest session still dates the close')
expect(staleCloseDateLabel(null, '2026-10-22') === null, 'no close date, no label')
expect(staleCloseDateLabel('not a date', '2026-10-22') === null, 'malformed date is not shown')
expect(backtestTrackingLabel('v2') === '追蹤口徑 v2', 'backtest names its tracking version')
expect(backtestTrackingLabel(null) === '追蹤口徑 未記錄', 'a run without a version says so')
