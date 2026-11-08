<!-- owns: 技術指標 -->
# 技術指標

版本 `indicators/v1`；公式與參數集中在 `backend/app/indicators.py`（`INDICATOR_VERSION`、`PARAMETERS`、`REQUIRED_BARS`），批次在 `backend/worker/indicator_batch.py`。改公式、參數或不足規則必須升版；`technical_indicators` 以（標的、日期、`formula_version`）為唯一鍵，新版本另寫列，不覆寫既有版本結果。

價格基準另有版本（`PRICE_BASIS`，每列記在 `price_basis`）。改還原規則要升價格基準；同一 `formula_version` 下舊基準的列不再提供：bars API 只讀目前基準的列，舊列當作 `not_computed`。指標批次遇到某標的沒有目前基準的列時，刪掉該標的這個 `formula_version` 的列並整段重寫（結果的 `instruments_rebased`）。

**輸入與價格基準**：輸入是 DB 保存的日線 `market_bars`。停牌列（`is_suspended`）與無效列（OHLC 非有限正數、`low` 高於開收或 `high` 低於開收、成交量為負）不進任何窗口、不補值；該日每欄為 null，原因 `suspended`／`invalid_bar`。開高低任一欄存 null（指數與台指期來源沒有或不合理的開高低，美股只有收盤；不看 `price_reason`）的列只檢查收盤，量存 null 的列不檢查量，兩者都照樣計入可用根數，讀到它們的欄位依下方「合成資料」段為 null；DB 深度審查（`tools/audit`）重算時用同一口徑（#557）。窗口以該股「可用日線根數」計，不比對交易所日曆；缺日不補，前後兩根直接相鄰。價格基準 `as_of_date_raw_basis/v2`：T 日的值以 T 日原始價為基準，T 以前的價格依 DB 已收錄的除權息、分割事件（`worker.pipeline._action_factor_by_bar`）換算到 T 日基準，所以 T 日的均線與 T 日原始 K 線同一尺度；之後才發生的事件不影響 T。未收錄的事件等同不還原。成交量不還原。

**還原因子**（`worker.pipeline._corporate_action_factor`，每個事件一個因子，累乘；指標、`technical_features`、訊號與計畫追蹤、觀察價位共用）：

