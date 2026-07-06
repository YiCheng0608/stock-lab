# Review：spec-3（PostgreSQL schema、models 與 Alembic 遷移）

## Rework re-review（2026-07-06，因 test-integration 發現的 ORM enum bug）

- reviewer：獨立對抗式 reviewer 子代理
- review depth：full（reopen 一律 full）
- verdict：**pass**
- 觸發原因：`test-integration`（真 Postgres e2e）發現 `backend/app/models/security.py` 的 `Enum(SecurityMarket, native_enum=True)` 未設 `values_callable`，預設以 enum name（`LISTED`/`OTC`）讀寫，但 migration 建的 Postgres enum type 為小寫 value（`listed`/`otc`），ORM 讀回 `Security` 列時拋 `LookupError`。`blame` 判定：此 bug 位於 spec-3 的 `allowed_outputs`（models），非本次觸發它的 spec-11。
- 修復：worker（tier medium）只改 `backend/app/models/security.py` 的 `market` 欄位定義，加上 `values_callable=lambda enum_cls: [e.value for e in enum_cls]`，未動 migration。worker 自行以真 Postgres 做過 round-trip 驗證（插入/讀回 `LISTED`/`OTC` 兩值皆過、`pg_enum` 確認 DB 端 label 未變）。
- reviewer 覆核重點：
  - 確認改動僅落在 `market` 欄位，其餘 `security.py` 內容（docstring、其他欄位、`SecurityMarket` 定義本身）未變。
  - 確認 migration 檔（`ade484fabe6f_initial_schema.py`）未被觸碰，且其 `sa.Enum("listed","otc",...)` 本就是 value-based DDL，不是 bug 來源。
  - 從 SQLAlchemy `Enum` 型別行為推導：`values_callable` 同時決定 bind（寫入）與 result（讀出）processor 用的 label 表，是雙向修復，不是只修一邊。
  - 全 repo grep `SecurityMarket` 用法：`pipeline.py` 與各 adapter 皆已是 value-based（小寫字串字面量或 `SecurityMarket(value)` 建構），未發現其他 name/value 不一致的殘留地雷；也沒有其他 model 檔用同樣的 `Enum(...)` pattern 而未修。
  - scope 檢查（因 worktree 無 commit 基準，改用 mtime 交叉比對）：spec-3 允許範圍外的檔案（adapters/notifications/ingestion/test 檔）mtime 皆早於本次改動時間，確認未被本次 rework 動到。
- 結論：修復正確、範圍收斂、未發現回歸或殘留同型 bug。

---

## 初次 review（spec-3 首次 produce）

- reviewer：獨立對抗式 reviewer 子代理
- review depth：full（risk: high）
- verdict：**pass**
- 驗證方式：**真 DB 實跑**（非靜態審查）。以 docker `postgres:16` 起一次性容器（port 55432），用本 worktree 既有 `backend/venv` 的 alembic，對空庫實跑 `alembic upgrade head` / `downgrade base` / 再 `upgrade head`，並直接以 `psql` 查系統目錄與做功能性 insert 驗證。

## 逐項 upgrade_triggers 檢查

| trigger | 結果 | 證據 |
|---|---|---|
| migration 無法套用 | **未命中** | `alembic upgrade head` EXIT=0；`downgrade base` EXIT=0（庫僅剩 `alembic_version`、enum type `security_market` 也被清為 0）；再 `upgrade head` EXIT=0（分區重新 37 個）。down/re-up 冪等，enum drop/recreate 路徑無殘留衝突。 |
| 分區缺 | **未命中** | `broker_branch_trades` relkind=`p`（原生分區表）；子分區 37 個（2025-01～2027-12 共 36 個月分區 ＋ 1 個 `_default`）；bound 正確（`FOR VALUES FROM ('2025-01-01') TO ('2025-02-01')` … / DEFAULT）。功能性：2026-05 資料落 `broker_branch_trades_2026_05`、範圍外 2030 資料落 `_default`。 |
| 索引/唯一鍵缺 | **未命中** | daily_prices `uq_daily_prices_security_date`(security_id,date)、chips `uq_chips_security_date`、corporate_actions `uq_corporate_actions_security_ex_date`、broker `uq_broker_branch_trades_security_branch_date`(security_id,broker_branch_code,date) 皆為 unique index，實查存在。broker PK=`(id,date)` 含分區鍵、業務去重鍵含 date，符合 PG 分區表約束。 |
| 雙價欄位缺 | **未命中** | daily_prices 同時有 `open/high/low/close_raw`（NOT NULL）與 `open/high/low/close_adj`（NULL，留給 spec-10 回填），實查欄位與 nullable 相符。 |
| user FK 缺 | **未命中（見下方判定）** | `users` 表存在，供未來自選股/策略掛載；全 schema 無任何表寫死 `user_id=1` 或單一使用者假設，符合 design.md §2 原則 2。 |
| outputs 越界 | **未命中** | spec-3 工作時窗（14:26–14:30）只動 `backend/app/models/*`（chip/corporate_action/daily_price/security/broker_branch_trade/__init__）與 `backend/alembic/*`（env.py、versions/、alembic.ini），全落在 allowed_outputs。`config.py`/`main.py`/`Dockerfile`/`pyproject.toml`（12:00–12:34）在 spec-3 時窗內未被改動。`models/user.py`、`models/base.py`（12:36）未被 spec-3 本輪改動。 |
| last_failure 非空 | 不適用 | 本次即產生此 review 訊號。 |

