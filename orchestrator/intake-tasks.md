# Intake 任務清單：stock-lab 第一期 Ingestion Pipeline

扁平清單。`spec-1` = intake（本規劃，不列入下游）。下游 worker 由 `spec-2` 起。每段自足；orchestrator 派工時只貼該段給 worker。

**全域約定（凡涉及者，各段已重述必要部分）**：後端在 `backend/` 子目錄，Python package 名 `app`；`docker-compose.yml` 在 repo 根。worker 只寫生產程式，**不得寫測試檔**（`*.test.*` / `*_test.py` / `tests/**` / fixtures 歸對應 test 節點）。對外網站格式不可重現，adapter 一律針對「傳入的回應字串/位元組」寫純解析函式，不在建置期打外網。

---

## spec-2: 專案骨架 ＋ Docker Compose

- 角色: worker
- 目的: 建 Python + FastAPI 專案骨架與 Docker Compose（postgres + fastapi + ingestion service），讓下游全部任務有可運行的地基。
- 輸入: design.md §4（技術棧）、§5（部署）；需求 requirement.md。
- 產出:
  - `backend/pyproject.toml`（依賴：fastapi、uvicorn、sqlalchemy、alembic、psycopg[binary]、apscheduler、httpx、pytest、pydantic-settings 等）
  - `backend/Dockerfile`
  - `docker-compose.yml`（repo 根；服務 postgres、api、ingestion；`restart: unless-stopped`；ingestion 服務 command 指向未來排程入口 `python -m app.ingestion.scheduler`）
  - `backend/app/__init__.py`、`backend/app/main.py`（FastAPI app，含 `GET /health`）
  - `backend/app/config.py`（pydantic-settings 讀 env：DB URL、通知 token 等）
  - `backend/.env.example`、`backend/app/core/__init__.py`
- depends_on: []
- allowed_outputs: ["backend/pyproject.toml", "backend/Dockerfile", "docker-compose.yml", "backend/app/__init__.py", "backend/app/main.py", "backend/app/config.py", "backend/.env.example", "backend/app/core/__init__.py", "backend/README.md"]
- forbid_outputs: ["backend/app/models/*", "backend/app/adapters/*", "backend/app/notifications/*", "backend/app/ingestion/*", "*_test.py", "*.test.*", "backend/tests/*"]
- requires_test: true
- tier: low
- worker 指示: 一律用 compose 內 postgres，不假設本機已裝 PG。ingestion service 的 command 直接寫成 `python -m app.ingestion.scheduler`（模組本身由 spec-11 實作，本任務不建該檔，只在 compose 引用路徑）。`main.py` 提供 `GET /health` 回 `{"status":"ok"}` 供 boot smoke。所有可變設定走 env（DB URL、TELEGRAM_BOT_TOKEN 等），寫進 `.env.example`。
- 完成定義: `docker compose config` 通過；`from app.main import app` 可匯入；對 app 用 FastAPI TestClient `GET /health` 得 200。
- 拆分理由: 基礎建置設定（infra config）ownership 與後續程式模組不同，且為所有下游依賴的根節點。

---

## spec-3: PostgreSQL schema、models 與 Alembic 遷移

- 角色: worker
- 目的: 定義全期資料模型並以 Alembic 遷移建表：user 概念、雙價格制、分點按月分區。
- 輸入: design.md §2 原則 2（不寫死單一 user）、§3（四類資料）、§4（PG 分區與索引）、§7（雙價格制）。上游 spec-2 已備好 pyproject（含 sqlalchemy/alembic）與 `app.config`。
- 產出:
  - `backend/app/models/**`（SQLAlchemy models）：
    - `users`（user 概念，自選股/策略日後掛此，本期至少一張表 + FK 佔位，不寫死單一 user）
    - `securities`（股票基本資料：代號、名稱、市場別〔上市/上櫃〕、股本等；為 `daily_prices`/`chips`/`broker_branch_trades` 的**父表**，見下方 FK）
    - `daily_prices`（原始 OHLCV **與**除權息還原欄位：如 `close_raw` / `close_adj` 或 `close` + `adj_factor`，需能重建還原線；**`security` 欄為 FK 關聯 `securities`**）
    - `chips`（三大法人買賣超、融資券餘額、借券賣出餘額；可一表多欄或分表，由 worker 依正規化判斷但需 (security, date) 唯一鍵；**`security` 欄為 FK 關聯 `securities`**）
    - `broker_branch_trades`（券商分點買賣日報表：security、broker_branch、date、買量、賣量；**按 date 月分區** ＋ **(security, broker_branch, date) 索引**；**`security` 欄為 FK 關聯 `securities`**）
    - `corporate_actions`（除權息事件：除權息日、配股配息、股本變動）
  - `backend/alembic.ini`、`backend/alembic/**`（env.py ＋ 建上述表/分區/索引的 migration）
