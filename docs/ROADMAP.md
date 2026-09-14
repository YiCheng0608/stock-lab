# 開發路線與目前能力

更新：2026-09-14。能力依截至 R36 的有限 review 整理；具名驗收以局部邊界解讀。工作 ID 與完成條件見[執行清單](ROADMAP_EXECUTION.md)，角色與接手見[協作紀錄](TASK_COORDINATION.md)。

## 目前進度（2026-09-14 核對）

**仍在補齊 R0，部分 R1 與前端功能已可用；R0–R3 均未整體完成。** R34 的 opt-in worker capture 已提交為 `87b8429`，只接受其有限研究用途。R35 的 member-return identity 與 R36 的 canonical candidate producer／decision lookup 已通過有限 review；backfill typed 相容、API typed 輸出與歷史回算未完成。

| 階段 | 已有能力 | 主要缺口 |
| --- | --- | --- |
| R0：研究基準與時間 | 信心／價位／時間相容語意；ATR 純核心及獨立保存層；有限 migration／startup gate；artifact、離線比較、pure-rule replay、worker capture。 | 完整歷史輸入與 SignalArtifact bridge、ATR worker 接線、新交易計畫、PIT gate、legacy-v2 paired replay。 |
| R1：可靠資料與事件 | 官方行情／法人／融資與 raw、backfill；四來源 registry／capture、兩個有限 consumer；產業期間、停復牌與公司行動局部修正。 | 逐域 coverage／可得時間／修訂、完整公司行動及停復牌、正式舊分類修復、事件群組／摘要、當沖／借券／分點與必要基本面。 |
| R2：候選與交易計畫 | v1 候選、行動摘要、持倉；群組候選 typed producer／decision lookup；個股研究頁與全站 UX 已有限 review。 | Candidate backfill／public API typed identity、完整計畫與成交／退出 lifecycle、成本／tick／gap／流動性、倉位／題材曝險及整合驗收。 |
| R3：AI 與有效性 | 固定規則、追蹤、回測及研究規格。 | 預先定義目標／採用門檻、walk-forward、樣本外／校準、前瞻樣本與模型採用；尚無經驗收 AI 預測或勝率。 |

### 接下來的順序

