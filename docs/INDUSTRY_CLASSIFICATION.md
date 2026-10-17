# TWSE／TPEx 產業分類契約

本文規範官方產業代碼對照、mapper 的 fail-closed 規則、collector 對一般產業／ETF／新上市 membership 的期間轉換，以及群組成員與候選的身分契約。Mapper 在 `backend/app/taxonomy.py`，membership 轉換在 `backend/worker/pipeline.py`。前端對產業族群顯示「既有族群關聯待重新核實」提示（`frontend/src/presentation.ts` 的 `TEMPORARY_INDUSTRY_GROUP_NOTICE`）。

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

## 3. Mapper 與 fail-closed 規則

- 官方 numeric input 必須同時有可辨識的 `exchange` 與兩位數 `code`；只對該市場 current ordinary code 回 canonical，其餘為 `None`。查表一律用 `(exchange, code)`，不得先跨市場查全域 code，因為市場專屬、停用與特殊碼不同。
- blank、`00`、TWSE 91、TPEx 80／18／34、未列碼、缺 exchange 或格式錯誤，都不建立 verified `official_industry`；`Other` 不能代表 unknown。
- current 官方 feed 必須保留 exchange＋numeric code 證據；英文 canonical label 只用於讀取既有列（`canonical_industry_label`），不能升格為官方事實。
- 只有 ordinary industry 可合併成跨市場 canonical group；membership source 至少保留 exchange。

## 4. 日期語意

| 欄位 | 語意 |
| --- | --- |
| `classification_evidence_at` | 官方碼表擷取／核對日，不是公司分類生效日。 |
| `membership_effective_date` | membership period 的起日，即本系統開始採用該觀測的日期，不是來源生效日。 |
| `market_data_as_of` | 價格、籌碼、features、group scores 與 signals 的市場截點。 |

`instruments.industry` 沒有 revision history，三種日期不得互換；上市日、raw 收錄日與 market as-of 都不能補造分類生效日。

## 5. Membership 期間轉換

Collector 對三個 domain 各自計算 desired state，只操作自己擁有的 membership：stock／IPO 的 ordinary `official_industry`、`group_type=etf`、`daily_hot_group` 的 `new-listings`；manual、其他熱門族群與 universe 中缺席的標的不動。

- **觀測日 D**：每筆 instrument 須唯一綁定同 batch、相符市場與 endpoint 的 capture；`captured_at` 取 `FetchedPayload.collected_at`（collector 寫入的 naive 值按 UTC 解讀），確認不在未來後轉 Asia/Taipei 日曆日為 D。D 是本系統開始採用該觀測的下限，不是來源生效日；`D > score_date` 時該 instrument 全部 skip 並記 warning。
- **一般產業**：current ordinary code 形成單一 desired group；可信的 non-empty numeric unknown／special／unsupported 形成空集合，只關閉舊 membership；blank、non-numeric 或有歧義的證據 fail-closed。只出現在新上市 endpoint 的 IPO 沒有產業來源，skip 並記 warning。
- **ETF**：`normalize_etf_category`（`backend/worker/sources.py`）把 TWSE `FundType`／TPEx `indexName` 對到本地 heuristic 類別，無法辨識的文字歸 `thematic`，不是官方 taxonomy；類別缺失或非法時整批 rollback，不關既有 ETF membership。ETF 轉為 stock／IPO 只接受相符的官方 current record。
- **期間**：同日同 group 不變更；改分類時舊 open row 關於 `D-1`、自 D 開新 row；可信空集合只關閉；不回填歷史。same-day 錯誤、future open、overlap／multiple-open、inactive 或 metadata 衝突在變更前拒絕，不刪歷史、不改日期、不任選一列；raw 可保留，membership／group 變更整筆 rollback。
- **新上市**：窗口為 `0 <= D-L <= 60` 個曆日（`L` 為官方掛牌日，`E=L+60`），與 20／60 根 bars 的可行動門檻分離。只有 `L<=D<=E` 才新建 bounded `[max(D,L), E]`；`L>D` 不預建，`D>E` 不回填；舊 open row 在窗口內補 `valid_to=E`，已過期只 forward-close 於 `D-1`；既有 bounded row 的 `valid_to` 與 E 不符時拒絕。缺 L 為 unresolved 並保留舊 membership。

## 6. 群組成員與候選身分

`GroupDailyScore.details_json` 以 `member_return_identity_version` 與 `candidate_identity_version`（皆為 `instrument-id-v1`）標記 typed 身分；`hot_group_v1` 公式、候選排序與 top 4 上限不受本節影響。`Instrument.status`、類型與 ETF 類別沒有歷史版本，下列核對不構成 PIT 證明。

- **結構**：`member_returns[]` 與 `candidate_instruments[]`（score 已排序成員的 top 4）每列有正整數且非布林的 `instrument_id`（同一 DB 的本地鍵）與非空 `exchange`、`symbol`，ID 與 pair 各自唯一；`candidate_symbols` 是等長同序的文字投影，不能反推身分。marker 未知、結構錯誤、重複或投影不一致時，該 score 的成員報酬或候選來源整份 fail-closed，不以 symbol 猜測。
- **策略輸入**（`worker.pipeline._resolve_group_member_return`）：以 `instrument_id` 找列並核對 exchange＋symbol；`excess_return_20d` 只接受有限數值；結果寫入 Signal 的 `rule_evidence_json.group_member_return_lookup`，拒絕時走缺資料語意。
- **Decision 候選**（`decision._group_candidate_ids`）：先以 `score.trading_date` 驗證 ID 對應、當日有效 membership 與 producer 的類型／ETF 類別 gate，任一列不合即拒絕整個 score；再以 requested as-of 逐 ID 排除已退出或 inactive 者，不改綁同 symbol 的另一列。
- **回補與 coverage**（`worker.backfill._candidate_instrument_keys`）：合法 typed 候選逐列對照 Instrument 後，納入目前 active 的 ID；不套 decision 的 membership 縮選，malformed score 只移除該 score。
- **Public API**（`api._public_candidate_identity`）：另回 `public_candidate_identity_version="instrument-id-string-v1"` 與十進位字串 `instrument_id`；以來源日 `score.trading_date` 驗證 membership 與 gate，任一不合即整份 `candidate_instruments` 為空。族群詳情只在 typed 身分合法時連到 `/stocks/{exchange}/{symbol}`；候選「評分日期」讀 score `trading_date`，成員表讀 members response `meta.data_as_of`。
- **沒有 marker 的 score**：只有 symbol 文字時，策略輸入與 decision 候選要求來源日恰好一個有效同 symbol 成員（`legacy_symbol_unique`），另一市場同 symbol 成員有效即拒絕；回補納入所有 active 的同 symbol 標的；public API 只顯示文字、不產生連結。