- depends_on: [spec-2]
- allowed_outputs: ["backend/app/models/*", "backend/alembic.ini", "backend/alembic/*"]
- forbid_outputs: ["backend/app/adapters/*", "backend/app/notifications/*", "backend/app/ingestion/*", "*_test.py", "backend/tests/*"]
- requires_test: true
- tier: medium
- worker 指示: 分點表 `broker_branch_trades` **必須** PostgreSQL 原生按月分區（`PARTITION BY RANGE (date)`），並建 (security, broker_branch, date) 索引——用 Alembic migration 的 raw SQL 或對應 helper 完成，不能只在 ORM 標記。`daily_prices` 必須同時容納原始價與還原價（擇一表達：雙欄或 raw+adj_factor），還原值本期允許先為 NULL，由 spec-10 回填。所有掛使用者資料的表以 `user_id` FK 關聯 `users`，即使目前只有一筆 user 也不得寫死。**`daily_prices`/`chips`/`broker_branch_trades` 的 `security` 欄必須是 FK 關聯 `securities`**（`securities` 為父表，須先有該股票列才能插入這三表；此 FK 決定了 pipeline 的執行順序，見 spec-11）。用 Alembic 而非直接建表。
- 完成定義: 對一個空 PostgreSQL 跑 `alembic upgrade head` 成功；升級後可查得上述各表存在、`broker_branch_trades` 有月分區、(security, broker_branch, date) 索引存在、`daily_prices` 具原始與還原兩組價格欄位、掛 user 的表有 `user_id` FK、`daily_prices`/`chips`/`broker_branch_trades` 對 `securities` 的 `security` FK 存在。
- 拆分理由: 資料模型是跨全期的高風險地基（分區/雙價/user FK/索引一次到位），ownership（models + migrations）獨立，失敗成本高需獨立 full review。

---

## spec-4: Adapter 契約（DataSource / BrokerBranchSource / CaptchaSolver ABC）

- 角色: worker
- 目的: 定義所有資料源 adapter 實作的抽象契約，特別是 design 明列、供日後換 FinMind 的 `BrokerBranchSource` 縫。
- 輸入: design.md §2 原則 1（每源一 adapter）、§3（分點 `BrokerBranchSource` 未來替換）。
- 產出:
  - `backend/app/adapters/__init__.py`
  - `backend/app/adapters/base.py`：
    - `DataSource` ABC（抽象方法如 `fetch(target, date) -> raw`、`parse(raw) -> list[NormalizedRow]`；命名由 worker 定，但需讓「抓取」與「純解析」分離，解析可獨立測）
    - `BrokerBranchSource` ABC（繼承/獨立皆可；抽象化「取得某股某日分點資料」，讓自爬版與未來 FinMind 版可互換而不動下游）
    - `CaptchaSolver` ABC（抽象化驗證碼求解；供分點 adapter 注入，預設實作在 spec-8）
  - `backend/app/adapters/registry.py`（來源註冊/發現機制，供排程遍歷）：提供 `@register` 裝飾器（供各 adapter 在自己檔案內標註自身來源類別、自行註冊）＋ `discover()`（用 `pkgutil`/`importlib` 掃描 `adapters` 套件、import 各模組以觸發其 `@register`，回傳/填充已註冊來源）＋列舉已註冊來源的介面
