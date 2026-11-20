explore.json 的 sha256：`49de079c5e3ba1e760170d5ffaf2f6a1eb0adc640f269e28ff86e80ad79c4192`

# 新策略探索 第 1 輪 驗證段（explore_research 第 2 版，#703）

- 登記 commit `0ba48e9`（docs/spec/evidence.md「新策略探索」）；工具設計 https://github.com/YiCheng0608/stock-lab/issues/703#issuecomment-6874888073
- 定義雜湊 `600dc942361847eb9591425b4eb97ce4178b477695ff34fc234e45a665ebec63`
- 比較次數：本輪 8 個、累計 8 個；另列：前瞻 H1：1 組（#691）；#673 出場規則：14 組；#682 組合層級回測：18 組；#689 評分改版：108 組；#619／#643 特徵判定：組數見各自報告
- 門檻：超額日均 > 0 且 t ≥ 2.00，且絕對報酬日均 > 0；段長下限 250 日；研究 DB 要有段內已下市公司
- 副本：最新交易日 2026-11-13，alembic `0033_mainstream_lists`
- 讀取的資料到 2024-09-27（之後的列不讀）
- 耗時 137 秒，峰值記憶體 1.09 GB
- 重現：`python tools/research/explore_research.py --db /research/stock.db --segment validation --exploration-report /out/explore-x.json --exploration-sha256 7b157b269d800ffa93caaa45703feefb04633bff239c9fe3803dab2dd0bdc1f8 --exploration-url https://github.com/YiCheng0608/stock-lab/issues/867#issuecomment-7032779893 --out /out/validation`
- 前瞻觀察：超額日均 > 0 但 t < 2.00，且絕對報酬日均 > 0；只當紀錄，不算通過、不進產品
- 探索段報告：https://github.com/YiCheng0608/stock-lab/issues/867#issuecomment-7032779893（sha256 `7b157b269d800ffa93caaa45703feefb04633bff239c9fe3803dab2dd0bdc1f8`）

## 判定

| 代號 | 方向 | N／K | 日數 | 對加權指數超額日均 | t | 對母體超額日均 | t | 絕對報酬日均 | 判定 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| X4 | 籌碼＋基本面 | 20／60 | 1153 | 0.030% | 1.02 | 0.015% | 0.80 | 0.093% | 前瞻觀察 |

各假設的數字、只列出的指標與資料覆蓋見 `<代號>/summary.md`。
