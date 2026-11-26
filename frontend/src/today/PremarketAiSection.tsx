import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'

import { getPremarketAi } from '../api'
import { AiBadge } from '../news/NewsViews'
import type { PremarketAiReason, PremarketAiResponse, PremarketAiStock } from '../types'
import {
  PREMARKET_AI_ERROR, PREMARKET_AI_GAPS, PREMARKET_AI_JOIN, premarketAiShown, PREMARKET_AI_INPUT_GAPS, PREMARKET_AI_LOADING, PREMARKET_AI_TITLE,
  premarketAiAction, premarketAiGroups, premarketAiLevels, premarketAiMeta, premarketAiRefs, premarketAiState, premarketAiStockName,
} from './premarketAi'
import './premarketAi.css'

// The pre-market AI reading of the shown list (#1042; UI_COPY_SPEC §10 早盤 AI 判讀, DESIGN_SYSTEM §7). The reading is
// inference, in the §7 block with one 「AI 推論」 badge; the rule's prices (today-list stocks only, 3a) and the input's
// data gaps are facts and carry no 推論 mark.
// Only under the 今日名單 tab: the reading is of that list (the other lists carry no levels or AI).
export function PremarketAiSection({ listDate }: { listDate: string | null | undefined }) {
  const [search] = useSearchParams()
  const shown = premarketAiShown(search, listDate)
  const query = useQuery({ queryKey: ['premarket-ai', listDate], queryFn: () => getPremarketAi(listDate as string), enabled: shown })
  if (!shown) return null
  return <PremarketAiView data={query.data} loading={query.isLoading} error={query.error} />
}

function ReasonItem({ reason }: { reason: PremarketAiReason }) {
  const { news, others } = premarketAiRefs(reason)
  return (
    <li className="premarket-ai-reason">
      <span>{reason.text}</span>
      {news.length > 0 && (
        <span className="premarket-ai-refs">
          {news.map((item) => <Link key={item.id} className="text-link premarket-ai-news" to={`/news/${item.id}`}>{item.label}</Link>)}
        </span>
      )}
      {others.length > 0 && <span className="premarket-ai-refs muted">依據 {others.join('、')}</span>}
    </li>
  )
}

function Reasons({ reasons }: { reasons: readonly PremarketAiReason[] }) {
  if (reasons.length === 0) return null
  return <ul className="premarket-ai-reasons">{reasons.map((reason, index) => <ReasonItem key={index} reason={reason} />)}</ul>
}

function StockItem({ stock }: { stock: PremarketAiStock }) {
  const levels = premarketAiLevels(stock)
  return (
    <li className="premarket-ai-stock" data-symbol={stock.symbol} data-on-today-list={stock.on_today_list ? 'yes' : 'no'}>
      <p className="premarket-ai-stock-head">
        <span className="premarket-ai-stock-name">{premarketAiStockName(stock)}</span>{PREMARKET_AI_JOIN}
        <span className="premarket-ai-action" data-action={stock.action}>{premarketAiAction(stock)}</span>
      </p>
      {levels && <div className="premarket-ai-levels">{levels}</div>}
      <Reasons reasons={stock.reasons} />
    </li>
  )
}

export function PremarketAiView({ data, loading = false, error = null }: { data: PremarketAiResponse | undefined; loading?: boolean; error?: unknown }) {
  const state = data ? premarketAiState(data) : null
  return (
    <section className="ai-inference premarket-ai" aria-label={PREMARKET_AI_TITLE} data-premarket-state={data?.status ?? (loading ? 'loading' : 'error')}>
      <div className="ai-inference-head"><h2>{PREMARKET_AI_TITLE}</h2><AiBadge /></div>
      {!data || !state
        ? <p className="premarket-ai-empty">{loading ? PREMARKET_AI_LOADING : error ? PREMARKET_AI_ERROR : PREMARKET_AI_LOADING}</p>
        : state.kind === 'empty'
          ? <p className="premarket-ai-empty">{state.text}</p>
          : (
            <>
              <p className="small-note premarket-ai-meta">{premarketAiMeta(data)}</p>
              {data.market && (
                <div className="premarket-ai-block" data-part="market">
                  <h3>大盤 <span className="premarket-ai-value">{data.market.stance_text}（{data.market.confidence_text}）</span></h3>
                  <Reasons reasons={data.market.reasons} />
                </div>
              )}
              {data.sectors.length > 0 && (
                <div className="premarket-ai-block" data-part="sectors">
                  <h3>族群</h3>
                  <ul className="premarket-ai-list">
                    {data.sectors.map((sector) => (
                      <li key={sector.group_id} className="premarket-ai-sector">
                        <p className="premarket-ai-stock-head"><span className="premarket-ai-stock-name">{sector.name}</span>{PREMARKET_AI_JOIN}<span className="premarket-ai-action">{sector.direction_text}</span></p>
                        <Reasons reasons={sector.reasons} />
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {premarketAiGroups(data.stocks).map((group) => (
                <div key={group.title} className="premarket-ai-block" data-part={group.listed ? 'listed' : 'others'}>
                  <h3>{group.title}（{group.stocks.length} 檔）</h3>
                  <ul className="premarket-ai-list">{group.stocks.map((stock) => <StockItem key={stock.symbol} stock={stock} />)}</ul>
                </div>
              ))}
              {data.data_gaps.length > 0 && (
                <div className="premarket-ai-block" data-part="data-gaps">
                  <h3>{PREMARKET_AI_GAPS}</h3>
                  <ul className="premarket-ai-reasons">{data.data_gaps.map((gap, index) => <li key={index} className="premarket-ai-reason">{gap}</li>)}</ul>
                </div>
              )}
            </>
          )}
      {data && data.input_gaps.length > 0 && (
        <p className="small-note premarket-ai-input-gaps">{PREMARKET_AI_INPUT_GAPS}：{data.input_gaps.join('；')}</p>
      )}
    </section>
  )
}
