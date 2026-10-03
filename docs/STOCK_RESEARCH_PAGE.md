# 個股研究頁契約

更新：2026-10-03。本文定義 `/stocks/:exchange/:symbol` 的現行有限契約；原個股頁 review 範圍見 §5，M1-P1 總覽見 §9，M1-P2b 單日法人見 §10，M1-P3b selected 官方事件見 §11，待做籌碼見 §8。這不代表完整研究產品、R0 或 [ROADMAP](ROADMAP.md) 已完成。

## 1. 使用者工作與資訊順序

使用者先確認標的、實際資料區間與價格口徑，再依序讀取行動摘要、日 K／成交量／MA20／MA60、族群、法人籌碼、官方事件／新聞、策略條件，以及 coverage／來源。頁面允許零行動、零新聞、缺籌碼或均線不足；不得為填滿畫面造資料。它不是 AI 選股、下單或完整交易計畫。

## 2. 現有 API 與畫面 cross-review

### 2.1 實際 payload

前端 `getStock(exchange, symbol, asOf?)` 呼叫 `GET /stocks/{exchange}/{symbol}?as_of=YYYY-MM-DD`。`as_of` 可省略；後端組成同一資料日期截止的 instrument detail，再加入 decision summary、coverage、news 與 `overview`。M1-P1 總覽及日期控制見 §9；截止不代表歷史當時可得。

| 區塊 | 實際欄位／上限 | 呈現限制 |
| --- | --- | --- |
| 標的 | `instrument` | 以 exchange＋symbol 識別，顯示名稱與類型。 |
| 行情 | `bars` 最多 120 筆，舊到新 | 含 OHLC、adj_close、volume、turnover、source、data_as_of、collected_at、is_suspended；只代表本次視窗。 |
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
- volume 須為有限非負股數；null、NaN 或負值不補 0，對應列／區塊須標不可用。
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

