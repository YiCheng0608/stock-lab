# Canonical v1 規格

本文只保存 `breakout_v1`、`pullback_v1`、`hot_group_v1`、[技術指標](#技術指標) `indicators/v1`、價位、eligibility、生命週期與回測的 canonical 基準；實作狀態與排程見 [ROADMAP](ROADMAP.md)。修改公式、時間、成本或機率語意時必須升版並保留舊 run、輸入、設定與結果；公式變更可由 config 的 `formula_version` 子版本升版（如法人 `institutional-flow/v2-shares-per-share-volume`），此時 `StrategyVersion.version` 維持 `1.0.0`，舊公式識別保留於 `domain.INSTITUTIONAL_FLOW_FORMULAS`。`StrategyVersion` 以（`name`、`version`、`formula_version`）識別：子版本升版時舊公式的列整列保留（id、`version`、`config_json`、快照不改），新公式另建一列，既存訊號仍指向其原列。

設定來源是 `backend/app/domain.py`；worker 保存可序列化設定、rule evidence、data cutoff 與 raw provenance。此規格用於重現和稽核，不證明策略已採用或有效。

## 共通原則

- T 是訊號收盤日；最早成交為 T+1，不用 T 收盤冒充成交。
- 價格與必要量值須為有限正數。NaN、Infinity、交易日不足、必要資料缺失、停牌或不可重建路徑一律 `data_incomplete` 或 `incomparable`，不補 0。
- 歷史 v1 以日期 T 作 cutoff；這不證明盤後輸入在 T 日 13:30 已可得。新的 PIT 版本須另存 availability、revision 與 decision time。
- failed／partial collect run 不分析或追蹤。明確官方 no-data 且無列的非交易日可略過；錯日、缺報告日期或無法證實的空 payload 必須 fail closed。
- `observation` 表示該策略輸入完整、規則已判定但條件未成立；缺 entry／target／RR 是正常狀態。只有 strategy contract 明確提供合法等待價位時才能顯示等待突破／回踩，否則顯示「暫無研究條件／持續觀察」且摘要 blocker 為空。

## breakout_v1

| 條件 | 定義 |
| --- | --- |
| 突破 | `close[T] > max(high[T-20:T-1])`；前 20 個交易日不含 T。 |
| 量能 | `volume[T] / mean(volume[T-20:T-1]) >= 1.20`。 |
| 族群 | 群組等權 20 日報酬 − TAIEX 20 日報酬 `> 0`。 |
| 法人 | `sum(foreign + trust + dealer, 5d) / average_daily_volume_20d >= -0.003`；分子為 5 日淨股數，分母為含 T 的 20 日均量（股），比率無單位，語意為 5 日淨賣超達 20 日均量的 0.3%。公式識別 `institutional-flow/v2-shares-per-share-volume`；原股÷TWD 成交額的 `institutional-flow/v1-shares-per-twd-turnover` 單位不一致，已不計算。 |
| 融資 | 5 日融資餘額變動比 `<= 0.05`。 |

任何一項不足即 `data_incomplete`，不產生 actionable signal。這只判定單一策略列；同標的同 as-of 的另一條完整策略不得被連帶降級，聚合見 [PRODUCT_SPEC](PRODUCT_SPEC.md#action-merge)。

## pullback_v1

- 至少 60 根日線，`MA20 > MA60`，且 `close[T] >= MA60[T]`。
- 支撐區：`0.97 <= close[T] / MA20[T] <= 1.02`。
- 量能：`0.60 <= volume[T] / mean(volume[T-20:T-1]) <= 1.20`。
- 族群、法人與融資確認沿用 breakout 的 20／5／20／5 日定義；任一不足即 fail closed。

## 價位、ETF 與生命週期

- 合法 entry type 只有 breakout 與 pullback；entry、invalid、targets 必須為有限正數。
- `invalid_price < entry < target_1`；第一目標 RR 必須 `>= 1.5`；存在的 `target_2 > target_1`。
- IPO 少於 20 根不觀察，20–59 根只可 observation，至少 60 根才可 actionable。
- ETF 全部收集、分類並進 ETF 分榜。broad_market、dividend、sector、thematic、commodity 可套一般策略；bond、leveraged、inverse 回傳 `etf_category_excluded_from_actionable_signals:<category>`，仍可收集與排行。

    observation -> conditional -> active -> target_1_hit -> target_2_hit -> settled
                      |              +-> invalidated / expired / incomparable -> settled
                      +-> data_incomplete / invalid_levels / expired

## hot_group_v1

基準為 TAIEX 調整收盤價；相對報酬、廣度、量能、法人、催化劑權重依序為 35%、25%、15%、15%、10%。

| 分項 | 公式 |
| --- | --- |
| 相對報酬 | 群組等權超額報酬；1／5／20 日按 20%／30%／50% 加權後取同榜 percentile。 |
| 廣度 | 成員跑贏 TAIEX 的比例；1／5／20 日採相同 20%／30%／50% 權重。 |
| 量能 | `volume_1d / prior_20d_avg` 與 `mean(volume_5d) / prior_20d_avg` 各 50%，取同榜 percentile。 |
| 法人 | 5 日三大法人淨股數／含 T 的 20 日成交量合計（股），取同榜 percentile。 |
| 催化劑 | MOPS／TWSE-TPEx 公告／申報事件；1／5／20 日按 50%／30%／20% 加權，3 件封頂。 |

membership 必須在 score date 有效；每個股票榜或 ETF 類別分區至少 3 檔合格成員。事件 missing policy：

- 官方事件完整覆蓋 1／5／20 日窗口且沒有已核實事件時，催化劑才是有效 0。
- unsupported、partial、錯日、缺日或事件—族群關聯未核實時，催化劑為 null，不能改成 0 或推測方向。
- 只有其餘四個 component 全部完整，且同榜同日所有合格群組一致為 event unsupported 時，才計算 `(0.35×相對報酬 + 0.25×廣度 + 0.15×量能 + 0.15×法人流) / 0.90`；品質固定為 partial。
- 五個 component 全部完整才可稱「完整熱門」。四分項 observation 不得產生候選或 action，也不得虛構事件理由。

歷史 coverage 見 [DATA_SOURCES](DATA_SOURCES.md)；每次仍依實際資料判斷。

## 技術指標

版本 `indicators/v1`；公式與參數集中在 `backend/app/indicators.py`（`INDICATOR_VERSION`、`PARAMETERS`、`REQUIRED_BARS`），批次在 `backend/worker/indicator_batch.py`。改公式、參數或不足規則必須升版；`technical_indicators` 以（標的、日期、`formula_version`）為唯一鍵，新版本另寫列，不覆寫舊版本結果。

**輸入與價格基準**

- 輸入是 DB 保存的日線 `market_bars`。停牌列（`is_suspended`）與無效列（OHLC 非有限正數、`low` 高於開收或 `high` 低於開收、成交量缺漏或為負）不進任何窗口、不補值；該日每欄為 null，原因 `suspended`／`invalid_bar`。
- 窗口以該股「可用日線根數」計，不比對交易所日曆；缺日不補，前後兩根直接相鄰。
- 價格基準 `as_of_date_raw_basis`：T 日的值以 T 日原始價為基準，T 以前的價格依 DB 已收錄的除權息、分割事件（`worker.pipeline._action_factor_by_bar`）換算到 T 日基準，所以 T 日的均線與 T 日原始 K 線同一尺度；之後才發生的事件不影響 T。未收錄的事件等同不還原。成交量不還原。

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

EMA 與 Wilder 平滑依賴全部可用歷史，起算點是該股在 DB 的第一根可用日線；DB 往前回補後要重算（見 [OPERATIONS §3](OPERATIONS.md#3-現有-worker-cli)）。

`technical_features` 自本版起不再保存 `prior_20_highs`／`prior_20_lows`／`prior_20_volumes` 陣列，其他欄位語意不變；`breakout_v1`／`pullback_v1` 與 `hot_group_v1` 需要的前 20 根高點與量改由 `market_bars` 即時切取（`worker.pipeline._prior_20_window`），切法與數值和原陣列相同，公式不變。

**資料不足**：可用根數少於上表時該欄為 null，原因 `insufficient_bars`，並保存 `bar_count`（含 T 的可用根數），API 另附 `required_bars` 讓畫面說明「需 N 根、現有 M 根」。RSI 窗口內完全沒有漲跌時為 null，原因 `no_price_change`。批次尚未寫入的日期，API 回 `not_computed`。

**週線**：由日線聚合，依 ISO 週（週一起算；補班交易日併入當週）分組，只用可用日線：開＝首日開、高＝最高高、低＝最低低、收＝末日收、量＝加總，`date` 為該週最後一個交易日並附 `week_start`、`trading_days`。週指標以週線序列套用同一公式與參數重算（MA5 即 5 週），價格基準為該週最後一日；整週停牌則無該週。週線指標於 API 請求時計算，不入庫。

**API**：`GET /api/stocks/{exchange}/{symbol}/bars?interval=day|week&limit=N`（`limit` 1～1500，預設 250，取最近 N 根）。每根回 OHLCV、來源、`bar_count`、上表各欄與 `reasons`（只列 null 欄位的原因）；頂層附 `data_as_of`、行情 `sources` 與 `indicators`（版本、價格基準、參數、`required_bars`、欄位清單、指標來源與日線批次計算時間）。日線指標讀 `technical_indicators`，週線即時計算。

## Tracking 與 technical backtest 口徑

1. T+1 起依觸發條件成交；買賣各採不利 5 bps 滑價，淨報酬扣預設 30 bps round-trip 成本，並寫入 evidence。
2. 每筆訊號最多追蹤 20 個交易日；T+5、T+20 各寫一筆 settlement。
3. 公司行動需可追溯調整因子；停牌、缺可判定價格或同日 stop／target 皆觸及且順序未知時標 incomparable。
4. replay 固定 canonical version，保存日期範圍、cutoff、設定快照與執行數；相同成功 request key 可重用既有 run。
5. audit 保存 observation、data_incomplete 等所有規則列；technical summary 只納入 actionable evidence，按策略／標的類型／T+5、T+20 分組。
6. 三個月或更短一律標 `insufficient_sample`；更長也不等於參數最佳化、walk-forward、獨立 OOS 或策略有效。勝率不能單獨決定採用。

## 已知實作偏差與版本修正要求

1. worker 的 `atr14` 是最多 14 根 high-low 的平均，不含前收盤的 True Range，不是 Wilder ATR。
2. 舊 conditional 的 `confidence=0.75` 沒有校準證據，只可標示為舊版固定值，不得稱 75% 勝率；rule-only 的數值為 null。
3. `_risk_levels` 以固定風險倍數產生 1.6R／3R，合法 RR 只證明算術關係，不代表可成交、壓力位或預測。
4. T 日 13:30 cutoff 可能早於法人等盤後資料，PIT 版本須另存 availability／revision／decision time。
5. 30 bps 成本與單邊 5 bps 滑價是固定假設，不區分商品與情境。
6. `StrategyVersion` 的唯一鍵是（`name`、`version`、`formula_version`），由 alembic `0009_strategy_formula_version` 與 fallback 建立。
7. 0009 遷移把既存列標為快照宣告的已知公式、與 v2 之前三個 canonical 快照（固定 SHA-256 清單）完全相同者標 `institutional-flow/v1-shares-per-twd-turnover`，其餘標 `unclassified/<reason>`，不猜測。
8. 非 v2 公式的列設 `active=false`，id、`version`、`config_json`、快照不改，舊訊號仍指向原列，讀取時 `strategy.active` 由 true 變 false。
9. `_ensure_strategies` 只取（名稱、版本、目前公式）的列或新建，不重用 v1 或 `unclassified` 列，取到的列與 canonical 不符時以 `strategy_snapshot_mismatch` 拒用。
10. `analysis` 的 `signal_key` 不含公式，同鍵訊號屬於其他公式時以 `signal_formula_conflict` 拒絕覆寫，`analyze` 以 `StrategyVersionError` 結束且不提交該次結果，`daily` 不進入 evaluate。
11. v2 之前已有 `analysis` 訊號的（標的、日期、策略）不能以 v2 在 `analysis` 命名空間重算；新日期與 backtest 不受影響。
12. 0009 遷移只支援 SQLite，其他方言不分類既存列。
13. `GET /api/strategies` 每列含 `id`（`StrategyVersion` 整數主鍵）與 `formula_version`（庫內原值，含 `unclassified/<reason>`）。
14. DB 路徑的法人比率（`backend/worker/pipeline.py` 的 `_validated_flow_and_volume_inputs`）以 T（含）以前最後 20 根非停牌 bar 計算、最後 5 根須有籌碼列，不核對交易所日曆，也不要求最後一根就是 T。
