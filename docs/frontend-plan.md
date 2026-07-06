# 台股盤後分析工具 — 前端實作計畫

> 本文件是**前端頁面生成的直接依據**，整合並展開自 [design.md](design.md) 的前端相關章節（§2、§4、§6、§7、§9、§10）。
> 層級關係：`design.md` 仍是全案設計的事實來源；本文件是其前端部分的**實作級展開**。若本文件與 `design.md` 衝突，以 `design.md` 為準並先修訂之。
> 視覺規格細節（色票、字體階層、元件樣式）以 [design-system/DESIGN.md](design-system/DESIGN.md) 為準，本文件只記錄**台股在地化覆蓋**與落地方式。

## 1. 範圍與前提

- 產出物：`frontend/` 目錄下的 Vite + React + TypeScript SPA，涵蓋第一期全部 UI（design.md §6）。
- **Thick server / thin client**（design.md §2）：篩選、指標、策略邏輯全在後端。前端**不得**自行計算指標、不得複製篩選語意，只負責「組出條件 JSON 送後端」與「呈現後端算好的結果」。
- 後端由另一流程產生中。本文件的 API 端點名稱為**指示性假設**（見 §5），實際契約一律以 FastAPI `/openapi.json` 的 codegen 結果為準——**端點對不上時改前端呼叫，不改後端**。
- 僅支援 **dark mode**（設計系統為 dark 原生）；light mode 明確不做。

## 2. 技術棧（承 design.md §4，此處為定版）

| 項目 | 選型 | 備註 |
|---|---|---|
| 建置 | Vite + React 18+ + TypeScript（strict） | 純 SPA，無 SSR |
| 路由 | React Router v6+ | 見 §6 路由表 |
| 伺服器狀態 | TanStack Query v5 | 所有 API 資料的唯一通道 |
| UI 狀態 | React 內建 state | 夠用前不引入全域狀態庫 |
| API client | orval（讀 `/openapi.json`）| 產 typed client + Query hooks，`npm run codegen` |
| K 線圖 | lightweight-charts | 封裝為 `<KLineChart>` |
| 統計圖 | ECharts | 封裝為 `<StatChart>` |
| 樣式 | CSS variables（design tokens）＋ CSS Modules | **不用** MUI/AntD 等元件庫，元件自建 |
| PWA | vite-plugin-pwa | 只快取 app shell |
| 測試 | Vitest + React Testing Library | 重點測 ConditionBuilder 的 JSON 輸出 |

## 3. 專案結構

```
frontend/
├── src/
│   ├── api/                # orval 生成物（勿手改）＋ axios/fetch instance
│   ├── theme/              # tokens.css（design tokens）、global.css
│   ├── components/         # 跨頁共用元件（見 §8）
│   ├── features/           # 按功能分模組，頁面專屬元件放各自 feature 內
│   │   ├── stock/          #   個股頁：K 線、指標、個股分點
│   │   ├── screener/       #   篩選頁：條件建構器、結果表
│   │   ├── broker/         #   分點頁：分點視角、標籤管理
│   │   ├── strategy/       #   策略頁：策略清單、命中歷史
│   │   └── home/           #   首頁：自選股＋今日訊號
│   ├── layouts/            # AppShell（側欄導航＋內容區）
│   ├── routes.tsx
│   └── main.tsx
├── orval.config.ts
└── vite.config.ts          # dev proxy /api → localhost:8000、PWA 設定
```

- 判準：被兩個以上 feature 使用才進 `components/`，否則留在 feature 內。
- `src/api/` 為生成物，進 `.gitignore` 或標注生成 header，PR 不 review 其內容。

## 4. 設計系統落地（DESIGN.md ＋ design.md §10 覆蓋）

### 4.1 Tokens 落地方式

DESIGN.md 的色票、字階、間距、圓角全部轉為 `src/theme/tokens.css` 的 CSS variables，命名比照其語意（如 `--bg-canvas`、`--text-secondary`、`--border-subtle`）。元件一律引用 variables，**不得寫死色碼**。

### 4.2 台股在地化覆蓋（優先於 DESIGN.md 原文）

| 項目 | 規則 |
|---|---|
| 漲跌色 | **紅漲**（`#ef4444` 系）**綠跌**（`#10b981` 系），與歐美相反。此二色只用於漲跌、買賣超語意，**禁止**作裝飾或狀態色使用 |
| 品牌紫 | `#5e6ad2` / `#7170ff` 僅用於互動元素（CTA、選中態、連結），不與漲跌色混用 |
| 平盤 | 用中性文字色（`--text-secondary`），不套紅綠 |
| 表格密度 | 允許比 Linear 原版更小的行高（資料表 32px 級），維持「以邊框透明度分層」 |
| 字體 | Inter fallback 補 `"Noto Sans TC", "PingFang TC"`；所有數字欄位 `font-variant-numeric: tabular-nums` |

### 4.3 語意元件

