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
| 建置 | Vite + React 19 + TypeScript（strict） | 純 SPA，無 SSR |
| 路由 | React Router v7（library mode） | 見 §6 路由表 |
| 伺服器狀態 | TanStack Query v5 | 所有 API 資料的唯一通道 |
| UI 狀態 | React 內建 state | 夠用前不引入全域狀態庫 |
| API client | orval（讀版控的 `openapi.json` snapshot，見 §5.1）| 產 typed client + Query hooks，`npm run codegen` |
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
- `src/api/` 為生成物，進 `.gitignore`，PR 不 review 其內容；`frontend/openapi.json` snapshot 則**進版控**（見 §5.1），fresh clone / CI 不需活的後端即可 codegen＋build。

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
| Monospace | **不採購 Berkeley Mono**（商用字體），直接用 DESIGN.md 的 fallback 鏈 `ui-monospace, "SF Mono", Menlo`；數字表格走 Inter＋tabular-nums，不依賴 mono |

### 4.3 語意元件

漲跌呈現統一走 `<PriceChange value={} />` 元件（自動處理正負號、紅綠、平盤中性色、tabular-nums），**禁止**各頁自行上色，確保全站一致。

## 5. 資料層

### 5.1 契約流程

1. repo 版控一份 `frontend/openapi.json` snapshot；orval 讀此**本地檔**，`npm run codegen` 與 `npm run build` 皆不依賴活的後端（M0 因此不被後端進度卡住）。
2. `npm run codegen` 生成 typed client＋TanStack Query hooks 至 `src/api/`。
3. 後端 schema 變動 → 起本機後端跑 `npm run openapi:pull`（抓 `http://localhost:8000/openapi.json` 覆蓋 snapshot）→ 重跑 codegen → TypeScript 編譯錯誤即契約漂移警報；snapshot 的 diff 進 PR 一併 review。

### 5.2 指示性 API 面（以 codegen 為準）

| 資料 | 假設端點 |
|---|---|
| 個股 K 線（含指標序列） | `GET /api/stocks/{id}/candles?adjusted=&indicators=`（指標序列**跟隨 `adjusted` 參數**用同一價格序列計算，見 §7.3 與 design.md §7） |
| 個股每日籌碼 | `GET /api/stocks/{id}/chips` |
| 個股分點買賣超 | `GET /api/stocks/{id}/broker-flows?date=` |
| 分點清單／搜尋 | `GET /api/brokers?q=&tag=`（§7.5 分點清單頁：依名稱搜尋、依標籤過濾） |
| 分點每日進出 | `GET /api/brokers/{id}/flows` |
| 分點標籤 CRUD | `GET/POST/DELETE /api/brokers/{id}/tags` |
| 篩選（即席） | `POST /api/screener/run`（body＝條件 JSON；回應每檔**須含觸發值摘要**——各條件實際命中的數值，供結果表顯示） |
| 條件 schema 能力表 | `GET /api/screener/capabilities`（可用指標、運算子、參數範圍——條件建構器據此**動態**長出 UI，不寫死） |
| 策略 CRUD | `GET/POST/PUT/DELETE /api/strategies`（清單／詳情回應含**後端生成的人話條件摘要** `summary`；詳情另含**原始條件 JSON**，供 §7.7「複製到篩選頁編輯」回填建構器） |
| 策略命中歷史 | `GET /api/strategies/{id}/hits`（每筆附命中日收盤與**固定 5/10/20 日後報酬**三欄） |
| 每日訊號摘要 | `GET /api/signals?date=`（各策略該日命中檔數——首頁「訊號」卡的來源，不從策略清單拼裝） |
| 自選股 | `GET/POST/DELETE /api/watchlist`（GET 回應**含最後資料日行情快照**：收盤、漲跌、漲跌幅、成交量、三大法人買賣超——首頁表格一次拿齊，不做 N+1） |
| 系統 meta | `GET /api/meta`（pipeline 最後成功日、分點累積起始日、資料起訖範圍——§7.1 側欄與 §7.3/§7.6 標注的來源） |
| 交易日曆 | `GET /api/calendar?from=&to=`（`<DateNav>` 跳過非交易日、限資料範圍用） |
| 個股搜尋 | `GET /api/stocks/search?q=`（`<StockSearch>` typeahead，代號/名稱） |
| 標籤清單（全域） | `GET /api/tags`（`<TagEditor>`「選自既有標籤」的來源） |

