# 策略、交易計畫與 AI 驗證

更新：2026-09-12。現行固定規則基準見 [V1_SPEC](V1_SPEC.md)。C-001 只完成 rule-only confidence 的最小相容語意修正；C-002 已加入並通過 review 的 ATR 純核心，但尚未接入正式 worker；C-005 已通過 B4a read-time 規則參考價語意 review。這些都不代表新 trade plan、PIT 接線、策略／模型或整個 R0 已完成。優先順序與狀態見 [ROADMAP](ROADMAP.md)。

## 1. 現行能力與已知限制

主要 worker 已有特徵計算、breakout_v1／pullback_v1、族群分數、rule evidence、條件訊號、逐日追蹤與 T+5／T+20 結算。三大法人／融資有官方輸入；缺值不補 0。現行流程未見已訓練並驗證的 AI 預測模型。

| 項目 | 靜態核對的現況 | 處理 |
| --- | --- | --- |
| atr14 | worker 仍使用最近最多 14 根 high-low 平均；另有已 review、未接線的 `technical_v2_atr14_wilder` 純核心 | 新核心納入 prev close、14 TR seed 與 Wilder recurrence；後續仍需版本隔離 artifact、來源接線與 replay。 |
| confidence | 新 rule-only signal 的 legacy 數值欄位為 null；既有同 key 數值保留 | `signal-confidence/v2` 的 `not_calibrated`、legacy `v1-fixed` 的 `legacy_fixed_value` 及 `unknown_numeric` 均明示非校準、非機率；不得作勝率。 |
| 點位 | 風險距離約為 max(atr 或 entry×2%, entry×1%)，目標為 entry+1.6R／3R；Round05 B4a read-time semantics 已 review | 僅 `breakout_v1@1.0.0`／`pullback_v1@1.0.0` 可套 canonical 固定規則標籤；其他 identity 為 unknown。保留數值作基準，不冒稱 AI 預測或成交。 |
| 決策 cutoff | 訊號寫成 T 日 13:30，但部分輸入盤後才公開 | 區分市場日期、可得時間與決策時間；需修正時間模型。 |
| 成本 | 買賣各 5 bps 不利滑價、30 bps round-trip 成本假設 | 是模型假設，不是全商品／全交易的實際費率。 |
| 當沖／分點 | 部分 model 欄位預留，主要收集／訊號流程尚未接齊 | 不推斷資金身分，不以空欄位算風險分數。 |

