# Phase 4：產品呈現、新聞時間與交易單位

> 歷史文件；2026-09-11 起不再作派工、完成度或能力現況依據。現行狀態只看 [ROADMAP](ROADMAP.md)，本文件不會恢復 Phase 4。

## 歷史定位與原目標

Phase 4 原本要把資料列整理為「結論 → 關鍵數字 → 證據／來源 → raw 診斷」的研究介面，並建立同標的一日一張卡、用途別完整度、新聞時間誠實與台股單位顯示。

它沒有授權下單、即時報價、正式 DB、來源採購、策略升版或預設版本切換。Unknown 不補 0，缺少可信 basis／時間／價位時不造漲跌、交易條件或發布時間；呈現驗收也不證策略績效或來源 truth。

## 現行文件

功能與操作契約由[文件索引](README.md)分工；狀態和驗收只看 [ROADMAP](ROADMAP.md)／[執行清單](ROADMAP_EXECUTION.md)。

## 仍未決事項

- 新聞來源授權、白名單、保存範圍、關聯／影響覆核責任、revision/quarantine 與停用條件。
- 即時報價來源與可信時間／basis；未決前日線只依現行文件稱最近收盤。
- 可供 hot-group 使用的事件 coverage 與其覆核責任。
- 後端 compact research summary、新聞 list/detail 投影及前端接線是否完成，須依實際 API/UI 與 ROADMAP 驗證，不能由歷史 proposal 推定。

## Git 取閱

原頁面欄位、卡片矩陣、單位範例、API proposal與逐輪驗收可用 `git show 69f62cf:docs/PHASE4_PLAN.md` 取閱；它們是歷史紀錄，不能覆蓋上述現行文件。
