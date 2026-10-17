# Frontend

React、TypeScript、Vite、React Query 與 ECharts 的台股研究介面。頁面與路由見[產品規格 §2](../docs/PRODUCT_SPEC.md#2-主導航與資訊順序)，視覺與元件見[設計規範](../docs/DESIGN_SYSTEM.md)，文案與單位見[UI 文案](../docs/UI_COPY_SPEC.md)。

## 啟動

從專案根目錄另開終端：

```powershell
Set-Location frontend
pnpm install --frozen-lockfile
pnpm run dev
```

需略過 lifecycle scripts 時用 `pnpm install --frozen-lockfile --ignore-scripts`；依 `pnpm-lock.yaml`，不要混用 npm。API 預設為 `http://127.0.0.1:8000/api`；需要覆寫時在啟動前設定 `$env:VITE_API_BASE`，位址須符合[跨站請求防護](../docs/OPERATIONS.md#11-產品-api-的跨站請求防護)的 Host 規則。`pnpm run test:ci` 執行 `src` 下全部測試，`pnpm run build` 執行 TypeScript 檢查與 production build。後端啟動及資料路徑查[操作手冊](../docs/OPERATIONS.md)。

所有頁面共用 `components/Shell.tsx`（固定頂部 Navbar、搜尋導向 `/stocks?q=`、資料日期 badge、窄版漢堡選單）；個股頁「圖表與指標」讀 bars API（[V1_SPEC 技術指標](../docs/V1_SPEC.md#技術指標)），「新聞與公告」見下段，其餘分頁讀 `GET /api/stocks/{exchange}/{symbol}`。

族群頁 `/themes` 以分頁籤切換產業／題材，讀 `GET /api/themes?board=industry|theme&limit=100`（一次取整榜，名稱搜尋在前端過濾；`?board=theme` 記住題材榜）；族群詳情 `/themes/:id` 讀 `GET /api/themes/{id}`（走勢 `trend`、榜別）、同榜的 board 回應（排名、品質與五分項）、`GET /api/themes/{id}/members`（分頁成員與收盤）與 `GET /api/news?theme_id={id}&limit=10`；今日頁「熱門族群」讀同一 board 端點 `limit=10`，其餘區塊讀 `GET /api/dashboard`。族群相關的邏輯、元件與 fixture 測試在 `src/themes/`。

新聞頁 `/news` 以分頁籤切換國內／國際／官方公告，讀 `GET /api/news?category=domestic|international`（官方公告為 `source_kind=official_disclosure`）加 `q`、`symbol`、`cursor`、`limit=20`；分頁、關鍵字與代號記在網址（`?tab=`、`?q=`、`?symbol=`）。詳情 `/news/:id` 讀 `GET /api/news/{id}`，來源事實與「AI 摘要與判讀」（回應的 `ai` 物件）分區。個股頁「新聞與公告」讀 `GET /api/news?symbol={代號}&limit=50` 並只保留交易所＋代號完全相符（或官方公告的純代號相符）者，今日頁的新聞區沿用同一張卡片。時間只讀 `product_time`（[NEWS_SPEC §6](../docs/NEWS_SPEC.md#6-ui-與-api-契約)），文案依 [UI 文案 §4](../docs/UI_COPY_SPEC.md#4-新聞卡文案與折疊)。新聞相關的邏輯、元件與 fixture 測試在 `src/news/`。
