import { Link } from 'react-router-dom'

import { Badge, Card, DateBadge, EmptyState, Skeleton, Table } from '../components/ui'
import { AiBadge } from '../news/NewsViews'
import type { CandidateComponentKey, CandidateItem, CandidatesResponse } from '../types'
import {
  CANDIDATE_COMPONENTS,
  CANDIDATE_DISCLAIMER,
  NOTE_DISCLAIMER,
  NOTE_TITLE,
  PARTIAL_NOTE,
  candidateGroupText,
  candidateNoteView,
  candidateSourceText,
  candidateStrategyLabel,
  candidatesState,
  exchangeLabel,
  formatCandidateScore,
  formatDate,
  formatEntryZone,
  formatPrice,
  formatRiskReward,
  formatSubItemValue,
  stockPath,
  subItemLabel,
} from './candidates'

// Daily candidate list (candidate_score_v1, #215): the today section and the stock page panel.
// Copy follows UI_COPY_SPEC §10; reason dots and level colours follow DESIGN_SYSTEM §7.

function errorReason(error: unknown): string {
  return error instanceof Error ? error.message : '請稍後重新整理'
}

function InferenceBadge() {
  return <Badge tone="accent" dot className="badge-compact">推論</Badge>
}

function ComponentScores({ item }: { item: CandidateItem }) {
  const missing = CANDIDATE_COMPONENTS.filter(({ key }) => item.components[key]?.score == null)
  return (
    <>
      <dl className="candidate-components">
        {CANDIDATE_COMPONENTS.map(({ key, label }) => {
          const component = item.components[key]
          return (
            <div key={key} data-component={key}>
              <dt>{label}{component?.inference && <> <InferenceBadge /></>}</dt>
              <dd title={component?.score == null ? component?.null_explanation ?? undefined : undefined}>{formatCandidateScore(component?.score)}</dd>
            </div>
          )
        })}
      </dl>
      {missing.length > 0 && (
        <ul className="candidate-null-notes small-note">
          {missing.map(({ key, label }) => <li key={key}>{label}：{item.components[key]?.null_explanation ?? '無資料'}</li>)}
        </ul>
      )}
    </>
  )
}

function ScoreDetails({ item, open }: { item: CandidateItem; open: boolean }) {
  return (
    <details className="details candidate-details" open={open}>
      <summary>評分細節、資料日期與來源</summary>
      <Table note="分數與 percentile 為 0–100，越高越好（「較低為佳」的子項已反向）；「—」表示無資料，不以 0 計。">
        <thead><tr><th>分項</th><th>子項</th><th className="num">原值</th><th className="num">percentile</th><th className="num">子項權重</th></tr></thead>
        <tbody>
          {CANDIDATE_COMPONENTS.flatMap(({ key, label }) => {
            const component = item.components[key]
            const entries = Object.entries(component?.items ?? {})
            return entries.map(([name, sub], index) => (
              <tr key={key + name} data-sub-item={name}>
                {index === 0 && <td rowSpan={entries.length}>{label}（{formatCandidateScore(component?.score)}，權重 {Math.round((component?.weight ?? 0) * 100)}%）{component?.inference && <> <InferenceBadge /></>}</td>}
                <td>{subItemLabel(name)}{sub.null_explanation && <div className="small-note">{sub.null_explanation}</div>}</td>
                <td className="num">{formatSubItemValue(name, sub.value)}</td>
                <td className="num">{formatCandidateScore(sub.percentile)}</td>
                <td className="num">{Math.round(sub.weight * 100)}%</td>
              </tr>
            ))
          })}
        </tbody>
      </Table>
      {item.alternatives.length > 0 && (
        <div className="small-note">同檔另一策略：{item.alternatives.map((alt) => `${candidateStrategyLabel(alt.strategy)} 總分 ${formatCandidateScore(alt.total_score)}`).join('、')}（只留總分高者）</div>
      )}
      <div className="small-note">權重涵蓋 {Math.round(item.weight_coverage * 100)}% · 資料日期 {formatDate(item.data_as_of) ?? '待核實'}{item.levels.earliest_execution_date ? ` · 規則最早執行日 ${formatDate(item.levels.earliest_execution_date)}` : ''}</div>
      <div className="small-note">來源：{candidateSourceText(item)}</div>
    </details>
  )
}

// LLM note (#220): DESIGN_SYSTEM §7 inference block, apart from the rule values; never part of the score.
function CandidateNote({ item }: { item: CandidateItem }) {
  const view = candidateNoteView(item.llm_note)
  return (
    <section className="ai-inference candidate-note" aria-label={NOTE_TITLE} data-note-state={view.kind}>
      <div className="ai-inference-head"><h3>{NOTE_TITLE}</h3><AiBadge /></div>
      {view.kind === 'done'
        ? (
          <dl className="candidate-note-parts">
            {view.parts.map((part) => <div key={part.key} data-note-part={part.key}><dt>{part.label}</dt><dd>{part.text}</dd></div>)}
          </dl>
        )
        : <p className="candidate-note-empty">{view.text}</p>}
      <p className="small-note">{NOTE_DISCLAIMER}</p>
      {view.meta && <p className="small-note ai-meta">{view.meta}</p>}
    </section>
  )
}

