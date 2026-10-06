import type { PriceFocusDayMove, PriceLotFocusData } from './types'
import { createPriceMemoryFixture, priceFixtureInstrument } from './stockPriceMemoryRead.test'
import { approximateRangePct, exactDayMove, exactDayRange, exactLotsText, exactTurnoverText, minLotsShares, minRangeMilliPct, minTurnoverValue, priceFocusDetailPath, priceFocusReturnPath, rangeMeetsMinimum, sharesMeetMinimum, validPriceFocusDayMove, validPriceFocusParams, validPriceLotFocus } from './priceFocus'

/** Reconstructed client contract only; never an actual source capture. */
export function createPriceFocusFixture(minLots = '20000', dayMove: PriceFocusDayMove = 'all', minTurnover = '0', minRangePct = '0', cutoff = '2026-10-05'): PriceLotFocusData {
  const reads = ['3105', '6488'].map((symbol) => ({ instrument: priceFixtureInstrument(symbol), price_memory: createPriceMemoryFixture(symbol, cutoff) }))
  // Independent fixed-data expectations; fixtures never establish source admission.
  const rangeLimits = cutoff === '2026-10-05' ? [1300 / 307, 300 / 61] : [700 / 123, 460 / 47]
  const scope = reads.filter((read, index) => {
    const bar = read.price_memory.latest!, move = cutoff === '2026-10-05' ? index === 0 ? 'up' : 'down' : index === 0 ? 'down' : 'up'
    return sharesMeetMinimum(bar.volume_exact, minLotsShares(minLots)!) && sharesMeetMinimum(bar.turnover_exact!, minTurnover)
      && (dayMove === 'all' || move === dayMove) && Number(minRangePct) <= rangeLimits[index]
  })
  return { version: 'price-lot-focus/m2-v4', status: 'available', as_of: cutoff, min_lots: minLots, min_shares: minLotsShares(minLots)!, day_move: dayMove, min_turnover: minTurnover, min_range_pct: minRangePct,
    count: scope.length, items: scope.map((read) => {
      const bar = read.price_memory.latest!, move = exactDayMove(bar.source_fields['開盤'], bar.source_fields['收盤'])!
      return { exchange: 'TPEx', symbol: read.instrument.symbol, name: read.instrument.name, volume_exact: bar.volume_exact, volume_lots: exactLotsText(bar.volume_exact),
        min_lots: minLots, min_shares: minLotsShares(minLots)!, day_move: move, min_turnover: minTurnover, turnover_exact: bar.turnover_exact!, min_range_pct: minRangePct,
        open_exact: bar.source_fields['開盤'], close_exact: bar.source_fields['收盤'], high_exact: bar.source_fields['最高'], low_exact: bar.source_fields['最低'],
        reasons: ['volume_at_least_min_lots', 'turnover_at_least_min_turnover', move === 'up' ? 'close_above_open' : 'close_below_open', 'range_at_least_min_range_pct'], source_date: cutoff, source_version: 'tpex-11370/' + cutoff,
        detail_url: priceFocusDetailPath(read.instrument.symbol, cutoff, minLots, dayMove, minTurnover, minRangePct) }
    }), reads,
    supported_scope: { exchange: 'TPEx', symbols: ['3105', '6488'], cutoff, currency: 'TWD', asset_type: 'stock' },
    can_capture: false, reasons: [], historical_pit: 'unsupported', sort: 'code_ascending' }
}

export function createUnloadedFocusFixture(): PriceLotFocusData {
  const data = createPriceFocusFixture('50000')
  data.status = 'unavailable'; data.count = null; data.can_capture = true; data.reasons = ['price_memory_capture_missing']
  for (const read of data.reads) {
    const memory = read.price_memory!
    memory.status = 'unavailable'; memory.latest = null; memory.bars = []; memory.provenance = null; memory.attribution = null
    memory.reasons = ['price_memory_capture_missing']
    memory.capture_state = { enabled: true, attempted: false, busy: false, can_capture: true, cache_present: false, request_count: 0, action: 'not_attempted' }
  }
  return data
}

