# Canonical v1 規格

版本基準保留；文件核對日：2026-09-11。本輪不重定義 v1 公式、不重算或改寫歷史訊號。下一版方向與驗證見 [STRATEGIES](STRATEGIES.md)，已知實作偏差見本文最後一節。文中的 P0／P1 與短樣本結果為原文件歷史範圍，非本輪 DB 驗證。

app/domain.py 是 breakout_v1、pullback_v1 與 hot_group_v1 的設定來源。worker 保存可序列化設定快照、rule evidence、data cutoff 與 raw provenance；所有不完整輸入均採保守處理。

| 範圍 | 原有程式能力 | 原文件的歷史資料紀錄與限制 |
| --- | --- | --- |
| v1 evaluator、價位／RR、生命週期、hot-group | 已接入 worker／API | 不代表策略已採用。 |
| 官方 universe、OHLCV、TAIEX、MOPS、公司行動、raw provenance | 已接入 | P0 已有 65 個 verified TAIEX sessions；events、fundamentals、corporate actions coverage 仍有 partial／unsupported。 |
| TWSE／TPEx chips | 已接入 | P0 有 148,346 筆 chips；個別標的仍依 20／60 日 gap 維持 partial／missing。 |
| T+1、T+5／T+20 tracking | 已接入 | 歷史 P1 原規劃只分析 2026-09-08；P0 本身不構成 tracking 或績效結論，也不限制未來分析日期。 |
| technical backtest、run audit、cutoff、actionable-only summary | 已接入 | 三個月或較短為 insufficient_sample。 |
| walk-forward、獨立 OOS、採用結論 | 尚未完成 | 不得由目前訊號或短樣本推論績效。 |

## 共通原則

- T 是訊號收盤日；最早成交是 T+1，不能以 T 收盤當成交價。
- 價格與量必須是有限正數。NaN、Infinity、交易日不足、缺少必要資料、停牌或不可重建的資料路徑，一律是 data_incomplete 或 incomparable。
- 歷史 v1 以 T 作訊號日 cutoff；日曆日期不等於來源可得時間。盤後才公開的資料不可宣稱在 T 日 13:30 已知，詳見最後一節的時間缺口。
- 一般 daily 流程遇到 failed 或 partial run 不分析或追蹤，現有 analyze 也檢查最新 collect run。舊 P1 的 2026-09-08 範圍化作業是歷史驗收設計，不是已存在的 analyze --date 功能；未來局部 gate 仍須實作／驗收，不會用 0 補足。
- TWSE 明確 no-data 且無列的日期可安全略過；報告日期錯誤或沒有日期的 payload 不可被拿來代表其他交易日，必須 fail-closed。
- `observation` 表示該策略的 canonical 輸入完整、規則已判定但條件未成立；它不是 `data_incomplete`，且 entry／target／RR 缺席屬正常。只有 observation contract 明確輸出有限合法的等待價位時，產品層才可顯示等待突破／回踩；否則行動摘要是「暫無研究條件／繼續觀察」，summary blocker 為空並保留未通過理由。

## breakout_v1

| 條件 | 定義 |
| --- | --- |
| 突破 | close[T] > max(high[T-20:T-1])；前 20 個交易日不含訊號日。 |
| 量能 | volume[T] / mean(volume[T-20:T-1]) >= 1.20。 |
| 族群 | 等權群組 20 日報酬減 TAIEX（臺灣加權指數）20 日報酬 > 0。 |
| 法人 | sum(foreign + trust + dealer, 5d) / average_daily_turnover_20d >= -0.003。 |
| 融資 | 5 日融資餘額變動比 <= 0.05。 |

