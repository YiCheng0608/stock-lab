# 個股研究頁契約

更新：2026-09-13。狀態：**Round13 有限產品範圍已通過統籌 final review**。本文只定義 `/stocks/:exchange/:symbol` 的本輪產品與驗收邊界；此狀態不代表整體研究產品、R0 或後續 ROADMAP 完成。

## 1. 使用者工作與資訊順序

使用者進入一檔股票後，應能先確認「看的是哪一檔、哪段資料、什麼價格口徑」，再依序完成：

1. 讀取行動摘要與主要資料缺口；
2. 觀察日 K、成交量及 MA20／MA60；
3. 對照族群、法人籌碼、官方事件／新聞與策略必要條件；
4. 查閱 coverage、時間與來源，判斷哪些結論可用、哪些仍未知。

頁面不是 AI 選股、買賣指令或完整交易計畫。零行動、零新聞、缺籌碼或均線不足都是合法狀態，不能為了填滿畫面造資料。

## 2. 現有 API 與畫面 cross-review

### 2.1 實際 payload

前端 `getStock(exchange, symbol)` 呼叫 `GET /stocks/{exchange}/{symbol}`。後端先組成 instrument detail，再加上 `decision_summary`、`coverage` 與 news；沒有本輪專用新 endpoint 或日期 query。

| 區塊 | 實際欄位／上限 | 本輪用法與限制 |
| --- | --- | --- |
| 標的 | `instrument` | 以 exchange＋symbol 為唯一頁面身分，並顯示名稱／類型。 |
| 行情 | `bars` 最多 120 筆；後端取最近日期後反轉成舊到新 | 每筆有 date、open、high、low、close、adj_close、volume、turnover、source、data_as_of、collected_at、is_suspended。API 沒有宣稱完整歷史。 |
| 技術快照 | `features` 只有最新一筆 `TechnicalFeature.features_json` | 可顯示最新摘要，但不可拿單一 `features.ma20`／`ma60` 畫歷史線。本輪歷史 MA 只由 response bars 計算。 |
| 族群 | `groups`：id、name、valid_from、valid_to | 本輪前頁面未呈現；本輪加入研究區，不從名稱推論未提供的題材身分。 |
| 籌碼 | `chips` 最多 120 筆 | 顯示既有法人／融資欄位與資料日／來源；「外陸資」是資料欄位，不延伸成券商分點或特定外資身分。 |
| 事件／新聞 | `events` 最多 50 筆；stock endpoint 另加 active、非 conflict 的 `news` 最多 20 筆 | 兩者可分區或合併成時間軸，但必須保留類型、來源與時間，不能把所有 news 直接改稱資料庫 Event 或已核實催化。 |
| 策略／行動 | `strategy_conditions`、`signals` 最多 20 筆、`decision_summary` | requires 是固定規則所需資料，不等於通過；行動摘要沿用既有價位、confidence 與 product-time 安全語意，不新增分數／價位。 |
| 品質 | `coverage`、`quality_summary`、`data_quality` 最多 10 筆 | 明示缺日、資料不足、用途別品質與 unknown，不用圖表存在取代 coverage。 |

本輪開始時的前端只有最近 30 根行情表格，欄位不含 open，沒有 K 線、成交量子圖、縮放或歷史 MA；頁首取第一根 bar 的來源，未知來源又可能被通用 helper 顯示為「官方資料來源」；族群未顯示，`news` 則被放在「官方事件」標題下。這些是本輪需修正的實際差異，不是已完成證據。

### 2.2 價格口徑

圖表只用每根 bar 的 `open`／`high`／`low`／`close`。Payload 另有 `adj_close`，但沒有 `price_basis`、OHLC adjustment factor、applied-through 或公司行動還原鏈，所以標示固定為：

> 原始 API 價格；還原方式未提供

這句只表示 API 的價格 basis 不足，不能改寫為「已確認未還原」或「已完成還原」。單一 `adj_close` 不足以生成 adjusted OHLC，本輪不得混用。

## 3. 圖表資料契約

### 3.1 驗證與排序

