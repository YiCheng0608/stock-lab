explore.json 的 sha256：`02e533a77a4af4fc4a70b5daa60c05813b4b25e076c10cde7cddd03cf107fac5`

# 新策略探索 第 1 輪 探索段（explore_research 第 2 版，#703）

- 登記 commit `0ba48e9`（docs/spec/evidence.md「新策略探索」）；工具設計 https://github.com/YiCheng0608/stock-lab/issues/703#issuecomment-6874888073
- 定義雜湊 `600dc942361847eb9591425b4eb97ce4178b477695ff34fc234e45a665ebec63`
- 比較次數：本輪 8 個、累計 8 個；另列：前瞻 H1：1 組（#691）；#673 出場規則：14 組；#682 組合層級回測：18 組；#689 評分改版：108 組；#619／#643 特徵判定：組數見各自報告
- 門檻：超額日均 > 0 且 t ≥ 2.00，且絕對報酬日均 > 0；段長下限 500 日；研究 DB 要有段內已下市公司
- 副本：最新交易日 2026-11-13，alembic `0033_mainstream_lists`
- 讀取的資料到 2019-12-31（之後的列不讀）
- 耗時 257 秒，峰值記憶體 1.55 GB
- 重現：`python tools/research/explore_research.py --db /research/stock.db --segment exploration --hypotheses X6 --out /out/exploration-x6`
- 本次跑的假設：X6

## 判定

| 代號 | 方向 | N／K | 日數 | 對加權指數超額日均 | t | 對母體超額日均 | t | 絕對報酬日均 | 判定 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| X6 | 大型股傾向 | 10／20 | 1187 | -0.037% | -2.26 | 0.001% | 0.05 | -0.015% | 沒有通過（探索段） |

各假設的數字、只列出的指標與資料覆蓋見 `<代號>/summary.md`。
