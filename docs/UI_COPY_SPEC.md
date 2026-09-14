# UI 文案與資訊層級規格

更新：2026-09-14。本文是日常頁的中文、資訊層級、單位、unknown 與 reason code 契約，不表示所有案例已驗收。能力狀態見 [ROADMAP](ROADMAP.md)，策略合併判定見 [PRODUCT_SPEC](PRODUCT_SPEC.md#action-merge)。

## 1. 共通原則

- 日常頁使用可理解、可追溯的繁體中文；enum、欄位名、資料庫 key、raw ID 與 ISO 時間只可在預設收合的研究／系統層。
- 每個「完整」都須說明資料層與用途。官方事實、規則關聯、推論與 unknown 分開；unknown 不是負面訊號。
- Asia/Taipei 日期顯示 `YYYY/MM/DD`，日期時間顯示 `YYYY/MM/DD HH:mm`。
- 「現價」只用於可信即時報價；日資料一律寫「最近收盤（日期）」。缺少可驗證行情時不顯示價格結論。
- 台股紅漲綠跌須同時有正負號或文字，不能只靠顏色。

## 2. 禁止露出的內部詞與繁中對照

| 內部詞 | 日常頁 |
| --- | --- |
| DecisionSummary | 行動摘要 |
| data_insufficient／data_incomplete | 策略判斷資料待補 |
| canonical／canonical config snapshot | 固定研究規則／規則版本與稽核設定；只在研究詳情 |
| prior_20_highs／bars_20d／bars_60d／institutional_flow_5d | 前 20 個交易日高點／近 20 日行情／近 60 日行情／近 5 日法人籌碼 |
| company／taiwan／international | 個股公告／台灣官方事件／國際事件；尚未接入的來源不顯示空卡 |
| high confidence | 標的關聯已驗證；不得解讀成勝率 |
| medium confidence | 關聯由規則核實；可展開查看使用的方法與規則 |
| low／unknown confidence | 關聯尚未判定；不驅動進場、出場或其他交易動作 |
| impact_direction unknown | 影響尚未判定 |
| official_disclosure | 官方公告資料 |
| 未核實 Industry 名稱、代碼或 ID | 日常頁不顯示；系統頁寫「官方產業名稱待對照」 |

## 3. 三種資料完整度

| 資料層 | 完整 | 部分／缺失 | 只代表 |
| --- | --- | --- | --- |
| 來源擷取 | 來源擷取完整 | 來源擷取部分完成／失敗 | 來源與 raw 稽核；不代表欄位或歷史窗口完整。 |
| 當日行情 | 當日行情完整 | 當日行情部分缺漏／尚無可驗證行情 | 指定標的、市場與日期的 OHLCV。 |
| 策略判斷 | `<策略>條件資料完整` | `<策略>條件資料待補` | 該策略所需行情、TAIEX、membership、籌碼等輸入。 |

同頁可同時顯示「來源擷取完整 · 當日行情完整 · 回踩條件資料待補」，並列精確缺項。全市場 run 成功或資料列增加不能升格個別標的；全域 partial 也不能自動降級一條已完整策略。

同卡有兩條策略時使用「主研究條件資料完整 · 另一研究條件資料待補：<缺項>」。只有所有呈現條件都完整時才可省略範圍。完整 observation 沒有 entry／target／RR 仍是完整，不使用資料待補 badge。

## 4. 新聞卡文案與折疊

### 4.1 卡片正面

固定順序：分類與來源 → 兩行內原始標題 → 120 個全形字元或三行內摘要 → 來源時間 → 影響／關聯 → 相關標的 → 來源連結。標題只正規化連續空白與換行，列表截在兩行，詳情仍保留完整標題。`/news` 不展開全文；`/news/:id` 用「展開公告內容／收合公告內容」，只顯示可用的來源 description，不顯示 raw JSON 或內部 ID。

沒有摘要時寫「官方來源未提供摘要」。只有存在合法可用原文時，才可另顯示附引用與方法的「AI 摘要」；不得由標題或模型記憶補造。

### 4.2 日期與可信度

| 狀態 | 文案／處置 |
| --- | --- |
| published_at／event_at／event_date | 「發布於 日期時間」／「事件於 日期時間」／「事件日 日期」 |
| 三者皆無 | 「來源時間未提供」；collected_at 只在詳情稽核層顯示「系統收錄時間」 |
| time_consistency=conflict | 「資料集事件日期與公告內容提及日期不一致，時間待人工核實」 |
| 直接關聯／核實規則關聯／無證據 | 「標的關聯已驗證」／「關聯由規則核實」／「關聯尚未判定」 |

列表按 [NEWS_SPEC](NEWS_SPEC.md) 的已核實來源時間與 cursor 契約排序。未知時間目前可有 collected_at fallback，但不可顯示成發布時間；目標是移到時間待核實區。confidence 只描述關聯證據，不表示事件真假、方向或報酬。

### 4.3 來源連結

- `source_url_kind=item`：「查看原文／原始公告」。
- `source_url_kind=feed`：「查看官方公告資料集」，並提示未必定位本則公告。
- `source_url_kind=none`：「來源連結未提供」，不畫無效按鈕。
- raw payload、hash 與 event ID 只在稽核層。

### 4.4 族群關聯

新聞卡只顯示來源直接指向且已驗證的族群，或已核實的 Event—Instrument—Theme 關聯。由現有 membership 自動推得、英文名稱／代碼、名稱狀態未核實的關聯只留系統層。

## 5. 行動中心的預設資訊層級

1. **持倉風險與觀察**：已驗證減碼／退場條件、使用者 stop 或持倉風險資料待補。
2. **可研究條件**：完整 conditional、有合法 contract 價位的等待條件，以及持倉觀察。
3. **自選／事件關注**：自選、已核實事件，或完整 observation 的「暫無研究條件，持續觀察」。
4. **資料待補**：預設收合為「X 檔暫無法評估」，列最多三種常見缺項。

非持倉 data insufficient 不進預設卡片列表。行情完整但策略不足時可顯示「最近收盤」；當日行情不足時寫「價格資料尚未完整，暫不顯示最近收盤」。無合法 levels 或 RR 時隱藏相應區塊，必要時寫「研究價位／風險報酬比暫無法計算」，不用 0 或破折號。

## 6. 行動狀態與卡片文字

| `action_state` | 標籤 | 次文案／限制 |
| --- | --- | --- |
| conditional_entry | 符合條件後可研究進場 | 觸發與資料條件成立後，最早 T+1 再檢查；不是成交。 |
| wait_breakout | 等待突破條件 | contract 有合法門檻時才顯示；突破後仍需重查量能、族群與籌碼。 |
| wait_pullback | 等待回踩條件 | contract 有合法區間時才顯示；回到區間後仍需重查趨勢、量能與籌碼。 |
| hold_observe | 持倉觀察 | 只用於持倉，留意使用者 stop、策略失效與資料更新。 |
| reduce_exit | 持倉風險：減碼／退場條件 | 已碰到既定風險條件，重新研究處置；不是自動下單。 |
| data_insufficient | 策略判斷資料待補 | 目前無法產生研究動作；列精確缺項，不顯示方向。 |
| no_condition | 暫無研究條件 | 資料完整但條件未成立且沒有合法等待價位；顯示未通過理由。 |
| manual_review | 需人工判讀 | cutoff、basis、標的、價位或執行證據無法調和；不合成動作與價位。 |

日常頁說「突破／回踩研究條件」，完整版本名只在研究詳情。

### 6.1 兩個研究條件的合併呈現

判定以 [產品行動合併契約](PRODUCT_SPEC.md#action-merge) 為準。UI 必須遵守：

- 一條 conditional 不因另一條 observation 或 data incomplete 被降級；後者只在替代條件展開。
- 兩條 conditional 維持一張卡，各自價位不可混用；固定排序不代表信心或採用優先。
- observation 只有 contract 給合法價位時才顯示等待條件；否則顯示「暫無研究條件」，summary blocker 為空。
- 已驗證持倉風險優先，其他條件置於「其他研究條件」並標明不是新增／加碼指令。
- 熱門族群和事件只是脈絡，不是個股策略的新硬 gate。

## 7. Glossary 覆蓋與呈現

前後端 glossary 至少覆蓋 `stock_chips`、`foreign_investor`、`trust_investor`、`dealer`、`margin_change`、`breakout`、`pullback`、`rr`、`data_completeness`、`taiex`、`lot`、`average_cost`。Modal 依白話定義、用途、解讀與限制排列，不以 term_id 或欄位名作標題；完整詞義見 [GLOSSARY](GLOSSARY.md)。

## 8. 程式驗收條件

驗收至少涵蓋：日常路由不露內部字串；三層完整度與雙策略範圍不衝突；新聞全文折疊、URL 類型、unknown 影響與未核實族群正確；行動中心不被資料待補卡淹沒；詞彙可鍵盤操作；雙 observation 無合法價位時不造 levels；同標的一日一張卡；250／1,000／1,250 股格式及每股成本正確。未知、空值、載入失敗與窄版也須 fail closed。

## 9. v1 族群空狀態與發布規則

五分項完整才稱 v1 完整熱門。四分項只有在 V1_SPEC 的一致 event coverage 條件下，才可標「技術與籌碼觀察（事件資料待補）」；不能產生完整熱門候選。歷史某日為零不形成永久文案。新題材榜需另立方法版本；尚未接入的來源直接標未接入。

## 10. 壓縮卡、詳情與單位文案

### 10.1 今日／個股清單壓縮卡

順序為：代號／名稱 → 最近收盤與可信漲跌幅 → 一個行動結論 → 一個主要原因 → 一組關鍵價位（如合法）→ 資料日期與詳情入口。缺相鄰、同 basis 的可信前收盤時寫「漲跌幅待核實」；no condition、資料待補或人工判讀不顯示關鍵價位。

### 10.2 個股詳情的第一屏

依「今日研究結論 → 現在怎麼做 → 關鍵價位 → 為何如此 → 資料時間與完整度」排列；技術、籌碼、事件、替代條件和稽核置後並可收合。固定附註：「此為研究工具與資料摘要，不構成投資建議、報酬保證或自動下單指令。」

### 10.3 張／零股

DB／API quantity 保持精確整數股；台股 UI 的已知股數以 `原值 / 1,000` 顯示為張，最多 3 位小數，負值保留方向。250、1,000、1,250 股分別顯示「250 股（零股）」「1 張」「1 張 250 股」；平均成本固定為「NT$X／股」。來源或單位 unknown／mixed 時寫「單位待核實」並不換算。TAIEX 等指數用點數。

## 11. 現行信心語意與下一版 AI、題材及短線資金文案

| 資訊 | 允許 | 禁止 |
| --- | --- | --- |
| 完整度／規則狀態 | 「突破條件資料完整」「此條件已符合」 | 推論勝率或保證方向。 |
| legacy confidence=0.75 | 僅在已知 v1 1.0.0 且值為 0.75 時，技術層標「舊版固定規則值（未經機率校準；非勝率）」 | 顯示 75% 勝率或信任 evidence 自稱 prediction。 |
| null／unknown numeric | 「未校準；非預測勝率」 | 補 0%、百分比或機率。 |
| 模型機率 | 驗證後附事件、期間、資料日、樣本與校準資訊 | 無期間的上漲機率或模型自評。 |
| AI 摘要／事件影響 | 有引用的 AI 摘要；影響推論附方法與 unknown | 冒充原文、篇數當利多。 |
| 題材關聯 | 官方產業／經核實題材／待核實候選 | 模型標籤冒充官方分類。 |
| 當沖／分點 | 當沖交易占比；分點反轉附 N、X 與定義 | 外資當沖、主力明天必賣或身分認定。 |
| 規則參考價 | 觸發區間、失效價、不追價上限 | AI 精準買點或保證目標。 |

風險預算未知時寫「尚未設定風險預算，暫不提供部位數量」。不交易、到期、未觸發、未成交與模擬追蹤必須分開。

## 12. 中文原因碼對照

未知 code 一律顯示「研究條件需要人工核對」，原值只留稽核層。不同策略的 code 保留各自範圍。

| 原始值 | 日常文案／處置 |
| --- | --- |
| `passed`／`rejected`／`data_incomplete`／`observation`／`conditional` | 依序為「此研究條件已符合」「尚未成立」「資料待補」「條件尚未成立，持續觀察」「符合條件後可研究進場」；observation 不是缺資料，conditional 須附 T+1。 |
| `active`、`target_1_hit`、`target_2_hit`、`invalidated`、`expired`、`incomparable`、`settled` | 只在 tracking／歷史顯示中文狀態，不替代今日結論。 |
| `invalid_levels` | 「研究價位無法驗證」；隱藏所有不合法價位。 |
| `required inputs complete` | 稽核敘述；日常改成「突破／回踩條件資料完整」。 |
| `prior_20_highs_missing_or_invalid` | 前 20 個交易日高點資料待補。 |
| `prior_20_volumes_missing_or_invalid` | 前 20 個交易日成交量資料待補。 |
| `close_missing_or_non_finite`／`volume_missing_or_non_finite` | 最近收盤／當日成交量資料待補；不補 0。 |
| `ma20_missing_or_non_finite`／`ma60_missing_or_non_finite` | 20／60 日均線資料待補。 |
| `group_excess_return_20d_missing_or_non_finite` | 近 20 日相對大盤資料待補，不把 unknown 當中性。 |
| `institutional_flow_to_turnover_ratio_5d_missing_or_non_finite` | 近 5 日法人籌碼資料待補。 |
| `margin_balance_change_ratio_5d_missing_or_non_finite` | 近 5 日融資變化資料待補。 |
| `close_or_volume_must_be_positive`／`price_and_volume_inputs_must_be_positive` | 價格、均線或成交量異常，列資料待補，不解讀方向。 |
| `bar_count_missing_or_invalid`／`bar_count_must_be_a_non_negative_integer` | 歷史交易日數資料／格式待核實。 |
| `history_under_60_bars` | 近 60 個交易日行情不足，pullback 不可判定。 |
| `close_not_above_prior_20_day_high`／`volume_ratio_below_1_20` | 收盤尚未突破／量能未達 1.20；是規則未通過，不是看空。 |
| `group_relative_strength_not_positive` | 已核實群組未呈相對大盤正向；不顯示 raw group ID。 |
| `institutional_flow_materially_adverse`／`margin_financing_increase_abnormal` | 法人／融資未達規則要求；中性描述，不作預測。 |
| `ma20_not_above_ma60`／`close_below_ma60` | MA20 尚未高於 MA60／收盤低於 MA60。 |
| `close_outside_ma20_support_zone`／`pullback_volume_ratio_outside_range` | 收盤不在支撐區／回踩量比不在規則區間。 |
| `effective_group_score_missing_or_under_minimum_members` | 群組成員或相對大盤資料不足；不能顯示為 0 分。 |
| `signal_day_suspended` | 訊號日交易狀態不適合計算；隱藏動作與價位。 |
| `unsupported_instrument_type` | 商品類型暫不適用一般研究規則。 |
| `unsupported_or_missing_etf_category`／`etf_category_is_only_valid_for_etf` | ETF／商品分類待核實，不產生一般動作。 |
| `etf_category_excluded_from_actionable_signals:bond`／`etf_category_excluded_from_actionable_signals:leveraged`／`etf_category_excluded_from_actionable_signals:inverse` | 債券／槓桿／反向 ETF 可收集與分榜，暫不產生一般 v1 動作。 |
| `ipo_history_under_20_bars`／`ipo_observation_only_under_60_bars` | IPO 未滿 20 日不動作；20–59 日只觀察。 |
| `unsupported_entry_type` | 進場類型無法驗證；隱藏價位。 |
| `entry_price_must_be_finite_and_positive`／`invalid_price_must_be_finite_and_positive`／`invalid_price_must_be_below_entry` | 進場或失效價無法驗證；隱藏相關價位、目標與 RR。 |
| `target_1_must_be_finite_and_positive`／`target_1_must_exceed_entry` | 第一目標無法驗證；隱藏 target 與 RR。 |
| `target_2_must_be_finite_and_positive_when_present`／`target_2_must_exceed_target_1` | 第二目標無法驗證；只隱藏第二目標，第一目標仍獨立檢查。 |
| `minimum_first_target_risk_reward_must_be_finite_and_positive` | RR 門檻設定待核實；隱藏 RR 與條件價位包。 |
| `target_1_risk_reward_below_minimum` | 第一目標 RR 未達門檻，不形成 conditional；不是績效結論。 |
| `unsupported_current_status`／`unsupported_next_status`／`illegal_signal_status_transition` | 追蹤狀態無法驗證；日常顯示「需人工判讀」。 |
