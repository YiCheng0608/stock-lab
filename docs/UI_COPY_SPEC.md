# UI 文案與資訊層級規格

更新：2026-10-04。本文是日常頁的中文、資訊層級、單位、unknown 與 reason code 契約；繁中文案、法人命名、數值格與官方分點入口已有有限 review，成交額 availability 的 UI 語意依本輪資料契約補充，不表示已新增成交額介面或所有案例均已驗收。能力狀態見 [ROADMAP](ROADMAP.md)，策略合併判定見 [PRODUCT_SPEC](PRODUCT_SPEC.md#action-merge)。

## 1. 共通原則

- 日常頁使用可理解、可追溯的繁體中文；enum、欄位名、資料庫 key、raw ID 與 ISO 時間只可在預設收合的研究／系統層。
- 每個「完整」都須說明資料層與用途。官方事實、規則關聯、推論與 unknown 分開；unknown 不是負面訊號。
- Asia/Taipei 日期顯示 `YYYY/MM/DD`，日期時間顯示 `YYYY/MM/DD HH:mm`。
- 「現價」只用於可信即時報價；日資料一律寫「最近收盤（日期）」。缺少可驗證行情時不顯示價格結論。
- 台股紅漲綠跌須同時有正負號或文字，不能只靠顏色。
- 數值表格、缺值與合法 0 的顯示依 [§10.4](#104-數值表格單位與空白)。

## 2. 禁止露出的內部詞與繁中對照

| 內部詞 | 日常頁 |
| --- | --- |
| DecisionSummary | 行動摘要 |
| data_insufficient／data_incomplete | 策略判斷資料待補 |
| canonical／canonical config snapshot | 固定研究規則／規則版本與稽核設定；只在研究詳情 |
| prior_20_highs／bars_20d／bars_60d／institutional_flow_5d | 前 20 個交易日高點／近 20 日行情／近 60 日行情／近 5 日法人籌碼 |
| company／taiwan／international | 個股公告／台灣官方事件／國際事件；尚未接入的來源不顯示空卡 |
| foreign_investor | 外資；日常頁使用簡稱，來源／稽核層保留官方「外資及陸資」合計欄位的口徑 |
| high confidence | 標的關聯已驗證；不得解讀成勝率 |
| medium confidence | 關聯由規則核實；可展開查看使用的方法與規則 |
| low／unknown confidence | 關聯尚未判定；不驅動進場、出場或其他交易動作 |
| impact_direction unknown | 影響尚未判定 |
| official_disclosure | 官方公告資料 |
| 未核實 Industry 名稱、代碼或 ID | 日常頁不顯示；系統頁寫「官方產業名稱待對照」 |

## 3. 三種資料完整度

| 資料層 | 完整 | 部分／缺失 | 只代表 |
| --- | --- | --- | --- |
| 來源擷取 | 來源擷取完整 | 來源擷取部分完成／失敗 | 來源與 raw 稽核；不代表欄位或歷史窗口完整。 |
| 當日行情 | 當日行情完整 | 當日行情部分缺漏／尚無可驗證行情 | 指定標的、市場與日期的 OHLCV。 |
| 策略判斷 | `<策略>條件資料完整` | `<策略>條件資料待補` | 該策略所需行情、TAIEX、membership、籌碼等輸入。 |

同頁可同時顯示「來源擷取完整 · 當日行情完整 · 回踩條件資料待補」，並列精確缺項。全市場 run 成功或資料列增加不能升格個別標的；全域 partial 也不能自動降級一條已完整策略。

同卡有兩條策略時使用「主研究條件資料完整 · 另一研究條件資料待補：<缺項>」。只有所有呈現條件都完整時才可省略範圍。完整 observation 沒有 entry／target／RR 仍是完整，不使用資料待補 badge。

## 4. 新聞卡文案與折疊

### 4.1 卡片正面

固定順序：分類與來源 → 兩行內原始標題 → 120 個全形字元或三行內摘要 → 來源時間 → 影響／關聯 → 相關標的 → 來源連結。標題只正規化連續空白與換行，列表截在兩行，詳情仍保留完整標題。`/news` 不展開全文；`/news/:id` 用「展開公告內容／收合公告內容」，只顯示可用的來源 description，不顯示 raw JSON 或內部 ID。

沒有摘要時寫「官方來源未提供摘要」。只有存在合法可用原文時，才可另顯示附引用與方法的「AI 摘要」；不得由標題或模型記憶補造。

### 4.2 日期與可信度

| 狀態 | 文案／處置 |
| --- | --- |
| published_at／event_at／event_date | 「發布於 日期時間」／「事件於 日期時間」／「事件日 日期」 |
| 三者皆無 | 「來源時間未提供」；collected_at 只在詳情稽核層顯示「系統收錄時間」 |
| time_consistency=conflict | 「資料集事件日期與公告內容提及日期不一致，時間待人工核實」 |
| 直接關聯／核實規則關聯／無證據 | 「標的關聯已驗證」／「關聯由規則核實」／「關聯尚未判定」 |

列表按 [NEWS_SPEC](NEWS_SPEC.md) 的已核實來源時間與 cursor 契約排序。未知時間目前可有 collected_at fallback，但不可顯示成發布時間；目標是移到時間待核實區。confidence 只描述關聯證據，不表示事件真假、方向或報酬。

### 4.3 來源連結

- `source_url_kind=item`：「查看原文／原始公告」。
- `source_url_kind=feed`：「查看官方公告資料集」，並提示未必定位本則公告。
- `source_url_kind=none`：「來源連結未提供」，不畫無效按鈕。
- raw payload、hash 與 event ID 只在稽核層。

### 4.4 族群關聯

新聞卡只顯示來源直接指向且已驗證的族群，或已核實的 Event—Instrument—Theme 關聯。由現有 membership 自動推得、英文名稱／代碼、名稱狀態未核實的關聯只留系統層。

## 5. 行動中心的預設資訊層級

1. **持倉風險與觀察**：已驗證減碼／退場條件、使用者 stop 或持倉風險資料待補。
2. **可研究條件**：完整 conditional、有合法 contract 價位的等待條件，以及持倉觀察。
3. **自選／事件關注**：自選、已核實事件，或完整 observation 的「暫無研究條件，持續觀察」。
4. **資料待補**：預設收合為「X 檔暫無法評估」，列最多三種常見缺項。

非持倉 data insufficient 不進預設卡片列表。行情完整但策略不足時可顯示「最近收盤」；當日行情不足時寫「價格資料尚未完整，暫不顯示最近收盤」。無合法 levels 或 RR 時隱藏相應區塊，必要時寫「研究價位／風險報酬比暫無法計算」，不用 0 或破折號。

## 6. 行動狀態與卡片文字

| `action_state` | 標籤 | 次文案／限制 |
| --- | --- | --- |
| conditional_entry | 符合條件後可研究進場 | 觸發與資料條件成立後，最早 T+1 再檢查；不是成交。 |
| wait_breakout | 等待突破條件 | contract 有合法門檻時才顯示；突破後仍需重查量能、族群與籌碼。 |
| wait_pullback | 等待回踩條件 | contract 有合法區間時才顯示；回到區間後仍需重查趨勢、量能與籌碼。 |
| hold_observe | 持倉觀察 | 只用於持倉，留意使用者 stop、策略失效與資料更新。 |
| reduce_exit | 持倉風險：減碼／退場條件 | 已碰到既定風險條件，重新研究處置；不是自動下單。 |
| data_insufficient | 策略判斷資料待補 | 目前無法產生研究動作；列精確缺項，不顯示方向。 |
| no_condition | 暫無研究條件 | 資料完整但條件未成立且沒有合法等待價位；顯示未通過理由。 |
| manual_review | 需人工判讀 | cutoff、basis、標的、價位或執行證據無法調和；不合成動作與價位。 |

日常頁說「突破／回踩研究條件」，完整版本名只在研究詳情。

### 6.1 兩個研究條件的合併呈現

判定以 [產品行動合併契約](PRODUCT_SPEC.md#action-merge) 為準。UI 維持同標的一張卡與各策略自己的價位；持倉風險優先，其他條件置於「其他研究條件」。沒有合法等待價位時顯示「暫無研究條件」，不得因另一策略缺資料而降級已完整條件。

## 7. Glossary 覆蓋與呈現

前後端 glossary 至少覆蓋 `stock_chips`、`foreign_investor`、`trust_investor`、`dealer`、`margin_change`、`breakout`、`pullback`、`rr`、`data_completeness`、`taiex`、`lot`、`average_cost`。Modal 依白話定義、用途、解讀與限制排列，不以 term_id 或欄位名作標題；完整詞義見 [GLOSSARY](GLOSSARY.md)。詞彙按鈕須支援滑鼠、觸控、Enter／Space，Esc 關閉後焦點回觸發點；定義不得只靠 hover 或顏色。

## 8. 程式驗收條件

驗收至少涵蓋：日常路由不露內部字串；三層完整度與雙策略範圍不衝突；新聞全文折疊、URL 類型、unknown 影響與未核實族群正確；行動中心不被資料待補卡淹沒；詞彙可鍵盤操作；雙 observation 無合法價位時不造 levels；同標的一日一張卡；250／1,000／1,250 股格式及每股成本正確；法人欄顯示「外資／投信／自營商」；數值表格的單位、正負號、合法 0 與空白原因符合本規格。未知、空值、載入失敗與窄版也須 fail closed。

## 9. v1 族群空狀態與發布規則

完整與四分項條件以 [V1_SPEC](V1_SPEC.md#hot_group_v1) 為準。UI 對合格 partial 顯示「技術與籌碼觀察（事件資料待補）」，不得稱完整熱門或產生完整熱門候選；歷史零結果不形成永久文案。

## 10. 壓縮卡、詳情與單位文案

### 10.1 今日／個股清單壓縮卡

順序為：代號／名稱 → 最近收盤與可信漲跌幅 → 一個行動結論 → 一個主要原因 → 一組關鍵價位（如合法）→ 資料日期與詳情入口。缺相鄰、同 basis 的可信前收盤時寫「漲跌幅待核實」；no condition、資料待補或人工判讀不顯示關鍵價位。

### 10.2 個股詳情的第一屏

依「今日研究結論 → 現在怎麼做 → 關鍵價位 → 為何如此 → 資料時間與完整度」排列；技術、籌碼、事件、替代條件和稽核置後並可收合。固定附註：「此為研究工具與資料摘要，不構成投資建議、報酬保證或自動下單指令。」

M3-P6c 個股行情讀回隔離的下列文案已有限接受。StockPage 無行情記錄時提示「尚無行情記錄。」；真 invalid／partial、malformed 或 conflicting 讀值契約時提示「行情讀值無效，先核對原記錄。」。兩者接續「最近收盤與漲跌待核實；已知日期的合法歷史行情仍可查看。」；頁首最近收盤與漲跌顯示「待核實」，不把拒用改稱零或負面訊號。stored syntax known 而 M1 尚未准入／缺原件證據時，只呈現報價待核實與既有來源不足說明，不加「行情讀值無效」。missing 0／空 metadata 保留無行情文案；兩項退修經必要 HTTP／SSR 及具名畫面後才接受。其餘獨立研究入口保留。精確 API／窗口／來源 gate、有限相容、實際操作與未驗界線只由[個股頁 §15](STOCK_RESEARCH_PAGE.md#15-m3-p6c個股詳情行情讀回污染隔離)詳述，不在此複製。

M3-P6d 研究候選讀回隔離與候選 read.status 非字串 guard 的單項退修已有限接受。新版 invalid／malformed 提示為「研究候選讀值無效或格式待核實，先核對原記錄；行情與其他獨立區塊仍可查看。」；可定位的 slots 隔離續接「各策略分別核對，不以較早候選代替。」。拒用研究 summary／levels 不把獨立行情改為零或壞值，也不抹除健康 alternate 與原 complete observation／hold_observe／primary=null。精確資料契約、十個已核 malformed case、非字串 focused 補驗與具名 browser 操作界線只由[個股頁 §16](STOCK_RESEARCH_PAGE.md#16-m3-p6d個股詳情研究候選讀回污染隔離)負責。

研究分頁新增「研究候選 · 只讀記錄」，附「本窗 N 筆，最多 20 筆；固定要求仍為兩種策略。讀值語法不證來源、可得時間或成立條件。」。每列保留「記錄 #ID · 策略」、日期、版本與「原狀態」，不是建立 Plan／採用候選按鈕；候選筆數與固定兩種策略不可混稱。狀態文字如下：

| 狀態 | 實際文案 |
| --- | --- |
| invalid | 「候選讀值無效，先核對原記錄。」 |
| missing | 「必要讀值未提供。」 |
| known | 「儲存讀值語法已分類，尚不代表研究條件成立。」 |
| 可選欄位 invalid | 「部分欄位待核實；可選顯示欄位不單獨否定其他完整策略。」 |
| 無候選 | 「本截止範圍尚無研究候選。」 |
| malformed | 「研究候選讀回格式待核實，先核對原記錄。」 |
| 完全 undefined 舊回應 | 「舊版回應未提供研究候選讀回狀態。」；null／矛盾的新狀態不當舊回應。 |

全標的 unknown date 用「全標的有 N 筆候選日期無法定位（記錄 #ID）；研究結論待核實。」；未知策略 identity 改為「策略身分無法定位」。無日期／版本／原 status 時寫「待核實」，未知策略名為「策略身分待核實」，不捏造較早候選或成立結論。已接受五案中的 B-JSON 最終原生分頁切換；其餘四案是程式 DOM.click 後核實 actual browser DOM，不泛稱五案原生互動通過。非字串 status 必須拒用，必要 pure 補驗中合法 missing 提示保留、malformed 提示存在、known 提示不冒用。

#### M3-P6e 獨立特徵／籌碼區塊文案（有限接受）

以下文案已由統籌在必要 actual HTTP／App 及具名操作範圍有限接受；來源／具名操作有限接受、主線說明已整合；版本封存與 merge 收據以 Git／原 task 為準。六案中只有 B 最終原生切 tab，其餘 DOM.click 支持與原失敗分報，不外推全部原生互動。精確讀值／窗口／截止與欄位 gate 只由[個股頁 §17](STOCK_RESEARCH_PAGE.md#17-m3-p6e個股特徵籌碼獨立區塊讀回隔離)負責。

| 區塊與狀態 | 實際文案 |
| --- | --- |
| 後端特徵 missing／invalid／malformed | 「後端特徵讀值缺失或無效，先核對原記錄；不以較早快照替代，行情與研究條件仍可查看。」 |
| 後端特徵標籤 | 「MA20／MA60（後端特徵快照）」；不能冒稱前端歷史行情計算的均線。 |
| 有可核實快照 | 保留快照資料日、來源與建立時間，附「讀值語法不證明來源或當時可用性。」 |
| 籌碼 missing／invalid／malformed | 「籌碼讀值缺失或無效，先核對原記錄；未提供與無效數值保留空白，其他獨立區塊仍可查看。」 |
| 無可核實籌碼列 | 「尚無可核實的籌碼資料。」 |

特徵拒用的 MA 與籌碼各欄 null 保留待核實／空白，不補零或改成負面研究結論；有限 MA 的零與負值依原語義顯示，不另加正值門檻。malformed 只拒用所屬 section，合法 chip 列可各欄保留；健康行情與原研究條件獨立。P6d 文案與其 native／DOM.click 支持界線不改。

### 10.3 張／零股

DB／API quantity 保持精確整數股；台股 UI 的已知股數以 `原值 / 1,000` 顯示為張，最多 3 位小數，負值保留方向。250、1,000、1,250 股在非表格的部位摘要可分別顯示「250 股（零股）」「1 張」「1 張 250 股」；表格仍依下一節把單位置於表外。平均成本是每股價格，單位放欄位標題或緊鄰說明；幣別須有來源證據，API 未提供 currency 時寫「各標的報價幣別的元」，不得一律加 `NT$`。來源或數量單位 unknown／mixed 時不換算；表格外寫「單位待核實」，數值格留空。TAIEX 等指數用點數。

#### M3-P1 既有庫存股數的有限呈現契約

本節保留 M3-P1 當時的有限驗收，現行保存與輸入範圍由下方 [M3-P2](#m3-p2-可信整數保存與磁碟重開契約)補充。本批「既有可信庫存股數→精確張／零股／原股呈現與失精輸入拒收」的九個程式檔、必要驗證與具名庫存操作已由統籌有限接受。當時持倉 `shares` 儲存型別為 Float，本批只信任**當時儲存值**為有限、非負整數且不超過 `9,007,199,254,740,991` 的股數，零只供讀取。超上限、負值、分數或非有限舊值顯示「股數待核實」，不把已捨入的大數還原成原先奇數或 int64 上限，也不宣稱已修復存量或大整數保存。

持倉 API 保留既有 `shares` 數字相容欄；非有限值不能作合法 JSON 數字時回 `null`。增添的 `shares_exact` 在可信時為 canonical ASCII 十進位整數字串，零為 `"0"`、其他值無前導零；不可信時為 `null`，`quantity` 亦為 `null`。可信 `quantity` 保留原有 numeric 欄與單位／拆分形狀，另補 `total_shares_exact`／`quantity_lots_exact` 字串；前端型別允許補欄缺失以相容舊 API。純 Python helper 接受實際 `int` 的 `0..9,223,372,036,854,775,807`，用整數 `divmod` 拆張／零股；這與 ORM Float 的安全範圍分開驗證，不把純 helper 的大數支持當成已保存的大數能力。

JavaScript 股數顯示 parser 支持完整 `0..9,223,372,036,854,775,807` 的 canonical ASCII 字串，直接拆最後三位及加千分位，保留精確張數、零股與原股數。只有 `shares_exact === undefined` 的舊回應，才可回退至有限、非負且為安全整數的 `shares` number；明示 `null`、壞格式、溢位、Unicode 數字、尾端空白或換行均拒用，不再以數字欄補值。存量可信上限須保留尾數 991，例如 `9,007,199,254,740 張 991 股` 及 `9,007,199,254,740,991 股`；非表格摘要沿用張／零股文案，表格仍依 §10.4 將單位放表外。可信 `quantity.unit="mixed"` 表示同一已知總股數拆成整張加零股，是呈現分類；來源數量單位 unknown／mixed 則仍不換算，兩者語意不同。

新增／更新保留四種互斥的 StrictInt 正整數輸入：`shares`、`unit + quantity`（`unit=lot` 或 `odd_lot`）、`quantity_lots`、`odd_lot_shares`，一次只能提供一種。最終股數須為 `1..9,007,199,254,740,991`；張數乘 1,000 後再檢查上限，unsafe 請求在 commit 前以 HTTP 422 拒收並保留既有持倉。UI 先以原始 ASCII 數字與所選單位檢查正整數及上限，再轉 Number 送出；股單位上限為上述安全整數，張單位上限為 `9,007,199,254,740`。表單須說明目前可保存範圍並顯示結果／錯誤，不讓輸入捨入後成為另一個合法值。

本批只處理股數呈現與失精輸入 gate，正常估值、決策與計畫計算不變。純記憶體 SQLite 的保存／讀回不代表磁碟重開；正式 DB、真官方／live、估值、新計畫、完整 backend、production build 與完整 M3 均未由本批驗收。實際證據與待驗項依[開發入口](development-baseline/README.md#m3-p1-既有庫存股數的零落盤驗證入口)及[協作紀錄](TASK_COORDINATION.md)，尚未通過的項目不得稱完成。

本次產品驗收採 `2026-10-03` 的 TWSE／TPEx synthetic 使用者庫存，不是官方行情或正式 DB 樣本。實際 router、記憶體 SQLite commit／refresh→GET、product fetch／`Response.json()` 與具名庫存操作已有限接受；純 helper 的實際 int `ODD`／int64 `MAX` 及 SSR 字串 formatter 另驗，未把 ORM `ODDFLOAT`／`MAXFLOAT` 的未知股數升格成可信大數。

| 具名操作 | 已接受的有限結果 |
| --- | --- |
| 桌面 `1365×900`，兩市場 `ZERO0`／`SAFE`／不可信舊股數 | 零可唯讀呈現；SAFE 保留完整原股數及尾數 991；不可信股數顯示待核實，不用數字欄回退。 |
| TWSE 股單位原始輸入 `9007199254740993`／SAFE 保存 | 前者由 UI 拒收、無 POST；SAFE 保存後精確讀回張／零股／原股數。 |
| 桌面張單位 `9007199254741`／`9007199254740` | 超限拒收，該列完整 JSON 不變；最大合法張數保存後讀回，該 TWSE 測試持倉的刪除亦已核對。 |
| TPEx `390×844` 窄版，`1001` 股保存後刪除 | 呈現 `1 張 1 股` 及原值 `1,001 股`；document 寬 375，12 張卡的 24 個數量子元素 client／scroll width 均為 273，editor 寬 305，未觀測橫向溢出。 |

具名操作的擷取範圍 console 為空；19 個網路請求均為自有 `8778`、status 200（3 POST／2 DELETE／14 GET），23 個 performance entries 均同 origin，觀測外網為 0。這些計數限該擷取範圍，不當整段 session 的完整 log。preview 只在記憶體 CSS 排除外部字型並以 CSP 阻外網，本次限 fallback font，不修改正式字型契約。QA viewport 已還原 `1365×900`，tab 已關閉，兩個自有 server／listener 已獨立核實不存在，新增測試產物／殘留為 0；測試與清理的 exit 0 分報，版本、命令、操作及清理收據留原 task。

#### M3-P2 可信整數保存與磁碟重開契約

本批支援 M3／R2-C1 的股數保存基線；核心契約、必要記憶體／磁碟／HTTP 與下表具名操作已有限接受。持倉保留 `shares` Float 相容欄，另用 nullable `shares_integer` 保存 `0..9,223,372,036,854,775,807` 的 SQLite 整數，零只供讀取。有效新欄優先；新欄非 NULL 卻非實際 int、為負值或溢位時，`shares_exact`／`quantity` 為 `null`，不得回退至 Float。新欄 NULL 才可沿 M3-P1 gate 使用目前有限、非負、安全整數的舊值；unsafe、分數、負值及非有限舊值仍是「股數待核實」。Migration 只一次回填可信舊值，不重建已捨入的原數，也不改舊 Float 或成本／停損／風險／note／updated_at；具體 schema／rollback 規則見 [R0 §8.11](R0_IMPLEMENTATION.md#811-m3-p2持倉精確整數-migrationreadiness有限接受)。

新寫入仍同時保存 exact int 與 Float mirror。P2 當時 API `shares` 保持 raw Float 的有限數字相容性；現行讀取已由 [M3-P5](#m3-p5-可信庫存股數與既有估值持倉判定一致) 改為可信 safe 總股數 numeric，其餘 null。`quantity` 的原 numeric 欄仍不能作大數精確顯示依據。`shares_exact`、`total_shares_exact` 與 `quantity_lots_exact` 使用 canonical ASCII 整數字串，張／零股由整數拆分，`quantity` 原有 numeric／unit／display 形狀保留。JavaScript 優先用完整精確字串，不經 Number；只有精確欄缺失的舊 API 可回退至有限、非負、安全整數 number，明示 `null` 或壞字串仍不得補值。`mixed` 的已知張／零股拆分與來源單位 unknown／mixed 的語意保持 M3-P1 規則。

四種互斥輸入仍為 `shares`、`unit + quantity`（`unit=lot`／`odd_lot`）、`quantity_lots`、`odd_lot_shares`，一次只能提供一種。每種欄位可用 strict 正整數 number，最終總股數仍限 `1..9,007,199,254,740,991`；或用無前導零的 canonical ASCII 正整數字串，最終總股數可到 `9,223,372,036,854,775,807`。張數以整數乘 1,000 後再驗上限；number 張數上限 `9,007,199,254,740`，string 張數上限 `9,223,372,036,854,775`。零、bool、float、負值、Unicode 數字、空白／換行、正負號、分數、科學記號、混合表示及溢位，均在 commit 前以 HTTP 422 拒收，既有持倉完整列保持不變。

UI 檢核原始 ASCII 數字字串，可刪前導零形成 canonical 字串；全零仍拒收，不轉 Number 送量。表單說明 int64 保存上限，股單位與張單位分別套上述 string 上限；保留完整原股數、張數與餘股，超限時不送 POST。最大合法張數保存成 `9,223,372,036,854,775,000` 股，零股為 0。顯示 parser 的 `0..int64 MAX` 範圍不縮限，平均成本仍是每股價格，表外單位依 §10.4。

本批不改正常有限估值、held／worker／risk／new Plan 行為；Float 相容欄的大數估值不宣稱 exact 或完整驗收。來源與保存範圍為 `2026-10-03` synthetic TWSE／TPEx 使用者庫存，沒有新增官方來源或正式持倉 coverage。必要磁碟 migration／close／reopen、actual `app.main` owned fixture startup 與 HTTP 支持範圍見[開發入口](development-baseline/README.md#m3-p2-可信整數保存與磁碟重開驗證入口)；正式 DB／migration、production deployment、真官方／live、完整 backend／production Vite build、新計畫、完整 M3、歷史／availability／PIT 及原 M1／M2 gate 仍未完成。

| 具名操作 | 已接受的有限結果 |
| --- | --- |
| Actual `1365×900` 桌面，TWSE NEW 股單位 `9007199254740993` | POST 200；完整原股數與 `9,007,199,254,740 張 993 股` 正確。 |
| 同桌面，TPEx NEW 股單位 `9223372036854775807` | POST 200；完整原股數與 `9,223,372,036,854,775 張 807 股` 正確。 |
| 關閉第一個 API 程序，再以第二個程序開同一磁碟庫 | actual lifespan／readiness 通過；完整兩列 NEW JSON（含 updated_at）與關閉前相同。 |
| `390×844` reload，兩列完整 int64 呈現 | document client／scroll width 均 375，數量元素均 273，未觀測橫向溢出。 |
| 窄版股數 MAX+1／張數 `9223372036854776` | 原生表單拒收、POST 計數 `2→2`；兩列完整 NEW JSON 不變。 |
| 窄版最大合法張數 `9223372036854775` | 保存 200，exact 股數 `9223372036854775000`／零股 0；14 張卡的 28 個數量元素 client／scroll width 均 273，editor 305，未觀測橫向溢出。 |
| 窄版原生刪除兩列 NEW，再讀回 | 兩次 DELETE 200；GET 200／items 空、cards 0。 |

本次只接受正確 post-navigation viewport 與 focus 後實際生效的操作；初始 blank viewport、hidden 頁面的未生效 click 及 Orca runtime_unavailable 不算操作通過。擷取範圍 32 個 network requests（27 GET／3 POST／2 DELETE）均為自有 8780、status 200，reload 後 16 個 performance resources 均同 origin，觀測外網為 0；不當完整 session log。Console 的 7 entries 為 3 個 React DevTools info 與 4 個已知 React Router future warnings，無 error，不宣稱空 console。QA viewport 已還原、tab 已關閉，自有程序／child／listener 已核實不存在；隔離 DB 已清；capture stop 額外 HAR 的審核拒絕殘留分報於[協作紀錄](TASK_COORDINATION.md)。命令、版本、原始失敗與有限接受收據留原 task，不另造附件。

<a id="m3-p3-庫存成本停損風險輸入可信檢核與拒收保留"></a>

#### M3-P3 庫存成本／停損／風險輸入可信檢核與拒收保留

本批支援 M3／R2-C1 的可信使用者輸入基線；七個程式檔、必要記憶體 router／JSON／前端驗證及下表具名庫存操作已由統籌有限接受。既有 `average_cost` 是每股成本，`stop_price` 是使用者停損輸入，`risk_budget` 保留為持倉記錄欄；本批不新增風險預算 UI 或部位計算。價格及成本的幣別說明沿 §10.3，不猜成新臺幣。

三層檢核各自負責不同輸入，不以其中一層的拒收冒充其他層已驗：

| 層 | 現行契約 |
| --- | --- |
| UI 原始成本／停損字串 | 只處理兩個既有欄位。原始空字串 `""` 送 `null`；非空必須完整符合 ASCII 十進位 `digits(.digits*)?` 或 `.digits`，可有前導零，例如 `0012.5`、`12.`、`.5`。不 trim、不允正負號、空白／換行、科學記號、Unicode 數字、貨幣或千分分隔。轉 Number 後須有限且非負，原始數字有非零位但轉成零時亦拒收，避免極小非零值被當零。先驗完整表單再送請求；自拒收不 POST，保留全部 draft 並顯示錯誤。 |
| Actual `upsertPortfolio` helper | 對三欄在 JSON 序列化前檢核，僅接受 `null`、`undefined` 或 `typeof number`、有限且非負；非法值不 fetch、不修改 payload。不能讓 `JSON.stringify` 將 NaN／Infinity 轉為 `null` 後變成合法清欄。一般 post 與 quantity 路徑不變。 |
| Raw HTTP／server | `average_cost`、`stop_price`、`risk_budget` 僅接受已解碼的 actual JSON int／float、有限且非負，或 `null`。Bool、數字字串、container、負值、非有限值及轉 Float 溢位，均在 commit 前 HTTP 422 拒收；現有持倉完整列與 JSON 保持不變，包括精確股數、Float mirror、三個欄位、note 與 updated_at，亦不新增拒收的持倉。 |

零是合法明示值，不等於 null。省略三欄仍為 `None`，沿既有 upsert 整列覆寫／清空規則；本批沒有改成 PATCH，明示 `null` 與省略都可清欄。UI 收到 API 422 或其他保存錯誤時保留 draft，busy 恢復；成功後依原流程讀回。停損不新增 `stop < cost` 或必須正值的限制，也不將 0 改成策略失效 fallback；風險資料未知時仍不提供部位數量。

這是 Float／JavaScript Number 的可信輸入 gate，不是十進位精確保存。合法小數仍可有二進位近似；server 不從已解碼的數字還原原始 JSON token，UI 的原字串 underflow 檢核與 server 的已解碼值 gate 分開。沒有修改 schema、legacy Float 或既有污染列、held／worker／risk 行動、新 Plan、價格級距、來源或 PIT。

本次採 `2026-10-03` synthetic TWSE／TPEx 使用者庫存與 memory server，不當正式持倉、官方行情或 live coverage。主契約支持範圍如下；完整命令、版本、失敗與清理收據見[開發入口](development-baseline/README.md#m3-p3-庫存價值輸入的零落盤驗證入口)及[協作紀錄](TASK_COORDINATION.md)。

| 具名操作 | 已接受的有限結果 |
| --- | --- |
| Actual 桌面 `1298×924`，TWSE NEW `1001` 股、成本 `12.5`／停損 `9.75` | 原生保存 POST 200、GET 正確。最初 requested `1365×900` 未立即生效，不把它當保存時的實際 viewport。 |
| Actual 窄版 `390×844`，TPEx NEW `1` 張、成本／停損 `0` | 原生保存 POST 200、GET 的合法零保留；這次首次零值保存已切窄版，不當兩市場桌面保存證據。 |
| Actual `390×844`，成本 `1e2`／310 位數 overflow、停損 327 字元非零 underflow | 三種原字串均由 UI 拒收、無 POST，全部 draft 與持倉完整 JSON 不變。document client／scroll width 均 375、editor 305、input 303，未觀測橫向溢出。 |
| 一次 transport fault 將原合法 POST 的成本改為 `false` | actual router 回 422；UI 保留 draft、busy 恢復、完整 JSON 不變，使用真拒收回應，不是 mock response。 |
| 新表單只填 TPEx NEW `2` 張，獨立核成本／停損原字串為 `""` | POST 200、GET 的成本／停損／risk_budget 均為 null，原非零值已清。首次 CLI 空字串操作失敗及誤按保存原值不算本次空白清欄通過。 |

兩次原生刪除 click 沒有 DELETE，未驗收本批刪除操作；兩列 NEW 只在記憶體，shutdown 後釋放，原 12 列完整 JSON 保持。本批 scoped memory fetch recorder 為 21 requests（16 GET／5 POST，20 個 200／1 個 422、外網 0），不是完整 session capture；26 個 performance resources 同 origin。Console 3 entries 為 1 React DevTools info／2 既有 Router future warnings，error 0，不稱空 console。QA 最後實際還原 `1365×900`、document 寬 1350 且無橫向溢出，原 tab 已關、自有 memory 程序／children／listeners 已核不存在，新測試磁碟產物為 0；前輪 HAR 仍在且不重試，兩者分報。

正式 DB、磁碟保存／重開、production deployment、真官方／live、完整 backend／production Vite build、既有污染的可信讀回、風險行動與所有估值、risk sizing、新 Plan、完整 M3、歷史／availability／PIT 仍未由本批驗收。後續 M3-P4 已有限接受的可信讀回及非法停損隔離見下節；兩批各依具名範圍驗收，不以輸入 gate 推定所有估值／風險行動已完成。

<a id="m3-p4-既有庫存價值可信讀回與非法停損隔離"></a>

#### M3-P4 既有庫存價值可信讀回與非法停損隔離

本批支援 M3／R2-C1 的既有庫存可信讀取；九個程式檔、必要零落盤 direct／actual API→JSON→JavaScript／UI／decision，以及下表具名操作已由統籌有限接受。三欄仍是既有 `average_cost`、`stop_price`、`risk_budget`，不改 schema 或輸入契約；新增 `portfolio_value_status`，分別記錄三欄的 `known`／`missing`／`invalid`。本批不增加 risk budget 的 UI 輸入或配置，只提供該欄 API 值及狀態。

| 讀取狀態 | 核定規則與呈現 |
| --- | --- |
| `known` | 原讀值須為 actual int／float（排除 bool），轉為 Float 後有限且非負；0 合法且保留。API 提供可信數值，成本／停損只讀區顯示數值，幣別說明沿 §10.3。 |
| `missing` | 只有 actual `None` 是未提供；API 數值為 null，成本／停損顯示「未提供」。不把空字串、非法型別或非有限值當未提供。 |
| `invalid` | 其他型別、負數、非有限值或轉 Float 溢位均為待核實；API 數值為 null、狀態保留 invalid，不回傳原始污染值，成本／停損顯示「待核實」。讀取不寫回 DB、不修原列或 updated_at。 |

只有可信成本可代入既有 unrealized_pnl 公式，原有限結果保護不變；missing／invalid 成本不生成損益。這是 Float／JavaScript Number 的可信性檢核，不宣稱十進位 exact，也不從目前讀值重建已丟失的輸入意圖。SQLite affinity 已將數字文字或 bool 轉成數值，或 NaN 轉為 NULL 時，讀取只能判目前型別與值，不能復原原始 token／意圖或冒稱已識別那些污染。

庫存停損 `known` 優先於策略停損，包含明示 0；只有 `missing` 可沿既有策略停損 fallback。`invalid` 不 fallback、不與現價比較，停損語意為 unknown，保留 `origin=portfolio_position.stop_price` 與 `reason=invalid_position_stop`。既有來源、時間與策略 gate 仍先執行；全部原 gate 通過且確有 held position 時，非法庫存停損才走專用 manual_review，使用「庫存停損待核實，先核對原記錄。」及相應核對說明，不誤稱策略衝突或提供交易建議。早期 gate 未通過時保留原原因及行為，不以本批提示蓋過來源／時間／策略限制。

前端讀回須同時核對 metadata 與值。`portfolio_value_status` 完全缺席的舊 API，raw null 顯示「未提供」，只有有限、非負 JavaScript number 可沿相容回退顯示可信數值；明示非法、缺欄或與值不一致的 metadata 一律「待核實」，不得以 metadata 存在或數字可轉換作為可信證據。成本沿既有顯示、新增既有停損的只讀數值／未提供／待核實區；risk_budget 不新增 UI input 或配置。

本次使用 `2026-10-04` synthetic TWSE／TPEx 的十四個使用者庫存列及六十個明示 fixture 日期，僅為零落盤本地驗證，不當正式持倉、官方交易日或 live coverage。390×844 是窄版 viewport、mobile=false，不是硬體手機／觸控驗收；本輪未測保存／刪除，讀回 fixture 封鎖 mutation，不併入前輪保存／刪除證據。主契約的具名支持範圍如下；必要邊界、入口與清理結果見[開發入口](development-baseline/README.md#m3-p4-庫存價值可信讀回的零落盤驗證入口)，完整命令／版本／原始 exit／hash 留 task。

| 具名操作 | 已接受的有限結果 |
| --- | --- |
| Actual 桌面 `1298×924` 的既有庫存頁 | 成本／停損讀回可核，document client／scroll width 均 1283；不把最後還原的 `1365×900` 當首次桌面尺寸。 |
| Actual 窄版 `390×844`，TWSE／TPEx 共 14 列 | 兩市場 MISSING 顯「未提供」、ZERO 的成本／停損為 0 且損益 +10,500、NORMAL 成本／停損 12.5 且損益 −2,000；NEGATIVE／INFINITY／TEXT／BLOB 顯「待核實」、損益「未提供」。Document 寬均 375，卡片 header 寬 273，未觀測橫向溢出。 |
| 原 tab 的行動→TWSE TEXT 個股研究分頁 | 實際導頁後讀得 manual_review、專用「庫存停損待核實，先核對原記錄。」；原研究總覽的來源／時間限制仍顯示，不以 synthetic 完整 decision gate 冒充真行情或來源准入。首次 offscreen click exit 0 沒有導頁，未驗收，捲至可見並重新讀取元素後才接受。 |

Actual HTTP 的十四列與十四個完整 decisions 已核三態、0 優先、missing-only fallback 與 invalid 隔離；讀取前後全十四列 SQL（全部欄位、note、updated_at 與三欄 typeof）雜湊一致，無 mutation。必要邊界及舊 API metadata 缺席／raw null、明示壞 metadata 的相容結果另由可重建 formatter／SSR 驗證，不冒充 live API 情境。

原 QA tab `c0cd04e4-4539-4d73-a36d-b80f71a75328` 首次 snapshot／eval 均 runtime_unavailable、exit 1，沿同 tab 原生 focus 後恢復，未另建 tab。Scoped memory fetch 只記 3 個 GET／200（TWSE TEXT stocks、portfolio、actions），mutation 0／外網空；7 個 performance resources 為 owned，同次 Orca console 回 `messages=[]`，僅支持這個擷取範圍，不稱完整 session／所有 console 空。未使用會落 HAR 的 capture。最後 actual viewport 還原 `1365×900`、document 寬均 1350，原 tab close exit 0／list 空；兩個 owned memory serve／children／listeners 已核不存在，測試及清理分報成功，新增測試磁碟產物／殘留 0，舊 HAR／其他 blocked／occupied 資源未動。

本節保留 P4 信任讀回與非法庫存停損隔離的原有限驗收，不修污染或遺失 intent，不外推所有估值／風險行動。後續 [M3-P5](#m3-p5-可信庫存股數與既有估值持倉判定一致) 已有限接受股數／既有估值／held 一致接線；兩批各依具名範圍驗收，不從可信股數推定金融估值 exact 或行情信任已驗。

<a id="m3-p5-可信庫存股數與既有估值持倉判定一致"></a>

#### M3-P5 可信庫存股數與既有估值／持倉判定一致

本批支援 M3／R2-C1；十檔程式、必要零落盤 SQLite→router→JSON→JavaScript／UI 及下表具名操作已由統籌有限接受。既有 consumer 共用 `trusted_position_shares`：`shares_integer` 非 NULL 時，只接受 actual int（排除 bool）且在 `0..9,223,372,036,854,775,807`；非法新欄不 fallback。新欄 NULL 才可取有限、非負、安全整數的 legacy int／float，上限 `9,007,199,254,740,991`。不從 Float 還原原始捨入值，不寫回污染記錄或 note／updated_at；schema、輸入與 M3-P2 磁碟契約保留。

| 記錄與可信總股數 | `position_quantity_status`／held |
| --- | --- |
| 有記錄、可信正整數（包含 int64 大數） | `known`／true |
| 有記錄、可信零 | `known`／false |
| 有記錄、總股數無法核實 | `unknown`／null；保留記錄，不當作 0／無持倉 |
| 沒有持倉記錄 | decision 為 `absent`／false；portfolio 不造空持倉列 |

API 相容 `shares` 改用可信總股數：不超 safe 上限時提供 numeric，其餘回 null，不能再讀取互相衝突的 raw Float。既有 `shares_exact`、`quantity` 精確字串與張／零股拆分保留；大數顯示仍用完整字串，不依賴 `quantity` 的 Number 相容欄位。例 integer=1000／Float=0 仍為 1000 股、held=true；integer=0／Float=1000 則為零、held=false。

`valuation_status` 分別記錄 `market_value` 與 `unrealized_pnl`，不能從其中一項推定另一項：

| 狀態 | 計算與畫面 |
| --- | --- |
| `quantity_unknown` | 股數未知時兩項均 null，顯示「股數待核實」。 |
| `precision_unsupported` | 可信總股數超過 safe 上限時兩項均 null，顯示「估值精度待支援」；exact int64 呈現與 held=true 保留。 |
| `known` | safe 股數的市值沿既有 close × shares；close 須 actual int／float 且有限，乘積須有限。損益另須 M3-P4 成本為 known，且市值 − 成本 × shares 有限。畫面保留零、正損益加號與負值。 |
| `missing` | safe 股數下沒有 bar／close=None，市值為 null；成本 missing 時損益為 null。成本 known 時，損益沿市值的 missing 狀態。顯示「未提供」。 |
| `invalid` | safe 股數下型別／非有限 close、非有限計算結果，或成本 invalid 的損益，均 null，顯示「待核實」。成本 missing／invalid 的損益狀態優先於市值狀態。 |

known 只表示本批有限算式可計算，不等於行情來源、日期、價格合法性或 tick 已通過研究 gate；本節保留 M3-P5 原有限驗收結果。現行庫存收盤隔離／本地試算狀態由已有限接受的 [M3-P6a](#m3-p6a-庫存收盤數值隔離與本地試算可檢視)負責，不倒改本批歷史支持範圍。不宣稱 Decimal 或精確金融估值。前端只在 explicit known 與有限 number 一致時顯數字；狀態存在但 malformed／矛盾時顯「待核實」，不改用 raw 值救回。只有舊 API 未提供狀態欄，才沿有限 number／null 的相容顯示。

未知持倉保留為行動候選，在首頁、行動列表及真正的研究詳情 `ActionDetailPanel` 顯示「股數待核實」badge。原 source／time／strategy gates 優先：未通過仍保留原 data_insufficient 說明；全通過後 unknown 才為 manual_review，專用指示「庫存股數待核實，先核對原記錄。」，不提供 primary levels。P4 可信正數的非法停損隔離仍保留。

`held_only` 只收 held=true；未知與可信零不混入該篩選。`held_unknown` 與 held 採相同的各端點範圍：無 state 的 actions 使用全部 filtered IDs，有 state 時使用全部 filtered rows，dashboard 使用 compact first page；原 `scope` 字串保留，不把目前頁或 compact count 宣稱全域，也不報被篩掉資料的數量。優先集合先列可信持有、未知記錄，再沿原候選順序及去重，recorded zero 保留；無 state 路徑在選頁後才建 decision；有 state 則沿原 filtered universe 先建 decision，再篩 state／計數／分頁。

本次採 `2026-10-04` synthetic TWSE／TPEx 十六列庫存、兩個無持倉 metadata 與明示 fixture 日期，不當正式庫存、官方行情／日曆或 live coverage。

| 具名操作 | 已接受的有限結果 |
| --- | --- |
| Actual 桌面 `1298×924` 與 `390×844`（mobile=false）庫存 | 十六列 1000／zero／unknown／ODD／MAX 精確呈現，正常市值 0／10,500、損益 +500 與大數 unsupported 正確；document client／scroll width 分別均為 1283／375，窄版數量 head 273，未觀測橫向溢出。 |
| 行動狀態篩選及實際可見 click：TWSE BADINT | 四個完整 unknown 為 manual_review；研究詳情顯專用 strong 指示及 badge，primary levels 為空。 |
| TPEx GATEFAIL 的實際研究詳情及首頁 | 兩個 gate 未滿 unknown 仍 data_insufficient；原 heading／strong 說明保留並有 badge、levels 空。首頁保留不完整 unknown 並去重。 |
| 詳情 badge 退修後的桌面／390px | 真正 ActionDetailPanel 的完整／不完整兩 profile 均通過；第一版 ProductActionCard SSR 不當詳情證據。 |

原 tab 首次 snapshot／eval runtime_unavailable、exit 1；沿同 tab 原生 focus 恢復。工具 help、未 quote 的 PowerShell ref／JavaScript 引號失敗分報；詳情 badge 遺漏則是產品退修，補正後才有限接受。Scoped recorder 只涵蓋前版 8 GET／200、外網／mutation 空；最終詳情 performance 3 個 owned resources，不當完整 session capture。QA 最後還原 actual 1365×900、document 寬均 1350，原 tab 已關；自有程序／children／listeners 已核不存在，新測試落盤／殘留 0。最終 console 讀取六則為兩個 React DevTools info 與四個既有 Router warnings，無該讀取 error，不稱無 warning 或完整 capture。

本批未驗真正磁碟保存／重開、正式 DB／migration、真官方／live、production deployment／Vite build、完整 backend、行情來源／日期／價格可信性、所有估值／風險行動、risk sizing、新 Plan、完整 M3／PIT；不新增個人風險額度輸入。必要磁碟驗收不能以 memory 取代。重建入口與精確證據範圍見[開發入口](development-baseline/README.md#m3-p5-可信股數與估值持倉判定的零落盤驗證入口)，後續庫存本地數值隔離／試算的有限範圍見 [M3-P6a](#m3-p6a-庫存收盤數值隔離與本地試算可檢視)。

<a id="m3-p6a-庫存收盤數值隔離與本地試算可檢視"></a>

#### M3-P6a 庫存收盤數值隔離與本地試算可檢視

本批支援 M3／R2-C1；七檔實作、修正版零落盤驗證、actual HTTP／JSON／Portfolio SSR 及下表具名桌面／390px 操作已由統籌有限接受。沿 M3-P2／P5 可信股數與 P4 成本讀回，只處理庫存收盤數值、記錄欄位及可收合的本地試算。數值可計算與來源／日期證據分開；本批來源、日期證據固定為 `unverified`，不借 M1 selected 原件或用途 gate 通過，不新增來源准入、PIT 或完整 M3 完成度。

庫存端點以專用 SQL 投影讀取最新儲存行情，按原儲存 `trading_date DESC`、`id DESC` 選一列，只取必要 `close`、`trading_date`、`source`、`data_as_of`、`collected_at`；`id` 僅作同日排序。先取得未經價格 cast 的讀值，再分類／投影；不載入整個 MarketBar ORM，不改共用 `bar_dict`。所選列不合格時保留該列的 missing／invalid 狀態，不另找較早合法價格替代；此排序不證行情日曆、截止或真正最新可得資料。

| 本地讀值 | API 狀態與用途 |
| --- | --- |
| `close` 為 actual int／float（排除 bool）、有限且大於 0 | `known`；只證當次讀值可作有限數值試算，不稱可信行情。 |
| 沒有行情列，或 `close` 為 actual None | `missing`，值為 null；不補 0。 |
| 其他型別、零、負數、非有限值或轉換溢位 | `invalid`，價格投影為 null；不回傳原污染 token，也不修原列。 |
| `source`、`trading_date`、`data_as_of`、`collected_at` | 分別記錄 `known`／`missing`／`invalid`；known 只表示本地欄位符合自身語法／型別要求，缺席與非法不混用。日期語法合格不證交易日、截止、發布、first availability 或 PIT；來源字串不充來源准入。 |

`portfolio_quote` 分別提供 close／close_status、recorded／record_status，以及固定 `source_verification=unverified`／`date_verification=unverified`；`latest_bar` 只提供必要投影欄位，狀態須與值一致。Datetime 記錄字串最多 **64 字元**，source 最多 **120 字元**；拒絕 C0（U+0000–U+001F）、DEL（U+007F）及無法合法 UTF-8 編碼的字串，source 也拒空白字串，不泛稱拒絕所有 Unicode 控制類別，不截斷、不正規化救回。日期須為有效 `YYYY-MM-DD`；datetime 須為有效曆日及帶秒的記錄時間，時／偏移時小於 24，分／秒及偏移分／秒小於 60，Python／JavaScript 皆拒非法 `+01:99`，不補時區。`data_as_of` 只核記錄時間語法，畫面標「記錄資料時間」，不稱資料截止或可得時間。讀取不更新任何行情／庫存欄、note 或 updated_at；SQLite affinity 已轉換或遺失的原始 token／輸入意圖不從讀值復原。

`valuation_status` 仍分別描述市值及未實現損益；兩值都是本地 Float／JavaScript Number 試算，不是行情驗證結果或精確金額：

| 條件與優先序 | 市值／未實現損益 |
| --- | --- |
| 股數未知 | 兩項皆 null／`quantity_unknown`，保留「股數待核實」。 |
| 可信股數超 safe 上限 | 兩項皆 null／`precision_unsupported`，保留「估值精度待支援」及 exact 股數／held。 |
| safe 股數、close known 且 close × shares 有限 | 市值為 `local_estimate`；零股的試算 0 仍是使用未核實行情的本地試算。 |
| safe 股數、close missing／invalid，或乘積溢位／非有限 | 市值分別為 null／`missing` 或 null／`invalid`。 |
| safe 股數、成本 missing／invalid | 損益分別為 null／`missing` 或 null／`invalid`；成本狀態優先於 close／市值狀態。 |
| safe 股數、成本 known | close／市值不可試算時沿相應 missing／invalid；市值 − 成本 × shares 有限才為 `local_estimate`，否則為 null／invalid。 |

現行 `portfolio_quote`／`local_estimate` 回應的日常庫存卡不顯示未核實的 close、市值或損益數字。可試算時顯示「行情待核實」；close missing／invalid 分別為「未提供行情」／「行情數值待核實」，估值 missing／invalid 分別沿「未提供」／「待核實」，股數未知與超 safe 沿上表提示。可信數量、成本與停損仍可正常呈現，不以本批行情隔離蓋掉既有股數／成本狀態或 decision 的早期 gate。

每卡提供預設收合的 **「核對本地行情與試算」**。展開後，只有 `portfolio_quote`／本地核對 metadata 與實際值嚴格一致，才顯示可核對的 close、來源／資料日期／記錄資料時間／收集時間記錄，以及市值／損益兩項 local_estimate。明示 **「本地記錄；來源／日期待核實」** 與 **「本地試算，行情來源／日期尚未核實」**；行情 metadata 缺席、非法或矛盾不以 raw 值救回，明示 metadata 不得繞過單欄矛盾。各欄 missing／invalid 必須如實呈現，幣別與單位沿 §10.4，不猜成新臺幣。

只有估值 metadata **完全 undefined** 的舊 API，日常估值仍保留原有限 numeric／null 相容顯示；null、部分缺欄或明示 malformed／矛盾的 metadata 不屬此回退。舊 API 數字可顯示不證行情已核實；此相容與現行 local_estimate 隔離分開，不放寬 `portfolio_quote`／本地核對欄位的嚴格檢核。

不稱「最近收盤」「現價」「官方」或「可信行情」，不把合格來源字串／日期改寫成 admission、cutoff 或 availability 證據。本批不改原 decision／source／time／tick／stop gates、新 Plan、input／save／delete；不作 Decimal exact、風險行動或金融估值完整驗收。

本次使用 `2026-10-04` synthetic TWSE／TPEx **20 筆庫存／18 筆行情**，不是正式庫存、官方行情／交易日或來源證據。Actual Response.json／真正 PortfolioSubsection 的二十列已核；portfolio_positions／market_bars 兩整表全欄、全部 typeof、note、updated_at 在 HTTP 與產品操作前後相同，讀取 mutation 0。必要入口、版本及精確驗證範圍見[開發入口](development-baseline/README.md#m3-p6a-庫存本地行情與試算的零落盤驗證入口)，命令／exit／SQL hash 留 task。

| 具名操作 | 已接受的有限結果 |
| --- | --- |
| 真正 full App 的 `/actions` 上 Portfolio，桌面 `1298×924` | 二十張卡預設收合；document client／scroll width 均 1283、card 589。TWSE NORMAL／BADPRICE／MISSINGBAR／DIRTYDATE／METABAD／POISON／BADQ／HUGEQ／ZEROQ 經 focus 後實際 Enter 展開及收回；10.5／10,500／+500 與合法零試算正確，缺席／非法／股數未知／unsupported 不造 0。 |
| `390×844`（mobile=false）的同一 Portfolio | TPEx NORMAL／POISON／BADQ／HUGEQ／OVERFLOW 以實際 Enter 展開及收回；document 寬均 375、card 303、detail 273。120 字來源、64 字時間及 309 位 Float 本地 close 可核對，未觀測橫向溢出；不稱硬體手機／觸控驗收。 |

初次 snapshot 的 runtime_unavailable、最後 inline JavaScript 的 PowerShell 引號 eval 失敗均分報；沿同 tab 原生恢復、改 here-string 單引號 probe 後才成功，不重建 tab、不重跑已驗操作、未開 HAR。Scoped memory fetch recorder 只涵蓋 1 GET／200、external／mutation 空，不是完整 capture；6 個 owned performance resources 含原 actions 的 **2 GET／500**，本次 console 讀 `messages=[]` 不表示整個 session 無 warnings。QA tab、viewport、自有程序／children／listeners 已核實清理，新測試磁碟產物／附件／暫存／殘留 0，舊 excluded 資源未動。

P6a 驗收時 `decision._prepare_decision_context` 仍載入完整 MarketBar；synthetic `not-a-date` 被 Date processor 拒絕，`/api/actions?limit=20` 兩次 500、頁面原資料載入 error，Portfolio 仍可用。P6a 有限接受不包含完整 ActionsPage 或行動端點回歸通過；原失敗保留，後續清單隔離的現行有限範圍見下列 P6b，不倒改 P6a 驗收。行情來源／日期／availability 證據、真官方／live、M1 正向 file gate、正式 DB／真正磁碟重開、production／完整 backend／Vite build、Decimal exact、PIT、新 Plan、保存／刪除 UI 及完整 M3 未驗；沒有授權 tiny 唯讀行情 artifact，不以 memory patch 降低 file gate。下一步見[ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)，freeze／索引／commit／merge 見[協作紀錄](TASK_COORDINATION.md)。

<a id="m3-p6b-actions-清單逐列行情讀回污染隔離"></a>

#### M3-P6b Actions 清單逐列行情讀回污染隔離

本批支援 M3／R2-C2；八檔實作、必要零落盤／actual HTTP／SSR 與下表具名 Actions 清單操作已由統籌有限接受。解除單列行情的 Date／DateTime／價格 processor 污染使整份清單失敗的缺口；只交付清單搜尋／清除、state、分頁與逐列狀態。`market_read.status=known` 只表示必要讀值合格，不表示來源准入、官方日期、用途、availability 或 PIT 已驗證，也不把原 source／time／strategy gates 改成語法檢核。

decision 以未定型 SQL 讀八欄 `id`、`instrument_id`、`trading_date`、`close`、`adj_close`、`source`、`is_suspended`、`raw_payload_id`，避免載入完整 MarketBar。核心欄位與可選比較／追溯欄位分開：

| 讀值 | 本批處置 |
| --- | --- |
| `trading_date` | 必須為有效且完整的 `YYYY-MM-DD` 字串；無法定位日期者不假定過去或未來。 |
| `close` | 只接受 actual int／float（排除 bool）、有限且大於 0；不以 cast 救回 TEXT／BLOB、零、負數或非有限值。 |
| `source` | 非空、非純空白／BOM，最多 120 字元，可合法 UTF-8 編碼，拒 C0 與 DEL；字串合格不證來源身分或用途准入。 |
| `is_suspended` | 原儲存讀值必須為 actual int 的 0／1；其他值為 invalid，不靠 truthiness 改成合法旗標。 |
| `adj_close` | 只供相鄰價格 basis 比較；無效時漲跌待核實，不單憑此欄使合格核心 close 無法呈現。比率須有限且為正，差額／百分比須有限；UI 另核百分比乘 100 仍有限。 |
| `raw_payload_id` | 非 actual 正整數時投影為 null，不冒充 raw 證據；該欄存在也不等於 provenance gate 通過。 |

上述 gate 分類的是 SQLite affinity 已處理的讀值；儲存前的 bool／數字文字可能已轉為 actual numeric 而成為 known，不能由目前型別恢復原始 token／意圖，不修 DB。known 亦不證合法 tick、完整 OHLC、真實停牌狀態或用途准入。

按原儲存 `trading_date DESC`、`id DESC` 選候選，合法 future date 依既有 `as_of` 排除，先套最多 120 列再驗值，不以刪除壞列補較早行情。該標的任一列日期無法定位時，即使 raw 文字排序位於 cutoff／120 列窗口之外，仍保留該列身分並使最新行情 fail closed；不把非法字串作 lexical future 排除，也不 fallback 到較早合法 close。Session cache 保留此結果。歷史合格筆數只計核心欄位有效的列，不把全部 SQL 列數當成已驗來源或完整交易日窗口。

`market_read` 提供 `known`／`invalid`／`missing` 與 `invalid_fields`；invalid 候選仍保留標的／候選及可用 evidence refs，價格日期、close 與漲跌投影為 null，`primary_levels={}`，不修原列或補 0。不存在行情則為 missing。TAIEX 交易日所需 MarketBar 日期／來源投影是本批必要依賴；原 RawPayload、official run、MI_INDEX 原件檔案／parser／provenance gate 保留，未讀欄位不再觸發無關 processor。漲跌仍須原已核實的相鄰 session、核心行情、停牌與同 basis 條件，不由兩個相鄰資料列推定。

原來源／時間／策略 gates 優先，未知股數與非法停損的既有條件保留；不改 candidate 順序、去重、state／q／held_only、分頁與 `held_unknown` 的 scope。無 state 仍選頁後建立 decision，有 state 仍先在完整 filtered universe 建 decision，再篩 state／計數／分頁；dashboard 仍是 compact first page 範圍，不宣稱全域數量。

`CompactActionCard` 明示讀值契約時，只在 known、空 `invalid_fields` 與正有限 numeric price 一致下顯數字。invalid／missing、不支援或 partial status、malformed／矛盾狀態及非法價格均顯「待核實」「漲跌待核實」及「策略判斷資料待補」；invalid 顯「行情讀值無效，先核對原記錄。」，missing 顯「尚無行情記錄。」。只有 `market_read` 完全 undefined 的舊 API 才沿原有限 number 相容，不以 malformed 新契約 fallback raw 值。合法極大有限價格在卡內換行，不因字串長度改為 unsupported；漲跌的顯示 overflow 仍待核實。

本次使用 **2026-10-04 synthetic TWSE／TPEx 24 庫存、每市場 12 symbols、60 個明示 fixture 日期**及 complete run／signals，不是官方行情、日曆、來源准入或正式持倉。

| 具名操作 | 已接受的有限結果 |
| --- | --- |
| 桌面 `1298×924` Actions 清單 | 初頁 20 卡／24 total；B-CLOSE 搜尋 2、清除 20；data_insufficient 12、manual_review 4，其中 unknown 2。實際 focus＋Enter 下一頁 4／unknown 2，再回首頁 20。document 寬均 1283、card 294，未觀測橫向溢出。 |
| `390×844`（mobile=false）Actions 清單 | C-DATE 搜尋 2、清除、state 12／manual 4 與實際 Enter 分頁同範圍；document 寬均 375、card 337，未觀測橫向溢出，不稱實體手機／觸控驗收。 |
| 逐列隔離與價格 | B-CLOSE／C-DATE 等污染價格待核實；H-MISSING 有無行情記錄說明；G-ADJUST／K-HISTORY 漲跌待核實；D-METADATA／正常 close 10.5 可見。合法 future 5000 未混入 cutoff；股數 unknown 保留，未造 primary levels。 |
| 必要巨大值補驗的兩尺寸預設清單 | L-FUTURE 截止日 close／adj_close 為 `1e308`，翌日 5000 仍排除；TPEx 卡片完整 411 字元與原 Intl price 相符。桌面／390px card 寬 294／337、price box 195／238，card／price box scroll width 均等於自身寬，document 寬仍均 1283／375，漲跌待核實。補驗不另宣稱搜尋／Enter 通過。 |
| 正常卡片原導航 | 真正 Enter `A-NORMAL` 經原 `/actions/TWSE/A-NORMAL` 進 StockPage，`/api/stocks/TWSE/A-NORMAL` 為 200；M1 總覽仍拒 fixture、0／60 合格與研究資料待補，原 file／source gate 未降。污染卡片的整個詳情路徑未點、未驗。 |

初操作 instance 的 scoped fetch **13 GET／200**、performance **17 owned resources／200**；巨大值補驗另 instance 為 **2 GET／200**、**6 owned resources／200**，各自 external／mutation 空，非完整 session capture。既有搜尋／state／分頁／正常導航仍有效；工具失敗與 ref click 未動分報，真正 Enter 後才接受，補驗 Enter 無新 GET 不算新操作。初 console limit 50 為空，final 同範圍有 **React DevTools info 1／既有 Router warnings 2**，不稱全域無 warning。兩 instances 各自在自身 HTTP／UI／pre-shutdown 保持 24 庫存／1,382 行情全欄＋typeof／note／updated_at 同 digest、read mutation 0，不跨 instance 比 hash。Final viewport 已還原 1365×900／寬均 1350、20 卡／details 全收合，owned tab 已關、兩 serve final exit 0，PIDs／children／8777、8778 listeners 已獨立核空；新增測試產物／附件／暫存／殘留 0，舊 excluded 資源未動。

污染卡片進 StockPage 的 typed max-date／完整 120 bars／`bar_dict` 路徑仍待驗；SSR 的 action detail panel 不等於這條真實路徑。完整 ActionsPage、行情來源／日期／availability、真官方／live、M1 正向 filesystem gate、正式 DB／磁碟重開、完整 backend／production Vite build、Decimal exact、新 Plan、完整 M3／PIT 未驗。必要磁碟或原件驗收不以 memory fixture 取代；下一具名候選 P6c 由 [ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)負責，重建入口見[開發入口](development-baseline/README.md#m3-p6b-actions-清單行情讀回的零落盤驗證入口)。

### 10.4 數值表格、單位與空白

同一張表的單位只在表題、副標、caption 或緊鄰說明出現一次，例如「單位：張」；欄名與數值格不逐格重複「張」「股」「元」或百分號。價格在 API 沒有 currency 時統一說「各標的報價幣別的元」，指數說「點」，不得猜成新臺幣。數值格只顯示數字，方向值明示 `+`／`-`。缺值不寫 0、`N/A`、`--`、「無資料」或英文 placeholder，改為空白，並在表格外寫「空白表示來源未提供」；若原因是來源或單位未核實，須另行具體說明。

若既有畫面呈現成交金額，須依 API 的 `turnover_status` 決定數值格：`available` 且值為來源明確的 `0` 才顯示 `0`；`unavailable` 或 `unknown` 即使底層 `turnover=0` 也留空。缺失／無效可在表格外說「成交金額未取得」，舊零未核實則說「成交金額待核實」，不把兩者合稱來源真的零；原因碼與數值狀態須一致。這是顯示契約，不新增成交額 UI；底層保存與 flow 計算規則見 [資料來源：P2+](DATA_SOURCES.md#r1-a2-p2-成交金額可得狀態有限接受)。tooltip、等效資料表與表外說明須同步使用相同口徑。

## 11. 現行信心語意與下一版 AI、題材及短線資金文案

| 資訊 | 允許 | 禁止 |
| --- | --- | --- |
| 完整度／規則狀態 | 「突破條件資料完整」「此條件已符合」 | 推論勝率或保證方向。 |
| legacy confidence=0.75 | 僅在已知 v1 1.0.0 且值為 0.75 時，技術層標「舊版固定規則值（未經機率校準；非勝率）」 | 顯示 75% 勝率或信任 evidence 自稱 prediction。 |
| null／unknown numeric | 「未校準；非預測勝率」 | 補 0%、百分比或機率。 |
| 模型機率 | 驗證後附事件、期間、資料日、樣本與校準資訊 | 無期間的上漲機率或模型自評。 |
| AI 摘要／事件影響 | 有引用的 AI 摘要；影響推論附方法與 unknown | 冒充原文、篇數當利多。 |
| 題材關聯 | 官方產業／經核實題材／待核實候選 | 模型標籤冒充官方分類。 |
| 三大法人 | 外資、投信、自營商分開顯示；「外資」是官方外資及陸資合計欄位的日常簡稱 | 把廣義券商、分點或「主力」併成第四類，或把自營商擴稱所有券商交易。 |
| 當沖／主力進出／券商／分點 | 現有官方逐檔查詢入口須明說尚未整合；有可驗證資料且口徑版本化後，分點反轉須交代 N、X 與定義。待做欄位與口徑見 [個股頁 §8](STOCK_RESEARCH_PAGE.md#8-籌碼三部分後續待做)。 | 外資當沖、未定義主力排行、身分或未來行為推論，以及把人工入口說成已接資料集。 |
| 規則參考價 | 觸發區間、失效價、不追價上限 | AI 精準買點或保證目標。 |

風險預算未知時寫「尚未設定風險預算，暫不提供部位數量」。不交易、到期、未觸發、未成交與模擬追蹤必須分開。

## 12. 中文原因碼對照

未知 code 一律顯示「研究條件需要人工核對」，原值只留稽核層。不同策略的 code 保留各自範圍。

| 原始值 | 日常文案／處置 |
| --- | --- |
| `passed`／`rejected`／`data_incomplete`／`observation`／`conditional` | 依序為「此研究條件已符合」「尚未成立」「資料待補」「條件尚未成立，持續觀察」「符合條件後可研究進場」；observation 不是缺資料，conditional 須附 T+1。 |
| `active`、`target_1_hit`、`target_2_hit`、`invalidated`、`expired`、`incomparable`、`settled` | 只在 tracking／歷史顯示中文狀態，不替代今日結論。 |
| `invalid_levels` | 「研究價位無法驗證」；隱藏所有不合法價位。 |
| `required inputs complete` | 稽核敘述；日常改成「突破／回踩條件資料完整」。 |
| `prior_20_highs_missing_or_invalid` | 前 20 個交易日高點資料待補。 |
| `prior_20_volumes_missing_or_invalid` | 前 20 個交易日成交量資料待補。 |
| `close_missing_or_non_finite`／`volume_missing_or_non_finite` | 最近收盤／當日成交量資料待補；不補 0。 |
| `ma20_missing_or_non_finite`／`ma60_missing_or_non_finite` | 20／60 日均線資料待補。 |
| `group_excess_return_20d_missing_or_non_finite` | 近 20 日相對大盤資料待補，不把 unknown 當中性。 |
| `institutional_flow_to_turnover_ratio_5d_missing_or_non_finite` | 近 5 日法人籌碼資料待補。 |
| `margin_balance_change_ratio_5d_missing_or_non_finite` | 近 5 日融資變化資料待補。 |
| `close_or_volume_must_be_positive`／`price_and_volume_inputs_must_be_positive` | 價格、均線或成交量異常，列資料待補，不解讀方向。 |
| `bar_count_missing_or_invalid`／`bar_count_must_be_a_non_negative_integer` | 歷史交易日數資料／格式待核實。 |
| `history_under_60_bars` | 近 60 個交易日行情不足，pullback 不可判定。 |
| `close_not_above_prior_20_day_high`／`volume_ratio_below_1_20` | 收盤尚未突破／量能未達 1.20；是規則未通過，不是看空。 |
| `group_relative_strength_not_positive` | 已核實群組未呈相對大盤正向；不顯示 raw group ID。 |
| `institutional_flow_materially_adverse`／`margin_financing_increase_abnormal` | 法人／融資未達規則要求；中性描述，不作預測。 |
| `ma20_not_above_ma60`／`close_below_ma60` | MA20 尚未高於 MA60／收盤低於 MA60。 |
| `close_outside_ma20_support_zone`／`pullback_volume_ratio_outside_range` | 收盤不在支撐區／回踩量比不在規則區間。 |
| `effective_group_score_missing_or_under_minimum_members` | 群組成員或相對大盤資料不足；不能顯示為 0 分。 |
| `signal_day_suspended` | 訊號日交易狀態不適合計算；隱藏動作與價位。 |
| `unsupported_instrument_type` | 商品類型暫不適用一般研究規則。 |
| `unsupported_or_missing_etf_category`／`etf_category_is_only_valid_for_etf` | ETF／商品分類待核實，不產生一般動作。 |
| `etf_category_excluded_from_actionable_signals:bond`／`etf_category_excluded_from_actionable_signals:leveraged`／`etf_category_excluded_from_actionable_signals:inverse` | 債券／槓桿／反向 ETF 可收集與分榜，暫不產生一般 v1 動作。 |
| `ipo_history_under_20_bars`／`ipo_observation_only_under_60_bars` | IPO 未滿 20 日不動作；20–59 日只觀察。 |
| `unsupported_entry_type` | 進場類型無法驗證；隱藏價位。 |
| `entry_price_must_be_finite_and_positive`／`invalid_price_must_be_finite_and_positive`／`invalid_price_must_be_below_entry` | 進場或失效價無法驗證；隱藏相關價位、目標與 RR。 |
| `target_1_must_be_finite_and_positive`／`target_1_must_exceed_entry` | 第一目標無法驗證；隱藏 target 與 RR。 |
| `target_2_must_be_finite_and_positive_when_present`／`target_2_must_exceed_target_1` | 第二目標無法驗證；只隱藏第二目標，第一目標仍獨立檢查。 |
| `minimum_first_target_risk_reward_must_be_finite_and_positive` | RR 門檻設定待核實；隱藏 RR 與條件價位包。 |
| `target_1_risk_reward_below_minimum` | 第一目標 RR 未達門檻，不形成 conditional；不是績效結論。 |
| `unsupported_current_status`／`unsupported_next_status`／`illegal_signal_status_transition` | 追蹤狀態無法驗證；日常顯示「需人工判讀」。 |
