# TWSE／TPEx 產業分類與隔離修復契約

更新：2026-09-14。R15 mapping／隔離診斷、R16 ordinary-industry normal collector、R17 ETF／new-listing candidate lifecycle、R35 member-return identity 與 R36 candidate identity 均只在各節表列有限範圍通過 review。正式與 `.local` DB、歷史分類、舊族群分數與研究輸出尚未修復，Round14「既有族群關聯待重新核實」guard 不得撤除。

## 1. 官方證據 snapshot

`classification_evidence_at=2026-09-13`（Asia/Taipei）。TWSE current 表由 B.12.00 基表加 2023-07-03 官方變更組成，再與當次 OpenAPI code 交叉檢查；不能把舊基表單獨稱為 2026 最新版。TPEx 以 2025 v5.41 完整表為主、V12.14 為交叉驗證。API 出表日只識別公司基本資料 snapshot，不是每檔分類生效日。

| 來源 | 本次使用的日期／範圍 |
| --- | --- |
| [TWSE IP 行情網路 B.12.00](https://www.twse.com.tw/staticFiles/product/broker/ff80808166388ea1016676ac941001e0.pdf) | 107/10 修改、109/03 實施；附錄三 01–31 基表。 |
| [TWSE 產業格式公告](https://eshop.twse.com.tw/zh/news/detail/0000000087e9b84901886b8d96940024) | 2023-05-30 公告；2023-07-03 起 code 16 更名並新增 35–38。 |
| [TWSE 公司基本資料](https://openapi.twse.com.tw/v1/opendata/t187ap03_L) | `出表日期=1150911`，1,094 rows；另見 10 筆 TDR code 91。 |
| [TPEx IP 行情網路 v5.41](https://dsp.tpex.org.tw/storage/eb_data/11405/1140500476-1.pdf) | 2025-05-13 文件；current 完整表，並記 2023-07-03 新增 35–38、停用 18／34。 |
| [TPEx 上櫃股票 IP V12.14](https://dsp.tpex.org.tw/storage/eb_data/11309/1130500936-1.pdf) | 2024-09-23 文件；分類表與 v5.41 一致。 |
| [TPEx 公司基本資料](https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O) | `Date=1150912`，891 rows；當次未見 18、34、80。 |

## 2. 完整市場別代碼期待表

`—` 表示 current 一般產業表不支援。internal canonical 是穩定 group identity；官方市場別名稱仍以本表為準。`Tourism`、`Financial` 保留既有 key，觀光共用中文顯示為「觀光餐旅」。

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
| 34 | — | — | TPEx 歷史電子商務碼；current unsupported |
| 35 | 綠能環保 | 綠能環保 | `Green Energy` |
| 36 | 數位雲端 | 數位雲端 | `Digital Cloud` |
| 37 | 運動休閒 | 運動休閒 | `Sports and Leisure` |
| 38 | 居家生活 | 居家生活 | `Household` |
| 80 | — | 管理股票 | 特殊狀態；不建一般產業排行 membership |
| 91 | 一般表未列；當次 TWSE API 僅見 TDR | — | 特殊證券碼；不建一般產業排行 membership |

shared current codes 沒有異義 collision；兩市場 22 都是生技醫療。查表仍必須使用 `(exchange, code)`，因市場專屬、停用與特殊碼不同。歷史錯誤是 TWSE 18、20–31 錯移、缺 19、31 誤接文化創意；TWSE 32、TPEx 18／34 應 unsupported，TPEx 80 是特殊狀態。

## 3. Mapper 與 fail-closed 契約

- 官方 numeric input 必須同時有可辨識 `exchange` 與兩位數 `code`；只對該市場 current ordinary code 回 canonical，其餘為 `None`。不得先跨市場查全域 code。
- blank、`00`、TWSE 91、TPEx 80／18／34、未列碼、缺 exchange 或格式錯誤，都不建立 verified `official_industry`；`Other` 不能作 unknown fallback。
- current 官方 feed 必須保留 exchange＋numeric code 證據；legacy 英文 alias 只供相容讀取，不能升格為官方 truth。
- `backend/tests/fixtures/official_industry_codes.json` 只驗 current ordinary code 集合，其中 `official_names` 是測試樣本，不是完整市場別名稱 oracle。
- manifest 保存 source URL、API 出表日、capture time、mapping version 與每筆 raw exchange／code。legacy 缺少的逐列時間保持 unknown。
- 只有 ordinary industry 可合併成跨市場 canonical group；membership source 至少保留 exchange。

## 4. 三種日期與修復邊界

| 欄位 | 本輪值 | 語意 |
| --- | --- | --- |
| `classification_evidence_at` | 2026-09-13 | current 官方碼表擷取／核對日，不是公司分類生效日。 |
| `membership_effective_date` | 2026-09-13 | current-table diagnostic 副本的 forward transition 日，不是 fresh truth。 |
| `market_data_as_of` | 2026-09-08 | 價格、籌碼、features、group scores 與 signals 的市場截點。 |

`instruments.industry` 沒有 revision history，三種日期不得互換；上市日、raw 收錄日與 market as-of 都不能補造分類生效日。

- current diagnostic 只在 2026-09-13 forward transition：舊錯 open membership 關在 2026-09-12，expected ordinary membership 自 2026-09-13 起；歷史列保留，unknown／unsupported／special 不建 ordinary membership。
- current 副本保留 2026-09-08 scores、signals、evaluations、settlements，不重算或覆寫。
- counterfactual `baseline`／`corrected` 從同一唯讀 backup 建立，價格、籌碼與 features 相同；corrected 只以 current mapping 作情境輸入並用獨立 signal namespace。這是影響量測，不是 2026-09-08 PIT／歷史真值。

## 5. 隔離驗收矩陣（有限範圍已 review）

| Gate | 有限接受範圍 |
| --- | --- |
| mapping | current ordinary codes 精確命中；market-only、停用、特殊、blank／00／unknown 與 numeric-without-exchange fail-closed。 |
| current transition | 每個 supported active stock／IPO 在 2026-09-13 恰有一個 expected membership；unknown／special 為 0；舊列保留且期間無 overlap。 |
| derived preservation | current 副本的 2026-09-08 scores、signals、evaluations、settlements 不變。 |
| counterfactual | baseline／corrected 使用相同 market inputs，只允許 membership、重算 scores 與隔離 signals 有預期差異。 |
| isolation／rerun | 隔離副本 integrity／FK 正常；第二次執行不再漂移；正式與 `.local` DB 不變。 |

2026-09-13 有限 review 的量測：current 與 counterfactual 各有 1,974 個 supported 標的取得唯一 expected membership，35 個 unknown／special 為 0；關閉 1,551 個舊錯 membership（TWSE 845、TPEx 706），新增 1,541 個 expected membership（TWSE 835、TPEx 706），原 2,403 rows 均保留。counterfactual group-score rows 41→52、45 rows 有差異，兩側各 6 個 non-null score；兩側各產生 4,616 筆隔離 signals。這些數字只屬該次隔離資料。

正式 DB 未修復、歷史 effective date 未證、舊 derived outputs 未重算，所以文件、fixture、mapping test 或 counterfactual 成功都不能解除前端 guard，也不證策略有效性。

## 6. Round16 normal collector 觀測期間（有限接線已 review）

R16 只讓 normal collector 對 stock／IPO 的 ordinary `official_industry` 使用可信 capture 的觀測日作 forward transition；不回填歷史。ETF／new-listing lifecycle 由第 7 節另行定界。

### 6.1 觀測時間與來源綁定

- 每筆 instrument 必須以 `payload_sha256` 唯一匹配同 batch authoritative universe capture，並核對 exchange、source、endpoint allowlist 與 digest。TWSE／TPEx ordinary industry 只能各自來自 listed-company endpoint。
- `captured_at` 取 `FetchedPayload.collected_at`；現行 local capture 的 naive 值依既有契約按 UTC 解讀，其他 naive 時間不可類推。正規化後須確認不在未來，再轉 Asia/Taipei 日曆日 `D=observation_date`。
- `D` 是本系統開始採用 current observation 的下限，不是來源 effective date或 PIT。`data_as_of`、listing／start／score date 都不能替代。
- 若 `D > score_date`，該 instrument 的 ordinary membership 全部 skip，不關舊、不新增；run receipt 記 warning、counts 與兩日期，行情 backfill 可繼續。
- receipt 的 `industry_membership_observations` 保存 `version=industry-observation-v1`、`scope=ordinary_industry_only`、status、skipped／unresolved counts、warnings 與逐筆 source／endpoint／digest、capture／observed／score dates、raw refs、time relationship、raw classification 和 status。
- force success 將前一成功 receipt append 到 history；force failure 保留最後成功 receipt，並另存 latest attempt／failed attempts。非 force reuse 不改寫既有成功 receipt。
- raw 去重時間不能冒充當次 capture。新 raw 的 aware time 正規化成 UTC-naive 以符合現有 SQLite 欄位；missing／invalid timestamp 不以 DB default 或現在時間補造，run 必須成為 failed，並保留可得的原檔、digest與 persistence error。
- 只出現在 TWSE new-listing endpoint 的 IPO 沒有 ordinary-industry authority，限縮為 skip＋warning；其他 identity／digest／source conflict 仍 fail-closed。

### 6.2 Ordinary-industry 狀態與期間轉換

- numeric current ordinary code 形成單一 desired canonical group。可信的 non-empty numeric unknown／special／unsupported 形成空集合，只關閉先前 ordinary membership；blank、non-numeric 或 ambiguous evidence fail-closed，不能當成「確認無產業」。
- reconciliation 只操作 collector-owned `official_industry`；manual、ETF、`daily_hot_group` 與 universe 缺席標的不動。
- exact 同日同 canonical open membership 是零 mutation。舊 open row 的 `valid_from < D` 時，change 先關於 `D-1` 再自 `D` 開新 row；可信空集合只關閉。
- same-day wrong、future open、overlap／multiple-open、inactive 或 metadata 衝突須在 mutation 前拒絕；不得刪歷史、改日期或任選一列。raw 可先保存，但 membership／group mutation 整筆 rollback。

### 6.3 最小驗收矩陣

| Gate | 必須成立 |
| --- | --- |
| evidence／time | authoritative identity 唯一；D 只來自可信 capture；future time 拒絕。 |
| score boundary | `D<=score_date` 只 forward transition；`D>score_date` skip，不污染舊 score。 |
| transition | unchanged／change、可信空集合、ambiguous failure 與 exact rerun符合 §6.2。 |
| conflict／atomicity | same-day、future、overlap、inactive 與 evidence conflict 在 mutation 前拒絕。 |
| isolation | other domains、缺席 instrument、manual 與既有 score不因 industry reconciliation 漂移。 |
| receipt／retry | 成功、partial、reuse、force failure 與 raw time error可分辨且不覆蓋最後成功 evidence。 |

2026-09-13 的有限 review 包含 actual universe parser→本地 official-shaped fixtures→完整 `collect`、aware timestamp、transaction、integrity／FK 與正式／`.local` DB 不變檢查。它不是 live 官方來源、source-time truth、legacy raw time repair、歷史 PIT 或正式 DB 修復。

## 7. Round17 ETF／new-listing candidate lifecycle（有限接線已 review）

R17 只完成 current capture 驅動的 ETF 與 `new-listings` candidate lifecycle；不改第 6 節 ordinary counts／scope，也不授權正式資料修復。

### 7.1 來源語意與五種日期

- TWSE ETF raw 類型來自 `FundType`，TPEx 來自 `indexName`，再交現行 `normalize_etf_category(value, symbol, name)`。`broad_market`、`dividend`、`sector`、`thematic`、`commodity`、`bond`、`leveraged`、`inverse` 是 local heuristic，不是共同官方 taxonomy；未知文字或只有 symbol／name 可 fallback `thematic`，receipt 必須標 method/version。
- candidate record 仍須唯一綁定相符市場與 endpoint 的 authoritative capture。ETF presence/category 只由 ETF endpoint 證明；stock／IPO presence、上市日與退出只由相符 listed-company／new-listing record 證明。
- capture time、未來拒絕與 `D>score_date` skip 沿用 §6.1。

| 名稱 | 意義 | lifecycle 用途 |
| --- | --- | --- |
| `D`／`observation_date` | capture 的台北觀測日 | transition 不得早於 D。 |
| `L`／`listing_date` | authoritative 掛牌／核准上市日 | 只界定 new-listing 事件與 60 個曆日窗口。 |
| `start_date` | 行情 backfill 起日 | 不建立 candidate period。 |
| `score_date` | collect／analysis 截點 | 只作截點與 skip 判斷。 |
| `E=L+60 days` | 0..60 inclusive 的最後曆日 | bounded `valid_to`；不是 60 根 bars。 |

### 7.2 ETF category lifecycle

- valid local category 形成 `group_type=etf` 的單一 desired membership；group identity 跨市場共用，membership source 保留 exchange，receipt 保存 endpoint、digest 與 heuristic version。
- 新 period `valid_from=D`；category change 於 `D-1` 關舊、自 D 開新。exact same-day same-category rerun 零 mutation；same-day wrong、future、overlap／multiple-open、closed conflict 或 inactive／metadata conflict fail-closed。
- category 缺失／非法或 capture 無法唯一綁定時整批 rollback，不關既有 ETF membership。heuristic fallback 不能稱來源驗證。
- ETF→stock／IPO 退出只接受相符 authoritative current record；`L>D` prospective row、缺席、synthetic index或其他 domain membership 都不能證明退出。

### 7.3 New-listing window 與到期

- new-listing 是 stock／IPO 的事件型 `daily_hot_group`；窗口為 `0 <= D-L <= 60` 個曆日 inclusive，與 20／60 根有效 bars 的 actionable guard 分離。
- 只有 `L<=D<=E` 才新建 `[max(D,L), E]`。`L>D` 不預建 future period；`D>E` 不回填過期歷史。missing L 為 unresolved 並保留舊 membership；invalid L fail-closed。
- 新 period 一開始即 bounded，exact rerun 零 mutation。legacy open row 在窗口內只補 `valid_to=E`；本次才觀察到已過期時，只可 forward-close 於 `D-1` 並揭露 D 前可能錯誤。既有 bounded row 的 `valid_to` 與本次 E 不符時拒絕，不覆寫。
- listed／new-listing record 依 L/window 決定 desired state；ETF record才可證明轉入 ETF。每個 domain 分別計算，不能用單一 group id 廣泛關閉其他 rows。

### 7.4 Domain isolation、atomicity 與 receipt

- reconciliation 只操作 collector-owned canonical `etf` 與 `new-listings`；ordinary industry、manual、其他 hot groups、缺席 instrument、synthetic index 不在 closure。
- helper 不 commit／rollback caller transaction。SQLite 在 `begin_nested()` 前確保 physical outer transaction 已開始；成功仍受 caller commit／rollback，helper failure 只撤 savepoint。collect 後段失敗時 normalized instrument／bar／group／membership 全 rollback，先前安全 commit 的 raw 可保留。
- ordinary receipt 的 version/scope/counts 不改。`etf` 與 `newlisting` 各有 version、scope、status、counts、observations；ETF 另帶 `classification_method_version=normalize_etf_category-v1`。synthetic index 可令 candidate scope partial，而行情 run與 ordinary scope仍 success／observed，三者分開解讀。
- force history、failed attempt、raw 去重與 exact reuse 規則沿用 §6.1。

### 7.5 C017-C 最小驗收矩陣（有限範圍已 review）

| Gate | 必須成立 |
| --- | --- |
| ETF source／normalization | raw 與 local normalized category 分開；null／illegal category fail＋rollback。 |
| time | D 只作 forward observation；`D>score_date` skip；future capture拒絕。 |
| ETF transition | initial／unchanged／change／可信退出／缺席／rerun符合 §7.2。 |
| new-listing | future、day 0、day 60、day 61、expired、missing L 符合 §7.3。 |
| legacy／conflict | cap、forward-close、wrong expiry、same-day、overlap與 identity conflict均保守處理。 |
| transaction／receipt | caller rollback有效、helper failure只撤 savepoint、後段 failure不留 normalized partial write；scope receipts不互相覆蓋。 |

2026-09-13 的有限 review 包含 actual parsers、本地 official-shaped fixtures、完整 `collect`、SQLite caller rollback／savepoint、integrity／FK 與保護來源檢查。未完成項：官方 capture metadata／availability truth、ETF heuristic 品質、legacy 錯誤期間、source-effective/PIT、正式 DB 修復、synthetic index lifecycle、ordinary-industry↔ETF 歷史轉換、舊 derived outputs 重算、metadata history治理、guard解除與策略有效性。

## 8. 群組衍生成員報酬的身分契約（有限 review）

群組分數仍依當日有效 membership 計算；本節只規範 `GroupDailyScore.details_json.member_returns` 到個股策略輸入的身分連結，不改 `hot_group_v1` 分數、最低成員數、`breakout_v1`／`pullback_v1` 公式或策略版本。

### 8.1 新產出與精確讀取

- 新產出的 `details_json` 必須有 `member_return_identity_version="instrument-id-v1"`。每個 `member_returns[]` 同時保存正整數且非布林的 `instrument_id`、非空 `exchange` 與 `symbol`；整份清單的 ID 及 `(exchange, symbol)` 各自不得重複。`instrument_id` 是該 DB 內的本地鍵，仍須用 exchange＋symbol 交叉核對；這不證明跨 DB 可攜性或來源 truth。
- worker 只用 `instrument_id` 找目標列，並要求該列的 exchange／symbol 與目標 Instrument 完全相同；目標的 `excess_return_20d` 只接受有限的原生整數或浮點數，布林、字串、null、NaN 與 infinity 都視為不可用。
- member-return helper 只處理已由既有 group selection 選中的 score，不取代其有效 membership、active group、score date、TAIEX benchmark、最低成員數與有限 group return gates。
- marker 未知／空值、列結構或 identity 非法、`instrument_id`／`(exchange, symbol)` 重複、目標缺席或 identity 衝突時一律 fail closed；有 marker 的 payload 不得降級用 symbol 猜測。這個拒絕只約束 member-return 輸入，不改 `candidate_symbols` 的既有字串相容輸出。

### 8.2 舊 payload 的有限相容

沒有 marker 的舊 payload 只有在所有列都沒有 `instrument_id`／`exchange` 時才可能相容讀取。worker 必須以該 score 的 `group_id` 與 `signal_date` 重查有效 membership，再套用與 producer 相同的股票／ETF 類型及 category gate；相同 symbol 的有效 canonical identity 必須恰好是目標 `instrument_id`，而 payload 也必須恰有一筆同 symbol 且其 20 日超額報酬為有限數值，才可採用 `legacy_symbol_unique`。

只看 payload 中同 symbol 的筆數不足以證明身分：另一市場的同 symbol 成員即使因技術資料不足而沒有寫入 `member_returns`，只要在當日仍是有效成員，就必須拒絕。期間邊界、群組、類型或 identity 無法唯一核對時，輸入保持 null，不任選第一筆。

### 8.3 證據、相容邊界與後續缺口

- Signal 的 `rule_evidence_json.group_member_return_lookup` 保存 `version="group-member-return-lookup/v1"`、來源 marker、group／score date、requested 與 matched identity、`instrument_id`／`legacy_symbol_unique`／`rejected` mode 及 reason。拒絕時 matched 為 null，策略仍走既有缺資料語意。
- `group_daily_scores` 仍以 `(group_id, trading_date)` 原位重算；本輪不改 schema 或既有 upsert 行為，也不做歷史批次 migration 或回算。新 producer 重算後才有新版 identity，舊列只受 §8.2 的保守相容保護，因此不能宣稱歷史群組資料已全面 canonical。
- `candidate_symbols` 與 decision lookup 的獨立身分缺口及 R36 核定契約見 §9；本節的 member-return 完成狀態不代表候選身分也已完成。

本節的有限 review 只接受新 producer 的 member identity、worker 精確／legacy lookup、拒絕語意及 Signal evidence；未改 domain 公式、策略 pin、群組分數、candidate selection 或歷史資料。

## 9. 群組候選的身分契約

狀態：R36 已有限 review。本節規範 `GroupDailyScore.details_json` 的候選產出到 decision candidate selection。外層 score 仍須通過既有的 active group、`data_quality="complete"`、至少 3 個 eligible members、非空 rank 與 `benchmark="TAIEX"` gate；`hot_group_v1` 公式、候選排序、top 4 上限、策略 pins 與其他 action buckets 不變。

### 9.1 新產出與顯示投影

- 新 score 使用 `candidate_identity_version="instrument-id-v1"`，並把同一批已排序 member metrics 的 top 4 寫入 `candidate_instruments[]`。每列必須有正整數且非布林的 `instrument_id`，以及非空字串 `exchange`、`symbol`；整份清單的 ID 與 `(exchange, symbol)` 各自不得重複，最多 4 列。
- `candidate_symbols` 保留為相容 API／UI 的字串投影，必須與 `candidate_instruments` 等長、同順序且逐列等於 `symbol`。兩個不同 exchange 的合法 identity 可以同 symbol，因此投影可有重複 symbol；consumer 不得再用投影反推身分。
- producer 的 eligible member、股票／ETF 類型與 ETF category gate、20／5 日排序及「score 不成立則候選為空」語意不變。`instrument_id` 是該 DB 的本地鍵，exchange＋symbol 只供交叉核對，不宣稱跨 DB 可攜或官方來源 truth。

### 9.2 Typed decision lookup

- marker 只接受精確的 `instrument-id-v1`。marker unknown、null、空值，無 marker 卻混入 typed 欄位，candidate list／projection 結構錯誤、超過 4 列、ID／pair 重複或逐列投影不一致時，整個 score 的 candidate source fail closed；不得降級用 symbol 猜測。這不移除 held、watchlist、Signal、event 等其他 action bucket。
- 每列先以 `score.trading_date` 驗證 exact `instrument_id` 對應的 Instrument exchange＋symbol、該 group 當日有效 membership，以及 producer 相同的 instrument type／ETF category gate。來源日驗證不得用 Instrument 的目前 active 狀態排除 membership 身分；任何來源日不合資格或 identity conflict 都拒絕整個 score 的候選來源。
- 再以 requested as-of 驗證同一 `instrument_id` 仍為 active、仍有該 group 有效 membership，且仍通過相同 type／category gate。正常的 as-of 退出只逐 ID 排除，不拖垮同 score 的其他合法候選，也不得改綁另一個同 symbol Instrument。

### 9.3 Legacy 相容與時間邊界

- Legacy 只限沒有 marker、沒有 `candidate_instruments`，且 `candidate_symbols` 是最多 4 個非空字串的清單。其他 malformed shape 拒絕整個 score 的候選來源；重複 symbol 則保守排除該 symbol，不影響其餘可證明者。
- 每個 legacy symbol 必須先在 `score.trading_date` 以該 group 的所有有效 membership 與 producer type／category gate 證明恰好一個 canonical `instrument_id`；此步不得用目前 active 狀態把現在 inactive 的同 symbol 成員濾掉，否則會把來源日歧義洗成唯一。其後才要求該 exact ID 在 requested as-of 仍 active、有效且通過同 gate。來源日歧義不能因後日只剩一個同 symbol 成員而解鎖；來源日唯一的舊身分退出後，也不能轉綁後加入的同 symbol 身分。
- `Instrument.status`、instrument type 與 ETF category 目前沒有可供此 lookup 重建的完整歷史版本；上述核對只能保守使用現有 metadata 與 membership period，不構成 source-effective 歷史 truth 或 PIT 證明。

### 9.4 相容邊界與驗收

- R36 當輪 API／UI 仍只輸出既有 `candidate_symbols`／`candidates` 字串欄位；R38 另完成 public typed source-day 投影，見 §9.6。Schema 與 `group_daily_scores` 的 `(group_id, trading_date)` 原 upsert 行為不變，既有 rows 不做批次回算；同日正常重算仍可由原 upsert 更新該 row，重新產出的 score 才帶新 marker。
- 最小驗收須走 actual producer→persisted score→decision：至少 5 個有效成員，top 4 只選中其中一個市場的同 symbol identity，另一個市場成員不得被額外展開；另涵蓋來源日歧義、後日退出／加入、正反插入順序、typed malformed／重複／identity conflict、legacy unique／ambiguous 與其他 action bucket 保留。
- Decision helper 目前對每個 qualifying group 各做一次 identity／日期 projection，再合併候選；本批未驗大規模群組效能、actions cursor 遍歷或分頁，新 candidate unit suite 不能當成 pagination 驗收。
- 2026-09-14 的有限 review 接受 producer、decision helper、新 focused suite 與既有 product／actions／producer targeted regressions；程式來源已 freeze。它不是 full backend、正式 DB、服務、效能／cursor、PIT 或歷史驗收。
- R37 已有限 review backfill／coverage 的 typed 相容，獨立納入語意見 §9.5；R38 的 public source-day 展示另見 §9.6。這些後續小批不回寫 R36 的 decision 驗收範圍，也不代表歷史資料、正式分類修復或策略有效性完成。

### 9.5 Backfill／coverage 的候選納入契約

狀態：R37 已有限 review。本節只規範 `resolve_backfill_scope` 的 `candidates`／`priority` 候選來源，以及直接重用該 resolver 的 `/api/coverage?scope=candidates|priority`；它們建立資料回補／coverage 的 `(exchange, symbol)` **納入集合**，不是 decision candidate selection。不得套用 §9.2／9.3 的 group qualification、rank、membership、instrument type 或 ETF category 縮選，也不改 `hot_group_v1`、score 產出、Signal 或其他 priority bucket。

- 只讀 `trading_date` 落在 caller 起訖日內的 `GroupDailyScore`；score date 只作範圍邊界，不表示 source availability／PIT。非 object 的 `details_json` 略過，不由其他欄位猜測。
- 只要 `candidate_identity_version` 或 `candidate_instruments` 任一 typed 欄位存在，就進 strict typed envelope：marker 必須精確為 `instrument-id-v1`；typed／projection 都須為最多 4 列的 list；每列 `instrument_id` 必須是非 bool 且落在 SQLite signed 64-bit 可查詢範圍 `1..2^63-1` 的整數，exchange／symbol 必須是非空字串；ID 與 pair 各自唯一，`candidate_symbols` 必須等長、同序且逐列等於 typed symbol。任何 shape、marker、超界、重複或 projection 錯誤都拒絕該 score 的整份候選貢獻，不得 fallback 到 symbol。
- 合法 typed envelope 要先把**全部 ID（包括目前 inactive）**對照同一 DB 的 Instrument，逐列證明 exact ID 對應 payload 的 exchange＋symbol；缺 ID 或 pair conflict 拒絕整個 score。完成整份核對後才逐 ID 套目前 active filter，保留仍 active 的 exact pair；inactive 不得改綁同 symbol 的另一列。這是 local DB identity 與目前可回補範圍，不是 score-date membership、歷史 instrument metadata 或 PIT 證明。
- Legacy 僅限 marker 與 typed 欄位都不存在。`candidate_symbols` 保留既有 list＋`str(...).strip()` 相容，空字串略過、重複值去重；每個 symbol 納入所有目前 active 的同 symbol exchange 列。這種安全擴大只避免回補漏抓，不證明哪一列可供決策，也不得反向放寬 §9.3 的 legacy selection。
- Signal 候選與 `priority` 的 portfolio／watchlist／event 等來源各自保留；某個 malformed typed group score 只移除該 score 的候選貢獻。既有 backfill run 已保存的 `metadata.target_instruments` 是 run snapshot，resume／force 不重新解析；修正只影響新建或實際重新 resolve 的範圍。
- `/api/coverage` 在具名 scope 時直接使用同一 internal resolver，因此會受本契約影響；R38 的 public typed source-day 展示是另一條讀取契約，不能反向改變本節的 collection inclusion 語意，見 §9.6。
- 2026-09-15 的有限 review 接受 worker helper 與獨立測試：實際記憶體 ORM `flush`／`expire` readback 後，走 resolver → metadata plan → scoped adapter，並直接呼叫 coverage function 檢查真 report；涵蓋 typed 精確市場／雙市場／空列、inactive、不存在、signed 64-bit 邊界／超界或衝突 ID／pair、第二列失敗不洩漏第一列、malformed envelope、legacy coercion／重複／跨市場擴大、日期範圍、跨 score union、Signal／priority 獨立來源及不套 decision type/category。它不是 HTTP、完整 targeted backfill、磁碟持久化、全 backend、效能、正式 DB、非 SQLite、availability 或 PIT 驗收。

### 9.6 Public candidate 的 source-day 身分展示契約

狀態：R38 已有限 review。本節只規範既有 group score 在 public API 與族群詳情 UI 的來源日身分展示；它不是 §9.2 的 requested-as-of decision selection，也不是 §9.5 的 backfill／coverage inclusion。

#### 9.6.1 Public representation 與 fail-closed

- Public payload 保留原有 `candidate_symbols`（theme）或 `candidates`（group）文字陣列，並新增固定 `public_candidate_identity_version="instrument-id-string-v1"` 與 `candidate_instruments[]`。Public `instrument_id` 必須是 `1..2^63-1` 的十進位字串，避免超過 JavaScript safe integer 後失真；它仍是同一 DB 的本地鍵，不宣稱跨 DB 可攜，也不改其他 API 既有的 numeric `instrument.id`。
- `public_candidate_identity_version` 只標示 public representation，不單獨證明來源身分有效。Typed consumer 必須同時取得完整 `candidate_instruments[]`，並驗證每列非空 `exchange`／`symbol`、十進位字串 ID、最多 4 列、ID 與 pair 各自唯一，以及與文字陣列等長、同序且逐列 symbol 相同；兩個市場可有相同 symbol。
- Server 先嚴格驗 internal `candidate_identity_version="instrument-id-v1"`、typed／文字 list、長度與上限、正整數非布林且在 SQLite signed 64-bit 範圍的 ID、非空 pair、ID／pair 唯一及 ordered projection。任一列或 envelope 不合法，整份 public `candidate_instruments` 為空，不洩漏部分成功，也不以 symbol 反推 identity。
- 原文字陣列是相容顯示，不是身分證據：只保留原生非空字串，維持原順序與重複值；malformed 的非字串／空白項目略過，不做 `str(...)` coercion。Legacy、缺 DB／score 或 malformed typed source 都只能留下這種安全文字，不能產生 typed link。

#### 9.6.2 Source-day 核對與 endpoint gate

- 合法 internal envelope 的**所有** ID 必須先在同一 DB 找到 exact Instrument exchange＋symbol，並證明該 group membership 在 `score.trading_date` 有效，且通過 producer 相同的股票／IPO 或 ETF group type／category gate；任一 ID 缺失、pair conflict 或來源日不合資格即整份 typed identity 為空。
- 這是 score-source snapshot 的展示，所以不套 Instrument 目前 active、official/requested as-of membership 或 backfill 的 active-symbol 擴大。來源日後退出或目前 inactive 的 exact identity 仍保留，且可用其 exchange＋symbol 連到個股頁；它不表示目前仍可決策、可交易或具官方 PIT。
- Theme product 投影（dashboard themes、themes list／detail／members）保留既有 qualified gate：不 qualified 時文字與 typed 候選都為空。Legacy group 相容投影（dashboard groups、groups list／detail）不新增 theme qualification gate；即使能展示合法來源 payload，也不等於 qualified 或 actionable。Full、compact 與 route projection 共用同一驗證，compact 仍只保留原有 top 4 顯示上限。

#### 9.6.3 UI、驗收與限制

- 族群詳情只在 public marker、整份 typed shape、ID／pair 唯一及 ordered symbol 對齊都合法時建立 `/stocks/{exchange}/{symbol}`；文字顯示 exchange＋symbol，同 symbol 跨市場仍可分辨，React key 使用 identity 加序位。Legacy 或 malformed 只顯示文字，不查目前 member page，也不因 pagination 是否載完而改變連結。
- 候選的「評分日期」讀 score `trading_date`；成員表的「成員資料截至」獨立讀 members response `meta.data_as_of`。不得用目前 members、不同日期或已載入的單一 member page 反推 score candidate identity。
- 2026-09-15 的有限 review 接受 9 個 focused tests：記憶體 ORM commit／expire 與 JSON type assertion、所有 helper 與 in-process ASGI route 投影、inactive／後日退出、跨市場同 symbol、`2^53+1` 與 SQLite max ID、malformed／legacy、source membership／type-category、member pagination，以及 actual React SSR；另有 TypeScript no-emit 檢查。ASGI 使用實際 API router 與 memory DB dependency override；React SSR 的 query／router 與不相關 child 使用小型替身。沒有 socket、lifespan、真瀏覽器、full backend、正式 DB、效能、PIT 或歷史回算驗收。Instrument status／type／category 缺完整歷史版本，因此來源日核對仍不是 source-effective metadata truth。
