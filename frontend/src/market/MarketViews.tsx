import type { ReactNode } from 'react'

import { DataTable, DateBadge, cx, type Column } from '../components/ui'
import type { IndexRow, MarketOverview, MarketOverviewExchange, StockBarsInterval, StockBarsResponse, TaiexMa60 } from '../types'
import { formatFixed } from '../units'
import { isFiniteNumber } from '../stock/stockBars'
import { StockBarsChart } from '../stock/StockBarsChart'
import {
  EXCHANGES,
  FRED_ATTRIBUTION,
  INDEX_CHART_ID,
  INDEX_CHART_TITLE_ID,
  INDEX_SELECT_HINT,
  INDEX_SOURCE_NOTE,
  INDEX_SPECS,
  INDEX_TABLE_TITLE,
  MA60_LABEL,
  ROLL_LABEL,
  SHORT_SCOPE_LABELS,
  TAIFEX_ATTRIBUTION,
  TW_GROUP_TITLE,
  TX_ROLL_NOTE,
  available,
  changeTone,
  chartTitle,
  collectedSinceText,
  contractText,
  dash,
  futuresLatestText,
  indexAvailable,
  indexDateText,
  indexMa60Cell,
  indexMissingText,
  indexRow,
  indexTableNotes,
  ma60MissingText,
  ma60PositionParts,
  ma60SegmentsText,
  marketOverviewNotes,
  missingText,
  rollNote,
  signedPercent,
  usGroupTitle,
  type ExchangeSpec,
  type IndexSpec,
} from './marketOverview'

// The market page blocks (/market, Issue 549/561/564): 大盤概況 with 加權指數與季線, then 指數總表 and the shared daily K
// chart of the selected row, in the order DESIGN_SYSTEM §4 fixes.
// Copy and units follow UI_COPY_SPEC §11.

function IndexWidget({ spec, row }: { spec: ExchangeSpec; row: MarketOverviewExchange | null }) {
  const index = row?.index
  return (
    <div className="market-widget market-index" data-exchange={spec.exchange}>
      <div className="market-widget-head"><span className="market-widget-label">{spec.index}</span><span className="market-widget-unit">點</span></div>
      {index ? <>
        <div className="market-widget-value">{dash(index.close, 2)}</div>
        <div className={cx('market-widget-change', changeTone(index.change))}>{isFiniteNumber(index.change) ? formatFixed(index.change, 2, true) : '—'}（{signedPercent(index.change_pct)}）</div>
      </> : <div className="market-widget-empty">{missingText(spec)}</div>}
    </div>
  )
}

// Turnover is stored in 元 and shown in 億元 with two decimals, followed by its short scope.
function turnoverText(row: MarketOverviewExchange): ReactNode {
  const { value, scope, scope_label: scopeLabel } = row.turnover ?? { value: null, scope: null, scope_label: null }
  const short = (scope ? SHORT_SCOPE_LABELS[scope] : undefined) ?? scopeLabel
  return <>{isFiniteNumber(value) ? formatFixed(value / 1e8, 2) : '—'}{short && <> <span className="market-row-scope">{short}</span></>}</>
}

function breadthText(row: MarketOverviewExchange): string {
  const breadth = row.breadth
  if (!breadth) return '—'
  const limits = breadth.limit_up == null && breadth.limit_down == null ? '' : `（${dash(breadth.limit_up)}／${dash(breadth.limit_down)}）`
  return `上漲 ${dash(breadth.advancers)} · 下跌 ${dash(breadth.decliners)} · 平盤 ${dash(breadth.unchanged)}${limits}`
}

function DualWidget({ className, label, unit, overview, value }: { className: string; label: string; unit: string; overview: MarketOverview | undefined; value: (row: MarketOverviewExchange) => ReactNode }) {
  return (
    <div className={cx('market-widget market-widget-dual', className)}>
      <div className="market-widget-head"><span className="market-widget-label">{label}</span><span className="market-widget-unit">{unit}</span></div>
      {EXCHANGES.map((spec) => {
        const row = available(overview, spec.exchange)
        return row
          ? <div key={spec.exchange} className="market-row" data-exchange={spec.exchange}><span className="market-row-label">{spec.label}</span> {value(row)}</div>
          : <div key={spec.exchange} className="market-row market-row-empty" data-exchange={spec.exchange}>{missingText(spec)}</div>
      })}
    </div>
  )
}

// One bar of four widgets: the two indexes, turnover and breadth (DESIGN_SYSTEM §5 market-widget, dual-row variant).
export function MarketOverviewView({ overview }: { overview: MarketOverview | undefined }) {
  return (
    <div className="market-overview-grid">
      {EXCHANGES.map((spec) => <IndexWidget key={spec.exchange} spec={spec} row={available(overview, spec.exchange)} />)}
      <DualWidget className="market-turnover" label="成交金額" unit="億元" overview={overview} value={turnoverText} />
      <DualWidget className="market-breadth" label="漲跌家數（股票）" unit="括號為漲停／跌停" overview={overview} value={breadthText} />
    </div>
  )
}

