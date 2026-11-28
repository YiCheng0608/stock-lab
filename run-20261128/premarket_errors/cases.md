# 早盤 AI 判錯清單 2026-11（premarket_errors 第 1 版，#1069）

- 判讀：champion、`premarket_v1`；2026-11 的判讀日 done 0、failed 0、rejected 0 天（failed／rejected 只列天數）
- 其他提示版本的 champion（只列，不收）：沒有
- 案例歸結果出來的那個月（大盤是 D，個股是期間的最後一個交易日）：本月判錯 0 筆（大盤當日判錯 0、defer 卻漲 0、keep／reprice 卻觸停損 0、沒有規則價位的 keep 卻跌 0），判對 0 筆；本月的判讀中不能比 0、分數列還沒寫 0、已寫但結果在之後的月份 0（後兩種到結果那個月才收）
- 大盤 d0 判對率：—（0 天）
- 收進 `cases.json`：判錯最多 30 筆（大盤全收，個股依超額絕對值）、每類同樣筆數的判對當對照
- 提案：**樣本不足，不提案**（大盤 d0 已對答案 0 天（至少 15），判錯 0 筆（至少 10））
- 重現：`python tools/research/premarket_errors.py --db /db/stock.db --month 2026-11 --out /out/run-20261128/premarket_errors --min-free-gb 0`

## 案例

（沒有）

## 理由引用的種類與判對率（只列出，不進清單）

- 判對：大盤看 `hit`；每檔看 T+5 對母體超額的正負（keep／reprice 為正、defer 為負）。這和判錯的 ±3 個百分點門檻不是同一個口徑

（沒有）

