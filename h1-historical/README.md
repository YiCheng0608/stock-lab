# #867 H1 歷史樣本外（portfolio_research 第 1 版，`--window historical`，只跑一次）

## 先讀：下市股月營收缺口造成的偏差（方向有利於 H1，只在主鍵同分時起作用）

照 [#867 決定 7032683717](https://github.com/YiCheng0608/stock-lab/issues/867#issuecomment-7032683717)，用凍結的 H1 原樣跑。工具輸出（`summary.md` 等）沒有改，偏差寫在這份 README。

- **H1 怎麼用月營收**：`revenue_high_12` 是第二排序鍵（`portfolio_research.HYPOTHESES["H1"]`）。缺值的股票不會被剔除，只在主鍵 `trust_buy_days_5` 同分時排到最後（`portfolio_research.ranking_key`）。研究 DB 的下市股大多沒有月營收（#786，主要是 `not_public` 130 檔），所以同分時它們幾乎選不到，但基準母體裡有它們。
- **大小**（[設計提問 7032659972](https://github.com/YiCheng0608/stock-lab/issues/867#issuecomment-7032659972) 的唯讀量測，[design/](https://github.com/YiCheng0608/stock-lab/tree/pr-assets/867/design)）：
  - 窗口 2012-05-08～2024-09-27。第 5 名落在主鍵同分組裡、要由次鍵決定的，幾乎每一天都是。
  - 同分組裡有缺 `revenue_high_12` 的下市股的有 1,165 日，這些下市股共 1,559 個檔日被排到同分組最後。
  - 2012-05-08～2014-01 全部公司的 `revenue_high_12` 都缺（月營收 2013-01 起，要 12 個月）。這段只按主鍵與雜湊排序，對下市股沒有差別待遇。
- **方向**：選股時避開了之後下市的公司，基準卻有它們，所以偏差有利於 H1，但比 X3、X4、X7、S1～S3 的「缺值就排除」小。例外是合併消滅的公司可能有收購溢價。

## 結果

- 判定：**通過**。共 3,037 日，對母體超額日均 0.026%，t 2.17；對加權指數 -0.008%，t -0.54，只列出。
- 各檔 sha256：

```
7eb477f5f0932b2e0a5fe68ea1defdf16d418aa35efee9f7b55c269fc13c4977  summary.md
4029c7b37c870c0601a3017b5c521f79d896a6f00fb9be49219f55d62b7f8eac  tables.json
002ce309b12edaf57b71dcd53a71d6c4b500b793f598ef2c3d06f158c8be16d1  equity.csv
e5ac58cb0d0a7f3077d13226d8c7b9153ce0e3672ab818052880301689f01365  picks.csv
37d95aea61c254aa186a9821320f0f31372c0580f4dbb66cb3b6567d8f151f49  trades.csv
```

- `run.log` 是容器的 stdout／stderr。
