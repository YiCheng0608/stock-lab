<!-- owns: breakout_v1、pullback_v1、breakout_v2／pullback_v2、breakout_v3／pullback_v3 -->
# breakout／pullback

## breakout_v1

| 條件 | 定義 |
| --- | --- |
| 突破 | `close[T] > max(high[T-20:T-1])`；前 20 個交易日不含 T。 |
| 量能 | `volume[T] / mean(volume[T-20:T-1]) >= 1.20`。 |
| 族群 | 群組等權 20 日報酬 − TAIEX 20 日報酬 `> 0`。 |
| 法人 | `sum(foreign + trust + dealer, 5d) / average_daily_volume_20d >= -0.003`；分子為 5 日淨股數，分母為含 T 的 20 日均量（股），比率無單位，語意為 5 日淨賣超達 20 日均量的 0.3%。公式識別 `institutional-flow/v2-shares-per-share-volume`。 |
| 融資 | 5 日融資餘額變動比 `<= 0.05`。 |

任何一項不足即 `data_incomplete`，不產生 actionable signal。這只判定單一策略列；同標的同 as-of 的另一條完整策略不得被連帶降級，聚合見 [PRODUCT_SPEC](../PRODUCT_SPEC.md#action-merge)。

## pullback_v1

- 至少 60 根日線，`MA20 > MA60`，且 `close[T] >= MA60[T]`。
- 支撐區：`0.97 <= close[T] / MA20[T] <= 1.02`；量能：`0.60 <= volume[T] / mean(volume[T-20:T-1]) <= 1.20`。
- 族群、法人與融資確認沿用 breakout 的 20／5／20／5 日定義；任一不足即 fail closed。

## breakout_v2／pullback_v2

前一版策略（[#392](https://github.com/YiCheng0608/stock-lab/issues/392)），現行為 [breakout_v3／pullback_v3](#breakout_v3pullback_v3)。條件、門檻、價位、`kind`、`entry_type` 都與 [breakout_v1](#breakout_v1)、[pullback_v1](#pullback_v1) 相同（`config` 只多 `supersedes` 與 `data_policy.margin_financing_eligibility`，version `2.0.0`），只差融資條件的「不適用」：

- **融資標的判定**（`app.margin_lists.margin_financing_state`，讀 [融資標的清單](../DATA_SOURCES.md#融資標的清單)，窗口與 5 日融資變動比相同：含 T 的 6 個非停牌交易日）：
  - 變動比算得出來：照 v1 判定。
  - T 日清單已存而且沒有這個代號：**不適用**（非融資標的）。
  - 窗口 6 天的清單都已存，T 有列但窗口內有一天沒有（新納入）：**不適用**，因為這段窗口的變動比沒有定義。
  - 其餘（T 日清單沒存、窗口有一天沒存、在清單上但缺融資值）：**缺資料**，與 v1 相同，fail closed 為 `data_incomplete`。
- **不適用時**：略過融資確認，不擋成立也不算未成立；其他條件照判。`rule_evidence_json.inputs.margin_eligibility` 記 `applicable`／`not_applicable`／`missing`。條件清單的 `margin_financing` 記 `satisfied = null`、`reasons = ["margin_financing_not_applicable"]`；條件價位不把它算缺項；決策摘要的缺項不列融資，籌碼完整度不檢查融資欄。
- **5 日前融資餘額為 0** 的融資標的（分母為 0）仍是缺資料；v3 改為依餘額判定。
- **不改的部分**：`hot_group_v1` 與候選評分的融資分項。
- **v1 不改寫**：analyze 只寫 `REGISTRY` 的策略。v1 留在 `app.strategies.SUPERSEDED`，舊訊號與它們的條件價位照舊可讀，見[策略框架與 registry](README.md#策略框架與-registry)。

## breakout_v3／pullback_v3

現行策略（[#404](https://github.com/YiCheng0608/stock-lab/issues/404)）。條件、門檻、價位、`kind`、`entry_type` 與融資「不適用」都與 [breakout_v2／pullback_v2](#breakout_v2pullback_v2) 相同（`config` 只改 `name`、`version` `3.0.0`、`supersedes`，並多 `data_policy.margin_zero_base`），只差 5 日前融資餘額為 0 的判定：

- **零基期**（`app.margin_zero_base.zero_base_state`）：5 日融資變動比的分母 `margin_balance[T-5]` 為 0 時比率沒有定義，`margin_balance_change_ratio_5d` 照舊記 null（`hot_group_v1` 與候選評分的融資分項讀的比率不變）。窗口與比率相同（含 T 的 6 個非停牌交易日，6 天都要有籌碼列，`T-5` 與 T 的餘額都要有值；中間日只看籌碼列存在，不看餘額，與比率相同）：
  - `T-5` 與 T 都是 0：`zero_base_unchanged`，變動視為 0，融資條件成立，判定與比率為 0 時相同。6 天都是 0 屬於這一種；和比率一樣只看頭尾兩天。
  - `T-5` 是 0、T 大於 0：`zero_base_increased`，視為增加異常，記 `margin_financing_increase_abnormal`，融資條件不成立；其他條件照判，理由順序與比率超過 `0.05` 時相同。其他條件缺資料時仍是 `data_incomplete`，不改成不成立。
  - 窗口內缺籌碼列、`T-5` 或 T 缺餘額：仍是缺資料，fail closed 為 `data_incomplete`。
- **先後**：非融資標的的「不適用」（v2 規則）先判；不適用時不讀零基期。其餘標的（`margin_eligibility` 為 `applicable` 或 `missing`，含清單沒存的）都依餘額判零基期。
- **證據**：`rule_evidence_json.inputs.margin_zero_base` 記 `zero_base_unchanged`／`zero_base_increased`，比率有定義或缺資料時為 null；`margin_eligibility` 照 v2 規則（只看比率與清單，所以零基期的標的記 `missing`）。條件清單的 `margin_financing`：不變時 `actual = 0`、成立；增加時 `actual = null`、不成立。條件價位與決策摘要的缺項不把零基期的融資算缺項。
- **v2 不改寫**：analyze 只寫 `REGISTRY` 的策略；v2 與 v1 都在 `app.strategies.SUPERSEDED`，舊訊號照舊可讀，同一標的同一天只讀最新的一版，見[策略框架與 registry](README.md#策略框架與-registry)。候選池改由 [candidate_score_v5](candidate_score.md#candidate_score_v5) 讀 v3。
