import type { Instrument, InstitutionalDailyData, InstitutionalWindowReceipt, InstitutionalWindowsData, OfficialEventsData, StockOverviewData, StockPriceSavedData } from '../types'
import { memoryPriceCaptureReady, PRICE_HEADERS, PRICE_SYMBOL_NAMES, priceMemoryInstrumentSupported, priceSourcePins, validStockPriceMemoryRead } from '../stockPriceMemoryRead'
import { privatePriceSupported, validStockPriceSavedRead } from '../stockPriceSavedRead'
import { validSavedFocusStock } from '../savedPriceFocus'
import { formatResearchDate, formatResearchDateTime } from '../stockResearch'
import { formatCanonicalShareLots, formatCanonicalShares, formatTableVolume, formatTableVolumeShares } from '../units'

const REASONS: Record<string, string> = {
  price_memory_capture_missing: '尚未載入本次官方單日行情。',
  price_cutoff_not_supported: '此來源只支持 2026/10/5、2026/10/6；請明示套用其中一日。',
  price_capture_not_enabled: '伺服器尚未明示啟用此官方行情載入。',
  price_instrument_not_supported: '此政策只支援已核准的上櫃普通股。',
  price_external_policy_pins_mismatch: '此官方行情的授權版本設定待核實。',
  price_capture_busy: '官方行情正在載入。',
  price_body_version_mismatch: '來源原件版本已變更，未採用數值。',
  window_capture_not_enabled: '伺服器尚未明示啟用法人窗口載入。',
  window_capture_configuration_invalid: '法人窗口設定無效，尚未啟用。',
  window_market_or_symbol_not_supported: '目前只支持上櫃 3105、6488。',
  window_cutoff_not_supported: '所選日期不在本次法人窗口的支持截止範圍；不沿用其他截止的數值。',
  window_memory_capture_missing: '尚未載入本次法人窗口。',
  window_capture_busy: '伺服器正在載入法人窗口，請稍後讀取。',
  window_capture_failed: '本次法人窗口載入失敗；已有嘗試不自動重試。',
  window_memory_evidence_invalid: '本次法人原件無法完整核對。',
  window_capture_request_failed: '法人窗口請求失敗；請核對伺服器狀態後讀取。',
  window_read_request_failed: '本次法人窗口讀取失敗；可再次讀取已取得的同批原件。',
  chips_memory_evidence_invalid: '本次法人窗口原件與版本未能通過核對。',
  institutional_window_expected_dates_missing: '窗口缺少所需交易日原件；缺值不作 0。',
  price_source_not_admitted: '這筆行情來源與用途尚待核對',
  price_ingestion_provenance_missing: '缺少合格的收集紀錄關聯',
  price_raw_evidence_missing: '缺少可回指的原始資料與擷取證據',
  price_registry_pin_mismatch: '來源清單版本或雜湊不一致',
  price_body_hash_mismatch: '原始資料雜湊不一致',
  price_receipt_invalid: '擷取紀錄格式無效',
  price_receipt_mismatch: '擷取紀錄與來源、版本或原始資料不一致',
  price_receipt_http_invalid: '擷取紀錄未確認成功回應',
  price_attribution_mismatch: '缺少一致的來源與授權註記',
  price_conditions_mismatch: '擷取限制執行證據不一致',
  price_capture_time_mismatch: '擷取時間與原始資料紀錄不一致',
  price_raw_date_mismatch: '原始資料日期不一致',
  price_evidence_changed: '驗證期間來源檔案發生變更',
  price_purpose_not_admitted: '來源的研究使用條件尚待核對',
  price_identity_date_mismatch: '標的或行情日期與原件不一致',
  price_suspended: '這筆行情標示為停牌',
  price_invalid_ohlc: '開高低收數值或範圍無效',
  price_invalid_volume: '成交量缺失或不是有效非負整數',
  price_selected_row_invalid: '原件中的選中標的缺失或數值無效',
  price_selected_value_mismatch: '行情數值與選中原件不一致',
  price_turnover_state_mismatch: '成交額或可得狀態與原件不一致',
  price_data_date_mismatch: '行情資料日與選中原件不一致',
  price_duplicate_date: '重複日期的行情全部拒用',
  price_evidence_invalid: '來源證據無法完整驗證',
  price_no_rows_before_cutoff: '截止日期以前沒有行情資料',
  price_latest_before_cutoff: '最新可用行情早於研究截止日期',
  institutional_sources_not_admitted: '法人資料的來源與完整性尚待核對',
  multi_session_institutional_evidence_missing: '缺少可核對的多個交易日法人原件',
  trading_session_source_not_admitted: '缺少已核對的交易日基準',
  strategy_input_sources_not_admitted: '策略所需法人、成交額與族群資料尚待核對',
  strategy_time_evidence_not_verified: '策略輸入與結果的時間證據尚未驗收',
  industry_membership_not_verified: '既有族群關聯待重新核實',
  strategy_result_missing: '截止日期以前沒有這個版本的策略結果',
  strategy_result_before_cutoff: '既有策略結果早於本次截止日期',
  event_capture_consumer_not_verified: '官方事件原件與讀取結果尚待核對',
  event_source_time_not_verified: '事件來源與發布／事件時間尚未完整驗證',
  event_capture_not_enabled: '伺服器尚未明示啟用官方除權息預告取得操作',
  event_capture_configuration_invalid: '伺服器取得設定無效，尚未啟用',
  event_exchange_not_supported: '本區塊目前僅支援上市（TWSE）官方預告',
  event_invalid_symbol: '標的代號尚待核對',
  event_memory_capture_missing: '尚未取得本次官方除權息預告',
  event_shared_cutoff_missing: '尚無共同研究截止日期；取得的觀測日期不會自動補成截止日期',
  event_observation_after_cutoff: '本次觀測日晚於研究截止，無法判斷截止當時已知哪些預告',
  event_capture_in_progress: '同一程序正在取得官方預告，請稍後讀取',
  event_evidence_invalid: '官方預告原件、來源或版本無法完整核對',
  event_capture_failed: '本次官方預告取得失敗，尚無可採用的原件',
  event_capture_request_failed: '本次取得操作未成功，請確認伺服器連線後再操作',
  daily_exchange_not_supported: '本區塊目前僅支援上櫃（TPEx）原件',
  daily_shared_cutoff_missing: '尚無共同研究截止日期',
  daily_capture_not_configured: '尚未設定本地單日法人原件',
  daily_invalid_configuration: '本地原件設定尚待核對',
  daily_invalid_symbol: '標的代號尚待核對',
  daily_after_cutoff: '設定的原件資料日晚於研究截止日期，本次不採用',
  daily_evidence_invalid: '單日法人原件無法完整驗證',
  daily_configured_date_before_cutoff: '設定的原件資料日早於研究截止日期；尚未確認截至日前最新資料',
  selected_row_missing: '原件中沒有這個標的的唯一資料列',
  selected_row_duplicate: '原件中這個標的資料列重複',
  payload_date_mismatch: '原件資料日與設定日期不一致',
}

export function overviewReason(reason: string): string {
  if (reason.startsWith('selected_symbol_missing:')) return '本次官方預告中缺少這個標的；無法據此宣稱沒有事件'
  if (reason.startsWith('http_status:')) return '官方預告來源本次未成功回應，沒有自動重試'
  if (reason.startsWith('purpose_not_admitted:')) return '官方預告的來源使用條件未通過核對'
  if (reason === 'selected_event_duplicate') return '本次官方預告含重複事件，全部拒用'
  if (reason === 'selected_event_class_unknown') return '本次官方預告事件類型無法核對'
  if (reason.startsWith('receipt_mismatch:')) return '擷取紀錄與原件、來源或版本不一致'
  if (reason.startsWith('selected_')) return REASONS[reason] ?? '選中標的的來源欄位無法核對'
  if (reason === 'invalid_share_quantity' || reason === 'negative_gross_quantity') return '選中標的的法人股數或加總無法核對'
  if (reason.startsWith('body_')) return '原始資料檔案不可讀、不穩定或不符合檔案驗證條件'
  if (reason.startsWith('receipt_')) return '擷取紀錄檔案不可讀、不穩定或不符合檔案驗證條件'
  return REASONS[reason] ?? '來源證據尚待核對'
}

function number(value: number | null, digits = 2): string {
  return value != null && Number.isFinite(value) ? value.toLocaleString('zh-TW', { maximumFractionDigits: digits }) : '未提供'
}

