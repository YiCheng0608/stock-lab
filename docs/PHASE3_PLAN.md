# Phase 3：資料補齊、族群研究與新聞治理

> 歷史文件；2026-09-11 起不再作派工、完成度或現況依據。現行優先順序只看 [ROADMAP](ROADMAP.md)，本文件不會恢復 Phase 3。

## 歷史定位與原目標

Phase 3 原本要在有限、可稽核的官方資料中，建立用途別 coverage、可發布熱門族群、可研究個股行動，以及受治理的官方新聞。它要求缺值保持 unknown、失敗 fail closed、資料與策略結果可追溯；有限案例與短樣本不代表策略有效。

其獨有邊界是：不做無界歷史回填、不以其他標的補 IPO 歷史、不把 endpoint failure／錯日／缺日改成最近日或 0、不讓未核准媒體或未核實 AI 關聯進正式理由，也不因本計畫授權排程、正式 DB 或來源採購。

## 現行文件

| 主題 | 現行文件 |
| --- | --- |
| 產品範圍、候選與行動合併 | [PRODUCT_SPEC](PRODUCT_SPEC.md) |
| v1 公式、eligibility、hot-group、tracking | [V1_SPEC](V1_SPEC.md) |
| Coverage、日期範圍與已驗結果 | [DATA_SOURCES](DATA_SOURCES.md) |
| 收集、重試、DB 與執行安全 | [OPERATIONS](OPERATIONS.md) |
| Taxonomy 與 membership | [INDUSTRY_CLASSIFICATION](INDUSTRY_CLASSIFICATION.md) |
| 新聞來源、時間、去重與 AI 覆核 | [NEWS_SPEC](NEWS_SPEC.md) |
| 中文、完整度、空狀態與原因碼 | [UI_COPY_SPEC](UI_COPY_SPEC.md) |
| 現況、未完成項與排程 | [ROADMAP](ROADMAP.md)、[ROADMAP_EXECUTION](ROADMAP_EXECUTION.md) |

## 仍未決事項

- 媒體／國際／總體來源的授權、白名單、保存範圍、覆核責任與服務水準。
- 可按交易日核實的事件來源、taxonomy 審核責任，以及可供 hot-group 使用的事件 coverage。
- 正式執行資源／頻率、資料保留與可見範圍；未決前不自行啟用來源、排程或正式資料操作。
- 進入 walk-forward／獨立 OOS 的條件；單日案例與有限歷史 coverage 不構成採用證據。

## Git 取閱

原 P0/P1 順序、coverage 數字、批次／retry 設計、驗收矩陣與逐輪證據可用 `git show 69f62cf7b9e9003c3878952cc33636ed9a063865:docs/PHASE3_PLAN.md` 取閱；它們是歷史紀錄，不能覆蓋上述現行文件。
