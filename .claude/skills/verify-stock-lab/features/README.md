# features

Drive 段依下表順序執行五個檔。後面的檔案會用前面記下的值（今日 → 族群 → 個股 → 行動走同一條路徑），順序不可換。

| 順序 | 檔案 | 導覽代號 | 記下供後面使用 |
| --- | --- | --- | --- |
| 1 | [today.md](today.md) | `today` | `D`、`B`、`today-board.json` 的 `items[0].theme_id`（`T`）與 `display_name` |
| 2 | [news.md](news.md) | `news` | — |
| 3 | [themes.md](themes.md) | `themes` | `theme-members.json` 第一個成員的 `exchange`、`symbol`（`E`、`S`） |
| 4 | [stocks.md](stocks.md) | `stocks` | `I`、`stock.json` |
| 5 | [actions.md](actions.md) | `actions` | — |

## 跨檔傳遞的值

| 值 | 定義 | 記下的檔 | 使用的檔 |
| --- | --- | --- | --- |
| `D` | `dashboard.json` 的 `as_of` 前 10 字 | today | stocks S3（導覽列的 `資料 <D>`） |
| `B` | `today-board.json` 的 `meta.trading_date` | today | themes（族群榜 `B` 指各榜自己的 `meta.trading_date`，與今日的 `B` 應同一天） |
| `T`、名稱 | `today-board.json` 的 `items[0].theme_id` 與 `display_name` | today | themes 的 `theme-detail`／`theme-members` URL 與 G7 |
| `E`、`S` | `theme-members.json` 第一個成員的 `exchange`、`symbol` | themes | stocks 的 API、截圖與 S3、S6；actions 的 `action-detail` 與 A6、A7 |
| `I` | `facts-stock.json` 的 `instrument.latest_trading_date` | stocks | stocks S3～S8 |

前一個檔沒記下某個值（API 非 200、清單為空）時，用到它的檢查判「無法判定」，原因寫缺哪個值、來自哪個檔。

## 檢查類型

各檔「檢查」表的 `類型` 欄：`CI` 是機械式檢查，[`tools/verify/page_checks.py`](../../../../tools/verify/page_checks.py) 有實作，CI `verify` job 每次在假資料庫上跑；`人工` 要 agent 判斷，不寫成程式。新增或改類型時兩邊一起改，`backend/tests/test_verify_checks.py` 會擋下標 `CI` 卻沒實作、或有實作卻沒標 `CI` 的檢查。

## 結果表

每個 `results/<導覽代號>.md` 的表格都是四欄：`檢查`、`結果`、`原因類別`、`證據`。通過的檢查原因類別寫 `—`。

### 原因類別

失敗與無法判定的檢查各選一類：

| 類別 | 什麼時候用 |
| --- | --- |
| 文件漂移 | features 檔與現行程式不符（元件位置、文案、分頁、API 欄位改了），頁面照現行規格運作 |
| 工具缺口 | 證據取不到或取錯（`screenshot.cjs`、`curl`、`db_facts.py`、環境），不代表頁面錯 |
| 產品缺陷 | 頁面與 API／DB 不一致，或違反[顯示原則](../../../../docs/ROADMAP.md#v1-範圍基線2026-10-17-核定) |

**不改檢查讓它通過**：跑 verify 的同一輪不改 features 檔或工具。判成文件漂移或工具缺口的照實記下，另開 PR 修；修的時候以程式與規格為準，不以這次的頁面輸出為準。

## 陷阱

全部導覽共通的規則在 [SKILL Drive 共通規則](../SKILL.md#3-drive)；只屬於某一頁的陷阱寫在該檔的「陷阱」小節。