function Reasons({ reasons }: { reasons: string[] }) {
  return reasons.length ? <ul className="overview-reasons">{reasons.map((reason) => <li key={reason}>{overviewReason(reason)}</li>)}</ul> : null
}

export function InstitutionalDaily({ data, windowsPresent = false }: { data?: InstitutionalDailyData; windowsPresent?: boolean }) {
  const row = data?.status === 'available' ? data.row : null
  const provenance = row ? data?.provenance : null
  const unitKnown = data?.unit === 'shares' && row?.unit === 'shares' && data.quantity_encoding === 'canonical_integer_string'
  const lots = (value: unknown, gross = false) => unitKnown ? formatCanonicalShareLots(value, 1, gross) ?? '待核對' : '單位待核實'
  const original = (value: unknown, gross = false) => unitKnown ? formatCanonicalShares(value, 1, gross) ?? '待核對' : '單位待核實'
  return <section className="panel overview-institutional-daily"><h3>單日法人原件</h3>
    {row && provenance ? <>
      <p>{row.company_name}（{row.symbol}） · 資料日 {formatResearchDate(row.date)} · 單位：{unitKnown ? '張' : '來源單位待核實'}</p>
      <p className="small-note">僅核對本次設定的單日原件與選中標的；不代表完整市場或截至日前最新資料。</p>
      <div className="table-wrap"><table><caption>法人買進、賣出與淨買賣超（{unitKnown ? '張' : '單位待核實'}）；正值為買超、負值為賣超。</caption><thead><tr><th>法人</th><th>買進</th><th>賣出</th><th>淨買賣超</th></tr></thead><tbody>
        {(['foreign', 'trust', 'dealer'] as const).map((key) => <tr key={key}><td>{row.investors[key].label}</td><td>{lots(row.investors[key].buy, true)}</td><td>{lots(row.investors[key].sell, true)}</td><td>{lots(row.investors[key].net)}</td></tr>)}
        <tr><th colSpan={3}>三類法人淨買賣超合計</th><td>{lots(row.total_net)}</td></tr>
      </tbody></table></div>
      <p className="small-note">來源 <a href={provenance.endpoint} target="_blank" rel="noreferrer">證券櫃檯買賣中心 · 上櫃股票三大法人買賣明細資訊</a>；擷取 {formatResearchDateTime(provenance.captured_at)}。本地原件與數值一致；歷史當時可得（PIT）未支援。</p>
      {data?.attribution && <p className="small-note">資料提供：{data.attribution.owner.data_provider} · {data.attribution.owner.attribution_year} · <a href={data.attribution.owner.license_url} target="_blank" rel="noreferrer">政府資料開放授權條款</a></p>}
      <details className="technical-details"><summary>查看法人原件日期、來源版本與雜湊</summary>
        <div className="table-wrap"><table><caption>來源稽核原值（{unitKnown ? '股' : '單位待核實'}）</caption><thead><tr><th>法人</th><th>買進</th><th>賣出</th><th>淨買賣超</th></tr></thead><tbody>
          {(['foreign', 'trust', 'dealer'] as const).map((key) => <tr key={key}><th>{row.investors[key].label}</th><td>{original(row.investors[key].buy, true)}</td><td>{original(row.investors[key].sell, true)}</td><td>{original(row.investors[key].net)}</td></tr>)}
          <tr><th colSpan={3}>三類法人淨買賣超合計</th><td>{original(row.total_net)}</td></tr>
        </tbody></table></div>
        <div className="overview-provenance">原始資料日 {row.source_date} · 原件列序 {row.row_ordinal} · {data?.version}</div>
        <div className="overview-provenance">來源版本 {provenance.source_version} · registry {provenance.registry_version} · manifest {provenance.manifest_digest}</div>
        <div className="overview-provenance">原件 SHA-256 {provenance.body_sha256} · 擷取紀錄 SHA-256 {provenance.receipt_sha256}</div>
        <div className="overview-provenance">擷取時間原值 {provenance.captured_at}</div>
      </details>
    </> : <div className="data-gap">尚無可核對的單日法人原件。</div>}
    <Reasons reasons={data?.reasons ?? ['daily_capture_not_configured']} />
    <p className="small-note">{windowsPresent ? '此單日區塊只核對設定原件；5／20 日窗口請見上方各窗的交易日與缺日狀態。' : '最近 5／20 交易日法人窗口仍不可用；缺少交易日基準與多日原件。'}缺值不作 0，融資不併入三大法人。</p>
  </section>
}

export function formatWindowShares(value: unknown, horizon: 1 | 5 | 20 = 1): string | null {
  return formatCanonicalShares(value, horizon)
}

export const SCOPE7_SYMBOL_NAMES: Record<string, string> = { '3105': '穩懋', '3293': '鈊象', '5274': '信驊', '5347': '世界', '6488': '環球晶', '6510': '精測', '8069': '元太' }
export const SCOPE7_SYMBOLS = Object.keys(SCOPE7_SYMBOL_NAMES)
export const CHIPS1006_POLICY_DIGEST = 'sha256:36c761a5f6e22afee86ad414769b88c06e97ae792141879a5660cf0856c180d5'
const chipsDates = ['09-01', '09-02', '09-03', '09-04', '09-07', '09-08', '09-09', '09-10', '09-11', '09-14', '09-15', '09-16', '09-17', '09-18', '09-21', '09-22', '09-23', '09-24', '09-29', '09-30', '10-01', '10-02', '10-05', '10-06'].map((day) => `2026-${day}`)
const chipsPolicy = 'm1-chips-cutoff-tpex-2026-10-06.1'
const chipsCalendar = 'tpex-2026-09-01_2026-10-06-weekdays-11503027221/chips-v1'
export const CHIPS1006_DAILY_FIELDS = ['資料日期', '代號', '名稱',
  '外資及陸資不含外資自營商買進股數', '外資及陸資不含外資自營商賣出股數', '外資及陸資不含外資自營商買賣超股數',
  '外資自營商買進股數', '外資自營商賣出股數', '外資自營商買賣超股數', '外資及陸資買進股數', '外資及陸資賣出股數', '外資及陸資買賣超股數',
  '投信買進股數', '投信賣出股數', '投信買賣超股數', '自營商自行買賣買進股數', '自營商自行買賣賣出股數', '自營商自行買賣買賣超股數',
  '自營商避險買進股數', '自營商避險賣出股數', '自營商避險買賣超股數', '自營商買進股數', '自營商賣出股數', '自營商買賣超股數', '三大法人買賣超股數合計']
const chipsIndexFields = ['資料日期', '開市', '最高價', '最低價', '收市', '漲跌']
const chipsOriginalReceiptFields: Array<keyof InstitutionalWindowReceipt> = ['schema_version', 'source_id', 'source_version', 'requested_date', 'url', 'method', 'body_sha256', 'body_bytes', 'request_started_at', 'captured_at', 'policy_version', 'policy_digest', 'profile', 'http_status', 'content_type', 'content_encoding', 'storage', 'published_time', 'first_available_time', 'revision_time', 'historical_pit', 'request_count']
const sameOriginalReceipt = (expanded: InstitutionalWindowReceipt, original?: InstitutionalWindowReceipt) => !!original && chipsOriginalReceiptFields.every((field) => expanded[field] === original[field])
const sameStrings = (value: unknown, expected: string[]) => Array.isArray(value) && value.length === expected.length && value.every((item, index) => item === expected[index])
const exactKeys = (value: unknown, expected: string[]) => value !== null && typeof value === 'object' && !Array.isArray(value)
  && sameStrings(Object.keys(value).sort(), [...expected].sort())

function chipsFinancialOriginals(values: Record<string, string> | undefined) {
  if (!exactKeys(values, CHIPS1006_DAILY_FIELDS) || !values) return null
  const groups: bigint[][] = []
  for (let offset = 3; offset < 24; offset += 3) {
    const group: bigint[] = []
    for (let index = 0; index < 3; index++) {
      const text = values[CHIPS1006_DAILY_FIELDS[offset + index]]
      if (typeof text !== 'string' || text.length > 20 || !/^(?:0|-?[1-9][0-9]*)$/.test(text)) return null
      const quantity = BigInt(text)
      if (quantity > 9223372036854775807n || quantity < -9223372036854775807n || (index < 2 && quantity < 0n)) return null
      group.push(quantity)
    }
    if (group[0] - group[1] !== group[2]) return null
    groups.push(group)
  }
  if (![0, 1, 2].every((index) => groups[2][index] === groups[0][index] + groups[1][index]
    && groups[6][index] === groups[4][index] + groups[5][index])) return null
  const total = values[CHIPS1006_DAILY_FIELDS[24]]
  if (typeof total !== 'string' || total.length > 20 || !/^(?:0|-?[1-9][0-9]*)$/.test(total)
    || BigInt(total) > 9223372036854775807n || BigInt(total) < -9223372036854775807n
    || BigInt(total) !== groups[0][2] + groups[3][2] + groups[6][2]) return null
  return { foreign: groups[0], trust: groups[3], dealer: groups[6], total }
}