漲跌呈現統一走 `<PriceChange value={} />` 元件（自動處理正負號、紅綠、平盤中性色、tabular-nums），**禁止**各頁自行上色，確保全站一致。

## 5. 資料層

### 5.1 契約流程

1. 後端起本機服務 → `npm run codegen`（orval 讀 `http://localhost:8000/openapi.json`）。
2. 生成 typed client＋TanStack Query hooks 至 `src/api/`。
3. 後端 schema 變動 → 重跑 codegen → TypeScript 編譯錯誤即契約漂移警報。

### 5.2 指示性 API 面（以 codegen 為準）

| 資料 | 假設端點 |
|---|---|
| 個股 K 線（含指標序列） | `GET /api/stocks/{id}/candles?adjusted=&indicators=` |
| 個股每日籌碼 | `GET /api/stocks/{id}/chips` |
| 個股分點買賣超 | `GET /api/stocks/{id}/broker-flows?date=` |
| 分點每日進出 | `GET /api/brokers/{id}/flows` |
| 分點標籤 CRUD | `GET/POST/DELETE /api/brokers/{id}/tags` |
| 篩選（即席） | `POST /api/screener/run`（body＝條件 JSON） |
| 條件 schema 能力表 | `GET /api/screener/capabilities`（可用指標、運算子、參數範圍——條件建構器據此**動態**長出 UI，不寫死） |
| 策略 CRUD | `GET/POST/PUT/DELETE /api/strategies` |
| 策略命中歷史 | `GET /api/strategies/{id}/hits` |
| 自選股 | `GET/POST/DELETE /api/watchlist` |

### 5.3 通用慣例

- **Loading**：skeleton（表格骨架列、圖表灰底），不用 spinner 全屏遮罩。
- **錯誤**：統一 `<QueryError retry={} />` 區塊級呈現；不彈全域 alert。
- **快取**：盤後資料一日一變，`staleTime` 可大方設長（小時級）；`POST /screener/run` 不快取。
- **空狀態**：分點類頁面的空狀態需區分「該日無資料」與「該日在本系統累積起始日之前」（呼應 design.md §3 分點自上線日累積）。

## 6. 路由表

| 路由 | 頁面 | 期別 |
|---|---|---|
| `/` | 首頁：自選股清單＋今日策略命中摘要 | 一 |
| `/stock/:id` | 個股頁（K 線＋指標＋籌碼＋分點個股視角） | 一 |
| `/screener` | 篩選頁（條件建構器＋結果表） | 一 |
| `/broker/:id` | 分點頁（單一分點進出＋標籤） | 一 |
| `/strategies` | 策略清單 | 一 |
| `/strategies/:id` | 策略詳情＋命中歷史 | 一 |
| `/backtest/...` | 回測 | 二（僅預留導航位，本期不做） |

## 7. 頁面規格

每頁共通：頂部麵包屑＋全域股票搜尋框（代號/名稱 typeahead，選定即跳 `/stock/:id`）。

### 7.1 AppShell

- 左側固定窄側欄（DESIGN.md Navigation 規格）：首頁、篩選、策略、（分點與個股頁由搜尋/連結進入，不佔側欄）。
- 側欄底部固定顯示「資料更新至 YYYY-MM-DD」（讀 pipeline 最後成功日），這是盤後工具最重要的全域狀態。

### 7.2 首頁 `/`

- 自選股表格：代號、名稱、收盤、漲跌（`<PriceChange>`）、成交量、三大法人買賣超。點列進個股頁。
- 「今日訊號」卡片：各策略當日命中檔數，點擊進策略詳情。
- 空自選股時的引導：提示用搜尋框加入。

### 7.3 個股頁 `/stock/:id`

第一期最重的頁面，上下三段：

1. **K 線區**（lightweight-charts）
   - 日 K＋成交量副圖；指標疊圖（MA 主圖；KD/MACD/RSI 副圖，可增減）。
   - **原始價／還原價切換**（design.md §7）：預設原始價；切換鈕旁固定 ⓘ：「還原價已調整除權息缺口；本站指標與回測一律以還原價計算」。
   - 區間選擇：3M / 6M / 1Y / 3Y / 全部。
2. **籌碼區**：三大法人買賣超（ECharts 柱狀，紅買綠賣）、融資券餘額走勢。欄位名附口語化 ⓘ（融資使用率、借券賣出餘額等，design.md §9）。
3. **分點區（個股視角）**
   - 當日買超/賣超分點 Top 15 兩欄表：分點名（帶標籤 badge）、買賣超張數、均價、佔當日成交量比。
   - 集中度指標（後端算好，前端只顯示）＋主力成本區。
   - 日期選擇器可回看歷史（限累積範圍內）。
   - 頁面固定標注：「分點資料為盤後公布，本系統自 YYYY-MM 起累積」（起始日讀 API）。
   - 點分點名 → `/broker/:id`。

### 7.4 篩選頁 `/screener`

