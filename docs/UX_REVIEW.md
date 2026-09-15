# 全站前端 UX 契約與有限 review

更新：2026-09-16。本文只記錄前端資訊架構、文案、單位與互動的有限 review 範圍；現行文案與單位契約見 [UI_COPY_SPEC](UI_COPY_SPEC.md)。這不是整站資料、後端、DB 或 [ROADMAP](ROADMAP.md) 完成聲明。

## 1. 逐頁問題、改法與待驗

| 頁面 | 已採用的處理 | 仍須守住的邊界 |
| --- | --- | --- |
| 全站導覽／列表 | 卡片只留辨識、一個結論、一至兩個核心數字、資料日與詳情；統一「上一頁／下一頁／儲存／庫存」。 | 鍵盤、focus、寬窄版、載入／錯誤／空資料與列表到詳情可操作；紅漲綠跌另有正負號或文字。 |
| 今日、研究清單、行動／庫存 | 第一層為結論與關鍵數字，證據／來源其次，raw 診斷收合。 | 不遺失來源、時間、風險與缺資料原因；持倉實寫不在本 review。 |
| 新聞 | 列表只顯示辨識、摘要、來源與資料日期；全文、時間衝突和 raw 留詳情。 | Event／News 可分辨；unknown 發布時間不補成事件時間。 |
| 族群 | 缺席 action 欄位視為未評估；日期讀 `meta.data_as_of`；相對指標具名；分頁可用。 | 正式 membership 未修復，依第 2 節顯示警示；不得把中文名或 warning 當修復證據。 |
| 個股 | 結論 → 數字 → 證據／來源 → raw；已知股數依第 3 節換算。 | 圖表、tooltip、等效表格與籌碼卡一致；缺 bar／chip、unknown／mixed source 均 fail closed。 |
| 研究／系統／詞彙 | coverage、健康狀態與詞彙置於次要層，主要入口明示可採取動作。 | 故障、來源、資料時間與限制仍可追溯；深連結與返回正常。 |

## 2. 已發現的市場別產業分類缺陷

正式 DB 的舊 membership 與市場別官方 current 表不一致；這是分類資料錯誤，不是翻譯問題。映射、日期邊界、影響範圍與修復規則見 [INDUSTRY_CLASSIFICATION](INDUSTRY_CLASSIFICATION.md)。

正式資料重建完成前：

- 官方產業排行、候選、關聯與衍生研究條件不得採信。
- UI 顯示「既有族群關聯待重新核實」；`display_name` 加「（既有分類）」與待核實 badge，原始 membership 名稱／ID 只在資料說明。
- unknown／special code 不進一般產業排行；局部 mapping 正確不代表舊資料、scores 或候選已修復。
- OHLCV、數量換算與新聞內容不因分類缺陷自動失效。

隔離 current／counterfactual 診斷曾通過有限 review；該次未修改正式與 `.local` DB，分類仍待重建。

## 3. 單位契約

有限 review 已覆蓋股數換算為張、融資維持官方單位、合法 0、unknown／mixed 單位、價格幣別與持倉股／張格式；顯示不改 API、儲存值或研究計算。唯一完整契約見 [UI_COPY_SPEC §10.3–10.4](UI_COPY_SPEC.md#103-張零股)。

## 4. Unknown 與錯誤欄位別名

| 情境 | 必須顯示 | 禁止 |
| --- | --- | --- |
| null、無來源、缺 bar／chip 或 role unknown | 數值格留空，表外列原因；其他區塊照常顯示。 | 補 0、日期、來源、成功狀態或 placeholder。 |
| naive datetime | 「待核實（時間格式未確認）」 | 猜 UTC、台北或發布時間。 |
| 數量來源／單位 unknown 或 mixed | 「單位待核實」 | 除以 1,000 或套用鄰近單位。 |
| endpoint 本來沒有 action 欄位 | 不顯示 action；必要時「此列表未評估」。 | 「尚無研究動作」或「策略判斷資料待補」。 |
| 日期／metric 讀錯路徑 | 讀 `meta.data_as_of`；顯示「1 日／5 日相對 TAIEX」。 | 把既有日期顯示成破折號或露出匿名 key。 |

## 5. Round14 final review 證據與限制

前端 self-test、獨立資料檢查、TypeScript typecheck、production build，以及桌面與 320／390／768px browser 流程已在穩定 source snapshot 通過有限 review。範圍包含新聞分頁、研究 tab、個股 K 線／張數／籌碼 raw、分類警示、空行情與中文錯誤。

正式 membership／migration、持倉實寫與整站資料正確性仍未驗。coverage API 曾有一次未確定原因的程序異常；後續未重現不證明瀏覽器、併發或長時穩定。

## 6. 2026-09-15 獨立 UI 文案維護（已有限 review）

獨立 UI 維護已有限接受繁中、ETF／族群名稱、空值、法人欄名與兩市場官方分點入口；個股案例另覆蓋張數換算、融資原單位、合法 0、MA60 不足、未知幣別、指數／收盤價與中文新聞。記憶體前端測試與 final `npm run build` 通過。

這只代表既有資料的唯讀 UI 案例。正式分點資料集、歷史 coverage、主力身分／排名、完整無障礙、full backend、一般 API startup、正式 DB／部署與 ROADMAP round 均未驗；未執行 migration。既有大型 JavaScript chunk 警告未阻擋此有限 review。
