import type { InstrumentDetail, StockDetailChip } from './types'

const states = ['known', 'missing', 'invalid']
const numbers = ['foreign_buy', 'trust_buy', 'dealer_buy', 'margin_balance', 'margin_change', 'short_balance', 'borrowed_sell', 'day_trade_ratio']
const chipCore = ['id', 'instrument_id', 'trading_date', ...numbers.slice(0, 5)]
const featureCore = ['id', 'instrument_id', 'trading_date', 'features_json']
const featureFields = [...featureCore, 'source', 'created_at', 'ma20', 'ma60']
const chipFields = [...chipCore, ...numbers.slice(5), 'source', 'data_as_of', 'collected_at', 'raw_payload_id']
const object = (value: unknown): value is Record<string, unknown> => value != null && typeof value === 'object' && !Array.isArray(value)
const state = (value: unknown): value is string => typeof value === 'string' && states.includes(value)
const identity = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value > 0
const count = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
const finite = (value: unknown) => typeof value === 'number' && Number.isFinite(value)
const nullableNumber = (value: unknown) => value === null || finite(value)
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every((item) => typeof item === 'string') && new Set(value).size === value.length
const text = (value: unknown) => typeof value === 'string' && value.length > 0 && value.length <= 240 && [...value].length <= 120
  && value.replace(/^[ \t\r\n\ufeff]+|[ \t\r\n\ufeff]+$/g, '').length > 0 && !/[\x00-\x1f\x7f]/.test(value) && unicode(value)
// Parsed projections use normalized JS spelling. This generous finite budget
// allows valid 65536-byte raw JSON numbers/Unicode to change spelling after parse.
const PROJECTED_JSON_BYTES = 524288

function unicode(value: string): boolean {
  for (let index = 0; index < value.length; index++) {
    const unit = value.charCodeAt(index)
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = value.charCodeAt(++index)
      if (!(next >= 0xdc00 && next <= 0xdfff)) return false
    } else if (unit >= 0xdc00 && unit <= 0xdfff) return false
  }
  return true
}

const dateOnly = (value: unknown): value is string => typeof value === 'string' && /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value)
  && Number(value.slice(0, 4)) > 0 && !Number.isNaN(new Date(value + 'T00:00:00Z').getTime())
  && new Date(value + 'T00:00:00Z').toISOString().slice(0, 10) === value
const instant = (value: unknown) => typeof value === 'string'
  && /^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})?$/.test(value)
  && dateOnly(value.slice(0, 10)) && Number(value.slice(11, 13)) <= 23 && Number(value.slice(14, 16)) <= 59 && Number(value.slice(17, 19)) <= 59
  && (!/[+-][0-9]{2}:[0-9]{2}$/.test(value) || (Number(value.slice(-5, -3)) <= 23 && Number(value.slice(-2)) <= 59))

function jsonObject(value: unknown): value is Record<string, unknown> {
  if (!object(value)) return false
  const pending: Array<[unknown, number]> = [[value, 0]]
  let nodes = 0, bytes = 0
  while (pending.length) {
    const [item, depth] = pending.pop()!
    if (++nodes > 16384 || depth > 32) return false
    if (typeof item === 'number' && !finite(item)) return false
    if (typeof item === 'string') {
      if (item.length > PROJECTED_JSON_BYTES) return false
      bytes += 2
      for (let index = 0; index < item.length; index++) {
        const unit = item.charCodeAt(index)
        if (unit >= 0xd800 && unit <= 0xdbff) {
          const next = item.charCodeAt(++index)
          if (!(next >= 0xdc00 && next <= 0xdfff)) return false
          bytes += 4
        } else if (unit >= 0xdc00 && unit <= 0xdfff) return false
        else bytes += unit < 32 ? [8, 9, 10, 12, 13].includes(unit) ? 2 : 6
          : unit === 34 || unit === 92 ? 2 : unit <= 127 ? 1 : unit <= 2047 ? 2 : 3
        if (bytes > PROJECTED_JSON_BYTES) return false
      }
    } else if (item === null) bytes += 4
    else if (typeof item === 'number') bytes += JSON.stringify(item).length
    else if (typeof item === 'boolean') bytes += item ? 4 : 5
    if (Array.isArray(item)) {
      if (item.length > 16384 - nodes - pending.length) return false
      bytes += 2 + Math.max(0, item.length - 1)
      for (const child of item) pending.push([child, depth + 1])
    } else if (object(item)) {
      const keys = Object.keys(item)
      if (keys.length * 2 > 16384 - nodes - pending.length) return false
      bytes += 2 + keys.length + Math.max(0, keys.length - 1)
      for (const key of keys) { pending.push([key, depth + 1]); pending.push([item[key], depth + 1]) }
    } else if (item !== null && !['string', 'number', 'boolean'].includes(typeof item)) return false
    if (bytes > PROJECTED_JSON_BYTES) return false
  }
  return true
}

function rowRead(value: unknown, schema: string[], essential: string[], extraInvalid: string[] = []): boolean {
  if (!object(value) || !state(value.status) || !strings(value.invalid_fields) || !strings(value.missing_fields) || !object(value.metadata_fields)) return false
  const fields = value.metadata_fields
  if (Object.keys(fields).length !== schema.length || !schema.every((key) => state(fields[key]))) return false
  const invalid = [...new Set([...essential, ...extraInvalid])].filter((key) => fields[key] === 'invalid').sort()
  const missing = essential.filter((key) => fields[key] === 'missing').sort()
  return value.invalid_fields.join() === invalid.join() && value.missing_fields.join() === missing.join()
    && value.status === (invalid.length ? 'invalid' : missing.length ? 'missing' : 'known')
}