export function validChips1006Identity(data: InstitutionalWindowsData, exchange?: string, symbol?: string, cutoff?: string, calendar = false, scope7 = false): boolean {
  const suffix = scope7 ? 'chips-1006-stock-scope-7-v1' : calendar ? 'chips-1006-calendar-v2' : 'chips-1006-v1'
  try {
    return data.schema_version === `institutional-windows-read/${suffix}` && data.version === `institutional-windows/${suffix}`
      && data.exchange === 'TPEx' && (scope7 ? SCOPE7_SYMBOLS : ['3105', '6488']).includes(data.symbol ?? '') && data.as_of === '2026-10-06'
      && (exchange === undefined || exchange === data.exchange) && (symbol === undefined || symbol === data.symbol)
      && (cutoff === undefined || cutoff === data.as_of) && data.unit === 'shares' && data.quantity_encoding === 'canonical_integer_string'
      && data.historical_pit === 'unsupported' && sameStrings(data.investors, ['foreign', 'trust', 'dealer'])
      && sameStrings(data.horizons?.map(String), ['5', '20']) && data.supported_scope?.exchange === 'TPEx'
      && sameStrings(data.supported_scope.symbols, scope7 ? SCOPE7_SYMBOLS : ['3105', '6488']) && sameStrings(data.supported_scope.supported_cutoffs, ['2026-10-06'])
      && data.supported_scope.calendar_from === '2026-09-01' && data.supported_scope.calendar_to === '2026-10-06'
      && sameStrings(data.supported_scope.financial_dates, chipsDates.slice(-20)) && data.supported_scope.selection === 'explicit_requested_as_of_only'
      && (!scope7 || exactKeys(data.supported_scope.identities, SCOPE7_SYMBOLS) && SCOPE7_SYMBOLS.every((code) => {
        const identity = data.supported_scope!.identities![code]
        return exactKeys(identity, ['as_of', 'currency', 'exchange', 'market', 'name', 'pit_membership', 'security_type'])
          && identity.as_of === '2026-10-06' && identity.currency === 'TWD' && identity.exchange === 'TPEx'
          && identity.market === 'TW' && identity.name === SCOPE7_SYMBOL_NAMES[code] && identity.pit_membership === false && identity.security_type === 'stock'
      }))
  } catch { return false }
}

