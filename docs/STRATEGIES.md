# 策略、交易計畫與 AI 驗證

更新：2026-09-16。固定規則基準見 [V1_SPEC](V1_SPEC.md)，能力與優先順序見 [ROADMAP](ROADMAP.md)。本文定義下一版研究、交易計畫、AI 與驗證方法；未具名驗收的項目仍待完成。

## 1. 現行能力與已知限制

主要 worker 已有特徵計算、`breakout_v1`／`pullback_v1`、族群分數、rule evidence、條件訊號、逐日追蹤與 T+5／T+20 結算。三大法人與融資使用官方輸入，缺值不補 0；目前沒有已訓練並驗證的 AI 預測模型。

| 項目 | 現況與限制 |
| --- | --- |
| ATR | worker 仍以最近最多 14 根 high-low 平均。已 review、未接線的 `technical_v2_atr14_wilder` 納入 prev close、14 TR seed 與 Wilder recurrence，並要求 expected sessions、decision time、共同比價 basis 與公司行動 coverage／availability；它只驗 caller metadata 一致性，不證明來源 truth。 |
| confidence | 新 rule-only signal 的 legacy 數值為 null；既有值保留。`signal-confidence/v2` 的 `not_calibrated`、legacy `v1-fixed` 的 `legacy_fixed_value` 與 `unknown_numeric` 都不是機率。只有策略名、version 1.0.0、值 0.75 同時符合時才辨識 legacy 固定值。 |
| 規則價位 | 現行風險距離約為 `max(atr 或 entry×2%, entry×1%)`，目標為 `entry+1.6R`／`entry+3R`；只對兩個 v1 策略 1.0.0 使用固定規則標籤，其他 identity 為 unknown。合法數值不代表預測或成交。 |
| 價位語意 | breakout、pullback、reference entry、invalid、targets、持倉成本、使用者 stop 與 tracking 成交價分開。pullback `zone_width=max((atr or close×1%)×0.5, close×0.5%)`，下界為 `round(max(0.01, support-zone_width))`。legacy signal 無可驗證 basis 或 offset-aware `decision_at` 時回傳 null＋reason。 |
| 時間 | 訊號曾寫為 T 日 13:30，但部分必要輸入盤後才公開。市場日期、資料 availability／revision 與 decision time 必須分開；現有日期 cutoff 不證明 PIT。 |
| 成本 | 買賣各 5 bps 不利滑價、30 bps round-trip 成本是固定模型假設，不是所有商品或交易的實際費率。`cost_included=false` 只表示 level 算式未扣成本。 |
| 當沖／分點 | model 有部分預留欄位，主要收集與訊號流程未接齊。不得從空欄位或分點推論特定資金身分。 |

## 2. v1 保留與新版本邊界

