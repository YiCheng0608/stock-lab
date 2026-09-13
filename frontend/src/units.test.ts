import { formatShareLots, formatShareQuantity, formatSignedShareLots, formatSourceAwareShareLots, formatVolumeLots, isVerifiedChipFlowSource, isVerifiedMarginSource, isVerifiedShareSource, sharesFromUnit } from './units'

if (sharesFromUnit('lot', 1) !== 1000) throw new Error('one lot must equal 1000 shares')
if (sharesFromUnit('lot', 2) !== 2000) throw new Error('lot conversion must be exact')
if (sharesFromUnit('odd_lot', 999) !== 999) throw new Error('odd-lot conversion must preserve shares')
if (formatShareQuantity(1000) !== '1 張') throw new Error('1000 shares should display as one lot')
if (formatShareQuantity(1500) !== '1 張 500 股') throw new Error('mixed holdings should show lots and remainder')
if (formatShareQuantity(999) !== '999 股（零股）') throw new Error('odd-lot holdings should show shares')
if (formatShareLots(1500) !== '1.5 張') throw new Error('share volume should display fractional lots')
if (formatShareLots(-500) !== '-0.5 張') throw new Error('negative share flow should preserve sign')
if (formatShareLots(1000.25) !== '1 張') throw new Error('share volume should cap display precision at three decimals')
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
