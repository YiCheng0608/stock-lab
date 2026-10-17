# 前端設計規範

本文是前端唯一的視覺與互動規範，所有前端工作（新頁面、改版、元件）都必須遵守；偏離要先在 Issue 說明並經統籌同意。參考範本為 UI/UX Pro Max 的 investment-platform demo（`https://uupm.cc/demo/investment-platform`，2026-10-17 取樣），本文已把它的 token 與元件規則轉寫為本專案可直接使用的版本，開發時以本文為準、不必再回去看範本。

頁面資訊架構與各頁內容見 [PRODUCT_SPEC §2](PRODUCT_SPEC.md#2-主導航與資訊順序)、文案與單位見 [UI_COPY_SPEC](UI_COPY_SPEC.md)。

## 1. 整體氛圍

- **深色金融儀表板**：近黑的藍灰底、分層的卡片、細白邊線、單一藍色主色，資料數字用等寬字。安靜、專業、以數字為主角，不用插圖與大面積彩色。
- **層次靠底色而非陰影**：頁面底 → 區塊底 → 卡片 → 浮起元素四層底色；陰影只在 hover 與主按鈕出現。
- **點綴而非裝飾**：漸層只用在 logo、標題關鍵字（`gradient-text`）與主按鈕；背景柔光（blur 光暈）只在首頁 hero 一處。
- **一眼可讀的漲跌**：漲跌只靠顏色與正負號，不加箭頭圖示或閃爍。
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

字體載入：Google Fonts `Inter:wght@400;500;600;700` 與 `JetBrains+Mono:wght@400;500`；中文 fallback 用 `Noto Sans TC`（可選載入）。只允許 Inter 當標題與內文、JetBrains Mono 當數字。

## 3. 字級與數字

| 用途 | 字級／字重 | 說明 |
| --- | --- | --- |
| 頁面大標（hero） | 36–60px／700，`leading-tight` | 只在首頁；關鍵字用 `gradient-text` |
| 區塊標題 h2 | 30–36px／700 | 置中或靠左，下方 8px 說明文字（muted，18px） |
| 卡片標題 h3 | 20px／600 | |
| 內文 | 16px／400 | 說明文字用 `--color-text-muted` |
| 標籤、表頭、註腳 | 14px／500；註腳 12px | 表頭 muted，不全大寫 |
| 主要數字（股價、淨值） | 30–36px／700，`--font-mono` | 卡片一個主數字 |
| 次要數字（表格、統計） | 14–16px／500–600，`--font-mono`，`tabular-nums` | 靠右對齊 |
| 漲跌 | 同欄位字級／600 | 色依 `--color-up`／`--color-down`／`--color-flat`，正數帶 `+` |

所有金額與百分比用 `font-variant-numeric: tabular-nums` 對齊；千分位逗號；百分比兩位小數；價格依標的 tick 顯示小數位。

## 4. 版面與導航

- **Navbar**：固定頂部，高 64px，`backdrop-filter: blur(20px)`，底色 `rgba(11,15,26,0.95)`，下緣 1px `--color-border`。左側 40px 圓角 logo（主色→強調色漸層方塊＋白色折線圖示）加產品名；中間五個主導航連結（今日、新聞、族群、個股、行動），顏色 muted、hover 轉主文字色、當前頁主文字色加 2px 主色底線；右側放搜尋（代號／名稱）與資料日期 badge。手機收成漢堡選單。
- **內容容器**：`max-width: var(--content-max)`，左右 padding 16／24／32px（手機／平板／桌面）。
- **區塊**：垂直 padding 64px，桌面 96px；相鄰區塊以 `--color-bg` 與 `--color-bg-alt` 交錯。
- **網格**：卡片列用 CSS grid，桌面 2–4 欄、平板 2 欄、手機 1 欄，gap 16–24px。
- **Hero（僅首頁）**：左文右卡的雙欄；背景兩顆 400–500px 的圓形光暈（主色 10% 與強調色 10%，`blur(120px)`），其餘頁面不用光暈。

## 5. 元件

| 元件 | 規則 |
| --- | --- |
| `card` | 底 `--color-bg-card`、1px `--color-border`、圓角 16px、padding 24px；hover 邊線轉 `--color-border-hover`。資料卡用它。 |
| `feature-card` | 同 card，可點擊；hover 邊線轉主色、上移 4px、陰影 `--shadow-hover`。左上 48px 圓角 12px 圖示底（主色 20% 透明），圖示用主色線條。 |
| `market-widget` | 小型數據方塊：底 card 色、圓角 12px、padding 16px；上方 muted 標籤，中間 mono 主數字，下方漲跌。 |
| `stat-value` | 統計數字：mono、24px、600。 |
| `badge` | 膠囊：底 card 色、1px 邊、圓角 50px、padding 6px 14px、14px 字；狀態變體把文字與邊線改成 success／primary／warning／error。前面可放 8px 圓點（活躍狀態加 `animate-pulse`）。 |
| `btn-primary` | 漸層 `135deg, --color-primary → --color-primary-dark`，白字 600，圓角 10px，padding 14px 28px；hover 上移 2px 加 `--shadow-btn`。每個畫面最多一個主按鈕。 |
| `btn-secondary` | 透明底、1px `--color-border`、主文字色，圓角 10px；hover 底轉 card 色、邊線轉主文字色。 |
| `btn-ghost` | 無邊無底 muted 文字，hover 轉主文字色；用於導航與表格內動作。 |
| 表格 | 容器用 card；表頭 14px muted、底邊 1px；列高 56px、底邊 1px `--color-border`、最後一列無邊；hover 列底 `--color-bg-elevated`；數字欄靠右 mono；每列右側可放一個小的 `btn-primary`（text-sm、padding 8px 16px）或 ghost 連結。 |
| 列表項（個股列） | 左：40px 圓角方塊顯示代號前綴或產業縮寫（`--color-bg-elevated`）＋代號（600）與名稱（muted 14px）；右：價格（mono）與漲跌（色＋正負號）。 |
| 輸入框 | 底 `--color-bg-alt`、1px 邊、圓角 8px、padding 12px 16px；focus 邊線轉主色，無外框光暈。 |
| 分頁籤（tabs） | 文字 tabs，選中者主文字色加 2px 主色底線；用於指標面板（MACD／RSI／KD／布林）、新聞國內／國際、族群產業／題材。 |
| 空狀態 | 卡片內置中 muted 文字「無資料」加一行原因（如「日線不足 60 根」），不用插圖。 |
| 載入 | 卡片骨架（`--color-bg-elevated` 條塊，淡入淡出），不用旋轉圖示。 |
| Toast／錯誤 | 右上角 card 樣式，左側 4px 色條（success／warning／error）。 |

## 6. 圖表（ECharts）

- 背景透明，格線 `rgba(255,255,255,0.06)`，軸文字 `--color-text-muted` 12px mono。
- K 線：漲 `--color-up`、跌 `--color-down`，實體與影線同色；成交量柱同漲跌色、60% 透明。
- 均線固定色：MA5 `#f59e0b`、MA10 `#8b5cf6`、MA20 `#3b82f6`、MA60 `#10b981`、MA120 `#9ca3af`。
- 指標面板（MACD／RSI／KD／布林）置於主圖下方，高度為主圖 35%，共用 x 軸與 dataZoom；MACD 柱用漲跌色，DIF／DEA 用主色與強調色；RSI／KD 參考線（20／80、30／70）用 `--color-text-subtle` 虛線。
- 單線圖（熱度走勢、淨值）：主色線寬 2px，下方用主色漸層填充（頂部 25% 透明到底部 0）。
- Tooltip：底 `--color-bg-card`、1px 邊、圓角 8px、mono 數字；滑鼠十字線 `--color-text-subtle`。
- 資料日期一律顯示在圖右上角 badge。

## 7. 資料與狀態的視覺語言

- 每張資料卡右上角 badge 顯示資料日期（如「資料 10/17」）；排程更新中顯示 warning badge「更新中」。
- 無資料：欄位留空顯示「—」加 muted 原因，不顯示 0。
- LLM 推論內容：左側 2px 強調色（`--color-accent`）豎線加「AI 推論」小 badge，與事實分區。
- 進出點卡：進場區主文字色 mono；停損 `--color-error`；目標 `--color-success`；RR 用 badge。
- 候選清單理由：最多三條，每條一行，前綴 8px 色點（技術 primary、籌碼 secondary、新聞 accent）。

## 8. 無障礙與動效

- 文字對比至少 4.5:1；muted 文字只用於 14px 以上。
- 所有互動元件有 `:focus-visible` 外框（2px 主色、offset 2px）。
- 動效只用 transform 與 opacity，時長 200–300ms；`prefers-reduced-motion` 時全部關閉。
- 圖示用 24px 線條 SVG（stroke 2，`currentColor`），不用彩色圖示或 emoji。

## 9. 實作規則

- 樣式以 Tailwind utility 搭配上述 CSS 變數（`text-[var(--color-text-muted)]` 形式）或等價的 CSS class；禁止元件內 inline 色碼。
- 共用元件放 `frontend/src/components/ui/`（Card、Badge、Button、Table、Tabs、Stat、EmptyState、Skeleton），頁面只組裝不重畫。
- 新元件先查本文是否已有對應規則；沒有就先補本文再實作。
- PR 附桌面（1280px）與手機（390px）截圖各一張，確認符合本文。
