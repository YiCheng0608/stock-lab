import { candidateStrategyLabel, formatCandidateScore, liquidityExclusionText } from '../candidates/candidates'
import { productActionReasonLabel } from '../presentation'
import type { ActionSummary, StrategyBoard, StrategyBoardRow } from '../types'
import { unmetText } from './strategyBoard'

// The stock page summary card (#519, UI_COPY_SPEC §8.2 摘要卡): what the page already judges, rearranged. Nothing here
// computes a new judgement; the verdict is the first rule of the table that holds, the reasons are the API's sentences.

export type VerdictTone = 'success' | 'primary' | 'warning' | 'default'
export type StockVerdict = { label: string; tone: VerdictTone; reason: string }

export const SUMMARY_COLUMNS = { verdict: '目前判斷', closest: '最接近成立', levels: '規則價位' } as const
export const SUMMARY_LINK = '完整條件 →'
export const NO_ACTION_TEXT = '尚無行動摘要。'
export const NO_BOARD_TEXT = '此股尚無策略判定資料。'
export const NOT_CANDIDATE_TEXT = '不在這個資料日的每日候選名單'
export const ETF_NOT_SCORED_TEXT = 'ETF 不列入候選評分'

const INCOMPLETE_STATES: readonly string[] = ['data_insufficient', 'data_incomplete', 'insufficient_data']

const instruction = (action: ActionSummary) => action.display_instruction ?? action.action_instruction ?? action.display_action ?? action.action_label_zh ?? ''
const primaryReason = (action: ActionSummary | null) => action?.primary_reason?.label || null

export function stockVerdict(board: StrategyBoard | null | undefined, action: ActionSummary | null | undefined): StockVerdict {
  const rows = board?.strategies ?? []
  const state = action?.action_state ?? null
  if (!board && !action) return { label: '無資料', tone: 'default', reason: NO_ACTION_TEXT }
  if (action && state === 'reduce_exit') return { label: '持倉風險', tone: 'warning', reason: instruction(action) }
  if (board?.candidate) {
    const { rank, total_score: score, strategy } = board.candidate
    return { label: '可買', tone: 'success', reason: `每日候選第 ${rank} 名 · 總分 ${formatCandidateScore(score)} · ${candidateStrategyLabel(strategy)}` }
  }
  if (action && state === 'hold_observe') return { label: '持倉觀察', tone: 'primary', reason: instruction(action) }
  if (action && state === 'manual_review') return { label: '需人工判讀', tone: 'warning', reason: primaryReason(action) ?? instruction(action) }
  if (rows.length && rows.every((row) => row.status === 'not_applicable')) return { label: '不適用', tone: 'default', reason: unmetText(rows[0]) }
  if (action && INCOMPLETE_STATES.includes(state ?? '')) {
    const labels = (action.gap_reasons ?? []).map((reason) => reason.label).filter(Boolean)
    const reason = labels.length ? labels.join('；') : productActionReasonLabel(action.data_gap ?? '研究資料尚未完整，尚不能計算進場、失效與目標價。')
    return { label: '資料不足', tone: 'warning', reason }
  }
  if (rows.some((row) => row.status === 'conditional')) {
    const floor = board?.liquidity ? liquidityExclusionText({ ...board.liquidity, exclusion: board.liquidity.candidate_exclusion }) : null
    const etf = action?.instrument.instrument_type === 'etf'
    return { label: '條件成立', tone: 'success', reason: floor ?? (etf ? ETF_NOT_SCORED_TEXT : NOT_CANDIDATE_TEXT) }
  }
  return { label: '觀察', tone: 'primary', reason: primaryReason(action ?? null) ?? (action ? instruction(action) : NO_ACTION_TEXT) }
}

// The strategy the card shows: the candidate's, then the first conditional row, then the observation with the fewest unmet
// conditions (one without condition details last; a tie keeps the declared order), then the first row.
export function closestStrategy(board: StrategyBoard | null | undefined): StrategyBoardRow | null {
  const rows = board?.strategies ?? []
  if (!rows.length) return null
  const candidate = board?.candidate ? rows.find((row) => row.strategy === board.candidate?.strategy) : undefined
  if (candidate) return candidate
  const conditional = rows.find((row) => row.status === 'conditional')
  if (conditional) return conditional
  const unmet = (row: StrategyBoardRow) => row.levels_missing && row.conditions.length === 0 ? Number.POSITIVE_INFINITY : row.unmet.length
  const observed = rows.filter((row) => row.status === 'observation')
  if (observed.length) return observed.reduce((best, row) => unmet(row) < unmet(best) ? row : best)
  return rows[0]
}
