# 新聞 `/news`

入口：主導航「新聞」，`NewsPage` → `NewsListView`（`frontend/src/news/NewsViews.tsx`）；詳情 `/news/:id` → `NewsDetailView`。

## API

| 檔名 | URL（前綴 `http://127.0.0.1:8227/api`） |
| --- | --- |
| `news-domestic.json` | `/news?category=domestic&limit=20` |
| `news-international.json` | `/news?category=international&limit=20` |
| `news-official.json` | `/news?source_kind=official_disclosure&limit=20` |
| `news-detail.json` | `/news/<id>`，`id` 取 `news-domestic.json` 第一則 `ai.status` 為 `done` 的項目（沒有就取第一則） |

## 截圖

| 名稱 | 參數 |
| --- | --- |
| `news` | `--url http://127.0.0.1:4227/news --name news`（1280 與 390） |
| `news-international` | `--url "http://127.0.0.1:4227/news?tab=international" --name news-international --widths 1280` |
| `news-official` | `--url "http://127.0.0.1:4227/news?tab=official" --name news-official --widths 1280` |
| `news-detail` | `--url http://127.0.0.1:4227/news/<id> --name news-detail`（1280 與 390） |

## 預期資料與標記

| 區塊 | 資料來源 | 必須顯示的來源與資料日期 | 「推論」位置 | 空資料文案 |
| --- | --- | --- | --- | --- |
| 列表卡（三個分頁） | 各分頁 API `items` | 來源 badge（`source_name`；官方公告為來源標籤）、`<分類> · <來源類型>`、時間行 `發布於／事件於／事件日 …`（或 `來源時間待核實／來源時間未提供`） | 有 AI 判讀的卡在方向後接整行 `AI 推論` | 國內 `目前沒有符合條件的國內新聞。`、國際 `目前沒有符合條件的國際新聞。`、官方 `目前沒有符合條件的官方公告。` |
| 詳情：來源事實 | `news-detail.json` | 區塊 `來源事實`、來源名稱、時間行、`查看原文` 或來源說明 | — | 摘要空時 `NO_SUMMARY_TEXT` |
| 詳情：AI 摘要與判讀 | `news-detail.json` 的 `ai` | `模型 <model> · 提示版本 <prompt_version> · 產生時間 …` | 標題 `AI 摘要與判讀` 下一行 `AI 推論`；候選標的、候選題材標 `待核實` | `此則尚未產生 AI 摘要與判讀。` |

## 檢查

| 編號 | 檢查 | 怎麼判 |
| --- | --- | --- |
| N1 | 頁面可用 | 每張截圖 `ready` true、`httpErrors` 與 `consoleErrors` 空、`overflow` false |
| N2 | 列表與 API 一致 | 國內用 `news-1280.txt`、國際用 `news-international-1280.txt`、官方用 `news-official-1280.txt`（N3、N4 同）。三個分頁各自：API `items` 空時空資料文案為整行出現；否則前 3 則 `title`（官方公告的標題會被改寫，改比來源 badge 與時間行：badge 是 `newsSourceLabel(source_name)`（`frontend/src/presentation.ts`，例如 `MOPS` → `公開資訊觀測站公告`），時間行是 `事件日 <event_date 的 YYYY/MM/DD>`）依序為整行出現 |
| N3 | 每張卡有時間 | 各分頁 `^(發布於\|事件於\|事件日) \|^來源時間(待核實\|未提供)$` 的行數 = API `items` 數 |
| N4 | AI 標記 | 各分頁整行 `AI 推論` 的行數 = API `items` 中 `ai.status` 為 `done` 且 `ai.inference` 為 true 的數量 |
| N5 | 新聞日期合理 | `facts.json` 的 `news_latest_published_at`（UTC，加 8 小時）不晚於現在的台北時間；國內第一則的時間行日期不晚於今天 |
| N6 | 詳情分欄 | `news-detail-1280.txt` 有整行 `來源事實` 與 `AI 摘要與判讀`，`AI 摘要與判讀` 下一行是 `AI 推論`；`ai` 為 done 時有 `模型 <ai.model> · 提示版本 <ai.prompt_version>` 開頭的行，否則有 `此則尚未產生 AI 摘要與判讀。` |

## 陷阱

- 「有 AI 判讀」與前端 `usableAi` 相同：`ai.status` 為 `done` 且 `ai.inference` 為 true（方向欄位是 `ai.impact_direction`）。今日 T6 與個股「新聞與公告」也用這個定義。
- DB 與 API 裡沒有時區的時間（例如 `news_items.published_at`、`ai.generated_at`）是 UTC，與台北時間比較前加 8 小時（N5）。

## 判定

- 通過：N1～N6 全部通過。
- 失敗：任一條失敗，列出編號、分頁、預期與實際。
- 無法判定：截圖未 ready 或 API 非 200；依賴它的檢查不判。

## 輸出格式

```markdown
### 新聞 `/news`：通過

| 檢查 | 結果 | 原因類別 | 證據 |
| --- | --- | --- | --- |
| N1 | 通過 | — | 5 張截圖 ready，無錯誤，無橫向捲動 |
| N3 | 通過 | — | 國內 20／20、國際 20／20、官方 20／20 張卡有時間行 |
| N4 | 通過 | — | 國內 `AI 推論` 18 行 = API done 18 則 |

截圖：shots/news-1280.png、shots/news-390.png、shots/news-detail-1280.png
```