- date 必須可辨識且每個交易日唯一；重複日期不得任選第一筆、最後一筆或平均後假裝有效。
- O／H／L／C 必須是有限數字，且 `low <= min(open, close) <= max(open, close) <= high`。不合格列不生成 K 棒，並顯示資料問題；不得以 close 補 open／high／low。
- volume 必須是有限且非負的股數；缺失或非法值不得補 0。成交量無法成立時，對應列／區塊須明示不可用。
- bars 依 date 由舊到新呈現。若 response 順序異常，可在不改變資料值的前提下排序，但須先拒絕重複日期；停牌或無交易依原欄位標示，不造平盤棒。
- 頁面顯示 response 總筆數、實際可畫筆數、最早／最晚日期；少於 120 筆只說實際筆數，恰為 120 筆也只能說「本次最多 120 根視窗」。

### 3.2 MA20／MA60

均線是本輪前端視覺化衍生值，不寫回 API／DB，也不等同 worker 的 `TechnicalFeature`、新 ATR 或策略換版。

- MA20／MA60 分別是截至該日最近 20／60 根合格、唯一日期 bar 的 close 簡單平均。
- 前 19／59 個點維持缺值，不前填、不回填、不用較短窗口冒充。
- 遭拒列或已知日期缺口不能被靜默刪除後跨越補算；受影響窗口不畫 MA，並由 coverage／圖表狀態說明。
- 顯示精度可格式化，但計算不得先四捨五入每根 close。最新 API feature 值若另列，需標為最新快照，不要求與此視窗衍生線冒充同一 provenance。

### 3.3 互動與等效資訊

- 主圖為日 K，成交量以股為單位對齊相同日期；MA20／MA60 有可辨識圖例，資料不足的線不出現並有文字原因。
- tooltip／focus 摘要至少含日期、開、高、低、收、成交量；數字與可讀表格使用同一筆資料及同一單位。
- 提供 client-side 縮放與復位，範圍不得超出本次 response；縮放不觸發或暗示後端載入完整歷史。
- 鍵盤或輔助技術不必操作每個 canvas 點，但必須能以表格或等效 DOM 內容讀到日期與 OHLCV，並能操作必要的縮放復位控制。顏色不是漲跌或均線的唯一辨識方式。
- 無 bars、全部無效、部分無效與載入失敗各有不同訊息；保留頁面其他可用研究區塊，不用空圖遮蔽錯誤。

## 4. 來源、區間與研究整合

頁首或圖表旁固定顯示：標的、最早／最晚 bar date、總筆數／可畫筆數、所有實際 `source` 值的安全標籤，以及價格口徑。若來源缺失、未知或區間內混合，直接說「來源未提供／未知／混合來源」並列出可稽核值；未知值不可由 fallback 改稱官方。

研究頁最少保留以下語意：

- `decision_summary` 是既有聚合結果，仍可為空或資料待補；其規則參考價不是委託、成交或個人化建議。
- `groups` 顯示名稱與 membership 有效期間；不把存在 membership 自動翻成今日熱門或正向催化。
- `chips` 分開外陸資、投信、自營商與融資，保留日期／來源；不合計成未驗證的「主力」。
- `events` 與 `news` 清楚區分或在統一時間軸標出種類；標題、來源、事件／發布時間及 conflict／unknown 語意沿用既有契約。
- `strategy_conditions` 顯示需要哪些資料；真正條件結果看 decision／signals，不新增前端評分。
- `coverage`／`quality_summary` 保持可見，特別是 20／60 日不足與缺 bar／chip 日期；技術 raw 可收合，但使用者不必先展開 raw 才知道資料是否不足。

## 5. 驗收矩陣

| 案例 | 必須觀察到 |
| --- | --- |
| 60 根以上完整資料 | K、成交量、MA20、MA60、日期 OHLCV 提示、縮放／復位、等效表格與區間／來源／basis 標示一致。 |
| 20–59 根 | MA20 只從第 20 根開始；MA60 不出現且有不足原因。 |
| 1–19 根 | K／合法成交量仍可看；兩條 MA 都不補，coverage 與文字狀態一致。 |
| 0 根 | 無圖表資料狀態；行動、族群、事件等其他 payload 若存在仍可研究。 |
| 無效 OHLC／volume null、NaN、負值 | 不補 close 或 0；不生成誤導 K／量，顯示被拒資料數／原因。 |
| 重複日期／順序反轉 | 重複日期 fail closed；純順序問題可穩定排序，值不改寫。 |
| 缺 bar 日期／停牌 | 不跨缺口補 MA 或造平盤 K；與 coverage／is_suspended 標示相容。 |
| 未知／混合來源 | 不顯示成單一「官方來源」；實際值及 unknown 清楚可見。 |
| 事件與 news 同時存在 | 兩種證據可辨識，來源／時間不互相冒充，連結與空值安全。 |
| 行動摘要缺失或資料待補 | 不造評分／價位；圖表與其他研究區塊仍可用。 |