- depends_on: [spec-2]
- allowed_outputs: ["backend/app/adapters/__init__.py", "backend/app/adapters/base.py", "backend/app/adapters/registry.py"]
- forbid_outputs: ["backend/app/adapters/daily_price.py", "backend/app/adapters/chips.py", "backend/app/adapters/broker_branch.py", "backend/app/adapters/corporate_actions.py", "backend/app/models/*", "backend/app/notifications/*", "*_test.py", "backend/tests/*"]
- worker 指示: 契約必須讓「抓取（碰網路）」與「解析（純函式）」分離，使解析可對固定樣本單元測試而不打外網。`BrokerBranchSource` 是 design 明列的未來 FinMind 替換縫——把驗證碼、節流、來源三者都抽象在介面後，換來源不動下游。只定義抽象與註冊機制，不實作任何具體來源。**registry 採「裝飾器自註冊 ＋ 掃描觸發」**：`@register` 供各 adapter 在自己檔內標註、`discover()` 用 `pkgutil`/`importlib` 掃 `adapters` 套件 import 觸發註冊。本任務完成時 adapter 尚不存在，故 registry 對空套件也要能正常運作（`discover()` 掃到零個來源不算錯）；**不得手動維護來源清單**（那會與尚未存在的 adapter 脫鉤、永遠為空）。
- 完成定義: 模組可匯入；ABC 未實作抽象方法時無法實體化（可被 `issubclass` / 抽象方法檢查驗證）；`@register` 裝飾器可將一個測試用假來源類別註冊進 registry 並被列舉到；`discover()` 對 `adapters` 套件可執行且回傳已註冊集合（此時具體 adapter 尚未存在，故**不要求列出任何真實來源**）。
- 拆分理由: 這是四個 adapter ＋ 排程共同依賴的介面縫（含 design 點名的 FinMind 替換點），設計錯誤高槓桿，ownership 獨立且需獨立 full review。
- requires_test: true
- tier: medium

---

## spec-5: 失敗通知 adapter（Notifier ABC ＋ log stub ＋ Telegram shell）

- 角色: worker
- 目的: 提供 ingestion 失敗告警的 adapter 介面與最小可用實作，讓排程可呼叫真實物件；Telegram 真推播內容不在本期。
- 輸入: design.md §5（失敗當天告警）、§8（Telegram bot，通知做成 adapter）。
- 產出:
  - `backend/app/notifications/__init__.py`
  - `backend/app/notifications/base.py`：`Notifier` ABC（如 `notify(subject, message) -> None`）
  - `backend/app/notifications/log_notifier.py`：最小可用 stub（寫入 log / stdout，永不失敗，供本期預設）
  - `backend/app/notifications/telegram_notifier.py`：Telegram adapter **shell**（讀 `TELEGRAM_BOT_TOKEN` env、實作 `Notifier` 介面，但本期不驗真推播；無 token 時降級為 no-op 並記 log）
- depends_on: [spec-2]
- allowed_outputs: ["backend/app/notifications/__init__.py", "backend/app/notifications/base.py", "backend/app/notifications/log_notifier.py", "backend/app/notifications/telegram_notifier.py"]
- forbid_outputs: ["backend/app/adapters/*", "backend/app/models/*", "backend/app/ingestion/*", "*_test.py", "backend/tests/*"]
- requires_test: true
- tier: low
- worker 指示: `Notifier` 介面要留得住日後 LINE Messaging API / email（別把 Telegram 專屬概念寫進 ABC）。log stub 是本期預設通知器、必須永不拋例外。Telegram shell 讀 env token、實作介面，但**不真的送出**、不在測試/建置期打 Telegram API；缺 token 時 no-op。design §8 註記 LINE Notify 已於 2025-03 終止，勿參考。
- 完成定義: 三個類別可匯入；`LogNotifier().notify(...)` 不拋例外並可觀察到輸出；`TelegramNotifier` 是 `Notifier` 子類、無 token 時 `notify` 不拋例外亦不發網路請求。
- 拆分理由: 通知是與資料源正交的獨立模組 ownership，且下游只有排程消費（非 adapter），低風險可獨立收斂。

---

## spec-6: 日價量 adapter（K 線）

