import { isValidElement } from 'react'
import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StrategyVersionCard, StrategyVersionList, backtestGroupKey } from './StrategyVersionCard'
import type { BacktestGroup, StrategyRow } from '../types'

// Standalone regression module (no browser, no server, no network). The server
// renderer never reports duplicate keys, so key uniqueness is asserted on the
// keys of the elements the list produces, with the old name+version key as a
// control that the fixture really collides.
const check = (condition: boolean, message: string) => { if (!condition) throw new Error(message) }

const V1 = 'institutional-flow/v1-shares-per-twd-turnover'
const V2 = 'institutional-flow/v2-shares-per-share-volume'
const UNCLASSIFIED = 'unclassified/empty_snapshot'

const strategy = (id: number, name: string, formula_version: string, active: boolean): StrategyRow => ({
  id, name, version: '1.0.0', formula_version, kind: 'breakout', active, config: {},
  canonical_config_snapshot: { formula: formula_version }, created_at: null,
})
const rows = [
  strategy(7, 'breakout_v1', V1, false),
  strategy(9, 'breakout_v1', V2, true),
  strategy(12, 'breakout_v1', UNCLASSIFIED, false),
  strategy(13, 'pullback_v1', V2, true),
]
const labelFor = (name: string) => (name === 'breakout_v1' ? '突破條件' : name === 'pullback_v1' ? '回踩條件' : '策略條件')
const badgeFor = (item: StrategyRow) => <span className="pill">{item.active ? 'on' : 'off'}</span>
const count = (haystack: string, needle: string) => haystack.split(needle).length - 1

check(new Set(rows.map((item) => item.name + item.version)).size < rows.length, 'fixture must reproduce the old name+version key collision')

for (const variant of ['condition', 'panel'] as const) {
  const list = StrategyVersionList({ items: rows, variant, labelFor, badgeFor })
  const children = (list.props as { children: ReactNode[] }).children
  check(Array.isArray(children) && children.length === rows.length, `${variant}: one card per row`)
  const keys = children.map((child) => (isValidElement(child) ? child.key : null))
  check(keys.every((key) => key !== null) && new Set(keys).size === rows.length, `${variant}: sibling keys are unique`)
  check(keys.join(',') === rows.map((item) => String(item.id)).join(','), `${variant}: key is the row id`)

  const html = renderToStaticMarkup(<StrategyVersionList items={rows} variant={variant} labelFor={labelFor} badgeFor={badgeFor} />)
  check(count(html, '公式版本 ') === rows.length && count(html, '規則版本 1.0.0') === rows.length, `${variant}: every card shows rule and formula version`)
  for (const formula of [V1, V2, UNCLASSIFIED]) check(html.includes('公式版本 ' + formula), `${variant}: formula ${formula} shown as stored`)

  const cards = rows.map((item) => renderToStaticMarkup(<StrategyVersionCard item={item} label={labelFor(item.name)} variant={variant} badge={badgeFor(item)} />))
  check(new Set(cards).size === rows.length, `${variant}: same name/version cards are distinguishable`)
  check(cards[0] !== cards[1] && cards[0].includes(V1) && !cards[0].includes(V2) && cards[1].includes(V2) && !cards[1].includes(V1), `${variant}: each card shows only its own formula`)
  check(cards[2].includes('公式版本 ' + UNCLASSIFIED), `${variant}: unclassified formula shown verbatim`)
  check(variant === 'condition' ? cards[0].includes('condition-head') && cards[0].includes('class="pill"') : cards[0].startsWith('<article class="panel">') && !cards[0].includes('class="pill"'), `${variant}: card structure`)
  check(renderToStaticMarkup(<StrategyVersionList items={[]} variant={variant} labelFor={labelFor} />) === '', `${variant}: empty list renders nothing`)
}

const group = (strategy: string, version: string, instrument_type: string, horizon: number): BacktestGroup => ({
  strategy, version, instrument_type, horizon, sample: 0, comparable: 0, incomparable: 0, assessment: 'unknown', interpretation: '',
})
const groups = [
  group('breakout_v1', '1.0.0', 'stock', 5),
  group('breakout_v1', '1.1.0', 'stock', 5),
  group('breakout_v1', '1.0.0', 'etf', 5),
  group('breakout_v1', '1.0.0', 'stock', 10),
]
check(new Set(groups.map((row) => row.strategy + row.instrument_type + row.horizon)).size < groups.length, 'backtest fixture must reproduce the old key collision')
check(new Set(groups.map(backtestGroupKey)).size === groups.length, 'backtest keys are unique when two versions coexist')
check(backtestGroupKey(group('ab', 'c', 'stock', 5)) !== backtestGroupKey(group('a', 'bc', 'stock', 5)), 'backtest key keeps field boundaries')
