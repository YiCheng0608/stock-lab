import { formatCanonicalShareLots, formatCanonicalShares, formatTableNumber, formatTableVolume, formatTableVolumeShares, formatTableChip, formatShareLots, formatShareQuantity, formatPositionShares, positionQuantityFromText, formatSignedShareLots, formatSourceAwareShareLots, formatVolumeLots, isVerifiedChipFlowSource, isVerifiedMarginSource, isVerifiedShareSource, sharesFromUnit, type ShareUnit } from './units'

if (sharesFromUnit('lot', 1) !== 1000) throw new Error('one lot must equal 1000 shares')
if (sharesFromUnit('lot', 2) !== 2000) throw new Error('lot conversion must be exact')
if (sharesFromUnit('odd_lot', 999) !== 999) throw new Error('odd-lot conversion must preserve shares')
if (formatShareQuantity(1000) !== '1 張') throw new Error('1000 shares should display as one lot')
if (formatShareQuantity(1500) !== '1.5 張') throw new Error('mixed holdings should retain their remainder in decimal lots')
if (formatShareQuantity(999) !== '0.999 張') throw new Error('odd-lot holdings should retain every share in decimal lots')
if (formatShareLots(1500) !== '1.5 張') throw new Error('share volume should display fractional lots')
if (formatShareLots(-500) !== '-0.5 張') throw new Error('negative share flow should preserve sign')
if (formatShareLots(1000.25) !== '待核實') throw new Error('fractional shares must not be rounded into a valid quantity')
if (formatSignedShareLots(-1000) !== '-1 張') throw new Error('signed share flow should preserve a negative sign')
if (formatVolumeLots(1000) !== '1 張') throw new Error('nonnegative volume should display as lots')
if (formatVolumeLots(-1000) !== '待核實' || formatVolumeLots(Number.NaN) !== '待核實') throw new Error('negative or nonfinite volume must fail closed')
if (!isVerifiedShareSource('twse') || !isVerifiedShareSource('tpex')) throw new Error('official bar sources should be verified')
if (formatSourceAwareShareLots(1500, 'twse') !== '1.5 張') throw new Error('verified bar source should convert to lots')
if (formatSourceAwareShareLots(1500, 'unknown_twse') !== '1,500（單位待提供）') throw new Error('unknown bar source must preserve raw value')
if (formatSourceAwareShareLots(-1000, 'twse') !== '待核實' || formatSourceAwareShareLots(-1000, 'unknown') !== '待核實') throw new Error('negative volume must not be rendered as a negative lot count')
for (const source of ['unknown_twse', 'twse+mixed', 'unverified-twse']) {
  if (isVerifiedShareSource(source)) throw new Error(`unrecognized bar source was accepted: ${source}`)
}
if (!isVerifiedChipFlowSource('twse_t86') || !isVerifiedChipFlowSource('twse_t86+twse_margin') || !isVerifiedChipFlowSource('tpex_3insti+tpex_margin')) throw new Error('official institutional source combinations should be verified')
for (const source of ['twse_t86+unknown', 'mixed', 'unknown_twse_t86']) {
  if (isVerifiedChipFlowSource(source)) throw new Error(`unrecognized chip source was accepted: ${source}`)
}
if (!isVerifiedMarginSource('twse_margin') || !isVerifiedMarginSource('tpex_3insti+tpex_margin')) throw new Error('official margin source combinations should be verified')
for (const quantity of [0, -1, 1.5]) {
  try {
    sharesFromUnit('lot', quantity)
    throw new Error('invalid share quantity was accepted')
  } catch (error) {
    if (!(error instanceof Error) || error.message === 'invalid share quantity was accepted') throw error
  }
}

for (const value of [null, undefined, Number.NaN, Infinity, '0']) {
  if (formatTableNumber(value) !== '') throw new Error('missing or invalid table values must stay blank')
}
if (formatTableNumber(0) !== '0') throw new Error('real zero must remain visible')
if (formatTableVolume(1250, 'twse') !== '1.25') throw new Error('table volume must convert without a unit suffix')
if (formatTableVolume(1250, 'mixed') !== '' || formatTableVolume(-1, 'twse') !== '') throw new Error('unverified or invalid volume must stay blank')
if (formatTableChip(-1250, 'twse_t86') !== '-1.25' || formatTableChip(250, 'tpex_3insti') !== '+0.25') throw new Error('table flow preserves direction and fractional lots')
if (formatTableChip(0, 'twse_t86') !== '0' || formatTableChip(null, 'twse_t86') !== '') throw new Error('chip zero and missing are distinct')
if (formatTableChip(1250, 'twse_margin', true) !== '+1,250') throw new Error('margin values already use lots and must not be divided again')
if (formatTableChip(1250, 'twse_t86+unknown') !== '' || formatTableChip(1250, 'twse_t86', true) !== '') throw new Error('unknown field units must not mix into the lot table')

