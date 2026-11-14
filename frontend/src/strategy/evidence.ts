// 「現行規則尚無證據」 (Issue 693; UI_COPY_SPEC §10, §13; decision 6873621771): the research found no edge in the rules behind
// 今日名單 (docs/spec/evidence.md; Issues 671, 673, 682, 689), so the list head, the stock page's candidate row and the 策略說明
// page say so in one sentence and link to the 研究結論 section of /strategy. The list itself, its scores and prices are unchanged.
export const NO_EVIDENCE_TEXT = '現行規則尚無證據：照名單價位進出，回測扣成本後沒有贏過同日母體。'
// The link after the sentence on the list head.
export const NO_EVIDENCE_LINK_LABEL = '研究結論 →'
// The short form beside the stock page's candidate disclaimer.
export const NO_EVIDENCE_SHORT_LABEL = '現行規則尚無證據 →'
export const EVIDENCE_SECTION_ID = 'strategy-evidence'
export const EVIDENCE_PATH = `/strategy#${EVIDENCE_SECTION_ID}`

// The 研究結論 section of /strategy: one finding a line, each with the Issues of its report (numbers from those reports).
export const EVIDENCE_FINDINGS: ReadonlyArray<{ text: string; issues: readonly number[] }> = [
  { text: '8 個進場與確認條件，探索、驗證兩段都沒有對之後報酬的預測力', issues: [671] },
  { text: '兩條規則的訊號，不論哪種出場，扣成本後每筆平均報酬為負：現行出場勝率約 43%，每筆約 −1.07%', issues: [673] },
  { text: '照名單每天買前幾檔，資金曲線沒有贏過同日母體；改用有證據的特徵排序也還不夠；有紀律地找新策略的研究（前瞻驗證、歷史回補）進行中', issues: [682, 689] },
]
export const EVIDENCE_CLOSING = '名單照常每天產出，讓你看到條件成立的股票；新策略要先通過事先寫好的前瞻驗證才會換上。價位是規則算出的參考，不是預期報酬。'
// 「#671」 built here, so no source line holds a literal that reads as a hex colour (noHardcodedColors.test.ts).
export const issueLabel = (issue: number) => '#' + String(issue)
