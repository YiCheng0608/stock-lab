# 資料來源、coverage 與限制

更新：2026-09-13。Round09 只對首批四個既有官方 OpenAPI endpoint 做來源文件查證與各一次有界唯讀 probe；下列既有資料計數仍沿用原文件歷史驗收紀錄。新增的 source registry 已通過有限 foundation review，尚未接完整既有 collector／pipeline 或 condition executor。Round27 另確認具名 SQLite snapshots 的 schema／row preservation，並把目前 checkout 的 API startup 改成有限唯讀 readiness gate；兩者都不是市場 coverage、內容正確性或 PIT 證據。能力狀態見 [ROADMAP](ROADMAP.md)，逐來源證據見 [SOURCE_REGISTRY](SOURCE_REGISTRY.md)。

## 資料庫政策

現有 collect／daily／backfill 使用官方來源，SQLite 保存正規化市場資料、衍生研究資料及 raw 參照；沒有可信市場資料時呈現尚無資料。下一版可新增經確認的媒體／國際／分點資料層，但須分開來源、版本與推論，不能覆寫官方事實。Round09 未啟用新來源，也沒有讓 registry 自動改變 legacy collector。

## 正式 data/stock.db：歷史 P0 結果

驗收時間為 2026-09-10。P0 的市場資料窗口已達成，但 run 不是完整 coverage；它保留 partial、unsupported 與 skipped 的差異，且所有數字均為正式官方資料與稽核證據，不是範例。

| P0 證據 | 結果 | 解讀 |
| --- | ---: | --- |
| verified TAIEX sessions | 65，target_met=true | 可作 1／5／20 日比較和 60 日策略窗口的共同基準。 |
| 明確 no-data／skipped | 2 | 不算有效交易日，不會被補成行情。 |
| bars | 149,770，含 65 筆 TAIEX | 市場窗口存在，但不是每個標的皆完整。 |
| chips | 148,346 | 需要時仍以標的、日期、欄位 gate 檢查。 |
| 2330 | bars 65、chips 65、20／60 日 gaps=0 | 這是單一標的的 coverage 證據，不可外推到全市場。 |
| 行情未達 20／60 日 | 244／333 檔 | 受影響標的與其群組策略結果必為 data_incomplete。 |
| chips 未達 20／60 日 | 139／173 檔 | 不補 0；需要法人／融資的 gate fail-closed。 |
| events | 65 session 全為 unsupported | 官方 feed 不是可按日期驗證的 empty-session；催化劑必為 null，不是 0。 |
| fundamentals | 65 session partial | 目前不是 v1 策略輸入，但不可說已完整。 |
| corporate actions | 2 success、63 partial | 受影響的價位／tracking 缺可追溯資料時為 incomparable 或 data_incomplete。 |
| integrity／provenance | 正常 | DB integrity、FK、provenance 已通過；正式 pre-P0 backup 已存在。 |