// 加權指數與季線 (Issue 561): one neutral strip under the four widgets — the close, its date, the position against MA60 and
// the latest runs above it; without a position only the reason. No up/down colors: background, not a signal.
export function TaiexMa60View({ item }: { item: TaiexMa60 | undefined }) {
  const missing = ma60MissingText(item)
  const parts = item ? ma60PositionParts(item) : null
  const segments = item ? ma60SegmentsText(item) : null
  return (
    <div className="market-ma60" data-status={item?.status ?? 'missing'}>
      <div className="market-widget-head"><span className="market-widget-label">{MA60_LABEL}</span><span className="market-widget-unit">點</span></div>
      {parts
        ? <div className="market-ma60-line">{parts.lead}<strong className="market-ma60-position">{parts.position}</strong>{parts.ma60}</div>
        : <div className="market-widget-empty market-ma60-empty">{missing}</div>}
      {segments && <div className="market-ma60-segments">{segments}</div>}
    </div>
  )
}

export function MarketOverviewPanel({ overview }: { overview: MarketOverview | undefined }) {
  return (
    <section className="panel market-panel market-overview" aria-labelledby="market-overview-title">
      <div className="panel-head">
        <h2 id="market-overview-title">大盤概況</h2>
        <DateBadge date={overview?.trading_date ?? null} />
        <details className="data-explanation">
          <summary>資料說明</summary>
          {marketOverviewNotes(overview).map((line) => <div key={line}>{line}</div>)}
        </details>
      </div>
      <MarketOverviewView overview={overview} />
      <TaiexMa60View item={overview?.taiex_ma60} />
    </section>
  )
}

// ---- 指數總表, Issue 564 --------------------------------------------------------------------------------

type TableRow = { spec: IndexSpec; row: IndexRow | null }

const priceCell = ({ spec, row }: TableRow) => indexAvailable(row) ? dash(row.close, spec.digits) : '—'

function ChangeCell({ spec, row }: TableRow) {
  if (!indexAvailable(row)) return <>—</>
  // A TX roll day has no change; the cell says why instead of a blank (decision 6725073156), the note under the table says more.
  if (row.change_status === 'contract_roll') return <span className="market-index-muted">{ROLL_LABEL}</span>
  return <span className={changeTone(row.change) ?? undefined}>{isFiniteNumber(row.change) ? formatFixed(row.change, spec.digits, true) : '—'}</span>
}

function PercentCell({ row }: TableRow) {
  if (!indexAvailable(row)) return <>—</>
  if (row.change_status === 'contract_roll') return <span className="market-index-muted">{ROLL_LABEL}</span>
  // The tone reads the shown percent, not the ratio that rounds to 0.00 (summaryItems).
  const percent = isFiniteNumber(row.change_pct) ? row.change_pct * 100 : null
  return <span className={changeTone(percent) ?? undefined}>{signedPercent(row.change_pct)}</span>
}

function DateCell({ row }: TableRow) {
  if (!indexAvailable(row)) return <span className="market-index-missing">{indexMissingText(row)}</span>
  const { date, flag } = indexDateText(row)
  return <>{date}{flag && <> <span className={cx('market-index-flag', row.freshness === 'stale' && 'market-index-stale')}>{flag}</span></>}</>
}

function Ma60Cell({ spec, row }: TableRow) {
  const cell = indexMa60Cell(row, spec.digits)
  return cell.kind === 'position'
    ? <><strong className="market-index-position">{cell.position}</strong> <span className="market-index-muted">{cell.ma60}</span></>
    : <span className="market-index-muted">{cell.text}</span>
}

function NameCell({ spec, row, selected }: TableRow & { selected: boolean }) {
  const contract = contractText(row)
  return (
    <>
      {/* A native button: Tab reaches it and Enter or Space clicks it; the click bubbles to the row's onClick. */}
      <button type="button" className="market-index-select" aria-pressed={selected} aria-controls={INDEX_CHART_ID}>{spec.name}</button>
      {contract && <> <span className="market-index-sub">{contract}</span></>}
    </>
  )
}

function indexColumns(selected: string): ReadonlyArray<Column<TableRow>> {
  return [
    { key: 'name', header: '指數', cellClassName: 'market-index-name', cell: (item) => <NameCell {...item} selected={item.spec.key === selected} /> },
    { key: 'close', header: '收盤（點）', num: true, cellClassName: 'market-index-close', cell: priceCell },
    { key: 'change', header: '漲跌', num: true, cellClassName: 'market-index-change', cell: (item) => <ChangeCell {...item} /> },
    { key: 'pct', header: '漲跌幅', num: true, cellClassName: 'market-index-pct', cell: (item) => <PercentCell {...item} /> },
    { key: 'date', header: '資料日', cellClassName: 'market-index-date', cell: (item) => <DateCell {...item} /> },
    { key: 'ma60', header: '相對季線（MA60）', cellClassName: 'market-index-ma60', cell: (item) => <Ma60Cell {...item} /> },
    { key: 'source', header: '來源', wideOnly: true, cellClassName: 'market-index-source', cell: ({ row, spec }) => row?.source?.label ?? (spec.group === 'us' ? 'FRED' : '—') },
  ]
}

