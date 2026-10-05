import type { PriceLotFocusData } from './types'
import { createPriceMemoryFixture, priceFixtureInstrument } from './stockPriceMemoryRead.test'
import { exactLotsText, minLotsShares, priceFocusReturnPath, validPriceLotFocus } from './priceFocus'

/** Reconstructed client contract only; never an actual source capture. */
export function createPriceFocusFixture(minLots = '20000'): PriceLotFocusData {
  const scope = minLots === '50000' ? [] : minLots === '10000' || minLots === '0.000' ? ['3105', '6488'] : ['3105']
  const minimum: Record<string, string> = { '20000': '20000000', '20000.000': '20000000', '10000': '10000000', '50000': '50000000', '0.000': '0' }
  return { version: 'price-lot-focus/m2-v1', status: 'available', as_of: '2026-10-05', min_lots: minLots, min_shares: minimum[minLots],
    count: scope.length, items: scope.map((symbol) => ({ exchange: 'TPEx', symbol, name: symbol === '3105' ? '穩懋' : '環球晶',
      volume_exact: symbol === '3105' ? '48127911' : '18982607', volume_lots: symbol === '3105' ? '48127.911' : '18982.607',
      min_lots: minLots, min_shares: minimum[minLots], reason: 'volume_at_least_min_lots', source_date: '2026-10-05', source_version: 'tpex-11370/2026-10-05',
      detail_url: `/stocks/TPEx/${symbol}?as_of=2026-10-05&from=price-lots&focus_as_of=2026-10-05&focus_min_lots=${minLots}` })),
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
  ]
  for (const corrupt of corruptions) { const data = createPriceFocusFixture('10000'); corrupt(data); check(!validPriceLotFocus(data, '2026-10-05', '10000'), 'reject incomplete or conflicting proof') }
  const falseEmpty = createUnloadedFocusFixture(); falseEmpty.status = 'available'; falseEmpty.count = 0; falseEmpty.can_capture = false; falseEmpty.reasons = []
  check(!validPriceLotFocus(falseEmpty, '2026-10-05', '50000'), 'missing source cannot become true zero')
  const unsafe = createPriceFocusFixture()
  unsafe.min_lots = '9007199254740.993'; unsafe.min_shares = '9007199254740993'
  const bar = unsafe.reads[0].price_memory!.latest!
  bar.volume_exact = '9007199254740993'; bar.volume = null; bar.source_fields['成交股數'] = bar.volume_exact
  Object.assign(unsafe.items[0], { volume_exact: '9007199254740993', volume_lots: '9007199254740.993', min_lots: unsafe.min_lots, min_shares: unsafe.min_shares,
    detail_url: '/stocks/TPEx/3105?as_of=2026-10-05&from=price-lots&focus_as_of=2026-10-05&focus_min_lots=9007199254740.993' })
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
      min_lots: minimum, min_shares: shares, detail_url: `/stocks/TPEx/${item.symbol}?as_of=2026-10-05&from=price-lots&focus_as_of=2026-10-05&focus_min_lots=${minimum}` }))
    check(validPriceLotFocus(data, '2026-10-05', minimum), 'zero, one share and int64 complete-response boundary')
  }
  const good = 'as_of=2026-10-05&from=price-lots&focus_as_of=2026-10-05&focus_min_lots=20000.000'
  check(priceFocusReturnPath(new URLSearchParams(good)) === '/?as_of=2026-10-05&min_lots=20000.000#price-lot-focus-title', 'returns original equivalent threshold string')
  for (const bad of [good + '&next=https://foreign.example', good + '&focus_min_lots=1', good.replace('2026-10-05', '2026-02-30'),
    good.replace('focus_as_of=2026-10-05', 'focus_as_of=https://foreign.example'), good.replace('20000.000', '1e3'), good.replace('from=price-lots', 'from=https://foreign.example')]) {
    check(priceFocusReturnPath(new URLSearchParams(bad)) === null, 'reject malformed/foreign/duplicate return state')
  }
  check(!validPriceLotFocus(createPriceFocusFixture(), '2026-10-02', '20000'), 'reject response URL cutoff mismatch')
  return checks
}