- 角色: worker
- 目的: 從證交所/櫃買官方 OpenAPI 與每日收盤行情擷取日 OHLCV，正規化為 `daily_prices` 的**原始價**列。
- 輸入: design.md §3（日價量來源、歷史可整批回補）、§7（本 adapter 只落原始價，還原價由 spec-10 算）。上游：spec-4 的 `DataSource` 契約、spec-3 的 `daily_prices` model。
- 產出: `backend/app/adapters/daily_price.py`（實作 `DataSource`：抓取函式 ＋ **純解析函式** `parse(raw) -> list[正規化列]`；支援單日與 date range 回補入參）
- depends_on: [spec-3, spec-4]
- allowed_outputs: ["backend/app/adapters/daily_price.py"]
- forbid_outputs: ["backend/app/adapters/chips.py", "backend/app/adapters/broker_branch.py", "backend/app/adapters/corporate_actions.py", "backend/app/models/*", "*_test.py", "backend/tests/*"]
- requires_test: true
- tier: medium
- worker 指示: 抓取（碰網路）與解析（純函式）必須分離；解析函式吃「已取得的回應字串/位元組」回正規化列，**不得在解析路徑打外網**。**市場覆蓋（Q10 已按建議定案）：本期同時支援上市（證交所）與上櫃（櫃買）兩市場**；兩市場頁面/端點格式若不同，於本檔內以各自的純解析函式表達（同一 adapter、多個 parse 函式），正規化到同一 `daily_prices`。只落**原始價**到 `daily_prices`（還原欄位留給 spec-10）。支援 date range 入參以備十年回補（實際回補是營運任務、不阻塞驗收）。若端點需金鑰則走 env、缺金鑰標記該源 skip 而非 crash。本 adapter 需在自己檔案內用 spec-4 registry 的 `@register` 裝飾器自行註冊（import registry 做註冊仍在本檔範圍內，不碰 spec-4 檔案）。
- 完成定義: 對上市與上櫃兩市場各一段固定樣本回應（由 test 節點提供 fixture），對應解析函式輸出預期的正規化 OHLCV 列（欄位、型別、日期、代號正確）。
- 拆分理由: 獨立 adapter 模組、獨立目標欄位、獨立來源格式與 fixture，失敗根因與其他源不同，可平行。

---

## spec-7: 籌碼 adapter（三大法人 / 融資券 / 借券）

- 角色: worker
- 目的: 從證交所/櫃買每日統計擷取三大法人買賣超、融資券餘額、借券賣出餘額，正規化入 `chips`。
- 輸入: design.md §3（籌碼來源、穩定好爬）。上游：spec-4 的 `DataSource` 契約、spec-3 的 `chips` model。
- 產出: `backend/app/adapters/chips.py`（實作 `DataSource`：抓取 ＋ 純解析；涵蓋三大法人、融資券、借券三類每日數據，正規化為 (security, date) 為鍵的列）
- depends_on: [spec-3, spec-4, spec-12]
- allowed_outputs: ["backend/app/adapters/chips.py"]
- forbid_outputs: ["backend/app/adapters/daily_price.py", "backend/app/adapters/broker_branch.py", "backend/app/adapters/corporate_actions.py", "backend/app/models/*", "*_test.py", "backend/tests/*"]
- requires_test: true
- tier: medium
- worker 指示: 抓取與解析分離，解析為純函式、不打外網。**資料集覆蓋：本期三類籌碼齊做**——三大法人買賣超、融資券餘額、借券賣出餘額，皆對應 `chips` 的欄位、以 (security, date) 為唯一鍵正規化（三套來源頁面各自一個 parse 純函式，同一 adapter 內表達）。**市場覆蓋（Q10 已定案）：上市（證交所）與上櫃（櫃買）兩市場都做**；兩市場格式若不同則各自 parse 函式。若某端點需金鑰走 env、缺則 skip 該源。若本期籌碼頁需 HTML 解析，`beautifulsoup4`/`lxml` 已由 spec-12 於 pyproject 備妥（故本節點 `depends_on` 含 spec-12）；本節點只 import，**不得改 `backend/pyproject.toml`**。本 adapter 需在自己檔案內用 spec-4 registry 的 `@register` 裝飾器自行註冊。
- 完成定義: 對三類籌碼、兩市場的固定樣本回應（test 節點提供 fixture），各解析函式輸出預期的正規化列，鍵與數值正確。
- 拆分理由: 獨立 adapter 模組與獨立目標表，來源格式與 fixture 不同於其他源，可平行。

---

## spec-8: 券商分點 adapter（買賣日報表，自爬 ＋ 節流 ＋ 驗證碼）

