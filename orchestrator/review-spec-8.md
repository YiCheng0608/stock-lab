# Re-review: spec-8 券商分點 adapter

## 二次 rework re-review（2026-07-06，spec-3 enum 修復觸發的級聯重驗）

- verdict：**pass**
- 觸發原因：spec-3 為修另一個 bug（`Security.market` 的 SQLAlchemy `Enum` 加 `values_callable`）被引擎級聯重置為 pending，非本檔本身有問題。
- 覆核重點（含最高風險項:spec-11 依賴的介面）：
  - `broker_branch.py` 全檔 grep `SecurityMarket|app.models` 零命中；market 皆為 `Literal["listed","otc"]` 字面值，從未建構 enum instance。
  - 直接讀 `pipeline.py:535-546` 實際呼叫點，確認 `_broker_branch_targets()` 對 `resolve_universe(date, market)` 仍是 positional call、對 `"listed"`/`"otc"` 兩市場都跑得動、空集合仍 raise，介面未受影響。
  - `_upsert_broker_branch` 對 `Security` 的查找是純 by-symbol，market 只用於錯誤訊息字串，不經過 enum round-trip。
  - scope 檢查：`broker_branch.py` mtime 早於本輪 spec-3 修復時間，確認本輪未被觸碰。
- 結論：無需改動，原樣記回 verified。

---

- 角色：reviewer，full depth，採對抗式 framing。
- 審查對象：`backend/app/adapters/broker_branch.py`。
- 對照基準：`orchestrator/requirement.md`、`orchestrator/intake-tasks.md` spec-8、`orchestrator/intake-verification-map.md` spec-8、`orchestrator/intake-review-map.md` spec-8、`backend/app/adapters/base.py`、`backend/app/adapters/registry.py`、`backend/app/models/broker_branch_trade.py`。
- 本次限制：依指示不可改 manifest/cli，不代改程式；本次只更新本紀錄檔。

## Verdict: pass

前次 fail 的兩個阻斷點已修掉：

1. 同列雙欄分點表已能解析左右兩組券商欄位。
2. `BrokerBranchRaw.date` 已能在 parser 無日期時補進輸出列，不再產生 `date=None`。

本次 full re-review 未發現新的 spec-8 阻斷問題。

## 前次 fail re-check

### F1: 同列雙欄分點表左右兩組都解析

- 結果：pass。
- 依據：`_find_header_groups()` 會在 header row 中收集所有含「券商」或「分點」的欄位位置，並依下一個 branch header 作為分組邊界，建立多組 `{"branch","buy","sell"}` index。`_parse_table_matrix()` 對每列逐一跑所有 groups，不再只讀第一組。
- 本地 probe：一列同時含 `9200 凱基台北` 與 `9100 群益金鼎`，`parse_twse_html()` 輸出 codes `['9200', '9100']`，`parse_tpex_html()` 也輸出 codes `['9200', '9100']`。

### F2: `BrokerBranchRaw.date` 補上 parser 無日期時的 None

- 結果：pass。
- 依據：`OfficialBrokerBranchSource.parse()` 對 `BrokerBranchRaw` 每頁 parser 結果逐列檢查 `if row.get("date") is None: row["date"] = raw.date`，可覆蓋 `_make_row()` 先放入的 `None`。
- 本地 probe：`BrokerBranchRaw(date=2026-07-06, pages=(html_no_date,))` 解析後輸出 `fallback_dates [datetime.date(2026, 7, 6)]`。
- 影響確認：TPEx fetch path 若先把 JSON rows 轉 `_rows_to_fixture_html()`，該 HTML 即使無日期，後續也會由 raw date 補回，不再卡 `broker_branch_trades.date` 非空欄位。

## spec-8 條件逐項檢查

