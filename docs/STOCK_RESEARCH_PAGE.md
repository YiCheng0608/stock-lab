# 個股研究頁契約

更新：2026-10-04。本文定義 `/stocks/:exchange/:symbol` 的現行有限契約；原個股頁 review 範圍見 §5，M1-P1 總覽見 §9，M1-P2b 單日法人見 §10，M1-P3b selected 官方事件見 §11，待做籌碼見 §8；成交量精確呈現見 §14，M3-P6c 個股行情讀回隔離的核定契約與有限接受範圍見 §15。這不代表完整研究產品、R0 或 [ROADMAP](ROADMAP.md) 已完成。

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

API 也沒有 currency 欄位，且標的可能不是新臺幣計價。價格表外統一寫「各標的報價幣別的元」，指數寫「點」；在取得可驗證幣別前，不得一律加 `NT$` 或猜測幣別。

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

來源明確為股數的成交量依 §14 的精確整數字串換算為「張」；法人買賣超仍以 `原值 / 1,000` 顯示為「張」，已核實融資欄位依官方「張」語意顯示。顯示換算不改原成交量、策略計算或 raw evidence；unknown／mixed 時不換算。成交量的核定增欄與圖形近似範圍見 §14；其餘格式、空白與幣別規則見 [UI_COPY_SPEC §10](UI_COPY_SPEC.md#10-壓縮卡詳情與單位文案)。

市場別產業 membership 重建前，個股與行動詳情顯示「既有族群關聯待重新核實」；族群中文名加「（既有分類）」與待核實 badge。不得顯示可信排名或將衍生條件稱為已核實；這不改寫 OHLCV、單位或新聞。相關有限 UI review 只涵蓋文案、空值、法人命名、單位顯示、ETF／族群名稱及官方分點入口，不新增 API、分點資料、歷史 coverage 或主力身分。

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

| 區塊 | 本批結果 | 待補條件 |
| --- | --- | --- |
| 外資／投信／自營商 5／20 日 | 目前 `build_stock_overview` 固定回傳 `institutional.status=unavailable`、`values=null`；原因依單日區塊是否可用而異，不補零、融資不併入。 | 本批採用的 exact 多日法人來源及用途准入、交易日基準、逐法人欄位／單位／缺日 coverage、窗口計算與 API／UI 接線驗收。 |
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
