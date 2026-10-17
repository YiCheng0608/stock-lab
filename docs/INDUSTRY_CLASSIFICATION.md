# TWSE／TPEx 產業分類契約

本文規範官方產業代碼對照、mapper 的 fail-closed 規則、collector 對一般產業／ETF／新上市 membership 的期間轉換，以及群組成員與候選的身分契約。Mapper 在 `backend/app/taxonomy.py`，membership 轉換在 `backend/worker/pipeline.py`。DB 內既有的族群關聯尚未全面重新核實，前端對產業族群顯示「既有族群關聯待重新核實」提示（`frontend/src/presentation.ts`），資料修復完成前不得移除。

## 1. 官方代碼來源

TWSE current 表由 B.12.00 基表加官方格式公告的變更組成，並與 OpenAPI 公司基本資料的 code 交叉檢查；TPEx 以 v5.41 完整表為主、V12.14 為交叉驗證。API 出表日只識別公司基本資料 snapshot，不是每檔分類的生效日。

| 來源 | 內容 |
| --- | --- |
| [TWSE IP 行情網路 B.12.00](https://www.twse.com.tw/staticFiles/product/broker/ff80808166388ea1016676ac941001e0.pdf) | 附錄三 01–31 基表。 |
| [TWSE 產業格式公告](https://eshop.twse.com.tw/zh/news/detail/0000000087e9b84901886b8d96940024) | 2023-07-03 起 code 16 更名並新增 35–38。 |
| [TWSE 公司基本資料](https://openapi.twse.com.tw/v1/opendata/t187ap03_L) | 上市公司產業別 code；另含 TDR code 91。 |
| [TPEx IP 行情網路 v5.41](https://dsp.tpex.org.tw/storage/eb_data/11405/1140500476-1.pdf) | current 完整表；2023-07-03 新增 35–38、停用 18／34。 |
| [TPEx 上櫃股票 IP V12.14](https://dsp.tpex.org.tw/storage/eb_data/11309/1130500936-1.pdf) | 分類表與 v5.41 一致。 |
| [TPEx 公司基本資料](https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O) | 上櫃公司產業別 code。 |

## 2. 市場別代碼對照表

`—` 表示 current 一般產業表不支援。internal canonical 是穩定的 group identity；官方市場別名稱以本表為準。`Tourism`、`Financial` 保留既有 key，觀光共用中文顯示為「觀光餐旅」。

| code | TWSE current 官方名稱 | TPEx current 官方名稱 | internal canonical／處理 |
| --- | --- | --- | --- |
| 01 | 水泥工業 | — | `Cement`（TWSE only） |
| 02 | 食品工業 | 食品工業 | `Food` |
| 03 | 塑膠工業 | 塑膠工業 | `Plastic` |
| 04 | 紡織纖維 | 紡織纖維 | `Textile` |
| 05 | 電機機械 | 電機機械 | `Electrical Machinery` |
| 06 | 電器電纜 | 電器電纜 | `Electrical Cable` |
| 07 | — | — | unsupported |
| 08 | 玻璃陶瓷 | 玻璃陶瓷 | `Glass` |
| 09 | 造紙工業 | — | `Paper`（TWSE only） |
| 10 | 鋼鐵工業 | 鋼鐵工業 | `Iron and Steel` |
| 11 | 橡膠工業 | 橡膠工業 | `Rubber` |
| 12 | 汽車工業 | — | `Automobile`（TWSE only） |
| 13 | — | — | unsupported |
| 14 | 建材營造 | 建材營造 | `Construction` |
| 15 | 航運業 | 航運業 | `Shipping` |
| 16 | 觀光餐旅 | 觀光餐旅 | `Tourism` |
| 17 | 金融保險 | 金融業 | `Financial`；市場原文分別追溯 |
| 18 | 貿易百貨 | — | `Wholesale and Retail`（TWSE only）；TPEx 已停用 |
| 19 | 綜合 | — | `Composite`（TWSE only） |
| 20 | 其他 | 其他 | `Other`；只接受精確 code 20 |
| 21 | 化學工業 | 化學工業 | `Chemical` |
| 22 | 生技醫療業 | 生技醫療 | `Biotechnology` |
| 23 | 油電燃氣業 | 油電燃氣業 | `Oil, Gas and Electricity` |
| 24 | 半導體業 | 半導體業 | `Semiconductor` |
| 25 | 電腦及週邊設備業 | 電腦及週邊設備業 | `Computer and Peripherals` |
| 26 | 光電業 | 光電業 | `Optoelectronics` |
| 27 | 通信網路業 | 通信網路業 | `Communications` |
| 28 | 電子零組件業 | 電子零組件業 | `Electronic Parts` |
| 29 | 電子通路業 | 電子通路業 | `Electronic Distribution` |
| 30 | 資訊服務業 | 資訊服務業 | `Information Service` |
| 31 | 其他電子業 | 其他電子業 | `Other Electronics` |
| 32 | — | 文化創意業 | `Cultural Innovation`（TPEx only） |
| 33 | — | 農業科技業 | `Agriculture Technology`（TPEx only） |
| 34 | — | — | TPEx 已停用的電子商務碼；unsupported |
| 35 | 綠能環保 | 綠能環保 | `Green Energy` |
| 36 | 數位雲端 | 數位雲端 | `Digital Cloud` |
| 37 | 運動休閒 | 運動休閒 | `Sports and Leisure` |
| 38 | 居家生活 | 居家生活 | `Household` |
| 80 | — | 管理股票 | 特殊狀態；不建一般產業排行 membership |
| 91 | 一般表未列；TWSE API 僅見於 TDR | — | 特殊證券碼；不建一般產業排行 membership |

兩市場共有的 current code 沒有異義；兩市場 22 都是生技醫療。查表仍必須使用 `(exchange, code)`，因為市場專屬、停用與特殊碼不同。

## 3. Mapper 與 fail-closed 規則

- 官方 numeric input 必須同時有可辨識的 `exchange` 與兩位數 `code`；只對該市場 current ordinary code 回 canonical，其餘為 `None`。不得先跨市場查全域 code。
- blank、`00`、TWSE 91、TPEx 80／18／34、未列碼、缺 exchange 或格式錯誤，都不建立 verified `official_industry`；`Other` 不能作 unknown fallback。
- current 官方 feed 必須保留 exchange＋numeric code 證據；legacy 英文 alias 只供相容讀取，不能升格為官方事實。
- `backend/tests/fixtures/official_industry_codes.json` 只驗 current ordinary code 集合，其中 `official_names` 是測試樣本，不是完整市場別名稱 oracle。
- 只有 ordinary industry 可合併成跨市場 canonical group；membership source 至少保留 exchange。

## 4. 日期語意

| 欄位 | 語意 |
| --- | --- |
| `classification_evidence_at` | 官方碼表擷取／核對日，不是公司分類生效日。 |
| `membership_effective_date` | membership period 的起日，即本系統開始採用該觀測的日期，不是來源生效日。 |
| `market_data_as_of` | 價格、籌碼、features、group scores 與 signals 的市場截點。 |

`instruments.industry` 沒有 revision history，三種日期不得互換；上市日、raw 收錄日與 market as-of 都不能補造分類生效日。

## 6. 一般產業 membership

Collector 只對 stock／IPO 的 ordinary `official_industry`，以可信 capture 觀測日作 forward transition，不回填歷史。ETF 與新上市見第 7 節。

### 6.1 觀測時間與來源綁定

- 每筆 instrument 必須以 `payload_sha256` 唯一匹配同 batch 的 authoritative universe capture，並核對 exchange、source、endpoint allowlist 與 digest。TWSE／TPEx ordinary industry 只能各自來自上市／上櫃公司基本資料 endpoint。
- `captured_at` 取 `FetchedPayload.collected_at`；collector 寫入的 naive 值按 UTC 解讀，其他 naive 時間不可類推。正規化後須確認不在未來，再轉 Asia/Taipei 日曆日 `D=observation_date`。
- `D` 是本系統開始採用該觀測的下限，不是來源生效日或 PIT。`data_as_of`、listing／start／score date 都不能替代。
- 若 `D > score_date`，該 instrument 的 ordinary membership 全部 skip，不關舊、不新增；run receipt 記 warning、counts 與兩個日期，行情 backfill 可繼續。
- run receipt 的 `industry_membership_observations` 保存 `version=industry-observation-v1`、`scope=ordinary_industry_only`、status、skipped／unresolved counts、warnings 與逐筆 source／endpoint／digest、capture／observed／score dates、raw refs、時間關係、raw classification 與 status。
- force 成功時把前一個成功 receipt 附加到 history；force 失敗保留最後成功 receipt，另存最近一次與失敗的 attempts。非 force 重用不改寫既有成功 receipt。
- raw 去重時間不能冒充當次 capture。新 raw 的 aware time 正規化成 UTC-naive 以符合 SQLite 欄位；缺少或無效的 timestamp 不以 DB default 或現在時間補造，run 標為 failed，並保留可得的原檔、digest 與 persistence error。
- 只出現在 TWSE 新上市 endpoint 的 IPO 沒有 ordinary-industry 來源，skip 並記 warning；其他 identity／digest／source 衝突仍 fail-closed。

### 6.2 狀態與期間轉換

- numeric current ordinary code 形成單一 desired canonical group。可信的 non-empty numeric unknown／special／unsupported 形成空集合，只關閉先前的 ordinary membership；blank、non-numeric 或有歧義的證據 fail-closed，不能當成「確認無產業」。
- reconciliation 只操作 collector 擁有的 `official_industry`；manual、ETF、`daily_hot_group` 與 universe 中缺席的標的不動。
- 同日同 canonical 的 open membership 不做任何變更。舊 open row 的 `valid_from < D` 時，改分類先關於 `D-1` 再自 `D` 開新 row；可信空集合只關閉。
- same-day 錯誤、future open、overlap／multiple-open、inactive 或 metadata 衝突在變更前拒絕；不得刪歷史、改日期或任選一列。raw 可先保存，但 membership／group 變更整筆 rollback。

## 7. ETF 與新上市 lifecycle

### 7.1 來源語意與日期

- TWSE ETF raw 類型來自 `FundType`，TPEx 來自 `indexName`，再交 `normalize_etf_category(value, symbol, name)`（`backend/worker/sources.py`）。`broad_market`、`dividend`、`sector`、`thematic`、`commodity`、`bond`、`leveraged`、`inverse` 是本地 heuristic，不是共同官方 taxonomy；未知文字或只有 symbol／name 時 fallback `thematic`，receipt 必須標 method／version。
- candidate record 必須唯一綁定相符市場與 endpoint 的 authoritative capture。ETF 存在與類別只由 ETF endpoint 證明；stock／IPO 存在、上市日與退出只由相符的上市公司／新上市 record 證明。
- capture time、未來拒絕與 `D>score_date` skip 沿用 §6.1。

| 名稱 | 意義 | lifecycle 用途 |
| --- | --- | --- |
| `D`／`observation_date` | capture 的台北觀測日 | transition 不得早於 D。 |
| `L`／`listing_date` | 官方掛牌／核准上市日 | 只界定新上市事件與 60 個曆日窗口。 |
| `start_date` | 行情 backfill 起日 | 不建立 candidate period。 |
| `score_date` | collect／analysis 截點 | 只作截點與 skip 判斷。 |
| `E=L+60 days` | 0..60 inclusive 的最後曆日 | bounded `valid_to`；不是 60 根 bars。 |

### 7.2 ETF 類別

- 有效的本地類別形成 `group_type=etf` 的單一 desired membership；group identity 跨市場共用，membership source 保留 exchange，receipt 保存 endpoint、digest 與 heuristic version。
- 新 period `valid_from=D`；類別改變時於 `D-1` 關舊、自 D 開新。同日同類別重跑不做變更；same-day 錯誤、future、overlap／multiple-open、closed conflict 或 inactive／metadata 衝突 fail-closed。
- 類別缺失或非法、capture 無法唯一綁定時整批 rollback，不關既有 ETF membership。heuristic fallback 不能稱為來源驗證。
- ETF 轉為 stock／IPO 只接受相符的官方 current record；`L>D` 的預告列、缺席、合成指數或其他 domain 的 membership 都不能證明退出。

### 7.3 新上市窗口與到期

- 新上市是 stock／IPO 的事件型 `daily_hot_group`（group `new-listings`）；窗口為 `0 <= D-L <= 60` 個曆日 inclusive，與 20／60 根有效 bars 的可行動門檻分離。
- 只有 `L<=D<=E` 才新建 `[max(D,L), E]`。`L>D` 不預建未來期間；`D>E` 不回填過期歷史。缺 L 為 unresolved 並保留舊 membership；無效 L fail-closed。
- 新 period 一開始即 bounded，同條件重跑不做變更。舊的 open row 在窗口內只補 `valid_to=E`；觀察時已過期，只可 forward-close 於 `D-1`，並標示 D 以前的期間未經本次驗證。既有 bounded row 的 `valid_to` 與本次 E 不符時拒絕，不覆寫。
- 上市公司／新上市 record 依 L 與窗口決定 desired state；只有 ETF record 可證明轉入 ETF。每個 domain 分別計算，不得用單一 group id 廣泛關閉其他 rows。

### 7.4 Domain 隔離、交易與 receipt

- reconciliation 只操作 collector 擁有的 canonical `etf` 與 `new-listings`；ordinary industry、manual、其他熱門族群、缺席標的與合成指數不在範圍內。
- helper 不 commit／rollback caller 的 transaction。SQLite 在 `begin_nested()` 前確保外層 transaction 已開始；成功仍由 caller commit／rollback，helper 失敗只撤 savepoint。collect 後段失敗時 instrument／bar／group／membership 全部 rollback，先前已安全 commit 的 raw 可保留。
- ordinary receipt 的 version／scope／counts 不受影響。`etf` 與 `newlisting` 各有 version、scope、status、counts、observations；ETF 另帶 `classification_method_version=normalize_etf_category-v1`。合成指數可使 candidate scope 為 partial，而行情 run 與 ordinary scope 仍為 success／observed，三者分開解讀。
- force history、失敗 attempt、raw 去重與重用規則沿用 §6.1。

## 8. 群組成員報酬的身分

群組分數依當日有效 membership 計算；本節只規範 `GroupDailyScore.details_json.member_returns` 到個股策略輸入的身分連結，不影響 `hot_group_v1` 分數、最低成員數、`breakout_v1`／`pullback_v1` 公式或策略版本。

- producer 寫入 `member_return_identity_version="instrument-id-v1"`。每個 `member_returns[]` 同時保存正整數且非布林的 `instrument_id`、非空的 `exchange` 與 `symbol`；整份清單的 ID 與 `(exchange, symbol)` 各自不得重複。`instrument_id` 是同一 DB 的本地鍵，仍須以 exchange＋symbol 交叉核對。
- worker 只用 `instrument_id` 找目標列，並要求該列的 exchange／symbol 與目標 Instrument 完全相同；`excess_return_20d` 只接受有限的原生整數或浮點數，布林、字串、null、NaN 與 infinity 都視為不可用。
- marker 未知或空值、列結構或 identity 非法、ID／pair 重複、目標缺席或 identity 衝突時 fail-closed；有 marker 的 payload 不得降級用 symbol 猜測。
- 沒有 marker 的舊 payload，只有在所有列都沒有 `instrument_id`／`exchange` 時才進入 legacy 核對：以該 score 的 `group_id` 與 `signal_date` 重查有效 membership，套用與 producer 相同的股票／ETF 類型與類別 gate；同 symbol 的有效 canonical identity 必須恰好是目標 `instrument_id`，payload 也必須恰有一筆同 symbol 且 20 日超額報酬為有限數值，才採用 `legacy_symbol_unique`。另一市場的同 symbol 成員只要當日仍有效，就必須拒絕。
- Signal 的 `rule_evidence_json.group_member_return_lookup` 保存 `version="group-member-return-lookup/v1"`、來源 marker、group／score date、requested 與 matched identity、`instrument_id`／`legacy_symbol_unique`／`rejected` mode 及 reason。拒絕時 matched 為 null，策略走既有的缺資料語意。
- `group_daily_scores` 以 `(group_id, trading_date)` 原位重算；只有重新產出的 score 帶新版 identity，舊列只受上述 legacy 規則保護。

## 9. 群組候選的身分

外層 score 必須通過 active group、`data_quality="complete"`、至少 3 個 eligible members、非空 rank 與 `benchmark="TAIEX"`；`hot_group_v1` 公式、候選排序與 top 4 上限不受本節影響。

### 9.1 產出與文字投影

- score 使用 `candidate_identity_version="instrument-id-v1"`，把同一批已排序 member metrics 的 top 4 寫入 `candidate_instruments[]`。每列必須有正整數且非布林的 `instrument_id`，以及非空字串 `exchange`、`symbol`；ID 與 `(exchange, symbol)` 各自不得重複，最多 4 列。
- `candidate_symbols` 是相容 API／UI 的字串投影，必須與 `candidate_instruments` 等長、同序且逐列等於 `symbol`。兩市場可有同 symbol，consumer 不得用投影反推身分。

### 9.2 Decision 候選選取

- marker 只接受精確的 `instrument-id-v1`。marker 未知或空值、無 marker 卻混入 typed 欄位、結構錯誤、超過 4 列、ID／pair 重複或逐列投影不一致時，整個 score 的候選來源 fail-closed，不降級用 symbol 猜測；held、watchlist、Signal、event 等其他 action bucket 不受影響。
- 每列先以 `score.trading_date` 驗證 exact `instrument_id` 對應的 exchange＋symbol、該 group 當日有效 membership，以及與 producer 相同的類型／ETF 類別 gate；此步不以 Instrument 目前 active 狀態排除。任一列來源日不合資格或 identity 衝突，即拒絕整個 score 的候選來源。
- 再以 requested as-of 驗證同一 `instrument_id` 仍 active、仍有該 group 有效 membership且通過同 gate。正常退出只逐 ID 排除，不影響同 score 其他合法候選，也不改綁另一個同 symbol Instrument。

### 9.3 Legacy 相容與時間邊界

- Legacy 只限沒有 marker、沒有 `candidate_instruments`，且 `candidate_symbols` 是最多 4 個非空字串的清單；其他形狀拒絕整個 score。重複 symbol 只排除該 symbol。每個 legacy symbol 必須先在 `score.trading_date` 以全部有效 membership 與 producer gate 證明恰好一個 canonical `instrument_id`（不以目前 active 狀態過濾），再要求該 ID 在 requested as-of 仍 active、有效且通過同 gate；來源日的歧義不能因後日只剩一個同 symbol 成員而解除，來源日唯一的身分退出後也不能改綁後加入的同 symbol 身分。
- `Instrument.status`、類型與 ETF 類別沒有完整歷史版本，上述核對只能使用現有 metadata 與 membership period，不構成 PIT 證明。

### 9.5 Backfill／coverage 的候選納入契約

`resolve_backfill_scope` 的 `candidates`／`priority` 來源與重用它的 `/api/coverage?scope=candidates|priority` 建立回補／coverage 的 `(exchange, symbol)` 納入集合，不是 decision 候選選取，不套用 §9.2／9.3 的 qualification、rank、membership、類型或 ETF 類別縮選。

- 只讀 `trading_date` 落在起訖日內的 `GroupDailyScore`；非 object 的 `details_json` 略過。
- 只要 `candidate_identity_version` 或 `candidate_instruments` 任一存在，就進 strict typed 驗證：marker 精確為 `instrument-id-v1`；typed／投影都是最多 4 列的 list；`instrument_id` 為非 bool 且在 `1..2^63-1` 的整數，exchange／symbol 為非空字串；ID 與 pair 各自唯一，`candidate_symbols` 等長、同序且逐列相等。任何錯誤都拒絕該 score 的整份候選，不 fallback 到 symbol。
- 合法 typed 資料先把全部 ID（含目前 inactive）對照同一 DB 的 Instrument，逐列證明 exchange＋symbol；缺 ID 或 pair 衝突拒絕整個 score。核對完成後才逐 ID 套目前 active filter；inactive 不改綁同 symbol 的另一列。
- Legacy 僅限 marker 與 typed 欄位都不存在：`candidate_symbols` 以 `str(...).strip()` 讀取，空字串略過、重複去重，每個 symbol 納入所有目前 active 的同 symbol 列。這只避免回補漏抓，不放寬 §9.3 的 legacy 選取。
- Signal 候選與 `priority` 的 portfolio／watchlist／event 來源各自保留；malformed typed score 只移除該 score 的候選。已保存的 `metadata.target_instruments` 是 run snapshot，resume／force 不重新解析。

### 9.6 Public candidate 的 source-day 身分展示契約

既有 group score 在 public API 與族群詳情 UI 的來源日身分展示；不同於 §9.2 的 requested-as-of 選取，也不同於 §9.5 的回補納入。

- Public payload 保留原有 `candidate_symbols`（theme）或 `candidates`（group）文字陣列，另加固定的 `public_candidate_identity_version="instrument-id-string-v1"` 與 `candidate_instruments[]`。Public `instrument_id` 是 `1..2^63-1` 的十進位字串，避免超過 JavaScript safe integer 後失真。
- Server 先嚴格驗證 internal envelope（同 §9.1 與 §9.5 的 typed 規則）；任一列或 envelope 不合法，整份 public `candidate_instruments` 為空，不洩漏部分結果，也不以 symbol 反推。文字陣列只保留原生非空字串並維持順序與重複值，不做 `str(...)` 轉型；legacy 或 malformed 只留文字，不產生連結。
- 合法 envelope 的所有 ID 必須在同一 DB 找到 exact exchange＋symbol，並證明該 group membership 在 `score.trading_date` 有效且通過 producer 的類型／ETF 類別 gate；任一不符即整份 typed identity 為空。這是來源日 snapshot，不套目前 active 或 requested as-of；來源日後退出或目前 inactive 的 identity 仍保留並可連到個股頁，不代表目前可決策。
- Theme 投影（dashboard themes、themes list／detail／members）保留既有 qualified gate：不 qualified 時文字與 typed 候選都為空。Group 相容投影（dashboard groups、groups list／detail）不加 qualification gate。Full、compact 與 route 投影共用同一驗證，compact 仍只顯示 top 4。
- 族群詳情只在 public marker、整份 typed 結構、ID／pair 唯一與 symbol 對齊都合法時建立 `/stocks/{exchange}/{symbol}` 連結，文字顯示 exchange＋symbol，React key 使用 identity 加序位。候選的「評分日期」讀 score `trading_date`；成員表的「成員資料截至」讀 members response `meta.data_as_of`，兩者不互相推導。
