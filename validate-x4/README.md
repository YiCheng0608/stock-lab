# #867 驗證段：X4（explore_research 第 2 版，只跑一次）

## 先讀：下市股月營收缺口造成的偏差（有利於假設）

照 [#867 決定 7032683717](https://github.com/YiCheng0608/stock-lab/issues/867#issuecomment-7032683717)（選項 A），本次照登記原樣跑：定義、判定、門檻、工具版本都沒動。工具產出的 `explore.md`／`explore.json` 原樣，沒有改；偏差寫在這份 README。

- **缺口**：研究 DB 在下市股上大多沒有月營收（#786，主要是 `not_public` 130 檔）。X4 的條件缺值就不符合，所以這些股票在選股前就被排除，基準母體裡卻有它們。
- **驗證段的大小**（[設計提問 7032659972](https://github.com/YiCheng0608/stock-lab/issues/867#issuecomment-7032659972)，[design/](https://github.com/YiCheng0608/stock-lab/tree/pr-assets/867/design)）：
  - 母體 2.2% 的檔日是之後下市的股票，其中 70% 因缺值被排除。
  - 名單中的下市股占比約 1.2%（若有資料，估計）→ 0.5%。
  - 比探索段小很多（探索段母體 7.9%、91%）。
- **方向**：
  - 偏差有利於假設。
  - 例外：合併消滅的公司可能有收購溢價。
- **對照**：「基準去掉當天缺 `revenue_yoy` 或 `eps_growth_yield` 的下市股」的超額，只列出、不判定，見 [control/](https://github.com/YiCheng0608/stock-lab/tree/pr-assets/867/control)。

## 結果

- `explore.json` 的 sha256：`49de079c5e3ba1e760170d5ffaf2f6a1eb0adc640f269e28ff86e80ad79c4192`
- 探索報告：sha256 `7b157b26…dc1f8`，連結 https://github.com/YiCheng0608/stock-lab/issues/867#issuecomment-7032779893 （統籌決定 [7033178620](https://github.com/YiCheng0608/stock-lab/issues/867#issuecomment-7033178620) 核對）。
- 判定：**前瞻觀察**。對母體超額 t 0.80，未達 2；絕對報酬 > 0。照 evidence.md，前瞻觀察不跑已用段、不進產品。
- `run.log` 是容器的 stdout／stderr。
