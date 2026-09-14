# Round14 全站前端 UX review（已 review）

更新：2026-09-14。這是 Round14 前端資訊架構、文案、單位換算與互動的有限 review，不是整站資料、後端、DB 或 ROADMAP 完成聲明。未新增 API `units`、來源、付費服務或策略能力。

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

這是正式資料的分類錯誤，不是翻譯問題。TWSE／TPEx shared code 無異義 collision；差異在市場專屬、停用及特殊碼。正式 DB 仍有大量舊 membership 不符官方 current 表，例如 TPEx 3176 raw industry 22 被連到 Shipping。完整 current／歷史映射、日期邊界、影響數量與修復規則見 [INDUSTRY_CLASSIFICATION](INDUSTRY_CLASSIFICATION.md)。

正式資料重建完成前：

- 官方產業排行、候選、關聯與衍生研究條件不得採信。
- UI 顯示「既有族群關聯待重新核實」；`display_name` 加「（既有分類）」與待核實 badge，原始 membership 名稱／ID 只在資料說明。
- unknown／special code 不進一般產業排行；單一 mapping 正確不代表舊資料、scores 或候選已修復。
- OHLCV、數量換算與新聞內容不因分類缺陷自動失效。

隔離 current／counterfactual 診斷曾通過有限 review，正式與 `.local` DB 未變，因此上述 guard 仍有效。

## 3. 單位契約

格式最多 3 位小數並移除尾端零；顯示換算不改 API、儲存值或研究計算。

| 資料 | 顯示 | Fail closed |
| --- | --- | --- |
| TWSE／TPEx 日成交股數 | `原值 / 1,000`，單位「張」，不得為負。 | null、非有限、負值或來源不明時不造 0。 |
| 外陸資／投信／自營商買賣超股數 | `原值 / 1,000`，單位「張」，保留正負號。 | null、unknown／mixed source 不換算。 |
| TWSE 融資增減 | 已核實官方欄位在台股 UI 以「張」顯示。 | 無法確認來源時不沿用。 |
| TPEx 融資餘額差 | 單位「張」，保留正負號。 | null 或來源未知不補值。 |
| unknown／mixed | 「單位待核實」；raw 若可見須標未換算。 | 不由交易所、symbol 或鄰近欄位猜單位。 |

持倉的 canonical quantity 是精確整數股；250、1,000、1,250 股分別顯示「250 股（零股）」「1 張」「1 張 250 股」，平均成本仍為每股。完整文案見 [UI_COPY_SPEC](UI_COPY_SPEC.md#103-張零股)。

## 4. Unknown 與錯誤欄位別名

| 情境 | 必須顯示 | 禁止 |
| --- | --- | --- |
| null、無來源、缺 bar／chip 或 role unknown | 具體缺項與原因，其他區塊照常顯示。 | 補 0、日期、來源或成功狀態。 |
| naive datetime | 「待核實（時間格式未確認）」 | 猜 UTC、台北或發布時間。 |
| 數量來源／單位 unknown 或 mixed | 「單位待核實」 | 除以 1,000 或套用鄰近單位。 |
| endpoint 本來沒有 action 欄位 | 不顯示 action；必要時「此列表未評估」。 | 「尚無研究動作」或「策略判斷資料待補」。 |
| 日期／metric 讀錯路徑 | 讀 `meta.data_as_of`；顯示「1 日／5 日相對 TAIEX」。 | 把既有日期顯示成破折號或露出匿名 key。 |

## 5. Final review 證據與限制

2026-09-13 統籌對穩定 source snapshot 完成前端 self-test、獨立資料檢查、TypeScript typecheck、production build，以及桌面與 320／390／768px 的具名 browser 流程；新聞分頁、研究 tab、個股 K 線／張數／籌碼 raw、族群「（既有分類）」警示、空行情和中文 ErrorBox 均在有限範圍通過。輪末 frontend／docs 索引 receipt 已接受。原測試次數、viewport 數值、hash 與命令可查 `git show 69f62cf:docs/UX_REVIEW.md`。

此 review 只涵蓋 Round14 前端。正式產業 membership、正式 migration、持倉實寫與整站資料正確性仍未驗；一次 coverage API 程序異常退出的原因未確定，後續單次 in-process／HTTP 200 只表示未重現，不證明瀏覽器、併發或長時穩定。索引成功也不是功能驗收。