- 角色: worker
- 目的: 從 `bsr.twse.com.tw`（上市）與櫃買對應頁自爬券商分點買賣日報表，正規化入 `broker_branch_trades`；實作 `BrokerBranchSource` 讓日後可換 FinMind。
- 輸入: design.md §3（分點注意事項：只能抓當日、需節流、帶驗證碼、社群有成熟 OCR、FinMind 為未來選配）、§11（維運熱點）。上游：spec-4 的 `BrokerBranchSource` / `CaptchaSolver` 契約、spec-3 的 `broker_branch_trades` model。開放問題 Q1（OCR 建議 ddddocr）、Q2（分點 universe 為子集）、Q5（節流間隔可設定）已按建議排入。
- 產出: `backend/app/adapters/broker_branch.py`（實作 `BrokerBranchSource`：抓取單股單日多頁 ＋ 純解析函式 ＋ 節流器 ＋ 注入式 `CaptchaSolver`（預設 ddddocr 實作）＋ 可設定的抓取 universe）
- depends_on: [spec-3, spec-4, spec-12]
- allowed_outputs: ["backend/app/adapters/broker_branch.py"]
- forbid_outputs: ["backend/app/adapters/daily_price.py", "backend/app/adapters/chips.py", "backend/app/adapters/corporate_actions.py", "backend/app/models/*", "*_test.py", "backend/tests/*"]
- requires_test: true
- tier: high
- worker 指示: 抓取路徑碰網路、驗證碼、節流；**解析為純函式**（吃已取得的分點頁 HTML → 正規化 (security, broker_branch, date, 買量, 賣量) 列），可獨立單元測試。**市場覆蓋（Q10 已定案）：上市（`bsr.twse.com.tw`）與上櫃（櫃買對應頁）兩市場都做**；兩市場頁面格式若不同則各自 parse 純函式，同一 adapter 內表達。節流採保守單線程 ＋ 每檔間隔可設定（預設 3–5s）。驗證碼透過注入的 `CaptchaSolver`（預設 ddddocr），介面化以便日後替換；驗證碼求解與真外站抓取**不列入機器驗收必要條件**。`ddddocr` 依賴已由 spec-12 於 pyproject 增列（故本節點 `depends_on` 含 spec-12），本節點只 import、**不得改 `backend/pyproject.toml`**。整支 adapter 實作 `BrokerBranchSource`，使日後 FinMind 版可整段替換不動下游。分點 universe（每日抓哪些股）可設定，預設「**成交量前 N（可設定）**」子集（本期無自選股表，勿引用；見 Q2）。**只抓當日**（官方不提供歷史，錯過即缺洞）。本 adapter 需在自己檔案內用 spec-4 registry 的 `@register` 裝飾器自行註冊。
- 完成定義: 對固定樣本分點頁 HTML（test 節點提供 fixture），解析函式輸出預期的正規化分點列；節流器可用 mock 時鐘驗證請求間隔 ≥ 設定值；`CaptchaSolver` 為可注入介面（測試可注入假 solver）。真外站抓取與真驗證碼辨識不在驗收內。
- 拆分理由: 全案最高維運風險與最複雜實作（驗證碼/節流/改版/FinMind 縫），獨立 ownership 與 fixture，須獨立 full review 與風險隔離。

---

## spec-9: 除權息 / 股本 / 基本資料 adapter（公開資訊觀測站）

- 角色: worker
- 目的: 從公開資訊觀測站擷取除權息事件、股本變動、股票基本資料，正規化入 `corporate_actions` 與 `securities`。
- 輸入: design.md §3（公開資訊觀測站，格式雜但好爬）、§7（除權息事件供還原係數計算）。上游：spec-4 的 `DataSource` 契約、spec-3 的 `corporate_actions` / `securities` model。
- 產出: `backend/app/adapters/corporate_actions.py`（實作 `DataSource`：抓取 ＋ 純解析；輸出除權息事件（除權息日、配股/配息）、股本變動、基本資料）
- depends_on: [spec-3, spec-4, spec-12]
- allowed_outputs: ["backend/app/adapters/corporate_actions.py"]
- forbid_outputs: ["backend/app/adapters/daily_price.py", "backend/app/adapters/chips.py", "backend/app/adapters/broker_branch.py", "backend/app/models/*", "*_test.py", "backend/tests/*"]
- requires_test: true
- tier: medium
- worker 指示: 抓取與解析分離，解析為純函式、不打外網。**資料集覆蓋：本期三套頁面齊做**——除權息事件、股本變動、股票基本資料（三套來源頁面各自一個 parse 純函式，同一 adapter 內表達）。除權息事件的欄位需**足以讓 spec-10 計算還原係數**（至少：除權息日、每股配息、每股配股/無償配股率）。基本資料落 `securities`（含市場別上市/上櫃）、除權息與股本變動落 `corporate_actions`。解析所需的 HTML/XML 套件（`beautifulsoup4`/`lxml`）已由 spec-12 於 pyproject 增列（故本節點 `depends_on` 含 spec-12），本節點直接 import、**不得改 `backend/pyproject.toml`**。**市場覆蓋（Q10 已定案）：上市與上櫃兩市場的證券都要落地 `securities`**（`securities` 是其他表的 FK 父表，覆蓋不全會使其他源該股票插入失敗，見 spec-11 執行順序）。本 adapter 需在自己檔案內用 spec-4 registry 的 `@register` 裝飾器自行註冊。
- 完成定義: 對三套頁面（除權息/股本/基本資料）、涵蓋上市與上櫃的固定樣本回應（test 節點提供 fixture），各解析函式輸出預期的正規化列，欄位足以支撐還原係數計算。
- 拆分理由: 獨立 adapter 模組與目標表，來源格式與 fixture 不同；與「還原係數計算」失敗根因不同（解析 vs 數學），故與 spec-10 分開。

