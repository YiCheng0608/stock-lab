# Canonical v1 規格

本文只保存 `breakout_v1`、`pullback_v1`、`hot_group_v1`、價位、eligibility、生命週期與回測的 canonical 基準。下一版方向與驗證見 [STRATEGIES](STRATEGIES.md)，實作狀態與排程見 [ROADMAP](ROADMAP.md)。修改公式、時間、成本或機率語意時必須升版並保留舊 run、輸入、設定與結果；公式變更可由 config 的 `formula_version` 子版本升版（如法人 `institutional-flow/v2-shares-per-share-volume`），此時 `StrategyVersion.version` 維持 `1.0.0`，舊公式識別保留於 `domain.INSTITUTIONAL_FLOW_FORMULAS`。`StrategyVersion` 以（`name`、`version`、`formula_version`）識別：子版本升版時舊公式的列整列保留（id、`version`、`config_json`、快照不改），新公式另建一列，既存訊號仍指向其原列。

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

## Tracking 與 technical backtest 口徑

1. T+1 起依觸發條件成交；買賣各採不利 5 bps 滑價，淨報酬扣預設 30 bps round-trip 成本，並寫入 evidence。
2. 每筆訊號最多追蹤 20 個交易日；T+5、T+20 各寫一筆 settlement。
3. 公司行動需可追溯調整因子；停牌、缺可判定價格或同日 stop／target 皆觸及且順序未知時標 incomparable。
4. replay 固定 canonical version，保存日期範圍、cutoff、設定快照與執行數；相同成功 request key 可重用既有 run。
5. audit 保存 observation、data_incomplete 等所有規則列；technical summary 只納入 actionable evidence，按策略／標的類型／T+5、T+20 分組。
6. 三個月或更短一律標 `insufficient_sample`；更長也不等於參數最佳化、walk-forward、獨立 OOS 或策略有效。勝率不能單獨決定採用。

## 已知實作偏差與版本修正要求

1. worker 的 atr14 是最多 14 根 high-low 平均，缺少 prev close 的 True Range；Wilder ATR 純核心尚未接線。
2. 舊 conditional `confidence=0.75` 沒有校準證據；只可標示舊版固定值，不得稱 75% 勝率。新 rule-only 數值為 null。
3. `_risk_levels` 使用固定風險倍數產生 1.6R／3R；合法 RR 只證明算術關係，不代表可成交、壓力位或預測。
4. T 日 13:30 cutoff 可能早於法人等盤後資料；新的 PIT 版本須補 availability／revision／decision time。
5. 30 bps 成本與單邊 5 bps 滑價是固定假設；新版本需區分商品與情境並保持舊結果可重現。
6. `StrategyVersion` 的唯一鍵是（`name`、`version`、`formula_version`），由 alembic `0009_strategy_formula_version` 與 fallback 建立。遷移對每個既存列標一個 `formula_version`：快照宣告的已知公式值；沒有宣告但與 v2 之前三個 canonical 快照（固定的 SHA-256 清單，名稱與版本須相符）的 canonical JSON 完全相同者標 `institutional-flow/v1-shares-per-twd-turnover`；其餘（空快照、無法解析、`config_json` 與快照不一致、未知公式值、不在清單內的內容）標具名 `unclassified/<reason>`，不猜測。非 v2 公式的列設 `active=false`，id、`version`、`config_json`、快照不改，舊訊號仍指向原列。`_ensure_strategies` 只取（名稱、版本、目前公式）的列或新建，不重用 v1 或 `unclassified` 列、不補寫空快照；取到的列與 canonical 不符時以 `strategy_snapshot_mismatch` 拒用。`analysis` 的 `signal_key` 不含公式，`_upsert_signal_for_strategy` 遇同鍵訊號所屬列的公式與目前不同（含無法歸屬的列）時，以 `signal_formula_conflict` 拒絕覆寫，舊訊號整列保留。殘餘限制：
   - v2 之前已有 `analysis` 訊號的（標的、日期、策略）不能以 v2 在 `analysis` 命名空間重算；新日期與 backtest 不受影響。要以 v2 重算這些歷史日期，須另行調整 `signal_key` 格式。
   - 舊列 `active=false`，所以舊訊號讀取結果的 `strategy.active` 由 true 變 false，其餘欄位不變。
   - 只認得固定清單內的 v2 前快照；更早或被改動的快照標為 `unclassified`。
   - 本條只處理既存快照的保存；在正式 DB 執行遷移、以新公式跑訊號另需授權。
7. DB 路徑的法人比率（`backend/worker/pipeline.py` 的 `_validated_flow_and_volume_inputs`）以該標的非停牌 bar 取截止日 T（含）以前最後 20 根，最後 5 根的日期須有籌碼列；它不核對交易所日曆，也不要求最後一根就是 T：停牌日被跳過；T 本身沒有非停牌 bar 時（strategy 路徑在 T 沒有 bar 列時另不產生訊號），窗口結束於更早一日；缺某個交易日的 bar 時，20 根橫跨 21 個平日。這些情形只要窗口仍滿 20 根且量、籌碼完整就照算，不拒用。取得模組路徑另有 24 日日曆全等檢查（見 [SOURCE_REGISTRY](SOURCE_REGISTRY.md)），DB 路徑沒有。

以上未全部修正或接入正式流程；狀態以 ROADMAP 為準。
