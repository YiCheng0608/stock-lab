# Phase 4 產品呈現、新聞時間與交易單位規格

> 文件狀態：2026-09-11 起原路徑封存，僅供歷史背景與舊驗收案例追溯。以下「目前」「待實作」「唯一權威」「可直接實作」與日期／階段限制均為當時敘述，不代表目前能力、不構成新操作授權，也不代表本階段已驗收完成。
>
> 現行方向及優先序見 [PRODUCT_SPEC](PRODUCT_SPEC.md) 與 [ROADMAP](ROADMAP.md)。行動合併改由 [產品合併契約](PRODUCT_SPEC.md#action-merge) 維護；新聞來源／時間由 [NEWS_SPEC](NEWS_SPEC.md)、中文原因碼／單位由 [UI_COPY_SPEC](UI_COPY_SPEC.md) 維護。舊全量人工審核、日期限制或進度敘述不覆蓋現行契約。保留決定見 [文件索引](README.md)。

---

狀態：**規劃中，待程式實作與驗收**。本文件只定義產品介面、API 投影與文案契約；不改變 canonical v1 的策略公式、ETF eligibility、正式資料庫或 P0／P1 的 coverage 結論。它補充並優先於舊文件中與本文件衝突的「日常頁呈現、新聞排序、新聞時間與交易單位」敘述。策略與資料 gate 仍以 [V1_SPEC.md](V1_SPEC.md)、[STRATEGIES.md](STRATEGIES.md) 與 [PHASE3_PLAN.md](PHASE3_PLAN.md) 為準。

本機現有新聞投影仍以 `collected_at` 排序，且尚未有 `/news/:id` 詳情頁；這是要修正的現況，不是本規格聲稱已完成的功能。現有正式資料只有官方來源；國際、總體與媒體新聞均未接入。

## 1. 目標、邊界與共通原則

Phase 4 的目標是把「資料列」改成研究者能快速判讀的資訊層級：先知道現在能否研究、再看關鍵價位與原因，最後才展開技術、籌碼、事件與稽核證據。它不是下單、投資顧問或報酬預測功能。

共通規則：

1. **一檔、一日、一張摘要。** 日常首頁以 `exchange + symbol + as_of` 去重；若同一標的同時來自候選、行動、持倉、自選或事件，只能有一張正面卡，來源以小型脈絡標籤合併。
2. **先結論，後證據。** 卡片正面只留一個研究動作、一個最重要原因與一組最重要價位。所有替代策略、完整理由、第二目標、公式、raw 與稽核 ID 都在詳情／展開層。
3. **日線不是即時報價。** 只有可信的即時報價來源才可用「現價」。目前官方日資料一律標示「最近收盤（YYYY/MM/DD）」。
4. **未知不得補成 0 或方向。** 缺失事件、族群關聯、漲跌幅、價格、價位或新聞時間，必須顯示待核實／不顯示，而非補 0、猜測利多利空或生成摘要。
5. **日常頁不露出內部字串。** enum、reason code、欄位名、group ID、canonical 版本、raw payload ID、event ID 與 ISO 字串只能在系統／研究稽核層預設收合顯示。
6. **完整度必須帶用途。** 來源擷取、當日行情與策略判斷是三個不同層次；任一層完整都不能推論其他層完整。

## 2. 首頁、清單與行動卡：壓縮但不失真

### 2.1 首頁資料合併與優先序

首頁維持「今日市場與新聞 → 受影響族群 → 今日關注股票」的順序，但原本分開的「候選股票」與「行動卡」合併成一個 **今日關注股票** 區塊。它取候選、行動、持倉、自選與已核實事件的聯集後去重；同一標的不可以在首頁出現兩張完整卡。

排序為：已驗證持倉風險 → 完整且有研究動作的條件 → 已核實事件／自選關注 → 完整 observation 的暫無條件。非持倉且策略判斷資料待補的項目維持收合的數量摘要，不進首頁主卡清單。

每個合併卡可有最多三個脈絡標籤，例如「持倉」「自選」「已核實個股公告」「族群觀察」；這些標籤不是多張策略卡，也不是推薦強度。沒有已核實族群／事件時，不顯示猜測性標籤。

### 2.2 卡片正面固定欄位

卡片正面固定為以下資訊，且不得加上第二套完整策略欄位：

| 位置 | 欄位與呈現規則 |
| --- | --- |
| 標頭 | `代號 名稱`，必要時加交易所；ETF 類別以中文小標籤呈現。 |
| 價格 | 可信日線時顯示「最近收盤 YYYY/MM/DD：NT$X」。若前一個**相鄰、已核實交易日**的同調整基礎收盤價也為有限正數，才可附「漲跌 X%」；否則只寫「漲跌幅待核實」，不以 0.00% 取代。 |
| 今日結論 | 僅一個 action label，使用第 3 節的繁中標籤。 |
| 主要原因 | 最多一行、只用第 4 節翻譯後的中文事實，例如「收盤尚未站上前 20 個交易日高點」；不得直接串接多個原始 code。 |
| 最重要價位 | `條件進場`：觸發／失效；`等待突破`：觀察門檻；`等待回踩`：觀察區間；`持倉風險`：最優先的使用者停損或策略失效（必須標明來源）；`暫無條件`、`資料待補`、`需人工判讀`：不顯示虛構價位。目標價、RR 和替代條件放詳情。 |
| 資料時間 | 簡短顯示「資料截至 YYYY/MM/DD」及必要的資料層 badge；連結到詳情。 |

可信漲跌幅的必要條件是：兩筆收盤價均為有限正數、前一筆是該標的上一個已核實 TAIEX 交易日、兩筆使用相同公司行動調整基礎，且沒有停牌／缺值／品質衝突。任一條不滿足時，不使用紅綠方向或百分比。

### 2.3 不同動作的單組關鍵價位

| 行動摘要 | 卡片正面可顯示 | 不可在正面顯示 |
| --- | --- | --- |
| 符合條件後可研究進場 | `觸發 NT$X／失效 NT$Y`、最早 T+1 | 第二目標、完整 RR 推導、另一策略價位。 |
| 等待突破條件 | `觀察門檻 NT$X` | 把門檻稱作已成交 entry，或憑高點推造目標／停損。 |
| 等待回踩條件 | `觀察區間 NT$X–Y` | 把區間稱作已成交 entry，或憑均線推造 target／RR。 |
| 持倉觀察 | 有效的使用者停損或策略失效可作「留意價位」，並標明來源 | 新增／加碼語言；沒有有效價位時的破折號或 0。 |
| 持倉風險：減碼／退場條件 | `風險價位 NT$X（使用者停損／策略失效）` | 「立即賣出」、自動下單或未核實價格。 |
| 暫無研究條件／策略判斷資料待補／需人工判讀 | 不顯示價位 | entry、invalid、target、RR、看多看空色彩。 |

## 3. 個股詳情與行動語意

### 3.1 個股詳情固定資訊階層

個股詳情的第一屏依下列順序，不讓技術表、原始公告或策略列壓過結論：

1. **標的與資料時間**：代號、名稱、交易所、最近收盤（如可驗證）、資料截至日與三種完整度。
2. **今日研究結論**：一個行動標籤與一行白話結論。
3. **現在怎麼做**：條件、等待事項或不行動原因；所有條件進場都要寫「最早 T+1」。
4. **關鍵價位**：只顯示該主條件自己的觸發／區間、失效與（有有效值時）第一目標、RR；使用者停損與策略失效分開標示。
5. **為何如此**：最多三個已翻譯、可追溯的理由與相應完整度；可展開查看所有條件未通過／待補原因。
6. **資料時間與完整度**：來源擷取、當日行情、策略判斷各自說明；不得只顯示「完整」或「資料不足」。

以下區塊必須放在第一屏之後並預設收合：**技術條件**、**個股籌碼**、**公告與事件**、**替代研究條件**、**資料來源與稽核**。最後一層才可顯示規則版本、raw／event 參照和原始 reason code，且標示為系統維運資訊。

### 3.2 行動摘要的繁中文案

| API `action_state` | 日常標籤 | 首要文案 | 價位／行為限制 |
| --- | --- | --- | --- |
| `conditional_entry` | 符合條件後可研究進場 | 「僅在觸發價與資料條件同時成立時研究進場；最早下一個可判定交易日（T+1）再檢查。」 | 顯示同一主策略的觸發、失效、第一目標與有效 RR。不是已成交、不是下單指令。 |
| `wait_breakout` | 等待突破條件 | 「等待收盤符合突破觀察門檻後，再重新核對量能、族群與籌碼。」 | 只在 contract 有合法、有限門檻時顯示；門檻不是 entry。 |
| `wait_pullback` | 等待回踩條件 | 「等待回到觀察區間後，再重新核對趨勢、量能與籌碼。」 | 只在 contract 有合法、有限區間時顯示；區間不是 entry。 |
| `hold_observe` | 持倉觀察 | 「目前未見已核實的減碼／退場條件；持續留意失效價、使用者停損與資料更新。」 | 只有持倉才可使用；不能包裝成加碼建議。 |
| `reduce_exit` | 持倉風險：減碼／退場條件 | 「已碰到既定風險條件，請依自己的風險規畫重新研究減碼或退場。」 | 必須區分使用者停損與策略失效；不是自動賣出。 |
| `data_insufficient` | 策略判斷資料待補 | 「目前無法產生研究動作。先補齊：<精確資料域>。」 | 沒有價位時寫「研究價位暫無法計算」；不得出現方向、entry、target 或 RR。 |
| `no_condition` | 暫無研究條件 | 「資料足夠，但目前尚未符合研究條件；持續觀察。」 | 不是資料待補。只有合法等待價位才改用等待突破／回踩。 |
| `manual_review` | 需人工判讀 | 「資料截止、價位或研究條件存在無法自動調和的衝突，先人工核對證據。」 | 不顯示合成的主價位或交易動作。 |

所有上述卡片與個股詳情固定附註：「此為研究工具與資料摘要，不構成投資建議、報酬保證或自動下單指令。」

## 4. 內部狀態、原因與群組名稱翻譯

### 4.1 顯示分層

- **日常頁**：只接受已翻譯的中文標籤、句子和資料域名稱；不得傳遞或 render 原始 code。
- **研究詳情**：可顯示完整中文原因、規則版本和可點擊詞彙；仍不直接以 raw code 作主文案。
- **系統／稽核層**：可在預設收合的「技術識別」中顯示原始 code、group ID、canonical snapshot、raw payload／event ID 和 API evidence。

前端不得以底線切詞、首字母大寫或翻譯機制處理未知 code 後直接輸出。未知 code 必須降級為「研究條件需要人工核對」，同時把原始值留在稽核層與 error telemetry；不得杜撰買賣解讀。

### 4.2 策略評估狀態與原因碼對照

下表涵蓋目前 `domain.py` evaluator、eligibility、價位驗證、生命週期驗證及 pipeline 額外 blocker 會產生的原始字串。相同字串若來自 breakout 或 pullback，仍必須保留策略範圍，不可把兩條策略的理由混成一個 blocker。

| 原始 API／evidence 值 | 日常頁中文與意義 | 顯示範圍與處置 |
| --- | --- | --- |
| `passed` | 此研究條件已符合 | 只在所有 eligibility、必要輸入與價位驗證也通過時，才可形成「符合條件後可研究進場」。 |
| `rejected` | 此研究條件尚未成立 | 顯示具體未通過項目；不是資料缺漏、不是策略失敗。 |
| `data_incomplete` | 此研究條件資料待補 | 顯示精確資料域；不能補 0。 |
| `observation` | 條件尚未成立，持續觀察 | 有 contract 合法等待價位才轉為等待突破／回踩；否則是「暫無研究條件」。 |
| `conditional` | 符合條件後可研究進場 | 日常文案需附最早 T+1；不可寫成已成交。 |
| `active`、`target_1_hit`、`target_2_hit`、`invalidated`、`expired`、`incomparable`、`settled` | 研究追蹤狀態 | 只在 tracking／研究歷史以中文呈現，例如「已失效」「無法比較」；不替代當日研究結論。 |
| `invalid_levels` | 研究價位無法驗證 | 列入資料待補／需人工判讀，隱藏所有不合法價位。 |
| `required inputs complete` | 此研究條件必要輸入完整 | 是稽核敘述，不直接作日常 badge；日常頁須改成有範圍的「突破條件資料完整」或「回踩條件資料完整」。 |
| `prior_20_highs_missing_or_invalid` | 前 20 個交易日高點資料待補 | breakout 的精確缺項。 |
| `prior_20_volumes_missing_or_invalid` | 前 20 個交易日成交量資料待補 | breakout／pullback 的精確缺項。 |
| `close_missing_or_non_finite` | 最近收盤資料待補 | 相關策略不可計算；不顯示價格結論。 |
| `volume_missing_or_non_finite` | 當日成交量資料待補 | 相關策略不可計算。 |
| `ma20_missing_or_non_finite` | 20 日均線資料待補 | pullback 的精確缺項。 |
| `ma60_missing_or_non_finite` | 60 日均線資料待補 | pullback 的精確缺項。 |
| `group_excess_return_20d_missing_or_non_finite` | 近 20 日相對大盤資料待補 | 相關策略不可計算；不把未知族群強弱當中性。 |
| `institutional_flow_to_turnover_ratio_5d_missing_or_non_finite` | 近 5 日法人籌碼資料待補 | 相關策略不可計算；不以 0 取代。 |
| `margin_balance_change_ratio_5d_missing_or_non_finite` | 近 5 日融資變化資料待補 | 相關策略不可計算；不以 0 取代。 |
| `close_or_volume_must_be_positive` | 收盤或成交量資料無法用於計算 | 當作資料待補／異常值，不解讀為價格方向。 |
| `bar_count_missing_or_invalid` | 歷史交易日數資料待補 | pullback 的精確缺項。 |
| `history_under_60_bars` | 近 60 個交易日行情不足 | pullback 不可判定；不等同新股的看法。 |
| `price_and_volume_inputs_must_be_positive` | 價格、均線或成交量資料無法用於計算 | 當作資料待補／異常值。 |
| `close_not_above_prior_20_day_high` | 收盤尚未站上前 20 個交易日高點 | breakout 的條件未通過，不是看空結論。 |
| `volume_ratio_below_1_20` | 成交量未達近 20 日均量的規則門檻 | breakout 的條件未通過。 |
| `group_relative_strength_not_positive` | 所屬已核實群組未呈相對大盤正向 | 只在群組資格本身有效時呈現；不顯示 raw group ID。 |
| `institutional_flow_materially_adverse` | 法人籌碼未達規則要求 | 中性地描述規則未通過，不把它翻成預測。 |
| `margin_financing_increase_abnormal` | 融資變化超過規則上限 | 中性地描述規則未通過。 |
| `ma20_not_above_ma60` | 20 日均線尚未高於 60 日均線 | pullback 的趨勢條件未通過。 |
| `close_below_ma60` | 收盤低於 60 日均線 | pullback 的趨勢條件未通過。 |
| `close_outside_ma20_support_zone` | 收盤未落在 20 日均線支撐觀察區 | pullback 的支撐條件未通過。 |
| `pullback_volume_ratio_outside_range` | 回踩期間成交量未落在規則區間 | pullback 的量能條件未通過。 |
| `effective_group_score_missing_or_under_minimum_members` | 族群成員或相對大盤資料不足，無法取得有效群組脈絡 | 顯示為精確 blocker；不是「族群分數為 0」。 |
| `signal_day_suspended` | 訊號日交易狀態不適合計算 | 隱藏動作與價位，保留可追溯的停復牌事件。 |
| `unsupported_instrument_type` | 此商品類型暫不適用一般研究規則 | 不把未支援商品混成股票行動卡。 |
| `bar_count_must_be_a_non_negative_integer` | 歷史交易日資料格式待核實 | 系統／資料待補層。 |
| `unsupported_or_missing_etf_category` | ETF 類別待核實，暫不產生一般研究動作 | 可保留 ETF 分榜，但不產生 v1 actionable signal。 |
| `etf_category_excluded_from_actionable_signals:bond` | 債券型 ETF 暫不適用一般 v1 研究訊號 | 可收集、分類與 ETF 分榜；日常不產生 breakout／pullback 動作。 |
| `etf_category_excluded_from_actionable_signals:leveraged` | 槓桿型 ETF 暫不適用一般 v1 研究訊號 | 同上。 |
| `etf_category_excluded_from_actionable_signals:inverse` | 反向型 ETF 暫不適用一般 v1 研究訊號 | 同上。 |
| `etf_category_is_only_valid_for_etf` | 商品分類資料待核實 | 系統／資料待補層，不向使用者暴露內部型別。 |
| `ipo_history_under_20_bars` | 新上市／上櫃標的歷史未滿 20 個交易日 | 不產生一般 v1 研究動作。 |
| `ipo_observation_only_under_60_bars` | 新上市／上櫃標的歷史未滿 60 個交易日，僅作觀察 | 不產生 actionable entry；不把它說成一般資料錯誤。 |
| `unsupported_entry_type` | 研究進場類型無法驗證 | 隱藏價位，交由系統稽核。 |
| `entry_price_must_be_finite_and_positive` | 研究進場價無法驗證 | 隱藏 entry、target、RR。 |
| `invalid_price_must_be_finite_and_positive` | 研究失效價無法驗證 | 隱藏相關價位與 RR。 |
| `invalid_price_must_be_below_entry` | 研究失效價與進場價關係無法驗證 | 隱藏相關價位與 RR。 |
| `target_1_must_be_finite_and_positive` | 第一目標價無法驗證 | 隱藏 target 與 RR。 |
| `target_1_must_exceed_entry` | 第一目標價與進場價關係無法驗證 | 隱藏 target 與 RR。 |
| `target_2_must_be_finite_and_positive_when_present` | 第二目標價無法驗證 | 隱藏第二目標；第一目標仍須獨立驗證。 |
| `target_2_must_exceed_target_1` | 第二目標價與第一目標價關係無法驗證 | 隱藏第二目標。 |
| `minimum_first_target_risk_reward_must_be_finite_and_positive` | 風險報酬門檻設定待核實 | 隱藏 RR 與條件進場價位包。 |
| `target_1_risk_reward_below_minimum` | 第一目標的風險報酬未達規則門檻 | 不形成條件進場；不是策略績效結論。 |
| `unsupported_current_status`、`unsupported_next_status`、`illegal_signal_status_transition` | 研究追蹤狀態無法驗證 | 只在系統／稽核層顯示；日常改為「需人工判讀」。 |

### 4.3 群組與證據名稱

| 內部名稱 | 日常頁政策 |
| --- | --- |
| `group_id`、`theme_id`、`leaderboard`、membership role／confidence | 不直接顯示。只有 `display_name_zh`、中文描述、名稱來源和名稱狀態皆已核實時，才顯示中文名稱。 |
| `Industry · Shipping` | 只有官方中文映射與關聯都經核實時才可顯示「航運（官方產業分類）」；否則隱藏。 |
| `Industry · 32`、`Industry · 38`、未知產業代碼 | 日常新聞、首頁、個股事件與行動卡一律不顯示。系統層可寫「官方產業名稱待對照」。 |
| `breakout_v1`、`pullback_v1` | 日常說「突破研究條件」「回踩研究條件」；完整版本名只在研究規則／稽核展開層。 |
| `prior_20_highs`、`prior_20_volumes`、`institutional_flow_5d`、`required inputs complete` | 日常改為「前 20 個交易日高點」「前 20 個交易日成交量」「近 5 日法人籌碼」「<策略>條件資料完整」。 |

## 5. 新聞資訊架構與時間誠實性

### 5.1 路由與頁面內容

| 路由 | 用途與最低欄位 | 預設行為 |
| --- | --- | --- |
| `/news` | 時間、來源、類別、標題、摘要預覽、已核實相關標的；標題連到詳情。 | 一列一則去重後新聞；摘要最多三行／120 個全形字元；不展示完整原始公告、raw、ISO 時間或未核實族群。 |
| `/news/:id` | 標題、摘要、可展開全文、事件類別、來源、來源時間、已核實標的／主題、影響資訊、官方 URL、預設收合的 provenance。 | 顯示原始內容時維持來源原意，不生成內容；不確定關聯或時間必須明示。 |

`/news` 卡片固定順序：

    個股公告 · MOPS 官方公告資料
    [來源原始標題，最多兩行；點擊前往新聞詳情]
    [來源摘要預覽；無摘要則「官方來源未提供摘要」]
    發布於／事件日／來源時間未提供（依第 5.2 節）
    相關標的：2330（僅直接或規則／人工已核實者）
    官方公告資料集／查看原始公告（依 URL 類型）

`/news/:id` 的第一屏依序為：標題 → 摘要 → 全文折疊 → 類別與來源 → 時間 → 相關標的／已核實主題 → 影響狀態 → 來源 URL。最後才提供「資料來源與稽核」折疊層，其中 `系統收錄時間`、來源 endpoint、raw payload／event 參照與時間品質可以查看。列表卡不得顯示 `collected_at`。

### 5.2 時間欄位、顯示和穩定排序

每則新聞必須分開保存和回傳 `published_at`、`event_at`、`event_date`（若來源只有日期）、`collected_at`、`time_basis` 與 `time_precision`。空值就是未知，不能用事件類型、內文文字或擷取時間補成發布時間。

對每一則可在日常列表顯示的項目，選擇第一個已核實時間作為 `display_time` 與排序來源：

1. `published_at`：來源直接提供的發布時間，顯示「發布於 YYYY/MM/DD HH:mm」。
2. `event_at`：來源直接提供或可稽核的事件時間，顯示「事件於 YYYY/MM/DD HH:mm」。
3. `event_date`：來源只有日期，顯示「事件日 YYYY/MM/DD」；不可虛構時分秒。
4. `collected_at`：前三者皆不存在且未發現時間衝突時，僅作系統排序 fallback；列表寫「來源時間未提供」，詳情稽核層才寫「系統收錄時間 YYYY/MM/DD HH:mm」。

排序使用每筆的 `display_time`，由新到舊；不是把全部 `published_at` 先排完、也不是把最新回補資料依 `collected_at` 推到最近。這使得歷史回補仍以其已核實的發布／事件日期排序，不會蓋過真正的新消息。

`GET /news` 必須改用不可變的 keyset cursor，不用 offset。cursor 至少編碼 `display_time`、`time_basis`、`time_precision`、`canonical_key` 與 `id`；排序為 `display_time desc`，同值時依 `time_basis`（published → event → event_date → collected）、時間精度（含時間 → 僅日期）、`canonical_key desc`、`id desc`。這個 tie-breaker 保證下一頁不重複、不跳列，並讓同時間的回應穩定。篩選、搜尋和去重必須在建立 cursor 前完成。

### 5.3 沒有發布時間與 MOPS 日期衝突

- 沒有 `published_at` 不得顯示「發布於」、不得以 `event_date` 偽裝成發布時間，也不得說成「最新公告」。若有已核實事件時間／日期，使用「事件於／事件日」；否則列表只寫「來源時間未提供」。
- MOPS 內文若提及一個日期，不可由 parser 自動寫入 `published_at` 或 `event_at`。它最多可作稽核候選欄位，不能替代來源結構化時間。
- 當 MOPS 資料集 `event_date` 與可辨識的內文事實日期不一致、或來源無法證明兩者關係時，標記 `time_consistency=conflict`。此筆不進預設「最新」新聞串流、不能驅動事件脈絡／族群／行動；可在「時間待核實官方公告」篩選中顯示，詳情明示：「資料集事件日期與公告內容提及日期不一致，時間待人工核實。」
- 發生 `time_consistency=conflict` 時，不能以 `collected_at` 把歷史回補塞到最新位置；它仍可保留原始證據與稽核連結。

### 5.4 來源連結、類別與關聯

| 狀態 | 日常文案與限制 |
| --- | --- |
| `source_url_kind=item` | 「查看原始公告」或「查看原文」，連到實際單篇 URL。 |
| `source_url_kind=feed` | 「查看官方公告資料集」，並固定註明「此連結開啟官方清單，未必直接定位本則公告。」 |
| `source_url_kind=none` | 「來源連結未提供」，不顯示不可點擊按鈕。 |
| 官方公告、MOPS、交易所事件 | 分類為「個股公告」或「台灣官方事件」；它是事件證據，不自動代表利多、利空或新聞完整 coverage。 |
| 未核實標的／主題關聯 | 不顯示關聯標籤、不顯示英文／代碼族群；不得由 membership 自動推論。 |
| 影響方向未知 | 顯示「影響尚未判定」，不使用紅綠、買賣或看多看空暗示。 |

## 6. 張數、零股與金額單位

### 6.1 資料與顯示契約

- 資料庫與 API 的交易數量 canonical unit 永遠是 **股（shares）**，必須是整數；不得因 UI 顯示轉成張後回寫、四捨五入或改變持倉。
- 台股預設以 **1 張 = 1,000 股** 顯示。介面可提供「張／股」切換，但預設為張；切換只改顯示，不改資料。
- 張模式的精確格式為：恰好 1,000 股顯示「1 張」；1,250 股顯示「1 張 250 股」；少於 1,000 股顯示「250 股（零股）」；不得顯示「0 張 250 股」。大於 1,000 且有餘數時一律顯示 `N 張 M 股`。
- 持倉平均成本一律為 **每股價格**，例如「平均成本 NT$X／股」；市值、未實現損益、已實現損益與手續費以精確股數計算，不以顯示張數近似。輸入張數時，前端要轉成精確整數 shares 並在送出前顯示換算結果。
- 成交量原始單位也是股。張模式可顯示「成交量 N 張 M 股」；數字過大時摘要可先顯示完整張數、詳情保留股數，兩者均不可改變原始數量。
- ETF 使用與股票完全相同的張／零股與每股成本規則。TAIEX 等不可交易指數以「點」呈現、不得顯示張數；現行不支援的商品類型不應混入股票／ETF 的持倉數量元件。

### 6.2 介面文字

| 情境 | 文案 |
| --- | --- |
| 張模式切換 | 「單位：張」／「單位：股」 |
| 250 股持倉 | 「持有 250 股（零股）」 |
| 1,250 股持倉 | 「持有 1 張 250 股」 |
| 成本 | 「平均成本 NT$X／股」 |
| 無有效持倉數量 | 「持倉數量待確認」 |

## 7. 未來國際／市場新聞的資料治理

國際、總體或媒體來源在以下所有條件完成前，**不得抓取、寫入正式 NewsItem、顯示於日常新聞、推測市場影響或作為族群／行動理由**：

1. 白名單記錄來源所有者、類型、授權／可用範圍、可保存內容、保留期限、endpoint、rate limit、責任人與可停用開關。
2. 每則都有來源名稱、單篇 canonical URL（`source_url_kind=item`）、來源提供的 `published_at` 或明確未知狀態、內容／摘要使用權和原始識別碼。
3. 先用來源 item ID／canonical URL 去重；缺失時才以來源、正規化標題、時間、標的與內容雜湊建立 `canonical_key`。撤回、更正、重複與下線保留生命週期，不覆寫稽核證據。
4. 標的／族群關聯必須有來源直接證據、可稽核規則或人工審核。回傳 `association_confidence`、`association_method`、`reviewer`、`reviewed_at` 與原因；未核實不輸出日常標籤。
5. 正負影響預設 `unknown`。任何正負判讀、跨來源事件合併、AI 摘要或主題關聯都要人工審核、可回溯並有政策版本。
6. 新來源先進隔離 quarantine，通過授權、時間、URL、去重、關聯與 UI 驗收後才可提升。搜尋結果、社群、瀏覽片段與模型推測都不能作替代資料。

## 8. 建議 API 投影（待實作）

本節是新增／調整 API 的目標契約，不代表目前端點已符合。

### 8.1 Compact action／stock summary

首頁與個股目錄應接收一個以 `exchange + symbol + as_of` 去重的 `research_summary`。至少回傳：

    {
      "instrument": {"exchange": "TWSE", "symbol": "2330", "name": "…"},
      "as_of": "YYYY-MM-DD",
      "close": 0.0,
      "close_as_of": "YYYY-MM-DD",
      "change_percent": null,
      "change_status": "verified|unverified|unavailable",
      "action_state": "conditional_entry|…",
      "display_action": "符合條件後可研究進場",
      "primary_reason": {"label": "…", "scope": "breakout"},
      "primary_levels": {"kind": "trigger_invalid", "trigger": 0.0, "invalid": 0.0},
      "data_status": {"source": "complete", "market": "complete", "strategy": "partial"},
      "context_badges": ["held", "watchlist"],
      "detail_url": "/stocks/TWSE/2330"
    }

`primary_reason`、`display_action` 和 `primary_levels` 必須在 backend／presentation 層完成翻譯與驗證；前端不得重新組合 raw evidence 或跨策略的價位。

### 8.2 新聞 list／detail

`GET /news` 回傳去重後項目、opaque keyset cursor 與：

    "meta": {
      "sort": "display_time_desc,time_basis_desc,time_precision_desc,canonical_key_desc,id_desc",
      "next_cursor": "opaque-or-null",
      "data_as_of": "YYYY-MM-DD"
    }

每個 list item 必須有 `display_time`、`time_basis`（published／event／event_date／collected／unverified）、`time_precision`（datetime／date／none）、`time_consistency`、`source`、`title`、`summary_preview`、已核實 `symbols`、已核實 `themes` 與 `detail_url`。`collected_at` 不應出現在 list item 的日常呈現欄位。

`GET /news/:id` 回傳 list 欄位加上 `description`、影響／關聯證據、來源 URL 型別、`provenance` 與 `collected_at`。`provenance`、原始 ID、endpoint 與 timestamps 預設由 UI 收合。

## 9. 實作與驗收矩陣

| ID | 範圍 | 可驗收輸入 | 預期結果 |
| --- | --- | --- | --- |
| C1 | 首頁去重 | 同一 `TWSE/2330/as_of` 同時出現在候選與 actions | 今日關注股票只有一張壓縮卡；脈絡標籤合併，沒有兩張 breakout／pullback 卡。 |
| C2 | 價格與漲跌 | 有兩個相鄰、同調整基礎、可信收盤 | 顯示最近收盤與漲跌%；任一條缺失時不顯示 0%，而是「漲跌幅待核實」。 |
| C3 | 卡片價位 | conditional、wait_breakout、wait_pullback、data_insufficient 各一例 | 每張只顯示本節指定的一組價位；待補項目沒有 entry／target／RR。 |
| D1 | 個股詳情 | 有完整主條件及替代條件的標的 | 第一屏依第 3.1 節；替代策略與完整 evidence 收合，兩組價位不混用。 |
| D2 | 行動文案 | 八個 `action_state` 各一例 | 顯示第 3.2 節中文；沒有「買入」「立即賣出」「自動下單」或投資保證。 |
| I1 | raw code 隱藏 | 任一 evaluator／pipeline 原始 reason、group ID、status | 日常頁沒有底線 code、`DecisionSummary`、`canonical`、`prior_20_highs` 或 `Industry · 32`；系統層可收合追溯。 |
| N1 | 新聞列表 | 有 published、event datetime、event date、無來源時間各一筆 | 顯示正確時間語意；`collected_at` 不在卡片正面；標題連 `/news/:id`。 |
| N2 | 歷史回補排序 | 舊 event_date 但新 collected_at 的官方資料 | 仍按舊 event date 排，不會出現在最新消息前方。 |
| N3 | MOPS 日期衝突 | 資料集日期與內文日期不一致 | 不進預設最新串流、不推導 published／event time、不產生關聯或影響；可在時間待核實頁看到明確說明。 |
| N4 | 來源與關聯 | feed URL、item URL、未核實 theme 各一例 | 來源按鈕正確；feed 明示是資料集；未核實主題／英文 ID 不顯示。 |
| U1 | 數量單位 | 250、1,000、1,250 shares 的股票與 ETF 持倉 | 分別顯示「250 股（零股）」「1 張」「1 張 250 股」；平均成本仍是每股，損益以精確 shares 算。 |
| U2 | 指數／不支援商品 | TAIEX 與非股票／ETF 類別 | TAIEX 顯示點數；不混入張數持倉元件。 |
| G1 | 未核准新聞 | 搜尋摘要、媒體 URL 或國際來源沒有白名單／授權 | 留在 quarantine 或完全不取用；不出現在 NewsItem、熱門理由、候選或行動卡。 |

驗收通過只代表資訊呈現與 fail-closed 契約正確，不代表策略績效、勝率、walk-forward、獨立 OOS 或採用結論。

## 10. 程式 task 實作清單與外部決策

### 可直接實作

1. 建立後端 presentation mapper，將第 4 節所有 reason／state／group 狀態轉為結構化中文 label、scope、severity 和可否顯示，不把 raw strings 交給日常 UI。
2. 為首頁 union 建立 `research_summary` 去重與排序，並落實 compact card 的單組價位規則。
3. 重整個股詳情第一屏與可收合證據區，讓替代策略、稽核和原始公告不搶占結論層。
4. 實作 `/news/:id`、新聞時間資料欄位、keyset cursor、`display_time` 排序與 `time_consistency` quarantine；同時把現行 `collected_at desc` 改為第 5.2 節契約。
5. 落實 feed／item URL 文案、未核實主題隱藏與完整內容只在詳情折疊。
6. 將所有數量持續以 shares 儲存，新增可逆、無精度損失的張／股 presentation formatter 與相關前端測試。
7. 為第 9 節 C1–U2 寫 API、presentation 和 UI 測試；未知 reason code 必須 fail-closed 並留 telemetry。

### 仍需外部決策

- 國際、宏觀與媒體來源白名單、授權、可保存摘要範圍、保留期限與責任人。
- 人工審核誰可以核實新聞時間衝突、標的／主題關聯、影響方向和撤回／更正。
- 是否引入已授權的即時報價來源；在此之前日常價格一律是最近收盤。
- 何時有足夠可核實官方事件 coverage 供 hot_group 催化劑使用；本文件沒有放寬 Phase 3 的五 component gate。
