# #867 探索段：S1～S3（trade_research 第 1 版）

## 先讀：下市股月營收缺口造成的偏差（有利於假設）

照 [#867 決定 7032683717](https://github.com/YiCheng0608/stock-lab/issues/867#issuecomment-7032683717)（選項 A），本次照登記原樣跑：定義、判定、門檻、工具版本都沒動。工具產出的 `explore.md`／`explore.json` 原樣，沒有改；偏差寫在這份 README。

- **缺口**：研究 DB 在下市股上大多沒有月營收（#786「補完後的缺口」，主要是 `not_public` 130 檔）。S1～S3 的 `revenue_yoy > 0` 遇到缺值就不成為訊號（`trade_research.ranked`），逐筆評估的基準母體（`evidence_lib.universe`）卻含這些股票。
- **大小**（[設計提問 7032659972](https://github.com/YiCheng0608/stock-lab/issues/867#issuecomment-7032659972) 的唯讀量測，[design/](https://github.com/YiCheng0608/stock-lab/tree/pr-assets/867/design)；沿用 X3 的訊號日，不套 ATR14、占用與 S1 的大盤濾網）：
  - 探索段（2014-12-26～2019-12-31）母體 7.6% 的檔日是之後下市的股票，其中 91% 因沒有月營收被排除。
  - 通過 `revenue_yoy > 0` 的名單中，下市股占比從約 6.7%（若有資料，估計）降到 0.7%。
- **方向**：
  - 假設的訊號幾乎沒有之後下市的公司，基準卻有，而下市前的公司多半表現差，所以偏差有利於假設。
  - 例外：`not_public` 裡合併消滅的公司可能有收購溢價，方向相反；比例沒有查證。
- 三個假設都沒有通過探索段，所以不做「基準去掉缺月營收的下市股」的對照（決定：只做探索通過的）。

## 結果

`explore.json` 的 sha256：`eae22284845cbb3bf3f2ef5e60ecf444a50d2474034d45f32109a6966d4e984f`

判定見 `explore.md`，各假設見 `<代號>/summary.md`。`run.log` 是容器的 stdout／stderr。