| 檢查項 | 結果 | 依據 |
|---|---|---|
| `BrokerBranchSource` 實作與未來替換縫 | pass | `OfficialBrokerBranchSource(BrokerBranchSource)`；`fetch/parse` 消費面維持在抽象契約後，可由日後 FinMind 版整段替換。 |
| 雙市場支援 | pass | `parse_twse_html()` 固定 `market="listed"`；`parse_tpex_html()` / `parse_tpex_json()` 固定 `market="otc"`；`fetch()` 依 `BrokerBranchTarget.market` 分 TWSE/TPEx 路徑。probe 驗到 listed/otc market 正確。 |
| pure parse，不打外網 | pass | `parse_twse_html()`、`parse_tpex_html()`、`parse_tpex_json()` 只吃傳入 HTML/JSON 並用 BeautifulSoup/本地轉換；外網 I/O 只在 `_fetch_*` 與 `_fetch_top_volume_symbols()`。 |
| 3-5s 節流 | pass | `ThrottleConfig(min_seconds=3.0, max_seconds=5.0)`；`SingleThreadThrottle.wait()` 第二次以後用 `random.uniform(min,max)` 補睡差額；probe mock clock 得到 sleep `3.528...`，落在 3-5s。 |
| 單線程保守抓取 | pass | `fetch_many()` 逐檔 list comprehension 呼叫 `fetch()`，每次 `fetch()` 先 `self._throttle.wait()`，沒有並發。 |
| `CaptchaSolver` 注入 | pass | constructor 接 `captcha_solver: CaptchaSolver | None`，有傳入就 `super().__init__(captcha_solver)`；預設才建立 `DdddOcrCaptchaSolver()`。probe 假 solver 可注入且 `source.captcha_solver.solve()` 回傳假值。 |
| 預設 ddddocr 且延遲 import | pass | `DdddOcrCaptchaSolver.__init__()` 內才 `import ddddocr`；只 import module / 跑 parser 不會載入 OCR。 |
| 成交量前 N universe | pass | `resolve_universe()` 未設定 universe 時呼叫 `_fetch_top_volume_symbols(date, market, self._universe_limit)`；`_DEFAULT_UNIVERSE_LIMIT = 50`；未看到引用自選股表。 |
| 可設定 universe | pass | constructor 接 `universe` 與 `universe_limit`；`_configured_universe()` 支援全市場共用 sequence 或依 market 的 dict。 |
| 只抓當日 | pass | `fetch()` 呼叫 `_ensure_today_only(date)`；非 `today()` 直接 `ValueError`。probe 非當日得到「官方分點頁只提供當日資料」錯誤。 |
| `@register` 自註冊 | pass | `@register("broker_branch_official")` 標在 `OfficialBrokerBranchSource`；probe `registered_sources()` 含 `broker_branch_official`。 |
| 輸出欄位可落 broker_branch_trades | pass | rows 包含 `symbol/market/date/broker_branch_code/broker_branch_name/buy_volume/sell_volume`；前次 `date=None` 阻斷已修。 |
| outputs 邊界 | pass for this review | 本次未改 adapter/manifest/cli；只覆寫 `orchestrator/review-spec-8.md`。worktree 既有多個 untracked 產物，無法用 `git status` 對 spec-8 worker 歸因，但審查對象本身符合 spec-8 allowed output。 |

## 本地驗證

使用 `PYTHONPATH=backend backend/venv/bin/python`，全程未打外網，未修改程式。

- `python -m py_compile backend/app/adapters/broker_branch.py`：pass。
- 雙欄 HTML fixture：
  - TWSE: `double_twse_codes ['9200', '9100']`，market 皆 `listed`。
  - TPEx: `double_tpex_codes ['9200', '9100']`，market 皆 `otc`。
- `BrokerBranchRaw.date` fallback：
  - 無日期 HTML + raw date `2026-07-06` 輸出 `fallback_dates [datetime.date(2026, 7, 6)]`。
- 介面與註冊：
  - `issubclass(OfficialBrokerBranchSource, BrokerBranchSource)` 與 `isinstance(source, BrokerBranchSource)` 皆 true。
  - `registered_sources()` 含 `broker_branch_official`。
  - 假 `CaptchaSolver` 注入成功。
- TPEx JSON parser：
  - 輸出 `symbol='6488'`, `market='otc'`, `date=datetime.date(2026, 7, 6)`, branch `9200` 與買賣量。
- 節流：
  - mock clock 第二次 wait sleep `3.528...` 秒，符合 3-5s 設定。
- 只抓當日：
  - `_ensure_today_only(2026-07-05)` 在 `today=2026-07-06` 時丟出預期 `ValueError`。

## 剩餘風險與非阻斷觀察

- 沒有專門的 `test-8` 測試檔可跑；本次以 reviewer probe 驗證指定修補與 spec-8 條件。這是測試覆蓋缺口，不是目前程式阻斷。
- 真外站抓取、真 OCR、TPEx Turnstile 變動不在 spec-8 machine 驗收內；依 intake 定義屬維運風險，靠排程重試與告警承接。
- `parse(raw: str)` 預設走 TWSE parser；若下游要直接把 OTC HTML string 當 raw 傳入，需走 `parse_tpex_html()` 或帶 `BrokerBranchRaw(market="otc")`。現有 `fetch()` path 會帶 `BrokerBranchRaw`，不構成本次阻斷。

## 結論

pass。前次兩個 fail 已用程式結構與本地 probe 雙重確認修復；BrokerBranchSource、雙市場、pure parse、3-5s 節流、CaptchaSolver 注入、成交量前 N universe、只抓當日與 `@register` 皆符合 spec-8。

```json
{ "verdict": "pass", "reason": "previous double-column parsing and BrokerBranchRaw.date fallback failures are fixed; spec-8 adapter requirements hold under local probes" }
```
