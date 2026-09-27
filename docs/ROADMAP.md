# 開發路線與目前能力

更新：2026-09-27。本文件管能力、優先順序與待決事項；工作 ID／完成條件見[執行清單](ROADMAP_EXECUTION.md)，接手與暫停狀態見[協作紀錄](TASK_COORDINATION.md)。

## 目前進度（2026-09-27 核對）

**R0–R3 均未整體完成。** 下表依既有有限驗收、opt-in prior volumes 本地列接線、獨立 selected-bar verifier，以及 B4b／B5b 各自 caller-input 純核心的有限 review 整理；verifier 只判定指定本地證據一致，尚無實際檔案／snapshot 整合驗收或既有流程接線。相關回歸仍待補，見[協作紀錄](TASK_COORDINATION.md)。

| 階段 | 已有能力 | 主要缺口 |
| --- | --- | --- |
| R0：研究基準與時間 | 信心／價位／時間相容語意；ATR 純核心及獨立保存層；有限 migration／startup gate；artifact、離線比較、pure-rule replay、worker capture、Bridge B opt-in candidate adapter；selected bar close／volume 與 prior volumes 最多 20 筆本地 metadata 關係；獨立 `STOCK_DAY_ALL` selected-bar 本地證據一致性 verifier；B4b 事後假設與 B5b caller-declared time-cutoff 各有純核心有限 review。 | 待跑回歸與 verifier 真實 tuple 整合、其餘衍生輸入、歷史原件／來源版本與 availability／歷史決策證據、artifact consumer、ATR worker 接線、完整 B4b 的官方 tick／費稅／日曆、完整 B5b 的實際依賴與來源／PIT gate、產品／持久化接線與 legacy-v2 paired replay。 |
| R1：可靠資料與事件 | 官方行情／法人／融資與 raw、backfill；四來源 registry／capture、兩個有限 consumer；TAIEX 身分窄修正與 TWSE／TPEx 成交額 availability 已各有限接受；產業期間、停復牌與公司行動局部修正。 | 成交額的磁碟 capture／legacy migration 與正式 DB 升級待驗；逐市場／逐欄 coverage、TAIEX 合成 OHLC／量額與成交量小數截整、可得時間／修訂、完整公司行動及停復牌、正式舊分類修復、事件群組／摘要、當沖／借券／分點資料與必要基本面仍缺。免費官方分點人工查詢入口不等於已接資料集。 |
| R2：候選與交易計畫 | v1 候選、行動摘要、持倉；群組候選身分、回補範圍及來源日展示；個股研究頁、繁中、表外單位與官方分點入口。 | 歷史身分／PIT、完整計畫與成交／退出流程、成本／tick／gap／流動性、倉位／題材曝險及整合驗收。 |
| R3：AI 與有效性 | 固定規則、追蹤、回測及研究規格。 | 預先定義目標／採用門檻、walk-forward、樣本外／校準、前瞻樣本與模型採用；尚無經驗收 AI 預測或勝率。 |