P0 的 global status 是 partial。原 Phase 3 的 P1 只規劃分析 2026-09-08，屬歷史作業範圍，不限制所有未來分析。歷史背景見 [PHASE3_PLAN](PHASE3_PLAN.md)；現行聚合契約見 [PRODUCT_SPEC](PRODUCT_SPEC.md#action-merge)。實際 CLI analyze 仍有最新 collect run gate，不能由文件推論 per-as-of 分析入口已可用。

## Official sources 與實作方式

| 資料域 | 官方來源／目前處理 |
| --- | --- |
| TWSE universe | https://openapi.twse.com.tw/v1/opendata/t187ap03_L（上市公司）、t187ap47_L（ETF）及新上市來源建立 allowlist。 |
| TPEx universe | https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O（issuer master）加 https://info.tpex.org.tw/api/etfFilter POST（ETF allowlist）。混合 quote 的權證、CB、ETN、興櫃不會 fallback 成 stock。 |
| TWSE OHLCV | 當日為 https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL；bounded history 為 https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX，並依 allowlist 過濾。 |
| TPEx OHLCV | https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes POST；body 使用 date=YYYYMMDD、response=json，0–3 個月逐日擷取並依 stock／ETF allowlist 過濾。 |
| TWSE chips | 法人為 https://www.twse.com.tw/rwd/zh/fund/T86；融資為 https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN。 |
| TPEx chips | 法人為 https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade POST；融資為 https://www.tpex.org.tw/www/zh-tw/margin/balance POST。 |
| TAIEX | 官方指數資料，供 hot-group 的超額報酬基準。 |
| MOPS／公司行動 | 重大訊息、基本面 snapshot 與 corporate actions，供催化劑和 execution／settlement 調整。 |
| 停復牌 | TPEx https://www.tpex.org.tw/openapi/v1/tpex_spendi_history 會寫入可稽核 suspension／resumption event；TWSE 完整歷史 coverage 尚不完整。 |
| Raw provenance | 每個 payload 保存 endpoint、SHA-256、擷取時間、data-as-of；正規化行情、chips、事件可連回 raw payload。 |

## Round09 R1-A1／G-SOURCE 首批有限 review

本批查證 `STOCK_DAY_ALL`、`holidaySchedule`、`TWT48U_ALL`、`tpex_spendi_history` 四個現有 GET endpoint。四者在對應政府資料集頁均標示免費與政府資料開放授權條款第 1 版；raw 保存／摘要可在顯名、來源完整性與 provenance 條件下分別列為候選准入。官方頁沒有提供數字 rate limit、精確發布時鐘、逐筆 first availability、完整 revision／withdrawal lineage 或 endpoint-specific deprecation notice，所以這些欄位保留 `unknown + reason`。

用途必須分開：`local_fetch`、`raw_store`、`summarize` 有各自正面證據與 machine-readable conditions，不會因缺 point-in-time 證據一併被封鎖；`historical_pit` 則對四者全部 fail closed／unsupported，直到可重建當時版本與可得時間。一次 HTTP 200、今日 payload shape、fixture 或 endpoint 名稱含「history」都不能補足這個缺口。完整 identity、授權、時間、probe hash 與 decision matrix 見 [SOURCE_REGISTRY](SOURCE_REGISTRY.md)。有限 review 只涵蓋唯讀 registry／四來源人工查證；不能寫成整體 R1-A1、runtime condition enforcement 或 collector 接線已完成。

目前 events／NewsItem 已有官方事件投影、來源連結、raw 稽核、published_at 等時間欄位，以及 display_time／time_basis／time_precision／time_consistency。新聞詳情與來源時間排序在程式可見，不再記為未實作；但時間欄位存在不等於來源已提供每筆可信時間。原 P0 unsupported 也不能被解讀為零事件。

主要 worker 尚未接入完整媒體／國際新聞或分點資料；ChipSnapshot 雖有 day_trade_ratio、short_balance、borrowed_sell，現有 ChipRecord／_upsert_official_chip 主要傳遞法人及融資，不能據此聲稱上述資料已被收集。事件來源、AI 摘要與時間治理統一見 [NEWS_SPEC](NEWS_SPEC.md)。

## 0–3 個月隔離收集驗證

原文件記載當時程式在隔離 DB 以 2026-06-10 至 2026-09-08 進行 official-only 收集，整體結果為 partial：

| 階段 | bars | chips | raw | 稽核結論 |
| --- | ---: | ---: | ---: | --- |
| 首次收集 | 145,180 | 142,149 | 381 | 有官方資料品質警告，故 run 為 partial。 |
| 相同 request 重跑後 | 145,180 | 143,520 | 389 | 使用同一 run_id；已驗證沒有 duplicate key、raw orphan 或 bar／chip orphan。 |

這驗證 TPEx 三個月官方 OHLCV、法人與融資流程、raw provenance 與冪等行為已接入；它不表示整體 TWSE／TPEx 歷史資料完整，也不代表正式 data/stock.db 已擁有三個月 coverage。

## v1 資料規則與歷史來源限制

- --months-back 只允許 0、1、2、3。1–3 個月收集應先在隔離 DB 執行並檢查 run status、data_quality 與 raw evidence。
- TWSE 對明確 no-data 且無列的日期會安全略過；日期錯誤、日期缺失或資料缺日的 payload 會 fail-closed，絕不映射為其他交易日。
- 原驗收紀錄中，歷史 TWSE MI_INDEX／CDN，以及 T86／MI_MARGN 在部分日期回應 307／428；2026-09-08 的 MI_MARGN 亦未提供可驗證日期。這是整體三個月 run 為 partial、不能宣稱歷史 chips 完整的原因。
- chips 已接入，不是未實作功能；但任何交易所、日期、欄位或 allowlisted 標的缺少完整法人與融資時，資料品質為 partial／missing。v1 所需特徵不補 0，策略結果是 data_incomplete。
- P0 events 的 65 個 session 都是 unsupported，不是「65 日沒有事件」。hot_group 的 catalyst 需為 null、品質為 partial；只有四個其他 component 完整且同榜 event coverage 一致 unsupported 時，才可有不稱熱門的技術與籌碼觀察。
- ETFs 一律收集、分類並進 ETF hot-group 分榜。bond、leveraged、inverse 只排除於一般 v1 actionable signal，不排除於資料或排行。
- TPEx suspension history 已接入；TWSE 完整歷史 suspension coverage 仍可能讓追蹤結果成為 incomparable。

## 資料庫安全

目前程式的 migration head 為 Alembic `0006_news_json_defaults`，前置依序為 0001_schema_v1、0002_instrument_exchange_key、0003_backtest_run_metadata、0004_product_news_themes、0005_news_temporal_contract，另有可寫第六枚 marker 的相容 schema fallback。Round11 只在專案外 Temp SQLite review `news_items.symbols_json`／`theme_ids_json` 的 SQL `[]` defaults、舊 schema repair 與 atomic failure-safety；這不表示所有 historical schema parity 或非 SQLite 已驗證。

歷史狀態不可回寫：C003／R11／R25 review 時正式 `data/stock.db` 沒有 `alembic_version`、只有五筆 fallback markers，Round11 沒有對它執行 0006、restore 或 deployment。R26 期間另一個使用者 preview task 的舊 lifespan 實際把正式 DB 升到 0006；Round27 唯讀觀察的正式檔為 296,366,080 bytes、SHA-256 `3a21772050b3053557c0798876cc0aa1efe024fcbdce5ab44e35e6abf12da018`，`.local` 檔為 438,272 bytes、SHA-256 `87453d7b29954b6d506f8020b8987f321aa6749ce9bc24fbef695dd3874b8d02`。R27 沒有 migration、repair 或 restore 兩個來源 DB。

Round27 的具名保存檢查以外部 consistent snapshots 比較 R26 saved original 與 current：20 個歷史表／622,399 rows 的 type-tagged full-row multiset hashes 相同，沒有舊欄增刪；schema 差異只有新 `alembic_version`／PK autoindex，以及兩個 News JSON `[]` defaults／identifier quoting。另在外部副本實跑 0001→0006，21 個 table descriptors、typed rows 與完整 `sqlite_schema` 均等於 current snapshot。這只解釋這組 saved-original／current／replay，不證所有 legacy 或 custom schema、正式 deployment／restore、介入期間的因果、資料內容真實性或 PIT。

目前 API startup 只讀 marker 與有限 mapped schema identity，不會建庫、migration 或 repair；`worker.cli init-db` 與其他 worker 明確流程仍可初始化／升級。readiness 不做完整 type／nullability／collation／FK action／CHECK／額外 schema 稽核，也不掃歷史 rows、FK 資料或深層 integrity。正式升級仍須先取得授權及 consistent backup，再依 [操作手冊](OPERATIONS.md) 於指定隔離副本驗證。

本輪未建立排程；歷史驗收未建立 Windows Task Scheduler／Codex 排程。後續資料收集排程與交易自動化分開評估，見 [ROADMAP](ROADMAP.md)。

## 下一版資料需求與可得性

下列是需求，不是已簽約、已接入或已確認 coverage。

| 資料 | 優先目的 | 必須確認／保存 |
| --- | --- | --- |
| 官方日行情、TAIEX、公司行動、停牌 | 正確價格特徵、執行與回測 | 交易日／標的／調整基礎、原始及修訂版本、停復牌與缺口。 |
| 分類法人資料 | 資金持續性與分歧 | 外陸資／投信／自營商，自行買賣／避險若可得；買、賣、淨額的單位與官方定義。 |
| 現股當沖統計 | 短線交易活躍度 | 股數／金額、分子分母口徑、首次公布與 T+1／T+2 修訂；不能將當沖占比解讀成某類法人占比。 |
| 券商／分點逐日買賣 | 集中度、次日反轉特徵 | 通道識別、買賣量／金額／價格、歷史可取得範圍、資料權限與費用；不是投資人帳戶。 |
| 融券／借券／持股結構 | 補充籌碼風險 | 定義、更新頻率、可得時間與涵蓋市場；列入後续研究，不先假定有有效預測力。 |
| 公司財報／營收／重大公告 | 公司品質與事件影響驗證 | 會計期間與實際公告時間分開，更正前後版本。 |
| 官方宏觀、可信媒體與國際事件 | 題材和個股的新資訊 | 原文／來源、使用條件、發布／可得時間、去重與影響證據。 |
| 題材 membership | 跨產業研究 | 多重歸屬、證據、相關程度、生效／失效時間與版本。 |

券商分點資料是通道彙總，證交所說明包含自營與經紀客戶的合計，因此不能用分點名稱判定資金國籍、同一投資人或確定的隔日沖意圖。可研究分點買賣反轉，僅標示描述特徵／疑似風險。[官方說明](https://bsr.twse.com.tw/bshtm/bsMenu.aspx)

櫃買中心說明當沖統計可能調整至 T+2，最終數與 T／T+1 參考值不同；資料設計必須保存當時版本。各來源的實際修訂政策仍需逐一確認，不把一個來源規則外推全部市場。[官方說明](https://www.tpex.org.tw/storage/zh-tw/web/stock/trading/intraday_stat/intraday_trading_statY.htm)

## 時間、版本與研究窗口（目標契約）

- market_date／event_date：資料描述哪個交易日或事件，不代表何時可用。
- published_at／first_available_at：來源發布及可取得時間；無法證明時標未知，不能由內文日期猜測。
- collected_at：本系統實際取得時間。缺可驗證來源可得時間時，只能保守使用有證據的時間，不把回補日反推成歷史可得日。
- revision_available_at／supersedes：每次更正何時可用及替代哪個版本；原始版本保留。
- decision_at／generated_at：策略及模型何時作判斷；最早執行不得早於必要資料可得及策略允許的下一交易時段。
- as-of 查詢：決策只讀當時可得的資料與 membership。正式可用與事後修訂結果分開儲存／查詢，避免覆寫造成洩漏。

當前 signal.data_cutoff 的 13:30 字串不代表所有盤後資料在收盤時已知，列為 R0 修正。新長期歷史研究需定義 universe、下市／停牌、來源版本、覆蓋及費用，再做有界收集；目前 collect 0–3 個月及 backfill 93 日界線不會因文件更新而放寬。

## 歷史程式驗證紀錄

原文件記載 2026-09-08 backend suite 為 54 passed、frontend production build 通過。這是當時的程式驗證，不能當作本輪或目前 checkout 的測試結果，更不是策略績效證據。
