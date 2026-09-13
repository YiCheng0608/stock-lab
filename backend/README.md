# Backend

FastAPI、SQLAlchemy／SQLite，以及官方資料收集、回補、固定規則分析、追蹤與技術回測。現行策略與預測缺口見 [開發路線](../docs/ROADMAP.md)，完整命令見 [操作手冊](../docs/OPERATIONS.md)。

## 模組入口

| 路徑 | 職責 |
| --- | --- |
| app/main.py、app/database_readiness.py、app/api.py | 唯讀啟動 readiness、產品 API、研究及診斷端點。 |
| app/models.py、app/db.py | 資料模型、SQLite session。 |
| app/domain.py | Canonical v1 規則、eligibility、價位／狀態驗證。 |
| app/decision.py | 同標的策略／持倉／品質的行動摘要。 |
| app/news.py、app/presentation.py、app/units.py | 官方事件投影、中文呈現、股數單位。 |
| worker/sources.py | 官方 adapter、parser、原始回應保存。 |
| worker/pipeline.py | collect、analyze、evaluate、backtest、daily。 |
| worker/backfill.py、worker/cli.py | 日期／scope 回補與 CLI。 |
| alembic/versions | Schema revision，目前程式 head 為 0006_news_json_defaults。 |

目前 checkout 的 API lifespan 只以 SQLite `mode=ro`／`query_only` 做有限 readiness gate，不會初始化、升級或修復 DB；缺檔、空檔、不可讀、marker 或必要 mapped 結構不合時會拒絕啟動。建立／升級 schema 必須由操作者在核對 `STOCK_DATA_DIR`、`STOCK_DB_PATH`、`STOCK_RAW_DIR`、consistent backup 與授權後，明確執行 `python -m worker.cli init-db`。設定載入仍可能建立 data／raw 目錄，API request handlers 與 worker 也仍可能寫入，故不可把「startup 唯讀」擴大成整個服務唯讀。

## 目前與下一版

新聞詳情、來源時間欄位及排序、行動摘要、張／股與 backfill 已在程式可見，不再一律標為待新增。2026-09-11 文件輪只做文件及靜態核對，當次未重新驗收服務。Round27 的啟動邊界另通過 39 個獨立啟動案例與完整 backend 1,011 passed／1 個既有 Windows symlink privilege skip；但沒有重啟使用者既有服務，既有 process 可能仍載入先前版本。

CLI 包含 init-db、collect、daily、backfill、analyze、evaluate、backtest。collect／daily／backfill 市場資料使用官方來源；daily 與 analyze 仍有最新收集 run gate，不能把局部資料完整視為自動可執行。

ATR 的實作定義、固定 confidence=0.75、13:30 cutoff 與規則點位已記入待修正清單。新增媒體／國際新聞、分點行為、模型與交易計畫都是下一版工作，不能由 model 預留欄位認定已完成。

## 開發前閱讀

- [產品與合併契約](../docs/PRODUCT_SPEC.md)
- [策略／模型驗證](../docs/STRATEGIES.md)與 [v1 基準](../docs/V1_SPEC.md)
- [資料與歷史 coverage](../docs/DATA_SOURCES.md)
- [新聞契約](../docs/NEWS_SPEC.md)與 [UI 文案](../docs/UI_COPY_SPEC.md)

程式修改需相應測試。2026-09-11 文件輪只有文件修改，當次未執行 pytest、分析、收集或 migration。Round27 測試全部使用專案外資料路徑，沒有執行正式 DB migration／repair／restore、前端 build 或 UI 驗收；完整啟動契約、證據與限制見 [R0 §8.6](../docs/R0_IMPLEMENTATION.md#86-round27-api-startup-readiness有限-review)。