export function runPriceFocusTests(): number {
  let checks = 0
  const check = (value: boolean, message: string) => { checks++; if (!value) throw new Error(message) }
  for (const [raw, expected] of [['0', '0'], ['0.001', '1'], ['20000.000', '20000000'], ['9007199254740.993', '9007199254740993'], ['9223372036854775.807', '9223372036854775807']]) {
    check(minLotsShares(raw) === expected, 'exact threshold ' + raw)
  }
  for (const invalid of [20000, 0.001, null, true, '', '-1', '+1', '01', '.1', '1.', '1.0001', '1e3', '1\n', '１', '20,000', '9223372036854775.808']) {
    check(minLotsShares(invalid) === null, 'reject invalid threshold ' + String(invalid))
  }
  check(exactLotsText('1') === '0.001' && exactLotsText('0') === '0', 'zero and one odd share')
  for (const minimum of ['20000', '20000.000', '10000', '50000', '0.000']) {
    check(validPriceLotFocus(createPriceFocusFixture(minimum), '2026-10-05', minimum), 'accepted expected candidate set ' + minimum)
  }
  check(validPriceLotFocus(createUnloadedFocusFixture(), '2026-10-05', '50000'), 'unloaded source is valid unavailable state')
  const corruptions: Array<(data: PriceLotFocusData) => void> = [
    (data) => { data.count = null }, (data) => { data.items.reverse() }, (data) => { data.items.push(data.items[0]); data.count = 3 },
    (data) => { data.reads.pop() }, (data) => { data.reads[1].instrument.name = 'unknown' },
    (data) => { data.reads[1].instrument.market = 'US' }, (data) => { data.reads[1].instrument.etf_category = 'mixed' },
    (data) => { data.reads[1].instrument.currency = 'USD' }, (data) => { data.items[0].detail_url = 'https://foreign.example/' },
    (data) => { data.items[0].volume_exact = '0' }, (data) => { data.reads[1].price_memory!.as_of = '2026-10-02' },
    (data) => { data.reads[1].price_memory!.provenance!.captured_at = '2026-10-06T00:00:00Z' },
    (data) => { data.items[0].day_move = 'flat' }, (data) => { data.items[0].open_exact = '614' },
    (data) => { data.items[0].reasons[2] = 'close_below_open' }, (data) => { data.items[0].reasons.pop() },
    (data) => { delete data.reads[0].price_memory!.latest!.source_fields['開盤'] },
    (data) => { data.reads[0].price_memory!.latest!.source_fields['收盤'] = '-1' },
    (data) => { data.day_move = 'up' },
  ]
  for (const corrupt of corruptions) { const data = createPriceFocusFixture('10000'); corrupt(data); check(!validPriceLotFocus(data, '2026-10-05', '10000'), 'reject incomplete or conflicting proof') }
  const falseEmpty = createUnloadedFocusFixture(); falseEmpty.status = 'available'; falseEmpty.count = 0; falseEmpty.can_capture = false; falseEmpty.reasons = []
  check(!validPriceLotFocus(falseEmpty, '2026-10-05', '50000'), 'missing source cannot become true zero')
  const unsafe = createPriceFocusFixture()
  unsafe.min_lots = '9007199254740.993'; unsafe.min_shares = '9007199254740993'
  const bar = unsafe.reads[0].price_memory!.latest!
  bar.volume_exact = '9007199254740993'; bar.volume = null; bar.source_fields['成交股數'] = bar.volume_exact
  Object.assign(unsafe.items[0], { volume_exact: '9007199254740993', volume_lots: '9007199254740.993', min_lots: unsafe.min_lots, min_shares: unsafe.min_shares,
    detail_url: priceFocusDetailPath('3105', '2026-10-05', '9007199254740.993') })
  check(validPriceLotFocus(unsafe, '2026-10-05', '9007199254740.993'), 'above safe integer still selects exact equality')
  unsafe.min_lots = '9007199254740.994'; unsafe.min_shares = '9007199254740994'; unsafe.items = []; unsafe.count = 0
  check(validPriceLotFocus(unsafe, '2026-10-05', '9007199254740.994'), 'one share higher threshold excludes unsafe number')
  for (const [volume, lots, minimum, shares, expectedCount] of [
    ['0', '0', '0', '0', 2], ['0', '0', '0.001', '1', 0], ['1', '0.001', '0.001', '1', 2],
    ['9223372036854775807', '9223372036854775.807', '9223372036854775.807', '9223372036854775807', 2],
  ] as const) {
    const data = createPriceFocusFixture('0.000')
    data.min_lots = minimum; data.min_shares = shares; data.count = expectedCount
    for (const read of data.reads) {
      const bar = read.price_memory!.latest!
      bar.volume_exact = volume; bar.volume = volume.length > 16 ? null : Number(volume); bar.source_fields['成交股數'] = volume
    }
    data.items = expectedCount === 0 ? [] : data.items.map((item) => ({ ...item, volume_exact: volume, volume_lots: lots,
      min_lots: minimum, min_shares: shares, detail_url: priceFocusDetailPath(item.symbol, '2026-10-05', minimum) }))
    check(validPriceLotFocus(data, '2026-10-05', minimum), 'zero, one share and int64 complete-response boundary')
  }
  const good = 'as_of=2026-10-05&from=price-lots&focus_as_of=2026-10-05&focus_min_lots=20000.000'
  check(priceFocusReturnPath(new URLSearchParams(good)) === '/?as_of=2026-10-05&min_lots=20000.000&day_move=all&min_turnover=0&min_range_pct=0#price-lot-focus-title', 'legacy URL returns original threshold string and default direction/amount')
  for (const bad of [good + '&next=https://foreign.example', good + '&focus_min_lots=1', good.replace('2026-10-05', '2026-02-30'),
    good.replace('focus_as_of=2026-10-05', 'focus_as_of=https://foreign.example'), good.replace('20000.000', '1e3'), good.replace('from=price-lots', 'from=https://foreign.example'),
    good + '&focus_day_move=unknown', good + '&focus_day_move=up&focus_day_move=down', good + '&focus_day_move=',
    good.replace('as_of=2026-10-05', 'as_of=2026-10-02'), good + '&from=price-lots', good + '&focus_as_of=2026-10-05']) {
    check(priceFocusReturnPath(new URLSearchParams(bad)) === null, 'reject malformed/foreign/duplicate return state')
  }
  check(!validPriceLotFocus(createPriceFocusFixture(), '2026-10-02', '20000'), 'reject response URL cutoff mismatch')
  for (const move of ['all', 'up', 'down', 'flat'] as const) {
    const data = createPriceFocusFixture('10000.000', move)
    const expected = move === 'all' ? ['3105', '6488'] : move === 'up' ? ['3105'] : move === 'down' ? ['6488'] : []
    check(data.items.map((item) => item.symbol).join() === expected.join() && validPriceLotFocus(data, '2026-10-05', '10000.000', move), 'all directions complete expected set ' + move)
    check(priceFocusReturnPath(new URLSearchParams(good + '&focus_day_move=' + move)) === `/?as_of=2026-10-05&min_lots=20000.000&day_move=${move}&min_turnover=0&min_range_pct=0#price-lot-focus-title`, 'complete original conditions ' + move)
    check(!validPriceLotFocus(data, '2026-10-05', '10000.000', move === 'up' ? 'down' : 'up'), 'reject stale other direction ' + move)
  }
  for (const [opening, closing, expected] of [['1.000000000000000001', '1.000000000000000002', 'up'], ['1.000000000000000002', '1.000000000000000001', 'down'],
    ['1', '1.000', 'flat'], ['0.0010', '0.001', 'flat'], ['9.9', '10.0', 'up'], ['0.0001', '0.001', 'up']]) {
    check(exactDayMove(opening, closing) === expected, 'source exact decimal ' + opening + '/' + closing)
  }
  check(Number('1.000000000000000001') === Number('1.000000000000000002'), 'precision case actually projects to same Number')
  for (const value of [null, 1, '', '0', '0.000', '-1', 'NaN', 'Infinity', '1e0', '01', '1.', '１', ' 1', '1\n', '1'.repeat(65)]) {
    check(exactDayMove(value, '1') === null && exactDayMove('1', value) === null, 'reject invalid O/C ' + String(value))
  }
  for (const invalid of [null, 1, '', 'UP', 'all\n', 'unknown']) check(!validPriceFocusDayMove(invalid), 'reject invalid direction')
  const precise = createPriceFocusFixture('10000', 'up')
  const preciseBar = precise.reads[0].price_memory!.latest!
  preciseBar.open = preciseBar.close = 1; preciseBar.low = 1; preciseBar.high = 2
  Object.assign(preciseBar.source_fields, { '開盤': '1.000000000000000001', '收盤': '1.000000000000000002', '最低': '1', '最高': '2' })
  Object.assign(precise.items[0], { open_exact: '1.000000000000000001', close_exact: '1.000000000000000002', high_exact: '2', low_exact: '1' })
  check(validPriceLotFocus(precise, '2026-10-05', '10000', 'up'), 'validator selects up despite same projected Number')
  const flat = createPriceFocusFixture('10000')
  flat.day_move = 'flat'
  for (const read of flat.reads) {
    const bar = read.price_memory!.latest!
    bar.open = bar.close = 1; bar.low = 1; bar.high = 2
    Object.assign(bar.source_fields, { '開盤': '1.0', '收盤': '1.000', '最低': '1', '最高': '2' })
  }
  for (const item of flat.items) Object.assign(item, { day_move: 'flat', open_exact: '1.0', close_exact: '1.000', high_exact: '2', low_exact: '1', reasons: ['volume_at_least_min_lots', 'turnover_at_least_min_turnover', 'close_equal_open', 'range_at_least_min_range_pct'], detail_url: priceFocusDetailPath(item.symbol, '2026-10-05', '10000', 'flat') })
  check(validPriceLotFocus(flat, '2026-10-05', '10000', 'flat'), 'equal value with different trailing decimals selects flat')
  for (const amount of ['0', '1', '29694939981', '9007199254740993', '9223372036854775807']) check(minTurnoverValue(amount) === amount, 'exact int64 TWD ' + amount)
  for (const bad of [null, true, 1, '', '00', '01', '-1', '+1', '1.0', '1e3', '1,000', ' 1', '1\n', '１', '9223372036854775808']) {
    check(minTurnoverValue(bad) === null, 'reject invalid TWD ' + String(bad))
  }
  check(exactTurnoverText('9007199254740993') === '9,007,199,254,740,993', 'exact grouping above safe Number')
  for (const [amount, move, expected] of [['25000000000', 'all', '3105'], ['20000000000', 'all', '3105,6488'], ['25000000000', 'down', ''],
    ['29694939981', 'all', '3105'], ['29694939982', 'all', ''], ['22887612060', 'down', '6488'], ['22887612061', 'down', '']] as const) {
    const data = createPriceFocusFixture('10000.000', move, amount)
    check(data.items.map((item) => item.symbol).join() === expected && validPriceLotFocus(data, '2026-10-05', '10000.000', move, amount), 'exact amount candidate set ' + amount + '/' + move)
    check(!validPriceLotFocus(data, '2026-10-05', '10000.000', move, '0'), 'stale other turnover response rejected')
    check(priceFocusReturnPath(new URLSearchParams(good + '&focus_day_move=' + move + '&focus_min_turnover=' + amount))
      === `/?as_of=2026-10-05&min_lots=20000.000&day_move=${move}&min_turnover=${amount}&min_range_pct=0#price-lot-focus-title`, 'all original conditions including exact TWD')
  }
  for (const [amount, minimum, expectedCount] of [['0', '0', 2], ['0', '1', 0], ['1', '1', 2], ['1', '2', 0],
    ['9007199254740993', '9007199254740993', 2], ['9007199254740993', '9007199254740994', 0], ['9223372036854775807', '9223372036854775807', 2]] as const) {
    const data = createPriceFocusFixture('10000')
    data.min_turnover = minimum
    for (const read of data.reads) {
      const bar = read.price_memory!.latest!
      bar.turnover_exact = amount
      bar.turnover = amount.length > 16 || (amount.length === 16 && amount > '9007199254740991') ? null : Number(amount)
      bar.source_fields['成交金額'] = amount
    }
    data.items = expectedCount ? data.items.map((item) => ({ ...item, min_turnover: minimum, turnover_exact: amount,
      detail_url: priceFocusDetailPath(item.symbol, '2026-10-05', '10000', 'all', minimum) })) : []
    data.count = expectedCount
    check(validPriceLotFocus(data, '2026-10-05', '10000', 'all', minimum), 'zero/one/unsafe/int64 complete amount response ' + amount + '/' + minimum)
  }
  for (const corrupt of [
    (data: PriceLotFocusData) => { data.items[0].turnover_exact = '0' },
    (data: PriceLotFocusData) => { data.items[0].min_turnover = '1' },
    (data: PriceLotFocusData) => { data.reads[1].price_memory!.latest!.source_fields['成交金額'] = '0' },
    (data: PriceLotFocusData) => { data.reads[1].price_memory!.latest!.turnover_status = 'unavailable' },
    (data: PriceLotFocusData) => { const bar = data.reads[1].price_memory!.latest!; bar.turnover_exact = null; bar.turnover = null; bar.turnover_status = 'unavailable'; bar.turnover_reason = 'missing'; bar.source_fields['成交金額'] = '' },
  ]) {
    const data = createPriceFocusFixture('10000'); corrupt(data)
    check(!validPriceLotFocus(data, '2026-10-05', '10000'), 'missing/conflicting turnover never passes even zero threshold')
  }
  const home = 'as_of=2026-10-05&min_lots=10000.000&day_move=all'
  check(validPriceFocusParams(new URLSearchParams(home)) && validPriceFocusParams(new URLSearchParams(home + '&q=3105')), 'legacy homepage and shared q preserved')
  for (const suffix of ['&min_turnover=', '&min_turnover=-1', '&min_turnover=01', '&min_turnover=1.0', '&min_turnover=1&min_turnover=2', '&next=https://foreign.example', '&q=1&q=2']) {
    check(!validPriceFocusParams(new URLSearchParams(home + suffix)), 'invalid/duplicate/foreign homepage disabled')
  }
  for (const suffix of ['&focus_min_turnover=', '&focus_min_turnover=-1', '&focus_min_turnover=01', '&focus_min_turnover=1.0', '&focus_min_turnover=1&focus_min_turnover=2']) {
    check(priceFocusReturnPath(new URLSearchParams(good + suffix)) === null, 'unsafe turnover return state rejected')
  }
  for (const [raw, expected] of [['0.000', '0'], ['4.500', '4500'], ['9223372036854775.807', '9223372036854775807']]) check(minRangeMilliPct(raw) === expected, 'range int64 thousandth ' + raw)
  for (const bad of [null, 1, true, '', '01', '-1', '+1', '.1', '1.', '1.0001', '1e0', ' 1', '1\n', '１', '1,000', '9223372036854775.808']) check(minRangeMilliPct(bad) === null, 'invalid range threshold ' + String(bad))
  const longOpen = '1.000000000000000000000000000001'
  for (const [opening, high, low, minimum, expected] of [
    ['100', '104', '100', '4', true], ['100.00', '104.000', '100.0', '4.001', false],
    ['3', '3.0001', '3.0', '0.003', true], ['3.00', '3.0001', '3', '0.004', false],
    [longOpen, '1.040000000000000000000000000001', longOpen, '4', false],
    [longOpen, '1.040000000000000000000000000001', longOpen, '3.999', true],
    ['1', '92233720368548.75807', '1', '9223372036854775.807', true], ['1', '92233720368548.75806', '1', '9223372036854775.807', false],
    ['1.0', '1.000', '1', '0.000', true], ['1', '1', '1', '0.001', false],
  ] as const) check(rangeMeetsMinimum(opening, high, low, minimum) === expected, 'independent rational boundary ' + opening + '/' + minimum)
  check(approximateRangePct('1', '1.000005', '1') === '0.001' && rangeMeetsMinimum('1', '1.000005', '1', '0.001') === false, 'display half-up is separate from exact candidate boundary')
  check(approximateRangePct('615.00', '623.00', '588.00') === '5.691' && approximateRangePct('1175.00', '1260.00', '1145.00') === '9.787', 'new date independent 700/123 and 460/47 percentages')
  for (const bad of [null, 1, '', '0', '-1', '01', '1e0', '1\n', '1'.repeat(65)]) check(exactDayRange(bad, '1', '1') === null && exactDayRange('1', bad, '1') === null && exactDayRange('1', '1', bad) === null, 'missing invalid range never becomes zero')
  check(exactDayRange('2', '1', '1') === null && exactDayRange('1', '2', '1.000000000000000000000000000001') === null, 'exact bounds even when Number projection hides violation')
  for (const [minimum, move, expected] of [['0', 'all', '3105,6488'], ['4', 'all', '3105,6488'], ['6.000', 'all', '6488'], ['10', 'all', ''], ['6', 'down', ''], ['6', 'up', '6488'],
    ['5.691', 'all', '3105,6488'], ['5.692', 'all', '6488'], ['9.787', 'all', '6488'], ['9.788', 'all', '']] as const) {
    const data = createPriceFocusFixture('10000.000', move, '0', minimum, '2026-10-06')
    check(data.items.map((item) => item.symbol).join() === expected && validPriceLotFocus(data, '2026-10-06', '10000.000', move, '0', minimum), 'new date exact range result ' + minimum + '/' + move)
    check(!validPriceLotFocus(data, '2026-10-05', '10000.000', move, '0', minimum), 'new date never admitted under old cutoff')
    check(priceFocusReturnPath(new URLSearchParams(priceFocusDetailPath('6488', '2026-10-06', '10000.000', move, '0', minimum).split('?')[1])) === `/?as_of=2026-10-06&min_lots=10000.000&day_move=${move}&min_turnover=0&min_range_pct=${minimum}#price-lot-focus-title`, 'all five raw conditions returned')
  }
  for (const corrupt of [
    (data: PriceLotFocusData) => { data.min_range_pct = '1' }, (data: PriceLotFocusData) => { data.items[0].min_range_pct = '1' },
    (data: PriceLotFocusData) => { data.items[0].high_exact = '1' }, (data: PriceLotFocusData) => { data.items[0].low_exact = '1' },
    (data: PriceLotFocusData) => { data.items[0].reasons[3] = 'other' as 'range_at_least_min_range_pct' },
    (data: PriceLotFocusData) => { data.items[0].detail_url += '&focus_min_range_pct=1' },
    (data: PriceLotFocusData) => { delete data.reads[1].price_memory!.latest!.source_fields['最高'] },
    (data: PriceLotFocusData) => { data.reads[1].price_memory!.latest!.source_fields['最低'] = '' },
  ]) { const data = createPriceFocusFixture('10000'); corrupt(data); check(!validPriceLotFocus(data, '2026-10-05', '10000'), 'reject range response tampering even threshold zero') }
  const zeroRange = createPriceFocusFixture('10000')
  for (const read of zeroRange.reads) { const bar = read.price_memory!.latest!; bar.open = bar.high = bar.low = bar.close = 1; Object.assign(bar.source_fields, { '開盤': '1.0', '最高': '1.000', '最低': '1', '收盤': '1' }) }
  for (const item of zeroRange.items) Object.assign(item, { open_exact: '1.0', high_exact: '1.000', low_exact: '1', close_exact: '1', day_move: 'flat', reasons: ['volume_at_least_min_lots', 'turnover_at_least_min_turnover', 'close_equal_open', 'range_at_least_min_range_pct'] })
  check(validPriceLotFocus(zeroRange, '2026-10-05', '10000'), 'source exact zero range succeeds at zero threshold')
  zeroRange.min_range_pct = '0.001'; zeroRange.items = []; zeroRange.count = 0
  check(validPriceLotFocus(zeroRange, '2026-10-05', '10000', 'all', '0', '0.001'), 'source zero range gives true zero at positive threshold')
  const nearFour = createPriceFocusFixture('10000', 'all', '0', '4')
  nearFour.items = []; nearFour.count = 0
  for (const read of nearFour.reads) {
    const bar = read.price_memory!.latest!
    bar.open = bar.close = bar.low = 1; bar.high = 1.04
    Object.assign(bar.source_fields, { '開盤': longOpen, '最低': longOpen, '收盤': longOpen, '最高': '1.040000000000000000000000000001' })
  }
  check(validPriceLotFocus(nearFour, '2026-10-05', '10000', 'all', '0', '4'), 'complete response recomputes below four despite rounded Number equality')
  for (const suffix of ['&min_range_pct=', '&min_range_pct=01', '&min_range_pct=-1', '&min_range_pct=1e0', '&min_range_pct=1.0001', '&min_range_pct=1&min_range_pct=2']) check(!validPriceFocusParams(new URLSearchParams(home + suffix)), 'invalid homepage range state disabled')
  for (const suffix of ['&focus_min_range_pct=', '&focus_min_range_pct=01', '&focus_min_range_pct=-1', '&focus_min_range_pct=1.0001', '&focus_min_range_pct=1&focus_min_range_pct=2', '&q=3105']) check(priceFocusReturnPath(new URLSearchParams(good + suffix)) === null, 'invalid range/extra q safe return rejected')
  check(!validPriceLotFocus(createPriceFocusFixture('10000', 'all', '0', '4'), '2026-10-05', '10000', 'all', '0', '4.000'), 'raw tail zeros are part of response identity')
  return checks
}