### 5.3 通用慣例

- **Loading**：skeleton（表格骨架列、圖表灰底），不用 spinner 全屏遮罩。
- **錯誤**：統一 `<QueryError retry={} />` 區塊級呈現；不彈全域 alert。
- **快取**：盤後資料一日一變，`staleTime` 可大方設長（小時級）；`POST /screener/run` 不快取。例外：`/api/meta` 用短 `staleTime`（分鐘級）——pipeline 傍晚起每小時重試（design.md §5），使用中資料可能更新，「資料更新至」不能顯示舊值。
- **空狀態**：分點類頁面的空狀態需區分「該日無資料」與「該日在本系統累積起始日之前」（呼應 design.md §3 分點自上線日累積）。
- **「今日／當日」語意**：全站所有「今日／當日」一律指 **`/api/meta` 的 pipeline 最後成功日**，不是日曆上的今天（週末、假日、傍晚 pipeline 未跑完時兩者不同）。UI 顯示這類資料時**標示實際資料日期**（如「07/04 訊號」），不寫「今日」二字，避免週一早上把上週五資料誤讀為新資料。
- **數字格式**：千分位、張／萬張、億元等縮寫規則統一收在 `src/lib/format.ts`，各頁**不得**自行格式化（與 §4.3 禁止各頁自行上色同一精神）。

## 6. 路由表

| 路由 | 頁面 | 期別 |
|---|---|---|
| `/` | 首頁：自選股清單＋今日策略命中摘要 | 一 |
| `/stock/:id` | 個股頁（K 線＋指標＋籌碼＋分點個股視角） | 一 |
| `/screener` | 篩選頁（條件建構器＋結果表） | 一 |
| `/brokers` | 分點清單（已標籤分點＋分點搜尋——分點功能的常駐入口） | 一 |
| `/broker/:id` | 分點頁（單一分點進出＋標籤） | 一 |
| `/strategies` | 策略清單 | 一 |
| `/strategies/:id` | 策略詳情＋命中歷史 | 一 |
| `/backtest/...` | 回測 | 二（僅預留導航位，本期不做） |

## 7. 頁面規格

每頁共通：頂部麵包屑＋全域股票搜尋框（代號/名稱 typeahead，選定即跳 `/stock/:id`）。

### 7.1 AppShell

- 左側固定窄側欄（DESIGN.md Navigation 規格）：首頁、篩選、分點（`/brokers`）、策略。個股頁不佔側欄，由搜尋/連結進入。
- 側欄底部固定顯示「資料更新至 YYYY-MM-DD」（讀 `/api/meta` 的 pipeline 最後成功日），這是盤後工具最重要的全域狀態。

### 7.2 首頁 `/`

- 自選股表格：代號、名稱、收盤、漲跌與漲跌幅（`<PriceChange>` 含 % 模式）、成交量、三大法人買賣超。資料一次來自 `GET /api/watchlist` 的行情快照（§5.2）。點列進個股頁。
- 「訊號」卡片：各策略於最後資料日的命中檔數（來源 `GET /api/signals`），卡片標題**標示實際資料日期**（§5.3「今日」語意），點擊進策略詳情。
- 空自選股時的引導：提示用搜尋框加入。

### 7.3 個股頁 `/stock/:id`

第一期最重的頁面，上下三段：

1. **K 線區**（lightweight-charts）
   - 日 K＋成交量副圖；指標疊圖（MA 主圖；KD/MACD/RSI 副圖，可增減）。
   - **圖表指標跟隨顯示價格**（design.md §7）：指標序列隨 `adjusted` 參數與 K 棒用同一價格序列計算（否則還原價 MA 疊在原始價 K 棒上會因除權息缺口浮空）；篩選與回測仍一律還原價。
   - 指標**參數組第一期固定**：MA(5, 20, 60)、KD(9, 3, 3)、MACD(12, 26, 9)、RSI(14)；只能增減指標，不能改參數（參數自訂列 §11 不做）。各指標旁 ⓘ 附簡短定義含所用參數（design.md §9）。
   - **原始價／還原價切換**（design.md §7）：預設原始價；切換鈕旁固定 ⓘ：「還原價已調整除權息缺口；圖表指標隨當前價格計算，篩選與回測一律以還原價計算」。
   - 區間選擇：3M / 6M / 1Y / 3Y / 全部。