- 左側**條件建構器**、右側結果表的雙欄佈局。
- 條件建構器輸出的**唯一產物是條件 JSON**（design.md §6 的 JSON 條件 schema），送 `POST /screener/run`；前端不解讀語意。
  - 可用條件（指標比較、連續 N 天、排名/佔比、分點行為）由 `/screener/capabilities` 動態驅動，後端加新指標時前端**零改動**。
  - 條件列可增刪、AND 群組（OR 等進階組合依 capabilities 宣告決定是否顯示）。
  - 每個指標參數旁 ⓘ 簡短定義（design.md §9）。
  - 篩選頁固定一行小字：「篩選條件以還原價計算」。
- 結果表：代號、名稱、收盤、漲跌、觸發值摘要；點列進個股頁。
- 「**存成策略**」按鈕：命名後 `POST /strategies`，成功後導向策略詳情——這是篩選頁與策略頁的銜接點。

### 7.5 分點頁 `/broker/:id`

- 標頭：分點名＋標籤 badges＋**標籤編輯**（增刪，選自既有標籤或新建；純手動，design.md 明確不做自動分類）。
- 每日進出時間軸：該分點各日買賣的股票明細表（股票、買賣超、均價），可按股票過濾。
- 近期動向摘要：近 5/20 日累計買賣超 Top 股票（ECharts 橫條）。
- 同樣固定標注資料累積起始日。

### 7.6 策略頁 `/strategies`、`/strategies/:id`

- 清單：策略名、條件摘要（由 JSON 渲染成人話的唯讀摘要）、最近命中日與檔數、啟用/停用開關。
- 詳情：
  - 條件唯讀展示＋「複製到篩選頁編輯」（帶 JSON 回 `/screener`，改完另存或覆蓋）。
  - **命中歷史**：按日分組的命中清單，附命中日收盤價與**其後 N 日報酬**（後端算），並固定 ⓘ：「命中歷史為前向紀錄，無前視偏差」。

## 8. 共用元件清單

| 元件 | 職責 |
|---|---|
| `<PriceChange>` | 漲跌數字：紅漲綠跌、平盤中性、正負號、tabular-nums（見 §4.3） |
| `<DataTable>` | 高密度表格：排序、sticky header、行高 32px、邊框透明度分層 |
| `<KLineChart>` | lightweight-charts wrapper：K 線＋量＋指標疊圖、台股紅漲綠跌 K 棒 |
| `<StatChart>` | ECharts wrapper：預注入 dark 主題與 tokens 色 |
| `<InfoHint>` | ⓘ tooltip，design.md §9 所有內建說明的唯一載體 |
| `<AdjustToggle>` | 原始價／還原價切換＋內建說明文案 |
| `<TagBadge>` / `<TagEditor>` | 分點標籤顯示與編輯 |
| `<StockSearch>` | 全域個股搜尋 typeahead |
| `<DateNav>` | 交易日日期選擇（跳過非交易日、限資料範圍） |
| `<EmptyState>` / `<QueryError>` | 空狀態（含分點累積起始日變體）與錯誤重試 |

## 9. PWA 與部署

- vite-plugin-pwa：manifest（名稱、dark 主題色、icon）＋ service worker **僅預快取 app shell**；API 回應不離線快取。
- RWD：桌面雙欄佈局在 `<768px` 摺疊為單欄、側欄收合為底部 tab；表格橫向捲動而非砍欄位。觸控目標依 DESIGN.md §8。
- 部署（承 design.md §4/§5）：`vite build` 靜態檔打進 FastAPI image，掛 `/`，API 走 `/api`；compose 無新增服務，LAN 同源安裝 PWA。

## 10. 實作里程碑

| 里程碑 | 內容 | 完成判準 |
|---|---|---|
| **M0 Scaffold** | Vite 專案、tokens.css、AppShell、路由骨架、orval codegen 管線、`<PriceChange>`/`<DataTable>`/`<InfoHint>` | `npm run codegen && npm run build` 全綠；空頁面可導航 |
| **M1 個股頁** | §7.3 全部＋`<KLineChart>`/`<AdjustToggle>` | 任一股票可看 K 線、切還原價、看籌碼與當日分點 |
| **M2 篩選頁** | §7.4＋條件建構器（capabilities 驅動） | 組條件→出結果→存成策略 |
| **M3 分點頁** | §7.5＋標籤編輯 | 追蹤一個分點的每日進出並上標籤 |
| **M4 首頁＋策略頁** | §7.2、§7.6 | 自選股、命中歷史可用；第一期 UI 完備 |
| **M5 收尾** | PWA、RWD 摺疊、§9 提示文案盤點 | 手機 LAN 安裝可用；design.md §9 清單逐項核對 |

順序理由：M1 先做是因為它逼出最多共用元件與 API 契約問題；篩選（M2）是策略（M4）的前置。

## 11. 明確不做（本期前端）

- Light mode、盤中即時更新（無 WebSocket）、前端指標計算、自動分點分類 UI、回測頁（僅留路由位）、多帳號/登入 UI。
