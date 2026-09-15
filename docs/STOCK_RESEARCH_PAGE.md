# 個股研究頁契約

更新：2026-09-15。`/stocks/:exchange/:symbol` 的有限產品範圍已於 2026-09-12 通過統籌 review，Round14 另驗收前端顯示換算與分類警示。2026-09-15 的繁中文案、法人命名、數值表格與官方分點入口維護亦已通過有限 review；本文不代表完整研究產品、R0 或 ROADMAP 已完成。

## 1. 使用者工作與資訊順序

使用者先確認標的、實際資料區間與價格口徑，再依序讀取行動摘要、日 K／成交量／MA20／MA60、族群、法人籌碼、官方事件／新聞、策略條件，以及 coverage／來源。頁面允許零行動、零新聞、缺籌碼或均線不足；不得為填滿畫面造資料。它不是 AI 選股、下單或完整交易計畫。

## 2. 現有 API 與畫面 cross-review

### 2.1 實際 payload

前端 `getStock(exchange, symbol)` 呼叫 `GET /stocks/{exchange}/{symbol}`。後端組成 instrument detail，再加入 decision summary、coverage 與 news；沒有此頁專用日期 query。

| 區塊 | 實際欄位／上限 | 呈現限制 |
| --- | --- | --- |
| 標的 | `instrument` | 以 exchange＋symbol 識別，顯示名稱與類型。 |
| 行情 | `bars` 最多 120 筆，舊到新 | 含 OHLC、adj_close、volume、turnover、source、data_as_of、collected_at、is_suspended；只代表本次視窗。 |
| 技術快照 | 最新一筆 `features` | 可作最新摘要，不能由單點 feature 畫歷史 MA；歷史 MA 由 response bars 算。 |
| 族群 | `groups` | 顯示名稱與有效期，不由名稱推論題材或熱門。 |
| 籌碼 | `chips` 最多 120 筆 | 法人／融資連同日期和來源顯示；不得推論分點或特定外資身分。 |
| 事件／新聞 | `events` 最多 50、active 非 conflict `news` 最多 20 | 分開或標示類型；不能互相冒充或一律稱已核實催化劑。 |
| 策略／行動 | `strategy_conditions`、`signals` 最多 20、`decision_summary` | requires 只是需求，不是通過；沿用既有價位、信心與 product-time 語意。 |
| 品質 | `coverage`、`quality_summary`、`data_quality` 最多 10 | 顯示用途別完整度、缺日與 unknown；圖表存在不能替代 coverage。 |

### 2.2 價格口徑

圖表只使用每根 bar 的原始 open／high／low／close。payload 沒有 `price_basis`、OHLC adjustment factor、applied-through 或完整公司行動還原鏈；單一 `adj_close` 不足以生成 adjusted OHLC。因此固定標示：

> 原始 API 價格；還原方式未提供

這不等於已確認「未還原」，也不代表還原已完成。

API 也沒有 currency 欄位，且標的可能不是新臺幣計價。價格表外統一寫「各標的報價幣別的元」，指數寫「點」；在取得可驗證幣別前，不得一律加 `NT$` 或猜測幣別。

## 3. 圖表資料契約

### 3.1 驗證與排序

- date 必須合法且唯一；重複日期 fail closed，不能任選、平均或覆寫。
- O／H／L／C 須為有限數字且 `low <= min(open, close) <= max(open, close) <= high`；非法列不生成 K 棒，不能用 close 補值。
- volume 須為有限非負股數；null、NaN 或負值不補 0，對應列／區塊須標不可用。
- 合法 bars 依日期舊到新排序；停牌或無交易按原欄位標示，不造平盤棒。
- 顯示總筆數、可畫筆數及最早／最晚日期。少於 120 筆只說實際筆數；恰為 120 筆也只能說「本次最多 120 根視窗」。

### 3.2 MA20／MA60

MA20／MA60 是前端由合格、唯一日期 bar 的最近 20／60 個 close 計算的簡單平均，不回寫 API／DB，也不代表 worker feature 或策略升版。

- 前 19／59 點保持缺值，不用短窗口、前填或回填。
- 已拒列或已知缺日會中斷受影響窗口，不能靜默跨越補算。
- 計算前不逐筆四捨五入；最新 API feature 如另列，須標為不同 provenance 的最新快照。

### 3.3 互動與等效資訊

日 K、成交量與兩條 MA 使用相同日期並有可辨識圖例；tooltip／focus 與可讀表格至少提供日期及 OHLCV，數值和單位一致。數值表格把單位置於表題或緊鄰說明，數值格只放數字並保留正負號；缺值留空且在表外說明，合法 0 仍顯示。縮放／復位只限 response 視窗，不暗示載入完整歷史。鍵盤與輔助技術使用者可操作必要控制並讀取等效 DOM 資料；顏色不是唯一辨識方式。

無 bars、全部無效、部分無效與載入失敗各有訊息；其他可用研究區塊仍保留。

## 4. 來源、區間與研究整合

頁首或圖表旁顯示標的、日期區間、總筆數／可畫筆數、所有 source 的安全標籤與價格口徑。來源缺失、unknown 或 mixed 時如實標示，不能由 fallback 改稱官方。