**籌碼三區仍待做**：三大法人沿用已有資料；主力進出與券商分點的交易匯入、統計、排行／歷史及自動更新尚未完成。定義見[個股頁 §8](STOCK_RESEARCH_PAGE.md#8-籌碼三部分後續待做)。

### 接下來的順序

1. **R0-B2 SignalArtifact bridge B**：A 的映射／缺口、B 的 capture→candidate adapter、opt-in selected bar 與 prior volumes 本地 metadata 接線，以及獨立 `STOCK_DAY_ALL` selected-bar verifier 均只有有限 review；candidate 與 caller save 分離，verifier 不改既有 `bytes_unverified`。下一步尋找已授權可唯讀的 research snapshot／body／receipt／registry pins tuple，驗獨立 verifier 的實際整合；若缺 specimen 或 pins 則保持待驗，不建附件或 fixture。可行的未跑回歸仍待補；必要磁碟驗證須待[協作紀錄](TASK_COORDINATION.md)所述配額條件解除。歷史原件／上游版本及 availability／historical decision 待證；prior volumes 不升格，consumer、paired replay 與預設切換均未核定。精確缺口見 [Signal artifact §10](SIGNAL_ARTIFACTS.md#10-bridge-a-可證映射與-bridge-b-有限成果)。
2. **R0 其餘接線與比較**：依來源與時間證據核定 B3-wire、B5b 的實際整合，並接續 B4b／B5b 已有限 review 的 caller-input 純核心所缺的來源／PIT、完整依賴與 B7 paired replay；純核心結果不證來源真實性、成交或 paired output。
3. **R1 資料與事件**：來源可行性可與 R0 並行；正式分類修復依其自身資料與授權驗收，不被無關 capture 小批阻塞。
4. **R2、R3**：按實際可用來源交付完整計畫／風險，再以預先登錄門檻做模型及前瞻驗證。受限來源只影響依賴它的功能。

## R0 要修正的五件事

| ID | 現況 | 剩餘驗收 |
| --- | --- | --- |
| R0-1 ATR | Wilder 純核心與保存層已有限 review；worker 仍用 legacy 算法。 | 官方輸入與可得時間、B3-wire、PIT 及新舊重播比較。 |
| R0-2 信心與保存輸入 | 新固定規則 confidence 為 null；legacy 值不代表機率。保存、比較、replay、capture、bridge A、B adapter、selected bar 與 prior volumes 本地 metadata 關係及獨立 selected-bar 本地證據 verifier 各有有限成果。 | 待跑回歸與 verifier 真實 tuple 整合、逐輸入歷史原件／上游版本、availability／完整歷史輸入、consumer／產品接線、同 snapshot 新舊 paired replay 與選版。 |
| R0-3 價位 | 已標規則參考價；B4b caller-input 純核心有限 review 可對盤後 long 假設檢查 tick、成本、gap、不追價、流動性、期限及日線先後未知，結果不主張 PIT 或成交。 | 完整 B4b 的官方 tick／費稅／交易日曆、來源與 availability／PIT、持久化及 worker／API／UI、完整 legacy replay／新舊逐欄 paired comparison；尚未形成產品交易計畫。 |
| R0-4 時間 | 已有時間保存與顯示基礎，兩者尚未接通；B5b 的 caller-declared time-cutoff 純核心有限 review 能檢查精確配對輸入的首次可得／修訂／live 收集時間，但不證來源真實性或完整依賴。 | Store／worker／產品關聯、實際來源與歷史決策證據、完整 B5b／PIT gate、修訂與回補整合。 |
| R0-5 DB 邊界 | 有限 migration、canonical rebuild 與唯讀 startup gates 已 review。 | 正式 migration／restore／deployment、未支援 schema 及服務 reload。 |

算法、schema 與驗收限制由 [R0 實作](R0_IMPLEMENTATION.md)負責。修正須辨識 feature、strategy、execution、presentation 及資料版本，不沿用 v1 名稱改歷史語意；預設切換另需 B7 與決策。

## 已接受成果的查閱位置

具名工作狀態見[執行清單](ROADMAP_EXECUTION.md)，細節按[文件索引](README.md)查各契約。歷史測試數、命令與提交證據由 Git／原 task 追溯，不換算成產品完成百分比。

## R1–R3 驗收方向

- **R1**：逐市場、標的、日期與用途驗來源／coverage；成交額缺失／無效依已選契約以數值 `0` 另存 `unavailable` 與原因，不能當有效零，其餘 unknown 不補零。完整條件見[資料來源](DATA_SOURCES.md)、[新聞](NEWS_SPEC.md)與[產業分類](INDUSTRY_CLASSIFICATION.md)。
- **R2**：分開公司品質、事件機會、交易位置與持倉風險；交付可拒絕交易的完整計畫，見[產品規格](PRODUCT_SPEC.md)。
- **R3**：先定目標與採用門檻，再驗增量、樣本外與前瞻；樣本不足保持等待，未校準不給機率，見[策略驗證](STRATEGIES.md)。

## 產品取捨與待決定事項

| 項目 | 現行處理 |
| --- | --- |
| 成交額缺值 | 已選定保留有效 OHLC／volume，缺失或無效成交額數值存 `0` 並另存狀態／原因；明確來源零才是可用零。有限實作與待驗邊界見 [R1-A2](ROADMAP_EXECUTION.md#4-r1可靠資料與事件)。 |
| 使用情境 | 暫以盤後 long、最早 T+1、數天至數週設計；精確期間與做空待決。T+5／T+20 是追蹤窗口，不是必然退出日。 |
| 風險預算 | 未知時不預填個人比例或具體張數；一般研究方案可先版本化設計。 |
| 來源／AI | 免費公開來源先做可行性；供應商、預算、歷史權限、部署、成本／隱私未選定。預測／採用門檻在看測試結果前記錄。 |
| 資訊審核 | 來源准入、逐項證據及高風險／低把握覆核；不要求每則合格摘要一律人工點選。 |
| 保留加強 | 來源／時間／品質追溯、策略版本、回測、模擬追蹤、持倉風險、新聞、族群、個股頁。raw／run／coverage／原因碼／完整公式留研究後台。 |
| 降低新增優先 | 全 ETF 專用策略、完整財務記帳、大量新指標、細碎呈現改版；既有相容能力保留。 |
| 第一版不含 | 盤中即時交易、自動下單、無來源 AI 報價、未驗證勝率、確定身分的「隔日沖主力」標籤。 |

資料收集排程與交易自動化分開：前者依來源可靠性、重試與觀測驗收，不以策略績效作前置；實際排程及交易各須明確操作授權。