function consistent(fields: Record<string, unknown>, key: string, value: unknown, valid: (value: unknown) => boolean): boolean {
  return state(fields[key]) && (fields[key] === 'known' ? valid(value) : value === null)
}

function envelope(value: unknown, rows: Record<string, unknown>[], limit: number): boolean {
  if (!object(value) || value.version !== 'stock-independent-read/v1' || !state(value.status) || value.window_limit !== limit
    || value.verification !== 'stored_value_syntax_only' || !count(value.candidate_count) || value.candidate_count !== rows.length || rows.length > limit
    || !count(value.scanned_count) || !count(value.future_count) || !count(value.unlocated_count)
    || value.future_count > value.scanned_count || value.unlocated_count > value.scanned_count - value.future_count
    || value.candidate_count !== Math.min(limit, value.scanned_count - value.future_count)
    || !Array.isArray(value.candidate_order) || value.candidate_order.length !== rows.length
    || (value.unlocated_count === 0 ? value.unlocated_id !== null : !identity(value.unlocated_id))) return false
  const ids = new Set<number>()
  for (const [index, row] of rows.entries()) {
    if (!identity(row.id) || ids.has(row.id) || value.candidate_order[index] !== row.id) return false
    ids.add(row.id)
  }
  if (value.unlocated_count === 0 && rows.some((row) => row.trading_date === null || row.date === null)) return false
  const statuses = rows.map((row) => (row.row_read as Record<string, unknown>).status)
  const expected = value.unlocated_count || statuses.includes('invalid') ? 'invalid' : !rows.length || statuses.includes('missing') ? 'missing' : 'known'
  return value.status === expected
}

export function validStockFeatureRead(data: InstrumentDetail): boolean {
  const snapshot = data.feature_snapshot
  if (data.feature_read === undefined && snapshot === undefined) {
    return jsonObject(data.features) && ['ma20', 'ma60'].every((key) => data.features[key] === undefined || nullableNumber(data.features[key]))
  }
  if (data.feature_read === undefined || !jsonObject(data.features)) return false
  if (snapshot === null) return Object.keys(data.features).length === 0 && envelope(data.feature_read, [], 1)
  if (!object(snapshot) || !rowRead(snapshot.row_read, featureFields, featureCore, ['ma20', 'ma60'])) return false
  const fields = snapshot.row_read.metadata_fields
  if (!consistent(fields, 'id', snapshot.id, identity) || !consistent(fields, 'instrument_id', snapshot.instrument_id, identity)
    || snapshot.instrument_id !== data.instrument.id || !consistent(fields, 'trading_date', snapshot.trading_date, dateOnly)
    || !consistent(fields, 'source', snapshot.source, text) || !consistent(fields, 'created_at', snapshot.created_at, instant)
    || !consistent(fields, 'features_json', snapshot.features_json, jsonObject)) return false
  const features = snapshot.features_json
  for (const key of ['ma20', 'ma60']) {
    const value = features?.[key] ?? null
    if (!consistent(fields, key, value, finite)) return false
    if (fields[key] !== 'missing' && (!object(features) || !Object.prototype.hasOwnProperty.call(features, key))) return false
  }
  return JSON.stringify(data.features) === JSON.stringify(features ?? {}) && envelope(data.feature_read, [snapshot], 1)
}

export function validStockChipRead(data: InstrumentDetail): boolean {
  if (!Array.isArray(data.chips) || data.chips.length > 120) return false
  const legacy = data.chip_read === undefined
  if (legacy && data.chips.some((row) => object(row) && row.row_read !== undefined)) return false
  for (const row of data.chips) {
    const raw = row as unknown as Record<string, unknown>
    if (!object(row) || !(row.date === null || dateOnly(row.date)) || !(row.source === null || text(row.source))
      || !numbers.every((key) => nullableNumber(raw[key])) || !['data_as_of', 'collected_at'].every((key) => raw[key] === null || instant(raw[key]))) return false
    if (legacy) { if (!dateOnly(row.date)) return false; continue }
    if (!rowRead(row.row_read, chipFields, chipCore)) return false
    const fields = row.row_read!.metadata_fields
    if (row.instrument_id !== data.instrument.id || !consistent(fields, 'id', row.id, identity)
      || !consistent(fields, 'instrument_id', row.instrument_id, identity) || !consistent(fields, 'raw_payload_id', row.raw_payload_id, identity)
      || !consistent(fields, 'trading_date', row.date, dateOnly) || !consistent(fields, 'source', row.source, text)
      || !numbers.every((key) => consistent(fields, key, raw[key], finite))
      || !['data_as_of', 'collected_at'].every((key) => consistent(fields, key, raw[key], instant))) return false
  }
  const rows = [...data.chips].reverse()
  let previous: StockDetailChip | undefined
  for (const row of rows) {
    if (previous?.date && row.date && (row.date > previous.date || (!legacy && row.date === previous.date && row.id! > previous.id!))) return false
    if (row.date) previous = row
  }
  return legacy || envelope(data.chip_read, rows as unknown as Record<string, unknown>[], 120)
}

export function stockIndependentView(data: InstrumentDetail) {
  const featureValid = validStockFeatureRead(data), chipValid = validStockChipRead(data)
  const featureLocated = data.feature_read === undefined || (featureValid && data.feature_read.status === 'known' && data.feature_read.unlocated_count === 0
    && data.feature_snapshot?.row_read.metadata_fields.trading_date === 'known')
  return { featureValid, chipValid, features: featureValid && featureLocated ? data.features : {},
    chips: chipValid ? data.chips : [], featureStatus: featureValid ? data.feature_read?.status ?? 'known' : 'invalid',
    chipStatus: chipValid ? data.chip_read?.status ?? 'known' : 'invalid' }
}