來源明確為股數的成交量和法人買賣超以 `原值 / 1,000` 顯示為「張」；已核實融資欄位依官方「張」語意顯示。顯示換算不改 API、圖表、策略計算或 raw evidence；unknown／mixed 時不換算。完整格式、空白與幣別規則見 [UI_COPY_SPEC §10](UI_COPY_SPEC.md#10-壓縮卡詳情與單位文案)。

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

- `as_of` 是含當日的**資料日期篩選**，`cutoff_basis=data_date_inclusive`；明示日期不自動往後推。未指定時優先最新儲存行情日；無行情時取其他研究紀錄的最新資料日期，含 active 且時間 verified 的關聯新聞。財報優先公告日，缺公告時的期間日只提供截止基準，不證公告已可得；新聞優先發布、其次事件時間，按臺北轉為日期。無可用日期則為 null，不補今日。
- 同一 response 的行情、技術快照、法人、membership、策略／行動、公司行動、基本面、事件與品質使用同一截止；原資料日、`collected_at`、發布／事件時間保留，不改寫成截止日期。日期篩選不證來源准入、availability、修訂版本或 PIT，`historical_pit=unsupported`。
- 新聞清單在最多 20 筆限制前，依既有已核對的發布／事件時間篩選；datetime 按臺北截止日結束換算，date-only 保留純日期，未知／衝突或超過截止的項目不混入。收集時間不充發布時間。這是既有時間欄位的有限投影，不證事件原件、first availability 或歷史 PIT。
- 日期輸入套用後，URL query 與資料 query 使用同一 `as_of`；「最新資料」移除明示截止並回到 API 的實際資料日期。總覽保留事後研究與歷史可得性未支援的說明。

### 9.2 原件合格的價格視窗

本批只採已准入的 exact `STOCK_DAY_ALL`，來源／用途與 capture gate 依 [SOURCE_REGISTRY](SOURCE_REGISTRY.md#51-stock_day_all-selected-security-bars)，不因 legacy `source=twse`、官方名稱或歷史 P0 結果放行 `MI_INDEX`、TPEx 或其他來源。

先取截止以前最多 120 筆候選行情，再逐筆核對；拒列不另抓更早資料湊滿 120 筆。`candidate_count`、`valid_count`、實際 `from/to`、`latest`、合格 `bars` 與 `rejected[].date/reason` 分開回傳；無合格列時價格 unavailable，其餘研究入口仍可使用。只說本次實際範圍／筆數，不稱完整 N 個交易日；來源本身沒有 TAIEX，不由列數推導交易 session。

每筆合格價須符合：

1. TWSE／symbol／資料日期精確配對，行情經 raw FK 回指指定 `body.bin` 與同目錄 `receipt.json`；原件 hash、capture receipt、成功 HTTP、收集紀錄關聯與 capture time 一致。
2. 使用已 review registry version／digest、exact endpoint／GET 與 source version；`local_fetch`、`raw_store`、`summarize` 用途及必要 conditions 通過，保留顯名、授權與可追溯來源。
3. selected 原件 O／H／L／C、成交量、成交額狀態與保存列一致；OHLC 為正有限數且範圍合法，成交量為非負精確整數。重複日期拒用；缺 selected row、停牌、數值或證據無效保留具體原因。
4. 合格列保留 raw／ingestion identity、body／receipt SHA-256、來源／registry 版本、endpoint、capture／原收集時間；details 可核對每筆價格與來源。這只證**本地原件與保存值一致**，不是來源真偽、完整歷史、revision 或 PIT 的證明。

價格沿用 §2.2 原始 API 口徑與報價幣別限制，不產生 adjusted OHLC。成交額 unavailable 在總覽輸出 null、保留 status／reason；來源合法零仍顯示零，不把保存用的缺值 `0` 當有效來源零。既有 `detail.bars`／K 線仍是按日期篩選的原研究資料，不會因新增總覽而自動升格本批准入來源或完整窗口；頁首新報價取總覽合格 `latest`，不從 legacy 行動價或不合格 bar 補值。

### 9.3 法人、條件與新聞入口

| 區塊 | 本批結果 | 待補條件 |
| --- | --- | --- |
| 外資／投信／自營商 5／20 日 | `institutional.status=unavailable`、`values=null`；顯示法人來源及交易日基準尚待核對，不補零、融資不併入。 | T86／dailyTrade 等所採 exact 來源及用途准入、交易日基準、逐法人欄位／單位／缺日 coverage 與窗口版本。 |
| 突破／回踩條件 | 沿用 `breakout_v1`／`pullback_v1` identity，列既有結果日期／版本；本批均為 `data_insufficient`，附來源、時間、分類及結果缺失／早於截止的原因。 | 必要輸入、來源、時間與分類 gate 具體滿足後才可判「成立／未成立」；requires、過期 signals 或價位存在都不算通過。 |
| 新聞與官方事件入口 | 可切到既有新聞／公告分頁，保留原時間與來源連結；`events.status=unavailable`，顯示原件 consumer 與來源時間待驗。 | 具名事件原件、consumer、發布／事件時間、來源用途與相應 coverage 驗收；入口不是已驗收催化劑，不推論價格影響。 |

M1-P2a 另 explicit TPEx 日法人 capture／selected 摘要 library／CLI 已有限 review，契約與單日兩檔支持範圍見[來源 §8](SOURCE_REGISTRY.md#8-m1-p2atpex-日法人來源與-selected-摘要)。M1-P2a 本身未接總覽 API／UI 或 5／20 交易日窗口；後續 M1-P2b 的獨立單日原件接線見[第 10 節](#10-m1-p2b單日法人原件總覽接線)，上表多日 `institutional` unavailable 契約維持，單日 CLI 數值不作前端 fallback。

後續 M1-P3b 已以獨立觀測日期 gate 接 selected 官方事件，具名支持範圍見[第 11 節](#11-m1-p3bselected-官方事件總覽接線)；發布／首次可得時間仍 unknown，完整事件 coverage 與研究條件缺口保留。

既有分類待核實提示與原策略、價位／信心語意保留；本批沒有新評分、機率、完整交易計畫或張數。缺來源只讓相關總覽區塊保持 unavailable／資料不足，不將本批價格交付擴寫成完整 M1。

### 9.4 本批有限驗收與待驗

統籌已有限接受 **TWSE 1101、2330，來源資料日 2026-10-01 的單日 selected 真實樣本**：單次 exact `STOCK_DAY_ALL` capture 經既有 loader／select、記憶體 SQLite 到真實 API 的 OHLC、成交量、成交額六欄與原件逐欄一致；`as_of=2026-09-30` 排除 10 月 1 日資料。這不代表完整 collect、磁碟 DB 或正式 DB 驗收。

有限產品操作包含桌面個股目錄進入 2330、總覽數值、來源 details／hash、新聞入口、日期套用與「最新資料」復原；窄版初始單欄與展開來源 details 未見 body 橫向溢出。來源 schema 可對同 gate 的 TWSE selected rows 逐列核對，但本次真實驗收範圍只含上述兩檔／單日，不外推其他標的、TAIEX、TPEx、多日價格、完整 session 或法人數值。

後端最終來源復核再次確認兩檔六欄與原件一致、完整 detail 的總覽與獨立總覽端點相等；9 月 30 日截止排除 10 月 1 日，10 月 2 日截止保留 10 月 1 日且標示最新價格早於截止。新增邊界回歸已通過：Windows 檔案讀取／變更拒收、來源 gate、合法零／缺額／非有限值、空標的／非法日期、無行情／只有新聞／財報公告截止、SQL NULL、臺北跨日與超過 200 筆新新聞的 limit 前篩選、legacy 相容；測試收據留本輪 task。

前端型別、總覽 React SSR 顯示檢查與 production build 已通過；大型 JS chunk 警告仍在。本輪 M1-P1 的程式與具名驗收已接受並有限 review，freeze／索引／commit 收據留本輪 task。完整 M1、R0／R1 及 R2-E1 整體均未完成；下一個可行子能力是法人與交易日來源准入後的可驗窗口，不能由本批直接宣稱 M2 已可完成。

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

統籌以既有核定 ZIP、實際 API router 與記憶體 SQLite，獨立核對 **TPEx 3105／6488、2026-10-02** 各十個數值與原件逐欄一致、完整 detail 的總覽與獨立總覽端點相等，資料日、雙 hash、固定 pins 與列序正確，ZIP 讀前後不變。前端 SSR 核對兩檔數值／日期／追溯欄位、int64 邊界與拒收呈現，後端記憶體靶向回歸及本批不落盤型別檢查通過；記憶體 esbuild 全 App bundle 成功，並用於下述真實瀏覽器操作。完整 backend 與 production Vite build 本輪未跑，不能把記憶體 bundle 或 P1 結果當 P2b 的新 production build 驗收。

真實瀏覽器桌面已核對 3105、從個股入口進入 6488 再套用 10 月 2 日，各十個數值正確；來源顯名／連結、展開雙 hash／列序與日期／版本可讀。`as_of=2026-10-01` 排除 10 月 2 日，10 月 3 日截止保留 10 月 2 日並提示尚未確認截至日前最新資料；「最新資料」清除明示截止後，測試用記憶體 DB 無其他 dated rows 時維持無共用截止，不由法人設定補日期。390×844 窄版展開雜湊的換行修正已複驗，body 無橫向溢出，表格自身可水平捲動。程式、上述具名操作與有限驗收已由統籌接受，不外推其他標的、多日或正式 DB／持久化。

失敗、退修及最終命令、exit、測試與 freeze／索引／commit 收據留本輪 task。本輪新增測試產物為 0，額外落盤測試配額亦為 0；測試／清理限制見 [TASK_COORDINATION](TASK_COORDINATION.md)。

`institutional` 的 5／20 日 `values` 仍為 null；單日可用時，窗口缺口須精確表示 `multi_session_institutional_evidence_missing` 與 `trading_session_source_not_admitted`，不能再把已准入 TPEx 單日來源說成未准入。單日區塊的 `session_windows` 同樣 unavailable。本批無新交易日曆准入，不接 TWSE T86、DB／legacy、預設 collector、多日彙總、事件或完整研究條件；`historical_pit=unsupported`，完整 M1、M2 及 R0／R1／R2-E1 仍未完成。

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

統籌於 **2026-10-03（臺北）** 已有限接受真實畫面首次取得按鈕經專用 POST → actual capture → consumer → API；未 mock transport 或返回。普通 GET 後外網取得次數為 0，按鈕後為 1；當次 HTTP 200、單一 GET、原件 58 列，capture UTC `2026-10-02T23:28:41.219715+00:00`。以同一份真原件按 ordinal 逐列核對如下 selected；全部保留未來生效日期：

| Code／Name | 原 Date → 生效日期 | 原分類／顯示 | 原件列序 |
| --- | --- | --- | --- |
| `0056`／元大高股息（ETF） | `1151022` → 2026-10-22 | `息`／除息 | 5 |
| `1449`／佳和 | `1151012` → 2026-10-12 | `權`／除權 | 49 |
| `1463`／強盛新 | `1151015` → 2026-10-15 | `息`／除息 | 50 |

三個標的的 detail `overview` 與獨立總覽相等；10 月 2 日截止全部拒收、`rows=[]`／`provenance=null`，缺截止不補觀測日。再 POST 1449 重用同 cache，外網取得次數仍為 1；原件／receipt 的雙 hash、原中文四欄與列序已核對，獨立 Python assertions 通過。Harness 的記憶體 catalogue 只提供測試路由 metadata，不代表真行情、磁碟 DB 或正式 DB 證據。

桌面 **1365×900** 已具名核對 0056 首次取得、ETF 名稱／除息／10 月 22 日、展開原民國日期／分類／列序 5／雙 hash／UTC raw time，以及 TWSE 顯名、OGL1.0 與 license href。10 月 2 日截止排除事件；「最新資料」移除 query 後，minimal catalogue 無其他 dated rows，保持 `as_of=null`／事件 unavailable；套回 10 月 3 日恢復，再讀未取得新原件。從目錄進入 1449／1463，名稱、除權／除息與 10 月 12／15 日均已核對。來源／授權 href 已檢查，未另開外網。

**390×844** 窄版在 1463 展開來源 details 後，body 無橫向溢出；事件表可在自身範圍右捲到生效日 10 月 15 日，未迫使整頁橫向捲動。最後取得次數仍為 1、cache bytes 與雙 hash 相同；按鈕／日期操作不稱背景或最新 feed 更新。

後端最終靶向記憶體回歸通過；先前 P3a consumer 回歸仍對應未變 worker，不外推完整 backend。前端型別與既有價格／法人、新增事件 SSR 通過，記憶體全 App bundle 用於上述真實 UI 操作；完整 backend 與 production Vite build 本輪未跑，記憶體 bundle 不能稱 production build。最小 fixture 不替代 live 來源證據，這次 live body／receipt 未保存，不能離線重播；先前失敗、退修後成功複驗、命令、版本、exit、hash 與 freeze／索引／commit 收據分別留 task。

本輪新增測試附件／產物為 0，專用前後端 process 已終止、memory body 隨 process 釋放，測試 tab 已關閉並還原 viewport；舊落盤殘留與清理拒絕保持原限制、不重試。額外測試落盤配額為 0，入口限制見[開發與驗證入口](development-baseline/README.md)。

完整 M1 仍缺可驗 5／20 交易日窗口與成立／未成立研究條件；本批不接 DB／legacy、新聞群組／更正／撤回史、自動排程或交易，不增加 R0／R1／R2-E1 整體完成度。

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

統籌於 **2026-10-03（臺北）** 接受一次實際首頁首次取得按鈕 → focus POST → exact TWT48U capture → consumer → API：HTTP 200、`request_count=1`、`capture_calls=1`，capture UTC `2026-10-03T02:03:07.107068+00:00`；body **15,689 bytes、58 列／58 個不同代碼**，`total=displayed=58`、`truncated=false`。全 58 列的 `Code`／`Name`／`Date`／`Exdividend` 與 1-based 列序逐列對 API 一致；未驗金融欄位仍未公開。本次 feed 每股一個事件，同股多事件及超過 100 股的情境另由 fixture 核對，不把這次 live 當成該邊界的真實案例。

同一份原件供 M1 **0056／元大高股息（ETF）、1449／佳和、1463／強盛新** 使用，detail 的總覽與獨立總覽同一 `as_of`、selected rows 及雙 hash 一致；`as_of=2026-10-02` 排除本次觀測。0056 的原值 `1151022／息／列 5`，1449 `1151012／權／列 49`，1463 `1151015／息／列 50` 已核對，未來生效預告保留。Harness 的記憶體 catalogue 只提供上述三標的路由 metadata，其餘 **55 股**保留來源名稱／事件但無個股連結；這不是正式 catalogue、真行情、磁碟 DB 或全市場 coverage 驗收。

桌面真畫面已核對首次按鈕取得 **58 張卡**、10 月 2 日截止無卡且提示排除、套回 10 月 3 日恢復同 58 卡／同 cache；來源／授權入口、0056 原件值 details 及進入同截止 M1 已核對。新聞區空文字曾與上方已取得事件矛盾，局部文案退修後以同一 live cache 複驗通過，不改寫其他新聞頁或新聞 API。

**390×844** 窄版已核對 58 卡、日期控制、讀取已取得原件、來源 hash 換行；document scroll width **375 < 390**，表格在自身範圍水平捲動，沒有迫使整頁橫向捲動。從 1463 進 M1 保留同截止，10 月 15 日除息可讀。截止、讀 cache 及詳情往返後取得次數仍為 1，不稱最新 feed 或背景更新。

後端純記憶體 consumer／API 必要回歸、非 available 無頂層 `rows` 的退修複驗，以及前端型別／SSR／記憶體全 App bundle 通過。合法空 feed、同股多事件、100 股截斷、unknown catalogue、receipt／pins／分類拒收與取得鎖等 fixture 情境只證實作邊界；**完整 backend／production Vite build 未跑**，記憶體 bundle 不能代替 production 驗收。本次 live body／receipt 未保存，**不能離線重播**；命令、版本、exit、hash、失敗／退修與成功複驗，以及最終 freeze／索引／commit 收據留本輪 task，不另存附件。

測試與清理分報：QA tab 已關閉、viewport 已還原；專用 backend、最後一次與先前兩次 frontend 自有進程皆已終止、exit 0，memory body 隨 process 釋放。新增附件／暫存為 0，舊殘留及清理拒絕維持原狀，額外落盤配額仍為 0；精確限制見[協作紀錄](TASK_COORDINATION.md)。

本批不增加來源准入、DB／legacy、新聞跨源群組／更正／撤回史、族群可信排名、研究條件、完整 M1／M2、排程或交易能力；完整歷史與 PIT、R0／R1／R2-E1 整體 gate 保留。
