# 個股研究頁契約

更新：2026-10-07。本文定義 `/stocks/:exchange/:symbol` 的現行有限契約；原個股頁 review 範圍見 §5，M1-P1 總覽見 §9，M1-P2b 單日法人見 §10，M1-P3b selected 官方事件見 §11，待做籌碼見 §8；成交量精確呈現見 §14，M3-P6c 個股行情讀回隔離的核定契約與有限接受範圍見 §15。這不代表完整研究產品、R0 或 [ROADMAP](ROADMAP.md) 已完成。

現行新增3105／6488 explicit10/06真5／20日法人窗口、完整24日曆、具名可信操作與失敗讀取清值見[§36](#36-m1-chips-cutoff-1006-1同截止法人窗口與完整日曆)；W8依§24原cutoff／pins保留，不自動提升default。

## 1. 使用者工作與資訊順序

使用者先確認標的、實際資料區間與價格口徑，再依序讀取行動摘要、日 K／成交量／MA20／MA60、族群、法人籌碼、官方事件／新聞、策略條件，以及 coverage／來源。頁面允許零行動、零新聞、缺籌碼或均線不足；不得為填滿畫面造資料。它不是 AI 選股、下單或完整交易計畫。

## 2. 現有 API 與畫面 cross-review

### 2.1 實際 payload

前端 `getStock(exchange, symbol, asOf?)` 呼叫 `GET /stocks/{exchange}/{symbol}?as_of=YYYY-MM-DD`。`as_of` 可省略；後端組成同一資料日期截止的 instrument detail，再加入 decision summary、coverage、news 與 `overview`。M1-P1 總覽及日期控制見 §9；截止不代表歷史當時可得。

| 區塊 | 實際欄位／上限 | 呈現限制 |
| --- | --- | --- |
| 標的 | `instrument` | 以 exchange＋symbol 識別，顯示名稱與類型。 |
| 行情 | `bars` 最多 120 個候選位置，回傳舊到新；新增 `market_read` | 精確成交量依 §14；M3-P6c 的 nullable 讀回、欄位狀態、拒列不回填及有限接受範圍依 [§15](#15-m3-p6c個股詳情行情讀回污染隔離)。只代表本次視窗，known 不等於來源准入。 |
| 技術快照 | 最新一筆 `features` | 可作最新摘要，不能由單點 feature 畫歷史 MA；歷史 MA 由 response bars 算。 |
| 族群 | `groups` | 顯示名稱與有效期，不由名稱推論題材或熱門。 |
| 籌碼 | `chips` 最多 120 筆 | 法人／融資連同日期和來源顯示；不得推論分點或特定外資身分。 |
| 事件／新聞 | `events` 最多 50、active 非 conflict `news` 最多 20 | 分開或標示類型；不能互相冒充或一律稱已核實催化劑。 |
| 策略／行動 | `strategy_conditions`、`signals` 最多 20、`decision_summary` | requires 只是需求，不是通過；沿用既有價位、信心與 product-time 語意。 |
| 品質 | `coverage`、`quality_summary`、`data_quality` 最多 10 | 顯示用途別完整度、缺日與 unknown；圖表存在不能替代 coverage。 |
| M1-P1 總覽 | `overview`、`news_cutoff` | 原件合格價格、法人／事件缺項與研究條件共用資料截止；新增原件價格與既有 bars／K 線的來源驗收範圍不同，見 §9。 |

### 2.2 價格口徑

圖表只使用每根 bar 的原始 open／high／low／close。payload 沒有 `price_basis`、OHLC adjustment factor、applied-through 或完整公司行動還原鏈；單一 `adj_close` 不足以生成 adjusted OHLC。因此固定標示：

> 原始 API 價格；還原方式未提供

這不等於已確認「未還原」，也不代表還原已完成。

原DB bars沒有currency欄位，標的可能不是新臺幣計價；表外寫「各標的報價幣別的元」，指數寫「點」，未證幣別不得猜NT$。M1-PRICE-1的兩股memory另有正面TWD typed契約，依[§25](#25-m1-price-1上櫃兩股單日價量閉環有限接受)，不外推原DB或其他市場。

## 3. 圖表資料契約

### 3.1 驗證與排序

- date 必須合法且唯一；重複日期 fail closed，不能任選、平均或覆寫。
- O／H／L／C 須為有限數字且 `low <= min(open, close) <= max(open, close) <= high`；非法列不生成 K 棒，不能用 close 補值。
- 成交量可用性依 §14 的精確欄位與舊回應回退條件；不可用值不補 0，對應列／區塊須標不可用。
- 合法 bars 依日期舊到新排序；停牌或無交易按原欄位標示，不造平盤棒。
- 顯示總筆數、可畫筆數及最早／最晚日期。少於 120 筆只說實際筆數；恰為 120 筆也只能說「本次最多 120 根視窗」。

### 3.2 MA20／MA60

MA20／MA60 是前端由合格、唯一日期 bar 的最近 20／60 個 close 計算的簡單平均，不回寫 API／DB，也不代表 worker feature 或策略升版。

- 前 19／59 點保持缺值，不用短窗口、前填或回填。
- 已拒列或已知缺日會中斷受影響窗口，不能靜默跨越補算。
- 計算前不逐筆四捨五入；最新 API feature 如另列，須標為不同 provenance 的最新快照。

### 3.3 互動與等效資訊

日 K、成交量與兩條 MA 使用相同日期並有可辨識圖例；tooltip／focus 與可讀表格至少提供日期及 OHLCV，數值和單位一致。數值表格把單位置於表題或緊鄰說明，數值格只放數字並保留正負號；缺值留空且在表外說明，合法 0 仍顯示。縮放／復位只限 response 視窗，不暗示載入完整歷史。鍵盤與輔助技術使用者可操作必要控制並讀取等效 DOM 資料；顏色不是唯一辨識方式。

無 bars、全部無效、部分無效與載入失敗各有訊息；其他可用研究區塊仍保留。

## 4. 來源、區間與研究整合

頁首或圖表旁顯示標的、日期區間、總筆數／可畫筆數、所有 source 的安全標籤與價格口徑。來源缺失、unknown 或 mixed 時如實標示，不能由 fallback 改稱官方。

- decision summary 可為空或資料待補；規則價位不是委託、成交或個人化建議。
- groups 顯示 membership 有效期，不把 membership 當熱門或催化劑。
- chips 分開顯示外資、投信、自營商與融資。「外資」是來源「外資及陸資」合計欄位的日常簡稱；三大法人只有這三類，不把廣義券商或分點併入。
- 券商／分點區塊依 exchange 提供 TWSE 或 TPEx 官方逐檔查詢入口，並顯示「目前未提供整合資料」。入口不形成主力排行、歷史分點資料或投資人身分判定。
- events 與 news 保留類型、來源及事件／發布時間，沿用 conflict／unknown 契約。
- strategy conditions 只說明輸入需求；實際結果讀 decision／signals，不新增前端評分。
- coverage／quality 保持可見，尤其 20／60 日與 bar／chip 缺口；raw 可收合，但缺資料原因不能只藏在 raw。

## 5. 驗收矩陣

| 案例 | 必須觀察到 |
| --- | --- |
| ≥60 根完整資料 | K、量、MA20、MA60、OHLCV 提示、縮放／復位、等效表格及區間／來源／basis 一致。 |
| 20–59／1–19 根 | MA20 從第 20 根開始；MA60 不足不畫。1–19 根仍顯示合法 K／量，兩條 MA 都不補。 |
| 0 根 | 顯示無圖表資料；其他 payload 若存在仍可研究。 |
| 非法 OHLC／volume | 拒列並顯示數量／原因，不補 close 或 0。 |
| 重複／反序日期 | 重複 fail closed；純順序問題可穩定排序但不改值。 |
| 缺日／停牌 | 不跨缺口算 MA 或造 K，與 coverage／is_suspended 相容。 |
| unknown／mixed source | 不顯示成單一官方來源。 |
| 法人籌碼 | 欄名為「外資／投信／自營商」；表外統一標示單位與空白原因，數值格只放含正負號的數字，合法 0 不消失。 |
| 券商／分點 | 依上市／上櫃標的開啟對應官方查詢；畫面明示尚未整合資料，不造主力排行或分點數值。 |
| events 與 news 並存 | 類型、來源、時間、連結與空值可辨識。 |
| 行動摘要缺失／待補 | 不造評分或價位；圖表與其他研究區塊仍可用。 |

### 5.1 2026-09-12 final review 證據

穩定 source snapshot 已完成 §5 矩陣的前端資料邊界、型別、production build、桌面／窄版與隔離唯讀 API 有限 review；大型 JS chunk 警告仍在。原始驗收紀錄可查 `git show 2acc3c5deff6fbf33ee104e2e28e3f16e8904a73:docs/STOCK_RESEARCH_PAGE.md`。此證據不涵蓋下一節或 §8。

## 6. 明確未包含

完整歷史下載、adjusted OHLC、PIT／availability truth、legacy／new signal comparison、B7 paired replay、Wilder ATR 正式接線、策略績效／勝率、AI 研究、完整 trade plan、個人風險部位、正式 DB migration、來源採購、自動排程與下單仍未完成。

## 7. 前端顯示契約

UNIT-LOTS-1 的現行日常主值以張顯示，單日／5與20日法人及成交量保留精確零股，原股數移入預設收合的來源稽核 details；已為張的融資不再除1,000。來源單位 unknown／mixed 不猜，合法零及正負方向保留，顯示換算不改 API／DB／計算或 raw evidence。統一格式、canonical邊界、輸入與每股價格口徑只由 [UI_COPY_SPEC §10.3](UI_COPY_SPEC.md#103-張零股) 詳述；成交量 exact欄位與圖形近似界線依 §14。§10、§14與§18～24的原股表／DOM值是各批當時驗收，保留歷史原值；現行主表與原股收合方式依下節。

市場別產業 membership 重建前，個股與行動詳情顯示「既有族群關聯待重新核實」；族群中文名加「（既有分類）」與待核實 badge。不得顯示可信排名或將衍生條件稱為已核實；這不改寫 OHLCV、單位或新聞。相關有限 UI review 只涵蓋文案、空值、法人命名、單位顯示、ETF／族群名稱及官方分點入口，不新增 API、分點資料、歷史 coverage 或主力身分。

### 7.1 UNIT-LOTS-1 日常張數與原股稽核（有限接受）

單日法人主表列張，原 buy／sell／net及合計股字串在來源 details可核對；5／20日主表使用對應 horizon的精確張數，daily evidence details保留每日原股。5／20日數值只在 shares單位／canonical編碼、支持截止與available日曆／窗口一致時顯示；required／valid日期須各恰為該horizon、唯一、升序且逐項相等，起訖／同cutoff及缺／壞日為空均須一致。拒用不補零或採較早／future值；日期、版本、來源及缺日顯示保留，不放寬原准入。價格主表／quote的成交量以張呈現，原股數在價格來源 details保留；庫存與原始籌碼的日常／稽核分工依 UI契約。

Root已對10個既有W8 net獨立換算，桌面 `1277×924` 的單日／窗口／量主值與原股details同值；庫存可信原生輸入／提交見[UI §10.3](UI_COPY_SPEC.md#103-張零股)。`390×844`、client375的單日／窗口／庫存／chip DOM數值及layout已核，page375內的表格由自己的table-wrap捲動，原值details預設收合。Chip頁籤的native切換未觸發event，DOM選擇只支持數值／layout，不能稱全部窄版流程為native通過。初始fill/select輔助與後續具名trusted操作分開。

此為已接受的數量前置，沒有新來源／價格准入、磁碟保存或完整M1驗收；價格、trend及突破／回踩gates不因換算而通過。固定樣本、memory預覽／guard及未跑項見[開發入口](development-baseline/README.md#unit-lots-1-台股張數前置的記憶體驗證入口)，完整原始驗收及程序清理收據留原task。

## 8. 籌碼三部分（後續待做）

個股頁後續把籌碼拆成三個可分辨的區塊；下表是待做功能契約，不代表資料或畫面已實作。

| 區塊 | 預定內容 | 現況與邊界 |
| --- | --- | --- |
| 三大法人 | 沿用現有外資、投信、自營商資料，保留日期、來源、正負方向與缺值。 | 法人資料已存在；「外資」仍是官方外資及陸資合計欄位的日常簡稱。融資資訊繼續獨立顯示，不併入三大法人。 |
| 主力進出 | 由可驗證的券商分點交易統計推導買賣超、買賣分點家數差、5 日與 20 日集中度。 | 尚未計算。實作前須核定交易日與選樣、家數差正負定義、Top N、集中度分母、缺日與版本；「主力」只表示統計指標，不是特定投資人身分。 |
| 券商分點 | 買賣超排行、單一分點歷史與同券商彙總。 | 目前只有依市場導向的官方逐檔人工查詢入口；尚無交易明細匯入、排行、歷史或券商彙總。 |

三區整合、交易明細匯入、主力計算、券商彙總／歷史及自動更新均待後續實作與具名驗收。局部可重現匯入可獨立驗收，但不能因此宣稱已有完整免費歷史、PIT 或每日自動更新；來源邊界見 [DATA_SOURCES](DATA_SOURCES.md#券商分點與主力統計的來源邊界後續待做)。

## 9. M1-P1：截止一致與來源可追溯總覽

M1-P1 新增個股研究總覽、日期套用／最新資料操作，以及獨立 `GET /stocks/{exchange}/{symbol}/overview?as_of=YYYY-MM-DD`。初版總覽版本為 `stock-overview/p1-v1`；後續單日法人接線見[第 10 節](#10-m1-p2b單日法人原件總覽接線)，selected 官方事件見[第 11 節](#11-m1-p3bselected-官方事件總覽接線)。完整 M1 的法人窗口、完整事件 coverage 及成立／未成立研究條件仍未完成。

### 9.1 共用截止與時間

- `as_of` 是含當日的**資料日期篩選**，`cutoff_basis=data_date_inclusive`；明示日期不自動往後推。未指定時優先最新儲存行情日；M3-P6c 對無法定位行情日期的截止處置依 [§15.2](#152-候選窗口截止與未知日期)，不回退較早日期。無行情時仍取其他研究紀錄的最新資料日期，含 active 且時間 verified 的關聯新聞。財報優先公告日，缺公告時的期間日只提供截止基準，不證公告已可得；新聞優先發布、其次事件時間，按臺北轉為日期。無可用日期則為 null，不補今日。
- 同一 response 的行情、技術快照、法人、membership、策略／行動、公司行動、基本面、事件與品質使用同一截止；原資料日、`collected_at`、發布／事件時間保留，不改寫成截止日期。日期篩選不證來源准入、availability、修訂版本或 PIT，`historical_pit=unsupported`。
- 新聞清單在最多 20 筆限制前，依既有已核對的發布／事件時間篩選；datetime 按臺北截止日結束換算，date-only 保留純日期，未知／衝突或超過截止的項目不混入。收集時間不充發布時間。這是既有時間欄位的有限投影，不證事件原件、first availability 或歷史 PIT。
- 日期輸入套用後，URL query 與資料 query 使用同一 `as_of`；「最新資料」移除明示截止並回到 API 的實際資料日期。總覽保留事後研究與歷史可得性未支援的說明。

### 9.2 原件合格的價格視窗

本批只採已准入的 exact `STOCK_DAY_ALL`，來源／用途與 capture gate 依 [SOURCE_REGISTRY](SOURCE_REGISTRY.md#51-stock_day_all-selected-security-bars)，不因 legacy `source=twse`、官方名稱或歷史 P0 結果放行 `MI_INDEX`、TPEx 或其他來源。

先取截止以前最多 120 筆候選行情，再逐筆核對；拒列不另抓更早資料湊滿 120 筆。`candidate_count`、`valid_count`、實際 `from/to`、`latest`、合格 `bars` 與 `rejected[].date/reason` 分開回傳。M3-P6c 最新候選不合格時的 `latest=null`、歷史合格列保留與 nullable rejected 依 [§15.4](#154-m1-總覽版本與最新價格)，其餘研究入口仍可使用。只說本次實際範圍／筆數，不稱完整 N 個交易日；來源本身沒有 TAIEX，不由列數推導交易 session。

每筆合格價須符合：

1. TWSE／symbol／資料日期精確配對，行情經 raw FK 回指指定 `body.bin` 與同目錄 `receipt.json`；原件 hash、capture receipt、成功 HTTP、收集紀錄關聯與 capture time 一致。
2. 使用已 review registry version／digest、exact endpoint／GET 與 source version；`local_fetch`、`raw_store`、`summarize` 用途及必要 conditions 通過，保留顯名、授權與可追溯來源。
3. selected 原件 O／H／L／C、成交量、成交額狀態與保存列一致；OHLC 為正有限數且範圍合法，成交量為非負精確整數。重複日期拒用；缺 selected row、停牌、數值或證據無效保留具體原因。
4. 合格列保留 raw／ingestion identity、body／receipt SHA-256、來源／registry 版本、endpoint、capture／原收集時間；details 可核對每筆價格與來源。這只證**本地原件與保存值一致**，不是來源真偽、完整歷史、revision 或 PIT 的證明。

價格沿用 §2.2 原始 API 口徑與報價幣別限制，不產生 adjusted OHLC。成交額 unavailable 在總覽輸出 null、保留 status／reason；來源合法零仍顯示零，不把保存用的缺值 `0` 當有效來源零。既有 `detail.bars`／K 線仍是按日期篩選的原研究資料，不會因新增總覽而自動升格本批准入來源或完整窗口；頁首新報價取總覽合格 `latest`，不從 legacy 行動價或不合格 bar 補值。

### 9.3 法人、條件與新聞入口

本節保留 P1／P2b 的有限版本範圍；W2 單截止見[§18](#18-m1-w2同截止法人窗口與原件追溯)，現行 W3 兩股／三截止法人窗口見[§19](#19-m1-w3三截止法人窗口與原件追溯)。研究條件未因此啟用。

| 區塊 | 本批結果 | 待補條件 |
| --- | --- | --- |
| 外資／投信／自營商 5／20 日 | P1／P2b 版本固定回傳 `institutional.status=unavailable`、`values=null`；原因依單日區塊是否可用而異，不補零、融資不併入。 | 本批採用的 exact 多日法人來源及用途准入、交易日基準、逐法人欄位／單位／缺日 coverage、窗口計算與 API／UI 接線驗收。 |
| 突破／回踩條件 | `conditions` 中的 `breakout_v1`／`pullback_v1` 固定為 `status=data_insufficient`，即使已有 Signal 亦同；日期、版本與 `reasons` 依讀回記錄改變。 | 必要輸入、來源、時間與適用分類 gate、版本化規則計算及 API／UI 接線驗收均滿足後，才可判「成立／未成立」；Signal 或價位存在不算通過。 |
| 新聞與官方事件入口 | 可切到既有新聞／公告分頁，保留原時間與來源連結；`events.status=unavailable`，顯示原件 consumer 與來源時間待驗。 | 具名事件原件、consumer、發布／事件時間、來源用途與相應 coverage 驗收；入口不是已驗收催化劑，不推論價格影響。 |

M1-P2a 另 explicit TPEx 日法人 capture／selected 摘要 library／CLI 已有限 review，契約與單日兩檔支持範圍見[來源 §8](SOURCE_REGISTRY.md#8-m1-p2atpex-日法人來源與-selected-摘要)。M1-P2a 本身未接總覽 API／UI 或 5／20 交易日窗口；後續 M1-P2b 的獨立單日原件接線見[第 10 節](#10-m1-p2b單日法人原件總覽接線)，上表多日 `institutional` unavailable 契約維持，單日 CLI 數值不作前端 fallback。

上述兩項固定狀態是核心能力尚未接通的保守回應，不能解讀為本次行情或使用者設定暫時缺資料。補入資料或換研究截止不會自動啟用 5／20 日計算或條件判定；仍須先具名驗證來源、交易日與缺日證據，再完成窗口／規則計算、API／UI 接線及產品驗收，解除條件見[執行清單 §2.1](ROADMAP_EXECUTION.md#21-近期里程碑接線映射)。條件原因會反映來源／時間／分類待核實、記錄缺失、無法定位、讀值無效或早於截止；原因變動不代表已能判定成立或未成立。分類是否必要須按所採策略／場景核對，不假定所有場景可省；門檻未滿足仍保持資料不足，不補零或猜結論。已准入且有限接受的 TPEx 單日能力依 §10 保留，不與多日窗口混用。

後續 M1-P3b 已以獨立觀測日期 gate 接 selected 官方事件，具名支持範圍見[第 11 節](#11-m1-p3bselected-官方事件總覽接線)；發布／首次可得時間仍 unknown，完整事件 coverage 與研究條件缺口保留。

既有分類待核實提示與原策略、價位／信心語意保留；本批沒有新評分、機率、完整交易計畫或張數。缺來源只讓相關總覽區塊保持 unavailable／資料不足，不將本批價格交付擴寫成完整 M1。

### 9.4 本批有限驗收與待驗

已有限接受 **TWSE 1101／2330、2026-10-01** 的單日 selected 真原件→loader／select→記憶體 SQLite→實際 API：OHLC／成交量／成交額六欄與原件一致，detail 與獨立總覽相等。9 月 30 日截止排除，10 月 2 日保留但明示價格早於截止。這不證完整 collect、磁碟 DB、全市場、多日或交易 session。

具名操作包括桌面目錄進 2330、總覽／來源 details／新聞入口、日期套用及「最新資料」；窄版單欄與 details 未見 body 橫向溢出。必要來源 gate、Windows 檔案變更拒收、零／缺額／非有限、日期／新聞 limit 前篩選、SQL NULL、跨日／legacy 邊界及前端型別／SSR／production build 已有限接受；大型 JS chunk warning 仍在。

法人窗口、完整事件 coverage、成立／未成立研究條件及完整 M1 未完成，後續依 [ROADMAP](ROADMAP.md)／[接線映射](ROADMAP_EXECUTION.md#21-近期里程碑接線映射)推進。逐輪驗證和版本收據留原 task。

## 10. M1-P2b：單日法人原件總覽接線

**已有限 review，只接受下述具名範圍。** 本批在既有總覽新增獨立 `institutional_daily` 區塊，總覽版本為 `stock-overview/p2b-v1`，單日區塊版本為 `institutional-daily/p2b-v1`；只接明示設定的 TPEx 單日原件，不改成完整 5／20 交易日窗口。來源准入、股數口徑與原件 gate 沿用 [SOURCE_REGISTRY §8](SOURCE_REGISTRY.md#8-m1-p2atpex-日法人來源與-selected-摘要)。

### 10.1 明示設定與共用截止

[`institutional_daily.py`](../backend/app/institutional_daily.py) 從 server 執行環境讀取兩個設定：`STOCK_TPEX_INSTITUTIONAL_CAPTURE_ZIP` 是既有且核定 `capture.zip` 的絕對路徑，`STOCK_TPEX_INSTITUTIONAL_CAPTURE_DATE` 是對應原件的 Gregorian `YYYY-MM-DD` 日期。兩者須同時有效；不搜尋目錄、推算最新日、送網路 request、解壓、改原件、寫 DB／legacy 或快取。使用 M1-P2a 固定 manifest、registry version／digest 與 `free_public_local` profile，不接受 client 指定路徑或以未准入資料補值。

單日區塊使用 §9.1 的共用 `as_of`。原件日期須不晚於截止，不依法人設定改總覽日期；無共用截止時仍 unavailable。未明示 `as_of` 時，設定的法人日期也不作最新資料 cutoff fallback。各失敗結果保留 reason，`row`／`provenance`／`attribution` 為 null，不回傳原件內容或 server 檔案路徑。

| 條件 | 單日區塊結果 |
| --- | --- |
| 非 TPEx／無共用截止 | `daily_exchange_not_supported`／`daily_shared_cutoff_missing`，讀原件前停止。 |
| 兩個設定皆未提供／設定不完整或無效 | `daily_capture_not_configured`／`daily_invalid_configuration`；未配置不讀任何法人原件。 |
| 設定日期晚於截止 | `daily_after_cutoff`，讀原件前停止，不採用未來資料。 |
| 原件日期、selected row、receipt 或固定 pins 不合格 | unavailable，保留可識別的拒收原因；未能安全識別的例外以 `daily_evidence_invalid` 表示，不洩漏 OS 例外。 |
| 原件合格且日期等於／早於截止 | available；早於截止另留 `daily_configured_date_before_cutoff`，不能稱截至日前最新資料。 |

### 10.2 精確股數與可追溯呈現

合格 `row` 保留 symbol／company name、Gregorian `date`、原始民國 `source_date`、1-based `row_ordinal` 與三類 `source_fields`；外資及陸資（不含外資自營商）、投信、自營商的 buy／sell／net，以及 `total_net` 共十個數值均輸出 canonical 整數**字串**，`unit=shares`、`quantity_encoding=canonical_integer_string`。沿用 [SOURCE_REGISTRY §8.2](SOURCE_REGISTRY.md#82-selected-摘要契約與操作) 的整數範圍與加總 gate，合法來源零保留零，缺失或不一致不補零。

此單日原件表以**股**顯示，直接在整數字串加入千分位，不轉 JavaScript `Number` 或換算成張；因此超過安全整數的正負數仍保留全部位數。它是獨立的原件核對表，既有 §7 的法人歷史表顯示換算仍沿用原契約。融資不併入三大法人，不使用單日數值補 5／20 日窗口。

`provenance` 保留 exact endpoint、source／registry version、manifest digest、body／receipt 雙 SHA-256、capture time 與 `local_evidence_consistent` 語意；API 亦保留 attribution、summarize decision 與 condition receipts。畫面提供原件資料日、三類買進／賣出／淨超與合計、來源與授權入口，以及可展開的日期、列序、版本、雙 hash 和 capture time 原值。單日 available 只證選中列與本地原件一致，不證官方 origin authentication、完整市場、最新資料或 PIT。

### 10.3 有限驗收與未支援範圍

已有限接受核定 ZIP 的 **TPEx 3105／6488、2026-10-02**：各十個數值與 actual API 逐欄一致，detail 與獨立總覽相等，日期／雙 hash／pins／列序正確，ZIP 讀前後不變。記憶體 SQLite 不作磁碟或正式 DB 證據；必要後端回歸、型別／SSR、int64／拒收及 App 記憶體 bundle 已驗，**完整 backend／production Vite build 未跑**。

桌面已核 3105、目錄進 6488、來源／授權與 details；10 月 1 日截止排除，10 月 3 日保留但明示未證截至日前最新資料。無其他 dated rows 的 memory fixture 點「最新資料」仍無共用截止，不由法人設定補日。**390×844** details 的雙 hash 可換行，body 無橫向溢出，表格自行捲動。只接受上述兩檔單日及具名操作，不外推全市場／持久化。

5／20 日 institutional values 仍 null；單日可用時原因為 `multi_session_institutional_evidence_missing`、`trading_session_source_not_admitted`，不能把已准入 TPEx 單日來源說成未准入。單日 session_windows 仍 unavailable；未接 TWSE T86、DB／legacy、多日、完整事件／研究條件或 PIT。入口見開發文件；歷史版本、失敗及清理收據留原 task／Git，現有未清資源見[協作紀錄](TASK_COORDINATION.md)。

## 11. M1-P3b：selected 官方事件總覽接線

**程式、原件／API 與下述具名桌面／窄版操作已有限 review。** 本批把 [SOURCE_REGISTRY §9](SOURCE_REGISTRY.md#9-m1-p3atwt48u-selected-官方事件原件摘要) 已有限接受的 TWT48U 記憶體 consumer 接到總覽，總覽版本為 `stock-overview/p3b-v1`，`events` 版本為 `official-events/p3b-v1`。只採原四來源固定 manifest／pins、`free_public_local` profile 與 exact TWT48U GET，不增加來源准入、完整歷史或研究條件。

### 11.1 明示取得與記憶體生命週期

[`official_events.py`](../backend/app/official_events.py) 需 server 明示 `STOCK_TWSE_EVENTS_MEMORY_CAPTURE=1` 才啟用取得操作；普通個股／總覽 GET 與模組 import 不送外網 request。專用 route 為 `POST /api/stocks/{exchange}/{symbol}/official-events/capture?as_of=YYYY-MM-DD`，不需要 body 參數；先確認 instrument 存在，再檢查 TWSE、4–6 碼 ASCII 大寫字母／數字 symbol 與 exact 啟用值。首次 POST 經既有 P3a capture 與 selected consumer 成功後，才發布一份 immutable body／receipt bytes tuple。取得操作不寫 DB、檔案或 ZIP，不使用 client 指定 endpoint、路徑、pins 或其他來源。

成功 cache 後，GET 與 POST 都只重驗同一份 bytes／receipt 並選取標的，不重新抓取、refresh 或背景更新。首個 selected 拒收或取得失敗不發布 cache；取得中另一請求以 `event_capture_in_progress` 拒收。重啟後才可能取得新原件；cache 消失不能稱已保存、可重開讀回或可離線重播。來源失敗、不合格 receipt／selected 或缺列回 unavailable，不以 legacy Event／NewsItem、網頁搜尋或未驗數值補值；selected 缺列亦不代表已驗證「無事件」。

### 11.2 共用截止與未來生效預告

總覽沿用 §9.1 的共用 `as_of`。本次 capture time 轉為臺北的 `observed_date`，只有 `observed_date <= as_of`（含當日）才可呈現該原件的 selected 事件；缺共用截止或截止早於觀測日仍 unavailable。觀測日期可提供未通過原因與操作提示，但不能自動取代共用截止或作「最新資料」日期 fallback。

官方 `Date` 仍是 `effective_date`，不是發布／首次可得時間；合格原件中的未來生效預告保留，不按 `event_date <= as_of` 刪掉。`published_at`、`first_available_at`、`revision_available_at` 仍 null／unknown，`historical_pit=unsupported`。本批只做本次觀測日期的事後研究篩選，不證精確時刻的 availability、歷史當時可得、完整 session 或 revision lineage。

### 11.3 可追溯呈現與拒收

合格 `rows` 只投影 exchange／symbol／company name、生效日期與原民國日期、原 `Exdividend` 分類字串、effective-date 角色／date 精度、分類／label、1-based 列序，以及三個 null 時間與 unknown availability。未驗金融欄位仍在 process 原 bytes，API 不公開完整 `source_row`，也不顯示其數值。`provenance` 保存 source／registry version、固定 pins、body／receipt 雙 hash、capture／request time、storage 與 `local_evidence_consistent`；API 另留 attribution、用途 decision 與 condition receipts。

畫面呈現證券身分、除息／除權／除權息、生效日期、觀測日期、未來生效預告與未驗發布／首次可得時間，並可展開原日期／分類、列序、版本、雙 hash 與 capture time。TWSE 原 manifest 的顯名取 `owner.name=Taiwan Stock Exchange (TWSE)`，授權取 `terms.value=OGL 1.0` 並連到 `https://data.gov.tw/license`；不用 TPEx 的 `data_provider`／year 欄位。型別、SSR 與實際授權顯名／href 已具名核對。

`source_url_kind=feed` 的連結使用「官方公告資料集」，說明未必定位本則，不能寫成「查看原文」。除權息分類不形成正負催化、價格影響、調整因子或成立／未成立條件；同一原件的選列驗證不代表全市場或完整歷史 coverage。非 TWSE、未明示啟用、尚無 cache、來源／selected 拒收、缺截止與截止早於觀測日等情境須可辨識，不補零或假事件。

| 條件 | `events` 結果 |
| --- | --- |
| 未提供／空啟用值、啟用值不是 exact `1` | `event_capture_not_enabled`／`event_capture_configuration_invalid`；不外網取得、不曝露 cache。 |
| 非 TWSE、invalid symbol | `event_exchange_not_supported`／`event_invalid_symbol`，不曝露 cache。 |
| 尚無成功 cache | 普通 GET 回 `event_memory_capture_missing`。 |
| 缺共用截止、截止早於臺北觀測日 | `event_shared_cutoff_missing`／`event_observation_after_cutoff`；可回 `observed_date` 提示，`rows=[]`、`provenance=null`，不補日期。 |
| selected 缺列、重複／分類／receipt 無效或 HTTP 失敗 | unavailable，保留安全 consumer reason 或 `http_status:503` 等狀態；未能安全識別的例外以 `event_evidence_invalid`／`event_capture_failed` 表示，不洩漏 OS 路徑。 |
| 合格 selected 且觀測日不晚於截止 | available，保留全部合格 selected 事件，包括晚於截止的未來生效預告；不是截至日前最新 feed 或歷史 PIT。 |

### 11.4 有限驗收與未支援範圍

已有限接受 **2026-10-03（臺北）** 真畫面首次取得→POST→actual capture／consumer／API：普通 GET 零外網取得，首次按鈕後單一 GET、HTTP 200，原件 58 列。下列 selected 原值／列序與 API 一致，未來生效預告保留：

| Code／Name | 原 Date → 生效日期 | 原分類／顯示 | 原件列序 |
| --- | --- | --- | --- |
| `0056`／元大高股息（ETF） | `1151022` → 2026-10-22 | `息`／除息 | 5 |
| `1449`／佳和 | `1151012` → 2026-10-12 | `權`／除權 | 49 |
| `1463`／強盛新 | `1151015` → 2026-10-15 | `息`／除息 | 50 |

三個標的 detail／獨立總覽相等；10 月 2 日截止拒收、rows=[]／provenance=null，缺截止不補觀測日。再 POST 1449 重用同 cache，取得次數仍 1，原件／receipt 雙 hash 不變。Memory catalogue 只提供路由 metadata，不作真行情／DB 證據。

桌面 **1365×900** 核 0056 首次取得、ETF 名稱／生效日、details 原日期／分類／列序／雙 hash、TWSE 顯名／OGL1.0／license href；截止排除、無 dated rows 的「最新資料」保持 as_of=null，套回 10 月 3 日恢復同原件。目錄進 1449／1463 的名稱／日期已核。**390×844** 1463 details 無 body 橫向溢出，事件表自行捲動。

必要後端記憶體回歸、前端型別／價格／法人／事件 SSR 與 App 記憶體 bundle 已有限接受；完整 backend／production Vite build 未跑。Live body／receipt 未保存，**不能離線重播**；失敗、複驗、exit、hash 與清理收據留 task，既有殘留依[協作紀錄](TASK_COORDINATION.md)。

完整 M1 仍缺可驗 5／20 日窗口及成立／未成立條件；不接 DB／legacy、事件群組／更正／撤回史、排程或交易，不放寬來源／PIT gate。

## 12. M2-P1：官方事件關注清單接個股總覽

**程式、真原件／API 與下述具名桌面／窄版操作已 review（有限）。** 本批在今日頁新增官方事件關注清單，版本 `official-event-focus/p1-v1`；只採既有 exact TWT48U 記憶體來源與固定 pins，不把事件分類變成交易訊號、價格影響或可信排名。來源 consumer 契約見[來源 §11](SOURCE_REGISTRY.md#11-m2-p1本次官方事件-feed-摘要)，M1 的 5／20 日與研究條件等待狀態保留。

### 12.1 明示截止、取得與同一份原件

`GET /api/focus/official-events?as_of=YYYY-MM-DD` 必須明示有效日期，缺少或 invalid query 回 HTTP 422，普通 GET 與 import 不送外網 request。`POST /api/focus/official-events/capture?as_of=YYYY-MM-DD` 才是首次取得操作，不需 body 參數；沿用 server exact `STOCK_TWSE_EVENTS_MEMORY_CAPTURE=1` 與 §11.1 的固定來源、用途及記憶體限制，不需 client 指定 endpoint、pins 或檔案路徑。今日頁未帶 query 時，日期控制預填當下臺北日期並明示送給 API；這不更動 M1「最新資料」的 cutoff fallback。

關注清單與 P3b 個股事件共用同一 process 的 cache／鎖；首次合格 capture 成功後只再用同一份 immutable body／receipt，不 refresh 或背景更新。合法空 feed 可發布成功 cache，之後 selected consumer 仍須拒收缺 selected，不能把零筆關注結果改成已證個股無事件。取得中、HTTP／receipt／feed 不合格、未明示啟用或沒有 cache 與合法零筆須分開；失敗不發布新 cache。重啟後記憶體消失，不能稱持久化或可離線重播。

本次 capture 的臺北 `observed_date` 須不晚於明示 `as_of`，才可呈現清單；較早截止不回事件，也不由觀測日補日期。官方生效日期仍可晚於截止，保留為未來生效預告。觀測日／UTC capture time 與生效日分開；發布／首次可得／修訂時間仍 null／unknown，`historical_pit=unsupported`。`as_of` 只限制這次觀測的事後研究範圍，不證當時已可得、截至日前最新 feed 或完整交易日。

| 情境 | 關注清單結果 |
| --- | --- |
| 無成功 cache 的普通 GET | `event_memory_capture_missing`；只在截止不早於當下臺北日期時允許首次取得。 |
| 無 cache 且 POST 截止早於當下臺北日期 | `event_cutoff_before_current_observation`，零外網取得。 |
| cache 觀測日晚於截止 | `event_observation_after_cutoff`，`items=[]`／`provenance=null`；同原件仍保留，不取得新版本。 |
| 未啟用、設定錯誤或取得中 | `event_capture_not_enabled`、`event_capture_configuration_invalid` 或 `event_capture_in_progress`；不公開事件內容。 |
| feed／receipt 拒收或 HTTP 失敗 | unavailable，保留安全 consumer reason 或 `http_status:503`；不發布成功 cache。 |
| 合格 feed，觀測日不晚於截止 | available，含合法零筆；再次讀取或 POST 為 `capture_action=cached`，不 refresh。 |

所有 focus 回應均無頂層 `rows`；非 available 結果的 `items=[]`，不以原件內容作 fallback。回應的 `coverage=observed_feed_only`、`research_conditions=unknown` 明列範圍。

### 12.2 同股去重與可追溯理由

全 feed 合格後，以 TWSE＋來源代碼組成一張關注卡，同股所有事件放在 `items[].events`，保留原件列序及各自生效日期／除權息分類。關注理由只陳述「本次官方資料集觀測到的除權息事件」，不加正負催化、分數、勝率、價位或策略成立判斷。`order=symbol_lexicographic` 是固定代碼字串順序，不表示推薦次序；`limit=100`，`total` 是本次不同標的數、`displayed` 是實際顯示標的數，`truncated` 表示是否超過上限，不讓截斷偽裝成完整清單。`candidate_count`／`selected_count` 是已驗的 feed 事件列數，不能當標的數或交易股數。

來源代碼／公司名與事件先保留，`company_name` 不由 catalogue 名稱覆寫。Catalogue 的 TWSE＋代碼已知時，`stock_page_available=true`，`detail_url` 提供帶同一 `as_of` 的 M1 個股總覽入口；未知時為 false／null，保留來源名稱與事件，顯示尚無個股目錄對應，不猜 instrument 或建立連結。已知標的連結不放行 M1 缺少的價格、法人窗口或研究條件，也不把 ETF 稱普通股票。

清單呈現「本次觀測」、觀測日、生效日及未來預告；原日期／分類與列序收在「事件原件值」。來源 details 提供來源／授權入口、來源與 registry version、固定 pins、雙 hash 與格式化觀測時間；API 保留 capture／request UTC 原值及用途／條件 receipts。`source_url_kind=feed` 的入口定位官方資料集，畫面來源「臺灣證券交易所原始資料」不稱本則單篇原文；未驗金融數值不公開。合法空 JSON array 只表示**這次合格 feed 零筆**，不代表全市場沒有事件；來源不足、invalid 或 cutoff 拒用仍 unavailable，不補候選。

### 12.3 驗收與尚缺項

已有限接受 **2026-10-03（臺北）** 首頁首次取得→focus POST→exact memory capture／consumer／API：單一 GET、HTTP 200，**58 列／58 股**，total=displayed=58、truncated=false。Code／Name／Date／Exdividend 與 1-based 列序逐列對 actual API 一致；未驗金融欄位未公開。同股多事件／100 股上限另由 fixture 核對，不冒充當次 live。

同原件供 M1 **0056（ETF）／1449／1463**，detail／獨立總覽與清單同 as_of、selected／雙 hash 一致，原日期／分類／列序與 §11.4 表相同；10 月 2 日排除，未來生效預告保留。Memory catalogue 只提供這三個路由，其餘 **55 股**無連結，不作正式 catalogue／行情／DB coverage。

桌面核首次 58 卡、10 月 2 日排除、10 月 3 日恢復同 cache、來源／授權、0056 原件 details 及同 cutoff 進 M1。新聞區原矛盾空文案退修後同 cache 複驗通過。**390×844** 核日期控制／讀 cache／hash 換行、1463 進 M1 保留 cutoff，document 寬 **375**，表格自行捲動；截止／往返後取得次數仍 1。

必要記憶體 consumer／API、非 available 無頂層 rows、型別／SSR／App bundle 已有限接受；空 feed、多事件、截斷、未知 catalogue、receipt／pins／分類拒收與鎖只證 fixture 邊界。**完整 backend／production Vite build 未跑**；原件未保存，**不能離線重播**。歷史操作失敗、複驗與清理收據留原 task／Git；現有未清資源見[協作紀錄](TASK_COORDINATION.md)。

本批只交事件關注入口，不增加准入、DB／legacy、跨源群組／更正／撤回、可信排名、研究條件、完整 M1／M2、排程、交易或 PIT。

## 13. M2-P2：官方事件清單搜尋與研究往返

**程式、必要回歸、真原件／API 與下述具名桌面／窄版操作已有限接受。** 版本為 `official-event-focus/p2-v1`，沿用 §12 的來源、完整 feed 驗證、明示取得、截止與 cache。搜尋完整合格原件，M1 返回保留原清單條件；來源 pins、unknown availability、PIT 與完整 M1／M2 gate 維持。

### 13.1 先驗全原件，再搜尋與限制顯示數

`GET /api/focus/official-events?as_of=YYYY-MM-DD&q=...` 與明示首次 `POST /api/focus/official-events/capture?as_of=YYYY-MM-DD&q=...` 的 `q` 為 optional，預設空字串；有效 `as_of` 仍必填。`q` 的原始長度最多 **100 個 Unicode 字元**，先驗長度再 `strip` 去除前後空白；包括 101 個空白的超長 query 皆回 HTTP 422，不取得來源。純函式另對非字串／超長值回 unavailable、`event_search_query_invalid`、`can_capture=false`，不抓外網。

合法 query 在 `search_query` 保留去除前後空白後的原大小寫，以 `casefold` 作不分大小寫的 **literal substring（連續文字）** 比對；不作 regex、模糊搜尋或推薦。完整 body 身分／日期／分類、receipt／pins／hash 與截止 gate 先通過，才按來源代碼去重、搜尋、固定代碼排序及套 100 股上限。任一原件列不合格即整份 unavailable，即使該列不符合搜尋或在顯示上限以外也不得略過。

搜尋只比對來源 `Code` 或該股任一事件的來源 `Name`，不使用 catalogue 名稱。某股任一名稱或代碼符合時，該卡保留該股全部合格事件及各自原件列序，不只留下符合名稱的事件。Catalogue 仍只決定是否有既有 M1 入口，不覆寫來源名稱或擴張搜尋範圍。

| 回應欄位 | 意義 |
| --- | --- |
| `candidate_count`／`selected_count` | 已驗全 feed 的原件事件列數；搜尋不改成符合標的數。 |
| `total` | 搜尋前原件去重標的數。 |
| `matched` | 完整合格 feed 中符合搜尋的標的數。 |
| `displayed` | 實際顯示標的數，等於 `min(matched, 100)`。 |
| `truncated` | `matched > 100`；依符合結果計算，不因原清單超過 100 股而誤報搜尋截斷。 |
| `search_query` | 已去除前後空白的 query；空字串表示查看全原件標的。 |

空原件為 available、`total=matched=displayed=0`，只證本次合格原件零列；非空原件無符合為 available、`total>0`／`matched=displayed=0`，可清除搜尋回全清單；來源或截止不可用為 unavailable，不顯示結果統計或舊卡片。三者文案分開，皆不推論全市場沒有事件。unavailable 的 `items=[]`，無頂層 `rows`，初始 `total`／`matched`／`displayed` 為 0；這些零值不是已驗原件為空的證據。

### 13.2 提交搜尋與固定研究返回路徑

今日頁搜尋僅 Enter／「搜尋」提交，輸入中的 draft 不更新 query 或呼叫 API；「清除搜尋」保留當前 `as_of` 並回本次全清單。超長 draft 顯示錯誤，不提交。查詢 key 同時包含 `as_of`／`q`，不以舊結果作新條件的 placeholder；首次 POST 結果及錯誤保留其請求 key，不能套到已切換的條件。搜尋、截止、返回與讀 cache 均不 refresh 來源。

已知 catalogue 的 `detail_url` 固定為 `/stocks/TWSE/{symbol}`，query 帶相同 `as_of`、`from=official-events`、去除前後空白的 `focus_q` 與原清單 `focus_as_of`。只有固定 `from` 值、有效原截止（含拒絕 0000 年）及不超過 100 個 Unicode 字元的原 query 才提供「返回官方事件關注」，返回固定 `/?as_of=原focus_as_of&q=原focus_q#official-event-focus-title`，參數經 URL 編碼；不接受自由 return URL。M1 內修改個股截止仍保留原清單條件，返回時恢復原搜尋／截止。前端去除空白與 Python `strip` 使用相同集合，包括 NEL／U+001C–001F，保留 FEFF，避免同 query 的字元語意分歧。參數不合格時回既有個股入口，不猜原清單；未知 catalogue 仍保留事件但無個股連結。

### 13.3 本次有限驗收與尚缺項

已有限接受 **2026-10-03（臺北）** 單次 exact TWT48U memory capture 的 **58 列／58 股**；四個原欄與列序逐列對 actual API 一致。query 支持範圍：

| query | 真原件符合 |
| --- | --- |
| 元大 | 0056／00940，2 股 |
| 前後空白的 0056 | 0056，1 股 |
| 14 | 00714／1449／1463／2614，4 股 |
| 00400a | 00400A，1 股 |
| 不存在%&?# | 0 股 |

各查詢同 provenance／雙 hash，不發新來源 request。0056（ETF）／1449／1463 的 M1 同 cutoff 事件全等，其餘 55 股無 fixture catalogue 連結；catalogue 不作正式市場／行情／DB 證據。

桌面 **1365×900** 核名稱搜尋／trim、0056 進 M1 改至 10 月 2 日排除、返回仍恢復 **10 月 3 日／元大 2 股**，無符合／截止不可用／新條件不混舊卡。**390×844** 核 1463 搜尋→M1→同條件返回、清除回 58 股、0056 來源／授權／同 hash；document 寬 **375**，表格自行捲動。

必要後端記憶體回歸、型別／SSR／App 記憶體 bundle 及 Unicode 空白／0000 年補驗已有限接受。空原件、101 股以上搜尋後截斷、匹配外壞列、同股多名稱／完整事件及 query 邊界只證 fixture。**完整 backend／production Vite build 未跑**，Live 原件未保存、**不能離線重播**。原失敗與成功收據留 task，清理／舊 Temp 限制依[協作紀錄](TASK_COORDINATION.md)；不新增排名、金融推論、研究條件、持久化或完整 M1／M2。

## 14. M1／R1-A2：成交量 HTTP→JavaScript→個股精確呈現

**程式、必要記憶體驗證、完整字串邊界複驗與下述 TWSE／TPEx 具名操作已由統籌有限接受。** 本批支援 M1 研究資料可信／R1-A2，處理 HTTP 整數 token 經 JavaScript `Number` 後可能失去位數的呈現缺口；有限接受不代表真官方／live、完整產品或 production 驗收。

### 14.1 API 增欄與舊回應相容

個股行情及可用總覽的成交量新增 `volume_exact: string | null`，既有數字 `volume` 保留。精確欄位表示股數，須為 ASCII 十進位 canonical 非負整數字串：只有 `0` 或非零數字開頭的連續數字，範圍為 **0–9223372036854775807**（含上限）。不接受前導零、正負號、小數、科學記號、千分位或空白；無法提供合法精確值時為 null，不補成零。後端只新增純 helper 與本批 API 投影，不變更 portfolio、parser、selected consumer 或來源 gate。

前端先驗精確欄位，不以已失真的數字覆蓋它：

| 回應情況 | 成交量呈現 |
| --- | --- |
| `volume_exact` 是範圍內的 canonical 字串 | 使用字串保留全部位數。 |
| 舊回應沒有該欄位，讀得 `undefined` | 僅當 `volume` 是 `Number.isSafeInteger` 的非負數時，才轉成整數字串回退。 |
| 精確欄位為 null、非字串、格式不合法或超過 int64 上限 | 不回退到 `volume`；顯示不可用／空白及既有缺值說明。 |
| 舊回應數字不是非負安全整數 | 不補零，不聲稱精確值可用。 |

### 14.2 股、張與圖形的精度

股數直接在整數字串加入千分位。來源明確為股數時，張數以字串切分末三位換算，必要時補足小數前的零；不先轉 `Number`、除法或四捨五入，不遺失零股。合法零顯示 `0`，缺值與零分開；來源單位 unknown／mixed 的原限制保留。

| 精確股數 | 股數文字 | 張數文字 |
| --- | --- | --- |
| `0` | `0` | `0` |
| `1` | `1` | `0.001` |
| `9007199254740993` | `9,007,199,254,740,993` | `9,007,199,254,740.993` |
| `9223372036854775807` | `9,223,372,036,854,775,807` | `9,223,372,036,854,775.807` |

有可用成交量時，App 頂部、日行情表、總覽張數 quote 與股數表格、圖表 tooltip 及等效資料表均接相同精確值。圖形高度仍使用數字近似並須明示；核對值以 tooltip 與資料表的精確文字為準。這不改 OHLC、MA、時間／來源、策略計算或原始證據，不放寬下述 TPEx 總覽缺口。

### 14.3 准入與本輪有限接受範圍

TWSE 總覽仍須通過 §9 的 selected 原件證據 gate；不能因增添精確欄位而接受不合格價格。TPEx detail 可用時接本欄位，總覽維持現有 unavailable，不為本批放寬來源。單日法人精確股數、完整 5／20 日窗口、研究條件、M1-P4a unknown 權利、完整 M1／M2／M3 與 PIT 的原限制保留。

固定 synthetic fixture 日期為 **2026-10-01**，TWSE／TPEx 各使用下列八個合成標的，名稱明示記憶體合成測試；不是官方標的或真實行情：

| 合成標的 | 精確股數 |
| --- | --- |
| `ZERO0` | `0` |
| `ONE1` | `1` |
| `N999` | `999` |
| `LOT1` | `1000` |
| `LOT01` | `1001` |
| `SAFE` | `9007199254740991` |
| `ODD` | `9007199254740993` |
| `MAX` | `9223372036854775807` |

已有限接受專用後端 actual HTTP、前端型別／units／chart／overview／事件 SSR、全 App 記憶體 bundle，以及 loopback production fetch／Response.json。雙 formatter 的尾端 ASCII／Unicode 空白拒用另有必要補驗。這些只支持表列 synthetic／相容邊界，runner 原失敗與修正後成功留 task，不稱首跑全部通過。

Synthetic 證據不稱官方真實樣本或 live；記憶體原件 fixture 僅 patch `_capture_evidence`，承接既有 selected gate，不重驗或代替新的磁碟驗收，不新增來源准入、正式 DB 或磁碟保存驗收。記憶體全 App bundle 不作 production Vite build 驗收；本輪零落盤入口與隔離限制見[開發入口](development-baseline/README.md#m1r1-a2-成交量精確呈現的零落盤驗證入口)，實際版本、命令、exit、失敗／修正及清理收據留 task。

### 14.4 統籌具名操作與未驗邊界

TWSE 桌面 `MAX` 的 headline 與總覽 quote 均為 **9,223,372,036,854,775.807 張**，總覽股數表為 **9,223,372,036,854,775,807 股**；chart 資料表、實際滑鼠 hover tooltip 與「資料說明」的日行情表保留同一精確值。`ODD` 的兩個張數 quote、股數及 chart 資料表保持全部位數；`ZERO0` 的上述成交量文字均為合法零。

**390×844** 窄版完整 headline／總覽數字可讀，資料表自行捲動，document scroll width 為 **375**。截止以 DOM value setter／input／change 加實際「套用截止」按鈕驗：2026-09-30 排除價格／成交量，「最新」恢復 MAX；這不作 native calendar 驗收。

TPEx `MAX`／`ODD`／`ZERO0` 的 chart 資料表分別保持 **9,223,372,036,854,775.807／9,007,199,254,740.993／0 張**，`MAX` 的「資料說明」日行情表同樣精確；headline／總覽仍為未提供，來源 gate 為 0 passed，不冒稱兩市場總覽能力。「資料說明」以 DOM `button.click()` 觸發正式 handler 後，核實選中頁籤、展開及表格值；先前 native click 沒有切換，不當作通過。

上述操作使用 memory-only 全 App esbuild preview／fallback font，外網觀測為 0。兩 serve 的 exit **1** 與 direct test／Node check exit 0 分報，Python serve 沒有最後完整 audit receipt；歷史清理收據留原 task／Git，現有未清資源見[協作紀錄](TASK_COORDINATION.md)。完整 backend、production build／startup、正式 DB、真官方／live、完整 5／20 日與 PIT 未驗。

## 15. M3-P6c：個股詳情行情讀回污染隔離

本批支援 M3／R2-C2；必要記憶體／actual API／App 與下述具名操作已有限接受。精確讀回契約由本節負責，文案見[UI](UI_COPY_SPEC.md#102-個股詳情的第一屏)，入口見[開發文件](development-baseline/README.md#m3-p6c-個股詳情行情讀回的零落盤驗證入口)。P6b 的污染詳情未因本批追認；不新增來源、即時價格、Plan 或交易能力。

### 15.1 原始投影、nullable 值與讀值狀態

Stock detail／instrument detail 與 M1 候選行情以未定型 SQL 讀十七欄：`id`、`instrument_id`、`trading_date`、`open`、`high`、`low`、`close`、`adj_close`、`volume`、`turnover`、`turnover_status`、`turnover_reason`、`source`、`data_as_of`、`collected_at`、`raw_payload_id`、`is_suspended`；不載入完整 MarketBar 的 Date／DateTime／Float processor，也不修改 shared `bar_dict`、decision read 或 portfolio quote。

公開 `bars` 保留候選 `id`，`date` 及必要數值／metadata 無法安全投影時為 null，不補 0、不 cast 救回 TEXT／BLOB 或修原列。逐欄原值為 SQL NULL 時記 missing，非 NULL 但未通過讀值規則時記 invalid；OHLC 幾何不成立另記 `ohlc=invalid`。這是 SQLite affinity 已處理的讀值，不恢復保存前的 token 或原始意圖。

| 分類 | 讀值規則與影響 |
| --- | --- |
| 核心 | 日期為合法完整 `YYYY-MM-DD`；OHLC 為 actual int／float、排除 bool、正有限且 low／high 範圍成立；volume 為 actual int、0–9223372036854775807；source 沿既有可編碼、非空與控制字元限制；停牌旗標只收 actual int 0／1。合法 volume 0 保留，精確文字依 §14。 |
| 可選 metadata | `adj_close`、turnover／status／reason、`data_as_of`、`collected_at`、raw FK 逐欄列於 `metadata_fields`；壞 metadata 投影 null，不單憑該欄使可畫的核心 OHLC 無效。turnover 只收非負有限數，status 只收 available／unavailable／unknown；raw FK 只收正 actual int。這些讀值仍不等於 M1 原件或來源證據。 |
| `market_read` | 列與頂層提供 known／missing／invalid、`invalid_fields`、`missing_fields`、`metadata_fields`；核心 invalid 優先，其次 missing，均無者才 known。known 只證語法，`verification=stored_value_syntax_only`，不證用途、官方日期、availability、tick 或 PIT。 |

頂層另提供 `candidate_count`、`window_limit=120`、`unlocated_count` 與第一個 `unlocated_market_bar_id`。無候選列為 missing、`missing_fields=["market_bar"]`；任何無法定位日期使頂層 invalid，即使該列不在回傳的 120 個位置內。完整條件與原始日期不可由 status 單獨推定。

### 15.2 候選窗口、截止與未知日期

原儲存 `trading_date DESC`、`id DESC` 決定候選位置；合法 future date 依明示／共用截止排除，最多 120 個位置**先限定再驗值**。拒列保留其位置，不先 filter 合格列、較早 fallback 或另取較早資料補滿；detail 回傳這個候選窗口的反向次序，非法日期不冒充已知的時間順序。

無法定位日期的檢查涵蓋該標的全部儲存行情，不受 cutoff／120 列窗口限制；非法字串不能當 lexical future 略過。未明示 `as_of` 時，有任一無法定位日期即使其他行情日期合法，共用 cutoff 仍為 null，不改用較早日或今日。明示合法 `as_of` 保留原值，可用研究區塊沿該日期篩選，但未知行情日仍阻止頁首報價與 M1 latest。完全沒有行情時，§9.1 的其他研究日期 fallback 維持。

### 15.3 圖表缺口、有限均線與頁首

圖表只畫核心讀值合格、日期合法且唯一的 bar；已知日期的拒列／重複列保留空位置。coverage 的已知缺日可加入 gap，但不建立 K 棒或收盤值；均線不跨 gap，之後須重新累積完整 20／60 個合格 close。日期無法定位時，包含窗口外的 unknown，整個視窗 MA20／MA60 均為 null；同一來源與價格基準限制保留。即使每個 close 有限，平均的中間加總或結果非有限也投影 null，不輸出 Infinity／NaN。

StockPage 核對頂層 status、各狀態陣列／metadata、120 窗口與候選數、unknown 數及 verification；known 必須至少一個候選、核心無缺項／invalid、七個 metadata key 完整。合法 missing 且 candidate_count=0 可保留空 metadata，不誤標 invalid。只有一致的 known 和合格候選可進價格呈現；invalid／missing、不支援或 malformed 新契約、狀態矛盾、候選值矛盾及非有限價格拒用。完全 undefined 的舊 API 才沿原有限數值相容，不用 malformed 新回應 fallback legacy 值。

stored syntax known 但 M1 `overview.price.status=unavailable` 只表示未准入／缺原件證據，頁首價格／漲跌待核實，不能因此顯示「行情讀值無效」。真 invalid／missing、partial 或 conflicting 回應才用新增讀值缺口提示；其餘獨立可用研究區塊保留。正常 M1 unavailable 與 missing 0／空 metadata 的兩項退修，經受影響 actual HTTP／完整 App SSR 及具名畫面後才有限接受，原失敗另報。

### 15.4 M1 總覽版本與最新價格

新總覽 presentation version 為 `stock-overview/p6c-v1`，反映 nullable rejected、讀值狀態與 no-fallback 語義；registry／source／purpose／version／digest pins 未改。§9.2 的 selected 原件、raw FK／body／receipt、hash、來源、用途及時間 gate 保留，`_stable_read`／`_capture_evidence` 未修改；未驗必要原件／磁碟條件不以記憶體替代。

`price.latest` 只在**最新候選本身**通過完整 M1 核對、且該標的無無法定位日期時成立。最新候選未准入／證據或數值不合格時，不改用較早合格價格；`price.status=unavailable`、latest=null，可保留較早真正合格的歷史 `bars`、`valid_count` 與 from／to。`rejected` 保留候選 id、nullable date 與具體 reason；unknown 日期及最新候選未合格分別列出原因。M1 可用價格與 detail 語法 known 仍是不同驗收層。

### 15.5 具名有限接受與未包含

本次 served fixture 為 **2026-10-04 synthetic TWSE 十二個標的／十二庫存／784 行情**；不是官方行情／日曆或 M1 原件。原 Node／Python 邊界、actual getStock／Response.json／完整 App 詳情讀回與以下具名操作已有限接受。數量、原始失敗、退修與程序限制由開發入口／task 分報，不把 SSR 當真正操作。

| 具名操作 | 已接受的有限結果及界線 |
| --- | --- |
| 桌面 `1298×924` 原 B-CLOSE action Link | 真正進入 `/actions/TWSE/B-CLOSE`，actual getStock 為 200；行情讀值無效與頁首待核實可辨識。native 研究分頁真正 selected，研究條件 data_insufficient、20 of 60 的條件範圍可讀；document client／scroll width 均 1283。 |
| D-METADATA／I-MISSING | D 核心 known、60／60 歷史讀回，M1 仍拒 fixture且不顯 invalid gap；I 明示「尚無行情記錄。」。這不將 D metadata 或 source syntax 升格准入來源。 |
| C-DATE 預設無截止，`390×844`／mobile=false | 先 goto 再設 viewport；default cutoff=null、日期 input 空、invalid／一個 unlocated 候選、eligible=0。document 寬均 375；只接受這個無有效歷史的窄版 DOM，不稱有效歷史窄版或表單提交已驗。 |
| C-DATE 明示截止的 direct URL | `as_of` GET 為 200，但 390px 的 client 375／scroll 1228，橫向溢出 assertion exit 1。resize／ResizeObserver／requestAnimationFrame probes 未形成原因證據；visible／hasFocus 為 true，canvas 0、圖表 instance inner 1193／outer 305px。原因未證，不接受窄版歷史 layout 或實際 canvas 畫圖。 |
| L-WINDOW／K-FUTURE 桌面 | L 回傳 eligible 120／120，窗口外 unlocated 日期仍阻止 MA；K 保留 10 月 4 日、排除 10 月 5 日。兩者 document 寬均 1283、API 200；候選／歷史範圍與原 M1 gates 保留，不外推完整交易日或來源驗收。 |

原 native date fill／ref click／Enter 曾多次 ack，但沒有對應 URL／API／DOM 事件，不算截止表單成功。隱藏表格 `innerText` 空白不能證明 MA 全空或第一個日期；只接受 `textContent` 日期、Node 算術邊界及 UI 的 MA reason。既有 renderer 與截止 form 本輪未改，physical canvas、有效歷史窄版 layout 及真正截止表單提交保持未驗；early runtime／timeout／ref、viewport 時機與 StopIteration 原失敗不倒改通過。

同一 fixture 的讀回前後及 UI 後，十二持倉／784 行情的全部欄位／typeof／note／updated_at 同 digest，read mutation 0。Console 只作 limit 50 查閱，仍有 DevTools info／Router warnings；短暫 compiler 未即時觀測並發。歷史程序／清理結果留原 task／Git，現有未清資源見[協作紀錄](TASK_COORDINATION.md)。

本批不證官方／live、正向 M1 filesystem gate、正式 DB／磁碟重開、Decimal exact、availability／PIT、完整 backend／production Vite build、完整 ActionsPage、M1／M3 或交易計畫。無合格來源仍拒用，不以 partial／unknown 文案降低原件／磁碟完成條件；其他研究候選讀回仍待有界審查，下一步及必要依賴由 [ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)負責。

## 16. M3-P6d：個股詳情研究候選讀回污染隔離

本批支援 M3／R2-C2；stock／instrument detail 的 Signal／StrategyVersion raw 讀回、必要 decision／overview caller、actual API／App 與下述具名操作已有限接受，候選 read.status 的 builtin-string guard 補驗亦接受。精確契約由本節負責，文案見[UI](UI_COPY_SPEC.md#102-個股詳情的第一屏)，入口見[開發文件](development-baseline/README.md#m3-p6d-個股研究候選讀回的零落盤驗證入口)；版本收據留 Git／原 task，不倒改 P6c 的原驗收。

### 16.1 只在個股路徑啟用的原始投影

stock／instrument detail 以 raw SQL 左連接 Signal 與 StrategyVersion，避開完整 Date／DateTime／Float／JSON processor；decision 的 `stock_research_reads=True` 只由個股 caller opt-in，cache 區分該模式。overview 的條件及無行情 Signal 日期 fallback 使用同一 raw reader；舊 Actions／tracking 等預設 typed Signal 路徑沒有擴成此模式，也不修改 models、原列、writer 或 shared 行情契約。

候選保留原 `id`、`instrument_id`、`strategy_version_id`、日期與原 status；不能安全投影的欄位為 null，逐欄 `metadata_fields` 分 known／missing／invalid。SQL NULL 在投影層保留 missing，非 NULL 壞值列 invalid，不補 0、空 evidence 或較早列。這是讀回語法分類，不還原 SQLite affinity 前的 token，也不證來源、用途、可得時間、tick、PIT 或研究條件成立。

| 分類 | 讀值與影響 |
| --- | --- |
| 必要身份 | id／instrument FK／version FK 為 actual 正 int64；signal key／status／data quality／strategy name／version 為有界、可編碼的非空字串；signal_date 為合法完整日期。核心欄位 missing／invalid 保留狀態，不構造身份。前端另核 safe integer，不能安全辨識的回應拒用。 |
| 被策略消費的值 | breakout 使用突破／失效／目標價；pullback 使用參考進場／回踩區／失效／目標價。提供的價格須 actual int／float、排 bool、正且有限；evidence／data_cutoff／earliest_execution_date 的 present invalid 也使該候選 invalid。缺少可 nullable 的價位／時間／evidence 不新增必填 gate，仍由原策略語意判斷。 |
| 可選 metadata | confidence、rationale、source_report、entry_type、execution 欄位、created_at，以及 strategy kind／config／snapshot／active／created_at 逐欄保留狀態；壞值投影 null，不僅因可選欄位使所有完整策略失效。讀值 known 不是 source／time／version 准入。 |

`signal_read` 提供 status、invalid_fields、missing_fields、metadata_fields；invalid 優先於必要身份 missing，否則 known。合法但未知的策略 version 保留原語意，不假定所有 actionability gate 已驗；complete observation 缺少預期進場價位是原本的正常研究結果，不能被新必填條件改成污染。

### 16.2 JSON 與有限計算

Signal evidence 與 StrategyVersion config／canonical snapshot 只收可用 UTF-8 表示、最外層為 object 的 JSON；拒絕重複 key、非有限 constant／number、過深或過多節點。每欄最多 **65,536 UTF-8 bytes**，root depth 0、最大 **32**，最大 **16,384 nodes**，object key 也計 node。所有嵌套 integer 需能轉成有限 Float，避免 Python 可解析的巨大 integer 在 browser 變成 Infinity；這不是 Decimal exact 驗證。

合法 `{}` 保留；present invalid 投影 null／invalid，不能改成 `{}` 讓下游採空 evidence。SQL None 維持 null／missing 及既有 fallback，沒有新增必填 gate；本批只在 pure projection／RR 邊界驗此語意，不稱已向 NOT NULL SQLite 欄位保存 SQL NULL。evidence 的 inputs／levels 若提供須為 object，被消費的 RR 與三項數值 inputs 須 actual 有限數字。後端附加的 level_semantics 與 raw JSON 分開處理，前端核其一致且有界，不讓生成欄位侵占合法 raw JSON 的 node／depth 預算。

stock 模式 derived RR 的中間計算／結果非有限時投影 null；已有有限 evidence／fallback 規則保留，不製造 RR 或可操作結論。本批不增加 writer geometry、獨立 tick、source／time／version gate；既有規則仍決定合法研究行動。

### 16.3 詳情窗口、全集 latest 與截止

原儲存 signal_date DESC、id DESC 定候選次序；可定位且晚於 cutoff 的列排除，日期未知不能靠 lexical 大小當 future 略過。詳情保留最多 **20 個候選位置，先限定再驗值**，壞列不刪掉、不取較早合法列補滿。`candidate_order` 與回傳 signals 一致，不冒稱未知日期已知時間順序。

每策略 canonical latest 的 scope 是符合截止的全候選集，與詳情 20 列不同。breakout_v1／pullback_v1 各取其原排序最新列，bad latest 不能換較早候選；詳情的 20 個 custom invalid 記錄也不代替窗口外的健康 canonical slot。

全標的的無法定位日期檢查不受截止／20 列限制；符合截止範圍內無法定位 strategy identity（缺／壞 FK、無可定位的 joined id／name）也使整個研究 scope 拒用，而非略過未知策略。已定位 invalid core 只隔離該候選／策略 slot，其他健康策略沿原 actionability，aggregate invalid 不等於全面丟棄研究結果。

Signal 污染不撤掉已有合法 bar cutoff，獨立行情沿 §15 處理。無行情時，Signal 的日期 fallback 改用 raw 日期；有任一 unlocated Signal 日且未明示 as_of，共用 cutoff 保持 null，不改成較早日或今日。明示 cutoff 保留；其他 typed 研究日期仍有原依賴，不稱 FeatureSnapshot／Chip 污染已隔離。

### 16.4 回應與前端拒用界線

頂層與個股 decision 提供 `research_read`，version 為 `stock-research-read/v1`、verification 為 `stored_value_syntax_only`。其 candidate_count／candidate_order／window_limit=20、scanned／future／兩種 unlocated count 與第一個 id、兩個 canonical latest slot、blocked_strategies、decision_block_scope 一起核對；scope 為 instrument／slots／none。無候選為 missing；窗口內有候選 invalid 或全標的無法定位則 aggregate invalid，但可保留健康 alternate。

StockPage 核 candidate 身份、次序、欄位狀態、canonical slot 與 decision 的 envelope 一致；unsupported／矛盾／malformed 新回應不得拿 legacy 值補 summary／levels。完全 undefined 的舊回應只保留受限 action shape／有限數值相容與未提供狀態說明；null 不是 legacy。候選／slot 的 read.status 必須是 actual string known／missing／invalid，不能透過 String coercion 接受 array 或自訂 object。非字串拒用已做 focused pure／Panel 補驗，known 提示不冒用於 malformed status；HTTP-derived malformed 與非 JSON helper 的支持範圍由開發入口區分，不外推所有型別組合。

結構安全的 invalid／data_insufficient 結果可顯示，候選列表只讀原身份／日期／策略／版本／狀態，不是 Plan 或交易入口。held 的 `hold_observe`、`primary_strategy=null` 且 complete／known observation、空 missing／全 null 價位保留；正常 observation 不因沒有 expected entry levels 被抹除。summary 不可信時拒用研究行動／levels，bars 與其他獨立可用區塊保留；其中 typed models 本身的污染仍在本批範圍外。

### 16.5 具名有限接受與未包含

本次 fixture source 建構 **2026-10-04 synthetic 14 標的（TWSE 十三研究標的＋一個合成 TAIEX）**；初始 840 行情，I-NOBARS 移除 60 後，actual 四表 snapshot 為 **780 行情／十三庫存／38 Signals／5 StrategyVersions**，未由 instrument table snapshot 另驗標的數。這不是官方行情／來源、正式持倉或 M1 原件。actual getStock／Response.json、完整 App SSR 與以下五個桌面 case 已有限接受；每案 actual API 為 200、真正 App DOM 的研究分頁 selected，candidate count／raw identity／order／提示已核。桌面 **1298×924** 的 document client／scroll width 均 **1283**。

| Case | 已接受的有限結果與操作方式 |
| --- | --- |
| B-JSON | 1 筆、記錄 #2，日期／version／原 status 與 invalid 提示可見；行情 gap 0，拒用研究行動。原生 ref click 最終 selected 已核，先前未切換／錯 selector assertion 不改報成功。 |
| F-ALTERNATE | 2 筆，健康 pullback 與 invalid breakout 並存，原 hold_observe 保留，HTTP 的 primary 為 pullback_v1。程式 DOM.click 後核 actual App DOM，不稱原生點擊全部成功。 |
| H-WINDOW | 原序 #37 至 #18、恰 20 個 custom invalid，canonical 全集仍保留健康 hold_observe。程式 DOM.click 後核實，未把這 20 筆冒充 canonical 來源全集。 |
| I-NOBARS | 1 筆日期無法定位，default cutoff=null、無行情狀態保留，研究拒用。程式 DOM.click 後核實，不算截止表單提交。 |
| M-OBSERVATION | 1 筆 complete／known observation，hold_observe 保留；HTTP primary=null 與原空 levels 語意已核。程式 DOM.click 後核實，不額外宣稱新行動或原生 Enter 通過。 |

其餘四案以 DOM.click 核真正 browser DOM；工具 ack／focus／Enter 未 selected 不算成功，原失敗留 task，不稱五案全原生或推測未切換原因。

同一 fixture 的 HTTP／UI 前後，Signals／StrategyVersions／positions／bars 全欄與 typeof 同 digest、read mutation 0。Console 有既有 warnings，短暫 compiler 未即時觀測並發；歷史清理收據留原 task／Git，現有 blocked logs 依[協作紀錄](TASK_COORDINATION.md)。

本批未驗正向 M1 raw filesystem／磁碟重開、正式 DB／migration、完整 backend／production build、官方／live／availability／PIT、Decimal exact、新 Plan、全部行動或完整 M1／M3。P6c physical canvas、有效歷史窄版 layout、真正截止表單與其他 inherited 未驗界線保留；FeatureSnapshot／Chip、legacy tracking／Actions 等其他 typed models 尚未支持此隔離。下一具名候選／audit 與完成條件由 [ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)負責，有界審查本身不當能力交付。

## 17. M3-P6e：個股特徵／籌碼獨立區塊讀回隔離

本批支援 M3／R2-C2，接續 §16 未納入的特徵／籌碼。必要 direct／actual HTTP／App 與下述六具名操作已有限接受；污染留在自己的區塊，健康行情／研究仍可查看。版本收據留 Git／原 task，P6d 原測試與失敗只適用 §16。

### 17.1 個股 opt-in raw 投影與欄位狀態

產品稱呼 FeatureSnapshot／Chip 的實際保存模型為 `TechnicalFeature`／`ChipSnapshot`。只在 stock／instrument detail 及必要 stock decision／overview caller 啟用兩表 raw reader：`technical_features` 全 **6** 欄、`chip_snapshots` 全 **15** 欄繞過 Date／DateTime／JSON processor，**不使用 CAST**、不修資料或改 writer。其他 typed routes、legacy Actions／tracking 不在此 opt-in 隔離範圍。

feature snapshot 保留 id、instrument_id、trading_date、features_json、source、created_at；chip 保留 id／instrument_id／日期、八數值、source／data_as_of／collected_at／raw_payload_id。raw 身份僅接受正 int64、不 coercion；前端 section 身份另要求 JavaScript safe integer，不能把超 safe 的原始身份捨入後當同一列。每個欄位分 known／missing／invalid，missing／invalid 投影為 null，拒絕把數字字串、布林或非有限數字當可信數值。row_read 描述欄位狀態；feature_read／chip_read 使用 `stock-independent-read/v1`，含候選筆數／順序、scanned／future／unlocated count 與位置。`stored_value_syntax_only` 只證儲存讀值語法，known 不證來源、可得時間、用途或 PIT。

### 17.2 截止、窗口與無較早替代

raw 候選排序為 trading_date DESC／id DESC；先在完整該標的 scope 辨識日期，可定位且晚於截止的 known future 先排除，再固定 **feature 1／chips 120** 候選位置後驗值。不先刪 invalid 列湊窗口、不 refill；bad latest 不回到較早 feature，chips 壞列保留位置與 null 欄位。unlocated 在全 scope 判定，窗口外的無法定位日期不能因未顯示而消失。chips API 將同一固定候選反向供顯示，不重新查較早列；scanned／future／unlocated counts 指完整該標的 scope，與 coverage 分開。coverage 只採這 120 候選中日期合法且原五 consumed core 完整、並落在既有 TAIEX window 的交集；不證完整來源／市場 coverage。

健康 bars 的截止沿原優先規則；無 bars 時，兩獨立表任一 unlocated 使 default cutoff 保持 None，不取其他較早合法日冒充。明示 as_of 保留原值，但不把 unlocated 變成可用列；feature invalid／unlocated envelope 拒用 MA 呈現、不以較早快照替代。這是日期篩選與語法隔離，不證完整交易日、來源時間或歷史當時可得。

### 17.3 特徵 JSON、MA 與籌碼既有依賴

後端 features_json 沿原 strict dict reader，檢查原 JSON **65,536 UTF-8 bytes／depth 32／nodes 16,384**、合法 Unicode 與有限數字；不是 dict 或超限拒用。MA20／MA60 只接受內建有限數值，**零與負值保留**，不新增 positive gate；可選 source／created_at 無效只投影 null。feature 原始 JSON byte 限額與前端投影值的限額分開，parse／數字表示可能改變 JSON 拼法，前端不宣稱重證原 byte budget。

chip 八數值為 foreign_buy／trust_buy／dealer_buy／margin_balance／margin_change／short_balance／borrowed_sell／day_trade_ratio，有限數值或 null 逐欄呈現。原五個 consumed core（foreign_buy、trust_buy、dealer_buy、margin_balance、margin_change）與身份／日期仍支援原 5 日完整性 gate；其餘 optional 數值／metadata 的 invalid 不另加 blanket actionability gate。原 conditional、完整 observation、held quantity／stop 與必要 source 優先不改；不把 feature／chip known 自動當研究成立或新 Plan。

### 17.4 前端獨立區塊與有限相容

StockPage／StockResearchPanel 共用純 guard 核 shape、builtin-string state、field metadata、身份、數量與順序一致性。malformed feature 只拒用 feature／MA，malformed chip envelope 只拒用 chips；結構合法的 chip 列保留各欄有限數值與 missing／invalid null，並顯示自己區塊的 gap，健康 bars／研究不被整體抹除。前端 normalized／projected JSON 採 **512 KiB** 呈現限額，另核 **depth 32／nodes 16,384** 的有限樹與合法 Unicode；原 JSON 解析後的合法數字可能展開成較長拼法，這項上限與後端原 raw **65,536 bytes** 分開，不證原件或來源。合法數字展開與 giant string／key／object／array、null metadata／非字串 state 等 pure 邊界已由必要 helper 核對，必要 actual HTTP／App 支持已有限接受，不外推其他路徑。全部新讀值欄位 undefined 的舊 API 僅有有限數值相容；null／矛盾的新 envelope 不當舊回應。shared `ChipSnapshot` type 保持原樣。

actual getStock／Response.json、完整 App／Panel、具名兩分頁操作與同 instance 六表全欄／SQLite typeof 在讀回前後及 UI 後不變、read mutation 0 已在以下有限範圍接受。當批方法／資料／HTTP／SSR／程序配額及原始 exit 留原 task／Git；可重建入口及零落盤限制見[開發入口](development-baseline/README.md#m3-p6e-個股獨立特徵籌碼讀回的零落盤驗證入口)，現有未清資源見[協作紀錄](TASK_COORDINATION.md)；文案見 [UI 規格](UI_COPY_SPEC.md#m3-p6e-獨立特徵籌碼區塊文案有限接受)。

### 17.5 具名有限接受與未包含

必要 direct 首輪新 held observation 測試誤期望 primary_risk={}，實際原 kind／stop:null／semantics 正確；只修該 expectation 後單項補驗通過，八個有效 case 未重播。必要 noEmit／pure guards、actual getStock／Response.json、App／Panel 已有限接受；原 exit、數量、SQL receipts 與 warnings 留原 task／Git，可重建入口見[開發入口](development-baseline/README.md#m3-p6e-個股獨立特徵籌碼讀回的零落盤驗證入口)，不把 pure cases 全改稱 HTTP-derived JSON。

SQL None 的 features_json 只核 pure projection，不聲稱存進 NOT NULL 欄；SQLite affinity 已數值化的 numeric string／bool 只能核現在 storage，不能還原遺失輸入意圖。

本次 **2026-10-04 synthetic** 單一 Python fixture 含十個研究標的與一個合成 TAIEX，不是官方行情、正式持倉或 M1 原件；actual HTTP／App／Panel 已接受，具名六案 API 均 200。資料筆數及 SSR／HTTP 計數由開發入口負責。桌面 **1298×924／mobile=false／client＝scroll 1283**，以下分頁 selected／實際 DOM 與必要數值已核。

| Case | 已接受的有限結果與實際操作 |
| --- | --- |
| B-JSON | 資料 tab 原生 click 最終成功；feature candidate 1、invalid、features={}，不呈較早 MA999，60 bars 與 hold_observe 保留。首次 offscreen ACK 沒事件不算成功；捲至可見後才核原生操作。 |
| D-METADATA | data＋chips 以程式 DOM.click 核 selected；MA20／60為10／9、source／時間 null、1 chip 各合法值保留、未知單位空白、無 core gap；60 bars／hold_observe 保留。原生 ACK 仍 technical 的 assertion 失敗另報。 |
| E-CHIP | DOM.click chips selected；1 列 foreign_buy／margin_change 無效空白，其他有限數值保留，不以整列零代替。 |
| H-WINDOW | DOM.click chips selected；120 candidates／scanned121，最新 invalid 仍在、不 refill；30 UI 列日期10/04至9/05。另 DOM.click research 可見持有觀察、Panel及4價位；錯 CSS 的 candidateRows=0查詢不當實際候選數。 |
| F-UNLOCATED | DOM.click chips selected；120 candidates／scanned122、窗口外unlocated1／id252，候選日期皆合法仍保留區塊 gap，不把窗口合法當全 scope 無污染。 |
| I-NOBARS | 無 as_of 的 default cutoff=None、bars0／summary=null；1 unlocated／id251／date=null，DOM.click chips 核「未提供」，不偽造日期或截止。 |

只有 B 最終為原生分頁操作，其餘是 DOM.click 後核實真正 App DOM。Runtime／selector／原生 ack 未切換等原失敗留 task，不稱六案全原生；兩 QA pages 順序使用、最大同時一個，沒有重啟／reseed fixture 或 replay B。

同一 fixture 六表全欄／typeof 在 start、HTTP 前後及 UI 後同 digest、read mutation 0。Console／network 只支持具名查閱範圍，compiler exit code 未觀測；歷史程序／順序 QA pages 收據留原 task／Git，現有 blocked 殘留依[協作紀錄](TASK_COORDINATION.md)。

本批不改 P6d／P6c 的已接受操作或原失敗，不宣稱其他 typed models／legacy Actions／tracking、M1 正向原件、官方／live／availability／PIT、正式 DB／migration／磁碟重開、完整 backend／production build、新 Plan、完整 M1／M3。P6c canvas／有效歷史窄版／真正截止提交等 inherited 未驗保持待驗；memory fixture 不降低原件或磁碟條件。

5／20 日法人與研究條件仍固定保守回應時，代表必要輸入／consumer 未接通；P6e 讀回可靠性改善不等於核心流程完成。後續選題優先解除具名核心依賴或新增可驗收操作，不預設新隔離輪，詳見[ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)。

## 18. M1-W2：同截止法人窗口與原件追溯

本節保留 W2 的歷史版本／單截止操作；現行四截止與新版來源沿[§20](#20-m1-w4四截止法人窗口與原件追溯)。

**實際原件→API／UI 及下述操作已有限接受。** 支持 TPEx 3105／6488、唯一共用 `as_of=2026-10-02`；總覽 `stock-overview/w2-v1`、法人 `institutional-windows/w2-v1`。來源、policy pins、22日曆／20日原件、單位／缺日與計算版本沿用[來源 §13](SOURCE_REGISTRY.md#13-m1-w1tpex-多日法人與完整有界交易日)，不放寬 P2b 單日或其他來源。

### 18.1 明示取得、共用截止與記憶體

Server 必須 exact `STOCK_TPEX_INSTITUTIONAL_WINDOW_MEMORY_CAPTURE=1`。`POST /api/stocks/{exchange}/{symbol}/institutional-windows/capture?as_of=2026-10-02` 先核標的存在，再用共用截止核支持範圍；首次核定操作才調 W1 loader，最多22 GET。後續兩股 POST／detail／overview GET 重驗同一批 process-memory 原件，普通 GET／import 零外網、不寫 DB／檔案。非阻塞鎖拒並行取得；成功或失敗後不 retry、refresh 或較早 fallback。重啟後須另作新觀測，不稱保存或離線重播。

未啟用／無效設定、未取得、busy、來源／日曆失敗及範圍外各有 reason。其他市場／標的／截止不返回舊窗口數值；缺共用截止不補資料日。10/03 截止無值／無載入按鈕，恢復10/02讀 held cache；取得時間不能替代資料 cutoff，也不能推論歷史當時可得。

### 18.2 精確窗口與來源展開

`overview.institutional.windows['5'/'20']` 各有 status、values、from／to、required／valid／missing／invalid dates、原因及 daily evidence；detail 與獨立 overview 同截止／版本。外資（不含外資自營商）／投信／自營商分列，canonical 整數字串以 BigInt 加千分位，單位股、不轉 Number。只有單位／編碼、支持 cutoff、日曆及該窗 available、三值合法才顯數值；缺日按窗顯示資料不足，不補零、縮窗或重加外資自營商。

畫面顯示所需／已驗／缺日、TPEx 顯名、兩個政府資料集及 OGL1 連結。展開可查日曆規則／休市公告、版本／policy、逐日原列序與 buy／sell／net、exact CSV、body／receipt SHA、UTC取得時間。published／first available／revision unknown、PIT unsupported、不判研究條件成立；P2b 單日區塊仍獨立。

### 18.3 已接受操作與未驗邊界

桌面1298×924 native 首按3105載入，22新 GET／22原件 body hash 與 W1 相符，但 capture／receipt 是新觀測。兩股40原列、360個 API buy／sell／net 字串及12窗口 net 的獨立 buy－sell 重算一致；detail／overview 同截止／版本，19表全欄及 typeof 前後不變、guard0。3105／6488原生讀回六值、截止10/03 submit 拒用與恢復10/02 submit、TWSE3105範圍外無值／無按鈕均接受；全程 request_count 仍22。

桌面來源原生展開、390×844原生 scroll 後展開2026-09-03原列175，外資 buy `11,221,514`／sell `11,657,008`／net `-435,494`、hash／UTC可追。body client／scroll 375／375；wrapper303、table780、overflow auto，DOM scrollLeft477後完整性末欄在 wrapper內。原生橫向工具 ack 後 scrollLeft仍0，**原生橫向手勢未驗**。首次 snapshot 斷線及視口外 click 未展開的原失敗留 task，不改報首跑全通。

5個新 API case、18 SSR、full-src noEmit、mock product HTTP已有限接受；Vite build未跑，字型僅fallback，physical canvas／pending導航 race 未驗。範圍外日期／證券／TWSE、修訂／PIT、研究條件與磁碟保存仍缺，完整 M1 未完成。驗證入口見[開發文件](development-baseline/README.md#m1-w2-法人窗口的零落盤驗證入口)，細命令／UTC／full hashes 留原 task。

## 19. M1-W3：三截止法人窗口與原件追溯

本節保留 W3歷史版本／三截止操作；現行四截止見[§20](#20-m1-w4四截止法人窗口與原件追溯)。

**實際原件→API／完整 App 原生操作已有限接受。** 支持 TPEx 3105／6488、共用 `as_of` 為2026-09-30／10-01／10-02；總覽 `stock-overview/w3-v1`、法人 `institutional-windows/w3-v1`、worker `tpex-institutional-window/w3-v1`。當次 policy／來源版本、完整日曆、窗口與36 net參考由[來源 §14](SOURCE_REGISTRY.md#14-m1-w3三截止法人來源與窗口)管理；§18及§13來源 W1 pins僅為歷史，不作本版設定。

### 19.1 共用截止、一次取得及精確呈現

明示 server設定仍為 exact `STOCK_TPEX_INSTITUTIONAL_WINDOW_MEMORY_CAPTURE=1`。capture POST先核標的存在與 supported cutoff；首次核定操作取得同一 instance 的22 daily＋2 month process-memory union，後續兩股 POST／detail／overview GET重驗 held同24份原件，普通 GET／import零外網、不寫 DB／檔案。非阻塞鎖、一次嘗試／拒 retry／refresh／較早 fallback及重啟須新觀測的界線不變；**W3 first POST 為 actual API 3105／9/30，原生操作讀取其 held instance**。

日期輸入與原生「套用截止」提交後，總覽及每窗採同 cutoff。5／20日各列三類 canonical整數字串、股單位、BigInt千分位與 required／valid／missing／invalid dates；需該日的窗口缺資料就拒用，不補零、縮窗或採 future／earlier值。三 cutoff均驗缺日0。範圍外截止或市場／標的移除先前所有 net及窗口載入按鈕，恢復支持 cutoff才讀同 held值。

來源詳情保留 TPEx署名、政府資料集／授權、exact CSV、原列序及 buy／sell／net、body／receipt SHA、UTC、policy／source／calendar／calculation版本。所選 cutoff只顯≤cutoff的窗口 daily evidence；例如9/30的20日列集合9/1～9/30，union中較晚的10/1、10/2不混入。published／first available／revision仍 unknown、PIT unsupported，突破／回踩仍固定保守，單日 P2b與其他來源區塊保持獨立。

### 19.2 具名原生操作驗收

| 操作 | 已接受的有限結果 |
| --- | --- |
| 兩股三截止切換 | 完整 App同 instance，3105與6488各 Date input填寫及原生「套用截止」依序9/30→10/1→10/2；DOM36 net全部對獨立原件真值。3105明核 trusted pointerdown／up／click及日期填寫鍵事件；兩股原生讀取按鈕的 repeat POST仍讀 held同24原件。 |
| 6488來源詳情 | 10/2原生展開，cutoff／policy／calendar／calculation、hashes及UTC與同批收據一致。 |
| 390×844新日原列 | 切9/30，原生展開6488的9/1原列646，九個 buy／sell／net真欄位及來源版本／hash／UTC可見，日原列開啟 isTrusted=true；20日日列為9/1～9/30，無未來日。body client／scroll375／375，wrapper303／table780、overflow auto。 |
| 未支持 cutoff與市場 | 原生提交9/29後無舊 net／無窗口按鈕，恢復9/30讀同 held值；TWSE3105／9/30亦無 net／按鈕，actual API同樣拒用。 |

`DOM.scrollIntoView`僅作定位 setup，不列為原生橫向手勢。最初兩次 Orca snapshot／eval runtime connection failure、未 focus時工具 ack但 trusted事件／來源展開均0的操作保留為原失敗；後續 `--focus`才使 browser pane實際聚焦，原生操作成功，未 restart／換 browser／重取來源。詳細證據留原 task，不把早先 ack當 native通過。

### 19.3 已驗與未驗的界線

兩股／三截止 actual API的6組 detail.overview等於直接overview，cutoff／版本／batch一致；原件與重複 API字串核對集中[來源 §14.4](SOURCE_REGISTRY.md#144-w3-真資料與有限數值核對)。19表全欄／typeof由 before至 shutdown不變、reader exit0／guard0，測試及自有服務清理見[開發入口](development-baseline/README.md#m1-w3-三截止法人窗口的零落盤驗證入口)。

worker7、actual router5、24 SSR、full-src noEmit及 mock product HTTP／BigInt36 net已有限接受。完整 backend／舊 ZIP／live未重跑；horizontal原生手勢、physical canvas、Vite／production build及 pending導航 race仍未驗。範圍外日期／證券／TWSE、修訂／PIT、研究條件、原件保存與跨程序讀回及完整 M1未完成；W3本版未放行9/29；後續 W4新範圍另見§20。

## 20. M1-W4：四截止法人窗口與原件追溯

本節是W4已驗收的歷史操作／版本；現行W5五截止見[§21](#21-m1-w5五截止法人窗口與原件追溯)，原W4數值及未驗界線仍保留。

**實際原件→API及兩股各四 cutoff可信原生表單操作已有限接受。** 支持 TPEx3105／6488、共用 `as_of=2026-09-29／09-30／10-01／10-02`；總覽 `stock-overview/w4-v1`、法人 `institutional-windows/w4-v1`、worker `tpex-institutional-window/w4-v1`。來源、policy pins、23日曆／全月 index核對及唯一48 net真值見[來源 §15](SOURCE_REGISTRY.md#15-m1-w4四截止法人來源與全月日曆核對)，W1–W3設定與觀測只保留歷史。

### 20.1 共用截止、一次取得及精確呈現

沿 exact server opt-in `STOCK_TPEX_INSTITUTIONAL_WINDOW_MEMORY_CAPTURE=1`及既有 capture POST。先核標的存在與 supported cutoff；W4 first actual API POST為3105／9/29，新取3 month＋23 daily。後續兩股 POST／detail／overview GET重驗 held同26份 process-memory原件；普通 GET／import零外網、不寫 DB／檔案。鎖／一次嘗試、拒 retry／refresh／較早 fallback及重啟須新觀測界線不變，原生操作讀同一 instance。

日期原生「套用截止」後每窗採同 cutoff，canonical整數字串以 BigInt千分位、單位股；5／20日各列三類 net及 required／valid／missing／invalid dates。八組兩股／四截止共48 DOM net對獨立真值，from／to正確且 missing0；缺日按窗拒用，不補零、縮窗或採 future／earlier值。

來源詳情保留 TPEx署名／政府資料集／授權、exact URL／日原列序／buy／sell／net、body／receipt SHA／UTC及 policy／source／calendar／calculation版本。月原件顯示完整月已驗列數、有界採用列數及界線前已驗但未採用列數；8月為21／1／20。日窗口只顯≤cutoff的 required daily evidence，不把界線前已驗 index或 union未來日加入。發布／first availability／revision unknown、PIT unsupported；突破／回踩固定保守，P2b單日與其他來源區塊保持獨立。

### 20.2 具名原生操作與驗收邊界

| 操作 | 已接受的有限結果 |
| --- | --- |
| 兩股四截止切換 | 同完整 App／held instance，3105、6488各原生日期填寫及可信 form submit四截止；48 DOM net、5／20日起迄與missing0均核通。兩股各一次可信 BUTTON click的repeat POST仍 held26，不新增來源取得。 |
| 不支持 cutoff | 6488原生提交9/28後舊 net消失／窗口button0，原生恢復9/29讀 held值已接受；source request_count仍26。 |
| 390×844新增原列 | 在390×844，兩股原生 trusted SUMMARY展開8/31原列：3105列176／6488列645、各九個 DOM raw金融欄位及 hash／v3 source version均與原件一致。另一次375×844窄版量測為 innerWidth375、body scrollWidth360（15px垂直 scrollbar）、wrapper288／table780、overflow auto；定位／scroll setup不列原生橫向手勢。 |
| 範圍外市場 | TWSE3105／9/29 route DOM為資料不足／無舊數值／窗口button0已核；route setup不稱原生市場導航。 |

其後六組 source outer SUMMARY（兩股×9/30／10/1／10/2）各原生展開；20個 required日列／日期≤cutoff及每組180個 buy／sell／net raw欄位均以 DOM/textContent核對（含未原生展開的子表），合計1080欄對獨立原件。9/29兩股來源的 policy／calendar／日列及8/31新原列亦已核。

初期 connection failure、JS quoting錯誤、locator參數錯誤、鍵盤／type ack無輸入、視口外窄版定位及6488轉頁後0可信事件均不計成功。後續同 visible terminal切回、tab focus／locator及原生方向鍵分段操作才核可信表單；一次 same-owned-page reload不重取 source。Win32 focus回false不是成功，Computer Use guide讀取未發生 GUI操作／operation file。細節原失敗與 setup留 task，不把工具 ack、DOM定位或 readback當原生輸入證據。

### 20.3 驗證與尚缺邊界

來源／actual API數值核對集中[§15.4](SOURCE_REGISTRY.md#154-w4真資料與唯一48-net參考)；19表全欄／typeof及guards、具名測試補驗與服務清理界線見[開發入口](development-baseline/README.md#m1-w4-四截止法人窗口的零落盤驗證入口)。Worker9首跑exit0；API首suite exit1的失敗保留，僅修正後具名 first-post案例補驗exit0；noEmit／40 SSR／48 mock HTTP BigInt net exit0。本輪 actual API／具名原生操作及 owned服務清理已有限接受。缺／錯8/31造成局部窗口失效由必要 synthetic API／SSR驗證，不稱 actual缺日原生操作。

未重跑 legacy／ZIP／old live／完整 backend；physical canvas、原生橫向手勢、Vite／production build及 pending導航 race仍未驗。範圍外日期／證券／TWSE數值、修訂／PIT、研究條件、raw保存／跨程序讀回與完整 M1未完成；本W4觀測未取得／准入W5新9/24及8/28 daily；後續W5獨立版本／操作見§21，不由W4 pins放行。

## 21. M1-W5：五截止法人窗口與原件追溯

**原件→actual API及兩股各五截止可信原生操作已有限接受。** 支持TPEx3105／6488、共用 `as_of=2026-09-24／09-29／09-30／10-01／10-02`；總覽 `stock-overview/w5-v1`、法人 `institutional-windows/w5-v1`、worker `tpex-institutional-window/w5-v1`。Policy／source versions、24日曆與唯一60 net真值集中[來源 §16](SOURCE_REGISTRY.md#16-m1-w5五截止法人來源與完整有界日曆)，W1–W4設定／觀測只保留歷史。

### 21.1 共用截止、一次取得及精確來源呈現

沿server opt-in `STOCK_TPEX_INSTITUTIONAL_WINDOW_MEMORY_CAPTURE=1`及既有capture POST。先核標的存在與supported cutoff；W5 first actual POST為3105／9/24，新取3 month＋24 daily。後續POST／detail／overview GET重驗同held27份process-memory原件；普通GET／import零外網、不寫DB／檔案。鎖／一次嘗試、拒retry／refresh／較早fallback及重啟須新觀測界線不變，所有原生操作讀同一instance。

日期原生「套用截止」後每窗採同cutoff；canonical整數字串以BigInt千分位、單位股，5／20日各列三類net與required／valid／missing／invalid dates。缺日按窗拒用，不補零、縮窗或較早／未來替代。

來源詳情保留TPEx署名／資料集／授權、exact URL／daily raw ordinal／buy／sell／net、body／receipt SHA／UTC及policy／source／calendar／calculation版本。來源版本觀測日期明示Asia/Taipei2026-10-05，UTC精確收據另列。月原件顯示全返回月已驗、有界採用與界線前已驗未採列數；8月21／2／19。日窗口只顯≤cutoff的required daily evidence，不把較晚union日或界線前index當作窗口daily。發布／first availability／revision unknown、PIT unsupported；突破／回踩固定保守，P2b與其他來源區塊獨立。

### 21.2 具名原生操作與有限驗收

| 操作 | 已接受的有限結果 |
| --- | --- |
| 兩股五截止切換 | 同完整App／held instance，兩股各五個可信原生日期表單submit；isTrusted input／change／submit／KEYDOWN正面核。10組共60 DOM net、5／20日起迄及missing0逐欄對獨立真值。兩股各一次native BUTTON重複POST仍held27。 |
| 來源原生外層展開 | 兩股×五cutoff共10組source outer SUMMARY可信展開，每組20 required dates≤cutoff及180 buy／sell／net原字串以textContent核，合計1800金融欄與原件一致；不稱全部20個daily子表都曾原生展開。 |
| 390×844新8/28原列 | 兩股9/24原生trusted daily SUMMARY展開8/28，日期1150828、各9個DOM raw金融欄、body hash及daily v4一致；raw ordinal3105=175、6488=652。新body hash見來源§16.4，不重抄數值。 |
| 不支持cutoff與恢復 | 6488原生9/28後舊DOM net／raw evidence／window button均0；原生恢復9/24的6 net與真值一致，source request_count仍27。 |
| 範圍外市場 | TWSE3105／9/24 route DOM numeric0／window button0；goto只作route setup，不稱原生市場導航。 |

390×844實測innerWidth390、body scrollWidth375（15px垂直scrollbar）、wrapper303／table780／overflow auto；375×844另實測innerWidth375、body360／wrapper288／table780／auto。原生展開及寬度核對不代原生橫向手勢、physical canvas或production build。

Native續接只用同owned page／session，一次sameURL goto不重取來源。Connection／JS quote／os206／ack0 trusted／source-closed assert／snapshot截斷及日期中間值誤到9/29均不計成功；原wait9/28 exit1及詳細raw／error留原task，核實actual date並原生修正後才接受9/28拒用／恢復。工具ack／DOM定位不代可信輸入，未換page／session或重取來源。

### 21.3 驗證及仍未支持的界線

來源／actual API逐欄及60真值集中[§16.4](SOURCE_REGISTRY.md#164-真來源獨立觀測與唯一60-net參考)；11 worker／5 real-router mock、核定Node noEmit／62 SSR／60 mock BigInt及owned服務清理見[開發入口](development-baseline/README.md#m1-w5-五截止法人窗口的零落盤驗證入口)。實際missing0；缺／壞8/28導致局部窗口失效只由必要synthetic API／SSR驗證，不稱actual缺日原生操作。

未重跑legacy／ZIP／old live／完整backend；physical canvas、原生橫向手勢、Vite／production build及pending導航race仍未驗。範圍外日期／標的／TWSE、修訂／PIT、研究條件、raw保存／跨程序讀回與完整M1未完成；W6新9/23及8/27 daily仍待真來源／新版本gate，不由本版放行。

## 22. M1-W6：六截止法人窗口與原件追溯

**真來源→六截止72 net／actual API及兩股具名可信native已有限接受；owned page／服務已核清。** 支持TPEx3105／6488、共用 `as_of=2026-09-23／09-24／09-29／09-30／10-01／10-02`；總覽 `stock-overview/w6-v1`、法人 `institutional-windows/w6-v1`、worker `tpex-institutional-window/w6-v1`。本版來源／policy／25日曆及唯一72 net集中[來源 §17](SOURCE_REGISTRY.md#17-m1-w6六截止法人來源與完整有界日曆)；§18–21各自保留歷史，非本版設定。

### 22.1 同截止、一次取得及原列追溯

沿server opt-in `STOCK_TPEX_INSTITUTIONAL_WINDOW_MEMORY_CAPTURE=1`與既有capture POST，先核標的存在與supported cutoff；first actual POST3105／9/23新取3month＋25daily，後續POST／detail／overview GET重驗同held28 process-memory原件，普通GET／import零外網、不寫DB／檔案。鎖／一次嘗試、拒retry／refresh／較早fallback及重啟新觀測界線不變。

原生「套用截止」後兩窗採同cutoff，canonical整數字串用BigInt千分位／股，5／20日三類net及required／valid／missing／invalid分列。來源詳情沿署名／資料集／授權、exact URL／daily raw ordinal／buy／sell／net、雙SHA／UTC與policy／source／calendar／calculation版本。月原件全返回已驗、有界採用、界線前未採分開，8月21／3／18；daily只列≤cutoff required evidence。發布／first availability／revision unknown、PIT unsupported；突破／回踩固定保守，未新增trend／研究條件，其他來源區塊獨立。

### 22.2 具名可信原生操作與有限驗收

| 操作 | 已接受的有限結果 |
| --- | --- |
| 兩股六截止切換 | 同完整App／held28 instance，兩股各六次unique可信原生日期form submit，共12組；72 DOM net、5／20日起迄及missing0逐欄對root獨立raw真值。6488恢復操作另計，不混12 unique base cases。兩股各一次native BUTTON repeat POST仍held28。 |
| 來源外層展開 | 12組outer SUMMARY可信open，每組20 required dates≤cutoff、180 finance textContent原字串／hash／daily v5／ordinal逐欄核通，共2160欄；不稱全部20 nested daily曾原生展開，不混API2700或1100 distinct raw金融欄。 |
| 390×844新8/27原列 | 兩股9/23 nested SUMMARY可信open：日期1150827、各9個buy／sell／net raw字串、body hash及daily v5一致，ordinal3105=176／6488=647。Body hash與72值集中來源§17，不重抄數值。 |
| Unsupported與恢復 | 6488 native9/28清舊值：numeric／window button／daily evidence均0；native恢復9/23後6 net與真值一致，held28不重取。 |
| 範圍外市場 | TWSE3105／9/23 route DOM numeric／window button／daily evidence均0；goto僅route setup，不稱native市場navigation。 |

390×844實測innerWidth390、document.body.clientWidth375（15px垂直scrollbar）、wrapper303／table780／overflow auto。Goto會重設viewport：6488曾實觀desktop1277／924，後再set390核新mobile；不聲稱goto保留窄版。W6未新驗375、原生橫向手勢、physical canvas或Vite／production build，舊§21的375範圍保留歷史。

同唯一owned page／session續接，無reload／新page／來源重取。首snapshot、tabswitch focus及wait URL glob各connectionclosed原exit1，exact terminal switch＋existing tab focus後可用；direct PS eval quoting SyntaxError（Private field #stock）改Python structured ASCII argv。首次CSS click ack命中HTML未open、outer-open／trusted-summary檢查失敗不計成功；scrollIntoView setup後可信SUMMARY才接受。Native helper首次將Orca date string誤parse JSON，SyntaxError／0form submit、9/24留draft；修reader並同date up／down再submit成功。Snapshot trunc只tool output截斷，不另稱parse failure；完整原錯／exit／trusted evidence留原task，ack／定位不代可信輸入。

### 22.3 仍未支持的界線

實際missing0；缺／壞8/27與按窗口失效須分報synthetic API／SSR及actual範圍，不稱actual缺日native。Legacy／ZIP／old live／完整backend、physical canvas、原生橫向手勢、Vite／production build與pending導航race未驗；範圍外日期／標的／TWSE、修訂／PIT、trend／研究條件、raw保存／跨程序讀回及完整M1仍未完成。必要mock及已核owned page／服務清理收據由[開發入口](development-baseline/README.md#m1-w6-六截止法人窗口的零落盤驗證入口)管理，原失敗及完整證據留原task。

## 23. M1-W7：七截止法人窗口與原件追溯

**真來源→七截止84 net／actual API及兩股具名可信native已有限接受；owned page／服務清理已核。** 支持TPEx3105／6488，共用 `as_of=2026-09-22／09-23／09-24／09-29／09-30／10-01／10-02`；總覽 `stock-overview/w7-v1`、法人 `institutional-windows/w7-v1`、worker `tpex-institutional-window/w7-v1`。來源／policy／26日曆及唯一84 net集中[來源 §18](SOURCE_REGISTRY.md#18-m1-w7七截止法人來源與完整有界日曆)；§18–22原byte保留歷史，不作本版設定。

### 23.1 同截止、一次取得及原列追溯

沿server opt-in `STOCK_TPEX_INSTITUTIONAL_WINDOW_MEMORY_CAPTURE=1`與既有capture POST，先核標的存在與supported cutoff；first actual POST3105／9/22新取3month＋26daily，後續POST／detail／overview GET重驗同held29 process-memory原件，普通GET／import零外網、不寫DB／檔案。鎖／一次嘗試、拒retry／refresh／較早fallback及重啟新觀測界線不變。

原生「套用截止」後兩窗同cutoff，canonical整數字串以BigInt千分位／股呈現，5／20日三類net及required／valid／missing／invalid分列。來源詳情沿署名／資料集／授權、exact URL／daily raw ordinal／buy／sell／net、雙SHA／UTC與policy／source／calendar／calculation版本。月原件全返回已驗、有界採用、界線前未採分開，8月21／4／17；daily只列≤cutoff required evidence。發布／first availability／revision unknown、PIT unsupported；突破／回踩固定保守，未新增trend／研究條件或Signal接線，其他來源區塊獨立。

### 23.2 具名可信原生操作與有限驗收

| 操作 | 已接受的有限結果 |
| --- | --- |
| 兩股七截止切換 | 同完整App／held29 instance，兩股各七次unique可信date spinbutton Arrow及FORM submit，共14組；首3105／9/22 Enter，其餘Apply BUTTON。84 DOM net、5／20日起迄及missing0對root獨立raw真值；恢復不算第15唯一。兩股各一次native讀取BUTTON repeat POST仍held29。 |
| 來源外層展開 | 14組outer SUMMARY可信open，各20 required daily≤cutoff、180 raw金融textContent／hash／daily v6／ordinal逐欄核通，共2520欄。不稱全部20 nested日子表曾原生展開，不混API3150或1144 distinct raw金融欄。 |
| 390×844新8/26原列 | 兩股9/22 nested SUMMARY可信open：日期1150826、各9個buy／sell／net raw字串、body hash及daily v6一致，ordinal3105=175／6488=637；hash與84值集中來源§18。 |
| Unsupported與恢復 | 6488 native9/28清舊值：numeric／window button／daily evidence均0；native恢復9/22後6 net與真值一致、held29不重取。 |
| 範圍外市場 | TWSE3105／9/22 route DOM numeric／window button／daily evidence均0；goto僅route setup，不稱native市場navigation。 |

14組日期操作中13組explicit390×844，首組viewport未獨立印出；另兩股9/22新8/26nested原列均於390×844可信展開。實測innerWidth390／body.clientWidth375／wrapper303／table780／overflow auto；375是clientWidth，不是scrollWidth或新375 viewport驗收。新375 viewport、原生水平手勢、physical canvas、Vite／production build及pending導航race未驗。

只續用同owned page，無reload／restart／新page／來源重取。Focus ack／keyup無trusted事件不算成功；goto後缺--focus使draft未變、monthend ArrowUp形成9/31空draft（assert exit1／0submit）均未計通過，修exact own terminal＋same page --focus及有效方向後才接受，只補剩6日期而非重跑已通8組。其他namespace／connectionclosed／@ref／quote／長命令及viewport原錯、原exit、可信證據與服務清理集中[開發入口](development-baseline/README.md#m1-w7-七截止法人窗口的零落盤驗證入口)及原task，不以ack／定位代可信輸入。

### 23.3 仍未支持的界線

Actual missing0；缺／壞8/26局部窗口失效只有必要synthetic API／SSR，不稱actual missing native。Catalog／price seed僅synthetic-memory，19表保留不證真行情或正式DB；legacy／ZIP／old live／完整backend、physical canvas、原生橫向手勢、Vite／production build與pending導航race未驗。範圍外日期／標的／TWSE、修訂／PIT、trend／研究條件／Signal、raw保存／跨程序讀回及完整M1仍未完成。

## 24. M1-W8：八截止法人窗口與原件追溯

**真來源→八截止96 net／actual API及兩股具名可信native已有限接受；owned page／服務清理已核。** 支持TPEx3105／6488，共用 `as_of=2026-09-21／09-22／09-23／09-24／09-29／09-30／10-01／10-02`；總覽 `stock-overview/w8-v1`、法人 `institutional-windows/w8-v1`、worker `tpex-institutional-window/w8-v1`。來源／policy／27日曆與唯一96 net集中[來源 §19](SOURCE_REGISTRY.md#19-m1-w8八截止法人來源與完整有界日曆)；§18–23原byte保留歷史，不作本版設定。

### 24.1 同截止、一次取得及原列追溯

沿server opt-in `STOCK_TPEX_INSTITUTIONAL_WINDOW_MEMORY_CAPTURE=1`與既有capture POST，先核標的存在／supported cutoff。First actual POST3105／9/21新取3month＋27daily，後續POST／detail／overview GET重驗同held30 process-memory原件；普通GET／import零外網，不寫DB／檔案。鎖／一次嘗試、拒retry／refresh／較早fallback與重啟新觀測界線不變。

原生「套用截止」後兩窗同cutoff，canonical整數字串以BigInt千分位／股呈現，5／20日三類net及required／valid／missing／invalid分列。來源詳情沿署名／資料集／授權、exact URL／daily ordinal／buy／sell／net、雙SHA／UTC及policy／source／calendar／calculation版本。月原件全返回已驗、有界採用與界線前未採分開，8月21／5／16；daily只列≤cutoff required evidence。發布／first availability／revision unknown、PIT unsupported；突破／回踩固定保守，未新增trend／研究條件或Signal接線，其他來源區塊獨立。

### 24.2 具名可信原生操作與有限驗收

| 操作 | 已接受的有限結果 |
| --- | --- |
| 兩股八截止切換 | ROOT-W8-NATIVE-3105-1／6488-1於同完整App／held30 instance，各8組unique可信date spinbutton方向鍵＋FORM submit，共16組；96 DOM net、5／20日起迄與actual missing0均對root獨立raw真值。16組日期全有explicit390×844觀測；恢復不算第17唯一支持日期。 |
| 來源外層展開 | 16組outer SUMMARY可信click，各20 required daily≤cutoff、9金融textContent／日逐欄對held30，共2880欄。不稱20 nested日子表全曾原生展開，不混API3600與1188 distinct raw金融欄。 |
| 390×844新8/25原列 | 兩股9/21 nested SUMMARY可信open：日期1150825、各9個buy／sell／net raw字串、body hash／daily v7一致，ordinal3105=175／6488=641；hash與96值集中來源§19。 |
| 原生再次讀取 | 各股9/21「讀取本次法人窗口」BUTTON可信repeat POST，仍held30／source0，不重取當次原件。 |
| Unsupported與恢復 | ROOT-W8-NATIVE-BOUNDARY-1：6488 native9/28清numeric cells／capture button／daily evidence各0；native9/21恢復真6 net，保持held30。 |
| 範圍外市場 | TWSE3105／9/21 route三項各0；goto僅route setup，不稱native市場導航。 |

兩股新原列實測390×844、body.clientWidth375／wrapper303／table780／overflow auto；375為body clientWidth，非新375 viewport或scrollWidth驗收。新375 viewport、原生水平手勢、physical canvas、Vite／production build與pending導航race均未驗。

本輪建立1個owned page `f86c37bb-b554-4f85-854a-d874bb062eaf`；其後沿同頁續接，無額外page／reload／restart／來源重取，最後唯一close。Focus／key／click ack未有trusted事件、日期或outer open不算pass；正確fresh focus／viewport scroll後actual trusted才通。6488 goto／tab focus後actual1277×924使viewport assert1／0forms，explicit重設390×844後才核8組unique。其他connectionclosed／unsupported argument／PS quote原錯、原exit及補驗見[開發入口](development-baseline/README.md#m1-w8-八截止法人窗口的零落盤驗證入口)，不以ack或定位代可信輸入。

### 24.3 仍未支持的界線

Actual missing0；缺／壞8/25按窗口失效只有必要synthetic API／SSR，不稱actual missing native。Node mock HTTP未跑；上述16組native已覆蓋actual full App產品fetch／Response.json真96 net。Catalog／price seed僅synthetic memory，19表保留不證真行情或正式DB；legacy／ZIP／old live／完整backend、physical canvas、原生橫向手勢、Vite／production build與pending導航race未驗。範圍外日期／標的／TWSE、修訂／PIT、trend／研究條件／Signal、raw保存／跨程序讀回及完整M1仍未完成。

## 25. M1-PRICE-1：上櫃兩股單日價量閉環（有限接受）

**TPEx3105穩懋／6488環球晶、2026-10-05的真單日價量、actual API與具名可信操作已由root有限接受。** 來源／用途、固定policy／body pins、兩股唯一金融值及production capture權威見[來源 §20](SOURCE_REGISTRY.md#20-m1-price-1tpex-兩股單日價格來源與准入)。原§9／15的DB行情／來源gate保留；memory價格不替它們取得准入或保存驗收。

### 25.1 具名操作與同股／同截止契約

使用者明示研究截止2026-10-05後，在「櫃買官方單日行情」按「載入 10/5 官方行情」。`POST /stocks/{exchange}/{symbol}/prices/capture?as_of=2026-10-05` 使用空object body；每程序僅首次合法明示POST可有界取得1份官方CSV，從3105切到6488用同process cache。普通GET／重複POST／切股不增加外網，失敗cache不自動retry，import不能自動取得。精確啟用值及外部policy pins見[開發入口](development-baseline/README.md#m1-price-1-單日價量的記憶體驗證入口)。

`price_memory` 的 `stock-price-memory/m1-v1` 與原DB路徑雙軌；source／版本／完整性、同symbol／asof有效才接headline、單日OHLC／成交量圖與新價格面板，三處使用同一股／日。預設asof不為新價格前移；明選2026-10-02或「最新資料」返回既有default10/02時，10/05 memory不可滲入，漲跌仍待核實。沒有其他cutoff歷史取得或較早／未來fallback。

Memory typed契約明示TWD，正面wrapper身分檢核依來源§20.1；其他unknown市場不外推。價格為元／股、成交額為TWD元，成交量依[單位契約](UI_COPY_SPEC.md#103-張零股)顯示精確張；source details保留canonical股及金融原字串。quote-date、request開始／capture UTC、source／policy／body／receipt SHA與署名可追溯；publication／first available／revision未知，非PIT。bar `id`／`raw_payload_id`／`ingestion_run_id` 為null，不偽裝DB記錄。

### 25.2 已接受操作與未驗界線

Root獨立核官方CSV全結構、兩股12個金融cell及API／chart／audit精確張；3105與6488的headline、價格面板及chart同stock／day。真正native日期3次ArrowUp→套用→載入→3105 audit／chart table→同cutoff6488→窄版audit／chart table→最新資料default10/02，全為isTrusted；default與explicit10/02都不滲入10/05。GET／重複POST兩股同cache、0額外source，DB tables preserved=true及guards0已核。

桌面1277×924、client1262無page overflow；窄版390×844、client375／page375，canvas305有真resize、SHA原列305無overflow，780寬chart table在303寬local scroll容器。這是具名兩股與控制的有限桌面／窄版接受。輔助typedkeypress／type ACK未改日期、root Python引號SyntaxError exit1，以及獨立CSV ordinal混用assert exit1均保留原task；後續具名native與修正exit0另核，不把輔助ACK當操作通過。

本批core+1／dependency+1、stall0；loader／validator修正與必要UNIT回歸屬同批，不另算可靠性batch。UNIT-LOTS-1前置core0／dep0、當時stall1另報。必要tests及owned服務／page清理由[開發入口](development-baseline/README.md#m1-price-1-單日價量的記憶體驗證入口)詳述；清理的PTY rawexit1不改成驗收exit0。

本server catalogue及10/02是synthetic，只有official10/05單日價格為actual；只存memory，重啟須重載。沒有正式資料目錄、DB保存／跨程序、backend full、MA20／MA60／trend、完整M1／M2／M3、研究條件／Signal／Plan或PIT驗收。MA20／趨勢仍缺20／21真實歷史close及對應日曆，index11391不能作個股價格；下一核心及其待滿足條件見[ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)。

## 26. M2-FOCUS-LOTS-1：精確成交張數關注與同截止往返（有限接受）

**已有限接受 TPEx 3105穩懋／6488環球晶、選定來源日2026-10-05的成交張數關注、actual API與下述具名操作。** 版本 `price-lot-focus/m2-v1`；只採[來源 §20](SOURCE_REGISTRY.md#20-m1-price-1tpex-兩股單日價格來源與准入)已准入的單日價格，沒有新增市場、日期或可信排名。本輪 fresh 觀測與 M2 consumer 用途見[§20.4](SOURCE_REGISTRY.md#204-m2-focus-lots-1-同來源的本輪觀測與採用)；§12／13官方事件與§25 M1歷史界線保留。

### 26.1 明選條件、精確比較與來源完整性

`GET /api/focus/price-lots?as_of=YYYY-MM-DD&min_lots=...` 與明示 `POST /api/focus/price-lots/capture` 使用相同 query，client POST body為空object。兩參數必填；缺值、無效日期或非法門檻回HTTP422，不取得來源。`min_lots` 必須是最長20字元的非負ASCII十進位字串，整數部為 `0` 或無前導零的正整數，小數可有1～3位；不接受正負號、逗號、空白、科學記號、尾點或第四位小數。換算後canonical股數不得超過 `9223372036854775807`，即 `9,223,372,036,854,775.807` 張；`0`、`0.001`與`20000.000`可表達精確門檻。

回應保留原 `min_lots` 字串，另給canonical `min_shares`；後端以精確整數股比較，前端以canonical股字串長度與字典序重算，不經Number或小數除法。成交量日常主值為精確張，原股留稽核；價格／成本仍元／股，既有庫存的整數 `unit + quantity` POST不改，單位規則見[UI §10.3](UI_COPY_SPEC.md#103-張零股)。

來源範圍須恰為兩個已核exact名稱的TW／TPEx普通stock、無ETF分類，typed TWD gate仍依§20.1。`reads` 按3105／6488給兩股memory讀值；available前須各有同股／同cutoff的完整價格、shares單位、canonical成交股數、可追溯provenance，而且兩股provenance一致。前端再驗scope、版本、全部reads、候選集合、數量與固定detail URL；即使沒有候選仍驗兩股reads。不合格不拿legacy、其他日期、較早值或原件片段補數。

每股最多一張卡，依代碼升序；item帶 `volume_exact`、精確 `volume_lots`、原門檻／canonical股門檻、`reason=volume_at_least_min_lots`、來源日／版本與固定個股URL。主理由為成交量達門檻，不推論資金流向、前日漲跌或研究結論。

### 26.2 真零、來源不足與取得生命週期

只有 `status=available`、兩股完整來源與候選重算均合格時，`count` 才是候選數；未達門檻的合法結果為 `count=0`／`items=[]`。未載入、有效但不支持的日期、身分或來源拒用為 `status=unavailable`／`count=null`／`items=[]`，另給reasons，不把空清單當真零。`can_capture` 只在來源可合法首次取得時開放；不支持2026-10-02，也不以10/05補該日。

普通GET與import不送外網；首次合法明示capture仍沿同一TpexPriceStore／固定policy及body pins，每程序最多1個bounded GET，重複POST、切股、讀取與門檻變更共用cache，失敗不自動retry。表單draft只在「套用條件」提交後改URL／query；查詢與capture結果依原 `as_of/min_lots` key保存，無舊結果placeholder或window-focus來源refresh。本輪 actual 採root新GET所持的**同程序 preloaded Store**供真router／UI讀取，後續stock與focus POST只是cache再用，不冒稱本輪native首次POST才取得外網。check fixture與preloaded服務界線見[開發入口](development-baseline/README.md#m2-focus-lots-1-精確張數關注的記憶體驗證入口)。

### 26.3 固定個股路徑與返回原字串

detail固定 `/stocks/TPEx/{symbol}`，query只有 `as_of`、`from=price-lots`、`focus_as_of`、`focus_min_lots`，進入同cutoff M1。返回只接受這四個參數各恰一次、沒有未知參數、兩日期有效且原門檻合法，固定組成 `/?as_of=原focus_as_of&min_lots=原focus_min_lots#price-lot-focus-title`，由URLSearchParams編碼；不接受自由return URL。個股內更改cutoff仍保存原關注條件，返回保留 `20000.000` 的尾零；非法或重複參數不猜原條件，回既有個股入口。原官方事件返回仍用其既有契約。

### 26.4 已接受操作與未驗邊界

Root以本輪同程序真原件核兩股12金融欄、actual focus／M1 API與以下結果；原股及唯一金融值仍以來源§20為權威，不另複製金融表。

| 明選來源日／最小張數 | 已接受結果 |
| --- | --- |
| 2026-10-05／`20000` | 只3105，48,127.911張；同cutoff個股→返回20000。 |
| 2026-10-05／`10000` | 3105／6488依code順序，6488為18,982.607張；兩股同cutoff往返。 |
| 2026-10-05／`50000` | available、count0，兩股原件合格後的真零候選。 |
| 2026-10-05／`48127.911`與`48127.912` | actual API分別count1／count0，精確零股門檻無捨入。 |
| 2026-10-02／合法門檻 | unavailable、countnull，候選未知，不借10/05價格。 |

1277寬桌面具名click／submit已核20k／10k兩股往返；390寬窄版另核50k真零與10/02候選未知。修wrap後以可信focus＋Enter展開3105來源details，docWidth375，原股48127911、data row205、門檻20000000股及完整body／receipt SHA可讀；進M1顯示615元／股、48,127.911張、canvas305，再原生返回 `20000.000` 且表單／URL原字串一致。初版長SHA展開溢出438已退修，補驗後page375；屬同核心批次必要退修。Orca fill的input／change事件為isTrusted=false，只是draft設定；可信click／submit／Enter產生的click另核，不稱trusted文字輸入。

兩個stock POST、兩個focus POST及重複GET同cache零新增外網；M1 default／explicit10/02不滲10/05已核。核心操作+1＝真張數關注與同截止往返；dependency0（既有來源複用）、reliability0、stall0。必要checks與owned服務清理另見開發入口，原非零工具／PTY收據保留原task。

本次只含已核兩股與選定10/05單日；catalogue／10/02仍synthetic，沒有正式DB、磁碟保存／跨程序、離線replay、PIT、全市場、排名／題材、MA20／trend、研究條件／Signal／Plan或完整M1／M2／M3驗收。取得時間不代表發布或首次可得；原件只存本次process memory，owned服務結束已釋放。下一日內O/C方向條件尚未實作／驗收，依[ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)，不稱前日漲跌或趨勢。

## 27. M2-FOCUS-DAY-MOVE-1：單日方向關注與完整條件往返（有限接受）

**已有限接受TPEx3105穩懋／6488環球晶、選定來源日2026-10-05的精確成交張門檻＋單日O/C方向、actual API及下述具名往返操作。** 現行consumer為 `price-lot-focus/m2-v2`；§26是m2-v1當時的驗收快照，現行方向與返回契約依本節。Fresh觀測／用途／版本見[來源 §20.5](SOURCE_REGISTRY.md#205-m2-focus-day-move-1-同來源的新觀測與方向-consumer)，§20.1固定policy／pins與§20.2金融表保持。M1仍缺20／21真歷史close／日曆、策略inputs／time gate，單日操作不放行MA／trend或研究判定。

### 27.1 三個條件與精確單日比較

`GET /api/focus/price-lots` 與明示 `POST /api/focus/price-lots/capture` 沿既有 `as_of/min_lots`，新增 `day_move=all|up|down|flat`，省略時為all；對應「全部／收高於開／收低於開／平收」，比較當日收盤與當日開盤，不是前收盤漲跌。日期／門檻仍必填；三條件任一重複、日期／門檻／方向非法，在capture前HTTP422。Client POST body仍空object。門檻20字元／最多三位小數／int64 canonical股與原尾零依§26.1、[UI §10.3](UI_COPY_SPEC.md#103-張零股)，不改穩定換算。

O/C取每股 `source_fields`「開盤／收盤」原字串，各最長64字元，只接受無正負號、前導零、空白、科學記號或尾點的正ASCII十進位價格；可有小數，合法值必須大於0。後端以Decimal比較，前端以整數部分長度／字典序與補齊小數字串獨立重算，不經JS Number。收大於開為up、收小於開為down、同值為flat；缺失／無效／零價格不猜方向。

候選同時達精確股門檻及所選方向；all只略過方向篩選，仍核每股O/C並顯示實際up／down／flat。每股一張卡、依code升序，item保留 `volume_exact/volume_lots/min_lots/min_shares`，新增實際 `day_move/open_exact/close_exact`；固定兩理由 `volume_at_least_min_lots` 加 `close_above_open|close_below_open|close_equal_open`。前端重算兩股reads、全部候選、原值／理由與固定URL，不只驗顯示卡片。

### 27.2 來源完整性、真零與cache

恰為已核兩股普通stock／TPEx／TWD、同股／同截止完整原件及一致provenance後才可available。任何O/C缺失／invalid為 `unavailable/count=null/items=[]`，理由 `price_focus_direction_unavailable`；未載入、來源拒用及不支持10/02依既有原因拒用。即使count0，也先驗兩股完整reads及實際方向；只有available0才是此範圍真零，不以空清單補0。

首次取得與cache沿來源§20.1：每程序最多1 bounded GET、3MiB／30秒／redirect0／retry0；普通GET／import零外網、失敗不自動retry。本輪actual在同程序已驗held Store供真router／UI，source1／runner0，後續focus／stock POST只再用cache。Draft在「套用條件」submit後才改URL，query／capture結果key包含 `as_of/min_lots/day_move`，不混方向，不以舊placeholder或window-focus刷新來源。

### 27.3 同截止研究與安全返回

固定detail為 `/stocks/TPEx/{symbol}`，query是 `as_of/from=price-lots/focus_as_of/focus_min_lots/focus_day_move`，進同cutoff M1。返回白名單只有上述五key，前四各恰一次，`focus_day_move`最多一次且合法；legacy省略方向按all。日期有效且 `as_of` 必須等於原 `focus_as_of`，原門檻合法，才由URLSearchParams固定組成 `/?as_of=原日期&min_lots=原字串&day_move=原方向#price-lot-focus-title`。

返回保留 `10000.000/20000.000` 尾零及方向，不是自由return URL。未知key（含next）、重複key、錯日期／門檻／方向或研究截止與原日期不一致時，拒原條件返回，使用本地 `/stocks`，不導向外部。今日頁重複條件不啟query；原官方事件返回契約保持。

### 27.4 已接受actual結果與具名操作

Root以本輪fresh原件獨立核actual HTTP及以下結果；O/C與唯一金融值由來源§20管理，不另建金融表。

| 明選來源日／min_lots／day_move | 已接受actual API結果 |
| --- | --- |
| 10/05／`10000.000`／all、up、down、flat | all依code為3105／6488；up只3105；down只6488；flat為available0。 |
| 10/05／`20000.000`／all、down | all只3105；down為available0。 |
| 10/05／`48127.911`→`48127.912`／up | count1→0，精確零股門檻無捨入。 |
| 10/05／`18982.607`→`18982.608`／down | count1→0，精確零股門檻無捨入。 |
| 10/05／`50000`／all | available0。 |
| 10/02／合法條件 | unavailable／countnull，不借10/05值。 |

另核6組非法query各GET／POST共12次422、focus POST2／stock POST2 cache再用及M1 default10/02不滲10/05。1277桌面與390×844窄版具名native click／submit／link／back為isTrusted=true；up／down兩股M1同cutoff往返保留 `10000.000` 與方向，20k／all返回 `20000.000/all`；all2、flat0及10/02未知actual UI已核。重複URL未query，detail的外部next拒用回本地/stocks；窄版source details經native展開，doc375／details305／canvas305。

Orca select／fill的input/change=false只設draft；ArrowDown no-event、未submit點擊不算完成，實際定位後click／submit另核。原工具／編碼／輔助觀測收據保留原task，後正面結果不覆寫原exit。必要Python10／Node28src noEmit、110helper／44SSR及owned清理見[開發入口](development-baseline/README.md#m2-focus-day-move-1-單日方向與完整返回的記憶體驗證入口)；source1／runner0、各guard0、DB preserved=true與額外檔案0已核。

本輪core+1／dep0（複用既有來源）／reliability0／stall0；必要退修／重驗同核心批次。原件只process memory，服務結束已釋放；catalogue／10/02仍synthetic，無正式DB／磁碟保存／跨程序、PIT、全市場／排名／題材、MA／trend、研究／Signal／Plan或完整M1／M2／M3驗收。下一精確成交金額條件仍待新root來源及具名操作gate，見[ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)。

## 28. M2-FOCUS-TURNOVER-1：精確成交金額與四條件往返（有限接受）

**已有限接受TPEx3105穩懋／6488環球晶、來源日2026-10-05的精確成交張門檻＋O/C方向＋TWD成交額、actual API與具名往返。** 現行consumer為 `price-lot-focus/m2-v3`；§26／27各保留m2-v1／v2歷史，穩定張換算及O/C比較不改。本輪fresh准入／capture見[來源 §20.6](SOURCE_REGISTRY.md#206-m2-focus-turnover-1-同來源的新觀測與成交額-consumer)，固定policy／pins與唯一金融表依§20.1／20.2。M1的20／21真個股歷史close／日曆、strategy inputs／time／execution gate仍缺，不由單日操作放行研究。

### 28.1 四條件、精確成交額與三理由

沿 `GET /api/focus/price-lots` 及明示 `POST /api/focus/price-lots/capture` 的 `as_of/min_lots/day_move`，新增 `min_turnover`，省略為字串 `0`；client POST body仍空object。門檻必須是canonical非負ASCII整數字串，最長19字元／上限 `9223372036854775807`，單位TWD元。明示空值、前導零、正負號、小數、科學記號、空白、逗號、Unicode數字與溢位拒收。四條件重複／非法或API未知query key均於catalogue查詢及capture前HTTP422；首頁非法／重複條件不發focus request、讀取／capture按鈕disabled。Shared `q` 及官方事件返回保持既有用途。

回應與item保留原 `min_turnover`，item帶 `turnover_exact`；元值以canonical int64字串／整數比較，不經JS Number。先驗兩股完整reads、同股／同截止、TPEx普通stock／TWD、完整一致provenance及O/C；再驗每股 `turnover_exact` 為合法精確字串、等於source_fields「成交金額」，`turnover_status=available` 且 `turnover_reason` 明示null。缺值、壞字串、狀態未知／unavailable、缺reason或原值衝突，為 `price_focus_turnover_unavailable`／count=null／items=[]，不能補0或跳過不合格股。

原件明確0且完整gate合格可以available；本輪此來源兩股成交額均為正，來源零只由synthetic邊界驗證。完整reads須在filter前驗，即使最後零候選仍核兩股；只有available／count0才是此範圍真零。候選須同時達股門檻、成交額門檻與所選方向；all不略過實際O/C驗證。每股一張卡、code升序，固定三理由 `volume_at_least_min_lots`、`turnover_at_least_min_turnover`、實際 `close_above_open|close_below_open|close_equal_open`。前端獨立重算全部reads／候選／理由／URL，不只驗顯示卡片。

### 28.2 同截止、完整原條件與安全返回

detail固定 `/stocks/TPEx/{symbol}`，query為 `as_of/from=price-lots/focus_as_of/focus_min_lots/focus_day_move/focus_min_turnover`，進同cutoff M1。返回白名單僅這六key；前四各恰一次，方向／金額各最多一次，legacy省略分別為all／0。日期有效且研究as_of等於原focus_as_of、兩門檻及方向合法後，URLSearchParams固定組成 `/?as_of=原日期&min_lots=原字串&day_move=原方向&min_turnover=原金額#price-lot-focus-title`。

日期、張門檻尾零、方向與成交額字串完整往返。未知key（含next）、duplicate、負值或其他非法值、不一致截止均拒原條件返回，fallback本地 `/stocks`，不訪外域。首頁shared q相容與原官方事件往返不改。Draft在「套用條件」submit後改URL；query／capture結果key包含四條件，無舊placeholder／window-focus來源refresh。普通GET／條件變更與重複POST共用同程序Store，固定每程序1 GET／3MiB／30秒／redirect0／retry0，失敗不自動retry。

### 28.3 已接受actual與具名操作

Root新原件與真HTTP已核以下結果；來源O/H/L/C／股／元唯一值仍見§20.2，不重建金融表。

| 10/05條件（min_lots／day_move／min_turnover） | 已接受actual API結果 |
| --- | --- |
| `10000.000/all/25000000000`、`10000.000/all/20000000000` | 分別只有3105、依code兩股。 |
| `10000.000/down/25000000000` | available0。 |
| up／`29694939981`→`29694939982` | 3105等額成立→加1元真0。 |
| down／`22887612060`→`22887612061` | 6488等額成立→加1元真0。 |
| all／`0`、all／int64 MAX；legacy省略金額 | 0為兩股、MAX為真0；省略採0。 |
| 10/02合法條件 | unavailable／count=null，不借10/05值。 |

另核16次invalid GET／POST422，focus POST2／stock POST2同cache、extra GET0，stock default及explicit10/02不滲10/05。Root腳本首exit1是在前段9cases／非法／POST完成後誤讀default stock頂部as_of；修正overview位置後remaining2及receipt exit0，原exit保留，不稱重取來源。

1277×924桌面doc1262：原生click／submit套20e9兩股，3105同cutoff link／back保留四條件。390×844窄版doc375、card rect305／client303、開source details275／canvas305：trusted Enter／submit驗down25e9真0、6488等額／加1元真0、down20e9→6488→返回原日期／`10000.000/down/20000000000`；10/02顯候選數未知。Click／Enter／submit／link／back均isTrusted=true，fill／select的input/change=false只設draft；初offscreen背景click不當通過，scroll至可見後才接受，原選擇器assert與後正面核對分報。非法duplicate／negative及next首頁focus request0／disabled／card0，stock外域next無原條件link且只回本地/stocks。

本輪core+1／dep0（既有來源）／reliability0／stall0，wrap及測試退修同批。必要驗證、synthetic尺寸與owned清理由[開發入口](development-baseline/README.md#m2-focus-turnover-1-精確成交金額與四條件返回的記憶體驗證入口)管理。只process memory、owned服務已結束，catalogue／10/02仍synthetic；未驗正式DB／磁碟保存／跨程序、full suite／production build、全市場／PIT／MA／trend／研究／Signal／Plan或完整M1／M2／M3。下一本日振幅條件待新輪gate與actual，見[ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)。

## 29. M2-FOCUS-DAY-RANGE-1：本日振幅與五條件往返

**程式、10/06新來源准入、actual API及可信桌面／窄版具名操作已有限接受；B1 core+1／dep+1／reliability0／stall0。** Consumer `price-lot-focus/m2-v4`；§26～28保留m2-v1／v2／v3當時範圍。新來源與金融值由[來源 §20.7](SOURCE_REGISTRY.md#207-m2-focus-day-range-1新日期來源准入與本日振幅-consumer)管理；10/05固定tuple與§20.1～20.6歷史不覆寫。只有TPEx3105穩懋／6488環球晶、stock／TWD及明確核准10/05、10/06兩日期，非任意新日期或自動最新。單日資料不解除M1的20／21真歷史close／日曆、strategy inputs／time／execution gate。

### 29.1 原百分比、精確比較與完整來源gate

沿 `GET /api/focus/price-lots` 與明示 `POST /api/focus/price-lots/capture`，五條件為 `as_of/min_lots/day_move/min_turnover/min_range_pct`，POST body仍空object。新百分比門檻省略採原字串 `0`；明示空值非法。只接受非負ASCII十進位原字串，整數部分為0或非零開頭、最多三位小數、總長≤20字元，保留尾零；不接受符號、前導零、科學記號、空白、逗號、Unicode數字或超限。千分之一百分點scaled int64≤`9223372036854775807`，故原門檻最高`9223372036854775.807`%。API未知key、重複或非法五條件均在catalogue／capture前HTTP422；首頁非法不查focus，讀取／capture停用。原張／股及元／股口徑不改。

本日振幅為 `100×(H−L)/O`。O/H/L取原件「開盤／最高／最低」十進位字串，各≤64字元、非負標準形狀並實際正值，對齊共同小數位後轉Python int／JS BigInt；須`H≥O≥L>0`。候選比較精確使用 `100000×(H−L)≥minimum_scaled×O`，不先除法、轉JS Number或四捨五入。不要求振幅為正：合法H=L可得0；門檻0仍須完整O/H/L，missing、壞形狀或矛盾不得補0。

先核兩股完整reads、同股／同截止、source tuple／provenance一致、canonical成交股數、原O/C、TWD成交額/status/reason/raw一致及O/H/L，才filter。振幅不合格為`price_focus_range_unavailable`／count=null／items=[]，不跳過壞股；all與最後零候選也不略過完整gate。只有available／count0是此範圍真零。回應與item保留原min_range_pct，item新增high_exact／low_exact；原open_exact／close_exact仍取原值。

每股一張卡、code升序，同時滿足張門檻、成交額、方向與振幅。固定四理由順序為`volume_at_least_min_lots`、`turnover_at_least_min_turnover`、實際`close_above_open|close_below_open|close_equal_open`、`range_at_least_min_range_pct`。前端獨立重驗全部reads、精確候選／理由／欄位／URL，並非只驗顯示卡。振幅百分比可half-up至三位小數、標「約」，僅供閱讀；候選與邊界一律精確比較。

### 29.2 同截止研究、五條件返回與兩日期隔離

固定detail `/stocks/TPEx/{symbol}`，query白名單為`as_of/from/focus_as_of/focus_min_lots/focus_day_move/focus_min_turnover/focus_min_range_pct`；前四各恰一次，後三各最多一次，legacy省略分別all／0／0。研究as_of須等於focus_as_of；門檻與方向均合法後，返回固定本地 `/?as_of=原日期&min_lots=原字串&day_move=原方向&min_turnover=原金額&min_range_pct=原百分比#price-lot-focus-title`。日期、張與百分比尾零、方向、金額完整保留；未知key（含next）、duplicate、非法值或截止不一致拒原條件返回，只fallback本地/stocks。Shared q與原官方事件往返保持。

Draft經「套用條件」submit後才改URL；query／capture key含全部五條件，無placeholder／window-focus來源refresh。每程序只能採一份所選日期原件；兩日期各自需要匹配外部policy pins與immutable tuple，10/06不得給10/05、default或explicit10/02。新服務用10/06 pins時，10/05為external pins mismatch，不能聲稱另持有歷史body。Ordinary GET、切條件、切股與重複POST共用Store、不新增source GET；失敗不retry。新來源的root先取得觀測與後pure builder准入見§20.7，不將cached UI操作說成fresh GET。

### 29.3 已核actual API與有限原生操作

本輪actual是**2026-10-06**，不是舊10/05 fixture的4／4.5／5%預期。Root同程序held原件／新tuple供真router，明選`10000.000/all/0`時：

| min_range_pct／方向 | 已核actual API |
| --- | --- |
| 0、4／all | 依code兩股。 |
| 6.000／all、6.000／up | 僅6488。 |
| 10／all、6／down | available0。 |
| 5.691→5.692／all | 兩股→僅6488。 |
| 9.787→9.788／all | 僅6488→available0。 |

兩股M1 samecutoff六金融值、四理由與五條件原字串、cached POST零新增GET、精度／duplicate GET及POST422已核。Blank／default10/02、explicit10/02與10/05不洩10/06；10/05 external pins mismatch與舊接受範圍分開。DB preserved=true、server／client guards皆0；router載入前importlib.util與runner NameError後更正，body仍held、未重取，原非零收據留task。

先前可信桌面／窄版submit、link／back及拒收操作曾卡在外部native delivery。Footer10/05文案退修與必要check已通，actual render正確；當時三owned Orca pages的click／keypress／inserttext只有ACK，events空、值／React／URL未改，未接受原生操作。當時三頁皆exact closed、tabs0；readonly未證明可用且符合不改runtime／不落盤的不同native路徑，等待外部delivery／provider或真正window聚焦等變化，未斷言唯一原因。

續驗由root有限接受：外部Orca從1.4.220更新為1.4.221，非root執行更新、不宣稱因果修復；同原root／roles、同10/06 held body，source_request_count1／runner追加GET0／DB preserved／entry guards0不變。桌面1277及窄版390以真正座標mouse move／down／up產生trusted click／submit，不用DOM click／radius。Range6.000只6488，個股→研究條件同cutoff10/06→safe back保留全部五原條件，包括min_lots=10000.000、day_move=up、min_turnover=10000000000、min_range_pct=6.000；四理由與source detail窄版換行正確，document client／scroll375／375。

桌面range10是真0、0是兩股，5.691兩股／5.692只6488已真正操作核對；native inserttext6.0001產生trusted beforeinput／input，三個price buttons disabled、cards0／focus query0。10/02配0.000仍missing／unknown，非真0；duplicate range URL亦cards0／read及capture disabled／focus query0。合法stock path帶foreign next只暴露本地fallback `/stocks`，無focus-return／foreign link；最後額外fallback native click僅ACK、無DOM event，未完成該追加case，不稱拒收返回click已通。有效五條件safe return早已真正native通過；上述href／零query觀測及既有helper／API拒收證據支持安全契約。

新source／tuple→Store→真router／可信具名操作解除old pins依賴並交付有限核心，root計數core+1／dep+1／reliability0／stall0；B1有限核心驗收已接受。沿原root／三child完成文件review與版本封存，不new round／BOOT、追加quote GET未核定，feature freeze／index／Git／master merge／next coordinator均pending。四owned pages皆closed／tabs0；兩owned RAM服務與compiler已停止、ports無listener，held原件memory於Python process absence釋放；清理後驗0與Ctrl+C rawexit1分報。Edge profile超cap後停止且兩清理請求被automatic review拒絕，殘留NO-RETRY／exact path及服務範圍只詳見[開發入口](development-baseline/README.md#m2-focus-day-range-1-新日期與五條件返回的記憶體驗證入口)。行情／receipt僅memory，profile metadata是額外artifact；未驗保存／跨程序、full suite／production build、全市場／PIT／MA／trend／研究／Signal／Plan或完整M1／M2／M3。

## 30. M2-FOCUS-STOCK-SCOPE-1：三股關注與同截止往返

**TPEx普通股支援2→3、actual計算／API及可信桌面／窄版操作已有限接受。** 新增5347世界，與3105穩懋／6488環球晶在同一2026-10-06來源日使用；consumer `price-lot-focus/m2-v5`、projection `stock-price-memory/m2-stock-scope-v1`。新身分、政策、原件、金融值與兩次觀測只由[來源 §21](SOURCE_REGISTRY.md#21-m2-focus-stock-scope-1三股來源准入)管理；§25～29保留兩股當時驗收與舊tuple。單日scope擴大不解除M1歷史／日曆／strategy／time／execution gate。

### 30.1 三股完整gate與既有五條件

沿§29的精確張／canonical股、O/C方向、int64 TWD成交額、原百分比≤3小數／scaled int64及OHL整數交叉比較。五條件仍 `as_of/min_lots/day_move/min_turnover/min_range_pct`；沒有第六個URL條件，內部policy選擇不讓使用者混拼scope。Default10/06採新三股tuple；explicit舊10/06 m1 policy及10/05舊兩股tuple保留原immutable pins與原scope，不把第三股灌入舊policy。

Filter前必須取得**所選policy的全部普通股reads**，逐股核code／name／TW-TPEx／stock／TWD／空ETF分類、同cutoff／tuple／provenance及全部required金融原字串。三股scope有一股缺、壞、衝突便unavailable／count=null／items=[]，不能跳過壞股或縮回兩股。All與最後零候選仍經完整gate；available/count0才是此範圍真零。Raw source詳情可回指新body／receipt／policy與各股18個原欄。

候選仍每股一張卡、code升序、四理由固定順序且同股去重；前端獨立重驗reads／候選／reason／欄位及URL，不僅驗卡片。Unknown或malformed scope於StockOverview安全拒用，包含六個malformed／unknown SSR案例，避免未驗scope被join或呈現；本次必要防錯屬同一核心批次，不另計可靠性增量。

### 30.2 Actual API與精確邊界

Root live router核九組actual案例，每次都先驗三股原件及同provenance；全零門檻／all得到依code排序三股。新第三股的具名邊界為：

| 原條件或邊界 | 已接受結果 |
| --- | --- |
| 20000.000張／up／成交額0／振幅5.691 | 只有5347。 |
| 上述振幅改5.692 | available0。 |
| 5347成交張數等額門檻／增加0.001張 | 5347／available0。 |
| 5347成交額等額門檻／增加1元 | 5347／available0。 |
| 0張／all／成交額0／振幅6.000，再改10 | 6488／available0。 |

等額原值見[來源 §21.2](SOURCE_REGISTRY.md#212-本輪觀測原件與三股金融值)。All3 stock reads、四理由、五原字串、samecutoff detail、cached focus POST及三股stock POST均核通；Store1／runner新增GET0、preloaded=true、DB preserved／全部guards0。Default10/02與舊10/05不洩第三股新原件的API隔離已核；未將這些API證據升格為本輪未跑的native10/02、6.0001或額外invalid fallback案例。

### 30.3 桌面／窄版可信往返

本輪唯一owned Orca page；桌面1277×900、窄版390×844，以真正座標mouse move／down／up得到 `isTrusted=true` 的click／submit、5347連結、原件summary展開與返回，實際URL／卡片均改變。Draft fill／select的 `isTrusted=false` 只屬條件準備，不稱trusted typing。

桌面與窄版均以原五字串 `2026-10-06 / 20000.000 / up / 6615109776 / 5.691` 套用，唯一5347→同cutoff個股→展開該股18原欄及body／receipt／policy→返回，五字串含尾零完整保留。Safe local URL與拒收契約仍沿§29.2；不增加新的返回條件。

窄版另以5.692取得真零、5.691恢復一股，再以 `0.000/all/0/0.000` 得三股code順。開啟raw details時桌面scrollWidth1262≤1277，窄版375≤390；來源SHA及原欄換行無page水平溢出。這些是已接受的具名操作，不含未執行的其他native案例。

### 30.4 完成與驗收界線

Root接受B1 coreoperation+1／selected identity-source scope dependency+1／reliability0／stall0。唯一page已exact closed、tabs0；本輪API／preview／compiler已停、listeners none、第二原件memory釋放，測試及原exit／清理收據見[開發入口](development-baseline/README.md#m2-focus-stock-scope-1-三股範圍的記憶體驗證入口)／原task。舊day-range NO-RETRY profile及其他歷史資源不納入本輪清理。

前輪source17與三股功能驗收已接受，DOC review／freeze／七涉及scope索引及qualified coverage／exact commit與另准master merge `50c228d` 已完成；§30保留該範圍，後續四股見[§31](#31-m2-focus-stock-scope-2四股關注與同截止往返)，現行五股見[§32](#32-m2-focus-stock-scope-3五股關注與同截止往返)。未驗磁碟保存／跨程序、full suite／production build、全市場／PIT／20／21歷史close／完整日曆／MA／trend／研究／Signal／Plan或完整M1／M2／M3。既有有效證據沿用，不因換角色重跑。

## 31. M2-FOCUS-STOCK-SCOPE-2：四股關注與同截止往返

**普通TPEx支援3→4的來源／計算、actual API及可信desktop／窄版操作已有限接受。** 新增5274信驊，scope為3105／5274／5347／6488，來源日2026-10-06；consumer `price-lot-focus/m2-v6`、projection `stock-price-memory/m2-stock-scope-v2`。來源identity／policy／raw金融值只由[來源 §23](SOURCE_REGISTRY.md#23-m2-focus-stock-scope-2四股來源准入)管理；§25～30保留舊兩股／三股範圍與版本，本節不解除M1多日／日曆／strategy／time／execution缺口。

### 31.1 四股完整gate與五條件

精確張／canonical股、O/C、int64 TWD元與振幅仍沿§29.1／§30.1。Default10/06採新四股 `.2` tuple；explicit `.1` 三股、更早10/06與10/05兩股tuple保持自身scope／pins，不把第四股灌入舊policy。公開條件仍 `as_of/min_lots/day_move/min_turnover/min_range_pct`，不增加第六個URL條件或讓使用者混拼policy。

Filter前驗所選policy全部required reads、逐股身分／金融原字串、同cutoff／tuple／provenance。任一股missing／invalid／conflict時unavailable、count=null、items=[]；不能跳過壞股、縮scope或將未知當0。Available/count0才是四股完整gate後的真零。每股一張卡、code升序、四理由固定順序去重，前端仍獨立重驗候選／理由／raw reads與safe local五條件URL。

### 31.2 Actual API與精確邊界

Root actual API八組案例已接受，含全四股code順、四股reads／samecutoff、五cached POST及舊日期隔離；四股18欄的身分前三欄外側空白正規化比對、其餘60原字串與24金融值核對見來源§23.2。下表振幅兩案的direct API成交額條件為0元；§31.3具名native往返另用3627465565元，候選結果相同。5274具名inclusive邊界為：

| 條件／邊界 | 已接受結果 |
| --- | --- |
| 10/06、0.000張、down、0元、振幅5.327 | 3105＋5274，依code排序。 |
| 上述振幅改5.328 | 只有3105。 |
| 5274張門檻188.693／188.694 | 5274在等額包含，增加0.001張排除。 |
| 5274成交額3627465565／3627465566元 | 等額包含，增加1元排除。 |
| 0.000張／all／0元／振幅10 | available/count0／items=[]。 |

All4 reads、四理由同股去重、五原字串與samecutoff detail已核；preloaded Store1／runnerGET0、guards0／DB preserved=true。Default、10/02及舊10/05 missing12的API隔離已核，未將此API邊界升格為未執行的native歷史日期案例。

### 31.3 桌面／窄版具名可信操作

1277×900 desktop與390×844窄版均以真正mouse click／submit套用下列五原字串：`2026-10-06 / 0.000 / down / 3627465565 / 5.327` 得3105＋5274；百分比改5.328得3105，再恢復5.327，點5274→同cutoff個股→raw summary展開→返回。Click／submit／link／summary／back的isTrusted=true、actual URL與卡片變化已核，返回保留全部五字串含尾零；draft fill／select的isTrusted=false只屬設定，不稱trusted typing。

窄版另以 `2026-10-06 / 0.000 / all / 0 / 10` 得真零，再以 `2026-10-06 / 0.000 / all / 0 / 0.000` 恢復四股code順。Desktop關注頁scrollWidth1262≤1277；窄版關注、5274詳情與raw展開375≤390，無水平溢出。Source欄位／SHA仍可追溯與換行；safe local返回及拒收契約不改。

### 31.4 完成與未驗範圍

Root接受同一B1 source13與核心驗收：coreoperation+1／selected identity-source scope dependency+1／reliability0／stall0。唯一page已closed／tabs0，owned服務及compiler已停、ports none、held raw釋放；測試與raw exit／清理分報由[開發入口](development-baseline/README.md#m2-focus-stock-scope-2-四股範圍的記憶體驗證入口)管理。該版source13＋DOC8 freeze21／七scope索引與qualified coverage／exact commit及正常ff-only master merge `899fa62260e495075cc756ff31869a57df6b3895` 已接受；本節保留四股版本，五股見§32，現行六股見§33。

未驗磁碟保存／跨程序、full suite／production build、全市場／PIT／20／21歷史close／完整日曆、MA／trend／研究／Signal／Plan或完整M1／M2／M3。既有通過證據按範圍沿用，NO-RETRY歷史資源不納入本輪功能清理。

## 32. M2-FOCUS-STOCK-SCOPE-3：五股關注與同截止往返

本節五股版本已合併至本輪starting master；原pending由原task／Git final receipt覆蓋，現行六股見§33，舊操作證據按原範圍保留。

**普通TPEx支援4→5的資料／計算、actual API與可信desktop／窄版操作已有限接受。** 新增3293鈊象，scope3105／3293／5274／5347／6488、source-date2026-10-06；focus `price-lot-focus/m2-v7`、projection `stock-price-memory/m2-stock-scope-v3`。Identity／policy／raw金融值只由[來源 §25](SOURCE_REGISTRY.md#25-m2-focus-stock-scope-3五股來源准入)管理，§25～31保留舊版本的有限範圍。

### 32.1 五股完整gate與既有五條件

沿§29.1的精確張／canonical股、原O/C、int64 TWD元與振幅；default10/06採 `.3`五股，explicit舊 `.2`四股／`.1`三股／更早兩股保持immutable tuples。公開條件仍 `as_of/min_lots/day_move/min_turnover/min_range_pct`，不增加第六條或讓使用者拼policy。

所選policy全部required reads、逐股身分／金融原字串、cutoff／tuple／provenance先gate後filter；任一missing／invalid／conflict時unavailable、count=null、items=[]，不跳壞股或縮scope。Available/count0才是完整五股的真零；每股一張卡、code升序、四理由固定順序去重，前端仍獨立重驗候選／理由／raw reads及safe local五條件URL。

### 32.2 Actual API與精確inclusive邊界

Root actual API10案已接受：全五股code順／90欄原件／30金融值、四理由／sameprovenance；五symbol POST加focus POST共六cached calls不新增GET，default／explicit10/02／舊10/05對3293缺資料已核。Final fresh actual Store sourcecount1／runnerGET1／preloaded=false、DB preserved／guards0；本輪總CSV GET3的觀測及失敗界線見來源§25.2。

| 10/06條件／邊界 | 已接受API候選（code順） |
| --- | --- |
| min_lots1495.462／down，其他門檻0 | 3105＋3293；1495.463只3105。 |
| min_turnover1164617657／down，張與振幅0 | 3105＋3293＋5274；增加1元只3105＋5274。 |
| min_range_pct2.770／down，張與成交額0 | 3105＋3293＋5274；2.771只3105＋5274。 |
| 1495.462／down／1164617657／2.770 | 3105＋3293；振幅改2.771只3105。 |
| 0.000／all／0／振幅10 | available/count0／items=[]。 |

3293 inclusive張／元／振幅皆由原exact值判斷；count0與unknown不混用。同cutoff detail與五個原字串保留已核，不將API舊日期缺資料案例升格本輪未執行的native歷史日期操作。

### 32.3 Desktop／窄版可信往返與真零恢復

Actual desktop **1277×924**、窄版**390×844**均已核 `2026-10-06 / 1495.462 / down / 1164617657 / 2.770` 得3105＋3293，振幅2.771只3105；兩個viewport各自核3293→同cutoff個股→raw summary展開→返回，以上結果不表示兩者操作順序相同。首次load／submit／link／summary／back之isTrusted=true、actual URL／卡片變化已核；draft fill／select只作setup，不稱native input typing。3293原件追溯核data ordinal255（含header行256），返回完整五原字串含尾零。

窄版另以 `2026-10-06 / 0.000 / all / 0 / 10` 真零，改振幅0.000恢復五股code順。FOCUS／detail／RAW OPEN各實測desktop scrollWidth1262≤1277、窄版375≤390，無水平溢出，SHA與來源欄位可追溯／換行。

首個窄版3293 offscreen座標miss只送HTML click、raw assertion失敗，該attempt不接受；explicit visible scroll後coordinate down/up／link的native事件已通。PS quoting／JS splat與CLI help／mouseclick syntax診斷修正後才作有效操作，原收據留task；不寫成產品故障、首跑全過或有效native失敗。

### 32.4 完成、版本與未驗邊界

Root accepted source12／net24911B及核心：coreoperation+1／selected identity-source scope dependency+1／reliability0／stall0。五股source12＋DOC8／freeze20／七scope qualified索引、exact commit及正常ff-only local master merge已接受；收據留原task。Owned page／API／preview／compiler／observer已清、held raw隨process exit釋放；必要checks、rawexit及清理由[開發入口](development-baseline/README.md#m2-focus-stock-scope-3-五股範圍的記憶體驗證入口)管理。

未驗磁碟保存／跨程序、full suite／production build、全市場／PIT、20／21歷史close／完整日曆、MA／trend／ATR／研究／Signal／Plan或完整M1／M2／M3。歷史NO-RETRY資源排除，既有有效證據按適用範圍沿用。

## 33. M2-FOCUS-STOCK-SCOPE-4：六股關注與同截止往返

**普通TPEx支援5→6的資料／計算、actual API與可信desktop／窄版操作已有限接受。** 新增8069元太，scope依code為3105／3293／5274／5347／6488／8069、source-date2026-10-06；focus `price-lot-focus/m2-v8`、projection `stock-price-memory/m2-stock-scope-v4`。Identity／policy／原件金融由[來源 §27](SOURCE_REGISTRY.md#27-m2-focus-stock-scope-4六股來源准入)管理，舊版本有限範圍與金融表保持。

### 33.1 六股完整gate與五條件

沿§29.1精確張／canonical股、原O/C、int64 TWD元及振幅。Default10/06採`.4`六股；explicit舊`.3`五股、`.2`四股、`.1`三股與更早兩股immutable tuples保持。舊兩股backend producer=m2-v5、frontend legacy consumer的m2-v4相容是既有基線，本輪未改producer。公開條件仍`as_of/min_lots/day_move/min_turnover/min_range_pct`，不增加第六條或讓使用者拼policy。

全部required reads、逐股身分／金融原字串、同cutoff／tuple／provenance先gate後filter；任一missing／invalid／conflict仍unavailable、count=null、items=[]，不跳壞股或縮scope。Available/count0才是完整六股的真零；每股一張卡、code升序、四理由固定順序去重，frontend獨立重驗候選／理由／raw reads與safe local五條件URL。

### 33.2 Actual API與精確inclusive邊界

Root actual API10案已接受：全六股108原件欄／36金融值、完整reads／共cutoff／provenance及四理由；六symbol POST＋focus POST共七cached calls不新增source。Default／explicit10/02／舊10/05對8069unavailable已核，不升格未跑的native歷史日期案例。Source修改後final actual Store sourcecount1／runnerGET1／preloaded=false、guards0／disk0／DB preserved；本輪總financial GET3的觀測與失敗界線見來源§27.2。

8069張10796.741 inclusive／10796.742排除、成交額1607943663元inclusive／1607943664排除、振幅4.421 inclusive／4.422排除，方向up均按原exact值核對。Combined結果如下：

| 10/06完整條件（除as_of外） | 已接受API候選（code順） |
| --- | --- |
| 10796.741／up／1607943663／4.421 | 5347＋6488＋8069 |
| 10796.741／up／1607943663／4.422 | 5347＋6488 |
| 0.000／all／0／0.000 | 全六股 |
| 0.000／all／0／10 | available/count0／items=[] |

門檻字串尾零與同cutoff detail／safe返回保留；顯示「約」不替代原值比較，真零≠unknown。

### 33.3 Desktop／窄版可信往返與真零恢復

同一owned page的desktop **1277×924**按lower→8069 detail→raw open→back same五原字串→upper；窄版 **390×844**按upper→lower→8069 detail→raw open→back→upper→true zero→restore。Lower為`2026-10-06 / 10796.741 / up / 1607943663 / 4.421`，upper只改振幅4.422；原五字串含尾零完整返回。8069原件追溯核data ordinal12098（含header行12099）。

21個native click／submit／toggle events均isTrusted=true，含firstload／link／raw／back；draft programmatic fill／select只作setup，不稱trusted typing。Desktop及窄版各實測focus／detail／raw open的scrollWidth1262≤1277／375≤390，無水平溢出。窄版`0.000 / all / 0 / 10`真零，振幅改0.000恢復全六股code順。

Root首次card anchor label extractor為null、第二state shell inner-doublequote formatter失敗只屬diagnostics；在相應admission前更正，沒有bad native action、追加source或產品故障證據，不寫成首次全通過。

### 33.4 完成、版本與未驗邊界

Root accepted source13／net25368B與B1核心：coreoperation+1／selected ordinary identity-source-date-policy dependency+1／reliability0／stall0。六股source13＋DOC8／freeze21／七分區qualified索引、exact commit／正常ff-only local master merge及下一統籌visible gate已接受。Owned page／API／preview／compiler已清、held raw已釋放；necessary checks與原exit／清理由[開發入口](development-baseline/README.md#m2-focus-stock-scope-4-六股範圍的記憶體驗證入口)管理。

未驗磁碟保存／跨程序、full suite／production build、全市場／PIT、20／21歷史close／完整calendar／strategy time execution、MA／trend／ATR／研究／Signal／Plan或完整M1／M2／M3。歷史NO-RETRY排除，既有有效證據按範圍沿用。

## 34. M2-FOCUS-STOCK-SCOPE-5：七股關注與同截止往返

普通TPEx支援6→7新增6510精測的資料／計算、actual API及可信桌面／窄版操作已有限接受。Scope code順3105／3293／5274／5347／6488／6510／8069、source-date2026-10-06；focus `price-lot-focus/m2-v9`、projection `stock-price-memory/m2-stock-scope-v5`。身份／policy／金融原件權威見[來源 §29](SOURCE_REGISTRY.md#29-m2-focus-stock-scope-5七股來源准入)。

### 34.1 完整gate與actual API

沿§29.1精確張／canonical股、原O/C、int64 TWD元及振幅公式。Default10/06採`.5`七股，explicit舊六股及更早immutable tuples／舊兩股producer相容保持；公開條件仍`as_of/min_lots/day_move/min_turnover/min_range_pct`，不增加第六條。

全部required reads／逐股身份及金融／同cutoff／tuple／provenance先gate後filter；任一missing／invalid／conflict為unavailable、count=null、items=[]，不跳壞股或縮scope。完整七股available/count0才是真零；四理由固定順序去重、一股一卡／code升序，frontend獨立重驗raw與safe local五條件URL。

Root actual API10案已核126欄／42金融值及原六股canonical保持；七symbol POST＋一focus POSTcached零新增source。Default／explicit10/02／old10/05對6510unavailable已核，後者不升格未跑native日期case。Source修改後final Store1／runner1／preloaded=false／guards0／disk0／DB preserved；兩次financial GET版本由來源§29.2管理。

| 10/06門檻（min_lots／day_move／min_turnover／min_range_pct） | 已接受結果（code順） |
| --- | --- |
| 560.518／down／1729347985／2.880 | 3105＋6510 |
| 560.518／down／1729347985／2.881 | 3105 |
| 0.000／all／0／0.000 | 全七股 |
| 0.000／all／0／10 | available/count0／items=[] |

6510張560.518 inclusive／560.519排除、成交額1729347985 inclusive／1729347986排除、振幅2.880 inclusive／2.881排除均按原exact值核。顯示約值或3,055千分位不替代原3055.00與精確比較。

### 34.2 Desktop／窄版往返

唯一owned page `045cdead-1528-460f-adc2-949aa3fc0fa1`：desktop1277×924全七股→lower→6510同cutoff detail→raw open→back保留五原字串→upper；窄版390×844 upper→lower→6510 detail／raw open／back→upper→真零→restore。Lower為`2026-10-06 / 560.518 / down / 1729347985 / 2.880`，upper只改2.881，原尾零完整返回；raw追溯ordinal726／含header727。

21個native click／submit／toggle均isTrusted=true；draft programmatic fill／select只setup，不稱trusted typing。14個states含full raw open，desktop scrollWidth1262≤1277／窄版375≤390；窄版`0.000 / all / 0 / 10`真零，振幅0.000恢復七股code順。

### 34.3 完成及未驗

Source14及本B1核心已root接受：coreoperation+1／selected identity-source-date-policy dependency+1／reliability0／stall0；owned page／API／preview／compiler已清，raw已釋放。Checks與cleanup／原exit見[開發入口](development-baseline/README.md#m2-focus-stock-scope-5-七股範圍的記憶體驗證入口)。DOC review→freeze→qualified affected index→exact local commit→另准master merge／新統籌gate尚待。

未驗磁碟保存／跨程序、full suite／production build、全市場／PIT、20／21歷史close／complete calendar／strategy time execution、MA／trend／ATR／研究／Signal／Plan或完整M1／M2／M3。下一M1-PRICE-SAVE-1需新用途／私有磁碟範圍准入及actual跨程序API／UI；當前操作仍process memory。

## 35. M1-PRICE-SAVE-1：私人單日保存與跨程序操作

**七股／2026-10-06的實際磁碟保存、NEW reader、actual API及具名桌面／窄版已有限接受。** 原件、dual pins、三檔schema及時間權威見[來源 §30](SOURCE_REGISTRY.md#30-m1-price-save-1私人單日保存與跨程序讀回)；原`.5` memory及§34 focus不自動切換storage來源。

### 35.1 明示保存、讀回與同股同截止

`POST /api/stocks/{exchange}/{symbol}/prices/save?as_of=2026-10-06`只保存現有合法memory capture，不觸發金融GET；無capture拒用。`GET /api/stocks/{exchange}/{symbol}/prices/saved?as_of=2026-10-06`只重開核定私人bundle；須exact supported TPEx identity／scope／date與兩種policy pins。缺cutoff、10/05、10/07皆unavailable，不能用較早或較晚資料補值。

Saved payload `stock-price-saved/m1-v1`以`origin=private_local`區分，`latest`／單bar接同股同日headline／表／圖；`provenance`保留原capture的process_memory事實及UTC，`storage_provenance`另存storage receipt／SHA／saved_at。Source raw欄位、canonical股、精確張與TWD元／股維持；DB IDs null，published／first_available／revision unknown／historical_pit unsupported。Frontend先重驗saved schema／scope／units／raw金融值／same symbol-cutoff／兩層provenance與hash，再採數值。

使用者分別按「保存此日行情」及「讀取已保存行情」；切stock／date隔離request token及舊saved值，日期恢復仍須explicit read。讀回不hydrate memory／不auto-fetch；NEW saved-only reader empty Store／禁止capture，讀與空memory save均零金融GET。原default截止／legacy memory及DB讀值gate保持；具名文案由[UI §10.2](UI_COPY_SPEC.md#102-個股詳情的第一屏)管理。

### 35.2 已接受actual API與原生操作

Root保存及producer停止後重啟NEW reader，actual七股saved API核all126 source fields／42金融、fullbody及兩receipt exact bytes/hash，writes0／mutations0／guards0／DB preserved。Negative5：缺cutoff、10/05、10/07 unavailable；empty memory save unavailable；reader capture POST405。Native idempotent save保存原files／saved_at，沒有追加source或write。

桌面1277×924逐一讀全七股；窄版390×844讀6510／3105／6488，6510full18原列DOM含`-50.00 `尾空白、desktop／窄版raw open均核。6510單日chart實際O3125／H3140／L3050／C3055、成交560.518張，MA空，不假造20日趨勢。日期10/05拒用→10/06恢復只在explicit read後採值；stock／date token隔離已核。

Normal停止owned reader後，同一token實際重讀經proxy502失敗，`price_private_request_failed`清除舊saved headline／table；這是connection failure，並非actual missing-file。Producer5＋reader35共40trusted native events；draft programmatic只SETUP。15個已測states：desktop scroll1262≤1277、narrow375≤390，無水平溢出。

### 35.3 完成、清理及驗收邊界

本B1 operation+1／necessary private-save及跨程序dependency+1／reliability0／stall0。Source13已root接受，checks／文件範圍／配額及三檔NO-RETRY殘留見[開發入口](development-baseline/README.md#m1-price-save-1-私人磁碟保存與新程序驗證入口)；DOC review／freeze／qualified index／exact commit／另准master merge仍待。

Actual missing-file native UI未跑，完整性／schema／部分bundle拒用有synthetic證據；actual failed reread則是proxy502。產品磁碟raw未刪，memory raw已隨程序停止釋放；不把清理拒絕稱成功。未驗full suite／production build／其他平台路徑、跨日自動累積、全市場／PIT、20／21歷史close／complete calendar／strategy time execution或完整M1／M2／M3。

## 36. M1-CHIPS-CUTOFF-1006-1：同截止法人窗口與完整日曆

**3105穩懋／6488環球晶、explicit10/06的真5／20交易日法人窗口、actual API及可信desktop／窄版已有限接受。** 總覽 `stock-overview/chips-1006-v1`、法人 `institutional-windows/chips-1006-v1`／read `institutional-windows-read/chips-1006-v1`。Exact來源／policy pins、完整24日曆與唯一12 canonical net由[來源 §31](SOURCE_REGISTRY.md#31-m1-chips-cutoff-1006-1同1006法人窗口與完整有界日曆)管理；§24 W8保持原10/02截止／版本，其他區塊未借法人grant取得准入。

### 36.1 顯式截止、同批讀取與失敗清值

沿 `POST /stocks/{exchange}/{symbol}/institutional-windows/capture?as_of=2026-10-06`；detail／overview帶同explicit日期。只有10/06選新獨立Store及pins，省略日期／resolved default／舊cutoff仍走W8；不自動把default提升至10/06。最初「載入5／20日法人窗口」合法明示BUTTON取2月＋20daily一次，後續「讀取本次法人窗口」／切兩股／普通GET重驗held22，source0；failed attempt不另取得或重啟。

畫面先核expected exchange／symbol／explicit cutoff、schema／worker／policy／body／原canonical receipt、完整24calendar與兩窗required dates、原25欄／金融關係／BigInt sum，再顯示張值與來源。5日9/30～10/6、20日9/7～10/6；合法0保留、missing／invalid不補0、不縮窗或fallback。日常張值使用[§10.3](UI_COPY_SPEC.md#103-張零股)穩定公式，最多三位小數去尾零；外資簡稱仍保留「不含外資自營商」。

Outer「查看法人窗口的每日數值、交易日與來源版本」列完整24日六欄日曆，與20法人daily分開；閉日9/25、9/28明示依官方公告。每日日子表提供全25原字串、row ordinal、source／policy／calendar／calculation版本、body／receipt SHA及UTC。觀測非publication／revision／first availability，PIT未支援，不推論trend／研究條件成立。

同token讀取network失敗或回應核對失敗時，立即隱藏net數值、窗口表及verified raw／details，只留可讀原因與同批讀取button；不能因React query保留舊cache而繼續顯示舊數值。返回有效10/06且成功核對後才能恢復；source重試權不由讀button取得。

### 36.2 具名actual API與可信native

| 已接受操作 | 範圍與證據 |
| --- | --- |
| NEW first load及held讀取 | Trusted BUTTON前空新／W8 Stores、finance seed0、source0；唯一first load22 fresh。Actual capture POST response200三次＝firstload1＋heldreads2，source始終22；另有最後502一次。 |
| 兩股desktop與窄版 | 1277×924／scrollWidth1262及390×844／375，全12張值對root獨立真值；3105→6488→3105恢復正確。 |
| 日曆與原列追溯 | 兩股outer實際展開完整24日六欄；各股實際展開9/7、10/5、10/6三daily的25原字串。兩股20daily×25 DOM全部對raw相等，不稱40daily均曾native展開。 |
| 截止隔離與恢復 | 可信鍵盤input／change／FORM submit套10/07及舊10/02，新數值清除；恢復10/06正常且held讀無新增source。只驗新值隔離，不把空W8 Store說成舊W8來源失效。 |
| 同token失敗讀取 | 正常停止API後，native讀button實際responseStatus502；nets／table／details／verified raw均0，保留button與失敗原因，無producer restart。 |

同一可見page共54events／53 trustedtrue／1 untrusted CLI fill失敗。首次CLI點到HTML、source0；滾至actual BUTTON才取得唯一22。CSS未命中、runtime connectionclosed讀失敗與無效fill ACK不算成功；沿same page讀回，沒有Orca重啟／capture retry；日期案例以後續真鍵盤事件通過。CLI填值只屬setup，不能冒稱可信輸入。

### 36.3 完成、清理與未驗

Root接受operation+1／必要來源用途＋觀測日曆＋daily dependency+1／reliability0／stall0；唯一owned page正常closed／tabs[]、API／preview／compiler及listeners已核不存在，raw只memory已釋放、diskartifact0。Normal Ctrl+C rawexit1與cleanup proof exit0分報，收據見[開發入口](development-baseline/README.md#m1-chips-cutoff-1006-1-同截止法人窗口的零落盤驗證入口)。

缺／壞來源按窗失效、污染／busy／pins等邊界只以必要synthetic驗證；actual missing-source native未跑。未驗全市場／TWSE、普通股20／21close、完整strategy／time／execution、PIT、trend／Signal／Plan、法人磁碟保存／跨程序、full suite／production build或完整M1／M2／M3。舊private三檔及整個DAY-RANGE NO-RETRY保持；既有通過證據不因新角色重跑。

## 37. M1-SAVED-PRICE-FOCUS-1006-1：保存來源關注與同截止往返

**保存七股／2026-10-06的四條件篩選→同股同截止detail→五原條件返回已有限接受。** `price-saved-focus/m1-v1`獨立於memory `price-lot-focus/m2-v9`；exact consumer/storage/capture pins、fullraw與金融真值只由[來源 §32](SOURCE_REGISTRY.md#32-m1-saved-price-focus-1006-1保存來源的七股關注准入)管理，原§34／§35／§36不自動取得新准入。

### 37.1 明示只讀、全七股gate與exact條件

`GET /api/focus/price-saved`只接受 `as_of/min_lots/day_move/min_turnover/min_range_pct` 五條件，前兩required；duplicate／unknown／invalid query回422。合法但unsupported10/05、10/07為unavailable／count=null／items=[]且不讀檔。Supported僅explicit10/06、來源§32七identities；完整原件／全七股required reads及同tuple／日期／provenance先gate後filter。四項條件AND、inclusive精確比較、code升序、一股一卡；available真零不等於來源不足。精確張／int64 TWD／C對O方向／振幅公式與原漲跌欄區別見來源§32.2。

Entry、套用條件、切換及返回都不auto-read；使用者按「讀取已保存行情」才核目前條件。同一stock／date／source-mode／條件組有generation token；busy、回應失敗及切換隔離舊值，late response不回填其他狀態。頁面為 `/focus/price-saved`，詳情帶 `source_mode=private_saved`、`from=price-saved-focus` 與safe local返回條件；來源模式不新增第六個公開filter。

### 37.2 Saved detail、來源追溯與失敗隔離

新consumer detail為 `GET /api/stocks/{exchange}/{symbol}/prices/saved-focus?as_of=2026-10-06`；old `/prices/saved` 在guarded mode外保持。NEW consumer runner只讀且全部POST禁止，guarded mode的old saved入口405，避免繞過shared read budget。切同股／日期／source-mode先清saved值，合法返回五條件才啟用新read；不save、capture、hydrate memory或採old memory／DB價格fallback。

Frontend先重驗新consumer及原saved schema／兩層provenance／hash／scope／cutoff／raw金融值，再接headline、成交張、表與單日chart；原列drawer保留18 source fields、row ordinal與capture/storage receipt。返回留 `as_of/min_lots/day_move/min_turnover/min_range_pct` 的**五個原字串**，含 `0.000`／`2.880` 尾零；不正規化成另一組輸入。原capture process_memory及現在private_local並列，擷取／保存UTC不是發布時間，MA／trend／研究條件仍待補。

Actual focus same-token HTTP502立即清全部cards、count、來源blocks及raw；detail same-token HTTP502清headline、成交張、table、原列drawer及canvas，保留read button與ONE「讀取原因」diagnostic details。Diagnostic details不是raw drawer，不以其存在誤報舊原件仍顯示。缺／壞來源不用0、其他日期或memory／DB補值；恢復後仍須明示讀取。具名文案由[UI §10.6](UI_COPY_SPEC.md#106-保存來源關注與同截止返回)管理。

### 37.3 Actual API、精確邊界與可信native

Root獨立API驗全部七股detail的126原字串／42金融、完整三檔hash與兩receipt canonical，不稱七股都曾native開raw drawer。Actual focus結果如下，門檻順序為張／方向／TWD元／振幅%：

| 條件 | code順結果 |
| --- | --- |
| 560.518／down／1729347985／2.880 | 3105＋6510 |
| 560.519／down／1729347985／2.880 | 3105 |
| 560.518／down／1729347986／2.880 | 3105 |
| 560.518／down／1729347985／2.881 | 3105 |
| 0／all／0／0 | 全七股 |
| 0／up／0／0 | 5347＋6488＋8069 |
| 0／down／0／0 | 3105＋3293＋5274＋6510 |
| 0／flat／0／0 | available genuine0／items=[] |

Desktop1277×924／doc1262與narrow390×844／doc375均完成trusted read、6510 detail及五原字串back，無水平溢出。Desktop驗七exact cards、三mixed boundary與flat真零；6510 headline／560.518張、source18 drawer均對actual raw，ordinal726／含header727，原 `-50.00 ` 保持。Narrow只驗mixed3105＋6510、genuine6510 read及headline收盤3055／560.518張／成交額1729347985、五原字串返回；未驗窄版native raw drawer展開。Entry／apply／back沒有自動read；同stock/date/source-mode token隔離與focus／detail兩個actual same-token502清值均核通。

同ONE lifetime page共96 browser events，全isTrusted=true；含兩次offscreen HTML miss後在同頁actual SUMMARY／A改正。首次Ctrl+A沒有選取而append invalid字串，後以trusted End／Backspace／inserttext改正；只後續正確輸入通過，不稱首次選取成功。CLI讀取／prefix／quoting／ref失敗不是產品成功操作，不據此重啟或重放。首次root detail assertion把diagnostic details當raw而exit1，後readonly proof0釐清；產品不用source edit／rerun。

### 37.4 完成與未驗邊界

本B1 coreoperation+1／necessary derived saved-source readonly-use dep+1／reliability0／stall0；source13已獨立接受，必要驗證與owned runtime清理由[開發入口](development-baseline/README.md#m1-saved-price-focus-1006-1-保存來源關注的零落盤驗證入口)管理。Raw disk仍保留；三檔NO-RETRY與整個DAY-RANGE fence不變。Actual missing-file UI未跑；synthetic integrity／schema不改稱actual missing-file，HTTP502不改稱缺檔驗收。未跑full suite／production build／diskcases／install；未驗其他平台、全市場／PIT、普通20／21close／trend／strategy／time／execution或完整M1／M2／M3。

## 38. M1-SAVED-PRICE-CHIPS-INTEGRATION-1006-1：共同入口與同截止往返

**Saved-focus→3105／6488同explicit10/06的saved OHLC＋真5／20net→追溯→原五條件返回已有限接受。** 是NEW共同guarded API／preview的具名操作；source-use／五獨立policies、原件／金融與caps由[來源 §33](SOURCE_REGISTRY.md#33-m1-saved-price-chips-integration-1006-1保存行情與法人窗口共同入口)管理。原§34～37各自有限能力與pins保持，其他五saved股只有既有price能力。

### 38.1 明示讀取與同一context

Joint preview以 `VITE_SAVED_PRICE_CHIPS_INTEGRATION='m1-v1'` 啟用；條件、URL與saved-focus detail須同context，3105／6488才可首次載入法人。Saved入口／套用／切股／back不自動private read／capture；先明示讀保存行情，再trusted首次「載入5／20日法人窗口」。成功後同一SINGLE NEW API提供saved headline／OHLC／成交張與§31完整日曆／20daily真5／20交易日12 net；切兩股不重啟、不取得live price／hydrate old memory，不擴大cutoff。

當current private／chips／stock read／refetch或provenance核對失敗，兩區數值、raw與chart一併清除，留下read buttons及ONE原因。恢復須same current context／generation內成功的明示NEW saved snapshot和明示held chips read；成功一邊或舊generation成功不足，held read不取得外網，failed capture不自動重試。

### 38.2 Actual具名操作

原RAW五條件 `2026-10-06 / 10000.000 / all / 0 / 0.000` 產生code順四卡3105／5347／6488／8069；以下全在ONE page／ONE producer：

1. 明示saved-focus read、3105同10/06 detail saved read；trusted FIRST chipsload取得新22，headline／OHLC／5／20net同頁可讀。
2. 切6488同cutoff明示read，查看兩股來源與raw provenance，再back回五完全相同原字串。
3. 既有capture的held button POST200新增source0；正常停止API後，同token6488 trusted heldbutton POST actual HTTP502（request52352.26），不restart。
4. 502同時清saved headline／volume／原列／chart及chips nets／calendar／dailyraw；tables0／canvas0、兩read buttons保留、ONE chips alert；再窄版trusted back五RAW同值。

Desktop1277×924／doc1262：四卡、兩股headlines＋12net；price drawer各18原欄（ROOT兩股36原字串／12金融、ord205＋717核對），calendar drawer完整24×6，10/06 daily各25原欄／ord176＋646。Native未逐一開20dailyraw；ROOT獨立原件驗證不改稱native全20日逐欄。Narrow390×844／doc375：四卡、兩identity headlines＋12net及五RAW往返已核，未驗窄版rawdrawer。

ONE lifetime page `ee33ac1b-e221-47d3-8331-2d73c0c40328` 40events全trusted。兩次ineffective TD-selector與兩次offscreen HTML clicks，由same page實際SUMMARY／A修正；首次selectors／readonly eval quoting／syntax／help失敗保留，沒有implementation／source retry。Source新22為當次首次native取得、非舊capture replay。

### 38.3 驗收與未完成

ROOT接受source實作、fresh22／all原receipt／金融、actual API及上列trusted操作；API50788／parent55084 SINGLE empty stores、finance seed0／preloadedfalse、guards0／19DB full schema與values／typeof preserved。本批price金融GET0／外部來源metadataGET0／new product disk0／DBmut0；private12bundles／36files含ROOT，existing private三檔仍在。

B1 coreoperation+1／necessary joint-source-use-guard dep+1／reliability0／stall0。必要Py6／Node42guard＋9recovery＋7AppSSR／33src noEmit及首次失敗、normal exit與cleanup分報由[開發入口](development-baseline/README.md#m1-saved-price-chips-integration-1006-1-共同入口的零落盤驗證入口)管理，命令與逐輪receipt留原task。Memory invalid／recovery／provenance tests不當actual missing-file UI；因NO-RETRY後者NOT RUN。未跑full suite／old full SSR／install／production build／diskcases，不外推其他平台／全市場／PIT或完整M1／M2／M3。

下一候選 `M1-SAVED-PRICE-CHIPS-FOCUS-1006-1` 缺institutional predicate consumer／API／form／result；現saved-focus只有四price predicates、API五query fields，API和preview guards皆拒institutional query。擬僅3105／6488按選定investor、5或20日、signed net threshold精確篩選，再joint detail／全RAW返回；verified zero與unavailable分開，非ranking／strategy／PIT。NEW root先核缺失操作、選定語義／新policy、兩finite uses／pins／caps／errors，才private read／implementation／金融GET；目前未准新用途或producer，memory已釋放，fresh22須新必要grant。普通20／21stock closes／trend／strategy／time／execution及完整ROADMAP仍缺。

## 39. M1-SAVED-PRICE-CHIPS-FOCUS-1006-1：八條件入口與不可用驗收邊界

**八條件guarded入口及具名unavailable操作已有限接受；法人matching、verifiedzero、jointdetail和八RAWback仍待驗。** 來源與14399B新policy／schema、signed精確比較、scope／quota及calendar拒用由[來源 §34](SOURCE_REGISTRY.md#34-m1-saved-price-chips-focus-1006-1保存行情與法人條件關注准入及日曆缺口)管理，不以fixture或前輪joint成功代本輪正向操作。

### 39.1 已實作操作契約

新頁 `/saved-price-chips-focus`僅 `VITE_SAVED_PRICE_CHIPS_FOCUS='m1-v1'` 啟用，獨立於既有saved-focus／joint入口。八欄為原 `as_of/min_lots/day_move/min_turnover/min_range_pct` ＋ `investor/horizon/min_net_lots`；僅3105／6488的selected investor／true5或20日net與四price條件同時成立才列卡。全七price仍須完整核對，其餘五股不屬joint scope。

兩個來源按鈕承接三次明示動作：①「讀取保存來源並篩選」核NEW private snapshot；②「首次取得法人來源」啟動一次新capture；③再按「讀取保存來源並篩選」核NEW private snapshot＋held chips。Entry／apply／切股／back／capture completion不auto-private read，也不在失敗capture後自動重抓。讀成功price而缺chips，候選仍未知；只有七price／兩股chips完整才可宣告真零。

新focus GET要求八keys各一次／body0、壞query422，unsupported cutoff在I/O前unavailable；路由名稱與source模式不變成第九filter。預定detail context為11keys：`as_of/from=price-saved-chips-focus/source_mode=private_saved`＋`focus_as_of/focus_min_lots/focus_day_move/focus_min_turnover/focus_min_range_pct/focus_investor/focus_horizon/focus_min_net_lots`；只合法同cutoff兩股才可進joint detail，返回必須保留全部八原字串。此detail/back為已實作但未actual驗收的契約。

Current source／snapshot／chips或provenance失敗須同時mask prices／chart／raw與chips nets／calendar／dailyraw；只留明示操作及原因。解除mask需same generation的新private及held chips皆成功，late／舊generation成功不能回填。Preview建置後曾補新flag下attempted失敗detail guard並跑memory checks；沒有重開preview／後續native，actual detail NOT RUN，原joint flag expression保持。

### 39.2 Actual unavailable操作

ONE page的具名桌面／窄版操作已接受；25trusted events及首次未送達動作／輸入修正的完整收據留ROOT原task。

- Desktop1277×924/doc1262：home→八欄apply private0→明示read1七price仍unknown→ONE trusted FIRST只取兩index、Oct10/7超scope失敗→明示read2仍unknown。
- Narrow390×844/doc375：10/5apply/read為unsupported、private0；回10/6配min_lots1000000.000，明示read3仍unknown。ROOT actualAPI read4核count=null/items=[]/price=null/institutional=[]/bothready=false/capture_attempted=true/can_capture=false，這個高門檻案例沒有驗出真零。
- API正常停止後最後trusted read保持masked；沒有具名actual HTTP502status或positive→clear證據，不能沿用前輪same-token502驗收。

Matchingcards／verifiedzero／jointdetail／八RAWback／負門檻actual均未驗，沒有本輪正向rawdrawer／chart驗收。ROOT價格／index原欄核對不代native逐欄驗收；actual missing-private-file UI NOT RUN。

### 39.3 驗收、停滯與下一候選

ROOT只接受以上unavailable及owned退出。Actual private7snapshots/21files、financial index2/daily0、metadata0／new productdisk0／DBmut0，原三檔post-stop不變；guards0／19DB全量保留。Coreoperation0／dependency0／reliability0／stall1（前0），正向source gap未解除。Py6／Node59/17/7／36src noEmit的必要checks與未跑項見[開發入口](development-baseline/README.md#m1-saved-price-chips-focus-1006-1-八條件入口的零落盤驗證入口)；原失敗／runtime／關閉收據留ROOT task，memory測試不代產品正向驗收。

下一conditional candidate `M2-FOCUS-STOCK-SCOPE-6-B1`：新增ordinary第八股的單日四理由→同截止個股→五RAWback，尚未准入。Current worker只fixed10/5／10/6、最新.5七股；fresh身份／實際date／scope用途及必要versioned date guard須在金融GET前另核，不能承諾目前wire仍10/6或擴private七股／joint兩股。Calendar替代也須另准parser/schema/policy；本failed producer禁retry／restart／newproducer。完整M1／M2／M3及20／21stock closes／trend／strategy／PIT／time／execution仍未完成。


## 40. M2-FOCUS-STOCK-SCOPE-6：八股四條件與同截止往返

ROOT已有限接受explicit2026-10-07、ordinary TPEx第八股6223旺矽的四price predicates→同cutoff detail→五RAWback。八股code順3105／3293／5274／5347／6223／6488／6510／8069；新focus `price-lot-focus/m2-v10`／projection `stock-price-memory/m2-stock-scope-v6`。身份、授權、新policy／原件／時間及finance quota由[來源 §35](SOURCE_REGISTRY.md#35-m2-focus-stock-scope-6八股與新來源日准入)管理；原defaults、七股.5／private及兩股chips不改。

### 40.1 完整gate與actual API

公開條件仍 `as_of/min_lots/day_move/min_turnover/min_range_pct` 五RAW；精確張／O-C方向／int64 TWD元／本日振幅四predicate沿穩定AND與inclusive比較，依code排序，不是ranking。全部八股required reads及cutoff／tuple／provenance先gate後filter；缺失／invalid／conflict回count=null/items=[]，完整available才可判count0。

ROOT local API九案已接受；未改欄位的案例均沿base `2026-10-07 / 896.441 / down / 4984488555 / 4.000`：

| 案例 | 已核結果 |
| --- | --- |
| Base | count2，3105＋6223。 |
| min_lots896.442 | 排除6223；native亦核只3105。 |
| min_turnover4984488556 | 排除6223。 |
| min_range_pct4.382 | 含6223。 |
| min_range_pct4.383 | 排除6223，顯示約4.383不作比較值。 |
| 0.000／all／0／0.000 | 全八股。 |
| min_lots1000000.000 | available/count0/read8。 |
| 0.000／flat／0／0.000（平收） | available/count0/read8。 |
| as_of2026-10-06 | unavailable/count=null/read7、no source GET。 |

同cutoff6223 detail已核收盤5530元／股、896.441張、成交額4984488555元、OHLC5590／5725／5480／5530；只有單日1K，不產生MA20／MA60。原18欄／full SHA／ORIGINAL receipt／provenance可由明示disclosure追溯。

### 40.2 ONE page可信輸入與往返

唯一page `67cccd5f-d0a0-494e-875c-387273d83e53`：來源日期先以explicit URL設定10/07，其他四欄由native typing／select後Apply；Apply不auto source。ONE trusted FIRST click `6a79f608-879b-47c5-883a-69a48a3867e3`觸發空producer首次GET，preloaded=false／financeSeed0；沒有JS fill、value assignment或fake events。

Desktop1277×924/doc1262：base兩卡→6223同cutoff detail→native Tab＋Enter開disclosure核18 ORIGINAL fields／full SHA／receipt／provenance→back五RAW exact→張門檻896.442只3105→restore兩卡。窄版SAME page390×844/mobile、actual docWidth390：1000000.000顯示「已核8股、符合0檔」→restore base兩卡→6223 detail→back同五RAW，尾零保留。

Ctrl+A曾造成append；在SAME page用native Home／exact Delete再native Type修正，無效動作也保留於完整183events：23click／143input／12change／5submit、ALL isTrusted=true。Canonical receipt19741B／SHA `98c372d856a25dac3e56fcaab8eb7a6990e5f30ba15a66261087395a7dfdd762`留ROOT原task，不另建附件。

### 40.3 Current failure清值與驗收邊界

ONE API normalstop後，SAME page ONE trusted Read `82f93e10-2446-414a-acdc-a43f0d06565f`的browser ResourceTiming核HTTP502；原positive cards/count清除，候選未知／無cards／無count，五RAW仍保留且FIRST disabled。沒有restart。**停止後detail錯誤actual NOT RUN**，只有synthetic SSR，不能升格該case或沿用舊502收據。

ROOT接受source14、actual操作及owned退出；coreoperation+1／standalone dependency0／reliability+1（current failure清stale values）／stall1→0。Final preview20 local API GET／1POST／14rejected不是financialGET；19 memory tables的schema／indexes／triggers／全部values／每cell typeof保留，guards0／private0／newdisk0。必要checks、原失敗與退出見[開發入口](development-baseline/README.md#m2-focus-stock-scope-6-八股新來源日的零落盤驗證入口)。

DOC review→freeze→qualified索引→exact commit→另准master merge尚待。完整M1／M2／M3、ordinary20／21close history／trend／strategy／PIT／time／Signal／Plan／execution仍未完成；下一未准入候選見[ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)。Private／chips／failed producer及既有cleanup fences保持。

## 41. M1-SAVED-PRICE-CHIPS-FOCUS-CALENDAR-1006-2：八條件正向關注與同截止往返

ROOT已有限接受2026-10-06保存七股與3105／6488法人的八條件positive／verifiedzero／jointdetail／八RAW返回；新full-month用途、policy／pins、原件／12net與執行cap由[來源 §36](SOURCE_REGISTRY.md#36-m1-saved-price-chips-focus-calendar-1006-2全月日曆與八條件來源准入)管理。舊§39的unavailable批次及原flag不改，當輪失敗不改寫成功。

### 41.1 新入口與明示來源操作

新頁 `/saved-price-chips-focus-calendar`、`VITE_SAVED_PRICE_CHIPS_FOCUS_CALENDAR='m1-v2'` 與舊joint／focus flag互斥；新GET `/api/focus/price-saved-chips-calendar`要求 `as_of/min_lots/day_move/min_turnover/min_range_pct/investor/horizon/min_net_lots` 全八keys各一次／body0，invalid／duplicate／unknown422。只explicit10/06／joint3105與6488；valid unsupported date在private/source I/O前unavailable/countnull。

三個明示按鈕順序是「讀取保存來源」→「首次取得法人來源」→「核對共同來源並篩選」。第三步核NEW private snapshot＋held chips；entry／apply／切股／back／capture completion均不auto-read。已有held來源時，單按price read仍不能列joint候選，須第三步明示核對。完整whole7＋both gate、signed淨超與AND／含等號沿來源§36，不因高price門檻省略chips。

Detail沿11keys同cutoff context：`as_of/from=price-saved-chips-focus-calendar/source_mode=private_saved`＋八個 `focus_*` 原字串；exchange／symbol／cutoff／pins不合拒用。返回新頁保留全部八RAW及尾零；不能以old route／defaults或另一generation補值。

### 41.2 Actual API與可信操作

Base八RAW為 `2026-10-06 / 13913.614 / all / 11863581093 / 5.691 / foreign / 5 / 594.644`，count2＝3105＋6488。ROOT actual API十二案在未改欄位時沿base：

| 條件變更 | 已核結果 |
| --- | --- |
| min_lots13913.615 | 只3105。 |
| min_turnover11863581094 | 只6488。 |
| min_range_pct5.692 | 只6488。 |
| day_move down／up | 分別只3105／6488。 |
| min_net_lots594.645 | 只3105。 |
| min_lots1000000.000 | available0，仍驗完整七price與both chips。 |
| 全price條件0／flat | available0。 |
| foreign／20／-14155.476 | 兩股，精確含等號。 |
| foreign／20／-14155.475 | 只3105。 |
| as_of2026-10-07 | unavailable/countnull、private0。 |

所有上述case source維持22；cached POST回409/alreadyattempted且不新增source/private。API／proxy各23invalid＋valid unsupported4共50guards在I/O前核：GET body422、oversizePOST413、old savePOST405、emptyFIRST在price readiness前409；不把local API requests計成financial GET。

ONE intended page `42c7d462`（完整ID／receipts留原task），desktop1277×924/doc1262與窄版390×844/doc375（scrollbar、無horizontal overflow）均核base兩卡、6488 samecutoff detail／明示read與back全部八RAW；native高張1000000.000真零→restore兩卡已驗。Desktop6488 detail核同日OHLC／精確張與TWD、六net含negative20、單日1K／MA未支援；native Tab＋Enter開price disclosure核18原欄／full SHA，calendar disclosure核ALL25六欄含保留10/07。3105 detail明示read核收盤592元／股、19731.7張、TWD11863581093、六net及1K。兩source dates同10/06，capture／saved UTC與發布未知分開。

Desktop及narrow原條件返回前後private counter23相等，無implicit read；133 recorded events＝33click/90input/6change/4submit、ALL trusted，沒有JS fill／value assignment／fakeevents。原keyboard offscreen／focus mistakes仍留task；兩個accidental about:blank tabs為nullorigin／no network resource、各正常關閉，不能視為額外financial證據或globaltabs清理。

### 41.3 Current failure、修正與驗收邊界

ONE API normalstop後，same3105 trusted Read的ResourceTiming實際502，原positive同時清price headline／volume／chart／raw與chips nets／calendar／dailyraw，canvas0/table0；再native back並trusted joint Read核focus實際502，cards0／count不顯示／候選未知，FIRST及joint disabled、全部八RAW保留。沒有restart／source retry；停止後actual recovery NOT RUN，只synthetic same-generation雙成功recovery。

初次20日negative card文字空白保留為actual發現；只calendar-v2 signed formatter修正，old expression不改，final SSR驗negative5／20及zero。當前preview仍用修正前bundle，**POSTFIX NEGATIVE CARD ACTUAL NOT RUN**；negative精確API／detail受驗不代修正後card native驗收。Actual missing-private-file UI也未跑。

ROOT接受source20／coreoperation+1／standalone dep0／reliability+1（current source失敗清兩來源）／stall0。19 memory SQLite全schema/index/trigger/value/every-cell typeof preserved、guards0／financeSeed0／preloadedfalse／newdisk0／formalDB0，children actual GET/private0。必要checks及owned退出由[開發入口](development-baseline/README.md#m1-saved-price-chips-focus-calendar-1006-2-全月日曆八條件的零落盤驗證入口)管理；private與排除清理fences保持。Freeze／qualified索引／commit／另准master merge仍待；完整ROADMAP未完成。

## 42. M1-SAVED-PRICE-CHIPS-FOCUS-STOCK-SCOPE-7-1006-1：七股八條件與同截止往返

ROOT有限接受saved七股＋七股法人的explicit2026-10-06八條件關注；來源identity／新policies/pins／ALL140daily／42net／private cap由[來源 §37](SOURCE_REGISTRY.md#37-m1-saved-price-chips-focus-stock-scope-7-1006-1七股共同來源准入)單一管理。§41兩股calendar及修正後negative card未驗的歷史保持，本節只描述本次新profile。

### 42.1 新入口、共同來源與返回

新頁 `/saved-price-chips-focus-stock-scope-7`、compile `VITE_SAVED_PRICE_CHIPS_FOCUS_STOCK_SCOPE_7='m1-v1'`；new GET `/api/focus/price-saved-chips-stock-scope-7`接受 `as_of/min_lots/day_move/min_turnover/min_range_pct/investor/horizon/min_net_lots` 八required keys各一次、body0；old/calendar flags與route保留獨立且不能補值。Invalid／duplicate／unknown在IO前拒用；valid unsupported日期先unavailable。Signed grammar、int64、inclusive AND、code順與exact價格公式沿來源§32.2／34.1。

明示「讀取保存來源」→「首次取得法人來源」→「核對共同來源並篩選」；entry／apply／切股／capture completion／back不auto-private read。Price-only即使held chips已獨立核實仍不jointready；先fullALL7price＋ALL7chips gate，再篩選，真零也須完整來源。初次saved未讀只清price，held chips可顯示；actual current source failure則清BOTH，不把unknown寫count0。

Detail context沿11keys：`as_of/from=price-saved-chips-focus-stock-scope-7/source_mode=private_saved`及八 `focus_*` 原字串；samecutoff／exchange／symbol／pins／generation不合拒用。Back保留全部八RAW及尾零，不借old route/default；沒有implicit read。顯示provenance欄位與原列，不聲稱整份original receipt JSON直接呈現在UI。

### 42.2 Actual API與可信七股操作

BASE八RAW `2026-10-06 / 0.000 / all / 0 / 0.000 / foreign / 20 / -9223372036854775.808`得到七股code順3105／3293／5274／5347／6488／6510／8069。ROOT以原saved價格／Decimal及FULL42nets獨立判定十二個actual API案例：

| 條件 | 已核結果 |
| --- | --- |
| min_lots188.693／188.694 | 前者含5274，後者排5274。 |
| min_turnover1164617657／1164617658 | 前者含3293，後者排3293。 |
| min_range_pct2.770／2.771 | 前者七股，後者排3293。 |
| day_move up／down／flat | up＝5347/6488/8069；down＝3105/3293/5274/6510；flat＝available0。 |
| foreign／20／-319.920與-319.919 | 前者5股含6510，後者4股。 |
| trust／5／-66.756 | 6股，排6510。 |

First harness已完成ONE request後因 `code`對actual `symbol`的KeyError raw1，首結果七股獨立接受且不重跑；剩11案沿SAME finite plan完成raw0。First large raw output被truncated，不稱完整APIresponse輸出；FULL financial原件另由ROOT獨立核實。錯猜local cachedPOST focuspath先405，修正ONE actual capture endpoint才409/alreadyattempted，source22/private26不增，兩者均非upstream POST；58 preFIRST API/proxy guards受驗、IO0。原failed CLI `--keys`／offscreen HTML／Control+A selectionmiss留task，不改寫通過。

ONE intended page `12403d60-029f-4ed0-9a5f-1a09929549e4`；desktop1277×924/doc1262及narrow390×844/doc375/scroll375皆actual七卡positive且無horizontal overflow。新profile foreign20 negative cards6488 `-14155.476`張、6510 `-319.92`張、8069 `-9278.025`張已native受驗；不retroclaim舊calendar formatter。Observer80events＝45click/30input/3change/2submit ALLisTrustedtrue，含missteps；無fill/value assignment/fakeevents。

All7同cutoff detail均經native focus/Enter與明示read，完整18原price欄／SHA／provenance、六net及ALL25×6calendar由ROOT對original held body／private snapshot獨立核對。新五股3293窄版、5274／5347／6510／8069，以及本newroute3105／6488皆實跑；各單日1K／MA未支援。6510原source delta `-50.00 `尾空白保持，與C−O的−70分開。Native back核全部八RAW／private counter不增；可信Backspace/inserttext高張1000000.000得到fullseven available0，restore七卡及八RAW已核。

### 42.3 Current failure、未跑項與剩餘能力

ONE API normal Ctrl+C退出raw1後，same5274 native Read具positive ResourceTiming actual502，先前positive價量／price raw/chart與法人nets／calendar/dailyraw同時mask，canvas0/alltables0。Native back＋focus Read再核actual502、cards0／countunknown、FIRST及joint disabled／全部八RAW保留。未restart／retry／actual recovery；missing-private-file與post-stop recovery NOT RUN，僅synthetic契約驗證。

ONE preview normal Ctrl+C raw1；ROOT核五ownPIDs absent、8799/8800無listener；ONE intended page normalclose、fresh tabs[]。Final proxy26GET/1POST/27rejected為local，非financialGET。19 memory SQLite全schema/index/trigger/values/everycelltypeof保持，guards0／financeSeed0／preloadedfalse／formalDB0／privatewrites0／newproductdisk0／childactualIO0。必要checks、原exit與清理邊界見[開發入口](development-baseline/README.md#m1-saved-price-chips-focus-stock-scope-7-1006-1-七股八條件的零落盤驗證入口)。

Coreoperation+1／standalone coredependency0／reliability+1（新scope7 aggregate int64 overflow guard）／stall0→0；source20已接受、DOC/freeze/qualified index/Git仍待ROOT。新七股daily raw追溯不等於每日net圖／精確日期表／running cumulative已交付；下一 `M1-CHIPS-STOCK-SCOPE-7-DAILY-NET-TREND-20-1006-1-B1`未准入，見[執行清單](ROADMAP_EXECUTION.md)。完整ROADMAP、ordinary20/21closes／trend／strategy／time／PIT／Plan／execution未完成。

## 43. M1-CHIPS-STOCK-SCOPE-7-DAILY-NET-TREND-20-1006-1：七股每日淨超與累計操作

ROOT有限接受同explicit2026-10-06的chips-only七股操作。新policy／profile／完整來源與int64累計契約只由[來源 §38](SOURCE_REGISTRY.md#38-m1-chips-stock-scope-7-daily-net-trend-20-1006-1七股每日法人淨超與窗口累計)管理；§42 saved/chips及old calendar、失敗／未跑與版本pending歷史不改。本批不讀保存價格，不以法人每日net冒稱股價趨勢或完整M1。

### 43.1 新入口、明示動作與追溯

Route `/chips-stock-scope-7-daily-net-trend`、compile `VITE_CHIPS_SERIES_STOCK_SCOPE_7=m1-v1`及runner `--chips-series-stock-scope-7-opt-in`；old flags保持獨立。GET `/api/chips/series-stock-scope-7?as_of=2026-10-06`，body0；POST同route的 `/capture?as_of=2026-10-06`，empty JSON object≤4096B。兩端只接受exact as_of key各一次；duplicate／unknown／invalid先拒，合法unsupported cutoff在state／IO前unavailable。Investor／horizon是UI RAW controls，不能寫成GET或capture query keys。

選外資（不含外資自營商）／投信／自營商及5／20日，七股卡→同截止daily detail→back保留as_of／investor／horizon三RAW。明示「首次取得來源（僅一次）」或「明確讀取已持有來源」；套用、切股、法人／窗口及返回不auto-fetch／read。FIRST latch已用不能再取得。Detail列兩SVG每日淨超／窗口累計、精確日期表（股／張）、窗口起迄及累計起點0；SVG比例只供定位，dated operable point與row開原25字串／ordinal／兩SHA／calendar，不用圖形約值作精確數值。

### 43.2 Actual正負值、每日零與42窗口

ONE intentional page。Desktop1277×924／doc1262：ROOT把七股×三法人×兩窗口的42份日期表及兩SVG aria值完整比對original signed arithmetic；ALL525 prefixes／42期末值受驗，5日窗口從本窗口首日前0重算。All7 foreign20的首／末point均核ALL25原字串與body／original receipt SHA。

Narrow390×844／doc375／scroll375無horizontal overflow；ROOT核all7 foreign5卡／samecutoff detail／表與兩圖／三RAW返回。ROOT逐一native開啟ALL25 calendar原列，核150原字串與原receipts，10/07保留但排除。Actual negative每日／累計值沿signed精確股／張；外資口徑保持。

Actual verified zero為3293／trust／2026-09-29 ordinal221，日期表row及每日SVG point回指original25欄。「已驗證當日淨超為零」僅指該日；ALL42窗口totals皆非零，沒有actual whole-window zero驗收。Synthetic zero-window契約不能取代實際零窗口。

### 43.3 Unsupported、current failure與未跑項

Native 10/07日期mask全部數值；恢復10/06仍masked，須明示held READ成功才恢復same generation／Source22，ROOT已核。FIRST不能重複；完整local cached POST核409／already_attempted且Source22不增。兩次local cached POST：首harness cap8193 short read raw1；修正後再核完整10303B HTTP409／already_attempted local rejection response，無financial GET retry。

API normal Ctrl+C rawexit1後，5274／foreign5明示READ的owned proxy完整response502／owned_api_unavailable由ROOT獨立接受；UI mask ALL SVG／日期表／raw／calendar。Native back、改dealer20及cards READ不能unmask。瀏覽器positive502 ResourceTiming未觀測，不宣稱該RT斷言通過；沒有post-stop restart／actual recovery。

Observer477 events＝154click／263keydown／26input／24change／10submit，ALLisTrusted=true，無fill／value assignment／fakeevents。Offscreen HTML click、錯誤--keys／linklabel、ConPTY511-char reviewinput、PRE keyboard tab focus與RT assertion失敗原收據留task；它們不是已通case，也不改寫成product/source failure。Actual僅採ROOT具名接受證據。

### 43.4 退出、進度與使用者暫停

ONE API原source22不變、guards0，normal Ctrl+C rawexit1；成功preview SAMEhandle normal Ctrl+C亦rawexit1，local proxy8GET／3POST／34reject非financial。Preview最初一次BEFORELISTEN失敗（local DNS／CSS），SAME角色修ONE preview file後一次成功；不是只有一次preview attempt，API沒有重啟，FIRST前source0。

ROOT核五owned PIDs absent、8801／8802無listener；ONE intentional page normalclose、fresh tabs[]，原receipt留task。必要checks及限制見[開發入口](development-baseline/README.md#m1-chips-stock-scope-7-daily-net-trend-20-1006-1-七股每日淨超的零落盤驗證入口)；privateactualIO／newdisk／正式DB／upstreamPOST0，無source／service／browser restart。

Coreoperation+1／standalone dependency0／reliability+1／stall0→0；此處接受daily-net圖／日期表／window-reset累計，不解除ordinary20／21closes、股價trend／strategy／PIT／execution。使用者「這裡做完先幫我停下來」：本批DOC／freeze／索引／commit／另准local master merge後暫停；文件截止版本封存仍待。下一普通股收盤序列與趨勢候選等待恢復及新准入，current四角色／worktree保留，不建立下一輪。

## 44. M2-OFFICIAL-EVENT-DATE-RANGE-20261008-1：官方事件日期區間與研究往返

ROOT已有限接受 `official-event-focus/p3-v1` 的effective date區間、搜尋、真零與同截止往返。只沿[來源 §39.1](SOURCE_REGISTRY.md#391-m2-official-event-date-range-20261008-1實際來源結果)的本次exact TWT48U觀測；§12／13舊版本與58列歷史不改。範圍是觀測feed的身分／日期／分類及來源追溯，不是全市場完整事件、普通股身分／行情或PIT。

### 44.1 請求、順序與計數

`GET /api/focus/official-events`及明示首次`POST /api/focus/official-events/capture`均要求as_of，optional q／from／to。日期須有效ASCII YYYY-MM-DD且非0000年；缺側不限，已提供empty、無效日期、from>to、duplicate／unknown keys在source／catalogue前HTTP422。q沿§13原100 Unicode字元上限、先長度後strip、casefold literal substring。原件完整身分／日期／分類、receipt／pins／hash及觀測截止全部通過後，才逐event按effective date含首末篩選、依標的分組、按來源Code或保留事件Name搜尋、symbol排序及cap100；區間外／搜尋外／cap外壞列不得跳過。

| 回應欄位 | p3-v1語義 |
| --- | --- |
| candidate_count／selected_count | 全合格feed事件列數，range／q不改。 |
| total | 全feed去重標的數，range／q不改。 |
| effective_from／effective_to | canonical邊界或null。 |
| range_event_count | 區間內事件列數，先於q。 |
| range_matched | 區間內去重標的數，先於q。 |
| matched | 區間內再符合q的標的數，先於cap。 |
| displayed／truncated | min(matched,100)／matched>100。 |

每卡只保留該股落在區間內的合格事件；任一保留Name或Code符合q即可留下該卡全部區間內事件，保持原件ordinal。available真零與unavailable／未知分開；不得拿初始零計數當已驗空原件。

### 44.2 提交、同截止返回與共用URL

日期／q draft須明示提交後才查詢；查詢key含as_of／q／from／to，條件切換不沿用舊成功卡片或count。清除日期／搜尋維持研究截止。首頁原張／方向／成交額／振幅四條件仍相容，事件提交保留它們；q／from／to只作共享首頁狀態，不送價量API。

已知catalogue detail固定`/stocks/TWSE/{symbol}`，帶as_of、from=official-events、focus_as_of／focus_q與可選focus_from／focus_to。返回固定首頁official-event-focus-title anchor並恢復原as_of／q／from／to；個股內改as_of不改原清單截止。安全URL／日期／query multiplicity與回應條件驗證仍必須通過，不接受任意return URL。三instrument synthetic catalogue只證routing；來源卡名稱不由catalogue覆寫，無M1入口仍保留事件。

### 44.3 本次真來源及具名接受邊界

本次Taipei2026-10-08 ONE fresh GET為62事件／62標的；ROOT逐列日期／分類／名稱／ordinal與actual API一致。具名接受：as_of10/08全62；10/01～12/31 62；10/22＋q0056 1；to10/22含首末58、from10/22含首末5；01/01～01/02 available真零，清除條件恢復。q trim、重複GET／POST及focus／selected共用held原件不增加金融GET；as_of10/07觀測晚於截止，unavailable。

Desktop1365×900：0056日期22 draft套用前不查詢、提交後1卡、detail同10/08；M1改07再返回仍為原08＋q＋range。Narrow390×844：Jan1～2真零、清除日期／搜尋、1463detail往返均受驗且無horizontal overflow。這些依實際可信事件接受；offscreen／type ACK／Ctrl+A未選中等工具失敗不算操作成功，原failed receipts留task。

停止API後native讀取回本地proxy502，cards清0且count清除，不保留成功狀態，不把失敗當真零。首次取得前全feed先驗才publish；focus／selected共享首次attempt及失敗seal，首次失敗耗額度，換入口不再取。這項可靠性有必要記憶體邊界驗證，不宣稱本次真金融GET曾失敗。原件／receipt只RAM，API結束後釋放，沒有重播／restart／durable保存。

### 44.4 尚缺與後續

Coreoperation+1／dependency0／reliability+1／stall0→0。發布／first availability／revision／歷史PIT、事件價格影響及完整M1／M2／M3仍未驗。下一候選息／權／權息類型組合日期／q與同截止往返，雖有本次三分類來源路徑，仍須新ROOT核新quota／pins／具名驗收；本批金融GET與metadata均SPENT，不復用producer或已釋放原件。必要checks／原失敗及owned runtime退出見[開發入口](development-baseline/README.md#m2-official-event-date-range-20261008-1-官方事件區間的零落盤驗證入口)。

## 45. M2-OFFICIAL-EVENT-KIND-20261008-1/B1：官方事件精確類型與研究往返

2026-10-08。ROOT已有限接受新 `official-event-focus/p4-v1`：官方事件精確類型配effective inclusive日期／q、原事件trace、同cutoff M1及原五條件安全返回。新真原件62事件62標的，息55／權6／權息1；来源及完整body／ORIGINAL receipt雙SHA由[來源准入](SOURCE_REGISTRY.md) §40管理，原§44與舊pins不改。

### 45.1 類型、篩選與精確計數

home／API `event_kind` 為精確 all／ex_dividend／ex_right／ex_right_and_dividend，分別全部／息／權／權息；息不含權息。日期grammar／range／q／kind／duplicate／unknown先於source及catalogue拒422。完整feed與receipt先驗，再逐event range→kind，group及q→code排序→cap100；每卡只保留range＋kind真匹配的原events、日期／分類／ordinal與雙SHA，來源名稱不由synthetic catalogue覆寫。

| 欄位 | 精確語義 |
| --- | --- |
| candidate_count／selected_count／total | 全合格feed事件列數／全合格feed事件列數／全feed去重標的數；range／kind／q不改。 |
| effective_from／effective_to | canonical日期邊界或null；含首末日、缺側不限。 |
| range_event_count／range_matched | range後、kind與q前的事件列數／去重標的數。 |
| event_kind | canonical精確類型。 |
| kind_event_count／kind_matched | range＋kind後、q前的事件列數／去重標的數。 |
| matched／displayed／truncated | 再q後標的數／min(matched,100)／matched>100。 |

任一保留event的Name或Code符合q即可留下該股全部range＋kind事件。available真零可顯示0；unavailable／失敗不得保留成功卡、count或provenance，也不冒稱真零。

### 45.2 明確套用、共用URL與返回

日期／q／event_kind皆draft，明確提交後才查詢；query key與response guard含event_kind，切換條件清舊成功狀態。清類型還原all且保留q／date／as_of，清日期或清q保留kind。四price條件共享首頁URL相容；事件參數不送price API。

已知catalogue detail固定`/stocks/TWSE/{symbol}`，帶as_of、from=official-events、focus_as_of／focus_q／可選focus_from／focus_to及focus_event_kind。返回固定首頁official-event-focus-title anchor，恢復原as_of／q／from／to／event_kind；M1內改as_of不改原清單截止。日期／query multiplicity及safe local URL／回應条件仍須驗，不接受任意return URL。synthetic4（0056ETF／1449／1463／2614）只證routing，無M1入口仍保留事件。

### 45.3 本次具名actual接受

FIRST前8invalid422／source_gets0；新generation一金融GET後15focus＋8detail cutoff＋4cached POST＋4unavailable接受，外網仍1。Desktop1365×900：1449權10/12 range1／kind1／q1、0056息10/22 1／1／1、2614權息10/06 2／1／1，原ordinal分別49／5／53及雙SHA可追溯。draft不先套用；1449同08進M1、改07 unavailable、返回原08及五條件已核。

Narrow390×844：2614權息、1449權、1463息（10/15 range2／kind2／q1，ordinal50）positive；1463 M1同08改07後返回原08五條件；1463權10/15 available真0。清類保留q／date／as_of，清日期與q保留kind，cutoff07 unavailable→08恢復均受驗，無horizontal overflow。

API停止後same-key READ與cross-kind ex_right apply是真實trusted操作，本地502且cards／count／provenance清0。曾ACK未delivery的讀取不算成功；typed tab switch --focus恢復可見輸入後才接受。首次offscreen／日期fill ACK未改值等原失敗留task，不宣稱金融GET失败、不改產品碼或新增reliability；Date是生效日，不代published／availability／PIT。

### 45.4 清理、版本與尚缺

API48848／preview10296／compiler46848 absent、8803／8804無listener；ownedpage close／tabs[]。API與preview正常SIGINT均raw1；API無shutdownprint，preview有shutdown／loopback31GET＋1POST／rejected0／guard0／disk_artifact0。原件RAM隨API退出釋放，無restart／replay／hydrate；privateIO／新增test及product檔案0B，indexcache另報。必要checks與原失敗見[開發入口](development-baseline/README.md)。

Coreoperation+1／standalone dependency0／reliability0／stall0→0；不驗ordinary／fullmarket／price、payout numeric／PIT／forecast／Plan／save，完整M1／M2／M3未完成。SOURCE9＋DOC6待ROOT review／freeze／索引／commit／merge；下一核心由ROOT另核，不機械延filter或重審無新path。接手及前任精確清理見[協作紀錄](TASK_COORDINATION.md)，收據留原task，不回寫hash。

## 46. M1-TWSE-ISSUER-EVENT-PROFILE-20261008-1/B1：真公司原欄位與同截止事件研究

2026-10-08。ROOT已有限接受 `twse-issuer-event-profile/m1-v1`：1449／1463／2614真TWSE原Code／全名／簡稱／出表日期／上市日期／行業原碼及trace，配同cutoff官方事件，再回原五條件。1095公司／58事件全原件、dualSHA／ordinal／原始欄位由[來源 §41](SOURCE_REGISTRY.md)管理；原四源／defaults／pins及§45保留，catalogue只供routing，不能證普通股或ETF身分。

### 46.1 明示取得與原欄位

先明示取得本次官方事件，再以公司「讀取本次公司基本資料」送 `POST /api/stocks/TWSE/{code}/issuer-profile/capture?as_of=2026-10-08`、body `{}`；issuer只支持1449／1463／2614、本cutoff及獨立外部pins。new empty producer各single attempt／FIRST失敗SPENT；同程序其他選定代號／重複POST／GET只用已核cache，不新增外網。missing／較早cutoff／unsupported／未取得皆保留unavailable，不能補0／較早fallback；0056公司不支持，文案不暗示ETF類型。

公司headline用同cutoff受核原簡稱；完整公司全名與原eventName各自保留，Code exact join、eventName須等於issuer全名或簡稱，否則unavailable。raw report／listing／industry及原ordinal／body與receipt SHA可展開trace，report／listing raw＋ISO與event effective Date分列；published／availability／revision未知、nonPIT，不作ordinary／產業名稱／分類品質／行情／capital或payout數值結論。原industry04／20保持字串，不以未准入碼表翻成名稱。

### 46.2 本次 actual positives 與安全返回

API20 TestClient calls：FIRST前8invalid issuerPOST全422／sourceGET0／DB0，初始1449unavailable；三detail positive＋三cachedissuerPOST／missing-cutoff／07／0056unavailable／1449恢復08受驗。1463權10/15 available真零：全feed58、range2、kind0、items[]，不是公司缺證或失敗當零。

Desktop1365×900及narrow390×844三股：1449佳和／權10/12、1463強盛新／息10/15、2614東森／權息10/06；六原公司欄、上市raw／ISO、industry04／04／20、原事件Date／Name／Exdividend、雙trace展開與原件雙SHA已核，無horizontal overflow。Narrow1463權10/15真0／0056unsupported、missing-cutoff兩viewport受驗。2614可信native07 unavailable→08cache恢復，再改07後安全返回原清單08／q2614／from=to10/06／ex_right_and_dividend五條件；M1改cutoff不改原focus_as_of／focus_q／focus_from／focus_to／focus_event_kind。原p4-v1 draft／apply／clear語義保持；這些日期是來源／研究／事件生效角色，不代歷史可得性。

### 46.3 真失敗清值與執行邊界

API正常STOP後，same-key1449可信native公司READ POST實際502，headline改公司名稱待核對，issuerRows0／eventRows0／provenance0；crossselected1463GET502整頁error／fields0，均為失敗拒用，不算positive。network request IDs `51488.115`／`51488.121` 留task。先前selector／offscreen／ACK未delivery／syntax與inspection錯誤原exit保持，只有實際狀態效果才計接受，不把工具錯誤當來源／MCP失敗或reliability增量。

API26328正常STOP raw0／server_stoppedtrue／兩source_gets各1／四audit0，RAM原件已釋放。修字前preview46188／compiler25556 normalSIGINT raw1／shutdown GET35 POST7 reject0；修字後只RAM rebuild preview34000／compiler61744 normalSIGINT raw1／shutdown GET3 POST1 reject0，API未restart／無新金融GET，兩preview guard／artifacts0。ROOT核5PID absent、8805／8806無listen、唯一ownedpage `9b4d13a6…` 正常closed／tabs[]，所有test／product／artifactfiles0B／privateIO0；shared indexcache另報。必要checks與原失敗見[開發入口](development-baseline/README.md)。

本批coreoperation+1／standalone coredependency0／reliability0／stall0→0；完整M1／M2／M3未完成。未驗ordinary／0056ETF／industry名稱／可信排名／groupmembership／fullmarket／price history／capital與payout數值／PIT／Plan／保存。SOURCE13＋DOC6版本封存待ROOTreview／freeze／索引／commit／另准merge，下一產業trace尚未准入，見[協作紀錄](TASK_COORDINATION.md)／[執行清單](ROADMAP_EXECUTION.md)。

## 47. M1-TWSE-ISSUER-INDUSTRY-TRACE-20261008-1/B1：公司原碼與產業名稱追溯

2026-10-08。ROOT已有限接受SOURCE12、41backend／7warnings與45src noEmit＋71targetchecks raw0、完整fresh originals／21 direct API、可信desktop／narrow具名操作及停止後failure clear。來源／新pins見[來源 §42](SOURCE_REGISTRY.md)，兩碼及日期邊界見[產業 §10](INDUSTRY_CLASSIFICATION.md)，必要驗證見[開發入口](development-baseline/README.md)。

### 47.1 同截止與獨立名稱區塊

`twse-issuer-industry-trace/m1-v1` 是detail `overview.issuer_industry_trace` 新pure-read投影；原 `twse_issuer_profile` v1／六原欄／Code與Name join／capture端點保持，產業不另建capture endpoint或taxonomy GET。先明示取得本次事件，再公司READ沿§46 issuer POST；兩NEW empty producer各attempt1，cachedPOST／其他selected detail GET只用本程序cache。需要 `STOCK_TWSE_INDUSTRY_TRACE=1` 及獨立registry／consumer四external version-digest pins；無pin／缺證unavailable，不升default。

「產業名稱與碼表追溯」顯示1449／1463原04配紡織纖維、2614原20配其他，公司分類生效日明示未知；原Code及名稱分欄、TWSE署名、B.12.00／2023公告／分類規則第2條三official links保持完整。展開「查看產業名稱版本與來源追溯」顯示引用version／metadata observed、issuer／event ordinals、兩sourceversion／body及receipt雙SHA、registry／canonical引用宣告pin與所有日期角色；清楚說明宣告SHA不是PDF／公告／規則原件SHA、沒有原始文件擷取紀錄。

same cutoff須共同核issuer六原欄、exact exchange／code與eventName等於原full_name或short_name、完整原件pins／SHA／觀測日及精確兩碼宣告。missing-cutoff／earlier07／0056unsupported／其他raw碼／特殊或停用碼／名稱或source conflict均保留unavailable，row／provenance為null，不補名稱／零／較早fallback、不用Other吞unknown。原profile classification仍unsupported；新名稱不證ordinary／ETF／membership／完整current分類／排名／行情／PIT。

### 47.2 本次實際驗收與安全返回

ROOT21 direct API已核FIRST前8 invalid422／sourceGET0／DB0、三股同cutoff真碼名／雙原件trace、三cachedPOST、missing／07／0056 unavailable及08 restore；1463權10/15清單真零仍58／range2／kind0／items[]，不是公司分類缺證當零。原focus `official-event-focus/p4-v1` 類型／q／effective from-to語意與五個原條件保持。

可信desktop1365×900及narrow390×844三公司六原欄、原04／04／20配紡織纖維／紡織纖維／其他、三事件型、三完整展開引用trace／issuer與event dualSHA／ordinals、公司分類effective未知、safe back原as_of／q／from／to／kind、nooverflow全部受驗。Native select除權→apply為1463真零：total58／range2／kind0／matched0；narrow07以day ArrowDown／apply為unavailable（三table0／trace0），ArrowUp／apply08恢復三table，再07detail／back仍保原08五條件。1449 missing-cutoff與0056 unavailable row／trace0，窄390及該case實際桌面1277無overflow；0056不證ETF身分。

API停止後，same-key1449 native公司READ實際讀取失敗，headline改「公司名稱待核對」、公司／event／industry三table0、provenance summaries0，舊fullname及紡織纖維均消失；desktop1365與narrow390已實際核。Crossselected1463 GET實際502／performance responseStatus502、mainerror／values0／provenance0，narrow390無overflow。這是實際拒用與清值，不作positive；requestFailure／response核對失敗不沿用舊query值。

停止前完整same held ORIGINAL identity／dualSHA／全schema再核，sourceGET各1／guards0。API52996正常STOP raw0／server_stopped=true、兩原件RAM釋放；preview55124／compiler31816正常SIGINT raw1／SHUTDOWN GET46 POST7 rejected0／guards與artifacts0。三PID absent、8807／8808無listen、唯一ownedpage `d6ad81a9-215b-433c-b9a7-da164326a12b` 正常close／tabs[]、新test／productartifactfiles0B／privateIO0／DBfiles0已核，不restart／replay／clone／hydrate。原工具失敗／viewport重設及實際效果門檻見[開發入口](development-baseline/README.md)。

本批coreoperation+1／standalone coredependency0／reliability0／stall0→0；只三公司兩碼引用及具名同cutoff研究往返，不外推ordinary／0056ETF／完整current分類／membership／排名／行情／PIT／資本或配息數值／策略／保存／Plan，完整M1／M2／M3未完成。SOURCE12＋DOC7版本封存待ROOT review／freeze／索引／commit／另准merge；下一 gross 買／賣拆解候選 UNADMITTED，詳 ROADMAP／[協作紀錄](TASK_COORDINATION.md)，完成條件見[執行清單](ROADMAP_EXECUTION.md)。