1. **Candidate backfill typed 相容調查**：R36 已有限 review producer→decision 的 typed identity、score-date／as-of 同身分驗證與保守 legacy selection。下一輪先走 `_candidate_instrument_keys` 實際路徑，盤點所有 consumer，核對 source-date、inactive 與 ID 證明後才核最小修正；legacy backfill 擴大 scope 與 decision selection 語意分開。API typed 輸出另列後續，詳見[產業分類 §9](INDUSTRY_CLASSIFICATION.md#9-群組候選的身分契約)。
2. **R0 接線與比較**：補來源／subject／availability／decision-time 到 SignalArtifact 的橋接、B3-wire、B5b，依依賴完成 B4b 與 B7。
3. **R1 資料與事件**：來源可行性可與 R0 並行；正式分類修復依其自身資料與授權驗收，不被無關 capture 小批阻塞。
4. **R2、R3**：按實際可用來源交付完整計畫／風險，再以預先登錄門檻做模型及前瞻驗證。受限來源只影響依賴它的功能。

## R0 要修正的五件事

| ID | 現況 | 剩餘驗收 |
| --- | --- | --- |
| R0-1 ATR | legacy `atr14` 仍為最近最多 14 根 high-low 平均；Wilder 純核心與 B3-persist 已有限 review，尚未接 worker。 | 官方 session／halt／公司行動／previous-close 與 availability 證據、B3-wire、PIT 及 paired replay。 |
| R0-2 信心與保存輸入 | 新 rule-only confidence 為 null；legacy 0.75 不代表機率。四個 artifact／comparison／replay／capture 小批已有限 review。 | 可證完整歷史輸入、SignalArtifact 及產品接線、legacy-v2 paired output、明確選版；capture receipt 不證來源 truth。 |
| R0-3 價位 | B4a 已標示規則參考價；legacy 目標仍為 1.6R／3R，未換成完整交易計畫。 | B4b：tick 後價位順序、成本、gap、不追價、流動性、期限與不可比情況。 |
| R0-4 時間 | legacy `data_cutoff` 的 T 日 13:30 不證資料當時可得；time-evidence foundation 與產品 read-time projection 分離。 | strict store／worker／產品關聯、`available_at <= decision_at`、live collected-at gate、修訂與 backfill 的 B5b。 |
| R0-5 DB 邊界 | 程式 head 為 `0006_news_json_defaults`；有限 migration、canonical rebuild 與唯讀 startup gates 已 review。外部 preview 曾升級正式 DB，不算正式 migration 驗收。 | 正式 migration／restore／deployment、未支援 historical／custom schema 及服務 reload；startup 通過不代表任意 INSERT 或完整資料驗證。 |

完整規格由 [R0 實作](R0_IMPLEMENTATION.md)負責。後續修正不能沿用 v1 名稱改歷史語意；feature、strategy、execution、presentation 及資料版本須可辨識，預設切換另需 B7 與決策。

## 已接受成果的查閱位置

| 範圍 | 有限成果與主要邊界 | 契約 |
| --- | --- | --- |
| R03／10／11／27–31 | 隔離 migration／restore mechanics、News defaults、canonical instruments／settlements rebuild、readiness identity gates；不等於任意 schema 或正式部署。 | [R0](R0_IMPLEMENTATION.md) |
| R02／04／06–08 | ATR 純核心、immutable provenance store、time-evidence 與 read-time projection；官方 truth／worker／PIT 仍待接。 | [R0](R0_IMPLEMENTATION.md) |
| R12／32／33／34 | immutable Signal artifact、描述比較、caller-input pure replay、owned DB actual worker capture；尚無共同歷史輸入 bridge 或 legacy-v2 paired replay。 | [保存與重播契約](README.md) |
| R13／14 | 個股 K 線／量／MA 與研究流程、單位／unknown／列表至詳情 UX；不是完整交易計畫或績效驗證。 | [個股頁](STOCK_RESEARCH_PAGE.md)、[UX](UX_REVIEW.md) |
| R15–17 | 分類 mapping、ordinary-industry 觀測期間、ETF／new-listing lifecycle；正式錯分類及歷史 PIT 未修復。 | [產業分類](INDUSTRY_CLASSIFICATION.md) |
| R09／18–20 | 四來源用途別 policy 與 standalone capture；consumer 只有 STOCK_DAY_ALL 單日 selected-security 與 holidaySchedule 單年度 positive exclusion。 | [來源 registry](SOURCE_REGISTRY.md) |
| R21–26 | TPEx today code-only、history Serial／split-pair、公司行動 ratio／reference／cash precision；TWSE 既有 action 唯讀來源分類。不是第三個 capture consumer或舊資料修復。 | [來源 registry](SOURCE_REGISTRY.md) |

R34 final targeted 為 52 passed；2,436-pass full suite 對應較早 capture guard，兩者不能互換。正式 DB 當輪 hash 不可得。其餘原始測試、失敗史、雜湊與命令由 Git `69f62cf` 的舊文件及原 task 追溯，不在路線圖重複累積，也不換算成產品完成百分比。

## R1–R3 驗收方向

- **R1**：資料按 exchange／symbol／session／用途查 coverage，unknown 不補零；來源保存／摘要／PIT 分別准入。事件保留原文、首次／更正／撤回及可得時間，去重不丟來源；產業與題材分層且有版本。當沖與借券等逐欄驗單位／修訂；分點無可靠合法歷史即受限；基本面只補研究所需。
- **R2**：公司品質、事件機會、交易位置、持倉風險分開；計畫涵蓋 trigger／fill、進場區間、不追價、失效、目標、期限、成本與流動性。可輸出不交易／到期／無法成交；同日 stop／target 無順序不可偏向有利結果，同股多策略／題材不重複占用曝險。
- **R3**：先定 target、持有窗口、成本、split、校準與採用門檻，再比較固定技術＋題材＋新聞＋籌碼＋AI 的增量；walk-forward／OOS 與前瞻按當時 universe／membership／資料版本執行。LLM 摘要不等於策略增益；模型 cutoff 不明的歷史分析僅探索。樣本與市場狀態不足保持等待，未校準不給機率。

## 產品取捨與待決定事項

| 項目 | 現行處理 |
| --- | --- |
| 使用情境 | 暫以盤後 long、最早 T+1、數天至數週設計；精確期間與做空待決。T+5／T+20 是追蹤窗口，不是必然退出日。 |
| 風險預算 | 未知時不預填個人比例或具體張數；一般研究方案可先版本化設計。 |
| 來源／AI | 免費公開來源先做可行性；供應商、預算、歷史權限、部署、成本／隱私未選定。預測／採用門檻在看測試結果前記錄。 |
| 資訊審核 | 來源准入、逐項證據及高風險／低把握覆核；不要求每則合格摘要一律人工點選。 |
| 保留加強 | 來源／時間／品質追溯、策略版本、回測、模擬追蹤、持倉風險、新聞、族群、個股頁。raw／run／coverage／原因碼／完整公式留研究後台。 |
| 降低新增優先 | 全 ETF 專用策略、完整財務記帳、大量新指標、細碎呈現改版；既有相容能力保留。 |
| 第一版不含 | 盤中即時交易、自動下單、無來源 AI 報價、未驗證勝率、確定身分的「隔日沖主力」標籤。 |

資料收集排程與交易自動化分開：前者依來源可靠性、重試與觀測驗收，不以策略績效作前置；實際排程及交易各須明確操作授權。
