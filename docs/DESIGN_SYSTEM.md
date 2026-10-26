# 前端設計規範

本文是前端唯一的視覺與互動規範，所有前端工作（新頁面、改版、元件）都必須遵守；偏離要先在 Issue 說明並經統籌同意。token 與元件規則源自 UI/UX Pro Max 的 investment-platform demo，以本文為準。

頁面資訊架構與各頁內容見 [PRODUCT_SPEC §2](PRODUCT_SPEC.md#2-主導航與資訊順序)、文案與單位見 [UI_COPY_SPEC](UI_COPY_SPEC.md)。

## 1. 整體氛圍

- **深色金融儀表板**：近黑的藍灰底、分層的卡片、細白邊線、單一藍色主色，資料數字用等寬字。安靜、專業、以數字為主角，不用插圖與大面積彩色。
- **層次靠底色而非陰影**：頁面底 → 區塊底 → 卡片 → 浮起元素四層底色；陰影只在 hover 與主按鈕出現。
- **點綴而非裝飾**：漸層只用在 logo、標題關鍵字（`gradient-text`）與主按鈕；不用背景柔光（blur 光暈）。
- **一眼可讀的漲跌**：漲跌只靠顏色與正負號，不加箭頭圖示或閃爍。數值與價位的紅綠只用於漲跌（台股慣例紅漲綠跌）；進出點等其他數值與價位語意不用紅綠（§7）。例外：狀態 badge 的 success／error 變體（§5，如「行情來源完整」）與籌碼理由色點的 `--color-secondary`（§7）表示狀態或分類，不是數值方向。
- **桌面優先、窄版可用**：內容寬 1280px 居中，16px 側邊留白，手機單欄。

## 2. Design tokens

所有顏色、字體、圓角、間距一律透過 CSS 變數使用，不得在元件內寫死色碼。以下為 `frontend/src/styles/tokens.css` 的規範內容；實作時以本節為準建立或更新該檔。

```css
:root {
  /* 色彩 */
  --color-primary: #3b82f6;        /* 主色：按鈕、連結、選取、圖表主線 */
  --color-primary-dark: #2563eb;   /* 主按鈕漸層終點、hover */
  --color-accent: #8b5cf6;         /* 強調：漸層另一端、第二序列 */
  --color-secondary: #10b981;      /* 次要資訊色：正向狀態、第二漸層 */
  --color-success: #22c55e;        /* 成功／正向狀態 */
  --color-warning: #f59e0b;        /* 警示、資料延遲 */
  --color-error: #ef4444;          /* 錯誤／負向狀態 */

  --color-up: #ef4444;             /* 台股慣例：漲為紅 */
  --color-down: #22c55e;           /* 台股慣例：跌為綠 */
  --color-flat: #9ca3af;           /* 平盤、無變化 */

  --color-bg: #0b0f1a;             /* 頁面底 */
  --color-bg-alt: #111827;         /* 交錯區塊底、側欄 */
  --color-bg-card: #1f2937;        /* 卡片 */
  --color-bg-elevated: #374151;    /* 卡片內浮起元素、次要按鈕底、hover 列 */
  --color-border: rgba(255, 255, 255, 0.10);
  --color-border-hover: rgba(255, 255, 255, 0.20);

  --color-text: #f9fafb;           /* 主文字 */
  --color-text-muted: #9ca3af;     /* 說明、標籤、表頭 */
  --color-text-subtle: #6b7280;    /* 註腳、停用 */
  --color-on-primary: #ffffff;     /* 主按鈕文字、logo 圖示 */
  --color-primary-soft: rgba(59, 130, 246, 0.20); /* feature-card 圖示底、選取底 */
  --color-nav-bg: rgba(11, 15, 26, 0.95);         /* Navbar 底 */
  --color-overlay: rgba(0, 0, 0, 0.68);           /* modal 遮罩 */

  /* 圖表（§6；ECharts 於執行時讀取這些變數） */
  --chart-grid: rgba(255, 255, 255, 0.06);
  --chart-ma5: #f59e0b;
  --chart-ma10: #8b5cf6;
  --chart-ma20: #3b82f6;
  --chart-ma60: #10b981;
  --chart-ma120: #9ca3af;

  /* 字體 */
  --font-heading: "Inter", "Noto Sans TC", system-ui, sans-serif;
  --font-body: "Inter", "Noto Sans TC", system-ui, sans-serif;
  --font-mono: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;

  /* 圓角 */
  --radius-sm: 8px;    /* 標籤、小按鈕、輸入框 */
  --radius-md: 10px;   /* 按鈕 */
  --radius-lg: 12px;   /* 小 widget、表格容器 */
  --radius-xl: 16px;   /* 卡片 */
  --radius-pill: 50px; /* badge */

  /* 間距（4px 基準） */
  --space-1: 4px;  --space-2: 8px;  --space-3: 12px; --space-4: 16px;
  --space-5: 20px; --space-6: 24px; --space-8: 32px; --space-10: 40px;
  --space-12: 48px; --space-16: 64px; --space-24: 96px;

  /* 版面 */
  --content-max: 1280px;
  --nav-height: 64px;

  /* 動效 */
  --transition: all 0.3s ease;
  --shadow-hover: 0 20px 40px rgba(59, 130, 246, 0.15);
  --shadow-btn: 0 8px 24px rgba(59, 130, 246, 0.40);
}

@media (prefers-reduced-motion: reduce) {
  :root { --transition: none; }
}
```

字體載入：`frontend/index.html` 以 Google Fonts 載入 `Inter:wght@400;500;600;700` 與 `JetBrains+Mono:wght@400;500;600;700`（§3 的數字用到 600／700）；中文備用字體用 `Noto Sans TC`（`400;500;700`）。只允許 Inter 當標題與內文、JetBrains Mono 當數字。

## 3. 字級與數字

| 用途 | 字級／字重 | 說明 |
| --- | --- | --- |
| 頁面標題 h1 | 28px／700 | 今日頁不放頁面大標，第一行是頁首資料列（§4） |
| 區塊標題 h2 | 30–36px／700 | 置中或靠左，下方 8px 說明文字（muted，18px） |
| 卡片標題 h3 | 20px／600 | |
| 內文 | 16px／400 | 說明文字用 `--color-text-muted` |
| 標籤、表頭、註腳 | 14px／500；註腳 12px | 表頭 muted，不全大寫 |
| 主要數字（股價、淨值） | 30–36px／700，`--font-mono` | 卡片一個主數字 |
| 次要數字（表格、統計） | 14–16px／500–600，`--font-mono`，`tabular-nums` | 靠右對齊 |
| 漲跌 | 同欄位字級／600 | 色依 `--color-up`／`--color-down`／`--color-flat`，正數帶 `+` |

所有金額與百分比用 `font-variant-numeric: tabular-nums` 對齊；千分位逗號。同一欄（表格的一欄、同類卡片的同一欄位）小數位數固定，不因數值而去掉尾端 0（`21.10` 不寫 `21.1`）：

| 數值 | 位數 |
| --- | --- |
| 單一標的的價格（K 線表、個股頁、行動卡收盤與漲跌） | 依該標的最近收盤的 tick（`priceDigits`）：50 元以下 2 位、50～500 元 1 位、500 元以上 0 位；ETF 2 位。漲跌金額與收盤同位數 |
| 跨標的的價格欄（個股清單、族群成員） | 2 位 |
| 規則算出的價位（進場、觸發、停損、目標） | 2 位 |
| 百分比 | 2 位（另有規定者依 [UI_COPY_SPEC](UI_COPY_SPEC.md)） |
| 張數、筆數、檔數、日數 | 整數；張的換算見 [UI_COPY_SPEC §8.3](UI_COPY_SPEC.md#83-張零股) |

## 4. 版面與導航

- **Navbar**：固定頂部，高 64px，`backdrop-filter: blur(20px)`，底色 `--color-nav-bg`，下緣 1px `--color-border`。左側 40px 圓角 logo（主色→強調色漸層方塊＋白色折線圖示）加產品名；中間五個主導航連結（今日、新聞、族群、個股、行動），顏色 muted、hover 轉主文字色、當前頁主文字色加 2px 主色底線；右側放搜尋（代號／名稱）與資料日期 badge。手機收成漢堡選單。
- **內容容器**：`max-width: var(--content-max)`，左右 padding 16／24／32px（手機／平板／桌面）。
- **區塊**：垂直 padding 64px，桌面 96px；相鄰區塊以 `--color-bg` 與 `--color-bg-alt` 交錯。
- **網格**：卡片列用 CSS grid，桌面 2–4 欄、平板 2 欄、手機 1 欄，gap 16–24px。
- **今日頁頁首**：沒有 hero 與光暈。第一行是一行資料列（資料截至日期 · 來源 · 快照模式 · 品質 badge · 「資料說明」展開），其下是大盤概況列：四個雙列 `market-widget`（加權指數、櫃買指數、成交金額、漲跌家數），桌面一列四格（約 90px 高）；640px 以下只顯示兩個指數，成交金額與漲跌家數收進「成交金額與漲跌家數」`<details>`。之後依序為持倉風險提示列（有才出現）、明日候選、熱門族群與重點新聞（桌面兩欄）、關注標的（[PRODUCT_SPEC §2](PRODUCT_SPEC.md#2-主導航與資訊順序)）。全部收合時，1280×800 第一屏要看到至少 6 列候選、390×844 至少 2 張候選卡。

## 5. 元件

| 元件 | 規則 |
| --- | --- |
| `card` | 底 `--color-bg-card`、1px `--color-border`、圓角 16px、padding 24px；hover 邊線轉 `--color-border-hover`。資料卡用它。 |
| `feature-card` | 同 card，可點擊；hover 邊線轉主色、上移 4px、陰影 `--shadow-hover`。左上 48px 圓角 12px 圖示底（主色 20% 透明），圖示用主色線條。 |
| `market-widget` | 小型數據方塊：底 card 色、圓角 12px、padding 16px；上方 muted 標籤，中間 mono 主數字，下方漲跌。**雙列變體**（今日頁大盤概況）：標籤右側放單位，內容分上市、上櫃兩行，每行前置 muted 的「上市」「上櫃」，數字 mono、不換行，成交金額的金額後接 muted 短範圍（[UI_COPY_SPEC §11](UI_COPY_SPEC.md#11-今日頁頁首與大盤概況)）；某一邊沒有資料時該行改為 muted 文案，另一行照常。 |
| 候選列表 | 今日頁「明日候選」。桌面（641px 以上）用共用 `DataTable`：一檔一列，數字欄（收盤、進場區、停損、目標、RR、總分）不換行；每列最後一欄是「AI 推論 ▸」accent badge 按鈕，展開時在該列下方插入一列整列寬（`colSpan`）的明細列，明細列內容放在 `<details>` 裡（按鈕切換它，未展開時明細列沒有高度）。640px 以下改為一檔一張卡片，不用橫向捲動表格：名次＋代號名稱＋總分 → 市場 · 策略 · 族群 → 收盤／進場區／停損／目標四格（價位不換行；目標放不下時整格自成一列）→ 主要理由 → 「AI 說明」`<details>`。預設列前 10 檔，其餘收進「顯示其餘 N 檔」`<details>`。 |
| 族群成員表 | 族群詳情「族群成員」（文案與欄位見 [UI_COPY_SPEC §8.5](UI_COPY_SPEC.md#85-族群榜與族群詳情)）。表上方右側一個「排序」`filter-select`。桌面（641px 以上）用共用 `DataTable`：數字欄（收盤、漲跌幅、成交值、5 日相對、20 日相對）不換行，名稱欄可換行，狀態 badge 用 compact 尺寸接在名稱後（「候選 #N」primary，「條件成立」「領先成員」預設樣式）；不同日的「資料 YYYY/MM/DD」放在收盤格第二行，12px muted。640px 以下一檔一張卡片，不用橫向捲動表格：標題列左側代號名稱與 badge、右側收盤與漲跌幅（mono，不換行；不同日的日期在收盤下）→ 第二列成交值、5 日相對、20 日相對三格（muted 標籤在上、mono 數字在下）→ 題材榜另一行證據。卡片沿用 card 的底色與邊線，圓角 12px、padding 12px 16px。 |
| 提示列 | 整列寬的 card（圓角 12px、padding 12px 16px），左側 4px 色條（同 Toast，持倉風險用 warning）；一行文字加右側 ghost 連結，窄版可換行。用於今日頁持倉風險提示，有資料才出現。 |
| `stat-value` | 統計數字：mono、24px、600。 |
| `badge` | 膠囊：底 card 色、1px 邊、圓角 50px、padding 6px 14px、14px 字；狀態變體把文字與邊線改成 success／primary／warning／error；`accent` 變體（只用於「AI 推論」）邊線與圓點用 `--color-accent`、文字維持主文字色以保對比。前面可放 8px 圓點（活躍狀態加 `animate-pulse`）。 |
| `btn-primary` | 漸層 `135deg, --color-primary → --color-primary-dark`，白字 600，圓角 10px，padding 14px 28px；hover 上移 2px 加 `--shadow-btn`。每個畫面最多一個主按鈕。 |
| `btn-secondary` | 透明底、1px `--color-border`、主文字色，圓角 10px；hover 底轉 card 色、邊線轉主文字色。 |
| `btn-ghost` | 無邊無底 muted 文字，hover 轉主文字色；用於導航與表格內動作。 |
| 表格 | 容器用 card；表頭 14px muted、底邊 1px；列高 56px、底邊 1px `--color-border`、最後一列無邊；hover 列底 `--color-bg-elevated`；每列右側可放一個小的 `btn-primary`（text-sm、padding 8px 16px）或 ghost 連結。數字欄的表頭與內容一起靠右（同一個 `num` class，由共用 `DataTable` 的欄位定義同時套到 th 與 td），內容 mono、`tabular-nums`、不換行；文字欄靠左，可換行。窄版規則見 §5.1。 |
| 列表項（個股列） | 左：40px 圓角方塊顯示代號前綴或產業縮寫（`--color-bg-elevated`）＋代號（600）與名稱（muted 14px）；右：價格（mono）與漲跌（色＋正負號）。 |
| 輸入框 | 底 `--color-bg-alt`、1px 邊、圓角 8px、padding 12px 16px；focus 邊線轉主色，無外框光暈。 |
| 分頁籤（tabs） | 文字 tabs，選中者主文字色加 2px 主色底線；用於指標面板（MACD／RSI／KD／布林）、新聞國內／國際／官方公告、族群產業／題材。 |
| 空狀態 | 卡片內置中 muted 文字「無資料」加一行原因（如「日線不足 60 根」），不用插圖。 |
| 載入 | 卡片骨架（`--color-bg-elevated` 條塊，淡入淡出），不用旋轉圖示。 |
| Toast／錯誤 | 右上角 card 樣式，左側 4px 色條（success／warning／error）。 |

### 5.1 窄版與卡片內的表格

- 表格寬度依內容，不設固定最小寬度；容器 `overflow-x: auto`，欄位放不下時只在表格內橫向捲動，頁面本身不得出現橫向捲動。
- 儲存格預設不換行，避免中文被擠成一字一行；只有長文字欄（子項說明、族群名稱）標記可換行（`DataTable` 欄位 `wrap`）。
- 640px 以下：儲存格左右 padding 8px、列高 44px；第一欄（日期、代號或子項名）固定在左側（`position: sticky`），捲動時仍看得到這一列是什麼；關鍵數字欄（收盤、買賣超）要在第一屏看得到，次要文字欄（交易所、類型、角色等）可在此寬度隱藏（欄位 `wideOnly`），完整內容在桌面版與詳情頁。
- 卡片內的表格（例如候選卡的評分細節）至多 4 欄，分組標題放在獨立的整列（`colSpan`），不另占一欄，讓數字欄在 390px 寬的卡片內完整可見。
- 欄位多、需要逐列比較的榜單（族群榜）在 640px 以下改用卡片呈現。

## 6. 圖表（ECharts）

- 圖表顏色同樣只來自 tokens：ECharts 畫在 canvas 上不能解析 `var()`，元件在執行時以 `getComputedStyle(document.documentElement)` 讀取 §2 的變數再傳給 option。
- 背景透明，格線 `--chart-grid`，軸文字 `--color-text-muted` 12px mono。
- K 線：漲 `--color-up`、跌 `--color-down`，實體與影線同色；成交量柱同漲跌色、60% 透明。
- 均線固定色：MA5 `--chart-ma5`（`#f59e0b`）、MA10 `--chart-ma10`（`#8b5cf6`）、MA20 `--chart-ma20`（`#3b82f6`）、MA60 `--chart-ma60`（`#10b981`）、MA120 `--chart-ma120`（`#9ca3af`）。布林面板：中軌主色、上下軌強調色、收盤線 muted。
- 指標面板（MACD／RSI／KD／布林）置於主圖下方，高度為主圖 35%，共用 x 軸與 dataZoom；MACD 柱用漲跌色，DIF／DEA 用主色與強調色；RSI／KD 參考線（20／80、30／70）用 `--color-text-subtle` 虛線。
- 單線圖（熱度走勢、淨值）：主色線寬 2px，下方用主色漸層填充（頂部 25% 透明到底部 0）。
- Tooltip：底 `--color-bg-card`、1px 邊、圓角 8px、mono 數字；滑鼠十字線 `--color-text-subtle`。
- 資料日期一律顯示在圖右上角 badge。

## 7. 資料與狀態的視覺語言

- 每張資料卡右上角 badge 顯示資料日期（如「資料 10/17」）；排程更新中顯示 warning badge「更新中」。
- 無資料：欄位留空顯示「—」加 muted 原因，不顯示 0。
- LLM 推論內容：左側 2px 強調色（`--color-accent`）豎線加「AI 推論」小 badge，與事實分區。
- 進出點（全站：今日候選、個股頁候選面板與研究條件、行動頁卡片與行動詳情）：進場區主文字色 mono（`.level-entry`）；停損 `--color-warning`（`.level-stop`）；目標 `--color-primary`（`.level-target`）；RR 用 badge；每個價位都帶文字標籤。紅綠只用於漲跌，進出點不用 `--color-error`／`--color-success`，以免讀成漲跌。
- 候選清單理由：照 API 順序（`candidate_score_v1` 每檔最多四條），每條一行，前綴 8px 色點（技術 primary、籌碼 secondary、新聞 accent、族群 `--color-text-muted`）；`inference=true` 的理由同列加「推論」badge（accent 變體）。今日頁列表只顯示第一條，展開明細顯示全部；個股頁候選面板顯示全部。

## 8. 無障礙與動效

- 文字對比至少 4.5:1；muted 文字只用於 14px 以上。
- 所有互動元件有 `:focus-visible` 外框（2px 主色、offset 2px）。
- 動效只用 transform 與 opacity，時長 200–300ms；`prefers-reduced-motion` 時全部關閉。
- 圖示用 24px 線條 SVG（stroke 2，`currentColor`），不用彩色圖示或 emoji。

## 9. 實作規則

- 樣式以 Tailwind utility 搭配上述 CSS 變數（`text-[var(--color-text-muted)]` 形式）或等價的 CSS class；禁止元件內 inline 色碼。色碼字面值（`#rgb`、`rgb()`、`rgba()`、`hsl()`）只出現在 `frontend/src/styles/tokens.css`，由 `frontend/src/noHardcodedColors.test.ts` 檢查。
- 共用元件放 `frontend/src/components/ui/`（Card、Badge、Button、Table、Tabs、Stat、EmptyState、Skeleton），頁面只組裝不重畫。
- 新元件先查本文是否已有對應規則；沒有就先補本文再實作。
- PR 附桌面（1280px）與手機（390px）截圖各一張，確認符合本文。
