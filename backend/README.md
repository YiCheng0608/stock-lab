# Backend

FastAPI、SQLAlchemy／SQLite，以及官方資料收集、回補、固定規則分析、指標批次、追蹤與回測。啟動、readiness 與 CLI 參數以[操作手冊](../docs/OPERATIONS.md)為準，能力邊界查[開發路線](../docs/ROADMAP.md)。

## 模組入口

| 路徑 | 職責 |
| --- | --- |
| app/main.py、app/browser_gate.py、app/api.py | 啟動 readiness、跨站寫入防護、產品 API、研究及診斷端點。 |
| app/config.py、app/models.py、app/db.py | 路徑與上限設定、資料模型與 SQLite session。 |
| app/database_readiness.py、app/migrations.py、app/migration_revisions.py、app/*_migration.py、app/news_json_defaults.py | 唯讀啟動檢查、revision chain 與 `init-db` 的 SQLite 遷移步驟。 |
| app/domain.py、app/decision.py、app/decision_market_reads.py、app/level_semantics.py | v1 規則與設定、eligibility、價位語意、行動摘要。 |
| app/indicators.py、app/stock_bars.py | 技術指標公式；個股日／週 K 線與指標 payload。 |
| app/taxonomy.py、app/coverage.py | 官方產業代碼 mapper；官方交易日 coverage。 |
| app/news.py、app/product_time.py、app/presentation.py、app/glossary.py | 官方事件投影成新聞、時間語意、中文呈現與詞彙。 |
| app/units.py、app/portfolio_quotes.py、app/portfolio_values.py | 張／股換算與持倉讀值。 |
| worker/sources.py、worker/pipeline.py | 官方 adapter／parser、raw、collect／analyze／evaluate／backtest／daily。 |
| worker/indicator_batch.py；worker/collect.py、daily.py、analyze.py、evaluate.py | 每日指標批次；單一步驟的命令入口。 |
| worker/backfill.py、worker/cli.py | 日期／scope 回補與 CLI。 |
| alembic/versions | Schema revisions；建庫與升級見[操作手冊](../docs/OPERATIONS.md#2-資料庫migration-與-readiness)。 |

本機檢查命令見[工作手冊](../docs/GITHUB_WORKFLOW.md#本機檢查)；依賴版本以 `validation-requirements.lock.txt` 為 constraints。
