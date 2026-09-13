# Phase 3：資料補齊、族群研究與新聞治理

> 文件狀態：2026-09-11 起原路徑封存，僅供歷史背景與舊驗收案例追溯。以下「目前」「待實作」「唯一權威」「可直接實作」與日期／階段限制均為當時敘述，不代表目前能力、不構成新操作授權，也不代表本階段已驗收完成。
>
> 現行方向及優先序見 [PRODUCT_SPEC](PRODUCT_SPEC.md) 與 [ROADMAP](ROADMAP.md)。行動合併改由 [產品合併契約](PRODUCT_SPEC.md#action-merge) 維護；新聞來源／時間由 [NEWS_SPEC](NEWS_SPEC.md)、中文原因碼／單位由 [UI_COPY_SPEC](UI_COPY_SPEC.md) 維護。舊全量人工審核、日期限制或進度敘述不覆蓋現行契約。保留決定見 [文件索引](README.md)。

---

狀態：P0 的正式資料補齊已完成，但結果為 partial；P1 僅規劃對 2026-09-08 做範圍化 analyze。本文仍是 Phase 3 的唯一產品與研究執行規格；它補足 [PRODUCT_SPEC.md](PRODUCT_SPEC.md)、[NEWS_SPEC.md](NEWS_SPEC.md)、[STRATEGIES.md](STRATEGIES.md)、[DATA_SOURCES.md](DATA_SOURCES.md)、[OPERATIONS.md](OPERATIONS.md) 與 [UI_COPY_SPEC.md](UI_COPY_SPEC.md)，但不改變 canonical v1 的公式、ETF 政策或已保存資料。

## 1. 起點、目標與不做的事

截至 2026-09-10 的正式 P0 結果，TAIEX 已有 65 個已驗證交易日，P0 的市場資料窗口已達 target_met；但整體 run 因事件、基本面與公司行動資料域仍為 partial。Phase 2 的資訊架構與介面能如實呈現官方事件、資料截止日與資料待補，但尚不能把 partial 結果宣稱為完整熱門族群，也沒有策略績效、walk-forward 或 T+1／T+5／T+20 採用結論。國際、總體與媒體新聞也尚未接入。

Phase 3 的目標是讓研究者能在**有限、可稽核的官方資料範圍**內回答：

1. 哪些族群的資料已足以被稱為「熱門」，以及原因與限制是什麼？
2. 哪些個股有完整證據可呈現研究條件，哪些仍只能顯示資料待補？
3. 官方公告和未來可能接入的新聞，是否有清楚來源、時間、關聯與治理狀態？

本階段不做下列事項：

- 不做無界線的全歷史下載、回填或參數最佳化。
- 不以短期回放、勝率、社群說法或缺值補 0 作策略採用結論。
- 不把搜尋結果、未授權媒體內容、模型推測或未審核族群關聯寫入正式新聞。
- 不建立 Windows Task Scheduler 或 Codex 排程；批次先以人工啟動、隔離演練與可稽核 run 為準。
- 不把 Phase 3 的計畫、測試案例或資料量目標描述成已完成 coverage 或策略績效。

### 1.1 現有規格盤點與優先權

| 文件 | 已定義、可沿用的內容 | Phase 3 要補上的缺口 |
| --- | --- | --- |
| [PRODUCT_SPEC.md](PRODUCT_SPEC.md) | 五個主導航、事件 → 族群 → 個股 → 行動的研究流程、分層資料概念。 | 可驗收的資料天數、公開 gate、retry 優先級與「何時不排行」。 |
| [NEWS_SPEC.md](NEWS_SPEC.md) | 官方 Event 投影、時間、來源、去重、影響預設 unknown 與 API 契約。 | 來源白名單、授權、quarantine、人工審核和新來源的準入／下線流程。 |
| [STRATEGIES.md](STRATEGIES.md) | canonical v1、T+1、T+5／T+20、ETF 邊界與 technical backtest 限制。 | 用官方 raw 重跑的研究就緒案例與 coverage 前置條件。 |
| [DATA_SOURCES.md](DATA_SOURCES.md) | 正式 P0 的 65 日資料窗口、官方 adapter、partial 原因和 provenance。 | 事件 date-scoped coverage 的修復、個別缺口的 targeted retry 與後續實際 coverage。 |
| [OPERATIONS.md](OPERATIONS.md) | official-only CLI、隔離 DB、migration 與既有 partial 的安全處理。 | Phase 3 batch 大小、重試上限、run audit 與不建立排程的操作邊界。 |
| [UI_COPY_SPEC.md](UI_COPY_SPEC.md) | 三種完整度、新聞折疊、未核實關聯隱藏與行動中心層級。 | 未達資料門檻時的族群空狀態，以及只有 complete 才能顯示「熱門」的發布規則。 |

規格優先序如下：canonical 公式、ETF eligibility 與 lifecycle 以 [V1_SPEC.md](V1_SPEC.md) 為準；本文件負責 Phase 3 的資料範圍、發布 gate 和治理；[UI_COPY_SPEC.md](UI_COPY_SPEC.md) 負責日常 UI 用語；[DATA_SOURCES.md](DATA_SOURCES.md) 只陳述已驗證的實際 coverage。若實作與本文件不符，應先更新規格與驗收，而不是以 UI 或資料列數自行改寫研究結論。

## 2. 優先序與階段驗收

| 優先序 | 交付物 | 為何先做 | 最小驗收條件 |
| --- | --- | --- | --- |
| P0 | coverage manifest、範圍化 official run、raw／錯誤稽核 | 沒有可辨識的範圍與缺口，就無法判斷任何「完整」。 | **已完成，結果 partial**：65 個 verified TAIEX sessions、2 個明確 no-data skip；資料完整性與 provenance 正常，但事件、基本面、公司行動仍有缺口。 |
| P1 | 2026-09-08 的範圍化 analyze 與 gate audit | breakout、pullback 與 hot group 依賴跨日資料和 TAIEX，但不能讓全域 partial 直接升格或一律阻擋個別標的。 | 僅評估 2026-09-08；每一列都要以 instrument／group／as-of 的必要輸入品質決定 passed、rejected 或 data_incomplete。 |
| P2 | 可用版熱門族群 | 先證明族群資料完整與中文名稱正確，再談排行與候選。 | 只對 complete、至少 3 位合格成員、TAIEX 與五個 component 均有來源證據的群組排行。 |
| P3 | 可研究的行動中心案例 | 行動卡必須以真實／隔離官方資料驗收，而非以介面 mock。 | breakout、pullback、持倉風險、資料待補各有一個可重跑案例；不可比較情況不產生結果。 |
| P4 | 新聞來源治理與人工審核流程 | 新聞的可信來源與關聯必須先於擴大內容量。 | 官方公告分類、來源連結、去重、時間與未核實關聯都可驗收；任何新媒體／國際來源先經核准。 |

P0 已提供 P1 所需的市場窗口，但沒有解除任何 per-instrument、per-group 或 event 的 fail-closed gate。P1 是 P2、P3 的前置條件；P4 的官方公告治理可平行進行，媒體或國際來源是否實作仍取決於第 8 節的外部決策。

### 2.1 正式 P0 結果與解讀

| 項目 | 正式 P0 結果 | 對 P1 的意義 |
| --- | --- | --- |
| TAIEX | 65 個 verified sessions，target_met=true。 | 具備 1／5／20 日比較及 60 日策略窗口的共同基準。 |
| 明確非交易日 | 2 個 no-data 日期安全標示為 skipped。 | 不補成交易日，也不把它們算進 20／60 日樣本。 |
| OHLCV／chips | bars 149,770（含 65 筆 TAIEX）、chips 148,346。2330 的 bars、chips 各 65，20／60 日 gap 均為 0。 | 市場窗口存在，但不表示每個標的已完整。 |
| 個別 coverage 缺口 | 行情未達 20／60 日者為 244／333；chips 未達 20／60 日者為 139／173。 | 受影響標的或其群組必須依缺口 data_incomplete；不以全市場總量掩蓋。 |
| events | 65 個 session 全為 unsupported，原因是官方 feed 不是 date-scoped empty-session。 | 催化劑不可被視為 0 或已核實；詳見第 4.2 節。 |
| fundamentals／公司行動 | fundamentals 在 65 個 session 為 partial；corporate actions 為 2 success、63 partial。 | 基本面不是 v1 gate；但受公司行動影響且無可追溯因子的策略價位／tracking 要 fail-closed。 |
| 稽核與安全 | DB integrity、FK、provenance 正常；正式 pre-P0 backup 已存在。 | P0 結果可重查，但不代表策略績效或 OOS 樣本。 |

## 3. 有界的官方資料補齊

### 3.1 範圍與交易日邊界

Phase 3 對每個基準日只追求下列有限窗口，不將「抓得到更多」等同於「資料更好」：

| 對象 | 市場基礎目標 | 可作策略／族群用途的邊界 | 產品處理 |
| --- | --- | --- | --- |
| TWSE／TPEx 股票 | authoritative allowlist 中每一檔股票，65 個**已驗證交易日** OHLCV。 | 60 根完整日線可供 pullback；訊號日加前 20 日可供 breakout；同日期 TAIEX 必須齊全。 | 若任一必要日期錯日、缺日或欄位不可驗證，受影響標的為資料待補。 |
| ETF | authoritative ETF allowlist 中所有分類，65 個已驗證交易日 OHLCV 與分類。 | ETF 另立 hot_group_v1 分榜；broad_market、dividend、sector、thematic、commodity 才可進一般 v1 行動 gate。 | bond、leveraged、inverse 仍完整收集、分類與分榜，但固定顯示為一般 breakout／pullback 不適用。 |
| IPO | 自上市日起最多取得 60 根可驗證日線；不足部分不可用其他標的補足。 | 少於 20 根日線：不觀察；20–59 根：只可 observation；至少 60 根才可能 actionable。 | IPO 的上市日、交易所與日線數必須有官方證據；不足時不以「新股題材」替代策略條件。 |
| TAIEX | 與股票／ETF 相同的 65 個已驗證交易日。 | hot group 的 1／5／20 日比較與個股的 20 日族群相對強度都以同一交易日序列計算。 | 缺一個所需基準日，即受影響分數、排行或策略資料待補。 |
| chips | 至少最近 20 個已驗證交易日的法人、融資與必要週轉額；5 日特徵只能從其中完整資料計算。 | breakout、pullback 的 5 日法人／融資 gate，以及 hot group 的 5 日法人流／20 日週轉額。 | 交易所、日期、欄位或 allowlisted 成員缺漏時不補 0；可有行情但仍不可產生策略或完整排行。 |
| 官方事件／公司行動 | 近 20 個交易日的事件 coverage，及涵蓋 65 日窗口、影響該窗口的已知公司行動。 | hot group 催化劑、新聞卡、tracking 可比性。 | 「官方資料完整但沒有事件」可為 0；「事件來源未收齊」必為 null／partial。 |

65 是操作上的有界目標：它提供 60 日策略窗口與 5 個交易日緩衝，不是「至少三個月就已驗證策略」。收集必須以實際交易日序列而非曆日補算。既有 CLI 的 **--months-back 0–3** 限制仍適用；Phase 3 不要求或授權超過三個月的單次回補。

### 3.2 批次、重試、freshness 與稽核

每一次實作都必須把 collection scope 寫入 run metadata。推薦的有限工作單位如下：

| 項目 | 規格 |
| --- | --- |
| 批次大小 | 一個市場基礎 batch 最多 5 個交易日 × 一個交易所 × 一個資料域；65 日基礎層最多分 13 個日期 batch 執行。單一 run 不得默默擴大成更長歷史範圍。 |
| 重試上限 | 同一 exchange／trading_date／data_domain 在一個 batch 最多 3 次立即嘗試；若仍非 success，最多 2 次後續 targeted retry，總嘗試上限為 5。 |
| 重試對象 | 只重試失敗或 partial 的日期、交易所、資料域與受影響標的；不可重跑整段成功資料以掩蓋缺口。 |
| 退避與冪等 | 每次請求有可重用 request key；保存 response hash、endpoint、時間、HTTP／解析錯誤與嘗試次數。成功資料不重複插入，失敗資料不被後來的空回應覆寫。 |
| freshness | 「可用」只表示所需資料截止日與已驗證官方交易日相符，並非即時報價。若有一個較新的已確認交易日未完成所需域，標為 stale／策略判斷資料待補。 |
| coverage manifest | 每個 scope 至少有 expected_dates、received_dates、missing_dates、status、data_as_of、collected_at、raw_payload_ids 或 error_refs。UI 應以三種完整度文案呈現，不以 run 的單一 success 推論所有欄位完整。 |

明確 no-data 且官方無列的日期可標示為 skipped_non_trading，不算成有效交易日；錯日、無報告日期、空白但沒有明示 no-data、解析錯誤或來源端點失敗均為 partial 或 missing。需要該日期的策略、族群分數、tracking 一律 fail-closed。

### 3.3 Targeted retry 優先級

市場基礎層完成前，目標標的只能補「阻擋它的最小資料域」，不可藉由局部完整宣稱整體完整。排程順序如下：

1. **持倉風險**：持倉標的的最新 OHLCV、停牌／公司行動與既有 stop／invalid 所需資料。資料不足時只顯示風險資料待補，不自動判定退場。
2. **自選與使用者明確查詢**：使用者自選或明確開啟研究的標的，補齊其 60 日日線、5／20 日 chips、TAIEX／membership 依賴資料。
3. **直接關聯的官方事件標的**：近 5 個交易日、具有已驗證 Event—Instrument 關聯者；事件只能提高補資料優先級，不能替代策略條件。
4. **合格族群候選**：先完成可能達標群組的所有成員資料，再處理每群最多 10 檔候選，跨群去重。
5. **其餘市場基礎缺口**：依交易所、日期、資料域補齊 bounded 65／20 日範圍。

每個 targeted retry 都必須可回答「為何補這一筆、缺哪一項、取自哪個官方端點、最後結果為何」。不因持倉、自選或事件優先而降低 fail-closed 要求。

### 3.4 停牌、公司行動與來源失敗

- 停牌或沒有可判定的下一交易日價格時，T+1 execution 不成立；追蹤或結算標示 incomparable，不是 0 報酬或延後猜測成交。
- 公司行動只有在官方 action、有效日期與可追溯調整因子都齊全時才調整 execution／settlement；缺因子或日期衝突時，該筆結果為 incomparable。
- 同日同時觸及 stop 和 target 而日內順序無法由資料判定時，禁止假設先後順序。
- 端點失敗、錯日或缺日會保留 error／raw 稽核，不回退至非官方資料，也不以最近一日複製替代。

## 4. 可用版熱門族群

### 4.1 中文 taxonomy 與 membership

族群名稱的權威鏈為：**TWSE／TPEx 官方產業或 ETF 分類來源 → versioned mapping registry → 可見中文名稱**。registry 至少保存 source_name、官方 code／原名、display_name_zh、name_status、生效日、審核者／時間與 mapping version。

| 狀態 | 對外處理 |
| --- | --- |
| verified | 可顯示已核實的中文名稱，並可用於熱門族群、事件關聯與候選清單。 |
| pending | 顯示「官方產業名稱待對照」與資料截止日；不猜測中文題材、不顯示英文／代碼作熱門名稱、不進一般族群排行。 |
| retired／conflicted | 保留歷史稽核，不納入最新排行；需人工確認後才可恢復。 |

ETF 固定與股票族群分榜，並依 ETF 類別再分區。ETF 類別不是題材翻譯的替代品；bond、leveraged、inverse 只是不適用一般 v1 action，並不被刪除或隱藏。

### 4.2 催化劑 policy：完整熱門的硬 gate、技術觀察的 nullable component

**決定：催化劑／事件是「完整熱門」的硬性 complete gate，但不是 hot_group_v1 計算的硬性阻擋 gate。** 這沿用既有 canonical 設定，而不是為了得到結果而放寬規則：

- canonical v1 已定義 catalyst 缺失為 null、品質為 partial、不得補中性 0；四個其餘 component 的可用權重剛好為 90%，故可依既有最小 90% 規則重新正規化。
- 因 P0 的 65 個 events session 全為 unsupported，P1 的 **完整熱門排行數預期為 0**。首頁與正式熱門排行榜必須顯示「目前無完整熱門族群：官方事件資料尚無法按交易日核實」，而非顯示 0 分、0 件事件或空白原因。
- P1 可產生一個嚴格標示的 **技術與籌碼觀察**，但它不是「熱門族群」、不是完整排名、也不得直接產生候選／進場動作。

技術與籌碼觀察只有在以下條件全部成立時才可在同一股票榜或 ETF 類別分榜內比較：

1. score date membership 有效，taxonomy 為 verified，且至少 3 位成員具備所需歷史資料。
2. TAIEX 和所有納入成員在同一 score date 的 1／5／20 日報酬、20 日量能基準、5 日法人流／20 日週轉額均完整且交易日正確對齊。
3. 相對報酬、廣度、量能、法人流四個 component 均為 complete；沒有任一個 core component 可以用「催化劑缺失」掩蓋。
4. 事件 coverage 必須對該 score date、該榜內所有合格群組**一致地**為 unsupported；若有的群組已核實 event、有的群組 unsupported，禁止把兩種 coverage 混在同一排序。
5. 分數只使用四個已存在 component：以 (0.35×相對報酬 + 0.25×廣度 + 0.15×量能 + 0.15×法人流) 除以 0.90 重新正規化。catalyst 一律保持 null，不寫入 0、不推測正負影響、不以「沒有事件」當理由。
6. 輸出必須保存 component availability、使用權重、event_coverage_status=unsupported、品質 partial 與 publication_state=technical_observation_event_pending。任何缺少該等稽核欄位的資料都不顯示排序。

若事件來源日後在完整 1／5／20 日窗口可逐日核實，才可依 canonical 催化劑公式加入它。資料完整但沒有已核實事件時，催化劑才是有效的 0；事件來源 unsupported、partial、錯日或關聯未核實時必為 null。

### 4.3 對使用者的族群卡

通過公開門檻的每張卡只呈現可理解、可追溯的內容：

| 區塊 | 顯示規則 |
| --- | --- |
| 完整熱門 | 五個 component 都 complete 時，才可使用「熱門」與完整排行。P0 事件限制下，這個區塊應是 0 個並說明原因。 |
| 技術與籌碼觀察 | 僅符合第 4.2 節所有條件時顯示；標題固定加上「事件資料待補」，不使用「熱門」字樣。 |
| 為何值得觀察 | 最多三個有數字與窗口的相對報酬、廣度、量能或法人流原因；不以合成分數單獨充當理由，也不寫事件影響。 |
| 需要注意什麼 | 固定顯示「官方事件資料尚無法按交易日核實；催化劑未納入」。另顯示資料截至日、成員數、集中度、停牌／公司行動或其餘限制；未知影響不能著色為利多／利空。 |
| 候選股 | 只有完整熱門族群才可列出同一資料截止日、策略判斷資料完整、具有效研究條件的成員；技術與籌碼觀察不產生候選清單。 |
| 資料完整度 | 使用「來源擷取／當日行情／策略判斷」三層文字；不得把族群級 complete 誤解為每一檔股票都可行動。 |

### 4.4 P1 analyze 驗收表

P1 只對 2026-09-08 進行 analyze，不回放或重新評估其他日期。**有無卡片、分數或 passed 列都不是策略採用標準。** 驗收必須逐列保存原因，並符合下表：

| 範圍 | 必要 gate | 可接受結果 | 禁止結果 |
| --- | --- | --- | --- |
| P1 scope 與 provenance | as-of 固定為 2026-09-08；每筆可連回 P0 coverage manifest、raw provenance 與資料截止日。 | passed、rejected、observation、data_incomplete 都可；0 個 actionable 亦可驗收。 | 把 P0 全域 partial 當全數成功，或以其他日期／未來資料補入。 |
| 族群 eligibility | membership 在 score date 有效；策略所用群組至少 3 位合格成員、20 日群組相對 TAIEX 可計算。taxonomy verified 是公開排行 gate，不是純數值 group-relative 的替代資料。 | group-relative 通過、拒絕或資料待補。 | membership 無效、TAIEX 缺日、成員不足時仍輸出正的群組確認。 |
| 完整熱門 | 五 component 都 complete，事件資料可按 1／5／20 日核實。 | P0 下預期 0 個完整熱門，並顯示事件資料待補原因。 | 把 unsupported event 當 0 或稱為完整熱門。 |
| 技術與籌碼觀察 | 完全符合第 4.2 節四 core component 與 uniform event unsupported 條件。 | partial 的觀察列，且不產生候選／行動。 | 混合 event coverage 排名、用觀察列當完整熱門或動作理由。 |
| breakout_v1 | 20 個訊號日前高點與量、20 日群組相對 TAIEX、5 日法人／20 日週轉、5 日融資皆完整；close 突破、量比至少 1.2、族群為正、法人非明顯反向、融資未異常增加；價位有限且 RR 至少 1.5。 | passed、rejected、observation 或 data_incomplete，且只有 passed 最早成交為 T+1。 | 事件 unsupported 單獨阻擋已完整的 breakout，或把 observation 的未通過條件誤作缺資料、將缺少任一 v1 input 的列升為 actionable。 |
| pullback_v1 | 至少 60 根日線、MA20 大於 MA60、close 位於 MA20 支撐區且不低於 MA60、20 日量能與群組／法人／融資資料完整；價位有限且 RR 至少 1.5。 | passed、rejected、observation 或 data_incomplete。 | 少於 60 根日線、缺 chips／群組資料時仍通過，或把 observation 誤作資料待補。 |
| 資料待補理由 | 對個別標的精確列出近 20／60 日行情、TAIEX、有效 membership／群組、近 5 日法人、20 日週轉、近 5 日融資、公司行動因子或停牌資料的缺項。 | 資料待補卡與 audit reason 一致。 | 用全域 P0 partial、事件未核實或模糊「資料不足」掩蓋實際缺項。 |
| IPO | 少於 20 根日線不觀察；20–59 根僅 observation；至少 60 根才檢查其他 v1 gate。 | 對應的 ineligible、observation、passed／rejected／data_incomplete。 | 20–59 根 IPO 成為 actionable。 |
| ETF | 所有類別可收集、分類、進 ETF 分榜；broad_market、dividend、sector、thematic、commodity 才能套用一般 v1。 | 合格類別依一般 gate；bond、leveraged、inverse 有可辨識 fail-closed 原因。 | 因 category 未分類仍當股、或讓 bond／leveraged／inverse 產生一般 actionable signal。 |

事件 coverage 不屬於 breakout_v1 或 pullback_v1 的既有必要輸入。若其他 v1 input 完整，事件 unsupported 只能在行動卡另列「事件脈絡資料待補」，不能杜撰事件理由，也不能把 technical signal 改稱為資料完整的完整熱門推薦。

### 4.5 P1 行動摘要合併矩陣（規劃中，實作契約）

這一節是 P1 對同一標的、同一資料截止日合併 breakout_v1 與 pullback_v1 的唯一產品規則。它不改變任一 v1 公式，也不以「卡片數量」作為策略採用依據。日常頁只顯示繁中行動文案；`DecisionSummary`、`conditional`、`observation`、`data_incomplete` 等識別碼只可留在 API／稽核層。

先個別判定每一條策略，再進行合併：

- **完整且已符合條件**：該策略自己的必要輸入、標的 eligibility、資料截止日、公司行動／已知停牌狀態均可驗證；其 entry、失效價、第一目標與 RR 均為有限合法數字，第一目標 RR 不低於 1.5，且最早 T+1 可明示。只有此狀態可產生「符合條件後可研究進場」。
- **完整觀察條件**：該策略自己的 canonical 輸入已完整、規則也已完成判定，但進場 predicate 尚未成立。它的 `blocking_reasons` 為空，未通過的 rule reasons 要保留為證據；沒有 entry／失效價／目標／RR 是正常狀態，不是資料待補。只有 observation contract 額外提供合法的等待突破／回踩價位時，才可呈現等待動作；否則摘要是「暫無研究條件／繼續觀察」。
- **策略判斷資料待補**：只限於該策略自己的 canonical 必要輸入、價位驗證、執行狀態或資料截止日無法驗證，且必須列出精確缺項。「條件未成立」不是缺項。另一條策略的缺項不能倒灌成它的缺項。

所屬群組的有效 membership、群組相對 TAIEX 與策略指定的籌碼資料仍是兩個 v1 策略各自的必要輸入。相反地，**是否位於完整熱門族群**與**催化劑／事件 coverage**不是額外硬 gate：前者是公開族群排行資格，後者是背景脈絡。兩者可在卡片揭露限制，但不能單獨把已完整的個股條件降為資料待補。完整熱門候選清單是發現用篩選，不是行動中心的收錄門檻。

| 合併情境 | 主卡狀態與價位 | 次要條件／背景的呈現 | 不可做的事 |
| --- | --- | --- | --- |
| A．一條完整且已符合條件＋另一條完整觀察條件 | 以已符合條件的策略顯示「符合條件後可研究進場」、它自己的觸發／失效／目標／RR 與最早 T+1。 | 若 observation contract 有合法等待價位，才顯示「替代條件：等待突破／等待回踩」；沒有時寫「替代策略：本次條件未成立」，只保留未通過理由。觀察條件沒有 entry／目標是正常的，不列為缺項。 | 不得因替代 observation 沒有完整價位或等待價位，把主卡改成「策略判斷資料待補」。 |
| B．一條完整且已符合條件＋另一條策略資料待補 | 同 A；主卡仍由已完整條件產生。 | 在可展開區顯示「主研究條件資料完整；另一研究條件資料待補：<精確缺項>」。 | 不得把整張卡改為資料待補、隱藏主策略價位，或用另一策略的 0／空值補算。 |
| C．兩條都完整且已符合條件 | 若兩組證據可共存，維持一張卡。先取最早可執行的 T+1；相同時以 `breakout_v1` 在 `pullback_v1` 前作**固定呈現排序**，不是信心、報酬或採用排序。主條件照自身價位顯示。 | 另一組完整條件顯示為「替代條件」，保留自己的觸發／失效／目標／RR 與 T+1，並說明「兩組價位不可交叉混用」。 | 不得把兩組 entry、失效價、目標或 RR 拼成一組；不得因分數較高或預期報酬較大任意選主條件。若資料截止日、除權息調整基礎、標的識別或執行狀態互相無法調和，改為「需人工判讀」，不合成進場價位。 |
| D-1．至少一條完整 observation 有合法等待價位 | 只有該 observation contract 明確輸出有限、合法的等待突破門檻或回踩區間時，才顯示「等待突破條件」或「等待回踩條件」。 | 另一條若也有合法等待價位，顯示為替代等待條件；若資料待補，顯示其精確缺項。等待價位只作觀察，不替代 entry／失效／目標／RR。 | 不得以既有高點、MA 或最近收盤臆造等待價位，也不得把另一策略待補升格為整張卡的 blocker。 |
| D-2．一條完整觀察條件沒有合法等待價位＋另一條策略資料待補 | 主狀態為「暫無研究條件／繼續觀察」，摘要 `blocking_reasons=[]`。 | 保留完整觀察條件的未通過 rule reasons；另一策略的缺項只在該策略區塊顯示「另一研究條件資料待補：<精確缺項>」。 | 不得將整張卡標為資料待補、填入 0／破折號或虛構 entry、目標、RR。 |
| D-3．兩條完整觀察條件且都沒有合法等待價位 | 主狀態同為「暫無研究條件／繼續觀察」，摘要 `blocking_reasons=[]`。 | 保留 breakout 與 pullback 各自未通過理由，供研究詳細頁展開；沒有價位就不顯示價位區塊。 | 不得把「條件未成立」翻成缺少資料或把正常 observation 放入資料待補清單。 |
| E．已驗證持倉風險與任一策略條件同時存在 | 已驗證的使用者停損、策略失效或退場條件一律優先，主卡為「持倉風險：減碼／退場條件」。 | 原本完整的進場／等待條件可放在「其他研究條件」，並明示「持倉風險優先處理；此處不是新增／加碼指令」。使用者停損與策略失效價分別標示。 | 不得以新的進場條件壓過已驗證風險，也不得自動下單。若持倉風險資料本身待補，只能顯示「持倉風險資料待補」，不能虛構減碼／退場；其餘策略再依 A–D 判定。 |

合法等待價位必須由該策略的 observation contract 明確輸出，而非由摘要層推測：突破只接受有限正數的突破門檻；回踩只接受有限正數、下界不高於上界的回踩區間；兩者的類型必須與策略一致。等待價位是「何時再檢查」而不是已成立的 entry，因而不要求未成立條件先有 target／RR。若兩條完整 observation 有一條或兩條各自提供合法等待價位，才以 D-1 顯示一個等待主條件；兩條皆提供時，以固定策略排序呈現，另一條為替代等待條件。沒有合法等待價位時一律依 D-2／D-3 顯示暫無條件。

此次正式 DB 驗收中的 2330 breakout 與 pullback 都是 data_quality complete 的 observation，僅因策略條件未通過而沒有 entry／target／RR。它是 D-3 的實際驗收例：結果必須是「暫無研究條件／繼續觀察」、摘要 `blocking_reasons=[]`，並保留各策略理由；這不是策略結論或績效證據。

兩條 long 策略的 entry 區間不同，本身不是衝突；它們是兩套可分開驗證的條件。只有同一資料截止日存在無法調和的資料／調整／執行證據，才使用「需人工判讀」。同一策略較舊、過期或非同一 as-of 的列不得作為替代條件；應保留在研究歷史，不可混入當日摘要。

真正必須 fail-closed 的情況限於主策略必要日線、TAIEX、有效 membership／群組、法人／融資、公司行動調整或停牌資料缺漏；已符合條件卻有無效或非有限價位、RR 未達門檻；不合資格 IPO／ETF；已知無法在 T+1 執行；或前述不可調和的證據衝突。完整熱門為 0、事件 unsupported、任一策略僅 observation、或替代策略資料待補，均不是已完整策略的 fail-closed 原因。

P1 實作驗收至少要能以正式或隔離官方 raw 重跑 A–E 五種情境：

1. A、B、C 的每一張主卡都保留完整主策略價位、RR、T+1 與可追溯 evidence；B 不得得到整體資料待補狀態。
2. D-1 只在 observation contract 提供合法等待價位時顯示等待條件；D-2／D-3 則必須為「暫無研究條件／繼續觀察」、摘要 `blocking_reasons=[]`，保留未通過理由且不顯示 0、破折號或偽造 RR。另一策略的待補原因可展開，但不能成為摘要 blocker。
3. E 的已驗證持倉風險必須排在任何新進場條件前；風險資料待補不可以假造退場結論。
4. 行動清單必須收錄每一個完整且已符合條件的標的，即使它未列入完整熱門候選；同時揭露「族群脈絡」與「事件脈絡」的真實狀態，不得把它包裝成熱門推薦。
5. API／稽核輸出必須能辨識主策略、替代條件、各自資料截止日、每條策略的未通過理由與精確待補原因，以及摘要與 per-strategy 的 blocker 範圍；日常 UI 不得露出內部狀態字串。
6. 2330 的雙 complete-observation 官方資料例必須重跑為 D-3，不可因 entry／target／RR 缺席而成為資料待補。

## 5. 行動中心達到可研究的驗收

行動中心不以卡片數量為成就。Phase 3 必須建立四個可重跑的驗收案例，市場資料只能是正式或隔離資料庫中的官方 raw capture；不得以合成價格、合成 chips 或樣本資料偽造通過。

| 案例 | 必要官方證據 | 預期卡片與不可做的事 |
| --- | --- | --- |
| breakout | 同一 as-of 的 65 日 OHLCV、前 20 日高點／量、TAIEX、合格族群、5 日法人與融資、有效價位。 | 僅在 close 超過前 20 日高點、量比至少 1.2、其餘 gate 通過且 RR ≥ 1.5 時顯示「符合條件後可研究進場」；明示最早 T+1。 |
| pullback | 至少 60 根日線、MA20／MA60、支撐區、20 日量能基準、族群與 chips 證據。 | 條件未成立但 contract 有合法回踩觀察區間時才顯示「等待回踩條件」；沒有該價位時為「暫無研究條件／繼續觀察」。符合全部條件才可呈現有限且有效的 entry／invalid／target。 |
| 持倉風險 | 官方行情、停牌／公司行動狀態與一筆隔離資料庫中的使用者持倉輸入。 | 已驗證失效或使用者 stop 條件時顯示「持倉風險：減碼／退場條件」；這不是自動下單，且策略 invalid 與使用者 stop 必須分開。 |
| 資料待補 | 使用 P0 中未達 20／60 日行情或 chips coverage 的真實官方缺口，或隔離官方 run 的明確缺口重跑。 | 預設收合，顯示資料截至日與缺少欄位；沒有完整 levels 時不得顯示 entry、失效價、目標、RR 或投資方向。 |

每個案例的 test record 必須保存：official raw payload／hash reference、instrument、exchange、score date、coverage manifest、canonical version、輸入品質、預期 action state 與畫面文案。持倉案例中唯一可人工建立的是使用者的隔離持倉資料；市場資料仍必須保持官方可追溯。

通過策略 gate 的價位一律遵守：

- entry、invalid、target_1（及存在時的 target_2）均為有限正數，且 invalid < entry < target_1。
- 第一目標 RR 至少 1.5；無法計算時一律不顯示 RR。
- T 是訊號收盤日；最早成交只能是下一個可判定的交易日 T+1，不能把 T 收盤當成交。
- 停牌、缺價格、缺公司行動調整因子、或同日 stop／target 順序不可判定時，tracking／settlement 是 incomparable；不可把它算進勝／負、報酬或採用結論。

四個案例通過只代表資料與產品契約可運作，不代表策略有效、已採用、具勝率，或已完成 walk-forward／獨立 OOS。

## 6. 新聞來源治理

### 6.1 既有官方公告

| 來源／事件 | 對外類別 | 摘要與連結政策 | 對行動的關係 |
| --- | --- | --- | --- |
| MOPS material_information 且有直接標的關聯 | 個股公告 | 保留來源標題與 description 的折疊預覽；若只有 feed URL，標示「官方公告資料集」，不可假裝單篇原文。 | 只作事件證據與 targeted retry 優先級；預設影響尚未判定。 |
| MOPS 無直接標的關聯 | 台灣官方事件 | 同上，保留 event_at 與 collected_at 的區別。 | 不自動關聯個股或族群。 |
| TWSE／TPEx 停復牌、公司行動或官方公告 | 個股公告（直接標的）或台灣官方事件（無直接標的） | 說明它可能是交易可比性／公司行動證據，不一律等同市場新聞。 | 可使 tracking 成為 incomparable；沒有完整策略輸入時不產生進出場建議。 |

官方公告的分類、預設折疊、Asia/Taipei 時間、item／feed 連結差異和未核實族群隱藏方式，以 [NEWS_SPEC.md](NEWS_SPEC.md) 與 [UI_COPY_SPEC.md](UI_COPY_SPEC.md) 為準。原始公告未提供摘要時，顯示「官方來源未提供摘要」，不生成或改寫內容。

### 6.2 國際、總體與媒體來源的準入

任何一個新來源進正式新聞前，必須完成下列治理紀錄：

1. **來源白名單**：來源所有者、來源類型、授權／使用條件、允許的 endpoint／內容、canonical URL 格式、頻率／rate limit、語言、保留期限、停用開關與責任人。
2. **原文與時間**：每一項都有實際 source_name、source_url、source_url_kind=item、published_at（若來源提供）、event_at（若可驗證）與 collected_at。沒有單篇 URL 或時間的資料不可偽裝成逐篇新聞。
3. **去重與生命週期**：先以 source item ID／canonical URL 去重；再以來源、正規化標題、日期、標的與 content hash 形成 key。更正、撤回、重複或下線保留 audit 狀態，不直接覆寫歷史來源。
4. **關聯與影響**：預設 impact_direction=unknown。標的／族群只在來源直接明示，或以可稽核規則／人工審核驗證後才可顯示；方向、理由與方法要可追溯。關聯不是買賣訊號。
5. **人工審核**：任何跨來源主題合併、事件—族群關聯、正負影響標記與 AI 產生摘要，均需保存 reviewer、reviewed_at、rationale、policy version 與原始證據。未審核資料只可停留在隔離／quarantine 稽核區，不可寫入正式 NewsItem 或日常 UI。

尚未被白名單核准的搜尋結果、瀏覽片段、社群貼文、媒體 URL 或推測，**不得**寫入正式新聞、族群原因、候選理由或行動卡。若未來要使用 AI 摘要，也必須先有明確內容授權、保留政策與人工審核規則；本計畫不預設已獲得這些權限。

## 7. 直接可實作項目

程式 task 可依本規格直接實作／測試的清單：

1. 建立 bounded collection plan：每筆 scope 有 exchange、domain、交易日範圍、batch、request key、attempt、狀態與 raw／error reference，並強制 5 日 batch、3+2 次重試上限。
2. 建立 coverage manifest 與 API／系統頁資料契約，將 success、partial、missing、skipped_non_trading、stale 分開呈現，且可連到資料截止日。
3. 為 authoritative stock、ETF、IPO、TAIEX、chips、官方事件／公司行動實作第 3.1 節的 65／20 日 bounded backfill 與 targeted retry queue；只從既有官方 adapter 取資料。
4. 建立 versioned official taxonomy mapping／membership 驗證流程；pending、conflicted 名稱不進日常熱門排行或新聞族群標籤。
5. 對 hot group 增加兩層公開 gate：五 component complete 才是完整熱門；在 uniform event unsupported 下，四 component 可作技術與籌碼觀察，但必須 partial、重正規化、不可稱熱門或產生候選。
6. 實作「完整熱門／技術與籌碼觀察／需要注意」的結構化欄位與空狀態；候選股只能取完整熱門中的策略判斷資料完整成員。
7. 為行動中心建立四個使用隔離官方 raw 的可重跑驗收案例，以及 incomparable、沒有價位／RR時不顯示的 UI／API 測試。
8. 將既有官方 Event 分類與來源 link policy 固化；未核實 theme 關聯不輸出日常頁。為未來來源建立 whitelist／quarantine／review metadata，但不要先接入未核准媒體。
9. 以 planned、coverage status 與 run audit 更新 UI，避免把本計畫或單一成功 run 顯示成「全市場完成」。

## 8. 需要使用者或外部來源決策

下列事項不能由程式推測或自行啟用：

| 決策 | 為何需要外部授權／決定 |
| --- | --- |
| 國際、總體、台灣媒體的來源白名單與授權 | 決定可否抓取、保存、摘要、展示原文連結及保留期限。 |
| 新聞人工審核責任人與服務水準 | 決定誰可核實主題、標的、影響方向、撤回與更正。 |
| 可按交易日核實的官方事件來源 | P0 的既有 official feed 65 session 全為 unsupported；在確認可用官方 endpoint、使用條件與稽核方式前，催化劑必須保持 null。 |
| 官方 taxonomy 中文映射的審核責任 | 避免把英文／代碼或不確定產業翻譯成看似確定的中文題材。 |
| Phase 3 的執行資源與頻率 | 決定可執行多少 bounded batch、何時重試、何時標 stale；在另有明確決策前不建立排程。 |
| 資料保留、撤回與使用者可見範圍 | 影響 raw、quarantine、媒體 metadata 和資料診斷的保存及隱私／法務處理。 |
| 何時進入 walk-forward／獨立 OOS | 必須先有足夠、可比且完整的官方歷史 coverage；不可由本階段自行宣告。 |

## 9. Phase 3 完成定義

只有同時滿足下列項目，才能稱為「Phase 3 已完成」；其中任一項未完成時，產品仍應誠實顯示 planned、partial 或資料待補：

1. P0 coverage manifest、bounded batch、重試與 raw/error audit 已部署並通過隔離測試。
2. P0 的 65 日官方資料範圍、2 個 skipped 日期、個別 20／60 日缺口、partial 資料域與 integrity／provenance 已可清楚報告；partial 不會被升格為完整。
3. 若 events 仍 unsupported，完整熱門排行必須正確為 0；只有符合第 4.2 節的 technical observation 才可顯示，且不會變成熱門或候選。若日後 events complete，才驗收五 component、至少三成員的完整熱門分榜。
4. 第 5 節的 breakout、pullback、持倉風險、資料待補四個案例都可用正式或隔離官方 raw 重跑，並通過 T+1、RR、價位與 incomparable 的檢查。
5. 現有官方公告有正確分類、折疊、來源、時間、去重與未核實關聯處理；任何新增新聞來源均已先通過第 6.2 節的白名單和審核 gate。
6. README、資料來源、操作、策略、產品與 UI 文案文件同步記錄實際 coverage、未完成來源與限制；仍不宣稱策略績效、walk-forward、OOS 或採用結論。

## 10. Phase 4 呈現層交接（規劃中）

Phase 4 不改變本計畫的 P0 partial、P1 per-as-of gate、五 component 熱門 gate、事件 unsupported 或候選限制。它只處理產品呈現：將同一標的的候選／行動壓縮成一張卡、把策略原始 reason 翻成繁中、建立新聞詳情與來源時間排序、並採用精確股數加張／零股顯示。新聞 `collected_at` 不再是列表的主要時間；它只作收錄稽核與最後 fallback，避免歷史回補顛倒新聞時序。完整實作契約與驗收矩陣見 [PHASE4_PLAN.md](PHASE4_PLAN.md)。