---

## spec-10: 除權息還原價計算

- 角色: worker
- 目的: 依 `corporate_actions` 的除權息事件自算還原係數，回填 `daily_prices` 的還原價欄位（技術指標/篩選/回測日後一律用還原價）。
- 輸入: design.md §7（雙價格制、還原係數自算、指標與回測用還原價、六到九月除息旺季不還原會假訊號）。上游：spec-3 的 `daily_prices`（原始價已由 spec-6 落地）與 `corporate_actions`（由 spec-9 落地）model 與語意。
- 產出: `backend/app/pricing/adjustment.py`（純計算模組：吃某股的原始日價序列 ＋ 除權息事件序列 → 計算各日還原係數並回填還原價；不碰網路、不碰爬蟲）
- depends_on: [spec-3, spec-9]
- allowed_outputs: ["backend/app/pricing/__init__.py", "backend/app/pricing/adjustment.py"]
- forbid_outputs: ["backend/app/adapters/*", "backend/app/models/*", "backend/app/ingestion/*", "*_test.py", "backend/tests/*"]
- requires_test: true
- tier: high
- worker 指示: 這是**純數學**：給定原始價序列與除權息事件（除息配息、除權配股），把還原係數往前串接算出各日還原價。是全期正確性熱點（design §7 點名六到九月除息旺季不還原會假訊號淹沒）。以可測純函式表達，輸入輸出明確；不打外網、不寫爬蟲、不改 model 定義（只回填值）。
- 完成定義: 對「已知除權息事件 ＋ 原始價序列」的樣本（test 節點提供），輸出的還原係數與還原價序列等於人工核算的預期值（含跨多次除權息的連乘、除息與除權混合情境）。
- 拆分理由: 與除權息**抓取**（spec-9）失敗根因不同（數學 vs 解析），fixture 與 review 重點不同；correctness 高風險須獨立 full review。

---

## spec-11: APScheduler 排程協調器

- 角色: worker
- 目的: 用 APScheduler 每日傍晚起、每小時重試直到成功地串接各 adapter 與還原計算，記錄各源當日成功狀態，失敗時觸發通知。
- 輸入: design.md §5（APScheduler、不依賴 OS 排程器、每日傍晚起每小時重試直到成功、失敗當天告警）、§3（分點錯過即永久缺洞故需重試）。上游：spec-4 registry、spec-5 Notifier、spec-6/7/8/9 adapter、spec-10 還原計算。
- 產出:
  - `backend/app/ingestion/__init__.py`
  - `backend/app/ingestion/pipeline.py`（一次 run：遍歷各源→抓取→入庫→算還原價；回報各源成功/失敗）
  - `backend/app/ingestion/scheduler.py`（APScheduler 進入點，即 spec-2 compose ingestion service 的 `python -m app.ingestion.scheduler`；每日傍晚排程 ＋ 每小時重試未成功源直到全綠 ＋ 失敗經 Notifier 告警）
