# spec-10 full review

verdict: pass
depth: full
reviewer_role: reviewer
framing: 假設還原價已上線並污染技術指標/回測，反推是否有日期方向、事件合併、累積倍率、量化或 pipeline 回填介面會讓整段序列失真。

## 審查輸入

- 使用者原文: `orchestrator/requirement.md`
- 任務切片: `orchestrator/intake-tasks.md` 的 `spec-10`
- 驗證地圖: `orchestrator/intake-verification-map.md` 的 `spec-10`
- review map: `orchestrator/intake-review-map.md` 的 `spec-10`
- 實際產物: `backend/app/pricing/adjustment.py`, `backend/app/pricing/__init__.py`
- 相關 model: `backend/app/models/daily_price.py`, `backend/app/models/corporate_action.py`

## 結論

pass。未發現會讓 test-10 數學 fixture 失敗的明顯問題；實作符合「純數學、向後還原、事件日前交易日套用、多事件連乘、同日除息除權合併、Decimal 量化至 Numeric(12,4)、提供 pipeline row 回填 helper」的 spec-10 要求。

## 對抗式檢查

### outputs 邊界

pass。spec-10 allowed outputs 是：

- `backend/app/pricing/__init__.py`
- `backend/app/pricing/adjustment.py`

本次審查對象集中在這兩個 pricing 檔；`backend/app/models/daily_price.py` 與 `backend/app/models/corporate_action.py` 僅作為必讀上游契約比對，未看到 spec-10 需要修改 model 才成立的跡象。限制：此 worktree 目前 `backend/` 與 `orchestrator/` 整體為 untracked，無法用 git diff 精準歸因每個 worker 的 touched set；本項以指定產物內容與 spec-10 allowed outputs 對照。

### 純數學與 I/O 隔離

pass。`backend/app/pricing/adjustment.py` 只使用 dataclass、date、bisect、Decimal 與 mapping/object 轉換；沒有網路、DB session、ORM query、爬蟲、檔案或 adapter 呼叫。`apply_adjustments_to_rows` 只修改呼叫端傳入的 mapping row，不處理 persistence。

### 公式與日期方向

pass。`calculate_event_ratio` 使用：

```text
(previous_close - cash_dividend_per_share)
/ (previous_close * (1 + stock_dividend_per_share))
```

`calculate_adjustment_factors` 以事件日前一個交易日的 `close_raw` 作為 previous close，並只對 `bar.date < ex_rights_date` 的交易日乘上事件比例；事件日與事件日之後不套用該事件本身。這符合向後還原語意，避免除權息日之後的已除權息價格被重複調整。

### 多次事件連乘與方向

pass。事件依日期由舊到新處理，每個事件比例乘到事件日前所有交易日。因此更早的交易日會吃到所有後續事件的連乘；事件 A 之後、事件 B 之前的區間只吃到 B 之後的事件。這是後還原價格序列需要的方向。

本地 probe：

```text
事件 2024-01-03: 前收 90、現金 10 => ratio 0.888888...
事件 2024-01-04: 前收 80、股票股利 0.1 => ratio 0.909090...

factor(2024-01-01) = 0.888888... * 0.909090... = 0.808080...
factor(2024-01-02) = 0.808080...
factor(2024-01-03) = 0.909090...
factor(2024-01-04) = 1
```

結果符合「事件日不套自身事件，但會套日後事件」的污染反推條件。

### 除息 + 除權混合、同日多筆 action 合併

pass。`_combine_actions` 依 `ex_rights_date` 合併同日多筆 action，現金股利加總、股票股利加總；`calculate_event_ratio` 對合併後事件一次套入現金與股票股利公式。同日除息與除權不會被拆成兩個 sequential ratio，也不會因同日多列覆蓋前一列。

### Decimal 與 Numeric(12,4) 相容性

pass。所有數值先以 `Decimal(str(value))` 正規化，預設 `DEFAULT_PRICE_QUANT = Decimal("0.0001")`，`*_adj` 以 `ROUND_HALF_UP` 量化到四位小數。這與 `daily_prices` 的 `Numeric(12,4)` 欄位相容。還原係數本身未寫入 model 欄位，因此不需要受 `Numeric(12,4)` 限制。

### pipeline 回填介面

pass。`apply_adjustments_to_rows` 可吃 normalized daily price mapping rows，呼叫 `fill_adjusted_prices` 後依日期回填：

- `open_adj`
- `high_adj`
- `low_adj`
- `close_adj`

這正好對應 `DailyPrice` 的還原價欄位，且不要求 pipeline 先建立 ORM 物件或 DB session。

### `__init__.py` 匯出

pass。`backend/app/pricing/__init__.py` 匯出 `PriceBar`、`CorporateActionEvent`、`AdjustedPriceBar`、`calculate_event_ratio`、`calculate_adjustment_factors`、`fill_adjusted_prices`、`apply_adjustments_to_rows`，足以讓 test-10 與 spec-11 pipeline 消費。

## 本地 reviewer probe

使用 `PYTHONPATH=backend python` 匯入 `app.pricing.adjustment`，全程未打外網、未連 DB、未呼叫 orchestrator `cli.js`。

- `calculate_event_ratio(90, cash=10, stock=0)` 得 `0.888888...`。
- `calculate_event_ratio(80, cash=0, stock=0.1)` 得 `0.909090...`。
- 四日 price 序列加兩個事件時計算出 factors: `0.808080...`, `0.808080...`, `0.909090...`, `1`。
- `fill_adjusted_prices` 將 close quantize 成四位小數，如 `80.8081`, `72.7273`, `72.7273`, `70.0000`。
- `apply_adjustments_to_rows` 回填 mapping rows 的四個 `*_adj` 欄位。

## 剩餘風險

- 未看到正式 `test-10` 測試檔；本次 reviewer probe 只驗核心數學方向與 row 回填，不取代後續 machine test 節點。
- 若上游 spec-9 將股票股利以「每仟股配股股數」而非「每股配股數」餵入，會造成比例錯誤；但 `CorporateActionEvent` 與 `CorporateAction` 欄位註解都明確要求每股配股數，這屬上游資料正規化契約。
- 遇到現金股利大於等於前收或股票股利使分母非正時會丟 `ValueError`。這比靜默產生負還原價安全，非阻斷。

```json
{ "verdict": "pass", "reason": "spec-10 pricing.adjustment is pure Decimal math with correct backward adjustment direction, event-day exclusion, multi-event compounding, same-day action merging, Numeric(12,4)-compatible quantization, and row refill helper for pipeline" }
```
