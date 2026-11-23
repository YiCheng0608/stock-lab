explore.json 的 sha256：`f3ab9ef136fd82ba58163e967ec74d52b5118afba214ff2de12abc05e7e38b1f`

# 新策略探索 第 15 輪 驗證段（round15_research 第 1 版，#984）

- 登記 commit `7612838a`（docs/spec/evidence.md「第十五輪：P1～P3」）：https://github.com/YiCheng0608/stock-lab/issues/982#issuecomment-7093927348
- 定義雜湊 `dbbeb3e2626bbd4642c7b8732da3f376c9905e50575bee8f2dbed60273ea824e`
- 比較次數：本輪 3 個、累計 58 個；另列：前瞻 H1：1 組（#691）；#673 出場規則：14 組；#682 組合層級回測：18 組；#689 評分改版：108 組；#619／#643 特徵判定：組數見各自報告
- 門檻：超額日均 > 0 且 t ≥ 3.332，且絕對報酬日均 > 0；段長下限 250 日；研究 DB 要有段內已下市公司。探索段 t ≥ 2，驗證段 t ≥ 3.332（Bonferroni，累計 58 個：1 − Φ(z)＝0.025 ÷ 58，寫死不重算）
- 引擎：P1、P2 是 X7 的事件日帳戶（`explore_research.simulate_events`，P1 窗口之間兩邊都留現金），P3 是組合引擎（`portfolio_research.simulate`，K＝20）；日數是有淨值的交易日
- 存活者偏差（P2）：下市股的季報只有 EPS，沒有 `margins_up` 的四個欄位，期間內下市公司的季幾乎都不符合，會排除之後下市的公司，偏差方向對假設有利。對照基準（母體去掉當天缺欄位的下市、轉板股）的超額與 t 在 `P2/summary.md`「數字」表的「超額（對對照基準，只列出）」列與 `explore.md` 的「只列出、不判定」
- P1 的限制：窗口約 20 個交易日，探索段只有 15 個窗口，檢定力低；窗口之間兩邊都是現金，全段的超額平均約是窗口內的 p 倍、標準差約 √p 倍（p 是窗口內日子的比例），t 約等於只用窗口內的日子算；金融業等法定期限不同的公司照樣算名次，但窗口是一般公司的；名單可能集中在季節性強的少數產業，看產業分布；下市與轉板標的共 76 個公司年缺 EPS，缺的排最後，偏差方向對假設有利；驗證段最後一個窗口是 2024-07-15（2024Q2，用 2021～2023 的 EPS）
- P2 的限制：存活者偏差：下市股的季報是 XBRL 整包補的，只寫了 EPS，沒有這四個欄位，期間內下市公司的季幾乎都不符合，會排除之後下市的公司，偏差方向對假設有利，比 K2 的 76 個公司年大；金融業等格式與法定期限不同的公司不會符合；2013 年的欄名由 `--coverage-only` 列
- P3 的限制：日間反轉的定義照論文摘要與二手整理，未讀全文；和 Z4 的關係：Z4 買隔夜報酬最低的，P3 選隔夜常漲、盤中常跌回的，排序變數不同（頻率，不是報酬的大小）；方向由 Akbas et al. 事先定，但登記時 Z4 的狀態已知，看和 Z4 的重疊比例
- 副本：最新交易日 2026-11-13，alembic `0033_mainstream_lists`
- 讀取的資料到 2024-09-27（之後的列不讀）
- 耗時 630 秒，峰值記憶體 2.12 GB
- 重現：`python tools/research/round15_research.py --db /research/stock.db --segment validation --exploration-report /out/exploration/explore.json --exploration-sha256 a6a97da06db34eba3e967451747812f8590db2c66304d57e8f77fd1b801e11fb --exploration-url https://github.com/YiCheng0608/stock-lab/blob/pr-assets/986/exploration/explore.json --out /out/validation`
- 前瞻觀察：超額 > 0 但 t < 3.332（沒有 t 下限），且絕對報酬 > 0；只當紀錄，不算通過、不進產品
- 探索段報告：https://github.com/YiCheng0608/stock-lab/blob/pr-assets/986/exploration/explore.json（sha256 `a6a97da06db34eba3e967451747812f8590db2c66304d57e8f77fd1b801e11fb`）

## 判定

| 代號 | 方向 | 日數 | 對加權指數超額 | t | 對母體超額 | t | 絕對報酬 | 判定 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| P2 | 基本面：三率三升 | 1097 | 0.068% | 1.82 | 0.059% | 2.59 | 0.152% | 前瞻觀察 |

只列出、不判定：

- P2 對對照基準的超額：日均 0.056%、t 2.50（1,097 日）
- P2 每次調倉的名單檔數：平均 20.0
- P2 和 K2 的重疊：平均 20.8%（19 個訊號日）
- P2 和 X4 的重疊：平均 10.3%（19 個訊號日）
- P2 的平均投入比例 98.4%、期末未賣的比例 5.3%

各假設的數字、只列出的指標與資料覆蓋見 `<代號>/summary.md`。
