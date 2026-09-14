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
| alembic/versions | Schema revisions；目前程式 head 為 0006_news_json_defaults。 |

API lifespan 只做有限唯讀 readiness；缺檔、版本或必要結構不合時拒絕啟動。建庫／升級須明確執行 `python -m worker.cli init-db`，並先確認三個 `STOCK_*` 路徑、備份及授權。設定載入可能建立目錄，API handlers 與 worker 仍可能寫入，不能把 startup 唯讀當成整個服務唯讀。

`daily`／`analyze` 仍有最新收集 run gate。新 ATR、artifact、comparison、replay 與 worker capture 的有限契約見[R0 實作](../docs/R0_IMPLEMENTATION.md)；它們不自動切換預設策略或完成 PIT。

驗證依[開發入口](../docs/development-baseline/README.md)與[AGENTS](../AGENTS.md)，不在此重複累積歷史測試筆數。