- depends_on: [spec-4, spec-5, spec-6, spec-7, spec-8, spec-9, spec-10]
- allowed_outputs: ["backend/app/ingestion/__init__.py", "backend/app/ingestion/pipeline.py", "backend/app/ingestion/scheduler.py"]
- forbid_outputs: ["backend/app/adapters/*", "backend/app/notifications/*", "backend/app/models/*", "backend/app/pricing/*", "docker-compose.yml", "*_test.py", "backend/tests/*"]
- requires_test: true
- tier: high
- worker 指示: 用 spec-4 registry 的 `discover()` 取得各來源（不手動維護清單）。**執行順序（FK 約束）：pipeline 每次 run 必須先跑 spec-9 對應的除權息/股本/基本資料源、把 `securities` 灌好，再跑其他源**（`daily_prices`/`chips`/`broker_branch_trades` 對 `securities` 有 FK，父表列不存在會插入失敗）。此為 pipeline 執行層順序，不在 depends_on 圖表達（adapter 解析層彼此無依賴）。**還原價步驟語意（雙價格制）：算還原價時必須對每檔股票餵入其整段歷史日價序列並重寫全部還原列，而非只對當日新到的列算還原**——因為一筆新的除權息事件會回溯改寫該股全部歷史還原價（spec-10 純函式簽名已容得下整段序列輸入，pipeline 端要以整段序列呼叫、回填全歷史）。重試語意是風險核心——「每小時重試**直到成功**」意味只重試**當日尚未成功的源**、成功的不重抓；全部成功才停當日排程。**時區與重試截止**：排程時間以 **Asia/Taipei** 計（「傍晚」為台北時間）；當日每小時重試至當日 23:59（Asia/Taipei）截止，跨日即視為新的一輪（隔天的排程從頭起算，不無限累積前一日未成功源）。失敗要經 Notifier（spec-5）告警。時鐘/排程觸發需可注入或可 mock，讓重試邏輯能用可控時鐘單元測試（不真的等一小時）。不得改 `docker-compose.yml`（compose 已由 spec-2 指向本模組入口）。分點錯過即永久缺洞，重試邏輯要對此特性穩健。
- 完成定義: 以 mock 時鐘 ＋ mock adapter（部分先失敗後成功）驗證：未成功源會於下一小時重試、成功源不重抓、全綠後停止當日、任一源失敗時 Notifier 被呼叫；並驗證 pipeline 先跑 securities 源再跑依賴 FK 的源、還原價步驟以整段歷史序列回填。
- 拆分理由: 依賴全部下游、承載高風險重試語意，ownership 獨立（排程模組），須獨立 full review。

---

## spec-12: 依賴清單擴充（ddddocr 驗證碼 ＋ beautifulsoup4/lxml HTML/XML 解析）

- 角色: worker
- 目的: 在 spec-2 已建立的 `backend/pyproject.toml` 依賴清單上，補進骨架未含、但下游平行 adapter 需要的三個第三方套件——`ddddocr`（spec-8 券商分點驗證碼辨識，Q1 決議）、`beautifulsoup4` 與 `lxml`（spec-9 公開資訊觀測站「格式雜」HTML/XML 解析，spec-7 籌碼頁備援）。由本節點**單一擁有** pyproject 的依賴寫入權，讓需要新依賴的平行 adapter 節點不必各自搶寫同一檔。
- 輸入: Q1（OCR 選 ddddocr）決議；spec-9 worker 指示（HTML/XML 解析需求）；spec-2 已產出的 `backend/pyproject.toml`。
- 產出: `backend/pyproject.toml`（**僅**在既有依賴清單新增 `ddddocr`、`beautifulsoup4`、`lxml`；不改動 spec-2 已寫的專案 metadata、build 設定、既有依賴或工具設定）
- depends_on: [spec-2]
- allowed_outputs: ["backend/pyproject.toml"]
- forbid_outputs: ["backend/Dockerfile", "docker-compose.yml", "backend/app/__init__.py", "backend/app/main.py", "backend/app/config.py", "backend/.env.example", "backend/app/core/*", "backend/app/models/*", "backend/app/adapters/*", "backend/app/notifications/*", "backend/app/ingestion/*", "backend/app/pricing/*", "backend/alembic.ini", "backend/alembic/*", "*_test.py", "*.test.*", "backend/tests/*"]
- requires_test: true
- tier: low
- worker 指示: 只動 pyproject 的依賴清單（`[project].dependencies`；若採 optional 群組亦可但需被主安裝路徑涵蓋），新增 `ddddocr`、`beautifulsoup4`、`lxml` 三者。**不得刪改 spec-2 已寫的任何其他行**（fastapi/uvicorn/sqlalchemy/… 既有依賴與 build/tool/metadata 區段）；此節點唯一職責是「增列依賴」。版本約束用寬鬆下限或不釘死，交由 lockfile / preflight 解析。不新增任何程式模組、不碰 adapter/model/notifications/ingestion/compose。`ddddocr` 會連帶拉入 onnxruntime 等較重依賴，屬預期，不需為此改動其他檔。
- 完成定義: `backend/pyproject.toml` 以 tomllib 解析成功；依賴清單含 `ddddocr`、`beautifulsoup4`、`lxml`；spec-2 原有依賴與其他區段原封未動（diff 僅新增依賴行）；preflight 安裝後 `import ddddocr`、`import bs4`、`import lxml` 皆成功。
- 拆分理由: 依賴清單寫入權原被 spec-2 的 `allowed_outputs` 獨占鎖住，但 spec-8（必需 ddddocr）與 spec-9（必需 HTML/XML 解析）是彼此平行的 adapter，無合法路徑加依賴；若讓兩個平行節點各自取得 pyproject 寫入權會撞寫同一檔、破壞平行安全。集中成單一序列化擁有者（`depends_on: [spec-2]`、下游需依賴者接於其後）可補此缺口，又保住「任兩個可平行節點不同時持有 pyproject 寫入權」。