2. **籌碼區**：三大法人買賣超（ECharts 柱狀，紅買綠賣）、融資券餘額走勢。欄位名附口語化 ⓘ（融資使用率、借券賣出餘額等，design.md §9）。
3. **分點區（個股視角）**
   - 當日買超/賣超分點 Top 15 兩欄表：分點名（帶標籤 badge）、買賣超張數、均價、佔當日成交量比。
   - 集中度指標（後端算好，前端只顯示）＋主力成本區：第一期皆以**數字卡**呈現（成本區為價格區間文字，如「512–538」）；疊加到 K 線圖為第二期（§11）。
   - 日期選擇器可回看歷史（限累積範圍內）。
   - 頁面固定標注：「分點資料為盤後公布，本系統自 YYYY-MM 起累積」（起始日讀 `/api/meta`）。
   - 點分點名 → `/broker/:id`。

### 7.4 篩選頁 `/screener`

- 左側**條件建構器**、右側結果表的雙欄佈局。
- 條件建構器是條件 JSON（design.md §6 的 JSON 條件 schema）的**雙向編輯器**：UI state ↔ JSON——向外送 `POST /screener/run`，向內接受既有策略的 JSON 回填（§7.7）。前端因此**懂 JSON 的結構**（欄位、巢狀），但**不解讀篩選語意**（不算指標、不複製比較邏輯）；結構知識僅來自 `/screener/capabilities`，不寫死。
  - 可用條件（指標比較、連續 N 天、排名/佔比、分點行為）由 capabilities 動態驅動，後端加新指標時前端**零改動**。
  - **降級規則**：回填的 JSON 若引用 capabilities 已不宣告的指標/運算子，該條件列以唯讀「不支援的條件」呈現（顯示原始 JSON 片段），可刪除、不可編輯，其餘條件照常編輯。
  - 條件列可增刪、AND 群組（OR 等進階組合依 capabilities 宣告決定是否顯示）。
  - 每個指標參數旁 ⓘ 簡短定義（design.md §9）。
  - 篩選頁固定一行小字：「篩選條件以還原價計算」。
- 結果表：代號、名稱、收盤、漲跌與漲跌幅、觸發值摘要（後端回傳，§5.2）；點列進個股頁。
  - **筆數上限**：`/screener/run` 由後端限制回傳筆數（上限 500，超出時回應標示截斷、前端顯示「符合逾 500 檔，請縮小條件」）；前端不做分頁、不做虛擬捲動（§11）。
- 「**存成策略**」按鈕：命名後 `POST /strategies`，成功後導向策略詳情——這是篩選頁與策略頁的銜接點。

### 7.5 分點清單 `/brokers`

分點功能的常駐入口（側欄項）——沒有它，`/broker/:id` 只能從個股頁 Top 15 進入，上過標籤的分點隔天無路可回。

- 預設顯示**已標籤分點**清單：分點名、標籤 badges、近 5 日累計買賣超金額；點列進 `/broker/:id`。
- 頂部分點搜尋框（名稱 typeahead，`GET /api/brokers?q=`）＋標籤過濾 chips。
- 空狀態（尚無任何標籤時）：引導文案「從個股頁的分點表點進分點，為它上第一個標籤」。

### 7.6 分點頁 `/broker/:id`

- 標頭：分點名＋標籤 badges＋**標籤編輯**（增刪，選自既有標籤或新建；純手動，design.md 明確不做自動分類）。
- 每日進出時間軸：該分點各日買賣的股票明細表（股票、買賣超、均價），可按股票過濾。
- 近期動向摘要：近 5/20 日累計買賣超 Top 股票（ECharts 橫條）。
- 同樣固定標注資料累積起始日。

### 7.7 策略頁 `/strategies`、`/strategies/:id`

- 清單：策略名、條件摘要（顯示**後端回傳的 `summary` 字串**——前端不解讀 JSON 語意，維持 §7.4「零改動」原則；摘要生成屬後端職責）、最近命中日與檔數、啟用/停用開關。
- 詳情：
  - 條件唯讀展示（同樣用後端 `summary`）＋「複製到篩選頁編輯」：導向 `/screener?strategy=:id`，篩選頁據 query param 抓該策略詳情的**原始條件 JSON**（§5.2）灌入建構器（重新整理不掉），改完另存新策略或覆蓋原策略。回填時遇已不支援的條件，依 §7.4 降級規則處理。
  - **命中歷史**：按日分組的命中清單，附命中日收盤價與**其後 5/10/20 日報酬**三欄（後端算；未滿 N 日者該欄空白），並固定 ⓘ：「命中歷史為前向紀錄，無前視偏差」。