1. 事件 `details_json` 有 `price_factor` 時用它。
2. 事件有官方除權息價格（TPEx `ClosePriceBeforeExRightsDiviend`／`ExRightsDiviendQuote`，TWSE `TWT49U` 的 `除權息前收盤價`／`除權息參考價`）時，因子是 `除權息參考價 ／ 除權息前收盤價`，涵蓋配股、配息、現金增資與認股（3691 2026-10-27：106.15 ／ 109.00 ＝ 0.9739）。例外：欄位算出的參考價（欄位因子 × 除權息前收盤價）與 `除權息參考價` 差在 0.02 元內（含剛好 0.02；`ACTION_REFERENCE_TOLERANCE`，官方以 0.01 元捨去公布，差距先四捨五入到小數 6 位再比）時，欄位因子就是未捨去的官方比，照用欄位因子。所以只有現增、認股，以及欄位被[寫入防呆](../DATA_SOURCES.md#寫入防呆)留空的列會改用官方比。
3. 沒有官方價格（daily 的 `TWT48U_ALL`）時用欄位（現行公式）：分割比、`1 ／ (1 + 配股率)`、`(參考價 − 現金股利) ／ 參考價`；參考價是事件的 `reference_price`，沒有時用事件前最後一根收盤。現增、認股在這裡不還原。

`as_of_date_raw_basis`（v1，#394 以前）只有第 1、3 步。

**公式**（`C`、`H`、`L`、`V` 為上述基準的收、高、低與量）

| 欄位 | 定義 | 需要根數 |
| --- | --- | --- |
| `ma5`／`ma10`／`ma20`／`ma60`／`ma120` | 近 n 根 `C` 的簡單平均 | n |
| `macd_dif` | `EMA12(C) − EMA26(C)`；EMA 的 α = 2/(n+1)，以前 n 根簡單平均起算 | 26 |
| `macd_signal` | `EMA9(DIF)`，以前 9 個 DIF 的簡單平均起算 | 34 |
| `macd_hist` | `DIF − signal`（不乘 2） | 34 |
| `rsi6`／`rsi12` | Wilder：首個平均漲跌為前 n 個變動的簡單平均，之後 `(前值 × (n−1) + 本期) / n`；`RSI = 100 × 平均漲 / (平均漲 + 平均跌)` | n+1 |
| `kd_k`／`kd_d` | `RSV = 100 × (C − L9) / (H9 − L9)`（L9、H9 為近 9 根最低低、最高高）；`K = K' + (RSV − K')/3`、`D = D' + (K − D')/3`，首根前 `K' = D' = 50`；`H9 = L9` 時 RSV 取 50 | 9 |
| `boll_mid`／`boll_upper`／`boll_lower` | 中軌 = MA20；上下軌 = 中軌 ± 2 × 近 20 根 `C` 的母體標準差 | 20 |
| `vol_ma5`／`vol_ma20` | 近 n 根 `V` 的簡單平均 | n |

EMA 與 Wilder 平滑依賴全部可用歷史，起算點是該股在 DB 的第一根可用日線；DB 往前回補後要重算（見 [現有 worker CLI](../ops/CLI.md#現有-worker-cli)）。

`technical_features` 不保存前 20 根陣列；`breakout_v1`／`pullback_v1` 與 `hot_group_v1` 需要的前 20 根高點與量由 `market_bars` 即時切取（`worker.pipeline._prior_20_window`）。

**資料不足**：可用根數少於上表時該欄為 null，原因 `insufficient_bars`，並保存 `bar_count`（含 T 的可用根數），API 另附 `required_bars` 讓畫面說明「需 N 根、現有 M 根」。RSI 在該股自第一根可用日線起完全沒有漲跌時為 null，原因 `no_price_change`（Wilder 平滑下只要曾有漲跌，平均值就不會回到 0）。批次尚未寫入的日期，API 回 `not_computed`。

**合成資料**：指數 parser 寫的日線（`source=twse_index`，或 `turnover_reason=synthetic_index`；`app.indicators.is_synthetic_bar`）只有收盤是官方值，開高低是收盤、量是 0（[DATA_SOURCES](../DATA_SOURCES.md#官方來源)）。讀高低點或量的欄位遇到合成日線為 null，原因 `synthetic_index`，即使根數不足也記這個原因：`kd_k`／`kd_d` 會遞迴到第一根，所以只要 T 以前有一根合成日線就留空；`vol_ma5`／`vol_ma20` 只看自己的窗口。其餘欄位只讀收盤，照算。週線含一天合成日線就算合成。指數與台指期的真實日線（[DATA_SOURCES 指數日 K](../DATA_SOURCES.md#指數日-k)，#552）某天來源沒有開高低時存 null：KD 同樣從那天起為 null，原因 `missing_ohlc`；某天沒有成交量時，窗口含那天的 `vol_ma5`／`vol_ma20` 為 null，原因 `missing_volume`；那天的收盤照樣進只讀收盤的欄位，週線含那天時週線的開高低（或量）為 null。同一欄同時遇到合成日線時記 `synthetic_index`。這條規則從價格基準 `as_of_date_raw_basis/v2` 起生效；v1 的列照合成值算了 KD 與量均，換基準時整段重寫（見上方價格基準版本）。

**週線**：由日線聚合，依 ISO 週（週一起算；補班交易日併入當週）分組，只用可用日線：開＝首日開、高＝最高高、低＝最低低、收＝末日收、量＝加總，`date` 為該週最後一個交易日並附 `week_start`、`trading_days`。週指標以週線序列套用同一公式與參數重算（MA5 即 5 週），價格基準為該週最後一日；整週停牌則無該週。週線指標於 API 請求時計算，不入庫。

**API**：`GET /api/stocks/{exchange}/{symbol}/bars?interval=day|week&limit=N`（`limit` 1～1500，預設 250，取最近 N 根）。每根回 OHLCV、來源、`bar_count`、上表各欄與 `reasons`（只列 null 欄位的原因）；頂層附 `data_as_of`、行情 `sources` 與 `indicators`（版本、價格基準、參數、`required_bars`、欄位清單、指標來源與日線批次計算時間）。日線指標讀 `technical_indicators`，週線即時計算。