const exactVolumeCases = [
  ['0', '0', '0'], ['1', '0.001', '1'], ['999', '0.999', '999'],
  ['1000', '1', '1,000'], ['1001', '1.001', '1,001'],
  ['9007199254740991', '9,007,199,254,740.991', '9,007,199,254,740,991'],
  ['9007199254740993', '9,007,199,254,740.993', '9,007,199,254,740,993'],
  ['9223372036854775807', '9,223,372,036,854,775.807', '9,223,372,036,854,775,807'],
]
for (const [exact, lots, shares] of exactVolumeCases) {
  for (const source of ['twse', 'tpex']) {
    if (formatTableVolume(Number(exact), source, exact) !== lots) throw new Error(`exact lots lost digits: ${exact}`)
    if (formatTableVolumeShares(Number(exact), source, exact) !== shares) throw new Error(`exact shares lost digits: ${exact}`)
  }
}
for (const exact of [null, true, 1, '', '00', '01', '-0', '-1', '+1', ' 1', '1 ', '1\n', '1\r', '1\r\n', '1\t', '1\u2028', '1\u2029', '1.0', '1.5', '1e3', '1,000', '9223372036854775808', '9'.repeat(1000)]) {
  // Deliberately violate the compile-time shape to test real malformed JSON.
  if (formatTableVolume(1000, 'twse', exact as string) !== '' || formatTableVolumeShares(1000, 'twse', exact as string) !== '') throw new Error('invalid exact field must not fall back to the safe number')
}
for (const value of [true, -1, 1.5, NaN, Infinity, 9007199254740992, Number('9007199254740993'), Number('9223372036854775807')]) {
  if (formatTableVolume(value as number, 'twse') !== '' || formatTableVolumeShares(value as number, 'twse') !== '') throw new Error('unsafe legacy-only volume must not be shown as exact')
}
if (formatTableVolume(9007199254740991, 'twse') !== '9,007,199,254,740.991') throw new Error('safe legacy boundary must retain every digit after conversion')
if (formatTableVolume(1000, 'unknown', '1000') !== '' || formatTableVolumeShares(1000, 'twse+mixed', '1000') !== '') throw new Error('exact text cannot admit an unknown source unit')
console.log('units exact volume cases passed')

const exactPositionCases = [
  ['0', '0 張'], ['1', '0.001 張'], ['999', '0.999 張'],
  ['1000', '1 張'], ['1001', '1.001 張'],
  ['9007199254740991', '9,007,199,254,740.991 張'],
  ['9007199254740993', '9,007,199,254,740.993 張'],
  ['9223372036854775807', '9,223,372,036,854,775.807 張'],
]
for (const [exact, mixed] of exactPositionCases) {
  if (formatShareQuantity(Number(exact), exact) !== mixed) throw new Error(`exact mixed position lost digits: ${exact}`)
  if (formatPositionShares(Number(exact), exact) !== exact.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + ' 股') throw new Error(`exact original shares lost digits: ${exact}`)
}
for (const exact of [null, true, 1, '', '00', '01', '-0', '-1', '+1', ' 1', '1 ', '1\n', '1\r', '1\r\n', '1\t', '1\u2028', '1\u2029', '1.0', '1.5', '1e3', '1,000', '９', '9223372036854775808', '9'.repeat(1000)]) {
  if (formatShareQuantity(1000, exact as string) !== '庫存數量待核實' || formatPositionShares(1000, exact as string) !== '股數待核實') throw new Error('malformed exact position must not use its safe number')
}
for (const value of [null, undefined, true, -1, 1.5, NaN, Infinity, 9007199254740992, Number('9007199254740993'), Number('9223372036854775807')]) {
  if (formatShareQuantity(value as number) !== '庫存數量待核實' || formatPositionShares(value as number) !== '股數待核實') throw new Error('unsafe legacy position must stay unknown')
}
if (formatShareQuantity(9007199254740991) !== '9,007,199,254,740.991 張') throw new Error('safe absent-field position must retain remainder 991')
if (formatPositionShares(0) !== '0 股') throw new Error('existing zero must remain visible')
for (const [unit, raw, expected] of [['lot', '9007199254740', '9007199254740'], ['odd_lot', '9007199254740991', '9007199254740991'], ['lot', '0001', '1'], ['odd_lot', '1500', '1500'], ['odd_lot', '9007199254740993', '9007199254740993'], ['odd_lot', '9223372036854775807', '9223372036854775807'], ['lot', '9223372036854775', '9223372036854775']] as const) {
  if (positionQuantityFromText(unit, raw) !== expected) throw new Error('valid raw position input was changed')
}
for (const [unit, raw] of [['lot', '9223372036854776'], ['odd_lot', '9223372036854775808'], ['wrong', '1'], ...['', '0', '000', '-1', '+1', '1.0', '1.5', '1e3', '1,000', ' 1', '1 ', '1\n', '1\r', '1\t', '1\u2028', '1\u2029', '９', 'NaN', 'Infinity', '9'.repeat(1000)].map((raw) => ['lot', raw])]) {
  let denied = false
  try { positionQuantityFromText(unit as ShareUnit, raw) } catch { denied = true }
  if (!denied) throw new Error(`unsafe raw position input accepted: ${unit}/${raw}`)
}
for (const [unit, quantity] of [['wrong', 1], ['lot', 9007199254741], ['odd_lot', 9007199254740992], ['odd_lot', Infinity], ['odd_lot', NaN]] as const) {
  let denied = false
  try { sharesFromUnit(unit as ShareUnit, quantity) } catch { denied = true }
  if (!denied) throw new Error('unsafe numeric position input accepted')
}
console.log('units exact position and raw input boundaries passed')