## 8. 共用元件清單

| 元件 | 職責 |
|---|---|
| `<PriceChange>` | 漲跌數字：紅漲綠跌、平盤中性、正負號、tabular-nums（見 §4.3）；兩種模式——僅漲跌值／值＋漲跌幅 %（首頁與結果表用後者） |
| `<DataTable>` | 高密度表格：排序、sticky header、行高 32px、邊框透明度分層 |
| `<KLineChart>` | lightweight-charts wrapper：K 線＋量＋指標疊圖、台股紅漲綠跌 K 棒 |
| `<StatChart>` | ECharts wrapper：預注入 dark 主題與 tokens 色 |
| `<InfoHint>` | ⓘ tooltip，design.md §9 所有內建說明的唯一載體 |
| `<AdjustToggle>` | 原始價／還原價切換＋內建說明文案 |
| `<TagBadge>` / `<TagEditor>` | 分點標籤顯示與編輯 |
| `<StockSearch>` | 全域個股搜尋 typeahead |
| `<DateNav>` | 交易日日期選擇（跳過非交易日、限資料範圍） |
| `<EmptyState>` / `<QueryError>` | 空狀態（含分點累積起始日變體）與錯誤重試 |

另：數字格式統一走 `src/lib/format.ts`（§5.3），不屬元件但同為「全站一致」的強制共用點。

## 9. PWA 與部署

- vite-plugin-pwa：manifest（名稱、dark 主題色、icon）＋ service worker **僅預快取 app shell**；API 回應不離線快取。
- RWD：桌面雙欄佈局在 `<768px` 摺疊為單欄、側欄收合為底部 tab；表格橫向捲動而非砍欄位。觸控目標依 DESIGN.md §8。
- 部署（承 design.md §4/§5）：`vite build` 靜態檔打進 FastAPI image，掛 `/`，API 走 `/api`；compose 無新增服務，LAN 同源安裝 PWA。

## 10. 實作里程碑

| 里程碑 | 內容 | 完成判準 |
|---|---|---|
| **M0 Scaffold** | Vite 專案、tokens.css、AppShell、路由骨架、orval codegen 管線（含首版 `openapi.json` snapshot，後端未就緒時可先手寫最小 snapshot 佔位）、`<PriceChange>`/`<DataTable>`/`<InfoHint>` | `npm run codegen && npm run build` 全綠（不依賴活的後端）；空頁面可導航 |
| **M1 個股頁** | §7.3 全部＋`<KLineChart>`/`<AdjustToggle>` | 任一股票可看 K 線、切還原價、看籌碼與當日分點 |
| **M2 篩選頁** | §7.4＋條件建構器（capabilities 驅動） | 組條件→出結果→存成策略 |
| **M3 分點頁** | §7.5、§7.6＋標籤編輯 | 追蹤一個分點的每日進出並上標籤，隔天可從分點清單直接回訪 |
| **M4 首頁＋策略頁** | §7.2、§7.7 | 自選股、命中歷史可用；第一期 UI 完備 |
| **M5 收尾** | PWA、RWD 摺疊、§9 提示文案盤點 | 手機 LAN 安裝可用；design.md §9 清單逐項核對 |

順序理由：M1 先做是因為它逼出最多共用元件與 API 契約問題；篩選（M2）是策略（M4）的前置。

## 11. 明確不做（本期前端）

- Light mode、盤中即時更新（無 WebSocket）、前端指標計算、自動分點分類 UI、回測頁（僅留路由位）、多帳號/登入 UI。
- 指標**參數自訂**（第一期固定預設參數組，見 §7.3）。
- 標籤的**全域管理**（改名、刪除整個標籤並連動所有分點）——第一期只有分點層級的增刪（§7.6）。
- 篩選結果**分頁／虛擬捲動**（以後端 500 筆上限代替，見 §7.4）。
- 主力成本區**疊加至 K 線圖**（第一期數字卡呈現，見 §7.3）。
