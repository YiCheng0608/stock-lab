# Round14 全站前端 UX review（已 review）

更新：2026-09-13。這是 Round14 前端 UX 的有限 review 與驗收入口，不是整站資料或 ROADMAP 完成聲明。本輪只調整既有前端資訊架構、文案與顯示換算；不新增 API `units`、後端／worker／DB 工程、來源採購或付費服務。[Wantgoo App](https://www.wantgoo.com/app) 只作報價、技術、法人資訊分區的版面參考，不複製資料、文案或資產。

## 1. 逐頁問題、改法與待驗

| 頁面／流程 | 已確認問題 | Round14 改法 | 統籌驗收重點 |
| --- | --- | --- | --- |
| 全站導覽與列表 | 卡片同時承載過多診斷；操作詞不一致；方向可能只靠顏色。 | 卡片只留辨識資訊、一個結論、一至兩個核心數字、資料日期與詳情入口；統一「上一頁／下一頁／儲存／庫存」；台股紅漲綠跌並同時顯示正負號或文字。 | 鍵盤、focus、寬／窄版、載入／錯誤／空資料、列表到詳情均可操作。 |
| 今日總覽、研究清單與行動／庫存 | 摘要、證據與 raw 診斷混在同一視覺層級。 | 首屏先呈現結論與關鍵數字；證據／來源其次；raw 診斷改為詳情或可展開區。 | 不遺失既有來源、時間、風險與缺資料理由；儲存／庫存流程回歸。 |
| 新聞列表／詳情 | 列表容易塞入全文與時間診斷，事件與新聞語意可能混用。 | 列表只顯示事件辨識、摘要、來源與資料日期；全文、時間衝突和 raw evidence 留在詳情。 | Event／News 可辨識；未知發布時間不被補成事件時間。 |
| 族群列表／詳情 | 共用股票表格會把不存在的 action 欄位錯顯為「尚無研究動作／策略判斷資料：待補」；日期讀錯層；相對報酬鍵名匿名；分頁未作用；正式資料另有舊產業 membership 錯分類。 | 缺席欄位視為未評估；日期讀 `meta.data_as_of`；相對指標具名；族群品質文案限縮；恢復分頁。官方產業排行與衍生研究條件暫標「既有族群關聯待重新核實」；卡片／詳情保留中文 `display_name` 並加「（既有分類）」與待核實 badge，原始英文 membership name／ID 只在資料說明展開。 | 真實 payload、候選 identity、正負方向、日期與跨頁一致；不得把 warning 或中文 display name 當成分類已修復。 |
| 個股列表／詳情 | 成交量仍以股呈現；籌碼單位文案未決；大量診斷擠壓主要研究結論。 | 依下表把來源明確的股數換算為張；結論→關鍵數字→證據／來源→raw 診斷；詳細表格保留可追溯原值。 | 圖表、提示、等效表格與籌碼卡一致；缺 bar／chip、unknown／mixed source 均 fail closed。 |
| 研究／系統／詞彙頁 | 工程狀態與產品任務同權，使用者難以找到下一步。 | 保留可追溯性，但把 coverage、健康狀態與詞彙解釋置於次要層；主要入口明示可採取動作。 | 不隱藏故障、來源、資料時間或限制；深連結與返回流程正常。 |

## 2. 已發現的市場別產業分類缺陷

這是真資料分類錯誤，不是英文翻譯。R15 已按兩市場官方 current 表更正 R14 的初步推測：shared code 沒有異義 collision，TWSE／TPEx `22` 都是生技醫療；差異在市場專屬、停用及特殊碼。完整表、官方版本／頁碼、raw API hashes、日期邊界與隔離修復矩陣見 [產業分類契約](INDUSTRY_CLASSIFICATION.md)。

| 核對項 | 2026-09-13 唯讀結果 | 產品／工程界線 |
| --- | --- | --- |
| 3176 | 正式 DB raw `exchange=TPEx`、`industry=22`，唯一有效 official membership 卻是 `Industry · Shipping`。 | 顯示「既有族群關聯待重新核實」；族群中文 `display_name` 加「（既有分類）」與待核實 badge，原始英文 membership name／ID 僅在資料說明展開。 |
| TPEx 影響 | 代碼 22 的 98 檔全掛 Shipping、0 檔掛 current Biotechnology；全 TPEx 有效產業 membership 890 筆中 706 筆與官方表不符。 | current 表不含已於 2023-07-03 停用的 18／34；80 是管理股票特殊碼，不作一般產業排行。 |
| R14 程式基線 | TPEx 22 已對到 `Biotechnology`，但 TPEx 18 仍被當 current ordinary industry；正式 DB 尚未依正確表重建。 | 單一正確案例或新 mapping 不等於舊資料、scores 或候選已修復。 |
| TWSE 影響 | 基線把 18、20–31 錯移，缺 19；32 實為 TWSE current unsupported，不是缺少分類。統籌以獨立表重現 1,094 筆中 845 筆 wrong-or-unsupported（含特殊 91 TDR）。 | 先修完整 mapping／負面測試，再只在隔離副本驗 memberships 與衍生影響；不直接全市場重跑正式 DB。 |

核查 snapshot：`data/stock.db` SHA-256 `74A34389DBFA65429D27EA41BC9DECA2A132808F10093E2FFDE98665D96232D6`；`backend/app/taxonomy.py` `35CA3ADC9E997B8E09CAE2F3963763DB010152009D6061CB8B9818E2DC26CB50`；`backend/worker/pipeline.py` `C78D2AF655607F07F798213337B5DB9BC4914462F06A697D1CDC27FB8319018C`。查詢使用 immutable read-only DB；這些 hash 只凍結核查證據，不宣稱分類已修復。

OHLCV、成交量／籌碼張數與新聞內容不因這項分類缺陷改判為失效；但以錯 membership 產生的產業排行、候選、關聯與研究條件不得採信。R15 的 current 修復、2026-09-08 counterfactual pair 與正式 DB 禁寫界線均以 [產業分類契約](INDUSTRY_CLASSIFICATION.md#4-三種日期與修復邊界) 為準。

R15 的 mapping 與專案外隔離診斷已通過統籌有限 review：supported active stock／ipo 在 current 與 counterfactual 各為 1,974 筆且各有唯一 expected membership，35 筆 unknown／special 均沒有一般產業 membership；正式與 `.local` DB 未變。這不修正本頁所讀的正式 DB，所以「既有族群關聯待重新核實」guard 仍須保留。

## 3. 單位契約

顯示格式固定為最多 3 位小數，移除不必要的尾端零；已知股數一律除以 1,000。這是前端顯示換算，不更動 API、儲存值或研究計算。

| 資料項 | 已證實的來源／儲存語意 | Round14 顯示 | Fail-closed 規則 |
| --- | --- | --- | --- |
| 日成交量 | TWSE `TradeVolume`／成交股數、TPEx `TradingShares`／成交股數；worker 原值寫入 `bar.volume`。 | `原值 ÷ 1,000`，單位「張」，0–3 位小數，不得為負。 | null、非有限值、負值或來源不明時不造 0、不臆算。 |
| 外資／投信／自營商買賣超 | TWSE 與 TPEx 官方日報欄位為買賣超股數；worker 原值寫入籌碼 snapshot。 | `原值 ÷ 1,000`，單位「張」，0–3 位小數，保留正負號。 | null 不補 0；來源／單位 unknown 或 mixed 時不換算。 |
| TWSE 融資增減 | 官方 MI_MARGN 為融資交易單位；程式以今日餘額減前日餘額保存。 | 本輪台股介面以「張」顯示，0–3 位小數，保留正負號。 | 來源無法確認為該官方欄位時，不沿用此換算。 |
| TPEx 融資增減 | 官方欄位明示前／今日融資餘額（張）；程式保存其差額。 | 單位「張」，0–3 位小數，保留正負號。 | null 或未知來源不補值。 |
| 未知／混合來源 | 沒有足夠證據確認單位。 | 顯示「單位待核實」，不提供換算值。 | 不以交易所、symbol 或鄰近欄位推測。 |

官方語意核對入口：[TWSE 三大法人日報 T86](https://www.twse.com.tw/fund/T86?response=html)、[TPEx 三大法人買賣明細](https://www.tpex.org.tw/zh-tw/mainboard/trading/major-institutional/detail/day.html)、[TWSE 融資融券 MI_MARGN](https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=20260814&response=html&selectType=ALL)、[TPEx 市場資訊／融資張數說明](https://www.tpex.org.tw/zh-tw/market-infomation.html)。

## 4. Unknown 與錯誤欄位別名

| 情境 | 分類 | 必須顯示 | 禁止行為 |
| --- | --- | --- | --- |
| API 明確為 null、無來源、缺 bar／chip 或角色 unknown | 真缺資料 | 具體缺少內容與原因；其他可用區塊照常顯示。 | 補成 0、日期、來源或成功狀態。 |
| 不含 timezone 的 datetime | 格式未確認 | `待核實（時間格式未確認）`。 | 猜 UTC、台北時間或發布時間。 |
| 來源 unknown／mixed，無法確認數量單位 | 單位未確認 | `單位待核實`，保留可追溯 raw 值時須明示未換算。 | 以 1,000 換算或套用相鄰資料單位。 |
| 族群成員 endpoint 本來就沒有 action 欄位 | 錯誤欄位別名／未評估 | 不顯示 action 結論；需要時標「此列表未評估」。 | 顯示「尚無研究動作」或「策略判斷資料：待補」。 |
| `meta.data_as_of` 被讀成頂層欄位，或相對報酬鍵名直接露出 | 錯誤欄位別名 | 讀正確日期路徑；顯示「1 日／5 日相對 TAIEX」。 | 把已存在日期顯示成 `—`，或讓匿名 metric key 成為產品文案。 |

## 5. Final review 證據與限制

統籌完成六個 frontend self-test、32 項獨立檢查、TypeScript typecheck 與 production build，均通過。瀏覽器具名核對涵蓋：桌面全站逐頁；320px 新聞與首頁（viewport／scroll width 均 305）；390px 的 2330 K 線、張數及可展開籌碼原值；768px 族群頁的「（既有分類）」；桌面個股研究結論前 warning；320px 的 4804 缺行情。新聞第 1／2／3 頁分別 20／20／18 筆，末頁下一頁 disabled，返回首頁為 20 筆；研究分頁以 Enter 啟用且 `aria-selected=true`。共用 ErrorBox 的中文主提示與原錯誤 details 由統籌 source review 接受；作者最終 runner 全部通過，但不另增加上述 test count。

2026-09-13 Round14 輪末索引已由統籌接受：frontend／docs 刷新成功，相關分區沒有 recorded parse_partial／skipped；backend exact coverage 仍回報 `metadata_changed`，因此只關閉 Round14 的索引待辦，不把 receipt 當功能驗收。

覆蓋頁的 R14 隔離 API `8133` 意外 exit 1 原因仍未確定。R15 另在新唯讀副本重試：四個 in-process `/coverage` 請求皆 200；新 localhost uvicorn 的 `/api/coverage` 為 200、19.455 秒、2,779,888 bytes，隨後 `/api/stocks/TWSE/2330` 亦 200 且服務仍存活。這只能說單次真 HTTP 未重現退出，不涵蓋瀏覽器、併發或長時穩定性，也不倒推 R14 事故原因。正式／`.local` DB 前後 hash、size、mtime 不變；R15 雖已有限 review mapping 與隔離 current／counterfactual 診斷，正式 DB 舊分類、正式 migration 與持倉實寫仍未驗。本文件的 `已 review` 仍只涵蓋 Round14 前端 UX。