export function validChips1006Read(data: InstitutionalWindowsData, exchange?: string, symbol?: string, cutoff?: string, calendar = false, scope7 = false): boolean {
  const suffix = scope7 ? 'chips-1006-stock-scope-7-v1' : calendar ? 'chips-1006-calendar-v2' : 'chips-1006-v1'
  const selectedPolicy = scope7 ? 'm1-chips-cutoff-stock-scope-7-tpex-2026-10-06.1' : calendar ? 'm1-chips-cutoff-calendar-tpex-2026-10-06.2' : chipsPolicy
  const selectedDigest = scope7 ? 'sha256:b2f939100bd76de12bd974abb80f267596bf5a55f839271a5f4cc61409f9c220' : calendar ? 'sha256:1acf97b7dd0f13b9b49ed3293497e52ca52ea077256b8d99d9bc21ed5761d403' : CHIPS1006_POLICY_DIGEST
  const selectedCalendar = scope7 ? 'tpex-2026-09-01_2026-10-06-full-month-observed-2026-10-07-11503027221/chips-stock-scope-7-v1' : calendar ? 'tpex-2026-09-01_2026-10-06-full-month-observed-2026-10-07-11503027221/chips-calendar-v2' : chipsCalendar
  const selectedProfile = scope7 ? 'free_public_local_full_month_cutoff_stock_scope_7' : calendar ? 'free_public_local_full_month_cutoff' : 'free_public_local'
  const fullMonth = calendar || scope7
  const originalDates = fullMonth ? [...chipsDates, '2026-10-07'] : chipsDates
  try {
    if (!validChips1006Identity(data, exchange, symbol, cutoff, calendar, scope7) || data.policy?.version !== selectedPolicy || data.policy.digest !== selectedDigest
      || data.policy.profile !== selectedProfile || data.calculation_version !== 'independent-net-sum/expected-session-inclusive-v1'
      || data.provenance?.worker_version !== `tpex-institutional-window/${suffix}`
      || data.provenance.worker_schema_version !== `tpex-institutional-window-summary/${suffix}`
      || data.provenance.verification !== 'local_evidence_consistent' || data.calendar?.schema_version !== `tpex-observed-calendar/${suffix}`
      || data.calendar.version !== selectedCalendar || data.calendar.status !== 'available'
      || data.calendar.from !== '2026-09-01' || data.calendar.to !== '2026-10-06'
      || !sameStrings(data.calendar.expected_dates, chipsDates) || !sameStrings(data.calendar.valid_dates, chipsDates)
      || !sameStrings(data.calendar.missing_dates, []) || data.published_time !== 'unknown'
      || data.first_available_time !== 'unknown' || data.revision_time !== 'unknown') return false
    const receiptValid = (receipt: NonNullable<InstitutionalWindowsData['provenance']>['captured_versions'][number], daily: boolean, requested: string, checked: boolean) => {
      const base = daily ? 'https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data&d=' : 'https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data&date='
      const parameter = daily ? `115/${requested.slice(5).replace('-', '/')}` : requested.replaceAll('-', '/')
      const type = receipt.content_type?.toLowerCase().split(';').map((part) => part.trim()) ?? []
      return receipt.schema_version === `tpex-institutional-memory-capture/${suffix}`
        && receipt.source_id === (daily ? 'tpex_government_institutional_csv' : 'tpex_government_index_csv')
        && receipt.source_version === (daily ? `dataset-11856-dated-csv-observed-2026-10-07/${scope7 ? 'chips-stock-scope-7-v1' : calendar ? 'chips-calendar-v2' : 'chips-v1'}` : `dataset-11391-month-csv-observed-2026-10-07/${scope7 ? 'chips-stock-scope-7-v1' : calendar ? 'chips-calendar-v2' : 'chips-v1'}`)
        && receipt.requested_date === requested && receipt.url === base + encodeURIComponent(parameter) && receipt.method === 'GET'
        && /^[0-9a-f]{64}$/.test(receipt.body_sha256) && (!checked || /^sha256:[0-9a-f]{64}$/.test(receipt.receipt_sha256 ?? ''))
        && Number.isInteger(receipt.body_bytes) && receipt.body_bytes > 0 && receipt.body_bytes <= (daily ? 2097152 : 1048576)
        && receipt.policy_version === selectedPolicy && receipt.policy_digest === selectedDigest && receipt.profile === selectedProfile
        && receipt.historical_pit === 'unsupported' && Number.isInteger(receipt.http_status) && receipt.http_status! >= 200 && receipt.http_status! < 300
        && receipt.storage === 'process_memory' && receipt.request_count === 1 && receipt.published_time === 'unknown'
        && receipt.first_available_time === 'unknown' && receipt.revision_time === 'unknown'
        && ['application/csv', 'text/csv'].includes(type[0]) && type.slice(1).every((part) => ['charset=utf-8', 'charset="utf-8"'].includes(part))
        && ['', 'identity'].includes(receipt.content_encoding?.toLowerCase().trim() ?? 'invalid')
        && [receipt.request_started_at, receipt.captured_at].every((instant) => /(?:Z|\+00:00)$/.test(instant) && Number.isFinite(Date.parse(instant)))
        && Date.parse(receipt.request_started_at) <= Date.parse(receipt.captured_at)
    }
    const months = ['2026-09-01', '2026-10-01']
    if (!Array.isArray(data.calendar.evidence) || data.calendar.evidence.length !== 2
      || !data.calendar.evidence.every((receipt, index) => receiptValid(receipt, false, months[index], true)
        && receipt.validation_scope === (fullMonth ? 'all_returned_month_rows_including_valid_post_cutoff_rows' : 'all_returned_month_rows') && receipt.candidate_count === (fullMonth ? [20, 5] : [20, 4])[index]
        && receipt.adopted_count === [20, 4][index] && receipt.pre_calendar_row_count === 0 && (!fullMonth || receipt.post_cutoff_row_count === [0, 1][index]))) return false
    if (fullMonth && (data.status !== 'available' || data.calendar.observation_date !== '2026-10-07'
      || !sameStrings(data.calendar.original_expected_dates, originalDates)
      || !sameStrings(data.calendar.original_valid_dates, originalDates)
      || !sameStrings(data.calendar.post_cutoff_dates, ['2026-10-07'])
      || !Array.isArray(data.calendar.rows) || data.calendar.rows.length !== 24
      || JSON.stringify(data.calendar.rows) !== JSON.stringify(data.calendar.original_rows?.slice(0, 24)))) return false
    const calendarRows = fullMonth ? data.calendar.original_rows : data.calendar.rows
    if (!Array.isArray(calendarRows) || calendarRows.length !== originalDates.length || !calendarRows.every((row, index) => {
      const month = row.date?.slice(0, 7) === '2026-09' ? 0 : 1
      if (row.date !== originalDates[index] || !exactKeys(row.source_values, chipsIndexFields)
        || !Object.values(row.source_values).every((value) => typeof value === 'string' && value === value.trim() && value.length > 0 && value.length <= 64)
        || row.source_values['資料日期'] !== row.date.replaceAll('-', '') || row.body_sha256 !== data.calendar!.evidence![month].body_sha256
        || !Number.isInteger(row.row_ordinal) || row.row_ordinal <= 0 || row.row_ordinal > (fullMonth ? [20, 5] : [20, 4])[month]) return false
      if (!chipsIndexFields.slice(1).every((key) => /^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/.test(row.source_values[key]))) return false
      const [open, high, low, close, change] = chipsIndexFields.slice(1).map((key) => Number(row.source_values[key]))
      return [open, high, low, close, change].every(Number.isFinite) && [open, high, low, close].every((value) => value > 0)
        && low <= Math.min(open, close) && Math.max(open, close) <= high
    }) || new Set(calendarRows.map((row) => `${row.body_sha256}:${row.row_ordinal}`)).size !== originalDates.length) return false
    const captured = data.provenance.captured_versions
    const requested = [...months, ...chipsDates.slice(-20)]
    if (!Array.isArray(captured) || captured.length < 2 || captured.length > 22 || fullMonth && captured.length !== 22
      || new Set(captured.map((receipt) => `${receipt.source_id}:${receipt.requested_date}`)).size !== captured.length
      || !captured.every((receipt, index) => index < 2 ? receiptValid(receipt, false, months[index], false)
        : chipsDates.slice(-20).includes(receipt.requested_date) && receiptValid(receipt, true, receipt.requested_date, false)
          && (index === 2 || receipt.requested_date > captured[index - 1].requested_date))) return false
    if (!data.calendar.evidence.every((receipt, index) => sameOriginalReceipt(receipt, captured[index]))) return false
    const adoptedRows = new Map<string, string>()
    for (const horizon of [5, 20] as const) {
      const window = data.windows?.[String(horizon)], expected = chipsDates.slice(-horizon)
      if (!window || window.horizon !== horizon || !sameStrings(window.required_dates, expected)) return false
      const known = expected.filter((day) => window.valid_dates?.includes(day)), missing = expected.filter((day) => !known.includes(day))
      if (!sameStrings(window.valid_dates, known) || !sameStrings(window.missing_dates, missing)
        || !Array.isArray(window.invalid_dates) || new Set(window.invalid_dates.map((item) => item.date)).size !== window.invalid_dates.length
        || !window.invalid_dates.every((item) => missing.includes(item.date) && typeof item.reason === 'string' && item.reason.length > 0)
        || window.from !== expected[0] || window.to !== '2026-10-06'
        || !Array.isArray(window.daily_evidence) || window.daily_evidence.length !== known.length) return false
      if (window.status === 'available') {
        if (missing.length || window.invalid_dates.length || !window.values
          || !(['foreign', 'trust', 'dealer'] as const).every((key) => formatWindowShares(window.values![key], horizon) !== null)) return false
      } else if (window.status !== 'unavailable' || window.values !== null || !missing.length) return false
      const sums = { foreign: 0n, trust: 0n, dealer: 0n }
      if (!window.daily_evidence.every(({ row, provenance }, index) => {
        const original = chipsFinancialOriginals(row.source_values)
        if (!original || !exactKeys(row.investors, ['foreign', 'trust', 'dealer']) || row.total_net !== original.total) return false
        for (const [key, offset, label] of [['foreign', 3, '外資及陸資（不含外資自營商）'], ['trust', 12, '投信'], ['dealer', 21, '自營商']] as const) {
          const investor = row.investors[key]
          if (investor.label !== label || investor.buy !== String(original[key][0]) || investor.sell !== String(original[key][1]) || investor.net !== String(original[key][2])
            || !exactKeys(investor.source_fields, ['buy', 'sell', 'net']) || investor.source_fields.buy !== CHIPS1006_DAILY_FIELDS[offset]
            || investor.source_fields.sell !== CHIPS1006_DAILY_FIELDS[offset + 1] || investor.source_fields.net !== CHIPS1006_DAILY_FIELDS[offset + 2]) return false
          sums[key] += original[key][2]
        }
        const adopted = JSON.stringify([row.row_ordinal, ...CHIPS1006_DAILY_FIELDS.map((field) => row.source_values![field]), provenance.receipt_sha256, provenance.body_sha256])
        if (adoptedRows.has(row.date) && adoptedRows.get(row.date) !== adopted) return false
        adoptedRows.set(row.date, adopted)
        return row.symbol === data.symbol && row.date === known[index]
        && row.source_date === '115' + known[index].slice(5).replace('-', '') && Number.isInteger(row.row_ordinal) && row.row_ordinal > 0
        && typeof row.company_name === 'string' && row.company_name.trim().length > 0 && receiptValid(provenance, true, known[index], true)
        && requested.includes(known[index]) && sameOriginalReceipt(provenance, captured.find((item) => item.source_id === 'tpex_government_institutional_csv' && item.requested_date === known[index]))
        && row.source_values && Object.keys(row.source_values).length === 25 && Object.values(row.source_values).every((value) => typeof value === 'string')
        && row.source_values['資料日期'] === row.source_date && row.source_values['代號'] === data.symbol && row.source_values['名稱'] === row.company_name
         && (!scope7 || row.company_name.trim() === SCOPE7_SYMBOL_NAMES[data.symbol!]
           && provenance.selected_count === 7
           && provenance.validation_scope === 'all_row_structure_dates_unique_codes_names; selected_seven_exact_pinned_names_all_22_financial_fields')
      })) return false
      if (window.status === 'available' && !(['foreign', 'trust', 'dealer'] as const).every((key) => window.values![key] === String(sums[key]) && (!scope7 || sums[key] >= -9223372036854775808n && sums[key] <= 9223372036854775807n))) return false
    }
    return true
  } catch { return false }
}

function knownWindowLots(data: InstitutionalWindowsData, horizon: 5 | 20, calendar = false, scope7 = false): string[] | null {
  if ((data.as_of === '2026-10-06' || data.version?.includes('chips-1006')) && !validChips1006Read(data, undefined, undefined, undefined, calendar, scope7)) return null
  const window = data.windows?.[String(horizon)]
  if (!window || window.horizon !== horizon || !data.horizons.includes(horizon)
    || data.unit !== 'shares' || data.quantity_encoding !== 'canonical_integer_string'
    || typeof data.as_of !== 'string' || data.supported_scope?.supported_cutoffs.includes(data.as_of) !== true
    || data.calendar?.status !== 'available' || window.status !== 'available'
    || window.required_dates.length !== horizon || window.valid_dates.length !== horizon
    || new Set(window.required_dates).size !== horizon || window.missing_dates.length !== 0 || window.invalid_dates.length !== 0
    || window.from !== window.required_dates[0] || window.to !== data.as_of || window.required_dates[horizon - 1] !== data.as_of
    || !window.required_dates.every((day, index) => day === window.valid_dates[index] && day <= data.as_of! && (index === 0 || day > window.required_dates[index - 1]))) return null
  const values = (['foreign', 'trust', 'dealer'] as const).map((key) => formatCanonicalShareLots(window.values?.[key], horizon))
  return values.every((value) => value !== null) ? values as string[] : null
}

