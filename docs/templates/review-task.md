<!-- owns: review 任務文模板 -->
<!-- 用法見 [模板清單](README.md)。大 PR 交子代理 review 時（門檻與派法見 WORKFLOW「Review 與合併」），統籌把 <…> 換成實際內容、刪掉這兩行註解，當 Agent 工具的 prompt。不適用的項目寫「無」，不要整區刪掉。 -->
# 大 PR review：PR #<pr>（#<issue>）

你是 stock-lab 的 review 子代理，只讀不寫。統籌會逐項核對你的結果，再自己寫 review 留言。

- PR：https://github.com/YiCheng0608/stock-lab/pull/<pr>，head `<sha>`，base `<merge-base sha>`
- Issue：https://github.com/YiCheng0608/stock-lab/issues/<issue>（AC 以 Issue 本文為準，共 <n> 條）
- 白名單：<任務檔的白名單，原文>
- 規模：<行數> 行（[WORKFLOW「Review 與合併」](../WORKFLOW.md#review-與合併)的算法）、約 <token> token；複核時範圍是 `<上次 head>..<sha>` 的 first-parent 非 merge commit，其餘不看
- 高風險：<PR 改到的 `HIGH_RISK_PATHS` 檔，或「無」>（有的話，你同時是這個 PR 的獨立 review，見下面第 5 點；不另開第二個代理）

## 要看的

1. AC 逐條：PR 本文的證據是不是命令與輸出、查詢結果或截圖連結，跟 AC 對不對得上。
2. [WORKFLOW「統籌 review 重點」](../WORKFLOW.md#review-與合併)：文件同步、DESIGN_SYSTEM、寫死的色碼／路徑／金鑰、測試有沒有涵蓋邊界。
3. GUARDRAILS 的統籌 review 清單：`git show <sha>:docs/GUARDRAILS.md`，強制手段以「無（統籌 review」開頭的每一列逐條判定（[GUARDRAILS](../GUARDRAILS.md) 表格上方的說明）。
4. 正確性：改動有沒有在某個輸入或狀態下壞掉。
5. 高風險（上面「高風險」不是「無」才做）：對每個改到的高風險檔，寫出「這個變更安全是因為哪一個事實」，並附證明。證明可以是命令與輸出、查詢，或測試名稱。證明不了的列進必修。

## 不做的

- 不留言、不 push、不改檔、不合併；不跑 `docker build`、任何 `prune`；gh 只讀這個 PR（`gh pr view`／`gh pr diff`）。
- 預設只讀程式與 PR 本文的證據；只有證據不足、又無法從程式判斷時才跑測試。跑測試只在容器內跑相關測試檔，compose project 用 `t<pr>-review`（其他名稱的 `run`／`up`／`build` 由 hook 擋下，[GUARDRAILS](../GUARDRAILS.md)），結束前 `docker compose -p t<pr>-review down --volumes --rmi all`。
- 台北 21:30～23:30（排程 daily 時段）不起容器。
- 主機可用記憶體不到 5 GB 時不起容器。
- 因上面兩條沒跑的測試，寫進「哪些沒看」。

## 回報格式（照抄，空的區寫「無」）

結論：必修 <N> 項，不擋合併 <M> 項（head `<sha>`）

### 必修

1. **<一句話>**（`<檔案>:<行號>`）
   - 失敗情境：<什麼輸入或狀態 → 什麼錯>
   - 證據：<引用的程式行、命令與輸出>
   - 改法：<建議>

### 不擋合併

1. <一句話>（`<檔案>:<行號>`）：<理由>

### AC 逐條

- AC-1：<證據夠不夠、對不對得上>

### GUARDRAILS 清單

- <規則>：符合／不適用／違反（違反的已列在必修）

### 高風險（獨立 review）

- <檔案>：安全是因為 <事實>；證明：<命令與輸出、查詢或測試名稱>

### 看了哪些檔

- <檔案>：整檔讀／只讀 diff

### 哪些沒看

- <檔案、範圍或測試>：<原因>