## FK 父子關係（design §3 pipeline 執行順序地基）

`daily_prices` / `chips` / `broker_branch_trades` / `corporate_actions` 對 `securities` 的 FK 均實建（分區表的 FK 亦下放到全部 37 個子分區）。功能性驗證：先插子表（security_id=999，無父列）被 FK 擋下並報 `daily_prices_security_id_fkey` 違反；先插 `securities` 再插子表成功。此即 spec-11 要求「pipeline 先灌 securities 再跑其他源」的資料庫層依據，成立。

## worker 自陳風險點的阻擋判定

1. **36 個月分區區間寫死 ＋ default 分區兜底**：未命中 trigger、**不阻擋**，但屬需追蹤的營運限制。已知 PostgreSQL 行為：一旦資料落進 default 分區覆蓋的日期範圍，日後要為該範圍新增月分區會失敗（除非 default 對該範圍為空，需 detach/搬列）。design §3 明示分點資料自上線日起「只增不減」持續累積，2028 起（超出 2027-12 窗口）新資料將靜默落 default，屆時補建分區會卡。建議：把「每月自動 roll 出下一批分區」交由 spec-11 排程器/營運腳本處理（非 spec-3 職責面）。spec-3 本身 migration 可套用、且錯落 default 不擋 upgrade，符合驗收。

2. **`*_adj`/籌碼欄位多為 nullable、無 CHECK**：**不阻擋**。`*_adj` NULL 為 intake 明訂（spec-10 回填）；籌碼三類欄位允許缺值反映來源實況。屬可接受的已知設計。

3. **corporate_actions 假設同股同除權息日僅一筆**：**不阻擋**。同一 `(security, ex_rights_date)` 單列同時容納現金股利、股票股利與股本變動欄位，符合台股「同日除權息合併於一事件」；除息日與除權日不同時則落不同列，唯一鍵可容。設計合理。

## 其他觀察（非阻擋）

- `alembic check` 會回報「Detected removed table `broker_branch_trades_YYYY_MM`」一類差異——此為宣告式分區的**已知假陽性**（Alembic 不把分區子表納入 ORM metadata）。已過濾確認：父表無任何真實 column/type/nullable/FK 漂移，ORM 與 migration 對父表一致。若日後啟用 autogenerate，需以 `include_object`/`include_name` 濾掉分區子表；本期為手寫 migration，不觸發此路徑。
- repo 內有一支 `backend/test_notifier_spec5.py`（notifier 相關，屬 spec-5 範疇），非 spec-3 產出、不歸此 review 判定。

## user FK 判定說明（對抗式覆核）

intake spec-3 完成定義有「掛 user 的表有 user_id FK」一句。本期實際**無任何 user-scoped 資料表**：securities/daily_prices/chips/broker_branch_trades/corporate_actions 皆為全市場共用資料，自選股/策略等 user-owned 功能屬 design §6 第一期第 2 項以後、需求已明確排除。因此本期正解正是：備妥 `users` 表作未來掛載點、且不在任何表寫死單一使用者——worker 的做法正確。若硬把 `user_id` FK 加到全市場資料表反而是正規化錯誤。此處 intake 措辭略有歧義（「FK 佔位」可被誤讀為要求一個實體 FK 欄），但 design §2 原則 2 的忠實度（不寫死單一 user）已達成，不構成阻擋。
