import { formatPrice } from '../candidates/candidates'
import { formatDay, formatTaipeiMinute } from '../dates'
import type { ChartLevels } from '../stock/stockBars'
import type { AiListLevels, AiListPick, AiListReason, AiListResponse } from '../types'

// The today page's AI list (#1146, UI_COPY_SPEC §10 AI 名單): its words and how a pick's levels read. The backend
// (app.ai_list) gives the sentences that say why a pick has no levels; the page writes them as they are.
export const AI_LIST_TITLE = 'AI 名單'
export const AI_LIST_MARK = 'AI 推論，未經驗證'
export const AI_LIST_LOADING = 'AI 名單載入中…'
export const AI_LIST_ERROR = 'AI 名單暫時無法載入'
export const AI_LIST_MISSING = '尚無 AI 名單（每個交易日 08:21 開盤前產出）'
export const AI_LIST_GAPS = '資料缺口'
export const AI_LIST_INPUT_GAPS = '名單輸入的資料缺口'
export const AI_LIST_LEVEL_REFS = '價位依據'
export const AI_LIST_EXIT = '出場條件'
export const AI_LIST_ENTRY_CONDITION = '進場條件'
// The background rule list (#1142 3/4 Q3-5 A): folded under the AI list, closed at first.
export const RULE_LIST_FOLD = '規則名單（背景計算，對答案用的基準）'
export const RULE_LIST_TITLE = '規則名單'

const mmdd = (iso: string | null | undefined): string | null => {
  const day = formatDay(iso)
  return day ? day.slice(5) : null
}

// 「AI 名單 · 2026/11/27 開盤前產出（08:22）」.
export function aiListHead(data: AiListResponse): string {
  const day = formatDay(data.session_date)
  const at = formatTaipeiMinute(data.finished_at)?.slice(11)
  return day ? `${AI_LIST_TITLE} · ${day} 開盤前產出${at ? `（${at}）` : ''}` : AI_LIST_TITLE
}

// 「模型 claude-sonnet-5-5 · 提示 ai_list_v1 · AI 推論，未經驗證」.
export function aiListMeta(data: AiListResponse): string {
  return [`模型 ${data.llm_model ?? '未記錄'}`, `提示 ${data.prompt_version}`, AI_LIST_MARK].join(' · ')
}

// 「11/27 的名單」 when the list is not today's (the night before, a weekend, today not made yet or failed).
export function aiListStaleBadge(data: AiListResponse): string | null {
  if (data.status !== 'done' || data.is_today) return null
  const day = mmdd(data.session_date)
  return day ? `${day} 的名單` : null
}

// 「大盤 中性（把握低）· 依據：台指期夜盤＞加權指數＞隔夜消息＞美股」.
export function aiListMarket(data: AiListResponse): string | null {
  const market = data.market
  if (!market) return null
  const head = `大盤 ${market.stance_text}${market.confidence_text ? `（${market.confidence_text}）` : ''}`
  return market.basis_text ? `${head} · 依據：${market.basis_text}` : head
}

// One labelled price in the §7 entry/stop/target colour.
export type AiLevelPart = { label: string; value: string; className: 'level-entry' | 'level-stop' | 'level-target' | null }

// 進場 站上 233.00（不追價 236.50）／進場區 44.40～46.05、停損、目標一／二、RR、有效至 (UI_COPY_SPEC §10 AI 名單).
export function aiLevelParts(levels: AiListLevels): AiLevelPart[] {
  const { entry } = levels
  const entryPart: AiLevelPart = entry.type === 'breakout'
    ? { label: '進場', value: `站上 ${formatPrice(entry.low)}${entry.high > entry.low ? `（不追價 ${formatPrice(entry.high)}）` : ''}`, className: 'level-entry' }
    : { label: '進場區', value: `${formatPrice(entry.low)}～${formatPrice(entry.high)}`, className: 'level-entry' }
  const target = levels.target_2 != null ? `${formatPrice(levels.target_1)}／二 ${formatPrice(levels.target_2)}` : formatPrice(levels.target_1)
  const parts: AiLevelPart[] = [entryPart, { label: '停損', value: formatPrice(levels.stop), className: 'level-stop' }, { label: '目標一', value: target, className: 'level-target' }]
  if (typeof levels.risk_reward === 'number') parts.push({ label: 'RR', value: `${levels.risk_reward.toFixed(2)} 倍`, className: null })
  const until = mmdd(levels.valid_until)
  if (until) parts.push({ label: '有效至', value: until, className: null })
  return parts
}

// The same as one line (verify T30 mirrors it): 「進場 站上 233.00（不追價 236.50）｜停損 226.00｜…」.
export function aiLevelsText(levels: AiListLevels): string {
  return aiLevelParts(levels).map((part) => `${part.label} ${part.value}`).join('｜')
}

// Why a pick shows no levels: past its validity, or a failed check.
export function aiNoLevelsText(pick: AiListPick): string | null {
  if (pick.levels) return null
  return pick.expired_text ?? pick.levels_text
}

// The K-line card's AI lines (#1142 4/4 row 26): a breakout's entry is its low, a pullback's the middle of its zone.
export function aiChartLevels(pick: AiListPick): ChartLevels | null {
  const levels = pick.levels
  if (!levels) return null
  const entry = levels.entry.type === 'breakout' ? levels.entry.low : (levels.entry.low + levels.entry.high) / 2
  if (!(levels.stop > 0 && levels.stop < entry && entry < levels.target_1)) return null
  return { entry, stop: levels.stop, target: levels.target_1, source: 'ai' }
}

// 「1477 聚陽」.
export function aiPickName(pick: AiListPick): string {
  return [pick.symbol, pick.name].filter(Boolean).join(' ')
}

export function aiPickPath(pick: AiListPick): string {
  return `/stocks/${encodeURIComponent(pick.exchange ?? 'TWSE')}/${encodeURIComponent(pick.symbol)}`
}

// A reason's cited news (each links to its news page) and the labels of the others, once each.
export function aiReasonRefs(reason: AiListReason): { news: { id: number; label: string }[]; others: string[] } {
  const news: { id: number; label: string }[] = []
  const others: string[] = []
  for (const ref of reason.refs) {
    if (ref.kind === 'news' && typeof ref.news_id === 'number') {
      if (!news.some((item) => item.id === ref.news_id)) news.push({ id: ref.news_id, label: ref.label ?? `新聞 ${ref.news_id}` })
    } else if (ref.label && !others.includes(ref.label)) {
      others.push(ref.label)
    }
  }
  return { news, others }
}
