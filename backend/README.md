# Backend

FastAPI、SQLAlchemy／SQLite，以及官方資料收集、回補、固定規則分析、追蹤與回測。啟動和 CLI 參數以[操作手冊](../docs/OPERATIONS.md)為準，能力與待辦查[開發路線](../docs/ROADMAP.md)。

## 模組入口

| 路徑 | 職責 |
| --- | --- |
| app/main.py、app/database_readiness.py、app/api.py | 啟動 readiness、產品 API、研究及診斷端點。 |
| app/models.py、app/db.py | 資料模型與 SQLite session。 |
| app/domain.py、app/decision.py | v1 規則、eligibility、價位／狀態、行動摘要。 |
| app/news.py、app/presentation.py、app/units.py | 官方事件投影、中文呈現與單位。 |
| worker/sources.py、worker/pipeline.py | 官方 adapter／parser、raw、collect／analyze／evaluate／backtest／daily。 |
| worker/backfill.py、worker/cli.py | 日期／scope 回補與 CLI。 |
| alembic/versions | Schema revisions；版本與相容範圍見 [R0 §8](../docs/R0_IMPLEMENTATION.md#8-r0-5migration-head-與實際-db-revision)。 |

API lifespan 只做唯讀 readiness，不相容即拒絕啟動；config import 執行 data／raw 目錄建立，資料變更 handlers 與 worker 有寫入入口。建庫／升級與路徑檢查依[操作手冊](../docs/OPERATIONS.md#2-資料庫migration-與-readiness)，不能把 startup 唯讀當成整個服務唯讀。

`daily`／`analyze` 仍有最新收集 run gate。新 ATR、artifact、comparison、replay 與 worker capture 的有限契約見[R0 實作](../docs/R0_IMPLEMENTATION.md)；它們不自動切換預設策略或完成 PIT。

驗證依[開發入口](../docs/development-baseline/README.md)。
