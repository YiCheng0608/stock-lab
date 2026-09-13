# 操作手冊

現行測試入口與環境重建見 [開發入口](development-baseline/README.md)。下文具名輪次的 Temp／external 路徑屬歷史驗收記錄，附件已清理，不再作為可執行命令或依賴位置。

更新：2026-09-13，依現有 CLI、migration 原始碼、C-003/B6 隔離驗收、Round10 C010 synthetic regression／restore mechanics、Round11 C011 News JSON defaults／atomic migration regression、Round12 C012 signal artifact local foundation、Round15–17 產業／candidate membership、Round18–20 source capture／兩個有限 consumer review、Round26 TWSE action read-only classification、Round27 API startup readiness、Round28 canonical legacy instruments migration guard、Round29 canonical legacy `signal_settlements` migration guard、Round30 settlement startup UNIQUE metadata gate，以及 Round31 instruments startup UNIQUE metadata gate核對。R26 自身的 migration 與資料驗證仍只在專案外 Temp DB；但另一個使用者 preview task 的舊 API lifespan 已把正式 DB 升到 0006，故不能再泛稱正式 DB 從未升級。該外部變化不是 R26 核准的 migration、restore、分類或公司行動修復；R27–R31 也沒有再 migration／repair／restore 正式或 `.local` DB。下列一般命令仍須由操作者按實際環境與授權執行，不能因文件列出就視為已跑。未來功能與驗證路線見 [ROADMAP](ROADMAP.md)。

## 1. 工作目錄與隔離資料庫

以下後端命令皆從專案根目錄執行。先安裝可用的 Python／Node；不要把文件範例誤當本機環境已備妥。

    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install -r backend/requirements.txt

    $env:STOCK_DATA_DIR = (Join-Path $PWD '.local/data')
    $env:STOCK_DB_PATH = (Join-Path $env:STOCK_DATA_DIR 'stock.db')
    $env:STOCK_RAW_DIR = (Join-Path $env:STOCK_DATA_DIR 'raw')
    $env:PYTHONPATH = (Join-Path $PWD 'backend')

    python -m worker.cli init-db
    python -m uvicorn app.main:app --reload --port 8000

`python -m worker.cli init-db` 是明確的 schema 建立／升級動作；應先確認三個 `STOCK_*` 路徑、取得授權與 consistent backup，再只對指定隔離 DB 演練。Round27 起目前 checkout 的 API lifespan 改為 `check_database_readiness()`：它以 SQLite `mode=ro`／`query_only` 在單一 read transaction 內做一秒 busy timeout 的有限檢查，不會自動建立、migration、repair 或 stamp。缺檔會保持不存在；空檔、不可讀、版本／必要 mapped 結構不合時會以 `DatabaseReadinessError` 拒絕啟動，訊息要求核對三個路徑並明確執行 `init-db`。

「startup schema 唯讀」不等於整個服務唯讀。`app.config` import 仍會建立設定的 data／raw 目錄，API request handlers 可寫入，collect／daily／backfill／analyze／evaluate／backtest 等 worker 路徑仍可能呼叫 `init_db` 或寫資料。R27 沒有重啟使用者既有服務，已在執行的 process 可能仍載入舊版 lifespan；更新 source 本身不會替既有 process 切換行為。對 live WAL／SHM 或 concurrent writer 的 side effects 也沒有完成證據，不能把外部 controlled-copy 的 no-mutation 結果直接外推。

程式的 Alembic migration head 為 `0006_news_json_defaults`，前置為 0001_schema_v1 → 0002_instrument_exchange_key → 0003_backtest_run_metadata → 0004_product_news_themes → 0005_news_temporal_contract。這是檔案中的 revision 鏈，不能證明某個 stock.db 已升級至此。Alembic 不可用時另有相容 schema fallback，現有程式可寫第六枚 marker；fallback 不等同已由 Alembic 驗證 revision，且兩者都不是市場資料匯入工具。

C-003/B6 於 2026-09-12 當時已確認：runtime 解析正式庫為 `data/stock.db`；用 SQLite `mode=ro` 與 `query_only` 讀取時，該庫沒有 `alembic_version`，但有五筆 fallback `schema_migrations`。這是 C003/R11/R25 review 時點的歷史狀態，不能回寫成當時已在 Alembic 0005／0006。

C-003 驗收時 bundled `backend/.deps` 沒有 requirements 已宣告的 Alembic；C-003 與 C011 的真 Alembic 1.19.2 驗證均使用專案外 Temp 依賴。一般操作前應先在隔離環境確認 `alembic` 可 import／執行並記錄版本。正式 DB 的現況查詢必須使用 SQLite 唯讀連線；不要用可能初始化或升級 schema 的一般啟動命令代替唯讀查驗。

R26 開始時正式 DB baseline 為 296,054,784 bytes、SHA-256 `74a34389dbfa65429d27ea41bc9deca2a132808f10093e2ffde98665d96232d6`；輪初已知歷史狀態是沒有 `alembic_version`、有 fallback markers，不能稱原先 Alembic current 為 0001。另一個使用者 preview task `01a0994a-f42c-7f40-9aef-218d01917dab` 啟動 `.venv` Uvicorn 後，lifespan startup log 顯示執行 `base→0001→…→0006`。統籌其後只用 `mode=ro`／`query_only=1` 查得目前 `alembic_version=0006_news_json_defaults`、21 tables，查驗前後 current 檔皆為 296,366,080 bytes、SHA-256 `3a21772050b3053557c0798876cc0aa1efe024fcbdce5ab44e35e6abf12da018`。這只確認目前 head 與唯讀查驗不再改檔，不是完整 historical/schema parity、正式 migration acceptance、restore/deployment drill 或資料 repair。`.local/data/stock.db` 仍為 438,272 bytes、SHA-256 `87453d7b29954b6d506f8020b8987f321aa6749ce9bc24fbef695dd3874b8d02`。

## 1.1 B6 已 review 的隔離驗證

