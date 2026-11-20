# X6 探索段（#864）的資料說明

本目錄除了這份 README 以外，都是 `explore_research.py --segment exploration --hypotheses X6` 的原始輸出；`explore.json` 的 sha256 是 `02e533a77a4af4fc4a70b5daa60c05813b4b25e076c10cde7cddd03cf107fac5`。這份 README 是工程師事後加的，不在工具的輸出裡，也不影響雜湊。

## 補班日的三大法人缺口（照登記規則：缺值排最後）

- **現象**：TWSE 的週六補班交易日，約 450～490 檔 `stock`／`ipo` 的 `foreign_buy`、`trust_buy`、`dealer_buy` 都是 null。平日也有約 84 檔（TWSE）、163 檔（TPEx）。`institutional_flow_20` 是 20 天加總，任一天 null 就缺值。所以一個補班日，會讓那些股票在之後 20 個訊號日都排到最後。
- **原因：官方沒列，不是資料錯**。查證見 [提問 7043539560](https://github.com/YiCheng0608/stock-lab/issues/864#issuecomment-7043539560)：
  - 2017-06-03、2016-06-04、2017-06-05 的 T86，以及 2017-06-05 的 TPEx `insti/dailyTrade`，null 的代號都不在當天 raw 的解析結果裡（四天都是 0 檔）。
  - 這些列是只由融資券 collect 建的，當天沒有法人進出。
- **處理**：照登記規則「條件缺值排最後、不剔除」，不改資料、不改工具（[決定 7043686420](https://github.com/YiCheng0608/stock-lab/issues/864#issuecomment-7043686420)）。
- **影響估計**（以當天成交金額前 150 名代理 X6 的 60 日平均成交金額前 150 名）：
  - 2015-03～2019 共 8 個補班日，每個補班日前 150 名裡缺 0～9 檔（平均約 4 檔）；平日缺 0 檔。
  - 受影響約 160 個訊號日（占 1,187 日的 13%）。
  - 改變的選股粗估約占全部選股檔次的 0.3%（約 40／11,870）。
- `coverage` 表裡 X6 三大法人的缺值比例（例如 2017 年 10.5%）是用共同口徑母體算的，不是用前 150 名算的。
