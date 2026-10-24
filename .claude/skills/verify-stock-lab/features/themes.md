# 族群 `/themes`

入口：主導航「族群」，`ThemesPage` → `ThemesBoardView`（`frontend/src/themes/ThemeViews.tsx`）；詳情 `/themes/:id` → `ThemeDetailView`。路徑：今日熱門族群 #1 → 族群詳情。

## API

| 檔名 | URL（前綴 `http://127.0.0.1:8227/api`） |
| --- | --- |
| `themes-industry.json` | `/themes?board=industry&limit=100` |
| `themes-theme.json` | `/themes?board=theme&limit=100` |
| `theme-suggestions.json` | `/theme-suggestions?limit=20`（與頁面的 `THEME_SUGGESTION_LIMIT` 相同） |
| `theme-detail.json` | `/themes/<T>`，`T` = 今日記下的 `items[0].theme_id` |
| `theme-members.json` | `/themes/<T>/members?page=1&page_size=30&sort=price` |

## 截圖

| 名稱 | 參數 |
| --- | --- |
| `themes` | `--url http://127.0.0.1:4227/themes --name themes`（1280 與 390） |
| `themes-theme` | `--url "http://127.0.0.1:4227/themes?board=theme" --name themes-theme --widths 1280` |
| `theme-detail` | `--url http://127.0.0.1:4227/themes/<T> --name theme-detail`（1280 與 390） |

## 預期資料與標記

| 區塊 | 資料來源 | 必須顯示的來源與資料日期 | 「推論」位置 | 空資料文案 |
| --- | --- | --- | --- | --- |
| 產業／題材榜 | `themes-*.json` | `<產業\|題材>榜 · 共 <meta.total> 個族群` 的下一行 `資料 <B/>`；`meta.data_as_of` 與 `trading_date` 不同時再接 `官方資料 <data_as_of>` | — | `meta.empty_message` 或 `此榜目前沒有族群` |
| 新聞題材建議 | `theme-suggestions.json` | `<total> 個建議 · 最近更新 …`；每張卡 `<n> 則新聞 · 首次 … · 最近 …` | 每張卡標題後 `待核實` 與 `AI 推論`；區塊說明「由 AI 從近期新聞判讀出的題材名稱彙整…」 | `目前沒有新聞題材建議` |
| 族群詳情 | `theme-detail.json`、`theme-members.json` | 標頭 `資料 <B/>`；`熱度走勢` 與 `五分項` 卡各有 `資料 <B/>`；`成員資料截至 <M/>`；成員表 `資料日期` 欄 | — | `走勢資料不足（需至少 2 個交易日的分數）`、`此日期沒有有效成員`、`此族群尚無已核實關聯的新聞` |

`B` = 該榜 `meta.trading_date`；`M` = `theme-members.json` 的 `meta.data_as_of`。

## 檢查

| 編號 | 檢查 | 怎麼判 |
| --- | --- | --- |
| G1 | 頁面可用 | 每張截圖 `ready` true、`httpErrors` 與 `consoleErrors` 空、`overflow` false |
| G2 | 榜單資料日期標記 | `themes-1280.txt` 整行 `產業榜 · 共 <total> 個族群` 的下一行是 `資料 <B/>`；`themes-theme-1280.txt` 的 `題材榜 · 共 <total> 個族群` 同樣；`B` 等於 `facts.json` 的 `group_scores_latest_trading_date` |
| G3 | 榜單內容 | 1280 表格：以 `排名\t族群` 開頭的表頭存在；`items[0].display_name` 與 `items[-1].display_name` 各為整行出現。390：`#1` 為整行、下一行為 `items[0].display_name` |
| G4 | 題材建議推論標記 | 看 `themes-1280.txt`。`items` 非空時：整行 `待核實` 的行數 ≥ `items` 數，整行 `AI 推論` 的行數 ≥ `items` 數，且 `<meta.total> 個建議` 開頭的行存在；空時空資料文案為整行出現 |
| G5 | 詳情日期 | `theme-detail-1280.txt` 整行 `熱度走勢` 與 `五分項` 的下一行都是 `資料 <B/>`；有 `成員資料截至 <M/>` 這行 |
| G6 | 詳情成員 | 表頭 `代號\t名稱\t市場\t角色\t收盤\t資料日期` 存在；`theme-members.json` 第一個成員的 `symbol` 與 `name` 出現在同一行；`第 1／<total_pages> 頁 · 共 <meta.total> 檔` 存在（`total_pages` 以每頁 30 檔計） |
| G7 | 今日到族群一致 | 今日頁 `#1` 的族群名稱 = 本頁產業榜 `items[0].display_name` = `theme-detail.json` 的 `theme.display_name`，且這個名稱在 `theme-detail-1280.txt` 的 `← 回到…榜` 之後、`排名` 之前為整行出現 |

## 陷阱

- 1280 的榜單是表格（以 tab 分欄），390 是卡片（`#1` 一行、名稱在下一行），G3 兩個寬度的判法不同。
- 產業榜是 `/themes` 預設分頁，題材榜要帶 `?board=theme`；兩榜的 `B` 各自取該榜的 `meta.trading_date`。

## 判定

- 通過：G1～G7 全部通過。
- 失敗：任一條失敗，列出編號、預期與實際。
- 無法判定：截圖未 ready 或 API 非 200；依賴它的檢查不判。

## 輸出格式

```markdown
### 族群 `/themes`：失敗

| 檢查 | 結果 | 原因類別 | 證據 |
| --- | --- | --- | --- |
| G2 | 失敗 | 產品缺陷 | `產業榜 · 共 34 個族群` 的下一行是空白與表格說明，缺 `資料 2026/10/21`（themes-1280.txt 第 17～19 行） |
| G5 | 通過 | — | 熱度走勢、五分項皆 `資料 2026/10/21`；成員資料截至 2026/10/21 |

截圖：shots/themes-1280.png、shots/themes-390.png、shots/theme-detail-1280.png
```

記下供個股使用：`theme-members.json` 第一個成員的 `exchange` 與 `symbol`（記為 `E`、`S`）。
