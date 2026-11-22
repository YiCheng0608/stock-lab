explore.json 的 sha256：`e5ea33d9b3857f756ceac1552734a839ed172b9848399577edc8a25136ddebe2`

# 新策略探索 第 12 輪 驗證段（round12_research 第 1 版，#962）

- 登記 commit `24d700c3`（docs/spec/evidence.md「第十二輪：J1～J4」）：https://github.com/YiCheng0608/stock-lab/issues/956#issuecomment-7078404124
- 定義雜湊 `12f24befd44c279118ade14460c722f968849a00c48a27b4def7690ca3f0954f`
- 比較次數：本輪 4 個、累計 49 個；另列：前瞻 H1：1 組（#691）；#673 出場規則：14 組；#682 組合層級回測：18 組；#689 評分改版：108 組；#619／#643 特徵判定：組數見各自報告
- 門檻：超額日均 > 0 且 t ≥ 3.285，且絕對報酬日均 > 0；段長下限 250 日；研究 DB 要有段內已下市公司；J3 另要有成交的訊號日至少 60 日（逐筆評估）。探索段 t ≥ 2，驗證段 t ≥ 3.285（Bonferroni，累計 49 個：1 − Φ(z)＝0.025 ÷ 49，寫死不重算）
- 引擎：J1、J2、J4 是組合引擎（`portfolio_research.simulate`，日數是有淨值的交易日）；J3 是逐筆評估（`trade_research`，日數是段內交易日，超額與 t 在訊號日序列上）
- J1 的判定只看整體；分狀態的數字只列出
- J1 的限制：情緒狀態會持續好幾個月，切換次數少，等於只有少數幾段在比兩邊，t 高估獨立樣本數；情緒高的日子名單就是 V1 的名單
- J2 的限制：三大法人的官方表只列當天有法人進出的證券，沒列的日子是缺值，名單會偏離法人很少進出的小型股；`feature_evidence` 的 `trust_flow_5`（投信 5 日）是 #619～#689 在已用段比較過的特徵之一，J2 依文獻提，沒有看那批結果；不足 20 檔的日子留現金，平均投入比例可能偏低，是登記時事先定的規則
- J3 的限制：稅制在 2018 年改過（在探索段裡），二代健保補充保費 2013 年起；驗證段全在 2018 年以後；除息集中在 6～9 月；逐筆平均假設每個訊號都買得到、每筆等額，不是一個帳戶的資金曲線；同一季的訊號持有期間高度重疊
- J4 的限制：原文另外控制了其他變數，這裡沒有扣掉成交量的異常，成交量放大常伴隨流動性改善，J4 可能沾到 Z1，看和 Z1 名單的重疊比例
- 副本：最新交易日 2026-11-13，alembic `0033_mainstream_lists`
- 讀取的資料到 2024-09-27（之後的列不讀）
- 耗時 615 秒，峰值記憶體 2.14 GB
- 重現：`python tools/research/round12_research.py --db /research/stock.db --segment validation --exploration-report /out/exploration/explore.json --exploration-sha256 d11af72cd59c80d967f9cc6ead62f8504a5bb2f8d022ab6a4f03d61d34cb09af --exploration-url https://github.com/YiCheng0608/stock-lab/issues/964#issuecomment-7082081487 --out /out/validation`
- 前瞻觀察：超額 > 0 但 t < 3.285，且絕對報酬 > 0；只當紀錄，不算通過、不進產品
- 探索段報告：https://github.com/YiCheng0608/stock-lab/issues/964#issuecomment-7082081487（sha256 `d11af72cd59c80d967f9cc6ead62f8504a5bb2f8d022ab6a4f03d61d34cb09af`）

## 判定

| 代號 | 方向 | 引擎 | 日數 | 有成交的訊號日 | 對加權指數超額 | t | 對母體超額 | t | 絕對報酬 | 判定 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| J2 | 籌碼：投信 | 組合 | 1153 | — | -0.048% | -2.01 | -0.021% | -1.06 | 0.015% | 驗證段反轉 |

各假設的數字、只列出的指標與資料覆蓋見 `<代號>/summary.md`。