- decision summary 可為空或資料待補；規則價位不是委託、成交或個人化建議。
- groups 顯示 membership 有效期，不把 membership 當熱門或催化劑。
- chips 分開顯示外資、投信、自營商與融資。「外資」是來源「外資及陸資」合計欄位的日常簡稱；三大法人只有這三類，不把廣義券商或分點併入。
- 券商／分點區塊依 exchange 提供 TWSE 或 TPEx 官方逐檔查詢入口，並顯示「目前未提供整合資料」。入口不形成主力排行、歷史分點資料或投資人身分判定。
- events 與 news 保留類型、來源及事件／發布時間，沿用 conflict／unknown 契約。
- strategy conditions 只說明輸入需求；實際結果讀 decision／signals，不新增前端評分。
- coverage／quality 保持可見，尤其 20／60 日與 bar／chip 缺口；raw 可收合，但缺資料原因不能只藏在 raw。

## 5. 驗收矩陣

| 案例 | 必須觀察到 |
| --- | --- |
| ≥60 根完整資料 | K、量、MA20、MA60、OHLCV 提示、縮放／復位、等效表格及區間／來源／basis 一致。 |
| 20–59／1–19 根 | MA20 從第 20 根開始；MA60 不足不畫。1–19 根仍顯示合法 K／量，兩條 MA 都不補。 |
| 0 根 | 顯示無圖表資料；其他 payload 若存在仍可研究。 |
| 非法 OHLC／volume | 拒列並顯示數量／原因，不補 close 或 0。 |
| 重複／反序日期 | 重複 fail closed；純順序問題可穩定排序但不改值。 |
| 缺日／停牌 | 不跨缺口算 MA 或造 K，與 coverage／is_suspended 相容。 |
| unknown／mixed source | 不顯示成單一官方來源。 |
| 法人籌碼 | 欄名為「外資／投信／自營商」；表外統一標示單位與空白原因，數值格只放含正負號的數字，合法 0 不消失。 |
| 券商／分點 | 依上市／上櫃標的開啟對應官方查詢；畫面明示尚未整合資料，不造主力排行或分點數值。 |
| events 與 news 並存 | 類型、來源、時間、連結與空值可辨識。 |
| 行動摘要缺失／待補 | 不造評分或價位；圖表與其他研究區塊仍可用。 |

### 5.1 2026-09-12 final review 證據

統籌於 2026-09-12 對穩定 source snapshot 完成前端資料邊界、型別、production build、桌面／窄版及隔離唯讀真實 API 流程的有限驗收；2330 的日期、OHLCV、MA20／MA60、縮放與復位，以及 4804 的空資料狀態均有核對。驗收保留大型 JS chunk 警告，且較早分頁曾出現後來已修正的 update-depth error。

此證據只結清本文矩陣，不涵蓋下一節項目。原始命令、測試次數、數值、hash 與暫存路徑可由基準版本查閱：`git show 69f62cf:docs/STOCK_RESEARCH_PAGE.md`。

## 6. 明確未包含

完整歷史下載、adjusted OHLC、PIT／availability truth、legacy／new signal comparison、B7 paired replay、Wilder ATR 正式接線、策略績效／勝率、AI 研究、完整 trade plan、個人風險部位、正式 DB migration、來源採購、自動排程與下單仍未完成。

## 7. 前端顯示契約

Round13 對 API 原始股數與圖表轉換的驗證仍有效；Round14 只改台股 UI 顯示。來源明確為股數的成交量和法人買賣超以 `原值 / 1,000` 顯示為「張」，最多 3 位小數並保留正負號；TWSE／TPEx 已核實的融資欄位按其官方「張」語意顯示。不得改寫 API、圖表／策略計算或 raw evidence。來源或單位 unknown／mixed 時不換算；數值格留空，單位待核實與空白原因放在表格外。完整單位與數值格規則見 [UX_REVIEW](UX_REVIEW.md#3-單位契約) 與 [UI_COPY_SPEC](UI_COPY_SPEC.md#104-數值表格單位與空白)。

正式資料另有市場別產業 membership 缺陷。重建前，個股與行動詳情顯示「既有族群關聯待重新核實」；族群中文名加「（既有分類）」與待核實 badge，原始 membership 名稱／ID 收進資料說明。不得顯示可信排名或將衍生條件宣稱已核實；這不改寫 OHLCV、單位或新聞。

2026-09-15 獨立 UI 維護已有限接受日常頁的繁中文案、空數值、外資／投信／自營商欄名、ETF 與族群代碼中文顯示，以及依市場導向的官方券商分點查詢入口。具名 browser 案例核對 2330 的法人張數與融資原單位、006201 的合法 0 與「ETF · 大盤型」、MA60 不足時留空、00687C 不猜新臺幣、TAIEX／close 對應「加權指數／收盤價」、中文新聞列表及兩市場官方入口；6 份記憶體前端測試與 final production build 均以 exit 0 通過。這項維護不新增 API 欄位、分點 collector、歷史資料或「主力」身分，也不是 full backend、一般 API startup 或正式部署驗收；大型 JavaScript chunk 警告仍是既有非阻擋限制。
