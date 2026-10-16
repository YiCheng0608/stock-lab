# 個股研究頁契約

本文定義 `/stocks/:exchange/:symbol` 的現行有限契約。這不代表完整研究產品、R0 或 [ROADMAP](ROADMAP.md) 已完成。

## 現行節次索引

各 explicit 版本彼此獨立：W8 依 §24 的原 cutoff／pins 保留，不自動提升 default。已歸檔節次與子節不在本文，查 Git 指標；`git show f431b9885cd3332ddd328309d0041a15c55b8610:docs/STOCK_RESEARCH_PAGE.md` 取得歸檔前全文，下表連結為該版本的行範圍。Issue #105 清空的收據小節在各標題下留 `git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` 指標。

| 節 | 範圍 | 現況與歸檔指標 |
| --- | --- | --- |
| [§1](#1-使用者工作與資訊順序) | 使用者工作與資訊順序 | 現行 |
| [§2](#2-現有-api-與畫面-cross-review) | 現有 API 與畫面 cross-review（2.1 實際 payload、2.2 價格口徑） | 現行 |
| [§3](#3-圖表資料契約) | 圖表資料契約（驗證與排序、MA20／MA60、互動與等效資訊） | 現行 |
| [§4](#4-來源區間與研究整合) | 來源、區間與研究整合 | 現行 |
| [§5](#5-驗收矩陣) | 驗收矩陣 | 現行 |
| [§6](#6-明確未包含) | 明確未包含 | 現行 |
| [§7](#7-前端顯示契約) | 前端顯示契約（7.1 UNIT-LOTS-1 日常張數與原股稽核） | 現行 |
| [§8](#8-籌碼三部分後續待做) | 籌碼三部分 | 現行 |
| [§9](#9-m1-p1截止一致與來源可追溯總覽) | M1-P1：截止一致與來源可追溯總覽 | 現行 |
| [§10](#10-m1-p2b單日法人原件總覽接線) | M1-P2b：單日法人原件總覽接線 | 現行 |
| [§11](#11-m1-p3bselected-官方事件總覽接線) | M1-P3b：selected 官方事件總覽接線 | 現行 |
| [§12](#12-m2-p1官方事件關注清單接個股總覽) | M2-P1：官方事件關注清單接個股總覽 | 現行 |
| [§13](#13-m2-p2官方事件清單搜尋與研究往返) | M2-P2：官方事件清單搜尋與研究往返 | 現行 |
| [§14](#14-m1r1-a2成交量-httpjavascript個股精確呈現) | M1／R1-A2：成交量 HTTP→JavaScript→個股精確呈現 | 現行 |
| [§15](#15-m3-p6c個股詳情行情讀回污染隔離) | M3-P6c：個股詳情行情讀回污染隔離 | 現行 |
| [§16](#16-m3-p6d個股詳情研究候選讀回污染隔離) | M3-P6d：個股詳情研究候選讀回污染隔離（16.1～16.4 契約、16.5 能力邊界） | 現行（保留 16.1～16.4）；§16.5 改為能力邊界，移出內容見原節：[L469–L529](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/STOCK_RESEARCH_PAGE.md#L469-L529) |
| [§17](#17-m3-p6e個股特徵籌碼獨立區塊讀回隔離) | M3-P6e：個股特徵／籌碼獨立區塊讀回隔離（17.1～17.4 契約、17.5 能力邊界） | 現行（保留 17.1～17.4）；§17.5 改為能力邊界，移出內容見原節：[L531–L582](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/STOCK_RESEARCH_PAGE.md#L531-L582) |
| [§18](#18-m1-w2同截止法人窗口與原件追溯) | M1-W2：同截止法人窗口 API／UI 共同基礎（18.1 取得與記憶體、18.2 精確窗口與來源展開） | 現行（保留 18.1、18.2）；移出內容見原節：[L584–L608](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/STOCK_RESEARCH_PAGE.md#L584-L608) |
| §19～§23 | M1-W3～W7 三至七截止法人窗口與原件追溯 | 歸檔：[L610–L760](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/STOCK_RESEARCH_PAGE.md#L610-L760)；現行見 [§24](#24-m1-w8八截止法人窗口與原件追溯) |
| [§24](#24-m1-w8八截止法人窗口與原件追溯) | M1-W8：八截止法人窗口與原件追溯（現行版本） | 現行（保留 24.1、24.3 能力邊界）；移出內容見原節：[L762–L789](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/STOCK_RESEARCH_PAGE.md#L762-L789) |
| [§25](#25-m1-price-1上櫃兩股單日價量閉環有限接受) | M1-PRICE-1：上櫃兩股單日價量閉環 | 現行（保留 25.1）；§25.2 改為能力邊界，移出內容見原節：[L791–L811](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/STOCK_RESEARCH_PAGE.md#L791-L811) |
| [§26](#26-m2-focus-lots-1精確成交張數關注與同截止往返有限接受) | M2-FOCUS-LOTS-1：精確成交張數關注與同截止往返（26.1～26.3 契約） | 現行（保留 26.1～26.3）；移出內容見原節：[L813–L853](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/STOCK_RESEARCH_PAGE.md#L813-L853) |
| [§27](#27-m2-focus-day-move-1單日方向關注與完整條件往返有限接受) | M2-FOCUS-DAY-MOVE-1：單日方向關注與完整條件往返（27.1～27.3 契約） | 現行（保留 27.1～27.3）；移出內容見原節：[L855–L896](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/STOCK_RESEARCH_PAGE.md#L855-L896) |
| [§28](#28-m2-focus-turnover-1精確成交金額與四條件往返有限接受) | M2-FOCUS-TURNOVER-1：精確成交金額與四條件往返（28.1～28.2 契約） | 現行（保留 28.1、28.2）；移出內容見原節：[L898–L933](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/STOCK_RESEARCH_PAGE.md#L898-L933) |
| [§29](#29-m2-focus-day-range-1本日振幅與五條件往返) | M2-FOCUS-DAY-RANGE-1：本日振幅與五條件往返（29.1～29.2 契約） | 現行（保留 29.1、29.2）；移出內容見原節：[L935–L975](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/STOCK_RESEARCH_PAGE.md#L935-L975) |
| §30～§33 | M2-FOCUS-STOCK-SCOPE-1～4：三～六股關注與同截止往返 | 歸檔：[L977–L1130](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/STOCK_RESEARCH_PAGE.md#L977-L1130)；現行 gate 見 [§34](#34-m2-focus-stock-scope-5七股關注與同截止往返)，policy 版本見[來源 §29.1](SOURCE_REGISTRY.md#291-1006-價格-policy-tuple-版本表) |
| [§34](#34-m2-focus-stock-scope-5七股關注與同截止往返) | M2-FOCUS-STOCK-SCOPE-5：七股（default 2026-10-06）關注與同截止往返 | 現行（保留 34.1 gate）；移出內容見原節：[L1132–L1163](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/STOCK_RESEARCH_PAGE.md#L1132-L1163) |
| [§35](#35-m1-price-save-1私人單日保存與跨程序操作) | M1-PRICE-SAVE-1：私人單日保存與跨程序操作（35.1 契約） | 現行（保留 35.1）；移出內容見原節：[L1165–L1189](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/STOCK_RESEARCH_PAGE.md#L1165-L1189) |
| [§36](#36-m1-chips-cutoff-1006-1同截止法人窗口與完整日曆) | M1-CHIPS-CUTOFF-1006-1：同截止法人窗口與完整日曆 | 現行 |
| [§37](#37-m1-saved-price-focus-1006-1保存來源關注與同截止往返) | M1-SAVED-PRICE-FOCUS-1006-1：保存來源關注與同截止往返 | 現行 |
| [§38](#38-m1-saved-price-chips-integration-1006-1共同入口與同截止往返) | M1-SAVED-PRICE-CHIPS-INTEGRATION-1006-1：共同入口與同截止往返 | 現行 |
| [§39](#39-m1-saved-price-chips-focus-1006-1八條件入口與不可用驗收邊界) | M1-SAVED-PRICE-CHIPS-FOCUS-1006-1：八條件入口與不可用驗收邊界 | 現行 |
| [§40](#40-m2-focus-stock-scope-6八股四條件與同截止往返) | M2-FOCUS-STOCK-SCOPE-6：八股四條件與同截止往返 | 現行 |
| [§41](#41-m1-saved-price-chips-focus-calendar-1006-2八條件正向關注與同截止往返) | M1-SAVED-PRICE-CHIPS-FOCUS-CALENDAR-1006-2：八條件正向關注與同截止往返 | 現行 |
| [§42](#42-m1-saved-price-chips-focus-stock-scope-7-1006-1七股八條件與同截止往返) | M1-SAVED-PRICE-CHIPS-FOCUS-STOCK-SCOPE-7-1006-1：七股八條件與同截止往返 | 現行 |
| [§43](#43-m1-chips-stock-scope-7-daily-net-trend-20-1006-1七股每日淨超與累計操作) | M1-CHIPS-STOCK-SCOPE-7-DAILY-NET-TREND-20-1006-1：七股每日淨超與累計操作 | 現行 |
| [§44](#44-m2-official-event-date-range-20261008-1官方事件日期區間與研究往返) | M2-OFFICIAL-EVENT-DATE-RANGE-20261008-1：官方事件日期區間與研究往返 | 現行 |
| [§45](#45-m2-official-event-kind-20261008-1b1官方事件精確類型與研究往返) | M2-OFFICIAL-EVENT-KIND-20261008-1/B1：官方事件精確類型與研究往返 | 現行 |
| [§46](#46-m1-twse-issuer-event-profile-20261008-1b1真公司原欄位與同截止事件研究) | M1-TWSE-ISSUER-EVENT-PROFILE-20261008-1/B1：真公司原欄位與同截止事件研究 | 現行 |
| [§47](#47-m1-twse-issuer-industry-trace-20261008-1b1公司原碼與產業名稱追溯) | M1-TWSE-ISSUER-INDUSTRY-TRACE-20261008-1/B1：公司原碼與產業名稱追溯 | 現行 |
| [§48](#48-m1-chips-stock-scope-7-gross-trade-20-1006-1b1七股gross買賣與net對照有限操作) | M1-CHIPS-STOCK-SCOPE-7-GROSS-TRADE-20-1006-1/B1：七股 gross 買賣與 net 對照有限操作 | 現行 |
| [§49](#49-m1-chips-stock-scope-7-direction-segments-20-1006-20261008-1b1七股方向與窗口區段有限操作) | M1-CHIPS-STOCK-SCOPE-7-DIRECTION-SEGMENTS-20-1006-20261008-1/B1：七股方向與窗口區段有限操作 | 現行 |
| [§50](#50-m1-chips-stock-scope-7-adjacent-windows-5-1006-20261008-1b1兩相鄰5日比較與雙原列操作) | M1-CHIPS-STOCK-SCOPE-7-ADJACENT-WINDOWS-5-1006-20261008-1/B1：兩相鄰 5 日比較與雙原列操作 | 現行 |
| [§51](#51-m1-chips-stock-scope-7-dealer-components-5-1006-20261008-1b1自行買賣避險及合計並列對帳) | M1-CHIPS-STOCK-SCOPE-7-DEALER-COMPONENTS-5-1006-20261008-1/B1：自行買賣、避險及合計並列對帳 | 現行 |
| [#9](#9七股自行買賣與避險五日方向組合頁) | #9：七股自行買賣與避險五日方向組合頁（入口與 RAW 控制、取得流程、原列追溯、本機 API 防護、已知限制） | 現行 |
| [#8](#8七股普通收盤-ma20-與-20-日報酬唯讀區塊) | #8：七股普通收盤 MA20 與 20 日報酬唯讀區塊（範圍與讀取閘門、數值與捨入、來源版本與不支援項、原因碼、畫面與操作、能力邊界） | 現行 |

## 1. 使用者工作與資訊順序

使用者先確認標的、實際資料區間與價格口徑，再依序讀取行動摘要、日 K／成交量／MA20／MA60、族群、法人籌碼、官方事件／新聞、策略條件，以及 coverage／來源。頁面允許零行動、零新聞、缺籌碼或均線不足；不得為填滿畫面造資料。它不是 AI 選股、下單或完整交易計畫。

## 2. 現有 API 與畫面 cross-review

### 2.1 實際 payload

前端 `getStock(exchange, symbol, asOf?)` 呼叫 `GET /stocks/{exchange}/{symbol}?as_of=YYYY-MM-DD`。`as_of` 可省略；後端組成同一資料日期截止的 instrument detail，再加入 decision summary、coverage、news 與 `overview`。M1-P1 總覽及日期控制見 §9；截止不代表歷史當時可得。

| 區塊 | 實際欄位／上限 | 呈現限制 |
| --- | --- | --- |
| 標的 | `instrument` | 以 exchange＋symbol 識別，顯示名稱與類型。 |
| 行情 | `bars` 最多 120 個候選位置，回傳舊到新；新增 `market_read` | 精確成交量依 §14；M3-P6c 的 nullable 讀回、欄位狀態、拒列不回填及有限接受範圍依 [§15](#15-m3-p6c個股詳情行情讀回污染隔離)。只代表本次視窗，known 不等於來源准入。 |
| 技術快照 | 最新一筆 `features` | 可作最新摘要，不能由單點 feature 畫歷史 MA；歷史 MA 由 response bars 算。 |
| 族群 | `groups` | 顯示名稱與有效期，不由名稱推論題材或熱門。 |
| 籌碼 | `chips` 最多 120 筆 | 法人／融資連同日期和來源顯示；不得推論分點或特定外資身分。 |
| 事件／新聞 | `events` 最多 50、active 非 conflict `news` 最多 20 | 分開或標示類型；不能互相冒充或一律稱已核實催化劑。 |
| 策略／行動 | `strategy_conditions`、`signals` 最多 20、`decision_summary` | requires 只是需求，不是通過；沿用既有價位、信心與 product-time 語意。 |
| 品質 | `coverage`、`quality_summary`、`data_quality` 最多 10 | 顯示用途別完整度、缺日與 unknown；圖表存在不能替代 coverage。 |
| M1-P1 總覽 | `overview`、`news_cutoff` | 原件合格價格、法人／事件缺項與研究條件共用資料截止；新增原件價格與既有 bars／K 線的來源驗收範圍不同，見 §9。 |

### 2.2 價格口徑

圖表只使用每根 bar 的原始 open／high／low／close。payload 沒有 `price_basis`、OHLC adjustment factor、applied-through 或完整公司行動還原鏈；單一 `adj_close` 不足以生成 adjusted OHLC。因此固定標示：

> 原始 API 價格；還原方式未提供

這不等於已確認「未還原」，也不代表還原已完成。

原 DB bars 沒有 currency 欄位，標的可能不是新臺幣計價；表外寫「各標的報價幣別的元」，指數寫「點」，未證幣別不得猜 NT$。M1-PRICE-1 的兩股 memory 另有正面 TWD typed 契約，依[§25](#25-m1-price-1上櫃兩股單日價量閉環有限接受)，不外推原 DB 或其他市場。

## 3. 圖表資料契約

### 3.1 驗證與排序

- date 必須合法且唯一；重複日期 fail closed，不能任選、平均或覆寫。
- O／H／L／C 須為有限數字且 `low <= min(open, close) <= max(open, close) <= high`；非法列不生成 K 棒，不能用 close 補值。
- 成交量可用性依 §14 的精確欄位與舊回應回退條件；不可用值不補 0，對應列／區塊須標不可用。
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

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §5.1。

## 6. 明確未包含

完整歷史下載、adjusted OHLC、PIT／availability truth、legacy／new signal comparison、B7 paired replay、Wilder ATR 正式接線、策略績效／勝率、AI 研究、完整 trade plan、個人風險部位、正式 DB migration、來源採購、自動排程與下單仍未完成。

## 7. 前端顯示契約

UNIT-LOTS-1 的現行日常主值以張顯示，單日／5 與 20 日法人及成交量保留精確零股，原股數移入預設收合的來源稽核 details；已為張的融資不再除 1,000。來源單位 unknown／mixed 不猜，合法零及正負方向保留，顯示換算不改 API／DB／計算或 raw evidence。統一格式、canonical 邊界、輸入與每股價格口徑只由 [UI_COPY_SPEC §10.3](UI_COPY_SPEC.md#103-張零股) 詳述；成交量 exact 欄位與圖形近似界線依 §14。§10、§14 與 §18～24 的原股表／DOM 值是各批當時驗收，保留歷史原值；現行主表與原股收合方式依下節。

市場別產業 membership 重建前，個股與行動詳情顯示「既有族群關聯待重新核實」；族群中文名加「（既有分類）」與待核實 badge。不得顯示可信排名或將衍生條件稱為已核實；這不改寫 OHLCV、單位或新聞。相關有限 UI review 只涵蓋文案、空值、法人命名、單位顯示、ETF／族群名稱及官方分點入口，不新增 API、分點資料、歷史 coverage 或主力身分。

### 7.1 UNIT-LOTS-1 日常張數與原股稽核（有限接受）

單日法人主表列張，原 buy／sell／net 及合計股字串在來源 details 可核對；5／20 日主表使用對應 horizon 的精確張數，daily evidence details 保留每日原股。5／20 日數值只在 shares 單位／canonical 編碼、支持截止與 available 日曆／窗口一致時顯示；required／valid 日期須各恰為該 horizon、唯一、升序且逐項相等，起訖／同 cutoff 及缺／壞日為空均須一致。拒用不補零或採較早／future 值；日期、版本、來源及缺日顯示保留，不放寬原准入。價格主表／quote 的成交量以張呈現，原股數在價格來源 details 保留；庫存與原始籌碼的日常／稽核分工依 UI 契約。

此為已接受的數量前置，沒有新來源／價格准入、磁碟保存或完整 M1 驗收；價格、trend 及突破／回踩 gates 不因換算而通過。固定樣本、memory 預覽／guard 及未跑項見[開發入口](development-baseline/README.md#unit-lots-1-台股張數前置的記憶體驗證入口)。

## 8. 籌碼三部分（後續待做）

個股頁的籌碼分成三個可分辨的區塊；下表是功能契約與定義，不代表資料或畫面已完整實作。

| 區塊 | 定義與邊界 |
| --- | --- |
| 三大法人 | 沿用現有外資、投信、自營商資料，保留日期、來源、正負方向與缺值；外資簡稱依 §4。融資資訊獨立顯示，不併入三大法人。 |
| 主力進出 | 由可驗證、可重現的券商分點交易統計推導買賣超、買賣分點家數差及 5／20 日集中度；「主力」只表示統計指標，不是特定投資人身分。交易日與選樣、家數差正負定義、Top N、集中度分母、缺日與版本須先核定才可計算。 |
| 券商分點 | 買賣超排行、單一分點歷史與同券商彙總；現行只有依市場導向的官方逐檔查詢入口。 |

現況只有三大法人區塊有資料：主力進出尚未計算，券商分點尚無交易明細匯入、排行、歷史或券商彙總；三區整合與自動更新均待實作與具名驗收。局部可重現匯入可獨立驗收，但不能因此宣稱已有完整免費歷史、PIT 或每日自動更新；來源邊界見 [DATA_SOURCES](DATA_SOURCES.md#券商分點與主力統計的來源邊界後續待做)。

## 9. M1-P1：截止一致與來源可追溯總覽

M1-P1 新增個股研究總覽、日期套用／最新資料操作，以及獨立 `GET /stocks/{exchange}/{symbol}/overview?as_of=YYYY-MM-DD`。初版總覽版本為 `stock-overview/p1-v1`；後續單日法人接線見[第 10 節](#10-m1-p2b單日法人原件總覽接線)，selected 官方事件見[第 11 節](#11-m1-p3bselected-官方事件總覽接線)。完整 M1 的法人窗口、完整事件 coverage 及成立／未成立研究條件仍未完成。

### 9.1 共用截止與時間

- `as_of` 是含當日的**資料日期篩選**，`cutoff_basis=data_date_inclusive`；明示日期不自動往後推。未指定時優先最新儲存行情日；M3-P6c 對無法定位行情日期的截止處置依 [§15.2](#152-候選窗口截止與未知日期)，不回退較早日期。無行情時仍取其他研究紀錄的最新資料日期，含 active 且時間 verified 的關聯新聞。財報優先公告日，缺公告時的期間日只提供截止基準，不證公告已可得；新聞優先發布、其次事件時間，按臺北轉為日期。無可用日期則為 null，不補今日。
- 同一 response 的行情、技術快照、法人、membership、策略／行動、公司行動、基本面、事件與品質使用同一截止；原資料日、`collected_at`、發布／事件時間保留，不改寫成截止日期。日期篩選不證來源准入、availability、修訂版本或 PIT，`historical_pit=unsupported`。
- 新聞清單在最多 20 筆限制前，依既有已核對的發布／事件時間篩選；datetime 按臺北截止日結束換算，date-only 保留純日期，未知／衝突或超過截止的項目不混入。收集時間不充發布時間。這是既有時間欄位的有限投影，不證事件原件、first availability 或歷史 PIT。
- 日期輸入套用後，URL query 與資料 query 使用同一 `as_of`；「最新資料」移除明示截止並回到 API 的實際資料日期。總覽保留事後研究與歷史可得性未支援的說明。

### 9.2 原件合格的價格視窗

本批只採已准入的 exact `STOCK_DAY_ALL`，來源／用途與 capture gate 依 [SOURCE_REGISTRY](SOURCE_REGISTRY.md#51-stock_day_all-selected-security-bars)，不因 legacy `source=twse`、官方名稱或歷史 P0 結果放行 `MI_INDEX`、TPEx 或其他來源。

先取截止以前最多 120 筆候選行情，再逐筆核對；拒列不另抓更早資料湊滿 120 筆。`candidate_count`、`valid_count`、實際 `from/to`、`latest`、合格 `bars` 與 `rejected[].date/reason` 分開回傳。M3-P6c 最新候選不合格時的 `latest=null`、歷史合格列保留與 nullable rejected 依 [§15.4](#154-m1-總覽版本與最新價格)，其餘研究入口仍可使用。只說本次實際範圍／筆數，不稱完整 N 個交易日；來源本身沒有 TAIEX，不由列數推導交易 session。

每筆合格價須符合：

1. TWSE／symbol／資料日期精確配對，行情經 raw FK 回指指定 `body.bin` 與同目錄 `receipt.json`；原件 hash、capture receipt、成功 HTTP、收集紀錄關聯與 capture time 一致。
2. 使用已 review registry version／digest、exact endpoint／GET 與 source version；`local_fetch`、`raw_store`、`summarize` 用途及必要 conditions 通過，保留顯名、授權與可追溯來源。
3. selected 原件 O／H／L／C、成交量、成交額狀態與保存列一致；OHLC 為正有限數且範圍合法，成交量為非負精確整數。重複日期拒用；缺 selected row、停牌、數值或證據無效保留具體原因。
4. 合格列保留 raw／ingestion identity、body／receipt SHA-256、來源／registry 版本、endpoint、capture／原收集時間；details 可核對每筆價格與來源。這只證**本地原件與保存值一致**，不是來源真偽、完整歷史、revision 或 PIT 的證明。

價格沿用 §2.2 原始 API 口徑與報價幣別限制，不產生 adjusted OHLC。成交額 unavailable 在總覽輸出 null、保留 status／reason；來源合法零仍顯示零，不把保存用的缺值 `0` 當有效來源零。既有 `detail.bars`／K 線仍是按日期篩選的原研究資料，不會因新增總覽而自動升格本批准入來源或完整窗口；頁首新報價取總覽合格 `latest`，不從 legacy 行動價或不合格 bar 補值。

### 9.3 法人、條件與新聞入口

本節只保留 M1-P1 當時的入口契約；5／20 日法人窗口見 §24、§36，官方事件見 §11。研究條件未因此啟用。

- 外資／投信／自營商 5／20 日：P1／P2b 版本固定回傳 `institutional.status=unavailable`、`values=null`，不補零、融資不併入。
- 突破／回踩條件：`conditions` 中的 `breakout_v1`／`pullback_v1` 固定為 `status=data_insufficient`，即使已有 Signal 亦同；日期、版本與 `reasons` 依讀回記錄改變。必要輸入、來源、時間與適用分類 gate、版本化規則計算及 API／UI 接線驗收均滿足後，才可判「成立／未成立」；Signal 或價位存在不算通過。
- 新聞與官方事件入口：可切到既有新聞／公告分頁，保留原時間與來源連結；P1 版本 `events.status=unavailable`。

M1-P2a 的 TPEx 日法人 capture／selected 摘要契約與單日兩檔支持範圍見[來源 §8](SOURCE_REGISTRY.md#8-m1-p2atpex-日法人來源與-selected-摘要)；單日 CLI 數值不作前端 fallback，已准入的 TPEx 單日能力依 §10 保留，不與多日窗口混用。

上述固定狀態是核心能力尚未接通的保守回應，不能解讀為本次行情或使用者設定暫時缺資料。條件原因會反映來源／時間／分類待核實、記錄缺失、無法定位、讀值無效或早於截止；原因變動不代表已能判定成立或未成立。分類是否必要須按所採策略／場景核對，不假定所有場景可省；門檻未滿足仍保持資料不足，不補零或猜結論。

既有分類待核實提示與原策略、價位／信心語意保留；本批沒有新評分、機率、完整交易計畫或張數。

### 9.4 本批有限驗收與待驗

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §9.4。

## 10. M1-P2b：單日法人原件總覽接線

本批在既有總覽新增獨立 `institutional_daily` 區塊，總覽版本為 `stock-overview/p2b-v1`，單日區塊版本為 `institutional-daily/p2b-v1`；只接明示設定的 TPEx 單日原件，不改成完整 5／20 交易日窗口。來源准入、股數口徑與原件 gate 沿用 [SOURCE_REGISTRY §8](SOURCE_REGISTRY.md#8-m1-p2atpex-日法人來源與-selected-摘要)。

### 10.1 明示設定與共用截止

[`institutional_daily.py`](../backend/app/institutional_daily.py) 從 server 執行環境讀取兩個設定：`STOCK_TPEX_INSTITUTIONAL_CAPTURE_ZIP` 是既有且核定 `capture.zip` 的絕對路徑，`STOCK_TPEX_INSTITUTIONAL_CAPTURE_DATE` 是對應原件的 Gregorian `YYYY-MM-DD` 日期。兩者須同時有效；不搜尋目錄、推算最新日、送網路 request、解壓、改原件、寫 DB／legacy 或快取。使用 M1-P2a 固定 manifest、registry version／digest 與 `free_public_local` profile，不接受 client 指定路徑或以未准入資料補值。

單日區塊使用 §9.1 的共用 `as_of`。原件日期須不晚於截止，不依法人設定改總覽日期；無共用截止時仍 unavailable。未明示 `as_of` 時，設定的法人日期也不作最新資料 cutoff fallback。各失敗結果保留 reason，`row`／`provenance`／`attribution` 為 null，不回傳原件內容或 server 檔案路徑。

| 條件 | 單日區塊結果 |
| --- | --- |
| 非 TPEx／無共用截止 | `daily_exchange_not_supported`／`daily_shared_cutoff_missing`，讀原件前停止。 |
| 兩個設定皆未提供／設定不完整或無效 | `daily_capture_not_configured`／`daily_invalid_configuration`；未配置不讀任何法人原件。 |
| 設定日期晚於截止 | `daily_after_cutoff`，讀原件前停止，不採用未來資料。 |
| 原件日期、selected row、receipt 或固定 pins 不合格 | unavailable，保留可識別的拒收原因；未能安全識別的例外以 `daily_evidence_invalid` 表示，不洩漏 OS 例外。 |
| 原件合格且日期等於／早於截止 | available；早於截止另留 `daily_configured_date_before_cutoff`，不能稱截至日前最新資料。 |

### 10.2 精確股數與可追溯呈現

合格 `row` 保留 symbol／company name、Gregorian `date`、原始民國 `source_date`、1-based `row_ordinal` 與三類 `source_fields`；外資及陸資（不含外資自營商）、投信、自營商的 buy／sell／net，以及 `total_net` 共十個數值均輸出 canonical 整數**字串**，`unit=shares`、`quantity_encoding=canonical_integer_string`。沿用 [SOURCE_REGISTRY §8.2](SOURCE_REGISTRY.md#82-selected-摘要契約與操作) 的整數範圍與加總 gate，合法來源零保留零，缺失或不一致不補零。

此單日原件表以**股**顯示，直接在整數字串加入千分位，不轉 JavaScript `Number` 或換算成張；因此超過安全整數的正負數仍保留全部位數。它是獨立的原件核對表，既有 §7 的法人歷史表顯示換算仍沿用原契約。融資不併入三大法人，不使用單日數值補 5／20 日窗口。

`provenance` 保留 exact endpoint、source／registry version、manifest digest、body／receipt 雙 SHA-256、capture time 與 `local_evidence_consistent` 語意；API 亦保留 attribution、summarize decision 與 condition receipts。畫面提供原件資料日、三類買進／賣出／淨超與合計、來源與授權入口，以及可展開的日期、列序、版本、雙 hash 和 capture time 原值。單日 available 只證選中列與本地原件一致，不證官方 origin authentication、完整市場、最新資料或 PIT。
P2b 版本的 5／20 日 `institutional.values` 仍為 null；單日可用時 reason 為 `multi_session_institutional_evidence_missing`、`trading_session_source_not_admitted`，不能把已准入的 TPEx 單日來源說成未准入。單日 `session_windows` 在本版 unavailable。

### 10.3 有限驗收與未支援範圍

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §10.3。

## 11. M1-P3b：selected 官方事件總覽接線

本批把 [SOURCE_REGISTRY §9](SOURCE_REGISTRY.md#9-m1-p3atwt48u-selected-官方事件原件摘要) 已有限接受的 TWT48U 記憶體 consumer 接到總覽，總覽版本為 `stock-overview/p3b-v1`，`events` 版本為 `official-events/p3b-v1`。只採原四來源固定 manifest／pins、`free_public_local` profile 與 exact TWT48U GET，不增加來源准入、完整歷史或研究條件。

### 11.1 明示取得與記憶體生命週期

[`official_events.py`](../backend/app/official_events.py) 需 server 明示 `STOCK_TWSE_EVENTS_MEMORY_CAPTURE=1` 才啟用取得操作；普通個股／總覽 GET 與模組 import 不送外網 request。專用 route 為 `POST /api/stocks/{exchange}/{symbol}/official-events/capture?as_of=YYYY-MM-DD`，不需要 body 參數；先確認 instrument 存在，再檢查 TWSE、4–6 碼 ASCII 大寫字母／數字 symbol 與 exact 啟用值。首次 POST 經既有 P3a capture 與 selected consumer 成功後，才發布一份 immutable body／receipt bytes tuple。取得操作不寫 DB、檔案或 ZIP，不使用 client 指定 endpoint、路徑、pins 或其他來源。

成功 cache 後，GET 與 POST 都只重驗同一份 bytes／receipt 並選取標的，不重新抓取、refresh 或背景更新。首個 selected 拒收或取得失敗不發布 cache；取得中另一請求以 `event_capture_in_progress` 拒收。重啟後才可能取得新原件；cache 消失不能稱已保存、可重開讀回或可離線重播。來源失敗、不合格 receipt／selected 或缺列回 unavailable，不以 legacy Event／NewsItem、網頁搜尋或未驗數值補值；selected 缺列亦不代表已驗證「無事件」。

### 11.2 共用截止與未來生效預告

總覽沿用 §9.1 的共用 `as_of`。本次 capture time 轉為臺北的 `observed_date`，只有 `observed_date <= as_of`（含當日）才可呈現該原件的 selected 事件；缺共用截止或截止早於觀測日仍 unavailable。觀測日期可提供未通過原因與操作提示，但不能自動取代共用截止或作「最新資料」日期 fallback。

官方 `Date` 仍是 `effective_date`，不是發布／首次可得時間；合格原件中的未來生效預告保留，不按 `event_date <= as_of` 刪掉。`published_at`、`first_available_at`、`revision_available_at` 仍 null／unknown，`historical_pit=unsupported`。本批只做本次觀測日期的事後研究篩選，不證精確時刻的 availability、歷史當時可得、完整 session 或 revision lineage。

### 11.3 可追溯呈現與拒收

合格 `rows` 只投影 exchange／symbol／company name、生效日期與原民國日期、原 `Exdividend` 分類字串、effective-date 角色／date 精度、分類／label、1-based 列序，以及三個 null 時間與 unknown availability。未驗金融欄位仍在 process 原 bytes，API 不公開完整 `source_row`，也不顯示其數值。`provenance` 保存 source／registry version、固定 pins、body／receipt 雙 hash、capture／request time、storage 與 `local_evidence_consistent`；API 另留 attribution、用途 decision 與 condition receipts。

畫面呈現證券身分、除息／除權／除權息、生效日期、觀測日期、未來生效預告與未驗發布／首次可得時間，並可展開原日期／分類、列序、版本、雙 hash 與 capture time。TWSE 原 manifest 的顯名取 `owner.name=Taiwan Stock Exchange (TWSE)`，授權取 `terms.value=OGL 1.0` 並連到 `https://data.gov.tw/license`；不用 TPEx 的 `data_provider`／year 欄位。型別、SSR 與實際授權顯名／href 已具名核對。

`source_url_kind=feed` 的連結使用「官方公告資料集」，說明未必定位本則，不能寫成「查看原文」。除權息分類不形成正負催化、價格影響、調整因子或成立／未成立條件；同一原件的選列驗證不代表全市場或完整歷史 coverage。非 TWSE、未明示啟用、尚無 cache、來源／selected 拒收、缺截止與截止早於觀測日等情境須可辨識，不補零或假事件。

| 條件 | `events` 結果 |
| --- | --- |
| 未提供／空啟用值、啟用值不是 exact `1` | `event_capture_not_enabled`／`event_capture_configuration_invalid`；不外網取得、不曝露 cache。 |
| 非 TWSE、invalid symbol | `event_exchange_not_supported`／`event_invalid_symbol`，不曝露 cache。 |
| 尚無成功 cache | 普通 GET 回 `event_memory_capture_missing`。 |
| 缺共用截止、截止早於臺北觀測日 | `event_shared_cutoff_missing`／`event_observation_after_cutoff`；可回 `observed_date` 提示，`rows=[]`、`provenance=null`，不補日期。 |
| selected 缺列、重複／分類／receipt 無效或 HTTP 失敗 | unavailable，保留安全 consumer reason 或 `http_status:503` 等狀態；未能安全識別的例外以 `event_evidence_invalid`／`event_capture_failed` 表示，不洩漏 OS 路徑。 |
| 合格 selected 且觀測日不晚於截止 | available，保留全部合格 selected 事件，包括晚於截止的未來生效預告；不是截至日前最新 feed 或歷史 PIT。 |

### 11.4 有限驗收與未支援範圍

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §11.4。

## 12. M2-P1：官方事件關注清單接個股總覽

本批在今日頁新增官方事件關注清單，版本 `official-event-focus/p1-v1`；只採既有 exact TWT48U 記憶體來源與固定 pins，不把事件分類變成交易訊號、價格影響或可信排名。來源 consumer 契約見[來源 §11](SOURCE_REGISTRY.md#11-m2-p1本次官方事件-feed-摘要)，M1 的 5／20 日與研究條件等待狀態保留。

### 12.1 明示截止、取得與同一份原件

`GET /api/focus/official-events?as_of=YYYY-MM-DD` 必須明示有效日期，缺少或 invalid query 回 HTTP 422，普通 GET 與 import 不送外網 request。`POST /api/focus/official-events/capture?as_of=YYYY-MM-DD` 才是首次取得操作，不需 body 參數；沿用 server exact `STOCK_TWSE_EVENTS_MEMORY_CAPTURE=1` 與 §11.1 的固定來源、用途及記憶體限制，不需 client 指定 endpoint、pins 或檔案路徑。今日頁未帶 query 時，日期控制預填當下臺北日期並明示送給 API；這不更動 M1「最新資料」的 cutoff fallback。

關注清單與 P3b 個股事件共用同一 process 的 cache／鎖；首次合格 capture 成功後只再用同一份 immutable body／receipt，不 refresh 或背景更新。合法空 feed 可發布成功 cache，之後 selected consumer 仍須拒收缺 selected，不能把零筆關注結果改成已證個股無事件。取得中、HTTP／receipt／feed 不合格、未明示啟用或沒有 cache 與合法零筆須分開；失敗不發布新 cache。重啟後記憶體消失，不能稱持久化或可離線重播。

本次 capture 的臺北 `observed_date` 須不晚於明示 `as_of`，才可呈現清單；較早截止不回事件，也不由觀測日補日期。官方生效日期仍可晚於截止，保留為未來生效預告。觀測日／UTC capture time 與生效日分開；發布／首次可得／修訂時間仍 null／unknown，`historical_pit=unsupported`。`as_of` 只限制這次觀測的事後研究範圍，不證當時已可得、截至日前最新 feed 或完整交易日。

| 情境 | 關注清單結果 |
| --- | --- |
| 無成功 cache 的普通 GET | `event_memory_capture_missing`；只在截止不早於當下臺北日期時允許首次取得。 |
| 無 cache 且 POST 截止早於當下臺北日期 | `event_cutoff_before_current_observation`，零外網取得。 |
| cache 觀測日晚於截止 | `event_observation_after_cutoff`，`items=[]`／`provenance=null`；同原件仍保留，不取得新版本。 |
| 未啟用、設定錯誤或取得中 | `event_capture_not_enabled`、`event_capture_configuration_invalid` 或 `event_capture_in_progress`；不公開事件內容。 |
| feed／receipt 拒收或 HTTP 失敗 | unavailable，保留安全 consumer reason 或 `http_status:503`；不發布成功 cache。 |
| 合格 feed，觀測日不晚於截止 | available，含合法零筆；再次讀取或 POST 為 `capture_action=cached`，不 refresh。 |

所有 focus 回應均無頂層 `rows`；非 available 結果的 `items=[]`，不以原件內容作 fallback。回應的 `coverage=observed_feed_only`、`research_conditions=unknown` 明列範圍。

### 12.2 同股去重與可追溯理由

全 feed 合格後，以 TWSE＋來源代碼組成一張關注卡，同股所有事件放在 `items[].events`，保留原件列序及各自生效日期／除權息分類。關注理由只陳述「本次官方資料集觀測到的除權息事件」，不加正負催化、分數、勝率、價位或策略成立判斷。`order=symbol_lexicographic` 是固定代碼字串順序，不表示推薦次序；`limit=100`，`total` 是本次不同標的數、`displayed` 是實際顯示標的數，`truncated` 表示是否超過上限，不讓截斷偽裝成完整清單。`candidate_count`／`selected_count` 是已驗的 feed 事件列數，不能當標的數或交易股數。

來源代碼／公司名與事件先保留，`company_name` 不由 catalogue 名稱覆寫。Catalogue 的 TWSE＋代碼已知時，`stock_page_available=true`，`detail_url` 提供帶同一 `as_of` 的 M1 個股總覽入口；未知時為 false／null，保留來源名稱與事件，顯示尚無個股目錄對應，不猜 instrument 或建立連結。已知標的連結不放行 M1 缺少的價格、法人窗口或研究條件，也不把 ETF 稱普通股票。

清單呈現「本次觀測」、觀測日、生效日及未來預告；原日期／分類與列序收在「事件原件值」。來源 details 提供來源／授權入口、來源與 registry version、固定 pins、雙 hash 與格式化觀測時間；API 保留 capture／request UTC 原值及用途／條件 receipts。`source_url_kind=feed` 的入口定位官方資料集，畫面來源「臺灣證券交易所原始資料」不稱本則單篇原文；未驗金融數值不公開。合法空 JSON array 只表示**這次合格 feed 零筆**，不代表全市場沒有事件；來源不足、invalid 或 cutoff 拒用仍 unavailable，不補候選。

### 12.3 驗收與尚缺項

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §12.3。

## 13. M2-P2：官方事件清單搜尋與研究往返

版本為 `official-event-focus/p2-v1`，沿用 §12 的來源、完整 feed 驗證、明示取得、截止與 cache。搜尋完整合格原件，M1 返回保留原清單條件；來源 pins、unknown availability、PIT 與完整 M1／M2 gate 維持。

### 13.1 先驗全原件，再搜尋與限制顯示數

`GET /api/focus/official-events?as_of=YYYY-MM-DD&q=...` 與明示首次 `POST /api/focus/official-events/capture?as_of=YYYY-MM-DD&q=...` 的 `q` 為 optional，預設空字串；有效 `as_of` 仍必填。`q` 的原始長度最多 **100 個 Unicode 字元**，先驗長度再 `strip` 去除前後空白；包括 101 個空白的超長 query 皆回 HTTP 422，不取得來源。純函式另對非字串／超長值回 unavailable、`event_search_query_invalid`、`can_capture=false`，不抓外網。

合法 query 在 `search_query` 保留去除前後空白後的原大小寫，以 `casefold` 作不分大小寫的 **literal substring（連續文字）** 比對；不作 regex、模糊搜尋或推薦。完整 body 身分／日期／分類、receipt／pins／hash 與截止 gate 先通過，才按來源代碼去重、搜尋、固定代碼排序及套 100 股上限。任一原件列不合格即整份 unavailable，即使該列不符合搜尋或在顯示上限以外也不得略過。

搜尋只比對來源 `Code` 或該股任一事件的來源 `Name`，不使用 catalogue 名稱。某股任一名稱或代碼符合時，該卡保留該股全部合格事件及各自原件列序，不只留下符合名稱的事件。Catalogue 仍只決定是否有既有 M1 入口，不覆寫來源名稱或擴張搜尋範圍。

| 回應欄位 | 意義 |
| --- | --- |
| `candidate_count`／`selected_count` | 已驗全 feed 的原件事件列數；搜尋不改成符合標的數。 |
| `total` | 搜尋前原件去重標的數。 |
| `matched` | 完整合格 feed 中符合搜尋的標的數。 |
| `displayed` | 實際顯示標的數，等於 `min(matched, 100)`。 |
| `truncated` | `matched > 100`；依符合結果計算，不因原清單超過 100 股而誤報搜尋截斷。 |
| `search_query` | 已去除前後空白的 query；空字串表示查看全原件標的。 |

空原件為 available、`total=matched=displayed=0`，只證本次合格原件零列；非空原件無符合為 available、`total>0`／`matched=displayed=0`，可清除搜尋回全清單；來源或截止不可用為 unavailable，不顯示結果統計或舊卡片。三者文案分開，皆不推論全市場沒有事件。unavailable 的 `items=[]`，無頂層 `rows`，初始 `total`／`matched`／`displayed` 為 0；這些零值不是已驗原件為空的證據。

### 13.2 提交搜尋與固定研究返回路徑

今日頁搜尋僅 Enter／「搜尋」提交，輸入中的 draft 不更新 query 或呼叫 API；「清除搜尋」保留當前 `as_of` 並回本次全清單。超長 draft 顯示錯誤，不提交。查詢 key 同時包含 `as_of`／`q`，不以舊結果作新條件的 placeholder；首次 POST 結果及錯誤保留其請求 key，不能套到已切換的條件。搜尋、截止、返回與讀 cache 均不 refresh 來源。

已知 catalogue 的 `detail_url` 固定為 `/stocks/TWSE/{symbol}`，query 帶相同 `as_of`、`from=official-events`、去除前後空白的 `focus_q` 與原清單 `focus_as_of`。只有固定 `from` 值、有效原截止（含拒絕 0000 年）及不超過 100 個 Unicode 字元的原 query 才提供「返回官方事件關注」，返回固定 `/?as_of=原focus_as_of&q=原focus_q#official-event-focus-title`，參數經 URL 編碼；不接受自由 return URL。M1 內修改個股截止仍保留原清單條件，返回時恢復原搜尋／截止。前端去除空白與 Python `strip` 使用相同集合，包括 NEL／U+001C–001F，保留 FEFF，避免同 query 的字元語意分歧。參數不合格時回既有個股入口，不猜原清單；未知 catalogue 仍保留事件但無個股連結。

### 13.3 本次有限驗收與尚缺項

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §13.3。

## 14. M1／R1-A2：成交量 HTTP→JavaScript→個股精確呈現

本批支援 M1 研究資料可信／R1-A2，處理 HTTP 整數 token 經 JavaScript `Number` 後可能失去位數的呈現缺口；有限接受不代表真官方／live、完整產品或 production 驗收。

### 14.1 API 增欄與舊回應相容

個股行情及可用總覽的成交量新增 `volume_exact: string | null`，既有數字 `volume` 保留。精確欄位表示股數，須為 ASCII 十進位 canonical 非負整數字串：只有 `0` 或非零數字開頭的連續數字，範圍為 **0–9223372036854775807**（含上限）。不接受前導零、正負號、小數、科學記號、千分位或空白；無法提供合法精確值時為 null，不補成零。後端只新增純 helper 與本批 API 投影，不變更 portfolio、parser、selected consumer 或來源 gate。

前端先驗精確欄位，不以已失真的數字覆蓋它：

| 回應情況 | 成交量呈現 |
| --- | --- |
| `volume_exact` 是範圍內的 canonical 字串 | 使用字串保留全部位數。 |
| 舊回應沒有該欄位，讀得 `undefined` | 僅當 `volume` 是 `Number.isSafeInteger` 的非負數時，才轉成整數字串回退。 |
| 精確欄位為 null、非字串、格式不合法或超過 int64 上限 | 不回退到 `volume`；顯示不可用／空白及既有缺值說明。 |
| 舊回應數字不是非負安全整數 | 不補零，不聲稱精確值可用。 |

### 14.2 股、張與圖形的精度

股數直接在整數字串加入千分位。來源明確為股數時，張數以字串切分末三位換算，必要時補足小數前的零；不先轉 `Number`、除法或四捨五入，不遺失零股。合法零顯示 `0`，缺值與零分開；來源單位 unknown／mixed 的原限制保留。

| 精確股數 | 股數文字 | 張數文字 |
| --- | --- | --- |
| `0` | `0` | `0` |
| `1` | `1` | `0.001` |
| `9007199254740993` | `9,007,199,254,740,993` | `9,007,199,254,740.993` |
| `9223372036854775807` | `9,223,372,036,854,775,807` | `9,223,372,036,854,775.807` |

有可用成交量時，App 頂部、日行情表、總覽張數 quote 與股數表格、圖表 tooltip 及等效資料表均接相同精確值。圖形高度仍使用數字近似並須明示；核對值以 tooltip 與資料表的精確文字為準。這不改 OHLC、MA、時間／來源、策略計算或原始證據，不放寬下述 TPEx 總覽缺口。

### 14.3 准入與本輪有限接受範圍

TWSE 總覽仍須通過 §9 的 selected 原件證據 gate；不能因增添精確欄位而接受不合格價格。TPEx detail 可用時接本欄位，總覽維持現有 unavailable，不為本批放寬來源。單日法人精確股數、完整 5／20 日窗口、研究條件、M1-P4a unknown 權利、完整 M1／M2／M3 與 PIT 的原限制保留。

記憶體原件 fixture 僅 patch `_capture_evidence`、承接既有 selected gate，只支持 synthetic／相容邊界，不稱官方真實樣本或 live，不新增來源准入、正式 DB 或磁碟保存驗收；零落盤入口與隔離限制見[開發入口](development-baseline/README.md#m1r1-a2-成交量精確呈現的零落盤驗證入口)。

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §14.3。

### 14.4 統籌具名操作與未驗邊界

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §14.4。

## 15. M3-P6c：個股詳情行情讀回污染隔離

本批支援 M3／R2-C2。精確讀回契約由本節負責，文案見[UI](UI_COPY_SPEC.md#102-個股詳情的第一屏)，入口見[開發文件](development-baseline/README.md#m3-p6c-個股詳情行情讀回的零落盤驗證入口)。P6b 的污染詳情未因本批追認；不新增來源、即時價格、Plan 或交易能力。

### 15.1 原始投影、nullable 值與讀值狀態

Stock detail／instrument detail 與 M1 候選行情以未定型 SQL 讀十七欄：`id`、`instrument_id`、`trading_date`、`open`、`high`、`low`、`close`、`adj_close`、`volume`、`turnover`、`turnover_status`、`turnover_reason`、`source`、`data_as_of`、`collected_at`、`raw_payload_id`、`is_suspended`；不載入完整 MarketBar 的 Date／DateTime／Float processor，也不修改 shared `bar_dict`、decision read 或 portfolio quote。

公開 `bars` 保留候選 `id`，`date` 及必要數值／metadata 無法安全投影時為 null，不補 0、不 cast 救回 TEXT／BLOB 或修原列。逐欄原值為 SQL NULL 時記 missing，非 NULL 但未通過讀值規則時記 invalid；OHLC 幾何不成立另記 `ohlc=invalid`。這是 SQLite affinity 已處理的讀值，不恢復保存前的 token 或原始意圖。

| 分類 | 讀值規則與影響 |
| --- | --- |
| 核心 | 日期為合法完整 `YYYY-MM-DD`；OHLC 為 actual int／float、排除 bool、正有限且 low／high 範圍成立；volume 為 actual int、0–9223372036854775807；source 沿既有可編碼、非空與控制字元限制；停牌旗標只收 actual int 0／1。合法 volume 0 保留，精確文字依 §14。 |
| 可選 metadata | `adj_close`、turnover／status／reason、`data_as_of`、`collected_at`、raw FK 逐欄列於 `metadata_fields`；壞 metadata 投影 null，不單憑該欄使可畫的核心 OHLC 無效。turnover 只收非負有限數，status 只收 available／unavailable／unknown；raw FK 只收正 actual int。這些讀值仍不等於 M1 原件或來源證據。 |
| `market_read` | 列與頂層提供 known／missing／invalid、`invalid_fields`、`missing_fields`、`metadata_fields`；核心 invalid 優先，其次 missing，均無者才 known。known 只證語法，`verification=stored_value_syntax_only`，不證用途、官方日期、availability、tick 或 PIT。 |

頂層另提供 `candidate_count`、`window_limit=120`、`unlocated_count` 與第一個 `unlocated_market_bar_id`。無候選列為 missing、`missing_fields=["market_bar"]`；任何無法定位日期使頂層 invalid，即使該列不在回傳的 120 個位置內。完整條件與原始日期不可由 status 單獨推定。

### 15.2 候選窗口、截止與未知日期

原儲存 `trading_date DESC`、`id DESC` 決定候選位置；合法 future date 依明示／共用截止排除，最多 120 個位置**先限定再驗值**。拒列保留其位置，不先 filter 合格列、較早 fallback 或另取較早資料補滿；detail 回傳這個候選窗口的反向次序，非法日期不冒充已知的時間順序。

無法定位日期的檢查涵蓋該標的全部儲存行情，不受 cutoff／120 列窗口限制；非法字串不能當 lexical future 略過。未明示 `as_of` 時，有任一無法定位日期即使其他行情日期合法，共用 cutoff 仍為 null，不改用較早日或今日。明示合法 `as_of` 保留原值，可用研究區塊沿該日期篩選，但未知行情日仍阻止頁首報價與 M1 latest。完全沒有行情時，§9.1 的其他研究日期 fallback 維持。

### 15.3 圖表缺口、有限均線與頁首

圖表只畫核心讀值合格、日期合法且唯一的 bar；已知日期的拒列／重複列保留空位置。coverage 的已知缺日可加入 gap，但不建立 K 棒或收盤值；均線不跨 gap，之後須重新累積完整 20／60 個合格 close。日期無法定位時，包含窗口外的 unknown，整個視窗 MA20／MA60 均為 null；同一來源與價格基準限制保留。即使每個 close 有限，平均的中間加總或結果非有限也投影 null，不輸出 Infinity／NaN。

StockPage 核對頂層 status、各狀態陣列／metadata、120 窗口與候選數、unknown 數及 verification；known 必須至少一個候選、核心無缺項／invalid、七個 metadata key 完整。合法 missing 且 candidate_count=0 可保留空 metadata，不誤標 invalid。只有一致的 known 和合格候選可進價格呈現；invalid／missing、不支援或 malformed 新契約、狀態矛盾、候選值矛盾及非有限價格拒用。完全 undefined 的舊 API 才沿原有限數值相容，不用 malformed 新回應 fallback legacy 值。

stored syntax known 但 M1 `overview.price.status=unavailable` 只表示未准入／缺原件證據，頁首價格／漲跌待核實，不能因此顯示「行情讀值無效」。真 invalid／missing、partial 或 conflicting 回應才用新增讀值缺口提示；其餘獨立可用研究區塊保留。正常 M1 unavailable 與 missing 0／空 metadata 的兩項退修，經受影響 actual HTTP／完整 App SSR 及具名畫面後才有限接受，原失敗另報。

### 15.4 M1 總覽版本與最新價格

新總覽 presentation version 為 `stock-overview/p6c-v1`，反映 nullable rejected、讀值狀態與 no-fallback 語義；registry／source／purpose／version／digest pins 未改。§9.2 的 selected 原件、raw FK／body／receipt、hash、來源、用途及時間 gate 保留，`_stable_read`／`_capture_evidence` 未修改；未驗必要原件／磁碟條件不以記憶體替代。

`price.latest` 只在**最新候選本身**通過完整 M1 核對、且該標的無無法定位日期時成立。最新候選未准入／證據或數值不合格時，不改用較早合格價格；`price.status=unavailable`、latest=null，可保留較早真正合格的歷史 `bars`、`valid_count` 與 from／to。`rejected` 保留候選 id、nullable date 與具體 reason；unknown 日期及最新候選未合格分別列出原因。M1 可用價格與 detail 語法 known 仍是不同驗收層。
本批能力邊界同 §16.5；physical canvas、有效歷史窄版 layout 與真正截止表單提交另保持未驗。

### 15.5 具名有限接受與未包含

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §15.5。

## 16. M3-P6d：個股詳情研究候選讀回污染隔離

本批支援 M3／R2-C2；stock／instrument detail 的 Signal／StrategyVersion raw 讀回與必要 decision／overview caller 的精確契約由本節負責，文案見[UI](UI_COPY_SPEC.md#102-個股詳情的第一屏)，入口見[開發文件](development-baseline/README.md#m3-p6d-個股研究候選讀回的零落盤驗證入口)；版本收據留 Git／原 task，不倒改 P6c 的原驗收。

### 16.1 只在個股路徑啟用的原始投影

stock／instrument detail 以 raw SQL 左連接 Signal 與 StrategyVersion，避開完整 Date／DateTime／Float／JSON processor；decision 的 `stock_research_reads=True` 只由個股 caller opt-in，cache 區分該模式。overview 的條件及無行情 Signal 日期 fallback 使用同一 raw reader；舊 Actions／tracking 等預設 typed Signal 路徑沒有擴成此模式，也不修改 models、原列、writer 或 shared 行情契約。

候選保留原 `id`、`instrument_id`、`strategy_version_id`、日期與原 status；不能安全投影的欄位為 null，逐欄 `metadata_fields` 分 known／missing／invalid。SQL NULL 在投影層保留 missing，非 NULL 壞值列 invalid，不補 0、空 evidence 或較早列。這是讀回語法分類，不還原 SQLite affinity 前的 token，也不證來源、用途、可得時間、tick、PIT 或研究條件成立。

| 分類 | 讀值與影響 |
| --- | --- |
| 必要身份 | id／instrument FK／version FK 為 actual 正 int64；signal key／status／data quality／strategy name／version 為有界、可編碼的非空字串；signal_date 為合法完整日期。核心欄位 missing／invalid 保留狀態，不構造身份。前端另核 safe integer，不能安全辨識的回應拒用。 |
| 被策略消費的值 | breakout 使用突破／失效／目標價；pullback 使用參考進場／回踩區／失效／目標價。提供的價格須 actual int／float、排 bool、正且有限；evidence／data_cutoff／earliest_execution_date 的 present invalid 也使該候選 invalid。缺少可 nullable 的價位／時間／evidence 不新增必填 gate，仍由原策略語意判斷。 |
| 可選 metadata | confidence、rationale、source_report、entry_type、execution 欄位、created_at，以及 strategy kind／config／snapshot／active／created_at 逐欄保留狀態；壞值投影 null，不僅因可選欄位使所有完整策略失效。讀值 known 不是 source／time／version 准入。 |

`signal_read` 提供 status、invalid_fields、missing_fields、metadata_fields；invalid 優先於必要身份 missing，否則 known。合法但未知的策略 version 保留原語意，不假定所有 actionability gate 已驗；complete observation 缺少預期進場價位是原本的正常研究結果，不能被新必填條件改成污染。

### 16.2 JSON 與有限計算

Signal evidence 與 StrategyVersion config／canonical snapshot 只收可用 UTF-8 表示、最外層為 object 的 JSON；拒絕重複 key、非有限 constant／number、過深或過多節點。每欄最多 **65,536 UTF-8 bytes**，root depth 0、最大 **32**，最大 **16,384 nodes**，object key 也計 node。所有嵌套 integer 需能轉成有限 Float，避免 Python 可解析的巨大 integer 在 browser 變成 Infinity；這不是 Decimal exact 驗證。

合法 `{}` 保留；present invalid 投影 null／invalid，不能改成 `{}` 讓下游採空 evidence。SQL None 維持 null／missing 及既有 fallback，沒有新增必填 gate；本批只在 pure projection／RR 邊界驗此語意，不稱已向 NOT NULL SQLite 欄位保存 SQL NULL。evidence 的 inputs／levels 若提供須為 object，被消費的 RR 與三項數值 inputs 須 actual 有限數字。後端附加的 level_semantics 與 raw JSON 分開處理，前端核其一致且有界，不讓生成欄位侵占合法 raw JSON 的 node／depth 預算。

stock 模式 derived RR 的中間計算／結果非有限時投影 null；已有有限 evidence／fallback 規則保留，不製造 RR 或可操作結論。本批不增加 writer geometry、獨立 tick、source／time／version gate；既有規則仍決定合法研究行動。

### 16.3 詳情窗口、全集 latest 與截止

原儲存 signal_date DESC、id DESC 定候選次序；可定位且晚於 cutoff 的列排除，日期未知不能靠 lexical 大小當 future 略過。詳情保留最多 **20 個候選位置，先限定再驗值**，壞列不刪掉、不取較早合法列補滿。`candidate_order` 與回傳 signals 一致，不冒稱未知日期已知時間順序。

每策略 canonical latest 的 scope 是符合截止的全候選集，與詳情 20 列不同。breakout_v1／pullback_v1 各取其原排序最新列，bad latest 不能換較早候選；詳情的 20 個 custom invalid 記錄也不代替窗口外的健康 canonical slot。

全標的的無法定位日期檢查不受截止／20 列限制；符合截止範圍內無法定位 strategy identity（缺／壞 FK、無可定位的 joined id／name）也使整個研究 scope 拒用，而非略過未知策略。已定位 invalid core 只隔離該候選／策略 slot，其他健康策略沿原 actionability，aggregate invalid 不等於全面丟棄研究結果。

Signal 污染不撤掉已有合法 bar cutoff，獨立行情沿 §15 處理。無行情時，Signal 的日期 fallback 改用 raw 日期；有任一 unlocated Signal 日且未明示 as_of，共用 cutoff 保持 null，不改成較早日或今日。明示 cutoff 保留；其他 typed 研究日期仍有原依賴，不稱 FeatureSnapshot／Chip 污染已隔離。

### 16.4 回應與前端拒用界線

頂層與個股 decision 提供 `research_read`，version 為 `stock-research-read/v1`、verification 為 `stored_value_syntax_only`。其 candidate_count／candidate_order／window_limit=20、scanned／future／兩種 unlocated count 與第一個 id、兩個 canonical latest slot、blocked_strategies、decision_block_scope 一起核對；scope 為 instrument／slots／none。無候選為 missing；窗口內有候選 invalid 或全標的無法定位則 aggregate invalid，但可保留健康 alternate。

StockPage 核 candidate 身份、次序、欄位狀態、canonical slot 與 decision 的 envelope 一致；unsupported／矛盾／malformed 新回應不得拿 legacy 值補 summary／levels。完全 undefined 的舊回應只保留受限 action shape／有限數值相容與未提供狀態說明；null 不是 legacy。候選／slot 的 read.status 必須是 actual string known／missing／invalid，不能透過 String coercion 接受 array 或自訂 object。非字串拒用已做 focused pure／Panel 補驗，known 提示不冒用於 malformed status；HTTP-derived malformed 與非 JSON helper 的支持範圍由開發入口區分，不外推所有型別組合。

結構安全的 invalid／data_insufficient 結果可顯示，候選列表只讀原身份／日期／策略／版本／狀態，不是 Plan 或交易入口。held 的 `hold_observe`、`primary_strategy=null` 且 complete／known observation、空 missing／全 null 價位保留；正常 observation 不因沒有 expected entry levels 被抹除。summary 不可信時拒用研究行動／levels，bars 與其他獨立可用區塊保留；其中 typed models 本身的污染仍在本批範圍外。

### 16.5 能力邊界

本批不證：正向 M1 raw filesystem／磁碟重開、正式 DB／migration、官方／live／availability／PIT、Decimal exact、新 Plan、全部行動或完整 M1／M3；FeatureSnapshot／Chip、legacy tracking／Actions 等其他 typed models 尚未支持此隔離。

## 17. M3-P6e：個股特徵／籌碼獨立區塊讀回隔離

本批支援 M3／R2-C2，接續 §16 未納入的特徵／籌碼。污染留在自己的區塊，健康行情／研究仍可查看。版本收據留 Git／原 task，P6d 原測試與失敗只適用 §16。

### 17.1 個股 opt-in raw 投影與欄位狀態

產品稱呼 FeatureSnapshot／Chip 的實際保存模型為 `TechnicalFeature`／`ChipSnapshot`。只在 stock／instrument detail 及必要 stock decision／overview caller 啟用兩表 raw reader：`technical_features` 全 **6** 欄、`chip_snapshots` 全 **15** 欄繞過 Date／DateTime／JSON processor，**不使用 CAST**、不修資料或改 writer。其他 typed routes、legacy Actions／tracking 不在此 opt-in 隔離範圍。

feature snapshot 保留 id、instrument_id、trading_date、features_json、source、created_at；chip 保留 id／instrument_id／日期、八數值、source／data_as_of／collected_at／raw_payload_id。raw 身份僅接受正 int64、不 coercion；前端 section 身份另要求 JavaScript safe integer，不能把超 safe 的原始身份捨入後當同一列。每個欄位分 known／missing／invalid，missing／invalid 投影為 null，拒絕把數字字串、布林或非有限數字當可信數值。row_read 描述欄位狀態；feature_read／chip_read 使用 `stock-independent-read/v1`，含候選筆數／順序、scanned／future／unlocated count 與位置。`stored_value_syntax_only` 只證儲存讀值語法，known 不證來源、可得時間、用途或 PIT。

### 17.2 截止、窗口與無較早替代

raw 候選排序為 trading_date DESC／id DESC；先在完整該標的 scope 辨識日期，可定位且晚於截止的 known future 先排除，再固定 **feature 1／chips 120** 候選位置後驗值。不先刪 invalid 列湊窗口、不 refill；bad latest 不回到較早 feature，chips 壞列保留位置與 null 欄位。unlocated 在全 scope 判定，窗口外的無法定位日期不能因未顯示而消失。chips API 將同一固定候選反向供顯示，不重新查較早列；scanned／future／unlocated counts 指完整該標的 scope，與 coverage 分開。coverage 只採這 120 候選中日期合法且原五 consumed core 完整、並落在既有 TAIEX window 的交集；不證完整來源／市場 coverage。

健康 bars 的截止沿原優先規則；無 bars 時，兩獨立表任一 unlocated 使 default cutoff 保持 None，不取其他較早合法日冒充。明示 as_of 保留原值，但不把 unlocated 變成可用列；feature invalid／unlocated envelope 拒用 MA 呈現、不以較早快照替代。這是日期篩選與語法隔離，不證完整交易日、來源時間或歷史當時可得。

### 17.3 特徵 JSON、MA 與籌碼既有依賴

後端 features_json 沿原 strict dict reader，檢查原 JSON **65,536 UTF-8 bytes／depth 32／nodes 16,384**、合法 Unicode 與有限數字；不是 dict 或超限拒用。MA20／MA60 只接受內建有限數值，**零與負值保留**，不新增 positive gate；可選 source／created_at 無效只投影 null。feature 原始 JSON byte 限額與前端投影值的限額分開，parse／數字表示可能改變 JSON 拼法，前端不宣稱重證原 byte budget。

chip 八數值為 foreign_buy／trust_buy／dealer_buy／margin_balance／margin_change／short_balance／borrowed_sell／day_trade_ratio，有限數值或 null 逐欄呈現。原五個 consumed core（foreign_buy、trust_buy、dealer_buy、margin_balance、margin_change）與身份／日期仍支援原 5 日完整性 gate；其餘 optional 數值／metadata 的 invalid 不另加 blanket actionability gate。原 conditional、完整 observation、held quantity／stop 與必要 source 優先不改；不把 feature／chip known 自動當研究成立或新 Plan。

### 17.4 前端獨立區塊與有限相容

StockPage／StockResearchPanel 共用純 guard 核 shape、builtin-string state、field metadata、身份、數量與順序一致性。malformed feature 只拒用 feature／MA，malformed chip envelope 只拒用 chips；結構合法的 chip 列保留各欄有限數值與 missing／invalid null，並顯示自己區塊的 gap，健康 bars／研究不被整體抹除。前端 normalized／projected JSON 採 **512 KiB** 呈現限額，另核 **depth 32／nodes 16,384** 的有限樹與合法 Unicode；原 JSON 解析後的合法數字可能展開成較長拼法，這項上限與後端原 raw **65,536 bytes** 分開，不證原件或來源。合法數字展開與 giant string／key／object／array、null metadata／非字串 state 等 pure 邊界已由必要 helper 核對，必要 actual HTTP／App 支持已有限接受，不外推其他路徑。全部新讀值欄位 undefined 的舊 API 僅有有限數值相容；null／矛盾的新 envelope 不當舊回應。shared `ChipSnapshot` type 保持原樣。

可重建入口及零落盤限制見[開發入口](development-baseline/README.md#m3-p6e-個股獨立特徵籌碼讀回的零落盤驗證入口)；文案見 [UI 規格](UI_COPY_SPEC.md#m3-p6e-獨立特徵籌碼區塊文案有限接受)。

### 17.5 能力邊界

SQL None 的 features_json 只核 pure projection，不聲稱存進 NOT NULL 欄；SQLite affinity 已數值化的 numeric string／bool 只能核現在 storage，不能還原遺失輸入意圖。

其他不證項目同 §16.5；memory fixture 不降低原件或磁碟條件。

## 18. M1-W2：同截止法人窗口與原件追溯

本節是 W 系列同截止法人窗口 API／UI 的共同基礎（§18.1 取得與記憶體、§18.2 精確窗口與來源展開），W3 起各版本沿用；現行版本見 [§24](#24-m1-w8八截止法人窗口與原件追溯)。

支持 TPEx 3105／6488、唯一共用 `as_of=2026-10-02`；總覽 `stock-overview/w2-v1`、法人 `institutional-windows/w2-v1`。來源、policy pins、22日曆／20日原件、單位／缺日與計算版本沿用[來源 §13](SOURCE_REGISTRY.md#13-m1-w1tpex-多日法人與完整有界交易日)，不放寬 P2b 單日或其他來源。

### 18.1 明示取得、共用截止與記憶體

Server 必須 exact `STOCK_TPEX_INSTITUTIONAL_WINDOW_MEMORY_CAPTURE=1`。`POST /api/stocks/{exchange}/{symbol}/institutional-windows/capture?as_of=2026-10-02` 先核標的存在，再用共用截止核支持範圍；首次核定操作才調 W1 loader，最多22 GET。後續兩股 POST／detail／overview GET 重驗同一批 process-memory 原件，普通 GET／import 零外網、不寫 DB／檔案。非阻塞鎖拒並行取得；成功或失敗後不 retry、refresh 或較早 fallback。重啟後須另作新觀測，不稱保存或離線重播。

未啟用／無效設定、未取得、busy、來源／日曆失敗及範圍外各有 reason。其他市場／標的／截止不返回舊窗口數值；缺共用截止不補資料日。10/03 截止無值／無載入按鈕，恢復10/02讀 held cache；取得時間不能替代資料 cutoff，也不能推論歷史當時可得。

### 18.2 精確窗口與來源展開

`overview.institutional.windows['5'/'20']` 各有 status、values、from／to、required／valid／missing／invalid dates、原因及 daily evidence；detail 與獨立 overview 同截止／版本。外資（不含外資自營商）／投信／自營商分列，canonical 整數字串以 BigInt 加千分位，單位股、不轉 Number。只有單位／編碼、支持 cutoff、日曆及該窗 available、三值合法才顯數值；缺日按窗顯示資料不足，不補零、縮窗或重加外資自營商。

畫面顯示所需／已驗／缺日、TPEx 顯名、兩個政府資料集及 OGL1 連結。展開可查日曆規則／休市公告、版本／policy、逐日原列序與 buy／sell／net、exact CSV、body／receipt SHA、UTC取得時間。published／first available／revision unknown、PIT unsupported、不判研究條件成立；P2b 單日區塊仍獨立。

## 24. M1-W8：八截止法人窗口與原件追溯

支持TPEx3105／6488，共用 `as_of=2026-09-21／09-22／09-23／09-24／09-29／09-30／10-01／10-02`；總覽 `stock-overview/w8-v1`、法人 `institutional-windows/w8-v1`、worker `tpex-institutional-window/w8-v1`。來源／policy／27日曆與唯一96 net集中[來源 §19](SOURCE_REGISTRY.md#19-m1-w8八截止法人來源與完整有界日曆)；§18 為共同基礎；W3～W7 已歸檔，不作本版設定。

### 24.1 同截止、一次取得及原列追溯

沿server opt-in `STOCK_TPEX_INSTITUTIONAL_WINDOW_MEMORY_CAPTURE=1`與既有capture POST，先核標的存在／supported cutoff。First actual POST3105／9/21新取3month＋27daily，後續POST／detail／overview GET重驗同held30 process-memory原件；普通GET／import零外網，不寫DB／檔案。鎖／一次嘗試、拒retry／refresh／較早fallback與重啟新觀測界線不變。

原生「套用截止」後兩窗同cutoff，canonical整數字串以BigInt千分位／股呈現，5／20日三類net及required／valid／missing／invalid分列。來源詳情沿署名／資料集／授權、exact URL／daily ordinal／buy／sell／net、雙SHA／UTC及policy／source／calendar／calculation版本。月原件全返回已驗、有界採用與界線前未採分開，8月21／5／16；daily只列≤cutoff required evidence。發布／first availability／revision unknown、PIT unsupported；突破／回踩固定保守，未新增trend／研究條件或Signal接線，其他來源區塊獨立。

### 24.2 具名可信原生操作與有限驗收

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §24.2。

### 24.3 仍未支持的界線

缺／壞 8/25 按窗口失效只有必要的 synthetic API／SSR 驗證，不稱 actual missing native。Catalog／price seed 僅為 synthetic memory，不證真行情或正式 DB。Physical canvas、原生橫向手勢、Vite／production build、pending 導航 race、legacy／ZIP／old live／完整 backend 不在 W8 已證範圍。範圍外日期／標的／TWSE、修訂／PIT、trend／研究條件／Signal、raw 保存／跨程序讀回及完整 M1 不在本版範圍。

## 25. M1-PRICE-1：上櫃兩股單日價量閉環（有限接受）

來源／用途、固定policy／body pins、兩股唯一金融值及production capture權威見[來源 §20](SOURCE_REGISTRY.md#20-m1-price-1tpex-兩股單日價格來源與准入)。原§9／15的DB行情／來源gate保留；memory價格不替它們取得准入或保存驗收。

### 25.1 具名操作與同股／同截止契約

使用者明示研究截止2026-10-05後，在「櫃買官方單日行情」按「載入 10/5 官方行情」。`POST /stocks/{exchange}/{symbol}/prices/capture?as_of=2026-10-05` 使用空object body；每程序僅首次合法明示POST可有界取得1份官方CSV，從3105切到6488用同process cache。普通GET／重複POST／切股不增加外網，失敗cache不自動retry，import不能自動取得。精確啟用值及外部policy pins見[開發入口](development-baseline/README.md#m1-price-1-單日價量的記憶體驗證入口)。

`price_memory` 的 `stock-price-memory/m1-v1` 與原DB路徑雙軌；source／版本／完整性、同symbol／asof有效才接headline、單日OHLC／成交量圖與新價格面板，三處使用同一股／日。預設asof不為新價格前移；明選2026-10-02或「最新資料」返回既有default10/02時，10/05 memory不可滲入，漲跌仍待核實。沒有其他cutoff歷史取得或較早／未來fallback。

Memory typed契約明示TWD，正面wrapper身分檢核依來源§20.1；其他unknown市場不外推。價格為元／股、成交額為TWD元，成交量依[單位契約](UI_COPY_SPEC.md#103-張零股)顯示精確張；source details保留canonical股及金融原字串。quote-date、request開始／capture UTC、source／policy／body／receipt SHA與署名可追溯；publication／first available／revision未知，非PIT。bar `id`／`raw_payload_id`／`ingestion_run_id` 為null，不偽裝DB記錄。

### 25.2 能力邊界

本server catalogue及10/02是synthetic，只有official10/05單日價格為actual；只存memory，重啟須重載。index11391不能作個股價格。不提供：正式資料目錄、DB保存／跨程序、MA20／MA60／trend、研究條件／Signal／Plan或PIT。

## 26. M2-FOCUS-LOTS-1：精確成交張數關注與同截止往返（有限接受）

本節定義成交張數條件（`min_lots`）與 `price-lot-focus/m2-v1` 的起點契約；只採[來源 §20](SOURCE_REGISTRY.md#20-m1-price-1tpex-兩股單日價格來源與准入)已准入的單日價格，沒有新增市場、日期或可信排名。現行 consumer 版本與 scope 依 [§29](#29-m2-focus-day-range-1本日振幅與五條件往返)、[§34](#34-m2-focus-stock-scope-5七股關注與同截止往返)；§12／13官方事件與§25 M1歷史界線保留。

### 26.1 明選條件、精確比較與來源完整性

`GET /api/focus/price-lots?as_of=YYYY-MM-DD&min_lots=...` 與明示 `POST /api/focus/price-lots/capture` 使用相同 query，client POST body為空object。兩參數必填；缺值、無效日期或非法門檻回HTTP422，不取得來源。`min_lots` 必須是最長20字元的非負ASCII十進位字串，整數部為 `0` 或無前導零的正整數，小數可有1～3位；不接受正負號、逗號、空白、科學記號、尾點或第四位小數。換算後canonical股數不得超過 `9223372036854775807`，即 `9,223,372,036,854,775.807` 張；`0`、`0.001`與`20000.000`可表達精確門檻。

回應保留原 `min_lots` 字串，另給canonical `min_shares`；後端以精確整數股比較，前端以canonical股字串長度與字典序重算，不經Number或小數除法。成交量日常主值為精確張，原股留稽核；價格／成本仍元／股，既有庫存的整數 `unit + quantity` POST不改，單位規則見[UI §10.3](UI_COPY_SPEC.md#103-張零股)。

來源範圍須恰為兩個已核exact名稱的TW／TPEx普通stock、無ETF分類，typed TWD gate仍依§20.1。`reads` 按3105／6488給兩股memory讀值；available前須各有同股／同cutoff的完整價格、shares單位、canonical成交股數、可追溯provenance，而且兩股provenance一致。前端再驗scope、版本、全部reads、候選集合、數量與固定detail URL；即使沒有候選仍驗兩股reads。不合格不拿legacy、其他日期、較早值或原件片段補數。

每股最多一張卡，依代碼升序；item帶 `volume_exact`、精確 `volume_lots`、原門檻／canonical股門檻、`reason=volume_at_least_min_lots`、來源日／版本與固定個股URL。主理由為成交量達門檻，不推論資金流向、前日漲跌或研究結論。

### 26.2 真零、來源不足與取得生命週期

只有 `status=available`、兩股完整來源與候選重算均合格時，`count` 才是候選數；未達門檻的合法結果為 `count=0`／`items=[]`。未載入、有效但不支持的日期、身分或來源拒用為 `status=unavailable`／`count=null`／`items=[]`，另給reasons，不把空清單當真零。`can_capture` 只在來源可合法首次取得時開放；不支持2026-10-02，也不以10/05補該日。

普通GET與import不送外網；首次合法明示capture仍沿同一TpexPriceStore／固定policy及body pins，每程序最多1個bounded GET，重複POST、切股、讀取與門檻變更共用cache，失敗不自動retry。表單draft只在「套用條件」提交後改URL／query；查詢與capture結果依原 `as_of/min_lots` key保存，無舊結果placeholder或window-focus來源refresh。

### 26.3 固定個股路徑與返回原字串

detail 固定 `/stocks/TPEx/{symbol}`，query 只有 `as_of`、`from=price-lots`、`focus_as_of`、`focus_min_lots`，進入同 cutoff M1。返回只接受各版本列出的白名單參數：必要參數各恰一次、可選參數最多一次、沒有未知參數（含 `next`），兩日期有效，原門檻／方向／金額／百分比合法，且研究 `as_of` 須等於原 `focus_as_of`（m2-v2 起）；通過後才由 URLSearchParams 固定組成本地 `/?as_of=原focus_as_of&min_lots=原focus_min_lots#price-lot-focus-title`（後續版本依各節追加參數），不接受自由 return URL。個股內更改 cutoff 仍保存原關注條件，返回保留 `20000.000` 等原字串尾零；非法、重複或不一致參數不猜原條件，回既有本地 `/stocks` 個股入口，不導向外部。原官方事件返回仍用其既有契約。

## 27. M2-FOCUS-DAY-MOVE-1：單日方向關注與完整條件往返（有限接受）

現行consumer為 `price-lot-focus/m2-v2`；§26的張數條件仍有效，現行方向與返回契約依本節。§20.1固定policy／pins與§20.2金融表保持。單日操作不放行MA／trend或研究判定。

### 27.1 三個條件與精確單日比較

`GET /api/focus/price-lots` 與明示 `POST /api/focus/price-lots/capture` 沿既有 `as_of/min_lots`，新增 `day_move=all|up|down|flat`，省略時為all；對應「全部／收高於開／收低於開／平收」，比較當日收盤與當日開盤，不是前收盤漲跌。日期／門檻仍必填；三條件任一重複、日期／門檻／方向非法，在capture前HTTP422。Client POST body仍空object。門檻20字元／最多三位小數／int64 canonical股與原尾零依§26.1、[UI §10.3](UI_COPY_SPEC.md#103-張零股)，不改穩定換算。

O/C取每股 `source_fields`「開盤／收盤」原字串，各最長64字元，只接受無正負號、前導零、空白、科學記號或尾點的正ASCII十進位價格；可有小數，合法值必須大於0。後端以Decimal比較，前端以整數部分長度／字典序與補齊小數字串獨立重算，不經JS Number。收大於開為up、收小於開為down、同值為flat；缺失／無效／零價格不猜方向。

候選同時達精確股門檻及所選方向；all只略過方向篩選，仍核每股O/C並顯示實際up／down／flat。每股一張卡、依code升序，item保留 `volume_exact/volume_lots/min_lots/min_shares`，新增實際 `day_move/open_exact/close_exact`；固定兩理由 `volume_at_least_min_lots` 加 `close_above_open|close_below_open|close_equal_open`。前端重算兩股reads、全部候選、原值／理由與固定URL，不只驗顯示卡片。

### 27.2 來源完整性、真零與cache

恰為已核兩股普通stock／TPEx／TWD、同股／同截止完整原件及一致provenance後才可available。任何O/C缺失／invalid為 `unavailable/count=null/items=[]`，理由 `price_focus_direction_unavailable`；未載入、來源拒用及不支持10/02依既有原因拒用。即使count0，也先驗兩股完整reads及實際方向；只有available0才是此範圍真零，不以空清單補0。

首次取得與cache沿來源§20.1：每程序最多1 bounded GET、3MiB／30秒／redirect0／retry0；普通GET／import零外網、失敗不自動retry。本輪actual在同程序已驗held Store供真router／UI，source1／runner0，後續focus／stock POST只再用cache。Draft在「套用條件」submit後才改URL，query／capture結果key包含 `as_of/min_lots/day_move`，不混方向，不以舊placeholder或window-focus刷新來源。

### 27.3 同截止研究與安全返回

固定detail為 `/stocks/TPEx/{symbol}`，query是 `as_of/from=price-lots/focus_as_of/focus_min_lots/focus_day_move`，進同cutoff M1。返回白名單只有上述五key，前四各恰一次，`focus_day_move`最多一次且合法；legacy省略方向按all。日期有效且 `as_of` 必須等於原 `focus_as_of`，原門檻合法，才由URLSearchParams固定組成 `/?as_of=原日期&min_lots=原字串&day_move=原方向#price-lot-focus-title`。

拒收與本地 fallback 規則見 §26.3；今日頁重複條件不啟 query，原官方事件返回契約保持。

## 28. M2-FOCUS-TURNOVER-1：精確成交金額與四條件往返（有限接受）

現行consumer為 `price-lot-focus/m2-v3`；§26／27各保留m2-v1／v2歷史，穩定張換算及O/C比較不改。固定policy／pins與唯一金融表依§20.1／20.2。M1的20／21真個股歷史close／日曆、strategy inputs／time／execution gate仍缺，不由單日操作放行研究。

### 28.1 四條件、精確成交額與三理由

沿 `GET /api/focus/price-lots` 及明示 `POST /api/focus/price-lots/capture` 的 `as_of/min_lots/day_move`，新增 `min_turnover`，省略為字串 `0`；client POST body仍空object。門檻必須是canonical非負ASCII整數字串，最長19字元／上限 `9223372036854775807`，單位TWD元。明示空值、前導零、正負號、小數、科學記號、空白、逗號、Unicode數字與溢位拒收。四條件重複／非法或API未知query key均於catalogue查詢及capture前HTTP422；首頁非法／重複條件不發focus request、讀取／capture按鈕disabled。Shared `q` 及官方事件返回保持既有用途。

回應與item保留原 `min_turnover`，item帶 `turnover_exact`；元值以canonical int64字串／整數比較，不經JS Number。先驗兩股完整reads、同股／同截止、TPEx普通stock／TWD、完整一致provenance及O/C；再驗每股 `turnover_exact` 為合法精確字串、等於source_fields「成交金額」，`turnover_status=available` 且 `turnover_reason` 明示null。缺值、壞字串、狀態未知／unavailable、缺reason或原值衝突，為 `price_focus_turnover_unavailable`／count=null／items=[]，不能補0或跳過不合格股。

原件明確0且完整gate合格可以available；本輪此來源兩股成交額均為正，來源零只由synthetic邊界驗證。完整reads須在filter前驗，即使最後零候選仍核兩股；只有available／count0才是此範圍真零。候選須同時達股門檻、成交額門檻與所選方向；all不略過實際O/C驗證。每股一張卡、code升序，固定三理由 `volume_at_least_min_lots`、`turnover_at_least_min_turnover`、實際 `close_above_open|close_below_open|close_equal_open`。前端獨立重算全部reads／候選／理由／URL，不只驗顯示卡片。

### 28.2 同截止、完整原條件與安全返回

detail固定 `/stocks/TPEx/{symbol}`，query為 `as_of/from=price-lots/focus_as_of/focus_min_lots/focus_day_move/focus_min_turnover`，進同cutoff M1。返回白名單僅這六key；前四各恰一次，方向／金額各最多一次，legacy省略分別為all／0。日期有效且研究as_of等於原focus_as_of、兩門檻及方向合法後，URLSearchParams固定組成 `/?as_of=原日期&min_lots=原字串&day_move=原方向&min_turnover=原金額#price-lot-focus-title`。

拒收與本地 fallback 規則見 §26.3；首頁 shared q 相容與原官方事件往返不改。Draft 在「套用條件」submit 後改 URL；query／capture 結果 key 包含四條件，無舊 placeholder／window-focus 來源 refresh。普通 GET／條件變更與重複 POST 共用同程序 Store，固定每程序 1 GET／3MiB／30 秒／redirect 0／retry 0，失敗不自動 retry。

## 29. M2-FOCUS-DAY-RANGE-1：本日振幅與五條件往返

Consumer `price-lot-focus/m2-v4`；§26～28保留m2-v1／v2／v3當時範圍。新來源與金融值由[來源 §20.7](SOURCE_REGISTRY.md#207-m2-focus-day-range-1新日期來源准入與本日振幅-consumer)管理；10/05固定tuple與§20.1不覆寫。只有TPEx3105穩懋／6488環球晶、stock／TWD及明確核准10/05、10/06兩日期，非任意新日期或自動最新。單日資料不解除M1的20／21真歷史close／日曆、strategy inputs／time／execution gate。

### 29.1 原百分比、精確比較與完整來源gate

沿 `GET /api/focus/price-lots` 與明示 `POST /api/focus/price-lots/capture`，五條件為 `as_of/min_lots/day_move/min_turnover/min_range_pct`，POST body仍空object。新百分比門檻省略採原字串 `0`；明示空值非法。只接受非負ASCII十進位原字串，整數部分為0或非零開頭、最多三位小數、總長≤20字元，保留尾零；不接受符號、前導零、科學記號、空白、逗號、Unicode數字或超限。千分之一百分點scaled int64≤`9223372036854775807`，故原門檻最高`9223372036854775.807`%。API未知key、重複或非法五條件均在catalogue／capture前HTTP422；首頁非法不查focus，讀取／capture停用。原張／股及元／股口徑不改。

本日振幅為 `100×(H−L)/O`。O/H/L取原件「開盤／最高／最低」十進位字串，各≤64字元、非負標準形狀並實際正值，對齊共同小數位後轉Python int／JS BigInt；須`H≥O≥L>0`。候選比較精確使用 `100000×(H−L)≥minimum_scaled×O`，不先除法、轉JS Number或四捨五入。不要求振幅為正：合法H=L可得0；門檻0仍須完整O/H/L，missing、壞形狀或矛盾不得補0。

先核兩股完整reads、同股／同截止、source tuple／provenance一致、canonical成交股數、原O/C、TWD成交額/status/reason/raw一致及O/H/L，才filter。振幅不合格為`price_focus_range_unavailable`／count=null／items=[]，不跳過壞股；all與最後零候選也不略過完整gate。只有available／count0是此範圍真零。回應與item保留原min_range_pct，item新增high_exact／low_exact；原open_exact／close_exact仍取原值。

每股一張卡、code升序，同時滿足張門檻、成交額、方向與振幅。固定四理由順序為`volume_at_least_min_lots`、`turnover_at_least_min_turnover`、實際`close_above_open|close_below_open|close_equal_open`、`range_at_least_min_range_pct`。前端獨立重驗全部reads、精確候選／理由／欄位／URL，並非只驗顯示卡。振幅百分比可half-up至三位小數、標「約」，僅供閱讀；候選與邊界一律精確比較。

### 29.2 同截止研究、五條件返回與兩日期隔離

固定detail `/stocks/TPEx/{symbol}`，query白名單為`as_of/from/focus_as_of/focus_min_lots/focus_day_move/focus_min_turnover/focus_min_range_pct`；前四各恰一次，後三各最多一次，legacy省略分別all／0／0。研究as_of須等於focus_as_of；門檻與方向均合法後，返回固定本地 `/?as_of=原日期&min_lots=原字串&day_move=原方向&min_turnover=原金額&min_range_pct=原百分比#price-lot-focus-title`。日期、張與百分比尾零、方向、金額完整保留；拒收與本地 fallback 規則見 §26.3。Shared q與原官方事件往返保持。

Draft經「套用條件」submit後才改URL；query／capture key含全部五條件，無placeholder／window-focus來源refresh。每程序只能採一份所選日期原件；兩日期各自需要匹配外部policy pins與immutable tuple，10/06不得給10/05、default或explicit10/02。新服務用10/06 pins時，10/05為external pins mismatch，不能聲稱另持有歷史body。Ordinary GET、切條件、切股與重複POST共用Store、不新增source GET；失敗不retry。新來源由pure builder准入，policy與builder版本見§20.7；不將cached UI操作說成fresh GET。

## 34. M2-FOCUS-STOCK-SCOPE-5：七股關注與同截止往返

default 10/06 的七股 scope（普通TPEx，新增6510精測）；3～6 股的先前版本（原 §30～§33）使用同一 gate 與五條件，各版 policy 見[來源 §29.1](SOURCE_REGISTRY.md#291-1006-價格-policy-tuple-版本表)。Scope code順3105／3293／5274／5347／6488／6510／8069、source-date2026-10-06；focus `price-lot-focus/m2-v9`、projection `stock-price-memory/m2-stock-scope-v5`。身份／policy／金融原件權威見[來源 §29](SOURCE_REGISTRY.md#29-m2-focus-stock-scope-5七股來源准入)。

### 34.1 完整gate

沿§29.1精確張／canonical股、原O/C、int64 TWD元及振幅公式。Default10/06採`.5`七股，explicit舊六股及更早immutable tuples／舊兩股producer相容保持；公開條件仍`as_of/min_lots/day_move/min_turnover/min_range_pct`，不增加第六條。

全部required reads／逐股身份及金融／同cutoff／tuple／provenance先gate後filter；任一missing／invalid／conflict為unavailable、count=null、items=[]，不跳壞股或縮scope。完整七股available/count0才是真零；四理由固定順序去重、一股一卡／code升序，frontend獨立重驗raw與safe local五條件URL。

Unknown或malformed scope於StockOverview安全拒用，避免未驗scope被join或呈現；raw source詳情可回指body／receipt／policy與各股18個原欄。

## 35. M1-PRICE-SAVE-1：私人單日保存與跨程序操作

原件、dual pins、三檔schema及時間權威見[來源 §30](SOURCE_REGISTRY.md#30-m1-price-save-1私人單日保存與跨程序讀回)；原`.5` memory及§34 focus不自動切換storage來源。

### 35.1 明示保存、讀回與同股同截止

`POST /api/stocks/{exchange}/{symbol}/prices/save?as_of=2026-10-06`只保存現有合法memory capture，不觸發金融GET；無capture拒用。`GET /api/stocks/{exchange}/{symbol}/prices/saved?as_of=2026-10-06`只重開核定私人bundle；須exact supported TPEx identity／scope／date與兩種policy pins。缺cutoff、10/05、10/07皆unavailable，不能用較早或較晚資料補值。

Saved payload `stock-price-saved/m1-v1`以`origin=private_local`區分，`latest`／單bar接同股同日headline／表／圖；`provenance`保留原capture的process_memory事實及UTC，`storage_provenance`另存storage receipt／SHA／saved_at。Source raw欄位、canonical股、精確張與TWD元／股維持；DB IDs null，published／first_available／revision unknown／historical_pit unsupported。Frontend先重驗saved schema／scope／units／raw金融值／same symbol-cutoff／兩層provenance與hash，再採數值。

使用者分別按「保存此日行情」及「讀取已保存行情」；切stock／date隔離request token及舊saved值，日期恢復仍須explicit read。讀回不hydrate memory／不auto-fetch；NEW saved-only reader empty Store／禁止capture，讀與空memory save均零金融GET。原default截止／legacy memory及DB讀值gate保持；具名文案由[UI §10.2](UI_COPY_SPEC.md#102-個股詳情的第一屏)管理。

## 36. M1-CHIPS-CUTOFF-1006-1：同截止法人窗口與完整日曆

本節定義 3105 穩懋／6488 環球晶、explicit 2026-10-06 的真 5／20 交易日法人窗口契約。總覽 `stock-overview/chips-1006-v1`、法人 `institutional-windows/chips-1006-v1`／read `institutional-windows-read/chips-1006-v1`。Exact 來源／policy pins、完整 24 日曆與唯一 12 canonical net 由[來源 §31](SOURCE_REGISTRY.md#31-m1-chips-cutoff-1006-1同1006法人窗口與完整有界日曆)管理；§24 W8 保持原 10/02 截止／版本，其他區塊未借法人 grant 取得准入。

### 36.1 顯式截止、同批讀取與失敗清值

沿 `POST /stocks/{exchange}/{symbol}/institutional-windows/capture?as_of=2026-10-06`；detail／overview帶同explicit日期。只有10/06選新獨立Store及pins，省略日期／resolved default／舊cutoff仍走W8；不自動把default提升至10/06。最初「載入5／20日法人窗口」合法明示BUTTON取2月＋20daily一次，後續「讀取本次法人窗口」／切兩股／普通GET重驗held22，source0；failed attempt不另取得或重啟。

畫面先核expected exchange／symbol／explicit cutoff、schema／worker／policy／body／原canonical receipt、完整24calendar與兩窗required dates、原25欄／金融關係／BigInt sum，再顯示張值與來源。5日9/30～10/6、20日9/7～10/6；合法0保留、missing／invalid不補0、不縮窗或fallback。日常張值使用[§10.3](UI_COPY_SPEC.md#103-張零股)穩定公式，最多三位小數去尾零；外資簡稱仍保留「不含外資自營商」。

Outer「查看法人窗口的每日數值、交易日與來源版本」列完整24日六欄日曆，與20法人daily分開；閉日9/25、9/28明示依官方公告。每日日子表提供全25原字串、row ordinal、source／policy／calendar／calculation版本、body／receipt SHA及UTC。觀測非publication／revision／first availability，PIT未支援，不推論trend／研究條件成立。

同token讀取network失敗或回應核對失敗時，立即隱藏net數值、窗口表及verified raw／details，只留可讀原因與同批讀取button；不能因React query保留舊cache而繼續顯示舊數值。返回有效10/06且成功核對後才能恢復；source重試權不由讀button取得。
能力邊界：缺／壞來源按窗失效、污染／busy／pins 等邊界只以必要 synthetic 驗證，actual missing-source native 未跑；未驗全市場／TWSE、普通股 20／21 close、完整 strategy／time／execution、PIT、trend／Signal／Plan、法人磁碟保存／跨程序或完整 M1／M2／M3。

### 36.2 具名actual API與可信native

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §36.2。

### 36.3 完成、清理與未驗

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §36.3。

## 37. M1-SAVED-PRICE-FOCUS-1006-1：保存來源關注與同截止往返

本節定義保存七股／2026-10-06 的四條件篩選→同股同截止 detail→五原條件返回契約。`price-saved-focus/m1-v1` 獨立於 memory `price-lot-focus/m2-v9`；exact consumer／storage／capture pins、full raw 與金融真值只由[來源 §32](SOURCE_REGISTRY.md#32-m1-saved-price-focus-1006-1保存來源的七股關注准入)管理，原 §34／§35／§36 不自動取得新准入。

### 37.1 明示只讀、全七股gate與exact條件

`GET /api/focus/price-saved`只接受 `as_of/min_lots/day_move/min_turnover/min_range_pct` 五條件，前兩required；duplicate／unknown／invalid query回422。合法但unsupported10/05、10/07為unavailable／count=null／items=[]且不讀檔。Supported僅explicit10/06、來源§32七identities；完整原件／全七股required reads及同tuple／日期／provenance先gate後filter。四項條件AND、inclusive精確比較、code升序、一股一卡；available真零不等於來源不足。精確張／int64 TWD／C對O方向／振幅公式與原漲跌欄區別見來源§32.2。

Entry、套用條件、切換及返回都不auto-read；使用者按「讀取已保存行情」才核目前條件。同一stock／date／source-mode／條件組有generation token；busy、回應失敗及切換隔離舊值，late response不回填其他狀態。頁面為 `/focus/price-saved`，詳情帶 `source_mode=private_saved`、`from=price-saved-focus` 與safe local返回條件；來源模式不新增第六個公開filter。

### 37.2 Saved detail、來源追溯與失敗隔離

新consumer detail為 `GET /api/stocks/{exchange}/{symbol}/prices/saved-focus?as_of=2026-10-06`；old `/prices/saved` 在guarded mode外保持。NEW consumer runner只讀且全部POST禁止，guarded mode的old saved入口405，避免繞過shared read budget。切同股／日期／source-mode先清saved值，合法返回五條件才啟用新read；不save、capture、hydrate memory或採old memory／DB價格fallback。

Frontend先重驗新consumer及原saved schema／兩層provenance／hash／scope／cutoff／raw金融值，再接headline、成交張、表與單日chart；原列drawer保留18 source fields、row ordinal與capture/storage receipt。返回留 `as_of/min_lots/day_move/min_turnover/min_range_pct` 的**五個原字串**，含 `0.000`／`2.880` 尾零；不正規化成另一組輸入。原capture process_memory及現在private_local並列，擷取／保存UTC不是發布時間，MA／trend／研究條件仍待補。

Actual focus same-token HTTP502立即清全部cards、count、來源blocks及raw；detail same-token HTTP502清headline、成交張、table、原列drawer及canvas，保留read button與ONE「讀取原因」diagnostic details。Diagnostic details不是raw drawer，不以其存在誤報舊原件仍顯示。缺／壞來源不用0、其他日期或memory／DB補值；恢復後仍須明示讀取。具名文案由[UI §10.6](UI_COPY_SPEC.md#106-保存來源關注與同截止返回)管理。
能力邊界：actual missing-file UI 未跑，synthetic integrity／schema 與 HTTP 502 均不改稱缺檔驗收；未驗其他平台、全市場／PIT、普通 20／21 close／trend／strategy／time／execution 或完整 M1／M2／M3。

### 37.3 Actual API、精確邊界與可信native

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §37.3。

### 37.4 完成與未驗邊界

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §37.4。

## 38. M1-SAVED-PRICE-CHIPS-INTEGRATION-1006-1：共同入口與同截止往返

本節定義 saved-focus→3105／6488 同 explicit 10/06 的 saved OHLC＋真 5／20 net→追溯→原五條件返回的共同 guarded API／preview 契約；source-use／五獨立 policies、原件／金融與 caps 由[來源 §33](SOURCE_REGISTRY.md#33-m1-saved-price-chips-integration-1006-1保存行情與法人窗口共同入口)管理。原 §34～37 各自有限能力與 pins 保持，其他五 saved 股只有既有 price 能力。

### 38.1 明示讀取與同一context

Joint preview以 `VITE_SAVED_PRICE_CHIPS_INTEGRATION='m1-v1'` 啟用；條件、URL與saved-focus detail須同context，3105／6488才可首次載入法人。Saved入口／套用／切股／back不自動private read／capture；先明示讀保存行情，再trusted首次「載入5／20日法人窗口」。成功後同一SINGLE NEW API提供saved headline／OHLC／成交張與§31完整日曆／20daily真5／20交易日12 net；切兩股不重啟、不取得live price／hydrate old memory，不擴大cutoff。

當current private／chips／stock read／refetch或provenance核對失敗，兩區數值、raw與chart一併清除，留下read buttons及ONE原因。恢復須same current context／generation內成功的明示NEW saved snapshot和明示held chips read；成功一邊或舊generation成功不足，held read不取得外網，failed capture不自動重試。
能力邊界：memory invalid／recovery／provenance 測試不當 actual missing-file UI；不外推其他平台、全市場／PIT 或完整 M1／M2／M3。

### 38.2 Actual具名操作

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §38.2。

### 38.3 驗收與未完成

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §38.3。

## 39. M1-SAVED-PRICE-CHIPS-FOCUS-1006-1：八條件入口與不可用驗收邊界

本節定義八條件 guarded 入口契約；本版只接受 unavailable 操作，法人 matching、verified zero、joint detail 與八 RAW back 的正向驗收由 §41 接續。來源與新 policy／schema、signed 精確比較、scope／quota 及 calendar 拒用由[來源 §34](SOURCE_REGISTRY.md#34-m1-saved-price-chips-focus-1006-1保存行情與法人條件關注准入及日曆缺口)管理，不以 fixture 或前輪 joint 成功代本輪正向操作。

### 39.1 已實作操作契約

新頁 `/saved-price-chips-focus`僅 `VITE_SAVED_PRICE_CHIPS_FOCUS='m1-v1'` 啟用，獨立於既有saved-focus／joint入口。八欄為原 `as_of/min_lots/day_move/min_turnover/min_range_pct` ＋ `investor/horizon/min_net_lots`；僅3105／6488的selected investor／true5或20日net與四price條件同時成立才列卡。全七price仍須完整核對，其餘五股不屬joint scope。

兩個來源按鈕承接三次明示動作：①「讀取保存來源並篩選」核NEW private snapshot；②「首次取得法人來源」啟動一次新capture；③再按「讀取保存來源並篩選」核NEW private snapshot＋held chips。Entry／apply／切股／back／capture completion不auto-private read，也不在失敗capture後自動重抓。讀成功price而缺chips，候選仍未知；只有七price／兩股chips完整才可宣告真零。

新focus GET要求八keys各一次／body0、壞query422，unsupported cutoff在I/O前unavailable；路由名稱與source模式不變成第九filter。預定detail context為11keys：`as_of/from=price-saved-chips-focus/source_mode=private_saved`＋`focus_as_of/focus_min_lots/focus_day_move/focus_min_turnover/focus_min_range_pct/focus_investor/focus_horizon/focus_min_net_lots`；只合法同cutoff兩股才可進joint detail，返回必須保留全部八原字串。此detail/back為已實作但未actual驗收的契約。

Current source／snapshot／chips或provenance失敗須同時mask prices／chart／raw與chips nets／calendar／dailyraw；只留明示操作及原因。解除mask需same generation的新private及held chips皆成功，late／舊generation成功不能回填。Preview建置後曾補新flag下attempted失敗detail guard並跑memory checks；沒有重開preview／後續native，actual detail NOT RUN，原joint flag expression保持。

### 39.2 Actual unavailable操作

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §39.2。

### 39.3 驗收邊界

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §39.3。

## 40. M2-FOCUS-STOCK-SCOPE-6：八股四條件與同截止往返

本節定義 explicit 2026-10-07、普通 TPEx 第八股 6223 旺矽的四 price predicates→同 cutoff detail→五 RAW back 契約。八股 code 順 3105／3293／5274／5347／6223／6488／6510／8069；新 focus `price-lot-focus/m2-v10`／projection `stock-price-memory/m2-stock-scope-v6`。身份、授權、新 policy／原件／時間及 finance quota 由[來源 §35](SOURCE_REGISTRY.md#35-m2-focus-stock-scope-6八股與新來源日准入)管理；原 defaults、七股 .5／private 及兩股 chips 不改。

### 40.1 完整gate與actual API

公開條件仍 `as_of/min_lots/day_move/min_turnover/min_range_pct` 五RAW；精確張／O-C方向／int64 TWD元／本日振幅四predicate沿穩定AND與inclusive比較，依code排序，不是ranking。全部八股required reads及cutoff／tuple／provenance先gate後filter；缺失／invalid／conflict回count=null/items=[]，完整available才可判count0。

單日資料只產生單日 K 線，不產生 MA20／MA60；原 18 欄／full SHA／ORIGINAL receipt／provenance 可由明示 disclosure 追溯。能力邊界：停止後 detail 錯誤只有 synthetic SSR；完整 M1／M2／M3、普通股 20／21 close 歷史、trend／strategy／PIT／Signal／Plan／execution 未完成。

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §40.1。

### 40.2 ONE page可信輸入與往返

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §40.2。

### 40.3 Current failure清值與驗收邊界

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §40.3。

## 41. M1-SAVED-PRICE-CHIPS-FOCUS-CALENDAR-1006-2：八條件正向關注與同截止往返

本節定義 2026-10-06 保存七股與 3105／6488 法人的八條件 positive／verified zero／joint detail／八 RAW 返回契約；新 full-month 用途、policy／pins、原件／12 net 與執行 cap 由[來源 §36](SOURCE_REGISTRY.md#36-m1-saved-price-chips-focus-calendar-1006-2全月日曆與八條件來源准入)管理。舊 §39 的 unavailable 批次及原 flag 不改。

### 41.1 新入口與明示來源操作

新頁 `/saved-price-chips-focus-calendar`、`VITE_SAVED_PRICE_CHIPS_FOCUS_CALENDAR='m1-v2'` 與舊joint／focus flag互斥；新GET `/api/focus/price-saved-chips-calendar`要求 `as_of/min_lots/day_move/min_turnover/min_range_pct/investor/horizon/min_net_lots` 全八keys各一次／body0，invalid／duplicate／unknown422。只explicit10/06／joint3105與6488；valid unsupported date在private/source I/O前unavailable/countnull。

三個明示按鈕順序是「讀取保存來源」→「首次取得法人來源」→「核對共同來源並篩選」。第三步核NEW private snapshot＋held chips；entry／apply／切股／back／capture completion均不auto-read。已有held來源時，單按price read仍不能列joint候選，須第三步明示核對。完整whole7＋both gate、signed淨超與AND／含等號沿來源§36，不因高price門檻省略chips。

Detail沿11keys同cutoff context：`as_of/from=price-saved-chips-focus-calendar/source_mode=private_saved`＋八個 `focus_*` 原字串；exchange／symbol／cutoff／pins不合拒用。返回新頁保留全部八RAW及尾零；不能以old route／defaults或另一generation補值。
已有 held 來源時，重複 capture POST 回 409／already_attempted 且不新增 source／private；GET 帶 body 回 422、oversize POST 回 413、old save POST 回 405、price readiness 前的 empty FIRST 回 409。能力邊界：20 日 negative card 的 signed formatter 修正後未經 actual native 重驗；actual missing-private-file UI 未跑；停止後 recovery 只有 synthetic same-generation 驗證。

### 41.2 Actual API與可信操作

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §41.2。

### 41.3 Current failure、修正與驗收邊界

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §41.3。

## 42. M1-SAVED-PRICE-CHIPS-FOCUS-STOCK-SCOPE-7-1006-1：七股八條件與同截止往返

本節定義 saved 七股＋七股法人的 explicit 2026-10-06 八條件關注契約；來源 identity／新 policies／pins／ALL 140 daily／42 net／private cap 由[來源 §37](SOURCE_REGISTRY.md#37-m1-saved-price-chips-focus-stock-scope-7-1006-1七股共同來源准入)單一管理。§41 兩股 calendar 及修正後 negative card 未驗的歷史保持，本節只描述本次新 profile。

### 42.1 新入口、共同來源與返回

新頁 `/saved-price-chips-focus-stock-scope-7`、compile `VITE_SAVED_PRICE_CHIPS_FOCUS_STOCK_SCOPE_7='m1-v1'`；new GET `/api/focus/price-saved-chips-stock-scope-7`接受 `as_of/min_lots/day_move/min_turnover/min_range_pct/investor/horizon/min_net_lots` 八required keys各一次、body0；old/calendar flags與route保留獨立且不能補值。Invalid／duplicate／unknown在IO前拒用；valid unsupported日期先unavailable。Signed grammar、int64、inclusive AND、code順與exact價格公式沿來源§32.2／34.1。

明示「讀取保存來源」→「首次取得法人來源」→「核對共同來源並篩選」；entry／apply／切股／capture completion／back不auto-private read。Price-only即使held chips已獨立核實仍不jointready；先fullALL7price＋ALL7chips gate，再篩選，真零也須完整來源。初次saved未讀只清price，held chips可顯示；actual current source failure則清BOTH，不把unknown寫count0。

Detail context沿11keys：`as_of/from=price-saved-chips-focus-stock-scope-7/source_mode=private_saved`及八 `focus_*` 原字串；samecutoff／exchange／symbol／pins／generation不合拒用。Back保留全部八RAW及尾零，不借old route/default；沒有implicit read。顯示provenance欄位與原列，不聲稱整份original receipt JSON直接呈現在UI。
能力邊界：missing-private-file 與停止後 recovery 只有 synthetic 契約驗證；七股 daily raw 追溯不等於每日 net 圖／精確日期表／累計已交付（見 §43）；完整 ROADMAP、普通股 20／21 close／trend／strategy／time／PIT／Plan／execution 未完成。

### 42.2 Actual API與可信七股操作

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §42.2。

### 42.3 Current failure、未跑項與剩餘能力

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §42.3。

## 43. M1-CHIPS-STOCK-SCOPE-7-DAILY-NET-TREND-20-1006-1：七股每日淨超與累計操作

本節定義同 explicit 2026-10-06 的 chips-only 七股每日淨超與累計契約。新 policy／profile／完整來源與 int64 累計契約只由[來源 §38](SOURCE_REGISTRY.md#38-m1-chips-stock-scope-7-daily-net-trend-20-1006-1七股每日法人淨超與窗口累計)管理；§42 saved／chips 及 old calendar 不改。本批不讀保存價格，不以法人每日 net 冒稱股價趨勢或完整 M1。

### 43.1 新入口、明示動作與追溯

Route `/chips-stock-scope-7-daily-net-trend`、compile `VITE_CHIPS_SERIES_STOCK_SCOPE_7=m1-v1`及runner `--chips-series-stock-scope-7-opt-in`；old flags保持獨立。GET `/api/chips/series-stock-scope-7?as_of=2026-10-06`，body0；POST同route的 `/capture?as_of=2026-10-06`，empty JSON object≤4096B。兩端只接受exact as_of key各一次；duplicate／unknown／invalid先拒，合法unsupported cutoff在state／IO前unavailable。Investor／horizon是UI RAW controls，不能寫成GET或capture query keys。

選外資（不含外資自營商）／投信／自營商及5／20日，七股卡→同截止daily detail→back保留as_of／investor／horizon三RAW。明示「首次取得來源（僅一次）」或「明確讀取已持有來源」；套用、切股、法人／窗口及返回不auto-fetch／read。FIRST latch已用不能再取得。Detail列兩SVG每日淨超／窗口累計、精確日期表（股／張）、窗口起迄及累計起點0；SVG比例只供定位，dated operable point與row開原25字串／ordinal／兩SHA／calendar，不用圖形約值作精確數值。
Unsupported 日期（如 10/07）mask 全部數值；改回 10/06 仍 masked，須明示 held READ 成功才恢復同一 generation。FIRST 不能重複，cached capture POST 回 409／already_attempted 且不新增來源。讀取失敗（如 502）mask 全部 SVG／日期表／raw／calendar；back、改法人／窗口及 cards READ 不能 unmask。「已驗證當日淨超為零」只指該日，不代表整窗為零。能力邊界：不解除普通股 20／21 close、股價 trend／strategy／PIT／execution。

### 43.2 Actual正負值、每日零與42窗口

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §43.2。

### 43.3 Unsupported、current failure與未跑項

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §43.3。

### 43.4 退出、進度與使用者暫停

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §43.4。

## 44. M2-OFFICIAL-EVENT-DATE-RANGE-20261008-1：官方事件日期區間與研究往返

`official-event-focus/p3-v1` 定義 effective date 區間、搜尋、真零與同截止往返。只沿[來源 §39.1](SOURCE_REGISTRY.md#391-m2-official-event-date-range-20261008-1實際來源結果)的本次 exact TWT48U 觀測；§12／13 舊版本不改。範圍是觀測 feed 的身分／日期／分類及來源追溯，不是全市場完整事件、普通股身分／行情或 PIT。

### 44.1 請求、順序與計數

`GET /api/focus/official-events`及明示首次`POST /api/focus/official-events/capture`均要求as_of，optional q／from／to。日期須有效ASCII YYYY-MM-DD且非0000年；缺側不限，已提供empty、無效日期、from>to、duplicate／unknown keys在source／catalogue前HTTP422。q沿§13原100 Unicode字元上限、先長度後strip、casefold literal substring。原件完整身分／日期／分類、receipt／pins／hash及觀測截止全部通過後，才逐event按effective date含首末篩選、依標的分組、按來源Code或保留事件Name搜尋、symbol排序及cap100；區間外／搜尋外／cap外壞列不得跳過。

| 回應欄位 | p3-v1語義 |
| --- | --- |
| candidate_count／selected_count | 全合格feed事件列數，range／q不改。 |
| total | 全feed去重標的數，range／q不改。 |
| effective_from／effective_to | canonical邊界或null。 |
| range_event_count | 區間內事件列數，先於q。 |
| range_matched | 區間內去重標的數，先於q。 |
| matched | 區間內再符合q的標的數，先於cap。 |
| displayed／truncated | min(matched,100)／matched>100。 |

每卡只保留該股落在區間內的合格事件；任一保留Name或Code符合q即可留下該卡全部區間內事件，保持原件ordinal。available真零與unavailable／未知分開；不得拿初始零計數當已驗空原件。

### 44.2 提交、同截止返回與共用URL

日期／q draft須明示提交後才查詢；查詢key含as_of／q／from／to，條件切換不沿用舊成功卡片或count。清除日期／搜尋維持研究截止。首頁原張／方向／成交額／振幅四條件仍相容，事件提交保留它們；q／from／to只作共享首頁狀態，不送價量API。

已知catalogue detail固定`/stocks/TWSE/{symbol}`，帶as_of、from=official-events、focus_as_of／focus_q與可選focus_from／focus_to。返回固定首頁official-event-focus-title anchor並恢復原as_of／q／from／to；個股內改as_of不改原清單截止。安全URL／日期／query multiplicity與回應條件驗證仍必須通過，不接受任意return URL。三instrument synthetic catalogue只證routing；來源卡名稱不由catalogue覆寫，無M1入口仍保留事件。
讀取失敗時清除 cards 與 count，不保留成功狀態，也不把失敗當真零。首次取得前全 feed 先驗才 publish；focus／selected 共享首次 attempt 與失敗 seal，首次失敗即耗盡額度，換入口不再取。原件／receipt 只在 RAM，API 結束即釋放，沒有重播／restart／durable 保存。能力邊界：發布／first availability／revision／歷史 PIT、事件價格影響及完整 M1／M2／M3 未驗。

### 44.3 本次真來源及具名接受邊界

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §44.3。

### 44.4 尚缺與後續

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §44.4。

## 45. M2-OFFICIAL-EVENT-KIND-20261008-1/B1：官方事件精確類型與研究往返

`official-event-focus/p4-v1` 定義官方事件精確類型配 effective inclusive 日期／q、原事件 trace、同 cutoff M1 及原五條件安全返回。來源原件及完整 body／ORIGINAL receipt 雙 SHA 由[來源准入](SOURCE_REGISTRY.md) §40 管理，原 §44 與舊 pins 不改。

### 45.1 類型、篩選與精確計數

home／API `event_kind` 為精確 all／ex_dividend／ex_right／ex_right_and_dividend，分別全部／息／權／權息；息不含權息。日期grammar／range／q／kind／duplicate／unknown先於source及catalogue拒422。完整feed與receipt先驗，再逐event range→kind，group及q→code排序→cap100；每卡只保留range＋kind真匹配的原events、日期／分類／ordinal與雙SHA，來源名稱不由synthetic catalogue覆寫。

| 欄位 | 精確語義 |
| --- | --- |
| candidate_count／selected_count／total | 全合格feed事件列數／全合格feed事件列數／全feed去重標的數；range／kind／q不改。 |
| effective_from／effective_to | canonical日期邊界或null；含首末日、缺側不限。 |
| range_event_count／range_matched | range後、kind與q前的事件列數／去重標的數。 |
| event_kind | canonical精確類型。 |
| kind_event_count／kind_matched | range＋kind後、q前的事件列數／去重標的數。 |
| matched／displayed／truncated | 再q後標的數／min(matched,100)／matched>100。 |

任一保留event的Name或Code符合q即可留下該股全部range＋kind事件。available真零可顯示0；unavailable／失敗不得保留成功卡、count或provenance，也不冒稱真零。

### 45.2 明確套用、共用URL與返回

日期／q／event_kind皆draft，明確提交後才查詢；query key與response guard含event_kind，切換條件清舊成功狀態。清類型還原all且保留q／date／as_of，清日期或清q保留kind。四price條件共享首頁URL相容；事件參數不送price API。

已知catalogue detail固定`/stocks/TWSE/{symbol}`，帶as_of、from=official-events、focus_as_of／focus_q／可選focus_from／focus_to及focus_event_kind。返回固定首頁official-event-focus-title anchor，恢復原as_of／q／from／to／event_kind；M1內改as_of不改原清單截止。日期／query multiplicity及safe local URL／回應条件仍須驗，不接受任意return URL。synthetic4（0056ETF／1449／1463／2614）只證routing，無M1入口仍保留事件。
能力邊界：Date 是生效日，不代 published／availability／PIT；不驗普通股身分、全市場、價格、payout 數值、forecast、Plan 或保存，完整 M1／M2／M3 未完成。

### 45.3 本次具名actual接受

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §45.3。

### 45.4 清理、版本與尚缺

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §45.4。

## 46. M1-TWSE-ISSUER-EVENT-PROFILE-20261008-1/B1：真公司原欄位與同截止事件研究

`twse-issuer-event-profile/m1-v1` 定義 1449／1463／2614 真 TWSE 原 Code／全名／簡稱／出表日期／上市日期／行業原碼及 trace，配同 cutoff 官方事件，再回原五條件。公司／事件全原件、dual SHA／ordinal／原始欄位由[來源 §41](SOURCE_REGISTRY.md)管理；原四源／defaults／pins 及 §45 保留，catalogue 只供 routing，不能證普通股或 ETF 身分。

### 46.1 明示取得與原欄位

先明示取得本次官方事件，再以公司「讀取本次公司基本資料」送 `POST /api/stocks/TWSE/{code}/issuer-profile/capture?as_of=2026-10-08`、body `{}`；issuer只支持1449／1463／2614、本cutoff及獨立外部pins。new empty producer各single attempt／FIRST失敗SPENT；同程序其他選定代號／重複POST／GET只用已核cache，不新增外網。missing／較早cutoff／unsupported／未取得皆保留unavailable，不能補0／較早fallback；0056公司不支持，文案不暗示ETF類型。

公司headline用同cutoff受核原簡稱；完整公司全名與原eventName各自保留，Code exact join、eventName須等於issuer全名或簡稱，否則unavailable。raw report／listing／industry及原ordinal／body與receipt SHA可展開trace，report／listing raw＋ISO與event effective Date分列；published／availability／revision未知、nonPIT，不作ordinary／產業名稱／分類品質／行情／capital或payout數值結論。原industry04／20保持字串，不以未准入碼表翻成名稱。
讀取失敗時 headline 改為公司名稱待核對，公司列／事件列與 provenance 清空，不保留舊值；cross-selected 讀取失敗整頁 error、欄位清空。事件清單真零（如 range 內無該類型）不是公司缺證或失敗。能力邊界：未驗普通股／ETF 身分、產業名稱、可信排名、group membership、全市場、價格歷史、資本與 payout 數值、PIT、Plan 或保存。

### 46.2 本次 actual positives 與安全返回

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §46.2。

### 46.3 真失敗清值與執行邊界

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §46.3。

## 47. M1-TWSE-ISSUER-INDUSTRY-TRACE-20261008-1/B1：公司原碼與產業名稱追溯

本節定義公司原碼與產業名稱追溯契約。來源／新 pins 見[來源 §42](SOURCE_REGISTRY.md)，兩碼及日期邊界見[產業 §10](INDUSTRY_CLASSIFICATION.md)，必要驗證見[開發入口](development-baseline/README.md)。

### 47.1 同截止與獨立名稱區塊

`twse-issuer-industry-trace/m1-v1` 是detail `overview.issuer_industry_trace` 新pure-read投影；原 `twse_issuer_profile` v1／六原欄／Code與Name join／capture端點保持，產業不另建capture endpoint或taxonomy GET。先明示取得本次事件，再公司READ沿§46 issuer POST；兩NEW empty producer各attempt1，cachedPOST／其他selected detail GET只用本程序cache。需要 `STOCK_TWSE_INDUSTRY_TRACE=1` 及獨立registry／consumer四external version-digest pins；無pin／缺證unavailable，不升default。

「產業名稱與碼表追溯」顯示1449／1463原04配紡織纖維、2614原20配其他，公司分類生效日明示未知；原Code及名稱分欄、TWSE署名、B.12.00／2023公告／分類規則第2條三official links保持完整。展開「查看產業名稱版本與來源追溯」顯示引用version／metadata observed、issuer／event ordinals、兩sourceversion／body及receipt雙SHA、registry／canonical引用宣告pin與所有日期角色；清楚說明宣告SHA不是PDF／公告／規則原件SHA、沒有原始文件擷取紀錄。

same cutoff須共同核issuer六原欄、exact exchange／code與eventName等於原full_name或short_name、完整原件pins／SHA／觀測日及精確兩碼宣告。missing-cutoff／earlier07／0056unsupported／其他raw碼／特殊或停用碼／名稱或source conflict均保留unavailable，row／provenance為null，不補名稱／零／較早fallback、不用Other吞unknown。原profile classification仍unsupported；新名稱不證ordinary／ETF／membership／完整current分類／排名／行情／PIT。
讀取失敗時 headline 改為「公司名稱待核對」，公司／事件／產業三表與 provenance 清空，舊全名及產業名稱一併消失，不沿用舊 query 值。能力邊界：只三公司兩碼引用及同 cutoff 研究往返，不外推普通股／ETF 身分、完整 current 分類、membership、排名、行情、PIT、資本或配息數值、策略、保存或 Plan。

### 47.2 本次實際驗收與安全返回

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §47.2。

## 48. M1-CHIPS-STOCK-SCOPE-7-GROSS-TRADE-20-1006-1/B1：七股gross買賣與net對照有限操作

本節定義七股 gross 買賣與 net 對照契約，只接受列明範圍，不外推完整 M1。來源、版本、OGL 署名、calendar 及 gross 數值只由[來源 §43](SOURCE_REGISTRY.md)管理；old daily-net §43 及 saved／calendar profiles／flags／default pins 不變，普通股 closes／MA20／股價趨勢仍缺新 rights／calendar，不以此交付完整 M1。

### 48.1 獨立入口與明示取得

新route `/chips-stock-scope-7-gross-trade`、compile `VITE_CHIPS_GROSS_STOCK_SCOPE_7=m1-v1`、runner `--chips-gross-stock-scope-7-opt-in`；API `/api/chips/gross-stock-scope-7`及其 `/capture`。Worker／capture／read與profile須完整匹配SOURCE43外部expectedpins，不從receivedpolicy自建pin、不升olddefaults；有效命令與synthetic邊界見[開發入口](development-baseline/README.md)。

同explicit `as_of=2026-10-06`，選foreign（不含外資自營商）／trust／dealer及5／20日，七股3105／3293／5274／5347／6488／6510／8069卡→同cutoff detail→back保原as_of／investor／horizon三RAWcontrols。套用／切股／改法人或窗口／back不auto-fetch或READ；來源只允許明示FIRST_once一次，重複cachedcapture409／不新增來源；heldREAD只讀same generation。

### 48.2 每日買賣、窗口累計與精確trace

新detail顯示買／賣daily圖及買／賣累計圖、exact日期表與net對照、各窗口buy／sell／net totals；股／張依SOURCE43精確canonical字串，不以SVG約值當數值。5／20的三個累計均從本窗口首日前0開始，窗口起迄清楚，5不沿20起點。全部七股×三法人×兩窗口的 buy／sell／net totals 與每日 prefix 須可完整對帳，不能只核當前股或非零樣本。

Dated operable point與對應date-row展開ALL25原string、原ordinal、bodySHA、ORIGINALreceiptSHA與完整calendar原列；合法postcutoff列保留但不採入。維持TPEx／year2026／兩完整dataset名／observedversions／OGL1.0 URL及來源完整性署名、observation2026-10-08／researchcutoff10-06分離；published／firstavailability／revision未知、nonPIT，不把metadata時間冒row發布或決策時可知。

### 48.3 Mask、缺證與安全返回

Unsupported10/07必須mask全部values／charts／raw／calendar；改回10/06仍masked，只有明示heldREAD成功才恢復同generation。Unknownstock／missing-date／actualsourcefail與讀取失敗均清ALLvalues／charts／raw／calendar，不留舊數值；back只恢復三RAWcontrols，不能unmask或暗讀。Whole7profile依SOURCE43 failclosed，不補0／縮窗／跳壞股。Fresh實件有gross0cell並通過完整gate才驗actualzero；無則明列缺口，不以fixture或missing當真零。
能力邊界：實際零窗口未驗，fixture 不代真零；保存／跨程序未授；完整 M1／M2／M3 未完成。

### 48.4 已接受的具名操作與未跑邊界

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §48.4。

## 49. M1-CHIPS-STOCK-SCOPE-7-DIRECTION-SEGMENTS-20-1006-20261008-1/B1：七股方向與窗口區段有限操作

本節定義七股方向與窗口區段契約，非完整 M1。新來源／OGL 署名／pins／分類與計算由[來源 §44](SOURCE_REGISTRY.md)管理；old net／gross／default pins 與四 TWSE profiles 不改。入口與 synthetic 邊界見[開發入口](development-baseline/README.md)。

### 49.1 獨立入口與RAW controls

Route `/chips-stock-scope-7-direction-segments`、flag `VITE_CHIPS_DIRECTION_STOCK_SCOPE_7=m1-v1`、runner `--chips-direction-stock-scope-7-opt-in`；API `/api/chips/direction-stock-scope-7`及 `/capture`，外部expectedpins完整匹配SOURCE44。Explicit `as_of=2026-10-06`，七股3105／3293／5274／5347／6488／6510／8069，foreign／trust／dealer與5／20窗口。卡→detail→back保as_of／investor／horizon三RAWcontrols；apply／切股／改法人／窗口／back不暗fetch或READ，只有明示FIRST_once及成功explicit heldREAD可顯示同generation。

每日三net分類、各法人正負零counts、maximal signed／zero segments起迄與長度、窗口內latest run均用精確值；zero獨立並終止正負run。Window首段earlierunknown，不能稱完整歷史連續日數。Segment native展開對應日期，再展開三原net／ALL25 header與原strings／ordinal／dualSHA／未增補canonicalreceipt及calendar；署名保TPEx／year2026／兩完整dataset名／observedversions／OGL1.0 URL。Observed10/08與cutoff10/06分離，published／firstavailability／revision未知、nonPIT。
能力邊界：all-zero triple、整窗 zero run 與 latest zero 缺實件，未驗，fixture 不代真值；保存／跨程序未授；不證 price／Signal／Plan／ranking，完整 M1／M2／M3 未完成。

### 49.2 完整actual矩陣與零值邊界

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §49.2。

### 49.3 Mask、明示恢復與同key失敗清值

Unsupported（如 10/07）或空日期 apply 時 mask 全部 counts／category／segments／latest／dates／trace／raw／calendar，且不發 API call；改回 10/06 仍 mask，只有 explicit held READ 成功才恢復同一 generation。Unknown 代號返回有效日期仍 mask；back 保留三 RAW controls 而不 unmask／暗讀。

FIRST 前 invalid query 回 422、unsupported 空值回 200 unavailable、held 回 409；cached POST 帶正確 query 回 409 且無來源 GET，missing query 回 422，兩者分報。API 停止後同 key READ 回 502 即清除全部 counts／category／segments／dates／trace／raw／calendar；back 保同三 RAW 且仍 mask。Whole7 profile 依 SOURCE44 fail closed，不補 0／縮窗或跳壞股。

### 49.4 驗收及退出限制

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §49.4。

## 50. M1-CHIPS-STOCK-SCOPE-7-ADJACENT-WINDOWS-5-1006-20261008-1/B1：兩相鄰5日比較與雙原列操作

本節定義兩相鄰 5 日比較與雙原列契約，不代表完整 M1。來源／版本／pins／完整署名、calendar 及計算只由[來源 §45](SOURCE_REGISTRY.md)管理；old series／gross／direction／default pins 及四 TWSE profiles 不改。Check 入口與 synthetic 邊界見[開發入口](development-baseline/README.md)。

### 50.1 獨立入口與明示來源動作

Route `/chips-stock-scope-7-adjacent-windows`，flag `VITE_CHIPS_ADJACENT_STOCK_SCOPE_7=m1-v1`，runner `--chips-adjacent-stock-scope-7-opt-in`；API `/api/chips/adjacent-stock-scope-7`及 `/capture`匹配SOURCE45外部pins。GET exact一次as_of query、body0；POST exact as_of、空JSON object（4096B上限），不接受unknown／duplicate keys。Explicit `as_of=2026-10-06`、foreign／trust／dealer、horizon5 only；七股3105／3293／5274／5347／6488／6510／8069卡→detail→back保as_of／investor／horizon三RAWcontrols。

Apply／切股／切法人／back不暗fetch或READ；只有一次明示trusted FIRST取得fresh12，明示成功held READ讀同generation。已mask時有效apply／back不能unmask或沿用舊值。FIRST 前 invalid query 回 422、unsupported 空值 200 unavailable、held 409；FIRST 後 cached POST 含 as_of 回 409，missing query 回 422，兩者分報。

### 50.2 Counts、net、差異與兩個日期原列

Board及detail並排前5／近5正負零日數、net總和（股／張）及近5−前5 count／net delta，明示各窗起迄與完整window-limited latest run及segments；起點earlier_unknown限制保留。數值用精確canonical股／張，不把視覺約值當對帳。每股5列pair清楚顯示兩不同日期、各原net與近減前差異；「查看兩份原始列」一次展開兩側完整ALL25 header／原strings、ordinal、bodySHA／ORIGINALreceiptSHA、三net及未增補canonical receipt。

完整calendar原26列（含postcutoff）與原6欄／receipt trace可操作，excluded仍追溯，不僅顯示採入十日。TPEx／year2026／兩完整dataset名／observed versions／OGL1.0與完整署名保持，observation10/08與cutoff10/06分離，published／firstavailability／revision未知、nonPIT。
能力邊界：all-zero triple、整窗全零、net sum 0、total delta 0 與 pair delta 0 缺實件，fixture 不補 actual；保存／跨程序未授；不證 price／Signal／Plan／ranking，完整 M1／M2／M3 未完成。

### 50.3 可信矩陣與actual零值

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §50.3。

### 50.4 Mask、browser return及same-key failureclear

Unsupported（10/07）及空日期 native Apply 不發 API，清除全部 counts／totals／deltas／pairs／segments／latest／raw／receipts／calendar；valid back 仍 mask，explicit READ 200 才恢復同一 generation。Unknown 代號 navigate 後的 browser back 須 mask：`pagehide` 以 flushSync 遮罩並清 selected，`pageshow` 於 persisted 時亦遮罩，保持 lifecycle listener；persisted=true 的 BFCache 復原未受實際觀察，RAM lifecycle checks 只是 synthetic 邊界。

API 停止後 explicit READ 502 清除全部數值；三 RAW back 保同 cutoff 且 mask。requestFailure 或 schema 失敗不留舊值。Whole7 source conflict／missing／unsupported 均 fail closed，不補 0 或縮窗。

### 50.5 驗收、退出及限制

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §50.5。

## 51. M1-CHIPS-STOCK-SCOPE-7-DEALER-COMPONENTS-5-1006-20261008-1/B1：自行買賣、避險及合計並列對帳

本節定義自營商自行買賣、避險及合計並列對帳契約，不代表完整 M1。新版本／pins／provider-owner／完整署名、calendar 與數值只由[來源 §46](SOURCE_REGISTRY.md)管理；old series／gross／direction／adjacent／default pins 及四 TWSE profiles 不改。Synthetic 邊界見[開發入口](development-baseline/README.md)。

### 51.1 獨立入口與明示動作

Route `/chips-stock-scope-7-dealer-components`、flag `VITE_CHIPS_DEALER_COMPONENTS_STOCK_SCOPE_7=m1-v1`、runner `--chips-dealer-components-stock-scope-7-opt-in`；API `/api/chips/dealer-components-stock-scope-7`及`/capture`完整匹配SOURCE46外部pins。GET exact一次as_of query／body0；POST exact as_of／空JSON object（4096B上限），不接受unknown／duplicate keys。Explicit as_of2026-10-06、investor=dealer、horizon=5；七股卡→同cutoff detail→back保as_of／investor／horizon三RAWcontrols，三components始終並列，不篩self／hedge來改名old TOTAL。

Apply／切股／back不暗fetch／READ；僅一次明示trusted FIRST取得fresh7，之後明示成功heldREAD只讀same generation。Masked時valid Apply／back不能unmask或沿用舊數值。SOURCE46日期／pins／全部whole7 gate失敗均unavailable，不補0／縮窗／跳壞股。

### 51.2 三組買賣淨額與完整追溯

List及detail並列self／hedge／total的buy／sell／net五日totals，detail列五日各9metrics、component對帳與精確股／張。Each day及window顯示buy−sell=net、self＋hedge=total的可核結果；股／張依canonical精確字串，不用視覺約值對帳。

每日期原列可native展開ALL25 header／原string、ordinal、bodySHA、未增補ORIGINALreceiptSHA／URL及canonicalreceipt；三components／9metrics與原欄對帳。完整returnedcalendar（本次26列）原6欄、含合法postcutoff excluded與canonical亦可操作，不只採入五日；TPEx owner／FSC SFB provider、year2026／完整兩dataset名／新observedversions／OGL1.0 URL與774B署名保留。Observation10/08與researchcutoff10/06分離，publication／firstavailability／revision unknown、nonPIT。
能力邊界：window zero、triple zero 與 net zero 缺實件，fixture 與 RAM lifecycle checks 不代 actual；保存／跨程序未授；不證 price／ranking／Signal／Plan，完整 M1／M2／M3 未完成。

### 51.3 可信矩陣及零值

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §51.3。

### 51.4 Mask、browser return與同key失敗清ALL

Unsupported（10/07）及空值 native Apply 清除全部 daily／window totals／component checks／raw／receipts／calendar，不發 API call；valid Apply 仍 masked，只有 trusted READ 成功才恢復同一 generation。Unknown 代號 full goto／browser back 全 mask，須 explicit READ 同 generation 才恢復。Lifecycle 含 pagehide flushSync mask、pageshow persisted 守門及 popstate mask；persisted=true 的 BFCache 未實際觀察，不以 RAM tests 補證。

API 停止後 READ 502 清除全部數值，三 RAW back 保同 cutoff 且 mask；source／read／schema 失敗不留舊值。

### 51.5 驗證、退出及剩餘邊界

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/STOCK_RESEARCH_PAGE.md` §51.5。

## #9：七股自行買賣與避險五日方向組合頁

本節定義 #9 的獨立 chips 頁與其本機 API：截止日 2026-10-06、TPEx 3105／3293／5274／5347／6488／6510／8069，自行買賣（`Dealer_self`）與避險（`Dealer_Hedging`）最近五個交易日的每日方向、九種組合、相反方向日數、各方向日數、最大連續區段與窗口內最新區段，並可從區段追溯到該股該日 FinMind 的全部原列。來源、policy pin、gate、計算規則與 SPENT 帳只由[來源 #9 一節](SOURCE_REGISTRY.md#9-qa1七股-finmind-自行買賣與避險五日淨額原件issue9-dealer-direction-combos-finmind-v2)管理，本節不重述；驗證入口見[開發入口](development-baseline/README.md#9-七股自行買賣與避險方向組合的零落盤驗證入口)。

### #9 入口、RAW 控制與返回

- **入口**：路由 `/chips-stock-scope-7-dealer-direction-combos`（七張卡）與 `/chips-stock-scope-7-dealer-direction-combos/:symbol`（詳情）。以 build flag `VITE_CHIPS_DEALER_DIRECTION_COMBOS_STOCK_SCOPE_7=m1-v1` 啟用，不得與其他 chips profile 的 flag 同時啟用（否則 `App` 丟出 `chips profiles cannot be enabled together`）；runner 旗標為 `--chips-dealer-direction-combos-opt-in`。Preview build 須另行注入外部 policy 的 SHA-256（`VITE_CHIPS_DEALER_DIRECTION_COMBOS_POLICY_SHA256`）；空值或格式錯誤時 fail-closed，不顯示任何值。
- **三個 RAW 控制**：`as_of`、`investor`、`horizon`，唯一准入組合是 `2026-10-06`／`dealer`／`5`（兩個下拉各只有一個選項；截止日期是文字輸入，改了只是草稿）。合法的 RAW 查詢是空查詢，或恰好這三個鍵各出現一次且值為准入值；鍵序與百分號編碼不拘，解碼後相同即合法。缺少、多餘、重複、值錯誤的參數，或不在七檔內的 symbol，都遮罩全部值並停用 READ 與 FIRST。空查詢載入後，頁面把網址 `replace` 成標準三元組。
- **套用條件**只改網址：先遮罩、不發任何請求；改回准入值也不恢復舊值，必須明確 READ。
- **返回連結**：卡片連到詳情時帶標準三元組。詳情的「返回七股（保留原始條件）」連結＝列表路由加上當下的 `location.search`，逐字保留，不經 `URLSearchParams` 重新編碼或正規化（含缺少、多餘、重複、值錯誤的 RAW 查詢），所以返回後 READ 與 FIRST 的可用狀態和離開的頁面相同。點擊時先遮罩；返回、套用、切股與瀏覽器上一頁都不暗中 fetch 或 READ。

### #9 取得流程、遮罩與失敗清值

頁面的 phase 為 `unacquired`、`acquiring`、`pending`、`available`、`failed`、`expired`、`released`、`masked`、`unsupported`、`error`；只有 `available` 顯示值。

1. **載入**：phase `unacquired`，不顯示任何值。
2. **FIRST（首次取得來源，僅一次）**：只接受可信（`isTrusted`）的原生點擊，且 RAW 控制合法、沒有進行中的請求、此次頁面載入尚未鎖定 FIRST（用過 FIRST，或 READ 讀到已持有的來源後，都會鎖定；重新載入頁面會解除前端鎖定，但 API 仍回 409 `already_attempted`，不會再取得）；送出 `POST /api/chips/dealer-direction-combos-stock-scope-7/capture?as_of=2026-10-06`，body 恰為 `{}`。取得成功後狀態是 `pending`（reason `pending_independent_admission`）：原件已在 RAM，但尚未通過獨立驗證准入，**不顯示任何值**。
3. **准入**：由獨立 oracle 經 root-local 的 admit 端點把 `pending` 轉成 `available`（規則見來源節）；頁面本身不執行准入。
4. **READ（明確讀取已持有來源）**：只接受可信點擊，送出 `GET /api/chips/dealer-direction-combos-stock-scope-7?as_of=2026-10-06`。只有 API 狀態為 `available`，且前端驗證器通過才顯示：外部 pin 相符、七份 receipt、五日原列、日期、name、dealer 兩列的淨額與全部衍生值重算後逐項相等、generation 與已持有的來源相同。任一不符整批不顯示。
5. **非 `available` 的回應**：`new` 顯示未取得；`acquiring`、`pending` 顯示等待；`failed`（額度已用盡、不重試）、`expired`、`released`、`calculation_conflict`、`cutoff_not_supported` 與網路錯誤、非 200 都清空全部值並顯示對應標籤。FIRST 用過之後再送 capture，API 回 409 `already_attempted`、不發任何 GET。

**遮罩**：套用條件、返回連結、`pagehide`、`popstate`、`pageshow` 且 `persisted`、RAW 查詢不合法或 symbol 未知，都會遮罩全部值。遮罩不可被套用或返回解除，只有明確 READ 成功（且 generation 相同）才恢復。

**失敗清值**：READ 失敗（502、網路中斷、schema 或驗證失敗）會清空全部值（卡片摘要、每日表、區段、組合、原列、日曆），不留舊值，也不把上一次的成功值當作現值。

### #9 顯示與原列追溯

- **列表**：七張卡，顯示「已驗證股數：7」（未取得時為「未知」）；每張卡的摘要表並列自行買賣與避險的正／負／零日數、窗口內最新區段（方向、起訖、日數，首段標「窗口前延續未知」）與相反方向日數。
- **詳情**：每日淨額表（股與張、方向、當日組合、是否相反方向）、兩個 component 的全部最大區段、九種組合的日數與日期、相反方向日期。股與張來自精確字串（張＝股 ÷ 1000，不用浮點）；計算規則見來源節。
- **原列追溯**：每日列的按鈕、區段內的日期、組合日期與相反方向日期都展開同一份「該股該日原列」面板：全部五個 `name` 列（回應列序、name、buy 與 sell 的股與張、原鍵序）、body SHA-256、canonical receipt SHA-256、URL、§31.2 日曆參照（固定交易日，不取日曆），以及未增補的 canonical receipt 文字。
- **零值標籤**：每日淨額為 0 時標「已驗證淨額為零」，原列 buy 或 sell 為 0 時標「已驗證原值為零」；零自成一段。標籤只在 READ 通過驗證後由原列值產生，缺值或未知不當作零。
- **來源說明**（頁尾與日曆區塊）：提供者 FinMind（服務提供者，非官方直接來源）、dataset 名、policy 的權利字串與「API 當下值」（非 PIT）標示、淨額為本地衍生；日曆區塊顯示固定日曆參照、09-29 只作 anchor、56 個 anchor 全數相等，以及零值形狀比對結果（只記錄，不拒用）。

### #9 本機 API 防護與埠

| 端點 | 方法 | 說明 |
| --- | --- | --- |
| `/api/chips/dealer-direction-combos-stock-scope-7` | GET | READ；query 恰為一個 `as_of`（ISO 日期），body 為空。可用時 200，否則 409 並帶 `reason` 的空白 payload（無任何值） |
| `/api/chips/dealer-direction-combos-stock-scope-7/capture` | POST | FIRST；query 同上，body 恰為 `{}`。成功 200（`pending`）；已嘗試過 409 `already_attempted`；取得失敗 502（`failed`） |
| `/__dealer_direction_root_receipt`、`/__dealer_direction_admit` | GET、POST | 供獨立 oracle 的 root-local 端點：只回應 loopback 用戶端、不接受 query；不經 preview 代理，不屬頁面操作 |

READ payload 的 schema 為 `dealer-direction-combos-read/finmind-stock-scope-7-v1`，calculation 為 `dealer-self-hedging-sign-combos-counts-maximal-segments/five-session-int64-v1`。`as_of` 不是 2026-10-06 回 409 `cutoff_not_supported`；query 鍵不是恰好一個 `as_of` 或日期不合法回 422；未登記路徑 404、方法不符 405。

本機服務只綁 `127.0.0.1`，不發 CORS 標頭。API 與 preview 對每個請求先過跨站防護，再碰任何狀態或額度；Host、Sec-Fetch-Site、Origin、POST 的 Content-Type 四項依此順序檢查，第一個不符即回應。其他本機 API／preview runner 套用同一組規則，範圍與限制見[開發入口](development-baseline/README.md#102-本機-runner-的跨站請求防護)：

- **Host**：必須恰有一個值，且為 `127.0.0.1:<該服務的埠>`，否則 403 `host_not_admitted`（防 DNS rebinding）。
- **Sec-Fetch-Site**：有送時須恰一個值，且為 `same-origin` 或 `none`，否則 403 `cross_site_rejected`。
- **Origin**：有送時須恰一個值，且為 `http://127.0.0.1:<該服務的埠>`，否則 403 `origin_not_admitted`。
- **POST 的 Content-Type**：須恰一個值，為 `application/json`（可接 `; charset=utf-8`，不分大小寫），否則 415 `content_type_json_required`。
- **capture 的 body**：恰為兩個位元組 `{}`；BOM、空白、換行、`{ }`、UTF-16／32 寫法一律 422；capture 上限 4,096 B，admit 上限 8,192 B（超過 413 `body_limit`）；深層巢狀回 422，不是 500。
- **Preview 代理**：以 Node 的原始標頭清單套用同一組規則（Node 會丟掉重複的 Host 與 Content-Type，不能看 `req.headers`）；只代理 `GET` 與 `POST …/capture` 兩個產品呼叫，query 恰為合法日期的 `as_of`，其餘 422 `preview_path_method_query_not_admitted`；轉發時固定上游 `Host` 與 `Content-Type: application/json`。root-local 的兩個端點只能直接連 API 埠。

埠：API 預設 8799、preview 預設 8800（`--port`；preview 的 `--api-port` 預設 8799），兩者須不同且介於 1024～65535。#9 的驗證埠為 API 18799、preview 18800，冒煙用 18801／18802（登記見 [#9 留言 6128262506](https://github.com/YiCheng0608/stock-lab/issues/9#issuecomment-6128262506)）。

### #9 已知限制與能力邊界

- **範圍**：只有截止 2026-10-06、七檔、`dealer`（自行買賣加避險）、`horizon=5`。不做排名、篩選、價格、Signal、Plan、磁碟保存、跨程序或 DB；值是「API 當下值」，非 PIT。取得是 RAM-only 單次，生命週期與重取條件見來源節。
- **BFCache 未證，不宣稱支持。**頁面以 `pagehide`、`pageshow`（`persisted`）與 `popstate` 遮罩；用 `location.href` 離開再上一頁時，頁面被重新載入，沒有觀察到 BFCache 還原。
- **FIRST 重按的 phase 標示**：來源已持有時再按 FIRST，API 回 `already_attempted`，頁面把 phase 標成 `pending`（除非是 `failed`），而 API 的實際狀態是 `available`；訊息文字正確、不顯示值。
- **desktop 版面**：1365 寬時七張卡各自的摘要表在卡內橫向捲動才看得到全部欄位（只做 DOM 量測，未做視覺檢查）。
- **Preview 的 `rejected_requests`** 只計次數，不記被拒內容，無法逐筆歸因。
- **前端驗證器的盲區**：非 dealer 三種列（`Foreign_Investor`、`Foreign_Dealer_Self`、`Investment_Trust`）的 buy 與 sell、`row_index`、`key_order` 的實際排列、`generation`、`calendar.meaning` 與 `provenance` 的說明欄位，前端沒有原 body 無法驗；dealer 兩種列的任何改動都會被拒。後端以 56 個 anchor 核 `Foreign_Investor`、`Investment_Trust`、`Dealer_self`、`Dealer_Hedging` 的五日淨額和，`Foreign_Dealer_Self` 不在 anchor 內。
- **空查詢**載入後被 `replace` 成標準三元組，返回連結帶的是點擊當下的網址。
- **零值形狀**：真實原件只涵蓋原列 buy 或 sell 為零的標籤；淨額為零（方向 `zero`）、整窗為零與兩個 component 同為零的形狀，沒有真實原件的紀錄，只有合成資料驗過。
- **來源層限制**（JSON 字面值 `-0` 被當成 0 接受、charge 與 open 之間逾時會保守多記一次 attempted）見[來源節的未驗與限制](SOURCE_REGISTRY.md#9-未驗與限制)。

## #8：七股普通收盤 MA20 與 20 日報酬唯讀區塊

本節定義個股頁技術分頁的「收盤、MA20 與 20 日報酬」區塊及其本機 API：只讀[來源 §52](SOURCE_REGISTRY.md#52-7七股普通收盤與交易日曆的日期時區語意契約)保存的七股名目收盤，在截止 2026-10-06 顯示最近收盤、MA20、20 日報酬與收盤÷MA20。來源、policy pin、保存格式與讀回驗證只由來源 §52 管理，本節不重述。圖表的 MA20／MA60（§3.2）由 response bars 計算，是另一條路徑，兩者互不替代，也不互相補值。文案見 [UI 文案 §10.12](UI_COPY_SPEC.md#1012-七股普通收盤-ma20-與-20-日報酬)。

### #8 範圍與讀取閘門

- **API**：`GET /api/stocks/{exchange}/{symbol}/ordinary-close-trend?as_of=2026-10-06`，payload `version` 為 `ordinary-close-trend/m1-v1`。只有 GET，沒有寫入路由（其他方法 405）。query 只能有一個 `as_of`；未知鍵、重複的 `as_of` 或無效日期回 422；目錄 DB 找不到標的回 404（與 `prices/saved` 一致，七股須在 instruments 內）。
- **支援範圍**：交易所 TPEx、代號 3105／3293／5274／5347／6488／6510／8069；目錄身分須為 market `TW`、`instrument_type=stock`、無 `etf_category`，不比對名稱。截止只有 2026-10-06。
- **不讀檔閘門**：先判截止、再判標的，不符就回 200 的 `unavailable`（`ordinary_close_cutoff_not_supported`，含省略 `as_of`、10-05、10-07；或 `ordinary_close_instrument_not_supported`）。此時不讀環境變數、不開任何檔，也不改用較早或較晚的資料。
- **讀取**：通過閘門後，請求時才讀 `STOCK_ORDINARY_CLOSE_PRIVATE_ROOT`（不在 import 時），呼叫 `load_saved_closes(root, policy_version, "2026-10-06")`，**不帶 `pins`**，使產品 pin 生效（§52 規定）。每個請求完整重驗；不快取、不取源、不保存、不連網。
- **窗口核對**：取保存 60 日的尾端 21 筆。其日期須逐筆等於 bundle 交易日序列的末 21 日、最後一日＝截止，且 policy 版本相符，否則 `ordinary_close_window_mismatch`；缺日不補算、不跨越。
- **失敗形狀**：`status=unavailable`、`values=null`、`closes=[]`、`provenance=null`、`reasons` 非空、`read_state.verified=false`；沒有部分值。

### #8 數值、捨入與追溯

| 值 | 定義 | 使用的收盤 |
| --- | --- | --- |
| MA20 | 最近 20 個交易日收盤的簡單平均 | 21 筆中的後 20 筆 |
| 20 日報酬 | `close[T] / close[T-20] − 1`，T＝截止日 | 21 筆 |
| 收盤÷MA20 | `close[T] / MA20[T]` | 同上 |

MA20 沿用 §3.2；20 日報酬是 [V1_SPEC](V1_SPEC.md) 族群 20 日報酬的單股形式，**不是**相對 TAIEX 的 `group_excess_return_20d`。三者都不是新公式，不用較短窗口、不前填，計算前不逐筆四捨五入。

- **精確值**：以有理數計算（後端 `Fraction`，前端 BigInt）；每個值的 `exact` 是約分後的分數字串。
- **捨入**：只在 `display` 捨入一次，四捨五入、0.5 遠離零進位（half away from zero，非銀行家捨入），結果為零時不帶負號。MA20 取 2 位（元／股）；20 日報酬以百分比取 2 位（`display_unit=percent`、`display_scale=100`）；收盤÷MA20 取 4 位。收盤以保存的原字串顯示，不捨入。每個值帶 `display_unit`、`display_scale`、`display_places` 與 `rounding=half_up_away_from_zero`。
- **逐值追溯**：`closes` 為 21 筆 `{date, close}`（原字串）。MA20 帶 `window_start`、`window_end`、`count`；20 日報酬帶 `base_date`、`base_close`、`latest_date`、`latest_close`；收盤÷MA20 帶 `latest_date`、`latest_close`、`ma20_window_start`、`ma20_window_end`。
- **資料不足**：單值在收盤不足時為 `data_insufficient`（`ordinary_close_window_insufficient`），不補算。
- **趨勢**：`values.trend` 固定 `status=formula_not_defined`、`reasons=["trend_formula_not_defined"]`，`exact`、`display` 為 null，畫面稱「趨勢判定規格未定義，不推論」。原量化契約沒有獨立的個股趨勢公式；pullback 的 MA20／MA60 過濾需要 60 根收盤並跨越公司行動，來源 policy 不支援，不屬本區塊。不以 MA20、報酬或比值的正負推論方向。

### #8 來源版本、不支援項與限制

- **`provenance`**：`storage`、`storage_schema`、`consumer_version`、`source_policy`（version、sha256、bytes）、`cutoff`、`closes_file`／`closes_bytes`／`closes_sha256`、`receipt_sha256`、`saved_at`（UTC）、`calendar`（來源版本、筆數、窗口、時區語意）、`adapter` 雜湊、`attribution`、`rights`；`publication_time`、`first_availability`、`revision_time` 皆 `unknown`，`historical_pit=unsupported`。
- **`unsupported`**（policy v1 逐字 16 項）：`historical_pit`、`publication_time`、`first_availability`、`revision_guarantee`、`adjusted_prices`、`company_actions`、`suspension_comparability`、`whole_window_historical_membership`、`historical_eligibility`、`actionable_strategy`、`plan`、`trading`、`historical_simulation`、`raw_body_storage`、`redistribution`、`other_cutoffs`。後端回應與前端核對都要求與此清單**集合完全相等**（不多、不少、無重複；順序不屬契約），available 與 unavailable 兩種回應皆然，不符整份不採。
- **`limitations`**：來源模組的固定限制碼（內容對應 §52「範圍與限制」），加上 `provider_reported_nominal_closes_not_adjusted_for_company_actions`、`suspension_comparability_not_established`、`trend_judgement_formula_not_defined_not_inferred`、`not_historical_pit_not_a_plan_signal_or_trade`。
- **`read_state`**：`verified`、`read_only=true`、`network_requests=0`、`writes=0`。
- **用途**：只顯示名目收盤（未還原）與它導出的研究值；不含公司行動與停牌可比性，非 PIT；不進條件計畫、Signal、策略成立判定或可執行建議，兩策略的判定仍由各自契約負責。

### #8 原因碼與失敗清值

`reasons` 是穩定代碼，中文文案由 [UI 文案 §10.12](UI_COPY_SPEC.md#1012-七股普通收盤-ma20-與-20-日報酬)管理。

- **後端**：
  - `ordinary_close_cutoff_not_supported`、`ordinary_close_instrument_not_supported`：不讀檔閘門。
  - `ordinary_close_` 加來源讀回的錯誤碼：`root_unset`（環境變數未設或空字串）、`root_invalid`（非絕對路徑或含 `..`）、`saved_*`（§52 讀回驗證失敗，例如 `saved_missing`）等；碼不符 `[a-z0-9_]{1,64}` 時為 `ordinary_close_read_failed`。
  - `ordinary_close_window_mismatch`：窗口核對失敗。
  - `ordinary_close_storage_io_failed`：讀檔發生 `OSError`。
  - `ordinary_close_window_insufficient`：單值資料不足。
- **前端另有**：`ordinary_close_request_failed`（請求失敗）與 `ordinary_close_contract_invalid`（回應未通過前端核對）。
- **前端核對**：版本、標的、截止、頂層與 `provenance` 的欄位集合、policy pin（版本、SHA-256、bytes）、`unsupported` 集合、`read_state`，並以 21 個收盤原字串獨立重算三個值（`exact`、`display` 與追溯欄位）。任一不符整份不採，不顯示任何數值。
- **失敗清值**：任何失敗都不留數值、收盤與來源明細，不以舊值或零代替。

### #8 畫面與操作

- **位置**：只在 TPEx 七股個股頁的「技術」分頁、圖表之後出現；其他標的不渲染此區塊。
- **明示讀取**：載入時不發請求，初始為「尚未讀取」。截止等於 2026-10-06 才有讀取按鈕，按一次發一次 GET。截止不是 2026-10-06（含最新資料、未指定日期）時，說明不符、無按鈕、前端不發請求；API 對同一情形仍獨立擋下。
- **清值**：切換股票或截止日期（含 A→B→A）後，值全部清除並回到「尚未讀取」，須重新按按鈕；舊 context 的晚到回應丟棄，不填入目前 context。
- **返回原條件**：區塊不改網址，個股頁的 `as_of` 與從關注頁帶來的返回條件原樣保留；返回關注頁的行為依[§37](#37-m1-saved-price-focus-1006-1保存來源關注與同截止往返)，本區塊不改動。
- **展開明細**：收合區列 21 筆日期、收盤原字串與用途，三個精確分數，政策版本與 SHA-256，收盤檔與收據的 SHA-256，保存時間，交易日曆，發布／首次可得／修訂皆 `unknown`、PIT 不支援，署名與 16 項不支援項。

### #8 能力邊界與未驗

- **範圍**：只有截止 2026-10-06、七檔；不做排名、篩選、保存、DB、其他截止、較短窗口或趨勢判定。值是已保存名目收盤的導出值，非 PIT。趨勢公式未定義前，本區塊不宣稱趨勢完成。
- **未驗：從 `/focus/price-saved` 列表卡片點入。** 該列表讀另一個私人 root，不在本區塊的授權範圍；實機只驗了卡片產生的同形詳情網址與五個條件的返回。
- **前端「資料不足」分支不可達。** 來源恆為 60 日，API 不輸出 `data_insufficient`；前端若收到，會因三個值須皆為 `available` 而整份當作 `ordinary_close_contract_invalid` 拒用，仍不顯示任何數值。API 層資料不足的語意只由 `derive_values` 的單元測試證明。
- **窗口內兩筆收盤互換偵測不到。** 互換不改變 MA20、報酬與比值，前端重算無從察覺；追溯靠 `closes_sha256`。
- **新增測試不在 CI 清單。** 後端 `tests/test_ordinary_close_trend.py` 與前端 `OrdinaryCloseTrend.test.tsx` 不在 CI 的固定子集內，由工程自測與 QA 執行。
- **瀏覽器**：原生操作只在 Edge；Chrome、Safari 與其他時區環境未驗。
