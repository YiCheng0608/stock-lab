import type { ReactNode } from 'react'
import type { BacktestGroup, StrategyRow } from '../types'

export type StrategyVersionVariant = 'condition' | 'panel'

// The delimiter keeps field boundaries from running together in the key.
export const backtestGroupKey = (row: Pick<BacktestGroup, 'strategy' | 'version' | 'instrument_type' | 'horizon'>): string =>
  [row.strategy, row.version, row.instrument_type, row.horizon].join('|')

type CardProps = {
  item: Pick<StrategyRow, 'version' | 'formula_version' | 'canonical_config_snapshot'>
  label: string
  variant: StrategyVersionVariant
  badge?: ReactNode
}

export function StrategyVersionCard({ item, label, variant, badge }: CardProps) {
  const formula = <div className="small-note">公式版本 {item.formula_version}</div>
  const details = <details className="technical-details"><summary>查看規則設定</summary><pre>{JSON.stringify(item.canonical_config_snapshot, null, 2)}</pre></details>
  if (variant === 'condition') {
    return <div className="condition"><div className="condition-head"><strong>{label} · 規則版本 {item.version}</strong>{badge}</div>{formula}{details}</div>
  }
  return <article className="panel"><div className="position-head"><strong>{label}</strong><span>規則版本 {item.version}</span></div>{formula}{details}</article>
}

type ListProps = {
  items: StrategyRow[]
  variant: StrategyVersionVariant
  labelFor: (name: string) => string
  badgeFor?: (item: StrategyRow) => ReactNode
}

// The same name/version can have several rows that differ only by
// formula_version, so `id` is the only unique key.
export function StrategyVersionList({ items, variant, labelFor, badgeFor }: ListProps) {
  return <>{items.map((item) => <StrategyVersionCard key={item.id} item={item} label={labelFor(item.name)} variant={variant} badge={badgeFor?.(item)} />)}</>
}