export function InstitutionalWindows({ data, onCapture, busy = false, requestFailure, expectedExchange, expectedSymbol, expectedCutoff, calendar = false, scope7 = false }: {
  data: InstitutionalWindowsData; onCapture?: () => void; busy?: boolean; requestFailure?: string
  expectedExchange?: string; expectedSymbol?: string; expectedCutoff?: string; calendar?: boolean; scope7?: boolean
}) {
  const claimsNew = data.as_of === '2026-10-06' || data.version?.includes('chips-1006') || data.schema_version?.includes('chips-1006')
  const hasNewEvidence = data.calendar?.status === 'available' || Object.values(data.windows ?? {}).some((window) => window?.values != null || (window?.daily_evidence?.length ?? 0) > 0)
  if (claimsNew && (!validChips1006Identity(data, expectedExchange, expectedSymbol, expectedCutoff, calendar, scope7)
    || (hasNewEvidence && !validChips1006Read(data, expectedExchange, expectedSymbol, expectedCutoff, calendar, scope7)))) {
    return <section className="panel overview-institutional-windows"><h3>外資／投信／自營商</h3>
      {scope7 && onCapture && data.capture_state?.attempted && <button type="button" className="secondary-button" disabled={busy} onClick={onCapture}>讀取本次法人窗口</button>}
      <div className="data-gap">資料不足：法人窗口來源、版本或截止未能通過核對。</div></section>
  }
  if (claimsNew && requestFailure) return <section className="panel overview-institutional-windows"><h3>外資／投信／自營商</h3>
    {(data.capture_state?.can_capture || scope7 && data.capture_state?.attempted) && onCapture && <button type="button" className="secondary-button" disabled={busy || data.capture_state?.busy} onClick={onCapture}>{busy ? '正在載入法人窗口…' : '讀取本次法人窗口'}</button>}
    <div className="data-gap" role="alert">資料不足：本次法人窗口讀取未能通過核對。{overviewReason(requestFailure)}</div></section>
  const state = data.capture_state
  const unitKnown = data.unit === 'shares' && data.quantity_encoding === 'canonical_integer_string'
  const cutoffSupported = typeof data.as_of === 'string' && data.supported_scope?.supported_cutoffs?.includes(data.as_of) === true
  const sourceWindow = data.windows?.['20'] ?? data.windows?.['5']
  const evidence = cutoffSupported ? (sourceWindow?.daily_evidence ?? []).filter(({ row }) =>
    row.date <= data.as_of! && sourceWindow?.required_dates.includes(row.date)) : []
  return <section className="panel overview-institutional-windows"><h3>外資／投信／自營商</h3>
    {!data.version ? <><div className="badge">資料不足</div><p>最近 5／20 交易日淨買賣超與趨勢尚不可用。</p></> : <>
      <p className="small-note">各法人淨買賣超，單位：{unitKnown ? '張' : '來源單位待核實'}；正值為買超，負值為賣超。截止包含當日，缺日不補零或改取更早日期。</p>
      {cutoffSupported && (state?.can_capture || scope7 && state?.attempted) && onCapture && <button type="button" className="secondary-button" disabled={busy || state?.busy} onClick={onCapture}>{busy || state?.busy ? '正在載入法人窗口…' : state?.attempted ? '讀取本次法人窗口' : '載入5／20日法人窗口'}</button>}
      {requestFailure && <div className="data-gap" role="alert">{overviewReason(requestFailure)}</div>}
      <div className="table-wrap"><table><caption>最近 5／20 交易日法人淨買賣超（{unitKnown ? '張' : '單位待核實'}）</caption><thead><tr><th>窗口／日期</th><th>外資（不含外資自營商）</th><th>投信</th><th>自營商</th><th>交易日完整性</th></tr></thead><tbody>{([5, 20] as const).map((horizon) => {
        const window = data.windows?.[String(horizon)]
        const formatted = knownWindowLots(data, horizon, calendar, scope7)
        return <tr key={horizon}><th>{horizon} 交易日{window?.from && <div className="small-note">{formatResearchDate(window.from)} — {formatResearchDate(window.to ?? null)}</div>}</th>{formatted ? formatted.map((value, index) => <td className="numeric-cell" key={index}>{value}</td>) : <td colSpan={3}><div className="data-gap">資料不足{window?.values && '：數值或窗口條件待核對'}</div></td>}<td>{window ? `所需 ${window.required_dates.length}／已驗 ${window.valid_dates.length}／缺 ${window.missing_dates.length} 日` : '尚未核對'}</td></tr>
      })}</tbody></table></div>
      {Object.values(data.windows ?? {}).map((window) => window.missing_dates.length > 0 && <details className="technical-details" key={window.horizon}><summary>{window.horizon} 日窗口缺日與未採用原因</summary><div>缺日：{window.missing_dates.join('、')}</div>{window.invalid_dates.map((item) => <div key={item.date}>{item.date}：{overviewReason(item.reason)}</div>)}<Reasons reasons={window.reasons} /></details>)}
      <p className="small-note">來源：證券櫃檯買賣中心（TPEx） · <a href="https://data.gov.tw/dataset/11856" target="_blank" rel="noreferrer">上櫃股票三大法人買賣明細資訊</a> · <a href="https://data.gov.tw/dataset/11391" target="_blank" rel="noreferrer">櫃買指數歷史資料</a>；授權 <a href="https://data.gov.tw/license" target="_blank" rel="noreferrer">政府資料開放授權條款第 1 版（OGL 1.0）</a>。</p>
      <p className="small-note">本次取得版本的資料日期統計，只留在伺服器記憶體；讀取沿用同一批原件。取得批次涵蓋 {data.supported_scope?.supported_cutoffs.length ?? 0} 個支持截止，各窗口只採用截至所選日期的原件。發布、首次可得與修訂時間均未知，不代表歷史當時可得（PIT 未支援），不推論研究條件成立。</p>
      <details className="technical-details"><summary>查看法人窗口的每日數值、交易日與來源版本</summary>
        <div className="table-wrap"><table><caption>窗口來源稽核原值（{unitKnown ? '股' : '單位待核實'}）</caption><thead><tr><th>窗口</th><th>外資</th><th>投信</th><th>自營商</th></tr></thead><tbody>{([5, 20] as const).map((horizon) => <tr key={horizon}><th>{horizon} 交易日</th>{(['foreign', 'trust', 'dealer'] as const).map((key) => <td key={key}>{knownWindowLots(data, horizon, calendar, scope7) ? formatWindowShares(data.windows?.[String(horizon)]?.values?.[key], horizon) : '待核對'}</td>)}</tr>)}</tbody></table></div>
        <div>本次截止 {formatResearchDate(data.as_of ?? null)}；支持範圍：上櫃 {scope7 ? SCOPE7_SYMBOLS.join('、') : '3105、6488'}，截止 {data.supported_scope?.supported_cutoffs?.map((day) => formatResearchDate(day)).join('、') ?? '未核對'}。</div>
        <div>總覽法人版本 {data.version} · 計算版本 {data.calculation_version ?? '未核對'}</div>
        <div className="overview-provenance">來源政策版本 {data.policy?.version ?? '未核對'} · 雜湊 {data.policy?.digest ?? '未核對'}</div>
        <div>交易日基準 {data.calendar?.version ?? '未核對'}；所需 {data.calendar?.expected_dates?.length ?? 0}／已驗 {data.calendar?.valid_dates?.length ?? 0} 日。只支持 {formatResearchDate(data.supported_scope?.calendar_from ?? null)} — {formatResearchDate(data.supported_scope?.calendar_to ?? null)}。</div>
        {data.calendar?.basis && <p>週一至週五：<a href={data.calendar.basis.weekday_rule} target="_blank" rel="noreferrer">官方交易時間規則</a>；明示休市日 {data.calendar.basis.closed_dates.join('、')}：<a href={data.calendar.basis.closed_notice} target="_blank" rel="noreferrer">官方休市公告</a>。其餘預期日期均以唯一指數原件核對，不以缺列推定休市。</p>}
        {claimsNew && data.calendar?.status === 'available' && <><p>完整已觀測交易日曆：2026-09-01 — 2026-10-06。9月20列，10月截至10/6為4列；全部24列已驗並採用。{(calendar || scope7) && '月原件另含合法10/07列，已驗並保留但不採入10/06窗口。'}</p><div className="table-wrap"><table><caption>{calendar || scope7 ? '25個已驗月原件交易日（24日採用）的完整6欄指數原字串' : '24個已觀測交易日的完整6欄指數原字串'}</caption><thead><tr><th>交易日／原件列序</th>{chipsIndexFields.map((field) => <th key={field}>{field}</th>)}<th>原件SHA-256</th></tr></thead><tbody>{(calendar || scope7 ? data.calendar.original_rows : data.calendar.rows)?.map((row) => <tr key={row.date}><th>{row.date}／{row.row_ordinal}</th>{chipsIndexFields.map((field) => <td key={field}>{row.source_values[field]}</td>)}<td>{row.body_sha256}</td></tr>)}</tbody></table></div></>}
        {(data.calendar?.evidence ?? []).map((receipt) => <div className="overview-provenance" key={receipt.requested_date}>日曆原件 {receipt.requested_date} · <a href={receipt.url} target="_blank" rel="noreferrer">來源 CSV</a> · {receipt.source_version} · SHA-256 {receipt.body_sha256} · UTC 取得 {receipt.captured_at}{['all_returned_month_rows', 'all_returned_month_rows_including_valid_post_cutoff_rows'].includes(receipt.validation_scope ?? '') && <span> · {claimsNew ? '完整返回原件' : '完整月原件'}已驗 {receipt.candidate_count} 列／本範圍採用 {receipt.adopted_count} 列{claimsNew ? '；只證此已觀測有界交易日曆。' : <>／界線前已驗但未採用 {receipt.pre_calendar_row_count} 列；不推論完整月交易日曆。</>}</span>}</div>)}
        {evidence.map(({ row, provenance }) => <details key={row.date}><summary>{row.date} · {row.company_name}（{row.symbol}） · 原件列序 {row.row_ordinal}</summary><div className="table-wrap"><table><caption>每日來源稽核原值（{unitKnown ? '股' : '單位待核實'}）</caption><thead><tr><th>法人</th><th>買進</th><th>賣出</th><th>淨買賣超</th></tr></thead><tbody>{(['foreign', 'trust', 'dealer'] as const).map((key) => <tr key={key}><th>{row.investors[key].label}</th><td>{unitKnown ? formatCanonicalShares(row.investors[key].buy, 1, true) ?? '待核對' : '單位待核實'}</td><td>{unitKnown ? formatCanonicalShares(row.investors[key].sell, 1, true) ?? '待核對' : '單位待核實'}</td><td>{unitKnown ? formatWindowShares(row.investors[key].net) ?? '待核對' : '單位待核實'}</td></tr>)}</tbody></table></div>{claimsNew && row.source_values && <div className="table-wrap"><table><caption>此日完整25欄官方原字串</caption><thead><tr><th>來源欄位</th><th>原字串</th></tr></thead><tbody>{Object.entries(row.source_values).map(([field, value]) => <tr key={field}><th>{field}</th><td>{value}</td></tr>)}</tbody></table></div>}<div className="overview-provenance">原始資料日 {row.source_date} · <a href={provenance.url} target="_blank" rel="noreferrer">來源 CSV</a> · {provenance.source_version} · SHA-256 {provenance.body_sha256} · 擷取紀錄 SHA-256 {provenance.receipt_sha256} · UTC 取得 {provenance.captured_at}</div></details>)}
        <p>官方統計按當日原始成交，非錯帳／更正帳號調整後資料；下載版本是否修訂未知。本次原件 SHA-256 識別取得版本。</p>
      </details>
    </>}
    <Reasons reasons={data.reasons} />
  </section>
}