---

## Test 節點（machine 驗收；fixture 與測試檔歸此，不歸 worker spec）

以下為建議 test 節點；orchestrator 依 verification map 建立。每個 test 節點負責撰寫並執行對應驗收，含所需 fixture。

- **test-2** verifies spec-2 — kind: smoke；`docker compose config` 通過 ＋ FastAPI TestClient `GET /health`=200。
- **test-3** verifies spec-3 — kind: integration（需 PG）；`alembic upgrade head` ＋ 斷言表/月分區/索引/雙價欄位/user FK/`daily_prices`·`chips`·`broker_branch_trades` 對 `securities` 的 FK。depends_on: test-2。
- **test-4** verifies spec-4 — kind: unit；ABC 抽象方法強制；registry 的 `@register` 可註冊一個假來源並被列舉、`discover()` 對 `adapters` 套件可執行（此時無真實 adapter，故驗機制而非真實來源清單）。
- **test-5** verifies spec-5 — kind: unit；三通知器可匯入、log stub 不拋、Telegram shell 無 token 不打網路。
- **test-6** verifies spec-6 — kind: unit；含 daily price 樣本 fixture，驗解析輸出正規化 OHLCV。
- **test-7** verifies spec-7 — kind: unit；含籌碼樣本 fixture，驗三類籌碼解析。
- **test-8** verifies spec-8 — kind: unit；含分點頁 HTML fixture ＋ mock 時鐘 ＋ 假 CaptchaSolver，驗解析與節流間隔。**不含真外站/真驗證碼**。
- **test-9** verifies spec-9 — kind: unit；含公開資訊觀測站樣本 fixture，驗除權息/股本/基本資料解析。
- **test-10** verifies spec-10 — kind: unit；已知除權息事件 ＋ 原始價序列 → 驗還原係數/還原價（含連乘、除息除權混合）。
- **test-11** verifies spec-11 — kind: unit；mock 時鐘 ＋ mock adapter，驗每小時重試直到成功、成功不重抓、失敗觸發通知。
- **test-12** verifies spec-12 — kind: smoke/unit；`backend/pyproject.toml` 以 tomllib 解析成功、依賴清單含 `ddddocr`/`beautifulsoup4`/`lxml`、spec-2 原有依賴與其他區段未被刪改；preflight 安裝後 `import ddddocr`、`import bs4`、`import lxml` 成功。depends_on: test-2。
- **test-integration** verifies [spec-11 及其上游端到端] — kind: integration/e2e（需 PG）；以 fixture-backed adapter 灌進真 postgres，斷言各表有資料、securities 先落地使依 FK 的表插入成功、還原價已算（整段序列回填）、模擬某源失敗會重試並觸發通知。depends_on: test-3, test-11。**不打外網**（需 docker daemon，見 Q11；無 daemon 時依 Q11 降級標記 blocked）。
