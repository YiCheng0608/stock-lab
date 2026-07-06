# review-spec-7: 籌碼 adapter focused review

## Rework re-review（2026-07-06，spec-3 enum 修復觸發的級聯重驗）

- verdict：**pass**
- 觸發原因：spec-3 為修另一個 bug（`Security.market` 的 SQLAlchemy `Enum` 加 `values_callable`）被引擎級聯重置為 pending，非本檔本身有問題。
- 覆核結果：`chips.py` 全檔無 `app.models`/`SecurityMarket` import；六個 parse 函式（三大法人/融資券/借券 × 上市/上櫃）皆寫入小寫字面值 `"listed"`/`"otc"`，與修復後 enum `.value` 一致，且因本檔從未經 ORM enum 層，此修復對其本就正交。三類籌碼 × 兩市場覆蓋、`(security,date)` 正規化、`@register("chips")` 自註冊皆重新核對成立。無需改動，原樣記回 verified。

- verdict: pass
- review_depth: focused
- role: reviewer
- target: `backend/app/adapters/chips.py`

## 審查依據

- 使用者原文: `orchestrator/requirement.md`
- 任務切片: `orchestrator/intake-tasks.md` 的 `spec-7`
- 驗證地圖: `orchestrator/intake-verification-map.md` 的 `spec-7`
- review map: `orchestrator/intake-review-map.md` 的 `spec-7`
- 上游契約: `backend/app/adapters/base.py`, `backend/app/adapters/registry.py`
- 相關 model: `backend/app/models/chip.py`
- 實作: `backend/app/adapters/chips.py`

## 對抗式檢查

假設此 adapter 已上線並導致籌碼資料錯誤，最可能的失效點是：漏市場、漏資料類別、parse 偷打外網、未註冊導致排程 discover 不到、欄位 index 或單位轉換錯誤、三份來源沒有合併成同一列。

本次檢查結果：

- 產物邊界: spec-7 實作檔為 `backend/app/adapters/chips.py`；本輪未修改 `orchestrator/manifest.json`，也未呼叫 `cli.js`。注意：`git diff -- backend/app/adapters/chips.py` 對目前未追蹤檔沒有輸出，因此本審查以檔案內容為主。
- 三類資料覆蓋: 已實作三大法人、融資券、借券賣出餘額。
- 兩市場覆蓋: TWSE 與 TPEx 都有獨立解析路徑，共六個 parser：`parse_twse_institutional`, `parse_tpex_institutional`, `parse_twse_margin`, `parse_tpex_margin`, `parse_twse_lending`, `parse_tpex_lending`。
- fetch / parse 分離: `ChipsSource.fetch()` 只負責六個官方 JSON 來源抓取；`parse_*()` 與 `parse_chips()` 都只吃傳入 payload，未觸發網路或外部狀態讀取。
- registry: `ChipsSource` 使用 `@register("chips")` 自註冊，符合 `registry.py` 契約。
- model 欄位對應: 輸出欄位對應 `Chip` model 的 `foreign_net`, `investment_trust_net`, `dealer_net`, `margin_balance`, `short_balance`, `securities_lending_balance`；`parse_chips()` 以 `(symbol, market, date)` 合併成單列。
- 單位與 index: 以官方 2024-01-02 JSON 欄位抽查，TWSE/TPEx 融資券餘額欄位取的是今日/資券餘額，並以張轉股數乘 1000；TWSE/TPEx 借券來源欄位本身為股數，取當日餘額且未再乘 1000；三大法人欄位取買賣超股數，未發現明顯錯位。

## 結論

focused review 未發現需退回 worker 的阻擋問題。後續 test 節點仍應用 fixture 固化三類資料乘以兩市場的欄位映射，特別是 TPEx 欄位順序與官方格式漂移。
