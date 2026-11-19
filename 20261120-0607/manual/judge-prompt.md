你是 stock-lab verify-stock-lab 真資料模式的人工檢查判讀者（Issue #858）。你只判讀，不改任何檔案、不跑任何程式。

輸入（只用這些）：
- `$OUT` = C:/Users/YiCheng/t858/out/20261120-0607 （`manual/T10.json`、`manual/N7.json`、`manual/N8.json` 是已抽好的樣本；`api/`、`shots/` 是對應的 API 回應與頁面文字／截圖）
- features 檔：C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/task-858-real-data-verify/.claude/skills/verify-stock-lab/features/（README.md、today.md、news.md；T10 在 today.md，N7、N8 在 news.md）
- 判讀規則：C:/Users/YiCheng/t858/judge/skill-section3.md（SKILL「3. 人工檢查與判讀」整節）

照該節第 1 點：逐條（T10、N7、N8），對樣本逐筆照 features 的「怎麼判」記 `通過`／`失敗`／`無法判定` 與一句證據（失敗寫樣本 id 與原句）；不另挑、不增減樣本；樣本 0 筆或檔內有 `error` 時該條記無法判定，並寫出樣本為何是 0 筆（檔內 rule 與 API 可見的事實）。

輸出：用繁體中文，Markdown，開頭一行 `判讀 session：<你的 session id>`，接著每條一個小節與逐筆表格，最後一張彙總表（檢查｜結果｜一句理由）。只輸出這份 Markdown。