export function OfficialEvents({ data, onCapture, busy = false, requestFailure }: {
  data: OfficialEventsData; onCapture?: () => void; busy?: boolean; requestFailure?: string
}) {
  const provenance = data.status === 'available' ? data.provenance : null
  return <section className="panel overview-official-events"><h3>官方除權息預告</h3>
    <p className="small-note">明示取得後，原件只保留在本次伺服器程序記憶體。已有原件時讀取同一次觀測；重新取得需重新啟動伺服器，未確認最新資料。</p>
    {data.can_capture && onCapture && <button type="button" className="secondary-button" disabled={busy} onClick={onCapture}>{busy ? '正在取得官方預告…' : data.cache_present ? '讀取本次官方除權息預告' : '取得本次官方除權息預告'}</button>}
    {requestFailure && <div className="data-gap" role="alert">{overviewReason(requestFailure)}</div>}
    <Reasons reasons={data.reasons} />
    {data.observed_date && <p>本次觀測日（臺北）：{formatResearchDate(data.observed_date)}{data.status !== 'available' && '；請將研究截止日期設為此日或較晚日期，再核對本次觀測。'}</p>}
    {provenance && <>
      <div className="table-wrap"><table><caption>本次選中標的的官方除權息預告；事件日為生效日，保留未來日期。</caption><thead><tr><th>標的</th><th>預告類型</th><th>生效日期</th></tr></thead><tbody>{data.rows.map((row) => <tr key={`${row.symbol}-${row.event_date}-${row.kind}`}><td>{row.company_name}（{row.symbol}）</td><td>{row.label}</td><td>{formatResearchDate(row.event_date)}</td></tr>)}</tbody></table></div>
      <p className="small-note">來源：臺灣證券交易所 · 上市除權除息預告表 · <a href={provenance.endpoint} target="_blank" rel="noreferrer">查看官方公告資料集</a>；連結為整份清單（資料 feed），未提供單則原文。</p>
      {data.attribution && <p className="small-note">資料提供：{data.attribution.owner.name} · 授權 {data.attribution.terms.value} · <a href="https://data.gov.tw/license" target="_blank" rel="noreferrer">政府資料開放授權條款</a></p>}
      <details className="technical-details"><summary>查看官方預告觀測、來源版本與雜湊</summary>
        <div className="overview-provenance">擷取觀測時間 {formatResearchDateTime(provenance.captured_at)} · 原值 {provenance.captured_at} · {data.version}</div>
        {data.rows.map((row) => <div className="overview-provenance" key={row.row_ordinal}>{row.symbol} · 原始民國生效日期 {row.source_date} · 原始分類 {row.source_classification} · 原件列序 {row.row_ordinal}</div>)}
        <div className="overview-provenance">來源版本 {provenance.source_version} · registry {provenance.registry_version} · manifest {provenance.manifest_digest}</div>
        <div className="overview-provenance">原件 SHA-256 {provenance.body_sha256} · 擷取紀錄 SHA-256 {provenance.receipt_sha256}</div>
      </details>
    </>}
    <p className="small-note">發布、首次可得與修訂時間均未知；觀測時間不代表發布時間，也不證歷史當時已知。僅核對名稱、代號、生效日期與除權息類型，未驗金融數值，不推論價格影響。</p>
  </section>
}

