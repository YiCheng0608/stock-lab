explore.json 的 sha256：`9c90dd6ff8c4f435a1980939b9fdd6d56a1b3bc0ded04cab8a135136f8ea9bf4`

# 新策略探索 第 8 輪 驗證段（round8_research 第 1 版，#918）

- 登記 commit `df0aa8b5`（docs/spec/evidence.md「第八輪：Z1～Z4」）：https://github.com/YiCheng0608/stock-lab/issues/915#issuecomment-7055425946
- 定義雜湊 `cd00cd2d201893370ec706168af5a30cb8e1e684c47ba30fc91356447876d757`
- 比較次數：本輪 4 個、累計 34 個；另列：前瞻 H1：1 組（#691）；#673 出場規則：14 組；#682 組合層級回測：18 組；#689 評分改版：108 組；#619／#643 特徵判定：組數見各自報告
- 門檻：超額日均 > 0 且 t ≥ 3.180，且絕對報酬日均 > 0；段長下限 250 日；研究 DB 要有段內已下市公司。探索段 t ≥ 2，驗證段 t ≥ 3.180（Bonferroni，累計 34 個：1 − Φ(z)＝0.025 ÷ 34，寫死不重算）
- Z1 的限制：選到的股票常在漲停附近，T+1 漲停鎖死買不到的檔照引擎略過、不遞補，名單不足 20 檔的餘額留現金
- Z2 的限制：漲跌幅限制 2015-06-01 起由 ±7% 放寬到 ±10%，兩邊的尾巴都被截斷，偏態的分布跨年不同；排序只在同一天之間比，名單不受影響，但不同年份的特徵值不能直接比
- Z3 的限制：上櫃股也用加權指數當大盤（兩市場同一個基準，不混用櫃買指數），同 Y3；加權指數是價格指數、不含股利。Frazzini & Pedersen 的 BAB 是多空、以 beta 加權槓桿；這裡只做多、等權，測的是「低 beta 的 20 檔贏不贏母體」，不是 BAB 因子本身
- 副本：最新交易日 2026-11-13，alembic `0033_mainstream_lists`
- 讀取的資料到 2024-09-27（之後的列不讀）
- 耗時 170 秒，峰值記憶體 1.12 GB
- 重現：`python tools/research/round8_research.py --db /research/stock.db --segment validation --exploration-report /out/exploration/explore.json --exploration-sha256 f2a8c8df49f560f6352afb3114ee013b692e65e01ca9e9b0f7c3982822a93622 --exploration-url https://github.com/YiCheng0608/stock-lab/blob/pr-assets/928/exploration/explore.json --out /out/validation`
- 前瞻觀察：超額日均 > 0 但 t < 3.180，且絕對報酬日均 > 0；只當紀錄，不算通過、不進產品
- 探索段報告：https://github.com/YiCheng0608/stock-lab/blob/pr-assets/928/exploration/explore.json（sha256 `f2a8c8df49f560f6352afb3114ee013b692e65e01ca9e9b0f7c3982822a93622`）

## 判定

| 代號 | 方向 | N／K | 日數 | 對加權指數超額日均 | t | 對母體超額日均 | t | 絕對報酬日均 | 判定 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Z2 | 彩券偏好 | 20／60 | 1153 | -0.001% | -0.05 | -0.016% | -0.75 | 0.062% | 驗證段反轉 |

各假設的數字、只列出的指標與資料覆蓋見 `<代號>/summary.md`。
