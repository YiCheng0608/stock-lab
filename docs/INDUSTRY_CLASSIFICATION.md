# TWSE／TPEx 產業分類與隔離修復契約

更新：2026-09-13。狀態：`R15 mapping／隔離診斷、R16 ordinary-industry normal collector 與 R17 ETF／new-listing candidate lifecycle 已通過有限 review；正式資料未修復`。本文件是官方代碼、fail-closed、有效期間、R15 隔離驗收、R16 ordinary-industry 與 R17 candidate lifecycle 的單一入口；不表示正式或 `.local` DB、歷史分類、族群分數或研究輸出已修復。

## 1. 官方證據 snapshot

`classification_evidence_at=2026-09-13`（Asia/Taipei）。官方 API raw 於 `2026-09-13T01:10:01+08:00` 擷取至專案外 `C:/Users/YiCheng/AppData/Local/Temp/stock-r15-industry-evidence/`；下列 SHA-256 固定本輪實際讀到的 bytes，網址日後更新不應覆寫此證據語意。

| 來源 | 文件／資料日期與定位 | 本輪保存證據 |
| --- | --- | --- |
| [TWSE IP 行情網路 B.12.00](https://www.twse.com.tw/staticFiles/product/broker/ff80808166388ea1016676ac941001e0.pdf) | 107/10 修改、109/03 實施；PDF p.101（頁尾第 92 頁）附錄三是 01–31 基表。文件只給到月份，不補造日。 | `twse-ip-B12.pdf`，SHA-256 `3739F28ACBA7BDCE2C1D21016A2C8C3C8C63B2CA14D013446F9448D733F4A5DC`。 |
| [TWSE 產業格式修改公告](https://eshop.twse.com.tw/zh/news/detail/0000000087e9b84901886b8d96940024) | 公告 2023-05-30；2023-07-03 起代碼 16 更名，新增 35–38。 | `twse-new-categories-20230530.html`，SHA-256 `4E759E244227C29AA449482F94BC15506C9DF3905D4D4F7BE4C7EDA71C29B055`。 |
| [TWSE 上市公司基本資料 OpenAPI](https://openapi.twse.com.tw/v1/opendata/t187ap03_L) | raw `出表日期=1150911`（2026-09-11），1,094 rows；普通分類代碼與下表一致，另有 10 筆 TDR 使用 91。 | `twse-t187ap03_L.json`，1,326,276 bytes，SHA-256 `31123B2251D0D3666F9D508B2D8404CE0AA1D68072AE93126C55C0733F6F6FB2`。 |
| [TPEx 櫃檯買賣 IP 行情網路 v5.41](https://dsp.tpex.org.tw/storage/eb_data/11405/1140500476-1.pdf) | 文件 2025-05-13、預定 2025-06-30 上線；PDF p.27（頁尾第 26 頁）是完整 current 表。PDF p.11（頁尾第 10 頁）明載 2023-07-03 更名／新增 35–38 並刪除 18、34；v5.41 本身只新增證券別 `BS`，沒有產業碼異動。 | `tpex-2025-notice.pdf`，899,071 bytes，SHA-256 `784D29BD39A9E5C945CB01F745E83EABAF9198E6B2D7D582D2EC6483874C610A`。 |
| [TPEx 上櫃股票 IP 行情網路 V12.14](https://dsp.tpex.org.tw/storage/eb_data/11309/1130500936-1.pdf) | 文件 2024-09-23、V12.14 自 2024-11-18 實施；PDF p.96（頁尾第 85 頁）完整表與 v5.41 一致，作跨規格交叉驗證。 | `tpex-v12.14-20240923.pdf`，806,033 bytes，SHA-256 `55D44B6E0B06497448EE70B7490D8AFA02BECAE6C7F267B96C6422CAF085D5E0`。 |
| [TPEx 上櫃公司基本資料 OpenAPI](https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O) | raw `Date=1150912`（2026-09-12），891 rows；出現的普通分類碼皆在下表，沒有 18、34、80。 | `tpex-mopsfin_t187ap03_O.json`，1,072,030 bytes，SHA-256 `AC2293AAAE531FF61C422236D188D78BCE57EAA48D626924BB4D9AD32AA73F25`。 |

TWSE 的完整 current 表是 B.12.00 基表套用 2023-07-03 官方變更後的結果，並以本輪 OpenAPI 實際代碼交叉檢查；不能把 B.12.00 單獨說成 2026 年最新版。TPEx 以 2025 v5.41 完整表為主、V12.14 為交叉驗證。API 出表日只表示這次公司基本資料 snapshot，不等於每檔分類的歷史生效日。

## 2. 完整市場別代碼期待表

`—` 表示 current 一般產業表不支援；internal canonical 只供穩定 group identity。市場別官方原文保留在本表與證據 snapshot；既有產品仍可使用共用中文簡稱，本輪不新增 market-specific UI。`Tourism` 與 `Financial` 維持既有穩定 key，觀光的共用中文簡稱應反映 current「觀光餐旅」。

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
| 17 | 金融保險 | 金融業 | `Financial`；市場別原文留在證據表 |
| 18 | 貿易百貨 | — | `Wholesale and Retail`（TWSE only）；TPEx 自 2023-07-03 停用 |
| 19 | 綜合 | — | `Composite`（TWSE only） |
| 20 | 其他 | 其他 | `Other`；只接受精確 code 20，不是 fallback |
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
| 34 | — | — | TPEx 電子商務歷史碼，2023-07-03 停用；current unsupported |
| 35 | 綠能環保 | 綠能環保 | `Green Energy` |
| 36 | 數位雲端 | 數位雲端 | `Digital Cloud` |
| 37 | 運動休閒 | 運動休閒 | `Sports and Leisure` |
| 38 | 居家生活 | 居家生活 | `Household` |
| 80 | — | 管理股票 | 特殊狀態，不建立一般 `official_industry` 排行族群 |
| 91 | 一般產業表未列；本輪 API 僅見 TDR | — | 特殊證券碼，不建立一般 `official_industry` 排行族群 |

現行官方表的 shared codes 沒有異義 collision；兩市場 code 22 都是生技醫療，並非 TWSE 油電／TPEx 生技。仍須以 `(exchange, code)` 查表，因市場專屬、停用及特殊碼不同。現行程式的實際 collision 是 TWSE 18 與 20–31 被錯移一格、缺 19，並把 31 錯接文化創意；TWSE 32 應是 unsupported，不是缺少的 current 分類。TPEx 18 應改為 unsupported，80 則須保留特殊狀態而非一般產業排行。

## 3. Mapper 與 fail-closed 契約

- 官方 numeric input 必須同時具有可辨識的 `exchange` 與兩位數 `code`；只有該市場 current ordinary code 回傳 canonical string，其餘維持 `None`。本輪不新增四態 mapper schema，也不可先跨市場查全域 code。
- 空白、`00`、TWSE `91`、TPEx `80`、TPEx `18`／`34`、任何未列碼、缺 exchange 或格式錯誤，都不得建立 verified `official_industry` membership。`20=Other` 只由精確 code 20 產生，不可承接 unknown。
- current 官方 feed 不得以 canonical 英文 alias 取代 `(exchange, numeric code)` 證據。舊 fixture／legacy row 可相容讀取英文，但不能因此升格為官方 truth。
- `backend/tests/fixtures/official_industry_codes.json` 只驗證兩市場 current ordinary code 集合；其中扁平、選取式的 `official_names` 只是測試樣本，不是完整或市場別名稱 oracle，也不能取代本文件的官方原文表。
- 本輪 manifest 記錄全域官方 source URL、API 出表日、擷取時間、mapping version，以及被處理資料的 raw exchange／code。legacy row 原本沒有的逐列來源時間維持 unknown，不補造證據；隔離修復時也不以「沿用上次」冒充 current verified。
- 只有 ordinary industry 可合併成跨市場 canonical group；membership source 至少保留 exchange，17 的市場別官方原文則由本輪 evidence snapshot 追溯。

## 4. 三種日期與修復邊界

| 欄位 | 本輪值 | 語意 |
| --- | --- | --- |
| `classification_evidence_at` | 2026-09-13 | 本輪擷取／核對 current 官方 code table 的日期；不是每家公司分類生效日。 |
| `membership_effective_date` | 2026-09-13 | 本輪 current-table diagnostic 隔離副本的 period 切換日；不是 fresh 公司分類 truth。 |
| `market_data_as_of` | 2026-09-08 | 既有價格、籌碼、features、group scores 與 signals 的市場資料截點。 |

三者不可互換。`instruments.industry` 只有 current 值，沒有分類 revision／歷史 snapshot；raw 最新收錄日、上市日或 `market_data_as_of` 都不能補成分類生效日。因此：

- current 修復副本只把 legacy raw code 依 current table 做 forward-only diagnostic transition：錯誤 open membership 於 2026-09-12 結束，expected ordinary membership 自 2026-09-13 開始；既有歷史 rows 不刪除、不改名、不回填上市日。unknown／unsupported／special 自該日沒有 verified ordinary membership。此結果不是 fresh 2026-09-13 公司分類核實。
- current 修復副本保留 2026-09-08 舊 group scores、原 signals、evaluations 與 settlements，不回算、不覆寫；它們仍是舊 membership 下的歷史產物。
- 另由同一份唯讀 backup 建立 `baseline` 與 `corrected` 兩個 2026-09-08 counterfactual diagnostic 副本。兩者使用相同價格、籌碼與 features；corrected 僅把本輪 current mapping 當情境輸入，以既有函式重算 group scores，signals 使用獨立 namespace。這只量測分類修正影響，不是 2026-09-08 PIT 或歷史真值。

## 5. 隔離驗收矩陣（有限範圍已 review）

| Gate | 必須留下的實際證據 | 通過條件 |
| --- | --- | --- |
| mapping | 完整表逐碼正／負測試、source hashes、mapping hash；含 shared 同義、market-only、TPEx 18／34 停用、80／91 特殊、blank／00／任意 unknown、numeric-without-exchange。 | 所有 ordinary code 精確命中；其餘均 fail closed；3176／TPEx 22 為 Biotechnology，TWSE 22 亦為 Biotechnology。 |
| baseline | 從正式 DB consistent read-only backup 產生的 before counts 與 mismatch 明細。 | 可重現 R14 的 TPEx 706／890；統籌另已重現 TWSE 845／1,094 wrong-or-unsupported。兩者只是修復前基線。 |
| current membership | 專案外 current-table diagnostic 修復副本、period transition audit、before／after row counts。 | 每檔 supported active stock／ipo 在 2026-09-13 恰有一個 expected ordinary membership；unknown／unsupported／special 為 0；無重疊或反向期間，舊 rows 可追溯；不宣稱 fresh company truth。 |
| current derived preservation | 2026-09-08 scores、signals、evaluations、settlements 的 row／content fingerprints。 | current 修復前後完全不變；不得以 membership 修好宣稱舊 scores 或候選已修。 |
| counterfactual pair | baseline／corrected DB 路徑與 hashes、相同 market bars／chips／features fingerprints、重算命令與 exit code。 | 兩份只有 scenario membership、重算 scores 與獨立 namespace signals 可有預期差異；列出 members、eligible count、score、rank、quality、候選／signal 差異及因果對照。 |
| isolation | `PRAGMA integrity_check`、`foreign_key_check`、正式與 `.local` DB 前後 SHA／size／mtime。 | 所有副本 integrity `ok`、FK 0；正式 `data/stock.db` 維持 `74A34389DBFA65429D27EA41BC9DECA2A132808F10093E2FFDE98665D96232D6`，`.local/data/stock.db` 維持 `87453D7B29954B6D506F8020B8987F321AA6749CE9BC24FBEF695DD3874B8D02`。 |
| rerun／trace | 同一副本第二次執行的 mutation count、表 fingerprints；manifest 記錄 input/output hash、三種日期、source/mapping version、命令、exit code、限制。 | 第二次執行不新增 period／score／signal 漂移；所有產物能回指本輪 snapshot。 |

2026-09-13 統籌已獨立重現上述有限範圍：current 與 counterfactual 各有 1,974 個 supported active stock／ipo 恰有一個 expected membership，35 個 unknown／special 均為 0；關閉 1,551 個舊錯 membership（TWSE 845、TPEx 706）、新增 1,541 個 expected membership（TWSE 835、TPEx 706），原 2,403 筆 membership 全保留且只按契約切 `valid_to`。current 副本的非 group／membership 表與 prepared copy 相同；baseline／corrected 的價格、籌碼、features、raw、news、evaluations 等輸入／歷史表相同，原 signals 未改。

counterfactual 的 group score rows 由 41 變 52，45 列有差異，兩側各 6 個 non-null score；兩側各產生 4,616 筆隔離 namespace signals，差異為 rationale 3,048、rule evidence 18、data quality／status 各 8，其中 9103、9105、912000、9136 的兩策略由 `observation` 轉為 `data_incomplete`。統籌另逐群核對 eligible 與 member 的 1／5／20 日平均、null score 不產 candidate、integrity `ok` 與 FK 0；完整 backend 為 372 passed／4,625 warnings／22.41 秒、exit 0。獨立證據為 `C:/Users/YiCheng/AppData/Local/Temp/stock-r15-coordinator-review/independent-final-db-review.json`；作者交付為 `C:/Users/YiCheng/AppData/Local/Temp/stock-taxonomy-diagnostic-dbv_xvgb/report.json`。

正式 DB 未修復前，Round14「既有族群關聯待重新核實」guard 必須持續保留；本輪驗收不授權撤除，mapping 單元測試、文件、fixture、隔離副本或 counterfactual 成功也不能單獨撤除。正式 DB 寫入、歷史回填、策略有效性與 PIT 仍不在本批。

## 6. Round16 normal collector 觀測期間（有限接線已 review）

C016 已把 normal collector 的 `stock`／`ipo` ordinary `official_industry` 關聯改為按可信 capture 觀測日向前轉換，並經統籌有限 review。ETF 分類與 `new-listings` 保留既有日期行為，本輪只驗不被 industry reconciliation 誤關；這兩個 domain 的歷史時間風險未完成。

### 6.1 觀測時間與來源綁定

- 每筆 instrument 必須以 `payload_sha256` 唯一匹配本次 batch 的 authoritative universe capture，並同時核對 exchange、source、endpoint allowlist 與 digest。TWSE ordinary industry 只能來自 TWSE listed-company endpoint，TPEx 只能來自 TPEx listed-company endpoint；digest 或 raw id 單獨都不是充分證據。
- `captured_at` 取該次 `FetchedPayload.collected_at`。現行 `capture_payload` 產生的 naive 值只因其程式契約可明確按 UTC 解讀；不得把其他任意 naive 時間猜成 UTC。正規化後還須在 fetch 完成時核對不是未來時間，再轉成 Asia/Taipei 日曆日 `observation_date=D`。
- `D` 只表示「系統最早自此觀測日向前採用這份 current 分類」，不是公司實際分類生效日、來源宣示的 effective date 或歷史 PIT。`FetchedPayload.data_as_of` 在現行 universe fetch 是呼叫端傳入值；它與 `listing_date`、行情 `start_date`、`score_date` 都不得替代 `D` 或補造歷史分類。
- 若 `D > score_date`，該 instrument 的 ordinary-industry membership 全部跳過，不關舊列、不新增列；行情 backfill 可繼續。run metadata 必須列 warning、skipped count、`D` 與 `score_date`，不得把 current snapshot 注入較早的 score date。
- 成功或 partial 的 receipt 存在 `IngestionRun.metadata_json.industry_membership_observations`，物件包含 `version=industry-observation-v1`、`scope=ordinary_industry_only`、`status=observed|partial`、`skipped_count`、`unresolved_count`、`warnings` 與逐筆 `observations`。逐筆欄位包含 `exchange`、`symbol`、`source`、`endpoint`、`sha256`、`captured_at_utc`、`observed_date`、`score_date`、`raw_payload_id`、`stored_raw_collected_at_utc`、`time_semantics`、`raw_time_relationship`、`raw_classification`、`classification_status` 與 `status`。
- 強制重跑成功時，前一份成功 receipt 追加至 `industry_observation_history`；重跑失敗時保留前一份 `industry_membership_observations`，把本次證據寫入最新 `industry_observation_attempt` 並追加 `industry_failed_attempts`。非 force idempotent reuse 會透傳已保存的成功 receipt，不以本次呼叫時間改寫它。
- 相同 request／hash 的 `RawPayload` 可去重並保留最早收錄時間，因此 raw id 或 `stored_raw_collected_at_utc` 不能冒充本次 capture 時間。新 raw 寫入前會把 aware timestamp 正規化為 UTC，再以 UTC-naive 形式配合現有 SQLite 欄位保存；既有 naive rows 不回寫，只能依本地 capture 的既有 UTC 契約解讀，不能升格成外部時間真值。timestamp 缺失／非法時 `_upsert_raw_payload` 拒絕寫入，不能靠 DB default 或現在時間補造。此時 run 仍須可靠成為 `failed`，並以原始 payload file path、digest、null／invalid value 與 `raw_persistence_errors` 保存 failed-attempt 證據；不保證會有 raw DB row。
- 只出現在 TWSE new-listing endpoint、尚未出現在 listed-company endpoint 的 IPO 沒有 ordinary-industry 權威 evidence：其 industry normalization 應 skip 並在 receipt 留 warning／reason，不能升格成 verified ordinary membership；這不阻斷該 IPO 其他已具證據的 instrument／行情處理。其餘 exchange、source、endpoint、digest 缺錯或不唯一仍是 evidence conflict，不得降格成一般 skip。

### 6.2 Ordinary-industry 狀態與期間轉換

- normal collector 只接受帶正確 exchange 的 numeric industry code。current ordinary code 形成單一 expected canonical group；明確 non-empty numeric unknown／special／unsupported 只有在可信 listed-company capture 下才形成空集合，會關閉先前 open ordinary membership 而不猜新群組，receipt 必須保存 raw code 與 reason。可信 listed row 的缺欄／空白、非 numeric 或其他 ambiguous classification evidence 使 normalization fail closed；前節的 new-listing-only IPO 則按限定例外 skip＋warning。兩者都不能把資料缺漏當成「已確認無產業」。
- industry reconciliation 只操作 collector-owned `official_industry` domain；manual membership 及本次 universe 未列出的 instrument 不動，不得以 hot-group overlap 掩蓋 industry 衝突。normal collector 仍可依既有流程更新 ETF／`daily_hot_group` 與行情等其他 domain，本輪只證明 ordinary-industry 處理不會誤關它們，不能宣稱成功 collect 的所有表均不變。
- exact 同日、同 canonical open 關聯為 idempotent，重跑零 mutation。若既有 open ordinary 關聯的 `valid_from < D`，ordinary change 先把舊列關在 `D - 1 day`，再從 `D` 新增 expected 關聯；可信空集合只執行前半段。這是 observation transition，不是歷史 effective-date 回填。
- mutation 前須整批驗證期間與 canonical identity。same-day wrong 關聯、任何 future open period、既有 overlap／多 open、inactive 或 metadata 不符的 canonical group，都因日粒度無法無損修正而拒絕 normalization；不得刪除、改寫日期或任選一列。raw capture 已先保存時應保留，membership／group mutation 則整筆交易 rollback 並留下失敗原因。

### 6.3 最小驗收矩陣

| Gate | C016／統籌實際證據 | 通過條件 |
| --- | --- | --- |
| evidence／time | authoritative endpoint、source、exchange、digest 唯一匹配；UTC→Asia/Taipei 日界與 future-time negative cases。 | `D` 只由本次可信 capture 產生；`data_as_of`、listing／start／score date 均不能代替。 |
| score boundary | `D < score_date`、`D = score_date`、`D > score_date` 隔離案例及 run receipt。 | 前兩者只做 forward transition；後者只跳過 ordinary industry 並明記 counts／dates，歷史 score 不受 current snapshot 污染。 |
| state transition | ordinary unchanged／change、numeric unknown／special／unsupported、缺失／ambiguous、重跑案例。 | change gapless、可信空集合關舊不新增、缺失／ambiguous fail closed、exact rerun 零 mutation。 |
| conflict／atomicity | same-day wrong、future period、overlap／多 open、inactive canonical 與 evidence conflict。 | 所有衝突在 membership mutation 前拒絕；raw 可追溯，group／membership 無部分寫入。 |
| domain isolation | 同一 instrument 同時具有 industry、ETF／new-listing 或 manual 關聯，以及 universe 缺席案例。 | industry reconciliation 不改其他 domain 與缺席 instrument；collector 對其他 domain 的正常更新不在不變承諾。 |
| receipt／retry | success、partial、idempotent reuse、force success／failure、missing／invalid timestamp 與 raw persistence error。 | 當次 capture 與去重 raw 最早時間分開；history／failed attempts 不覆蓋最後成功 receipt；非法時間不補造 raw DB timestamp，run 不停在 running。 |
| scope／history | 專案外 Temp DB、正式與 `.local` DB 前後 hash／size／mtime、既有 derived rows fingerprints。 | 正式庫不變；成功／skip 重跑只承諾 group、membership 與既有 score 不漂移，正常 bar `collected_at` 可更新；failed rollback 另驗 instrument／bar 全欄不變。不得把 R15 counterfactual 或 R16 observation transition 稱為歷史 PIT。 |

統籌最後以 Python 3.12.14 與既有專案外 Alembic 1.19.2 執行完整 backend：412 passed、4,902 warnings、pytest 31.67 秒（process 33.031 秒）、exit 0；作者最後完整 backend 亦為 412 passed／4,902 warnings／32.97 秒，兩者分開記錄。統籌另以實際 TWSE／TPEx universe parser 處理本地 official-shaped fixture，再走完整 `collect`，11 項檢查於 D 版再次 exit 0：涵蓋上市日不回填、跨市場共用 canonical、ordinary change、TPEx 80 關舊、exact rerun、same-day／missing evidence atomic rollback、manual／2026-09-08 score 保留、`D > score_date` skip、integrity `ok` 與 FK 0；aware timestamp probe 也由修正前失敗改為 final 通過。初版 harness 曾把正常 forced collect 會更新的 `MarketBar.collected_at` 也納入全等比較而失敗；final 已依上述正確範圍重跑，不冒稱成功 collect 所有表不變。

完整證據在 `C:/Users/YiCheng/AppData/Local/Temp/stock-r16-coordinator-review/full-backend-review.json`、`full-backend.log`、`independent-collector-review.json`、`aware-timestamp-probe.json` 與 `source-review-changed.json`；C 版 410 項結果另存歷史檔，不是 final。本批沒有 live 官方網路驗證；fixture 的 capture metadata 是 caller-provided 可信假設，不證外部來源真值、availability 或歷史 PIT。正式與 `.local` DB 及保護來源前後一致。ETF／`new-listings` 期間不在 R16 範圍，後續僅由第 7 節有限接線補上 current candidate lifecycle；正式 DB 修復、來源時間 truth、既有 legacy raw 時間修復、metadata history 無界增長、舊 derived outputs 重算、前端 guard 解除與策略有效性仍未完成。

## 7. Round17 ETF／new-listing candidate lifecycle（有限接線已 review）

C017-C 已完成 normal collector 既有 ETF 與 `new-listings` candidate membership 的來源、日期、到期、domain 切換與 SQLite transaction 修正，並經統籌有限 review。本節不改第 6 節 ordinary-industry 的 scope、counts 或觀測期間，也不授權正式／`.local` DB 修復、歷史回填或解除前端 guard。

### 7.1 來源語意與五種日期

- TWSE ETF record 的 raw 類型來自官方 ETF feed 的 free-text `FundType`；TPEx ETF record 取 ETF allowlist 的 `indexName`，再連同 symbol、name 交給現行 `normalize_etf_category(value, symbol, name)`。`broad_market`、`dividend`、`sector`、`thematic`、`commodity`、`bond`、`leveraged`、`inverse` 是本地有限集合與 token heuristic 的輸出，不是來源直接發布的共同 taxonomy、分類 effective date 或 PIT truth。未知文字及只有 symbol／name 的資料可能 fallback 為 `thematic`；文件須區分 raw description 與 local normalized category，receipt 至少回指 raw capture 並明列 normalization method／version，不能稱「官方 ETF 分類」。本批不改 mapper 的分類品質。
- 每筆 candidate record 仍須以 `payload_sha256` 唯一匹配本次 batch 的 authoritative capture，並核對 exchange、source、endpoint allowlist 與 digest。ETF presence／category 只能由對應市場 ETF endpoint 支持；stock／IPO presence、上市日及退出判定只能由相符的 listed-company／new-listing authoritative record 支持。raw id、同碼其他 endpoint 或另一個 domain 的 membership 都不是充分證據。
- capture `collected_at` 依第 6.1 節先正規化 UTC、拒絕未來 capture，再轉 Asia/Taipei 日曆日 `D`。這仍是「本系統自 D 起看見 current record」的 observation floor；不是來源 effective date。若 `D > score_date`，ETF 與 new-listing lifecycle 都只記 partial／skip，不關舊、不新增，也不把 current capture 插入較早的分析截點。

| 名稱 | 意義 | candidate membership 可否使用 |
| --- | --- | --- |
| `D`／`observation_date` | 本次唯一可信 capture 的台北觀測日 | 是；新 transition 不得早於 D |
| `L`／`listing_date` | authoritative record 報告的掛牌日／核准上市日 | 只界定 new-listing 事件與 60 個曆日窗口；不是 ETF category effective date |
| `start_date` | 本次行情 backfill 的查詢起日 | 否；不得拿來建立 ETF／new-listing period |
| `score_date` | 本次 collection／analysis 截點，也是 `D > score_date` 的防未來界線 | 只作截點與 skip 判斷；不是 category 或 listing effective date |
| `E=L+60 days` | new-listing 0..60 inclusive 的最後一個曆日 | 只作 bounded `valid_to`；不得與 60 根有效 bars 混用 |

### 7.2 ETF category lifecycle

- authoritative ETF record 經現行 local normalizer 產生有限 category 後，才形成該 instrument 在 `group_type=etf` 的單一 desired canonical membership。group identity 跨市場共用；membership source 保留 exchange，receipt 另保留 endpoint、digest 與 normalization method。target group 與任何將被關閉的 collector-owned existing group 若 inactive，或 name、type、definition／source metadata 與 canonical identity 衝突，整批拒絕，不就地改寫成另一個概念。
- 新建 ETF category membership 的 `valid_from=D`；category change 則把同 domain 的舊 open period 關在 `D - 1 day`，並自 D 開新 period。不得使用 ETF 的 `listing_date`、行情 `start_date` 或 `score_date` 回填 category history。exact 同 D、同 canonical open membership 是零 mutation；same-day wrong、future、overlap／多 open 或 closed-period 衝突須在 mutation 前 fail closed。
- 若 normalized category 缺失、不在有限集合或 record 無法唯一綁定 authoritative ETF capture，整批 fail 並 rollback；不得把資料缺漏解讀成已確認退出，也不得關閉既有 open ETF membership。現行 mapper 對未知文字的 `thematic` fallback 只能標示為 heuristic，不能冒稱 unknown 已由來源驗證。
- ETF↔stock／IPO 的退出只能由本次 authoritative current record 證成：ETF record 可建立／轉換 ETF domain，authoritative listed stock／IPO record 才可把既有 open ETF period於 D 前一日 forward-close。`L > D` 的 prospective new-listing row 尚不能證明 current stock／IPO state，也不得拿來關 ETF；若該 instrument 已有 collector-owned ETF／new-listing history，須保守拒絕而非改動。不得因 instrument 缺席、synthetic index、manual／industry／daily-hot membership 或另一個 category 的存在自行猜測退出。

### 7.3 New-listing window 與到期

- new-listing 是股票／IPO 的事件型 `daily_hot_group`，不得只看 mutable `Instrument.instrument_type=ipo` 決定歷史。authoritative `L` 的窗口是 `0 <= D-L <= 60` 個曆日且兩端 inclusive；它與 `instrument_eligibility` 的 20／60 根有效 bars 分屬 membership lifecycle 與 actionable guard，不能互相替代。官方 refresh 在第 61 個曆日把 current type 轉為 stock，也不代表已有 60 根有效 bars。
- 對本輪新建立的 period，只有 `L <= D <= E` 時可寫入 `valid_from=max(D,L)`、`valid_to=E`。`L > D` 是尚未發生的 future listing，只能等待日後 capture，不預建 future membership；若已有任何 collector-owned ETF／new-listing history則 fail，避免用 prospective row 改寫 current state。`D > E` 不補造已過期歷史。`L` 缺失則記 unresolved 並保留既有 new-listing membership；格式非法須 fail，不得以 type、第一根 bar、backfill start 或 score date代填。
- 新建 period 一開始即為 bounded；同一 `valid_from`／`valid_to=E` 的 exact rerun 零 mutation。既有 legacy open period若 D 仍在窗口，只補上 `valid_to=E` 且保留原 `valid_from`；若到本次 D 才首次確知已過期，只能將它 forward-close 於 `D - 1 day`，不得把本次 current observation 倒寫成過去已知的 `E`。後者須在驗收證據揭露 legacy overrun，並保留「D 前期間可能錯誤」限制。
- authoritative listed／new-listing record 會按 L/window 決定 new-listing desired state；authoritative ETF record 才能證明 instrument 已轉入 ETF domain並退出 open new-listing。第 61 日的 ipo→stock、stock／ipo↔ETF 與 category change 都要分 domain 計算 desired state，不得用一個非空 group id 廣泛關閉所有 `etf`／`daily_hot_group` rows。

### 7.4 Domain isolation、atomicity 與 receipt

- candidate reconciliation 只操作 collector-owned canonical `etf` 與 `new-listings` membership；兩個 domain 分別 preflight／transition。ordinary `official_industry`、manual、其他 `daily_hot_group`、缺席 instrument 與 synthetic index 均不在 candidate desired-set closure。不得以全域 `official-*` prefix 廣泛停用 legacy groups；歷史列不刪除、不改名，除上述 forward transition／bounded expiry 外不改日期。
- candidate helper 不自行 commit，也不 rollback caller transaction；`begin_nested()` 前須先確保實體 outer transaction 已開始。特別是 sqlite3 legacy mode 在 SELECT／SAVEPOINT 前可能仍未 `BEGIN`，因此只有 SQLite driver 尚未 `in_transaction` 時才明確開 outer `BEGIN`，再建立 savepoint，避免 `RELEASE` 把 helper mutation 實質提交。helper 成功後的變更仍受 caller commit／rollback 控制；helper 失敗只撤該 savepoint，caller 先前 pending writes 保留。collect 若在 helper 後的 `sync_news_from_events` 或其他 normalized 階段失敗，instrument／bar／group／membership 必須整體 rollback；只有 normalization 前已安全 commit 的 raw capture 保留並進 failed-attempt receipt，不能把部分 candidate success 寫成整批成功。
- 既有 `industry_membership_observations` 的 ordinary-industry `version`、`scope=ordinary_industry_only`、status、counts 與 `observations` 不改義，其 counts 不包含新增子節點。C017-C 在同一物件加入 `etf` 與 `newlisting`：`version` 分別為 `etf-observation-v1`／`newlisting-observation-v1`，`scope` 分別為 `etf`／`newlisting`，並各有 `status`、`skipped_count`、`unresolved_count` 與 `observations`。逐筆以 `raw_payload_id`、source、endpoint、sha256 回指 raw capture，不另宣稱保存 raw category 文字；ETF 另以 `classification_method_version=normalize_etf_category-v1` 明示 local heuristic。TAIEX 等 synthetic index 會在兩個子 scope 留 `unresolved_synthetic_index`，所以行情 run 可 success、ordinary receipt 可 observed，而子 scope 仍為 partial；三者須分開解讀。
- force success、force failure 與非 force idempotent reuse 沿用第 6.1 節 receipt 保存規則：最後成功 `industry_membership_observations` 不被失敗覆蓋，成功 history、latest attempt、failed attempts 與去重 raw 的最早收錄時間仍分開；exact reuse 不以新呼叫時間重寫 D 或 lifecycle receipt。

### 7.5 C017-C 最小驗收矩陣（有限範圍已 review）

| Gate | C017-C／統籌實際案例 | 通過條件 |
| --- | --- | --- |
| ETF source／normalization | TWSE `FundType`、TPEx `indexName`、raw 未知／缺失但 local fallback 為 `thematic`，以及 normalized category 為 null／非法。 | raw 與 local normalized 值分開；heuristic 不稱官方 taxonomy；normalized null／非法使整批 failed／rollback，不猜 category 或退出。 |
| time boundary | ETF 的 `D < score_date`、`D = score_date`、`D > score_date`；另測 `captured_at > observed_now`，並確認 L／start／score 不成為 category effective date。 | ETF period 只自 D forward；合法 capture 的 `D > score_date` 才 skip／partial，未來 capture 直接拒絕。 |
| ETF transition | 初建、unchanged、category change、authoritative ETF→stock／IPO、缺席 instrument、exact rerun。 | 同 domain gapless、可信退出才關舊、缺席不動、exact rerun 零 mutation。 |
| new-listing window | `D < L`、`D = L`、窗口內、`D = E`、`D > E`、第 61 日 type switch、missing L。 | 新 period 為 `[max(D,L), E]`；future 不預建、過期不補歷史、missing unresolved。 |
| legacy expiry | 窗口內 legacy open、已過期 legacy open、同 expiry rerun。 | 窗口內只 cap E；過期只 D-1 forward-close 並揭露 overrun；既有 bounded hot row 若 `valid_to` 與本次 `L+60` 不吻合則保守拒絕，不覆寫成 current evidence 或 PIT。 |
| conflict／isolation | same-day wrong、future／overlap／多 open、closed expiry conflict、target／existing group inactive 或 metadata conflict；future L 與同 instrument 的 industry、manual、其他 hot group。 | mutation 前拒絕衝突；future listing 不關 current ETF，只改已被可信 current record 證成的 canonical domain，其他 membership 不漂移。 |
| receipt／retry／atomicity | success、partial、unresolved、force success／failure、idempotent reuse與 raw 已先保存的失敗。 | 兩個子節點與 ordinary receipt 可分辨；history／attempt 不覆蓋；normalized collect mutation 不部分提交。 |
| safety | 專案外 Temp DB、完整 backend、integrity／FK、正式與 `.local` DB 及保護來源 fingerprints。 | 隔離驗收通過才可改狀態；正式庫、既有 R16 ordinary semantics、derived rows 與前端 guard 不因本批宣稱完成。 |

統籌以 Python 3.12.14、Alembic 1.19.2 完整重跑 backend：481 passed／5,066 warnings，pytest 49.91 秒（process 51.328 秒）、exit 0；作者 C final 另為 481 passed／5,066 warnings／51.55 秒。統籌並以實際 TWSE／TPEx universe parser 處理本地 official-shaped fixtures，再走完整 `collect` 的 11 項檢查：跨市場同 ETF category、new-listing day 60 inclusive／day 61 bounded 自然退出、ETF gapless change 與另一市場不變、same-capture group／membership／歷史 score 不變、同日／缺分類全 normalized rollback、forced failure 保留最近成功 receipt、`D > score_date` 全 membership 不變、authoritative ETF↔stock／IPO 只改 ETF／hot 而保留 industry，以及 manual／其他 hot／歷史 score 不變；integrity `ok`、FK 0。

SQLite physical transaction probe 在 B 版重現 caller rollback 後仍殘留 1 筆 membership，C 修正後 caller rollback 的 group／membership 都為 0；作者四個 transaction cases 亦由 red 轉 green，並證明 helper failure 只撤 savepoint、collect 後段故障會 rollback 全部 normalized mutation而保留先前 raw。C017-C frozen source 只有 `backend/worker/pipeline.py`、`backend/tests/test_etf_listing_membership_collection.py`、`backend/tests/test_official_membership_collection.py` 與 `backend/tests/test_pipeline_integration.py`；沒有 `sources.py`、models、API、frontend 或 schema 變更。統籌完整測試期間所有保護來源與正式／`.local` DB 前後 fingerprints 不變。final 證據在 `C:/Users/YiCheng/AppData/Local/Temp/stock-r17-coordinator-review/full-backend-review.json`、`full-backend.log`、`independent-collector-review.json` 與 `savepoint-rollback-probe.json`；B 版 477 passed 與失敗 probe 均是中途結果，不是 final。初版 independent harness 曾誤把 failed force 前的倒數第二份 transition receipt 與 failure 後 receipt 比較；final 已改核最近成功 repeat receipt並重跑，不宣稱重跑 receipt 的 `action` 必須相同。

本節通過只證 current capture 驅動的 candidate lifecycle。官方端 capture metadata／availability 仍是 caller-trusted assumption；ETF heuristic 品質、legacy 錯誤期間修復、真正 source-effective/PIT、正式 DB 修復、synthetic index lifecycle、ordinary-industry↔ETF 的歷史轉換、舊 derived outputs 重算、metadata history 長期治理、前端 guard 解除與策略有效性皆留待後續。
