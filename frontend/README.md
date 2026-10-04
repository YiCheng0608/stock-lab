# Frontend

React、TypeScript、Vite、React Query 與 ECharts 的台股研究介面。方向見[產品規格](../docs/PRODUCT_SPEC.md)，完成狀態見[開發路線](../docs/ROADMAP.md)。

## 啟動

從專案根目錄另開終端：

```powershell
Set-Location frontend
npm install
npm run dev
```

也可選用 `pnpm install --ignore-scripts`／`pnpm dev`，不要混用安裝流程。API 預設為 `http://127.0.0.1:8000/api`；需要覆寫時在啟動前設定 `$env:VITE_API_BASE`。`npm run build` 執行 TypeScript 檢查與 production build。後端啟動及資料路徑查[操作手冊](../docs/OPERATIONS.md)。

## 頁面與契約

- 主導航：今日、新聞、族群、個股、行動；新聞詳情 `/news/:id`，個股 `/stocks/:exchange/:symbol`。
- 研究／診斷：`/research/backtest`、`/research/coverage`、`/research/strategies`、`/system/data-quality`、`/glossary`。
- [UI 文案](../docs/UI_COPY_SPEC.md)：中文狀態、單位、未知與卡片；[個股研究頁](../docs/STOCK_RESEARCH_PAGE.md)：圖表與研究流程。
- [新聞契約](../docs/NEWS_SPEC.md)：來源、去重、時間；[詞彙表](../docs/GLOSSARY.md)：術語。

股數以精確 shares 保存，成本為每股；張／股只作輸入與呈現。最近收盤不稱即時價，固定 confidence 不稱勝率。現行能力與驗收邊界以 ROADMAP 及上述契約為準。