const REASON_COMPONENTS: ReadonlySet<string> = new Set<CandidateComponentKey>(['technical', 'chips', 'news_sentiment', 'group'])

export function CandidateCard({ item, linkToStock = true, detailsOpen = false }: { item: CandidateItem; linkToStock?: boolean; detailsOpen?: boolean }) {
  const { instrument, levels } = item
  const name = <><strong>{instrument.symbol}</strong> {instrument.name}</>
  return (
    <article className="card candidate-card" data-candidate-rank={item.rank}>
      <div className="candidate-head">
        <span className="candidate-rank" aria-label={`第 ${item.rank} 名`}>#{item.rank}</span>
        <div className="candidate-name">
          {linkToStock ? <Link className="symbol-link" to={stockPath(item)}>{name}</Link> : <span>{name}</span>}
          <div className="small-note">{exchangeLabel(instrument.exchange)} · {candidateStrategyLabel(item.strategy)}</div>
        </div>
        <div className="candidate-total"><span>總分</span><b>{formatCandidateScore(item.total_score)}</b></div>
      </div>
      {item.partial_components && <div className="candidate-partial small-note">{PARTIAL_NOTE}</div>}
      <dl className="candidate-levels">
        <div><dt>進場區</dt><dd className="level-entry">{formatEntryZone(levels)}</dd></div>
        <div><dt>停損</dt><dd className="level-stop">{formatPrice(levels.invalid_price)}</dd></div>
        <div><dt>目標</dt><dd className="level-target">{formatPrice(levels.target_1)}{levels.target_2 != null && <span className="level-target-2">／{formatPrice(levels.target_2)}</span>}</dd></div>
        <div><dt>RR</dt><dd><Badge tone="primary" className="badge-compact">{formatRiskReward(levels.risk_reward)}</Badge></dd></div>
      </dl>
      <ComponentScores item={item} />
      {item.reasons.length > 0 && (
        <ul className="candidate-reasons">
          {item.reasons.map((reason) => (
            <li key={reason.code} data-reason={reason.code}>
              <i className={'reason-dot reason-dot-' + (REASON_COMPONENTS.has(reason.component) ? reason.component : 'other')} aria-hidden="true" />
              <span>{reason.text}</span>
              {reason.inference && <InferenceBadge />}
            </li>
          ))}
        </ul>
      )}
      <div className="small-note candidate-groups">族群：{item.groups.length ? item.groups.map(candidateGroupText).join('、') : '無所屬產業或題材'}</div>
      <CandidateNote item={item} />
      <ScoreDetails item={item} open={detailsOpen} />
    </article>
  )
}

export function CandidatesSection({ data, loading, error }: { data: CandidatesResponse | undefined; loading: boolean; error: unknown }) {
  const state = data ? candidatesState(data) : null
  return (
    <section className="candidates-section" aria-labelledby="candidates-title">
      <div className="section-head">
        <div><div className="eyebrow">每日候選 · 依評分排序</div><h2 id="candidates-title">明日候選</h2></div>
        {data && data.status !== 'not_computed' && (
          <div className="board-dates"><DateBadge date={formatDate(data.trading_date)} />{state?.kind === 'list' && <Badge>{data.candidate_count} 檔</Badge>}</div>
        )}
      </div>
      <p className="small-note candidate-disclaimer">{CANDIDATE_DISCLAIMER}</p>
      {loading
        ? <Skeleton lines={4} label="明日候選載入中…" />
        : error
          ? <Card><EmptyState title="資料暫時無法載入" reason={errorReason(error)} /></Card>
          : !state
            ? null
            : state.kind === 'list'
              ? null
              : <Card><EmptyState title={state.kind === 'zero' ? '當日零候選' : '尚無候選清單'} reason={state.text} /></Card>}
    </section>
  )
}

// Stock page: only rendered when the stock is in the latest run on or before the cutoff.
export function StockCandidatePanel({ candidate }: { candidate: CandidateItem | null | undefined }) {
  if (!candidate) return null
  return (
    <section className="candidates-section stock-candidate" aria-labelledby="stock-candidate-title">
      <div className="section-head">
        <div><div className="eyebrow">每日候選 · 第 {candidate.rank} 名</div><h2 id="stock-candidate-title">明日候選</h2></div>
        <DateBadge date={formatDate(candidate.trading_date)} />
      </div>
      <p className="small-note candidate-disclaimer">{CANDIDATE_DISCLAIMER}</p>
      <CandidateCard item={candidate} linkToStock={false} detailsOpen />
    </section>
  )
}
