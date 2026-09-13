# Frontend

React、TypeScript、Vite、React Query 與 ECharts 的台股研究介面。主流程為事件 → 族群／題材 → 個股證據 → 行動／持倉追蹤。完整方向見 [產品規格](../docs/PRODUCT_SPEC.md)，狀態見 [開發路線](../docs/ROADMAP.md)。

## 啟動

另開終端，從專案根目錄執行：

    Set-Location frontend
    npm install
    npm run dev

也可使用 pnpm install --ignore-scripts 與 pnpm dev；選擇一套套件管理流程。API 預設為 http://127.0.0.1:8000/api，可於啟動前設定：

    $env:VITE_API_BASE = 'http://127.0.0.1:8000/api'

npm run build 執行 TypeScript 檢查及 production build。後端的隔離環境與啟動請見 [操作手冊](../docs/OPERATIONS.md)，不要在 frontend 工作目錄直接複製 backend 的相對路徑命令。

## 頁面與呈現

- 主導航：今日、新聞、族群、個股、行動。
- 新聞 /news/:id、個股 /stocks/:exchange/:symbol、持倉／壓縮行動卡在程式可見。
- 研究／診斷：/research/backtest、/research/coverage、/research/strategies、/system/data-quality、/glossary。
- 股數以精確 shares 保存、張／股僅為輸入與呈現；成本一律每股。
- 最近收盤不稱即時現價；來源、當日行情、個別策略完整度分開。
- 未來新增 AI 摘要、題材或短線資金資訊時，來源事實、推論與未知分開；固定信心值不可顯示為勝率。
- 模型、題材擴充、外部新聞／分點、完整交易計畫與風險部位仍待建置。本輪未驗收 UI 或 production build。

## 文案權威

[UI_COPY_SPEC](../docs/UI_COPY_SPEC.md) 負責中文狀態、卡片層級、原因碼、單位及不確定性；[NEWS_SPEC](../docs/NEWS_SPEC.md) 負責新聞時間／去重／來源；[GLOSSARY](../docs/GLOSSARY.md) 負責術語。Phase 3／4 已原路徑封存，不再當目前進度。

每次 UI 實作只更新 ROADMAP 的狀態和相關領域契約，不在此重複保存會過期的 P0 計數或測試筆數。
