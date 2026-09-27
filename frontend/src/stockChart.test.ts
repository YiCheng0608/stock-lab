import { buildStockChartOption, dataZoomEventWindow, formatStockTooltip, movingAverage, prepareStockChartData, rangeStartIndex, windowForRange } from './stockChart'
import type { Bar } from './types'

function expect(condition: boolean, message: string): void {
  if (!condition) throw new Error(message)
}

function bar(date: string, close: number, overrides: Partial<Bar> = {}): Bar {
  return {
    date,
    open: close - 1,
    high: close + 1,
    low: close - 2,
    close,
    adj_close: close,
    volume: 1000,
    turnover: 1000,
    turnover_status: 'available',
    turnover_reason: null,
    source: 'twse',
    data_as_of: '2026-09-12T00:00:00+00:00',
    collected_at: '2026-09-12T00:00:00+00:00',
    is_suspended: false,
    ...overrides,
  }
}

const prepared = prepareStockChartData([
  bar('2026-09-03', 12),
  bar('2026-09-01', 10),
  bar('2026-09-02', 11),
])
expect(prepared.bars.map((row) => row.date).join(',') === '2026-09-01,2026-09-02,2026-09-03', 'chart data sorts by trading date')
expect(prepared.points.length === 3, 'valid rows remain available')
expect(prepared.invalidRows === 0, 'valid rows are not rejected')
expect(prepareStockChartData(null).points.length === 0, 'empty payloads render no synthetic bars')
expect(rangeStartIndex(120, 30) === 90, 'range control starts at the requested window')
expect(rangeStartIndex(3, 30) === 0, 'short history starts at zero')
expect(movingAverage([1, 2, 3, 4], 3).join(',') === ',,2,3', 'moving average waits for a full window')
expect(movingAverage([1, null, 3], 2).every((value) => value === null), 'missing values do not get filled into an average')

const duplicate = prepareStockChartData([bar('2026-09-01', 10), bar('2026-09-01', 12), bar('2026-09-02', 13)])
expect(duplicate.points.length === 2 && duplicate.points[0].date === '2026-09-01' && duplicate.points[0].bar === null && duplicate.points[1].bar?.close === 13, 'duplicate dates remain locatable but are not guessed')
expect(duplicate.duplicateRows === 2 && duplicate.duplicateDates[0] === '2026-09-01', 'duplicate diagnostics retain the exact date')

const malformed = prepareStockChartData([
  bar('2026-09-01', 10, { high: Number.NaN }),
  bar('2026-02-30', 10),
  null as unknown as Bar,
])
expect(malformed.points.length === 1 && malformed.points[0].bar === null && malformed.invalidRows === 3, 'invalid and malformed rows fail closed with a locatable date slot')

const enough = prepareStockChartData(Array.from({ length: 60 }, (_, index) => bar(new Date(Date.UTC(2026, 0, index + 1)).toISOString().slice(0, 10), index + 10)))
expect(enough.ma20[19] != null && enough.ma60[59] != null, 'MA20 and MA60 require enough same-source rows')
expect(enough.ma20[18] === null && enough.ma60[58] === null, 'MA values remain absent before their full windows')

const unknownBasis = prepareStockChartData([bar('2026-09-01', 10, { source: 'unknown' }), bar('2026-09-02', 11, { source: 'unknown' })])
expect(unknownBasis.maStatus === 'basis_unknown' && unknownBasis.ma20.every((value) => value === null), 'unknown source does not produce asserted moving averages')

const gapRows = Array.from({ length: 41 }, (_, index) => {
  const date = new Date(Date.UTC(2026, 0, index + 1)).toISOString().slice(0, 10)
  return index === 10 ? bar(date, 20, { close: Number.NaN }) : bar(date, index + 10)
})
const gap = prepareStockChartData(gapRows)
expect(gap.points.length === 41 && gap.points[10].bar === null && gap.maStatus === 'data_gap', 'invalid OHLC keeps a null date slot for moving-average gaps')
expect(gap.ma20[29] === null && gap.ma20[30] != null, 'moving averages restart after a data gap instead of crossing it')

const knownGap = prepareStockChartData(gapRows.slice(0, 20).map((row) => row), { knownGapDates: ['2026-01-21'] })
expect(knownGap.points.some((point) => point.date === '2026-01-21' && point.bar === null), 'coverage-provided missing dates become explicit null slots')

const tooltip = formatStockTooltip(prepared, { componentType: 'series', componentSubType: 'line', componentIndex: 0, name: '2026-09-01', dataIndex: 0, data: [9, 10, 8, 11], value: [9, 10, 8, 11], $vars: [] })
expect(tooltip.includes('2026-09-01') && tooltip.includes('成交量（張）') && tooltip.includes('成交量（張）：1') && !tooltip.includes('1 張'), 'tooltip contains OHLCV text in lots')
expect(!tooltip.includes('<script>'), 'tooltip does not pass through executable markup')

const negativeVolume = prepareStockChartData([bar('2026-09-04', 13, { volume: -1000 })])
const negativeTooltip = formatStockTooltip(negativeVolume, { componentType: 'series', dataIndex: 0 })
expect(negativeTooltip.includes('待核實') && !negativeTooltip.includes('-1 張'), 'negative volume tooltip fails closed instead of displaying a negative lot count')
const negativeOption = buildStockChartOption(negativeVolume, 'all')
const negativeVolumeSeries = Array.isArray(negativeOption.series) ? negativeOption.series.find((series) => series && typeof series === 'object' && 'name' in series && series.name === '成交量') : null
expect(Boolean(negativeVolumeSeries && Array.isArray(negativeVolumeSeries.data) && negativeVolumeSeries.data[0] && typeof negativeVolumeSeries.data[0] === 'object' && 'value' in negativeVolumeSeries.data[0] && negativeVolumeSeries.data[0].value === null), 'negative volume bars are omitted from the chart series')

const option = buildStockChartOption(enough, 30)
expect(Array.isArray(option.dataZoom) && option.dataZoom.length === 2, 'chart exposes inside and slider zoom')
expect(Array.isArray(option.series) && option.series.some((series) => series && 'type' in series && series.type === 'candlestick'), 'chart uses candlestick series')
expect(windowForRange(120, 30).start === 90 && windowForRange(120, 30).end === 119, 'range window has inclusive endpoints')
expect(dataZoomEventWindow({ startValue: 3, endValue: 7 }, 10)?.start === 3 && dataZoomEventWindow({ startValue: 3, endValue: 7 }, 10)?.end === 7, 'dataZoom startValue/endValue update the metadata window')
expect(dataZoomEventWindow({ batch: [{ startValue: 2, endValue: 5 }] }, 10)?.end === 5, 'batched dataZoom events are supported')