function PriceMemory({ data, instrument, cutoff, explicitCutoff, onCapture, busy, failure }: {
  data: StockOverviewData['price_memory']; instrument?: Instrument; cutoff: string | null; explicitCutoff?: string
  onCapture?: () => void; busy?: boolean; failure?: string
}) {
  if (!data || !instrument || instrument.exchange !== 'TPEx' || !Object.prototype.hasOwnProperty.call(PRICE_SYMBOL_NAMES, instrument.symbol)) return null
  const known = (!explicitCutoff || explicitCutoff === cutoff) && validStockPriceMemoryRead(data, instrument, explicitCutoff || cutoff)
  const ready = priceMemoryInstrumentSupported(instrument) && priceSourcePins(explicitCutoff ?? null) !== null && memoryPriceCaptureReady(data, instrument.exchange, instrument.symbol, cutoff)
  const bar = known ? data.latest : null
  const scope = known || ready ? data.supported_scope : null
  return <section className="panel overview-price-memory" aria-labelledby="price-memory-title">
    <h3 id="price-memory-title">櫃買官方單日行情</h3>
    <p className="small-note">{scope ? <>本次政策支持的上櫃普通股：{scope.symbols.join('、')}，來源日 {scope.cutoff}。</> : <>支持範圍待核實。</>}請先明示套用截止日期，再載入行情。每次服務只取得一份指定日期原件，未提供歷史窗口。</p>
    <button type="button" className="secondary-button" onClick={onCapture} disabled={!ready || busy || !onCapture}>{busy ? '載入官方行情中…' : `載入 ${explicitCutoff ?? '指定日期'} 官方行情`}</button>
    {known ? <>
      <div className="stock-quote-grid"><div><span>收盤（元／股）</span><strong>{number(bar!.close)}</strong></div><div><span>成交量（張）</span><strong>{formatTableVolume(bar!.volume, bar!.source, bar!.volume_exact)}</strong></div><div><span>成交額（新臺幣元）</span><strong>{bar!.turnover_exact === null ? '未提供' : formatCanonicalShares(bar!.turnover_exact, 1, true)}</strong></div></div>
      <div className="overview-ohlc"><span>開 {number(bar!.open)}</span><span>高 {number(bar!.high)}</span><span>低 {number(bar!.low)}</span><span>收 {number(bar!.close)}</span></div>
      <p className="small-note">資料日 {formatResearchDate(bar!.date)} · <a href={bar!.provenance.endpoint} target="_blank" rel="noreferrer">櫃買中心 · 上櫃股票行情（11370）</a>；本次暫存，重啟後需重新載入。擷取時間不是發布時間，歷史當時可得未支援。</p>
      <p className="small-note">{data.attribution!.owners.join('、')} · {data.attribution!.year} · {data.attribution!.release_version} · <a href={data.attribution!.license_url} target="_blank" rel="noreferrer">政府資料開放授權條款 OGL 1.0</a>。</p>
      <details className="technical-details"><summary>查看官方價格原列、來源版本與 SHA</summary>
        <div className="overview-provenance">單一原件：全 {data.provenance!.row_count} 列已核結構；金融數值僅核 {data.provenance!.selected_symbols.join('、')}。CSV 資料列序 {bar!.row_ordinal}；記憶體 ID {data.provenance!.memory_capture_id}。</div>
        <div className="table-wrap"><table><caption>官方 CSV 原字串：價格為元／股，成交股數為股，成交金額為新臺幣元；空白成交額表示未提供。</caption><thead><tr><th>欄位</th><th>來源原值</th></tr></thead><tbody>{PRICE_HEADERS.map((field) => <tr key={field}><th>{field}</th><td>{bar!.source_fields[field]}</td></tr>)}</tbody></table></div>
        <div className="overview-provenance">原件 SHA-256 {data.provenance!.body_sha256}</div><div className="overview-provenance">擷取紀錄 SHA-256 {data.provenance!.receipt_sha256}</div>
        <div className="overview-provenance">政策 {data.provenance!.policy_version} · {data.provenance!.policy_digest}</div>
        <div>請求開始 UTC {data.provenance!.request_started_at} · 完成 UTC {data.provenance!.captured_at}</div>
        <div>raw_payload_id null · ingestion_run_id null · bar id null；沒有建立 DB 記錄。發布／首次可得／修訂時間未知。</div>
      </details>
    </> : <div className="data-gap">{data.status === 'available' ? '記憶體行情契約待核實，未採用數值。' : '此截止尚無已核對的官方單日行情。'} 不以其他日期行情補值。</div>}
    {!known && <Reasons reasons={data.reasons} />}
    {failure && <><p role="status">官方行情載入未完成；請核對來源詳情。此批次不自動重試。</p><details className="technical-details"><summary>查看載入原因</summary>{overviewReason(failure)}（{failure}）</details></>}
    <p className="small-note">此資料只含一天，趨勢與研究條件仍待補；載入失敗後不自動重試。</p>
  </section>
}


export function PriceSaved({ data, instrument, cutoff, canSave, onSave, onRead, busy, failure, readonly = false }: {
  data?: StockPriceSavedData; instrument?: Instrument; cutoff?: string; canSave: boolean
  onSave?: () => void; onRead?: () => void; busy?: boolean; failure?: string; readonly?: boolean
}) {
  if (!instrument || !privatePriceSupported(instrument, cutoff ?? null)) return null
  const known = !failure && validStockPriceSavedRead(data, instrument, cutoff ?? null) && (!readonly || validSavedFocusStock(data, instrument, cutoff ?? ''))
  const bar = known ? data.latest : null
  return <section className="panel overview-price-memory" aria-labelledby="price-saved-title">
    <h3 id="price-saved-title">本機保存的單日行情</h3>
    <p className="small-note">{readonly ? '明示讀取本機保存的完整原件並核對，只採用目前同股同日的結果。' : '保存此日完整官方原件，服務重啟後可讀回核對。'}僅支持本次核定的七股及 2026-10-06。</p>
    <div className="filter-row">{!readonly && <button type="button" className="secondary-button" onClick={onSave} disabled={!canSave || busy || !onSave}>保存此日行情</button>}
      <button type="button" className="secondary-button" onClick={onRead} disabled={busy || !onRead}>{busy ? '核對保存資料中…' : '讀取已保存行情'}</button></div>
    {known ? <>
      <p role="status">{data.storage_state.action === 'reopened' ? '已從本機讀回並核對原件。' : data.storage_state.action === 'already_saved' ? '此份原件已保存並重新核對。' : '此日行情已保存並核對。'}</p>
      <div className="stock-quote-grid"><div><span>收盤（元／股）</span><strong>{number(bar!.close)}</strong></div><div><span>成交量（張）</span><strong>{formatTableVolume(bar!.volume, bar!.source, bar!.volume_exact)}</strong></div><div><span>成交額（新臺幣元）</span><strong>{bar!.turnover_exact === null ? '未提供' : formatCanonicalShares(bar!.turnover_exact, 1, true)}</strong></div></div>
      <p className="small-note">資料日 {formatResearchDate(bar!.date)} · <a href={data.provenance!.endpoint} target="_blank" rel="noreferrer">櫃買中心 · 上櫃股票行情（11370）</a>。{data.attribution!.owners.join('、')} · {data.attribution!.year} · {data.attribution!.release_version} · <a href={data.attribution!.license_url} target="_blank" rel="noreferrer">政府資料開放授權條款 OGL 1.0</a>。</p>
      <details className="technical-details"><summary>查看保存原件、官方原列與 SHA</summary>
        <div>來源全 {data.provenance!.row_count} 列核結構；金融數值僅核 {data.provenance!.selected_symbols.join('、')}。CSV 資料列序 {bar!.row_ordinal}；{data.provenance!.source_version}。</div>
        <div className="table-wrap"><table><caption>保存原件的官方原字串：價格為元／股，成交股數為股，成交金額為新臺幣元。</caption><thead><tr><th>欄位</th><th>來源原值</th></tr></thead><tbody>{PRICE_HEADERS.map((field) => <tr key={field}><th>{field}</th><td>{bar!.source_fields[field]}</td></tr>)}</tbody></table></div>
        <div className="overview-provenance">原件 SHA-256 {data.provenance!.body_sha256}</div>
        <div className="overview-provenance">原始擷取紀錄 SHA-256 {data.provenance!.receipt_sha256}</div>
        <div className="overview-provenance">保存紀錄 SHA-256 {data.storage_provenance!.storage_receipt_sha256}</div>
        <div className="overview-provenance">原始擷取政策 {data.provenance!.policy_version} · {data.provenance!.policy_digest}</div>
        <div className="overview-provenance">私有保存政策 {data.storage_provenance!.storage_policy_version} · {data.storage_provenance!.storage_policy_digest}</div>
        <div>原始擷取 UTC {data.provenance!.request_started_at} — {data.provenance!.captured_at}；保存 UTC {data.storage_provenance!.saved_at}。</div>
        <div>原始擷取紀錄 storage process_memory；目前保存 origin private_local。讀回網路請求 0；bar／raw_payload／ingestion_run id 均 null，沒有 DB 記錄。</div>
      </details>
    </> : <p className="small-note">尚未讀取已保存行情；請先套用截止日期，再明示保存或讀取。</p>}
    {failure && <><p role="status">保存資料未能通過核對，請查看原因。</p><details className="technical-details"><summary>查看保存／讀回原因</summary>{failure}</details></>}
    <p className="small-note">仍只含一天；擷取與保存時間不是發布時間，歷史當時可得、歷史窗口與研究條件待補。</p>
  </section>
}