- `breakout_v1`、`pullback_v1`、`hot_group_v1` 保留作可重現基準；公式、IPO／ETF eligibility、缺值與 incomparable 規則見 [V1_SPEC](V1_SPEC.md)。
- 新的事件方向、題材、法人拆分、ATR、價位、成本、時間或特徵不得放進同名舊模型。每次變更都需可辨識版本、設定、輸入與結果；舊 run 不可被悄悄改寫。
- hot-group 事件數不是利多強度。有效 membership 與群組相對強度仍是 v1 必要資料；完整熱門與事件脈絡不另加成個股策略硬 gate。
- 主／替代條件、完整 observation、資料待補與持倉風險的合併以 [PRODUCT_SPEC](PRODUCT_SPEC.md#action-merge) 為準。
- 先修正基準再比較新功能；新模型只勝過已知錯誤的舊算法，不能據此宣稱有效。

## 3. 下一版特徵研究

| 面向 | 待研究 | 限制 |
| --- | --- | --- |
| 公司品質 | 營收／獲利變化、公告與重大風險 | 依實際公告可得時間；好公司不等於好買點。 |
| 事件機會 | 新資訊、受益／受害傳導、期間與反證 | 事實和推論分開；轉載不重複計。 |
| 族群／題材 | 相對強弱、熱度、廣度、集中度、生命週期 | 使用當時成員／分類；強勢可能已過度延伸。 |
| 籌碼 | 分類法人流、持續性、集中度、分點反轉、當沖與價格反應 | 是彙總特徵，不能辨識特定投資人或隔日沖。 |
| 技術位置 | 正確 ATR、支撐壓力、突破／回踩、量價、跳空、距均線延伸 | 每項先定義數學與資料 basis，再與 v1 比較。 |
| 市場與交易風險 | 大盤／波動、流動性、事件缺口、停牌、同題材曝險 | 高分不能越過硬性風險限制。 |

不預先指定新特徵必然有效的權重或門檻；只保留有穩健增量證據的複雜度。

## 4. 交易計畫與進出場（待實作）

第一版設計為盤後 long、持有數天至數週；精確期間與風險參數仍待決定。計畫不是成交紀錄或模型自由生成的建議文字，至少包含：

1. 標的、策略／特徵／執行版本、decision_at、資料 cutoff／availability 與有效期限。
2. 突破或回踩條件、確認方式、進場區間、不追價上限及最早執行時段。
3. 策略失效、使用者停損、目標、移動停利、分批退出、時間停損與事件失效的明確 predicate 及優先序。
4. 交易所價格級距、費用／稅、滑價、流動性、成交量與可成交假設。
5. 單筆可承受損失、單股及同題材曝險上限；未設定風險預算時不給具體張數。
6. 預期風險報酬、經驗證的預測分布（若有）、反證、缺項與拒絕交易原因。

開盤或實際成交偏離參考價時要重算風險與上限；跳空超過不追價上限則拒絕。stop 是觸發條件，不保證跳空時仍以 stop 價成交。建立、更新、未觸發、到期、資料待補、拒絕、未成交、模擬成交與使用者實際成交均分開留歷史。T+5／T+20 是比較窗口，不能冒充實際退出或真實損益。

## 5. AI 三部分與機率定義

| 部分 | 允許輸出 | 禁止替代 |
| --- | --- | --- |
| 新聞理解 | 有引用的摘要、事件、新資訊、關聯候選、正反理由 | 無來源事實、自由報價、投資人身分判定。 |
| 量化評估 | 明確期間與事件下的機率／報酬分布、不確定性與適用範圍 | 固定分數或模型自評冒充校準機率。 |
| 交易風險規則 | 可重現觸發、價位、退出、部位限制與拒絕交易 | 因文章指令或高分跳過風險 gate。 |

預測目標需先固定，例如「計畫觸發且可成交後，H 個交易日內先觸及目標而非停損的機率」，另記未觸發／不可成交比例。H、目標、停損、成本與 incomparable 定義都要版本化；H 尚未選定。資料完整度、規則狀態、關聯證據與校準機率分欄。樣本不足、校準失敗、超出適用範圍或漂移時，機率留空並拒絕判斷。

## 6. 驗證方法與採用門檻（待建立）

- **Point-in-time**：資料、新聞、修訂、membership、財報與公司行動只用當時可得版本。
- **歷史樣本**：保留下市／失敗標的與當時 universe；65 日或三個月窗口都不構成充分策略樣本。
- **時間切分**：訓練、調參／校準、最終測試分開；重疊持有期的隔離方法與窗口須在看最終測試前版本化核定；walk-forward 後仍保留獨立測試。
- **模型記憶**：LLM 預訓練可能知道歷史；提示日期不能消除洩漏。記錄模型版本／cutoff，另以前瞻模擬驗證。
- **公平比較**：技術基準與加入族群、新聞、籌碼、AI 的版本使用相同 universe、時間、成本與執行限制，記錄所有嘗試。
- **指標**：成本後報酬、最大回撤、尾部損失、有效樣本、成交率、曝險與市場狀態穩定性；機率另評 Brier／校準曲線，勝率不單獨決定採用。
- **不可比與成本**：同日 stop／target 順序未知、缺價格或公司行動不可重建時標 incomparable 並報占比；成本做敏感度分析。
- **前瞻模擬**：每天先保存快照、候選與計畫，再記結果；保留零候選、未成交、模型失敗與撤回。
- **採用**：在看最終測試前先定樣本、校準、回撤與可成交門檻；未過門檻維持研究狀態，通過也不等於永久有效。

現行 backtest 是固定版本 technical replay，保存 run metadata、request key 與 actionable-only summary。三個月或更短一律標 `insufficient_sample`；更長也不自動合格。

## 7. 參考依據

- [ATR 定義](https://www.tradingview.com/support/solutions/43000501823-average-true-range-atr/)
- [證交所券商買賣資料說明](https://bsr.twse.com.tw/bshtm/bsMenu.aspx)
- [The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)

這些資料只支持方法與限制，不證明本專案策略有效。