let canonicalChecks = 0
function checkCanonical(condition: boolean, message: string): void {
  canonicalChecks++
  if (!condition) throw new Error(message)
}
for (const [shares, lots] of [
  ['0', '0'], ['1', '0.001'], ['-1', '-0.001'], ['999', '0.999'], ['-999', '-0.999'],
  ['1000', '1'], ['1500', '1.5'], ['-1500', '-1.5'],
  ['9007199254740993', '9,007,199,254,740.993'],
  ['-9223372036854775807', '-9,223,372,036,854,775.807'],
]) checkCanonical(formatCanonicalShareLots(shares) === lots, 'canonical daily lots must preserve every digit and sign')
for (const [horizon, maximum, expected] of [
  [5, '46116860184273879035', '46,116,860,184,273,879.035'],
  [20, '184467440737095516140', '184,467,440,737,095,516.14'],
] as const) {
  checkCanonical(formatCanonicalShareLots(maximum, horizon) === expected, 'positive horizon boundary')
  checkCanonical(formatCanonicalShareLots('-' + maximum, horizon) === '-' + expected, 'negative horizon boundary')
  checkCanonical(formatCanonicalShares(maximum, horizon) !== null && formatCanonicalShareLots(maximum) === null, 'window sum is valid beyond the daily range')
}
for (const [value, horizon] of [['9223372036854775808', 1], ['46116860184273879036', 5], ['184467440737095516141', 20]] as const) {
  checkCanonical(formatCanonicalShareLots(value, horizon) === null && formatCanonicalShareLots('-' + value, horizon) === null, 'over-limit signed quantities are rejected')
}
for (const value of [null, undefined, true, 1, '', '01', '-0', '+1', ' 1', '1 ', '1\n', '1\r', '1\r\n', '1\t', '1\u2028', '1\u2029', '1.0', '1e3', '1,000', '９', '9'.repeat(1000)]) {
  checkCanonical(formatCanonicalShareLots(value, 20) === null && formatCanonicalShares(value, 20) === null, 'malformed canonical text must never be normalized or rounded')
}
checkCanonical(formatCanonicalShareLots('-1', 1, true) === null && formatCanonicalShares('-1', 1, true) === null, 'negative gross shares are rejected')
for (const value of [1.5, 9007199254740992, NaN, Infinity]) {
  checkCanonical(formatTableChip(value, 'twse_t86') === '' && formatShareLots(value) === '待核實' && formatSignedShareLots(value) === '待核實', 'numeric share flows reject fractional and unsafe values')
}
checkCanonical(formatTableChip(1, 'tpex_3insti') === '+0.001' && formatTableChip(-1, 'twse_t86') === '-0.001', 'legacy safe one-share flows remain exact')
checkCanonical(formatTableChip(1250, 'tpex_margin', true) === '+1,250' && formatTableChip(1250, 'tpex_3insti+tpex_margin', true) === '+1,250', 'verified margin source is already lots')
checkCanonical(formatTableChip(1, 'mixed') === '' && formatTableChip(1, 'twse_t86+unknown') === '', 'unknown units cannot claim lots')
export const unitLotsCanonicalChecks = canonicalChecks
console.log('units canonical lots', canonicalChecks, 'checks passed')