// The seven rows in two groups (台股, 美股), one table at every width (DESIGN_SYSTEM §4 大盤頁: 640px and below each row
// is two lines, no horizontal scroll). A click anywhere on a row, or Enter on its name button, selects it.
export function IndexTableView({ overview, selected, onSelect }: { overview: MarketOverview | undefined; selected: string; onSelect: (key: string) => void }) {
  const rows: TableRow[] = INDEX_SPECS.map((spec) => ({ spec, row: indexRow(overview, spec.key) }))
  const usTitle = usGroupTitle(overview)
  const roll = rollNote(indexRow(overview, 'tx'))
  return (
    <>
      <DataTable
        wrapClassName="market-index-table"
        columns={indexColumns(selected)}
        rows={rows}
        rowKey={({ spec }) => spec.key}
        groupTitle={({ spec }, index) => index === 0 || rows[index - 1].spec.group !== spec.group ? (spec.group === 'tw' ? TW_GROUP_TITLE : usTitle) : null}
        rowProps={({ spec }) => ({
          className: cx('market-index-row', spec.key === selected && 'is-selected'),
          'data-index': spec.key,
          'aria-current': spec.key === selected ? 'true' : undefined,
          onClick: () => onSelect(spec.key),
        })}
      />
      {roll && <p className="small-note market-index-note">{roll}</p>}
      <p className="small-note market-index-note">{INDEX_SOURCE_NOTE}</p>
      <p className="small-note market-index-note">{INDEX_SELECT_HINT}</p>
    </>
  )
}

export function IndexTablePanel({ overview, selected, onSelect }: { overview: MarketOverview | undefined; selected: string; onSelect: (key: string) => void }) {
  return (
    <section className="panel market-panel market-indexes" aria-labelledby="market-indexes-title">
      <div className="panel-head">
        <h2 id="market-indexes-title">{INDEX_TABLE_TITLE}</h2>
        <DateBadge date={overview?.trading_date ?? null} />
        <details className="data-explanation">
          <summary>資料說明</summary>
          {indexTableNotes(overview).map((line) => <div key={line}>{line}</div>)}
        </details>
      </div>
      <IndexTableView overview={overview} selected={selected} onSelect={onSelect} />
    </section>
  )
}

// ---- 共用 K 線圖 ----------------------------------------------------------------------------------------

// The TX chart's lines under the K line: the latest contract month, open interest and settlement price, when the
// history starts, the roll rule and the open-data attribution (Issue 552; UI_COPY_SPEC §11).
function FuturesFooter({ data }: { data: StockBarsResponse | undefined }) {
  const latest = futuresLatestText(data)
  const since = collectedSinceText(data)
  return (
    <div className="market-chart-footer" data-exchange="TAIFEX">
      {latest && <p className="market-chart-contract">{latest}</p>}
      <p>{since ? `${since}；` : ''}{TX_ROLL_NOTE}</p>
      <p>{TAIFEX_ATTRIBUTION}</p>
    </div>
  )
}

// A US chart: the FRED attribution and the series' copyright notice (FRED terms: keep the notices intact).
export function UsChartFooter({ row }: { row: IndexRow | null }) {
  return (
    <div className="market-chart-footer" data-exchange="US">
      <p>{FRED_ATTRIBUTION}</p>
      {row?.source?.copyright && <p>{row.source.copyright}</p>}
    </div>
  )
}

// The selected row's chart: the stock page's StockBarsChart (same period switch, indicators and empty states), titled
// 「{名稱}日線」; a US index is a close line with the chart's own note (DESIGN_SYSTEM §4 大盤頁, §6).
export function MarketChartView({ spec, row, interval, onIntervalChange, data, loading, error }: {
  spec: IndexSpec
  row: IndexRow | null
  interval: StockBarsInterval
  onIntervalChange: (interval: StockBarsInterval) => void
  data: StockBarsResponse | undefined
  loading: boolean
  error: unknown
}) {
  const footer = spec.instrumentType === 'futures' ? <FuturesFooter data={data} /> : spec.group === 'us' ? <UsChartFooter row={row} /> : undefined
  return (
    <div className="market-chart" id={INDEX_CHART_ID} data-chart={spec.key}>
      <StockBarsChart interval={interval} onIntervalChange={onIntervalChange} data={data} loading={loading} error={error}
        instrumentType={spec.instrumentType} title={chartTitle(spec)} titleId={INDEX_CHART_TITLE_ID} footer={footer} />
    </div>
  )
}
