# spec-9 focused re-review

## 二次 rework re-review（2026-07-06，spec-3 enum 修復觸發的級聯重驗）

- verdict：**pass**
- 觸發原因：spec-3 修 `Security.market` 的 SQLAlchemy `Enum` `values_callable` 被引擎級聯重置為 pending，非本檔本身有問題。
- 覆核重點：`corporate_actions.py` 全檔無 `app.models`/`SecurityMarket` import；`_TYPEK_TO_MARKET`/`_normalize_market` 對未知市場碼採「拒絕該列、不誤分類為 listed」的安全 fallback，輸出值仍為小寫 `"listed"`/`"otc"`，與修復後 enum `.value` 一致。與 spec-10（`adjustment.py`）的欄位契約（`ex_rights_date`/`cash_dividend_per_share`/`stock_dividend_per_share`）逐字比對仍吻合。三套頁面×兩市場覆蓋、`@register` 自註冊皆重新核對成立。
- 非阻斷觀察（留給 spec-11 review 追蹤，非本次 verdict 影響因素）：`corporate_actions` 表的 `(security_id, ex_rights_date)` 唯一鍵同時被除權息事件與股本變動事件共用，若同股同日兩者皆有事件會撞鍵；這是 pipeline upsert 合併職責的問題，不是本 parse 純函式的正確性問題。
- 結論：無需改動，原樣記回 verified。

---

verdict: pass
depth: focused
reviewer_role: reviewer
framing: 聚焦確認前次 fail 是否已修正，並重新抽查 spec-9 review map 的主要風險面。

## 審查輸入

- 使用者原文: `orchestrator/requirement.md`
- 任務切片: `orchestrator/intake-tasks.md` 的 `spec-9`
- 驗證地圖: `orchestrator/intake-verification-map.md` 的 `spec-9`
- review map: `orchestrator/intake-review-map.md` 的 `spec-9`
- 實際產物: `backend/app/adapters/corporate_actions.py`
- 上游契約: `backend/app/adapters/base.py`, `backend/app/adapters/registry.py`
- 相關 model: `backend/app/models/corporate_action.py`, `backend/app/models/security.py`

## 前次 fail 修正確認

前次 fail 主因是 `_extract_tables` 移除空白 cell，導致 HTML table 後續以表頭 index 對齊資料列時欄位左移。現況已修正：

- `backend/app/adapters/corporate_actions.py` 的 `_extract_tables` 以 `cells = [_clean_text(cell) ...]` 保留每個 `th` / `td` 的位置。
- 同函式只用 `if any(cells): parsed_rows.append(cells)` 跳過整列全空，不再刪除列內空白 cell。
- `_records_from_table` 仍按表頭 index 對齊並 padding 短列，因此保留空白 cell 後可正確維持欄位位置。

我用本機純解析 smoke 驗證：

```bash
PYTHONPATH=backend backend/venv/bin/python - <<'PY'
from app.adapters.corporate_actions import parse_dividend_events, _extract_tables
# HTML fixture 含：
# 1. 只有除息：除權日期/股票股利 td 空白
# 2. 只有除權：除息日期/現金股利 td 空白
# 3. 同日除權息
# 4. 整列全空
PY
```

驗證結果：

- `_extract_tables` 保留只有除息列尾端 `'', ''`，也保留只有除權列中間 `'', ''`。
- 整列全空未進入 table rows。
- `parse_dividend_events` 對只有除息列產出 `cash_dividend_per_share=Decimal('3.0')`、`stock_dividend_per_share=None`、日期為除息交易日。
- 對只有除權列產出 `cash_dividend_per_share=None`、`stock_dividend_per_share=Decimal('0.1')`、日期為除權交易日。
- 同日除權息列合併成單列，現金股利與股票股利皆保留。

結論：前次 P1 已修正；「只有除息 / 只有除權 fixture 不會欄位錯位」這項已由控制流程與 smoke sample 共同確認。

## spec-9 風險面抽查

### 三套頁面齊備

通過。檔案內有三個獨立純解析入口：

- `parse_security_master`：股票基本資料，輸出 `row_type="security"`。
- `parse_dividend_events`：除權息事件，輸出現金股利與股票股利欄位。
- `parse_capital_changes`：股本變動，輸出股本變動日期、變動股數與變動後股數。

`MopsCorporateActionsSource.fetch` 回傳 `basic` / `dividend` / `capital` 三類 raw bucket，`parse` 依 bucket 分派到三套 parser。

### pure parse / fetch 分離

通過。三個 parse helper 都只吃 `raw` 與 context 參數，不打外網、不讀外部狀態；網路 I/O 集中在 `MopsCorporateActionsSource.fetch` / `_post`。`parse` 只把 fetch 回來的 raw HTML / mapping 轉為 normalized rows。

### registry 自註冊

通過。`MopsCorporateActionsSource` 使用 `@register("corporate_actions_mops")`，且繼承 `DataSource`，符合 spec-4 registry 契約。

### 除權息欄位支撐 spec-10

通過。除權息列至少含：

- `ex_rights_date`
- `cash_dividend_per_share`
- `stock_dividend_per_share`

此外也保留 `symbol`, `market`, `name`, `action_type` 與股本欄位占位。只有除息、只有除權、同日除權息三種情境都能對應到 spec-10 所需的還原係數輸入。

### securities 上市 / 上櫃父表覆蓋

通過。`_iter_market_inputs(None)` 預設回傳 `["listed", "otc"]`，`fetch(None, date)` 會抓上市與上櫃基本資料；`parse_security_master` 支援 `TYPEK` / 市場別 / context market，輸出 `market` 為 `listed` 或 `otc`。這能讓 `securities` 作為其他表 FK 父表覆蓋上市與上櫃。

### 股本變動

通過。`parse_capital_changes` 解析變更日期、增減股數、變動後股數；若缺增減股數但有前後股數，可用排序後的 `previous_after_shares` 推得變動量。股本變動列與除權息列共用 `corporate_action` row shape，符合 spec-9 將股本變動落入 `corporate_actions` 的要求。

## 限制

- 此 worktree 目前 `backend/` 與 `orchestrator/` 整體為 untracked，無法用 git diff 精準分辨 worker 變更時窗；本次 review 以實際檔案內容與 focused smoke 為準。
- 此 worktree 未看到 `test-9` 測試檔或正式 fixture；本次只做 reviewer 端的最小純解析 smoke，不取代後續 machine test 節點。
- `fetch` 的真外站可用性不在 spec-9 machine 驗收範圍內，本次未打外網。

## 結論

pass。前次 fail 的空白 td 欄位錯位已修正；三套頁面、fetch/parse 分離、`@register`、spec-10 所需除權息欄位，以及上市/上櫃 securities 父表覆蓋皆通過 focused re-review。
