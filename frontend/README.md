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

所有頁面共用 `components/Shell.tsx`（固定頂部 Navbar、搜尋導向 `/stocks?q=`、資料日期 badge、窄版漢堡選單）；個股頁「圖表與指標」讀 bars API（[V1_SPEC 技術指標](../docs/V1_SPEC.md#技術指標)），其餘分頁讀 `GET /api/stocks/{exchange}/{symbol}`。
