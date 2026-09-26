# 協作與接手狀態

本文件只留目前角色、接手與下一步；流程依 [AGENTS](../AGENTS.md)，能力與優先順序查 [ROADMAP](ROADMAP.md)。

## 目前狀態（2026-09-27）

- 本輪進行 [R0-B2 Bridge B](ROADMAP_EXECUTION.md#r0-b版本化-artifact-與-atr) 的 opt-in selected bar close／volume 本地 metadata 接線。程式五檔交付已由統籌有限 review：capture v2 依 receipt kind 封存 selected bar 與 raw metadata，Bridge B 依 v1/v2 產 detached candidate；caller save 仍須明示。文件接受、freeze、索引與 commit 的實際狀態及最終 receipt 以本輪統籌 task 為準。
- R0-B2／R0 整體仍未完成。其餘衍生輸入來源／版本、真正 raw bytes、availability／歷史 decision、PIT、consumer、同 snapshot legacy-v2 paired replay 與預設切換均未驗收或核定；實際限制見 [Signal artifact §10–11](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與下一候選)。本輪程式驗證屬小型 synthetic owned research DB 邊界，不能證正式資料或磁碟峰值。
- R35–38 的成員與候選身分、回補範圍、來源日展示維持各自的有限 review；完整歷史回算與 PIT 仍缺，細節見[產業分類 §8–9](INDUSTRY_CLASSIFICATION.md#8-群組衍生成員報酬的身分契約有限-review)。獨立 UI 維護成果與[籌碼三部分](STOCK_RESEARCH_PAGE.md#8-籌碼三部分後續待做)的待做範圍不因本輪改變。

### 本輪角色與寫入分工

| 角色 | task ID／model／reasoning | 寫入／驗收範圍 |
| --- | --- | --- |
| 統籌 | `01a0de5b-67e3-7f00-a75a-d8f7b5fa47fc`；`gpt-6-astra`／`high` | 核定 selected bar 接線範圍、程式與文件 review、freeze、索引及 commit 准入。 |
| 程式 | `01a0de5b-66ef-7422-97a9-306b35cc9240`；`gpt-6-sol`／`ultra` | `backend/worker/analysis_capture.py`、`pipeline.py`、`signal_artifact_bridge.py` 與兩份對應測試；不改規格。 |
| 文件 | `01a0de5b-65e4-77e3-be22-cc508465d9cd`；`gpt-6-sol`／`xhigh` | 本輪受影響的 Signal artifact、worker capture、ROADMAP／執行清單與本交接；不改程式。 |
| 索引與 Git commit | `01a0de5b-6900-78f2-aadc-de22f489476d`；`gpt-6-luna`／`medium` | 統籌 freeze 後更新索引、驗 coverage，並提交核准檔案；不改來源。 |

## 接續範圍

1. 已完成及驗收邊界：既有 Bridge B 接受 explicit capture→candidate adapter；本輪新模式 `selected-bar/v1` 將 selected bar close／volume 的本地列與 raw metadata 關係封存成 v2 capture，bridge 產對應 v2 input manifest／candidate。候選不自動保存；小型 synthetic owned DB 的測試與清理具名證據、限制留各 task。
2. 尚缺項：其餘衍生輸入來源與版本、真正 raw bytes 與來源真實性、可得時間、歷史 decision／PIT、完整歷史輸入、consumer 與同 snapshot paired output；R0-B2／R0 不得據此標完成。
3. 下一步與依賴／完成條件：下一個最小候選可評估其餘衍生輸入的可封存來源關係及真正 raw bytes／版本證據，須由後續統籌另核；availability／historical input、B3-wire、B5b、B7 等仍依各自 gate。Consumer、paired replay、預設切換不由本輪預核。本輪完成指定流程後待命，不自行結案或啟動下一輪。
4. Freeze／索引／commit：統籌接受文件並 freeze 後，才由索引角色更新涉及分區與 coverage；統籌複核並核准檔案後才本地 commit。結果與 hash 留統籌 task，不預寫完成 receipt。

## 歷史與維護

舊角色 ID、交付狀態、測試及 commit 證據由[Git／原 task](README.md#歷史查閱)追溯；舊分派不覆蓋 AGENTS，也不恢復已刪除附件或舊統籌派工權。更新本文件時替換目前狀態，不追加逐輪日誌。