export function StockOverview({ data, instrument, explicitCutoff, onCapturePrice, capturingPrice, priceRequestFailure, savedPrice, onSavePrice, onReadSavedPrice, privatePriceBusy, privatePriceFailure, privateSavedOnly = false, onNews, onCaptureEvents, capturingEvents, eventRequestFailure, onCaptureWindows, capturingWindows, windowRequestFailure, institutionalCalendar = false, institutionalScope7 = false }: {
  data: StockOverviewData; onNews: () => void; onCaptureEvents?: () => void; capturingEvents?: boolean; eventRequestFailure?: string
  onCaptureWindows?: () => void; capturingWindows?: boolean; windowRequestFailure?: string
  instrument?: Instrument; explicitCutoff?: string; onCapturePrice?: () => void; capturingPrice?: boolean; priceRequestFailure?: string
  savedPrice?: StockPriceSavedData; onSavePrice?: () => void; onReadSavedPrice?: () => void; privatePriceBusy?: boolean; privatePriceFailure?: string
  privateSavedOnly?: boolean; institutionalCalendar?: boolean; institutionalScope7?: boolean
}) {
  const price = data.price
  const latest = privateSavedOnly ? null : price.latest
  const memoryKnown = !privateSavedOnly && instrument && (!explicitCutoff || explicitCutoff === data.as_of) ? validStockPriceMemoryRead(data.price_memory, instrument, explicitCutoff || data.as_of) : false
  const savedKnown = !privatePriceFailure && instrument && explicitCutoff === data.as_of && validStockPriceSavedRead(savedPrice, instrument, explicitCutoff || null) && (!privateSavedOnly || validSavedFocusStock(savedPrice, instrument, explicitCutoff || ''))
  return <section className="stock-overview" aria-labelledby="stock-overview-title">
    <div className="section-head overview-head"><div><div className="eyebrow">研究總覽</div><h2 id="stock-overview-title">資料截止 {formatResearchDate(data.as_of)}</h2></div><span className="badge">{memoryKnown || savedKnown || latest ? '價格來源已核對／部分資料待補' : '研究資料待補'}</span></div>
    <p className="overview-cutoff-note">依資料日期截至的事後研究；不代表歷史當時可得。價格保留原始口徑，尚未提供完整還原鏈。</p>
    <div className="overview-grid">
      {!privateSavedOnly && <PriceMemory data={data.price_memory} instrument={instrument} cutoff={data.as_of} explicitCutoff={explicitCutoff} onCapture={onCapturePrice} busy={capturingPrice} failure={priceRequestFailure} />}
      <PriceSaved readonly={privateSavedOnly} data={savedKnown ? savedPrice : undefined} instrument={instrument} cutoff={explicitCutoff === data.as_of ? explicitCutoff : undefined} canSave={Boolean(memoryKnown && data.price_memory?.provenance?.policy_version === 'm2-stock-scope-tpex-11370-2026-10-06.5')} onSave={onSavePrice} onRead={onReadSavedPrice} busy={privatePriceBusy} failure={privatePriceFailure} />
      {!privateSavedOnly && !memoryKnown && !savedKnown && <section className="panel overview-price"><h3>既有價格與實際視窗</h3>
        <p className="small-note">本次最多 {price.window_limit} 筆，收到 {price.candidate_count} 筆、通過 {price.valid_count} 筆；不代表完整交易日窗口。</p>
        {latest ? <>
          <div className="overview-range">可用區間 {formatResearchDate(price.from)} — {formatResearchDate(price.to)}</div>
          <div className="stock-quote-grid"><div><span>最新可用收盤（報價幣別元）</span><strong>{number(latest.close)}</strong></div><div><span>成交量（張）</span><strong>{formatTableVolume(latest.volume, latest.source, latest.volume_exact) || '數值或單位待核實'}</strong></div><div><span>資料日</span><strong>{formatResearchDate(latest.date)}</strong></div></div>
          <div className="overview-ohlc"><span>開 {number(latest.open)}</span><span>高 {number(latest.high)}</span><span>低 {number(latest.low)}</span><span>收 {number(latest.close)}</span></div>
          <p className="small-note">成交額（來源計價單位）：{number(latest.turnover, 0)}{latest.turnover_status !== 'available' && `；原件${latest.turnover_reason === 'missing' ? '缺少成交額' : '成交額無效'}，未補零。`}</p>
          <p className="small-note">來源 <a href={latest.provenance.endpoint} target="_blank" rel="noreferrer">臺灣證券交易所 · STOCK_DAY_ALL</a>；擷取 {formatResearchDateTime(latest.provenance.captured_at)}。本地原件與數值一致，不代表來源真偽或歷史可得性已驗證。</p>
          <details className="technical-details"><summary>查看價格視窗與來源版本</summary>
            <div>總覽版本 {data.version} · 來源版本 {latest.provenance.source_version} · registry {latest.provenance.registry_version}</div>
            <div className="table-wrap"><table><caption>原始價格（各標的報價幣別的元）與成交量（股）；成交額為來源計價單位，空白表示不可用。</caption><thead><tr><th>日期</th><th>開</th><th>高</th><th>低</th><th>收</th><th>成交量</th><th>成交額</th></tr></thead><tbody>{price.bars.map((bar) => <tr key={bar.date}><td>{formatResearchDate(bar.date)}</td><td>{number(bar.open)}</td><td>{number(bar.high)}</td><td>{number(bar.low)}</td><td>{number(bar.close)}</td><td>{formatTableVolumeShares(bar.volume, bar.source, bar.volume_exact)}</td><td>{bar.turnover == null ? '' : number(bar.turnover, 0)}</td></tr>)}</tbody></table></div>
            {price.bars.map((bar) => <div className="overview-provenance" key={bar.date}>{bar.date} · raw {bar.provenance.raw_payload_id} · 原件 SHA-256 {bar.provenance.body_sha256} · 擷取紀錄 SHA-256 {bar.provenance.receipt_sha256} · 資料時間原值 {bar.data_as_of} · 收集時間原值 {bar.collected_at ?? '未提供'}</div>)}
          </details>
        </> : <div className="data-gap">尚無來源與數值已核對的價格。其餘研究入口可繼續使用。</div>}
        <Reasons reasons={price.reasons} />
        {price.rejected.length > 0 && <details className="technical-details"><summary>未採用 {price.rejected.length} 筆行情的日期與原因</summary>{price.rejected.map((row, index) => <div key={`${row.date}-${index}`}>{formatResearchDate(row.date)}：{overviewReason(row.reason)}（{row.reason}）</div>)}</details>}
      </section>}
      <InstitutionalWindows calendar={institutionalCalendar} scope7={institutionalScope7} data={data.institutional} expectedExchange={instrument?.exchange} expectedSymbol={instrument?.symbol} expectedCutoff={explicitCutoff ?? data.as_of ?? undefined} onCapture={onCaptureWindows} busy={capturingWindows} requestFailure={windowRequestFailure} />
      <InstitutionalDaily data={data.institutional_daily} windowsPresent={Boolean(data.institutional.version)} />
      <section className="panel overview-conditions"><h3>研究條件</h3>{data.conditions.map((condition) => <div className="overview-condition" key={condition.strategy}><div className="position-head"><strong>{condition.label}</strong><span className="badge">{condition.status === 'met' ? '成立' : condition.status === 'not_met' ? '未成立' : '資料不足'}</span></div><p className="small-note">既有結果日期 {formatResearchDate(condition.signal_date)}</p><Reasons reasons={condition.reasons} /><details className="technical-details"><summary>查看策略版本</summary>{condition.strategy} · 版本 {condition.version ?? '尚無可核對結果'}</details></div>)}<p className="small-note">沿用既有固定規則；輸入需求不等於條件成立，仍需補齊資料後才能形成完整交易計畫。</p></section>
      <OfficialEvents data={data.events} onCapture={onCaptureEvents} busy={capturingEvents} requestFailure={eventRequestFailure} />
      <section className="panel"><h3>新聞與公告入口</h3><p>保留既有來源連結、發布與事件時間。</p><button type="button" className="secondary-button" onClick={onNews}>查看新聞與公告</button><p className="small-note">新聞採已核對的發布／事件時間截至；未知時間或超過截止的項目不混入本次清單。</p></section>
    </div>
    <details className="technical-details"><summary>研究範圍與總覽版本</summary>總覽版本 {data.version}。法人窗口依上方各窗狀態，支持範圍及截止見法人區塊；價格、設定的單日法人原件及明示取得的除權息預告沿各自證據；其他範圍與研究條件尚未完成。歷史當時可得（PIT）未支援。</details>
  </section>
}