程式入口：[pipeline](../backend/worker/pipeline.py)、[ATR 純核心](../backend/app/atr.py)、[domain](../backend/app/domain.py)、[config](../backend/app/config.py)。C-001 未改規則 gate、價位或執行，也未重跑正式分析；其當時統籌隔離 backend 完整 pytest 為 128 passed，且前端有已證明修改前後相同的既存 presentation assertion failure。C-002 後來只修正該過時測試期待、沒有改產品文字；統籌 final ATR targeted 為 28 passed、0.26 秒、exit 0，`presentation.test.ts` 編譯與完整執行皆 exit 0。這不代表最後修正後的全 backend、全 frontend suite 或瀏覽器 UI 已驗收；完整限制與 hash 見 [R0 契約](R0_IMPLEMENTATION.md#46-c-002-final-review-證據與未完成邊界)。

## 2. v1 保留與新版本邊界

- breakout_v1、pullback_v1 及 hot_group_v1 保留作可重現基準；IPO／ETF eligibility、缺值與 incomparable 規則見 V1_SPEC。
- hot_group_v1 的事件數量不是利多強度。下一版的事件方向／新資訊、題材、分開的法人特徵不得偷偷放入同名舊模型。
- 官方產業相對強度與經核實 membership 仍是 v1 必要資料；完整熱門標籤與事件脈絡不另加成個股策略硬 gate。
- 主／替代條件、完整 observation、資料待補與持倉風險合併，以 [產品合併契約](PRODUCT_SPEC.md#action-merge) 為準。
- 更動 ATR、點位、成本、時間或特徵定義都需可辨識版本與配置。舊 run、輸入／raw、規則證據及結果保留；不能讓同一版本下的歷史績效悄悄改變。
- `technical_v2_atr14_wilder` 目前是已 review、無 I/O 的純 artifact 核心，不是策略已採用的 feature。它強制 expected sessions、decision time、共同比價基礎與公司行動 coverage／availability evidence；公司行動是整個 artifact basis 的完整 dependencies，任一項不合格就不能讓任何 TR 進 warm-up。純核心只能驗證 caller metadata 的一致性與時間，不證明官方來源 truth。
- confidence 的本次改動以 `confidence_semantics.version`／`kind` 追蹤輸出語意，不冒稱 strategy 規則升版。legacy 固定值只在 breakout_v1／pullback_v1、strategy version 1.0.0 及值 0.75 同時成立時辨識；API 不信任 evidence 內自行宣告的機率 marker。完整雙版本 artifact／replay 尚未完成。
- 先修正基準再比較新功能，不能讓新模型只是勝過已知錯誤的舊算法就宣稱有效。
- 已 review 的 B4a 將規則 `breakout_price`／pullback zone／`reference_entry`／`invalid_price`／targets 與持倉 `average_cost`、使用者 stop、tracking `execution_price` 分開。pullback 保留現行 `zone_width=max((atr or close×1%)×0.5, close×0.5%)`，下緣是 `max(0.01, support-zone_width)` 後 round，不能漏掉 0.01 floor。legacy Signal 未保存可驗證的 price-basis identity 或含 offset 的 `decision_at`，所以 nested semantics 為 `null+reason`；不得由 `data_cutoff`、date-only 欄位或 naive `created_at` 猜測。`cost_included=false` 只表示 level 算式未扣成本，不否定 execution/backtest 另有 5 bps／30 bps 假設。完整矩陣與 fixture 限制見 [R0 §6.1](R0_IMPLEMENTATION.md#61-legacy-價位的強制標示)。

## 3. 下一版特徵研究

| 面向 | 待研究項目 | 解讀限制 |
| --- | --- | --- |
| 公司品質 | 營收／獲利變化、公告與重大公司風險 | 按實際公告可得時間；好公司不等於好買點。 |
| 事件機會 | 新資訊、受益／受害傳導、影響期間、反面證據 | 來源事實與推論分開；轉載不重複計。 |
| 族群／題材 | 相對強弱、熱度增減、廣度、領漲集中、題材生命週期 | 使用當時成員／分類；強勢可能已過度延伸。 |
| 籌碼 | 分類法人流、多日持續性、集中度、分點反轉、當沖及價格反應 | 只是彙總特徵；不確定辨識投資人身分／隔日沖。 |
| 技術位置 | 正確 ATR、支撐壓力、突破／回踩、量價、跳空、距均線延伸 | 每項有數學定義，先以兩策略做基準。 |
| 市場與交易風險 | 大盤／波動狀態、流動性、事件缺口、停牌、同題材曝險 | 高分不得越過硬性風險限制。 |

不預先為新特徵指定「一定有效」權重或門檻。新增特徵需比較增量效果，移除沒有穩健增益的複雜度。

## 4. 交易計畫與進出場（待實作）

第一版設計假設是盤後 long、數天至數週；精確期間和風險參數需另行決定。計畫不是成交紀錄，也不是模型自由生成的一段建議文字。

每份計畫至少定義：

1. 標的、策略／特徵／執行版本、decision_at、資料可用截止與有效期限。
2. 突破或回踩條件、確認方式、進場區間、不追價上限、最早執行時段。
3. 策略失效／價格停損、第一目標與後續退出規則；支撐壓力與風險距離的計算可重現。
4. 時間停損、事件前提失效、族群轉弱、移動停利或分批退出的明確 predicate；同時觸發的優先序。
5. 適用交易所／商品的價格級距、費用／稅、滑價、流動性／成交量限制與可成交假設。
6. 使用者單筆可承受損失、單股及同題材曝險上限；沒有風險預算就不生成具體張數。
7. 預期風險報酬、模型預測分布（若經驗證）、反面證據、資料缺項及不交易原因。

實際開盤／成交與參考價不同時，重新檢查風險報酬和上限；跳空超過不追價上限就拒絕，不假設總能在理想點位買到。stop 是觸發條件，不保證跳空時仍以 stop 價成交。

每筆計畫保留建立與更新歷史。無觸發、到期、資料待補、拒絕交易、未成交、模擬成交及使用者實際成交分開。個股多策略／多題材不能重複占用風險預算。

現行 T+5／T+20 保留比較窗口；新增實際退出時間需另外記錄，不能將固定窗口報酬誤稱真實交易損益。

## 5. AI 三部分與機率定義

| 部分 | 允許輸出 | 不應承擔 |
| --- | --- | --- |
| 新聞理解 | 來源摘要、事件類型、新資訊、關聯候選、正反面理由與引用 | 無來源的事實、自由報價、投資人身分判定。 |
| 量化評估 | 明確期間與事件定義下的機率／報酬分布、不確定性、適用範圍 | 以固定分數或模型自述信心冒充校準機率。 |
| 交易風險規則 | 觸發、價位、退出、部位約束與拒絕交易 | 因新聞文字指令或高分跳過風險限制。 |

預測目標需先寫清楚。例如「計畫觸發且可成交後，H 個交易日內先觸及目標而非停損的機率」；另記未觸發／不可成交比例。H、目標、停損、成本及不可比標記必須固定版本。此處 H 是待決定參數，不是已選定策略。

資料完整度、規則通過狀態、新聞關聯證據程度、經校準的預測機率分欄保存。沒有樣本、校準失敗、適用範圍外或資料漂移時，機率留空並拒絕模型判斷。

## 6. 驗證方法與採用門檻（待建立）

- **Point-in-time**：資料、新聞、修訂、題材 membership、財報與公司行動皆按當時可得版本使用；盤後才可得的籌碼不可回填成收盤前已知。
- **歷史樣本**：保留下市／失敗標的與當時 universe；不能用今天熱門名單回測過去。規劃跨多種市場狀態的歷史資料，不能把 65 日窗口當訓練資料充分性證明。
- **時間切分**：訓練、調參／校準、最終測試分開；對重疊持有期做必要隔離，walk-forward 後仍保留獨立測試集。
- **模型記憶**：LLM 可能已從預訓練知道歷史結果；固定提示日期無法保證無洩漏。記錄模型版本／cutoff，另以前瞻模擬驗證，不把歷史摘要回放直接當預測證據。
- **公平比較**：技術基準、加入族群、新聞、籌碼、AI 使用相同 universe／時間／成本與執行限制，記錄所有嘗試而非只選最佳組合。
- **指標**：成本後報酬、最大回撤、尾部損失、有效樣本、成交率、曝險、不同市場狀態穩定性；機率另評 Brier／校準曲線等。勝率不單獨決定採用。
- **不可比與成本**：同日 stop／target 順序未知、缺價格或公司行動不可重建時保留 incomparable；報告其占比，不能刪掉後只報漂亮結果。成本參數做敏感度分析。
- **前瞻模擬**：每天先保存資料快照、候選與計畫，再記未來結果；保留零候選、未成交、模型失敗和撤回，避免事後挑選。
- **採用**：先定義樣本／校準／回撤／可成交等門檻，再看測試；未通過保持研究狀態。紙上結果與真實成交分開，通過也不等於永久有效。

現行 backtest 是固定版本 technical replay，保存 run metadata／request key 與 actionable-only summary。/api/backtest/summary 與 /research/backtest 提供研究摘要，/backtest 為相容轉址。三個月或更短依 v1 標 insufficient_sample；更長也不自動合格。

## 7. 參考依據

- [ATR 定義](https://www.tradingview.com/support/solutions/43000501823-average-true-range-atr/)：True Range 納入前收盤與跳空。
- [證交所券商買賣資料說明](https://bsr.twse.com.tw/bshtm/bsMenu.aspx)：資料包含自營及經紀客戶合計；分點身分推論有界線。
- [The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)：大量策略挑選可能造成樣本外失效，支持保留嘗試紀錄及獨立驗證。

參考資料用來界定方法與限制，不提供本專案策略已有效的證據。
