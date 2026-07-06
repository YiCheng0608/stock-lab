# spec-11 full re-review

verdict: pass
fix_target: none

## 審查輸入

- 需求原文：`orchestrator/requirement.md`
- 任務切片：`orchestrator/intake-tasks.md` 的 `spec-11`
- 驗證地圖：`orchestrator/intake-verification-map.md` 的 `spec-11`
- review map：`orchestrator/intake-review-map.md` 的 `spec-11`
- 前次紀錄：`orchestrator/review-spec-11.md`
- 實作檔：`backend/app/ingestion/pipeline.py`、`backend/app/ingestion/scheduler.py`、`backend/app/ingestion/__init__.py`
- 契約抽查：`backend/app/adapters/registry.py`、`backend/app/adapters/broker_branch.py`、`backend/app/models/*`、`backend/app/pricing/adjustment.py`

## 對抗式結論

前次三個阻斷點已修補，且沒有在本次指定檔案內看到新的 spec-11 阻斷缺口。production entrypoint 會組裝 SQLAlchemy repository；broker branch 預設 target 會走上市/上櫃 universe 並在空集合時變成 source failure；還原價重算會從 DB 讀全量 daily price history 與 corporate actions，再回寫同一檔股票完整歷史的 adjusted 欄位。

## 前次阻斷點複查

### F1：broker_branch 空 universe 假成功

已修補。

- `Pipeline.default_target_provider()` 對 `broker_branch` / `broker` source 改呼叫 `_broker_branch_targets()`。
- `_broker_branch_targets()` 要求 source 必須提供 `resolve_universe()`，並固定對 `listed`、`otc` 兩市場各取 universe。
- 兩市場合併後若仍為空，會 raise `ValueError`；`Pipeline._run_source()` 捕捉後回 `SourceRunResult(success=False, error=...)`。
- `IngestionCoordinator._notify_failures()` 會對 failed source 發通知，且 notifier exception 被 `_safe_notify()` 隔離。

因此預設 production pipeline 不會再把 broker branch 空 target 當成成功 0 筆。

### F2：scheduler production path 使用 InMemory

已修補。

- `scheduler.main()` 現在建立 `IngestionCoordinator(create_production_pipeline(), _default_notifier())`。
- `create_production_pipeline()` 使用 `create_sqlalchemy_repository()`，不再是裸 `Pipeline()`。
- `create_sqlalchemy_repository()` 從 `app.config.get_settings().database_url` 或環境 fallback 建 engine/sessionmaker，並注入 `SQLAlchemyIngestionRepository`。
- `backend/app/ingestion/__init__.py` 有匯出 `SQLAlchemyIngestionRepository`、`create_sqlalchemy_repository`、`create_production_pipeline`。

production compose entrypoint `python -m app.ingestion.scheduler` 會走持久化 repository，而非 process memory。

### F3：production 無完整歷史序列回填

已修補。

- `SQLAlchemyIngestionRepository.list_price_series()` 讀取所有 `DailyPrice`，依 `security_id` 分組並依日期排序，提供完整 daily price history。
- `SQLAlchemyIngestionRepository.list_corporate_actions(security_key)` 讀取該 security 的所有 `CorporateAction`，依 `ex_rights_date` 排序。
- `Pipeline.recalculate_adjusted_prices()` 對每個完整 price series 呼叫 `fill_adjusted_prices(prices, actions)`。
- `SQLAlchemyIngestionRepository.replace_adjusted_prices()` 重新查該 security 全部 `DailyPrice`，依日期把 `open_adj/high_adj/low_adj/close_adj` 回填。

這滿足「不是只算當日新列，而是依完整歷史序列回填 adjusted prices」的 spec-11 語意。

## SQLAlchemy repository 寫入覆蓋

`SQLAlchemyIngestionRepository.write_rows()` 會依 row kind 分派到以下 upsert：

- `securities`：`_upsert_security()` 寫 `symbol/name/market/outstanding_shares/is_active`。
- `daily_prices`：`_upsert_daily_price()` 以既有 `Security` FK 寫 `date/open_raw/high_raw/low_raw/close_raw/volume`。
- `chips`：`_upsert_chip()` 以既有 `Security` FK 寫三大法人、融資券、借券欄位。
- `broker_branch_trades`：`_upsert_broker_branch()` 以既有 `Security` FK、分點代號、日期 upsert 買賣量。
- `corporate_actions`：`_upsert_corporate_action()` 以既有 `Security` FK、除權息日 upsert 配息、配股、股本變動欄位。

`_row_write_order()` 會把 `row_type == "security"` 排在同批 rows 前面，使 MOPS 同批輸出的 securities 先落地，再寫 corporate action；dependent rows 找不到 parent security 時會明確 fail，不會靜默略過 FK 問題。

## 原通過項目回歸

- registry 使用仍成立：`Pipeline` 預設 `discover=registry.discover`，未手寫 adapter 清單。
- source ordering 仍先跑 security/corporate 類 source，再跑 daily/chips/broker 類 source。
- 成功源不重抓、未成功源重試仍成立：coordinator 保存當日 `succeeded_sources`，下一輪只傳 pending source。
- 全綠停止仍成立：所有 source succeeded 且 adjustment succeeded 後 `state.all_green=True`，後續 trigger 回 `None`。
- 跨日新輪仍成立：Taipei date 改變時建立新的 `DailyIngestionState`。
- cutoff 仍成立：預設 23:59 後停止觸發。
- notifier 隔離仍成立：通知失敗只記 log，不破壞 retry path。
- 可注入 mock 仍成立：pipeline 可注入 sources/discover/repository/sink/target_provider/adjustment_writer；scheduler 可注入 clock/notifier/scheduler_factory。

## 剩餘非阻斷風險

- `IngestionCoordinator` 仍直接呼叫 `Pipeline._ordered_sources()`，屬 private method 耦合；這是維護性風險，不影響本次 spec-11 驗收。
- 本次為 reviewer 靜態重審，未取代 `test-11` 或 integration test 的實跑證據；機器驗證仍應由後續 test 節點負責。

## reason

前次 F1/F2/F3 的 production 路徑缺口已補齊，且原有重試、通知、registry discover、mock 注入與全歷史還原價語意仍成立。
