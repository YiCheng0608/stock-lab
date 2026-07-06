# Review: spec-6 日價量 adapter（K 線）

## Rework re-review（2026-07-06，spec-3 enum 修復觸發的級聯重驗）

- verdict：**pass**
- 觸發原因：spec-3 為修另一個 bug（`Security.market` 的 SQLAlchemy `Enum` 加 `values_callable`）被引擎級聯重置為 pending，非本檔本身有問題。
- 覆核結果：`daily_price.py` 全檔 grep `app.models`/`SecurityMarket` 零命中；`parse_twse`/`parse_tpex` 寫入的 market 欄位本就是小寫字面值 `"listed"`/`"otc"`，與修復後的 enum `.value` 一致（修復前也不影響，因為本檔從未經過 ORM enum 層）。`registry.discover()` 確認 `daily_price_twse`/`daily_price_tpex` 皆正常註冊。spec-6 完成定義（雙市場解析、抓取/解析分離、date range 回補、自註冊）逐項重新核對仍成立。無需改動，原樣記回 verified。

- 角色：reviewer，focused review。
- 對抗式 framing：假設 adapter 已上線後造成日價量缺漏、欄位對不上、registry 掃不到、或解析 fixture 失敗，反推本次產物是否有這些失效方式。
- 審查基準：`orchestrator/requirement.md`、`orchestrator/intake-tasks.md` 的 spec-6、`orchestrator/intake-verification-map.md` 的 spec-6、`orchestrator/intake-review-map.md` 的 spec-6。
- 審查對象：`backend/app/adapters/daily_price.py`，並對照上游契約 `backend/app/adapters/base.py`、`backend/app/adapters/registry.py`。

## Verdict: **pass**

`daily_price.py` 同時提供 TWSE 上市與 TPEx 上櫃來源，抓取與解析路徑分離，解析函式只吃 raw JSON dict / string / bytes 並回傳正規化 raw OHLCV；兩個 `DataSource` 子類別都以 `@register` 自註冊。未看到把除權息還原價邏輯塞進本 adapter 的行為，也未看到明顯會讓 spec-6 fixture 測試因欄位、型別、日期或市場代號而失敗的問題。

## Focused 檢查

| 檢查點 | 結果 | 依據 |
|---|---|---|
| 只修改 / 產出 `backend/app/adapters/daily_price.py` | **未命中阻斷；但 scope 證據有限** | `git diff -- backend/app/adapters/daily_price.py` 無輸出，因該檔目前是 untracked，無法用指定 diff 觀察新增內容。`git status --short` 顯示整個 `backend/` / `orchestrator/` 仍是未追蹤脈絡，無法僅靠 git attribution 判斷 spec-6 worker 是否越界；本次 focused review 只審 `daily_price.py`，未發現此檔以外為 spec-6 所需的修改。 |
| 支援上市 + 上櫃 | **通過** | `parse_twse` / `TwseDailyPriceSource` 處理 TWSE MI_INDEX，`parse_tpex` / `TpexDailyPriceSource` 處理 TPEx daily close quotes，市場值分別為 `listed` / `otc`，與 `SecurityMarket` enum 對齊。 |
| parse 是純函式，不打外網 | **通過** | `parse_twse(raw)` 與 `parse_tpex(raw)` 只呼叫 `_decode_json_payload`、日期 / 數值轉換與 list/dict 操作；網路 I/O 只存在於各 source 的 `fetch()`。 |
| `@register` 自註冊 | **通過** | `TwseDailyPriceSource` 使用 `@register("daily_price_twse")`，`TpexDailyPriceSource` 使用 `@register("daily_price_tpex")`，符合 spec-4 registry 契約。 |
| 正規化到 `daily_prices` 原始 OHLCV 欄位 | **通過** | 輸出欄位為 `symbol`、`market`、`date`、`open_raw`、`high_raw`、`low_raw`、`close_raw`、`volume`；schema 的 `DailyPrice` 原始欄位為 `open_raw/high_raw/low_raw/close_raw/volume`，可由 pipeline 以 `symbol`+`market` 對應 `security_id` 後落庫。 |
| 未混入還原價邏輯 | **通過** | 未產出 `*_adj`、`adj_factor` 或 corporate action 計算；檔頭也明確把還原價留給 spec-10。 |
| fixture 易失敗風險 | **未命中阻斷** | 本地手寫 TWSE/TPEx JSON dict/string/bytes 樣本可解析為預期列；`date` 為 `datetime.date`，價格為 `Decimal`，volume 為 `int`，symbol 有 strip。TPEx 官方端點現場回應的頂層 `date` 亦為西元 `YYYYMMDD`，支撐 `_to_trading_date` 假設。 |

## 我額外做的 sanity check

未呼叫 `cli.js`，未修改 `orchestrator/manifest.json`，未打真外站作為驗收。只用 `backend/venv/bin/python` 加 `PYTHONPATH=backend` 執行手寫固定樣本：

- `parse_twse` 對 dict / JSON string / bytes 皆回傳 `2330`、`market="listed"`、`date=datetime.date(2024, 1, 2)`、raw OHLCV。
- `parse_tpex` 對 dict / JSON string / bytes 皆回傳 `6488`、`market="otc"`、`date=datetime.date(2024, 1, 2)`、raw OHLCV。
- `TwseDailyPriceSource().parse(...)` 與 `TpexDailyPriceSource().parse(...)` 可委派到對應 parse 函式。
- import 後 `registered_sources()` 含 `daily_price_twse` 與 `daily_price_tpex`。

觀察：用系統 Python 直接 import 會因未安裝 `httpx` 失敗；`backend/pyproject.toml` 已宣告 `httpx>=0.27`，用專案 venv 執行成功，因此判為環境未啟用依賴，不是 spec-6 code 缺陷。

## 風險 / 備註（非阻斷）

- **R1（scope 可觀測性）**：因 `daily_price.py` 是 untracked，指定的 `git diff -- backend/app/adapters/daily_price.py` 無法顯示新增內容；review 只能以檔案內容與當前狀態判斷，不能精準證明 worker 只動過此檔。此為工作樹狀態限制，不是 adapter 行為缺陷。
- **R2（實站格式仍需 fixture 覆蓋）**：TWSE 以 table title hint 找「每日收盤行情」，TPEx 取 `tables[0]`；目前對固定樣本與官方現場格式看起來合理，但後續 test-6 的 fixture 應保留兩市場代表性樣本，尤其是非交易日、無成交列、千分位與 `--` 值。

```json
{ "verdict": "pass" }
```