### 5.1 2026-09-12 final review 證據

統籌以 `C:/Users/YiCheng/AppData/Local/Temp/stock-r13-coordinator-review` 的隔離證據獨立驗收：六個前端 self-test、17/17 獨立資料邊界檢查、TypeScript typecheck 與 production build 全為 exit 0；build 轉換 666 modules、6.88 秒，仍保留 JS chunk 超過 500 kB 的警告。10 個本輪 source hash 在驗證前後穩定，86 個 protected targets 與 105 個 cache baseline（含正式／`.local` DB、package 與 lockfile）不變。

隔離、唯讀的正式 DB 備份 browser 流程已驗 2330 預設／30 日／復位與 4804 空資料，390px 版面沒有 page-level 橫向溢位；final new-tab browser error logs 為空。2330 最末日提示精確對上 2026-09-08、O2465／H2505／L2460／C2470／V28931697、MA20=2407、MA60=2396.92。05:36 的舊分頁曾在較早版本出現 update-depth error，修正後才完成上述新分頁重驗，故不能解讀為開發過程從未出錯。這是統籌對穩定 source snapshot 的獨立驗收；C013 程式 task 沒有另行提供作者 final 聲明。

本批因此改列 `已 review`，但只結清本文明列的有限產品範圍。本次文件交付時，文件索引尚待 I050；最新索引驗收狀態見 [協作紀錄](TASK_COORDINATION.md)。索引成功與否不改變上述功能驗收邊界。

## 6. 明確未包含

本輪不證明或交付：完整歷史下載、adjusted OHLC、PIT／availability truth、legacy／new signal comparison、B7 paired replay、新 ATR 接線、策略績效／勝率、AI 研究、完整 trade plan、個人風險部位、正式 DB migration、來源採購、自動排程或下單。這些既有 ROADMAP 驗收仍有效。

## 7. Round14 前端顯示契約覆寫（已 review；輪末索引待複核）

Round13 對 API 原始成交量股數與圖表資料轉換的驗證紀錄保留不變；Round14 只覆寫台股使用者介面的顯示契約。來源明確為股數的成交量與法人買賣超，顯示值為原值除以 1,000、單位固定為「張」、最多 3 位小數，並保留法人數值的正負方向；例如 `28,931,697` 股顯示為 `28,931.697 張`。TWSE 融資的交易單位在本輪台股介面顯示為張。不得改寫 API 原始值、圖表計算、策略計算或 raw evidence。

來源或單位未知／混合時，不推測也不套用除以 1,000，介面須直接標明無法確認單位。統籌已在 390px 的 2330 個股頁核對 K 線、張數及籌碼原值展開，在 320px 的 4804 核對缺行情狀態；完整單位表、證據與限制見 [Round14 UX review](UX_REVIEW.md#5-final-review-證據與限制)。本節的 `已 review` 只代表前端顯示與互動，不包含持倉實寫、產業資料修復、正式 DB 或整體研究驗收；輪末索引待複核。

族群欄位另有獨立的正式資料缺陷：例如 TPEx 3176 的 raw `industry=22` 被舊 membership 接到 Shipping。資料重建前，個股與行動詳情顯示「既有族群關聯待重新核實」；族群卡片／詳情可保留中文 `display_name`，但須加「（既有分類）」與待核實 badge，原始英文 membership name／ID 收進資料說明。不得顯示可信排名或把衍生研究條件宣稱已核實。OHLCV、張數換算與新聞內容不因這項分類缺陷改寫；分類修正及正式 DB 重建不在 Round14 顯示批。