任何一項資料不足即 data_incomplete，不產生 actionable signal。這是**單一 v1 策略列**的判定；同一標的、同一資料截止日的另一條 breakout_v1 或 pullback_v1 若已完整通過，不得因此在行動摘要被一併降級，合併規則見 [現行行動合併契約](PRODUCT_SPEC.md#action-merge)。

## pullback_v1

- 至少 60 根日線，MA20 > MA60，且 close[T] >= MA60[T]。
- 支撐區：0.97 <= close[T] / MA20[T] <= 1.02。
- 量能：0.60 <= volume[T] / mean(volume[T-20:T-1]) <= 1.20。
- 族群、法人與融資確認沿用 breakout 的 20／5／20／5 日定義；任何不足即 fail-closed。

## 價位、ETF 與生命週期

- 合法 entry type 僅有 breakout 與 pullback；entry、invalid、targets 必須是有限正數。
- invalid_price < entry < target_1，第一目標風險報酬比必須 >= 1.5；存在的 target_2 必須高於 target_1。
- IPO 少於 20 根日線不得觀察，20–59 根只能 observation，至少 60 根才可 actionable。
- ETF 一律蒐集、分類並進入 ETF hot-group 分榜。broad_market、dividend、sector、thematic、commodity 可套用一般策略；bond、leveraged、inverse 必須回傳 etf_category_excluded_from_actionable_signals:&lt;category&gt;。後三類仍被收集與排行，只是不會成為一般 v1 actionable signal。

    observation -> conditional -> active -> target_1_hit -> target_2_hit -> settled
                      |              +-> invalidated / expired / incomparable -> settled
                      +-> data_incomplete / invalid_levels / expired

## hot_group_v1

基準是 TAIEX 調整收盤價，權重為相對報酬 35%、廣度 25%、量能 15%、法人流 15%、催化劑 10%。

| 分項 | 公式 |
| --- | --- |
| 相對報酬 | 群組等權超額報酬，1／5／20 日以 20%／30%／50% 加權，同榜 percentile。 |
| 廣度 | 成員超過 TAIEX 的比例，1／5／20 日同權重。 |
| 量能 | volume_1d / prior_20d_avg 與 mean(volume_5d) / prior_20d_avg 各 50%，同榜 percentile。 |
| 法人 | 5 日三大法人淨額／20 日週轉額，同榜 percentile。 |
| 催化劑 | MOPS／TWSE-TPEx 公告／申報事件，1／5／20 日 50%／30%／20%，3 件封頂。 |

membership 必須在 score date 有效；每個股票榜或 ETF 類別分區至少需要 3 檔合格成員。催化劑沒有資料時為 null，以其餘權重重算且品質為 partial；可用權重少於 90% 時不給分數。

催化劑的 missing policy 必須精確區分：

- 官方事件資料已完整覆蓋該 1／5／20 日窗口、但沒有已核實事件時，催化劑才是有效的 0。
- 事件來源 unsupported、partial、錯日、缺日或事件—族群關聯未核實時，催化劑必為 null；不得以 0、正向、負向或中性事件替代。
- 只有相對報酬、廣度、量能、法人流四個 component 全部完整，而且同一榜、同一 score date 的所有合格群組都一致為 event unsupported 時，才可按既有 90% 最低可用權重計算四 component 的技術與籌碼觀察分數。其計算是 (0.35×相對報酬 + 0.25×廣度 + 0.15×量能 + 0.15×法人流)／0.90；輸出品質固定為 partial。
- 五個 component 都完整才可作「完整熱門」排行。四 component observation 不是完整熱門、不得產生候選或 action，也不得把不存在或未核實的事件寫進理由。

歷史 P0 的 65 個事件 session 都是 unsupported，因此當時 P1 的完整熱門預期為 0。這個歷史結果不固定套用所有未來日期；每次仍依實際 coverage 判斷。歷史背景見 [PHASE3_PLAN](PHASE3_PLAN.md)，現行呈現見 [PRODUCT_SPEC](PRODUCT_SPEC.md)。

## Tracking 與 technical backtest 口徑

1. T+1 開始依觸發條件成交；買賣各採不利 5 bps 滑價，淨報酬扣預設 30 bps round-trip 成本，並寫入 evidence。
2. 每筆訊號最多逐日追蹤 20 個交易日，寫入 SignalEvaluation，於 T+5、T+20 各寫一筆 SignalSettlement。
3. 公司行動用可追溯調整因子處理；停牌、缺可判定價格或同日 stop／target 同時觸及時標為 incomparable，不假設有利順序。TPEx suspension history 可提供事件證據；TWSE 完整歷史停牌 coverage 尚不完整。
4. backtest 回放固定 canonical version，保存日期範圍、cutoff、設定快照與執行數。相同成功 request key 會重用既有 run。
5. replay 保存 observation、data_incomplete 等所有規則 audit row；technical summary 僅將 actionable evidence 納入樣本，按策略／標的類型／T+5、T+20 分組。
6. 三個月或更短的範圍一律標 insufficient_sample。它不是參數最佳化、策略績效驗證、walk-forward 或獨立 OOS；勝率不可作為單一採用依據。

## 2026-09-11 已知實作偏差與版本修正要求

1. worker 的 atr14 目前是最近最多 14 根 high-low 平均，缺少前收盤形成的 True Range，不能當作已正確實作的標準 ATR。
2. conditional 訊號固定 confidence=0.75，沒有訓練／校準證據，不代表 75% 勝率；既有資料保留原值與版本，產品不得解讀為預測。
3. _risk_levels 使用固定風險倍數產生 1.6R／3R 目標；RR 有效僅代表價位算術關係，不代表可成交、合理壓力位或模型預測。
4. data_cutoff 保存 T 日 13:30，但必要法人／其他資料可能盤後才公布。下一版需補 availability／revision／decision 時間，並以修正版本重現，不能以日期檢查冒充無未來資訊。
5. 30 bps 成本與單邊 5 bps 滑價是固定假設；下一版應區分商品、交易情境和實際費用／流動性，且保持舊結果可重現。

以上尚未修正程式。修改公式、指標、時間、成本或機率語意時，需建立可追溯版本和前後差異，不沿用同名同版本覆寫歷史。這份規格仍保留原 v1 權重、eligibility、價位關係與 lifecycle，作基準與稽核，不作策略採用證明。
