import type { PriceFocusDayMove, PriceLotFocusData } from './types'
import { createPriceMemoryFixture, priceFixtureInstrument } from './stockPriceMemoryRead.test'
import { exactDayMove, exactLotsText, exactTurnoverText, minLotsShares, minTurnoverValue, priceFocusDetailPath, priceFocusReturnPath, sharesMeetMinimum, validPriceFocusDayMove, validPriceFocusParams, validPriceLotFocus } from './priceFocus'

/** Reconstructed client contract only; never an actual source capture. */
export function createPriceFocusFixture(minLots = '20000', dayMove: PriceFocusDayMove = 'all', minTurnover = '0'): PriceLotFocusData {
  const volumeScope = ['3105', '6488'].filter((symbol) => sharesMeetMinimum(symbol === '3105' ? '48127911' : '18982607', minLotsShares(minLots)!)
    && sharesMeetMinimum(symbol === '3105' ? '29694939981' : '22887612060', minTurnover))
  const scope = volumeScope.filter((symbol) => dayMove === 'all' || dayMove === (symbol === '3105' ? 'up' : 'down'))
  const minimum: Record<string, string> = { '20000': '20000000', '20000.000': '20000000', '10000': '10000000', '50000': '50000000', '0.000': '0' }
  return { version: 'price-lot-focus/m2-v3', status: 'available', as_of: '2026-10-05', min_lots: minLots, min_shares: minimum[minLots] ?? minLotsShares(minLots)!, day_move: dayMove, min_turnover: minTurnover,
    count: scope.length, items: scope.map((symbol) => ({ exchange: 'TPEx', symbol, name: symbol === '3105' ? '穩懋' : '環球晶',
      volume_exact: symbol === '3105' ? '48127911' : '18982607', volume_lots: symbol === '3105' ? '48127.911' : '18982.607',
      min_lots: minLots, min_shares: minimum[minLots] ?? minLotsShares(minLots)!, day_move: symbol === '3105' ? 'up' : 'down',
      min_turnover: minTurnover, turnover_exact: symbol === '3105' ? '29694939981' : '22887612060',
      open_exact: symbol === '3105' ? '614.00' : '1220.00', close_exact: symbol === '3105' ? '615.00' : '1180.00',
      reasons: ['volume_at_least_min_lots', 'turnover_at_least_min_turnover', symbol === '3105' ? 'close_above_open' : 'close_below_open'], source_date: '2026-10-05', source_version: 'tpex-11370/2026-10-05',
      detail_url: priceFocusDetailPath(symbol, '2026-10-05', minLots, dayMove, minTurnover) })),
    reads: ['3105', '6488'].map((symbol) => ({ instrument: priceFixtureInstrument(symbol), price_memory: createPriceMemoryFixture(symbol) })),
    supported_scope: { exchange: 'TPEx', symbols: ['3105', '6488'], cutoff: '2026-10-05', currency: 'TWD', asset_type: 'stock' },
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
  check(priceFocusReturnPath(new URLSearchParams(good)) === '/?as_of=2026-10-05&min_lots=20000.000&day_move=all&min_turnover=0#price-lot-focus-title', 'legacy URL returns original threshold string and default direction/amount')
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
    check(priceFocusReturnPath(new URLSearchParams(good + '&focus_day_move=' + move)) === `/?as_of=2026-10-05&min_lots=20000.000&day_move=${move}&min_turnover=0#price-lot-focus-title`, 'complete original conditions ' + move)
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
  Object.assign(precise.items[0], { open_exact: '1.000000000000000001', close_exact: '1.000000000000000002' })
  check(validPriceLotFocus(precise, '2026-10-05', '10000', 'up'), 'validator selects up despite same projected Number')
  const flat = createPriceFocusFixture('10000')
  flat.day_move = 'flat'
  for (const read of flat.reads) {
    const bar = read.price_memory!.latest!
    bar.open = bar.close = 1; bar.low = 1; bar.high = 2
    Object.assign(bar.source_fields, { '開盤': '1.0', '收盤': '1.000', '最低': '1', '最高': '2' })
  }
  for (const item of flat.items) Object.assign(item, { day_move: 'flat', open_exact: '1.0', close_exact: '1.000', reasons: ['volume_at_least_min_lots', 'turnover_at_least_min_turnover', 'close_equal_open'], detail_url: priceFocusDetailPath(item.symbol, '2026-10-05', '10000', 'flat') })
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
      === `/?as_of=2026-10-05&min_lots=20000.000&day_move=${move}&min_turnover=${amount}#price-lot-focus-title`, 'all original conditions including exact TWD')
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
  return checks
}
