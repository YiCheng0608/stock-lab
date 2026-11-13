<!-- owns: 目前產品能力 -->
# 目前產品能力

依領域分組，每列一項已完成的能力：「現況」寫做到哪與限制，「依據」是 Issue／PR，「規格」連到契約段落。

## 資料收集與回補

| 能力 | 現況 | 依據 | 規格 |
|---|---|---|---|
| 官方日資料 | TWSE／TPEx 整批日行情、法人、融資、官方事件的收集與回補 | — | — |
| 融券餘額 | 每日從同一份融資融券官方檔收融券今日餘額（張，`short_balance`），缺欄或非數字留空；2024-09-30 起的歷史以 `chips short-balance` 從已存 raw 補寫；不進策略、評分與候選，畫面不顯示 | [#662](https://github.com/YiCheng0608/stock-lab/issues/662) | [籌碼來源](DATA_SOURCES.md#籌碼來源) |
| 重大訊息 | 以 MOPS 日期查詢記每日已核實查詢日與空日，可單獨回補事件 | [#464](https://github.com/YiCheng0608/stock-lab/issues/464) | [重大訊息日期查詢](DATA_SOURCES.md#重大訊息日期查詢) |
| 季度財報 | 季度累計營收與基本 EPS 可用 MOPS 彙總報表回補近 8 季，可得日用各產業的法定申報期限，基本面快照保留首見出表日 | [#529](https://github.com/YiCheng0608/stock-lab/issues/529) | [季度財報回補](DATA_SOURCES.md#季度財報回補) |
| 月營收 | 每日收集官方快照、可回補近 24 個月（上市、上櫃的國內與國外公司），以可得日篩選、不納入策略 | [#530](https://github.com/YiCheng0608/stock-lab/issues/530) | [月營收](DATA_SOURCES.md#月營收) |
| 月營收更正 | 快照出表後公司更正的月份以 MOPS 營業收入統計表為準，標「已更正」並保留原快照值，之後的快照不會改回 | [#543](https://github.com/YiCheng0608/stock-lab/issues/543) | — |
| 申報窗口自動回補 | `daily` 在申報期限前後的窗口自動回補最近 2 季與最近 2 個月，補上快照換期後才上市的新股與晚申報，失敗只記非核心警告 | [#536](https://github.com/YiCheng0608/stock-lab/issues/536) | [排程](ops/SCHEDULING.md#日誌與-run-記錄) |
| 長區間回補 | CLI 回補可跨多段 93 日視窗 | — | — |
| 普通股列與標的狀態 | 官方行情的普通股列不悄悄丟掉，主檔外的列寫入既有標的或記 `unmatched_bar`；標的的下市／轉上市／休眠狀態每日同步 | — | [標的狀態同步](DATA_SOURCES.md#標的狀態同步) |
| 交易日曆 | `daily` 的 trading_calendar 步驟保存官方休市表 | — | [交易日曆](DATA_SOURCES.md#交易日曆) |
| 指數日 K | 加權、櫃買兩個指數比照個股存真實開高低收與量值，2023-09-01 起回補（比個股的 2024-09-30 早約一年，個股第一天就有指數的季線、半年線與年線；2024-09-30 前的指數列不是交易日基準，不讓個股看起來缺資料）、daily 每日補，加權的收盤列原地升級、交易日基準不變 | [#563](https://github.com/YiCheng0608/stock-lab/issues/563)、[#552](https://github.com/YiCheng0608/stock-lab/issues/552) | [指數日 K](DATA_SOURCES.md#指數日-k) |
| 台指期 | 每日用期交所開放資料，2023-09-01 起到開放資料第一天之前以期交所網站下載 `futDataDown` 回補（另一個來源名稱，限本機個人研究，#563），存合約月份、未平倉與結算價 | [#552](https://github.com/YiCheng0608/stock-lab/issues/552) | [台指期](DATA_SOURCES.md#台指期) |
| 美股指數 | S&P 500、NASDAQ 綜合、道瓊工業與費城半導體指數的 FinMind 日線，收集後存在資料庫與 API（#633 起大盤頁不顯示）；獨立的 `index-bars us-collect`，scheduler 容器週二至週六 06:30、09:30 抓，2023-09-01 起；開高低收與量照存，費半來源沒有量；台股 daily 不再抓美股；API 的新鮮度仍帶資料日、「非最新」與「美股休市」判定；不進策略或回測 | [#568](https://github.com/YiCheng0608/stock-lab/issues/568)、[#547](https://github.com/YiCheng0608/stock-lab/issues/547) | [美股指數](DATA_SOURCES.md#美股指數) |

## 分析與策略

| 能力 | 現況 | 依據 | 規格 |
|---|---|---|---|
| 規則策略 | 現行 `breakout_v3`／`pullback_v4`，回踩型的 RR 以進場區中點計算；另有 `hot_group_v1` | [#580](https://github.com/YiCheng0608/stock-lab/issues/580) | — |
| 融資條件 | 非融資標的的融資條件記不適用；5 日前融資餘額為 0 時依餘額判定 | [#392](https://github.com/YiCheng0608/stock-lab/issues/392)、[#404](https://github.com/YiCheng0608/stock-lab/issues/404) | — |
| 舊版策略 | `breakout_v1`／`pullback_v1`、`breakout_v2`／`pullback_v2`、`pullback_v3` 的舊訊號照舊可讀 | — | — |
| 策略 registry | 策略已統一由 registry 宣告 | — | [策略框架與 registry](spec/README.md#策略框架與-registry) |
| 條件價位 | `daily` 的 strategy_levels 步驟為每個訊號保存下一交易日要達到的收盤與量、參考停損與目標；不影響訊號與 run 狀態；步驟失敗由看門狗回報 | — | [條件價位 `strategy_levels_v1`](spec/strategy_levels.md) |
| 規則最早執行日 | 由 trading_calendar 步驟保存的官方休市表推算，不再依賴之後的日線 | — | [價位、ETF 與生命週期](spec/README.md#價位etf-與生命週期) |
| 資料不足原因 | 策略判斷資料不足時，個股頁與行動摘要寫出原因句（上市未滿 60 日、停牌、官方無成交、官方行情表或法人／融資表未列、ETF 類別不適用等），狀態寫「資料不足，無法判斷」（只有 ETF 類別不適用時寫「不適用一般研究條件」）；策略總表的「差哪個條件」寫同主題的原因句，只有沒收到、可回補的缺口寫「待回補」 | [#511](https://github.com/YiCheng0608/stock-lab/issues/511)、[#524](https://github.com/YiCheng0608/stock-lab/issues/524) | [UI_COPY_SPEC §6.1](UI_COPY_SPEC.md#61-資料不足的原因句) |
| 族群分層 | 族群分官方產業與版本化題材表兩層 | — | [題材表](INDUSTRY_CLASSIFICATION.md#7-題材表) |
| 族群熱度 | `hot_group_v1` 對兩層各算一榜並有排名 API；催化劑依 MOPS 日期覆蓋計算（窗口全部核實才有值，沒有事件是 0，#453），值是有事件成員比例的同榜 percentile（#474） | — | [hot_group_v1](spec/hot_group.md) |
| 技術回測與研究介面 | 已有技術回測及研究介面 | — | — |

## 候選與追蹤

| 能力 | 現況 | 依據 | 規格 |
|---|---|---|---|
| 明日候選排序 | `daily` 在 analyze 之後以 candidate_score_v7（技術＋籌碼＋族群＋新聞情緒，各分項可見、只用於排序）對當日 conditional 普通股排序，保存明日候選至多 20 檔與規則式理由、所屬族群，由 `/api/candidates` 與個股 API 的 `candidate` 提供 | — | [`candidate_score_v7`](spec/candidate_score.md#candidate_score_v7) |
| 流動性門檻 | 20 日均量未達 1,000 張的股票不列候選，個股頁與我的追蹤在成立旁註明 | [#490](https://github.com/YiCheng0608/stock-lab/issues/490) | — |
| 候選 AI 進出點說明 | `daily` 以 `claude -p` 產生、標「AI 推論」的進出點說明 | — | [候選 AI 進出點說明](spec/candidate_score.md#候選-ai-進出點說明) |
| 進場方式 | 每檔候選的第一行以白話寫進場方式：突破型或回踩型、明天起在哪個價位附近可進場、跌破哪裡停損與目標（訊號的成立價位；失效只看停損），收合的完整條件列資料日的判定，缺價位時寫原因 | [#491](https://github.com/YiCheng0608/stock-lab/issues/491) | [UI_COPY_SPEC §10.2](UI_COPY_SPEC.md#102-進場方式) |
| 追蹤計畫 | 今日名單的明細與個股研究分頁的成立條件可「加入追蹤」；`daily` 的 `plan_tracking` 步驟每日以日線規則更新計畫的模擬成交與結果；可取消、不統計勝率 | — | [使用者追蹤計畫](spec/tracking.md#使用者追蹤計畫) |
| 追蹤口徑版本 | 現行 `tracking_v2` 在開盤已越過目標一或失效價時不進場、T+N 只用第 N 根以前的成交；settlement、technical backtest（`technical-backtest:v2`，技術回測頁顯示版本）與計畫（`plan_tracking_v2`）都記版本，舊版本的列不改寫 | — | [口徑版本](spec/tracking.md#口徑版本) |
| 行動摘要與持倉 | 已有行動摘要與持倉 | — | — |

## 新聞與 LLM

| 能力 | 現況 | 依據 | 規格 |
|---|---|---|---|
| 新聞收集 | 國內／國際財經新聞每 2 小時收集進 DB，以規則排除彩券與社會等非股市內容 | — | [新聞來源](DATA_SOURCES.md#新聞來源) |
| 規則關聯 | 以規則關聯個股與 ETF，含簡稱、兩字名稱與去掉產業尾詞的全名（`rule:exact-name-code/v3`，卡片標規則版本）；兩字名稱的誤配以唯讀量測工具判讀 | [#451](https://github.com/YiCheng0608/stock-lab/issues/451)、[#461](https://github.com/YiCheng0608/stock-lab/issues/461) | [NEWS_SPEC §2](NEWS_SPEC.md#規則關聯) |
| LLM 摘要與題材候選 | 以 LLM 批次（`claude -p`）產生摘要、關聯候選與方向判讀；摘要以提示約束忠於原文、數字不在原文的那則不顯示；題材候選要引用原文片段且以規則核對，沒依據的不保存 | [#413](https://github.com/YiCheng0608/stock-lab/issues/413) | — |
| 個股候選核實 | 讀取時以規則核對名稱或代號是否出現在原文，畫面分「規則核實：原文提及」與「推論」 | [#465](https://github.com/YiCheng0608/stock-lab/issues/465) | — |
| 候選標示 | 候選一律寫代號與名稱；興櫃股的名稱取自 TPEx 興櫃名冊、標「（興櫃）」，已下市的標「（已下市）」，兩者都不連到個股頁；主檔與名冊都查不到的代號不顯示，原因留在 API | [#512](https://github.com/YiCheng0608/stock-lab/issues/512) | [興櫃名冊](DATA_SOURCES.md#興櫃名冊) |
| 處理額度 | 每輪新舊各半額度，3 天窗口內的新聞在當天的各輪間處理完，一批漏回一則時其餘照寫 | [#450](https://github.com/YiCheng0608/stock-lab/issues/450) | — |
| 分欄保存 | LLM 結果分欄保存並標推論 | — | [NEWS_SPEC §5](NEWS_SPEC.md#5-ai-摘要與推論) |

## 各頁面

| 能力 | 現況 | 依據 | 規格 |
|---|---|---|---|
| 主導航 | 六個主導航（今日名單、大盤、我的追蹤、族群、個股、策略說明，#493、#549）已存在；新聞清單與研究、資料品質、用語表由頁尾的「系統」頁（`/system`）進入（#631） | — | [六個主導航](PRODUCT_SPEC.md#2-主導航與資訊順序) |
| 今日名單（`/`） | #493 前的「明日候選」區；候選顯示排名、價位、四分項（null 附說明）、理由與族群，並附候選 AI 進出點說明；桌面表格七欄固定寬度、進場句放在「進場方式」欄，1280×800 第一屏 6 列，1279px 以下改卡片；名單下方是熱門族群一張卡，首頁不放新聞卡（#625）；顯示族群兩榜前 5 名；只留一行大盤摘要連到大盤頁 | [#549](https://github.com/YiCheng0608/stock-lab/issues/549) | — |
| 個股頁 K 線 | 日／週 K 線、成交量、MA5～120 與 MACD／RSI／KD／布林面板（讀 bars API），K 線可切 1M／3M／6M／1Y／全部區間（「全部」另取最多 1500 根） | [#600](https://github.com/YiCheng0608/stock-lab/issues/600) | — |
| 個股頁策略總表 | 「進出場」分頁最上方的策略總表為每個策略列出狀態（成立／觀察／資料不足／不適用）、差哪個條件、成立價位或「條件未成立・觀察價位」，候選股另有候選列（排名、價位、四分項、理由與族群）與 AI 推論 | [#274](https://github.com/YiCheng0608/stock-lab/issues/274) | [UI_COPY_SPEC §10.1](UI_COPY_SPEC.md#101-個股策略總表) |
| 個股頁財務分頁 | 季報下方列近 12 個月月營收 | — | — |
| 我的追蹤（`/watch`） | 原行動頁，舊網址 `/actions` 轉址；在行動列表之前分「我的庫存／追蹤計畫／追蹤回看」三區顯示狀態、模擬報酬與逐日明細；`/actions/:exchange/:symbol` 轉到個股頁進出場分頁 | — | — |
| 我的追蹤分級 | 依 `action_tier_v1` 分級排序（持倉風險、今日候選、其他成立條件、接近成立在前，其他觀察與資料不足在後），預設只列重點並隱藏 ETF，以篩選膠囊與「含 ETF」切換；接近成立卡只寫還差哪個條件與差距、不顯示價位，「暫無研究條件」的主要原因寫差項最少的策略差哪幾項 | [#278](https://github.com/YiCheng0608/stock-lab/issues/278)、[#279](https://github.com/YiCheng0608/stock-lab/issues/279) | [UI_COPY_SPEC §5](UI_COPY_SPEC.md#5-行動中心的分級與預設篩選) |
| 族群頁 | 可切換產業／題材兩榜看排名、五分項、品質與成員數；族群詳情有近 20 日熱度走勢、成員（題材附證據）與相關新聞 | — | — |
| 大盤頁（`/market`） | 集中大盤概況（加權、櫃買指數、成交金額、漲跌家數） | — | — |
| 大盤頁指數總表 | 3 檔指數一張總表（加權、櫃買、台指期近月；#633 起頁面不列四檔美股，資料照收）：收盤、漲跌、漲跌幅、資料日與非最新、相對季線（各自的 `indicators/v1` `ma60`，判定同加權季線）、來源；台指期換月日不計漲跌、寫「換月」；點一列或 Tab 到列按 Enter 切換下方共用的一張日 K，網址 `?index=` 保留選擇 | [#564](https://github.com/YiCheng0608/stock-lab/issues/564) | — |
| 大盤頁日 K | 沿用個股頁 K 線元件（日／週切換與指標面板） | — | — |
| 加權指數與季線 | 大盤概況下方一行：加權指數與季線（MA60，讀指標批次已存的 `indicators/v1` `ma60`）：資料日收盤在季線之上、之下或持平，與近 250 個交易日內最近 3 段在季線之上的區段，定義同 #546 研究版 R3（收盤嚴格高於 MA60、需要 60 根收盤，不足時寫資料不足）；只當背景資訊顯示、不進策略與候選 | [#561](https://github.com/YiCheng0608/stock-lab/issues/561) | — |

## 排程與維運

| 能力 | 現況 | 依據 | 規格 |
|---|---|---|---|
| scheduler 容器 | `worker.cli serve` 排程 `daily`／`news`／`us` 工作 | — | [排程](ops/SCHEDULING.md#scheduler-容器的排程serve) |
| 看門狗與 run 記錄 | 看門狗與 `schedule_runs` run 記錄 | — | — |
| 維護模式 | 回補、回測期間的維護模式只停 daily 與 news | [#468](https://github.com/YiCheng0608/stock-lab/issues/468) | [維護模式](ops/SCHEDULING.md#維護模式) |

## 驗證、CI 與版本

| 能力 | 現況 | 依據 | 規格 |
|---|---|---|---|
| PR 驗證 | CI 每個 PR 依改動範圍在假資料庫上端到端驗證受影響的主導航，master 每晚跑全套 | — | — |
| V1 範圍 | 2026-10-17 基線的 M1～M3 核心條件都已實作 | — | [2026-10-17 基線](ROADMAP.md#v1-範圍基線2026-10-17-核定) |
| V1 發布驗收 | V1-G7 發布驗收已於 2026-11-02 結案（排程窗口 2026-10-27～11-02），V1 milestone 已關閉 | [V1-G7 發布驗收](https://github.com/YiCheng0608/stock-lab/issues/260) | — |