- C-003 當時的正式 DB 查驗前後 SHA-256 均為 `74A34389DBFA65429D27EA41BC9DECA2A132808F10093E2FFDE98665D96232D6`，size／mtime 不變；C-003 沒有執行 upgrade。這不是 R26 current fingerprint。
- SQLite backup API 建立的外部 Temp 副本與另一個 fresh DB 都以真 Alembic 升到唯一 head `0005_news_temporal_contract`；integrity check 正常、foreign key violation 為 0。
- 副本 upgrade 前後 20 個既有表（含 fallback marker 表）、共同欄位集合、622,399 筆 row count 與完整內容 fingerprint 相同；只新增 `alembic_version`。
- 隔離 API startup 與 `/api/health` 200 通過；有 Alembic 的完整 backend 為 157 passed、4486 warnings、24.34 秒、exit 0。無 Alembic 的 targeted suite 明示跳過真 Alembic 案例，不能把 skip 解讀為已驗 upgrade。
- production migrations 沒有修改；`backend/tests/test_schema.py` 現在分別驗真 Alembic 與強制 fallback。完整報告與 hash 見 [R0 §8.2](R0_IMPLEMENTATION.md#82-c-003-final-review-證據與限制)。

Round10 C010 已把 recovery mechanics 實作為自動回歸，但範圍只是一個固定、最小、六表 synthetic 0004 pre-head slice：真 Alembic 升至 0005 後用 SQLite backup API 建 consistent backup，另建並改壞故障副本，再還原到全新 Temp path；驗完整 slice schema、所有 rows、revision、PK／FK／unique、integrity 及 backup/source 不變。統籌另以不依賴測試 helper 的 SQL／SQLite 檢查得到 22／22；完整 backend 為 241 passed、4613 warnings、31.69 秒、exit 0。證據與三個資產 hash 見 [R0 §8.3](R0_IMPLEMENTATION.md#83-round10-c010-migrationrestore-regression-assets有限-reviewr0-a2-未結清)。

這不改寫 C-003 當時「restore 未實跑」的歷史，也不是正式 restore／deployment drill。migrations 仍為 forward-only，不宣稱 downgrade 通過；任何正式升級都需另行授權、當次 consistent backup、指定正式副本的 restore drill 與部署驗收。Round10 當時揭露的 `news_items.symbols_json`／`theme_ids_json` fresh schema parity gap 已由下節 C011 在明列範圍修正；不能把後續結果倒寫成 C010 當時已通過。

### 1.1.1 Round11 C011 JSON defaults migration（有限 review）

- current ORM、fresh head、0005→0006 與 explicit 0004→0005→0006 的兩個 JSON 欄位現在都有等價 SQL `[]` default；raw SQL 省略兩欄或只省略 `theme_ids_json` 會得到空陣列。
- SQLite repair 支援可安全保存的額外 index、owned trigger、字串 default literal 與 `supersedes_id` self-FK。遇 inbound FK、view、external trigger、AUTOINCREMENT、generated column、未知非空 default 等未支援形狀時，會在任何 mutation 前 fail-closed；非 SQLite 未經本批驗證。
- 真 Alembic 的 SQLite runner 會建立明確 driver transaction；若呼叫者傳入的 external `Connection` 已在 transaction 中，會在 mutation 前拒絕。repair helper 若單獨呼叫，transaction 仍由呼叫端負責。成功或失敗都須恢復原本 `PRAGMA foreign_keys` 模式。
- 主 24／24 fault 矩陣涵蓋 Alembic engine、Alembic external `Connection`、fallback 三個入口，在 fresh／old005、FK 0／1、各自 marker SQL 前／後故障時驗 schema、全部 rows、revision／markers 完整回滾與 retry；explicit 0004 有成功到 head 驗證，但不宣稱也跑完上述全部 fault 交叉。
- 成功後重跑比較 schema、research rows 與 version set；fallback 既有 `INSERT OR REPLACE schema_migrations` 可能更新 operational `applied_at`，故不能把該時間戳寫成每次完全不變。Round10 測試現在固定驗 005／current-metadata comparison；C011 inline fixed DDL 只是小型 old005-like slice，真正 old full 005 Temp copy 由統籌獨立驗證補證。
- 統籌完整 backend 259 passed、4625 warnings、14.12 秒，獨立檢查 73／73、atomic 24／24；在 Round11 驗收當時，正式 DB 沒有 `alembic_version`、只有五筆舊 fallback markers，C011 沒有執行 0006。其後 R26 觀察到的外部 preview startup 變化不回寫這項歷史證據。完整邊界見 [R0 §8.4](R0_IMPLEMENTATION.md#84-round11-c011json-server-default-parity-與-atomic-migration-回歸有限-review)。

### 1.1.2 Round27 API startup readiness（有限 review）

readiness 接受的版本狀態只有兩族：Alembic table 必須恰有唯一 current head `0006_news_json_defaults`，且 fallback table 可不存在，或包含從 0001 開始、長度 1–6 的非空完整已知 prefix；沒有 Alembic table 時，fallback 必須恰有六枚 revisions。Alembic stale／unknown／multiple／malformed 不能由 fallback 覆蓋；marker view、空表、gap、duplicate、null／非字串或 unknown marker 均拒絕。

有限 schema gate 只核 19 個 mapped objects 都是 real tables、具體 mapped column names、ordered primary key、必要 unique column keys、foreign-key definitions，以及 `news_items.symbols_json`／`theme_ids_json` 的 SQL 空陣列 literal defaults。唯一 partial-unique 相容例外是既有 `ix_ingestion_runs_request_key`：只能是 `ingestion_runs(request_key)` 且完整保存的 `CREATE UNIQUE INDEX` DDL predicate 恰為 `request_key IS NOT NULL`；其他 partial index、較窄 subset 或註解／字串偽裝都不接受。成功沒有 public status payload，函式回 `None`；失敗是含說明文字的 `DatabaseReadinessError`。

這不是完整 schema 或資料庫健康檢查：不保證 type、nullability、collation、FK actions、CHECK、額外 schema 或完整 SQL-text parity，也不掃歷史 row、資料 FK、`quick_check`／`integrity_check` 或深層 page corruption。額外且不破壞必要 identity 的 custom schema 可存在。需要更深驗證時仍應使用 consistent external copy，不能讓 startup gate 取代 migration／restore／deployment review。

統籌獨立 startup review 為 39 cases／41 subprocess calls、exit 0；其中兩個 subprocess 明確建立 fresh Alembic／fallback seed DB，其餘 lifespan／health cases 均裝設 migration／repair／`create_all` bombs，並逐案比對 SHA／size／mtime 或缺檔狀態。完整 backend 為 1,011 passed、1 個既有 Windows symlink privilege skip、9,089 warnings，pytest 74.68 秒／subprocess 80.203 秒、exit 0；133 個 protected paths unchanged。詳細 preservation、歷史 replay、freeze 與限制見 [R0 §8.6](R0_IMPLEMENTATION.md#86-round27-api-startup-readiness有限-review)。所有測試 DB 都在專案外 Temp；沒有前端 build／UI 驗收，也沒有正式 migration／repair／restore。

### 1.1.3 Round28 canonical legacy instruments migration guard（有限 review）

`python -m worker.cli init-db` 仍是明確 schema mutation；API startup不會代跑。Round28只接受 SQLite legacy instruments `UNIQUE(market, symbol) → UNIQUE(exchange, symbol)` 的 finite guard、preservation與rollback邊界：統籌 final `206+16=222` independent cases及 full backend `1,397 passed／1 skipped／12,029 warnings／exit 0`。正式或 `.local` DB沒有因本批被migration、restore或repair；操作前仍須對具名外部 consistent copy演練並保存before fingerprint與restore路徑。

允許自動 rebuild 的只有已知 canonical legacy column definitions／constraints／indexes。現行 inbound FK allowlist也不是泛用：只接受九個具名 application child各自的單欄 `instrument_id → instruments.id`，且必須是 simple `ON UPDATE NO ACTION`／`ON DELETE NO ACTION`、`MATCH NONE`、non-deferrable。recognized current ordered full identity會 no-rebuild並保留受測代表性 extra objects，但這不是 full current schema validation。下列情況會在 destructive DDL及 revision／fallback marker寫入前拒絕：

- legacy＋current full identity同時存在、兩者都不存在，或identity只由partial／expression／reversed unique提供；
- `(exchange, symbol)` duplicate，或canonical legacy必要欄／definition／PK不符；
- unsupported extra legacy column／index／trigger／view／default／CHECK／self、outbound或未知 inbound FK、generated／hidden column、table option；
- main schema任何以`instruments__v1_rebuild`開頭的occupied object、TEMP `instruments`或TEMP scratch shadow；
- `alembic_version`或`schema_migrations`宣稱已知0002–0006 revision，但`instruments`仍是legacy或不存在；
- 既有`foreign_key_check`違規或其他preflight／health gate不符。

遇到這些錯誤，不要手動刪scratch、補marker或反覆執行以嘗試自動salvage。本批沒有定義repair；保留DB與error，回到原consistent backup／新外部副本做人工診斷。呼叫前已缺parent並留scratch／old artifact的保存殘局會原樣fail closed。這與修後migration從完整fixture注入fault不同：96個fault cases皆驗failure後完整schema／typed rows回到exact before state，移除injector後在同一DB retry成功。

SQLite Alembic runner在transaction外記錄並管理原FK 0／1，接著以單一explicit transaction包住revision chain、marker與pre／post `integrity_check`／`foreign_key_check`；fallback以named savepoint提供相同成功邊界。普通success／failure／no-op後恢復原FK狀態。直接提供Alembic external `Connection`時必須是inactive；已有active transaction會在mutation前拒絕。不要自行用`PRAGMA foreign_keys=OFF`繞過guard。若刻意使FK restore本身失敗，只保證原migration exception仍是主錯誤、restore exception成為cause，不保證該注入案的FK已恢復或connection可重用。

作者final source的run05只是selected subset `249 passed／1,191 warnings／51.38s／exit0`；run04的`464 passed`發生在最後known-marker patch前，兩者都不是作者final full 386重跑。最終386個新parameterized cases由統籌full backend完整走過；final輸出只列1 skipped而未列reason，不把R27另有記錄的Windows symlink限制冒充本輪重驗。News test只改 `_old_005_engine` 的兩個instruments SQL fixture expressions以提供current identity prerequisite；News production、schema／rows／self-FK／defaults／trigger／index／fault assertions及R11歷史驗收不變。

完整source freeze、failure history、matrix與guards見 [R0 §8.7](R0_IMPLEMENTATION.md#87-round28-c028canonical-legacy-instruments-identity-rebuild-rollbackfail-closed有限-review)。這項有限保全不代表任意custom或所有historical schema可自動保存，也不取代consistent backup、restore drill或正式deployment review；non-SQLite、attached schema、真crash／disk-full／concurrent writer、資料truth／PIT都未驗。`signal_settlements`具名缺口已由下一節分開驗收，不能倒寫成Round28成果。

### 1.1.4 Round29 canonical legacy `signal_settlements` migration guard（有限 review）

`python -m worker.cli init-db`仍是明確schema mutation；API startup不會代跑。Round29只接受SQLite legacy settlement從simple full `UNIQUE(signal_id)`轉成ordered full `UNIQUE(signal_id, horizon)`的finite guard、preservation與rollback邊界：統籌final `408+14=422` independent cases、主矩陣84 fault exact rollback／same-DB retry及full backend `1,837 passed／1 skipped／12,414 warnings／exit 0`。正式或`.local` DB沒有因本批被migration、restore或repair；操作前仍須在具名external consistent copy演練，保存before fingerprint與restore路徑。

允許自動rebuild的只有unmarked exact known 9-column legacy或known 14-column additive legacy，且必須有simple ordinary BINARY `UNIQUE(signal_id)`及exact sole `signal_id → signals.id` FK。legacy nonunique index可以完全缺席；若存在，只接受兩個known ordinary index shapes，rebuild後會建立這兩個known indexes。missing horizon與nullable legacy row的`NULL horizon`都會刻意寫成integer 20；missing execution欄位為NULL、missing quality為`complete`，其他known typed payload與id保留。這是已接受的migration normalization；若操作需求不能接受NULL→20，應停止而不是直接執行。

recognized current需要14個known columns、id PK、essential NOT NULL／defaults、exact ordered pair identity、exact outbound FK及基本row checks，然後no-rebuild。受測extra current objects、non-conflicting inbound FK與quoted default會保留，但這不是任意CHECK／trigger／extra schema、secondary nonunique index existence或完整row audit。legacy state的任何inbound FK都拒絕；不要把current no-rebuild的保留行為外推到destructive legacy rebuild。

下列情況會在destructive DDL及revision／fallback marker成功邊界前拒絕：

- unsupported legacy extra column／default／CHECK／index／trigger／view／generated column／table option；
- legacy inbound FK、noncanonical outbound／self FK，或`signals` parent缺失／不合；
- mixed、neither、partial、expression、reversed或duplicate identity，以及noninteger horizon；
- main schema任何settlement scratch prefix、TEMP `signal_settlements`或TEMP scratch shadow；
- 任一marker family宣稱known 0001–0006，但settlement仍absent、legacy或invalid。

遇到拒絕時，不要手動刪scratch、補marker或反覆執行以嘗試salvage。本批沒有repair policy；保存DB與error，在新external copy人工診斷。helper不commit、rollback、切FK或寫markers；transaction由fallback SAVEPOINT或Alembic explicit transaction擁有，postflight在commit前且marker仍在同一transaction內。external `Connection`必須inactive，已有active transaction會在mutation前拒絕。

R29沒有修改R27 `check_database_readiness()`。統籌只在一份保存的external Phase A mixed-identity DB觀察到readiness回`None`，但memory copy插入第二個不同horizon時仍被`UNIQUE(signal_id)`阻擋；來源430,080 bytes、SHA-256 `f06e4c48d24e98599d607f02c33d7b7b914b7aba10b458ced7cefae9b022f291`且未變。這是下一輪候選，不表示正式DB已知有此shape，也不能用startup成功取代明確`init-db`前的consistent-copy migration review。

作者targeted03的final 440 new settlement tests含96 fault與144 false-marker cases；作者full01因外部launcher未把`PYTHONPATH`傳給child subprocess而exit 1，修正launcher後targeted source-runtime通過，repository source未因而改動。統籌final full才是本輪complete backend證據；skip明列為Windows symlink privilege unavailable，158 protected paths unchanged。完整source freeze、matrix、failure history與邊界見 [R0 §8.8](R0_IMPLEMENTATION.md#88-round29-c029canonical-legacy-signal_settlements-identity-rebuild-rollbackfail-closed有限-review)。non-SQLite、attached schema、crash／disk-full／commit failure／concurrency、正式restore／deployment與資料truth／PIT仍未驗。

### 1.1.5 Round30 API startup `signal_settlements` UNIQUE metadata gate（有限 review）

R29 上述「沒有修改 R27 readiness」是歷史事實；Round30 才補上 startup settlement UNIQUE gate。現在 `check_database_readiness()` 除既有 mapped schema 檢查外，還要求至少一個 ordered full ordinary BINARY ASC `UNIQUE(signal_id, horizon)`。所有 UNIQUE 的 key parts 只要含 `signal_id` 或 `horizon`，都必須是相同 canonical pair；signal-only、horizon-only、reversed、superset／mixed、target partial、DESC 或 non-BINARY 會 fail closed。重複 canonical pair、unrelated named-column UNIQUE 與 nonunique extra indexes可存在。ASC／reversed 的拒絕是相容政策，不表示其 INSERT 一定失敗。

此 gate 只查 `index_list`／`index_xinfo` metadata 的 key parts，不解析 partial predicate：`UNIQUE(source) WHERE horizon=20` 或 `UNIQUE(id) WHERE signal_id>0` 仍按 unrelated key 接受。任何 UNIQUE expression 因 key 歸屬無法有限確認而保守拒絕。任意 CHECK、trigger、unrelated UNIQUE 的實際語意不在 audit 內，因此 startup 成功不保證任意 INSERT 成功；需要確認某個產品寫入時，仍須在具名 external copy 依真實 transaction／FK／trigger／constraint 路徑另驗，不能以 readiness 取代。

最終統籌 external matrix 為 87 個 populated DB、261 個 direct／repeat／actual lifespan entries 加 261 個 memory INSERT probes，mismatches `[]`、exit 0；逐案以 `mode=ro`、`query_only`、單一 `BEGIN` 執行，readonly trace／authorizer沒有 business-row read，且 `migrations.upgrade_database`、`_fallback_upgrade`、`Base.metadata.create_all`及settlement preflight／rebuild bombs均未觸發。完整 backend 為 `1,963 passed／1 skipped／12,414 warnings`，pytest 226.12 秒、process 229.344 秒、exit 0；唯一 skip 是 `backend/tests/test_source_runtime.py:238: symlink privilege unavailable`，159 個 guards 的 SHA／size／exact mtime 均未變。正式 DB 只受既有 fingerprint 守衛且未被本批開啟；沒有 migration／repair／restore、service、install、Git mutation、deployment、帳戶或交易動作。

完整 source scope、126 個新增測試、matrix 與限制見 [R0 §8.9](R0_IMPLEMENTATION.md#89-round30-c030api-startup-signal_settlements-unique-metadata-gate有限-review)。non-SQLite、attached schema、任意 historical／custom schema、實體 crash／disk-full／concurrency、資料 truth／PIT、running service reload與 R0 整體仍未完成。下一個候選只是一個 external instruments synthetic probe：current pair 加 legacy `UNIQUE(market, symbol)` 可能通過 readiness，卻阻擋同 symbol 的第二個 exchange；它不是 Round30 acceptance，也沒有矩陣或正式 DB 證據。

### 1.1.6 Round31 API startup `instruments` UNIQUE metadata gate（有限 review）

Round30 上述 instruments probe是歷史候選；Round31 才新增 startup instruments gate。`market` 仍是較廣分類，canonical identity是ordered `(exchange,symbol)`；但現行 writer會明確讀寫 `market`／`exchange`／`symbol`，所以三欄都必須是 `table_xinfo.hidden=0`，作非 hidden／generated 的mapped欄位相容檢查，不代表完整writability。startup另要求至少一個full／non-partial、ASC／BINARY canonical UNIQUE，且所有key parts觸及三欄的UNIQUE都必須同形；single、legacy `(market,symbol)`、reversed、superset／mixed、partial、target DESC／non-BINARY及任意UNIQUE expression都fail closed。

這是有限 descriptor policy。DESC／reversed／superset等部分拒絕形狀未必會妨礙受測INSERT；`index_xinfo.cid>=0`也只證named key，canonical欄位的nongenerated性另由`table_xinfo`證明。key-unrelated named-column UNIQUE仍可包含partial／collation／DESC或generated extra；gate不解析predicate／generated dependency，所以它仍可能引用symbol並擋寫。任意CHECK／trigger、nonunique index、其他欄位type／nullability／default與任意INSERT語意都不在audit。

統籌matrix以123個populated external DB走369個direct／repeat／actual lifespan entries及492個memory probes，mismatches `[]`、exit 0；`mode=ro`、`query_only`、單一`BEGIN`與authorizer無business-row read均通過，具名migration／helper／`create_all`禁止呼叫均未觸發。final full backend為`2,161 passed／1 skipped／12,414 warnings`，pytest 273.99秒、process 277.218秒、exit 0；唯一skip是`backend/tests/test_source_runtime.py:238: symlink privilege unavailable`，160 guards unchanged。synthetic seed與backend migration tests有執行，但正式／`.local` DB未被本批SQLite-open或mutation；目前checkout也未重啟service。

完整scope與限制見 [R0 §8.10](R0_IMPLEMENTATION.md#810-round31-c031api-startup-instruments-unique-metadata-gate有限-review)。此startup policy可比R28 recognized-current no-rebuild判定更窄；`worker.cli init-db`不會自動修復或移除所有被拒custom shape。正式migration／restore／deployment、non-SQLite、attached／任意historical或custom schema、crash／concurrency、資料truth／PIT與R0整體仍未完成；輪末索引尚由I070在freeze後複核。

## 1.2 C-004 獨立 artifact store（有限儲存段落已 review）

`backend/app/artifact_store.py` 現有 `ArtifactStore`，store schema version 為 1。它是明確 opt-in 的獨立 SQLite store，不是 `STOCK_DB_PATH` 所指的 legacy database；schema 1 不是 Alembic revision，也不改程式 head `0006_news_json_defaults`、fallback markers、legacy `Base.metadata`、API lifespan 或 `worker.cli init-db`。模組沒有預設 DB 路徑，也沒有 CLI；呼叫端即使自行使用環境變數，仍須把路徑明確傳給 `ArtifactStore(path)`。

本地驗證先在專案外建立全新具名 Temp 路徑；下列 `R04_ARTIFACT_DB_PATH` 只是操作端變數，store 不會自動讀取：

```powershell
$artifactTempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("stock-r04-artifact-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $artifactTempRoot | Out-Null
$env:R04_ARTIFACT_DB_PATH = Join-Path $artifactTempRoot "artifacts.sqlite"
$env:PYTHONPATH = Join-Path $PWD "backend"
```

接線端的最小 Python 形狀如下；`artifact` 必須先由 ATR 純核心建立，其餘 evidence／digest 也都由呼叫端明確提供。這不是可自行抓取或驗證官方資料的完整腳本：

```python
from os import environ
from pathlib import Path

from app.artifact_store import ArtifactStore

with ArtifactStore(Path(environ["R04_ARTIFACT_DB_PATH"])) as store:
    saved = store.save_atr_artifact(  # alias: store.save(...)
        {"exchange": "TWSE", "symbol": "2330", "legacy_reference": legacy_reference},
        artifact.observations[-1].trading_date,
        artifact,
        snapshot_hash=snapshot_hash,
        implementation_digest=implementation_digest,
        dependency_manifest=dependency_manifest,
        instrument_evidence=instrument_evidence,
        source_evidence=source_evidence,
        calendar_evidence=calendar_evidence,
        halt_evidence=halt_evidence,
        previous_close_evidence=previous_close_evidence,
        calculation_config=calculation_config,
        attempt_id=attempt_id,
        run_id=run_id,
    )

    exact = store.get_atr(
        saved.instrument,
        saved.market_date,
        feature_version=saved.feature_version,
        snapshot_id=saved.snapshot_id,
        snapshot_hash=saved.snapshot_hash,
        decision_at=saved.decision_at,
    )
    exact_by_key = store.get_by_key(saved.artifact_key)
```

`market_date` 固定等於完整 `ATRArtifact` 最後一筆 observation date；`save_atr_artifact`／`save` 的一次呼叫，以單一交易保存該 artifact 的 parent、全部 observations、dependencies 與 attempt relation，任一列失敗就整次回滾。這不代表有通用多-artifact batch API，也不代表多次 `save` 共用同一交易。相同 identity 與 payload 重試保留首次 `generated_at` 並另記 attempt；collision fail-closed。busy lock 只等待有界時間後回報可重試錯誤。

一般 reader 必須精確給 exchange＋symbol、terminal market date、feature version、snapshot id/hash 與 aware as-of；它不會選 latest。若 config、implementation 或 dependency digest 不同而使這些 selector 仍對應多筆，`get_atr` 會以 ambiguity fail-closed，呼叫端須使用已知 `artifact_key` 的 `get_by_key`。aware `+08:00` 等輸入會正規化為 UTC；naive timestamp 拒絕。

跨 SQLite 檔沒有 legacy instrument FK。canonical instrument key 目前只有 normalized exchange＋symbol；`market`／`instrument_type` 不是強制 identity 欄位。nullable `legacy_reference` 只是 link。`instrument_evidence` 必填 source ref、snapshot id/hash 與 `validation_status=caller_supplied_only`，其他 source／calendar／halt／previous-close evidence 及 calculation config 也須符合最低結構；這只能證明 metadata 被結構驗證、canonicalized 並保存，**不能**證明來源官方且真實、availability 一定早於 decision、manifest 完整涵蓋實際輸入，或 market/type 已由外部主檔核實。完整 source truth 與 PIT gate 仍屬 B3-wire／B5 後續。

既存空檔、非 artifact SQLite 或未知 store version 應在不改原 schema／內容下拒絕；直接一般 SQL 的 parent／children／attempt UPDATE、DELETE 與 `INSERT OR REPLACE` 由 schema triggers 阻擋，但這不是對可任意修改 schema、停用或替換 trigger 的惡意管理者防護。artifact key／identity 由 SQLite unique 約束，payload SHA-256 則由 Python 計算及比對；schema 1 沒有 DB 內 SHA 重算或單獨 payload-hash unique。不得把測試 path 指向 `data/stock.db` 或其他既存研究庫。

2026-09-12 統籌 final review 使用 bundled Python 3.12.14，`PYTHONPATH=C:/Users/YiCheng/AppData/Local/Temp/stock-r03-c003-alembic-deps-20260911-170100;backend;backend/.deps`，執行 `python -m pytest backend -q --disable-warnings`：176 passed、4486 warnings、26.84 秒、exit 0；真 Alembic 1.19.2 可用，`conftest` 將 DB／raw 指到專案外 Temp。ATR＋store targeted 為 47 passed、exit 0。final SHA-256：`backend/app/artifact_store.py` 為 `40CEC8F0304E26456EC41C9C23DE03AE7ABE0F1B1145068508450430435DAC66`，`backend/tests/test_artifact_store.py` 為 `B519CF4FED6B45D46FAB8EA1590633F443630C9B7190ADFD7FFE3DE1D745CC7A`。

小修前獨立 SQLite 報告 `C:/Users/YiCheng/AppData/Local/Temp/stock-r04-coordinator-5hv5_brl/review.json`（store hash `7593836d…`）驗證 ownership 拒絕、UTC 等價 retry、collision 四表不變、不可變 SQL、含 `#` 路徑重開與 ThreadPool 雙連線相同 identity。final source 報告 `C:/Users/YiCheng/AppData/Local/Temp/stock-r04-final-review-c2_iri8g/review.json` 驗證缺 null reason、負 TR／ATR 拒絕且 parent row count 為 0，合法 ATR=5 可保存；它沒有獨立 assert 四表全空或 persisted zero，後者不能寫成已獨立驗證。naive attempt 在 child rows 插入後仍四表回滾與未知 store version 不改 bytes／mtime，則由 final 程式測試覆蓋。

baseline `C:/Users/YiCheng/AppData/Local/Temp/stock-r04-baseline-4fb9f0579d6141d295c3c0bcc9bc9e57.json` 顯示 `atr.py`、`models.py`、`db.py`、`migrations.py`、`api.py`、`worker/pipeline.py`、正式 `data/stock.db` 與 `.local/data/stock.db` 的 hash／size／mtime 全不變。C-004 當時尚待的同日唯讀 legacy＋Wilder v2＋兩 as-of 比較與完整 provenance 缺漏政策，已由下節 C-006 在相同有限 storage scope 補齊。worker、API、正式來源 truth 與 PIT execution gate 仍分屬 B3-wire／B5-time，尚未接線；所以不能解讀為 `stock.db` 已 migration、完整 B3／B2／B7 或 R0 已完成。

## 1.3 C-006 strict provenance 與本地比較（有限 B3-persist 已 review）

Round 06 已通過 [R0 §4.9](R0_IMPLEMENTATION.md#49-c-006-provenancecompatibility-final-review-與完成邊界) 的有限 review。store schema 仍為 1；strict contract 固定是 name=`atr-provenance`、version=2、id=`atr-provenance/v2`、mode=`caller_provided_only`，instrument adapter status 為 `caller_supplied_only`。既有 C-004 schema 1 key、seal、payload、首次 generated time 與 immutable rows 原樣保留；普通 writer／reader 仍維持舊 minimal 行為，ordinary writer 即使保存 caller 提供的 strict-like marker 也不代表已驗 strict。strict reader 會重驗完整 projection 並拒絕矛盾／缺漏，不能靠補 metadata 或 marker 升格。

strict save 使用 `ArtifactStore.save_atr_artifact_strict(..., provenance=...)`，讀取使用 `get_strict_by_key`／`read_strict` 或 `get_strict_atr`。provenance 固定頂層是 contract、feature、instrument、source、algorithm、basis、calendar、sessions、halts、previous_close、company_actions；完整 shape 可參考測試資產 `backend/tests/strict_artifact_fixture.py`，但 fixture 值不能搬進正式資料。操作端須顯式提供 snapshot＋逐列 ordered row refs/status/basis/aware availability、instrument mapping、method/config/implementation、共同 basis、calendar/session/halt window/status、所有實際選用 previous close 的 current/predecessor refs，以及完整 corporate-action manifest/digest/coverage/source/aware availability。必要結構缺失時拒寫；unknown/unavailable 必須帶 machine reason，且只能配對應 fail-closed null，不能保存 non-null ATR 作為已驗有效結果。

strict writer 在同一 transaction 內、attempt 寫入後與 COMMIT 前執行 strict re-read；失敗會回滾 parent、observations、dependencies、attempts 四表。manifest、basis 與 config digest 由收到的 canonical 結構重算；外部 snapshot／implementation 的 SHA-256 或 SHA-512 只驗 algorithm、hex 長度與 shape，不代表 store 已從原始 bytes 核真。這一層始終只驗 caller-provided 結構與自洽性，不驗官方 truth 或 PIT。

本地 comparison 使用 `ArtifactComparisonReader(legacy_path, artifact_path).compare(...)`，selector 型別是 `LegacyFeatureSelector` 與 `ArtifactSelector`。它必須顯式 opt in：指定 legacy stable-checkpoint SQLite 路徑與 exact exchange＋symbol/date/row，另指定 artifact store 路徑；store operand 可用 exact artifact key，或完整 feature name/version＋snapshot id/hash＋UTC exact decision-at。以 key 取回後仍核對 instrument/date 及任何另給 selector；禁止 latest／`<= as_of`／第一筆 fallback，零筆、多筆、cross-identity、legacy mapping 不唯一或 mismatch 均拒絕。

兩個 reader 都以 URI `mode=ro` 與 `PRAGMA query_only=ON` 開啟，支援路徑中的 `#`；缺檔、live WAL/SHM/journal sidecar、讀取期間檔案變更或 ownership/schema 不符都拒絕，所以應先用 SQLite backup/checkpoint 取得專案外 stable file。legacy selector 的 snapshot/version 是 caller 聲明，reader 另核對檔案實際 SHA-256；驗證前後 hash、size、mtime、schema、row count 與既有欄位 fingerprint 必須不變。一般驗證不得把路徑指向 `data/stock.db` 或 `.local` DB；若另有明確授權只讀正式庫，也仍要先依 B6 規則，不應用 comparison 當 migration 或 startup 工具。

比較輸出須分列同日 legacy、Wilder v2 as-of A、Wilder v2 as-of B 的 value/null、reason、version、snapshot、basis、decision-at 與 exact ref/key，並對三個 pair 各自輸出 comparability/reasons/delta。只有該 pair 的完整 signature 相容且兩值非 null 才可產生 delta；basis/snapshot/version/implementation 不同或值為 null 時，該 pair 必須標 `incomparable`、machine reason 且 delta=null。legacy row 沒有持久化的 algorithm/as-of/basis provenance，所以即使 caller 聲明吻合，legacy-vs-new 仍固定不可比；legacy 缺漏不反向阻塞證據完整的 v2 A-vs-B。這個本地比較不寫回 DB，也不是 worker/API 接線、官方 source truth、PIT execution gate 或 B7 paired replay。

統籌 final backend 為 200 passed、4592 warnings、25.72 秒、exit 0；獨立報告位於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r06-final-review-dg6tjhm9/review.json`，保護檔報告位於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r06-coordinator-p5raawt4/protected-review.json`。這輪沒有前端變更，也未重跑 UI/build；上述完成狀態只屬離線 B3-persist，不含 B3-wire、B5-time、官方來源或 B7。

## 1.4 Round07 `time-evidence/v1` 本地 store（有限 foundation 已 review）

`TimeEvidence.from_mapping(mapping)` 建立 strict `time-evidence/v1`；`to_dict()` 回傳四類 identity、revision／supersedes、各 role object，以及 `caller_provided_only=true`、`availability_truth=not_asserted`。七個必要 role 是 `published_at`、`first_available_at`、`collected_at`、`revision_available_at`、`decision_at`、`generated_at`、`earliest_execution_at`，另至少明示 `market_date`、`event_date`、`instant`、`event_at` 其中一個 anchor。每個 role 都要有 status／precision／value／source／evidence／ref；unknown／unavailable 另帶 reason。known datetime 必須含 offset 並 canonicalize 為 UTC `+00:00`，date-only 只保存 date，不補午夜。

`source_identity` 是 caller 選定的 stable lineage key；role `source` 是該時間證據的提供者，可以不同。兩層都必須明示且 alias 不矛盾，但本 store 不查官方准入、內容真實或同源關係。`legacy_safe(mapping)` 及 aliases 深拷貝 legacy 值，naive datetime 只轉成不加 timezone 的原 ISO text；只把合法 `signal_date` 投影為 date，`data_cutoff`、`created_at`、`earliest_execution_date` 不升格成 availability／decision instant。

`TimeEvidenceStore(explicit_path)` 沒有預設 DB，runtime 會拒絕正式 `data/stock.db`、專案 `.local`、既有空 DB 與 foreign DB。本輪操作仍只使用專案外 Temp DB。`append(...)` 以 version＋subject＋source＋revision id 作 stable identity，回傳 `created` 或 `idempotent_replay`；相同 identity 改 snapshot／payload 為 collision。每 lineage 只允許一個 root；只有 root 的 `revision_available_at` 可為 not-applicable＋reason，revision 可為 known 或 unknown／unavailable＋reason。revision 另列 append＋同 lineage supersedes；單次寫入、關係與 commit 前 revalidation 同一 transaction，失敗全 rollback，舊列另有 update／delete／replace triggers。reader 會逐層核對 ancestor 存在並重驗 row seal。

讀取入口為 `read(evidence_key)`／`read_exact`、`read_revision(subject_identity, source_identity, revision_id, version=..., snapshot_identity=...)` 及 `history(subject_identity, source_identity, version=..., snapshot_identity=...)`；都是明確 selector，沒有 latest／最大時間／`<= as_of` fallback。`export_json(output_path, subject_identity, source_identity, ...)` 以同目錄 temporary file＋hard link 做 atomic no-clobber，拒絕既存 target、active SQLite store 與受保護路徑，輸出完整 records／digests。

統籌 final 完整 backend：215 passed、4592 warnings、24.03 秒、exit 0；作者 final targeted：15 passed、0.32 秒。獨立 22 項檢查報告在 `C:/Users/YiCheng/AppData/Local/Temp/stock-r07-final-review-80ea2c0ab3bd4f9ea7f4eab4187a76aa/review.json`；15 個保護目標報告在同目錄 `protected-review.json`，全部 hash／size／mtime 不變。

final SHA-256：`time_evidence.py`=`799D9B9BD51C284321059AC908AB1079A2E0D12E875861E0FA9CA4B54E4245E7`、`time_evidence_store.py`=`A454FA7A354DDE4E65A6F17D85188414A9930A6B3D4E1846E72FC6A547E92FC4`、`test_time_evidence.py`=`5CFD4AD8160B207ACDD850BCA3BB37087F594F7A0B03BAF90BFDA6775D4E4067`、`test_time_evidence_store.py`=`9FFF228814CAE8708D33B00C51369C6E68B3812D14D93FB49CF53DA51DE717EE`。

這只證明 caller-provided 的 B5a 本地核心／store／JSON export；不接 API、worker、News、UI 或排程，不執行 B5b PIT gate，也不證明官方 availability truth。本輪沒有前端變更或 frontend build／UI 驗收，不能把 local helper/export 當成產品輸出已完成。

## 1.5 Round08 `product-time/v1` 產品 read-time 輸出（有限 review）

既有 News、signal、action、stock、dashboard 與 tracking API 現在回傳 `product_time.version=product-time/v1` 與獨立 `response_generated_at`。這是 `backend/app/product_time.py` 對已存在欄位的純 read-time projection，不讀 C007 `TimeEvidenceStore`、不寫 DB，也不採信 `Event.details`、`rule_evidence` 等任意 JSON 自報 marker。`availability_truth=not_asserted` 固定提醒操作端：角色結構完整不等於官方來源、歷史 availability 或 PIT 已驗。

操作與消費端必須遵守：

- 只有 `status=known` 且 `precision=date|instant` 的 role 可顯示為已知；instant 還須是合法含 offset 值，正規化 UTC 後才以 Asia/Taipei 顯示。naive、missing、非法值、不可信 News basis／precision 與 conflict 使用 null＋machine reason，不自行補 UTC、台北時區、午夜或 13:30。
- `market_date`／`event_date`／`earliest_execution_date` 是日曆日期；legacy `signal_date`、`data_cutoff`、naive `created_at` 與 action `generated_at` 保留相容稽核值，但不建立 decision／availability／historical generated／execution instant。真正 `earliest_execution_at` 仍是 unknown。
- `response_generated_at` 是本次 API 組裝時間；同一 signal/news 在 compact、detail、nested response 的角色 projection 應相同，但不同 request 的 response time 可以不同。
- News 的 `collected_at` 是獨立系統收錄時間，不代表 `first_available_at`；action legacy 區的 ingestion run `finished_at` 也不得升格成資料 `collected_at`。News 項目不套用規則最早執行日。
- 前端若已有 `product_time` 且 role unknown，顯示「待核實」，不得 fallback 舊日期；只有完全沒有新 contract 的 legacy response 才可安全格式化合法 date fallback。收錄時間技術區也走相同 formatter。

統籌 final 使用 bundled Python 3.12.14＋外部真 Alembic 1.19.2，`python -m pytest backend -q --disable-warnings` 為 221 passed、4603 warnings、24.55 秒、exit 0。四個 frontend self-test、`presentation` 在 UTC／America/Los_Angeles、`tsc -b` 與 Vite 82-module production build／1.08 秒均通過。報告集中在 `C:/Users/YiCheng/AppData/Local/Temp/stock-r08-coordinator-ui/final-review.json`；18-response comparison 排除本次動態 `generated_at`／`response_generated_at` 後沒有 legacy 差異，17-entry query counts、8 組同 subject projection、16 個時間案例與 15 個 protected targets 皆列在該報告或同目錄附件。統籌 fixture 的 tracking detail 有 signal 而 evaluation rows 為空；非空 tracking rows 由作者 integration test 與 final full suite 覆蓋。CUA 只觀察隔離 fixture 的可見文字／值，不是像素 layout、technical details 展開或真市場證據；其 backend 啟動早於 final compact-news 欄位補漏，該欄位另由 final API comparison 覆蓋。測試服務已停止。

final changed-source SHA-256：`product_time.py=B47D6B6D…A02F5D`、`api.py=A361AC98…9613C4`、`decision.py=BC50F327…5D389D7`、`test_product_time.py=A0EA534C…368B14`、`test_product.py=6E0464D1…072EAA`、`App.tsx=4FFDA068…A5BC8`、`presentation.ts=E9A0539A…B25CA8`、`types.ts=78B753ED…EA964`、`presentation.test.ts=358A6603…E0AB2D`。報告另列未改的 `test_api.py=A3340FB0…7CD180`；它不是 changed source。C007、ATR/artifact、model/news/schema/worker 與正式 `data/stock.db`、`.local/data/stock.db` 共 15 個保護目標的 hash／size／mtime 不變。

這一節只結清 B5a 的產品 read-time projection。若要讓產品或 worker 使用 C007 strict evidence，仍須另做明確 persistence linkage、來源准入／availability truth 與 B5b as-of/PIT gate；不能靠本投影把 unknown 變 known，也不能把它當成 B3-wire、B7 paired replay、正式 migration 或自動交易授權。

## 1.6 Round09 source registry 唯讀檢查（有限 foundation 已 review）

`worker.source_registry` 是獨立 standard-library foundation；import、validate、inspect 不發 HTTP、不載入 app config、不開 DB，也不接既有 collector。CLI 必須顯式給 `--manifest`。只有外部同時提供已 review 的 `registry_version` 與 canonical digest，validation 才可回 `verification=pinned`；不可從待驗 manifest 自己讀出版本／digest 後再聲稱外部 pin 已通過。

在根目錄設定可用 Python 與 `PYTHONPATH` 後，以 release／統籌 review 紀錄中的外部值執行：

    $env:PYTHONPATH = (Join-Path $PWD 'backend')
    $registryPath = (Join-Path $PWD 'backend/worker/source_registry.json')
    $expectedRegistryVersion = 'r1-a1-c009-2026-09-12.1'
    $expectedRegistryDigest = 'sha256:eb6c290d7716300c4117bb2cdc61a66cbf8d62e344870928933b44b77461f87b'
    python -m worker.source_registry validate `
      --manifest $registryPath `
      --expected-registry-version $expectedRegistryVersion `
      --expected-digest $expectedRegistryDigest

逐用途 inspect 也必須沿用相同 pins；不能只檢查一個用途後外推其餘用途：

    foreach ($purpose in 'local_fetch','raw_store','summarize','historical_pit') {
      python -m worker.source_registry inspect `
        --manifest $registryPath `
        --profile free_public_local `
        --purpose $purpose `
        --expected-registry-version $expectedRegistryVersion `
        --expected-digest $expectedRegistryDigest
    }

輸出 `allow` 只表示該 policy profile 的 eligibility；Round09 當時沒有 executor 自動驗證 `bounded_requests`、`attribute_source`、`preserve_source_integrity` 等條件。Round18 已另增 §1.6.1 的 standalone capture executor，但它不會改變其他呼叫端或 legacy collector。`restricted`／`unsupported` 必須連同 reasons 保留，不得把 unknown 改成禁止，也不得改讀別的用途繞過。`historical_pit` 在首批四來源均為 unsupported，不能拿當日 snapshot、HTTP 200 或 endpoint 名稱中的 `history` 做 replay。完整證據與用途矩陣見 [SOURCE_REGISTRY](SOURCE_REGISTRY.md)。

Round09 final：外部 pin validate 為 `valid=true`、`verification=pinned`；四來源的 `historical_pit` 均為 unsupported。統籌 full backend 為 237 passed、4603 warnings、25.31 秒、exit 0；獨立 contract checks 61／61。23 個 protected targets 的 hash／size／mtime 不變，未跑 frontend（本輪無前端變更）。證據與三個最終來源檔 hash 集中在 [SOURCE_REGISTRY §7](SOURCE_REGISTRY.md#7-round09-final-review-證據)。

### 1.6.1 Round18 `source-capture/v1` standalone runtime（有限範圍已 review）

這個命令不是正常 `collect`／`daily`／`backfill`，也不碰 DB。從專案根目錄以一個已存在的專案外 parent、尚不存在或空的 output directory 執行；以下三個 `STOCK_*` 隔離值屬防護設定，runtime 的獨立 import 驗收證實不會載入 app／pipeline／sources 或建立這些路徑：

    $env:PYTHONPATH = (Join-Path $PWD 'backend')
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $captureRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('stock-source-capture-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $captureRoot | Out-Null
    $env:STOCK_DATA_DIR = Join-Path $captureRoot 'unused-data'
    $env:STOCK_DB_PATH = Join-Path $captureRoot 'unused.db'
    $env:STOCK_RAW_DIR = Join-Path $captureRoot 'unused-raw'
    $registryPath = (Join-Path $PWD 'backend/worker/source_registry.json')
    $expectedRegistryVersion = 'r1-a1-c009-2026-09-12.1'
    $expectedRegistryDigest = 'sha256:eb6c290d7716300c4117bb2cdc61a66cbf8d62e344870928933b44b77461f87b'
    python -m worker.source_runtime capture `
      --manifest $registryPath `
      --profile free_public_local `
      --source twse_stock_day_all `
      --expected-registry-version $expectedRegistryVersion `
      --expected-digest $expectedRegistryDigest `
      --output-dir (Join-Path $captureRoot 'capture')

`--source` 只接受 `twse_stock_day_all`、`twse_holiday_schedule`、`twse_twt48u_all`、`tpex_spendi_history`；每次只選一筆。執行前會驗 external version＋digest pin、profile、source version、固定 exact URL／GET、`local_fetch` 與 `raw_store` 都為 allow、condition exact set，以及 manifest rate-limit status 仍是 executor 可處理的 `unknown`。任何 preflight 錯誤都維持 `request_count=0`，CLI stdout 回 `source-capture/v1` failure receipt、exit 2，不建立 failed output file。

成功時 output directory 只有 `capture.zip`，ZIP_STORED 內含 `body.bin` 與 `receipt.json`。`body.bin` 是 HTTP transfer framing 後、content decoding 前的 identity entity bytes；client 送 `Accept-Encoding: identity`，非 identity `Content-Encoding`、非 2xx、invalid JSON、NaN、逾時或超過 5 MiB 都失敗且不發布。15 秒是 httpx per-operation timeout；30 秒只在 streamed chunks 之間 cooperative 檢查，不是 hard total timeout。沒有 retry、redirect follow 或 warm-up；429／503 的 `Retry-After` 原值只在 stdout failure receipt。成功 receipt 包含 aware UTC 時間、body bytes／SHA-256、pins、policy decisions、condition receipts、來源 attribution 與原 manifest `rate_limit_evidence`；目前 `rate_limit_verified=false`，不得解讀為已驗官方 numeric quota 或跨 process 節流。

publication 先把完整 bundle 寫入同 directory staging，再以 exclusive hard link 建立 `capture.zip`；既有／競爭 target 不覆寫，filesystem 不支援 hard link 時 fail closed。失敗只清理自己擁有的 lock／staging，不刪競爭者檔案。不要把 output 指進 workspace、正式／`.local` data 路徑或缺少 parent 的路徑。

Round18 final：統籌完整 backend 519 passed、1 skipped、5,066 warnings，pytest 57.36 秒／process 58.75 秒、exit 0；獨立 33／33 checks 全過，驗證期間納入 guard 的程式／測試來源與正式／`.local` 兩 DB fingerprints unchanged。作者 targeted 54 passed、1 skipped／2.21 秒，作者 full 519 passed、1 skipped、5,066 warnings／57.75 秒。skip 是 symlink privilege unavailable，Windows junction 真實案例已通過。統籌另只對 `twse_stock_day_all` 做一次 live CLI：1 request、HTTP 200、319,396 bytes、1,379 rows、SHA-256 `0b1aff71084982ae31d719b47fff2c975205c6173ccb6d083232b4f5eeb23cbe`，bundle integrity 通過；不能外推另外三筆 live 可用或來源／時間 truth。證據範圍見 [SOURCE_REGISTRY §7.1](SOURCE_REGISTRY.md#71-round18-c018-standalone-source-capture-final-review-證據)。

本節只結清獨立 raw capture；legacy collector gate、session／action／suspension 內容驗證、C007 strict time evidence、`summarize`、`historical_pit`、PIT、排程與正式來源 truth 均未完成。

### 1.6.2 Round19 `STOCK_DAY_ALL` bundle → existing collect（有限接線已 review）

Round19 沒有新增 CLI；這是 caller 明確選用的 Python library path。先在任何 `collect` 前完整載入一次 Round18 `capture.zip`，並指定同一份 externally pinned manifest、profile、registry version／digest、精確 market date 與專案外 materialization directory：

    import os

    os.environ.update({
        "STOCK_DATA_DIR": str(temp_data_dir),
        "STOCK_DB_PATH": str(temp_db_path),
        "STOCK_RAW_DIR": str(temp_raw_dir),
    })

    from worker.stock_day_capture import load_stock_day_capture
    from worker.sources import OfficialMarketDataAdapter, TpexAdapter, TwseAdapter
    from worker.pipeline import collect

    capture = load_stock_day_capture(
        capture_zip,
        manifest=registry_path,
        profile="free_public_local",
        expected_registry_version=expected_registry_version,
        expected_digest=expected_registry_digest,
        expected_market_date=market_date,
        output_dir=materialized_output_dir,
    )
    adapter = OfficialMarketDataAdapter(
        twse=TwseAdapter(fetcher=twse_fetcher, stock_day_capture=capture),
        tpex=TpexAdapter(fetcher=tpex_fetcher),
    )
    result = collect(end_date=market_date, adapter=adapter, force=True)

上例的 `temp_data_dir`、`temp_db_path`、`temp_raw_dir` 與 `materialized_output_dir` 都必須先解析成專案外 Temp 路徑；三個 `STOCK_*` 設定必須在 import `worker.sources`／`worker.pipeline` 或任何會載入 app config 的模組**之前**完成。本輪只授權專案外隔離測試；不要在已 import 舊 config 的長駐程序內重設環境變數並假定路徑已切換，也不要把這段操作防護寫成產品 runtime 新 gate。

`load_stock_day_capture(...)` 只在 ZIP、receipt、pins／policy、全 body code／date 結構與 output preflight 全部通過後，才以 lock＋exclusive `xb` materialize plain `body.bin`、`receipt.json` 並回傳 capture object。既有輸出、競爭寫入，或 materialized body／receipt 與 capture object 的受驗時間、hash、body 欄位不一致都 fail closed；每次 `select(...)` 都重新核對。兩個 plain files 不是雙檔 atomic publication，也不是永久 immutable artifact；local unsigned metadata 不是 authenticity proof，也不防惡意 Python caller。

這條 opt-in 只替換 capture date 的 `STOCK_DAY_ALL` selected-security input。同日 missing／invalid symbol 不可由 MI_INDEX security row 補回，其他歷史日期與同日 MI_INDEX／TAIEX 維持原 path；TPEx 也不受 capture 取代。因此上例的 `twse_fetcher`／`tpex_fetcher` 必須依執行目的明確提供：隔離測試可注入本地 fixtures，正常 adapter 則仍可能發網路請求。不得把單一 capture 寫成 all-offline、full-runtime gate 或兩市場完整 collector。若相同 request key 已有成功 run，`force=False` 可能直接 reuse 並跳過 capture；要驗這條接線必須明確用 `force=True`。

selected OHLC 必須完整、有限、正值且 range 自洽；`TradeVolume` 是非負 signed-64-bit 精確整數，`TradeValue` 非負，缺漏／非法不能補 0。數字以 `Decimal` 解析，`9007199254740993.0` 可精確轉成 `9007199254740993`。成功列保留原 bundle SHA、aware UTC `captured_at` 與兩個 materialized refs；capture UTC 寫入新 `RawPayload.collected_at`，`MarketBar.collected_at` 仍為 ingestion-now。raw dedup 只在完整 `ingestion_run_id + source + endpoint + sha256` 相同時重用原 row、path 與 timestamp。`adj_close` 仍有既有 `record.adj_close or record.close` persistence fallback，不能宣稱已有 adjustment truth。

missing／invalid selected symbol 會留下 warning，run 可依既有整體結果為 `partial`／`failed`；upsert-only 不刪同 symbol/day 的舊 bar。capture 也不能單獨建立 session：沒有獨立有效的 MI_INDEX／TAIEX 時，即使 capture 有 bars，run 仍 failed、raw 可保留但不得建立新 bar／session。`captured_at` 不是 published／first-available／revision time；本批未接 C007 time store、availability truth、B5b／PIT、summary、正式分類、排程或正式 DB。

Round19 final：統籌完整 backend 590 passed、1 skipped、5,198 warnings，pytest 47.27 秒／process 48.344 秒、exit 0；code／tests 與正式、`.local` 兩 DB 的 before／after fingerprints unchanged，文件未納入該 guard。獨立 capture 30／30 checks 重讀保存的 1,379-row bundle，得到 1,367 個有效 rows／12 個 unavailable；獨立 existing-consumer 7／7 checks 以真實 adapters／`collect`、本地輔助 fixtures 與全面禁 HTTP 完成，結果 `partial`、`records=2`、`taiex_records=1`、`raw_payloads=10`，並驗 old bar 保留、只有完整 `ingestion_run_id + source + endpoint + sha256` 相同才 raw reuse、session 不由 capture 新增及 integrity／FK。這不是新 live 或兩市場完整內容證據；完整 hashes、精度 probe、另外兩個 full-suite integration 與限制見 [SOURCE_REGISTRY §7.2](SOURCE_REGISTRY.md#72-round19-c019-b-stock_day_all-contentconsumer-final-review-證據)。

### 1.6.3 Round20 `holidaySchedule` bundle → positive request exclusion（有限接線已 review）

Round20 已 review 一條新的 library-only opt-in。先依 §1.6.1 對 `twse_holiday_schedule` 取得一次專案外 `capture.zip`；下列 `STOCK_*` 必須在任何 `worker`／`app` import 前設定成全新的專案外 Temp 路徑，因為 `worker.sources` 本身也可能載入設定：

    import os
    import tempfile
    from pathlib import Path

    runtime_root = Path(tempfile.mkdtemp(prefix="stock-r20-holiday-")).resolve()
    os.environ.update({
        "STOCK_DATA_DIR": str(runtime_root / "data"),
        "STOCK_DB_PATH": str(runtime_root / "stock.db"),
        "STOCK_RAW_DIR": str(runtime_root / "raw"),
    })
    materialized_output_dir = runtime_root / "holiday-materialized"

環境固定後才載入預定介面；`capture_zip` 與 `registry_path` 必須由 caller 明確提供，不可複製本例後落回 default data path：

    from worker.holiday_capture import load_holiday_capture
    from worker.sources import OfficialMarketDataAdapter, TpexAdapter, TwseAdapter
    from worker.pipeline import collect

    holiday = load_holiday_capture(
        capture_zip,
        manifest=registry_path,
        profile="free_public_local",
        expected_registry_version=expected_registry_version,
        expected_digest=expected_registry_digest,
        expected_schedule_year=schedule_year,
        output_dir=materialized_output_dir,
    )
    adapter = OfficialMarketDataAdapter(
        twse=TwseAdapter(fetcher=twse_fetcher, holiday_capture=holiday),
        tpex=TpexAdapter(fetcher=tpex_fetcher),
    )
    result = collect(end_date=end_date, months_back=months_back, adapter=adapter, force=True)

`capture_zip`、`materialized_output_dir` 與三個 `STOCK_*` 路徑都必須解析到專案外；同一 request key 已有成功 run 時，`force=False` 可能直接 reuse 而沒有消費 holiday capture。未提供 `holiday_capture` 時 legacy holiday GET 不變；顯式提供但 loader／select 拒絕時不得 silent fallback。這不是新 CLI，也不是 full offline：其他 TWSE／TPEx feeds 仍由 caller 指定的 fetcher 或正常 network path 取得。

loader 只在 bundle／receipt／pins／policy／hash／aware UTC time 與全 body 結構通過後回傳 capture object。每列必要 `Name`／`Date`／`Weekday`／`Description` 是 string，額外欄可存在；Date 接受已明列的 ROC／Gregorian compact、slash、hyphen 格式，但必須全域唯一、可無歧義換算且全部屬 `expected_schedule_year`，weekday 也須與日期一致。每次 `HolidayCapture.select(start, end)` 都重驗 materialized bytes／receipt／hash／year／time。range 可跨年：只可能排除 capture 年度內通過 closed grammar 的日期，其他年度與 unknown wording 仍走既有查詢。materialized `body.bin`／`receipt.json` 以 lock＋exclusive create 依序寫入，任一步驟失敗只清理自己擁有的檔案且不覆寫競爭者；兩個 plain files 不是雙檔 atomic publication 或永久 immutable artifact。

positive exclusion 只接受有限 holiday-name 加 exact `依規定放假1日。`、內含日期／weekday／日數可重算一致的完整多日／補假句，以及 exact `市場無交易，僅辦理結算交割作業` 加空 Description。開始交易、春節前最後交易及任何未識別文字都不排除。多日 `fetch_bars` 可略過這些 explicit closed weekday 的 MI_INDEX request；單日範圍不使用 capture。calendar 本身不加入 `no_data_dates`，不產生／刪除 `MarketBar`、TAIEX 或 session，也不證明未列日期開市或全年 coverage。collect 仍是 upsert-only；隔離或正式 DB 原有的 closed-date bar／session 不會由本能力刪除或修正，「不新增 session」只描述本次 calendar 行為，不是既有 calendar consistency repair。

同一流程實際可見的 daily all-symbol security 或 current index 有有效 OHLC，而日期同時被標為 closed 時，整次必須 fail closed；不檢查也不宣稱知道因 calendar 排除而根本未抓取的 MI_INDEX 內容。holiday raw 仍以原 SHA、receipt `captured_at` 與 materialized refs 進既有 raw audit，`data_as_of` 只記 schedule year；capture time 不是 official published／first-available／revision time。新增／未知名稱或文字會留下 `holiday_capture_unknown` warning，整體 run 可依其他結果為 partial；未提供 capture 時仍使用既有寬鬆文字判定，本批沒有修改 legacy grammar。

Round20 final：freeze hashes 為 `sources.py=d05f2aec…2065a6`、`holiday_capture.py=f209f557…de640e`、`test_holiday_capture.py=abb2f8ab…e208237`。統籌以 Python 3.12.14、Alembic 1.19.2 執行完整 backend：678 passed、1 skipped、7,201 warnings，pytest 53.89 秒／process 55.016 秒、exit 0；guard 內 code／source 與正式、`.local` 兩 DB fingerprints unchanged，文件不在該 guard。final independent 17／17 checks 核對保存的 27-row live body、24 closed／18 weekday／3 non-closure oracle、五個 legacy delta、全域／文字／capture object timestamp drift、request list 及真實 adapters／collect，隔離結果為 `partial`、26 records、13 TAIEX、48 raw，raw UTC／hash／reuse、closed 不新增 session、integrity／FK 通過。作者 final holiday suite 為 88 passed／2,003 warnings／6.84 秒；較早的作者 676-pass full 是新增兩測試前結果，不作 final full。作者測試與主 full 另涵蓋 combined TWSE＋TPEx fixtures、force／reuse、materialized bytes／receipt tamper、stale closed row 保留及 conflict raw；不把主 17 checks 外推成完整雙市場矩陣。唯一 skip 沿用 Round18 Windows symlink privilege，沒有新增 skip。完整證據與限制見 [SOURCE_REGISTRY §7.3](SOURCE_REGISTRY.md#73-round20-c020-b-holidayschedule-contentconsumer-final-review-證據)。

### 1.6.4 Round21 TPEx today announcement code-only 修正（有限資料品質修正已 review）

本批沒有新 CLI、registry row、capture bundle 或正式 DB 操作。既有 collector 仍抓取 `TPEX_SUSPEND_ENDPOINT=/tpex_spendi_today` 並保存 raw，但不再只因 response row 有 `SecuritiesCompanyCode`，就把 `end` 日同代號的正常 OHLC bar 覆成 `is_suspended=true`。官方 catalog 名稱是「當日公布暫停／恢復交易股票」，且 schema 同時有 `暫停交易` 與 `恢復交易` 字串；它不是 current suspended-only list。非空公告現在只在既有 warnings list 留純文字警告供稽核，不新增 stable reason code／schema；空 response 也不可當作開市證據。

final review 已分別核對只有代號、恢復公告、future suspension、malformed／狀態不足、未選取代號與 empty today response。code-only 公告不再改寫正常 bar 或阻斷已重現的 tracking trigger／comparable；effective-session、return 與 signal eligibility 目前只有靜態影響路徑，不列為本批獨立實證。統籌 independent review 9／9 checks 使用 actual `TpexAdapter`、保存的 pre-round fixture fetcher、raw file SHA 與真 SQLite upsert／tracking，並驗明確外部 suspension flag、integrity／FK；它不是 whole `collect`，也沒有獨立驗 ingestion-run linkage。完整 `collect`、raw linkage、force／failure 行為由作者 targeted tests 與統籌 full backend 實跑覆蓋；final full 為 696 passed、1 skipped，106 個 code／tests／正式與 `.local` DB guard 路徑 unchanged。第一次完整 suite 因三個既有 success／reuse fixture 誤帶非空 today 公告而有 3 failures；只隔離該無關 fixture後 final full 轉綠，原 assertions 保留，失敗證據也保留。

同一 request key 若已有 `success`，`force=False` 會 zero-call reuse，不會消費新邏輯或修舊旗標；既有 `partial` 不走該 shortcut，`force=False` 仍會重抓。`force=True` 新 fetch 可按本次正規化更新同日 `MarketBar.is_suspended`，但不會自動重算既存 `SignalEvaluation`，也不修正其他日期。需要 retroactive repair／replay 時必須另立範圍與證據，不能把本輪 normal collect 測試外推。

`tpex_spendi_history` 是另一個 event-date list：`event_date` 是停牌／復牌生效日；caller `end` 是研究 cutoff；raw `collected_at` 是本系統觀測時間；官方 first availability／revision lineage 仍未知。未來 `DateOfResumedTrading` 可能是已公告排程，不能因日期晚於 cutoff 就一律刪除；但較晚抓到的 current snapshot 也不能證明較早 decision 時已知。本批不改 history parser、`_suspension_gap_between(...)` 或 Event persistence，只保留這項 PIT 限制；完整矩陣、最終 696-pass full／9-check independent review 與截斷 catalog 證據邊界見 [SOURCE_REGISTRY §2.6](SOURCE_REGISTRY.md#26-round21-tpex_spendi_today-code-only-停牌推論修正有限資料品質修正已-review) 及 [§7.4](SOURCE_REGISTRY.md#74-round21-c021-cd023-c-today-announcement-code-only-final-review-證據)。

### 1.6.5 Round22 TPEx history `Serial` 身分修正（有限資料品質修正已 review）

本批沒有新增 CLI、registry row、capture bundle、migration 或正式 DB 操作；只把既有 `parse_tpex_suspension_history_rows(...)` 的 identity keys 由 `SecuritiesCompanyCode, Serial, Code, 證券代號, 代號` 收窄為 `SecuritiesCompanyCode, Code, 證券代號, 代號`。官方 bounded schema 明列 `Serial=編號`、`SecuritiesCompanyCode=證券代號`；`Code` 與兩個中文欄位只是既有 local compatibility aliases，不代表 exact endpoint 官方 schema 有這些欄位。parser 仍取第一個非空值後查 `allowed_symbols`，canonical 非空但不在 universe 時不嘗試後續 aliases；本批沒有新 conflict/type/date policy。

運維上要分清「阻止新錯 Event」與「修復舊 Event」。Serial-only／Serial-shadowed 新回應不再把編號當證券代號，但成功 request key 的 `force=False` 仍可 zero-call reuse；`force=True` 雖會重抓、保留此次擷取的 raw 證據（可能去重）並 upsert 新解析結果，empty、被忽略或改成另一證券的結果都不會刪除先前錯存的 `Event`。舊 Event 仍可能讓 `_suspension_gap_between(...)` 及新 tracking evaluation 得到 suspended，既存 `SignalEvaluation` 也不自動重算。因此不要以 force refetch 當 retroactive repair。專案外隔離 diagnostic／repair 設計／replay 可依既有免費公開資料與本地測試授權續做；只有正式 DB cleanup／replay 寫入需另有具名授權、備份、選取、dry-run、回滾與對照驗收。

作者新 34-case suite 覆蓋 pure parser、actual TPEx／both-market Official adapter、actual `collect`、migration-created external SQLite、raw FK、gap／tracking、reuse／force 與 legacy retention；final targeted 為 97 passed、1,597 warnings、pytest 4.71 秒。統籌 independent 15／15 checks 使用 actual `TpexAdapter` 與真 SQLite，但不是 whole `collect`、無網路，且 DB 以 current `Base.metadata` 建立；統籌 full backend 為 730 passed、1 skipped、8,093 warnings、pytest 55.53 秒／process 56.688 秒，107 個 guard paths（含兩 DB）unchanged。完整證據歸屬、hash 與限制見 [SOURCE_REGISTRY §2.7](SOURCE_REGISTRY.md#27-round22-tpex-history-serial-身分修正有限資料品質修正已-review) 及 [§7.5](SOURCE_REGISTRY.md#75-round22-c022-b-tpex-history-identity-有限-review-證據)。

### 1.6.6 Round23 TPEx history split-row resume linkage（有限資料品質修正已 review）

本批沒有新增 CLI、registry row、capture loader、migration、schema／execution version、gap algorithm、future event cutoff 或正式 DB 操作。`parse_tpex_suspension_history_rows(...)` 先沿用 Round22 的 identity／alias precedence、`_text(...)` coercion、`parse_roc_date(...)` 與 exact `allowed_symbols`，再按同一 selected symbol 的**全部輸入列**計數；invalid、空日期與 duplicate 也算列數。只有恰好兩列，其中一列 start 可解析且對側 resume raw text 空白，另一列 resume 可解析且對側 start raw text 空白，並滿足 `start < resume`，才把 resume linkage 加到 suspension Event；不依 `Serial`、列序、相鄰性或 time 欄判定，time 只保留 raw。

符合條件時，suspension details 的原 `source_row` 仍指 start row，既有 `resumed_date`／`interval_end` 由 null 補為 resume date，並新增完整 `resumption_source_row`；分開的 resumption Event、payload provenance、bars、warnings 與 coverage 維持既有行為。不符合唯一 split pair 的 unmatched blank、malformed nonblank、倒置、same-day／intraday、同列雙日期、duplicate／multiple cycles 或 identity 歧義全部保留舊 row-local 行為，可能仍有 `interval_end=null` 與無界 tracking 推定；操作者不得把本批解讀成 fail-closed hardening、reason-code policy、完整 halt coverage 或復牌日開市證明。

同 key 的舊 null end 可由實際 `force=True` fetch upsert 成 finite end；`success + force=False` 仍可 zero-call reuse。相同 raw content 可依既有 dedupe 重用 raw FK，不保證每次新增 raw row；舊錯身分 Event 不刪，既存 `SignalEvaluation` 不重算，新 evaluation 才使用當時 Event details。專案外 diagnostic／repair design／replay 可以持續；正式或 `.local` DB cleanup／replay 寫入仍須另行具名授權。

D025-A exact body 共 362 rows、181 個唯一嚴格跨日 pairs；兩次成功 direct GET 中只有第二次保存 79,602-byte 原 body，SHA-256 `4e3747a4a27c1e45542ce476ff7ccd0384e5c420e9f2d5bbfd9257b9cc48e6a2`，另一次 web-open 回 502，成功回應也只有 `Content-Type` 而無完整 headers。9／9 oracle 是獨立仿寫 predicate；統籌 `live_shape_review` 是不 import production parser 的 offline 獨立 shape oracle，production parser 的 whole-181 三種排列另屬 19-check independent review。C023-A2 把 full saved body 送入 actual adapter，再由 synthetic universe 只選 `1788` 兩個 Event，並另以本地 fixtures 驗 `collect`／SQLite；這不是 whole-181 DB consumer。作者嵌入式兩列 cases 才直接使用 `1788` subset。

作者五個相關 module 為 142 passed、1,846 warnings、exit 0；較早一次指定不存在 `test_pipeline.py` 得 exit 4／no tests，修正命令後轉綠。統籌 independent 19／19 checks、完整 backend 775 passed／1 skipped／8,342 warnings、exit 0，108 個 guard paths（106 個 code／tests／frontend 加兩個 DB）unchanged。程式／新測試 SHA-256 分別為 `04872eb7ab86efdfadf80459bffc9a09db7a40aa358eae8b08e64ba5a731a178`、`3a847b82ca7e52d19c478a261b0c08759b565c4309e86acd90253788f5344234`；完整證據歸屬與限制見 [SOURCE_REGISTRY §2.8](SOURCE_REGISTRY.md#28-round23-tpex-history-split-row-resume-linkage有限資料品質修正已-review) 及 [§7.6](SOURCE_REGISTRY.md#76-round23-c023-bd025-b-split-row-linkage-final-review-證據)。

### 1.6.7 Round24 TPEx 公司行動 ratio／reference mapping（有限資料品質修正已 review）

修正前 `TpexAdapter.fetch_actions(...)` 的兩個來源語意有維度錯置：`StockDividend` 的官方名稱是「權值」，由「除權息前收盤價－息值－未進位除權息參考價」得到，是價格差額，不是配股率；`OpeningReferencePrice` 是除權息後按檔位選取的「開始交易基準價」，不是除權息前收盤價。C024-B 只把 `stock_dividend_ratio` 改由 exact `StockDivdendThousandShares`／local `每仟股無償配股` 讀取，parsed non-null 再除以 1,000；`reference_price` 改由 exact `ClosePriceBeforeExRightsDiviend`／local `除權息前收盤價` 讀取。舊 `StockDividend`／`權值`／`無償配股率` 及 `OpeningReferencePrice`／`開始交易基準價` fallback 移除；兩個中文名稱只是 local compatibility labels，不是 checked API keys。

操作與驗收必須維持窄界線：cash 欄位 precedence／精度、identity、ROC date、future as-of filter、action type、raw details／payload SHA、順序／列數均不改；前收缺失仍沿用既有 previous official bar fallback，但不能把該 bar 說成官方 Article 57 substitute truth。在本輪具名正常輸入案例（finite `P>C≥0`、`Rf≥0`，且無 paid subscription 或其他同日調整）中，既有 factor 可寫成 `1/(1+Rf) × (P-C)/P`，與官方 `Q/P=(P-C)/(P×(1+Rf))` 等價；這不是 negative／non-finite／invalid 的全面 hardening，也不保證同日其他 action 合成已完整。

完整公式另含現金增資：`Q=(P-C+S×Rp)/(1+Rf+Rp)`。現有 normalized model／factor 沒有 `Rp` 與 `S`，所以 paid subscription 仍不正確；不可用只修 free ratio 的結果冒充 paid 已支援。C024-B 不採 `ExRightsDiviendQuote/P` explicit factor、不接 `tpex_exright_prepost`、不改 TWSE、共用 factor、schema／execution version、registry／capture／PIT，也沒有自動或正式 repair：有效同 key 的 `force=True` refetch 可 upsert 舊 `CorporateAction`，`force=False` reuse 不更新；`collect` 不自動重算舊 `SignalEvaluation`，但顯式對同 signal evaluate 可能 upsert。

D026-A 保存的 `tpex_exright_daily` 當次 body 僅三筆 ROC 1150914 cash-only；以本輪 2026-09-13 as-of 應由既有 future cutoff 全數排除，2026-09-14 的隔離 replay 不是 historical availability 證據。non-zero free ratio 只可用 official-schema-shaped synthetic 驗 `/1000` 與 downstream factor，不得標成 live。另一份 `tpex_exright_prepost` current body 是分離來源且尚無 registry admission／consumer。作者 C024-B 的 dedicated 為 34 passed，相關 targeted 為 79 passed、1,094 warnings、exit 0；統籌 independent 26／26 checks、exit 0，完整 backend 809 passed、1 skipped、8,731 warnings、pytest 56.26 秒（process 57.5 秒）、exit 0，109 TOTAL＝107 個 source／code／tests／frontend paths＋2 DB guard unchanged。唯一 skip 是既有 Windows symlink privilege case。程式／新測試 SHA-256 分別為 `8381ab59b4ddc462f354ccbab5642f2dd2c84b2b4b3a3cdf8f45a7886c0e0211`、`be1fd88112b560a17408693edc7b7e33ecd82869a9d5ca76ea87db05db2cb9a8`。調查、7 次 direct GET、oracle、證據歸屬與限制見 [SOURCE_REGISTRY §2.9](SOURCE_REGISTRY.md#29-round24-tpex-公司行動-ratioreference-mapping有限資料品質修正已-review) 及 [§7.7](SOURCE_REGISTRY.md#77-round24-c024-bd026-b-公司行動-mapping-final-review-證據)。

### 1.6.8 Round25 TPEx 公司行動 cash precision（有限資料品質修正已 review）

C025-B 只把同一 `TpexAdapter.fetch_actions(...)` 的 `cash_dividend` 欄序改為 `CashDivdend` → `CashDividend` → `現金股利` → `息值`。前兩個是 checked exact keys，後兩個只作 local compatibility；較精確的「現金股利」先於六位小數「息值」。沿用 `_text` first-nonblank 與一次既有 `parse_number`：missing／null／空白才 fallback，nonblank invalid 會得到 null 而不降級；leading-dot 仍受既有 substring parser 行為影響，負值、NaN 等全面 policy 沒有趁本批改動。

保存的 5278 row 在 2026-09-14 隔離 replay 改取 0.26618165，cash-only factor 的 Fraction 是 `472676367/478000000`；6204、8423 數值不變。這只修 normalized 每股 cash 的 precision／selection，不保證與官方顯示 quote、未進位或 tick 規則在所有小數位一致；三筆仍是 2026-09-13 觀測到的 future-dated current shape，2026-09-13 as-of 必須是零列，不是 PIT。

操作上，成功 `force=False` reuse 不 fetch，會保留已存在的舊 cash；只有有效 `force=True` refetch 才把同一 action ID 更新成精確值，raw 可因相同 bytes 重用同一 raw ID。這不會自動重算舊 evaluation；新 signal 的 normalized history／tracking 會使用新 factor，而顯式重跑同一 signal 仍可能 upsert。previous-reference fallback 只是 action 日前找到的既有 `MarketBar.close`，可能來自 synthetic fixture，不能稱保證官方或 Article 57 truth。作者 actual whole-collect 提供 raw FK／bytes／reuse-force／兩 consumer 證據；統籌 29 checks 的 SQLite persistence 是 direct `_upsert_action(raw FK=None)`，兩者不可混稱。

Paid、TWSE 與完整公司行動仍不在本批。paid 需要可信 `Rp/S/P`、持久化及版本策略；新增 schema/migration 只是一種未核准方案，raw `details_json` 可承載欄位也不等於已准入。TPEx 4541 已證 direct `Rp=0.07391303` 不等於 pro-rata-per-thousand 除 1,000 的 `0.05913042676`。TWSE type-only 修正會因 `action_type` identity 留下第二筆 action 並雙算；checked TWT48U_ALL 沒有 pre-close/reference 欄，均留後續獨立處理。完整 final review、831-pass full suite 與限制見 [SOURCE_REGISTRY §2.10](SOURCE_REGISTRY.md#210-round25-tpex-公司行動-cash-precision有限資料品質修正已-review) 及 [§7.8](SOURCE_REGISTRY.md#78-round25-c025-bd027-b-cash-precision-final-review-證據)。

### 1.6.9 Round26 TWSE action source classification（有限唯讀投影已 review）

`GET /instruments/{symbol}` 的既有 `corporate_actions[]` 現多一個 `source_action_classification`。只有 source exact `twse`、exchange exact `TWSE`、details 為非空 mapping，且 exact `Code`／`Date`／`Exdividend` 均為 nonblank string，Code、7 位 ASCII ROC date 與 action identity 一致，`Exdividend.trim()` 又是 `息`／`權`／`權息`，才回 `ex_dividend`／`ex_right`／`ex_right_and_dividend`；其他一律 `unknown` 並給固定 reason。local aliases 只做 conflict check，不能補足 official fields。完整輸出 shape、reason precedence 與 alias/date 規則以 [SOURCE_REGISTRY §2.11](SOURCE_REGISTRY.md#211-round26-twse-source_action_classification有限唯讀投影已-review) 為唯一契約。

這是 response assembly 的唯讀相容投影：既有 `type`、action identity、排序／50 筆上限、worker、raw、factor、schema、前端與 DB 不改；成功 reuse／force 行為、舊 evaluation 與既有 duplicate factor 風險也不修。作者 targeted 149 passed；統籌獨立 129 checks、完整 backend 935 passed／1 skipped，舊／新同為 19 queries，均 exit 0。保存 body 68 rows 為息 63／權 2／權息 3；2026-12-31 full replay 是 current snapshot exercise，不是 PIT。操作上不得把 `trusted_twse_exact_fields` 解讀為官方 event ID、authenticity、raw-body membership、完整性、first availability 或 revision。完整證據與限制見 [SOURCE_REGISTRY §7.9](SOURCE_REGISTRY.md#79-round26-c026-bd028-b-twse-source-classification-final-review-證據)。

## 1.7 Round12 `signal-artifact/v1` 本地 store（有限 foundation 已 review）

`SignalArtifactStore` 是 Python local API，不是現有 worker CLI、API endpoint 或啟動流程的一部分。它沒有預設 DB 路徑，也拒絕 `:memory:`；caller 必須明示專案外的專用 SQLite 檔。不要把 `STOCK_DB_PATH`、正式 `data/stock.db`、專案 `.local` 或 workspace 內路徑傳給它。constructor 會先做 resolved path／alias 保護；既存檔則先以 read-only ownership preflight 驗 store kind、schema version 與 owner token，再開 write-capable connection。既存空 DB、foreign DB、未知版本、symlink／junction／hard-link alias 都 fail-closed；拒絕時不得假定 WAL／SHM／journal sidecar 可被安全改動。

mapping 的 `contract` 可省略或為 `null`，normalizer 會補 `signal-artifact/v1`；non-null 未知版本拒絕。`SignalArtifact` dataclass 本身沒有 contract 欄。新 rule-only artifact 的 `confidence` 固定 null、confidence semantics 固定非機率 v2，`earliest_execution_at` 固定 null＋`execution_time_unavailable_without_pit_session_availability`。所有 source／implementation evidence 都是 caller-provided-only；store 只驗 canonical 結構與 digest 自洽，不證明官方來源、availability truth 或 repository commit。

寫入端要明示完整 instrument、market date、strategy、output semantics、snapshot、ruleset／implementation、basis／dependency、必填 aware `decision_at` 與 research result；`as_of_at` 可為 null，有值時才必須 aware。C012 實際以 research core 導出 `lineage_key`，再由 core＋positive integer `revision` 導出 `identity_hash`／`artifact_key`；`identity_hash` 不是純 input hash。root 是 revision 1／active；唯一 lifecycle child 是下一 revision／withdrawn＋supersedes、aware reason/time。沒有 `revision_id`、`revision_kind` 或獨立 `levels` 欄；caller 價位只有放進 `rule_evidence` 才會保存。

`save_artifact(...)` 使用 `BEGIN IMMEDIATE`，artifact、binding、feature refs、lifecycle、attempt 與 nullable run relation 同 transaction 寫入並在 commit 前重驗。同一 research core／revision 與同 payload 是 idempotent replay；同 identity 的 research payload 不同則 collision。`generated_at` 是本次候選時間，首次成功值才成 immutable store metadata；retry 不改舊值。每個 artifact 可有多個 attempt、每個 run 可跨多個 attempt，而每個 attempt 最多屬於一個 run；同 artifact＋run 的多次 attempt 合法。

讀取只用明確 selector：`get_exact(artifact_key=...)`、`get_exact(identity_hash=...)` 或 `get_exact(lineage_key=..., revision=...)`；`history(lineage_key)` 只看 exact lineage。`list_artifacts` 至少要求 lineage，或 strategy name／market date／exchange／symbol 其中一個實際支援的 filter，完全無 filter 時拒絕；沒有 implicit latest、`<= as_of` 或全庫 dump。reader 會重算 identity、payload／seal、binding、ancestor、feature refs、lifecycle、attempt 與 run relation；stored relation 的 run id 或 relation key 不一致也拒絕。回傳物是 detached transfer snapshot，不是宣稱 nested values deep immutable；修改某次 read 結果不得影響 DB 或下一次 read。

Round12 final：統籌完整 backend 為 285 passed／4625 warnings／16.95 秒、exit 0，獨立矩陣 45／45；作者 targeted 26 passed／1.56 秒、完整 backend 285 passed／17.29 秒；文件角色 targeted 26 passed／1.57 秒、exit 0。四個 final source/test SHA-256、cross-review 與限制見 [Signal artifact §9](SIGNAL_ARTIFACTS.md#9-round12-c012-final-review-證據與限制)。所有測試與 DB 都在專案外 Temp。

保護結果須記為 **40／41 unchanged**。正式 `data/stock.db` 不變且 C012 沒有 migration；`.local/data/stock.db` 的唯一差異可歸因另一個 `執行前後端專案` task（`01a0913c-797b-7863-a5a6-5f47f469bc9b`）依使用者另行要求在 09:27 啟動 lifespan `init_db`，不是 C012 store 寫入。統籌後續唯讀查驗其為 0006、News JSON defaults 為 `[]` 且讀前後 hash 穩定；這不等於 C012 證明 `.local` 全部歷史列 preservation，也不是正式 deployment／migration 驗收。

這一節不提供 legacy reader／comparison、API list/detail/action、DecisionSummary、UI、worker、官方 availability／PIT 或 B7；操作者不得把 local foundation 接成預設版本、正式排程或正式 DB，直到各後續批次獨立 review。

## 2. 現有 CLI

| 指令 | 行為與限制 |
| --- | --- |
| python -m worker.cli init-db | 明確初始化／升級指定資料庫；先核對三個 `STOCK_*` 路徑、consistent backup 與授權。API startup 不會代跑。 |
| python -m worker.cli collect --date YYYY-MM-DD --months-back 0 | 官方來源收集；months-back 只接受 0、1、2、3。 |
| python -m worker.cli daily --date YYYY-MM-DD --months-back 0 | collect 成功才 analyze；analyze 成功才 evaluate。 |
| python -m worker.cli backfill --start-date YYYY-MM-DD --end-date YYYY-MM-DD --scope market | 指定日期範圍的官方回補、重試與稽核；scope 見下文。 |
| python -m worker.cli analyze | 目前先檢查最新官方 collect run 的 success 和有效 as-of，再計算訊號；不能把它描述為任意局部分析器。 |
| python -m worker.cli evaluate | 更新訊號執行／逐日追蹤與 T+5／T+20 結算；會寫入資料庫。 |
| python -m worker.cli backtest --start-date YYYY-MM-DD --end-date YYYY-MM-DD | 回放已有資料、保存規則／結果 audit；不是下載歷史資料。 |

backfill 的既有 scope 為 market、portfolio、watchlist、events、candidates、priority、all；scope 名稱存在不代表已具備完整自選管理 UI 或來源。--force 會重新擷取已完成日期，不是一般重試的預設選項。

目前 backfill 要求起日不晚於迄日，兩日差不超過 OFFICIAL_MAX_BACKFILL_DAYS=93；為補足目標交易日可能使用其規則內的較早候選日期，仍受迄日前 93 日邊界限制。應檢查 request 範圍與 audit 的實際 effective scope，不能只看輸入日期。

回補計畫採最多 5 個交易日的批次，現有 adapter 調用逐日進行；立即 3 次及後續 2 次重試限制已在程式定義。保留 partial／missing／skipped 與 raw/error，不以空值改寫成功資料。

## 3. 隔離研究範例

以下只是歷史範例日期，不代表應立即執行或目前已取得完整資料：

    python -m worker.cli collect --date 2026-09-08 --months-back 0

如需指定期間回補：

    python -m worker.cli backfill --start-date 2026-06-10 --end-date 2026-09-08 --scope market

先檢查 run status、有效交易日、缺欄／缺日與原始來源，再決定是否分析。collect 為 partial／failed 時 daily 會跳過後續；目前 analyze 也有全域最新 run gate。ROADMAP 規劃中的 per-strategy／as-of 分析不可藉由人工改 status 為 success 達成。

只有符合當次資料與研究範圍時才分別執行：

    python -m worker.cli analyze
    python -m worker.cli evaluate
    python -m worker.cli backtest --start-date 2026-06-10 --end-date 2026-09-08

舊 Phase 3 的 2026-09-08 P1 是特定歷史驗收作業，不是所有未來 analyze 的日期限制。現有 CLI 沒有 P1 指令或 analyze --date 參數，不應杜撰。

## 4. 資料品質與結果

- 檢查用途所需的交易所、標的、日期與欄位；行情成功不代表法人／融資／事件也完整。
- 只有官方明確 no-data 無列日可略過；錯日、缺日、未知日期和無法解析維持缺漏。
- 時間未知、停牌、公司行動不可重建或同日 stop／target 順序不明，不假設有利成交／報酬。
- 買賣各 5 bps 與 30 bps round-trip 是現行執行假設，非所有真實交易費率。
- API／畫面上的 legacy entry、突破、回踩區、失效與 target 是**規則參考價**，不是持倉成本、委託或成交。持倉 `average_cost`／使用者 stop 與 tracking `execution_price` 要看各自來源；沒有 execution origin 時不可稱券商真實成交。`cost_included=false` 只表示 level 算式沒有扣成本。
- legacy `data_cutoff`、`signal_date`／`earliest_execution_date` 與 naive `created_at` 都不能證明 `decision_at`。B4a 若回傳 time／basis unknown，應讀取其 reason，不得由日期字串自行補午夜、13:30、UTC 或 raw／adjusted basis。
- 已 review 的 B4a response 使用 nested `level_semantics.version=signal-level-semantics/v1`；只有 allowlist name+version 可標 `rule_reference`／`legacy-risk-levels/v1`，其他為 `unknown`。其中 historical `decision_at`、`generated_at` 與 `price_basis` 仍是 null+machine reason；`response_generated_at` 只是含 offset 的 API 組裝時間。前端 `/signals`、`/tracking` 是相容 redirect，不應當成獨立畫面已驗收。
- /api/ingestion-runs、/api/backfill-runs、/api/data-quality、/api/backtest/summary 提供稽核與摘要；/api/coverage 提供覆蓋資訊。
- 前端研究頁為 /research/backtest、/research/coverage；舊 /backtest 為相容轉址。
- 短回測依 v1 為 insufficient_sample；更長範圍也須另行樣本外與執行驗證。

## 5. 前端與程式驗證

前端可用另一終端，自根目錄執行：

    Push-Location frontend
    npm install
    npm run dev
    Pop-Location

production build 與後端測試需分開執行，避免停留在 frontend 目錄時使用 backend 相對路徑：

    Push-Location frontend
    npm run build
    Pop-Location

    & ./tools/Invoke-Validation.ps1 -TestPaths @('backend/tests')

預設 API 為 http://127.0.0.1:8000/api；可於啟動前設定 VITE_API_BASE。pytest 應使用隔離 fixture／資料路徑，不能指向正式 DB 做測試。

### 5.1 Round13 個股研究頁驗證（有限產品範圍已 review）

個股頁驗收以 [個股研究頁契約](STOCK_RESEARCH_PAGE.md) 為準。先跑本輪具名資料轉換／元件測試，再跑完整 frontend test（若專案有對應 script）、TypeScript 與 `npm run build`；各命令的 exit code、pass／fail／skip 數與輸出路徑分開留證。不能只用 screenshot、fixture 或靜態型別宣稱真實 API 已接線。

瀏覽器檢查使用隔離資料路徑啟動的 API，或讀取已由其他 task 管理且確認安全的現存服務；不得為本驗收啟動既有 app lifespan 去寫正式或 `.local` DB，也不得停止、重啟或改寫現存服務。至少選一個有 60 根以上有效 bars 的個股與一個不足 20／60 根或含無效資料的邊界案例，核對：

- 路由、載入／錯誤／空資料狀態，及 API response 與圖表日期、OHLCV、成交量單位一致；
- 縮放、復位、hover／focus 資訊與等效可讀資料可操作；不同視窗大小不遮住必要資訊；
- MA20／MA60 逐點以該日以前的既有 close 計算，窗口不足、無效或跨缺口時不補線；最新 feature snapshot 不冒充歷史 MA 序列；
- 區間為實際回傳首末日，明示最多 120 根、不代表完整歷史；來源逐一彙整，unknown 或混合來源不被通用標籤改稱官方；
- K 線使用 API `open`／`high`／`low`／`close`，頁面顯示「原始 API 價格；還原方式未提供」。不得因另有 `adj_close` 就宣稱 OHLC 已還原、未還原或自行拼出調整後 K 線；
- 行動摘要、族群、法人籌碼、官方事件與 news、策略條件、coverage／品質各自保留來源與語意；策略 requires 不顯示成已達成，news 不因版面標題被誤稱為資料庫 Event。

真實 API 瀏覽器檢查仍只證明選定隔離資料與本輪產品路徑，不證全市場 coverage、來源權利／PIT、策略績效、正式 DB、安全部署或 B7。

2026-09-12 統籌以隔離、唯讀的正式 DB 備份完成具名測試、build 與 browser 流程，有限產品範圍改列 `已 review`；正式／`.local` DB、package 與 lockfile 未改。完整命令結果、版面／數值核對、仍存在的 chunk warning，以及較早版本舊分頁錯誤與修正後重驗，統一見 [個股研究頁契約](STOCK_RESEARCH_PAGE.md#51-2026-09-12-final-review-證據) 與其所指的專案外證據目錄。

原文件記載 2026-09-08 的 backend 54 passed 及 frontend build 通過，屬歷史紀錄。C-003 的 157 passed 只對其 final checkout、外部 Alembic 1.19.2 與隔離測試環境成立，不是來源 coverage、策略績效、正式 DB migration 或前端驗收。歷史 coverage 與驗證紀錄集中在 [DATA_SOURCES](DATA_SOURCES.md)。

### 5.2 Round14 全站前端 UX 驗證（已 review）

本輪逐頁驗收矩陣以 [Round14 UX review](UX_REVIEW.md) 為準，且沿用上一節的隔離資料、不得寫正式／`.local` DB 與不得干擾既有服務原則。至少以真實 API payload 核對：已知股數除以 1,000 後顯示為張、最多 3 位小數，法人負值保留方向；來源或單位 unknown／mixed 時不換算；族群詳情不因共用欄位缺席而錯顯「尚無研究動作」或「策略判斷資料：待補」，日期取正確 `meta.data_as_of`，成員分頁可操作。另須覆蓋上一頁／下一頁／儲存／庫存、台股紅漲綠跌且不只靠顏色、列表到詳情、鍵盤操作及窄版不溢位。

Round13 以原始股數核對 API／圖表的紀錄仍是當時資料轉換與 payload 的歷史證據；Round14 改的是使用者介面顯示契約，不可倒推 API 已改單位。統籌已完成具名 self-test、獨立檢查、typecheck／build 與瀏覽器核對，證據集中在 [Round14 UX review](UX_REVIEW.md#5-final-review-證據與限制)。

產業分類另須以 3176／TPEx `industry=22` 的負面案例核對：產品須顯示「既有族群關聯待重新核實」；族群卡片／詳情可保留中文 `display_name`，但必須加「（既有分類）」與待核實 badge，原始英文 membership name／ID 只在資料說明展開。官方產業排行與衍生研究條件不得標成已驗證。後續 mapping、有效期間與隔離重建一律依 [產業分類契約](INDUSTRY_CLASSIFICATION.md)；前端 warning 不等於資料修復。

2026-09-13 最終複驗期間，隔離唯讀 API `8133` 意外以 exit 1 結束，原因未確定；統籌恢復自己管理的測試服務後，個股與資料品質頁正常。R15 以新唯讀副本做四個 in-process request 及一次新 localhost uvicorn 真 HTTP：`/api/coverage` 200／19.455 秒／2,779,888 bytes，隨後個股 request 亦 200 且服務仍存活；這只表示本次未重現，不涵蓋瀏覽器、併發或長時穩定性。後續不得停止使用者其他服務。持倉只驗表單與純單位轉換，沒有實際寫入；正式 DB、後端及 package／lockfile 保持 baseline。Round14 輪末索引 receipt 已接受，backend `metadata_changed` coverage 限制仍保留。

### 5.3 Round15 產業分類隔離驗收（有限範圍已 review）

本輪程式與專案外隔離診斷已由統籌接受；正式與 `.local` DB 仍禁止寫入。日後只在明確授權範圍重跑診斷時，沿用以下安全順序：

1. 唯讀固定正式 DB SHA／size／mtime，以 SQLite backup API 建立專案外 consistent backup；current、baseline 與 corrected 三個工作副本都從同一 backup 建立。
2. 將 `classification_evidence_at=2026-09-13`、`membership_effective_date=2026-09-13`、`market_data_as_of=2026-09-08` 分欄保存。第一個是官方表核對日，第二個只是 current-table diagnostic 切換日，第三個是市場資料截點；皆不是歷史分類 truth。
3. current 副本只轉換 membership period，保留 2026-09-08 scores、原 signals、evaluations 與 settlements。baseline／corrected counterfactual 副本才以相同 market bars、chips、features 重算 scores，並以獨立 signal namespace 比對。
4. 驗 `integrity_check`、foreign keys、mapping 全表與負面碼、membership 無重疊、derived fingerprints、第二次執行無漂移、輸入／輸出與 source hashes；最後再比對正式與 `.local` DB 完全未變。

統籌 final review 獨立核對 current／counterfactual 各 1,974 個 supported 標的唯一 expected membership、35 個 unknown／special 無一般產業 membership、current 既有 derived rows 不變、counterfactual pair 輸入／歷史表等價、完整 backend 372 passed，以及 SQL／表／群組均值、integrity／FK 與正式／`.local` DB 不變。模型第二次 rerun 由作者執行，統籌 review 程式與 final report；獨立核對在 `C:/Users/YiCheng/AppData/Local/Temp/stock-r15-coordinator-review/independent-final-db-review.json`，作者完整 trace 在 `C:/Users/YiCheng/AppData/Local/Temp/stock-taxonomy-diagnostic-dbv_xvgb/report.json`。

若任一來源、legacy row 或歷史有效日缺 evidence，保留 unknown；不得以 listing date、raw collected date 或 2026-09-08 補造分類有效日。TPEx 80 管理股票與 TWSE 91 TDR 不進一般產業排行，`Other` 只接受精確 code 20。完整 current 表與有限 review 矩陣見 [產業分類契約](INDUSTRY_CLASSIFICATION.md#5-隔離驗收矩陣有限範圍已-review)。正式 DB 未修復前，Round14 guard 不得撤除；本結果不是歷史 PIT、fresh 公司 truth 或策略有效性證據。

### 5.4 Round16 normal collector 產業觀測稽核（有限範圍已 review）

`collect` 的行情 run 與 ordinary-industry receipt 要分開讀：run 可以是 `success`，而 `industry_membership_observations.status` 因 `D > score_date` 或 new-listing-only unresolved 成為 `partial`。此時只跳過對應 instrument 的 ordinary-industry mutation，不能把 run success 說成全分類 verified；非 force idempotent reuse 會透傳已保存 receipt。

操作檢查至少包含：

1. 核 `industry_membership_observations.version/scope/status/skipped_count/unresolved_count/warnings/observations`；逐筆比對 `exchange`、`symbol`、`source`、authoritative `endpoint`、`sha256`、`captured_at_utc`、`observed_date`、`score_date`、`raw_payload_id`、`stored_raw_collected_at_utc`、`time_semantics`、`raw_time_relationship` 與 `raw_classification`。listing／start／score date 與 caller-provided `data_as_of` 都不是分類有效日。
2. force success 會把前一份成功 receipt 加入 `industry_observation_history`；force failure 必須保留最後成功 receipt，並把本次資料放進 `industry_observation_attempt`／`industry_failed_attempts`。不要只看 run row 的最後狀態而遺失成功觀測或失敗嘗試。
3. 新 raw 的 aware timestamp 先轉 UTC，再以 UTC-naive 配合現有 SQLite 欄位保存；既有 naive rows 不回寫，仍只按本地 capture 的既有 UTC 契約解讀。missing／invalid timestamp 不得由 DB default 補現在時間，可能只有原始 payload file、digest、null／invalid value 與 `raw_persistence_errors`，但 run 必須成為 `failed` 而非停在 `running`；先確認 raw DB row 是否實際存在，再引用 raw id。
4. 成功／skip 重跑只核 collector-owned industry group、membership 與既有 historical score 不漂移；正常 forced ingestion 可以更新 `MarketBar.collected_at`。same-day／missing evidence 等 failed rollback 才另外核 instrument／bar 全欄不變。industry reconciliation 不改其他 domain 與缺席 instrument，但 collector 對其他 domain 的正常更新不在不變承諾。

統籌 final 完整 backend 為 412 passed／4,902 warnings／pytest 31.67 秒（process 33.031 秒）、exit 0；作者 final 為 412 passed／4,902 warnings／32.97 秒。統籌另以實際 TWSE／TPEx universe parser 加本地 official-shaped fixture 做 11 項完整 `collect` 檢查，並重跑 aware timestamp probe；integrity `ok`、FK 0，保護來源及正式／`.local` DB 前後一致。證據在 `C:/Users/YiCheng/AppData/Local/Temp/stock-r16-coordinator-review/`。這不是 live 官方來源、capture metadata 外部認證、既有 legacy raw 時間修復、歷史 PIT 或正式 DB 修復；R15 guard 繼續保留。下一批只先唯讀定界 ETF／new-listing 日期與 domain lifecycle。

### 5.5 Round17 ETF／new-listing candidate lifecycle 稽核（有限範圍已 review）

行情 `collect.status=success`、ordinary-industry receipt 與兩個 candidate 子 scope 要分開讀。`industry_membership_observations` 原本的 ordinary `scope=ordinary_industry_only` 與 counts 不包含 `etf`／`newlisting`；新增子節點各有自己的 version、scope、status、skipped／unresolved counts 與 observations。TAIEX 等 synthetic index 會在兩個子節點留下 `unresolved_synthetic_index`，因此行情 run 可 success、ordinary scope 可 observed，而 candidate 子 scope 為 partial；不得把其中一個狀態擴寫成全分類 verified 或 failed。

操作檢查至少包含：

1. ETF observation 逐筆核 source／endpoint／sha256、capture UTC、台北日 D、score date、raw payload id、normalized category 與 `classification_method_version=normalize_etf_category-v1`。raw category 文字由 raw capture 追溯，receipt 不另存該文字；有限 category 是 local heuristic，不是官方 taxonomy 或 source-effective truth。
2. new-listing 以 authoritative L 驗 `L..L+60` 曆日兩端 inclusive；20／60 根有效 bars 只屬 IPO actionable guard。新 period 從 D 開始且 bounded，D 前不回填；day 60 保留、day 61 無需再收集即可因既有 `valid_to` 自然退出。missing L 是 unresolved，非法 L／future capture／evidence conflict 則 fail；合法 capture 的 `D > score_date` 只 skip candidate mutation。
3. 核 ETF unchanged／gapless category change、authoritative ETF↔stock／IPO、new-listing legacy cap／過期 forward-close、same-day／overlap／identity conflict與 exact rerun。只有相符的 current authoritative record 可證退出；缺席、synthetic index、prospective `L>D`、manual、ordinary industry 或其他 hot group不得代證。既有 bounded hot row 的 `valid_to` 若不等於本次 `L+60`，保守拒絕而非覆寫；legacy 的 D 前錯誤期間仍保留。
4. receipt 只按實際 schema 核 `etf`／`newlisting` 子節點與既有 force history／attempt；不要假設每筆都有通用 `reason`、period before／after 或 `warnings` 欄位，也不要求 repeat receipt 的 `action` 與前一次 transition 相同。
5. SQLite helper 在 `begin_nested()` 前確認 physical outer transaction；helper 不 commit／rollback caller。實際 file SQLite 至少驗 success 後 caller rollback／commit、helper failure 只撤 savepoint並保留 caller pending writes，以及 helper 後 `sync_news_from_events` 故障使 normalized instrument／bar／group／membership 全 rollback、normalization 前已 commit raw 保留。

統籌以 Python 3.12.14、Alembic 1.19.2 執行完整 backend：481 passed／5,066 warnings，pytest 49.91 秒（process 51.328 秒）、exit 0；作者 C final 另為 481 passed／5,066 warnings／51.55 秒。統籌 actual TWSE／TPEx parser→本地 official-shaped fixtures→完整 `collect` 11 checks、SQLite rollback probe、integrity `ok`／FK 0 均通過；測試期間四個 frozen source 與正式／`.local` DB fingerprints 前後一致。證據在 `C:/Users/YiCheng/AppData/Local/Temp/stock-r17-coordinator-review/full-backend-review.json`、`full-backend.log`、`independent-collector-review.json` 與 `savepoint-rollback-probe.json`。B 版 477 passed 與 rollback=false 是中途結果；初版 independent harness 選錯前次 receipt，final 已改核最近成功 repeat receipt並重跑。

本節不證 live source／capture metadata 真值、ETF heuristic 品質、legacy 錯誤期間、synthetic index lifecycle、historical PIT、ordinary-industry↔ETF 歷史轉換、正式 DB 修復、guard 解除、metadata history 長期治理或策略有效性。該段當時的「下一輪」已在 Round18 選定並完成有限 standalone source capture；它不回頭擴大 Round17 的 candidate lifecycle 驗收。

## 6. 排程與未來工作

本輪沒有建立任何排程。收資料／重試排程需要來源延遲、rate limit、冪等、錯誤可見性、備份及操作設定；它不以策略績效驗證為前置。自動下單則是不同能力，不在第一版範圍。

本文件所列具名開發批次不執行來源採購、媒體或分點接入、AI 訓練、長歷史回補或正式 DB 寫入。已核准並 review 的 migration／初始化執行範圍包含 B6 的專案外正式庫 consistent copy／fresh DB 歷史驗證、Round10 synthetic fixture 的 pre-head／fresh／backup／fault／restore Temp 路徑、Round11 的專案外 JSON defaults／atomic regression，以及 Round27 對具名保存 baseline 的外部 0001→0006 replay 與兩個明確 fresh Alembic／fallback seed initialization subprocess；都不是正式 DB 寫入。R26 期間另有使用者 preview task 的舊 lifespan 實際改動正式 DB，已在 §1 記錄為外部狀態變化，不因此成為 R26 正式 migration 驗收。Round27 的保存與 startup acceptance 只涵蓋具名 saved-original／current／replay snapshots 及有限 readiness contract；它沒有正式 migration／restore／deployment，也不驗所有 historical／custom schema、非 SQLite、資料 truth 或 PIT。後續實作須按 [ROADMAP 執行清單](ROADMAP_EXECUTION.md) 獨立驗收，不能將文件、fixture、隔離升級、外部 startup 成功或 readiness 通過當作整體能力已完成。

Round19 已完成單日 `STOCK_DAY_ALL` selected-security 的有限內容驗證與 existing-consumer library opt-in；Round20 再完成單年度 `holidaySchedule` 的多日 positive request exclusion。Round21 通過既有 `tpex_spendi_today` code-only 停牌誤判修正；Round22 又只移除 `tpex_spendi_history` 的 `Serial` identity fallback；Round23 再只補唯一嚴格跨日 split pair 的 resume linkage；Round24 修 TPEx 公司行動的 ratio／reference 兩個 normalization slot，Round25 再只修同 consumer 的 cash precision／selection；Round26 只在 instrument detail 增加 TWSE action 的 read-only source classification。以上均已通過各自的有限 review。這些小批都沒有把 local capture time 升格為官方 first availability／PIT truth，也沒有新增公司行動或 `tpex_spendi_history` capture consumer、完整 legacy collector。Round21 的 reuse 不修舊 bar flag；Round22／23 都不刪舊錯 Event 或自動重算既存 evaluation，且 Round23 的不合格 shape 仍可能維持無界 suspension。Round24／25 也沒有 paid subscription、舊資料自動 repair 或 evaluation 自動 replay；Round26 不驗 raw-body membership／official identity，也不修既有 duplicate factor。公司行動完整 capture／PIT、完整停復牌、正式 cleanup、其他來源、正式 DB repair 與排程仍未接或未授權。
